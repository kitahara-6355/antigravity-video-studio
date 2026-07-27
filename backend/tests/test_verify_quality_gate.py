import sys
import os
import pytest
import requests
import requests_mock

# パス設定 (絶対パスでワークスペースルートを指定し、Windows用にパスを正規化)
WORKSPACE_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, WORKSPACE_ROOT)

import backend.verify_quality_gate as verify_quality_gate

def test_verify_quality_gate_pytest_mode(monkeypatch):
    """pytest環境下での TestClient 経由の検証ルートをテスト"""
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_verify_quality_gate")
    verify_quality_gate.test_quality_gate()

def test_verify_quality_gate_manual_mode_success(monkeypatch):
    """手動実行（requests.post 成功）ルートをテスト"""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    
    import sys
    pytest_module = sys.modules.get("pytest")
    if "pytest" in sys.modules:
        del sys.modules["pytest"]
        
    try:
        with requests_mock.Mocker() as m:
            m.post("http://localhost:8000/api/director/verify-quality", json={"status": "success", "score": 90})
            verify_quality_gate.test_quality_gate()
    finally:
        if pytest_module:
            sys.modules["pytest"] = pytest_module

def test_verify_quality_gate_manual_mode_connection_error(monkeypatch):
    """手動実行（requests.post が ConnectionError）ルートをテスト"""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    
    import sys
    pytest_module = sys.modules.get("pytest")
    if "pytest" in sys.modules:
        del sys.modules["pytest"]
        
    try:
        with requests_mock.Mocker() as m:
            m.post("http://localhost:8000/api/director/verify-quality", exc=requests.exceptions.ConnectionError("Connection refused"))
            verify_quality_gate.test_quality_gate()
    finally:
        if pytest_module:
            sys.modules["pytest"] = pytest_module

def test_verify_quality_gate_manual_mode_api_error(monkeypatch):
    """手動実行（requests.post がエラーレスポンス 400 を返す）ルートをテスト"""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    
    import sys
    pytest_module = sys.modules.get("pytest")
    if "pytest" in sys.modules:
        del sys.modules["pytest"]
        
    try:
        with requests_mock.Mocker() as m:
            m.post("http://localhost:8000/api/director/verify-quality", status_code=400, json={"error": "Bad Request"})
            verify_quality_gate.test_quality_gate()
    finally:
        if pytest_module:
            sys.modules["pytest"] = pytest_module

def test_verify_quality_gate_manual_mode_json_decode_error(monkeypatch):
    """手動実行（JSONデコードエラー）ルートをテスト"""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    
    import sys
    pytest_module = sys.modules.get("pytest")
    if "pytest" in sys.modules:
        del sys.modules["pytest"]
        
    try:
        with requests_mock.Mocker() as m:
            m.post("http://localhost:8000/api/director/verify-quality", status_code=500, text="Internal Server Error")
            verify_quality_gate.test_quality_gate()
    finally:
        if pytest_module:
            sys.modules["pytest"] = pytest_module

def test_verify_quality_gate_manual_mode_generic_request_exception(monkeypatch):
    """手動実行（ConnectionError以外のRequestException）ルートをテスト"""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    
    import sys
    pytest_module = sys.modules.get("pytest")
    if "pytest" in sys.modules:
        del sys.modules["pytest"]
        
    try:
        with requests_mock.Mocker() as m:
            m.post("http://localhost:8000/api/director/verify-quality", exc=requests.exceptions.Timeout("Request timeout"))
            verify_quality_gate.test_quality_gate()
    finally:
        if pytest_module:
            sys.modules["pytest"] = pytest_module

def test_verify_quality_gate_main():
    """__main__ブロックの実行をカバーするために直接実行をシミュレート"""
    import runpy
    target_script = os.path.normpath(os.path.join(WORKSPACE_ROOT, "backend", "verify_quality_gate.py"))
    runpy.run_path(target_script, run_name="__main__")

def test_verify_quality_gate_pytest_mode_status_error(monkeypatch):
    """pytest環境下で TestClient が 200 以外のステータスコードを返したときに AssertionError が発生することを検証"""
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_verify_quality_gate")
    
    from fastapi.testclient import TestClient
    
    class FakeResponse:
        status_code = 500
        def json(self):
            return {"error": "Internal Server Error"}
            
    def mock_post(*args, **kwargs):
        return FakeResponse()
        
    monkeypatch.setattr(TestClient, "post", mock_post)
    
    with pytest.raises(AssertionError):
        verify_quality_gate.test_quality_gate()

def test_verify_quality_gate_pytest_mode_json_type_error(monkeypatch):
    """pytest環境下で TestClient のレスポンスが dict 以外（リストなど）のときに AssertionError が発生することを検証"""
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_verify_quality_gate")
    
    from fastapi.testclient import TestClient
    
    class FakeResponse:
        status_code = 200
        def json(self):
            return ["not", "a", "dict"]
            
    def mock_post(*args, **kwargs):
        return FakeResponse()
        
    monkeypatch.setattr(TestClient, "post", mock_post)
    
    with pytest.raises(AssertionError):
        verify_quality_gate.test_quality_gate()

def test_verify_quality_gate_is_pytest_variations(monkeypatch):
    """is_pytest が True と判定される各種条件を個別に検証"""
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "some_test")
    
    pytest_module = sys.modules.get("pytest")
    if "pytest" in sys.modules:
        del sys.modules["pytest"]
        
    try:
        called = []
        from fastapi.testclient import TestClient
        
        class FakeResponse:
            status_code = 200
            def json(self):
                return {}
        
        monkeypatch.setattr(TestClient, "post", lambda *a, **k: called.append(True) or FakeResponse())
        
        verify_quality_gate.test_quality_gate()
        assert len(called) == 1
    finally:
        if pytest_module:
            sys.modules["pytest"] = pytest_module
