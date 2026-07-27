#!/usr/bin/env python3
"""testpaths を分割して pytest を複数プロセスで実行し、結果とカバレッジを1つにまとめる。

## なぜ必要か

testpaths を 454 ファイル（約10,000テスト）へ広げたところ、CI(Linux) が
**メモリ不足でプロセスごと殺された**（exit 137、全体の 20% 地点）。

    3482 Killed  python -m pytest -q --tb=short --junitxml=... --cov ...

pytest は収集した全テストのレポートを保持し続け、そこにテスト側が確保した
モック・画像・DB 接続などが積み上がる。1プロセスで1万件を走らせるのは
GitHub ランナーのメモリに収まらない。

バッチごとに新しいプロセスで実行すればメモリは都度解放される。
カバレッジは `--cov-append` で積算し、JUnit XML は最後に結合するため、
マージゲートの判定材料は1プロセス実行のときと同じ形で得られる。

## 使い方

    python scripts/run_test_batches.py --batches 4 \
        --junit test-results.xml --coverage coverage.json

終了コード: 0 = 全バッチ成功 / 1 = いずれかのバッチが失敗
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_testpaths() -> list[str]:
    """pytest.ini の testpaths からファイル一覧を取り出す。"""
    entries: list[str] = []
    started = False
    for line in (ROOT / "pytest.ini").read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("testpaths"):
            started = True
            continue
        if not started:
            continue
        if s and not s.startswith(" ") and "=" in s and not s.endswith(".py"):
            break
        if s and not s.startswith("#") and s.endswith(".py"):
            entries.append(s)
    return entries


def split(items: list[str], n: int) -> list[list[str]]:
    """順序を保ったまま n 個に分ける（並び順が結果に影響するため入れ替えない）。"""
    size, rest = divmod(len(items), n)
    out, i = [], 0
    for b in range(n):
        take = size + (1 if b < rest else 0)
        out.append(items[i:i + take])
        i += take
    return [c for c in out if c]


def merge_junit(parts: list[Path], dest: Path) -> tuple[int, int, int]:
    """複数の JUnit XML を1つに結合する。戻り値は (tests, failures, errors)。"""
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite", {"name": "pytest"})
    tests = failures = errors = skipped = 0
    time_total = 0.0

    for p in parts:
        if not p.exists():
            continue
        for ts in ET.parse(p).getroot().iter("testsuite"):
            tests += int(ts.get("tests", 0))
            failures += int(ts.get("failures", 0))
            errors += int(ts.get("errors", 0))
            skipped += int(ts.get("skipped", 0))
            time_total += float(ts.get("time", 0) or 0)
            for tc in ts:
                suite.append(tc)

    suite.set("tests", str(tests))
    suite.set("failures", str(failures))
    suite.set("errors", str(errors))
    suite.set("skipped", str(skipped))
    suite.set("time", f"{time_total:.3f}")
    ET.ElementTree(root).write(dest, encoding="utf-8", xml_declaration=True)
    return tests, failures, errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batches", type=int, default=4)
    ap.add_argument("--junit", default="test-results.xml")
    ap.add_argument("--coverage", default="coverage.json")
    ap.add_argument("--timeout", type=int, default=120)
    args = ap.parse_args()

    files = read_testpaths()
    if not files:
        print("testpaths が読み取れませんでした", file=sys.stderr)
        return 1
    chunks = split(files, args.batches)
    print(f"{len(files)} ファイルを {len(chunks)} バッチに分割して実行します", flush=True)

    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")

    subprocess.run([sys.executable, "-m", "coverage", "erase"], cwd=ROOT, env=env)

    parts: list[Path] = []
    failed_batches: list[int] = []
    for i, chunk in enumerate(chunks, 1):
        part = ROOT / f".junit_batch_{i}.xml"
        parts.append(part)
        cmd = [
            sys.executable, "-m", "pytest", "-q", "--tb=short", "-p", "no:randomly",
            f"--timeout={args.timeout}", "-o", "testpaths=",
            # 1ファイルの収集エラーでバッチ全体（約2,500件）が失われるのを防ぐ。
            # エラー自体は JUnit XML に残るのでマージゲートの判定材料からは漏れない。
            "--continue-on-collection-errors",
            f"--junitxml={part}", "--cov", "--cov-append", "--cov-report=",
            *chunk,
        ]
        print(f"\n=== バッチ {i}/{len(chunks)}（{len(chunk)} ファイル）===", flush=True)
        r = subprocess.run(cmd, cwd=ROOT, env=env)
        if r.returncode != 0:
            failed_batches.append(i)
            print(f"バッチ {i} が失敗しました (exit={r.returncode})", flush=True)

    tests, failures, errors = merge_junit(parts, ROOT / args.junit)
    for p in parts:
        p.unlink(missing_ok=True)

    subprocess.run([sys.executable, "-m", "coverage", "json", "-o", args.coverage],
                   cwd=ROOT, env=env)

    print(f"\n合計: {tests} 件 / 失敗 {failures} / エラー {errors}")
    if failed_batches:
        print(f"失敗したバッチ: {failed_batches}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
