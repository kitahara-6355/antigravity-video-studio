import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import json
import uuid
from datetime import datetime, timezone, timedelta
import subprocess

import backend.agents.orchestration.orchestrator as orchestrator
from backend.agents.orchestration.orchestrator import (
    OrchestrationHub,
    _safe_parse_iso,
    _read_json,
    _write_json,
    _append_jsonl,
    _read_jsonl,
    _now_iso,
    OpusQuotaExceededException
)

_ORIGINAL_GIT_AUTO_COMMIT = OrchestrationHub._git_auto_commit

# 各パスを pytest の tmp_path で差し替える fixture
@pytest.fixture(autouse=True)
def mock_paths(tmp_path):
    t_base = tmp_path / "orchestration"
    t_memory = tmp_path / "memory"
    t_inbox = tmp_path / "inbox"
    
    t_base.mkdir(parents=True, exist_ok=True)
    t_memory.mkdir(parents=True, exist_ok=True)
    t_inbox.mkdir(parents=True, exist_ok=True)
    
    import sys
    orchestration_names = ["hub_common", "orchestrator", "hub_batch", "hub_gate", "hub_reports", "hub_session", "hub_status", "convergence_loop"]
    for name, module in list(sys.modules.items()):
        matching_names = [on for on in orchestration_names if name.endswith(on) or name == on]
        if matching_names and module:
            setattr(module, "TASK_QUEUE_PATH", t_base / "task_queue.json")
            setattr(module, "OPUS_DIRECTIVE_PATH", t_base / "opus_directive.json")
            setattr(module, "FLASH_REPORTS_PATH", t_base / "flash_reports.jsonl")
            setattr(module, "MESSAGE_BOX_PATH", t_base / "message_box.jsonl")
            setattr(module, "PHASE_STATE_PATH", t_memory / "phase_state.json")
            setattr(module, "PHASE_GATES_PATH", t_memory / "phase_gates.json")
            setattr(module, "FLASH_SESSION_PATH", t_base / "flash_session.json")
            setattr(module, "DESIGN_STOCK_PATH", t_base / "design_stock.json")
            setattr(module, "INBOX_DIR", t_inbox)
            setattr(module, "MODULE_INDEX_PATH", t_base / "module_index.json")
            setattr(module, "_MEMORY_DIR", t_memory)
            setattr(module, "_PROJECT_ROOT", tmp_path)
        
    with patch("backend.harness.governance.governance_engine.validate_batch_quality") as mock_val, \
         patch.object(OrchestrationHub, "_auto_measure_coverage") as mock_cov, \
         patch.object(OrchestrationHub, "_git_auto_commit") as mock_git:
        yield


def test_safe_parse_iso():
    assert _safe_parse_iso(None) is None
    assert _safe_parse_iso("") is None
    assert _safe_parse_iso("invalid-date") is None
    
    # 正常系
    dt = _safe_parse_iso("2026-05-28T22:12:15Z")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 5
    assert dt.day == 28
    assert dt.hour == 22
    assert dt.tzinfo == timezone.utc

    # タイムゾーンオフセット指定
    dt2 = _safe_parse_iso("2026-05-28T22:12:15+09:00")
    assert dt2 is not None
    assert dt2.tzinfo == timezone(timedelta(hours=9))


def test_read_write_json(tmp_path):
    test_file = tmp_path / "test.json"
    
    # 存在しないファイル
    assert _read_json(test_file) == {}
    
    # 正常書き込みと読み込み
    data = {"key": "value"}
    _write_json(test_file, data)
    assert _read_json(test_file) == data
    
    # JSON破損時のフォールバック
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("{invalid json")
    assert _read_json(test_file) == {}

    # OSErrorのフォールバック
    with patch("builtins.open", side_effect=OSError("Permission denied")):
        assert _read_json(test_file) == {}

    # _write_json の OSError
    with patch("builtins.open", side_effect=OSError("Read-only file system")):
        with pytest.raises(OSError):
            _write_json(test_file, {"key": "val"})


def test_jsonl_operations(tmp_path):
    test_file = tmp_path / "test.jsonl"
    
    # 存在しないファイル
    assert _read_jsonl(test_file) == []
    
    # 追記
    rec1 = {"id": 1, "msg": "hello"}
    _append_jsonl(test_file, rec1)
    assert _read_jsonl(test_file) == [rec1]
    
    # 複数追記と一部破損行のスキップ
    rec2 = {"id": 2, "msg": "world"}
    _append_jsonl(test_file, rec2)
    
    # 手動で壊れた行を挿入
    with open(test_file, "a", encoding="utf-8") as f:
        f.write("invalid_json_line\n")
    
    rec3 = {"id": 3, "msg": "end"}
    _append_jsonl(test_file, rec3)
    
    # 破損行はスキップされる
    records = _read_jsonl(test_file)
    assert len(records) == 3
    assert records[0] == rec1
    assert records[1] == rec2
    assert records[2] == rec3


def test_jsonl_rotation(tmp_path):
    test_file = tmp_path / "rotate.jsonl"
    
    # 1005行追記してローテーションを発動させる
    for i in range(1005):
        _append_jsonl(test_file, {"num": i})
        
    # 元ファイルは最新の1000行になるはず
    records = _read_jsonl(test_file)
    assert len(records) == 1000
    assert records[0]["num"] == 5
    assert records[-1]["num"] == 1004
    
    # アーカイブファイルが作成されているはず
    archives = list(tmp_path.glob("rotate.archive.*.jsonl"))
    assert len(archives) == 1
    archive_records = _read_jsonl(archives[0])
    assert len(archive_records) == 5
    assert archive_records[0]["num"] == 0
    assert archive_records[-1]["num"] == 4

    # ローテーションでエラーが発生した場合のサイレントガードのテスト
    with patch("builtins.open", side_effect=OSError("Disk full")):
        # 例外が伝播せずにサイレント終了する
        orchestrator._rotate_jsonl_if_needed(test_file, max_lines=500)


