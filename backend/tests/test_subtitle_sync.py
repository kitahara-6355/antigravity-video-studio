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


def test_a_long_unheard_head_is_given_time_to_be_said():
    # 実例（17分58秒・28回目）: 「ね あわよくば その98%の人口の中から改めて」の頭 13 字を認識が
    # 拾えず、最初に拾えた「の中から」の直前の話し始め（文の途中の息継ぎ）で出て、2行が 1.2 秒で消えた
    sp = _map([(10.0, 17.3), (17.5, 18.1), (18.4, 21.0)], total=25)
    segs = [{"start": 10.0, "end": 17.3, "text": "筆で文字を書くっていうことの",
             "_asr": True, "_asr_first": 10.0, "_asr_marks": [(0, 10.0)]},
            {"start": 17.57, "end": 20.5, "text": "ね　あわよくば\nその98%の人口の中から改めて",
             "_asr": True, "_asr_first": 18.46, "_asr_marks": [(13, 18.46)]}]
    out, _ = sync.align_segments(segs, sp, [], RULES)
    assert out[1]["start"] == pytest.approx(17.5, abs=0.02)


def test_a_short_unheard_head_still_starts_at_the_onset_before_the_first_recognised_word():
    # 認識の字の時刻は早めに出るので、短い頭（「デザイン」4字）は今までどおり直前の話し始め
    sp = _map([(28.5, 34.9), (35.3, 39.4)], total=45)
    segs = [{"start": 28.5, "end": 34.7, "text": "記念すべき", "_asr": True, "_asr_first": 28.5,
             "_asr_marks": [(0, 28.5)]},
            {"start": 34.78, "end": 39.4, "text": "デザイン書道の", "_asr": True, "_asr_first": 35.3,
             "_asr_marks": [(4, 35.3)]}]
    out, _ = sync.align_segments(segs, sp, [], RULES)
    assert out[1]["start"] == pytest.approx(35.3, abs=0.02)


def test_an_unheard_head_starts_where_speech_resumes_after_the_caption_before():
    # 実例（28分40秒・31回目）: 「私から見ると 書いてるところずっと…」の頭 7 字を認識が拾えず、
    # 最初に拾えた「いてる」の直前の話し始め（1721.65 秒）に出た。7 字を 0.2 秒で言うことになり、
    # 前の「はい ありがとうございます」が「私から見ると」の間も出ていた。前の字幕の声の後ろの
    # 話し始めまで探し、頭を言える所が無ければそのうち早い方
    sp = _map([(1717.67, 1719.16), (1719.46, 1720.42), (1720.81, 1721.08), (1721.65, 1726.0)], total=1730)
    segs = [{"start": 1718.33, "end": 1719.88, "text": "はい\u3000ありがとうございます", "_asr": True,
             "_asr_first": 1718.59, "_asr_marks": [(2, 1718.59), (11, 1719.75)]},
            {"start": 1720.94, "end": 1725.7, "text": "私から見ると\u3000書いてるところずっと\n見てたんです",
             "_asr": True, "_asr_first": 1721.85, "_asr_marks": [(7, 1721.85), (8, 1721.93), (9, 1722.05)]}]
    out, _ = sync.align_segments(segs, sp, [], RULES)
    assert out[1]["start"] == pytest.approx(1720.81, abs=0.02)


def test_an_unheard_head_does_not_take_speech_right_after_the_caption_before():
    # 実例（32分52秒）: 前の字幕の最後に聞こえた字（「僕」）は話し始めより早めに出る。その直後の
    # 話し始めは前の字幕の声なので、次の字幕の頭（「だから」）には使わない
    sp = _map([(1971.39, 1972.49), (1972.69, 1972.85), (1973.73, 1974.1), (1974.34, 1976.0)], total=1980)
    segs = [{"start": 1971.39, "end": 1972.6, "text": "三浦半島にね\u3000僕よく行くんですよ", "_asr": True,
             "_asr_first": 1971.28, "_asr_marks": [(0, 1971.28), (7, 1972.52)]},
            {"start": 1973.2, "end": 1976.0, "text": "だから\u3000自宅からね\n40分回ればいけるんで", "_asr": True,
             "_asr_first": 1973.62, "_asr_marks": [(3, 1973.62), (4, 1973.86), (5, 1974.06)]}]
    out, _ = sync.align_segments(segs, sp, [], RULES)
    assert out[1]["start"] == pytest.approx(1973.73, abs=0.02)


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


