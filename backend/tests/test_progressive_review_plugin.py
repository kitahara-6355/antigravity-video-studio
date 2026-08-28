import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock

# backend ディレクトリを sys.path に追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from core import ProductionContext, PluginPhase
from plugins.progressive_review_plugin import (
    ProgressiveReviewPlugin,
    ReviewStage,
    ReviewItem,
    StageReview,
    progressive_review
)

def test_plugin_metadata():
    """プラグインの基本メタデータのテスト"""
    plugin = ProgressiveReviewPlugin()
    assert plugin.name == "progressive_review"
    assert plugin.phase == PluginPhase.POST_PROCESS
    assert plugin.priority == 50
    assert plugin.can_execute(ProductionContext()) is True

def test_stage_operations():
    """ステージ承認・修正要求・未承認ステージ取得 API のテスト"""
    plugin = ProgressiveReviewPlugin()
    context = ProductionContext()
    
    # 実行前は _reviews は空
    assert plugin.get_pending_stages() == []
    
    # 実行して _reviews を生成
    plugin.execute(context)
    
    # 初期状態では approved=False なので、すべてのステージが pending
    pending = plugin.get_pending_stages()
    assert len(pending) == 5
    assert ReviewStage.SUBTITLE in pending
    
    # ステージを承認
    assert plugin.approve_stage(ReviewStage.SUBTITLE) is True
    pending = plugin.get_pending_stages()
    assert len(pending) == 4
    assert ReviewStage.SUBTITLE not in pending
    
    # 存在しないステージの承認は False
    assert plugin.approve_stage(MagicMock()) is False
    
    # 修正を要求
    assert plugin.request_revision(ReviewStage.SUBTITLE, "字幕のフォントを修正してください") is True
    pending = plugin.get_pending_stages()
    assert len(pending) == 5
    assert ReviewStage.SUBTITLE in pending
    assert plugin._reviews[ReviewStage.SUBTITLE].revision_requested is True
    assert plugin._reviews[ReviewStage.SUBTITLE].revision_notes == "字幕のフォントを修正してください"
    assert plugin._reviews[ReviewStage.SUBTITLE].approved is False
    
    # 存在しないステージの修正要求は False
    assert plugin.request_revision(MagicMock(), "notes") is False

def test_review_subtitles_boundaries():
    """字幕レビューの境界値検証"""
    plugin = ProgressiveReviewPlugin()
    context = ProductionContext()
    
    # 1. 正常系 (ちょうど良い長さと文字数)
    context.set_extension("segments", [
        {"text": "こんにちは", "start": 1.0, "end": 3.0}, # 2.0秒、5文字
        {"text": "テストです", "start": 4.0, "end": 6.5}  # 2.5秒、5文字
    ])
    review = plugin._generate_stage_review(ReviewStage.SUBTITLE, context)
    assert review.overall_score == 100.0
    assert review.consistency_score == 100.0
    assert len(review.issues) == 0
    
    # 2. 境界値: 表示時間が短すぎる (0.5秒未満)
    context.set_extension("segments", [
        {"text": "あ", "start": 1.0, "end": 1.49} # 0.49秒
    ])
    review = plugin._generate_stage_review(ReviewStage.SUBTITLE, context)
    assert review.overall_score == 0.0
    assert "表示時間が短すぎます（0.5秒未満）" in review.items[0].issues
    
    # 3. 境界値: 表示時間が長すぎる (6秒超)
    context.set_extension("segments", [
        {"text": "あ", "start": 1.0, "end": 7.01} # 6.01秒
    ])
    review = plugin._generate_stage_review(ReviewStage.SUBTITLE, context)
    assert review.overall_score == 0.0
    assert "表示時間が長すぎます（6秒超）" in review.items[0].issues
 
    # 4. 境界値: ちょうど 0.5秒と 6.0秒 (パスするはず)
    context.set_extension("segments", [
        {"text": "あ", "start": 1.0, "end": 1.5},
        {"text": "い", "start": 2.0, "end": 8.0}
    ])
    review = plugin._generate_stage_review(ReviewStage.SUBTITLE, context)
    assert review.overall_score == 100.0

    # 5. 境界値: 文字数が多すぎる (40文字超)
    long_text = "あ" * 41
    context.set_extension("segments", [
        {"text": long_text, "start": 1.0, "end": 4.0}
    ])
    review = plugin._generate_stage_review(ReviewStage.SUBTITLE, context)
    assert review.overall_score == 0.0
    assert "文字数が多すぎます（40文字超）" in review.items[0].issues

    # 6. 境界値: ちょうど 40文字 (パスするはず)
    border_text = "あ" * 40
    context.set_extension("segments", [
        {"text": border_text, "start": 1.0, "end": 4.0}
    ])
    review = plugin._generate_stage_review(ReviewStage.SUBTITLE, context)
    assert review.overall_score == 100.0

    # 7. 全体の表示時間のばらつき（分散 > 4.0）
    context.set_extension("segments", [
        {"text": "あ", "start": 0.0, "end": 1.0},  # 1.0秒
        {"text": "い", "start": 2.0, "end": 8.0}   # 6.0秒
    ])
    review = plugin._generate_stage_review(ReviewStage.SUBTITLE, context)
    assert "字幕の表示時間にばらつきがあります" in review.issues

