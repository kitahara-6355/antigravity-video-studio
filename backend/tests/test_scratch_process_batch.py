import sys
import os
import json
from unittest.mock import patch, MagicMock, mock_open

# sys.path に backend を追加
sys.path.append(os.path.abspath("backend"))

import backend.scratch.process_batch as process_batch

def test_copy_files_from_worktree_not_exists():
    with patch("os.path.exists", return_value=False) as mock_exists, \
         patch("builtins.print") as mock_print:
        process_batch.copy_files_from_worktree("dummy_path")
        mock_exists.assert_called_once_with("dummy_path")
        mock_print.assert_any_call("      [Copy] Worktree path not found: dummy_path")

def test_copy_files_from_worktree_success():
    git_status_output = (
        "M  backend/agents/orchestration/orchestrator.py\n"
        "A  backend/scratch/process_batch.py\n"
        "?? temp_thumbnails/dummy.png\n"
        "?? content_dump.txt\n"
        "D  backend/agents/orchestration/some_config.json\n"
    )
    
    mock_run = MagicMock()
    mock_run.stdout = git_status_output
    
    def custom_isdir(path):
        if "isdir_test" in path:
            return True
        return False

    with patch("os.path.exists", return_value=True), \
         patch("subprocess.run", return_value=mock_run) as mock_sub_run, \
         patch("os.path.isdir", side_effect=custom_isdir), \
         patch("os.makedirs") as mock_makedirs, \
         patch("shutil.copy2") as mock_copy, \
         patch("builtins.print"):
        
        mock_run.stdout += "M  isdir_test\n"
        mock_run.stdout += 'M  "quoted_file.py"\n'

        process_batch.copy_files_from_worktree("dummy_wt")
        
        expected_quoted_dst = os.path.join(process_batch.parent_dir, "quoted_file.py")
        mock_copy.assert_any_call(os.path.join("dummy_wt", "quoted_file.py"), expected_quoted_dst)

def test_main_log_not_exists():
    mock_hub_cls = MagicMock()
    mock_hub = MagicMock()
    mock_hub.get_queue_status.return_value = {"batch_id": "test_batch"}
    mock_hub_cls.return_value = mock_hub
    
    def custom_open(path, mode="r", *args, **kwargs):
        path_str = str(path)
        if "task_queue.json" in path_str:
            return mock_open(read_data=json.dumps({"tasks": []}))()
        return mock_open(read_data="{}")()

    with patch("agents.orchestration.OrchestrationHub", mock_hub_cls, create=True), \
         patch("backend.agents.orchestration.OrchestrationHub", mock_hub_cls, create=True), \
         patch("os.path.exists", side_effect=lambda path: "task_queue.json" in str(path)), \
         patch("builtins.open", side_effect=custom_open), \
         patch("builtins.print") as mock_print:
        
        process_batch.main()
        mock_print.assert_any_call("Error: Log path not found: " + process_batch.log_path)

