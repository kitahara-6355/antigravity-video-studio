"""
Sprint 4.2.5: 中程度不足解消テスト (S425-01〜S425-10)

設計書: sprint_425_medium_deficiency_design.md §3
是正対象: M-01〜M-06 (通知キュー / 監督プロファイル / 矛盾検出 / O-12互換 / triggers EP / 却下履歴)

MASTER L1789: Milestone 4.2 Soul自律進化 (D-05)
"""
import json
import hashlib
import pytest
import uuid
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime
from fastapi.testclient import TestClient


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def tmp_evolution_log(tmp_path):
    """テスト用evolution_log.jsonを作成"""
    evo_path = tmp_path / "evolution_log.json"
    evo_path.write_text(json.dumps({
        "entries": [{"type": "test", "timestamp": 1}],
        "philosophies": [
            {"philosophy": "映像は静かに語る", "source": "manual"},
            {"philosophy": "大胆なカットで観客を驚かせる", "source": "manual"},
        ],
        "decision_insights": [],
        "trust_score": 0.0,
        "trust_history": [],
        "pending_proposals": [],
        "trigger_history": [],
        "notifications": [],
        "director_profile": {},
        "rejection_history": [],
        "session_count": 0,
        "rejection_count": 5,
        "approval_count": 0,
    }), encoding="utf-8")
    return evo_path


@pytest.fixture
def tmp_constitution(tmp_path):
    """テスト用constitution.json"""
    const_path = tmp_path / "constitution.json"
    const_path.write_text(json.dumps({
        "content_policy": [],
        "brand_personality": {"keywords": []},
    }), encoding="utf-8")
    return const_path


@pytest.fixture
def trigger_service(tmp_evolution_log, tmp_constitution):
    """EvolutionTriggerService with test paths"""
    from services.evolution_trigger_service import EvolutionTriggerService
    return EvolutionTriggerService(
        evolution_log_path=tmp_evolution_log,
        constitution_path=tmp_constitution,
        cooldown_seconds=0,  # テスト用: cooldown無効
    )


@pytest.fixture
def proposal_service(tmp_evolution_log):
    """PhilosophyProposalService with test path"""
    from services.philosophy_proposal_service import PhilosophyProposalService
    return PhilosophyProposalService(
        evolution_log_path=tmp_evolution_log,
    )


@pytest.fixture
def sync_service(tmp_evolution_log):
    """EvolutionSyncService with test path"""
    from services.evolution_sync_service import EvolutionSyncService
    return EvolutionSyncService(
        evolution_log_path=tmp_evolution_log,
    )


# =============================================================================
# S425-01: test_trigger_notification_emitted (M-01)
# トリガー発火時にevo_log.notificationsにイベント追加
# =============================================================================

class TestS425_01_TriggerNotificationEmitted:
    """M-01: トリガー発火時にevo_log.notificationsにイベント追加"""

    def test_trigger_notification_emitted(self, trigger_service, tmp_evolution_log):
        """S425-01: トリガー発火 → notifications配列にイベント追加"""
        # decision_logger mock → 却下3回でreject_policyトリガー発火
        mock_prefs = {
            "却下パターン": {"色調整": 4},
            "好み（承認数）": {},
            "こだわり（却下傾向）": {"色調整": 3},
            "好み（承認傾向）": {},
            "承認率": 50.0,
            "総判断数": 10,
        }
        mock_dl = MagicMock()
        mock_dl.get_director_preferences.return_value = mock_prefs

        with patch.dict("sys.modules", {"decision_logger": MagicMock(decision_logger=mock_dl)}):
            result = trigger_service.evaluate_triggers()

        assert result["total_fired"] >= 1, "トリガーが発火すべき"

        # evo_logを再読み込みしてnotificationsを確認
        evo_data = json.loads(tmp_evolution_log.read_text(encoding="utf-8"))
        notifications = evo_data.get("notifications", [])
        assert len(notifications) >= 1, "notifications配列にイベントが追加されるべき"


# =============================================================================
# S425-02: test_notification_includes_rule_detail (M-01)
# 通知にrule_id/message/created_at/read=falseが含まれる
# =============================================================================

