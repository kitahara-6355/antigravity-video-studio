"""素材の音を、映像と同じ時間軸（素材の秒）で読む。

動画の音と映像は、それぞれ自分の時刻（タイムスタンプ）で並んでいる。収録を結合した素材では、
つなぎ目で音の時刻が飛ぶことがある（前のファイルの音が映像より少し短い）。ffmpeg で音を
そのまま読むと、飛んだ所が詰まり、後ろの音がその分だけ早い時刻で読める。

raw 4本の結合（43分）は、29分58秒・30分51秒・37分48秒のつなぎ目で音が計 165ms 飛んでいて、
37分48秒より後ろの声を 0.165 秒早い時刻で解析していた（2026-10-18 実測）。カットと字幕は
映像の時刻で切る・出すので、書き出しで音を時刻どおりに並べると（56回目）、解析した声の時刻と
書き出した声がずれ、36分55秒の聞き手の「テーマパーク？」の字幕が声の無い所に配られて消えた。

解析に使う音は `read_pcm` で読む（書き出しと同じ `TIMELINE_FILTER` で、飛んだ所は無音で埋める）。
詰めて読んだ時刻のまま残っている結果（音声認識のキャッシュ）は、`audio_gaps` で飛びを測り
`to_source_times` で直す。
"""
from __future__ import annotations

import bisect
import json
import logging
import subprocess
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# 音を素材の時刻どおりに並べる（飛んだ所は無音で埋め、重なった所は捨てる。頭は 0 秒から）。
# 書き出し（`smart_cut_engine._frame_cut_graph`）も同じフィルタで並べる
TIMELINE_FILTER = "aresample=async=1:min_hard_comp=0.01:first_pts=0"
# TIMELINE_FILTER の min_hard_comp。これより短い飛びは埋めない（時刻の丸めの揺れ）
MIN_GAP_SEC = 0.01


def read_pcm(media, rate: int = 16000, timeout: int = 1800) -> bytes:
    """動画・音声ファイルの音を、素材の時間軸どおりに mono・16bit で読む（ffmpeg・ローカル）。

    i 番目のサンプルが素材の i / rate 秒。読めなければ RuntimeError。
    """
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-v", "error", "-i", str(media), "-vn", "-af", TIMELINE_FILTER,
         "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"],
        capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"音声の読み出しに失敗: {proc.stderr[-300:]!r}")
    return proc.stdout


def audio_gaps(media) -> list[tuple[float, float]]:
    """音の時刻の飛び: (詰めて読んだときの位置（秒）, 飛んだ長さ（秒）) の並び（ffprobe・ローカル）。

    音が 0 秒より後ろで始まる分も、頭の飛びとして数える。重なり（時刻が戻る所）は負の長さ。
    `MIN_GAP_SEC` より短い揺れは数えない。読めなければ OSError・ValueError・SubprocessError。
    """
    path = Path(media)
    st = path.stat()
    return list(_audio_gaps(str(path.resolve()), st.st_size, int(st.st_mtime)))


@lru_cache(maxsize=8)
def _audio_gaps(path: str, size: int, mtime: int) -> tuple[tuple[float, float], ...]:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=sample_rate:frame=pts_time,nb_samples", "-of", "json", path],
        capture_output=True, text=True, timeout=600, check=True)
    data = json.loads(proc.stdout or "{}")
    rate = int((data.get("streams") or [{}])[0].get("sample_rate") or 0)
    if rate <= 0:
        raise ValueError(f"音のサンプリングレートが読めません: {path}")
    gaps: list[tuple[float, float]] = []
    expected = decoded = 0.0  # 次の音が始まるはずの素材の秒・詰めて読んだときの位置
    for frame in data.get("frames") or []:
        try:
            t, n = float(frame["pts_time"]), int(frame["nb_samples"])
        except (KeyError, TypeError, ValueError):
            continue
        if abs(t - expected) >= MIN_GAP_SEC:
            gaps.append((round(decoded, 4), round(t - expected, 4)))
        expected, decoded = t + n / rate, decoded + n / rate
    return tuple(gaps)


def to_source_times(times, gaps) -> list[float]:
    """詰めて読んだ時刻（秒）を素材の時間軸に直す。その位置より前の飛びを足す。"""
    positions = [p for p, _ in gaps]
    shift, total = [], 0.0
    for _, g in gaps:
        total += g
        shift.append(total)
    out = []
    for t in times:
        k = bisect.bisect_right(positions, float(t))
        out.append(round(float(t) + (shift[k - 1] if k else 0.0), 3))
    return out
