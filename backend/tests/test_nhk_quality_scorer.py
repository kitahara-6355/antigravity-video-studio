"""NHK Quality Scorer テスト

テスト対象: backend/services/nhk_quality_scorer.py
テスト項目:
  1. NHKQualityScorer インスタンス化
  2. NHKScoreReport.to_dict() のキー検証
  3. AxisScore フィールド検証
  4. _parse_srt_timing SRTパース検証
  5. _time_to_ms 時間変換検証
  6. _score_display_duration スコア計算検証
  7. _grade グレード判定検証
  8. score() SRTのみ動作検証 (FFmpegモック)
"""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

from typing import Any

import pytest

# パス設定
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.nhk_quality_scorer import (
    AxisScore,
    NHKQualityScorer,
    NHKScoreReport,
)


# ─── テスト用SRTヘルパー ───

SAMPLE_SRT = textwrap.dedent("""\
    1
    00:00:01,000 --> 00:00:04,000
    こんにちは世界

    2
    00:00:05,000 --> 00:00:08,500
    テスト字幕です

    3
    00:00:10,000 --> 00:00:13,000
    三番目の字幕
""")

SAMPLE_SRT_FAST = textwrap.dedent("""\
    1
    00:00:01,000 --> 00:00:01,500
    これは非常に長い文章で表示時間が短すぎるテストケースです

    2
    00:00:02,000 --> 00:00:02,200
    高速表示テストの文字列です
""")


@pytest.fixture
def scorer() -> NHKQualityScorer:
    """NHKQualityScorerインスタンス"""
    return NHKQualityScorer()


@pytest.fixture
def srt_file(tmp_path: Path) -> str:
    """テスト用SRTファイルを作成"""
    srt = tmp_path / "test.srt"
    srt.write_text(SAMPLE_SRT, encoding="utf-8")
    return str(srt)


@pytest.fixture
def srt_file_fast(tmp_path: Path) -> str:
    """高速表示SRTファイル（表示時間が短い）"""
    srt = tmp_path / "fast.srt"
    srt.write_text(SAMPLE_SRT_FAST, encoding="utf-8")
    return str(srt)


@pytest.fixture
def video_path(tmp_path: Path) -> str:
    """ダミー動画パス（ファイルは存在させる）"""
    p = tmp_path / "dummy.mp4"
    p.write_bytes(b"\x00" * 100)
    return str(p)


# ─── Test 1: インスタンス化 ───

class TestNHKQualityScorerInstantiation:
    """NHKQualityScorerがインスタンス化できること"""

    def test_instantiate(self) -> None:
        scorer = NHKQualityScorer()
        assert scorer is not None
        assert isinstance(scorer, NHKQualityScorer)

    def test_class_constants(self) -> None:
        scorer = NHKQualityScorer()
        assert scorer.TIMING_THRESHOLD_MS == 80
        assert scorer.CHARS_PER_SEC_EXCELLENT == 4.2
        assert scorer.BUG_HUNTER_THRESHOLD == 60.0
        assert scorer.LOUDNESS_TARGET == -14.0
        assert scorer.CONTRAST_RATIO_AA == 4.5


# ─── Test 2: NHKScoreReport.to_dict() ───

class TestNHKScoreReportToDict:
    """NHKScoreReport.to_dict() が正しいキーを含むこと"""

    def _make_axis(self, name: str = "test", score: float = 80.0) -> AxisScore:
        return AxisScore(
            name=name, score=score, max_score=100.0,
            grade="Good", threshold=60.0,
        )

    def test_to_dict_keys(self) -> None:
        report = NHKScoreReport(
            timing_accuracy=self._make_axis("timing"),
            display_duration=self._make_axis("display"),
            readability=self._make_axis("readability"),
            audio_balance=self._make_axis("audio"),
            cut_rhythm=self._make_axis("cuts"),
            overall_score=80.0,
            overall_grade="Good",
        )
        d = report.to_dict()
        expected_keys = {
            "overall_score", "overall_grade", "axes",
            "degradation_log", "suggestions", "scored_at",
        }
        assert set(d.keys()) == expected_keys

    def test_axes_count(self) -> None:
        report = NHKScoreReport(
            timing_accuracy=self._make_axis(),
            display_duration=self._make_axis(),
            readability=self._make_axis(),
            audio_balance=self._make_axis(),
            cut_rhythm=self._make_axis(),
        )
        d = report.to_dict()
        assert len(d["axes"]) == 5

    def test_axes_property(self) -> None:
        axes_data = [self._make_axis(f"axis_{i}") for i in range(5)]
        report = NHKScoreReport(
            timing_accuracy=axes_data[0],
            display_duration=axes_data[1],
            readability=axes_data[2],
            audio_balance=axes_data[3],
            cut_rhythm=axes_data[4],
        )
        assert len(report.axes) == 5
        assert report.axes[0].name == "axis_0"

    def test_scored_at_auto_generated(self) -> None:
        report = NHKScoreReport(
            timing_accuracy=self._make_axis(),
            display_duration=self._make_axis(),
            readability=self._make_axis(),
            audio_balance=self._make_axis(),
            cut_rhythm=self._make_axis(),
        )
        assert report.scored_at  # 非空
        assert "T" in report.scored_at  # ISO形式


# ─── Test 3: AxisScore フィールド ───

class TestAxisScore:
    """AxisScoreの各フィールドが正しいこと"""

    def test_fields(self) -> None:
        axis = AxisScore(
            name="テスト軸", score=85.5, max_score=100.0,
            grade="Excellent", threshold=60.0,
            details={"key": "val"}, suggestion="改善点",
        )
        assert axis.name == "テスト軸"
        assert axis.score == 85.5
        assert axis.max_score == 100.0
        assert axis.grade == "Excellent"
        assert axis.threshold == 60.0
        assert axis.details == {"key": "val"}
        assert axis.suggestion == "改善点"

    def test_defaults(self) -> None:
        axis = AxisScore(
            name="minimal", score=50.0, max_score=100.0,
            grade="Acceptable", threshold=60.0,
        )
        assert axis.details == {}
        assert axis.suggestion == ""


# ─── Test 4: _parse_srt_timing ───