class TestS425_02_NotificationIncludesRuleDetail:
    """M-01: 通知にrule_id/message/created_at/read=falseが含まれる"""

    def test_notification_includes_rule_detail(self, trigger_service, tmp_evolution_log):
        """S425-02: 通知にrule_id, message, created_at, read=False, detail含む"""
        mock_prefs = {
            "却下パターン": {"テンポ": 5},
            "好み（承認数）": {},
            "こだわり（却下傾向）": {},
            "好み（承認傾向）": {},
            "承認率": 0.0,
            "総判断数": 5,
        }
        mock_dl = MagicMock()
        mock_dl.get_director_preferences.return_value = mock_prefs

        with patch.dict("sys.modules", {"decision_logger": MagicMock(decision_logger=mock_dl)}):
            trigger_service.evaluate_triggers()

        evo_data = json.loads(tmp_evolution_log.read_text(encoding="utf-8"))
        notifications = evo_data.get("notifications", [])
        assert len(notifications) >= 1

        n = notifications[0]
        assert "rule_id" in n, "rule_idフィールド必須"
        assert "message" in n, "messageフィールド必須"
        assert "created_at" in n, "created_atフィールド必須"
        assert n["read"] is False, "read=False (未読)"
        assert isinstance(n.get("message"), str) and len(n["message"]) > 0, "メッセージは空でないstr"


# =============================================================================
# S425-03: test_dashboard_returns_unread_notifications (M-01)
# GET /dashboard → notifications配列に未読通知が含まれる
# =============================================================================

class TestS425_03_DashboardReturnsUnreadNotifications:
    """M-01: ダッシュボードが未読通知を返す"""

    def test_dashboard_returns_unread_notifications(self, tmp_evolution_log, sync_service):
        """S425-03: 前提: evo_logにnotifications1件以上存在 → dashboard返却にnotifications含む"""
        # 事前にnotificationsを1件書き込み
        evo_data = json.loads(tmp_evolution_log.read_text(encoding="utf-8"))
        evo_data["notifications"] = [{
            "id": str(uuid.uuid4()),
            "type": "trigger_fired",
            "rule_id": "reject_policy",
            "message": "テスト通知",
            "created_at": datetime.now().isoformat(),
            "read": False,
        }]
        tmp_evolution_log.write_text(
            json.dumps(evo_data, ensure_ascii=False), encoding="utf-8"
        )

        dashboard = sync_service.get_dashboard_data()
        assert "notifications" in dashboard, "dashboardにnotificationsキー必須"
        assert len(dashboard["notifications"]) >= 1, "未読通知が1件以上"
        assert dashboard["notifications"][0]["read"] is False


# =============================================================================
# S425-04: test_director_profile_generated (M-02)
# evaluate_triggers後（トリガー未発火時も）にdirector_profileが更新される (D-01)
# =============================================================================

class TestS425_04_DirectorProfileGenerated:
    """M-02: evaluate_triggers後にdirector_profileが更新される (D-01: 常時)"""

    def test_director_profile_generated(self, tmp_evolution_log, tmp_constitution):
        """S425-04: トリガー未発火時もdirector_profileが更新される"""
        from services.evolution_trigger_service import EvolutionTriggerService

        # 閾値に満たないデータ → トリガーは発火しない
        evo_data = json.loads(tmp_evolution_log.read_text(encoding="utf-8"))
        evo_data["rejection_count"] = 0
        evo_data["approval_count"] = 0
        evo_data["session_count"] = 0
        tmp_evolution_log.write_text(
            json.dumps(evo_data, ensure_ascii=False), encoding="utf-8"
        )

        service = EvolutionTriggerService(
            evolution_log_path=tmp_evolution_log,
            constitution_path=tmp_constitution,
        )

        result = service.evaluate_triggers()
        assert result["total_fired"] == 0, "トリガー未発火の確認"

        # D-01: トリガー未発火でもdirector_profileが更新
        evo_after = json.loads(tmp_evolution_log.read_text(encoding="utf-8"))
        profile = evo_after.get("director_profile")
        assert profile is not None, "director_profileが存在すべき"
        assert "updated_at" in profile, "updated_atフィールド必須"


