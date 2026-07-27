"""
hub_reports.py (ReportsMixin) のユニットテスト。

テスト戦略:
- ファイルI/O: _read_json, _read_jsonl, _append_jsonl をモック
- subprocess: git操作は subprocess.run をモック
- 交差依存: check_flash_alive, _update_subagent_dashboard 等をモック
- 純粋関数: _parse_git_log_stat は直接テスト
"""
import json
import pytest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, mock_open

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.orchestration.hub_reports import ReportsMixin
from agents.orchestration.hub_status import StatusMixin


# --- テスト用のHub擬似クラス（両Mixinを継承） ---
class _TestHub(ReportsMixin, StatusMixin):
    """テスト用に両Mixinを結合した擬似Hub"""
    def __init__(self):
        pass
    def check_flash_alive(self):
        return {"alive": True, "status": "running"}
    def diagnose_flash_issues(self):
        return []
    def get_phase_state(self):
        return {"current_phase": 33, "current_milestone": "M33.1"}
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
# get_reports_since
# ============================================================
class TestGetReportsSince:
    """get_reports_since: 指定時刻以降のレポートフィルタリング"""

    @patch("agents.orchestration.hub_reports._read_jsonl")
    def test_returns_reports_after_timestamp(self, mock_read, hub):
        mock_read.return_value = [
            {"timestamp": "2026-06-10T00:00:00+00:00", "batch_id": "old"},
            {"timestamp": "2026-06-12T10:00:00+00:00", "batch_id": "new1"},
            {"timestamp": "2026-06-13T05:00:00+00:00", "batch_id": "new2"},
        ]
        result = hub.get_reports_since("2026-06-12T00:00:00+00:00")
        assert len(result) == 2
        assert result[0]["batch_id"] == "new1"
        assert result[1]["batch_id"] == "new2"

    @patch("agents.orchestration.hub_reports._read_jsonl")
    def test_returns_empty_for_invalid_since(self, mock_read, hub):
        result = hub.get_reports_since("")
        assert result == []
        mock_read.assert_not_called()

    @patch("agents.orchestration.hub_reports._read_jsonl")
    def test_returns_empty_when_no_matches(self, mock_read, hub):
        mock_read.return_value = [
            {"timestamp": "2026-06-01T00:00:00+00:00", "batch_id": "old"},
        ]
        result = hub.get_reports_since("2026-06-12T00:00:00+00:00")
        assert result == []

    @patch("agents.orchestration.hub_reports._read_jsonl")
    def test_skips_records_without_timestamp(self, mock_read, hub):
        mock_read.return_value = [
            {"batch_id": "no_ts"},
            {"timestamp": "2026-06-13T05:00:00+00:00", "batch_id": "with_ts"},
        ]
        result = hub.get_reports_since("2026-06-12T00:00:00+00:00")
        assert len(result) == 1


