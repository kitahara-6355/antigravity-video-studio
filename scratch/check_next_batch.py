import sys
from pathlib import Path

# パスを追加して backend をインポートできるようにする
backend_path = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(backend_path))

from agents.orchestration.orchestrator import OrchestrationHub

hub = OrchestrationHub()

state = hub.get_phase_state()
phase = state.get("current_phase")
milestone = state.get("current_milestone")
print(f"Current State: Phase {phase}, Milestone {milestone}")

next_batch = hub.get_next_batch(phase=phase, milestone=milestone, batch_size=6)
print(f"Next Batch: {next_batch}")

queue_status = hub.get_queue_status()
print(f"Queue Status: {queue_status}")
