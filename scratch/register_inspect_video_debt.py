import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from agents.memory.technical_debt import TechnicalDebtStore

store = TechnicalDebtStore()

# 1. Line 28
e1 = store.register_debt(
    category="ACCEPTED_SAFETY",
    file_path="inspect_video.py",
    line_number=28,
    pattern="except Exception as e:",
    cause_pattern="DP-01",
    fix_pattern="Pillow verification exception handling",
    registered_by="flash_cleanup",
    notes="Safe guard for corrupted pillow images"
)
store.accept_debt(e1.debt_id, "Legitimate safety guard for image corruption verification")

# 2. Line 34
e2 = store.register_debt(
    category="ACCEPTED_SAFETY",
    file_path="inspect_video.py",
    line_number=34,
    pattern="except Exception as e:",
    cause_pattern="DP-01",
    fix_pattern="Pillow image open exception handling",
    registered_by="flash_cleanup",
    notes="Safe guard for resolution verification on pillow load"
)
store.accept_debt(e2.debt_id, "Legitimate safety guard for resolution load verification")

print("TDR entries registered and accepted successfully.")
