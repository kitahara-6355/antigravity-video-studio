"""文字起こしを2回して、食い違いを手元の音声認識で決める（2026-10-06）。

起こしの区切りを変えて起こし直すと、Gemini の聞き違いが毎回別の所に出た
（26回目の冒頭で「書家の北原」が「諸岡の北原」、「書に出会った」が「よそに出会った」）。
温度 0 でも区切りが変われば渡す音声が変わる。どちらの回の字が正しいかは運だった。

守りたい性質:

1. 2回目と手元の音声認識が同じ字を聞き、1回目だけが違う所は 2回目の字にする（2対1）
2. 認識が1回目と同じ・どちらとも違う所は 1回目のまま
3. 行の分け方と時刻は 1回目のまま（字だけ直す）
4. 1回目の字を2字以上消さない・言いよどみと数字は触らない（認識が落としやすい所）
5. 2回目は区切りの位置をずらして起こす（1回目の区切りの前後が2回目では区切りの中ほどになる）
6. 認識が使えない・2回目が落ちたら 1回目のまま進む
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


def test_more_than_one_character_of_the_first_pass_is_never_dropped():
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
