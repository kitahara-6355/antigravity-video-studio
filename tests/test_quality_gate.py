import os
import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

# パス設定 (conftestで設定されるが、安全のため)
tests_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(tests_dir)
backend_dir = os.path.join(project_root, "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from video_pipeline.quality_gate import (
    QualityGate,
    QualityConfig,
    QualityReport,
    SubtitleScore,
    VisualScore,
    AudioScore,
    EncodingScore,
)

FIXTURE_DIR = Path(backend_dir) / "tests" / "fixtures" / "raw_videos"
TEST_SHORT = FIXTURE_DIR / "test_short_15s.mp4"
TEST_MEDIUM = FIXTURE_DIR / "test_medium_30s.mp4"
TEST_LONG = FIXTURE_DIR / "test_long_60s.mp4"

PERFECT_SRT = Path(backend_dir) / "tests" / "fixtures" / "subtitles" / "perfect_score.srt"


def save_quality_snapshot(case_name, scores):
    """品質スコアをスナップショットファイルとして保存する (regression_baseline用)"""
    snapshot_path = Path(project_root) / "tests" / "quality_score_snapshot.json"
    data = {}
    if snapshot_path.exists():
        try:
            data = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    data[case_name] = scores
    snapshot_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. 正常系: 実動画3本の評価（字幕なし）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@pytest.mark.slow
