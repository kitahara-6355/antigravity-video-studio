"""字幕の欠落の検知と、聞き流し語の扱い（2026-10-06 ユーザー指摘）。

指摘: 55秒〜1分50秒はかなり喋っているのに字幕が3つほどしかなく、
その後で急に追いついた。欠落を検知できないまま品質点が 86 点出ていた。

原因は Gemini の起こしが 120 秒チャンクの中で約 30 秒の発話を落とし、
残った1文に 54 秒分の時刻を付けたこと。字幕の無い区間は SmartCut が消す。

守りたい性質:

1. 喋っているのに字幕が無い区間・文字が極端に薄い区間を見つける
2. 欠落があれば品質ゲートは**点数に関わらず**合格させない
3. 文字が薄いチャンクは刻み直して起こし直し、文字が増えた方を採る
4. 文頭の「さて、」「それから、」と、相づちだけの字幕は出さない（内容に掛かる用法は残す）
"""
from __future__ import annotations

import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from subtitle_engine import coverage as cv
from subtitle_engine import text_formatter as tf

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg が無い")


# ------------------------------------------------------------
# 1. 欠落の測定（音声は差し替え。ffmpeg 不要）
# ------------------------------------------------------------

def test_silence_log_becomes_speech_intervals():
    log = ("[silencedetect @ 0x1] silence_start: 2.5\n"
           "[silencedetect @ 0x1] silence_end: 4.0 | silence_duration: 1.5\n"
           "[silencedetect @ 0x1] silence_start: 9\n")

    speech = cv.speech_from_silences(cv.parse_silences(log), 10.0)

    assert speech == [(0.0, 2.5), (4.0, 9.0)]


def test_speech_without_any_subtitle_is_uncovered():
    speech = [(0.0, 60.0)]
    segs = [{"start": 0.0, "end": 20.0, "text": "あ" * 140}]

    rep = cv.measure(segs, speech, 60.0)

    assert rep.uncovered == [(21.0, 60.0)]  # 字幕の後ろ 1 秒は許す
    assert rep.has_gaps


def test_one_sentence_stretched_over_a_minute_is_sparse_even_though_covered():
    """実際の欠落: 1文（約120文字）に 54 秒が付いていた。時間は覆っているが中身が無い。"""
    speech = [(53.4, 107.8)]
    segs = [{"start": 53.4, "end": 107.8, "text": "あ" * 120}]

    rep = cv.measure(segs, speech, 120.0)

    assert rep.uncovered_sec == 0
    assert rep.sparse and rep.has_gaps


def test_normal_conversation_has_no_gaps():
    speech = [(0.0, 30.0), (31.0, 60.0)]
    segs = [{"start": t, "end": t + 3, "text": "あ" * 20} for t in range(0, 60, 3)]

    rep = cv.measure(segs, speech, 60.0)

    assert not rep.has_gaps


def test_short_aizuchi_left_out_is_not_a_gap():
    """相づちを字幕から外した跡（0.5秒未満）は欠落に数えない。"""
    speech = [(0.0, 10.0), (12.0, 12.4), (13.0, 23.0)]
    segs = [{"start": 0.0, "end": 10.0, "text": "あ" * 70}, {"start": 13.0, "end": 23.0, "text": "あ" * 70}]

    assert not cv.measure(segs, speech, 23.0).has_gaps


def test_measure_reads_the_source_timeline_keys():
    speech = [(100.0, 110.0)]
    segs = [{"start": 0.0, "end": 10.0, "sourceStart": 100.0, "sourceEnd": 110.0, "text": "あ" * 70}]

    rep = cv.measure(segs, speech, 120.0, start_key="sourceStart", end_key="sourceEnd")

    assert not rep.has_gaps


# ------------------------------------------------------------
# 2. 品質ゲート: 欠落があれば合格させない
# ------------------------------------------------------------

