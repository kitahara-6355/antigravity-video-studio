"""
Test coverage boost for legacy_management_router.py
Aiming for 100% coverage by targeting missing exception paths, upload, and websocket.
"""

import os
import sys
import shutil
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock, mock_open
from fastapi import HTTPException
from fastapi.testclient import TestClient

# Add backend directory to sys.path
_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

_services_dir = str(Path(__file__).resolve().parent.parent.parent / "services")
if _services_dir not in sys.path:
    sys.path.insert(0, _services_dir)

from fastapi import FastAPI
import sys
import routers.legacy_management_router
legacy_management_router = sys.modules['routers.legacy_management_router']
from routers.legacy_management_router import get_video
router = legacy_management_router.router

app = FastAPI()
app.include_router(router)
from routers.usage_router import thumbnail_router
app.include_router(thumbnail_router)


@pytest.fixture
def client():
    return TestClient(app)



# === 1. GET /api/video (L95 - Video file not found & success) ===

def test_get_video_not_found(client):
    with patch("os.path.exists", return_value=False):
        response = client.get("/api/video")
        assert response.status_code == 404
        assert response.json()["detail"] == "動画ファイルが見つかりません。"

def test_get_video_success():
    with patch("os.path.exists", return_value=True):
        response = get_video()
        assert response.media_type == "video/mp4"
        assert response.path.endswith("sample_raw.mp4")



# === 2. POST /api/archives/restore/{snapshot_id} (L112, L114 - Restore snapshot success & exception paths) ===

def test_restore_snapshot_success(client):
    with patch("project_archiver.project_archiver.restore_snapshot") as mock_restore:
        response = client.post("/api/archives/restore/snap_123")
        assert response.status_code == 200
        assert response.json() == {"status": "success", "message": "Snapshot snap_123 restored."}
        mock_restore.assert_called_once_with("snap_123")

def test_restore_snapshot_http_exception(client):
    with patch("project_archiver.project_archiver.restore_snapshot", side_effect=HTTPException(status_code=400, detail="Bad Snapshot")):
        response = client.post("/api/archives/restore/snap_bad")
        assert response.status_code == 400
        assert response.json()["detail"] == "Bad Snapshot"

def test_restore_snapshot_general_exception(client):
    with patch("project_archiver.project_archiver.restore_snapshot", side_effect=ValueError("General error")):
        response = client.post("/api/archives/restore/snap_error")
        assert response.status_code == 500
        assert "General error" in response.json()["detail"]


# === 3. POST /api/collaboration/feedback (L124-153 - Feedback request full coverage) ===

@pytest.mark.anyio
async def test_process_feedback_approve_admin(client):
    with patch("branding_manager.branding_manager.update_user_rank") as mock_rank, \
         patch("branding_manager.branding_manager.log_evolution") as mock_evolve, \
         patch("branding.history_manager.history_manager.log_event") as mock_log_event:
        
        response = client.post("/api/collaboration/feedback", json={
            "suggestion_id": "sug_001",
            "action": "approve",
            "role": "admin",
            "comment": "Nice work"
        })
        assert response.status_code == 200
        assert response.json() == {"status": "success", "message": "Feedback from admin registered."}
        mock_rank.assert_called_once_with("tech_rank", 10)
        mock_evolve.assert_called_once()
        mock_log_event.assert_called_once()

@pytest.mark.anyio
async def test_process_feedback_reject_owner(client):
    with patch("branding_manager.branding_manager.update_user_rank") as mock_rank, \
         patch("branding_manager.branding_manager.log_evolution") as mock_evolve, \
         patch("branding.history_manager.history_manager.log_event") as mock_log_event:
        
        response = client.post("/api/collaboration/feedback", json={
            "suggestion_id": "sug_002",
            "action": "reject",
            "role": "owner",
            "comment": "Need change"
        })
        assert response.status_code == 200
        assert response.json() == {"status": "success", "message": "Feedback from owner registered."}
        mock_rank.assert_called_once_with("biz_rank", 5)
        mock_evolve.assert_called_once()

