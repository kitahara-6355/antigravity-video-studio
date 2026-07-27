"""
Sprint 4.2.1: 閾値トリガーエンジン テスト

MASTER L1789: Milestone 4.2 Soul自律進化 (D-05)
設計書: sprint_42_soul_evolution_design.md §3

テスト一覧:
- S421-01: test_trigger_rejection_threshold — 却下3回 → content_policy追記
- S421-02: test_trigger_approval_threshold — 承認5回 → keywords追記
- S421-03: test_trigger_philosophy_integration — philosophies 10件 → integrate
- S421-04: test_trigger_trust_upgrade — 5セッション → trust_score +0.1
- S421-05: test_trigger_max_delta_guard — パラメータ変化 ≤ 0.10
- S421-06: test_trigger_status_api — get_trigger_status() 全ルール返却
- S421-07: test_trigger_no_duplicate — cooldown で重複発火防止
- S421-08: test_trigger_append_only — content_policy/keywords 削除なし

セルフチェック:
- SC-01: 却下閾値=3, 承認閾値=5, 哲学統合閾値=10
- SC-02: content_policy/keywords操作がappendのみ
- SC-06: 既存evolution_logフィールド非破壊
"""
import json
import time
import pytest
import asyncio
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
)

from services.evolution_trigger_service import EvolutionTriggerService, TriggerRule

@pytest.fixture(autouse=True)
def mock_philosophy_proposal_gen():
    """PhilosophyProposalService.generate_integration_proposalをモックして警告を防ぐ"""
    async def dummy_gen(*args, **kwargs):
        mock_prop = MagicMock()
        mock_prop.proposal_id = "mock-integration-proposal-id"
        mock_prop.status = "pending"
        return mock_prop
    with patch("services.philosophy_proposal_service.PhilosophyProposalService.generate_integration_proposal", side_effect=dummy_gen):
        yield


# ---------------------------------------------------------------------------
# Helper: テスト用evo_log / constitution を tmp_path に作成
# ---------------------------------------------------------------------------

def _make_evo_log(tmp_path: Path, **kwargs) -> Path:
    """evolution_log.json をテスト用に作成"""
    data = {
        "entries": [],
        "philosophies": [],
        "decision_insights": [],
        "trust_score": 0.0,
        "trust_history": [],
        "pending_proposals": [],
        "trigger_history": [],
        "session_count": 0,
        "rejection_count": 0,
        "approval_count": 0,
    }
    data.update(kwargs)
    p = tmp_path / "evolution_log.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _make_constitution(tmp_path: Path, **kwargs) -> Path:
    """constitution.json をテスト用に作成"""
    data = {
        "channel_name": "TestChannel",
        "brand_personality": {"keywords": ["既存KW"]},
        "content_policy": ["既存ポリシー"],
    }
    data.update(kwargs)
    p = tmp_path / "constitution.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def _make_svc(tmp_path: Path, **evo_kwargs) -> EvolutionTriggerService:
    """テスト用 EvolutionTriggerService を生成 (cooldown=0で即発火)"""
    evo_path = _make_evo_log(tmp_path, **evo_kwargs)
    const_path = _make_constitution(tmp_path)
    return EvolutionTriggerService(
        evolution_log_path=evo_path,
        constitution_path=const_path,
        cooldown_seconds=0,  # テスト中は cooldown 無効
    )


# ---------------------------------------------------------------------------
# S421-01: test_trigger_rejection_threshold
# ---------------------------------------------------------------------------

class TestTriggerRejectionThreshold:
    """S421-01: 却下パターン3回 → content_policy追記 + evolution_log記録"""

    def test_trigger_rejection_threshold(self, tmp_path):
        """却下カウント≥3 → add_content_policy アクション実行 + evolution_log記録"""
        evo_path = _make_evo_log(tmp_path, rejection_count=3)
        const_path = _make_constitution(tmp_path)
        svc = EvolutionTriggerService(
            evolution_log_path=evo_path,
            constitution_path=const_path,
            cooldown_seconds=0,
        )

        # decision_logger.get_director_preferences() をモック
        mock_prefs = {"却下パターン": {"blur": 3, "zoom": 2}}
        with patch.object(svc, "_count_rejection_patterns", return_value=3):
            with patch(
                "services.evolution_trigger_service.EvolutionTriggerService"
                "._action_add_content_policy",
                wraps=svc._action_add_content_policy,
            ):
                # decision_logger をモック
                mock_dl = MagicMock()
                mock_dl.get_director_preferences.return_value = mock_prefs
                with patch.dict("sys.modules", {"decision_logger": MagicMock(decision_logger=mock_dl)}):
                    result = svc.evaluate_triggers()

        # reject_policy ルールが発火
        fired_ids = [r["rule_id"] for r in result["fired"]]
        assert "reject_policy" in fired_ids, f"fired: {fired_ids}"

        # evolution_log の trigger_history に記録されること (SC-06)
        evo_log = json.loads(evo_path.read_text(encoding="utf-8"))
        assert len(evo_log["trigger_history"]) >= 1
        triggered = [e for e in evo_log["trigger_history"] if e["rule_id"] == "reject_policy"]
        assert len(triggered) >= 1

    def test_rejection_below_threshold_not_fired(self, tmp_path):
        """却下カウント<3 → reject_policy は発火しない"""
        svc = _make_svc(tmp_path, rejection_count=2)
        with patch.object(svc, "_count_rejection_patterns", return_value=2):
            result = svc.evaluate_triggers()
        fired_ids = [r["rule_id"] for r in result["fired"]]
        assert "reject_policy" not in fired_ids


