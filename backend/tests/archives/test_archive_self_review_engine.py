import pytest
import sys
import os
import json
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

# backend ディレクトリへのパスを通す
backend_dir = Path(__file__).resolve().parents[2]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# モジュールインポート前のモック設定
os.environ["GOOGLE_API_KEY"] = "mock_api_key"

mock_genai_client = MagicMock()
genai_patcher = patch("google.genai.Client", return_value=mock_genai_client)
genai_patcher.start()

model_registry_patcher = patch("model_registry.get_model", return_value="mock-model")
model_registry_patcher.start()

# テスト対象モジュールのインポート
import importlib.util
module_path = backend_dir / "archives" / "archive_stable_v3.0_20260118_0953" / "self_review_engine.py"
spec = importlib.util.spec_from_file_location("self_review_engine_archive", str(module_path))
sre_mod = importlib.util.module_from_spec(spec)
sys.modules["self_review_engine_archive"] = sre_mod
spec.loader.exec_module(sre_mod)

SelfReviewEngine = sre_mod.SelfReviewEngine
ReviewResult = sre_mod.ReviewResult
QualityScore = sre_mod.QualityScore
review_generation = sre_mod.review_generation
review_and_improve_func = sre_mod.review_and_improve

def test_import_and_init():
    engine = SelfReviewEngine()
    assert engine is not None
    assert engine.model == "mock-model"
    assert engine.constitution == {}

def test_load_constitution_exists():
    mock_data = {"constitution_rules": ["rule1"]}
    # Path.exists と open をモック化して憲法のロードをテスト
    with patch.object(Path, "exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=json.dumps(mock_data))):
            engine = SelfReviewEngine()
            assert engine.constitution == mock_data

def test_review_success():
    engine = SelfReviewEngine()
    
    # 正常な JSON レスポンスを返すモック
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "context_fit": 0.9,
        "constitution_fit": 0.85,
        "technical_quality": 0.8,
        "issues": ["issue1"],
        "suggestions": ["suggestion1"]
    })
    mock_genai_client.models.generate_content.return_value = mock_response

    result = engine.review("test content", "telop", {"topic": "test"})
    assert result.passed is True
    assert result.score.context_fit == 0.9
    assert result.score.constitution_fit == 0.85
    assert result.score.technical_quality == 0.8
    assert result.score.overall == pytest.approx(0.85)
    assert result.issues == ["issue1"]
    assert result.suggestions == ["suggestion1"]

def test_review_failure_api_exception():
    engine = SelfReviewEngine()
    
    # APIエラーをシミュレート
    mock_genai_client.models.generate_content.side_effect = Exception("API error")
    
    result = engine.review("test content", "telop", {"topic": "test"})
    # 例外時はフォールバックレビューになり、passed=True, score=0.75になる
    assert result.passed is True
    assert result.score.overall == 0.75
    # side_effect を解除
    mock_genai_client.models.generate_content.side_effect = None

def test_parse_review_invalid_json():
    engine = SelfReviewEngine()
    
    # JSON以外のテキスト (正規表現マッチしない)
    result = engine._parse_review("invalid response text")
    assert result.passed is True
    assert result.score.overall == 0.75

    # 破損したJSON (正規表現マッチするが、JSONDecodeErrorになるケース)
    result = engine._parse_review("{invalid json}")
    assert result.passed is True
    assert result.score.overall == 0.75

def test_parse_review_missing_keys():
    engine = SelfReviewEngine()
    
    # 必要なキーが欠けている場合
    result = engine._parse_review(json.dumps({}))
    assert result.score.context_fit == 0.5
    assert result.score.constitution_fit == 0.5
    assert result.score.technical_quality == 0.5
    assert result.score.overall == 0.5
    assert result.passed is False

def test_parse_review_boundary_values():
    engine = SelfReviewEngine()
    
    # 閾値（context_fit: 0.70, constitution_fit: 0.80, technical_quality: 0.60, overall: 0.70）
    # ちょうど閾値の場合 -> 合格
    passed_data = {
        "context_fit": 0.70,
        "constitution_fit": 0.80,
        "technical_quality": 0.60
    }
    result = engine._parse_review(json.dumps(passed_data))
    assert result.passed is True
    
    # いずれかが閾値未満の場合 -> 不合格
    failed_data1 = {
        "context_fit": 0.69,
        "constitution_fit": 0.80,
        "technical_quality": 0.60
    }
    result = engine._parse_review(json.dumps(failed_data1))
    assert result.passed is False

    failed_data2 = {
        "context_fit": 0.70,
        "constitution_fit": 0.79,
        "technical_quality": 0.60
    }
    result = engine._parse_review(json.dumps(failed_data2))
    assert result.passed is False