@pytest.mark.parametrize(
    "video_path",
    [TEST_SHORT, TEST_MEDIUM, TEST_LONG]
)
def test_evaluate_real_videos(video_path):
    """3本の実動画の評価テスト。品質スコアを算出し、結果が合格基準を満たすことを確認する。"""
    if not video_path.exists():
        pytest.skip(f"テスト用の実動画ファイルが存在しません: {video_path}")

    gate = QualityGate()
    report = gate.evaluate(str(video_path))

    assert isinstance(report, QualityReport)
    assert report.video_path == str(video_path)
    assert report.total_score >= 80.0  # 品質閾値: total_score >= 80
    assert report.passed is True

    # 各品質軸(audio/visual/subtitle/encoding)の個別スコアが存在することを確認
    assert report.visual_score is not None
    assert report.audio_score is not None
    assert report.encoding_score is not None
    # 字幕なし評価なので、subtitle_score は None であるべき
    assert report.subtitle_score is None

    # 各品質スコアの重み適用後の寄与度を算出してアサートする
    total_weight = (
        gate.config.visual_weight
        + (gate.config.audio_weight if report.audio_score.available else 0.0)
        + (gate.config.encoding_weight if report.encoding_score.available else 0.0)
    )

    visual_contrib = report.visual_score.total * gate.config.visual_weight / total_weight
    audio_contrib = report.audio_score.total * gate.config.audio_weight / total_weight if report.audio_score.available else 0.0
    encoding_contrib = report.encoding_score.total * gate.config.encoding_weight / total_weight if report.encoding_score.available else 0.0

    # 品質レポートの各軸スコアを個別に assert (audio >= 15, visual >= 25等)
    # 字幕なし評価（合計重み 0.70）の場合、満点は visual: 42.8点, audio: 28.5点, encoding: 28.5点
    assert visual_contrib >= 25.0, f"visual_contrib ({visual_contrib:.1f}) < 25.0"
    if report.audio_score.available:
        assert audio_contrib >= 15.0, f"audio_contrib ({audio_contrib:.1f}) < 15.0"
    if report.encoding_score.available:
        assert encoding_contrib >= 15.0, f"encoding_contrib ({encoding_contrib:.1f}) < 15.0"

    # 品質スコアのスナップショット保存（regression_baseline用）
    save_quality_snapshot(video_path.name, {
        "total_score": report.total_score,
        "visual_score": report.visual_score.total,
        "visual_contrib": round(visual_contrib, 2),
        "audio_score": report.audio_score.total if report.audio_score.available else None,
        "audio_contrib": round(audio_contrib, 2) if report.audio_score.available else None,
        "encoding_score": report.encoding_score.total if report.encoding_score.available else None,
        "encoding_contrib": round(encoding_contrib, 2) if report.encoding_score.available else None,
        "subtitle_score": None,
        "subtitle_contrib": 0.0
    })


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. 字幕付き評価: 動画+perfect_score.srtで字幕品質も含む総合スコア
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@pytest.mark.slow
def test_evaluate_with_subtitles():
    """動画と perfect_score.srt 字幕ファイルによる字幕品質を含む総合スコアの評価"""
    if not TEST_SHORT.exists():
        pytest.skip(f"テスト用の実動画ファイルが存在しません: {TEST_SHORT}")
    if not PERFECT_SRT.exists():
        pytest.skip(f"完璧な字幕ファイルが存在しません: {PERFECT_SRT}")

    gate = QualityGate()
    report = gate.evaluate(str(TEST_SHORT), subtitle_path=str(PERFECT_SRT))

    assert isinstance(report, QualityReport)
    assert report.total_score >= 80.0  # 品質スコア80点以上
    assert report.passed is True

    assert report.subtitle_score is not None
    assert report.subtitle_score.total > 0

    # 各品質スコア(重み適用後の寄与度)を個別に assert
    # 字幕ありの場合、全軸が有効で合計重みは 1.0 になるはず
    total_weight = (
        gate.config.visual_weight
        + (gate.config.audio_weight if report.audio_score.available else 0.0)
        + (gate.config.encoding_weight if report.encoding_score.available else 0.0)
        + gate.config.subtitle_weight
    )

    visual_contrib = report.visual_score.total * gate.config.visual_weight / total_weight
    audio_contrib = report.audio_score.total * gate.config.audio_weight / total_weight if report.audio_score.available else 0.0
    encoding_contrib = report.encoding_score.total * gate.config.encoding_weight / total_weight if report.encoding_score.available else 0.0
    subtitle_contrib = report.subtitle_score.total * gate.config.subtitle_weight / total_weight

    # 各軸スコアを個別に assert
    # 字幕ありの場合、満点は visual: 30点, audio: 20点, encoding: 20点, subtitle: 30点
    assert visual_contrib >= 20.0, f"visual_contrib ({visual_contrib:.1f}) < 20.0"
    if report.audio_score.available:
        assert audio_contrib >= 12.0, f"audio_contrib ({audio_contrib:.1f}) < 12.0"
    if report.encoding_score.available:
        assert encoding_contrib >= 12.0, f"encoding_contrib ({encoding_contrib:.1f}) < 12.0"
    assert subtitle_contrib >= 20.0, f"subtitle_contrib ({subtitle_contrib:.1f}) < 20.0"

    # 品質スコアのスナップショット保存（regression_baseline用）
    save_quality_snapshot(f"{TEST_SHORT.name}_with_subtitles", {
        "total_score": report.total_score,
        "visual_score": report.visual_score.total,
        "visual_contrib": round(visual_contrib, 2),
        "audio_score": report.audio_score.total if report.audio_score.available else None,
        "audio_contrib": round(audio_contrib, 2) if report.audio_score.available else None,
        "encoding_score": report.encoding_score.total if report.encoding_score.available else None,
        "encoding_contrib": round(encoding_contrib, 2) if report.encoding_score.available else None,
        "subtitle_score": report.subtitle_score.total,
        "subtitle_contrib": round(subtitle_contrib, 2)
    })


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. レポート生成: generate_improvement_report -> 改善提案
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def test_generate_improvement_report():
    """低スコアの品質レポートから、適切な改善提案が生成されることを確認。"""
    gate = QualityGate()

    # 低品質なダミーレポートの作成
    report = QualityReport(
        video_path="dummy.mp4",
        total_score=50.0,
        passed=False,
        subtitle_score=SubtitleScore(
            chars_per_line=20.0,          # 制限(13)超え
            display_duration_avg=0.8,     # 下限(1.5)未満
            sync_offset_ms=300.0,         # 制限(200)超え
            contrast_ratio=3.0,           # WCAG AA(4.5)未満
            total=40.0
        ),
        visual_score=VisualScore(
            contrast_ratio=3.0,           # WCAG AA(4.5)未満
            safe_area_compliance=90.0,     # 100%未満
            total=50.0
        ),
        audio_score=AudioScore(
            loudness_lufs=-20.0,          # deviation 6.0 (> 1.0)
            loudness_deviation=6.0,
            total=30.0,
            available=True
        ),
        encoding_score=EncodingScore(
            crf_value=28,                 # 制限(23)超え
            frame_drop_count=5,           # フレームドロップあり
            total=40.0,
            available=True
        )
    )

    suggestions = gate.generate_improvement_report(report)
    assert len(suggestions) > 0

    # 深刻度順にソートされていることを確認 (critical -> warning -> info)
    severities = [s.severity for s in suggestions]
    for i in range(len(severities) - 1):
        # 簡易順序チェック: 後ろの項目が前の項目より高い深刻度ではないこと
        order = {"critical": 0, "warning": 1, "info": 2}
        assert order[severities[i]] <= order[severities[i+1]]

    # 各カテゴリの提案が含まれていることの確認
    categories = {s.category for s in suggestions}
    assert "subtitle" in categories
    assert "visual" in categories
    assert "audio" in categories
    assert "encoding" in categories


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. ffprobe不可時: N/A軸を除外して再正規化
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def test_normalize_score_without_ffprobe(tmp_path):
    """ffprobeが利用不可能な場合に、利用不可の軸を除外して再正規化計算することの確認。"""
    gate = QualityGate()

    # ffprobe を無効化
    gate._ffprobe_available = False

    # テスト用の動画を用意 (空ファイルでも、ffprobe無効ならエラーにならず evaluate できる)
    dummy_video = tmp_path / "dummy_video.mp4"
    dummy_video.write_bytes(b"\x00" * 10)

    # 評価を実行
    report = gate.evaluate(str(dummy_video))

    # ffprobe不可なので、audio, encoding は available=False
    assert report.audio_score.available is False
    assert report.encoding_score.available is False
    assert report.audio_score.total == 0.0
    assert report.encoding_score.total == 0.0

    # スコア再正規化の計算チェック
    # 字幕なしなので、有効なのは visual (重み 0.30) のみ
    # よって、total_score は visual.total と一致するはず
    assert report.total_score == report.visual_score.total


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. パラメータ化テスト @pytest.mark.parametrize で6-10ケース
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@pytest.mark.parametrize(
    "case_name, video_exists, srt_content, mock_ffprobe, expected_passed, expected_exception",
    [
        # ── 正常系 (2ケース) ──
        # 1. 正常な動画のみ
        ("normal_video_only", True, None, True, True, None),
        # 2. 正常な動画 + 正常な字幕
        ("normal_video_with_srt", True, "1\n00:00:01,000 --> 00:00:04,000\nHello World\n", True, True, None),

        # ── 境界値 (3ケース) ──
        # 3. 字幕文字数制限境界 (ちょうど13文字)
        ("srt_chars_limit_border", True, "1\n00:00:01,000 --> 00:00:04,000\n1234567890123\n", True, True, None),
        # 4. 字幕表示時間下限境界 (ちょうど1.5秒)
        ("srt_duration_lower_border", True, "1\n00:00:01,000 --> 00:00:02,500\nTest\n", True, True, None),
        # 5. 字幕表示時間上限境界 (ちょうど7.0秒)
        ("srt_duration_upper_border", True, "1\n00:00:01,000 --> 00:00:08,000\nTest\n", True, True, None),

        # ── 異常系 (4ケース) ──
        # 6. 動画ファイルが存在しない (FileNotFoundError)
        ("video_not_found", False, None, True, False, FileNotFoundError),
        # 7. 字幕ファイルが空 (字幕解析に失敗して低スコアになる)
        ("empty_srt", True, "", True, False, None),
        # 8. ffprobe利用不可時のフォールバック動作 (警告が出つつも合格する)
        ("ffprobe_unavailable", True, None, False, True, None),
        # 9. 字幕が低品質すぎて不合格 (文字数が多すぎ、かつ表示時間が極端に短いため絶対に品質スコアが低下する)
        ("low_quality_srt", True, "1\n00:00:01,000 --> 00:00:01,100\nこの字幕は非常に長くて表示時間が極端に短いため絶対に品質スコアが低下します。\n", True, False, None),
    ]
)
def test_parametrize_quality_gate(
    tmp_path, case_name, video_exists, srt_content, mock_ffprobe, expected_passed, expected_exception
):
    """正常系(2+)、境界値(2+)、異常系(2+)を含むパラメータ化テストケース群"""
    # 準備
    video_path = TEST_SHORT if video_exists else tmp_path / "non_existent.mp4"
    if video_exists and not TEST_SHORT.exists():
        pytest.skip(f"テスト用の実動画ファイルが存在しません: {TEST_SHORT}")

    srt_path = None
    if srt_content is not None:
        p = tmp_path / f"{case_name}.srt"
        p.write_text(srt_content, encoding="utf-8")
        srt_path = str(p)

    gate = QualityGate()
    gate._ffprobe_available = mock_ffprobe

    # 実行とアサーション
    if expected_exception:
        with pytest.raises(expected_exception):
            gate.evaluate(str(video_path), subtitle_path=srt_path)
    else:
        report = gate.evaluate(str(video_path), subtitle_path=srt_path)
        assert isinstance(report, QualityReport)
        assert report.passed == expected_passed
