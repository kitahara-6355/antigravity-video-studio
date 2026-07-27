"""
Flash Get Next Batch CLI Entrypoint

This module provides a command-line interface to fetch the next batch of tasks
for a running Flash session, update its heartbeat, and display current status.
"""

import sys
import os
import json
import argparse
import traceback

# プロジェクトルートおよび backend ディレクトリを PYTHONPATH に追加
root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, root_path)
sys.path.insert(0, os.path.join(root_path, "backend"))

from backend.agents.orchestration import OrchestrationHub

def main():
    """
    Get the next task batch from OrchestrationHub, update heartbeat, and print status.
    
    This CLI tool manages the process of fetching tasks for the current running Flash session.
    It registers the conversation ID, updates the heartbeat, fetches the next batch of tasks
    for the specified phase and milestone, and formats the latest session status.
    """
    try:
        parser = argparse.ArgumentParser(description="Get next task batch and update status.")
        parser.add_argument("--conversation-id", "-id", type=str, required=True, help="Conversation ID")
        parser.add_argument("--phase", type=int, default=30, help="Current Phase")
        parser.add_argument("--milestone", type=str, default="M30.1", help="Current Milestone")
        parser.add_argument("--batch-size", type=int, default=10, help="Batch Size")
        
        args = parser.parse_args()
        
        hub = OrchestrationHub()
        hub.register_flash_conversation_id(args.conversation_id)
        
        # 1. 心拍更新
        hub.flash_update_heartbeat()
        
        # 2. 次のバッチを取得
        print(f"Fetching next batch for Phase {args.phase}, Milestone {args.milestone}, Batch Size {args.batch_size}...")
        batch = hub.get_next_batch(
            phase=args.phase,
            milestone=args.milestone,
            batch_size=args.batch_size
        )
        
        print("=== BATCH_TASKS ===")
        print(json.dumps(batch, indent=2, ensure_ascii=False))
        print("===================")
        
        # 3. 最新ステータス表示
        status = hub.generate_flash_status()
        print("=== STATUS ===")
        print(status["formatted"])
        print("==============")
    except Exception as e:
        print(f"Error executing flash_get_next_batch: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
