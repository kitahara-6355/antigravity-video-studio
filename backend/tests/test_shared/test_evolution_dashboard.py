"""
test_evolution_dashboard.py — Sprint 4.2.3 パラメータ自動調整 + 進化ダッシュボード

8テスト (S423-01〜S423-08):
- S423-01: test_trust_score_auto_upgrade
- S423-02: test_trust_score_max_cap
- S423-03: test_trust_score_persistence
- S423-04: test_weight_clamp_with_upgraded_trust
- S423-05: test_dashboard_api
- S423-06: test_dashboard_philosophy_timeline
- S423-07: test_evolution_history
- S423-08: test_full_evolution_cycle

設計書: sprint_42_soul_evolution_design.md §3 Sprint 4.2.3
セルフチェック: SC-04 (trust_score ≤ 1.0, 1回変化幅 ≤ 0.1), SC-06 (既存フィールド非破壊)
"""
import json
import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# プロジェクトルートをパスに追加
backend_dir = Path(__file__).parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def tmp_evolution_log(tmp_path):
    """テスト用evolution_log.jsonのパス"""
    return tmp_path / "evolution_log.json"


@pytest.fixture
def tmp_constitution(tmp_path):
    """テスト用constitution.jsonのパス"""
    constitution = tmp_path / "constitution.json"
    constitution.write_text(json.dumps({
        "content_policy": [],
        "brand_personality": {"keywords": []},
    }, ensure_ascii=False), encoding="utf-8")
    return constitution


@pytest.fixture
def evo_log_with_sessions(tmp_evolution_log):
    """session_count=5 のevolution_log"""
    data = {
        "entries": [],
        "philosophies": [],
        "decision_insights": [],
        "trust_score": 0.0,
        "trust_history": [],
        "pending_proposals": [],
        "trigger_history": [],
        "session_count": 5,
        "rejection_count": 0,
        "approval_count": 0,
    }
    tmp_evolution_log.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return tmp_evolution_log


@pytest.fixture
def trigger_service(evo_log_with_sessions, tmp_constitution):
    """EvolutionTriggerService インスタンス (session_count=5)"""
    from services.evolution_trigger_service import EvolutionTriggerService
    return EvolutionTriggerService(
        evolution_log_path=evo_log_with_sessions,
        constitution_path=tmp_constitution,
        cooldown_seconds=0,  # テストでcooldown無効化
    )


@pytest.fixture
def dashboard_evo_log(tmp_evolution_log):
    """ダッシュボードテスト用の充実したevolution_log"""
    data = {
        "entries": [
            {"type": "smartcut_strategy", "timestamp": 1000, "summary": "test"},
        ],
        "philosophies": [
            {
                "philosophy": "映像には魂が宿る",
                "source": "proposal",
                "proposal_id": "p-001",
                "approved_at": "2026-05-01T10:00:00",
                "original_content": "映像には魂が宿る",
                "was_edited": False,
            },
            {
                "philosophy": "静寂は最高の演出である",
                "source": "proposal",
                "proposal_id": "p-002",
                "approved_at": "2026-05-02T10:00:00",
                "original_content": "静寂は最高の演出である",
                "was_edited": False,
            },
        ],
        "decision_insights": [],
        "trust_score": 0.3,
        "trust_history": [
            {"from": 0.0, "to": 0.1, "delta": 0.1, "reason": "session_count_threshold",
             "timestamp": "2026-05-01T00:00:00"},
            {"from": 0.1, "to": 0.2, "delta": 0.1, "reason": "session_count_threshold",
             "timestamp": "2026-05-05T00:00:00"},
            {"from": 0.2, "to": 0.3, "delta": 0.1, "reason": "session_count_threshold",
             "timestamp": "2026-05-10T00:00:00"},
        ],
        "pending_proposals": [
            {
                "proposal_id": "p-pending-001",
                "content": "新しい哲学提案テスト",
                "source_summary": "テスト用",
                "generated_at": "2026-05-11T12:00:00",
                "status": "pending",
                "user_edit": None,
            },
        ],
        "trigger_history": [
            {
                "rule_id": "trust_upgrade",
                "fired_at": 1000.0,
                "iso_time": "2026-05-01T00:00:00",
                "detail": {"previous_trust": 0.0, "new_trust": 0.1, "delta_applied": 0.1},
            },
            {
                "rule_id": "trust_upgrade",
                "fired_at": 2000.0,
                "iso_time": "2026-05-05T00:00:00",
                "detail": {"previous_trust": 0.1, "new_trust": 0.2, "delta_applied": 0.1},
            },
        ],
        "session_count": 15,
        "rejection_count": 0,
        "approval_count": 0,
    }
    tmp_evolution_log.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return tmp_evolution_log


