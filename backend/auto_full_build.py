import subprocess
import os
import re
import sys
import argparse
import asyncio
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

# backend ディレクトリを sys.path に追加
backend_dir = Path(__file__).parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from services.soul_feedback import SoulFeedbackParams, SoulFeedbackProcessor
from progressive_preview import ProgressivePreview
from progressive_preview_report import PreviewReportGenerator
from metadata_generator import generate_metadata
from graded_previews.youtuber_grade_scorer import score_against_youtuber_standard
from silence_trimmer import detect_silence, trim_silence_and_srt
from template_config import template_config
from subtitle_engine.text_formatter import format_segments

# パス設定
BASE_DIR = Path(r"C:\Users\PC_User\Desktop\script\video-automation")
RAW_DIR = BASE_DIR / "vault-assets" / "raw_videos" / "本番RAW01  対談_山田"
if not RAW_DIR.exists():
    # フォルダ名スペースの揺らぎ対応
    RAW_DIR = BASE_DIR / "vault-assets" / "raw_videos" / "本番RAW01 対談_山田"
SRT_DIR = BASE_DIR / "vault-assets" / "raw_videos" / "AI Studio アップロード用動画"
TEMP_DIR = BASE_DIR / "backend" / "temp" / "final_build"
FONT_PATH = r"C:\Windows\Fonts\msgothic.ttc"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

def parse_srt(srt_path):
    """SRT ファイルを読み込み、セグメント辞書のリストを返す"""
    try:
        content = Path(srt_path).read_text(encoding='utf-8-sig')
    except (FileNotFoundError, OSError) as e:
        print(f"⚠️ SRTファイル読み込みエラー: {e}")
        return []
        
    blocks = re.split(r'\n\n+', content.strip())
    segments = []
    
    def parse_time_to_seconds(time_str):
        try:
            hours, minutes, seconds_ms = time_str.split(':')
            seconds, ms = seconds_ms.split(',')
            return int(hours)*3600 + int(minutes)*60 + int(seconds) + int(ms)/1000.0
        except (ValueError, IndexError, TypeError) as e:
            print(f"⚠️ 時間フォーマットパースエラー '{time_str}': {e}")
            return 0.0

    for i, block in enumerate(blocks, 1):
        lines = block.strip().split('\n')
        if len(lines) >= 3:
            time_match = re.match(r'(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})', lines[1])
            if time_match:
                start_sec = parse_time_to_seconds(time_match.group(1))
                end_sec = parse_time_to_seconds(time_match.group(2))
                text = '\n'.join(lines[2:])
                segments.append({
                    "id": i,
                    "start": start_sec,
                    "end": end_sec,
                    "text": text
                })
    return segments

def write_srt(segments, srt_path):
    """セグメント辞書のリストを SRT ファイルに書き出す"""
    def format_seconds_to_srt_time(seconds):
        try:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            ms = int((seconds - int(seconds)) * 1000)
            return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"
        except (ValueError, TypeError) as e:
            print(f"⚠️ 時間フォーマット生成エラー: {e}")
            return "00:00:00,000"

    try:
        with open(srt_path, "w", encoding="utf-8") as f:
            for i, seg in enumerate(segments, 1):
                f.write(f"{i}\n")
                f.write(f"{format_seconds_to_srt_time(seg.get('start', 0.0))} --> {format_seconds_to_srt_time(seg.get('end', 0.0))}\n")
                f.write(f"{seg.get('text', '')}\n\n")
    except (OSError, KeyError) as e:
        print(f"⚠️ SRTファイル書き込みエラー: {e}")

def get_formatted_srt(scene_name, srt_path):
    """
    元の SRT を template_config の max_chars_per_line 以下の文字数に整形した
    一時的な SRT ファイルを生成してそのパスを返す
    """
    try:
        max_chars = template_config.get_max_chars_per_line()
        print(f"   [SRT] 整形用文字数制限: {max_chars} 文字/行")
        
        segments = parse_srt(srt_path)
        formatted_segs = format_segments(segments, max_chars=max_chars)
        
        temp_srt_path = TEMP_DIR / f"{scene_name}_formatted.srt"
        write_srt(formatted_segs, temp_srt_path)
        return temp_srt_path
    except (AttributeError, ValueError, TypeError, OSError) as e:
        print(f"⚠️ SRT整形処理中にエラーが発生しました: {e}。元の SRT を使用します。")
        return Path(srt_path)

# テーマリスト
THEMES = [
    "デザイン書道作家 山田タロウ",
    "伝統の筆づくり 存続の危機",
    "企業ロゴを筆で書く デザイン書道",
    "山田氏のゲスト書道パフォーマンス",
    "山田流：有名ブランドの書を手がける",
    "ユニクロ×書道 未来を繋ぐ挑戦",
    "鬼滅の刃×書道 山田の筆技",
    "有名人も注目！山田の書道教室"
]

