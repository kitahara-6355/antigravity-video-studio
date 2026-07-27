"""
高インパクトモジュール テスト — service_container.py / error_reporter.py
カバレッジ分子拡大: 本番コードの品質保証
"""

import pytest
import os
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock


# ============================================================
# ServiceContainer テスト (12件)
# ============================================================

class TestServiceContainer:
    """ServiceContainer DI パターンのテスト"""

    def _make_container(self):
        from service_container import ServiceContainer
        return ServiceContainer()

    def test_register_and_get(self):
        """register + get — 即時インスタンス"""
        c = self._make_container()
        c.register("svc", {"key": "value"})
        result = c.get("svc")
        assert result == {"key": "value"}

    def test_register_lazy_deferred_init(self):
        """register_lazy — 遅延初期化（get時に初めて呼ばれる）"""
        c = self._make_container()
        called = {"count": 0}
        def factory():
            called["count"] += 1
            return "lazy_instance"
        c.register_lazy("lazy_svc", factory)
        assert called["count"] == 0  # まだ呼ばれていない
        result = c.get("lazy_svc")
        assert result == "lazy_instance"
        assert called["count"] == 1

    def test_lazy_singleton(self):
        """register_lazy — 2回目以降はキャッシュ（シングルトン保証）"""
        c = self._make_container()
        call_count = {"n": 0}
        def factory():
            call_count["n"] += 1
            return f"instance_{call_count['n']}"
        c.register_lazy("svc", factory)
        r1 = c.get("svc")
        r2 = c.get("svc")
        assert r1 == r2 == "instance_1"
        assert call_count["n"] == 1  # 1回しか呼ばれない

    def test_get_unknown_raises(self):
        """get — 未登録サービス → KeyError"""
        c = self._make_container()
        with pytest.raises(KeyError, match="not registered"):
            c.get("nonexistent")

    def test_lazy_factory_error(self):
        """register_lazy — ファクトリー例外がそのまま伝播"""
        c = self._make_container()
        def bad_factory():
            raise RuntimeError("init failed")
        c.register_lazy("bad", bad_factory)
        with pytest.raises(RuntimeError, match="init failed"):
            c.get("bad")

    def test_override(self):
        """override — テスト用にモック差し替え"""
        c = self._make_container()
        c.register("svc", "original")
        c.override("svc", "mocked")
        assert c.get("svc") == "mocked"

    def test_override_removes_factory(self):
        """override — 遅延ファクトリーも削除される"""
        c = self._make_container()
        c.register_lazy("svc", lambda: "from_factory")
        c.override("svc", "override_value")
        assert c.get("svc") == "override_value"

    def test_has(self):
        """has — 登録確認"""
        c = self._make_container()
        assert c.has("x") is False
        c.register("x", 42)
        assert c.has("x") is True

    def test_has_lazy(self):
        """has — 遅延登録でもTrueを返す"""
        c = self._make_container()
        c.register_lazy("lazy", lambda: None)
        assert c.has("lazy") is True

    def test_reset(self):
        """reset — 全サービスクリア"""
        c = self._make_container()
        c.register("a", 1)
        c.register_lazy("b", lambda: 2)
        c.reset()
        assert c.has("a") is False
        assert c.has("b") is False

    def test_registered_services(self):
        """registered_services — サービス名一覧"""
        c = self._make_container()
        c.register("beta", 1)
        c.register_lazy("alpha", lambda: 2)
        names = c.registered_services
        assert names == ["alpha", "beta"]

    def test_setup_services_idempotent(self):
        """setup_services — 2回呼んでも安全"""
        from service_container import container, setup_services
        container.reset()
        setup_services()
        first_services = container.registered_services[:]
        setup_services()  # 2回目
        assert container.registered_services == first_services

    def _mock_import_failure(self, target_module: str):
        import builtins
        orig_import = builtins.__import__
        def mock_import(name, *args, **kwargs):
            if name == target_module:
                raise ImportError(f"mocked import error for {name}")
            return orig_import(name, *args, **kwargs)
        return patch("builtins.__import__", side_effect=mock_import)

    def test_init_usage_tracker(self):
        mock_tracker = MagicMock()
        mock_class = MagicMock(return_value=mock_tracker)
        with patch.dict("sys.modules", {"usage_tracker.api_usage_tracker": MagicMock(APIUsageTracker=mock_class)}):
            from service_container import _init_usage_tracker
            result = _init_usage_tracker()
            assert result == mock_tracker
            mock_class.assert_called_once()

    def test_init_youtube_analytics(self):
        mock_client = MagicMock()
        mock_class = MagicMock(return_value=mock_client)
        with patch.dict("sys.modules", {"services.youtube_analytics_client": MagicMock(YouTubeAnalyticsClient=mock_class)}):
            from service_container import _init_youtube_analytics
            result = _init_youtube_analytics()
            assert result == mock_client
            mock_class.assert_called_once()

    def test_init_speaker_diarizer(self):
        mock_diarizer = MagicMock()
        mock_class = MagicMock(return_value=mock_diarizer)
        with patch.dict("sys.modules", {"subtitle_engine.speaker_diarizer": MagicMock(SpeakerDiarizer=mock_class)}):
            from service_container import _init_speaker_diarizer
            result = _init_speaker_diarizer()
            assert result == mock_diarizer
            mock_class.assert_called_once()

    def test_init_branding_manager_success(self):
        mock_mgr = MagicMock()
        mock_class = MagicMock(return_value=mock_mgr)
        with patch.dict("sys.modules", {"branding_manager": MagicMock(BrandingManager=mock_class)}):
            from service_container import _init_branding_manager
            result = _init_branding_manager()
            assert result == mock_mgr
            mock_class.assert_called_once()

    def test_init_branding_manager_import_error(self):
        from service_container import _init_branding_manager
        with patch.dict("sys.modules", {"branding_manager": None}):
            with self._mock_import_failure("branding_manager"):
                result = _init_branding_manager()
                assert result is None

    def test_init_pipeline_coordinator_success(self):
        mock_coord = MagicMock()
        mock_class = MagicMock(return_value=mock_coord)
        with patch.dict("sys.modules", {"agents.pipeline_coordinator": MagicMock(PipelineCoordinator=mock_class)}):
            from service_container import _init_pipeline_coordinator
            result = _init_pipeline_coordinator()
            assert result == mock_coord
            mock_class.assert_called_once()

    def test_init_pipeline_coordinator_import_error(self):
        from service_container import _init_pipeline_coordinator
        with patch.dict("sys.modules", {"agents.pipeline_coordinator": None}):
            with self._mock_import_failure("agents.pipeline_coordinator"):
                result = _init_pipeline_coordinator()
                assert result is None

    def test_init_gemini_client_success(self):
        mock_client = MagicMock()
        mock_func = MagicMock(return_value=mock_client)
        with patch.dict("sys.modules", {"gemini_client_factory": MagicMock(get_gemini_client=mock_func)}):
            from service_container import _init_gemini_client
            result = _init_gemini_client()
            assert result == mock_client
            mock_func.assert_called_once()

    def test_init_gemini_client_exception(self):
        from service_container import _init_gemini_client
        mock_func = MagicMock(side_effect=Exception("Gemini init failed"))
        with patch.dict("sys.modules", {"gemini_client_factory": MagicMock(get_gemini_client=mock_func)}):
            result = _init_gemini_client()
            assert result is None
            mock_func.assert_called_once()

    def test_init_harness_hooks_success(self):
        mock_hooks = MagicMock()
        with patch.dict("sys.modules", {"harness.hooks": MagicMock(hook_system=mock_hooks)}):
            from service_container import _init_harness_hooks
            result = _init_harness_hooks()
            assert result == mock_hooks
            mock_hooks.register_builtin_hooks.assert_called_once()

    def test_init_harness_hooks_import_error(self):
        from service_container import _init_harness_hooks
        with patch.dict("sys.modules", {"harness.hooks": None}):
            with self._mock_import_failure("harness.hooks"):
                result = _init_harness_hooks()
                assert result is None

    def test_init_harness_sessions_success(self):
        mock_sessions = MagicMock()
        with patch.dict("sys.modules", {"harness.session_manager": MagicMock(session_manager=mock_sessions)}):
            from service_container import _init_harness_sessions
            result = _init_harness_sessions()
            assert result == mock_sessions

    def test_init_harness_sessions_import_error(self):
        from service_container import _init_harness_sessions
        with patch.dict("sys.modules", {"harness.session_manager": None}):
            with self._mock_import_failure("harness.session_manager"):
                result = _init_harness_sessions()
                assert result is None

    def test_init_harness_governance_success(self):
        mock_gov = MagicMock()
        with patch.dict("sys.modules", {"harness.governance": MagicMock(governance_engine=mock_gov)}):
            from service_container import _init_harness_governance
            result = _init_harness_governance()
            assert result == mock_gov

    def test_init_harness_governance_import_error(self):
        from service_container import _init_harness_governance
        with patch.dict("sys.modules", {"harness.governance": None}):
            with self._mock_import_failure("harness.governance"):
                result = _init_harness_governance()
                assert result is None

    def test_init_harness_tools_success(self):
        mock_tools = MagicMock()
        with patch.dict("sys.modules", {"harness.tool_registry": MagicMock(tool_registry=mock_tools)}):
            from service_container import _init_harness_tools
            result = _init_harness_tools()
            assert result == mock_tools

    def test_init_harness_tools_import_error(self):
        from service_container import _init_harness_tools
        with patch.dict("sys.modules", {"harness.tool_registry": None}):
            with self._mock_import_failure("harness.tool_registry"):
                result = _init_harness_tools()
                assert result is None

    def test_init_youtube_optimizer_import_error(self):
        """_init_youtube_optimizer が ImportError 時に適切に None を返す"""
        from service_container import _init_youtube_optimizer
        with patch.dict("sys.modules", {"plugins.youtube_optimizer_plugin": None}):
            with self._mock_import_failure("plugins.youtube_optimizer_plugin"):
                result = _init_youtube_optimizer()
                assert result is None

    def test_init_youtube_optimizer_success(self):
        """_init_youtube_optimizer が正常にモジュールをインポートして返す"""
        mock_opt = MagicMock()
        with patch.dict("sys.modules", {"plugins.youtube_optimizer_plugin": MagicMock(youtube_optimizer=mock_opt)}):
            from service_container import _init_youtube_optimizer
            result = _init_youtube_optimizer()
            assert result == mock_opt


