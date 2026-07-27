import sys
import os
import json
import logging
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

# パスの解決
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
backend_dir = os.path.join(project_root, "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.template_recommender import TemplateRecommender

@pytest.fixture
def recommender():
    return TemplateRecommender()

def test_clean_segments_valid(recommender):
    segments = [
        {"start": 1.0, "end": 3.0, "text": "Hello"},
        {"start": "4.5", "end": "6.0", "text": "World"}
    ]
    cleaned = recommender._clean_segments(segments)
    assert len(cleaned) == 2
    assert cleaned[0] == {"start": 1.0, "end": 3.0, "text": "Hello"}
    assert cleaned[1] == {"start": 4.5, "end": 6.0, "text": "World"}

def test_clean_segments_invalid_types(recommender):
    segments = [
        "not_a_dict",
        {"start": None, "end": None, "text": None},
        {"start": "invalid_float", "end": "invalid_float", "text": 123}
    ]
    cleaned = recommender._clean_segments(segments)
    assert len(cleaned) == 2
    # 1つ目は非dictなのでスキップされる
    assert cleaned[0] == {"start": 0.0, "end": 0.0, "text": ""}
    assert cleaned[1] == {"start": 0.0, "end": 0.0, "text": "123"}

def test_analyze_segments_empty(recommender):
    # segments が None または空の場合
    assert recommender.analyze_segments([]) == {
        "speech_density": 0,
        "avg_silence": 0,
        "avg_segment_chars": 0,
        "tempo_fast_ratio": 0,
    }
    # クレンジング後に空になる場合
    assert recommender.analyze_segments(["not_a_dict"]) == {
        "speech_density": 0,
        "avg_silence": 0,
        "avg_segment_chars": 0,
        "tempo_fast_ratio": 0,
    }

def test_analyze_segments_duration_estimation(recommender):
    # duration が 0 以下のとき、最終セグメントの end から推定
    segments = [
        {"start": 0.0, "end": 10.0, "text": "Test"}
    ]
    res = recommender.analyze_segments(segments, total_duration_seconds=0)
    # duration = 10秒 = 1/6分。speech_density = 1 / (1/6) = 6.0
    assert res["speech_density"] == 6.0

    # duration が型エラーのときも 0.0 になり自動推定される
    res = recommender.analyze_segments(segments, total_duration_seconds="invalid_float")
    assert res["speech_density"] == 6.0

def test_analyze_segments_metrics_calculation(recommender):
    # 複数のセグメントで無音時間やテンポ比率を測定
    segments = [
        {"start": 1.0, "end": 2.0, "text": "Short"},     # 1秒
        {"start": 3.0, "end": 6.0, "text": "Longer"},     # 3秒
        {"start": 8.0, "end": 9.5, "text": "Short2"},    # 1.5秒
    ]
    # total_duration = 10.0秒 = 1/6分 = 0.1666分
    # speech_density = 3 / (10/60) = 18.0
    # silences gap: 
    #   gap1: 3.0 - 2.0 = 1.0
    #   gap2: 8.0 - 6.0 = 2.0
    #   avg_silence = (1.0 + 2.0) / 2 = 1.5
    # char counts: len("Short")=5, len("Longer")=6, len("Short2")=6. avg = 17 / 3 = 5.666 -> 5.7
    # short segments (<2.0s):
    #   gap1 (1.0s) -> short (1.0 - 2.0) = 1.0s (short)
    #   gap2 (3.0s) -> long (3.0 - 6.0) = 3.0s (not short)
    #   gap3 (1.5s) -> short (8.0 - 9.5) = 1.5s (short)
    #   tempo_fast_ratio = 2 / 3 = 0.67
    res = recommender.analyze_segments(segments, total_duration_seconds=10.0)
    assert res == {
        "speech_density": 18.0,
        "avg_silence": 1.5,
        "avg_segment_chars": 5.7,
        "tempo_fast_ratio": 0.67
    }

def test_scoring_methods(recommender):
    # _score_speech_density
    # 範囲内: 3 <= 5 <= 12
    score, reason = recommender._score_speech_density(5.0, 3.0, 12.0)
    assert score == 30.0
    assert "発話密度 5.0/分 が範囲内" in reason

    # 下振れ: density < min_val
    score, reason = recommender._score_speech_density(1.0, 3.0, 12.0)
    # 30.0 - (3.0 - 1.0) * 3 = 24.0
    assert score == 24.0
    assert reason is None

    # 上振れ: density > max_val
    score, reason = recommender._score_speech_density(15.0, 3.0, 12.0)
    # 30.0 - (15.0 - 12.0) * 2 = 24.0
    assert score == 24.0
    assert reason is None

    # スコア下限は 0.0
    score, reason = recommender._score_speech_density(100.0, 3.0, 12.0)
    assert score == 0.0

    # _score_silence
    # 範囲内
    score, reason = recommender._score_silence(5.0, 2.0, 10.0)
    assert score == 25.0
    assert "無音間隔 5.0秒 が範囲内" in reason

    # 下振れ: avg_silence < min_val
    score, reason = recommender._score_silence(1.0, 2.0, 10.0)
    # 25.0 - (2.0 - 1.0) * 5 = 20.0
    assert score == 20.0

    # 上振れ: avg_silence > max_val
    score, reason = recommender._score_silence(12.0, 2.0, 10.0)
    # 25.0 - (12.0 - 10.0) * 3 = 19.0
    assert score == 19.0

    # スコア下限 0.0
    score, _ = recommender._score_silence(100.0, 2.0, 10.0)
    assert score == 0.0

    # _score_segment_chars
    score, reason = recommender._score_segment_chars(20.0, 15.0, 50.0)
    assert score == 25.0
    assert "平均文字数 20.0文字 が範囲内" in reason

    score, reason = recommender._score_segment_chars(5.0, 15.0, 50.0)
    assert score == 0.0
    assert reason is None

    # _score_tempo
    score, reason = recommender._score_tempo(0.2, 0.3)
    assert score == 20.0
    assert "テンポ比率 0.2 が基準内" in reason

    score, reason = recommender._score_tempo(0.5, 0.3)
    assert score == 0.0
    assert reason is None

def test_calculate_scores_priority_tie(recommender):
    # スコアが完全に同点の場合に、priorityが高いほうが選ばれることを確認
    # 各テンプレートプロファイルを上書きしてスコアリング結果が同点になるように仕込む
    recommender.TEMPLATE_PROFILES = {
        "tmpl_low_priority": {
            "speech_density_range": (0, 100),
            "avg_silence_range": (0, 100),
            "avg_segment_chars_range": (0, 100),
            "tempo_fast_ratio_max": 1.0,
            "priority": 1,
        },
        "tmpl_high_priority": {
            "speech_density_range": (0, 100),
            "avg_silence_range": (0, 100),
            "avg_segment_chars_range": (0, 100),
            "tempo_fast_ratio_max": 1.0,
            "priority": 10,
        }
    }
    segments = [{"start": 0, "end": 5, "text": "Hello"}]
    # apply_learning_bias は Mock でそのまま返すようにする
    with patch.object(recommender, "_apply_learning_bias", side_effect=lambda best_id, scores: best_id):
        best_id, scores = recommender._calculate_scores(segments, total_duration_seconds=5)
        # 同点なので priority 10 の tmpl_high_priority が選ばれるべき
        assert best_id == "tmpl_high_priority"

def test_recommend_success(recommender):
    # 正常系の recommend 呼び出し
    segments = [{"start": 0, "end": 2, "text": "Hello"}]
    with patch.object(recommender, "_calculate_scores") as mock_calc:
        mock_calc.return_value = ("nhk_documentary", {"nhk_documentary": {"score": 100.0, "reasons": ["Test"], "profile": {}}})
        best_id, details = recommender.recommend(segments, total_duration_seconds=10)
        assert best_id == "nhk_documentary"
        assert details["score"] == 100.0

def test_apply_learning_bias_no_history(recommender):
    # evolution_log.json が存在しない場合
    with patch("pathlib.Path.exists", return_value=False):
        scores = {"nhk_documentary": {"score": 50.0, "reasons": []}}
        best_id = recommender._apply_learning_bias("nhk_documentary", scores)
        assert best_id == "nhk_documentary"

def test_apply_learning_bias_success(recommender):
    # evolution_log.json が正常に存在し、バイアスが適用されるケース
    dummy_history = {
        "template_selections": [
            {"template_id": "nhk_documentary", "satisfaction": 5}, # 高評価 -> +15, count=1 (+1)
            {"template_id": "nhk_documentary", "satisfaction": 4}, # 高評価 -> +15, count=2 (+2)
            {"template_id": "mrbeast_entertainment", "satisfaction": 2}, # 低評価 -> -10, count=1 (+1)
            {"template_id": "hikakin_vlog", "satisfaction": None}, # satisfaction が None -> count=1 (+1), avg = 3 (補正なし)
            {"template_id": "asmr_relaxation", "satisfaction": "invalid"}, # satisfaction が型エラー -> count=1 (+1), avg = 3 (補正なし)
            {"template_id": "asmr_relaxation", "satisfaction": 6} # satisfaction が範囲外 -> count=2 (+2), avg = 3 (319行目をカバー)
        ]
    }
    
    scores = {
        "nhk_documentary": {"score": 30.0, "reasons": []},
        "mrbeast_entertainment": {"score": 50.0, "reasons": []},
        "hikakin_vlog": {"score": 40.0, "reasons": []},
        "asmr_relaxation": {"score": 10.0, "reasons": []}
    }

    with patch("pathlib.Path.exists", return_value=True):
        with patch("pathlib.Path.read_text", return_value=json.dumps(dummy_history)):
            best_id = recommender._apply_learning_bias("mrbeast_entertainment", scores)
            
            # スコア変化の確認
            assert best_id == "nhk_documentary"
            assert scores["nhk_documentary"]["score"] == 47.0
            
            # 理由の追加チェック
            assert any("📈 過去2回選択・高評価" in r for r in scores["nhk_documentary"]["reasons"])
            assert any("📉 過去に低評価" in r for r in scores["mrbeast_entertainment"]["reasons"])

def test_apply_learning_bias_exceptions(recommender):
    scores = {"nhk_documentary": {"score": 50.0, "reasons": []}}

    # 1. JSONDecodeError
    with patch("pathlib.Path.exists", return_value=True):
        with patch("pathlib.Path.read_text", return_value="{corrupted json"):
            best_id = recommender._apply_learning_bias("nhk_documentary", scores)
            assert best_id == "nhk_documentary"

    # 2. OSError
    with patch("pathlib.Path.exists", return_value=True):
        with patch("pathlib.Path.read_text", side_effect=OSError("Read error")):
            best_id = recommender._apply_learning_bias("nhk_documentary", scores)
            assert best_id == "nhk_documentary"

    # 3. KeyError / TypeError
    # JSON構造自体は正しいが、template_selections の中身が辞書ではない等
    dummy_bad_structure = {
        "template_selections": [
            "not_a_dict",
            {"template_id": 123},  # template_id が str でない
            {"template_id": None},
        ]
    }
    with patch("pathlib.Path.exists", return_value=True):
        with patch("pathlib.Path.read_text", return_value=json.dumps(dummy_bad_structure)):
            best_id = recommender._apply_learning_bias("nhk_documentary", scores)
            assert best_id == "nhk_documentary"

    # template_selections が list でない場合
    dummy_bad_structure_2 = {
        "template_selections": "not_a_list"
    }
    with patch("pathlib.Path.exists", return_value=True):
        with patch("pathlib.Path.read_text", return_value=json.dumps(dummy_bad_structure_2)):
            best_id = recommender._apply_learning_bias("nhk_documentary", scores)
            assert best_id == "nhk_documentary"

    # data が dict でない場合（リストなど）
    with patch("pathlib.Path.exists", return_value=True):
        with patch("pathlib.Path.read_text", return_value="[]"):
            best_id = recommender._apply_learning_bias("nhk_documentary", scores)
            assert best_id == "nhk_documentary"

    # 4. 想定外の例外 (Exception)
    # 例えば Path.read_text が RuntimeError を投げる
    with patch("pathlib.Path.exists", return_value=True):
        with patch("pathlib.Path.read_text", side_effect=RuntimeError("Unexpected error")):
            best_id = recommender._apply_learning_bias("nhk_documentary", scores)
            assert best_id == "nhk_documentary"

    # 5. 明示的に KeyError / TypeError を発生させる (361行目をカバー)
    # get メソッドで KeyError / TypeError を発生させる dict 継承 Mock を仕込む
    class BadEntry(dict):
        def __init__(self, exc_type):
            super().__init__()
            self.exc_type = exc_type
        def get(self, *args, **kwargs):
            raise self.exc_type("Simulated error")

    for exc in [TypeError, KeyError]:
        dummy_err_structure = {
            "template_selections": [
                BadEntry(exc)
            ]
        }
        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.read_text", return_value=json.dumps({"dummy": "value"})):
                # JSONデコードは辞書だが、history取得時に強制的にBadEntryが含まれるようにモックする
                with patch("json.loads", return_value=dummy_err_structure):
                    best_id = recommender._apply_learning_bias("nhk_documentary", scores)
                    assert best_id == "nhk_documentary"

def test_recommend_with_alternatives(recommender):
    # 代替案を含む推奨
    segments = [{"start": 0, "end": 2, "text": "Hello"}]
    with patch.object(recommender, "_calculate_scores") as mock_calc:
        mock_calc.return_value = (
            "nhk_documentary",
            {
                "nhk_documentary": {"score": 90.0, "reasons": [], "profile": {}},
                "mrbeast_entertainment": {"score": 50.0, "reasons": [], "profile": {}},
                "hikakin_vlog": {"score": 70.0, "reasons": [], "profile": {}},
                "asmr_relaxation": {"score": 20.0, "reasons": [], "profile": {}},
            }
        )
        
        alternatives = recommender.recommend_with_alternatives(segments, total_duration_seconds=10)
        
        # スコア順にソートされていること: nhk(90) -> hikakin(70) -> mrbeast(50) -> asmr(20)
        assert len(alternatives) == 4
        assert alternatives[0]["template_id"] == "nhk_documentary"
        assert alternatives[0]["is_recommended"] is True
        assert alternatives[1]["template_id"] == "hikakin_vlog"
        assert alternatives[1]["is_recommended"] is False
        assert alternatives[2]["template_id"] == "mrbeast_entertainment"
        assert alternatives[3]["template_id"] == "asmr_relaxation"
