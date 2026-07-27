import json
import os
import re
import shutil
import subprocess
import sys
import time

MY_CONV_ID = "a9736a64-a242-485f-942e-bf8476d21fa6"
log_path = r"C:\Users\PC_User\.gemini\antigravity\brain\a9736a64-a242-485f-942e-bf8476d21fa6\.system_generated\logs\transcript.jsonl"
parent_dir = r"C:\Users\PC_User\Desktop\script\video-automation"

def copy_files_from_worktree(worktree_path):
    if not os.path.exists(worktree_path):
        print(f"      [Copy] Worktree path not found: {worktree_path}")
        return
        
    print(f"      [Copy] Copying changes from: {os.path.basename(worktree_path)}")
    subprocess_result = subprocess.run(["git", "-c", "core.quotepath=false", "status", "--porcelain"], cwd=worktree_path, capture_output=True, text=True)
    git_status_lines = subprocess_result.stdout.splitlines()
    
    for line in git_status_lines:
        status_code = line[:2]
        file_rel_path = line[3:].strip()
        
        if file_rel_path.startswith('"') and file_rel_path.endswith('"'):
            file_rel_path = file_rel_path[1:-1]
            
        # コピー除外パターン
        if "temp_thumbnails" in file_rel_path or "content_dump.txt" in file_rel_path or "process_batch.py" in file_rel_path:
            continue
            
        # システムメタデータ（JSON等）の先祖返り防止除外
        if file_rel_path.endswith(".json") and ("agents/orchestration" in file_rel_path or "agents/memory" in file_rel_path):
            print(f"        [Skip System File] {file_rel_path}")
            continue
            
        src_file = os.path.join(worktree_path, file_rel_path)
        dst_file = os.path.join(parent_dir, file_rel_path)
        
        if os.path.isdir(src_file):
            continue
            
        print(f"        -> {file_rel_path} ({status_code})")
        os.makedirs(os.path.dirname(dst_file), exist_ok=True)
        shutil.copy2(src_file, dst_file)

def _load_task_queue(queue_path="backend/agents/orchestration/task_queue.json"):
    if os.path.exists(queue_path):
        with open(queue_path, "r", encoding="utf-8") as f:
            queue_data = json.load(f)
        return queue_data.get("tasks", [])
    return []

def _build_group_to_tasks_map(tasks):
    group_to_tasks = {}
    for task in tasks:
        group_name = task["group"]
        if group_name not in group_to_tasks:
            group_to_tasks[group_name] = []
        group_to_tasks[group_name].append(task["id"])
    return group_to_tasks

def _resolve_subagents_from_log(log_path, group_to_tasks):
    subagent_to_task = {}
    subagent_to_path = {}
    
    if not os.path.exists(log_path):
        print(f"Error: Log path not found: {log_path}")
        return subagent_to_task, subagent_to_path

    # INVOKE_SUBAGENT ログを末尾からスキャン (DONEステータスのみ)
    with open(log_path, "r", encoding="utf-8") as f:
        log_lines = f.readlines()
        
    latest_dispatch_log_line = None
    for line in reversed(log_lines):
        try:
            data = json.loads(line)
            if data.get("type") == "INVOKE_SUBAGENT" and data.get("status") == "DONE":
                latest_dispatch_log_line = line
                break
        except (json.JSONDecodeError, TypeError):
            pass
            
    if latest_dispatch_log_line:
        try:
            data = json.loads(latest_dispatch_log_line)
            content = data.get("content", "")
            
            parts = content.split('"conversationId":')
            for part in parts[1:]:
                conversation_id_match = re.search(r'^\s*\"([^\"]+)\"', part)
                if conversation_id_match:
                    conversation_id = conversation_id_match.group(1)
                    
                    workspace_match = re.search(r'\"workspaceUris\"\s*:\s*\[\s*\"file:///([^\"]+)\"\s*\]', part)
                    if workspace_match:
                        subagent_to_path[conversation_id] = os.path.normpath(workspace_match.group(1))
                        
                    worktree_group_match = re.search(r"subagent-([a-zA-Z0-9_-]+)-Agent-", part)
                    if worktree_group_match:
                        group_raw = worktree_group_match.group(1)
                        group_name = group_raw.replace("-", "_")
                        
                        if group_name in group_to_tasks:
                            assigned_task_ids = list(subagent_to_task.values())
                            for task_id in group_to_tasks[group_name]:
                                if task_id not in assigned_task_ids:
                                    subagent_to_task[conversation_id] = task_id
                                    break
        except (json.JSONDecodeError, AttributeError, TypeError, ValueError, IndexError) as e:
            print(f"Error parsing latest INVOKE_SUBAGENT: {e}")
            
    return subagent_to_task, subagent_to_path

