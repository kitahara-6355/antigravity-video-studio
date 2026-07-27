import pytest
from unittest.mock import patch, MagicMock
from backend.services.nhk_quality_scorer import NHKQualityScorer, AxisScore, NHKScoreReport

def test_score_basic():
    scorer = NHKQualityScorer()
    # 正常系テスト: srtなし、videoなし等でフォールバックすること
    report = scorer.score("non_existent_video.mp4", "non_existent.srt")
    assert isinstance(report, NHKScoreReport)
    assert report.timing_accuracy.grade == "N/A"
    assert report.display_duration.grade == "N/A"
    assert report.readability.grade == "Acceptable"
    assert report.audio_balance.grade == "N/A"
    assert report.cut_rhythm.grade == "N/A"

@patch("backend.services.nhk_quality_scorer.os.path.exists")
def test_parse_srt_timing_exception(mock_exists):
    mock_exists.return_value = True
    scorer = NHKQualityScorer()
    
    # openをモックしてTypeErrorを発生させ、except (TypeError, AttributeError) を通す
    with patch("builtins.open", side_effect=TypeError("Type error")):
        entries = scorer._parse_srt_timing("dummy.srt")
        assert entries == []

@patch("backend.services.nhk_quality_scorer.QUALITY_LOG_PATH")
def test_load_degradation_log_exception(mock_path):
    mock_path.exists.return_value = True
    scorer = NHKQualityScorer()
    
    # openをモックしてTypeErrorを発生させ、except (TypeError, AttributeError) を通す
    with patch("builtins.open", side_effect=TypeError("Type error")):
        logs = scorer._load_degradation_log("dummy.mp4")
        assert logs == []

@patch("backend.services.nhk_quality_scorer.os.path.exists")
@patch("backend.services.nhk_quality_scorer.subprocess.run")
def test_score_audio_exceptions(mock_run, mock_exists):
    mock_exists.return_value = True
    scorer = NHKQualityScorer()
    
    # AttributeErrorを発生させて except (KeyError, IndexError, AttributeError) を通す
    # _validate_audio_stream内での json.loads 結果が None の場合に AttributeError を起こす
    mock_run.return_value = MagicMock(returncode=0, stdout="null") 
    
    report = scorer.score("dummy.mp4", None)
    assert report.audio_balance.score == 50.0
    assert "音声分析失敗" in report.audio_balance.suggestion

@patch("backend.services.nhk_quality_scorer.os.path.exists")
@patch("backend.services.nhk_quality_scorer.subprocess.run")
def test_score_cuts_exceptions(mock_run, mock_exists):
    mock_exists.return_value = True
    scorer = NHKQualityScorer()
    
    # AttributeErrorを発生させて except (KeyError, IndexError, AttributeError) を通す
    # _get_video_duration内での json.loads 結果が None の場合に AttributeError を起こす
    mock_run.return_value = MagicMock(returncode=0, stdout="null") 
    
    report = scorer.score("dummy.mp4", None)
    assert report.cut_rhythm.score == 50.0
    assert "カット分析失敗" in report.cut_rhythm.suggestion
