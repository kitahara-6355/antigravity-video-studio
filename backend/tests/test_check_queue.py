# -*- coding: utf-8 -*-
import json
import os
import runpy
import pytest
from unittest.mock import MagicMock
from backend.scratch.check_queue import check

def test_check_queue_all_missing(capsys):
    # Test case when all files are missing
    check(
        queue_path="nonexistent_queue.json",
        session_path="nonexistent_session.json",
        phase_path="nonexistent_phase.json"
    )
    captured = capsys.readouterr()
    assert "No phase state found." in captured.out
    assert "No session state found." in captured.out
    assert "No task queue found." in captured.out

def test_check_queue_all_present(tmp_path, capsys):
    # Test case when all files are present with data
    phase_data = {
        "current_phase": 15,
        "current_milestone": "M15.1",
        "last_batch_id": "batch_abc",
        "flash_tasks_total": 10,
        "flash_tasks_passed": 8,
        "flash_tasks_failed": 2
    }
    session_data = {
        "consecutive_failures": 1,
        "recent_errors": ["Error 1", "Error 2"]
    }
    queue_data = {
        "current_batch_id": "batch_abc",
        "tasks": [
            {"id": "t1", "group": "auth", "target_module": "m1", "status": "pass", "assigned_agent": "agent1"},
            {"id": "t2", "group": "api", "target_module": "m2", "status": "fail", "assigned_agent": "agent2"}
        ]
    }

    phase_file = tmp_path / "phase_state.json"
    session_file = tmp_path / "flash_session.json"
    queue_file = tmp_path / "task_queue.json"

    phase_file.write_text(json.dumps(phase_data), encoding="utf-8")
    session_file.write_text(json.dumps(session_data), encoding="utf-8")
    queue_file.write_text(json.dumps(queue_data), encoding="utf-8")

    check(
        queue_path=str(queue_file),
        session_path=str(session_file),
        phase_path=str(phase_file)
    )

    captured = capsys.readouterr()
    
    # Phase State Assertions
    assert "Current Phase: 15" in captured.out
    assert "Current Milestone: M15.1" in captured.out
    assert "Last Batch ID (Phase State): batch_abc" in captured.out
    assert "Total: 10, Passed: 8, Failed: 2" in captured.out

    # Session State Assertions
    assert "Consecutive Failures: 1" in captured.out
    assert "Recent Errors Count: 2" in captured.out
    assert "- Error 1" in captured.out
    assert "- Error 2" in captured.out

    # Task Queue Assertions
    assert "Current Batch ID in Queue: batch_abc" in captured.out
    assert "Total tasks in queue: 2" in captured.out
    assert "Status summary: {'pass': 1, 'fail': 1}" in captured.out
    assert "- ID: t1 | Group: auth | Target: m1 | Status: pass | Agent: agent1" in captured.out
    assert "- ID: t2 | Group: api | Target: m2 | Status: fail | Agent: agent2" in captured.out

def test_check_queue_session_no_errors(tmp_path, capsys):
    # Test case when recent_errors is empty
    session_data = {
        "consecutive_failures": 0,
        "recent_errors": []
    }
    session_file = tmp_path / "flash_session.json"
    session_file.write_text(json.dumps(session_data), encoding="utf-8")

    check(
        queue_path="nonexistent_queue.json",
        session_path=str(session_file),
        phase_path="nonexistent_phase.json"
    )

    captured = capsys.readouterr()
    assert "Consecutive Failures: 0" in captured.out
    assert "Recent Errors Count: 0" in captured.out
    assert "Recent Errors:" not in captured.out