# ============================================================
# _generate_batch_report_file
# ============================================================
class TestGenerateBatchReportFile:
    """_generate_batch_report_file: バッチ完了レポートのMD生成"""

    @patch("agents.orchestration.hub_reports._read_json")
    def test_creates_report_file(self, mock_read_json, hub, tmp_path):
        mock_read_json.return_value = {"recent_errors": []}
        with patch("agents.orchestration.hub_reports.INBOX_DIR", tmp_path):
            state = {
                "current_phase": 33, "current_milestone": "M33.1",
                "flash_batches_completed": 10,
                "metrics": {"coverage_pct": 82, "test_count": 159},
                "blacklisted_modules": [],
            }
            results = {"passed": 5, "failed": 1, "total": 6}
            filepath = hub._generate_batch_report_file("batch_abc", results, state)
            assert filepath.exists()
            content = filepath.read_text(encoding="utf-8")
            assert "batch_abc" in content
            assert "5成功" in content
            assert "1失敗" in content

    @patch("agents.orchestration.hub_reports._read_json")
    def test_includes_error_details_on_failure(self, mock_read_json, hub, tmp_path):
        mock_read_json.return_value = {
            "recent_errors": [
                {"module": "test_api.py", "error": "ImportError", "timestamp": "2026-06-13"},
            ]
        }
        with patch("agents.orchestration.hub_reports.INBOX_DIR", tmp_path):
            state = {"current_phase": 33, "current_milestone": "M33.1",
                     "flash_batches_completed": 5, "metrics": {},
                     "blacklisted_modules": []}
            results = {"passed": 4, "failed": 2, "total": 6}
            filepath = hub._generate_batch_report_file("batch_err", results, state)
            content = filepath.read_text(encoding="utf-8")
            assert "失敗詳細" in content
            assert "ImportError" in content

    @patch("agents.orchestration.hub_reports._read_json")
    def test_includes_blacklist_section(self, mock_read_json, hub, tmp_path):
        mock_read_json.return_value = {"recent_errors": []}
        with patch("agents.orchestration.hub_reports.INBOX_DIR", tmp_path):
            state = {"current_phase": 33, "current_milestone": "M33.1",
                     "flash_batches_completed": 5, "metrics": {},
                     "blacklisted_modules": ["broken_module"]}
            results = {"passed": 6, "failed": 0, "total": 6}
            filepath = hub._generate_batch_report_file("batch_bl", results, state)
            content = filepath.read_text(encoding="utf-8")
            assert "ブラックリスト" in content
            assert "broken_module" in content


# ============================================================
# _emit_harness_audit_log
# ============================================================
class TestEmitHarnessAuditLog:
    """_emit_harness_audit_log: 監査ログ(JSONL)追記"""

    @patch("agents.orchestration.hub_reports._append_jsonl")
    def test_appends_audit_record(self, mock_append, hub):
        results = {"passed": 5, "failed": 1}
        report = {"design_stock_tasks": 2, "git_diff_summary": {"files_changed": 3}}
        hub._emit_harness_audit_log("b1", results, report)
        mock_append.assert_called_once()
        args = mock_append.call_args
        record = args[0][1]
        assert record["event"] == "PostBatchComplete"
        assert record["session_id"] == "b1"
        assert record["batch_results"]["passed"] == 5

    @patch("agents.orchestration.hub_reports._append_jsonl")
    def test_handles_empty_report(self, mock_append, hub):
        hub._emit_harness_audit_log("b2", {"passed": 0, "failed": 0}, {})
        mock_append.assert_called_once()
        record = mock_append.call_args[0][1]
        assert record["batch_results"]["total"] == 0


# ============================================================
# _parse_git_log_stat（純粋関数テスト）
# format: '%h %ci %s' — 例: "a44d528 2026-05-21 08:30:15 +0900 fix: message"
# ============================================================
class TestParseGitLogStat:
    """_parse_git_log_stat: git log --stat --format='%h %ci %s' 出力のパース"""

    def test_parses_single_commit(self, hub):
        log_text = """a44d528 2026-06-13 10:00:15 +0900 fix: correct error handling
 backend/agents/director.py | 5 ++---
 1 file changed, 2 insertions(+), 3 deletions(-)
"""
        result = hub._parse_git_log_stat(log_text)
        assert len(result) >= 1
        assert result[0]["hash"] == "a44d528"
        assert "director.py" in result[0]["files"][0]["name"]

    def test_returns_empty_for_empty_input(self, hub):
        result = hub._parse_git_log_stat("")
        assert result == []

    def test_parses_multiple_commits(self, hub):
        log_text = """aaa1111 2026-06-13 10:00:00 +0900 feat: add module A
 backend/module_a.py | 10 ++++++++++
 1 file changed, 10 insertions(+)

bbb2222 2026-06-13 11:00:00 +0900 fix: patch module B
 backend/module_b.py | 3 ++-
 1 file changed, 2 insertions(+), 1 deletion(-)
"""
        result = hub._parse_git_log_stat(log_text)
        assert len(result) == 2
        assert result[0]["hash"] == "aaa1111"
        assert result[1]["hash"] == "bbb2222"

    def test_extracts_commit_time(self, hub):
        log_text = """abc1234 2026-06-13 14:30:00 +0900 test commit
 file.py | 1 +
"""
        result = hub._parse_git_log_stat(log_text)
        assert result[0]["time"] is not None
        assert result[0]["time"].hour == 14


