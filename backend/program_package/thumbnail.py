"""番組のサムネを、収録 raw のコマから組む（AI 画像生成を使わない・0円）。

構成は P1（2026-10-23 北原さん決定）: 背景は収録の壁の薄紫（美麗書院のテーマカラー）、
中央に色紙、左右に2人の笑顔を切り抜いて大きく、下に金と赤の明朝でキャッチ、両端に名前を縦書き。

- 人物は壁の色で抜く（クロマキー）。壁の前で撮った収録ならそのまま使える
- 色紙は揮毫の場面のコマから墨だけを抜き、金縁の新しい色紙に載せ直す
- 何を使ったかは backend/config/thumbnails/<収録ID>.json に残す（どのコマを選んだか・誰が決めたか）

使い方（リポジトリ直下で）::

    python -m backend.program_package.thumbnail --fetch-fonts
    python -m backend.program_package.thumbnail SPEC.json --raw RAW.mp4 --out DIR --options
    python -m backend.program_package.thumbnail SPEC.json --raw RAW.mp4 --out DIR --pick B3 K1
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from backend.logo_check import source_time

W, H = 1280, 720
FONT_DIR = Path(__file__).resolve().parents[1] / "data" / "fonts"
# Google Fonts（SIL Open Font License）
FONTS = {"mincho": "ShipporiMinchoB1.ttf", "gothic": "NotoSansJP-Black.ttf",
         # 番組の雰囲気えらびの書体（2026-10-26）: 筆・装飾の明朝・手書きのペン
         "fude": "YujiSyuku.ttf", "tokumin": "KaiseiTokumin-ExtraBold.ttf", "pen": "ZenKurenaido.ttf"}
FONT_CSS = {"mincho": "Shippori+Mincho+B1:wght@800", "gothic": "Noto+Sans+JP:wght@900",
            "fude": "Yuji+Syuku", "tokumin": "Kaisei+Tokumin:wght@800", "pen": "Zen+Kurenaido"}
GOLD = ((255, 244, 196), (214, 164, 70), (255, 226, 140), (150, 100, 30))
RED = ((255, 120, 120), (220, 20, 40), (150, 0, 20))
FRAME = (24, 37, 1163, 683)  # 収録の絵がある所（黒い縁を除く）
SIDES = {"left": (24, 37, 600, 500), "right": (620, 37, 1163, 500)}


def font_urls(css: str) -> list[str]:
    return re.findall(r"url\((https://fonts\.gstatic\.com/[^)]+\.ttf)\)", css)


def fetch_fonts() -> None:
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    for key, family in FONT_CSS.items():
        if (FONT_DIR / FONTS[key]).exists():  # 入れ直すと字形が変わりうるので、ある物は触らない
            continue
        with urllib.request.urlopen(f"https://fonts.googleapis.com/css2?family={family}") as r:
            url = font_urls(r.read().decode())[0]
        urllib.request.urlretrieve(url, FONT_DIR / FONTS[key])
        print(f"{FONTS[key]} ← {url}")


def font(key: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / FONTS[key]), size)


# ---- 切り抜き ----

def wall_mask(im: Image.Image) -> Image.Image:
    """壁（薄紫）を 0、人や物を 255 にした白黒。"""
    a = np.asarray(im.convert("RGB")).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    wall = (b - g > 7) & (r - g > 22) & (r - b > 10) & (r - b < 45) & (g > 60)
    m = Image.fromarray(np.where(wall, 0, 255).astype("uint8"))
    return m.filter(ImageFilter.MedianFilter(7)).filter(ImageFilter.MinFilter(5))


def head_of(mask: np.ndarray) -> tuple[int, float]:
    """白黒の人の形から、頭の上端の行と頭の中心の列を返す。"""
    rows = np.where(mask.sum(axis=1) > 12)[0]
    top = int(rows[0])
    cols = np.where(mask[top:top + 90].sum(axis=0) > 3)[0]
    return top, (cols[0] + cols[-1]) / 2


def cutout(im: Image.Image, k: float = 2.0):
    """人物を抜いて k 倍にし、(絵, 透明度, 頭の上端, 頭の中心) を返す。下端は背景に溶かす。"""
    m = wall_mask(im)
    top, cx = head_of(np.asarray(m) > 128)
    fade = Image.linear_gradient("L").resize(m.size).point(lambda v: 255 if v < 190 else int(255 * (255 - v) / 65))
    m = ImageChops.multiply(m.filter(ImageFilter.GaussianBlur(1.2)), fade)
    im = ImageEnhance.Brightness(im.convert("RGB")).enhance(1.08)
    im = ImageEnhance.Contrast(ImageEnhance.Color(im).enhance(1.08)).enhance(1.06)
    size = (round(im.width * k), round(im.height * k))
    im = im.resize(size, Image.LANCZOS).filter(ImageFilter.UnsharpMask(2, 70, 2))
    return im, m.resize(size, Image.LANCZOS), top * k, cx * k


def place(canvas: Image.Image, person: Image.Image, head_x: float, head_y: float = 70, k: float = 2.0) -> None:
    im, m, top, cx = cutout(person, k)
    canvas.paste(im, (round(head_x - cx), round(head_y - top)), m)


# ---- 色紙・文字 ----

def shikishi(board: Image.Image, w: int = 250) -> Image.Image:
    """揮毫のコマ（白黒）から墨だけを抜き、金縁の新しい色紙に載せ直す。"""
    ink = board.convert("L").point(lambda v: 255 if v < 95 else (0 if v > 150 else int(255 * (150 - v) / 55)))
    ImageDraw.Draw(ink).rectangle([0, int(ink.height * 0.9), ink.width, ink.height], fill=0)  # 下端の汚れ
    h = round(w * 1.12)
    out = Image.new("RGB", (w, h), (246, 240, 226))
    d = ImageDraw.Draw(out)
    d.rectangle([0, 0, w - 1, h - 1], outline=(196, 156, 72), width=7)
    d.rectangle([12, 12, w - 13, h - 13], outline=(214, 182, 110), width=1)
    ink = ink.resize((round(w * 0.86), round(w * 0.86 * ink.height / ink.width)), Image.LANCZOS)
    out.paste((18, 14, 16), ((w - ink.width) // 2, (h - ink.height) // 2), ink)
    return out


def paste_board(im: Image.Image, board: Image.Image, cx: int, cy: int, angle: float = -3) -> None:
    sh = Image.new("RGBA", (board.width + 60, board.height + 60), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rectangle([30, 36, 30 + board.width, 36 + board.height], fill=(0, 0, 0, 170))
    sh = sh.filter(ImageFilter.GaussianBlur(12)).rotate(angle, expand=True, resample=Image.BICUBIC)
    b = board.convert("RGBA").rotate(angle, expand=True, resample=Image.BICUBIC)
    im.paste(sh, (cx - sh.width // 2, cy - sh.height // 2 + 8), sh)
    im.paste(b, (cx - b.width // 2, cy - b.height // 2), b)


def gradient_text(im: Image.Image, xy, s: str, f, colors=GOLD, anchor: str = "ls", stroke: int = 8,
                  stroke_fill=(0, 0, 0)) -> None:
    """縁取り（既定は黒）の上に、上から下へ色が移る文字を置く（金・赤）。"""
    d = ImageDraw.Draw(im)
    top, bot = d.textbbox(xy, s, font=f, anchor=anchor, stroke_width=stroke)[1::2]
    d.text(xy, s, font=f, fill=stroke_fill, anchor=anchor, stroke_width=stroke, stroke_fill=stroke_fill)
    m = Image.new("L", im.size, 0)
    ImageDraw.Draw(m).text(xy, s, font=f, fill=255, anchor=anchor)
    ys = np.clip((np.arange(im.height) - top) / max(1, bot - top), 0, 1)
    stops = np.linspace(0, 1, len(colors))
    g = np.zeros((im.height, im.width, 3))
    for c in range(3):
        g[..., c] = np.interp(ys, stops, [col[c] for col in colors])[:, None]
    im.paste(Image.fromarray(g.astype("uint8")), (0, 0), m)


def boxed(im: Image.Image, cx: float, y: float, s: str, f) -> None:
    d = ImageDraw.Draw(im)
    tw = d.textlength(s, font=f)
    h = f.size + 26
    d.rectangle([cx - tw / 2 - 26, y, cx + tw / 2 + 26, y + h], fill=(10, 8, 10), outline=(196, 156, 72), width=3)
    d.rectangle([cx - tw / 2 - 20, y + 6, cx + tw / 2 + 20, y + h - 6], outline=(120, 92, 40), width=1)
    d.text((cx, y + h / 2), s, font=f, fill=(255, 236, 180), anchor="mm")


def vertical(im: Image.Image, x: float, y: float, s: str, f) -> None:
    d = ImageDraw.Draw(im)
    for ch in s:
        if ch == " ":
            y += f.size * 0.4
            continue
        d.text((x, y), ch, font=f, fill="white", anchor="ma", stroke_width=5, stroke_fill=(0, 0, 0))
        y += f.size * 1.02


def background(theme: dict, stripes: bool = True, size: tuple[int, int] | None = None) -> Image.Image:
    w, h = size or (W, H)
    y = np.linspace(0, 1, h)[:, None]
    x = np.linspace(-1, 1, w)[None, :]
    glow = np.clip(1 - (x ** 2 * 0.75 + (y - 0.38) ** 2 * 1.8), 0, 1) ** 1.2
    light, deep = np.array(theme["light"]), np.array(theme["deep"])
    a = deep + (light - deep) * glow[..., None]
    a += np.random.default_rng(1).normal(0, 2.5, a.shape)  # 質感（毎回同じ）
    im = Image.fromarray(np.clip(a, 0, 255).astype("uint8"))
    d = ImageDraw.Draw(im)
    for i in range(-3, 4) if stripes else ():  # 細い金の斜線
        x0 = w / 2 + i * 150
        d.line([(x0 - 260, h), (x0 + 260, 0)], fill=(206, 170, 104), width=1)
    return im


def shade(im: Image.Image, color, frm: float = 0.58, mx: int = 235) -> Image.Image:
    sh = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(sh)
    top = int(H * frm)
    for y in range(top, H):
        d.line([(0, y), (W, y)], fill=int(mx * min(1, 1.5 * (y - top) / (H - top))))
    return Image.composite(Image.new("RGB", (W, H), tuple(color)), im, sh)


CATCH = 84


def catch_width(spec: dict) -> float:
    d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    f = font("mincho", CATCH)
    return d.textlength(spec["text"]["line1"], font=f) + d.textlength(spec["text"]["line2"], font=f)


def compose(spec: dict, left: Image.Image, right: Image.Image, board: Image.Image) -> Image.Image:
    """P1 の構成で1枚に組む。left/right はその人の側を切った収録のコマ、board は色紙の所。"""
    t = spec["text"]
    im = background(spec["theme"])
    place(im, left, 290)
    place(im, right, 990)
    im = shade(im, spec["theme"]["shade"])
    paste_board(im, shikishi(board), W // 2, 250)
    boxed(im, W // 2, 440, t["tag"], font("mincho", 34))
    f = font("mincho", CATCH)
    w1 = ImageDraw.Draw(im).textlength(t["line1"], font=f)
    x = (W - catch_width(spec)) / 2
    gradient_text(im, (x, 640), t["line1"], f, RED)
    gradient_text(im, (x + w1, 640), t["line2"], f, GOLD)
    nf = font("mincho", 40)
    vertical(im, 34, 20, t["left_name"], nf)
    vertical(im, W - 34, 20, t["right_name"], nf)
    return im


# ---- 収録からコマを取る ----

def frame(spec: dict, raw: Path, at: float) -> Image.Image:
    """本編の時刻 at のコマを、編集の固定（lock）の区間をたどって raw から取る（字幕なし）。"""
    ranges = [(float(a), float(b)) for a, b in json.loads(Path(spec["lock"]).read_text(encoding="utf-8"))["ranges"]]
    png = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{source_time(ranges, at):.3f}", "-i", str(raw),
                          "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
                         capture_output=True, check=True).stdout
    from io import BytesIO
    return Image.open(BytesIO(png)).convert("RGB")


def side(spec: dict, raw: Path, at: float, which: str) -> Image.Image:
    return frame(spec, raw, at).crop(SIDES[which])


def options(spec: dict, raw: Path) -> Image.Image:
    """切り抜きの候補を記号と本編の時刻つきで並べる（人が選ぶ）。"""
    lab = font("gothic", 30)
    n = max(len(spec["left"]), len(spec["right"]))
    sheet = Image.new("RGB", (n * 320, 800), (60, 30, 52))
    d = ImageDraw.Draw(sheet)
    for r, which in enumerate(("left", "right")):
        for i, (key, at) in enumerate(spec[which].items()):
            tile = Image.new("RGB", (640, 740), (176, 130, 150))
            place(tile, side(spec, raw, at, which), 320, 60)
            x, y = i * 320 + 10, r * 400 + 44
            sheet.paste(tile.resize((300, 347), Image.LANCZOS), (x, y))
            mm, ss = divmod(int(at), 60)
            d.text((x, y - 40), f"{key}（{mm}:{ss:02d}）", font=lab, fill="white")
    return sheet


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="収録のコマから番組のサムネを組む")
    p.add_argument("spec", nargs="?")
    p.add_argument("--raw", help="つないだ raw（lock の素材）")
    p.add_argument("--out", default=".")
    p.add_argument("--options", action="store_true", help="切り抜きの候補を並べる")
    p.add_argument("--pick", nargs=2, metavar=("LEFT", "RIGHT"), help="この組み合わせで組む（例 B3 K1）")
    p.add_argument("--fetch-fonts", action="store_true")
    a = p.parse_args(argv)
    if a.fetch_fonts:
        fetch_fonts()
        if not a.spec:
            return 0
    spec = json.loads(Path(a.spec).read_text(encoding="utf-8"))
    raw, out = Path(a.raw), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.options:
        options(spec, raw).save(out / "切り抜き候補.jpg", quality=90)
    picks = [a.pick] if a.pick else spec.get("chosen", [])
    s = spec["shikishi"]
    board = frame(spec, raw, s["at"]).crop(tuple(s["crop"]))
    for left, right in picks:
        im = compose(spec, side(spec, raw, spec["left"][left], "left"),
                     side(spec, raw, spec["right"][right], "right"), board)
        path = out / f"サムネ_{spec['layout']}_{left}_{right}.png"
        im.save(path)
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
