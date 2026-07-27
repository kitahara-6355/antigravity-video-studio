import sys
import os

# プロジェクトルートと backend を PYTHONPATH に追加
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
backend_path = os.path.join(project_root, "backend")
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    # 最優先で心拍を更新
    hub.flash_update_heartbeat()
    
    # ステータスを取得して出力
    status = hub.generate_flash_status()
    print("STATUS_START")
    print(status["formatted"])
    print("STATUS_END")
    
    # 追加のパラメータをパースしやすい形で出力
    print(f"CTX_PCT:{status.get('context_consumption_pct', 0)}")
    print(f"BATCH_CUR:{status.get('batch_cur', 0)}")
    print(f"BATCH_MAX:{status.get('batch_max', 0)}")
    print(f"TASK_CUR:{status.get('task_cur', 0)}")
    print(f"TASK_MAX:{status.get('task_max', 0)}")
    print(f"URGENCY:{status.get('archive_urgency', 'normal')}")

if __name__ == "__main__":
    main()
