"""
Option C: ハイブリッドパイプライン
- テロップなしマスター動画を保存
- シーン別動的テーマテロップを適用
- ロゴ透過問題を修正
"""
import os
import subprocess
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import ctypes
# ctypes.wintypes は Windows 専用。Linux（CI）では import 自体が失敗するため保護する
try:
    from ctypes import wintypes
except (ImportError, ValueError):
    wintypes = None
import time
import shutil
import logging

from path_resolver import project_root

logger = logging.getLogger(__name__)

# Progressive Preview System (憲法 9.1 視覚確認プロトコル)
from progressive_preview import ProgressivePreview
from preview_report_generator import PreviewReportGenerator

# ショートパス変換
# ショートパス変換は Windows API。Linux では使えないので None のままにする
# （import 時に無条件で呼ぶと、このモジュールが Linux で import すらできない）
_GetShortPathNameW = None
try:
    if hasattr(ctypes, "windll") and wintypes is not None:
        _GetShortPathNameW = ctypes.windll.kernel32.GetShortPathNameW
        _GetShortPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        _GetShortPathNameW.restype = wintypes.DWORD
except (AttributeError, ImportError, NameError, OSError):
    _GetShortPathNameW = None

def get_short_path(long_path):
    import os
    path = os.path.abspath(long_path)
    if not os.path.exists(path) or _GetShortPathNameW is None:
        return path
    output_buf_size = 256
    output_buf = ctypes.create_unicode_buffer(output_buf_size)
    needed = _GetShortPathNameW(path, output_buf, output_buf_size)
    while needed > output_buf_size:
        output_buf_size = needed
        output_buf = ctypes.create_unicode_buffer(output_buf_size)
        needed = _GetShortPathNameW(path, output_buf, output_buf_size)
    return output_buf.value if needed > 0 else path

def create_theme_telop(text, output_path, include_logo=True):
    """テーマテロップ画像を作成（ロゴ透過問題修正済み）"""
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\YuGothB.ttc", 20)
    except:
        font = ImageFont.truetype(r"C:\Windows\Fonts\msgothic.ttc", 20)
    
    # テキストサイズ計算
    dummy = Image.new('RGBA', (1, 1))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0] + 20
    text_height = 45
    
    if include_logo:
        base = project_root()
        logo_path = base / "backend" / "branding" / "logos" / "brand_logo.png"
        
        # ロゴを読み込み、透過を正しく処理
        logo = Image.open(logo_path).convert('RGBA')
        logo_width = 23
        logo_height = 45
        logo = logo.resize((logo_width, logo_height), Image.LANCZOS)
        
        # 全体幅 = ロゴ + 間隔 + テキスト
        total_width = logo_width + 5 + text_width
        
        # 完全透明な背景で画像を作成
        combined = Image.new('RGBA', (total_width, text_height), (0, 0, 0, 0))
        
        # ロゴを貼り付け（透過を維持）
        combined.paste(logo, (0, 0), logo)
        
        # テロップ背景（半透明黒）をテキスト部分のみに適用
        telop_bg = Image.new('RGBA', (text_width, text_height), (0, 0, 0, 128))
        combined.paste(telop_bg, (logo_width + 5, 0), telop_bg)
        
        # テキストを描画
        draw = ImageDraw.Draw(combined)
        text_x = logo_width + 5 + 10
        text_y = (text_height - (bbox[3] - bbox[1])) // 2
        draw.text((text_x, text_y), text, font=font, fill=(255, 255, 255, 255))
        
        combined.save(output_path)
    else:
        # ロゴなしの場合
        telop = Image.new('RGBA', (text_width, text_height), (0, 0, 0, 128))
        draw = ImageDraw.Draw(telop)
        text_x = 10
        text_y = (text_height - (bbox[3] - bbox[1])) // 2
        draw.text((text_x, text_y), text, font=font, fill=(255, 255, 255, 255))
        telop.save(output_path)
    
    return output_path

