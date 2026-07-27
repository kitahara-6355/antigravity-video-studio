import sys
import os
import types
import importlib.util

# backend.routers のインポートエラーを防ぐため sys.modules にダミーのモジュールを作成し__init__.pyをバイパスする
routers_module = types.ModuleType('backend.routers')
routers_module.__path__ = [os.path.abspath(os.path.join(os.path.dirname(__file__), '../routers'))]
sys.modules['backend.routers'] = routers_module

# backend.routers.error_schemas を明示的にロードする
module_name = 'backend.routers.error_schemas'
file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../routers/error_schemas.py'))
spec = importlib.util.spec_from_file_location(module_name, file_path)
error_schemas = importlib.util.module_from_spec(spec)
sys.modules[module_name] = error_schemas
spec.loader.exec_module(error_schemas)

# インポートを実施
from backend.routers.error_schemas import (
    ErrorCode,
    ErrorDetail,
    StandardErrorResponse,
    create_error_response,
    global_exception_handler,
    http_exception_handler,
    register_error_handlers,
    _extract_request_id,
)

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse
from datetime import datetime
from unittest.mock import patch

# 1. ErrorCode Enumのテスト
def test_error_code_values():
    assert ErrorCode.INTERNAL_ERROR == "INTERNAL_ERROR"
    assert ErrorCode.VALIDATION_ERROR == "VALIDATION_ERROR"
    assert ErrorCode.NOT_FOUND == "NOT_FOUND"
    assert ErrorCode.UNAUTHORIZED == "UNAUTHORIZED"
    assert ErrorCode.FORBIDDEN == "FORBIDDEN"
    assert ErrorCode.PROCESSING_FAILED == "PROCESSING_FAILED"
    assert ErrorCode.AI_ERROR == "AI_ERROR"
    assert ErrorCode.FILE_ERROR == "FILE_ERROR"
    assert ErrorCode.WEBSOCKET_ERROR == "WEBSOCKET_ERROR"


# 2. ErrorDetail Pydanticモデル
def test_error_detail_validation():
    # 正常系
    detail = ErrorDetail(field="username", message="Username is required", code="REQUIRED")
    assert detail.field == "username"
    assert detail.message == "Username is required"
    assert detail.code == "REQUIRED"

    # オプションフィールドの省略
    detail_min = ErrorDetail(message="Generic error")
    assert detail_min.field is None
    assert detail_min.code is None
    assert detail_min.message == "Generic error"


# 3. StandardErrorResponse Pydanticモデル
def test_standard_error_response_validation():
    now_str = datetime.now().isoformat()
    response = StandardErrorResponse(
        error="An error occurred",
        code=ErrorCode.INTERNAL_ERROR,
        timestamp=now_str,
        request_id="req-123",
        details=[ErrorDetail(field="test", message="detail message")]
    )
    assert response.success is False
    assert response.error == "An error occurred"
    assert response.code == ErrorCode.INTERNAL_ERROR
    assert response.timestamp == now_str
    assert response.request_id == "req-123"
    assert len(response.details) == 1
    assert response.details[0].field == "test"


# 4. create_error_response のテスト
def test_create_error_response():
    # details と request_id を指定
    details = [ErrorDetail(field="email", message="Invalid email")]
    response = create_error_response(
        code=ErrorCode.VALIDATION_ERROR,
        message="Validation failed",
        status_code=400,
        details=details,
        request_id="req-456"
    )
    
    assert response.status_code == 400
    import json
    data = json.loads(response.body.decode("utf-8"))
    
    assert data["success"] is False
    assert data["error"] == "Validation failed"
    assert data["code"] == "VALIDATION_ERROR"
    assert data["request_id"] == "req-456"
    assert len(data["details"]) == 1
    assert data["details"][0]["field"] == "email"
    assert "timestamp" in data


# 5. 例外ハンドラ検証用のFastAPIアプリ
@pytest.fixture
def test_app():
    app = FastAPI()
    
    @app.get("/trigger-exception")
    def trigger_exception():
        raise Exception("Unhandled test exception")
        
    @app.get("/trigger-http-exception/{status_code}")
    def trigger_http_exception(status_code: int):
        raise HTTPException(status_code=status_code, detail=f"HTTP Error {status_code}")

    register_error_handlers(app)
    return app


# 6. global_exception_handler と http_exception_handler の動作検証
def test_global_exception_handler(test_app):
    # TestClientで例外ハンドラ経由の挙動を検証
    client = TestClient(test_app, raise_server_exceptions=False)
    
    # X-Request-IDなし
    response = client.get("/trigger-exception")
    assert response.status_code == 500
    data = response.json()
    assert data["success"] is False
    assert data["code"] == "INTERNAL_ERROR"
    assert data["error"] == "予期せぬエラーが発生しました"
    assert data["request_id"] is None
    
    # X-Request-IDあり
    response_with_id = client.get("/trigger-exception", headers={"X-Request-ID": "req-789"})
    assert response_with_id.status_code == 500
    data_with_id = response_with_id.json()
    assert data_with_id["request_id"] == "req-789"


