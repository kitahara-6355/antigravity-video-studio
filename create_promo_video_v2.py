"""
美麗書院 プロモーション映像 v2
修正点:
- 字幕（SRT）を焼き込み
- 動画02を短縮（5秒）
- 動画03/04のハイライトを追加
- より良いペース配分
"""
import subprocess
import os
from pathlib import Path

# パス設定
BASE_DIR = Path(r"C:\Users\PC_User\Desktop\script\video-automation")
RAW_DIR = BASE_DIR / "raw_videos" / "AI Studio アップロード用動画"
ASSET_DIR = BASE_DIR / "raw_videos" / "スライド用素材" / "特選"
OUTPUT_DIR = BASE_DIR / "output" / "promo"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 入力ファイル
VIDEO_01 = RAW_DIR / "シーン01_前編.mp4"
VIDEO_02 = RAW_DIR / "シーン02_ゲスト書道.mp4"
VIDEO_03 = RAW_DIR / "シーン03_後編01.mp4"
VIDEO_04 = RAW_DIR / "シーン04_後編02.mp4"
SRT_01 = RAW_DIR / "シーン01_前編_regenerated.srt"
SRT_03 = RAW_DIR / "シーン03_後編01_regenerated.srt"
SRT_04 = RAW_DIR / "シーン04_後編02_regenerated.srt"
LOGO = ASSET_DIR / "常時_ロゴマーク.JPG"
ARTWORK = ASSET_DIR / "OP_Movie_墨画２.JPG"

# 出力ファイル
OUTPUT_VIDEO = OUTPUT_DIR / "birei_promo_v2.mp4"
TEMP_DIR = OUTPUT_DIR / "temp_v2"
TEMP_DIR.mkdir(exist_ok=True)

# Windowsフォントパス
FONT_PATH = "C\\\\:/Windows/Fonts/meiryo.ttc"

def run_ffmpeg(cmd, description=""):
    """FFmpegコマンド実行"""
    print(f"\n=== {description} ===")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: {result.stderr[:500]}")
        return False
    print("Done!")
    return True

def extract_clip_with_subtitles(input_file, output_file, start, duration, srt_file=None, srt_offset=0, description=""):
    """字幕付きクリップを抽出"""
    vf_filters = ["scale=1920:1080:force_original_aspect_ratio=decrease", "pad=1920:1080:(ow-iw)/2:(oh-ih)/2"]
    
    # 字幕フィルター追加（offsetでタイムスタンプ調整）
    if srt_file and srt_file.exists():
        # SRTパスをエスケープ
        srt_path_escaped = str(srt_file).replace("\\", "/").replace(":", "\\:")
        # 字幕のスタイル設定
        subtitle_filter = f"subtitles='{srt_path_escaped}':force_style='FontName=Meiryo,FontSize=24,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,BorderStyle=3,Outline=2,Shadow=1'"
        vf_filters.append(subtitle_filter)
    
    vf_string = ",".join(vf_filters)
    
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", str(input_file),
        "-t", str(duration),
        "-vf", vf_string,
        "-c:v", "libx264", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        str(output_file)
    ]
    return run_ffmpeg(cmd, description)

def extract_clip_simple(input_file, output_file, start, duration, description=""):
    """シンプルなクリップ抽出（字幕なし、書道シーン用）"""
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", str(input_file),
        "-t", str(duration),
        "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
        "-c:v", "libx264", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        str(output_file)
    ]
    return run_ffmpeg(cmd, description)

