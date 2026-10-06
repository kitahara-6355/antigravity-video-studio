"""字幕の欠落を、音声の「喋っている時間」と突き合わせて見つける。

2026-10-06 ユーザー指摘で作った。Gemini の文字起こしが 120 秒チャンクの中で
約 30 秒の発話を丸ごと落とし、残った1文に 54 秒分の時刻を付けていた。
字幕の無い区間は SmartCut が「不要」として動画から消すので、
**欠落は字幕の抜けではなく、発話そのものの消失になる。**
それでも品質ゲートは 86 点を出していた（欠落を数える項目が無かった）。

見るものは2つ:

1. **覆われていない発話** — 喋っているのに、どの字幕の時間にも入っていない秒数
2. **薄い区間** — 字幕の時間には入っているが、喋っている長さに比べて文字が極端に少ない区間
   （1文に 54 秒が付いたような場合。1 は 0 秒になるので 2 が要る）

喋っている時間は ffmpeg の silencedetect の補集合で取る（ローカル・無料）。
"""
from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

NOISE_DB = -35
MIN_SILENCE_SEC = 0.7
WINDOW_SEC = 30.0
# 日本語の会話は 1 秒に 6〜8 文字ほど。3 を切る区間は、ほぼ確実に何かが抜けている
SPARSE_CPS = 3.0
# 喋っている時間がこれより短い区間は、文字数の比で判定しない（相づちだけの区間など）
MIN_SPEECH_IN_WINDOW = 8.0
# 字幕の前後この秒数までの発話は覆われているとみなす（時刻の小さなずれを咎めない）
TOLERANCE_SEC = 1.0
# 覆われていない発話の割合がこれを超えたら欠落とみなす
MAX_UNCOVERED_RATIO = 0.02


@dataclass
class CoverageReport:
    duration: float
    speech_sec: float
    uncovered_sec: float
    uncovered: list[tuple[float, float]] = field(default_factory=list)
    sparse: list[dict] = field(default_factory=list)

    @property
    def uncovered_ratio(self) -> float:
        return self.uncovered_sec / self.speech_sec if self.speech_sec > 0 else 0.0

    @property
    def has_gaps(self) -> bool:
        return self.uncovered_ratio > MAX_UNCOVERED_RATIO or bool(self.sparse)

    def to_dict(self) -> dict:
        return {
            "duration": round(self.duration, 2),
            "speech_sec": round(self.speech_sec, 2),
            "uncovered_sec": round(self.uncovered_sec, 2),
            "uncovered_ratio": round(self.uncovered_ratio, 4),
            "uncovered": [(round(a, 2), round(b, 2)) for a, b in self.uncovered],
            "sparse": self.sparse,
            "has_gaps": self.has_gaps,
        }

    def summary(self) -> str:
        parts = [f"覆われていない発話 {self.uncovered_sec:.0f}秒（{self.uncovered_ratio:.1%}）"]
        if self.sparse:
            parts.append("文字が薄い区間 " + ", ".join(_mmss(w["start"]) for w in self.sparse[:6])
                         + (" ほか" if len(self.sparse) > 6 else ""))
        return " / ".join(parts)


def _mmss(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"


def _probe_duration(path: str | Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True, timeout=60).stdout
    return float(out.strip())


def parse_silences(log: str) -> list[tuple[float, float | None]]:
    """silencedetect のログから (開始, 終了) を取り出す。末尾まで無音なら終了は None。"""
    out: list[tuple[float, float | None]] = []
    start = None
    for kind, value in re.findall(r"silence_(start|end): (-?[0-9.]+)", log):
        t = max(0.0, float(value))
        if kind == "start":
            start = t
        elif start is not None:
            out.append((start, t))
            start = None
    if start is not None:
        out.append((start, None))
    return out


def speech_from_silences(silences: list[tuple[float, float | None]],
                         duration: float) -> list[tuple[float, float]]:
    """無音区間の補集合（＝音がある区間）。"""
    speech = []
    cur = 0.0
    for a, b in silences:
        if a > cur:
            speech.append((cur, min(a, duration)))
        cur = duration if b is None else max(cur, b)
    if cur < duration:
        speech.append((cur, duration))
    return [(a, b) for a, b in speech if b - a > 0.05]


def speech_intervals(media: str | Path) -> tuple[list[tuple[float, float]], float]:
    """音がある区間と全体の長さ。ffmpeg が無い・読めないときは例外。"""
    duration = _probe_duration(media)
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(media), "-vn",
         "-af", f"silencedetect=noise={NOISE_DB}dB:d={MIN_SILENCE_SEC}", "-f", "null", "-"],
        capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0:
        raise RuntimeError(f"silencedetect に失敗: {proc.stderr[-300:]}")
    return speech_from_silences(parse_silences(proc.stderr), duration), duration


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _subtract(intervals: list[tuple[float, float]],
              cover: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out = []
    cover = sorted(cover)
    for a, b in intervals:
        cur = a
        for c0, c1 in cover:
            if c1 <= cur or c0 >= b:
                continue
            if c0 > cur:
                out.append((cur, c0))
            cur = max(cur, c1)
            if cur >= b:
                break
        if cur < b:
            out.append((cur, b))
    return [(a, b) for a, b in out if b - a > 0.05]


def _seg_chars(seg: dict) -> int:
    return len(str(seg.get("text") or "").replace("\n", "").strip())


def measure(segments: list[dict], speech: list[tuple[float, float]], duration: float,
            *, start_key: str = "start", end_key: str = "end",
            window: float = WINDOW_SEC) -> CoverageReport:
    """字幕（`start_key`/`end_key` の時間軸）が発話をどれだけ覆っているか。"""
    spans = []
    for s in segments:
        try:
            a, b = float(s.get(start_key)), float(s.get(end_key))
        except (TypeError, ValueError):
            continue
        if b > a and _seg_chars(s):
            spans.append((a, b, _seg_chars(s)))
    cover = [(a - TOLERANCE_SEC, b + TOLERANCE_SEC) for a, b, _ in spans]
    uncovered = _subtract(speech, cover)
    # 0.5 秒未満の切れ端（相づちを外した跡など）は数えない
    uncovered = [(a, b) for a, b in uncovered if b - a >= 0.5]

    sparse = []
    w0 = 0.0
    while w0 < duration:
        w1 = min(w0 + window, duration)
        talk = sum(_overlap(a, b, w0, w1) for a, b in speech)
        if talk >= MIN_SPEECH_IN_WINDOW:
            chars = sum(n * _overlap(a, b, w0, w1) / (b - a) for a, b, n in spans)
            cps = chars / talk
            if cps < SPARSE_CPS:
                sparse.append({"start": round(w0, 1), "end": round(w1, 1),
                               "speech_sec": round(talk, 1), "chars": round(chars),
                               "cps": round(cps, 2)})
        w0 = w1
    return CoverageReport(duration=duration,
                          speech_sec=sum(b - a for a, b in speech),
                          uncovered_sec=sum(b - a for a, b in uncovered),
                          uncovered=uncovered, sparse=sparse)


def check_media(media: str | Path, segments: list[dict], **kw) -> CoverageReport:
    speech, duration = speech_intervals(media)
    return measure(segments, speech, duration, **kw)
