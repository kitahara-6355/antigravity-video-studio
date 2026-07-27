# -*- coding: utf-8 -*-
import pytest
from harness.governance import GovernanceEngine, AgentScope

def test_token_limit_checking():
    # テスト用のクリーンな GovernanceEngine インスタンスを作成
    engine = GovernanceEngine()
    
    # テスト用の AgentScope を登録
    test_scope = AgentScope(
        agent_id="test_token_agent",
        agent_name="トークンテスト用エージェント",
        description="トークン制限機能の検証",
        max_tokens=1000,
        current_tokens=0
    )
    engine.register_scope(test_scope)
    
    # 通常の消費チェック
    assert engine.check_token_limit("test_token_agent", 500) is True
    assert engine.check_token_limit("test_token_agent", 400) is True
    
    # 累積値の確認
    stats = engine.get_stats()
    assert stats["scopes"]["test_token_agent"]["tokens"] == "900/1000"
    
    # 上限突破時の拒否チェック
    assert engine.check_token_limit("test_token_agent", 200) is False
    # 消費量が増えていないことの確認
    stats = engine.get_stats()
    assert stats["scopes"]["test_token_agent"]["tokens"] == "900/1000"
    
    # カウンターリセットのチェック
    engine.reset_api_counters()
    stats = engine.get_stats()
    assert stats["scopes"]["test_token_agent"]["tokens"] == "0/1000"
    
    # 未定義エージェントの場合
    assert engine.check_token_limit("nonexistent_agent", 5000) is True


def test_trace_tree_construction():
    engine = GovernanceEngine()
    
    # トレーススパンのシミュレーション
    trace_id = "test-trace-123"
    
    # スパンの開始・終了（時系列に完了させて completed_spans に入れる）
    # ルートスパン
    root_id = engine.start_span("root_op", "root_tool", trace_id=trace_id)
    
    # 子スパン1
    child1_id = engine.start_span("child_op_1", "tool_1", trace_id=trace_id, parent_span_id=root_id)
    # 子スパン1の完了
    engine.end_span(child1_id, status="ok")
    
    # 子スパン2
    child2_id = engine.start_span("child_op_2", "tool_2", trace_id=trace_id, parent_span_id=root_id)
    
    # 孫スパン（子スパン2の子）
    grandchild_id = engine.start_span("grandchild_op", "tool_3", trace_id=trace_id, parent_span_id=child2_id)
    engine.end_span(grandchild_id, status="ok")
    
    # 子スパン2の完了
    engine.end_span(child2_id, status="error")
    
    # ルートスパンの完了
    engine.end_span(root_id, status="ok")
    
    # ツリーの構築
    tree = engine.get_trace_tree(trace_id)
    
    # ツリー構造の検証
    assert len(tree) == 1
    root_node = tree[0]
    assert root_node["span_id"] == root_id
    assert root_node["operation"] == "root_op"
    assert len(root_node["children"]) == 2
    
    # 子ノードの検証（完了順/追加順）
    child1_node = next(c for c in root_node["children"] if c["span_id"] == child1_id)
    child2_node = next(c for c in root_node["children"] if c["span_id"] == child2_id)
    
    assert child1_node["status"] == "ok"
    assert child2_node["status"] == "error"
    
    assert len(child2_node["children"]) == 1
    grandchild_node = child2_node["children"][0]
    assert grandchild_node["span_id"] == grandchild_id
    assert grandchild_node["operation"] == "grandchild_op"
    
    # 存在しない trace_id の場合
    assert engine.get_trace_tree("nonexistent-trace") == []


def test_check_permission():
    engine = GovernanceEngine()
    
    # ホワイトリスト方式の検証
    # transcriber は allowed_tools={"transcribe_video"}
    assert engine.check_permission("transcriber", "transcribe_video") is True
    assert engine.check_permission("transcriber", "invalid_tool") is False
    
    # ブラックリスト方式の検証
    from harness.governance import AgentScope
    custom_scope = AgentScope(
        agent_id="blacklist_agent",
        agent_name="ブラックリストテストエージェント",
        description="ブラックリストの検証",
        disallowed_tools={"delete_database"}
    )
    engine.register_scope(custom_scope)
    assert engine.check_permission("blacklist_agent", "read_data") is True
    assert engine.check_permission("blacklist_agent", "delete_database") is False
    
    # スコープ未定義のエージェント
    assert engine.check_permission("nonexistent_agent", "any_tool") is True

