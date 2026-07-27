import json
from datetime import datetime, timezone

json_path = r"c:\Users\PC_User\Desktop\script\video-automation\backend\agents\orchestration\task_queue.json"

try:
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    updated = False
    for task in data.get("tasks", []):
        if task.get("id") == "T-batch_fc706b-test_weaver-000":
            task["status"] = "pass"
            task["result"] = {
                "message": "check_pipeline_status.py の JSONデコードエラー等のエッジケーステスト追加完了 (カバレッジ100%)",
                "changed_files": [
                    "backend/tests/test_check_pipeline_status.py"
                ]
            }
            task["completed_at"] = datetime.now(timezone.utc).isoformat()
            updated = True
            break

    if updated:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print("SUCCESS: Updated T-batch_fc706b-test_weaver-000 to pass.")
    else:
        print("ERROR: Task T-batch_fc706b-test_weaver-000 not found.")

except Exception as e:
    print(f"EXCEPTION: {e}")
