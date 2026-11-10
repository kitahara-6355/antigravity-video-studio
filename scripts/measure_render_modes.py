"""書き出しモード（production / safe）のエンコード設定を**実測**で比べる（D-47・2026-11-10）。

    python scripts/measure_render_modes.py <動画> [--start 600] [--seconds 120] [--scale 1920x1080] [--out 結果.json]

本線の書き出しは、承認したプレビューを libx264 で焼き直す。設定ごとに
「かかる時間（実時間の何倍速か）・ファイルの大きさ（Mbps）・元との近さ（SSIM）」を測って表にする。
画質と時間のどこを取るかは北原さんが決める（`backend/config/render_modes.json`）。

AI は呼ばない。0円。GPU は使わない（クラウドと同じ CPU の libx264 で測る）。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CANDIDATES = [
    ("fast", "ultrafast", 28),
    ("balanced", "veryfast", 23),
    ("—", "medium", 20),
    ("—", "medium", 18),
    ("quality", "slow", 18),
]


def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stderr


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("video")
    p.add_argument("--start", type=float, default=600)
    p.add_argument("--seconds", type=float, default=120)
    p.add_argument("--scale", default="1920x1080", help="測る大きさ（元が小さければ拡大する）")
    p.add_argument("--out", default=None)
    a = p.parse_args(argv)
    w, h = a.scale.split("x")
    rows = []
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "src.mkv"
        # 元（基準）: 指定の区間を、ほぼ劣化なしで測る大きさにそろえる
        run(["ffmpeg", "-v", "error", "-y", "-ss", str(a.start), "-t", str(a.seconds), "-i", a.video,
             "-vf", f"scale={w}:{h}:flags=bicubic", "-c:v", "libx264", "-preset", "veryfast", "-crf", "8",
             "-pix_fmt", "yuv420p", "-c:a", "copy", str(src)])
        for name, preset, crf in CANDIDATES:
            dst = Path(d) / f"{preset}_{crf}.mp4"
            t0 = time.time()
            run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-c:v", "libx264", "-preset", preset,
                 "-crf", str(crf), "-pix_fmt", "yuv420p", "-c:a", "aac", str(dst)])
            took = time.time() - t0
            log = run(["ffmpeg", "-v", "info", "-i", str(dst), "-i", str(src), "-lavfi", "ssim", "-an",
                       "-f", "null", "-"])
            ssim = float(re.search(r"All:([\d.]+)", log).group(1))
            rows.append({"encode": name, "preset": preset, "crf": crf,
                         "seconds": round(took, 1), "speed_x": round(a.seconds / took, 2),
                         "mbps": round(dst.stat().st_size * 8 / a.seconds / 1e6, 2), "ssim": round(ssim, 4)})
    print(f"{'名前':<10}{'preset':<11}{'crf':>4}{'時間(秒)':>9}{'倍速':>7}{'Mbps':>7}{'SSIM':>8}")
    for r in rows:
        print(f"{r['encode']:<10}{r['preset']:<11}{r['crf']:>4}{r['seconds']:>9}{r['speed_x']:>7}"
              f"{r['mbps']:>7}{r['ssim']:>8}")
    if a.out:
        Path(a.out).write_text(json.dumps({"video": Path(a.video).name, "start": a.start,
                                           "seconds": a.seconds, "scale": a.scale, "rows": rows},
                                          ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
