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


def test_a_character_glued_across_a_long_gap_is_not_used():
    # 実例（20分08秒）: 「なるべくね」の「な」が、2.3 秒前の「しれない」の「な」と
    # ひと続きで突き合い、字幕が 2 秒早く出た
    caps = [{"start": 0.0, "end": 1.0, "text": "有利かもしれません"},
            {"start": 1.0, "end": 2.0, "text": "なるべくね細くならない"}]
    tokens = toks("有利かもしれな", 10.0) + [("る", 13.5)] + toks("べくね細くならない", 13.7)
    aligner.align_captions(caps, tokens)
    assert caps[1]["_asr"]
    assert caps[1]["start"] == pytest.approx(13.5 - aligner.CHAR_SEC, abs=0.05)


def test_referee_accepts_a_correction_the_audio_supports():
    # 実例: 校閲の「歌詞織ですギャラは → 菓子折りギャラは」は元の文から離れているので
    # 捨てていた。音声認識の文字に近い方を採る
    judge = aligner.referee_from_tokens(toks("菓子折りですギャラは", 100.0))
    seg = {"start": 100.0, "end": 102.0, "text": "歌詞織 です ギャラ は"}
    assert judge(seg, "菓子折り、ギャラは") is True


def test_referee_rejects_a_correction_the_audio_does_not_support():
    # 実例: 「あと2日後これ工事って言」→「あと二兎を追う者は一兎をも得」（作り話）
    judge = aligner.referee_from_tokens(toks("新版画賞とあと二日後これ工事っていう", 50.0))
    seg = {"start": 50.0, "end": 54.0, "text": "新版画賞と、あと 2 日後これ工事って言"}
    assert judge(seg, "新版画賞と、あと二兎を追う者は一兎をも得") is False


def test_referee_only_listens_near_the_line():
    judge = aligner.referee_from_tokens(toks("菓子折りですギャラは", 300.0))
    seg = {"start": 100.0, "end": 102.0, "text": "歌詞織 です ギャラ は"}
    assert judge(seg, "菓子折り、ギャラは") is False


def test_no_referee_without_recognition(tmp_path, monkeypatch):
    monkeypatch.setenv("AVS_ALIGN_MODEL_DIR", str(tmp_path / "none"))
    assert aligner.referee_for(str(tmp_path / "missing.mp4")) is None


def test_first_recognised_time_is_kept():
    caps = [{"start": 0.0, "end": 2.0, "text": "デザイン書道の第一人者"}]
    aligner.align_captions(caps, toks("書道の第一人者", 35.3))
    assert caps[0]["_asr_first"] == pytest.approx(35.3)
    assert caps[0]["start"] == pytest.approx(35.3 - 4 * aligner.CHAR_SEC, abs=0.01)


def test_a_small_stray_match_far_from_the_rest_is_ignored():
    # 実例（25分44秒）: 「もうこう書き直して…」の「う書」が、3 秒前の「偉そう」の「う」と
    # はぐれた「書」に突き合い、字幕が 3.5 秒早く出て、前の2枚と順番まで入れ替わった
    caps = [{"start": 0.0, "end": 2.0, "text": "先生って言われると偉そうじゃない"},
            {"start": 2.0, "end": 4.0, "text": "もうこう書き直してくれっていう"}]
    tokens = (toks("先生って言われるから何か偉そう", 10.0) + [("書", 13.5)]
              + toks("き直してくれって言われて", 16.6))
    aligner.align_captions(caps, tokens)
    assert caps[1]["_asr_first"] == pytest.approx(16.6)
    # 拾えなかった頭の「もうこう書」の5文字ぶんだけ、さかのぼる
    assert caps[1]["start"] == pytest.approx(16.6 - 5 * aligner.CHAR_SEC, abs=0.01)


def test_recognised_starts_never_go_back_before_the_previous_caption():
    caps = [{"start": 0.0, "end": 1.0, "text": "あいうえお"},
            {"start": 1.0, "end": 2.0, "text": "かきくけこさしすせそ"}]
    # 2枚目は頭の5文字を拾えず、外挿すると1枚目より前に出る
    tokens = toks("あいうえお", 10.0, 0.1) + toks("しすせそ", 10.6, 0.1)
    aligner.align_captions(caps, tokens)
    assert caps[1]["start"] >= caps[0]["start"]
    assert caps[1]["start"] >= 10.4


def test_unaligned_captions_keep_their_order_when_there_is_no_room():
    caps = [{"start": 0.0, "end": 1.0, "text": "あいうえお"},
            {"start": 50.0, "end": 51.0, "text": "ききとれない"},
            {"start": 1.0, "end": 2.0, "text": "かきくけこ"}]
    aligner.align_captions(caps, toks("あいうえお", 10.0) + toks("かきくけこ", 11.0))
    aligner.interpolate_unaligned(caps)
    assert caps[0]["start"] <= caps[1]["start"] <= caps[2]["start"]


def test_a_character_the_proofreader_added_but_nobody_said_is_removed():
    # 実例（68 秒）: 校閲が「最初 に 書 に」を「最初にな書に」にした（前の回は「最初実に」）
    ref = aligner.referee_from_tokens(toks("まず先生が最初に書に出会ったきっかけっていうのは", 70.0))
    seg = {"start": 70.0, "end": 76.0,
           "text": "まず 先生 が え 、 最初 に 書 に 出会っ た きっかけっ て いう の は"}
    want = "まず先生が最初に書に出会ったきっかけっていうのは"
    assert ref.trim(seg, "まず先生が最初にな書に出会ったきっかけっていうのは") == want
    assert ref.trim(seg, "まず先生が最初実に書に出会ったきっかけっていうのは") == want


def test_an_added_word_the_audio_has_is_kept():
    ref = aligner.referee_from_tokens(toks("久木田デザイン書道塾を主宰されて", 50.0))
    seg = {"start": 50.0, "end": 54.0, "text": "久木田デザイン書道塾主宰されて"}
    assert ref.trim(seg, "久木田デザイン書道塾を主宰されて") == "久木田デザイン書道塾を主宰されて"


def test_replacements_are_not_trimmed():
    # 「読んで」→「呼んで」は、認識も「読んで」と聞くが、足しではなく置き換えなので戻さない
    ref = aligner.referee_from_tokens(toks("もう初回ね読んでいただいて", 44.0))
    seg = {"start": 44.0, "end": 46.0, "text": "もう初会ね。読んでいただいて。"}
    assert ref.trim(seg, "もう初回ね。呼んでいただいて。") == "もう初回ね。呼んでいただいて。"


def test_nothing_is_trimmed_where_the_recogniser_heard_nothing():
    ref = aligner.referee_from_tokens(toks("まったく別の話", 300.0))
    seg = {"start": 70.0, "end": 76.0, "text": "最初に書に出会った"}
    assert ref.trim(seg, "最初にな書に出会った") == "最初にな書に出会った"
