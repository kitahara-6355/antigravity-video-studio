import sys
import os
import json
import re

# プロジェクトルートおよび backend ディレクトリをパスに追加
root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, root_path)
sys.path.insert(0, os.path.join(root_path, "backend"))
from backend.agents.orchestration import OrchestrationHub

# UUIDの簡易バリデーション用正規表現
UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)

def main():
    try:
        # 位置引数のみを抽出（ハイフンで始まるオプション引数を除外）
        args = [arg for arg in sys.argv[1:] if not arg.startswith("-")]
        conv_id = args[0] if args else "ce05d36d-f2c8-452b-8ea9-9053a1e718a0"
        
        # UUID 形式のバリデーション
        if not UUID_PATTERN.match(conv_id):
            print(f"ERROR: Invalid conversation ID format: {conv_id}", file=sys.stderr)
            sys.exit(1)

        hub = OrchestrationHub()
        hub.register_flash_conversation_id(conv_id)
        
        # 心拍更新
        hub.flash_update_heartbeat()
        print("HEARTBEAT_UPDATED")

        # 最新ステータス表示
        status = hub.generate_flash_status()
        print("FLASH_STATUS:" + json.dumps(status))

        # キュー情報
        q_status = hub.get_queue_status()
        print("QUEUE_STATUS:" + json.dumps(q_status))
    except FileNotFoundError as e:
        print(f"ERROR: Configuration or session file not found: {e}", file=sys.stderr)
        sys.exit(1)
    except PermissionError as e:
        print(f"ERROR: Permission denied when accessing configuration or session file: {e}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: Failed to parse session JSON: {e}", file=sys.stderr)
        sys.exit(1)
    except (ValueError, RuntimeError) as e:
        import traceback
        print(f"ERROR: Failed to run heartbeat_only main: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":  # pragma: no cover
    main()
