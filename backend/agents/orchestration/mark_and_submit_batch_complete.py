import os
import sys
import json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from backend.agents.orchestration import OrchestrationHub

def submit_batch_results(hub: OrchestrationHub, batch_id: str, batch_results: dict) -> None:
    """バッチの実行結果をOrchestrationHubに送信します。"""
    try:
        hub.submit_batch_report(batch_id, batch_results)
        print("BATCH_SUBMITTED_SUCCESSFULLY")
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError, IndexError, ImportError) as e:
        print(f"Error submitting batch results: {e}", file=sys.stderr)
        raise

def display_flash_status(hub: OrchestrationHub) -> None:
    """最新のFlashステータスを取得し、JSON形式で表示します。"""
    try:
        status = hub.generate_flash_status()
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError, IndexError, ImportError) as e:
        print(f"Error generating flash status: {e}", file=sys.stderr)
        raise

    try:
        status_json = json.dumps(status)
    except (TypeError, ValueError) as e:
        print(f"Error serializing flash status to JSON: {e}", file=sys.stderr)
        raise

    print("FLASH_STATUS:" + status_json)

def main() -> int:
    """メインのエントリーポイント関数です。
    OrchestrationHubを初期化し、対象バッチの完了報告を送信したのち、
    最新のFlashステータスを表示します。
    """
    try:
        hub = OrchestrationHub()
        hub.register_flash_conversation_id("ce05d36d-f2c8-452b-8ea9-9053a1e718a0")
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError, IndexError, ImportError) as e:
        print(f"Error initializing OrchestrationHub: {e}", file=sys.stderr)
        return 1
    
    # バッチ完了報告
    target_batch_id = "batch_63e89e"
    results = {
        "passed": 5,
        "failed": 1,
        "skipped": 0,
        "total": 6
    }
    
    try:
        submit_batch_results(hub, target_batch_id, results)
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError, IndexError, ImportError):
        return 1

    # 最新ステータス表示
    try:
        display_flash_status(hub)
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError, IndexError, ImportError):
        return 1

    return 0

if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
