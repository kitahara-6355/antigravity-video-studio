"""完成した対談から、縦長（1080x1920）の Shorts を切り出す（AI を呼ばない・0円）。

- 区間は完成版の時刻で指定し、編集の固定（lock）をたどって raw から取り直す（字幕の焼き込みが無い絵）
- 字幕は承認済みの字幕（.subtitles.json）をそのまま使い、大きく焼き込む
- 画面: 上にキャッチ2行（赤と金の明朝）、真ん中に対談の絵、下に字幕と出演者名。背景は美麗書院の薄紫
- Shorts の画面は下と右に操作ボタンが重なるので、字幕は下から 1/3 より上に置く

使い方（リポジトリ直下で）::

    python -m backend.program_package.shorts SPEC.json --raw RAW.mp4 --subs SUBS.json --out DIR [--only S1 S3]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from backend.program_package import thumbnail as th

W, H = 1080, 1920
VIDEO_Y = 640  # 対談の絵の上端
LEAD, TAIL = 0.25, 0.35  # 字幕の出だしの少し前から、終わりの少し後まで


def seconds(stamp: str) -> float:
    n = 0.0
    for part in stamp.split(":"):
        n = n * 60 + float(part)
    return n


def snap(part, segments: list[dict]) -> tuple[float, float]:
    """区間の指定を秒にする。"m:ss" は字幕の出だしとみなし、終わりは最後の字幕の終わりまでにする。"""
    a, b = part
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a), float(b)
    sa, sb = seconds(a), seconds(b)
    first = min((s for s in segments if s["start"] >= sa - 0.6), key=lambda s: s["start"])
    last = max((s for s in segments if s["start"] < sb + 1.0), key=lambda s: s["start"])
    return max(0.0, first["start"] - LEAD), last["end"] + TAIL


def raw_pieces(a: float, b: float, ranges: list) -> list[tuple[float, float]]:
    """完成版の a〜b 秒を、残す区間をつないだ raw のどこから取るかに直す。"""
    out, t = [], 0.0
    for ra, rb in ranges:
        n = rb - ra
        lo, hi = max(a, t), min(b, t + n)
        if lo < hi:
            out.append((ra + lo - t, ra + hi - t))
        t += n
    return out


def clip_cues(parts: list[tuple[float, float]], segments: list[dict]) -> list[tuple[float, float, str]]:
    """区間に入る字幕を、切り出した Shorts の時刻に置き直す。"""
    out, offset = [], 0.0
    for a, b in parts:
        for s in segments:
            lo, hi = max(a, s["start"]), min(b, s["end"])
            if hi - lo > 0.2:
                out.append((offset + lo - a, offset + hi - a, s["text"]))
        offset += b - a
    return out


def ass_time(t: float) -> str:
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def ass(cues) -> str:
    head = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 2\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV\n"
        "Style: S,Noto Sans JP Black,66,&H00FFFFFF,&H00301430,&H80000000,0,1,7,2,8,60,60,1290\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Text\n")
    lines = [f"Dialogue: 0,{ass_time(a)},{ass_time(b)},S,{t.replace(chr(10), r'\N')}" for a, b, t in cues]
    return head + "\n".join(lines) + "\n"


def card(title: list[str], names: str, theme: dict) -> Image.Image:
    """動かない部分（背景・キャッチ・名前）を1枚に描く。"""
    import numpy as np
    y = np.linspace(0, 1, H)[:, None]
    x = np.linspace(-1, 1, W)[None, :]
    glow = np.clip(1 - (x ** 2 * 0.6 + (y - 0.3) ** 2 * 1.6), 0, 1) ** 1.2
    light, deep = np.array(theme["light"]), np.array(theme["deep"])
    a = deep + (light - deep) * glow[..., None]
    im = Image.fromarray(np.clip(a, 0, 255).astype("uint8"))
    d = ImageDraw.Draw(im)
    for i in range(-4, 5):
        x0 = W / 2 + i * 160
        d.line([(x0 - 500, H), (x0 + 500, 0)], fill=(206, 170, 104), width=1)
    # 長い行は、左右に 60px ずつ余白が残る大きさまで縮める（2行とも同じ大きさ）
    longest = max(d.textlength(t, font=th.font("mincho", 100)) for t in title)
    f = th.font("mincho", min(100, int(100 * (W - 120) / longest)))
    th.gradient_text(im, (W / 2, 330), title[0], f, th.RED, anchor="ms", stroke=9)
    th.gradient_text(im, (W / 2, 470), title[1], f, th.GOLD, anchor="ms", stroke=9)
    d.rectangle([0, VIDEO_Y - 6, W, VIDEO_Y + 618], fill=(196, 156, 72))  # 金の細い枠
    nf = th.font("mincho", 44)
    d.text((W / 2, 560), names, font=nf, fill="white", anchor="ms", stroke_width=5, stroke_fill=(40, 16, 36))
    return im


def render(spec: dict, clip: dict, raw: Path, segments: list[dict], out: Path) -> Path:
    ranges = [(float(a), float(b)) for a, b in json.loads(Path(spec["lock"]).read_text(encoding="utf-8"))["ranges"]]
    parts = [snap(p, segments) for p in clip["parts"]]
    pieces = [rp for a, b in parts for rp in raw_pieces(a, b, ranges)]
    # 背景は動画の壁（薄紫）と同化しない色にする（2026-10-23 北原さん）
    theme = spec.get("background", {"light": [104, 50, 90], "deep": [28, 10, 26]})
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        card(clip["title"], spec["names"], theme).save(tmp / "card.png")
        (tmp / "subs.ass").write_text(ass(clip_cues(parts, segments)), encoding="utf-8")
        fx, fy, fx2, fy2 = th.FRAME
        trims = "".join(
            f"[0:v]trim={a:.3f}:{b:.3f},setpts=PTS-STARTPTS[v{i}];[0:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS[a{i}];"
            for i, (a, b) in enumerate(pieces))
        joined = "".join(f"[v{i}][a{i}]" for i in range(len(pieces)))
        graph = (f"{trims}{joined}concat=n={len(pieces)}:v=1:a=1[cv][ca];"
                 f"[cv]crop={fx2 - fx}:{fy2 - fy}:{fx}:{fy},scale={W}:-2[sv];"
                 f"[1:v][sv]overlay=0:{VIDEO_Y}:shortest=1[bg];"
                 f"[bg]ass={tmp / 'subs.ass'}:fontsdir={th.FONT_DIR}[out]")
        dst = out / f"{spec['recording']}_{clip['key']}.mp4"
        start = max(0.0, pieces[0][0] - 1)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-i", str(raw), "-loop", "1",
                        "-i", str(tmp / "card.png"),
                        "-filter_complex", _shift(graph, start),
                        "-map", "[out]", "-map", "[ca]", "-shortest", "-c:v", "libx264", "-crf", "20",
                        "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                        "-movflags", "+faststart", str(dst)], check=True)
    return dst


def _shift(graph: str, start: float) -> str:
    """入力を start 秒から読むので、trim の時刻をその分ずらす。"""
    import re
    return re.sub(r"(a?trim=)([\d.]+):([\d.]+)",
                  lambda m: f"{m.group(1)}{float(m.group(2)) - start:.3f}:{float(m.group(3)) - start:.3f}", graph)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="完成した対談から縦長の Shorts を切り出す")
    p.add_argument("spec")
    p.add_argument("--raw", required=True)
    p.add_argument("--subs", required=True, help="承認済みの字幕（.subtitles.json）")
    p.add_argument("--out", default=".")
    p.add_argument("--only", nargs="*")
    a = p.parse_args(argv)
    spec = json.loads(Path(a.spec).read_text(encoding="utf-8"))
    segments = json.loads(Path(a.subs).read_text(encoding="utf-8"))["segments"]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for clip in spec["clips"]:
        if a.only and clip["key"] not in a.only:
            continue
        print(render(spec, clip, Path(a.raw), segments, out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
