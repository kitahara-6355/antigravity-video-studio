"""字幕の出だし・終わりを音声の話し始め・話し終わりに合わせる（2026-10-06 ユーザー指摘）。

「30〜40秒の字幕が言葉より先に出すぎる」。出だしは話し始めの 0.3 秒後、
終わりは次の話し始めの 0.2 秒前（ユーザー指定）。
"""
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from subtitle_engine import sync  # noqa: E402

RULES = dict(sync.DEFAULT_TIMING)


def _levels(spans, total, speech_db=-15.0, floor_db=-50.0):
    """10ms ごとの音量列。spans の区間だけ声。"""
    n = int(total / sync.FRAME_SEC)
    lv = np.full(n, floor_db)
    for a, b in spans:
        lv[int(a / sync.FRAME_SEC):int(b / sync.FRAME_SEC)] = speech_db
    return lv


def _map(spans, total=20.0):
    return sync.speech_map_from_levels(_levels(spans, total))


def test_speech_map_finds_onsets_and_offsets():
    sp = _map([(1.0, 3.0), (4.0, 6.5)])
    assert sp.onsets == pytest.approx([1.0, 4.0], abs=0.02)
    assert sp.offsets == pytest.approx([3.0, 6.5], abs=0.02)


def test_short_breath_is_not_a_pause():
    # 0.1 秒の息継ぎは間ではない（字幕を途切れさせない）
    sp = _map([(1.0, 2.0), (2.1, 3.0)])
    assert sp.onsets == pytest.approx([1.0], abs=0.02)


def test_floor_follows_the_room_noise():
    # 背景音が大きい場所でも、背景より十分大きい区間だけを声とみなす
    lv = _levels([(1.0, 2.0)], 10.0, speech_db=-12.0, floor_db=-30.0)
    sp = sync.speech_map_from_levels(lv)
    assert sp.onsets == pytest.approx([1.0], abs=0.02)


def test_caption_that_came_early_waits_for_speech_plus_lead_in():
    # 30〜40秒の実例: 推定 34.87 に出ていたが、話し始めは 35.31
    sp = _map([(30.0, 34.9), (35.31, 36.34), (37.8, 39.4)], total=45)
    segs = [{"start": 30.0, "end": 34.87, "text": "前"},
            {"start": 34.87, "end": 36.53, "text": "久木田博信先生です。"},
            {"start": 36.53, "end": 39.7, "text": "先生、どうぞよろしく"}]
    out, _ = sync.align_segments(segs, sp, [], RULES)
    assert out[1]["start"] == pytest.approx(35.31, abs=0.02)
    assert out[2]["start"] == pytest.approx(37.8, abs=0.02)


def test_caption_ends_before_next_sentence_starts():
    sp = _map([(1.0, 3.0), (4.0, 6.0)])
    segs = [{"start": 1.0, "end": 3.5, "text": "一文目"},
            {"start": 3.5, "end": 6.0, "text": "二文目"}]
    out, _ = sync.align_segments(segs, sp, [], RULES)
    # 話し終わり 3.0 + 残し 0.5 = 3.5 と、次の話し始め 4.0 - 0.2 = 3.8 の早い方
    assert out[0]["end"] == pytest.approx(3.5, abs=0.02)
    # 間が長いときは出しっぱなしにしない
    sp2 = _map([(1.0, 3.0), (8.0, 9.0)])
    segs2 = [{"start": 1.0, "end": 7.9, "text": "一文目"},
             {"start": 8.0, "end": 9.0, "text": "二文目"}]
    out2, _ = sync.align_segments(segs2, sp2, [], RULES)
    assert out2[0]["end"] == pytest.approx(3.5, abs=0.02)


def test_end_is_before_next_onset_by_user_margin_when_pause_is_short():
    sp = _map([(1.0, 3.0), (3.6, 6.0)])
    segs = [{"start": 1.0, "end": 3.0, "text": "一文目"},
            {"start": 3.6, "end": 6.0, "text": "二文目"}]
    out, _ = sync.align_segments(segs, sp, [], RULES)
    assert out[0]["end"] == pytest.approx(3.4, abs=0.02)
    assert out[1]["start"] == pytest.approx(3.6, abs=0.02)


def test_very_short_pause_is_chained():
    # 0.4 秒の間なら、0.2 秒だけ消して出し直すより続けて出す（ちらつき防止・Netflix）
    sp = _map([(1.0, 3.0), (3.4, 6.0)])
    segs = [{"start": 1.0, "end": 3.0, "text": "一文目"},
            {"start": 3.4, "end": 6.0, "text": "二文目"}]
    out, _ = sync.align_segments(segs, sp, [], RULES)
    assert 0 < out[1]["start"] - out[0]["end"] <= 2 * sync.VIDEO_FRAME + 0.01


def test_lead_in_starts_on_the_onset_by_default():
    assert sync.DEFAULT_TIMING["lead_in_sec"] == 0.0


