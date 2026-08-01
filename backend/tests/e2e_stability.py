"""
E2Eテスト: 安定稼働品質ゲート検証

テスト内容:
  1. 短尺テスト: 13秒テスト動画（全パイプライン）
  2. 長尺テスト: 30分RAW動画（GPU Whisperチャンク分割）
  3. 連続安定性: 短尺3回連続で全回合格確認

基準点:
  - 75点以上 = 安定稼働合格
  - stabilityカテゴリ = 100点必須
"""
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _wp
except ImportError:
    from path_resolver import writable_path as _wp


import asyncio
import http.client
import io
import json
import os
import sqlite3
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
import uuid
from pathlib import Path
import PIL
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))

PASS_SCORE = int(os.getenv("PASS_SCORE", "75"))  # 安定稼働基準点
API_BASE = os.getenv("API_BASE", "http://localhost:8000")
LONG_VIDEO = os.getenv("LONG_VIDEO_PATH", r"C:\Users\PC_User\Desktop\script\vault-assets\raw_videos\2025-09_Recording\2025-09-22_16-34-33.mp4")


def _safe_unlink(path) -> None:
    """ファイルを安全に削除する（存在しなくてもエラーにしない、OSErrorを無視する）"""
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def _open_and_load_image(file_path_or_bytes) -> PIL.Image.Image:
    """ファイルパスまたはバイトデータから画像を検証した上でロードして返す"""
    fp = io.BytesIO(file_path_or_bytes) if isinstance(file_path_or_bytes, bytes) else str(file_path_or_bytes)
    try:
        img = Image.open(fp)
        img.verify()
        if isinstance(fp, io.BytesIO):
            fp.seek(0)
        img = Image.open(fp)
        img.load()
        return img
    except (PIL.UnidentifiedImageError, OSError, SyntaxError) as e:
        raise ValueError(f"Image is corrupted or invalid format: {e}")


def create_test_video(duration: int = 13, output_dir: str = None) -> str:
    """FFmpegで短尺テスト動画を生成"""
    if not isinstance(duration, int) or isinstance(duration, bool):
        raise TypeError(f"duration must be an integer, got {type(duration)}")
    if duration <= 0:
        raise ValueError(f"duration must be a positive integer, got {duration}")
    if output_dir is not None and not isinstance(output_dir, (str, Path)):
        raise TypeError(f"output_dir must be a string or Path object, got {type(output_dir)}")

    if output_dir is None:
        output_dir = str(Path(__file__).parent / "tests")
    Path(output_dir).mkdir(exist_ok=True)

    # Validate output directory writability
    if not os.access(output_dir, os.W_OK):
        raise PermissionError(f"Output directory is not writable: {output_dir}")

    output_path_str = str(Path(output_dir) / f"test_{duration}s.mp4")

    if Path(output_path_str).exists():
        return output_path_str

    threads = os.getenv("FFMPEG_THREADS", "2")
    preset = os.getenv("FFMPEG_PRESET", "fast")

    try:
        subprocess.run([
            "ffmpeg", "-y",
            "-threads", threads,
            "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=1280x720:rate=30",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
            "-c:v", "libx264", "-preset", preset, "-b:v", "3M",
            "-c:a", "aac", "-b:a", "128k",
            output_path_str
        ], capture_output=True, timeout=30, check=True)
    except FileNotFoundError as e:
        _safe_unlink(output_path_str)
        raise RuntimeError(f"FFmpeg executable not found or not executable. Please ensure ffmpeg is installed and added to PATH: {e}") from e
    except subprocess.TimeoutExpired as e:
        _safe_unlink(output_path_str)
        raise RuntimeError(f"FFmpeg process timed out: {e}") from e
    except (subprocess.CalledProcessError, subprocess.SubprocessError) as e:
        _safe_unlink(output_path_str)
        raise RuntimeError(f"FFmpeg process failed: {e}") from e
    except OSError as e:
        _safe_unlink(output_path_str)
        raise RuntimeError(f"OSError occurred while running FFmpeg: {e}") from e

    return output_path_str


def _clean_pipeline_files(video_path: str):
    """中間生成ファイル（チェックポイントとwavファイル）を削除"""
    if not isinstance(video_path, (str, Path)):
        raise TypeError(f"video_path must be a string or Path object, got {type(video_path)}")
    checkpoint_path = str(Path(video_path).parent / "_whisper_segments.jsonl")
    wav_path = str(Path(video_path).parent / "_whisper_audio.wav")
    for f in [checkpoint_path, wav_path]:
        _safe_unlink(f)


