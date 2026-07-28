"""
Phase 20 一気通貫実行スクリプト（英語ファイル名版）
Phase 4-7 を順番に実行し、結果をwalkthrough形式で出力

Phase 9: 日本語ファイル名問題の抜本解決
- scene_id による英語ファイル名統一
- カルーセル形式レポート（スクショ+確認事項）
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from path_resolver import brain_dir, raw_videos_dir
from interactive_preview import run_full_pipeline
from preview_system import SubtitlePreviewGenerator

# パス設定
RAW_DIR = raw_videos_dir() / "AI Studio アップロード用動画"
# 会話 UUID は当時のもの。親（brain/）は解決に通してある。
ARTIFACT_DIR = brain_dir() / "0cc79527-362f-4816-aa0a-27c9f69dbaa5"
PREVIEWS_DIR = ARTIFACT_DIR / "previews"

# シーン定義（英語scene_id使用）
SCENES = [
    {
        "scene_id": "scene01_part1",
        "name": "シーン01_前編",
        "video": str(RAW_DIR / "シーン01_前編.mp4"),
        "subtitle": str(RAW_DIR / "シーン01_前編_official.srt"),
        "timestamps": ["00:00:05", "00:01:00", "00:05:00", "00:10:00"]
    },
    {
        "scene_id": "scene03_part2a",
        "name": "シーン03_後編01",
        "video": str(RAW_DIR / "シーン03_後編01.mp4"),
        "subtitle": str(RAW_DIR / "シーン03_後編01_official.srt"),
        "timestamps": ["00:00:05", "00:02:00", "00:04:00"]
    },
    {
        "scene_id": "scene04_part2b",
        "name": "シーン04_後編02",
        "video": str(RAW_DIR / "シーン04_後編02.mp4"),
        "subtitle": str(RAW_DIR / "シーン04_後編02_official.srt"),
        "timestamps": ["00:00:05", "00:02:00", "00:04:00"]
    },
]


def main():
    print("=" * 60)
    print("Phase 20: インタラクティブプレビューシステム")
    print("Phase 9: 英語ファイル名統一版")
    print("=" * 60)
    
    # Step 1: 字幕付きスクショ生成（英語ファイル名）
    print("\n📷 Step 1: 字幕付きスクショ生成（英語ファイル名）")
    subtitle_gen = SubtitlePreviewGenerator(PREVIEWS_DIR)
    
    for scene in SCENES:
        scene_id = scene["scene_id"]
        print(f"\n  {scene_id} ({scene['name']})")
        srt_path = Path(scene["subtitle"]) if scene.get("subtitle") else None
        video_path = Path(scene["video"])
        
        screenshots = []
        if video_path.exists():
            for ts in scene["timestamps"]:
                ts_safe = ts.replace(":", "-")
                # 英語ファイル名を使用
                output_name = f"{scene_id}_{ts_safe}"
                
                if srt_path and srt_path.exists():
                    result = subtitle_gen.capture_with_subtitle(
                        video_path, srt_path, ts, output_name
                    )
                    if result:
                        screenshots.append({
                            "timestamp": ts,
                            "path": str(result),
                            "filename": f"{output_name}_sub.jpg",
                            "with_subtitle": True
                        })
                        print(f"    ✅ {ts} → {output_name}_sub.jpg")
        else:
            print(f"    ⚠️ 動画ファイルが見つかりません")
        
        scene["screenshots"] = screenshots
    
    # Step 2: Phase 4-7 実行
    print("\n" + "=" * 60)
    print("📋 Step 2: Phase 4-7 実行 (AI分析 & テロップ提案)")
    print("=" * 60)
    
    report = run_full_pipeline(SCENES, ARTIFACT_DIR)
    
    # Step 3: レポート保存
    output_path = ARTIFACT_DIR / "phase20_report.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)
    
    print(f"\n✅ レポート保存: {output_path}")
    print("\n" + "=" * 60)
    print("完了！")
    print("=" * 60)


if __name__ == "__main__":
    main()
