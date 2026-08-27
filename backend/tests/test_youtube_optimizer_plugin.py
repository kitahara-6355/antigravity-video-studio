# -*- coding: utf-8 -*-
"""
Tests for youtube_optimizer_plugin.py
"""

import os
import shutil
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from plugins.youtube_optimizer_plugin import youtube_optimizer, ThumbnailCandidate, SEOMetadata, HookAnalysis, YouTubeOptimizedContext

@pytest.fixture(autouse=True)
def cleanup_output():
    # テスト前後のクリーンアップ
    yield
    output_dir = Path("output")
    if output_dir.exists():
        try:
            shutil.rmtree(output_dir)
        except Exception:
            pass

@pytest.mark.asyncio
async def test_generate_thumbnail_with_imagen_success():
    mock_client = MagicMock()
    mock_image = MagicMock()
    mock_generated_image = MagicMock()
    mock_generated_image.image = mock_image
    
    mock_result = MagicMock()
    mock_result.generated_images = [mock_generated_image]
    mock_client.models.generate_images.return_value = mock_result
    
    thumbnail = ThumbnailCandidate(
        id="test_thumb_01",
        concept="好奇心喚起型",
        target_emotion="好奇心",
        text_overlay="知らないと損する〇〇"
    )
    context = {"topic": "生産性向上"}
    
    # gemini_client_factory からインポートされるため、そちらをパッチする
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
        res = await youtube_optimizer.generate_thumbnail_with_imagen(thumbnail, context)
        
        # 呼び出しの確認
        mock_client.models.generate_images.assert_called_once()
        mock_image.save.assert_called_once()
        
        expected_path = Path("output/thumbnails") / f"{thumbnail.id}.png"
        assert thumbnail.path == expected_path
        assert res == str(expected_path)

@pytest.mark.asyncio
async def test_generate_thumbnail_with_imagen_api_error():
    mock_client = MagicMock()
    mock_client.models.generate_images.side_effect = ValueError("API error")
    
    thumbnail = ThumbnailCandidate(
        id="test_thumb_02",
        concept="好奇心喚起型",
        target_emotion="好奇心",
        text_overlay="知らないと損する〇〇"
    )
    context = {"topic": "生産性向上"}
    
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
        res = await youtube_optimizer.generate_thumbnail_with_imagen(thumbnail, context)
        
        assert res is None
        assert thumbnail.path is None

@pytest.mark.asyncio
async def test_generate_thumbnail_with_imagen_empty_result():
    mock_client = MagicMock()
    mock_result = MagicMock()
    mock_result.generated_images = []
    mock_client.models.generate_images.return_value = mock_result
    
    thumbnail = ThumbnailCandidate(
        id="test_thumb_03",
        concept="好奇心喚起型",
        target_emotion="好奇心",
        text_overlay="知らないと損する〇〇"
    )
    context = {"topic": "生産性向上"}
    
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
        res = await youtube_optimizer.generate_thumbnail_with_imagen(thumbnail, context)
        
        assert res is None
        assert thumbnail.path is None

@pytest.mark.asyncio
async def test_optimize_context_full():
    segments = [
        {'start': 0, 'end': 2, 'text': 'みなさんこんにちは！'},
        {'start': 2, 'end': 5, 'text': '今日は驚きの事実を3つお伝えします！'},
        {'start': 5, 'end': 10, 'text': '知っていますか？実はこの方法で10倍 of 成果が出ました'},
        {'start': 10, 'end': 30, 'text': 'まず最初に、基本的なポイントを解説していきます'},
        {'start': 30, 'end': 60, 'text': '次に、しかし重要なのはここからです'},
        {'start': 60, 'end': 90, 'text': 'つまり、これが結論です！まとめると3つのポイントがあります'},
        {'start': 90, 'end': 120, 'text': '最後に、今すぐ実践できる方法をお伝えします'},
    ]
    topics = ['生産性向上', 'ライフハック', '時短術', '効率化', '仕事術']
    context = {'topic': '生産性向上', 'task_id': 'test_pro_001', 'soul_narrative': '信念テスト'}
    
    result = await youtube_optimizer.optimize_context(segments, topics, context)
    
    assert result.task_id == 'test_pro_001'
    assert result.hook_score > 0
    assert len(result.thumbnail_candidates) == 3
    assert result.seo_metadata is not None
    assert len(result.highlights) > 0
    assert result.soul_narrative == '信念テスト'

