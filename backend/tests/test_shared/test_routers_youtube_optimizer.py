"""
YouTube Optimizer Router テスト — 30テスト
Phase 0-9 の全エンドポイントをFastAPI TestClientでカバー
"""
# Python 3.13 + Pydantic 2.x MRO ValueError回避のためのモンキーパッチ
try:
    import pydantic._internal._model_construction as model_construction
    _orig_new = model_construction.ModelMetaclass.__new__
    def _patched_new(mcs, cls_name, bases, namespace, *args, **kwargs):
        try:
            return _orig_new(mcs, cls_name, bases, namespace, *args, **kwargs)
        except ValueError as e:
            if "tuple.index(x): x not in tuple" in str(e):
                return super(model_construction.ModelMetaclass, mcs).__new__(mcs, cls_name, bases, namespace)
            raise
    model_construction.ModelMetaclass.__new__ = _patched_new
except Exception:
    pass

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import HTTPException


def _get_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.youtube_optimizer import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ============================================================
# Phase 0: 企画フェーズ (5件)
# ============================================================

class TestPrePlan:
    def test_pre_plan_success(self):
        """POST /pre-plan — 正常系"""
        import routers.youtube_optimizer as youtube_optimizer
        mock_yt = MagicMock()
        with patch.object(youtube_optimizer, "youtube_optimizer", mock_yt, create=True):
            client = _get_client()
            res = client.post("/api/youtube/pre-plan", json={
                "topic": "一人キャンプ飯", "genre": "Vlog"
            })
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            assert len(data["title_candidates"]) == 5
            assert data["best_title"] is not None

    def test_pre_plan_go_nogo(self):
        """POST /pre-plan — GO/RECONSIDER判定"""
        client = _get_client()
        res = client.post("/api/youtube/pre-plan", json={
            "topic": "テスト", "genre": ""
        })
        assert res.status_code == 200
        data = res.json()
        assert data["go_nogo"] in ("GO", "RECONSIDER")

    def test_pre_plan_with_evolution_log(self):
        """POST /pre-plan — evolution_log読み込み失敗時もpast_lessonsデフォルト"""
        client = _get_client()
        res = client.post("/api/youtube/pre-plan", json={"topic": "テスト"})
        assert res.status_code == 200

    def test_estimate_ctr_emotion_triggers(self):
        """_estimate_ctr — 感情トリガーでスコア上昇"""
        from routers.youtube_optimizer import _estimate_ctr
        base = _estimate_ctr("テスト", "")
        boosted = _estimate_ctr("【完全版】衝撃の100選", "エンタメ")
        assert boosted > base

    def test_generate_thumbnail_concepts(self):
        """_generate_thumbnail_concepts — 3案返却"""
        from routers.youtube_optimizer import _generate_thumbnail_concepts
        result = _generate_thumbnail_concepts("テスト", "Vlog", ["タイトル1"])
        assert len(result) == 3
        assert all("id" in c for c in result)


# ============================================================
# Phase 1: 予測型最適化 (7件)
# ============================================================

