import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from core import ProductionContext, ProductionPhase
from plugins.progressive_review_plugin import (
    ProgressiveReviewPlugin,
    ReviewStage,
    ReviewItem,
    StageReview,
    progressive_review
)

def test_plugin_metadata():
    """プラグインのメタデータと基本プロパティの検証"""
    plugin = ProgressiveReviewPlugin()
    assert plugin.name == "progressive_review"
    assert plugin.priority == 50
    assert plugin.can_execute(None) is True
    assert len(plugin.STAGES) == 5
    assert ReviewStage.SUBTITLE in plugin.STAGES

def test_approve_and_revision_flow():
    """ステージ承認・修正要求のライフサイクル検証"""
    plugin = ProgressiveReviewPlugin()
    
    # モックのコンテキストで一度executeを実行して_reviewsを初期化
    ctx = ProductionContext()
    plugin.execute(ctx)
    
    # 初期状態では未承認
    pending = plugin.get_pending_stages()
    assert ReviewStage.SUBTITLE in pending
    
    # 承認
    success = plugin.approve_stage(ReviewStage.SUBTITLE)
    assert success is True
    assert ReviewStage.SUBTITLE not in plugin.get_pending_stages()
    assert plugin._reviews[ReviewStage.SUBTITLE].approved is True
    assert plugin._reviews[ReviewStage.SUBTITLE].revision_requested is False
    
    # 修正要求
    success = plugin.request_revision(ReviewStage.SUBTITLE, "字幕のフォントを変更してください")
    assert success is True
    assert ReviewStage.SUBTITLE in plugin.get_pending_stages()
    assert plugin._reviews[ReviewStage.SUBTITLE].approved is False
    assert plugin._reviews[ReviewStage.SUBTITLE].revision_requested is True
    assert plugin._reviews[ReviewStage.SUBTITLE].revision_notes == "字幕のフォントを変更してください"
    
    # 存在しないステージの操作
    assert plugin.approve_stage(MagicMock()) is False
    assert plugin.request_revision(MagicMock(), "notes") is False

def test_review_subtitles():
    """字幕レビューの各判定条件の検証"""
    plugin = ProgressiveReviewPlugin()
    
    # 1. 正常なケース
    ctx = ProductionContext()
    ctx.set_extension("segments", [
        {"text": "こんにちは", "start": 0.0, "end": 2.0},
        {"text": "世界", "start": 2.5, "end": 4.5}
    ])
    review = plugin._generate_stage_review(ReviewStage.SUBTITLE, ctx)
    assert review.approved is False
    assert len(review.issues) == 0
    assert review.overall_score == 100.0
    
    # 2. 短すぎる、長すぎる、文字数超過、ばらつき（分散）のケース
    ctx2 = ProductionContext()
    ctx2.set_extension("segments", [
        # 短すぎる(0.4s)
        {"text": "短い", "start": 0.0, "end": 0.4},
        # 長すぎる(7.0s)
        {"text": "長い長い長い長い長い長い長い長い長い長い長い長い長い長い長い長い長い長い長い長い", "start": 1.0, "end": 8.0},
        # 文字数超過(41文字)
        {"text": "あ" * 41, "start": 9.0, "end": 12.0}
    ])
    review2 = plugin._generate_stage_review(ReviewStage.SUBTITLE, ctx2)
    assert len(review2.items) == 3
    
    # 各アイテムの検証
    assert "表示時間が短すぎます（0.5秒未満）" in review2.items[0].issues
    assert "表示時間が長すぎます（6秒超）" in review2.items[1].issues
    assert "文字数が多すぎます（40文字超）" in review2.items[2].issues
    
    # 分散の検証（durations: [0.4, 7.0, 3.0]）
    # 平均: 3.466
    # 分散: ((0.4-3.466)^2 + (7.0-3.466)^2 + (3.0-3.466)^2) / 3 = (9.40 + 12.48 + 0.21) / 3 = 7.36 > 4.0
    assert "字幕の表示時間にばらつきがあります" in review2.issues
    assert any("平均表示時間に近づける" in s for s in review2.suggestions)

