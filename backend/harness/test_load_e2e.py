"""
RAW動画 負荷テスト — Harness統合パイプライン E2E
最大負荷: 43分 / 1049MB / 1280x720 30fps の merged 動画

テスト項目:
  1. ヘルスチェック
  2. ディスク容量確認
  3. パイプライン起動（Harness Mode）
  4. 進捗モニタリング（最大10分追跡）
  5. ステージ別タイミング計測
  6. API使用量確認
  7. セッション永続化確認
"""
import json
import time
import urllib.request
import sys
from datetime import datetime

BASE = "http://localhost:8000"
# 最大負荷テスト用: 43分 1049MB merged動画
VIDEO = r"C:\Users\PC_User\Desktop\script\video-automation\vault-outputs\merged\merged_20260405_202804.mp4"
TARGET_MINUTES = 20  # SmartCut目標20分（43分→20分 = 53%カット）

def api(method, path, data=None, timeout=15):
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
        r = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        try:
            return json.loads(body), e.code
        except:
            return {"error": body[:200]}, e.code
    except Exception as e:
        return {"error": str(e)}, 0


def main():
    start_time = time.time()
    print("=" * 70)
    print(f"🔥 RAW動画 負荷テスト — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   Video: 43min / 1049MB / 1280x720 / 30fps")
    print(f"   Target: {TARGET_MINUTES}min (SmartCut 53%カット)")
    print("=" * 70)
    
    results = []
    
    # =========================================================
    # 1. ヘルスチェック
    # =========================================================
    print("\n--- 1. ヘルスチェック ---")
    resp, code = api("GET", "/health")
    if code == 200:
        checks = resp.get("checks", {})
        print(f"  Status: {resp['status']}")
        print(f"  FFmpeg: {checks.get('ffmpeg', {}).get('available', False)}")
        print(f"  GPU:    {checks.get('ffmpeg', {}).get('gpu_nvenc', False)}")
        print(f"  Gemini: {checks.get('gemini', {}).get('key_configured', False)}")
        disk = checks.get("disk", {})
        print(f"  Disk:   {disk.get('free_gb', 0):.1f}GB free")
        results.append(("ヘルスチェック", "PASS"))
    else:
        print(f"  ❌ Health check failed: {code}")
        results.append(("ヘルスチェック", "FAIL"))
        return
    
    # =========================================================
    # 2. ディスク容量チェック（最低3GB必要）
    # =========================================================
    print("\n--- 2. ディスク容量チェック ---")
    free_gb = disk.get("free_gb", 0)
    if free_gb < 3.0:
        print(f"  ❌ ディスク容量不足: {free_gb:.1f}GB (最低3GB必要)")
        results.append(("ディスク容量", "FAIL"))
        return
    print(f"  ✅ {free_gb:.1f}GB 利用可能")
    results.append(("ディスク容量", "PASS"))
    
    # =========================================================
    # 3. パイプライン起動
    # =========================================================
    print("\n--- 3. パイプライン起動 (Harness Mode) ---")
    resp, code = api("POST", "/api/pipeline/start", {
        "video_path": VIDEO,
        "target_minutes": TARGET_MINUTES,
    })
    if code == 200 and resp.get("status") == "started":
        harness = resp.get("harness_mode", "unknown")
        sid = resp.get("session_id", "")
        print(f"  Status:  {resp['status']}")
        print(f"  Harness: {harness}")
        print(f"  Session: {sid[:12]}...")
        results.append(("パイプライン起動", "PASS"))
    else:
        print(f"  ❌ 起動失敗: code={code}, resp={json.dumps(resp, ensure_ascii=False)[:200]}")
        results.append(("パイプライン起動", "FAIL"))
        # idle状態でなく既に走っている可能性
        if "already running" in str(resp) or "running" in str(resp):
            print("  ⚠️ パイプラインが既に実行中です。モニタリングに移行します。")
        else:
            return
    
    # =========================================================
    # 4. 進捗モニタリング（最大10分 = 600秒）
    # =========================================================
    print("\n--- 4. 進捗モニタリング (最大10分) ---")
    stage_timings = {}
    prev_stage = -1
    final_status = None
    monitoring_start = time.time()
    MAX_MONITORING = 600  # 10分
    
    poll_count = 0
    while True:
        elapsed = time.time() - monitoring_start
        if elapsed > MAX_MONITORING:
            print(f"\n  ⏳ {MAX_MONITORING}秒経過 — モニタリング終了")
            break
        
        time.sleep(5)
        poll_count += 1
        resp, code = api("GET", "/api/pipeline/status")
        if code != 200:
            print(f"  ⚠️ Status API error: {code}")
            continue
        
        status = resp.get("status", "")
        stage = resp.get("current_stage", 0)
        stages = resp.get("stages", [])
        
        # ステージ変化検出
        if stage != prev_stage:
            stage_name = stages[stage]["name"] if stage < len(stages) else "完了"
            stage_timings[stage_name] = {
                "start": time.time(),
                "elapsed": elapsed,
            }
            if prev_stage >= 0 and prev_stage < len(stages):
                prev_name = stages[prev_stage]["name"]
                if prev_name in stage_timings:
                    stage_timings[prev_name]["duration"] = time.time() - stage_timings[prev_name]["start"]
            prev_stage = stage
        
        # 進捗表示
        active = [s["name"] for s in stages if s["status"] == "running"]
        completed = [s["name"] for s in stages if s["status"] == "completed"]
        stage_bar = f"{len(completed)}/{len(stages)}"
        
        if poll_count % 6 == 0 or status in ("completed", "error"):  # 30秒ごとに表示
            print(f"  [{elapsed:5.0f}s] status={status} stages={stage_bar} active={active}")
        
        if status in ("completed", "error"):
            final_status = status
            break
    
    if final_status is None:
        final_status = "running"
    
    # =========================================================
    # 5. ステージタイミング結果
    # =========================================================
    print("\n--- 5. ステージタイミング ---")
    for name, timing in stage_timings.items():
        dur = timing.get("duration", 0)
        if dur > 0:
            print(f"  {name}: {dur:.1f}s")
        else:
            print(f"  {name}: 実行中...")
    
    total_elapsed = time.time() - start_time
    print(f"\n  総経過時間: {total_elapsed:.1f}s ({total_elapsed/60:.1f}min)")
    
    # =========================================================
    # 6. API使用量
    # =========================================================
    print("\n--- 6. API使用量 ---")
    resp, code = api("GET", "/api/pipeline/api-usage")
    if code == 200:
        models = resp.get("models", {})
        for model, info in models.items():
            used = info.get("used", 0)
            limit = info.get("limit", 0)
            ratio = info.get("usage_ratio", 0)
            if used > 0:
                print(f"  {model}: {used}/{limit} ({ratio:.1%})")
        results.append(("API使用量", "PASS"))
    else:
        print(f"  ⚠️ {code}: {resp}")
        results.append(("API使用量", "INFO"))
    
    # =========================================================
    # 7. セッション確認
    # =========================================================
    print("\n--- 7. セッション確認 ---")
    resp2, code2 = api("GET", "/api/pipeline/status")
    if code2 == 200:
        sid = resp2.get("session_id", "")
        print(f"  Session: {sid[:12] if sid else 'N/A'}...")
        print(f"  Status:  {resp2.get('status')}")
        print(f"  Error:   {resp2.get('error', 'None')}")
        results.append(("セッション確認", "PASS"))
    
    # =========================================================
    # 最終サマリー
    # =========================================================
    print("\n" + "=" * 70)
    print(f"📊 テスト結果サマリー — {final_status.upper()}")
    print("=" * 70)
    
    for name, result in results:
        icon = "✅" if result == "PASS" else "❌" if result == "FAIL" else "ℹ️"
        print(f"  {icon} {name}: {result}")
    
    print(f"\n  🕐 総テスト時間: {total_elapsed:.1f}s")
    print(f"  📁 対象動画: 43min / 1049MB")
    print(f"  🎯 SmartCut目標: {TARGET_MINUTES}min")
    
    if final_status == "completed":
        print("\n  🎉 パイプライン完走！")
    elif final_status == "running":
        print("\n  ⏳ パイプラインはバックグラウンドで継続中")
        print("  → ブラウザの運用監視パネルで進捗を確認してください")
    elif final_status == "error":
        error = resp2.get("error", "不明") if code2 == 200 else "不明"
        print(f"\n  ⚠️ パイプラインエラー: {error}")
    
    print("=" * 70)


if __name__ == "__main__":
    main()
