"""Start pipeline with pre-merged video (skip merge step)"""
import requests
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from path_resolver import vault_outputs_dir

API_BASE = "http://localhost:8000"

# 既に結合済みの動画を直接使用（結合ステップをスキップ）
merged_video = str(vault_outputs_dir() / "merged" / "merged_20260405_202804.mp4")

payload = {
    "video_path": merged_video,  # 単一動画として渡す（結合スキップ）
    "video_paths": [],
    "target_minutes": 20,
}

print("=== パイプライン起動（結合済み動画を使用）===")
print(f"動画: {merged_video}")

resp = requests.post(f"{API_BASE}/api/pipeline/start", json=payload)
print(f"\nStatus: {resp.status_code}")
print(f"Response: {json.dumps(resp.json(), ensure_ascii=False, indent=2)}")