# ---------------------------------------------------------------------------
# S421-02: test_trigger_approval_threshold
# ---------------------------------------------------------------------------

class TestTriggerApprovalThreshold:
    """S421-02: 承認パターン5回 → keywords追記 + evolution_log記録"""

    def test_trigger_approval_threshold(self, tmp_path):
        """承認カウント≥5 → add_keyword アクション実行"""
        evo_path = _make_evo_log(tmp_path, approval_count=5)
        const_path = _make_constitution(tmp_path)
        svc = EvolutionTriggerService(
            evolution_log_path=evo_path,
            constitution_path=const_path,
            cooldown_seconds=0,
        )

        mock_prefs = {"好み（承認数）": {"cinematic": 5, "cool": 2}}
        with patch.object(svc, "_count_approval_patterns", return_value=5):
            mock_dl = MagicMock()
            mock_dl.get_director_preferences.return_value = mock_prefs
            with patch.dict("sys.modules", {"decision_logger": MagicMock(decision_logger=mock_dl)}):
                result = svc.evaluate_triggers()

        fired_ids = [r["rule_id"] for r in result["fired"]]
        assert "approve_keyword" in fired_ids, f"fired: {fired_ids}"

        # constitution.json に keyword が追記されること (SC-02: append only)
        const_data = json.loads(const_path.read_text(encoding="utf-8"))
        assert "cinematic" in const_data["brand_personality"]["keywords"]
        # 既存キーワードが消えていないこと (SC-02)
        assert "既存KW" in const_data["brand_personality"]["keywords"]

    def test_approval_below_threshold_not_fired(self, tmp_path):
        """承認カウント<5 → approve_keyword は発火しない"""
        svc = _make_svc(tmp_path, approval_count=4)
        with patch.object(svc, "_count_approval_patterns", return_value=4):
            result = svc.evaluate_triggers()
        fired_ids = [r["rule_id"] for r in result["fired"]]
        assert "approve_keyword" not in fired_ids


# ---------------------------------------------------------------------------
# S421-03: test_trigger_philosophy_integration
# ---------------------------------------------------------------------------

class TestTriggerPhilosophyIntegration:
    """S421-03: philosophies 10件到達 → integrate アクション実行"""

    def test_trigger_philosophy_integration(self, tmp_path):
        """philosophies 10件 → philosophy_integration ルール発火"""
        philosophies = [{"philosophy": f"哲学{i}"} for i in range(10)]
        svc = _make_svc(tmp_path, philosophies=philosophies)

        result = svc.evaluate_triggers()

        fired_ids = [r["rule_id"] for r in result["fired"]]
        assert "philosophy_integration" in fired_ids, f"fired: {fired_ids}"

        # detail に philosophy_count と integration_triggered が含まれること
        phi_result = next(r for r in result["fired"] if r["rule_id"] == "philosophy_integration")
        assert phi_result["detail"].get("integration_triggered") is True
        assert phi_result["detail"].get("philosophy_count") == 10

    def test_philosophy_below_threshold_not_fired(self, tmp_path):
        """philosophies 9件 → philosophy_integration は発火しない"""
        philosophies = [{"philosophy": f"哲学{i}"} for i in range(9)]
        svc = _make_svc(tmp_path, philosophies=philosophies)
        result = svc.evaluate_triggers()
        fired_ids = [r["rule_id"] for r in result["fired"]]
        assert "philosophy_integration" not in fired_ids


# ---------------------------------------------------------------------------
# S421-04: test_trigger_trust_upgrade
# ---------------------------------------------------------------------------

