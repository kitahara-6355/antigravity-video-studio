import sys
import json
from backend.agents.orchestration import OrchestrationHub

def main():
    if len(sys.argv) < 5:
        print("Usage: python submit_batch.py <batch_id> <passed> <failed> <skipped>")
        sys.exit(1)
        
    batch_id = sys.argv[1]
    passed = int(sys.argv[2])
    failed = int(sys.argv[3])
    skipped = int(sys.argv[4])
    total = passed + failed + skipped
    
    try:
        hub = OrchestrationHub()
        hub.submit_batch_report(batch_id, {
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "total": total
        })
        print("SUCCESS")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