def test_main_full_process_success():
    mock_hub_cls = MagicMock()
    mock_hub = MagicMock()
    mock_hub.get_queue_status.return_value = {"batch_id": "test_batch"}
    mock_hub.get_phase_state.return_value = {"current_phase": 27, "current_milestone": "M27.1"}
    mock_hub.get_next_batch.return_value = [{"id": "next-task"}]
    mock_hub.generate_flash_status.return_value = {"formatted": "Status details"}
    mock_hub_cls.return_value = mock_hub
    
    # task-5 (pending のまま更新されない) を追加
    queue_data = {
        "tasks": [
            {"id": "task-1", "status": "pending", "group": "weaver1"},
            {"id": "task-2", "status": "pass", "group": "weaver2"},
            {"id": "task-3", "status": "fail", "group": "weaver3"},
            {"id": "task-4", "status": "skip", "group": "weaver4"},
            {"id": "task-5", "status": "pending", "group": "weaver5"}
        ]
    }
    
    # 偽の SYSTEM_MESSAGE (sender無し) を追加して L144-145 continue を実行させ、
    # 末尾に broken-json を追加して L91-92 except Exception を実行させる
    log_lines = [
        json.dumps({
            "type": "SYSTEM_MESSAGE",
            "content": "This is a system message without sender PASS"
        }),
        json.dumps({
            "type": "SYSTEM_MESSAGE",
            "content": "sender=a9736a64-a242-485f-942e-bf8476d21fa6 Task completed successfully. - [changed_file.py](file:///C:/wt1/changed_file.py) PASS"
        }),
        json.dumps({
            "type": "INVOKE_SUBAGENT",
            "status": "DONE",
            "content": '"conversationId": "a9736a64-a242-485f-942e-bf8476d21fa6" "workspaceUris" : [ "file:///C:/wt1" ] subagent-weaver1-Agent-'
        }),
        "broken-json-at-end{"
    ]
    
    def custom_exists(path):
        return True

    def custom_open(path, mode="r", *args, **kwargs):
        path_str = str(path)
        if "task_queue.json" in path_str:
            return mock_open(read_data=json.dumps(queue_data))()
        elif "transcript.jsonl" in path_str:
            mock_file = MagicMock()
            mock_file.__enter__.return_value = mock_file
            mock_file.readlines.return_value = log_lines
            mock_file.__iter__.return_value = iter(log_lines)
            return mock_file
        return mock_open(read_data="{}")()

    with patch("agents.orchestration.OrchestrationHub", mock_hub_cls, create=True), \
         patch("backend.agents.orchestration.OrchestrationHub", mock_hub_cls, create=True), \
         patch("os.path.exists", side_effect=custom_exists), \
         patch("builtins.open", side_effect=custom_open), \
         patch("backend.scratch.process_batch.copy_files_from_worktree") as mock_copy_wt, \
         patch("builtins.print") as mock_print:
        
        process_batch.main()
        
        mock_copy_wt.assert_called_once_with("C:\\wt1")
        mock_hub.mark_task_done.assert_called_once_with("task-1", "pass", {
            "message": "sender=a9736a64-a242-485f-942e-bf8476d21fa6 Task completed successfully. - [changed_file.py](file:///C:/wt1/changed_file.py) PASS",
            "changed_files": ["changed_file.py"]
        })
        mock_print.assert_any_call("    -> Still running")

def test_main_parser_exception():
    mock_hub_cls = MagicMock()
    mock_hub = MagicMock()
    mock_hub.get_queue_status.return_value = {"batch_id": "test_batch"}
    mock_hub_cls.return_value = mock_hub
    
    log_lines = [
        json.dumps({
            "type": "INVOKE_SUBAGENT",
            "status": "DONE",
            "content": 12345
        }),
        json.dumps({
            "type": "SYSTEM_MESSAGE",
            "content": None
        })
    ]
    
    def custom_open(path, mode="r", *args, **kwargs):
        path_str = str(path)
        if "task_queue.json" in path_str:
            return mock_open(read_data=json.dumps({"tasks": []}))()
        elif "transcript.jsonl" in path_str:
            mock_file = MagicMock()
            mock_file.__enter__.return_value = mock_file
            mock_file.readlines.return_value = log_lines
            mock_file.__iter__.return_value = iter(log_lines)
            return mock_file
        return mock_open(read_data="{}")()
        
    with patch("agents.orchestration.OrchestrationHub", mock_hub_cls, create=True), \
         patch("backend.agents.orchestration.OrchestrationHub", mock_hub_cls, create=True), \
         patch("os.path.exists", return_value=True), \
         patch("builtins.open", side_effect=custom_open), \
         patch("builtins.print") as mock_print:
         
        process_batch.main()
        mock_print.assert_any_call("Error parsing latest INVOKE_SUBAGENT: 'int' object has no attribute 'split'")

