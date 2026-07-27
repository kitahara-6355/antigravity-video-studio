import sys
import os

repo_path = r"c:\Users\PC_User\Desktop\script\video-automation"
sys.path.append(repo_path)
sys.path.append(os.path.join(repo_path, "backend"))

from backend.agents.memory.technical_debt import TechnicalDebtStore

store = TechnicalDebtStore()
entries = store.get_entries_by_file("routers/director.py")
accepted_count = 0
for entry in entries:
    if entry.status in ("open", "fixed"):
        store.accept_debt(
            debt_id=entry.debt_id,
            reason="FastAPI endpoint safety net: except HTTPException: raise guard is placed right before generic except Exception, translating other errors to 500 with logger.",
        )
        accepted_count += 1

print(f"Accepted {accepted_count} debts for routers/director.py")
