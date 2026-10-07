"""backend/subtitle_engine/gemini_transcriber.py — Gemini 音声入力の文字起こし（R2.5-C4）。

守りたい性質:

1. 応答の時刻をチャンクに収め、重なりを詰めて、絶対時刻に直す
2. 1チャンクでも起こせなければ全体を失敗にする（黙って抜けると SmartCut が動画から消す）
3. 出力の行の形が Whisper の経路と同じ

Gemini には接続しない（呼び出しは差し替える）。
"""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from subtitle_engine import gemini_transcriber as gt

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg が無い")


def test_parse_shifts_to_absolute_time_and_keeps_the_whisper_shape():
    text = json.dumps([{"start": 1.0, "end": 2.5, "text": "こんにちは"}])

    segs = gt.parse_segments(text, offset=120.0, duration=120.0)

    assert segs == [{"start": 121.0, "end": 122.5, "text": "こんにちは",
                     "sourceStart": 121.0, "sourceEnd": 122.5, "words": []}]


def test_parse_clamps_times_that_run_past_the_chunk():
    """Flash 系は長い音声で時刻が伸びる。チャンクの外に字幕を置かない。"""
    text = json.dumps([{"start": 118.0, "end": 130.0, "text": "a"},
                       {"start": 140.0, "end": 150.0, "text": "b"}])

    segs = gt.parse_segments(text, offset=0.0, duration=120.0)

    assert all(s["end"] <= 120.0 for s in segs)
    assert segs[0]["start"] == 118.0


def test_parse_sorts_and_trims_overlaps():
    text = json.dumps([{"start": 5.0, "end": 9.0, "text": "後"},
                       {"start": 0.0, "end": 6.0, "text": "前"}])

    segs = gt.parse_segments(text, offset=0.0, duration=60.0)

    assert [s["text"] for s in segs] == ["前", "後"]
    assert segs[0]["end"] <= segs[1]["start"]


def test_parse_drops_empty_and_timeless_items():
    text = json.dumps([{"start": 0, "end": 1, "text": " "},
                       {"start": "x", "end": 2, "text": "時刻なし"},
                       {"text": "時刻なし2"},
                       "文字列",
                       {"start": 2, "end": 3, "text": "残る"}])

    assert [s["text"] for s in gt.parse_segments(text, 0.0, 60.0)] == ["残る"]


@pytest.mark.parametrize("wrapped", [
    '```json\n[{"start": 0, "end": 1, "text": "a"}]\n```',
    'はい。\n[{"start": 0, "end": 1, "text": "a"}]',
    '{"segments": [{"start": 0, "end": 1, "text": "a"}]}',
])
def test_parse_reads_wrapped_json(wrapped):
    assert gt.parse_segments(wrapped, 0.0, 10.0)[0]["text"] == "a"


def test_parse_refuses_a_reply_that_is_not_json():
    with pytest.raises(ValueError):
        gt.parse_segments("申し訳ありませんが", 0.0, 10.0)


@pytest.fixture
def clip(tmp_path):
    path = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
                    "-c:a", "aac", str(path)], check=True)
    return path


@needs_ffmpeg
def test_transcribe_splits_into_chunks_and_offsets_each(clip):
    seen = []

    def call(client, model, audio, duration):
        seen.append(round(duration, 1))
        return json.dumps([{"start": 0.5, "end": 1.5, "text": f"c{len(seen)}"}]), model

    result = gt.transcribe(clip, client=object(), model="m", chunk_sec=2, parallel=1, call=call, backoff=0)

    assert result.chunks == 3
    assert [s["start"] for s in result.segments] == [0.5, 2.5, 4.5]
    assert result.models_used == ["m"]


@needs_ffmpeg
def test_one_failed_chunk_fails_the_whole_transcription(clip):
    """黙って抜けた区間は SmartCut が動画から消す。部分成功を成功と呼ばない。"""
    def call(client, model, audio, duration):
        if audio.name == "chunk_001.mp3":
            raise OSError("503")
        return json.dumps([{"start": 0, "end": 1, "text": "a"}]), model

    with pytest.raises(gt.TranscriptionError) as exc:
        gt.transcribe(clip, client=object(), model="m", chunk_sec=2, parallel=1, call=call, backoff=0)
    assert "チャンク 2/3" in str(exc.value)


