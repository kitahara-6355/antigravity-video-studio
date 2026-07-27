# -*- coding: utf-8 -*-
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from backend.agents.orchestration import OrchestrationHub

hub = OrchestrationHub()

# T-batch_d6d052-test_weaver-004
hub.mark_task_done("T-batch_d6d052-test_weaver-004", "fail", {
    "error": "Process hung and killed: pytest was executed without specifying target test files, resulting in running the entire test suite (4868 tests) and hanging.",
    "traceback": "Killed by parent agent due to inactivity.",
    "changed_files": []
})

# T-batch_d6d052-test_weaver-006
hub.mark_task_done("T-batch_d6d052-test_weaver-006", "fail", {
    "error": "Process hung and killed: pytest was executed without specifying target test files, resulting in running the entire test suite (4868 tests) and hanging.",
    "traceback": "Killed by parent agent due to inactivity.",
    "changed_files": []
})

print("Successfully marked hung tasks as fail.")
