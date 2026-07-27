import json
import pytest
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from services.evolution_sync_service import EvolutionSyncService


class TestEvolutionSyncPerformance:
    """EvolutionSyncService.sync_agent_performance の検証"""

    def test_sync_agent_performance_basic(self, tmp_path):
        """flash_reports.jsonl から各エージェントの成功率を正しく集計して evolution_log.json に同期する"""
        # テスト用 evolution_log.json の作成 (branding ディレクトリを作成)
        branding_dir = tmp_path / "branding"
        branding_dir.mkdir(parents=True, exist_ok=True)
        evo_log_path = branding_dir / "evolution_log.json"
        evo_log_path.write_text(json.dumps({
            "entries": [],
            "philosophies": [],
            "decision_insights": []
        }), encoding="utf-8")

        # テスト用 flash_reports.jsonl の作成 (agents/orchestration ディレクトリを作成)
        orchestration_dir = tmp_path / "agents" / "orchestration"
        orchestration_dir.mkdir(parents=True, exist_ok=True)
        reports_path = orchestration_dir / "flash_reports.jsonl"

        # ダミーのレポートデータ書き込み (JSON Lines)
        # 1バッチ目: test_weaver (2 pass, 1 fail), bug_hunter (1 pass)
        # 2バッチ目: test_weaver (1 pass), bug_hunter (1 fail), refactor (2 pass)
        reports_path.write_text(
            json.dumps({
                "batch_id": "batch_001",
                "tasks": [
                    {"group": "test_weaver", "status": "pass"},
                    {"group": "test_weaver", "status": "fail"},
                    {"group": "test_weaver", "status": "pass"},
                    {"group": "bug_hunter", "status": "pass"}
                ]
            }) + "\n" +
            json.dumps({
                "batch_id": "batch_002",
                "tasks": [
                    {"group": "test_weaver", "status": "pass"},
                    {"group": "bug_hunter", "status": "failed"},
                    {"group": "refactor", "status": "pass"},
                    {"group": "refactor", "status": "pass"}
                ]
            }) + "\n",
            encoding="utf-8"
        )

        service = EvolutionSyncService(evolution_log_path=evo_log_path)
        perf = service.sync_agent_performance()

        # 集計結果の確認
        assert perf["test_weaver"]["passed"] == 3
        assert perf["test_weaver"]["failed"] == 1
        assert perf["test_weaver"]["total"] == 4
        assert perf["test_weaver"]["success_rate"] == 0.75

        assert perf["bug_hunter"]["passed"] == 1
        assert perf["bug_hunter"]["failed"] == 1
        assert perf["bug_hunter"]["total"] == 2
        assert perf["bug_hunter"]["success_rate"] == 0.5

        assert perf["refactor"]["passed"] == 2
        assert perf["refactor"]["failed"] == 0
        assert perf["refactor"]["total"] == 2
        assert perf["refactor"]["success_rate"] == 1.0

        # evolution_log.json に書き込まれているか確認
        with open(evo_log_path, "r", encoding="utf-8") as f:
            evo_data = json.load(f)
        
        assert "agent_performance" in evo_data
        saved_perf = evo_data["agent_performance"]
        assert saved_perf["test_weaver"]["success_rate"] == 0.75
        assert saved_perf["bug_hunter"]["success_rate"] == 0.5
        assert saved_perf["refactor"]["success_rate"] == 1.0

    def test_sync_agent_performance_no_file(self, tmp_path):
        """flash_reports.jsonl が見つからない場合は空の辞書を返す"""
        branding_dir = tmp_path / "branding"
        branding_dir.mkdir(parents=True, exist_ok=True)
        evo_log_path = branding_dir / "evolution_log.json"
        evo_log_path.write_text(json.dumps({}), encoding="utf-8")

        service = EvolutionSyncService(evolution_log_path=evo_log_path)
        # reports_path は存在しないため空の辞書が返るはず
        perf = service.sync_agent_performance()
        assert perf == {}
