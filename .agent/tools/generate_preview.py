"""
generate_preview.py - プレビュー生成ツール (Kitchen)

動画の短いサンプルを抽出し、指定されたエフェクトを適用して
Before/After比較用のプレビュー画像・動画を生成する。

Usage:
    python tools/generate_preview.py --input <source_video> --duration 10 --effect <effect_name>

Output (JSON):
    {
        "status": "success",
        "before_path": "vault-outputs/previews/before_sample.png",
        "after_path": "vault-outputs/previews/after_sample.png",
        "report_path": "vault-outputs/previews/preview_report.html"
    }
"""
import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(description="プレビュー生成ツール")
    parser.add_argument("--input", required=True, help="入力動画のパス")
    parser.add_argument("--duration", type=int, default=10, help="サンプル秒数")
    parser.add_argument("--effect", required=True, help="適用エフェクト名")
    args = parser.parse_args()

    # TODO: FFmpegを用いたサンプル抽出とエフェクト適用を実装
    result = {
        "status": "not_implemented",
        "message": f"Stub: Would generate {args.duration}s preview of '{args.input}' with effect '{args.effect}'",
        "before_path": None,
        "after_path": None,
        "report_path": None,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
