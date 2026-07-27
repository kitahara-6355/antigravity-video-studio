"""
Phase 1: 本番動画処理パイプライン
自己監視・自己修復・進捗報告機能付き
"""
import subprocess
import os
from pathlib import Path
import ctypes
# ctypes.wintypes は Windows 専用。Linux（CI）では import 自体が失敗するため保護する
try:
    from ctypes import wintypes
except (ImportError, ValueError):
    wintypes = None
import time
import json
from datetime import datetime

# ショートパス変換（Phase 0からコピー）
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

def run_ffmpeg_with_retry(cmd, description, max_retries=3, timeout_sec=300):
    for attempt in range(max_retries):
        try:
            print(f"\n[{description}] Attempt {attempt + 1}/{max_retries}")
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout_sec,
                encoding='utf-8', errors='ignore'
            )
            if result.returncode == 0:
                print(f"✅ Success: {description}")
                return (True, None, None)
            else:
                error_msg = result.stderr[-200:] if result.stderr else "Unknown error"
                print(f"⚠️ Failed: {error_msg[:100]}")
                if attempt < max_retries - 1:
                    time.sleep(2)
        except subprocess.TimeoutExpired:
            print(f"⏱️ Timeout after {timeout_sec}s")
        except (subprocess.SubprocessError, OSError, ValueError) as e:
            print(f"❌ Subprocess or OS error during ffmpeg execution: {e.__class__.__name__}: {e}")
    return (False, None, f"Failed after {max_retries} attempts")

def process_chunk(input_path, output_path, start_sec, duration_sec, description):
    """5分チャンクを処理"""
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_sec),
        "-t", str(duration_sec),
        "-i", input_path,
        "-vf", "crop=1152:720:26:0,scale=1280:720",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        str(output_path)
    ]
    success, _, error = run_ffmpeg_with_retry(
        cmd, description, max_retries=3, timeout_sec=180
    )
    return success

def concat_videos(input_files, output_file):
    """Concat Demuxerで無劣化結合"""
    concat_list = output_file.parent / "concat_list.txt"
    with open(concat_list, "w", encoding="utf-8") as f:
        for inp in input_files:
            path = str(inp.absolute()).replace("\\", "/")
            f.write(f"file '{path}'\n")
    
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy",
        str(output_file)
    ]
    success, _, error = run_ffmpeg_with_retry(
        cmd, "Concat videos", max_retries=2, timeout_sec=60
    )
    return success

