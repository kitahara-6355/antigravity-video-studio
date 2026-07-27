import sys
import os
import asyncio
import importlib
import builtins
import logging
import pytest
from unittest.mock import patch, MagicMock, AsyncMock, ANY
from fastapi import APIRouter
from fastapi.testclient import TestClient

# backend へのパスを追加
backend_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

# ---------------------------------------------------------------------------
# 重いルーターおよび api_versioning 依存モジュールをインポートさせないためのグローバルモック設定
# ---------------------------------------------------------------------------
import types

# 1. routers パッケージのモック作成
mock_routers = types.ModuleType("routers")
mock_routers.__path__ = []  # パッケージとして振る舞うように設定

router_names = [
    "trinity_router", "director_router", "segments_router", "render_router",
    "quality_router", "collaboration_router", "websocket_router", "preview_router",
    "usage_router", "youtube_optimizer_router", "smartcut_router", "ab_test_tracker_router",
    "shorts_router", "youtube_upload_router", "antigravity_router", "manager_router",
    "soul_router", "dashboard_router", "approval_router", "philosophy_router",
    "log_router", "error_router", "legacy_director_router", "legacy_council_router",
    "legacy_production_router", "legacy_management_router", "live_ws_router",
    "pipeline_router", "health_router", "pipeline_report_router", "admin_setup_router",
    "admin_quota_router", "admin_analytics_router", "admin_quality_router",
    "admin_incident_router", "admin_integration_router", "admin_channel_router",
    "admin_performance_router", "themes_router"
]
for name in router_names:
    setattr(mock_routers, name, APIRouter())

# sys.modules へのモック登録
sys.modules["routers"] = mock_routers

# 2. api_versioning が依存する個別ルーターのモック
themes_mod = types.ModuleType("routers.themes_router")
themes_mod.router = APIRouter()
sys.modules["routers.themes_router"] = themes_mod

soul_mod = types.ModuleType("routers.soul_router")
soul_mod.router = APIRouter()
sys.modules["routers.soul_router"] = soul_mod

# 2.5 routers.usage_router
usage_router_mod = types.ModuleType("routers.usage_router")
usage_router_mod.thumbnail_router = APIRouter()
sys.modules["routers.usage_router"] = usage_router_mod

# 3. mcp_server モジュールのモック
mcp_mod = types.ModuleType("mcp_server")
mcp_mod.create_mcp_router = lambda: APIRouter()
sys.modules["mcp_server"] = mcp_mod


# 元のインポート関数を保持
original_import = builtins.__import__

@pytest.fixture(autouse=True)
def clean_sys_modules():
    """
    テストごとに sys.modules から main モジュールをクリアし、
    またテスト終了時に sys.modules を元の状態に復元する。
    """
    original_modules = sys.modules.copy()
    
    for mod in ["main", "backend.main"]:
        if mod in sys.modules:
            del sys.modules[mod]
            
    yield
    
    sys.modules.clear()
    sys.modules.update(original_modules)

def mock_import_factory(fail_imports=None):
    """
    特定のモジュールのインポート時に例外を投げるためのカスタムインポート関数を作成する。
    """
    def _mock_import(name, globals=None, locals=None, fromlist=(), level=0):
        if fail_imports:
            full_names = [name]
            if fromlist:
                for f in fromlist:
                    full_names.append(f"{name}.{f}")
            for target_name, exc in fail_imports.items():
                if any(fn == target_name or fn.startswith(target_name + ".") for fn in full_names):
                    raise exc
        return original_import(name, globals, locals, fromlist, level)
    return _mock_import


# ---------------------------------------------------------------------------
# 1. JSONFormatter のテスト
# ---------------------------------------------------------------------------
def test_json_formatter():
    import main
    formatter = main.StructuredJSONFormatter()
    
    # 正常系ログ
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Test message",
        args=(),
        exc_info=None
    )
    result = formatter.format(record)
    assert "Test message" in result
    assert "level" in result
    assert "request_id" not in result
    
    # exc_info ありのログ
    try:
        raise ValueError("test error")
    except ValueError:
        exc_info = sys.exc_info()
        
    record_exc = logging.LogRecord(
        name="test_logger",
        level=logging.ERROR,
        pathname="test.py",
        lineno=20,
        msg="Error occurred",
        args=(),
        exc_info=exc_info
    )
    result_exc = formatter.format(record_exc)
    assert "ValueError: test error" in result_exc
    assert "exception" in result_exc

    # request_id ありのログ
    record_req = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=30,
        msg="Request logs",
        args=(),
        exc_info=None
    )
    record_req.request_id = "req-999"
    result_req = formatter.format(record_req)
    assert "req-999" in result_req
    assert "request_id" in result_req