def test_an_unheard_caption_snapped_too_short_gets_back_the_time_it_was_given():
    # 実例（11分52秒・50回目）: 認識が拾えなかった聞き手の「エピソードなんですか？」を前後の聞こえた字幕の
    # 間（1.31 秒）に配り、声の立ち上がり（712.54 秒）に寄せた。次の「ああ なるほど」まで 0.72 秒になり、
    # 読めない・声も拾えない字幕として外していた。出だしを配った所の方へ、読める長さまで戻す
    sp = _map([(707.56, 709.23), (709.55, 710.59), (711.31, 712.03), (712.54, 713.12),
               (713.33, 714.47), (714.59, 714.99)], total=730)
    segs = [{"start": 709.12, "end": 711.97, "text": "泣きそうになるわっていうね", "_asr": True,
             "_asr_first": 709.12, "_asr_marks": [(0, 709.12), (12, 711.84)]},
            {"start": 711.97, "end": 713.28, "text": "エピソードなんですか？", "_asr_interp": True},
            {"start": 713.28, "end": 713.96, "text": "ああ　なるほど", "_asr": True,
             "_asr_first": 713.67, "_asr_marks": [(3, 713.67), (4, 713.79), (5, 713.83)]}]
    out, stats = sync.align_segments(segs, sp, [], RULES)
    shown = [s for s in out if s["text"] == "エピソードなんですか？"]
    assert len(shown) == 1 and stats["dropped"] == 0
    assert shown[0]["end"] - shown[0]["start"] >= RULES["min_display_sec"]
    # 戻すのは読める長さぎりぎりまで（声より早く出る分を小さくする）
    assert shown[0]["start"] > 712.54 - 0.2
    nxt = [s for s in out if s["text"].startswith("ああ")][0]
    assert nxt["start"] == pytest.approx(713.33, abs=0.02)
    before = [s for s in out if s["text"].startswith("泣き")][0]
    assert before["end"] >= 712.03


def test_an_unheard_caption_takes_back_time_only_while_the_one_before_stays_readable():
    # 実例（29分24秒・50回目）: 認識がほぼ拾えない所に3枚を配った。真ん中の「皆さんぜひ」は声に寄せて
    # 0.51 秒になり外れた。前の（これも声の拾えない）字幕を読める長さに残して戻す
    sp = _map([(1761.42, 1762.40), (1762.78, 1764.74), (1764.89, 1765.18), (1765.47, 1766.47),
               (1766.69, 1766.86), (1767.07, 1768.36)], total=1780)
    segs = [{"start": 1760.9, "end": 1763.0, "text": "それでいいですか？", "_asr": True,
             "_asr_first": 1761.03, "_asr_marks": [(1, 1761.03), (7, 1762.87)]},
            {"start": 1763.0, "end": 1764.359, "text": "ありがとうございます", "_asr_interp": True},
            {"start": 1764.359, "end": 1765.038, "text": "皆さんぜひ", "_asr_interp": True},
            {"start": 1765.038, "end": 1766.94, "text": "ご応募ください　お待ちしてます", "_asr_interp": True},
            {"start": 1766.94, "end": 1770.39, "text": "はいどこに\n当たるか分かりませんからね", "_asr": True,
             "_asr_first": 1767.33, "_asr_marks": [(3, 1767.33), (16, 1770.13)]}]
    out, stats = sync.align_segments(segs, sp, [], RULES)
    texts = [s["text"] for s in out]
    assert "皆さんぜひ" in texts and stats["dropped"] == 0
    for s in out:
        assert not sync._too_short(s, RULES["min_display_sec"]), s
    assert out[texts.index("ご応募ください　お待ちしてます")]["start"] == pytest.approx(1765.47, abs=0.02)


