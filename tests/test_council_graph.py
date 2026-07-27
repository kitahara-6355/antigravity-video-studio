import sys
import os
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

# Ensure backend path is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.council_graph import run_council, HTTPException, GENAI_ERRORS

@pytest.fixture(autouse=True)
def mock_gemini_api_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "mock-api-key")

@pytest.mark.asyncio
async def test_run_council_import_error_on_runners():
    """google-adk のインポートエラー発生時にフォールバック応答が返ることをテスト"""
    # sys.modules から google.adk を一時的に隠す、または patch.dict を使う
    with patch.dict(sys.modules, {"google.adk.runners": None}):
        res = await run_council(user_query="データ分析をお願いします", session_id="test-session-import-error")
        assert res["status"] == "error"
        assert "Council of Minds の起動に失敗しました" in res["synthesis"]
        assert res["session_id"] == "test-session-import-error"

@pytest.mark.asyncio
async def test_run_council_success():
    """正常系: ADKが正常に動き、統合レポートが取得できることをテスト"""
    # 各種モック
    mock_runner_instance = MagicMock()
    mock_session_service = AsyncMock()
    mock_runner_instance.session_service = mock_session_service

    # session.state に 'council_synthesis' を入れておく
    mock_session = MagicMock()
    mock_session.state = {"council_synthesis": "モック化された最終統合レポート"}
    mock_session_service.create_session.return_value = mock_session
    mock_session_service.get_session.return_value = mock_session

    # run_async が返す非同期イテレータのモック
    # event.is_final_response() -> True, event.content.parts[0].text -> "モックのストリーミング結果"
    mock_event = MagicMock()
    mock_event.is_final_response.return_value = True
    mock_part = MagicMock()
    mock_part.text = "モックのストリーミング結果"
    mock_event.content.parts = [mock_part]

    async def mock_run_async(*args, **kwargs):
        yield mock_event

    mock_runner_instance.run_async = mock_run_async

    with patch("google.adk.runners.InMemoryRunner", return_value=mock_runner_instance), \
         patch("google.adk.sessions.InMemorySessionService", return_value=mock_session_service):
        
        res = await run_council(user_query="テストクエリ", session_id="success-session")
        assert res["status"] == "success"
        assert res["synthesis"] == "モックのストリーミング結果"
        assert res["session_id"] == "success-session"

@pytest.mark.asyncio
async def test_run_council_success_fallback_to_state():
    """正常系：ストリーミング結果が空の場合に session.state の output_key から取得することをテスト"""
    mock_runner_instance = MagicMock()
    mock_session_service = AsyncMock()
    mock_runner_instance.session_service = mock_session_service

    mock_session = MagicMock()
    mock_session.state = {"council_synthesis": "ステートから取得した最終統合レポート"}
    mock_session_service.create_session.return_value = mock_session
    mock_session_service.get_session.return_value = mock_session

    # 空のストリーミング結果を返す
    async def mock_run_async(*args, **kwargs):
        yield None

    mock_runner_instance.run_async = mock_run_async

    with patch("google.adk.runners.InMemoryRunner", return_value=mock_runner_instance), \
         patch("google.adk.sessions.InMemorySessionService", return_value=mock_session_service):
        
        res = await run_council(user_query="テストクエリ", session_id="state-fallback-session")
        assert res["status"] == "success"
        assert res["synthesis"] == "ステートから取得した最終統合レポート"

@pytest.mark.asyncio
async def test_run_council_http_exception():
    """HTTPException が発生した場合、そのまま再送出（raise）されることをテスト"""
    mock_runner_instance = MagicMock()
    mock_session_service = AsyncMock()
    mock_runner_instance.session_service = mock_session_service
    # create_session で HTTPException を発生させる
    mock_session_service.create_session.side_effect = HTTPException(status_code=400, detail="Bad Request")

    with patch("google.adk.runners.InMemoryRunner", return_value=mock_runner_instance), \
         patch("google.adk.sessions.InMemorySessionService", return_value=mock_session_service):
        
        with pytest.raises(HTTPException):
            await run_council(user_query="テストクエリ", session_id="http-exception-session")

