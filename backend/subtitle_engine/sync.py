"""字幕の出だし・終わりを、出力の音声の「話し始め・話し終わり」に合わせる。

2026-10-06 ユーザー指摘で作った。「30〜40秒の字幕が言葉より先に出すぎる」。
字幕の時刻は文字起こし（Gemini）の推定で、0.1〜0.5 秒刻みの粗い値しか無い。
さらに1つの発話を何枚かに分けるとき、各字幕の時刻は文字数で按分していた。
その結果、字幕が話し始めより 0.4〜1.2 秒早く出ていた。

やること:

1. 出力の音声から「間（ポーズ）」を取り、話し始め（onset）と話し終わり（offset）の候補にする
2. 各字幕の推定時刻を、近くの話し始め・話し終わりに寄せる（無ければ推定のまま）
3. 見せ方の規則を掛ける — 出だしは話し始めの少し後、終わりは次の話し始めの少し前、
   つながった発話は途切れさせない、短すぎる字幕は伸ばす、カットの直前・直後で出入りしない

数字は template の subtitle_rules で変えられる（`timing_rules()`）。
"""
from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

FRAME_SEC = 0.01
# 1フレーム（30fps）。字幕を続けて出すときの最小のすき間（2フレーム）に使う
VIDEO_FRAME = 1 / 30

DEFAULT_TIMING = {
    # 出だし: 話し始めからこの秒数だけ遅らせる。業界の標準（Netflix・DCMP）は話し始めちょうど。
    # 0.3 秒は冒頭で遅く感じた（2026-10-06 ユーザー確認）ので 0 にした
    "lead_in_sec": 0.0,
    # 終わり: 次の話し始めのこの秒数前に消す（ユーザー指定 0.2）
    "end_before_next_sec": 0.2,
    # 話し終わってから残してよい最長（間が長いときに出しっぱなしにしない）
    "linger_sec": 0.5,
    # 字幕どうしのすき間がこれ未満になるなら、2フレーム空けて続けて出す（ちらつき防止）
    "chain_gap_sec": 0.5,
    # 一番短い表示時間
    "min_display_sec": 0.8,
    # 推定時刻から、この範囲の話し始め・話し終わりにだけ寄せる
    "snap_window_sec": 0.8,
    # カットの直前・直後この秒数では字幕を出し入れしない（カット点に揃える）
    "cut_zone_sec": 0.25,
    # 1枚の字幕を出し続けてよい最長。Netflix の字幕の基準（Timed Text Style Guide）も 7 秒。
    # 2行の字幕がこれより長く出るときは、話の切れ目で2枚に分ける（`_split_long`）。0 なら分けない
    "max_display_sec": 7.0,
}

# 隣り合う字幕の出だしの最小の間隔（同じ話し始めに2枚が寄るのを防ぐ）
MIN_STEP_SEC = 0.4
# 音声認識で時刻を取った字幕は、近くの話し始めにだけ寄せる。認識の時刻は文字の位置
# そのものなので、遠くの話し始めは別の句（51 秒で 1.3 秒遅れた・2026-10-06 実測）
ASR_SNAP_BEFORE_SEC = 0.25
ASR_SNAP_AFTER_SEC = 0.4
# 人が話せる速さの上限（字/秒）。認識が拾えなかった字幕の頭を話す時間の見積もりに使う
# （`aligner.MAX_CPS` と同じ値）
HEAD_MAX_CPS = 12.0
# 認識の字の時刻が、実際の声より早く出る幅。35 秒の「デザイン書道の」は、間の後の話し始め
# （35.41 秒）と同じ時刻に「書」が出た。「デザイン」を話す分、0.4 秒ほど早い（2026-10-07 実測）
HEAD_EARLY_SEC = 0.4
# 頭を認識が拾えなかった字幕（この字数以上）は、前の字幕で最後に聞こえた字の後ろまで話し始めを探す。
# 遠くても、拾えなかった字を毎秒 HEAD_MIN_CPS 字で話せる所まで（28分40秒「私から見ると 書いてる…」は
# 31回目で頭の 7 字を 0.2 秒で言わせる所に出て、前の字幕が「私から見ると」の間も出ていた）。
# 前の字幕の最後に聞こえた字も早めに出るので、その後ろ HEAD_EARLY_SEC は前の字幕の声とみなす
HEAD_LOOKBACK_MIN_CHARS = 3
HEAD_MIN_CPS = 3.0
HEAD_AFTER_PREV_SEC = HEAD_EARLY_SEC
# 間とみなす長さと、話しているとみなす長さ
MIN_PAUSE_SEC = 0.15
MIN_SPEECH_SEC = 0.1
# 局所の背景音（その前後数秒の静かな側）より、これだけ大きければ声とみなす
SPEECH_ABOVE_FLOOR_DB = 12.0
FLOOR_WINDOW_SEC = 3.0
# 話し始めの頭を戻す範囲と、立ち上がりとみなす大きさ
ONSET_BACKTRACK_SEC = 0.15
ONSET_ABOVE_FLOOR_DB = 6.0
FLOOR_PERCENTILE = 10
GLOBAL_FLOOR_PERCENTILE = 30


def timing_rules() -> dict:
    """テンプレートの subtitle_rules で上書きした値。読めなければ既定値。"""
    rules = dict(DEFAULT_TIMING)
    try:
        from template_config import template_config
        custom = template_config.get_subtitle_rules() or {}
    except Exception:  # テンプレートが無い・壊れていても字幕は出す
        custom = {}
    for key in rules:
        value = custom.get(key)
        if isinstance(value, (int, float)) and value >= 0:
            rules[key] = float(value)
    return rules


@dataclass
class SpeechMap:
    """話し始めと話し終わりの候補（秒、昇順）。"""
    onsets: list[float]
    offsets: list[float]
    duration: float


def frame_levels_db(samples: np.ndarray, rate: int) -> np.ndarray:
    """10ms ごとの音量（dBFS）。"""
    hop = int(rate * FRAME_SEC)
    n = len(samples) // hop
    if n == 0:
        return np.zeros(0)
    frames = samples[: n * hop].astype(np.float64).reshape(n, hop) / 32768.0
    rms = np.sqrt(np.mean(frames * frames, axis=1)) + 1e-9
    return 20 * np.log10(rms)


