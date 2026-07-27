# -*- coding: utf-8 -*-
import sys
import io
import os

# Insert project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Ensure UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    # 1. Update heartbeat first (Step 0)
    print("Updating heartbeat...")
    hub.flash_update_heartbeat()
    
    # 2. Generate flash status
    print("Generating status...")
    status = hub.generate_flash_status()
    print("=== STATUS_START ===")
    print(status["formatted"])
    print("=== STATUS_END ===")
    
    # Also print raw JSON parameters for self-check
    print(f"Context: {status.get('context_consumption_pct', 0)}")
    print(f"Batch: {status.get('batch_index', 0)}/{status.get('batch_total', 0)}")
    print(f"Tasks: {status.get('task_index', 0)}/{status.get('task_total', 0)}")

if __name__ == "__main__":
    main()