def test_review_telops():
    """テロップレビューの各判定条件の検証"""
    plugin = ProgressiveReviewPlugin()
    
    # 1. テロップ設定なし
    ctx = ProductionContext()
    review = plugin._generate_stage_review(ReviewStage.TELOP, ctx)
    assert any("テロップが設定されていません" in s for s in review.suggestions)
    
    # 2. パレット不一致のケース
    ctx2 = ProductionContext()
    ctx2.mood_settings = {
        "color_palette": {
            "primary": "#FFFFFF",
            "secondary": "#000000"
        }
    }
    ctx2.set_extension("telop_candidates", [
        {"text": "タイトル", "color": "#FF0000", "preview": "data:image/png;base64,..."}, # パレット不一致
        {"text": "サブタイトル", "color": "#FFFFFF"} # パレット一致
    ])
    review2 = plugin._generate_stage_review(ReviewStage.TELOP, ctx2)
    assert len(review2.items) == 2
    assert "カラーパレットと不一致" in review2.items[0].issues
    assert len(review2.items[1].issues) == 0

def test_review_visuals():
    """ビジュアル素材レビューの各判定条件の検証"""
    plugin = ProgressiveReviewPlugin()
    
    ctx = ProductionContext()
    ctx.thumbnail_candidates = ["path/to/thumb1.jpg", "path/to/thumb2.jpg"]
    ctx.set_extension("scenes", [
        {"name": "シーン1", "image": "data:image/jpeg;base64,..."},
        {"name": "シーン2", "image": None} # 画像なしはReviewItemに登録されない
    ])
    
    review = plugin._generate_stage_review(ReviewStage.VISUAL, ctx)
    assert len(review.items) == 3 # 2 thumbnails + 1 scene_image
    assert review.items[0].type == "thumbnail"
    assert review.items[0].preview_path == "path/to/thumb1.jpg"
    assert review.items[2].type == "scene_image"
    assert review.items[2].content == "シーン1"
    assert any("複数のサムネイル候補があります" in s for s in review.suggestions)

def test_review_videos():
    """動画素材レビューの各判定条件の検証"""
    plugin = ProgressiveReviewPlugin()
    
    # 1. オープニング・エンディング未設定
    ctx = ProductionContext()
    review = plugin._generate_stage_review(ReviewStage.VIDEO, ctx)
    assert "オープニング動画が設定されていません" in review.issues
    assert "エンディング動画が設定されていません" in review.issues
    
    # 2. 設定済み ＆ トランジションあり
    ctx2 = ProductionContext()
    ctx2.opening = "path/to/op.mp4"
    ctx2.ending = "path/to/ed.mp4"
    ctx2.set_extension("transitions", [
        {"type": "fade", "duration": 1.0}
    ])
    review2 = plugin._generate_stage_review(ReviewStage.VIDEO, ctx2)
    assert len(review2.issues) == 0
    assert len(review2.items) == 3 # opening + ending + transition
    assert review2.items[0].type == "opening_video"
    assert review2.items[1].type == "ending_video"
    assert review2.items[2].type == "transition"
    assert review2.items[2].content == "fade"

def test_review_final():
    """最終統合レビューの各判定条件の検証"""
    plugin = ProgressiveReviewPlugin()
    
    ctx = ProductionContext()
    ctx.quality_score = 95.0
    ctx.set_extension("music_layer", "path/to/bgm.mp3")
    
    # executeを実行して全ステージの初期レビューを生成
    plugin.execute(ctx)
    
    # 1. 初期状態（前ステージに未承認かつ修正要求中のものはないが、issuesがあるかもしれない）
    # 字幕や動画などの初期レビューで未設定警告が出ているため、FINALでそれらを集約する
    review = plugin._generate_stage_review(ReviewStage.FINAL, ctx)
    assert len(review.items) == 2 # quality_score + bgm
    assert review.items[0].passed is True
    assert review.items[1].passed is True
    assert review.items[1].content == "bgm.mp3"
    
    # 2. 他のステージで修正要求中がある場合
    plugin.request_revision(ReviewStage.SUBTITLE, "修正要求")
    review2 = plugin._generate_stage_review(ReviewStage.FINAL, ctx)
    assert "[subtitle] 修正が未完了です" in review2.issues
    
    # 3. 品質スコアが低い場合 ＆ BGM未設定
    ctx2 = ProductionContext()
    ctx2.quality_score = 85.0
    
    plugin2 = ProgressiveReviewPlugin()
    plugin2.execute(ctx2)
    review3 = plugin2._generate_stage_review(ReviewStage.FINAL, ctx2)
    assert review3.items[0].passed is False # 90未満はpassed=False
    assert len(review3.items) == 1 # BGMがないためbgmアイテムは追加されない
    
    # 4. 全チェックがパスし、前ステージに問題がなく、かつ承認済みのクリーンな状態
    plugin3 = ProgressiveReviewPlugin()
    ctx3 = ProductionContext()
    ctx3.opening = "op.mp4"
    ctx3.ending = "ed.mp4"
    ctx3.quality_score = 95.0
    ctx3.set_extension("music_layer", "bgm.mp3")
    # 字幕セグメントも正常に設定
    ctx3.set_extension("segments", [{"text": "OK", "start": 0.0, "end": 2.0}])
    # テロップ候補も正常に設定
    ctx3.set_extension("telop_candidates", [{"text": "OK"}])
    
    plugin3.execute(ctx3)
    
    # FINAL以外の全ステージを承認
    for stage in plugin3.STAGES[:-1]:
        plugin3.approve_stage(stage)
        
    review4 = plugin3._generate_stage_review(ReviewStage.FINAL, ctx3)
    # 前ステージのissuesがすべて解消されているはず
    assert len(review4.issues) == 0
    assert any("全チェック項目をパスしました" in s for s in review4.suggestions)

