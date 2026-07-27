#!/usr/bin/env python3
"""testpaths 内のテストモジュール名の衝突を検出する。

## なぜ必要か

pytest は `__init__.py` の無いディレクトリのテストファイルをトップレベル
モジュールとして import する。そのため別ディレクトリにある同名ファイルは
同じモジュール名に解決され、収集エラーになる:

    import file mismatch:
      imported module 'test_dispatch_next_batch' has this __file__ attribute: ...
    HINT: remove __pycache__ / .pyc files and/or use a unique basename

厄介なのは「ディレクトリ単独で実行すると通り、全体実行のときだけ壊れる」点。
2026-07-25 の testpaths 拡張作業で2種類の衝突を踏んだ:

  1. tests/test_shared/ と backend/tests/test_shared/
     どちらも __init__.py を持つため、共に `test_shared` パッケージに解決される
  2. tests/test_dispatch_next_batch.py と
     backend/tests/scratch/test_dispatch_next_batch.py
     scratch/ に __init__.py が無く、共に `test_dispatch_next_batch` になる

testpaths を広げるたびに手作業で確認するのは現実的でないため機械化する。

## 使い方

    python scripts/check_test_module_collisions.py          # testpaths を検査
    python scripts/check_test_module_collisions.py --all    # 全テストファイルを検査

終了コード: 0 = 衝突なし / 1 = 衝突あり
"""

from __future__ import annotations

import argparse
import collections
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def module_name(rel_path: str) -> str:
    """pytest が使うモジュール名を推定する。

    ファイルの位置から上へ辿り、__init__.py が途切れた最初の地点が
    パッケージのルート。そこから下がモジュール名になる。
    """
    parts = Path(rel_path).parts
    for i in range(len(parts) - 1, -1, -1):
        pkg_dir = ROOT.joinpath(*parts[:i]) if i else ROOT
        if not (pkg_dir / "__init__.py").exists():
            return ".".join(parts[i:]).removesuffix(".py")
    return ".".join(parts).removesuffix(".py")


def testpaths_entries() -> list[str]:
    """pytest.ini の testpaths からファイル一覧を取り出す。

    コメント行（`    # ...`）が挟まっても途切れないよう、
    testpaths セクション全体を取ってから .py 行だけを拾う。
    """
    ini = (ROOT / "pytest.ini").read_text(encoding="utf-8")
    lines = ini.splitlines()
    entries: list[str] = []
    inside = False
    for line in lines:
        if re.match(r"^testpaths\s*=", line):
            inside = True
            continue
        if inside:
            # インデントが無くなったらセクション終了（空行は読み飛ばす）
            if line.strip() and not line[:1].isspace():
                break
            m = re.match(r"^\s+(\S+\.py)\s*$", line)
            if m:
                entries.append(m.group(1))
    return entries


def all_test_files() -> list[str]:
    out = []
    for base in ("backend/tests", "tests"):
        d = ROOT / base
        if d.is_dir():
            out += [
                str(p.relative_to(ROOT)).replace("\\", "/")
                for p in d.rglob("test_*.py")
            ]
    return sorted(out)


def shadowed_production_packages() -> list[tuple[str, str]]:
    """テストディレクトリが本番モジュール名を隠していないか検査する。

    backend/tests/scratch/ を package 化したところ、トップレベル名 `scratch` が
    そちらに解決され、本番の backend/scratch が import できなくなった
    （from scratch.dispatch_next_batch import ... が ModuleNotFoundError）。
    同じ構造の問題が backend/tests/archives, backend/tests/usage_tracker にもあった。

    テスト側のディレクトリは、本番側に同名ディレクトリがある限り package 化しない。
    """
    problems: list[tuple[str, str]] = []
    backend = ROOT / "backend"
    tests_dir = backend / "tests"
    if not tests_dir.is_dir():
        return problems
    for sub in tests_dir.iterdir():
        if not sub.is_dir() or not (sub / "__init__.py").exists():
            continue
        prod = backend / sub.name
        if prod.is_dir() and prod != sub:
            problems.append((f"backend/tests/{sub.name}", f"backend/{sub.name}"))
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="testpaths ではなく全テストファイルを検査する")
    args = ap.parse_args()

    shadows = shadowed_production_packages()
    if shadows:
        print(f"🚫 テストディレクトリが本番モジュール名を隠しています（{len(shadows)} 件）:")
        for test_dir, prod_dir in shadows:
            print(f"  ::error ::{test_dir} が {prod_dir} を隠します")
        print(f"\n{test_dir}/__init__.py を削除してください。")
        return 1

    entries = all_test_files() if args.all else testpaths_entries()
    if not entries:
        print("検査対象がありません（pytest.ini の testpaths を確認してください）")
        return 1

    groups: dict[str, list[str]] = collections.defaultdict(list)
    for e in entries:
        groups[module_name(e)].append(e)

    collisions = {k: v for k, v in groups.items() if len(v) > 1}

    print(f"検査対象: {len(entries)} ファイル")
    if not collisions:
        print("✅ モジュール名の衝突はありません")
        return 0

    print(f"\n🚫 モジュール名が衝突しています（{len(collisions)} 件）:")
    for name, files in sorted(collisions.items()):
        print(f"  ::error ::{name}")
        for f in files:
            print(f"      {f}")
    print("\nどちらか一方を testpaths から外すか、ファイル名を一意にしてください。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
