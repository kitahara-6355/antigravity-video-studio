import sys
import os
import json
from unittest.mock import patch, MagicMock
import pytest
from pathlib import Path
from datetime import datetime, timezone
from contextlib import ExitStack

import backend.agents.orchestration.orchestrator as orchestrator
from backend.agents.orchestration.orchestrator import OrchestrationHub
from backend.agents.orchestration.heartbeat_only import main

# 各パスを pytest の tmp_path で差し替える fixture
@pytest.fixture(autouse=True)
def mock_paths(tmp_path):
    t_base = tmp_path / 'orchestration'
    t_memory = tmp_path / 'memory'
    t_inbox = tmp_path / 'inbox'
    
    t_base.mkdir(parents=True, exist_ok=True)
    t_memory.mkdir(parents=True, exist_ok=True)
    t_inbox.mkdir(parents=True, exist_ok=True)
    
    # 関連モジュールをすべてインポートして sys.modules に登録する
    import sys
    import backend.agents.orchestration.hub_common as hub_common
    import backend.agents.orchestration.hub_session as hub_session
    import backend.agents.orchestration.hub_status as hub_status
    import backend.agents.orchestration.hub_batch as hub_batch
    import backend.agents.orchestration.hub_gate as hub_gate
    import backend.agents.orchestration.hub_reports as hub_reports
    import backend.agents.orchestration.orchestrator as orchestrator
    
    modules_to_patch = []
    target_suffixes = [
        "hub_common", "hub_session", "hub_status", "hub_batch",
        "hub_gate", "hub_reports", "orchestrator"
    ]
    for name, mod in list(sys.modules.items()):
        if mod is None:
            continue
        for suffix in target_suffixes:
            if name == suffix or name.endswith("." + suffix):
                if mod not in modules_to_patch:
                    modules_to_patch.append(mod)
                break
                
    path_vars = {
        'TASK_QUEUE_PATH': t_base / 'task_queue.json',
        'OPUS_DIRECTIVE_PATH': t_base / 'opus_directive.json',
        'FLASH_REPORTS_PATH': t_base / 'flash_reports.jsonl',
        'MESSAGE_BOX_PATH': t_base / 'message_box.jsonl',
        'PHASE_STATE_PATH': t_memory / 'phase_state.json',
        'PHASE_GATES_PATH': t_memory / 'phase_gates.json',
        'FLASH_SESSION_PATH': t_base / 'flash_session.json',
        'INBOX_DIR': t_inbox,
        '_PROJECT_ROOT': tmp_path,
    }
    
    with ExitStack() as stack:
        for m in modules_to_patch:
            for var_name, var_value in path_vars.items():
                if hasattr(m, var_name):
                    stack.enter_context(patch.object(m, var_name, var_value))
        yield

def test_heartbeat_only_main(capsys):
    session = {
        'status': 'running',
        'last_heartbeat': '2026-05-31T00:00:00Z'
    }
    orchestrator._write_json(orchestrator.FLASH_SESSION_PATH, session)
    
    queue = {
        'tasks': []
    }
    orchestrator._write_json(orchestrator.TASK_QUEUE_PATH, queue)
    
    state = {
        'current_phase': 5,
        'current_milestone': 'M5.1'
    }
    orchestrator._write_json(orchestrator.PHASE_STATE_PATH, state)

    # sys.argvをモックして不要な pytest の引数を排除する
    with patch('sys.argv', ['heartbeat_only.py', 'ce05d36d-f2c8-452b-8ea9-9053a1e718a0']):
        main()

    captured = capsys.readouterr()
    assert 'HEARTBEAT_UPDATED' in captured.out
    assert 'FLASH_STATUS:' in captured.out
    assert 'QUEUE_STATUS:' in captured.out

    new_session = orchestrator._read_json(orchestrator.FLASH_SESSION_PATH)
    assert new_session['conversation_id'] == 'ce05d36d-f2c8-452b-8ea9-9053a1e718a0'

def test_heartbeat_only_invalid_uuid(capsys):
    # 無効な UUID が渡された場合は SystemExit(1) になり、エラーが stderr に出力されること
    with patch('sys.argv', ['heartbeat_only.py', 'invalid-uuid-format']):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1
    
    captured = capsys.readouterr()
    assert "ERROR: Invalid conversation ID format: invalid-uuid-format" in captured.err

