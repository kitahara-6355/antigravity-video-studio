"""完成版から縦長の Shorts を切り出す道具（backend/program_package/shorts.py）。"""
import json
from pathlib import Path

from backend.program_package import shorts as sh

SEGS = [
    {"start": 10.0, "end": 13.0, "text": "一つめ"},
    {"start": 13.5, "end": 18.0, "text": "二つめ\nの行"},
    {"start": 20.0, "end": 24.0, "text": "三つめ"},
]
SPEC = Path(__file__).resolve().parents[1] / "config" / "shorts" / "20250922_久木田ヒロノブ.json"


def test_cue_times_snap_to_the_whole_subtitle():
    # "0:13" は2つめの字幕の出だし → 終わりはその字幕の終わりまで
    assert sh.snap(["0:10", "0:13"], SEGS) == (10.0 - sh.LEAD, 18.0 + sh.TAIL)


def test_plain_seconds_are_used_as_they_are():
    assert sh.snap([11.0, 19.5], SEGS) == (11.0, 19.5)


def test_an_output_range_is_traced_back_to_the_raw():
    ranges = [(0.0, 10.0), (15.0, 30.0)]  # 10〜15秒は切ってある
    assert sh.raw_pieces(8.0, 12.0, ranges) == [(8.0, 10.0), (15.0, 17.0)]
    assert sh.raw_pieces(2.0, 5.0, ranges) == [(2.0, 5.0)]


def test_subtitles_are_moved_onto_the_clip_timeline():
    cues = sh.clip_cues([(12.0, 15.0), (20.0, 22.0)], SEGS)
    # 1つめの区間: 一つめ(12-13) と 二つめ(13.5-15)、2つめの区間は 3秒後から 三つめ
    assert [(round(a, 2), round(b, 2), t) for a, b, t in cues] == [
        (0.0, 1.0, "一つめ"), (1.5, 3.0, "二つめ\nの行"), (3.0, 5.0, "三つめ")]


def test_ass_time_format():
    assert sh.ass_time(3725.5) == "1:02:05.50"


def test_every_clip_fits_a_short():
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    keys = [c["key"] for c in spec["clips"]]
    assert len(keys) == len(set(keys))
    for c in spec["clips"]:
        assert len(c["title"]) == 2 and c["parts"]


def test_a_framed_panel_keeps_the_picture_shape_and_centre():
    x, y, w, h = sh.panel({"inset": 40})
    assert (x, w) == (40, sh.W - 80) and h % 2 == 0
    assert abs(w / h - sh.W / sh.VIDEO_H) < 0.01
    assert y + h / 2 == sh.VIDEO_Y + sh.VIDEO_H / 2
    assert sh.panel(None) == (0, sh.VIDEO_Y, sh.W, sh.VIDEO_H)


def test_the_frame_surrounds_the_picture():
    im = sh.card(["あ", "い"], "う", sh.LILAC, {"inset": 40, "width": 14, "shadow": True})
    x, y, w, h = sh.panel({"inset": 40})
    gold = sh.GOLD_FRAME
    assert im.getpixel((x - 8, y + h // 2)) == gold and im.getpixel((x + w + 6, y + h // 2)) == gold
    assert im.getpixel((sh.W // 2, y - 8)) == gold
