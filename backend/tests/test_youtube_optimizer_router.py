"""
YouTube Optimizer Router エッジケース・異常系テスト
routers/youtube_optimizer.py に対するカバレッジ向上テスト
"""

import sys
import pydantic
import pydantic.root_model
sys.modules['pydantic.root_model'] = pydantic.root_model

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

# ルーターをインポート
import os
from pathlib import Path

# パス追加
sys.path.insert(0, str(Path(__file__).parent.parent))
from routers.youtube_optimizer import router

# ミニFastAPIアプリ構築
app = FastAPI()
app.include_router(router)
client = TestClient(app)


# ===========================================================================
# Phase 0: 企画フェーズ テスト
# ===========================================================================

def test_pre_plan_exception():
    with patch("routers.youtube_optimizer._generate_title_candidates", side_effect=Exception("Pre-plan internal error")):
        response = client.post("/api/youtube/pre-plan", json={
            "topic": "一人キャンプ飯",
            "target_audience": "20代男性",
            "genre": "Vlog",
            "reference_videos": []
        })
        assert response.status_code == 500
        assert "Pre-plan internal error" in response.json()["detail"]


# ===========================================================================
# Phase 1: 予測型コンテンツ最適化 テスト
# ===========================================================================

def test_optimize_exception():
    with patch("plugins.youtube_optimizer_plugin.youtube_optimizer.optimize_context", side_effect=Exception("Optimize internal error")):
        response = client.post("/api/youtube/optimize", json={
            "segments": [{"start": 0, "end": 2, "text": "こんにちは"}],
            "topics": ["Vlog"],
            "context": {}
        })
        assert response.status_code == 500
        assert "Optimize internal error" in response.json()["detail"]


def test_generate_thumbnail_exception():
    with patch("plugins.youtube_optimizer_plugin.youtube_optimizer.generate_thumbnail_with_imagen", side_effect=Exception("Imagen error")):
        response = client.post("/api/youtube/generate-thumbnail", json={
            "thumbnail_id": "thumb_001",
            "context": {"concept": "cool thumbnail"}
        })
        assert response.status_code == 500
        assert "Imagen error" in response.json()["detail"]


def test_generate_thumbnail_failure():
    with patch("plugins.youtube_optimizer_plugin.youtube_optimizer.generate_thumbnail_with_imagen", return_value=None):
        response = client.post("/api/youtube/generate-thumbnail", json={
            "thumbnail_id": "thumb_001",
            "context": {"concept": "cool thumbnail"}
        })
        assert response.status_code == 200
        assert response.json()["success"] is False
        assert response.json()["message"] == "Thumbnail generation failed"


def test_improve_hook_exception():
    with patch("services.hook_improver.hook_improver.generate_improvements", side_effect=Exception("Hook improver error")):
        response = client.post("/api/youtube/improve-hook", json={
            "hook_text": "みなさんこんにちは",
            "current_score": 50,
            "hook_analysis": {},
            "video_topic": "キャンプ"
        })
        assert response.status_code == 500
        assert "Hook improver error" in response.json()["detail"]


def test_generate_hook_preview_exception():
    with patch("services.hook_preview_generator.hook_preview_generator.generate_screenshot_preview", side_effect=Exception("Preview error")):
        response = client.post("/api/youtube/hook-preview", json={
            "video_path": "dummy.mp4",
            "original_text": "before",
            "improved_text": "after",
            "task_id": "task_1"
        })
        assert response.status_code == 500
        assert "Preview error" in response.json()["detail"]


def test_apply_hook_exception():
    with patch("services.hook_evolution_service.hook_evolution_service.apply_improvement", side_effect=Exception("Apply error")):
        response = client.post("/api/youtube/apply-hook", json={
            "task_id": "task_1",
            "improvement_type": "attention",
            "improved_text": "after",
            "original_text": "before",
            "expected_score_boost": 10
        })
        assert response.status_code == 500
        assert "Apply error" in response.json()["detail"]


def test_revert_hook_exception():
    with patch("services.hook_evolution_service.hook_evolution_service.revert_latest", side_effect=Exception("Revert error")):
        response = client.post("/api/youtube/revert-hook?task_id=task_1")
        assert response.status_code == 500
        assert "Revert error" in response.json()["detail"]


def test_hook_history_exception():
    with patch("services.hook_evolution_service.hook_evolution_service.get_history", side_effect=Exception("History error")):
        response = client.get("/api/youtube/hook-history?task_id=task_1")
        assert response.status_code == 500
        assert "History error" in response.json()["detail"]


# ===========================================================================
# Phase 2: 公開後フィードバックループ テスト
# ===========================================================================

def test_feedback_loop_no_video_id():
    mock_wagamama = MagicMock()
    mock_wagamama.get_record.return_value = {"title": "Test Title"}  # youtube_video_id なし
    
    with patch("wagamama_manager.wagamama_manager", mock_wagamama), \
         patch("services.post_publish_collector.post_publish_collector.collect_performance_data") as mock_collect, \
         patch("services.prediction_validator.prediction_validator.validate_prediction") as mock_validate, \
         patch("routers.youtube_optimizer._record_post_publish_feedback"):
         
        mock_collect.return_value = {}
        mock_validate.return_value = {"status": "success", "analysis": {"difference": 1, "significant_deviation": False}}
        
        response = client.post("/api/youtube/feedback-loop/waga_001")
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["video_id_used"] == "vid_mock_waga_001"


def test_feedback_loop_error_skipped():
    mock_wagamama = MagicMock()
    mock_wagamama.get_record.return_value = {"youtube_video_id": "vid_123"}
    
    with patch("wagamama_manager.wagamama_manager", mock_wagamama), \
         patch("services.post_publish_collector.post_publish_collector.collect_performance_data") as mock_collect, \
         patch("services.prediction_validator.prediction_validator.validate_prediction") as mock_validate:
         
        mock_collect.return_value = {}
        mock_validate.return_value = {"status": "skipped", "message": "Too early to validate"}
        
        response = client.post("/api/youtube/feedback-loop/waga_001")
        assert response.status_code == 200
        assert response.json()["success"] is False
        assert response.json()["message"] == "Too early to validate"


def test_feedback_loop_exception():
    mock_wagamama = MagicMock()
    mock_wagamama.get_record.return_value = {"youtube_video_id": "vid_123"}
    
    with patch("wagamama_manager.wagamama_manager", mock_wagamama), \
         patch("services.post_publish_collector.post_publish_collector.collect_performance_data", side_effect=Exception("Feedback error")):
         
        response = client.post("/api/youtube/feedback-loop/waga_001")
        assert response.status_code == 500
        assert "Feedback error" in response.json()["detail"]


def test_feedback_loop_distillation_exception():
    mock_wagamama = MagicMock()
    mock_wagamama.get_record.return_value = {"youtube_video_id": "vid_123"}
    
    with patch("wagamama_manager.wagamama_manager", mock_wagamama), \
         patch("services.post_publish_collector.post_publish_collector.collect_performance_data") as mock_collect, \
         patch("services.prediction_validator.prediction_validator.validate_prediction") as mock_validate, \
         patch("routers.youtube_optimizer._record_post_publish_feedback", side_effect=Exception("Log record error")):
         
        mock_collect.return_value = {}
        mock_validate.return_value = {"status": "success", "analysis": {"difference": 5.0, "significant_deviation": True}}
        
        response = client.post("/api/youtube/feedback-loop/waga_001")
        assert response.status_code == 500
        assert "Log record error" in response.json()["detail"]


