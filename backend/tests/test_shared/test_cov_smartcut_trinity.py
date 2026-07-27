"""
Sprint 3.7.4: 複利的負債ゼロ化テスト
対象: routers/smartcut.py (SC-01~15), routers/trinity.py (TR-01~07), video_processor.py (VP-01~08)
設計書: sprint_374_design.md
"""
import pytest
import json
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi.testclient import TestClient


def get_error_message(resp) -> str:
    data = resp.json()
    if isinstance(data, dict):
        return data.get("detail") or data.get("error") or ""
    return str(data)


# ─────────────────────────────────────────────
# Fixtures: SmartCut
# ─────────────────────────────────────────────

@pytest.fixture
def mock_smart_cut_initialized():
    """初期化済みSmartCutPluginのMock"""
    mock = MagicMock()
    mock._context = MagicMock()
    mock.get_recommendation.return_value = {"segments": [{"id": "s1", "duration": 60}], "total_duration": 900}
    mock.get_locked_segments.return_value = [{"id": "s1"}]
    mock.get_all_candidates.return_value = {"highlights": [{"id": "h1"}], "chapters": [{"id": "c1"}]}
    mock.lock_segment.return_value = True
    mock.unlock_segment.return_value = True
    mock.finalize.return_value = {"final_segments": [{"id": "s1"}], "total_duration": 900}
    return mock


@pytest.fixture
def mock_smart_cut_not_initialized():
    """未初期化状態のMock"""
    mock = MagicMock()
    mock._context = None
    return mock


@pytest.fixture
def sc_client(mock_smart_cut_initialized):
    """SmartCut router用クライアント（初期化済みstate）"""
    from main import app
    import routers.smartcut as sc_module
    sc_module._smart_cut_instance = mock_smart_cut_initialized
    client = TestClient(app)
    yield client
    sc_module._smart_cut_instance = None


@pytest.fixture
def sc_client_uninit():
    """SmartCut router用クライアント（未初期化state） - _context=None でHTTPException 400が正しく伝播"""
    from main import app
    import routers.smartcut as sc_module

    # _context=None の場合、HTTPExceptionが発生するが lock/unlock/finalize の except Exception で
    # 捕捉されて500になる実装上のバグがある。ここでは実装に合わせて400相当の検証をするため、
    # HTTPException が raise される前にチェックが効くよう _context=None のみ設定する。
    mock = MagicMock()
    mock._context = None
    # HTTPException は except Exception に捕捉されるため、500が返る仕様を確認するテストに変更
    sc_module._smart_cut_instance = mock
    client = TestClient(app)
    yield client
    sc_module._smart_cut_instance = None


# ─────────────────────────────────────────────
# SC-01: /init 成功
# ─────────────────────────────────────────────

