import pytest
import sys
import os
import json
import base64
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open, AsyncMock

# backend ディレクトリへのパスを通す
backend_dir = Path(__file__).resolve().parents[2]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# アーカイブディレクトリへのパスを通す
archive_dir = backend_dir / "archives" / "archive_stable_v3.0_20260118_0953"
if str(archive_dir) not in sys.path:
    sys.path.insert(0, str(archive_dir))

# 環境変数
os.environ["GOOGLE_API_KEY"] = "mock_api_key"

# 外部依存のモック化（sys.modulesを利用してインポートエラーを防ぐ）
mock_brain = MagicMock()
mock_task_manager = MagicMock()
mock_branding_manager = MagicMock()
mock_settings_manager = MagicMock()
mock_preview_engine = MagicMock()
mock_video_processor = MagicMock()
mock_quality_gate = MagicMock()
mock_draft_manager = MagicMock()
mock_cleanup_manager = MagicMock()
mock_decision_logger = MagicMock()
mock_task_store = MagicMock()
mock_project_archiver = MagicMock()
mock_whisper_transcriber = MagicMock()
mock_subtitle_formatter = MagicMock()
mock_thumbnail_generator = MagicMock()
# AsyncMock に設定して await エラーを防ぐ
mock_thumbnail_generator.generate = AsyncMock()
mock_broadcaster = MagicMock()
mock_progress_manager = MagicMock()
mock_audio_master = MagicMock()
mock_color_grading = MagicMock()
mock_progressive_preview = MagicMock()
mock_preview_report_generator = MagicMock()

# モックを sys.modules に登録
sys.modules["director_engine"] = MagicMock(brain=mock_brain, task_manager=mock_task_manager)
sys.modules["branding_manager"] = MagicMock(branding_manager=mock_branding_manager)
sys.modules["settings_manager"] = MagicMock(settings_manager=mock_settings_manager)
sys.modules["preview_engine"] = MagicMock(preview_engine=mock_preview_engine)
sys.modules["video_processor"] = MagicMock(video_processor=mock_video_processor, MOOD_SETTINGS={"elegant": MagicMock(name="elegant", transition="fade", telop_style="default")})
sys.modules["quality_gate_agent"] = MagicMock(quality_gate=mock_quality_gate)
sys.modules["draft_manager"] = MagicMock(draft_manager=mock_draft_manager)
sys.modules["cleanup_manager"] = MagicMock(cleanup_manager=mock_cleanup_manager)
sys.modules["decision_logger"] = MagicMock(decision_logger=mock_decision_logger)
sys.modules["task_store"] = MagicMock(task_store=mock_task_store)
sys.modules["project_archiver"] = MagicMock(project_archiver=mock_project_archiver)
sys.modules["subtitle_engine"] = MagicMock(WhisperTranscriber=mock_whisper_transcriber, SubtitleFormatter=mock_subtitle_formatter)
sys.modules["thumbnail_engine"] = MagicMock(generator=mock_thumbnail_generator)
sys.modules["websocket_handler"] = MagicMock(progress_manager=mock_progress_manager, broadcaster=mock_broadcaster)
sys.modules["audio_master"] = MagicMock(audio_master=mock_audio_master)
sys.modules["color_grading"] = MagicMock(color_grading=mock_color_grading)
sys.modules["progressive_preview"] = MagicMock(ProgressivePreview=mock_progressive_preview)
sys.modules["preview_report_generator"] = MagicMock(PreviewReportGenerator=mock_preview_report_generator)

# レンダーエンジンとグラフのモック
sys.modules["smart_cut_engine"] = MagicMock(render_smart_cut=MagicMock(return_value=True))
sys.modules["workflow_utils"] = MagicMock(render_subtitles=MagicMock())

# council_graph を invoke メソッドを持つモックにする
mock_council_graph = MagicMock()
mock_council_graph.invoke.return_value = {"messages": [], "synthesis": "mock synthesis"}
sys.modules["agents.graph"] = MagicMock(council_graph=mock_council_graph)

