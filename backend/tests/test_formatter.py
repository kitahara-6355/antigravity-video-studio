import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock

# NumPyやfaster_whisper関連のインポートによるエラーを防ぐため、事前にsys.modulesにモックを登録する
sys.modules["faster_whisper"] = MagicMock()
sys.modules["subtitle_engine.whisper_transcriber"] = MagicMock()
sys.modules["subtitle_engine.ai_proofreader"] = MagicMock()

# backend ディレクトリを sys.path に追加して直接インポートできるようにする
_backend_dir = str(Path(__file__).resolve().parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from subtitle_engine.formatter import SubtitleFormatter


def test_to_vtt_success():
    subtitles = [
        {"start": 1.23, "end": 4.56, "text": "Hello World"},
        {"start": 3605.12, "end": 3610.99, "text": "One hour later"}
    ]
    vtt_output = SubtitleFormatter.to_vtt(subtitles)
    assert "WEBVTT\n\n" in vtt_output
    assert "1\n00:00:01.230 --> 00:00:04.560\nHello World\n\n" in vtt_output
    assert "2\n01:00:05.120 --> 01:00:10.990\nOne hour later\n\n" in vtt_output


def test_to_srt_success():
    subtitles = [
        {"start": 1.23, "end": 4.56, "text": "Hello World"},
        {"start": 3605.12, "end": 3610.99, "text": "One hour later"}
    ]
    srt_output = SubtitleFormatter.to_srt(subtitles)
    assert "1\n00:00:01,230 --> 00:00:04,560\nHello World\n\n" in srt_output
    assert "2\n01:00:05,120 --> 01:00:10,990\nOne hour later\n\n" in srt_output


def test_format_time_vtt_edge_cases():
    assert SubtitleFormatter._format_time_vtt(0.0) == "00:00:00.000"
    assert SubtitleFormatter._format_time_vtt(0.001) == "00:00:00.001"
    assert SubtitleFormatter._format_time_vtt(59.999) == "00:00:59.999"
    assert SubtitleFormatter._format_time_vtt(60.0) == "00:01:00.000"
    assert SubtitleFormatter._format_time_vtt(3600.0) == "01:00:00.000"
    assert SubtitleFormatter._format_time_vtt(360000.0) == "100:00:00.000"


def test_format_time_srt_edge_cases():
    assert SubtitleFormatter._format_time_srt(0.0) == "00:00:00,000"
    assert SubtitleFormatter._format_time_srt(0.001) == "00:00:00,001"
    assert SubtitleFormatter._format_time_srt(59.999) == "00:00:59,999"
    assert SubtitleFormatter._format_time_srt(60.0) == "00:01:00,000"
    assert SubtitleFormatter._format_time_srt(3600.0) == "01:00:00,000"
    assert SubtitleFormatter._format_time_srt(360000.0) == "100:00:00,000"


def test_empty_subtitles():
    assert SubtitleFormatter.to_vtt([]) == "WEBVTT\n\n"
    assert SubtitleFormatter.to_srt([]) == ""


def test_missing_keys_raises_key_error():
    subtitles = [{"start": 1.0, "end": 2.0}]
    with pytest.raises(KeyError):
        SubtitleFormatter.to_vtt(subtitles)
    with pytest.raises(KeyError):
        SubtitleFormatter.to_srt(subtitles)


def test_float_precision_rounding():
    assert SubtitleFormatter._format_time_vtt(0.0004) == "00:00:00.000"
    assert SubtitleFormatter._format_time_vtt(0.0006) == "00:00:00.001"


def test_format_time_vtt_negative_and_extreme():
    # 負の時間の挙動確認（現在の実装におけるフォーマット挙動）
    assert SubtitleFormatter._format_time_vtt(-1.5) == "-1:59:58.500"

    # 超巨大な時間
    assert SubtitleFormatter._format_time_vtt(3599999.999) == "999:59:59.999"


def test_invalid_types_raises_type_error():
    # startやendが文字列の場合の挙動
    subtitles = [{"start": "1.0", "end": 2.0, "text": "Test"}]
    with pytest.raises(TypeError):
        SubtitleFormatter.to_vtt(subtitles)

    # startやendがNoneの場合の挙動
    subtitles = [{"start": 1.0, "end": None, "text": "Test"}]
    with pytest.raises(TypeError):
        SubtitleFormatter.to_srt(subtitles)


def test_to_vtt_and_srt_special_characters():
    # 改行や特殊文字を含むテキストのフォーマット
    subtitles = [
        {"start": 1.0, "end": 2.0, "text": "Hello\nWorld!"},
        {"start": 2.5, "end": 3.5, "text": "Special symbols: & < > \" '"}
    ]
    vtt = SubtitleFormatter.to_vtt(subtitles)
    assert "1\n00:00:01.000 --> 00:00:02.000\nHello\nWorld!\n\n" in vtt
    assert "2\n00:00:02.500 --> 00:00:03.500\nSpecial symbols: & < > \" '\n\n" in vtt

    srt = SubtitleFormatter.to_srt(subtitles)
    assert "1\n00:00:01,000 --> 00:00:02,000\nHello\nWorld!\n\n" in srt
    assert "2\n00:00:02,500 --> 00:00:03,500\nSpecial symbols: & < > \" '\n\n" in srt


def test_validate_subtitles_extra_edge_cases():
    # subtitles が None
    with pytest.raises(TypeError):
        SubtitleFormatter.to_vtt(None)

    # subtitles がリストではない
    with pytest.raises(TypeError):
        SubtitleFormatter.to_vtt("not a list")

    # subtitles の要素が辞書ではない
    with pytest.raises(TypeError):
        SubtitleFormatter.to_vtt(["not a dict"])

    # start が None
    with pytest.raises(TypeError):
        SubtitleFormatter.to_vtt([{"start": None, "end": 1.0, "text": "test"}])

    # start が boolean (boolはintのサブクラスなので明示的チェックが必要)
    with pytest.raises(TypeError):
        SubtitleFormatter.to_vtt([{"start": True, "end": 1.0, "text": "test"}])

    # end が boolean
    with pytest.raises(TypeError):
        SubtitleFormatter.to_vtt([{"start": 1.0, "end": False, "text": "test"}])

    # start が負の値
    with pytest.raises(ValueError):
        SubtitleFormatter.to_vtt([{"start": -1.0, "end": 1.0, "text": "test"}])

    # end が負の値
    with pytest.raises(ValueError):
        SubtitleFormatter.to_vtt([{"start": 1.0, "end": -1.0, "text": "test"}])

    # start > end
    with pytest.raises(ValueError):
        SubtitleFormatter.to_vtt([{"start": 2.0, "end": 1.0, "text": "test"}])

    # text が None
    with pytest.raises(TypeError):
        SubtitleFormatter.to_vtt([{"start": 1.0, "end": 2.0, "text": None}])

    # text が文字列ではない
    with pytest.raises(TypeError):
        SubtitleFormatter.to_vtt([{"start": 1.0, "end": 2.0, "text": 12345}])
