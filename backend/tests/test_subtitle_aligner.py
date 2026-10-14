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


def _guest_then_echo():
    # 実例（2分32秒・28回目）: ゲストの「…僕のデビューなんですよ」に聞き手が「デビューですか？」と
    # 返す。認識は2つの「デビュー」を1つにまとめ、頭の「デ」「ビ」をゲスト側の時刻で出した
    caps = [{"start": 151.5, "end": 155.6, "text": "それで泣きながら帰ったっていうのが\n僕のデビューなんですよ"},
            {"start": 155.6, "end": 156.7, "text": "デビューですか？"}]
    tokens = (toks("それで泣きながら帰った", 152.0, 0.13)
              + [("デ", 153.9), ("ビ", 154.7)] + toks("ューですか", 155.6, 0.12))
    return caps, tokens


def test_a_stray_head_that_leaves_the_caption_before_unspeakable_is_not_used():
    caps, tokens = _guest_then_echo()
    aligner.align_captions(caps, tokens)
    guest, echo = caps
    assert echo["_asr"] and echo["_asr_first"] == pytest.approx(155.6)
    # 拾えなかった頭の「デビ」の2文字ぶんだけ、さかのぼる
    assert echo["start"] == pytest.approx(155.6 - 2 * aligner.CHAR_SEC, abs=0.01)
    # ゲストの字幕の聞こえなかった尻（17字）を話せる時間が残る
    assert echo["start"] - guest["start"] >= 28 / aligner.MAX_CPS


def test_a_stray_head_is_kept_when_the_caption_before_has_time():
    # 前の字幕を全部聞き取れていれば、頭の1文字が離れていても動かさない
    # （話し始めの1文字は、認識の時刻が早めに出ることが多い・28回目で90枚）
    caps = [{"start": 0.0, "end": 1.0, "text": "あいうえお"},
            {"start": 1.0, "end": 2.0, "text": "かきくけこ"}]
    aligner.align_captions(caps, toks("あいうえお", 10.0, 0.1) + [("か", 11.0)] + toks("きくけこ", 11.8, 0.1))
    assert caps[1]["start"] == pytest.approx(11.0)


def test_a_head_heard_as_a_whole_phrase_is_kept_even_if_the_caption_before_runs_out():
    # 頭が3文字以上のひと続きで聞こえていれば、前の字幕の側が誤り（28回目の 35分40秒）
    caps = [{"start": 0.0, "end": 3.0, "text": "今は30本ぐらいしか作れないとかその原毛の質まで悪くなっちゃって"},
            {"start": 3.0, "end": 5.0, "text": "イタチにおいてはもう入ってこないのね"}]
    aligner.align_captions(caps, toks("今は三十本ぐらいしか作れないと", 10.0, 0.13) + toks("タチにおいては", 12.6, 0.15))
    assert caps[1]["_asr_first"] == pytest.approx(12.6)


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


def _brush_question():
    # 2分19秒（34回目）: 校閲が辞書どおりに「もういつですか？」を「もう毛筆ですか？」に直した。認識は
    # 「もういつです」と聞いているので、直した字幕は突き合わず、声より 2.3 秒早く出た（33回目は合っていた）
    caps = [{"start": 0.0, "end": 8.0, "text": "文鎮置かないで帰ってきたんですよ"},
            {"start": 8.0, "end": 10.0, "text": "もう毛筆ですか？"},
            {"start": 10.0, "end": 12.0, "text": "「3」って書いたの覚えてるんですけど"}]
    heard = (toks("文鎮置かないで帰ってきたんですよ", 1.0) + [("も", 7.8)] + toks("ういつです", 11.9, 0.12)
             + toks("三って書いたの覚えてるんですけど", 15.0))
    return caps, heard


def test_a_caption_the_dictionary_corrected_takes_the_time_of_what_was_heard():
    caps, heard = _brush_question()
    aligner.align_captions(caps, heard)
    assert caps[0]["_asr"] and caps[2]["_asr"] and not caps[1].get("_asr")
    n = aligner.align_heard_forms(caps, heard, terms=(("もういつですか", "もう毛筆ですか"),))
    assert n == 1 and caps[1]["_asr"]
    assert caps[1]["start"] == pytest.approx(11.9 - aligner.CHAR_SEC, abs=0.05)
    assert caps[1]["text"] == "もう毛筆ですか？"  # 字幕の文はそのまま
    assert all(0 <= c < len("もう毛筆ですか") for c, _ in caps[1]["_asr_marks"])


