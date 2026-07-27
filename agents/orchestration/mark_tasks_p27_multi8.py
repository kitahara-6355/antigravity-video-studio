import sys
import os

def setup_project_path():
    """スクリプトの配置ディレクトリからプロジェクトルートを算出し、sys.pathに追加する"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, "..", "..", ".."))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    return project_root

# パス設定の実行
project_root_path = setup_project_path()

# プロジェクトルートが追加された後にインポート
from backend.agents.orchestration import OrchestrationHub

def mark_weaver_tasks(hub: OrchestrationHub):
    """test_weaverタスクの実行結果をマークする"""
    # 1. 心拍更新
    hub.flash_update_heartbeat()
    
    # 2. test_weaver-000 の失敗マーク
    hub.mark_task_done("T-batch_c4f4d2-test_weaver-000", "fail", {
        "error": "RESOURCE_EXHAUSTED (code 429): You have exhausted your capacity on this model."
    })
    
    # 3. test_weaver-001 の成功マーク
    hub.mark_task_done("T-batch_c4f4d2-test_weaver-001", "pass", {
        "message": "verify_collaborative_model.py の未カバー行テスト追加完了 (カバレッジ 81% -> 100%)",
        "changed_files": ["backend/tests/test_verify_collaborative_model.py"]
    })
    print("TASKS_MARKED")

def show_flash_status(hub: OrchestrationHub):
    """OrchestrationHubから現在のステータスを生成し、標準出力に表示する"""
    status = hub.generate_flash_status()
    print("=== STATUS ===")
    print(status["formatted"])
    print("==============")

def main():
    target_conversation_id = "3ed8fce0-a204-47fd-a220-c27fecf03706"
    hub = OrchestrationHub()
    hub.register_flash_conversation_id(target_conversation_id)
    
    mark_weaver_tasks(hub)
    show_flash_status(hub)

if __name__ == "__main__":
    main()
