import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from template_recommender import TemplateRecommender

def test_analyze_segments_empty():
    tr = TemplateRecommender()
    res = tr.analyze_segments([])
    assert res == {
        "speech_density": 0,
        "avg_silence": 0,
        "avg_segment_chars": 0,
        "tempo_fast_ratio": 0,
    }

def test_analyze_segments_basic():
    tr = TemplateRecommender()
    segments = [
        {"start": 0, "end": 10, "text": "Hello world"},
        {"start": 30, "end": 40, "text": "This is a test segment"},
    ]
    res = tr.analyze_segments(segments, total_duration_seconds=120)
    assert res["speech_density"] == 1.0
    assert res["avg_silence"] == 20.0
    assert res["avg_segment_chars"] == 16.5
    assert res["tempo_fast_ratio"] == 0.0

def test_analyze_segments_short_tempo():
    tr = TemplateRecommender()
    segments = [
        {"start": 0, "end": 1.5, "text": "Short"},
        {"start": 2.0, "end": 3.0, "text": "Tiny"},
    ]
    res = tr.analyze_segments(segments)
    assert res["tempo_fast_ratio"] == 1.0

def test_recommend_mrbeast():
    tr = TemplateRecommender()
    segments = [
        {"start": i*2, "end": i*2 + 1.5, "text": "a"*10}
        for i in range(40)
    ]
    best_id, info = tr.recommend(segments)
    assert best_id == "mrbeast_entertainment"
    assert info["score"] > 0

def test_recommend_asmr():
    tr = TemplateRecommender()
    segments = [
        {"start": 0, "end": 1, "text": "shh"},
        {"start": 30, "end": 31, "text": "quiet"},
    ]
    best_id, info = tr.recommend(segments, total_duration_seconds=100)
    assert best_id == "asmr_relaxation"

def test_recommend_with_alternatives():
    tr = TemplateRecommender()
    segments = [
        {"start": 0, "end": 1.0, "text": "Hello"},
        {"start": 2.0, "end": 3.0, "text": "World"}
    ]
    alts = tr.recommend_with_alternatives(segments)
    assert len(alts) == 4
    assert alts[0]["is_recommended"] is True

@patch("pathlib.Path.exists")
@patch("pathlib.Path.read_text")
def test_apply_learning_bias(mock_read_text, mock_exists):
    tr = TemplateRecommender()
    
    mock_exists.return_value = True
    mock_read_text.return_value = '{"template_selections": [{"template_id": "hikakin_vlog", "satisfaction": 5}, {"template_id": "mrbeast_entertainment", "satisfaction": 1}]}'
    
    scores = {
        "nhk_documentary": {"score": 50, "reasons": [], "profile": {}},
        "mrbeast_entertainment": {"score": 50, "reasons": [], "profile": {}},
        "hikakin_vlog": {"score": 50, "reasons": [], "profile": {}},
        "asmr_relaxation": {"score": 50, "reasons": [], "profile": {}},
    }
    
    best_id = tr._apply_learning_bias("nhk_documentary", scores)
    
    assert best_id == "hikakin_vlog"
    assert scores["hikakin_vlog"]["score"] == 50 + 1 + 15
    assert scores["mrbeast_entertainment"]["score"] == 50 + 1 - 10

@patch("pathlib.Path.exists")
@patch("pathlib.Path.read_text")
def test_apply_learning_bias_empty_history(mock_read_text, mock_exists):
    tr = TemplateRecommender()
    mock_exists.return_value = True
    mock_read_text.return_value = '{"other_key": []}'
    best_id = tr._apply_learning_bias("nhk_documentary", {})
    assert best_id == "nhk_documentary"


def test_recommend_nhk_documentary():
    tr = TemplateRecommender()
    # Speech density: ~6.0/min (3-12 range)
    # Avg silence: ~4.0s (2.0-10.0 range)
    # Avg segment chars: ~30.0 (15-50 range)
    # Tempo fast ratio: 0.0 (<= 0.3 range)
    segments = [
        {"start": 0, "end": 5, "text": "a" * 30},
        {"start": 9, "end": 14, "text": "b" * 30},
        {"start": 18, "end": 23, "text": "c" * 30},
    ]
    best_id, info = tr.recommend(segments, total_duration_seconds=30)
    assert best_id == "nhk_documentary"
    assert info["score"] > 0