def speech_mask(levels: np.ndarray) -> np.ndarray:
    """声のあるフレーム。背景音の大きさは場所ごとに違うので、前後数秒の静かな側を基準にする。"""
    if len(levels) == 0:
        return np.zeros(0, dtype=bool)
    half = int(FLOOR_WINDOW_SEC / FRAME_SEC)
    step = max(1, half // 6)
    centers = np.arange(0, len(levels), step)
    floors = np.array([np.percentile(levels[max(0, c - half): c + half + 1], FLOOR_PERCENTILE)
                       for c in centers])
    floor = np.interp(np.arange(len(levels)), centers, floors)
    # 声が数秒続くと局所の基準が声そのものになるので、全体の静かな側で頭を抑える
    floor = np.minimum(floor, np.percentile(levels, GLOBAL_FLOOR_PERCENTILE))
    mask = _clean(levels > floor + SPEECH_ABOVE_FLOOR_DB)
    # 話し始めは声が立ち上がる途中から。弱い立ち上がり（子音・息）まで頭を戻す
    back = int(ONSET_BACKTRACK_SEC / FRAME_SEC)
    for a, _ in _runs(mask, True):
        j = a
        while j > 0 and a - j < back and not mask[j - 1] and levels[j - 1] > floor[j - 1] + ONSET_ABOVE_FLOOR_DB:
            j -= 1
        mask[j:a] = True
    return mask


def _runs(mask: np.ndarray, value: bool) -> list[tuple[int, int]]:
    out, start = [], None
    for i, v in enumerate(mask):
        if v == value and start is None:
            start = i
        elif v != value and start is not None:
            out.append((start, i))
            start = None
    if start is not None:
        out.append((start, len(mask)))
    return out


def _clean(mask: np.ndarray) -> np.ndarray:
    """短い間は声に、短い声（咳・物音）は間に戻す。"""
    mask = mask.copy()
    min_pause = int(MIN_PAUSE_SEC / FRAME_SEC)
    min_speech = int(MIN_SPEECH_SEC / FRAME_SEC)
    for a, b in _runs(mask, False):
        if b - a < min_pause and a > 0 and b < len(mask):
            mask[a:b] = True
    for a, b in _runs(mask, True):
        if b - a < min_speech:
            mask[a:b] = False
    return mask


def speech_map_from_levels(levels: np.ndarray) -> SpeechMap:
    mask = speech_mask(levels)
    runs = _runs(mask, True)
    return SpeechMap(onsets=[a * FRAME_SEC for a, _ in runs],
                     offsets=[b * FRAME_SEC for _, b in runs],
                     duration=len(levels) * FRAME_SEC)


def speech_map(media: str, rate: int = 16000) -> SpeechMap:
    """動画・音声ファイルから話し始め・話し終わりを取る（ffmpeg・ローカル）。"""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-v", "error", "-i", str(media), "-vn", "-ac", "1",
         "-ar", str(rate), "-f", "s16le", "-"],
        capture_output=True, timeout=1800)
    if proc.returncode != 0:
        raise RuntimeError(f"音声の読み出しに失敗: {proc.stderr[-300:]!r}")
    samples = np.frombuffer(proc.stdout, dtype=np.int16)
    return speech_map_from_levels(frame_levels_db(samples, rate))


def _nearest(points: list[float], t: float, window: float) -> float | None:
    if not points:
        return None
    i = int(np.searchsorted(points, t))
    best = None
    for j in (i - 1, i):
        if 0 <= j < len(points) and abs(points[j] - t) <= window:
            if best is None or abs(points[j] - t) < abs(best - t):
                best = points[j]
    return best


def _nearest_biased(points: list[float], t: float, before: float, after: float) -> float | None:
    cands = [p for p in points if t - before <= p <= t + after]
    return min(cands, key=lambda p: abs(p - t)) if cands else None


def _pause_end(t: float, speech: SpeechMap) -> float | None:
    """t が間（MIN_GAP_BEFORE 以上）の中なら、その間が明けて話し始める時刻。"""
    i = int(np.searchsorted(speech.onsets, t, side="right"))
    if 0 < i < len(speech.onsets) and speech.offsets[i - 1] <= t:
        if speech.onsets[i] - speech.offsets[i - 1] >= MIN_GAP_BEFORE:
            return speech.onsets[i]
    return None


def _pause_start(t: float, speech: SpeechMap) -> float | None:
    """t が間（MIN_GAP_BEFORE 以上）の中なら、その間に入った時刻（話し終わり）。"""
    i = int(np.searchsorted(speech.offsets, t, side="right"))
    if i > 0 and speech.offsets[i - 1] <= t:
        nxt = speech.onsets[i] if i < len(speech.onsets) else speech.duration
        if t < nxt and nxt - speech.offsets[i - 1] >= MIN_GAP_BEFORE:
            return speech.offsets[i - 1]
    return None


def _in_cut_zone(t: float, cut_points: list[float], zone: float) -> float | None:
    for cp in cut_points:
        if abs(t - cp) < zone:
            return cp
    return None


def _zone(seg: dict) -> tuple[float, float]:
    """字幕を出してよい区間（出力の秒・`aligner.keep_in_zones`）。無ければ全体。"""
    z = seg.get("_zone")
    return (float(z[0]), float(z[1])) if z else (float("-inf"), float("inf"))


def _within(points: list[float], zone: tuple[float, float]) -> list[float]:
    """points（昇順）のうち zone の中の点。"""
    lo = int(np.searchsorted(points, zone[0], side="left"))
    hi = int(np.searchsorted(points, zone[1], side="right"))
    return points[lo:hi]


def _chars(seg: dict) -> int:
    return max(1, len("".join(str(seg.get("text") or "").split())))


def _active(speech: SpeechMap, a: float, b: float) -> list[tuple[float, float]]:
    out = []
    for on, off in zip(speech.onsets, speech.offsets):
        lo, hi = max(on, a), min(off, b)
        if hi > lo:
            out.append((lo, hi))
    return out


def _speaking_time(speech: SpeechMap, a: float, b: float) -> float:
    """a〜b 秒のうち、声がある（話している）長さ。"""
    return sum(hi - lo for lo, hi in _active(speech, a, b))


def _last_heard(s: dict) -> float | None:
    """字幕で最後に聞こえた（認識と突き合った）字の時刻。無ければ None。

    字幕から外した言いよどみを認識が聞いていれば（`aligner.mark_filler_tails` の `_asr_tail`）、
    その声も前の字幕のものとみなす（1分35秒の「こう」・35回目）
    """
    marks = s.get("_asr_marks") or ()
    if not (s.get("_asr") and marks):
        return None
    return max(float(marks[-1][1]), float(s.get("_asr_tail") or 0.0))


def _clock(active: list[tuple[float, float]], x: float) -> float:
    """喋っている時間の先頭から x 秒の位置の時刻。"""
    for lo, hi in active:
        if x <= hi - lo:
            return lo + x
        x -= hi - lo
    return active[-1][1]


def _distribute_by_speech(items: list[dict], speech: SpeechMap) -> int:
    """同じ発話（sourceStart/sourceEnd が同じ）から分けた字幕の時刻を、文字数で
    **喋っている時間**に配り直す。これまでは間も含めた時間で按分していたので、
    発話の途中に間があると後ろの字幕ほど早く出た（2026-10-06 ユーザー指摘 12秒・32〜42秒）。
    """
    def key(s):
        # 音声認識で時刻が付いた字幕（突き合った字幕と、その間に配った字幕）は配り直さない。
        # 文字ごとの時刻の方が確かで、配り直すと 38 秒の字幕が声より 1.2 秒早く出た
        if s.get("_asr") or s.get("_asr_interp"):
            return (None, None)
        return (s.get("sourceStart"), s.get("sourceEnd"))

    done = 0
    i = 0
    while i < len(items):
        j = i + 1
        if key(items[i]) != (None, None):
            while j < len(items) and key(items[j]) == key(items[i]):
                j += 1
        group = items[i:j]
        if len(group) >= 2:
            a, b = float(group[0]["start"]), float(group[-1]["end"])
            active = _active(speech, a, b)
            total = sum(hi - lo for lo, hi in active)
            if total >= MIN_STEP_SEC * len(group):
                chars = [_chars(s) for s in group]
                whole = sum(chars)
                acc = 0
                for s, c in zip(group, chars):
                    s["start"] = _clock(active, total * acc / whole)
                    acc += c
                    s["end"] = _clock(active, total * acc / whole - 1e-6)
                done += 1
        i = j
    return done


