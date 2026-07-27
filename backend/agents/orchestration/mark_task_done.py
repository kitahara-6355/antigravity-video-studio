import sys
import json
from backend.agents.orchestration import OrchestrationHub

def main():
    if len(sys.argv) < 3:
        print("Usage: python mark_task_done.py <task_id> <result> '<report_json>'")
        sys.exit(1)
        
    task_id = sys.argv[1]
    result = sys.argv[2]
    
    report_data = None
    if len(sys.argv) >= 4:
        if sys.argv[3] == '-':
            try:
                report_data = json.loads(sys.stdin.read())
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                print(f"Failed to parse JSON from stdin: {e}")
                sys.exit(1)
        else:
            try:
                report_data = json.loads(sys.argv[3])
            except json.JSONDecodeError as e:
                print(f"Failed to parse JSON argument: {e}")
                sys.exit(1)
                
    hub = OrchestrationHub()
    hub.mark_task_done(task_id, result, report_data)
    print(f"Successfully marked task {task_id} as {result}")

if __name__ == "__main__":
    main()