def test_review_subtitles_empty_and_invalid():
    """字幕レビューの空値および異常データ(例外フォールバック)検証"""
    plugin = ProgressiveReviewPlugin()
    context = ProductionContext()
    
    # 1. segments が存在しない、または空
    context.set_extension("segments", [])
    review = plugin._generate_stage_review(ReviewStage.SUBTITLE, context)
    assert review.overall_score == 100.0
    assert review.consistency_score == 100.0
    
    # 2. segments 内の dict に必要なキーが欠けている、または型が異なる場合の境界値検証
    # text 欠損、start/end が文字列
    context.set_extension("segments", [
        {"start": "invalid", "end": 2.0} # start が文字列
    ])
    
    # 例外が発生せず安全に処理され、duration=0 になるため警告が発火することを確認
    review = plugin._generate_stage_review(ReviewStage.SUBTITLE, context)
    assert review.overall_score == 0.0
    assert review.items[0].passed is False
    assert "表示時間が短すぎます（0.5秒未満）" in review.items[0].issues

def test_review_telops_boundaries():
    """テロップレビューの境界値検証"""
    plugin = ProgressiveReviewPlugin()
    context = ProductionContext()
    
    # 1. テロップ候補が空の場合の suggestions
    context.set_extension("telop_candidates", [])
    review = plugin._generate_stage_review(ReviewStage.TELOP, context)
    assert "テロップが設定されていません" in review.suggestions
    
    # 2. カラーパレットとの一致検証
    context.mood_settings = {
        "color_palette": {
            "primary": "#FF0000",
            "secondary": "#00FF00"
        }
    }
    context.set_extension("telop_candidates", [
        {"text": "テロップ1", "color": "#FF0000"}, # 一致
        {"text": "テロップ2", "color": "#0000FF"}  # 不一致
    ])
    review = plugin._generate_stage_review(ReviewStage.TELOP, context)
    assert review.overall_score == 50.0
    assert "カラーパレットと不一致" in review.items[1].issues
    assert review.items[0].passed is True
    assert review.items[1].passed is False