def test_process_feedback_http_exception(client):
    with patch("branding.history_manager.history_manager.log_event", side_effect=HTTPException(status_code=400, detail="Invalid Feedback")):
        response = client.post("/api/collaboration/feedback", json={
            "suggestion_id": "sug_003",
            "action": "approve",
            "role": "admin"
        })
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid Feedback"

def test_process_feedback_general_exception(client):
    with patch("branding.history_manager.history_manager.log_event", side_effect=Exception("Database error")):
        response = client.post("/api/collaboration/feedback", json={
            "suggestion_id": "sug_003",
            "action": "approve",
            "role": "admin"
        })
        assert response.status_code == 500
        assert "Database error" in response.json()["detail"]


# === 4. POST /api/collaboration/journal (L171, L181-184 - Journal history init and exception handling) ===

def test_add_journal_entry_init_history(client):
    mock_user_model = {}
    with patch("branding_manager.branding_manager.user_model", mock_user_model), \
         patch("branding_manager.branding_manager.update_user_model") as mock_update, \
         patch("branding_manager.branding_manager.log_evolution") as mock_log:
        
        response = client.post("/api/collaboration/journal", json={
            "author": "admin",
            "content": "Initial note"
        })
        assert response.status_code == 200
        assert "Initial note" in response.json()["notes"]
        assert "interaction_history" in mock_user_model
        assert "collaborative_notes" in mock_user_model["interaction_history"]
        mock_update.assert_called_once()

def test_add_journal_entry_http_exception(client):
    with patch("branding_manager.branding_manager.update_user_model", side_effect=HTTPException(status_code=403, detail="Forbidden")):
        response = client.post("/api/collaboration/journal", json={
            "author": "admin",
            "content": "error note"
        })
        assert response.status_code == 403
        assert response.json()["detail"] == "Forbidden"

def test_add_journal_entry_general_exception(client):
    with patch("branding_manager.branding_manager.update_user_model", side_effect=ValueError("Save failed")):
        response = client.post("/api/collaboration/journal", json={
            "author": "admin",
            "content": "error note"
        })
        assert response.status_code == 500
        assert "Save failed" in response.json()["detail"]


# === 5. POST /api/settings/video (L204-231 - File upload, exceptions, and cleanup) ===

@pytest.mark.anyio
async def test_upload_video_source_success(client):
    with patch("settings_manager.settings_manager.update_video_source", return_value={"status": "updated"}) as mock_update, \
         patch("shutil.copyfileobj") as mock_copy, \
         patch("builtins.open", mock_open()):
         
        response = client.post("/api/settings/video", files={"file": ("test.mp4", b"dummy mp4 content", "video/mp4")})
        assert response.status_code == 200
        assert response.json() == {"status": "updated"}
        mock_update.assert_called_once()

@pytest.mark.anyio
async def test_upload_video_source_http_exception(client):
    # when update_video_source throws HTTPException, legacy_management_router does NOT call os.remove.
    with patch("settings_manager.settings_manager.update_video_source", side_effect=HTTPException(status_code=400, detail="Invalid video")):
        response = client.post("/api/settings/video", files={"file": ("test.mp4", b"dummy mp4 content", "video/mp4")})
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid video"

@pytest.mark.anyio
async def test_upload_video_source_general_exception(client):
    with patch("settings_manager.settings_manager.update_video_source", side_effect=RuntimeError("Disk write failed")):
        with patch("os.path.exists", return_value=True), \
             patch("os.remove") as mock_remove:
            response = client.post("/api/settings/video", files={"file": ("test.mp4", b"dummy mp4 content", "video/mp4")})
            assert response.status_code == 500
            assert "Disk write failed" in response.json()["detail"]
            mock_remove.assert_called_once()
            
@pytest.mark.anyio
async def test_upload_video_source_remove_exception(client):
    with patch("settings_manager.settings_manager.update_video_source", side_effect=RuntimeError("Disk write failed")):
        with patch("os.path.exists", return_value=True), \
             patch("os.remove", side_effect=Exception("Permission denied")):
            response = client.post("/api/settings/video", files={"file": ("test.mp4", b"dummy", "video/mp4")})
            assert response.status_code == 500