def test_ensure_files_exist_initialization():
    # fixtureにより全ファイルがtmp_pathにマッピングされている
    hub = OrchestrationHub()
    
    # ファイルが作成されたか確認
    assert orchestrator.TASK_QUEUE_PATH.exists()
    assert orchestrator.OPUS_DIRECTIVE_PATH.exists()
    assert orchestrator.FLASH_REPORTS_PATH.exists()
    assert orchestrator.MESSAGE_BOX_PATH.exists()
    assert orchestrator.FLASH_SESSION_PATH.exists()
    assert orchestrator.PHASE_GATES_PATH.exists()
    
    # 各ファイルのデフォルト値の検証
    session = _read_json(orchestrator.FLASH_SESSION_PATH)
    assert session["status"] == "not_started"
    
    directive = _read_json(orchestrator.OPUS_DIRECTIVE_PATH)
    assert directive["resume"] is True


def test_calculate_dynamic_limit():
    hub = OrchestrationHub()
    
    # エラーがない場合
    session = {}
    assert hub._calculate_dynamic_limit(session) == 15
    
    # 429以外のエラー
    now_str = datetime.now(timezone.utc).isoformat()
    session = {
        "recent_errors": [
            {"timestamp": now_str, "error": "Connection Timeout"}
        ]
    }
    assert hub._calculate_dynamic_limit(session) == 15
    
    # 直近の429エラー
    session = {
        "recent_errors": [
            {"timestamp": now_str, "error": "429: RESOURCE_EXHAUSTED"}
        ]
    }
    assert hub._calculate_dynamic_limit(session) == 2
    
    # 10分以上前の429エラー
    old_time = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat()
    session = {
        "recent_errors": [
            {"timestamp": old_time, "error": "429: Resource Exhausted"}
        ]
    }
    assert hub._calculate_dynamic_limit(session) == 15

    # KeyErrorが発生する不正なエラー辞書
    session = {
        "recent_errors": [
            {"error": "429"}  # timestampがない
        ]
    }
    assert hub._calculate_dynamic_limit(session) == 15


def test_recover_timed_out_tasks():
    hub = OrchestrationHub()
    
    now = datetime.now(timezone.utc)
    stale_time = (now - timedelta(minutes=31)).isoformat()
    fresh_time = (now - timedelta(minutes=10)).isoformat()
    
    queue = {
        "tasks": [
            # タイムアウトしたL1タスク -> リトライカウント+1, status=pending
            {"id": "T-1", "level": "L1", "status": "running", "started_at": stale_time, "retry_count": 0},
            # タイムアウトしたL2タスクでリトライ限界未満 -> status=pending
            {"id": "T-2", "level": "L2", "status": "running", "started_at": stale_time, "retry_count": 1},
            # タイムアウトしたL2タスクでリトライ限界到達 -> status=skip
            {"id": "T-3", "level": "L2", "status": "running", "started_at": stale_time, "retry_count": 2},
            # タイムアウトしていないタスク -> 変化なし
            {"id": "T-4", "level": "L1", "status": "running", "started_at": fresh_time, "retry_count": 0},
            # started_at がないタスク -> started_atがセットされる
            {"id": "T-5", "level": "L1", "status": "running", "retry_count": 0},
            # started_at が不正な形式 -> started_atがリセットされる
            {"id": "T-6", "level": "L1", "status": "running", "started_at": "invalid-date", "retry_count": 0},
        ]
    }
    _write_json(orchestrator.TASK_QUEUE_PATH, queue)
    
    hub._recover_timed_out_tasks(queue, timeout_seconds=1800)
    
    tasks = {t["id"]: t for t in queue["tasks"]}
    
    assert tasks["T-1"]["status"] == "pending"
    assert tasks["T-1"]["started_at"] is None
    assert tasks["T-1"]["retry_count"] == 1
    
    assert tasks["T-2"]["status"] == "pending"
    assert tasks["T-2"]["retry_count"] == 2
    
    assert tasks["T-3"]["status"] == "skip"
    assert "MAX_RETRIES_EXCEEDED" in tasks["T-3"]["result"]["error"]
    
    assert tasks["T-4"]["status"] == "running"
    assert tasks["T-5"]["started_at"] is not None
    assert tasks["T-6"]["started_at"] is not None


def test_mark_task_done_success():
    hub = OrchestrationHub()
    
    # ダミーのタスクキューを準備
    queue = {
        "tasks": [
            {"id": "T-1", "status": "running", "started_at": _now_iso(), "target_module": "backend/services/vector.py"},
            {"id": "T-2", "status": "running", "started_at": _now_iso(), "target_module": "backend/routers/smartcut.py"}
        ]
    }
    _write_json(orchestrator.TASK_QUEUE_PATH, queue)
    
    state = {
        "flash_consecutive_failures": 3,
        "flash_batches_completed": 0,
        "metrics": {"coverage_pct": 50, "test_count": 100, "critical_debt": 2}
    }
    _write_json(orchestrator.PHASE_STATE_PATH, state)
    
    # タスク成功を記録
    hub.mark_task_done("T-1", result="pass", report={"message": "All green", "changed_files": ["backend/services/vector.py"]})
    
    new_queue = _read_json(orchestrator.TASK_QUEUE_PATH)
    t1 = next(t for t in new_queue["tasks"] if t["id"] == "T-1")
    assert t1["status"] == "pass"
    assert t1["result"]["message"] == "All green"
    
    # 連続失敗がリセットされているはず
    new_state = _read_json(orchestrator.PHASE_STATE_PATH)
    assert new_state["flash_consecutive_failures"] == 0


def test_mark_task_done_fail():
    hub = OrchestrationHub()
    
    queue = {
        "tasks": [
            {"id": "T-2", "status": "running", "started_at": _now_iso(), "target_module": "backend/routers/smartcut.py"}
        ]
    }
    _write_json(orchestrator.TASK_QUEUE_PATH, queue)
    
    state = {
        "flash_consecutive_failures": 0,
        "flash_batches_completed": 0,
        "metrics": {"coverage_pct": 50, "test_count": 100, "critical_debt": 2}
    }
    _write_json(orchestrator.PHASE_STATE_PATH, state)
    
    # タスク失敗を記録 (consecutive failure の増加)
    hub.mark_task_done("T-2", result="fail", report={"error": "SyntaxError", "traceback": "Traceback info"})
    
    new_state = _read_json(orchestrator.PHASE_STATE_PATH)
    assert new_state["flash_consecutive_failures"] == 1
    
    # デバッグレポートが inbox に作成されているか
    inbox_files = list(orchestrator.INBOX_DIR.glob("error_*_T-2.md"))
    assert len(inbox_files) == 1
    report_content = inbox_files[0].read_text(encoding="utf-8")
    assert "SyntaxError" in report_content
    assert "Traceback info" in report_content