# ============================================================
# ErrorReportManager テスト (10件)
# ============================================================

class TestErrorReportManager:
    """ErrorReportManager のテスト"""

    def _make_manager(self, tmp_path):
        from error_reporter import ErrorReportManager
        return ErrorReportManager(report_dir=str(tmp_path))

    def test_report_error_returns_id(self, tmp_path):
        """report_error — IDを返す"""
        mgr = self._make_manager(tmp_path)
        report_id = mgr.report_error("TestError", "Something went wrong")
        assert isinstance(report_id, str)
        assert len(report_id) == 8

    def test_report_and_get_unresolved(self, tmp_path):
        """report_error + get_unresolved — 未解決リスト"""
        mgr = self._make_manager(tmp_path)
        mgr.report_error("Error1", "msg1")
        mgr.report_error("Error2", "msg2")
        unresolved = mgr.get_unresolved()
        assert len(unresolved) == 2

    def test_resolve_error(self, tmp_path):
        """resolve_error — エラー解決"""
        mgr = self._make_manager(tmp_path)
        rid = mgr.report_error("TestError", "test")
        success = mgr.resolve_error(rid, "Fixed the issue")
        assert success is True
        assert len(mgr.get_unresolved()) == 0

    def test_resolve_unknown_id(self, tmp_path):
        """resolve_error — 不明なID → False"""
        mgr = self._make_manager(tmp_path)
        assert mgr.resolve_error("unknown", "fix") is False

    def test_get_stats(self, tmp_path):
        """get_stats — 統計"""
        mgr = self._make_manager(tmp_path)
        mgr.report_error("TypeError", "type err")
        mgr.report_error("ValueError", "val err")
        rid = mgr.report_error("TypeError", "another type err")
        mgr.resolve_error(rid, "fixed")
        stats = mgr.get_stats()
        assert stats["total"] == 3
        assert stats["unresolved"] == 2
        assert stats["resolved"] == 1
        assert stats["by_type"]["TypeError"] == 2

    def test_persistence(self, tmp_path):
        """永続化 — 保存と再読込"""
        from error_reporter import ErrorReportManager
        mgr1 = ErrorReportManager(report_dir=str(tmp_path))
        mgr1.report_error("PersistTest", "should persist")
        # 新しいインスタンスで再読込
        mgr2 = ErrorReportManager(report_dir=str(tmp_path))
        assert len(mgr2.get_unresolved()) == 1
        assert mgr2.get_unresolved()[0].error_type == "PersistTest"

    def test_load_corrupt_file(self, tmp_path):
        """_load_reports — 壊れたJSONファイルでもクラッシュしない"""
        report_file = tmp_path / "reports.json"
        report_file.write_text("NOT VALID JSON", encoding="utf-8")
        from error_reporter import ErrorReportManager
        mgr = ErrorReportManager(report_dir=str(tmp_path))
        assert mgr._reports == []

    def test_load_reports_type_error(self, tmp_path):
        """_load_reports — JSONは正しいがスキーマ(引数)が合わずTypeErrorが発生する場合"""
        report_file = tmp_path / "reports.json"
        report_file.write_text(json.dumps([{"invalid_field": "value"}]), encoding="utf-8")
        from error_reporter import ErrorReportManager
        with patch("error_reporter.logger.warning") as mock_log_warning:
            mgr = ErrorReportManager(report_dir=str(tmp_path))
            assert mgr._reports == []
            mock_log_warning.assert_called_once()
            assert "Skipping corrupted report element" in mock_log_warning.call_args[0][0]

    def test_report_with_context(self, tmp_path):
        """report_error — コンテキスト付き"""
        mgr = self._make_manager(tmp_path)
        rid = mgr.report_error("Error", "msg", context={"worker": "transcribe", "stage": 0})
        report = [r for r in mgr._reports if r.id == rid][0]
        assert report.context["worker"] == "transcribe"

    def test_save_reports_os_error(self, tmp_path):
        """_save_reports — OSError時にエラーログを出力する"""
        mgr = self._make_manager(tmp_path)
        mgr.report_error("Test", "msg")
        with patch("builtins.open", side_effect=OSError("Disk full")):
            with patch("error_reporter.logger.error") as mock_log_error:
                with pytest.raises(OSError, match="Disk full"):
                    mgr._save_reports()
                mock_log_error.assert_called_once()
                assert "Failed to save reports" in mock_log_error.call_args[0][0]