def test_an_unheard_backchannel_is_not_given_time_back():
    # 相づちだけの字幕は字幕に出さない（`is_standalone_omittable`）ので、前の字幕の時間を削ってまで戻さない
    # （25分11秒「うんうんうん」）
    sp = _map([(1506.77, 1508.56), (1508.85, 1510.93), (1511.68, 1511.91), (1512.39, 1512.75),
               (1512.92, 1513.93)], total=1520)
    segs = [{"start": 1508.51, "end": 1510.97, "text": "一週間のうち六日間費やす", "_asr": True,
             "_asr_first": 1508.51, "_asr_marks": [(0, 1508.79), (10, 1510.71)]},
            {"start": 1510.97, "end": 1512.37, "text": "うんうんうん", "_asr_interp": True},
            {"start": 1512.37, "end": 1515.0, "text": "もうある程度これで書ける状況に", "_asr": True,
             "_asr_first": 1512.37, "_asr_marks": [(0, 1512.37), (1, 1512.89)]}]
    out, stats = sync.align_segments(segs, sp, [], RULES)
    assert "うんうんうん" not in [s["text"] for s in out]
    assert stats["unheard_roomed"] == 0


def test_an_unheard_caption_given_too_little_time_is_still_dropped():
    # 実例（4分53秒）: 聞き手が重ねた「オリンピック はい」は、配った間（0.76 秒）から読める長さを取れない
    sp = _map([(291.44, 293.70), (293.92, 294.10), (294.53, 294.75), (294.90, 297.58)], total=300)
    segs = [{"start": 291.43, "end": 293.76, "text": "僕生まれた年のオリンピック", "_asr": True,
             "_asr_first": 291.43, "_asr_marks": [(0, 291.43), (12, 293.63)]},
            {"start": 293.76, "end": 294.52, "text": "オリンピック　はい", "_asr_interp": True},
            {"start": 294.52, "end": 297.97, "text": "こっから\nいわゆる広告デザインっていうのが", "_asr": True,
             "_asr_first": 294.52, "_asr_marks": [(0, 294.52), (1, 294.80)]}]
    out, stats = sync.align_segments(segs, sp, [], RULES)
    assert all("はい" not in s["text"] for s in out)
    assert stats["dropped"] == 1
    assert out[0]["end"] >= 293.70
    # 外した字幕は、本文・配った時刻・理由を集計に残す（品質ゲートが字幕にしなかった発話を数える）
    assert stats["gone"] == [{"start": 293.76, "end": 294.52, "text": "オリンピック　はい",
                              "reason": "unheard_short"}]


def test_every_dropped_caption_is_listed_with_its_reason():
    # 置き場所が無く時刻の取り合いに加えなかった字幕も、外した字幕として残す
    sp = _map([(570.0, 578.9), (579.2, 584.0)], total=600)
    full = "あ" * 18 + "\n" + "い" * 18
    segs = [{"start": 574.9, "end": 578.86, "text": full, "_asr": True},
            {"start": 578.86, "end": 579.18, "text": "いたんだよね", "_asr_interp": True},
            {"start": 579.18, "end": 584.4, "text": full, "_asr": True}]
    _, stats = sync.align_segments(segs, sp, [578.9], RULES)
    # 声の拾えない字幕をカット点のそばに配った（カットで声が消えた言葉）ときは、理由を cut にする
    assert stats["gone"] == [{"start": 578.86, "end": 579.18, "text": "いたんだよね", "reason": "cut"}]
    # 隣とまとめた字幕は外していない
    sp = _map([(1.0, 3.0), (3.05, 3.4), (3.5, 6.0)], total=10)
    segs = [{"start": 1.0, "end": 3.0, "text": "一文目", "_asr": True},
            {"start": 3.05, "end": 3.4, "text": "はい", "_asr": True},
            {"start": 3.5, "end": 6.0, "text": "二文目", "_asr": True}]
    _, stats = sync.align_segments(segs, sp, [], RULES)
    assert stats["gone"] == []


