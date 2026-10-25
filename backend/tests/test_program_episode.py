"""完成版に OP・章の見出し・テロップ・ED を足す道具（backend/program_package/episode.py）。"""
import json
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest
from PIL import ImageFont

from backend.program_package import chapters as ch
from backend.program_package import episode as ep

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "backend" / "config" / "episode" / "20250922_久木田ヒロノブ.json"



@pytest.fixture
def fonts(monkeypatch):
    # フォントは gitignore（Google Fonts から取る）で CI には無い。無いときは Pillow 内蔵の字形で
    # 代える（日本語は豆腐になるが、置き場所と大きさの検査はできる）
    if not all((ep.th.FONT_DIR / f).exists() for f in ep.th.FONTS.values()):
        monkeypatch.setattr(ep.th, "font", lambda key, size: ImageFont.load_default(size))


def spec():
    return json.loads(SPEC.read_text(encoding="utf-8"))


def test_op_length_counts_the_overlapping_joins():
    s = {"opening": {"cuts": [[0, 5], [10, 14]], "title_seconds": 3}}
    assert ep.op_length(s) == 5 + 4 + 3 - ep.FADE * 2
    # 番組 OP があれば前に足す（言葉3枚＋番組名、今回の OP とのつなぎ目も重ねる）
    s["program_opening"] = {"slides": ["a", "b", "c"], "slide_seconds": 3, "title_seconds": 4.5}
    assert ep.program_length(s) == 3 * 3 + 4.5
    assert ep.op_length(s) == ep.program_length(s) + (5 + 4 + 3 - ep.FADE * 2) - ep.FADE


def test_every_chapter_gets_a_heading_including_the_first():
    s = spec()
    body = ch.parse((ROOT / s["package"]).read_text(encoding="utf-8"))
    shown = [title for title in (t for _, t in body) if title not in s["chapters_skip"]]
    assert shown[0] == body[0][1]  # 第1章も出す（2026-10-23 北原さん）
    assert s["chapter_seconds"] >= 8


def test_name_pops_for_host_and_guest_do_not_overlap():
    s = spec()
    pops = sorted((p["at"], p["at"] + p.get("seconds", 7.0)) for p in s["name_pops"])
    assert {p["name"] for p in s["name_pops"]} >= {"北原美麗", "久木田ヒロノブ"}
    for (_, a1), (b0, _) in pairwise(pops):
        assert a1 <= b0


def test_chapters_are_shifted_by_the_opening_and_still_valid():
    s = spec()
    s["package"] = str(ROOT / s["package"])
    op = ep.op_length(s)
    shifted = ep.shifted_chapters(s, op)
    body = ch.parse(Path(s["package"]).read_text(encoding="utf-8"))
    assert shifted[0] == (0, s["op_chapter"])
    assert [t for t, _ in shifted[1:]] == [round(t + op) for t, _ in body]
    assert not ch.problems(shifted, op + 2558.37 + s["ending"]["seconds"])


def test_stamp_format():
    assert ep.stamp(65.9) == "1:05"
    assert ep.stamp(3725) == "1:02:05"


def test_overlays_never_overlap_each_other():
    s = spec()
    body = ch.parse((ROOT / s["package"]).read_text(encoding="utf-8"))
    shows = [(t + 1.0, t + 1.0 + s["chapter_seconds"]) for n, (t, title) in enumerate(body, 1)
             if title not in s["chapters_skip"]]
    shows += [(tp["at"], tp["at"] + tp.get("seconds", 5.0)) for tp in s["telops"]]
    shows.sort()
    for (a0, a1), (b0, _) in pairwise(shows):
        assert a1 <= b0, (a0, b0)


def test_telop_stays_in_the_picture_and_above_the_subtitles(fonts):
    im = ep.telop_card("剣閃", "久木田先生が作った筆文字フォント\n「鬼滅の刃」で使われている")
    x0, y0, x1, y1 = im.getbbox()
    fx0, fy0, fx1, _ = ep.th.FRAME
    assert fx0 <= x0 and x1 <= fx1 and fy0 <= y0 and y1 < 200


def test_chapter_heading_sits_just_under_the_top_of_the_picture(fonts):
    # 美麗さんの頭に近づかないよう上に詰める（2026-10-23 北原さん）。絵の外（黒い縁）には出ない
    x0, y0, _, y1 = ep.chapter_card(7, "フォント「剣閃」と「鬼滅の刃」").getbbox()
    assert ep.th.FRAME[1] <= y0 and y1 <= 140 and x0 >= ep.th.FRAME[0]


def test_first_chapter_heading_can_sit_at_the_top_right(fonts):
    # 美麗さん一人の場面は頭が左上に来るので、第1章は右上に寄せる（2026-10-23 北原さん）
    x0, _, x1, _ = ep.chapter_card(1, "オープニング・ゲスト紹介", right=True).getbbox()
    assert x1 <= ep.th.FRAME[2] and x0 > ep.W / 2
    assert 1 in spec()["chapters_right"]


def test_opening_words_are_written_in_from_the_left():
    # 番組 OP の言葉は、きっちり一文字ずつでなくても書き足されていく感じに（2026-10-23 北原さん）
    edges = [400.0 + 56 * i for i in range(9)]
    early, mid, late = (ep.column_alpha(edges, t, 0.11)[0, :, 0] for t in (0.0, 0.5, 5.0))
    assert early.max() == 0
    assert mid[420] == 1 and mid[860] == 0  # 左は書き終わり、右はまだ
    assert np.all(np.diff(mid) <= 1e-6)  # 左から右へ（逆戻りしない）
    assert late.min() == 1


def test_name_pops_stay_off_the_heads(fonts):
    # 久木田さんの名前が頭に掛かっていた（2026-10-23 北原さん）。頭の来る所（avoid）に1画素も掛けない
    pops = spec()["name_pops"]
    guest = next(p for p in pops if p["name"] == "久木田ヒロノブ")
    assert guest["avoid"]
    for p in pops:
        assert not ep.pop_hits(p), p["name"]


def test_gift_deadline_is_two_weeks_after_publishing():
    # 締切は動画公開から2週間後（2026-10-23 北原さん）。公開日が決まるまでは【未定】
    e = spec()["ending"]
    assert e["deadline_days"] == 14
    assert any("{deadline}" in s for s in e["gift_lines"])
    assert "【未定】" in " ".join(ep.gift_lines({**e, "publish_date": None}))
    assert "締切 11月14日（土）まで" in ep.gift_lines({**e, "publish_date": "2026-10-31"})