# ============================================================
# FAQManager テスト (8件)
# ============================================================

class TestFAQManager:
    """FAQManager のテスト"""

    def _make_manager(self):
        from error_reporter import FAQManager
        return FAQManager()

    def test_default_faqs_loaded(self):
        """デフォルトFAQが3件ロードされる"""
        mgr = self._make_manager()
        assert len(mgr._faqs) == 3

    def test_search_by_keyword(self):
        """search — キーワードマッチ"""
        mgr = self._make_manager()
        results = mgr.search("接続")
        assert len(results) >= 1
        assert results[0].id == "faq_1"

    def test_search_by_error_pattern(self):
        """search — エラーパターンマッチ（最高優先度）"""
        mgr = self._make_manager()
        results = mgr.search("ECONNREFUSED")
        assert len(results) >= 1
        assert results[0].id == "faq_1"

    def test_search_no_match(self):
        """search — マッチなし → 空リスト"""
        mgr = self._make_manager()
        results = mgr.search("完全に無関係なクエリ12345")
        assert results == []

    def test_find_for_error_found(self):
        """find_for_error — マッチあり"""
        mgr = self._make_manager()
        faq = mgr.find_for_error("Connection refused")
        assert faq is not None
        assert faq.id == "faq_1"

    def test_find_for_error_not_found(self):
        """find_for_error — マッチなし → None"""
        mgr = self._make_manager()
        faq = mgr.find_for_error("unknown error xyz")
        assert faq is None

    def test_add_faq(self):
        """add_faq — FAQ追加"""
        from error_reporter import FAQManager, FAQEntry
        mgr = FAQManager()
        mgr.add_faq(FAQEntry(id="custom1", question="test Q", answer="test A"))
        assert len(mgr._faqs) == 4

    def test_search_multiple_criteria(self):
        """search — 複数条件マッチ → スコア順"""
        mgr = self._make_manager()
        results = mgr.search("timeout slow")
        assert len(results) >= 1
        # "遅い" FAQが最上位にくるはず
        assert results[0].id == "faq_3"