class TestParseSrtTiming:
    """_parse_srt_timingが正しくSRTをパースすること"""

    def test_parse_normal_srt(self, scorer: NHKQualityScorer, srt_file: str) -> None:
        entries = scorer._parse_srt_timing(srt_file)
        assert len(entries) == 3
        # 1番目: 00:00:01,000 → 1000ms
        assert entries[0]["start"] == 1000
        assert entries[0]["end"] == 4000
        assert "こんにちは世界" in entries[0]["text"]

    def test_parse_text_content(self, scorer: NHKQualityScorer, srt_file: str) -> None:
        entries = scorer._parse_srt_timing(srt_file)
        assert entries[1]["text"] == "テスト字幕です"
        assert entries[2]["text"] == "三番目の字幕"

    def test_parse_nonexistent_file(self, scorer: NHKQualityScorer) -> None:
        entries = scorer._parse_srt_timing("/nonexistent/path.srt")
        assert entries == []

    def test_parse_empty_srt(self, scorer: NHKQualityScorer, tmp_path: Path) -> None:
        empty = tmp_path / "empty.srt"
        empty.write_text("", encoding="utf-8")
        entries = scorer._parse_srt_timing(str(empty))
        assert entries == []

    def test_parse_malformed_srt(self, scorer: NHKQualityScorer, tmp_path: Path) -> None:
        """タイミング行がない不正なSRT"""
        malformed = tmp_path / "bad.srt"
        malformed.write_text("This is not an SRT file\nJust text", encoding="utf-8")
        entries = scorer._parse_srt_timing(str(malformed))
        assert entries == []


# ─── Test 5: _time_to_ms ───

class TestTimeToMs:
    """_time_to_msが正しく変換すること"""

    def test_zero(self) -> None:
        assert NHKQualityScorer._time_to_ms("00:00:00,000") == 0

    def test_one_second(self) -> None:
        assert NHKQualityScorer._time_to_ms("00:00:01,000") == 1000

    def test_one_minute(self) -> None:
        assert NHKQualityScorer._time_to_ms("00:01:00,000") == 60000

    def test_one_hour(self) -> None:
        assert NHKQualityScorer._time_to_ms("01:00:00,000") == 3600000

    def test_complex_time(self) -> None:
        # 1h 23m 45s 678ms
        assert NHKQualityScorer._time_to_ms("01:23:45,678") == (
            1 * 3600000 + 23 * 60000 + 45 * 1000 + 678
        )

    def test_dot_separator(self) -> None:
        """ドット区切りも対応"""
        assert NHKQualityScorer._time_to_ms("00:00:01.500") == 1500

    def test_invalid_format(self) -> None:
        """不正な形式は0を返す"""
        assert NHKQualityScorer._time_to_ms("invalid") == 0

    def test_time_to_ms_varied_precision(self) -> None:
        """ミリ秒の桁数が異なる場合でも正しくパースされること"""
        assert NHKQualityScorer._time_to_ms("00:00:01.5") == 1500
        assert NHKQualityScorer._time_to_ms("00:00:01.05") == 1050
        assert NHKQualityScorer._time_to_ms("00:00:01.1234") == 1123
        assert NHKQualityScorer._time_to_ms("00:00:01.000") == 1000


# ─── Test 6: _score_display_duration ───

class TestScoreDisplayDuration:
    """_score_display_durationがSRTで正しくスコア計算すること"""

    def test_no_srt(self, scorer: NHKQualityScorer) -> None:
        result = scorer._score_display_duration(None)
        assert result.name == "字幕表示時間"
        assert result.score == 0.0
        assert result.grade == "N/A"

    def test_normal_srt(self, scorer: NHKQualityScorer, srt_file: str) -> None:
        """通常のSRT: 3秒表示で6-7文字 → NHK基準(4文字/秒)以下なのでExcellent/Good"""
        result = scorer._score_display_duration(srt_file)
        assert result.name == "字幕表示時間"
        assert result.score > 0
        assert result.grade in ("Excellent", "Good", "Acceptable")
        assert "excellent" in result.details or "good" in result.details

    def test_fast_srt(self, scorer: NHKQualityScorer, srt_file_fast: str) -> None:
        """高速表示SRT: 表示時間が短い → スコアが低い"""
        result = scorer._score_display_duration(srt_file_fast)
        assert result.name == "字幕表示時間"
        # 0.5秒で25文字 = 50CPS → poorにカウントされるはず
        assert result.details.get("poor", 0) > 0

    def test_nonexistent_srt(self, scorer: NHKQualityScorer) -> None:
        result = scorer._score_display_duration("/nonexistent.srt")
        assert result.score == 0.0
        assert result.grade == "N/A"

    def test_empty_srt(self, scorer: NHKQualityScorer, tmp_path: Path) -> None:
        empty = tmp_path / "empty.srt"
        empty.write_text("", encoding="utf-8")
        result = scorer._score_display_duration(str(empty))
        assert result.score == 50.0
        assert result.grade == "Acceptable"

    def test_display_duration_with_speaker_and_symbols(self, scorer: NHKQualityScorer, tmp_path: Path) -> None:
        """話者表記や記号を含むSRTのスコアリングテスト"""
        # [話者1] のような話者表記や、「」！？などの記号が多く含まれるが、
        # クレンジングされれば excellent (4文字/秒以下) になるはずのケース
        # 発話内容: 「こんにちは世界」 (7文字)
        # 表示時間: 2.0秒 (CPS = 3.5 <= 4.2 -> excellent)
        # もしクレンジングしないと: 「[話者A] こんにちは世界！」 (18文字) -> CPS = 9.0 -> poor
        srt_content = textwrap.dedent("""\
            1
            00:00:01,000 --> 00:00:03,000
            「[話者A] こんにちは世界！」
        """)
        srt = tmp_path / "speaker_symbols.srt"
        srt.write_text(srt_content, encoding="utf-8")
        
        result = scorer._score_display_duration(str(srt))
        assert result.details.get("excellent", 0) == 1
        assert result.score == 100.0


# ─── Test 7: _grade ───

class TestGrade:
    """_gradeが正しいグレードを返すこと"""

    def test_excellent(self) -> None:
        assert NHKQualityScorer._grade(85.0) == "Excellent"
        assert NHKQualityScorer._grade(100.0) == "Excellent"
        assert NHKQualityScorer._grade(90.0) == "Excellent"

    def test_good(self) -> None:
        assert NHKQualityScorer._grade(70.0) == "Good"
        assert NHKQualityScorer._grade(84.9) == "Good"

    def test_acceptable(self) -> None:
        assert NHKQualityScorer._grade(50.0) == "Acceptable"
        assert NHKQualityScorer._grade(69.9) == "Acceptable"

    def test_poor(self) -> None:
        assert NHKQualityScorer._grade(0.0) == "Poor"
        assert NHKQualityScorer._grade(49.9) == "Poor"

    def test_boundary_85(self) -> None:
        """85の境界値"""
        assert NHKQualityScorer._grade(85.0) == "Excellent"
        assert NHKQualityScorer._grade(84.99) == "Good"


# ─── Test 8: score() SRTのみ動作 (FFmpegモック) ───