def test_a_spoken_line_with_no_room_is_added_to_the_next_caption_as_a_line():
    # 実例（12分12秒・51回目）: 聞き手の「黒子ですよ」は認識が書かず、その声（732.52〜733.18 秒）に次の字幕の
    # 頭の「誰」が張り付いた。前後の聞こえた字幕の間に配った 0.38 秒には置き場所が無く、言った言葉が字幕から
    # 消えていた。時刻は動かさず、次の字幕に1行として足す（言った後に出る）
    sp = _map([(730.01, 731.83), (732.52, 733.18), (733.46, 736.02)], total=740)
    segs = [{"start": 730.43, "end": 731.95, "text": "アーティストじゃないんで", "_asr": True,
             "_asr_first": 730.43},
            {"start": 732.0, "end": 732.15, "text": "はい", "_asr_interp": True},
            {"start": 732.15, "end": 732.53, "text": "黒子ですよ", "_asr_interp": True},
            {"start": 732.53, "end": 735.54, "text": "誰が書いたか分かんないけどって", "_asr": True,
             "_asr_first": 732.53}]
    out, stats = sync.align_segments(segs, sp, [], RULES)
    assert [s["text"] for s in out] == ["アーティストじゃないんで", "黒子ですよ\n誰が書いたか分かんないけどって"]
    assert out[1]["start"] == pytest.approx(732.52, abs=0.05)
    assert stats["joined"] == 1 and stats["dropped"] == 1
    # 相づちだけの「はい」は足さず、外した字幕に残す
    assert [(g["text"], g["reason"]) for g in stats["gone"]] == [("はい", "no_room")]


def test_a_spoken_line_with_no_room_goes_to_the_caption_before_when_the_next_is_far():
    # 次の字幕が離れていれば（`LOST_JOIN_SEC` 秒より後ろ）、前の字幕に足す
    sp = _map([(10.0, 12.3), (14.6, 17.0)], total=20)
    segs = [{"start": 10.0, "end": 12.0, "text": "そういうことに努めていきたいなと", "_asr": True,
             "_asr_first": 10.0},
            {"start": 12.0, "end": 12.4, "text": "思います", "_asr_interp": True},
            {"start": 14.6, "end": 17.0, "text": "はい　分かりました", "_asr": True, "_asr_first": 14.6}]
    out, stats = sync.align_segments(segs, sp, [], RULES)
    assert [s["text"] for s in out] == ["そういうことに努めていきたいなと\n思います", "はい　分かりました"]
    assert stats["joined"] == 1 and stats["gone"] == []


def test_a_spoken_line_far_from_both_neighbours_is_not_added():
    # 隣の字幕がどちらも離れていれば足さない（離れた所の言葉として出る）。外した字幕に残し、品質ゲートが数える
    sp = _map([(1.0, 3.0), (8.0, 10.0)], total=12)
    segs = [{"start": 1.0, "end": 3.0, "text": "一文目です", "_asr": True, "_asr_first": 1.0},
            {"start": 5.0, "end": 5.4, "text": "黒子ですよ", "_asr_interp": True},
            {"start": 8.0, "end": 10.0, "text": "二文目です", "_asr": True, "_asr_first": 8.0}]
    out, stats = sync.align_segments(segs, sp, [], RULES)
    assert [s["text"] for s in out] == ["一文目です", "二文目です"]
    assert stats["joined"] == 0
    assert stats["gone"] == [{"start": 5.0, "end": 5.4, "text": "黒子ですよ", "reason": "no_room"}]


