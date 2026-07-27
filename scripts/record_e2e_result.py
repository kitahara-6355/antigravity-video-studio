"""
E2E結果の構造化JSON記録 + 差分比較

Phase 1 M1.1 T-011/T-012:
- E2E実行結果をタイムスタンプ付きJSONで保存
- 前回結果との差分比較レポートを生成

使用例:
    python scripts/record_e2e_result.py record --results '{"workers": {"transcribe": "pass"}}'
    python scripts/record_e2e_result.py compare --current e2e_results/e2e_20260420_120000.json
"""

import json
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List, Tuple


# ============================================================
# 定数
# ============================================================

DEFAULT_OUTPUT_DIR = "e2e_results"

WORKER_NAMES = [
    "transcribe",
    "proofread",
    "smartcut",
    "preview",
    "quality_gate",
    "render",
    "youtube_opt",
]


# ============================================================
# E2E結果の記録
# ============================================================

def record_result(
    results: Dict,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    metadata: Optional[Dict] = None,
) -> str:
    """E2E結果をタイムスタンプ付きJSONで保存

    Args:
        results: E2E実行結果。{"workers": {"transcribe": "pass", ...}} 形式
        output_dir: 出力ディレクトリ
        metadata: 追加メタデータ（git hash、環境情報等）

    Returns:
        保存したJSONファイルのパス
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"e2e_{ts}.json"
    filepath = output_path / filename

    record = {
        "timestamp": datetime.now().isoformat(),
        "results": results,
        "summary": _compute_summary(results),
        "metadata": metadata or {},
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)

    print(f"✅ E2E結果保存: {filepath}")
    return str(filepath)


def _compute_summary(results: Dict) -> Dict:
    """結果のサマリーを計算"""
    workers = results.get("workers", {})
    total = len(workers)
    passed = sum(1 for v in workers.values() if v in ("pass", "passed", True))
    failed = sum(1 for v in workers.values() if v in ("fail", "failed", False))
    skipped = total - passed - failed

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "pass_rate": round(passed / max(total, 1) * 100, 1),
    }


# ============================================================
# E2E結果の差分比較
# ============================================================

def compare_results(
    current_path: str,
    previous_path: Optional[str] = None,
    output_dir: str = DEFAULT_OUTPUT_DIR,
) -> Dict:
    """2つのE2E結果JSONを比較し差分レポートを生成

    Args:
        current_path: 現在の結果ファイルパス
        previous_path: 前回の結果ファイルパス（省略時は自動検出）
        output_dir: E2E結果ディレクトリ（自動検出用）

    Returns:
        差分レポート dict
    """
    current = _load_result(current_path)

    if not previous_path:
        previous_path = _find_previous(current_path, output_dir)
    
    if not previous_path:
        return {
            "status": "no_previous",
            "message": "前回の結果ファイルが見つかりません（初回実行）",
            "current_summary": current.get("summary", {}),
        }

    previous = _load_result(previous_path)

    # Worker別の変化
    cur_workers = current.get("results", {}).get("workers", {})
    prev_workers = previous.get("results", {}).get("workers", {})

    improvements = []  # fail → pass
    regressions = []   # pass → fail
    unchanged = []     # 変化なし

    all_workers = set(list(cur_workers.keys()) + list(prev_workers.keys()))
    for worker in sorted(all_workers):
        cur_status = cur_workers.get(worker, "missing")
        prev_status = prev_workers.get(worker, "missing")

        if cur_status == prev_status:
            unchanged.append(worker)
        elif cur_status in ("pass", "passed", True) and prev_status in ("fail", "failed", False):
            improvements.append(worker)
        elif cur_status in ("fail", "failed", False) and prev_status in ("pass", "passed", True):
            regressions.append(worker)

    report = {
        "status": "compared",
        "current_file": current_path,
        "previous_file": previous_path,
        "current_summary": current.get("summary", {}),
        "previous_summary": previous.get("summary", {}),
        "improvements": improvements,
        "regressions": regressions,
        "unchanged": unchanged,
    }

    # レポート表示
    _print_report(report)
    return report


def _load_result(path: str) -> Dict:
    """結果JSONを読み込み"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _find_previous(current_path: str, output_dir: str) -> Optional[str]:
    """現在のファイルの1つ前の結果ファイルを自動検出"""
    result_dir = Path(output_dir)
    if not result_dir.exists():
        return None

    files = sorted(result_dir.glob("e2e_*.json"))
    current_name = Path(current_path).name

    prev_file = None
    for f in files:
        if f.name == current_name:
            break
        prev_file = str(f)

    return prev_file


def _print_report(report: Dict):
    """差分レポートを表示"""
    cur = report["current_summary"]
    prev = report["previous_summary"]

    print("\n📊 E2E差分レポート")
    print(f"  現在: {cur.get('passed', 0)}/{cur.get('total', 0)} PASS ({cur.get('pass_rate', 0)}%)")
    print(f"  前回: {prev.get('passed', 0)}/{prev.get('total', 0)} PASS ({prev.get('pass_rate', 0)}%)")

    delta = cur.get("pass_rate", 0) - prev.get("pass_rate", 0)
    if delta > 0:
        print(f"  変動: +{delta}% 📈")
    elif delta < 0:
        print(f"  変動: {delta}% 📉")
    else:
        print(f"  変動: ±0%")

    if report["improvements"]:
        print(f"\n  ✅ 改善: {', '.join(report['improvements'])}")
    if report["regressions"]:
        print(f"\n  ❌ 後退: {', '.join(report['regressions'])}")


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="E2E結果の記録・比較")
    sub = parser.add_subparsers(dest="command")

    # record
    rec = sub.add_parser("record", help="E2E結果を記録")
    rec.add_argument("--results", required=True, help="JSON形式の結果文字列")
    rec.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)

    # compare
    cmp = sub.add_parser("compare", help="E2E結果を比較")
    cmp.add_argument("--current", required=True, help="現在の結果ファイルパス")
    cmp.add_argument("--previous", help="前回の結果ファイルパス（省略で自動検出）")
    cmp.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)

    args = parser.parse_args()

    if args.command == "record":
        results = json.loads(args.results)
        record_result(results, args.output_dir)
    elif args.command == "compare":
        compare_results(args.current, getattr(args, "previous", None), args.output_dir)
    else:
        parser.print_help()
