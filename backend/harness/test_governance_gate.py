"""
Harness Governance Quality Gate Test
"""
import pytest
from unittest.mock import patch, MagicMock
from harness.governance import governance_engine, AgentScope
from pathlib import Path
from datetime import datetime
import time

# ============================================================
# 既存の品質ゲートテスト
# ============================================================

@patch("subprocess.run")
def test_validate_batch_quality_pass(mock_run):
    """正常なバッチ結果（失敗タスクなし、変更ファイル制限内）が合格することを確認"""
    # 2つのプロダクション変更ファイルを返すモック
    m1 = MagicMock()
    m1.stdout = "backend/agents/orchestration/orchestrator.py\n"
    m2 = MagicMock()
    m2.stdout = "backend/harness/governance.py\n"
    mock_run.side_effect = [m1, m2]

    results = {"passed": 3, "failed": 0, "total": 3}
    report = {
        "git_diff_summary": {"files_changed": 2},
        "tasks": [{"id": "T1"}, {"id": "T2"}, {"id": "T3"}]
    }
    # 例外が発生しないこと
    governance_engine.validate_batch_quality(results, report)

def test_validate_batch_quality_fail_task():
    """失敗タスクがある場合にValueErrorでブロックされることを確認"""
    results = {"passed": 2, "failed": 1, "total": 3}
    report = {
        "git_diff_summary": {"files_changed": 2},
        "tasks": [{"id": "T1"}, {"id": "T2"}, {"id": "T3", "status": "fail"}]
    }
    with pytest.raises(ValueError) as excinfo:
        governance_engine.validate_batch_quality(results, report)
    assert "失敗したタスク" in str(excinfo.value)

@patch("subprocess.run")
def test_validate_batch_quality_fail_file_limit(mock_run):
    """変更ファイル数が制限（タスク数 * 3）を超える場合にValueErrorでブロックされることを確認"""
    # 10個のプロダクション変更ファイルを返すモック
    m1 = MagicMock()
    m1.stdout = "\n".join([f"backend/module_{i}.py" for i in range(10)]) + "\n"
    m2 = MagicMock()
    m2.stdout = ""
    mock_run.side_effect = [m1, m2]

    results = {"passed": 2, "failed": 0, "total": 2}
    report = {
        "git_diff_summary": {"files_changed": 10},  # 2タスク * 3 = 6まで許容なので10はNG
        "tasks": [{"id": "T1"}, {"id": "T2"}]
    }
    with pytest.raises(ValueError) as excinfo:
        governance_engine.validate_batch_quality(results, report)
    assert "変更された本番ファイル数" in str(excinfo.value)

@patch("subprocess.run")
def test_validate_batch_quality_empty_tasks(mock_run):
    """タスクリストが空の場合でも最低3ファイル制限が適用され、合格することを確認"""
    # 2つの変更ファイルを返すモック（正常）
    m1 = MagicMock()
    m1.stdout = "backend/a.py\nbackend/b.py\n"
    m2 = MagicMock()
    m2.stdout = ""
    mock_run.side_effect = [m1, m2]

    results = {"passed": 0, "failed": 0, "total": 0}
    report = {
        "git_diff_summary": {"files_changed": 2},  # 最低3まで許容なので2はOK
        "tasks": []
    }
    governance_engine.validate_batch_quality(results, report)

@patch("subprocess.run")
def test_validate_batch_quality_empty_tasks_fail(mock_run):
    """タスクリストが空で4以上の変更がある場合にブロックされることを確認"""
    # 4つの変更ファイルを返すモック（異常）
    m1 = MagicMock()
    m1.stdout = "backend/a.py\nbackend/b.py\nbackend/c.py\nbackend/d.py\n"
    m2 = MagicMock()
    m2.stdout = ""
    mock_run.side_effect = [m1, m2]

    results = {"passed": 0, "failed": 0, "total": 0}
    report = {
        "git_diff_summary": {"files_changed": 4},
        "tasks": []
    }
    with pytest.raises(ValueError) as excinfo:
        governance_engine.validate_batch_quality(results, report)
    assert "変更された本番ファイル数" in str(excinfo.value)


