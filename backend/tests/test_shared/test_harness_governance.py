"""
test_harness_governance.py — M2.3 Sprint 2.3.3 GovernanceEngine 5テスト

テスト対象: backend/harness/governance.py (408行, 20分岐)
  - GovernanceEngine: check_permission (ブラックリスト), end_span (未知ID),
    flush_traces (正常/空), check_permission 性能

テスト設計方針:
  - 既存 test_harness.py #10-#13 で主要12分岐カバー済み
  - 本ファイルは未カバーのエッジケース（ブラックリスト、未知span、flush I/O）に集中
  - trace_dir は tmp_path で隔離

カテゴリ構成:
  C1-C4: エッジケース・I/O (3)
  C5: 統合 (1)
  C6: 性能 (1)
"""

import sys
import json
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from harness.governance import GovernanceEngine, AgentScope


# ============================================================
# フィクスチャ
# ============================================================

@pytest.fixture
def governance_engine(tmp_path):
    """各テストで新規GovernanceEngineを生成（trace_dir=tmp_path）"""
    return GovernanceEngine(trace_dir=tmp_path)


# ============================================================
# C1-C4: エッジケース・I/O (3)
# ============================================================

class TestEdgeCases:
    """C1-C4: エッジケース・I/Oテスト"""

    def test_G_C1_01_check_permission_blacklist_mode(self, governance_engine):
        """G-C1-01: allowed_tools空 + disallowed_tools にツール名がある場合、拒否されること"""
        # ブラックリスト方式のカスタムスコープ
        scope = AgentScope(
            agent_id="restricted_agent",
            agent_name="制限付きエージェント",
            description="ブラックリストテスト用",
            allowed_tools=set(),  # ホワイトリスト空
            disallowed_tools={"dangerous_tool", "delete_all"},
        )
        governance_engine.register_scope(scope)

        # ブラックリストにあるツール → 拒否
        assert governance_engine.check_permission("restricted_agent", "dangerous_tool") is False
        assert governance_engine.check_permission("restricted_agent", "delete_all") is False
        # ブラックリストにないツール → 許可
        assert governance_engine.check_permission("restricted_agent", "safe_tool") is True

    def test_G_C2_01_end_span_unknown_id(self, governance_engine):
        """G-C2-01: 存在しない span_id で end_span() を呼んでもエラーにならないこと"""
        # 例外が発生しないことを確認
        governance_engine.end_span("nonexistent-span-id", status="ok")
        # completed_spans にも追加されないことを確認
        assert len(governance_engine._completed_spans) == 0

    def test_G_C3_01_flush_traces_writes_jsonl(self, governance_engine, tmp_path):
        """G-C3-01: flush_traces() が JSONL ファイルを出力し、内容が正しいこと"""
        # 2つのスパンを作成して完了させる
        span1 = governance_engine.start_span(
            "transcribe", "transcribe_video",
            attributes={"input_path": "/test.mp4"},
        )
        governance_engine.end_span(span1, status="ok")

        span2 = governance_engine.start_span(
            "proofread", "proofread_subtitles",
        )
        governance_engine.add_span_event(span2, "correction_applied", {"count": 5})
        governance_engine.end_span(span2, status="ok", attributes={"corrections": 5})

        # flush
        governance_engine.flush_traces(session_id="test-session")

        # JSONL ファイルが作成されたことを確認
        trace_files = list(tmp_path.glob("trace_test-session_*.jsonl"))
        assert len(trace_files) == 1

        # 内容を検証
        lines = trace_files[0].read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

        span1_data = json.loads(lines[0])
        assert span1_data["operation"] == "transcribe"
        assert span1_data["tool_name"] == "transcribe_video"
        assert span1_data["status"] == "ok"
        assert span1_data["duration_ms"] is not None
        assert span1_data["attributes"]["input_path"] == "/test.mp4"

        span2_data = json.loads(lines[1])
        assert span2_data["operation"] == "proofread"
        assert len(span2_data["events"]) == 1
        assert span2_data["events"][0]["name"] == "correction_applied"
        assert span2_data["attributes"]["corrections"] == 5

        # flush 後、completed_spans はクリアされること
        assert len(governance_engine._completed_spans) == 0