def test_mark_task_done_not_found_and_coverage_update():
    hub = OrchestrationHub()
    
    queue = {"tasks": []}
    _write_json(orchestrator.TASK_QUEUE_PATH, queue)
    
    state = {
        "metrics": {"coverage_pct": 50, "test_count": 100, "critical_debt": 2}
    }
    _write_json(orchestrator.PHASE_STATE_PATH, state)
    
    # 存在しないタスク
    hub.mark_task_done("T-NONE", result="pass")
    
    # カバレッジとテスト数の更新検証
    hub.update_phase_state({"metrics": {"coverage_pct": 55, "test_count": 105, "critical_debt": 1}})
    new_state = _read_json(orchestrator.PHASE_STATE_PATH)
    assert new_state["metrics"]["coverage_pct"] == 55
    assert new_state["metrics"]["test_count"] == 105
    assert new_state["metrics"]["critical_debt"] == 1


def test_get_next_batch_cooldown():
    hub = OrchestrationHub()
    
    # 1分以内に 429 エラーがある場合、クールダウンにより空バッチを返す
    now_str = datetime.now(timezone.utc).isoformat()
    session = {
        "status": "running",
        "recent_errors": [
            {"timestamp": now_str, "error": "429 Too Many Requests"}
        ]
    }
    _write_json(orchestrator.FLASH_SESSION_PATH, session)
    
    # クールダウンが効いて空が返る
    batch = hub.get_next_batch(phase=5, milestone="M5.1")
    assert batch == []


def test_get_next_batch_reentry_guard():
    hub = OrchestrationHub()
    
    # running なタスクがまだ残っている場合、新バッチは発行しない
    queue = {
        "tasks": [
            {"id": "T-1", "status": "running", "started_at": _now_iso()}
        ]
    }
    _write_json(orchestrator.TASK_QUEUE_PATH, queue)
    
    # 既存の running タスクがあるため、それらが返る
    batch = hub.get_next_batch(phase=5, milestone="M5.1")
    assert len(batch) == 1
    assert batch[0]["id"] == "T-1"


def test_get_next_batch_stale_running_reset():
    hub = OrchestrationHub()
    
    # 30分以上 running 状態のタスクがある場合、それを pending にリセットして再スケジュール可能にする
    stale_time = (datetime.now(timezone.utc) - timedelta(minutes=31)).isoformat()
    queue = {
        "tasks": [
            {"id": "T-1", "status": "running", "started_at": stale_time, "group": "bug_hunter"}
        ]
    }
    _write_json(orchestrator.TASK_QUEUE_PATH, queue)
    
    # リセットされて新規スケジュールされるためバッチが取得できる
    batch = hub.get_next_batch(phase=5, milestone="M5.1")
    assert len(batch) > 0
    assert batch[0]["status"] == "running"


def test_get_next_batch_milestone_advance():
    hub = OrchestrationHub()
    state = {
        "current_phase": 5,
        "current_milestone": "M5.2",
        "flash_batches_completed": 0,
        "metrics": {"coverage_pct": 30, "critical_debt": 2}
    }
    _write_json(orchestrator.PHASE_STATE_PATH, state)
    
    batch = hub.get_next_batch(phase=5, milestone="M5.2")
    assert len(batch) > 0
    queue = _read_json(orchestrator.TASK_QUEUE_PATH)
    assert queue["milestone"] == "M5.2"


def test_submit_batch_report_phase_advance_success(tmp_path):
    hub = OrchestrationHub()
    
    gates = {
        "5": {
            "min_coverage": 35,
            "max_critical_debt": 10
        }
    }
    _write_json(orchestrator.PHASE_GATES_PATH, gates)

    queue = {
        "current_batch_id": "batch_abc",
        "phase": 5,
        "milestone": "M5.5",
        "tasks": [
            {"id": "T-1", "status": "pass"}
        ]
    }
    _write_json(orchestrator.TASK_QUEUE_PATH, queue)
    
    state = {
        "current_phase": 5,
        "current_milestone": "M5.5",
        "flash_batches_completed": 4,
        "metrics": {"coverage_pct": 40, "critical_debt": 2}
    }
    _write_json(orchestrator.PHASE_STATE_PATH, state)
    
    # submit_batch_report を呼ぶと、ゲートチェックが走り、自動的に phase 6 に進むはず
    with patch.object(hub, "_capture_git_diff", return_value={"files_changed": 0}):
        hub.submit_batch_report("batch_abc", {"passed": 1, "failed": 0})
    
    new_state = _read_json(orchestrator.PHASE_STATE_PATH)
    assert new_state["current_phase"] == 6
    assert new_state["current_milestone"] == "M6.1"
    
    # Phase 5 完了報告書が作成されているか確認
    now_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    report_file = tmp_path / "inbox" / f"phase_5_completion_{now_str}.md"
    assert report_file.exists()


def test_submit_batch_report_phase_gate_failed():
    hub = OrchestrationHub()
    
    gates = {
        "5": {
            "min_coverage": 35,
            "max_critical_debt": 10
        }
    }
    _write_json(orchestrator.PHASE_GATES_PATH, gates)

    queue = {
        "current_batch_id": "batch_abc",
        "phase": 5,
        "milestone": "M5.5",
        "tasks": [
            {"id": "T-1", "status": "pass"}
        ]
    }
    _write_json(orchestrator.TASK_QUEUE_PATH, queue)
    
    state = {
        "current_phase": 5,
        "current_milestone": "M5.5",
        "flash_batches_completed": 4,
        "metrics": {"coverage_pct": 30, "critical_debt": 2}  # カバレッジ不足
    }
    _write_json(orchestrator.PHASE_STATE_PATH, state)
    
    # submit_batch_report を呼んでもゲート不通過のため Phase は 5.5 のまま
    with patch.object(hub, "_capture_git_diff", return_value={"files_changed": 0}):
        hub.submit_batch_report("batch_abc", {"passed": 1, "failed": 0})
    
    new_state = _read_json(orchestrator.PHASE_STATE_PATH)
    assert new_state["current_phase"] == 5
    assert new_state["current_milestone"] == "M5.5"


