"""Register trinity.py except Exception entries in TDR and remove runtime registration code."""
import sys, os, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from agents.memory.technical_debt import TechnicalDebtStore, DEBT_DIR

store = TechnicalDebtStore(DEBT_DIR)

# Check if trinity.py already has entries
existing = [e for e in store.entries if 'trinity.py' in e.file_path and e.status == 'open']
print(f"Existing trinity.py entries: {len(existing)}")

# The exception lines in trinity.py (the actual except Exception lines)
exception_lines = [23, 50, 85, 112, 139, 172, 203, 249, 283, 317, 354, 390]
endpoint_names = [
    "get_trinity_status", "sync_analytics", "simulate_analytics",
    "get_models", "get_evolution", "sync_evolution",
    "get_evolution_status", "get_evolution_proposals",
    "approve_evolution_proposal", "reject_evolution_proposal",
    "get_evolution_dashboard", "get_evolution_triggers"
]

registered = 0
for line, name in zip(exception_lines, endpoint_names):
    # Check if already registered
    already = any(e.file_path == 'routers/trinity.py' and e.line_number == line for e in store.entries)
    if not already:
        store.register_debt(
            category="IMPORTANT_SERVICE",
            file_path="routers/trinity.py",
            line_number=line,
            pattern="except Exception as e:",
            cause_pattern="DP-01",
            fix_pattern="Router層catch-all: HTTPExceptionガード配置済み、TDR静的登録",
            registered_by="opus_tdr_fix",
            notes=f"trinity.py {name}: except HTTPException: raiseガードあり"
        )
        registered += 1

print(f"Registered {registered} new entries")
print(f"Total entries: {len(store.entries)}")