# ============================================================
# S423-01: test_trust_score_auto_upgrade
# ============================================================

class TestTrustScoreAutoUpgrade:
    """S423-01: 5セッション完了ごとにtrust_score +0.1"""

    def test_trust_score_auto_upgrade(self, trigger_service, evo_log_with_sessions):
        """S423-01: session_count=5 → evaluate_triggers → trust_score +0.1"""
        result = trigger_service.evaluate_triggers()

        # trust_upgrade が発火したことを確認
        fired_ids = [r["rule_id"] for r in result["fired"]]
        assert "trust_upgrade" in fired_ids, (
            f"trust_upgrade should fire with session_count=5, fired={fired_ids}"
        )

        # evolution_log を再読み込みして trust_score を確認
        with open(evo_log_with_sessions, "r", encoding="utf-8") as f:
            evo_log = json.load(f)

        # SC-04: trust_score = 0.0 + 0.1 = 0.1
        assert evo_log["trust_score"] == pytest.approx(0.1, abs=1e-9), (
            f"trust_score should be 0.1 after upgrade, got {evo_log['trust_score']}"
        )

        # trust_history に記録されていること
        assert len(evo_log["trust_history"]) >= 1
        latest = evo_log["trust_history"][-1]
        assert latest["delta"] == pytest.approx(0.1, abs=1e-9)
        assert latest["from"] == pytest.approx(0.0, abs=1e-9)
        assert latest["to"] == pytest.approx(0.1, abs=1e-9)


# ============================================================
# S423-02: test_trust_score_max_cap
# ============================================================

class TestTrustScoreMaxCap:
    """S423-02: trust_score ≤ 1.0"""

    def test_trust_score_max_cap(self, tmp_path):
        """S423-02: trust_score=0.95 で +0.1 → 1.0 (not 1.05)"""
        from services.evolution_trigger_service import EvolutionTriggerService

        evo_log_path = tmp_path / "evolution_log.json"
        constitution_path = tmp_path / "constitution.json"
        constitution_path.write_text(json.dumps({}), encoding="utf-8")

        # trust_score = 0.95, session_count = 5
        data = {
            "entries": [],
            "philosophies": [],
            "trust_score": 0.95,
            "trust_history": [],
            "trigger_history": [],
            "session_count": 5,
            "rejection_count": 0,
            "approval_count": 0,
            "pending_proposals": [],
        }
        evo_log_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        service = EvolutionTriggerService(
            evolution_log_path=evo_log_path,
            constitution_path=constitution_path,
            cooldown_seconds=0,
        )

        service.evaluate_triggers()

        with open(evo_log_path, "r", encoding="utf-8") as f:
            result = json.load(f)

        # SC-04: trust_score ≤ 1.0
        assert result["trust_score"] <= 1.0, (
            f"trust_score must not exceed 1.0, got {result['trust_score']}"
        )
        assert result["trust_score"] == pytest.approx(1.0, abs=1e-9), (
            f"trust_score should be capped at 1.0, got {result['trust_score']}"
        )


# ============================================================
# S423-03: test_trust_score_persistence
# ============================================================

class TestTrustScorePersistence:
    """S423-03: trust_scoreがevolution_log.jsonに永続化"""

    def test_trust_score_persistence(self, trigger_service, evo_log_with_sessions):
        """S423-03: trust昇格後、ファイル再読み込みで永続化確認"""
        # 1回目: trust昇格
        trigger_service.evaluate_triggers()

        # ファイル再読み込み (新しいサービスインスタンス)
        from services.evolution_trigger_service import EvolutionTriggerService
        service2 = EvolutionTriggerService(
            evolution_log_path=evo_log_with_sessions,
            cooldown_seconds=0,
        )
        status = service2.get_trigger_status()

        # trust_upgradeルールの状態から間接的に永続化確認
        with open(evo_log_with_sessions, "r", encoding="utf-8") as f:
            persisted = json.load(f)

        assert persisted["trust_score"] == pytest.approx(0.1, abs=1e-9), (
            f"trust_score should persist to file, got {persisted['trust_score']}"
        )
        assert len(persisted["trust_history"]) >= 1, (
            "trust_history should persist"
        )
        assert "last_updated" in persisted, (
            "last_updated timestamp should be present"
        )


# ============================================================
# S423-04: test_weight_clamp_with_upgraded_trust
# ============================================================

