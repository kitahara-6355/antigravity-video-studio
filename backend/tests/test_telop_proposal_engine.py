import pytest
from unittest.mock import MagicMock, patch
import json

from telop_proposal_engine import (
    TelopCandidate,
    SceneProposal,
    TelopProposalEngine,
    extract_telops,
    propose_scenes,
    telop_engine
)

# サンプルセグメントデータ
SAMPLE_SEGMENTS = [
    {"id": "seg_001", "start": 0.0, "end": 2.5, "text": "こんにちは、これはテスト動画です。"},
    {"id": "seg_002", "start": 2.5, "end": 6.0, "text": "ここで重要なポイントを説明します。本質が大切です。"},
    {"id": "seg_003", "start": 6.0, "end": 10.0, "text": "最後の結論として、これが一番の秘訣になります。めちゃくちゃすごい！"},
]

SAMPLE_TOPICS = [
    {"name": "導入", "importance": 0.5},
    {"name": "本編", "importance": 0.9}
]

@pytest.fixture
def mock_gemini():
    """Geminiクライアントとモデル取得のモック"""
    with patch("telop_proposal_engine.get_gemini_client") as mock_get_client, \
         patch("telop_proposal_engine.get_model") as mock_get_model:
        
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_get_model.return_value = "dummy-model"
        
        yield mock_client, mock_get_client, mock_get_model


def test_dataclasses():
    """データクラスの初期化テスト"""
    candidate = TelopCandidate(
        id="telop_001",
        segment_id="seg_001",
        start=0.0,
        end=2.0,
        original_text="テスト",
        telop_text="テストテロップ",
        importance=0.8
    )
    assert candidate.id == "telop_001"
    assert candidate.style_suggestion == "default"
    assert candidate.position_suggestion == "bottom_center"
    assert candidate.duration_sec == 3.0
    assert candidate.reason == ""

    scene = SceneProposal(
        id="scene_01",
        name="イントロ",
        start_time=0.0,
        end_time=5.0,
        duration_sec=5.0,
        telop_count=1
    )
    assert scene.name == "イントロ"
    assert scene.summary == ""
    assert scene.mood == "neutral"


def test_engine_init(mock_gemini):
    """エンジンの初期化テスト"""
    mock_client, mock_get_client, mock_get_model = mock_gemini
    engine = TelopProposalEngine()
    
    assert engine.client == mock_client
    assert engine.model == "dummy-model"
    mock_get_client.assert_called_once()
    mock_get_model.assert_called_once_with("quality_gate")


def test_extract_telop_candidates_success(mock_gemini):
    """テロップ候補抽出の正常系テスト"""
    mock_client, _, _ = mock_gemini
    
    # モックのAIレスポンス設定
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "telop_candidates": [
            {
                "segment_id": "seg_002",
                "telop_text": "重要なポイント",
                "importance": 0.9,
                "style_suggestion": "emphasis",
                "position_suggestion": "center",
                "reason": "ポイントの強調"
            },
            {
                "segment_id": "seg_003",
                "telop_text": "これが一番の秘訣",
                "importance": 0.95,
                "style_suggestion": "sparkle",
                "position_suggestion": "bottom_center",
                "reason": "結論"
            }
        ]
    })
    mock_client.models.generate_content.return_value = mock_response
    
    engine = TelopProposalEngine()
    candidates = engine.extract_telop_candidates(SAMPLE_SEGMENTS, max_candidates=1)
    
    # max_candidates=1 のため、重要度が最も高い 0.95 の候補のみ返るはず
    assert len(candidates) == 1
    assert candidates[0].telop_text == "これが一番の秘訣"
    assert candidates[0].importance == 0.95
    assert candidates[0].style_suggestion == "sparkle"
    assert candidates[0].position_suggestion == "bottom_center"
    assert candidates[0].reason == "結論"
    assert candidates[0].segment_id == "seg_003"
    assert candidates[0].start == 6.0
    assert candidates[0].end == 10.0


def test_extract_telop_candidates_no_json_match(mock_gemini):
    """AIレスポンスにJSONが見つからない場合のフォールバックテスト"""
    mock_client, _, _ = mock_gemini
    mock_response = MagicMock()
    mock_response.text = "エラーが発生しました。JSONはありません。"
    mock_client.models.generate_content.return_value = mock_response
    
    engine = TelopProposalEngine()
    candidates = engine.extract_telop_candidates(SAMPLE_SEGMENTS)
    
    # _fallback_extract が呼び出される
    # SAMPLE_SEGMENTS の seg_002 に "ポイント"、"本質"、"大切" が含まれる
    # seg_003 に "秘訣"、"すごい" が含まれる
    assert len(candidates) > 0
    assert candidates[0].reason == "キーワードマッチ"


