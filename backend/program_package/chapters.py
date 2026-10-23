"""概要欄のチャプターが YouTube の決まりに合っているかを確かめる（AI を呼ばない）。

YouTube がチャプターとして扱う条件: 最初が 0:00・3つ以上・どれも10秒以上・時刻が増えていく。
加えて、動画の長さを超えないこと。

使い方::

    python -m backend.program_package.chapters 投稿パッケージ.txt --duration 2558.37
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

LINE = re.compile(r"^\s*((?:\d+:)?\d{1,2}:\d{2})\s+(\S.*)$")


def seconds(stamp: str) -> int:
    n = 0
    for part in stamp.split(":"):
        n = n * 60 + int(part)
    return n


def parse(text: str) -> list[tuple[int, str]]:
    return [(seconds(m.group(1)), m.group(2).strip()) for m in map(LINE.match, text.splitlines()) if m]


def problems(chapters: list[tuple[int, str]], duration: float) -> list[str]:
    out = []
    if len(chapters) < 3:
        out.append(f"チャプターが {len(chapters)} 個（3つ以上が要る）")
    if chapters and chapters[0][0] != 0:
        out.append("最初が 0:00 ではない")
    ends = [t for t, _ in chapters[1:]] + [duration]
    for (t, title), end in zip(chapters, ends):
        if end <= t:
            out.append(f"{title}: 時刻が前より後ろになっていない")
        elif end - t < 10:
            out.append(f"{title}: {end - t:.0f} 秒しかない（10秒以上が要る）")
        if t >= duration:
            out.append(f"{title}: 動画の長さを超えている")
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="チャプターが YouTube の決まりに合うか")
    p.add_argument("text")
    p.add_argument("--duration", type=float, required=True, help="動画の長さ（秒）")
    a = p.parse_args(argv)
    chapters = parse(Path(a.text).read_text(encoding="utf-8"))
    bad = problems(chapters, a.duration)
    for b in bad:
        print("NG", b)
    print(f"チャプター {len(chapters)} 個: {'合っています' if not bad else '直してください'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
