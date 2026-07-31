"""
元のRAW動画から完全に再構築
クロップ + カット編集 + 全編プレミアムテロップ
"""
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path

import subprocess
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import ctypes
# ctypes.wintypes は Windows 専用。Linux（CI）では import 自体が失敗する
try:
    from ctypes import wintypes
except (ImportError, ValueError):
    wintypes = None
import time
import logging

logger = logging.getLogger("clean_rebuild")

# Progressive Preview System (憲法 9.1 視覚確認プロトコル)
from progressive_preview import ProgressivePreview
from services.preview_report_generator import PreviewReportGenerator

# ショートパス変換
_GetShortPathNameW = None
try:
    if hasattr(ctypes, "windll") and wintypes is not None:
        _GetShortPathNameW = ctypes.windll.kernel32.GetShortPathNameW
        _GetShortPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        _GetShortPathNameW.restype = wintypes.DWORD
except (AttributeError, ImportError, NameError) as e:
    logger.warning("Failed to initialize Windows short path API: %s", e)

def get_short_path(long_path):
    import os
    path = os.path.abspath(long_path)
    if not os.path.exists(path) or _GetShortPathNameW is None:
        return path
    output_buf_size = 256
    try:
        output_buf = ctypes.create_unicode_buffer(output_buf_size)
        needed = _GetShortPathNameW(path, output_buf, output_buf_size)
        while needed > output_buf_size:
            output_buf_size = needed
            output_buf = ctypes.create_unicode_buffer(output_buf_size)
            needed = _GetShortPathNameW(path, output_buf, output_buf_size)
        return output_buf.value if needed > 0 else path
    except (ctypes.ArgumentError, TypeError, ValueError, OSError) as e:
        logger.error("Error getting short path: %s", e)
        return path