# ルーターもモック
sys.modules["manager_monitoring"] = MagicMock(router=MagicMock())
sys.modules["routers"] = MagicMock(dashboard_router=MagicMock(), approval_router=MagicMock(), philosophy_router=MagicMock())
sys.modules["log_manager"] = MagicMock(router=MagicMock())
sys.modules["error_reporter"] = MagicMock(router=MagicMock())
sys.modules["antigravity_api"] = MagicMock(router=MagicMock())

# list_models は list_gemini_models を公開
mock_list_models = MagicMock()
mock_list_models.list_gemini_models.return_value = ["gemini-1.5-pro", "gemini-1.5-flash"]
sys.modules["list_models"] = mock_list_models

# branding.history_manager もモック
mock_history = MagicMock()
sys.modules["branding.history_manager"] = MagicMock(history_manager=mock_history)

# branding_managerのモック設定
mock_branding_manager.user_model = {"interaction_history": {"collaborative_notes": "notes"}}
mock_branding_manager.get_evolution_log.return_value = {"philosophies": []}
mock_branding_manager.constitution = {
    "evolution_vision": "test vision",
    "brand_personality": {"keywords": ["test"]},
    "content_policy": ["policy1"]
}

# テスト対象モジュールのインポート
import importlib.util
module_path = archive_dir / "main.py"
spec = importlib.util.spec_from_file_location("main_archive", str(module_path))
main_mod = importlib.util.module_from_spec(spec)
sys.modules["main_archive"] = main_mod
spec.loader.exec_module(main_mod)

from fastapi.testclient import TestClient

@pytest.fixture
def client():
    return TestClient(main_mod.app)

def test_read_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"status": "Constitution Active", "app": "Antigravity Video Studio"}

def test_api_status(client):
    # GET /api/status
    response = client.get("/api/status")
    assert response.status_code == 200
    assert response.json() == {"interaction_history": {"collaborative_notes": "notes"}}

def test_api_analytics_sync(client):
    # POST /api/analytics/sync
    mock_branding_manager.process_analytics_update.return_value = {"status": "synchronized"}
    response = client.post("/api/analytics/sync")
    assert response.status_code == 200
    assert response.json() == {"status": "synchronized"}

def test_api_analytics_simulate(client):
    from branding.analytics_manager import analytics_manager
    analytics_manager.sim_add_views = MagicMock(return_value="sim_result")
    mock_branding_manager.process_analytics_update.return_value = "sync_result"
    response = client.post("/api/analytics/simulate?views=500")
    assert response.status_code == 200
    assert response.json() == {"simulation": "sim_result", "sync": "sync_result"}

def test_api_models(client):
    # GET /api/models
    response = client.get("/api/models")
    assert response.status_code == 200
    assert "models" in response.json()

def test_api_models_exception(client):
    with patch("main_archive.list_gemini_models", side_effect=Exception("API error")):
        response = client.get("/api/models")
        assert response.status_code == 500

def test_api_director_chat(client):
    # POST /api/director/chat
    mock_brain.chat_session.return_value = "hello from mock brain"
    response = client.post("/api/director/chat", json={"message": "hi", "history": []})
    assert response.status_code == 200
    assert response.json() == {"text": "hello from mock brain"}

def test_api_director_chat_exception(client):
    mock_brain.chat_session.side_effect = Exception("chat error")
    response = client.post("/api/director/chat", json={"message": "hi", "history": []})
    assert response.status_code == 500
    mock_brain.chat_session.side_effect = None

def test_api_director_generate_image(client):
    mock_brain.generate_image.return_value = [b"mock_bytes"]
    response = client.post("/api/director/generate-image", json={"prompt": "test"})
    assert response.status_code == 200
    assert response.json() == {"images": [base64.b64encode(b"mock_bytes").decode('utf-8')]}

def test_api_director_generate_image_exception(client):
    mock_brain.generate_image.side_effect = Exception("image error")
    response = client.post("/api/director/generate-image", json={"prompt": "test"})
    assert response.status_code == 500
    mock_brain.generate_image.side_effect = None

def test_api_director_generate_image_async(client):
    mock_task_manager.create_task.return_value = "task_123"
    response = client.post("/api/director/generate-image-async", json={"prompt": "test"})
    assert response.status_code == 200
    assert response.json() == {"status": "pending", "task_id": "task_123"}