def test_main_failed_task_success():
    mock_hub_cls = MagicMock()
    mock_hub = MagicMock()
    mock_hub.get_queue_status.return_value = {"batch_id": "test_batch"}
    mock_hub.get_phase_state.return_value = {"current_phase": 27, "current_milestone": "M27.1"}
    mock_hub.get_next_batch.return_value = []
    mock_hub.generate_flash_status.return_value = {"formatted": "Status details"}
    mock_hub_cls.return_value = mock_hub
    
    queue_data = {
        "tasks": [
            {"id": "task-1", "status": "pending", "group": "weaver1"}
        ]
    }
    
    log_lines = [
        json.dumps({
            "type": "SYSTEM_MESSAGE",
            "content": "sender=a9736a64-a242-485f-942e-bf8476d21fa6 Task FAILED with errors"
        }),
        json.dumps({
            "type": "INVOKE_SUBAGENT",
            "status": "DONE",
            "content": '"conversationId": "a9736a64-a242-485f-942e-bf8476d21fa6" "workspaceUris" : [ "file:///C:/wt1" ] subagent-weaver1-Agent-'
        }),
        "broken-json-at-end{"
    ]
    
    def custom_open(path, mode="r", *args, **kwargs):
        path_str = str(path)
        if "task_queue.json" in path_str:
            return mock_open(read_data=json.dumps(queue_data))()
        elif "transcript.jsonl" in path_str:
            mock_file = MagicMock()
            mock_file.__enter__.return_value = mock_file
            mock_file.readlines.return_value = log_lines
            mock_file.__iter__.return_value = iter(log_lines)
            return mock_file
        return mock_open(read_data="{}")()

    with patch("agents.orchestration.OrchestrationHub", mock_hub_cls, create=True), \
         patch("backend.agents.orchestration.OrchestrationHub", mock_hub_cls, create=True), \
         patch("os.path.exists", return_value=True), \
         patch("builtins.open", side_effect=custom_open), \
         patch("backend.scratch.process_batch.copy_files_from_worktree"), \
         patch("builtins.print") as mock_print:
        
        process_batch.main()
        
        mock_print.assert_any_call("    -> Marking task as fail")
        mock_hub.mark_task_done.assert_called_once_with("task-1", "fail", {
            "message": "sender=a9736a64-a242-485f-942e-bf8476d21fa6 Task FAILED with errors",
            "changed_files": []
        })

def test_main_mark_task_done_exception():
    mock_hub_cls = MagicMock()
    mock_hub = MagicMock()
    mock_hub.get_queue_status.return_value = {"batch_id": "test_batch"}
    mock_hub.mark_task_done.side_effect = OSError("Mark Error")
    mock_hub_cls.return_value = mock_hub

    queue_data = {
        "tasks": [
            {"id": "task-1", "status": "pending", "group": "weaver1"}
        ]
    }

    log_lines = [
        json.dumps({
            "type": "SYSTEM_MESSAGE",
            "content": "sender=a9736a64-a242-485f-942e-bf8476d21fa6 Task completed successfully. - [changed_file.py](file:///C:/wt1/changed_file.py) PASS"
        }),
        json.dumps({
            "type": "INVOKE_SUBAGENT",
            "status": "DONE",
            "content": '"conversationId": "a9736a64-a242-485f-942e-bf8476d21fa6" "workspaceUris" : [ "file:///C:/wt1" ] subagent-weaver1-Agent-'
        }),
        "broken-json-at-end{"
    ]

    def custom_open(path, mode="r", *args, **kwargs):
        path_str = str(path)
        if "task_queue.json" in path_str:
            return mock_open(read_data=json.dumps(queue_data))()
        elif "transcript.jsonl" in path_str:
            mock_file = MagicMock()
            mock_file.__enter__.return_value = mock_file
            mock_file.readlines.return_value = log_lines
            mock_file.__iter__.return_value = iter(log_lines)
            return mock_file
        return mock_open(read_data="{}")()

    with patch("agents.orchestration.OrchestrationHub", mock_hub_cls, create=True), \
         patch("backend.agents.orchestration.OrchestrationHub", mock_hub_cls, create=True), \
         patch("os.path.exists", return_value=True), \
         patch("builtins.open", side_effect=custom_open), \
         patch("backend.scratch.process_batch.copy_files_from_worktree"), \
         patch("builtins.print") as mock_print:
        
        process_batch.main()
        
        mock_print.assert_any_call("    [Warning] mark_task_done failed for task-1: Mark Error")