class ExceptionDict(dict):
    def __setitem__(self, key, value):
        raise ValueError("Simulated error setting item")

@pytest.mark.asyncio
async def test_optimize_context_director_brain_handling():
    # Director Brain インポート成功および例外発生時の挙動をテスト
    # ハイライトが検出されるように感情的なテキストを設定
    segments = [{'start': 0, 'end': 5, 'text': 'これはすごい！驚きです！'}]
    topics = ['テスト']
    
    # 1. sys.modules に director_engine をインポート可能なダミーモジュールとして注入する
    mock_brain = MagicMock()
    context = {'topic': 'テスト'}
    with patch.dict("sys.modules", {"director_engine": MagicMock(brain=mock_brain)}):
        result = await youtube_optimizer.optimize_context(segments, topics, context)
        assert context.get("director_brain_feedback") is not None
        assert "detected_highlights" in context

    # 2. 内部での一般例外 (Exception) 発生時のキャッチ処理を検証
    # _integrate_director_brain 内部で context に値を設定しようとしたときに例外を発生させる
    ex_context = ExceptionDict({'topic': 'テスト'})
    with patch.dict("sys.modules", {"director_engine": MagicMock(brain=mock_brain)}):
        # 例外が内部でキャッチされ、クラッシュしないことを確認
        result = await youtube_optimizer.optimize_context(segments, topics, ex_context)
        assert result is not None

def test_evaluate_hook_genres():
    # ジャンル別ボーナスのカバレッジ
    p = youtube_optimizer
    
    # 1. 開発/教育系
    score, p_type, suggestions = p._evaluate_hook("具体的な数字 3つのポイント プロとして教えます", genre="education")
    assert score > 0
    assert p_type == "specificity" or p_type == "authority"
    
    # 2. エンターテイメント
    score, p_type, suggestions = p._evaluate_hook("衝撃！まさかの結果！私の経験", genre="entertainment")
    assert score > 0
    assert "surprise" in p_type or "story" in p_type
    
    # 3. ビジネス
    score, p_type, suggestions = p._evaluate_hook("得する節約プロの裏技", genre="business")
    assert score > 0
    
    # 4. 低スコア時の改善提案
    score, p_type, suggestions = p._evaluate_hook("普通の話です", genre="education")
    assert score < 70
    assert len(suggestions) > 0
    
    score, p_type, suggestions = p._evaluate_hook("普通の話です", genre="entertainment")
    assert score < 70
    assert len(suggestions) > 0
    
    score, p_type, suggestions = p._evaluate_hook("普通の話です", genre="other")
    assert score < 70
    assert len(suggestions) > 0

def test_calculate_dynamic_ctr():
    p = youtube_optimizer
    
    # 感嘆符、疑問符、文字数（適正範囲）、パワーワードすべて満たす場合
    ctr1 = p.calculate_dynamic_ctr("【完全版】これは驚き！本当に結果が出るのか？")
    assert 2.0 <= ctr1 <= 15.0
    
    # 極端に短いタイトル
    ctr2 = p.calculate_dynamic_ctr("短い")
    assert ctr2 < ctr1

def test_generate_chapters_fallback():
    p = youtube_optimizer
    
    # 1. 空のセグメント
    assert p._generate_chapters([]) == []
    
    # 2. セグメント数が少なく、5チャプターに満たない場合の均等補完
    segments = [
        {'start': 0, 'end': 30, 'text': 'オープニング'},
        {'start': 30, 'end': 60, 'text': '導入'},
    ]
    chapters = p._generate_chapters(segments)
    assert len(chapters) == 5
    assert chapters[0]["title"] == "オープニング"
    assert chapters[4]["title"] == "まとめ"
    
    # 3. マーカー抽出のカバレッジ
    # マーカーの後のテキストが正しく抽出されるか
    title = p._extract_chapter_title("ここでは重要なポイントを説明します", "重要")
    assert title == "なポイントを説明しま"  # "重要" の後ろから10文字