def _gap_report():
    return cv.measure([{"start": 0.0, "end": 5.0, "text": "あ" * 30}], [(0.0, 60.0)], 60.0)


def test_coverage_plugin_blocks_when_speech_is_missing(tmp_path, monkeypatch):
    from quality_gate_plugins import SubtitleCoverageCheck

    video = tmp_path / "src.mp4"
    video.write_bytes(b"x")
    monkeypatch.setattr(cv, "check_media", lambda media, segs, **kw: _gap_report())
    ctx = SimpleNamespace(segments=[{"start": 0, "end": 5, "text": "a"}], video_path=str(video),
                          preview_path=None)

    result = SubtitleCoverageCheck().analyze(ctx)

    assert result["blocking"] is True
    assert result["deductions"] > 0
    assert any("字幕の欠落" in f for f in result["feedback"])


def test_coverage_plugin_reads_the_preview_sidecar(tmp_path, monkeypatch):
    from quality_gate_plugins import SubtitleCoverageCheck
    from smart_cut_engine import write_subtitle_sidecar

    preview = tmp_path / "preview.mp4"
    preview.write_bytes(b"x")
    write_subtitle_sidecar(preview, [{"start": 0.0, "end": 2.0, "text": "こんにちは"}])
    seen = []

    def fake(media, segs, **kw):
        seen.append((media, segs[0]["text"], kw.get("start_key")))
        return cv.measure(segs, [(0.0, 2.0)], 2.0, **kw)

    monkeypatch.setattr(cv, "check_media", fake)
    ctx = SimpleNamespace(segments=[], video_path=None, preview_path=str(preview))

    result = SubtitleCoverageCheck().analyze(ctx)

    assert seen == [(str(preview), "こんにちは", "start")]
    assert result["blocking"] is False


def test_coverage_plugin_says_it_did_not_check_without_media():
    from quality_gate_plugins import SubtitleCoverageCheck

    result = SubtitleCoverageCheck().analyze(SimpleNamespace(segments=[], video_path=None, preview_path=None))

    assert result["checked"] is False


def test_a_blocking_finding_keeps_the_score_below_the_pass_line(monkeypatch):
    """他の項目が満点でも、欠落があれば 90 点に届かない。"""
    import quality_gate_plugins as qgp

    class Blocker(qgp.QualityCheckPlugin):
        name = "blocker"
        category = "core"

        def analyze(self, ctx, template_config=None):
            return {"deductions": 0, "feedback": [], "blocking": True}

    monkeypatch.setattr(qgp, "PLUGIN_REGISTRY", [Blocker()])

    result = qgp.run_all_plugins(SimpleNamespace(declared_gaps=set()))

    assert result["blocking"] == ["blocker"]


def test_the_gate_worker_caps_the_score_when_something_blocks():
    from agents.workers import quality_gate_worker as qgw

    assert qgw.BLOCKING_SCORE_CAP < 90
    assert "BLOCKING_SCORE_CAP" in open(qgw.__file__, encoding="utf-8").read().split("result = run_all_plugins")[1][:800]


# ------------------------------------------------------------
# 3. 薄いチャンクは刻み直して起こし直す
# ------------------------------------------------------------

@needs_ffmpeg
def test_sparse_chunk_is_retranscribed_in_halves(tmp_path, monkeypatch):
    from subtitle_engine import gemini_transcriber as gt

    clip = tmp_path / "talk.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=20",
                    "-c:a", "aac", str(clip)], check=True)
    calls = []

    def call(client, model, audio, duration):
        calls.append(round(duration))
        if duration > 15:  # 最初の 20 秒チャンク: 1文に全部の時刻を付けて中身を落とす
            return json.dumps([{"start": 0, "end": 20, "text": "あ" * 20}]), model
        return json.dumps([{"start": 0, "end": duration, "text": "い" * 70}]), model

    result = gt.transcribe(clip, client=object(), model="m", chunk_sec=20, parallel=1, call=call, backoff=0)

    assert calls == [20, 10, 10]
    assert result.rechecked == [{"start": 0.0, "chars_before": 20, "chars_after": 140, "adopted": True}]
    assert "".join(s["text"] for s in result.segments) == "い" * 140
    assert result.coverage is not None and not result.coverage["has_gaps"]


