import logging
import time
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from backend.logging_middleware import (
    RequestLoggingMiddleware,
    SlowRequestMiddleware,
    setup_logging_middleware,
)

# 1. 正常系テスト (FastAPI統合テスト)
def test_request_logging_middleware_success(caplog):
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/success")
    def success_endpoint():
        return {"status": "ok"}

    client = TestClient(app)
    
    caplog.clear()
    caplog.set_level(logging.INFO)
    
    response = client.get("/success")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert "X-Response-Time" in response.headers
    
    # ログメッセージの検証
    log_records = [r.message for r in caplog.records if r.name == "api.requests"]
    assert len(log_records) >= 2
    assert any("→ GET /success" in msg for msg in log_records)
    assert any("← 200" in msg for msg in log_records)

# 2. HTTPException を投げた場合のテスト (既知の例外)
def test_request_logging_middleware_http_exception(caplog):
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/http-error")
    def http_error_endpoint():
        raise HTTPException(status_code=400, detail="Bad Request Details")

    client = TestClient(app)
    
    caplog.clear()
    caplog.set_level(logging.ERROR)
    
    response = client.get("/http-error")
    assert response.status_code == 400

# 3. ユニットテストでの例外ハンドリングの直接検証 (カバレッジ100%保証のため)
@pytest.mark.asyncio
async def test_request_logging_middleware_direct_dispatch_exceptions(caplog):
    middleware = RequestLoggingMiddleware(app=None)
    
    # 正常系 (clientがNoneの場合もカバー)
    mock_request_no_client = MagicMock(spec=Request)
    mock_request_no_client.method = "POST"
    mock_request_no_client.url.path = "/test-path"
    mock_request_no_client.client = None
    
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.headers = {}
    
    async def mock_call_next_success(req):
        return mock_response
        
    caplog.clear()
    caplog.set_level(logging.INFO)
    
    res = await middleware.dispatch(mock_request_no_client, mock_call_next_success)
    assert res == mock_response
    assert "X-Request-ID" in res.headers
    assert "X-Response-Time" in res.headers
    
    log_records = [r.message for r in caplog.records if r.name == "api.requests"]
    assert any("→ POST /test-path from unknown" in msg for msg in log_records)
    assert any("← 201" in msg for msg in log_records)

    # HTTPException を投げた場合
    async def mock_call_next_http_exc(req):
        raise HTTPException(status_code=403, detail="Forbidden")
        
    caplog.clear()
    caplog.set_level(logging.ERROR)
    
    with pytest.raises(HTTPException) as exc_info:
        await middleware.dispatch(mock_request_no_client, mock_call_next_http_exc)
    assert exc_info.value.status_code == 403
    
    # エラーログが出力されていないこと（HTTPExceptionはエラーログ出力対象外）
    assert not any("✕ Error" in r.message for r in caplog.records)

    # ValueError を投げた場合
    async def mock_call_next_val_exc(req):
        raise ValueError("Something went wrong")
        
    caplog.clear()
    caplog.set_level(logging.ERROR)
    
    with pytest.raises(ValueError, match="Something went wrong"):
        await middleware.dispatch(mock_request_no_client, mock_call_next_val_exc)
        
    log_records = [r.message for r in caplog.records if r.name == "api.requests"]
    assert any("✕ ValueError: Something went wrong" in msg for msg in log_records)
    assert any(r.exc_info is not None for r in caplog.records if "✕ ValueError" in r.message)

    # RuntimeError を投げた場合
    async def mock_call_next_run_exc(req):
        raise RuntimeError("Runtime fail")
        
    caplog.clear()
    caplog.set_level(logging.ERROR)
    
    with pytest.raises(RuntimeError, match="Runtime fail"):
        await middleware.dispatch(mock_request_no_client, mock_call_next_run_exc)
        
    log_records = [r.message for r in caplog.records if r.name == "api.requests"]
    assert any("✕ RuntimeError: Runtime fail" in msg for msg in log_records)
    assert any(r.exc_info is not None for r in caplog.records if "✕ RuntimeError" in r.message)

    # KeyError を投げた場合
    async def mock_call_next_key_exc(req):
        raise KeyError("missing_key")
        
    caplog.clear()
    caplog.set_level(logging.ERROR)
    
    with pytest.raises(KeyError, match="missing_key"):
        await middleware.dispatch(mock_request_no_client, mock_call_next_key_exc)
        
    log_records = [r.message for r in caplog.records if r.name == "api.requests"]
    assert any("✕ KeyError: 'missing_key'" in msg for msg in log_records)
    assert any(r.exc_info is not None for r in caplog.records if "✕ KeyError" in r.message)

    # TypeError を投げた場合
    async def mock_call_next_type_exc(req):
        raise TypeError("Invalid type")
        
    caplog.clear()
    caplog.set_level(logging.ERROR)
    
    with pytest.raises(TypeError, match="Invalid type"):
        await middleware.dispatch(mock_request_no_client, mock_call_next_type_exc)
        
    log_records = [r.message for r in caplog.records if r.name == "api.requests"]
    assert any("✕ TypeError: Invalid type" in msg for msg in log_records)
    assert any(r.exc_info is not None for r in caplog.records if "✕ TypeError" in r.message)

    # AttributeError を投げた場合
    async def mock_call_next_attr_exc(req):
        raise AttributeError("Attribute missing")
        
    caplog.clear()
    caplog.set_level(logging.ERROR)
    
    with pytest.raises(AttributeError, match="Attribute missing"):
        await middleware.dispatch(mock_request_no_client, mock_call_next_attr_exc)
        
    log_records = [r.message for r in caplog.records if r.name == "api.requests"]
    assert any("✕ AttributeError: Attribute missing" in msg for msg in log_records)
    assert any(r.exc_info is not None for r in caplog.records if "✕ AttributeError" in r.message)

    # 一般的な Exception を投げた場合
    async def mock_call_next_general_exc(req):
        raise Exception("Generic fail")
        
    caplog.clear()
    caplog.set_level(logging.ERROR)
    
    with pytest.raises(Exception, match="Generic fail"):
        await middleware.dispatch(mock_request_no_client, mock_call_next_general_exc)
        
    log_records = [r.message for r in caplog.records if r.name == "api.requests"]
    assert any("✕ Unexpected Error (Exception): Generic fail" in msg for msg in log_records)
    assert any(r.exc_info is not None for r in caplog.records if "✕ Unexpected Error" in r.message)