# ===========================================================================
# Phase 3: 視聴維持率分析 テスト
# ===========================================================================

def test_retention_map_exception():
    # 501 の門（R1.5-C4）より先には進めないので、例外処理を試すときは
    # IMPLEMENTED を立ててから通す。門そのものは
    # test_retention_map_未実装なら501で止まる が押さえている
    with patch("plugins.retention_map_plugin.retention_map_plugin.IMPLEMENTED", True), \
         patch("plugins.retention_map_plugin.retention_map_plugin.analyze_retention_risks", side_effect=Exception("Retention error")):
        response = client.post("/api/youtube/retention-map", json={
            "video_id": "vid_123",
            "duration_sec": 300,
            "video_path": "dummy.mp4"
        })
        assert response.status_code == 500
        assert "Retention error" in response.json()["detail"]


# ===========================================================================
# Phase 4: シリーズ連動・継続視聴 テスト
# ===========================================================================

def test_series_register_exception():
    with patch("services.series_planner.series_planner.register_series", side_effect=Exception("Series error")):
        response = client.post("/api/youtube/series/register", json={
            "series_id": "ser_001",
            "title": "Camping Series",
            "theme": "Camp",
            "target_persona": "All"
        })
        assert response.status_code == 500
        assert "Series error" in response.json()["detail"]


def test_series_add_video_failure():
    with patch("services.series_planner.series_planner.add_video_to_series", return_value=False):
        response = client.post("/api/youtube/series/add-video", json={
            "series_id": "ser_001",
            "video_id": "vid_001",
            "video_title": "First Camping"
        })
        assert response.status_code == 200
        assert response.json()["success"] is False
        assert response.json()["message"] == "シリーズが見つかりません"


def test_series_add_video_exception():
    with patch("services.series_planner.series_planner.add_video_to_series", side_effect=Exception("Add video error")):
        response = client.post("/api/youtube/series/add-video", json={
            "series_id": "ser_001",
            "video_id": "vid_001",
            "video_title": "First Camping"
        })
        assert response.status_code == 500
        assert "Add video error" in response.json()["detail"]


def test_series_suggest_next_exception():
    with patch("services.series_planner.series_planner.suggest_next_video", side_effect=Exception("Suggest error")):
        response = client.post("/api/youtube/series/suggest-next", json={
            "series_id": "ser_001",
            "current_video_id": "vid_001",
            "current_context": ""
        })
        assert response.status_code == 500
        assert "Suggest error" in response.json()["detail"]


def test_series_playlist_exception():
    with patch("services.series_planner.series_planner.optimize_playlist", side_effect=Exception("Playlist error")):
        response = client.get("/api/youtube/series/ser_001/playlist")
        assert response.status_code == 500
        assert "Playlist error" in response.json()["detail"]


def test_series_session_score_exception():
    with patch("plugins.youtube_optimizer_plugin.youtube_optimizer.calculate_session_continuation_score", side_effect=Exception("Session score error")):
        response = client.post("/api/youtube/series/session-score", json={
            "video_id": "vid_001",
            "series_id": "ser_001",
            "has_end_screen": True,
            "has_teaser": True,
            "brand_consistency": 80.0
        })
        assert response.status_code == 500
        assert "Session score error" in response.json()["detail"]


# ===========================================================================
# Phase 5: セマンティック資産検索 テスト
# ===========================================================================

def test_assets_build_index_exception():
    with patch("asset_library.asset_library.build_search_index", side_effect=Exception("Build index error")):
        response = client.post("/api/youtube/assets/build-index?force_rebuild=False")
        assert response.status_code == 500
        assert "Build index error" in response.json()["detail"]


def test_assets_search_empty_query():
    response = client.get("/api/youtube/assets/search?q=&top_k=5")
    assert response.status_code == 400
    assert "クエリ(q)を指定してください。" in response.json()["detail"]


def test_assets_search_exception():
    with patch("asset_library.asset_library.search_assets", side_effect=Exception("Search error")):
        response = client.get("/api/youtube/assets/search?q=music&top_k=5")
        assert response.status_code == 500
        assert "Search error" in response.json()["detail"]


def test_assets_index_stats_exception():
    with patch("services.vector_search.vector_search_engine.get_index_stats", side_effect=Exception("Stats error")):
        response = client.get("/api/youtube/assets/index-stats")
        assert response.status_code == 500
        assert "Stats error" in response.json()["detail"]


# ===========================================================================
# Phase 6: 投稿スケジュール管理 テスト
# ===========================================================================

def test_schedule_add_exception():
    with patch("services.publish_scheduler.publish_scheduler.add_entry", side_effect=Exception("Schedule add error")):
        response = client.post("/api/youtube/schedule/add", json={
            "title": "Video 1",
            "planned_date": "2026-05-22",
            "status": "draft"
        })
        assert response.status_code == 500
        assert "Schedule add error" in response.json()["detail"]


def test_schedule_get_exception():
    with patch("services.publish_scheduler.publish_scheduler.get_schedule", side_effect=Exception("Schedule get error")):
        response = client.get("/api/youtube/schedule?upcoming_only=True")
        assert response.status_code == 500
        assert "Schedule get error" in response.json()["detail"]


def test_schedule_deadline_exception():
    with patch("services.publish_scheduler.publish_scheduler.get_next_deadline", side_effect=Exception("Deadline error")):
        response = client.get("/api/youtube/schedule/next-deadline")
        assert response.status_code == 500
        assert "Deadline error" in response.json()["detail"]


def test_schedule_pace_exception():
    with patch("services.publish_scheduler.publish_scheduler.analyze_pace", side_effect=Exception("Pace error")):
        response = client.get("/api/youtube/schedule/pace-analysis")
        assert response.status_code == 500
        assert "Pace error" in response.json()["detail"]


def test_schedule_update_status_failure():
    with patch("services.publish_scheduler.publish_scheduler.update_status", return_value=False):
        response = client.post("/api/youtube/schedule/update-status", json={
            "entry_id": "ent_001",
            "status": "published"
        })
        assert response.status_code == 200
        assert response.json()["success"] is False
        assert response.json()["message"] == "該当エントリが見つかりません"


def test_schedule_update_status_exception():
    with patch("services.publish_scheduler.publish_scheduler.update_status", side_effect=Exception("Update error")):
        response = client.post("/api/youtube/schedule/update-status", json={
            "entry_id": "ent_001",
            "status": "published"
        })
        assert response.status_code == 500
        assert "Update error" in response.json()["detail"]


def test_schedule_settings_get_exception():
    with patch("services.publish_scheduler.publish_scheduler.get_settings", side_effect=Exception("Settings get error")):
        response = client.get("/api/youtube/schedule/settings")
        assert response.status_code == 500
        assert "Settings get error" in response.json()["detail"]


def test_schedule_settings_update_exception():
    with patch("services.publish_scheduler.publish_scheduler.update_settings", side_effect=Exception("Settings update error")):
        response = client.put("/api/youtube/schedule/settings", json={
            "target_per_week": 3
        })
        assert response.status_code == 500
        assert "Settings update error" in response.json()["detail"]


# ===========================================================================
# Phase 7: サムネイル分析強化 テスト
# ===========================================================================

def test_thumbnail_analyze_exception():
    with patch("services.thumbnail_analyzer.thumbnail_analyzer.analyze", side_effect=Exception("Thumbnail analyze error")):
        response = client.post("/api/youtube/thumbnail/analyze", json={})
        assert response.status_code == 500
        assert "Thumbnail analyze error" in response.json()["detail"]