class TestTriggerTrustUpgrade:
    """S421-04: 5セッション → trust_score +0.1 (max 1.0)"""

    def test_trigger_trust_upgrade(self, tmp_path):
        """session_count=5 → trust_score += 0.1"""
        svc = _make_svc(tmp_path, session_count=5, trust_score=0.0)

        result = svc.evaluate_triggers()

        fired_ids = [r["rule_id"] for r in result["fired"]]
        assert "trust_upgrade" in fired_ids, f"fired: {fired_ids}"

        # evolution_log の trust_score が更新されていること
        evo_log = json.loads(svc._evolution_log_path.read_text(encoding="utf-8"))
        assert abs(evo_log["trust_score"] - 0.1) < 1e-9

    def test_trust_upgrade_detail(self, tmp_path):
        """trust_upgradeアクションのdetailに previous/new/delta が含まれること"""
        svc = _make_svc(tmp_path, session_count=5, trust_score=0.3)
        result = svc.evaluate_triggers()

        trust_result = next(
            (r for r in result["fired"] if r["rule_id"] == "trust_upgrade"), None
        )
        assert trust_result is not None
        detail = trust_result["detail"]
        assert "previous_trust" in detail
        assert "new_trust" in detail
        assert "delta_applied" in detail
        assert abs(detail["previous_trust"] - 0.3) < 1e-9
        assert abs(detail["new_trust"] - 0.4) < 1e-9


# ---------------------------------------------------------------------------
# S421-05: test_trigger_max_delta_guard
# ---------------------------------------------------------------------------

class TestTriggerMaxDeltaGuard:
    """S421-05: パラメータ変化 ≤ 0.10 を超えない (SC-04)"""

    def test_max_delta_guard_trust_upgrade(self, tmp_path):
        """trust_upgrade の delta が max_delta=0.10 を超えないこと"""
        svc = _make_svc(tmp_path, session_count=5, trust_score=0.5)
        # trust_upgrade ルールの max_delta を強制的に大きくしてもガードされること
        svc._rules = [
            TriggerRule("trust_upgrade", "session_count", 5, "upgrade_trust", 0.50),
        ]
        result = svc.evaluate_triggers()

        trust_result = next(
            (r for r in result["fired"] if r["rule_id"] == "trust_upgrade"), None
        )
        assert trust_result is not None
        delta = trust_result["detail"]["delta_applied"]
        # SC-04: 1回の変化量 ≤ 0.10 (コード内で min(max_delta, 0.10) でガード)
        assert delta <= 0.10

    def test_trust_score_max_cap(self, tmp_path):
        """trust_score が 1.0 を超えないこと (SC-04)"""
        svc = _make_svc(tmp_path, session_count=5, trust_score=0.95)
        result = svc.evaluate_triggers()

        evo_log = json.loads(svc._evolution_log_path.read_text(encoding="utf-8"))
        assert evo_log["trust_score"] <= 1.0

    def test_trust_score_already_max(self, tmp_path):
        """trust_score が既に 1.0 の場合、変化しないこと"""
        svc = _make_svc(tmp_path, session_count=5, trust_score=1.0)
        result = svc.evaluate_triggers()

        evo_log = json.loads(svc._evolution_log_path.read_text(encoding="utf-8"))
        assert evo_log["trust_score"] == 1.0


# ---------------------------------------------------------------------------
# S421-06: test_trigger_status_api
# ---------------------------------------------------------------------------

class TestTriggerStatusApi:
    """S421-06: get_trigger_status() → 全ルールの現在値/閾値を返す"""

    def test_trigger_status_api_returns_all_rules(self, tmp_path):
        """get_trigger_status() が全4ルールのステータスを返すこと"""
        svc = _make_svc(tmp_path, session_count=3, trust_score=0.2)
        status = svc.get_trigger_status()

        assert "rules" in status
        rule_ids = [r["rule_id"] for r in status["rules"]]
        # DEFAULT_RULES の4ルールがすべて含まれること
        assert "reject_policy" in rule_ids
        assert "approve_keyword" in rule_ids
        assert "trust_upgrade" in rule_ids
        assert "philosophy_integration" in rule_ids

    def test_trigger_status_contains_threshold_and_current(self, tmp_path):
        """各ルールに threshold / current_value / progress_pct が含まれること"""
        svc = _make_svc(tmp_path, session_count=3)
        status = svc.get_trigger_status()

        for rule_status in status["rules"]:
            assert "threshold" in rule_status, f"threshold missing: {rule_status}"
            assert "current_value" in rule_status
            assert "progress_pct" in rule_status
            assert 0.0 <= rule_status["progress_pct"] <= 1.0

    def test_trigger_status_trust_upgrade_threshold_is_5(self, tmp_path):
        """trust_upgrade ルールの threshold が 5 であること (SC-01)"""
        svc = _make_svc(tmp_path)
        status = svc.get_trigger_status()
        trust_rule = next(r for r in status["rules"] if r["rule_id"] == "trust_upgrade")
        assert trust_rule["threshold"] == 5

    def test_trigger_status_reject_policy_threshold_is_3(self, tmp_path):
        """reject_policy ルールの threshold が 3 であること (SC-01)"""
        svc = _make_svc(tmp_path)
        status = svc.get_trigger_status()
        reject_rule = next(r for r in status["rules"] if r["rule_id"] == "reject_policy")
        assert reject_rule["threshold"] == 3

    def test_trigger_status_philosophy_integration_threshold_is_10(self, tmp_path):
        """philosophy_integration ルールの threshold が 10 であること (SC-01)"""
        svc = _make_svc(tmp_path)
        status = svc.get_trigger_status()
        phi_rule = next(r for r in status["rules"] if r["rule_id"] == "philosophy_integration")
        assert phi_rule["threshold"] == 10


