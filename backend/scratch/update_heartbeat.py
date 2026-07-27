import sys

def setup_system_path() -> None:
    """プロジェクトのルートパスをシステムパスに追加します。"""
    project_root = "C:/Users/PC_User/Desktop/script/video-automation"
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

# インポート前にシステムパスをセットアップ
setup_system_path()

# システムパス追加後にOrchestrationHubをインポート
from backend.agents.orchestration import OrchestrationHub

def execute_heartbeat_update() -> None:
    """OrchestrationHubを通じてハートビートを更新します。"""
    hub = OrchestrationHub()
    hub.flash_update_heartbeat()
    print("Heartbeat updated successfully.")

# インポート時の副作用としてハートビートを更新
execute_heartbeat_update()