def test_main_hub_exceptions():
    mock_hub_cls = MagicMock()
    mock_hub = MagicMock()
    mock_hub.get_queue_status.return_value = {"batch_id": "test_batch"}
    mock_hub.submit_batch_report.side_effect = OSError("Submit Error")
    mock_hub_cls.return_value = mock_hub

    queue_data = {
        "tasks": [
            {"id": "task-1", "status": "pending", "group": "weaver1"}
        ]
    }

    log_lines = [
        json.dumps({
            "type": "SYSTEM_MESSAGE",
            "content": "sender=a9736a64-a242-485f-942e-bf8476d21fa6 Task completed successfully. - [changed_file.py](file:///C:/wt1/changed_file.py) PASS"
        }),
        json.dumps({
            "type": "INVOKE_SUBAGENT",
            "status": "DONE",
            "content": '"conversationId": "a9736a64-a242-485f-942e-bf8476d21fa6" "workspaceUris" : [ "file:///C:/wt1" ] subagent-weaver1-Agent-'
        }),
        "broken-json-at-end{"
    ]

    def custom_open(path, mode="r", *args, **kwargs):
        path_str = str(path)
        if "task_queue.json" in path_str:
            return mock_open(read_data=json.dumps(queue_data))()
        elif "transcript.jsonl" in path_str:
            mock_file = MagicMock()
            mock_file.__enter__.return_value = mock_file
            mock_file.readlines.return_value = log_lines
            mock_file.__iter__.return_value = iter(log_lines)
            return mock_file
        return mock_open(read_data="{}")()

    with patch("agents.orchestration.OrchestrationHub", mock_hub_cls, create=True), \
         patch("backend.agents.orchestration.OrchestrationHub", mock_hub_cls, create=True), \
         patch("os.path.exists", return_value=True), \
         patch("builtins.open", side_effect=custom_open), \
         patch("backend.scratch.process_batch.copy_files_from_worktree"), \
         patch("builtins.print") as mock_print:
        
        process_batch.main()
        
        mock_print.assert_any_call("[Warning] submit_batch_report failed: Submit Error")

def test_main_no_queue():
    mock_hub_cls = MagicMock()
    mock_hub = MagicMock()
    mock_hub.get_queue_status.return_value = {}
    mock_hub.generate_flash_status.return_value = {"formatted": "Status details"}
    mock_hub_cls.return_value = mock_hub

    # log_path は True（存在）、task_queue.json は False（存在しない）を返すようにする
    def custom_exists(path):
        path_str = str(path)
        if "task_queue.json" in path_str:
            return False
        return True

    with patch("agents.orchestration.OrchestrationHub", mock_hub_cls, create=True), \
         patch("backend.agents.orchestration.OrchestrationHub", mock_hub_cls, create=True), \
         patch("os.path.exists", side_effect=custom_exists), \
         patch("builtins.open", return_value=mock_open(read_data="{}")()), \
         patch("builtins.print") as mock_print:
         
        process_batch.main()
        mock_print.assert_any_call("=== STATUS_END ===")

def test_resolve_subagents_from_log_not_exists():
    with patch("os.path.exists", return_value=False) as mock_exists, \
         patch("builtins.print") as mock_print:
        subagent_to_task, subagent_to_path = process_batch._resolve_subagents_from_log("non_existent_log.jsonl", {})
        assert subagent_to_task == {}
        assert subagent_to_path == {}
        mock_print.assert_any_call("Error: Log path not found: non_existent_log.jsonl")

def test_resolve_subagents_from_log_parser_exception():
    log_lines = [
        json.dumps({
            "type": "INVOKE_SUBAGENT",
            "status": "DONE",
            "content": 12345
        })
    ]
    def custom_open(path, mode="r", *args, **kwargs):
        mock_file = MagicMock()
        mock_file.__enter__.return_value = mock_file
        mock_file.readlines.return_value = log_lines
        mock_file.__iter__.return_value = iter(log_lines)
        return mock_file

    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", side_effect=custom_open), \
         patch("builtins.print") as mock_print:
        subagent_to_task, subagent_to_path = process_batch._resolve_subagents_from_log("dummy_log.jsonl", {})
        mock_print.assert_any_call("Error parsing latest INVOKE_SUBAGENT: 'int' object has no attribute 'split'")

def test_scan_task_results_not_exists():
    with patch("os.path.exists", return_value=False):
        results = process_batch._scan_task_results("non_existent_log.jsonl", {})
        assert results == {}




