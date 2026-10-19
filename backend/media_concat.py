"""取り込んだ素材を、順につないで1本にする（フェーズ1の取り込み・2026-10-18）。

対談の収録は数本に分かれる（raw 4本は 29分58秒・53秒・6分56秒・5分27秒）。パイプラインは1本の
素材を読むので、取り込んだ順につなぐ。

## つなぎ方は2通り

- **そのまま（copy）**: 映像の形（コーデック・大きさ・コマの間隔）と音の形がそろい、1080p 以下で、
  コマの間隔が一定の素材。再エンコードしないので速く、画も変わらない。つなぎ目で音の時刻が少し
  飛ぶことがある（前のファイルの音が映像より短い）が、解析は `media_timeline` が時刻どおりに読む
- **1080p に直す（transcode）**: 4K・形がそろわない・コマの間隔が一定でない素材。1本ずつ大きさと
  コマをそろえ、音を映像と同じ長さにして（足りなければ無音で埋め、余れば切る）つなぐ。中間の
  ファイルは作らない（撮影データは大きく、作業場の空きを2倍使わないため）。大きくはせず、形も変えない

各素材がつないだ1本の何秒から始まるかを、隣の `<名前>.parts.json` に残す（時間の対応づけと出どころ）。
書き出しは `<名前>.part.<拡張子>` に書いてから名前を付けるので、途中で止まっても完成品に見えない。

    python -m backend.media_concat 出力.mp4 素材1.mp4 素材2.mp4 ...
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

MAX_HEIGHT = 1080
FIT = (1920, 1080)
# つないだ後にも作業場に残す空き（書き出しは空き1GB未満だと始まらない）
FREE_MARGIN_BYTES = 2 * 1024 ** 3
# 1080p に直すときの大きさの見積もり（多めに毎秒 12Mbit）
TRANSCODE_BYTES_PER_SEC = 12_000_000 // 8
# 平均のコマの間隔が、宣言の間隔からこれ以上ずれていれば「一定でない」と見る
RATE_TOLERANCE = 0.005

VIDEO_CODEC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]
AUDIO_CODEC = ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
# 目次（moov）を頭に置く。raw 4本の結合（10-05）もこの形で、同じ素材をつなぎ直すと1バイトずつ同じになる
# （起こしのキャッシュは結合の中身の sha256 で引くので、形が違うと全部呼び直しになる）
FASTSTART = ["-movflags", "+faststart"]


class JoinError(RuntimeError):
    """素材を読めない・つなげない・空きが足りない。"""


def probe(path: str | Path) -> dict:
    """1本の形（ffprobe・ローカル）。映像か音が無ければ JoinError。"""
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True)
    name = Path(path).name
    if proc.returncode != 0:
        raise JoinError(f"{name}: 読めません（{proc.stderr.strip()[:200]}）")
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None or audio is None:
        raise JoinError(f"{name}: 映像か音がありません")
    duration = float((data.get("format") or {}).get("duration") or 0)
    return {
        "duration": duration,
        "video_duration": float(video.get("duration") or duration),
        "codec": video.get("codec_name", ""),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": video.get("r_frame_rate", ""),
        "avg_fps": video.get("avg_frame_rate", ""),
        "pix_fmt": video.get("pix_fmt", ""),
        "audio_codec": audio.get("codec_name", ""),
        "sample_rate": int(audio.get("sample_rate") or 0),
        "channels": int(audio.get("channels") or 0),
    }


def _rate(value: str) -> Fraction | None:
    try:
        rate = Fraction(value)
    except (ValueError, ZeroDivisionError):
        return None
    return rate if rate > 0 else None


def _constant_rate(info: dict) -> bool:
    declared, average = _rate(info.get("fps", "")), _rate(info.get("avg_fps", ""))
    if declared is None or average is None:
        return False
    return abs(float(average) / float(declared) - 1) <= RATE_TOLERANCE


def _shape(info: dict) -> tuple:
    return (info["codec"], info["width"], info["height"], _rate(info["fps"]), info["pix_fmt"],
            info["audio_codec"], info["sample_rate"], info["channels"])


def _even(value: float) -> int:
    return max(2, int(value) // 2 * 2)


@dataclass(frozen=True)
class Plan:
    mode: str    # "copy" / "transcode"
    reason: str
    width: int
    height: int
    fps: str


def plan(infos: Sequence[dict]) -> Plan:
    """つなぎ方を決める。そろった 1080p 以下の素材はそのまま、ほかは 1080p に直す。"""
    if not infos:
        raise JoinError("つなぐ素材がありません")
    first = infos[0]
    reasons = []
    tallest = max(i["height"] for i in infos)
    if tallest > MAX_HEIGHT:
        reasons.append(f"{tallest}p の素材を {MAX_HEIGHT}p に縮める")
    if any(_shape(i) != _shape(first) for i in infos):
        reasons.append("素材ごとに形（コーデック・大きさ・コマ・音）が違う")
    if not all(_constant_rate(i) for i in infos):
        reasons.append("コマの間隔が一定でない素材がある")
    if not reasons:
        return Plan("copy", "形のそろった 1080p 以下の素材なので、つなぐだけ",
                    first["width"], first["height"], first["fps"])
    # 枠は面積のいちばん大きい素材（主のカメラ）の形。縦と横の最大を別の素材から取ると、縦の素材が
    # 1本混ざっただけで正方形になる。ほかの素材は枠に収めて余りを黒で埋める
    main = max(infos, key=lambda i: i["width"] * i["height"])
    scale = min(1.0, FIT[0] / main["width"], FIT[1] / main["height"])
    return Plan("transcode", "・".join(reasons), _even(main["width"] * scale), _even(main["height"] * scale),
                first["fps"] if _rate(first["fps"]) else "30000/1001")


def manifest_path(out: str | Path) -> Path:
    return Path(out).with_suffix(".parts.json")


def _part_path(out: Path) -> Path:
    return out.with_name(f"{out.stem}.part{out.suffix}")


def _copy_command(paths: Sequence[Path], listing: Path, out: Path) -> list[str]:
    listing.write_text("".join("file '" + str(p.resolve()).replace("'", "'\\''") + "'\n" for p in paths),
                       encoding="utf-8")
    return ["ffmpeg", "-hide_banner", "-v", "error", "-y", "-f", "concat", "-safe", "0",
            "-i", str(listing), "-map", "0:v:0", "-map", "0:a:0", "-c", "copy", *FASTSTART, str(out)]


def _transcode_command(paths: Sequence[Path], infos: Sequence[dict], p: Plan, out: Path) -> list[str]:
    chains = []
    for i, info in enumerate(infos):
        d = f"{info['video_duration']:.6f}"
        chains.append(
            f"[{i}:v:0]setpts=PTS-STARTPTS,"
            f"scale={p.width}:{p.height}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={p.width}:{p.height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={p.fps},format=yuv420p[v{i}];"
            f"[{i}:a:0]aresample=48000:async=1:min_hard_comp=0.01:first_pts=0,"
            f"aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"apad=whole_dur={d},atrim=end={d},asetpts=N/SR/TB[a{i}]")
    joined = "".join(f"[v{i}][a{i}]" for i in range(len(infos)))
    graph = ";".join(chains) + f";{joined}concat=n={len(infos)}:v=1:a=1[v][a]"
    inputs = [arg for path in paths for arg in ("-i", str(path))]
    return (["ffmpeg", "-hide_banner", "-v", "error", "-y", *inputs, "-filter_complex", graph,
             "-map", "[v]", "-map", "[a]", *VIDEO_CODEC, *AUDIO_CODEC, *FASTSTART, str(out)])


def _run(cmd: list[str], total: float, on_progress: Callable[[float, float], None] | None) -> None:
    """ffmpeg を流す。`-progress` の出力から、書き出した秒数を on_progress に渡す。

    エラーの出力は進み具合と同じ口で読む。別の口にして進み具合を読み終わるまで溜めると、溜め場（64KB）が
    埋まった所で ffmpeg が待ちに入り、どちらも進まなくなる（壊れたコマが続く素材で起きる）。
    """
    proc = subprocess.Popen([*cmd[:-1], "-progress", "pipe:1", "-nostats", cmd[-1]],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    assert proc.stdout is not None
    said: deque[str] = deque(maxlen=20)
    for line in proc.stdout:
        key, eq, value = line.strip().partition("=")
        value = value.strip()  # `bitrate=   0.3kbits/s` のように値の前を空けて書く項目がある
        if eq and key.isidentifier() and " " not in value:  # 進み具合（`out_time_us=1500000` など）
            if on_progress and key == "out_time_us" and value.isdigit():
                on_progress(int(value) / 1_000_000, total)
        elif line.strip():
            said.append(line.strip())
    if proc.wait() != 0:
        raise JoinError("ffmpeg が失敗しました: " + " / ".join(said)[-500:])


def join(paths: Sequence[str | Path], out: str | Path, *,
         free_bytes: Callable[[Path], int] | None = None,
         on_progress: Callable[[float, float], None] | None = None) -> dict:
    """素材を渡した順につないで `out` に書き、控え（`manifest_path(out)`）を返す・書く。"""
    paths = [Path(p) for p in paths]
    if not paths:
        raise JoinError("つなぐ素材がありません")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    infos = [probe(p) for p in paths]
    how = plan(infos)
    total = sum(i["video_duration"] if how.mode == "transcode" else i["duration"] for i in infos)
    estimate = (sum(p.stat().st_size for p in paths) if how.mode == "copy"
                else int(total * TRANSCODE_BYTES_PER_SEC))
    free = (free_bytes or (lambda d: shutil.disk_usage(d).free))(out.parent)
    if free < estimate + FREE_MARGIN_BYTES:
        raise JoinError(f"作業場の空きが足りません（空き {free / 1024 ** 3:.1f} GB / 見込み "
                        f"{estimate / 1024 ** 3:.1f} GB ＋ 残す {FREE_MARGIN_BYTES / 1024 ** 3:.0f} GB）")
    part = _part_path(out)
    listing = out.with_suffix(".list.txt")
    try:
        cmd = (_copy_command(paths, listing, part) if how.mode == "copy"
               else _transcode_command(paths, infos, how, part))
        _run(cmd, total, on_progress)
        part.replace(out)
    finally:
        part.unlink(missing_ok=True)
        listing.unlink(missing_ok=True)
    parts, start = [], 0.0
    for path, info in zip(paths, infos):
        length = info["video_duration"] if how.mode == "transcode" else info["duration"]
        parts.append({"name": path.name, "start": round(start, 6), "duration": round(length, 6),
                      "size": path.stat().st_size, "width": info["width"], "height": info["height"],
                      "codec": info["codec"], "fps": info["fps"]})
        start += length
    result = probe(out)
    manifest = {"out": out.name, "mode": how.mode, "reason": how.reason,
                "width": result["width"], "height": result["height"], "fps": result["fps"],
                "duration": result["duration"], "size": out.stat().st_size, "parts": parts}
    manifest_path(out).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="取り込んだ素材を順につないで1本にする（ローカル・無料）")
    parser.add_argument("out")
    parser.add_argument("clips", nargs="+")
    args = parser.parse_args(argv)

    def show(done: float, total: float) -> None:
        print(f"\r  {done / 60:5.1f} / {total / 60:.1f} 分", end="", flush=True)

    try:
        manifest = join(args.clips, args.out, on_progress=show)
    except JoinError as e:
        print(f"\n🚫 {e}", file=sys.stderr)
        return 1
    print(f"\n{manifest['out']}: {manifest['mode']}（{manifest['reason']}）"
          f" {manifest['width']}x{manifest['height']}・{manifest['duration'] / 60:.1f} 分")
    for p in manifest["parts"]:
        print(f"  {p['start']:9.3f} 秒から  {p['name']}（{p['duration']:.3f} 秒）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
