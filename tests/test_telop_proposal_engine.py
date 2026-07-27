import sys
from pathlib import Path

# backend パス追加
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import pytest
from unittest.mock import MagicMock, patch
from dataclasses import asdict

# モジュールインポート用のモック設定
mock_client = MagicMock()
mock_model = MagicMock()

# ここでモジュール読み込み時のパッチを当てる
with patch("gemini_client_factory.get_gemini_client", return_value=mock_client),      patch("model_registry.get_model", return_value=mock_model):
    if "telop_proposal_engine" in sys.modules:
        del sys.modules["telop_proposal_engine"]
    import telop_proposal_engine as engine

# テスト内で使うダミーのクライアントレスポンスクラス
class DummyResponse:
    def __init__(self, text):
        self.text = text

def test_engine_init():
    # 新規インスタンス化のテスト
    with patch("telop_proposal_engine.get_gemini_client") as mock_get_client,          patch("telop_proposal_engine.get_model") as mock_get_model:
        eng = engine.TelopProposalEngine()
        mock_get_client.assert_called_once()
        mock_get_model.assert_called_once_with("quality_gate")

def test_extract_telop_candidates_success():
    # 正常系のLLM応答パーステスト
    # LLMがJSONを正しく返すケース
    json_response_text = """
    {
      "telop_candidates": [
        {
          "segment_id": "seg_001",
          "telop_text": "テロップ1",
          "importance": 0.9,
          "style_suggestion": "emphasis",
          "position_suggestion": "center",
          "reason": "名言"
        },
        {
          "segment_id": "seg_002",
          "telop_text": "テロップ2",
          "importance": 0.8,
          "style_suggestion": "default",
          "position_suggestion": "bottom_center",
          "reason": "結論"
        }
      ]
    }
    """
    mock_client.models.generate_content.return_value = DummyResponse(json_response_text)
    
    segments = [
        {"id": "seg_001", "start": 0.0, "end": 2.0, "text": "これはテストのセグメント1です。"},
        {"id": "seg_002", "start": 2.0, "end": 4.5, "text": "重要な結論です。"}
    ]
    
    eng = engine.TelopProposalEngine()
    eng.client = mock_client
    
    candidates = eng.extract_telop_candidates(segments, max_candidates=1)
    
    # max_candidates=1 なので1件だけ返るはず。かつ重要度の高い方が優先される
    assert len(candidates) == 1
    assert candidates[0].segment_id == "seg_001"
    assert candidates[0].telop_text == "テロップ1"
    assert candidates[0].importance == 0.9
    assert candidates[0].style_suggestion == "emphasis"
    assert candidates[0].position_suggestion == "center"
    assert candidates[0].reason == "名言"
    
    # segment_id が見つからない場合のフォールバック挙動の検証
    json_response_text_invalid_seg = """
    {
      "telop_candidates": [
        {
          "segment_id": "seg_unknown",
          "telop_text": "不明なセグメントテロップ",
          "importance": 0.5
        }
      ]
    }
    """
    mock_client.models.generate_content.return_value = DummyResponse(json_response_text_invalid_seg)
    candidates = eng.extract_telop_candidates(segments, max_candidates=5)
    assert len(candidates) == 1
    assert candidates[0].segment_id == "seg_unknown"
    assert candidates[0].start == 0.0
    assert candidates[0].end == 0.0
    assert candidates[0].original_text == ""

