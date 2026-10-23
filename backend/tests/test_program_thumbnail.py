"""番組のサムネを収録のコマから組む道具（backend/program_package/thumbnail.py）。"""
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from backend.program_package import thumbnail as th

SPEC = Path(__file__).resolve().parents[1] / "config" / "thumbnails" / "20250922_久木田ヒロノブ.json"
WALL = (176, 130, 150)


def test_the_wall_colour_is_keyed_out_and_people_are_kept():
    im = Image.new("RGB", (60, 40), WALL)
    im.paste((240, 240, 240), (20, 10, 40, 40))  # 白い上着
    im.paste((60, 45, 40), (22, 0, 38, 14))  # 髪
    m = np.asarray(th.wall_mask(im))
    assert m[2, 2] == 0  # 壁
    assert m[20, 30] == 255 and m[7, 30] == 255


def test_the_head_is_found_from_the_top_of_the_mask():
    m = np.zeros((100, 80), dtype=bool)
    m[30:, 20:61] = True
    top, cx = th.head_of(m)
    assert top == 30 and cx == 40


def test_font_urls_are_read_from_the_css():
    css = "@font-face {\n  font-family: 'Noto Sans JP';\n  src: url(https://fonts.gstatic.com/s/x/v1/a.ttf) format('truetype');\n}"
    assert th.font_urls(css) == ["https://fonts.gstatic.com/s/x/v1/a.ttf"]


def test_the_spec_names_only_candidates_it_has():
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    for left, right in spec["chosen"]:
        assert left in spec["left"] and right in spec["right"]
    assert set(spec["text"]) == {"tag", "line1", "line2", "left_name", "right_name"}


def test_the_layout_fits_a_youtube_thumbnail(tmp_path):
    if not all((th.FONT_DIR / f).exists() for f in th.FONTS.values()):
        pytest.skip("フォントが無い（python -m backend.program_package.thumbnail --fetch-fonts）")
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    person = Image.new("RGB", (400, 460), WALL)
    person.paste((240, 240, 240), (100, 120, 300, 460))
    person.paste((60, 45, 40), (140, 40, 260, 140))
    board = Image.new("L", (300, 340), 255)
    im = th.compose(spec, person, person, board)
    assert im.size == (1280, 720)
    # 下のキャッチは左右に 10px 以上の余白を残して収まる
    assert th.catch_width(spec) <= 1280 - 20
