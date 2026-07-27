"""
E2E Test — API経由パイプライン起動テスト
最小動画ファイルでハーネス統合パイプラインの結合を検証
"""
import json
import time
import urllib.request
import sys

BASE = "http://localhost:8000"
VIDEO = r"C:\Users\PC_User\Desktop\script\vault-assets\raw_videos\2025-09_Recording\2025-09-22_15-30-47.mp4"


def api(method, path, data=None):
    url = f"{BASE}{path}"
    if data:
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"},
            method=method,
        )
    else:
        req = urllib.request.Request(url, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=10)
        return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        return json.loads(e.read()), e.code
    except Exception as e:
        return {"error": str(e)}, 0


def main():
    print("=" * 60)
    print("E2E Test — Harness Pipeline via API")
    print("=" * 60)
    passed = 0
    failed = 0

    # 1. Status check (idle)
    print("\n--- 1. Initial Status ---")
    resp, code = api("GET", "/api/pipeline/status")
    assert code == 200, f"Status code {code}"
    assert resp["status"] == "idle", f"Expected idle, got {resp['status']}"
    print(f"  Status: {resp['status']} ✅")
    passed += 1

    # 2. Start pipeline
    print("\n--- 2. Start Pipeline (Harness Mode) ---")
    resp, code = api("POST", "/api/pipeline/start", {
        "video_path": VIDEO,
        "target_minutes": 5,
    })
    assert code == 200, f"Start failed: code={code}, resp={resp}"
    assert resp["status"] == "started", f"Expected started, got {resp}"
    harness_mode = resp.get("harness_mode", "unknown")
    session_id = resp.get("session_id", "")
    print(f"  Status: {resp['status']}")
    print(f"  Harness mode: {harness_mode}")
    print(f"  Session ID: {session_id[:8]}...")
    assert harness_mode == "enabled", f"Expected harness enabled, got {harness_mode}"
    print("  ✅ Pipeline started in Harness mode")
    passed += 1

    # 3. Status check (running)
    print("\n--- 3. Running Status ---")
    time.sleep(2)
    resp, code = api("GET", "/api/pipeline/status")
    status = resp.get("status", "")
    print(f"  Status: {status}")
    print(f"  Stage: {resp.get('current_stage', 0)}")
    # running or already completed/error is fine for E2E
    assert status in ("running", "completed", "error"), f"Unexpected: {status}"
    print(f"  ✅ Pipeline is {status}")
    passed += 1

    # 4. Wait and check progress (max 30s)
    print("\n--- 4. Progress Check (max 30s) ---")
    final_status = None
    for i in range(15):
        time.sleep(2)
        resp, code = api("GET", "/api/pipeline/status")
        status = resp.get("status", "")
        stage = resp.get("current_stage", 0)
        stages = resp.get("stages", [])
        active = [s["name"] for s in stages if s["status"] == "running"]
        print(f"  [{i*2+2}s] status={status} stage={stage} active={active}")
        if status in ("completed", "error"):
            final_status = status
            break

    if final_status is None:
        print("  ⏳ Pipeline still running after 30s (expected for real video)")
        final_status = "running"

    print(f"  Final status: {final_status}")

    # Any status is acceptable for E2E - we're testing the wiring, not the full pipeline
    if final_status == "completed":
        print("  ✅ Pipeline completed successfully!")
        passed += 1
    elif final_status == "error":
        error = resp.get("error", "")
        print(f"  ❌ Pipeline error: {error[:100]}")
        failed += 1  # エラーは不合格
    else:
        print("  ⏳ Pipeline still running (takes longer for real video)")
        passed += 1

    # 5. API Usage
    print("\n--- 5. API Usage ---")
    resp, code = api("GET", "/api/pipeline/api-usage")
    if code == 200:
        print(f"  Usage: {resp}")
        print("  ✅ API Usage endpoint OK")
        passed += 1
    else:
        print(f"  ⚠️ API Usage: {resp}")
        failed += 1

    # 6. Video list
    print("\n--- 6. Video List ---")
    resp, code = api("GET", "/api/pipeline/videos")
    if code == 200:
        count = resp.get("count", 0)
        print(f"  Videos: {count} files")
        print("  ✅ Video list OK")
        passed += 1
    else:
        failed += 1

    # Summary
    total = passed + failed
    print("\n" + "=" * 60)
    if failed == 0:
        print(f"✅ E2E: ALL {passed}/{total} CHECKS PASSED")
    else:
        print(f"⚠️ E2E: {passed}/{total} passed, {failed} issues")
    print("=" * 60)


if __name__ == "__main__":
    main()