FLASH_SEC = 0.5
# 読み切れない速さ（1秒あたりの字数）。出る時間が min_display_sec に届かず、これより速い字幕も
# 隣とまとめる（2分41秒の 16 字「行かなくなったってことはないんで」が 0.76 秒・2026-10-06 実測）。
# 「はい」のような短い語は 0.6 秒でも読めるので残す
FAST_CPS = 8.0
# 切れ目を動かすのは、2枚の字幕のすき間がこれ以内のとき（続けて話している）
RESPLIT_MAX_GAP_SEC = 0.3
# 長く出続ける字幕を分けるとき（`_split_long`）: 2行目の頭の字をこの字数まで認識が拾えなくても、
# 次に拾えた字から話し始めを見積もる。分けた1枚がこれより短くなるなら分けない
SPLIT_HEAD_SKIP = 2
SPLIT_MIN_PART_SEC = 1.5
# 1行目を話し終えてから2行目を話し始めるまでに、これより長く話している（字幕に無い言葉がある）なら
# 分けない。分けるとその声に字幕が出ない（40回目の 36分03秒: 起こしが「…タッパーに移したら
# おいしくなりますね／紙皿だったらおいしくない…」を1文にまとめ、間の 2 秒の声が字幕に無かった）
SPLIT_MAX_UNSAID_SEC = 1.0
# 認識の1字を話す長さ（`aligner.CHAR_SEC` と同じ値。拾えなかった字の時刻の見積もりに使う）
SPLIT_CHAR_SEC = 0.13
# 分けた所の手前の字の後ろ・後ろの頭の字の前に続く声は、この長さまでその字の声とみなす（字の時刻は
# 言い始めの時刻。42回目の 1分22秒は「時に」の「に」が 0.6 秒伸び、拾えなかった「お習」の声と合わせて、
# 字幕に無い声を 1.1 秒と数えていた。実際は間の 0.3 秒だけ）
SPLIT_WORD_EDGE_SEC = 0.5


def _too_short(s: dict, min_display: float) -> bool:
    """読めないほど短く出る字幕か。"""
    dur = float(s["end"]) - float(s["start"])
    return dur < FLASH_SEC or (dur < min_display and _chars(s) > FAST_CPS * max(dur, 0.01))


def _caption_limits() -> tuple[int, int]:
    """1行の文字数と行数（テンプレート。読めなければ 18 字・2 行）。"""
    try:
        from template_config import template_config
        return (int(template_config.get_max_chars_per_line()),
                int(template_config.get_subtitle_rules().get("max_lines", 2)))
    except Exception:
        return 18, 2


def _flat(s: dict) -> str:
    """字幕を1行に戻した文。句読点を外した跡の改行（`_break_punct`）は全角スペースにして、語の切れ目を残す。"""
    lines = str(s.get("text") or "").split("\n")
    if len(lines) == 2 and s.get("_break_punct"):
        return f"{lines[0]}\u3000{lines[1]}"
    return "".join(lines)


def _breaks_at_space(flat: str, text: str | None) -> bool:
    """1行の文 flat を組んだ text の改行が、flat の空白（句読点を外した跡）の所か。"""
    if not text or text.count("\n") != 1:
        return False
    first = text.split("\n")[0]
    return flat.startswith(first) and flat[len(first):len(first) + 1] in ("\u3000", " ")


def _as_one_caption(first: str, second: str, max_chars: int, max_lines: int,
                    first_flat: str | None = None, second_flat: str | None = None) -> str | None:
    """2枚の字幕を続けて1枚（max_lines 行・1行 max_chars 字）に組み直した形。入らなければ None。

    first_flat / second_flat は1行に戻した文（`_flat`）。無ければ改行を詰める。
    """
    if "\n" not in first and "\n" not in second and max_lines >= 2:
        return f"{first}\n{second}"
    a = first.replace("\n", "") if first_flat is None else first_flat
    b = second.replace("\n", "") if second_flat is None else second_flat
    flat = f"{a}\u3000{b}"
    try:
        caps = _split_flat(flat, max_chars, max_lines)
    except Exception:  # 組み直せなくても字幕は出す
        caps = []
    if caps:
        # 継ぎ目の空白が行頭・行末に来たら消す（「…次の週から\n　行かなく…」）
        return "\n".join(line.strip("\u3000 ") for line in caps[0].split("\n")) if len(caps) == 1 else None
    if len(flat) > max_chars * max_lines:
        return None
    return "\n".join(flat[k:k + max_chars] for k in range(0, len(flat), max_chars))


def _merge_flashes(items: list[dict], min_display: float, max_chars: int | None = None,
                   max_lines: int | None = None) -> int:
    """読めないほど短く出る字幕（`_too_short`）を、隣の字幕とまとめて1枚にする。

    隣が1行なら行として足す。隣が2行でも、続けて1枚に組み直せるならそうする
    （2分36秒の「もう強烈な」が 0.49 秒で消えた・2026-10-06 実測）。
    詰まっている側（すき間が短い側）に寄せる。
    """
    if max_chars is None or max_lines is None:
        max_chars, max_lines = _caption_limits()
    merged = 0
    for i, s in enumerate(items):
        if s.get("_merged") or not _too_short(s, min_display):
            continue
        # 声の拾えない字幕は 0.5 秒未満のときだけまとめる（速さで延ばすと、カットで消えた言葉が長く出る）
        if _unheard(s) and float(s["end"]) - float(s["start"]) >= FLASH_SEC:
            continue
        cands = []
        for j in (i - 1, i + 1):
            # カットの向こうの字幕とはまとめない（まとめた字幕がカットをまたいで出る）
            if 0 <= j < len(items) and not items[j].get("_merged") and _zone(items[j]) == _zone(s):
                o = items[j]
                pair = (o, s) if j < i else (s, o)
                first, second = str(pair[0].get("text", "")), str(pair[1].get("text", ""))
                text = _as_one_caption(first, second, max_chars, max_lines, _flat(pair[0]), _flat(pair[1]))
                if text is not None:
                    gap = s["start"] - o["end"] if j < i else o["start"] - s["end"]
                    # 2枚の継ぎ目は語の切れ目（組み直すときも全角スペースを置く）
                    joint = text == f"{first}\n{second}" or _breaks_at_space(
                        f"{_flat(pair[0])}\u3000{_flat(pair[1])}", text)
                    cands.append((gap, j, text, joint))
        if not cands:
            continue
        _, j, text, joint = min(cands, key=lambda c: (c[0], c[1]))
        o = items[j]
        o["text"], o["_break_punct"] = text, joint
        if j < i:
            o["end"] = max(o["end"], s["end"])
            o["_ends_punct"] = s.get("_ends_punct", False)
        else:
            o["start"] = min(o["start"], s["start"])
        s["_merged"] = True
        merged += 1
    return merged