def test_an_unheard_caption_with_no_room_does_not_cut_a_heard_one_short():
    # 実例（15分26秒）: 重なって話した「ファンが」は認識に無く、前後の聞こえた字幕の間に隙も無い。
    # それでも時刻を取り合いに加わり、聞こえた「そういう中でね…」を 0.33 秒で消させた
    sp = _map([(920.3, 924.5), (925.72, 929.04), (929.64, 935.0)], total=940)
    segs = [{"start": 923.05, "end": 925.93, "text": "言われていますけど\nファンが先生の文字を",
             "_asr": True, "_asr_first": 923.18},
            {"start": 925.93, "end": 925.93, "text": "ファンが", "_asr_interp": True},
            {"start": 925.72, "end": 929.17, "text": "そういう中でね　筆文字を\n見てくれているわけじゃないですか",
             "_asr": True, "_asr_first": 925.72},
            {"start": 929.68, "end": 931.57, "text": "おそらくその映画だけじゃなくて",
             "_asr": True, "_asr_first": 930.2}]
    out, stats = sync.align_segments(segs, sp, [], RULES)
    # 1枚としても、隣に足しても出さない
    assert sum(s["text"].replace("\n", "").count("ファンが") for s in out) == 1
    shown = [s for s in out if s["text"].startswith("そういう中でね")][0]
    assert shown["end"] - shown["start"] >= 2.5
    assert stats["dropped"] == 1


def test_a_caption_is_not_pushed_onto_the_next_recognised_onset():
    # 実例（21分28秒）: 「…いけないなってい|ふうに思ってますね」の「思ってますね」はカットで消え、
    # 字幕の出だしが間に入った。間の終わり（次の「先ほどね」の話し始め）まで送ったので、
    # 0.33 秒で消え、「先ほどね」も 0.4 秒遅れた
    sp = _map([(1282.98, 1284.78), (1285.12, 1287.37), (1288.78, 1289.97), (1290.14, 1290.94)],
              total=1300)
    segs = [{"start": 1282.97, "end": 1287.46, "text": "この文化庁セットでやっぱり\n考えていかないといけないなってい",
             "_asr": True, "_asr_first": 1282.97},
            {"start": 1287.46, "end": 1288.37, "text": "ふうに思ってますね", "_asr_interp": True, "_asr_heard": 3},
            {"start": 1288.78, "end": 1293.99, "text": "先ほどね　お習字っていうワードが\n出たんですけども",
             "_asr": True, "_asr_first": 1288.78}]
    out, _ = sync.align_segments(segs, sp, [1287.7], RULES)
    nxt = [s for s in out if s["text"].startswith("先ほどね")][0]
    assert nxt["start"] == pytest.approx(1288.78, abs=0.05)
    mid = [s for s in out if s["text"] == "ふうに思ってますね"][0]
    assert mid["end"] - mid["start"] >= 0.8


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


def test_an_unheard_head_does_not_start_on_a_filler_taken_out_of_the_caption_before():
    # 1分35秒（35回目）の形: 前の字幕から外した「こう」は、認識が聞いている（`_asr_tail`）。その
    # 話し始めは前の字幕の声なので、頭を聞き取れなかった次の字幕の話し始めにはしない
    sp = _map([(93.2, 95.3), (95.7, 96.7), (97.13, 99.0)], total=110)
    segs = [{"start": 93.13, "end": 95.19, "text": "それで興味があったんで", "_asr": True,
             "_asr_first": 93.26, "_asr_marks": [(1, 93.26), (10, 95.06)], "_asr_tail": 96.62},
            {"start": 96.9, "end": 99.0, "text": "引いたらそこが書道教室だった", "_asr": True,
             "_asr_first": 97.6, "_asr_marks": [(10, 97.6), (11, 97.75), (12, 97.9)]}]
    out, _ = sync.align_segments(segs, sp, [], RULES)
    assert out[1]["start"] == pytest.approx(97.13, abs=0.02)


# --- カットの向こうに出さない（`_zone`・2026-10-13 38回目の 36分03秒「私も」ほか）-----------------

FULL = "あ" * 18 + "\n" + "い" * 18


def _inside_zones(out):
    return all(s["_zone"][0] - 1e-6 <= s["start"] <= s["end"] <= s["_zone"][1] + 1e-6 for s in out)