def test_heartbeat_only_exception(capsys):
    # 例外発生時に SystemExit(1) になり、エラーが stderr に出力されること
    with patch('sys.argv', ['heartbeat_only.py', 'ce05d36d-f2c8-452b-8ea9-9053a1e718a0']):
        # OrchestrationHub が初期化時に例外を投げるようにモックする
        with patch('backend.agents.orchestration.heartbeat_only.OrchestrationHub', side_effect=ValueError("Mock initialization failed")):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
            
    captured = capsys.readouterr()
    assert "ERROR: Failed to run heartbeat_only main: Mock initialization failed" in captured.err

def test_flash_update_heartbeat_auto_recovery():
    # TD-778: flash_update_heartbeat auto-recovery
    session = {
        'status': 'stopped',
        'auto_stop_reason': 'stale',
        'last_heartbeat': '2026-05-31T00:00:00Z'
    }
    orchestrator._write_json(orchestrator.FLASH_SESSION_PATH, session)
    
    hub = OrchestrationHub()
    hub.flash_update_heartbeat()
    
    new_session = orchestrator._read_json(orchestrator.FLASH_SESSION_PATH)
    assert new_session['status'] == 'running'
    assert new_session.get('auto_stop_reason') is None
    assert new_session.get('auto_stopped_at') is None
    
    event_log_path = Path(orchestrator.FLASH_SESSION_PATH).parent / 'event_log.jsonl'
    assert event_log_path.exists()
    
    with open(event_log_path, 'r', encoding='utf-8') as f:
        events = [json.loads(line) for line in f]
    assert len(events) > 0
    assert events[0]['lifecycle'] == 'AUTO_RECOVERED'
    assert 'stopped → running' in events[0]['change'][0]

def test_flash_heartbeat_auto_recovery():
    # TD-777: flash_heartbeat auto-recovery
    session = {
        'status': 'stopped',
        'auto_stop_reason': 'stale',
        'last_heartbeat': '2026-05-31T00:00:00Z'
    }
    orchestrator._write_json(orchestrator.FLASH_SESSION_PATH, session)
    
    hub = OrchestrationHub()
    hub.flash_heartbeat()
    
    new_session = orchestrator._read_json(orchestrator.FLASH_SESSION_PATH)
    assert new_session['status'] == 'running'
    assert new_session.get('auto_stop_reason') is None
    assert new_session.get('auto_stopped_at') is None
    
    event_log_path = Path(orchestrator.FLASH_SESSION_PATH).parent / 'event_log.jsonl'
    assert event_log_path.exists()
    
    with open(event_log_path, 'r', encoding='utf-8') as f:
        events = [json.loads(line) for line in f]
    assert len(events) > 0
    assert events[0]['lifecycle'] == 'AUTO_RECOVERED'
    assert 'stopped → running' in events[0]['change'][0]

def test_heartbeat_only_filenotfound(capsys):
    with patch('sys.argv', ['heartbeat_only.py', 'ce05d36d-f2c8-452b-8ea9-9053a1e718a0']):
        with patch('backend.agents.orchestration.heartbeat_only.OrchestrationHub', side_effect=FileNotFoundError("Session file missing")):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "ERROR: Configuration or session file not found: Session file missing" in captured.err

def test_heartbeat_only_permissionerror(capsys):
    with patch('sys.argv', ['heartbeat_only.py', 'ce05d36d-f2c8-452b-8ea9-9053a1e718a0']):
        with patch('backend.agents.orchestration.heartbeat_only.OrchestrationHub', side_effect=PermissionError("Access denied")):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "ERROR: Permission denied when accessing configuration or session file: Access denied" in captured.err

def test_heartbeat_only_jsondecodeerror(capsys):
    with patch('sys.argv', ['heartbeat_only.py', 'ce05d36d-f2c8-452b-8ea9-9053a1e718a0']):
        with patch('backend.agents.orchestration.heartbeat_only.OrchestrationHub', side_effect=json.JSONDecodeError("Expecting value", "{}", 0)):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "ERROR: Failed to parse session JSON: Expecting value" in captured.err

def test_heartbeat_only_traceback(capsys):
    with patch('sys.argv', ['heartbeat_only.py', 'ce05d36d-f2c8-452b-8ea9-9053a1e718a0']):
        with patch('backend.agents.orchestration.heartbeat_only.OrchestrationHub', side_effect=RuntimeError("Some runtime issue")):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "ERROR: Failed to run heartbeat_only main: Some runtime issue" in captured.err
    assert "Traceback (most recent call last):" in captured.err
    assert "RuntimeError: Some runtime issue" in captured.err