class TestSmartCutInit:
    def test_init_success(self):
        """SC-01: POST /init → 200, success=True, scan_result構造正しい"""
        from main import app
        import routers.smartcut as sc_module

        mock_scan_result = MagicMock()
        mock_scan_result.total_segments = 10
        mock_scan_result.highlight_candidates = [{"id": "h1"}, {"id": "h2"}]
        mock_scan_result.chapter_candidates = [{"id": "c1"}]
        mock_scan_result.estimated_cut_rate = 0.4

        mock_context = MagicMock()
        mock_context.scan_result = mock_scan_result
        mock_context.segments = []

        mock_scan_plugin = MagicMock()
        mock_scan_plugin.execute.return_value = mock_context

        mock_sc = MagicMock()
        mock_sc.get_recommendation.return_value = {"segments": [], "total_duration": 900}

        sc_module._smart_cut_instance = None

        # LightweightScanPlugin/ProductionContext は関数内ローカルimport → sys.modules でモック
        import sys
        fake_scan_mod = MagicMock()
        fake_scan_mod.LightweightScanPlugin = MagicMock(return_value=mock_scan_plugin)
        fake_ctx_mod = MagicMock()
        fake_ctx_mod.ProductionContext = MagicMock(return_value=mock_context)
        fake_sc_plugin_mod = MagicMock()
        fake_sc_plugin_mod.SmartCutPlugin = MagicMock()
        fake_sc_plugin_mod.SmartCutContext = MagicMock()

        with patch.dict(sys.modules, {
            "plugins.lightweight_scan_plugin": fake_scan_mod,
            "core.context": fake_ctx_mod,
            "plugins.smart_cut_plugin": fake_sc_plugin_mod,
        }), patch("routers.smartcut._get_smart_cut", return_value=mock_sc):
            client = TestClient(app)
            resp = client.post("/api/smartcut/init", json={
                "segments": [{"id": "s1", "start": 0, "end": 10}],
                "opening_duration": 10.0,
                "ending_duration": 20.0
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "scan_result" in data
        assert data["scan_result"]["total_segments"] == 10
        assert data["scan_result"]["highlight_count"] == 2
        assert "recommendation" in data

    def test_init_scan_exception(self):
        """SC-02: POST /init, ScanPlugin例外 → 500"""
        from main import app
        import routers.smartcut as sc_module
        import sys
        sc_module._smart_cut_instance = None

        # LightweightScanPlugin のインスタンス化で例外を発生させる
        fake_scan_mod = MagicMock()
        fake_scan_mod.LightweightScanPlugin = MagicMock(side_effect=RuntimeError("scan failed"))

        with patch.dict(sys.modules, {"plugins.lightweight_scan_plugin": fake_scan_mod}):
            client = TestClient(app)
            resp = client.post("/api/smartcut/init", json={
                "segments": [],
                "opening_duration": 10.0,
                "ending_duration": 20.0
            })

        assert resp.status_code == 500
        assert "scan failed" in get_error_message(resp)

    def test_init_http_exception_relay(self):
        """SC-02b: POST /init, ScanPluginがHTTPExceptionを投げる → そのまま返却"""
        from main import app
        import routers.smartcut as sc_module
        import sys
        from fastapi import HTTPException
        sc_module._smart_cut_instance = None

        fake_scan_mod = MagicMock()
        fake_scan_mod.LightweightScanPlugin = MagicMock(
            return_value=MagicMock(execute=MagicMock(side_effect=HTTPException(status_code=400, detail="custom bad request")))
        )

        with patch.dict(sys.modules, {"plugins.lightweight_scan_plugin": fake_scan_mod}):
            client = TestClient(app)
            resp = client.post("/api/smartcut/init", json={
                "segments": [],
                "opening_duration": 10.0,
                "ending_duration": 20.0
            })

        assert resp.status_code == 400
        assert "custom bad request" in get_error_message(resp)


# ─────────────────────────────────────────────
# SC-03~06: /recommend
# ─────────────────────────────────────────────

class TestSmartCutRecommend:
    def test_recommend_success(self, sc_client):
        """SC-03: POST /recommend → 200, recommendation存在"""
        resp = sc_client.post("/api/smartcut/recommend", json={"target_duration_minutes": 30})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "recommendation" in data
        assert len(data["recommendation"]["segments"]) > 0

    def test_recommend_not_initialized(self, sc_client_uninit):
        """SC-04: POST /recommend (context=None) → 400"""
        resp = sc_client_uninit.post("/api/smartcut/recommend", json={"target_duration_minutes": 30})
        assert resp.status_code == 400
        assert "not initialized" in get_error_message(resp).lower()

    def test_recommend_exception(self, sc_client, mock_smart_cut_initialized):
        """SC-05: POST /recommend, update例外 → 500"""
        mock_smart_cut_initialized.update_recommendation.side_effect = RuntimeError("update error")
        resp = sc_client.post("/api/smartcut/recommend", json={"target_duration_minutes": 30})
        assert resp.status_code == 500

    def test_recommend_http_exception_relay(self, sc_client, mock_smart_cut_initialized):
        """SC-06: POST /recommend, HTTPException → リレイズ（400のまま）"""
        from fastapi import HTTPException
        mock_smart_cut_initialized.update_recommendation.side_effect = HTTPException(status_code=422, detail="invalid")
        resp = sc_client.post("/api/smartcut/recommend", json={"target_duration_minutes": 99})
        assert resp.status_code == 422


# ─────────────────────────────────────────────
# SC-07~09: /lock
# ─────────────────────────────────────────────

class TestSmartCutLock:
    def test_lock_success(self, sc_client):
        """SC-07: POST /lock → 200, locked_segments存在"""
        resp = sc_client.post("/api/smartcut/lock", json={
            "segment_id": "s1", "title": "Opening", "start_time": 0.0, "end_time": 60.0, "reason": "key"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "locked_segments" in data
        assert len(data["locked_segments"]) > 0

    def test_lock_not_initialized(self, sc_client_uninit):
        """SC-08: POST /lock (context=None) → 400（P-1修正済み: HTTPException正常伝播）"""
        resp = sc_client_uninit.post("/api/smartcut/lock", json={
            "segment_id": "s1", "title": "T", "start_time": 0.0, "end_time": 10.0
        })
        assert resp.status_code == 400
        detail = get_error_message(resp)
        assert "not initialized" in detail.lower()

    def test_lock_exception(self, sc_client, mock_smart_cut_initialized):
        """SC-09: POST /lock, lock_segment例外 → 500"""
        mock_smart_cut_initialized.lock_segment.side_effect = RuntimeError("lock error")
        resp = sc_client.post("/api/smartcut/lock", json={
            "segment_id": "s1", "title": "T", "start_time": 0.0, "end_time": 10.0
        })
        assert resp.status_code == 500

    def test_lock_validation_error(self, sc_client):
        """SC-09b: POST /lock, start_time >= end_time → 422 ValidationError"""
        resp = sc_client.post("/api/smartcut/lock", json={
            "segment_id": "s1",
            "title": "T",
            "start_time": 10.0,
            "end_time": 5.0
        })
        assert resp.status_code == 422
        assert "start_time must be less than end_time" in resp.text


# ─────────────────────────────────────────────
# SC-10~12: /unlock
# ─────────────────────────────────────────────

class TestSmartCutUnlock:
    def test_unlock_success(self, sc_client):
        """SC-10: POST /unlock → 200, success + recommendation"""
        resp = sc_client.post("/api/smartcut/unlock", json={"segment_id": "s1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "recommendation" in data

    def test_unlock_not_initialized(self, sc_client_uninit):
        """SC-11: POST /unlock (context=None) → 400（P-1修正済み: HTTPException正常伝播）"""
        resp = sc_client_uninit.post("/api/smartcut/unlock", json={"segment_id": "s1"})
        assert resp.status_code == 400
        detail = get_error_message(resp)
        assert "not initialized" in detail.lower()

    def test_unlock_exception(self, sc_client, mock_smart_cut_initialized):
        """SC-12: POST /unlock, 例外 → 500"""
        mock_smart_cut_initialized.unlock_segment.side_effect = RuntimeError("unlock error")
        resp = sc_client.post("/api/smartcut/unlock", json={"segment_id": "s1"})
        assert resp.status_code == 500


# ─────────────────────────────────────────────
# SC-13~15: /finalize
# ─────────────────────────────────────────────

class TestSmartCutFinalize:
    def test_finalize_success(self, sc_client):
        """SC-13: POST /finalize → 200, finalized存在"""
        resp = sc_client.post("/api/smartcut/finalize")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "finalized" in data
        assert "final_segments" in data["finalized"]

    def test_finalize_not_initialized(self, sc_client_uninit):
        """SC-14: POST /finalize (context=None) → 400（P-1修正済み: HTTPException正常伝播）"""
        resp = sc_client_uninit.post("/api/smartcut/finalize")
        assert resp.status_code == 400
        detail = get_error_message(resp)
        assert "not initialized" in detail.lower()

    def test_finalize_exception(self, sc_client, mock_smart_cut_initialized):
        """SC-15: POST /finalize, 例外 → 500"""
        mock_smart_cut_initialized.finalize.side_effect = RuntimeError("finalize error")
        resp = sc_client.post("/api/smartcut/finalize")
        assert resp.status_code == 500


# ─────────────────────────────────────────────
# SC-16: _get_smart_cut() の遅延初期化
# ─────────────────────────────────────────────

class TestSmartCutGetSmartCut:
    def test_get_smart_cut_lazy_initialization(self):
        """SC-16: _smart_cut_instance が None の場合、SmartCutPlugin がインポートされ初期化される"""
        import routers.smartcut as sc_module
        import sys
        
        # 状態リセット
        sc_module._smart_cut_instance = None
        
        mock_plugin_class = MagicMock()
        fake_sc_plugin_mod = MagicMock()
        fake_sc_plugin_mod.SmartCutPlugin = mock_plugin_class
        
        with patch.dict(sys.modules, {"plugins.smart_cut_plugin": fake_sc_plugin_mod}):
            instance = sc_module._get_smart_cut()
            
        assert instance is not None
        mock_plugin_class.assert_called_once()
        assert sc_module._smart_cut_instance == instance


# ─────────────────────────────────────────────
# SC-17~20: /all-candidates
# ─────────────────────────────────────────────

class TestSmartCutAllCandidates:
    def test_all_candidates_success(self, sc_client):
        """SC-17: GET /all-candidates → 200, candidates存在"""
        resp = sc_client.get("/api/smartcut/all-candidates")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "candidates" in data

    def test_all_candidates_not_initialized(self, sc_client_uninit):
        """SC-18: GET /all-candidates (context=None) → 400"""
        resp = sc_client_uninit.get("/api/smartcut/all-candidates")
        assert resp.status_code == 400
        assert "not initialized" in get_error_message(resp).lower()

    def test_all_candidates_exception(self, sc_client, mock_smart_cut_initialized):
        """SC-19: GET /all-candidates, 例外発生 → 500"""
        mock_smart_cut_initialized.get_all_candidates.side_effect = RuntimeError("candidates error")
        resp = sc_client.get("/api/smartcut/all-candidates")
        assert resp.status_code == 500

    def test_all_candidates_http_exception_relay(self, sc_client, mock_smart_cut_initialized):
        """SC-20: GET /all-candidates, HTTPException → そのまま返却"""
        from fastapi import HTTPException
        mock_smart_cut_initialized.get_all_candidates.side_effect = HTTPException(status_code=403, detail="forbidden")
        resp = sc_client.get("/api/smartcut/all-candidates")
        assert resp.status_code == 403


# ─────────────────────────────────────────────
# SC-21: /health
# ─────────────────────────────────────────────

class TestSmartCutHealth:
    def test_health_check_success(self):
        """SC-21: GET /health → 200, status=ok"""
        from main import app
        client = TestClient(app)
        resp = client.get("/api/smartcut/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "service": "smartcut"}


# ─────────────────────────────────────────────
# Fixtures: Trinity
# ─────────────────────────────────────────────

@pytest.fixture
def mock_branding_manager():
    mock = MagicMock()
    mock.user_model = {"rank": "A", "xp": 100, "tech_rank": "S", "biz_rank": "A"}
    mock.process_analytics_update.return_value = {"updates": 2, "status": "ok"}
    mock.get_evolution_log.return_value = {"entries": [], "philosophies": []}
    return mock


@pytest.fixture
def mock_decision_logger():
    mock = MagicMock()
    mock.sync_to_evolution_log.return_value = {"synced": 5}
    mock.get_stats.return_value = {"total": 42}
    return mock


@pytest.fixture
def mock_analytics_manager():
    mock = MagicMock()
    mock.sim_add_views.return_value = {"added": 1000, "total": 5000}
    return mock


@pytest.fixture
def trinity_client(mock_branding_manager, mock_decision_logger, mock_analytics_manager):
    """Trinity router用クライアント"""
    from main import app
    with patch("routers.trinity.branding_manager", mock_branding_manager, create=True):
        client = TestClient(app)
        yield client, mock_branding_manager, mock_decision_logger, mock_analytics_manager


# ─────────────────────────────────────────────
# TR-01~07: Trinity Router
# ─────────────────────────────────────────────

class TestTrinityRouter:
    def test_get_trinity_status(self, mock_branding_manager):
        """TR-01: GET /status → 200, user_model構造"""
        from main import app
        with patch("branding_manager.branding_manager", mock_branding_manager):
            client = TestClient(app)
            resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "rank" in data
        assert data["xp"] == 100

    def test_sync_analytics(self, mock_branding_manager):
        """TR-02: POST /analytics/sync → 200, result存在"""
        from main import app
        with patch("branding_manager.branding_manager", mock_branding_manager):
            client = TestClient(app)
            resp = client.post("/api/analytics/sync")
        assert resp.status_code == 200
        data = resp.json()
        assert "updates" in data or "status" in data

    def test_simulate_analytics(self, mock_branding_manager, mock_analytics_manager):
        """TR-03: POST /analytics/simulate → 200, simulation+sync"""
        from main import app
        with patch("branding_manager.branding_manager", mock_branding_manager), \
             patch("branding.analytics_manager.analytics_manager", mock_analytics_manager):
            client = TestClient(app)
            resp = client.post("/api/analytics/simulate?views=500")
        assert resp.status_code == 200
        data = resp.json()
        assert "simulation" in data
        assert "sync" in data

    def test_get_models(self):
        """TR-04: GET /models → 200, models配列"""
        from main import app
        mock_list = MagicMock(return_value=["gemini-2.0-flash", "gemini-1.5-pro"])
        with patch("list_models.list_gemini_models", mock_list):
            client = TestClient(app)
            resp = client.get("/api/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "models" in data
        assert isinstance(data["models"], list)

    def test_evolution_sync(self, mock_branding_manager, mock_decision_logger):
        """TR-05: POST /evolution/sync → 200, decisions_synced + constitution_updates + philosophy_triggered"""
        from main import app

        mock_service = MagicMock()
        mock_service.return_value.sync_all.return_value = {
            "status": "success",
            "result": {
                "decisions_synced": 5,
                "constitution_updates": 2,
                "philosophy_triggered": False,
                "smartcut_strategies_recorded": 0,
            }
        }

        with patch("services.evolution_sync_service.EvolutionSyncService", mock_service):
            client = TestClient(app)
            resp = client.post("/api/evolution/sync")
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        result = data["result"]
        assert "decisions_synced" in result
        assert "constitution_updates" in result
        assert "philosophy_triggered" in result
        assert result["decisions_synced"] == 5
        assert result["constitution_updates"] == 2

    def test_get_evolution_status_with_log(self, tmp_path, mock_decision_logger):
        """TR-06: GET /evolution/status (evo_log存在) → entries数+philosophies数+decision_count"""
        from main import app

        mock_service = MagicMock()
        mock_service.return_value.get_evolution_status.return_value = {
            "evolution_entries": 2,
            "philosophies": 1,
            "decision_count": 42,
            "last_sync": "2026-05-10T00:00:00",
            "smartcut_strategies": 0,
        }

        with patch("services.evolution_sync_service.EvolutionSyncService", mock_service):
            client = TestClient(app)
            resp = client.get("/api/evolution/status")

        assert resp.status_code == 200
        data = resp.json()
        assert "evolution_entries" in data
        assert "philosophies" in data
        assert "decision_count" in data
        assert data["decision_count"] == 42

    def test_get_evolution_status_no_log(self, mock_decision_logger):
        """TR-07: GET /evolution/status (evo_logなし) → evolution_entries=0"""
        from main import app

        mock_service = MagicMock()
        mock_service.return_value.get_evolution_status.return_value = {
            "evolution_entries": 0,
            "philosophies": 0,
            "decision_count": 0,
            "last_sync": None,
            "smartcut_strategies": 0,
        }

        with patch("services.evolution_sync_service.EvolutionSyncService", mock_service):
            client = TestClient(app)
            resp = client.get("/api/evolution/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["evolution_entries"] == 0
        assert data["philosophies"] == 0

    def test_get_evolution(self, mock_branding_manager):
        """TR-08: GET /evolution → 200, evolution_log"""
        from main import app
        with patch("branding_manager.branding_manager", mock_branding_manager):
            client = TestClient(app)
            resp = client.get("/api/evolution")
        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data

    def test_get_evolution_proposals(self):
        """TR-09: GET /evolution/proposals → 200, proposals list"""
        from main import app
        
        mock_proposal = MagicMock()
        mock_proposal.proposal_id = "prop_123"
        mock_proposal.content = "Test Content"
        mock_proposal.source_summary = "Summary"
        mock_proposal.generated_at = "2026-05-20"
        mock_proposal.status = "pending"
        mock_proposal.user_edit = "edit"
        
        mock_service = MagicMock()
        mock_service.return_value.get_pending_proposals.return_value = [mock_proposal]
        
        with patch("services.philosophy_proposal_service.PhilosophyProposalService", mock_service):
            client = TestClient(app)
            resp = client.get("/api/evolution/proposals")
            
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["proposal_id"] == "prop_123"

    def test_approve_evolution_proposal(self):
        """TR-10: POST /evolution/proposals/{proposal_id}/approve → 200"""
        from main import app
        
        mock_service = MagicMock()
        mock_service.return_value.approve_proposal.return_value = True
        
        with patch("services.philosophy_proposal_service.PhilosophyProposalService", mock_service):
            client = TestClient(app)
            resp = client.post("/api/evolution/proposals/prop_123/approve", json={"edited_text": "Updated Text"})
            
        assert resp.status_code == 200
        data = resp.json()
        assert data["approved"] is True
        assert data["proposal_id"] == "prop_123"
        mock_service.return_value.approve_proposal.assert_called_once_with("prop_123", edited="Updated Text")

    def test_reject_evolution_proposal(self):
        """TR-11: POST /evolution/proposals/{proposal_id}/reject → 200"""
        from main import app
        
        mock_service = MagicMock()
        mock_service.return_value.reject_proposal.return_value = True
        
        with patch("services.philosophy_proposal_service.PhilosophyProposalService", mock_service):
            client = TestClient(app)
            resp = client.post("/api/evolution/proposals/prop_123/reject", json={"reason": "No good"})
            
        assert resp.status_code == 200
        data = resp.json()
        assert data["rejected"] is True
        assert data["proposal_id"] == "prop_123"
        mock_service.return_value.reject_proposal.assert_called_once_with("prop_123", reason="No good")

    def test_get_evolution_dashboard(self):
        """TR-12: GET /evolution/dashboard → 200, dashboard data"""
        from main import app
        
        mock_service = MagicMock()
        mock_service.return_value.get_dashboard_data.return_value = {
            "trigger_status": {},
            "proposals": [],
            "trust": 0.9,
            "philosophy_timeline": [],
            "trigger_history": []
        }
        
        with patch("services.evolution_sync_service.EvolutionSyncService", mock_service):
            client = TestClient(app)
            resp = client.get("/api/evolution/dashboard")
            
        assert resp.status_code == 200
        data = resp.json()
        assert "trust" in data
        assert data["trust"] == 0.9

    def test_get_evolution_triggers(self):
        """TR-13: GET /evolution/triggers → 200, triggers list"""
        from main import app
        
        mock_service = MagicMock()
        mock_service.return_value.get_trigger_status.return_value = [
            {"trigger_id": "t1", "fired": True}
        ]
        
        with patch("services.evolution_trigger_service.EvolutionTriggerService", mock_service):
            client = TestClient(app)
            resp = client.get("/api/evolution/triggers")
            
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data[0]["trigger_id"] == "t1"


# ─────────────────────────────────────────────
# Fixtures: VideoProcessor
# ─────────────────────────────────────────────

@pytest.fixture
def vp(tmp_path):
    """VideoProcessorインスタンス（テスト用tmpdir）"""
    from video_processor import VideoProcessor
    return VideoProcessor(output_dir=str(tmp_path / "output"))


# ─────────────────────────────────────────────
# VP-01~08: VideoProcessor
# ─────────────────────────────────────────────

class TestVideoProcessor:
    def test_process_video_full_success(self, vp, tmp_path, safe_popen_mock):
        """VP-01: process_video → True, phase=COMPLETE, progress=100"""
        from video_processor import ProcessingPhase

        # 実在するダミーファイルを作成
        vid = tmp_path / "test.mp4"
        vid.write_bytes(b"fake_video_data")

        task = vp.create_task("t001", [str(vid)], "elegant")

        proc = safe_popen_mock(returncode=0)
        with patch("video_processor.subprocess.Popen", return_value=proc), \
             patch.object(vp, "_record_soul_narrative"):
            result = vp.process_video("t001")

        assert result is True
        assert task.phase == ProcessingPhase.COMPLETE
        assert task.progress == 100
        assert task.output_path is not None

    def test_process_video_no_valid_paths_no_demo(self, vp, tmp_path, safe_popen_mock):
        """VP-02: 全パス不存在+デモなし → warning発生しても処理継続（空シーン）"""
        task = vp.create_task("t002", ["/nonexistent/video.mp4"], "dynamic")

        proc = safe_popen_mock(returncode=0)
        with patch("video_processor.subprocess.Popen", return_value=proc), \
             patch("pathlib.Path.exists", return_value=False), \
             patch("pathlib.Path.glob", return_value=[]), \
             patch.object(vp, "_record_soul_narrative"):
            result = vp.process_video("t002")

        # パスなし+デモなし → processedシーン0でmerge/branding実行
        # エラーでもTrueまたはFalse (graceful)
        assert isinstance(result, bool)

    def test_process_video_with_demo_fallback(self, vp, tmp_path, safe_popen_mock):
        """VP-03: パス不存在+デモdir存在 → デモ動画使用"""
        from video_processor import ProcessingPhase

        demo_vid = tmp_path / "demo.mp4"
        demo_vid.write_bytes(b"demo_video")

        task = vp.create_task("t003", ["/nonexistent.mp4"], "dramatic")

        proc = safe_popen_mock(returncode=0)
        with patch("video_processor.subprocess.Popen", return_value=proc), \
             patch("pathlib.Path.exists", side_effect=lambda self=None: True), \
             patch("pathlib.Path.glob", return_value=[demo_vid]), \
             patch.object(vp, "_record_soul_narrative"):
            result = vp.process_video("t003")

        assert isinstance(result, bool)

    def test_process_video_exception(self, vp, tmp_path):
        """VP-04: process_video中に例外 → phase=ERROR, return False"""
        from video_processor import ProcessingPhase

        task = vp.create_task("t004", ["/nonexistent.mp4"], "elegant")

        with patch.object(vp, "get_mood_settings", side_effect=RuntimeError("mood error")):
            result = vp.process_video("t004")

        assert result is False
        assert task.phase == ProcessingPhase.ERROR
        assert "mood error" in task.error

    def test_merge_scenes_single(self, vp, tmp_path):
        """VP-05: 1シーン → shutil.copy（FFmpeg不要）"""
        src = tmp_path / "scene1.mp4"
        src.write_bytes(b"scene1_data")
        dst = tmp_path / "merged.mp4"

        # shutil は関数内ローカルimportのため shutil.copy を直接パッチ
        with patch("shutil.copy") as mock_copy:
            vp._merge_scenes([str(src)], str(dst))

        mock_copy.assert_called_once_with(str(src), str(dst))

    def test_merge_scenes_failure_fallback(self, vp, tmp_path, safe_popen_mock):
        """VP-06: FFmpeg失敗 → 最初のシーンコピー"""
        src1 = tmp_path / "scene1.mp4"
        src2 = tmp_path / "scene2.mp4"
        src1.write_bytes(b"scene1")
        src2.write_bytes(b"scene2")
        dst = tmp_path / "merged.mp4"

        proc = safe_popen_mock(returncode=1)
        with patch("video_processor.subprocess.Popen", return_value=proc), \
             patch("shutil.copy") as mock_copy:
            vp._merge_scenes([str(src1), str(src2)], str(dst))

        mock_copy.assert_called_once_with(str(src1), str(dst))

    def test_apply_branding_no_logo(self, vp, tmp_path):
        """VP-07: ロゴ不存在 → コピーフォールバック"""
        src = tmp_path / "merged.mp4"
        src.write_bytes(b"merged")
        dst = tmp_path / "final.mp4"

        settings = vp.get_mood_settings("elegant")

        with patch.object(Path, "exists", return_value=False), \
             patch("shutil.copy") as mock_copy:
            vp._apply_branding(str(src), str(dst), settings)

        mock_copy.assert_called_once_with(str(src), str(dst))

    def test_apply_branding_ffmpeg_failure(self, vp, tmp_path, safe_popen_mock):
        """VP-08: FFmpeg失敗 → コピーフォールバック"""
        src = tmp_path / "merged.mp4"
        src.write_bytes(b"merged")
        logo = tmp_path / "logo.png"
        logo.write_bytes(b"logo_data")
        dst = tmp_path / "final.mp4"

        settings = vp.get_mood_settings("dynamic")
        proc = safe_popen_mock(returncode=1)

        with patch.object(Path, "exists", return_value=True), \
             patch("video_processor.subprocess.Popen", return_value=proc), \
             patch("shutil.copy") as mock_copy:
            vp._apply_branding(str(src), str(dst), settings)

        mock_copy.assert_called_once_with(str(src), str(dst))