# ============================================================
# C5: 統合 (1)
# ============================================================

class TestIntegration:
    """C5: 統合テスト"""

    def test_G_C5_01_flush_traces_empty_noop(self, governance_engine, tmp_path):
        """G-C5-01: 完了スパンが0件の場合、flush_traces() がファイルを作成しないこと"""
        governance_engine.flush_traces(session_id="empty-session")

        trace_files = list(tmp_path.glob("*.jsonl"))
        assert len(trace_files) == 0


# ============================================================
# C6: 性能 (1)
# ============================================================

class TestPerformance:
    """C6: 性能テスト"""

    def test_G_C6_01_check_permission_speed(self, governance_engine):
        """G-C6-01: check_permission が 1000 回実行で 5ms 以内に完了すること"""
        start = time.perf_counter()
        for _ in range(1000):
            governance_engine.check_permission("transcriber", "transcribe_video")
        elapsed = time.perf_counter() - start

        assert elapsed < 0.005, f"1000回で {elapsed*1000:.1f}ms (> 5ms)"


# ============================================================
# C7: カバレッジ強化 & 例外フォールバック境界検証 (新規追加)
# ============================================================

class TestGovernanceCoverageBoost:
    """C7: 未カバーパスのカバーおよび例外フォールバックの境界検証"""

    def test_check_permission_undefined_scope(self, governance_engine):
        """未定義のエージェントIDに対する許可チェック（Trueが返る）"""
        assert governance_engine.check_permission("nonexistent_agent", "some_tool") is True

    def test_check_permission_whitelist_denied_warning(self, governance_engine, caplog):
        """ホワイトリスト拒否時に警告ログが出力されること"""
        import logging
        scope = AgentScope(
            agent_id="whitelist_agent",
            agent_name="ホワイトリスト制限エージェント",
            description="ホワイトリスト検証用",
            allowed_tools={"allowed_tool"},
        )
        governance_engine.register_scope(scope)

        with caplog.at_level(logging.WARNING):
            assert governance_engine.check_permission("whitelist_agent", "denied_tool") is False
            assert "Permission denied: whitelist_agent → denied_tool" in caplog.text

    def test_check_permission_no_restrictions(self, governance_engine):
        """allowed_toolsもdisallowed_toolsも空のスコープの動作検証"""
        scope = AgentScope(
            agent_id="free_agent",
            agent_name="自由エージェント",
            description="制限なし検証用",
            allowed_tools=set(),
            disallowed_tools=set(),
        )
        governance_engine.register_scope(scope)
        assert governance_engine.check_permission("free_agent", "any_tool") is True

    def test_check_rate_limit_flows(self, governance_engine, caplog):
        """Rate limit チェックの検証（未定義、正常加算、制限到達）"""
        import logging
        
        # 未定義エージェント
        assert governance_engine.check_rate_limit("nonexistent_agent") is True

        # カスタムスコープ（max_api_calls=2）
        scope = AgentScope(
            agent_id="limited_agent",
            agent_name="制限エージェント",
            description="API制限検証用",
            max_api_calls=2,
            current_api_calls=0,
        )
        governance_engine.register_scope(scope)

        # 1回目 (0 -> 1)
        assert governance_engine.check_rate_limit("limited_agent") is True
        assert scope.current_api_calls == 1

        # 2回目 (1 -> 2)
        assert governance_engine.check_rate_limit("limited_agent") is True
        assert scope.current_api_calls == 2

        # 3回目 (制限到達)
        with caplog.at_level(logging.WARNING):
            assert governance_engine.check_rate_limit("limited_agent") is False
            assert "Rate limit: limited_agent" in caplog.text

    def test_get_recent_traces(self, governance_engine):
        """直近 of 完了スパンが指定件数取得できること"""
        span1 = governance_engine.start_span("op1", "tool1")
        governance_engine.end_span(span1, status="ok")

        span2 = governance_engine.start_span("op2", "tool2")
        governance_engine.end_span(span2, status="error")

        recent = governance_engine.get_recent_traces(limit=1)
        assert len(recent) == 1
        assert recent[0]["span_id"] == span2
        assert recent[0]["operation"] == "op2"
        assert recent[0]["status"] == "error"

        recent_all = governance_engine.get_recent_traces(limit=5)
        assert len(recent_all) == 2
        assert recent_all[0]["span_id"] == span1

    def test_get_stats(self, governance_engine):
        """get_stats がガバナンス統計を正しく集計すること"""
        # 初期状態の統計
        stats = governance_engine.get_stats()
        assert "transcriber" in stats["scopes"]
        assert stats["active_spans"] == 0
        assert stats["completed_spans"] == 0

        # アクティブスパン追加
        span = governance_engine.start_span("op", "tool")
        stats = governance_engine.get_stats()
        assert stats["active_spans"] == 1
        assert stats["total_span_count"] == 1

        # 完了スパン追加
        governance_engine.end_span(span)
        stats = governance_engine.get_stats()
        assert stats["active_spans"] == 0
        assert stats["completed_spans"] == 1

    def test_reset_api_counters(self, governance_engine):
        """APIカウンターがリセットされること"""
        scope = AgentScope(
            agent_id="reset_agent",
            agent_name="リセットエージェント",
            description="リセット検証用",
            max_api_calls=5,
            current_api_calls=3,
        )
        governance_engine.register_scope(scope)
        
        governance_engine.reset_api_counters()
        assert scope.current_api_calls == 0

    def test_flush_traces_exception_fallback(self, governance_engine, monkeypatch, caplog):
        """例外フォールバックの境界検証: 書込み失敗時に例外をキャッチしてログ出力すること"""
        import logging

        span = governance_engine.start_span("op", "tool")
        governance_engine.end_span(span)

        # builtins.open が例外を投げるようにモック
        def mock_open_raise(*args, **kwargs):
            raise OSError("Mock disk write failure")

        # pythonの組み込み open をモック化
        import builtins
        monkeypatch.setattr(builtins, "open", mock_open_raise)

        with caplog.at_level(logging.ERROR):
            # 例外が外に漏れず、正常終了（フォールバック）すること
            governance_engine.flush_traces(session_id="error_session")
            assert "Trace flush failed: Mock disk write failure" in caplog.text

    def test_flush_traces_session_id_sanitization(self, governance_engine, tmp_path):
        """session_id にトラバーサル文字が含まれる場合、サニタイズされること"""
        span = governance_engine.start_span("op", "tool")
        governance_engine.end_span(span)

        # トラバーサル文字を含む session_id
        governance_engine.flush_traces(session_id="subdir/../hacker_session")

        # 隔離された tmp_path 直下に書き込まれるか確認 (Path.name により hacker_session になる)
        trace_files = list(tmp_path.glob("trace_hacker_session_*.jsonl"))
        assert len(trace_files) == 1
        assert trace_files[0].exists()

        # 親ディレクトリに trace_ が無いことも確認
        parent_trace = list(tmp_path.parent.glob("trace_hacker_session_*.jsonl"))
        assert len(parent_trace) == 0

    def test_end_span_invalid_time_format_fallback(self, governance_engine, caplog):
        """start_time が不正な形式の場合、end_span がクラッシュせずに duration_ms = 0.0 になること"""
        import logging

        span_id = governance_engine.start_span("op", "tool")
        # 不正な日付形式を手動で代入
        span = governance_engine._active_spans[span_id]
        span.start_time = "invalid-date-string"

        with caplog.at_level(logging.ERROR):
            governance_engine.end_span(span_id)
            assert "Failed to calculate span duration" in caplog.text

        completed = governance_engine._completed_spans[0]
        assert completed.duration_ms == 0.0

    def test_flush_traces_unserializable_attributes(self, governance_engine, caplog):
        """JSONシリアライズ不可能な属性がある場合、flush_traces が例外をキャッチしてログ出力すること"""
        import logging

        span_id = governance_engine.start_span("op", "tool", attributes={"unserializable": {1, 2, 3}}) # set はシリアライズ不可
        governance_engine.end_span(span_id)

        with caplog.at_level(logging.ERROR):
            # json.dumps は TypeError をスローするが、flush_traces 内でキャッチされログ出力される
            governance_engine.flush_traces(session_id="unserializable_session")
            assert "Trace flush failed:" in caplog.text

    def test_flush_traces_session_id_empty_or_dots(self, governance_engine, tmp_path):
        """session_id が '.' や '..' や空文字列の場合に 'default' として保存されること"""
        for invalid_id in [".", "..", ""]:
            span = governance_engine.start_span("op", "tool")
            governance_engine.end_span(span)
            governance_engine.flush_traces(session_id=invalid_id)

        # trace_default_*.jsonl ファイルが生成されることを検証
        trace_files = list(tmp_path.glob("trace_default_*.jsonl"))
        assert len(trace_files) >= 1

    def test_end_span_invalid_attributes_type(self, governance_engine, caplog):
        """attributes が辞書以外の型で渡された場合、例外がキャッチされてログ出力されること"""
        import logging

        span_id = governance_engine.start_span("op", "tool")
        with caplog.at_level(logging.ERROR):
            # attributes に dict 以外の型を指定
            governance_engine.end_span(span_id, attributes="not-a-dictionary")
            assert "Failed to update span attributes" in caplog.text


    def test_add_span_event_unknown_id(self, governance_engine):
        """存在しない span_id に対して add_span_event() を呼び出した場合、エラーにならず何も処理されないこと"""
        # 例外が発生しないことを確認
        governance_engine.add_span_event("nonexistent-span-id", "some_event")

    def test_check_token_limit_flows(self, governance_engine, caplog):
        """Token limit チェックの検証（未定義、正常加算、制限到達）"""
        import logging

        # 未定義エージェント
        assert governance_engine.check_token_limit("nonexistent_agent", 100) is True

        # カスタムスコープ (max_tokens=1000)
        scope = AgentScope(
            agent_id="token_limited_agent",
            agent_name="トークン制限エージェント",
            description="トークン制限検証用",
            max_tokens=1000,
            current_tokens=0,
        )
        governance_engine.register_scope(scope)

        # 正常消費 (0 -> 400)
        assert governance_engine.check_token_limit("token_limited_agent", 400) is True
        assert scope.current_tokens == 400

        # 正常消費 (400 -> 900)
        assert governance_engine.check_token_limit("token_limited_agent", 500) is True
        assert scope.current_tokens == 900

        # 上限超過 (900 + 200 > 1000)
        with caplog.at_level(logging.WARNING):
            assert governance_engine.check_token_limit("token_limited_agent", 200) is False
            assert "Token limit exceeded for token_limited_agent" in caplog.text
            assert scope.current_tokens == 900

    def test_get_trace_tree_flows(self, governance_engine):
        """get_trace_tree の検証（親子関係構築、空リスト、親不在）"""
        trace_id = "test-tree-trace"

        # 完了スパンが空の場合
        assert governance_engine.get_trace_tree(trace_id) == []

        # 親スパン
        span1_id = governance_engine.start_span("parent_op", "parent_tool", trace_id=trace_id)
        governance_engine.end_span(span1_id)

        # 子スパン
        span2_id = governance_engine.start_span("child_op", "child_tool", trace_id=trace_id, parent_span_id=span1_id)
        governance_engine.end_span(span2_id)

        # 親不在のスパン (parent_span_id が存在するが完了スパンにない)
        span3_id = governance_engine.start_span("orphan_op", "orphan_tool", trace_id=trace_id, parent_span_id="nonexistent-parent")
        governance_engine.end_span(span3_id)

        # 別の trace_id のスパン (対象外になる)
        span_other = governance_engine.start_span("other_op", "other_tool", trace_id="other-trace")
        governance_engine.end_span(span_other)

        tree = governance_engine.get_trace_tree(trace_id)
        assert len(tree) == 2  # span1 (親) と span3 (親不在) が root

        # span1 の検証
        parent_node = next(n for n in tree if n["span_id"] == span1_id)
        assert parent_node["operation"] == "parent_op"
        assert len(parent_node["children"]) == 1

        # span2 (子) の検証
        child_node = parent_node["children"][0]
        assert child_node["span_id"] == span2_id
        assert child_node["operation"] == "child_op"
        assert child_node["parent_span_id"] == span1_id

        # span3 (親不在) の検証
        orphan_node = next(n for n in tree if n["span_id"] == span3_id)
        assert orphan_node["operation"] == "orphan_op"
        assert orphan_node["parent_span_id"] == "nonexistent-parent"
        assert len(orphan_node["children"]) == 0

    def test_validate_batch_quality_flows(self, governance_engine, monkeypatch):
        """validate_batch_quality の検証（正常、失敗ありエラー、ファイル数制限超過、例外フォールバック）"""
        # 1. 正常系
        results = {"passed": 3, "failed": 0, "total": 3}
        report = {"tasks": [{"id": "T1"}, {"id": "T2"}], "git_diff_summary": {"files_changed": 1}}
        
        # git コマンドをモックして変更本番ファイル数を 0 にする
        class MockCompletedProcess:
            def __init__(self, stdout):
                self.stdout = stdout

        def mock_run_empty(*args, **kwargs):
            return MockCompletedProcess("")

        import subprocess
        monkeypatch.setattr(subprocess, "run", mock_run_empty)

        # 例外が発生しないこと
        governance_engine.validate_batch_quality(results, report)

        # 2. 異常系: 失敗タスクあり
        results_failed = {"passed": 2, "failed": 1, "total": 3}
        with pytest.raises(ValueError) as excinfo:
            governance_engine.validate_batch_quality(results_failed, report)
        assert "失敗したタスクが 1 件存在します" in str(excinfo.value)

        # 3. 異常系: 変更ファイル数制限超過 (git diff モック)
        # タスク数 2 -> 制限は max(3, 2 * 3) = 6 ファイル
        # 変更ファイルを 7 個（すべて本番コードと判定されるもの）にする
        def mock_run_many(*args, **kwargs):
            files = "\n".join([f"backend/core/file{i}.py" for i in range(7)])
            return MockCompletedProcess(files)

        monkeypatch.setattr(subprocess, "run", mock_run_many)

        with pytest.raises(ValueError) as excinfo:
            governance_engine.validate_batch_quality(results, report)
        assert "変更された本番ファイル数が制限値" in str(excinfo.value)

        # 除外ファイルがカウントされないことも検証
        def mock_run_excluded(*args, **kwargs):
            # 9ファイルのうち7ファイルがテストやドキュメントなどの除外対象
            files = [
                "backend/tests/test_file.py",
                "backend/core/test_core.py",
                "Human01_Official Artifact/doc.md",
                "scratch/temp.py",
                "README.md",
                "backend/temp_thumbnails/thumb1.png",
                "backend/core/flash_assign_subagents_run.py",
                "backend/core/file1.py",
                "backend/core/file2.py"
            ]
            return MockCompletedProcess("\n".join(files))

        monkeypatch.setattr(subprocess, "run", mock_run_excluded)
        # 本番変更ファイル数は 2 になるため、上限 6 未満でパスするはず
        governance_engine.validate_batch_quality(results, report)

        # 4. 例外フォールバックの検証
        # subprocess.run が例外を投げた場合、report から git_diff_summary を参照する
        def mock_run_raise(*args, **kwargs):
            raise RuntimeError("Git command failed")

        monkeypatch.setattr(subprocess, "run", mock_run_raise)

        # report 内の git_diff_summary で制限超過 (7ファイル)
        report_over = {"tasks": [{"id": "T1"}, {"id": "T2"}], "git_diff_summary": {"files_changed": 7}}
        with pytest.raises(ValueError) as excinfo:
            governance_engine.validate_batch_quality(results, report_over)
        assert "変更された本番ファイル数が制限値" in str(excinfo.value)

        # report 内の git_diff_summary で制限内 (2ファイル)
        report_under = {"tasks": [{"id": "T1"}, {"id": "T2"}], "git_diff_summary": {"files_changed": 2}}
        # 例外が発生しないこと
        governance_engine.validate_batch_quality(results, report_under)

    def test_flush_traces_session_id_none(self, governance_engine, tmp_path):
        """session_id が None の場合、'default' として正しく保存されること"""
        span = governance_engine.start_span("op", "tool")
        governance_engine.end_span(span)
        
        # session_id を明示的に指定しない (None)
        governance_engine.flush_traces(session_id=None)
        
        # trace_default_*.jsonl ファイルが生成されることを検証
        trace_files = list(tmp_path.glob("trace_default_*.jsonl"))
        assert len(trace_files) >= 1