def test_extract_telop_candidates_exception_fallback():
    # LLMが例外を投げるケース
    mock_client.models.generate_content.side_effect = Exception("API Error")
    
    # _fallback_extract が呼び出される。
    # キーワードマッチ用のセグメントを用意
    segments = [
        {"id": "seg_001", "start": 0.0, "end": 2.0, "text": "ここがポイントです"},  # キーワード "ポイント"
        {"id": "seg_002", "start": 2.0, "end": 4.0, "text": "これは普通のセグメント"},
        {"id": "seg_003", "start": 4.0, "end": 6.0, "text": "大切だけど50文字以上になっているテキストは除外されるはずなので長く書きます。これは本当に本当に本当に本当に本当に本当に本当に長いテキストです。"}, # 50文字以上
        {"id": "seg_004", "start": 6.0, "end": 8.0, "text": "核心に迫る20文字以上の長いテキストです。これは20文字以上になります。"} # キーワード "核心" & 20文字以上
    ]
    
    eng = engine.TelopProposalEngine()
    eng.client = mock_client
    
    candidates = eng.extract_telop_candidates(segments)
    
    # "ポイント" と "核心" がマッチするはず。
    # 50文字以上のものは除外され、20文字以上のものは切り詰められる。
    assert len(candidates) == 2
    
    # 順序は candidates 内の追加順（重要度は一律 0.7）
    # seg_001
    c1 = next(c for c in candidates if c.segment_id == "seg_001")
    assert c1.telop_text == "ここがポイントです"
    assert c1.importance == 0.7
    assert c1.reason == "キーワードマッチ"
    
    # seg_004
    c2 = next(c for c in candidates if c.segment_id == "seg_004")
    assert len(c2.telop_text) == 20
    assert c2.telop_text == "核心に迫る20文字以上の長いテキストです"

    # side_effect をリセット
    mock_client.models.generate_content.side_effect = None

def test_extract_telop_candidates_json_decode_error():
    # JSONではない適当なテキスト（reマッチしない）
    mock_client.models.generate_content.return_value = DummyResponse("これはただの文字列でJSONではない")
    
    segments = [
        {"id": "seg_001", "start": 0.0, "end": 2.0, "text": "ここがポイントです"}
    ]
    
    eng = engine.TelopProposalEngine()
    eng.client = mock_client
    
    candidates = eng.extract_telop_candidates(segments)
    assert len(candidates) == 1
    assert candidates[0].segment_id == "seg_001"
    
    # JSONマッチするがパースエラーになるケース
    # {} で囲んで正規表現にマッチさせつつ、中身を不正にする
    mock_client.models.generate_content.return_value = DummyResponse("{ 壊れたJSON }")
    candidates = eng.extract_telop_candidates(segments)
    assert len(candidates) == 1

def test_parse_telop_response_variations():
    # telop_candidatesキーが無いケース
    json_no_candidates = """
    {
      "something_else": []
    }
    """
    mock_client.models.generate_content.return_value = DummyResponse(json_no_candidates)
    segments = [{"id": "seg_001", "start": 0.0, "end": 2.0, "text": "こんにちは"}]
    
    eng = engine.TelopProposalEngine()
    eng.client = mock_client
    
    candidates = eng.extract_telop_candidates(segments)
    assert len(candidates) == 0

    # 項目に値が欠落している（デフォルト値の適用）ケース
    json_missing_fields = """
    {
      "telop_candidates": [
        {
          "segment_id": "seg_001"
        }
      ]
    }
    """
    mock_client.models.generate_content.return_value = DummyResponse(json_missing_fields)
    candidates = eng.extract_telop_candidates(segments)
    assert len(candidates) == 1
    assert candidates[0].telop_text == ""
    assert candidates[0].importance == 0.5
    assert candidates[0].style_suggestion == "default"
    assert candidates[0].position_suggestion == "bottom_center"
    assert candidates[0].reason == ""

def test_fallback_extract_variations():
    # キーワードマッチングのバリエーション
    # 20文字以下のキーワードマッチ
    segments = [
        {"id": "seg_001", "start": 0.0, "end": 2.0, "text": "これが大切です"}
    ]
    eng = engine.TelopProposalEngine()
    
    candidates = eng._fallback_extract(segments)
    assert len(candidates) == 1
    assert candidates[0].telop_text == "これが大切です"
    
    # キーワードを含まないケース
    segments_no_keyword = [
        {"id": "seg_002", "start": 2.0, "end": 4.0, "text": "普通のテキストです。"}
    ]
    candidates = eng._fallback_extract(segments_no_keyword)
    assert len(candidates) == 0

