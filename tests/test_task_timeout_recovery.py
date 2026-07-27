import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

import backend.agents.orchestration.orchestrator as orchestrator
from backend.agents.orchestration.orchestrator import (
    OrchestrationHub,
    _read_json,
    _write_json,
    _now_iso
)

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


def test_task_timeout_recovery():
    hub = OrchestrationHub()
    
    now = datetime.now(timezone.utc)
    stale_time = (now - timedelta(seconds=1000)).isoformat()  # 900秒以上経過
    
    queue = {
        "phase": 6,
        "milestone": "M6.1",
        "tasks": [
            # T-dep: 依存先タスク。これが pending として維持されることで自動再生成を防ぎ、かつこれが running になる
            {"id": "T-dep", "status": "pending", "retry_count": 0, "target_module": "services/auth.py"},
            # T-1: 通常のタイムアウト -> pending に差し戻し, retry_count+1。T-depに依存するため running に戻らない
            {"id": "T-1", "status": "running", "started_at": stale_time, "retry_count": 0, "dependencies": ["T-dep"], "target_module": "services/vector.py"},
            # T-2: リトライ限界 (2回) 未満のタイムアウト -> pending に差し戻し, retry_count+1。T-depに依存するため running に戻らない
            {"id": "T-2", "status": "running", "started_at": stale_time, "retry_count": 1, "dependencies": ["T-dep"], "target_module": "services/auth.py"},
            # T-3: リトライ限界 (2回) 超過のタイムアウト -> status=skip, completed_at記録, 結果にエラー, Opusにメッセージ
            {"id": "T-3", "status": "running", "started_at": stale_time, "retry_count": 2, "target_module": "routers/smartcut.py"}
        ]
    }
    _write_json(orchestrator.TASK_QUEUE_PATH, queue)
    _write_json(orchestrator.FLASH_SESSION_PATH, {"status": "running", "recent_errors": []})
    
    # get_next_batch を実行すると、タイムアウト回収が自動で走る
    hub.get_next_batch(phase=6, milestone="M6.1", timeout_seconds=900)
    
    new_queue = _read_json(orchestrator.TASK_QUEUE_PATH)
    tasks = {t["id"]: t for t in new_queue["tasks"]}
    
    # T-1検証
    assert tasks["T-1"]["status"] == "pending"
    assert tasks["T-1"]["started_at"] is None
    assert tasks["T-1"]["retry_count"] == 1
    
    # T-2検証
    assert tasks["T-2"]["status"] == "pending"
    assert tasks["T-2"]["started_at"] is None
    assert tasks["T-2"]["retry_count"] == 2
    
    # T-3検証
    assert tasks["T-3"]["status"] == "skip"
    assert tasks["T-3"]["completed_at"] is not None
    assert "MAX_RETRIES_EXCEEDED" in tasks["T-3"]["result"]["error"]
    assert tasks["T-3"]["result"]["retry_count"] == 3
    
    # session検証
    session = _read_json(orchestrator.FLASH_SESSION_PATH)
    assert len(session["recent_errors"]) == 3
    errors = {e["error"] for e in session["recent_errors"]}
    assert "TIMEOUT_RECOVERY: Task T-1 (retry 1/2)" in errors
    assert "TIMEOUT_RECOVERY: Task T-2 (retry 2/2)" in errors
    assert "TIMEOUT_RECOVERY: Task T-3 (retry 3/2)" in errors

    # message box検証 (Opusへのメッセージ)
    msgs = hub.read_messages(recipient="opus", unread_only=True)
    assert len(msgs) == 1
    assert "⚠️ タスク T-3" in msgs[0]["content"]


def test_task_timeout_recovery_send_message_error():
    hub = OrchestrationHub()
    now = datetime.now(timezone.utc)
    stale_time = (now - timedelta(seconds=1000)).isoformat()
    
    queue = {
        "phase": 6,
        "milestone": "M6.1",
        "tasks": [
            {"id": "T-dep", "status": "pending", "retry_count": 0, "target_module": "services/auth.py"},
            # T-3: 通常タイムアウト限界超過するタスク
            {"id": "T-3", "status": "running", "started_at": stale_time, "retry_count": 2, "target_module": "routers/smartcut.py"}
        ]
    }
    _write_json(orchestrator.TASK_QUEUE_PATH, queue)
    _write_json(orchestrator.FLASH_SESSION_PATH, {"status": "running", "recent_errors": []})
    
    # send_message が例外を投げるようにモックする
    with patch.object(hub, "send_message", side_effect=RuntimeError("Network down")):
        # 例外は内部でキャッチされ、クラッシュせずに正常終了するはず
        hub.get_next_batch(phase=6, milestone="M6.1", timeout_seconds=900)
        
    new_queue = _read_json(orchestrator.TASK_QUEUE_PATH)
    tasks = {t["id"]: t for t in new_queue["tasks"]}
    assert tasks["T-3"]["status"] == "skip"


