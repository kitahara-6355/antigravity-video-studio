"""
run_backend_tests.py - バックエンドテスト実行ツール (Kitchen)

pytestを実行し、テスト結果を構造化されたJSONとして出力する。

Usage:
    python tools/run_backend_tests.py --verbose

Output (JSON):
    {
        "status": "success",
        "total": 42,
        "passed": 42,
        "failed": 0,
        "errors": [],
        "duration_ms": 5200
    }
"""
import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(description="バックエンドテスト実行ツール")
    parser.add_argument("--verbose", action="store_true", help="詳細出力")
    args = parser.parse_args()

    # TODO: subprocess.run(['python', '-m', 'pytest', ...]) でテスト実行し結果をパース
    result = {
        "status": "not_implemented",
        "message": "Stub: Would run pytest and return structured results",
        "total": None,
        "passed": None,
        "failed": None,
        "errors": [],
        "duration_ms": None,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
