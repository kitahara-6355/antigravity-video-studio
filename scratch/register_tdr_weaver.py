import sys
from pathlib import Path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from agents.memory.technical_debt import technical_debt_store

# 1つ目の except Exception 登録
technical_debt_store.register_debt(
    category="IMPORTANT_SERVICE",
    file_path="agents/orchestration/mark_tasks_p27_weaver1_b88.py",
    line_number=80,
    pattern="except Exception as e:",
    cause_pattern="DP-01",
    fix_pattern="Pillowの画像検証における広範な例外捕捉",
    registered_by="bug_hunter_task_1",
    notes="Image.verify()で発生するあらゆる破損形式をValueErrorに変換し堅牢化"
)

# 2つ目の except Exception 登録
technical_debt_store.register_debt(
    category="IMPORTANT_SERVICE",
    file_path="agents/orchestration/mark_tasks_p27_weaver1_b88.py",
    line_number=88,
    pattern="except Exception as e:",
    cause_pattern="DP-01",
    fix_pattern="Pillowの画像ロードにおける広範な例外捕捉",
    registered_by="bug_hunter_task_1",
    notes="Image.load()で発生するあらゆる破損形式をValueErrorに変換し堅牢化"
)

print("TDR_REGISTER_SUCCESS")
