import pytest
import sys
import json
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock

# backend ディレクトリをパスに追加
_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from agents.pipeline_types import PipelineContext, Segment
from agents.workers.youtube_opt_worker import YouTubeOptWorker

def test_youtube_opt_worker_dod():
    """DoDの定義取得を検証"""
    worker = YouTubeOptWorker()
    assert worker.get_definition_of_done() == "タイトルが1案以上生成され、説明文とタグが含まれていること"

@pytest.mark.asyncio
async def test_youtube_opt_worker_get_val_coverage():
    """get_val関数の分岐網羅およびクロスメディア分析の正常系カバー"""
    worker = YouTubeOptWorker()
    
    class DummySegment:
        def __init__(self, text=None):
            self.text = text
            
    ctx = PipelineContext(
        video_path="dummy.mp4",
        session_id="test_session",
        segments=[
            DummySegment(text=None),  # hasattr=True, val=None -> L38 の default
            {"text": "辞書テキスト"},    # hasattr=False, isinstance(dict)=True -> L39-40
            "非オブジェクト文字列"      # hasattr=False, isinstance(dict)=False -> L41 の default
        ]
    )
    ctx.metadata = None
    # **SNS の実データを渡す**（R1.5-C4）。渡さないと本線は分析しない
    # （作り物のフォロワー数から投稿先を推奨しないため）
    ctx.metadata_source = {"sns_data": {"X": {"followers": 320, "posts": [
        {"text": "#AI", "impressions": 1200, "engagement": 45,
         "posted_at": "2026-05-20T19:15:00"}]}}}

    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "titles": ["AIによる動画自動化の未来"],
        "tags": ["AI", "動画"],
        "description": "動画解説",
        "chapters": []
    })
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client), \
         patch("services.cross_media_service.CrossMediaService") as mock_service_class:
        
        mock_service = mock_service_class.return_value
        mock_service.analyze_cross_media_correlation.return_value = {"score": 95}
        
        result = await worker.execute(ctx)
        assert result.success is True
        assert ctx.metadata["cross_media_correlation"] == {"score": 95}

@pytest.mark.asyncio
async def test_youtube_opt_worker_governance_error():
    """モデル解決時(model_governance)に例外が発生した場合のカバー (ImportError, AttributeError)"""
    worker = YouTubeOptWorker()
    
    ctx = PipelineContext(
        video_path="dummy.mp4",
        session_id="test_session",
        segments=[Segment(start=0.0, end=10.0, text="テスト")]
    )
    ctx.metadata = {}
    
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "titles": ["AIによる動画自動化の未来"],
        "tags": ["AI", "動画"],
        "description": "動画解説",
        "chapters": []
    })
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client), \
         patch("model_governance.model_governance._resolve_model", side_effect=AttributeError("モックエラー")):
        
        result = await worker.execute(ctx)
        assert result.success is True
        # **既定モデル名を直書きしない**（R1.5-C6）。正典は model_config.json
        from model_policy import resolve
        assert result.data["model_used"] == resolve("youtube_optimization").model
        assert not result.data["model_used"].startswith("gemini-2.5")

@pytest.mark.asyncio
async def test_youtube_opt_worker_ai_exception_fallback():
    """AIメタデータ生成時に例外が発生し、フォールバック（キーワード抽出 + チャプター生成）が行われることを検証"""
    worker = YouTubeOptWorker()
    
    ctx = PipelineContext(
        video_path="dummy.mp4",
        session_id="test_session",
        segments=[
            {"start": 0.0, "end": 10.0, "text": "こんにちは 日本語動画 テスト"},
            {"start": 290.0, "end": 310.0, "text": "中間パート 開発進捗"},
            {"start": 600.0, "end": 610.0, "text": "エンディング まとめ"}
        ]
    )
    ctx.metadata = {}
    
    with patch("gemini_client_factory.get_gemini_client", side_effect=ValueError("APIエラー")):
        result = await worker.execute(ctx)
        assert result.success is True
        assert "YouTube最適化(Gemini)" in ctx.skipped_features
        assert "chapters" in ctx.metadata
        assert len(ctx.metadata["chapters"]) >= 2
        assert len(ctx.metadata["tags"]) >= 5

@pytest.mark.asyncio
async def test_youtube_opt_worker_cross_media_exception():
    """クロスメディア相関分析で例外が発生した場合も、処理が正常に継続されることを検証"""
    worker = YouTubeOptWorker()
    
    ctx = PipelineContext(
        video_path="dummy.mp4",
        session_id="test_session",
        segments=[Segment(start=0.0, end=10.0, text="テスト")]
    )
    ctx.metadata = None
    
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "titles": ["AIによる動画自動化の未来"],
        "tags": ["AI", "動画"],
        "description": "動画解説",
        "chapters": []
    })
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client), \
         patch("services.cross_media_service.CrossMediaService") as mock_service_class:
         
        mock_service = mock_service_class.return_value
        mock_service.analyze_cross_media_correlation.side_effect = ValueError("分析エラー")
        
        result = await worker.execute(ctx)
        assert result.success is True
        assert ctx.metadata is not None
        assert "cross_media_correlation" not in ctx.metadata