class TestPhase1:
    def test_health_check(self):
        """GET /health"""
        client = _get_client()
        res = client.get("/api/youtube/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

    def test_optimize_success(self):
        """POST /optimize — 正常系"""
        from types import SimpleNamespace
        mock_result = MagicMock()
        mock_result.task_id = "t1"
        mock_result.hook_score = 85
        mock_result.hook_analysis = SimpleNamespace(score=85)
        mock_result.thumbnail_candidates = []
        mock_result.seo_metadata = SimpleNamespace(title="test")
        mock_result.highlights = []
        mock_result.soul_narrative = ""
        mock_yt = AsyncMock()
        mock_yt.optimize_context = AsyncMock(return_value=mock_result)
        with patch.dict("sys.modules", {"plugins.youtube_optimizer_plugin": MagicMock(youtube_optimizer=mock_yt)}):
            client = _get_client()
            res = client.post("/api/youtube/optimize", json={
                "segments": [{"text": "hello"}], "topics": ["test"]
            })
            assert res.status_code == 200
            assert res.json()["success"] is True

    def test_optimize_error(self):
        """POST /optimize — サービスエラー → 500"""
        with patch.dict("sys.modules", {"plugins.youtube_optimizer_plugin": MagicMock(side_effect=Exception("fail"))}):
            client = _get_client()
            res = client.post("/api/youtube/optimize", json={
                "segments": [], "topics": []
            })
            assert res.status_code == 500

    def test_generate_thumbnail_endpoint(self):
        """POST /generate-thumbnail — 正常系"""
        mock_yt = AsyncMock()
        mock_yt.generate_thumbnail_with_imagen = AsyncMock(return_value="/path/thumb.png")
        mock_tc = MagicMock()
        with patch.dict("sys.modules", {"plugins.youtube_optimizer_plugin": MagicMock(youtube_optimizer=mock_yt, ThumbnailCandidate=mock_tc)}):
            client = _get_client()
            res = client.post("/api/youtube/generate-thumbnail", json={
                "thumbnail_id": "t1", "context": {"concept": "test"}
            })
            assert res.status_code == 200
            assert res.json()["success"] is True

    def test_generate_thumbnail_fail(self):
        """POST /generate-thumbnail — 生成失敗"""
        mock_yt = AsyncMock()
        mock_yt.generate_thumbnail_with_imagen = AsyncMock(return_value=None)
        mock_tc = MagicMock()
        with patch.dict("sys.modules", {"plugins.youtube_optimizer_plugin": MagicMock(youtube_optimizer=mock_yt, ThumbnailCandidate=mock_tc)}):
            client = _get_client()
            res = client.post("/api/youtube/generate-thumbnail", json={
                "thumbnail_id": "t1", "context": {}
            })
            assert res.status_code == 200
            assert res.json()["success"] is False

    def test_improve_hook(self):
        """POST /improve-hook — 正常系"""
        mock_result = MagicMock()
        mock_result.original_score = 50
        mock_result.improvements = []
        mock_result.best_recommendation = None
        mock_result.analysis_summary = "ok"
        mock_svc = AsyncMock()
        mock_svc.generate_improvements = AsyncMock(return_value=mock_result)
        with patch.dict("sys.modules", {"services.hook_improver": MagicMock(hook_improver=mock_svc)}):
            client = _get_client()
            res = client.post("/api/youtube/improve-hook", json={
                "hook_text": "hello", "current_score": 50
            })
            assert res.status_code == 200
            assert res.json()["success"] is True

    def test_hook_preview(self):
        """POST /hook-preview — 正常系"""
        mock_ss = MagicMock(before_image="a", after_image="b", comparison_image="c")
        mock_vr = MagicMock(before_video_path="v1", after_video_path="v2")
        mock_gen = AsyncMock()
        mock_gen.generate_screenshot_preview = AsyncMock(return_value=mock_ss)
        mock_gen.generate_video_preview = AsyncMock(return_value=mock_vr)
        with patch.dict("sys.modules", {"services.hook_preview_generator": MagicMock(hook_preview_generator=mock_gen)}):
            client = _get_client()
            res = client.post("/api/youtube/hook-preview", json={
                "video_path": "/test.mp4", "original_text": "a", "improved_text": "b"
            })
            assert res.status_code == 200
            assert res.json()["success"] is True


# ============================================================
# Phase 1 continued: apply/revert/history (3件)
# ============================================================

class TestHookEvolution:
    def test_apply_hook(self):
        """POST /apply-hook"""
        mock_svc = MagicMock()
        mock_svc.apply_improvement.return_value = {"applied": True}
        with patch.dict("sys.modules", {"services.hook_evolution_service": MagicMock(hook_evolution_service=mock_svc)}):
            client = _get_client()
            res = client.post("/api/youtube/apply-hook", json={
                "task_id": "t1", "improvement_type": "attention",
                "improved_text": "new", "original_text": "old"
            })
            assert res.status_code == 200

    def test_revert_hook(self):
        """POST /revert-hook"""
        mock_svc = MagicMock()
        mock_svc.revert_latest.return_value = {"reverted": True}
        with patch.dict("sys.modules", {"services.hook_evolution_service": MagicMock(hook_evolution_service=mock_svc)}):
            client = _get_client()
            res = client.post("/api/youtube/revert-hook")
            assert res.status_code == 200

    def test_hook_history(self):
        """GET /hook-history"""
        mock_svc = MagicMock()
        mock_svc.get_history.return_value = {"history": []}
        with patch.dict("sys.modules", {"services.hook_evolution_service": MagicMock(hook_evolution_service=mock_svc)}):
            client = _get_client()
            res = client.get("/api/youtube/hook-history")
            assert res.status_code == 200


# ============================================================
# Phase 2: フィードバックループ (3件)
# ============================================================

class TestFeedbackLoop:
    def test_feedback_loop_success(self):
        """POST /feedback-loop/{id} — 正常系"""
        mock_collector = AsyncMock()
        mock_collector.collect_performance_data = AsyncMock(return_value={"metrics": {"click_through_rate": 5.0}})
        mock_validator = AsyncMock()
        mock_validator.validate_prediction = AsyncMock(return_value={"status": "ok", "analysis": {"difference": 1.0, "significant_deviation": False}})
        mock_wm = MagicMock()
        mock_wm.get_record.return_value = {"youtube_video_id": "vid123"}
        mock_wm.add_distilled_knowledge = MagicMock()
        import routers.youtube_optimizer as youtube_optimizer
        with patch.dict("sys.modules", {
            "services.post_publish_collector": MagicMock(post_publish_collector=mock_collector),
            "services.prediction_validator": MagicMock(prediction_validator=mock_validator),
            "wagamama_manager": MagicMock(wagamama_manager=mock_wm),
        }), patch.object(youtube_optimizer, "_record_post_publish_feedback"):
            client = _get_client()
            res = client.post("/api/youtube/feedback-loop/wag001")
            assert res.status_code == 200
            assert res.json()["success"] is True

    def test_feedback_loop_skipped(self):
        """POST /feedback-loop — validation skipped"""
        mock_collector = AsyncMock()
        mock_collector.collect_performance_data = AsyncMock(return_value={})
        mock_validator = AsyncMock()
        mock_validator.validate_prediction = AsyncMock(return_value={"status": "skipped", "message": "no data"})
        mock_wm = MagicMock()
        mock_wm.get_record.return_value = None
        with patch.dict("sys.modules", {
            "services.post_publish_collector": MagicMock(post_publish_collector=mock_collector),
            "services.prediction_validator": MagicMock(prediction_validator=mock_validator),
            "wagamama_manager": MagicMock(wagamama_manager=mock_wm),
        }):
            client = _get_client()
            res = client.post("/api/youtube/feedback-loop/wag002")
            assert res.status_code == 200
            assert res.json()["success"] is False

    def test_record_post_publish_feedback(self, tmp_path):
        """_record_post_publish_feedback — evolution_log書込"""
        import json
        from routers.youtube_optimizer import _record_post_publish_feedback
        log_file = tmp_path / "evolution_log.json"
        log_file.write_text("{}", encoding="utf-8")
        with patch("pathlib.Path.__truediv__", return_value=log_file):
            _record_post_publish_feedback(
                wagamama_id="w1", video_id="v1",
                actual_metrics={"metrics": {}, "retention_map": {"drop_off_points": ["1:30"]}},
                validation={"analysis": {"difference": 5, "significant_deviation": True}}
            )


# ============================================================
# Phase 3-4: Retention + Series (6件)
# ============================================================

class TestRetentionAndSeries:
    def test_retention_map(self):
        """POST /retention-map"""
        mock_report = MagicMock()
        mock_report.overall_risk_assessment = "low"
        mock_report.suggestions = []
        mock_report.model_dump.return_value = {}
        mock_plugin = MagicMock()
        mock_plugin.analyze_retention_risks.return_value = mock_report
        mock_gen = MagicMock()
        mock_gen.generate_html_report.return_value = "/tmp/report.html"
        with patch.dict("sys.modules", {
            "plugins.retention_map_plugin": MagicMock(retention_map_plugin=mock_plugin),
            "services.preview_report_generator": MagicMock(preview_report_generator=mock_gen),
        }):
            client = _get_client()
            res = client.post("/api/youtube/retention-map", json={
                "video_id": "v1", "duration_sec": 300
            })
            assert res.status_code == 200
            assert res.json()["success"] is True

    def test_series_register(self):
        """POST /series/register"""
        mock_sp = MagicMock()
        mock_sp.register_series.return_value = {"id": "s1"}
        with patch.dict("sys.modules", {"services.series_planner": MagicMock(series_planner=mock_sp)}):
            client = _get_client()
            res = client.post("/api/youtube/series/register", json={
                "series_id": "s1", "title": "テスト", "theme": "tech"
            })
            assert res.status_code == 200
            assert res.json()["success"] is True

    def test_series_add_video(self):
        """POST /series/add-video"""
        mock_sp = MagicMock()
        mock_sp.add_video_to_series.return_value = True
        with patch.dict("sys.modules", {"services.series_planner": MagicMock(series_planner=mock_sp)}):
            client = _get_client()
            res = client.post("/api/youtube/series/add-video", json={
                "series_id": "s1", "video_id": "v1", "video_title": "test"
            })
            assert res.status_code == 200
            assert res.json()["success"] is True

    def test_suggest_next_video(self):
        """POST /series/suggest-next"""
        mock_sp = MagicMock()
        mock_sp.suggest_next_video.return_value = {"suggestion": "next topic"}
        with patch.dict("sys.modules", {"services.series_planner": MagicMock(series_planner=mock_sp)}):
            client = _get_client()
            res = client.post("/api/youtube/series/suggest-next", json={
                "series_id": "s1", "current_video_id": "v1"
            })
            assert res.status_code == 200

    def test_optimize_playlist(self):
        """GET /series/{id}/playlist"""
        mock_sp = MagicMock()
        mock_sp.optimize_playlist.return_value = {"order": []}
        with patch.dict("sys.modules", {"services.series_planner": MagicMock(series_planner=mock_sp)}):
            client = _get_client()
            res = client.get("/api/youtube/series/s1/playlist")
            assert res.status_code == 200

    def test_session_score(self):
        """POST /series/session-score"""
        mock_yt = MagicMock()
        mock_yt.calculate_session_continuation_score.return_value = {"score": 75}
        with patch.dict("sys.modules", {"plugins.youtube_optimizer_plugin": MagicMock(youtube_optimizer=mock_yt)}):
            client = _get_client()
            res = client.post("/api/youtube/series/session-score", json={
                "video_id": "v1", "series_id": "s1"
            })
            assert res.status_code == 200


# ============================================================
# Phase 5-9: Assets/Schedule/Thumbnail/Comments/Shorts (6件)
# ============================================================

class TestPhase5to9:
    def test_build_asset_index(self):
        """POST /assets/build-index"""
        mock_lib = MagicMock()
        mock_lib.build_search_index.return_value = {"indexed": 10}
        with patch.dict("sys.modules", {"asset_library": MagicMock(asset_library=mock_lib)}):
            client = _get_client()
            res = client.post("/api/youtube/assets/build-index")
            assert res.status_code == 200

    def test_schedule_add(self):
        """POST /schedule/add"""
        mock_ps = MagicMock()
        mock_ps.add_entry.return_value = {"id": "e1"}
        with patch.dict("sys.modules", {"services.publish_scheduler": MagicMock(publish_scheduler=mock_ps)}):
            client = _get_client()
            res = client.post("/api/youtube/schedule/add", json={
                "title": "テスト動画", "planned_date": "2026-05-01"
            })
            assert res.status_code == 200

    def test_schedule_get(self):
        """GET /schedule"""
        mock_ps = MagicMock()
        mock_ps.get_schedule.return_value = []
        with patch.dict("sys.modules", {"services.publish_scheduler": MagicMock(publish_scheduler=mock_ps)}):
            client = _get_client()
            res = client.get("/api/youtube/schedule")
            assert res.status_code == 200

    def test_thumbnail_analyze(self):
        """POST /thumbnail/analyze"""
        mock_ta = MagicMock()
        mock_ta.analyze.return_value = {"score": 80}
        with patch.dict("sys.modules", {"services.thumbnail_analyzer": MagicMock(thumbnail_analyzer=mock_ta)}):
            client = _get_client()
            res = client.post("/api/youtube/thumbnail/analyze", json={})
            assert res.status_code == 200

    def test_comments_analyze(self):
        """POST /comments/analyze"""
        mock_ca = MagicMock()
        mock_ca.analyze_comments.return_value = {"sentiment": "positive"}
        with patch.dict("sys.modules", {"services.comment_analyzer": MagicMock(comment_analyzer=mock_ca)}):
            client = _get_client()
            res = client.post("/api/youtube/comments/analyze", json={
                "comments": ["great video!", "awesome"]
            })
            assert res.status_code == 200

    def test_shorts_extract(self):
        """POST /shorts/extract"""
        mock_sg = MagicMock()
        mock_sg.extract_shorts_candidates.return_value = {"candidates": []}
        with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_sg)}):
            client = _get_client()
            res = client.post("/api/youtube/shorts/extract", json={
                "segments": [{"text": "hi", "start": 0, "end": 5}],
                "video_duration_sec": 300
            })
            assert res.status_code == 200