def _scan_task_results(log_path, subagent_to_task):
    task_results = {}
    
    if not os.path.exists(log_path):
        return task_results
        
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                data = json.loads(line)
                if data.get("type") == "SYSTEM_MESSAGE":
                    content = data.get("content", "")
                    
                    sender_match = re.search(r"sender=([a-f0-9-]+)", content)
                    sender = sender_match.group(1) if sender_match else ""
                    
                    if sender in subagent_to_task:
                        task_id = subagent_to_task[sender]
                        status = "pass"
                        if "失敗" in content or "FAIL" in content or "fail" in content:
                            if "成功" not in content and "PASS" not in content:
                                status = "fail"
                        
                        report = {
                            "message": content[:500],
                            "changed_files": []
                        }
                        
                        files = re.findall(r"-\s*\[([^\]]+)\]\(file:///[^\)]+\)", content)
                        if files:
                            report["changed_files"] = files
                        
                        task_results[task_id] = {
                            "status": status,
                            "report": report,
                            "sender": sender
                        }
            except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
                pass
    return task_results

def _process_and_copy_tasks(hub, tasks, task_results, subagent_to_path):
    all_done = True
    passed_count = 0
    failed_count = 0
    skipped_count = 0
    
    for task in tasks:
        task_id = task["id"]
        task_status = task["status"]
        print(f"  - {task_id}: current_status={task_status}")
        
        if task_status in ("pass", "fail", "skip"):
            if task_status == "pass":
                passed_count += 1
            elif task_status == "fail":
                failed_count += 1
            else:
                skipped_count += 1
            continue
            
        if task_id in task_results:
            result_details = task_results[task_id]
            sender = result_details["sender"]
            
            # ファイルコピー
            worktree_path = subagent_to_path.get(sender)
            if worktree_path:
                copy_files_from_worktree(worktree_path)
                
            print(f"    -> Marking task as {result_details['status']}")
            try:
                hub.mark_task_done(task_id, result_details["status"], result_details["report"])
                if result_details["status"] == "pass":
                    passed_count += 1
                else:
                    failed_count += 1
            except (OSError, KeyError, ValueError, TypeError, TimeoutError) as e:
                print(f"    [Warning] mark_task_done failed for {task_id}: {e}")
                all_done = False
        else:
            print(f"    -> Still running")
            all_done = False
            
    return all_done, passed_count, failed_count, skipped_count

def _submit_batch_report_if_needed(hub, current_batch_id, tasks, all_done, passed, failed, skipped):
    if all_done and tasks:
        print("All tasks completed! Submitting batch report...")
        try:
            hub.submit_batch_report(current_batch_id, {
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "total": len(tasks)
            })
            print("Batch report submitted.")
            
            time.sleep(2)
            
            state = hub.get_phase_state()
            phase = state["current_phase"]
            milestone = state["current_milestone"]
            print(f"Getting next batch for Phase {phase}, Milestone {milestone}...")
            next_batch = hub.get_next_batch(phase, milestone, batch_size=6)
            print(f"Next batch loaded: {len(next_batch)} tasks.")
        except (OSError, KeyError, ValueError, TypeError, TimeoutError) as e:
            print(f"[Warning] submit_batch_report failed: {e}")

def main():
    sys.path.append(os.path.abspath("backend"))
    from agents.orchestration import OrchestrationHub
    
    hub = OrchestrationHub()
    hub.register_flash_conversation_id(MY_CONV_ID)
    
    queue = hub.get_queue_status()
    current_batch_id = queue.get("batch_id")
    print(f"Current Batch ID from Queue: {current_batch_id}")
    
    tasks = _load_task_queue()
    group_to_tasks = _build_group_to_tasks_map(tasks)
    
    if not os.path.exists(log_path):
        print(f"Error: Log path not found: {log_path}")
        return

    subagent_to_task, subagent_to_path = _resolve_subagents_from_log(log_path, group_to_tasks)
    
    print("Resolved subagent conversationId to task_id:")
    for cid, tid in subagent_to_task.items():
        print(f"  {cid} -> {tid} (path: {subagent_to_path.get(cid, 'unknown')})")

    task_results = _scan_task_results(log_path, subagent_to_task)
                
    print("Scanned task results:")
    for tid, res in task_results.items():
        print(f"  {tid}: status={res['status']}")

    print(f"Tasks in queue ({len(tasks)} total):")
    all_done, passed_count, failed_count, skipped_count = _process_and_copy_tasks(
        hub, tasks, task_results, subagent_to_path
    )

    _submit_batch_report_if_needed(
        hub, current_batch_id, tasks, all_done, passed_count, failed_count, skipped_count
    )

    # 5. ステータスを表示
    status = hub.generate_flash_status()
    print("=== STATUS_START ===")
    print(status["formatted"])
    print("=== STATUS_END ===")

if __name__ == "__main__":
    main()