class TestWeightClampWithUpgradedTrust:
    """S423-04: trust=0.3 → _clamp_weight影響値計算"""

    def test_weight_clamp_with_upgraded_trust(self):
        """S423-04: trust=0.3 → max_deviation=0.066 → weight制約確認

        _clamp_weight計算ロジック (smart_cut_plugin.py L268-276):
        max_deviation = trust_score * 0.22
        return max(1.0 - max_deviation, min(1.0 + max_deviation, raw_weight))

        trust=0.3 → max_deviation = 0.066
        - raw=1.5 → min(1.066, max(0.934, 1.5)) = 1.066
        - raw=0.5 → min(1.066, max(0.934, 0.5)) = 0.934
        - raw=1.0 → min(1.066, max(0.934, 1.0)) = 1.0 (中央値は不変)
        """
        from plugins.smart_cut_plugin import SmartCutPlugin

        trust = 0.3
        max_dev = trust * 0.22  # = 0.066

        # ケース1: raw=1.5 (上限に制約)
        result_high = SmartCutPlugin._clamp_weight(1.5, trust)
        expected_high = 1.0 + max_dev  # = 1.066
        assert result_high == pytest.approx(expected_high, abs=1e-9), (
            f"raw=1.5, trust=0.3 → expected {expected_high}, got {result_high}"
        )

        # ケース2: raw=0.5 (下限に制約)
        result_low = SmartCutPlugin._clamp_weight(0.5, trust)
        expected_low = 1.0 - max_dev  # = 0.934
        assert result_low == pytest.approx(expected_low, abs=1e-9), (
            f"raw=0.5, trust=0.3 → expected {expected_low}, got {result_low}"
        )

        # ケース3: raw=1.0 (中央値は不変)
        result_mid = SmartCutPlugin._clamp_weight(1.0, trust)
        assert result_mid == pytest.approx(1.0, abs=1e-9), (
            f"raw=1.0, trust=0.3 → expected 1.0, got {result_mid}"
        )

        # SC-04: 変化量が ±max_dev 以内であることの検証
        assert abs(result_high - 1.0) <= max_dev + 1e-9
        assert abs(result_low - 1.0) <= max_dev + 1e-9


# ============================================================
# S423-05: test_dashboard_api
# ============================================================

class TestDashboardApi:
    """S423-05: GET /dashboard → trigger_status+proposals+trust"""

    def test_dashboard_api(self, dashboard_evo_log, tmp_constitution):
        """S423-05: GET /api/evolution/dashboard → 200 + 必須フィールド"""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI

        app = FastAPI()

        # trinity routerをインポートしてマウント
        from routers.trinity import router
        app.include_router(router)

        client = TestClient(app)

        # evolution_log_path / constitution_path をモックで注入
        with patch(
            "services.evolution_sync_service.EvolutionSyncService.__init__",
            lambda self, evolution_log_path=None: (
                setattr(self, "_evolution_log_path", dashboard_evo_log) or None
            ),
        ):
            response = client.get("/api/evolution/dashboard")

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )

        data = response.json()

        # 必須フィールド存在確認
        assert "trigger_status" in data, "trigger_status missing"
        assert "pending_proposals" in data, "pending_proposals missing"
        assert "trust_score" in data, "trust_score missing"
        assert "trust_history" in data, "trust_history missing"
        assert "philosophy_timeline" in data, "philosophy_timeline missing"
        assert "trigger_history" in data, "trigger_history missing"
        assert "evolution_entries_count" in data, "evolution_entries_count missing"
        assert "philosophies_count" in data, "philosophies_count missing"

        # 値の妥当性
        assert data["trust_score"] == pytest.approx(0.3, abs=1e-9)
        assert data["philosophies_count"] == 2
        assert data["evolution_entries_count"] == 1
        assert len(data["pending_proposals"]) == 1


# ============================================================
# S423-06: test_dashboard_philosophy_timeline
# ============================================================

class TestDashboardPhilosophyTimeline:
    """S423-06: 哲学タイムライン含む"""

    def test_dashboard_philosophy_timeline(self, dashboard_evo_log):
        """S423-06: ダッシュボードに哲学タイムラインが含まれる"""
        from services.evolution_sync_service import EvolutionSyncService

        service = EvolutionSyncService(evolution_log_path=dashboard_evo_log)
        dashboard = service.get_dashboard_data()

        assert "philosophy_timeline" in dashboard, (
            "philosophy_timeline missing from dashboard"
        )

        timeline = dashboard["philosophy_timeline"]
        assert len(timeline) == 2, (
            f"Expected 2 philosophy entries, got {len(timeline)}"
        )

        # タイムラインの内容確認
        assert timeline[0]["philosophy"] == "映像には魂が宿る"
        assert timeline[1]["philosophy"] == "静寂は最高の演出である"

        # approved_at が含まれること (時系列表示に必要)
        for entry in timeline:
            assert "approved_at" in entry, "approved_at missing from timeline entry"


# ============================================================
# S423-07: test_evolution_history
# ============================================================

