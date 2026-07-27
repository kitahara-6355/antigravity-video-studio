import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    # get_next_batch
    batch = hub.get_next_batch(26, "M26.1", batch_size=6)
    print("--- Batch Tasks ---")
    for task in batch:
        print(f"ID: {task['id']}")
        print(f"Group: {task['group']}")
        print(f"Target Module: {task['target_module']}")
        print(f"Instruction: {task['instruction']}")
        print("--------------------")

if __name__ == "__main__":
    main()
