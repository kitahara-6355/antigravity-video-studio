"""文字起こしを2回して、食い違いを手元の音声認識で決める（2026-10-06）。

起こしの区切りを変えて起こし直すと、Gemini の聞き違いが毎回別の所に出た
（26回目の冒頭で「書家の北原」が「諸岡の北原」、「書に出会った」が「よそに出会った」）。
温度 0 でも区切りが変われば渡す音声が変わる。どちらの回の字が正しいかは運だった。

守りたい性質:

1. 2回目と手元の音声認識が同じ字を聞き、1回目だけが違う所は 2回目の字にする（2対1）。
   1回目が丸ごと落とした文は、文の時刻のそばで認識に聞こえれば、前後の字が聞こえなくても足す
   （言いよどみ・相づちだけの文、4字未満の文、1回目の字と合う認識の字は数えない）
2. 認識が1回目と同じ・どちらとも違う所は 1回目のまま
3. 行の分け方と時刻は 1回目のまま（字だけ直す）。1回目の行の切れ目に文を足すときだけ、2回目の時刻で行を足す
4. 1回目の字を2字以上消すのは、2回目にも無く、認識が前後の字を言う間もなく続けて聞いた所だけ（3字まで）。
   言いよどみと数字は触らない（認識が落としやすい所）
5. 2回目は区切りの位置をずらして起こす（1回目の区切りの前後が2回目では区切りの中ほどになる）。
   2回目の区切りは1回目の区切りから離す（静かな所に引き寄せられて同じ所に戻らない）。
   区切り方を変えても、頭と長さが変わらないチャンクは前の起こしから写す
6. 認識が使えない・2回目が落ちたら 1回目のまま進む
7. 2回でも決めきれない所（2回とも落とした・認識が片側でしか確かめられない）だけ、そこが真ん中に来る
   区間をもう1回起こし、3回目が認識に沿う字を書いたときだけ直す（2026-10-14・3分03秒
   「普通だったら」→「普通泣いて帰ったら」）。3回目が決めない所は区間を広げて読み直す（3回まで）。
   区間ごとの控えがキャッシュ。落ちたらそれまでに決まった所だけ直して進む
8. 2回目の起こしが別の字を書き、認識も決め手にならない所（割れた所）は、校閲の後の文で選ばせる候補にする。
   認識が本文の字を聞いた・本文の側に寄る所、書き分け・助詞・数字・辞書の語は候補にしない
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from subtitle_engine import transcript_fusion as tfu


def _heard(text: str, start: float = 0.0, step: float = 0.12) -> list[tuple[str, float]]:
    """手元の音声認識の結果の形（1字ずつ・時刻つき）。"""
    return [(ch, round(start + i * step, 3)) for i, ch in enumerate(text)]


def _row(start, end, text):
    return {"start": start, "end": end, "text": text, "sourceStart": start, "sourceEnd": end, "words": []}


# ------------------------------------------------------------
# 1〜4. 食い違いの決め方
# ------------------------------------------------------------

def test_a_word_the_second_pass_and_the_recogniser_both_heard_replaces_the_first():
    first = [_row(0.4, 3.0, "こんにちは、諸岡の北原美麗です。")]
    second = [_row(0.4, 3.0, "こんにちは、書家の北原美鈴です。")]

    out, stats = tfu.fuse(first, second, _heard("こんにちは書家の北原美玲です"))

    # 「書家」は2対1。「美麗／美鈴／美玲」はどれも違うので 1回目のまま
    assert out[0]["text"] == "こんにちは、書家の北原美麗です。"
    assert stats["adopted"] == 1
    assert stats["examples"][0]["before"] == "諸岡" and stats["examples"][0]["after"] == "書家"


def test_the_first_pass_stays_where_the_recogniser_agrees_with_it():
    first = [_row(0.0, 3.0, "最初に書に出会ったきっかけは何ですか。")]
    second = [_row(0.0, 3.0, "最初によそに出会ったきっかけは何ですか。")]

    out, stats = tfu.fuse(first, second, _heard("最初に書に出会ったきっかけは何ですか"))

    assert out[0]["text"] == first[0]["text"]
    assert stats["adopted"] == 0


def test_nothing_changes_where_the_recogniser_heard_neither():
    first = [_row(0.0, 3.0, "母親に、僕も習字入れ入って言って。")]
    second = [_row(0.0, 3.0, "母親に僕も囚入れてって言って。")]

    out, _ = tfu.fuse(first, second, _heard("母親に僕の習字入れで言って"))

    assert out[0]["text"] == first[0]["text"]


def test_rows_and_times_come_from_the_first_pass():
    first = [_row(10.0, 12.5, "へえ、そういう出会いな。"),
             _row(12.6, 16.0, "しかも、幼馴染の加藤君がそこにいたんでしょ。")]
    second = [_row(9.0, 16.5, "へえ、そういう出会いなんですね。しかも、幼馴染の加藤君がそこにいたんですよ。")]
    heard = _heard("へえそういう出会いなんですねしかも幼馴染の加藤君がそこにいたんですよ", start=10.0)

    out, stats = tfu.fuse(first, second, heard)

    assert [s["text"] for s in out] == ["へえ、そういう出会いなんですね。",
                                       "しかも、幼馴染の加藤君がそこにいたんですよ。"]
    assert [(s["start"], s["end"]) for s in out] == [(10.0, 12.5), (12.6, 16.0)]
    assert stats["adopted"] == 2


def test_only_the_head_of_an_addition_that_the_recogniser_also_heard_is_taken():
    # 実例（1分39秒・28回目）: 1回目は「出会いな」で切れ、2回目は「出会いなんですて」、
    # 認識は「出会いなんですね」。「んです」までは2回目と認識が同じ字を聞いている（2対1）
    first = [_row(10.0, 12.5, "へえ、そういう出会いな。")]
    second = [_row(10.0, 12.5, "へえ、そういう出会いなんですて。")]

    out, stats = tfu.fuse(first, second, _heard("へえそういう出会いなんですねしかも僕が", start=10.0))

    assert out[0]["text"] == "へえ、そういう出会いなんです。"
    assert stats["adopted"] == 1


def test_the_head_of_an_addition_is_not_taken_where_the_first_pass_was_heard():
    first = [_row(10.0, 12.5, "へえ、そういう出会いな。しかも")]
    second = [_row(10.0, 12.5, "へえ、そういう出会いなんですて。しかも")]

    out, _ = tfu.fuse(first, second, _heard("へえそういう出会いなしかもなんですね", start=10.0))

    assert out[0]["text"] == first[0]["text"]


# 実例（素材の 37分36秒・57回目）: 1回目は「…私も。」の次が段取りの「ちょっと切ります。」で、間の
# 「分かりました。」が無い。2回目と前の区切り方の2回目は書いた。認識は「あやかりたいと思います私も」を
# 聞かず（前の字と続けて探せない）、「分かりました」の頭の「分か」は声の区間の頭（2秒前）にこぼれた
WAKARI_FIRST = [_row(2247.4, 2257.4, "はあ、素晴らしいと思います。あの、あやかりたいと思います。私も。"),
                _row(2258.0, 2259.2, "ちょっと切ります。")]
WAKARI_SECOND = [_row(2251.6, 2256.1, "はあ、素晴らしいと思います。あの、あやかりたいと思います、私も。"),
                 _row(2256.1, 2257.6, "分かりました。"),
                 _row(2258.1, 2259.1, "ちょっと切ります。")]


def _wakari_heard(tail="りました"):
    return (_heard("すばらしいと思います", start=2251.4, step=0.15) + [("分", 2253.5), ("か", 2253.6)]
            + _heard(tail, start=2256.6, step=0.3) + _heard("切ります", start=2258.5, step=0.2))


def test_a_whole_sentence_only_the_first_pass_left_out_is_added_as_its_own_row():
    out, stats = tfu.fuse(WAKARI_FIRST, WAKARI_SECOND, _wakari_heard())

    assert [s["text"] for s in out] == [WAKARI_FIRST[0]["text"], "分かりました。", "ちょっと切ります。"]
    # 足した行の時刻は2回目の行から。ほかの行は1回目のまま
    assert [(s["start"], s["end"]) for s in out] == [(2247.4, 2257.4), (2256.1, 2257.6), (2258.0, 2259.2)]
    assert out[1]["sourceStart"] == 2256.1 and out[1]["words"] == []
    assert stats["adopted"] == 1 and stats["sentences"] == 1
    assert stats["examples"] == [{"start": 2256.1, "before": "", "after": "分かりました。"}]


def test_a_sentence_the_recogniser_heard_only_far_from_where_it_was_said_is_not_added():
    """頭の「分か」は2秒前にこぼれた字。文の時刻のそばで聞こえた字だけを数える。"""
    out, stats = tfu.fuse(WAKARI_FIRST, WAKARI_SECOND, _wakari_heard(tail="た"))

    assert [s["text"] for s in out] == [s["text"] for s in WAKARI_FIRST]
    assert stats["sentences"] == 0


def test_a_sentence_the_second_pass_wrote_twice_is_not_added_again():
    """区切りの境目で2回目が同じ文を繰り返しても、認識の字は1回目の文と合っている（1回目の声）。"""
    first = [_row(0.0, 4.0, "もう、終わりです。あ、もう、残念。")]
    second = [_row(0.0, 2.0, "もう終わりです。"), _row(2.0, 4.0, "もう終わりです。あ、もう、残念。")]

    out, stats = tfu.fuse(first, second, _heard("もう終わりですあもう残念", step=0.3))

    assert [s["text"] for s in out] == [first[0]["text"]] and stats["sentences"] == 0


def test_a_sentence_left_out_inside_a_row_goes_in_after_the_sentence_before_it():
    """足す所が1回目の行の中なら、その行の文の切れ目に句点ごと入れる（行と時刻はそのまま）。"""
    first = [_row(0.0, 6.0, "料理ですかね。素晴らしいと思います。")]
    second = [_row(0.0, 2.5, "料理ですかね。分かりました。"), _row(2.5, 6.0, "素晴らしいと思います。")]
    heard = _heard("料理です", step=0.2) + _heard("分かりました", start=1.6) + _heard("素晴らしいと思います", start=2.6)

    out, stats = tfu.fuse(first, second, heard)

    assert [(s["text"], s["start"], s["end"]) for s in out] == [
        ("料理ですかね。分かりました。素晴らしいと思います。", 0.0, 6.0)]
    assert stats["sentences"] == 1


@pytest.mark.parametrize("extra", ["うん、はい。", "そう。"])
def test_fillers_and_very_short_sentences_are_not_added(extra):
    first = [_row(0.0, 6.0, "料理ですかね。素晴らしいと思います。")]
    second = [_row(0.0, 2.5, f"料理ですかね。{extra}"), _row(2.5, 6.0, "素晴らしいと思います。")]
    said = extra.replace("、", "").replace("。", "")
    heard = _heard("料理です", step=0.2) + _heard(said, start=1.6) + _heard("素晴らしいと思います", start=2.6)

    out, stats = tfu.fuse(first, second, heard)

    assert out[0]["text"] == first[0]["text"] and stats["sentences"] == 0


def test_more_than_three_characters_of_the_first_pass_are_never_dropped():
    # 認識は早口や言い直しを落とす。認識に無いことだけでは 1回目の字を消さない
    first = [_row(0.0, 3.0, "それがね、それがね八歳のときです。")]
    second = [_row(0.0, 3.0, "それがね八歳のときです。")]

    out, _ = tfu.fuse(first, second, _heard("それがね八歳のときです"))

    assert out[0]["text"] == first[0]["text"]


def test_a_single_extra_character_heard_by_no_one_else_is_dropped():
    first = [_row(0.0, 3.0, "書を通してお人々の心に触れ。")]
    second = [_row(0.0, 3.0, "書を通して人々の心に触れ。")]

    out, _ = tfu.fuse(first, second, _heard("書を通して人々の心に触れ"))

    assert out[0]["text"] == "書を通して人々の心に触れ。"


def test_a_filler_next_to_the_difference_is_not_looked_for_in_the_recogniser():
    """42分05秒（43回目）: 1回目「機械をねあの、足てはいけない」・2回目「絶やして」・認識「機会をね絶やして」。

    認識は言いよどみを書かないので、前の字「の」（「あの」）を付けて探すと、2回目の字も聞こえない。
    """
    first = [_row(0.0, 6.0, "筆で文字を書くという機械をねあの、足てはいけないかなと。")]
    second = [_row(0.0, 6.0, "筆で文字を書くという機械をねあの、絶やしてはいけないかなと。")]

    out, stats = tfu.fuse(first, second, _heard("筆で文字を書くという機会をね絶やしてはいけないかなと"))

    assert out[0]["text"] == "筆で文字を書くという機械をねあの、絶やしてはいけないかなと。"
    assert stats["adopted"] == 1


@pytest.mark.parametrize("first_text, second_text, heard", [
    # 句読点で隔てていない言いよどみは外さない（1分27秒: 「が」は認識にも2回目にも無いが、消さない）
    ("その当時僕があの駄菓子屋によく行ってましたね。", "その当時僕あの駄菓子屋によく行ってましたね。",
     "その当時僕駄菓子屋によく行ってましたね"),
    # 1字の言いよどみは語の尻と見分けられない（5分44秒「そう。」の「う」）
    ("しーちきんだった。そう。しーちきんの雑誌広告で", "しーちきんだった。うん。しーちきんの雑誌広告で",
     "しーちきんだったしーちきんの雑誌広告で"),
])
def test_only_a_whole_filler_set_off_by_punctuation_is_left_out_of_the_context(first_text, second_text, heard):
    out, _ = tfu.fuse([_row(0.0, 6.0, first_text)], [_row(0.0, 6.0, second_text)], _heard(heard))

    assert out[0]["text"] == first_text


def _heard_with_pause(before: str, after: str, pause: float, start: float = 0.0,
                      step: float = 0.12) -> list[tuple[str, float]]:
    """before と after の間で pause 秒あけて聞いた認識（字の間は step 秒）。"""
    head = _heard(before, start, step)
    return head + _heard(after, head[-1][1] + pause, step)


def test_two_or_three_characters_the_recogniser_had_no_time_for_are_dropped():
    # 実例（2分49秒・35回目）: 1回目だけが「そう」を挟み、2回目と認識は「しようという」。
    # 認識は「と」と「い」を 0.2 秒で続けて聞いていて、「そう」を言う間は無かった
    first = [_row(0.0, 3.0, "あの克服しようとそういう感じですか？")]
    second = [_row(0.0, 3.0, "あの、克服しようという感じですか？")]

    out, stats = tfu.fuse(first, second, _heard("克服しようという感じで"))

    assert out[0]["text"] == "あの克服しようという感じですか？"
    assert stats["adopted"] == 1


def test_characters_are_kept_where_the_recogniser_left_time_to_say_them():
    # 前後の字の間が「そう」を言えるほどあいていれば、認識が落としただけかもしれない
    first = [_row(0.0, 3.0, "あの克服しようとそういう感じですか？")]
    second = [_row(0.0, 3.0, "あの、克服しようという感じですか？")]

    out, _ = tfu.fuse(first, second, _heard_with_pause("克服しようと", "いう感じで", pause=0.5))

    assert out[0]["text"] == first[0]["text"]


@pytest.mark.parametrize("first_text,second_text,heard", [
    ("それで、あの、ここで書きました。", "それで、ここで書きました。", "それでここで書きました"),
    ("生徒さんは百二十人です。", "生徒さんは百人です。", "生徒さんは百人です"),
])
def test_dropping_two_characters_leaves_fillers_and_numbers_alone(first_text, second_text, heard):
    out, _ = tfu.fuse([_row(0.0, 3.0, first_text)], [_row(0.0, 3.0, second_text)], _heard(heard))

    assert out[0]["text"] == first_text


def test_a_difference_that_runs_into_a_row_of_only_a_filler_is_still_decided():
    # 実例（2分46秒・35回目）: 1回目は「…ないよね。」の次の行が相づちの「ううん。」だけ。2回目と
    # 認識は「ないので」。食い違いが「よね＋ううん」と「ので」の1つにまとまり、1回目の行を
    # またぐので決めていなかった。言いよどみ（後で外す）だけの行の分は、食い違いに数えない
    first = [_row(172.1, 177.2, "行かなくなったってことはないよね。"),
             _row(177.2, 180.5, "ううん。あの克服しようという感じですか？")]
    second = [_row(172.9, 180.7, "行かなくなったってことはないので。あの、克服しようという感じですか？")]
    heard = _heard("行かなくなったってことはないので克服しようという感じで", start=172.5)

    out, stats = tfu.fuse(first, second, heard)

    assert [s["text"] for s in out] == ["行かなくなったってことはないので。",
                                       "ううん。あの克服しようという感じですか？"]
    assert stats["adopted"] == 1


def test_a_difference_across_rows_with_words_on_both_sides_is_left_alone():
    # 両方の行に言いよどみでない字があれば、どちらの行の字に当てるか決められない
    first = [_row(0.0, 2.0, "行かなくなったってことはないよね。"),
             _row(2.0, 4.0, "それで克服しようという感じですか？")]
    second = [_row(0.0, 4.0, "行かなくなったってことはないので克服しようという感じですか？")]
    heard = _heard("行かなくなったってことはないので克服しようという感じで")

    out, _ = tfu.fuse(first, second, heard)

    assert [s["text"] for s in out] == [s["text"] for s in first]


# 実例（10分16秒・45回目の前）: 1回目の区切り（624.54秒）で「電通」が割れ、「当時でん」「チーフの人たち」の
# 2行になった。2回目（区切りを1回目から5秒以上離した）と認識は「当時電通の人たち」と丸ごと聞いた
SPLIT_FIRST = [_row(617.4, 624.5, "そのスタジオの中には、当時でん"),
               _row(624.5, 635.0, "チーフの人たちとか、ショップの幹部とか。")]
SPLIT_SECOND = [_row(618.1, 634.4, "そのスタジオの中には当時電通の人たちとか、ショップの幹部とか。")]
SPLIT_HEARD = "そのスタジオの中には当時電通の人たちとかショップの幹部とか"


def test_a_word_split_at_a_chunk_cut_takes_what_the_second_pass_heard_whole():
    """区切りで割れた語は、隣り合う2行のうち割れた字の多い方の行に、2回目と認識の字を置く。"""
    out, stats = tfu.fuse(SPLIT_FIRST, SPLIT_SECOND, _heard(SPLIT_HEARD, start=620.0), cuts=[624.54])

    assert [s["text"] for s in out] == ["そのスタジオの中には、当時", "電通の人たちとか、ショップの幹部とか。"]
    assert [(s["start"], s["end"]) for s in out] == [(617.4, 624.5), (624.5, 635.0)]
    assert stats["adopted"] == 1
    assert stats["examples"][0]["before"] == "でんチーフ" and stats["examples"][0]["after"] == "電通"


def test_a_word_across_rows_that_do_not_meet_at_a_chunk_cut_is_left_alone():
    """区切りでない行の切れ目は、話者や文の切れ目。どちらの行の字か決められない。"""
    out, _ = tfu.fuse(SPLIT_FIRST, SPLIT_SECOND, _heard(SPLIT_HEARD, start=620.0), cuts=[600.0])

    assert [s["text"] for s in out] == [s["text"] for s in SPLIT_FIRST]


def test_a_word_split_at_a_cut_goes_to_the_row_that_would_otherwise_be_left_empty():
    first = [_row(622.0, 624.5, "でん"), _row(624.5, 635.0, "チーフの人たちとか、ショップの幹部とか。")]
    second = [_row(622.0, 634.4, "電通の人たちとか、ショップの幹部とか。")]

    out, _ = tfu.fuse(first, second, _heard("当時電通の人たちとかショップの幹部とか", start=622.0),
                      cuts=[624.54])

    assert [s["text"] for s in out] == ["電通", "の人たちとか、ショップの幹部とか。"]


def test_kanji_are_counted_as_two_sounds_when_checking_for_dropped_characters():
    """「でんちーふ→電通」は字数で3字減るが、漢字を2音に数えれば1字。漢字を2音に数えても2字以上
    減る所は、これまでどおり決めない（認識は早口や言い直しを落とす）。"""
    first = [_row(0.0, 3.0, "それはいいんじゃないですかね。")]
    second = [_row(0.0, 3.0, "それは良いですかね。")]

    out, _ = tfu.fuse(first, second, _heard("それは良いですかね"))

    assert out[0]["text"] == first[0]["text"]


@pytest.mark.parametrize("first_text,second_text,heard", [
    ("あの、ここで書きました。", "えっと、ここで書きました。", "えっとここで書きました"),
    ("生徒さんは百人くらいです。", "生徒さんは十人くらいです。", "生徒さんは十人くらいです"),
])
def test_fillers_and_numbers_are_left_alone(first_text, second_text, heard):
    out, _ = tfu.fuse([_row(0.0, 3.0, first_text)], [_row(0.0, 3.0, second_text)], _heard(heard))

    assert out[0]["text"] == first_text


def test_without_the_recogniser_the_first_pass_is_returned():
    first = [_row(0.0, 3.0, "こんにちは、諸岡の北原美麗です。")]

    out, stats = tfu.fuse(first, [_row(0.0, 3.0, "こんにちは、書家の北原美麗です。")], None)

    assert out == first and stats["adopted"] == 0


def test_the_rows_passed_in_are_not_changed():
    first = [_row(0.4, 3.0, "こんにちは、諸岡の北原美麗です。")]

    tfu.fuse(first, [_row(0.4, 3.0, "こんにちは、書家の北原美麗です。")], _heard("こんにちは書家の北原美麗です"))

    assert first[0]["text"] == "こんにちは、諸岡の北原美麗です。"


# ------------------------------------------------------------
# 5. 2回目は区切りをずらす
# ------------------------------------------------------------

def test_the_second_pass_cuts_halfway_between_the_first_pass_cuts():
    from subtitle_engine import gemini_transcriber as gt

    first = [o for o, _ in gt.plan_chunks(100.0, 30)][1:]
    second = [o for o, _ in gt.plan_chunks(100.0, 30, first=15)][1:]

    assert first == [30.0, 60.0, 90.0]
    assert second == [15.0, 45.0, 75.0]


def test_transcribe_passes_the_shifted_first_cut_to_the_plan(tmp_path, monkeypatch):
    from subtitle_engine import gemini_transcriber as gt

    seen = {}
    monkeypatch.setattr(gt.QuietMap, "from_media", classmethod(lambda cls, media: None))
    monkeypatch.setattr(gt, "_probe_duration", lambda path: 70.0)

    def fake_split(video, work, plan=None, **kw):
        seen["plan"] = plan
        return [(Path(work) / f"c{i}.mp3", o, d) for i, (o, d) in enumerate(plan)]
    monkeypatch.setattr(gt, "split_audio", fake_split)
    monkeypatch.setattr(gt, "_speech_or_none", lambda path: None)

    def call(client, model, path, dur):
        return json.dumps([{"start": 0.0, "end": min(2.0, dur), "text": "あいうえお"}]), "m"

    tx = gt.transcribe(tmp_path / "v.mp4", client=object(), model="m", call=call, first_chunk_sec=15)

    assert [o for o, _ in seen["plan"]] == [0.0, 15.0, 45.0]
    assert tx.cuts == [15.0, 45.0]


def _loud_but_at(total, pauses, frame=0.02):
    """pauses の秒の前後 0.2 秒だけ静かな、音の大きさの並び（フレームごと）。"""
    e = [1.0] * int(round(total / frame))
    for t in pauses:
        for i in range(int(round((t - 0.2) / frame)), int(round((t + 0.2) / frame))):
            e[i] = 0.001
    return e


def test_the_second_pass_keeps_its_cuts_away_from_the_first_pass_cuts():
    """一番静かな所を選ぶだけだと、2回目の区切りが静かな間に引き寄せられて1回目と同じ所に戻る
    （2026-10-14: 43 分の素材で 9 分以降は 103 か所中 83 か所が同じ所。10分16秒の「電通」を
    2回とも同じ所で割り、2回とも「チーフ」と聞き違えた）。"""
    from subtitle_engine import gemini_transcriber as gt
    quiet = gt.QuietMap(_loud_but_at(120, [25, 50, 75, 100]))
    first = [o for o, _ in gt.plan_chunks(120, 30, quiet)][1:]

    drifted = [o for o, _ in gt.plan_chunks(120, 30, quiet, first=15)][1:]
    second = gt.plan_chunks(120, 30, quiet, first=15, avoid=first)

    assert [round(c) for c in first] == [25, 50, 75, 100]
    assert {75, 100} <= {round(c) for c in drifted}, "離さないと 75 秒から先は同じ所で切る"
    cuts = [o for o, _ in second][1:]
    assert all(abs(c - f) >= gt.SECOND_PASS_GAP_SEC - 1e-6 for c in cuts for f in first)
    # チャンクの長さの決まり（2/3〜1 倍）は守る。隙間も重なりもなく終わりまで続く
    assert all(20 - 1e-6 <= d <= 30 + 1e-6 for _, d in second[1:-1])
    assert all(abs(o + d - n) < 1e-6 for (o, d), (n, _) in zip(second, second[1:]))
    assert abs(second[-1][0] + second[-1][1] - 120) < 1e-6


def test_a_cut_that_cannot_keep_away_is_still_made_at_the_quietest_point():
    """離せる所が無ければ離さない（チャンクの長さの決まりが先）。"""
    from subtitle_engine import gemini_transcriber as gt
    quiet = gt.QuietMap(_loud_but_at(60, [25]))

    assert abs(quiet.quietest(20, 30, target=30, avoid=[25.0], gap=6.0) - 25) < 0.1


def test_transcribe_keeps_the_cuts_away_from_the_cuts_it_is_given(tmp_path, monkeypatch):
    from subtitle_engine import gemini_transcriber as gt

    seen = []
    monkeypatch.setattr(gt.QuietMap, "from_media",
                        classmethod(lambda cls, media: gt.QuietMap(_loud_but_at(120, [25, 50, 75, 100]))))
    monkeypatch.setattr(gt, "_probe_duration", lambda path: 120.0)
    monkeypatch.setattr(gt, "split_audio", _fake_split(seen))
    monkeypatch.setattr(gt, "_speech_or_none", lambda path: None)

    def call(client, model, path, dur):
        return json.dumps([{"start": 0.0, "end": min(2.0, dur), "text": f"起こし{path.stem}"}]), "m"

    tx = gt.transcribe(tmp_path / "v.mp4", client=object(), model="m", call=call, first_chunk_sec=15,
                       avoid_cuts=[25.0, 50.0, 75.0, 100.0])

    assert len(tx.cuts) >= 3
    assert all(abs(c - f) >= gt.SECOND_PASS_GAP_SEC - 1e-6 for c in tx.cuts for f in (25, 50, 75, 100))


def test_chunks_whose_cut_did_not_change_are_taken_from_the_earlier_cutting(tmp_path, monkeypatch):
    """区切り方を変えても、頭と長さが変わらないチャンクは呼び直さない（確かめ済みの所の字が変わらない）。"""
    from subtitle_engine import gemini_transcriber as gt

    seen = []
    monkeypatch.setattr(gt.QuietMap, "from_media", classmethod(lambda cls, media: None))
    monkeypatch.setattr(gt, "_probe_duration", lambda path: 70.0)
    monkeypatch.setattr(gt, "split_audio", _fake_split(seen))
    monkeypatch.setattr(gt, "_speech_or_none", lambda path: None)
    earlier = tmp_path / "_gemini_earlier.jsonl"
    # 前の区切りは 15・40 秒、今の区切りは 15・45 秒。同じなのは頭の (0, 15) だけ
    gt.write_checkpoint([_row(1.0, 3.0, "前の起こし一本目"), _row(16.0, 18.0, "前の起こし二本目"),
                         _row(41.0, 43.0, "前の起こし三本目")],
                        earlier, meta={"cuts": [15.0, 40.0], "models_used": ["old-model"]})
    called = []

    def call(client, model, path, dur):
        called.append(path.stem)
        return json.dumps([{"start": 0.0, "end": min(2.0, dur), "text": f"起こし{path.stem}"}]), "m"

    tx = gt.transcribe(tmp_path / "v.mp4", client=object(), model="m", call=call, first_chunk_sec=15,
                       earlier=[earlier])

    assert sorted(called) == ["c1", "c2"]  # チャンクは並列に起こすので、呼ぶ順は決まらない
    assert [s["text"] for s in tx.segments] == ["前の起こし一本目", "起こしc1", "起こしc2"]
    assert tx.carried == 1
    assert tx.models_used == ["m", "old-model"]


def test_an_earlier_transcription_without_its_cuts_is_not_taken(tmp_path, monkeypatch):
    """区切りを記録していないキャッシュは、どこがどのチャンクか分からないので写さない。"""
    from subtitle_engine import gemini_transcriber as gt

    monkeypatch.setattr(gt.QuietMap, "from_media", classmethod(lambda cls, media: None))
    monkeypatch.setattr(gt, "_probe_duration", lambda path: 40.0)
    monkeypatch.setattr(gt, "split_audio", _fake_split([]))
    monkeypatch.setattr(gt, "_speech_or_none", lambda path: None)
    earlier = tmp_path / "_gemini_earlier.jsonl"
    gt.write_checkpoint([_row(1.0, 3.0, "前の起こし")], earlier)
    called = []

    def call(client, model, path, dur):
        called.append(path.stem)
        return json.dumps([{"start": 0.0, "end": min(2.0, dur), "text": f"起こし{path.stem}"}]), "m"

    tx = gt.transcribe(tmp_path / "v.mp4", client=object(), model="m", call=call, first_chunk_sec=15,
                       earlier=[earlier])

    assert sorted(called) == ["c0", "c1"] and tx.carried == 0


# ------------------------------------------------------------
# 6. 文字起こしの工程（2回目はキャッシュし、落ちたら 1回目のまま）
# ------------------------------------------------------------

def _video(tmp_path):
    v = tmp_path / "v.mp4"
    v.write_bytes(b"\x00" * 2048)
    return v


def _pass(text):
    return [_row(0.4, 3.0, text)]


def _setup_two_passes(tmp_path, monkeypatch, second_fails=False):
    from subtitle_engine import aligner, gemini_transcriber as gt

    monkeypatch.setenv("AVS_TRANSCRIBE_ENGINE", "gemini")
    calls = []

    def fake_transcribe(path, **kw):
        calls.append(kw.get("first_chunk_sec"))
        if kw.get("first_chunk_sec"):
            if second_fails:
                raise gt.TranscriptionError("チャンク 3/9 を起こせません")
            segs = _pass("こんにちは、書家の北原美麗です。" + "あ" * 300)
        else:
            segs = _pass("こんにちは、諸岡の北原美麗です。" + "あ" * 300)
        return gt.TranscribeResult(segments=segs, model="m", chunks=1, models_used=["m"],
                                   cuts=[15.0] if kw.get("first_chunk_sec") else [30.0])
    monkeypatch.setattr(gt, "transcribe", fake_transcribe)
    monkeypatch.setattr(aligner, "tokens_for", lambda media: _heard("こんにちは書家の北原美麗です" + "あ" * 300, 0.4, 0.008))
    return calls


def test_the_stage_fuses_a_second_pass_with_shifted_cuts(tmp_path, monkeypatch):
    from agents.pipeline_types import PipelineContext
    from agents.workers.transcribe_worker import TranscribeWorker

    calls = _setup_two_passes(tmp_path, monkeypatch)
    ctx = PipelineContext(video_path=str(_video(tmp_path)))

    result = asyncio.run(TranscribeWorker().execute(ctx))

    assert result.success
    assert calls == [None, 15, 15]  # 2回目は区切りを半分ずらす（前の区切り方の2回目も起こす）
    assert ctx.segments[0]["text"].startswith("こんにちは、書家の北原美麗です。")
    assert result.data["second_pass"]["adopted"] == 1
    assert len(list(tmp_path.glob("_gemini_*.jsonl"))) == 3, "1回目・前の区切り方の2回目・いまの2回目を別々にキャッシュする"


def test_the_second_pass_is_read_from_its_cache(tmp_path, monkeypatch):
    from agents.pipeline_types import PipelineContext
    from agents.workers.transcribe_worker import TranscribeWorker

    calls = _setup_two_passes(tmp_path, monkeypatch)
    asyncio.run(TranscribeWorker().execute(PipelineContext(video_path=str(_video(tmp_path)))))
    ctx = PipelineContext(video_path=str(tmp_path / "v.mp4"))

    asyncio.run(TranscribeWorker().execute(ctx))

    assert calls == [None, 15, 15]  # 2回目の実行では起こさない
    assert ctx.segments[0]["text"].startswith("こんにちは、書家の北原美麗です。")


def test_the_second_pass_is_told_where_the_first_pass_cut(tmp_path, monkeypatch):
    """1回目の区切りを2回目に渡す（そこから離して切る）。1回目をキャッシュから読むときは付帯情報の区切り。"""
    from agents.pipeline_types import PipelineContext
    from agents.workers.transcribe_worker import TranscribeWorker
    from subtitle_engine import gemini_transcriber as gt

    _setup_two_passes(tmp_path, monkeypatch)
    fake = gt.transcribe
    avoid = []

    def noting(path, **kw):
        avoid.append(list(kw.get("avoid_cuts") or []))
        return fake(path, **kw)
    monkeypatch.setattr(gt, "transcribe", noting)

    result = asyncio.run(TranscribeWorker().execute(PipelineContext(video_path=str(_video(tmp_path)))))
    for p in tmp_path.glob(f"_gemini_*{gt.CUT_TAG}{gt.SECOND_PASS_TAG}_*"):
        p.unlink()
    asyncio.run(TranscribeWorker().execute(PipelineContext(video_path=str(_video(tmp_path)))))

    assert avoid == [[], [], [30.0], [30.0]]  # 前の区切り方の2回目は1回目の区切りを避けない
    assert result.data["second_pass"]["models"] == ["m"], "2回目のモデルも実行記録に残す"


def test_a_second_pass_cut_the_earlier_way_is_made_again_from_its_unchanged_chunks(tmp_path, monkeypatch):
    """2回目の区切り方を変えたら起こし直す。前の区切り方の2回目は、区切りが同じチャンクを写す元にする。"""
    from agents.pipeline_types import PipelineContext
    from agents.workers.transcribe_worker import TranscribeWorker
    from subtitle_engine import gemini_transcriber as gt

    calls = _setup_two_passes(tmp_path, monkeypatch)
    asyncio.run(TranscribeWorker().execute(PipelineContext(video_path=str(_video(tmp_path)))))
    now = gt.CUT_TAG + gt.SECOND_PASS_TAG + "_"
    before = gt.CUT_TAG + gt.SECOND_PASS_EARLIER_TAGS[-1] + "_"
    for p in tmp_path.glob(f"_gemini_*{now}*"):
        p.rename(p.with_name(p.name.replace(now, before)))
    fake = gt.transcribe
    earlier = []

    def noting(path, **kw):
        earlier.append([Path(e).name for e in kw.get("earlier") or []])
        return fake(path, **kw)
    monkeypatch.setattr(gt, "transcribe", noting)

    asyncio.run(TranscribeWorker().execute(PipelineContext(video_path=str(_video(tmp_path)))))

    assert calls == [None, 15, 15, 15], "前の区切り方の2回目をそのままは使わない"
    assert len(earlier) == 1 and earlier[0] and all(before in name for name in earlier[0])


def test_a_second_pass_cut_the_earlier_way_is_also_heard_as_one_more_reading(tmp_path, monkeypatch):
    """前の区切り方の2回目も、いまの2回目と突き合わせた後にもう1つの聞き取りとして突き合わせる。"""
    from agents.pipeline_types import PipelineContext
    from agents.workers.transcribe_worker import TranscribeWorker
    from subtitle_engine import gemini_transcriber as gt

    _setup_two_passes(tmp_path, monkeypatch)
    asyncio.run(TranscribeWorker().execute(PipelineContext(video_path=str(_video(tmp_path)))))
    now = gt.CUT_TAG + gt.SECOND_PASS_TAG + "_"
    before = gt.CUT_TAG + gt.SECOND_PASS_EARLIER_TAGS[-1] + "_"
    for p in tmp_path.glob(f"_gemini_*{now}*"):
        p.rename(p.with_name(p.name.replace(now, before)))
    fake = gt.transcribe

    def mishearing(path, **kw):  # いまの区切り方の2回目は別の所で聞き違える
        tx = fake(path, **kw)
        if kw.get("first_chunk_sec"):
            tx.segments = _pass("こんにちは、初夏の北原美麗です。" + "あ" * 300)
        return tx
    monkeypatch.setattr(gt, "transcribe", mishearing)
    ctx = PipelineContext(video_path=str(_video(tmp_path)))

    result = asyncio.run(TranscribeWorker().execute(ctx))

    assert ctx.segments[0]["text"].startswith("こんにちは、書家の北原美麗です。")
    assert result.data["second_pass"]["adopted"] == 0
    assert [(e["tag"], e["adopted"]) for e in result.data["second_pass"]["earlier"]] == [
        (gt.SECOND_PASS_EARLIER_TAGS[-1], 1)]


def test_a_fresh_run_also_makes_the_earlier_cut_second_pass_before_the_current_one(tmp_path, monkeypatch):
    """キャッシュ無しで作り直しても同じ聞き取りの組になるように、前の区切り方の2回目も起こす。

    53回目の字幕は前の区切り方の2回目とも突き合わせていたが、それはキャッシュにしか無く、キャッシュ無しで
    作り直すと作られなかった（完成版の再現・2026-10-17）。先に起こすので、いまの区切り方の2回目は区切りが
    変わらないチャンクをそこから写せる。
    """
    from agents.pipeline_types import PipelineContext
    from agents.workers.transcribe_worker import TranscribeWorker
    from subtitle_engine import gemini_transcriber as gt

    _setup_two_passes(tmp_path, monkeypatch)
    fake = gt.transcribe
    made = []

    def noting(path, **kw):
        made.append((kw.get("first_chunk_sec"), list(kw.get("avoid_cuts") or []),
                     [Path(e).name for e in kw.get("earlier") or []], Path(kw["journal"]).name))
        return fake(path, **kw)
    monkeypatch.setattr(gt, "transcribe", noting)

    result = asyncio.run(TranscribeWorker().execute(PipelineContext(video_path=str(_video(tmp_path)))))

    before = gt.CUT_TAG + gt.SECOND_PASS_EARLIER_TAGS[-1] + "_"
    now = gt.CUT_TAG + gt.SECOND_PASS_TAG + "_"
    # 1回目・前の区切り方の2回目（1回目の区切りを避けない）・いまの2回目の順
    assert [(m[0], m[1]) for m in made] == [(None, []), (15, []), (15, [30.0])]
    assert before in made[1][3] and now in made[2][3]
    assert made[2][2] and all(before in name for name in made[2][2]), "いまの2回目は前の区切り方から写せる"
    earlier = result.data["second_pass"]["earlier"]
    assert [(e["tag"], e["models"]) for e in earlier] == [(gt.SECOND_PASS_EARLIER_TAGS[-1], ["m"])]


def test_a_failed_second_pass_keeps_the_first_and_says_so(tmp_path, monkeypatch):
    from agents.pipeline_types import PipelineContext
    from agents.workers.transcribe_worker import TranscribeWorker

    _setup_two_passes(tmp_path, monkeypatch, second_fails=True)
    ctx = PipelineContext(video_path=str(_video(tmp_path)))

    result = asyncio.run(TranscribeWorker().execute(ctx))

    assert result.success
    assert ctx.segments[0]["text"].startswith("こんにちは、諸岡の北原美麗です。")
    assert any("2回目" in w for w in ctx.warnings)


def test_without_the_recogniser_there_is_no_second_pass(tmp_path, monkeypatch):
    from agents.pipeline_types import PipelineContext
    from agents.workers.transcribe_worker import TranscribeWorker
    from subtitle_engine import aligner

    calls = _setup_two_passes(tmp_path, monkeypatch)
    monkeypatch.setattr(aligner, "tokens_for", lambda media: None)
    ctx = PipelineContext(video_path=str(_video(tmp_path)))

    result = asyncio.run(TranscribeWorker().execute(ctx))

    assert result.success and calls == [None]


def test_each_pass_keeps_chunk_notes_beside_its_cache_until_the_cache_is_written(tmp_path, monkeypatch):
    """1回目・2回目とも、途中で落ちたら続きから起こせるようにチャンクごとの控えを渡す。"""
    from agents.pipeline_types import PipelineContext
    from agents.workers.transcribe_worker import TranscribeWorker
    from subtitle_engine import gemini_transcriber as gt

    _setup_two_passes(tmp_path, monkeypatch)
    fake = gt.transcribe
    journals = []

    def noting(path, **kw):
        journals.append(Path(kw["journal"]))
        Path(kw["journal"]).write_text("{}\n", encoding="utf-8")  # 起こしている途中の控え
        return fake(path, **kw)
    monkeypatch.setattr(gt, "transcribe", noting)

    asyncio.run(TranscribeWorker().execute(PipelineContext(video_path=str(_video(tmp_path)))))

    assert [j.parent for j in journals] == [tmp_path] * 3
    assert len(set(journals)) == 3, "1回目・前の区切り方の2回目・いまの2回目で控えを分ける"
    assert not any(j.exists() for j in journals), "キャッシュを書いたら控えは要らない"


# ------------------------------------------------------------
# 7. 3回目の起こし（2回でも決めきれない所だけ）
# ------------------------------------------------------------

OMIT_ROW = "そう何かやっぱり好きだったから普通だったらもう行かないって平気でした。"
OMIT_HEARD = "そう何かやっぱり好きだったから普通泣いて帰ったらもう行かないって平気でした"


def test_a_spot_both_passes_dropped_is_found_where_the_recogniser_heard_more():
    fused = [_row(180.8, 186.8, OMIT_ROW)]

    spots = tfu.look_spots(fused, fused, _heard(OMIT_HEARD, 180.8, 0.15))

    assert [(s["kind"], s["cur"], s["want"]) for s in spots] == [("omit", "だ", "泣いて帰")]
    assert fused[0]["text"][spots[0]["c0"]:spots[0]["c1"]] == "だ"


@pytest.mark.parametrize("row, heard", [
    # 認識が多く聞いたのが2字だけ
    ("今日は普通にもう行かないって平気でした。", "今日は普通ににもう行かないって平気でした"),
    # 言いよどみ・数字・英字（認識はローマ字で書く）
    ("今日は普通にもう行かないって平気でした。", "今日は普通にあのあのあのもう行かないって平気でした"),
    ("今日は普通にもう行かないって平気でした。", "今日は普通に千五百もう行かないって平気でした"),
    ("一回目の未来チャンネルのゲストとして", "一回目のmillaychanelのゲストとして"),
    # 前後で合う字が短い（確かな所に挟まれていない）
    ("今日は普通だったら行かない。", "今日は普通泣いて帰ったら来ない"),
])
def test_a_spot_is_not_looked_at_again_without_strong_evidence(row, heard):
    fused = [_row(0.0, 5.0, row)]

    assert tfu.look_spots(fused, fused, _heard(heard)) == []


DROP_FIRST = "という感じで。そう何にかやっぱり好きだったから"
DROP_SECOND = "という感じで。そう何かやっぱり好きだったから"
DROP_HEARD = "という感じで何かやっぱり好きだったから"  # 認識は「そう」を落とした


def test_a_character_the_second_pass_dropped_is_looked_at_where_only_one_side_confirms_it():
    fused = [_row(176.0, 182.0, DROP_FIRST)]

    # 2対1 の決め方では、前後2字ずつ（「う何かや」）が認識に無いので決められない
    out, _ = tfu.fuse(fused, [_row(176.0, 182.0, DROP_SECOND)], _heard(DROP_HEARD, 176.0))
    assert out[0]["text"] == DROP_FIRST

    spots = tfu.look_spots(fused, [_row(176.0, 182.0, DROP_SECOND)], _heard(DROP_HEARD, 176.0))

    assert [(s["kind"], s["cur"], s["want"]) for s in spots] == [("drop", "に", "")]


def test_a_character_the_recogniser_heard_is_not_looked_at_again():
    fused = [_row(176.0, 182.0, DROP_FIRST)]

    spots = tfu.look_spots(fused, [_row(176.0, 182.0, DROP_SECOND)],
                           _heard("という感じでそう何にかやっぱり好きだったから", 176.0))

    assert spots == []


SWAP_ROWS = ["はい、わかりました。", "先生、あの、去年初めての初めてですね。"]
SWAP_HEARD = "はいわかりました今日ね初めての初めてはい"  # 認識は「先生、あの、」を落とした


def _swap_rows():
    return [_row(2562.3, 2564.6, SWAP_ROWS[0]), _row(2564.6, 2569.1, SWAP_ROWS[1])]


def test_a_spot_both_passes_misheard_alike_is_found_where_the_recogniser_heard_other_words():
    """42分03秒（43回目）: 2回とも「去年初めての初めてですね」、認識は「今日ね初めての初めて」。"""
    fused = _swap_rows()

    spots = tfu.look_spots(fused, fused, _heard(SWAP_HEARD, 2562.3, 0.25))

    assert [(s["kind"], s["cur"], s["want"]) for s in spots] == [("swap", "先生あの去年", "今日ね")]
    assert fused[1]["text"][spots[0]["c0"]:spots[0]["c1"]] == "先生、あの、去年"


@pytest.mark.parametrize("row, heard", [
    # かなと漢字の書き分けだけ（「いただき」と「頂き」）
    ("大切にされている言葉を書いていただきますね。", "大切にされている言葉を書いて頂きますね"),
    # 2字以下のかなどうし（助詞の違い）
    ("それがその経験が今の活動の原点にそうですね。", "それがその経験が今の活動の原点でそうですね"),
    # 数字（認識は漢数字で書く）
    ("自宅からね40分回ればいけるんで。", "自宅からね四十分もあればいけるんで"),
])
def test_a_spot_that_differs_only_in_spelling_or_particles_is_not_read_again(row, heard):
    fused = [_row(0.0, 5.0, row)]

    assert tfu.look_spots(fused, fused, _heard(heard)) == []


def test_a_word_in_the_dictionary_is_not_read_again():
    """名前は認識が別の字を書きやすい（31秒: 2回とも「久木田博信」、認識は「久木田浩信」）。"""
    fused = [_row(31.0, 42.0, "デザイン書道の第一人者久木田博信先生です。")]
    heard = _heard("デザイン書道の第一人者久木田浩信先生です", 31.0)

    assert [s["cur"] for s in tfu.look_spots(fused, fused, heard)] == ["博"]
    assert tfu.look_spots(fused, fused, heard, protect=("久木田博信",)) == []


NEITHER_ROW = "でじゃあ、怒んないように少しだったら"
NEITHER_SECOND = "でじゃあ怒れないように少しだったら"
NEITHER_HEARD = "はいでじゃあ折れないように少しだったらあ"


def test_a_spot_the_two_passes_wrote_differently_and_neither_was_heard_is_read_again():
    """9分18秒（44回目）: 1回目「怒んないように」・2回目「怒れないように」、認識は「折れないように」
    （芯が折れない話）。2回の突き合わせはどちらも認識に聞こえないので1回目のまま残し、校閲が
    「焦んないように」と書いた。2回とも同じ字の所（"swap"）とは別の候補にする。"""
    fused = [_row(564.5, 568.9, NEITHER_ROW)]
    second = [_row(564.5, 569.1, NEITHER_SECOND)]

    spots = tfu.look_spots(fused, second, _heard(NEITHER_HEARD, 564.0, 0.2))

    assert [(s["kind"], s["cur"], s["want"]) for s in spots] == [("neither", "怒ん", "折れ")]
    assert fused[0]["text"][spots[0]["c0"]:spots[0]["c1"]] == "、怒ん"


def test_a_spot_the_two_passes_wrote_differently_is_read_again_only_where_neither_was_heard():
    """2回目の字が認識に聞こえれば、突き合わせ（`fuse`）がその字にしているので候補にならない。"""
    first, second = [_row(564.5, 568.9, NEITHER_ROW)], [_row(564.5, 569.1, "でじゃあ折れないように少しだったら")]
    heard = _heard(NEITHER_HEARD, 564.0, 0.2)
    fused, _ = tfu.fuse(first, second, heard)

    assert fused[0]["text"] == "でじゃあ、折れないように少しだったら"
    assert tfu.look_spots(fused, second, heard) == []


@pytest.mark.parametrize("third_text, verdict, row", [
    # 3回目が認識と同じ字を書いた（2回の起こしはそれぞれ別の字）
    ("でじゃあ、折れないように少しだったら", "adopt", "でじゃあ、折れないように少しだったら"),
    # 3回目は2回目と同じ字（認識とは食い違ったまま。決めない）
    ("でじゃあ怒れないように少しだったら", "open", NEITHER_ROW),
    # 3回目は1回目と同じ字
    ("でじゃあ、怒んないように少しだったら", "keep", NEITHER_ROW),
])
def test_the_third_reading_decides_a_spot_neither_pass_was_heard(third_text, verdict, row):
    fused = [_row(564.5, 568.9, NEITHER_ROW)]
    spots = tfu.look_spots(fused, [_row(564.5, 569.1, NEITHER_SECOND)], _heard(NEITHER_HEARD, 564.0, 0.2))
    third = [_row(560.0, 575.0, third_text)]

    out, _ = _settle(fused, third, spots)

    assert tfu.judge(fused, third, spots[0])[0] == verdict
    assert [s["text"] for s in out] == [row]


@pytest.mark.parametrize("third_text, verdict, row", [
    # 3回目が認識に沿う字を書いた（2回の起こしの「先生、あの、」は残す）
    ("はい、わかりました。先生、あの、今日ね、初めての初めてですね。", "adopt", "先生、あの、今日ね、初めての初めてですね。"),
    # 3回目も2回の起こしと同じ
    ("はい、わかりました。先生、あの、去年初めての初めてですね。", "keep", SWAP_ROWS[1]),
    # 認識の字は書いたが、2回の起こしの字を2字以上落とした（「先生、あの、」）
    ("はい、わかりました。今日ね、初めての初めてですね。", "open", SWAP_ROWS[1]),
    # どちらでもない字
    ("はい、わかりました。先生、あの、今日は初めての初めてですね。", "open", SWAP_ROWS[1]),
])
def test_the_third_reading_decides_a_spot_both_passes_misheard_alike(third_text, verdict, row):
    fused = _swap_rows()
    spots = tfu.look_spots(fused, fused, _heard(SWAP_HEARD, 2562.3, 0.25))
    third = [_row(2556.0, 2575.0, third_text)]

    out, _ = _settle(fused, third, spots)

    assert tfu.judge(fused, third, spots[0])[0] == verdict
    assert [s["text"] for s in out] == [SWAP_ROWS[0], row]


def _settle(fused, third, spots):
    return tfu.settle(fused, spots, [tfu.judge(fused, third, s) for s in spots])


def test_the_third_reading_fills_in_what_both_passes_dropped():
    fused = [_row(180.8, 186.8, OMIT_ROW)]
    spots = tfu.look_spots(fused, fused, _heard(OMIT_HEARD, 180.8, 0.15))
    third = [_row(175.0, 190.0, "そう、何かやっぱり好きだったから、普通泣いて帰ったら、もう行かないって平気でした。")]

    out, stats = _settle(fused, third, spots)

    assert out[0]["text"] == "そう何かやっぱり好きだったから普通泣いて帰ったらもう行かないって平気でした。"
    assert stats["adopted"] == 1
    assert stats["examples"] == [{"start": 180.8, "before": "だ", "after": "泣いて帰"}]
    assert out[0]["start"] == 180.8 and fused[0]["text"] == OMIT_ROW, "時刻は変えず、渡した行も書き換えない"


def test_the_third_reading_drops_a_character_only_when_it_also_leaves_it_out():
    fused = [_row(176.0, 182.0, DROP_FIRST)]
    spots = tfu.look_spots(fused, [_row(176.0, 182.0, DROP_SECOND)], _heard(DROP_HEARD, 176.0))

    dropped, _ = _settle(fused, [_row(170.0, 190.0, "という感じで、そう、何かやっぱり好きだったから")], spots)
    kept, stats = _settle(fused, [_row(170.0, 190.0, "という感じで、そう何にかやっぱり好きだったから")], spots)

    assert dropped[0]["text"] == "という感じで。そう何かやっぱり好きだったから"
    assert kept[0]["text"] == DROP_FIRST and (stats["adopted"], stats["kept"]) == (0, 1)


def test_only_what_the_recogniser_also_heard_is_put_in():
    """3回目だけが足した字は置かない（3分03秒・余白 28 秒の読み「普通に泣いて帰ったら」の「に」）。"""
    fused = [_row(180.8, 186.8, OMIT_ROW)]
    spots = tfu.look_spots(fused, fused, _heard(OMIT_HEARD, 180.8, 0.15))
    third = [_row(175.0, 190.0, "そう何かやっぱり好きだったから普通に泣いて帰ったらもう行かないって平気でした。")]

    out, _ = _settle(fused, third, spots)

    assert out[0]["text"] == "そう何かやっぱり好きだったから普通泣いて帰ったらもう行かないって平気でした。"


@pytest.mark.parametrize("third_text, verdict", [
    # 3回目も同じ（2回の起こしにそろう: そのまま）
    ("そう何かやっぱり好きだったから普通だったらもう行かないって平気でした。", "keep"),
    # 認識とも違う・前後の字が無い（決まらない: 区間を変えて読み直す）
    ("そう何かやっぱり好きだったから普通泣いてがったらもう行かないって平気でした。", "open"),
    ("全然違う話をしています。", "open"),
])
def test_the_row_stays_unless_the_third_reading_agrees_with_the_recogniser(third_text, verdict):
    fused = [_row(180.8, 186.8, OMIT_ROW)]
    spots = tfu.look_spots(fused, fused, _heard(OMIT_HEARD, 180.8, 0.15))
    third = [_row(175.0, 190.0, third_text)]

    out, stats = _settle(fused, third, spots)

    assert out[0]["text"] == OMIT_ROW and stats["adopted"] == 0
    assert tfu.judge(fused, third, spots[0]) == (verdict, "")


def test_the_third_reading_far_from_the_row_is_not_used():
    fused = [_row(180.8, 186.8, OMIT_ROW)]
    spots = tfu.look_spots(fused, fused, _heard(OMIT_HEARD, 180.8, 0.15))
    far = [_row(600.0, 610.0, "そう、何かやっぱり好きだったから、普通泣いて帰ったら、もう行かないって平気でした。")]

    out, _ = _settle(fused, far, spots)

    assert out[0]["text"] == OMIT_ROW


def test_a_spot_at_the_head_of_a_row_takes_no_punctuation_from_the_sentence_before():
    """4分46秒: 2回とも「で、一番盛ん」、認識は「やっぱり一番盛ん」（行の頭の「で」を認識は落とす）。"""
    fused = [_row(284.0, 285.8, "そうですかね。"), _row(285.8, 295.8, "で、一番盛んになったのが")]
    spots = tfu.look_spots(fused, fused, _heard("そうですかねやっぱり一番盛んになったのが", 284.0, 0.3))
    assert [(s["row"], s["cur"], s["want"]) for s in spots] == [(1, "で", "やっぱり")]

    out, _ = _settle(fused, [_row(280.0, 300.0, "そうですかね。で、やっぱり一番盛んになったのが")], spots)

    assert [s["text"] for s in out] == ["そうですかね。", "で、やっぱり一番盛んになったのが"]


def test_windows_put_each_spot_in_the_middle_and_merge_close_ones():
    from subtitle_engine import gemini_transcriber as gt

    assert gt.look_windows([(100.0, 106.0)]) == [(92.0, 22.0)]
    # 重なる区間は 45 秒以内なら1つに
    assert gt.look_windows([(110.0, 115.0), (100.0, 106.0)]) == [(92.0, 31.0)]
    # まとめると長すぎるなら別々（重なってよい）
    assert gt.look_windows([(100.0, 120.0), (125.0, 150.0)]) == [(92.0, 36.0), (117.0, 41.0)]

    class Quiet:  # 一番静かな所は狙いの1秒後ろ
        def quietest(self, lo, hi, target):
            return min(hi, target + 1.0)

    assert gt.look_windows([(100.0, 106.0)], Quiet()) == [(93.0, 22.0)]
    # 読み直しは余白を広げる。まとめてよい長さも広げた分だけ延びる（45→65 秒）
    assert gt.look_windows([(100.0, 106.0)], pad=18.0) == [(82.0, 42.0)]
    assert gt.look_windows([(100.0, 106.0), (120.0, 126.0)], pad=18.0) == [(82.0, 62.0)]


def _fake_split(seen):
    def split(video, work, plan=None, **kw):
        seen.append(list(plan))
        return [(Path(work) / f"c{i}.mp3", o, d) for i, (o, d) in enumerate(plan)]
    return split


def test_windows_are_transcribed_once_and_read_from_their_notes_after(tmp_path, monkeypatch):
    from subtitle_engine import gemini_transcriber as gt

    seen, calls = [], []
    monkeypatch.setattr(gt, "split_audio", _fake_split(seen))

    def call(client, model, path, dur):
        calls.append(path.name)
        return json.dumps([{"start": 1.0, "end": 3.0, "text": "区間 です"}]), "m-used"

    journal = tmp_path / "_gemini_c30qc_x.chunks.journal"
    windows = [(92.0, 22.0), (300.0, 20.0)]
    segs, models = gt.transcribe_windows(tmp_path / "v.mp4", windows, client=object(), model="m",
                                         call=call, journal=journal)
    again, _ = gt.transcribe_windows(tmp_path / "v.mp4", windows, client=object(), model="m",
                                     call=call, journal=journal)

    assert calls == ["c0.mp3", "c1.mp3"], "2回目の実行では控えを使い、呼ばない"
    assert [s["start"] for s in segs] == [93.0, 301.0] and models == ["m-used"]
    assert segs[0]["text"] == "区間です", "日本語の間の空白は詰める"
    assert again == segs


def test_a_window_that_cannot_be_transcribed_fails_the_third_reading(tmp_path, monkeypatch):
    from subtitle_engine import gemini_transcriber as gt

    monkeypatch.setattr(gt, "split_audio", _fake_split([]))

    def call(client, model, path, dur):
        raise ValueError("JSON を読めません")

    with pytest.raises(gt.TranscriptionError):
        gt.transcribe_windows(tmp_path / "v.mp4", [(92.0, 22.0)], client=object(), model="m",
                              call=call, attempts=2, backoff=0, journal=tmp_path / "j")


FIXED = "そう、何かやっぱり好きだったから、普通泣いて帰ったら、もう行かないって平気でした。"
MISHEARD = "そう、何かやっぱり好きだったから、普通ナイデがったら、もう行かないって平気でした。"


def _setup_third_look(tmp_path, monkeypatch, readings=(FIXED,)):
    """1回目・2回目とも「普通だったら」、認識は「普通泣いて帰ったら」。

    readings は3回目以降の起こしの文（呼ばれた順・足りなければ最後のもの。None なら落ちる）。"""
    from subtitle_engine import aligner, gemini_transcriber as gt

    monkeypatch.setenv("AVS_TRANSCRIBE_ENGINE", "gemini")
    pad = "あいうえおかきくけこ" * 30

    def fake_transcribe(path, **kw):
        return gt.TranscribeResult(segments=[_row(0.4, 6.0, OMIT_ROW), _row(6.0, 30.0, pad)], model="m",
                                   chunks=1, models_used=["m"], cuts=[15.0] if kw.get("first_chunk_sec") else [30.0])
    monkeypatch.setattr(gt, "transcribe", fake_transcribe)
    monkeypatch.setattr(aligner, "tokens_for", lambda media: _heard(OMIT_HEARD + pad, 0.4, 0.08))
    monkeypatch.setattr(gt.QuietMap, "from_media", classmethod(lambda cls, media: None))
    looked = []

    def fake_windows(path, windows, **kw):
        looked.append((list(windows), Path(kw["journal"]).name))
        text = readings[min(len(looked), len(readings)) - 1]
        if text is None:
            raise gt.TranscriptionError("3回目の起こし（0秒〜）ができません")
        return [_row(0.0, 14.0, text)], ["m3"]
    monkeypatch.setattr(gt, "transcribe_windows", fake_windows)
    return looked


def test_the_stage_reads_the_undecided_spots_a_third_time(tmp_path, monkeypatch):
    from agents.pipeline_types import PipelineContext
    from agents.workers.transcribe_worker import TranscribeWorker

    looked = _setup_third_look(tmp_path, monkeypatch)
    ctx = PipelineContext(video_path=str(_video(tmp_path)))

    result = asyncio.run(TranscribeWorker().execute(ctx))

    assert result.success
    assert ctx.segments[0]["text"] == "そう何かやっぱり好きだったから普通泣いて帰ったらもう行かないって平気でした。"
    look = result.data["second_pass"]["third_look"]
    assert (look["spots"], look["windows"], look["adopted"], look["models"]) == (1, 1, 1, ["m3"])
    (windows, journal), = looked
    assert windows == [(0.0, 14.0)]  # 行の前後 8 秒（素材の頭で切れる）
    assert journal.startswith("_gemini_c30qc_") and journal.endswith(".chunks.journal"), "3回目は別の控え"


def test_the_third_reading_also_looks_where_an_earlier_second_pass_dropped_a_character(tmp_path, monkeypatch):
    """前の区切り方の2回目だけが1字消した所も3回目で読む（候補は聞き取りごとに探してまとめる）。

    45回目の後: 前の2回目と突き合わせると、いまの2回目とだけ見ていた候補では「書道で→書で」
    「奈良筆でも→奈良筆も」「最後の最後に→最後の最後」（44回目に前の2回目から3回目で直した所）が戻った。
    """
    from agents.pipeline_types import PipelineContext
    from agents.workers.transcribe_worker import TranscribeWorker
    from subtitle_engine import aligner, gemini_transcriber as gt

    monkeypatch.setenv("AVS_TRANSCRIBE_ENGINE", "gemini")
    pad = "あいうえおかきくけこ" * 30
    second = [DROP_SECOND]

    def fake_transcribe(path, **kw):
        text = second[0] if kw.get("first_chunk_sec") else DROP_FIRST
        return gt.TranscribeResult(segments=[_row(0.4, 6.0, text), _row(6.0, 30.0, pad)], model="m",
                                   chunks=1, models_used=["m"], cuts=[15.0] if kw.get("first_chunk_sec") else [30.0])
    monkeypatch.setattr(gt, "transcribe", fake_transcribe)
    monkeypatch.setattr(aligner, "tokens_for", lambda media: _heard(DROP_HEARD + pad, 0.4, 0.08))
    monkeypatch.setattr(gt.QuietMap, "from_media", classmethod(lambda cls, media: None))
    monkeypatch.setattr(gt, "transcribe_windows", lambda path, windows, **kw: (
        [_row(0.0, 14.0, "という感じで、そう、何かやっぱり好きだったから")], ["m3"]))
    asyncio.run(TranscribeWorker().execute(PipelineContext(video_path=str(_video(tmp_path)))))
    now = gt.CUT_TAG + gt.SECOND_PASS_TAG + "_"
    before = gt.CUT_TAG + gt.SECOND_PASS_EARLIER_TAGS[-1] + "_"
    for p in tmp_path.glob(f"_gemini_*{now}*"):
        p.rename(p.with_name(p.name.replace(now, before)))
    second[0] = DROP_FIRST  # いまの区切り方の2回目は1回目と同じ字を書いた
    ctx = PipelineContext(video_path=str(_video(tmp_path)))

    result = asyncio.run(TranscribeWorker().execute(ctx))

    assert ctx.segments[0]["text"] == DROP_SECOND
    look = result.data["second_pass"]["third_look"]
    assert (look["spots"], look["adopted"]) == (1, 1)


def test_a_failed_third_reading_keeps_the_two_pass_result_and_says_so(tmp_path, monkeypatch):
    from agents.pipeline_types import PipelineContext
    from agents.workers.transcribe_worker import TranscribeWorker

    _setup_third_look(tmp_path, monkeypatch, readings=(None,))
    ctx = PipelineContext(video_path=str(_video(tmp_path)))

    result = asyncio.run(TranscribeWorker().execute(ctx))

    assert result.success
    assert ctx.segments[0]["text"] == OMIT_ROW
    assert any("3回目" in w for w in ctx.warnings)


@pytest.mark.parametrize("readings, windows, text", [
    # 決まらない（認識とも違う）→ 余白 18 秒の区間で読み直して直る
    ((MISHEARD, FIXED), [(0.0, 14.0), (0.0, 24.0)], "そう何かやっぱり好きだったから普通泣いて帰ったらもう行かないって平気でした。"),
    # 2回の起こしと同じ字 → そのまま（読み直さない）
    ((OMIT_ROW,), [(0.0, 14.0)], OMIT_ROW),
    # 3回読んでも決まらない → そのまま
    ((MISHEARD,), [(0.0, 14.0), (0.0, 24.0), (0.0, 34.0)], OMIT_ROW),
])
def test_a_spot_the_third_reading_does_not_decide_is_read_again_with_a_wider_window(
        tmp_path, monkeypatch, readings, windows, text):
    from agents.pipeline_types import PipelineContext
    from agents.workers.transcribe_worker import TranscribeWorker

    looked = _setup_third_look(tmp_path, monkeypatch, readings=readings)
    ctx = PipelineContext(video_path=str(_video(tmp_path)))

    result = asyncio.run(TranscribeWorker().execute(ctx))

    assert result.success and ctx.segments[0]["text"] == text
    assert [w for (w,), _ in looked] == windows, "余白 8→18→28 秒。同じ控えに書き足す"
    assert len({journal for _, journal in looked}) == 1
    look = result.data["second_pass"]["third_look"]
    assert look["windows"] == len(windows)


SWAP_ROW = "はい、わかりました。先生、あの、去年初めての初めてですね。"
SWAP_FIXED = "はい、わかりました。先生、あの、今日ね、初めての初めてですね。"


def _setup_swap(monkeypatch, rows, heard, readings, second=None):
    """rows は1回目の起こし（second があれば2回目はそれ、無ければ1回目と同じ）。"""
    from subtitle_engine import aligner, gemini_transcriber as gt

    monkeypatch.setenv("AVS_TRANSCRIBE_ENGINE", "gemini")
    pad = "あいうえおかきくけこ" * 30

    def fake_transcribe(path, **kw):
        again = bool(kw.get("first_chunk_sec"))
        return gt.TranscribeResult(segments=[*(second if again and second else rows), _row(20.0, 50.0, pad)],
                                   model="m", chunks=1, models_used=["m"], cuts=[15.0] if again else [30.0])
    monkeypatch.setattr(gt, "transcribe", fake_transcribe)
    monkeypatch.setattr(aligner, "tokens_for", lambda media: _heard(heard + pad, 0.4, 0.08))
    monkeypatch.setattr(gt.QuietMap, "from_media", classmethod(lambda cls, media: None))
    looked = []

    def fake_windows(path, windows, **kw):
        looked.append(list(windows))
        return [_row(0.0, 20.0, readings)], ["m3"]
    monkeypatch.setattr(gt, "transcribe_windows", fake_windows)
    return looked


def test_spots_where_only_the_recogniser_heard_other_words_are_read_in_their_own_windows(tmp_path, monkeypatch):
    """(c) の候補を (a)(b) の候補と同じ区間にまとめると、(a)(b) の区間が変わって控えが使えなくなり、
    直っていた所（3分03秒）を読み直すことになる。"""
    from agents.pipeline_types import PipelineContext
    from agents.workers.transcribe_worker import TranscribeWorker

    looked = _setup_swap(monkeypatch, [_row(0.4, 6.0, OMIT_ROW), _row(10.0, 14.0, SWAP_ROW)],
                         OMIT_HEARD + "はいわかりました今日ね初めての初めてですね", FIXED + SWAP_FIXED)
    ctx = PipelineContext(video_path=str(_video(tmp_path)))

    result = asyncio.run(TranscribeWorker().execute(ctx))

    assert result.success
    assert looked == [[(0.0, 14.0)], [(2.0, 20.0)]], "(a)(b) の区間は (c) が無いときと同じ"
    assert [s["text"] for s in ctx.segments[:2]] == [
        "そう何かやっぱり好きだったから普通泣いて帰ったらもう行かないって平気でした。",
        "はい、わかりました。先生、あの、今日ね、初めての初めてですね。"]
    look = result.data["second_pass"]["third_look"]
    assert (look["spots"], look["windows"], look["adopted"]) == (2, 2, 2)


def test_spots_neither_pass_was_heard_are_read_in_their_own_windows(tmp_path, monkeypatch):
    """"neither" の候補も "swap" の候補と同じ区間にまとめない（"swap" の区間が変わると控えが使えず、
    決まっていた所を読み直すことになる）。"""
    from agents.pipeline_types import PipelineContext
    from agents.workers.transcribe_worker import TranscribeWorker

    looked = _setup_swap(monkeypatch, [_row(10.0, 14.0, SWAP_ROW), _row(15.0, 19.0, NEITHER_ROW)],
                         "はいわかりました今日ね初めての初めてですね" + "でじゃあ折れないように少しだったら",
                         SWAP_FIXED + "でじゃあ、折れないように少しだったら",
                         second=[_row(10.0, 14.0, SWAP_ROW), _row(15.0, 19.0, NEITHER_SECOND)])
    ctx = PipelineContext(video_path=str(_video(tmp_path)))

    result = asyncio.run(TranscribeWorker().execute(ctx))

    assert result.success
    assert looked == [[(2.0, 20.0)], [(7.0, 20.0)]], "\"swap\" の区間は \"neither\" が無いときと同じ"
    assert [s["text"] for s in ctx.segments[:2]] == [SWAP_FIXED, "でじゃあ、折れないように少しだったら"]
    look = result.data["second_pass"]["third_look"]
    assert (look["spots"], look["windows"], look["adopted"]) == (2, 2, 2)


def test_a_name_in_the_dictionary_is_not_read_a_third_time(tmp_path, monkeypatch):
    from agents.pipeline_types import PipelineContext
    from agents.workers.transcribe_worker import TranscribeWorker
    from subtitle_engine import aligner

    monkeypatch.setattr(aligner, "_dictionary_terms", lambda: (("久保田博信", "久木田博信"),))
    looked = _setup_swap(monkeypatch, [_row(0.4, 6.0, "デザイン書道の第一人者久木田博信先生です。")],
                         "デザイン書道の第一人者久木田浩信先生です", "デザイン書道の第一人者久木田浩信先生です。")
    ctx = PipelineContext(video_path=str(_video(tmp_path)))

    result = asyncio.run(TranscribeWorker().execute(ctx))

    assert result.success and looked == []
    assert ctx.segments[0]["text"] == "デザイン書道の第一人者久木田博信先生です。"


def test_a_failed_reading_again_leaves_the_spot_and_says_so(tmp_path, monkeypatch):
    from agents.pipeline_types import PipelineContext
    from agents.workers.transcribe_worker import TranscribeWorker

    looked = _setup_third_look(tmp_path, monkeypatch, readings=(MISHEARD, None))
    ctx = PipelineContext(video_path=str(_video(tmp_path)))

    result = asyncio.run(TranscribeWorker().execute(ctx))

    assert result.success and ctx.segments[0]["text"] == OMIT_ROW
    assert [w for (w,), _ in looked] == [(0.0, 14.0), (0.0, 24.0)]
    look = result.data["second_pass"]["third_look"]
    assert (look["windows"], look["open"]) == (1, 1) and "できません" in look["error"]
    assert any("3回目" in w for w in ctx.warnings)


# ------------------------------------------------------------
# 8. 3回目でも決まらない所は、校閲（AI）に「別の聞き取り」として渡す
# ------------------------------------------------------------

ZAYU_ROWS = ["座右の銘って僕ないんだよ、全然。", "なので偉そうな座右の目はなくて、僕はだからご縁なので"]
ZAYU_HEARD = "座右の銘って僕ないんだよ全然なので偉そうな座右の銘はなくて僕はだからご縁なので"


def _zayu_rows():
    return [_row(1640.0, 1646.0, ZAYU_ROWS[0]), _row(1646.0, 1652.0, ZAYU_ROWS[1])]


def test_a_spot_the_third_reading_could_not_settle_is_handed_on_as_another_hearing():
    """27分12秒（46回目）: 3回とも「座右の目」、認識は「座右の銘」。Gemini は何度起こしても同じ字を
    書くので、文脈で決める校閲に、その所と認識の字を渡す（前の行は「座右の銘って僕ないんだよ」）。"""
    fused = _zayu_rows()
    spots = tfu.look_spots(fused, fused, _heard(ZAYU_HEARD, 1640.0, 0.2))
    assert [(s["kind"], s["cur"], s["want"]) for s in spots] == [("swap", "目", "銘")]

    hints = tfu.heard_hints(fused, spots, [("keep", "")])

    assert [(h["incorrect"], h["correct"], h["term"]) for h in hints] == [("座右の目はなく", "座右の銘はなく", "銘")]
    assert hints[0]["start"] == 1646.0


def test_another_hearing_is_written_as_the_recogniser_wrote_it():
    """認識の字はそろえた字（カタカナをひらがなに）で比べるが、渡すのは認識が書いた字
    （13分55秒: 2回とも「今生田川で」、認識は「今治タオルとか」）。"""
    row = "ちょっと青森リンゴとか今生田川で、それも取っちゃうじゃない？"
    fused = [_row(830.0, 836.0, row)]
    spots = tfu.look_spots(fused, fused, _heard("ちょっと青森リンゴとか今治タオルとかそれも取っちゃうじゃない", 830.0, 0.2))
    assert [(s["kind"], s["want"]) for s in spots] == [("swap", "治たおるとか")]

    hints = tfu.heard_hints(fused, spots, [("open", "")])

    assert [(h["incorrect"], h["correct"], h["term"]) for h in hints] == [
        ("とか今生田川で", "とか今治タオルとか", "治タオルとか")]


def test_spots_the_third_reading_settled_or_that_only_drop_a_character_are_not_handed_on():
    fused = _zayu_rows()
    spots = tfu.look_spots(fused, fused, _heard(ZAYU_HEARD, 1640.0, 0.2))
    assert tfu.heard_hints(fused, spots, [("adopt", "銘")]) == []

    drop = tfu.look_spots([_row(176.0, 182.0, DROP_FIRST)], [_row(176.0, 182.0, DROP_SECOND)],
                          _heard(DROP_HEARD, 176.0))
    assert [s["kind"] for s in drop] == ["drop"]
    assert tfu.heard_hints([_row(176.0, 182.0, DROP_FIRST)], drop, [("open", "")]) == []


def test_another_hearing_takes_more_of_the_row_until_it_points_at_one_place():
    """校閲は渡した字の並びを文の中で探すので、ほかの所にも同じ並びがあれば前後を広げる。"""
    rows = ["それは座右の目はなく、と書いた。", "なので偉そうな座右の目はなくて、僕はだからご縁なので"]
    fused = [_row(1640.0, 1646.0, rows[0]), _row(1646.0, 1652.0, rows[1])]
    heard = _heard("それは座右の目はなくと書いたなので偉そうな座右の銘はなくて僕はだからご縁なので", 1640.0, 0.2)
    spots = tfu.look_spots(fused, fused, heard)
    assert [(s["row"], s["cur"]) for s in spots] == [(1, "目")]

    hints = tfu.heard_hints(fused, spots, [("keep", "")])

    assert [(h["incorrect"], h["correct"]) for h in hints] == [("な座右の目はなくて", "な座右の銘はなくて")]


def test_another_hearing_is_dropped_when_the_settled_row_no_longer_has_those_words():
    fused = _zayu_rows()
    spots = tfu.look_spots(fused, fused, _heard(ZAYU_HEARD, 1640.0, 0.2))
    settled = [fused[0], dict(fused[1], text="なので偉そうな座右の眼はなくて、僕はだからご縁なので")]

    assert tfu.heard_hints(fused, spots, [("keep", "")], settled) == []


def test_the_stage_hands_the_spots_it_could_not_settle_on_to_the_proofreader(tmp_path, monkeypatch):
    from agents.pipeline_types import PipelineContext
    from agents.workers.transcribe_worker import TranscribeWorker

    # 3回目も2回と同じ字（「去年」）を書いた → そのまま残し、認識の字（「今日ね」）を渡す
    _setup_swap(monkeypatch, [_row(10.0, 14.0, SWAP_ROW)], "はいわかりました今日ね初めての初めてですね", SWAP_ROW)
    ctx = PipelineContext(video_path=str(_video(tmp_path)))

    result = asyncio.run(TranscribeWorker().execute(ctx))

    assert result.success and ctx.segments[0]["text"] == SWAP_ROW
    assert [(h["incorrect"], h["correct"], h["term"]) for h in ctx.heard_hints] == [
        ("先生、あの、去年初めて", "今日ね初めて", "今日ね")]
    look = result.data["second_pass"]["third_look"]
    assert (look["kept"], look["hints"]) == (1, 1)


def test_a_filler_at_the_edge_of_a_spot_is_left_out_before_it_is_counted():
    """26分56秒（48回目）: 1回目「そうやって、うん、ぶっちゃけもう書きながら」・2回目「手本文字を」・認識
    「筆文字を」。認識は言いよどみを書かないので食い違いは「うんぶっちゃけもう」の9字になり、SWAP_MAX を
    超えて3回目の候補から外れていた。句読点で隔てた端の言いよどみを外して比べる。"""
    row = "だから、そうやって、うん、ぶっちゃけもう書きながら、各、お客さんがいて"
    fused = [_row(1625.7, 1629.8, row)]
    second = [_row(1625.9, 1630.0, "だから、そうやって手本文字を書きながら、各お客さんがいて")]

    spots = tfu.look_spots(fused, second, _heard("だからそうやって筆文字を書きながら各お客さんがいて", 1625.7, 0.15))

    assert [(s["kind"], s["cur"], s["want"]) for s in spots] == [("neither", "ぶっちゃけもう", "筆文字を")]
    assert row[spots[0]["c0"]:spots[0]["c1"]] == "、ぶっちゃけもう"


def test_a_filler_inside_a_word_is_not_left_out():
    """句読点で隔てていない「その」は語の一部のことがあるので外さない（候補の字数はそのまま）。"""
    x = "ほかのそのぶっちゃけもう書き"
    breaks = {3, 5}
    assert tfu._trim_fillers(x, 3, 12, breaks) == (5, 12)  # 「その」の前後に句読点がある
    assert tfu._trim_fillers(x, 3, 12, {3}) == (3, 12)     # 「その」の後ろに句読点が無い


# ------------------------------------------------------------
# 8. 2回目の起こしが割れた所（校閲の後の文で選ばせる）
# ------------------------------------------------------------

NARU_ROW = "僕はね、生活をできるように鳴ってるのは、やっぱりご縁ですよ。"
NARU_SECOND = "あのー僕がね、生活をできるようになっているのは、やっぱりご縁ですよ。"
NARU_EARLIER = "僕はね生活をできるようになってるのは、やっぱりご縁ですよ。"


def test_a_spot_the_second_pass_wrote_differently_and_the_recogniser_did_not_hear_is_split():
    """27分05秒（48回目）: 認識はこの5秒を書いていない（「僕はね生活を」の後は「うん」「なので」）ので、
    2対1 でも3回目でも決まらず「鳴ってる」が残った。前の2回目の「なってる」を候補にする。"""
    rows = [_row(1638.6, 1645.6, NARU_ROW)]
    heard = _heard("いやいや素晴らしいことですね僕はね生活をうんなので偉そうな", 1630.0, 0.5)

    spots = tfu.split_spots(rows, [[_row(1636.5, 1645.2, NARU_EARLIER)]], heard)

    assert [(s["kind"], s["cur"], s["heard"]) for s in spots] == [("split", "鳴", "な")]
    hints = tfu.heard_hints(rows, spots, [("open", "")])
    assert [(h["incorrect"], h["correct"]) for h in hints] == [("ように鳴ってる", "ようになってる")]


def test_both_second_passes_give_a_spot_each_when_they_wrote_different_words():
    """8分15秒（48回目）: 1回目「羽毛」・2回目「肌着」・前の2回目「褌」・認識「はや着」。"""
    rows = [_row(495.6, 499.0, "いや、だから僕全部脱いで、羽毛になって、そうなんですか？")]
    readings = [[_row(495.4, 499.2, "いや、だから僕全部脱いで、肌着になって、そうなんですか？")],
                [_row(495.6, 499.0, "いや、だから僕全部脱いで、褌になって、そうなんですか？")]]

    spots = tfu.split_spots(rows, readings, _heard("いやだから僕全部脱いではや着になってそうなんですか", 495.6, 0.15))

    assert [(s["cur"], s["heard"]) for s in spots] == [("羽毛", "肌着"), ("羽毛", "褌")]


def test_a_one_letter_filler_at_the_edge_of_the_second_reading_is_not_put_in():
    """11分59秒（48回目）: 1回目「最終ね、エピソード」・2回目「っていうね、え、エピソード」・認識「いうね」。
    2回目の「え」まで置くと、後ろの句読点が無いので「っていうね、えエピソード」と出る。句読点で隔てた
    端の言いよどみは、1字でも外してから置く。外した語との間の句読点は残す（49回目は「っていうね」だけを
    置いて「っていうねエピソードなんですか？」と続き、後ろの問いまで前の字幕につながった）。"""
    rows = [_row(714.5, 719.0, "俺は泣きそうになるわ。"), _row(719.06, 721.66, "最終のエピソードなんですか？"),
            _row(721.66, 729.96, "ああ、なるほど。すごいですね。")]
    readings = [[_row(714.5, 721.36, "俺は泣きそうになるわっていうね、え、エピソードなんです。"),
                 _row(721.46, 730.26, "ああ、なるほど。すごいですね。")]]

    spots = tfu.split_spots(rows, readings, _heard("俺は泣きそうになるいうねなるほどすごいですね", 714.5, 0.3))

    assert [(s["cur"], s["heard"]) for s in spots] == [("最終の", "っていうね、")]
    hints = tfu.heard_hints(rows, spots, [("open", "")])
    assert [(h["incorrect"], h["correct"]) for h in hints] == [("最終のエピソ", "っていうね、エピソ")]


@pytest.mark.parametrize("row, reading, put", [
    # 頭の言いよどみ: 外した語との間の句読点を頭に残す
    ("それはだから最終のエピソードなんです。", "それはだから、え、っていうねエピソードなんです。", "、っていうね"),
    # 本文のその端にもう句読点があれば足さない（「、、」にしない）
    ("それはだから最終の、エピソードなんです。", "それはだからっていうね、え、エピソードなんです。", "っていうね"),
])
def test_the_punctuation_beside_a_trimmed_filler_is_put_in_only_where_the_row_has_none(row, reading, put):
    spots = tfu.split_spots([_row(0.0, 5.0, row)], [[_row(0.0, 5.0, reading)]], _heard("あいうえお", 30.0))

    assert [s["heard"] for s in spots] == [put]


def test_a_spot_the_recogniser_heard_as_written_is_not_split():
    rows = [_row(495.6, 499.0, "いや、だから僕全部脱いで、羽毛になって、そうなんですか？")]
    readings = [[_row(495.4, 499.2, "いや、だから僕全部脱いで、肌着になって、そうなんですか？")]]

    assert tfu.split_spots(rows, readings, _heard("いやだから僕全部脱いで羽毛になってそうなんですか", 495.6, 0.15)) == []


def test_a_spot_the_recogniser_leans_to_is_not_split():
    """9分01秒（48回目）: 本文「12時、お腹の12時」・2回目「真夜中」・認識「おなかの十二時」。認識はかなで
    書くので字の並びでは聞こえたことにならないが、本文の字の方に寄っている。文として通る別の字に変えない
    （並べて選ばせると両順で「真夜中」を選んだ）。"""
    rows = [_row(540.0, 546.0, "てっぺんだよね。12時、お腹の12時。その前にね")]
    readings = [[_row(540.0, 546.0, "てっぺんだよね。12時、真夜中の12時。その前にね")]]

    assert tfu.split_spots(rows, readings, _heard("てっぺんだよね十二時おなかの十二時その前にね", 540.0, 0.2)) == []
    # 認識が黙っていれば候補にする
    assert [s["heard"] for s in tfu.split_spots(rows, readings, _heard("てっぺんだよねその前にね", 540.0, 0.5))] \
        == ["真夜中"]


@pytest.mark.parametrize("row, reading, kept", [
    # かなを漢字にするだけ（書き分け）・2字以下のかなどうし（助詞）は候補にしない
    ("大切にされている言葉を書いていただきますね。", "大切にされている言葉を書いて頂きますね。", False),
    ("それがその経験が今の活動の原点にそうですね。", "それがその経験が今の活動の原点でそうですね。", False),
    # 漢字をかなにするのは残す（本文の漢字が同じ音の別の語のことがある）
    ("生活をできるように鳴ってるのは、やっぱり", "生活をできるようになってるのは、やっぱり", True),
    # 数字・言いよどみ
    ("自宅からね40分回ればいけるんですよね。", "自宅からね45分回ればいけるんですよね。", False),
])
def test_spelling_particles_and_numbers_are_not_split(row, reading, kept):
    spots = tfu.split_spots([_row(0.0, 5.0, row)], [[_row(0.0, 5.0, reading)]], _heard("あいうえお", 30.0))

    assert bool(spots) is kept


def test_a_word_in_the_dictionary_is_not_split():
    """辞書の語は誤りの字も正しい字も候補にしない（52秒: 本文「久喜田」・2回目「釘本」。辞書が「久木田」に直す）。"""
    rows = [_row(52.8, 60.0, "先生は株式会社アドシアター代表で、久喜田デザイン書道塾主宰")]
    readings = [[_row(52.8, 60.0, "先生は株式会社アドシアター代表で、釘本デザイン書道塾主宰")]]
    heard = _heard("あいうえお", 100.0)

    assert [s["cur"] for s in tfu.split_spots(rows, readings, heard)] == ["久喜田"]
    assert tfu.split_spots(rows, readings, heard, protect=("久喜田", "久木田")) == []


def test_the_stage_keeps_the_second_readings_for_choosing_after_proofreading(tmp_path, monkeypatch):
    """校閲の後に割れた所を選び直す（`ProofreadWorker`）ために、2回目の起こしの行を残す。"""
    from agents.pipeline_types import PipelineContext
    from agents.workers.transcribe_worker import TranscribeWorker

    _setup_two_passes(tmp_path, monkeypatch)
    ctx = PipelineContext(video_path=str(_video(tmp_path)))

    assert asyncio.run(TranscribeWorker().execute(ctx)).success
    assert len(ctx.second_readings) == 2  # いまの区切り方・前の区切り方
    assert all(r[0]["text"].startswith("こんにちは、書家の北原美麗です。") for r in ctx.second_readings)