class TestEvolutionHistory:
    """S423-07: トリガー発火履歴をevolution_logから取得"""

    def test_evolution_history(self, dashboard_evo_log):
        """S423-07: ダッシュボードにトリガー発火履歴が含まれる"""
        from services.evolution_sync_service import EvolutionSyncService

        service = EvolutionSyncService(evolution_log_path=dashboard_evo_log)
        dashboard = service.get_dashboard_data()

        assert "trigger_history" in dashboard, (
            "trigger_history missing from dashboard"
        )

        history = dashboard["trigger_history"]
        assert len(history) == 2, (
            f"Expected 2 trigger history entries, got {len(history)}"
        )

        # trigger_history の内容確認
        assert history[0]["rule_id"] == "trust_upgrade"
        assert "detail" in history[0]
        assert history[0]["detail"]["previous_trust"] == 0.0
        assert history[0]["detail"]["new_trust"] == 0.1


# ============================================================
# S423-08: test_full_evolution_cycle
# ============================================================

class TestFullEvolutionCycle:
    """S423-08: 全サイクルE2E検証"""

    def test_full_evolution_cycle(self, tmp_path):
        """S423-08: session→trigger→trust昇格→_clamp_weight→ダッシュボード E2E

        サイクル:
        1. session_count=5 の evolution_log を準備
        2. evaluate_triggers() → trust_score 0.0 → 0.1
        3. _clamp_weight() で trust=0.1 の制約を検証
        4. ダッシュボードで trust_score + trust_history が正しく返される
        """
        from services.evolution_trigger_service import EvolutionTriggerService
        from services.evolution_sync_service import EvolutionSyncService
        from plugins.smart_cut_plugin import SmartCutPlugin

        evo_log_path = tmp_path / "evolution_log.json"
        constitution_path = tmp_path / "constitution.json"
        constitution_path.write_text(json.dumps({}), encoding="utf-8")

        # Step 1: session_count=5 で初期化
        initial_data = {
            "entries": [],
            "philosophies": [
                {
                    "philosophy": "テスト哲学",
                    "source": "manual",
                    "approved_at": "2026-05-11T00:00:00",
                }
            ],
            "decision_insights": [],
            "trust_score": 0.0,
            "trust_history": [],
            "pending_proposals": [],
            "trigger_history": [],
            "session_count": 5,
            "rejection_count": 0,
            "approval_count": 0,
        }
        evo_log_path.write_text(
            json.dumps(initial_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Step 2: evaluate_triggers → trust昇格
        trigger_svc = EvolutionTriggerService(
            evolution_log_path=evo_log_path,
            constitution_path=constitution_path,
            cooldown_seconds=0,
        )
        trigger_result = trigger_svc.evaluate_triggers()

        fired_ids = [r["rule_id"] for r in trigger_result["fired"]]
        assert "trust_upgrade" in fired_ids, (
            "trust_upgrade should fire in E2E cycle"
        )

        # Step 3: trust=0.1 での _clamp_weight 検証
        new_trust = 0.1
        max_dev = new_trust * 0.22  # = 0.022
        result = SmartCutPlugin._clamp_weight(1.5, new_trust)
        expected = 1.0 + max_dev  # = 1.022
        assert result == pytest.approx(expected, abs=1e-9), (
            f"_clamp_weight(1.5, 0.1) → expected {expected}, got {result}"
        )

        # Step 4: ダッシュボードで統合検証
        sync_svc = EvolutionSyncService(evolution_log_path=evo_log_path)
        dashboard = sync_svc.get_dashboard_data()

        # trust_score が 0.1 に昇格
        assert dashboard["trust_score"] == pytest.approx(0.1, abs=1e-9), (
            f"Dashboard trust_score should be 0.1, got {dashboard['trust_score']}"
        )

        # trust_history に1件記録
        assert len(dashboard["trust_history"]) >= 1, (
            "trust_history should have at least 1 entry"
        )

        # philosophy_timeline に1件
        assert dashboard["philosophies_count"] == 1, (
            f"philosophies_count should be 1, got {dashboard['philosophies_count']}"
        )

        # trigger_history にtrust_upgradeが記録
        assert len(dashboard["trigger_history"]) >= 1, (
            "trigger_history should have at least 1 entry from trust_upgrade"
        )

        # SC-06: 既存フィールド (entries, philosophies) が破壊されていない
        with open(evo_log_path, "r", encoding="utf-8") as f:
            final_log = json.load(f)

        assert "entries" in final_log, "SC-06: entries field must exist"
        assert "philosophies" in final_log, "SC-06: philosophies field must exist"
        assert len(final_log["philosophies"]) == 1, (
            "SC-06: philosophies should not be destroyed"
        )