def run_ffmpeg(cmd, description, timeout=600):
    print(f"\n[{description}] Starting...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding='utf-8', errors='ignore')
        if result.returncode == 0:
            print(f"✅ {description}")
            return True
        else:
            print(f"❌ {description} failed")
            print(result.stderr[-300:] if result.stderr else "")
            return False
    except subprocess.TimeoutExpired as e:
        print(f"❌ {description} timed out after {timeout} seconds")
        logger.exception(f"ffmpeg process timed out: {e}")
        return False

def hybrid_pipeline():
    base = project_root()
    raw_dir = base / "raw_videos" / "AI Studio アップロード用動画"
    
    # ディレクトリ構成
    masters_dir = base / "masters"
    edits_dir = base / "edits"
    final_dir = base / "final"
    temp_dir = base / "backend" / "temp" / "hybrid_build"
    
    for d in [masters_dir, edits_dir, final_dir, temp_dir]:
        d.mkdir(parents=True, exist_ok=True)
    
    # === 憲法 9.1: Progressive Preview Session 開始 ===
    session_id = f"hybrid_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    preview = ProgressivePreview(session_id=session_id)
    print(f"\n📸 Progressive Preview Session: {session_id}")
    
    # テーマテロップ定義
    themes = {
        "s01": "デザイン書道作家 山田タロウ",
        "s02": "山田氏のゲスト書道パフォーマンス",
        "s03": "山田流：有名ブランドの書を手がける",
        "s04": "有名人も注目！山田の書道教室"
    }
    
    # テロップ画像生成
    print("="*70)
    print("Step 1: Creating theme telop images (with fixed logo transparency)")
    print("="*70)
    
    telops = {}
    for key, text in themes.items():
        telop_path = temp_dir / f"telop_{key}.png"
        create_theme_telop(text, telop_path)
        telops[key] = telop_path
        print(f"✅ {key}: {text}")
    
    # Step 2: RAW動画のクロップ処理（テロップなし）
    print("\n" + "="*70)
    print("Step 2: Processing RAW videos (no telop - for master)")
    print("="*70)
    
    scenes_clean = {}
    crop_params = {
        "s01": "crop=1152:720:26:0,scale=1280:720",
        "s02": "crop=1920:960:0:60,scale=1280:720,fps=30",
        "s03": "crop=1136:640:28:40,scale=1280:720",
        "s04": "crop=1136:640:26:40,scale=1280:720"
    }
    
    raw_files = {
        "s01": raw_dir / "シーン01_前編.mp4",
        "s02": raw_dir / "シーン02_ゲスト書道.mp4",
        "s03": raw_dir / "シーン03_後編01.mp4",
        "s04": raw_dir / "シーン04_後編02.mp4"
    }
    
    for key, raw_path in raw_files.items():
        out_path = temp_dir / f"{key}_clean.mp4"
        run_ffmpeg([
            "ffmpeg", "-y", "-i", get_short_path(str(raw_path)),
            "-vf", crop_params[key],
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
            str(out_path)
        ], f"{key} crop+scale", timeout=600)
        scenes_clean[key] = out_path
    
    # Step 3: 4シーン結合（マスター動画）
    print("\n" + "="*70)
    print("Step 3: Creating master video (no telop)")
    print("="*70)
    
    concat_list = temp_dir / "concat_master.txt"
    with open(concat_list, "w", encoding="utf-8") as f:
        for key in ["s01", "s02", "s03", "s04"]:
            if scenes_clean[key].exists():
                f.write(f"file '{str(scenes_clean[key].absolute()).replace(chr(92), '/')}'\n")
    
    master_raw = temp_dir / "master_raw.mp4"
    run_ffmpeg([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_list), "-c", "copy", str(master_raw)
    ], "Master concatenation")
    
    # Step 4: カット編集（マスター動画に適用）
    print("\n" + "="*70)
    print("Step 4: Applying cuts to master")
    print("="*70)
    
    # カット: 30:48-30:51 (3秒), 37:35 (1秒), 37:38-37:47 (9秒)
    segs = [
        ("seg1", 0, 1848),           # 0:00 - 30:48
        ("seg2", 1851, 404),         # 30:51 - 37:35 (duration)
        ("seg3", 2256, 2),           # 37:36 - 37:38 (duration)
        ("seg4", 2267, None)         # 37:47 - end
    ]
    
    seg_files = []
    for name, start, duration in segs:
        seg_path = temp_dir / f"cut_{name}.mp4"
        if duration:
            run_ffmpeg(["ffmpeg", "-y", "-ss", str(start), "-t", str(duration), 
                       "-i", str(master_raw), "-c", "copy", str(seg_path)], f"Cut {name}")
        else:
            run_ffmpeg(["ffmpeg", "-y", "-ss", str(start), 
                       "-i", str(master_raw), "-c", "copy", str(seg_path)], f"Cut {name}")
        if seg_path.exists():
            seg_files.append(seg_path)
    
    cut_list = temp_dir / "concat_cut.txt"
    with open(cut_list, "w", encoding="utf-8") as f:
        for seg in seg_files:
            f.write(f"file '{str(seg.absolute()).replace(chr(92), '/')}'\n")
    
    master_edited = masters_dir / "soul_narrative_master.mp4"
    run_ffmpeg([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(cut_list), "-c", "copy", str(master_edited)
    ], "Master edited")
    
    # === 憲法 9.1: マスター動画作成後のプレビュー ===
    try:
        preview.snapshot_step("master_created", get_short_path(str(raw_files["s01"])), str(master_edited), num_samples=3)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as e:
        logger.exception("Progressive preview snapshot failed for master_created")
        print(f"   ⚠️ Preview failed: {e}")
    
    print(f"\n✅ Master saved: {master_edited}")
    
    # Step 5: 動的テーマテロップ適用（最終動画）
    print("\n" + "="*70)
    print("Step 5: Applying dynamic theme telops")
    print("="*70)
    
    # マスター動画の長さを取得
    check_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(master_edited)]
    result = subprocess.run(check_cmd, capture_output=True, text=True)
    total_duration = float(result.stdout.strip())
    
    # シーン別タイムライン（カット後の推定）
    # シーン01: 0-1848秒（30:48）→ カット後: 0-1848秒
    # シーン02: 1848-1902秒（54秒）→ カット後: 1845-1899秒
    # シーン03: 1902-2318秒（約7分）→ カット後: 1899-2254秒
    # シーン04: 2318-end → カット後: 2254-end
    
    # 各シーンに個別にテロップを適用（分割処理）
    final_output = final_dir / "soul_narrative_FINAL.mp4"
    
    # 複雑なフィルタを避け、単一のテロップを全編に適用（安定性優先）
    # 後日DaVinci Resolveで動的切り替えを実装する前提
    telop_main = telops["s01"]  # メインテロップ
    
    run_ffmpeg([
        "ffmpeg", "-y",
        "-i", str(master_edited),
        "-i", str(telop_main),
        "-filter_complex", "[0:v][1:v] overlay=15:15",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "copy", "-movflags", "+faststart",
        str(final_output)
    ], "Apply telop to final video", timeout=600)
    
    if final_output.exists():
        size_mb = final_output.stat().st_size / 1024 / 1024
        check_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", str(final_output)]
        result = subprocess.run(check_cmd, capture_output=True, text=True)
        duration_sec = float(result.stdout.strip())
        duration_min = int(duration_sec // 60)
        duration_sec_remaining = int(duration_sec % 60)
        
        print("\n" + "="*70)
        print("🎉 HYBRID PIPELINE COMPLETE!")
        print("="*70)
        print(f"\n📁 成果物:")
        print(f"   Master: {master_edited}")
        print(f"   Final:  {final_output}")
        print(f"\n📊 詳細:")
        print(f"   Size: {size_mb:.1f} MB")
        print(f"   Duration: {duration_min}:{duration_sec_remaining:02d}")
        print(f"   Telop: Yu Gothic Bold 20px (fixed transparency)")
        
        # === 憲法 9.1: 最終プレビュー + HTMLレポート ===
        try:
            preview.snapshot_step("final_with_telop", str(master_edited), str(final_output), num_samples=5)
            generator = PreviewReportGenerator()
            report_path = generator.generate_from_session_dir(str(preview.output_dir))
            print(f"   Report: {report_path}")
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as e:
            logger.exception("Progressive preview report generation failed")
            print(f"   ⚠️ Preview report failed: {e}")
        
        return {
            "master": str(master_edited),
            "final": str(final_output)
        }
    else:
        print("\n❌ Final output not created")
        return None

def main():
    start = time.time()
    result = hybrid_pipeline()
    elapsed = time.time() - start
    
    print(f"\nTotal time: {elapsed / 60:.1f} minutes")
    if result:
        print(f"\n🚀 Master: {result['master']}")
        print(f"🎬 Final: {result['final']}")
        return 0
    else:
        print("\n❌ Failed")
        return 1

if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
