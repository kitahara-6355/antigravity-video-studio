"""
Legacy Management Router — ユニークエンドポイントのみ残存 (Phase C)

v4.0 ルーターと重複していたエンドポイントは削除済み。

残存ユニークエンドポイント:
- GET  /                                  — ルートステータス
- GET  /api/video                         — 動画ストリーミング
- GET  /api/archives/snapshots            — スナップショット一覧
- POST /api/archives/restore/{id}         — スナップショット復元
- POST /api/collaboration/feedback        — フィードバック記録
- GET  /api/collaboration/journal         — コラボノート取得
- POST /api/collaboration/journal         — コラボノート追加
- GET  /api/settings                      — 設定取得
- POST /api/settings/identity             — アイデンティティ更新
- POST /api/settings/video                — 動画ソース更新
- POST /api/settings/reset                — ワークスペースリセット
- POST /api/soul/vision                   — ビジョン設定
- POST /api/soul/evolve                   — 進化トリガー
- POST /api/cleanup/run                   — クリーンアップ実行
- GET  /api/cleanup/preview               — クリーンアッププレビュー
- GET  /api/storage/stats                 — ストレージ統計
- POST /api/process/start                 — 処理開始
- WS   /ws/progress                       — リアルタイム進捗

削除済み（v4.0 routers/ に移行済み）:
  /api/status, /api/analytics/*, /api/models, /api/segments,
  /api/quality/*, /api/draft/*, /api/prefinal/create, /api/final/create,
  /api/decision/*, /api/evolution/*, /api/dashboard/status,
  /api/approval, /api/philosophy/list
"""

import os
import json
import time
import logging
import anyio
import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, BackgroundTasks, UploadFile, File, WebSocket
from fastapi.responses import FileResponse
from pydantic import BaseModel

from branding_manager import branding_manager
from branding.history_manager import history_manager, EventType

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Management Legacy"])

# --- Path setup ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "src")
VIDEO_PATH = os.path.join(SRC_DIR, "sample_raw.mp4")

# --- Dashboard state ---
_dashboard_state = {
    "phase": "idle", "progress": 0,
    "current_step": "待機中", "preview_url": None
}

# --- Request Models ---
class FeedbackRequest(BaseModel):
    suggestion_id: str
    action: str
    role: str
    comment: str = ""

class JournalRequest(BaseModel):
    author: str
    content: str

class IdentityUpdate(BaseModel):
    channel_name: str
    target_audience: str

class CleanupRequest(BaseModel):
    category: str = None
    dry_run: bool = False

class ProcessStartRequest(BaseModel):
    video_path: str = ""



# ===== Root & Video =====

@router.get("/")
def read_root():
    return {"status": "Constitution Active", "app": "Antigravity Video Studio"}

@router.get("/api/video")
def get_video():
    """プレビュー用動画をストリーミングする（ユニーク）"""
    if not os.path.exists(VIDEO_PATH):
        raise HTTPException(status_code=404, detail="動画ファイルが見つかりません。")
    return FileResponse(VIDEO_PATH, media_type="video/mp4")


# ===== Archives =====

@router.get("/api/archives/snapshots")
def list_snapshots():
    """Returns a list of all project snapshots."""
    from project_archiver import project_archiver
    return project_archiver.list_snapshots()