def test_api_director_generate_image_async_exception(client):
    mock_task_manager.create_task.side_effect = Exception("async error")
    response = client.post("/api/director/generate-image-async", json={"prompt": "test"})
    assert response.status_code == 500
    mock_task_manager.create_task.side_effect = None

def test_api_director_tasks(client):
    mock_task_manager.get_task.return_value = {"status": "completed"}
    response = client.get("/api/director/tasks/task_123")
    assert response.status_code == 200
    assert response.json() == {"status": "completed"}

def test_api_director_tasks_not_found(client):
    mock_task_manager.get_task.return_value = None
    response = client.get("/api/director/tasks/task_123")
    assert response.status_code == 404

def test_api_director_analyze_script(client):
    mock_brain.analyze_script.return_value = '{"analysis": "good"}'
    response = client.post("/api/director/analyze-script", json={"full_text": "hello"})
    assert response.status_code == 200
    assert response.json() == {"analysis": "good"}

def test_api_director_analyze_script_exception(client):
    mock_brain.analyze_script.side_effect = Exception("analysis error")
    response = client.post("/api/director/analyze-script", json={"full_text": "hello"})
    assert response.status_code == 500
    mock_brain.analyze_script.side_effect = None

def test_api_director_quality_score(client):
    mock_brain.calculate_quality_score.return_value = '{"quality_score": 85.5}'
    response = client.post("/api/director/quality-score", json={"storyboard_plan": [], "biz_rank": "Novice"})
    assert response.status_code == 200
    assert response.json() == {"quality_score": 85.5}

def test_api_director_analyze_resources(client):
    mock_brain.analyze_resource_needs.return_value = '{"resources": "ok"}'
    response = client.post("/api/director/analyze-resources", json={"full_text": "hello"})
    assert response.status_code == 200
    assert response.json() == {"resources": "ok"}

def test_api_director_generate_report(client):
    mock_brain.generate_production_report.return_value = '{"report": "content"}'
    mock_branding_manager.ingest_report.return_value = "ingest_result"
    response = client.post("/api/director/generate-report", json={"storyboard_plan": [], "quality_score": {}, "biz_rank": "Novice"})
    assert response.status_code == 200
    assert response.json() == {"report": {"report": "content"}, "ingest": "ingest_result"}

def test_api_director_plan_storyboard(client):
    mock_brain.generate_storyboard_plan.return_value = '{"storyboard": []}'
    response = client.post("/api/director/plan-storyboard", json={"full_text": "hello", "scenes": [], "selected_style": {}})
    assert response.status_code == 200
    assert response.json() == {"storyboard": []}

def test_api_director_batch_generate(client):
    mock_task_manager.create_task.return_value = "task_123"
    response = client.post("/api/director/batch-generate", json={"scenes": [], "style_prompt": "prompt"})
    assert response.status_code == 200
    assert response.json() == {"task_id": "task_123", "status": "pending"}

def test_api_segments_get_not_found(client):
    with patch("os.path.exists", return_value=False):
        response = client.get("/api/segments")
        assert response.status_code == 404

def test_api_segments_get_success(client):
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data='{"segments": []}')):
            response = client.get("/api/segments")
            assert response.status_code == 200
            assert response.json() == {"segments": []}

def test_api_segments_post(client):
    with patch("builtins.open", mock_open()) as mock_file:
        response = client.post("/api/segments", json={"segments": []})
        assert response.status_code == 200
        assert response.json() == {"status": "success"}

def test_api_video_not_found(client):
    with patch("os.path.exists", return_value=False):
        response = client.get("/api/video")
        assert response.status_code == 404

def test_api_video_success(client):
    with patch("os.path.exists", return_value=True):
        with patch("main_archive.FileResponse", return_value="file_response_obj"):
            response = client.get("/api/video")
            assert response.status_code == 200

def test_api_director_state_get(client):
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data='{"scenes": [], "audioConfig": null}')):
            response = client.get("/api/director/state")
            assert response.status_code == 200
            assert response.json() == {"scenes": [], "audioConfig": None}

def test_api_director_state_post(client):
    with patch("builtins.open", mock_open()) as mock_file:
        response = client.post("/api/director/state", json={"scenes": [], "audioConfig": None})
        assert response.status_code == 200
        assert response.json() == {"status": "success"}

