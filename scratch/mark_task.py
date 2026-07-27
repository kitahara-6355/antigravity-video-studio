# -*- coding: utf-8 -*-
import sys
import os

# add backend and root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../backend")))
sys.path.insert(1, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.agents.orchestration import OrchestrationHub

def main():
    if len(sys.argv) < 3:
        print("Usage: python mark_task.py <task_id> <status> [log_uri]")
        sys.exit(1)
    
    task_id = sys.argv[1]
    status = sys.argv[2]
    log_uri = sys.argv[3] if len(sys.argv) > 3 else None
    
    hub = OrchestrationHub()
    result = {"status": status}
    if log_uri:
        result["log_uri"] = log_uri
        
    hub.mark_task_done(task_id, status, result)
    print(f"Task {task_id} marked as {status}")

if __name__ == "__main__":
    main()