# ============================================================
# ErrorReporter ルーター テスト (5件)
# ============================================================

from fastapi import FastAPI
from fastapi.testclient import TestClient

class TestErrorReporterRouter:
    """error_reporter.py の FastAPI ルーターのテスト"""

    @pytest.fixture(autouse=True)
    def setup_client(self):
        from error_reporter import router
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def test_report_error_endpoint(self, tmp_path):
        """POST /api/support/report — エラー報告エンドポイント"""
        from error_reporter import error_report_manager
        old_dir = error_report_manager.report_dir
        error_report_manager.report_dir = str(tmp_path)
        old_reports = error_report_manager._reports
        error_report_manager._reports = []
        try:
            # FAQにマッチしない
            response = self.client.post(
                "/api/support/report",
                params={
                    "error_type": "UnknownError",
                    "message": "some message without matching faq",
                    "stack_trace": "line 1, in module"
                }
            )
            assert response.status_code == 200
            data = response.json()
            assert "report_id" in data
            assert data["related_faq"] is None
            
            # FAQにマッチする (Connection refused -> faq_1)
            response2 = self.client.post(
                "/api/support/report",
                params={
                    "error_type": "ConnectionError",
                    "message": "Connection refused to server",
                    "stack_trace": "line 2, in module"
                }
            )
            assert response2.status_code == 200
            data2 = response2.json()
            assert "report_id" in data2
            assert data2["related_faq"] is not None
            assert data2["related_faq"]["id"] == "faq_1"
        finally:
            error_report_manager.report_dir = old_dir
            error_report_manager._reports = old_reports

    def test_get_unresolved_endpoint(self, tmp_path):
        """GET /api/support/unresolved — 未解決エラー取得"""
        from error_reporter import error_report_manager
        old_dir = error_report_manager.report_dir
        error_report_manager.report_dir = str(tmp_path)
        old_reports = error_report_manager._reports
        error_report_manager._reports = []
        try:
            error_report_manager.report_error("Err1", "msg1")
            response = self.client.get("/api/support/unresolved")
            assert response.status_code == 200
            data = response.json()
            assert len(data["errors"]) == 1
            assert data["errors"][0]["error_type"] == "Err1"
        finally:
            error_report_manager.report_dir = old_dir
            error_report_manager._reports = old_reports

    def test_resolve_error_endpoint(self, tmp_path):
        """POST /api/support/resolve/{report_id} — エラー解決"""
        from error_reporter import error_report_manager
        old_dir = error_report_manager.report_dir
        error_report_manager.report_dir = str(tmp_path)
        old_reports = error_report_manager._reports
        error_report_manager._reports = []
        try:
            rid = error_report_manager.report_error("Err1", "msg1")
            response = self.client.post("/api/support/resolve/nonexistent", params={"resolution": "done"})
            assert response.status_code == 200
            assert response.json()["success"] is False
            response2 = self.client.post(f"/api/support/resolve/{rid}", params={"resolution": "resolved now"})
            assert response2.status_code == 200
            assert response2.json()["success"] is True
            assert len(error_report_manager.get_unresolved()) == 0
        finally:
            error_report_manager.report_dir = old_dir
            error_report_manager._reports = old_reports

    def test_search_faq_endpoint(self):
        """GET /api/support/faq — FAQ検索"""
        response = self.client.get("/api/support/faq", params={"query": "接続"})
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) >= 1
        assert data["results"][0]["id"] == "faq_1"

    def test_get_stats_endpoint(self, tmp_path):
        """GET /api/support/stats — エラー統計"""
        from error_reporter import error_report_manager
        old_dir = error_report_manager.report_dir
        error_report_manager.report_dir = str(tmp_path)
        old_reports = error_report_manager._reports
        error_report_manager._reports = []
        try:
            error_report_manager.report_error("Err1", "msg1")
            response = self.client.get("/api/support/stats")
            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 1
            assert data["unresolved"] == 1
        finally:
            error_report_manager.report_dir = old_dir
            error_report_manager._reports = old_reports