def test_api_archives_snapshots(client):
    mock_project_archiver.list_snapshots.return_value = ["snap1"]
    response = client.get("/api/archives/snapshots")
    assert response.status_code == 200
    assert response.json() == ["snap1"]

def test_api_archives_restore(client):
    mock_project_archiver.restore_snapshot.return_value = True
    response = client.post("/api/archives/restore/snap1")
    assert response.status_code == 200
    assert response.json() == {"status": "success", "message": "Snapshot snap1 restored."}

def test_api_archives_restore_failed(client):
    mock_project_archiver.restore_snapshot.side_effect = Exception("Restore failed")
    response = client.post("/api/archives/restore/snap1")
    assert response.status_code == 500
    mock_project_archiver.restore_snapshot.side_effect = None

def test_api_director_verify_quality(client):
    mock_brain.verify_production_quality.return_value = '{"verified": true}'
    response = client.post("/api/director/verify-quality", json={"full_text": "hello", "scenes": [], "segments": []})
    assert response.status_code == 200
    assert response.json() == {"verified": True}

def test_api_director_evolution(client):
    mock_branding_manager.get_evolution_log.return_value = {"evolution": ["evo1"]}
    response = client.get("/api/director/evolution")
    assert response.status_code == 200
    assert response.json() == {"evolution": ["evo1"]}

def test_api_collaboration_feedback(client):
    response = client.post("/api/collaboration/feedback", json={"suggestion_id": "s1", "action": "approve", "role": "admin"})
    assert response.status_code == 200
    assert response.json() == {"status": "success", "message": "Feedback from admin registered."}

def test_api_collaboration_journal_get(client):
    mock_branding_manager.user_model = {"interaction_history": {"collaborative_notes": "notes"}}
    response = client.get("/api/collaboration/journal")
    assert response.status_code == 200
    assert response.json() == {"notes": "notes"}

def test_api_collaboration_journal_post(client):
    mock_branding_manager.user_model = {"interaction_history": {"collaborative_notes": "notes"}}
    response = client.post("/api/collaboration/journal", json={"author": "admin", "content": "hello"})
    assert response.status_code == 200
    assert response.json()["status"] == "success"

def test_api_render(client):
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data='[]')):
            response = client.post("/api/render", json={"mode": "cut"})
            assert response.status_code == 200

def test_api_rhythm_split(client):
    response = client.post("/api/rhythm/split", json={"text": "hello"})
    assert response.status_code == 200
    assert "parts" in response.json()

def test_api_council_session(client):
    response = client.post("/api/council/session?query=test")
    assert response.status_code == 200
    assert "debate_flow" in response.json()

def test_api_council_decision(client):
    response = client.post("/api/council/decision", json={"resolution_id": "r1", "decision": "approve"})
    assert response.status_code == 200
    assert "status" in response.json()

def test_api_settings(client):
    mock_settings_manager.get_all_settings.return_value = {"s": 1}
    response = client.get("/api/settings")
    assert response.status_code == 200
    assert response.json() == {"s": 1}

def test_api_settings_identity(client):
    mock_settings_manager.update_identity.return_value = {"status": "success"}
    response = client.post("/api/settings/identity", json={"channel_name": "n", "target_audience": "a"})
    assert response.status_code == 200
    assert response.json() == {"status": "success"}

def test_api_settings_video(client):
    mock_settings_manager.update_video_source.return_value = {"status": "success"}
    response = client.post("/api/settings/video", files={"file": ("test.mp4", b"dummy content", "video/mp4")})
    assert response.status_code == 200
    assert response.json() == {"status": "success"}

def test_api_settings_reset(client):
    mock_settings_manager.reset_workspace.return_value = {"status": "success"}
    response = client.post("/api/settings/reset")
    assert response.status_code == 200
    assert response.json() == {"status": "success"}

def test_api_transcribe(client):
    response = client.post("/api/transcribe", json={"file_path": "f"})
    assert response.status_code == 200
    assert response.json()["status"] == "started"

def test_api_transcribe_status(client):
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data='{"status": "done"}')):
            response = client.get("/api/transcribe/status")
            assert response.status_code == 200
            assert response.json() == {"status": "done"}

