"""
プレビュースクリーンショット生成
技術憲法9条（視覚確認プロトコル）準拠

各シーンから複数タイムスタンプでスクリーンショットを生成
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from path_resolver import brain_dir, raw_videos_dir

# パス設定
RAW_DIR = raw_videos_dir() / "AI Studio アップロード用動画"
# 会話 UUID は当時のもの。親（brain/）は解決に通してある。
PREVIEW_DIR = brain_dir() / "0cc79527-362f-4816-aa0a-27c9f69dbaa5" / "previews"
PREVIEW_DIR.mkdir(exist_ok=True)

# 素材ファイル
SCENES = [
    ("シーン01_前編", "シーン01_前編.mp4", ["00:00:05", "00:01:00", "00:05:00", "00:10:00"]),
    ("シーン02_ゲスト書道", "シーン02_ゲスト書道.mp4", ["00:00:05", "00:00:30", "00:01:00"]),
    ("シーン03_後編01", "シーン03_後編01.mp4", ["00:00:05", "00:01:00", "00:03:00"]),
    ("シーン04_後編02", "シーン04_後編02.mp4", ["00:00:05", "00:01:00", "00:03:00"]),
]

def capture_screenshot(video_path: Path, timestamp: str, output_path: Path):
    """動画から指定時間のスクリーンショットを取得"""
    cmd = [
        "ffmpeg", "-y",
        "-ss", timestamp,
        "-i", str(video_path),
        "-vframes", "1",
        "-q:v", "2",
        str(output_path)
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except:
        return False

def main():
    print("=" * 60)
    print("プレビュースクリーンショット生成")
    print("技術憲法9条（視覚確認プロトコル）準拠")
    print("=" * 60)
    
    generated = []
    
    for scene_name, video_file, timestamps in SCENES:
        video_path = RAW_DIR / video_file
        
        if not video_path.exists():
            print(f"\n❌ {scene_name}: Video not found")
            continue
        
        print(f"\n📷 {scene_name}")
        
        for ts in timestamps:
            ts_safe = ts.replace(":", "-")
            output_path = PREVIEW_DIR / f"{scene_name}_{ts_safe}.jpg"
            
            if capture_screenshot(video_path, ts, output_path):
                print(f"  ✅ {ts} -> {output_path.name}")
                generated.append(output_path)
            else:
                print(f"  ⏭️ {ts} - スキップ（範囲外）")
    
    print(f"\n📊 生成完了: {len(generated)} 枚")
    print(f"📁 保存先: {PREVIEW_DIR}")
    
    # ファイル一覧を出力
    print("\n生成されたファイル:")
    for path in sorted(generated):
        print(f"  - {path.name}")
    
    return generated

if __name__ == "__main__":
    main()
