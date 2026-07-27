"""
Sprint 4.3.1: M4.2繰越解消テスト — S431-01〜S431-04

設計書: sprint_43_storage_coverage_design.md §4 Sprint 4.3.1
対象:
  m-01: _COOLDOWN_SECONDS 環境変数化 (EVOLUTION_COOLDOWN_SECONDS)
  m-02: trust_history 上限100件トリミング
  m-03: pending_proposals 上限50件管理
  m-04: schema_version マイグレーション ("2.0")
"""
import sys
import os
import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

# backend をパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import pytest


# ===========================================================================
# S431-01: cooldown本番値テスト (m-01)
# ===========================================================================

class TestCooldownProductionValue:
    """S431-01: _COOLDOWN_SECONDS 環境変数 EVOLUTION_COOLDOWN_SECONDS で制御

    検証基準:
    - 環境変数 EVOLUTION_COOLDOWN_SECONDS=86400 でcooldown期間が86400秒になる
    - デフォルト値が86400であること
    - 環境変数未設定時にデフォルト86400が使用されること
    """

    def test_cooldown_production_value(self):
        """環境変数 EVOLUTION_COOLDOWN_SECONDS=86400 で動作確認"""
        with patch.dict(os.environ, {"EVOLUTION_COOLDOWN_SECONDS": "86400"}):
            # モジュールを再インポートして環境変数を反映
            import importlib
            import services.evolution_trigger_service as ets_module
            importlib.reload(ets_module)

            assert ets_module._COOLDOWN_SECONDS == 86400

            # サービスインスタンスでもデフォルトが反映される
            svc = ets_module.EvolutionTriggerService(
                evolution_log_path=Path("dummy_evo.json"),
                constitution_path=Path("dummy_const.json"),
            )
            assert svc._cooldown_seconds == 86400

    def test_cooldown_custom_value(self):
        """環境変数で任意の値を設定可能"""
        with patch.dict(os.environ, {"EVOLUTION_COOLDOWN_SECONDS": "3600"}):
            import importlib
            import services.evolution_trigger_service as ets_module
            importlib.reload(ets_module)

            assert ets_module._COOLDOWN_SECONDS == 3600

    def test_cooldown_default_is_86400(self):
        """環境変数未設定時のデフォルトが86400"""
        env = os.environ.copy()
        env.pop("EVOLUTION_COOLDOWN_SECONDS", None)
        with patch.dict(os.environ, env, clear=True):
            import importlib
            import services.evolution_trigger_service as ets_module
            importlib.reload(ets_module)

            assert ets_module._COOLDOWN_SECONDS == 86400


# ===========================================================================
# S431-02: trust_history トリミングテスト (m-02)
# ===========================================================================

class TestTrustHistoryTrimming:
    """S431-02: trust_history 120件追加後、evaluate_triggers()で100件にトリミング

    検証基準:
    - 120件のtrust_historyがある状態でevaluate_triggers()を実行
    - 実行後、trust_historyが100件にトリミングされる
    - 最新100件が保持される（古い順削除 = SC-05準拠）
    """

    def test_trust_history_trimming(self, tmp_path):
        """trust_history 120件 → evaluate_triggers() → 100件にトリミング"""
        from services.evolution_trigger_service import EvolutionTriggerService

        evo_log_path = tmp_path / "evolution_log.json"
        constitution_path = tmp_path / "constitution.json"

        # 120件のtrust_historyを含むevo_logを作成
        trust_history = [
            {
                "timestamp": f"2026-05-{i:02d}T00:00:00",
                "from": i * 0.01,
                "to": (i + 1) * 0.01,
                "delta": 0.01,
                "reason": f"test_entry_{i}",
            }
            for i in range(120)
        ]

        evo_log = {
            "entries": [],
            "philosophies": [],
            "decision_insights": [],
            "trust_score": 0.5,
            "trust_history": trust_history,
            "pending_proposals": [],
            "trigger_history": [],
            "notifications": [],
            "director_profile": {},
            "rejection_history": [],
            "session_count": 0,
            "rejection_count": 0,
            "approval_count": 0,
        }

        with open(evo_log_path, "w", encoding="utf-8") as f:
            json.dump(evo_log, f, ensure_ascii=False, indent=2)
        with open(constitution_path, "w", encoding="utf-8") as f:
            json.dump({}, f)

        svc = EvolutionTriggerService(
            evolution_log_path=evo_log_path,
            constitution_path=constitution_path,
            cooldown_seconds=86400,
        )

        # evaluate_triggers実行（decision_logger不使用のフォールバック）
        svc.evaluate_triggers()

        # 保存されたevo_logを確認
        with open(evo_log_path, "r", encoding="utf-8") as f:
            saved = json.load(f)

        # 100件にトリミングされていることを確認
        assert len(saved["trust_history"]) == 100

        # 最新100件が保持されている（古い20件が削除）
        assert saved["trust_history"][0]["reason"] == "test_entry_20"
        assert saved["trust_history"][-1]["reason"] == "test_entry_119"


# ===========================================================================
# S431-03: pending_proposals溢れ対策テスト (m-03)
# ===========================================================================