def test_get_next_batch_available_modules_and_blacklist_override(tmp_path):
    hub = OrchestrationHub()
    
    # ダミーの python ファイルを backend ディレクトリ構造に作成
    backend_dir = tmp_path / "backend"
    (backend_dir / "services").mkdir(parents=True, exist_ok=True)
    (backend_dir / "routers").mkdir(parents=True, exist_ok=True)
    (backend_dir / "__pycache__").mkdir(parents=True, exist_ok=True)
    
    (backend_dir / "services" / "vector.py").write_text("class Vector:\n    def run(self):\n        try: pass\n        except Exception: pass", encoding="utf-8")
    (backend_dir / "services" / "auth.py").write_text("class Auth: pass", encoding="utf-8")
    (backend_dir / "routers" / "smartcut.py").write_text("class SmartCut: pass", encoding="utf-8")
    (backend_dir / "services" / "test_service.py").write_text("class TestService: pass", encoding="utf-8") # 除外対象
    (backend_dir / "__pycache__" / "cached.py").write_text("class Cached: pass", encoding="utf-8") # 除外対象
    
    # ブラックリスト
    state = {
        "current_phase": 5,
        "current_milestone": "M5.1",
        "blacklisted_modules": ["services/auth.py"] # auth.py を除外
    }
    _write_json(orchestrator.PHASE_STATE_PATH, state)
    
    # Opus 指示による配分優先とブラックリスト追加
    directive = {
        "directive_id": "dir_1",
        "priorities": {"bug_hunter": 100},
        "blacklist_override": ["routers/smartcut.py"], # smartcut.py も除外
        "resume": True
    }
    _write_json(orchestrator.OPUS_DIRECTIVE_PATH, directive)
    
    # 選択可能なモジュールは `services/vector.py` のみになるはず
    batch = hub.get_next_batch(phase=5, milestone="M5.1", batch_size=1)
    
    assert batch[0]["target_module"] == "services/vector.py"


def test_message_box_operations():
    hub = OrchestrationHub()
    
    # メッセージ送信
    hub.send_message(sender="Flash", recipient="Opus", content="Help needed on test failing")
    
    # メッセージ取得
    msgs = hub.read_messages(recipient="Opus", unread_only=True)
    assert len(msgs) == 1
    assert msgs[0]["from"] == "Flash"
    assert msgs[0]["content"] == "Help needed on test failing"
    assert msgs[0]["ack"] is False
    
    # 既読化
    hub.acknowledge_message(msgs[0]["id"])
    
    # 既読後は取得されない
    msgs_after = hub.read_messages(recipient="Opus", unread_only=True)
    assert len(msgs_after) == 0


def test_opus_week_review_and_quota():
    hub = OrchestrationHub()
    
    now = datetime.now(timezone.utc)
    state = {
        "last_opus_review": (now - timedelta(hours=6)).isoformat(), # 5時間以上経過
        "opus_week_start": now.isoformat(),
        "opus_hours_used_this_week": 1.0
    }
    _write_json(orchestrator.PHASE_STATE_PATH, state)
    
    # トリガーされるはず
    assert hub.should_trigger_opus_review() is True
    
    # レビュー開始
    hub.start_opus_review()
    
    new_state = _read_json(orchestrator.PHASE_STATE_PATH)
    assert new_state["awaiting_opus"] is True
    
    # クォータ制限（週 5 時間）
    new_state["opus_hours_used_this_week"] = 5.1
    _write_json(orchestrator.PHASE_STATE_PATH, new_state)
    
    with pytest.raises(OpusQuotaExceededException):
        hub.start_opus_review()
        
    # レビュー終了
    hub.end_opus_review(duration_seconds=3600)
    assert hub.should_trigger_opus_review() is False


@patch("subprocess.run")
def test_git_helpers(mock_run):
    hub = OrchestrationHub()
    
    # _capture_git_diff 正常系
    mock_run.side_effect = [
        MagicMock(stdout=" M file1.py\n M file2.py\n?? file3.py\n", returncode=0), # git status --porcelain
        MagicMock(stdout="3 files changed, 10 insertions(+)\n", returncode=0), # git diff HEAD --stat
    ]
    diff = hub._capture_git_diff()
    assert diff["files_changed"] == 3
    assert "file1.py" in diff["changed_files"]
    assert "file3.py" in diff["untracked_files"]
    
    # _git_auto_commit 正常系
    mock_run.side_effect = None
    mock_run.return_value = MagicMock(returncode=0)
    with patch.object(OrchestrationHub, "_git_auto_commit", _ORIGINAL_GIT_AUTO_COMMIT):
        assert hub._git_auto_commit("Auto commit msg") is True
    
    # 例外系
    mock_run.side_effect = subprocess.SubprocessError("Git error")
    diff_err = hub._capture_git_diff()
    assert diff_err["files_changed"] == 0
    assert "Git error" in diff_err["error"]


def test_diagnose_flash_issues():
    hub = OrchestrationHub()
    
    # heartbeat 遅延
    stale_time = (datetime.now(timezone.utc) - timedelta(minutes=35)).isoformat()
    session = {
        "status": "running",
        "last_heartbeat": stale_time,
        "stall_count": 3,
        "recent_errors": [{"error": "ResourceExhausted"}]
    }
    _write_json(orchestrator.FLASH_SESSION_PATH, session)
    
    state = {
        "flash_consecutive_failures": 6 # 連続失敗多発
    }
    _write_json(orchestrator.PHASE_STATE_PATH, state)
    
    diagnosis = hub.diagnose_flash_issues()
    assert len(diagnosis["issues"]) == 2
    types = [i["type"] for i in diagnosis["issues"]]
    assert "stale" in types
    assert "repeated_errors" in types


