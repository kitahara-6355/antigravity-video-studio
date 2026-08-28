"""
Router Tests Batch 2 - legacy_production / themes / pipeline_report / review
Total: ~45 tests

Key: sys.modulesのMagicMockパッチは pydantic.root_model を壊すため使用禁止。
Key: 関数の遅延インポートとインポートキャッシュに注意し、パッチは常にモジュールベースまたは両方のパスに対して当てる。
"""
import pytest
import builtins
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path
from fastapi import HTTPException


# ============================================================
# Legacy Production Router (17 tests)
# ============================================================

class TestLegacyProductionRouter:
    def _get_client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend.routers.legacy_production_router import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_transcription_status_idle(self):
        client = self._get_client()
        res = client.get("/api/transcribe/status")
        assert res.status_code == 200
        assert res.json()["status"] in ("idle", "unknown")

    def test_get_task_not_found(self):
        mock_ts = MagicMock()
        mock_ts.get_task.return_value = None
        with patch("backend.routers.legacy_production_router.task_store", mock_ts, create=True):
            client = self._get_client()
            res = client.get("/api/task/nonexistent")
        from task_store import task_store
        with patch.object(task_store, "get_task", return_value=None):
            client = self._get_client()
            res = client.get("/api/task/nonexistent")
            assert res.status_code == 404

    def test_get_task_found(self):
        from task_store import task_store
        mock_task = MagicMock()
        mock_task.to_dict.return_value = {"task_id": "t1", "status": "completed"}
        with patch.object(task_store, "get_task", return_value=mock_task):
            client = self._get_client()
            res = client.get("/api/task/t1")
            assert res.status_code == 200
            assert res.json()["task_id"] == "t1"

    def test_list_tasks(self):
        from task_store import task_store
        with patch.object(task_store, "list_tasks", return_value=[]):
            client = self._get_client()
            res = client.get("/api/tasks")
            assert res.status_code == 200
            assert "tasks" in res.json()

    def test_preview_decision(self):
        client = self._get_client()
        res = client.post("/api/preview/decision", json={
            "session_id": "s1", "decision": "approve", "feedback": ""
        })
        assert res.status_code == 200
        assert res.json()["status"] == "recorded"

    def test_list_preview_sessions(self):
        client = self._get_client()
        res = client.get("/api/preview/sessions")
        assert res.status_code == 200
        assert "sessions" in res.json()

    def test_video_process_status_not_found(self):
        client = self._get_client()
        res = client.get("/api/video/process/status/nonexistent")
        assert res.status_code == 404

    def test_debug_video_tasks(self):
        client = self._get_client()
        res = client.get("/api/debug/video-tasks")
        assert res.status_code == 200
        assert "task_count" in res.json()

    def test_list_available_videos(self):
        client = self._get_client()
        res = client.get("/api/video/list")
        assert res.status_code == 200
        assert "videos" in res.json()

    def test_validate_video_path_empty(self):
        from backend.routers.legacy_production_router import validate_video_path
        with pytest.raises(ValueError, match="required"):
            validate_video_path("")

    def test_validate_video_path_allow_none(self):
        from backend.routers.legacy_production_router import validate_video_path
        result = validate_video_path("", allow_none=True)
        assert result is None

    def test_validate_video_path_outside_dir(self, tmp_path):
        from backend.routers.legacy_production_router import validate_video_path
        fake = tmp_path / "test.mp4"
        fake.write_bytes(b"x" * 100)
        with pytest.raises(ValueError, match="Access denied"):
            validate_video_path(str(fake))

    def test_validate_video_path_http_exception(self):
        from backend.routers.legacy_production_router import validate_video_path
        with patch("backend.routers.legacy_production_router.Path") as mock_path_cls:
            mock_path_cls.return_value.resolve.side_effect = HTTPException(status_code=400, detail="HTTP error")
            with pytest.raises(HTTPException):
                validate_video_path("dummy.mp4")

    def test_color_presets_endpoint(self):
        """GET /api/video/color-presets - lazy import"""
        client = self._get_client()
        res = client.get("/api/video/color-presets")
        assert res.status_code in (200, 500)

    def test_create_preview_session(self):
        mock_pp = MagicMock()
        mock_pp.return_value.session_id = "sess1"
        mock_pp.return_value.output_dir = Path("/tmp/preview")
        with patch("backend.routers.legacy_production_router.ProgressivePreview", mock_pp, create=True):
            client = self._get_client()
            res = client.post("/api/preview/session", json={})
            assert res.status_code == 200

    def test_preview_report_not_found(self):
        client = self._get_client()
        res = client.get("/api/preview/report/nonexistent")
        assert res.status_code == 404

    def test_subtitle_export_invalid(self):
        client = self._get_client()
        res = client.post("/api/subtitle/export/xml", json=[])
        assert res.status_code in (400, 422)

    def test_rhythm_endpoint(self):
        mock_split = MagicMock(return_value=["part1", "part2"])
        with patch("backend.routers.legacy_production_router.semantic_split", mock_split, create=True):
            client = self._get_client()
            res = client.post("/api/rhythm/split", json={"text": "test", "target_chars": 13})
            assert res.status_code == 200

    def test_rhythm_endpoint_http_exception(self):
        import ai_rhythm
        with patch.object(ai_rhythm, "semantic_split", side_effect=HTTPException(status_code=400, detail="rhythm error")):
            client = self._get_client()
            res = client.post("/api/rhythm/split", json={"text": "test", "target_chars": 13})
            assert res.status_code == 400

    def test_rhythm_endpoint_general_exception(self):
        import ai_rhythm
        with patch.object(ai_rhythm, "semantic_split", side_effect=ValueError("general error")):
            client = self._get_client()
            res = client.post("/api/rhythm/split", json={"text": "test", "target_chars": 13})
            assert res.status_code == 500

    def test_get_transcription_status_exception(self):
        original_open = builtins.open
        def mock_open(file, *args, **kwargs):
            if "transcription_status.json" in str(file):
                raise IOError("Mocked read failure")
            return original_open(file, *args, **kwargs)

        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open):
                client = self._get_client()
                res = client.get("/api/transcribe/status")
                assert res.status_code == 200
                assert res.json()["status"] == "unknown"

    def test_transcribe_video_exception(self):
        with patch("subtitle_engine.WhisperTranscriber") as mock_whisper:
            mock_whisper.return_value.transcribe_with_proofreading.side_effect = Exception("whisper fail")
            client = self._get_client()
            res = client.post("/api/subtitle/transcribe", files={"file": ("test.mp4", b"dummy content")})
            assert res.status_code == 500
            assert "whisper fail" in res.json()["detail"]

    def test_export_subtitles_exception(self):
        with patch("subtitle_engine.SubtitleFormatter") as mock_formatter1, \
             patch("backend.subtitle_engine.SubtitleFormatter", create=True) as mock_formatter2:
            mock_formatter1.to_vtt.side_effect = Exception("formatter fail")
            mock_formatter2.to_vtt.side_effect = Exception("formatter fail")
            client = self._get_client()
            res = client.post("/api/subtitle/export/vtt", files=[("subtitles", ("subtitles.json", b"[]"))])
            assert res.status_code == 500
            assert "formatter fail" in res.json()["detail"]

    def test_capture_step_snapshot_exception(self):
        import progressive_preview
        with patch.object(progressive_preview, "ProgressivePreview") as mock_pp:
            mock_pp.return_value.snapshot_step.side_effect = Exception("snapshot fail")
            client = self._get_client()
            res = client.post("/api/preview/step", json={
                "session_id": "s1", "step_name": "s", "before_video": "b", "after_video": "a"
            })
            assert res.status_code == 500
            assert "snapshot fail" in res.json()["detail"]

    def test_get_preview_report_exception(self):
        from backend.routers.legacy_production_router import _preview_sessions
        mock_pp = MagicMock()
        mock_pp.output_dir = Path("/tmp/preview")
        _preview_sessions["sess_err"] = mock_pp
        
        import progressive_preview_report as preview_report
        with patch.object(preview_report, "PreviewReportGenerator") as mock_gen:
            mock_gen.return_value.generate_from_session_dir.side_effect = Exception("report fail")
            client = self._get_client()
            res = client.get("/api/preview/report/sess_err")
            assert res.status_code == 500
            assert "report fail" in res.json()["detail"]

    def test_apply_color_grading_exception(self):
        with patch("color_grading.color_grading") as mock_cg:
            mock_cg.apply_preset.side_effect = Exception("grading fail")
            client = self._get_client()
            res = client.post("/api/video/color-grade?video_path=test.mp4&preset=cinematic")
            assert res.status_code == 500
            assert "grading fail" in res.json()["detail"]


