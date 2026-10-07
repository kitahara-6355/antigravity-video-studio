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


def test_an_unaligned_caption_between_overlapping_neighbours_keeps_its_place():
    # 実例（15分26秒）: 前の字幕の終わり（認識に無い語の分を外挿）が次の字幕の出だしより後ろで、
    # 間の「ファンが」が次の字幕より後ろに置かれ、並べ直しで順番が入れ替わった
    caps = [{"start": 923.05, "end": 925.93, "text": "言われていますけど", "_asr": True},
            {"start": 928.3, "end": 929.3, "text": "ファンが"},
            {"start": 925.72, "end": 929.17, "text": "そういう中でね", "_asr": True}]
    aligner.interpolate_unaligned(caps)
    ordered = sorted(caps, key=lambda c: c["start"])
    assert [c["text"] for c in ordered] == [c["text"] for c in caps]


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


def test_a_replacement_that_changes_what_was_said_is_undone():
    # 実例（29分00秒）: 校閲が「私が手がけた仕事」を「私がつなげた仕事」にした。認識も「手がけた」
    ref = aligner.referee_from_tokens(toks("デザイン書道講座私が手がけた仕事をそれこそ", 1953.0), keep=())
    seg = {"start": 1954.4, "end": 1958.0, "text": "私が手がけた仕事"}
    assert ref.trim(seg, "私がつなげた仕事") == "私が手がけた仕事"


def test_only_the_replacement_the_audio_contradicts_is_undone():
    # 実例（37分16秒）: 「第1回め」→「初回め」は戻し、「ミレ」→「美麗」（かなを漢字に）は残す
    ref = aligner.referee_from_tokens(
        toks("今日ね初めての初めてはい第一回目のミレチャンネルのゲストとして来て頂いたんですが",
             2567.6, 0.15), keep=())
    seg = {"start": 2569.4, "end": 2574.3,
           "text": "始めてですね、第1回めのミレチャンネルのゲストとして出ていただいたんですが、"}
    got = ref.trim(seg, "始めてですね、初回めの美麗チャンネルのゲストとして出ていただいたんですが、")
    assert got == "始めてですね、第1回めの美麗チャンネルのゲストとして出ていただいたんですが、"


def test_kana_turned_into_kanji_is_kept():
    ref = aligner.referee_from_tokens(toks("すごいたんじゅんな形", 10.0), keep=())
    seg = {"start": 10.0, "end": 12.0, "text": "すごいたんじゅんな形"}
    assert ref.trim(seg, "すごい単純な形") == "すごい単純な形"


def test_a_dictionary_fix_is_kept_even_if_the_recogniser_heard_it_wrong():
    ref = aligner.referee_from_tokens(toks("株式会社バドシアター代表で", 10.0),
                                      keep=(("バドシアター", "アドシアター"),))
    seg = {"start": 10.0, "end": 12.0, "text": "株式会社バドシアター代表で"}
    assert ref.trim(seg, "株式会社アドシアター代表で") == "株式会社アドシアター代表で"


def test_making_a_dictionary_word_without_its_wrong_form_is_still_judged():
    # 実例（37分16秒）: 辞書に「初会」→「初回」があるが、元の文は「第1回め」。辞書どおりの直しではない
    ref = aligner.referee_from_tokens(toks("はい第一回目のゲストとして", 10.0),
                                      keep=(("初会", "初回"),))
    seg = {"start": 10.0, "end": 12.0, "text": "第1回めのゲストとして"}
    assert ref.trim(seg, "初回めのゲストとして") == "第1回めのゲストとして"


def test_a_replacement_the_recogniser_did_not_hear_either_way_is_kept():
    ref = aligner.referee_from_tokens(toks("それこそこういう考え", 10.0), keep=())
    seg = {"start": 10.0, "end": 12.0, "text": "鬼滅の槍がすごい"}
    assert ref.trim(seg, "鬼滅の刃がすごい") == "鬼滅の刃がすごい"


def test_nothing_is_trimmed_where_the_recogniser_heard_nothing():
    ref = aligner.referee_from_tokens(toks("まったく別の話", 300.0))
    seg = {"start": 70.0, "end": 76.0, "text": "最初に書に出会った"}
    assert ref.trim(seg, "最初にな書に出会った") == "最初にな書に出会った"


# --- 間の字幕を話す時間が残らない合わせ方は外す（2026-10-07）------------------------------
# 動画の最後で、締めの「ありがとうございました」が4回あり、認識が拾った1回を最初の
# 「はい 今日はありがとうございました」に合わせた。後ろの3枚（54字）を話す時間が残らず
# （動画の終わりまで 0 秒）、「本日は…」が 0.6 秒だけ出て、残りは動画の外に出て消えた。