@patch("subprocess.run")
def test_generate_hourly_report(mock_run, tmp_path):
    hub = OrchestrationHub()
    
    # git log mock
    git_stat_output = (
        "a44d528 2026-05-28 22:00:00 +0000 feat(bug_hunter): fix vector service\n"
        " backend/services/vector.py | 10 ++++++++++\n"
        " 1 file changed, 10 insertions(+)"
    )
    mock_run.side_effect = [
        MagicMock(stdout="a44d528 feat(bug_hunter): fix vector service", returncode=0),
        MagicMock(stdout=git_stat_output, returncode=0),
        MagicMock(stdout=" M backend/services/vector.py", returncode=0),
        MagicMock(stdout="", returncode=0),  # UXラチェット用のモックを追加
    ]
    
    # ダミーデータ
    queue = {
        "tasks": [
            {"id": "T-1", "group": "bug_hunter", "status": "pass", "target_module": "backend/services/vector.py",
             "result": {"message": "Success", "changed_files": ["backend/services/vector.py"]}}
        ]
    }
    _write_json(orchestrator.TASK_QUEUE_PATH, queue)
    
    state = {
        "current_phase": 5,
        "current_milestone": "M5.1",
        "metrics": {"coverage_pct": 50, "test_count": 100}
    }
    _write_json(orchestrator.PHASE_STATE_PATH, state)
    
    report_path = hub.generate_hourly_report()
    assert report_path.exists()
    
    report_content = report_path.read_text(encoding="utf-8")
    assert "1時間セッションレポート" in report_content
    assert "bug_hunter" in report_content
    assert "backend/services/vector.py" in report_content


def test_generate_daily_digest(tmp_path):
    hub = OrchestrationHub()
    
    now_str = datetime.now(timezone.utc).isoformat()
    # 直近エラーをモック
    session = {
        "session_started_at": now_str,
        "batches_in_session": 5,
        "recent_errors": [
            {"timestamp": now_str, "module": "backend/routers/smartcut.py", "error": "ImportError"}
        ]
    }
    _write_json(orchestrator.FLASH_SESSION_PATH, session)
    
    state = {
        "current_phase": 5,
        "current_milestone": "M5.1",
        "metrics": {"coverage_pct": 50, "test_count": 100}
    }
    _write_json(orchestrator.PHASE_STATE_PATH, state)
    
    digest_path = hub.generate_daily_digest()
    assert digest_path.exists()
    
    digest_content = digest_path.read_text(encoding="utf-8")
    assert "デイリーダイジェスト" in digest_content
    assert "ImportError" in digest_content


