"""
hub_status.py (StatusMixin) のユニットテスト。

テスト戦略:
- ファイルI/O: _read_json, _read_jsonl をモック
- 交差依存: check_flash_alive, get_phase_state 等をモック
- 純粋関数: _generate_executive_summary, _generate_roadmap_mermaid,
  _build_hourly_agent_activity は直接テスト
"""
import json
import pytest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.orchestration.hub_reports import ReportsMixin
from agents.orchestration.hub_status import StatusMixin


# --- テスト用のHub擬似クラス ---
class _TestHub(ReportsMixin, StatusMixin):
    """テスト用に両Mixinを結合した擬似Hub"""
    def __init__(self):
        pass
    def check_flash_alive(self):
        return {"alive": True, "status": "running"}
    def diagnose_flash_issues(self):
        return []
    def get_phase_state(self):
        return {"current_phase": 33, "current_milestone": "M33.1",
                "metrics": {"coverage_pct": 82, "test_count": 159}}
    def get_queue_status(self):
        return {"total": 6, "completed": 3, "running": 1}
    def read_messages(self, target="opus", unread_only=True):
        return []
    def check_phase_gate(self, phase=None):
        return {"gate_passed": True}
    def _get_available_modules(self, bl_set=None):
        return ["module_a", "module_b"]
    def _update_subagent_dashboard(self):
        pass


@pytest.fixture
def hub():
    return _TestHub()


# ============================================================
# generate_flash_status
# ============================================================
class TestGenerateFlashStatus:
    """generate_flash_status: Flashステータス全データの計算"""

    @patch("agents.orchestration.hub_status._get_flash_profile")
    @patch("agents.orchestration.hub_status._read_json")
    def test_returns_dict_with_required_fields(self, mock_read, mock_profile, hub):
        mock_profile.return_value = {
            "mode": "weekend", "batch_size": 8,
            "archive_batches": 35, "archive_hours": 6,
            "context_pct_per_batch": 4,
            "context_target_pct": 70, "context_warn_pct": 60,
        }
        mock_read.side_effect = [
            # FLASH_SESSION_PATH
            {"session_started_at": "2026-06-13T00:00:00+00:00",
             "tasks_completed_in_session": 50,
             "batches_in_session": 8,
             "subagents_running": 3,
             "context_pct_history": [3, 4, 5]},
            # TASK_QUEUE_PATH
            {"tasks": [
                {"status": "pass"}, {"status": "pass"},
                {"status": "fail"}, {"status": "running"},
                {"status": "pending"}, {"status": "pending"},
            ]},
            # PHASE_STATE_PATH
            {"current_phase": 33, "current_milestone": "M33.1",
             "metrics": {"coverage_pct": 82, "test_count": 159},
             "blacklisted_modules": []},
        ]
        result = hub.generate_flash_status()
        assert isinstance(result, dict)

    @patch("agents.orchestration.hub_status._get_flash_profile")
    @patch("agents.orchestration.hub_status._read_json")
    def test_handles_empty_session(self, mock_read, mock_profile, hub):
        mock_profile.return_value = {
            "mode": "standard", "batch_size": 6,
            "archive_batches": 30, "archive_hours": 5,
            "context_pct_per_batch": 4,
            "context_target_pct": 70, "context_warn_pct": 60,
        }
        mock_read.side_effect = [{}, {"tasks": []}, {}]
        result = hub.generate_flash_status()
        assert isinstance(result, dict)


# ============================================================
# _generate_executive_summary（純粋関数）
# シグネチャ: (self, task_summaries, failed_tasks, group_summary,
#              passed, failed, success_rate, state, gate, alive)
# ============================================================
class TestGenerateExecutiveSummary:
    """_generate_executive_summary: 全タスク3行総括"""

    def test_generates_summary_text(self, hub):
        task_summaries = [
            {"domain_name": "動画自動編集", "user_desc": "カット自動化",
             "group": "bug_hunter", "commit_msg": "fix cut logic"},
        ]
        failed_tasks = []
        group_summary = {"bug_hunter": {"passed": 3, "failed": 0}}
        state = {"current_phase": 33, "current_milestone": "M33.1"}
        gate = {"gate_passed": True}
        alive = {"alive": True, "status": "running"}
        result = hub._generate_executive_summary(
            task_summaries, failed_tasks, group_summary,
            passed=5, failed=1, success_rate=83.3,
            state=state, gate=gate, alive=alive
        )
        assert isinstance(result, str)
        assert len(result) > 0

    def test_handles_empty_inputs(self, hub):
        result = hub._generate_executive_summary(
            [], [], {},
            passed=0, failed=0, success_rate=0,
            state={}, gate={}, alive={}
        )
        assert isinstance(result, str)