@pytest.mark.asyncio
async def test_generate_pre_edit_assets():
    p = youtube_optimizer
    res = await p.generate_pre_edit_assets("新しい企画コンセプト")
    assert "title_candidates" in res
    assert "thumbnails" in res
    assert len(res["title_candidates"]) == 5
    assert len(res["thumbnails"]) == 3

def test_calculate_session_continuation_score():
    p = youtube_optimizer
    
    # 正常系 (すべてあり)
    res1 = p.calculate_session_continuation_score(
        current_video_id="v_001",
        series_id="s_001",
        has_end_screen=True,
        has_teaser=True,
        brand_consistency=90.0
    )
    assert res1["score"] > 70
    
    # 異常系・境界値 (すべてなし)
    res2 = p.calculate_session_continuation_score(
        current_video_id="v_002",
        series_id="s_002",
        has_end_screen=False,
        has_teaser=False,
        brand_consistency=50.0
    )
    assert res2["score"] < 70

import sys
import importlib

def test_resolve_model_fallback():
    import importlib.util
    from pathlib import Path
    
    # model_governance を一時的に無効化して別名モジュールとしてロードする
    file_path = str(Path(__file__).parent.parent / "plugins" / "youtube_optimizer_plugin.py")
    spec = importlib.util.spec_from_file_location("plugins.youtube_optimizer_plugin_fallback_test", file_path)
    module = importlib.util.module_from_spec(spec)
    
    with patch.dict("sys.modules", {"model_governance": None}):
        spec.loader.exec_module(module)
        
    # fallback が正常に定義され、正常に gemini-3.6-flash を返すことを確認
    assert module._resolve_model("branding") == "gemini-3.6-flash"

def test_youtube_optimized_context_to_dict():
    context = YouTubeOptimizedContext(
        task_id="test_to_dict",
        hook_score=85.0,
        selected_thumbnail_id="thumb_1"
    )
    # ThumbnailCandidate がある場合
    context.thumbnail_candidates = [
        ThumbnailCandidate(id="thumb_1", concept="テストコンセプト", target_emotion="驚き", text_overlay="テスト", predicted_ctr=5.5)
    ]
    # HookAnalysis や SEOMetadata も含める
    context.hook_analysis = HookAnalysis(score=85.0, attention_grabber="surprise", first_5_seconds_text="驚き！", improvement_suggestions=[], predicted_retention_impact="高")
    context.seo_metadata = SEOMetadata(title_candidates=["タイトル案"], description="説明", tags=["タグ"], hashtags=["#ハッシュ"], chapters=[], category="教育", keywords=["キー"])
    
    d = context.to_dict()
    assert d["task_id"] == "test_to_dict"
    assert d["hook_score"] == 85.0
    assert len(d["thumbnail_candidates"]) == 1
    assert d["thumbnail_candidates"][0]["id"] == "thumb_1"
    assert d["hook_analysis"]["score"] == 85.0
    assert d["seo_metadata"]["category"] == "教育"

@pytest.mark.asyncio
async def test_analyze_hook_boundary_segment():
    p = youtube_optimizer
    # 5秒を超えるが、開始が5秒未満のセグメント (例: 4.5 から 6.0)
    segments = [
        {"start": 0, "end": 4.5, "text": "オープニング"},
        {"start": 4.5, "end": 6.0, "text": "境界セグメント！"}
    ]
    res = await p.analyze_hook(segments)
    # 境界セグメントのテキストが含まれていることを確認 (156-157行目カバー)
    assert "境界セグメント" in res.first_5_seconds_text

def test_predict_retention_impact_levels():
    p = youtube_optimizer
    # 高 (score >= 80)
    assert "高:" in p._predict_retention_impact(85.0)
    # 中 (60 <= score < 80)
    assert "中:" in p._predict_retention_impact(70.0)
    # 低 (score < 60)
    assert "低:" in p._predict_retention_impact(50.0)