def test_flash_session_controls():
    hub = OrchestrationHub()
    
    # セッション開始
    hub.flash_session_start()
    session = _read_json(orchestrator.FLASH_SESSION_PATH)
    assert session["status"] == "running"
    assert session["session_started_at"] is not None
    assert session["last_heartbeat"] is not None
    
    # 心拍更新
    hub.flash_heartbeat()
    session = _read_json(orchestrator.FLASH_SESSION_PATH)
    assert session["last_heartbeat"] is not None
    
    # 軽量心拍更新 (flash_update_heartbeat)
    old_hb = session["last_heartbeat"]
    # _now_iso をモックして異なる時間を返す
    with patch("backend.agents.orchestration.hub_session._now_iso", return_value=(datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat()):
        hub.flash_update_heartbeat()
    session = _read_json(orchestrator.FLASH_SESSION_PATH)
    assert session["last_heartbeat"] != old_hb
    
    # ステータス更新
    hub.flash_update_status(activity="testing", step="Step 1: Running unit tests")
    session = _read_json(orchestrator.FLASH_SESSION_PATH)
    assert session["current_step"] == "Step 1: Running unit tests"
    assert session["current_activity"] == "testing"

    # セッション終了
    hub.flash_session_end(exit_reason="Completed all tasks")
    session = _read_json(orchestrator.FLASH_SESSION_PATH)
    assert session["status"] == "ended"
    assert session["exit_reason"] == "Completed all tasks"
    assert session["session_ended_at"] is not None


def test_check_flash_alive():
    hub = OrchestrationHub()
    
    # 1. 稼働中
    now_str = datetime.now(timezone.utc).isoformat()
    session = {
        "status": "running",
        "last_heartbeat": now_str,
        "current_step": "Idle"
    }
    _write_json(orchestrator.FLASH_SESSION_PATH, session)
    alive = hub.check_flash_alive()
    assert alive["alive"] is True
    assert alive["status"] == "running"
    
    # 2. 応答なし (30分超)
    stale_time = (datetime.now(timezone.utc) - timedelta(minutes=35)).isoformat()
    session["last_heartbeat"] = stale_time
    _write_json(orchestrator.FLASH_SESSION_PATH, session)
    alive = hub.check_flash_alive()
    assert alive["alive"] is False
    assert alive["status"] == "stale"
    
    # 3. 終了
    session["status"] = "ended"
    session["exit_reason"] = "Done"
    _write_json(orchestrator.FLASH_SESSION_PATH, session)
    alive = hub.check_flash_alive()
    assert alive["alive"] is False
    assert alive["status"] == "ended"
    assert alive["exit_reason"] == "Done"


def test_large_change_automatic_decomposition(tmp_path):
    hub = OrchestrationHub()
    
    # 1. ダミーのタスクキューを作成して実行中タスクを定義
    queue = {
        "current_batch_id": "batch_123",
        "phase": 5,
        "milestone": "M5.1",
        "tasks": [
            {
                "id": "T-123-001",
                "status": "running",
                "started_at": _now_iso(),
                "target_module": "services/vector.py",
                "group": "refactor"
            }
        ],
        "large_change_modules": []
    }
    _write_json(orchestrator.TASK_QUEUE_PATH, queue)
    
    state = {
        "current_phase": 5,
        "current_milestone": "M5.1",
        "flash_batches_completed": 0,
        "metrics": {"coverage_pct": 50, "test_count": 100}
    }
    _write_json(orchestrator.PHASE_STATE_PATH, state)
    
    # 2. タスク完了時に変更ファイル数を 4 件（3超）にして完了報告
    hub.mark_task_done(
        "T-123-001", 
        result="pass", 
        report={
            "message": "Large modification completed", 
            "changed_files": ["file1.py", "file2.py", "file3.py", "file4.py"]
        }
    )
    
    # 3. バッチレポート送信 (検出処理トリガー)
    with patch.object(hub, "_capture_git_diff", return_value={"files_changed": 4}):
        hub.submit_batch_report("batch_123", {"passed": 1, "failed": 0})
        
    # task_queue.json の large_change_modules にモジュールが登録されたか検証
    updated_queue = _read_json(orchestrator.TASK_QUEUE_PATH)
    assert "services/vector.py" in updated_queue.get("large_change_modules", [])
    
    # 4. 次バッチを生成するときに、該当モジュールのタスクが自動細分化されることを検証
    # available_modulesにservices/vector.pyを配置するためダミーファイルをtmp_pathに作成
    backend_dir = tmp_path / "backend" / "services"
    backend_dir.mkdir(parents=True, exist_ok=True)
    (backend_dir / "vector.py").write_text("class Vector: pass", encoding="utf-8")
    
    # prioritiesをモックしてrefactorグループで生成されるようにする
    with patch.object(hub, "_get_available_modules", return_value=["services/vector.py"]), \
         patch.object(hub, "_adjust_priorities_by_hit_rate", return_value={"refactor": 100}), \
         patch.object(hub, "_capture_git_diff", return_value={"files_changed": 0}):
        
        # 既存タスクがない状態（pending=0）でget_next_batchを呼び出し、新しいバッチを生成
        _write_json(orchestrator.TASK_QUEUE_PATH, {
            "tasks": [],
            "large_change_modules": ["services/vector.py"]
        })
        
        batch = hub.get_next_batch(phase=5, milestone="M5.1", batch_size=5)
        
        # 細分化されて3つのタスク（設計、実装、テスト）が生成されたか確認
        assert len(batch) >= 3
        # 分割されたタスクのIDと内容を検証
        split_ids = [t["id"] for t in batch]
        assert any("split0" in sid for sid in split_ids)
        assert any("split1" in sid for sid in split_ids)
        assert any("split2" in sid for sid in split_ids)
        
        # 適用後に large_change_modules から該当モジュールが削除されたことを検証
        final_queue = _read_json(orchestrator.TASK_QUEUE_PATH)
        assert "services/vector.py" not in final_queue.get("large_change_modules", [])


def test_mark_task_done_design_stock_status_update(tmp_path):
    hub = OrchestrationHub()
    
    # design_stock.json 初期モックデータ
    ds_data = {
        "config": {
            "target_stock_count": 10,
            "phases_ahead": 3,
            "stale_days_sa": 3,
            "stale_days_bc": 7
        },
        "stock_items": [
            {
                "id": "DS-001",
                "title": "Mock Design Task 1",
                "phase": 5,
                "difficulty": "C",
                "status": "dispatched",
                "created_at": _now_iso(),
                "last_activity": _now_iso()
            },
            {
                "id": "DS-AUTO-ABCDEF",
                "title": "Mock Design Task Auto",
                "phase": 5,
                "difficulty": "C",
                "status": "dispatched",
                "created_at": _now_iso(),
                "last_activity": _now_iso()
            }
        ]
    }
    _write_json(orchestrator.DESIGN_STOCK_PATH, ds_data)

    # 1. 正常系：design_stock_id が直接タスクにある場合 (ステップ分割タスク)
    queue = {
        "tasks": [
            {
                "id": "T-batch_123-ds-ds-001-000",
                "status": "running",
                "design_stock_id": "DS-001"
            }
        ]
    }
    _write_json(orchestrator.TASK_QUEUE_PATH, queue)
    
    state = {
        "current_phase": 5,
        "current_milestone": "M5.1",
        "flash_consecutive_failures": 0,
        "flash_batches_completed": 0,
        "metrics": {"coverage_pct": 50, "test_count": 100}
    }
    _write_json(orchestrator.PHASE_STATE_PATH, state)

    hub.mark_task_done("T-batch_123-ds-ds-001-000", result="pass")
    
    updated_ds = _read_json(orchestrator.DESIGN_STOCK_PATH)
    item_001 = next(item for item in updated_ds["stock_items"] if item["id"] == "DS-001")
    assert item_001["status"] == "completed"

    # 2. フォールバック系：design_stock_id がない場合 (T-batch_xxx-ds-ds-001 型)
    # DS-001をdispatchedに戻す
    item_001["status"] = "dispatched"
    _write_json(orchestrator.DESIGN_STOCK_PATH, updated_ds)

    queue2 = {
        "tasks": [
            {
                "id": "T-batch_123-ds-ds-001",
                "status": "running"
                # design_stock_id は意図的に無し
            }
        ]
    }
    _write_json(orchestrator.TASK_QUEUE_PATH, queue2)
    
    hub.mark_task_done("T-batch_123-ds-ds-001", result="pass")
    
    updated_ds2 = _read_json(orchestrator.DESIGN_STOCK_PATH)
    item_001_v2 = next(item for item in updated_ds2["stock_items"] if item["id"] == "DS-001")
    assert item_001_v2["status"] == "completed"

    # 3. フォールバック系：AUTO 形式 (T-batch_xxx-ds-ds-auto-abcdef-000 型)
    queue3 = {
        "tasks": [
            {
                "id": "T-batch_123-ds-ds-auto-abcdef-000",
                "status": "running"
                # design_stock_id は意図的に無し
            }
        ]
    }
    _write_json(orchestrator.TASK_QUEUE_PATH, queue3)
    
    hub.mark_task_done("T-batch_123-ds-ds-auto-abcdef-000", result="pass")
    
    updated_ds3 = _read_json(orchestrator.DESIGN_STOCK_PATH)
    item_auto = next(item for item in updated_ds3["stock_items"] if item["id"] == "DS-AUTO-ABCDEF")
    assert item_auto["status"] == "completed"


def test_verify_file(tmp_path):
    hub = OrchestrationHub()
    
    # 正常系: Broad exception なしのファイル
    normal_file = tmp_path / "normal.py"
    normal_file.write_text("def my_func():\n    try:\n        pass\n    except ValueError:\n        pass\n", encoding="utf-8")
    
    # ワークスペースパスを一時ディレクトリにモックしてテスト
    with patch.object(orchestrator, "_PROJECT_ROOT", tmp_path):
        # CodeVerifier の workspace_path も一時ディレクトリにするために patch
        with patch("backend.agents.orchestration.verifier.CodeVerifier.__init__", lambda self, workspace_path=None: setattr(self, "workspace_path", str(tmp_path))):
            res = hub.verify_file("normal.py")
            assert res["passed"] is True
            assert not res.get("errors")

            # 異常系: Broad exception (except Exception:) ありのファイル
            bad_file = tmp_path / "bad.py"
            bad_file.write_text("def my_func():\n    try:\n        pass\n    except Exception:\n        pass\n", encoding="utf-8")
            res_bad = hub.verify_file("bad.py")
            assert res_bad["passed"] is False
            assert len(res_bad["errors"]) > 0
            assert "Broad exception handler detected" in res_bad["errors"][0]

            # 異常系: 存在しないファイル
            res_missing = hub.verify_file("missing.py")
            assert res_missing["passed"] is False
            assert "File not found" in res_missing["error"]


@patch("subprocess.run")
def test_verify_test_suite(mock_subprocess_run):
    hub = OrchestrationHub()
    
    # 正常系: pytest 成功 (returncode=0)
    mock_res_ok = MagicMock(returncode=0, stdout="5 passed", stderr="")
    mock_subprocess_run.return_value = mock_res_ok
    
    res = hub.verify_test_suite("tests/test_something.py")
    assert res["passed"] is True
    assert res["stdout"] == "5 passed"
    assert res["exit_code"] == 0
    
    # 異常系: pytest 失敗 (returncode=1)
    mock_res_fail = MagicMock(returncode=1, stdout="1 failed", stderr="error details")
    mock_subprocess_run.return_value = mock_res_fail
    
    res_fail = hub.verify_test_suite("tests/test_something.py")
    assert res_fail["passed"] is False
    assert res_fail["stdout"] == "1 failed"
    assert res_fail["exit_code"] == 1

    # 例外系: subprocess.run 自体が例外を投げる場合
    mock_subprocess_run.side_effect = subprocess.SubprocessError("pytest command not found")
    
    res_err = hub.verify_test_suite("tests/test_something.py")
    assert res_err["passed"] is False
    assert "Test execution failed" in res_err["error"]


def test_generate_tasks_for_batch():
    hub = OrchestrationHub()
    
    # 設計ストックのダミーデータ
    stock_items = [
        # 単一タスク
        {
            "id": "DS-001",
            "title": "Implement Vector DB",
            "description": "Create a vector db connector.",
            "difficulty": "A",
            "target_module": "backend/services/vector.py"
        },
        # 分割ステップタスク
        {
            "id": "DS-002",
            "title": "Refactor Router",
            "description": "Clean up smartcut router.",
            "difficulty": "B",
            "implementation_steps": [
                {
                    "target_module": "backend/routers/smartcut.py",
                    "description": "Extract logic to service."
                },
                {
                    "target_module": "backend/routers/smartcut.py",
                    "description": "Add unit tests."
                }
            ]
        }
    ]
    
    tasks = hub.generate_tasks_for_batch("batch_b9f958", stock_items)
    
    # 合計 3 個のタスクが生成されるはず（DS-001で1つ、DS-002で2ステップ）
    assert len(tasks) == 3
    
    # DS-001のタスク検証
    t1 = next(t for t in tasks if "ds-001" in t["id"])
    assert t1["id"] == "T-batch_b9f958-ds-ds-001"
    assert t1["group"] == "design_stock"  # generator.py は常に design_stock を返すため
    assert t1["level"] == "L2"           # difficulty A -> L2
    assert t1["target_module"] == "backend/services/vector.py"
    assert "Implement Vector DB" in t1["instruction"]
    assert t1["status"] == "pending"
    
    # DS-002 of step 1 validation
    t2_step1 = next(t for t in tasks if t["id"] == "T-batch_b9f958-ds-ds-002-000")
    assert t2_step1["group"] == "design_stock"  # design_stock
    assert t2_step1["level"] == "L2"          # difficulty B -> L2
    assert t2_step1["target_module"] == "backend/routers/smartcut.py"
    assert "Extract logic to service." in t2_step1["instruction"]
    
    # DS-002 of step 2 validation
    t2_step2 = next(t for t in tasks if t["id"] == "T-batch_b9f958-ds-ds-002-001")
    assert t2_step2["group"] == "design_stock"
    assert t2_step2["level"] == "L2"
    assert t2_step2["target_module"] == "backend/routers/smartcut.py"
    assert "Add unit tests." in t2_step2["instruction"]


def test_orchestration_hub_direct_verification_methods(tmp_path):
    hub = OrchestrationHub()
    
    # verify_file が直接呼び出せることを検証
    # ダミーファイルを作成
    dummy_file = tmp_path / "dummy_test.py"
    dummy_file.write_text("# Dummy code\n", encoding="utf-8")
    
    with patch.object(orchestrator, "_PROJECT_ROOT", tmp_path):
        with patch("backend.agents.orchestration.verifier.CodeVerifier.__init__", lambda self, workspace_path=None: setattr(self, "workspace_path", str(tmp_path))):
            res = hub.verify_file("dummy_test.py")
            assert "passed" in res
            assert res["passed"] is True

    # verify_test_suite が直接呼び出せることを検証
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="passed", stderr="")
        res_suite = hub.verify_test_suite("tests/test_dummy.py")
        assert "passed" in res_suite
        assert res_suite["passed"] is True