def test_check_rate_limit():
    engine = GovernanceEngine()
    
    # カスタムスコープで制限を低くしてテストする
    from harness.governance import AgentScope
    limit_scope = AgentScope(
        agent_id="limit_agent",
        agent_name="制限テスト用エージェント",
        description="レート制限の検証",
        max_api_calls=2
    )
    engine.register_scope(limit_scope)
    
    assert engine.check_rate_limit("limit_agent") is True
    assert engine.check_rate_limit("limit_agent") is True
    assert engine.check_rate_limit("limit_agent") is False
    
    # 未定義エージェントの場合
    assert engine.check_rate_limit("nonexistent_agent") is True

def test_span_exceptions_and_events(tmp_path):
    engine = GovernanceEngine(trace_dir=tmp_path)
    
    # add_span_event で無効なスパンIDを指定
    engine.add_span_event("invalid_span_id", "some_event")
    
    # 有効なスパンの開始
    span_id = engine.start_span("op", "tool")
    engine.add_span_event(span_id, "some_event", attributes={"info": "test"})
    
    # end_span で無効なスパンIDを指定
    engine.end_span("invalid_span_id")
    
    # end_span で例外を発生させる検証
    duration = engine._calculate_duration_ms("invalid-time", "2026-05-30T12:00:00")
    assert duration == 0.0
    
    # 正常終了
    engine.end_span(span_id, status="ok", attributes={"result": "success"})
    
    # get_recent_traces の検証
    recent = engine.get_recent_traces(limit=10)
    assert len(recent) == 1
    assert recent[0]["span_id"] == span_id

def test_flush_traces(tmp_path):
    import json
    engine = GovernanceEngine(trace_dir=tmp_path)
    
    # 完了スパンがない状態で flush_traces しても何も書き込まれないこと
    engine.flush_traces(session_id="test_session")
    assert len(list(tmp_path.glob("*.jsonl"))) == 0
    
    # スパンを追加して完了させる
    span_id = engine.start_span("op1", "tool1")
    engine.end_span(span_id, status="ok")
    
    # ディレクトリトラバーサル対策の検証
    filepath = engine._generate_trace_filepath(session_id="..")
    assert filepath.name.startswith("trace_default_")
    
    # flush_traces 実行
    engine.flush_traces(session_id="test_session")
    
    # ファイルが書き込まれたことの検証
    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1
    
    # 書き込み内容の検証
    with open(files[0], "r", encoding="utf-8") as f:
        line = f.readline()
        data = json.loads(line)
        assert data["span_id"] == span_id
        assert data["operation"] == "op1"


def test_check_permission_empty_scope():
    engine = GovernanceEngine()
    from harness.governance import AgentScope
    empty_scope = AgentScope(
        agent_id="empty_agent",
        agent_name="空スコープエージェント",
        description="何もないスコープ"
    )
    engine.register_scope(empty_scope)
    assert engine.check_permission("empty_agent", "any_tool") is True

def test_end_span_invalid_attributes():
    engine = GovernanceEngine()
    span_id = engine.start_span("op", "tool")
    # attributes に update メソッドを持たないオブジェクトを指定して例外を起こす
    engine.end_span(span_id, attributes="not-a-dict")
    # 例外がログ出力され、スパンは正常に完了していること
    recent = engine.get_recent_traces(limit=1)
    assert len(recent) == 1

def test_flush_traces_os_error(tmp_path):
    engine = GovernanceEngine(trace_dir=tmp_path)
    span_id = engine.start_span("op", "tool")
    engine.end_span(span_id)
    
    # トレース保存先をファイルパスにして open で OSError を引き起こす
    # trace_dir をファイルにしてしまう
    dummy_file = tmp_path / "dummy_file"
    with open(dummy_file, "w") as f:
        f.write("")
    engine._trace_dir = dummy_file
    
    # flush_traces は例外をキャッチしてログ出力する
    engine.flush_traces(session_id="error_session")