def test_thumbnail_analyze_image_exception():
    with patch("services.thumbnail_analyzer.thumbnail_analyzer.analyze_image", side_effect=Exception("Thumbnail image analyze error")):
        response = client.post("/api/youtube/thumbnail/analyze-image", json={
            "image_path": "thumb.jpg"
        })
        assert response.status_code == 500
        assert "Thumbnail image analyze error" in response.json()["detail"]


# ===========================================================================
# Phase 8: コメント分析 テスト
# ===========================================================================

def test_comments_analyze_exception():
    with patch("services.comment_analyzer.comment_analyzer.analyze_comments", side_effect=Exception("Comment analyze error")):
        response = client.post("/api/youtube/comments/analyze", json={
            "comments": ["good video"],
            "video_id": "vid_001"
        })
        assert response.status_code == 500
        assert "Comment analyze error" in response.json()["detail"]


def test_comments_request_trends_exception():
    with patch("services.comment_analyzer.comment_analyzer.get_request_trends", side_effect=Exception("Trends error")):
        response = client.get("/api/youtube/comments/request-trends")
        assert response.status_code == 500
        assert "Trends error" in response.json()["detail"]


# ===========================================================================
# Phase 9: ショート動画量産 テスト
# ===========================================================================

def test_shorts_extract_exception():
    with patch("services.shorts_generator.shorts_generator.extract_shorts_candidates", side_effect=Exception("Shorts extract error")):
        response = client.post("/api/youtube/shorts/extract", json={
            "segments": [{"start": 0, "end": 10, "text": "test"}],
            "video_duration_sec": 300,
            "video_id": "vid_001"
        })
        assert response.status_code == 500
        assert "Shorts extract error" in response.json()["detail"]


# ===========================================================================
# 正常系および追加の例外系テスト (カバレッジ向上用)
# ===========================================================================