# === 6. POST /api/soul/vision (L249-252 - Exception handling) ===

@pytest.mark.anyio
async def test_set_vision_exceptions(client):
    with patch("fastapi.Request.json", new_callable=AsyncMock) as mock_json:
        mock_json.side_effect = HTTPException(status_code=400, detail="Custom HTTP error")
        response = client.post("/api/soul/vision", json={"vision": "test"})
        assert response.status_code == 400
        
    with patch("fastapi.Request.json", new_callable=AsyncMock) as mock_json:
        mock_json.side_effect = ValueError("Parsing failed")
        response = client.post("/api/soul/vision", json={"vision": "test"})
        assert response.status_code == 500
        assert "Parsing failed" in response.json()["detail"]


# === 7. POST /api/soul/evolve (L260, L262 - Success & Exception handling) ===

@pytest.mark.anyio
async def test_trigger_evolution_success(client):
    with patch("branding_manager.branding_manager.evolve_constitution") as mock_evolve:
        response = client.post("/api/soul/evolve", json={"event": {"type": "evolution"}})
        assert response.status_code == 200
        assert response.json() == {"status": "success"}
        mock_evolve.assert_called_once_with({"type": "evolution"})

@pytest.mark.anyio
async def test_trigger_evolution_exceptions(client):
    with patch("fastapi.Request.json", new_callable=AsyncMock) as mock_json:
        mock_json.side_effect = HTTPException(status_code=400, detail="Evolve HTTP error")
        response = client.post("/api/soul/evolve", json={})
        assert response.status_code == 400
        
    with patch("fastapi.Request.json", new_callable=AsyncMock) as mock_json:
        mock_json.side_effect = RuntimeError("Evolve internal error")
        response = client.post("/api/soul/evolve", json={})
        assert response.status_code == 500



# === 8. POST /api/cleanup/run (L272-289 - Default parameters & exception paths) ===

def test_run_cleanup_no_req_body(client):
    with patch("cleanup_manager.cleanup_manager.cleanup", return_value={
        "deleted": ["file1"], "protected": [], "freed_bytes": 1024*1024, "dry_run": False
    }) as mock_cleanup:
        response = client.post("/api/cleanup/run", json=None)
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["deleted_count"] == 1
        mock_cleanup.assert_called_once_with(None, False)

def test_run_cleanup_http_exception(client):
    with patch("cleanup_manager.cleanup_manager.cleanup", side_effect=HTTPException(status_code=400, detail="Cleanup failed")):
        response = client.post("/api/cleanup/run", json={"dry_run": True})
        assert response.status_code == 400

def test_run_cleanup_general_exception(client):
    with patch("cleanup_manager.cleanup_manager.cleanup", side_effect=RuntimeError("Delete failed")):
        response = client.post("/api/cleanup/run", json={"dry_run": True})
        assert response.status_code == 200
        assert response.json()["success"] is False
        assert response.json()["error"] == "Delete failed"


# === 9. POST /api/process/start (L331-335 - Process start exception handling) ===

def test_start_processing_http_exception(client):
    with patch("fastapi.BackgroundTasks.add_task", side_effect=HTTPException(status_code=400, detail="Task queue full")):
        response = client.post("/api/process/start", json={})
        assert response.status_code == 400
        
def test_start_processing_general_exception(client):
    with patch("fastapi.BackgroundTasks.add_task", side_effect=ValueError("Thread error")):
        response = client.post("/api/process/start", json={})
        assert response.status_code == 500
        assert "Thread error" in response.json()["detail"]


# === 10. WS /ws/progress (L343-344 - WebSocket endpoint verification) ===

@pytest.mark.anyio
async def test_websocket_progress():
    mock_ws = AsyncMock()
    with patch("websocket_handler.handle_progress_websocket", new_callable=AsyncMock) as mock_handle:
        from routers.legacy_management_router import websocket_progress_endpoint
        await websocket_progress_endpoint(mock_ws)
        mock_handle.assert_called_once_with(mock_ws)


# === 11. Additional tests for 100% coverage ===