# =============================================================================
# S425-05: test_director_profile_has_tendencies (M-02)
# director_profileにrejection_tendencies/approval_tendencies/approval_rateが含まれる
# =============================================================================

class TestS425_05_DirectorProfileHasTendencies:
    """M-02: director_profileに必須フィールドが含まれる"""

    def test_director_profile_has_tendencies(self, trigger_service, tmp_evolution_log):
        """S425-05: director_profileにrejection/approval_tendencies, approval_rate含む"""
        # decision_logger使用不可 → フォールバックパスでもフィールド存在を確認
        trigger_service.evaluate_triggers()

        evo_data = json.loads(tmp_evolution_log.read_text(encoding="utf-8"))
        profile = evo_data.get("director_profile", {})

        assert "rejection_tendencies" in profile, "rejection_tendenciesフィールド必須"
        assert "approval_tendencies" in profile, "approval_tendenciesフィールド必須"
        assert "approval_rate" in profile, "approval_rateフィールド必須"
        assert "total_decisions" in profile, "total_decisionsフィールド必須"
        assert "updated_at" in profile, "updated_atフィールド必須"


# =============================================================================
# S425-06: test_proposal_conflict_detection (M-03)
# _check_conflict_rules()で方向性矛盾を検出
# =============================================================================

class TestS425_06_ProposalConflictDetection:
    """M-03: ルールベース矛盾検出"""

    def test_proposal_conflict_detection(self, proposal_service):
        """S425-06: 正反対キーワードで矛盾検出 → status=pending_review + conflictフィールド"""
        # 既存哲学: "大胆なカットで..." + 新提案: "慎重な..."
        existing = [
            {"philosophy": "大胆なカットで観客を驚かせる", "source": "manual"},
        ]

        # D-02: ルールベースチェックの直接テスト
        result = proposal_service._check_conflict_rules(
            "慎重なアプローチを心がける", existing
        )
        assert result is not None, "方向性の矛盾が検出されるべき"
        assert "矛盾" in result, "矛盾メッセージ"
        assert "大胆" in result or "慎重" in result, "矛盾キーワードが含まれる"

    def test_no_conflict_when_compatible(self, proposal_service):
        """矛盾がない場合はNoneを返す"""
        existing = [
            {"philosophy": "映像は静かに語る", "source": "manual"},
        ]
        result = proposal_service._check_conflict_rules(
            "映像に深みを持たせる演出を追求する", existing
        )
        assert result is None, "矛盾なし → None"


# =============================================================================
# S425-07: test_dashboard_o12_compatible (M-04)
# GET /dashboard → evolution_entries/philosophies/trust_scoreフィールドがO-12期待形式と一致
# =============================================================================

class TestS425_07_DashboardO12Compatible:
    """M-04: O-12互換フィールド"""

    def test_dashboard_o12_compatible(self, sync_service, tmp_evolution_log):
        """S425-07: dashboardにO-12互換フィールド(evolution_entries, philosophies, entries)が存在"""
        dashboard = sync_service.get_dashboard_data()

        # D-03: O-12 UXストーリー実態に合わせた命名
        assert "evolution_entries" in dashboard, "evolution_entriesフィールド必須 (O12-L2-05)"
        assert "philosophies" in dashboard, "philosophiesフィールド必須 (O12-L2-06)"
        assert "entries" in dashboard, "entriesフィールド必須 (O12-L1-10)"
        assert "trust_score" in dashboard, "trust_scoreフィールド必須"

        # 型チェック
        assert isinstance(dashboard["evolution_entries"], int), "evolution_entriesはint"
        assert isinstance(dashboard["philosophies"], list), "philosophiesはlist"
        assert isinstance(dashboard["entries"], list), "entriesはlist"

        # 後方互換: 既存フィールドも存在
        assert "trigger_status" in dashboard
        assert "pending_proposals" in dashboard


# =============================================================================
# S425-08: test_triggers_endpoint_http (M-05)
# GET /evolution/triggers → 200 + rules配列が返る
# =============================================================================