def test_review_and_improve_passed_immediately():
    engine = SelfReviewEngine()
    
    # 1回目で合格するレスポンス
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "context_fit": 0.9,
        "constitution_fit": 0.9,
        "technical_quality": 0.9,
        "issues": [],
        "suggestions": []
    })
    
    with patch.object(engine, "review", return_value=ReviewResult(
        passed=True,
        score=QualityScore(0.9, 0.9, 0.9, 0.9),
        issues=[],
        suggestions=[]
    )) as mock_review:
        content, result = engine.review_and_improve("original content", "telop", {})
        assert content == "original content"
        assert result.passed is True
        assert result.improvement_applied is False
        assert len(result.improvement_history) == 0
        mock_review.assert_called_once()

def test_review_and_improve_with_custom_improve_func():
    engine = SelfReviewEngine()
    
    # 1回目は不合格、2回目で合格とするレビュー結果を設定
    r1 = ReviewResult(
        passed=False,
        score=QualityScore(0.5, 0.5, 0.5, 0.5),
        issues=["too short"],
        suggestions=["make it longer"]
    )
    r2 = ReviewResult(
        passed=True,
        score=QualityScore(0.8, 0.8, 0.8, 0.8),
        issues=[],
        suggestions=[]
    )
    
    # review() の戻り値を順に設定
    with patch.object(engine, "review", side_effect=[r1, r2]) as mock_review:
        improve_mock = MagicMock(return_value="improved content")
        content, result = engine.review_and_improve("original content", "telop", {}, improve_func=improve_mock)
        
        assert content == "improved content"
        assert result.passed is True
        assert result.improvement_applied is True
        assert len(result.improvement_history) == 1
        assert result.improvement_history[0]["round"] == 1
        assert result.improvement_history[0]["original_score"] == 0.5
        improve_mock.assert_called_once_with("original content", ["too short"], ["make it longer"])

def test_review_and_improve_max_rounds_reached():
    engine = SelfReviewEngine()
    
    # 常に不合格
    r = ReviewResult(
        passed=False,
        score=QualityScore(0.5, 0.5, 0.5, 0.5),
        issues=["bad"],
        suggestions=["fix"]
    )
    
    with patch.object(engine, "review", return_value=r) as mock_review:
        # デフォルト改善をモック
        with patch.object(engine, "_default_improve", return_value="improved content") as mock_default_improve:
            content, result = engine.review_and_improve("original content", "telop", {})
            assert content == "improved content"
            # MAX_IMPROVEMENT_ROUNDS (3回) + 最後の確認レビュー (1回) = 4回呼ばれる
            assert mock_review.call_count == 4
            assert mock_default_improve.call_count == 3
            assert result.improvement_applied is True
            assert len(result.improvement_history) == 3

def test_default_improve_success_and_failure():
    engine = SelfReviewEngine()
    
    # 改善成功ケース
    mock_response = MagicMock()
    mock_response.text = "improved text"
    mock_genai_client.models.generate_content.return_value = mock_response
    
    r = ReviewResult(passed=False, score=QualityScore(0.5, 0.5, 0.5, 0.5), issues=["i"], suggestions=["s"])
    result_content = engine._default_improve("content", r, {})
    assert result_content == "improved text"
    
    # 改善時APIエラー発生ケース
    mock_genai_client.models.generate_content.side_effect = Exception("Improve error")
    result_content_fail = engine._default_improve("content", r, {})
    # 元のコンテンツが返るはず
    assert result_content_fail == "content"
    mock_genai_client.models.generate_content.side_effect = None

def test_global_functions():
    # review_generation と review_and_improve 簡易関数のテスト
    r = ReviewResult(passed=True, score=QualityScore(0.8, 0.8, 0.8, 0.8))
    
    with patch("self_review_engine_archive.self_review_engine.review", return_value=r) as mock_review:
        res = review_generation("content", "telop", {})
        assert res.passed is True
        mock_review.assert_called_once_with("content", "telop", {})

    with patch("self_review_engine_archive.self_review_engine.review_and_improve", return_value=("improved", r)) as mock_improve:
        content, res = review_and_improve_func("content", "telop", {})
        assert content == "improved"
        assert res.passed is True
        mock_improve.assert_called_once_with("content", "telop", {})


def test_init_without_api_key():
    # GOOGLE_API_KEY が設定されていない場合の初期化
    with patch.dict(os.environ, {}, clear=True):
        engine = SelfReviewEngine()
        assert engine.client is None
        assert engine.model == "mock-model"