# ---------------------------------------------------------------------------
# S421-07: test_trigger_no_duplicate
# ---------------------------------------------------------------------------

class TestTriggerNoDuplicate:
    """S421-07: cooldown 機構で同一ルールの重複発火を防止"""

    def test_trigger_no_duplicate_within_cooldown(self, tmp_path):
        """cooldown期間内の2回目呼び出しでは同一ルールが発火しないこと"""
        philosophies = [{"philosophy": f"哲学{i}"} for i in range(10)]
        evo_path = _make_evo_log(tmp_path, philosophies=philosophies)
        const_path = _make_constitution(tmp_path)

        # cooldown_seconds を長く設定
        svc = EvolutionTriggerService(
            evolution_log_path=evo_path,
            constitution_path=const_path,
            cooldown_seconds=3600,
        )

        # 1回目: 発火する
        result1 = svc.evaluate_triggers()
        fired1 = [r["rule_id"] for r in result1["fired"]]
        assert "philosophy_integration" in fired1

        # 2回目: cooldown 内なので発火しない
        result2 = svc.evaluate_triggers()
        fired2 = [r["rule_id"] for r in result2["fired"]]
        assert "philosophy_integration" not in fired2
        assert "philosophy_integration" in result2["skipped"]

    def test_trigger_fires_after_cooldown_expired(self, tmp_path):
        """cooldown 期間が過ぎれば再度発火すること"""
        philosophies = [{"philosophy": f"哲学{i}"} for i in range(10)]
        evo_path = _make_evo_log(tmp_path, philosophies=philosophies)
        const_path = _make_constitution(tmp_path)

        # cooldown_seconds=0 で即座に再発火可能
        svc = EvolutionTriggerService(
            evolution_log_path=evo_path,
            constitution_path=const_path,
            cooldown_seconds=0,
        )

        result1 = svc.evaluate_triggers()
        result2 = svc.evaluate_triggers()

        fired1 = [r["rule_id"] for r in result1["fired"]]
        fired2 = [r["rule_id"] for r in result2["fired"]]
        # cooldown=0 なので両回とも発火する
        assert "philosophy_integration" in fired1
        assert "philosophy_integration" in fired2


# ---------------------------------------------------------------------------
# S421-08: test_trigger_append_only
# ---------------------------------------------------------------------------

class TestTriggerAppendOnly:
    """S421-08: content_policy/keywords 操作が append のみ (SC-02)"""

    def test_content_policy_not_deleted(self, tmp_path):
        """content_policy の既存エントリが削除されないこと (SC-02)"""
        evo_path = _make_evo_log(tmp_path, rejection_count=3)
        const_path = _make_constitution(tmp_path)
        svc = EvolutionTriggerService(
            evolution_log_path=evo_path,
            constitution_path=const_path,
            cooldown_seconds=0,
        )

        # 初期の content_policy を確認
        initial_const = json.loads(const_path.read_text(encoding="utf-8"))
        initial_policies = set(initial_const.get("content_policy", []))

        mock_prefs = {"却下パターン": {"blur": 3}}
        with patch.object(svc, "_count_rejection_patterns", return_value=3):
            mock_dl = MagicMock()
            mock_dl.get_director_preferences.return_value = mock_prefs
            with patch.dict("sys.modules", {"decision_logger": MagicMock(decision_logger=mock_dl)}):
                svc.evaluate_triggers()

        # evaluate_triggers 後の constitution を確認
        final_const = json.loads(const_path.read_text(encoding="utf-8"))
        final_policies = set(final_const.get("content_policy", []))

        # 初期ポリシーがすべて残っていること (削除なし)
        assert initial_policies.issubset(final_policies), (
            f"削除されたポリシー: {initial_policies - final_policies}"
        )

    def test_keywords_not_deleted(self, tmp_path):
        """keywords の既存エントリが削除されないこと (SC-02)"""
        evo_path = _make_evo_log(tmp_path, approval_count=5)
        const_path = _make_constitution(tmp_path)
        svc = EvolutionTriggerService(
            evolution_log_path=evo_path,
            constitution_path=const_path,
            cooldown_seconds=0,
        )

        initial_const = json.loads(const_path.read_text(encoding="utf-8"))
        initial_keywords = set(initial_const.get("brand_personality", {}).get("keywords", []))

        mock_prefs = {"好み（承認数）": {"cinematic": 5}}
        with patch.object(svc, "_count_approval_patterns", return_value=5):
            mock_dl = MagicMock()
            mock_dl.get_director_preferences.return_value = mock_prefs
            with patch.dict("sys.modules", {"decision_logger": MagicMock(decision_logger=mock_dl)}):
                svc.evaluate_triggers()

        final_const = json.loads(const_path.read_text(encoding="utf-8"))
        final_keywords = set(final_const.get("brand_personality", {}).get("keywords", []))

        # 初期キーワードがすべて残っていること (削除なし)
        assert initial_keywords.issubset(final_keywords), (
            f"削除されたキーワード: {initial_keywords - final_keywords}"
        )

    def test_existing_policy_not_duplicated(self, tmp_path):
        """同一 content_policy が既に存在する場合、重複追加しないこと"""
        existing_policy = "Avoid 'blur' adjustments; conflicts with director's preferences."
        evo_path = _make_evo_log(tmp_path, rejection_count=3)
        const_path = _make_constitution(tmp_path, content_policy=[existing_policy])
        svc = EvolutionTriggerService(
            evolution_log_path=evo_path,
            constitution_path=const_path,
            cooldown_seconds=0,
        )

        mock_prefs = {"却下パターン": {"blur": 3}}
        with patch.object(svc, "_count_rejection_patterns", return_value=3):
            mock_dl = MagicMock()
            mock_dl.get_director_preferences.return_value = mock_prefs
            with patch.dict("sys.modules", {"decision_logger": MagicMock(decision_logger=mock_dl)}):
                svc.evaluate_triggers()

        final_const = json.loads(const_path.read_text(encoding="utf-8"))
        count = final_const["content_policy"].count(existing_policy)
        assert count == 1, f"重複追加: count={count}"

    def test_evolution_log_existing_fields_preserved(self, tmp_path):
        """evolution_log の既存フィールド (entries/philosophies) が保全されること (SC-06)"""
        existing_entries = [{"type": "smartcut_strategy", "summary": "test"}]
        existing_philosophies = [{"philosophy": "テスト哲学"}]
        svc = _make_svc(
            tmp_path,
            entries=existing_entries,
            philosophies=existing_philosophies,
            session_count=5,
        )

        svc.evaluate_triggers()

        evo_log = json.loads(svc._evolution_log_path.read_text(encoding="utf-8"))
        # 既存エントリが保全されていること
        assert len(evo_log["entries"]) >= 1
        assert evo_log["entries"][0]["type"] == "smartcut_strategy"
        assert len(evo_log["philosophies"]) >= 1
        assert evo_log["philosophies"][0]["philosophy"] == "テスト哲学"


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Edge Cases & Exceptions (M25)
# ---------------------------------------------------------------------------