def _closing():
    return [{"start": 0.0, "end": 3.0, "text": "これからもどうぞよろしく"},
            {"start": 3.0, "end": 6.5, "text": "はい今日はありがとうございました"},
            {"start": 6.5, "end": 10.0, "text": "本日は先生にお越しいただきました"},
            {"start": 10.0, "end": 12.0, "text": "ありがとうございました"},
            {"start": 12.0, "end": 13.0, "text": "ありがとうございました"}]


def test_a_match_that_leaves_no_time_for_the_captions_after_it_is_released():
    caps = _closing()
    aligner.align_captions(caps, toks("これからもどうぞよろしく", 3.3, 0.13) + toks("ありがとうござ", 11.0))
    assert caps[1].get("_asr"), "前提: 同じ言葉の最初の字幕に合ってしまう"

    released = aligner.release_implausible(caps, end=13.3)
    aligner.interpolate_unaligned(caps, end=13.3)

    assert released == 1 and not caps[1].get("_asr")
    assert [c["start"] for c in caps] == sorted(c["start"] for c in caps)
    assert all(c["end"] <= 13.3 + 1e-6 for c in caps), "動画の外に出さない"
    assert caps[1]["start"] < 8.0, "前の字幕の後ろに続けて出す（認識の「ありがとう」まで待たない）"


def test_a_backchannel_over_the_other_speaker_does_not_release_anything():
    # 相づち（「はい」「うん」）は相手の話に重なるので、間に収まらないのはふつう
    caps = [{"start": 0.0, "end": 2.0, "text": "駄菓子屋の隣に引き戸が"},
            {"start": 2.0, "end": 2.5, "text": "はい"},
            {"start": 2.5, "end": 4.0, "text": "あってそこを開けると"}]
    aligner.align_captions(caps, toks("駄菓子屋の隣に引き戸が", 10.0) + toks("あってそこを開けると", 12.2))

    assert aligner.release_implausible(caps, end=20.0) == 0
    assert caps[0]["_asr"] and caps[2]["_asr"]


def test_of_two_matches_that_leave_no_room_the_one_out_of_step_with_its_neighbours_goes():
    def anchored(start, end, est, text):
        return {"start": start, "end": end, "_est_start": est, "_est_end": est + (end - start),
                "text": text, "_asr": True}
    caps = [anchored(10.0, 12.0, 10.0, "あいうえおかきくけこ"),
            anchored(18.0, 20.0, 12.0, "ありがとうございました"),  # 6 秒先の同じ言葉に合った
            {"start": 14.0, "end": 17.0, "text": "さしすせそたちつてとなにぬねのはひふへほまみむめも"},
            anchored(17.0, 19.0, 17.0, "やゆよらりるれろ"),
            anchored(19.5, 21.0, 19.5, "わをんがぎぐげご")]

    assert aligner.release_implausible(caps, end=30.0) == 1
    assert not caps[1].get("_asr") and caps[3]["_asr"]
    assert caps[1]["start"] == 12.0, "外した字幕は推定の時刻に戻す"


def test_captions_after_the_last_match_are_kept_inside_the_media():
    caps = [{"start": 0.0, "end": 1.0, "text": "あいうえお"},
            {"start": 1.0, "end": 3.0, "text": "ききとれない"},
            {"start": 3.0, "end": 5.0, "text": "これもききとれない"}]
    aligner.align_captions(caps, toks("あいうえお", 3.0))  # 3 秒遅らせると最後が 8 秒まで出る

    aligner.interpolate_unaligned(caps, end=6.5)

    assert caps[-1]["end"] <= 6.5
    assert caps[0]["end"] <= caps[1]["start"] < caps[2]["start"]


def test_captions_before_the_first_match_never_start_before_zero():
    caps = [{"start": 1.0, "end": 2.0, "text": "ききとれない"},
            {"start": 2.0, "end": 3.0, "text": "あいうえお"}]
    aligner.align_captions(caps, toks("あいうえお", 0.5))  # 1.5 秒早めると頭が -0.5 秒になる

    aligner.interpolate_unaligned(caps)

    assert 0.0 <= caps[0]["start"] < caps[0]["end"] <= caps[1]["start"]


def test_the_cut_step_keeps_the_closing_captions_inside_the_cut(tmp_path, monkeypatch):
    import smart_cut_engine
    from subtitle_engine import sync

    cut = tmp_path / "cut.mp4"
    cut.write_bytes(b"\x00" * 2048)
    monkeypatch.setattr(aligner, "tokens_for", lambda media: toks("これからもどうぞよろしく", 3.3, 0.13)
                        + toks("ありがとうござ", 11.0))
    monkeypatch.setattr(sync, "speech_map", lambda path: None)
    monkeypatch.setattr(sync, "align_segments", lambda segs, *a, **k: (segs, None))

    out = smart_cut_engine._align_to_speech(cut, _closing(), [], source_path="src.mp4", ranges=[(0.0, 13.3)])

    assert all(c["end"] <= 13.3 + 1e-6 for c in out), "残した区間の合計（動画の長さ）の外に出さない"
    assert out[1]["start"] < 8.0
