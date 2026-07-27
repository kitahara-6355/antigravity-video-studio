import sys
import os
import json

# プロジェクトルートを python path に追加
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    
    # 状態の取得
    state = hub.get_phase_state()
    phase = state.get("current_phase", 27)
    milestone = state.get("current_milestone", "M27.1")
    
    print(f"Current Phase: {phase}, Milestone: {milestone}")
    
    # バッチ取得
    batch = hub.get_next_batch(phase, milestone, batch_size=6)
    print("----- NEXT BATCH -----")
    print(json.dumps(batch, indent=2, ensure_ascii=False))
    
    # ステータス表示
    status = hub.generate_flash_status()
    print("----- STATUS -----")
    print(status.get("formatted", ""))
    
    # アーカイブ警告の確認
    if status.get("archive_urgency") == "warn":
        print("⚠️ ARCHIVE WARNING")

if __name__ == "__main__":
    main()
