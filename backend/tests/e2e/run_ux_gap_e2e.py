"""
run_ux_gap_e2e.py — E2Eテスト自動実行 & UXギャップ分析 & ラチェット連携

このスクリプトは、E2Eテストを実行し、テスト結果からUXストーリーの
検証項目の達成状況（PASS/FAIL）を収集・分析し、ギャップマトリクスを生成、
さらにラチェットスナップショットを永続化します。
"""
import sys
import os
import json
import socket
import time
import subprocess
from pathlib import Path

# パス設定
_current_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.abspath(os.path.join(_current_dir, "..", "..", ".."))
sys.path.insert(0, _repo_root)
sys.path.insert(0, os.path.join(_repo_root, "backend"))

from backend.ux_verification.gap_analyzer import UXGapAnalyzer
from backend.ux_verification.gap_ratchet import GapRatchetValidator

RESULTS_PATH = Path(_repo_root) / "backend" / "tests" / "e2e_results.json"
STORIES_DIR = Path(_repo_root) / "backend" / "ux_verification" / "stories"
SNAPSHOTS_DIR = Path(_repo_root) / "backend" / "ux_verification" / "snapshots"

BACKEND_PORT = 8000
FRONTEND_PORT = 5173


def _is_port_in_use(port: int) -> bool:
    """ポートが使用中か確認"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.settimeout(0.5)
            s.connect(("127.0.0.1", port))
            return True
        except (ConnectionRefusedError, OSError):
            return False


def _wait_for_port(port: int, timeout: int = 60) -> bool:
    """ポートが開くまで待機"""
    start = time.time()
    while time.time() - start < timeout:
        if _is_port_in_use(port):
            return True
        time.sleep(0.5)
    return False


def run_e2e_tests():
    """E2Eテストを順次実行（Sprint 1対象のO-1〜O-3に限定）"""
    print("=== [1/3] E2Eテスト実行中... ===", flush=True)
    
    # 既存のe2e_results.jsonをクリア
    if RESULTS_PATH.exists():
        try:
            RESULTS_PATH.unlink()
        except OSError:
            pass

    # テストファイルを検索（O-1〜O-3ストーリーに限定）
    target_names = ["test_e2e_m36_o1_material.py", "test_e2e_m36_o2_transcription.py", "test_e2e_m36_o3_proofreading.py"]
    test_files = [
        Path(_repo_root) / "backend" / "tests" / "e2e" / name
        for name in target_names
    ]
    
    # ファイル存在確認
    test_files = [p for p in test_files if p.exists()]
    
    if not test_files:
        print("対象のE2Eテストファイルが見つかりません。", flush=True)
        return False
        
    print(f"検出されたE2Eテストファイル (O-1〜O-3限定): {len(test_files)}件", flush=True)
    for p in test_files:
        print(f"  - {p.name}", flush=True)
    
    # サーバーの外部起動
    backend_proc = None
    frontend_proc = None
    
    # バックエンド起動
    if not _is_port_in_use(BACKEND_PORT):
        print(f"バックエンドサーバーをポート {BACKEND_PORT} で起動します...", flush=True)
        backend_dir = Path(_repo_root) / "backend"
        backend_proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(BACKEND_PORT)],
            cwd=str(backend_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )
        if not _wait_for_port(BACKEND_PORT):
            print("バックエンドサーバーの起動に失敗しました。", flush=True)
            if backend_proc:
                backend_proc.terminate()
            return False
        print("バックエンドサーバーが正常に起動しました。", flush=True)
    else:
        print(f"バックエンドサーバーは既に稼働しています (ポート {BACKEND_PORT})。", flush=True)

    # フロントエンド起動
    if not _is_port_in_use(FRONTEND_PORT):
        print(f"フロントエンドサーバーをポート {FRONTEND_PORT} で起動します...", flush=True)
        frontend_dir = Path(_repo_root) / "frontend"
        frontend_proc = subprocess.Popen(
            ["npm", "run", "dev", "--", "--port", str(FRONTEND_PORT), "--host", "127.0.0.1"],
            cwd=str(frontend_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=True,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )
        if not _wait_for_port(FRONTEND_PORT):
            print("フロントエンドサーバーの起動に失敗しました。", flush=True)
            if frontend_proc:
                frontend_proc.terminate()
            if backend_proc:
                backend_proc.terminate()
            return False
        print("フロントエンドサーバーが正常に起動しました。", flush=True)
    else:
        print(f"フロントエンドサーバーは既に稼働しています (ポート {FRONTEND_PORT})。", flush=True)

    # 環境変数の設定
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{_repo_root};{os.path.join(_repo_root, 'backend')}"
    env["PYTHONUNBUFFERED"] = "1"

    # テストファイルを順次実行（リアルタイム出力）
    success_count = 0
    for idx, test_file in enumerate(test_files, 1):
        print(f"\n[{idx}/{len(test_files)}] テスト実行開始: {test_file.name}", flush=True)
        cmd = [sys.executable, "-m", "pytest", str(test_file), "--timeout=300", "-v"]
        
        # リアルタイム表示のため stdout/stderr に sys.stdout/sys.stderr をバイパス
        proc = subprocess.run(cmd, env=env, stdout=sys.stdout, stderr=sys.stderr)
        if proc.returncode == 0:
            print(f"[{idx}/{len(test_files)}] ✅ PASS: {test_file.name}", flush=True)
            success_count += 1
        else:
            print(f"[{idx}/{len(test_files)}] ❌ FAIL: {test_file.name} (コード: {proc.returncode})", flush=True)

    # クリーンアップ
    print("\nサーバーを停止します...", flush=True)
    if frontend_proc:
        frontend_proc.terminate()
        try:
            frontend_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            frontend_proc.kill()
            
    if backend_proc:
        backend_proc.terminate()
        try:
            backend_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            backend_proc.kill()

    print(f"E2E実行完了: {success_count}/{len(test_files)} ファイル成功", flush=True)
    return RESULTS_PATH.exists()


def analyze_gaps_and_save_snapshot():
    """ギャップ分析を実行しスナップショットを保存"""
    print("\n=== [2/3] UXギャップ分析 & マトリクス生成 ===", flush=True)
    
    if not RESULTS_PATH.exists():
        print("[WARNING] E2Eテスト結果ファイル(e2e_results.json)が見つかりません。", flush=True)
        print("E2Eテストが未実行か、フックによる出力に失敗しました。未検証状態として分析します。", flush=True)
        e2e_results = None
    else:
        try:
            e2e_results = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
            print(f"E2Eテスト結果をロード完了。", flush=True)
        except Exception as e:
            print(f"結果ファイルのパース失敗: {e}", flush=True)
            e2e_results = None

    analyzer = UXGapAnalyzer(STORIES_DIR)
    report = analyzer.analyze(e2e_results)
    
    # マトリクスの出力
    matrix = analyzer.generate_gap_matrix()
    matrix_path = Path(_repo_root) / "backend" / "ux_verification" / "gap_matrix.md"
    matrix_path.write_text(matrix, encoding="utf-8")
    print(f"ギャップマトリクスを生成し保存しました: {matrix_path}", flush=True)

    # レポート表示
    print(f"分析サマリ: {report.pass_count} PASS / {report.fail_count} FAIL / {report.skip_count} SKIP", flush=True)
    print(f"PASS率: {report.pass_rate}%", flush=True)

    print("\n=== [3/3] ラチェットスナップショット保存 ===", flush=True)
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    
    # バージョン番号の決定
    existing_snapshots = sorted(SNAPSHOTS_DIR.glob("v*.json"))
    next_ver = len(existing_snapshots)
    snapshot_path = SNAPSHOTS_DIR / f"v{next_ver}_baseline.json"
    if next_ver == 0:
        snapshot_path = SNAPSHOTS_DIR / "v0_baseline.json"

    validator = GapRatchetValidator()
    validator.save_snapshot(report, snapshot_path)
    print(f"ラチェットスナップショットを保存しました: {snapshot_path}", flush=True)

    # 前回のスナップショットがあれば非退行検証を行う
    if next_ver > 0:
        prev_path = SNAPSHOTS_DIR / f"v{next_ver-1}_baseline.json"
        if prev_path.exists():
            print(f"前回スナップショット {prev_path.name} との比較検証を行います。", flush=True)
            try:
                prev_report = validator.load_snapshot(prev_path)
                result = validator.validate(prev_report, report)
                if result.valid:
                    print("✅ ラチェット検証合格: 退行は検出されませんでした。", flush=True)
                else:
                    print("❌ 警告: ラチェット検証違反（退行）を検出しました:", flush=True)
                    for v in result.violations:
                        print(f"  - {v.message}", flush=True)
            except Exception as e:
                print(f"ラチェット検証のロード中にエラー: {e}", flush=True)

    print("\n=== 完了 ===", flush=True)


if __name__ == "__main__":
    # E2Eテストを実行
    tests_run_ok = run_e2e_tests()
    # ギャップ分析とスナップショット保存
    analyze_gaps_and_save_snapshot()
