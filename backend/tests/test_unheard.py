"""backend/subtitle_engine/unheard.py — 声の聞こえない所の字幕を外す（2026-10-23 上野さんの回の揮毫の場面）。"""
from __future__ import annotations

import shutil
import subprocess

import pytest

from subtitle_engine import unheard


def _tokens(*spans):
    """(始まり, 終わり) の間に 0.2 秒ごとに字を置く。"""
    return [("あ", round(a + k * 0.2, 2)) for a, b in spans for k in range(int((b - a) / 0.2) + 1)]


def test_a_long_stretch_without_any_recognised_character_is_a_gap():
    gaps = unheard.silent_gaps(_tokens((0, 790), (850, 900)), 900.0)
    assert gaps == [(790.5, 849.5)]


def test_short_pauses_are_not_gaps():
    assert unheard.silent_gaps(_tokens((0, 100), (105, 200)), 200.0) == []


def test_only_quiet_gaps_count_as_voiceless():
    tokens = _tokens((0, 100), (120, 200), (220, 300))
    levels = {(100.5, 119.5): -42.0, (200.5, 219.5): -24.0}  # 2つ目は音が大きい（歌・拍手かもしれない）
    spans = unheard.voiceless_spans("x.mp4", tokens, 300.0, measure=lambda m, a, b: levels[(a, b)])
    assert spans == [(100.5, 119.5)]


def test_without_the_recogniser_nothing_is_called_voiceless():
    assert unheard.voiceless_spans("x.mp4", None, 300.0, measure=lambda *a: -60.0) == []


def test_only_captions_inside_a_voiceless_span_are_dropped():
    segs = [{"start": 795.0, "end": 801.0, "text": "書いていただきたいと思います"},  # はみ出す → 残す
            {"start": 816.4, "end": 825.4, "text": "そうですねちょっとこういう感じなんですよ"},
            {"start": 826.5, "end": 833.4, "text": "いやもうここは直したほうがいいですね"},
            {"start": 850.0, "end": 852.0, "text": "はいじゃあ先生"}]
    keep, gone = unheard.drop_inside(segs, [(800.5, 849.5)])
    assert [s["start"] for s in gone] == [816.4, 826.5]
    assert [s["start"] for s in keep] == [795.0, 850.0]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg が無い")
def test_mean_level_is_measured_from_the_media(tmp_path):
    quiet, loud = tmp_path / "q.wav", tmp_path / "l.wav"
    for path, vol in ((quiet, "0.003"), (loud, "0.5")):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        f"sine=frequency=300:duration=3", "-af", f"volume={vol}", str(path)], check=True)
    assert unheard.mean_db(quiet, 0, 2) < unheard.QUIET_DB < unheard.mean_db(loud, 0, 2)


@pytest.mark.parametrize("text, yes", [("4 3 2", True), ("５、４、３", True), ("三 二 一", True),
                                       ("はい皆さんこんにちは", False), ("2回目が始まりました", False), ("", False)])
def test_countdown_is_only_numbers(text, yes):
    assert unheard.is_countdown(text) is yes


def test_countdowns_are_dropped_only_near_the_head_of_each_file():
    segs = [{"start": 0.5, "end": 2.9, "text": "4 3 2"},
            {"start": 4.6, "end": 9.0, "text": "はい皆さんこんにちは"},
            {"start": 300.0, "end": 301.0, "text": "3 2 1"},         # 話の途中の数字は残す
            {"start": 790.0, "end": 791.0, "text": "5 4 3"}]         # 2本目の頭
    keep, gone = unheard.drop_countdowns(segs, [0.0, 789.5])
    assert [s["start"] for s in gone] == [0.5, 790.0]
    assert [s["start"] for s in keep] == [4.6, 300.0]