@pytest.mark.asyncio
async def test_run_council_timeout_error():
    """TimeoutError 発生時にフォールバック応答が返ることをテスト"""
    mock_runner_instance = MagicMock()
    mock_session_service = AsyncMock()
    mock_runner_instance.session_service = mock_session_service
    mock_session_service.create_session.side_effect = asyncio.TimeoutError("Connection timed out")

    with patch("google.adk.runners.InMemoryRunner", return_value=mock_runner_instance), \
         patch("google.adk.sessions.InMemorySessionService", return_value=mock_session_service):
        
        res = await run_council(user_query="テストクエリ", session_id="timeout-session")
        assert res["status"] == "error"
        assert "通信タイムアウトが発生しました" in res["synthesis"]

@pytest.mark.asyncio
async def test_run_council_value_error():
    """ValueError 発生時にフォールバック応答が返ることをテスト"""
    mock_runner_instance = MagicMock()
    mock_session_service = AsyncMock()
    mock_runner_instance.session_service = mock_session_service
    mock_session_service.create_session.side_effect = ValueError("Invalid parameter value")

    with patch("google.adk.runners.InMemoryRunner", return_value=mock_runner_instance), \
         patch("google.adk.sessions.InMemorySessionService", return_value=mock_session_service):
        
        res = await run_council(user_query="テストクエリ", session_id="value-error-session")
        assert res["status"] == "error"
        assert "Invalid parameter value" in res["synthesis"]

@pytest.mark.asyncio
async def test_run_council_genai_error():
    """Google GenAI APIError 発生時にフォールバック応答が返ることをテスト"""
    mock_runner_instance = MagicMock()
    mock_session_service = AsyncMock()
    mock_runner_instance.session_service = mock_session_service
    
    # GENAI_ERRORS のダミーエラーを使用
    error_class = GENAI_ERRORS[0]
    try:
        dummy_genai_error = error_class(code=500, response_json={})
    except TypeError:
        dummy_genai_error = error_class("API rate limit exceeded")
        
    mock_session_service.create_session.side_effect = dummy_genai_error

    with patch("google.adk.runners.InMemoryRunner", return_value=mock_runner_instance), \
         patch("google.adk.sessions.InMemorySessionService", return_value=mock_session_service):
        
        res = await run_council(user_query="テストクエリ", session_id="genai-error-session")
        assert res["status"] == "error"
        assert "Google APIエラーが発生しました" in res["synthesis"]

def test_thumbnail_resolver_arg_error():
    """ThumbnailResolver のインスタンス化引数不正（TypeError/ValueError）がラップされずにそのまま送出されることをテスト"""
    from agents.council_graph import ThumbnailResolver
    
    # services.thumbnail_analyzer.ThumbnailResolver をモック化し、初期化時に TypeError を発生させる
    mock_resolver_class = MagicMock(side_effect=TypeError("Invalid args"))
    
    # 既に real_class がキャッシュされている場合があるため、一時的にクリア
    original_real = ThumbnailResolver._real_class
    ThumbnailResolver._real_class = mock_resolver_class
    
    try:
        with pytest.raises(TypeError) as excinfo:
            ThumbnailResolver(invalid_arg="test")
        assert "Invalid args" in str(excinfo.value)
    finally:
        ThumbnailResolver._real_class = original_real

@pytest.mark.asyncio
async def test_run_council_value_error_handling():
    """run_council で ValueError が発生した際、個別ハンドリングで「構成エラーが発生しました」が返ることをテスト"""
    mock_runner_instance = MagicMock()
    mock_session_service = AsyncMock()
    mock_runner_instance.session_service = mock_session_service
    
    # ValueError を発生させる
    mock_session_service.create_session.side_effect = ValueError("Invalid config parameter")

    with patch("google.adk.runners.InMemoryRunner", return_value=mock_runner_instance), \
         patch("google.adk.sessions.InMemorySessionService", return_value=mock_session_service):
        
        res = await run_council(user_query="テストクエリ", session_id="val-err-session")
        assert res["status"] == "error"
        assert "構成エラーが発生しました" in res["synthesis"]

