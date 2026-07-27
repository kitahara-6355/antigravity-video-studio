#!/usr/bin/env python3
"""Ruff 違反数のラチェット（増加を許さない）。

背景:
    2026-07-25 実測で backend/ に 28,987 件の違反がある（うち 27,526 件は
    W293 blank-line-with-whitespace）。一括ゼロ化は非現実的なため、
    既存の UX 検証ラチェット / TDR ラチェットと同じ方式で「増やさない」ことを保証する。

    旧 ci.yml は `|| true` + `continue-on-error: true` でリンタ結果を完全に
    握り潰していたため、違反が増え続けても検知できなかった。

運用:
    ベースラインは .github/ruff-baseline.json。意図的に減らしたら
    `python .github/scripts/ruff_ratchet.py --update` でベースラインを更新して
    コミットする（下げる方向のみ許可）。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / ".github" / "ruff-baseline.json"

TARGET = "backend/"
SELECT = "E,F,W"
IGNORE = "E501,F401,E402"

# 「実バグの疑い」が強く、1件でも増やしたくないルール
CRITICAL_RULES = {"F821", "E722", "F811"}


def collect() -> Counter[str]:
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", TARGET,
         "--select", SELECT, "--ignore", IGNORE, "--output-format", "json"],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    if proc.returncode not in (0, 1):
        print(f"ruff の実行に失敗しました (exit={proc.returncode})")
        print(proc.stderr[:2000])
        sys.exit(2)
    try:
        items = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        print("ruff の JSON 出力を解析できませんでした")
        print(proc.stdout[:2000])
        sys.exit(2)
    return Counter(i.get("code") or "UNKNOWN" for i in items)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true",
                    help="ベースラインを現在値で更新する（増加方向は拒否）")
    args = ap.parse_args()

    current = collect()
    total = sum(current.values())

    if not BASELINE.exists():
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(
            json.dumps({"total": total, "by_rule": dict(sorted(current.items()))},
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        print(f"ベースラインを新規作成しました: 合計 {total} 件")
        return 0

    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    base_total: int = base.get("total", 0)
    base_rules: dict[str, int] = base.get("by_rule", {})

    regressions: list[str] = []
    for rule, count in sorted(current.items()):
        before = base_rules.get(rule, 0)
        if count > before:
            mark = "【重要】" if rule in CRITICAL_RULES else ""
            regressions.append(f"{mark}{rule}: {before} → {count} (+{count - before})")

    print(f"合計: {base_total} → {total} ({total - base_total:+d})")

    if args.update:
        if regressions:
            print("\n違反が増えているためベースラインを更新できません:")
            for r in regressions:
                print(f"  {r}")
            return 1
        BASELINE.write_text(
            json.dumps({"total": total, "by_rule": dict(sorted(current.items()))},
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        print("ベースラインを更新しました")
        return 0

    if regressions:
        print(f"\n🚫 ラチェット違反: {len(regressions)} 種類のルールで違反が増加しました")
        for r in regressions:
            print(f"  ::error ::{r}")
        print("\n増えた違反を解消するか、意図的な変更なら --update でベースラインを更新してください。")
        return 1

    if total < base_total:
        print(f"✅ 違反が {base_total - total} 件減りました。"
              f"--update でベースラインを更新することを推奨します")
    else:
        print("✅ ラチェット維持（違反の増加なし）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