def test_a_caption_does_not_linger_past_the_cut():
    # 話し終わり 2.45 秒 + 余韻 0.5 秒 = 2.95 秒は、2.6 秒のカットの向こう（次の場面）
    sp = _map([(1.0, 2.45), (3.5, 6.0)], total=10)
    segs = [{"start": 1.0, "end": 2.45, "text": "一", "_zone": (0.0, 2.6)},
            {"start": 3.5, "end": 6.0, "text": "二", "_zone": (2.6, 10.0)}]
    out, _ = sync.align_segments(segs, sp, [2.6], RULES)
    assert out[0]["end"] == pytest.approx(2.6, abs=0.01)
    assert _inside_zones(out)


def test_a_caption_is_not_snapped_to_speech_in_the_next_scene():
    # 36分03秒（38回目）の形: 「私も」の推定時刻はカットの直後で、近い話し始めは次の質問のもの。
    # そこに寄せると、カットの手前で言った言葉が次の質問に出る
    sp = _map([(1.0, 2.0), (2.5, 2.8), (3.3, 6.0)], total=10)
    segs = [{"start": 1.0, "end": 2.0, "text": "前の話", "_zone": (0.0, 2.9)},
            {"start": 2.95, "end": 3.4, "text": "私も", "_zone": (0.0, 2.9)},
            {"start": 3.3, "end": 6.0, "text": "次の質問です", "_zone": (2.9, 10.0)}]
    out, _ = sync.align_segments(segs, sp, [2.9], RULES)
    nxt = [s for s in out if "次の質問です" in s["text"]][0]
    assert "私も" not in nxt["text"]
    assert nxt["start"] == pytest.approx(3.3, abs=0.02)
    assert _inside_zones(out)


def test_a_flash_is_not_merged_with_a_caption_across_the_cut():
    sp = _map([(1.0, 2.9), (3.05, 3.35), (3.45, 6.0)], total=10)
    segs = [{"start": 1.0, "end": 2.9, "text": "前の話です", "_asr": True, "_zone": (0.0, 3.0)},
            {"start": 3.05, "end": 3.35, "text": "そうですね", "_asr": True, "_zone": (3.0, 10.0)},
            {"start": 3.45, "end": 6.0, "text": FULL, "_asr": True, "_zone": (3.0, 10.0)}]
    out, stats = sync.align_segments(segs, sp, [3.0], RULES)
    assert [s["text"] for s in out][:2] == ["前の話です", "そうですね"]
    assert stats["merged"] == 0
    assert _inside_zones(out)


def test_a_caption_with_no_room_in_its_scene_is_dropped_without_delaying_the_next():
    # 「そうですね」はカットの手前で言ったが、前の字幕で区間が埋まっていて入る隙が無い。
    # カットの向こうに出さずに外し、次の場面の字幕は自分の話し始めに出す
    sp = _map([(1.0, 2.9), (3.2, 6.0)], total=10)
    segs = [{"start": 1.0, "end": 2.9, "text": FULL, "_asr": True, "_zone": (0.0, 3.0)},
            {"start": 2.95, "end": 3.0, "text": "そうですね", "_asr": True, "_zone": (0.0, 3.0)},
            {"start": 3.2, "end": 6.0, "text": "次の話", "_asr": True, "_zone": (3.0, 10.0)}]
    out, stats = sync.align_segments(segs, sp, [3.0], RULES)
    assert all("そうですね" not in s["text"] for s in out)
    assert stats["dropped"] == 1
    assert out[-1]["start"] == pytest.approx(3.2, abs=0.02)
    assert _inside_zones(out)


# --- 長く出続ける2行の字幕を、話の切れ目で2枚に分ける（40回目の 1分22秒ほか・2026-10-14）-------

LONG = "あ" * 12 + "\n" + "い" * 12


def _long_caption(marks, **extra):
    return {"start": 1.0, "end": 9.6, "text": LONG, "_asr": True, "_asr_first": marks[0][1],
            "_asr_marks": marks, **extra}


