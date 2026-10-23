"""収録の黒い縁を拡大で埋める（2本目の対談・2026-10-23 北原さん「拡大して」）。

2025-10-20 の収録（上野雅巳さん）は、配信ソフトの画面をそのまま録っていて、場面ごとに
映像の周りが黒い:

- 美麗さんのワンショット: 1140×570 が (24, 74) に小さく置かれ、周りが黒い
- 2人の場面: 1080×720 が (100, 0) に置かれ、左右に黒い帯
- 揮毫の場面: 1280×720 いっぱい（縁なし）

## やり方

1. **見つける**（`detect`）: ffmpeg の cropdetect で毎秒2コマ、映像のある枠を測る。
   1.5秒より短い枠（場面の切り替わりの途中のコマ）は前の場面にまとめる。
   境目はその前後を全コマで測り直して、コマ単位で合わせる
2. **埋める**（`fill`）: 場面ごとに、映像のある枠の中から出力と同じ縦横比の窓を真ん中で切り出し、
   出力の大きさに拡大する。黒い縁が無い場面はそのまま。音は触らない（再エンコードもしない）

拡大はするが、映像の中身（人の位置・顔）は動かさない。窓は枠の真ん中に置く。
上下を切るのは2人の場面（3:2 → 16:9 で上下 56 画素ずつ）、左右を切るのはワンショット（2:1 → 16:9）。

場面の並びは、つないだ素材の控え（`.parts.json`）の `fill` に残す。

    python -m backend.media_fill detect 素材.mp4
    python -m backend.media_fill fill 素材.mp4 出力.mp4
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

# cropdetect が黒と見る明るさ（0〜255）。暗い服を縁と見ないよう、ffmpeg の既定（24）のまま
BLACK_LIMIT = 24
# 1回目に測るコマの間隔（毎秒2コマ）
SAMPLE_FPS = 2
# これより短い枠は場面と見ない（切り替わりの途中のコマ。測ると 0.5〜1.0 秒）
MIN_SCENE_SEC = 1.5
# 枠のずれをこの画素まで同じと見る（cropdetect は 2 画素単位で揺れる）
SAME_PX = 8
# 枠が出力のこの割合以上なら「縁なし」と見る
FULL_RATIO = 0.97

VIDEO_CODEC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]


class FillError(RuntimeError):
    """素材を読めない・埋められない。"""


@dataclass(frozen=True)
class Box:
    w: int
    h: int
    x: int
    y: int

    def same(self, other: "Box") -> bool:
        return all(abs(a - b) <= SAME_PX for a, b in
                   ((self.w, other.w), (self.h, other.h), (self.x, other.x), (self.y, other.y)))


@dataclass(frozen=True)
class Scene:
    start: float
    end: float
    box: Box
    crop: Box | None  # None は縁なし（そのまま）


def _even(v: float) -> int:
    return max(2, int(round(v)) // 2 * 2)


def fill_window(box: Box, width: int, height: int) -> Box | None:
    """枠 `box` の中から、出力（width×height）と同じ縦横比の窓を真ん中で切り出す。縁なしは None。"""
    if box.w >= width * FULL_RATIO and box.h >= height * FULL_RATIO:
        return None
    aspect = width / height
    if box.w / box.h > aspect:  # 横に長い → 左右を切る
        w, h = _even(box.h * aspect), _even(box.h)
    else:  # 縦に長い → 上下を切る
        w, h = _even(box.w), _even(box.w / aspect)
    x = box.x + (box.w - w) // 2
    y = box.y + (box.h - h) // 2
    return Box(w, h, x, y)


def scenes_from_samples(samples: Sequence[tuple[float, Box]], duration: float,
                        width: int, height: int) -> list[Scene]:
    """測った (時刻, 枠) の並びを場面にまとめる。短い枠は前の場面に入れる。"""
    if not samples:
        raise FillError("映像の枠を測れませんでした")
    runs: list[list] = []  # [始まり, 枠, 何コマ]
    for t, box in samples:
        if runs and runs[-1][1].same(box):
            runs[-1][2] += 1
        else:
            runs.append([t, box, 1])
    step = (samples[1][0] - samples[0][0]) if len(samples) > 1 else 1.0
    kept: list[list] = []
    for run in runs:
        if run[2] * step < MIN_SCENE_SEC and kept:
            continue  # 前の場面に入れる（切り替わりの途中）
        if kept and kept[-1][1].same(run[1]):
            continue  # 短い枠を飛ばした結果、前と同じ枠が続いた
        kept.append(run)
    kept[0][0] = 0.0
    scenes = []
    for i, (start, box, _) in enumerate(kept):
        end = kept[i + 1][0] if i + 1 < len(kept) else duration
        scenes.append(Scene(round(start, 3), round(end, 3), box, fill_window(box, width, height)))
    return scenes


_KEYS = re.compile(r"lavfi\.cropdetect\.(w|h|x|y)=(\d+)")


def _cropdetect(path: Path, *, fps: float | None, start: float = 0.0, length: float | None = None
                ) -> list[tuple[float, Box]]:
    vf = (f"fps={fps}," if fps else "") + f"cropdetect=limit={BLACK_LIMIT}:round=2:reset=1,metadata=print:file=-"
    cmd = ["ffmpeg", "-hide_banner", "-v", "error", "-ss", f"{start:.3f}", "-i", str(path)]
    if length is not None:
        cmd += ["-t", f"{length:.3f}"]
    cmd += ["-an", "-vf", vf, "-f", "null", "-"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise FillError(f"{path.name}: 枠を測れません（{proc.stderr.strip()[:200]}）")
    return parse_metadata(proc.stdout, offset=start)


def parse_metadata(text: str, offset: float = 0.0) -> list[tuple[float, Box]]:
    """`metadata=print` の出力から (時刻, 枠) を読む。"""
    out: list[tuple[float, Box]] = []
    t, vals = None, {}
    for line in text.splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            t, vals = float(m.group(1)) + offset, {}
            continue
        k = _KEYS.search(line)
        if k and t is not None:
            vals[k.group(1)] = int(k.group(2))
            if len(vals) == 4:
                out.append((round(t, 3), Box(vals["w"], vals["h"], vals["x"], vals["y"])))
                t = None
    return out


def _probe(path: Path) -> tuple[int, int, float, float]:
    proc = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                           "stream=width,height,r_frame_rate:format=duration", "-of", "json", str(path)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise FillError(f"{path.name}: 読めません（{proc.stderr.strip()[:200]}）")
    data = json.loads(proc.stdout)
    s = data["streams"][0]
    num, _, den = s["r_frame_rate"].partition("/")
    return int(s["width"]), int(s["height"]), float(data["format"]["duration"]), float(num) / float(den or 1)


def detect(path: str | Path) -> dict:
    """場面ごとの枠と切り出す窓を返す（ローカル・無料）。"""
    path = Path(path)
    width, height, duration, fps = _probe(path)
    scenes = scenes_from_samples(_cropdetect(path, fps=SAMPLE_FPS), duration, width, height)
    refined = [scenes[0]]
    for prev, cur in zip(scenes, scenes[1:]):
        # 境目を前後 0.6 秒、全コマで測り直し、次の場面の枠になった最初のコマにそろえる
        lo = max(prev.start, cur.start - 0.6)
        frames = _cropdetect(path, fps=None, start=lo, length=1.2)
        hit = next((t for t, b in frames if b.same(cur.box)), cur.start)
        start = round(round(hit * fps) / fps, 3)
        refined[-1] = Scene(refined[-1].start, start, refined[-1].box, refined[-1].crop)
        refined.append(Scene(start, cur.end, cur.box, cur.crop))
    return {"width": width, "height": height, "duration": duration,
            "scenes": [{"start": s.start, "end": s.end, "box": asdict(s.box),
                        "crop": asdict(s.crop) if s.crop else None} for s in refined]}


def filter_graph(plan: dict) -> str:
    """場面ごとに切り出して拡大し、つなぎ直す filtergraph。"""
    W, H = plan["width"], plan["height"]
    scenes = plan["scenes"]
    chains = [f"[0:v:0]split={len(scenes)}" + "".join(f"[s{i}]" for i in range(len(scenes)))]
    for i, s in enumerate(scenes):
        end = "" if i == len(scenes) - 1 else f":end={s['end']}"
        f = f"[s{i}]trim=start={s['start']}{end},setpts=PTS-STARTPTS"
        c = s.get("crop")
        if c:
            f += f",crop={c['w']}:{c['h']}:{c['x']}:{c['y']},scale={W}:{H}:flags=lanczos"
        chains.append(f + f",setsar=1,format=yuv420p[v{i}]")
    joined = "".join(f"[v{i}]" for i in range(len(scenes)))
    return ";".join(chains) + f";{joined}concat=n={len(scenes)}:v=1:a=0[v]"


def needs_fill(plan: dict) -> bool:
    return any(s.get("crop") for s in plan["scenes"])


def fill(src: str | Path, out: str | Path, plan: dict | None = None) -> dict:
    """`src` の黒い縁を拡大で埋めて `out` に書く。音はそのまま写す。場面の並びを返す。"""
    src, out = Path(src), Path(out)
    plan = plan or detect(src)
    part = out.with_name(f"{out.stem}.part{out.suffix}")
    cmd = ["ffmpeg", "-hide_banner", "-v", "error", "-y", "-i", str(src),
           "-filter_complex", filter_graph(plan), "-map", "[v]", "-map", "0:a:0",
           *VIDEO_CODEC, "-c:a", "copy", "-movflags", "+faststart", str(part)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise FillError("ffmpeg が失敗しました: " + proc.stderr.strip()[-500:])
        part.replace(out)
    finally:
        part.unlink(missing_ok=True)
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="収録の黒い縁を拡大で埋める（ローカル・無料）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("detect", help="場面ごとの枠を測る（読むだけ）")
    d.add_argument("src")
    f = sub.add_parser("fill", help="拡大して書き出す")
    f.add_argument("src")
    f.add_argument("out")
    args = parser.parse_args(argv)
    try:
        plan = detect(args.src) if args.cmd == "detect" else fill(args.src, args.out)
    except FillError as e:
        print(f"🚫 {e}", file=sys.stderr)
        return 1
    for s in plan["scenes"]:
        b, c = s["box"], s["crop"]
        how = f"{c['w']}x{c['h']}+{c['x']}+{c['y']} を拡大" if c else "そのまま"
        print(f"  {s['start']:9.3f}〜{s['end']:9.3f} 秒  枠 {b['w']}x{b['h']}+{b['x']}+{b['y']}  {how}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
