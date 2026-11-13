"""仕上げ版の音だけを差し替える — 番組 OP の曲・インタビュー中の BGM・音割れ止め（2026-11-12）。

映像は作り直さない（``-c:v copy``）。42分の仕上げ版でも 1 回が数分で済むので、打ち合わせの場で
曲や音量を何度でも試せる。AI は呼ばない。0円。

- **番組 OP の曲**: 番組 OP（どの回でも同じ・頭の ``program_length`` 秒）の音を新しい曲に入れ替える。
  今回の名場面へのつなぎ目（FADE 秒）で、前の曲の残りを消して新しい曲を下げ切る
- **BGM**: 本編の時刻（完成版 v62 の時刻）の区間に、曲を小さく敷く。話している間は自動で下げる
  （``sidechaincompress``・話し声を合図にする）。区間の頭と終わりはふわっと出し入れする
- **ED の曲**: 最後の ED（``ending.seconds`` 秒）に曲を敷く。頭はふわっと入れ、最後で下げ切る。
  ED の曲があるとき、BGM の既定の範囲は本編の終わりまで（ED の手前）
- **音割れ止め**: 最後に全体の上限（既定 -1.5 dBFS・4 倍に上げて掛ける）を掛ける。v62 は 7:34 付近で +5.8 dBFS まで出ていた

指定（``AUDIO.json``）::

    {"op_music": {"path": "OP曲.m4a", "start": 0.0, "volume": 0.9, "fade_out": 1.5, "provisional": false},
     "bgm": {"path": "BGM.m4a", "start": 0.0, "volume_db": -22, "duck": true, "fade": 3.0,
             "ranges": [[0, 2540]], "provisional": false},
     "ed_music": {"path": "ED曲.m4a", "start": 0.0, "volume": 0.9, "fade_in": 1.0, "fade_out": 3.0},
     "peak_db": -1.5}

``op_music``・``bgm``・``ed_music`` はどちらも ``null`` でよい（音割れ止めだけ掛ける）。曲は短ければ繰り返す。
仮の曲（``provisional: true``）を使った版は、名前に「_仮曲入り」が付く（公開に使わない印）。

使い方（リポジトリ直下で）::

    python -m backend.program_package.remix EPISODE_SPEC.json 仕上げ版.mp4 --audio AUDIO.json \\
        --version v67 --out OUT [--review] [--clip 454 30]

- ``--review``: 同じ書き出しの確認用 360p（``_確認用360p.mp4``）も作る（承認の門の ``--review`` に渡す）
- ``--clip 本編の秒 長さ``: 聞き比べ用の短い切り出し（何度でも付けられる。本編の時刻で指定）
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from backend.program_package import episode as ep

FADE = ep.FADE


def duration(path: str | Path) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                 str(path)], capture_output=True, text=True, check=True).stdout)


def timeline(spec: dict) -> dict:
    """仕上げ版の中の区切り（秒）。番組 OP の終わりと本編の頭。"""
    return {"program": ep.program_length(spec), "body": ep.op_length(spec),
            "ed": float((spec.get("ending") or {}).get("seconds", 0.0))}


def _fmt(label: str) -> str:
    return f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo{label}"


def graph(audio: dict, tl: dict, total: float) -> tuple[list[str], str]:
    """入力（0 番は仕上げ版）の後ろに足す ffmpeg の入力と、音の filter_complex。出力は [a]。"""
    inputs: list[str] = []
    g: list[str] = []
    n = 1
    op, bgm, ed = audio.get("op_music"), audio.get("bgm"), audio.get("ed_music")
    peak = 10 ** (float(audio.get("peak_db", -1.5)) / 20)
    g.append("[0:a]" + _fmt(",asplit=2[orig][sc]" if bgm else "[orig]"))
    mixes = []
    if op:
        p = tl["program"]
        if p <= FADE:
            raise ValueError("この回の指定には番組 OP がありません（op_music は使えない）")
        x = p - FADE
        # 前の曲は番組 OP の間を消し、つなぎ目で元の音（名場面）へ戻す
        g.append(f"[orig]volume='if(lt(t,{x:.3f}),0,if(lt(t,{p:.3f}),(t-{x:.3f})/{FADE},1))':eval=frame[base]")
        fo = float(op.get("fade_out", 1.5))
        inputs += ["-stream_loop", "-1", "-ss", f"{float(op.get('start', 0.0)):.3f}", "-t", f"{p:.3f}", "-i", op["path"]]
        g.append(f"[{n}:a]{_fmt('')},volume={float(op.get('volume', 0.9))},afade=t=in:d=0.3,"
                 f"afade=t=out:st={max(0.0, p - fo):.3f}:d={fo}[opm]")
        mixes.append("[opm]")
        n += 1
    else:
        g.append("[orig]anull[base]")
    if bgm:
        end = total - tl["body"] - (tl.get("ed", 0.0) if ed else 0.0)
        ranges = bgm.get("ranges") or [[0.0, end]]
        fade = float(bgm.get("fade", 3.0))
        parts = []
        for k, (a, b) in enumerate(ranges):
            a, b = float(a), float(b)
            if b - a <= 2 * fade:
                raise ValueError(f"BGM の区間 {a}〜{b} が短すぎます（出し入れ {fade} 秒×2 より長く）")
            length = b - a
            start = float(bgm.get("start", 0.0))
            song = bgm.get("_len")  # 曲の長さ（remix が測って入れる）
            xf = float(bgm.get("loop_crossfade", 4.0))
            if song and song - start > 2 * xf:
                # 曲の終わりから頭へ、xf 秒かけて重ねてつなぐ（-stream_loop の急な継ぎ目は「リズムが止まる」と
                # 聞こえた・2026-11-12 北原さん）。1 回目は start から、2 回目からは頭から
                step = song - xf
                reps = max(1, int((length + start) // step) + 1)
                labels = []
                for r in range(reps):
                    inputs += (["-ss", f"{start:.3f}"] if r == 0 else []) + ["-i", bgm["path"]]
                    g.append(f"[{n}:a]{_fmt('')}[b{k}r{r}]")
                    labels.append(f"b{k}r{r}")
                    n += 1
                cur = labels[0]
                for r, nxt in enumerate(labels[1:], start=1):
                    g.append(f"[{cur}][{nxt}]acrossfade=d={xf}:c1=qsin:c2=qsin[b{k}x{r}]")
                    cur = f"b{k}x{r}"
                src = f"[{cur}]atrim=0:{length:.3f},asetpts=PTS-STARTPTS,"
            else:
                inputs += ["-stream_loop", "-1", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", bgm["path"]]
                src = f"[{n}:a]{_fmt('')},"
                n += 1
            at = int(round((tl["body"] + a) * 1000))
            g.append(f"{src}volume={float(bgm.get('volume_db', -22))}dB,afade=t=in:d={fade},"
                     f"afade=t=out:st={length - fade:.3f}:d={fade},adelay={at}:all=1[b{k}]")
            parts.append(f"[b{k}]")
        if len(parts) > 1:
            g.append("".join(parts) + f"amix=inputs={len(parts)}:normalize=0:duration=longest[bg]")
        else:
            g.append(f"{parts[0]}anull[bg]")
        if bgm.get("duck", True):
            # 話し声（元の音）が出ている間だけ BGM を下げる。release を長めにして、言葉の切れ目で波打たせない
            # 下げ幅は ratio（既定 3）。強く速く下げると BGM が波打ち「リズムが止まる」と聞こえた（2026-11-12）
            ratio = float(bgm.get("duck_ratio", 3))
            g.append(f"[bg][sc]sidechaincompress=threshold=0.05:ratio={ratio}:attack=80:release=2000[bgd]")
        else:
            g.append("[sc]anullsink;[bg]anull[bgd]")
        mixes.append("[bgd]")
    if ed:
        e = tl.get("ed", 0.0)
        if e <= 0:
            raise ValueError("この回の指定には ED がありません（ed_music は使えない）")
        st = total - e
        fi, fo = float(ed.get("fade_in", 1.0)), float(ed.get("fade_out", 3.0))
        inputs += ["-stream_loop", "-1", "-ss", f"{float(ed.get('start', 0.0)):.3f}", "-t", f"{e:.3f}", "-i", ed["path"]]
        g.append(f"[{n}:a]{_fmt('')},volume={float(ed.get('volume', 0.9))},afade=t=in:d={fi},"
                 f"afade=t=out:st={max(0.0, e - fo):.3f}:d={fo},adelay={int(round(st * 1000))}:all=1[edm]")
        mixes.append("[edm]")
        n += 1
    if mixes:
        g.append(f"[base]{''.join(mixes)}amix=inputs={1 + len(mixes)}:normalize=0:duration=first[mix]")
    else:
        g.append("[base]anull[mix]")
    # 4 倍に上げてから上限を掛ける（標本の間で 0 dBFS を超える山＝トゥルーピークも抑える。
    # 48kHz のままでは v62 で +1.4 dBFS 残った）。AAC に圧縮するとまた少しはみ出すので、既定は -1.5
    g.append(f"[mix]aresample=192000,alimiter=limit={peak:.4f}:level=0:attack=5:release=80,aresample=48000[a]")
    return inputs, ";".join(g)


def output_name(spec: dict, audio: dict, version: str) -> str:
    prov = any((audio.get(k) or {}).get("provisional") for k in ("op_music", "bgm", "ed_music"))
    return f"{spec['recording']}_{version}{'_仮曲入り' if prov else ''}.mp4"


def remix(spec: dict, video: str | Path, audio: dict, version: str, out: str | Path) -> Path:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    total = duration(video)
    tl = timeline(spec)
    if audio.get("bgm") and Path(audio["bgm"]["path"]).exists():
        audio = {**audio, "bgm": {**audio["bgm"], "_len": duration(audio["bgm"]["path"])}}
    extra, g = graph(audio, tl, total)
    dst = out / output_name(spec, audio, version)
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(video), *extra, "-filter_complex", g,
                    "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-t", f"{total:.3f}", "-movflags", "+faststart", str(dst)], check=True)
    return dst


def review_copy(dst: Path) -> Path:
    """承認の門に渡す確認用 360p（同じ書き出しの縮小版）。"""
    rv = dst.with_name(dst.stem + "_確認用360p.mp4")
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(dst), "-vf", "scale=-2:360",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(rv)], check=True)
    return rv


def clip(dst: Path, start: float, length: float, tag: str) -> Path:
    """聞き比べ用の短い切り出し（映像はそのまま写すので数秒で済む）。"""
    c = dst.with_name(f"{dst.stem}_聞き比べ_{tag}.mp4")
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{max(0.0, start):.3f}", "-i", str(dst),
                    "-t", f"{length:.3f}", "-c", "copy", str(c)], check=True)
    return c


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="仕上げ版の音だけを差し替える（OP の曲・BGM・音割れ止め）")
    p.add_argument("spec", help="episode の指定（backend/config/episode/<収録ID>.json）")
    p.add_argument("video", help="仕上げ版の mp4（episode の出力）")
    p.add_argument("--audio", required=True, help="音の指定（AUDIO.json）")
    p.add_argument("--version", required=True, help="出力の版（例 v67）")
    p.add_argument("--out", default=".")
    p.add_argument("--review", action="store_true", help="確認用 360p も作る")
    p.add_argument("--clip", nargs=2, type=float, action="append", default=[], metavar=("本編の秒", "長さ"),
                   help="聞き比べ用の切り出し。番組 OP は --clip -1 30（頭から）")
    a = p.parse_args(argv)
    spec = json.loads(Path(a.spec).read_text(encoding="utf-8"))
    audio = json.loads(Path(a.audio).read_text(encoding="utf-8"))
    tl = timeline(spec)
    print(f"番組 OP: 0〜{tl['program']:.1f}秒 ／ 本編の頭: {tl['body']:.1f}秒（本編の秒 + {tl['body']:.1f} = 仕上げ版の秒）")
    dst = remix(spec, a.video, audio, a.version, a.out)
    print(dst)
    for s, length in a.clip:
        at = 0.0 if s < 0 else tl["body"] + s
        print(clip(dst, at, length, "OP" if s < 0 else f"{int(s)}s"))
    if a.review:
        print(review_copy(dst))
    return 0


if __name__ == "__main__":
    sys.exit(main())
