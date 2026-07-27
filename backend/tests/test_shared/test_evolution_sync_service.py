"""
Sprint 4.1.4: EvolutionSyncService テスト

MASTER L1778-L1779 検証:
- S414-01: sync_all() → decisions_synced + constitution_updates
- S414-02: finalize → evolution_logにstrategyエントリ

追加テスト:
- S414-03: /evolution/sync → EvolutionSyncService経由
- S414-04: /evolution/status → EvolutionSyncService経由
- S414-05: record_strategy エラー時 graceful degradation
- S414-06: sync_all エラー時 graceful degradation
- S414-07: get_evolution_status 正常動作

設計書: sprint_41_design.md §Q3 仮説B
セルフチェック: SC-5 (evolution/sync → 200), SC-7 (finalize後にstrategy記録)
"""
import json
import time
import pytest
import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from services.evolution_sync_service import EvolutionSyncService


# ─────────────────────────────────────────────
# S414-01: sync_all() → decisions_synced + constitution_updates
# ─────────────────────────────────────────────

class TestEvolutionSyncAll:
    """S414-01: sync_all()の統合同期検証"""

    def test_sync_all_success(self, tmp_path):
        """sync_all() が decisions_synced + constitution_updates を返す"""
        evo_log_path = tmp_path / "evolution_log.json"
        evo_log_path.write_text(json.dumps({
            "entries": [
                {"type": "smartcut_strategy", "summary": "test"},
                {"type": "video_production", "summary": "test2"},
            ],
            "philosophies": [{"text": "p1"}],
            "decision_insights": [],
        }), encoding="utf-8")

        service = EvolutionSyncService(evolution_log_path=evo_log_path)

        mock_dl = MagicMock()
        mock_dl.sync_to_soul_narrative.return_value = {
            "synced": 5, "new_insights": [{"type": "preference"}]
        }

        mock_bm = MagicMock()
        mock_bm.process_analytics_update.return_value = {"updates": 3}

        with patch("decision_logger.decision_logger", mock_dl), \
             patch("branding_manager.branding_manager", mock_bm):
            result = service.sync_all()

        assert result["status"] == "success"
        r = result["result"]
        assert r["decisions_synced"] == 5
        assert r["constitution_updates"] == 3
        assert r["philosophy_triggered"] is True
        assert r["smartcut_strategies_recorded"] == 1

    def test_sync_all_no_insights(self, tmp_path):
        """sync結果にnew_insightsが空の場合、philosophy_triggered=False"""
        evo_log_path = tmp_path / "evolution_log.json"
        evo_log_path.write_text(json.dumps({
            "entries": [], "philosophies": [],
        }), encoding="utf-8")

        service = EvolutionSyncService(evolution_log_path=evo_log_path)

        mock_dl = MagicMock()
        mock_dl.sync_to_soul_narrative.return_value = {"synced": 0}

        mock_bm = MagicMock()
        mock_bm.process_analytics_update.return_value = {"updates": 0}

        with patch("decision_logger.decision_logger", mock_dl), \
             patch("branding_manager.branding_manager", mock_bm):
            result = service.sync_all()

        assert result["status"] == "success"
        r = result["result"]
        assert r["decisions_synced"] == 0
        assert r["constitution_updates"] == 0
        assert r["philosophy_triggered"] is False
        assert r["smartcut_strategies_recorded"] == 0

    def test_sync_all_decision_logger_fails(self, tmp_path):
        """decision_logger失敗時もgraceful degradation"""
        evo_log_path = tmp_path / "evolution_log.json"
        evo_log_path.write_text(json.dumps({
            "entries": [], "philosophies": [],
        }), encoding="utf-8")

        service = EvolutionSyncService(evolution_log_path=evo_log_path)

        mock_dl = MagicMock()
        mock_dl.sync_to_soul_narrative.side_effect = RuntimeError("DB error")

        mock_bm = MagicMock()
        mock_bm.process_analytics_update.return_value = {"updates": 1}

        with patch("decision_logger.decision_logger", mock_dl), \
             patch("branding_manager.branding_manager", mock_bm):
            result = service.sync_all()

        assert result["status"] == "success"
        r = result["result"]
        assert r["decisions_synced"] == 0  # エラー時はデフォルト
        assert r["constitution_updates"] == 1  # 他は正常に動作

    def test_sync_all_branding_manager_fails(self, tmp_path):
        """branding_manager失敗時もgraceful degradation"""
        evo_log_path = tmp_path / "evolution_log.json"
        evo_log_path.write_text(json.dumps({
            "entries": [], "philosophies": [],
        }), encoding="utf-8")

        service = EvolutionSyncService(evolution_log_path=evo_log_path)

        mock_dl = MagicMock()
        mock_dl.sync_to_soul_narrative.return_value = {"synced": 2}

        mock_bm = MagicMock()
        mock_bm.process_analytics_update.side_effect = RuntimeError("API error")

        with patch("decision_logger.decision_logger", mock_dl), \
             patch("branding_manager.branding_manager", mock_bm):
            result = service.sync_all()

        assert result["status"] == "success"
        r = result["result"]
        assert r["decisions_synced"] == 2
        assert r["constitution_updates"] == 0  # エラー時はデフォルト


# ─────────────────────────────────────────────
# S414-02: finalize → evolution_logにstrategyエントリ
# ─────────────────────────────────────────────