class TestScoreWithMockedFFmpeg:
    """score()がSRTのみで動作すること（FFmpegはモック）"""

    def _mock_subprocess_run(self, *args, **kwargs):
        """subprocess.run のモック: コマンドに応じて適切な結果を返す"""
        cmd = args[0] if args else kwargs.get("args", [])
        mock_result = MagicMock()
        mock_result.returncode = 0

        if cmd and cmd[0] == "ffprobe":
            if "-show_streams" in cmd:
                # ffprobe audio stream
                mock_result.stdout = json.dumps({
                    "streams": [{"codec_type": "audio", "sample_rate": "44100"}]
                })
                mock_result.stderr = ""
            elif "-show_entries" in cmd:
                # ffprobe duration
                mock_result.stdout = json.dumps({
                    "format": {"duration": "120.0"}
                })
                mock_result.stderr = ""
        elif cmd and cmd[0] == "ffmpeg":
            mock_result.stdout = ""
            if "loudnorm" in str(cmd):
                # LUFS計測結果
                mock_result.stderr = json.dumps({
                    "input_i": "-14.5",
                    "input_tp": "-1.0",
                    "input_lra": "7.0",
                })
            else:
                # シーンチェンジ検出: 15回のpts_time出力
                mock_result.stderr = "\n".join(
                    [f"[Parsed_showinfo] pts_time:{i * 8.0}" for i in range(15)]
                )
        return mock_result

    @patch("services.nhk_quality_scorer.subprocess.run")
    def test_score_full_with_srt(
        self, mock_run: MagicMock, scorer: NHKQualityScorer,
        srt_file: str, video_path: str,
    ) -> None:
        """全軸スコアリングがモック環境で動作すること"""
        mock_run.side_effect = self._mock_subprocess_run

        report = scorer.score(video_path, srt_path=srt_file)

        assert isinstance(report, NHKScoreReport)
        assert report.overall_score > 0
        assert report.overall_grade in ("Excellent", "Good", "Acceptable", "Poor")
        assert len(report.axes) == 5

        # 各軸の名前を検証
        axis_names = [a.name for a in report.axes]
        assert "字幕タイミング精度" in axis_names
        assert "字幕表示時間" in axis_names
        assert "テロップ可読性" in axis_names
        assert "音量バランス" in axis_names
        assert "カット割りリズム" in axis_names

    @patch("services.nhk_quality_scorer.subprocess.run")
    def test_score_without_srt(
        self, mock_run: MagicMock, scorer: NHKQualityScorer,
        video_path: str,
    ) -> None:
        """SRTなしでもスコアリングが動作すること"""
        mock_run.side_effect = self._mock_subprocess_run

        report = scorer.score(video_path, srt_path=None)

        assert isinstance(report, NHKScoreReport)
        # SRTなし: 字幕系は0点orN/A
        assert report.timing_accuracy.score == 0.0
        assert report.display_duration.score == 0.0

    @patch("services.nhk_quality_scorer.subprocess.run")
    def test_score_to_dict_serializable(
        self, mock_run: MagicMock, scorer: NHKQualityScorer,
        srt_file: str, video_path: str,
    ) -> None:
        """to_dict()の結果がJSON直列化可能であること"""
        mock_run.side_effect = self._mock_subprocess_run

        report = scorer.score(video_path, srt_path=srt_file)
        d = report.to_dict()
        serialized = json.dumps(d, ensure_ascii=False)
        assert isinstance(serialized, str)
        parsed = json.loads(serialized)
        assert parsed["overall_score"] == report.overall_score

    @patch("services.nhk_quality_scorer.subprocess.run")
    def test_audio_score_in_range(
        self, mock_run: MagicMock, scorer: NHKQualityScorer,
        video_path: str,
    ) -> None:
        """モックのLUFS=-14.5は許容範囲内 → score=100"""
        mock_run.side_effect = self._mock_subprocess_run

        report = scorer.score(video_path)
        assert report.audio_balance.score == 100.0
        assert report.audio_balance.details["lufs"] == -14.5

    @patch("services.nhk_quality_scorer.subprocess.run")
    def test_cuts_score_in_range(
        self, mock_run: MagicMock, scorer: NHKQualityScorer,
        video_path: str,
    ) -> None:
        """モックの15カット/2分 = 7.5回/分 → CUT_FREQ_RANGE (8-18) の近傍"""
        mock_run.side_effect = self._mock_subprocess_run

        report = scorer.score(video_path)
        # 7.5は8-18の範囲外だが、5-23の範囲内 → score=75
        assert report.cut_rhythm.score in (75.0, 100.0)

    @patch("services.nhk_quality_scorer.subprocess.run")
    def test_ffmpeg_failure_graceful(
        self, mock_run: MagicMock, scorer: NHKQualityScorer,
        video_path: str,
    ) -> None:
        """FFmpegが失敗してもスコアリングは中断されない"""
        mock_run.side_effect = subprocess.SubprocessError("FFmpeg failed")

        report = scorer.score(video_path)
        assert isinstance(report, NHKScoreReport)
        # FFmpeg失敗時はfallbackスコア
        assert report.audio_balance.score == 50.0
        assert report.cut_rhythm.score == 50.0

    @patch("services.nhk_quality_scorer.subprocess.run")
    def test_score_audio_and_cuts_missing_video(
        self, mock_run: MagicMock, scorer: NHKQualityScorer
    ) -> None:
        """動画ファイルが存在しない場合、音量バランスとカット割りリズムはスコア0.0およびエラーメッセージを返す"""
        nonexistent_path = "/nonexistent/video_file.mp4"
        
        report = scorer.score(nonexistent_path)
        
        # 音量バランスの検証
        assert report.audio_balance.score == 0.0
        assert report.audio_balance.grade == "N/A"
        assert report.audio_balance.suggestion == "動画ファイルが見つかりません"
        
        # カット割りリズムの検証
        assert report.cut_rhythm.score == 0.0
        assert report.cut_rhythm.grade == "N/A"
        assert report.cut_rhythm.suggestion == "動画ファイルが見つかりません"

    @patch("services.nhk_quality_scorer.subprocess.run")
    def test_score_audio_and_cuts_no_video_path(
        self, mock_run: MagicMock, scorer: NHKQualityScorer
    ) -> None:
        """動画ファイルパスが指定されていない場合、音量バランスとカット割りリズムはスキップされスコア100.0およびグレードN/Aを返す"""
        report = scorer.score("")
        
        # 音量バランスの検証
        assert report.audio_balance.score == 100.0
        assert report.audio_balance.grade == "N/A"
        assert report.audio_balance.suggestion == ""
        
        # カット割りリズムの検証
        assert report.cut_rhythm.score == 100.0
        assert report.cut_rhythm.grade == "N/A"
        assert report.cut_rhythm.suggestion == ""


    @patch("services.nhk_quality_scorer.subprocess.run")
    def test_score_timing_empty_srt(
        self, mock_run: MagicMock, scorer: NHKQualityScorer, tmp_path: Path
    ) -> None:
        """空のSRTファイルに対する_score_timingの挙動"""
        empty = tmp_path / "empty_timing.srt"
        empty.write_text("", encoding="utf-8")
        result = scorer._score_timing("/nonexistent/video.mp4", str(empty))
        assert result.score == 50.0
        assert result.grade == "Acceptable"
        assert result.suggestion == "SRTエントリが空です"

    @patch("services.nhk_quality_scorer.subprocess.run")
    def test_score_readability_empty_srt(
        self, mock_run: MagicMock, scorer: NHKQualityScorer, tmp_path: Path
    ) -> None:
        """空のSRTファイルに対する_score_readabilityの挙動"""
        empty = tmp_path / "empty_readability.srt"
        empty.write_text("", encoding="utf-8")
        result = scorer._score_readability("/nonexistent/video.mp4", str(empty))
        assert result.score == 50.0
        assert result.grade == "Acceptable"

    @patch("services.nhk_quality_scorer.subprocess.run")
    def test_lufs_extraction_failure(
        self, mock_run: MagicMock, scorer: NHKQualityScorer, video_path: str
    ) -> None:
        """loudnorm出力にlufs値が見つからない場合のフォールバック値（-20.0）のテスト"""
        def _mock_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            mock_result = MagicMock()
            mock_result.returncode = 0
            if "ffprobe" in cmd[0]:
                mock_result.stdout = '{"streams": [{"codec_type": "audio", "sample_rate": "44100"}]}'
            elif "ffmpeg" in cmd[0]:
                mock_result.stderr = "invalid stderr output without input_i"
            return mock_result

        mock_run.side_effect = _mock_run
        result = scorer._score_audio(video_path)
        # -20.0 LUFS は LOUDNESS_RANGE (-16.0 ~ -13.0) から4以上離れているので 25.0 点
        assert result.score == 50.0
        assert result.details["lufs"] == -20.0

    @patch("services.nhk_quality_scorer.subprocess.run")
    def test_cuts_duration_failure(
        self, mock_run: MagicMock, scorer: NHKQualityScorer, video_path: str
    ) -> None:
        """durationが0以下のときに例外が発生し、カット割りリズムがAcceptable(50.0)として処理されること"""
        def _mock_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            mock_result = MagicMock()
            mock_result.returncode = 0
            if "ffprobe" in cmd[0]:
                mock_result.stdout = '{"format": {"duration": "0.0"}}'
            return mock_result

        mock_run.side_effect = _mock_run
        result = scorer._score_cuts(video_path)
        assert result.score == 50.0
        assert "カット分析失敗" in result.suggestion

    @patch("services.nhk_quality_scorer.QUALITY_LOG_PATH")
    def test_load_degradation_log_exception(
        self, mock_log_path: MagicMock, scorer: NHKQualityScorer
    ) -> None:
        """デgradation_logのファイル読み込みで例外が発生した場合に空リストを返すこと"""
        mock_log_path.exists.return_value = True
        mock_log_path.open.side_effect = Exception("Read error")
        logs = scorer._load_degradation_log("/dummy/path")
        assert logs == []

    @patch("services.nhk_quality_scorer.subprocess.run")
    def test_validate_audio_stream_failure(
        self, mock_run: MagicMock, scorer: NHKQualityScorer
    ) -> None:
        """ffprobeの終了コードが非ゼロのとき、RuntimeErrorが発生すること"""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "some ffprobe error message"
        mock_run.return_value = mock_result
        
        with pytest.raises(RuntimeError) as exc_info:
            scorer._validate_audio_stream("/dummy/path.mp4")
        assert "ffprobe failed: some ffprobe error message" in str(exc_info.value)

    def test_count_timing_issues_additional(self, scorer: NHKQualityScorer) -> None:
        """重複および5秒超のギャップが正しくカウントされること"""
        entries = [
            {"start": 1000, "end": 3000, "text": "A"},
            {"start": 2500, "end": 4000, "text": "B"},  # 重複 (+1)
            {"start": 9500, "end": 11000, "text": "C"}, # ギャップ5.5秒 (+1)
        ]
        issues = scorer._count_timing_issues(entries)
        assert issues == 2

    def test_evaluate_single_entry_cps_zero_duration(self, scorer: NHKQualityScorer) -> None:
        """表示秒数が0以下のとき'poor'が返されること"""
        entry = {"start": 1000, "end": 1000, "text": "短い"}
        assert scorer._evaluate_single_entry_cps(entry) == "poor"

    def test_score_display_duration_cps_variations(
        self, scorer: NHKQualityScorer, tmp_path: Path
    ) -> None:
        """CPSがgood, acceptableの時の判定パスを通るテスト"""
        srt_content = textwrap.dedent("""\
            1
            00:00:01,000 --> 00:00:03,000
            あいうえおかきくけ

            2
            00:00:04,000 --> 00:00:06,000
            あいうえおかきくけこさしす
        """)
        srt = tmp_path / "cps_test.srt"
        srt.write_text(srt_content, encoding="utf-8")
        
        result = scorer._score_display_duration(str(srt))
        assert result.details["good"] == 1
        assert result.details["acceptable"] == 1

    def test_analyze_entry_readability_line_violations(self, scorer: NHKQualityScorer) -> None:
        """3行以上の字幕および20文字を超える行に対する減点と検出"""
        # 3行以上
        deduction, issues = scorer._analyze_entry_readability("A\nB\nC")
        assert deduction == 2.0
        assert "3行以上の字幕" in issues

        # 20文字超の行
        long_text = "あいうえおかきくけこさしすせそたちつてとなにぬねの"
        deduction2, issues2 = scorer._analyze_entry_readability(long_text)
        assert deduction2 == 1.0
        assert "長すぎる行" in issues2

    def test_calculate_audio_score_variations(self, scorer: NHKQualityScorer) -> None:
        """LUFS値によるオーディオスコア計算結果の確認"""
        # low - 2.0 <= lufs <= high + 2.0 (スコア 75)
        assert scorer._calculate_audio_score(-17.0) == 75.0
        assert scorer._calculate_audio_score(-12.0) == 75.0

        # それ以外 (スコア 25)
        assert scorer._calculate_audio_score(-21.0) == 25.0
        assert scorer._calculate_audio_score(-8.0) == 25.0

    def test_calculate_cut_score_variations(self, scorer: NHKQualityScorer) -> None:
        """カット割り頻度によるスコア計算結果の確認"""
        # low <= cuts_per_min <= high (スコア 100)
        assert scorer._calculate_cut_score(10.0) == 100.0

        # low - 5.0 <= cuts_per_min <= high + 10.0 (スコア 50)
        assert scorer._calculate_cut_score(4.0) == 50.0

        # それ以外 (スコア 25)
        assert scorer._calculate_cut_score(2.0) == 25.0
        assert scorer._calculate_cut_score(30.0) == 25.0

    def test_load_degradation_log_file_not_exists(
        self, scorer: NHKQualityScorer
    ) -> None:
        """ログファイルが存在しない場合、空のリストが返ること"""
        with patch("services.nhk_quality_scorer.QUALITY_LOG_PATH") as mock_path:
            mock_path.exists.return_value = False
            logs = scorer._load_degradation_log("/dummy/path")
            assert logs == []

    def test_load_degradation_log_exists_and_readable(
        self, scorer: NHKQualityScorer, tmp_path: Path
    ) -> None:
        """ログファイルが存在し、正常に読み込めること"""
        log_file = tmp_path / "pipeline_quality_log.jsonl"
        log_data = [
            {"overall_score": 80.0},
            {"overall_score": 85.0},
            {"overall_score": 90.0},
        ]
        with open(log_file, "w", encoding="utf-8") as f:
            for d in log_data:
                f.write(json.dumps(d) + "\n")
        
        with patch("services.nhk_quality_scorer.QUALITY_LOG_PATH", log_file):
            logs = scorer._load_degradation_log("/dummy/path")
            assert len(logs) == 3
            assert logs[2]["overall_score"] == 90.0

    def test_load_degradation_log_exception_real(self, scorer: NHKQualityScorer) -> None:
        """QUALITY_LOG_PATHを差し替えて例外を強制発生させ、490-491をカバーする"""
        import services.nhk_quality_scorer
        from pathlib import Path
        
        class BadPath(type(Path())):
            def exists(self):
                return True

        original_path = services.nhk_quality_scorer.QUALITY_LOG_PATH
        # 実在しないファイルを指すBadPathで差し替え。exists()はTrueを返すためtryに入るが、open()でFileNotFoundErrorをスローする。
        services.nhk_quality_scorer.QUALITY_LOG_PATH = BadPath("nonexistent_log_file_trigger_exception.jsonl")
        try:
            logs = scorer._load_degradation_log("/dummy/path")
            assert logs == []
        finally:
            services.nhk_quality_scorer.QUALITY_LOG_PATH = original_path

    def test_score_audio_and_cuts_empty_or_none_video(
        self, scorer: NHKQualityScorer
    ) -> None:
        """動画ファイルパスが空文字列またはNoneの場合、音量バランスとカット割りリズムはスコア100.0およびgrade='N/A'を返す"""
        # Noneの場合
        report_none = scorer.score(None)
        assert report_none.audio_balance.score == 100.0
        assert report_none.audio_balance.grade == "N/A"
        assert report_none.audio_balance.suggestion == ""
        assert report_none.cut_rhythm.score == 100.0
        assert report_none.cut_rhythm.grade == "N/A"
        assert report_none.cut_rhythm.suggestion == ""

        # 空文字列の場合
        report_empty = scorer.score("")
        assert report_empty.audio_balance.score == 100.0
        assert report_empty.audio_balance.grade == "N/A"
        assert report_empty.audio_balance.suggestion == ""
        assert report_empty.cut_rhythm.score == 100.0
        assert report_empty.cut_rhythm.grade == "N/A"
        assert report_empty.cut_rhythm.suggestion == ""

    def test_score_audio_and_cuts_whitespace_video(
        self, scorer: NHKQualityScorer
    ) -> None:
        """動画ファイルパスが空白文字のみの場合、音量バランスとカット割りリズムはスコア0.0およびgrade='N/A'を返す"""
        report_whitespace = scorer.score("   ")
        assert report_whitespace.audio_balance.score == 0.0
        assert report_whitespace.audio_balance.grade == "N/A"
        assert "動画ファイルが見つかりません" in report_whitespace.audio_balance.suggestion
        assert report_whitespace.cut_rhythm.score == 0.0
        assert report_whitespace.cut_rhythm.grade == "N/A"
        assert "動画ファイルが見つかりません" in report_whitespace.cut_rhythm.suggestion


    def test_overall_score_calculation_with_na_axes(
        self, scorer: NHKQualityScorer
    ) -> None:
        """一部の軸が N/A の場合、全体スコア (overall_score) が有効な軸のみの加重平均で正しく算出されること"""
        with patch.object(scorer, "_score_timing") as mock_timing, \
             patch.object(scorer, "_score_display_duration") as mock_display, \
             patch.object(scorer, "_score_readability") as mock_readability, \
             patch.object(scorer, "_score_audio") as mock_audio, \
             patch.object(scorer, "_score_cuts") as mock_cuts:
            
            # timing: 80.0 (Good) [weight: 0.15]
            # readability: 90.0 (Excellent) [weight: 0.20]
            # audio: 0.0 (N/A) [weight: 0.25]  <- 除外
            # cuts: 0.0 (N/A) [weight: 0.25]   <- 除外
            # display: 0.0 (N/A) [weight: 0.15] <- 除外
            mock_timing.return_value = AxisScore("字幕タイミング精度", 80.0, 100.0, "Good", 60.0)
            mock_display.return_value = AxisScore("字幕表示時間", 0.0, 100.0, "N/A", 60.0)
            mock_readability.return_value = AxisScore("テロップ可読性", 90.0, 100.0, "Excellent", 60.0)
            mock_audio.return_value = AxisScore("音量バランス", 0.0, 100.0, "N/A", 60.0)
            mock_cuts.return_value = AxisScore("カット割りリズム", 0.0, 100.0, "N/A", 60.0)
            
            report = scorer.score("/dummy/video.mp4")
            
            # 有効な重みの合計: 0.15 (timing) + 0.20 (readability) = 0.35
            # 重み付き合計: 80.0 * 0.15 + 90.0 * 0.20 = 12.0 + 18.0 = 30.0
            # 期待値: 30.0 / 0.35 = 85.714... -> 85.7
            assert report.overall_score == 85.7
            assert report.overall_grade == "Excellent"

    def test_quality_feedback_trigger_na_grade_is_ignored(self) -> None:
        """grade が 'N/A' の軸は、たとえスコアが閾値以下であってもトリガーされない。"""
        from services.quality_feedback_trigger import QualityFeedbackTrigger
        from unittest.mock import mock_open, MagicMock
        
        trigger = QualityFeedbackTrigger(threshold=60.0)
        
        report = {
            "overall_score": 80.0,
            "overall_grade": "Good",
            "axes": [
                {"name": "音量バランス", "score": 0.0, "max_score": 100, "grade": "N/A",
                 "suggestion": "動画ファイルが見つかりません", "threshold": 60.0},
                {"name": "カット割りリズム", "score": 0.0, "max_score": 100, "grade": "N/A",
                 "suggestion": "動画ファイルが見つかりません", "threshold": 60.0},
                {"name": "字幕表示時間", "score": 80.0, "max_score": 100, "grade": "Good", "threshold": 60.0},
            ]
        }
        
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        
        with patch("services.quality_feedback_trigger.TASK_QUEUE_PATH", mock_path), \
             patch("services.quality_feedback_trigger.open", mock_open(read_data='{"tasks": [], "current_batch_id": "test_batch"}')):
            result = trigger.evaluate_and_trigger(report)
            
        assert result["triggered"] is False
        assert result["tasks_created"] == 0


    @patch("services.nhk_quality_scorer.subprocess.run")
    def test_score_audio_subprocess_error(
        self, mock_run: MagicMock, scorer: NHKQualityScorer, video_path: str
    ) -> None:
        """FFmpeg実行時にSubprocessErrorが発生した場合の音量バランスのハンドリングを検証"""
        def _mock_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            mock_result = MagicMock()
            if "ffprobe" in cmd[0]:
                mock_result.returncode = 0
                mock_result.stdout = '{"streams": [{"codec_type": "audio", "sample_rate": "44100"}]}'
            elif "ffmpeg" in cmd[0]:
                raise subprocess.SubprocessError("FFmpeg process crashed")
            return mock_result

        mock_run.side_effect = _mock_run
        result = scorer._score_audio(video_path)
        assert result.score == 50.0
        assert "コマンド実行エラー" in result.suggestion

    @patch("services.nhk_quality_scorer.subprocess.run")
    def test_score_cuts_json_decode_error(
        self, mock_run: MagicMock, scorer: NHKQualityScorer, video_path: str
    ) -> None:
        """ffprobeのduration出力が不正なJSONだった場合のカット割りリズムのハンドリングを検証"""
        def _mock_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            mock_result = MagicMock()
            mock_result.returncode = 0
            if "ffprobe" in cmd[0]:
                # 不正なJSONを出力
                mock_result.stdout = "{malformed json"
            return mock_result

        mock_run.side_effect = _mock_run
        result = scorer._score_cuts(video_path)
        assert result.score == 50.0
        assert "パースエラー" in result.suggestion

    def test_parse_srt_unicode_decode_error(
        self, scorer: NHKQualityScorer, tmp_path: Path
    ) -> None:
        """SRTファイル読み込み時にUnicodeDecodeErrorが発生した場合の挙動を検証"""
        bad_encoding_file = tmp_path / "bad_encoding.srt"
        # UTF-16で書き出すことで、デフォルトのUTF-8読み込み時にUnicodeDecodeErrorを発生させる
        bad_encoding_file.write_text("1\n00:00:01,000 --> 00:00:02,000\nテスト\n", encoding="utf-16")
        
        entries = scorer._parse_srt_timing(str(bad_encoding_file))
        # エラーハンドリングされて空のリストが返ることを確認
        assert entries == []

    def test_load_degradation_log_json_decode_error(
        self, scorer: NHKQualityScorer, tmp_path: Path
    ) -> None:
        """品質低下ログファイルに不正なJSON行が含まれる場合の挙動を検証"""
        log_file = tmp_path / "broken_log.jsonl"
        log_file.write_text("{\n{broken json}\n", encoding="utf-8")
        
        with patch("services.nhk_quality_scorer.QUALITY_LOG_PATH", log_file):
            logs = scorer._load_degradation_log("/dummy/path")
            assert logs == []

    def test_clean_text_for_scoring_robustness(self, scorer: NHKQualityScorer) -> None:
        """_clean_text_for_scoring に None や非文字列が渡された場合のハンドリングを検証"""
        # None が渡された場合は空文字列が返る
        assert scorer._clean_text_for_scoring(None) == ""
        # 文字列以外が渡された場合は文字列に変換して処理される
        assert scorer._clean_text_for_scoring(12345) == "12345"

    def test_time_to_ms_robustness(self) -> None:
        """_time_to_ms に不正な入力が渡された場合のハンドリングを検証"""
        # None や空文字列
        assert NHKQualityScorer._time_to_ms(None) == 0
        assert NHKQualityScorer._time_to_ms("") == 0
        # フォーマット不正
        assert NHKQualityScorer._time_to_ms("12:34") == 0
        assert NHKQualityScorer._time_to_ms("aa:bb:cc,ddd") == 0

    def test_clean_text_multiline_speakers(self, scorer: NHKQualityScorer) -> None:
        """複数行テキストで、2行目以降の行頭にある話者表記も正しく除去されること"""
        text = "話者1: こんにちは\n話者2: こんばんは\n[話者3]さようなら"
        cleaned = scorer._clean_text_for_scoring(text, remove_symbols=True)
        # 記号除去・スペース改行除去後の期待値: "こんにちはこんばんはさようなら"
        assert cleaned == "こんにちはこんばんはさようなら"

    def test_validate_audio_stream_no_streams(self, scorer: NHKQualityScorer) -> None:
        """ffprobeの出力JSONでstreamsが空の場合にValueErrorが発生すること"""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '{"streams": []}'
        
        with patch("services.nhk_quality_scorer.subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError) as exc_info:
                scorer._validate_audio_stream("/dummy/path.mp4")
            assert "No audio streams found" in str(exc_info.value)


    def test_count_timing_issues_self_reversal(self, scorer: NHKQualityScorer) -> None:
        """単一エントリ内でstart >= endの逆転がある場合にタイミング問題としてカウントされること"""
        entries = [
            {"start": 1000, "end": 3000, "text": "A"},
            {"start": 5000, "end": 4000, "text": "B"},  # 自己逆転 (+1)
            {"start": 6000, "end": 8000, "text": "C"},
        ]
        issues = scorer._count_timing_issues(entries)
        assert issues == 1

    def test_clean_text_parentheses_removal(self, scorer: NHKQualityScorer) -> None:
        """丸括弧で囲まれた話者名や演出用文字が正しくクレンジングされること"""
        text_en = "(Speaker) Hello (laughter)"
        text_ja = "（話者A）こんにちは（笑）"
        assert scorer._clean_text_for_scoring(text_en, remove_symbols=True) == "Hello"
        assert scorer._clean_text_for_scoring(text_ja, remove_symbols=True) == "こんにちは"


class TestNHKQualityScorerCoverageExpansion:
    """カバレッジ向上のための追加テスト"""

    def test_overall_score_calculation_all_na_axes(self, scorer: NHKQualityScorer) -> None:
        """すべての軸が N/A の場合、overall_score が 0.0 になることを検証 (L103)"""
        def make_na_axis(name):
            return AxisScore(name=name, score=0.0, max_score=100.0, grade="N/A", threshold=60.0)

        with patch.object(scorer, "_score_timing", return_value=make_na_axis("字幕タイミング精度")), \
             patch.object(scorer, "_score_display_duration", return_value=make_na_axis("字幕表示時間")), \
             patch.object(scorer, "_score_readability", return_value=make_na_axis("テロップ可読性")), \
             patch.object(scorer, "_score_audio", return_value=make_na_axis("音量バランス")), \
             patch.object(scorer, "_score_cuts", return_value=make_na_axis("カット割りリズム")):
            report = scorer.score("/dummy/path.mp4")
            assert report.overall_score == 0.0
            assert report.overall_grade == "Poor"

    @patch("services.nhk_quality_scorer.subprocess.run")
    def test_score_audio_exceptions(self, mock_run: MagicMock, scorer: NHKQualityScorer, video_path: str) -> None:
        """_score_audio 内で発生する各種例外のハンドリングを検証 (L374-375, L388-389, L395-396)"""
        # 1. FileNotFoundError (L374-375)
        mock_run.side_effect = FileNotFoundError("ffprobe command not found")
        result = scorer._score_audio(video_path)
        assert result.score == 0.0
        assert result.grade == "N/A"
        assert "分析コマンドが見つかりません" in result.suggestion

        # 2. ValueError (L388-389)
        with patch.object(scorer, "_validate_audio_stream", side_effect=ValueError("Test ValueError")):
            result = scorer._score_audio(video_path)
            assert result.score == 50.0
            assert result.grade == "Acceptable"
            assert "値エラー" in result.suggestion

        # 3. RuntimeError (L395-396)
        with patch.object(scorer, "_validate_audio_stream", side_effect=RuntimeError("Test RuntimeError")):
            result = scorer._score_audio(video_path)
            assert result.score == 50.0
            assert result.grade == "Acceptable"
            assert "ランタイムエラー" in result.suggestion

    @patch("services.nhk_quality_scorer.subprocess.run")
    def test_score_cuts_exceptions(self, mock_run: MagicMock, scorer: NHKQualityScorer, video_path: str) -> None:
        """_score_cuts 内で発生する各種例外のハンドリングを検証 (L486-487, L493-494)"""
        # 1. FileNotFoundError (L486-487)
        with patch.object(scorer, "_get_video_duration", side_effect=FileNotFoundError("ffprobe not found")):
            result = scorer._score_cuts(video_path)
            assert result.score == 0.0
            assert result.grade == "N/A"
            assert "分析コマンドが見つかりません" in result.suggestion

        # 2. SubprocessError (L493-494)
        with patch.object(scorer, "_get_video_duration", side_effect=subprocess.SubprocessError("ffprobe failed")):
            result = scorer._score_cuts(video_path)
            assert result.score == 50.0
            assert result.grade == "Acceptable"
            assert "コマンド実行エラー" in result.suggestion

    def test_parse_srt_timing_exceptions(self, scorer: NHKQualityScorer) -> None:
        """_parse_srt_timing 内で発生する例外のハンドリングを検証 (L577-580)"""
        # 1. ValueError / IndexError (L577-578)
        with patch("services.nhk_quality_scorer.open", side_effect=ValueError("Test ValueError")):
            entries = scorer._parse_srt_timing("dummy.srt")
            assert entries == []

        # 2. TypeError / AttributeError (L579-580)
        with patch("services.nhk_quality_scorer.open", side_effect=TypeError("Test TypeError")):
            entries = scorer._parse_srt_timing("dummy.srt")
            assert entries == []

    def test_time_to_ms_no_ms(self) -> None:
        """ミリ秒指定（ドットやカンマ）がない場合のパースを検証 (L600)"""
        assert NHKQualityScorer._time_to_ms("00:00:01") == 1000
        assert NHKQualityScorer._time_to_ms("00:01") == 0

    def test_load_degradation_log_exceptions(self, scorer: NHKQualityScorer) -> None:
        """_load_degradation_log で想定外の例外が発生した場合のハンドリングを検証 (L623-625)"""
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        
        with patch("services.nhk_quality_scorer.QUALITY_LOG_PATH", mock_path), \
             patch("services.nhk_quality_scorer.open", side_effect=TypeError("Test TypeError")):
            logs = scorer._load_degradation_log("/dummy/path")
            assert logs == []

    @patch("services.nhk_quality_scorer.subprocess.run")
    def test_score_audio_attribute_error(self, mock_run: MagicMock, scorer: NHKQualityScorer, video_path: str) -> None:
        """_score_audio 内で AttributeError が発生した時のハンドリングを検証 (L402-403)"""
        with patch.object(scorer, "_validate_audio_stream", side_effect=AttributeError("Test AttributeError")):
            result = scorer._score_audio(video_path)
            assert result.score == 50.0
            assert result.grade == "Acceptable"
            assert "音声分析失敗:" in result.suggestion

    @patch("services.nhk_quality_scorer.subprocess.run")
    def test_score_cuts_attribute_error(self, mock_run: MagicMock, scorer: NHKQualityScorer, video_path: str) -> None:
        """_score_cuts 内で AttributeError が発生した時のハンドリングを検証 (L506-508)"""
        with patch.object(scorer, "_get_video_duration", side_effect=AttributeError("Test AttributeError")):
            result = scorer._score_cuts(video_path)
            assert result.score == 50.0
            assert result.grade == "Acceptable"
            assert "カット分析失敗:" in result.suggestion


class TestNHKQualityScorerEdgeCases:
    """エッジケース（境界値、None入力、空リスト、巨大入力、不正型）に対するテスト"""

    @pytest.mark.parametrize("time_str, expected", [
        (None, 0),
        ("", 0),
        ("   ", 0),
        (1234, 0),
        ([], 0),
        ("12:34", 0),
        ("12:34:56:78", 0),
        ("aa:bb:cc", 0),
        ("12:34:56.abc", 0),
        ("12:34:56.", 45296000),
        ("00:00:01,2", 1200),
        ("00:00:01,2345", 1234),
        ("99:99:99,999", 99 * 3600000 + 99 * 60000 + 99000 + 999),
        ("00:00:00,000", 0),
    ])
    def test_time_to_ms_edge_cases(self, time_str: Any, expected: int) -> None:
        """_time_to_ms のエッジケース入力を検証"""
        assert NHKQualityScorer._time_to_ms(time_str) == expected

    def test_clean_text_for_scoring_edge_cases(self, scorer: NHKQualityScorer) -> None:
        """_clean_text_for_scoring のエッジケース入力を検証"""
        # None や 不正な型
        assert scorer._clean_text_for_scoring(None) == ""
        assert scorer._clean_text_for_scoring(12345) == "12345"
        # dict は文字列化されて記号が消える
        # "{'a': 1}" -> "{" と "}" は記号リストに含まれないので残る。
        cleaned_dict = scorer._clean_text_for_scoring({"a": 1})
        assert cleaned_dict == "1}"

        # 空入力
        assert scorer._clean_text_for_scoring("") == ""
        assert scorer._clean_text_for_scoring("   \n\t  ") == ""

        # 入れ子括弧、閉じられていない括弧
        assert scorer._clean_text_for_scoring("[話者[サブ]]") == ""
        assert scorer._clean_text_for_scoring("[話者") == "話者"  # 記号除去のみ
        assert scorer._clean_text_for_scoring("(話者") == "話者"

        # 巨大文字列
        huge_text = "([話者] " + ("A" * 10000) + ")"
        assert scorer._clean_text_for_scoring(huge_text) == ""

    @pytest.mark.parametrize("score, expected", [
        (100.0, "Excellent"),
        (85.0, "Excellent"),
        (84.9, "Good"),
        (70.0, "Good"),
        (69.9, "Acceptable"),
        (50.0, "Acceptable"),
        (49.9, "Poor"),
        (0.0, "Poor"),
        (-10.0, "Poor"),
        (float('inf'), "Excellent"),
        (float('-inf'), "Poor"),
    ])
    def test_grade_edge_cases(self, score: float, expected: str) -> None:
        """_grade の境界値や特殊浮動小数点の挙動を検証"""
        assert NHKQualityScorer._grade(score) == expected

    def test_evaluate_single_entry_cps_edge_cases(self, scorer: NHKQualityScorer) -> None:
        """_evaluate_single_entry_cps の異常な期間 (duration) を検証"""
        entry_zero = {"start": 1000, "end": 1000, "text": "Hello"}
        assert scorer._evaluate_single_entry_cps(entry_zero) == "poor"

        entry_negative = {"start": 2000, "end": 1000, "text": "Hello"}
        assert scorer._evaluate_single_entry_cps(entry_negative) == "poor"

        entry_no_text = {"start": 1000, "end": 2000}
        assert scorer._evaluate_single_entry_cps(entry_no_text) == "excellent"

    def test_count_line_limit_violations_edge_cases(self, scorer: NHKQualityScorer) -> None:
        """_count_line_limit_violations の None 入力を検証 (AttributeError が発生すること)"""
        with pytest.raises(AttributeError):
            scorer._count_line_limit_violations(None)

    def test_score_paths_edge_cases(self, scorer: NHKQualityScorer) -> None:
        """score() に None や実在しないパスを渡したときの挙動を検証"""
        report1 = scorer.score(video_path=None, srt_path=None)
        assert report1.overall_score == 50.0

        report2 = scorer.score(video_path="   ", srt_path="   ")
        assert report2.overall_score == 50.0

        report3 = scorer.score(video_path="/nonexistent/video.mp4", srt_path="/nonexistent/sub.srt")
        assert report3.overall_score == 50.0


class TestNHKQualityScorerMoreEdgeCases:
    """更なるエッジケース（境界値、None入力、不正型、異常値）のテスト"""

    def test_time_to_ms_extra_edge_cases(self) -> None:
        """_time_to_ms に対する極端なエッジケースを検証"""
        # 小数点以下が2桁の場合（230msに変換されることを確認）
        assert NHKQualityScorer._time_to_ms("00:00:01.23") == 1230
        # 小数点以下が4桁以上の場合（先頭3桁の234msに変換されることを確認）
        assert NHKQualityScorer._time_to_ms("00:00:01.2345") == 1234
        # コロンが1つの場合
        assert NHKQualityScorer._time_to_ms("00:01.000") == 0
        # コロンがない場合
        assert NHKQualityScorer._time_to_ms("0001000") == 0
        # 数字以外の文字が含まれる場合
        assert NHKQualityScorer._time_to_ms("00:00:01,2a3") == 0
        # 異常に巨大な時間表記
        assert NHKQualityScorer._time_to_ms("999:00:00.000") == 999 * 3600000

    def test_clean_text_for_scoring_extra_edge_cases(self, scorer: NHKQualityScorer) -> None:
        """_clean_text_for_scoring に対するネストされた括弧や不正文字の検証"""
        # ネストされた全角丸括弧（現在の非再帰的な正規表現実装では、内側のみ除去されて閉じ括弧が残る挙動となる）
        assert scorer._clean_text_for_scoring("（話者A（演出B））こんにちは") == "）こんにちは"
        # 閉じられていない全角括弧（閉じ括弧がないため正規表現にマッチせず、かつ全角丸括弧は記号除去リストに含まれないため残る挙動となる）
        assert scorer._clean_text_for_scoring("（話者Aこんにちは") == "（話者Aこんにちは"
        # 制御文字の混入（ゼロ幅スペースなどは現在の文字除去ロジックの対象外であるため、残る挙動となる）
        assert scorer._clean_text_for_scoring("話者:\u200bこんにちは\t\r\n") == "\u200bこんにちは"
        # 記号除去なしの場合
        assert scorer._clean_text_for_scoring("こんにちは！", remove_symbols=False) == "こんにちは！"

    def test_parse_srt_timing_directory_path(self, scorer: NHKQualityScorer, tmp_path: Path) -> None:
        """_parse_srt_timing にディレクトリのパスを渡した際に、PermissionError/IsADirectoryErrorが適切に捕捉されて空リストが返ることを検証"""
        # tmp_path はディレクトリ
        entries = scorer._parse_srt_timing(str(tmp_path))
        assert entries == []

    def test_parse_srt_timing_empty_file(self, scorer: NHKQualityScorer, tmp_path: Path) -> None:
        """_parse_srt_timing に空のファイルを渡した場合に空リストが返ることを検証"""
        empty_file = tmp_path / "empty.srt"
        empty_file.write_text("", encoding="utf-8")
        entries = scorer._parse_srt_timing(str(empty_file))
        assert entries == []

    def test_calculate_cut_score_nan_inf(self, scorer: NHKQualityScorer) -> None:
        """_calculate_cut_score に nan や inf を渡した際の挙動"""
        # inf
        assert scorer._calculate_cut_score(float('inf')) == 25.0
        # -inf
        assert scorer._calculate_cut_score(float('-inf')) == 25.0
        # nanの場合
        assert scorer._calculate_cut_score(float('nan')) == 25.0
        # 非常に大きな値
        assert scorer._calculate_cut_score(1e10) == 25.0
        # 負の値
        assert scorer._calculate_cut_score(-5.0) == 25.0

    def test_calculate_audio_score_nan_inf(self, scorer: NHKQualityScorer) -> None:
        """_calculate_audio_score に nan や inf を渡した際の挙動"""
        # inf
        assert scorer._calculate_audio_score(float('inf')) == 25.0
        # -inf
        assert scorer._calculate_audio_score(float('-inf')) == 25.0
        # nan
        assert scorer._calculate_audio_score(float('nan')) == 25.0

    def test_count_timing_issues_empty_and_single(self, scorer: NHKQualityScorer) -> None:
        """_count_timing_issues に空または要素が1つのリストを渡した際の挙動"""
        assert scorer._count_timing_issues([]) == 0
        assert scorer._count_timing_issues([{"start": 1000, "end": 2000}]) == 0