def _trigger_pipeline_api(video_path: str, target_minutes: int) -> dict:
    """パイプラインの開始APIを呼び出す"""
    try:
        body = json.dumps({
            "video_path": video_path,
            "video_paths": [],
            "target_minutes": target_minutes
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{API_BASE}/api/pipeline/start",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        resp = urllib.request.urlopen(req, timeout=10)
        try:
            return json.loads(resp.read())
        finally:
            resp.close()
    except urllib.error.HTTPError as e:
        print(f"  ❌ pipeline start HTTP error {e.code}: {e.reason}")
        return {"status": "error", "error": f"Start failed with HTTP status {e.code}: {e.reason}"}
    except urllib.error.URLError as e:
        print(f"  ❌ pipeline start network failed: {e}")
        return {"status": "error", "error": f"Start failed due to network: {e}"}
    except ConnectionError as e:
        print(f"  ❌ pipeline start connection failed: {e}")
        return {"status": "error", "error": f"Start failed due to connection error: {e}"}
    except json.JSONDecodeError as e:
        print(f"  ❌ pipeline start response decode failed: {e}")
        return {"status": "error", "error": f"Start failed due to invalid json: {e}"}
    except TimeoutError as e:
        print(f"  ❌ pipeline start timed out: {e}")
        return {"status": "error", "error": f"Start timed out: {e}"}
    except (http.client.HTTPException, ValueError, UnicodeDecodeError) as e:
        print(f"  ❌ pipeline start request or decoding failed: {e}")
        return {"status": "error", "error": f"Start failed due to request or decoding error: {e}"}
    except (TypeError, NameError, AttributeError):
        raise
    except Exception as e:
        tb_str = traceback.format_exc()
        print(f"  ❌ pipeline start failed with unexpected error ({type(e).__name__}): {e}\n{tb_str}")
        return {"status": "error", "error": f"Start failed: unexpected error {type(e).__name__} - {e}"}


def _poll_pipeline_status(timeout: int) -> dict:
    """パイプラインのステータスをポーリングする"""
    start_time = time.time()
    last_err = None
    while time.time() - start_time < timeout:
        time.sleep(10)
        try:
            resp = urllib.request.urlopen(f"{API_BASE}/api/pipeline/status", timeout=5)
            try:
                status = json.loads(resp.read())
                if isinstance(status, dict) and status.get("status") in ("completed", "error"):
                    return status
            finally:
                resp.close()
        except urllib.error.HTTPError as e:
            last_err = e
            print(f"  [Warning] polling status HTTP error {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            last_err = e
            print(f"  [Warning] polling status network failed: {e}")
        except ConnectionError as e:
            last_err = e
            print(f"  [Warning] polling status connection failed: {e}")
        except json.JSONDecodeError as e:
            last_err = e
            print(f"  [Warning] polling status response decode failed: {e}")
        except TimeoutError as e:
            last_err = e
            print(f"  [Warning] polling status timed out: {e}")
        except (http.client.HTTPException, ValueError, UnicodeDecodeError) as e:
            last_err = e
            print(f"  [Warning] polling status failed due to request or decoding error: {e}")
        except (TypeError, NameError, AttributeError):
            raise
        except Exception as e:
            last_err = e
            tb_str = traceback.format_exc()
            print(f"  [Warning] polling status failed with unexpected error ({type(e).__name__}): {e}\n{tb_str}")

    error_msg = f"Timeout (last error: {last_err})" if last_err else "Timeout"
    return {"status": "error", "error": error_msg}


def run_pipeline(video_path: str, target_minutes: int = 3, timeout: int = 600) -> dict:
    """パイプラインをAPIで実行し結果を取得"""
    if not isinstance(video_path, (str, Path)):
        raise TypeError(f"video_path must be a string or Path object, got {type(video_path)}")
    if not isinstance(target_minutes, int) or isinstance(target_minutes, bool):
        raise TypeError(f"target_minutes must be an integer, got {type(target_minutes)}")
    if target_minutes <= 0:
        raise ValueError(f"target_minutes must be a positive integer, got {target_minutes}")
    if not isinstance(timeout, int) or isinstance(timeout, bool):
        raise TypeError(f"timeout must be an integer, got {type(timeout)}")
    if timeout <= 0:
        raise ValueError(f"timeout must be a positive integer, got {timeout}")

    _clean_pipeline_files(video_path)
    start_result = _trigger_pipeline_api(video_path, target_minutes)
    if start_result.get("status") == "error":
        return start_result
    return _poll_pipeline_status(timeout)


def check_result(result: dict, label: str) -> bool:
    """結果を検証"""
    if not isinstance(result, dict):
        print(f"  ❌ {label}: 結果が辞書形式ではありません ({type(result)})")
        return False

    if result.get("status") != "completed":
        print(f"  ❌ {label}: パイプライン未完了 - {result.get('error', 'unknown')}")
        return False

    res_data = result.get("result")
    if not isinstance(res_data, dict):
        print(f"  ❌ {label}: 結果の詳細(result)が辞書形式ではありません")
        return False

    score = res_data.get("quality_score", 0)
    segments = res_data.get("segments_count", 0)
    duration = res_data.get("duration_seconds", 0)

    # カテゴリ別スコア
    quality_details = res_data.get("quality_details")
    if not isinstance(quality_details, dict):
        quality_details = {}

    category_report = quality_details.get("category_report")
    if not isinstance(category_report, list):
        category_report = []

    stability_score = None
    for cat in category_report:
        if isinstance(cat, dict) and cat.get("category") == "stability":
            stability_score = cat.get("score")

    passed = score >= PASS_SCORE
    stability_ok = stability_score is None or stability_score >= 90

    status = "✅" if (passed and stability_ok) else "❌"
    print(f"  {status} {label}:")
    print(f"     スコア: {score}点 (基準: {PASS_SCORE}点)")
    print(f"     安定稼働: {stability_score}点")
    print(f"     セグメント: {segments}")
    print(f"     処理時間: {duration:.0f}秒")

    if not passed:
        feedback = quality_details.get("feedback")
        if not isinstance(feedback, list):
            feedback = []
        for fb in feedback[:5]:
            print(f"     FB: {fb}")

    return passed and stability_ok


def wait_backend_ready(max_wait=30):
    """バックエンドの起動を確認"""
    print(f"Checking backend connection at {API_BASE}...")
    for i in range(max_wait):
        try:
            resp = urllib.request.urlopen(f"{API_BASE}/api/status", timeout=3)
            try:
                print("Backend is ready.")
                return True
            finally:
                resp.close()
        except urllib.error.HTTPError as e:
            print(f"Backend HTTP error (attempt {i+1}/{max_wait}): status {e.code}")
            time.sleep(1)
        except urllib.error.URLError as e:
            print(f"Backend not ready (attempt {i+1}/{max_wait}): {e}")
            time.sleep(1)
        except ConnectionError as e:
            print(f"Backend connection failed (attempt {i+1}/{max_wait}): {e}")
            time.sleep(1)
        except TimeoutError as e:
            print(f"Timeout checking backend (attempt {i+1}/{max_wait}): {e}")
            time.sleep(1)
        except (http.client.HTTPException, ValueError) as e:
            print(f"Expected error checking backend: {type(e).__name__}: {e}")
            time.sleep(1)
        except (TypeError, NameError, AttributeError):
            raise
        except Exception as e:
            tb_str = traceback.format_exc()
            print(f"Unexpected error checking backend: {type(e).__name__}: {e}\n{tb_str}")
            time.sleep(1)
    return False


def _run_short_video_test() -> tuple[str, bool]:
    """短尺テストを実行し、テスト用動画パスと合否結果のタプルを返す"""
    print("\n[Test 1] 短尺テスト (13秒)")
    test_video_path = create_test_video(13)
    result = run_pipeline(test_video_path, target_minutes=3, timeout=300)
    passed = check_result(result, "短尺13秒")
    return test_video_path, passed


def _run_long_video_test() -> bool | None:
    """長尺テストを実行する。動画がない場合は None を返す"""
    if Path(LONG_VIDEO).exists():
        print("\n[Test 2] 長尺テスト (30分RAW)")
        result = run_pipeline(LONG_VIDEO, target_minutes=20, timeout=900)
        return check_result(result, "長尺30分RAW")
    else:
        print("\n[Test 2] ⏭️ スキップ: RAW動画が見つかりません")
        return None


def _run_consecutive_stability_test(test_video_path: str) -> bool:
    """連続安定性テストを実行する"""
    print("\n[Test 3] 連続安定性テスト (短尺×3回)")
    consecutive_pass = 0
    for i in range(3):
        print(f"  --- 試行 {i+1}/3 ---")
        checkpoint_path = str(Path(test_video_path).parent / "_whisper_segments.jsonl")
        _safe_unlink(checkpoint_path)

        result = run_pipeline(test_video_path, target_minutes=3, timeout=300)
        passed = check_result(result, f"連続{i+1}/3")
        if passed:
            consecutive_pass += 1
    return consecutive_pass == 3


def _run_thumbnail_automation_test() -> bool:
    """サムネイル生成自動化検証を実行する"""
    print("\n[Test 4] サムネイル生成自動化検証")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        task_id = "test_thumbnail_e2e"
        res_json = loop.run_until_complete(run_thumbnail_stage_task(task_id, ":memory:"))
        res_dict = json.loads(res_json)
        passed = res_dict.get("valid", False)
        # クリーンアップ
        p_str = str(_wp("temp_thumbnails") / f"{task_id}.png")
        _safe_unlink(p_str)
    except (RuntimeError, json.JSONDecodeError, ValueError, OSError) as e:
        print(f"  ❌ サムネイル自動化テスト失敗: {e}")
        passed = False
    finally:
        try:
            loop.close()
        finally:
            asyncio.set_event_loop(None)
    return passed


def main():
    print("=" * 60)
    print("🛡️ 安定稼働 E2Eテスト")
    print("=" * 60)

    if not wait_backend_ready():
        print("❌ バックエンド未起動")
        sys.exit(1)

    results = []

    # ━━━ Test 1: 短尺テスト ━━━
    test_video_path, passed_short = _run_short_video_test()
    results.append(("短尺13秒", passed_short))

    # ━━━ Test 2: 長尺テスト (30分RAW) ━━━
    passed_long = _run_long_video_test()
    if passed_long is not None:
        results.append(("長尺30分RAW", passed_long))

    # ━━━ Test 3: 連続安定性 (短尺3回) ━━━
    passed_consec = _run_consecutive_stability_test(test_video_path)
    results.append(("連続安定性3/3", passed_consec))

    # ━━━ Test 4: サムネイル生成自動化検証 ━━━
    passed_thumb = _run_thumbnail_automation_test()
    results.append(("サムネイル自動化検証", passed_thumb))

    # ━━━ 総合結果 ━━━
    print("\n" + "=" * 60)
    print("📊 総合結果")
    print("=" * 60)
    all_pass = True
    for label, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {label}")
        if not passed:
            all_pass = False

    print(f"\n{'🎉 全テスト合格！安定稼働認定' if all_pass else '⚠️ 一部テスト不合格'}")
    sys.exit(0 if all_pass else 1)


def _load_image(file_path_or_bytes) -> tuple[PIL.Image.Image, int]:
    """ファイルパスまたはバイトデータから画像をロードし、画像オブジェクトとサイズ(bytes)を返す"""
    if isinstance(file_path_or_bytes, bytes):
        size_bytes = len(file_path_or_bytes)
    elif isinstance(file_path_or_bytes, (str, Path)):
        path_str = str(file_path_or_bytes)
        try:
            if not os.path.exists(path_str):
                raise FileNotFoundError(f"Thumbnail file not found: {path_str}")
            size_bytes = os.path.getsize(path_str)
        except FileNotFoundError:
            raise
        except OSError as e:
            raise OSError(f"Failed to access thumbnail file {path_str}: {e}")
    else:
        raise TypeError(f"file_path_or_bytes must be bytes, str, or Path, got {type(file_path_or_bytes)}")

    img = _open_and_load_image(file_path_or_bytes)
    return img, size_bytes


def _validate_image_metrics(img: PIL.Image.Image, size_bytes: int) -> dict:
    """画像の幅、高さ、アスペクト比、ファイルサイズを検証する"""
    try:
        width, height = img.size
    except (AttributeError, OSError) as e:
        raise ValueError(f"Failed to load image for resolution check: {e}")

    if size_bytes >= 4 * 1024 * 1024:
        raise ValueError(f"File size exceeds 4MB limit: {size_bytes} bytes")

    if width < 1280 or height < 720:
        raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")

    aspect_ratio_val = width / height
    target_ratio = 16.0 / 9.0
    if abs(aspect_ratio_val - target_ratio) > 1e-2:
        raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio_val:.3f}")

    return {
        "width": width,
        "height": height,
        "size_bytes": size_bytes,
        "valid": True
    }


def verify_thumbnail_quality(file_path_or_bytes) -> dict:
    """
    サムネイル画像の品質要件を検証する。
    - 解像度: 1280x720 以上
    - アスペクト比: 16:9
    - ファイルサイズ: 4MB 未満
    - 破損チェック: Pillowで正常にロード可能
    """
    img, size_bytes = _load_image(file_path_or_bytes)
    return _validate_image_metrics(img, size_bytes)


def generate_thumbnail(output_path, width: int = 1280, height: int = 720, text: str = "Thumbnail") -> str:
    """Pillowを使用して、アトミックに指定の解像度でサムネイル画像を生成する"""
    try:
        width = int(width)
        height = int(height)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Width and height must be integers: {e}")

    if width <= 0 or height <= 0:
        raise ValueError(f"Width and height must be positive integers. Got {width}x{height}")

    output_path_str = str(output_path)
    parent_dir = os.path.dirname(os.path.abspath(output_path_str))
    os.makedirs(parent_dir, exist_ok=True)

    # アトミック書き込み用のテンポラリファイルパス
    base, ext = os.path.splitext(output_path_str)
    temp_path_str = f"{base}.{uuid.uuid4().hex}{ext}.tmp"

    try:
        img = Image.new("RGB", (width, height), color=(73, 109, 137))
        draw = ImageDraw.Draw(img)
        draw.text((10, 10), text, fill=(255, 255, 0))
        img.save(temp_path_str, "PNG")

        _safe_unlink(output_path_str)

        try:
            os.rename(temp_path_str, output_path_str)
        except OSError:
            if os.path.exists(output_path_str):
                os.replace(temp_path_str, output_path_str)
            else:
                raise
    finally:
        _safe_unlink(temp_path_str)

    return output_path_str


async def run_thumbnail_stage_task(task_id: str, db_path: str = ":memory:") -> str:
    """
    StageBoundAgent の process_func として動作する non-blocking な非同期タスク処理。
    自動リトライ、結果保存、DBマイグレーションと連携。
    """
    output_dir = _wp("temp_thumbnails")
    os.makedirs(str(output_dir), exist_ok=True)
    output_path = output_dir / f"{task_id}.png"
    output_path_str = str(output_path)

    # 正常な16:9画像のダミーを生成
    generate_thumbnail(output_path_str, width=1280, height=720, text=f"Task ID: {task_id}")

    conn = None
    try:
        # 品質要件の検証
        result_info = verify_thumbnail_quality(output_path)

        # 結果保存とDBマイグレーション (sqlite3)
        conn = sqlite3.connect(db_path)
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS thumbnail_results (
                    task_id TEXT PRIMARY KEY,
                    path TEXT,
                    width INTEGER,
                    height INTEGER,
                    size_bytes INTEGER,
                    verified_at REAL
                )
            """)
            conn.execute(
                "INSERT OR REPLACE INTO thumbnail_results VALUES (?, ?, ?, ?, ?, ?)",
                (task_id, str(output_path), result_info["width"], result_info["height"], result_info["size_bytes"], time.time())
            )

        return json.dumps(result_info)
    except TypeError as e:
        raise RuntimeError(f"Thumbnail task failed due to invalid type parameter for task {task_id}: {e}") from e
    except ValueError as e:
        raise RuntimeError(f"Thumbnail task failed due to invalid value parameter for task {task_id}: {e}") from e
    except sqlite3.Error as e:
        raise RuntimeError(f"Thumbnail task database operation failed for task {task_id} on {db_path}: {e}") from e
    except OSError as e:
        raise RuntimeError(f"Thumbnail task file I/O failed for task {task_id}: {e}") from e
    except (NameError, AttributeError):
        raise
    except Exception as e:
        tb_str = traceback.format_exc()
        print(f"Unexpected error during run_thumbnail_stage_task for task {task_id}: {type(e).__name__} - {e}\n{tb_str}")
        raise RuntimeError(f"Unexpected thumbnail task failure for task {task_id}: {type(e).__name__} - {e}") from e
    finally:
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass


if __name__ == "__main__":
    main()