def test_a_two_line_caption_shown_too_long_is_split_where_the_second_line_is_said():
    # 40回目の 1分22秒: 「私 小学校3年生の時に お習字を/スタートしたんですけど その当時僕が」が
    # 10.2 秒出て、2行目は話す 6 秒前から見えていた。2行目の頭を話した時刻（認識）で2枚に分ける
    sp = _map([(1.0, 5.2), (6.0, 9.6)], total=12)
    segs = [_long_caption([(0, 1.0), (11, 5.0), (12, 6.0), (23, 9.5)])]
    out, stats = sync.align_segments(segs, sp, [], RULES)
    assert [s["text"] for s in out] == ["あ" * 12, "い" * 12]
    assert out[0]["start"] == pytest.approx(1.0, abs=0.02)
    assert out[0]["end"] == pytest.approx(5.7, abs=0.02)   # 話し終わり + 余韻 0.5 秒
    assert out[1]["start"] == pytest.approx(6.0, abs=0.02)
    assert stats["split_long"] == 1
    # 分けた字幕の文字ごとの時刻は、それぞれの行の字の番号で付け直す
    assert out[1]["_asr_marks"][0] == (0, 6.0)


def test_a_two_line_caption_within_the_limit_is_left_alone():
    sp = _map([(1.0, 3.2), (3.6, 6.0)], total=10)
    segs = [{"start": 1.0, "end": 6.0, "text": LONG, "_asr": True, "_asr_first": 1.0,
             "_asr_marks": [(0, 1.0), (12, 3.6), (23, 5.9)]}]
    out, stats = sync.align_segments(segs, sp, [], RULES)
    assert [s["text"] for s in out] == [LONG]
    assert stats["split_long"] == 0


def test_a_second_line_whose_head_was_barely_heard_starts_where_speech_resumes():
    # 2行目の頭の 2 字を認識が拾えなくても、次に拾えた字の前の話し始めで分ける
    sp = _map([(1.0, 5.2), (6.0, 9.6)], total=12)
    segs = [_long_caption([(0, 1.0), (11, 5.0), (14, 6.3), (23, 9.5)])]
    out, _ = sync.align_segments(segs, sp, [], RULES)
    assert [s["text"] for s in out] == ["あ" * 12, "い" * 12]
    assert out[1]["start"] == pytest.approx(6.0, abs=0.02)


def test_a_second_line_the_recogniser_did_not_hear_is_not_split():
    # 2行目を話した時刻が分からない（頭の 3 字以上を拾えない）なら分けない
    sp = _map([(1.0, 5.2), (6.0, 9.6)], total=12)
    segs = [_long_caption([(0, 1.0), (11, 5.0), (16, 7.0), (23, 9.5)])]
    out, stats = sync.align_segments(segs, sp, [], RULES)
    assert [s["text"] for s in out] == [LONG]
    assert stats["split_long"] == 0


def test_a_caption_is_not_split_where_it_would_leave_speech_without_a_caption():
    # 40回目の 36分03秒: 起こしが2つの文を1枚にまとめ、1行目と2行目の間の 2 秒の声（「移したら
    # おいしくなりますね」）は字幕に無かった。分けるとその声の間に字幕が出なくなる
    sp = _map([(1.0, 5.2), (5.5, 7.4), (7.6, 9.6)], total=12)
    segs = [_long_caption([(0, 1.0), (11, 5.0), (12, 7.6), (23, 9.5)])]
    out, stats = sync.align_segments(segs, sp, [], RULES)
    assert [s["text"] for s in out] == [LONG]
    assert stats["split_long"] == 0


def test_a_split_that_would_leave_a_part_too_short_to_read_is_not_made():
    # 2行目を話し始めたのが字幕の終わり間際なら、分けても2枚目が読めない
    sp = _map([(1.0, 9.0), (9.2, 9.6)], total=12)
    segs = [_long_caption([(0, 1.0), (11, 8.9), (12, 9.2), (23, 9.5)])]
    out, stats = sync.align_segments(segs, sp, [], RULES)
    assert [s["text"] for s in out] == [LONG]
    assert stats["split_long"] == 0