class TestTriggerEdgeCasesAndExceptions:
    """カバレッジ 100% 達成のためのエッジケースおよび例外検証テスト"""

    def test_unknown_trigger_type(self, tmp_path):
        """未知の trigger_type を評価した場合、現在値は 0 を返すこと"""
        svc = _make_svc(tmp_path)
        svc._rules = [TriggerRule("dummy", "unknown_type", 5, "upgrade_trust", 0.0)]
        result = svc.evaluate_triggers()
        assert "dummy" in result["skipped"]
        status = svc.get_trigger_status()
        dummy_status = next(r for r in status["rules"] if r["rule_id"] == "dummy")
        assert dummy_status["current_value"] == 0
        assert dummy_status["progress_pct"] == 0.0

    def test_count_rejection_patterns_normal(self, tmp_path):
        """decision_logger が正常にインポートでき、却下パターンがある場合に正しく最大値を返すこと"""
        svc = _make_svc(tmp_path)
        mock_prefs = {
            "却下パターン": {"blur": 3, "dark": 5}
        }
        mock_dl = MagicMock()
        mock_dl.get_director_preferences.return_value = mock_prefs
        with patch.dict("sys.modules", {"decision_logger": MagicMock(decision_logger=mock_dl)}):
            val = svc._count_rejection_patterns({})
            assert val == 5

    def test_count_rejection_patterns_exception(self, tmp_path):
        """rejection_patterns のカウント取得で例外が発生した際、evo_log のフォールバック値が使われること"""
        svc = _make_svc(tmp_path, rejection_count=4)
        with patch("decision_logger.decision_logger.get_director_preferences", side_effect=Exception("Mock preference error")):
            val = svc._count_rejection_patterns({"rejection_count": 4})
            assert val == 4

    def test_count_approval_patterns_normal(self, tmp_path):
        """decision_logger が正常にインポートでき、承認パターンがある場合に正しく最大値を返すこと"""
        svc = _make_svc(tmp_path)
        mock_prefs = {
            "好み（承認数）": {"cinematic": 4, "bright": 8}
        }
        mock_dl = MagicMock()
        mock_dl.get_director_preferences.return_value = mock_prefs
        with patch.dict("sys.modules", {"decision_logger": MagicMock(decision_logger=mock_dl)}):
            val = svc._count_approval_patterns({})
            assert val == 8

    def test_count_approval_patterns_exception(self, tmp_path):
        """approval_patterns のカウント取得で例外が発生した際、evo_log のフォールバック値が使われること"""
        svc = _make_svc(tmp_path, approval_count=6)
        with patch("decision_logger.decision_logger.get_director_preferences", side_effect=Exception("Mock preference error")):
            val = svc._count_approval_patterns({"approval_count": 6})
            assert val == 6

    def test_execute_unknown_action(self, tmp_path):
        """未知のアクションを指定したルールが発火した際、エラー情報が detail に記録され、警告が出ること"""
        svc = _make_svc(tmp_path, session_count=5)
        svc._rules = [TriggerRule("unknown_action_rule", "session_count", 5, "invalid_action", 0.0)]
        result = svc.evaluate_triggers()
        fired = next(r for r in result["fired"] if r["rule_id"] == "unknown_action_rule")
        assert "error" in fired["detail"]
        assert "unknown action" in fired["detail"]["error"]

    def test_execute_action_exception_handling(self, tmp_path):
        """アクション実行中に予期せぬ例外が発生した際、evaluate_triggers がクラッシュせず detail に error が入ること"""
        svc = _make_svc(tmp_path, session_count=5)
        with patch.object(svc, "_action_upgrade_trust", side_effect=ValueError("Test trust error")):
            result = svc.evaluate_triggers()
            fired = next(r for r in result["fired"] if r["rule_id"] == "trust_upgrade")
            assert "error" in fired["detail"]
            assert "Test trust error" in fired["detail"]["error"]

    def test_action_add_content_policy_exception(self, tmp_path):
        """add_content_policy アクションで decision_logger からの取得エラー時、例外が発生せずに空で処理されること"""
        svc = _make_svc(tmp_path)
        with patch("decision_logger.decision_logger.get_director_preferences", side_effect=Exception("Mock preference error")):
            detail = svc._action_add_content_policy({})
            assert detail["added_policies"] == []

    def test_action_add_keyword_exception(self, tmp_path):
        """add_keyword アクションで decision_logger からの取得エラー時、例外が発生せずに空で処理されること"""
        svc = _make_svc(tmp_path)
        with patch("decision_logger.decision_logger.get_director_preferences", side_effect=Exception("Mock preference error")):
            detail = svc._action_add_keyword({})
            assert detail["added_keywords"] == []

    def test_constitution_missing_fields_initialization(self, tmp_path):
        """constitution に content_policy や brand_personality がない場合、自動で初期化され、アクションが追加されること"""
        evo_path = _make_evo_log(tmp_path)
        const_path = tmp_path / "empty_constitution.json"
        const_path.write_text("{}", encoding="utf-8")

        svc = EvolutionTriggerService(
            evolution_log_path=evo_path,
            constitution_path=const_path,
            cooldown_seconds=0,
        )
        
        mock_prefs = {
            "却下パターン": {"blur": 3},
            "好み（承認数）": {"cinematic": 5}
        }
        mock_dl = MagicMock()
        mock_dl.get_director_preferences.return_value = mock_prefs
        with patch.object(svc, "_count_rejection_patterns", return_value=3):
            with patch.object(svc, "_count_approval_patterns", return_value=5):
                with patch.dict("sys.modules", {"decision_logger": MagicMock(decision_logger=mock_dl)}):
                    svc.evaluate_triggers()

        const_data = json.loads(const_path.read_text(encoding="utf-8"))
        assert "content_policy" in const_data
        assert any("blur" in p for p in const_data["content_policy"])
        assert "brand_personality" in const_data
        assert "keywords" in const_data["brand_personality"]
        assert "cinematic" in const_data["brand_personality"]["keywords"]

    def test_action_integrate_philosophy_event_loop_running(self, tmp_path):
        """イベントループが実行中の時、非同期タスクとして提案生成がキューイングされること"""
        svc = _make_svc(tmp_path)
        mock_proposal_svc = MagicMock()
        
        async def dummy_coro():
            pass
        coro = dummy_coro()
        mock_proposal_svc.generate_integration_proposal = MagicMock(return_value=coro)
    
        mock_loop = MagicMock()
        mock_loop.is_running.return_value = True
        mock_loop.create_task.return_value = MagicMock(spec=asyncio.Task)
    
        try:
            with patch("asyncio.get_running_loop", return_value=mock_loop):
                with patch("asyncio.get_event_loop", return_value=mock_loop):
                    with patch("services.philosophy_proposal_service.PhilosophyProposalService", return_value=mock_proposal_svc):
                        detail = svc._action_integrate_philosophy({"philosophies": [1, 2, 3]})
                        assert detail["integration_status"] == "async_queued"
                        assert detail["integration_triggered"] is True
        finally:
            coro.close()  # GC警告の防止

    def test_action_integrate_philosophy_exception(self, tmp_path):
        """提案生成で例外が発生した際、status='error' になり、エラー内容が記録されること"""
        svc = _make_svc(tmp_path)
        
        async def dummy_coro_raise():
            raise RuntimeError("Proposal Service Error")
        
        mock_proposal_svc = MagicMock()
        mock_proposal_svc.generate_integration_proposal = MagicMock(return_value=dummy_coro_raise())
    
        with patch("asyncio.get_running_loop", side_effect=RuntimeError("no running loop")):
            with patch("services.philosophy_proposal_service.PhilosophyProposalService", return_value=mock_proposal_svc):
                detail = svc._action_integrate_philosophy({"philosophies": [1, 2, 3]})
                assert detail["integration_status"] == "error"
                assert "Proposal Service Error" in detail["error"]

    def test_trim_trust_history(self, tmp_path):
        """trust_history が 100 件を超えた場合、古い順に削除され最大 100 件に保たれること"""
        trust_history = [{"index": i} for i in range(105)]
        svc = _make_svc(tmp_path, trust_history=trust_history, session_count=5)
        
        svc.evaluate_triggers()
        
        evo_log = svc._load_evolution_log()
        assert len(evo_log["trust_history"]) == 100
        assert evo_log["trust_history"][0]["index"] == 6
        assert evo_log["trust_history"][-1]["reason"] == "session_count_threshold"

    def test_update_director_profile_type_error_and_exception(self, tmp_path):
        """director_profile 更新時に prefs が dict でない等の場合に例外ハンドリングされ、フォールバックすること"""
        svc = _make_svc(tmp_path, session_count=10)
        
        mock_dl = MagicMock()
        mock_dl.get_director_preferences.return_value = None
        with patch.dict("sys.modules", {"decision_logger": MagicMock(decision_logger=mock_dl)}):
            evo_log = {"session_count": 10}
            svc._update_director_profile(evo_log)
            assert evo_log["director_profile"]["total_decisions"] == 10

        mock_dl_err = MagicMock()
        mock_dl_err.get_director_preferences.side_effect = Exception("Logger Crash")
        with patch.dict("sys.modules", {"decision_logger": MagicMock(decision_logger=mock_dl_err)}):
            evo_log = {"session_count": 12}
            svc._update_director_profile(evo_log)
            assert evo_log["director_profile"]["total_decisions"] == 12

    def test_update_director_profile_invalid_element_types(self, tmp_path):
        """prefs の要素が期待する型 (dict/int/float) でない場合、適切に初期値が補完されること"""
        svc = _make_svc(tmp_path)
        mock_prefs = {
            "こだわり（却下傾向）": ["invalid_list"],
            "好み（承認傾向）": "invalid_string",
            "承認率": "invalid_rate",
            "総判断数": "invalid_total"
        }
        mock_dl = MagicMock()
        mock_dl.get_director_preferences.return_value = mock_prefs
        with patch.dict("sys.modules", {"decision_logger": MagicMock(decision_logger=mock_dl)}):
            evo_log = {}
            svc._update_director_profile(evo_log)
            profile = evo_log["director_profile"]
            assert profile["rejection_tendencies"] == {}
            assert profile["approval_tendencies"] == {}
            assert profile["approval_rate"] == 0.0
            assert profile["total_decisions"] == 0

    def test_file_io_exceptions(self, tmp_path):
        """各 json ファイルの読み書きで例外が発生した場合に、適切にログ出力されフォールバックすること"""
        svc = _make_svc(tmp_path)
        
        with patch("utils.json_safe_io.safe_load_json", side_effect=RuntimeError("Read Error")):
            log = svc._load_evolution_log()
            assert log["entries"] == []
            assert log["trust_score"] == 0.0

        with patch("utils.json_safe_io.safe_save_json", side_effect=RuntimeError("Write Error")):
            svc._save_evolution_log({"test": "data"})

        svc._constitution_path.write_text("invalid json", encoding="utf-8")
        const = svc._load_constitution()
        assert const == {}

        with patch("builtins.open", side_effect=IOError("Permission Denied")):
            svc._save_constitution({"test": "data"})

    def test_emit_notification_exception(self, tmp_path):
        """_emit_notification で detail が辞書型でないなど例外が発生した際、フォールバックメッセージが使われること"""
        svc = _make_svc(tmp_path)
        evo_log = {}
        svc._emit_notification("trust_upgrade", None, evo_log) # type: ignore
        assert "notifications" in evo_log
        assert evo_log["notifications"][0]["message"] == "trust_scoreが{new_trust}に昇格しました"

    def test_cooldown_seconds_env_fallback(self, tmp_path):
        """EVOLUTION_COOLDOWN_SECONDS が不正な文字列の場合に 86400 にフォールバックされること"""
        with patch.dict(os.environ, {"EVOLUTION_COOLDOWN_SECONDS": "invalid_value"}):
            # モジュールをリロードして _COOLDOWN_SECONDS を再評価
            import importlib
            import services.evolution_trigger_service
            importlib.reload(services.evolution_trigger_service)
            assert services.evolution_trigger_service._COOLDOWN_SECONDS == 86400
        # テスト後に正常値に戻すためにリロード
        importlib.reload(services.evolution_trigger_service)

    def test_action_upgrade_trust_invalid_score_fallback(self, tmp_path):
        """trust_score が不正な値の場合、0.0 にフォールバックされて trust_upgrade が動作すること"""
        svc = _make_svc(tmp_path, trust_score="invalid_score", session_count=5)
        result = svc.evaluate_triggers()
        fired_ids = [r["rule_id"] for r in result["fired"]]
        assert "trust_upgrade" in fired_ids
        
        evo_log = svc._load_evolution_log()
        assert abs(evo_log["trust_score"] - 0.1) < 1e-9

    def test_evaluate_triggers_save_failure_handling(self, tmp_path):
        """_save_evolution_log が失敗したときでも evaluate_triggers が正常に終了すること"""
        svc = _make_svc(tmp_path, session_count=5)
        with patch("utils.json_safe_io.safe_save_json", side_effect=RuntimeError("Save failed")):
            result = svc.evaluate_triggers()
            assert result["total_fired"] >= 1

    def test_default_paths_initialization(self):
        """引数を省略した際、デフォルトのパスが正しく初期化されること"""
        svc = EvolutionTriggerService()
        assert svc._evolution_log_path.name == "evolution_log.json"
        assert svc._constitution_path.name == "constitution.json"
        assert "branding" in svc._evolution_log_path.parts
        assert "branding" in svc._constitution_path.parts

    def test_emit_notification_unknown_rule_id(self, tmp_path):
        """未知の rule_id が指定された場合、デフォルトのフォーマットで通知メッセージが作成されること"""
        svc = _make_svc(tmp_path)
        evo_log = {}
        svc._emit_notification("custom_rule_id", {"info": "some_info"}, evo_log)
        assert "notifications" in evo_log
        assert evo_log["notifications"][0]["rule_id"] == "custom_rule_id"
        assert evo_log["notifications"][0]["message"] == "トリガー custom_rule_id が発火しました"


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Phase 27: 非同期警告・GCによるタスク消滅回避テスト
# ---------------------------------------------------------------------------