@pytest.mark.asyncio
async def test_run_council_attribute_error_handling():
    """run_council で AttributeError が発生した際、個別ハンドリングで「内部プログラムエラーが発生しました」が返ることをテスト"""
    mock_runner_instance = MagicMock()
    mock_session_service = AsyncMock()
    mock_runner_instance.session_service = mock_session_service
    
    # AttributeError を発生させる
    mock_session_service.create_session.side_effect = AttributeError("Session object has no attribute 'state'")

    with patch("google.adk.runners.InMemoryRunner", return_value=mock_runner_instance), \
         patch("google.adk.sessions.InMemorySessionService", return_value=mock_session_service):
        
        res = await run_council(user_query="テストクエリ", session_id="attr-err-session")
        assert res["status"] == "error"
        assert "内部プログラムエラーが発生しました" in res["synthesis"]

def test_thumbnail_resolver_os_error_initialization():
    """ThumbnailResolver の初期化中に OSError が発生した際、RuntimeError にラップされることをテスト"""
    from agents.council_graph import ThumbnailResolver
    
    # services.thumbnail_analyzer.ThumbnailResolver をモック化し、初期化時に OSError を発生させる
    mock_resolver_class = MagicMock(side_effect=OSError("Disk failure"))
    
    original_real = ThumbnailResolver._real_class
    ThumbnailResolver._real_class = mock_resolver_class
    
    try:
        with pytest.raises(RuntimeError) as excinfo:
            ThumbnailResolver()
        assert "ThumbnailResolver の初期化中にエラーが発生しました" in str(excinfo.value)
        assert "Disk failure" in str(excinfo.value)
    finally:
        ThumbnailResolver._real_class = original_real

@pytest.mark.asyncio
async def test_run_council_runtime_error():
    """run_council で RuntimeError が発生した際、個別ハンドリングで「実行時エラーが発生しました」が返ることをテスト"""
    mock_runner_instance = MagicMock()
    mock_session_service = AsyncMock()
    mock_runner_instance.session_service = mock_session_service
    
    # RuntimeError を発生させる
    mock_session_service.create_session.side_effect = RuntimeError("ADK Runner crashed")

    with patch("google.adk.runners.InMemoryRunner", return_value=mock_runner_instance), \
         patch("google.adk.sessions.InMemorySessionService", return_value=mock_session_service):
        
        res = await run_council(user_query="テストクエリ", session_id="run-err-session")
        assert res["status"] == "error"
        assert "実行時エラーが発生しました" in res["synthesis"]
        assert "ADK Runner crashed" in res["synthesis"]



def test_thumbnail_resolver_instantiation_key_error_wrapping():
    """ThumbnailResolver のインスタンス化中に KeyError が発生した際、RuntimeError にラップされることをテスト"""
    from agents.council_graph import ThumbnailResolver
    
    class KeyErrorResolver:
        def __init__(self, *args, **kwargs):
            raise KeyError("Specific key error mock")
            
    original_real = ThumbnailResolver._real_class
    ThumbnailResolver._real_class = KeyErrorResolver
    
    try:
        with pytest.raises(RuntimeError) as excinfo:
            ThumbnailResolver()
        assert "ThumbnailResolver の初期化中にエラーが発生しました" in str(excinfo.value)
        assert "Specific key error mock" in str(excinfo.value)
    finally:
        ThumbnailResolver._real_class = original_real


def test_thumbnail_resolver_import_error_propagation():
    """ThumbnailResolver のインスタンス化中に ImportError が発生した際、そのまま再送出されることをテスト"""
    from agents.council_graph import ThumbnailResolver
    
    # 意図的に ImportError を発生させるモック
    mock_resolver_class = MagicMock(side_effect=ImportError("Failed to import dependency"))
    
    original_real = ThumbnailResolver._real_class
    ThumbnailResolver._real_class = mock_resolver_class
    
    try:
        with pytest.raises(ImportError) as excinfo:
            ThumbnailResolver()
        assert "Failed to import dependency" in str(excinfo.value)
    finally:
        ThumbnailResolver._real_class = original_real

def test_thumbnail_resolver_genai_error_propagation():
    """ThumbnailResolver のインスタンス化中に APIError が発生した際、そのまま再送出されることをテスト"""
    from agents.council_graph import ThumbnailResolver
    
    # GENAI_ERRORS のダミーエラーを使用
    error_class = GENAI_ERRORS[0]
    try:
        dummy_genai_error = error_class(code=500, response_json={})
    except TypeError:
        dummy_genai_error = error_class("API Error occurred")
        
    mock_resolver_class = MagicMock(side_effect=dummy_genai_error)
    
    original_real = ThumbnailResolver._real_class
    ThumbnailResolver._real_class = mock_resolver_class
    
    try:
        with pytest.raises(error_class) as excinfo:
            ThumbnailResolver()
        err_str = str(excinfo.value)
        assert "API Error occurred" in err_str or "500" in err_str
    finally:
        ThumbnailResolver._real_class = original_real

