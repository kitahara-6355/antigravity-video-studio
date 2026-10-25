"""目視OKの完成版に、番組の飾り（OP・章の見出し・補足のテロップ・ED）を足す（AI を呼ばない・0円）。

- 本編は完成版をそのまま使う（字幕は焼き込み済み）。絵の中身は1コマも変えない
- 番組 OP: 文字だけの映像。言葉が左から書き足されていき、最後に番組名（どの回でも同じ・曲を重ねる）
- 今回の OP: 本編の名場面をいくつかつなぎ、最後にタイトル（色紙と番組名・ゲスト名）
- 名前のポップ: あいさつと紹介の所に、肩書きと名前（頭の来る所 avoid には掛けない）
- 章の見出し: 投稿パッケージのチャプターの時刻に、左上（第1章は右上）の壁の所へ8秒出す
- 補足のテロップ: 知らないと分かりにくい言葉に、上の真ん中へ短い説明を出す
- ED: プレゼントの告知（締切は公開日から自動で出す）とチャンネル登録の呼びかけ。右側は YouTube の終了画面を置く余白
- OP の分だけ本編が後ろにずれるので、チャプターもずらして書き出す（YouTube の決まりも確かめる）

使い方（リポジトリ直下で）::

    python -m backend.program_package.episode SPEC.json --out DIR [--cards]   # --cards は静止画だけ
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from backend.program_package import chapters as ch
from backend.program_package import opening as opening_mod
from backend.program_package import thumbnail as th

W, H = 1280, 720
FADE = 0.4
INK = (40, 16, 36)
GOLD_LINE = (214, 164, 70)
PANEL = (40, 14, 36, 170)
CHAPTER_Y = 42  # 章の見出しの上端（絵の上端 37 のすぐ下）


def stamp(t: float) -> str:
    t = int(t)
    h, rem = divmod(t, 3600)
    return f"{h}:{rem // 60:02d}:{rem % 60:02d}" if h else f"{rem // 60}:{rem % 60:02d}"


def board_of(spec: dict) -> tuple[Image.Image, dict]:
    tspec = json.loads(Path(spec["thumbnail"]).read_text(encoding="utf-8"))
    tspec["lock"] = spec.get("lock", tspec["lock"])
    s = tspec["shikishi"]
    return th.shikishi(th.frame(tspec, Path(spec["raw"]), s["at"]).crop(tuple(s["crop"])), 340), tspec["theme"]


def outlined(d: ImageDraw.ImageDraw, xy, s: str, size: int, fill="white", anchor="ls") -> None:
    d.text(xy, s, font=th.font("mincho", size), fill=fill, anchor=anchor, stroke_width=5, stroke_fill=INK)


def title_card(spec: dict, board: Image.Image, theme: dict) -> Image.Image:
    """OP の最後の1枚（T2: 色紙が左・文字が右）。"""
    t = spec["title"]
    im = th.background(theme)
    th.paste_board(im, board, 360, 360, angle=-3)
    x = 700
    th.gradient_text(im, (x, 200), t["series"], th.font("mincho", 60), th.GOLD, stroke=8)
    th.gradient_text(im, (x, 290), t["episode"], th.font("mincho", 60), th.RED, stroke=8)
    d = ImageDraw.Draw(im)
    d.line([(x, 340), (W - 80, 340)], fill=GOLD_LINE, width=3)
    outlined(d, (x, 420), t["tag"], 36)
    th.gradient_text(im, (x, 520), t["guest"], th.font("mincho", 76), th.GOLD, stroke=9)
    outlined(d, (x, 610), t["host"], 34)
    return im


def name_card(lines: list[str], name: str, y: int, right: int | None = None,
              pitch: int = 30, size: int = 56) -> Image.Image:
    """名前のポップ（肩書きと名前）。右寄せで、その人の近くの壁の所に出す（right は右端の x）。

    pitch は肩書きの行の間隔、size は名前の大きさ。頭の上の壁が狭い場面では詰める。
    """
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    right = right or th.FRAME[2] - 40
    sf, nf = th.font("gothic", 24), th.font("mincho", size)
    for i, line in enumerate(lines):
        d.text((right, y + pitch * i), line, font=sf, fill="white", anchor="ra", stroke_width=4, stroke_fill=INK)
    ly = y + pitch * len(lines) + 8
    w = max(d.textlength(name, font=nf), *(d.textlength(t, font=sf) for t in lines)) if lines else d.textlength(name, font=nf)
    d.line([(right - w, ly), (right, ly)], fill=GOLD_LINE + (255,), width=2)
    th.gradient_text(im, (right, ly + round(size * 1.18)), name, nf, th.GOLD, anchor="rs", stroke=8)
    return im


def pop_card(pop: dict) -> Image.Image:
    """指定ファイルの name_pops の1件から名前のポップを作る。"""
    return name_card(pop["lines"], pop["name"], pop["y"], pop.get("right"), pop.get("pitch", 30), pop.get("size", 56))


def pop_hits(pop: dict) -> list[list[int]]:
    """名前のポップが掛かってしまう「頭の来る所」（指定の avoid）を返す。空なら掛からない。"""
    a = np.asarray(pop_card(pop))[..., 3]
    return [z for z in pop.get("avoid", []) if a[z[1]:z[3], z[0]:z[2]].any()]


def chapter_card(n: int, text: str, right: bool = False) -> Image.Image:
    """章の見出し（C2: 帯なし・金の章番号と白い縁取りの明朝）。透明の1枚で、左上の壁の所に出す。

    美麗さんの頭に近づかないよう、絵の上端（th.FRAME の y=37）まで詰める（2026-10-23 北原さん）。
    right=True は右上に寄せる（美麗さん一人の場面は頭が左上に来るため。第1章）。
    """
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    f = th.font("mincho", 38)
    w = d.textlength(text, font=f)
    x, y = (th.FRAME[2] - 40 - w if right else 48), CHAPTER_Y
    d.text((x, y), f"第{n}章", font=th.font("mincho", 24), fill=(255, 226, 140), stroke_width=4, stroke_fill=INK)
    d.line([(x, y + 32), (x + w, y + 32)], fill=GOLD_LINE + (255,), width=2)
    d.text((x, y + 38), text, font=f, fill="white", stroke_width=5, stroke_fill=INK)
    return im


def telop_card(head: str, body: str) -> Image.Image:
    """補足のテロップ。上の真ん中（二人の頭の間の壁）に、言葉と短い説明を出す。"""
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    hf, bf = th.font("mincho", 34), th.font("gothic", 24)
    lines = body.split("\n")
    w = max([d.textlength(head, font=hf)] + [d.textlength(s, font=bf) for s in lines])
    cx, y = (th.FRAME[0] + th.FRAME[2]) / 2, 62
    x0, x1, y1 = cx - w / 2 - 22, cx + w / 2 + 22, y + 52 + 34 * len(lines)
    d.rectangle([x0, y - 6, x1, y1], fill=PANEL)
    d.rectangle([x0, y1 - 4, x1, y1], fill=GOLD_LINE + (255,))
    d.text((cx, y), head, font=hf, fill=(255, 226, 140), anchor="mt")
    for i, s in enumerate(lines):
        d.text((cx, y + 48 + 34 * i), s, font=bf, fill="white", anchor="mt")
    return im


def deadline_text(e: dict) -> str:
    """プレゼントの締切。公開日（publish_date）の deadline_days 日後。公開日が未定なら【未定】。"""
    if not e.get("publish_date"):
        return "【未定】"
    d = date.fromisoformat(e["publish_date"]) + timedelta(days=e.get("deadline_days", 14))
    return f"{d.month}月{d.day}日（{'月火水木金土日'[d.weekday()]}）まで"


def gift_lines(e: dict) -> list[str]:
    return [s.replace("{deadline}", deadline_text(e)) for s in e["gift_lines"]]


def end_card(spec: dict, board: Image.Image, theme: dict) -> Image.Image:
    """ED。左に告知、右半分は YouTube の終了画面（動画・登録ボタン）を置く余白。"""
    e = spec["ending"]
    im = th.background(theme)
    d = ImageDraw.Draw(im)
    x = 70
    th.gradient_text(im, (x, 130), e["gift_title"], th.font("mincho", 50), th.RED, stroke=8)
    for i, s in enumerate(gift_lines(e)):
        outlined(d, (x, 205 + 50 * i), s, 32)
    small = board.resize((board.width * 3 // 5, board.height * 3 // 5))
    th.paste_board(im, small, x + 110, 470, angle=-3)
    th.gradient_text(im, (x, 680), e["subscribe"], th.font("mincho", 40), th.GOLD, stroke=7)
    d.rectangle([700, 90, W - 60, H - 90], outline=GOLD_LINE, width=2)  # 終了画面の要素を置く所の目安
    return im


def shifted_chapters(spec: dict, op_len: float) -> list[tuple[int, str]]:
    body = ch.parse(Path(spec["package"]).read_text(encoding="utf-8"))
    out = [(0, spec["op_chapter"])]
    out += [(round(t + op_len), title) for t, title in body]
    return out


def program_of(spec: dict) -> dict | None:
    """番組共通 OP の指定（spec の program が指す番組の指定）。無ければ None。"""
    return opening_mod.load(spec["program"]) if spec.get("program") else None


def program_length(spec: dict) -> float:
    p = program_of(spec)
    return opening_mod.length(p) if p else 0.0


def op_length(spec: dict) -> float:
    """本編より前の長さ。番組 OP（あれば）→ 今回の名場面 → タイトル。つなぎ目はどれも短く重ねる。"""
    o = spec["opening"]
    cuts = sum(b - a for a, b in o["cuts"])
    n = len(o["cuts"]) + 1
    episode = cuts + o["title_seconds"] - FADE * (n - 1)
    prog = program_length(spec)
    return prog + episode - FADE if prog else episode


def build(spec: dict, out: Path, cards_only: bool = False) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    board, theme = board_of(spec)
    body = ch.parse(Path(spec["package"]).read_text(encoding="utf-8"))
    cards = {"title": title_card(spec, board, theme), "ending": end_card(spec, board, theme)}
    for n, (t, title) in enumerate(body, start=1):
        if title not in spec.get("chapters_skip", []):
            cards[f"ch{n:02d}"] = chapter_card(n, title, n in spec.get("chapters_right", []))
    for i, pop in enumerate(spec.get("name_pops", [])):
        cards[f"np{i:02d}"] = pop_card(pop)
    for i, tp in enumerate(spec.get("telops", [])):
        cards[f"tp{i:02d}"] = telop_card(tp["head"], tp["body"])
    if cards_only:
        for k, im in cards.items():
            im.save(out / f"{k}.png")
        return out
    src = Path(spec["source"])
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                str(src)], capture_output=True, text=True, check=True).stdout)
    op = op_length(spec)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for k, im in cards.items():
            im.save(tmp / f"{k}.png")
        spec = {**spec, "_theme": theme}
        graph, inputs = _graph(spec, body, dur, tmp)
        music = (program_of(spec) or {}).get("music") or {}
        # 仮の曲を入れた版は公開に使わない。名前で分かるようにする
        tag = "_仮曲入り" if music.get("provisional") else ""
        dst = out / f"{spec['recording']}_{spec['version']}{tag}.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", graph,
                        "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "20", "-preset", "medium",
                        "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
                        "-movflags", "+faststart", str(dst)], check=True)
    chapters = shifted_chapters(spec, op)
    total = op + dur + spec["ending"]["seconds"]
    bad = ch.problems(chapters, total)
    (out / f"{spec['recording']}_{spec['version']}_チャプター.txt").write_text(
        "\n".join(f"{stamp(t)} {s}" for t, s in chapters) + "\n", encoding="utf-8")
    if bad:
        raise SystemExit("チャプターが YouTube の決まりに合わない: " + " / ".join(bad))
    return dst


def _chain(g: list[str], clips: list[tuple[str, str, float]], tag: str) -> tuple[str, str, float]:
    """絵と音の組を順につなぐ。つなぎ目は FADE 秒重ねる。"""
    v, a, length = clips[0]
    for j, (nv, na, nl) in enumerate(clips[1:]):
        g.append(f"[{v}][{nv}]xfade=transition=fade:duration={FADE}:offset={length - FADE:.3f}[{tag}v{j}];"
                 f"[{a}][{na}]acrossfade=d={FADE}[{tag}a{j}]")
        v, a, length = f"{tag}v{j}", f"{tag}a{j}", length + nl - FADE
    return v, a, length


def _graph(spec: dict, body, dur: float, tmp: Path) -> tuple[str, list[str]]:
    o, e = spec["opening"], spec["ending"]
    src = spec["source"]
    inputs = ["-i", src, "-loop", "1", "-framerate", "30", "-t", str(o["title_seconds"]), "-i", str(tmp / "title.png"),
              "-loop", "1", "-framerate", "30", "-t", str(e["seconds"]), "-i", str(tmp / "ending.png")]
    g = []
    n_in = 3

    def cut(path: str, a: float, b: float, tag: str) -> tuple[str, str, float]:
        # 場面ごとに別の入力として読む（本編と同じ入力から切ると、そこまでの本編のコマを
        # 全部メモリに溜めてしまい、42分の本編では落ちる）
        nonlocal n_in
        inputs.extend(["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", path])
        g.append(f"[{n_in}:v]setpts=PTS-STARTPTS,fps=30,format=yuv420p,scale={W}:{H}[{tag}v];"
                 f"[{n_in}:a]asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo[{tag}a]")
        n_in += 1
        return f"{tag}v", f"{tag}a", b - a

    def still(png: Path, sec: float, tag: str) -> tuple[str, str, float]:
        nonlocal n_in
        inputs.extend(["-loop", "1", "-framerate", "30", "-t", f"{sec}", "-i", str(png)])
        g.append(f"[{n_in}:v]format=yuv420p,fps=30[{tag}v];anullsrc=r=48000:cl=stereo,atrim=0:{sec}[{tag}a]")
        n_in += 1
        return f"{tag}v", f"{tag}a", sec

    # 今回の名場面 → タイトル
    clips = [cut(src, a, b, f"o{i}") for i, (a, b) in enumerate(o["cuts"])]
    g.append(f"[1:v]format=yuv420p,fps=30[tv];anullsrc=r=48000:cl=stereo,atrim=0:{o['title_seconds']}[ta]")
    op_v, op_a, op_l = _chain(g, [*clips, ("tv", "ta", o["title_seconds"])], "x")
    # 番組 OP（どの回でも同じ）。資産の mp4（曲入り）をそのまま頭に付ける。資産が無ければここで作る
    p = program_of(spec)
    if p:
        asset = spec.get("program_asset")
        if asset:
            seq = Path(asset)
        else:
            seq = tmp / "program.mp4"
            opening_mod.render(p, seq, "横")
        pl = opening_mod.length(p)
        inputs.extend(["-i", str(seq)])
        g.append(f"[{n_in}:v]fps=30,format=yuv420p,scale={W}:{H}[pv];"
                 f"[{n_in}:a]aformat=sample_rates=48000:channel_layouts=stereo[pa]")
        n_in += 1
        op_v, op_a, op_l = _chain(g, [("pv", "pa", pl), (op_v, op_a, op_l)], "z")
    # 本編: 章の見出し・テロップ・名前のポップを、時刻の所でふわっと出して消す
    g.append("[0:v]fps=30,format=yuv420p[m0]")
    m = "m0"
    shows = []
    for n, (t, title) in enumerate(body, start=1):
        if (tmp / f"ch{n:02d}.png").exists():
            shows.append((tmp / f"ch{n:02d}.png", t + (0.5 if n == 1 else 1.0), spec.get("chapter_seconds", 4.0)))
    for i, tp in enumerate(spec.get("telops", [])):
        shows.append((tmp / f"tp{i:02d}.png", tp["at"], tp.get("seconds", 5.0)))
    for i, pop in enumerate(spec.get("name_pops", [])):
        shows.append((tmp / f"np{i:02d}.png", pop["at"], pop.get("seconds", 7.0)))
    for k, (png, at, sec) in enumerate(shows):
        inputs += ["-loop", "1", "-framerate", "30", "-t", f"{sec:.2f}", "-i", str(png)]
        g.append(f"[{n_in}:v]format=rgba,fade=in:st=0:d={FADE}:alpha=1,fade=out:st={sec - FADE:.2f}:d={FADE}:alpha=1,"
                 f"setpts=PTS+{at:.3f}/TB[s{k}];[{m}][s{k}]overlay=0:0:eof_action=pass[m{k + 1}]")
        m = f"m{k + 1}"
        n_in += 1
    g.append(f"[2:v]format=yuv420p,fps=30,fade=in:st=0:d={FADE}[ev];"
             f"anullsrc=r=48000:cl=stereo,atrim=0:{e['seconds']}[ea]")
    g.append(f"[{op_v}][{op_a}][{m}][0:a][ev][ea]concat=n=3:v=1:a=1[v][a]")
    return ";".join(g), inputs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="完成版に OP・章の見出し・テロップ・ED を足す")
    p.add_argument("spec")
    p.add_argument("--out", default=".")
    p.add_argument("--cards", action="store_true", help="静止画だけ作る（確かめ用）")
    a = p.parse_args(argv)
    spec = json.loads(Path(a.spec).read_text(encoding="utf-8"))
    print(build(spec, Path(a.out), a.cards))
    return 0


if __name__ == "__main__":
    sys.exit(main())
