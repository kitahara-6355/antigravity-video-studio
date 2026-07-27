"""
T-025: 音声テスト動画(TV-01)でクリーンE2E実行（キャッシュなし）
MASTER v3.6 Phase 1 > M1.2 > Sprint 1.2.3

検証基準: 7 Workerのうち5/7以上 pass
"""
import json
import time
import urllib.request
import sys
import os
from pathlib import Path

BASE = "http://localhost:8000"
TV01_PATH = str(Path(__file__).parent.parent / "test_videos" / "tv01_real_clip.mp4")

WORKERS = [
    "transcribe",
    "proofread",
    "smartcut",
    "preview",
    "quality_gate",
    "render",
    "youtube_opt",
]


def api(method, path, data=None, timeout=15):
    url = f"{BASE}{path}"
    if data:
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method=method,
        )
    else:
        req = urllib.request.Request(url, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read()), e.code
        except Exception:
            return {"error": str(e)}, e.code
    except Exception as e:
        return {"error": str(e)}, 0


def worker_pass_count(stages):
    """ステージリストからWorker別pass/fail/skip数を計算"""
    results = {}
    for s in stages:
        name = s.get("name", "")
        status = s.get("status", "pending")
        results[name] = status
    return results


def main():
    print("=" * 65)
    print("T-025: クリーンE2E — TV-01 音声テスト動画")
    print("=" * 65)
    print(f"  動画: {TV01_PATH}")
    print(f"  検証基準: 5/7 Worker以上 pass")
    print()

    # TV-01が存在するか確認
    if not Path(TV01_PATH).exists():
        print(f"❌ TV-01が見つかりません: {TV01_PATH}")
        sys.exit(1)
    print(f"  ✅ TV-01確認: {Path(TV01_PATH).stat().st_size // 1024} KB")

    # ===== 1. ステータス確認 =====
    print("\n--- Step 1: 初期ステータス確認 ---")
    resp, code = api("GET", "/api/pipeline/status")
    if code != 200:
        print(f"❌ ステータス取得失敗: {code}")
        sys.exit(1)
    current_status = resp.get("status", "")
    print(f"  ステータス: {current_status}")

    # 実行中の場合は停止試行
    if current_status == "running":
        print("  ⚠️ パイプライン実行中 — 停止試行...")
        stop_resp, stop_code = api("POST", "/api/pipeline/stop")
        time.sleep(3)
        resp, code = api("GET", "/api/pipeline/status")
        current_status = resp.get("status", "")
        print(f"  停止後ステータス: {current_status}")

    # ===== 2. パイプライン起動 =====
    print("\n--- Step 2: パイプライン起動 (TV-01) ---")
    resp, code = api("POST", "/api/pipeline/start", {
        "video_path": TV01_PATH,
        "target_minutes": 5,
    })
    if code != 200:
        print(f"❌ 起動失敗: code={code}, resp={resp}")
        sys.exit(1)

    started_status = resp.get("status", "")
    session_id = resp.get("session_id", "")
    harness_mode = resp.get("harness_mode", "unknown")
    print(f"  ステータス: {started_status}")
    print(f"  セッションID: {session_id[:8] if session_id else 'N/A'}...")
    print(f"  ハーネスモード: {harness_mode}")

    if started_status not in ("started", "running"):
        print(f"❌ 起動に失敗しました: {resp}")
        sys.exit(1)
    print("  ✅ パイプライン起動成功")

    # ===== 3. 進捗モニタリング (最大10分) =====
    print("\n--- Step 3: 進捗モニタリング (最大600秒) ---")
    max_wait = 600
    poll_interval = 10
    elapsed = 0
    final_status = None
    final_resp = {}

    last_stage = -1
    while elapsed < max_wait:
        time.sleep(poll_interval)
        elapsed += poll_interval

        resp, code = api("GET", "/api/pipeline/status", timeout=10)
        if code != 200:
            print(f"  [{elapsed:3d}s] ⚠️ ステータス取得失敗 code={code}")
            continue

        status = resp.get("status", "")
        stage = resp.get("current_stage", 0)
        stages = resp.get("stages", [])
        active = [s.get("name", "?") for s in stages if s.get("status") == "running"]
        completed = [s.get("name", "?") for s in stages if s.get("status") == "done"]

        if stage != last_stage:
            print(f"  [{elapsed:3d}s] status={status} stage={stage}/{len(stages)} active={active}")
            if completed:
                print(f"         完了済: {completed}")
            last_stage = stage

        if status in ("completed", "error", "idle") and elapsed > 10:
            final_status = status
            final_resp = resp
            break

    if final_status is None:
        print(f"  ⏳ {max_wait}秒後もまだ実行中")
        resp, code = api("GET", "/api/pipeline/status")
        final_status = resp.get("status", "timeout")
        final_resp = resp

    # ===== 4. 結果評価 =====
    print(f"\n--- Step 4: 結果評価 ---")
    print(f"  最終ステータス: {final_status}")

    stages = final_resp.get("stages", [])
    worker_results = {}
    passed = 0
    failed = 0
    skipped = 0

    for s in stages:
        name = s.get("name", "?")
        status = s.get("status", "pending")
        detail = s.get("detail", "")
        if status == "done":
            worker_results[name] = "pass"
            passed += 1
            print(f"  ✅ {name}: PASS — {detail[:60]}")
        elif status == "error":
            worker_results[name] = "fail"
            failed += 1
            print(f"  ❌ {name}: FAIL — {detail[:60]}")
        elif status in ("running", "pending"):
            worker_results[name] = "skip"
            skipped += 1
            print(f"  ⏳ {name}: {status.upper()} — {detail[:60]}")

    total_eval = passed + failed + skipped
    print(f"\n  結果: {passed}/{total_eval} pass ({failed} fail, {skipped} skip)")

    # T-025判定基準: 5/7以上
    target = 5
    if passed >= target:
        t025_result = "PASS"
        print(f"\n  🎉 T-025: PASS ({passed}/{total_eval} ≥ {target}/7)")
    elif final_status == "error":
        t025_result = "FAIL"
        error_msg = final_resp.get("error", "")
        print(f"\n  ❌ T-025: FAIL (パイプラインエラー: {error_msg[:100]})")
    else:
        t025_result = "PARTIAL"
        print(f"\n  ⚠️ T-025: PARTIAL ({passed}/{total_eval} pass, タイムアウトまたは実行中)")

    # ===== 5. 結果返却 =====
    return {
        "t025_result": t025_result,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "total": total_eval,
        "final_status": final_status,
        "worker_results": worker_results,
        "session_id": session_id,
    }


if __name__ == "__main__":
    result = main()
    print("\n" + "=" * 65)
    print(f"T-025完了: {result['t025_result']}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