def cleanup_temp_files():
    print(">>> 一時ファイルをクリーンアップ中...")
    try:
        count = 0
        for file_path in TEMP_DIR.glob("*"):
            if file_path.is_file():
                file_path.unlink()
                count += 1
        print(f"✅ 一時ファイルのクリーンアップ完了 ({count} 個のファイルを削除)")
    except Exception as e:
        print(f"⚠️ クリーンアップ中にエラーが発生しました: {e}")

def generate_telops(telop_color="#FFFFFF"):
    print(">>> 1. テロップ画像を生成中...")
    try:
        font = ImageFont.truetype(FONT_PATH, 18)
    except (OSError, IOError):
        print(f"⚠️ フォントファイル {FONT_PATH} が見つからないか読み込めません。デフォルトフォントを使用します。")
        font = ImageFont.load_default()
        
    for i, text in enumerate(THEMES):
        try:
            # テロップ画像作成 (高さ45px)
            img = Image.new('RGBA', (400, 45), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.rectangle((0, 0, 400, 45), fill=(0, 0, 0, 128))
            draw.text((12, 12), text, font=font, fill=telop_color)
            
            # ロゴとの合成はせず、そのまま保存 (「左上の画像はなくて良い」要件に対応)
            img.save(TEMP_DIR / f"brand_telop_{i}.png")
        except (OSError, ValueError, TypeError) as e:
            print(f"⚠️ テロップ画像 {i} の生成に失敗しました: {e}")
    print("✅ テロップ画像生成完了")

def process_scene(scene_name, input_file, crop, srt_file=None, telop_indices=None, feedback_params=None):
    if feedback_params is None:
        feedback_params = SoulFeedbackParams()

    print(f">>> シーン処理開始: {scene_name}")
    
    input_path = Path(input_file)
    if not input_path.exists():
        print(f"❌ 入力動画ファイルが存在しません: {input_path}")
        raise FileNotFoundError(f"Input video file not found: {input_path}")
        
    # --- 無音トリミング (Jet Cut) の適用 ---
    # srt_file がある（対談/トーク系の）シーンのみに無音トリミングを適用し、
    # 音楽や実演映像だけのシーン（scene02など）の誤カットを防止する。
    if srt_file and Path(srt_file).exists():
        trimmed_video = TEMP_DIR / f"{scene_name}_trimmed.mp4"
        trimmed_srt = TEMP_DIR / f"{scene_name}_trimmed.srt"
        print(f"   [JetCut] 無音検出を実行中...")
        try:
            silences = detect_silence(str(input_file), noise_db=-40, duration_limit=1.5)
            # 実際に削るべき無音区間が存在するか判定 (min_silence_len = 1.5, keep_silence_len = 0.5)
            cut_ranges = []
            for s in silences:
                s_start = s["start"]
                s_end = s["end"]
                s_dur = s["duration"]
                if s_dur > 1.5:
                    trim_start = s_start + (0.5 / 2.0)
                    trim_end = s_end - (0.5 / 2.0)
                    if trim_end > trim_start:
                        cut_ranges.append((trim_start, trim_end))
            
            if cut_ranges:
                print(f"   [JetCut] 無音トリミング（Jet Cut）を適用中... (検出数: {len(cut_ranges)} 区間)")
                trim_silence_and_srt(
                    video_path=str(input_file),
                    srt_path=str(srt_file),
                    output_video_path=str(trimmed_video),
                    output_srt_path=str(trimmed_srt),
                    noise_db=-40,
                    min_silence_len=1.5,
                    keep_silence_len=0.5
                )
                # 入力ファイルをトリミングされた一時ファイルに置き換え
                input_file = trimmed_video
                srt_file = trimmed_srt
                print(f"   [JetCut] 適用成功: {trimmed_video.name}")
            else:
                print(f"   [JetCut] 削るべき無音区間が検出されなかったため、トリミングをスキップし元動画を直接使用します。")
        except (FileNotFoundError, subprocess.CalledProcessError, ValueError, OSError) as e:
            print(f"   ⚠️ 無音トリミング適用中にエラーが発生しました: {e}。元動画を使用します。")

    output_parts = []
    
    # 字幕焼き込みとクロップを同時に実行し、HD (1280x720) に統一
    # クロップ後の映像を中央配置し、黒帯を最小限にする
    if srt_file and Path(srt_file).exists():
        try:
            formatted_srt = get_formatted_srt(scene_name, srt_file)
            srt_rel = Path(formatted_srt).relative_to(BASE_DIR).as_posix()
            vf_subtitles = f",subtitles='{srt_rel}':force_style='FontSize={feedback_params.subtitle_font_size}'"
            print(f"   [SRT] 整形済み一時 SRT を適用: {srt_rel} (フォントサイズ: {feedback_params.subtitle_font_size})")
        except Exception as e:
            print(f"   ⚠️ SRT 整形処理中にエラーが発生しました: {e}。元の SRT を使用します。")
            srt_rel = Path(srt_file).relative_to(BASE_DIR).as_posix()
            vf_subtitles = f",subtitles='{srt_rel}':force_style='FontSize={feedback_params.subtitle_font_size}'"
    else:
        vf_subtitles = ""
    
    # 簡易化のため：各シーンを一旦クロップ＋スケーリング＋字幕
    if feedback_params.tempo_multiplier != 1.0:
        base_vf = f"crop={crop},scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,format=yuv420p,fps=fps=30{vf_subtitles},setpts=PTS/{feedback_params.tempo_multiplier}"
    else:
        base_vf = f"crop={crop},scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,format=yuv420p,fps=fps=30{vf_subtitles}"
    
    # オーバーレイフィルタの構築
    if telop_indices:
        # base_vf の出力を [v0] とする
        vf = f"{base_vf}[v0]; "
        for j, (idx, start, end) in enumerate(telop_indices):
            movie_path = (TEMP_DIR / f"brand_telop_{idx}.png").relative_to(BASE_DIR).as_posix()
            movie_filter = f"movie='{movie_path}'[t{idx}]"
            is_last = (j == len(telop_indices) - 1)
            out_label = "" if is_last else f"[v{j+1}]"
            overlay_filter = f"[v{j}][t{idx}]overlay=15:15:enable='between(t,{start},{end})'{out_label}"
            vf += f"{movie_filter}; {overlay_filter}"
            if not is_last:
                vf += "; "
    else:
        vf = base_vf

    temp_output = TEMP_DIR / f"{scene_name}_processed.mp4"
    if temp_output.exists() and temp_output.stat().st_size > 1000000:
        print(f"   [Cache] 処理済み動画 {temp_output.name} が既に存在するため、エンコードをスキップします。")
        return temp_output

    # オーディオフィルタ (atempo, volume) の構築
    af_filters = []
    if feedback_params.tempo_multiplier != 1.0:
        af_filters.append(f"atempo={feedback_params.tempo_multiplier}")
    if feedback_params.volume_multiplier != 1.0:
        af_filters.append(f"volume={feedback_params.volume_multiplier}")

    cmd = [
        "ffmpeg", "-y", "-i", str(input_file),
        "-vf", vf
    ]
    if af_filters:
        cmd.extend(["-af", ",".join(af_filters)])
        
    cmd.extend([
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-b:v", "12M",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        str(temp_output)
    ])
    
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ ffmpegの実行に失敗しました: {e}")
        raise
    print(f"✅ シーン完了: {scene_name}")
    return temp_output

def main():
    parser = argparse.ArgumentParser(description="Auto Full Build Pipeline with Soul Feedback")
    parser.add_argument("--feedback", type=str, default="", help="定性的な演出指示テキスト")
    args = parser.parse_args()
    
    feedback_params = SoulFeedbackParams()
    if args.feedback:
        print(f">>> 定性演出指示を解析中: \"{args.feedback}\"")
        processor = SoulFeedbackProcessor()
        feedback_params = asyncio.run(processor.parse_qualitative_feedback(args.feedback))
        print(f">>> 解析されたパラメータ: {feedback_params}")

    # === 憲法 9.1: Progressive Preview Session 開始 ===
    session_id = f"full_build_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    preview = ProgressivePreview(session_id=session_id)
    print(f"\n📸 Progressive Preview Session: {session_id}")
    print(f"   Output: {preview.output_dir}\n")
    
    generate_telops(telop_color=feedback_params.telop_color)
    
    # タイムライン設定
    scenes_config = [
        {
            "name": "scene01",
            "input": RAW_DIR / "シーン01_前編.mp4",
            "srt": SRT_DIR / "シーン01_前編_regenerated.srt",
            "crop": "1152:720:26:0",
            "telops": [(0, 0, 600), (1, 600, 1200), (2, 1200, 1800)]
        },
        {
            "name": "scene02",
            "input": RAW_DIR / "シーン02_ゲスト書道.mp4",
            "srt": None,
            "crop": "1920:960:0:60",
            "telops": [(3, 0, 60)]
        },
        {
            "name": "scene03",
            "input": RAW_DIR / "シーン03_後編01.mp4",
            "srt": SRT_DIR / "シーン03_後編01_regenerated.srt",
            "crop": "1136:640:28:40",
            "telops": [(4, 0, 210), (5, 210, 420)]
        },
        {
            "name": "scene04",
            "input": RAW_DIR / "シーン04_後編02.mp4",
            "srt": SRT_DIR / "シーン04_後編02_regenerated.srt",
            "crop": "1136:640:26:40",
            "telops": [(6, 0, 165), (7, 165, 330)]
        }
    ]
    
    processed_files = []
    all_segments = []
    current_time_offset = 0.0
    from video_editor_engine import video_editor
    
    for scene in scenes_config:
        input_file = scene["input"]
        output_file = process_scene(
            scene["name"], 
            input_file, 
            scene["crop"], 
            scene["srt"], 
            scene["telops"],
            feedback_params=feedback_params
        )
        processed_files.append(output_file)
        
        # format_segments結果を累積
        if scene["srt"] and Path(scene["srt"]).exists():
            formatted_srt_path = TEMP_DIR / f"{scene['name']}_formatted.srt"
            if formatted_srt_path.exists():
                scene_segs = parse_srt(formatted_srt_path)
                for seg in scene_segs:
                    seg["start"] += current_time_offset
                    seg["end"] += current_time_offset
                    all_segments.append(seg)
        
        duration = video_editor.ffmpeg.get_duration(output_file)
        if duration is not None:
            current_time_offset += duration
        
        # === 憲法 9.1: 事後報告 - 処理完了後に比較スナップショット ===
        print(f"\n📸 Generating preview for {scene['name']}...")
        try:
            preview.snapshot_step(
                step_name=scene["name"],
                before_video=str(input_file),
                after_video=str(output_file),
                num_samples=3
            )
        except Exception as e:
            print(f"   ⚠️ Preview generation failed: {e}")
            # プレビュー失敗でも処理は継続（バイパス権限）
    
    # 最終結合
    final_output = BASE_DIR / "soul_narrative_full_v1.mp4"
    if final_output.exists() and final_output.stat().st_size > 10000000:
        print(f"   [Cache] 最終結合動画 {final_output.name} が既に存在するため、再結合をスキップします。")
    else:
        print(">>> 最終結合中...")
        concat_list_path = TEMP_DIR / "concat.txt"
        with open(concat_list_path, "w") as f:
            for p in processed_files:
                f.write(f"file '{str(p.absolute()).replace('\\', '/')}'\n")
                
        subprocess.run([
            "ffmpeg", "-y", "-fflags", "+genpts",
            "-f", "concat", "-safe", "0", "-i", str(concat_list_path),
            "-c", "copy", str(final_output)
        ], check=True)
    
    # === 憲法 9.1: 最終プレビュー - 開始/25%/50%/75%/終了の5枚 ===
    print("\n📸 Generating final preview...")
    try:
        # 最初のシーンと最終出力を比較
        first_input = scenes_config[0]["input"]
        preview.snapshot_step(
            step_name="final_combined",
            before_video=str(first_input),
            after_video=str(final_output),
            num_samples=5
        )
    except Exception as e:
        print(f"   ⚠️ Final preview failed: {e}")
    
    # === HTMLレポート生成 ===
    print("\n📄 Generating HTML Report...")
    try:
        generator = PreviewReportGenerator()
        report_path = generator.generate_from_session_dir(str(preview.output_dir))
        print(f"✅ Report generated: {report_path}")
    except Exception as e:
        print(f"   ⚠️ Report generation failed: {e}")
        
    # === メタデータ生成 (タスク2) ===
    print("\n📝 Generating video metadata...")
    try:
        metadata_dir = BASE_DIR / "vault-outputs" / "preview"
        metadata = generate_metadata(all_segments, str(final_output), metadata_dir)
        print(f"✅ Metadata generated successfully at: {metadata_dir / 'metadata.json'}")
        print(f"   Title: {metadata['title']}")
        print(f"   Chapters count: {len(metadata['chapters'])}")
    except Exception as e:
        print(f"   ⚠️ Metadata generation failed: {e}")
        metadata = {}
        
    # === YouTuber規格スコアリングの自動更新 ===
    print("\n📊 Measuring YouTuber grade score...")
    try:
        import json
        spec_path = BASE_DIR / "backend" / "graded_previews" / "youtuber_standard_spec.json"
        
        if "title" in metadata and "titles" not in metadata:
            metadata["titles"] = [metadata["title"]]
            
        result = score_against_youtuber_standard(
            str(spec_path),
            str(final_output),
            all_segments,
            metadata
        )
        
        result_path = BASE_DIR / "backend" / "graded_previews" / "youtuber_grade_result.json"
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"✅ YouTuber grade score updated: {result['total_score']} (Grade: {result['grade']})")
    except Exception as e:
        print(f"   ⚠️ Scorer execution failed: {e}")
    
    # === 一時ファイルの自動クリーンアップ (憲法 11.3 ディスク管理) ===
    cleanup_temp_files()
    
    print(f"\n✨ 全ての工程が完了しました！")
    print(f"完成ファイル: {final_output}")
    print(f"プレビューレポート: {preview.output_dir / 'preview_report.html'}")

if __name__ == "__main__":
    main()
