"""番組共通 OP（資産）の道具のテスト。"""
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import ImageFont

from backend.program_package import opening as op

ROOT = Path(__file__).resolve().parents[2]
PROGRAM = ROOT / "backend" / "config" / "program" / "美麗の書道対談.json"
EPISODE = ROOT / "backend" / "config" / "episode" / "20250922_久木田ヒロノブ.json"


@pytest.fixture
def fonts(monkeypatch):
    # フォントは gitignore で CI には無い。無いときは Pillow 内蔵の字形で代える
    if not all((op.th.FONT_DIR / f).exists() for f in op.th.FONTS.values()):
        monkeypatch.setattr(op.th, "font", lambda key, size: ImageFont.load_default(size))


def test_opening_words_are_written_in_from_the_left():
    # 言葉は、きっちり一文字ずつでなくても書き足されていく感じに（2026-10-23 北原さん）
    edges = [400.0 + 56 * i for i in range(9)]
    early, mid, late = (op.column_alpha(edges, t, 0.11)[0, :, 0] for t in (0.0, 0.5, 5.0))
    assert early.max() == 0
    assert mid[420] == 1 and mid[860] == 0  # 左は書き終わり、右はまだ
    assert np.all(np.diff(mid) <= 1e-6)  # 左から右へ（逆戻りしない）
    assert late.min() == 1


def test_program_opening_is_one_shared_asset_for_every_episode():
    # 番組共通 OP は資産として別保存し、各回の本編はそれを指す（2026-10-25 北原さん）
    program = op.load(PROGRAM)
    episode = json.loads(EPISODE.read_text(encoding="utf-8"))
    assert (ROOT / episode["program"]).resolve() == PROGRAM.resolve()
    assert "program_opening" not in episode  # 回ごとに OP の中身を持たない
    assert set(program["asset"]["forms"]) == set(op.SIZES)
    assert op.output_name(program, "縦").startswith(f"番組OP_{program['version']}_縦")


def test_provisional_music_is_marked_in_the_file_name():
    p = {"version": "v1", "music": {"provisional": True}}
    assert op.output_name(p, "横") == "番組OP_v1_横_仮曲入り.mp4"
    assert op.output_name({"version": "v2", "music": None}, "横") == "番組OP_v2_横.mp4"


def test_long_words_break_at_the_space_on_the_vertical_screen(fonts):
    f = op.th.font("mincho", 56)
    lines = op.wrap(["大切にされている言葉を 書いていただく"], f, op.SIZES["縦"][0] - 120)
    d = op.ImageDraw.Draw(op.Image.new("RGB", (1, 1)))
    assert all(d.textlength(s, font=f) <= op.SIZES["縦"][0] - 120 for s in lines)
    assert "".join(lines).replace(" ", "") == "大切にされている言葉を書いていただく"


def test_style_choices_are_checked_and_the_default_is_what_was_approved():
    # 10-23 に北原さんが OK した形が既定。知らない選択肢は止める
    assert op.style_of({}) == {"reveal": "brush", "background": "glow", "finish": "sweep"}
    with pytest.raises(SystemExit):
        op.style_of({"style": {"reveal": "spin"}})


def test_picker_shows_every_choice_and_presets_stay_in_the_choices():
    # 案を見て選ぶだけで雰囲気が決まる仕組み（2026-10-25 北原さん）。軸ごとに全部の選択肢の見本を出す
    from backend.program_package import style_picker as sp
    vs = sp.variants(op.load(PROGRAM))
    for axis, choices in op.CHOICES.items():
        assert {v["choice"] for v in vs if v["axis"] == axis} == set(choices)
    for p in sp.PRESETS.values():
        assert op.style_of({"style": p["style"]}) == p["style"]
    assert sum(v["current"] for v in vs if v["axis"] == "preset") == 1  # 今の形がどれか分かる


@pytest.mark.parametrize("style", [{"reveal": r} for r in op.CHOICES["reveal"]] +
                         [{"background": b} for b in op.CHOICES["background"]] +
                         [{"finish": f} for f in op.CHOICES["finish"]])
def test_every_style_draws_frames_without_errors(fonts, style):
    # 小さい画面で数コマだけ描いて、どの選択肢も落ちないことを確かめる（書き出しはしない）
    prog = {"name": "美麗の書道対談", "slides": ["書を通して"], "slide_seconds": 1.0, "title_seconds": 2.0,
            "theme": {"light": [214, 178, 196], "deep": [92, 52, 78]}, "style": style}
    frames = list(op.frames(prog, (320, 180)))
    assert len(frames) == 90 and all(f.shape == (180, 320, 3) for f in frames[::30])


def test_a_pick_is_written_to_the_program_and_kept_as_a_narrative(tmp_path):
    # 選んだ形は番組の指定へ、理由はソウル・ナラティブ（判断の記録）へ（憲法 §5.2・§10）
    from backend.program_package import style_picker as sp
    prog = tmp_path / "p.json"
    prog.write_text(PROGRAM.read_text(encoding="utf-8"), encoding="utf-8")

    class Log:
        def __init__(self):
            self.rec, self.synced = [], False

        def record_decision(self, **kw):
            self.rec.append(kw)

        def sync_to_soul_narrative(self):
            self.synced = True

    log = Log()
    out = sp.apply(prog, {"reveal": "rise", "background": "washi", "finish": "seal", "note": "落款が良い",
                          "at": "2026-10-25T14:00:00Z"}, log)
    assert op.load(prog)["style"] == out["style"] == {"reveal": "rise", "background": "washi", "finish": "seal"}
    assert "落款が良い" in out["history"][-1]
    assert log.synced and log.rec[0]["reason"] == "落款が良い" and log.rec[0]["decision"] == "modify"
    with pytest.raises(SystemExit):
        sp.apply(prog, {"reveal": "spin", "background": "glow", "finish": "sweep"}, log)