def test_chunks_are_short_enough_not_to_drop_speech():
    from subtitle_engine import gemini_transcriber as gt

    assert gt.CHUNK_SEC <= 30


def test_the_cache_of_the_old_chunking_is_not_reused():
    from agents.workers.transcribe_worker import _gemini_checkpoint

    assert _gemini_checkpoint("work/_whisper_abc.jsonl") != "work/_gemini_abc.jsonl"


# ------------------------------------------------------------
# 4. 聞くだけで足りる言葉
# ------------------------------------------------------------

LEAD = ["さて", "それから", "で", "まあ", "じゃあ", "あ"]
STANDALONE = ["はい", "うん", "へえ", "なるほど"]


@pytest.mark.parametrize("text,expected", [
    ("さて、次の話題です。", "次の話題です。"),
    ("で、今ね、公開されている", "今ね、公開されている"),
    ("はい。それから、もう一つ。", "はい。もう一つ。"),
    ("それから3年後に", "それから3年後に"),       # 内容に掛かる用法は残す
    ("あ、強烈な。", "強烈な。"),
    ("、本日は晴天です。", "本日は晴天です。"),     # フィラーを外した跡の「、」
    ("まあ、", "まあ、"),                            # 空になるなら外さない
])
def test_lead_words_are_dropped_only_at_the_head_before_a_comma(text, expected):
    assert tf.strip_lead_words(text, LEAD) == expected


@pytest.mark.parametrize("text,expected", [
    ("はい。", True),
    ("はい、はい。", True),
    ("うん、なるほど。", True),
    ("へえ", True),
    ("はい、ありがとうございます。", False),
    ("なるほどですね、それは", False),
])
def test_aizuchi_only_captions_are_omittable(text, expected):
    assert tf.is_standalone_omittable(text, STANDALONE) is expected


def test_the_word_lists_live_in_the_template_rules():
    from template_config import template_config

    rules = template_config.get_subtitle_rules()
    assert "それから" in rules["omit_lead_words"]
    assert "はい" in rules["omit_standalone_words"]


def test_format_segments_drops_lead_words():
    segs = [{"text": "さて、今日のゲストです。", "start": 0.0, "end": 2.0}]

    assert tf.format_segments(segs, 15)[0]["text"] == "今日のゲストです。"


def test_burned_srt_skips_aizuchi_only_captions(tmp_path, monkeypatch):
    """相づちだけの字幕は焼き込まない（音声とカットは残す）。"""
    import pathlib as _pl
    import smart_cut_engine as sce

    written = {}
    original = _pl.Path.write_text

    def spy(self, data, *a, **k):
        if self.name == "_temp_subtitles.srt":
            written["srt"] = data
            raise RuntimeError("ここで止める")
        return original(self, data, *a, **k)

    monkeypatch.setattr(_pl.Path, "write_text", spy)
    segs = [{"start": 0.0, "end": 1.0, "text": "はい。"},
            {"start": 1.0, "end": 3.0, "text": "書道の魅力です。"}]
    try:
        sce._burn_subtitles_ffmpeg(str(tmp_path / "in.mp4"), segs, str(tmp_path / "out.mp4"), object())
    except Exception:
        pass

    assert "はい。" not in written["srt"]
    assert "書道の魅力です。" in written["srt"]


# ------------------------------------------------------------
# 5. 書いている場面（音はあるが発話ではない）は欠落に数えない
# ------------------------------------------------------------