def _split_flat(flat: str, max_chars: int, max_lines: int) -> list[str]:
    """1行の文を字幕（1枚 max_lines 行・1行 max_chars 字）に組む。

    句読点を出さないとき、文の中の全角スペースは外した句読点の跡（か2枚の継ぎ目）なので、「、」に
    戻して折り目の手掛かりにし、組んだ後でまた外す。空白のまま組むと、句読点の所を切れ目と見ずに
    「…すごく人気だと|思います」と折った（15分59秒・28回目）。
    """
    from subtitle_engine import text_formatter as tf
    if not tf._strip_punctuation_enabled():
        return tf.split_into_captions(flat, max_chars, max_lines)
    caps = tf.split_into_captions(flat.replace("\u3000", "、"), max_chars, max_lines, True)
    return [c for c in (tf.strip_punctuation(c) for c in caps) if c]


def _wrap_one(text: str, max_chars: int, max_lines: int) -> str | None:
    """1枚（max_lines 行・1行 max_chars 字）に組んだ形。入らなければ None。"""
    try:
        caps = _split_flat(text, max_chars, max_lines)
    except Exception:  # 組めなければ動かさない
        return None
    if len(caps) != 1:
        return None
    return "\n".join(line.strip("\u3000 ") for line in caps[0].split("\n"))


def _cut_times(s: dict) -> list[tuple[int, int, float]]:
    """字幕の文節の切れ目と、その切れ目の次の文字を話した時刻（認識）: (位置, 文字の番号, 時刻)。"""
    marks = dict(s.get("_asr_marks") or ())
    if not marks:
        return []
    try:
        from subtitle_engine import aligner
        from subtitle_engine import text_formatter as tf
        parser = tf._phrase_parser()
    except Exception:  # 文節が読めなければ動かさない
        return []
    flat = _flat(s)
    if parser is None or not flat:
        return []
    out = []
    for k in tf._phrase_ends(parser, flat)[:-1]:
        n = len(aligner._norm_text(flat[:k]))
        if n in marks:
            out.append((k, n, float(marks[n])))
    return out


def _resplit_flashes(items: list[dict], min_display: float, max_chars: int | None = None,
                     max_lines: int | None = None) -> int:
    """隣とまとめられなかった短すぎる字幕に、前の字幕の終わりの文節を移して、出る時間を延ばす。

    実例（62秒）: 「…理事長で|いらっしゃいまして」と切れ、早口の「いらっしゃいまして」が 0.7 秒で
    消えた。隣はどちらも2行でまとめられない。前の字幕の文節の切れ目のうち、音声認識で話した時刻が
    分かる所で切り直し、両方が min_display_sec 以上出る最も少ない移し方を採る。
    続けて話している（すき間が RESPLIT_MAX_GAP_SEC 以内）ときだけ動かす。声が聞こえない字幕
    （カットで声が消えた言葉）は動かさない。別の発話から移すときは間を1字空ける。
    """
    if max_chars is None or max_lines is None:
        max_chars, max_lines = _caption_limits()
    live = [s for s in items if not s.get("_merged")]
    moved = 0
    for i, s in enumerate(live):
        if i == 0 or _unheard(s) or not _too_short(s, min_display):
            continue
        p = live[i - 1]
        if float(s["start"]) - float(p["end"]) > RESPLIT_MAX_GAP_SEC or _zone(p) != _zone(s):
            continue
        text, flat = _flat(s), _flat(p)
        a, b = p.get("sourceStart"), s.get("sourceStart")
        # 別の発話から移すとき・前の字幕が句読点で終わっていたとき（「…見てるでしょ。」）は1字空ける
        sep = "\u3000" if (a is not None and b is not None and a != b) or p.get("_ends_punct") else ""
        for k, n, t in reversed(_cut_times(p)):
            if t - 2 * VIDEO_FRAME - float(p["start"]) < min_display or float(s["end"]) - t < min_display:
                continue
            head_flat = flat[:k].rstrip("\u3000 ")
            tail_flat = flat[k:].strip("\u3000 ") + sep + text
            head = _wrap_one(head_flat, max_chars, max_lines)
            tail = _wrap_one(tail_flat, max_chars, max_lines)
            if head and tail:
                p["text"], p["end"] = head, round(t - 2 * VIDEO_FRAME, 3)
                s["text"], s["start"] = tail, round(t, 3)
                p["_break_punct"] = _breaks_at_space(head_flat, head)
                s["_break_punct"] = _breaks_at_space(tail_flat, tail)
                p["_ends_punct"] = head_flat != flat[:k] or flat[k:k + 1] in ("\u3000", " ")
                _move_marks(p, s, n, flat[k:])
                moved += 1
                break
    return moved


def _move_marks(p: dict, s: dict, n: int, moved: str) -> None:
    """前の字幕の n 文字目から後ろ（moved）を次の字幕の頭へ移したあと、文字ごとの時刻も付け直す。"""
    from subtitle_engine import aligner
    shift = len(aligner._norm_text(moved))
    marks = list(p.get("_asr_marks") or ())
    p["_asr_marks"] = [(c, t) for c, t in marks if c < n]
    s["_asr_marks"] = [(c - n, t) for c, t in marks if c >= n] + [
        (c + shift, t) for c, t in (s.get("_asr_marks") or ())]


def _unheard(s: dict) -> bool:
    """音声認識に声が1文字も無く、前後の字幕の間に配っただけの字幕（カットで声が消えた言葉など）。"""
    return bool(s.get("_asr_interp") and not s.get("_asr") and not s.get("_asr_heard"))


def _readable_sec(s: dict, min_display: float) -> float:
    """`_too_short` にならない最短の出る長さ（丸めの分を少し足す）。"""
    return max(FLASH_SEC, min(min_display, _chars(s) / FAST_CPS)) + 0.01


