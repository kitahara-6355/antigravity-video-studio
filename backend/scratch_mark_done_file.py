import sys
import json
from agents.orchestration import OrchestrationHub

def main():
    if len(sys.argv) < 2:
        print("Usage: python scratch_mark_done_file.py <json_file_path>")
        sys.exit(1)
        
    json_path = sys.argv[1]
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    task_id = data["task_id"]
    status = data["status"]
    report = data["report"]
    
    hub = OrchestrationHub()
    hub.mark_task_done(task_id, status, report)
    print(f"Task {task_id} marked as {status} successfully from file.")

if __name__ == "__main__":
    main()