def test_extract_telop_candidates_json_decode_error(mock_gemini):
    """AIレスポンスのJSONが壊れている場合のフォールバックテスト"""
    mock_client, _, _ = mock_gemini
    mock_response = MagicMock()
    mock_response.text = "{ telop_candidates: [ 壊れたJSON ] }"
    mock_client.models.generate_content.return_value = mock_response
    
    engine = TelopProposalEngine()
    candidates = engine.extract_telop_candidates(SAMPLE_SEGMENTS)
    
    assert len(candidates) > 0
    assert candidates[0].reason == "キーワードマッチ"


def test_extract_telop_candidates_api_exception(mock_gemini):
    """API呼び出しが例外をスローした場合のフォールバックテスト"""
    mock_client, _, _ = mock_gemini
    mock_client.models.generate_content.side_effect = ValueError("API Connection Error")
    
    engine = TelopProposalEngine()
    candidates = engine.extract_telop_candidates(SAMPLE_SEGMENTS)
    
    assert len(candidates) > 0
    assert candidates[0].reason == "キーワードマッチ"


def test_fallback_extract_text_truncation():
    """フォールバック抽出時のテキスト切り詰めテスト"""
    engine = TelopProposalEngine()
    
    # 20文字を超えるキーワードマッチテキスト
    long_text = "この本質は極めて大切であり、非常に重要ポイントです。"
    segments = [{"id": "seg_001", "start": 0.0, "end": 5.0, "text": long_text}]
    
    candidates = engine._fallback_extract(segments)
    assert len(candidates) == 1
    assert len(candidates[0].telop_text) == 20
    assert candidates[0].telop_text == long_text[:20]


def test_propose_scene_structure_success(mock_gemini):
    """シーン構成提案の正常系テスト"""
    mock_client, _, _ = mock_gemini
    
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "scenes": [
            {
                "name": "テストオープニング",
                "start_seg": "seg_001",
                "end_seg": "seg_001",
                "summary": "挨拶",
                "mood": "welcoming",
                "suggested_telops": 1
            },
            {
                "name": "メイン解説",
                "start_seg": "seg_002",
                "end_seg": "seg_003",
                "summary": "ポイントと結論",
                "mood": "informative",
                "suggested_telops": 3
            }
        ]
    })
    mock_client.models.generate_content.return_value = mock_response
    
    engine = TelopProposalEngine()
    scenes = engine.propose_scene_structure(SAMPLE_SEGMENTS, SAMPLE_TOPICS)
    
    assert len(scenes) == 2
    assert scenes[0].name == "テストオープニング"
    assert scenes[0].start_time == 0.0
    assert scenes[0].end_time == 2.5
    assert scenes[0].duration_sec == 2.5
    assert scenes[0].telop_count == 1
    assert scenes[0].mood == "welcoming"
    
    assert scenes[1].name == "メイン解説"
    assert scenes[1].start_time == 2.5
    assert scenes[1].end_time == 10.0
    assert scenes[1].duration_sec == 7.5
    assert scenes[1].telop_count == 3
    assert scenes[1].mood == "informative"


def test_propose_scene_structure_no_json_match(mock_gemini):
    """シーン構成提案のAIレスポンスにJSONがない場合のフォールバック"""
    mock_client, _, _ = mock_gemini
    mock_response = MagicMock()
    mock_response.text = "テキストのみの応答"
    mock_client.models.generate_content.return_value = mock_response
    
    engine = TelopProposalEngine()
    scenes = engine.propose_scene_structure(SAMPLE_SEGMENTS)
    
    # 均等分割フォールバックが機能する
    assert len(scenes) > 0
    assert scenes[0].name.startswith("パート")


def test_propose_scene_structure_json_decode_error(mock_gemini):
    """シーン構成提案のAIレスポンスのJSONが壊れている場合のフォールバック"""
    mock_client, _, _ = mock_gemini
    mock_response = MagicMock()
    mock_response.text = "{ scenes: [ 壊れたデータ ] }"
    mock_client.models.generate_content.return_value = mock_response
    
    engine = TelopProposalEngine()
    scenes = engine.propose_scene_structure(SAMPLE_SEGMENTS)
    
    assert len(scenes) > 0
    assert scenes[0].name.startswith("パート")


