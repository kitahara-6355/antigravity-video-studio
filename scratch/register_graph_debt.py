"""Register graph.py except Exception entries in TDR."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from agents.memory.technical_debt import TechnicalDebtStore

store = TechnicalDebtStore()

# graph.py の 3件の except Exception を登録
files_to_register = [
    {
        "file_path": "backend/agents/graph.py",
        "pattern": "except Exception (broad catch)",
        "category": "MINOR_INFRA",
        "line_number": 0,  # 複数箇所あるため0
        "description": "agents/graph.py: 3件のexcept Exception。Flash batch_783b64で追加されたテストカバレッジ強化に伴う防御的例外ハンドリング。"
    },
]

for entry in files_to_register:
    debt_id = store.register_debt(
        category=entry["category"],
        file_path=entry["file_path"],
        line_number=entry["line_number"],
        pattern=entry["pattern"],
        description=entry.get("description", ""),
    )
    print(f"✅ Registered: {debt_id} -> {entry['file_path']}")

print("\nDone.")
