#!/usr/bin/env python3
"""chaos テストを汚染しているファイルを CI(Linux) 上で二分探索する。

## 背景

tests/test_antigravity_pipeline_chaos.py は
  - Linux 単独実行 : 56 passed
  - Linux 全体実行 : 10 failed
となる。Windows では全体実行でも通る。

診断で「Linux でも patch は正常に効く（192 → 0）」「モジュールの二重ロードなし」
「instance は同一」を確認済みなので、プラットフォーム差ではなくテスト間汚染。

汚染源はローカル(Windows)では再現しないため、CI 上で特定する必要がある。

## 方法

pytest.ini の testpaths のうち chaos より前に実行されるファイル群を対象に、
前半／後半で分割しながら「その部分集合 + chaos」を実行し、
chaos が失敗する最小の集合へ絞り込む。

各試行は1プロセスで完結するため、CI 1往復で結論まで到達する。

## 終了コード

診断が目的なので常に 0（CI を止めない）。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VICTIM = "tests/test_antigravity_pipeline_chaos.py"
MAX_ROUNDS = 12


def testpaths_before_victim() -> list[str]:
    """testpaths のうち VICTIM より前に並ぶファイルを返す。"""
    ini = (ROOT / "pytest.ini").read_text(encoding="utf-8")
    entries: list[str] = []
    inside = False
    for line in ini.splitlines():
        if re.match(r"^testpaths\s*=", line):
            inside = True
            continue
        if inside:
            if line.strip() and not line[:1].isspace():
                break
            m = re.match(r"^\s+(\S+\.py)\s*$", line)
            if m:
                entries.append(m.group(1))
    if VICTIM in entries:
        entries = entries[: entries.index(VICTIM)]
    return [e for e in entries if (ROOT / e).is_file()]


def chaos_fails_with(files: list[str]) -> tuple[bool, str]:
    """files + VICTIM を実行し、chaos が失敗したかを返す。"""
    cmd = [sys.executable, "-m", "pytest", *files, VICTIM,
           "-q", "--tb=no", "-p", "no:cacheprovider"]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    out = proc.stdout + proc.stderr
    failed_chaos = bool(re.search(
        r"FAILED tests[/\\]test_antigravity_pipeline_chaos\.py", out))
    summary = ""
    for line in reversed(out.splitlines()):
        if "passed" in line or "failed" in line or "error" in line:
            summary = line.strip()
            break
    return failed_chaos, summary


def main() -> int:
    candidates = testpaths_before_victim()
    print(f"chaos より前に実行される testpaths: {len(candidates)} ファイル")

    fails, summary = chaos_fails_with(candidates)
    print(f"\n[全候補 + chaos] chaos 失敗={fails}  {summary}")
    if not fails:
        print("\n再現しませんでした。汚染源は chaos より後ろのファイル、"
              "または収集順の影響である可能性があります。")
        return 0

    alone_fails, alone_summary = chaos_fails_with([])
    print(f"[chaos 単独]     chaos 失敗={alone_fails}  {alone_summary}")
    if alone_fails:
        print("\n単独でも失敗するため汚染ではありません。環境差として個別に追ってください。")
        return 0

    # 二分探索: chaos を失敗させる最小の前置集合を探す
    lo = candidates
    for rnd in range(1, MAX_ROUNDS + 1):
        if len(lo) <= 1:
            break
        mid = len(lo) // 2
        first, second = lo[:mid], lo[mid:]

        f1, s1 = chaos_fails_with(first)
        print(f"\n[round {rnd}] 前半 {len(first)} 件 → chaos 失敗={f1}  {s1}")
        if f1:
            lo = first
            continue

        f2, s2 = chaos_fails_with(second)
        print(f"[round {rnd}] 後半 {len(second)} 件 → chaos 失敗={f2}  {s2}")
        if f2:
            lo = second
            continue

        print("\n前半・後半のどちらでも再現しませんでした。"
              "複数ファイルの組み合わせで発生する汚染の可能性があります。")
        print("現時点の候補:")
        for f in lo:
            print(f"  {f}")
        return 0

    print("\n" + "=" * 70)
    print("汚染源の候補（これ + chaos で失敗する最小集合）:")
    for f in lo:
        print(f"  ::warning ::{f}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