def test_propose_scene_structure_api_exception(mock_gemini):
    """シーン構成提案でAPI例外が発生した場合のフォールバック"""
    mock_client, _, _ = mock_gemini
    mock_client.models.generate_content.side_effect = ValueError("API Error")
    
    engine = TelopProposalEngine()
    scenes = engine.propose_scene_structure(SAMPLE_SEGMENTS)
    
    assert len(scenes) > 0
    assert scenes[0].name.startswith("パート")


def test_fallback_scene_proposal_scale():
    """フォールバックシーン提案の分割数制御テスト"""
    engine = TelopProposalEngine()
    
    # セグメントが大量にある場合のテスト (150セグメント)
    many_segments = [{"id": f"seg_{i:03d}", "start": float(i), "end": float(i+1), "text": "テスト"} for i in range(150)]
    scenes = engine._fallback_scene_proposal(many_segments)
    
    # total_segments = 150
    # scenes_count = min(5, max(2, 150 // 50)) = min(5, max(2, 3)) = 3
    assert len(scenes) == 3
    assert scenes[0].telop_count == 2


def test_generate_proposal_report():
    """提案レポート生成のテスト"""
    engine = TelopProposalEngine()
    
    candidates = [
        TelopCandidate(
            id="telop_000",
            segment_id="seg_001",
            start=0.0,
            end=2.0,
            original_text="テスト1",
            telop_text="テロップ1",
            importance=0.8
        )
    ]
    scenes = [
        SceneProposal(
            id="scene_00",
            name="パート1",
            start_time=0.0,
            end_time=2.0,
            duration_sec=2.0,
            telop_count=1
        )
    ]
    
    report = engine.generate_proposal_report(candidates, scenes)
    
    assert "generated_at" in report
    assert report["summary"]["total_telops"] == 1
    assert report["summary"]["total_scenes"] == 1
    assert report["summary"]["avg_telop_importance"] == 0.8
    assert report["telop_candidates"][0]["telop_text"] == "テロップ1"
    assert report["scene_proposals"][0]["name"] == "パート1"


def test_helper_functions(mock_gemini):
    """簡易ヘルパー関数 (extract_telops, propose_scenes) のテスト"""
    mock_client, _, _ = mock_gemini
    
    # モックAIのレスポンス設定 (telops)
    mock_response_telop = MagicMock()
    mock_response_telop.text = json.dumps({
        "telop_candidates": [
            {
                "segment_id": "seg_001",
                "telop_text": "テロップ",
                "importance": 0.9
            }
        ]
    })
    # モックAIのレスポンス設定 (scenes)
    mock_response_scene = MagicMock()
    mock_response_scene.text = json.dumps({
        "scenes": [
            {
                "name": "オープニング",
                "start_seg": "seg_001",
                "end_seg": "seg_001",
                "suggested_telops": 1
            }
        ]
    })
    
    # シングルトンインスタンスへのパッチ適用
    with patch.object(telop_engine, 'client', mock_client):
        mock_client.models.generate_content.side_effect = [mock_response_telop, mock_response_scene]
        
        # extract_telops
        telops = extract_telops(SAMPLE_SEGMENTS)
        assert len(telops) == 1
        assert telops[0]["telop_text"] == "テロップ"
        assert telops[0]["importance"] == 0.9
        
        # propose_scenes
        scenes = propose_scenes(SAMPLE_SEGMENTS)
        assert len(scenes) == 1
        assert scenes[0]["name"] == "オープニング"
        assert scenes[0]["telop_count"] == 1

def test_empty_and_small_segments(mock_gemini):
    """空または非常に少数のセグメント入力時のテスト"""
    mock_client, _, _ = mock_gemini
    engine = TelopProposalEngine()
    
    # 1. 空セグメント時の extract
    # _fallback_extract が呼ばれて空リストを返すはず
    candidates = engine.extract_telop_candidates([])
    assert candidates == []
    
    # 2. 空セグメント時の propose_scene
    # _fallback_scene_proposal が呼ばれて空リストを返すはず
    scenes = engine.propose_scene_structure([])
    assert scenes == []
    
    # 3. 1セグメントのみの場合の propose_scene
    # _fallback_scene_proposal が呼ばれて1つのシーン提案を返すはず
    single_seg = [{"id": "seg_001", "start": 0.0, "end": 2.5, "text": "テストのみ"}]
    scenes_single = engine.propose_scene_structure(single_seg)
    assert len(scenes_single) == 1
    assert scenes_single[0].name == "パート1"
    assert scenes_single[0].duration_sec == 2.5