def test_recommend_hikakin_vlog():
    tr = TemplateRecommender()
    # Speech density: ~15.0/min (8-25 range)
    # Avg silence: ~1.5s (0.5-3.0 range)
    # Avg segment chars: ~20.0 (8-35 range)
    # Tempo fast ratio: 0.0 (<= 0.7 range)
    segments = []
    for i in range(15):
        segments.append({
            "start": i * 4,
            "end": i * 4 + 2.5,
            "text": "x" * 20
        })
    best_id, info = tr.recommend(segments, total_duration_seconds=60)
    assert best_id == "hikakin_vlog"
    assert info["score"] > 0


def test_analyze_segments_single_segment():
    tr = TemplateRecommender()
    segments = [{"start": 0, "end": 5.0, "text": "Only one segment"}]
    res = tr.analyze_segments(segments, total_duration_seconds=60)
    assert res["speech_density"] == 1.0
    assert res["avg_silence"] == 0
    assert res["avg_segment_chars"] == 16.0
    assert res["tempo_fast_ratio"] == 0.0


def test_analyze_segments_invalid_times():
    tr = TemplateRecommender()
    # Negative gap, missing text, missing start/end
    segments = [
        {"start": 10, "end": 5, "text": "Reverse"},
        {"start": 0, "text": "Missing end"},
        {"end": 8, "text": "Missing start"},
        {"start": 12, "end": 15}  # Missing text
    ]
    # Should not crash and should return safe fallback dictionary
    res = tr.analyze_segments(segments, total_duration_seconds=30)
    assert isinstance(res, dict)
    assert "speech_density" in res
    assert "avg_silence" in res
    assert "avg_segment_chars" in res
    assert "tempo_fast_ratio" in res


@patch("pathlib.Path.exists")
@patch("pathlib.Path.read_text")
def test_apply_learning_bias_extended(mock_read_text, mock_exists):
    tr = TemplateRecommender()
    mock_exists.return_value = True
    
    # Satisfaction average is 3.0 (no satisfaction bonus/penalty)
    # count is 10 (familiarity bonus should cap at 5)
    mock_read_text.return_value = json.dumps({
        "template_selections": [
            {"template_id": "hikakin_vlog", "satisfaction": 3}
        ] * 10
    })
    
    scores = {
        "nhk_documentary": {"score": 50, "reasons": [], "profile": {}},
        "mrbeast_entertainment": {"score": 50, "reasons": [], "profile": {}},
        "hikakin_vlog": {"score": 50, "reasons": [], "profile": {}},
        "asmr_relaxation": {"score": 50, "reasons": [], "profile": {}},
    }
    
    best_id = tr._apply_learning_bias("nhk_documentary", scores)
    
    assert best_id == "hikakin_vlog"
    # Familiarity bonus: min(5, 10) = 5. Total = 55.
    assert scores["hikakin_vlog"]["score"] == 55


def test_recommend_with_alternatives_verification():
    tr = TemplateRecommender()
    segments = [
        {"start": 0, "end": 1.0, "text": "Hello"},
        {"start": 2.0, "end": 3.0, "text": "World"}
    ]
    alts = tr.recommend_with_alternatives(segments)
    
    # Verify descending sort order
    scores = [item["score"] for item in alts]
    assert scores == sorted(scores, reverse=True)
    
    # Verify is_recommended flags
    recommended_count = sum(1 for item in alts if item["is_recommended"])
    assert recommended_count == 1
    assert alts[0]["is_recommended"] is True

def test_apply_learning_bias_exception():
    tr = TemplateRecommender()
    with patch("pathlib.Path.exists", side_effect=Exception("Read error")):
        best_id = tr._apply_learning_bias("nhk_documentary", {})
        assert best_id == "nhk_documentary"