def create_premium_branding():
    """プレミアムブランディング画像を作成"""
    base = Path(__file__).resolve().parent.parent
    logo_path = base / "backend" / "branding" / "logos" / "brand_logo.png"
    output_path = _writable_path("backend/branding/premium_branding.png")
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    logo = None
    try:
        if logo_path.exists():
            logo = Image.open(logo_path).convert('RGBA')
            logo.thumbnail((28, 45), Image.Resampling.LANCZOS)
        else:
            logger.warning("Brand logo file not found: %s. Proceeding without logo.", logo_path)
    except (OSError, ValueError) as e:
        logger.error("Failed to load brand logo %s: %s. Proceeding without logo.", logo_path, e)
    
    telop_text = "デザイン書道作家 山田タロウ"
    telop = Image.new('RGBA', (330, 45), (0, 0, 0, 128))
    draw = ImageDraw.Draw(telop)
    
    font = None
    fonts_to_try = [
        r"C:\Windows\Fonts\YuGothB.ttc",
        r"C:\Windows\Fonts\msgothic.ttc",
        r"C:\Windows\Fonts\YuGothic.ttf",
        r"C:\Windows\Fonts\arial.ttf"
    ]
    for font_path in fonts_to_try:
        try:
            font = ImageFont.truetype(font_path, 20)
            break
        except OSError:
            continue
            
    if font is None:
        try:
            font = ImageFont.load_default()
            logger.warning("All premium fonts failed. Using default font.")
        except Exception as e:
            logger.error("Failed to load default font: %s", e)
            raise OSError("No usable font found") from e
    
    bbox = draw.textbbox((0, 0), telop_text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = (330 - text_width) // 2
    y = (45 - text_height) // 2
    draw.text((x, y), telop_text, font=font, fill=(255, 255, 255, 255))
    
    combined = Image.new('RGBA', (358, 45), (0, 0, 0, 0))
    if logo is not None:
        combined.paste(logo, (0, 0), logo)
        combined.paste(telop, (28, 0), telop)
    else:
        combined.paste(telop, (14, 0), telop)
        
    combined.save(output_path)
    print(f"✅ Premium branding: {output_path}")
    return output_path

def run_ffmpeg(cmd, description, timeout=600):
    print(f"\n[{description}] Starting...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding='utf-8', errors='ignore')
        if result.returncode == 0:
            print(f"✅ {description}")
            return True
        else:
            err_msg = result.stderr[-500:] if result.stderr else "No stderr output"
            logger.error("❌ %s failed with return code %s. Stderr: %s", description, result.returncode, err_msg)
            print(f"❌ {description} failed with return code {result.returncode}")
            print(err_msg)
            return False
    except subprocess.TimeoutExpired as e:
        logger.error(f"❌ {description} timed out after {timeout} seconds: {e}")
        print(f"❌ {description} timed out after {timeout} seconds")
        return False
    except FileNotFoundError as e:
        logger.error(f"❌ {description} failed: Command not found: {e}")
        print(f"❌ {description} failed: Command not found")
        return False
    except subprocess.SubprocessError as e:
        logger.error(f"❌ {description} failed with subprocess error: {e}")
        print(f"❌ {description} failed with subprocess error: {e}")
        return False

def clean_rebuild():
    base = Path(__file__).resolve().parent.parent
    raw_dir = base / "raw_videos" / "AI Studio アップロード用動画"
    clean_dir = base / "backend" / "temp" / "clean_rebuild"
    clean_dir.mkdir(parents=True, exist_ok=True)
    
    # === 憲法 9.1: Progressive Preview Session 開始 ===
    session_id = f"clean_rebuild_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    preview = ProgressivePreview(session_id=session_id)
    print(f"\n📸 Progressive Preview Session: {session_id}")
    
    branding = None
    try:
        branding = create_premium_branding()
    except Exception as e:
        logger.exception("Failed to create premium branding image. Proceeding without branding.")
        print(f"   ⚠️ Branding creation failed: {e}")
    
    print("\n" + "="*70)
    print("Step 1: Processing RAW videos with crop")
    print("="*70)
    
    # シーン01: クロップ(1152:720:26:0) → スケール(1280:720) → 30分処理
    s01_raw = get_short_path(str(raw_dir / "シーン01_前編.mp4"))
    s01_out = clean_dir / "s01_clean.mp4"
    
    if not run_ffmpeg([
        "ffmpeg", "-y", "-i", s01_raw,
        "-vf", "crop=1152:720:26:0,scale=1280:720",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
        str(s01_out)
    ], "Scene01 crop+scale", timeout=600):
        logger.error("Scene01 processing failed. Aborting clean rebuild.")
        return None
    
    # シーン02: クロップ(1920:960:0:60) → スケール(1280:720)
    s02_raw = get_short_path(str(raw_dir / "シーン02_ゲスト書道.mp4"))
    s02_out = clean_dir / "s02_clean.mp4"
    
    if not run_ffmpeg([
        "ffmpeg", "-y", "-i", s02_raw,
        "-vf", "crop=1920:960:0:60,scale=1280:720,fps=30",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
        str(s02_out)
    ], "Scene02 crop+scale+fps", timeout=120):
        logger.error("Scene02 processing failed. Aborting clean rebuild.")
        return None
    
    # シーン03: クロップ(1136:640:28:40) → スケール(1280:720)
    s03_raw = get_short_path(str(raw_dir / "シーン03_後編01.mp4"))
    s03_out = clean_dir / "s03_clean.mp4"
    
    if not run_ffmpeg([
        "ffmpeg", "-y", "-i", s03_raw,
        "-vf", "crop=1136:640:28:40,scale=1280:720",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
        str(s03_out)
    ], "Scene03 crop+scale", timeout=300):
        logger.error("Scene03 processing failed. Aborting clean rebuild.")
        return None
    
    # シーン04: クロップ(1136:640:26:40) → スケール(1280:720)
    s04_raw = get_short_path(str(raw_dir / "シーン04_後編02.mp4"))
    s04_out = clean_dir / "s04_clean.mp4"
    
    if not run_ffmpeg([
        "ffmpeg", "-y", "-i", s04_raw,
        "-vf", "crop=1136:640:26:40,scale=1280:720",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
        str(s04_out)
    ], "Scene04 crop+scale", timeout=240):
        logger.error("Scene04 processing failed. Aborting clean rebuild.")
        return None
    
    print("\n" + "="*70)
    print("Step 2: Concatenating 4 scenes")
    print("="*70)
    
    concat_list = clean_dir / "concat.txt"
    written_scenes = 0
    with open(concat_list, "w", encoding="utf-8") as f:
        for scene in [s01_out, s02_out, s03_out, s04_out]:
            if scene.exists():
                f.write(f"file '{str(scene.absolute()).replace(chr(92), '/')}'\n")
                written_scenes += 1
                
    if written_scenes == 0:
        logger.error("No clean scene files found to concatenate. Aborting clean rebuild.")
        return None
    
    merged = clean_dir / "merged_raw.mp4"
    if not run_ffmpeg([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_list), "-c", "copy", str(merged)
    ], "Concatenation", timeout=60):
        logger.error("Concatenation failed. Aborting clean rebuild.")
        return None
    
    # === 憲法 9.1: 結合後のプレビュー ===
    try:
        preview.snapshot_step("concatenation", s01_raw, str(merged), num_samples=3)
    except Exception as e:
        logger.exception("Progressive preview snapshot failed for concatenation")
        print(f"   ⚠️ Preview failed: {e}")
    
    print("\n" + "="*70)
    print("Step 3: Applying cuts")
    print("="*70)
    
    # カット: 30:48-30:51 (3秒), 37:35 (1秒), 37:38-37:47 (9秒)
    # セグメント分割
    seg1 = clean_dir / "cut_seg1.mp4"  # 0:00 - 30:48
    seg2 = clean_dir / "cut_seg2.mp4"  # 30:51 - 37:35
    seg3 = clean_dir / "cut_seg3.mp4"  # 37:36 - 37:38
    seg4 = clean_dir / "cut_seg4.mp4"  # 37:47 - end
    
    if not run_ffmpeg(["ffmpeg", "-y", "-ss", "0", "-t", "1848", "-i", str(merged), "-c", "copy", str(seg1)], "Cut seg1 (0-30:48)", timeout=30):
        logger.error("Cut segment 1 extraction failed. Aborting clean rebuild.")
        return None
    if not run_ffmpeg(["ffmpeg", "-y", "-ss", "1851", "-t", "404", "-i", str(merged), "-c", "copy", str(seg2)], "Cut seg2 (30:51-37:35)", timeout=30):
        logger.error("Cut segment 2 extraction failed. Aborting clean rebuild.")
        return None
    if not run_ffmpeg(["ffmpeg", "-y", "-ss", "2256", "-t", "2", "-i", str(merged), "-c", "copy", str(seg3)], "Cut seg3 (37:36-37:38)", timeout=10):
        logger.error("Cut segment 3 extraction failed. Aborting clean rebuild.")
        return None
    if not run_ffmpeg(["ffmpeg", "-y", "-ss", "2267", "-i", str(merged), "-c", "copy", str(seg4)], "Cut seg4 (37:47-end)", timeout=30):
        logger.error("Cut segment 4 extraction failed. Aborting clean rebuild.")
        return None
    
    cut_list = clean_dir / "cut_concat.txt"
    written_segs = 0
    with open(cut_list, "w", encoding="utf-8") as f:
        for seg in [seg1, seg2, seg3, seg4]:
            if seg.exists():
                f.write(f"file '{str(seg.absolute()).replace(chr(92), '/')}'\n")
                written_segs += 1
                
    if written_segs == 0:
        logger.error("No cut segments found to concatenate. Aborting clean rebuild.")
        return None
    
    cut_merged = clean_dir / "cut_merged.mp4"
    if not run_ffmpeg([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(cut_list), "-c", "copy", str(cut_merged)
    ], "Cut concatenation", timeout=30):
        logger.error("Cut concatenation failed. Aborting clean rebuild.")
        return None
    
    print("\n" + "="*70)
    print("Step 4: Adding premium telop to entire video")
    print("="*70)
    
    final_output = base / "soul_narrative_CLEAN_FINAL.mp4"
    
    overlay_success = False
    if branding and Path(branding).exists():
        overlay_success = run_ffmpeg([
            "ffmpeg", "-y",
            "-i", str(cut_merged),
            "-i", str(branding),
            "-filter_complex", "[0:v][1:v] overlay=15:15",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "copy", "-movflags", "+faststart",
            str(final_output)
        ], "Premium telop overlay", timeout=600)
    else:
        logger.warning("Premium branding image is missing. Generating final output without overlay.")
        overlay_success = run_ffmpeg([
            "ffmpeg", "-y",
            "-i", str(cut_merged),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "copy", "-movflags", "+faststart",
            str(final_output)
        ], "Final output without overlay", timeout=600)
        
    if not overlay_success:
        logger.error("Premium telop overlay (or fallback) failed. Aborting clean rebuild.")
        return None
    
    if final_output.exists():
        size_mb = final_output.stat().st_size / 1024 / 1024
        duration_str = "N/A"
        try:
            check_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", 
                         "-of", "default=noprint_wrappers=1:nokey=1", str(final_output)]
            result = subprocess.run(check_cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and result.stdout.strip():
                duration_sec = float(result.stdout.strip())
                duration_min = int(duration_sec // 60)
                duration_sec_remaining = int(duration_sec % 60)
                duration_str = f"{duration_min}:{duration_sec_remaining:02d}"
        except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError, ValueError) as e:
            logger.warning(f"Failed to retrieve video duration using ffprobe: {e}")
        
        print("\n" + "="*70)
        print("🎉 CLEAN REBUILD COMPLETE!")
        print("="*70)
        print(f"   File: {final_output}")
        print(f"   Size: {size_mb:.1f} MB")
        print(f"   Duration: {duration_str}")
        
        # === 憲法 9.1: 最終プレビュー + HTMLレポート ===
        try:
            preview.snapshot_step("final_output", s01_raw, str(final_output), num_samples=5)
            generator = PreviewReportGenerator()
            report_path = generator.generate_from_session_dir(str(preview.output_dir))
            print(f"   Report: {report_path}")
        except Exception as e:
            logger.exception("Final progressive preview or report generation failed")
            print(f"   ⚠️ Preview report failed: {e}")
        
        return str(final_output)
    else:
        print("\n❌ Final output not created")
        return None

if __name__ == "__main__":
    start = time.time()
    result = clean_rebuild()
    elapsed = time.time() - start
    
    print(f"\nTotal time: {elapsed / 60:.1f} minutes")
    if result:
        print(f"\n🚀 {result}")
    else:
        print("\n❌ Failed")