def test_review_visuals_boundaries():
    """ビジュアル素材レビューの境界値検証"""
    plugin = ProgressiveReviewPlugin()
    context = ProductionContext()
    
    # 1. サムネイルとシーンが空の場合
    context.thumbnail_candidates = []
    context.set_extension("scenes", [])
    review = plugin._generate_stage_review(ReviewStage.VISUAL, context)
    assert review.overall_score == 100.0
    
    # 2. サムネイル候補が1つの場合と、複数ある場合の suggestion
    context.thumbnail_candidates = ["path/to/thumb1.jpg"]
    review = plugin._generate_stage_review(ReviewStage.VISUAL, context)
    assert len(review.suggestions) == 0
    
    context.thumbnail_candidates = ["path/to/thumb1.jpg", "path/to/thumb2.jpg"]
    review = plugin._generate_stage_review(ReviewStage.VISUAL, context)
    assert "複数のサムネイル候補があります。トーンの統一感を確認してください" in review.suggestions
    
    # 3. シーン画像の読み込み
    context.set_extension("scenes", [
        {"image": "data:image/png;base64,xxxx", "name": "シーン1"},
        {"image": "data:image/png;base64,yyyy"} # name 欠損
    ])
    review = plugin._generate_stage_review(ReviewStage.VISUAL, context)
    assert len(review.items) == 4 # 2 thumbnails + 2 scenes
    assert review.items[2].content == "シーン1"
    assert review.items[3].content == "Scene 2" # name 欠損時のデフォルト表記

    # 4. サムネイル候補に非文字列オブジェクト（base64などのデータ）を設定した場合の検証
    context.thumbnail_candidates = [
        "path/to/thumb.jpg",                         # str -> preview_path に入る
        {"data": "data:image/png;base64,xxxx"}       # dict -> preview_data に入る
    ]
    review_non_str = plugin._generate_stage_review(ReviewStage.VISUAL, context)
    assert review_non_str.items[0].preview_path == "path/to/thumb.jpg"
    assert review_non_str.items[0].preview_data is None
    assert review_non_str.items[1].preview_path is None
    assert review_non_str.items[1].preview_data == {"data": "data:image/png;base64,xxxx"}

def test_review_videos_boundaries():
    """動画素材レビューの境界値検証"""
    plugin = ProgressiveReviewPlugin()
    context = ProductionContext()
    
    # 1. オープニング・エンディングが欠損している場合
    context.opening = None
    context.ending = None
    review = plugin._generate_stage_review(ReviewStage.VIDEO, context)
    assert "オープニング動画が設定されていません" in review.issues
    assert "エンディング動画が設定されていません" in review.issues
    
    # 2. 設定されている場合
    context.opening = "opening.mp4"
    context.ending = "ending.mp4"
    context.set_extension("transitions", [{"type": "fade", "duration": 1.0}])
    review = plugin._generate_stage_review(ReviewStage.VIDEO, context)
    assert len(review.issues) == 0
    assert len(review.items) == 3 # opening, ending, transition
    assert review.items[2].content == "fade"

def test_review_final_boundaries():
    """最終統合レビューの境界値検証"""
    plugin = ProgressiveReviewPlugin()
    context = ProductionContext()
    
    # 正常に全ステージを実行
    plugin.execute(context)
    
    # 1. 品質スコアが90未満の場合の境界値検証
    context.quality_score = 89.9
    review = plugin._generate_stage_review(ReviewStage.FINAL, context)
    quality_item = next(item for item in review.items if item.id == "quality_score")
    assert quality_item.passed is False
    
    # 2. 品質スコアが90以上の場合
    context.quality_score = 90.0
    review = plugin._generate_stage_review(ReviewStage.FINAL, context)
    quality_item = next(item for item in review.items if item.id == "quality_score")
    assert quality_item.passed is True

    # 3. 他のステージで問題がある場合、FINALに集約されるか
    plugin._reviews[ReviewStage.SUBTITLE].issues = ["字幕長すぎ"]
    review = plugin._generate_stage_review(ReviewStage.FINAL, context)
    assert "[subtitle] 字幕長すぎ" in review.issues
    
    # 4. 他のステージが未承認かつ修正指示ありの場合
    plugin._reviews[ReviewStage.SUBTITLE].approved = False
    plugin._reviews[ReviewStage.SUBTITLE].revision_requested = True
    review = plugin._generate_stage_review(ReviewStage.FINAL, context)
    assert "[subtitle] 修正が未完了です" in review.issues

    # 5. BGMの設定有無
    context.set_extension("music_layer", "bgm.mp3")
    review = plugin._generate_stage_review(ReviewStage.FINAL, context)
    bgm_item = next(item for item in review.items if item.id == "bgm")
    assert bgm_item.content == "bgm.mp3"
    assert bgm_item.passed is True