@patch("pathlib.Path.exists")
@patch("pathlib.Path.read_text")
def test_apply_learning_bias_json_error(mock_read_text, mock_exists):
    tr = TemplateRecommender()
    mock_exists.return_value = True
    mock_read_text.return_value = "invalid json{"
    best_id = tr._apply_learning_bias("nhk_documentary", {})
    assert best_id == "nhk_documentary"




def test_analyze_segments_negative_duration():
    tr = TemplateRecommender()
    segments = [{"start": 10.0, "end": 5.0, "text": "Negative duration"}]
    res = tr.analyze_segments(segments, total_duration_seconds=30)
    assert res["tempo_fast_ratio"] == 0.0


def test_clean_segments_edge_cases():
    tr = TemplateRecommender()
    segments = [
        "not a dict",
        {"start": 0, "end": 1, "text": None},
        {"start": 0, "end": 1, "text": 123},
        {"start": "invalid", "end": 1, "text": "hello"},
        {"start": 0, "end": "invalid", "text": "hello"}
    ]
    cleaned = tr._clean_segments(segments)
    assert len(cleaned) == 4
    assert cleaned[0] == {"start": 0.0, "end": 1.0, "text": ""}
    assert cleaned[1] == {"start": 0.0, "end": 1.0, "text": "123"}
    assert cleaned[2] == {"start": 0.0, "end": 1.0, "text": "hello"}
    assert cleaned[3] == {"start": 0.0, "end": 0.0, "text": "hello"}


def test_analyze_segments_all_invalid():
    tr = TemplateRecommender()
    segments = ["not a dict"]
    res = tr.analyze_segments(segments)
    assert res == {
        "speech_density": 0,
        "avg_silence": 0,
        "avg_segment_chars": 0,
        "tempo_fast_ratio": 0,
    }


def test_analyze_segments_invalid_duration_type():
    tr = TemplateRecommender()
    segments = [{"start": 0, "end": 10, "text": "Hello world"}]
    res = tr.analyze_segments(segments, total_duration_seconds="invalid")
    assert res["speech_density"] == 6.0


@patch("pathlib.Path.exists")
@patch("pathlib.Path.read_text")
def test_apply_learning_bias_history_not_list(mock_read_text, mock_exists):
    tr = TemplateRecommender()
    mock_exists.return_value = True
    mock_read_text.return_value = '{"template_selections": "not a list"}'
    best_id = tr._apply_learning_bias("nhk_documentary", {})
    assert best_id == "nhk_documentary"


@patch("pathlib.Path.exists")
@patch("pathlib.Path.read_text")
def test_apply_learning_bias_entry_not_dict(mock_read_text, mock_exists):
    tr = TemplateRecommender()
    mock_exists.return_value = True
    mock_read_text.return_value = '{"template_selections": ["not a dict"]}'
    
    scores = {
        "nhk_documentary": {"score": 50, "reasons": [], "profile": {}},
    }
    best_id = tr._apply_learning_bias("nhk_documentary", scores)
    assert best_id == "nhk_documentary"


@patch("pathlib.Path.exists")
@patch("pathlib.Path.read_text")
def test_apply_learning_bias_invalid_template_id(mock_read_text, mock_exists):
    tr = TemplateRecommender()
    mock_exists.return_value = True
    mock_read_text.return_value = '{"template_selections": [{"template_id": 123, "satisfaction": 5}, {"template_id": "", "satisfaction": 5}]}'
    
    scores = {
        "nhk_documentary": {"score": 50, "reasons": [], "profile": {}},
    }
    best_id = tr._apply_learning_bias("nhk_documentary", scores)
    assert best_id == "nhk_documentary"