class TestRecordStrategy:
    """S414-02: CutStrategyのevolution_log永続化"""

    def test_record_strategy_basic(self, tmp_path):
        """record_strategy() でevolution_logにstrategyエントリが追加される"""
        from services.smartcut_strategy_service import CutStrategy

        evo_log_path = tmp_path / "evolution_log.json"
        evo_log_path.write_text(json.dumps({
            "entries": [], "philosophies": [],
        }), encoding="utf-8")

        service = EvolutionSyncService(evolution_log_path=evo_log_path)
        strategy = CutStrategy(
            summary="テスト戦略：冒頭の印象を重視",
            position_weights={"intro": 1.5, "body": 1.0, "highlight": 1.2, "outro": 0.9},
            brand_alignment_score=0.87,
            applied_philosophies=["技術と芸術の融合"],
            recommended_cut_rate=0.45,
            generated_at="2026-05-11T19:00:00",
            model_used="gemini-2.5-flash",
            trust_score=0.0,
        )

        result = service.record_strategy(
            strategy=strategy,
            session_id="test-session-001",
            finalize_result={"final_segments": [{"id": "s1"}], "total_duration": 900},
        )

        assert result is True

        # evolution_logの内容を検証
        with open(evo_log_path, "r", encoding="utf-8") as f:
            saved = json.load(f)

        assert len(saved["entries"]) == 1
        entry = saved["entries"][0]
        assert entry["type"] == "smartcut_strategy"
        assert entry["session_id"] == "test-session-001"
        assert "冒頭の印象を重視" in entry["summary"]
        assert entry["strategy_detail"]["brand_alignment_score"] == 0.87
        assert entry["strategy_detail"]["trust_score"] == 0.0
        assert entry["strategy_detail"]["model_used"] == "gemini-2.5-flash"
        assert entry["finalize_summary"]["segment_count"] == 1
        assert entry["finalize_summary"]["total_duration"] == 900
        assert "last_sync" in saved

    def test_record_strategy_without_finalize(self, tmp_path):
        """finalize_resultなしでもrecord_strategyが正常動作"""
        from services.smartcut_strategy_service import CutStrategy

        evo_log_path = tmp_path / "evolution_log.json"
        evo_log_path.write_text(json.dumps({
            "entries": [], "philosophies": [],
        }), encoding="utf-8")

        service = EvolutionSyncService(evolution_log_path=evo_log_path)
        strategy = CutStrategy.default()

        result = service.record_strategy(
            strategy=strategy,
            session_id="no-finalize-session",
        )

        assert result is True

        with open(evo_log_path, "r", encoding="utf-8") as f:
            saved = json.load(f)

        entry = saved["entries"][0]
        assert entry["type"] == "smartcut_strategy"
        assert "finalize_summary" not in entry

    def test_record_strategy_appends_to_existing(self, tmp_path):
        """既存のentriesに追記される（上書きしない）"""
        from services.smartcut_strategy_service import CutStrategy

        evo_log_path = tmp_path / "evolution_log.json"
        evo_log_path.write_text(json.dumps({
            "entries": [{"type": "video_production", "summary": "既存エントリ"}],
            "philosophies": [],
        }), encoding="utf-8")

        service = EvolutionSyncService(evolution_log_path=evo_log_path)
        strategy = CutStrategy.default()

        service.record_strategy(strategy=strategy, session_id="append-test")

        with open(evo_log_path, "r", encoding="utf-8") as f:
            saved = json.load(f)

        assert len(saved["entries"]) == 2
        assert saved["entries"][0]["type"] == "video_production"
        assert saved["entries"][1]["type"] == "smartcut_strategy"

    def test_record_strategy_error_returns_false(self, tmp_path):
        """evolution_log書込み失敗時にFalseを返す（graceful degradation）"""
        from services.smartcut_strategy_service import CutStrategy

        # C-05: safe_save_jsonはディレクトリ自動作成するため、
        # _save_evolution_logをモックしてエラーをシミュレート
        evo_log_path = tmp_path / "evolution_log.json"
        evo_log_path.write_text(json.dumps({
            "entries": [], "philosophies": [],
        }), encoding="utf-8")

        service = EvolutionSyncService(evolution_log_path=evo_log_path)
        strategy = CutStrategy.default()

        with patch.object(service, "_save_evolution_log", side_effect=PermissionError("write denied")):
            result = service.record_strategy(strategy=strategy, session_id="error-test")
        assert result is False

    def test_record_strategy_invalid_finalize_result(self, tmp_path):
        """finalize_resultが辞書ではない無効な型の場合に、AttributeErrorを安全に処理しFalseを返す"""
        from services.smartcut_strategy_service import CutStrategy
        evo_log_path = tmp_path / "evolution_log.json"
        evo_log_path.write_text(json.dumps({
            "entries": [], "philosophies": [],
        }), encoding="utf-8")
        service = EvolutionSyncService(evolution_log_path=evo_log_path)
        strategy = CutStrategy.default()

        # finalize_result に辞書ではない値（文字列など）を渡して AttributeError を誘発させる
        result = service.record_strategy(
            strategy=strategy,
            session_id="invalid-finalize-session",
            finalize_result="this-is-not-a-dict"
        )
        assert result is False

    def test_record_strategy_missing_fields_in_strategy(self, tmp_path):
        """strategyオブジェクトに必要なプロパティが欠けている場合、AttributeErrorをキャッチしFalseを返す"""
        evo_log_path = tmp_path / "evolution_log.json"
        evo_log_path.write_text(json.dumps({
            "entries": [], "philosophies": [],
        }), encoding="utf-8")
        service = EvolutionSyncService(evolution_log_path=evo_log_path)
        
        # summaryやbrand_alignment_score等を持たないダミーオブジェクト
        dummy_strategy = object()
        result = service.record_strategy(
            strategy=dummy_strategy,
            session_id="missing-fields-session"
        )
        assert result is False


# ─────────────────────────────────────────────
# S414-03: /evolution/sync → EvolutionSyncService経由
# ─────────────────────────────────────────────

