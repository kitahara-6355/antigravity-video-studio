# -*- coding: utf-8 -*-
import sys
from pathlib import Path
sys.path.insert(0, str(Path(r"C:\Users\PC_User\Desktop\script\video-automation\backend")))
sys.path.insert(0, str(Path(r"C:\Users\PC_User\Desktop\script\video-automation")))

import json
from backend.agents.orchestration import OrchestrationHub
from backend.agents.orchestration.orchestrator import TASK_QUEUE_PATH

def main():
    hub = OrchestrationHub()

    # 1. 429エラーをセッションに報告（スロットリングを作動させる）
    hub.flash_report_error(
        "RESOURCE_EXHAUSTED (code 429) on edge_case Agent (council_graph)",
        module="agents/council_graph.py"
    )

    # 2. タスクを pending に戻す
    with open(TASK_QUEUE_PATH, "r", encoding="utf-8") as f:
        queue = json.load(f)

    for task in queue.get("tasks", []):
        if task["id"] == "T-batch_d6d052-edge_case-003":
            task["status"] = "pending"
            task["started_at"] = None
            task["assigned_agent"] = None
            print("Reset task T-batch_d6d052-edge_case-003 to pending.")
            break

    with open(TASK_QUEUE_PATH, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