def test_propose_scene_structure_success():
    # シーン構成提案の正常系テスト
    json_response_text = """
    {
      "scenes": [
        {
          "name": "オープニング",
          "start_seg": "seg_001",
          "end_seg": "seg_002",
          "summary": "イントロダクション",
          "mood": "happy",
          "suggested_telops": 3
        }
      ]
    }
    """
    mock_client.models.generate_content.return_value = DummyResponse(json_response_text)
    
    segments = [
        {"id": "seg_001", "start": 0.0, "end": 2.0, "text": "こんにちは"},
        {"id": "seg_002", "start": 2.0, "end": 5.0, "text": "本日のテーマです"}
    ]
    
    eng = engine.TelopProposalEngine()
    eng.client = mock_client
    
    # topics を渡すケース
    topics = [{"title": "イントロ"}]
    scenes = eng.propose_scene_structure(segments, topics)
    assert len(scenes) == 1
    assert scenes[0].name == "オープニング"
    assert scenes[0].start_time == 0.0
    assert scenes[0].end_time == 5.0
    assert scenes[0].duration_sec == 5.0
    assert scenes[0].telop_count == 3
    assert scenes[0].summary == "イントロダクション"
    assert scenes[0].mood == "happy"
    
    # start_seg, end_seg が見つからない場合の挙動
    json_response_invalid_seg = """
    {
      "scenes": [
        {
          "name": "不明シーン",
          "start_seg": "unknown_start",
          "end_seg": "unknown_end",
          "suggested_telops": 1
        }
      ]
    }
    """
    mock_client.models.generate_content.return_value = DummyResponse(json_response_invalid_seg)
    scenes = eng.propose_scene_structure(segments)
    assert len(scenes) == 1
    assert scenes[0].start_time == 0.0
    assert scenes[0].end_time == 0.0

def test_propose_scene_structure_exception_fallback():
    # LLM例外発生時のフォールバックテスト
    mock_client.models.generate_content.side_effect = Exception("API Error")
    
    eng = engine.TelopProposalEngine()
    eng.client = mock_client
    
    # セグメント数が 0 のとき
    scenes = eng.propose_scene_structure([])
    assert len(scenes) == 0
    
    # セグメント数が 1 のとき (total_segments < 2 の分岐)
    segments_1 = [{"id": "seg_001", "start": 0.0, "end": 2.0, "text": "こんにちは"}]
    scenes = eng.propose_scene_structure(segments_1)
    assert len(scenes) == 1
    assert scenes[0].name == "パート1"
    assert scenes[0].start_time == 0.0
    assert scenes[0].end_time == 2.0
    
    # セグメント数が 120 のとき (total_segments // 50 の分岐、scenes_count = 2)
    segments_120 = [{"id": f"seg_{i:03d}", "start": float(i), "end": float(i+1), "text": "テスト"} for i in range(120)]
    scenes = eng.propose_scene_structure(segments_120)
    assert len(scenes) == 2
    assert scenes[0].name == "パート1"
    assert scenes[0].start_time == 0.0
    assert scenes[0].end_time == 60.0
    assert scenes[1].name == "パート2"
    assert scenes[1].start_time == 60.0
    assert scenes[1].end_time == 120.0
    
    mock_client.models.generate_content.side_effect = None

def test_propose_scene_structure_json_decode_error():
    # JSONパースエラー時のフォールバックテスト
    mock_client.models.generate_content.return_value = DummyResponse("JSONではないテキスト")
    
    segments = [{"id": "seg_001", "start": 0.0, "end": 2.0, "text": "こんにちは"}]
    
    eng = engine.TelopProposalEngine()
    eng.client = mock_client
    
    scenes = eng.propose_scene_structure(segments)
    assert len(scenes) == 1
    assert scenes[0].name == "パート1"
    
    # 壊れたJSONのケース
    mock_client.models.generate_content.return_value = DummyResponse("{ 壊れたJSON }")
    scenes = eng.propose_scene_structure(segments)
    assert len(scenes) == 1