def create_title_card(output_file, text="", duration=4):
    """タイトルカード作成"""
    text_filter = ""
    if text:
        text_filter = f",drawtext=fontfile='{FONT_PATH}':text='{text}':fontsize=64:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2:borderw=3:bordercolor=black"
    
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-t", str(duration),
        "-i", str(ARTWORK),
        "-loop", "1", "-t", str(duration),
        "-i", str(LOGO),
        "-filter_complex",
        f"[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2[bg];"
        f"[1:v]scale=250:-1[logo];"
        f"[bg][logo]overlay=W-w-30:H-h-30:format=auto,fade=t=in:st=0:d=0.5,fade=t=out:st={duration-0.5}:d=0.5{text_filter}[v]",
        "-map", "[v]",
        "-c:v", "libx264", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-t", str(duration),
        str(output_file)
    ]
    return run_ffmpeg(cmd, f"Creating title card: {text[:20] if text else 'Logo'}")

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
    print("美麗書院 プロモーション映像 v2 生成")
    print("修正: 字幕追加、動画02短縮、動画03/04追加")
    print("=" * 60)
    
    clips = []
    
    # 1. タイトルカード（4秒）
    title_card = TEMP_DIR / "01_title.mp4"
    if create_title_card(title_card, text="", duration=4):
        clips.append(title_card)
    
    # 2. オープニング - 自己紹介（8秒）字幕付き
    clip_intro = TEMP_DIR / "02_intro.mp4"
    if extract_clip_with_subtitles(VIDEO_01, clip_intro, start=0, duration=8, 
                                    srt_file=SRT_01, description="Opening intro with subtitles"):
        clips.append(clip_intro)
    
    # 3. チャンネルコンセプト（12秒）字幕付き
    clip_concept = TEMP_DIR / "03_concept.mp4"
    if extract_clip_with_subtitles(VIDEO_01, clip_concept, start=4, duration=12,
                                    srt_file=SRT_01, description="Channel concept with subtitles"):
        clips.append(clip_concept)
    
    # 4. ゲスト紹介（10秒）字幕付き
    clip_guest = TEMP_DIR / "04_guest.mp4"
    if extract_clip_with_subtitles(VIDEO_01, clip_guest, start=31, duration=10,
                                    srt_file=SRT_01, description="Guest intro with subtitles"):
        clips.append(clip_guest)
    
    # 5. 書道実演ハイライト（5秒）- 動画02から短く
    clip_demo = TEMP_DIR / "05_demo.mp4"
    if extract_clip_simple(VIDEO_02, clip_demo, start=60, duration=5,
                          description="Calligraphy demo (short)"):
        clips.append(clip_demo)
    
    # 6. 動画03ハイライト - 後編の印象的シーン（8秒）字幕付き
    clip_part3 = TEMP_DIR / "06_part3.mp4"
    if extract_clip_with_subtitles(VIDEO_03, clip_part3, start=30, duration=8,
                                    srt_file=SRT_03, description="Part 3 highlight with subtitles"):
        clips.append(clip_part3)
    
    # 7. 動画04ハイライト - 趣味の話（8秒）字幕付き
    clip_part4 = TEMP_DIR / "07_part4.mp4"
    if extract_clip_with_subtitles(VIDEO_04, clip_part4, start=60, duration=8,
                                    srt_file=SRT_04, description="Part 4 highlight with subtitles"):
        clips.append(clip_part4)
    
    # 8. エンディング（3秒）
    end_card = TEMP_DIR / "08_end.mp4"
    if create_title_card(end_card, text="チャンネル登録お願いします", duration=3):
        clips.append(end_card)
    
    # 結合
    if len(clips) > 0:
        print(f"\nConcatenating {len(clips)} clips...")
        if concat_videos(clips, OUTPUT_VIDEO):
            # 動画情報表示
            print(f"\n{'=' * 60}")
            print(f"✅ プロモーション映像 v2 生成完了!")
            print(f"Output: {OUTPUT_VIDEO}")
            print(f"{'=' * 60}")
            print("\n構成:")
            print("  1. タイトルカード (4秒)")
            print("  2. オープニング - 自己紹介 (8秒) ※字幕付き")
            print("  3. チャンネルコンセプト (12秒) ※字幕付き")
            print("  4. ゲスト紹介 (10秒) ※字幕付き")
            print("  5. 書道実演 (5秒)")
            print("  6. 動画03ハイライト (8秒) ※字幕付き")
            print("  7. 動画04ハイライト (8秒) ※字幕付き")
            print("  8. エンディング (3秒)")
            print(f"\n合計: 約58秒")
            return True
    
    return False

if __name__ == "__main__":
    main()
