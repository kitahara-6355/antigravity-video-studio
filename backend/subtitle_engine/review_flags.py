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
    return _compare(captions, tokens, threshold)[0]


def _compare(captions: list[dict], tokens: list, threshold: int) -> tuple[list[dict], dict]:
    """``flag_captions`` の本体。2つ目は、印の付いた字幕の番号 → 食い違った所の
    ``(字幕の字の位置の始め, 終わり, 聞き取りの元の字)`` の並び（候補を作るのに使う）。"""
    spans = [(float(c["a"]), float(c["b"])) for c in captions]
    cap, owner, pos = [], [], []
    for k, c in enumerate(captions):
        for n, ch in enumerate(c["t"]):
            if not _IGNORE.match(ch):
                cap.append(_norm(ch))
                owner.append(k)
                pos.append(n)
    # 音声認識は、字幕のある所（カットで落とした所を除く）だけを並べる
    heard = [(_norm(ch), float(t), ch) for ch, t in tokens if not _IGNORE.match(ch)
             and any(a - 1.0 <= float(t) <= b + 1.0 for a, b in spans)]
    asr = [ch for ch, _, _ in heard]
    regions: dict[int, list[tuple[int, int, str]]] = {}
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
        inside = [i for i in range(i1, i2) if owner[i] == owner[i1]]
        regions.setdefault(owner[i1], []).append(
            (pos[inside[0]], pos[inside[-1]] + 1, "".join(orig for _, _, orig in heard[j1:j2])))
    # 数は値で比べる: 字幕の数が、その字幕の時間に音声認識が聞いた数のどれとも違えば印
    for k, c in enumerate(captions):
        nums = [number_value(m) for m in _DIGITS.findall("".join(_norm(ch) for ch in c["t"]))]
        if not nums:
            continue
        a, b = spans[k]
        said = "".join(ch for ch, t, _ in heard if a - 1.0 <= t <= b + 1.0)
        values = {number_value(m) for m in _NUMS.findall(said)}
        wrong = [n for n in nums if n not in values]
        if values and wrong:
            score[k] += THRESHOLD
            pairs[k].append(("・".join(map(str, wrong)), "・".join(map(str, sorted(values)))))
            # 違う数が1つで、聞き取りにだけある数も1つなら、候補ではその数に替える（「10月」→「11月」）
            others = [m for m in _NUMS.findall(said) if number_value(m) not in nums]
            if len(set(wrong)) == 1 and len({number_value(m) for m in others}) == 1:
                shown = "".join(_norm(ch) for ch in c["t"])
                spot = next(m for m in _DIGITS.finditer(shown) if number_value(m.group()) == wrong[0])
                regions.setdefault(k, []).append((spot.start(), spot.end(), others[0]))
    out = []
    for k, c in enumerate(captions):
        if score[k] >= threshold:
            why = "／".join(f"字幕「{a}」・音声認識「{b}」" for a, b in pairs[k][:3])
            out.append({"i": c["i"], "score": score[k], "why": why})
    return out, {captions[k]["i"]: r for k, r in regions.items()}


# --- ほかの聞き取りも使う（2026-10-19） ---------------------------------------------------------
# 音声認識との食い違いだけでは、台帳の直しがまだ要る26か所のうち20か所にしか印が付かなかった
# （raw4 のゼロからの版）。文字起こしの2回目・3回目・1回目とも並べ、音声認識が食い違うか、
# 2つ以上の聞き取りが食い違う字幕に印を付けると24か所（残りは表記と、後で取り消した直し）。
# 印には、ほかの聞き取りのその字幕の所の字を候補として付ける。正しい字が候補にあれば、人は選ぶだけで済む。

RECOGNISER = "音声認識"
# 候補の字の窓（字幕の前後の秒）。聞き取りの時刻は粗いので広めに取って、字の並びで切り出す
OPTION_PAD = 2.0
# 字幕の字のうち、これだけが聞き取りの字と並ばなければ候補にしない（並べ損ね）
OPTION_MIN_MATCH = 0.3
# 候補の数の上限。多くの聞き取りが同じ字を書いた候補から並べる
MAX_OPTIONS = 3
# 並ばなかった頭と尻の字を候補に足すときの、字幕の時間からのはみ出し（秒）
OPTION_SLACK = 0.3


def reading_tokens(segments: list[dict]) -> list:
    """文字起こしの行（``start``/``end``/``text``、素材の秒）を ``[字, 素材の秒]`` にする。行の中は字数で割る。"""
    out, kept = [], []
    rows = sorted(segments, key=lambda s: float(s.get("sourceStart", s.get("start", 0.0))))
    for s in rows:
        a = float(s.get("sourceStart", s.get("start", 0.0)))
        b = float(s.get("sourceEnd", s.get("end", a)))
        # 区間が重なって起こした行（3回目の読み直しの窓）は、先に取った行と半分以上重なれば捨てる。
        # 字を時刻で並べると、2つの窓の字が交互に混ざる
        if any(min(b, kb) - max(a, ka) > 0.5 * max(1e-6, b - a) for ka, kb in kept[-4:]):
            continue
        kept.append((a, b))
        text = str(s.get("text") or "")
        for k, ch in enumerate(text):
            out.append([ch, round(a + (b - a) * (k + 0.5) / max(1, len(text)), 3)])
    return sorted(out, key=lambda x: x[1])


