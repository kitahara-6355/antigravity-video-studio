"""生成クリップの検品（backend/program_package/clip_check.py）。

キャラの絵はリポジトリに置かないので、合成の絵（帯の背景と丸いキャラ）で確かめる。
実物（EP001 シーン5 の失敗クリップ）での結果は knowledge に残した。
"""
import numpy as np
import pytest
from PIL import Image, ImageDraw

pytest.importorskip("cv2")

from backend.program_package import clip_check as c


def scene(scale=1.0, arm=False, smile=False, shift=0):
    """帯の背景（壁と床）に、丸い頭と体のキャラ。arm で腕を上げ、smile で口を開ける。"""
    im = Image.new("RGB", (216, 384), (226, 234, 244))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 250 + shift, 216, 384], fill=(194, 164, 132))
    cx, cy = 108, 150
    r = round(48 * scale)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(246, 208, 170), outline=(20, 20, 20), width=3)
    d.pieslice([cx - r, cy - r, cx + r, cy + r], 180, 360, fill=(30, 30, 30))
    d.rectangle([cx - round(30 * scale), cy + r, cx + round(30 * scale), cy + r + round(70 * scale)], fill=(70, 100, 150))
    if arm:
        d.rectangle([cx - r - round(14 * scale), cy - r, cx - r, cy + r], fill=(70, 100, 150))
    if smile:
        d.ellipse([cx - 14, cy + 8, cx + 14, cy + 30], fill=(200, 40, 40))
    return im


START, END = scene(), scene(arm=True, smile=True)


def clip(states, step=0.25):
    return [(i * step, np.asarray(scene(**s))) for i, s in enumerate(states)]


def test_a_clip_that_moves_to_the_end_frame_and_holds_passes():
    r = c.check_frames(clip([{}] * 4 + [{"arm": True, "smile": True}] * 28), START, END)
    assert r["ok"], r["reasons"]
    assert r["reached_at"] == 1.0 and r["use"][1] > 7.5


def test_a_zoom_in_the_middle_is_rejected_with_the_time():
    states = [{}] * 4 + [{"arm": True, "smile": True, "scale": 1.25}] * 28
    r = c.check_frames(clip(states), START, END)
    assert not r["ok"]
    assert any("大きさ" in s and "1.0 秒" in s for s in r["reasons"])
    assert r["use"][1] < 1.0


def test_a_clip_that_never_reaches_the_end_frame_is_rejected():
    r = c.check_frames(clip([{}] * 8 + [{"arm": True}] * 24), START, END)  # 腕は上がるが表情が違うまま
    assert not r["ok"] and any("一部が違う" in s for s in r["reasons"])


def test_a_clip_that_stays_on_the_first_frame_is_rejected():
    r = c.check_frames(clip([{}] * 32), START, END)
    assert not r["ok"] and any("届かない" in s for s in r["reasons"])


def test_returning_to_the_first_frame_is_rejected_and_the_good_part_is_kept():
    states = [{}] * 4 + [{"arm": True, "smile": True}] * 20 + [{}] * 8
    r = c.check_frames(clip(states), START, END)
    assert not r["ok"] and any("戻る" in s for s in r["reasons"])
    assert 5.5 <= r["use"][1] <= 6.0  # 戻る手前までは使える


def test_a_changed_background_is_rejected():
    states = [{}] * 4 + [{"arm": True, "smile": True, "shift": -120}] * 28  # 床の線が大きく動く＝カメラが変わった
    r = c.check_frames(clip(states), START, END)
    assert not r["ok"] and any("背景" in s for s in r["reasons"])


def test_a_one_frame_glitch_is_not_counted():
    states = [{}] * 4 + [{"arm": True, "smile": True}] * 28
    states[12] = {"arm": True, "smile": True, "scale": 1.3}
    assert c.check_frames(clip(states), START, END)["ok"]


def test_end_frame_drawn_at_another_size_is_allowed_for():
    # 最後のコマ自体が少し大きく描かれているなら、その大きさまでは「変わった」と言わない
    end = scene(arm=True, smile=True, scale=1.15)
    states = [{}] * 4 + [{"arm": True, "smile": True, "scale": 1.15}] * 28
    assert c.check_frames(clip(states), START, end)["ok"]


def test_no_frames_is_a_failure_not_a_pass():
    assert not c.check_frames([], START, END)["ok"]