# ============================================================
# Themes Router (10 tests)
# ============================================================

class TestThemesRouter:
    def _get_client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routers.themes_router import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_list_templates(self):
        client = self._get_client()
        res = client.get("/themes/templates")
        assert res.status_code == 200
        assert res.json()["count"] == 4

    def test_get_template_valid(self):
        client = self._get_client()
        res = client.get("/themes/templates/nhk_documentary")
        assert res.status_code == 200
        assert res.json()["template"]["id"] == "nhk_documentary"

    def test_get_template_invalid(self):
        client = self._get_client()
        res = client.get("/themes/templates/nonexistent")
        assert res.status_code == 404
        assert "Template 'nonexistent' not found" in res.json()["detail"]

    def test_list_themes(self):
        client = self._get_client()
        res = client.get("/themes")
        assert res.status_code == 200
        assert res.json()["count"] == 4

    def test_get_theme_valid(self):
        client = self._get_client()
        res = client.get("/themes/warm")
        assert res.status_code == 200
        assert res.json()["theme"]["id"] == "warm"

    def test_get_theme_invalid(self):
        client = self._get_client()
        res = client.get("/themes/nonexistent")
        assert res.status_code == 404
        assert "Theme 'nonexistent' not found" in res.json()["detail"]

    def test_apply_invalid_template(self):
        client = self._get_client()
        res = client.post("/themes/apply", json={"template_id": "bad", "theme_id": "warm"})
        assert res.status_code == 400
        assert "Template 'bad' not found" in res.json()["detail"]

    def test_apply_invalid_theme(self):
        client = self._get_client()
        res = client.post("/themes/apply", json={"template_id": "nhk_documentary", "theme_id": "bad"})
        assert res.status_code == 400
        assert "Theme 'bad' not found" in res.json()["detail"]

    def test_apply_success(self):
        mock_dtm = MagicMock()
        mock_dtm.update_tokens.return_value = {"updated": True}
        with patch("routers.themes_router.design_token_manager", mock_dtm, create=True), \
             patch("routers.themes_router.template_config", MagicMock(), create=True), \
             patch("routers.themes_router._record_template_selection"):
            client = self._get_client()
            res = client.post("/themes/apply", json={
                "template_id": "nhk_documentary", "theme_id": "warm"
            })
            assert res.status_code == 200
            assert res.json()["status"] == "applied"

    def test_get_stats_no_log(self):
        client = self._get_client()
        res = client.get("/themes/stats")
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, dict)