def _option(caption: dict, tokens: list) -> str:
    """聞き取り ``tokens`` のうち、字幕の所に当たる字（句読点と空白を除く）。並ばなければ空。"""
    a, b = float(caption["a"]), float(caption["b"])
    window = [(ch, float(t)) for ch, t in tokens if a - OPTION_PAD <= float(t) <= b + OPTION_PAD and not _IGNORE.match(ch)]
    cap = [ch for ch in caption["t"] if not _IGNORE.match(ch)]
    if not cap or not window:
        return ""
    sm = difflib.SequenceMatcher(None, [_norm(c) for c in cap], [_norm(c) for c, _ in window], autojunk=False)
    blocks = [m for m in sm.get_matching_blocks() if m.size]
    if sum(m.size for m in blocks) < OPTION_MIN_MATCH * len(cap):
        return ""
    # 一番長く並んだ所のまわり（字幕の字数＋4字）の並びだけを使う。遠くの1字の一致で窓が伸びない
    best = max(blocks, key=lambda m: m.size)
    blocks = [m for m in blocks if abs((m.b - m.a) - (best.b - best.a)) <= 4]
    first, last = blocks[0], blocks[-1]
    # 並ばなかった頭と尻は、字幕の時間の中の字だけを足す（字数は字幕の側より2字まで多くてよい）
    head = first.a + 2 if first.a else 0
    j1 = first.b
    while j1 > 0 and first.b - j1 < head and window[j1 - 1][1] >= a - OPTION_SLACK:
        j1 -= 1
    tail_len = len(cap) - last.a - last.size
    tail = tail_len + 2 if tail_len else 0
    j2 = last.b + last.size
    while j2 < len(window) and j2 - (last.b + last.size) < tail and window[j2][1] <= b + OPTION_SLACK:
        j2 += 1
    return "".join(ch for ch, _ in window[j1:j2])


def patched(caption: str, option: str) -> str:
    """字幕の字のうち、``option``（句読点と空白の無い字）と違う所だけを替えた字。空白と改行は字幕のまま。"""
    keep = [k for k, ch in enumerate(caption) if not _IGNORE.match(ch)]
    cap = [_norm(caption[k]) for k in keep]
    sm = difflib.SequenceMatcher(None, cap, [_norm(c) for c in option], autojunk=False)
    put: dict[int, str] = {}      # 字幕の字の番号 → その字の代わりに出す字（空なら落とす）
    before: dict[int, str] = {}   # 字幕の字の番号 → その字の前に足す字
    tail = ""
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        new = option[j1:j2]
        if i1 == i2:  # 足すだけ
            if i1 < len(keep):
                before[i1] = before.get(i1, "") + new
            else:
                tail += new
            continue
        put[i1] = new
        for n in range(i1 + 1, i2):
            put[n] = ""
    out, n = [], 0
    for k, ch in enumerate(caption):
        if n < len(keep) and keep[n] == k:
            out.append(before.get(n, "") + put.get(n, ch))
            n += 1
        else:
            out.append(ch)
    return "".join(out) + tail


def _replaced(text: str, regions: list[tuple[int, int, str]]) -> str:
    """``text`` の (始め, 終わり) の字を、聞き取りの字に替える（後ろから替えるので位置はずれない）。"""
    for a, b, new in sorted(regions, reverse=True):
        text = text[:a] + new + text[b:]
    return text


def flag_with_readings(captions: list[dict], sources: dict, threshold: int = THRESHOLD) -> list[dict]:
    """``sources``（名前 → ``[字, 素材の秒]``）と食い違う字幕。音声認識（``RECOGNISER``）が食い違うか、
    2つ以上の聞き取りが食い違えば印。返り値は ``{i, score, why, by, tier, options}``:
    ``tier`` は 1（2つ以上が食い違う・先に見る）か 2（音声認識だけ）、``options`` は ``{t, by}`` の候補。

    候補は、字幕の字のうち、その聞き取りと食い違った所だけをその聞き取りの字に替えたもの（空白と改行は
    字幕のまま）。食い違った所が分からない印（数の違いだけ）は、聞き取りの字幕の所の字で替える。
    """
    per, where = {}, {}
    for name, toks in sources.items():
        flags, regions = _compare(captions, toks, threshold)
        per[name] = {f["i"]: f for f in flags}
        where[name] = regions
    out = []
    for c in captions:
        by = [name for name in sources if c["i"] in per[name]]
        if not (len(by) >= 2 or RECOGNISER in by):
            continue
        options: dict[str, list[str]] = {}
        for name in by:
            regions = where[name].get(c["i"])
            if regions:
                text = _replaced(c["t"], regions)
            else:
                heard = _option(c, sources[name])
                text = patched(c["t"], heard) if heard else ""
            if text and re.sub(_IGNORE, "", text) != re.sub(_IGNORE, "", c["t"]):
                options.setdefault(text, []).append(name)
        out.append({"i": c["i"], "score": sum(per[name][c["i"]]["score"] for name in by),
                    "why": "／".join(f"{name}: {per[name][c['i']]['why']}" for name in by[:2]),
                    "by": by, "tier": 1 if len(by) >= 2 else 2,
                    "options": [{"t": t, "by": names} for t, names in
                                sorted(options.items(), key=lambda kv: -len(kv[1]))[:MAX_OPTIONS]]})
    return out