def test_a_corrected_caption_stays_unaligned_when_its_old_form_was_not_heard_either():
    caps, heard = _brush_question()
    caps[1]["text"] = "あっもう、毛筆。"
    aligner.align_captions(caps, heard)
    assert aligner.align_heard_forms(caps, heard, terms=(("湿布", "毛筆"),)) == 0
    assert not caps[1].get("_asr")


def test_only_the_recognition_between_the_matched_neighbours_is_used():
    # 直す前の形が、前後の合った字幕の外（別の所）で聞こえていても使わない
    caps, heard = _brush_question()
    heard = [(c, t) for c, t in heard if t < 7.0 or t >= 15.0] + toks("もういつですか", 30.0)
    aligner.align_captions(caps, heard)
    assert aligner.align_heard_forms(caps, heard, terms=(("もういつですか", "もう毛筆ですか"),)) == 0


def test_a_caption_matched_as_written_is_not_touched():
    caps = [{"start": 0.0, "end": 2.0, "text": "もう毛筆ですか？"}]
    heard = toks("もう毛筆ですか", 5.0)
    aligner.align_captions(caps, heard)
    before = dict(caps[0])
    assert aligner.align_heard_forms(caps, heard, terms=(("もういつですか", "もう毛筆ですか"),)) == 0
    assert caps[0] == before


def test_the_old_form_may_be_longer_than_the_correction():
    # 「角シアター」→「アドシアター」のように長さが変わっても、字幕の何文字目かは字幕の文で数える
    caps = [{"start": 0.0, "end": 1.0, "text": "そうです"},
            {"start": 1.0, "end": 2.0, "text": "久木田です"},
            {"start": 2.0, "end": 3.0, "text": "よろしくお願いします"}]
    heard = toks("そうです", 1.0) + toks("くきたさんです", 4.0) + toks("よろしくお願いします", 8.0)
    aligner.align_captions(caps, heard)
    assert not caps[1].get("_asr")
    assert aligner.align_heard_forms(caps, heard, terms=(("くきたさん", "久木田"),)) == 1
    assert all(0 <= c < len("久木田です") for c, _ in caps[1]["_asr_marks"])
    assert caps[1]["start"] == pytest.approx(4.0, abs=0.05)


def test_the_cut_step_matches_dictionary_corrections_by_what_was_heard(tmp_path, monkeypatch):
    import smart_cut_engine
    from subtitle_engine import sync

    cut = tmp_path / "cut.mp4"
    cut.write_bytes(b"\x00" * 2048)
    caps, heard = _brush_question()
    monkeypatch.setattr(aligner, "tokens_for", lambda media: heard)
    monkeypatch.setattr(aligner, "_dictionary_terms", lambda: (("もういつですか", "もう毛筆ですか"),))
    monkeypatch.setattr(sync, "speech_map", lambda path: None)
    monkeypatch.setattr(sync, "align_segments", lambda segs, *a, **k: (segs, None))

    out = smart_cut_engine._align_to_speech(cut, caps, [], source_path="src.mp4", ranges=[(0.0, 40.0)])

    assert out[1]["start"] == pytest.approx(11.9 - aligner.CHAR_SEC, abs=0.05)


def test_a_repeated_reply_takes_the_recognised_time_nearest_its_own_estimate():
    # 実例（3分04秒・31回目）: ゲストの「そうですね」→ 聞き手の「何か一番最初のきっかけなんですね」→
    # ゲストの「そうですね」。認識は2つ目の「そうですね」だけを拾った。全体の突き合わせは同じ長さなら
    # 早い方を採るので、1つ目が2つ目の時刻になり、間の質問は 1 秒に詰まって出なかった
    caps = [{"start": 179.75, "end": 183.52, "text": "その経験が今の活動の原点に？"},
            {"start": 183.52, "end": 184.82, "text": "そうですね"},
            {"start": 184.82, "end": 188.52, "text": "何か一番最初のきっかけなんですね"},
            {"start": 188.52, "end": 189.78, "text": "そうですね"},
            {"start": 189.78, "end": 194.59, "text": "ぼくはね　中学校入ってね"}]
    rec = toks("その経験が今の活動の原点で", 180.0) + toks("そうですね", 188.5) + toks("僕はね中学校入ってね", 190.3)
    aligner.align_captions(caps, rec)
    assert not caps[1].get("_asr")
    assert caps[3].get("_asr") and caps[3]["start"] == pytest.approx(188.5, abs=0.1)