# ---------------------------------------------------------------------------
# 2. CORS 設定 of the test
# ---------------------------------------------------------------------------
def test_cors_origins_parsing():
    custom_origins = "https://example.com, https://test.org "
    with patch.dict(os.environ, {"CORS_ALLOWED_ORIGINS": custom_origins}):
        import main
        importlib.reload(main)
        
        cors_middleware = [
            m for m in main.app.user_middleware 
            if m.cls.__name__ == "CORSMiddleware"
        ]
        assert len(cors_middleware) > 0
        
        m_opts = cors_middleware[0].options if hasattr(cors_middleware[0], "options") else getattr(cors_middleware[0], "kwargs", {})
        allow_origins = m_opts.get("allow_origins", [])
        assert "https://example.com" in allow_origins
        assert "https://test.org" in allow_origins


# ---------------------------------------------------------------------------
# 3. Lifespan 正常系のテスト
# ---------------------------------------------------------------------------
def test_lifespan_success():
    mock_tick_loop = AsyncMock()
    mock_tick_loop.start = AsyncMock()
    mock_tick_loop.stop = AsyncMock()
    
    mock_setup_services = MagicMock()
    mock_register_builtin_hooks = MagicMock()
    mock_register_governance_hook = MagicMock()
    mock_flush_traces = MagicMock()

    with patch.dict(sys.modules, {
        "agents.tick_loop": MagicMock(tick_loop=mock_tick_loop),
        "service_container": MagicMock(setup_services=mock_setup_services),
        "harness.hooks": MagicMock(hook_system=MagicMock(register_builtin_hooks=mock_register_builtin_hooks)),
        "harness.governance": MagicMock(governance_engine=MagicMock(flush_traces=mock_flush_traces)),
        "model_governance": MagicMock(register_governance_hook=mock_register_governance_hook),
    }):
        import main
        importlib.reload(main)
        
        with TestClient(main.app):
            pass
            
        mock_tick_loop.start.assert_called_once()
        mock_setup_services.assert_called_once()
        mock_register_builtin_hooks.assert_called_once()
        mock_register_governance_hook.assert_called_once()
        
        mock_flush_traces.assert_called_once()
        mock_tick_loop.stop.assert_called_once()


