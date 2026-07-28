#!/usr/bin/env python3
"""ローカル絶対パス直書きのラチェット（増加を許さない）。

背景:
    2026-07-28 時点で `C:\\Users\\<user>` 形式の直書きが 401 行残っている
    （着手前は 533 行）。本番コードからは撤去したが、テスト 87 行 /
    `scratch/` 212 行 / 過去記録 99 行 / `archives/` 3 行が残っている。

    直書きされた絶対パスは以下を同時に塞ぐ。

      - GitHub Actions(Ubuntu) での実行 — ランナーに `C:\\Users\\...` は無い
      - 素材の Drive 移行 — 置き場を変えるたびに参照元を個別に直すことになる
      - 別マシンでの開発 — ユーザー名が違うだけで動かない

    集約先は `backend/path_resolver.py`（フォントは `backend/font_resolver.py`）。
    ただし集約モジュールを作るだけでは新規流入は止まらない。実際 font_resolver
    導入後も `C:\\Windows\\Fonts` の直書きは残り続けている。
    Ruff ラチェットと同じ方式で「増やさない」ことを機械的に保証する。

運用:
    ベースラインは .github/abspath-baseline.json。減らしたら
    `python .github/scripts/abspath_ratchet.py --update` で更新してコミットする
    （下げる方向のみ許可）。
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / ".github" / "abspath-baseline.json"

# 走査対象の拡張子。過去記録（jsonl 等）は対象にしない —
# 当時の実行環境をそのまま記録したものなので、書き換えると記録の意味が壊れる。
SCAN_SUFFIXES = {".py", ".ini", ".cfg", ".toml", ".yml", ".yaml"}

SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".pytest_cache", ".ruff_cache", "frontend",
}

# 分類ごとに独立して数える。全体の合計だけを見ていると、
# 本番コードが増えたぶんを scratch/ の削除で相殺できてしまう。
CATEGORY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("archives", re.compile(r"(^|/)archives?/")),
    ("scratch", re.compile(r"(^|/)scratch/")),
    ("tests", re.compile(r"(^|/)tests?/|(^|/)test_[^/]+\.(py)$|^test_")),
)

# ユーザーのホーム配下を指す直書き。ドライブレターだけの `C:\Windows` は
# font_resolver がフォールバック候補として正当に持っているため対象外。
# ドライブレターの大小を問わない（`c:\Users` 表記が実在する）。
ABSPATH_RE = re.compile(r"[A-Za-z]:[\\/]{1,2}Users[\\/]{1,2}[A-Za-z0-9_.-]+")


def docstring_lines(source: str) -> set[int]:
    """docstring が占める行番号を返す。

    「なぜ集約したか」の説明として旧パスを書いた docstring まで数えると、
    集約先のモジュール自身が違反として計上されてしまう。
    数えるのは実行される行だけにする。
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()

    lines: set[int] = set()
    doc_nodes = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    for node in ast.walk(tree):
        if not isinstance(node, doc_nodes) or not node.body:
            continue
        first = node.body[0]
        if (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return lines


def executable_hits(path: Path, text: str) -> int:
    """実行される行にある直書きの数を数える（コメント・docstring は除く）。"""
    skip = docstring_lines(text) if path.suffix == ".py" else set()
    return sum(
        1
        for i, line in enumerate(text.splitlines(), 1)
        if i not in skip
        and not line.lstrip().startswith("#")
        and ABSPATH_RE.search(line)
    )


def classify(rel_posix: str) -> str:
    for name, pattern in CATEGORY_PATTERNS:
        if pattern.search(rel_posix):
            return name
    return "production"


def collect() -> Counter[str]:
    counts: Counter[str] = Counter()
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in SCAN_SUFFIXES:
            continue
        rel = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        hits = executable_hits(path, text)
        if hits:
            counts[classify(rel.as_posix())] += hits
    return counts


def write_baseline(counts: Counter[str]) -> None:
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(
        json.dumps(
            {"total": sum(counts.values()), "by_category": dict(sorted(counts.items()))},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true",
                    help="ベースラインを現在値で更新する（増加方向は拒否）")
    args = ap.parse_args()

    current = collect()
    total = sum(current.values())

    if not BASELINE.exists():
        write_baseline(current)
        print(f"ベースラインを新規作成しました: 合計 {total} 行")
        return 0

    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    base_total: int = base.get("total", 0)
    base_cats: dict[str, int] = base.get("by_category", {})

    regressions: list[str] = []
    for category in sorted(set(current) | set(base_cats)):
        before = base_cats.get(category, 0)
        now = current.get(category, 0)
        if now > before:
            mark = "【重要】" if category == "production" else ""
            regressions.append(f"{mark}{category}: {before} → {now} (+{now - before})")

    print(f"合計: {base_total} → {total} ({total - base_total:+d})")
    for category in sorted(set(current) | set(base_cats)):
        print(f"  {category}: {base_cats.get(category, 0)} → {current.get(category, 0)}")

    if args.update:
        if regressions:
            print("\n直書きが増えているためベースラインを更新できません:")
            for r in regressions:
                print(f"  {r}")
            return 1
        write_baseline(current)
        print("ベースラインを更新しました")
        return 0

    if regressions:
        print(f"\n🚫 ラチェット違反: {len(regressions)} 分類で直書きが増加しました")
        for r in regressions:
            print(f"  ::error ::{r}")
        print(
            "\nパスを直書きせず backend/path_resolver.py を使ってください"
            "（フォントは backend/font_resolver.py）。"
            "意図的な変更なら --update でベースラインを更新してください。"
        )
        return 1

    if total < base_total:
        print(f"✅ 直書きが {base_total - total} 行減りました。"
              f"--update でベースラインを更新することを推奨します")
    else:
        print("✅ ラチェット維持（直書きの増加なし）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