def test_thumbnail_resolver_generic_exception_wrapping():
    """ThumbnailResolver のインスタンス化中に一般的な例外が発生した際、RuntimeErrorにラップされることをテスト"""
    from agents.council_graph import ThumbnailResolver
    
    mock_resolver_class = MagicMock(side_effect=Exception("Generic unexpected failure"))
    
    original_real = ThumbnailResolver._real_class
    ThumbnailResolver._real_class = mock_resolver_class
    
    try:
        with pytest.raises(RuntimeError) as excinfo:
            ThumbnailResolver()
        assert "ThumbnailResolver の初期化中にエラーが発生しました" in str(excinfo.value)
        assert "Generic unexpected failure" in str(excinfo.value)
    finally:
        ThumbnailResolver._real_class = original_real


@pytest.mark.asyncio
async def test_run_council_key_error_handling():
    """run_council で KeyError（内部バグ検出）が発生した際、個別ハンドリングで「内部プログラムエラーが発生しました」が返ることをテスト"""
    mock_runner_instance = MagicMock()
    mock_session_service = AsyncMock()
    mock_runner_instance.session_service = mock_session_service
    
    # KeyError を発生させる
    mock_session_service.create_session.side_effect = KeyError("Missing expected session configuration key")

    with patch("google.adk.runners.InMemoryRunner", return_value=mock_runner_instance), \
         patch("google.adk.sessions.InMemorySessionService", return_value=mock_session_service):
        
        res = await run_council(user_query="テストクエリ", session_id="key-err-session")
        assert res["status"] == "error"
        assert "内部プログラムエラーが発生しました" in res["synthesis"]
        assert "Missing expected session configuration key" in res["synthesis"]

@pytest.mark.asyncio
async def test_run_council_generic_exception_handling():
    """run_council で予期せぬ Exception が発生した際、フォールバック応答にエラーメッセージが含まれることをテスト"""
    mock_runner_instance = MagicMock()
    mock_session_service = AsyncMock()
    mock_runner_instance.session_service = mock_session_service
    
    # 一般的な Exception を発生させる
    mock_session_service.create_session.side_effect = Exception("Unexpected database connection crash")

    with patch("google.adk.runners.InMemoryRunner", return_value=mock_runner_instance), \
         patch("google.adk.sessions.InMemorySessionService", return_value=mock_session_service):
        
        res = await run_council(user_query="テストクエリ", session_id="generic-exc-session")
        assert res["status"] == "error"
        assert "Unexpected database connection crash" in res["synthesis"]

def test_thumbnail_resolver_dynamic_import_error():
    """ThumbnailResolver の動的インポート失敗時に ImportError が発生することをテスト"""
    import sys
    from unittest.mock import patch
    from agents.council_graph import ThumbnailResolver
    
    original_real = ThumbnailResolver._real_class
    ThumbnailResolver._real_class = None
    
    with patch.dict(sys.modules, {"services.thumbnail_analyzer": None}):
        with pytest.raises(ImportError) as excinfo:
            ThumbnailResolver()
        assert "ThumbnailResolver (services.thumbnail_analyzer) のインポートに失敗しました" in str(excinfo.value)
    
    ThumbnailResolver._real_class = original_real


# ==============================================================
# 追加のエラーハンドリング・カバレッジ用テスト
# ==============================================================