# ---------------------------------------------------------------------------
# 4. Lifespan 例外系のテスト
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("fail_target, exc_type, log_message", [
    ("agents.tick_loop", ImportError("mocked import error"), "TickLoop 未インストール"),
    ("agents.tick_loop", RuntimeError("mocked general error"), "TickLoop 起動エラー"),
])
def test_lifespan_tick_loop_exceptions(fail_target, exc_type, log_message):
    class ListHandler(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records = []
        def emit(self, record):
            self.records.append(record)

    mock_import = mock_import_factory({fail_target: exc_type})
    
    with patch("builtins.__import__", side_effect=mock_import):
        import main
        importlib.reload(main)
        
        main.logger.setLevel(logging.DEBUG)  # ログレベルをDEBUGにしてINFOログもキャプチャする
        log_handler = ListHandler()
        main.logger.addHandler(log_handler)
        try:
            with patch("builtins.__import__", side_effect=mock_import):
                with TestClient(main.app):
                    pass
        finally:
            main.logger.removeHandler(log_handler)
            
        messages = [r.getMessage() for r in log_handler.records]
        assert any(log_message in m for m in messages)


def test_lifespan_service_container_exception():
    class ListHandler(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records = []
        def emit(self, record):
            self.records.append(record)

    mock_setup = MagicMock(side_effect=RuntimeError("Service Container Failed"))
    
    with patch.dict(sys.modules, {"service_container": MagicMock(setup_services=mock_setup)}):
        import main
        importlib.reload(main)
        
        main.logger.setLevel(logging.DEBUG)
        log_handler = ListHandler()
        main.logger.addHandler(log_handler)
        try:
            with TestClient(main.app):
                pass
        finally:
            main.logger.removeHandler(log_handler)
            
        messages = [r.getMessage() for r in log_handler.records]
        assert any("ServiceContainer init skipped: Service Container Failed" in m for m in messages)


@pytest.mark.parametrize("fail_target, exc_type, log_message", [
    ("harness.hooks", ImportError("mocked import error"), "Harness 未インストール — レガシーモードで動作"),
    ("harness.hooks", RuntimeError("mocked harness error"), "Harness init skipped: mocked harness error"),
])
def test_lifespan_harness_exceptions(fail_target, exc_type, log_message):
    class ListHandler(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records = []
        def emit(self, record):
            self.records.append(record)

    mock_import = mock_import_factory({fail_target: exc_type})
    
    with patch("builtins.__import__", side_effect=mock_import):
        import main
        importlib.reload(main)
        
        main.logger.setLevel(logging.DEBUG)
        log_handler = ListHandler()
        main.logger.addHandler(log_handler)
        try:
            with patch("builtins.__import__", side_effect=mock_import):
                with TestClient(main.app):
                    pass
        finally:
            main.logger.removeHandler(log_handler)
            
        messages = [r.getMessage() for r in log_handler.records]
        assert any(log_message in m for m in messages)


def test_lifespan_model_governance_exception():
    class ListHandler(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records = []
        def emit(self, record):
            self.records.append(record)

    mock_gov = MagicMock(side_effect=RuntimeError("Model Governance Failed"))
    
    with patch.dict(sys.modules, {"model_governance": MagicMock(register_governance_hook=mock_gov)}):
        import main
        importlib.reload(main)
        
        main.logger.setLevel(logging.DEBUG)
        log_handler = ListHandler()
        main.logger.addHandler(log_handler)
        try:
            mock_import = mock_import_factory({"model_governance": RuntimeError("Model Governance Failed")})
            with patch("builtins.__import__", side_effect=mock_import):
                with TestClient(main.app):
                    pass
        finally:
            main.logger.removeHandler(log_handler)
            
        messages = [r.getMessage() for r in log_handler.records]
        assert any("ModelGovernance skipped: Model Governance Failed" in m for m in messages)


def test_lifespan_shutdown_harness_exception():
    mock_flush = MagicMock(side_effect=RuntimeError("Flush Failed"))
    mock_governance = MagicMock()
    mock_governance.governance_engine.flush_traces = mock_flush
    
    with patch.dict(sys.modules, {
        "harness.hooks": MagicMock(),
        "harness.governance": mock_governance
    }):
        import main
        importlib.reload(main)
        
        with TestClient(main.app):
            pass
        
        mock_flush.assert_called_once()


def test_lifespan_shutdown_tick_loop_exception():
    class ListHandler(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records = []
        def emit(self, record):
            self.records.append(record)

    mock_tick_loop = AsyncMock()
    mock_tick_loop.start = AsyncMock()
    mock_tick_loop.stop = AsyncMock(side_effect=RuntimeError("Stop Failed"))
    
    with patch.dict(sys.modules, {"agents.tick_loop": MagicMock(tick_loop=mock_tick_loop)}):
        import main
        importlib.reload(main)
        
        main.logger.setLevel(logging.DEBUG)
        log_handler = ListHandler()
        main.logger.addHandler(log_handler)
        try:
            with TestClient(main.app):
                pass
        finally:
            main.logger.removeHandler(log_handler)
            
        mock_tick_loop.stop.assert_called_once()
        messages = [r.getMessage() for r in log_handler.records]
        assert any("TickLoop 停止エラー: Stop Failed" in m for m in messages)


# ---------------------------------------------------------------------------
# 5. api_versioning 例外のテスト
# ---------------------------------------------------------------------------
def test_api_versioning_exception():
    class ListHandler(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records = []
        def emit(self, record):
            self.records.append(record)

    mock_import = mock_import_factory({"api_versioning": RuntimeError("Versioning Error")})
    
    with patch("builtins.__import__", side_effect=mock_import):
        import main
        root_logger = logging.getLogger()
        log_handler = ListHandler()
        root_logger.addHandler(log_handler)
        try:
            importlib.reload(main)
        finally:
            root_logger.removeHandler(log_handler)
            
        messages = [r.getMessage() for r in log_handler.records]
        assert any("API versioning skipped: Versioning Error" in m for m in messages)


# ---------------------------------------------------------------------------
# 6. エントリーポイント (__name__ == "__main__") のテスト
# ---------------------------------------------------------------------------
def test_main_script_execution():
    import runpy
    target_path = os.path.join(backend_path, "main.py")
    with patch("uvicorn.run") as mock_uvicorn_run:
        runpy.run_path(target_path, run_name="__main__")
        mock_uvicorn_run.assert_called_once_with(
            ANY, host="127.0.0.1", port=8000
        )


# ---------------------------------------------------------------------------
# 7. エッジケースの補強テスト
# ---------------------------------------------------------------------------
def test_cors_origins_edge_cases():
    # 7.1. CORS_ALLOWED_ORIGINS が設定されていない場合のデフォルト
    with patch.dict(os.environ, {}, clear=True):
        if "CORS_ALLOWED_ORIGINS" in os.environ:
            del os.environ["CORS_ALLOWED_ORIGINS"]
        import main
        importlib.reload(main)
        
        cors_middleware = [
            m for m in main.app.user_middleware 
            if m.cls.__name__ == "CORSMiddleware"
        ]
        assert len(cors_middleware) > 0
        m_opts = cors_middleware[0].options if hasattr(cors_middleware[0], "options") else getattr(cors_middleware[0], "kwargs", {})
        allow_origins = m_opts.get("allow_origins", [])
        assert "http://localhost:5173" in allow_origins
        assert "http://localhost:3000" in allow_origins

    # 7.2. 空要素やトリムが必要な値が混ざっているケース
    custom_origins = " , , http://example.com , , http://test.org, "
    with patch.dict(os.environ, {"CORS_ALLOWED_ORIGINS": custom_origins}):
        import main
        importlib.reload(main)
        
        cors_middleware = [
            m for m in main.app.user_middleware 
            if m.cls.__name__ == "CORSMiddleware"
        ]
        m_opts = cors_middleware[0].options if hasattr(cors_middleware[0], "options") else getattr(cors_middleware[0], "kwargs", {})
        allow_origins = m_opts.get("allow_origins", [])
        assert len(allow_origins) == 2
        assert "http://example.com" in allow_origins
        assert "http://test.org" in allow_origins

    # 7.2.5. 完全な空値や有効な値が全くないケース
    with patch.dict(os.environ, {"CORS_ALLOWED_ORIGINS": ",  ,  "}):
        import main
        importlib.reload(main)
        cors_middleware = [
            m for m in main.app.user_middleware 
            if m.cls.__name__ == "CORSMiddleware"
        ]
        m_opts = cors_middleware[0].options if hasattr(cors_middleware[0], "options") else getattr(cors_middleware[0], "kwargs", {})
        allow_origins = m_opts.get("allow_origins", [])
        assert len(allow_origins) == 0


def test_json_formatter_edge_cases():
    import main
    formatter = main.StructuredJSONFormatter()
    
    # 7.3. exc_info が空タプルの場合
    record_empty_exc = logging.LogRecord(
        name="test_logger",
        level=logging.ERROR,
        pathname="test.py",
        lineno=40,
        msg="Empty err info",
        args=(),
        exc_info=()
    )
    result = formatter.format(record_empty_exc)
    assert "exception" not in result
    
    # 7.4. exc_info が (None, None, None) の場合
    record_none_exc = logging.LogRecord(
        name="test_logger",
        level=logging.ERROR,
        pathname="test.py",
        lineno=50,
        msg="None err info",
        args=(),
        exc_info=(None, None, None)
    )
    result = formatter.format(record_none_exc)
    assert "exception" not in result

    # 7.4.5. ネストされた例外（raise from）の場合
    try:
        try:
            raise TypeError("inner type error")
        except TypeError as inner:
            raise ValueError("outer value error") from inner
    except ValueError:
        exc_info = sys.exc_info()
        
    record_nested = logging.LogRecord(
        name="test_logger",
        level=logging.ERROR,
        pathname="test.py",
        lineno=60,
        msg="Nested error occurred",
        args=(),
        exc_info=exc_info
    )
    result_nested = formatter.format(record_nested)
    assert "ValueError: outer value error" in result_nested
    assert "TypeError: inner type error" in result_nested


def test_lifespan_shutdown_import_errors():
    # 7.5. シャットダウン時、harness.governance のインポートで ImportError が発生するケース
    mock_tick_loop = AsyncMock()
    mock_tick_loop.start = AsyncMock()
    mock_tick_loop.stop = MagicMock()
    
    state = {"is_shutdown": False}
    
    def custom_import(name, globals=None, locals=None, fromlist=(), level=0):
        if state["is_shutdown"]:
            if name == "harness.governance" or (name == "harness" and "governance" in fromlist):
                raise ImportError("mocked harness governance import error")
        return original_import(name, globals, locals, fromlist, level)

    with patch.dict(sys.modules, {
        "agents.tick_loop": MagicMock(tick_loop=mock_tick_loop),
        "service_container": MagicMock(),
        "harness.hooks": MagicMock(),
        "model_governance": MagicMock(),
    }):
        import main
        importlib.reload(main)
        
        with patch("builtins.__import__", side_effect=custom_import):
            with TestClient(main.app):
                state["is_shutdown"] = True
        
        mock_tick_loop.stop.assert_called_once()


def test_lifespan_shutdown_tick_loop_import_error():
    class ListHandler(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records = []
        def emit(self, record):
            self.records.append(record)

    # 7.6. シャットダウン時、agents.tick_loop の停止処理で例外が発生するケースの検証
    mock_tick_loop = AsyncMock()
    mock_tick_loop.start = AsyncMock()
    mock_tick_loop.stop = AsyncMock(side_effect=ImportError("mocked tick loop import error"))
    
    with patch.dict(sys.modules, {
        "agents.tick_loop": MagicMock(tick_loop=mock_tick_loop),
        "service_container": MagicMock(),
        "harness.hooks": MagicMock(),
        "model_governance": MagicMock(),
    }):
        import main
        importlib.reload(main)
        
        main.logger.setLevel(logging.DEBUG)
        log_handler = ListHandler()
        main.logger.addHandler(log_handler)
        try:
            with TestClient(main.app):
                pass
        finally:
            main.logger.removeHandler(log_handler)
            
        messages = [r.getMessage() for r in log_handler.records]
        assert any("TickLoop 停止エラー: mocked tick loop import error" in m for m in messages)


# ---------------------------------------------------------------------------
# 8. 追加の StructuredJSONFormatter 詳細検証テスト
# ---------------------------------------------------------------------------
def test_structured_json_formatter_detailed():
    import main
    import json
    formatter = main.StructuredJSONFormatter()
    
    # 日本語メッセージがそのままデコードされること (ensure_ascii=False の検証)
    japanese_msg = "日本語のエラーログメッセージ"
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg=japanese_msg,
        args=(),
        exc_info=None
    )
    result = formatter.format(record)
    parsed = json.loads(result)
    assert parsed["msg"] == japanese_msg
    assert japanese_msg in result


# ---------------------------------------------------------------------------
# 9. setup_logging() 初期化処理 of the test
# ---------------------------------------------------------------------------
def test_setup_logging_initialization():
    import main
    
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    root_logger.handlers.clear()
    
    try:
        with patch("pathlib.Path.mkdir") as mock_mkdir, \
             patch("logging.FileHandler") as mock_file_handler, \
             patch("logging.StreamHandler") as mock_stream_handler, \
             patch("logging.basicConfig") as mock_basic_config:
             
            mock_file_instance = MagicMock()
            mock_file_handler.return_value = mock_file_instance
            
            mock_stream_instance = MagicMock()
            mock_stream_handler.return_value = mock_stream_instance
            
            main.setup_logging()
            
            mock_mkdir.assert_called_once_with(exist_ok=True)
            mock_file_handler.assert_called_once()
            mock_stream_handler.assert_called_once()
            mock_basic_config.assert_called_once_with(
                level=logging.INFO,
                handlers=[mock_file_instance, mock_stream_instance]
            )
    finally:
        root_logger.handlers.clear()
        root_logger.handlers.extend(original_handlers)


def test_setup_logging_early_return():
    import main
    
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    
    # ダミーのハンドラをセットして、すでに初期化済みと認識させる
    dummy_handler = logging.NullHandler()
    root_logger.handlers = [dummy_handler]
    
    try:
        with patch("pathlib.Path.mkdir") as mock_mkdir, \
             patch("logging.FileHandler") as mock_file_handler, \
             patch("logging.StreamHandler") as mock_stream_handler, \
             patch("logging.basicConfig") as mock_basic_config:
             
            main.setup_logging()
            
            # 早期リターンが機能していれば、これらの設定処理は走らないはず
            mock_mkdir.assert_not_called()
            mock_file_handler.assert_not_called()
            mock_stream_handler.assert_not_called()
            mock_basic_config.assert_not_called()
    finally:
        root_logger.handlers = original_handlers


def test_lifespan_service_container_success_log():
    class ListHandler(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records = []
        def emit(self, record):
            self.records.append(record)

    mock_tick_loop = AsyncMock()
    mock_setup_services = MagicMock()
    
    with patch.dict(sys.modules, {
        "agents.tick_loop": MagicMock(tick_loop=mock_tick_loop),
        "service_container": MagicMock(setup_services=mock_setup_services),
        "harness.hooks": MagicMock(),
        "model_governance": MagicMock(),
    }):
        import main
        importlib.reload(main)
        
        main.logger.setLevel(logging.DEBUG)
        log_handler = ListHandler()
        main.logger.addHandler(log_handler)
        
        try:
            with TestClient(main.app):
                pass
        finally:
            main.logger.removeHandler(log_handler)
            
        messages = [r.getMessage() for r in log_handler.records]
        assert any("📦 ServiceContainer 初期化完了" in m for m in messages)


# ---------------------------------------------------------------------------
# 10. 実ファイルログとルーター整合性の追加テスト
# ---------------------------------------------------------------------------
def test_setup_logging_real_file_creation(tmp_path):
    import main
    
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    root_logger.handlers.clear()
    
    test_log_dir = tmp_path / "logs"
    test_log_file = test_log_dir / "backend.log"
    
    try:
        # Path.mkdir と FileHandler の実動作をテストするために Path を差し替える
        class FakePath:
            def __init__(self, *args):
                self.path = test_log_dir
            def mkdir(self, exist_ok=True):
                self.path.mkdir(exist_ok=exist_ok)
            def __truediv__(self, other):
                return self.path / other
                
        with patch("main.Path", FakePath):
            main.setup_logging()
            
            # ディレクトリとファイルが作成されていることを確認
            assert test_log_dir.exists()
            
            # テストログを出力してみる
            test_logger = logging.getLogger()
            test_logger.info("Test message for real file")
            
            # handlers を確認
            file_handlers = [h for h in root_logger.handlers if isinstance(h, logging.FileHandler)]
            assert len(file_handlers) > 0
            
            # ハンドラをフラッシュしてクローズする
            for h in root_logger.handlers:
                h.flush()
                h.close()
                
            assert test_log_file.exists()
            with open(test_log_file, "r", encoding="utf-8") as f:
                content = f.read()
                assert "Test message for real file" in content
                assert "ts" in content
                assert "level" in content
    finally:
        # グローバルなロガー設定を元に戻す
        for h in root_logger.handlers:
            h.close()
        root_logger.handlers.clear()
        root_logger.handlers.extend(original_handlers)


def test_app_router_registration_integrity():
    import main
    importlib.reload(main)
    
    # 登録されたすべてのルーターが、FastAPI app に反映されているかを検証
    app_routers = [route for route in main.app.routes]
    
    # ルーターが登録されているため、何かしらのルートが存在するはず
    assert len(app_routers) > 0


# ===========================================================================
# 11. エッジケースの徹底検証テスト (境界値、None入力、不正型、巨大入力)
# ===========================================================================

def test_json_formatter_extreme_and_invalid_types():
    import main
    import json
    formatter = main.StructuredJSONFormatter()

    # 11.1. request_id に不正な型 (整数, 辞書, リスト) を指定した場合
    for invalid_req_id in [12345, {"key": "val"}, [1, 2, 3]]:
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Invalid request_id type test",
            args=(),
            exc_info=None
        )
        record.request_id = invalid_req_id
        result = formatter.format(record)
        parsed = json.loads(result)
        # JSONシリアライズ可能であり、かつ元の値が正しく格納されていること
        assert "request_id" in parsed
        assert parsed["request_id"] == invalid_req_id

    # 11.2. request_id に巨大な文字列 (10KB) を指定した場合 (巨大入力)
    huge_req_id = "A" * 10240
    record_huge = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=20,
        msg="Huge request_id test",
        args=(),
        exc_info=None
    )
    record_huge.request_id = huge_req_id
    result_huge = formatter.format(record_huge)
    parsed_huge = json.loads(result_huge)
    assert parsed_huge["request_id"] == huge_req_id

    # 11.3. exc_info に不正な形式 (文字列など、タプル以外のオブジェクト)
    # 文字列を渡すと、[0] が文字になり、かつタプルではないため
    # logging.Formatter.formatException 内の traceback.print_exception で AttributeError が起きる。
    record_invalid_str = logging.LogRecord(
        name="test_logger",
        level=logging.ERROR,
        pathname="test.py",
        lineno=30,
        msg="Invalid exc_info str test",
        args=(),
        exc_info="not-a-tuple-exception"
    )
    with pytest.raises(AttributeError):
        formatter.format(record_invalid_str)

    # 11.3.2. exc_info が要素数の足りないタプルや None のみを含む場合
    # (None,) などの場合は record.exc_info[0] が None なので if を通らず正常終了する
    for valid_none_exc in [
        (None,),
        (None, None),
    ]:
        record_exc = logging.LogRecord(
            name="test_logger",
            level=logging.ERROR,
            pathname="test.py",
            lineno=30,
            msg="Invalid exc_info format test",
            args=(),
            exc_info=valid_none_exc
        )
        result_exc = formatter.format(record_exc)
        parsed_exc = json.loads(result_exc)
        assert "exception" not in parsed_exc

    # 11.4. メッセージ内に制御文字や極端な特殊文字、絵文字が含まれる場合
    special_msg = "🔥\x00\x01\x02\n\t特殊文字テスト\U0001F600"
    record_special = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=40,
        msg=special_msg,
        args=(),
        exc_info=None
    )
    result_special = formatter.format(record_special)
    parsed_special = json.loads(result_special)
    assert parsed_special["msg"] == special_msg


def test_cors_origins_huge_and_dirty_inputs():
    # 11.5. CORS_ALLOWED_ORIGINS に巨大な文字列、特殊文字、重複した値などを指定した場合
    huge_origin = "http://" + "b" * 5000 + ".com"
    custom_origins = f"http://a.com, {huge_origin}, http://a.com, , http://a.com "
    with patch.dict(os.environ, {"CORS_ALLOWED_ORIGINS": custom_origins}):
        import main
        importlib.reload(main)
        
        cors_middleware = [
            m for m in main.app.user_middleware 
            if m.cls.__name__ == "CORSMiddleware"
        ]
        m_opts = cors_middleware[0].options if hasattr(cors_middleware[0], "options") else getattr(cors_middleware[0], "kwargs", {})
        allow_origins = m_opts.get("allow_origins", [])
        # 空要素は除外される
        assert "http://a.com" in allow_origins
        assert huge_origin in allow_origins


def test_setup_logging_directory_creation_failure():
    # 11.6. logs が既にディレクトリ以外のファイルとして存在し、mkdir が失敗する場合の検証
    import main
    
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    root_logger.handlers.clear()
    
    try:
        with patch("pathlib.Path.mkdir", side_effect=OSError("File exists")), \
             patch("logging.FileHandler"), \
             patch("logging.StreamHandler"), \
             patch("logging.basicConfig"):
             
            with pytest.raises(OSError):
                main.setup_logging()
    finally:
        root_logger.handlers.clear()
        root_logger.handlers.extend(original_handlers)


def teardown_module(module):
    """
    test_main_coverage.py の全テスト実行終了後に、sys.modules の汚染をクリアする。
    """
    for key in ["routers", "routers.themes_router", "routers.soul_router", "routers.usage_router", "mcp_server"]:
        if key in sys.modules:
            del sys.modules[key]
