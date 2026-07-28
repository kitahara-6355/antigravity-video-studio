"""
自己監視・自己修復型 動画処理パイプライン
Phase 0: プレフライトチェック
"""
import subprocess
import os
from pathlib import Path
import ctypes
# ctypes.wintypes は Windows 専用。Linux（CI）では import 自体が失敗する
try:
    from ctypes import wintypes
except (ImportError, ValueError):
    wintypes = None
import time
import json

from path_resolver import project_root

# ========================================
# ユーティリティ: ショートパス変換
# ========================================
try:
    if wintypes is None:
        raise AttributeError("wintypes unavailable")
    _GetShortPathNameW = ctypes.windll.kernel32.GetShortPathNameW
    _GetShortPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    _GetShortPathNameW.restype = wintypes.DWORD
except (AttributeError, OSError, NameError) as e:
    _GetShortPathNameW = None

def get_short_path(long_path):
    """Windowsロングパスを8.3形式のショートパスに変換"""
    path = os.path.abspath(long_path)
    if not _GetShortPathNameW:
        return path
    if not os.path.exists(path):
        print(f"Warning: Path not found: {path}")
        return path
    
    output_buf_size = 256
    output_buf = ctypes.create_unicode_buffer(output_buf_size)
    needed = _GetShortPathNameW(path, output_buf, output_buf_size)
    
    while needed > output_buf_size:
        output_buf_size = needed
        output_buf = ctypes.create_unicode_buffer(output_buf_size)
        needed = _GetShortPathNameW(path, output_buf, output_buf_size)
    
    return output_buf.value if needed > 0 else path

