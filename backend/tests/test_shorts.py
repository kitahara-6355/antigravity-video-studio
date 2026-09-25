import sys
import os
from unittest.mock import MagicMock

# Python 3.13 環境下での Pydantic/MCP 互換性ロードエラーを回避するため、
# テストで未使用の google.adk / google.genai を sys.modules でモックしインポートをバイパスする。
sys.modules['google.adk'] = MagicMock()
sys.modules['google.genai'] = MagicMock()
sys.modules['google.genai.types'] = MagicMock()

# **`google.genai` を差し替えるなら `errors` も差し替える。**
# 差し替えないと、同じ pytest プロセスで後から読まれるモジュールの
# `from google.genai.errors import APIError` が
# 「'google.genai' is not a package」で落ちる。巻き添えの相手は
# **バッチの区切り次第**で、testpaths を1ファイル触るだけで変わる
# （2026-08-26 に踏んだ）。
class _MockAPIError(Exception):
    def __init__(self, message="", code=None):
        super().__init__(message)
        self.message = message
        self.code = code


_mock_genai_errors = MagicMock()
_mock_genai_errors.APIError = _MockAPIError
sys.modules["google.genai.errors"] = _mock_genai_errors




import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

# ルーターをインポート
try:
    from backend.routers.shorts import router
except ImportError:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from backend.routers.shorts import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)

class DummyClip:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

class DummyResult:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

# Candidates
def test_extract_shorts_candidates_success():
    mock_generator = MagicMock()
    mock_generator.extract_shorts_candidates.return_value = {"candidates": ["clip1"]}
    with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_generator)}):
        response = client.post(
            "/api/shorts/candidates",
            json={
                "segments": [{"start": 0, "end": 10}],
                "video_duration_sec": 300,
                "video_id": "test_video",
            },
        )
        assert response.status_code == 200
        assert response.json() == {"candidates": ["clip1"]}
        mock_generator.extract_shorts_candidates.assert_called_once_with(
            segments=[{"start": 0, "end": 10}],
            video_duration_sec=300,
            video_id="test_video",
        )

def test_extract_shorts_candidates_http_exception():
    mock_generator = MagicMock()
    mock_generator.extract_shorts_candidates.side_effect = HTTPException(status_code=400, detail="Custom HTTP error")
    with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_generator)}):
        response = client.post(
            "/api/shorts/candidates",
            json={
                "segments": [{"start": 0, "end": 10}],
                "video_duration_sec": 300,
                "video_id": "test_video",
            },
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Custom HTTP error"

def test_extract_shorts_candidates_general_exception():
    mock_generator = MagicMock()
    mock_generator.extract_shorts_candidates.side_effect = RuntimeError("System crash")
    with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_generator)}):
        response = client.post(
            "/api/shorts/candidates",
            json={
                "segments": [{"start": 0, "end": 10}],
                "video_duration_sec": 300,
                "video_id": "test_video",
            },
        )
        assert response.status_code == 500
        assert "System crash" in response.json()["detail"]

# Generate
def test_generate_shorts_success():
    mock_generator = MagicMock()
    clip_mock = DummyClip(
        id="c1",
        title="Clip 1",
        highlight_type="hook",
        start_time=1.0,
        end_time=5.0,
        duration=4.0,
        output_path="/path/to/clip1.mp4",
        status="completed"
    )
    result_mock = DummyResult(
        total_clips=1,
        completed_clips=1,
        clips=[clip_mock],
        output_dir="/path/to/out",
        message="Generated successfully"
    )
    mock_generator.generate_from_highlights = AsyncMock(return_value=result_mock)
    
    with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_generator)}):
        response = client.post(
            "/api/shorts/generate",
            json={
                "video_path": "/raw/video.mp4",
                "highlights": [{"start": 1.0, "end": 5.0}],
                "task_id": "task-123"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["total_clips"] == 1
        assert data["completed_clips"] == 1
        assert data["clips"][0]["id"] == "c1"
        assert data["clips"][0]["title"] == "Clip 1"
        assert data["output_dir"] == "/path/to/out"
        assert data["message"] == "Generated successfully"

def test_generate_shorts_http_exception():
    mock_generator = MagicMock()
    mock_generator.generate_from_highlights = AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden action"))
    with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_generator)}):
        response = client.post(
            "/api/shorts/generate",
            json={
                "video_path": "/raw/video.mp4",
                "highlights": [{"start": 1.0, "end": 5.0}],
                "task_id": "task-123"
            }
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "Forbidden action"

def test_generate_shorts_general_exception():
    mock_generator = MagicMock()
    mock_generator.generate_from_highlights = AsyncMock(side_effect=RuntimeError("Database failure"))
    with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_generator)}):
        response = client.post(
            "/api/shorts/generate",
            json={
                "video_path": "/raw/video.mp4",
                "highlights": [{"start": 1.0, "end": 5.0}],
                "task_id": "task-123"
            }
        )
        assert response.status_code == 500
        assert "Database failure" in response.json()["detail"]