def test_generate_stage_report():
    """レポート生成機能の検証"""
    plugin = ProgressiveReviewPlugin()
    context = ProductionContext()
    
    context.thumbnail_candidates = ["thumb.jpg"]
    context.set_extension("scenes", [{"image": "data:image/png;base64,xxxx"}])
    context.set_extension("segments", [{"text": "テスト", "start": 0.0, "end": 2.0}])
    
    plugin.execute(context)
    
    # SUBTITLE のレポート生成 (テキストのみ)
    report_sub = plugin.generate_stage_report(ReviewStage.SUBTITLE, context)
    assert "# 📋 字幕統一感チェック" in report_sub
    assert "## 📊 スコア" in report_sub
    assert "subtitle_0" in report_sub
    
    # VISUAL のレポート生成 (カルーセルあり)
    report_vis = plugin.generate_stage_report(ReviewStage.VISUAL, context)
    assert "````carousel" in report_vis
    assert "![thumbnail_0](file:///thumb.jpg)" in report_vis
    assert "data:image/png;base64,xxxx" in report_vis

def test_progressive_review_singleton():
    """シングルトンインスタンスの動作確認"""
    assert isinstance(progressive_review, ProgressiveReviewPlugin)

def test_review_subtitles_fallback_boundaries():
    """字幕レビューにおける例外フォールバックの境界値検証"""
    plugin = ProgressiveReviewPlugin()
    
    # 1. startキーが欠損している場合
    context1 = ProductionContext()
    context1.set_extension("segments", [{"text": "テスト1", "end": 0.4}])
    review1 = plugin._generate_stage_review(ReviewStage.SUBTITLE, context1)
    assert review1.items[0].passed is False
    assert review1.items[0].metadata["start"] == 0.0
    assert review1.items[0].metadata["end"] == 0.4
    assert review1.items[0].metadata["duration"] == 0.4
    
    # 2. endキーが欠損している場合
    context2 = ProductionContext()
    context2.set_extension("segments", [{"text": "テスト2", "start": 1.0}])
    review2 = plugin._generate_stage_review(ReviewStage.SUBTITLE, context2)
    assert review2.items[0].passed is False
    assert review2.items[0].metadata["start"] == 1.0
    assert review2.items[0].metadata["end"] == 0.0
    assert review2.items[0].metadata["duration"] == -1.0 # 0.0 - 1.0 = -1.0
    
    # 3. start または end が None の場合 (TypeError)
    context3 = ProductionContext()
    context3.set_extension("segments", [{"text": "テスト3", "start": None, "end": 0.4}])
    review3 = plugin._generate_stage_review(ReviewStage.SUBTITLE, context3)
    assert review3.items[0].passed is False
    assert review3.items[0].metadata["start"] == 0.0
    assert review3.items[0].metadata["duration"] == 0.4
    
    context4 = ProductionContext()
    context4.set_extension("segments", [{"text": "テスト4", "start": 1.0, "end": None}])
    review4 = plugin._generate_stage_review(ReviewStage.SUBTITLE, context4)
    assert review4.items[0].passed is False
    assert review4.items[0].metadata["end"] == 0.0
    assert review4.items[0].metadata["duration"] == -1.0
    
    # 4. start または end が非数値の不正な型の場合 (TypeError)
    context5 = ProductionContext()
    context5.set_extension("segments", [{"text": "テスト5", "start": [], "end": {}}])
    review5 = plugin._generate_stage_review(ReviewStage.SUBTITLE, context5)
    assert review5.items[0].metadata["start"] == 0.0
    assert review5.items[0].metadata["end"] == 0.0
    assert review5.items[0].metadata["duration"] == 0.0
    
    # 5. start または end が ValueError を引き起こす文字列の場合 (ValueError)
    context6 = ProductionContext()
    context6.set_extension("segments", [{"text": "テスト6", "start": "not_a_number", "end": "3.5"}])
    review6 = plugin._generate_stage_review(ReviewStage.SUBTITLE, context6)
    assert review6.items[0].metadata["start"] == 0.0
    assert review6.items[0].metadata["end"] == 0.0
    assert review6.items[0].metadata["duration"] == 0.0

