#!/usr/bin/env python3
"""ローカル絶対パス直書きのラチェット（増加を許さない）。

背景:
    直書きされた絶対パスは以下を同時に塞ぐ。

      - GitHub Actions(Ubuntu) での実行 — ランナーに `C:\\Users\\...` は無い
      - 素材の Drive 移行 — 置き場を変えるたびに参照元を個別に直すことになる
      - 別マシンでの開発 — ユーザー名が違うだけで動かない

    集約先は `backend/path_resolver.py`（フォントは `backend/font_resolver.py`）。

2種類を別々に数える理由:
    | 対象 | 集約先 | 2026-07-28 実測 |
    |---|---|---|
    | `C:\\Users\\<user>` 配下 | `path_resolver.py` | 本番 0 / 計 432 行 |
    | `C:\\Windows\\Fonts` | `font_resolver.py` | 本番 136 / 計 159 行 |

    合計だけを見ていると、片方を減らしたぶんでもう片方の増加を相殺できて
    しまう。分類は `fonts:` 接頭辞で分ける。

    集約モジュールを作るだけでは新規流入は止まらない。`font_resolver.py` は
    2026-07-25 に作られたが、3日後も直書きは 159 行残っていた。これがこの
    ラチェットを足した理由そのもの。

運用:
    ベースラインは .github/abspath-baseline.json。減らしたら
    `python .github/scripts/abspath_ratchet.py --update` で更新してコミットする
    （下げる方向のみ許可）。

    分類を新設した回だけは比較対象が無いので `--update` で初回計測を記録できる。
    ゲート側は未計測を 0 扱いにするので、コードとベースラインは必ず同じ
    コミットに入る。
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

# ユーザーのホーム配下を指す直書き。ドライブレターの大小を問わない
# （`c:\Users` 表記が実在する）。
ABSPATH_RE = re.compile(r"[A-Za-z]:[\\/]{1,2}Users[\\/]{1,2}[A-Za-z0-9_.-]+")

# Windows のフォントディレクトリ直書き。
#
# `font_resolver.py` を 2026-07-25 に作ったのに、2026-07-28 時点でまだ
# 165 行残っている（うち本番 136 行）。集約モジュールを作るだけでは
# 新規流入が止まらないことの実例なので、同じゲートをかける。
#
# ユーザーホームと別の分類として数える。合計だけ見ていると、
# ホーム配下を減らしたぶんでフォント直書きの増加を相殺できてしまう。
FONT_RE = re.compile(r"[A-Za-z]:[\\/]{1,2}Windows[\\/]{1,2}Fonts", re.IGNORECASE)

# 集約先そのものは数えない。候補パスを列挙するのがこのモジュールの役目で、
# ここにあるぶんには「直書き」ではない。docstring を除外するのと同じ理由。
EXEMPT_FROM_FONT_RE = {"backend/font_resolver.py"}

# パターンごとに独立したラチェットをかける。キーの接頭辞で分類を分ける。
SCAN_PATTERNS: tuple[tuple[str, re.Pattern[str], frozenset[str]], ...] = (
    ("", ABSPATH_RE, frozenset()),
    ("fonts:", FONT_RE, frozenset(EXEMPT_FROM_FONT_RE)),
)


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


def executable_hits(path: Path, text: str, pattern: re.Pattern[str] = ABSPATH_RE) -> int:
    """実行される行にある直書きの数を数える（コメント・docstring は除く）。"""
    skip = docstring_lines(text) if path.suffix == ".py" else set()
    return sum(
        1
        for i, line in enumerate(text.splitlines(), 1)
        if i not in skip
        and not line.lstrip().startswith("#")
        and pattern.search(line)
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
        rel_posix = rel.as_posix()
        for prefix, pattern, exempt in SCAN_PATTERNS:
            if rel_posix in exempt:
                continue
            hits = executable_hits(path, text, pattern)
            if hits:
                counts[prefix + classify(rel_posix)] += hits
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

    categories = sorted(set(current) | set(base_cats))

    # ベースラインに無い分類は「0だった」ではなく「まだ計測していない」。
    # 分類を新設した回だけは比較対象が存在しないので、--update で記録できる
    # ようにする。ゲート側は 0 扱い（fail-closed）にして、コードとベースラインが
    # 必ず同じコミットで入るよう強制する。
    new_categories = [c for c in categories if c not in base_cats and current.get(c, 0)]

    # (分類, 増加前, 増加後) のまま持つ。表示用の文字列を後から解析すると壊れる。
    regressions: list[tuple[str, int, int]] = [
        (c, base_cats.get(c, 0), current.get(c, 0))
        for c in categories
        if current.get(c, 0) > base_cats.get(c, 0)
    ]

    def describe(item: tuple[str, int, int]) -> str:
        category, before, now = item
        mark = "【重要】" if category.endswith("production") else ""
        before_text = str(before) if category in base_cats else "未計測"
        return f"{mark}{category}: {before_text} → {now} (+{now - before})"

    print(f"合計: {base_total} → {total} ({total - base_total:+d})")
    for category in categories:
        before_text = str(base_cats[category]) if category in base_cats else "未計測"
        print(f"  {category}: {before_text} → {current.get(category, 0)}")

    if args.update:
        blocking = [r for r in regressions if r[0] not in new_categories]
        if blocking:
            print("\n直書きが増えているためベースラインを更新できません:")
            for r in blocking:
                print(f"  {describe(r)}")
            return 1
        if new_categories:
            print(f"\n分類を新設しました（初回計測）: {', '.join(new_categories)}")
        write_baseline(current)
        print("ベースラインを更新しました")
        return 0

    if regressions:
        print(f"\n🚫 ラチェット違反: {len(regressions)} 分類で直書きが増加しました")
        for r in regressions:
            print(f"  ::error ::{describe(r)}")
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