def test_youtube_opt_worker_run_cross_media_analysis_direct():
    """_run_cross_media_analysis を直接呼び出し、ctx.metadata が dict でない場合のパスをカバー"""
    worker = YouTubeOptWorker()
    ctx = PipelineContext(
        video_path="dummy.mp4",
        session_id="test_session",
        segments=[]
    )
    ctx.metadata = None
    # **SNS の実データを渡す**（R1.5-C4）。渡さないと本線は分析しない
    # （作り物のフォロワー数から投稿先を推奨しないため）
    ctx.metadata_source = {"sns_data": {"X": {"followers": 320, "posts": [
        {"text": "#AI", "impressions": 1200, "engagement": 45,
         "posted_at": "2026-05-20T19:15:00"}]}}}
    
    with patch("services.cross_media_service.CrossMediaService") as mock_service_class:
        mock_service = mock_service_class.return_value
        mock_service.analyze_cross_media_correlation.return_value = {"score": 95}
        
        worker._run_cross_media_analysis(ctx)
        assert isinstance(ctx.metadata, dict)
        assert ctx.metadata["cross_media_correlation"] == {"score": 95}

@pytest.mark.asyncio
async def test_youtube_opt_worker_fallback_edge_cases():
    """フォールバック処理のエッジケースを網羅するテスト。
    - last_seg に end/sourceEnd が存在しない場合（default=300）
    - nearby セグメントが存在しない時間帯でのチャプタータイトルデフォルト化
    - unique_words が5個未満の場合のデフォルトタグ適用
    """
    worker = YouTubeOptWorker()
    
    # 1. 5個未満のユニークワード、且つ最後のセグメントに時間情報がないケース
    ctx = PipelineContext(
        video_path="dummy.mp4",
        session_id="test_session",
        segments=[
            {"text": "こんにちは"}, # ユニークワード数が極小
            {"text": "テスト"}
        ]
    )
    ctx.metadata = {}
    
    with patch("gemini_client_factory.get_gemini_client", side_effect=ValueError("APIエラー")):
        result = await worker.execute(ctx)
        assert result.success is True
        # 15個未満のユニークワードでのフォールバックタグ確認
        assert ctx.metadata["tags"] == ["動画", "Vlog", "日本語", "YouTube", "コンテンツ"]
        # total_sec が 300 になり、オープニングチャプターのみ
        assert len(ctx.metadata["chapters"]) == 1
        assert ctx.metadata["chapters"][0]["title"] == "オープニング"

    # 2. total_sec が長く、かつ nearby に該当しない時間帯があるケース
    ctx2 = PipelineContext(
        video_path="dummy.mp4",
        session_id="test_session",
        segments=[
            {"start": 0.0, "end": 10.0, "text": "はじめに"},
            # t=300 秒から30秒以上離れた位置に配置して nearby を空にする
            {"start": 100.0, "end": 110.0, "text": "遠いセグメント"},
            # 最後のセグメントで total_sec を 400 に設定
            {"start": 390.0, "end": 400.0, "text": "おわり"}
        ]
    )
    ctx2.metadata = {}
    
    with patch("gemini_client_factory.get_gemini_client", side_effect=ValueError("APIエラー")):
        result2 = await worker.execute(ctx2)
        assert result2.success is True
        # チャプター数: オープニング (0:00) + パート2 (5:00 = 300秒)
        assert len(ctx2.metadata["chapters"]) == 2
        # t=300 に近いセグメントがないため、タイトルは "パート2" になるはず
        assert ctx2.metadata["chapters"][1]["title"] == "パート2"

    # 3. segments が空の場合のケース
    ctx3 = PipelineContext(
        video_path="dummy.mp4",
        session_id="test_session",
        segments=[]
    )
    ctx3.metadata = {}
    
    with patch("gemini_client_factory.get_gemini_client", side_effect=ValueError("APIエラー")):
        result3 = await worker.execute(ctx3)
        assert result3.success is True
        # segments が空なので、オープニングチャプターのみ返される
        assert len(ctx3.metadata["chapters"]) == 1
        assert ctx3.metadata["chapters"][0]["title"] == "オープニング"

def test_youtube_opt_worker_robustness_extension():
    """堅牢性をさらに強化するための追加エッジケース検証"""
    worker = YouTubeOptWorker()

    # 1. _get_attribute_or_key の辞書キー値検証
    d = {"key_exists_but_none": None}
    assert worker._get_attribute_or_key(d, "key_exists_but_none", "default") is None
    assert worker._get_attribute_or_key(d, "non_existent_key", "default") == "default"

    # 2. _extract_fallback_tags で特殊文字や空文字列による動作
    # 空テキストの場合、日本語の漢字・ひらがな・カタカナがマッチしないため、デフォルトタグが返る
    assert worker._extract_fallback_tags("") == ["動画", "Vlog", "日本語", "YouTube", "コンテンツ"]
    # 2文字以上の日本語単語が5個未満の場合、デフォルトタグが返る
    assert worker._extract_fallback_tags("あいう") == ["動画", "Vlog", "日本語", "YouTube", "コンテンツ"]
    # 5単語以上のユニークな日本語がある場合
    tags = worker._extract_fallback_tags("動画 編集 自動 生成 技術 開発")
    assert len(tags) >= 5
    assert "動画" in tags

    # 3. _create_fallback_chapters の時間極端値 (0秒、5秒など)
    # セグメントが極めて短い場合
    short_segs = [{"start": 0.0, "end": 5.0, "text": "短い動画"}]
    ch_short = worker._create_fallback_chapters(short_segs)
    assert len(ch_short) == 1
    assert ch_short[0]["time"] == "0:00"

@pytest.mark.asyncio
async def test_youtube_opt_worker_import_error_fallback():
    """ImportError が発生した場合にプレースホルダーの APIError が定義されることを検証"""
    worker = YouTubeOptWorker()
    ctx = PipelineContext(
        video_path="dummy.mp4",
        session_id="test_session",
        segments=[]
    )
    ctx.metadata = {}
    
    with patch.dict("sys.modules", {"google.genai.errors": None, "google.genai": None}), \
         patch("gemini_client_factory.get_gemini_client", side_effect=ValueError("APIエラー")):
        
        result = await worker.execute(ctx)
        assert result.success is True