def test_coverage_gap_fillers():
    """未カバーのパスを通すためのテスト"""
    plugin = ProgressiveReviewPlugin()
    context = ProductionContext()
    
    # 全てのレビュー項目の基準を満たすように設定
    # SUBTITLE
    context.set_extension("segments", [{"text": "適度な長さの字幕", "start": 1.0, "end": 3.0}])
    # TELOP
    context.mood_settings = {"color_palette": {"primary": "#FF0000"}}
    context.set_extension("telop_candidates", [{"text": "テロップ", "color": "#FF0000"}])
    # VISUAL
    context.thumbnail_candidates = ["thumb.jpg"]
    context.set_extension("scenes", [{"image": "data:image/png;base64,xxxx", "name": "シーン"}])
    # VIDEO
    context.opening = "opening.mp4"
    context.ending = "ending.mp4"
    context.set_extension("transitions", [{"type": "fade"}])
    # FINAL
    context.quality_score = 95.0
    context.set_extension("music_layer", "bgm.mp3")
    
    # 実行
    plugin.execute(context)
    
    # 行368 のカバー検証: 全て承認して final_review を生成したとき、issues が無いため「全チェック項目をパスしました！」が入る
    for stage in plugin.STAGES[:-1]:
        plugin.approve_stage(stage)
        
    final_review = plugin._generate_stage_review(ReviewStage.FINAL, context)
    assert "全チェック項目をパスしました！レンダリング準備完了です" in final_review.suggestions
    
    # 行414 のカバー検証: プレビュー画像があり、かつ item.issues がある場合の _format_stage_report
    review_item_with_issue = ReviewItem(
        id="thumb_bad",
        type="thumbnail",
        preview_path="bad_thumb.jpg",
        passed=False,
        issues=["サムネイル解像度が低すぎます"]
    )
    stage_review_carousel_issue = StageReview(
        stage=ReviewStage.VISUAL,
        items=[review_item_with_issue],
        overall_score=0.0,
        consistency_score=100.0,
        issues=[],
        suggestions=[]
    )
    report_carousel_issue = plugin._format_stage_report(stage_review_carousel_issue)
    assert "⚠️ サムネイル解像度が低すぎます" in report_carousel_issue
    
    # 行434-437 & 441-444 のカバー検証: レビュー全体で issues と suggestions がある場合の _format_stage_report
    stage_review_global_issues = StageReview(
        stage=ReviewStage.SUBTITLE,
        items=[],
        overall_score=100.0,
        consistency_score=100.0,
        issues=["字幕のタイミングが不自然です"],
        suggestions=["フェードインを検討してください"]
    )
    report_global_issues = plugin._format_stage_report(stage_review_global_issues)
    assert "## ⚠️ 検出された問題" in report_global_issues
    assert "- 字幕のタイミングが不自然です" in report_global_issues
    assert "## 💡 改善提案" in report_global_issues
    assert "- フェードインを検討してください" in report_global_issues

def test_image_path_url_encoding():
    """画像パスにスペースや日本語（非ASCII）が含まれる場合の URL エンコード検証"""
    plugin = ProgressiveReviewPlugin()
    
    # 正常系 (エンコード不要なクリーンなパス)
    clean_path = "C:/Users/PC_User/Desktop/image.jpg"
    safe_clean = plugin._get_safe_link(clean_path)
    assert safe_clean == "file:///C:/Users/PC_User/Desktop/image.jpg"
    
    # 二重付与防止の検証
    file_prefix_path = "file:///C:/Users/PC_User/Desktop/image.jpg"
    safe_prefix = plugin._get_safe_link(file_prefix_path)
    assert safe_prefix == "file:///C:/Users/PC_User/Desktop/image.jpg"

    # スペースを含むパス
    space_path = r"C:\Users\PC_User\Desktop\Human01_Official Artifact\thumbnail 1.jpg"
    safe_space = plugin._get_safe_link(space_path)
    assert "%20" in safe_space
    assert "file:///C:/Users/PC_User/Desktop/Human01_Official%20Artifact/thumbnail%201.jpg" == safe_space
    
    # 日本語文字を含むパス
    japanese_path = r"C:\Users\PC_User\Desktop\画像フォルダ\サムネイル.jpg"
    safe_japanese = plugin._get_safe_link(japanese_path)
    assert "%E7%94%BB%E5%83%8F" in safe_japanese
    assert "file:///C:/Users/PC_User/Desktop/%E7%94%BB%E5%83%8F%E3%83%95%E3%82%A9%E3%83%AB%E3%83%80/%E3%82%B5%E3%83%A0%E3%83%8D%E3%82%A4%E3%83%AB.jpg" == safe_japanese

    # レポート生成時のカルーセル形式への適用検証
    ctx = ProductionContext()
    ctx.thumbnail_candidates = [japanese_path]
    plugin.execute(ctx)
    report = plugin.generate_stage_report(ReviewStage.VISUAL, ctx)
    assert "````carousel" in report
    assert f"![thumbnail_0]({safe_japanese})" in report


