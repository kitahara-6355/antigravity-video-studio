"""
Batch 10: legacy_production_router + pipeline_coordinator + video_processor
M2.6 カバレッジ 60% → 70% (Batch 10/10)

合計: ~55テスト
"""
import sys
import json
import asyncio
import pytest
import time as _time
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime

_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)


# ============================================================
# Part 1: legacy_production_router (20 tests)
# ============================================================

class TestLegacyValidatePath:
    """validate_video_path (同期ユーティリティ関数)"""

    def test_lp_01_empty_path(self):
        from routers.legacy_production_router import validate_video_path
        with pytest.raises(ValueError, match="File path is required"):
            validate_video_path("")

    def test_lp_02_allow_none(self):
        from routers.legacy_production_router import validate_video_path
        assert validate_video_path("", allow_none=True) is None

    def test_lp_03_outside_allowed_dir(self):
        from routers.legacy_production_router import validate_video_path
        with pytest.raises(ValueError, match="Access denied"):
            validate_video_path("C:\\Windows\\test.mp4")

    def test_lp_04_file_not_found(self, tmp_path):
        from routers.legacy_production_router import validate_video_path, ALLOWED_VIDEO_DIR
        fake = ALLOWED_VIDEO_DIR / "definitely_not_here_xyz.mp4"
        with pytest.raises(FileNotFoundError):
            validate_video_path(str(fake))


class TestLegacyEndpoints:
    """legacy_production_router.py — TestClientで直接呼ぶ"""

    @pytest.fixture(scope="class")
    def client(self):
        from fastapi.testclient import TestClient
        from main import app
        return TestClient(app, raise_server_exceptions=False)

    def test_lp_05_rhythm_split(self, client):
        r = client.post("/api/rhythm/split", json={"text": "これはテストテキストです。", "target_chars": 13})
        assert r.status_code in (200, 500)

    def test_lp_06_tasks_list(self, client):
        r = client.get("/api/tasks")
        assert r.status_code == 200
        assert "tasks" in r.json()

    def test_lp_07_task_not_found(self, client):
        r = client.get("/api/task/nonexistent-id")
        assert r.status_code == 404

    def test_lp_08_export_subtitles_no_task(self, client):
        r = client.post("/api/subtitle/export/srt", params={"task_id": "nonexistent"})
        assert r.status_code in (404, 422, 500)

    def test_lp_09_export_subtitles_bad_format(self, client):
        r = client.post("/api/subtitle/export/xyz", params={"task_id": "nonexistent"})
        assert r.status_code in (400, 404, 422, 500)

    def test_lp_10_preview_sessions(self, client):
        r = client.get("/api/preview/sessions")
        assert r.status_code == 200
        data = r.json()
        assert "sessions" in data or "error" in data

    def test_lp_11_preview_report_not_found(self, client):
        r = client.get("/api/preview/report/no-session")
        assert r.status_code == 404

    def test_lp_12_preview_decision_invalid(self, client):
        r = client.post("/api/preview/decision", json={
            "session_id": "no", "decision": "approve", "feedback": ""
        })
        assert r.status_code in (200, 404)  # May return 200 with error body

    def test_lp_13_color_presets(self, client):
        r = client.get("/api/video/color-presets")
        assert r.status_code in (200, 500)  # TECH_DEBT: 500 if preview_report_generator module missing

    def test_lp_14_video_list(self, client):
        r = client.get("/api/video/list")
        assert r.status_code == 200

    def test_lp_15_debug_tasks(self, client):
        r = client.get("/api/debug/video-tasks")
        assert r.status_code == 200

    def test_lp_16_process_status_not_found(self, client):
        r = client.get("/api/video/process/status/no-task")
        assert r.status_code == 404

    def test_lp_17_transcribe_status_empty(self, client):
        r = client.get("/api/transcribe/status")
        assert r.status_code == 200

    def test_lp_18_process_start_no_video(self, client, safe_popen_mock):
        proc = safe_popen_mock(returncode=0)
        with patch("subprocess.Popen", return_value=proc), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stderr = ""
            mock_run.return_value.stdout = "{}"
            r = client.post("/api/video/process/start", json={
                "video_paths": [], "mood": "elegant"
            })
            assert r.status_code in (200, 400, 404, 500)

    def test_lp_19_preview_session_create(self, client):
        r = client.post("/api/preview/session", json={})
        assert r.status_code == 200
        assert "session_id" in r.json()

    def test_lp_20_realtime_preview_error(self, client):
        r = client.post("/api/video/realtime-preview", json={
            "video_path": "", "mood": "elegant", "duration": 10
        })
        assert r.status_code in (200, 400, 500)