def test_read_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"status": "Constitution Active", "app": "Antigravity Video Studio"}

def test_list_snapshots_success(client):
    with patch("project_archiver.project_archiver.list_snapshots", return_value=["snap1", "snap2"]) as mock_list:
        response = client.get("/api/archives/snapshots")
        assert response.status_code == 200
        assert response.json() == ["snap1", "snap2"]
        mock_list.assert_called_once()

def test_get_journal_no_notes(client):
    mock_user_model = {}
    with patch("branding_manager.branding_manager.user_model", mock_user_model):
        response = client.get("/api/collaboration/journal")
        assert response.status_code == 200
        assert response.json() == {"notes": "No notes yet."}

def test_get_journal_with_notes(client):
    mock_user_model = {"interaction_history": {"collaborative_notes": "Existing notes"}}
    with patch("branding_manager.branding_manager.user_model", mock_user_model):
        response = client.get("/api/collaboration/journal")
        assert response.status_code == 200
        assert response.json() == {"notes": "Existing notes"}

@pytest.mark.anyio
async def test_get_settings(client):
    with patch("settings_manager.settings_manager.get_all_settings", return_value={"theme": "dark"}) as mock_get:
        response = client.get("/api/settings")
        assert response.status_code == 200
        assert response.json() == {"theme": "dark"}
        mock_get.assert_called_once()

@pytest.mark.anyio
async def test_update_identity(client):
    with patch("settings_manager.settings_manager.update_identity", return_value={"status": "updated"}) as mock_update:
        response = client.post("/api/settings/identity", json={"channel_name": "TestChan", "target_audience": "Devs"})
        assert response.status_code == 200
        assert response.json() == {"status": "updated"}
        mock_update.assert_called_once_with("TestChan", "Devs")

@pytest.mark.anyio
async def test_reset_workspace(client):
    with patch("settings_manager.settings_manager.reset_workspace", return_value={"status": "reset"}) as mock_reset:
        response = client.post("/api/settings/reset")
        assert response.status_code == 200
        assert response.json() == {"status": "reset"}
        mock_reset.assert_called_once()

@pytest.mark.anyio
async def test_set_vision_success(client):
    from branding_manager import branding_manager
    old_vision = branding_manager.current_vision
    try:
        response = client.post("/api/soul/vision", json={"vision": "New Vision"})
        assert response.status_code == 200
        assert response.json() == {"status": "success", "vision": "New Vision"}
        assert branding_manager.current_vision == "New Vision"
    finally:
        branding_manager.current_vision = old_vision

@pytest.mark.anyio
async def test_preview_cleanup(client):
    with patch("cleanup_manager.cleanup_manager.preview_cleanup", return_value={"files": []}) as mock_preview:
        response = client.get("/api/cleanup/preview")
        assert response.status_code == 200
        assert response.json() == {"files": []}
        mock_preview.assert_called_once()

@pytest.mark.anyio
async def test_get_storage_stats(client):
    with patch("cleanup_manager.cleanup_manager.get_storage_stats", return_value={"used": 100}) as mock_stats:
        response = client.get("/api/storage/stats")
        assert response.status_code == 200
        assert response.json() == {"used": 100}
        mock_stats.assert_called_once()

@pytest.mark.anyio
async def test_start_processing_background_task(client):
    captured_tasks = []
    def mock_add_task(func, *args, **kwargs):
        captured_tasks.append((func, args, kwargs))

    with patch("fastapi.BackgroundTasks.add_task", side_effect=mock_add_task), \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        
        response = client.post("/api/process/start", json={})
        assert response.status_code == 200
        assert response.json() == {"status": "started", "message": "処理を開始しました"}
        
        assert len(captured_tasks) == 1
        task_func, task_args, task_kwargs = captured_tasks[0]
        
        await task_func(*task_args, **task_kwargs)
        
        import sys
        legacy_management_router = sys.modules['routers.legacy_management_router']
        assert legacy_management_router._dashboard_state["progress"] == 100
        assert legacy_management_router._dashboard_state["phase"] == "preview"
        assert legacy_management_router._dashboard_state["preview_url"] == "/api/video"