# --- R1.5-C4: 未計測を測定結果に見せない --------------------------------------


def test_品質スコアが未計測なら0点不合格と言わない():
    """**未計測を「0.0点・不合格」という測定結果に見せない**（R1.5-C4）。

    `backend/core/context.py:67` の `quality_score` は dataclass の既定値
    0.0 で、この経路に品質ゲートは繋がっていない。2026-08-28 まで
    `f"品質スコア: {quality_score:.1f}/100"` と `passed = quality_score >= 90`
    をそのまま通しており、**測っていないことが「0.0点・不合格」として
    レポートに出ていた**（`review_router.py:131` から公開されている）。
    """
    plugin = ProgressiveReviewPlugin()
    context = ProductionContext()
    plugin.execute(context)

    assert context.quality_score == 0.0, "前提: この経路では未計測のまま"

    review = plugin._generate_stage_review(ReviewStage.FINAL, context)
    quality_item = next(i for i in review.items if i.id == "quality_score")

    assert "未計測" in (quality_item.content or "")
    assert "0.0/100" not in (quality_item.content or "")
    assert quality_item.metadata["measured"] is False
    assert quality_item.metadata["score"] is None


def test_未計測の項目は合否の分母に入らない():
    """合格に数えれば偽の success、不合格に数えれば偽の測定結果になる。"""
    plugin = ProgressiveReviewPlugin()
    context = ProductionContext()
    plugin.execute(context)

    未計測 = plugin._generate_stage_review(ReviewStage.FINAL, context)
    context.quality_score = 95.0
    計測済み = plugin._generate_stage_review(ReviewStage.FINAL, context)

    # 未計測の1件を分母から外すので、残りが全部合格なら 100.0 のまま
    assert 未計測.overall_score == 100.0, 未計測.overall_score
    assert 計測済み.overall_score == 100.0, 計測済み.overall_score

    # 合否を主張しない項目は表でも ✅/⚠️ を出さない
    表 = "\n".join(plugin._format_text_table_items(未計測.items))
    quality行 = [行 for 行 in 表.splitlines() if "quality_score" in 行]
    assert quality行, 表
    assert "—" in quality行[0], quality行[0]
    assert "✅" not in quality行[0] and "⚠️" not in quality行[0], quality行[0]


def test_計測済みなら従来どおり合否が出る():
    """**門が恒真でないことの確認。** 測ったときは合否を言う。"""
    plugin = ProgressiveReviewPlugin()
    context = ProductionContext()
    plugin.execute(context)

    context.quality_score = 89.9
    落ちる = next(i for i in plugin._generate_stage_review(
        ReviewStage.FINAL, context).items if i.id == "quality_score")
    context.quality_score = 90.0
    通る = next(i for i in plugin._generate_stage_review(
        ReviewStage.FINAL, context).items if i.id == "quality_score")

    assert 落ちる.passed is False and 落ちる.metadata["measured"] is True
    assert 通る.passed is True and 通る.metadata["measured"] is True
    assert "89.9/100" in (落ちる.content or "")