def test_imports_fallback():
    """各種モジュールがインポートできない場合のフォールバック定義をテスト"""
    import importlib
    
    # 元のモジュールを退避
    orig_fastapi = sys.modules.get("fastapi")
    orig_genai = sys.modules.get("google.genai.errors")
    orig_httpx = sys.modules.get("httpx")
    orig_google_api = sys.modules.get("google.api_core.exceptions")
    orig_grpc = sys.modules.get("grpc")

    try:
        # sys.modules から削除し、None を指定して ImportError を誘発
        with patch.dict(sys.modules, {
            "fastapi": None,
            "google.genai.errors": None,
            "httpx": None,
            "google.api_core.exceptions": None,
            "grpc": None
        }):
            import agents.council_graph
            importlib.reload(agents.council_graph)
            
            # ダミークラスが正常に定義されているか検証
            assert issubclass(agents.council_graph.HTTPException, Exception)
            # ダミー HTTPException の __init__ (26-28行目) を呼び出してカバレッジを通す
            dummy_exc = agents.council_graph.HTTPException(status_code=418, detail="Teapot")
            assert dummy_exc.status_code == 418
            assert dummy_exc.detail == "Teapot"
            
            dummy_exc_no_detail = agents.council_graph.HTTPException(status_code=500)
            assert dummy_exc_no_detail.status_code == 500
            
            assert len(agents.council_graph.GENAI_ERRORS) == 1
            assert agents.council_graph.GENAI_ERRORS[0].__name__ == "DummyGenAIError"
            assert agents.council_graph.HTTPX_ERRORS[0].__name__ == "DummyHTTPError"
            assert len(agents.council_graph.ALL_GENAI_ERRORS) >= 3
    finally:
        # 元に戻して再度リロード
        if orig_fastapi:
            sys.modules["fastapi"] = orig_fastapi
        else:
            sys.modules.pop("fastapi", None)
            
        if orig_genai:
            sys.modules["google.genai.errors"] = orig_genai
        else:
            sys.modules.pop("google.genai.errors", None)
            
        if orig_httpx:
            sys.modules["httpx"] = orig_httpx
        else:
            sys.modules.pop("httpx", None)

        if orig_google_api:
            sys.modules["google.api_core.exceptions"] = orig_google_api
        else:
            sys.modules.pop("google.api_core.exceptions", None)

        if orig_grpc:
            sys.modules["grpc"] = orig_grpc
        else:
            sys.modules.pop("grpc", None)
            
        importlib.reload(agents.council_graph)


@pytest.mark.asyncio
async def test_run_council_no_session_id():
    """session_id を指定しない場合に uuid が自動生成されることをテスト"""
    mock_runner_instance = MagicMock()
    mock_session_service = AsyncMock()
    mock_runner_instance.session_service = mock_session_service

    mock_session = MagicMock()
    mock_session.state = {"council_synthesis": "自動生成セッションテスト"}
    mock_session_service.create_session.return_value = mock_session
    mock_session_service.get_session.return_value = mock_session

    async def mock_run_async(*args, **kwargs):
        yield None

    mock_runner_instance.run_async = mock_run_async

    with patch("google.adk.runners.InMemoryRunner", return_value=mock_runner_instance),          patch("google.adk.sessions.InMemorySessionService", return_value=mock_session_service):
        
        res = await run_council(user_query="テストクエリ", session_id=None)
        assert res["status"] == "success"
        assert res["synthesis"] == "自動生成セッションテスト"
        assert res["session_id"] is not None
        import uuid
        try:
            uuid.UUID(res["session_id"])
        except ValueError:
            pytest.fail("session_id is not a valid UUID")


@pytest.mark.asyncio
async def test_run_council_get_session_failure():
    """get_session が None を返した場合のフォールバック動作をテスト"""
    mock_runner_instance = MagicMock()
    mock_session_service = AsyncMock()
    mock_runner_instance.session_service = mock_session_service

    mock_session_service.create_session.return_value = MagicMock()
    mock_session_service.get_session.return_value = None

    async def mock_run_async(*args, **kwargs):
        yield None

    mock_runner_instance.run_async = mock_run_async

    with patch("google.adk.runners.InMemoryRunner", return_value=mock_runner_instance),          patch("google.adk.sessions.InMemorySessionService", return_value=mock_session_service):
        
        res = await run_council(user_query="テストクエリ", session_id="get-session-fail-session")
        assert res["status"] == "success"
        assert "統合レポートを生成できませんでした（セッション情報の取得失敗）" in res["synthesis"]


@pytest.mark.asyncio
async def test_run_council_json_decode_error():
    """run_council で JSONDecodeError が発生した際にフォールバック応答が返ることをテスト"""
    mock_runner_instance = MagicMock()
    mock_session_service = AsyncMock()
    mock_runner_instance.session_service = mock_session_service
    
    import json
    mock_session_service.create_session.side_effect = json.JSONDecodeError("Expecting value", "{}", 0)

    with patch("google.adk.runners.InMemoryRunner", return_value=mock_runner_instance),          patch("google.adk.sessions.InMemorySessionService", return_value=mock_session_service):
        
        res = await run_council(user_query="テストクエリ", session_id="json-err-session")
        assert res["status"] == "error"
        assert "データの解析（JSON）に失敗しました" in res["synthesis"]