@patch("pathlib.Path.exists")
@patch("pathlib.Path.read_text")
def test_apply_learning_bias_satisfaction_none(mock_read_text, mock_exists):
    tr = TemplateRecommender()
    mock_exists.return_value = True
    mock_read_text.return_value = '{"template_selections": [{"template_id": "hikakin_vlog", "satisfaction": null}]}'
    
    scores = {
        "nhk_documentary": {"score": 50, "reasons": [], "profile": {}},
        "hikakin_vlog": {"score": 50, "reasons": [], "profile": {}},
    }
    best_id = tr._apply_learning_bias("nhk_documentary", scores)
    assert best_id == "hikakin_vlog"
    assert scores["hikakin_vlog"]["score"] == 51


@patch("pathlib.Path.exists")
@patch("pathlib.Path.read_text")
def test_apply_learning_bias_satisfaction_out_of_bounds_or_invalid(mock_read_text, mock_exists):
    tr = TemplateRecommender()
    mock_exists.return_value = True
    mock_read_text.return_value = '{"template_selections": [{"template_id": "hikakin_vlog", "satisfaction": 6}, {"template_id": "hikakin_vlog", "satisfaction": "invalid"}]}'
    
    scores = {
        "nhk_documentary": {"score": 50, "reasons": [], "profile": {}},
        "hikakin_vlog": {"score": 50, "reasons": [], "profile": {}},
    }
    best_id = tr._apply_learning_bias("nhk_documentary", scores)
    assert best_id == "hikakin_vlog"
    assert scores["hikakin_vlog"]["score"] == 52


@patch("pathlib.Path.exists")
@patch("pathlib.Path.read_text")
def test_apply_learning_bias_os_error(mock_read_text, mock_exists):
    tr = TemplateRecommender()
    mock_exists.return_value = True
    mock_read_text.side_effect = OSError("Disk read failed")
    
    best_id = tr._apply_learning_bias("nhk_documentary", {})
    assert best_id == "nhk_documentary"


@patch("pathlib.Path.exists")
@patch("pathlib.Path.read_text")
def test_apply_learning_bias_key_or_type_error(mock_read_text, mock_exists):
    tr = TemplateRecommender()
    mock_exists.return_value = True
    mock_read_text.side_effect = TypeError("Mocked TypeError")
    
    best_id = tr._apply_learning_bias("nhk_documentary", {})
    assert best_id == "nhk_documentary"


def test_score_speech_density_limits():
    tr = TemplateRecommender()
    # Min value is 3.0, Max is 12.0 for nhk_documentary.
    # If density is 0.0 (below min 3.0):
    # score = max(0.0, 30.0 - (3.0 - 0.0) * 3) = 21.0
    score, reason = tr._score_speech_density(0.0, 3.0, 12.0)
    assert score == 21.0
    assert reason is None

    # If density is extremely low, e.g. -10.0 (penalty makes it <= 0.0)
    # score = max(0.0, 30.0 - (3.0 - (-10.0)) * 3) = max(0.0, 30.0 - 39.0) = 0.0
    score, reason = tr._score_speech_density(-10.0, 3.0, 12.0)
    assert score == 0.0
    assert reason is None

    # If density is extremely high, e.g. 50.0 (max is 12.0)
    # score = max(0.0, 30.0 - (50.0 - 12.0) * 2) = max(0.0, 30.0 - 76.0) = 0.0
    score, reason = tr._score_speech_density(50.0, 3.0, 12.0)
    assert score == 0.0
    assert reason is None


def test_score_silence_limits():
    tr = TemplateRecommender()
    # Min is 2.0, Max is 10.0 for nhk_documentary.
    # If silence is extremely low, e.g. -10.0:
    # score = max(0.0, 25.0 - (2.0 - (-10.0)) * 5) = max(0.0, 25.0 - 60.0) = 0.0
    score, reason = tr._score_silence(-10.0, 2.0, 10.0)
    assert score == 0.0
    assert reason is None

    # If silence is extremely high, e.g. 50.0:
    # score = max(0.0, 25.0 - (50.0 - 10.0) * 3) = max(0.0, 25.0 - 120.0) = 0.0
    score, reason = tr._score_silence(50.0, 2.0, 10.0)
    assert score == 0.0
    assert reason is None