def test_extract_chapter_title_failures():
    p = youtube_optimizer
    # マーカーが含まれない場合
    assert p._extract_chapter_title("ここでは重要なポイントを説明します", "存在しないマーカー") == "存在しないマーカー"
    # マーカーの後に何も無い、または snippet が空の場合
    assert p._extract_chapter_title("重要なポイントは重要です", "重要です") == "重要です"

def test_calculate_importance_with_topic():
    p = youtube_optimizer
    # トピックが含まれる場合 (653行目の score += 30)
    topics = ["生産性"]
    score = p._calculate_importance("生産性を向上させる方法！", topics)
    assert score > 30

@pytest.mark.asyncio
async def test_integrate_director_brain_low_hook_score():
    p = youtube_optimizer
    yt_context = YouTubeOptimizedContext(
        task_id="test_low_hook",
        hook_score=50.0,
        soul_narrative="視聴者第一"
    )
    yt_context.hook_analysis = HookAnalysis(score=50.0, attention_grabber="neutral", first_5_seconds_text="普通", improvement_suggestions=[], predicted_retention_impact="低")
    
    mock_brain = MagicMock()
    context = {}
    with patch.dict("sys.modules", {"director_engine": MagicMock(brain=mock_brain)}):
        await p._integrate_director_brain(yt_context, context)
        # Soul Narrative に「（フック強化が課題）」が追記されていることを確認 (697行目カバー)
        assert "（フック強化が課題）" in yt_context.soul_narrative

@pytest.mark.asyncio
async def test_integrate_director_brain_import_error():
    p = youtube_optimizer
    yt_context = YouTubeOptimizedContext(task_id="test_import_err")
    context = {}
    # sys.modules に director_engine が無い状態 (None にして ImportError を起こす)
    with patch.dict("sys.modules", {"director_engine": None}):
        # 例外が発生せず正常終了することを確認 (706行目カバー)
        await p._integrate_director_brain(yt_context, context)

@pytest.mark.asyncio
async def test_calculate_dynamic_ctr_variations():
    p = youtube_optimizer
    
    # ルート1: hook_score >= 80, highlight_count >= 5
    yt_context_1 = YouTubeOptimizedContext(task_id="test_ctr_1", hook_score=85.0)
    yt_context_1.thumbnail_candidates = [ThumbnailCandidate(id="t1", target_emotion="好奇心")]
    yt_context_1.highlights = [{"importance": 50}] * 5
    
    await p._apply_dynamic_ctr_to_thumbnails(yt_context_1, {})
    # 根拠とCTRが設定されていることを確認
    assert yt_context_1.thumbnail_candidates[0].predicted_ctr > 3.0
    assert any("高フックスコア" in f for f in yt_context_1.thumbnail_candidates[0].ctr_factors)
    assert any("ハイライト5件" in f for f in yt_context_1.thumbnail_candidates[0].ctr_factors)
    
    # ルート2: 60 <= hook_score < 80, 3 <= highlight_count < 5
    yt_context_2 = YouTubeOptimizedContext(task_id="test_ctr_2", hook_score=70.0)
    yt_context_2.thumbnail_candidates = [ThumbnailCandidate(id="t2", target_emotion="驚き")]
    yt_context_2.highlights = [{"importance": 50}] * 3
    
    await p._apply_dynamic_ctr_to_thumbnails(yt_context_2, {})
    assert any("中フックスコア" in f for f in yt_context_2.thumbnail_candidates[0].ctr_factors)
    assert any("ハイライト3件" in f for f in yt_context_2.thumbnail_candidates[0].ctr_factors)