def phase1_full_processing():
    print("="*70)
    print("Phase 1: Full Video Processing")
    print(f"Start time: {datetime.now().strftime('%H:%M:%S')}")
    print("="*70)
    
    base_dir = Path(r"C:\Users\PC_User\Desktop\script\video-automation")
    raw_dir = base_dir / "raw_videos" / "AI Studio アップロード用動画"
    output_dir = base_dir / "backend" / "temp" / "phase1_final"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    results = {
        "scene01_chunks": [],
        "scene02": False,
        "scene04": False,
        "final_concat": False
    }
    
    # ========================================
    # シーン01: 5分×6チャンク
    # ========================================
    print("\n" + "="*70)
    print("Processing Scene 01 (30 min → 6 chunks × 5 min)")
    print("="*70)
    
    input_01 = raw_dir / "シーン01_前編.mp4"
    short_01 = get_short_path(str(input_01))
    
    chunks_01 = []
    for i in range(6):
        chunk_file = output_dir / f"scene01_chunk{i+1}.mp4"
        
        # 既存ファイルがあればスキップ
        if chunk_file.exists() and chunk_file.stat().st_size > 1000000:
            print(f"\n✅ Chunk {i+1}/6 already exists ({chunk_file.stat().st_size / 1024 / 1024:.1f} MB)")
            chunks_01.append(chunk_file)
            results["scene01_chunks"].append(True)
            continue
        
        start = i * 300
        print(f"\n--- Chunk {i+1}/6 ({start//60}:00 - {(start+300)//60}:00) ---")
        
        success = process_chunk(
            short_01, chunk_file,
            start, 300,
            f"Scene01 Chunk {i+1}/6"
        )
        
        if success and chunk_file.exists():
            size_mb = chunk_file.stat().st_size / 1024 / 1024
            print(f"✅ Chunk {i+1}/6: {size_mb:.1f} MB")
            chunks_01.append(chunk_file)
            results["scene01_chunks"].append(True)
        else:
            print(f"❌ Chunk {i+1}/6 failed - skipping")
            results["scene01_chunks"].append(False)
    
    # シーン01結合
    if len(chunks_01) >= 5:  # 最低5チャンクあれば結合
        scene01_final = output_dir / "scene01_final.mp4"
        print("\n--- Concatenating Scene 01 chunks ---")
        if concat_videos(chunks_01, scene01_final):
            print(f"✅ Scene 01 final: {scene01_final.stat().st_size / 1024 / 1024:.1f} MB")
        else:
            print("❌ Scene 01 concatenation failed")
    
    # ========================================
    # シーン02: 54秒（分割不要）
    # ========================================
    print("\n" + "="*70)
    print("Processing Scene 02 (54 sec)")
    print("="*70)
    
    input_02 = raw_dir / "シーン02_ゲスト書道.mp4"
    short_02 = get_short_path(str(input_02))
    scene02_final = output_dir / "scene02_final.mp4"
    
    cmd_02 = [
        "ffmpeg", "-y", "-i", short_02,
        "-vf", "crop=1920:960:0:60,scale=1280:720",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        str(scene02_final)
    ]
    
    success, _, _ = run_ffmpeg_with_retry(cmd_02, "Scene 02", timeout_sec=120)
    results["scene02"] = success
    
    # ========================================
    # シーン04: 5.5分（分割不要）
    # ========================================
    print("\n" + "="*70)
    print("Processing Scene 04 (5.5 min)")
    print("="*70)
    
    input_04 = raw_dir / "シーン04_後編02.mp4"
    short_04 = get_short_path(str(input_04))
    scene04_final = output_dir / "scene04_final.mp4"
    
    cmd_04 = [
        "ffmpeg", "-y", "-i", short_04,
        "-vf", "crop=1136:640:26:40,scale=1280:720",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        str(scene04_final)
    ]
    
    success, _, _ = run_ffmpeg_with_retry(cmd_04, "Scene 04", timeout_sec=180)
    results["scene04"] = success
    
    # ========================================
    # 最終結合
    # ========================================
    print("\n" + "="*70)
    print("Final Concatenation")
    print("="*70)
    
    scene03_existing = base_dir / "backend" / "temp" / "scene03_final" / "scene03_final.mp4"
    
    final_inputs = []
    if (output_dir / "scene01_final.mp4").exists():
        final_inputs.append(output_dir / "scene01_final.mp4")
    if scene02_final.exists():
        final_inputs.append(scene02_final)
    if scene03_existing.exists():
        final_inputs.append(scene03_existing)
    if scene04_final.exists():
        final_inputs.append(scene04_final)
    
    if len(final_inputs) >= 3:
        final_output = base_dir / "soul_narrative_complete.mp4"
        if concat_videos(final_inputs, final_output):
            results["final_concat"] = True
            size_mb = final_output.stat().st_size / 1024 / 1024
            print(f"\n🎉 FINAL VIDEO COMPLETE: {size_mb:.1f} MB")
            print(f"Location: {final_output}")
        else:
            print("\n❌ Final concatenation failed")
    else:
        print(f"\n⚠️ Not enough scenes ({len(final_inputs)}/4)")
    
    # 結果保存
    with open(output_dir / "phase1_results.json", "w") as f:
        json.dump(results, f, indent=2)
    
    print("\n" + "="*70)
    print(f"Phase 1 Complete: {datetime.now().strftime('%H:%M:%S')}")
    print("="*70)
    
    return results

if __name__ == "__main__":
    start_time = time.time()
    results = phase1_full_processing()
    elapsed = time.time() - start_time
    
    print(f"\nTotal elapsed time: {elapsed / 60:.1f} minutes")
    print(f"Scene01 chunks success: {sum(results['scene01_chunks'])}/6")
    print(f"Scene02 success: {results['scene02']}")
    print(f"Scene04 success: {results['scene04']}")
    print(f"Final concat success: {results['final_concat']}")
