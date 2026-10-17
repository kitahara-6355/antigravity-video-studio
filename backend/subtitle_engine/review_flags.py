"""機械の要確認 — 字幕と、別の音声認識（ReazonSpeech）の聞き取りが食い違う字幕に印を付ける。

人が通しで見るときに「どこを特に見ればよいか」を示すためのもの。直しはしない（直すのは人と校正台帳）。
52回目の 18分まで（字幕 304枚）で、北原さんが見つけた14か所のうち13か所の字幕に印が付いた。
印は 75枚（約25%）で、多くは音声認識の側の聞き違い（2026-10-17 実測）。読みの辞書が無いので、
漢字とひらがなの違い（「焦る」と「おれる」）は読みの違いとみなして数えない。

字幕の字の流れ全体と、音声認識の字の流れ全体を並べ（素材のうち使った所だけ）、字幕の字が音声認識の
別の字に置き換わっている所を数える。読みの違いだけのもの（ひらがなと漢字・数字の書き方）は数えない。
数は値で比べる（「10月」と「十一月」は違う。数は2回の起こしの多数決に入らないので、ここで拾う）。
"""
from __future__ import annotations

import difflib
import re

# 字幕1枚の印のしきい（食い違った字の数。漢字1字どうしの置き換えは2と数える）
THRESHOLD = 3
# これより長い食い違いは並べ損ね（音声認識が丸ごと落とした所など）とみて数えない
MAX_SPAN = 14

_IGNORE = re.compile(r"[、。，．,.!?！？「」『』（）()・…ー〜\s　]")
_HIRA = re.compile(r"^[ぁ-ゖ]+$")
_KANJI = re.compile(r"^[一-龯々〆]+$")
_KANJI_ANY = re.compile(r"[一-龯々〆]")
_NUM = re.compile(r"^[0-9〇一二三四五六七八九十百千万]+$")
_NUMS = re.compile(r"[0-9〇一二三四五六七八九十百千万]+")
_DIGITS = re.compile(r"[0-9][0-9十百千万]*")
_KANJI_DIGIT = {c: i for i, c in enumerate("〇一二三四五六七八九")}


def _norm(ch: str) -> str:
    if "ァ" <= ch <= "ヶ":
        return chr(ord(ch) - 0x60)  # カタカナはひらがなにそろえる
    if "０" <= ch <= "９":
        return chr(ord(ch) - 0xFEE0)
    return ch


def number_value(text: str) -> int:
    """「十一」→11・「二千二十」→2020・「20万」→200000。"""
    total, cur = 0, 0
    for ch in text:
        if ch.isdigit():
            cur = cur * 10 + int(ch)
        elif ch in _KANJI_DIGIT:
            cur = cur * 10 + _KANJI_DIGIT[ch]
        elif ch in "十百千":
            total += (cur or 1) * {"十": 10, "百": 100, "千": 1000}[ch]
            cur = 0
        elif ch == "万":
            total = (total + cur) * 10000
            cur = 0
    return total + cur


def _same_reading_or_minor(a: str, b: str) -> bool:
    if _NUM.match(a) and _NUM.match(b):
        return number_value(a) == number_value(b)
    if (_HIRA.match(a) and _KANJI.match(b)) or (_KANJI.match(a) and _HIRA.match(b)):
        return True
    return bool(_HIRA.match(a) and _HIRA.match(b) and max(len(a), len(b)) <= 2)


def _regions(sm: difflib.SequenceMatcher):
    """食い違いの塊。1字だけの一致をはさんで続く食い違いは1つにまとめる（「ほ|うら|い」）。"""
    cur = None
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal" and (i2 - i1 > 1 or cur is None):
            if cur:
                yield cur
                cur = None
            continue
        cur = [cur[0], i2, cur[2], j2, cur[4] or op == "replace"] if cur else [i1, i2, j1, j2, op == "replace"]
    if cur:
        yield cur


def flag_captions(captions: list[dict], tokens: list, threshold: int = THRESHOLD) -> list[dict]:
    """字幕（``{i, t, a, b}``: 番号・字・素材の始め・終わり）のうち、音声認識と食い違うもの。

    ``tokens`` は音声認識の ``[字, 素材の秒]``。返り値は ``{i, score, why}``（why は人が読む説明）。
    """
    spans = [(float(c["a"]), float(c["b"])) for c in captions]
    cap, owner = [], []
    for k, c in enumerate(captions):
        for ch in c["t"]:
            if not _IGNORE.match(ch):
                cap.append(_norm(ch))
                owner.append(k)
    # 音声認識は、字幕のある所（カットで落とした所を除く）だけを並べる
    heard = [(_norm(ch), float(t)) for ch, t in tokens if not _IGNORE.match(ch)
             and any(a - 1.0 <= float(t) <= b + 1.0 for a, b in spans)]
    asr = [ch for ch, _ in heard]
    score = [0] * len(captions)
    pairs: list[list[tuple[str, str]]] = [[] for _ in captions]
    sm = difflib.SequenceMatcher(None, cap, asr, autojunk=False)
    for i1, i2, j1, j2, has_replace in _regions(sm):
        a, b = "".join(cap[i1:i2]), "".join(asr[j1:j2])
        if not has_replace or not a or not b or len(a) > MAX_SPAN or len(b) > MAX_SPAN:
            continue
        if _same_reading_or_minor(a, b):
            continue
        # 漢字どうしの置き換え（「藤」→「久木」・名前や言葉の聞き違い）は重く数える
        weight = max(len(a), len(b)) + 1 if _KANJI_ANY.search(a) and _KANJI_ANY.search(b) else len(a)
        if len(a) + len(b) < 3 and weight < 2:
            continue
        for i in range(i1, i2):
            score[owner[i]] += 1
        score[owner[i1]] += weight - len(a)
        # 人が読む説明には、続く同じ字を2字まで付ける（「藤」「久木」→「藤田さ」「久木田さ」）
        tail = "".join(cap[i2:i2 + 2]) if "".join(cap[i2:i2 + 2]) == "".join(asr[j2:j2 + 2]) else ""
        pairs[owner[i1]].append((a + tail, b + tail))
    # 数は値で比べる: 字幕の数が、その字幕の時間に音声認識が聞いた数のどれとも違えば印
    for k, c in enumerate(captions):
        nums = [number_value(m) for m in _DIGITS.findall("".join(_norm(ch) for ch in c["t"]))]
        if not nums:
            continue
        a, b = spans[k]
        said = "".join(ch for ch, t in heard if a - 1.0 <= t <= b + 1.0)
        values = {number_value(m) for m in _NUMS.findall(said)}
        wrong = [n for n in nums if n not in values]
        if values and wrong:
            score[k] += THRESHOLD
            pairs[k].append(("・".join(map(str, wrong)), "・".join(map(str, sorted(values)))))
    out = []
    for k, c in enumerate(captions):
        if score[k] >= threshold:
            why = "／".join(f"字幕「{a}」・音声認識「{b}」" for a, b in pairs[k][:3])
            out.append({"i": c["i"], "score": score[k], "why": why})
    return out