def test_orchestrator_three_point_check(tmp_path):
    hub = OrchestrationHub()
    
    # --- 1. 入力ガードレール (input_guardrail) のテスト ---
    # 階層遡りパスの検知
    res_traversal = hub.verify_file("../outside.py")
    assert res_traversal["passed"] is False
    assert "Invalid file path" in res_traversal["error"]
    
    # 絶対パスの検知
    res_absolute = hub.verify_file("/absolute/path/file.py")
    assert res_absolute["passed"] is False
    assert "Invalid file path" in res_absolute["error"]
    
    # 1MB制限の検知
    large_file = tmp_path / "large_file.py"
    large_file.write_bytes(b"A" * (1024 * 1024 + 100))
    with patch.object(orchestrator, "_PROJECT_ROOT", tmp_path):
        res_large = hub.verify_file("large_file.py")
        assert res_large["passed"] is False
        assert "File size exceeds 1MB limit" in res_large["error"]

    # --- 2. セーフティフォールバック (safety_fallback) のテスト ---
    # タイムアウトの捕捉
    with patch("subprocess.run") as mock_run:
        # verify_dynamic is designed to retry with a 600s timeout if 300s fails/timeouts.
        # Thus, mock two timeouts to simulate the final failure after retry.
        mock_run.side_effect = [
            subprocess.TimeoutExpired(cmd="pytest", timeout=300),
            subprocess.TimeoutExpired(cmd="pytest", timeout=600)
        ]
        res_timeout = hub.verify_test_suite("tests/test_something.py")
        assert res_timeout["passed"] is False
        assert "Test execution timed out after 600 seconds" in res_timeout["error"]
        
    # 予期せぬ例外の捕捉
    with patch("backend.agents.orchestration.verifier.CodeVerifier.verify_dynamic") as mock_verify:
        mock_verify.side_effect = RuntimeError("Crash!")
        res_crash = hub.verify_test_suite("tests/test_something.py")
        assert res_crash["passed"] is False
        assert "Test execution failed: Crash!" in res_crash["error"]

    # --- 3. 定量的マッピング (quantitative_mapping) のテスト ---
    stock_items = [
        {"id": "DS-001", "title": "S Difficulty", "difficulty": "S"},
        {"id": "DS-002", "title": "A Difficulty", "difficulty": "A"},
        {"id": "DS-003", "title": "B Difficulty", "difficulty": "B"},
        {"id": "DS-004", "title": "C Difficulty", "difficulty": "C"},
        {"id": "DS-005", "title": "Unknown Difficulty", "difficulty": "X"}
    ]
    
    with patch("backend.agents.orchestration.generator.TaskGenerator.create_batch_tasks") as mock_create:
        mock_create.return_value = [
            {"design_stock_id": "DS-001", "level": "L1"},
            {"design_stock_id": "DS-002", "level": "L1"},
            {"design_stock_id": "DS-003", "level": "L1"},
            {"design_stock_id": "DS-004", "level": "L2"},
            {"design_stock_id": "DS-005", "level": "L2"}
        ]
        
        tasks = hub.generate_tasks_for_batch("batch_123", stock_items)
        assert tasks[0]["level"] == "L2"
        assert tasks[1]["level"] == "L2"
        assert tasks[2]["level"] == "L2"
        assert tasks[3]["level"] == "L1"
        assert tasks[4]["level"] == "L1"


