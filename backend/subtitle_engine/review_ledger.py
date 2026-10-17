"""校正台帳 — 人が通しで見て直した字幕を、書き出しのたびに同じ直しとして当てる。

北原さんが 52回目の 18分までを見て 14か所を直した（2026-10-17）。どれも文字起こしか校閲（AI）の
聞き違い・書き換えで、AI は呼ぶたびに揺れる。人の直しは素材ごとの台帳に残し、校閲・表記の統一の後、
整形（行の割り付け）の前に機械的に当てる。AI には渡さない。

台帳（JSON。`backend/config/reviews/`）:

- ``corrections``: ``{"id", "at", "from", "to", ...}``。``at`` は素材の秒（その言葉を言った所）。
  ``at`` に近い行から ``from`` を探して ``to`` に置き換える。句読点と空白、字幕で消える言いよどみ
  （「えっと」）は無視して探す（字幕で見える形はそれを外した形なので）。行の範囲から ``WINDOW_SEC``
  より離れた行は見ない。
- ``glossary``: ``{"term", "wrong": [...]}``。この素材の中だけで ``wrong`` を ``term`` に置き換える
  （同じ語の聞き違いが何度も出る固有名詞。ほかの素材には当てない — 全体の辞書は `proper_nouns.json`）。
  ``wrong`` が無い用語も書いてよい。用語はどの素材でも改行・字幕の切れ目で割らない（`terms`）。

当たらなかった直しは消さずに報告する。キャッシュ無しで起こし直すと、聞き違いが消えていたり
（``to`` が既にある = already）、別の字に変わっていたり（missing）するので、人が見直す所になる。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

REVIEWS_DIR = Path(__file__).resolve().parents[1] / "config" / "reviews"
# 行の範囲からこれより離れた行には当てない（行は長いと 15 秒ほどある）
WINDOW_SEC = 30.0
# 探すときに無視する字（字幕では句読点を外して空白にする）
_IGNORE = frozenset("、。，．,.!?！？ 　\n")


def load(path) -> dict | None:
    """台帳を読む。パスが空なら None（台帳なし）。壊れた直しがあれば ValueError。"""
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"校正台帳がありません: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    for c in data.get("corrections", []):
        if not isinstance(c.get("at"), (int, float)) or not c.get("from") or not isinstance(c.get("to"), str):
            raise ValueError(f"校正台帳の直しが壊れています（at・from・to が要る）: {c}")
    for g in data.get("glossary", []):
        if not g.get("term") or any(not w for w in g.get("wrong", [])):
            raise ValueError(f"校正台帳の用語が壊れています: {g}")
    data.setdefault("corrections", [])
    data.setdefault("glossary", [])
    return data


def terms(directory=REVIEWS_DIR) -> set[str]:
    """校正台帳すべての用語。整形が改行・字幕の切れ目で割らない語に使う（置き換えはその素材の中だけ）。"""
    out: set[str] = set()
    for p in sorted(Path(directory).glob("*.json")):
        try:
            out |= {g["term"] for g in json.loads(p.read_text(encoding="utf-8")).get("glossary", [])
                    if isinstance(g, dict) and g.get("term")}
        except (OSError, ValueError) as e:
            logger.warning(f"校正台帳の用語を読めません: {p}: {e}")
    return out


def _span(seg: dict) -> tuple[float, float]:
    a = seg.get("sourceStart", seg.get("start"))
    b = seg.get("sourceEnd", seg.get("end"))
    a = float(a if a is not None else 0.0)
    return a, float(b if b is not None else a)


def _distance(at: float, seg: dict) -> float:
    a, b = _span(seg)
    return 0.0 if a <= at <= b else min(abs(at - a), abs(at - b))


def _find(text: str, pattern: str) -> tuple[int, int] | None:
    """``pattern`` が ``text`` のどこにあるか（[i, j)）。句読点と空白は無視して探す。

    それでも無ければ、字幕で消える言いよどみ（`text_formatter.spoken_only_words`）も飛ばして探す。
    直しは画面の字幕から作るが、当てるのは整形の前の文で、言いよどみが残っている（53回目
    32分23秒の字幕「大　何だっけ？」は、文では「大、えっと何だっけ？」だった）。
    ``pattern`` の頭と後ろの句読点は、``text`` の同じ所の句読点まで含める（置き換えで「？？」にしない）。
    """
    i = text.find(pattern)
    if i >= 0:
        return i, i + len(pattern)
    want = "".join(ch for ch in pattern if ch not in _IGNORE)
    if not want:
        return None
    pos = [k for k, ch in enumerate(text) if ch not in _IGNORE]
    bare = "".join(text[k] for k in pos)
    i = bare.find(want)
    if i >= 0:
        return _with_marks(text, pattern, pos[i], pos[i + len(want) - 1] + 1)
    from subtitle_engine import text_formatter
    ignore = f"[{re.escape(''.join(sorted(_IGNORE)))}]"
    words = text_formatter.spoken_only_words()
    gap = f"(?:{ignore}|{'|'.join(map(re.escape, words))})*" if words else f"{ignore}*"
    m = re.search(gap.join(map(re.escape, want)), text)
    return _with_marks(text, pattern, m.start(), m.end()) if m else None


def _with_marks(text: str, pattern: str, i: int, j: int) -> tuple[int, int]:
    """[i, j) を、``pattern`` の頭と後ろにある句読点・空白の数まで、``text`` の句読点・空白に広げる。"""
    head = len(pattern) - len(pattern.lstrip("".join(_IGNORE)))
    tail = len(pattern) - len(pattern.rstrip("".join(_IGNORE)))
    while head and i > 0 and text[i - 1] in _IGNORE:
        i, head = i - 1, head - 1
    while tail and j < len(text) and text[j] in _IGNORE:
        j, tail = j + 1, tail - 1
    return i, j


def apply(segments: list[dict], ledger: dict | None) -> dict:
    """台帳の直しと用語を ``segments`` の ``text`` に当てる（その場で書き換える）。

    返り値は記録に残す報告: applied・already・missing（直しの id と at）と、glossary（用語ごとの置き換え数）。
    """
    report = {"applied": [], "already": [], "missing": [], "glossary": {}}
    if not ledger:
        return report
    for c in ledger.get("corrections", []):
        at = float(c["at"])
        near = sorted((d, k) for k, s in enumerate(segments)
                      if (d := _distance(at, s)) <= WINDOW_SEC)
        entry = {"id": c.get("id"), "at": at}
        for _, k in near:
            text = segments[k].get("text", "")
            hit = _find(text, c["from"])
            if hit:
                segments[k]["text"] = text[:hit[0]] + c["to"] + text[hit[1]:]
                report["applied"].append(entry)
                break
        else:
            right = c["to"] and any(_find(segments[k].get("text", ""), c["to"]) for _, k in near)
            report["already" if right else "missing"].append(entry)
    for g in ledger.get("glossary", []):
        n = 0
        for w in g.get("wrong", []):
            for s in segments:
                text = s.get("text", "")
                if w in text:
                    n += text.count(w)
                    s["text"] = text.replace(w, g["term"])
        if n:
            report["glossary"][g["term"]] = n
    return report