def test_task_no_timeout_recovery():
    hub = OrchestrationHub()
    
    now = datetime.now(timezone.utc)
    fresh_time = (now - timedelta(seconds=500)).isoformat()  # 900秒未満
    
    queue = {
        "phase": 6,
        "milestone": "M6.1",
        "tasks": [
            {"id": "T-4", "status": "running", "started_at": fresh_time, "retry_count": 0, "target_module": "services/vector.py"}
        ]
    }
    _write_json(orchestrator.TASK_QUEUE_PATH, queue)
    _write_json(orchestrator.FLASH_SESSION_PATH, {"status": "running", "recent_errors": []})
    
    hub.get_next_batch(phase=6, milestone="M6.1", timeout_seconds=900)
    
    new_queue = _read_json(orchestrator.TASK_QUEUE_PATH)
    tasks = {t["id"]: t for t in new_queue["tasks"]}
    
    # 状態が維持されていること
    assert tasks["T-4"]["status"] == "running"
    assert tasks["T-4"]["started_at"] == fresh_time
    assert tasks["T-4"]["retry_count"] == 0


def test_task_timeout_recovery_edge_cases():
    hub = OrchestrationHub()
    
    queue = {
        "phase": 6,
        "milestone": "M6.1",
        "tasks": [
            {"id": "T-dep", "status": "pending", "retry_count": 0, "target_module": "services/auth.py"},
            # T-5: started_at なし -> タイムアウト判定はされず、started_at が現在時刻で初期化される
            {"id": "T-5", "status": "running", "started_at": None, "retry_count": 0, "target_module": "services/vector.py"},
            {"id": "T-5_empty", "status": "running", "started_at": "", "retry_count": 0, "target_module": "services/vector.py"},
            # T-6: started_at 不正な形式 -> タイムアウト判定はされず、started_at が現在時刻で初期化される
            {"id": "T-6", "status": "running", "started_at": "invalid-date-format", "retry_count": 0, "target_module": "services/vector.py"},
            # T-7: assigned_agent あり、通常タイムアウト -> pendingに差し戻され、assigned_agent=Noneにリセット
            {"id": "T-7", "status": "running", "started_at": (datetime.now(timezone.utc) - timedelta(seconds=1000)).isoformat(), "retry_count": 0, "assigned_agent": "agent_123", "dependencies": ["T-dep"], "target_module": "services/vector.py"},
        ]
    }
    _write_json(orchestrator.TASK_QUEUE_PATH, queue)
    
    # flash_session.json に recent_errors キーが含まれていない状態を作成
    _write_json(orchestrator.FLASH_SESSION_PATH, {"status": "running"})
    
    hub.get_next_batch(phase=6, milestone="M6.1", timeout_seconds=900)
    
    new_queue = _read_json(orchestrator.TASK_QUEUE_PATH)
    tasks = {t["id"]: t for t in new_queue["tasks"]}
    
    # T-5検証
    assert tasks["T-5"]["status"] == "running"
    assert tasks["T-5"]["started_at"] is not None
    assert tasks["T-5_empty"]["status"] == "running"
    assert tasks["T-5_empty"]["started_at"] is not None
    
    # T-6検証
    assert tasks["T-6"]["status"] == "running"
    assert tasks["T-6"]["started_at"] is not None
    
    # T-7検証
    assert tasks["T-7"]["status"] == "pending"
    assert tasks["T-7"]["started_at"] is None
    assert tasks["T-7"].get("assigned_agent") is None
    
    # recent_errors が自動的に初期化され、T-7 のエラーが追加されていること
    session = _read_json(orchestrator.FLASH_SESSION_PATH)
    assert "recent_errors" in session
    assert len(session["recent_errors"]) == 1
    assert session["recent_errors"][0]["error"] == "TIMEOUT_RECOVERY: Task T-7 (retry 1/2)"
