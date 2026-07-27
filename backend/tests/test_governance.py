# -*- coding: utf-8 -*-
import json
import pytest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from backend.agents.orchestration import OrchestrationHub
from backend.agents.orchestration import orchestrator
from backend.agents.orchestration.report_compressor import ReportCompressor
from backend.agents.orchestration.directive_applicator import DirectiveApplicator

@pytest.fixture
def mock_governance_paths(tmp_path, monkeypatch):
    base_dir = tmp_path / "orchestration"
    memory_dir = tmp_path / "memory"
    inbox_dir = tmp_path / "inbox"
    base_dir.mkdir(parents=True, exist_ok=True)
    memory_dir.mkdir(parents=True, exist_ok=True)
    inbox_dir.mkdir(parents=True, exist_ok=True)
    
    # model_config.json のダミーファイルを一時フォルダに作成しておく（exists() 回避のため）
    (tmp_path / "backend").mkdir(parents=True, exist_ok=True)
    (tmp_path / "backend" / "model_config.json").touch()

    monkeypatch.setattr(orchestrator, "TASK_QUEUE_PATH", base_dir / "task_queue.json")
    monkeypatch.setattr(orchestrator, "OPUS_DIRECTIVE_PATH", base_dir / "opus_directive.json")
    monkeypatch.setattr(orchestrator, "FLASH_REPORTS_PATH", base_dir / "flash_reports.jsonl")
    monkeypatch.setattr(orchestrator, "MESSAGE_BOX_PATH", base_dir / "message_box.jsonl")
    monkeypatch.setattr(orchestrator, "PHASE_STATE_PATH", memory_dir / "phase_state.json")
    monkeypatch.setattr(orchestrator, "PHASE_GATES_PATH", memory_dir / "phase_gates.json")
    monkeypatch.setattr(orchestrator, "FLASH_SESSION_PATH", base_dir / "flash_session.json")
    monkeypatch.setattr(orchestrator, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(orchestrator, "_PROJECT_ROOT", tmp_path)
    
    from backend.agents.orchestration import generate_subagent_reports
    monkeypatch.setattr(generate_subagent_reports, "OFFICIAL_ARTIFACT_DIR", str(tmp_path / "Human01_Official Artifact"))
    monkeypatch.setattr(generate_subagent_reports, "REPORT_BASE_DIR", str(tmp_path / "Human01_Official Artifact" / "サブエージェント体制報告"))
    monkeypatch.setattr(generate_subagent_reports, "PERIODIC_REPORT_DIR", str(tmp_path / "Human01_Official Artifact" / "サブエージェント体制報告" / "定時レポート"))
    monkeypatch.setattr(generate_subagent_reports, "BULLETIN_REPORT_DIR", str(tmp_path / "Human01_Official Artifact" / "サブエージェント体制報告" / "速報"))
    monkeypatch.setattr(generate_subagent_reports, "RANKING_REPORT_DIR", str(tmp_path / "Human01_Official Artifact" / "サブエージェント体制報告" / "活動ランキング"))
    monkeypatch.setattr(generate_subagent_reports, "TASK_QUEUE_PATH", str(base_dir / "task_queue.json"))
    
    # phase_state のダミーデータ
    state_data = {
        "current_phase": 7,
        "current_milestone": "M7.1",
        "emergency_stop": False,
        "awaiting_opus": False,
        "last_opus_review": None,
        "metrics": {"coverage_pct": 55.0, "test_count": 200, "critical_debt": 0}
    }
    with open(memory_dir / "phase_state.json", "w", encoding="utf-8") as f:
        json.dump(state_data, f)
        
    return base_dir, memory_dir


# -----------------------------------------------------------------------------
# 1. should_trigger_opus_review のテスト
# -----------------------------------------------------------------------------

def test_should_trigger_review_by_time(mock_governance_paths):
    hub = OrchestrationHub()
    
    # 最終レビューが5時間前より前である場合、True
    state = orchestrator._read_json(orchestrator.PHASE_STATE_PATH)
    five_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    state["last_opus_review"] = five_hours_ago
    orchestrator._write_json(orchestrator.PHASE_STATE_PATH, state)
    
    assert hub.should_trigger_opus_review() is True

def test_should_trigger_review_by_failures(mock_governance_paths):
    hub = OrchestrationHub()
    
    # 3連続FAILの場合、True
    state = orchestrator._read_json(orchestrator.PHASE_STATE_PATH)
    state["flash_consecutive_failures"] = 3
    orchestrator._write_json(orchestrator.PHASE_STATE_PATH, state)
    
    assert hub.should_trigger_opus_review() is True

def test_should_trigger_review_by_milestone_done(mock_governance_paths):
    hub = OrchestrationHub()
    
    # マイルストーン全タスク完了（ゲート通過）の場合、True
    # phase_gates.json にゲートを定義
    _, memory_dir = mock_governance_paths
    gates = {"7": {"min_coverage": 55, "max_critical_debt": 0}}
    orchestrator._write_json(orchestrator.PHASE_GATES_PATH, gates)
    
    # タスクキューは空（全タスク完了）
    queue = hub._empty_queue()
    queue["tasks"] = [
        {"id": "T1", "status": "pass", "group": "test_weaver"}
    ]
    orchestrator._write_json(orchestrator.TASK_QUEUE_PATH, queue)
    
    assert hub.should_trigger_opus_review() is True

def test_trigger_review_now(mock_governance_paths):
    hub = OrchestrationHub()
    
    # 手動強制起動 API
    hub.trigger_opus_review_now()
    state = orchestrator._read_json(orchestrator.PHASE_STATE_PATH)
    assert state.get("awaiting_opus") is True
    assert hub.should_trigger_opus_review() is True

# -----------------------------------------------------------------------------
# 2. ReportCompressor のテスト
# -----------------------------------------------------------------------------

def test_report_compressor_basic():
    tasks = [
        {"id": "T1", "status": "pass", "group": "g1", "target_module": "m1"},
        {"id": "T2", "status": "fail", "group": "g2", "target_module": "m2", "report": {"error": "ZeroDivisionError", "traceback": "tb1"}},
        {"id": "T3", "status": "fail", "group": "g2", "target_module": "m2", "report": {"error": "ZeroDivisionError", "traceback": "tb2"}},
        {"id": "T4", "status": "fail", "group": "g3", "target_module": "m3", "report": {"error": "ValueError: invalid", "traceback": "tb3"}},
    ]
    
    compressor = ReportCompressor()
    summary = compressor.compress(tasks)
    
    # 成功率の計算
    assert summary["total"] == 4
    assert summary["passed"] == 1
    assert summary["failed"] == 3
    assert summary["success_rate"] == 25.0
    
    # エラーのクラスタリング（ZeroDivisionError は同一とみなされ、件数は 2 件としてまとまるはず）
    errors = summary["clustered_errors"]
    assert len(errors) == 2
    # ZeroDivisionError が検出される
    zero_err = next(e for e in errors if "ZeroDivisionError" in e["error"])
    assert zero_err["count"] == 2
    assert zero_err["module"] == "m2"

# -----------------------------------------------------------------------------
# 3. DirectiveApplicator のテスト
# -----------------------------------------------------------------------------

def test_directive_applicator_merge(tmp_path):
    prompt_file = tmp_path / "prompt.md"
    prompt_content = """# System Prompt
## Context
Some background...

## Opusからの軌道修正指示
<!-- OPUS_DIRECTIVE_START -->
<!-- OPUS_DIRECTIVE_END -->

## Tasks
Do these tasks...
"""
    prompt_file.write_text(prompt_content, encoding="utf-8")
    
    directive = {
        "priorities": ["Fix caching bugs", "Refactor vector search"],
        "strategy": "Focus on stability over speed"
    }
    
    applicator = DirectiveApplicator(prompt_file)
    success = applicator.apply(directive)
    
    assert success is True
    updated = prompt_file.read_text(encoding="utf-8")
    assert "Fix caching bugs" in updated
    assert "Focus on stability over speed" in updated

def test_directive_applicator_fallback(tmp_path):
    prompt_file = tmp_path / "prompt.md"
    prompt_content = """No placeholders here"""
    prompt_file.write_text(prompt_content, encoding="utf-8")
    
    applicator = DirectiveApplicator(prompt_file)
    # プレースホルダーがない場合は適用失敗しつつ、元のファイルが壊れないこと
    success = applicator.apply({"priorities": []})
    assert success is False
    assert prompt_file.read_text(encoding="utf-8") == "No placeholders here"

def test_report_compressor_empty_error():
    compressor = ReportCompressor()
    assert compressor._normalize_error(None) == "UnknownError"
    assert compressor._normalize_error("") == "UnknownError"

def test_directive_applicator_file_not_found(tmp_path):
    prompt_file = tmp_path / "nonexistent.md"
    applicator = DirectiveApplicator(prompt_file)
    success = applicator.apply({"priorities": []})
    assert success is False

def test_directive_applicator_read_exception(tmp_path):
    # ディレクトリをファイルパスとして渡すことで read_text() を失敗させる
    prompt_dir = tmp_path / "somedir"
    prompt_dir.mkdir()
    applicator = DirectiveApplicator(prompt_dir)
    success = applicator.apply({"priorities": []})
    assert success is False

def test_directive_applicator_write_exception(tmp_path, monkeypatch):
    prompt_file = tmp_path / "prompt.md"
    prompt_content = """<!-- OPUS_DIRECTIVE_START -->
<!-- OPUS_DIRECTIVE_END -->"""
    prompt_file.write_text(prompt_content, encoding="utf-8")
    
    applicator = DirectiveApplicator(prompt_file)
    
    # write_text メソッドをモックして例外を起こす
    def mock_write_text(*args, **kwargs):
        raise IOError("Write failed")
    
    monkeypatch.setattr(Path, "write_text", mock_write_text)
    
    success = applicator.apply({"priorities": ["test"]})
    assert success is False

def test_directive_applicator_empty_directive(tmp_path):
    prompt_file = tmp_path / "prompt.md"
    prompt_content = """<!-- OPUS_DIRECTIVE_START -->
<!-- OPUS_DIRECTIVE_END -->"""
    prompt_file.write_text(prompt_content, encoding="utf-8")
    
    applicator = DirectiveApplicator(prompt_file)
    success = applicator.apply({})
    
    assert success is True
    updated = prompt_file.read_text(encoding="utf-8")
    assert updated == "<!-- OPUS_DIRECTIVE_START -->\n\n<!-- OPUS_DIRECTIVE_END -->"


def test_directive_applicator_only_strategy(tmp_path):
    prompt_file = tmp_path / "prompt.md"
    prompt_content = """<!-- OPUS_DIRECTIVE_START -->
<!-- OPUS_DIRECTIVE_END -->"""
    prompt_file.write_text(prompt_content, encoding="utf-8")
    
    applicator = DirectiveApplicator(prompt_file)
    success = applicator.apply({"strategy": "Focus on stability"})
    
    assert success is True
    updated = prompt_file.read_text(encoding="utf-8")
    assert "- Priorities:" not in updated
    assert "- Strategy: Focus on stability" in updated


def test_directive_applicator_only_priorities(tmp_path):
    prompt_file = tmp_path / "prompt.md"
    prompt_content = """<!-- OPUS_DIRECTIVE_START -->
<!-- OPUS_DIRECTIVE_END -->"""
    prompt_file.write_text(prompt_content, encoding="utf-8")
    
    applicator = DirectiveApplicator(prompt_file)
    success = applicator.apply({"priorities": ["Task A", "Task B"]})
    
    assert success is True
    updated = prompt_file.read_text(encoding="utf-8")
    assert "- Priorities:" in updated
    assert "  - Task A" in updated
    assert "  - Task B" in updated
    assert "- Strategy:" not in updated



def test_generate_daily_digest(mock_governance_paths, monkeypatch):
    base_dir, memory_dir = mock_governance_paths
    hub = OrchestrationHub()

    # flash_session.json のモックデータ
    session_data = {
        "session_started_at": "2026-05-21T08:00:00Z",
        "batches_in_session": 3,
        "recent_errors": [
            {"timestamp": "2026-05-21T09:00:00Z", "module": "backend/api.py", "error": "ValueError: connection timeout"},
            {"timestamp": "2026-05-21T09:10:00Z", "module": "backend/api.py", "error": "ValueError: connection timeout"},
            {"timestamp": "2026-05-21T09:20:00Z", "module": "backend/utils.py", "error": "KeyError: 'db'"}
        ]
    }
    with open(base_dir / "flash_session.json", "w", encoding="utf-8") as f:
        json.dump(session_data, f)

    # flash_reports.jsonl のモックデータ（本日分）
    today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    report_data = [
        {"timestamp": f"{today_str}T08:30:00Z", "results": {"passed": 5, "failed": 1}},
        {"timestamp": f"{today_str}T09:30:00Z", "results": {"passed": 3, "failed": 1}}
    ]
    with open(base_dir / "flash_reports.jsonl", "w", encoding="utf-8") as f:
        for r in report_data:
            f.write(json.dumps(r) + "\n")

    # generate_daily_digest の実行
    filepath = hub.generate_daily_digest()
    
    # 検証
    assert filepath.exists()
    content = filepath.read_text(encoding="utf-8")
    assert "デイリーダイジェスト" in content
    assert "ValueError: connection timeout (件数: 2回)" in content
    assert "KeyError: 'db' (件数: 1回)" in content


def test_generate_hourly_report(mock_governance_paths, monkeypatch):
    base_dir, memory_dir = mock_governance_paths
    hub = OrchestrationHub()

    # task_queue.json のモックデータ
    queue_data = {
        "tasks": [
            {"id": "T1", "group": "test_weaver", "target_module": "backend/safe_io.py", "status": "pass", "report": {"message": "All passed", "changed_files": ["backend/safe_io.py"]}},
            {"id": "T2", "group": "bug_hunter", "target_module": "backend/wagamama_manager.py", "status": "fail", "report": {"error": "IndexError: out of range", "changed_files": []}},
            {"id": "T3", "group": "bug_hunter", "target_module": "backend/wagamama_manager.py", "status": "fail", "report": {"error": "IndexError: out of range", "changed_files": []}},
        ]
    }
    with open(base_dir / "task_queue.json", "w", encoding="utf-8") as f:
        json.dump(queue_data, f)

    # flash_session.json のモックデータ
    session_data = {
        "session_started_at": "2026-05-21T08:00:00Z",
        "batches_in_session": 1,
        "recent_errors": []
    }
    with open(base_dir / "flash_session.json", "w", encoding="utf-8") as f:
        json.dump(session_data, f)

    # flash_reports.jsonl のモックデータ（1時間前以内）
    now = datetime.now(timezone.utc)
    recent_time_str = (now - timedelta(minutes=10)).isoformat(timespec="seconds")
    report_data = [
        {"timestamp": recent_time_str, "results": {"passed": 1, "failed": 2}}
    ]
    with open(base_dir / "flash_reports.jsonl", "w", encoding="utf-8") as f:
        for r in report_data:
            f.write(json.dumps(r) + "\n")

    # subprocess.run をモック化してダミーの git log と git diff を返す
    import subprocess
    class MockCompletedProcess:
        def __init__(self, stdout):
            self.stdout = stdout
            self.returncode = 0

    def mock_run(cmd, *args, **kwargs):
        cmd_str = " ".join(cmd)
        if "log" in cmd_str and "--stat" in cmd_str:
            stat_out = (
                "a44d528 2026-05-21 08:30:15 +0900 [M7.1] test_weaver: add tests\n"
                " backend/safe_io.py | 12 +++--\n"
                " 1 file changed, 8 insertions(+), 4 deletions(-)\n"
            )
            return MockCompletedProcess(stat_out)
        elif "log" in cmd_str and "--oneline" in cmd_str:
            return MockCompletedProcess("a44d528 [M7.1] test_weaver: add tests")
        elif "diff" in cmd_str:
            return MockCompletedProcess(" backend/safe_io.py | 2 +-")
        return MockCompletedProcess("")

    monkeypatch.setattr(subprocess, "run", mock_run)

    # generate_hourly_report の実行
    filepath = hub.generate_hourly_report()

    # 検証
    assert filepath.exists()
    content = filepath.read_text(encoding="utf-8")
    assert "1時間セッションレポート" in content
    assert "「wagamama_manager.py」FAIL (件数: 2回)" in content
    assert "IndexError: out of range" in content


def test_should_trigger_review_no_state_file(mock_governance_paths):
    base_dir, memory_dir = mock_governance_paths
    hub = OrchestrationHub()
    
    import os
    state_file = memory_dir / "phase_state.json"
    if state_file.exists():
        os.remove(state_file)
        
    assert hub.should_trigger_opus_review() is False


def test_should_trigger_review_invalid_time_format(mock_governance_paths):
    hub = OrchestrationHub()
    state = orchestrator._read_json(orchestrator.PHASE_STATE_PATH)
    state["last_opus_review"] = "invalid-date-string"
    orchestrator._write_json(orchestrator.PHASE_STATE_PATH, state)
    
    assert hub.should_trigger_opus_review() is False


def test_should_trigger_review_by_many_failures(mock_governance_paths):
    hub = OrchestrationHub()
    state = orchestrator._read_json(orchestrator.PHASE_STATE_PATH)
    state["flash_tasks_failed"] = 5
    orchestrator._write_json(orchestrator.PHASE_STATE_PATH, state)
    
    assert hub.should_trigger_opus_review() is True


def test_should_trigger_review_all_false(mock_governance_paths):
    hub = OrchestrationHub()
    state = orchestrator._read_json(orchestrator.PHASE_STATE_PATH)
    state["last_opus_review"] = datetime.now(timezone.utc).isoformat()
    state["flash_consecutive_failures"] = 0
    state["flash_tasks_failed"] = 0
    orchestrator._write_json(orchestrator.PHASE_STATE_PATH, state)
    
    queue = hub._empty_queue()
    queue["tasks"] = [
        {"id": "T1", "status": "pending", "group": "test_weaver"}
    ]
    orchestrator._write_json(orchestrator.TASK_QUEUE_PATH, queue)
    
    assert hub.should_trigger_opus_review() is False


def test_get_current_directive(mock_governance_paths):
    hub = OrchestrationHub()
    
    directive_data = {"directive_id": "D1", "content": "test"}
    orchestrator._write_json(orchestrator.OPUS_DIRECTIVE_PATH, directive_data)
    d = hub.get_current_directive()
    assert d is not None
    assert d.get("directive_id") == "D1"
    
    orchestrator._write_json(orchestrator.OPUS_DIRECTIVE_PATH, {})
    assert hub.get_current_directive() is None






# -----------------------------------------------------------------------------
# 4. ReportCompressor 追加の境界値・エッジケーステスト
# -----------------------------------------------------------------------------

def test_report_compressor_empty_and_edge():
    compressor = ReportCompressor()
    
    # 空のタスクリスト
    summary = compressor.compress([])
    assert summary["total"] == 0
    assert summary["passed"] == 0
    assert summary["failed"] == 0
    assert summary["success_rate"] == 0.0
    assert summary["clustered_errors"] == []
    
    # すべて成功
    tasks_all_pass = [
        {"id": "T1", "status": "pass", "group": "g1", "target_module": "m1"},
        {"id": "T2", "status": "pass", "group": "g2", "target_module": "m2"}
    ]
    summary_all_pass = compressor.compress(tasks_all_pass)
    assert summary_all_pass["total"] == 2
    assert summary_all_pass["passed"] == 2
    assert summary_all_pass["failed"] == 0
    assert summary_all_pass["success_rate"] == 100.0
    assert summary_all_pass["clustered_errors"] == []

def test_report_compressor_normalize_patterns():
    compressor = ReportCompressor()
    
    # None と 空文字列
    assert compressor._normalize_error(None) == "UnknownError"
    assert compressor._normalize_error("") == "UnknownError"
    
    # 複数行のエラー
    multiline = "ValueError: something went wrong\n  File \"app.py\", line 10\n    x = 1/0"
    assert compressor._normalize_error(multiline) == "ValueError: something went wrong"
    
    # メモリ番地の置換
    mem_err = "Error at address 0x7f83e20bf3a0 and 0x5F"
    assert compressor._normalize_error(mem_err) == "Error at address 0x... and 0x..."
    
    # 単独数値の置換
    num_err = "Timeout after 30 seconds with 5 retries"
    assert compressor._normalize_error(num_err) == "Timeout after N seconds with N retries"
    
    # パス表記の置換
    path_err_unix = "Failed to load /home/user/src/module.py"
    path_err_win = "Failed to load C:\\Users\\User\\src\\module.py"
    assert compressor._normalize_error(path_err_unix) == "Failed to load file.py"
    assert compressor._normalize_error(path_err_win) == "Failed to load C:file.py"
    
    # 複合パターン
    complex_err = "Error in /path/to/main.py at 0x7f83e20: Division by 0 on line 42"
    assert compressor._normalize_error(complex_err) == "Error in file.py at 0x...: Division by N on line N"

def test_report_compressor_report_edge_cases():
    compressor = ReportCompressor()
    
    # reportキーなし、target_moduleキーなし
    tasks = [
        {"id": "T1", "status": "fail"}
    ]
    summary = compressor.compress(tasks)
    assert len(summary["clustered_errors"]) == 1
    err = summary["clustered_errors"][0]
    assert err["error"] == "Unknown error occurred"
    assert err["count"] == 1
    assert err["module"] == "unknown"
    assert err["sample_traceback"] == ""
    
    # reportが空辞書
    tasks_empty_report = [
        {"id": "T1", "status": "fail", "report": {}}
    ]
    summary_empty = compressor.compress(tasks_empty_report)
    assert summary_empty["clustered_errors"][0]["error"] == "Unknown error occurred"
    
    # errorがなくmessageがある場合
    tasks_msg_only = [
        {"id": "T1", "status": "fail", "report": {"message": "Custom message"}}
    ]
    summary_msg = compressor.compress(tasks_msg_only)
    assert summary_msg["clustered_errors"][0]["error"] == "Custom message"
    
    # 長いtracebackの切り詰め
    long_tb = "x" * 500
    tasks_long_tb = [
        {"id": "T1", "status": "fail", "report": {"error": "Fail", "traceback": long_tb}}
    ]
    summary_long_tb = compressor.compress(tasks_long_tb)
    sample_tb = summary_long_tb["clustered_errors"][0]["sample_traceback"]
    assert len(sample_tb) == 300
    assert sample_tb == "x" * 300


# -----------------------------------------------------------------------------
# 5. TokenLimiter のテスト
# -----------------------------------------------------------------------------

def test_token_limiter_import_error(monkeypatch):
    import sys
    import importlib
    
    # sys.modules から tiktoken を隠す
    monkeypatch.setitem(sys.modules, "tiktoken", None)
    
    # モジュールをリロードして ImportError を発生させる
    import backend.agents.orchestration.token_limiter
    importlib.reload(backend.agents.orchestration.token_limiter)
    
    assert backend.agents.orchestration.token_limiter.HAS_TIKTOKEN is False
    
    # テストが終わったら元に戻すためにリロードする
    monkeypatch.delitem(sys.modules, "tiktoken")
    importlib.reload(backend.agents.orchestration.token_limiter)

def test_token_limiter_count_tokens(monkeypatch):
    import backend.agents.orchestration.token_limiter as tl
    from backend.agents.orchestration.token_limiter import TokenLimiter
    limiter = TokenLimiter()
    
    # 空テキスト
    assert limiter.count_tokens("") == 0
    assert limiter.count_tokens(None) == 0

    # 通常カウント
    text = "hello world, this is a longer text to test token counting"
    cnt_normal = limiter.count_tokens(text)

    # tiktoken がない場合のフォールバックのシミュレーション
    monkeypatch.setattr(tl, "HAS_TIKTOKEN", False)
    cnt_fallback = limiter.count_tokens(text)
    assert cnt_fallback == len(text) // 4

    # tiktoken で例外が発生した場合のフォールバック
    monkeypatch.setattr(tl, "HAS_TIKTOKEN", True)
    def mock_get_encoding(name):
        raise ValueError("Mock tiktoken error")
    monkeypatch.setattr(tl.tiktoken, "get_encoding", mock_get_encoding)
    
    cnt_exception = limiter.count_tokens(text)
    assert cnt_exception == len(text) // 4

def test_token_limiter_trim_context():
    from backend.agents.orchestration.token_limiter import TokenLimiter
    limiter = TokenLimiter(max_tokens=10)

    # 上限以内のテキスト
    text = "Short text."
    assert limiter.trim_context(text) == text

    # 上限を超えるテキスト (リスト行を含む)
    text_long = (
        "Header information\n"
        "- Item 1 (old history)\n"
        "- Item 2 (medium history)\n"
        "- Item 3 (new history)\n"
        "Footer info"
    )
    trimmed = limiter.trim_context(text_long, max_tokens=12)
    assert "- Item 1" not in trimmed
    assert "Header information" in trimmed
    
    # リスト行を全部削っても上限を超える場合
    text_huge = "A" * 200
    trimmed_huge = limiter.trim_context(text_huge, max_tokens=5)
    assert trimmed_huge == ""

    # 複数行があり、リスト行ではないが上限を超える場合
    text_lines = "\n".join(["Line " + str(i) for i in range(20)])
    trimmed_lines = limiter.trim_context(text_lines, max_tokens=5)
    assert "Line 19" in trimmed_lines
    assert "Line 0" not in trimmed_lines

    # 混在テキスト: リスト行を全削除しても上限を超えるが、通常行を削除することで上限以下になる
    # ループ内の continue 分岐を通すためのテスト
    text_mixed = (
        "Normal Line 1\n"
        "- List Line 1\n"
        "Normal Line 2\n"
        "- List Line 2"
    )
    # tiktoken なしでカウントすると len(text_mixed) // 4 = 11 トークン
    # リスト行を全削除した temp_text は "Normal Line 1\nNormal Line 2" (26文字) -> 6 トークン
    # max_tokens=5 とすると、リスト行全削除(6)でも上限を超えるため、通常行の削除ループに入り、
    # i=1 (List Line 1) のときに continue を通る
    limiter_fallback = TokenLimiter(max_tokens=5)
    import backend.agents.orchestration.token_limiter
    backend.agents.orchestration.token_limiter.HAS_TIKTOKEN = False
    trimmed_mixed = limiter_fallback.trim_context(text_mixed)
    assert trimmed_mixed != ""

    # 極限フォールバックの return "" を通すためのテスト (max_tokens=-1)
    trimmed_neg = limiter_fallback.trim_context(text_mixed, max_tokens=-1)
    assert trimmed_neg == ""

    # モジュールの状態を復元
    importlib = __import__("importlib")
    importlib.reload(backend.agents.orchestration.token_limiter)


def test_start_opus_review_no_week_start(mock_governance_paths):
    hub = OrchestrationHub()
    state = orchestrator._read_json(orchestrator.PHASE_STATE_PATH)
    if "opus_week_start" in state:
        del state["opus_week_start"]
    state["opus_hours_used_this_week"] = 1.0
    orchestrator._write_json(orchestrator.PHASE_STATE_PATH, state)

    hub.start_opus_review(predicted_hours=1.0)
    
    updated = orchestrator._read_json(orchestrator.PHASE_STATE_PATH)
    assert updated["opus_week_start"] is not None
    assert updated["opus_hours_used_this_week"] == 0.0



# -----------------------------------------------------------------------------
# 6. start_opus_review / end_opus_review のテスト
# -----------------------------------------------------------------------------

def test_start_opus_review_normal(mock_governance_paths):
    hub = OrchestrationHub()
    
    # 初期状態
    state = orchestrator._read_json(orchestrator.PHASE_STATE_PATH)
    state["opus_hours_used_this_week"] = 1.0
    state["opus_week_start"] = datetime.now(timezone.utc).isoformat()
    orchestrator._write_json(orchestrator.PHASE_STATE_PATH, state)

    hub.start_opus_review(predicted_hours=1.0)
    
    updated = orchestrator._read_json(orchestrator.PHASE_STATE_PATH)
    assert updated["awaiting_opus"] is True
    assert updated["opus_hours_used_this_week"] == 1.0

def test_start_opus_review_reset_after_7days(mock_governance_paths):
    hub = OrchestrationHub()
    
    # 8日前の開始時刻をセット
    state = orchestrator._read_json(orchestrator.PHASE_STATE_PATH)
    state["opus_hours_used_this_week"] = 4.5
    state["opus_reviews_this_week"] = 10
    eight_days_ago = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    state["opus_week_start"] = eight_days_ago
    orchestrator._write_json(orchestrator.PHASE_STATE_PATH, state)

    hub.start_opus_review(predicted_hours=0.5)

    updated = orchestrator._read_json(orchestrator.PHASE_STATE_PATH)
    assert updated["opus_hours_used_this_week"] == 0.0
    assert updated["opus_reviews_this_week"] == 0
    assert updated["opus_week_start"] != eight_days_ago

def test_start_opus_review_invalid_week_start(mock_governance_paths):
    hub = OrchestrationHub()
    
    state = orchestrator._read_json(orchestrator.PHASE_STATE_PATH)
    state["opus_hours_used_this_week"] = 2.0
    state["opus_week_start"] = "invalid-date-string"
    orchestrator._write_json(orchestrator.PHASE_STATE_PATH, state)

    hub.start_opus_review()

    updated = orchestrator._read_json(orchestrator.PHASE_STATE_PATH)
    assert updated["opus_hours_used_this_week"] == 0.0

def test_start_opus_review_quota_exceeded(mock_governance_paths):
    from backend.agents.orchestration.orchestrator import OpusQuotaExceededException
    hub = OrchestrationHub()
    
    state = orchestrator._read_json(orchestrator.PHASE_STATE_PATH)
    state["opus_hours_used_this_week"] = 4.8
    state["opus_week_start"] = datetime.now(timezone.utc).isoformat()
    orchestrator._write_json(orchestrator.PHASE_STATE_PATH, state)

    with pytest.raises(OpusQuotaExceededException) as exc_info:
        hub.start_opus_review(predicted_hours=0.3)
    
    assert "Opus週時間制限を超過しました" in str(exc_info.value)

    state["opus_hours_used_this_week"] = 5.0
    orchestrator._write_json(orchestrator.PHASE_STATE_PATH, state)
    with pytest.raises(OpusQuotaExceededException):
        hub.start_opus_review(predicted_hours=0.0)

def test_end_opus_review(mock_governance_paths):
    hub = OrchestrationHub()
    
    state = orchestrator._read_json(orchestrator.PHASE_STATE_PATH)
    state["opus_hours_used_this_week"] = 1.0
    state["opus_reviews_this_week"] = 2
    state["awaiting_opus"] = True
    orchestrator._write_json(orchestrator.PHASE_STATE_PATH, state)

    hub.end_opus_review(duration_seconds=1800.0)

    updated = orchestrator._read_json(orchestrator.PHASE_STATE_PATH)
    assert updated["opus_hours_used_this_week"] == 1.5
    assert updated["opus_reviews_this_week"] == 3
    assert updated["awaiting_opus"] is False
    assert updated["last_opus_review"] is not None

def test_governance_no_state_file(mock_governance_paths):
    import os
    hub = OrchestrationHub()
    
    if orchestrator.PHASE_STATE_PATH.exists():
        os.remove(orchestrator.PHASE_STATE_PATH)

    hub.start_opus_review()
    hub.end_opus_review(100.0)

def test_report_compressor_agent_response():
    compressor = ReportCompressor()
    
    # 1. 空の応答
    assert compressor.compress_agent_response("", task_id="T1") == "[T1] 応答なし"
    assert compressor.compress_agent_response(None, task_id="T1") == "[T1] 応答なし"
    
    # 2. 短い応答
    short_resp = "SUCCESS: refactoring done."
    assert compressor.compress_agent_response(short_resp, task_id="T2") == short_resp
    
    # 3. 長い応答 (MAX_SUMMARY_CHARS: 400文字を超える)
    # ステータスインジケータを含む行、変更ファイル
    long_status = "✅ Task completed successfully.\n" + "Dummy line\n" * 100
    res = compressor.compress_agent_response(long_status, task_id="T3", modified_files=["file1.py", "file2.py"])
    assert "[T3] ✅ Task completed successfully." in res
    assert "変更: file1.py, file2.py" in res
    
    # 4. 長い応答でステータス行が複数（3行以上）
    status_heavy = "✅ Line 1\n❌ Line 2\nPASS Line 3\nFAIL Line 4\n" + "Dummy\n" * 100
    res_heavy = compressor.compress_agent_response(status_heavy, task_id="T4")
    assert "✅ Line 1 | ❌ Line 2 | PASS Line 3" in res_heavy
    assert "FAIL Line 4" not in res_heavy # 3行制限
    
    # 5. 長い応答でステータスも変更ファイルもなし (フォールバック)
    fallback_resp = "Start of response\n" + "Dummy line\n" * 100 + "End of response"
    res_fallback = compressor.compress_agent_response(fallback_resp, task_id="T5")
    assert res_fallback.startswith("[T5] Start of response")
    assert "End of" in res_fallback
    
    # 6. 変更ファイルが多数（5件超）
    many_files = [f"file_{i}.py" for i in range(10)]
    res_files = compressor.compress_agent_response("✅ done\n" + "Dummy\n" * 100, task_id="T6", modified_files=many_files)
    assert "変更: file_0.py, file_1.py, file_2.py, file_3.py, file_4.py (+5件)" in res_files

def test_report_compressor_test_output():
    compressor = ReportCompressor()
    
    # 1. 空の出力
    assert compressor.compress_test_output("") == "テスト出力なし"
    assert compressor.compress_test_output(None) == "テスト出力なし"
    
    # 2. 短い出力
    assert compressor.compress_test_output("PASSED") == "PASSED"
    
    # 3. pytest サマリー行の抽出
    output_with_summary = "running tests...\n" + "passed line\n" * 100 + "=== 10 passed, 1 failed in 2.5s ==="
    res = compressor.compress_test_output(output_with_summary)
    assert "=== 10 passed, 1 failed in 2.5s ===" in res
    
    # 4. FAILED行の抽出
    output_failed = "running tests...\nFAILED test_foo.py::test_bar\n" + "passed line\n" * 100
    res_failed = compressor.compress_test_output(output_failed)
    assert "FAILED: FAILED test_foo.py::test_bar" in res_failed
    
    # 5. ERROR行の抽出 (FAILEDなし)
    output_error = "running tests...\nERROR: something crashed\n" + "passed line\n" * 100
    res_error = compressor.compress_test_output(output_error)
    assert "ERROR: ERROR: something crashed" in res_error
    
    # 6. サマリー/FAILED/ERRORなしのフォールバック
    output_fallback = "line 1\nline 2\n" + "dummy\n" * 100 + "fallback_last_line"
    res_fallback = compressor.compress_test_output(output_fallback)
    assert "fallback_last_line" in res_fallback

def test_report_compressor_traceback_edge_cases():
    compressor = ReportCompressor()
    
    # 1. 空のトレースバック
    assert compressor.compress_traceback("") == ""
    assert compressor.compress_traceback(None) == ""
    
    # 2. 5行超かつ300文字超のトレースバック
    long_traceback = "\n".join(["error line " + str(i) + " " + "x"*50 for i in range(10)])
    res = compressor.compress_traceback(long_traceback)
    assert "...(5行省略)" in res
    assert len(res) <= 300