class TestPendingProposalsOverflow:
    """S431-03: pending_proposals 60件状態でgenerate_proposal()→古い順削除→50件維持

    検証基準:
    - 60件のpending_proposalsがある状態
    - generate_proposal()実行
    - 結果: 50件にトリミング後 + 新規1件 = 51件（トリミングは追加前に実行）
      ※設計意図: トリミングで50件に削減 → 追加で51件。次回実行時に再度50件に削減
      ※解決済み(approved/rejected)が優先的に削除される
    """

    @pytest.mark.asyncio
    async def test_pending_proposals_overflow(self, tmp_path):
        """pending_proposals 60件 → generate_proposal() → 50+1件"""
        from services.philosophy_proposal_service import PhilosophyProposalService

        evo_log_path = tmp_path / "evolution_log.json"

        # 60件のpending_proposalsを生成
        # 先頭20件はapproved/rejected (解決済み → 優先削除対象)
        proposals = []
        for i in range(60):
            status = "pending"
            if i < 10:
                status = "approved"
            elif i < 20:
                status = "rejected"
            proposals.append({
                "proposal_id": f"p-{i:03d}",
                "content": f"哲学提案 {i}",
                "source_summary": f"テスト {i}",
                "generated_at": f"2026-05-{(i % 28) + 1:02d}T00:00:00",
                "status": status,
                "user_edit": None,
                "proposal_type": "standard",
            })

        evo_log = {
            "entries": [],
            "philosophies": [{"text": f"phi-{i}"} for i in range(5)],
            "decision_insights": [],
            "pending_proposals": proposals,
        }

        with open(evo_log_path, "w", encoding="utf-8") as f:
            json.dump(evo_log, f, ensure_ascii=False, indent=2)

        svc = PhilosophyProposalService(evolution_log_path=evo_log_path)

        # Gemini呼出しをモック (from import対応: model_registryモジュール側をパッチ)
        mock_content = "テスト哲学: 動的な映像表現を追求する"
        with patch.object(svc, "_call_gemini", new_callable=AsyncMock, return_value=mock_content), \
             patch("model_registry.get_model", return_value="gemini-test"):

            result = await svc.generate_proposal(
                [{"text": "existing philosophy"}]
            )

        assert result is not None

        # 保存されたevo_logを確認
        with open(evo_log_path, "r", encoding="utf-8") as f:
            saved = json.load(f)

        # トリミング(60→50) + 新規追加(+1) = 51件
        assert len(saved["pending_proposals"]) == 51

        # 解決済み(approved/rejected)が優先削除されている
        remaining_statuses = [p["status"] for p in saved["pending_proposals"]]
        # 元の20件の解決済みのうち10件が削除されている
        approved_count = remaining_statuses.count("approved")
        rejected_count = remaining_statuses.count("rejected")
        # 60-50=10件削除。解決済み20件から10件が削除される
        assert approved_count + rejected_count == 10


# ===========================================================================
# S431-04: schema_versionマイグレーション (m-04)
# ===========================================================================

class TestSchemaVersionMigration:
    """S431-04: schema_version未設定のevo_logにmigrate_evolution_log()→"2.0"+全必須フィールド存在

    検証基準:
    - schema_version未設定 → "2.0"に設定される
    - 全必須フィールドが存在する
    - 既存データが非破壊 (§12.3準拠)
    """

    def test_schema_version_migration(self):
        """schema_version未設定 → migrate → "2.0" + 全必須フィールド存在"""
        from utils.evolution_log_migration import (
            migrate_evolution_log,
            CURRENT_SCHEMA_VERSION,
        )

        # schema_version未設定の旧形式evo_log
        old_evo_log = {
            "entries": [{"text": "existing entry"}],
            "philosophies": [{"text": "existing philosophy"}],
        }

        result = migrate_evolution_log(old_evo_log)

        # schema_versionが"2.0"に設定されている
        assert result["schema_version"] == CURRENT_SCHEMA_VERSION
        assert result["schema_version"] == "2.0"

        # 全必須フィールドが存在する
        required_fields = [
            "entries", "philosophies", "decision_insights",
            "trust_score", "trust_history", "pending_proposals",
            "trigger_history", "notifications", "director_profile",
            "rejection_history", "session_count", "rejection_count",
            "approval_count",
        ]
        for field_name in required_fields:
            assert field_name in result, f"必須フィールド '{field_name}' が欠落"

        # 既存データが非破壊 (§12.3)
        assert result["entries"] == [{"text": "existing entry"}]
        assert result["philosophies"] == [{"text": "existing philosophy"}]

    def test_schema_version_already_migrated(self):
        """既にschema_version="2.0"のデータはスキップ"""
        from utils.evolution_log_migration import migrate_evolution_log

        evo_log = {
            "schema_version": "2.0",
            "entries": [],
            "philosophies": [],
        }

        result = migrate_evolution_log(evo_log)

        assert result["schema_version"] == "2.0"
        # setdefaultされるフィールドが追加されないことを確認
        # (既にマイグレーション済みなのでスキップ)
        assert "trust_history" not in result  # スキップされたので追加されない

    def test_schema_version_with_existing_data_preserved(self):
        """マイグレーション時に既存のtrust_historyが保持される"""
        from utils.evolution_log_migration import migrate_evolution_log

        existing_history = [{"from": 0.0, "to": 0.1}]
        evo_log = {
            "entries": [],
            "trust_history": existing_history,
        }

        result = migrate_evolution_log(evo_log)

        assert result["schema_version"] == "2.0"
        assert result["trust_history"] == existing_history  # 非破壊
