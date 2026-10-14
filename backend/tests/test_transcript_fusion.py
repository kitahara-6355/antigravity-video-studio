"""文字起こしを2回して、食い違いを手元の音声認識で決める（2026-10-06）。

起こしの区切りを変えて起こし直すと、Gemini の聞き違いが毎回別の所に出た
（26回目の冒頭で「書家の北原」が「諸岡の北原」、「書に出会った」が「よそに出会った」）。
温度 0 でも区切りが変われば渡す音声が変わる。どちらの回の字が正しいかは運だった。

守りたい性質:

1. 2回目と手元の音声認識が同じ字を聞き、1回目だけが違う所は 2回目の字にする（2対1）
2. 認識が1回目と同じ・どちらとも違う所は 1回目のまま
3. 行の分け方と時刻は 1回目のまま（字だけ直す）
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

    assert called == ["c1", "c2"]
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

    assert called == ["c0", "c1"] and tx.carried == 0


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
    assert calls == [None, 15]  # 2回目は区切りを半分ずらす
    assert ctx.segments[0]["text"].startswith("こんにちは、書家の北原美麗です。")
    assert result.data["second_pass"]["adopted"] == 1
    assert len(list(tmp_path.glob("_gemini_*.jsonl"))) == 2, "1回目と2回目を別々にキャッシュする"


def test_the_second_pass_is_read_from_its_cache(tmp_path, monkeypatch):
    from agents.pipeline_types import PipelineContext
    from agents.workers.transcribe_worker import TranscribeWorker

    calls = _setup_two_passes(tmp_path, monkeypatch)
    asyncio.run(TranscribeWorker().execute(PipelineContext(video_path=str(_video(tmp_path)))))
    ctx = PipelineContext(video_path=str(tmp_path / "v.mp4"))

    asyncio.run(TranscribeWorker().execute(ctx))

    assert calls == [None, 15]  # 2回目の実行では起こさない
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

    assert avoid == [[], [30.0], [30.0]]
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

    assert calls == [None, 15, 15], "前の区切り方の2回目をそのままは使わない"
    assert len(earlier) == 1 and earlier[0] and all(before in name for name in earlier[0])


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

    assert [j.parent for j in journals] == [tmp_path, tmp_path]
    assert len(set(journals)) == 2, "1回目と2回目で控えを分ける"
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
