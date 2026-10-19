"""編集の決まり（フェーズ1の品質基準）— 北原さんのチャットの指示と書き出しの失敗を、決まりとして残して確かめる。

raw4 の結合テスト（2026-10-05〜19・1〜61回目）で、北原さんがチャットで出した指示（句読点・つなぎ言葉・
あいさつはノーカット など）と、書き出しで起きた失敗（欠落に気づかず高得点・校閲の作り話 など）は、
本線の規則とテストに入っている。ただ散らばっていて、どれが誰のどの言葉から来たか、今も守られているかが
コードを読まないと分からなかった。別の対談でもチャットの指示なしに同じ品質を保つため、台帳
``backend/config/edit_standards.json`` に1つずつ書き、3つの道具で確かめる:

- ``--show``: 決まりの一覧（人が読む）
- ``--gate``: 決まりごとの守る所（関数・設定）とテストが今もあるか。名前を変えて決まりが黙って消えるのを止める
- ``--check SIDECAR``: 書き出した字幕（``*.subtitles.json``）が、字幕から確かめられる決まりを守っているか

使い方（リポジトリ直下で）::

    PYTHONPATH=./backend python -m backend.edit_standards --show
    PYTHONPATH=./backend python -m backend.edit_standards --gate
    PYTHONPATH=./backend python -m backend.edit_standards --check PREVIEW.subtitles.json

どれも AI を呼ばない（課金なし）。
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER = REPO_ROOT / "backend" / "config" / "edit_standards.json"
PYTEST_INI = REPO_ROOT / "pytest.ini"
DICTIONARY = REPO_ROOT / "backend" / "branding" / "proper_nouns.json"

# 句読点。数の桁の「,」「.」（1,000・2.5）は句読点ではない
PUNCTUATION = re.compile(r"[、。，．]|(?<!\d)[,.]|[,.](?!\d)")
# 2行目が話す前から見えないように分ける長さ（sync の max_display_sec と同じ・Netflix の基準）
LONG_SEC = 7.0
# カット点をまたいだとみなす重なり
CROSS_SLACK_SEC = 0.05
# 割れを見る名前・用語の字数。2字の語はほかの語の一部にも出るので見ない。1行の半分を超える長い語
# （「筆文字で伝えたいことば大賞」）は前後の言葉と1行に収まらず、文節で折るしかないので見ない
TERM_MIN_CHARS = 3
TERM_MAX_CHARS = 9


def load(path: Path = LEDGER) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ── 守る所とテストが今もあるか ────────────────────────────────────────────────

def _module_names(tree: ast.Module) -> dict[str, ast.AST]:
    names: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names[node.name] = node
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names[t.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names[node.target.id] = node.value
    return names


def _has_member(node: ast.AST | None, member: str) -> bool:
    """クラスのメソッドか、辞書の文字の鍵か。"""
    if isinstance(node, ast.ClassDef):
        return any(isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)) and b.name == member for b in node.body)
    if isinstance(node, ast.Dict):
        return any(isinstance(k, ast.Constant) and k.value == member for k in node.keys)
    return False


def _parse(path: Path, cache: dict) -> ast.Module | None:
    if path not in cache:
        try:
            cache[path] = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            cache[path] = None
    return cache[path]


def where_problem(ref: str, cache: dict) -> str | None:
    """``path`` / ``path::名前`` / ``path::名前.鍵`` が今もあるか。無ければ理由。"""
    path_text, _, symbol = ref.partition("::")
    path = REPO_ROOT / path_text
    if not path.exists():
        return f"{path_text} がありません"
    if not symbol:
        return None
    tree = _parse(path, cache)
    if tree is None:
        return f"{path_text} を読めません"
    name, _, member = symbol.partition(".")
    names = _module_names(tree)
    if name not in names:
        return f"{path_text} に {name} がありません"
    if member and not _has_member(names[name], member):
        return f"{path_text} の {name} に {member} がありません"
    return None


def _testpaths() -> set[str]:
    try:
        text = PYTEST_INI.read_text(encoding="utf-8")
    except OSError:
        return set()
    m = re.search(r"^testpaths\s*=\s*\n((?:[ \t]+\S.*\n?)+)", text, re.M)
    return {line.strip() for line in m.group(1).splitlines() if line.strip()} if m else set()


def test_problem(ref: str, cache: dict, testpaths: set[str]) -> str | None:
    """``path::test_名前`` か ``path::Class::test_名前`` が今もあり、CI が流すファイルか。"""
    path_text, *parts = ref.split("::")
    path = REPO_ROOT / path_text
    if not path.is_file():
        return f"{path_text} がありません"
    if testpaths and path_text not in testpaths:
        return f"{path_text} は pytest.ini の testpaths に無く、CI で流れません"
    if not parts:
        return None
    tree = _parse(path, cache)
    if tree is None:
        return f"{path_text} を読めません"
    names = _module_names(tree)
    if len(parts) == 2:
        cls, fn = parts
        return None if _has_member(names.get(cls), fn) else f"{path_text} に {cls}::{fn} がありません"
    return None if isinstance(names.get(parts[0]), (ast.FunctionDef, ast.AsyncFunctionDef)) \
        else f"{path_text} に {parts[0]} がありません"


def gate(ledger: dict) -> list[str]:
    """台帳の形・守る所・テスト・点検の名前を確かめ、食い違いを返す（空なら合格）。"""
    problems, cache, testpaths, seen = [], {}, _testpaths(), set()
    groups = set(ledger.get("groups") or [])
    for rule in ledger.get("rules") or []:
        rid = rule.get("id") or "?"
        if not re.fullmatch(r"S\d{2}", rid) or rid in seen:
            problems.append(f"{rid}: id は S と2桁の数字で、重ならないこと")
        seen.add(rid)
        if rule.get("group") not in groups:
            problems.append(f"{rid}: group「{rule.get('group')}」が groups にありません")
        origin = rule.get("from") or {}
        for field in ("rule", "failure"):
            if not str(rule.get(field) or "").strip():
                problems.append(f"{rid}: {field} が空です")
        if not all(str(origin.get(k) or "").strip() for k in ("day", "by", "said")):
            problems.append(f"{rid}: from に day・by・said が要ります（誰のどの言葉から来たか）")
        if not rule.get("where"):
            problems.append(f"{rid}: where（本線で守る所）が空です")
        for ref in rule.get("where") or []:
            if (why := where_problem(ref, cache)):
                problems.append(f"{rid}: 守る所 {why}")
        if not rule.get("tests"):
            problems.append(f"{rid}: tests が空です（決まりが崩れたら落ちるテストが要ります）")
        for ref in rule.get("tests") or []:
            if (why := test_problem(ref, cache, testpaths)):
                problems.append(f"{rid}: テスト {why}")
        if rule.get("check") and rule["check"] not in CHECKS:
            problems.append(f"{rid}: 点検 {rule['check']} はありません（{', '.join(CHECKS)}）")
    return problems


# ── 書き出した字幕の点検 ─────────────────────────────────────────────────────

def _clock(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def _flat(text: str) -> str:
    return re.sub(r"[\s　]", "", text or "")


def _subtitle_rules() -> dict:
    try:
        from template_constants import _DEFAULT_SUBTITLE_RULES
    except ImportError:
        from backend.template_constants import _DEFAULT_SUBTITLE_RULES  # type: ignore[no-redef]
    return _DEFAULT_SUBTITLE_RULES


def _width(line: str) -> float:
    try:
        from subtitle_engine.text_formatter import display_width
    except ImportError:
        from backend.subtitle_engine.text_formatter import display_width  # type: ignore[no-redef]
    return display_width(line)


def _terms(path: Path = DICTIONARY) -> list[str]:
    try:
        entries = json.loads(path.read_text(encoding="utf-8")).get("entries") or []
    except (OSError, ValueError):
        return []
    return sorted({_flat(e.get("correct")) for e in entries
                   if e.get("confirmed") and TERM_MIN_CHARS <= len(_flat(e.get("correct"))) <= TERM_MAX_CHARS},
                  key=len, reverse=True)


def shown(side: dict) -> list[dict]:
    """画面に出る字幕。相づちだけの字幕は字幕データには残し（番組化の基礎データ）、焼き込むときに出さない
    （``smart_cut_engine._burn_subtitles_ffmpeg``）ので、点検もそれを除いて見る。"""
    try:
        from subtitle_engine.text_formatter import _omit_words, is_standalone_omittable
    except ImportError:
        from backend.subtitle_engine.text_formatter import _omit_words, is_standalone_omittable  # type: ignore[no-redef]
    words = _omit_words("omit_standalone_words")
    return [s for s in side["segments"]
            if (s.get("text") or "").strip() and not (words and is_standalone_omittable(s["text"].strip(), words))]


def check_no_punctuation(side: dict) -> list[str]:
    return [f"{_clock(s['start'])} {s['text']!r}" for s in shown(side) if PUNCTUATION.search(s.get("text") or "")]


def check_line_limits(side: dict) -> list[str]:
    rules = _subtitle_rules()
    max_chars, max_lines = rules.get("max_chars_per_line", 18), rules.get("max_lines", 2)
    out = []
    for s in shown(side):
        lines = (s.get("text") or "").split("\n")
        if len(lines) > max_lines or any(_width(line) > max_chars for line in lines):
            out.append(f"{_clock(s['start'])} {s['text']!r}")
    return out


def check_long_captions(side: dict) -> list[str]:
    return [f"{_clock(s['start'])} {s['end'] - s['start']:.1f}秒 {s['text']!r}" for s in shown(side)
            if s["end"] - s["start"] > LONG_SEC and "\n" in (s.get("text") or "")]


def check_flashes(side: dict) -> list[str]:
    try:
        from subtitle_engine.sync import FLASH_SEC
    except ImportError:
        from backend.subtitle_engine.sync import FLASH_SEC  # type: ignore[no-redef]
    return [f"{_clock(s['start'])} {s['end'] - s['start']:.2f}秒 {s['text']!r}" for s in shown(side)
            if s["end"] - s["start"] < FLASH_SEC]


def check_no_cross_cut(side: dict) -> list[str]:
    cuts = [float(c) for c in side.get("cut_points") or []]
    return [f"{_clock(s['start'])} カット {_clock(c)} をまたぐ {s['text']!r}" for s in shown(side)
            for c in cuts if s["start"] < c - CROSS_SLACK_SEC and s["end"] > c + CROSS_SLACK_SEC]


def check_no_lost_words(side: dict) -> list[str]:
    try:
        from quality_gate_plugins import _lost_lines
    except ImportError:
        from backend.quality_gate_plugins import _lost_lines  # type: ignore[no-redef]
    return [f"{_clock(float(g.get('start', 0)))} {g.get('text')!r}（{g.get('reason')}）"
            for g in _lost_lines(side.get("gone") or [], shown(side)) if g.get("blocking")]


def check_terms_unbroken(side: dict, terms: list[str] | None = None) -> list[str]:
    """名前・用語が改行か字幕の切れ目で割れていないか。"""
    terms = _terms() if terms is None else terms
    out, segs = [], shown(side)
    for i, s in enumerate(segs):
        text = s.get("text") or ""
        lines = [_flat(line) for line in text.split("\n")]
        whole = "".join(lines)
        nxt = _flat(segs[i + 1].get("text")) if i + 1 < len(segs) else ""
        for term in terms:
            if term in whole and not any(term in line for line in lines):
                out.append(f"{_clock(s['start'])} 改行で「{term}」が割れた {text!r}")
            joined = whole[-len(term) + 1:] + nxt[:len(term) - 1]
            if nxt and term in joined and term not in whole and term not in nxt:
                out.append(f"{_clock(s['start'])} 字幕の切れ目で「{term}」が割れた")
    return out


CHECKS = {
    "no_punctuation": check_no_punctuation,
    "line_limits": check_line_limits,
    "long_captions": check_long_captions,
    "flashes": check_flashes,
    "no_cross_cut": check_no_cross_cut,
    "no_lost_words": check_no_lost_words,
    "terms_unbroken": check_terms_unbroken,
}
# 守れないことがある決まり（分けると不自然になる所は分けない）。数は出すが不合格にはしない
ADVISORY = {"long_captions"}


def check(side: dict, ledger: dict) -> list[dict]:
    """書き出した字幕を、点検のある決まりで確かめる。1件 = {id, rule, check, advisory, hits}。"""
    out = []
    for rule in ledger.get("rules") or []:
        name = rule.get("check")
        if name in CHECKS:
            out.append({"id": rule["id"], "rule": rule["rule"], "check": name,
                        "advisory": name in ADVISORY, "hits": CHECKS[name](side)})
    return out


def failed(results: list[dict]) -> list[dict]:
    return [r for r in results if r["hits"] and not r["advisory"]]


def format_check(results: list[dict], limit: int = 5) -> list[str]:
    lines = []
    for r in results:
        mark = "✅" if not r["hits"] else ("⚠️" if r["advisory"] else "❌")
        lines.append(f"{mark} {r['id']} {r['rule']}（{len(r['hits'])}件）")
        lines += [f"     {h}" for h in r["hits"][:limit]]
        if len(r["hits"]) > limit:
            lines.append(f"     ほか {len(r['hits']) - limit}件")
    bad = failed(results)
    lines.append(f"{'❌' if bad else '✅'} 点検 {len(results)}件中 守れていない決まり {len(bad)}件"
                 + (f"（{', '.join(r['id'] for r in bad)}）" if bad else ""))
    return lines


def format_rules(ledger: dict) -> list[str]:
    lines = [ledger.get("title", "編集の決まり"), ""]
    for group in ledger.get("groups") or []:
        rules = [r for r in ledger["rules"] if r.get("group") == group]
        if not rules:
            continue
        lines.append(f"■ {group}")
        for r in rules:
            origin = r.get("from") or {}
            lines.append(f"  {r['id']} {r['rule']}")
            lines.append(f"      由来: {origin.get('day')} {origin.get('by')}「{origin.get('said')}」")
            lines.append(f"      失敗: {r.get('failure')}")
            lines.append(f"      守る所: {', '.join(r.get('where') or [])}"
                         + (f"／点検: {r['check']}" if r.get("check") else ""))
        lines.append("")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="編集の決まり（フェーズ1の品質基準）を見る・確かめる（AI を呼ばない）")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--show", action="store_true", help="決まりの一覧")
    mode.add_argument("--gate", action="store_true", help="守る所とテストが今もあるか（無ければ exit 1）")
    mode.add_argument("--check", metavar="SIDECAR", help="書き出した字幕が決まりを守っているか（守れていなければ exit 1）")
    parser.add_argument("--json", action="store_true", help="--check の結果を JSON で出す")
    args = parser.parse_args(argv)
    ledger = load()
    if args.show:
        print("\n".join(format_rules(ledger)))
        return 0
    if args.gate:
        problems = gate(ledger)
        for p in problems:
            print(f"❌ {p}")
        n = len(ledger.get("rules") or [])
        print(f"{'❌' if problems else '✅'} 決まり {n}件の守る所とテストを確かめました（食い違い {len(problems)}件）")
        return 1 if problems else 0
    results = check(json.loads(Path(args.check).read_text(encoding="utf-8")), ledger)
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=1))
    else:
        print("\n".join(format_check(results)))
    return 1 if failed(results) else 0


if __name__ == "__main__":
    sys.exit(main())