# ========================================
# 自動リトライ機能付きFFmpeg実行
# ========================================
def run_ffmpeg_with_retry(cmd, description, max_retries=3, timeout_sec=300):
    """
    FFmpegコマンドを実行し、失敗時に自動リトライ
    
    Returns:
        (success: bool, output_path: str or None, error_msg: str or None)
    """
    for attempt in range(max_retries):
        try:
            print(f"\n[{description}] Attempt {attempt + 1}/{max_retries}")
            print(f"Command: {' '.join(cmd[:5])}...")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                encoding='utf-8',
                errors='ignore'
            )
            
            if result.returncode == 0:
                print(f"✅ Success: {description}")
                return (True, None, None)
            else:
                error_msg = result.stderr[-500:] if result.stderr else "Unknown error"
                print(f"⚠️ Failed (attempt {attempt + 1}): {error_msg[:100]}")
                
                if attempt < max_retries - 1:
                    print("Retrying in 2 seconds...")
                    time.sleep(2)
                    
        except subprocess.TimeoutExpired:
            print(f"⏱️ Timeout after {timeout_sec}s")
            if attempt < max_retries - 1:
                print("Retrying with extended timeout...")
        except (subprocess.SubprocessError, OSError, ValueError, TypeError) as e:
            print(f"❌ Subprocess/OS Error during FFmpeg run: {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
    
    return (False, None, f"Failed after {max_retries} attempts")

# ========================================
# Phase 0: プレフライトチェック - 設定定数
# ========================================
# 環境変数が無いときに使われる既定のルート（path_resolver が算出する）
DEFAULT_FALLBACK_BASE_DIR = str(project_root())
RAW_VIDEOS_SUBDIR = Path("raw_videos") / "AI Studio アップロード用動画"
OUTPUT_SUBDIR = Path("backend") / "temp" / "phase0_check"
INPUT_VIDEO_NAME = "シーン01_前編.mp4"

# プレビュー生成（Test 2）の設定
PREVIEW_START_SEC = 60
PREVIEW_DURATION_SEC = 60
PREVIEW_CROP_SCALE_VF = "crop=1152:720:26:0,scale=1280:720"
PREVIEW_CRF = "28"
PREVIEW_PRESET = "veryfast"
PREVIEW_MIN_FILE_SIZE_BYTE = 100000

# チャンクテスト（Test 3）の設定
CHUNK_START_SEC = 60
CHUNK_DURATION_SEC = 300
CHUNK_MIN_FILE_SIZE_BYTE = 500000

def _resolve_paths():
    """プレフライトチェックで使用するパス（入力動画、出力ディレクトリ）を解決する"""
    # 環境変数（VIDEO_AUTOMATION_BASE_DIR / ANTIGRAVITY_BASE_DIR）と
    # スクリプト位置からの算出を path_resolver に一本化している
    base_dir = project_root()

    raw_dir = base_dir / RAW_VIDEOS_SUBDIR
    output_dir = base_dir / OUTPUT_SUBDIR
    input_video = raw_dir / INPUT_VIDEO_NAME
    
    return input_video, output_dir

def _test_short_path_conversion(input_video):
    """Test 1: ショートパス変換テスト"""
    print("\n[1/3] Testing short path conversion...")
    if not input_video.exists():
        print(f"❌ Input file not found: {input_video}")
        return False, str(input_video)
    
    short_path = get_short_path(str(input_video))
    print(f"Original: {input_video}")
    print(f"Short:    {short_path}")
    
    if os.path.exists(short_path):
        print("✅ Short path conversion successful")
        return True, short_path
    else:
        print("❌ Short path conversion failed")
        return False, short_path

def _test_preview_generation(short_path, output_dir):
    """Test 2: 1分プレビュー生成"""
    print("\n[2/3] Generating 1-minute preview...")
    preview_1min = output_dir / "test_1min.mp4"
    
    cmd_1min = [
        "ffmpeg", "-y",
        "-ss", str(PREVIEW_START_SEC),
        "-t", str(PREVIEW_DURATION_SEC),
        "-i", short_path,
        "-vf", PREVIEW_CROP_SCALE_VF,
        "-c:v", "libx264",
        "-preset", PREVIEW_PRESET,
        "-crf", PREVIEW_CRF,
        "-c:a", "copy",
        str(preview_1min)
    ]
    
    success, _, error = run_ffmpeg_with_retry(
        cmd_1min,
        "1-minute preview",
        max_retries=2,
        timeout_sec=60
    )
    
    if success and preview_1min.exists() and preview_1min.stat().st_size > PREVIEW_MIN_FILE_SIZE_BYTE:
        print(f"✅ 1-min preview: {preview_1min.stat().st_size / 1024 / 1024:.1f} MB")
        return True
    else:
        print("❌ 1-min preview generation failed")
        return False

def _test_chunk_processing(short_path, output_dir):
    """Test 3: 5分チャンクテスト"""
    print("\n[3/3] Testing 5-minute chunk processing...")
    chunk_5min = output_dir / "test_5min.mp4"
    
    cmd_5min = [
        "ffmpeg", "-y",
        "-ss", str(CHUNK_START_SEC),
        "-t", str(CHUNK_DURATION_SEC),
        "-i", short_path,
        "-vf", PREVIEW_CROP_SCALE_VF,
        "-c:v", "libx264",
        "-preset", PREVIEW_PRESET,
        "-crf", PREVIEW_CRF,
        "-c:a", "copy",
        str(chunk_5min)
    ]
    
    success, _, error = run_ffmpeg_with_retry(
        cmd_5min,
        "5-minute chunk",
        max_retries=2,
        timeout_sec=180
    )
    
    if success and chunk_5min.exists() and chunk_5min.stat().st_size > CHUNK_MIN_FILE_SIZE_BYTE:
        print(f"✅ 5-min chunk: {chunk_5min.stat().st_size / 1024 / 1024:.1f} MB")
        return True
    else:
        print("❌ 5-min chunk processing failed")
        return False

def phase0_preflight_check():
    """
    Phase 0: プレフライトチェック
    1分プレビューと5分チャンクテストで安定性を検証
    """
    print("="*70)
    print("Phase 0: Preflight Check")
    print("="*70)
    
    input_video, output_dir = _resolve_paths()
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"❌ Failed to create output directory {output_dir}: {e}")
        return {
            "short_path_test": False,
            "1min_preview": False,
            "5min_chunk": False,
            "overall_success": False
        }
    
    results = {
        "short_path_test": False,
        "1min_preview": False,
        "5min_chunk": False,
        "overall_success": False
    }
    
    # Test 1: ショートパス変換
    short_path_success, short_path = _test_short_path_conversion(input_video)
    results["short_path_test"] = short_path_success
    
    # Test 2: 1分プレビュー生成
    if results["short_path_test"]:
        results["1min_preview"] = _test_preview_generation(short_path, output_dir)
        
    # Test 3: 5分チャンクテスト
    if results["1min_preview"]:
        results["5min_chunk"] = _test_chunk_processing(short_path, output_dir)
        
    # 総合判定
    results["overall_success"] = all([
        results["short_path_test"],
        results["1min_preview"],
        results["5min_chunk"]
    ])
    
    # 結果をJSON保存 (UTF-8明示、例外安全)
    try:
        with open(output_dir / "phase0_results.json", "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
    except (OSError, TypeError) as e:
        print(f"❌ Failed to save preflight results to JSON: {e}")
    
    print("\n" + "="*70)
    if results["overall_success"]:
        print("✅✅✅ Phase 0: ALL TESTS PASSED ✅✅✅")
        print("Ready to proceed to Phase 1 (full processing)")
    else:
        print("❌ Phase 0: SOME TESTS FAILED")
        print("Review the errors above before proceeding")
    print("="*70)
    
    return results

if __name__ == "__main__":
    start_time = time.time()
    results = phase0_preflight_check()
    elapsed = time.time() - start_time
    
    print(f"\nTotal elapsed time: {elapsed:.1f} seconds")
    print(f"Success: {results['overall_success']}")
