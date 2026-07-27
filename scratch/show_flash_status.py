import sys
from pathlib import Path

# Set up paths
project_root = Path(__file__).resolve().parents[1]
backend_dir = project_root / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
if str(project_root) not in sys.path:
    sys.path.insert(1, str(project_root))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    hub.flash_update_heartbeat()
    status = hub.generate_flash_status()
    print("---STATUS_START---")
    print(status["formatted"])
    print("---STATUS_END---")
    
    # Also print JSON to verify context percentage and timer status
    import json
    print("---JSON_START---")
    print(json.dumps(status))
    print("---JSON_END---")

if __name__ == "__main__":
    main()
