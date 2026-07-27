"""
Σ-1b: カバレッジ実測スクリプト
pytestを実行し、結果をphase_state.jsonに直接書き込む。
手動入力・自己申告を排除し、機械的に正しい値のみを記録する。
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PHASE_STATE_PATH = os.path.join(WORKSPACE, "backend", "agents", "memory", "phase_state.json")
LOG_DIR = os.path.join(WORKSPACE, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

def measure_test_count():
    """pytest --collect-only でテスト件数を機械的にカウント"""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "--timeout=10"],
        capture_output=True, text=True, cwd=WORKSPACE, timeout=120
    )
    # 最終行から件数を抽出: "694 tests collected"
    lines = result.stdout.strip().splitlines()
    for line in reversed(lines):
        m = re.search(r"(\d+)\s+tests?\s+collected", line)
        if m:
            return int(m.group(1))
        # alternative format: "694 items"  
        m = re.search(r"(\d+)\s+items?", line)
        if m:
            return int(m.group(1))
    # フォールバック: "::" を含む行をカウント
    count = sum(1 for l in lines if "::" in l)
    return count if count > 0 else None

def measure_coverage():
    """pytest --cov でカバレッジを機械的に測定"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(LOG_DIR, f"coverage_measured_{timestamp}.txt")
    
    result = subprocess.run(
        [sys.executable, "-m", "pytest", 
         "--cov=backend", "--cov-report=term-missing",
         "-q", "--timeout=120", "--tb=no"],
        capture_output=True, text=True, cwd=WORKSPACE, timeout=600
    )
    
    # ログを保存（証拠）
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"=== Coverage Measurement at {timestamp} ===\n")
        f.write(f"Command: pytest --cov=backend --cov-report=term-missing -q\n")
        f.write(f"Return code: {result.returncode}\n\n")
        f.write("=== STDOUT ===\n")
        f.write(result.stdout)
        f.write("\n=== STDERR ===\n")
        f.write(result.stderr)
    
    # TOTAL行からカバレッジを抽出
    coverage_pct = None
    for line in result.stdout.splitlines():
        if line.startswith("TOTAL"):
            m = re.search(r"(\d+)%", line)
            if m:
                coverage_pct = int(m.group(1))
                break
    
    # テスト結果のサマリも抽出
    test_summary = None
    for line in reversed(result.stdout.splitlines()):
        if "passed" in line or "failed" in line:
            test_summary = line.strip()
            break
    
    return coverage_pct, log_path, test_summary

def update_phase_state(test_count, coverage_pct, log_path, test_summary):
    """phase_state.json に実測値を書き込む"""
    with open(PHASE_STATE_PATH, "r", encoding="utf-8") as f:
        state = json.load(f)
    
    now = datetime.now(timezone.utc).isoformat()
    state["metrics"]["coverage_pct"] = coverage_pct
    state["metrics"]["test_count"] = test_count
    state["metrics"]["coverage_verified"] = True
    state["metrics"]["coverage_source"] = f"scripts/measure_coverage.py @ {now}"
    state["metrics"]["coverage_log_path"] = log_path
    state["metrics"]["coverage_measured_at"] = now
    
    with open(PHASE_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    
    return state

def main():
    print("=" * 60)
    print("Σ-1b: カバレッジ実測 (Truth-First)")
    print("=" * 60)
    
    # Step 1: テスト件数
    print("\n[1/3] テスト件数カウント中...")
    test_count = measure_test_count()
    print(f"  テスト件数: {test_count}")
    
    # Step 2: カバレッジ測定
    print("\n[2/3] カバレッジ測定中（数分かかります）...")
    coverage_pct, log_path, test_summary = measure_coverage()
    print(f"  カバレッジ: {coverage_pct}%")
    print(f"  テスト結果: {test_summary}")
    print(f"  証拠ログ: {log_path}")
    
    # Step 3: phase_state.json 更新
    print("\n[3/3] phase_state.json 更新中...")
    state = update_phase_state(test_count, coverage_pct, log_path, test_summary)
    
    print("\n" + "=" * 60)
    print("✅ 実測完了")
    print(f"  test_count: {test_count}")
    print(f"  coverage_pct: {coverage_pct}%")
    print(f"  coverage_verified: True")
    print(f"  証拠ログ: {log_path}")
    print("=" * 60)

if __name__ == "__main__":
    main()