def test_a_repeated_reply_keeps_its_match_when_its_own_estimate_is_nearer():
    caps = [{"start": 183.52, "end": 184.82, "text": "そうですね"},
            {"start": 184.82, "end": 188.52, "text": "何か一番最初のきっかけなんですね"},
            {"start": 188.52, "end": 189.78, "text": "そうですね"}]
    aligner.align_captions(caps, toks("そうですね", 183.6) + toks("僕はね中学校入ってね", 190.3))
    assert caps[0].get("_asr") and caps[0]["start"] == pytest.approx(183.6, abs=0.1)
    assert not caps[2].get("_asr")


def test_a_repeated_reply_does_not_jump_over_a_caption_heard_later():
    # 間の字幕がもっと後ろで聞こえているなら、移すと順番が入れ替わるので移さない
    caps = [{"start": 10.0, "end": 11.0, "text": "そうですね"},
            {"start": 11.0, "end": 14.0, "text": "何か一番最初のきっかけ"},
            {"start": 14.0, "end": 15.0, "text": "そうですね"}]
    aligner.align_captions(caps, toks("そうですね", 14.0) + toks("何か一番最初のきっかけ", 16.0))
    assert caps[0].get("_asr") and not caps[2].get("_asr")


# 言いよどみにも指示語にもなる語（「こう」「あの」「その」）は文字だけでは決められない。
# 認識（ReazonSpeech）は放送の字幕で学習していて言いよどみを書き起こさないので、前後を続けて
# 聞いていて間の語だけが無いときに外す（31回目: 「小さいこうモニター」「層の幅をえ広げる」）
FILLERS = ["あのね", "あの", "こう", "その", "うん", "ええ", "え"]


def test_a_filler_the_recogniser_skipped_is_removed_from_the_caption():
    caps = [{"start": 0.0, "end": 3.0, "text": "小さいこうモニターを見ながら"}]
    assert aligner.drop_unheard_fillers(caps, toks("小さいモニターを見ながら", 10.0), FILLERS) == 1
    assert caps[0]["text"] == "小さいモニターを見ながら"


def test_a_filler_the_recogniser_heard_is_kept():
    # 「こうやって」「隣にこう引き戸が」のように認識が書き起こしたものは外さない
    caps = [{"start": 0.0, "end": 3.0, "text": "隣にこう引き戸が"}]
    assert aligner.drop_unheard_fillers(caps, toks("隣にこう引き戸が", 10.0), FILLERS) == 0
    assert caps[0]["text"] == "隣にこう引き戸が"


def test_a_filler_is_kept_where_the_recogniser_did_not_hear_both_sides():
    caps = [{"start": 0.0, "end": 3.0, "text": "その名前を出さない"}]
    assert aligner.drop_unheard_fillers(caps, toks("名前を出さない", 10.0), FILLERS) == 0
    caps = [{"start": 0.0, "end": 3.0, "text": "書道のこう世界"}]
    assert aligner.drop_unheard_fillers(caps, toks("書道の", 10.0) + toks("世界", 13.0), FILLERS) == 0


def test_a_one_character_filler_goes_only_before_a_break():
    caps = [{"start": 0.0, "end": 3.0, "text": "層の幅をえ\n広げる意味で"},
            {"start": 3.0, "end": 5.0, "text": "お考えです"}]
    rec = toks("層の幅を広げる意味で", 10.0) + toks("お考です", 13.0)
    assert aligner.drop_unheard_fillers(caps, rec, FILLERS) == 1
    # 外して1行に入るなら1行に組み直す（`_rewrap`）
    assert caps[0]["text"] == "層の幅を広げる意味で"
    assert caps[1]["text"] == "お考えです"


def test_the_space_next_to_a_removed_filler_goes_with_it():
    caps = [{"start": 0.0, "end": 3.0, "text": "皆さん　あのね　視聴者の皆さん"},
            {"start": 3.0, "end": 6.0, "text": "一番大きいので　うん"},
            {"start": 6.0, "end": 9.0, "text": "下手なことは"}]
    rec = toks("皆さん視聴者の皆さん", 10.0) + toks("一番大きいので下手なことは", 13.0)
    assert aligner.drop_unheard_fillers(caps, rec, FILLERS) == 2
    assert caps[0]["text"] == "皆さん　視聴者の皆さん"
    assert caps[1]["text"] == "一番大きいので"