class TestTrinityEvolutionSyncEndpoint:
    """S414-03: trinity.py /evolution/sync がEvolutionSyncService経由で動作"""

    def test_evolution_sync_endpoint(self):
        """POST /evolution/sync → 200, sync_allの結果が返る"""
        from main import app
        from fastapi.testclient import TestClient

        mock_service = MagicMock()
        mock_service.return_value.sync_all.return_value = {
            "status": "success",
            "result": {
                "decisions_synced": 7,
                "constitution_updates": 2,
                "philosophy_triggered": True,
                "smartcut_strategies_recorded": 3,
            }
        }

        with patch("services.evolution_sync_service.EvolutionSyncService", mock_service):
            client = TestClient(app)
            resp = client.post("/api/evolution/sync")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["result"]["decisions_synced"] == 7
        assert data["result"]["constitution_updates"] == 2
        assert data["result"]["smartcut_strategies_recorded"] == 3


# ─────────────────────────────────────────────
# S414-04: /evolution/status → EvolutionSyncService経由
# ─────────────────────────────────────────────

class TestTrinityEvolutionStatusEndpoint:
    """S414-04: trinity.py /evolution/status がEvolutionSyncService経由で動作"""

    def test_evolution_status_endpoint(self):
        """GET /evolution/status → 200, get_evolution_statusの結果が返る"""
        from main import app
        from fastapi.testclient import TestClient

        mock_service = MagicMock()
        mock_service.return_value.get_evolution_status.return_value = {
            "evolution_entries": 10,
            "philosophies": 228,
            "decision_count": 42,
            "last_sync": "2026-05-11T19:00:00",
            "smartcut_strategies": 5,
        }

        with patch("services.evolution_sync_service.EvolutionSyncService", mock_service):
            client = TestClient(app)
            resp = client.get("/api/evolution/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["evolution_entries"] == 10
        assert data["philosophies"] == 228
        assert data["decision_count"] == 42
        assert data["smartcut_strategies"] == 5


# ─────────────────────────────────────────────
# S414-05: get_evolution_status 正常動作
# ─────────────────────────────────────────────

class TestGetEvolutionStatus:
    """S414-05: get_evolution_status()の検証"""

    def test_status_with_data(self, tmp_path):
        """各種データが存在する場合のステータス取得"""
        evo_log_path = tmp_path / "evolution_log.json"
        evo_log_path.write_text(json.dumps({
            "entries": [
                {"type": "video_production", "summary": "e1"},
                {"type": "smartcut_strategy", "summary": "s1"},
                {"type": "smartcut_strategy", "summary": "s2"},
            ],
            "philosophies": [{"text": "p1"}, {"text": "p2"}, {"text": "p3"}],
            "last_sync": "2026-05-11T10:00:00",
        }), encoding="utf-8")

        service = EvolutionSyncService(evolution_log_path=evo_log_path)

        mock_dl = MagicMock()
        mock_dl.get_stats.return_value = {"total_decisions": 15}

        with patch("decision_logger.decision_logger", mock_dl):
            status = service.get_evolution_status()

        assert status["evolution_entries"] == 3
        assert status["philosophies"] == 3
        assert status["decision_count"] == 15
        assert status["last_sync"] == "2026-05-11T10:00:00"
        assert status["smartcut_strategies"] == 2

    def test_status_no_log_file(self, tmp_path):
        """evolution_log.jsonが存在しない場合のデフォルト値"""
        evo_log_path = tmp_path / "nonexistent.json"
        service = EvolutionSyncService(evolution_log_path=evo_log_path)

        with patch("decision_logger.decision_logger", MagicMock()) as mock_dl:
            mock_dl.get_stats.return_value = {"total_decisions": 0}
            status = service.get_evolution_status()

        assert status["evolution_entries"] == 0
        assert status["philosophies"] == 0
        assert status["smartcut_strategies"] == 0
        assert status["last_sync"] is None

    def test_status_decision_logger_fails(self, tmp_path):
        """decision_loggerがエラーでもgraceful"""
        evo_log_path = tmp_path / "evolution_log.json"
        evo_log_path.write_text(json.dumps({
            "entries": [{"type": "x"}],
            "philosophies": [{"text": "p"}],
        }), encoding="utf-8")

        service = EvolutionSyncService(evolution_log_path=evo_log_path)

        mock_dl = MagicMock()
        mock_dl.get_stats.side_effect = RuntimeError("logger broken")

        with patch("decision_logger.decision_logger", mock_dl):
            status = service.get_evolution_status()

        assert status["evolution_entries"] == 1
        assert status["decision_count"] == 0  # エラー時デフォルト

    def test_status_decision_logger_invalid_return(self, tmp_path):
        """decision_logger.get_stats()が無効な型（None等）を返した場合に、例外をキャッチしてdecision_countが0になる"""
        evo_log_path = tmp_path / "evolution_log.json"
        evo_log_path.write_text(json.dumps({
            "entries": [], "philosophies": [],
        }), encoding="utf-8")
        service = EvolutionSyncService(evolution_log_path=evo_log_path)

        mock_dl = MagicMock()
        mock_dl.get_stats.return_value = None  # getメソッドを持たないためAttributeErrorが発生する

        with patch("decision_logger.decision_logger", mock_dl):
            status = service.get_evolution_status()

        assert status["decision_count"] == 0


# ─────────────────────────────────────────────
# エッジケース / 例外ハンドリングのカバレッジ向上テスト
# ─────────────────────────────────────────────

class TestEvolutionSyncAllEdgeCases:
    """sync_all 内の各種 ImportError および一般例外のデグレード処理の検証"""

    def test_sync_all_decision_logger_import_error(self, tmp_path):
        """decision_logger インポートエラー時に警告を出力し、デフォルト値で継続する"""
        evo_log_path = tmp_path / "evolution_log.json"
        evo_log_path.write_text(json.dumps({"entries": []}), encoding="utf-8")
        service = EvolutionSyncService(evolution_log_path=evo_log_path)

        with patch.dict(sys.modules, {"decision_logger": None}):
            result = service.sync_all()

        assert result["status"] == "success"
        assert result["result"]["decisions_synced"] == 0
        assert result["result"]["philosophy_triggered"] is False

    def test_sync_all_branding_manager_import_error(self, tmp_path):
        """branding_manager インポートエラー時に警告を出力し、デフォルト値で継続する"""
        evo_log_path = tmp_path / "evolution_log.json"
        evo_log_path.write_text(json.dumps({"entries": []}), encoding="utf-8")
        service = EvolutionSyncService(evolution_log_path=evo_log_path)

        with patch.dict(sys.modules, {"branding_manager": None}):
            result = service.sync_all()

        assert result["status"] == "success"
        assert result["result"]["constitution_updates"] == 0

    def test_sync_all_trigger_service_import_error(self, tmp_path):
        """EvolutionTriggerService インポートエラー時に警告を出力し、デフォルト値で継続する"""
        evo_log_path = tmp_path / "evolution_log.json"
        evo_log_path.write_text(json.dumps({"entries": []}), encoding="utf-8")
        service = EvolutionSyncService(evolution_log_path=evo_log_path)

        with patch.dict(sys.modules, {"services.evolution_trigger_service": None}):
            result = service.sync_all()

        assert result["status"] == "success"
        assert result["result"]["trigger_results"] == []

    def test_sync_all_trigger_service_general_exception(self, tmp_path):
        """EvolutionTriggerService 評価時の一般例外発生時に警告を出力し、デフォルト値で継続する"""
        evo_log_path = tmp_path / "evolution_log.json"
        evo_log_path.write_text(json.dumps({"entries": []}), encoding="utf-8")
        service = EvolutionSyncService(evolution_log_path=evo_log_path)

        with patch("services.evolution_trigger_service.EvolutionTriggerService") as mock_service_cls:
            mock_service_cls.side_effect = RuntimeError("Trigger evaluation failed")
            result = service.sync_all()

        assert result["status"] == "success"
        assert result["result"]["trigger_results"] == []

    def test_sync_all_strategy_count_general_exception(self, tmp_path):
        """SmartCut戦略記録数取得時の一般例外発生時に警告を出力し、デフォルト値で継続する"""
        evo_log_path = tmp_path / "evolution_log.json"
        evo_log_path.write_text(json.dumps({"entries": []}), encoding="utf-8")
        service = EvolutionSyncService(evolution_log_path=evo_log_path)

        # _load_evolution_log で例外を発生させる
        with patch.object(service, "_load_evolution_log", side_effect=RuntimeError("Load failed")):
            result = service.sync_all()

        assert result["status"] == "success"
        assert result["result"]["smartcut_strategies_recorded"] == 0


class TestGetDashboardDataEdgeCases:
    """get_dashboard_data 内の例外ハンドリングの検証"""

    def test_get_dashboard_data_trigger_status_fails(self, tmp_path):
        """EvolutionTriggerService のステータス取得失敗時に警告を出力し、デフォルト値で継続する"""
        evo_log_path = tmp_path / "evolution_log.json"
        evo_log_path.write_text(json.dumps({"entries": []}), encoding="utf-8")
        service = EvolutionSyncService(evolution_log_path=evo_log_path)

        with patch("services.evolution_trigger_service.EvolutionTriggerService") as mock_service_cls:
            mock_service = MagicMock()
            mock_service.get_trigger_status.side_effect = RuntimeError("Trigger status failed")
            mock_service_cls.return_value = mock_service

            data = service.get_dashboard_data()

        assert data["trigger_status"] == {"rules": []}

    def test_get_dashboard_data_philosophy_proposal_fails(self, tmp_path):
        """PhilosophyProposalService の提案取得失敗時に警告を出力し、デフォルト値で継続する"""
        evo_log_path = tmp_path / "evolution_log.json"
        evo_log_path.write_text(json.dumps({"entries": []}), encoding="utf-8")
        service = EvolutionSyncService(evolution_log_path=evo_log_path)

        with patch("services.philosophy_proposal_service.PhilosophyProposalService") as mock_service_cls:
            mock_service = MagicMock()
            mock_service.get_pending_proposals.side_effect = RuntimeError("Proposal fetch failed")
            mock_service_cls.return_value = mock_service

            data = service.get_dashboard_data()

        assert data["pending_proposals"] == []

    def test_get_dashboard_data_proposals_none(self, tmp_path):
        """PhilosophyProposalService.get_pending_proposals()がNoneを返した際、警告を出力してpending_proposalsが空で継続される"""
        evo_log_path = tmp_path / "evolution_log.json"
        evo_log_path.write_text(json.dumps({"entries": []}), encoding="utf-8")
        service = EvolutionSyncService(evolution_log_path=evo_log_path)

        with patch("services.philosophy_proposal_service.PhilosophyProposalService") as mock_service_cls:
            mock_service = MagicMock()
            mock_service.get_pending_proposals.return_value = None  # NoneTypeはイテレーション不可
            mock_service_cls.return_value = mock_service

            data = service.get_dashboard_data()

        assert data["pending_proposals"] == []

    def test_get_dashboard_data_proposal_missing_attribute(self, tmp_path):
        """提案オブジェクトから属性が欠落してAttributeErrorが発生した際、警告を出力して安全に継続される"""
        evo_log_path = tmp_path / "evolution_log.json"
        evo_log_path.write_text(json.dumps({"entries": []}), encoding="utf-8")
        service = EvolutionSyncService(evolution_log_path=evo_log_path)

        with patch("services.philosophy_proposal_service.PhilosophyProposalService") as mock_service_cls:
            mock_service = MagicMock()
            
            # proposal_id などの属性にアクセスした際に AttributeError を引き起こすオブジェクト
            class BadProposal:
                @property
                def proposal_id(self):
                    raise AttributeError("missing proposal_id")
            
            mock_proposal = BadProposal()
            mock_service.get_pending_proposals.return_value = [mock_proposal]
            mock_service_cls.return_value = mock_service

            data = service.get_dashboard_data()

        assert data["pending_proposals"] == []


class TestLoadEvolutionLogEdgeCases:
    """_load_evolution_log 内の例外ハンドリングの検証"""

    def test_load_evolution_log_io_exception(self, tmp_path):
        """safe_load_json 失敗時に警告を出力し、デフォルト辞書を返す"""
        evo_log_path = tmp_path / "evolution_log.json"
        service = EvolutionSyncService(evolution_log_path=evo_log_path)

        with patch("utils.json_safe_io.safe_load_json", side_effect=RuntimeError("File locked or read error")):
            data = service._load_evolution_log()

        assert data == {"entries": [], "philosophies": [], "decision_insights": []}

    def test_load_evolution_log_returns_empty_or_none(self, tmp_path):
        """safe_load_jsonが空の辞書またはNoneを返した際、デフォルト構造が返される"""
        evo_log_path = tmp_path / "evolution_log.json"
        service = EvolutionSyncService(evolution_log_path=evo_log_path)

        with patch("utils.json_safe_io.safe_load_json", return_value=None):
            data1 = service._load_evolution_log()
        assert data1 == {"entries": [], "philosophies": [], "decision_insights": []}

        with patch("utils.json_safe_io.safe_load_json", return_value={}):
            data2 = service._load_evolution_log()
        assert data2 == {"entries": [], "philosophies": [], "decision_insights": []}


class TestEvolutionSyncInit:
    """EvolutionSyncService初期化テスト"""

    def test_init_default_path(self):
        """パス指定なしで初期化した場合、デフォルトのパスが設定される"""
        import services.evolution_sync_service
        service = EvolutionSyncService()
        backend_dir = Path(services.evolution_sync_service.__file__).parent.parent
        expected_path = backend_dir / "branding" / "evolution_log.json"
        assert service._evolution_log_path.resolve() == expected_path.resolve()


class TestGetDashboardData:
    """get_dashboard_data() の正常系テスト"""

    def test_get_dashboard_data_success(self, tmp_path):
        """各種データが存在する場合のダッシュボードデータ取得"""
        evo_log_path = tmp_path / "evolution_log.json"

        # 通知、監督プロファイル、entries、philosophies 等を含むモックログデータ
        mock_log_data = {
            "trust_score": 0.85,
            "trust_history": [0.80, 0.85],
            "philosophies": [{"text": "哲学1"}, {"text": "哲学2"}],
            "trigger_history": [{"trigger": "rule_1"}],
            "entries": [{"type": "smartcut_strategy", "summary": "s"}] * 25,
            "notifications": [
                {"id": "n1", "read": False},
                {"id": "n2", "read": True},
                {"id": "n3", "read": False},
            ],
            "director_profile": {"level": 5, "exp": 1200}
        }
        evo_log_path.write_text(json.dumps(mock_log_data), encoding="utf-8")

        service = EvolutionSyncService(evolution_log_path=evo_log_path)

        # EvolutionTriggerService のモック
        mock_trigger_svc = MagicMock()
        mock_trigger_svc.get_trigger_status.return_value = {"rules": [{"name": "rule1", "active": True}]}

        # PhilosophyProposalService のモック
        mock_proposal_svc = MagicMock()
        mock_proposal = MagicMock()
        mock_proposal.proposal_id = "prop_001"
        mock_proposal.content = "新しい哲学提案"
        mock_proposal.source_summary = "要因サマリー"
        mock_proposal.generated_at = "2026-05-26T14:00:00"
        mock_proposal.status = "pending"
        mock_proposal.user_edit = None
        mock_proposal_svc.get_pending_proposals.return_value = [mock_proposal]

        with patch("services.evolution_trigger_service.EvolutionTriggerService", return_value=mock_trigger_svc), \
             patch("services.philosophy_proposal_service.PhilosophyProposalService", return_value=mock_proposal_svc):
            data = service.get_dashboard_data()

        assert data["trust_score"] == 0.85
        assert data["trust_history"] == [0.80, 0.85]
        assert data["philosophies_count"] == 2
        assert len(data["philosophies"]) == 2
        assert len(data["trigger_history"]) == 1
        assert data["evolution_entries_count"] == 25
        assert data["evolution_entries"] == 25
        assert len(data["entries"]) == 20  # entries[-20:] のため20件に制限

        # 未読通知のみ抽出されているか確認
        assert len(data["notifications"]) == 2
        assert data["notifications"][0]["id"] == "n1"
        assert data["notifications"][1]["id"] == "n3"

        # 監督プロファイル
        assert data["director_profile"]["level"] == 5


class TestEvolutionSyncSafeExecute:
    """_safe_execute コンテキストマネージャの検証"""

    def test_safe_execute_success(self):
        """例外が発生しない場合、ブロック内の処理が正常に実行される"""
        service = EvolutionSyncService()
        execution_flag = False

        with service._safe_execute("test_action"):
            execution_flag = True

        assert execution_flag is True

    def test_safe_execute_import_error(self):
        """ImportError が発生した場合、警告ログを出力し例外は外部に伝播しない"""
        service = EvolutionSyncService()

        with patch("services.evolution_sync_service.logger.warning") as mock_warning:
            with service._safe_execute("test_import_error"):
                raise ImportError("dummy import error")

        mock_warning.assert_called_once()
        assert "dummy import error" in mock_warning.call_args[0][0]

    def test_safe_execute_general_exception(self):
        """一般の Exception が発生した場合、警告ログを出力し例外は外部に伝播しない"""
        service = EvolutionSyncService()

        with patch("services.evolution_sync_service.logger.warning") as mock_warning:
            with service._safe_execute("test_general_error"):
                raise ValueError("dummy value error")

        mock_warning.assert_called_once()
        assert "dummy value error" in mock_warning.call_args[0][0]


class TestLoadEvolutionLogMalformed:
    """_load_evolution_log で不正な構造のJSONデータをロードした場合の検証"""

    def test_load_evolution_log_returns_list(self, tmp_path):
        """safe_load_jsonが辞書ではなくリストを返した場合、そのままリストが返される（現行のL1制約に基づく挙動）"""
        evo_log_path = tmp_path / "evolution_log.json"
        service = EvolutionSyncService(evolution_log_path=evo_log_path)

        with patch("utils.json_safe_io.safe_load_json", return_value=[1, 2, 3]):
            data = service._load_evolution_log()

        assert data == [1, 2, 3]

    def test_load_evolution_log_returns_string(self, tmp_path):
        """safe_load_jsonが辞書ではなく文字列を返した場合、そのまま文字列が返される（現行のL1制約に基づく挙動）"""
        evo_log_path = tmp_path / "evolution_log.json"
        service = EvolutionSyncService(evolution_log_path=evo_log_path)

        with patch("utils.json_safe_io.safe_load_json", return_value="invalid_string"):
            data = service._load_evolution_log()

        assert data == "invalid_string"

    def test_load_evolution_log_returns_falsy_values(self, tmp_path):
        """safe_load_jsonが空リストや空文字列などのfalsyな値を返した場合、デフォルト辞書が返される"""
        evo_log_path = tmp_path / "evolution_log.json"
        service = EvolutionSyncService(evolution_log_path=evo_log_path)

        with patch("utils.json_safe_io.safe_load_json", return_value=[]):
            data1 = service._load_evolution_log()
        assert data1 == {"entries": [], "philosophies": [], "decision_insights": []}

        with patch("utils.json_safe_io.safe_load_json", return_value=""):
            data2 = service._load_evolution_log()
        assert data2 == {"entries": [], "philosophies": [], "decision_insights": []}


class TestEvolutionSyncInitCustom:
    """カスタムパスを用いた初期化の検証"""

    def test_init_custom_path(self, tmp_path):
        """明示的にPathオブジェクトを指定した場合、そのパスが保持される"""
        custom_path = tmp_path / "custom_evolution_log.json"
        service = EvolutionSyncService(evolution_log_path=custom_path)
        assert service._evolution_log_path == custom_path


class TestEvolutionSyncRobustnessCases:
    """追加の堅牢性検証テストケース (Phase 27)"""

    def test_record_strategy_partial_finalize_result(self, tmp_path):
        """finalize_resultの一部キー(final_segments等)が欠損していても、正常に処理されフォールバックすること"""
        from services.smartcut_strategy_service import CutStrategy
        evo_log_path = tmp_path / "evolution_log.json"
        evo_log_path.write_text(json.dumps({"entries": [], "philosophies": []}), encoding="utf-8")
        
        service = EvolutionSyncService(evolution_log_path=evo_log_path)
        strategy = CutStrategy.default()

        # final_segments が欠損している finalize_result
        partial_result = {"total_duration": 450}
        result = service.record_strategy(
            strategy=strategy,
            session_id="partial-finalize-session",
            finalize_result=partial_result
        )
        assert result is True

        with open(evo_log_path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        
        entry = saved["entries"][0]
        assert entry["finalize_summary"]["total_duration"] == 450
        assert entry["finalize_summary"]["segment_count"] == 0

    def test_get_dashboard_data_with_missing_keys(self, tmp_path):
        """evolution_logのtrust_score等がNone、かつentries等のリストキーが欠落している場合でも、get_dashboard_dataがクラッシュせず正常に応答すること"""
        evo_log_path = tmp_path / "evolution_log.json"
        
        # 一部のキーが None、一部のリスト型キー（entriesなど）が完全に欠落しているデータ
        mock_log_data = {
            "trust_score": None,
            "trust_history": None,
            "director_profile": None
            # entries, philosophies, trigger_history, notifications は欠落
        }
        evo_log_path.write_text(json.dumps(mock_log_data), encoding="utf-8")

        service = EvolutionSyncService(evolution_log_path=evo_log_path)

        with patch("services.evolution_trigger_service.EvolutionTriggerService") as mock_trigger_svc_cls,              patch("services.philosophy_proposal_service.PhilosophyProposalService") as mock_proposal_svc_cls:
            
            mock_trigger_svc_cls.return_value.get_trigger_status.return_value = {"rules": []}
            mock_proposal_svc_cls.return_value.get_pending_proposals.return_value = []
            
            data = service.get_dashboard_data()

        # 各値が安全に取得できているか確認（Noneのまま、または適切なデフォルト値）
        assert data["trust_score"] is None
        assert data["trust_history"] is None
        assert data["philosophies_count"] == 0
        assert data["evolution_entries_count"] == 0
        assert data["notifications"] == []

    def test_record_strategy_partial_finalize_result_types(self, tmp_path):
        """finalize_result の final_segments に無効な型（数値等）が指定された場合でも、安全に処理され segment_count = 0 にフォールバックされること"""
        from services.smartcut_strategy_service import CutStrategy
        evo_log_path = tmp_path / "evolution_log.json"
        evo_log_path.write_text(json.dumps({"entries": [], "philosophies": []}), encoding="utf-8")
        
        service = EvolutionSyncService(evolution_log_path=evo_log_path)
        strategy = CutStrategy.default()

        # final_segments がリストではなく数値になっている無効な finalize_result
        partial_result = {"total_duration": 300, "final_segments": 12345}
        result = service.record_strategy(
            strategy=strategy,
            session_id="invalid-segments-type-session",
            finalize_result=partial_result
        )
        assert result is True

        with open(evo_log_path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        
        entry = saved["entries"][0]
        assert entry["finalize_summary"]["total_duration"] == 300
        assert entry["finalize_summary"]["segment_count"] == 0

    def test_get_dashboard_data_malformed_notifications(self, tmp_path):
        """notifications が辞書のリストではなく無効な型（例えば文字列や数値）である場合、get_dashboard_data が安全に空リストを返すこと"""
        evo_log_path = tmp_path / "evolution_log.json"
        mock_log_data = {
            "notifications": "malformed_string_not_list"
        }
        evo_log_path.write_text(json.dumps(mock_log_data), encoding="utf-8")

        service = EvolutionSyncService(evolution_log_path=evo_log_path)

        with patch("services.evolution_trigger_service.EvolutionTriggerService") as mock_trigger_svc_cls,              patch("services.philosophy_proposal_service.PhilosophyProposalService") as mock_proposal_svc_cls:
            
            mock_trigger_svc_cls.return_value.get_trigger_status.return_value = {"rules": []}
            mock_proposal_svc_cls.return_value.get_pending_proposals.return_value = []
            
            data = service.get_dashboard_data()

        assert data["notifications"] == []

    def test_get_dashboard_data_malformed_director_profile(self, tmp_path):
        """director_profile が辞書型ではなく無効な型（例えば文字列）の場合でも、get_dashboard_data が例外をスローせず安全に応答すること"""
        evo_log_path = tmp_path / "evolution_log.json"
        mock_log_data = {
            "director_profile": "director_profile_is_a_string"
        }
        evo_log_path.write_text(json.dumps(mock_log_data), encoding="utf-8")

        service = EvolutionSyncService(evolution_log_path=evo_log_path)

        with patch("services.evolution_trigger_service.EvolutionTriggerService") as mock_trigger_svc_cls,              patch("services.philosophy_proposal_service.PhilosophyProposalService") as mock_proposal_svc_cls:
            
            mock_trigger_svc_cls.return_value.get_trigger_status.return_value = {"rules": []}
            mock_proposal_svc_cls.return_value.get_pending_proposals.return_value = []
            
            data = service.get_dashboard_data()

        assert data["director_profile"] == "director_profile_is_a_string"

    def test_load_evolution_log_syntax_error(self, tmp_path):
        """evolution_log.jsonが破損してJSONの構文エラーが発生した場合、安全にデフォルトの辞書が返されること"""
        evo_log_path = tmp_path / "corrupted_evolution_log.json"
        # 意図的に壊れたJSON文字列を書き込む
        evo_log_path.write_text("{malformed json:}", encoding="utf-8")

        service = EvolutionSyncService(evolution_log_path=evo_log_path)
        data = service._load_evolution_log()

        assert data == {"entries": [], "philosophies": [], "decision_insights": []}


# ─────────────────────────────────────────────
# 追加テスト: 具体的な例外ハンドリングの検証 (T-batch_10609a-bug_hunter-001)
# ─────────────────────────────────────────────

class TestSpecificExceptionHandling:
    """具体的な例外置換後のハンドリング検証"""

    def test_sync_agent_performance_json_decode_error(self, tmp_path):
        """sync_agent_performance で JSONDecodeError が発生した際に警告を出力し、後続の処理が継続すること"""
        branding_dir = tmp_path / "branding"
        branding_dir.mkdir(parents=True, exist_ok=True)
        evo_log_path = branding_dir / "evolution_log.json"
        evo_log_path.write_text(json.dumps({
            "entries": [], "philosophies": [],
        }), encoding="utf-8")

        service = EvolutionSyncService(evolution_log_path=evo_log_path)
        
        # 不正なJSON形式の行を含む reports_path をモック
        reports_dir = tmp_path / "agents" / "orchestration"
        reports_dir.mkdir(parents=True, exist_ok=True)
        reports_path = reports_dir / "flash_reports.jsonl"
        reports_path.write_text("invalid_json_line\n", encoding="utf-8")

        with patch("services.evolution_sync_service.logger.warning") as mock_warning:
            result = service.sync_agent_performance()

        # パースエラーがキャッチされ、処理が中断せずに完了すること
        assert result == {}
        mock_warning.assert_called()
        assert "flash_reports.jsonl 行パースエラー" in mock_warning.call_args_list[0][0][0] or "flash_reports.jsonl 行パースエラー" in mock_warning.call_args_list[1][0][0]

    def test_sync_agent_performance_os_error_on_open(self, tmp_path):
        """sync_agent_performance で reports_path のオープン時に OSError が発生した際、エラーログを出力し空の辞書を返すこと"""
        branding_dir = tmp_path / "branding"
        branding_dir.mkdir(parents=True, exist_ok=True)
        evo_log_path = branding_dir / "evolution_log.json"
        evo_log_path.write_text(json.dumps({
            "entries": [], "philosophies": [],
        }), encoding="utf-8")

        service = EvolutionSyncService(evolution_log_path=evo_log_path)

        reports_dir = tmp_path / "agents" / "orchestration"
        reports_dir.mkdir(parents=True, exist_ok=True)
        reports_path = reports_dir / "flash_reports.jsonl"
        reports_path.write_text("{}", encoding="utf-8")

        with patch("builtins.open", side_effect=OSError("Permission denied")),              patch("services.evolution_sync_service.logger.error") as mock_error:
            result = service.sync_agent_performance()

        assert result == {}
        mock_error.assert_called_once()
        assert "flash_reports.jsonl 読込失敗" in mock_error.call_args[0][0]

    def test_sync_agent_performance_os_error_on_save(self, tmp_path):
        """sync_agent_performance で evolution_log.json 保存時に OSError が発生した際、エラーログを出力し空の辞書を返すこと"""
        branding_dir = tmp_path / "branding"
        branding_dir.mkdir(parents=True, exist_ok=True)
        evo_log_path = branding_dir / "evolution_log.json"
        
        # 正常なデータ行を作成
        reports_dir = tmp_path / "agents" / "orchestration"
        reports_dir.mkdir(parents=True, exist_ok=True)
        reports_path = reports_dir / "flash_reports.jsonl"
        reports_path.write_text(json.dumps({
            "tasks": [{"group": "agent_A", "status": "pass"}]
        }) + "\n", encoding="utf-8")

        service = EvolutionSyncService(evolution_log_path=evo_log_path)

        # 保存時に OSError を発生させる
        with patch.object(service, "_save_evolution_log", side_effect=OSError("Disk full")),              patch("services.evolution_sync_service.logger.error") as mock_error:
            result = service.sync_agent_performance()

        assert result == {}
        mock_error.assert_called_once()
        assert "保存失敗" in mock_error.call_args[0][0]

    def test_safe_execute_traps_specific_errors(self):
        """_safe_execute が新しく指定された具体的な例外型（OSError等）を正しくキャッチしてバイパスすること"""
        service = EvolutionSyncService()

        # OSError
        with patch("services.evolution_sync_service.logger.warning") as mock_warning:
            with service._safe_execute("test_os_error"):
                raise OSError("Simulated OSError")
        mock_warning.assert_called_once()
        assert "Simulated OSError" in mock_warning.call_args[0][0]

        # KeyError
        with patch("services.evolution_sync_service.logger.warning") as mock_warning:
            with service._safe_execute("test_key_error"):
                raise KeyError("Simulated KeyError")
        mock_warning.assert_called_once()
        assert "Simulated KeyError" in mock_warning.call_args[0][0]

    def test_load_evolution_log_generic_exception(self, tmp_path):
        """_load_evolution_log で generic な Exception が発生した際、安全に捕捉してデフォルトの辞書を返すこと"""
        evo_log_path = tmp_path / "generic_error_log.json"
        service = EvolutionSyncService(evolution_log_path=evo_log_path)
        
        with patch("utils.json_safe_io.safe_load_json", side_effect=Exception("Unexpected System Error")), \
             patch("services.evolution_sync_service.logger.warning") as mock_warning:
            result = service._load_evolution_log()
            
        assert result == {"entries": [], "philosophies": [], "decision_insights": []}
        mock_warning.assert_called_once()
        assert "Unexpected System Error" in mock_warning.call_args[0][0]

    def test_sync_agent_performance_various_statuses_and_corruptions(self, tmp_path):
        """sync_agent_performance で status='failed', 'fail', group/status欠損, 空行, パースエラー等が含まれるファイルを処理する検証"""
        branding_dir = tmp_path / "branding"
        branding_dir.mkdir(parents=True, exist_ok=True)
        evo_log_path = branding_dir / "evolution_log.json"
        evo_log_path.write_text(json.dumps({
            "entries": [], "philosophies": [],
        }), encoding="utf-8")

        service = EvolutionSyncService(evolution_log_path=evo_log_path)

        reports_dir = tmp_path / "agents" / "orchestration"
        reports_dir.mkdir(parents=True, exist_ok=True)
        reports_path = reports_dir / "flash_reports.jsonl"
        
        # 1. 空行
        # 2. 正当な 'pass'
        # 3. 'failed'
        # 4. 'fail'
        # 5. group 欠損
        # 6. status 欠損
        # 7. jsonのパースエラー行
        lines = [
            "",
            json.dumps({"tasks": [{"group": "agent_A", "status": "pass"}]}),
            json.dumps({"tasks": [{"group": "agent_A", "status": "failed"}]}),
            json.dumps({"tasks": [{"group": "agent_B", "status": "fail"}]}),
            json.dumps({"tasks": [{"status": "pass"}]}),
            json.dumps({"tasks": [{"group": "agent_A"}]}),
            "{invalid_json}",
        ]
        reports_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        with patch("services.evolution_sync_service.logger.warning") as mock_warning:
            result = service.sync_agent_performance()

        assert result["agent_A"]["passed"] == 1
        assert result["agent_A"]["failed"] == 1
        assert result["agent_A"]["total"] == 2
        assert result["agent_A"]["success_rate"] == 0.5

        assert result["agent_B"]["passed"] == 0
        assert result["agent_B"]["failed"] == 1
        assert result["agent_B"]["total"] == 1
        assert result["agent_B"]["success_rate"] == 0.0

        mock_warning.assert_called()

    def test_sync_agent_performance_returns_empty_when_aggregate_fails(self, tmp_path):
        """_parse_and_aggregate_reports が空の辞書を返した場合、sync_agent_performance も空の辞書を返し保存処理をスキップすること"""
        branding_dir = tmp_path / "branding"
        branding_dir.mkdir(parents=True, exist_ok=True)
        evo_log_path = branding_dir / "evolution_log.json"
        evo_log_path.write_text(json.dumps({
            "entries": [], "philosophies": [],
        }), encoding="utf-8")

        service = EvolutionSyncService(evolution_log_path=evo_log_path)
        
        # 存在するが中身が空または不正な行だけのファイル
        reports_dir = tmp_path / "agents" / "orchestration"
        reports_dir.mkdir(parents=True, exist_ok=True)
        reports_path = reports_dir / "flash_reports.jsonl"
        reports_path.write_text("", encoding="utf-8")

        with patch.object(service, "_save_evolution_log") as mock_save:
            result = service.sync_agent_performance()

        assert result == {}
        mock_save.assert_not_called()
