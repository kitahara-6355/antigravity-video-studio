import pytest
from unittest.mock import MagicMock, patch
import sys
import importlib

from services.hook_improver import (
    HookImprovement,
    HookImprovementResult,
    HookImproverService,
    hook_improver
)

def test_hook_improvement_dataclass():
    """HookImprovementのデータクラスとしての基本動作テスト"""
    imp = HookImprovement(
        original_text="元テキスト",
        improved_text="改善テキスト",
        improvement_type="attention",
        expected_score_boost=15,
        rationale="理由"
    )
    assert imp.original_text == "元テキスト"
    assert imp.improved_text == "改善テキスト"
    assert imp.improvement_type == "attention"
    assert imp.expected_score_boost == 15
    assert imp.rationale == "理由"

def test_hook_improvement_result_dataclass():
    """HookImprovementResultのデータクラスとしての基本動作テスト"""
    res = HookImprovementResult(original_score=60)
    assert res.original_score == 60
    assert res.improvements == []
    assert res.best_recommendation is None
    assert res.analysis_summary == ""

def test_build_prompt():
    """プロンプト構築のテスト"""
    service = HookImproverService()
    
    # 通常パターン
    prompt = service._build_prompt(
        hook_text="こんにちは",
        current_score=50,
        problems=["声が小さい", "テンポが悪い"],
        attention_grabber="疑問型",
        video_topic="プログラミング"
    )
    assert "こんにちは" in prompt
    assert "50/100" in prompt
    assert "声が小さい" in prompt
    assert "疑問型" in prompt
    assert "プログラミング" in prompt

    # エッジケース: 空データ
    prompt_empty = service._build_prompt(
        hook_text="",
        current_score=0,
        problems=[],
        attention_grabber="",
        video_topic=""
    )
    assert "特なし" in prompt_empty or "特になし" in prompt_empty
    assert "不明" in prompt_empty

def test_parse_response_formats():
    """様々なレスポンス形式に対するパース動作テスト"""
    service = HookImproverService()
    original = "元テキスト"

    # 1. ```json で囲まれた形式
    response_json_block = """
    いくつかの説明があって、その後に：
    ```json
    [
      {
        "type": "attention",
        "improved_text": "注意テキスト",
        "score_boost": 15,
        "rationale": "理由1"
      }
    ]
    ```
    フッターなど。
    """
    res = service._parse_response(response_json_block, original)
    assert len(res) == 1
    assert res[0].improved_text == "注意テキスト"
    assert res[0].improvement_type == "attention"
    assert res[0].expected_score_boost == 15
    assert res[0].rationale == "理由1"
    assert res[0].original_text == original

    # 2. ``` で囲まれた形式
    response_block = """
    ```
    [
      {
        "type": "emotion",
        "improved_text": "感情テキスト",
        "score_boost": 10,
        "rationale": "理由2"
      }
    ]
    ```
    """
    res2 = service._parse_response(response_block, original)
    assert len(res2) == 1
    assert res2[0].improved_text == "感情テキスト"
    assert res2[0].expected_score_boost == 10

    # 3. 囲みのない生JSON
    response_raw = """
    [
      {
        "type": "curiosity",
        "improved_text": "好奇心テキスト",
        "score_boost": 20,
        "rationale": "理由3"
      }
    ]
    """
    res3 = service._parse_response(response_raw, original)
    assert len(res3) == 1
    assert res3[0].improved_text == "好奇心テキスト"
    assert res3[0].expected_score_boost == 20

    # 4. 不正なJSON形式
    response_invalid = "不正なレスポンスでJSONではない"
    res4 = service._parse_response(response_invalid, original)
    assert res4 == []