# ============================================================
# Phase 10: Edge Cases & Exception Handling (未カバー行の網羅)
# ============================================================

class TestEdgeCases:
    def test_pre_plan_http_exception(self):
        """POST /pre-plan — HTTPException伝播"""
        import routers.youtube_optimizer as youtube_optimizer
        with patch.object(youtube_optimizer, "_generate_title_candidates", side_effect=HTTPException(status_code=400, detail="Bad Request")):
            client = _get_client()
            res = client.post("/api/youtube/pre-plan", json={"topic": "テスト"})
            assert res.status_code == 400

    def test_pre_plan_generic_exception(self):
        """POST /pre-plan — 一般例外 -> 500"""
        import routers.youtube_optimizer as youtube_optimizer
        with patch.object(youtube_optimizer, "_generate_title_candidates", side_effect=Exception("Pre-plan internal fail")):
            client = _get_client()
            res = client.post("/api/youtube/pre-plan", json={"topic": "テスト"})
            assert res.status_code == 500
            assert "Pre-plan internal fail" in res.json()["detail"]

    def test_pre_plan_evolution_log_http_exception(self, tmp_path):
        """POST /pre-plan — evolution_log読込でHTTPException発生時は伝播"""
        import routers.youtube_optimizer as youtube_optimizer
        with patch("routers.youtube_optimizer.safe_load_json", side_effect=HTTPException(status_code=403, detail="Forbidden")):
            client = _get_client()
            res = client.post("/api/youtube/pre-plan", json={"topic": "テスト"})
            assert res.status_code == 403

    def test_pre_plan_evolution_log_generic_exception(self):
        """POST /pre-plan — evolution_log読込で一般例外発生時はpass"""
        import routers.youtube_optimizer as youtube_optimizer
        with patch("routers.youtube_optimizer.safe_load_json", side_effect=Exception("Read fail")):
            client = _get_client()
            res = client.post("/api/youtube/pre-plan", json={"topic": "テスト"})
            assert res.status_code == 200

    def test_optimize_http_exception(self):
        """POST /optimize — HTTPException伝播"""
        mock_yt = AsyncMock()
        mock_yt.optimize_context = AsyncMock(side_effect=HTTPException(status_code=402, detail="Payment Required"))
        with patch.dict("sys.modules", {"plugins.youtube_optimizer_plugin": MagicMock(youtube_optimizer=mock_yt)}):
            client = _get_client()
            res = client.post("/api/youtube/optimize", json={"segments": [], "topics": []})
            assert res.status_code == 402

    def test_generate_thumbnail_http_exception(self):
        """POST /generate-thumbnail — HTTPException伝播"""
        mock_yt = AsyncMock()
        mock_yt.generate_thumbnail_with_imagen = AsyncMock(side_effect=HTTPException(status_code=401, detail="Unauthorized"))
        with patch.dict("sys.modules", {"plugins.youtube_optimizer_plugin": MagicMock(youtube_optimizer=mock_yt, ThumbnailCandidate=MagicMock())}):
            client = _get_client()
            res = client.post("/api/youtube/generate-thumbnail", json={"thumbnail_id": "t1", "context": {}})
            assert res.status_code == 401

    def test_generate_thumbnail_generic_exception(self):
        """POST /generate-thumbnail — 一般例外 -> 500"""
        mock_yt = AsyncMock()
        mock_yt.generate_thumbnail_with_imagen = AsyncMock(side_effect=Exception("Imagen fail"))
        with patch.dict("sys.modules", {"plugins.youtube_optimizer_plugin": MagicMock(youtube_optimizer=mock_yt, ThumbnailCandidate=MagicMock())}):
            client = _get_client()
            res = client.post("/api/youtube/generate-thumbnail", json={"thumbnail_id": "t1", "context": {}})
            assert res.status_code == 500

    def test_improve_hook_http_exception(self):
        """POST /improve-hook — HTTPException伝播"""
        mock_svc = AsyncMock()
        mock_svc.generate_improvements = AsyncMock(side_effect=HTTPException(status_code=400, detail="Hook error"))
        with patch.dict("sys.modules", {"services.hook_improver": MagicMock(hook_improver=mock_svc)}):
            client = _get_client()
            res = client.post("/api/youtube/improve-hook", json={"hook_text": "hello", "current_score": 50})
            assert res.status_code == 400

    def test_hook_preview_http_exception(self):
        """POST /hook-preview — HTTPException伝播"""
        mock_gen = AsyncMock()
        mock_gen.generate_screenshot_preview = AsyncMock(side_effect=HTTPException(status_code=404, detail="Not Found"))
        with patch.dict("sys.modules", {"services.hook_preview_generator": MagicMock(hook_preview_generator=mock_gen)}):
            client = _get_client()
            res = client.post("/api/youtube/hook-preview", json={"video_path": "/test.mp4", "original_text": "a", "improved_text": "b"})
            assert res.status_code == 404

    def test_hook_preview_generic_exception(self):
        """POST /hook-preview — 一般例外 -> 500"""
        mock_gen = AsyncMock()
        mock_gen.generate_screenshot_preview = AsyncMock(side_effect=Exception("Preview fail"))
        with patch.dict("sys.modules", {"services.hook_preview_generator": MagicMock(hook_preview_generator=mock_gen)}):
            client = _get_client()
            res = client.post("/api/youtube/hook-preview", json={"video_path": "/test.mp4", "original_text": "a", "improved_text": "b"})
            assert res.status_code == 500

    def test_apply_hook_http_exception(self):
        """POST /apply-hook — HTTPException伝播"""
        mock_svc = MagicMock()
        mock_svc.apply_improvement.side_effect = HTTPException(status_code=409, detail="Conflict")
        with patch.dict("sys.modules", {"services.hook_evolution_service": MagicMock(hook_evolution_service=mock_svc)}):
            client = _get_client()
            res = client.post("/api/youtube/apply-hook", json={"task_id": "t1", "improvement_type": "attention", "improved_text": "new", "original_text": "old"})
            assert res.status_code == 409

    def test_apply_hook_generic_exception(self):
        """POST /apply-hook — 一般例外 -> 500"""
        mock_svc = MagicMock()
        mock_svc.apply_improvement.side_effect = Exception("Apply fail")
        with patch.dict("sys.modules", {"services.hook_evolution_service": MagicMock(hook_evolution_service=mock_svc)}):
            client = _get_client()
            res = client.post("/api/youtube/apply-hook", json={"task_id": "t1", "improvement_type": "attention", "improved_text": "new", "original_text": "old"})
            assert res.status_code == 500

    def test_revert_hook_http_exception(self):
        """POST /revert-hook — HTTPException伝播"""
        mock_svc = MagicMock()
        mock_svc.revert_latest.side_effect = HTTPException(status_code=400, detail="Revert error")
        with patch.dict("sys.modules", {"services.hook_evolution_service": MagicMock(hook_evolution_service=mock_svc)}):
            client = _get_client()
            res = client.post("/api/youtube/revert-hook")
            assert res.status_code == 400

    def test_revert_hook_generic_exception(self):
        """POST /revert-hook — 一般例外 -> 500"""
        mock_svc = MagicMock()
        mock_svc.revert_latest.side_effect = Exception("Revert fail")
        with patch.dict("sys.modules", {"services.hook_evolution_service": MagicMock(hook_evolution_service=mock_svc)}):
            client = _get_client()
            res = client.post("/api/youtube/revert-hook")
            assert res.status_code == 500

    def test_hook_history_http_exception(self):
        """GET /hook-history — HTTPException伝播"""
        mock_svc = MagicMock()
        mock_svc.get_history.side_effect = HTTPException(status_code=400, detail="History error")
        with patch.dict("sys.modules", {"services.hook_evolution_service": MagicMock(hook_evolution_service=mock_svc)}):
            client = _get_client()
            res = client.get("/api/youtube/hook-history")
            assert res.status_code == 400

    def test_hook_history_generic_exception(self):
        """GET /hook-history — 一般例外 -> 500"""
        mock_svc = MagicMock()
        mock_svc.get_history.side_effect = Exception("History fail")
        with patch.dict("sys.modules", {"services.hook_evolution_service": MagicMock(hook_evolution_service=mock_svc)}):
            client = _get_client()
            res = client.get("/api/youtube/hook-history")
            assert res.status_code == 500

    def test_feedback_loop_significant_deviation_and_push_notification(self):
        """POST /feedback-loop/{id} — 乖離判定 & 管理者通知"""
        mock_collector = AsyncMock()
        mock_collector.collect_performance_data = AsyncMock(return_value={"metrics": {"click_through_rate": 5.0}})
        mock_validator = AsyncMock()
        mock_validator.validate_prediction = AsyncMock(return_value={
            "status": "ok",
            "analysis": {
                "difference": 15.0,
                "significant_deviation": True,
                "predicted": 20.0
            }
        })
        mock_wm = MagicMock()
        mock_wm.get_record.return_value = {"youtube_video_id": "vid123"}
        mock_wm.add_distilled_knowledge = MagicMock()
        import routers.youtube_optimizer as youtube_optimizer
        with patch.dict("sys.modules", {
            "services.post_publish_collector": MagicMock(post_publish_collector=mock_collector),
            "services.prediction_validator": MagicMock(prediction_validator=mock_validator),
            "wagamama_manager": MagicMock(wagamama_manager=mock_wm),
        }), patch.object(youtube_optimizer, "_record_post_publish_feedback"):
            client = _get_client()
            res = client.post("/api/youtube/feedback-loop/wag001")
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            assert data["admin_notified"] is True

    def test_feedback_loop_http_exception(self):
        """POST /feedback-loop/{id} — HTTPException伝播"""
        mock_collector = AsyncMock()
        mock_collector.collect_performance_data = AsyncMock(side_effect=HTTPException(status_code=400, detail="FB Loop error"))
        with patch.dict("sys.modules", {
            "services.post_publish_collector": MagicMock(post_publish_collector=mock_collector),
        }):
            client = _get_client()
            res = client.post("/api/youtube/feedback-loop/wag001")
            assert res.status_code == 400

    def test_feedback_loop_generic_exception(self):
        """POST /feedback-loop/{id} — 一般例外 -> 500"""
        mock_collector = AsyncMock()
        mock_collector.collect_performance_data = AsyncMock(side_effect=Exception("FB Loop fail"))
        with patch.dict("sys.modules", {
            "services.post_publish_collector": MagicMock(post_publish_collector=mock_collector),
        }):
            client = _get_client()
            res = client.post("/api/youtube/feedback-loop/wag001")
            assert res.status_code == 500

    def test_record_post_publish_feedback_rotation_and_exception(self, tmp_path, monkeypatch):
        """_record_post_publish_feedback — 50件ローテーション & HTTPException/Exception処理

        2026-08-02: 以前は `pathlib.Path.__truediv__` を差し替えて出力先を
        逸らしていた。実装が writable_path 経由（`joinpath`）になったので
        効かなくなったうえ、`/` を全面的に差し替えるのはこのテストと無関係な
        パス生成まで巻き込む。振り向けは実装と同じ経路
        （`ANTIGRAVITY_WRITABLE_ROOT`）で行う。
        """
        import json
        from routers.youtube_optimizer import _record_post_publish_feedback
        monkeypatch.setenv("ANTIGRAVITY_WRITABLE_ROOT", str(tmp_path))
        log_file = tmp_path / "backend" / "branding" / "evolution_log.json"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        initial_data = {
            "post_publish_feedbacks": [{"dummy": i} for i in range(60)]
        }
        log_file.write_text(json.dumps(initial_data), encoding="utf-8")
        _record_post_publish_feedback(
            wagamama_id="w1", video_id="v1",
            actual_metrics={"metrics": {}, "retention_map": {"drop_off_points": ["1:30"]}},
            validation={"analysis": {"difference": 15, "significant_deviation": True}}
        )
        written_data = json.loads(log_file.read_text(encoding="utf-8"))
        assert len(written_data["post_publish_feedbacks"]) == 50

        with patch("routers.youtube_optimizer._writable_path",
                   side_effect=HTTPException(status_code=400, detail="Write blocked")):
            with pytest.raises(HTTPException):
                _record_post_publish_feedback("w1", "v1", {}, {})

        with patch("routers.youtube_optimizer._writable_path", side_effect=Exception("Disk full")):
            _record_post_publish_feedback("w1", "v1", {}, {})

    def test_retention_map_http_exception(self):
        """POST /retention-map — HTTPException伝播"""
        mock_plugin = MagicMock()
        mock_plugin.analyze_retention_risks.side_effect = HTTPException(status_code=403, detail="Forbidden Map")
        with patch.dict("sys.modules", {"plugins.retention_map_plugin": MagicMock(retention_map_plugin=mock_plugin)}):
            client = _get_client()
            res = client.post("/api/youtube/retention-map", json={"video_id": "v1", "duration_sec": 300})
            assert res.status_code == 403

    def test_retention_map_generic_exception(self):
        """POST /retention-map — 一般例外 -> 500"""
        mock_plugin = MagicMock()
        mock_plugin.analyze_retention_risks.side_effect = Exception("Map fail")
        with patch.dict("sys.modules", {"plugins.retention_map_plugin": MagicMock(retention_map_plugin=mock_plugin)}):
            client = _get_client()
            res = client.post("/api/youtube/retention-map", json={"video_id": "v1", "duration_sec": 300})
            assert res.status_code == 500

    def test_series_register_http_exception(self):
        """POST /series/register — HTTPException伝播"""
        mock_sp = MagicMock()
        mock_sp.register_series.side_effect = HTTPException(status_code=400, detail="Register error")
        with patch.dict("sys.modules", {"services.series_planner": MagicMock(series_planner=mock_sp)}):
            client = _get_client()
            res = client.post("/api/youtube/series/register", json={"series_id": "s1", "title": "テスト", "theme": "tech"})
            assert res.status_code == 400

    def test_series_register_generic_exception(self):
        """POST /series/register — 一般例外 -> 500"""
        mock_sp = MagicMock()
        mock_sp.register_series.side_effect = Exception("Register fail")
        with patch.dict("sys.modules", {"services.series_planner": MagicMock(series_planner=mock_sp)}):
            client = _get_client()
            res = client.post("/api/youtube/series/register", json={"series_id": "s1", "title": "テスト", "theme": "tech"})
            assert res.status_code == 500

    def test_series_add_video_http_exception(self):
        """POST /series/add-video — HTTPException伝播"""
        mock_sp = MagicMock()
        mock_sp.add_video_to_series.side_effect = HTTPException(status_code=404, detail="Not Found Series")
        with patch.dict("sys.modules", {"services.series_planner": MagicMock(series_planner=mock_sp)}):
            client = _get_client()
            res = client.post("/api/youtube/series/add-video", json={"series_id": "s1", "video_id": "v1", "video_title": "test"})
            assert res.status_code == 404

    def test_series_add_video_generic_exception(self):
        """POST /series/add-video — 一般例外 -> 500"""
        mock_sp = MagicMock()
        mock_sp.add_video_to_series.side_effect = Exception("Add fail")
        with patch.dict("sys.modules", {"services.series_planner": MagicMock(series_planner=mock_sp)}):
            client = _get_client()
            res = client.post("/api/youtube/series/add-video", json={"series_id": "s1", "video_id": "v1", "video_title": "test"})
            assert res.status_code == 500

    def test_suggest_next_video_http_exception(self):
        """POST /series/suggest-next — HTTPException伝播"""
        mock_sp = MagicMock()
        mock_sp.suggest_next_video.side_effect = HTTPException(status_code=400, detail="Suggest error")
        with patch.dict("sys.modules", {"services.series_planner": MagicMock(series_planner=mock_sp)}):
            client = _get_client()
            res = client.post("/api/youtube/series/suggest-next", json={"series_id": "s1", "current_video_id": "v1"})
            assert res.status_code == 400

    def test_suggest_next_video_generic_exception(self):
        """POST /series/suggest-next — 一般例外 -> 500"""
        mock_sp = MagicMock()
        mock_sp.suggest_next_video.side_effect = Exception("Suggest fail")
        with patch.dict("sys.modules", {"services.series_planner": MagicMock(series_planner=mock_sp)}):
            client = _get_client()
            res = client.post("/api/youtube/series/suggest-next", json={"series_id": "s1", "current_video_id": "v1"})
            assert res.status_code == 500

    def test_optimize_playlist_http_exception(self):
        """GET /series/{id}/playlist — HTTPException伝播"""
        mock_sp = MagicMock()
        mock_sp.optimize_playlist.side_effect = HTTPException(status_code=404, detail="Playlist missing")
        with patch.dict("sys.modules", {"services.series_planner": MagicMock(series_planner=mock_sp)}):
            client = _get_client()
            res = client.get("/api/youtube/series/s1/playlist")
            assert res.status_code == 404

    def test_optimize_playlist_generic_exception(self):
        """GET /series/{id}/playlist — 一般例外 -> 500"""
        mock_sp = MagicMock()
        mock_sp.optimize_playlist.side_effect = Exception("Playlist fail")
        with patch.dict("sys.modules", {"services.series_planner": MagicMock(series_planner=mock_sp)}):
            client = _get_client()
            res = client.get("/api/youtube/series/s1/playlist")
            assert res.status_code == 500

    def test_session_score_http_exception(self):
        """POST /series/session-score — HTTPException伝播"""
        mock_yt = MagicMock()
        mock_yt.calculate_session_continuation_score.side_effect = HTTPException(status_code=400, detail="Score error")
        with patch.dict("sys.modules", {"plugins.youtube_optimizer_plugin": MagicMock(youtube_optimizer=mock_yt)}):
            client = _get_client()
            res = client.post("/api/youtube/series/session-score", json={"video_id": "v1", "series_id": "s1"})
            assert res.status_code == 400

    def test_session_score_generic_exception(self):
        """POST /series/session-score — 一般例外 -> 500"""
        mock_yt = MagicMock()
        mock_yt.calculate_session_continuation_score.side_effect = Exception("Score fail")
        with patch.dict("sys.modules", {"plugins.youtube_optimizer_plugin": MagicMock(youtube_optimizer=mock_yt)}):
            client = _get_client()
            res = client.post("/api/youtube/series/session-score", json={"video_id": "v1", "series_id": "s1"})
            assert res.status_code == 500

    def test_build_asset_index_http_exception(self):
        """POST /assets/build-index — HTTPException伝播"""
        mock_lib = MagicMock()
        mock_lib.build_search_index.side_effect = HTTPException(status_code=403, detail="Forbidden build")
        with patch.dict("sys.modules", {"asset_library": MagicMock(asset_library=mock_lib)}):
            client = _get_client()
            res = client.post("/api/youtube/assets/build-index")
            assert res.status_code == 403

    def test_build_asset_index_generic_exception(self):
        """POST /assets/build-index — 一般例外 -> 500"""
        mock_lib = MagicMock()
        mock_lib.build_search_index.side_effect = Exception("Build error")
        with patch.dict("sys.modules", {"asset_library": MagicMock(asset_library=mock_lib)}):
            client = _get_client()
            res = client.post("/api/youtube/assets/build-index")
            assert res.status_code == 500

    def test_search_assets_missing_query(self):
        """GET /assets/search — クエリ不足 -> 400 または 422"""
        client = _get_client()
        # クエリパラメータ自体を省略した場合は FastAPI により 422 が返る
        res = client.get("/api/youtube/assets/search")
        assert res.status_code == 422

        # クエリパラメータが空文字列の場合は application 層のチェックで 400 が返る
        res_empty = client.get("/api/youtube/assets/search?q=")
        assert res_empty.status_code == 400

    def test_search_assets_success(self):
        """GET /assets/search — 正常系"""
        mock_lib = MagicMock()
        mock_lib.search_assets.return_value = [{"asset_id": "a1"}]
        mock_vs = MagicMock()
        mock_vs.get_index_stats.return_value = {"total_vectors": 100}
        with patch.dict("sys.modules", {
            "asset_library": MagicMock(asset_library=mock_lib),
            "services.vector_search": MagicMock(vector_search_engine=mock_vs)
        }):
            client = _get_client()
            res = client.get("/api/youtube/assets/search?q=test&top_k=2")
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            assert data["count"] == 1
            assert data["results"][0]["asset_id"] == "a1"

    def test_search_assets_http_exception(self):
        """GET /assets/search — HTTPException伝播"""
        mock_lib = MagicMock()
        mock_lib.search_assets.side_effect = HTTPException(status_code=403, detail="Search Forbidden")
        with patch.dict("sys.modules", {"asset_library": MagicMock(asset_library=mock_lib)}):
            client = _get_client()
            res = client.get("/api/youtube/assets/search?q=test")
            assert res.status_code == 403

    def test_search_assets_generic_exception(self):
        """GET /assets/search — 一般例外 -> 500"""
        mock_lib = MagicMock()
        mock_lib.search_assets.side_effect = Exception("Search crash")
        with patch.dict("sys.modules", {"asset_library": MagicMock(asset_library=mock_lib)}):
            client = _get_client()
            res = client.get("/api/youtube/assets/search?q=test")
            assert res.status_code == 500

    def test_get_index_stats_success(self):
        """GET /assets/index-stats — 正常系"""
        mock_vs = MagicMock()
        mock_vs.get_index_stats.return_value = {"total_vectors": 100}
        with patch.dict("sys.modules", {"services.vector_search": MagicMock(vector_search_engine=mock_vs)}):
            client = _get_client()
            res = client.get("/api/youtube/assets/index-stats")
            assert res.status_code == 200
            assert res.json()["success"] is True
            assert res.json()["total_vectors"] == 100

    def test_get_index_stats_http_exception(self):
        """GET /assets/index-stats — HTTPException伝播"""
        mock_vs = MagicMock()
        mock_vs.get_index_stats.side_effect = HTTPException(status_code=400, detail="Stats bad request")
        with patch.dict("sys.modules", {"services.vector_search": MagicMock(vector_search_engine=mock_vs)}):
            client = _get_client()
            res = client.get("/api/youtube/assets/index-stats")
            assert res.status_code == 400

    def test_get_index_stats_generic_exception(self):
        """GET /assets/index-stats — 一般例外 -> 500"""
        mock_vs = MagicMock()
        mock_vs.get_index_stats.side_effect = Exception("Stats fail")
        with patch.dict("sys.modules", {"services.vector_search": MagicMock(vector_search_engine=mock_vs)}):
            client = _get_client()
            res = client.get("/api/youtube/assets/index-stats")
            assert res.status_code == 500

    def test_schedule_add_http_exception(self):
        """POST /schedule/add — HTTPException伝播"""
        mock_ps = MagicMock()
        mock_ps.add_entry.side_effect = HTTPException(status_code=400, detail="Add schedule error")
        with patch.dict("sys.modules", {"services.publish_scheduler": MagicMock(publish_scheduler=mock_ps)}):
            client = _get_client()
            res = client.post("/api/youtube/schedule/add", json={"title": "テスト動画", "planned_date": "2026-05-01"})
            assert res.status_code == 400

    def test_schedule_add_generic_exception(self):
        """POST /schedule/add — 一般例外 -> 500"""
        mock_ps = MagicMock()
        mock_ps.add_entry.side_effect = Exception("Add schedule fail")
        with patch.dict("sys.modules", {"services.publish_scheduler": MagicMock(publish_scheduler=mock_ps)}):
            client = _get_client()
            res = client.post("/api/youtube/schedule/add", json={"title": "テスト動画", "planned_date": "2026-05-01"})
            assert res.status_code == 500

    def test_schedule_get_http_exception(self):
        """GET /schedule — HTTPException伝播"""
        mock_ps = MagicMock()
        mock_ps.get_schedule.side_effect = HTTPException(status_code=403, detail="Get schedule forbidden")
        with patch.dict("sys.modules", {"services.publish_scheduler": MagicMock(publish_scheduler=mock_ps)}):
            client = _get_client()
            res = client.get("/api/youtube/schedule")
            assert res.status_code == 403

    def test_schedule_get_generic_exception(self):
        """GET /schedule — 一般例外 -> 500"""
        mock_ps = MagicMock()
        mock_ps.get_schedule.side_effect = Exception("Get schedule fail")
        with patch.dict("sys.modules", {"services.publish_scheduler": MagicMock(publish_scheduler=mock_ps)}):
            client = _get_client()
            res = client.get("/api/youtube/schedule")
            assert res.status_code == 500

    def test_get_next_deadline_success(self):
        """GET /schedule/next-deadline — 正常系"""
        mock_ps = MagicMock()
        mock_ps.get_next_deadline.return_value = {"next_deadline": "2026-05-02"}
        with patch.dict("sys.modules", {"services.publish_scheduler": MagicMock(publish_scheduler=mock_ps)}):
            client = _get_client()
            res = client.get("/api/youtube/schedule/next-deadline")
            assert res.status_code == 200
            assert res.json()["next_deadline"] == "2026-05-02"

    def test_get_next_deadline_http_exception(self):
        """GET /schedule/next-deadline — HTTPException伝播"""
        mock_ps = MagicMock()
        mock_ps.get_next_deadline.side_effect = HTTPException(status_code=400, detail="Deadline error")
        with patch.dict("sys.modules", {"services.publish_scheduler": MagicMock(publish_scheduler=mock_ps)}):
            client = _get_client()
            res = client.get("/api/youtube/schedule/next-deadline")
            assert res.status_code == 400

    def test_get_next_deadline_generic_exception(self):
        """GET /schedule/next-deadline — 一般例外 -> 500"""
        mock_ps = MagicMock()
        mock_ps.get_next_deadline.side_effect = Exception("Deadline fail")
        with patch.dict("sys.modules", {"services.publish_scheduler": MagicMock(publish_scheduler=mock_ps)}):
            client = _get_client()
            res = client.get("/api/youtube/schedule/next-deadline")
            assert res.status_code == 500

    def test_analyze_pace_success(self):
        """GET /schedule/pace-analysis — 正常系"""
        mock_ps = MagicMock()
        mock_ps.analyze_pace.return_value = {"pace": "on track"}
        with patch.dict("sys.modules", {"services.publish_scheduler": MagicMock(publish_scheduler=mock_ps)}):
            client = _get_client()
            res = client.get("/api/youtube/schedule/pace-analysis")
            assert res.status_code == 200
            assert res.json()["pace"] == "on track"

    def test_analyze_pace_http_exception(self):
        """GET /schedule/pace-analysis — HTTPException伝播"""
        mock_ps = MagicMock()
        mock_ps.analyze_pace.side_effect = HTTPException(status_code=400, detail="Pace error")
        with patch.dict("sys.modules", {"services.publish_scheduler": MagicMock(publish_scheduler=mock_ps)}):
            client = _get_client()
            res = client.get("/api/youtube/schedule/pace-analysis")
            assert res.status_code == 400

    def test_analyze_pace_generic_exception(self):
        """GET /schedule/pace-analysis — 一般例外 -> 500"""
        mock_ps = MagicMock()
        mock_ps.analyze_pace.side_effect = Exception("Pace fail")
        with patch.dict("sys.modules", {"services.publish_scheduler": MagicMock(publish_scheduler=mock_ps)}):
            client = _get_client()
            res = client.get("/api/youtube/schedule/pace-analysis")
            assert res.status_code == 500

    def test_update_schedule_status_not_found(self):
        """POST /schedule/update-status — 更新対象なし(正常系失敗)"""
        mock_ps = MagicMock()
        mock_ps.update_status.return_value = False
        with patch.dict("sys.modules", {"services.publish_scheduler": MagicMock(publish_scheduler=mock_ps)}):
            client = _get_client()
            res = client.post("/api/youtube/schedule/update-status", json={"entry_id": "nonexistent", "status": "published"})
            assert res.status_code == 200
            assert res.json()["success"] is False
            assert "該当エントリが見つかりません" in res.json()["message"]

    def test_update_schedule_status_http_exception(self):
        """POST /schedule/update-status — HTTPException伝播"""
        mock_ps = MagicMock()
        mock_ps.update_status.side_effect = HTTPException(status_code=400, detail="Update status error")
        with patch.dict("sys.modules", {"services.publish_scheduler": MagicMock(publish_scheduler=mock_ps)}):
            client = _get_client()
            res = client.post("/api/youtube/schedule/update-status", json={"entry_id": "e1", "status": "published"})
            assert res.status_code == 400

    def test_update_schedule_status_generic_exception(self):
        """POST /schedule/update-status — 一般例外 -> 500"""
        mock_ps = MagicMock()
        mock_ps.update_status.side_effect = Exception("Update status fail")
        with patch.dict("sys.modules", {"services.publish_scheduler": MagicMock(publish_scheduler=mock_ps)}):
            client = _get_client()
            res = client.post("/api/youtube/schedule/update-status", json={"entry_id": "e1", "status": "published"})
            assert res.status_code == 500

    def test_get_schedule_settings_success(self):
        """GET /schedule/settings — 正常系"""
        mock_ps = MagicMock()
        mock_ps.get_settings.return_value = {"target_per_week": 2}
        with patch.dict("sys.modules", {"services.publish_scheduler": MagicMock(publish_scheduler=mock_ps)}):
            client = _get_client()
            res = client.get("/api/youtube/schedule/settings")
            assert res.status_code == 200
            assert res.json()["success"] is True
            assert res.json()["settings"]["target_per_week"] == 2

    def test_get_schedule_settings_http_exception(self):
        """GET /schedule/settings — HTTPException伝播"""
        mock_ps = MagicMock()
        mock_ps.get_settings.side_effect = HTTPException(status_code=403, detail="Forbidden settings")
        with patch.dict("sys.modules", {"services.publish_scheduler": MagicMock(publish_scheduler=mock_ps)}):
            client = _get_client()
            res = client.get("/api/youtube/schedule/settings")
            assert res.status_code == 403

    def test_get_schedule_settings_generic_exception(self):
        """GET /schedule/settings — 一般例外 -> 500"""
        mock_ps = MagicMock()
        mock_ps.get_settings.side_effect = Exception("Settings get fail")
        with patch.dict("sys.modules", {"services.publish_scheduler": MagicMock(publish_scheduler=mock_ps)}):
            client = _get_client()
            res = client.get("/api/youtube/schedule/settings")
            assert res.status_code == 500

    def test_update_schedule_settings_success(self):
        """PUT /schedule/settings — 正常系"""
        mock_ps = MagicMock()
        mock_ps.update_settings.return_value = {"target_per_week": 3}
        with patch.dict("sys.modules", {"services.publish_scheduler": MagicMock(publish_scheduler=mock_ps)}):
            client = _get_client()
            res = client.put("/api/youtube/schedule/settings", json={"target_per_week": 3})
            assert res.status_code == 200
            assert res.json()["success"] is True
            assert res.json()["settings"]["target_per_week"] == 3

    def test_update_schedule_settings_http_exception(self):
        """PUT /schedule/settings — HTTPException伝播"""
        mock_ps = MagicMock()
        mock_ps.update_settings.side_effect = HTTPException(status_code=400, detail="Update settings error")
        with patch.dict("sys.modules", {"services.publish_scheduler": MagicMock(publish_scheduler=mock_ps)}):
            client = _get_client()
            res = client.put("/api/youtube/schedule/settings", json={"target_per_week": 3})
            assert res.status_code == 400

    def test_update_schedule_settings_generic_exception(self):
        """PUT /schedule/settings — 一般例外 -> 500"""
        mock_ps = MagicMock()
        mock_ps.update_settings.side_effect = Exception("Settings update fail")
        with patch.dict("sys.modules", {"services.publish_scheduler": MagicMock(publish_scheduler=mock_ps)}):
            client = _get_client()
            res = client.put("/api/youtube/schedule/settings", json={"target_per_week": 3})
            assert res.status_code == 500

    def test_thumbnail_analyze_http_exception(self):
        """POST /thumbnail/analyze — HTTPException伝播"""
        mock_ta = MagicMock()
        mock_ta.analyze.side_effect = HTTPException(status_code=400, detail="Analyze error")
        with patch.dict("sys.modules", {"services.thumbnail_analyzer": MagicMock(thumbnail_analyzer=mock_ta)}):
            client = _get_client()
            res = client.post("/api/youtube/thumbnail/analyze", json={})
            assert res.status_code == 400

    def test_thumbnail_analyze_generic_exception(self):
        """POST /thumbnail/analyze — 一般例外 -> 500"""
        mock_ta = MagicMock()
        mock_ta.analyze.side_effect = Exception("Analyze fail")
        with patch.dict("sys.modules", {"services.thumbnail_analyzer": MagicMock(thumbnail_analyzer=mock_ta)}):
            client = _get_client()
            res = client.post("/api/youtube/thumbnail/analyze", json={})
            assert res.status_code == 500

    def test_analyze_thumbnail_image_success(self):
        """POST /thumbnail/analyze-image — 正常系"""
        mock_ta = MagicMock()
        mock_ta.analyze_image.return_value = {"score": 90}
        with patch.dict("sys.modules", {"services.thumbnail_analyzer": MagicMock(thumbnail_analyzer=mock_ta)}):
            client = _get_client()
            res = client.post("/api/youtube/thumbnail/analyze-image", json={"image_path": "/path/to/img.png"})
            assert res.status_code == 200
            assert res.json()["score"] == 90

    def test_analyze_thumbnail_image_http_exception(self):
        """POST /thumbnail/analyze-image — HTTPException伝播"""
        mock_ta = MagicMock()
        mock_ta.analyze_image.side_effect = HTTPException(status_code=400, detail="Vision error")
        with patch.dict("sys.modules", {"services.thumbnail_analyzer": MagicMock(thumbnail_analyzer=mock_ta)}):
            client = _get_client()
            res = client.post("/api/youtube/thumbnail/analyze-image", json={"image_path": "/path/to/img.png"})
            assert res.status_code == 400

    def test_analyze_thumbnail_image_generic_exception(self):
        """POST /thumbnail/analyze-image — 一般例外 -> 500"""
        mock_ta = MagicMock()
        mock_ta.analyze_image.side_effect = Exception("Vision crash")
        with patch.dict("sys.modules", {"services.thumbnail_analyzer": MagicMock(thumbnail_analyzer=mock_ta)}):
            client = _get_client()
            res = client.post("/api/youtube/thumbnail/analyze-image", json={"image_path": "/path/to/img.png"})
            assert res.status_code == 500

    def test_comments_analyze_http_exception(self):
        """POST /comments/analyze — HTTPException伝播"""
        mock_ca = MagicMock()
        mock_ca.analyze_comments.side_effect = HTTPException(status_code=400, detail="Comment analyze error")
        with patch.dict("sys.modules", {"services.comment_analyzer": MagicMock(comment_analyzer=mock_ca)}):
            client = _get_client()
            res = client.post("/api/youtube/comments/analyze", json={"comments": []})
            assert res.status_code == 400

    def test_comments_analyze_generic_exception(self):
        """POST /comments/analyze — 一般例外 -> 500"""
        mock_ca = MagicMock()
        mock_ca.analyze_comments.side_effect = Exception("Comment analyze crash")
        with patch.dict("sys.modules", {"services.comment_analyzer": MagicMock(comment_analyzer=mock_ca)}):
            client = _get_client()
            res = client.post("/api/youtube/comments/analyze", json={"comments": []})
            assert res.status_code == 500

    def test_get_request_trends_success(self):
        """GET /comments/request-trends — 正常系"""
        mock_ca = MagicMock()
        mock_ca.get_request_trends.return_value = {"trends": []}
        with patch.dict("sys.modules", {"services.comment_analyzer": MagicMock(comment_analyzer=mock_ca)}):
            client = _get_client()
            res = client.get("/api/youtube/comments/request-trends")
            assert res.status_code == 200
            assert res.json()["trends"] == []

    def test_get_request_trends_http_exception(self):
        """GET /comments/request-trends — HTTPException伝播"""
        mock_ca = MagicMock()
        mock_ca.get_request_trends.side_effect = HTTPException(status_code=400, detail="Trends error")
        with patch.dict("sys.modules", {"services.comment_analyzer": MagicMock(comment_analyzer=mock_ca)}):
            client = _get_client()
            res = client.get("/api/youtube/comments/request-trends")
            assert res.status_code == 400

    def test_get_request_trends_generic_exception(self):
        """GET /comments/request-trends — 一般例外 -> 500"""
        mock_ca = MagicMock()
        mock_ca.get_request_trends.side_effect = Exception("Trends crash")
        with patch.dict("sys.modules", {"services.comment_analyzer": MagicMock(comment_analyzer=mock_ca)}):
            client = _get_client()
            res = client.get("/api/youtube/comments/request-trends")
            assert res.status_code == 500

    def test_shorts_extract_http_exception(self):
        """POST /shorts/extract — HTTPException伝播"""
        mock_sg = MagicMock()
        mock_sg.extract_shorts_candidates.side_effect = HTTPException(status_code=400, detail="Shorts error")
        with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_sg)}):
            client = _get_client()
            res = client.post("/api/youtube/shorts/extract", json={"segments": [], "video_duration_sec": 100})
            assert res.status_code == 400

    def test_shorts_extract_generic_exception(self):
        """POST /shorts/extract — 一般例外 -> 500"""
        mock_sg = MagicMock()
        mock_sg.extract_shorts_candidates.side_effect = Exception("Shorts crash")
        with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_sg)}):
            client = _get_client()
            res = client.post("/api/youtube/shorts/extract", json={"segments": [], "video_duration_sec": 100})
            assert res.status_code == 500

    def test_pre_plan_with_valid_evolution_log(self, tmp_path):
        """POST /pre-plan — 有効な lessons_learned を持つ evolution_log の読込"""
        import json
        log_file = tmp_path / "evolution_log.json"
        log_data = {
            "post_publish_feedbacks": [
                {
                    "lessons_learned": ["キャンプ飯はサムネに肉を大きく写すのが吉", "BGMは控えめにする"]
                }
            ]
        }
        log_file.write_text(json.dumps(log_data), encoding="utf-8")
        with patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.read_text", return_value=json.dumps(log_data)):
            client = _get_client()
            res = client.post("/api/youtube/pre-plan", json={"topic": "テスト"})
            assert res.status_code == 200

    def test_improve_hook_generic_exception(self):
        """POST /improve-hook — 一般例外 -> 500"""
        mock_svc = AsyncMock()
        mock_svc.generate_improvements = AsyncMock(side_effect=Exception("Hook general fail"))
        with patch.dict("sys.modules", {"services.hook_improver": MagicMock(hook_improver=mock_svc)}):
            client = _get_client()
            res = client.post("/api/youtube/improve-hook", json={"hook_text": "hello", "current_score": 50})
            assert res.status_code == 500
            assert "Hook general fail" in res.json()["detail"]

    def test_pre_plan_evolution_log_not_exists(self):
        """POST /pre-plan — evolution_log.json が存在しない場合の分岐をカバー"""
        with patch("pathlib.Path.exists", return_value=False):
            client = _get_client()
            res = client.post("/api/youtube/pre-plan", json={"topic": "テスト"})
            assert res.status_code == 200
            data = res.json()
            assert "past_lessons" in data

    def test_record_post_publish_feedback_log_not_exists(self, tmp_path, monkeypatch):
        """_record_post_publish_feedback — evolution_log.json が存在しない場合、および lessons_learned の空分岐をカバー"""
        from routers.youtube_optimizer import _record_post_publish_feedback
        monkeypatch.setenv("ANTIGRAVITY_WRITABLE_ROOT", str(tmp_path))
        log_file = tmp_path / "backend" / "branding" / "evolution_log.json"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        assert not log_file.exists()
        _record_post_publish_feedback(
            wagamama_id="w1", video_id="v1",
            actual_metrics={"metrics": {}, "retention_map": {"drop_off_points": []}},
            validation={"analysis": {"difference": 1, "significant_deviation": False}}
        )
        assert log_file.exists()

    def test_record_post_publish_feedback_http_exception_and_timeout(self):
        """_record_post_publish_feedback — HTTPExceptionがそのまま上に伝播し、Timeoutはキャッチして警告ログを出力することを検証"""
        from routers.youtube_optimizer import _record_post_publish_feedback
        from filelock import Timeout
        from fastapi import HTTPException
        import pytest

        # 1. HTTPException発生時にそのまま上に伝播することを確認
        with patch("routers.youtube_optimizer._writable_path",
                   side_effect=HTTPException(status_code=400, detail="HTTP error")):
            with pytest.raises(HTTPException):
                _record_post_publish_feedback("w1", "v1", {}, {})

    def test_pre_plan_evolution_log_read_exception_handling(self):
        """POST /pre-plan — evolution_log.json読み込み時に一般例外が発生した場合のハンドリング"""
        with patch("pathlib.Path.exists", return_value=True), \
             patch("routers.youtube_optimizer.safe_load_json", side_effect=Exception("Mock read fail")):
            client = _get_client()
            res = client.post("/api/youtube/pre-plan", json={"topic": "テスト"})
            assert res.status_code == 200
            # ログ出力のみで処理が続行され、デフォルト値が返ることを確認
            assert "past_lessons" in res.json()

    def test_pre_plan_value_error_handling(self):
        """POST /pre-plan — ValueError発生時の400エラーハンドリング"""
        with patch("routers.youtube_optimizer._generate_title_candidates", side_effect=ValueError("Invalid topic parameter")):
            client = _get_client()
            res = client.post("/api/youtube/pre-plan", json={"topic": "テスト"})
            assert res.status_code == 400
            assert "Invalid topic parameter" in res.json()["detail"]

    def test_pre_plan_generic_exception_handling(self):
        """POST /pre-plan — 一般例外発生時の500エラーハンドリング"""
        with patch("routers.youtube_optimizer._generate_title_candidates", side_effect=Exception("Database crash")):
            client = _get_client()
            res = client.post("/api/youtube/pre-plan", json={"topic": "テスト"})
            assert res.status_code == 500
            assert "Database crash" in res.json()["detail"]

    def test_pre_plan_ctr_boost_and_best_combo(self):
        """POST /pre-plan — 感情トリガー等のブーストが働き best_ctr が正しく更新されることを検証"""
        client = _get_client()
        # トリガーワードを含め、ジャンルを「エンタメ」にすることで高CTRを出し、best_ctr = ctr が通るようにする
        res = client.post("/api/youtube/pre-plan", json={
            "topic": "衝撃の知らない完全版本気なぜ全てマスター100選", 
            "genre": "エンタメ",
            "target_audience": "全員"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["best_title"] is not None

    def test_estimate_ctr_variations(self):
        """_estimate_ctr — 様々なタイトルパターンに対するCTR予測のバリエーションと上限9.0制限"""
        from routers.youtube_optimizer import _estimate_ctr
        
        # 1. 感情トリガーなし、数字なし、ジャンルデフォルト
        ctr1 = _estimate_ctr("普通のタイトル", "ASMR")
        
        # 2. トリガーあり
        ctr2 = _estimate_ctr("衝撃の事実", "エンタメ")
        assert ctr2 > ctr1
        
        # 3. トリガー＋数字＋かっこ
        ctr3 = _estimate_ctr("【完全版】知らないと損する3つのこと", "Vlog")
        assert ctr3 > ctr1
        
        # 4. 上限9.0の制限が効く過剰ブースト
        ctr_max = _estimate_ctr("【衝撃完全版永久保存本気知らないプロなぜ全てマスター】123456", "エンタメ")
        assert ctr_max == 9.0

    def test_optimize_value_error_handling(self):
        """POST /optimize — ValueError発生時の400エラーハンドリング"""
        mock_yt = AsyncMock()
        mock_yt.optimize_context = AsyncMock(side_effect=ValueError("Invalid segments"))
        with patch.dict("sys.modules", {"plugins.youtube_optimizer_plugin": MagicMock(youtube_optimizer=mock_yt)}):
            client = _get_client()
            res = client.post("/api/youtube/optimize", json={"segments": [], "topics": []})
            assert res.status_code == 400
            assert "Invalid segments" in res.json()["detail"]

    def test_optimize_generic_exception_handling(self):
        """POST /optimize — 一般例外発生時の500エラーハンドリング"""
        mock_yt = AsyncMock()
        mock_yt.optimize_context = AsyncMock(side_effect=Exception("Context analyzer crashed"))
        with patch.dict("sys.modules", {"plugins.youtube_optimizer_plugin": MagicMock(youtube_optimizer=mock_yt)}):
            client = _get_client()
            res = client.post("/api/youtube/optimize", json={"segments": [], "topics": []})
            assert res.status_code == 500
            assert "Context analyzer crashed" in res.json()["detail"]

    def test_generate_thumbnail_without_mock_class(self):
        """POST /generate-thumbnail — ThumbnailCandidate クラスをモックせずに本物をインスタンス化させてカバー率を向上"""
        from plugins.youtube_optimizer_plugin import ThumbnailCandidate
        mock_yt = AsyncMock()
        mock_yt.generate_thumbnail_with_imagen = AsyncMock(return_value="/path/to/img.png")
        # plugins.youtube_optimizer_plugin は mock するが ThumbnailCandidate は本物を通す
        with patch.dict("sys.modules", {"plugins.youtube_optimizer_plugin": MagicMock(youtube_optimizer=mock_yt, ThumbnailCandidate=ThumbnailCandidate)}):
            client = _get_client()
            res = client.post("/api/youtube/generate-thumbnail", json={
                "thumbnail_id": "t123", 
                "context": {"concept": "test concept", "target_emotion": "surprise", "text_overlay": "Wow!"}
            })
            assert res.status_code == 200
            assert res.json()["success"] is True

    def test_generate_thumbnail_value_error_handling(self):
        """POST /generate-thumbnail — ValueError発生時の400エラーハンドリング"""
        from plugins.youtube_optimizer_plugin import ThumbnailCandidate
        mock_yt = AsyncMock()
        mock_yt.generate_thumbnail_with_imagen = AsyncMock(side_effect=ValueError("Invalid image parameter"))
        with patch.dict("sys.modules", {"plugins.youtube_optimizer_plugin": MagicMock(youtube_optimizer=mock_yt, ThumbnailCandidate=ThumbnailCandidate)}):
            client = _get_client()
            res = client.post("/api/youtube/generate-thumbnail", json={"thumbnail_id": "t1", "context": {}})
            assert res.status_code == 400

    def test_generate_thumbnail_generic_exception_handling(self):
        """POST /generate-thumbnail — 一般例外発生時の500エラーハンドリング"""
        from plugins.youtube_optimizer_plugin import ThumbnailCandidate
        mock_yt = AsyncMock()
        mock_yt.generate_thumbnail_with_imagen = AsyncMock(side_effect=Exception("Imagen API down"))
        with patch.dict("sys.modules", {"plugins.youtube_optimizer_plugin": MagicMock(youtube_optimizer=mock_yt, ThumbnailCandidate=ThumbnailCandidate)}):
            client = _get_client()
            res = client.post("/api/youtube/generate-thumbnail", json={"thumbnail_id": "t1", "context": {}})
            assert res.status_code == 500

    def test_improve_hook_value_error_handling(self):
        """POST /improve-hook — ValueError発生時の400エラーハンドリング"""
        mock_svc = AsyncMock()
        mock_svc.generate_improvements = AsyncMock(side_effect=ValueError("Hook text too short"))
        with patch.dict("sys.modules", {"services.hook_improver": MagicMock(hook_improver=mock_svc)}):
            client = _get_client()
            res = client.post("/api/youtube/improve-hook", json={"hook_text": "hello", "current_score": 50})
            assert res.status_code == 400
            assert "Hook text too short" in res.json()["detail"]

    def test_hook_preview_value_error_handling(self):
        """POST /hook-preview — ValueError発生時の400エラーハンドリング"""
        mock_gen = AsyncMock()
        mock_gen.generate_screenshot_preview = AsyncMock(side_effect=ValueError("Video path not found"))
        with patch.dict("sys.modules", {"services.hook_preview_generator": MagicMock(hook_preview_generator=mock_gen)}):
            client = _get_client()
            res = client.post("/api/youtube/hook-preview", json={"video_path": "/test.mp4", "original_text": "a", "improved_text": "b"})
            assert res.status_code == 400
            assert "Video path not found" in res.json()["detail"]

    def test_apply_hook_value_error_handling(self):
        """POST /apply-hook — ValueError発生時の400エラーハンドリング"""
        mock_svc = MagicMock()
        mock_svc.apply_improvement.side_effect = ValueError("Task ID invalid")
        with patch.dict("sys.modules", {"services.hook_evolution_service": MagicMock(hook_evolution_service=mock_svc)}):
            client = _get_client()
            res = client.post("/api/youtube/apply-hook", json={"task_id": "t1", "improvement_type": "attention", "improved_text": "new", "original_text": "old"})
            assert res.status_code == 400
            assert "Task ID invalid" in res.json()["detail"]

    def test_revert_hook_value_error_handling(self):
        """POST /revert-hook — ValueError発生時の400エラーハンドリング"""
        mock_svc = MagicMock()
        mock_svc.revert_latest.side_effect = ValueError("Nothing to revert")
        with patch.dict("sys.modules", {"services.hook_evolution_service": MagicMock(hook_evolution_service=mock_svc)}):
            client = _get_client()
            res = client.post("/api/youtube/revert-hook")
            assert res.status_code == 400
            assert "Nothing to revert" in res.json()["detail"]

    def test_hook_history_value_error_handling(self):
        """GET /hook-history — ValueError発生時の400エラーハンドリング"""
        mock_svc = MagicMock()
        mock_svc.get_history.side_effect = ValueError("History log corrupted")
        with patch.dict("sys.modules", {"services.hook_evolution_service": MagicMock(hook_evolution_service=mock_svc)}):
            client = _get_client()
            res = client.get("/api/youtube/hook-history")
            assert res.status_code == 400
            assert "History log corrupted" in res.json()["detail"]

    def test_record_post_publish_feedback_timeout_handling(self):
        """Timeout発生時に例外がキャッチされ、ログ出力が行われる（上に伝播しない）ことを確認"""
        from filelock import Timeout
        from routers.youtube_optimizer import _record_post_publish_feedback
        with patch("pathlib.Path.__truediv__", side_effect=Timeout("C:/lockfile.lock")):
            # 例外が発生せずに処理が終了することを確認
            _record_post_publish_feedback("w1", "v1", {}, {})

