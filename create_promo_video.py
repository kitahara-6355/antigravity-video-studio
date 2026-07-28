"""
美麗書院 プロモーション映像生成スクリプト
約60秒のYouTubeプロモーション映像を作成
"""
import subprocess
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from path_resolver import project_root

# パス設定
BASE_DIR = project_root()
RAW_DIR = BASE_DIR / "raw_videos" / "AI Studio アップロード用動画"
ASSET_DIR = BASE_DIR / "raw_videos" / "スライド用素材" / "特選"
OUTPUT_DIR = BASE_DIR / "output" / "promo"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 入力ファイル
VIDEO_01 = RAW_DIR / "シーン01_前編.mp4"
VIDEO_02 = RAW_DIR / "シーン02_ゲスト書道.mp4"
LOGO = ASSET_DIR / "常時_ロゴマーク.JPG"
ARTWORK = ASSET_DIR / "OP_Movie_墨画２.JPG"

# 出力ファイル
OUTPUT_VIDEO = OUTPUT_DIR / "birei_promo_v1.mp4"
TEMP_DIR = OUTPUT_DIR / "temp"
TEMP_DIR.mkdir(exist_ok=True)

def run_ffmpeg(cmd, description=""):
    """FFmpegコマンド実行"""
    print(f"\n=== {description} ===")
    print(f"Command: {' '.join(cmd[:10])}...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: {result.stderr[:500]}")
        return False
    print("Done!")
    return True

def extract_clip(input_file, output_file, start, duration, description=""):
    """動画からクリップを抽出"""
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", str(input_file),
        "-t", str(duration),
        "-c:v", "libx264", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
        str(output_file)
    ]
    return run_ffmpeg(cmd, description)

def create_title_card(output_file, duration=5):
    """タイトルカード作成（ロゴ + 墨画背景）"""
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-t", str(duration),
        "-i", str(ARTWORK),
        "-loop", "1", "-t", str(duration),
        "-i", str(LOGO),
        "-filter_complex",
        "[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2[bg];"
        "[1:v]scale=300:-1[logo];"
        "[bg][logo]overlay=W-w-50:H-h-50:format=auto,fade=t=in:st=0:d=1,fade=t=out:st=4:d=1[v]",
        "-map", "[v]",
        "-c:v", "libx264", "-crf", "23",
        "-pix_fmt", "yuv420p",
        str(output_file)
    ]
    return run_ffmpeg(cmd, "Creating title card")

def add_text_overlay(input_file, output_file, text, position="center"):
    """テキストオーバーレイ追加"""
    # Windows用フォントパス
    font_path = "C\\:/Windows/Fonts/meiryo.ttc"
    
    if position == "center":
        pos = "x=(w-text_w)/2:y=(h-text_h)/2"
    elif position == "bottom":
        pos = "x=(w-text_w)/2:y=h-text_h-50"
    else:
        pos = "x=50:y=50"
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_file),
        "-vf", f"drawtext=fontfile='{font_path}':text='{text}':fontsize=48:fontcolor=white:borderw=2:bordercolor=black:{pos}",
        "-c:v", "libx264", "-crf", "23",
        "-c:a", "copy",
        str(output_file)
    ]
    return run_ffmpeg(cmd, f"Adding text: {text[:20]}...")

def concat_videos(input_files, output_file):
    """動画を結合"""
    concat_file = TEMP_DIR / "concat_list.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        for file in input_files:
            f.write(f"file '{file}'\n")
    
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-c:v", "libx264", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        str(output_file)
    ]
    return run_ffmpeg(cmd, "Concatenating videos")

def main():
    print("=" * 60)
    print("美麗書院 プロモーション映像生成")
    print("=" * 60)
    
    clips = []
    
    # 1. タイトルカード（5秒）
    title_card = TEMP_DIR / "01_title.mp4"
    if create_title_card(title_card, duration=5):
        clips.append(title_card)
    
    # 2. オープニングトーク（10秒）- シーン01の冒頭
    clip_intro = TEMP_DIR / "02_intro.mp4"
    if extract_clip(VIDEO_01, clip_intro, start=0, duration=10, description="Extracting intro"):
        clips.append(clip_intro)
    
    # 3. チャンネル紹介（15秒）- 北原美麗の自己紹介
    clip_channel = TEMP_DIR / "03_channel.mp4"
    if extract_clip(VIDEO_01, clip_channel, start=0, duration=15, description="Extracting channel intro"):
        clips.append(clip_channel)
    
    # 4. ゲスト紹介（10秒）- 山田先生登場
    clip_guest = TEMP_DIR / "04_guest.mp4"
    if extract_clip(VIDEO_01, clip_guest, start=31, duration=15, description="Extracting guest intro"):
        clips.append(clip_guest)
    
    # 5. 印象的な対話（15秒）- シャープのエピソード
    clip_story = TEMP_DIR / "05_story.mp4"
    if extract_clip(VIDEO_01, clip_story, start=390, duration=15, description="Extracting story"):
        clips.append(clip_story)
    
    # 6. 書道実演（10秒）- シーン02から
    clip_demo = TEMP_DIR / "06_demo.mp4"
    if extract_clip(VIDEO_02, clip_demo, start=0, duration=10, description="Extracting demo"):
        clips.append(clip_demo)
    
    # 7. エンディング（5秒）- タイトルカード再利用
    clips.append(title_card)
    
    # 結合
    if len(clips) > 0:
        print(f"\nConcatenating {len(clips)} clips...")
        if concat_videos(clips, OUTPUT_VIDEO):
            print(f"\n{'=' * 60}")
            print(f"✅ プロモーション映像生成完了!")
            print(f"Output: {OUTPUT_VIDEO}")
            print(f"{'=' * 60}")
            return True
    
    return False

if __name__ == "__main__":
    main()