def test_get_client():
    """_get_clientのキャッシュとクライアント生成動作のテスト"""
    service = HookImproverService()
    assert service._client is None

    # gemini_client_factory をパッチ
    with patch("gemini_client_factory.get_gemini_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        
        client1 = service._get_client()
        assert client1 == mock_client
        assert service._client == mock_client

        # 2回目はキャッシュが使われるはずなので mock_get_client は呼ばれない
        client2 = service._get_client()
        assert client2 == mock_client
        mock_get_client.assert_called_once()

@pytest.mark.asyncio
async def test_generate_improvements_success():
    """generate_improvements of 正常系動作テスト"""
    service = HookImproverService()
    
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = """
    ```json
    [
      {
        "type": "attention",
        "improved_text": "注意を引く案",
        "score_boost": 15,
        "rationale": "理由A"
      },
      {
        "type": "emotion",
        "improved_text": "感情に訴える案",
        "score_boost": 10,
        "rationale": "理由B"
      }
    ]
    ```
    """
    mock_client.models.generate_content.return_value = mock_response

    with patch.object(service, "_get_client", return_value=mock_client):
        result = await service.generate_improvements(
            hook_text="元のフックです",
            current_score=50,
            hook_analysis={
                "improvement_suggestions": ["提案1"],
                "attention_grabber": "タイプA"
            },
            video_topic="テストトピック"
        )
        
        assert isinstance(result, HookImprovementResult)
        assert result.original_score == 50
        assert len(result.improvements) == 2
        # 最もスコア上昇が高いのは「attention」の15
        assert result.best_recommendation is not None
        assert result.best_recommendation.improvement_type == "attention"
        assert result.best_recommendation.expected_score_boost == 15
        assert "attention" in result.analysis_summary
        assert "15点のスコア向上が期待できます" in result.analysis_summary

@pytest.mark.asyncio
async def test_generate_improvements_failure():
    """generate_improvements of 例外発生時ハンドリングテスト"""
    service = HookImproverService()
    
    # クライアント取得、あるいは API 呼び出しで例外が発生した場合
    with patch.object(service, "_get_client", side_effect=RuntimeError("APIエラー")):
        result = await service.generate_improvements(
            hook_text="元のフックです",
            current_score=50,
            hook_analysis={}
        )
        
        assert isinstance(result, HookImprovementResult)
        assert result.original_score == 50
        assert len(result.improvements) == 0
        assert result.best_recommendation is None
        assert "改善案の生成に失敗しました: APIエラー" in result.analysis_summary

def test_singleton_instance():
    """シングルトンインスタンスの存在確認"""
    assert isinstance(hook_improver, HookImproverService)

def test_import_error_fallback():
    """model_registryがインポートできない場合のフォールバックの動作検証"""
    import sys
    import importlib
    
    # model_registryをインポート不可に設定
    original_model_registry = sys.modules.get("model_registry")
    sys.modules["model_registry"] = None
    
    # hook_improver モジュールをリロードして、フォールバックの get_model が定義されることを確認
    import services.hook_improver
    importlib.reload(services.hook_improver)
    
    # **直書きの既定値に逃げない**（R1.5-C6）。2026-08-28 まで
    # gemini-2.5-flash を直書きしており、2026-10-16 に提供終了する
    from model_policy import resolve
    assert services.hook_improver.get_model("proofreader") == resolve("proofreader").model
    assert not services.hook_improver.get_model("proofreader").startswith("gemini-2.5")
    
    # 元に戻す
    if original_model_registry is not None:
        sys.modules["model_registry"] = original_model_registry
    else:
        del sys.modules["model_registry"]
    importlib.reload(services.hook_improver)

def test_parse_response_edge_cases():
    """_parse_response のエッジケース・異常系テスト"""
    service = HookImproverService()
    original = "元テキスト"

    # 1. リスト型ではない単一のJSON辞書
    response_dict = """
    {
      "type": "attention",
      "improved_text": "単一辞書",
      "score_boost": 15,
      "rationale": "理由"
    }
    """
    res = service._parse_response(response_dict, original)
    # リストではないため json.loads は成功するが items = data でループ処理時に例外が発生し空リストが返る
    assert res == []

    # 2. score_boost が文字列の数値の場合
    response_string_score = """
    [
      {
        "type": "attention",
        "improved_text": "文字列スコア",
        "score_boost": "25",
        "rationale": "理由"
      }
    ]
    """
    res_str = service._parse_response(response_string_score, original)
    assert len(res_str) == 1
    assert res_str[0].expected_score_boost == "25"

    # 3. score_boost が浮動小数点数の場合
    response_float_score = """
    [
      {
        "type": "attention",
        "improved_text": "小数スコア",
        "score_boost": 25.5,
        "rationale": "理由"
      }
    ]
    """
    res_float = service._parse_response(response_float_score, original)
    assert len(res_float) == 1
    assert res_float[0].expected_score_boost == 25.5

    # 4. score_boost キーが欠損している場合
    response_missing_score = """
    [
      {
        "type": "attention",
        "improved_text": "スコア欠損",
        "rationale": "理由"
      }
    ]
    """
    res_missing = service._parse_response(response_missing_score, original)
    assert len(res_missing) == 1
    assert res_missing[0].expected_score_boost == 0

    # 5. response_text が空文字列や None の場合
    assert service._parse_response("", original) == []
    assert service._parse_response(None, original) == []

    # 6. リストの中に辞書ではない不正な値が含まれる場合
    response_invalid_item = """
    [
      "invalid_item_type",
      {
        "type": "attention",
        "improved_text": "正常オブジェクト",
        "score_boost": 10
      }
    ]
    """
    # item.get() が AttributeError を起こし、例外ハンドリングで [] が返る
    res_invalid_item = service._parse_response(response_invalid_item, original)
    assert res_invalid_item == []

@pytest.mark.asyncio
async def test_generate_improvements_invalid_inputs():
    """generate_improvements の異常値・極端な入力値のテスト"""
    service = HookImproverService()

    # 1. hook_analysis に None を渡したとき
    # hook_analysis.get が AttributeError になり、例外がキャッチされてエラーハンドリング結果が返る
    result_none = await service.generate_improvements(
        hook_text="元のフックです",
        current_score=50,
        hook_analysis=None
    )
    assert result_none.__class__.__name__ == "HookImprovementResult"
    assert result_none.original_score == 50
    assert len(result_none.improvements) == 0
    assert "改善案の生成に失敗しました" in result_none.analysis_summary

    # 2. 改善案の期待スコア上昇値がすべて同じ値の場合
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = """
    [
      {
        "type": "attention",
        "improved_text": "案A",
        "score_boost": 10
      },
      {
        "type": "emotion",
        "improved_text": "案B",
        "score_boost": 10
      }
    ]
    """
    mock_client.models.generate_content.return_value = mock_response

    with patch.object(service, "_get_client", return_value=mock_client):
        result_same = await service.generate_improvements(
            hook_text="元のフックです",
            current_score=50,
            hook_analysis={}
        )
        assert result_same.best_recommendation is not None
        # 同一最大値の場合は max() の仕様により最初に見つかったものが選ばれる（"attention"）
        assert result_same.best_recommendation.improvement_type == "attention"
        assert result_same.best_recommendation.expected_score_boost == 10

    # 3. 改善案の期待スコア上昇値が負数の場合
    mock_response_negative = MagicMock()
    mock_response_negative.text = """
    [
      {
        "type": "attention",
        "improved_text": "案A",
        "score_boost": -5
      },
      {
        "type": "emotion",
        "improved_text": "案B",
        "score_boost": -2
      }
    ]
    """
    mock_client.models.generate_content.return_value = mock_response_negative

    with patch.object(service, "_get_client", return_value=mock_client):
        result_neg = await service.generate_improvements(
            hook_text="元のフックです",
            current_score=50,
            hook_analysis={}
        )
        assert result_neg.best_recommendation is not None
        # 最大値の -2（"emotion"）が選ばれる
        assert result_neg.best_recommendation.improvement_type == "emotion"
        assert result_neg.best_recommendation.expected_score_boost == -2
