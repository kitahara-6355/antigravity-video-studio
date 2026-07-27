"""Monitor pipeline status with periodic polling"""
import requests
import json
import time

API_BASE = "http://localhost:8000"

print("=== パイプライン進捗モニタリング ===")
print("5秒間隔でポーリング中...\n")

last_stage = -1
start_time = time.time()

for i in range(200):  # 最大16分
    try:
        resp = requests.get(f"{API_BASE}/api/pipeline/status", timeout=5)
        data = resp.json()
        
        status = data.get("status", "unknown")
        current_stage = data.get("current_stage", 0)
        stages = data.get("stages", [])
        
        elapsed = time.time() - start_time
        
        # ステージ変化時のみ詳細表示
        if current_stage != last_stage or status in ("completed", "error"):
            print(f"\n[{elapsed:.0f}秒] ステータス: {status} | ステージ: {current_stage}")
            for j, stage in enumerate(stages):
                icon = "✅" if stage["status"] == "completed" else "🔄" if stage["status"] == "running" else "❌" if stage["status"] == "error" else "⏳"
                detail = stage.get("detail", "")
                progress = stage.get("progress", -1)
                prog_str = f" [{progress}%]" if progress >= 0 else ""
                print(f"  {icon} {stage['name']}{prog_str}: {detail}")
            last_stage = current_stage
        else:
            # 進捗率の変化だけ表示
            for stage in stages:
                if stage["status"] == "running" and stage.get("progress", -1) >= 0:
                    print(f"  ⏱ {elapsed:.0f}s | {stage['name']} {stage.get('progress', 0)}% - {stage.get('detail', '')}", end="\r")
        
        if status in ("completed", "error"):
            print(f"\n\n{'='*50}")
            print(f"最終ステータス: {status}")
            if data.get("error"):
                print(f"エラー: {data['error']}")
            if data.get("result"):
                print(f"結果: {json.dumps(data['result'], ensure_ascii=False, indent=2)}")
            break
            
    except Exception as e:
        print(f"\n[{time.time()-start_time:.0f}秒] API接続エラー: {e}")
    
    time.sleep(5)
else:
    print("\nタイムアウト（16分超過）")