def _give_unheard_room(items: list[dict], given: list[dict], min_display: float) -> int:
    """隣とまとめられず読めないほど短い、声の拾えない字幕（`_unheard`）の出だしを、配った所（前後の
    聞こえた字幕の間・`aligner.interpolate_unaligned`。given の `_sync_index` 番）の方へ、読める長さまで
    戻す。戻した数を返す。

    話し始めに寄せた後で次の字幕までが読めない長さになると、言った言葉の字幕が外れていた
    （`_drop_unheard_flashes`。50回目の 11分52秒: 聞き手の「エピソードなんですか？」を前後の字幕の間
    1.31 秒に配り、声の立ち上がりに寄せて 0.72 秒になった）。声より早く出る分が小さくなるよう、戻すのは
    読める長さぎりぎりまで。配った所より前・区間の外へは戻さず、前の字幕にも読める長さを残す。
    配った間から読める長さを取れなければ、今までどおり外す。相づちだけの字幕（字幕に出さない）は戻さない。
    """
    try:
        from subtitle_engine.text_formatter import is_standalone_omittable
    except Exception:  # 読めなければ相づちも戻す
        def is_standalone_omittable(text):
            return False
    live = [s for s in items if not s.get("_merged")]
    moved = 0
    for i, s in enumerate(live):
        if not _unheard(s) or not _too_short(s, min_display) or is_standalone_omittable(s.get("text")):
            continue
        a, b = float(s["start"]), float(s["end"])
        lo = max(float(given[s["_sync_index"]]["start"]), _zone(s)[0])
        p = live[i - 1] if i > 0 and _zone(live[i - 1]) == _zone(s) else None
        if p is not None:
            lo = max(lo, float(p["start"]) + max(MIN_STEP_SEC, _readable_sec(p, min_display))
                     + 2 * VIDEO_FRAME)
        t = round(max(lo, b - _readable_sec(s, min_display)), 3)
        if t >= a or _too_short({"start": t, "end": b, "text": s.get("text")}, min_display):
            continue
        s["start"] = t
        if p is not None:
            p["end"] = round(min(float(p["end"]), t - 2 * VIDEO_FRAME), 3)
        moved += 1
    return moved


def _drop_unheard_flashes(items: list[dict], min_display: float = DEFAULT_TIMING["min_display_sec"]) -> int:
    """隣とまとめられなかった読めない字幕（`_too_short`）のうち、音声認識に声が無いものを出さない。

    カットで声が消えた言葉が、カット点に 0.3 秒だけ残る（9分39秒の「いたんだよね」・
    2026-10-06 実測）。読めず、言葉も聞こえないので出す意味が無い。認識に声がある字幕は残す。
    0.5 秒を超えても、字数に対して短すぎれば読めない（3分10秒の 16 字「何か一番最初の
    きっかけなんですね」が 0.55 秒・2026-10-07）。「はい」のように読める短い語は残す。
    """
    dropped = 0
    for s in items:
        if s.get("_merged") or not _too_short(s, min_display):
            continue
        if _unheard(s):
            s["_merged"], s["_gone"] = True, "unheard_short"
            dropped += 1
    return dropped


# 外した字幕を欠落と数える字数。これに満たない短い声（「おー」「もうね」）は数えない
LOST_MIN_CHARS = 4
# 外した字幕の言葉が、前後この秒数の中の字幕にあれば繰り返し（4分53秒「オリンピック はい」）
LOST_ECHO_SEC = 5.0
# カット点からこの秒数の中に配った字幕は、カットで声が消えた言葉とみなして隣に足さない（9分39秒「いたんだよね」）
LOST_CUT_SEC = 0.3
# 外した字幕と隣の字幕がこれより離れていたら足さない（離れた所の言葉として出てしまう）
LOST_JOIN_SEC = 1.0


def lost_content(text, near: str) -> str:
    """外した字幕 text の言葉のうち、相づち（`omit_standalone_words`）でも、近くの字幕の文 near にある言葉
    （相手の言葉をなぞった「オリンピック はい」）でもないもの。LOST_MIN_CHARS 字以上なら、言った言葉が
    字幕から消えている（`_join_lost`・品質ゲートの欠落）。"""
    try:
        from subtitle_engine.text_formatter import is_standalone_omittable, _omit_words
        aizuchi = _omit_words("omit_standalone_words")
    except Exception:  # 一覧が読めなければ相づちも言葉に数える
        is_standalone_omittable, aizuchi = None, []
    near = re.sub(r"\s", "", near or "")
    words = [w for w in re.split(r"[\s、。，．,.！？!?「」『』]+", str(text or "")) if w]
    return "".join(w for w in words if not (aizuchi and is_standalone_omittable(w, aizuchi)) and w not in near)


def _near_text(items: list[dict], a: float, b: float) -> str:
    """a〜b 秒の前後 LOST_ECHO_SEC の中に出る字幕の文。"""
    return "".join(str(s.get("text") or "") for s in items
                   if not s.get("_merged") and float(s["end"]) >= a - LOST_ECHO_SEC
                   and float(s["start"]) <= b + LOST_ECHO_SEC)


def _join_lost(items: list[dict], given: list[dict], lost: list[tuple[int, str]], cut_points: list[float],
               max_chars: int | None = None, max_lines: int | None = None) -> tuple[list[tuple[int, str]], int]:
    """外す字幕（lost: given の番号と理由）のうち言葉のあるもの（`lost_content`）を、隣の字幕に行として
    足す（時刻は動かさない）。返り値は (足せなかった分, 足した数)。

    置き場所の無い字幕は時刻の取り合いに加えずに外すので、認識が拾えない言葉が字幕から消えていた
    （12分12秒: 聞き手の「黒子ですよ」の声に、次の字幕の頭の字が張り付いた・41分59秒「思います」も同じ形）。
    相づちだけ・隣の字幕の繰り返し・短い声・映像の後ろの字幕は足さない。声の拾えない字幕をカット点のそばに
    配ったときは、カットで声が消えた言葉とみなし、理由を `cut` にして残す。足す先は同じ区間で LOST_JOIN_SEC 秒より
    近い隣の字幕（並びは元の字幕の順）で、1枚（max_lines 行）に収まる方。次の字幕を先に見る: 足した行は次の字幕と
    一緒に、言った後に出る（前の字幕に足すと、言う前から出る）。
    """
    if max_chars is None or max_lines is None:
        max_chars, max_lines = _caption_limits()
    live = sorted((s for s in items if not s.get("_merged") and s.get("_sync_index") is not None),
                  key=lambda s: s["_sync_index"])
    left, joined = [], 0
    for k, why in lost:
        s = given[k]
        a, b = float(s.get("start", 0)), float(s.get("end", 0))
        if (why != "past_end" and _unheard(s)
                and any(a - LOST_CUT_SEC <= c <= b + LOST_CUT_SEC for c in cut_points)):
            left.append((k, "cut"))
            continue
        if why == "past_end" or len(lost_content(s.get("text"), _near_text(live, a, b))) < LOST_MIN_CHARS:
            left.append((k, why))
            continue
        zone = _zone(s)
        before = [o for o in live if _zone(o) == zone and o["_sync_index"] < k]
        after = [o for o in live if _zone(o) == zone and o["_sync_index"] > k]
        cands = ([(after[0], False)] if after and float(after[0]["start"]) - b <= LOST_JOIN_SEC else []) + (
            [(before[-1], True)] if before and a - float(before[-1]["end"]) <= LOST_JOIN_SEC else [])
        for o, first in cands:
            pair = (o, s) if first else (s, o)
            p0, p1 = str(pair[0].get("text", "")), str(pair[1].get("text", ""))
            one = _as_one_caption(p0, p1, max_chars, max_lines, _flat(pair[0]), _flat(pair[1]))
            if one is not None:
                o["text"], o["_break_punct"] = one, one == f"{p0}\n{p1}" or _breaks_at_space(
                    f"{_flat(pair[0])}\u3000{_flat(pair[1])}", one)
                if first:
                    o["_ends_punct"] = s.get("_ends_punct", False)
                joined += 1
                break
        else:
            left.append((k, why))
    return left, joined