# List
def test_list_shorts_success():
    mock_generator = MagicMock()
    mock_generator.get_clip_list.return_value = [{"id": "c1", "status": "completed"}]
    with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_generator)}):
        response = client.get("/api/shorts/list?task_id=task-123")
        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "count": 1,
            "clips": [{"id": "c1", "status": "completed"}]
        }
        mock_generator.get_clip_list.assert_called_once_with(task_id="task-123")

def test_list_shorts_http_exception():
    mock_generator = MagicMock()
    mock_generator.get_clip_list.side_effect = HTTPException(status_code=404, detail="Task not found")
    with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_generator)}):
        response = client.get("/api/shorts/list?task_id=task-123")
        assert response.status_code == 404
        assert response.json()["detail"] == "Task not found"

def test_list_shorts_general_exception():
    mock_generator = MagicMock()
    mock_generator.get_clip_list.side_effect = RuntimeError("General list failure")
    with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_generator)}):
        response = client.get("/api/shorts/list?task_id=task-123")
        assert response.status_code == 500
        assert "General list failure" in response.json()["detail"]

# Export
def test_export_shorts_success():
    mock_generator = MagicMock()
    mock_generator.get_clip_list.return_value = [
        {"id": "clip_a", "status": "completed"},
        {"id": "clip_b", "status": "completed"}
    ]
    with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_generator)}):
        response = client.post(
            "/api/shorts/export",
            json={
                "clip_ids": ["clip_a"],
                "format": "mp4",
                "task_id": "task-abc"
            }
        )
        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "export_count": 1,
            "clips": [{"id": "clip_a", "status": "completed"}],
            "message": "1個のクリップをエクスポート準備完了"
        }

def test_export_shorts_no_clips():
    mock_generator = MagicMock()
    mock_generator.get_clip_list.return_value = [
        {"id": "clip_a", "status": "completed"},
        {"id": "clip_b", "status": "completed"}
    ]
    with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_generator)}):
        response = client.post(
            "/api/shorts/export",
            json={
                "clip_ids": ["clip_c"],
                "format": "mp4",
                "task_id": "task-abc"
            }
        )
        assert response.status_code == 200
        assert response.json() == {
            "success": False,
            "message": "指定されたクリップが見つかりませんでした"
        }

def test_export_shorts_http_exception():
    mock_generator = MagicMock()
    mock_generator.get_clip_list.side_effect = HTTPException(status_code=400, detail="Bad export request")
    with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_generator)}):
        response = client.post(
            "/api/shorts/export",
            json={
                "clip_ids": ["clip_a"],
                "format": "mp4",
                "task_id": "task-abc"
            }
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Bad export request"

def test_export_shorts_general_exception():
    mock_generator = MagicMock()
    mock_generator.get_clip_list.side_effect = RuntimeError("System error")
    with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_generator)}):
        response = client.post(
            "/api/shorts/export",
            json={
                "clip_ids": ["clip_a"],
                "format": "mp4",
                "task_id": "task-abc"
            }
        )
        assert response.status_code == 500
        assert "System error" in response.json()["detail"]

