import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))
sys.path.append(str(project_root / "backend"))

from backend.agents.orchestration import OrchestrationHub

hub = OrchestrationHub()
batch = hub.get_next_batch(phase=26, milestone="M26.1", batch_size=6)
print("=== BATCH ===")
print(batch)
print("\n=== QUEUE STATUS AFTER ===")
print(hub.get_queue_status())