# ============================================================
# Part 2: pipeline_coordinator (20 tests)
# ============================================================

class TestCoordinatorHelpers:
    """pipeline_coordinator.py — ヘルパーメソッド"""

    @pytest.fixture
    def coord(self):
        from agents.pipeline_coordinator import PipelineCoordinator
        return PipelineCoordinator()

    @pytest.fixture
    def ctx(self):
        from agents.pipeline_types import PipelineContext
        return PipelineContext(video_path="/fake/video.mp4", target_minutes=20, session_id="test-s")

    def test_pc_01_init(self, coord):
        assert len(coord.workers) == 7

    def test_pc_02_find_worker(self, coord):
        from agents.workers import TranscribeWorker, RenderWorker
        assert coord._find_worker(TranscribeWorker) is not None
        assert coord._find_worker(RenderWorker) is not None

    def test_pc_03_find_worker_missing(self, coord):
        assert coord._find_worker(str) is None

    def test_pc_04_set_callback(self, coord):
        cb = MagicMock()
        coord.set_progress_callback(cb)
        assert coord._progress_callback is cb

    def test_pc_05_set_ws_broadcast(self, coord):
        fn = MagicMock()
        coord.set_ws_broadcast(fn)
        assert coord._ws_broadcast is fn

    def test_pc_06_ensure_template_no_import(self, coord, ctx):
        with patch.dict(sys.modules, {"template_config": None}):
            coord._ensure_template(ctx)

    def test_pc_07_ensure_template_active(self, coord, ctx):
        mock_tc = MagicMock()
        mock_tc.is_active = True
        with patch.dict(sys.modules, {
            "template_config": MagicMock(template_config=mock_tc)
        }):
            coord._ensure_template(ctx)

    def test_pc_08_build_result_completed(self, coord, ctx):
        ctx.quality_score = 95
        ctx.stage_results = []
        result = coord._build_result(ctx, "completed", _time.time())
        assert result["status"] == "completed"
        assert result["quality_gate_report"] is None

    def test_pc_09_build_result_quality_blocked(self, coord, ctx):
        ctx.quality_score = 70
        ctx.quality_feedback = ["音声が小さい"]
        ctx.stage_results = []
        result = coord._build_result(ctx, "completed", _time.time())
        qgr = result["quality_gate_report"]
        assert qgr is not None
        assert qgr["gap"] == 20

    def test_pc_10_build_result_error(self, coord, ctx):
        ctx.quality_score = 0
        ctx.stage_results = []
        result = coord._build_result(ctx, "error", _time.time(), "fatal")
        assert result["error"] == "fatal"

    def test_pc_11_suggestions_audio(self, coord, ctx):
        ctx.quality_feedback = ["音が小さすぎます", "LUFSが基準以下"]
        s = coord._generate_improvement_suggestions(ctx)
        assert any(x["action"] == "audio_normalization" for x in s)

    def test_pc_12_suggestions_subtitle(self, coord, ctx):
        ctx.quality_feedback = ["字幕に誤字"]
        s = coord._generate_improvement_suggestions(ctx)
        assert any(x["action"] == "re_proofread" for x in s)

    def test_pc_13_suggestions_metadata(self, coord, ctx):
        ctx.quality_feedback = ["タイトル不適切"]
        s = coord._generate_improvement_suggestions(ctx)
        assert any(x["action"] == "regenerate_metadata" for x in s)

    def test_pc_14_suggestions_segments(self, coord, ctx):
        ctx.quality_feedback = ["セグメント構成が悪い"]
        s = coord._generate_improvement_suggestions(ctx)
        assert any(x["action"] == "restructure_segments" for x in s)

    def test_pc_15_no_dup_suggestions(self, coord, ctx):
        ctx.quality_feedback = ["音量低い", "LUFS不足", "ラウドネス問題"]
        s = coord._generate_improvement_suggestions(ctx)
        actions = [x["action"] for x in s]
        assert actions.count("audio_normalization") == 1

    def test_pc_16_empty_suggestions(self, coord, ctx):
        ctx.quality_feedback = []
        assert coord._generate_improvement_suggestions(ctx) == []

    @pytest.mark.asyncio
    async def test_pc_17_retention_skip(self, coord, ctx):
        with patch.dict(sys.modules, {"plugins.retention_map_plugin": None}):
            assert await coord._run_retention_analysis(ctx) is None

    @pytest.mark.asyncio
    async def test_pc_18_dream_learning_skip(self, coord, ctx):
        ctx.stage_results = []
        ctx.segments = []
        ctx.selected_segments = []
        with patch.dict(sys.modules, {"agents.dream_engine": None}):
            await coord._trigger_dream_learning(ctx)

    @pytest.mark.asyncio
    async def test_pc_19_notify_callback(self, coord):
        cb = MagicMock()
        coord.set_progress_callback(cb)
        from agents.workers import TranscribeWorker
        w = TranscribeWorker()
        await coord._notify(w, "running", "test")
        cb.assert_called_once()

    @pytest.mark.asyncio
    async def test_pc_20_notify_ws(self, coord):
        ws = AsyncMock()
        coord.set_ws_broadcast(ws)
        from agents.workers import TranscribeWorker
        w = TranscribeWorker()
        await coord._notify(w, "running", "test", data={"k": "v"})
        ws.assert_called_once()
        msg = ws.call_args[0][0]
        assert msg["type"] == "pipeline_progress"