def test_extract_telop_candidates_null_and_missing_keys(mock_gemini):
    """AIレスポンスのtelop_candidatesがnullまたはキー欠損している場合の挙動"""
    mock_client, _, _ = mock_gemini
    
    # 1. telop_candidatesがnullの場合
    mock_response_null = MagicMock()
    mock_response_null.text = json.dumps({
        "telop_candidates": None
    })
    mock_client.models.generate_content.return_value = mock_response_null
    
    engine = TelopProposalEngine()
    candidates_null = engine.extract_telop_candidates(SAMPLE_SEGMENTS)
    assert len(candidates_null) > 0
    assert candidates_null[0].reason == "キーワードマッチ"

    # 2. 候補内のキーが欠損している場合
    mock_response_missing = MagicMock()
    mock_response_missing.text = json.dumps({
        "telop_candidates": [
            {
                # すべてのキーが欠損
            }
        ]
    })
    mock_client.models.generate_content.return_value = mock_response_missing
    
    candidates_missing = engine.extract_telop_candidates(SAMPLE_SEGMENTS)
    assert len(candidates_missing) == 1
    c = candidates_missing[0]
    assert c.segment_id == ""
    assert c.telop_text == ""
    assert c.importance == 0.5
    assert c.style_suggestion == "default"
    assert c.position_suggestion == "bottom_center"
    assert c.reason == ""


def test_extract_telop_candidates_invalid_segment_id(mock_gemini):
    """AIレスポンスのsegment_idが無効（空または存在しない）場合の挙動"""
    mock_client, _, _ = mock_gemini
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "telop_candidates": [
            {
                "segment_id": "seg_invalid",  # 存在しないID
                "telop_text": "無効なIDのテロップ",
                "importance": 0.8
            }
        ]
    })
    mock_client.models.generate_content.return_value = mock_response
    
    engine = TelopProposalEngine()
    candidates = engine.extract_telop_candidates(SAMPLE_SEGMENTS)
    assert len(candidates) == 1
    c = candidates[0]
    assert c.segment_id == "seg_invalid"
    assert c.start == 0.0
    assert c.end == 0.0
    assert c.original_text == ""


def test_propose_scene_structure_null_and_missing_keys(mock_gemini):
    """AIレスポンスのscenesがnullまたはキー欠損している場合の挙動"""
    mock_client, _, _ = mock_gemini
    
    # 1. scenesがnullの場合
    mock_response_null = MagicMock()
    mock_response_null.text = json.dumps({
        "scenes": None
    })
    mock_client.models.generate_content.return_value = mock_response_null
    
    engine = TelopProposalEngine()
    scenes_null = engine.propose_scene_structure(SAMPLE_SEGMENTS)
    assert len(scenes_null) > 0
    assert scenes_null[0].name.startswith("パート")

    # 2. シーンオブジェクトのキーが欠損している場合
    mock_response_missing = MagicMock()
    mock_response_missing.text = json.dumps({
        "scenes": [
            {
                # すべてのキーが欠損
            }
        ]
    })
    mock_client.models.generate_content.return_value = mock_response_missing
    
    scenes_missing = engine.propose_scene_structure(SAMPLE_SEGMENTS)
    assert len(scenes_missing) == 1
    s = scenes_missing[0]
    assert s.name == "シーン1"
    assert s.start_time == 0
    assert s.end_time == 0
    assert s.duration_sec == 0
    assert s.telop_count == 0
    assert s.summary == ""
    assert s.mood == "neutral"


def test_propose_scene_structure_invalid_segment_id(mock_gemini):
    """AIレスポンスのstart_seg/end_segが無効な場合の挙動"""
    mock_client, _, _ = mock_gemini
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "scenes": [
            {
                "name": "無効セグメントシーン",
                "start_seg": "seg_invalid_start",
                "end_seg": "seg_invalid_end",
                "suggested_telops": 5
            }
        ]
    })
    mock_client.models.generate_content.return_value = mock_response
    
    engine = TelopProposalEngine()
    scenes = engine.propose_scene_structure(SAMPLE_SEGMENTS)
    assert len(scenes) == 1
    s = scenes[0]
    assert s.name == "無効セグメントシーン"
    assert s.start_time == 0.0
    assert s.end_time == 0.0
    assert s.duration_sec == 0.0


