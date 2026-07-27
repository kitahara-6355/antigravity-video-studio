"""Check orchestrator entries in TDR and fix path issue."""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from agents.memory.technical_debt import TechnicalDebtStore

store = TechnicalDebtStore()

# orchestrator.py の open entries を確認
orch_entries = [e for e in store.entries if 'orchestrator' in e.file_path and e.status == 'open']
print(f"orchestrator open entries: {len(orch_entries)}")
for e in orch_entries[:5]:
    print(f"  {e.debt_id} {e.file_path}:L{e.line_number}")

# ファイルが実際に存在するか確認
from pathlib import Path
backend = Path(__file__).resolve().parent.parent / "backend"
if orch_entries:
    fpath = orch_entries[0].file_path
    full = backend.parent / fpath
    print(f"\nPath check: {full}")
    print(f"Exists: {full.exists()}")
    
    # 正しいパスの候補を探す
    for candidate in backend.rglob("orchestrator.py"):
        print(f"Found: {candidate.relative_to(backend.parent)}")
