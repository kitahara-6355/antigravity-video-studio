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
    # 2行いっぱいの字幕は隣とまとめられない（一瞬の字幕をまとめる規則が働かない）
    full = "あ" * 18 + "\n" + "い" * 18
    segs = [{"start": 1.0, "end": 2.0, "text": full},
            {"start": 1.2, "end": 6.0, "text": full}]
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


def test_recognised_captions_keep_their_times_in_a_split_utterance():
    # 実例（38.6 秒）: 1つの発話から分けた2枚。後ろの字幕は音声認識で 39.8 秒からと分かっている。
    # 文字数で配り直していたので、声より 1.2 秒早く出た
    sp = _map([(35.3, 39.4), (39.8, 41.8)], total=45)
    src = {"sourceStart": 51.6, "sourceEnd": 60.0}
    segs = [{"start": 35.3, "end": 39.3, "text": "デザイン書道の\n第一人者久木田博信先生です",
             "_asr": True, **src},
            {"start": 39.8, "end": 41.8, "text": "先生どうぞよろしくお願いいたします",
             "_asr": True, **src}]
    out, stats = sync.align_segments(segs, sp, [], RULES)
    assert stats["redistributed"] == 0
    assert out[1]["start"] == pytest.approx(39.8, abs=0.05)


def test_recognised_caption_is_not_pulled_to_the_next_phrase():
    # 音声認識で、この字幕の最初の文字は 50.1 秒（話し続けの途中）と分かっている。
    # 0.8 秒後の息継ぎ明けの話し始めは次の句なので、そこへは寄せない
    sp = _map([(49.2, 50.6), (50.9, 53.0)], total=60)
    segs = [{"start": 49.2, "end": 50.0, "text": "はい", "_asr": True},
            {"start": 50.1, "end": 53.0, "text": "先生はアドシアター代表で", "_asr": True}]
    out, _ = sync.align_segments(segs, sp, [], RULES)
    assert out[1]["start"] == pytest.approx(50.1, abs=0.05)


def test_recognised_caption_still_snaps_to_a_nearby_onset():
    # 認識の時刻と声の立ち上がりの小さな差（0.2 秒）は、話し始めに合わせる
    sp = _map([(1.0, 3.0), (3.8, 6.0)], total=10)
    segs = [{"start": 1.0, "end": 3.0, "text": "一文目", "_asr": True},
            {"start": 3.6, "end": 6.0, "text": "二文目", "_asr": True}]
    out, _ = sync.align_segments(segs, sp, [], RULES)
    assert out[1]["start"] == pytest.approx(3.8, abs=0.02)


def test_unrecognised_caption_does_not_take_the_next_recognised_onset():
    # 実例（44.4 秒）: 認識で拾えなかった「こんにちは」が、次の「もう初回ね」の話し始めを取り、
    # 「もう初回ね」が 0.4 秒遅れた
    sp = _map([(41.2, 43.96), (44.38, 45.37)], total=50)
    segs = [{"start": 41.2, "end": 43.4, "text": "先生どうぞよろしくお願いいたします", "_asr": True},
            {"start": 43.5, "end": 44.1, "text": "こんにちは", "_asr_interp": True},
            {"start": 44.16, "end": 45.3, "text": "もう初回ね", "_asr": True}]
    out, _ = sync.align_segments(segs, sp, [], RULES)
    shown = [s for s in out if "初回" in s["text"]][0]
    assert shown["start"] == pytest.approx(44.38, abs=0.02)


def test_unrecognised_head_starts_at_the_onset_before_the_first_recognised_word():
    # 実例（35.3 秒）: 「デザイン書道の…」の「デザイン」を認識が拾わず、最初に拾えた「書」から
    # 4 文字分さかのぼった 34.8 秒に出た（前の文の終わり）。声は 35.3 秒から
    sp = _map([(28.5, 34.9), (35.3, 39.4)], total=45)
    segs = [{"start": 28.5, "end": 34.7, "text": "記念すべき", "_asr": True, "_asr_first": 28.5},
            {"start": 34.78, "end": 39.4, "text": "デザイン書道の", "_asr": True, "_asr_first": 35.3}]
    out, _ = sync.align_segments(segs, sp, [], RULES)
    assert out[1]["start"] == pytest.approx(35.3, abs=0.02)


def test_unheard_flash_that_cannot_be_merged_is_dropped():
    # 実例（9分39秒）: カットで声が消えた「いたんだよね」が、カット点に 0.3 秒だけ出た。
    # 認識にも無く、隣ともまとめられない一瞬の字幕は出さない
    sp = _map([(570.0, 578.9), (579.2, 584.0)], total=600)
    full = "あ" * 18 + "\n" + "い" * 18
    segs = [{"start": 574.9, "end": 578.86, "text": full, "_asr": True},
            {"start": 578.86, "end": 579.18, "text": "いたんだよね", "_asr_interp": True},
            {"start": 579.18, "end": 584.4, "text": full, "_asr": True}]
    out, stats = sync.align_segments(segs, sp, [578.9], RULES)
    assert all(s["text"] != "いたんだよね" for s in out)
    assert stats["dropped"] == 1


def test_recognised_flash_is_kept():
    sp = _map([(570.0, 578.9), (579.2, 584.0)], total=600)
    full = "あ" * 18 + "\n" + "い" * 18
    segs = [{"start": 574.9, "end": 578.86, "text": full, "_asr": True},
            {"start": 578.86, "end": 579.18, "text": "いたんだよね", "_asr": True},
            {"start": 579.18, "end": 584.4, "text": full, "_asr": True}]
    out, stats = sync.align_segments(segs, sp, [578.9], RULES)
    assert any(s["text"] == "いたんだよね" for s in out)
    assert stats["dropped"] == 0


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


def test_captions_past_the_end_of_the_video_are_not_shown():
    # 実例（37分45秒）: 締めの「ありがとうございました」が映像の終わり（2265.4 秒）より
    # 後ろに出ていた。終わりをまたぐ字幕は終わりで切り、後ろの字幕は出さない
    sp = _map([(0.5, 2.0), (2.5, 4.6)], total=5.0)
    segs = [{"start": 0.5, "end": 2.0, "text": "本日は"},
            {"start": 2.5, "end": 6.0, "text": "どうもありがとうございました"},
            {"start": 6.2, "end": 7.0, "text": "ありがとうございました"}]
    out, stats = sync.align_segments(segs, sp, [], RULES)
    assert [s["text"] for s in out] == ["本日は", "どうもありがとうございました"]
    assert out[-1]["end"] <= sp.duration
    assert stats["dropped"] == 1
