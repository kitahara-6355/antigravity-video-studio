"""番組共通の OP（どの回でも同じ）を、単体の動画の資産として書き出す（AI を呼ばない・0円）。

- 収録の絵は使わない文字だけの映像。言葉が左から書き足されていき、最後に番組名で締める
- 横（本編用 1280x720）と縦（Shorts 用 1080x1920）の2つを同じ指定から作る。曲も入れる
- 各回の本編は、この資産（mp4）を頭に付ける。OP を良くしたら資産を差し替えて本編を書き出し直す
  （2026-10-25 北原さん: 番組共通 OP を資産として別保存し、品質が上がったら各番組の OP を差し替える）

使い方（リポジトリ直下で）::

    python -m backend.program_package.opening PROGRAM.json --out DIR [--only 横 縦]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from backend.program_package import thumbnail as th

INK = (40, 16, 36)
GOLD_LINE = (214, 164, 70)
FPS = 30
SIZES = {"横": (1280, 720), "縦": (1080, 1920)}
SCALE = {(1280, 720): 1.0, (1080, 1920): 1.3}  # 縦はスマホで見るので文字を大きく


def _ease(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


def char_edges(text: str, font, cx: float) -> list[float]:
    """中央寄せの1行で、各文字の左端の x と最後の文字の右端（len+1 個）。"""
    d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    x0 = cx - d.textlength(text, font=font) / 2
    return [x0 + d.textlength(text[:i], font=font) for i in range(len(text) + 1)]


def column_alpha(edges: list[float], lt: float, interval: float, fade: float = 0.22, width: int = 1280) -> np.ndarray:
    """書き足していく文字の、画面の列ごとの濃さ（0〜1、形は (1, width, 1)）。

    i 文字目の左端は i*interval 秒後、右端は (i+1)*interval 秒後に出始める。境目はぼかすので、
    きっちり一文字ずつではなく、筆で左から書き足されていくように見える（2026-10-23 北原さん）。
    縁取りの分は両端の文字に含める。
    """
    xs = np.arange(width, dtype=np.float32)
    pos = np.interp(xs, edges, np.arange(len(edges), dtype=np.float32))  # 何文字目のどこか（端の外は端と同じ）
    x = np.clip((lt - pos * interval) / fade, 0, 1)
    return (1 - (1 - x) ** 3)[None, :, None]


def wrap(lines: list[str], font, limit: float) -> list[str]:
    """画面の幅に収まらない行を、空白の所で2行に分ける（縦の画面用）。"""
    d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    out = []
    for s in lines:
        if d.textlength(s, font=font) <= limit or " " not in s:
            out.append(s)
            continue
        cut = min((i for i, c in enumerate(s) if c == " "), key=lambda i: abs(i - len(s) / 2))
        out += [s[:cut], s[cut + 1:]]
    return out


def length(program: dict) -> float:
    return len(program["slides"]) * program["slide_seconds"] + program["title_seconds"]


def output_name(program: dict, form: str) -> str:
    # 仮の曲を入れた版は公開に使わない。名前で分かるようにする
    tag = "_仮曲入り" if (program.get("music") or {}).get("provisional") else ""
    return f"番組OP_{program['version']}_{form}{tag}.mp4"


STYLE = {"reveal": "brush", "background": "glow", "finish": "sweep"}  # 2026-10-23 北原さんが OK した形
CHOICES = {
    "reveal": {  # 言葉と番組名の現れ方
        "brush": "左から筆で書き足していく（境目をぼかす）",
        "rise": "行ごとに下から浮き上がる",
        "blur": "ぼんやりから焦点が合う",
        "stagger": "一文字ずつ小さく跳ねて出る",
    },
    "background": {  # 背景
        "glow": "薄紫の中央が明るい（動かない）",
        "drift": "光がゆっくり漂う",
        "washi": "和紙の繊維の質感",
        "gold_dust": "金の粉がゆっくり舞い上がる",
    },
    "finish": {  # 番組名の締め
        "sweep": "光が一度走る",
        "seal": "朱の落款が押される",
        "brush_line": "金の筆線が下に引かれる",
        "halo": "金の光がふわっと灯る",
    },
}


def style_of(program: dict) -> dict:
    st = {**STYLE, **program.get("style", {})}
    for k, v in st.items():
        if k in CHOICES and v not in CHOICES[k]:
            raise SystemExit(f"style.{k} に「{v}」はありません（{' / '.join(CHOICES[k])}）")
    return st


def _glow(theme: dict, size: tuple[int, int], cx: float = 0.0, cy: float = 0.38) -> np.ndarray:
    """薄紫の背景（中央が明るい）。cx・cy で明るい所をずらす。粒の質感は毎回同じ。"""
    w, h = size
    y = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    x = np.linspace(-1, 1, w, dtype=np.float32)[None, :]
    glow = np.clip(1 - ((x - cx) ** 2 * 0.75 + (y - cy) ** 2 * 1.8), 0, 1) ** 1.2
    light, deep = np.array(theme["light"], dtype=np.float32), np.array(theme["deep"], dtype=np.float32)
    return (deep + (light - deep) * glow[..., None]) / 255


def _washi(size: tuple[int, int]) -> np.ndarray:
    """和紙の繊維（白い細い筋）の層。RGBA 0〜1。毎回同じ。"""
    w, h = size
    rng = np.random.default_rng(7)
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for _ in range(int(w * h / 900)):
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        ang, ln = rng.uniform(0, np.pi), rng.uniform(8, 46)
        pts = [(x + np.cos(ang + 0.3 * np.sin(j)) * ln * j / 4, y + np.sin(ang + 0.3 * np.sin(j)) * ln * j / 4)
               for j in range(5)]
        d.line(pts, fill=(255, 250, 252, int(rng.uniform(40, 110))), width=int(rng.choice([1, 1, 2])))
    return np.asarray(im.filter(ImageFilter.GaussianBlur(0.7)), dtype=np.float32) / 255


class _Background:
    def __init__(self, kind: str, theme: dict, size: tuple[int, int]):
        self.kind, self.theme, self.size = kind, theme, size
        w, h = size
        noise = np.random.default_rng(1).normal(0, 2.5, (h, w, 3)).astype(np.float32) / 255  # 質感（毎回同じ）
        self.noise = noise
        self.still = np.asarray(th.background(theme, stripes=False, size=size), dtype=np.float32) / 255
        if kind == "washi":
            fib = _washi(size)
            self.still = self.still * (1 - fib[..., 3:4]) + fib[..., :3] * fib[..., 3:4]
        if kind == "gold_dust":
            rng = np.random.default_rng(3)
            n = int(w * h / 6000)
            self.dust = np.stack([rng.uniform(0, w, n), rng.uniform(0, h, n), rng.uniform(16, 40, n),
                                  rng.uniform(1.6, 4.0, n), rng.uniform(0, 2 * np.pi, n)], axis=1)

    def at(self, t: float) -> np.ndarray:
        if self.kind == "drift":
            cx, cy = 0.45 * np.sin(2 * np.pi * t / 10), 0.38 + 0.12 * np.cos(2 * np.pi * t / 8)
            return np.clip(_glow(self.theme, self.size, cx, cy) + self.noise, 0, 1)
        if self.kind == "gold_dust":
            f = self.still.copy()
            w, h = self.size
            gold = np.array([1.0, 0.86, 0.55], dtype=np.float32)
            for x, y, v, r, ph in self.dust:
                yy = (y - v * t) % h
                xx = x + 6 * np.sin(t * 0.8 + ph)
                a = 0.55 + 0.45 * np.sin(t * 2.2 + ph)
                x0, x1, y0, y1 = int(max(0, xx - 3 * r)), int(min(w, xx + 3 * r + 1)), int(max(0, yy - 3 * r)), int(min(h, yy + 3 * r + 1))
                if x0 >= x1 or y0 >= y1:
                    continue
                gx, gy = np.meshgrid(np.arange(x0, x1) - xx, np.arange(y0, y1) - yy)
                m = (a * 0.95 * np.exp(-(gx ** 2 + gy ** 2) / (2 * (r / 1.6) ** 2)))[..., None].astype(np.float32)
                f[y0:y1, x0:x1] = f[y0:y1, x0:x1] * (1 - m) + gold * m
            return f
        return self.still


def _rows(lay: np.ndarray) -> tuple[int, int]:
    """層の中で字のある行の範囲（上端・下端）。"""
    r = np.nonzero(lay[..., 3].max(axis=1) > 0)[0]
    return (int(r[0]), int(r[-1]) + 1) if len(r) else (0, 0)


def _reveal(kind: str, lay0: np.ndarray, e: list[float], lt: float, step: float, w: int, pitch: float,
            blurs: list[np.ndarray] | None = None, fade: float = 0.22) -> np.ndarray:
    """1行の言葉を、選んだ現れ方で lt 秒目の姿にする（RGBA 0〜1）。"""
    if kind == "brush":
        lay = lay0.copy()
        lay[..., 3:4] *= column_alpha(e, lt, step, fade=fade, width=w)
        return lay
    if kind == "rise":
        p = _ease(lt / 0.7)
        y0, y1 = _rows(lay0)
        dy = round((1 - p) * (y1 - y0) * 0.9)
        lay = np.zeros_like(lay0)
        lay[y0 + dy:y1] = lay0[y0:y1 - dy] if dy else lay0[y0:y1]
        lay[..., 3:4] *= p
        return lay
    if kind == "blur":
        p = _ease(lt / 0.8)
        idx = min(int(p * (len(blurs) - 1) + 0.5), len(blurs) - 1)
        lay = blurs[idx].copy()
        lay[..., 3:4] *= p
        return lay
    if kind == "stagger":
        lay = np.zeros_like(lay0)
        n = len(e) - 1
        for i in range(n):
            a = _ease((lt - i * 0.06) / 0.45)
            if a <= 0:
                continue
            x0 = 0 if i == 0 else round(e[i])
            x1 = w if i == n - 1 else round(e[i + 1])
            dy = round((1 - a) * pitch * 0.35)
            band = np.roll(lay0[:, x0:x1], dy, axis=0)
            band[..., 3:4] *= a
            lay[:, x0:x1] = band
        return lay
    raise ValueError(kind)


def _reveal_length(kind: str, chars: int, step: float) -> float:
    """1行が出そろうまでの秒数（次の行を始める時刻に使う）。"""
    return {"brush": chars * step, "rise": 0.5, "blur": 0.6, "stagger": chars * 0.06 + 0.2}[kind]


def frames(program: dict, size: tuple[int, int]):
    """OP のコマを順に返す（rgb の配列 0〜1）。"""
    w, h = size
    st = style_of(program)
    slides, sec, tsec = program["slides"], program["slide_seconds"], program["title_seconds"]
    step, tstep = program.get("char_seconds", 0.12), program.get("title_char_seconds", 0.24)
    theme = program["theme"]
    back = _Background(st["background"], theme, size)
    scale = SCALE.get(size, 1.0)
    sf = th.font("mincho", round(56 * scale))
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1))).textlength(program["name"], font=th.font("mincho", 116))
    nf = th.font("mincho", round(116 * min(scale, (w - 120) / probe)))  # 番組名は画面の幅に収める
    gold = np.array(GOLD_LINE, dtype=np.float32) / 255
    cy, pitch = h / 2 + 20, 78 * scale

    def image(draw) -> Image.Image:
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw(im)
        return im

    def arr(im: Image.Image) -> np.ndarray:
        return np.asarray(im, dtype=np.float32) / 255

    def blur_stack(im: Image.Image) -> list[np.ndarray] | None:
        if st["reveal"] != "blur":
            return None
        return [arr(im.filter(ImageFilter.GaussianBlur(r))) if r else arr(im) for r in (12, 8, 5, 3, 1.5, 0)]

    def outlined(im, xy, s):
        ImageDraw.Draw(im).text(xy, s, font=sf, fill="white", anchor="ms", stroke_width=5, stroke_fill=INK)

    texts, blurs, edges, widths = [], [], [], []
    for sl in slides:
        lines = wrap(sl if isinstance(sl, list) else [sl], sf, w - 120)
        ys = [cy + (i - (len(lines) - 1) / 2) * pitch for i in range(len(lines))]
        ims = [image(lambda im, s=s, y=y: outlined(im, (w / 2, y), s)) for s, y in zip(lines, ys, strict=True)]
        texts.append([arr(im) for im in ims])
        blurs.append([blur_stack(im) for im in ims])
        edges.append([char_edges(s, sf, w / 2) for s in lines])
        widths.append(max(e[-1] - e[0] for e in edges[-1]))
    span = pitch * (max(len(t) for t in texts) - 1)  # 行が増えたら金の線も上下に開く
    ty = h / 2 + round(nf.size * 0.345)
    title_im = image(lambda im: th.gradient_text(im, (w / 2, ty), program["name"], nf, th.GOLD, anchor="ms", stroke=11))
    title, tblurs = arr(title_im), blur_stack(title_im)
    tedges = char_edges(program["name"], nf, w / 2)
    tw = tedges[-1] - tedges[0]
    xs = np.arange(w, dtype=np.float32)[None, :]
    tdone = 0.2 + _reveal_length(st["reveal"], len(tedges) - 1, tstep) + 0.3  # 番組名が出そろう時刻
    if st["finish"] == "seal":
        side = int(nf.size * 0.82)
        seal = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        sd = ImageDraw.Draw(seal)
        sd.rounded_rectangle([2, 2, side - 3, side - 3], radius=side // 10, fill=(186, 38, 34, 235))
        sd.rounded_rectangle([side * 0.08, side * 0.08, side * 0.92, side * 0.92], radius=side // 14,
                             outline=(250, 236, 226, 230), width=max(2, side // 30))
        sf2 = th.font("mincho", int(side * 0.36))
        sd.text((side / 2, side * 0.3), "美", font=sf2, fill=(250, 236, 226), anchor="mm")
        sd.text((side / 2, side * 0.7), "麗", font=sf2, fill=(250, 236, 226), anchor="mm")
        seal_xy = (int(w / 2 + tw / 2 + nf.size * 0.25), int(ty - nf.size * 0.62))
        if seal_xy[0] + side > w - 10:  # 縦の画面で右に入らなければ番組名の下に置く
            seal_xy = (int(w / 2 - side / 2), int(ty + nf.size * 0.55))
    if st["finish"] == "halo":
        halo = np.clip(arr(title_im.filter(ImageFilter.GaussianBlur(nf.size * 0.3)))[..., 3:4] * 1.8, 0, 1)

    def over(frame, lay, alpha):
        a = lay[..., 3:4] * alpha
        return frame * (1 - a) + lay[..., :3] * a

    def gold_lines(frame, half, y1, y2, alpha):
        x0, x1 = int(max(0, w / 2 - half)), int(min(w, w / 2 + half))
        for y in (y1, y2):
            frame[y:y + 3, x0:x1] = frame[y:y + 3, x0:x1] * (1 - alpha) + gold * alpha
        return frame

    for k in range(round(length(program) * FPS)):
        t = k / FPS
        f = back.at(t).copy()
        i = int(t // sec)
        if i < len(slides):
            lt = t - i * sec
            out = 1 - _ease((lt - (sec - 0.45)) / 0.45)
            f = gold_lines(f, (widths[i] / 2 + 40) * _ease(lt / 0.9), int(h // 2 - 90 * scale - span / 2),
                           int(h // 2 + 80 * scale + span / 2), out)
            start = 0.15
            for lay0, bl, e in zip(texts[i], blurs[i], edges[i], strict=True):  # 行が複数なら上の行から順に出す
                f = over(f, _reveal(st["reveal"], lay0, e, lt - start, step, w, pitch, bl), out)
                start += _reveal_length(st["reveal"], len(e) - 1, step) + 0.1
        else:
            lt = t - len(slides) * sec
            if st["finish"] != "brush_line":
                f = gold_lines(f, (tw / 2 + 60) * _ease(lt / 1.2), h // 2 - round(nf.size * 0.69),
                               h // 2 + round(nf.size * 0.62), 1.0)
            lay = _reveal(st["reveal"], title, tedges, lt - 0.2, tstep, w, nf.size * 0.7, tblurs, fade=0.3)
            if st["finish"] == "sweep":  # 書き終わったあと、光が一度だけ左から右へ走る
                sweep = np.clip(1 - np.abs(xs - (-200 + (w + 400) * min(max((lt - tdone) / 0.9, 0), 1))) / 120, 0, 1)
                lay[..., :3] = np.clip(lay[..., :3] + 0.45 * sweep[..., None], 0, 1)
            if st["finish"] == "halo":
                a = 0.85 * _ease((lt - tdone) / 1.2)  # ふわっと灯って、そのまま残る
                f = f * (1 - halo * a) + np.array([1.0, 0.84, 0.48], dtype=np.float32) * halo * a
            if st["finish"] == "brush_line":  # 金の筆線が左から右へ。入りは太く、抜きは細く
                p = _ease((lt - tdone + 0.4) / 0.7)
                x0, x1 = w / 2 - tw / 2 - 30, w / 2 - tw / 2 - 30 + (tw + 60) * p
                y = int(ty + nf.size * 0.28)
                for x in range(int(x0), int(x1)):
                    q = (x - x0) / (tw + 60)
                    th_ = max(1, round(12 * (1 - q) + 3 * q))
                    f[y - th_ // 2:y + (th_ + 1) // 2, x] = gold
            f = over(f, lay, 1.0)
            if st["finish"] == "seal" and lt >= tdone:
                p = _ease((lt - tdone) / 0.25)
                sc = 1.35 - 0.35 * p
                s2 = seal.resize((max(1, int(side * sc)),) * 2)
                sa = np.asarray(s2, dtype=np.float32) / 255
                ox, oy = seal_xy[0] - (s2.width - side) // 2, seal_xy[1] - (s2.height - side) // 2
                x0, y0 = max(0, ox), max(0, oy)
                x1, y1 = min(w, ox + s2.width), min(h, oy + s2.height)
                sub = sa[y0 - oy:y1 - oy, x0 - ox:x1 - ox]
                a = sub[..., 3:4] * p
                f[y0:y1, x0:x1] = f[y0:y1, x0:x1] * (1 - a) + sub[..., :3] * a
            fade = _ease((lt - (tsec - 0.6)) / 0.6)  # 最後は少しだけ暗くして次へ
            f = f * (1 - 0.25 * fade)
        yield f


def render(program: dict, dst: Path, form: str = "横") -> float:
    """OP を1本書き出す（曲があれば入れる。無ければ無音）。長さ（秒）を返す。"""
    w, h = SIZES[form]
    total = length(program)
    music = program.get("music")
    with tempfile.TemporaryDirectory() as tmp:
        silent = Path(tmp) / "v.mp4"
        proc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
                                 "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p",
                                 str(silent)], stdin=subprocess.PIPE)
        for f in frames(program, (w, h)):
            proc.stdin.write((np.clip(f, 0, 1) * 255).astype(np.uint8).tobytes())
        proc.stdin.close()
        if proc.wait():
            raise SystemExit("番組 OP の書き出しに失敗")
        if music:
            st = music.get("start", 0.0)  # 曲のどこから使うか（番組名で盛り上がる所に合わせる）
            mix = (f"[1:a]atrim={st}:{st + total:.3f},asetpts=PTS-STARTPTS,"
                   f"aformat=sample_rates=48000:channel_layouts=stereo,volume={music.get('volume', 1.0)},"
                   f"afade=t=in:d=0.3,afade=t=out:st={total - 1.5:.3f}:d=1.5[a]")
            audio = ["-i", music["path"], "-filter_complex", mix, "-map", "0:v", "-map", "[a]"]
        else:
            audio = ["-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v", "-map", "1:a"]
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(silent), *audio, "-c:v", "copy", "-c:a", "aac",
                        "-b:a", "160k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(dst)], check=True)
    return total


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="番組共通の OP を単体の動画（横・縦）として書き出す")
    p.add_argument("program", help="番組の指定（backend/config/program/<番組名>.json）")
    p.add_argument("--out", default=".")
    p.add_argument("--only", nargs="*", choices=list(SIZES))
    a = p.parse_args(argv)
    program = load(a.program)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for form in a.only or list(SIZES):
        dst = out / output_name(program, form)
        render(program, dst, form)
        print(dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
