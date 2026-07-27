import sys
from pathlib import Path

# backend ディレクトリをパスに追加
sys.path.insert(0, "backend")

import auto_full_build

# 各種設定
scene = {
    "name": "scene01",
    "input": auto_full_build.RAW_DIR / "シーン01_前編.mp4",
    "srt": auto_full_build.SRT_DIR / "シーン01_前編_regenerated.srt",
    "crop": "1152:720:26:0",
    "telops": [(0, 0, 600), (1, 600, 1200), (2, 1200, 1800)]
}

# テロップ画像生成の実行
auto_full_build.generate_telops()

# シーンの処理実行
print("Starting process_scene for scene01...")
try:
    output_file = auto_full_build.process_scene(
        scene["name"],
        scene["input"],
        scene["crop"],
        scene["srt"],
        scene["telops"]
    )
    print(f"\nSUCCESS: scene01 processed successfully!")
    print(f"Output file: {output_file}")
    print(f"Size: {Path(output_file).stat().st_size / (1024*1024):.2f} MB")
except Exception as e:
    print(f"\nFAILURE: scene01 processing failed with error: {e}")
    sys.exit(1)
