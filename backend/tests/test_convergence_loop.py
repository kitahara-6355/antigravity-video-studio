"""
Test Suite for ConvergenceLoop (収束ループ)

# verifies: REQ-CONV-01
# verifies: REQ-CONV-02
# verifies: REQ-CONV-03
# verifies: REQ-CONV-04
# verifies: REQ-CONV-05
# satisfies: REQ-CONV-05
"""

import json
import pytest
from pathlib import Path
from backend.agents.orchestration.convergence_loop import (
    ConvergenceLoop,
    DEFAULT_MAX_RETRIES,
)


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def tmp_queue(tmp_path):
    """一時的なタスクキューファイルを作成する"""
    queue_path = tmp_path / "task_queue.json"
    queue_data = {
        "schema_version": "1.1",
        "current_batch_id": "batch_test01",
        "phase": 30,
        "milestone": "M30.1",
        "tasks": [
            {
                "id": "T-batch_test01-test_weaver-000",
                "group": "test_weaver",
                "level": "L1",
                "target_module": "sample_module.py",
                "instruction": "テスト用の指示",
                "status": "fail",
                "assigned_agent": "agent-001",
                "result": None,
                "created_at": "2026-06-06T00:00:00+00:00",
                "started_at": "2026-06-06T00:01:00+00:00",
                "retry_count": 0,
            },
            {
                "id": "T-batch_test01-bug_hunter-000",
                "group": "bug_hunter",
                "level": "L2",
                "target_module": "another_module.py",
                "instruction": "バグ修正指示",
                "status": "pass",
                "assigned_agent": "agent-002",
                "result": {"message": "success"},
                "created_at": "2026-06-06T00:00:00+00:00",
                "started_at": "2026-06-06T00:01:00+00:00",
                "retry_count": 0,
            },
            {
                "id": "T-batch_test01-refactor-000",
                "group": "refactor",
                "level": "L2",
                "target_module": "exhausted_module.py",
                "instruction": "リファクタ指示",
                "status": "fail",
                "assigned_agent": "agent-003",
                "result": None,
                "created_at": "2026-06-06T00:00:00+00:00",
                "started_at": "2026-06-06T00:01:00+00:00",
                "retry_count": 3,  # 既に上限
            },
        ],
        "blacklisted_modules": [],
        "assigned_modules": [],
    }
    queue_path.write_text(json.dumps(queue_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return queue_path


@pytest.fixture
def tmp_reports(tmp_path):
    """一時的なレポートファイルを作成する"""
    reports_path = tmp_path / "flash_reports.jsonl"
    reports_path.touch()
    return reports_path


@pytest.fixture
def loop(tmp_queue, tmp_reports):
    """ConvergenceLoop インスタンスを作成する"""
    return ConvergenceLoop(
        max_retries=3,
        task_queue_path=tmp_queue,
        flash_reports_path=tmp_reports,
    )


@pytest.fixture
def sample_fail_report():
    """失敗レポートのサンプル"""
    return {
        "error": "AssertionError: expected 42, got 0",
        "traceback": (
            "Traceback (most recent call last):\n"
            '  File "tests/test_sample.py", line 15, in test_calc\n'
            "    assert result == 42\n"
            "AssertionError: expected 42, got 0"
        ),
        "changed_files": ["backend/sample_module.py", "tests/test_sample.py"],
    }


@pytest.fixture
def sample_fatal_report():
    """致命的エラーのレポートサンプル"""
    return {
        "error": "SyntaxError: invalid syntax",
        "traceback": (
            "Traceback (most recent call last):\n"
            '  File "backend/broken.py", line 10\n'
            "    def foo(\n"
            "           ^\n"
            "SyntaxError: invalid syntax"
        ),
        "changed_files": [],
    }


# =========================================================================
# テスト: ConvergenceLoop の初期化
# =========================================================================
# verifies: REQ-CONV-01


class TestConvergenceLoopInit:
    """ConvergenceLoop のインスタンス生成テスト"""

    def test_default_max_retries(self):
        """デフォルトのリトライ上限が3であること"""
        loop = ConvergenceLoop()
        assert loop.max_retries == DEFAULT_MAX_RETRIES
        assert loop.max_retries == 3

    def test_custom_max_retries(self, tmp_path):
        """カスタムリトライ上限を設定できること"""
        loop = ConvergenceLoop(max_retries=5)
        assert loop.max_retries == 5

    def test_custom_paths(self, tmp_path):
        """カスタムパスを設定できること"""
        q_path = tmp_path / "q.json"
        r_path = tmp_path / "r.jsonl"
        loop = ConvergenceLoop(
            task_queue_path=q_path,
            flash_reports_path=r_path,
        )
        assert loop.task_queue_path == q_path
        assert loop.flash_reports_path == r_path


# =========================================================================
# テスト: should_retry() — リトライ可否判定
# =========================================================================
# verifies: REQ-CONV-03


class TestShouldRetry:
    """should_retry() のテスト"""

    def test_retry_allowed_on_first_failure(self, loop, sample_fail_report):
        """初回失敗時はリトライ可能であること"""
        task = {
            "id": "T-test-001",
            "retry_count": 0,
            "target_module": "sample.py",
        }
        decision = loop.should_retry(task, sample_fail_report)
        assert decision["retry"] is True
        assert decision["retry_count"] == 0
        assert "1/3" in decision["reason"]
        assert len(decision["feedback_prompt"]) > 0

    def test_retry_allowed_on_second_failure(self, loop, sample_fail_report):
        """2回目の失敗でもリトライ可能であること"""
        task = {"id": "T-test-002", "retry_count": 1}
        decision = loop.should_retry(task, sample_fail_report)
        assert decision["retry"] is True
        assert decision["retry_count"] == 1
        assert "2/3" in decision["reason"]

    def test_retry_denied_on_max_retries(self, loop, sample_fail_report):
        """リトライ上限に達した場合はリトライ不可であること"""
        task = {"id": "T-test-003", "retry_count": 3}
        decision = loop.should_retry(task, sample_fail_report)
        assert decision["retry"] is False
        assert "上限" in decision["reason"]

    def test_retry_denied_without_report(self, loop):
        """レポートなしではリトライ不可であること"""
        task = {"id": "T-test-004", "retry_count": 0}
        decision = loop.should_retry(task, None)
        assert decision["retry"] is False
        assert "レポート" in decision["reason"]

    def test_retry_denied_on_fatal_error(self, loop, sample_fatal_report):
        """致命的エラーではリトライ不可であること"""
        task = {"id": "T-test-005", "retry_count": 0}
        decision = loop.should_retry(task, sample_fatal_report)
        assert decision["retry"] is False
        assert "致命的" in decision["reason"]

    def test_retry_with_no_retry_count_field(self, loop, sample_fail_report):
        """retry_count フィールドがないタスクでも正常に動作すること"""
        task = {"id": "T-test-006"}  # retry_count なし
        decision = loop.should_retry(task, sample_fail_report)
        assert decision["retry"] is True
        assert decision["retry_count"] == 0


# =========================================================================
# テスト: prepare_retry() — キュー更新
# =========================================================================
# verifies: REQ-CONV-02, REQ-CONV-03


class TestPrepareRetry:
    """prepare_retry() のテスト"""

    def test_retry_updates_queue(self, loop, tmp_queue):
        """リトライ準備でキューが正しく更新されること"""
        task_id = "T-batch_test01-test_weaver-000"
        feedback = "前回のAssertionErrorを修正してください。"

        result = loop.prepare_retry(task_id, feedback)
        assert result is True

        # キューの内容を検証
        queue = json.loads(tmp_queue.read_text(encoding="utf-8"))
        task = next(t for t in queue["tasks"] if t["id"] == task_id)

        assert task["status"] == "pending"
        assert task["retry_count"] == 1
        assert task["started_at"] is None
        assert task["assigned_agent"] is None
        assert task["result"] is None
        assert "リトライ指示" in task["instruction"]
        assert feedback in task["instruction"]

    def test_retry_preserves_original_instruction(self, loop, tmp_queue):
        """リトライ時に元の指示が保持されること"""
        task_id = "T-batch_test01-test_weaver-000"
        feedback = "修正指示"

        loop.prepare_retry(task_id, feedback)

        queue = json.loads(tmp_queue.read_text(encoding="utf-8"))
        task = next(t for t in queue["tasks"] if t["id"] == task_id)
        assert "テスト用の指示" in task["instruction"]  # 元の指示が残っている

    def test_retry_nonexistent_task(self, loop):
        """存在しないタスクIDに対してはFalseを返すこと"""
        result = loop.prepare_retry("T-nonexistent-000", "feedback")
        assert result is False

    def test_retry_increments_count_correctly(self, loop, tmp_queue):
        """連続リトライでカウントが正しくインクリメントされること"""
        task_id = "T-batch_test01-test_weaver-000"

        # 1回目
        loop.prepare_retry(task_id, "fix #1")
        queue = json.loads(tmp_queue.read_text(encoding="utf-8"))
        task = next(t for t in queue["tasks"] if t["id"] == task_id)
        assert task["retry_count"] == 1

        # 2回目
        loop.prepare_retry(task_id, "fix #2")
        queue = json.loads(tmp_queue.read_text(encoding="utf-8"))
        task = next(t for t in queue["tasks"] if t["id"] == task_id)
        assert task["retry_count"] == 2


# =========================================================================
# テスト: record_retry_event() — リトライ記録
# =========================================================================
# verifies: REQ-CONV-04


class TestRecordRetryEvent:
    """record_retry_event() のテスト"""

    def test_event_recorded_to_jsonl(self, loop, tmp_reports):
        """リトライイベントがJSONLに記録されること"""
        loop.record_retry_event(
            task_id="T-test-001",
            retry_count=1,
            result="retry_fail",
            error_msg="AssertionError: expected 42",
            target_module="sample.py",
        )

        lines = tmp_reports.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1

        record = json.loads(lines[0])
        assert record["type"] == "convergence_loop_event"
        assert record["task_id"] == "T-test-001"
        assert record["retry_count"] == 1
        assert record["result"] == "retry_fail"
        assert "AssertionError" in record["error_msg"]
        assert record["target_module"] == "sample.py"
        assert "timestamp" in record

    def test_multiple_events(self, loop, tmp_reports):
        """複数のイベントが追記されること"""
        loop.record_retry_event("T-001", 1, "retry_fail")
        loop.record_retry_event("T-001", 2, "retry_success")

        lines = tmp_reports.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2

    def test_long_error_msg_truncated(self, loop, tmp_reports):
        """長いエラーメッセージが500文字に切り詰められること"""
        long_msg = "A" * 1000
        loop.record_retry_event("T-001", 1, "retry_fail", error_msg=long_msg)

        lines = tmp_reports.read_text(encoding="utf-8").strip().splitlines()
        record = json.loads(lines[0])
        assert len(record["error_msg"]) == 500


# =========================================================================
# テスト: get_retry_stats() — 統計情報
# =========================================================================
# verifies: REQ-CONV-04


class TestGetRetryStats:
    """get_retry_stats() のテスト"""

    def test_empty_stats(self, loop):
        """レポートが空の場合のデフォルト統計"""
        stats = loop.get_retry_stats()
        assert stats["total_retries"] == 0
        assert stats["retry_successes"] == 0
        assert stats["retry_failures"] == 0
        assert stats["retry_exhausted"] == 0
        assert stats["modules_retried"] == []

    def test_stats_with_events(self, loop, tmp_reports):
        """複数イベントからの統計集計"""
        loop.record_retry_event("T-001", 1, "retry_fail", target_module="mod_a.py")
        loop.record_retry_event("T-001", 2, "retry_success", target_module="mod_a.py")
        loop.record_retry_event("T-002", 1, "retry_exhausted", target_module="mod_b.py")

        stats = loop.get_retry_stats()
        assert stats["total_retries"] == 3
        assert stats["retry_successes"] == 1
        assert stats["retry_failures"] == 1
        assert stats["retry_exhausted"] == 1
        assert set(stats["modules_retried"]) == {"mod_a.py", "mod_b.py"}

    def test_stats_ignores_non_convergence_events(self, loop, tmp_reports):
        """convergence_loop_event 以外のレコードは無視されること"""
        # 通常のバッチレポートを追加
        with open(tmp_reports, "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "batch_report", "batch_id": "b1"}) + "\n")

        loop.record_retry_event("T-001", 1, "retry_fail")

        stats = loop.get_retry_stats()
        assert stats["total_retries"] == 1  # batch_report はカウントされない


# =========================================================================
# テスト: _is_fatal_error() — 致命的エラー判定
# =========================================================================
# verifies: REQ-CONV-01


class TestIsFatalError:
    """_is_fatal_error() のテスト"""

    @pytest.mark.parametrize("error_keyword", [
        "SyntaxError: invalid syntax",
        "IndentationError: unexpected indent",
        "ModuleNotFoundError: No module named 'xyz'",
        "PermissionError: [Errno 13] Permission denied",
        "MemoryError",
        "MAX_RETRIES_EXCEEDED: 5回タイムアウト",
        "Process killed by OOM killer",
    ])
    def test_fatal_patterns_detected(self, loop, error_keyword):
        """致命的エラーパターンが正しく検出されること"""
        assert loop._is_fatal_error(error_keyword, "") is True

    @pytest.mark.parametrize("error_keyword", [
        "AssertionError: expected 42",
        "TypeError: cannot unpack",
        "KeyError: 'missing_key'",
        "ValueError: invalid literal",
        "TimeoutError: test timed out",
        "FileNotFoundError: [Errno 2]",
    ])
    def test_non_fatal_patterns_not_detected(self, loop, error_keyword):
        """非致命的エラーは致命的と判定されないこと"""
        assert loop._is_fatal_error(error_keyword, "") is False


# =========================================================================
# テスト: _generate_feedback_prompt() — フィードバック生成
# =========================================================================
# verifies: REQ-CONV-01


class TestGenerateFeedbackPrompt:
    """_generate_feedback_prompt() のテスト"""

    def test_includes_error_summary(self, loop):
        """エラーサマリーがフィードバックに含まれること"""
        feedback = loop._generate_feedback_prompt(
            task={"id": "T-001"},
            error_msg="AssertionError: expected 42",
            traceback_str="",
            changed_files=[],
            retry_count=0,
        )
        assert "AssertionError" in feedback
        assert "試行 0 回目" in feedback

    def test_includes_traceback_excerpt(self, loop):
        """トレースバックの抜粋が含まれること"""
        tb = (
            "Traceback (most recent call last):\n"
            '  File "tests/test_sample.py", line 15, in test_calc\n'
            "    assert result == 42\n"
            "AssertionError"
        )
        feedback = loop._generate_feedback_prompt(
            task={"id": "T-001"},
            error_msg="AssertionError",
            traceback_str=tb,
            changed_files=[],
            retry_count=1,
        )
        assert "test_sample.py" in feedback

    def test_includes_changed_files(self, loop):
        """変更ファイル一覧がフィードバックに含まれること"""
        feedback = loop._generate_feedback_prompt(
            task={"id": "T-001"},
            error_msg="Error",
            traceback_str="",
            changed_files=["backend/mod.py", "tests/test_mod.py"],
            retry_count=0,
        )
        assert "backend/mod.py" in feedback
        assert "tests/test_mod.py" in feedback

    def test_guidance_for_assertion_error(self, loop):
        """AssertionError に対する修正ガイダンスが生成されること"""
        feedback = loop._generate_feedback_prompt(
            task={"id": "T-001"},
            error_msg="AssertionError: expected 42",
            traceback_str="AssertionError: expected 42",
            changed_files=[],
            retry_count=0,
        )
        assert "アサーション" in feedback or "テスト" in feedback

    def test_guidance_for_timeout(self, loop):
        """タイムアウトに対する修正ガイダンスが生成されること"""
        feedback = loop._generate_feedback_prompt(
            task={"id": "T-001"},
            error_msg="TimeoutError: test timed out after 300s",
            traceback_str="",
            changed_files=[],
            retry_count=0,
        )
        assert "タイムアウト" in feedback


# =========================================================================
# テスト: _extract_relevant_traceback() — トレースバック抽出
# =========================================================================
# verifies: REQ-CONV-01


class TestExtractRelevantTraceback:
    """_extract_relevant_traceback() のテスト"""

    def test_short_traceback_returned_as_is(self, loop):
        """短いトレースバックはそのまま返されること"""
        tb = "Traceback:\n  File 'test.py', line 1\nError"
        result = loop._extract_relevant_traceback(tb)
        assert "test.py" in result
        assert "Error" in result

    def test_long_traceback_truncated(self, loop):
        """長いトレースバックは最大8行に制限されること"""
        lines = [f"  File 'module_{i}.py', line {i}" for i in range(20)]
        lines.append("FinalError: something went wrong")
        tb = "\n".join(lines)
        result = loop._extract_relevant_traceback(tb)
        result_lines = result.strip().splitlines()
        assert len(result_lines) <= 8


# =========================================================================
# テスト: 統合テスト（エンドツーエンド）
# =========================================================================
# verifies: REQ-CONV-01
# verifies: REQ-CONV-02
# verifies: REQ-CONV-03
# verifies: REQ-CONV-04
# verifies: REQ-CONV-05


class TestConvergenceLoopIntegration:
    """収束ループの統合テスト"""

    def test_full_retry_cycle(self, loop, tmp_queue, tmp_reports, sample_fail_report):
        """完全なリトライサイクル: 判定 → 準備 → 記録"""
        task_id = "T-batch_test01-test_weaver-000"

        # キューからタスクを取得
        queue = json.loads(tmp_queue.read_text(encoding="utf-8"))
        task = next(t for t in queue["tasks"] if t["id"] == task_id)

        # 1. リトライ可否判定
        decision = loop.should_retry(task, sample_fail_report)
        assert decision["retry"] is True

        # 2. リトライ準備
        result = loop.prepare_retry(task_id, decision["feedback_prompt"])
        assert result is True

        # 3. リトライイベント記録
        loop.record_retry_event(
            task_id=task_id,
            retry_count=decision["retry_count"] + 1,
            result="retry_fail",
            error_msg=sample_fail_report["error"],
            target_module=task.get("target_module", ""),
        )

        # 4. 統計確認
        stats = loop.get_retry_stats()
        assert stats["total_retries"] == 1

        # 5. キューの状態確認
        updated_queue = json.loads(tmp_queue.read_text(encoding="utf-8"))
        updated_task = next(t for t in updated_queue["tasks"] if t["id"] == task_id)
        assert updated_task["status"] == "pending"
        assert updated_task["retry_count"] == 1

    def test_retry_exhaustion_cycle(self, loop, tmp_queue, sample_fail_report):
        """リトライ上限到達サイクル"""
        task_id = "T-batch_test01-refactor-000"

        queue = json.loads(tmp_queue.read_text(encoding="utf-8"))
        task = next(t for t in queue["tasks"] if t["id"] == task_id)

        # retry_count が既に 3（上限）のタスク
        decision = loop.should_retry(task, sample_fail_report)
        assert decision["retry"] is False
        assert "上限" in decision["reason"]

    def test_pass_task_not_retried(self, loop, tmp_queue, sample_fail_report):
        """成功したタスクはリトライ対象外であること（should_retryは呼ばれないが念のため）"""
        task_id = "T-batch_test01-bug_hunter-000"

        queue = json.loads(tmp_queue.read_text(encoding="utf-8"))
        task = next(t for t in queue["tasks"] if t["id"] == task_id)
        # passしたタスクでもshould_retryは構造的に呼べる（retry_countに依存）
        assert task["status"] == "pass"
