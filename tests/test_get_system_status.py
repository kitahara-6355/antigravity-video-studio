import json
import os
import subprocess
import sys
import pytest
from backend.agents.orchestration.get_system_status import (
    check_safety_guard,
    query_system_status,
    main,
)

def test_check_safety_guard():
    check_safety_guard()
    check_safety_guard("/dummy/path")

def test_query_system_status_all_files_not_found(tmp_path):
    base_dir = str(tmp_path)
    paths = {
        "flash_session": os.path.join(base_dir, "flash_session.json"),
        "task_queue": os.path.join(base_dir, "task_queue.json"),
        "phase_state": os.path.join(base_dir, "phase_state.json"),
        "tdr_index": os.path.join(base_dir, "technical_debt_index.json"),
        "design_stock": os.path.join(base_dir, "design_stock")
    }
    summary = query_system_status(paths=paths)
    
    assert summary["flash_session"] == "Not Found"
    assert summary["task_queue"] == "Not Found"
    assert summary["phase_state"] == "Not Found"
    assert summary["tdr_index"] == "Not Found"
    assert summary["design_stock"] == "Not Found"

def test_query_system_status_with_data_list_tdr(tmp_path):
    base_dir = tmp_path
    
    # 1. flash_session
    flash_session_data = {
        "status": "running",
        "last_heartbeat": "2026-05-29T12:00:00",
        "current_activity": "testing",
        "current_step": 3,
        "current_batch_id": "batch_01",
        "progress_pct": 50.0,
        "tasks_completed_in_session": 10
    }
    flash_session_file = base_dir / "flash_session.json"
    with open(flash_session_file, 'w', encoding='utf-8') as f:
        json.dump(flash_session_data, f)
        
    # 2. task_queue
    task_queue_data = {
        "current_batch_id": "batch_01",
        "status": "active",
        "tasks": [
            {"status": "pending"},
            {"status": "running"},
            {"status": "completed"},
            {"status": "pass"},
            {"status": "failed"},
            {"status": "unknown"}
        ]
    }
    task_queue_file = base_dir / "task_queue.json"
    with open(task_queue_file, 'w', encoding='utf-8') as f:
        json.dump(task_queue_data, f)
        
    # 3. phase_state
    phase_state_data = {
        "current_phase": 27,
        "phase_name": "Testing",
        "emergency_stop": False
    }
    phase_state_file = base_dir / "phase_state.json"
    with open(phase_state_file, 'w', encoding='utf-8') as f:
        json.dump(phase_state_data, f)
        
    # 4. tdr_index (list entries)
    tdr_index_data = {
        "entries": [
            {"status": "open", "priority": "CRITICAL"},
            {"status": "open", "priority": "HIGH"},
            {"status": "fixed"},
            {"status": "resolved"},
            {"status": "accepted"},
            {"status": "unknown"}
        ]
    }
    tdr_index_file = base_dir / "technical_debt_index.json"
    with open(tdr_index_file, 'w', encoding='utf-8') as f:
        json.dump(tdr_index_data, f)
        
    # 5. design_stock
    design_stock_dir = base_dir / "design_stock"
    design_stock_dir.mkdir()
    (design_stock_dir / "design1.md").write_text("content", encoding="utf-8")
    (design_stock_dir / "design2.md").write_text("content", encoding="utf-8")
    (design_stock_dir / "notes.txt").write_text("content", encoding="utf-8")
    
    paths = {
        "flash_session": str(flash_session_file),
        "task_queue": str(task_queue_file),
        "phase_state": str(phase_state_file),
        "tdr_index": str(tdr_index_file),
        "design_stock": str(design_stock_dir)
    }
    
    summary = query_system_status(paths=paths)
    
    assert summary["flash_session"]["status"] == "running"
    assert summary["flash_session"]["progress_pct"] == 50.0
    
    assert summary["task_queue"]["total_tasks"] == 6
    assert summary["task_queue"]["pending"] == 1
    assert summary["task_queue"]["running"] == 1
    assert summary["task_queue"]["completed"] == 2
    assert summary["task_queue"]["failed"] == 1
    assert summary["task_queue"]["current_batch_id"] == "batch_01"
    
    assert summary["phase_state"]["current_phase"] == 27
    assert summary["phase_state"]["emergency_stop"] is False
    
    assert summary["tdr_index"]["total_registered"] == 6
    assert summary["tdr_index"]["open"] == 2
    assert summary["tdr_index"]["resolved"] == 2
    assert summary["tdr_index"]["accepted"] == 1
    assert summary["tdr_index"]["critical_open"] == 1
    
    assert summary["design_stock"]["total_stock_count"] == 2
    assert set(summary["design_stock"]["files"]) == {"design1.md", "design2.md"}

def test_query_system_status_dict_tdr(tmp_path):
    base_dir = tmp_path
    
    tdr_index_data = {
        "entries": {
            "debt1": {"status": "open", "priority": "CRITICAL"},
            "debt2": {"status": "fixed"},
            "debt3": {"status": "accepted"}
        }
    }
    tdr_index_file = base_dir / "technical_debt_index.json"
    with open(tdr_index_file, 'w', encoding='utf-8') as f:
        json.dump(tdr_index_data, f)
        
    paths = {
        "flash_session": "",
        "task_queue": "",
        "phase_state": "",
        "tdr_index": str(tdr_index_file),
        "design_stock": ""
    }
    
    summary = query_system_status(paths=paths)
    
    assert summary["tdr_index"]["total_registered"] == 3
    assert summary["tdr_index"]["open"] == 1
    assert summary["tdr_index"]["resolved"] == 1
    assert summary["tdr_index"]["accepted"] == 1
    assert summary["tdr_index"]["critical_open"] == 1

def test_query_system_status_default_paths(monkeypatch):
    monkeypatch.setattr(os.path, "exists", lambda path: False)
    
    summary = query_system_status()
    assert summary["flash_session"] == "Not Found"
    
    summary2 = query_system_status(base_dir="/dummy/base")
    assert summary2["flash_session"] == "Not Found"

def test_main_function(monkeypatch, capsys):
    dummy_summary = {"status": "ok"}
    monkeypatch.setattr(
        "backend.agents.orchestration.get_system_status.query_system_status",
        lambda *args, **kwargs: dummy_summary
    )
    
    main()
    
    captured = capsys.readouterr()
    stdout_json = json.loads(captured.out)
    assert stdout_json == dummy_summary

def test_direct_script_execution():
    script_path = os.path.join(
        os.path.dirname(__file__), "..", "backend", "agents", "orchestration", "get_system_status.py"
    )
    script_path = os.path.abspath(script_path)
    
    res = subprocess.run([sys.executable, script_path], capture_output=True, text=True, check=True)
    
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert isinstance(data, dict)

def test_script_execution_via_runpy():
    import runpy
    runpy.run_module("backend.agents.orchestration.get_system_status", run_name="__main__")