# 4. SlowRequestMiddleware のテスト
def test_slow_request_middleware_fast(caplog):
    app = FastAPI()
    app.add_middleware(SlowRequestMiddleware, threshold_ms=100.0)

    @app.get("/fast")
    def fast_endpoint():
        return {"status": "fast"}

    client = TestClient(app)
    
    caplog.clear()
    caplog.set_level(logging.WARNING)
    
    response = client.get("/fast")
    assert response.status_code == 200
    # 警告ログがないこと
    assert not any("SLOW REQUEST" in r.message for r in caplog.records)

def test_slow_request_middleware_slow(caplog):
    app = FastAPI()
    app.add_middleware(SlowRequestMiddleware, threshold_ms=10.0)

    @app.get("/slow")
    def slow_endpoint():
        time.sleep(0.02) # 20ms スリープ
        return {"status": "slow"}

    client = TestClient(app)
    
    caplog.clear()
    caplog.set_level(logging.WARNING)
    
    response = client.get("/slow")
    assert response.status_code == 200
    # 警告ログがあること
    log_records = [r.message for r in caplog.records if r.name == "api.requests"]
    assert any("SLOW REQUEST: GET /slow" in msg for msg in log_records)


# 5. setup_logging_middleware のテスト
def test_setup_logging_middleware():
    app = FastAPI()
    setup_logging_middleware(app)
    
    middleware_classes = [m.cls for m in app.user_middleware]
    assert RequestLoggingMiddleware in middleware_classes
    assert SlowRequestMiddleware in middleware_classes