def test_a_caption_is_rewrapped_after_a_filler_is_taken_out():
    # 40回目の 16分39秒: 「その」があると「方でも」までが1行に入らず「テレビの/方でも」と折っていた。
    # 「その」を外した後も、その折り目のまま出た
    caps = [{"start": 0.0, "end": 4.0, "text": "ドラマというかそのアニメのテレビの\n方でもおそらってみんな見てるでしょ"}]
    rec = toks("ドラマというかアニメのテレビの方でもおそらってみんな見てるでしょ", 10.0)
    assert aligner.drop_unheard_fillers(caps, rec, FILLERS) == 1
    assert caps[0]["text"] == "ドラマというかアニメのテレビの方でも\nおそらってみんな見てるでしょ"


def test_fillers_in_a_row_go_together():
    caps = [{"start": 0.0, "end": 3.0, "text": "先生　あのその縁っていう"}]
    assert aligner.drop_unheard_fillers(caps, toks("先生縁っていう", 10.0), FILLERS) == 2
    assert caps[0]["text"] == "先生　縁っていう"


def test_a_caption_that_is_only_a_filler_is_left_to_the_backchannel_rule():
    caps = [{"start": 0.0, "end": 2.0, "text": "書いてくれた"},
            {"start": 2.0, "end": 3.0, "text": "うん"},
            {"start": 3.0, "end": 5.0, "text": "それでね"}]
    assert aligner.drop_unheard_fillers(caps, toks("書いてくれたそれでね", 10.0), FILLERS) == 0
    assert caps[1]["text"] == "うん"


def test_the_fillers_to_check_live_in_the_template_rules():
    from template_config import template_config

    words = template_config.get_subtitle_rules()["omit_unheard_fillers"]
    assert {"こう", "あの", "その", "え"} <= set(words)
    assert "この" not in words, "「このチャンネル」の「この」は認識が落としても中身"


def test_the_cut_step_drops_fillers_the_recogniser_skipped(tmp_path, monkeypatch):
    import smart_cut_engine
    from subtitle_engine import sync

    cut = tmp_path / "cut.mp4"
    cut.write_bytes(b"\x00" * 2048)
    monkeypatch.setattr(aligner, "tokens_for", lambda media: toks("小さいモニターを見ながら", 1.0))
    monkeypatch.setattr(sync, "speech_map", lambda path: None)
    monkeypatch.setattr(sync, "align_segments", lambda segs, *a, **k: (segs, None))

    caps = [{"start": 1.0, "end": 4.0, "text": "小さいこうモニターを見ながら"}]
    out = smart_cut_engine._align_to_speech(cut, caps, [], source_path="src.mp4", ranges=[(0.0, 10.0)])

    assert out[0]["text"] == "小さいモニターを見ながら"


def test_a_drawn_out_filler_is_removed_but_not_across_a_long_silence():
    # 実例（31分01秒・31回目）: 「毎回そのえ、課題が」の「え」は伸ばして1.2秒。認識は「その」「課題」だけ
    caps = [{"start": 0.0, "end": 3.0, "text": "毎回そのえ　課題があるので"}]
    rec = toks("毎回その", 10.0) + toks("課題があるので", 11.8)
    assert aligner.drop_unheard_fillers(caps, rec, FILLERS) == 1
    assert caps[0]["text"] == "毎回その課題があるので"
    caps = [{"start": 0.0, "end": 3.0, "text": "毎回そのえ　課題があるので"}]
    rec = toks("毎回その", 10.0) + toks("課題があるので", 15.0)
    assert aligner.drop_unheard_fillers(caps, rec, FILLERS) == 0


