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
5. 2回目は区切りの位置をずらして起こす（1回目の区切りの前後が2回目では区切りの中ほどになる）
6. 認識が使えない・2回目が落ちたら 1回目のまま進む
7. 2回でも決めきれない所（2回とも落とした・認識が片側でしか確かめられない）だけ、そこが真ん中に来る
   区間をもう1回起こし、3回目が認識に沿う字を書いたときだけ直す（2026-10-14・3分03秒
   「普通だったら」→「普通泣いて帰ったら」）。区間ごとの控えがキャッシュ。落ちたら2回の突き合わせのまま
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


def test_the_third_reading_fills_in_what_both_passes_dropped():
    fused = [_row(180.8, 186.8, OMIT_ROW)]
    spots = tfu.look_spots(fused, fused, _heard(OMIT_HEARD, 180.8, 0.15))
    third = [_row(175.0, 190.0, "そう、何かやっぱり好きだったから、普通泣いて帰ったら、もう行かないって平気でした。")]

    out, stats = tfu.settle(fused, third, spots)

    assert out[0]["text"] == "そう何かやっぱり好きだったから普通泣いて帰ったらもう行かないって平気でした。"
    assert stats["adopted"] == 1
    assert stats["examples"] == [{"start": 180.8, "before": "だ", "after": "泣いて帰"}]
    assert out[0]["start"] == 180.8 and fused[0]["text"] == OMIT_ROW, "時刻は変えず、渡した行も書き換えない"


def test_the_third_reading_drops_a_character_only_when_it_also_leaves_it_out():
    fused = [_row(176.0, 182.0, DROP_FIRST)]
    spots = tfu.look_spots(fused, [_row(176.0, 182.0, DROP_SECOND)], _heard(DROP_HEARD, 176.0))

    dropped, _ = tfu.settle(fused, [_row(170.0, 190.0, "という感じで、そう、何かやっぱり好きだったから")], spots)
    kept, stats = tfu.settle(fused, [_row(170.0, 190.0, "という感じで、そう何にかやっぱり好きだったから")], spots)

    assert dropped[0]["text"] == "という感じで。そう何かやっぱり好きだったから"
    assert kept[0]["text"] == DROP_FIRST and stats["adopted"] == 0


@pytest.mark.parametrize("third_text", [
    "そう何かやっぱり好きだったから普通だったらもう行かないって平気でした。",   # 3回目も同じ
    "そう何かやっぱり好きだったから普通泣いてがったらもう行かないって平気でした。",  # 認識とも違う
    "全然違う話をしています。",                                                  # 前後の字が無い
])
def test_the_row_stays_unless_the_third_reading_agrees_with_the_recogniser(third_text):
    fused = [_row(180.8, 186.8, OMIT_ROW)]
    spots = tfu.look_spots(fused, fused, _heard(OMIT_HEARD, 180.8, 0.15))

    out, stats = tfu.settle(fused, [_row(175.0, 190.0, third_text)], spots)

    assert out[0]["text"] == OMIT_ROW and stats["adopted"] == 0


def test_the_third_reading_far_from_the_row_is_not_used():
    fused = [_row(180.8, 186.8, OMIT_ROW)]
    spots = tfu.look_spots(fused, fused, _heard(OMIT_HEARD, 180.8, 0.15))
    far = [_row(600.0, 610.0, "そう、何かやっぱり好きだったから、普通泣いて帰ったら、もう行かないって平気でした。")]

    out, _ = tfu.settle(fused, far, spots)

    assert out[0]["text"] == OMIT_ROW


def test_a_spot_at_the_head_of_a_row_takes_no_punctuation_from_the_sentence_before():
    """4分46秒: 2回とも「で、一番盛ん」、認識は「やっぱり一番盛ん」（行の頭の「で」を認識は落とす）。"""
    fused = [_row(284.0, 285.8, "そうですかね。"), _row(285.8, 295.8, "で、一番盛んになったのが")]
    spots = tfu.look_spots(fused, fused, _heard("そうですかねやっぱり一番盛んになったのが", 284.0, 0.3))
    assert [(s["row"], s["cur"], s["want"]) for s in spots] == [(1, "で", "やっぱり")]

    out, _ = tfu.settle(fused, [_row(280.0, 300.0, "そうですかね。で、やっぱり一番盛んになったのが")], spots)

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


def _setup_third_look(tmp_path, monkeypatch, fails=False):
    """1回目・2回目とも「普通だったら」、認識は「普通泣いて帰ったら」。"""
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
        if fails:
            raise gt.TranscriptionError("3回目の起こし（0秒〜）ができません")
        return [_row(0.0, 14.0, "そう、何かやっぱり好きだったから、普通泣いて帰ったら、もう行かないって平気でした。")], ["m3"]
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

    _setup_third_look(tmp_path, monkeypatch, fails=True)
    ctx = PipelineContext(video_path=str(_video(tmp_path)))

    result = asyncio.run(TranscribeWorker().execute(ctx))

    assert result.success
    assert ctx.segments[0]["text"] == OMIT_ROW
    assert any("3回目" in w for w in ctx.warnings)
