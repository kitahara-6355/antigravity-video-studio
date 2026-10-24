"""声の聞こえない所の字幕を外し、その区間を「静かな区間」に入れる（2026-10-23 上野さんの回）。

2本目の対談の揮毫の場面（素材 13分36秒〜14分00秒）は、筆を動かしているだけで誰も話していない
（音量は -42dB 前後・電車の音だけ。音を 25dB 上げて聞き直しても「話し声なし」）。
それでも Gemini は「そうですね　ちょっとこういう感じなんですよ」「いやもうここはちょっとやっぱり
直したほうがいいですね」と**ありもしない台詞**を書き、21秒出る字幕になった。
さらにその区間が「文字の薄い区間」に数えられ、品質ゲートが字幕の欠落として不合格（77）にした。

見分け方は2つの耳の一致:

1. 手元の音声認識（ReazonSpeech・`aligner.tokens_for`）が `MIN_SEC` 秒以上、1字も聞き取っていない
2. その区間の平均の音量が `QUIET_DB` より小さい（話し声は -30dB 前後、部屋の音は -40dB 台）

両方を満たす区間を「声の無い区間」とし、その中に収まる字幕は出さない（外した字幕は記録に残す）。
区間は書いている場面と同じ扱いで、欠落の数え方から除く（`coverage.measure(exclude=...)`）。
認識が使えないとき（部品が無い）は何もしない。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

# これより長く手元の認識が黙っていたら、声の無い区間の候補
MIN_SEC = 8.0
# 平均の音量がこれより小さければ、話し声は無い
QUIET_DB = -36.0
# 候補の両端は、最後と最初に聞き取った字からこれだけ離す（言い終わり・言い始めを削らない）
EDGE_SEC = 0.5
# 字幕がこれだけはみ出していても、区間の中と見る
SLACK_SEC = 0.5


def silent_gaps(tokens: list[tuple[str, float]], duration: float, min_sec: float = MIN_SEC
                ) -> list[tuple[float, float]]:
    """手元の認識が `min_sec` 秒以上何も聞き取っていない区間。"""
    times = sorted(t for _, t in tokens)
    edges = [-EDGE_SEC] + times + [duration + EDGE_SEC]
    gaps = []
    for a, b in zip(edges, edges[1:]):
        lo, hi = max(0.0, a + EDGE_SEC), min(duration, b - EDGE_SEC)
        if hi - lo >= min_sec:
            gaps.append((round(lo, 2), round(hi, 2)))
    return gaps


def mean_db(media: str | Path, a: float, b: float) -> float | None:
    """区間の平均の音量（ffmpeg volumedetect・ローカル）。測れなければ None。"""
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}",
                           "-i", str(media), "-vn", "-af", "volumedetect", "-f", "null", "-"],
                          capture_output=True, text=True)
    m = re.search(r"mean_volume:\s*(-?[\d.]+|-inf) dB", proc.stderr)
    if not m:
        return None
    return float("-inf") if m.group(1) == "-inf" else float(m.group(1))


def voiceless_spans(media: str | Path, tokens: list[tuple[str, float]] | None, duration: float,
                    measure=mean_db) -> list[tuple[float, float]]:
    """2つの耳がそろって「声が無い」と言う区間。認識が無ければ空。"""
    if not tokens:
        return []
    out = []
    for a, b in silent_gaps(tokens, duration):
        db = measure(media, a, b)
        if db is not None and db < QUIET_DB:
            out.append((a, b))
    return out


def drop_inside(segments: list[dict], spans: list[tuple[float, float]]) -> tuple[list[dict], list[dict]]:
    """区間の中に収まる字幕を外す。返り値は (残す, 外した)。"""
    keep, gone = [], []
    for s in segments:
        try:
            a, b = float(s["start"]), float(s["end"])
        except (KeyError, TypeError, ValueError):
            keep.append(s)
            continue
        if any(lo - SLACK_SEC <= a and b <= hi + SLACK_SEC for lo, hi in spans):
            gone.append(s)
        else:
            keep.append(s)
    return keep, gone


# --- 撮り始めのカウントダウン（2026-10-23 上野さんの回: 出だしに「4 3 2」が字幕で出た） ---

# 撮り始めからこの秒数のうちの、数字だけの字幕をカウントダウンと見る
COUNTDOWN_SEC = 15.0
_COUNT = set("0123456789０１２３４５６７８９一二三四五六七八九十零 　、。,.!！?？・ー")


def is_countdown(text: str) -> bool:
    body = "".join(ch for ch in str(text or "") if ch != "\n")
    return bool(body.strip()) and all(ch in _COUNT for ch in body) and any(not ch.isspace() for ch in body)


def drop_countdowns(segments: list[dict], starts: list[float]) -> tuple[list[dict], list[dict]]:
    """撮り始め（素材の頭と、つないだ各ファイルの頭）から `COUNTDOWN_SEC` 秒以内の、数字だけの字幕を外す。

    字幕の無い所は書き出しで切られるので、出だしが話し始めちょうどになる（編集の決まり S-出だし）。"""
    heads = sorted({0.0, *(float(s) for s in starts)})
    keep, gone = [], []
    for s in segments:
        try:
            a = float(s["start"])
        except (KeyError, TypeError, ValueError):
            keep.append(s)
            continue
        near = any(h <= a < h + COUNTDOWN_SEC for h in heads)
        (gone if near and is_countdown(s.get("text", "")) else keep).append(s)
    return keep, gone