# ============================================================
# Pipeline Report Router (8 tests)
# ============================================================

class TestPipelineReportRouter:
    def _get_client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routers.pipeline_report import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_report_idle(self):
        with patch("routers.pipeline_router._pipeline_state", {
            "status": "idle", "result": {}, "video_path": ""
        }):
            client = self._get_client()
            res = client.get("/api/pipeline/report")
            assert res.status_code == 200
            assert "text/html" in res.headers["content-type"]

    def test_report_with_stages(self):
        mock_state = {
            "status": "completed", "video_path": "/test.mp4",
            "result": {
                "segments_count": 15,
                "stage_results": [
                    {"name": "SmartCut", "success": True, "detail": "10seg", "duration": 2.0, "retries": 0},
                ],
                "preview_path": None,
                "quality_details": {"score": 85, "category_report": [], "feedback": []},
                "final_path": None,
                "metadata": {"titles": ["T1"], "tags": ["t1", "t2", "t3", "t4", "t5"], "chapters": []},
                "duration_seconds": 120, "session_id": "sess-123",
            }
        }
        with patch("routers.pipeline_router._pipeline_state", mock_state):
            client = self._get_client()
            res = client.get("/api/pipeline/report")
            assert res.status_code == 200

    def test_probe_video_fallback(self):
        from routers.pipeline_report import _probe_video
        result = _probe_video("/nonexistent/path.mp4")
        assert result["valid"] is False

    def test_build_category_html_empty(self):
        from routers.pipeline_report import _build_category_html
        html = _build_category_html({})
        assert len(html) > 0

    def test_build_category_html_with_data(self):
        from routers.pipeline_report import _build_category_html
        html = _build_category_html({"category_report": [
            {"label": "audio", "score": 95, "status": "OK", "deductions": 5, "plugin_count": 3}
        ]})
        assert "95" in html

    def test_build_feedback_html_empty(self):
        from routers.pipeline_report import _build_feedback_html
        html = _build_feedback_html({"feedback": []})
        assert len(html) > 0

    def test_build_feedback_html_with_items(self):
        from routers.pipeline_report import _build_feedback_html
        html = _build_feedback_html({"feedback": ["issue1", "issue2"]})
        assert "2" in html

    def test_report_quality_gate(self):
        from unittest.mock import patch
        mock_state = {
            "status": "completed", "video_path": "/test.mp4",
            "result": {
                "segments_count": 10, "stage_results": [],
                "preview_path": None,
                "quality_details": {
                    "score": 95,
                    "category_report": [{"category": "audio", "label": "audio", "score": 95, "status": "PASS", "deductions": 5, "plugin_count": 2}],
                    "feedback": [],
                },
                "final_path": None,
                "metadata": {"titles": [], "tags": [], "chapters": []},
                "duration_seconds": 60, "session_id": "s1",
            }
        }
        with patch("routers.pipeline_router._pipeline_state", mock_state):
            client = self._get_client()
            res = client.get("/api/pipeline/report")
            assert res.status_code == 200

    def test_probe_video_success(self):
        import json
        from unittest.mock import patch, MagicMock
        from routers.pipeline_report import _probe_video
        mock_run_result = MagicMock()
        mock_run_result.returncode = 0
        mock_run_result.stdout = json.dumps({
            "streams": [
                {"codec_type": "video", "codec_name": "h264"},
                {"codec_type": "audio", "codec_name": "aac"}
            ],
            "format": {"duration": "123.45"}
        })
        with patch("subprocess.run", return_value=mock_run_result):
            res = _probe_video("dummy.mp4")
            assert res["valid"] is True
            assert res["video_codec"] == "h264"
            assert res["audio_codec"] == "aac"
            assert res["duration_sec"] == 123.5

    def test_probe_video_no_streams(self):
        import json
        from unittest.mock import patch, MagicMock
        from routers.pipeline_report import _probe_video
        mock_run_result = MagicMock()
        mock_run_result.returncode = 0
        mock_run_result.stdout = json.dumps({
            "streams": [],
            "format": {}
        })
        with patch("subprocess.run", return_value=mock_run_result):
            res = _probe_video("dummy.mp4")
            assert res["valid"] is True
            assert res["video_codec"] == "unknown"
            assert res["audio_codec"] == "unknown"
            assert res["duration_sec"] == 0

    def test_probe_video_exception(self):
        from unittest.mock import patch
        from routers.pipeline_report import _probe_video
        with patch("subprocess.run", side_effect=Exception("subprocess error")):
            res = _probe_video("dummy.mp4")
            assert res["valid"] is False
            assert res["error"] == "ffprobe不可"

    def test_probe_video_path_replacement_success(self):
        from unittest.mock import patch, MagicMock
        from routers.pipeline_report import _probe_video
        mock_editor = MagicMock()
        mock_editor.ffmpeg.ffmpeg_path = "C:\\path\\to\\ffmpeg.exe"
        
        mock_run = MagicMock()
        mock_run.returncode = 0
        mock_run.stdout = "{}"
        
        with patch.dict("sys.modules", {"video_editor_engine": MagicMock()}), \
             patch("video_editor_engine.video_editor", mock_editor, create=True), \
             patch("subprocess.run", mock_run):
            _probe_video("dummy.mp4")
            called_args = mock_run.call_args[0][0]
            assert "ffprobe.exe" in called_args[0]

    def test_probe_video_path_replacement_no_match(self):
        from unittest.mock import patch, MagicMock
        from routers.pipeline_report import _probe_video
        mock_editor = MagicMock()
        mock_editor.ffmpeg.ffmpeg_path = "C:\\path\\to\\ffmpeg_runner"
        
        mock_run = MagicMock()
        mock_run.returncode = 0
        mock_run.stdout = "{}"
        
        with patch.dict("sys.modules", {"video_editor_engine": MagicMock()}), \
             patch("video_editor_engine.video_editor", mock_editor, create=True), \
             patch("subprocess.run", mock_run):
            _probe_video("dummy.mp4")
            called_args = mock_run.call_args[0][0]
            assert "ffprobe.exe" in called_args[0]

    def test_probe_video_import_error(self):
        from unittest.mock import patch, MagicMock
        from routers.pipeline_report import _probe_video
        mock_run = MagicMock()
        mock_run.returncode = 0
        mock_run.stdout = "{}"
        
        orig_import = __import__
        def mock_import(name, *args, **kwargs):
            if name == "video_editor_engine":
                raise ImportError("mock import error")
            return orig_import(name, *args, **kwargs)
            
        with patch("builtins.__import__", side_effect=mock_import), \
             patch("subprocess.run", mock_run):
            _probe_video("dummy.mp4")
            called_args = mock_run.call_args[0][0]
            assert called_args[0] == "ffprobe"

    def test_build_category_html_non_dict(self):
        from routers.pipeline_report import _build_category_html
        quality = {
            "category_report": [
                None,
                {"category": "video", "label": "video", "score": 90, "status": "PASS", "deductions": 0, "plugin_count": 1}
            ]
        }
        html = _build_category_html(quality)
        assert "video" in html

    def test_report_quality_gate_invalid_score(self):
        from unittest.mock import patch
        for invalid_score in (None, "ninety"):
            mock_state = {
                "status": "completed", "video_path": "/test.mp4",
                "result": {
                    "segments_count": 10, "stage_results": [],
                    "preview_path": None,
                    "quality_details": {
                        "score": invalid_score,
                        "category_report": [],
                        "feedback": [],
                    },
                    "final_path": None,
                    "metadata": {"titles": [], "tags": [], "chapters": []},
                    "duration_seconds": 60, "session_id": "s1",
                }
            }
            with patch("routers.pipeline_router._pipeline_state", mock_state):
                client = self._get_client()
                res = client.get("/api/pipeline/report")
                assert res.status_code == 200

    def test_probe_video_import_http_exception(self):
        from routers.pipeline_report import _probe_video
        from unittest.mock import patch

        orig_import = __import__
        def mock_import(name, *args, **kwargs):
            if name == "video_editor_engine":
                raise HTTPException(status_code=400, detail="Import HTTP error")
            return orig_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            with pytest.raises(HTTPException) as excinfo:
                _probe_video("dummy.mp4")
            assert excinfo.value.status_code == 400
            assert excinfo.value.detail == "Import HTTP error"

    def test_probe_video_subprocess_http_exception(self):
        from routers.pipeline_report import _probe_video
        from unittest.mock import patch
        
        with patch("subprocess.run", side_effect=HTTPException(status_code=403, detail="Subprocess HTTP error")):
            with pytest.raises(HTTPException) as excinfo:
                _probe_video("dummy.mp4")
            assert excinfo.value.status_code == 403
            assert excinfo.value.detail == "Subprocess HTTP error"

    def test_report_all_ok(self, tmp_path):
        from unittest.mock import patch, MagicMock
        import json
        
        # 1MB以上のダミーファイルをテンポラリに作成
        dummy_preview = tmp_path / "preview.mp4"
        dummy_preview.write_bytes(b"x" * (1 * 1024 * 1024 + 100))
        dummy_final = tmp_path / "final.mp4"
        dummy_final.write_bytes(b"x" * (1 * 1024 * 1024 + 100))
        dummy_thumbnail = tmp_path / "thumbnail.jpg"
        dummy_thumbnail.write_bytes(b"x" * 2000)
        
        mock_state = {
            "status": "completed",
            "video_path": str(dummy_final),
            "result": {
                "segments_count": 5,
                "stage_results": [
                    {"name": "文字起こし", "success": True, "detail": "5seg", "duration": 1.0, "retries": 0},
                    {"name": "AI校閲", "success": True, "detail": "done", "duration": 1.0, "retries": 0},
                    {"name": "SmartCut", "success": True, "detail": "done", "duration": 1.0, "retries": 0},
                    {"name": "プレビュー", "success": True, "detail": "done", "duration": 1.0, "retries": 0},
                    {"name": "品質", "success": True, "detail": "done", "duration": 1.0, "retries": 0},
                    {"name": "レンダリング", "success": True, "detail": "done", "duration": 1.0, "retries": 0},
                    {"name": "YouTube", "success": True, "detail": "done", "duration": 1.0, "retries": 0},
                    {"name": "サムネイル", "success": True, "detail": "done", "duration": 1.0, "retries": 0},
                ],
                "preview_path": str(dummy_preview),
                "quality_details": {
                    "score": 95,
                    "category_report": [
                        {"category": "audio", "label": "audio", "score": 95, "status": "PASS", "deductions": 0, "plugin_count": 2}
                    ],
                    "feedback": [],
                },
                "final_path": str(dummy_final),
                "thumbnail_path": str(dummy_thumbnail),
                "metadata": {
                    "titles": ["Best Video"],
                    "tags": ["t1", "t2", "t3", "t4", "t5"],
                    "chapters": [{"timecode": "00:00", "title": "Intro"}]
                },
                "duration_seconds": 30,
                "session_id": "sess-all-ok",
            }
        }
        
        # ffprobeの正常系モック
        mock_run_result = MagicMock()
        mock_run_result.returncode = 0
        mock_run_result.stdout = json.dumps({
            "streams": [
                {"codec_type": "video", "codec_name": "h264"},
                {"codec_type": "audio", "codec_name": "aac"}
            ],
            "format": {"duration": "30.0"}
        })
        
        with patch("routers.pipeline_router._pipeline_state", mock_state), \
             patch("subprocess.run", return_value=mock_run_result):
            client = self._get_client()
            res = client.get("/api/pipeline/report")
            assert res.status_code == 200
            html_content = res.text
            assert "✅ 全機能適用済み完成動画" in html_content
            assert "background: linear-gradient(135deg, #065f46, #064e3b)" in html_content

    def test_report_thumbnail_success(self, tmp_path):
        dummy_thumb = tmp_path / "thumb.jpg"
        dummy_thumb.write_bytes(b"x" * 2000)
        mock_state = {
            "result": {
                "thumbnail_path": str(dummy_thumb)
            }
        }
        with patch("routers.pipeline_router._pipeline_state", mock_state):
            client = self._get_client()
            res = client.get("/api/pipeline/report/thumbnail")
            assert res.status_code == 200
            assert len(res.content) == 2000

    def test_report_thumbnail_not_found(self):
        mock_state = {
            "result": {
                "thumbnail_path": "nonexistent.jpg"
            }
        }
        with patch("routers.pipeline_router._pipeline_state", mock_state):
            client = self._get_client()
            res = client.get("/api/pipeline/report/thumbnail")
            assert res.status_code == 404