# 6. 堅牢化ガード処理とエッジケースのテスト
@pytest.mark.asyncio
async def test_request_logging_middleware_robustness_guards(caplog):
    middleware = RequestLoggingMiddleware(app=None)

    # ① request.method が文字列以外、request.url.path が文字列以外、request.client.host が文字列以外
    mock_request = MagicMock(spec=Request)
    mock_request.method = 12345  # 非文字列
    mock_request.url = MagicMock()
    mock_request.url.path = 99999  # 非文字列
    mock_request.client = MagicMock()
    mock_request.client.host = 88888  # 非文字列

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {}

    async def mock_call_next(req):
        return mock_response

    caplog.clear()
    caplog.set_level(logging.INFO)

    res = await middleware.dispatch(mock_request, mock_call_next)
    assert res == mock_response
    assert "X-Request-ID" in res.headers

    log_records = [r.message for r in caplog.records if r.name == "api.requests"]
    # method は str(12345) で '12345' に、url.path は str(99999) に、client.host も str(88888) になることを確認
    assert any("→ 12345 99999 from 88888" in msg for msg in log_records)


@pytest.mark.asyncio
async def test_request_logging_middleware_response_none(caplog):
    middleware = RequestLoggingMiddleware(app=None)

    # ② call_next が None を返す（レスポンスが None）場合
    mock_request = MagicMock(spec=Request)
    mock_request.method = "GET"
    mock_request.url.path = "/none-response"
    mock_request.client = None

    async def mock_call_next_none(req):
        return None

    caplog.clear()
    caplog.set_level(logging.INFO)

    res = await middleware.dispatch(mock_request, mock_call_next_none)
    # JSONResponse(500) が生成されていること
    assert res is not None
    assert res.status_code == 500
    # ヘッダーにIDが設定されていること
    assert "X-Request-ID" in res.headers


@pytest.mark.asyncio
async def test_request_logging_middleware_immutable_headers(caplog):
    middleware = RequestLoggingMiddleware(app=None)

    # ③ response.headers が不変（__setitem__ を持たない）オブジェクトの場合
    mock_request = MagicMock(spec=Request)
    mock_request.method = "GET"
    mock_request.url.path = "/immutable"
    mock_request.client = None

    mock_response = MagicMock()
    mock_response.status_code = 200
    # headers 属性はあるが、__setitem__ を持たないオブジェクトにする
    class ImmutableHeaders:
        pass
    mock_response.headers = ImmutableHeaders()

    async def mock_call_next(req):
        return mock_response

    caplog.clear()
    caplog.set_level(logging.INFO)

    # エラーにならずに正常終了すること
    res = await middleware.dispatch(mock_request, mock_call_next)
    assert res == mock_response


def test_slow_request_middleware_invalid_threshold():
    # ④ threshold_ms が無効な値の場合のフォールバック
    # 文字列
    middleware_str = SlowRequestMiddleware(app=None, threshold_ms="invalid")
    assert middleware_str.threshold_ms == 1000.0

    # 負の数
    middleware_neg = SlowRequestMiddleware(app=None, threshold_ms=-500)
    assert middleware_neg.threshold_ms == 1000.0

    # None
    middleware_none = SlowRequestMiddleware(app=None, threshold_ms=None)
    assert middleware_none.threshold_ms == 1000.0


def test_setup_logging_middleware_robustness():
    # ⑤ setup_logging_middleware に無効な値を渡した場合
    # None
    setup_logging_middleware(None)  # エラーにならないこと

    # add_middleware 属性を持たないオブジェクト
    setup_logging_middleware(object())  # エラーにならないこと


@pytest.mark.asyncio
async def test_slow_request_middleware_response_none():
    # ⑥ SlowRequestMiddleware.dispatch で response が None の場合
    middleware = SlowRequestMiddleware(app=None, threshold_ms=100.0)
    mock_request = MagicMock(spec=Request)
    
    async def mock_call_next_none(req):
        return None
        
    res = await middleware.dispatch(mock_request, mock_call_next_none)
    assert res is None


