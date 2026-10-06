"""字幕の文字を音声認識の時刻に合わせる（2026-10-06 ユーザー指摘「声と字幕が合っていない」）。

認識モデルは重いので、ここではモデルを呼ばずに「認識結果」を直接渡して、
突き合わせと配り直しの規則だけを確かめる。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from subtitle_engine import aligner  # noqa: E402


def toks(text, start=0.0, step=0.2):
    return [(c, round(start + i * step, 3)) for i, c in enumerate(text)]


def test_caption_takes_the_time_of_its_own_characters():
    caps = [{"start": 0.0, "end": 2.0, "text": "記念すべき"},
            {"start": 2.0, "end": 4.0, "text": "第1回目のゲストは"}]
    aligner.align_captions(caps, toks("記念すべき第一回目のゲストは", start=10.0))
    assert caps[0]["_asr"] and caps[1]["_asr"]
    assert caps[0]["start"] == pytest.approx(10.0, abs=0.05)
    assert caps[1]["start"] == pytest.approx(11.0, abs=0.05)
    assert caps[0]["end"] <= caps[1]["start"] + 0.3


def test_three_second_shift_is_corrected():
    # 実例: 字幕が声より約3秒早い
    caps = [{"start": 33.3, "end": 36.4, "text": "デザイン書道の第一人者"},
            {"start": 36.4, "end": 39.7, "text": "どうぞよろしくお願いいたします"}]
    aligner.align_captions(caps, toks("デザイン書道の第一人者", 35.3) + toks("どうぞよろしくお願いいたします", 39.6))
    assert caps[0]["start"] == pytest.approx(35.3, abs=0.1)
    assert caps[1]["start"] == pytest.approx(39.6, abs=0.1)


def test_unrecognized_caption_is_left_alone():
    caps = [{"start": 0.0, "end": 1.0, "text": "まったく違う言葉です"}]
    assert aligner.align_captions(caps, toks("別の文章がここにある", 5.0)) == 0
    assert caps[0]["start"] == 0.0 and "_asr" not in caps[0]


def test_a_single_common_character_does_not_move_a_caption():
    caps = [{"start": 0.0, "end": 1.0, "text": "のので"}]
    assert aligner.align_captions(caps, toks("まったく別の話", 9.0)) == 0


def test_unaligned_captions_are_spread_between_aligned_ones():
    caps = [{"start": 0.0, "end": 1.0, "text": "あいうえお"},
            {"start": 1.0, "end": 2.0, "text": "ききとれない"},
            {"start": 2.0, "end": 3.0, "text": "かきくけこ"}]
    aligner.align_captions(caps, toks("あいうえお", 10.0) + toks("かきくけこ", 14.0))
    moved = aligner.interpolate_unaligned(caps)
    assert moved == 1 and caps[1]["_asr_interp"]
    assert caps[0]["end"] <= caps[1]["start"] < caps[1]["end"] <= caps[2]["start"]


def test_captions_before_the_first_anchor_shift_with_it():
    caps = [{"start": 0.0, "end": 1.0, "text": "ききとれない"},
            {"start": 1.0, "end": 2.0, "text": "あいうえお"}]
    aligner.align_captions(caps, toks("あいうえお", 4.0))
    aligner.interpolate_unaligned(caps)
    assert caps[0]["start"] == pytest.approx(3.0, abs=0.1)


def test_normalisation_matches_digits_and_katakana():
    assert aligner.norm_char("１") == "一"
    assert aligner.norm_char("ア") == "あ"
    assert aligner.norm_char("、") == ""
    assert aligner._norm_text("第1回目、ゲスト") == aligner._norm_text("第一回目ゲスト")


def test_chunks_follow_speech_and_stay_short():
    onsets = [0.0, 1.0, 12.0]
    offsets = [0.5, 9.0, 13.0]
    bounds = aligner.chunk_bounds(onsets, offsets, 20.0, max_sec=8.0, max_gap=0.4, pad=0.1)
    assert all(b - a <= 8.2 for a, b in bounds)
    assert bounds[-1][0] == pytest.approx(11.9, abs=0.01)
    # 長い間（9.0→12.0）はまたがない
    assert all(not (a < 10.0 < b) for a, b in bounds)


def test_to_output_maps_source_times_onto_the_cut_timeline():
    tokens = [("あ", 1.0), ("い", 5.0), ("う", 12.0)]
    out = aligner.to_output(tokens, [(0.0, 2.0), (10.0, 14.0)])
    assert out == [("あ", 1.0), ("う", 4.0)]


def test_missing_model_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("AVS_ALIGN_MODEL_DIR", str(tmp_path / "none"))
    assert aligner.available() is False
    media = tmp_path / "v.mp4"
    media.write_bytes(b"x")
    assert aligner.tokens_for(str(media)) is None


def test_recognised_times_are_moved_to_the_voice_onset(tmp_path):
    # 認識の時刻は声の立ち上がりより約 0.2 秒早い（2026-10-06 実測 5 か所: 0.19〜0.30 秒）
    media = tmp_path / "v.mp4"
    media.write_bytes(b"x")
    aligner._cache_path(str(media)).write_text(
        json.dumps({"version": aligner.CACHE_VERSION, "tokens": [["あ", 1.0]]}), encoding="utf-8")
    assert aligner.tokens_for(str(media)) == [("あ", pytest.approx(1.0 + aligner.LAG_SEC))]
    assert 0.1 <= aligner.LAG_SEC <= 0.3
