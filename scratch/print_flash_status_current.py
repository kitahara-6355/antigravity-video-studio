import sys
import os
import json

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, base_dir)
sys.path.insert(0, os.path.join(base_dir, "backend"))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    # 現在のセッションの conversationId を登録
    hub.register_flash_conversation_id("790758f1-d405-4a07-86c1-ef5fe4705438")
    status = hub.generate_flash_status()
    print("---STATUS_START---")
    print(status["formatted"])
    print("---STATUS_END---")
    print("---JSON_START---")
    print(json.dumps(status))
    print("---JSON_END---")

if __name__ == '__main__':
    main()