def test_a_lead_word_left_behind_a_removed_filler_goes_too():
    # 実例（7分29秒・31回目）: 「書いたんですようんで、ここ」の「うん」だけ外すと「書いたんですよで」と出る。
    # 「で、」は文頭の聞き流し語（omit_lead_words）
    # 整形は句読点の跡の折り目に印（`_break_punct`）を付ける（「…うんで、/ここ、」）
    caps = [{"start": 0.0, "end": 3.0, "text": "書いたんですようんで\nここ\u3000でっかいカメラが",
             "_break_punct": True}]
    rec = toks("書いたんですよでここでっかいカメラが", 10.0)
    assert aligner.drop_unheard_fillers(caps, rec, FILLERS, leads=["で"]) == 2
    assert caps[0]["text"] == "書いたんですよ\nここ\u3000でっかいカメラが"
    caps = [{"start": 0.0, "end": 3.0, "text": "書いたんですよ\u3000うん\u3000で\u3000ここ"}]
    assert aligner.drop_unheard_fillers(caps, rec, FILLERS, leads=["で"]) == 2
    assert caps[0]["text"] == "書いたんですよ\u3000ここ"
    caps = [{"start": 0.0, "end": 3.0, "text": "先生あのでも本当に"}]
    assert aligner.drop_unheard_fillers(caps, toks("先生でも本当に", 10.0), FILLERS, leads=["で"]) == 1
    assert caps[0]["text"] == "先生でも本当に", "「でも」の「で」は文頭の「で、」ではない"


def test_removing_a_filler_keeps_the_other_spaces_as_they_were():
    caps = [{"start": 0.0, "end": 3.0, "text": "LINE こう やり取り"}]
    assert aligner.drop_unheard_fillers(caps, toks("LINEやり取り", 10.0), FILLERS) == 1
    assert caps[0]["text"] == "LINE やり取り"


def _filler_after_a_sentence():
    # 1分33秒（35回目）: 整形が「それで興味があったんで、こう」の「こう」を外した。認識は「こう」を聞いていて、
    # 次の「引いたらそこが書道教室だった」はほとんど聞き取れていない。前後の合った字幕の間に配ると、
    # 次の字幕が「こう」の声の所に 1.4 秒早く出た（33回目は「こう」が前の字幕にあって合っていた）
    caps = [{"start": 93.1, "end": 95.2, "text": "それで興味があったんで"},
            {"start": 97.1, "end": 98.8, "text": "引いたらそこが書道教室だった"},
            {"start": 99.5, "end": 101.5, "text": "へえ　そういう出会いなんです"}]
    heard = (toks("それで興味があったんで", 93.26, 0.18) + [("こ", 95.7), ("う", 96.62), ("へ", 97.12)]
             + toks("えそういう出会いなんです", 99.64, 0.14))
    return caps, heard


def test_a_filler_heard_right_after_a_caption_counts_as_its_voice():
    caps, heard = _filler_after_a_sentence()
    aligner.align_captions(caps, heard)
    assert caps[0]["_asr"] and not caps[1].get("_asr") and caps[2]["_asr"]
    assert aligner.mark_filler_tails(caps, heard, words=["こう", "あの"]) == 1
    assert caps[0]["_asr_tail"] == pytest.approx(96.62)


def test_an_unaligned_caption_is_not_put_on_a_filler_taken_out_of_the_caption_before():
    caps, heard = _filler_after_a_sentence()
    aligner.align_captions(caps, heard)
    aligner.mark_filler_tails(caps, heard, words=["こう"])
    aligner.interpolate_unaligned(caps)
    assert caps[1]["start"] == pytest.approx(96.62 + aligner.TAIL_SEC, abs=0.01)
    assert caps[1]["end"] <= caps[2]["start"]


def test_a_filler_that_starts_the_next_caption_is_left_to_it():
    caps, heard = _filler_after_a_sentence()
    caps[1]["text"] = "こう引いたらそこが書道教室だった"
    aligner.align_captions(caps, heard)
    assert aligner.mark_filler_tails(caps, heard, words=["こう"]) == 0


def test_a_word_said_straight_on_is_not_taken_for_a_filler():
    # 「こうやって」のように続けて話した語の頭は、言いよどみとして切り離さない
    caps, heard = _filler_after_a_sentence()
    heard = [(c, t) for c, t in heard if not 95.5 < t < 97.5] + toks("こうやって", 95.7, 0.12)
    heard.sort(key=lambda x: x[1])
    aligner.align_captions(caps, heard)
    assert aligner.mark_filler_tails(caps, heard, words=["こう"]) == 0


