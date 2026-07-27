"""
修正版: 全シーンを統一設定で再エンコード・結合
"""
import subprocess
import os
from pathlib import Path
import time

def run_ffmpeg(cmd, description):
    print(f"\n[{description}] Starting...")
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
    if result.returncode == 0:
        print(f"✅ Success: {description}")
        return True
    else:
        print(f"❌ Failed: {description}")
        print(result.stderr[-500:])
        return False

def fix_and_concat(base_dir=None):
    if base_dir is None:
        env_base = os.environ.get("VIDEO_AUTOMATION_BASE")
        if env_base:
            base = Path(env_base)
        else:
            base = Path(__file__).resolve().parent.parent
    else:
        base = Path(base_dir)
    phase1_dir = base / "backend" / "temp" / "phase1_final"
    fixed_dir = base / "backend" / "temp" / "fixed_unified"
    fixed_dir.mkdir(parents=True, exist_ok=True)
    
    # 統一設定
    TARGET_RES = "1280:720"
    TARGET_FPS = "30"
    PRESET = "veryfast"
    CRF = "23"
    
    print("="*70)
    print("Fixing Video Quality Issues")
    print("="*70)
    
    # シーン01: すでに正しい設定なのでそのまま使用
    scene01_source = phase1_dir / "scene01_final.mp4"
    scene01_fixed = fixed_dir / "scene01_final.mp4"
    
    if not scene01_fixed.exists():
        if not scene01_source.exists():
            print("\n❌ Scene 01 source file not found")
            return None
        print("\n[Scene 01] Copying (already correct)")
        try:
            import shutil
            shutil.copy(scene01_source, scene01_fixed)
        except OSError as e:
            print(f"❌ Failed to copy Scene 01: {e}")
            return None
    
    # シーン02: フレームレート修正（119fps → 30fps）
    scene02_source = phase1_dir / "scene02_final.mp4"
    scene02_fixed = fixed_dir / "scene02_final.mp4"
    
    if not scene02_fixed.exists():
        if not scene02_source.exists():
            print("\n❌ Scene 02 source file not found")
            return None
        cmd_02 = [
            "ffmpeg", "-y", "-i", str(scene02_source),
            "-vf", f"fps={TARGET_FPS},scale={TARGET_RES}",
            "-c:v", "libx264", "-preset", PRESET, "-crf", CRF,
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
            str(scene02_fixed)
        ]
        if not run_ffmpeg(cmd_02, "Scene 02 FPS Fix (119fps → 30fps)"):
            print("❌ Scene 02 processing failed")
            return None
    
    if not scene02_fixed.exists():
        print("❌ Scene 02 fixed file not found after processing")
        return None
    
    # シーン03: 解像度修正（1136x640 → 1280x720）
    scene03_source = base / "backend" / "temp" / "scene03_final" / "scene03_final.mp4"
    scene03_fixed = fixed_dir / "scene03_final.mp4"
    
    if not scene03_fixed.exists():
        if not scene03_source.exists():
            print("\n❌ Scene 03 source file not found")
            return None
        cmd_03 = [
            "ffmpeg", "-y", "-i", str(scene03_source),
            "-vf", f"scale={TARGET_RES}:force_original_aspect_ratio=decrease,pad={TARGET_RES}:(ow-iw)/2:(oh-ih)/2,fps={TARGET_FPS}",
            "-c:v", "libx264", "-preset", PRESET, "-crf", CRF,
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
            str(scene03_fixed)
        ]
        if not run_ffmpeg(cmd_03, "Scene 03 Resolution Fix (1136x640 → 1280x720)"):
            print("❌ Scene 03 processing failed")
            return None

    if not scene03_fixed.exists():
        print("❌ Scene 03 fixed file not found after processing")
        return None
    
    # シーン04: すでに正しい設定なのでそのまま使用
    scene04_source = phase1_dir / "scene04_final.mp4"
    scene04_fixed = fixed_dir / "scene04_final.mp4"
    
    if not scene04_fixed.exists():
        if not scene04_source.exists():
            print("\n❌ Scene 04 source file not found")
            return None
        print("\n[Scene 04] Copying (already correct)")
        try:
            import shutil
            shutil.copy(scene04_source, scene04_fixed)
        except OSError as e:
            print(f"❌ Failed to copy Scene 04: {e}")
            return None

    # 各シーンファイルの存在を最終確認
    for sf in [scene01_fixed, scene02_fixed, scene03_fixed, scene04_fixed]:
        if not sf.exists():
            print(f"❌ Missing expected scene file: {sf}")
            return None
    
    # 結合リスト作成
    concat_list = fixed_dir / "concat_fixed.txt"
    with open(concat_list, "w", encoding="utf-8") as f:
        for scene_file in [scene01_fixed, scene02_fixed, scene03_fixed, scene04_fixed]:
            path = str(scene_file.absolute()).replace("\\", "/")
            f.write(f"file '{path}'\n")
    
    # Concat Demuxerで結合
    final_output = base / "soul_narrative_FIXED.mp4"
    cmd_concat = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy",
        "-movflags", "+faststart",
        str(final_output)
    ]
    
    print("\n" + "="*70)
    print("Final Concatenation")
    print("="*70)
    
    if run_ffmpeg(cmd_concat, "Final Concat"):
        size_mb = final_output.stat().st_size / 1024 / 1024
        print(f"\n🎉 FIXED VIDEO COMPLETE!")
        print(f"   File: {final_output}")
        print(f"   Size: {size_mb:.1f} MB")
        
        # 品質チェック
        check_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
           "-show_entries", "stream=codec_name,width,height,r_frame_rate",
            "-of", "json",
            str(final_output)
        ]
        result = subprocess.run(check_cmd, capture_output=True, text=True)
        print("\nQuality Check:")
        print(result.stdout)
        
        return str(final_output)
    else:
        print("\n❌ Final concatenation failed")
        return None

if __name__ == "__main__":
    start = time.time()
    output_path = fix_and_concat()
    elapsed = time.time() - start
    
    print(f"\nTotal time: {elapsed / 60:.1f} minutes")
    if output_path:
        print(f"✅ SUCCESS: {output_path}")
    else:
        print("❌ FAILED")