# === 12. POST /api/thumbnail/generate (Thumbnail generation & Quality validation & StageBoundAgent) ===

def test_legacy_thumbnail_generate_success(client, tmp_path):
    db_file = tmp_path / "legacy_thumb_ok.db"
    out_dir = tmp_path / "legacy_thumbs_ok"
    
    response = client.post("/api/thumbnail/generate", json={
        "task_id": "test_legacy_ok",
        "text": "Legacy OK",
        "width": 1280,
        "height": 720,
        "max_retries": 0,
        "db_path": str(db_file),
        "output_dir": str(out_dir)
    })
    
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["success"] is True
    assert res_data["task_id"] == "test_legacy_ok"
    assert res_data["status"] == "COMPLETED"
    assert res_data["result"]["width"] == 1280
    assert res_data["result"]["height"] == 720
    
    # 生成されたファイルの存在検証と破損チェック
    out_file = out_dir / "test_legacy_ok.png"
    assert out_file.exists()
    
    from PIL import Image
    with Image.open(out_file) as img:
        img.verify()
    with Image.open(out_file) as img:
        img.load()
        assert img.size == (1280, 720)


def test_legacy_thumbnail_invalid_resolution(client):
    # 解像度不足 (1280x720未満)
    response = client.post("/api/thumbnail/generate", json={
        "task_id": "test_legacy_low_res",
        "text": "Low Res",
        "width": 1024,
        "height": 576,
        "max_retries": 0
    })
    assert response.status_code == 400
    assert "Resolution must be at least 1280x720" in response.json()["detail"]


def test_legacy_thumbnail_invalid_aspect_ratio(client):
    # アスペクト比不正 (16:9以外)
    response = client.post("/api/thumbnail/generate", json={
        "task_id": "test_legacy_bad_aspect",
        "text": "Bad Aspect",
        "width": 1280,
        "height": 800,
        "max_retries": 0
    })
    assert response.status_code == 400
    assert "Aspect ratio must be 16:9" in response.json()["detail"]


def test_legacy_thumbnail_task_failure_and_retry(client, tmp_path):
    db_file = tmp_path / "legacy_thumb_fail.db"
    # 書き込み不可能な不正パスを指定して、タスク実行失敗を誘発
    out_dir = Path("C:/invalid_dir_?:*")
    
    response = client.post("/api/thumbnail/generate", json={
        "task_id": "test_legacy_fail",
        "text": "Legacy Fail",
        "width": 1280,
        "height": 720,
        "max_retries": 1,  # 1回リトライ（計2回試行）
        "db_path": str(db_file),
        "output_dir": str(out_dir)
    })
    
    assert response.status_code == 500
    assert "Thumbnail task failed" in response.json()["detail"]
    
    # DBの状態検証
    import sqlite3
    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.execute("SELECT status, retry_count, max_retries FROM tasks WHERE id = ?", ("test_legacy_fail",))
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "FAILED"
        assert row[1] == 1  # 1回リトライされたことの検証
        assert row[2] == 1
    finally:
        conn.close()

def test_legacy_thumbnail_generate_default_output_dir(client, tmp_path):
    db_file = tmp_path / "legacy_thumb_default.db"
    
    # デフォルトの出力先 backend/temp/legacy_thumbnails が使用されるように、output_dirを省略
    response = client.post("/api/thumbnail/generate", json={
        "task_id": "test_legacy_default",
        "text": "Legacy Default",
        "width": 1280,
        "height": 720,
        "max_retries": 0,
        "db_path": str(db_file)
    })
    
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["success"] is True
    assert res_data["task_id"] == "test_legacy_default"
    assert res_data["status"] == "COMPLETED"
    
    # 生成されたファイルの存在検証と破損チェック
    out_file = Path("backend/temp/legacy_thumbnails/test_legacy_default.png")
    assert out_file.exists()
    
    from PIL import Image
    with Image.open(out_file) as img:
        img.verify()
    
    # テスト後に作成されたファイルを削除
    if out_file.exists():
        try:
            os.remove(out_file)
        except Exception:
            pass