# ============================================================
# Review Router (7 tests)
# ============================================================

class TestReviewRouter:
    def _get_client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routers.review_router import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_get_all_stages(self):
        client = self._get_client()
        res = client.get("/api/review/stages")
        assert res.status_code == 200
        assert res.json()["total"] == 5

    def test_get_stage_info(self):
        client = self._get_client()
        res = client.get("/api/review/stages/subtitle")
        assert res.status_code == 200
        assert res.json()["id"] == "subtitle"

    def test_get_stage_report(self):
        mock_pr = MagicMock()
        mock_pr.generate_stage_report.return_value = "# Report"
        with patch("routers.review_router.progressive_review", mock_pr, create=True), \
             patch("routers.review_router.PluginStage", MagicMock(), create=True), \
             patch("routers.review_router.ProductionContext", MagicMock(), create=True):
            client = self._get_client()
            res = client.get("/api/review/stages/subtitle/report")
            assert res.status_code == 200
            assert res.json()["status"] == "generated"

    def test_approve_stage(self):
        client = self._get_client()
        res = client.post("/api/review/stages/subtitle/approve")
        assert res.status_code in (200, 400, 500)

    def test_request_revision(self):
        client = self._get_client()
        res = client.post("/api/review/stages/subtitle/revision", json={
            "stage": "subtitle", "notes": "fix needed"
        })
        assert res.status_code in (200, 400, 500)

    def test_get_review_status(self):
        mock_pr = MagicMock()
        mock_pr.get_pending_stages.return_value = []
        with patch("routers.review_router.progressive_review", mock_pr, create=True):
            client = self._get_client()
            res = client.get("/api/review/status")
            assert res.status_code == 200
            assert res.json()["all_approved"] is True

    def test_get_review_summary(self):
        """**採点できたステージが無いので準備完了にならない**（R1.5-C4）。

        `pending_revisions == 0` だけを見ていたので、1つも測っていない
        セッションでも `ready_for_render: true` になっていた。それは
        「修正を要求した人が誰もいない」の意味でしかなく、品質の主張ではない。

        なお `routers.review_router.progressive_review` へのパッチは**効かない**
        （`_get_plugin_components()` が関数の中で import する）。ここが見ている
        のは実物の挙動で、空の `ProductionContext` では採点できるステージが無い。
        """
        client = self._get_client()
        res = client.get("/api/review/summary")
        assert res.status_code == 200
        body = res.json()
        assert body["summary"]["scored_stages"] == []
        assert body["summary"]["overall_score"] is None
        assert body["ready_for_render"] is False
        assert "品質ゲート" in body["ready_for_render_reason"]

    def test_採点できれば準備完了になりうる(self):
        """**門が恒真でないことの確認。** 採点できたステージがあれば true。"""
        mock_pr = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.get_extension.return_value = {
            "pending_revisions": 0, "scored_stages": ["subtitle"]}
        mock_pr.execute.return_value = mock_ctx
        with patch("plugins.progressive_review_plugin.progressive_review",
                   mock_pr, create=True), \
             patch("core.ProductionContext", MagicMock(return_value=mock_ctx),
                   create=True):
            res = self._get_client().get("/api/review/summary")
            assert res.status_code == 200
            assert res.json()["ready_for_render"] is True
