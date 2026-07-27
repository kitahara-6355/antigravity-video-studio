import sys
import os
import json

sys.path.insert(0, '.')
sys.path.insert(0, 'backend')
from backend.agents.orchestration import OrchestrationHub

def mark_task_and_submit(hub: OrchestrationHub) -> None:
    """タスクの完了をマークし、バッチ報告を提出します。"""
    try:
        hub.flash_update_heartbeat()
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError) as e:
        print(f"Error updating heartbeat: {e}", file=sys.stderr)
        raise

    try:
        hub.mark_task_done(
            "T-batch_3f4c3a-thumbnail-001",
            "pass",
            {
                "subagent_id": "a175d4c0-b115-412a-aab8-472995264f3c",
                "message": "verify_image_gen.py 日本語自動折り返し対応、一時ファイル拡張子保持、極小解像度Glassmorphism背景ガード、自動検証テスト追加。",
                "changed_files": [
                    "backend/verify_image_gen.py",
                    "backend/tests/test_verify_image_gen.py"
                ]
            }
        )
        print("Marked T-batch_3f4c3a-thumbnail-001 as pass.")
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError) as e:
        print(f"Error marking task done: {e}", file=sys.stderr)
        raise

    try:
        hub.submit_batch_report("batch_3f4c3a", {
            "passed": 6,
            "failed": 0,
            "skipped": 0,
            "total": 6
        })
        print("Batch batch_3f4c3a report submitted successfully.")
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError) as e:
        print(f"Error submitting batch report: {e}", file=sys.stderr)
        raise

def display_flash_status(hub: OrchestrationHub) -> None:
    """最新のFlashステータスを取得し表示します。"""
    try:
        status = hub.generate_flash_status()
        print("=== STATUS ===")
        print(status["formatted"])
        print("==============")
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError) as e:
        print(f"Error generating flash status: {e}", file=sys.stderr)
        raise

def main() -> int:
    try:
        hub = OrchestrationHub()
        hub.register_flash_conversation_id("0f2f32d3-7361-4ed8-b98a-ec10eb70314e")
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError) as e:
        print(f"Error initializing OrchestrationHub: {e}", file=sys.stderr)
        return 1

    try:
        mark_task_and_submit(hub)
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError):
        return 1

    try:
        display_flash_status(hub)
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError):
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())