# Render — **R2-C1 で閉じた**（2026-09-25）
#
# ここには「どう書き出すか」を見るテストが8件あった（ffmpeg の有無・字幕の焼き込み・
# 失敗時の 500・import 退避）。**承認を1件も見ずに 1080x1920 の完成動画を書いていた経路**
# なので、R2-C1「承認していない動画は書き出せない」と正面から衝突する（2026-09-24 の
# gate-verifier が実際に 671,403 byte の mp4 を作って反証した）。経路を閉じたので
# それらの分岐は到達しない。**見るものは「書き出さないこと」に変わる。**
#
# Shorts は収益化の主軸（登録者集め）なので消したのではなく止めただけ。承認の流れへ
# 載せ直す工事は D-48（P1）。載せ直すときは「承認を通したら書き出す」テストがここに戻る。

def test_render_short_は承認を通していないと断る():
    response = client.post(
        "/api/shorts/render",
        json={"video_path": "/path/video.mp4", "start_sec": 0.0, "end_sec": 10.0}
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "承認" in detail and "approval_gate" in detail


def test_render_short_は入力の良し悪しで挙動を変えない():
    """**断るのが先。** end_sec の逆転（かつて 400）でも同じ 409 を返す。"""
    for body in (
        {"video_path": "/path/video.mp4", "start_sec": 10.0, "end_sec": 5.0},
        {"video_path": "/path/video.mp4", "start_sec": 0.0, "end_sec": 10.0,
         "subtitle_text": "hello:world's", "output_filename": "out.mp4"},
    ):
        assert client.post("/api/shorts/render", json=body).status_code == 409


def test_render_short_は_ffmpeg_を呼ばない():
    """**書き出しの部品を1つも動かさない。** かつてはここで ffmpeg を回していた。"""
    mock_ffmpeg = MagicMock()
    mock_ffmpeg.is_available.return_value = True
    mock_editor = MagicMock(ffmpeg=mock_ffmpeg)

    with patch.dict("sys.modules", {"video_editor_engine": MagicMock(video_editor=mock_editor)}):
        response = client.post(
            "/api/shorts/render",
            json={"video_path": "/path/video.mp4", "start_sec": 0.0, "end_sec": 10.0,
                  "output_filename": "test.mp4"}
        )

    assert response.status_code == 409
    mock_ffmpeg.run_command.assert_not_called()
    mock_ffmpeg.is_available.assert_not_called()

# Health Check
def test_health_check():
    response = client.get("/api/shorts/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "shorts_generator"}


# New error handling and thumbnail endpoint tests added during Phase 33 refactoring
def test_extract_shorts_candidates_value_error():
    mock_generator = MagicMock()
    mock_generator.extract_shorts_candidates.side_effect = ValueError("Invalid segments list")
    with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_generator)}):
        response = client.post(
            "/api/shorts/candidates",
            json={
                "segments": [],
                "video_duration_sec": 300,
                "video_id": "test_video",
            },
        )
        assert response.status_code == 400
        assert "Invalid segments list" in response.json()["detail"]

def test_extract_shorts_candidates_import_error():
    with patch.dict("sys.modules", {"services.shorts_generator": None}):
        response = client.post(
            "/api/shorts/candidates",
            json={
                "segments": [{"start": 0, "end": 10}],
                "video_duration_sec": 300,
                "video_id": "test_video",
            },
        )
        assert response.status_code == 500
        assert "Required service module not found" in response.json()["detail"]

def test_generate_shorts_value_error():
    mock_generator = MagicMock()
    mock_generator.generate_from_highlights = AsyncMock(side_effect=ValueError("Invalid highlight timestamps"))
    with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_generator)}):
        response = client.post(
            "/api/shorts/generate",
            json={
                "video_path": "/raw/video.mp4",
                "highlights": [{"start": 1.0, "end": 5.0}],
                "task_id": "task-123"
            }
        )
        assert response.status_code == 400
        assert "Invalid highlight timestamps" in response.json()["detail"]

def test_generate_shorts_import_error():
    with patch.dict("sys.modules", {"services.shorts_generator": None}):
        response = client.post(
            "/api/shorts/generate",
            json={
                "video_path": "/raw/video.mp4",
                "highlights": [{"start": 1.0, "end": 5.0}],
                "task_id": "task-123"
            }
        )
        assert response.status_code == 500
        assert "Service configuration or layout error" in response.json()["detail"]