@needs_ffmpeg
def test_a_flaky_chunk_is_retried(clip):
    calls = {"n": 0}

    def call(client, model, audio, duration):
        calls["n"] += 1
        if calls["n"] == 1:
            return "壊れた応答", model
        return json.dumps([{"start": 0, "end": 1, "text": "a"}]), model

    result = gt.transcribe(clip, client=object(), model="m", chunk_sec=10, parallel=1, call=call, backoff=0)

    assert calls["n"] == 2
    assert len(result.segments) == 1


def test_the_transcription_task_is_on_a_free_tier():
    """モデルは段から引く。昇格先（pro・課金）に既定で乗せない。"""
    from backend import model_policy

    decision = model_policy.resolve(gt.TASK)
    assert decision.source == "task_mapping"
    assert decision.tier != "pro"


@needs_ffmpeg
def test_a_budget_stop_is_not_retried(clip):
    """予算切れ（cost_guard）は再試行しても通らない。そのまま上に返す。"""
    from backend.cost_guard import CostLimitExceeded
    calls = {"n": 0}

    def call(client, model, audio, duration):
        calls["n"] += 1
        raise CostLimitExceeded("残高なし")

    with pytest.raises(CostLimitExceeded):
        gt.transcribe(clip, client=object(), model="m", chunk_sec=10, parallel=1, call=call, backoff=0)
    assert calls["n"] == 1


# --- 途中で落ちたら、起こし終えたチャンクから続ける（2026-10-07）----------------------
# 2回目の起こしが 104 本中 71 本目で無料枠の1日の上限（500回）に当たり、起こし終えた
# 70 本分が消えた。枠は翌日まで戻らないので、やり直すたびに同じ所で落ちうる。


def _named(client, model, audio, duration):
    return json.dumps([{"start": 0, "end": 1, "text": audio.stem}]), model


@needs_ffmpeg
def test_a_transcription_cut_short_resumes_from_the_chunks_already_done(clip, tmp_path):
    journal = tmp_path / "tx.chunks.journal"
    seen = []

    def quota_out(client, model, audio, duration):
        seen.append(audio.name)
        if audio.name == "chunk_001.mp3":
            raise OSError("429 RESOURCE_EXHAUSTED")
        return _named(client, model, audio, duration)

    with pytest.raises(gt.TranscriptionError):
        gt.transcribe(clip, client=object(), model="m", chunk_sec=2, parallel=1, call=quota_out,
                      backoff=0, journal=journal)
    seen.clear()

    def ok(client, model, audio, duration):
        seen.append(audio.name)
        return _named(client, model, audio, duration)

    result = gt.transcribe(clip, client=object(), model="m", chunk_sec=2, parallel=1, call=ok,
                           backoff=0, journal=journal)

    assert seen == ["chunk_001.mp3"], "起こし終えた1本目と3本目は呼び直さない"
    assert [s["text"] for s in result.segments] == ["chunk_000", "chunk_001", "chunk_002"]


@needs_ffmpeg
def test_chunks_from_a_different_cut_are_not_reused(clip, tmp_path):
    journal = tmp_path / "tx.chunks.journal"
    gt.transcribe(clip, client=object(), model="m", chunk_sec=2, parallel=1, call=_named,
                  backoff=0, journal=journal)
    seen = []

    def ok(client, model, audio, duration):
        seen.append(audio.name)
        return _named(client, model, audio, duration)

    gt.transcribe(clip, client=object(), model="m", chunk_sec=2, parallel=1, call=ok,
                  backoff=0, journal=journal, first_chunk_sec=1)

    # 区切りが 1秒・3秒になる。頭のチャンクの長さが違うので使い回さない
    assert "chunk_000.mp3" in seen


def test_a_torn_last_line_of_the_chunk_notes_is_ignored(tmp_path):
    """控えの書き込み中に止められると、最後の行が途中で切れる。"""
    journal = tmp_path / "tx.chunks.journal"
    journal.write_text(json.dumps({"offset": 0.0, "duration": 2.0, "model": "m",
                                   "segments": [{"start": 0.0, "end": 1.0, "text": "a"}]},
                                  ensure_ascii=False) + "\n" + '{"offset": 2.0, "dur', encoding="utf-8")

    done = gt.read_journal(journal)

    assert list(done) == [(0.0, 2.0)]