def _gone(s: dict, reason: str) -> dict:
    """外した字幕の記録（時刻合わせの前の時刻・本文・理由）。品質ゲートが字幕にしなかった発話として数える。"""
    return {"start": round(float(s.get("start", 0)), 3), "end": round(float(s.get("end", 0)), 3),
            "text": s.get("text", ""), "reason": reason}


def _drop_squeezed(items: list[dict]) -> int:
    """区間（`_zone`）に入る隙が無く、1フレームも出ない字幕は出さない（隣ともまとめられなかった）。"""
    dropped = 0
    for s in items:
        if not s.get("_merged") and float(s["end"]) - float(s["start"]) < VIDEO_FRAME:
            s["_merged"], s["_gone"] = True, "squeezed"
            dropped += 1
    return dropped


def _drop_past_end(items: list[dict], end: float) -> int:
    """映像の終わりより後ろの字幕は出さず、終わりをまたぐ字幕は終わりで切る。

    締めの字幕が、前の字幕の時刻合わせに押されて尺の外に出た（37分45秒・2026-10-06 実測）。
    """
    if not end or end <= 0:
        return 0
    dropped = 0
    for s in items:
        if s.get("_merged"):
            continue
        if s["start"] >= end - MIN_STEP_SEC:
            s["_merged"], s["_gone"] = True, "past_end"
            dropped += 1
        elif s["end"] > end:
            s["end"] = round(end, 3)
    return dropped


def _word_edges(speech: SpeechMap, a: float, b: float) -> tuple[float, float]:
    """分けた所の手前の字を話し終えた見積もり a と、後ろの頭の字を話し始めた見積もり b を、声の切れ目まで広げる。

    a の後ろ・b の前に続く声が SPLIT_WORD_EDGE_SEC 以内に切れる・始まるなら、そこまではその字の声。
    a と b が同じ声の中（息継ぎ無しに続けて話した所）なら動かさない。
    """
    pairs = list(zip(speech.onsets, speech.offsets))
    at_a = next(((on, off) for on, off in pairs if on <= a < off), None)
    at_b = next(((on, off) for on, off in pairs if on < b <= off), None)
    if at_a is not None and at_a == at_b:
        return a, b
    if at_a is not None and at_a[1] - a <= SPLIT_WORD_EDGE_SEC:
        a = at_a[1]
    if at_b is not None and b - at_b[0] <= SPLIT_WORD_EDGE_SEC:
        b = at_b[0]
    return a, b


def _split_in_two(s: dict, speech: SpeechMap) -> list[dict] | None:
    """2行の字幕を、話した時刻（音声認識）で2枚に分けた形（合わせる前の時刻）。分けられなければ None。

    分ける所は改行か、改行より切れ目の良い（`text_formatter._break_score` が高い）文節の切れ目。改行が
    「を」の後ろでも「、」や節の終わりで分ける（42回目の 1分22秒: 改行で分けて「私 小学校3年生の時に
    お習字を」|「スタートしたんですけど その当時僕が」と、「お習字を｜スタートした」が別の字幕になった）。
    改行以外は「て・は・たら」くらい良い所（2点以上）だけ。同点なら改行、次に話している時間の真ん中に
    近い所。分けた2枚は整形と同じ折り方で組み直す（2行のこともある）。
    1枚目は分けた所の手前の字を話し終わるまで、2枚目は後ろの頭の字を話し始めた所から。後ろの頭の字を
    認識が拾えなくても SPLIT_HEAD_SKIP 字までなら、次に拾えた字から1字 SPLIT_CHAR_SEC 秒でさかのぼる
    （頭を拾えなかった字幕と同じく、後で拾えた字の前の話し始めに寄る）。2枚の間に字幕に無い声がある
    （SPLIT_MAX_UNSAID_SEC 超え）・分けた1枚が読めないほど短い・2字以下になる所では分けない。
    """
    from subtitle_engine import aligner
    from subtitle_engine import text_formatter as tf
    lines = str(s.get("text") or "").split("\n")
    if len(lines) != 2 or not s.get("_asr"):
        return None
    marks = [(int(c), float(t)) for c, t in s.get("_asr_marks") or ()]
    max_chars, max_lines = _caption_limits()
    flat = _flat(s)
    marked = flat.replace("\u3000", "、")  # 句読点を外した跡を「、」に戻して切れ目の良さを測る
    line_pos = len(flat) - len(lines[1])
    # 分けてよい所と、そこで切る良さ（文節の切れ目は前後の文節で測る）
    cuts, acc = {line_pos: tf._break_score(marked[:line_pos], marked[line_pos:])}, 0
    phrases = tf._phrases(marked, max_chars)
    for i, ph in enumerate(phrases[:-1], start=1):
        acc += len(ph)
        score = tf._break_score(ph, phrases[i])
        if acc == line_pos or score >= 2:
            cuts[acc] = score
    mid = (float(s["start"]) + float(s["end"])) / 2
    best = None
    for pos, score in sorted(cuts.items()):
        head_text, tail_text = flat[:pos].rstrip("\u3000 "), flat[pos:].lstrip("\u3000 ")
        if min(len(head_text.replace("\u3000", "")), len(tail_text.replace("\u3000", ""))) <= 2:
            continue
        n = len(aligner._norm_text(flat[:pos]))
        head = [(c, t) for c, t in marks if c < n]
        tail = [(c, t) for c, t in marks if c >= n]
        if not head or not tail or tail[0][0] - n > SPLIT_HEAD_SKIP:
            continue
        c2, t2 = tail[0]
        second_on = t2 - (c2 - n) * SPLIT_CHAR_SEC
        first_off = min(head[-1][1] + (n - head[-1][0]) * SPLIT_CHAR_SEC, second_on)
        first_off, second_on = _word_edges(speech, first_off, second_on)
        if (first_off - float(s["start"]) < SPLIT_MIN_PART_SEC
                or float(s["end"]) - second_on < SPLIT_MIN_PART_SEC
                or _speaking_time(speech, first_off, second_on) > SPLIT_MAX_UNSAID_SEC):
            continue
        if pos == line_pos:
            first_text, second_text = lines
        else:
            first_text = _wrap_one(head_text, max_chars, max_lines)
            second_text = _wrap_one(tail_text, max_chars, max_lines)
            if not first_text or not second_text:
                continue
        key = (score, pos == line_pos, -abs((first_off + second_on) / 2 - mid))
        if best is None or key > best[0]:
            best = (key, pos, n, head, tail, first_off, second_on, first_text, second_text)
    if best is None:
        return None
    _, pos, n, head, tail, first_off, second_on, first_text, second_text = best
    first = dict(s, text=first_text, end=round(first_off, 3), _asr_marks=head, _asr_heard=len(head),
                 _break_punct=_breaks_at_space(flat[:pos].rstrip("\u3000 "), first_text),
                 _ends_punct=flat[pos - 1] in "\u3000 ")
    # 字幕から外した言いよどみの声（`_asr_tail`）は字幕の尻のものなので、2枚目に残す
    first.pop("_asr_tail", None)
    second = dict(s, text=second_text, start=round(second_on, 3), _asr_first=round(tail[0][1], 3),
                  _asr_marks=[(c - n, t) for c, t in tail], _asr_heard=len(tail),
                  _break_punct=_breaks_at_space(flat[pos:].lstrip("\u3000 "), second_text))
    return [first, second]