def test_http_exception_handler_mapping(test_app):
    client = TestClient(test_app, raise_server_exceptions=False)
    
    # 400 Validation Error
    response = client.get("/trigger-http-exception/400", headers={"X-Request-ID": "id-400"})
    assert response.status_code == 400
    data = response.json()
    assert data["code"] == "VALIDATION_ERROR"
    assert data["error"] == "HTTP Error 400"
    assert data["request_id"] == "id-400"

    # 401 Unauthorized
    response = client.get("/trigger-http-exception/401")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"

    # 403 Forbidden
    response = client.get("/trigger-http-exception/403")
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"

    # 404 Not Found
    response = client.get("/trigger-http-exception/404")
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"

    # 500 Internal Error
    response = client.get("/trigger-http-exception/500")
    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"

    # マッピング未登録のHTTPステータス: 418 I'm a teapot -> INTERNAL_ERROR としてフォールバック
    response = client.get("/trigger-http-exception/418")
    assert response.status_code == 418
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert response.json()["error"] == "HTTP Error 418"


# 7. _extract_request_id のテスト
def test_extract_request_id_helper():
    class DummyRequest:
        def __init__(self, headers):
            self.headers = headers
            
    req_with_id = DummyRequest({"X-Request-ID": "test-id-123"})
    assert _extract_request_id(req_with_id) == "test-id-123"
    
    req_without_id = DummyRequest({})
    assert _extract_request_id(req_without_id) is None


# 8. 堅牢化した _extract_request_id のテスト
def test_extract_request_id_robustness():
    # requestがNone
    assert _extract_request_id(None) is None
    
    # headers属性を持たないオブジェクト
    class EmptyRequest:
        pass
    assert _extract_request_id(EmptyRequest()) is None

    # headersがgetメソッドを持たないオブジェクト
    class InvalidHeadersRequest:
        def __init__(self):
            self.headers = "not-a-dict-or-headers-object"
    assert _extract_request_id(InvalidHeadersRequest()) is None


# 9. global_exception_handler の HTTPException 委譲テスト
@pytest.mark.asyncio
async def test_global_exception_handler_delegation():
    class DummyRequest:
        def __init__(self, headers):
            self.headers = headers
            
    req = DummyRequest({})
    exc = HTTPException(status_code=400, detail="HTTP Error for delegation")
    
    resp = await global_exception_handler(req, exc)
    assert resp.status_code == 400
    
    import json
    data = json.loads(resp.body.decode("utf-8"))
    assert data["success"] is False
    assert data["code"] == "VALIDATION_ERROR"
    assert data["error"] == "HTTP Error for delegation"


# 10. http_exception_handler の構造化エラー詳細のパーステスト
@pytest.mark.asyncio
async def test_http_exception_handler_structured_detail():
    class DummyRequest:
        def __init__(self, headers):
            self.headers = headers
            
    req = DummyRequest({})
    import json
    
    # detailが辞書の場合
    detail_dict = {"message": "Invalid password", "field": "password", "code": "PASSWORD_TOO_SHORT"}
    exc_dict = HTTPException(status_code=400, detail=detail_dict)
    resp_dict = await http_exception_handler(req, exc_dict)
    
    assert resp_dict.status_code == 400
    data_dict = json.loads(resp_dict.body.decode("utf-8"))
    assert data_dict["error"] == "Invalid password"
    assert len(data_dict["details"]) == 1
    assert data_dict["details"][0]["field"] == "password"
    assert data_dict["details"][0]["message"] == "Invalid password"
    assert data_dict["details"][0]["code"] == "PASSWORD_TOO_SHORT"
    
    # detailがリストの場合
    detail_list = [
        {"message": "Required", "field": "email", "code": "REQUIRED"},
        "plain text detail error"
    ]
    exc_list = HTTPException(status_code=400, detail=detail_list)
    resp_list = await http_exception_handler(req, exc_list)
    
    assert resp_list.status_code == 400
    data_list = json.loads(resp_list.body.decode("utf-8"))
    assert data_list["error"] == "HTTP error occurred"
    assert len(data_list["details"]) == 2
    assert data_list["details"][0]["field"] == "email"
    assert data_list["details"][0]["message"] == "Required"
    assert data_list["details"][0]["code"] == "REQUIRED"
    assert data_list["details"][1]["field"] is None
    assert data_list["details"][1]["message"] == "plain text detail error"