def test_a_filler_long_after_the_caption_is_not_its_voice():
    # 前の字幕の声から離れた言いよどみは、間の（聞き取れなかった）字幕の後ろで言ったのかもしれない
    caps, heard = _filler_after_a_sentence()
    heard = [(c, t + (1.5 if 95.5 < t < 97.5 else 0.0)) for c, t in heard]
    aligner.align_captions(caps, heard)
    assert aligner.mark_filler_tails(caps, heard, words=["こう"]) == 0


def test_the_fillers_after_a_caption_come_from_the_template_rules(monkeypatch):
    caps, heard = _filler_after_a_sentence()
    aligner.align_captions(caps, heard)
    rules = {"omit_unheard_fillers": ["あの"], "omit_interjections": ["こう"]}
    from template_config import template_config
    monkeypatch.setattr(template_config, "get_subtitle_rules", lambda: rules)
    assert aligner.mark_filler_tails(caps, heard) == 1


def test_the_cut_step_keeps_unaligned_captions_off_a_removed_filler(tmp_path, monkeypatch):
    caps, heard = _filler_after_a_sentence()
    cut = tmp_path / "cut.mp4"
    cut.write_bytes(b"x")
    monkeypatch.setattr(aligner, "tokens_for", lambda media: heard)
    from subtitle_engine import sync
    seen = {}

    def fake_align(segments, speech, cut_points, rules):
        seen.update({c["text"]: c for c in segments})
        return segments, {}

    monkeypatch.setattr(sync, "speech_map", lambda media: None)
    monkeypatch.setattr(sync, "align_segments", fake_align)
    import smart_cut_engine
    smart_cut_engine._align_to_speech(str(cut), caps, [], source_path=str(cut), ranges=[(0.0, 200.0)])
    assert seen["それで興味があったんで"].get("_asr_tail") == pytest.approx(96.62)
    assert seen["引いたらそこが書道教室だった"]["start"] >= 97.0


def test_a_filler_is_not_taken_from_the_head_of_the_next_caption():
    # 12分25秒（35回目の試し）: 聞き手の「ああ」を認識は「あ」「の」と聞いた。「あの」として前の字幕の声に
    # すると、「ああ」が 1.8 秒遅れた。聞いた最初の字が次の字幕の最初の字なら、次の字幕の声かもしれない
    caps = [{"start": 742.0, "end": 745.2, "text": "強いなと思ったのは"},
            {"start": 745.9, "end": 746.8, "text": "ああ"},
            {"start": 747.8, "end": 750.0, "text": "テンポじゃないですか"}]
    heard = (toks("強いなと思ったのは", 743.5, 0.2) + [("あ", 745.9), ("の", 746.66)]
             + toks("テンポじゃないですか", 747.82, 0.15))
    aligner.align_captions(caps, heard)
    assert aligner.mark_filler_tails(caps, heard, words=["あの"]) == 0


def test_a_one_character_filler_is_not_taken_for_one():
    # 21分01秒（35回目の試し）: 認識が「縮小しても」の頭を「あ」と聞いた。1文字の言いよどみ（「あ」「え」）は
    # 聞き違いと見分けられないので、前の字幕の声にはしない
    caps, heard = _filler_after_a_sentence()
    heard = [(c, t) for c, t in heard if not 95.5 < t < 97.5] + [("あ", 95.7), ("へ", 97.12)]
    heard.sort(key=lambda x: x[1])
    aligner.align_captions(caps, heard)
    assert aligner.mark_filler_tails(caps, heard, words=["あ", "こう"]) == 0


def test_the_characters_of_a_filler_must_be_said_together():
    # 30分37秒（35回目の試し）: 「ま」と 3.2 秒後の「あ」を「まあ」とみなし、間の「ものだったんですけど」の
    # 字幕が 3.4 秒遅れた
    caps, heard = _filler_after_a_sentence()
    heard = [(c, t) for c, t in heard if not 95.5 < t < 97.5] + [("ま", 95.7), ("あ", 98.9)]
    heard.sort(key=lambda x: x[1])
    aligner.align_captions(caps, heard)
    assert aligner.mark_filler_tails(caps, heard, words=["まあ"]) == 0


