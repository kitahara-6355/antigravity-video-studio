# -*- coding: utf-8 -*-
import sys
import os

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "backend"))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    
    # 1. submit_batch_report
    batch_id = "batch_f95bcd"
    print(f"Submitting batch report for {batch_id}...")
    try:
        hub.submit_batch_report(batch_id, {
            "passed": 6,
            "failed": 0,
            "skipped": 0,
            "total": 6
        })
        print("Batch report submitted.")
    except Exception as e:
        print(f"Batch report submission failed or already submitted: {e}")
    
    # 2. Update heartbeat
    print("Updating heartbeat...")
    hub.flash_heartbeat()
    
    # 3. Get next batch
    print("Getting next batch...")
    phase_state = hub.get_phase_state()
    phase = phase_state.get("current_phase")
    milestone = phase_state.get("current_milestone")
    print(f"Current phase: {phase}, Milestone: {milestone}")
    
    next_batch = hub.get_next_batch(
        phase=phase,
        milestone=milestone,
        batch_size=6
    )
    if next_batch:
        print(f"Next batch retrieved: {len(next_batch)} tasks.")
        for t in next_batch:
            print(f" - {t['id']} ({t['group']}) in {t['target_module']}")
    else:
        print("No more tasks or awaiting Opus review.")
        
    # 4. Generate flash status
    status = hub.generate_flash_status()
    print("=== STATUS ===")
    print(status.get("formatted", ""))
    print("=== END ===")

if __name__ == "__main__":
    main()
