import sys
import os

sys.path.insert(0, r"c:\Users\PC_User\Desktop\script\video-automation\backend")
sys.path.insert(0, r"c:\Users\PC_User\Desktop\script\video-automation")

from backend.agents.memory.technical_debt import TechnicalDebtStore

def main():
    store = TechnicalDebtStore()
    
    # TD-1287 (Agent 002)
    store.resolve_debt(
        debt_id="TD-1287",
        fixed_by="T-batch_ff20df-bug_hunter-002",
        fix_evidence="Broad except Exception was already refactored into specific exceptions in flash_assign_subagents_8.py, verified by pytest."
    )
    print("Resolved TD-1287")
    
    # TD-1288 (Agent 003)
    store.resolve_debt(
        debt_id="TD-1288",
        fixed_by="T-batch_ff20df-bug_hunter-003",
        fix_evidence="Resolved broad except in run_session_end.py by catching specific OSError, verified by pytest."
    )
    print("Resolved TD-1288")

if __name__ == "__main__":
    main()
