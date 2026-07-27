import sys
import json
from backend.agents.orchestration import OrchestrationHub

def main():
    if len(sys.argv) < 3:
        print("Usage: python mark_done.py <task_id> <status> [report_json_str]")
        sys.exit(1)
        
    task_id = sys.argv[1]
    status = sys.argv[2]
    report = None
    
    if len(sys.argv) >= 4:
        try:
            report = json.loads(sys.argv[3])
        except Exception as e:
            print(f"Failed to parse report JSON: {e}")
            sys.exit(1)
            
    try:
        hub = OrchestrationHub()
        hub.mark_task_done(task_id, status, report)
        print("SUCCESS")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