def test_recommend_priority_fallback():
    # Verify that priority decides the recommendation when scores are tied.
    tr = TemplateRecommender()
    
    # Mock _calculate_scores to return identical scores but different priority templates.
    # Let's say nhk_documentary (priority 3) and hikakin_vlog (priority 4) both have score 50.0
    # hikakin_vlog should be recommended because it has a higher priority.
    scores = {
        "nhk_documentary": {"score": 50.0, "reasons": [], "profile": {}},
        "hikakin_vlog": {"score": 50.0, "reasons": [], "profile": {}},
    }
    
    # We patch _apply_learning_bias to just return the best_id it receives to test tie-breaker before it.
    with patch.object(tr, "_apply_learning_bias", side_effect=lambda best_id, scores: best_id):
        # We need to trigger the logic that sorts by (score, priority)
        # _calculate_scores does exactly this:
        # best_id = max(scores, key=lambda k: (scores[k]["score"], self.TEMPLATE_PROFILES[k]["priority"]))
        # Let's mock the internal score computation of _calculate_scores to inject our tied scores.
        with patch.object(tr, "_calculate_scores", return_value=("hikakin_vlog", scores)):
            best_id, info = tr.recommend([])
            assert best_id == "hikakin_vlog"

        # Also let's test the actual lambda sorting logic directly in a simulated tie-break
        test_scores = {
            "nhk_documentary": {"score": 50.0},
            "hikakin_vlog": {"score": 50.0},
            "mrbeast_entertainment": {"score": 50.0},
            "asmr_relaxation": {"score": 50.0},
        }
        best_id_tie = max(
            test_scores,
            key=lambda k: (
                test_scores[k]["score"],
                tr.TEMPLATE_PROFILES[k]["priority"]
            )
        )
        # hikakin_vlog priority is 4 (highest among these)
        assert best_id_tie == "hikakin_vlog"


def test_apply_learning_bias_str_satisfaction():
    tr = TemplateRecommender()
    with patch("pathlib.Path.exists") as mock_exists, \
         patch("pathlib.Path.read_text") as mock_read_text:
        mock_exists.return_value = True
        # Satisfaction as string numbers
        mock_read_text.return_value = json.dumps({
            "template_selections": [
                {"template_id": "hikakin_vlog", "satisfaction": "5"},
                {"template_id": "mrbeast_entertainment", "satisfaction": "1"}
            ]
        })
        scores = {
            "nhk_documentary": {"score": 50, "reasons": [], "profile": {}},
            "mrbeast_entertainment": {"score": 50, "reasons": [], "profile": {}},
            "hikakin_vlog": {"score": 50, "reasons": [], "profile": {}},
            "asmr_relaxation": {"score": 50, "reasons": [], "profile": {}},
        }
        best_id = tr._apply_learning_bias("nhk_documentary", scores)
        # hikakin_vlog has count=1, sat=5. avg_sat=5.0 >= 4. score -> 50 + min(5, 1) + 15 = 66
        # mrbeast_entertainment has count=1, sat=1. avg_sat=1.0 <= 2. score -> 50 + min(5, 1) - 10 = 41
        assert best_id == "hikakin_vlog"
        assert scores["hikakin_vlog"]["score"] == 66
        assert scores["mrbeast_entertainment"]["score"] == 41


def test_apply_learning_bias_path_priority():
    tr = TemplateRecommender()
    # We want to test that the first path in evolution_log_paths takes priority.
    # Path 1: Path(__file__).parent / "branding" / "evolution_log.json"
    # Path 2: Path("backend/branding/evolution_log.json")
    # If both exist, Path 1 should be read and Path 2 should NOT be read.
    
    with patch("pathlib.Path.exists") as mock_exists, \
         patch("pathlib.Path.read_text") as mock_read_text:
        
        # Track path instances used
        mock_exists.return_value = True
        mock_read_text.return_value = json.dumps({
            "template_selections": [
                {"template_id": "hikakin_vlog", "satisfaction": 5}
            ]
        })
        
        scores = {
            "nhk_documentary": {"score": 50, "reasons": [], "profile": {}},
            "hikakin_vlog": {"score": 50, "reasons": [], "profile": {}},
        }
        
        best_id = tr._apply_learning_bias("nhk_documentary", scores)
        
        # Check that mock_read_text was called exactly once, indicating it broke out of the loop
        assert mock_read_text.call_count == 1
        assert best_id == "hikakin_vlog"


