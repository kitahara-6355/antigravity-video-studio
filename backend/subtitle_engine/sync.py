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
}

# 隣り合う字幕の出だしの最小の間隔（同じ話し始めに2枚が寄るのを防ぐ）
MIN_STEP_SEC = 0.4
# 音声認識で時刻を取った字幕は、近くの話し始めにだけ寄せる。認識の時刻は文字の位置
# そのものなので、遠くの話し始めは別の句（51 秒で 1.3 秒遅れた・2026-10-06 実測）
ASR_SNAP_BEFORE_SEC = 0.25
ASR_SNAP_AFTER_SEC = 0.4
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


def _chars(seg: dict) -> int:
    return max(1, len("".join(str(seg.get("text") or "").split())))


def _active(speech: SpeechMap, a: float, b: float) -> list[tuple[float, float]]:
    out = []
    for on, off in zip(speech.onsets, speech.offsets):
        lo, hi = max(on, a), min(off, b)
        if hi > lo:
            out.append((lo, hi))
    return out


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


def _caption_limits() -> tuple[int, int]:
    """1行の文字数と行数（テンプレート。読めなければ 18 字・2 行）。"""
    try:
        from template_config import template_config
        return (int(template_config.get_max_chars_per_line()),
                int(template_config.get_subtitle_rules().get("max_lines", 2)))
    except Exception:
        return 18, 2


def _as_one_caption(first: str, second: str, max_chars: int, max_lines: int) -> str | None:
    """2枚の字幕を続けて1枚（max_lines 行・1行 max_chars 字）に組み直した形。入らなければ None。"""
    if "\n" not in first and "\n" not in second and max_lines >= 2:
        return f"{first}\n{second}"
    flat = f"{first}\u3000{second}".replace("\n", "")
    try:
        from subtitle_engine import text_formatter as tf
        caps = tf.split_into_captions(flat, max_chars, max_lines)
    except Exception:  # 組み直せなくても字幕は出す
        caps = []
    if caps:
        return caps[0] if len(caps) == 1 else None
    if len(flat) > max_chars * max_lines:
        return None
    return "\n".join(flat[k:k + max_chars] for k in range(0, len(flat), max_chars))


def _merge_flashes(items: list[dict], min_display: float, max_chars: int | None = None,
                   max_lines: int | None = None) -> int:
    """出る時間が FLASH_SEC 未満の字幕を、隣の字幕とまとめて1枚にする（読めない字幕を作らない）。

    隣が1行なら行として足す。隣が2行でも、続けて1枚に組み直せるならそうする
    （2分36秒の「もう強烈な」が 0.49 秒で消えた・2026-10-06 実測）。
    詰まっている側（すき間が短い側）に寄せる。
    """
    if max_chars is None or max_lines is None:
        max_chars, max_lines = _caption_limits()
    merged = 0
    for i, s in enumerate(items):
        if s.get("_merged") or s["end"] - s["start"] >= FLASH_SEC:
            continue
        cands = []
        for j in (i - 1, i + 1):
            if 0 <= j < len(items) and not items[j].get("_merged"):
                o = items[j]
                pair = (o, s) if j < i else (s, o)
                text = _as_one_caption(str(pair[0].get("text", "")), str(pair[1].get("text", "")),
                                       max_chars, max_lines)
                if text is not None:
                    gap = s["start"] - o["end"] if j < i else o["start"] - s["end"]
                    cands.append((gap, j, text))
        if not cands:
            continue
        _, j, text = min(cands, key=lambda c: (c[0], c[1]))
        o = items[j]
        o["text"] = text
        if j < i:
            o["end"] = max(o["end"], s["end"])
        else:
            o["start"] = min(o["start"], s["start"])
        s["_merged"] = True
        merged += 1
    return merged


def _drop_unheard_flashes(items: list[dict]) -> int:
    """隣とまとめられなかった一瞬の字幕のうち、音声認識に声が無いものを出さない。

    カットで声が消えた言葉が、カット点に 0.3 秒だけ残る（9分39秒の「いたんだよね」・
    2026-10-06 実測）。読めず、言葉も聞こえないので出す意味が無い。認識に声がある字幕は残す。
    """
    dropped = 0
    for s in items:
        if s.get("_merged") or s["end"] - s["start"] >= FLASH_SEC:
            continue
        if s.get("_asr_interp") and not s.get("_asr"):
            s["_merged"] = True
            dropped += 1
    return dropped


def align_segments(segments: list[dict], speech: SpeechMap,
                   cut_points: list[float] | None = None,
                   rules: dict | None = None) -> tuple[list[dict], dict]:
    """字幕（出力の時間軸の start/end）を話し始め・話し終わりに合わせる。

    返り値は (直した字幕, 集計)。字幕の順番・文字は変えない。
    """
    r = dict(DEFAULT_TIMING)
    r.update(rules or {})
    cut_points = sorted(cut_points or [])
    items = sorted((dict(s) for s in segments), key=lambda s: float(s.get("start", 0)))
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
        floor = onsets[-1] + MIN_STEP_SEC if onsets else -1.0
        first = float(s.get("_asr_first", a)) if s.get("_asr") else a
        if s.get("_asr") and first - a > 0.05:
            # 頭の何文字かを認識が拾えず、出だしを外挿している。拾えた最初の文字の直前の
            # 話し始めが出だし（35 秒の「デザイン書道の」が前の文の終わりの 34.8 秒に出た）
            near = [o for o in speech.onsets
                    if o >= floor and a - ASR_SNAP_BEFORE_SEC <= o <= first + 0.05]
            on = max(near) if near else None
        elif s.get("_asr"):
            on = _nearest_biased([o for o in speech.onsets if o >= floor], a,
                                 ASR_SNAP_BEFORE_SEC, ASR_SNAP_AFTER_SEC)
        else:
            # 文字起こしの時刻は早めに出がち（実測で早すぎ 163 件・遅すぎ 23 件）なので、後ろ側を広く探す
            on = _nearest_biased([o for o in speech.onsets if floor <= o < claimed[k + 1]], a,
                                 r["snap_window_sec"] * 0.6, r["snap_window_sec"] * 1.25)
        off = _nearest(speech.offsets, b, r["snap_window_sec"])
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
        # 間の中で出さない。話し始めを待たせる字幕は「早すぎ」に見える
        resume = _pause_end(t, speech)
        if resume is not None:
            onsets[i] = resume
            t = resume + r["lead_in_sec"]
        cp = _in_cut_zone(t, cut_points, r["cut_zone_sec"])
        if cp is not None:
            t = cp if t < cp else t
        if ins and t < ins[-1] + MIN_STEP_SEC:
            t = ins[-1] + MIN_STEP_SEC
        ins.append(t)
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
        outs.append(out)

    result = []
    for s, a, b in zip(items, ins, outs):
        s["start"], s["end"] = round(a, 3), round(max(b, a + 0.2), 3)
        result.append(s)
    merged = _merge_flashes(result, r["min_display_sec"])
    dropped = _drop_unheard_flashes(result)
    stats = {"captions": n, "snapped_in": snapped_in, "snapped_out": snapped_out,
             "redistributed": redistributed, "merged": merged, "dropped": dropped}
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