class TestAsyncWarningAndGcPrevention:
    """イベントループ実行時および未実行時の非同期処理における警告や例外を防ぐロジックの検証"""

    def test_action_integrate_philosophy_event_loop_running_real_task_registration(self, tmp_path):
        """イベントループが実行中のとき、作成された Task が強参照セットに追加され、
        完了時に自動で破棄されることを確認する (GCによるタスク消滅および未 awaited 警告の防止検証)
        """
        svc = _make_svc(tmp_path)
        
        # 実際に asyncio.Task が作成される挙動を確認するため、モックループを設定
        mock_loop = MagicMock()
        mock_loop.is_running.return_value = True
        
        # loop.create_task を呼んだときにダミーの Task が返るように設定
        dummy_task = MagicMock(spec=asyncio.Task)
        mock_loop.create_task.return_value = dummy_task

        # PhilosophyProposalServiceのモック
        mock_proposal_svc = MagicMock()
        async def dummy_coro():
            pass
        coro = dummy_coro()
        mock_proposal_svc.generate_integration_proposal = MagicMock(return_value=coro)
        
        try:
            with patch("asyncio.get_running_loop", return_value=mock_loop):
                with patch("services.philosophy_proposal_service.PhilosophyProposalService", return_value=mock_proposal_svc):
                    detail = svc._action_integrate_philosophy({"philosophies": [1, 2, 3]})
                    
                    # 正しくキューイングステータスが返ること
                    assert detail["integration_status"] == "async_queued"
                    
                    # 作成されたタスクへの強参照がセットに保持されていること
                    assert dummy_task in svc._background_tasks
                    
                    # task.add_done_callback が呼ばれていること
                    dummy_task.add_done_callback.assert_called_once()
                    
                    # コールバックを実行し、セットから安全に破棄されること
                    callback = dummy_task.add_done_callback.call_args[0][0]
                    callback(dummy_task)
                    assert dummy_task not in svc._background_tasks
        finally:
            coro.close()

    def test_action_integrate_philosophy_no_loop_fallback(self, tmp_path):
        """イベントループが実行中でないとき、正しく同期フォールバック (asyncio.run) 
        が呼ばれ、かつ警告が発生しないことを検証
        """
        svc = _make_svc(tmp_path)
        
        def fake_run(coro):
            coro.close()
            mock_proposal = MagicMock()
            mock_proposal.proposal_id = "test-fallback-id"
            return mock_proposal
        
        # get_running_loop が例外を投げる (ループが実行中でない) 状態をモック
        with patch("asyncio.get_running_loop", side_effect=RuntimeError("no running event loop")):
            with patch("asyncio.run", side_effect=fake_run) as mock_run:
                detail = svc._action_integrate_philosophy({"philosophies": [1, 2, 3]})
                
                assert detail["integration_status"] == "completed"
                assert detail["proposal_id"] == "test-fallback-id"
                mock_run.assert_called_once()
