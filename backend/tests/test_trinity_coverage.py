import pydantic

import sys
import os
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

# テスト実行時のPythonパス解決
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient
from fastapi import HTTPException

@pytest.fixture
def mock_branding_manager():
    mock = MagicMock()
    mock.user_model = {"rank": "A", "xp": 100, "tech_rank": "S", "biz_rank": "A"}
    mock.process_analytics_update.return_value = {"updates": 2, "status": "ok"}
    mock.get_evolution_log.return_value = {"entries": [], "philosophies": []}
    return mock

@pytest.fixture
def mock_analytics_manager():
    mock = MagicMock()
    mock.sim_add_views.return_value = {"added": 1000, "total": 5000}
    return mock

class TestTrinityRouterCoverage:
    def test_get_trinity_status(self, mock_branding_manager):
        """TR-C01: GET /status → 200, user_model取得"""
        from main import app
        with patch("branding_manager.branding_manager", mock_branding_manager):
            client = TestClient(app)
            resp = client.get("/api/status")
        assert resp.status_code == 200
        assert resp.json() == {"rank": "A", "xp": 100, "tech_rank": "S", "biz_rank": "A"}

    def test_sync_analytics(self, mock_branding_manager):
        """TR-C02: POST /analytics/sync → 200"""
        from main import app
        with patch("branding_manager.branding_manager", mock_branding_manager):
            client = TestClient(app)
            resp = client.post("/api/analytics/sync")
        assert resp.status_code == 200
        assert resp.json() == {"updates": 2, "status": "ok"}

    def test_simulate_analytics(self, mock_branding_manager, mock_analytics_manager):
        """TR-C03: POST /analytics/simulate → 200"""
        from main import app
        with patch("branding_manager.branding_manager", mock_branding_manager), \
             patch("branding.analytics_manager.analytics_manager", mock_analytics_manager):
            client = TestClient(app)
            # viewsパラメータあり
            resp = client.post("/api/analytics/simulate?views=2000")
            assert resp.status_code == 200
            data = resp.json()
            assert data["simulation"] == {"added": 1000, "total": 5000}
            assert data["sync"] == {"updates": 2, "status": "ok"}
            mock_analytics_manager.sim_add_views.assert_called_with(2000)

            # viewsパラメータなし (デフォルト1000の検証)
            resp_default = client.post("/api/analytics/simulate")
            assert resp_default.status_code == 200
            mock_analytics_manager.sim_add_views.assert_called_with(1000)

    def test_get_models(self):
        """TR-C04: GET /models → 200"""
        from main import app
        mock_list = MagicMock(return_value=["gemini-2.5-flash"])
        with patch("list_models.list_gemini_models", mock_list):
            client = TestClient(app)
            resp = client.get("/api/models")
        assert resp.status_code == 200
        assert resp.json() == {"models": ["gemini-2.5-flash"]}

    def test_get_evolution(self, mock_branding_manager):
        """TR-C05: GET /evolution → 200"""
        from main import app
        with patch("branding_manager.branding_manager", mock_branding_manager):
            client = TestClient(app)
            resp = client.get("/api/evolution")
        assert resp.status_code == 200
        assert resp.json() == {"entries": [], "philosophies": []}

    def test_sync_evolution(self):
        """TR-C06: POST /evolution/sync → 200"""
        from main import app
        mock_service = MagicMock()
        mock_service.return_value.sync_all.return_value = {"sync": "complete"}
        with patch("services.evolution_sync_service.EvolutionSyncService", mock_service):
            client = TestClient(app)
            resp = client.post("/api/evolution/sync")
        assert resp.status_code == 200
        assert resp.json() == {"sync": "complete"}

    def test_get_evolution_status(self):
        """TR-C07: GET /evolution/status → 200"""
        from main import app
        mock_service = MagicMock()
        mock_service.return_value.get_evolution_status.return_value = {"status": "active"}
        with patch("services.evolution_sync_service.EvolutionSyncService", mock_service):
            client = TestClient(app)
            resp = client.get("/api/evolution/status")
        assert resp.status_code == 200
        assert resp.json() == {"status": "active"}

    def test_get_evolution_proposals(self):
        """TR-C08: GET /evolution/proposals → 200"""
        from main import app
        mock_proposal = MagicMock()
        mock_proposal.proposal_id = "p1"
        mock_proposal.content = "c"
        mock_proposal.source_summary = "s"
        mock_proposal.generated_at = "g"
        mock_proposal.status = "pending"
        mock_proposal.user_edit = "u"

        mock_service = MagicMock()
        mock_service.return_value.get_pending_proposals.return_value = [mock_proposal]
        with patch("services.philosophy_proposal_service.PhilosophyProposalService", mock_service):
            client = TestClient(app)
            resp = client.get("/api/evolution/proposals")
        assert resp.status_code == 200
        assert resp.json() == [{
            "proposal_id": "p1",
            "content": "c",
            "source_summary": "s",
            "generated_at": "g",
            "status": "pending",
            "user_edit": "u"
        }]

    def test_approve_evolution_proposal(self):
        """TR-C09: POST /evolution/proposals/{proposal_id}/approve → 200"""
        from main import app
        mock_service = MagicMock()
        mock_service.return_value.approve_proposal.return_value = True
        with patch("services.philosophy_proposal_service.PhilosophyProposalService", mock_service):
            client = TestClient(app)
            
            # body が None の場合
            resp_none = client.post("/api/evolution/proposals/p1/approve")
            assert resp_none.status_code == 200
            assert resp_none.json() == {"approved": True, "proposal_id": "p1"}
            mock_service.return_value.approve_proposal.assert_called_with("p1", edited=None)

            # body が空の場合
            resp_empty = client.post("/api/evolution/proposals/p1/approve", json={})
            assert resp_empty.status_code == 200
            assert resp_empty.json() == {"approved": True, "proposal_id": "p1"}
            mock_service.return_value.approve_proposal.assert_called_with("p1", edited=None)

            # body に edited_text がある場合
            resp_edited = client.post("/api/evolution/proposals/p1/approve", json={"edited_text": "new"})
            assert resp_edited.status_code == 200
            assert resp_edited.json() == {"approved": True, "proposal_id": "p1"}
            mock_service.return_value.approve_proposal.assert_called_with("p1", edited="new")

    def test_reject_evolution_proposal(self):
        """TR-C10: POST /evolution/proposals/{proposal_id}/reject → 200"""
        from main import app
        mock_service = MagicMock()
        mock_service.return_value.reject_proposal.return_value = True
        with patch("services.philosophy_proposal_service.PhilosophyProposalService", mock_service):
            client = TestClient(app)
            
            # body が None の場合
            resp_none = client.post("/api/evolution/proposals/p1/reject")
            assert resp_none.status_code == 200
            assert resp_none.json() == {"rejected": True, "proposal_id": "p1"}
            mock_service.return_value.reject_proposal.assert_called_with("p1", reason="理由未記入")

            # body が空の場合
            resp_empty = client.post("/api/evolution/proposals/p1/reject", json={})
            assert resp_empty.status_code == 200
            assert resp_empty.json() == {"rejected": True, "proposal_id": "p1"}
            mock_service.return_value.reject_proposal.assert_called_with("p1", reason="理由未記入")

            # body に reason がある場合
            resp_reason = client.post("/api/evolution/proposals/p1/reject", json={"reason": "bad"})
            assert resp_reason.status_code == 200
            assert resp_reason.json() == {"rejected": True, "proposal_id": "p1"}
            mock_service.return_value.reject_proposal.assert_called_with("p1", reason="bad")

    def test_get_evolution_dashboard(self):
        """TR-C11: GET /evolution/dashboard → 200"""
        from main import app
        mock_service = MagicMock()
        mock_service.return_value.get_dashboard_data.return_value = {"dash": "data"}
        with patch("services.evolution_sync_service.EvolutionSyncService", mock_service):
            client = TestClient(app)
            resp = client.get("/api/evolution/dashboard")
        assert resp.status_code == 200
        assert resp.json() == {"dash": "data"}

    def test_get_evolution_triggers(self):
        """TR-C12: GET /evolution/triggers → 200"""
        from main import app
        mock_service = MagicMock()
        mock_service.return_value.get_trigger_status.return_value = [{"trigger": "ok"}]
        with patch("services.evolution_trigger_service.EvolutionTriggerService", mock_service):
            client = TestClient(app)
            resp = client.get("/api/evolution/triggers")
        assert resp.status_code == 200
        assert resp.json() == [{"trigger": "ok"}]

    def test_simulate_analytics_validation(self):
        """TR-C13: POST /analytics/simulate viewsが負の値または過大値のとき400"""
        from main import app
        client = TestClient(app)
        # 負の値
        resp_neg = client.post("/api/analytics/simulate?views=-100")
        assert resp_neg.status_code == 400
        assert resp_neg.json()["error"] == "Views must be non-negative"

        # 過大値
        resp_large = client.post("/api/analytics/simulate?views=1000000001")
        assert resp_large.status_code == 400
        assert resp_large.json()["error"] == "Views parameter too large"

    def test_approve_evolution_proposal_validation(self):
        """TR-C14: POST /evolution/proposals/{proposal_id}/approve proposal_idが空のとき400"""
        from main import app
        client = TestClient(app)
        resp = client.post("/api/evolution/proposals/%20/approve")
        assert resp.status_code == 400
        assert resp.json()["error"] == "Invalid proposal_id"

    def test_reject_evolution_proposal_validation(self):
        """TR-C15: POST /evolution/proposals/{proposal_id}/reject proposal_idが空のとき400"""
        from main import app
        client = TestClient(app)
        resp = client.post("/api/evolution/proposals/%20/reject")
        assert resp.status_code == 400
        assert resp.json()["error"] == "Invalid proposal_id"

    def test_approve_evolution_proposal_not_found(self):
        """TR-C16: POST /evolution/proposals/{proposal_id}/approve 承認失敗時404"""
        from main import app
        mock_service = MagicMock()
        mock_service.return_value.approve_proposal.return_value = False
        with patch("services.philosophy_proposal_service.PhilosophyProposalService", mock_service):
            client = TestClient(app)
            resp = client.post("/api/evolution/proposals/p1/approve")
        assert resp.status_code == 404
        assert resp.json()["error"] == "Proposal p1 not found or failed to approve"

    def test_reject_evolution_proposal_not_found(self):
        """TR-C17: POST /evolution/proposals/{proposal_id}/reject 却下失敗時404"""
        from main import app
        mock_service = MagicMock()
        mock_service.return_value.reject_proposal.return_value = False
        with patch("services.philosophy_proposal_service.PhilosophyProposalService", mock_service):
            client = TestClient(app)
            resp = client.post("/api/evolution/proposals/p1/reject")
        assert resp.status_code == 404
        assert resp.json()["error"] == "Proposal p1 not found or failed to reject"

    @patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt")
    def test_all_endpoints_exceptions(self, mock_register):
        """TR-C18: 全てのエンドポイントで例外発生時に500を返し、技術負債に登録されること"""
        from main import app
        client = TestClient(app)

        # 1. /status (例外)
        mock_bm1 = MagicMock()
        type(mock_bm1).user_model = PropertyMock(side_effect=OSError("Status DB Error"))
        with patch("branding_manager.branding_manager", mock_bm1):
            resp = client.get("/api/status")
        assert resp.status_code == 500
        
        # 部分一致および個別アサーションに変更して、詳細な例外情報（トレースバック）がnotesに添付されても動作するように修正
        assert mock_register.called
        call_kwargs = mock_register.call_args.kwargs
        assert call_kwargs["category"] == "CRITICAL_ROUTER"
        assert call_kwargs["file_path"] == "routers/trinity.py"
        assert call_kwargs["line_number"] == 44
        assert call_kwargs["pattern"] == "except (AttributeError, ValueError, TypeError, ImportError, OSError) as e:"
        assert call_kwargs["cause_pattern"] == "DP-01"
        assert call_kwargs["fix_pattern"] == "except HTTPException: raise を配置"
        assert call_kwargs["registered_by"] == "thumbnail_task"
        assert "Unexpected error in get_trinity_status: Status DB Error" in call_kwargs["notes"]
        assert "Traceback" in call_kwargs["notes"]

        # 1.5. /status (None の場合)
        mock_bm1_none = MagicMock()
        type(mock_bm1_none).user_model = PropertyMock(return_value=None)
        with patch("branding_manager.branding_manager", mock_bm1_none):
            resp = client.get("/api/status")
        assert resp.status_code == 404

        # 2. /analytics/sync (例外)
        mock_bm2 = MagicMock()
        mock_bm2.process_analytics_update.side_effect = Exception("Sync Error")
        with patch("branding_manager.branding_manager", mock_bm2):
            resp = client.post("/api/analytics/sync")
        assert resp.status_code == 500

        # 2.5. /analytics/sync (None の場合)
        mock_bm2_none = MagicMock()
        mock_bm2_none.process_analytics_update.return_value = None
        with patch("branding_manager.branding_manager", mock_bm2_none):
            resp = client.post("/api/analytics/sync")
        assert resp.status_code == 500

        # 3. /analytics/simulate (例外)
        mock_am = MagicMock()
        mock_am.sim_add_views.side_effect = Exception("Sim Error")
        with patch("branding.analytics_manager.analytics_manager", mock_am):
            resp = client.post("/api/analytics/simulate")
        assert resp.status_code == 500

        # 3.5. /analytics/simulate (HTTPException)
        mock_am_http = MagicMock()
        mock_am_http.sim_add_views.side_effect = HTTPException(status_code=400, detail="Sim HTTPException")
        with patch("branding.analytics_manager.analytics_manager", mock_am_http):
            resp = client.post("/api/analytics/simulate")
        assert resp.status_code == 400

        # 4. /models (例外)
        with patch("list_models.list_gemini_models", side_effect=Exception("Model Load Error")):
            resp = client.get("/api/models")
        assert resp.status_code == 500

        # 4.5. /models (None の場合)
        with patch("list_models.list_gemini_models", return_value=None):
            resp = client.get("/api/models")
        assert resp.status_code == 404

        # 5. /evolution (例外)
        mock_bm5 = MagicMock()
        mock_bm5.get_evolution_log.side_effect = Exception("Log Error")
        with patch("branding_manager.branding_manager", mock_bm5):
            resp = client.get("/api/evolution")
        assert resp.status_code == 500

        # 5.5. /evolution (None の場合)
        mock_bm5_none = MagicMock()
        mock_bm5_none.get_evolution_log.return_value = None
        with patch("branding_manager.branding_manager", mock_bm5_none):
            resp = client.get("/api/evolution")
        assert resp.status_code == 404

        # 6. /evolution/sync (例外)
        mock_service = MagicMock()
        mock_service.return_value.sync_all.side_effect = Exception("Sync Detail Error")
        with patch("services.evolution_sync_service.EvolutionSyncService", mock_service):
            resp = client.post("/api/evolution/sync")
        assert resp.status_code == 500

        # 6.5. /evolution/sync (None の場合)
        mock_service_none = MagicMock()
        mock_service_none.return_value.sync_all.return_value = None
        with patch("services.evolution_sync_service.EvolutionSyncService", mock_service_none):
            resp = client.post("/api/evolution/sync")
        assert resp.status_code == 500

        # 7. /evolution/status (例外)
        mock_service_status = MagicMock()
        mock_service_status.return_value.get_evolution_status.side_effect = Exception("Status Service Error")
        with patch("services.evolution_sync_service.EvolutionSyncService", mock_service_status):
            resp = client.get("/api/evolution/status")
        assert resp.status_code == 500

        # 7.5. /evolution/status (None の場合)
        mock_service_status_none = MagicMock()
        mock_service_status_none.return_value.get_evolution_status.return_value = None
        with patch("services.evolution_sync_service.EvolutionSyncService", mock_service_status_none):
            resp = client.get("/api/evolution/status")
        assert resp.status_code == 404

        # 8. /evolution/proposals (例外)
        mock_proposal_service = MagicMock()
        mock_proposal_service.return_value.get_pending_proposals.side_effect = Exception("Proposals Error")
        with patch("services.philosophy_proposal_service.PhilosophyProposalService", mock_proposal_service):
            resp = client.get("/api/evolution/proposals")
        assert resp.status_code == 500

        # 8.5. /evolution/proposals (None の場合)
        mock_proposal_service_none = MagicMock()
        mock_proposal_service_none.return_value.get_pending_proposals.return_value = None
        with patch("services.philosophy_proposal_service.PhilosophyProposalService", mock_proposal_service_none):
            resp = client.get("/api/evolution/proposals")
        assert resp.status_code == 200
        assert resp.json() == []

        # 8.7. /evolution/proposals (HTTPException)
        mock_proposal_service_http = MagicMock()
        mock_proposal_service_http.return_value.get_pending_proposals.side_effect = HTTPException(status_code=400, detail="Proposals HTTPException")
        with patch("services.philosophy_proposal_service.PhilosophyProposalService", mock_proposal_service_http):
            resp = client.get("/api/evolution/proposals")
        assert resp.status_code == 400

        # 9. /evolution/proposals/{proposal_id}/approve (例外)
        mock_proposal_service_approve = MagicMock()
        mock_proposal_service_approve.return_value.approve_proposal.side_effect = Exception("Approve Error")
        with patch("services.philosophy_proposal_service.PhilosophyProposalService", mock_proposal_service_approve):
            resp = client.post("/api/evolution/proposals/p1/approve")
        assert resp.status_code == 500

        # 10. /evolution/proposals/{proposal_id}/reject (例外)
        mock_proposal_service_reject = MagicMock()
        mock_proposal_service_reject.return_value.reject_proposal.side_effect = Exception("Reject Error")
        with patch("services.philosophy_proposal_service.PhilosophyProposalService", mock_proposal_service_reject):
            resp = client.post("/api/evolution/proposals/p1/reject")
        assert resp.status_code == 500

        # 11. /evolution/dashboard (例外)
        mock_service_dash = MagicMock()
        mock_service_dash.return_value.get_dashboard_data.side_effect = Exception("Dashboard Error")
        with patch("services.evolution_sync_service.EvolutionSyncService", mock_service_dash):
            resp = client.get("/api/evolution/dashboard")
        assert resp.status_code == 500

        # 11.5. /evolution/dashboard (None の場合)
        mock_service_dash_none = MagicMock()
        mock_service_dash_none.return_value.get_dashboard_data.return_value = None
        with patch("services.evolution_sync_service.EvolutionSyncService", mock_service_dash_none):
            resp = client.get("/api/evolution/dashboard")
        assert resp.status_code == 404

        # 12. /evolution/triggers (例外)
        mock_service_triggers = MagicMock()
        mock_service_triggers.return_value.get_trigger_status.side_effect = Exception("Triggers Error")
        with patch("services.evolution_trigger_service.EvolutionTriggerService", mock_service_triggers):
            resp = client.get("/api/evolution/triggers")
        assert resp.status_code == 500

        # 12.5. /evolution/triggers (None の場合)
        mock_service_triggers_none = MagicMock()
        mock_service_triggers_none.return_value.get_trigger_status.return_value = None
        with patch("services.evolution_trigger_service.EvolutionTriggerService", mock_service_triggers_none):
            resp = client.get("/api/evolution/triggers")
        assert resp.status_code == 404

    def test_register_debt_exception_logging(self):
        """TR-C19: _register_router_debt内での例外発生時に適切にエラーログが出力されること"""
        from main import app
        client = TestClient(app)
        mock_bm = MagicMock()
        type(mock_bm).user_model = PropertyMock(side_effect=OSError("Status Error"))
        
        with patch("branding_manager.branding_manager", mock_bm), \
             patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt", side_effect=Exception("TDR Fail")), \
             patch("logging.getLogger") as mock_get_logger:
            
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger
            resp = client.get("/api/status")
            
        assert resp.status_code == 500
        mock_logger.error.assert_called_with("Failed to register TDR debt: TDR Fail")

    def test_register_debt_includes_traceback_and_logs(self):
        """TR-C20: 例外発生時に_register_router_debtがスタックトレースをログ出力し、TDRに詳細情報を渡すことを検証"""
        from main import app
        client = TestClient(app)
        mock_bm = MagicMock()
        type(mock_bm).user_model = PropertyMock(side_effect=OSError("Detailed Log Test Error"))
        
        with patch("branding_manager.branding_manager", mock_bm), \
             patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt") as mock_register, \
             patch("logging.getLogger") as mock_get_logger:
            
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger
            resp = client.get("/api/status")
            
        assert resp.status_code == 500
        # logger.errorがスタックトレース（exc_info）を伴って呼び出されたことを確認
        assert mock_logger.error.called
        log_args, log_kwargs = mock_logger.error.call_args
        assert "Unexpected error in get_trinity_status: Detailed Log Test Error" in log_args[0]
        assert "exc_info" in log_kwargs
        
        # TDRに登録されたnotesに例外クラス名とTracebackが含まれていることを検証
        assert mock_register.called
        call_kwargs = mock_register.call_args.kwargs
        assert "Detailed Log Test Error" in call_kwargs["notes"]
        assert "Traceback" in call_kwargs["notes"]
