import pytest
from pathlib import Path

from backend.video_pipeline.subtitle_generator import SubtitleGenerator, SubtitleResult
from backend.video_pipeline.transcription_service import TranscriptResult, TranscriptSegment

def test_init_invalid_max_chars():
    """max_chars_per_line が 1 未満の場合に ValueError が発生することを確認するテスト。"""
    with pytest.raises(ValueError, match="max_chars_per_line must be at least 1"):
        SubtitleGenerator(max_chars_per_line=0)
    with pytest.raises(ValueError, match="max_chars_per_line must be at least 1"):
        SubtitleGenerator(max_chars_per_line=-5)

def test_generate_srt_none_transcript(tmp_path):
    """transcript が None の場合に ValueError が発生することを確認するテスト。"""
    generator = SubtitleGenerator(max_chars_per_line=13)
    output_file = tmp_path / "output.srt"
    with pytest.raises(ValueError, match="transcript cannot be None"):
        generator.generate_srt(None, str(output_file))

def test_generate_srt_success(tmp_path):
    """正常な TranscriptResult から正しく SRT が生成されることを確認するテスト。"""
    generator = SubtitleGenerator(max_chars_per_line=13)
    output_file = tmp_path / "output.srt"
    
    sample_transcript = TranscriptResult(
        success=True,
        segments=[
            TranscriptSegment(start=1.5, end=4.5, text="こんにちは、今日は良い天気ですね。"),
        ],
        language="ja",
        model_used="test_model",
        duration_seconds=5.0,
    )
    
    result = generator.generate_srt(sample_transcript, str(output_file))
    
    assert result.success is True
    assert result.entry_count == 1
    assert Path(result.output_path).exists()
    
    with open(result.output_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # タイムコードや自動改行のチェック
    # "こんにちは、今日は良い天気ですね。" -> max_chars=13 で改行されるはず
    # 、で改行されると「こんにちは、\n今日は良い天気ですね。」
    assert "00:00:01,500 --> 00:00:04,500" in content
    assert "こんにちは、\n今日は良い天気ですね。" in content

def test_generate_srt_empty_segments(tmp_path):
    """segments が空の場合に失敗結果が返ることを確認するテスト。"""
    generator = SubtitleGenerator(max_chars_per_line=13)
    output_file = tmp_path / "output.srt"
    
    sample_transcript = TranscriptResult(
        success=True,
        segments=[],
        language="ja",
        model_used="test_model",
        duration_seconds=0.0,
    )
    
    result = generator.generate_srt(sample_transcript, str(output_file))
    
    assert result.success is False
    assert "文字起こしセグメントが空です" in result.issues


@pytest.mark.parametrize(
    "segments, max_chars, expected_success, expected_entries, expected_texts",
    [
        # 正常系1: 改行なし
        (
            [TranscriptSegment(start=1.0, end=3.0, text="こんにちは")],
            13, True, 1, ["こんにちは"]
        ),
        # 正常系2: 改行あり（句読点による適切な分割）
        (
            [TranscriptSegment(start=1.0, end=3.0, text="こんにちは、今日は良い天気ですね。")],
            13, True, 1, ["こんにちは、", "今日は良い天気ですね。"]
        ),
        # 境界値1: ちょうど13文字
        (
            [TranscriptSegment(start=1.0, end=3.0, text="あいうえおかきくけこさしす")],
            13, True, 1, ["あいうえおかきくけこさしす"]
        ),
        # 境界値2: ちょうど14文字
        (
            [TranscriptSegment(start=1.0, end=3.0, text="あいうえおかきくけこさしすせ")],
            13, True, 1, ["あいうえおかきくけこさしす\nせ"]
        ),
        # 境界値3: タイムコードが0.0
        (
            [TranscriptSegment(start=0.0, end=0.0, text="テスト")],
            13, True, 1, ["00:00:00,000 --> 00:00:00,000\nテスト"]
        ),
        # 異常系1: 空テキスト（すべてスキップされエントリ数は0）
        (
            [TranscriptSegment(start=1.0, end=3.0, text=""), TranscriptSegment(start=3.0, end=5.0, text="   ")],
            13, True, 0, []
        ),
        # 異常系2: タイムコードが負の値
        (
            [TranscriptSegment(start=-5.0, end=-2.0, text="負のテスト")],
            13, True, 1, ["00:00:00,000 --> 00:00:00,000\n負のテスト"]
        ),
    ]
)
def test_generate_srt_parametrized(tmp_path, segments, max_chars, expected_success, expected_entries, expected_texts):
    generator = SubtitleGenerator(max_chars_per_line=max_chars)
    output_file = tmp_path / "output_parametrized.srt"
    
    transcript = TranscriptResult(
        success=True,
        segments=segments,
        language="ja",
        model_used="test_model",
        duration_seconds=5.0,
    )
    
    result = generator.generate_srt(transcript, str(output_file))
    
    assert result.success == expected_success
    assert result.entry_count == expected_entries
    
    if expected_success and expected_entries > 0:
        assert output_file.exists()
        content = output_file.read_text(encoding="utf-8")
        for text in expected_texts:
            assert text in content


def test_long_text_50_chars_split(tmp_path):
    """50文字の長文テキストが13文字以下で複数行に分割されることを確認するテスト。"""
    generator = SubtitleGenerator(max_chars_per_line=13)
    output_file = tmp_path / "long_text.srt"
    
    long_text = "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをんあいうえお"
    assert len(long_text) >= 50
    
    sample_transcript = TranscriptResult(
        success=True,
        segments=[
            TranscriptSegment(start=1.0, end=5.0, text=long_text),
        ],
        language="ja",
        model_used="test_model",
        duration_seconds=5.0,
    )
    
    result = generator.generate_srt(sample_transcript, str(output_file))
    assert result.success is True
    assert result.entry_count == 1
    
    content = output_file.read_text(encoding="utf-8")
    lines = content.strip().splitlines()
    
    # タイムコード行とインデックス行を除いたテキスト行を抽出
    # 形式は:
    # 1
    # 00:00:01,000 --> 00:00:05,000
    # テキスト1
    # テキスト2
    text_lines = lines[2:]
    
    assert len(text_lines) > 1  # 複数行に分割されていること
    for line in text_lines:
        assert len(line) <= 13  # 各行が13文字以下であること


from backend.video_pipeline.nhk_subtitle_scorer import NHKSubtitleScorer

def test_nhk_subtitle_scoring_above_70(tmp_path):
    """生成されたSRTファイルを nhk_subtitle_scorer でスコアリングし、70点以上であることを確認するテスト。"""
    generator = SubtitleGenerator(max_chars_per_line=13)
    output_file = tmp_path / "nhk_test.srt"
    
    sample_transcript = TranscriptResult(
        success=True,
        segments=[
            TranscriptSegment(start=1.5, end=4.5, text="こんにちは、今日は良い天気ですね。"),
            TranscriptSegment(start=5.0, end=8.0, text="字幕の品質を検証しています。"),
            TranscriptSegment(start=9.0, end=12.0, text="テストは正常に動作する見込みです。"),
        ],
        language="ja",
        model_used="test_model",
        duration_seconds=15.0,
    )
    
    result = generator.generate_srt(sample_transcript, str(output_file))
    assert result.success is True
    assert output_file.exists()
    
    scorer = NHKSubtitleScorer()
    report = scorer.score(str(output_file))
    
    print(f"NHK Subtitle Scorer Total Score: {report.total_score}")
    assert report.total_score >= 70


@pytest.mark.parametrize(
    "timecode, expected",
    [
        ("00:00:00,000", True),
        ("01:23:45,678", True),
        ("99:59:59,999", True),
        ("0:00:00,000", False),
        ("00:00:00.000", False),
        ("00:00:00,00", False),
        ("00:00:0,000", False),
        ("abc", False),
    ]
)
def test_validate_timecode_format(timecode, expected):
    generator = SubtitleGenerator()
    assert generator.validate_timecode_format(timecode) == expected