@pytest.mark.asyncio
async def test_run_council_os_error():
    """run_council で OSError が発生した際にフォールバック応答が返ることをテスト"""
    mock_runner_instance = MagicMock()
    mock_session_service = AsyncMock()
    mock_runner_instance.session_service = mock_session_service
    
    mock_session_service.create_session.side_effect = OSError("Permission denied")

    with patch("google.adk.runners.InMemoryRunner", return_value=mock_runner_instance),          patch("google.adk.sessions.InMemorySessionService", return_value=mock_session_service):
        
        res = await run_council(user_query="テストクエリ", session_id="os-err-session")
        assert res["status"] == "error"
        assert "システムI/Oエラーが発生しました" in res["synthesis"]


@pytest.mark.asyncio
async def test_run_council_httpx_error():
    """run_council で HTTPX エラーが発生した際にフォールバック応答が返ることをテスト"""
    mock_runner_instance = MagicMock()
    mock_session_service = AsyncMock()
    mock_runner_instance.session_service = mock_session_service
    
    from agents.council_graph import HTTPX_ERRORS
    error_class = HTTPX_ERRORS[0]
    
    try:
        import httpx
        dummy_httpx_error = httpx.RequestError("Network is down")
    except ImportError:
        dummy_httpx_error = error_class("Network is down")

    mock_session_service.create_session.side_effect = dummy_httpx_error

    with patch("google.adk.runners.InMemoryRunner", return_value=mock_runner_instance),          patch("google.adk.sessions.InMemorySessionService", return_value=mock_session_service):
        
        res = await run_council(user_query="テストクエリ", session_id="httpx-err-session")
        assert res["status"] == "error"
        assert "ネットワーク通信エラーが発生しました" in res["synthesis"]


@pytest.mark.asyncio
async def test_run_council_google_api_call_error():
    """run_council で GoogleAPICallError が発生した際にフォールバック応答が返ることをテスト"""
    mock_runner_instance = MagicMock()
    mock_session_service = AsyncMock()
    mock_runner_instance.session_service = mock_session_service
    
    from agents.council_graph import ALL_GENAI_ERRORS
    # ALL_GENAI_ERRORS から GoogleAPICallError (または DummyGoogleAPICallError) を探す
    error_class = None
    for err in ALL_GENAI_ERRORS:
        if "GoogleAPICallError" in err.__name__:
            error_class = err
            break
    if not error_class:
        error_class = ALL_GENAI_ERRORS[0]
        
    try:
        dummy_error = error_class("Google APICallError mock")
    except TypeError:
        dummy_error = error_class(message="Google APICallError mock")

    mock_session_service.create_session.side_effect = dummy_error

    with patch("google.adk.runners.InMemoryRunner", return_value=mock_runner_instance),          patch("google.adk.sessions.InMemorySessionService", return_value=mock_session_service):
        
        res = await run_council(user_query="テストクエリ", session_id="google-api-call-err-session")
        assert res["status"] == "error"
        assert "Google APIエラーが発生しました" in res["synthesis"]


@pytest.mark.asyncio
async def test_run_council_grpc_error():
    """run_council で grpc.RpcError が発生した際にフォールバック応答が返ることをテスト"""
    mock_runner_instance = MagicMock()
    mock_session_service = AsyncMock()
    mock_runner_instance.session_service = mock_session_service
    
    from agents.council_graph import ALL_GENAI_ERRORS
    error_class = None
    for err in ALL_GENAI_ERRORS:
        if "RpcError" in err.__name__ or "DummyGRPCError" in err.__name__:
            error_class = err
            break
    if not error_class:
        error_class = ALL_GENAI_ERRORS[0]
        
    try:
        dummy_error = error_class("gRPC error mock")
    except TypeError:
        dummy_error = error_class()

    mock_session_service.create_session.side_effect = dummy_error

    with patch("google.adk.runners.InMemoryRunner", return_value=mock_runner_instance),          patch("google.adk.sessions.InMemorySessionService", return_value=mock_session_service):
        
        res = await run_council(user_query="テストクエリ", session_id="grpc-err-session")
        assert res["status"] == "error"
        assert "Google APIエラーが発生しました" in res["synthesis"]