# ============================================================
# 新規追加：カバレッジ 100% のためのテストケース
# ============================================================

def test_check_permission_scope_not_found():
    """定義されていない agent_id の権限チェックは True を返すことを確認"""
    assert governance_engine.check_permission("non_existent_agent", "some_tool") is True

def test_check_permission_allowed_tools():
    """ホワイトリスト制限の動作確認"""
    scope = AgentScope(
        agent_id="test_allowed",
        agent_name="Test Allowed",
        description="test",
        allowed_tools={"tool_a", "tool_b"}
    )
    governance_engine.register_scope(scope)
    assert governance_engine.check_permission("test_allowed", "tool_a") is True
    assert governance_engine.check_permission("test_allowed", "tool_c") is False

def test_check_permission_disallowed_tools():
    """ブラックリスト制限の動作確認"""
    scope = AgentScope(
        agent_id="test_disallowed",
        agent_name="Test Disallowed",
        description="test",
        disallowed_tools={"tool_bad"}
    )
    governance_engine.register_scope(scope)
    assert governance_engine.check_permission("test_disallowed", "tool_good") is True
    assert governance_engine.check_permission("test_disallowed", "tool_bad") is False

def test_check_permission_no_restrictions():
    """制限リスト（ホワイト・ブラック）がいずれも空の場合の動作確認"""
    scope = AgentScope(
        agent_id="test_no_limit",
        agent_name="Test No Limit",
        description="test"
    )
    governance_engine.register_scope(scope)
    assert governance_engine.check_permission("test_no_limit", "any_tool") is True

def test_check_rate_limit_no_scope():
    """未定義の agent_id に対するレート制限チェックは True を返すことを確認"""
    assert governance_engine.check_rate_limit("non_existent_agent") is True

def test_check_rate_limit_lifecycle():
    """制限範囲内および制限超過時の動作確認"""
    scope = AgentScope(
        agent_id="test_rate",
        agent_name="Test Rate",
        description="test",
        max_api_calls=2
    )
    governance_engine.register_scope(scope)
    assert governance_engine.check_rate_limit("test_rate") is True
    assert scope.current_api_calls == 1
    assert governance_engine.check_rate_limit("test_rate") is True
    assert scope.current_api_calls == 2
    assert governance_engine.check_rate_limit("test_rate") is False

def test_check_token_limit_no_scope():
    """未定義の agent_id に対するトークン制限チェックは True を返すことを確認"""
    assert governance_engine.check_token_limit("non_existent_agent", 500) is True

def test_check_token_limit_lifecycle():
    """トークン制限範囲内および制限超過時の動作確認"""
    scope = AgentScope(
        agent_id="test_token",
        agent_name="Test Token",
        description="test",
        max_tokens=100
    )
    governance_engine.register_scope(scope)
    assert governance_engine.check_token_limit("test_token", 40) is True
    assert scope.current_tokens == 40
    assert governance_engine.check_token_limit("test_token", 60) is True
    assert scope.current_tokens == 100
    assert governance_engine.check_token_limit("test_token", 1) is False

def test_register_scope():
    """カスタムスコープ登録の動作確認"""
    scope = AgentScope(
        agent_id="custom_agent",
        agent_name="Custom",
        description="custom desc"
    )
    governance_engine.register_scope(scope)
    assert "custom_agent" in governance_engine._scopes
    assert governance_engine._scopes["custom_agent"] == scope