def test_check_queue_default_paths_with_env(tmp_path, monkeypatch, capsys):
    # Test case when paths are omitted and resolved dynamically using the env var
    monkeypatch.setenv("VIDEO_AUTOMATION_ROOT", str(tmp_path))

    phase_dir = tmp_path / "backend" / "agents" / "memory"
    queue_dir = tmp_path / "backend" / "agents" / "orchestration"
    phase_dir.mkdir(parents=True, exist_ok=True)
    queue_dir.mkdir(parents=True, exist_ok=True)

    phase_file = phase_dir / "phase_state.json"
    session_file = queue_dir / "flash_session.json"
    queue_file = queue_dir / "task_queue.json"

    phase_file.write_text(json.dumps({"current_phase": 15}), encoding="utf-8")
    session_file.write_text(json.dumps({"consecutive_failures": 0}), encoding="utf-8")
    queue_file.write_text(json.dumps({"tasks": []}), encoding="utf-8")

    check() # Runs with default parameters

    captured = capsys.readouterr()
    assert "Current Phase: 15" in captured.out
    assert "Consecutive Failures: 0" in captured.out
    assert "Total tasks in queue: 0" in captured.out

def test_check_queue_fallback_paths(monkeypatch, capsys):
    # Set a dummy root path to ensure default path checks fail
    monkeypatch.setenv("VIDEO_AUTOMATION_ROOT", "nonexistent_root_path_to_force_fallback")

    # Test fallback path resolution when default path is missing but fallback exists
    def mock_exists(path):
        if "nonexistent_root_path" in path:
            return False
        if "c:\\Users\\PC_User\\Desktop\\script" in path:
            return True
        return False

    monkeypatch.setattr(os.path, "exists", mock_exists)

    import builtins
    
    def mock_open(file, mode="r", *args, **kwargs):
        mock_file = MagicMock()
        mock_file.__enter__.return_value = mock_file
        if "phase_state.json" in file:
            mock_file.read.return_value = '{"current_phase": 15}'
        elif "flash_session.json" in file:
            mock_file.read.return_value = '{"consecutive_failures": 0, "recent_errors": []}'
        elif "task_queue.json" in file:
            mock_file.read.return_value = '{"current_batch_id": "b1", "tasks": []}'
        else:
            mock_file.read.return_value = '{}'
        return mock_file

    monkeypatch.setattr(builtins, "open", mock_open)

    check()

    captured = capsys.readouterr()
    assert "Current Phase: 15" in captured.out
    assert "Consecutive Failures: 0" in captured.out
    assert "Current Batch ID in Queue: b1" in captured.out

def test_check_queue_main(monkeypatch, tmp_path, capsys):
    # Cover the if __name__ == "__main__" block using runpy
    original_exists = os.path.exists
    def mock_exists(path):
        # Only allow paths inside the tmp_path; reject system fallbacks during this test
        if str(tmp_path) in path:
            return original_exists(path)
        return False
    monkeypatch.setattr(os.path, "exists", mock_exists)

    monkeypatch.setenv("VIDEO_AUTOMATION_ROOT", str(tmp_path))
    
    # Remove module from sys.modules to prevent RuntimeWarning
    import sys
    sys.modules.pop("backend.scratch.check_queue", None)
    
    runpy.run_module("backend.scratch.check_queue", run_name="__main__")
    
    captured = capsys.readouterr()
    assert "No phase state found." in captured.out


def test_check_queue_no_env_var(monkeypatch, capsys):
    # Test path resolution when VIDEO_AUTOMATION_ROOT is not set in environment
    monkeypatch.delenv("VIDEO_AUTOMATION_ROOT", raising=False)
    
    # We mock os.path.exists to return False to avoid hitting actual files on disk
    monkeypatch.setattr(os.path, "exists", lambda x: False)
    
    check()
    captured = capsys.readouterr()
    assert "No phase state found." in captured.out
    assert "No session state found." in captured.out
    assert "No task queue found." in captured.out