def test_list_shorts_value_error():
    mock_generator = MagicMock()
    mock_generator.get_clip_list.side_effect = ValueError("Task ID cannot be empty")
    with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_generator)}):
        response = client.get("/api/shorts/list?task_id=task-123")
        assert response.status_code == 400
        assert "Task ID cannot be empty" in response.json()["detail"]

def test_list_shorts_import_error():
    with patch.dict("sys.modules", {"services.shorts_generator": None}):
        response = client.get("/api/shorts/list?task_id=task-123")
        assert response.status_code == 500
        assert "Required service module not found" in response.json()["detail"]

def test_export_shorts_value_error():
    mock_generator = MagicMock()
    mock_generator.get_clip_list.side_effect = ValueError("Invalid clip list request")
    with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_generator)}):
        response = client.post(
            "/api/shorts/export",
            json={
                "clip_ids": ["clip_a"],
                "format": "mp4",
                "task_id": "task-abc"
            }
        )
        assert response.status_code == 400
        assert "Invalid clip list request" in response.json()["detail"]

def test_export_shorts_import_error():
    with patch.dict("sys.modules", {"services.shorts_generator": None}):
        response = client.post(
            "/api/shorts/export",
            json={
                "clip_ids": ["clip_a"],
                "format": "mp4",
                "task_id": "task-abc"
            }
        )
        assert response.status_code == 500
        assert "Required service module not found" in response.json()["detail"]

@pytest.mark.asyncio
async def test_generate_thumbnail_api_success():
    mock_resolver = MagicMock()
    mock_agent = AsyncMock()
    
    mock_agent.register_task = AsyncMock()
    mock_agent.start = AsyncMock()
    
    # StopAsyncIteration を回避するため、リストのポップを行うクロージャを使用する
    status_list = ["READY", "RUNNING", "COMPLETED"]
    async def get_status(*args, **kwargs):
        if status_list:
            return status_list.pop(0)
        return "COMPLETED"
    mock_agent.get_task_status = AsyncMock(side_effect=get_status)
    mock_agent.stop = AsyncMock()
    
    import sqlite3
    import json
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = [json.dumps({"thumbnail_path": "/path/thumb.jpg"})]
    mock_conn.execute.return_value = mock_cursor
    
    with patch("usage_tracker.alert_system.ThumbnailResolver", return_value=mock_resolver),          patch("agents.stage_bound_agent.StageBoundAgent", return_value=mock_agent),          patch("sqlite3.connect", return_value=mock_conn):
         
        response = client.post(
            "/api/shorts/thumbnail",
            json={
                "video_path": "/path/video.mp4",
                "task_id": "task-thumb-1",
                "text": "Awesome Thumbnail",
                "db_path": "test_thumb.db"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["task_id"] == "task-thumb-1"
        assert data["status"] == "COMPLETED"
        assert data["result"] == {"thumbnail_path": "/path/thumb.jpg"}

@pytest.mark.asyncio
async def test_generate_thumbnail_api_failed():
    mock_resolver = MagicMock()
    mock_agent = AsyncMock()
    
    mock_agent.register_task = AsyncMock()
    mock_agent.start = AsyncMock()
    
    status_list = ["READY", "FAILED"]
    async def get_status(*args, **kwargs):
        if status_list:
            return status_list.pop(0)
        return "FAILED"
    mock_agent.get_task_status = AsyncMock(side_effect=get_status)
    mock_agent.stop = AsyncMock()
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = ["Quality score too low"]
    mock_conn.execute.return_value = mock_cursor
    
    with patch("usage_tracker.alert_system.ThumbnailResolver", return_value=mock_resolver),          patch("agents.stage_bound_agent.StageBoundAgent", return_value=mock_agent),          patch("sqlite3.connect", return_value=mock_conn):
         
        response = client.post(
            "/api/shorts/thumbnail",
            json={
                "video_path": "/path/video.mp4",
                "task_id": "task-thumb-2",
                "text": "Bad Thumbnail",
                "db_path": "test_thumb.db"
            }
        )
        assert response.status_code == 500
        assert "Thumbnail task failed: Quality score too low" in response.json()["detail"]
