import os
import sys
import json
import re
from pathlib import Path

# PYTHONPATH の設定
root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, root_path)
sys.path.insert(0, os.path.join(root_path, "backend"))

from backend.agents.orchestration import OrchestrationHub
from backend.agents.orchestration.hub_common import TASK_QUEUE_PATH

def check_subagent_transcript(conv_id: str):
    # 指定された subagent の transcript.jsonl を確認し、
    # 完了報告メッセージやステータスを抽出する。
    app_data_dir = os.environ.get("ANTIGRAVITY_APP_DATA") or os.path.join(os.path.expanduser("~"), ".gemini", "antigravity")
    transcript_path = Path(app_data_dir) / "brain" / conv_id / ".system_generated" / "logs" / "transcript.jsonl"
    
    if not transcript_path.exists():
        print(f"Transcript path not found for {conv_id}: {transcript_path}")
        return None
        
    print(f"Reading transcript for {conv_id}...")
    
    # 最後の数行を解析して完了報告メッセージを探す
    last_model_message = None
    last_tool_call_send_message = None
    
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    step = json.loads(line)
                    if step.get("source") == "MODEL":
                        content = step.get("content", "")
                        if content:
                            last_model_message = content
                        if step.get("type") == "PLANNER_RESPONSE":
                            # tool_calls をチェック
                            for tc in step.get("tool_calls", []):
                                if tc.get("name") == "send_message":
                                    args = tc.get("args", {})
                                    # args が文字列の場合があるのでデコード
                                    if isinstance(args, str):
                                        try:
                                            args = json.loads(args)
                                        except:
                                            pass
                                    if isinstance(args, dict):
                                        msg = args.get("Message", "")
                                        if isinstance(msg, str):
                                            if msg.startswith('"') and msg.endswith('"'):
                                                msg = msg[1:-1]
                                            msg = msg.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"')
                                        last_tool_call_send_message = msg
                except json.JSONDecodeError as e:
                    print(f"Error parsing line: {e}")
    except OSError as e:
        print(f"Error reading transcript for {conv_id}: {e}")
        return None
        
    # 切り詰めやメッセージング形式の揺らぎに対応するため、親への送信メッセージとモデルの最終メッセージを統合して判定対象とする
    search_texts = []
    if last_tool_call_send_message:
        search_texts.append(last_tool_call_send_message)
    if last_model_message:
        search_texts.append(last_model_message)
        
    if not search_texts:
        return None
        
    search_text = "\n".join(search_texts)
    
    result_status = None
    patterns = [
        r"(?:結果|result|status|判定結果|ステータス)[^a-zA-Z]*\b(pass|passed|fail|failed|skip|skipped)\b",
        r"(?:結果|result|status|判定結果|ステータス)[\s\S]{0,100}\b(pass|passed|fail|failed|skip|skipped)\b",
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, search_text, re.IGNORECASE)
        if matches:
            result_status = matches[-1].lower()
            break
            
    if not result_status:
        text_lower = search_text.lower()
        if re.search(r"結果\s*:\s*(?:fail|failed)|result\s*:\s*(?:fail|failed)|status\s*:\s*(?:fail|failed)", text_lower):
            result_status = "fail"
        elif re.search(r"結果\s*:\s*(?:pass|passed)|result\s*:\s*(?:pass|passed)|status\s*:\s*(?:pass|passed)", text_lower):
            result_status = "pass"
        elif re.search(r"結果\s*:\s*(?:skip|skipped)|result\s*:\s*(?:skip|skipped)|status\s*:\s*(?:skip|skipped)", text_lower):
            result_status = "skipped"
            
    if not result_status:
        return None
        
    status_mapping = {
        "pass": "pass",
        "passed": "pass",
        "fail": "fail",
        "failed": "fail",
        "skip": "skipped",
        "skipped": "skipped",
    }
    normalized_status = status_mapping.get(result_status, "pass")
        
    # レポートオブジェクトの組み立て
    raw_output = last_tool_call_send_message or last_model_message or ""
    if len(raw_output) > 2000:
        raw_output = raw_output[:1000] + "\n... [TRUNCATED] ...\n" + raw_output[-1000:]

    report = {
        "message": "Collected from subagent transcript.",
        "raw_output": raw_output
    }
    
    # 変更ファイルの抽出（WindowsとLinux両方のパス区切りに対応し、/ に正規化する）
    # 引用符の有無に関わらず抽出できるように調整
    changed_files = re.findall(r"(backend[/\\][a-zA-Z0-9_\-\\./]+\.py)", raw_output)
    report["changed_files"] = list(set(f.replace("\\", "/") for f in changed_files)) if changed_files else []
    
    return {
        "status": normalized_status,
        "report": report
    }

def main():
    hub = OrchestrationHub()
    # 最優先で心拍更新 (心拍レジリエンス規約)
    hub.flash_update_heartbeat()
    
    # task_queue.json の読み込み
    queue_path = TASK_QUEUE_PATH
    if not queue_path.exists():
        print("task_queue.json not found.")
        sys.exit(1)
        
    with open(queue_path, "r", encoding="utf-8") as f:
        queue = json.load(f)
        
    current_batch_id = queue.get("current_batch_id")
    print(f"Current Batch ID: {current_batch_id}")
    
    all_completed = True
    any_marked = False
    
    for task in queue.get("tasks", []):
        task_id = task["id"]
        status = task["status"]
        
        if status in ("pass", "skipped", "fail"):
            continue
            
        # pending もしくは running
        conv_id = task.get("assigned_agent")
        if not conv_id:
            print(f"No active subagent found for task {task_id}")
            all_completed = False
            continue
            
        try:
            result = check_subagent_transcript(conv_id)
            if result:
                print(f"Subagent {conv_id} completed task {task_id} with status: {result['status']}")
                # mark_task_done
                hub.mark_task_done(task_id, result["status"], result["report"])
                any_marked = True
            else:
                print(f"Subagent {conv_id} for task {task_id} is still running...")
                all_completed = False
        except OSError as e:
            print(f"Error checking subagent {conv_id} for task {task_id}: {e}")
            all_completed = False
            
    if any_marked:
        # 心拍更新
        hub.flash_update_heartbeat()
        
    # 最新のキュー状態を再読込して確認
    with open(queue_path, "r", encoding="utf-8") as f:
        queue = json.load(f)
        
    unfinished = [t["id"] for t in queue.get("tasks", []) if t["status"] not in ("pass", "skipped", "fail")]
    
    if not unfinished:
        print("All tasks in batch are completed! Submitting batch report...")
        # 結果の集計
        passed = sum(1 for t in queue["tasks"] if t["status"] == "pass")
        failed = sum(1 for t in queue["tasks"] if t["status"] == "fail")
        skipped = sum(1 for t in queue["tasks"] if t["status"] == "skipped")
        
        # バッチ完了報告
        hub.submit_batch_report(current_batch_id, {
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "total": len(queue["tasks"])
        })
        print(f"Batch {current_batch_id} submitted successfully.")
        
        # 次のバッチを取得
        state = hub.get_phase_state()
        phase = state.get("current_phase", 33)
        milestone = state.get("current_milestone", "M33.1")
        print(f"Fetching next batch for Phase {phase}, Milestone {milestone}...")
        next_batch = hub.get_next_batch(phase, milestone, batch_size=6)
        print(f"Next batch: {next_batch}")
        
    else:
        print(f"Remaining unfinished tasks: {unfinished}")
        
    # ステータスの出力
    status = hub.generate_flash_status()
    print("=== STATUS ===")
    print(status["formatted"])
    print("==============")

if __name__ == "__main__":
    main()