# ============================================================
# _generate_roadmap_mermaid（純粋関数）
# ============================================================
class TestGenerateRoadmapMermaid:
    """_generate_roadmap_mermaid: テキストベースのロードマップ位置図"""

    def test_generates_roadmap_text(self, hub):
        state = {
            "current_phase": 33, "current_milestone": "M33.1",
            "phases_completed": [27, 28, 29, 30, 31, 32],
        }
        task_summaries = [
            {"domain_name": "テスト追加", "group": "test_weaver"},
        ]
        result = hub._generate_roadmap_mermaid(state, task_summaries)
        assert isinstance(result, str)

    def test_handles_empty_state(self, hub):
        result = hub._generate_roadmap_mermaid({}, [])
        assert isinstance(result, str)


# ============================================================
# _build_hourly_agent_activity（純粋関数）
# シグネチャ: (self, now_jst, state, metrics, flash_status,
#              total_tasks_in_batch, passed_tasks, failed_tasks_all,
#              running_tasks, commit_count, dynamic_behaviors)
# ============================================================
class TestBuildHourlyAgentActivity:
    """_build_hourly_agent_activity: サブエージェント活動セクション構築"""

    def test_builds_activity_markdown(self, hub):
        now_jst = datetime.now(timezone(timedelta(hours=9)))
        state = {"current_phase": 33, "current_milestone": "M33.1"}
        metrics = {"coverage_pct": 82, "test_count": 159}
        result = hub._build_hourly_agent_activity(
            now_jst=now_jst,
            state=state,
            metrics=metrics,
            flash_status="running",
            total_tasks_in_batch=6,
            passed_tasks=[{"id": "t1"}, {"id": "t2"}],
            failed_tasks_all=[],
            running_tasks=[],
            commit_count=5,
            dynamic_behaviors=[]
        )
        assert isinstance(result, str)
        assert "サブエージェント活動" in result


# ============================================================
# get_user_intervention_forecast
# ============================================================
class TestGetUserInterventionForecast:
    """get_user_intervention_forecast: ユーザー介入見通し"""

    @patch("agents.orchestration.hub_status._read_json")
    def test_returns_markdown_string(self, mock_read, hub):
        mock_read.return_value = {
            "session_started_at": "2026-06-13T00:00:00+00:00",
            "tasks_completed_in_session": 50,
            "batches_in_session": 8,
        }
        hub._compute_eta_and_next_check = MagicMock(return_value={
            "eta_jst": "15:00",
            "eta_minutes": 30,
            "next_check_jst": "15:30",
            "session_eta_jst": "16:00",
            "session_eta_minutes": 90,
            "recommended_return_jst": "16:00",
            "context_pct": 45,
            "remaining_capacity_tasks": 30,
            "drift_minutes": 0,
        })
        result = hub.get_user_intervention_forecast()
        assert isinstance(result, str)


# ============================================================
# StatusMixin クラス変数
# ============================================================
class TestStatusMixinClassVars:
    """StatusMixin のクラス変数が正しく定義されている"""

    def test_domain_map_exists(self, hub):
        assert hasattr(hub, "_DOMAIN_MAP")
        assert isinstance(hub._DOMAIN_MAP, dict)
        assert len(hub._DOMAIN_MAP) > 5

    def test_group_labels_exists(self, hub):
        assert hasattr(hub, "_GROUP_LABELS")
        assert isinstance(hub._GROUP_LABELS, dict)
        assert "bug_hunter" in hub._GROUP_LABELS
        assert "test_weaver" in hub._GROUP_LABELS

    def test_group_labels_have_4_tuple(self, hub):
        for key, val in hub._GROUP_LABELS.items():
            assert len(val) == 4, f"{key} should have 4-tuple (icon, label, user_effect, mission)"


# ============================================================
# _update_subagent_dashboard
# ============================================================
class TestUpdateSubagentDashboard:
    """_update_subagent_dashboard: pytest環境でのスキップ確認"""

    def test_does_not_raise_in_test_env(self, hub):
        hub._update_subagent_dashboard()