def test_check_queue_partial_fallback(monkeypatch, capsys):
    # Test case: phase_state and task_queue use fallback, session_state uses default (nonexistent -> fails)
    monkeypatch.setenv("VIDEO_AUTOMATION_ROOT", "dummy_root")
    
    def mock_exists(path):
        # Allow fallback paths for phase and queue to exist
        if "c:\\Users\\PC_User\\Desktop\\script" in path:
            if "phase_state.json" in path or "task_queue.json" in path:
                return True
        return False

    monkeypatch.setattr(os.path, "exists", mock_exists)

    import builtins
    from unittest.mock import MagicMock
    def mock_open(file, mode="r", *args, **kwargs):
        mock_file = MagicMock()
        mock_file.__enter__.return_value = mock_file
        if "phase_state.json" in file:
            mock_file.read.return_value = '{"current_phase": 99}'
        elif "task_queue.json" in file:
            mock_file.read.return_value = '{"tasks": []}'
        else:
            mock_file.read.return_value = '{}'
        return mock_file

    monkeypatch.setattr(builtins, "open", mock_open)

    check()
    captured = capsys.readouterr()
    assert "Current Phase: 99" in captured.out
    assert "No session state found." in captured.out
    assert "Total tasks in queue: 0" in captured.out


def test_check_queue_missing_keys_in_json(tmp_path, capsys):
    # Test JSON files missing expected keys
    phase_file = tmp_path / "phase_state.json"
    session_file = tmp_path / "flash_session.json"
    queue_file = tmp_path / "task_queue.json"

    # Write empty JSON objects or missing keys
    phase_file.write_text("{}", encoding="utf-8")
    session_file.write_text("{}", encoding="utf-8")
    queue_file.write_text("{}", encoding="utf-8")

    check(
        queue_path=str(queue_file),
        session_path=str(session_file),
        phase_path=str(phase_file)
    )

    captured = capsys.readouterr()
    assert "Current Phase: None" in captured.out
    assert "Current Milestone: None" in captured.out
    assert "Last Batch ID (Phase State): None" in captured.out
    assert "Total: None, Passed: None, Failed: None" in captured.out
    assert "Consecutive Failures: 0" in captured.out
    assert "Recent Errors Count: 0" in captured.out
    assert "Current Batch ID in Queue: None" in captured.out
    assert "Total tasks in queue: 0" in captured.out


def test_check_queue_tasks_missing_keys(tmp_path, capsys):
    # Test tasks in queue with missing keys in the dictionaries
    queue_file = tmp_path / "task_queue.json"
    queue_data = {
        "current_batch_id": "b_partial",
        "tasks": [
            # A task completely missing details
            {},
            # A task with partial details
            {"id": "t_partial", "status": "running"}
        ]
    }
    queue_file.write_text(json.dumps(queue_data), encoding="utf-8")

    check(
        queue_path=str(queue_file),
        session_path="nonexistent.json",
        phase_path="nonexistent.json"
    )

    captured = capsys.readouterr()
    assert "Total tasks in queue: 2" in captured.out
    assert "Status summary: {None: 1, 'running': 1}" in captured.out
    assert "- ID: None | Group: None | Target: None | Status: None | Agent: None" in captured.out
    assert "- ID: t_partial | Group: None | Target: None | Status: running | Agent: None" in captured.out


def test_check_queue_corrupted_json(tmp_path, capsys):
    # Test case when JSON files are present but corrupted (invalid syntax)
    phase_file = tmp_path / "phase_state.json"
    session_file = tmp_path / "flash_session.json"
    queue_file = tmp_path / "task_queue.json"

    # Write invalid JSON
    phase_file.write_text("{invalid_json", encoding="utf-8")
    session_file.write_text("{invalid_json", encoding="utf-8")
    queue_file.write_text("{invalid_json", encoding="utf-8")

    check(
        queue_path=str(queue_file),
        session_path=str(session_file),
        phase_path=str(phase_file)
    )

    captured = capsys.readouterr()
    assert "Error parsing phase state JSON" in captured.out
    assert "Error parsing session state JSON" in captured.out
    assert "Error parsing task queue JSON" in captured.out