def test_verified_quiet_windows_are_not_gaps():
    """30:00〜31:00 は書道を書いている場面。2回起こしても文字が出ないので除外する。"""
    speech = [(0.0, 60.0)]
    segs = [{"start": 0.0, "end": 30.0, "text": "あ" * 210}]

    assert cv.measure(segs, speech, 60.0).has_gaps
    rep = cv.measure(segs, speech, 60.0, exclude=[(30.0, 60.0)])
    assert not rep.has_gaps
    assert rep.excluded == [(30.0, 60.0)]


def test_source_windows_map_onto_the_cut_timeline():
    ranges = [(10.0, 20.0), (50.0, 70.0)]

    assert cv.map_to_output([(15.0, 55.0)], ranges) == [(5.0, 10.0), (10.0, 15.0)]


@needs_ffmpeg
def test_a_chunk_that_stays_thin_after_retry_is_marked_quiet(tmp_path):
    from subtitle_engine import gemini_transcriber as gt

    clip = tmp_path / "writing.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=20",
                    "-c:a", "aac", str(clip)], check=True)

    def call(client, model, audio, duration):
        return json.dumps([{"start": 0, "end": 1, "text": "うん"}]), model

    result = gt.transcribe(clip, client=object(), model="m", chunk_sec=20, parallel=1, call=call, backoff=0)

    assert result.quiet == [(0.0, 20.0)]
    assert not result.coverage["has_gaps"]


def test_quiet_windows_survive_the_cache(tmp_path):
    from subtitle_engine import gemini_transcriber as gt

    ckpt = tmp_path / "_gemini_c30_x.jsonl"
    gt.write_checkpoint([{"start": 0, "end": 1, "text": "a"}], ckpt, meta={"quiet": [[1800.0, 1830.0]]})

    assert gt.read_meta(ckpt)["quiet"] == [[1800.0, 1830.0]]


def test_gate_excludes_quiet_windows_and_still_reports_them(tmp_path, monkeypatch):
    from quality_gate_plugins import SubtitleCoverageCheck

    video = tmp_path / "src.mp4"
    video.write_bytes(b"x")
    monkeypatch.setattr(cv, "speech_intervals", lambda media: ([(0.0, 60.0)], 60.0))
    ctx = SimpleNamespace(segments=[{"start": 0, "end": 30, "sourceStart": 0, "sourceEnd": 30, "text": "あ" * 210}],
                          video_path=str(video), preview_path=None, verified_quiet=[(30.0, 60.0)])

    result = SubtitleCoverageCheck().analyze(ctx)

    assert result["blocking"] is False
    assert any("人が確認" in f for f in result["feedback"])


# ------------------------------------------------------------
# 6. 文字の薄さは文字起こしの段階でだけ測る（整形後は減るのが正しい）
# ------------------------------------------------------------

def test_formatted_subtitles_are_checked_for_time_only():
    """フィラー・相づちを外した字幕は文字が減る。時間で覆っていれば欠落ではない。"""
    speech = [(0.0, 30.0)]
    segs = [{"start": 0.0, "end": 30.0, "text": "あ" * 30}]

    assert cv.measure(segs, speech, 30.0).sparse
    assert not cv.measure(segs, speech, 30.0, check_sparse=False).has_gaps


def test_gate_blocks_on_gaps_found_at_transcription(tmp_path, monkeypatch):
    from quality_gate_plugins import SubtitleCoverageCheck

    video = tmp_path / "src.mp4"
    video.write_bytes(b"x")
    monkeypatch.setattr(cv, "speech_intervals", lambda media: ([(0.0, 30.0)], 30.0))
    ctx = SimpleNamespace(segments=[{"start": 0, "end": 30, "sourceStart": 0, "sourceEnd": 30, "text": "あ" * 30}],
                          video_path=str(video), preview_path=None, verified_quiet=[],
                          transcript_coverage={"has_gaps": True, "uncovered_sec": 0.0,
                                               "sparse": [{"start": 60.0}]})

    result = SubtitleCoverageCheck().analyze(ctx)

    assert result["blocking"] is True
    assert any("文字起こし" in f and "1:00" in f for f in result["feedback"])