def test_the_longest_display_can_be_changed_in_the_template():
    sp = _map([(1.0, 5.2), (6.0, 9.6)], total=12)
    segs = [_long_caption([(0, 1.0), (11, 5.0), (12, 6.0), (23, 9.5)])]
    out, stats = sync.align_segments(segs, sp, [], dict(RULES, max_display_sec=12.0))
    assert [s["text"] for s in out] == [LONG]
    out, stats = sync.align_segments(segs, sp, [], dict(RULES, max_display_sec=0.0))
    assert [s["text"] for s in out] == [LONG]   # 0 なら分けない


def test_split_parts_stay_in_the_scene_of_the_caption():
    sp = _map([(1.0, 5.2), (6.0, 9.6)], total=12)
    segs = [_long_caption([(0, 1.0), (11, 5.0), (12, 6.0), (23, 9.5)], _zone=(0.5, 10.0))]
    out, _ = sync.align_segments(segs, sp, [10.0], RULES)
    assert len(out) == 2 and _inside_zones(out)
    assert all(s["_zone"] == (0.5, 10.0) for s in out)


# 42回目の 1分22秒。改行は「お習字を」の後ろ（「を」の後ろ）にある
SCHOOL = "私\u3000小学校3年生の時に\u3000お習字を\nスタートしたんですけど\u3000その当時僕が"


def _school_caption():
    # 認識の字の番号は句読点の跡を除いた字の順（私0 … 時8 に9 お10 習11 字12 … ど24 そ25 … が30）。
    # 「に」は 3.6 秒に言い始めて 4.2 秒まで伸び、4.4〜4.75 秒に字幕に無い短い声、「お習」は拾えず
    # 5.0 秒から話し始めている
    marks = [(0, 1.0), (5, 2.4), (9, 3.6), (12, 5.6), (18, 6.6), (24, 7.8), (25, 8.4), (30, 9.5)]
    return {"start": 1.0, "end": 9.6, "text": SCHOOL, "_asr": True, "_asr_first": 1.0, "_asr_marks": marks}


def test_a_long_caption_is_split_at_the_best_break_rather_than_at_the_line_break():
    # 改行で分けると「…時に お習字を」|「スタートしたんですけど…」と、「お習字を｜スタートした」が別の字幕になる。
    # 「、」の跡で分け、話している時間の真ん中に近い方（「時に」の後ろ）を取る。2枚目は話し始めから出る
    sp = _map([(1.0, 4.2), (4.4, 4.75), (5.0, 8.0), (8.4, 9.6)], total=12)
    out, stats = sync.align_segments([_school_caption()], sp, [], RULES)
    assert [s["text"] for s in out] == ["私\u3000小学校3年生の時に", "お習字をスタートしたんですけど\nその当時僕が"]
    assert stats["split_long"] == 1
    assert out[1]["start"] == pytest.approx(5.0, abs=0.02)
    assert out[1]["_asr_marks"][0] == (2, 5.6)


def test_speech_left_without_a_caption_is_measured_from_where_the_words_end():
    # 「に」の伸びた声（0.47 秒）と、拾えなかった「お習」の声（0.34 秒）は字幕の言葉の声。字幕に無い声は
    # 間の 0.35 秒だけなので分けてよい。間の声が長ければ（1.2 秒）分けない
    sp = _map([(1.0, 4.2), (4.4, 4.75), (5.0, 8.0), (8.4, 9.6)], total=12)
    assert sync._word_edges(sp, 3.73, 5.34) == pytest.approx((4.2, 5.0), abs=0.02)
    sp = _map([(1.0, 4.2), (4.3, 5.5), (5.6, 8.0), (8.4, 9.6)], total=12)
    out, _ = sync.align_segments([_school_caption()], sp, [], RULES)
    assert "私\u3000小学校3年生の時に" not in [s["text"] for s in out]
