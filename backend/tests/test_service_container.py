"""
test_service_container.py — ServiceContainer のユニットテスト
全メソッド・全分岐をカバー。ファクトリー関数のモックテスト含む。
"""
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

_backend_dir = str(Path(__file__).resolve().parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from service_container import ServiceContainer, setup_services, container


class TestServiceContainer:
    """ServiceContainer クラスのユニットテスト"""

    def test_register_and_get(self):
        sc = ServiceContainer()
        sc.register("test_svc", "hello")
        assert sc.get("test_svc") == "hello"

    def test_register_lazy_and_get(self):
        sc = ServiceContainer()
        sc.register_lazy("lazy_svc", lambda: {"key": "value"})
        result = sc.get("lazy_svc")
        assert result == {"key": "value"}
        # 2回目はキャッシュ
        assert sc.get("lazy_svc") is result

    def test_lazy_factory_removed_after_init(self):
        sc = ServiceContainer()
        sc.register_lazy("once", lambda: 42)
        sc.get("once")
        assert "once" not in sc._factories
        assert "once" in sc._instances

    def test_get_unknown_raises_keyerror(self):
        sc = ServiceContainer()
        with pytest.raises(KeyError, match="not_registered"):
            sc.get("not_registered")

    def test_lazy_factory_exception_propagates(self):
        sc = ServiceContainer()
        sc.register_lazy("broken", lambda: 1 / 0)
        with pytest.raises(ZeroDivisionError):
            sc.get("broken")

    def test_override(self):
        sc = ServiceContainer()
        sc.register("svc", "original")
        sc.override("svc", "mocked")
        assert sc.get("svc") == "mocked"

    def test_override_removes_factory(self):
        sc = ServiceContainer()
        sc.register_lazy("svc", lambda: "from_factory")
        sc.override("svc", "direct")
        assert sc.get("svc") == "direct"
        assert "svc" not in sc._factories

    def test_has(self):
        sc = ServiceContainer()
        assert sc.has("x") is False
        sc.register("x", 1)
        assert sc.has("x") is True

    def test_has_lazy(self):
        sc = ServiceContainer()
        sc.register_lazy("y", lambda: 2)
        assert sc.has("y") is True

    def test_reset(self):
        sc = ServiceContainer()
        sc.register("a", 1)
        sc.register_lazy("b", lambda: 2)
        sc._initialized = True
        sc.reset()
        assert sc.has("a") is False
        assert sc.has("b") is False
        assert sc._initialized is False

    def test_registered_services(self):
        sc = ServiceContainer()
        sc.register("alpha", 1)
        sc.register_lazy("beta", lambda: 2)
        sc.register("gamma", 3)
        services = sc.registered_services
        assert "alpha" in services
        assert "beta" in services
        assert "gamma" in services
        # ソート済み
        assert services == sorted(services)

    def test_circular_dependency_detection(self):
        """循環参照が検出され、ValueErrorが発生することを確認"""
        sc = ServiceContainer()
        sc.register_lazy("A", lambda: sc.get("B"))
        sc.register_lazy("B", lambda: sc.get("A"))

        with pytest.raises(ValueError, match="Circular dependency detected"):
            sc.get("A")

        # 例外発生後に初期化中セットがクリーンアップされていること
        assert "A" not in sc._initializing
        assert "B" not in sc._initializing

    def test_thread_safety(self):
        """マルチスレッド環境での安全な遅延初期化を確認"""
        import threading
        import time

        sc = ServiceContainer()
        init_count = 0
        init_lock = threading.Lock()

        def slow_factory():
            nonlocal init_count
            time.sleep(0.05)  # 競合を発生しやすくする
            with init_lock:
                init_count += 1
            return f"instance-{init_count}"

        sc.register_lazy("slow_svc", slow_factory)

        results = []
        threads = []

        def worker():
            res = sc.get("slow_svc")
            results.append(res)

        # 5つのスレッドで同時に取得を試みる
        for _ in range(5):
            t = threading.Thread(target=worker)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # ファクトリーは1回しか実行されていないこと
        assert init_count == 1
        # すべてのスレッドが同じインスタンスを取得できたこと
        assert len(results) == 5
        assert all(r == "instance-1" for r in results)

    def test_get_logs_detailed_exception(self):
        """ServiceContainer.get 初期化失敗時に exc_info=True でエラーログが出力されること"""
        sc = ServiceContainer()
        sc.register_lazy("broken", lambda: 1 / 0)
        with patch("service_container.logger.error") as mock_error:
            with pytest.raises(ZeroDivisionError):
                sc.get("broken")
            mock_error.assert_called_once()
            _, kwargs = mock_error.call_args
            assert kwargs.get("exc_info") is True


class TestSetupServices:
    """setup_services() のテスト"""

    def test_setup_registers_services(self):
        container.reset()
        setup_services()
        assert container._initialized is True
        assert container.has("usage_tracker")
        assert container.has("youtube_analytics")
        assert container.has("speaker_diarizer")
        assert container.has("branding_manager")
        assert container.has("pipeline_coordinator")
        assert container.has("gemini_client")
        assert container.has("youtube_optimizer")
        assert container.has("thumbnail_plugin")
        assert container.has("harness_hook_system")
        assert container.has("harness_session_manager")
        assert container.has("harness_governance")
        assert container.has("harness_tool_registry")

    def test_setup_idempotent(self):
        container.reset()
        setup_services()
        initial_count = len(container.registered_services)
        setup_services()  # 2回目
        assert len(container.registered_services) == initial_count

    def test_branding_manager_import_error(self):
        """BrandingManager がない場合 None を返す (L172-177)"""
        sc = ServiceContainer()
        with patch.dict(sys.modules, {"branding_manager": None}):
            from service_container import _init_branding_manager
            sc.register_lazy("branding_manager", lambda: _init_branding_manager())
            result = sc.get("branding_manager")
            assert result is None

    def test_factory_functions_handle_import_error(self):
        """各ファクトリー関数のImportErrorフォールバック"""
        from service_container import (
            _init_branding_manager,
            _init_pipeline_coordinator,
            _init_gemini_client,
            _init_harness_hooks,
            _init_harness_sessions,
            _init_harness_governance,
            _init_harness_tools,
            _init_youtube_optimizer,
            _init_thumbnail_plugin,
        )

        # branding_manager — ImportError 時 None
        with patch.dict(sys.modules, {"branding_manager": None}):
            assert _init_branding_manager() is None

        # pipeline_coordinator — ImportError 時 None
        with patch.dict(sys.modules, {"agents.pipeline_coordinator": None}):
            assert _init_pipeline_coordinator() is None

        # gemini_client — Exception 時 None
        with patch.dict(sys.modules, {"gemini_client_factory": None}):
            assert _init_gemini_client() is None

        # harness hooks — ImportError 時 None
        with patch.dict(sys.modules, {"harness.hooks": None}):
            assert _init_harness_hooks() is None

        # harness sessions
        with patch.dict(sys.modules, {"harness.session_manager": None}):
            assert _init_harness_sessions() is None

        # harness governance
        with patch.dict(sys.modules, {"harness.governance": None}):
            assert _init_harness_governance() is None

        # harness tools
        with patch.dict(sys.modules, {"harness.tool_registry": None}):
            assert _init_harness_tools() is None

        # youtube_optimizer
        with patch.dict(sys.modules, {"plugins.youtube_optimizer_plugin": None}):
            assert _init_youtube_optimizer() is None

        # thumbnail_plugin
        with patch.dict(sys.modules, {"plugins.thumbnail_plugin": None}):
            assert _init_thumbnail_plugin() is None

    def test_factory_functions_success(self):
        """各ファクトリー関数の正常系初期化テスト"""
        from service_container import (
            _init_usage_tracker,
            _init_youtube_analytics,
            _init_youtube_optimizer,
            _init_thumbnail_plugin,
            _init_speaker_diarizer,
            _init_branding_manager,
            _init_pipeline_coordinator,
            _init_gemini_client,
            _init_harness_hooks,
            _init_harness_sessions,
            _init_harness_governance,
            _init_harness_tools,
        )

        # Usage Tracker (正常系はPath指定あり)
        assert _init_usage_tracker() is not None

        # YouTube Analytics
        assert _init_youtube_analytics() is not None

        # Speaker Diarizer
        assert _init_speaker_diarizer() is not None

        # YouTube Optimizer
        # モジュールが存在していればインスタンス、無ければNoneになるはず
        yt_opt = _init_youtube_optimizer()
        try:
            from plugins.youtube_optimizer_plugin import youtube_optimizer
            assert yt_opt is youtube_optimizer
        except ImportError:
            assert yt_opt is None

        # Thumbnail Plugin
        thumb = _init_thumbnail_plugin()
        try:
            from plugins.thumbnail_plugin import ThumbnailPlugin
            assert isinstance(thumb, ThumbnailPlugin)
        except ImportError:
            assert thumb is None

        # Branding Manager
        branding = _init_branding_manager()
        try:
            from branding_manager import BrandingManager
            assert isinstance(branding, BrandingManager)
        except ImportError:
            assert branding is None

        # Pipeline Coordinator
        coord = _init_pipeline_coordinator()
        try:
            from agents.pipeline_coordinator import PipelineCoordinator
            assert isinstance(coord, PipelineCoordinator)
        except ImportError:
            assert coord is None

        # Gemini Client
        gemini = _init_gemini_client()
        try:
            from gemini_client_factory import get_gemini_client
            assert gemini is not None
        except Exception:
            assert gemini is None

        # Harness hooks
        hooks = _init_harness_hooks()
        try:
            from harness.hooks import hook_system
            assert hooks is hook_system
        except ImportError:
            assert hooks is None

        # Harness sessions
        sessions = _init_harness_sessions()
        try:
            from harness.session_manager import session_manager
            assert sessions is session_manager
        except ImportError:
            assert sessions is None

        # Harness governance
        gov = _init_harness_governance()
        try:
            from harness.governance import governance_engine
            assert gov is governance_engine
        except ImportError:
            assert gov is None

        # Harness tools
        tools = _init_harness_tools()
        try:
            from harness.tool_registry import tool_registry
            assert tools is tool_registry
        except ImportError:
            assert tools is None

    def test_init_gemini_client_different_exceptions(self):
        """_init_gemini_client の例外ハンドリングの検証"""
        from service_container import _init_gemini_client

        # 1. ImportError / ModuleNotFoundError 時は logger.info が呼ばれ、None が返ること
        with patch.dict("sys.modules", {"gemini_client_factory": None}):
            with patch("service_container.logger.info") as mock_info:
                result = _init_gemini_client()
                assert result is None
                mock_info.assert_called_once()
                args, _ = mock_info.call_args
                assert "not available" in args[0]

        # 2. その他の例外発生時は logger.error が exc_info=True で呼ばれ、None が返ること
        mock_factory = MagicMock()
        mock_factory.get_gemini_client.side_effect = ValueError("Config error")
        with patch.dict("sys.modules", {"gemini_client_factory": mock_factory}):
            if "gemini_client_factory" in sys.modules:
                del sys.modules["gemini_client_factory"]
            sys.modules["gemini_client_factory"] = mock_factory
            try:
                with patch("service_container.logger.error") as mock_error:
                    result = _init_gemini_client()
                    assert result is None
                    mock_error.assert_called_once()
                    args, kwargs = mock_error.call_args
                    assert "Gemini client init failed" in args[0]
                    assert kwargs.get("exc_info") is True
            finally:
                if "gemini_client_factory" in sys.modules:
                    del sys.modules["gemini_client_factory"]