def test_parse_scene_response_variations():
    # scenesキーが無いケース
    json_no_scenes = """
    {
      "something_else": []
    }
    """
    mock_client.models.generate_content.return_value = DummyResponse(json_no_scenes)
    segments = [{"id": "seg_001", "start": 0.0, "end": 2.0, "text": "こんにちは"}]
    
    eng = engine.TelopProposalEngine()
    eng.client = mock_client
    
    scenes = eng.propose_scene_structure(segments)
    assert len(scenes) == 0

    # 項目に値が欠落している（デフォルト値の適用）ケース
    json_missing_fields = """
    {
      "scenes": [
        {
          "start_seg": "seg_001"
        }
      ]
    }
    """
    mock_client.models.generate_content.return_value = DummyResponse(json_missing_fields)
    scenes = eng.propose_scene_structure(segments)
    assert len(scenes) == 1
    assert scenes[0].name == "シーン1" # デフォルト名
    assert scenes[0].telop_count == 0
    assert scenes[0].summary == ""
    assert scenes[0].mood == "neutral"

def test_fallback_scene_proposal_boundaries():
    eng = engine.TelopProposalEngine()
    
    # セグメント数が非常に多いケース (250個 -> scenes_count = 5)
    segments_250 = [{"id": f"seg_{i:03d}", "start": float(i), "end": float(i+1), "text": "テスト"} for i in range(250)]
    scenes = eng._fallback_scene_proposal(segments_250)
    assert len(scenes) == 5
    assert scenes[0].name == "パート1"
    assert scenes[4].name == "パート5"

def test_generate_proposal_report():
    eng = engine.TelopProposalEngine()
    
    # テロップとシーンが空の場合
    report_empty = eng.generate_proposal_report([], [])
    assert report_empty["summary"]["total_telops"] == 0
    assert report_empty["summary"]["total_scenes"] == 0
    assert report_empty["summary"]["avg_telop_importance"] == 0
    
    # テロップとシーンがある場合
    telops = [
        engine.TelopCandidate("telop_001", "seg_001", 0.0, 2.0, "元", "テロップ", 0.8)
    ]
    scenes = [
        engine.SceneProposal("scene_001", "シーン1", 0.0, 2.0, 2.0, 1, "概要", "mood")
    ]
    report = eng.generate_proposal_report(telops, scenes)
    assert report["summary"]["total_telops"] == 1
    assert report["summary"]["total_scenes"] == 1
    assert report["summary"]["avg_telop_importance"] == 0.8
    assert report["telop_candidates"][0]["id"] == "telop_001"
    assert report["scene_proposals"][0]["id"] == "scene_001"

def test_module_wrapper_functions():
    # モジュールレベルの簡易関数のテスト
    engine.telop_engine.client = mock_client
    engine.telop_engine.model = mock_model
    
    json_response_telop = """
    {
      "telop_candidates": [
        {
          "segment_id": "seg_001",
          "telop_text": "テロップ",
          "importance": 0.8
        }
      ]
    }
    """
    json_response_scene = """
    {
      "scenes": [
        {
          "name": "シーン",
          "start_seg": "seg_001",
          "end_seg": "seg_001",
          "suggested_telops": 1
        }
      ]
    }
    """
    
    segments = [{"id": "seg_001", "start": 0.0, "end": 2.0, "text": "こんにちは"}]
    
    with patch.object(mock_client.models, "generate_content") as mock_gen:
        mock_gen.return_value = DummyResponse(json_response_telop)
        telops = engine.extract_telops(segments)
        assert len(telops) == 1
        assert telops[0]["telop_text"] == "テロップ"
        
        mock_gen.return_value = DummyResponse(json_response_scene)
        scenes = engine.propose_scenes(segments)
        assert len(scenes) == 1
        assert scenes[0]["name"] == "シーン"


def test_google_api_error_fallback():
    # GoogleAPIError 発生時のフォールバックテスト
    from google.api_core.exceptions import GoogleAPIError
    mock_client.models.generate_content.side_effect = GoogleAPIError("Mock API error")
    
    eng = engine.TelopProposalEngine()
    eng.client = mock_client
    
    segments = [{"id": "seg_001", "start": 0.0, "end": 2.0, "text": "ここがポイントです"}]
    
    # 1. extract_telop_candidates の検証
    candidates = eng.extract_telop_candidates(segments)
    assert len(candidates) == 1
    assert candidates[0].segment_id == "seg_001"
    
    # 2. propose_scene_structure の検証
    scenes = eng.propose_scene_structure(segments)
    assert len(scenes) == 1
    assert scenes[0].name == "パート1"
    
    mock_client.models.generate_content.side_effect = None
