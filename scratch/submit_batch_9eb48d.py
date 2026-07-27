import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))
sys.path.insert(0, PROJECT_ROOT)

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    
    # Submit report
    hub.submit_batch_report("batch_9eb48d", {
        "passed": 6,
        "failed": 0,
        "skipped": 0,
        "total": 6
    })
    print("Batch batch_9eb48d report submitted successfully.\n")
    
    # Generate and print status
    status = hub.generate_flash_status()
    print("=== FLASH STATUS ===")
    print(status["formatted"])

if __name__ == "__main__":
    main()
