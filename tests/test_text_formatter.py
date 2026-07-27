import pytest
import logging
from unittest.mock import patch

from subtitle_engine.text_formatter import (
    remove_fillers,
    _split_at_boundary,
    enforce_line_length,
    _split_by_word_timing,
    format_segments,
    adjust_segment_speeds,
    get_max_chars_from_template,
    get_chars_per_second_from_template,
)

def test_remove_fillers():
    # フィラーが正しく除去されること
    assert remove_fillers("えーと、今日はいい天気です。") == "、今日はいい天気です。"
    assert remove_fillers("あのー、ちょっと待ってください。") == "、待ってください。"
    # フィラーがない場合はそのまま
    assert remove_fillers("こんにちは。") == "こんにちは。"
    # 空文字や前後の空白処理
    assert remove_fillers("  えーと  ") == ""

def test_split_at_boundary():
    # 日本語の境界で正しく分割されるか
    text = "私は昨日、映画を見に行きました。"
    # max_chars = 8
    chunks = _split_at_boundary(text, max_chars=8)
    assert len(chunks) > 1
    # 各チャンクがmax_charsを超えていないこと
    for chunk in chunks:
        assert len(chunk) <= 8

    # 境界がない長文の強制分割
    long_text = "あ" * 30
    chunks = _split_at_boundary(long_text, max_chars=10)
    assert len(chunks) == 3
    assert chunks == ["あ" * 10, "あ" * 10, "あ" * 10]

    # 無効な入力の安全ガード
    assert _split_at_boundary(None) == []
    assert _split_at_boundary("テスト", max_chars=0) == ["テスト"]
    assert _split_at_boundary("テスト", max_chars=-5) == ["テスト"]
    assert _split_at_boundary("テスト", max_chars="invalid") == ["テスト"]

def test_enforce_line_length():
    # max_chars以下ならそのまま
    assert enforce_line_length("こんにちは", max_chars=10) == "こんにちは"
    
    # 境界で改行されること
    text = "私は昨日、映画を見に行きました。"
    enforced = enforce_line_length(text, max_chars=8)
    lines = enforced.split("\n")
    for line in lines:
        assert len(line) <= 8

    # 無効な入力の安全ガード
    assert enforce_line_length(None) == ""
    assert enforce_line_length("テスト", max_chars=0) == "テスト"
    assert enforce_line_length("テスト", max_chars="invalid") == "テスト"

def test_split_by_word_timing():
    parent_seg = {
        "text": "こんにちは世界",
        "start": 1.0,
        "end": 3.0,
    }
    words = [
        {"word": "こんにちは", "start": 1.0, "end": 2.0},
        {"word": "世界", "start": 2.0, "end": 3.0},
    ]

    # 分割されるケース (max_chars = 5)
    chunks = _split_by_word_timing(words, max_chars=5, parent_seg=parent_seg)
    assert len(chunks) == 2
    assert chunks[0]["text"] == "こんにちは"
    assert chunks[0]["start"] == 1.0
    assert chunks[0]["end"] == 2.0
    assert chunks[1]["text"] == "世界"
    assert chunks[1]["start"] == 2.0
    assert chunks[1]["end"] == 3.0

    # 分割されないケース (max_chars = 20)
    chunks = _split_by_word_timing(words, max_chars=20, parent_seg=parent_seg)
    # 分割数が1以下の場合は空リストが返る仕様
    assert chunks == []

    # 無効な入力・エラーハンドリングの検証
    assert _split_by_word_timing(None, 5, parent_seg) == []
    assert _split_by_word_timing(words, 5, None) == []
    assert _split_by_word_timing([], 5, parent_seg) == []

    # wordsの中に不正なオブジェクトやNoneがある場合
    bad_words = [
        {"word": "こんにちは", "start": 1.0, "end": 2.0},
        None,
        {"word": 12345, "start": 2.0, "end": 3.0},  # textがstrでない
        {"word": "", "start": 2.0, "end": 3.0},       # 空文字
        {"word": "世界", "start": "invalid_start", "end": 3.0}, # 不正なスタート
    ]
    chunks = _split_by_word_timing(bad_words, max_chars=5, parent_seg=parent_seg)
    # 有効な "こんにちは" だけでは1チャンクなので、chunksは空になるか、正しくフィルタされる
    assert isinstance(chunks, list)

def test_split_by_word_timing_exception_handling():
    class BadDict(dict):
        def copy(self):
            raise TypeError("Simulated dict copy error")

    parent_seg = BadDict(text="テスト", start=1.0, end=2.0)
    words = [
        {"word": "こんにちは", "start": 1.0, "end": 1.5},
        {"word": "世界", "start": 1.5, "end": 2.0},
    ]

    # loggerをキャプチャしてエラーログが出力されたことを確認
    with patch("subtitle_engine.text_formatter.logger") as mock_logger:
        chunks = _split_by_word_timing(words, max_chars=5, parent_seg=parent_seg)
        assert chunks == []
        # エラーログが記録されていることを確認
        assert mock_logger.error.called

def test_adjust_segment_speeds():
    # CPSが正常な範囲の場合
    normal_segs = [
        {"text": "こんにちは", "start": 1.0, "end": 3.0} # CPS = 5/2 = 2.5
    ]
    adjusted = adjust_segment_speeds(normal_segs, max_cps=4.0)
    assert adjusted[0]["end"] == 3.0

    # CPSが高すぎる場合の延長 (limit_cps = max_cps * 2 = 8.0)
    # 文字数10文字、秒数1秒 (CPS = 10.0) -> limit_cpsの8.0に合わせるため 1.25秒 に延長されるはず
    fast_segs = [
        {"text": "あ" * 10, "start": 1.0, "end": 2.0}
    ]
    adjusted = adjust_segment_speeds(fast_segs, max_cps=4.0)
    # 延長制限 min(next_start - 0.05, end + 2.0) が適用される。次のセグメントはないので end + 5.0 扱いとなり、
    # max_end = min(2.0+5.0-0.05, 2.0+2.0) = 4.0。
    # ターゲットdur = 10 / 8.0 = 1.25。new_end = min(4.0, 1.0 + 1.25) = 2.25。
    assert adjusted[0]["end"] == 2.25

    # 無効な入力の安全ガード
    assert adjust_segment_speeds(None) == []
    assert adjust_segment_speeds([]) == []
    assert adjust_segment_speeds([None]) == []

def test_format_segments_integration():
    # segments 統合テスト
    segments = [
        {"text": "えーと、本日は晴天なり。", "start": 0.0, "end": 2.0},
        {"text": "明日は雨が降るでしょう。", "start": 2.0, "end": 4.0},
    ]
    formatted = format_segments(segments, max_chars=10)
    assert len(formatted) >= 2
    # フィラーが除去されていること
    assert "えーと" not in formatted[0]["text"]
    # 1行の文字数が10文字以下になっていること
    for seg in formatted:
        for line in seg["text"].split("\n"):
            assert len(line) <= 10

def test_template_fallback_exception_handling():
    # template_config のインポート失敗を擬似的に発生させるテスト
    with patch("builtins.__import__", side_effect=ImportError("Simulated import error")):
        assert get_max_chars_from_template() == 15
        assert get_chars_per_second_from_template() == 4.0

    # template_config 自体はインポートできるが、属性取得でエラーになる場合
    with patch("builtins.__import__") as mock_import:
        mock_module = mock_import.return_value
        del mock_module.template_config # AttributeErrorを誘発
        assert get_max_chars_from_template() == 15
        assert get_chars_per_second_from_template() == 4.0