def _split_long(segments: list[dict], result: list[dict], max_sec: float,
                speech: SpeechMap) -> tuple[list[dict], int]:
    """合わせた結果で max_sec より長く出る2行の字幕を、合わせる前の字幕（segments）の方で2枚に分ける。

    40回目の 1分22秒: 「私 小学校3年生の時に お習字を/スタートしたんですけど その当時僕が」が
    10.2 秒出て、2行目は話す 6 秒前から見えていた（全編で 7 秒を超える字幕が 22 枚）。
    隣とまとめた・切れ目を動かした字幕（文が変わったもの）は分けない。返り値は (字幕, 分けた枚数)。
    """
    if not max_sec or max_sec <= 0:
        return segments, 0
    long = {s["_sync_index"] for s in result
            if float(s["end"]) - float(s["start"]) > max_sec
            and s.get("text") == segments[s["_sync_index"]].get("text")}
    out, split = [], 0
    for k, s in enumerate(segments):
        parts = _split_in_two(s, speech) if k in long else None
        if parts:
            out.extend(parts)
            split += 1
        else:
            out.append(s)
    return out, split


def align_segments(segments: list[dict], speech: SpeechMap,
                   cut_points: list[float] | None = None,
                   rules: dict | None = None) -> tuple[list[dict], dict]:
    """字幕（出力の時間軸の start/end）を話し始め・話し終わりに合わせる。

    返り値は (直した字幕, 集計)。字幕の順番は変えない。読めないほど短い字幕は隣とまとめ、
    長く出続ける2行の字幕（`max_display_sec` 超え）は話の切れ目で2枚に分けて合わせ直す。
    """
    r = dict(DEFAULT_TIMING)
    r.update(rules or {})
    result, stats = _align_once(segments, speech, cut_points, r)
    segments, split = _split_long(segments, result, r.get("max_display_sec", 0.0), speech)
    if split:
        result, stats = _align_once(segments, speech, cut_points, r)
        logger.info(f"✂️ {r['max_display_sec']:g}秒より長く出る2行の字幕を、話の切れ目で分けました: {split}枚")
    stats["split_long"] = split
    for s in result:
        s.pop("_sync_index", None)
    return result, stats