def test_hub_batch_error_handling_robustness(tmp_path):
    """hub_batch.py の改善されたエラーハンドリング（例外発生時にも処理が継続されること、およびログ出力）を検証する。"""
    hub = OrchestrationHub()
    
    # 1. _get_available_modules 内のキャッシュ読み込みで例外が発生しても、
    # 処理がクラッシュせずにフォールバック（ファイルスキャン）して正常に動作すること。
    index_path = tmp_path / "module_index.json"
    
    with patch.object(orchestrator, "MODULE_INDEX_PATH", index_path), \
         patch.object(hub, "_scan_backend_modules", return_value=["services/test_module.py"]), \
         patch("backend.agents.orchestration.hub_batch.safe_read_json", side_effect=PermissionError("Permission Denied")), \
         patch("backend.agents.orchestration.hub_batch.logger") as mock_logger:
        
        modules = hub._get_available_modules(blacklisted=set())
        assert modules == ["services/test_module.py"]
        # キャッシュ読み込み失敗の警告が記録されているか
        assert mock_logger.warning.called or mock_logger.error.called or mock_logger.debug.called

    # 2. _enrich_instruction 内での例外（ファイル読み込み例外など）発生時にも、
    # クラッシュせずに None が返され、警告ログが出力されること。
    with patch("backend.agents.orchestration.hub_batch.logger") as mock_logger:
        # 存在しないファイルパス等で例外を誘発
        with patch("backend.agents.orchestration.hub_batch.safe_read_json", side_effect=PermissionError("Permission Denied")):
            enrichment = hub._enrich_instruction("tdr_cleanup", "services/missing.py", miss_counts={})
            assert enrichment is None
            assert mock_logger.warning.called or mock_logger.error.called or mock_logger.debug.called







def test_hub_batch_additional_robustness(tmp_path):
    """T-batch_0ff685-bug_hunter-001 用のテスト。
    1. _calculate_max_concurrent 内で usage_tracker が例外（AttributeError等）を投げた場合のフォールバック検証。
    2. mark_task_done において result='failed' が渡された場合に fail と同様に統計更新およびエラー処理が行われることの検証。
    """
    hub = OrchestrationHub()

    # --- 1. usage_tracker 例外発生時のフォールバック検証 ---
    mock_tracker = MagicMock()
    mock_tracker.get_remaining_requests.side_effect = AttributeError("Mocked attribute error")

    with patch("backend.usage_tracker.tracker.usage_tracker", mock_tracker), \
         patch("pathlib.Path.exists", return_value=False):
        res = hub._calculate_max_concurrent(phase=26, batch_size=5, session={})
        assert res == 5

    # --- 2. mark_task_done で result="failed" 時の挙動検証 ---
    queue = {
        "tasks": [
            {"id": "T-TEST-FAILED", "status": "running", "started_at": _now_iso(), "target_module": "backend/services/vector.py", "retry_count": 0}
        ]
    }
    _write_json(orchestrator.TASK_QUEUE_PATH, queue)
    
    state = {
        "flash_consecutive_failures": 0,
        "flash_tasks_failed": 0,
        "flash_tasks_total": 0,
        "metrics": {"coverage_pct": 50, "test_count": 100, "critical_debt": 2}
    }
    _write_json(orchestrator.PHASE_STATE_PATH, state)

    hub.mark_task_done("T-TEST-FAILED", result="failed", report={"error": "SyntaxError", "traceback": "Traceback info"})

    new_state = _read_json(orchestrator.PHASE_STATE_PATH)
    assert new_state["flash_tasks_failed"] == 1
    assert new_state["flash_consecutive_failures"] == 1

    inbox_files = list(orchestrator.INBOX_DIR.glob("error_*_T-TEST-FAILED.md"))
    assert len(inbox_files) == 1
    report_content = inbox_files[0].read_text(encoding="utf-8")
    assert "SyntaxError" in report_content
