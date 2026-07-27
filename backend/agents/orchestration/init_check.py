import os
import sys

# スクリプトの場所からプロジェクトルートを算出し、sys.pathに挿入
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, "..", "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import json
from typing import Optional, List
from backend.agents.orchestration import OrchestrationHub

DEFAULT_CONVERSATION_ID = "ce05d36d-f2c8-452b-8ea9-9053a1e718a0"

def parse_args(args: List[str]) -> str:
    """コマンドライン引数から会話ID（conversation_id）を解析します。
    引数が指定されていない場合は、デフォルトのIDを返します。
    """
    if len(args) > 1:
        return args[1]
    return DEFAULT_CONVERSATION_ID

def run_init_check(conversation_id: str, hub: Optional[OrchestrationHub] = None) -> None:
    """OrchestrationHubから各種ステータスを取得し、標準出力に表示します。"""
    if hub is None:
        hub = OrchestrationHub()

    hub.register_flash_conversation_id(conversation_id)

    # 状態確認
    phase_state = hub.get_phase_state()
    print("PHASE_STATE:" + json.dumps(phase_state))

    queue_status = hub.get_queue_status()
    print("QUEUE_STATUS:" + json.dumps(queue_status))

    flash_status = hub.generate_flash_status()
    print("FLASH_STATUS:" + json.dumps(flash_status))

def main() -> None:
    try:
        conversation_id = parse_args(sys.argv)
        run_init_check(conversation_id)
    except Exception as e:
        sys.stderr.write(f"Error during init check: {e}\n")
        sys.exit(1)

if __name__ == "__main__":  # pragma: no cover
    main()


