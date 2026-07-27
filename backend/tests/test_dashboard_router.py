import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from fastapi import FastAPI, BackgroundTasks, HTTPException

# 対象モジュール
from routers.dashboard_router import router, get_state, ProcessStartRequest

app = FastAPI()
app.include_router(router)

client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_dashboard_state():
    """テストごとにダッシュボード状態を初期化"""
    state = get_state()
    state["phase"] = "idle"
    state["progress"] = 0
    state["current_step"] = "待機中"
    state["preview_url"] = None
    yield

def test_get_dashboard_status_endpoint():
    response = client.get("/api/dashboard/status")
    assert response.status_code == 200
    data = response.json()
    assert data["phase"] == "idle"
    assert data["progress"] == 0

def test_start_processing_success():
    # BackgroundTasks.add_taskをパッチして追加タスクをその場で同期実行する。
    def mock_add_task(func, *args, **kwargs):
        # time.sleepをモックして一瞬で完了させる
        with patch("time.sleep"):
            func(*args, **kwargs)
            
    with patch.object(BackgroundTasks, "add_task", side_effect=mock_add_task):
        response = client.post("/api/dashboard/process/start", json={"video_path": "test.mp4"})
        
    assert response.status_code == 200
    assert response.json() == {"status": "started", "message": "処理を開始しました"}
    
    # get_state()を使って再代入後の辞書を正しく取得・検証
    state = get_state()
    assert state["phase"] == "preview"
    assert state["progress"] == 100
    assert state["current_step"] == "プレビュー生成完了"
    assert state["preview_url"] == "/api/video"

def test_start_processing_http_exception():
    with patch.object(BackgroundTasks, "add_task") as mock_add:
        mock_add.side_effect = HTTPException(status_code=400, detail="Test HTTP error")
        response = client.post("/api/dashboard/process/start", json={"video_path": "test.mp4"})
        
    assert response.status_code == 400
    assert "Test HTTP error" in response.json()["detail"]

def test_start_processing_general_exception():
    with patch.object(BackgroundTasks, "add_task") as mock_add:
        mock_add.side_effect = ValueError("Some unexpected error")
        response = client.post("/api/dashboard/process/start", json={"video_path": "test.mp4"})
        
    assert response.status_code == 500
    assert "Some unexpected error" in response.json()["detail"]
    
    # get_state()を使って再代入後のエラー状態を検証
    state = get_state()
    assert state["phase"] == "error"
    assert "Some unexpected error" in state["current_step"]

def test_health_check_endpoint():
    response = client.get("/api/dashboard/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "module": "dashboard"}


def test_dashboard_reset_after_error():
    """エラー状態から再度処理を開始した際、状態が正常にリセットされるか検証"""
    state = get_state()
    state["phase"] = "error"
    state["current_step"] = "致命的なエラー"
    
    response = client.get("/api/dashboard/status")
    assert response.status_code == 200
    assert response.json()["phase"] == "error"
    assert response.json()["current_step"] == "致命的なエラー"
    
    with patch.object(BackgroundTasks, "add_task"):
        response = client.post("/api/dashboard/process/start", json={"video_path": "test.mp4"})
    assert response.status_code == 200
    
    response = client.get("/api/dashboard/status")
    assert response.status_code == 200
    data = response.json()
    assert data["phase"] == "preflight"
    assert data["progress"] == 0

def test_background_task_exception_handling():
    """バックグラウンドタスク実行中に例外が発生した場合、状態が error に遷移するか検証"""
    def mock_add_task(func, *args, **kwargs):
        with patch("time.sleep", side_effect=RuntimeError("Background processing failed")):
            try:
                func(*args, **kwargs)
            except Exception:
                pass
                
    with patch.object(BackgroundTasks, "add_task", side_effect=mock_add_task):
        response = client.post("/api/dashboard/process/start", json={"video_path": "test.mp4"})
        
    assert response.status_code == 200
    
    state = get_state()
    assert state["phase"] == "error"
    assert "Background processing failed" in state["current_step"]