def test_span_lifecycle():
    """スパンのライフサイクル（開始、イベント追加、終了、統計）の動作確認"""
    trace_id = "test-trace-id"
    parent_span_id = "parent-span-id"
    attributes = {"key1": "val1"}
    
    span_id = governance_engine.start_span(
        operation="test_op",
        tool_name="test_tool",
        trace_id=trace_id,
        parent_span_id=parent_span_id,
        attributes=attributes
    )
    
    assert span_id in governance_engine._active_spans
    span = governance_engine._active_spans[span_id]
    assert span.trace_id == trace_id
    assert span.parent_span_id == parent_span_id
    assert span.attributes == attributes

    governance_engine.add_span_event(span_id, "test_event", {"evt_key": "evt_val"})
    assert len(span.events) == 1
    assert span.events[0]["name"] == "test_event"
    assert span.events[0]["attributes"] == {"evt_key": "evt_val"}

    end_attributes = {"key2": "val2"}
    governance_engine.end_span(span_id, status="ok", attributes=end_attributes)
    
    assert span_id not in governance_engine._active_spans
    assert span.status == "ok"
    assert span.attributes == {"key1": "val1", "key2": "val2"}
    assert span.duration_ms is not None
    assert span.duration_ms >= 0.0

def test_end_span_invalid_id():
    """存在しないスパン ID の終了処理でエラーにならないこと"""
    governance_engine.end_span("non_existent_span_id")

def test_end_span_invalid_start_time():
    """start_time が不正フォーマットの時に duration_ms = 0.0 になること"""
    span_id = governance_engine.start_span("op", "tool")
    span = governance_engine._active_spans[span_id]
    span.start_time = "invalid_date_format"
    governance_engine.end_span(span_id)
    assert span.duration_ms == 0.0

def test_end_span_attribute_update_error():
    """attributes の update で例外が発生した際のエラーハンドリングが機能すること"""
    span_id = governance_engine.start_span("op", "tool")
    
    class BadAttributes:
        def update(self, *args, **kwargs):
            raise TypeError("bad update")
            
    governance_engine.end_span(span_id, attributes=BadAttributes())

def test_get_recent_traces():
    """最近の完了トレーススパンの一覧取得"""
    governance_engine._completed_spans.clear()
    
    s1 = governance_engine.start_span("op1", "tool1")
    governance_engine.end_span(s1)
    s2 = governance_engine.start_span("op2", "tool2")
    governance_engine.end_span(s2)
    
    traces = governance_engine.get_recent_traces(limit=1)
    assert len(traces) == 1
    assert traces[0]["operation"] == "op2"
    
    traces_all = governance_engine.get_recent_traces(limit=10)
    assert len(traces_all) == 2

def test_flush_traces_empty():
    """完了スパンがない場合に何も出力しないこと"""
    governance_engine._completed_spans.clear()
    with patch("builtins.open") as mock_open:
        governance_engine.flush_traces("session_123")
        mock_open.assert_not_called()

@patch("builtins.open")
def test_flush_traces_success(mock_open):
    """正常なトレース出力の動作確認"""
    governance_engine._completed_spans.clear()
    s = governance_engine.start_span("op", "tool")
    governance_engine.end_span(s)
    
    mock_file = MagicMock()
    mock_open.return_value.__enter__.return_value = mock_file
    
    governance_engine.flush_traces("session_ok")
    mock_open.assert_called_once()
    mock_file.write.assert_called_once()
    assert len(governance_engine._completed_spans) == 0

@patch("builtins.open")
def test_flush_traces_sanitize_session_id(mock_open):
    """session_id のサニタイズ（ディレクトリトラバーサル対策）の確認"""
    governance_engine._completed_spans.clear()
    s = governance_engine.start_span("op", "tool")
    governance_engine.end_span(s)
    
    mock_file = MagicMock()
    mock_open.return_value.__enter__.return_value = mock_file
    
    governance_engine.flush_traces("../dangerous")
    assert "dangerous" in str(mock_open.call_args[0][0])
    
    s2 = governance_engine.start_span("op", "tool")
    governance_engine.end_span(s2)
    governance_engine.flush_traces("..")
    assert "default" in str(mock_open.call_args[0][0])

    s3 = governance_engine.start_span("op", "tool")
    governance_engine.end_span(s3)
    governance_engine.flush_traces(None)
    assert "default" in str(mock_open.call_args[0][0])

