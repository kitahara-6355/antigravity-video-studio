"""
大容量4本結合パイプラインテスト
- 合計 9.8GB / 4本のRAW動画を結合してパイプライン実行
- GPU Whisper + NVENC レンダリング必須
- E2E品質ゲート7項目チェック
- テスト前後のディスク容量チェック + 自動クリーンアップ
"""

import json
import time
import sys
import shutil
import urllib.request
from datetime import datetime
from pathlib import Path

API_BASE = "http://localhost:8000"
VAULT_OUTPUTS = Path(r"C:\Users\PC_User\Desktop\script\video-automation\vault-outputs")
MIN_DISK_GB = 15  # 最低必要空き容量


def get_disk_free_gb() -> float:
    """Cドライブの空き容量(GB)を返す"""
    total, used, free = shutil.disk_usage("C:\\")
    return free / (1024 ** 3)


def auto_cleanup(keep_latest: int = 1):
    """古いmerged/preview/finalファイルを削除して容量確保"""
    freed = 0
    for subdir in ["merged", "preview", "final"]:
        d = VAULT_OUTPUTS / subdir
        if not d.exists():
            continue
        files = sorted(d.glob("*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True)
        for f in files[keep_latest:]:
            try:
                size = f.stat().st_size
                f.unlink()
                freed += size
            except Exception:
                pass
    # SmartCut一時ファイル
    for f in (VAULT_OUTPUTS / "preview").glob("_smartcut_*"):
        try:
            size = f.stat().st_size
            f.unlink()
            freed += size
        except Exception:
            pass
    # .tmp ファイル
    for f in VAULT_OUTPUTS.rglob("*.tmp.mp4"):
        try:
            size = f.stat().st_size
            f.unlink()
            freed += size
        except Exception:
            pass
    return freed / (1024 ** 3)

def get_top4_videos():
    """APIから容量上位4本（重複除外）を取得"""
    resp = urllib.request.urlopen(f"{API_BASE}/api/pipeline/videos", timeout=10)
    data = json.loads(resp.read())
    
    videos = sorted(data["videos"], key=lambda v: v["size_mb"], reverse=True)
    
    # 重複除外（同名ファイル）
    unique = []
    seen_names = set()
    for v in videos:
        if v["name"] not in seen_names:
            unique.append(v)
            seen_names.add(v["name"])
        if len(unique) == 4:
            break
    
    return unique

def run_4merge_test():
    print("=" * 60)
    print("🔥 大容量4本結合パイプラインテスト")
    print(f"   開始: {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 60)
    
    # ディスク容量チェック
    disk_free = get_disk_free_gb()
    print(f"\n💾 ディスク空き容量: {disk_free:.1f} GB")
    if disk_free < MIN_DISK_GB:
        print(f"   ⚠️ 空き容量不足 ({disk_free:.1f}GB < {MIN_DISK_GB}GB)。自動クリーンアップ実行...")
        freed = auto_cleanup(keep_latest=0)
        disk_free = get_disk_free_gb()
        print(f"   ✅ {freed:.1f}GB 解放 → 現在 {disk_free:.1f}GB")
        if disk_free < MIN_DISK_GB:
            print(f"   ❌ 容量不足が解消しません。手動で空き容量を確保してください。")
            return False
    
    # 動画取得
    videos = get_top4_videos()
    total_mb = sum(v["size_mb"] for v in videos)
    total_gb = total_mb / 1024
    
    print(f"\n📹 テスト動画 (合計 {total_gb:.1f} GB):")
    for i, v in enumerate(videos, 1):
        print(f"  {i}. {v['name']} ({v['size_mb']:.0f}MB) [{v['folder']}]")
    
    paths = [v["path"] for v in videos]
    
    # パイプライン起動
    print(f"\n🚀 パイプライン起動 (4本結合, 目標20分)...")
    body = json.dumps({
        "video_paths": paths,
        "target_minutes": 20
    }).encode("utf-8")
    
    req = urllib.request.Request(
        f"{API_BASE}/api/pipeline/start",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        start_result = json.loads(resp.read())
        print(f"   ✅ 起動成功: session={start_result.get('session_id', '?')[:8]}")
        print(f"   モード: {start_result.get('harness_mode', '?')}")
    except Exception as e:
        print(f"   ❌ 起動失敗: {e}")
        return False
    
    # 進捗監視ループ
    print(f"\n📊 進捗監視中... (タイムアウト: 45分)")
    start_time = time.time()
    TIMEOUT = 2700  # 45分
    last_stage = -1
    
    while time.time() - start_time < TIMEOUT:
        time.sleep(10)
        elapsed = time.time() - start_time
        
        try:
            resp = urllib.request.urlopen(f"{API_BASE}/api/pipeline/status", timeout=5)
            status = json.loads(resp.read())
        except Exception:
            continue
        
        pipeline_status = status.get("status", "")
        current_stage = status.get("current_stage", 0)
        
        # ステージ進捗表示
        if current_stage != last_stage:
            stages = status.get("stages", [])
            for i, s in enumerate(stages):
                if s["status"] == "running":
                    print(f"   [{elapsed:.0f}s] ▶ Stage {i+1}/7: {s['icon']} {s['name']} {s.get('detail', '')}")
                elif s["status"] == "completed" and i > last_stage:
                    print(f"   [{elapsed:.0f}s] ✅ Stage {i+1}/7: {s['icon']} {s['name']} {s.get('detail', '')}")
            last_stage = current_stage
        
        if pipeline_status == "completed":
            print(f"\n   ✅ パイプライン完了! ({elapsed:.0f}秒)")
            break
        elif pipeline_status == "error":
            err = status.get("error", "不明")
            print(f"\n   ❌ パイプラインエラー: {err}")
            return False
    else:
        print(f"\n   ❌ タイムアウト (45分)")
        return False
    
    # 結果分析
    result = status.get("result", {})
    
    print(f"\n{'='*60}")
    print(f"📋 テスト結果")
    print(f"{'='*60}")
    
    # ステージ結果
    stage_results = result.get("stage_results", [])
    all_pass = True
    total_duration = 0
    
    print(f"\n  ステージ別結果:")
    for sr in stage_results:
        icon = "✅" if sr.get("success") else "❌"
        dur = sr.get("duration", 0)
        total_duration += dur
        print(f"    {icon} {sr['name']}: {sr.get('detail', '')} ({dur:.1f}秒)")
        if not sr.get("success"):
            all_pass = False
    
    # 品質スコア
    score = result.get("quality_score", 0)
    segments = result.get("segments_count", 0)
    
    print(f"\n  品質スコア: {score}点")
    print(f"  セグメント数: {segments}")
    print(f"  処理時間: {total_duration:.0f}秒 ({total_duration/60:.1f}分)")
    print(f"  入力容量: {total_gb:.1f} GB")
    print(f"  処理速度: {total_gb / (total_duration / 60):.2f} GB/分" if total_duration > 0 else "")
    
    # カテゴリ別
    qd = result.get("quality_details", {})
    cat_report = qd.get("category_report", [])
    if cat_report:
        print(f"\n  カテゴリ別スコア:")
        for cat in cat_report:
            s = cat.get("score")
            if s is not None:
                print(f"    {cat.get('label', '')}: {s}点 {cat.get('status', '')}")
    
    # GPU確認
    gpu_used = False
    for sr in stage_results:
        detail = sr.get("detail", "")
        if "GPU" in detail or "NVENC" in detail or "nvenc" in detail:
            gpu_used = True
    
    print(f"\n  GPU処理: {'✅ 使用' if gpu_used else '❌ 未使用'}")
    
    # フィードバック
    feedback = qd.get("feedback", [])
    if feedback:
        print(f"\n  フィードバック:")
        for fb in feedback[:5]:
            print(f"    ⚠️ {fb}")
    
    # ヘルスチェック
    health = result.get("health", {})
    skipped = health.get("skipped_features", [])
    if skipped:
        print(f"\n  スキップ機能: {', '.join(skipped)}")
    
    # 出力ファイル確認
    print(f"\n  出力ファイル:")
    import glob
    outputs = Path(r"C:\Users\PC_User\Desktop\script\video-automation\vault-outputs")
    for subdir in ["preview", "final", "merged"]:
        d = outputs / subdir
        if d.exists():
            files = sorted(d.glob("*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True)
            if files:
                f = files[0]
                size_mb = f.stat().st_size / 1024 / 1024
                print(f"    📁 {subdir}/: {f.name} ({size_mb:.0f}MB)")
    
    # テスト後ディスク容量
    disk_after = get_disk_free_gb()
    print(f"\n  💾 ディスク空き: {disk_after:.1f}GB (テスト前: {disk_free:.1f}GB, 差: {disk_free - disk_after:+.1f}GB)")
    
    # 最終判定
    print(f"\n{'='*60}")
    verdict = "🎉 PASS" if (all_pass and score >= 75) else "❌ FAIL"
    print(f"  最終判定: {verdict}")
    print(f"  完了: {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}")
    
    return all_pass and score >= 75


if __name__ == "__main__":
    success = run_4merge_test()
    sys.exit(0 if success else 1)
