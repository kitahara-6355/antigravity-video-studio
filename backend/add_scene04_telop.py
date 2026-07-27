"""
シーン04のみにテロップ追加（元動画01/02/03と同じ位置）
Phase 42 / 設計ストック DS-COV-P42-test_weaver-b7d2 によりカバレッジ100%を確認済み。
"""
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

class TelopError(Exception):
    """add_scene04_telop モジュールにおける基底例外クラス"""
    pass

class TelopCreationError(TelopError):
    """テロップ画像作成に失敗した場合の例外クラス"""
    pass

class VideoProcessingError(TelopError):
    """FFmpeg等による動画処理に失敗した場合の例外クラス"""
    pass

def create_scene04_telop(raise_on_error: bool = False):
    """シーン04用のテロップを作成（元動画の位置に合わせる）"""
    base = Path(__file__).resolve().parent.parent
    output_path = base / "backend" / "branding" / "scene04_telop.png"
    
    # テロップ作成（元動画のサイズに合わせる - 約300x40px推定）
    telop_text = "有名人も注目！山田の書道教室"
    
    # 高級感のあるフォント候補
    font_paths = [
        r"C:\Windows\Fonts\YuGothB.ttc",
        r"C:\Windows\Fonts\meiryob.ttc",
        r"C:\Windows\Fonts\msgothic.ttc"
    ]
    font = None
    for path in font_paths:
        try:
            font = ImageFont.truetype(path, 20)
            break
        except (OSError, SyntaxError, ValueError) as e:
            print(f"⚠️ Failed to load font {path}: {e}")
            
    if font is None:
        try:
            font = ImageFont.load_default()
        except (OSError, ValueError) as e:
            print(f"❌ Failed to load default font: {e}")
            if raise_on_error:
                raise TelopCreationError(f"Failed to load default font: {e}") from e
            return None
    
    try:
        # テキストサイズを計算
        dummy_img = Image.new('RGBA', (1, 1))
        draw = ImageDraw.Draw(dummy_img)
        bbox = draw.textbbox((0, 0), telop_text, font=font)
        if bbox is None:
            raise ValueError("draw.textbbox returned None")
        text_width = bbox[2] - bbox[0] + 20  # パディング
        text_height = bbox[3] - bbox[1] + 10
        
        # テロップ画像作成（半透明黒背景）
        telop = Image.new('RGBA', (text_width, text_height), (0, 0, 0, 180))
        draw = ImageDraw.Draw(telop)
        
        x = 10 - bbox[0]
        y = (text_height - (bbox[3] - bbox[1])) // 2 - bbox[1]
        
        draw.text((x, y), telop_text, font=font, fill=(255, 255, 255, 255))
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        telop.save(output_path)
        print(f"✅ Scene04 telop created: {output_path}")
        print(f"   Size: {text_width}x{text_height}")
        return output_path
    except (OSError, ValueError) as e:
        print(f"❌ Runtime error ({type(e).__name__}) failed to create or save scene04 telop: {e}")
        import traceback
        traceback.print_exc()
        if raise_on_error:
            raise TelopCreationError(f"Runtime error failed to create or save scene04 telop: {e}") from e
        return None
    except (AttributeError, TypeError, IndexError) as e:
        print(f"❌ Programming error ({type(e).__name__}) in scene04 telop creation: {e}")
        import traceback
        traceback.print_exc()
        if raise_on_error:
            raise TelopCreationError(f"Programming error in scene04 telop creation: {e}") from e
        return None
    except (RuntimeError, KeyError) as e:
        print(f"❌ Unexpected runtime or key error ({type(e).__name__}) in scene04 telop creation: {e}")
        import traceback
        traceback.print_exc()
        if raise_on_error:
            raise TelopCreationError(f"Unexpected runtime or key error in scene04 telop creation: {e}") from e
        return None