@patch("builtins.open")
def test_flush_traces_io_error(mock_open):
    """ファイルオープン時に OSError 等が発生した場合のエラーハンドリングが機能すること"""
    governance_engine._completed_spans.clear()
    s = governance_engine.start_span("op", "tool")
    governance_engine.end_span(s)
    
    mock_open.side_effect = OSError("mock disk full")
    governance_engine.flush_traces("session_io")

def test_get_trace_tree():
    """親子関係に基づくトレースツリー構築の確認"""
    governance_engine._completed_spans.clear()
    
    assert governance_engine.get_trace_tree("non_existent_trace") == []
    
    t_id = "tree-trace"
    p_id = governance_engine.start_span("parent_op", "tool", trace_id=t_id)
    c_id = governance_engine.start_span("child_op", "tool", trace_id=t_id, parent_span_id=p_id)
    orphan_id = governance_engine.start_span("orphan_op", "tool", trace_id=t_id, parent_span_id="missing-parent")
    
    governance_engine.end_span(p_id)
    governance_engine.end_span(c_id)
    governance_engine.end_span(orphan_id)
    
    tree = governance_engine.get_trace_tree(t_id)
    assert len(tree) == 2
    
    parent_node = next(node for node in tree if node["span_id"] == p_id)
    assert len(parent_node["children"]) == 1
    assert parent_node["children"][0]["span_id"] == c_id
    
    orphan_node = next(node for node in tree if node["span_id"] == orphan_id)
    assert len(orphan_node["children"]) == 0

def test_get_stats():
    """統計情報取得の動作確認"""
    stats = governance_engine.get_stats()
    assert "scopes" in stats
    assert "active_spans" in stats
    assert "completed_spans" in stats
    assert "total_span_count" in stats

def test_reset_api_counters():
    """カウンターリセットの動作確認"""
    scope = AgentScope(
        agent_id="test_reset",
        agent_name="Test Reset",
        description="test",
        max_api_calls=10,
        max_tokens=100
    )
    governance_engine.register_scope(scope)
    governance_engine.check_rate_limit("test_reset")
    governance_engine.check_token_limit("test_reset", 50)
    
    assert scope.current_api_calls == 1
    assert scope.current_tokens == 50
    
    governance_engine.reset_api_counters()
    assert scope.current_api_calls == 0
    assert scope.current_tokens == 0

@patch("subprocess.run")
def test_validate_batch_quality_exclude_patterns(mock_run):
    """除外ファイルパターンがカウントから除外されること"""
    m1 = MagicMock()
    m1.stdout = "\n".join([
        "tests/test_a.py",
        "backend/test_b.py",
        "test_c.py",
        "Human01_Official Artifact/report.md",
        "scratch/temp.py",
        "temp_thumbnails/preview.jpg",
        "README.md",
        "docs/doc.txt",
        "config.json",
        "log.jsonl",
        "flash_assign_subagents.py",
        "flash_runner.py",
        "mark_tasks.py",
        "backend/real_production_file.py"
    ]) + "\n"
    m2 = MagicMock()
    m2.stdout = ""
    mock_run.side_effect = [m1, m2]

    results = {"passed": 1, "failed": 0, "total": 1}
    report = {
        "git_diff_summary": {"files_changed": 14},
        "tasks": [{"id": "T1"}]
    }
    
    governance_engine.validate_batch_quality(results, report)

@patch("subprocess.run")
def test_validate_batch_quality_subprocess_error(mock_run):
    """subprocess.run が例外をスローした際のフォールバック処理の確認"""
    mock_run.side_effect = RuntimeError("git command failed")
    
    results = {"passed": 1, "failed": 0, "total": 1}
    
    report_ok = {
        "git_diff_summary": {"files_changed": 2},
        "tasks": [{"id": "T1"}]
    }
    governance_engine.validate_batch_quality(results, report_ok)
    
    report_fail = {
        "git_diff_summary": {"files_changed": 5},
        "tasks": [{"id": "T1"}]
    }
    with pytest.raises(ValueError) as excinfo:
        governance_engine.validate_batch_quality(results, report_fail)
    assert "変更された本番ファイル数" in str(excinfo.value)