def test_a_filler_is_not_taken_from_a_backchannel_caption_further_on():
    # 17分45秒（35回目の試し）: 認識が聞いた聞き手の「ええ」には「ええ」の字幕がある（間の「うん」の後ろ）。
    # 前の字幕の声にすると「うん」「ええ」が後ろへ押し出された
    caps = [{"start": 1058.6, "end": 1064.5, "text": "逆にその98%の人を相手にしたいわけ"},
            {"start": 1064.5, "end": 1065.3, "text": "うん"},
            {"start": 1065.3, "end": 1065.9, "text": "ええ"},
            {"start": 1065.9, "end": 1070.0, "text": "普段筆を持たない人"}]
    heard = (toks("逆にその九十八の人を相手にしたいわけ", 1059.07, 0.33) + [("え", 1065.47), ("え", 1065.67)]
             + toks("普段筆を持たない人", 1066.15, 0.2))
    aligner.align_captions(caps, heard)
    assert caps[0]["_asr"] and caps[3]["_asr"]
    assert aligner.mark_filler_tails(caps, heard, words=["ええ"]) == 0


# --- 字幕は、その言葉が残った区間（カットとカットの間）の中に出す（2026-10-14） ---------------

def test_an_unheard_caption_stays_before_the_cut():
    # 38回目の 36分03秒「私も」: 認識は「分かりました」と聞いて合わず、前後の合った字幕の間に配ったら、
    # カットの向こうの次の質問の区間に出た
    caps = [{"start": 0.0, "end": 2.0, "text": "あやかりたいと思います", "_zone": (0.0, 3.0)},
            {"start": 2.0, "end": 2.6, "text": "私も", "_zone": (0.0, 3.0)},
            {"start": 3.5, "end": 6.0, "text": "先生がこれからやってみたいことは", "_zone": (3.0, 8.0)}]
    heard = toks("あやかりたいと思います", 0.2, 0.15) + toks("先生がこれからやってみたいことは", 4.4, 0.15)
    aligner.align_captions(caps, heard)
    assert caps[0]["_asr"] and caps[2]["_asr"] and not caps[1].get("_asr")
    aligner.interpolate_unaligned(caps, end=8.0)
    assert caps[0]["end"] <= caps[1]["start"] < caps[1]["end"] <= 3.0


def test_without_zones_unheard_captions_are_spread_as_before():
    caps = [{"start": 0.0, "end": 2.0, "text": "あやかりたいと思います"},
            {"start": 2.0, "end": 2.6, "text": "私も"},
            {"start": 3.5, "end": 6.0, "text": "先生がこれからやってみたいことは"}]
    heard = toks("あやかりたいと思います", 0.2, 0.15) + toks("先生がこれからやってみたいことは", 4.4, 0.15)
    aligner.align_captions(caps, heard)
    aligner.interpolate_unaligned(caps, end=8.0)
    assert caps[1]["start"] == pytest.approx(caps[0]["end"]) and caps[1]["end"] == pytest.approx(4.4)


def test_a_caption_with_no_room_left_in_its_zone_gets_none():
    caps = [{"start": 0.0, "end": 2.9, "text": "あやかりたいと思います", "_zone": (0.0, 3.0)},
            {"start": 2.9, "end": 3.0, "text": "私も", "_zone": (0.0, 3.0)},
            {"start": 3.5, "end": 6.0, "text": "先生がこれからやってみたいことは", "_zone": (3.0, 8.0)}]
    heard = toks("あやかりたいと思います", 1.4, 0.15) + toks("先生がこれからやってみたいことは", 4.4, 0.15)
    aligner.align_captions(caps, heard)
    aligner.keep_in_zones(caps, [3.0])
    aligner.interpolate_unaligned(caps, end=8.0)
    assert caps[1]["start"] == caps[1]["end"] == pytest.approx(3.0)


def test_an_unheard_tail_does_not_run_past_the_cut():
    # 素材の 38分44秒: 認識が聞かなかった尻の「悪くなっちゃって」を 1 字 CHAR_SEC で外挿すると、
    # 区間の外に 0.9 秒出た
    caps = [{"start": 0.0, "end": 4.0, "text": "作れないとか原毛の質まで悪くなっちゃって", "_zone": (0.0, 3.6)}]
    heard = toks("作れないとか原毛の質まで", 1.0, 0.2)
    aligner.align_captions(caps, heard)
    assert caps[0]["end"] > 3.6
    assert aligner.keep_in_zones(caps, [3.6]) == 1
    assert caps[0]["start"] == pytest.approx(1.0) and caps[0]["end"] == pytest.approx(3.6)