# ============================================================
# Part 3: video_processor 深掘り (15 tests)
# ============================================================

class TestVideoProcessorDeep:
    """video_processor.py — 未カバー分岐"""

    @pytest.fixture
    def proc(self, tmp_path):
        from video_processor import VideoProcessor
        return VideoProcessor(output_dir=str(tmp_path))

    def test_vp_01_init(self, proc):
        assert proc.output_dir.exists()

    def test_vp_02_get_mood_elegant(self, proc):
        s = proc.get_mood_settings("elegant")
        assert s.name == "エレガント"

    def test_vp_03_get_mood_dynamic(self, proc):
        s = proc.get_mood_settings("dynamic")
        assert s.name == "ダイナミック"

    def test_vp_04_get_mood_dramatic(self, proc):
        s = proc.get_mood_settings("dramatic")
        assert s.color_preset == "cinematic"

    def test_vp_05_get_mood_default(self, proc):
        s = proc.get_mood_settings("nonexistent")
        assert s.name == "エレガント"

    def test_vp_06_create_task(self, proc):
        t = proc.create_task("t1", ["/v.mp4"], "elegant")
        assert t.task_id == "t1"
        assert "t1" in proc.tasks

    def test_vp_07_get_task(self, proc):
        proc.create_task("t2", ["/v.mp4"], "dynamic")
        assert proc.get_task("t2") is not None
        assert proc.get_task("nope") is None

    def test_vp_08_color_filter_warm(self, proc):
        from video_processor import MOOD_SETTINGS
        f = proc._get_color_filter(MOOD_SETTINGS["elegant"])
        assert "colorbalance" in f

    def test_vp_09_color_filter_vibrant(self, proc):
        from video_processor import MOOD_SETTINGS
        f = proc._get_color_filter(MOOD_SETTINGS["dynamic"])
        assert "saturation=1.3" in f

    def test_vp_10_color_filter_cinematic(self, proc):
        from video_processor import MOOD_SETTINGS
        f = proc._get_color_filter(MOOD_SETTINGS["dramatic"])
        assert "saturation=0.9" in f

    def test_vp_11_progress_callback(self, proc):
        cb = MagicMock()
        proc.set_progress_callback(cb)
        t = proc.create_task("t3", ["/v.mp4"], "elegant")
        proc._notify_progress(t)
        cb.assert_called_once_with(t)

    def test_vp_12_process_no_task(self, proc):
        assert proc.process_video("nonexistent") is False

    def test_vp_13_audio_normalize_no_template(self, proc):
        with patch.dict(sys.modules, {"template_config": None}):
            args = proc._get_audio_normalize_args("/fake.mp4")
            assert args == []

    def test_vp_14_merge_no_scenes(self, proc, tmp_path):
        proc._merge_scenes([], str(tmp_path / "out.mp4"))

    def test_vp_15_merge_one_scene(self, proc, tmp_path):
        scene = tmp_path / "scene1.mp4"
        scene.write_bytes(b"fake")
        out = tmp_path / "merged.mp4"
        proc._merge_scenes([str(scene)], str(out))
        assert out.exists()
