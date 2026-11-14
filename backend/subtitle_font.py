"""字幕の書体を PC とクラウドで揃える。

PC は Windows 付属の Yu Gothic UI、クラウドには無いので代わりの書体で大きめに出ていた。
両方で同じ無料書体（BIZ UDPゴシック、SIL OFL）を ``backend/data/fonts`` から読ませる。
書体ファイルはリポジトリに入れず ``python -m backend.subtitle_font --fetch`` で取る。

- 既定: BIZ UDPGothic（2026-11-13 北原さん承認の計画。次の回から）
- 久木田回（v67 まで）を PC で同じ見た目で作り直すときは ``AVS_SUBTITLE_FONT="Yu Gothic UI"``
"""
from __future__ import annotations

import os
import re
import sys
import urllib.request
from pathlib import Path

DEFAULT_FAMILY = "BIZ UDPGothic"
FONT_DIR = Path(__file__).resolve().parent / "data" / "fonts"
FILES = {400: "BIZUDPGothic-Regular.ttf", 700: "BIZUDPGothic-Bold.ttf"}
CSS = "https://fonts.googleapis.com/css2?family=BIZ+UDPGothic:wght@400;700"


# 同じ FontSize でも書体の作りで大きさが変わる。Yu Gothic UI（PC の v67）と同じ見た目の幅に合わせる倍率。
# 2026-11-13 実測: 720p で FontSize=16 の Yu Gothic UI の帯幅 ≒ BIZ UDPGothic の FontSize=11（360p で 219px 対 220px）
SIZE_SCALE = {"BIZ UDPGothic": 11 / 16}


def family() -> str:
    return os.environ.get("AVS_SUBTITLE_FONT") or DEFAULT_FAMILY


def size(base: int | float) -> int:
    """Yu Gothic UI 基準の FontSize を、今の書体で同じ見た目になる値にする。"""
    return max(1, round(base * SIZE_SCALE.get(family(), 1.0)))


def escape_filter_path(path: str | Path) -> str:
    """ffmpeg のフィルタ引数の中で使えるように、\\ を / に、: を \\: にする。"""
    return str(path).replace("\\", "/").replace(":", "\\:")


def fontsdir_option() -> str:
    """subtitles フィルタに足す ``:fontsdir='…'``。書体が無ければ空（OS の書体で描く）。"""
    if not any(os.path.isfile(os.path.join(FONT_DIR, f)) for f in FILES.values()):
        return ""
    return f":fontsdir='{escape_filter_path(FONT_DIR)}'"


def fetch() -> None:
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(CSS, headers={"User-Agent": "Mozilla/5.0"})
    css = urllib.request.urlopen(req).read().decode()
    for weight, url in re.findall(r"font-weight: (\d+);\s*src: url\((https://[^)]+\.ttf)\)", css):
        urllib.request.urlretrieve(url, FONT_DIR / FILES[int(weight)])
        print(f"{FILES[int(weight)]} ← {url}")


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        fetch()
    print(f"書体: {family()}  置き場: {FONT_DIR}  fontsdir: {fontsdir_option() or '(無し)'}")
