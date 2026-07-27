"""
Phase 2: 10回連続パイプライン成功テスト

各実行で:
1. パイプライン起動
2. 完了まで待機
3. 7項目判定基準チェック
4. 結果記録

全10回合格 = Phase 2 完了
"""

import sys
import time
import requests
import os
from datetime import datetime

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
VIDEO_PATH = os.environ.get(
    "TEST_VIDEO_PATH",
    r"C:\Users\PC_User\Desktop\script\vault-assets\raw_videos\2025-09_Recording\2025-09-22_15-30-47.mp4"
)
MAX_WAIT = 180  # 最大待機秒数
POLL_INTERVAL = 5  # ポーリング間隔

# phase2_validator.py の check 関数を直接使用
from phase2_validator import run_checks


def wait_for_idle():
    """パイプラインがidle状態になるまで待機"""
    for _ in range(60):
        try:
            r = requests.get(f"{BASE_URL}/api/pipeline/status", timeout=5)
            status = r.json().get("status", "")
            if status in ("idle", "completed", "error"):
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def start_pipeline():
    """パイプラインを起動"""
    body = {
        "video_path": VIDEO_PATH,
        "video_paths": [],
        "target_minutes": 1,
    }
    r = requests.post(
        f"{BASE_URL}/api/pipeline/start",
        json=body,
        timeout=10,
    )
    return r.json()


def wait_for_completion():
    """パイプライン完了まで待機"""
    start = time.time()
    while time.time() - start < MAX_WAIT:
        try:
            r = requests.get(f"{BASE_URL}/api/pipeline/status", timeout=5)
            data = r.json()
            status = data.get("status", "")
            if status == "completed":
                return data
            elif status == "error":
                return data
        except Exception:
            pass
        time.sleep(POLL_INTERVAL)
    return None


def _log_run_start(run_num):
    """実行開始ヘッダーを出力"""
    print(f"\n{'='*50}")
    print(f"  Run {run_num}/10 — {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*50}")


def _start_pipeline_safely():
    """パイプラインを起動し結果を返す"""
    try:
        result = start_pipeline()
        session_id = result.get("session_id", "?")[:8]
        print(f"  起動: session={session_id}")
        return True, result
    except Exception as e:
        print(f"  ❌ 起動失敗: {e}")
        return False, f"起動失敗: {e}"


def _evaluate_pipeline_result(data):
    """完了したパイプライン結果の検証とスコア出力"""
    # 7項目チェック
    checks = run_checks(data)
    all_pass = True
    for name, ok, detail in checks:
        icon = "✅" if ok else "❌"
        print(f"  {icon} {name}")
        if not ok:
            all_pass = False

    score = data.get("result", {}).get("quality_score", 0)
    duration = data.get("result", {}).get("duration_seconds", 0)
    print(f"  → スコア: {score}点 / 実行時間: {duration}秒")

    return all_pass, f"score={score}, duration={duration}s"


def run_single_test(run_num):
    """単一テスト実行"""
    _log_run_start(run_num)

    # 起動
    success, result_or_err = _start_pipeline_safely()
    if not success:
        return False, result_or_err

    # 完了待機
    data = wait_for_completion()
    if data is None:
        print(f"  ❌ タイムアウト ({MAX_WAIT}秒)")
        return False, "タイムアウト"

    if data.get("status") == "error":
        error = data.get("error", "不明")
        print(f"  ❌ エラー: {error}")
        return False, f"エラー: {error}"

    # 検証評価
    return _evaluate_pipeline_result(data)


def _check_backend_online():
    """バックエンドがオンラインか確認"""
    try:
        requests.get(f"{BASE_URL}/api/status", timeout=5)
        print(f"  バックエンド: UP")
        return True
    except Exception:
        print("  ❌ バックエンドに接続できません")
        return False


def _run_test_loop():
    """10回のテスト実行ループを制御"""
    results = []
    for i in range(1, 11):
        # idle待機
        if not wait_for_idle():
            print(f"  ❌ Run {i}: idle待機タイムアウト")
            results.append((False, "idle待機失敗"))
            continue

        passed, detail = run_single_test(i)
        results.append((passed, detail))

        if not passed:
            print(f"\n⚠️ Run {i} 失敗。続行します...")

        # 次の実行前にクールダウン
        if i < 10:
            time.sleep(3)
    return results


def _print_final_summary(results):
    """最終結果を集計して出力"""
    print(f"\n{'='*50}")
    print("  Phase 2 最終結果")
    print(f"{'='*50}")

    pass_count = sum(1 for p, _ in results if p)
    for i, (passed, detail) in enumerate(results, 1):
        icon = "✅" if passed else "❌"
        print(f"  {icon} Run {i}: {detail}")

    print(f"\n  合格: {pass_count}/10")

    if pass_count == 10:
        print("\n  🎉🎉🎉 Phase 2 完了！10回連続成功達成！🎉🎉🎉")
    else:
        print(f"\n  ⚠️ Phase 2 未達成: {10 - pass_count}回失敗")

    print(f"  完了: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return pass_count == 10


def main():
    print("=" * 50)
    print("  Phase 2: 10回連続パイプライン成功テスト")
    print(f"  開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    # バックエンド確認
    if not _check_backend_online():
        return None

    # テストループ実行
    results = _run_test_loop()

    # 最終結果出力
    return _print_final_summary(results)


if __name__ == "__main__":  # pragma: no cover
    success = main()
    sys.exit(0 if success else 1)