@pytest.mark.asyncio
async def test_slow_request_middleware_error(caplog):
    # ⑦ SlowRequestMiddleware.dispatch で例外が発生し、かつ処理時間が閾値を超えた場合の検証
    middleware = SlowRequestMiddleware(app=None, threshold_ms=1.0)
    mock_request = MagicMock(spec=Request)
    mock_request.method = "POST"
    mock_request.url.path = "/slow-error"
    
    async def mock_call_next_slow_err(req):
        time.sleep(0.005) # 5ms
        raise ValueError("Database connection failed")
        
    caplog.clear()
    caplog.set_level(logging.WARNING)
    
    with pytest.raises(ValueError, match="Database connection failed"):
        await middleware.dispatch(mock_request, mock_call_next_slow_err)
        
    log_records = [r.message for r in caplog.records if r.name == "api.requests"]
    assert any("SLOW REQUEST WITH ERROR: POST /slow-error took" in msg for msg in log_records)
    assert any("Error: ValueError: Database connection failed" in msg for msg in log_records)


@pytest.mark.asyncio
async def test_request_logging_middleware_http_exception_completed_log(caplog):
    # HTTPException 発生時に完了ログが出力されることを検証する
    middleware = RequestLoggingMiddleware(app=None)
    mock_request = MagicMock(spec=Request)
    mock_request.method = "GET"
    mock_request.url.path = "/http-exc-log"
    mock_request.client = None

    async def mock_call_next_http_exc(req):
        raise HTTPException(status_code=400, detail="Bad Request Details")

    caplog.clear()
    caplog.set_level(logging.INFO)

    with pytest.raises(HTTPException):
        await middleware.dispatch(mock_request, mock_call_next_http_exc)

    log_records = [r.message for r in caplog.records if r.name == "api.requests"]
    assert any("→ GET /http-exc-log from unknown" in msg for msg in log_records)
    assert any("← 400" in msg for msg in log_records) or any("HTTPException" in msg for msg in log_records)


@pytest.mark.asyncio
async def test_request_logging_middleware_base_exception_logging(caplog):
    # asyncio.CancelledError (BaseException) 発生時にエラーログが出力されることを検証する
    import asyncio
    middleware = RequestLoggingMiddleware(app=None)
    mock_request = MagicMock(spec=Request)
    mock_request.method = "DELETE"
    mock_request.url.path = "/cancelled"
    mock_request.client = None

    async def mock_call_next_cancelled(req):
        raise asyncio.CancelledError("Connection closed by client")

    caplog.clear()
    caplog.set_level(logging.ERROR)

    with pytest.raises(asyncio.CancelledError):
        await middleware.dispatch(mock_request, mock_call_next_cancelled)

    log_records = [r.message for r in caplog.records if r.name == "api.requests"]
    assert any("✕ Unexpected Error (CancelledError): Connection closed by client" in msg for msg in log_records)


def test_slow_request_middleware_bool_threshold():
    # threshold_ms に bool 値 (True) が渡された場合に 1000.0 にフォールバックすることを検証する
    middleware = SlowRequestMiddleware(app=None, threshold_ms=True)
    assert middleware.threshold_ms == 1000.0


@pytest.mark.asyncio
async def test_slow_request_middleware_base_exception_error(caplog):
    # SlowRequestMiddleware.dispatch で BaseException (asyncio.CancelledError) が発生し、
    # 閾値を超えた場合に警告ログが出力されることを検証する
    import asyncio
    middleware = SlowRequestMiddleware(app=None, threshold_ms=1.0)
    mock_request = MagicMock(spec=Request)
    mock_request.method = "GET"
    mock_request.url.path = "/slow-cancel"

    async def mock_call_next_slow_cancel(req):
        time.sleep(0.005) # 5ms
        raise asyncio.CancelledError("Timeout or cancel")

    caplog.clear()
    caplog.set_level(logging.WARNING)

    with pytest.raises(asyncio.CancelledError):
        await middleware.dispatch(mock_request, mock_call_next_slow_cancel)

    log_records = [r.message for r in caplog.records if r.name == "api.requests"]
    assert any("SLOW REQUEST WITH ERROR: GET /slow-cancel took" in msg for msg in log_records)
    assert any("Error: CancelledError: Timeout or cancel" in msg for msg in log_records)

