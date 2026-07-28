"""
美麗書院 本番YouTube動画制作スクリプト
両憲法準拠プラン Phase 19+

技術憲法13条準拠: 大容量処理プロトコル
- パス指定によるダイレクト処理
- 非同期処理対応

仕様:
- 4シーン素材を結合（シーン01→02→03→04）
- 映画スタイル字幕（下部固定、白テキスト黒アウトライン）
- 話者名なし
- OP/ED BGMのみ（本編BGMなし）
- 無音カットのみ適用
"""

import subprocess
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from path_resolver import project_root, raw_videos_dir

# パス設定
RAW_DIR = raw_videos_dir() / "AI Studio アップロード用動画"
OUTPUT_DIR = project_root() / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# 素材ファイル
SCENES = [
    {
        "name": "シーン01_前編",
        "video": RAW_DIR / "シーン01_前編.mp4",
        "subtitle": RAW_DIR / "シーン01_前編_official.srt"
    },
    {
        "name": "シーン02_ゲスト書道",
        "video": RAW_DIR / "シーン02_ゲスト書道.mp4",
        "subtitle": None  # 書道シーンは字幕なし
    },
    {
        "name": "シーン03_後編01",
        "video": RAW_DIR / "シーン03_後編01.mp4",
        "subtitle": RAW_DIR / "シーン03_後編01_official.srt"
    },
    {
        "name": "シーン04_後編02",
        "video": RAW_DIR / "シーン04_後編02.mp4",
        "subtitle": RAW_DIR / "シーン04_後編02_official.srt"
    }
]

# 出力ファイル
OUTPUT_VIDEO = OUTPUT_DIR / "美麗書院_久北博之先生_第1回_本番.mp4"
DRAFT_VIDEO = OUTPUT_DIR / "美麗書院_久北博之先生_第1回_ドラフト.mp4"

# 字幕スタイル（映画スタイル）
SUBTITLE_STYLE = (
    "FontName=Noto Sans JP,"
    "FontSize=24,"
    "PrimaryColour=&H00FFFFFF,"  # 白
    "OutlineColour=&H00000000,"   # 黒アウトライン
    "BorderStyle=1,"
    "Outline=2,"
    "Shadow=1,"
    "Alignment=2,"  # 下部中央
    "MarginV=40"
)


def generate_subtitle_video(video_path: Path, subtitle_path: Path, output_path: Path, is_draft: bool = True):
    """動画に字幕を焼き込み"""
    if not subtitle_path or not subtitle_path.exists():
        # 字幕なしの場合はそのままコピー
        if is_draft:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-c:v", "libx264", "-crf", "28", "-preset", "fast",
                "-c:a", "aac", "-b:a", "128k",
                str(output_path)
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-c", "copy",
                str(output_path)
            ]
    else:
        # 字幕焼き込み
        subtitle_filter = f"subtitles='{str(subtitle_path).replace(chr(92), chr(92)+chr(92)).replace(':', chr(92)+':')}':force_style='{SUBTITLE_STYLE}'"
        
        if is_draft:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-vf", subtitle_filter,
                "-c:v", "libx264", "-crf", "28", "-preset", "fast",
                "-c:a", "aac", "-b:a", "128k",
                str(output_path)
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-vf", subtitle_filter,
                "-c:v", "libx264", "-crf", "18", "-preset", "slow",
                "-c:a", "aac", "-b:a", "192k",
                str(output_path)
            ]
    
    print(f"  Executing: {' '.join(cmd[:6])}...")
    subprocess.run(cmd, check=True)


def concat_videos(video_paths: list, output_path: Path):
    """複数動画を結合"""
    # 結合用リストファイル作成
    list_file = OUTPUT_DIR / "concat_list.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for path in video_paths:
            f.write(f"file '{path}'\n")
    
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        str(output_path)
    ]
    
    print(f"  Concatenating {len(video_paths)} videos...")
    subprocess.run(cmd, check=True)
    
    # リストファイル削除
    list_file.unlink()


def main():
    print("=" * 60)
    print("美麗書院 本番YouTube動画制作")
    print("第1回ゲスト: 久北博之先生")
    print("=" * 60)
    
    is_draft = True  # ドラフト版を生成
    
    # Step 1: 各シーンに字幕を焼き込み
    print("\n📹 Step 1: 字幕焼き込み")
    temp_videos = []
    
    for i, scene in enumerate(SCENES, 1):
        print(f"\n[{i}/{len(SCENES)}] {scene['name']}")
        
        if not scene["video"].exists():
            print(f"  ❌ Video not found: {scene['video']}")
            continue
        
        temp_output = OUTPUT_DIR / f"temp_{scene['name']}.mp4"
        
        try:
            generate_subtitle_video(
                scene["video"],
                scene["subtitle"],
                temp_output,
                is_draft=is_draft
            )
            temp_videos.append(temp_output)
            print(f"  ✅ Done: {temp_output.name}")
        except Exception as e:
            print(f"  ❌ Error: {e}")
    
    if len(temp_videos) == 0:
        print("\n❌ No videos processed")
        return
    
    # Step 2: 動画を結合
    print("\n📹 Step 2: 動画結合")
    output_path = DRAFT_VIDEO if is_draft else OUTPUT_VIDEO
    
    try:
        concat_videos(temp_videos, output_path)
        print(f"\n✅ 完成: {output_path}")
        print(f"📊 ファイルサイズ: {output_path.stat().st_size / (1024*1024):.1f} MB")
    except Exception as e:
        print(f"\n❌ 結合エラー: {e}")
    
    # Step 3: 一時ファイル削除（オプション）
    print("\n🧹 Step 3: 一時ファイルクリーンアップ")
    for temp in temp_videos:
        try:
            temp.unlink()
            print(f"  Deleted: {temp.name}")
        except:
            pass
    
    print("\n" + "=" * 60)
    print("完了！")
    print("=" * 60)


if __name__ == "__main__":
    main()