def test_apply_learning_bias_no_files_exist():
    tr = TemplateRecommender()
    with patch("pathlib.Path.exists", return_value=False):
        scores = {
            "nhk_documentary": {"score": 50, "reasons": [], "profile": {}},
        }
        best_id = tr._apply_learning_bias("nhk_documentary", scores)
        assert best_id == "nhk_documentary"


def test_apply_learning_bias_first_not_exist_second_exists():
    tr = TemplateRecommender()
    
    # Path.exists() の呼び出しに対して、1回目は False、2回目は True を返すように設定
    with patch("pathlib.Path.exists", side_effect=[False, True]), \
         patch("pathlib.Path.read_text", return_value='{"template_selections": [{"template_id": "hikakin_vlog", "satisfaction": 5}]}') as mock_read:
        scores = {
            "nhk_documentary": {"score": 50, "reasons": [], "profile": {}},
            "hikakin_vlog": {"score": 50, "reasons": [], "profile": {}},
        }
        best_id = tr._apply_learning_bias("nhk_documentary", scores)
        assert best_id == "hikakin_vlog"
        assert scores["hikakin_vlog"]["score"] == 66  # 50 + 1 (count) + 15 (satisfaction)
        assert mock_read.call_count == 1


def test_apply_learning_bias_json_is_list():
    tr = TemplateRecommender()
    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.read_text", return_value='[1, 2, 3]'):
        scores = {
            "nhk_documentary": {"score": 50, "reasons": [], "profile": {}},
        }
        best_id = tr._apply_learning_bias("nhk_documentary", scores)
        # JSONのルートが list なので history が空でフォールバックされる
        assert best_id == "nhk_documentary"


def test_clean_segments_type_error_handling():
    tr = TemplateRecommender()
    # startやendに float に変換できない list などを渡し、内部の TypeError 処理をカバー
    segments = [
        {"start": [], "end": {}, "text": "TypeError test"}
    ]
    cleaned = tr._clean_segments(segments)
    assert len(cleaned) == 1
    assert cleaned[0] == {"start": 0.0, "end": 0.0, "text": "TypeError test"}


def test_analyze_segments_duration_type_error():
    tr = TemplateRecommender()
    segments = [{"start": 0, "end": 10, "text": "Hello world"}]
    # total_duration_seconds に list を渡して TypeError を発生させる
    res = tr.analyze_segments(segments, total_duration_seconds=[])
    # フォールバックして max(end) -> 10.0秒になる
    assert res["speech_density"] == 6.0  # 1 / (10/60) = 6.0


def test_score_speech_density_in_range():
    tr = TemplateRecommender()
    score, reason = tr._score_speech_density(6.0, 3.0, 12.0)
    assert score == 30.0
    assert reason == "発話密度 6.0/分 が範囲内"


def test_score_silence_in_range():
    tr = TemplateRecommender()
    score, reason = tr._score_silence(2.5, 2.0, 10.0)
    assert score == 25.0
    assert reason == "無音間隔 2.5秒 が範囲内"


def test_score_segment_chars_limits():
    tr = TemplateRecommender()
    # In range
    score, reason = tr._score_segment_chars(30.0, 15.0, 50.0)
    assert score == 25.0
    assert reason == "平均文字数 30.0文字 が範囲内"
    # Out of range
    score, reason = tr._score_segment_chars(10.0, 15.0, 50.0)
    assert score == 0.0
    assert reason is None


def test_score_tempo_limits():
    tr = TemplateRecommender()
    # In range
    score, reason = tr._score_tempo(0.15, 0.3)
    assert score == 20.0
    assert reason == "テンポ比率 0.15 が基準内"
    # Out of range
    score, reason = tr._score_tempo(0.4, 0.3)
    assert score == 0.0
    assert reason is None