def test_thumbnail_resolver_signature_type_error():
    """ThumbnailResolver の引数バインド時の TypeError が適切に処理されることをテスト"""
    from agents.council_graph import ThumbnailResolver
    
    class DummyRealClass:
        def __init__(self, key):
            pass
            
    original_real = ThumbnailResolver._real_class
    ThumbnailResolver._real_class = DummyRealClass
    
    try:
        # 引数 key が必要なのに渡していないため, signature.bind で TypeError が発生する
        with pytest.raises(TypeError) as excinfo:
            ThumbnailResolver()
        assert "ThumbnailResolver の引数指定が不正です" in str(excinfo.value)
    finally:
        ThumbnailResolver._real_class = original_real


def test_thumbnail_resolver_http_exception_propagation():
    """ThumbnailResolver 内部での HTTPException がそのまま再送出されることをテスト"""
    from agents.council_graph import ThumbnailResolver
    
    mock_resolver_class = MagicMock(side_effect=HTTPException(status_code=403, detail="Forbidden"))
    
    original_real = ThumbnailResolver._real_class
    ThumbnailResolver._real_class = mock_resolver_class
    
    try:
        with pytest.raises(HTTPException) as excinfo:
            ThumbnailResolver()
        assert excinfo.value.status_code == 403
        assert excinfo.value.detail == "Forbidden"
    finally:
        ThumbnailResolver._real_class = original_real


def test_thumbnail_resolver_httpx_error_propagation():
    """ThumbnailResolver 内部での HTTPX_ERRORS がそのまま再送出されることをテスト"""
    from agents.council_graph import ThumbnailResolver, HTTPX_ERRORS
    
    error_class = HTTPX_ERRORS[0]
    try:
        import httpx
        dummy_error = httpx.RequestError("Network fail")
    except ImportError:
        dummy_error = error_class("Network fail")
        
    mock_resolver_class = MagicMock(side_effect=dummy_error)
    
    original_real = ThumbnailResolver._real_class
    ThumbnailResolver._real_class = mock_resolver_class
    
    try:
        with pytest.raises(error_class):
            ThumbnailResolver()
    finally:
        ThumbnailResolver._real_class = original_real


def test_thumbnail_resolver_real_class_type_error_wrapping():
    """is_mock = False の実クラス初期化時に TypeError/ValueError が発生した際、RuntimeErrorにラップされることをテスト"""
    from agents.council_graph import ThumbnailResolver
    
    class DummyErrorClass:
        def __init__(self, *args, **kwargs):
            raise ValueError("logical value error mock")
            
    original_real = ThumbnailResolver._real_class
    ThumbnailResolver._real_class = DummyErrorClass
    
    try:
        with pytest.raises(RuntimeError) as excinfo:
            ThumbnailResolver("arg")
        assert "ThumbnailResolver の初期化中にエラーが発生しました" in str(excinfo.value)
        assert "logical value error mock" in str(excinfo.value)
    finally:
        ThumbnailResolver._real_class = original_real


def test_thumbnail_resolver_mock_import_error_handling():
    """unittest.mock のインポートで ImportError が起きた場合のフォールバックをテスト"""
    from agents.council_graph import ThumbnailResolver
    import sys
    import importlib
    
    # 一時的に unittest.mock を sys.modules から除外
    orig_mock = sys.modules.get("unittest.mock")
    
    class DummyRealClass:
        def __init__(self):
            pass
            
    original_real = ThumbnailResolver._real_class
    ThumbnailResolver._real_class = DummyRealClass
    
    try:
        with patch.dict(sys.modules, {"unittest.mock": None}):
            # _real_class をリセットして再ロード等行わず、new() メソッド内の unittest.mock インポートを走らせる
            # new() が呼ばれると、try-except ImportError ブロックが実行される
            resolver = ThumbnailResolver()
            assert resolver is not None
    finally:
        ThumbnailResolver._real_class = original_real
        if orig_mock:
            sys.modules["unittest.mock"] = orig_mock


