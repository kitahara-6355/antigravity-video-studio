"""表記の揺れを、動画の中で多い方の書き方にそろえる（2026-10-13）。

同じ語が字幕によって書き分けられていた（33回目: 「僕」53・「ぼく」2、「分かる」8・「わかる」5、
「良かった」1・「よかった」2、「嬉しい」1・「うれしい」1）。校閲（AI）は100行ずつ見るので、
動画全体の書き方まではそろわない。放送や出版の字幕は、表記の決まりを1つ持ってそろえる。

書き分けの組はテンプレートの `notation_variants` に持つ。組ごとに動画の中で多い方の書き方に
寄せ、同数なら組の最初の書き方にする。字を書き換えるのは組の書き方どうしだけで、語の
選び方（「私」と「僕」）には触らない。

同じ字の並びが別の語の一部のことがある（「自分から」の「分か」、「こわかった」の「わか」）ので、
語の頭だけを見る。語の頭は、文節（BudouX）の頭か、区切り・開き括弧の直後。数字の直後
（「40分から」）は見ない。後ろには組ごとに決めた字（活用語尾・助詞）しか続けない。
「わかれば」（別れ）「わかい」（若い）のような別の語は、続く字で外れる。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 区切り（この直後は語の頭）
_BREAKS = " 　\n、。，．,.!?！？…・"
_OPENERS = "「『（(\"'“‘【"
# この直後は語の頭とみなさない（「40分から」「何分か」の「分」は数の単位）
_NUMERALS = set("0123456789０１２３４５６７８９〇一二三四五六七八九十百千万億何数半毎")


def _groups(groups=None) -> list[dict]:
    if groups is None:
        try:
            from template_config import template_config
            groups = template_config.get_subtitle_rules().get("notation_variants")
        except Exception:  # テンプレートが読めなければそろえない
            return []
    out = []
    for g in groups if isinstance(groups, list) else []:
        if not isinstance(g, dict):
            continue
        forms = [f for f in g.get("forms") or [] if isinstance(f, str) and f]
        if len(forms) >= 2:
            out.append({"forms": forms, "after": str(g.get("after") or ""), "noun": bool(g.get("noun"))})
    return out


def _word_starts(text: str) -> set[int]:
    """語が始まりうる位置: 文節の頭と、区切り・開き括弧の直後。"""
    from subtitle_engine.text_formatter import _phrase_parser
    starts = {0}
    parser = _phrase_parser()
    if parser is not None:
        pos = 0
        for part in parser.parse(text):
            starts.add(pos)
            pos += len(part)
    starts.update(i + 1 for i, ch in enumerate(text) if ch in _BREAKS or ch in _OPENERS)
    return starts


def _follows(text: str, j: int, group: dict) -> bool:
    """書き方の後ろ（位置 j）に、この組の語として続いてよい字が来ているか。"""
    from subtitle_engine.text_formatter import _script
    if j >= len(text):
        return group["noun"]  # 語幹（「分か」「良か」）で終わるのは語の途中
    ch = text[j]
    if ch in group["after"]:
        return True
    # 名詞・代名詞の後ろには、区切り・漢字・カタカナ（「僕自身」）が来てよい
    return group["noun"] and (ch in _BREAKS or _script(ch) != "hiragana")


def _places(text: str, form: str, group: dict, starts: set[int]) -> list[int]:
    out = []
    i = text.find(form)
    while i >= 0:
        if i in starts and not (i and text[i - 1] in _NUMERALS) and _follows(text, i + len(form), group):
            out.append(i)
        i = text.find(form, i + 1)
    return out


def unify_notation(segments: list[dict], groups=None) -> dict[str, int]:
    """字幕の文（segments の text）の書き分けを、組ごとに多い方へそろえる。

    返り値は {"ぼく→僕": 書き換えた数}。書き換えが無ければ空。segments はその場で書き換える。
    """
    groups = _groups(groups)
    if not groups or not segments:
        return {}
    texts = [str(s.get("text") or "") if isinstance(s, dict) else "" for s in segments]
    starts = [_word_starts(t) if t else set() for t in texts]
    changed: dict[str, int] = {}
    for group in groups:
        found = {f: [(k, i) for k, t in enumerate(texts) for i in _places(t, f, group, starts[k])]
                 for f in group["forms"]}
        used = [f for f in group["forms"] if found[f]]
        if len(used) < 2:
            continue
        # 多い方。同数なら組の最初の書き方（max は先に出たものを返す）
        target = max(group["forms"], key=lambda f: len(found[f]))
        edits: dict[int, list[tuple[int, str]]] = {}
        for form in used:
            if form != target:
                for k, i in found[form]:
                    edits.setdefault(k, []).append((i, form))
        for k, places in edits.items():
            text, limit = texts[k], len(texts[k])
            # 後ろから書き換える（前の位置がずれない）。重なる所は1回だけ
            for i, form in sorted(places, reverse=True):
                if i + len(form) > limit:
                    continue
                text = text[:i] + target + text[i + len(form):]
                limit = i
                key = f"{form}→{target}"
                changed[key] = changed.get(key, 0) + 1
            texts[k] = text
            # 同じ文の次の組のために、語の頭を数え直す
            starts[k] = _word_starts(text)
    for seg, text in zip(segments, texts):
        if isinstance(seg, dict) and seg.get("text") is not None and seg["text"] != text:
            seg["text"] = text
    if changed:
        logger.info("表記をそろえた: " + "、".join(f"{k} {v}件" for k, v in changed.items()))
    return changed