class TestS425_08_TriggersEndpointHttp:
    """M-05: GET /evolution/triggers HTTPテスト"""

    def test_triggers_endpoint_http(self):
        """S425-08: GET /api/evolution/triggers → 200 + rules配列"""
        from main import app
        client = TestClient(app)
        response = client.get("/api/evolution/triggers")
        assert response.status_code == 200, f"200期待, 実際: {response.status_code}"

        data = response.json()
        assert "rules" in data, "rulesキー必須"
        assert isinstance(data["rules"], list), "rulesはlist"

        # rules配列の各要素にrule_id/threshold/current_valueが含まれる
        if data["rules"]:
            rule = data["rules"][0]
            assert "rule_id" in rule, "rule_idフィールド必須"
            assert "threshold" in rule, "thresholdフィールド必須"
            assert "current_value" in rule, "current_valueフィールド必須"


# =============================================================================
# S425-09: test_proposal_avoids_past_rejection (M-06)
# 過去却下履歴存在時、_build_proposal_promptの返却に却下理由テキストが含まれる
# =============================================================================

class TestS425_09_ProposalAvoidsPastRejection:
    """M-06: 過去却下理由がプロンプトに注入される"""

    def test_proposal_avoids_past_rejection(self, proposal_service, tmp_evolution_log):
        """S425-09: rejection_history存在時 → _build_proposal_promptに却下理由含む"""
        # rejection_historyに1件追加
        evo_data = json.loads(tmp_evolution_log.read_text(encoding="utf-8"))
        evo_data["rejection_history"] = [{
            "proposal_id": str(uuid.uuid4()),
            "reason": "テンポが遅すぎる表現は不要",
            "content_hash": "abcdef1234567890",
            "rejected_at": datetime.now().isoformat(),
        }]
        tmp_evolution_log.write_text(
            json.dumps(evo_data, ensure_ascii=False), encoding="utf-8"
        )

        # D-04: 主軸はプロンプトへの過去却下理由注入
        prompt = proposal_service._build_proposal_prompt([])
        assert "テンポが遅すぎる表現は不要" in prompt, "却下理由がプロンプトに注入されるべき"
        assert "過去の却下理由" in prompt, "却下理由セクションのヘッダー"


# =============================================================================
# S425-10: test_rejection_history_recorded (M-06)
# reject_proposal() → rejection_historyにcontent_hash+reason付きで記録される
# =============================================================================

class TestS425_10_RejectionHistoryRecorded:
    """M-06: reject_proposal()でrejection_historyに記録"""

    def test_rejection_history_recorded(self, proposal_service, tmp_evolution_log):
        """S425-10: reject_proposal() → rejection_historyにcontent_hash+reason付きで記録"""
        # pending_proposalを事前セット
        proposal_id = str(uuid.uuid4())
        proposal_content = "テスト哲学提案: 映像に静寂の力を込める"
        evo_data = json.loads(tmp_evolution_log.read_text(encoding="utf-8"))
        evo_data["pending_proposals"] = [{
            "proposal_id": proposal_id,
            "content": proposal_content,
            "source_summary": "テスト",
            "generated_at": datetime.now().isoformat(),
            "status": "pending",
            "user_edit": None,
            "proposal_type": "standard",
        }]
        tmp_evolution_log.write_text(
            json.dumps(evo_data, ensure_ascii=False), encoding="utf-8"
        )

        # reject実行
        result = proposal_service.reject_proposal(
            proposal_id, reason="方向性が合わない"
        )
        assert result is True, "reject成功"

        # rejection_history確認
        evo_after = json.loads(tmp_evolution_log.read_text(encoding="utf-8"))
        history = evo_after.get("rejection_history", [])
        assert len(history) >= 1, "rejection_historyに1件以上"

        entry = history[-1]
        assert entry["proposal_id"] == proposal_id
        assert entry["reason"] == "方向性が合わない"
        assert "content_hash" in entry, "content_hashフィールド必須 (SC-18)"
        assert "rejected_at" in entry, "rejected_atフィールド必須"

        # content_hash検証
        expected_hash = hashlib.sha256(proposal_content.encode()).hexdigest()[:16]
        assert entry["content_hash"] == expected_hash, "content_hashが正しい"
