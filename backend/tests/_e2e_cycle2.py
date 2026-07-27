"""サイクル2 E2Eテスト: 4本番RAW動画でパイプライン起動→完了まで監視"""
import urllib.request
import urllib.error
import json
import time
import sys

API = "http://localhost:8000"

def wait_for_server(timeout=60):
    """サーバーの起動を待機する"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            urllib.request.urlopen(f"{API}/api/pipeline/status", timeout=3)
            return True
        except (urllib.error.URLError, OSError):
            time.sleep(2)
    return False

def check_dashboard():
    """UX-04修正確認: dashboardが200を返すか"""
    try:
        r = urllib.request.urlopen(f"{API}/api/usage/dashboard", timeout=5)
        data = json.loads(r.read())
        models = len(data.get("models", []))
        print(f"  Dashboard: OK ({models} models)")
        return True
    except (urllib.error.URLError, OSError, json.JSONDecodeError, AttributeError, TypeError) as e:
        print(f"  Dashboard: FAIL ({e})")
        return False

def _build_start_payload(paths, target_minutes=20):
    """パイプライン起動用リクエストのペイロードとリクエストオブジェクトを構築する"""
    start_url = f"{API}/api/pipeline/start"
    payload = {"video_paths": paths, "target_minutes": target_minutes}
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        start_url,
        data=body,
        headers={"Content-Type": "application/json"}
    )
    return req

def start_pipeline():
    """4つの本番RAW動画パスを指定してパイプラインを起動する"""
    paths = [
        r"C:\Users\PC_User\Desktop\script\vault-assets\raw_videos\本番RAW01 対談_山田\シーン01_前編.mp4",
        r"C:\Users\PC_User\Desktop\script\vault-assets\raw_videos\本番RAW01 対談_山田\シーン02_ゲスト書道.mp4",
        r"C:\Users\PC_User\Desktop\script\vault-assets\raw_videos\本番RAW01 対談_山田\シーン03_後編01.mp4",
        r"C:\Users\PC_User\Desktop\script\vault-assets\raw_videos\本番RAW01 対談_山田\シーン04_後編02.mp4",
    ]
    req = _build_start_payload(paths)
    resp = urllib.request.urlopen(req, timeout=15)
    return json.loads(resp.read())

def _format_progress_message(elapsed_seconds, status, completed_count, running_stages):
    """監視中の進捗状況をフォーマットしたメッセージを作成する"""
    message = f"[{elapsed_seconds:>4}s] {status} | {completed_count}/7"
    if running_stages:
        active_stage = running_stages[0]
        detail_text = active_stage.get('detail') or '...'
        message += f" | {active_stage['name']}: {detail_text[:50]}"
    return message

def monitor_pipeline(timeout=1800):
    """パイプラインのステータスを一定間隔でポーリング監視する"""
    start_time = time.time()
    status_url = f"{API}/api/pipeline/status"
    while time.time() - start_time < timeout:
        time.sleep(15)
        elapsed_seconds = int(time.time() - start_time)
        try:
            resp = urllib.request.urlopen(status_url, timeout=10)
            data = json.loads(resp.read())
            status = data["status"]
            stages = data.get("stages", [])
            completed_count = len([s for s in stages if s.get("status") == "completed"])
            running_stages = [s for s in stages if s.get("status") == "running"]
            
            msg = _format_progress_message(elapsed_seconds, status, completed_count, running_stages)
            print(msg, flush=True)
            
            if status in ("completed", "error"):
                return data
        except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError, AttributeError, TypeError) as e:
            print(f"[{elapsed_seconds:>4}s] polling: {e}", flush=True)
    return None

# ===== メイン =====
def main():
    print("=== サイクル2 E2Eテスト ===", flush=True)

    print("\n[1] サーバー起動待機...", flush=True)
    if not wait_for_server():
        print("FAIL: サーバー起動タイムアウト")
        sys.exit(1)
    print("  Backend: OK", flush=True)

    print("\n[2] UX-04確認: Dashboard API...", flush=True)
    check_dashboard()

    print("\n[3] パイプライン起動...", flush=True)
    result = start_pipeline()
    print(f"  Started: {result}", flush=True)

    print("\n[4] パイプライン監視...", flush=True)
    final = monitor_pipeline()

    if final:
        print(f"\n[5] 結果:", flush=True)
        print(json.dumps(final, ensure_ascii=False, indent=2)[:2000], flush=True)
        if final.get("status") == "error":
            sys.exit(1)
    else:
        print("\n[5] タイムアウト", flush=True)
        sys.exit(1)

if __name__ == '__main__':  # pragma: no cover
    main()