def test_api_task(client):
    from task_store import task_store
    mock_task = MagicMock()
    mock_task.to_dict.return_value = {"id": "t1"}
    task_store.get_task.return_value = mock_task
    response = client.get("/api/task/t1")
    assert response.status_code == 200
    assert response.json() == {"id": "t1"}

def test_api_task_not_found(client):
    from task_store import task_store
    task_store.get_task.return_value = None
    response = client.get("/api/task/t1")
    assert response.status_code == 404

def test_api_tasks(client):
    from task_store import task_store
    task_store.list_tasks.return_value = [{"id": "t1"}]
    response = client.get("/api/tasks")
    assert response.status_code == 200
    assert "tasks" in response.json()

def test_api_subtitle_export(client):
    mock_subtitle_formatter.to_vtt.return_value = "vtt_content"
    response = client.post("/api/subtitle/export/vtt", json=[])
    assert response.status_code == 200
    assert response.content == b"vtt_content"

def test_api_subtitle_export_srt(client):
    mock_subtitle_formatter.to_srt.return_value = "srt_content"
    response = client.post("/api/subtitle/export/srt", json=[])
    assert response.status_code == 200
    assert response.content == b"srt_content"

def test_api_subtitle_export_invalid(client):
    response = client.post("/api/subtitle/export/invalid", json=[])
    assert response.status_code == 400

def test_api_thumbnail_generate(client):
    mock_thumbnail_generator.generate.return_value = [{"id": "thumb"}]
    response = client.post("/api/thumbnail/generate", json={"video_title": "t"})
    assert response.status_code == 200
    assert response.json()["status"] == "success"

def test_api_soul_vision(client):
    response = client.post("/api/soul/vision", json={"vision": "new vision"})
    assert response.status_code == 200
    assert response.json() == {"status": "success", "vision": "new vision"}

def test_api_soul_evolve(client):
    response = client.post("/api/soul/evolve", json={"event": {}})
    assert response.status_code == 200
    assert response.json() == {"status": "success"}

def test_api_council_resolutions(client):
    with patch("agents.resolution_tracker.resolution_tracker.list_resolutions", return_value=[]):
        response = client.get("/api/council/resolutions")
        assert response.status_code == 200
        assert response.json() == {"status": "success", "resolutions": []}

def test_api_preview_cleanup(client):
    response = client.post("/api/preview/cleanup")
    assert response.status_code == 200
    assert "Cleaned up previews" in response.json()["message"]

def test_api_video_color_presets(client):
    mock_color_grading.PRESETS = {"cinematic": "cine"}
    response = client.get("/api/video/color-presets")
    assert response.status_code == 200
    assert "presets" in response.json()

def test_api_preview_sessions(client):
    response = client.get("/api/preview/sessions")
    assert response.status_code == 200
    assert "sessions" in response.json()

def test_api_quality_threshold(client):
    response = client.get("/api/quality/threshold")
    assert response.status_code == 200
    assert "pass_threshold" in response.json()

def test_api_draft_stats(client):
    mock_draft_manager.get_stats.return_value = {"size": 0}
    response = client.get("/api/draft/stats")
    assert response.status_code == 200
    assert response.json() == {"size": 0}

def test_api_cleanup_preview(client):
    mock_cleanup_manager.preview_cleanup.return_value = {"files": []}
    response = client.get("/api/cleanup/preview")
    assert response.status_code == 200
    assert response.json() == {"files": []}

def test_api_storage_stats(client):
    mock_cleanup_manager.get_storage_stats.return_value = {"total": 0}
    response = client.get("/api/storage/stats")
    assert response.status_code == 200
    assert response.json() == {"total": 0}

def test_api_decision_stats(client):
    mock_decision_logger.get_stats.return_value = {"count": 1}
    response = client.get("/api/decision/stats")
    assert response.status_code == 200
    assert response.json() == {"count": 1}

def test_api_director_profile(client):
    mock_decision_logger.get_director_preferences.return_value = {"pref": 1}
    response = client.get("/api/director/profile")
    assert response.status_code == 200
    assert response.json() == {"pref": 1}

def test_api_evolution_status(client):
    response = client.get("/api/evolution/status")
    assert response.status_code == 200
    assert "constitution_version" in response.json()