# ============================================================
# _capture_git_diff
# ============================================================
class TestCaptureGitDiff:
    """_capture_git_diff: git status + git diff のモックテスト"""

    @patch("subprocess.run")
    def test_captures_diff_successfully(self, mock_run, hub):
        hub._cleanup_git_index_lock = MagicMock()

        status_result = MagicMock()
        status_result.stdout = " M backend/test.py\n?? new_file.py\n"
        status_result.returncode = 0

        diff_result = MagicMock()
        diff_result.stdout = " backend/test.py | 2 +-\n 1 file changed\n"
        diff_result.returncode = 0

        mock_run.side_effect = [status_result, diff_result]
        result = hub._capture_git_diff()
        assert isinstance(result, dict)

    @patch("subprocess.run")
    def test_handles_git_error_gracefully(self, mock_run, hub):
        hub._cleanup_git_index_lock = MagicMock()
        mock_run.side_effect = Exception("git not found")
        result = hub._capture_git_diff()
        assert isinstance(result, dict)


# ============================================================
# _git_auto_commit
# ============================================================
class TestGitAutoCommit:
    """_git_auto_commit: git add + commitのモックテスト"""

    @patch("subprocess.run")
    def test_commits_successfully(self, mock_run, hub):
        hub._cleanup_git_index_lock = MagicMock()

        add_result = MagicMock()
        add_result.returncode = 0
        commit_result = MagicMock()
        commit_result.returncode = 0
        mock_run.side_effect = [add_result, commit_result]

        result = hub._git_auto_commit("test commit message")
        assert result is True

    @patch("subprocess.run")
    def test_returns_false_on_error(self, mock_run, hub):
        hub._cleanup_git_index_lock = MagicMock()
        mock_run.side_effect = Exception("git error")
        result = hub._git_auto_commit("fail commit")
        assert result is False


# ============================================================
# _cleanup_git_index_lock
# ============================================================
class TestCleanupGitIndexLock:
    """_cleanup_git_index_lock: ゾンビ .git/index.lock の自動削除テスト"""

    @patch("agents.orchestration.hub_reports._PROJECT_ROOT")
    def test_cleanup_removes_zombie_lock(self, mock_root, hub):
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_stat = MagicMock()
        mock_stat.st_mtime = 0.0  # 十分古いタイムスタンプ
        mock_path.stat.return_value = mock_stat
        
        # _PROJECT_ROOT / ".git" / "index.lock" のモック
        mock_root.__truediv__.return_value.__truediv__.return_value = mock_path
        
        hub._cleanup_git_index_lock()
        
        mock_path.unlink.assert_called_once_with(missing_ok=True)



# ============================================================
# 自動コミットの抑止（テスト実行中の誤コミット防止）
# ============================================================
class TestAutoCommitSuppression:
    """submit_batch_report の自動計装が、テスト実行中に git commit しないこと。

    _git_auto_commit は `git add -A` で作業ツリー全体を巻き込む。そのため
    pytest 実行が意図しないコミットを生む。2026-07-25 に cc/trinity-5.0 で
    実際に3件発生し、作業中の未コミットファイルまで取り込まれた。
    """

    def test_suppressed_while_pytest_is_running(self):
        from agents.orchestration.hub_gate import _auto_commit_suppressed

        # pytest 実行中は PYTEST_CURRENT_TEST が設定されている
        assert os.environ.get("PYTEST_CURRENT_TEST")
        assert _auto_commit_suppressed() is True

    def test_suppressed_by_explicit_env_var(self, monkeypatch):
        from agents.orchestration.hub_gate import _auto_commit_suppressed

        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("ANTIGRAVITY_DISABLE_AUTO_COMMIT", "1")
        assert _auto_commit_suppressed() is True

    def test_allowed_when_neither_is_set(self, monkeypatch):
        from agents.orchestration.hub_gate import _auto_commit_suppressed

        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("ANTIGRAVITY_DISABLE_AUTO_COMMIT", raising=False)
        assert _auto_commit_suppressed() is False
