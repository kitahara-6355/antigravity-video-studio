"""
Dashboard Router - ダッシュボードAPI

推奨タスク3: main.pyルーター分割
ダッシュボード関連のエンドポイントを独立モジュール化
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


class ProcessStartRequest(BaseModel):
    video_path: str = ""


# 処理状態（本番ではRedis使用推奨）
_dashboard_state = {
    "phase": "idle",
    "progress": 0,
    "current_step": "待機中",
    "preview_url": None
}


def get_state():
    """状態取得（外部からアクセス用）"""
    return _dashboard_state


def update_state(phase: str = None, progress: int = None, 
                 step: str = None, preview_url: str = None):
    """状態更新（外部からアクセス用）"""
    global _dashboard_state
    if phase is not None:
        _dashboard_state["phase"] = phase
    if progress is not None:
        _dashboard_state["progress"] = progress
    if step is not None:
        _dashboard_state["current_step"] = step
    if preview_url is not None:
        _dashboard_state["preview_url"] = preview_url


@router.get("/status")
async def get_dashboard_status():
    """統合ダッシュボードの現在の状態を取得"""
    return _dashboard_state


@router.post("/process/start")
async def start_processing(
    background_tasks: BackgroundTasks, 
    req: Optional[ProcessStartRequest] = None
):
    """ワンクリック動画処理開始"""
    global _dashboard_state
    
    try:
        _dashboard_state.clear()
        _dashboard_state.update({
            "phase": "preflight",
            "progress": 0,
            "current_step": "プリフライトチェック中...",
            "preview_url": None
        })
        
        def process_task():
            global _dashboard_state
            import time
            try:
                # Phase 1: Preflight
                _dashboard_state["progress"] = 10
                time.sleep(1)
                
                # Phase 2: Processing
                _dashboard_state["phase"] = "processing"
                _dashboard_state["current_step"] = "動画を処理中..."
                for i in range(10, 80, 10):
                    _dashboard_state["progress"] = i
                    time.sleep(0.5)
                
                # Phase 3: Preview Generation
                _dashboard_state["phase"] = "preview"
                _dashboard_state["current_step"] = "プレビュー生成完了"
                _dashboard_state["progress"] = 100
                _dashboard_state["preview_url"] = "/api/video"
            except (RuntimeError, ValueError, KeyError) as e:
                _dashboard_state["phase"] = "error"
                _dashboard_state["current_step"] = f"バックグラウンド処理エラー: {str(e)}"
        
        background_tasks.add_task(process_task)
        
        return {"status": "started", "message": "処理を開始しました"}
    except HTTPException:
        raise
    except (ValueError, KeyError, AttributeError) as e:
        _dashboard_state["phase"] = "error"
        _dashboard_state["current_step"] = f"エラー: {str(e)}"
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """ヘルスチェック"""
    return {"status": "healthy", "module": "dashboard"}