def test_generate_stage_report():
    """Markdownレポート生成のレイアウト検証（カルーセルとテーブル）"""
    plugin = ProgressiveReviewPlugin()
    
    # 1. プレビュー付きアイテム（カルーセル）とプレビューなしアイテム（テーブル）の混在
    ctx = ProductionContext()
    ctx.set_extension("segments", [
        {"text": "A" * 50, "start": 0.0, "end": 1.0} # issuesありのテキスト
    ])
    ctx.set_extension("telop_candidates", [
        {"text": "テロッププレビュー", "color": "#000", "preview": "data:image/png;base64,xxxx"} # issuesありのプレビュー
    ])
    
    # executeを実行してレビュー結果をキャッシュ
    plugin.execute(ctx)
    
    # SUBTITLEレポート（テキストのみ -> 表形式）
    report_sub = plugin.generate_stage_report(ReviewStage.SUBTITLE, ctx)
    assert "# 📋 字幕統一感チェック" in report_sub
    assert "| ID | 内容 | 状態 | 問題 |" in report_sub
    assert "subtitle_0" in report_sub
    
    # TELOPレポート（プレビューあり -> カルーセル）
    report_telop = plugin.generate_stage_report(ReviewStage.TELOP, ctx)
    assert "# 📋 テロップデザインチェック" in report_telop
    assert "````carousel" in report_telop
    assert "![テロッププレビュー](data:image/png;base64,xxxx)" in report_telop
    
    # 2. プレビューパスがある場合のカルーセル
    ctx2 = ProductionContext()
    ctx2.thumbnail_candidates = ["path/to/image.jpg"]
    
    plugin2 = ProgressiveReviewPlugin()
    plugin2.execute(ctx2)
    report_visual = plugin2.generate_stage_report(ReviewStage.VISUAL, ctx2)
    assert "````carousel" in report_visual
    assert "![thumbnail_0](path/to/image.jpg)" in report_visual
    
    # 3. テキスト切り詰めの検証
    ctx3 = ProductionContext()
    ctx3.set_extension("segments", [
        {"text": "W" * 100, "start": 0.0, "end": 1.0}
    ])
    plugin3 = ProgressiveReviewPlugin()
    plugin3.execute(ctx3)
    report_sub3 = plugin3.generate_stage_report(ReviewStage.SUBTITLE, ctx3)
    # 30文字に切り詰められることを検証
    assert "W" * 30 in report_sub3
    assert "W" * 31 not in report_sub3

    # 4. カルーセル複数スライド、プレビュー課題、全体課題、提案を網羅するテスト
    mock_review = StageReview(
        stage=ReviewStage.VISUAL,
        items=[
            ReviewItem(id="item1", type="thumbnail", preview_path="path1.jpg", issues=["画像が暗すぎます"], passed=False),
            ReviewItem(id="item2", type="scene_image", preview_data="data:image/png;base64,xxx", issues=["文字が重なっています"], passed=False)
        ],
        overall_score=0.0,
        consistency_score=50.0,
        issues=["全体の一貫性が不足しています"],
        suggestions=["フォントサイズを大きくしてください"]
    )
    report_mock = plugin._format_stage_report(mock_review)
    assert "````carousel" in report_mock
    assert "![item1](path1.jpg)" in report_mock
    assert "⚠️ 画像が暗すぎます" in report_mock
    assert "<!-- slide -->" in report_mock
    assert "![item2](data:image/png;base64,xxx)" in report_mock
    assert "⚠️ 文字が重なっています" in report_mock
    assert "## ⚠️ 検出された問題" in report_mock
    assert "- 全体の一貫性が不足しています" in report_mock
    assert "## 💡 改善提案" in report_mock
    assert "- フォントサイズを大きくしてください" in report_mock
