# -*- coding: utf-8 -*-
import json
from datetime import datetime, timezone
from pathlib import Path

session_path = Path("c:/Users/PC_User/Desktop/script/video-automation/backend/agents/orchestration/flash_session.json")

with open(session_path, "r", encoding="utf-8") as f:
    session = json.load(f)

session["subagents_running"] = 4
session["current_step"] = "バッチ batch_d6d052: 4タスク実行中 (1件クオータエラーにより一時退避)"

err_entry = {
    "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "error": "サブエージェント aaf658d9-4635-4f1e-a64d-2bd7f240a7b9 (T-batch_d6d052-test_weaver-008) 起動失敗: RESOURCE_EXHAUSTED (code 429)",
    "module": "routers/themes_router.py"
}
session["recent_errors"].insert(0, err_entry)
session["recent_errors"] = session["recent_errors"][:10]

session["last_heartbeat"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

with open(session_path, "w", encoding="utf-8") as f:
    json.dump(session, f, ensure_ascii=False, indent=2)

print("Updated flash_session.json for quota error.")