def _align_once(segments: list[dict], speech: SpeechMap, cut_points: list[float] | None,
                r: dict) -> tuple[list[dict], dict]:
    """`align_segments` の1回分。返す字幕には、元の字幕の番号（`_sync_index`）を付けておく。"""
    cut_points = sorted(cut_points or [])
    # 声が聞こえず、前後の聞こえた字幕の間に入る隙も無い字幕は、時刻の取り合いに加えない。
    # 出しても一瞬で消えるうえ、聞こえた字幕の時間を削る（15分26秒・重なって話した「ファンが」が
    # 「そういう中でね…」を 0.33 秒で消させた・2026-10-06 実測）
    heard_or_roomy = [dict(s, _sync_index=k) for k, s in enumerate(segments)
                      if not (_unheard(s) and float(s.get("end", 0)) - float(s.get("start", 0)) < FLASH_SEC)]
    kept = {s["_sync_index"] for s in heard_or_roomy}
    lost = [(k, "no_room") for k in range(len(segments)) if k not in kept]
    no_room = len(lost)
    items = sorted(heard_or_roomy, key=lambda s: float(s.get("start", 0)))
    n = len(items)
    snapped_in = snapped_out = 0

    # 0. 1つの発話を分けた字幕は、時刻を「喋っている時間」で配り直す（間には文字を置かない）
    redistributed = _distribute_by_speech(items, speech)

    # 1. 話し始め・話し終わりに寄せる。同じ話し始めを2枚で取り合わない
    # 音声認識で時刻を取った字幕の近くの話し始めは、その字幕のもの。手前の（認識で拾えなかった）
    # 字幕には取らせない（44 秒の「こんにちは」が「もう初回ね」の話し始めを取り、0.4 秒遅れた）
    claimed = [float("inf")] * (n + 1)
    for k in range(n - 1, -1, -1):
        claimed[k] = (float(items[k]["start"]) - ASR_SNAP_BEFORE_SEC
                      if items[k].get("_asr") else claimed[k + 1])
    onsets, offsets = [], []
    for k, s in enumerate(items):
        a, b = float(s["start"]), float(s["end"])
        # 話し始め・話し終わりは、字幕の言葉が残った区間の中から選ぶ（カットの向こうは別の場面の声）
        zone = _zone(s)
        zone_onsets = _within(speech.onsets, zone)
        # 前の字幕との間を空けるのは同じ区間のときだけ。カットの手前の字幕は区間の終わりまでしか出ない
        floor = onsets[-1] + MIN_STEP_SEC if onsets and _zone(items[k - 1]) == zone else -1.0
        first = float(s.get("_asr_first", a)) if s.get("_asr") else a
        if s.get("_asr") and first - a > 0.05:
            # 頭の何文字かを認識が拾えず、出だしを外挿している。拾えた最初の文字の直前の
            # 話し始めが出だし（35 秒の「デザイン書道の」が前の文の終わりの 34.8 秒に出た）。
            # ただし拾えなかった頭を話せる時間は残す。頭が長いと、直前の話し始めは文の途中
            # （17分58秒の「ね あわよくば その98%の」13字を飛ばして「の中から」で出た・2026-10-07）。
            # 認識の字の時刻は早めに出ることがあるので、その分は待つ（短い頭は今までどおり）
            head = (s.get("_asr_marks") or [(0, first)])[0][0]
            latest = first + 0.05 - max(0.0, head / HEAD_MAX_CPS - HEAD_EARLY_SEC)
            lo = a - ASR_SNAP_BEFORE_SEC
            prev_heard = _last_heard(items[k - 1]) if k > 0 else None
            if head >= HEAD_LOOKBACK_MIN_CHARS and prev_heard is not None:
                lo = min(lo, max(prev_heard + HEAD_AFTER_PREV_SEC, first - head / HEAD_MIN_CPS))
            near = [o for o in zone_onsets if o >= floor and lo <= o <= latest]
            on = None
            if near:
                # 頭を毎秒 HEAD_MAX_CPS 字で話せる、いちばん遅い話し始め。どこからでも足りなければ、
                # 前の字幕の声の後ろでいちばん早い話し始め（28分40秒・31回目）
                roomy = [o for o in near if _speaking_time(speech, o, first) >= head / HEAD_MAX_CPS]
                on = max(roomy) if roomy else min(near)
        elif s.get("_asr"):
            on = _nearest_biased([o for o in zone_onsets if o >= floor], a,
                                 ASR_SNAP_BEFORE_SEC, ASR_SNAP_AFTER_SEC)
        else:
            # 文字起こしの時刻は早めに出がち（実測で早すぎ 163 件・遅すぎ 23 件）なので、後ろ側を広く探す
            on = _nearest_biased([o for o in zone_onsets if floor <= o < claimed[k + 1]], a,
                                 r["snap_window_sec"] * 0.6, r["snap_window_sec"] * 1.25)
        off = _nearest(_within(speech.offsets, zone), b, r["snap_window_sec"])
        snapped_in += on is not None
        snapped_out += off is not None
        on = max(a, floor) if on is None else on
        if off is None:
            # 推定の終わりが長い間の中なら、話し終わりはその間の入り口
            off = _pause_start(b, speech)
        off = b if off is None else off
        if off <= on:  # 寄せた結果が逆転したら話し始めから推定の長さだけ
            off = on + max(b - a, MIN_STEP_SEC)
        onsets.append(on)
        offsets.append(off)

    # 2. 見せ方の規則
    ins = []
    for i in range(n):
        t = onsets[i] + r["lead_in_sec"]
        # 間の中で出さない。話し始めを待たせる字幕は「早すぎ」に見える。
        # ただし間の後ろの話し始めが次の（認識で時刻を取った）字幕のものなら送らない。送ると次の字幕と
        # ぶつかって一瞬で消え、次の字幕も遅れる（21分28秒の「ふうに思ってますね」・後ろ半分はカットで消えた）
        resume = _pause_end(t, speech)
        z0, z1 = _zone(items[i])
        if resume is not None and resume < claimed[i + 1] and resume < z1:
            onsets[i] = resume
            t = resume + r["lead_in_sec"]
        cp = _in_cut_zone(t, cut_points, r["cut_zone_sec"])
        if cp is not None:
            t = cp if t < cp else t
        if ins and t < ins[-1] + MIN_STEP_SEC and _zone(items[i - 1]) == (z0, z1):
            t = ins[-1] + MIN_STEP_SEC
        # 区間の外には出さない。入る隙が無ければ区間の終わりに置き、後で隣とまとめるか外す
        ins.append(min(max(t, z0), z1))
    outs = []
    for i in range(n):
        out = offsets[i] + r["linger_sec"]
        if i + 1 < n:
            nxt_on, nxt_in = onsets[i + 1], ins[i + 1]
            out = min(out, nxt_on - r["end_before_next_sec"])
            # 間がほとんど無い（つながった発話・1文を分けた字幕）は途切れさせずに続ける
            if out < offsets[i] or nxt_in - out < r["chain_gap_sec"] and nxt_in - offsets[i] < r["chain_gap_sec"]:
                out = nxt_in - 2 * VIDEO_FRAME
        out = max(out, ins[i] + r["min_display_sec"])
        if i + 1 < n:
            out = min(out, ins[i + 1] - 2 * VIDEO_FRAME)
        cp = _in_cut_zone(out, cut_points, r["cut_zone_sec"])
        if cp is not None and cp > ins[i] + 0.3:
            out = cp
        # 話し終わりの後の余韻も、カットの向こう（次の場面）には残さない
        outs.append(min(out, _zone(items[i])[1]))

    result = []
    for s, a, b in zip(items, ins, outs):
        s["start"], s["end"] = round(a, 3), round(min(max(b, a + 0.2), max(_zone(s)[1], a)), 3)
        result.append(s)
    past_end = _drop_past_end(result, speech.duration)
    merged = _merge_flashes(result, r["min_display_sec"])
    resplit = _resplit_flashes(result, r["min_display_sec"])
    roomed = _give_unheard_room(result, segments, r["min_display_sec"])
    dropped = (_drop_unheard_flashes(result, r["min_display_sec"]) + _drop_squeezed(result)
               + past_end + no_room)
    lost += [(s["_sync_index"], s["_gone"]) for s in result if s.get("_gone")]
    lost, joined = _join_lost(result, segments, lost, cut_points)
    if joined:
        logger.info(f"🧷 置き場所の無い字幕を隣の字幕に行として足しました: {joined}枚")
    stats = {"captions": n, "snapped_in": snapped_in, "snapped_out": snapped_out,
             "redistributed": redistributed, "merged": merged, "resplit": resplit,
             "dropped": dropped - joined, "unheard_roomed": roomed, "joined": joined,
             "gone": sorted((_gone(segments[k], why) for k, why in lost), key=lambda g: g["start"])}
    result = [s for s in result if not s.get("_merged")]
    logger.info(f"🎯 字幕の出だし・終わりを音声に合わせました: {n}枚, 話し始めに寄せた {snapped_in}, "
                f"話し終わりに寄せた {snapped_out}")
    return result, stats


MIN_GAP_BEFORE = 0.3


def measure_sync(segments: list[dict], speech: SpeechMap, *, early_sec: float = 0.1,
                 late_sec: float = 0.6) -> dict:
    """間（MIN_GAP_BEFORE 以上）の後の話し始めに、字幕がどう出ているか（品質ゲート用）。

    - 早すぎ: 字幕が間の中で出て、話し始めまで early_sec より長く待たせる
    - 遅すぎ: 話し始めから late_sec 経っても、新しい字幕が出ていない
      （前の字幕が出たまま話が続いている場合は数えない）
    話し続けの途中で分けた字幕は、どこが話し始めか音声から決まらないので数えない。
    """
    pauses = [(speech.offsets[i - 1], on) for i, on in enumerate(speech.onsets)
              if i > 0 and on - speech.offsets[i - 1] >= MIN_GAP_BEFORE]
    spans = []
    for s in segments:
        try:
            spans.append((float(s["start"]), float(s["end"])))
        except (KeyError, TypeError, ValueError):
            continue
    spans.sort()
    starts = [a for a, _ in spans]
    early = late = 0
    worst: list[tuple[float, float]] = []
    for p0, on in pauses:
        lo = int(np.searchsorted(starts, p0))
        hi = int(np.searchsorted(starts, on + late_sec))
        inside = starts[lo:hi]
        if not inside:
            # 新しい字幕が出ていない。前の字幕が出たままなら話の続き
            showing = any(a <= on + late_sec <= b for a, b in spans)
            if not showing and any(a > on for a in starts[hi:hi + 1]):
                late += 1
                worst.append((on, starts[hi] - on))
            continue
        first = inside[0]
        if first < on - early_sec:
            early += 1
            worst.append((on, first - on))
    checked = len(pauses)
    worst.sort(key=lambda x: -abs(x[1]))
    off = early + late
    return {"checked": checked, "early": early, "late": late,
            "off_ratio": round(off / checked, 3) if checked else 0.0,
            "worst": [(round(a, 2), round(d, 2)) for a, d in worst[:5]]}