def test_thumbnail_resolver_successful_real_resolver_import():
    """ThumbnailResolver が services.thumbnail_analyzer.ThumbnailResolver を正常にインポートできるケースをテスト"""
    import sys
    from unittest.mock import MagicMock, patch
    from agents.council_graph import ThumbnailResolver

    # _real_class をリセット
    ThumbnailResolver._real_class = None

    # ダミーのモッククラスを用意
    class MockRealResolver:
        def __init__(self, *args, **kwargs):
            pass

    # ダミーのモジュールを作成
    mock_module = MagicMock()
    mock_module.ThumbnailResolver = MockRealResolver

    with patch.dict(sys.modules, {"services.thumbnail_analyzer": mock_module}):
        resolver = ThumbnailResolver()
        assert ThumbnailResolver._real_class is MockRealResolver
        assert isinstance(resolver, MockRealResolver)

    # 最後に元に戻す
    ThumbnailResolver._real_class = None


@pytest.mark.asyncio
async def test_run_council_no_api_key(monkeypatch):
    """GEMINI_API_KEY が設定されていない場合に適切なエラーフォールバックが返ることをテスト"""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    res = await run_council(user_query="テスト質問", session_id="no-key-session")
    assert res["status"] == "error"
    assert "No API key was provided" in res["synthesis"]
    assert res["session_id"] == "no-key-session"


@pytest.mark.asyncio
async def test_run_council_special_session_id():
    """session_id に特殊文字や日本語、長大文字列が含まれていても正常に処理されることをテスト"""
    mock_runner_instance = MagicMock()
    mock_session_service = AsyncMock()
    mock_runner_instance.session_service = mock_session_service

    mock_session = MagicMock()
    mock_session.state = {"council_synthesis": "特殊セッションテスト"}
    mock_session_service.create_session.return_value = mock_session
    mock_session_service.get_session.return_value = mock_session

    async def mock_run_async(*args, **kwargs):
        yield None

    mock_runner_instance.run_async = mock_run_async

    # 特殊なセッションID
    special_id = "test-session-ID_日本語_1234567890" * 3

    with patch("google.adk.runners.InMemoryRunner", return_value=mock_runner_instance), \
         patch("google.adk.sessions.InMemorySessionService", return_value=mock_session_service):
        
        res = await run_council(user_query="テストクエリ", session_id=special_id)
        assert res["status"] == "success"
        assert res["synthesis"] == "特殊セッションテスト"
        assert res["session_id"] == special_id


def test_http_exception_import_source():
    """HTTPException が starlette.exceptions (またはフォールバッククラス) 由来であることをテスト"""
    from agents.council_graph import HTTPException
    try:
        from starlette.exceptions import HTTPException as StarletteHTTPException
        assert issubclass(HTTPException, StarletteHTTPException)
    except ImportError:
        assert issubclass(HTTPException, Exception)


def test_thumbnail_resolver_patch_propagation():
    """ThumbnailResolver に対する unittest.mock.patch.object が、
    動的生成される RealResolver インスタンスに正しく伝播することをテスト
    """
    from agents.council_graph import ThumbnailResolver
    from unittest.mock import patch, MagicMock

    # 元の real_class を退避
    original_real = ThumbnailResolver._real_class
    
    # 完全にダミーの実クラスを用意
    class MockRealClass:
        def __init__(self, key="default"):
            self.key = key
        def generate_thumbnail(self, output_path, text=""):
            return "original"

    ThumbnailResolver._real_class = MockRealClass

    try:
        # 1. クラスレベルでメソッドと __init__ をモック化する
        mock_init_called = []
        def mock_init(self, key="mocked"):
            mock_init_called.append(key)

        mock_generate = MagicMock(return_value="mocked_thumbnail")

        with patch.object(ThumbnailResolver, "__init__", mock_init), \
             patch.object(ThumbnailResolver, "generate_thumbnail", mock_generate):
            
            # 2. インスタンス生成（__new__ が走り、mock_init が呼ばれるはず）
            resolver = ThumbnailResolver(key="test_key")
            
            # 3. アサーション
            # __init__ の実行検証
            assert mock_init_called == ["test_key"]
            
            # メソッドの実行検証
            res = resolver.generate_thumbnail("path", "text")
            assert res == "mocked_thumbnail"
            mock_generate.assert_called_once_with(resolver, "path", "text")

    finally:
        ThumbnailResolver._real_class = original_real