def test_main_mark_task_done_specific_exceptions():
    mock_hub_cls = MagicMock()
    mock_hub = MagicMock()
    mock_hub.get_queue_status.return_value = {"batch_id": "test_batch"}
    mock_hub.mark_task_done.side_effect = OSError("Disk full")
    mock_hub_cls.return_value = mock_hub

    queue_data = {
        "tasks": [
            {"id": "task-1", "status": "pending", "group": "weaver1"}
        ]
    }

    log_lines = [
        json.dumps({
            "type": "SYSTEM_MESSAGE",
            "content": "sender=a9736a64-a242-485f-942e-bf8476d21fa6 Task completed successfully. PASS"
        }),
        json.dumps({
            "type": "INVOKE_SUBAGENT",
            "status": "DONE",
            "content": '"conversationId": "a9736a64-a242-485f-942e-bf8476d21fa6" "workspaceUris" : [ "file:///C:/wt1" ] subagent-weaver1-Agent-'
        })
    ]

    def custom_open(path, mode="r", *args, **kwargs):
        path_str = str(path)
        if "task_queue.json" in path_str:
            return mock_open(read_data=json.dumps(queue_data))()
        elif "transcript.jsonl" in path_str:
            mock_file = MagicMock()
            mock_file.__enter__.return_value = mock_file
            mock_file.readlines.return_value = log_lines
            mock_file.__iter__.return_value = iter(log_lines)
            return mock_file
        return mock_open(read_data="{}")()

    with patch("agents.orchestration.OrchestrationHub", mock_hub_cls, create=True),          patch("backend.agents.orchestration.OrchestrationHub", mock_hub_cls, create=True),          patch("os.path.exists", return_value=True),          patch("builtins.open", side_effect=custom_open),          patch("backend.scratch.process_batch.copy_files_from_worktree"),          patch("builtins.print") as mock_print:
        
        process_batch.main()
        
        mock_print.assert_any_call("    [Warning] mark_task_done failed for task-1: Disk full")

def test_main_submit_batch_report_specific_exceptions():
    mock_hub_cls = MagicMock()
    mock_hub = MagicMock()
    mock_hub.get_queue_status.return_value = {"batch_id": "test_batch"}
    mock_hub.submit_batch_report.side_effect = TimeoutError("Lock timeout")
    mock_hub_cls.return_value = mock_hub

    queue_data = {
        "tasks": [
            {"id": "task-1", "status": "pending", "group": "weaver1"}
        ]
    }

    log_lines = [
        json.dumps({
            "type": "SYSTEM_MESSAGE",
            "content": "sender=a9736a64-a242-485f-942e-bf8476d21fa6 Task completed successfully. PASS"
        }),
        json.dumps({
            "type": "INVOKE_SUBAGENT",
            "status": "DONE",
            "content": '"conversationId": "a9736a64-a242-485f-942e-bf8476d21fa6" "workspaceUris" : [ "file:///C:/wt1" ] subagent-weaver1-Agent-'
        })
    ]

    def custom_open(path, mode="r", *args, **kwargs):
        path_str = str(path)
        if "task_queue.json" in path_str:
            return mock_open(read_data=json.dumps(queue_data))()
        elif "transcript.jsonl" in path_str:
            mock_file = MagicMock()
            mock_file.__enter__.return_value = mock_file
            mock_file.readlines.return_value = log_lines
            mock_file.__iter__.return_value = iter(log_lines)
            return mock_file
        return mock_open(read_data="{}")()

    with patch("agents.orchestration.OrchestrationHub", mock_hub_cls, create=True),          patch("backend.agents.orchestration.OrchestrationHub", mock_hub_cls, create=True),          patch("os.path.exists", return_value=True),          patch("builtins.open", side_effect=custom_open),          patch("backend.scratch.process_batch.copy_files_from_worktree"),          patch("builtins.print") as mock_print:
        
        process_batch.main()
        
        mock_print.assert_any_call("[Warning] submit_batch_report failed: Lock timeout")

def test_resolve_subagents_from_log_type_error():
    log_lines = [json.dumps({"type": "INVOKE_SUBAGENT", "status": "DONE", "content": None})]

    def custom_open(path, mode="r", *args, **kwargs):
        mock_file = MagicMock()
        mock_file.__enter__.return_value = mock_file
        mock_file.readlines.return_value = log_lines
        mock_file.__iter__.return_value = iter(log_lines)
        return mock_file

    with patch("os.path.exists", return_value=True),          patch("builtins.open", side_effect=custom_open),          patch("builtins.print") as mock_print:
         
        subagent_to_task, subagent_to_path = process_batch._resolve_subagents_from_log("dummy_log.jsonl", {})
        assert subagent_to_task == {}
        assert subagent_to_path == {}
        any_error_printed = any("Error parsing latest INVOKE_SUBAGENT" in call[0][0] for call in mock_print.call_args_list)
        assert any_error_printed