def test_review_with_null_client():
    # client が None の場合、フォールバックレビューが返ることを確認
    with patch.dict(os.environ, {}, clear=True):
        engine = SelfReviewEngine()
        assert engine.client is None
        
        result = engine.review("test content", "telop", {"topic": "test"})
        assert result.passed is True
        assert result.score.overall == 0.75  # fallback score


def test_default_improve_with_null_client():
    # client が None の場合、元のコンテンツがそのまま返ることを確認
    with patch.dict(os.environ, {}, clear=True):
        engine = SelfReviewEngine()
        assert engine.client is None
        
        r = ReviewResult(passed=False, score=QualityScore(0.5, 0.5, 0.5, 0.5), issues=["i"], suggestions=["s"])
        result_content = engine._default_improve("original content", r, {})
        assert result_content == "original content"


def test_init_client_exception():
    # client初期化時に例外が発生した場合、正常に例外が捕捉されて client が None になることを確認
    with patch.dict(os.environ, {"GOOGLE_API_KEY": "mock_api_key"}):
        with patch("google.genai.Client", side_effect=Exception("Mock Client Init Error")):
            engine = SelfReviewEngine()
            assert engine.client is None


def test_review_with_list_json_response():
    # LLMが波括弧を含まないリスト型JSON（例: [1, 2, 3]）を返した場合、
    # 正規表現にマッチせず、フォールバックレビュー（passed=True, score=0.75）になることを検証
    engine = SelfReviewEngine()
    mock_response = MagicMock()
    mock_response.text = "[1, 2, 3]"
    mock_genai_client.models.generate_content.return_value = mock_response
    
    result = engine.review("test content", "telop", {"topic": "test"})
    assert result.passed is True
    assert result.score.overall == 0.75

    # LLMが波括弧を含むリスト（例: [{"context_fit": 0.9}]）を返した場合、
    # 正規表現によりオブジェクト部分が切り出され、不足キーが補完されて処理されることを検証
    mock_response.text = json.dumps([{"context_fit": 0.9}])
    result2 = engine.review("test content", "telop", {"topic": "test"})
    assert result2.passed is False
    assert result2.score.context_fit == 0.9
    assert result2.score.overall == pytest.approx((0.9 + 0.5 + 0.5) / 3)



def test_review_and_improve_default_improve_success_round2():
    # デフォルトの改善処理を使用して、2回目のレビューで合格するシナリオを検証
    engine = SelfReviewEngine()
    
    r1 = ReviewResult(
        passed=False,
        score=QualityScore(0.5, 0.5, 0.5, 0.5),
        issues=["too short"],
        suggestions=["make it longer"]
    )
    r2 = ReviewResult(
        passed=True,
        score=QualityScore(0.8, 0.8, 0.8, 0.8),
        issues=[],
        suggestions=[]
    )
    
    with patch.object(engine, "review", side_effect=[r1, r2]) as mock_review:
        with patch.object(engine, "_default_improve", return_value="improved content") as mock_default_improve:
            content, result = engine.review_and_improve("original content", "telop", {})
            
            assert content == "improved content"
            assert result.passed is True
            assert result.improvement_applied is True
            assert len(result.improvement_history) == 1
            assert result.improvement_history[0]["round"] == 1
            assert result.improvement_history[0]["original_score"] == 0.5
            assert mock_review.call_count == 2
            mock_default_improve.assert_called_once_with("original content", r1, {})


def test_review_and_improve_default_improve_api_error_max_rounds():
    # デフォルト改善処理でAPIエラーが発生しつつ、最大ラウンドに到達するシナリオを検証
    engine = SelfReviewEngine()
    
    r = ReviewResult(
        passed=False,
        score=QualityScore(0.5, 0.5, 0.5, 0.5),
        issues=["bad"],
        suggestions=["fix"]
    )
    
    mock_genai_client.models.generate_content.side_effect = Exception("Improve API Error")
    
    with patch.object(engine, "review", return_value=r) as mock_review:
        content, result = engine.review_and_improve("original content", "telop", {})
        assert content == "original content"
        assert mock_review.call_count == 4
        
    mock_genai_client.models.generate_content.side_effect = None


def test_load_constitution_corrupted_raises_error():
    # 憲法ファイルが存在するが破損している場合、初期化時にJSONDecodeErrorが発生することを検証
    with patch.object(Path, "exists", return_value=True):
        with patch("builtins.open", mock_open(read_data="{invalid_json")):
            with pytest.raises(json.JSONDecodeError):
                SelfReviewEngine()