def test_pre_plan_success():
    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.read_text", return_value='{"post_publish_feedbacks": [{"lessons_learned": ["lesson1"]}]}'), \
         patch("pathlib.Path.write_text") as mock_write:
        response = client.post("/api/youtube/pre-plan", json={
            "topic": "一人キャンプ飯",
            "target_audience": "20代男性",
            "genre": "Vlog",
            "reference_videos": []
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "title_candidates" in data
        assert len(data["title_candidates"]) > 0
        assert data["go_nogo"] in ("GO", "RECONSIDER")


def test_health_check_success():
    response = client.get("/api/youtube/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_optimize_success():
    class DummyHookAnalysis:
        def __init__(self):
            self.score = 85

    class DummyThumbnail:
        def __init__(self):
            self.id = "thumb_1"
            self.concept = "concept"
            self.target_emotion = "surprise"
            self.text_overlay = "overlay"
            self.predicted_ctr = 5.5
            self.ctr_confidence = "high"
            self.ctr_factors = ["factor1"]

    class DummySeoMetadata:
        def __init__(self):
            self.title = "SEO Title"

    class DummyResult:
        def __init__(self):
            self.task_id = "task_123"
            self.hook_score = 85
            self.hook_analysis = DummyHookAnalysis()
            self.thumbnail_candidates = [DummyThumbnail()]
            self.seo_metadata = DummySeoMetadata()
            self.highlights = ["highlight1"]
            self.soul_narrative = "soul"

    mock_result = DummyResult()

    with patch("plugins.youtube_optimizer_plugin.youtube_optimizer.optimize_context", return_value=mock_result):
        response = client.post("/api/youtube/optimize", json={
            "segments": [{"start": 0, "end": 2, "text": "こんにちは"}],
            "topics": ["Vlog"],
            "context": {}
        })
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["task_id"] == "task_123"


def test_generate_thumbnail_success():
    with patch("plugins.youtube_optimizer_plugin.youtube_optimizer.generate_thumbnail_with_imagen", return_value="path/to/thumb.jpg"):
        response = client.post("/api/youtube/generate-thumbnail", json={
            "thumbnail_id": "thumb_001",
            "context": {"concept": "cool thumbnail"}
        })
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["path"] == "path/to/thumb.jpg"


def test_improve_hook_success():
    mock_imp = MagicMock()
    mock_imp.improvement_type = "attention"
    mock_imp.original_text = "original"
    mock_imp.improved_text = "improved"
    mock_imp.expected_score_boost = 10
    mock_imp.rationale = "rationale"
    
    mock_best = MagicMock()
    mock_best.improvement_type = "attention"
    mock_best.improved_text = "improved"
    mock_best.expected_score_boost = 10

    mock_result = MagicMock()
    mock_result.original_score = 50
    mock_result.improvements = [mock_imp]
    mock_result.best_recommendation = mock_best
    mock_result.analysis_summary = "summary"

    with patch("services.hook_improver.hook_improver.generate_improvements", return_value=mock_result):
        response = client.post("/api/youtube/improve-hook", json={
            "hook_text": "みなさんこんにちは",
            "current_score": 50,
            "hook_analysis": {},
            "video_topic": "キャンプ"
        })
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["original_score"] == 50


def test_generate_hook_preview_success():
    mock_screenshot = MagicMock()
    mock_screenshot.before_image = "before.png"
    mock_screenshot.after_image = "after.png"
    mock_screenshot.comparison_image = "comp.png"

    mock_video = MagicMock()
    mock_video.before_video_path = "before.mp4"
    mock_video.after_video_path = "after.mp4"

    with patch("services.hook_preview_generator.hook_preview_generator.generate_screenshot_preview", return_value=mock_screenshot), \
         patch("services.hook_preview_generator.hook_preview_generator.generate_video_preview", return_value=mock_video):
         response = client.post("/api/youtube/hook-preview", json={
             "video_path": "dummy.mp4",
             "original_text": "before",
             "improved_text": "after",
             "task_id": "task_1"
         })
         assert response.status_code == 200
         assert response.json()["success"] is True
         assert response.json()["screenshot"]["before"] == "before.png"


def test_apply_hook_success():
    with patch("services.hook_evolution_service.hook_evolution_service.apply_improvement", return_value={"applied": True}):
        response = client.post("/api/youtube/apply-hook", json={
            "task_id": "task_1",
            "improvement_type": "attention",
            "improved_text": "after",
            "original_text": "before",
            "expected_score_boost": 10
        })
        assert response.status_code == 200
        assert response.json()["applied"] is True


def test_revert_hook_success():
    with patch("services.hook_evolution_service.hook_evolution_service.revert_latest", return_value={"reverted": True}):
        response = client.post("/api/youtube/revert-hook?task_id=task_1")
        assert response.status_code == 200
        assert response.json()["reverted"] is True


def test_hook_history_success():
    with patch("services.hook_evolution_service.hook_evolution_service.get_history", return_value={"history": []}):
        response = client.get("/api/youtube/hook-history?task_id=task_1")
        assert response.status_code == 200
        assert response.json()["history"] == []


def test_feedback_loop_success_with_deviation():
    mock_wagamama = MagicMock()
    mock_wagamama.get_record.return_value = {"youtube_video_id": "vid_123"}
    
    with patch("wagamama_manager.wagamama_manager", mock_wagamama), \
         patch("services.post_publish_collector.post_publish_collector.collect_performance_data") as mock_collect, \
         patch("services.prediction_validator.prediction_validator.validate_prediction") as mock_validate, \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.read_text", return_value='{"post_publish_feedbacks": []}'), \
         patch("pathlib.Path.write_text") as mock_write:
         
        mock_collect.return_value = {
            "metrics": {
                "click_through_rate": 5.2,
                "retention_rate_pct": 65.0,
                "views": 1000
            },
            "retention_map": {
                "drop_off_points": ["00:15", "01:30"]
            }
        }
        mock_validate.return_value = {
            "status": "success",
            "analysis": {
                "difference": 12.0,
                "significant_deviation": True,
                "predicted": 4.0
            }
        }
        
        response = client.post("/api/youtube/feedback-loop/waga_001")
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["admin_notified"] is True
        assert response.json()["evolution_log_updated"] is True


def test_retention_map_未実装なら501で止まる():
    """**未実装のものを「分析した」と言わない**（R1.5-C4）。

    2026-08-28 まで、この経路は `IMPLEMENTED` を見ずに
    `analyze_retention_risks()` を直接呼び、`success: True` を返したうえ
    HTML レポートまで書き出していた。中身は `random.random()` の
    モックなので、**同じリクエストで毎回違う値が API 応答と成果物に載る**。
    本線（`pipeline_coordinator._run_retention_analysis`）は同じ印を見て
    飛ばしているのに、API 経路だけ素通しだった。
    """
    from plugins.retention_map_plugin import retention_map_plugin

    assert retention_map_plugin.IMPLEMENTED is False, \
        "実装したら feature_gaps.json から retention_analysis を消し、このテストを直すこと"

    with patch("plugins.retention_map_plugin.retention_map_plugin.analyze_retention_risks") as 分析, \
         patch("services.preview_report_generator.preview_report_generator.generate_html_report") as 書き出し:
        response = client.post("/api/youtube/retention-map", json={
            "video_id": "vid_123",
            "duration_sec": 300,
            "video_path": "dummy.mp4"
        })

    assert response.status_code == 501, response.text
    detail = response.json()["detail"]
    assert detail["implemented"] is False
    assert detail["feature"] == "retention_analysis"
    # **分析も成果物の書き出しも起きないこと**（モックの値が外に出ない）
    分析.assert_not_called()
    書き出し.assert_not_called()


def test_retention_map_実装したら通る():
    """`IMPLEMENTED` を立てれば従来どおり動く（門が恒真でないことの確認）。"""
    mock_report = MagicMock()
    mock_report.overall_risk_assessment = "Low"
    mock_report.suggestions = ["suggestion1"]
    mock_report.model_dump.return_value = {"dummy": "data"}

    with patch("plugins.retention_map_plugin.retention_map_plugin.IMPLEMENTED", True), \
         patch("plugins.retention_map_plugin.retention_map_plugin.analyze_retention_risks", return_value=mock_report), \
         patch("services.preview_report_generator.preview_report_generator.generate_html_report", return_value="C:/path/report.html"):
        response = client.post("/api/youtube/retention-map", json={
            "video_id": "vid_123",
            "duration_sec": 300,
            "video_path": "dummy.mp4"
        })
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["overall_assessment"] == "Low"
        assert response.json()["report_url"] == "/api/reports/report.html"


def test_series_register_success():
    with patch("services.series_planner.series_planner.register_series", return_value={"series_id": "ser_001"}):
        response = client.post("/api/youtube/series/register", json={
            "series_id": "ser_001",
            "title": "Camping Series",
            "theme": "Camp",
            "target_persona": "All"
        })
        assert response.status_code == 200
        assert response.json()["success"] is True


def test_series_add_video_success():
    with patch("services.series_planner.series_planner.add_video_to_series", return_value=True):
        response = client.post("/api/youtube/series/add-video", json={
            "series_id": "ser_001",
            "video_id": "vid_001",
            "video_title": "First Camping"
        })
        assert response.status_code == 200
        assert response.json()["success"] is True


def test_series_suggest_next_success():
    with patch("services.series_planner.series_planner.suggest_next_video", return_value={"suggested_video_id": "vid_002"}):
        response = client.post("/api/youtube/series/suggest-next", json={
            "series_id": "ser_001",
            "current_video_id": "vid_001",
            "current_context": ""
        })
        assert response.status_code == 200
        assert response.json()["suggested_video_id"] == "vid_002"


def test_series_playlist_success():
    with patch("services.series_planner.series_planner.optimize_playlist", return_value={"playlist": []}):
        response = client.get("/api/youtube/series/ser_001/playlist")
        assert response.status_code == 200
        assert response.json()["playlist"] == []


def test_series_session_score_success():
    with patch("plugins.youtube_optimizer_plugin.youtube_optimizer.calculate_session_continuation_score", return_value={"score": 88}):
        response = client.post("/api/youtube/series/session-score", json={
            "video_id": "vid_001",
            "series_id": "ser_001",
            "has_end_screen": True,
            "has_teaser": True,
            "brand_consistency": 80.0
        })
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["score"] == 88


def test_assets_build_index_success():
    with patch("asset_library.asset_library.build_search_index", return_value={"status": "indexed"}):
        response = client.post("/api/youtube/assets/build-index?force_rebuild=False")
        assert response.status_code == 200
        assert response.json()["status"] == "indexed"


def test_assets_search_success():
    with patch("asset_library.asset_library.search_assets", return_value=[]), \
         patch("services.vector_search.vector_search_engine.get_index_stats", return_value={"stats": "ok"}):
        response = client.get("/api/youtube/assets/search?q=music&top_k=5")
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["count"] == 0


def test_assets_index_stats_success():
    with patch("services.vector_search.vector_search_engine.get_index_stats", return_value={"stats": "ok"}):
        response = client.get("/api/youtube/assets/index-stats")
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["stats"] == "ok"


def test_schedule_add_success():
    with patch("services.publish_scheduler.publish_scheduler.add_entry", return_value={"entry_id": "ent_001"}):
        response = client.post("/api/youtube/schedule/add", json={
            "title": "Video 1",
            "planned_date": "2026-05-22",
            "status": "draft"
        })
        assert response.status_code == 200
        assert response.json()["success"] is True


def test_schedule_get_success():
    with patch("services.publish_scheduler.publish_scheduler.get_schedule", return_value=[]):
        response = client.get("/api/youtube/schedule?upcoming_only=True")
        assert response.status_code == 200
        assert response.json()["success"] is True


def test_schedule_deadline_success():
    with patch("services.publish_scheduler.publish_scheduler.get_next_deadline", return_value={"deadline": "2026-05-25"}):
        response = client.get("/api/youtube/schedule/next-deadline")
        assert response.status_code == 200
        assert response.json()["deadline"] == "2026-05-25"


def test_schedule_pace_success():
    with patch("services.publish_scheduler.publish_scheduler.analyze_pace", return_value={"pace": "good"}):
        response = client.get("/api/youtube/schedule/pace-analysis")
        assert response.status_code == 200
        assert response.json()["pace"] == "good"


def test_schedule_update_status_success():
    with patch("services.publish_scheduler.publish_scheduler.update_status", return_value=True):
        response = client.post("/api/youtube/schedule/update-status", json={
            "entry_id": "ent_001",
            "status": "published"
        })
        assert response.status_code == 200
        assert response.json()["success"] is True


def test_schedule_settings_get_success():
    with patch("services.publish_scheduler.publish_scheduler.get_settings", return_value={"target": 3}):
        response = client.get("/api/youtube/schedule/settings")
        assert response.status_code == 200
        assert response.json()["success"] is True


def test_schedule_settings_update_success():
    with patch("services.publish_scheduler.publish_scheduler.update_settings", return_value={"target": 3}):
        response = client.put("/api/youtube/schedule/settings", json={
            "target_per_week": 3
        })
        assert response.status_code == 200
        assert response.json()["success"] is True


def test_thumbnail_analyze_success():
    with patch("services.thumbnail_analyzer.thumbnail_analyzer.analyze", return_value={"result": "ok"}):
        response = client.post("/api/youtube/thumbnail/analyze", json={})
        assert response.status_code == 200
        assert response.json()["result"] == "ok"


def test_thumbnail_analyze_image_success():
    with patch("services.thumbnail_analyzer.thumbnail_analyzer.analyze_image", return_value={"result": "ok"}):
        response = client.post("/api/youtube/thumbnail/analyze-image", json={
            "image_path": "thumb.jpg"
        })
        assert response.status_code == 200
        assert response.json()["result"] == "ok"


def test_comments_analyze_success():
    with patch("services.comment_analyzer.comment_analyzer.analyze_comments", return_value={"result": "ok"}):
        response = client.post("/api/youtube/comments/analyze", json={
            "comments": ["good video"],
            "video_id": "vid_001"
        })
        assert response.status_code == 200
        assert response.json()["result"] == "ok"


def test_comments_request_trends_success():
    with patch("services.comment_analyzer.comment_analyzer.get_request_trends", return_value={"trends": []}):
        response = client.get("/api/youtube/comments/request-trends")
        assert response.status_code == 200
        assert response.json()["trends"] == []


def test_shorts_extract_success():
    with patch("services.shorts_generator.shorts_generator.extract_shorts_candidates", return_value={"shorts": []}):
        response = client.post("/api/youtube/shorts/extract", json={
            "segments": [{"start": 0, "end": 10, "text": "test"}],
            "video_duration_sec": 300,
            "video_id": "vid_001"
        })
        assert response.status_code == 200
        assert response.json()["shorts"] == []


# ===========================================================================
# HTTPException 例外伝播テスト
# ===========================================================================

def test_pre_plan_http_exception():
    with patch("routers.youtube_optimizer._generate_title_candidates", side_effect=HTTPException(status_code=400, detail="Custom HTTP error")):
        response = client.post("/api/youtube/pre-plan", json={
            "topic": "一人キャンプ飯",
            "target_audience": "20代男性",
            "genre": "Vlog",
            "reference_videos": []
        })
        assert response.status_code == 400
        assert "Custom HTTP error" in response.json()["detail"]


def test_optimize_http_exception():
    with patch("plugins.youtube_optimizer_plugin.youtube_optimizer.optimize_context", side_effect=HTTPException(status_code=422, detail="Custom HTTP error")):
        response = client.post("/api/youtube/optimize", json={
            "segments": [{"start": 0, "end": 2, "text": "こんにちは"}],
            "topics": ["Vlog"],
            "context": {}
        })
        assert response.status_code == 422
        assert "Custom HTTP error" in response.json()["detail"]


def test_feedback_loop_http_exception():
    mock_wagamama = MagicMock()
    mock_wagamama.get_record.return_value = {"youtube_video_id": "vid_123"}
    with patch("wagamama_manager.wagamama_manager", mock_wagamama), \
         patch("services.post_publish_collector.post_publish_collector.collect_performance_data", side_effect=HTTPException(status_code=404, detail="Not Found")):
        response = client.post("/api/youtube/feedback-loop/waga_001")
        assert response.status_code == 404
        assert "Not Found" in response.json()["detail"]


def test_pre_plan_corrupted_json_fallback():
    # evolution_log.json が破損したJSONである場合のフォールバックテスト
    with patch("pathlib.Path.exists", return_value=True), \
         patch("routers.youtube_optimizer.safe_load_json", return_value={}):
        response = client.post("/api/youtube/pre-plan", json={
            "topic": "一人キャンプ飯",
            "target_audience": "20代男性",
            "genre": "Vlog",
            "reference_videos": []
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["past_lessons"] == ["初回のため参考データなし。制作後のフィードバックで精度が向上します。"]


def test_pre_plan_invalid_json_type_fallback():
    # evolution_log.json が辞書形式ではないJSON（例: リスト）である場合のフォールバックテスト
    with patch("pathlib.Path.exists", return_value=True), \
         patch("routers.youtube_optimizer.safe_load_json", return_value=[]):
        response = client.post("/api/youtube/pre-plan", json={
            "topic": "一人キャンプ飯",
            "target_audience": "20代男性",
            "genre": "Vlog",
            "reference_videos": []
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["past_lessons"] == ["初回のため参考データなし。制作後のフィードバックで精度が向上します。"]


def test_record_post_publish_feedback_io_error_fallback():
    # feedback-loop の _record_post_publish_feedback でファイルIOエラーが発生した時、
    # 例外が内部でキャッチされ、API自体は200 OKで正常終了することを検証するテスト
    mock_wagamama = MagicMock()
    mock_wagamama.get_record.return_value = {"youtube_video_id": "vid_123"}
    
    with patch("wagamama_manager.wagamama_manager", mock_wagamama), \
         patch("services.post_publish_collector.post_publish_collector.collect_performance_data") as mock_collect, \
         patch("services.prediction_validator.prediction_validator.validate_prediction") as mock_validate, \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.read_text", side_effect=OSError("Read permission denied")), \
         patch("pathlib.Path.write_text") as mock_write:
         
        mock_collect.return_value = {
            "metrics": {
                "click_through_rate": 5.2,
                "retention_rate_pct": 65.0,
                "views": 1000
            },
            "retention_map": {
                "drop_off_points": ["00:15", "01:30"]
            }
        }
        mock_validate.return_value = {
            "status": "success",
            "analysis": {
                "difference": 1.0,
                "significant_deviation": False,
                "predicted": 4.0
            }
        }
        
        response = client.post("/api/youtube/feedback-loop/waga_001")
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["evolution_log_updated"] is True  # 内部でエラーになっても成功扱い
        mock_write.assert_not_called()


# ===========================================================================
# 追加の HTTPException 例外伝播および境界値テスト (カバレッジ向上用)
# ===========================================================================

def test_generate_thumbnail_http_exception():
    with patch("plugins.youtube_optimizer_plugin.youtube_optimizer.generate_thumbnail_with_imagen", side_effect=HTTPException(status_code=400, detail="Imagen HTTP error")):
        response = client.post("/api/youtube/generate-thumbnail", json={
            "thumbnail_id": "thumb_001",
            "context": {"concept": "cool thumbnail"}
        })
        assert response.status_code == 400
        assert "Imagen HTTP error" in response.json()["detail"]


def test_improve_hook_http_exception():
    with patch("services.hook_improver.hook_improver.generate_improvements", side_effect=HTTPException(status_code=400, detail="Hook improver HTTP error")):
        response = client.post("/api/youtube/improve-hook", json={
            "hook_text": "みなさんこんにちは",
            "current_score": 50,
            "hook_analysis": {},
            "video_topic": "キャンプ"
        })
        assert response.status_code == 400
        assert "Hook improver HTTP error" in response.json()["detail"]


def test_generate_hook_preview_http_exception():
    with patch("services.hook_preview_generator.hook_preview_generator.generate_screenshot_preview", side_effect=HTTPException(status_code=400, detail="Preview HTTP error")):
        response = client.post("/api/youtube/hook-preview", json={
            "video_path": "dummy.mp4",
            "original_text": "before",
            "improved_text": "after",
            "task_id": "task_1"
        })
        assert response.status_code == 400
        assert "Preview HTTP error" in response.json()["detail"]


def test_apply_hook_http_exception():
    with patch("services.hook_evolution_service.hook_evolution_service.apply_improvement", side_effect=HTTPException(status_code=400, detail="Apply HTTP error")):
        response = client.post("/api/youtube/apply-hook", json={
            "task_id": "task_1",
            "improvement_type": "attention",
            "improved_text": "after",
            "original_text": "before",
            "expected_score_boost": 10
        })
        assert response.status_code == 400
        assert "Apply HTTP error" in response.json()["detail"]


def test_revert_hook_http_exception():
    with patch("services.hook_evolution_service.hook_evolution_service.revert_latest", side_effect=HTTPException(status_code=400, detail="Revert HTTP error")):
        response = client.post("/api/youtube/revert-hook?task_id=task_1")
        assert response.status_code == 400
        assert "Revert HTTP error" in response.json()["detail"]


def test_hook_history_http_exception():
    with patch("services.hook_evolution_service.hook_evolution_service.get_history", side_effect=HTTPException(status_code=400, detail="History HTTP error")):
        response = client.get("/api/youtube/hook-history?task_id=task_1")
        assert response.status_code == 400
        assert "History HTTP error" in response.json()["detail"]


def test_record_post_publish_feedback_http_exception():
    # _record_post_publish_feedback で HTTPException が発生した場合に raise されることを検証
    from routers.youtube_optimizer import _record_post_publish_feedback
    with patch("pathlib.Path.exists", return_value=True), \
         patch("routers.youtube_optimizer.safe_load_json", side_effect=HTTPException(status_code=400, detail="Feedback HTTP error")):
        with pytest.raises(HTTPException) as exc_info:
            _record_post_publish_feedback("waga_001", "vid_123", {}, {})
        assert exc_info.value.status_code == 400
        assert "Feedback HTTP error" in exc_info.value.detail


def test_retention_map_http_exception():
    # 501 の門（R1.5-C4）より先には進めないので、例外処理を試すときは
    # IMPLEMENTED を立ててから通す。門そのものは
    # test_retention_map_未実装なら501で止まる が押さえている
    with patch("plugins.retention_map_plugin.retention_map_plugin.IMPLEMENTED", True), \
         patch("plugins.retention_map_plugin.retention_map_plugin.analyze_retention_risks", side_effect=HTTPException(status_code=400, detail="Retention HTTP error")):
        response = client.post("/api/youtube/retention-map", json={
            "video_id": "vid_123",
            "duration_sec": 300,
            "video_path": "dummy.mp4"
        })
        assert response.status_code == 400
        assert "Retention HTTP error" in response.json()["detail"]


def test_series_register_http_exception():
    with patch("services.series_planner.series_planner.register_series", side_effect=HTTPException(status_code=400, detail="Series HTTP error")):
        response = client.post("/api/youtube/series/register", json={
            "series_id": "ser_001",
            "title": "Camping Series",
            "theme": "Camp",
            "target_persona": "All"
        })
        assert response.status_code == 400
        assert "Series HTTP error" in response.json()["detail"]


def test_series_add_video_http_exception():
    with patch("services.series_planner.series_planner.add_video_to_series", side_effect=HTTPException(status_code=400, detail="Add video HTTP error")):
        response = client.post("/api/youtube/series/add-video", json={
            "series_id": "ser_001",
            "video_id": "vid_001",
            "video_title": "First Camping"
        })
        assert response.status_code == 400
        assert "Add video HTTP error" in response.json()["detail"]


def test_series_suggest_next_http_exception():
    with patch("services.series_planner.series_planner.suggest_next_video", side_effect=HTTPException(status_code=400, detail="Suggest HTTP error")):
        response = client.post("/api/youtube/series/suggest-next", json={
            "series_id": "ser_001",
            "current_video_id": "vid_001",
            "current_context": ""
        })
        assert response.status_code == 400
        assert "Suggest HTTP error" in response.json()["detail"]


def test_series_playlist_http_exception():
    with patch("services.series_planner.series_planner.optimize_playlist", side_effect=HTTPException(status_code=400, detail="Playlist HTTP error")):
        response = client.get("/api/youtube/series/ser_001/playlist")
        assert response.status_code == 400
        assert "Playlist HTTP error" in response.json()["detail"]


def test_series_session_score_http_exception():
    with patch("plugins.youtube_optimizer_plugin.youtube_optimizer.calculate_session_continuation_score", side_effect=HTTPException(status_code=400, detail="Session HTTP error")):
        response = client.post("/api/youtube/series/session-score", json={
            "video_id": "vid_001",
            "series_id": "ser_001",
            "has_end_screen": True,
            "has_teaser": True,
            "brand_consistency": 80.0
        })
        assert response.status_code == 400
        assert "Session HTTP error" in response.json()["detail"]


def test_assets_build_index_http_exception():
    with patch("asset_library.asset_library.build_search_index", side_effect=HTTPException(status_code=400, detail="Build HTTP error")):
        response = client.post("/api/youtube/assets/build-index?force_rebuild=False")
        assert response.status_code == 400
        assert "Build HTTP error" in response.json()["detail"]


def test_assets_search_http_exception():
    with patch("asset_library.asset_library.search_assets", side_effect=HTTPException(status_code=400, detail="Search HTTP error")):
        response = client.get("/api/youtube/assets/search?q=music&top_k=5")
        assert response.status_code == 400
        assert "Search HTTP error" in response.json()["detail"]


def test_assets_index_stats_http_exception():
    with patch("services.vector_search.vector_search_engine.get_index_stats", side_effect=HTTPException(status_code=400, detail="Stats HTTP error")):
        response = client.get("/api/youtube/assets/index-stats")
        assert response.status_code == 400
        assert "Stats HTTP error" in response.json()["detail"]


def test_schedule_add_http_exception():
    with patch("services.publish_scheduler.publish_scheduler.add_entry", side_effect=HTTPException(status_code=400, detail="Schedule Add HTTP error")):
        response = client.post("/api/youtube/schedule/add", json={
            "title": "Video 1",
            "planned_date": "2026-05-22",
            "status": "draft"
        })
        assert response.status_code == 400
        assert "Schedule Add HTTP error" in response.json()["detail"]


def test_schedule_get_http_exception():
    with patch("services.publish_scheduler.publish_scheduler.get_schedule", side_effect=HTTPException(status_code=400, detail="Schedule Get HTTP error")):
        response = client.get("/api/youtube/schedule?upcoming_only=True")
        assert response.status_code == 400
        assert "Schedule Get HTTP error" in response.json()["detail"]


def test_schedule_deadline_http_exception():
    with patch("services.publish_scheduler.publish_scheduler.get_next_deadline", side_effect=HTTPException(status_code=400, detail="Deadline HTTP error")):
        response = client.get("/api/youtube/schedule/next-deadline")
        assert response.status_code == 400
        assert "Deadline HTTP error" in response.json()["detail"]


def test_schedule_pace_http_exception():
    with patch("services.publish_scheduler.publish_scheduler.analyze_pace", side_effect=HTTPException(status_code=400, detail="Pace HTTP error")):
        response = client.get("/api/youtube/schedule/pace-analysis")
        assert response.status_code == 400
        assert "Pace HTTP error" in response.json()["detail"]


def test_schedule_update_status_http_exception():
    with patch("services.publish_scheduler.publish_scheduler.update_status", side_effect=HTTPException(status_code=400, detail="Update HTTP error")):
        response = client.post("/api/youtube/schedule/update-status", json={
            "entry_id": "ent_001",
            "status": "published"
        })
        assert response.status_code == 400
        assert "Update HTTP error" in response.json()["detail"]


def test_schedule_settings_get_http_exception():
    with patch("services.publish_scheduler.publish_scheduler.get_settings", side_effect=HTTPException(status_code=400, detail="Settings Get HTTP error")):
        response = client.get("/api/youtube/schedule/settings")
        assert response.status_code == 400
        assert "Settings Get HTTP error" in response.json()["detail"]


def test_schedule_settings_update_http_exception():
    with patch("services.publish_scheduler.publish_scheduler.update_settings", side_effect=HTTPException(status_code=400, detail="Settings Update HTTP error")):
        response = client.put("/api/youtube/schedule/settings", json={
            "target_per_week": 3
        })
        assert response.status_code == 400
        assert "Settings Update HTTP error" in response.json()["detail"]


def test_thumbnail_analyze_http_exception():
    with patch("services.thumbnail_analyzer.thumbnail_analyzer.analyze", side_effect=HTTPException(status_code=400, detail="Analyze HTTP error")):
        response = client.post("/api/youtube/thumbnail/analyze", json={})
        assert response.status_code == 400
        assert "Analyze HTTP error" in response.json()["detail"]


def test_thumbnail_analyze_image_http_exception():
    with patch("services.thumbnail_analyzer.thumbnail_analyzer.analyze_image", side_effect=HTTPException(status_code=400, detail="Analyze Image HTTP error")):
        response = client.post("/api/youtube/thumbnail/analyze-image", json={
            "image_path": "thumb.jpg"
        })
        assert response.status_code == 400
        assert "Analyze Image HTTP error" in response.json()["detail"]


def test_comments_analyze_http_exception():
    with patch("services.comment_analyzer.comment_analyzer.analyze_comments", side_effect=HTTPException(status_code=400, detail="Comments HTTP error")):
        response = client.post("/api/youtube/comments/analyze", json={
            "comments": ["good video"],
            "video_id": "vid_001"
        })
        assert response.status_code == 400
        assert "Comments HTTP error" in response.json()["detail"]


def test_comments_request_trends_http_exception():
    with patch("services.comment_analyzer.comment_analyzer.get_request_trends", side_effect=HTTPException(status_code=400, detail="Trends HTTP error")):
        response = client.get("/api/youtube/comments/request-trends")
        assert response.status_code == 400
        assert "Trends HTTP error" in response.json()["detail"]


def test_shorts_extract_http_exception():
    with patch("services.shorts_generator.shorts_generator.extract_shorts_candidates", side_effect=HTTPException(status_code=400, detail="Shorts HTTP error")):
        response = client.post("/api/youtube/shorts/extract", json={
            "segments": [{"start": 0, "end": 10, "text": "test"}],
            "video_duration_sec": 300,
            "video_id": "vid_001"
        })
        assert response.status_code == 400
        assert "Shorts HTTP error" in response.json()["detail"]


def test_feedback_loop_rotation_over_50():
    dummy_feedbacks = [{"timestamp": "2026-05-25T18:00:00", "wagamama_id": f"waga_{i}", "lessons_learned": []} for i in range(55)]
    mock_data = {"post_publish_feedbacks": dummy_feedbacks}
    import json
    
    mock_wagamama = MagicMock()
    mock_wagamama.get_record.return_value = {"youtube_video_id": "vid_123"}
    
    with patch("wagamama_manager.wagamama_manager", mock_wagamama), \
         patch("services.post_publish_collector.post_publish_collector.collect_performance_data") as mock_collect, \
         patch("services.prediction_validator.prediction_validator.validate_prediction") as mock_validate, \
         patch("pathlib.Path.exists", return_value=True), \
         patch("routers.youtube_optimizer.safe_load_json", return_value=mock_data), \
         patch("routers.youtube_optimizer.safe_save_json") as mock_write:
         
        mock_collect.return_value = {
            "metrics": {
                "click_through_rate": 5.2,
                "retention_rate_pct": 65.0,
                "views": 1000
            },
            "retention_map": {
                "drop_off_points": ["00:15", "01:30"]
            }
        }
        mock_validate.return_value = {
            "status": "success",
            "analysis": {
                "difference": 1.0,
                "significant_deviation": False,
                "predicted": 4.0
            }
        }
        
        response = client.post("/api/youtube/feedback-loop/waga_new")
        assert response.status_code == 200
        assert response.json()["success"] is True
        
        mock_write.assert_called_once()
        written_data = mock_write.call_args[0][1]
        
        assert len(written_data["post_publish_feedbacks"]) == 50
        assert written_data["post_publish_feedbacks"][-1]["wagamama_id"] == "waga_new"


def test_pre_plan_evolution_log_http_exception():
    with patch("pathlib.Path.exists", return_value=True), \
         patch("routers.youtube_optimizer.safe_load_json", side_effect=HTTPException(status_code=400, detail="Evolution Log Read HTTP error")):
        response = client.post("/api/youtube/pre-plan", json={
            "topic": "一人キャンプ飯",
            "target_audience": "20代男性",
            "genre": "Vlog",
            "reference_videos": []
        })
        assert response.status_code == 400
        assert "Evolution Log Read HTTP error" in response.json()["detail"]


# ===========================================================================
# カバレッジ 100% を達成するための ValueError / Exception ハンドリングテスト
# ===========================================================================

def test_pre_plan_value_error():
    with patch("routers.youtube_optimizer._generate_title_candidates", side_effect=ValueError("Invalid plan topic")):
        response = client.post("/api/youtube/pre-plan", json={
            "topic": "一人キャンプ飯",
            "target_audience": "20代男性",
            "genre": "Vlog",
            "reference_videos": []
        })
        assert response.status_code == 400
        assert "Invalid plan topic" in response.json()["detail"]


def test_optimize_value_error():
    with patch("plugins.youtube_optimizer_plugin.youtube_optimizer.optimize_context", side_effect=ValueError("Optimization failed")):
        response = client.post("/api/youtube/optimize", json={
            "segments": [{"start": 0, "end": 2, "text": "こんにちは"}],
            "topics": ["Vlog"],
            "context": {}
        })
        assert response.status_code == 400
        assert "Optimization failed" in response.json()["detail"]


def test_feedback_loop_value_error():
    mock_wagamama = MagicMock()
    mock_wagamama.get_record.return_value = {"youtube_video_id": "vid_123"}
    with patch("wagamama_manager.wagamama_manager", mock_wagamama), \
         patch("services.post_publish_collector.post_publish_collector.collect_performance_data", side_effect=ValueError("Feedback value error")):
        response = client.post("/api/youtube/feedback-loop/waga_001")
        assert response.status_code == 400
        assert "Feedback value error" in response.json()["detail"]


def test_feedback_loop_wagamama_not_found():
    mock_wagamama = MagicMock()
    mock_wagamama.get_record.return_value = None
    with patch("wagamama_manager.wagamama_manager", mock_wagamama), \
         patch("services.post_publish_collector.post_publish_collector.collect_performance_data") as mock_collect, \
         patch("services.prediction_validator.prediction_validator.validate_prediction") as mock_validate, \
         patch("routers.youtube_optimizer._record_post_publish_feedback"):
        mock_collect.return_value = {}
        mock_validate.return_value = {"status": "success", "analysis": {"difference": 1.0, "significant_deviation": False}}
        response = client.post("/api/youtube/feedback-loop/waga_001")
        # フォールバックして 200 OK になる
        assert response.status_code == 200
        assert response.json()["success"] is True


def test_feedback_loop_wagamama_no_video_id():
    mock_wagamama = MagicMock()
    mock_wagamama.get_record.return_value = {"youtube_video_id": None}
    with patch("wagamama_manager.wagamama_manager", mock_wagamama), \
         patch("services.post_publish_collector.post_publish_collector.collect_performance_data") as mock_collect, \
         patch("services.prediction_validator.prediction_validator.validate_prediction") as mock_validate, \
         patch("routers.youtube_optimizer._record_post_publish_feedback"):
        mock_collect.return_value = {}
        mock_validate.return_value = {"status": "success", "analysis": {"difference": 1.0, "significant_deviation": False}}
        response = client.post("/api/youtube/feedback-loop/waga_001")
        # フォールバックして 200 OK になる
        assert response.status_code == 200
        assert response.json()["success"] is True


def test_feedback_loop_general_exception():
    mock_wagamama = MagicMock()
    mock_wagamama.get_record.return_value = {"youtube_video_id": "vid_123"}
    with patch("wagamama_manager.wagamama_manager", mock_wagamama), \
         patch("services.post_publish_collector.post_publish_collector.collect_performance_data", side_effect=Exception("Feedback general crash")):
        response = client.post("/api/youtube/feedback-loop/waga_001")
        assert response.status_code == 500
        assert "Feedback general crash" in response.json()["detail"]


def test_generate_thumbnail_value_error():
    with patch("plugins.youtube_optimizer_plugin.youtube_optimizer.generate_thumbnail_with_imagen", side_effect=ValueError("Thumbnail value error")):
        response = client.post("/api/youtube/generate-thumbnail", json={
            "thumbnail_id": "thumb_001",
            "context": {"concept": "cool thumbnail"}
        })
        assert response.status_code == 400
        assert "Thumbnail value error" in response.json()["detail"]


def test_improve_hook_value_error():
    with patch("services.hook_improver.hook_improver.generate_improvements", side_effect=ValueError("Hook value error")):
        response = client.post("/api/youtube/improve-hook", json={
            "hook_text": "みなさんこんにちは",
            "current_score": 50,
            "hook_analysis": {},
            "video_topic": "キャンプ"
        })
        assert response.status_code == 400
        assert "Hook value error" in response.json()["detail"]


def test_generate_hook_preview_value_error():
    with patch("services.hook_preview_generator.hook_preview_generator.generate_screenshot_preview", side_effect=ValueError("Preview value error")):
        response = client.post("/api/youtube/hook-preview", json={
            "video_path": "dummy.mp4",
            "original_text": "before",
            "improved_text": "after",
            "task_id": "task_1"
        })
        assert response.status_code == 400
        assert "Preview value error" in response.json()["detail"]


def test_apply_hook_value_error():
    with patch("services.hook_evolution_service.hook_evolution_service.apply_improvement", side_effect=ValueError("Apply value error")):
        response = client.post("/api/youtube/apply-hook", json={
            "task_id": "task_1",
            "improvement_type": "attention",
            "improved_text": "after",
            "original_text": "before",
            "expected_score_boost": 10
        })
        assert response.status_code == 400
        assert "Apply value error" in response.json()["detail"]


def test_revert_hook_value_error():
    with patch("services.hook_evolution_service.hook_evolution_service.revert_latest", side_effect=ValueError("Revert value error")):
        response = client.post("/api/youtube/revert-hook?task_id=task_1")
        assert response.status_code == 400
        assert "Revert value error" in response.json()["detail"]


def test_hook_history_value_error():
    with patch("services.hook_evolution_service.hook_evolution_service.get_history", side_effect=ValueError("History value error")):
        response = client.get("/api/youtube/hook-history?task_id=task_1")
        assert response.status_code == 400
        assert "History value error" in response.json()["detail"]


def test_retention_map_value_error():
    # 501 の門（R1.5-C4）より先には進めないので、例外処理を試すときは
    # IMPLEMENTED を立ててから通す。門そのものは
    # test_retention_map_未実装なら501で止まる が押さえている
    with patch("plugins.retention_map_plugin.retention_map_plugin.IMPLEMENTED", True), \
         patch("plugins.retention_map_plugin.retention_map_plugin.analyze_retention_risks", side_effect=ValueError("Retention value error")):
        response = client.post("/api/youtube/retention-map", json={
            "video_id": "vid_123",
            "duration_sec": 300,
            "video_path": "dummy.mp4"
        })
        assert response.status_code == 400
        assert "Retention value error" in response.json()["detail"]


def test_series_register_value_error():
    with patch("services.series_planner.series_planner.register_series", side_effect=ValueError("Series value error")):
        response = client.post("/api/youtube/series/register", json={
            "series_id": "ser_001",
            "title": "Camping Series",
            "theme": "Camp",
            "target_persona": "All"
        })
        assert response.status_code == 400
        assert "Series value error" in response.json()["detail"]


def test_series_add_video_value_error():
    with patch("services.series_planner.series_planner.add_video_to_series", side_effect=ValueError("Add video value error")):
        response = client.post("/api/youtube/series/add-video", json={
            "series_id": "ser_001",
            "video_id": "vid_001",
            "video_title": "First Camping"
        })
        assert response.status_code == 400
        assert "Add video value error" in response.json()["detail"]


def test_series_suggest_next_value_error():
    with patch("services.series_planner.series_planner.suggest_next_video", side_effect=ValueError("Suggest value error")):
        response = client.post("/api/youtube/series/suggest-next", json={
            "series_id": "ser_001",
            "current_video_id": "vid_001",
            "current_context": ""
        })
        assert response.status_code == 400
        assert "Suggest value error" in response.json()["detail"]


def test_series_playlist_value_error():
    with patch("services.series_planner.series_planner.optimize_playlist", side_effect=ValueError("Playlist value error")):
        response = client.get("/api/youtube/series/ser_001/playlist")
        assert response.status_code == 400
        assert "Playlist value error" in response.json()["detail"]


def test_series_session_score_value_error():
    with patch("plugins.youtube_optimizer_plugin.youtube_optimizer.calculate_session_continuation_score", side_effect=ValueError("Session value error")):
        response = client.post("/api/youtube/series/session-score", json={
            "video_id": "vid_001",
            "series_id": "ser_001",
            "has_end_screen": True,
            "has_teaser": True,
            "brand_consistency": 80.0
        })
        assert response.status_code == 400
        assert "Session value error" in response.json()["detail"]


def test_assets_build_index_value_error():
    with patch("asset_library.asset_library.build_search_index", side_effect=ValueError("Build value error")):
        response = client.post("/api/youtube/assets/build-index?force_rebuild=False")
        assert response.status_code == 400
        assert "Build value error" in response.json()["detail"]


def test_assets_search_value_error():
    with patch("asset_library.asset_library.search_assets", side_effect=ValueError("Search value error")):
        response = client.get("/api/youtube/assets/search?q=music&top_k=5")
        assert response.status_code == 400
        assert "Search value error" in response.json()["detail"]


def test_assets_index_stats_value_error():
    with patch("services.vector_search.vector_search_engine.get_index_stats", side_effect=ValueError("Stats value error")):
        response = client.get("/api/youtube/assets/index-stats")
        assert response.status_code == 400
        assert "Stats value error" in response.json()["detail"]