def test_soft_onset_is_pulled_back():
    # 立ち上がりの弱い声（背景+8dB）が 0.1 秒あってから本体が来る
    lv = _levels([(1.1, 2.0)], 5.0)
    lv[int(1.0 / sync.FRAME_SEC):int(1.1 / sync.FRAME_SEC)] = -42.0
    sp = sync.speech_map_from_levels(lv)
    assert sp.onsets[0] == pytest.approx(1.0, abs=0.02)


def test_split_captions_are_timed_by_speaking_time_not_wall_time():
    # 1つの発話を2枚に分けた。途中に 2 秒の間がある。文字数は同じ
    sp = _map([(1.0, 3.0), (5.0, 7.0)])
    segs = [{"start": 1.0, "end": 4.0, "text": "あいうえお", "sourceStart": 0, "sourceEnd": 7},
            {"start": 4.0, "end": 7.0, "text": "かきくけこ", "sourceStart": 0, "sourceEnd": 7}]
    out, stats = sync.align_segments(segs, sp, [], RULES)
    assert stats["redistributed"] == 1
    assert out[1]["start"] == pytest.approx(5.0, abs=0.05)


def test_split_sentence_is_chained_without_blinking():
    # 1つの発話を2枚に分けた字幕は、間が無いので2フレーム空けて続ける
    sp = _map([(1.0, 7.0)])
    segs = [{"start": 1.0, "end": 4.0, "text": "前半"},
            {"start": 4.0, "end": 7.0, "text": "後半"}]
    out, _ = sync.align_segments(segs, sp, [], RULES)
    gap = out[1]["start"] - out[0]["end"]
    assert 0 < gap <= 2 * sync.VIDEO_FRAME + 0.01


def test_min_display_and_no_overlap():
    sp = _map([(1.0, 1.3), (1.9, 3.0)])
    segs = [{"start": 1.0, "end": 1.3, "text": "あ、そう"},
            {"start": 1.9, "end": 3.0, "text": "次"}]
    out, _ = sync.align_segments(segs, sp, [], RULES)
    for a, b in zip(out, out[1:]):
        assert a["end"] <= b["start"]
    assert all(s["end"] - s["start"] >= 0.2 for s in out)


def test_two_captions_do_not_snap_to_the_same_onset():
    sp = _map([(1.0, 6.0)])
    segs = [{"start": 1.0, "end": 2.0, "text": "一"},
            {"start": 1.2, "end": 6.0, "text": "二"}]
    out, _ = sync.align_segments(segs, sp, [], RULES)
    assert out[1]["start"] - out[0]["start"] >= sync.MIN_STEP_SEC - 1e-6


def test_caption_does_not_start_just_before_a_cut():
    sp = _map([(1.0, 3.0), (5.0, 8.0)])
    segs = [{"start": 1.0, "end": 3.0, "text": "一"},
            {"start": 4.8, "end": 8.0, "text": "二"}]
    # 出だし 5.0 の直後 5.1 にカット → カット点に揃える
    out, _ = sync.align_segments(segs, sp, [5.1], RULES)
    assert out[1]["start"] == pytest.approx(5.1, abs=0.01)


def test_rules_can_be_overridden():
    sp = _map([(1.0, 3.0)])
    out, _ = sync.align_segments([{"start": 1.0, "end": 3.0, "text": "一"}], sp, [],
                                 {**RULES, "lead_in_sec": 0.0})
    assert out[0]["start"] == pytest.approx(1.0, abs=0.02)


def test_measure_sync_flags_early_and_late():
    sp = _map([(1.0, 3.0), (5.0, 7.0), (9.0, 11.0)])
    early = [{"start": 0.2, "end": 3.0}, {"start": 4.0, "end": 7.0}, {"start": 8.0, "end": 11.0}]
    m = sync.measure_sync(early, sp)
    assert m["early"] == 2 and m["checked"] == 2
    late = [{"start": 1.3, "end": 3.2}, {"start": 6.0, "end": 7.2}, {"start": 10.5, "end": 11.2}]
    m = sync.measure_sync(late, sp)
    assert m["late"] == 2
    good = [{"start": 1.3, "end": 3.2}, {"start": 5.3, "end": 7.2}, {"start": 9.3, "end": 11.2}]
    assert sync.measure_sync(good, sp)["off_ratio"] == 0.0


def test_measure_sync_ignores_speech_continuing_under_a_caption():
    # 前の字幕が出たまま話が続く（息継ぎの後も同じ文）は遅すぎではない
    sp = _map([(1.0, 3.0), (3.5, 6.0)])
    m = sync.measure_sync([{"start": 1.3, "end": 6.0}], sp)
    assert m["late"] == 0


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg が無い")
def test_speech_map_reads_media(tmp_path):
    media = tmp_path / "tone.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                    "-i", "anullsrc=r=16000:cl=mono:d=1", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=2:sample_rate=16000", "-f", "lavfi",
                    "-i", "anullsrc=r=16000:cl=mono:d=1",
                    "-filter_complex", "[0][1][2]concat=n=3:v=0:a=1", str(media)], check=True)
    sp = sync.speech_map(str(media))
    assert sp.onsets == pytest.approx([1.0], abs=0.05)
    assert sp.offsets == pytest.approx([3.0], abs=0.05)
