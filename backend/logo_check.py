"""書き出した動画の左上にロゴが入っていないかを、画素で確かめる（AI を呼ばない）。

目視に頼らない。書き出しの何か所かで、左上の一角を raw の同じ時刻の同じ一角と比べる。
ロゴが無ければ違いは圧縮の揺れだけで小さく、ロゴがあればそこだけ大きく違う。
書き出しの時刻から raw の時刻へは、編集の固定（edit_lock）の残す区間でたどる。

使い方（リポジトリ直下で）::

    python -m backend.logo_check OUT.mp4 --lock LOCK.json --material RAW.mp4
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# ロゴを置いていた所（720p の画素で x, y, 幅, 高さ。ロゴは 10,10 から高さ 45px・幅 23px で置いていた）
CORNER = (4, 4, 40, 60)
# 1画素あたりの平均の差（0〜255）。ロゴの無い所の圧縮の揺れより大きく、白いロゴより十分小さい所に置く
LIMIT = 12.0


def source_time(ranges: list, t: float) -> float:
    """書き出しの時刻 ``t`` を、残す区間をつないだ raw の時刻に戻す。"""
    for a, b in ranges:
        if t < b - a:
            return a + t
        t -= b - a
    raise ValueError("書き出しの長さを超えています")


def corner(video: Path, at: float, size: tuple[int, int]) -> bytes:
    """``video`` の ``at`` 秒の1枚を ``size`` に揃え、左上の一角を灰色の画素で返す。"""
    x, y, w, h = CORNER
    vf = f"scale={size[0]}:{size[1]},crop={w}:{h}:{x}:{y},format=gray"
    out = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{at:.3f}", "-i", str(video), "-frames:v", "1",
                          "-vf", vf, "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    if len(out) != w * h:
        raise RuntimeError(f"{video.name} の {at:.1f} 秒を読めませんでした")
    return out


def diff(a: bytes, b: bytes) -> float:
    return sum(abs(p - q) for p, q in zip(a, b)) / len(a)


def check(out: Path, lock: dict, material: Path, samples: int = 12) -> list[dict]:
    ranges = [(float(a), float(b)) for a, b in lock["ranges"]]
    total = sum(b - a for a, b in ranges)
    rows = []
    for i in range(samples):
        t = total * (i + 0.5) / samples
        s = source_time(ranges, t)
        # 出力は raw と同じ大きさに揃えて比べる（360p の確認用でも同じ物差しになる）
        d = diff(corner(out, t, (1280, 720)), corner(material, s, (1280, 720)))
        rows.append({"at": round(t, 1), "raw_at": round(s, 1), "diff": round(d, 2), "ok": d <= LIMIT})
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="書き出しの左上にロゴが無いかを画素で確かめる")
    parser.add_argument("out")
    parser.add_argument("--lock", required=True)
    parser.add_argument("--material", required=True)
    parser.add_argument("--samples", type=int, default=12)
    args = parser.parse_args(argv)
    rows = check(Path(args.out), json.loads(Path(args.lock).read_text(encoding="utf-8")),
                 Path(args.material), args.samples)
    for r in rows:
        print(f"  {r['at']:>8.1f} 秒（raw {r['raw_at']:>8.1f} 秒）  差 {r['diff']:>6.2f}  {'OK' if r['ok'] else 'ロゴあり?'}")
    bad = [r for r in rows if not r["ok"]]
    print(f"左上にロゴなし: {len(rows) - len(bad)}/{len(rows)} か所（差の上限 {LIMIT}）")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