@router.post("/api/archives/restore/{snapshot_id}")
def restore_snapshot(snapshot_id: str):
    """Restores a specific snapshot."""
    from project_archiver import project_archiver
    try:
        project_archiver.restore_snapshot(snapshot_id)
        return {"status": "success", "message": f"Snapshot {snapshot_id} restored."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===== Collaboration =====

@router.post("/api/collaboration/feedback")
async def process_feedback(feedback: FeedbackRequest):
    """Processes feedback from Admin or Owner."""
    try:
        history_manager.log_event(EventType.USER_INTERACTION, {
            "type": "COLLABORATIVE_FEEDBACK",
            "suggestion_id": feedback.suggestion_id,
            "action": feedback.action,
            "role": feedback.role,
            "comment": feedback.comment
        })
        xp_amount = 10 if feedback.action == "approve" else 5
        rank_type = "tech_rank" if feedback.role == "admin" else "biz_rank"
        await anyio.to_thread.run_sync(
            branding_manager.update_user_rank, rank_type, xp_amount
        )
        feedback_note = (
            f"Owner {feedback.action}ed with comment: {feedback.comment}"
            if feedback.role == "owner"
            else f"Admin {feedback.action}ed: {feedback.comment}"
        )
        await anyio.to_thread.run_sync(
            branding_manager.log_evolution, {
                "event": "COLLABORATIVE_DECISION",
                "feedback": feedback_note,
                "agenda_proposal": "Review collaborative synergy."
            }
        )
        return {"status": "success", "message": f"Feedback from {feedback.role} registered."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/collaboration/journal")
def get_journal():
    """Returns the collaborative notes history."""
    notes = branding_manager.user_model.get("interaction_history", {}).get("collaborative_notes", "No notes yet.")
    return {"notes": notes}

@router.post("/api/collaboration/journal")
async def add_journal_entry(req: JournalRequest):
    """Adds a collaborative note/decision to the user model."""
    try:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        new_note = f"[{timestamp}] {req.author.upper()}: {req.content}"
        current_history = branding_manager.user_model.get("interaction_history", {})
        current_notes = current_history.get("collaborative_notes", "")
        updated_notes = current_notes + "\n" + new_note if current_notes else new_note
        if "interaction_history" not in branding_manager.user_model:
            branding_manager.user_model["interaction_history"] = {}
        branding_manager.user_model["interaction_history"]["collaborative_notes"] = updated_notes
        branding_manager.update_user_model()
        branding_manager.log_evolution({
            "event": "COLLABORATIVE_NOTE",
            "author": req.author,
            "content": req.content,
            "agenda_proposal": "Align with new collaborative note."
        })
        return {"status": "success", "notes": updated_notes}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===== Settings =====

@router.get("/api/settings")
async def get_settings():
    """Returns all system settings."""
    from settings_manager import settings_manager
    return settings_manager.get_all_settings()

@router.post("/api/settings/identity")
async def update_identity(req: IdentityUpdate):
    """Updates Channel Name and Target Audience."""
    from settings_manager import settings_manager
    return settings_manager.update_identity(req.channel_name, req.target_audience)

@router.post("/api/settings/video")
async def upload_video_source(file: UploadFile = File(...)):
    """Replaces sample_raw.mp4 with uploaded file."""
    from settings_manager import settings_manager
    import shutil
    temp_path = f"temp_{file.filename}"
    try:
        def _write_file():
            with open(temp_path, "wb") as buffer:
                while True:
                    chunk = file.file.read(1024 * 1024)
                    if not chunk:
                        break
                    buffer.write(chunk)
        
        await anyio.to_thread.run_sync(_write_file)
        result = await anyio.to_thread.run_sync(
            settings_manager.update_video_source, temp_path, file.filename
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await file.close()

@router.post("/api/settings/reset")
async def reset_workspace():
    """Resets the workspace."""
    from settings_manager import settings_manager
    return settings_manager.reset_workspace()


# ===== Soul =====

@router.post("/api/soul/vision")
async def set_vision(request: Request):
    """ユーザーの動画に対する「想い・こだわり」をセットする。"""
    try:
        data = await request.json()
        branding_manager.current_vision = data.get("vision", "")
        return {"status": "success", "vision": branding_manager.current_vision}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/soul/evolve")
async def trigger_evolution(request: Request):
    """手動または自動で性格進化をトリガーする。"""
    try:
        data = await request.json()
        branding_manager.evolve_constitution(data.get("event", {}))
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===== Cleanup =====

@router.post("/api/cleanup/run")
async def run_cleanup(req: CleanupRequest = None):
    """一時ファイルをクリーンアップ"""
    from cleanup_manager import cleanup_manager
    try:
        result = cleanup_manager.cleanup(
            req.category if req else None,
            req.dry_run if req else False
        )
        return {
            "success": True,
            "deleted_count": len(result["deleted"]),
            "protected_count": len(result["protected"]),
            "freed_mb": round(result["freed_bytes"] / (1024 * 1024), 2),
            "dry_run": result["dry_run"],
            "details": result
        }
    except HTTPException:
        raise
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.get("/api/cleanup/preview")
async def preview_cleanup():
    """クリーンアップのプレビュー"""
    from cleanup_manager import cleanup_manager
    return cleanup_manager.preview_cleanup()

@router.get("/api/storage/stats")
async def get_storage_stats():
    """ストレージ使用状況を取得"""
    from cleanup_manager import cleanup_manager
    return cleanup_manager.get_storage_stats()


# ===== Process =====

@router.post("/api/process/start")
async def start_processing(background_tasks: BackgroundTasks, req: ProcessStartRequest = None):
    """ワンクリック動画処理開始"""
    try:
        _dashboard_state.update({
            "phase": "preflight", "progress": 0,
            "current_step": "プリフライトチェック中...", "preview_url": None
        })

        async def process_task():
            _dashboard_state["progress"] = 10
            await asyncio.sleep(1)
            _dashboard_state.update({"phase": "processing", "current_step": "動画を処理中..."})
            for i in range(10, 80, 10):
                _dashboard_state["progress"] = i
                await asyncio.sleep(0.5)
            _dashboard_state.update({
                "phase": "preview",
                "current_step": "プレビュー生成完了",
                "progress": 100,
                "preview_url": "/api/video"
            })

        background_tasks.add_task(process_task)
        return {"status": "started", "message": "処理を開始しました"}
    except HTTPException:
        raise
    except Exception as e:
        _dashboard_state.update({"phase": "error", "current_step": f"エラー: {str(e)}"})
        raise HTTPException(status_code=500, detail=str(e))


# ===== Thumbnail =====




# ===== WebSocket =====

@router.websocket("/ws/progress")
async def websocket_progress_endpoint(websocket: WebSocket):
    """リアルタイム進捗通知WebSocket"""
    from websocket_handler import handle_progress_websocket
    await handle_progress_websocket(websocket)