@pytest.mark.asyncio
async def test_calculate_dynamic_ctr_with_seo_metadata():
    p = youtube_optimizer
    # seo_metadata が存在し、タイトル5件以上、タグ15件以上の場合
    yt_context = YouTubeOptimizedContext(
        task_id="test_ctr_seo",
        hook_score=85.0
    )
    yt_context.thumbnail_candidates = [
        ThumbnailCandidate(id="t1", target_emotion="好奇心")
    ]
    yt_context.seo_metadata = SEOMetadata(
        title_candidates=["T1", "T2", "T3", "T4", "T5"],
        description="description",
        tags=["tag"] * 15,
        hashtags=["#tag"],
        chapters=[],
        category="教育",
        keywords=["key"]
    )
    
    await p._apply_dynamic_ctr_to_thumbnails(yt_context, {})
    
    # ctr_factors に期待される補正が入っていることを確認
    factors = yt_context.thumbnail_candidates[0].ctr_factors
    assert any("タイトル5案" in f for f in factors)
    assert any("タグ15個以上" in f for f in factors)


def test_evaluate_hook_high_score():
    p = youtube_optimizer
    # score >= 70 となるように多くのキーワードを含める
    text = "？なぜ 1 驚き！ わかる 実は 今すぐ 私は 得する 危険 プロ"
    score, p_type, suggestions = p._evaluate_hook(text, genre="education")
    assert score >= 70
    # suggestions に追加がされず空であることを確認 (230->250 の分岐カバー)
    assert len(suggestions) == 0

@pytest.mark.asyncio
async def test_integrate_director_brain_no_hook_analysis():
    p = youtube_optimizer
    yt_context = YouTubeOptimizedContext(task_id="test_no_hook_analysis")
    # hook_analysis は設定しない（Noneのまま）
    yt_context.highlights = [{"importance": 50}]
    
    mock_brain = MagicMock()
    context = {}
    with patch.dict("sys.modules", {"director_engine": MagicMock(brain=mock_brain)}):
        await p._integrate_director_brain(yt_context, context)
        # context に detected_highlights は入るが、director_brain_feedback は入らないことを確認 (685->700 の分岐カバー)
        assert "detected_highlights" in context
        assert "director_brain_feedback" not in context

@pytest.mark.asyncio
async def test_calculate_dynamic_ctr_with_seo_metadata_fewer_titles():
    p = youtube_optimizer
    yt_context = YouTubeOptimizedContext(
        task_id="test_ctr_seo_fewer",
        hook_score=85.0
    )
    yt_context.thumbnail_candidates = [
        ThumbnailCandidate(id="t1", target_emotion="好奇心")
    ]
    yt_context.seo_metadata = SEOMetadata(
        title_candidates=["T1", "T2", "T3", "T4"], # 5件未満
        description="description",
        tags=["tag"] * 15,
        hashtags=["#tag"],
        chapters=[],
        category="教育",
        keywords=["key"]
    )
    
    await p._apply_dynamic_ctr_to_thumbnails(yt_context, {})
    
    factors = yt_context.thumbnail_candidates[0].ctr_factors
    # 「タイトル5案」の補正が入っていないことを確認 (739->742 の分岐カバー)
    assert not any("タイトル5案" in f for f in factors)
    assert any("タグ15個以上" in f for f in factors)


@pytest.mark.asyncio
async def test_legacy_calculate_dynamic_ctr_alias():
    p = youtube_optimizer
    yt_context = YouTubeOptimizedContext(task_id="test_legacy_alias", hook_score=85.0)
    yt_context.thumbnail_candidates = [ThumbnailCandidate(id="t1", target_emotion="好奇心")]
    await p._calculate_dynamic_ctr(yt_context, {})
    assert yt_context.thumbnail_candidates[0].predicted_ctr > 3.0


@pytest.mark.asyncio
async def test_generate_thumbnail_with_imagen_os_error():
    mock_client = MagicMock()
    mock_client.models.generate_images.side_effect = OSError("Simulated disk error")
    
    thumbnail = ThumbnailCandidate(
        id="test_thumb_os_err",
        concept="好奇心喚起型",
        target_emotion="好奇心",
        text_overlay="知らないと損する〇〇"
    )
    context = {"topic": "生産性向上"}
    
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
        res = await youtube_optimizer.generate_thumbnail_with_imagen(thumbnail, context)
        # OSError is caught and returns None
        assert res is None
        assert thumbnail.path is None

