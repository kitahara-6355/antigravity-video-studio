import sys

def setup_path():
    """必要なパスを sys.path に追加します。"""
    import os
    from pathlib import Path
    current_file = Path(__file__).resolve()
    project_root = str(current_file.parents[3])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

setup_path()
from backend.agents.orchestration import OrchestrationHub

def initialize_hub(conversation_id: str) -> OrchestrationHub:
    """OrchestrationHubを初期化し、会話IDを登録して心拍を更新します。"""
    hub = OrchestrationHub()
    hub.register_flash_conversation_id(conversation_id)
    hub.flash_update_heartbeat()
    return hub

def mark_refactor_task(hub: OrchestrationHub):
    """対象のリファクタリングタスクを pass としてマークします。"""
    hub.mark_task_done(
        "T-batch_3f4c3a-refactor-000",
        "pass",
        {
            "subagent_id": "5d22fb19-c02e-4949-9ec7-62d2a9727351",
            "message": "transcribe_sync.py のリファクタリングタスク完了。デッドコードの除去、および非同期実行/JSON保存関数の分割。カバレッジ100%維持。",
            "changed_files": ["backend/transcribe_sync.py"]
        }
    )
    print("Marked T-batch_3f4c3a-refactor-000 as pass.")

def print_status(hub: OrchestrationHub):
    """現在のFlashステータスを標準出力に表示します。"""
    status = hub.generate_flash_status()
    print("=== STATUS ===")
    print(status["formatted"])
    print("==============")

def main():
    try:
        hub = initialize_hub("0f2f32d3-7361-4ed8-b98a-ec10eb70314e")
        mark_refactor_task(hub)
        print_status(hub)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError) as e:
        print(f"Error occurred during execution: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