def test_a_caption_heard_on_both_sides_of_a_cut_keeps_its_words():
    # 発話が間（カットで詰めた）をまたいで話されたら、言葉が聞こえた区間まで出してよい
    caps = [{"start": 0.0, "end": 2.5, "text": "スタートしたんですけどその当時僕が", "_zone": (0.0, 2.5)}]
    heard = toks("スタートしたんですけど", 0.5, 0.15) + toks("その当時僕が", 2.6, 0.15)
    aligner.align_captions(caps, heard)
    aligner.keep_in_zones(caps, [2.5, 6.0])
    assert caps[0]["_zone"] == (0.0, 6.0)
    assert caps[0]["end"] == pytest.approx(2.6 + 5 * 0.15 + aligner.CHAR_SEC)


def test_captions_without_a_zone_are_left_alone():
    caps = [{"start": 0.0, "end": 9.0, "text": "どこでもいい"}]
    assert aligner.keep_in_zones(caps, [3.0]) == 0 and caps[0]["end"] == 9.0


def test_the_old_form_the_recogniser_heard_is_used_whatever_the_dictionary_order():
    # 辞書に直す前の形がいくつもあると（「書字」は「周知」「周辞」）、以前は集合の並びで1つ選び、
    # 同じ入力でも起動ごとに合わせ方が変わった（31分05秒の「これあの　アドシアターのね」）
    caps = [{"start": 0.0, "end": 1.0, "text": "そうです"},
            {"start": 1.0, "end": 2.0, "text": "書字の"},
            {"start": 2.0, "end": 3.0, "text": "よろしくお願いします"}]
    heard = toks("そうです", 1.0) + toks("周辞の", 4.0) + toks("よろしくお願いします", 8.0)
    terms = (("周知", "書字"), ("周辞", "書字"))
    for order in (terms, terms[::-1]):
        cs = [dict(c) for c in caps]
        aligner.align_captions(cs, heard)
        assert not cs[1].get("_asr")
        assert aligner.align_heard_forms(cs, heard, terms=order) == 1
        assert cs[1]["start"] == pytest.approx(4.0, abs=0.05)


def test_an_unheard_caption_is_not_spread_over_a_scene_where_nobody_speaks():
    # 40回目の 29分38秒〜30分32秒（先生が字を書く場面・54秒）: 合わなかった「はい」（2字）を前後の合った
    # 字幕の間に文字数で配ったら、場面全体の 52 秒に出た。推定の時刻の所に、ゆっくり話す長さで置く
    caps = [{"start": 0.0, "end": 2.0, "text": "今から書いていただきます", "_asr": True},
            {"start": 26.0, "end": 31.0, "text": "はい"},
            {"start": 54.0, "end": 57.0, "text": "素敵な字を書いていただいたので", "_asr": True}]
    aligner.interpolate_unaligned(caps)
    assert caps[1]["start"] == pytest.approx(26.0)
    assert caps[1]["end"] == pytest.approx(26.0 + 2 / aligner.SLOW_CPS, abs=1e-3)


def test_a_pause_in_the_talk_still_gets_the_caption_spread_over_it():
    # 6分36秒の形: 12字に 7.4 秒。ゆっくり話せば埋まる（言いよどみ・間）ので、今までどおり間に配る
    caps = [{"start": 0.0, "end": 2.0, "text": "前の話です", "_asr": True},
            {"start": 2.5, "end": 4.0, "text": "私　拝見したことがあります"},
            {"start": 9.4, "end": 11.0, "text": "次の話です", "_asr": True}]
    aligner.interpolate_unaligned(caps)
    assert (caps[1]["start"], caps[1]["end"]) == (2.0, 9.4)


def test_an_unheard_caption_estimated_past_the_scene_stays_before_the_next_anchor():
    caps = [{"start": 0.0, "end": 2.0, "text": "今から書いていただきます", "_asr": True},
            {"start": 60.0, "end": 61.0, "text": "はい"},
            {"start": 54.0, "end": 57.0, "text": "素敵な字を書いていただいたので", "_asr": True}]
    aligner.interpolate_unaligned(caps)
    assert caps[1]["end"] == pytest.approx(54.0)
    assert caps[1]["start"] == pytest.approx(54.0 - 2 / aligner.SLOW_CPS, abs=1e-3)
