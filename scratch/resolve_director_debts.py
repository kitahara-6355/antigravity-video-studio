import sys
import os

repo_path = r"c:\Users\PC_User\Desktop\script\video-automation"
sys.path.append(repo_path)
sys.path.append(os.path.join(repo_path, "backend"))

from backend.agents.memory.technical_debt import TechnicalDebtStore

store = TechnicalDebtStore()
entries = store.get_entries_by_file("routers/director.py")
resolved_count = 0
for entry in entries:
    if entry.status == "open":
        store.resolve_debt(
            debt_id=entry.debt_id,
            fixed_by="T-batch_27b234-docker-002",
            fix_evidence="Implemented HTTPException raise guard before except Exception, translating generic errors to 500 with TDR registration.",
        )
        resolved_count += 1

print(f"Resolved {resolved_count} open debts for routers/director.py")