def test_fallback_scene_proposal_boundaries():
    """フォールバックシーン提案のセグメント数境界値テスト"""
    engine = TelopProposalEngine()
    
    # 0セグメント
    assert engine._fallback_scene_proposal([]) == []
    
    # 1セグメント
    scenes_1 = engine._fallback_scene_proposal([{"start": 0.0, "end": 1.0}])
    assert len(scenes_1) == 1
    assert scenes_1[0].duration_sec == 1.0
    
    # 2セグメント
    scenes_2 = engine._fallback_scene_proposal([{"start": 0.0, "end": 1.0}, {"start": 1.0, "end": 2.0}])
    assert len(scenes_2) == 1
    
    # 49セグメント (49 // 50 = 0 -> max(1, 0) = 1)
    segs_49 = [{"start": float(i), "end": float(i+1)} for i in range(49)]
    assert len(engine._fallback_scene_proposal(segs_49)) == 1
    
    # 50セグメント (50 // 50 = 1 -> max(1, 1) = 1)
    segs_50 = [{"start": float(i), "end": float(i+1)} for i in range(50)]
    assert len(engine._fallback_scene_proposal(segs_50)) == 1
    
    # 99セグメント (99 // 50 = 1 -> max(1, 1) = 1)
    segs_99 = [{"start": float(i), "end": float(i+1)} for i in range(99)]
    assert len(engine._fallback_scene_proposal(segs_99)) == 1
    
    # 100セグメント (100 // 50 = 2 -> max(1, 2) = 2)
    segs_100 = [{"start": float(i), "end": float(i+1)} for i in range(100)]
    assert len(engine._fallback_scene_proposal(segs_100)) == 2
    
    # 250セグメント (250 // 50 = 5 -> max(1, 5) = 5 -> min(5, 5) = 5)
    segs_250 = [{"start": float(i), "end": float(i+1)} for i in range(250)]
    assert len(engine._fallback_scene_proposal(segs_250)) == 5
    
    # 300セグメント (300 // 50 = 6 -> max(1, 6) = 6 -> min(5, 6) = 5)
    segs_300 = [{"start": float(i), "end": float(i+1)} for i in range(300)]
    assert len(engine._fallback_scene_proposal(segs_300)) == 5


def test_extract_telop_candidates_parse_errors(mock_gemini):
    """レスポンスパース中のTypeError/AttributeErrorなどの個別エラー発生時のフォールバックテスト"""
    mock_client, _, _ = mock_gemini
    
    # 1. response.text が AttributeError を引き起こすように設定 (textプロパティが欠損しているオブジェクト)
    mock_response = MagicMock(spec=[])  # textプロパティを持たない
    mock_client.models.generate_content.return_value = mock_response
    
    engine = TelopProposalEngine()
    candidates = engine.extract_telop_candidates(SAMPLE_SEGMENTS)
    assert len(candidates) > 0
    assert candidates[0].reason == "キーワードマッチ"

    # 2. response.text が文字列ではない (TypeErrorを誘発)
    mock_response_type = MagicMock()
    mock_response_type.text = 12345  # 文字列ではない
    mock_client.models.generate_content.return_value = mock_response_type
    
    candidates2 = engine.extract_telop_candidates(SAMPLE_SEGMENTS)
    assert len(candidates2) > 0
    assert candidates2[0].reason == "キーワードマッチ"


def test_propose_scene_structure_parse_errors(mock_gemini):
    """シーン提案パース中のTypeError/AttributeErrorなどの個別エラー発生時のフォールバックテスト"""
    mock_client, _, _ = mock_gemini
    
    # response.text が文字列ではない (TypeErrorを誘発)
    mock_response_type = MagicMock()
    mock_response_type.text = 12345
    mock_client.models.generate_content.return_value = mock_response_type
    
    engine = TelopProposalEngine()
    scenes = engine.propose_scene_structure(SAMPLE_SEGMENTS)
    assert len(scenes) > 0
    assert scenes[0].name.startswith("パート")