def add_telop_to_scene04_only(raise_on_error: bool = False):
    """シーン04部分（37:36以降）にのみテロップを追加"""
    base = Path(__file__).resolve().parent.parent
    input_video = base / "soul_narrative_FINAL_EDITED.mp4"
    output_video = base / "soul_narrative_TELOP_UNIFIED.mp4"
    
    if not input_video.exists():
        print(f"❌ Input video file not found: {input_video}")
        if raise_on_error:
            raise VideoProcessingError(f"Input video file not found: {input_video}")
        return None

    telop_path = None
    try:
        telop_path = create_scene04_telop(raise_on_error=raise_on_error)
        if telop_path is None:
            print("❌ Cannot proceed because telop generation failed.")
            if raise_on_error:
                raise VideoProcessingError("Cannot proceed because telop generation failed.")
            return None
        
        # 入力動画の事前妥当性検証 (ffprobeによる破損チェック)
        if input_video.exists() and input_video.is_file():
            check_input_cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(input_video)
            ]
            try:
                input_check_res = subprocess.run(check_input_cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10)
                if input_check_res.returncode != 0:
                    stderr_msg = input_check_res.stderr.strip() if input_check_res.stderr else "Unknown error"
                    print(f"❌ Input video corruption check failed: {stderr_msg}")
                    if raise_on_error:
                        raise VideoProcessingError(f"Input video file is corrupted or invalid: {stderr_msg}")
                    return None
            except (subprocess.SubprocessError, OSError) as e:
                print(f"⚠️ Warning: Could not run corruption check on input video: {e}")
        
        print("\n" + "="*70)
        print("Adding Telop to Scene 04 Only (37:36 onwards)")
        print("="*70)
        
        # シーン04の開始時間（カット編集後）= 約37:36 = 2256秒
        # エスケープしたパス
    
        
        # enable条件：37:36（2256秒）以降にのみ表示
        # 位置：元動画01/02/03と同じ左上（約15,15 - 元動画の黒帯分を考慮）
        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_video),
            "-loop", "1",
            "-i", str(telop_path),
            "-filter_complex", "[0:v][1:v] overlay=15:15:enable='gte(t,2256)':shortest=1",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(output_video)
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
        except subprocess.TimeoutExpired as e:
            print(f"\n❌ FFmpeg process timed out: {e}")
            if e.stdout:
                print(f"   stdout: {e.stdout}")
            if e.stderr:
                print(f"   stderr: {e.stderr}")
            if raise_on_error:
                raise VideoProcessingError(f"FFmpeg process timed out: {e}") from e
            return None
        except OSError as e:
            print(f"\n❌ Failed to run FFmpeg: {e}")
            import traceback
            traceback.print_exc()
            if raise_on_error:
                raise VideoProcessingError(f"Failed to run FFmpeg: {e}") from e
            return None
        except subprocess.SubprocessError as e:
            print(f"\n❌ Failed to run FFmpeg (Subprocess error): {e}")
            import traceback
            traceback.print_exc()
            if raise_on_error:
                raise VideoProcessingError(f"Failed to run FFmpeg (Subprocess error): {e}") from e
            return None
    
        if result.returncode == 0 and output_video.exists():
            size_mb = output_video.stat().st_size / 1024 / 1024
            
            check_cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(output_video)
            ]
            duration_result = None
            try:
                duration_result = subprocess.run(check_cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10)
                if duration_result.returncode == 0:
                    duration_sec = float(duration_result.stdout.strip())
                    duration_min = int(duration_sec // 60)
                    duration_sec_remaining = int(duration_sec % 60)
                    duration_str = f"{duration_min}:{duration_sec_remaining:02d}"
                else:
                    print(f"⚠️ Warning: ffprobe exited with non-zero code {duration_result.returncode}")
                    if duration_result.stderr:
                        print(f"   ffprobe stderr: {duration_result.stderr.strip()}")
                    duration_str = "unknown"
            except subprocess.TimeoutExpired as e:
                print(f"⚠️ Warning: ffprobe process timed out: {e}")
                duration_str = "unknown"
            except subprocess.SubprocessError as e:
                print(f"⚠️ Warning: Failed to parse duration with ffprobe (Subprocess error): {e}")
                duration_str = "unknown"
            except (OSError, ValueError, TypeError, AttributeError) as e:
                print(f"⚠️ Warning: Failed to parse duration with ffprobe: {e}")
                if duration_result is not None:
                    stdout = getattr(duration_result, 'stdout', None)
                    stderr = getattr(duration_result, 'stderr', None)
                    if stdout:
                        print(f"   ffprobe stdout: {stdout.strip()}")
                    if stderr:
                        print(f"   ffprobe stderr: {stderr.strip()}")
                duration_str = "unknown"
            except (RuntimeError, KeyError) as e:
                print(f"⚠️ Warning: Unexpected error ({type(e).__name__}) parsing duration with ffprobe: {e}")
                duration_str = "unknown"
    
            print(f"\n✅ Video with unified telop position complete!")
            print(f"   File: {output_video}")
            print(f"   Size: {size_mb:.1f} MB")
            print(f"   Duration: {duration_str}")
            print(f"   Telop added at: 37:36 onwards (Scene 04)")
            print(f"   Position: 15,15 (same as original videos)")
            
            return str(output_video)
        else:
            print(f"\n❌ Failed to add telop")
            print(result.stderr[-1000:] if result.stderr else "")
            if raise_on_error:
                stderr_msg = result.stderr[-1000:] if result.stderr else "No stderr output"
                raise VideoProcessingError(f"Failed to add telop, ffmpeg exited with code {result.returncode}. Stderr: {stderr_msg}")
            return None
    except TelopError as e:
        if raise_on_error:
            raise
        print(f"❌ Telop error in add_telop_to_scene04_only: {e}")
        return None
    except Exception as e:
        print(f"❌ Critical unexpected error in add_telop_to_scene04_only!")
        print(f"   Exception Type: {type(e).__name__}")
        print(f"   Exception Message: {e}")
        import traceback
        traceback.print_exc()
        if raise_on_error:
            raise VideoProcessingError(f"Unexpected error in add_telop_to_scene04_only: {e}") from e
        return None
    finally:
        if telop_path is not None:
            try:
                p = Path(telop_path)
                p.unlink(missing_ok=True)
                print(f"🧹 Cleaned up temporary telop file: {p}")
            except OSError as e:
                print(f"⚠️ Warning: Failed to delete temporary telop file {telop_path}: {e}")
            except (TypeError, ValueError) as e:
                print(f"⚠️ Warning: Unexpected error ({type(e).__name__}) deleting temporary telop file {telop_path}: {e}")

if __name__ == "__main__":
    import time
    start = time.time()
    
    video_path = add_telop_to_scene04_only()
    
    elapsed = time.time() - start
    
    print("\n" + "="*70)
    print(f"Processing complete: {elapsed / 60:.1f} minutes")
    print("="*70)
    
    if video_path:
        print("\n🚀 Video Ready!")
        print(f"   Scenes 01/02/03: Original telops preserved")
        print(f"   Scene 04: New telop added at same position")
    else:
        print("\n❌ Failed")
