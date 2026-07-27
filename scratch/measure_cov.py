import subprocess
import json
import os
import sys

def main():
    print("Starting coverage measurement...")
    # カバレッジ測定コマンドを実行
    # Windows環境における subprocess 実行の規約、timeout は長めに設定 (300秒)
    cmd = ["pytest", "--cov=backend", "--cov-report=json", "--cov-report=term-missing", "--timeout=300"]
    print(f"Running: {' '.join(cmd)}")
    
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=300, encoding="utf-8", errors="ignore")
        print("Coverage run completed.")
        
        # 標準出力と標準エラーのログ保存
        with open("scratch/pytest_cov_stdout.log", "w", encoding="utf-8") as f:
            f.write(res.stdout)
        with open("scratch/pytest_cov_stderr.log", "w", encoding="utf-8") as f:
            f.write(res.stderr)
            
        print("Stdout saved to scratch/pytest_cov_stdout.log")
        print("Stderr saved to scratch/pytest_cov_stderr.log")
        
        if os.path.exists("coverage.json"):
            print("coverage.json successfully generated.")
            with open("coverage.json", "r", encoding="utf-8") as f:
                cov_data = json.load(f)
            
            # メタデータ表示
            meta = cov_data.get("meta", {})
            totals = cov_data.get("totals", {})
            print(f"Total coverage percent: {totals.get('percent_covered'):.2f}%")
            print(f"Total Statements: {totals.get('num_statements')}")
            print(f"Missing Statements: {totals.get('missing_statements')}")
        else:
            print("Warning: coverage.json was not generated.")
            
    except subprocess.TimeoutExpired:
        print("Error: Coverage measurement timed out (300s).")
    except Exception as e:
        print(f"Error occurred: {e}")

if __name__ == "__main__":
    main()
