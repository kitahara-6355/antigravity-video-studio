"""
Approval Router - 承認APIルーター

推奨タスク3: main.pyルーター分割
承認/却下フローのエンドポイントを独立モジュール化
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
import logging
import sys
import os

# パス追加（backendディレクトリをモジュールパスに追加）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from branding.history_manager import history_manager, EventType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/approval", tags=["Approval"])


class ApprovalRequest(BaseModel):
    approved: bool
    feedback: str = ""
    timestamp: str = ""
    session_id: str = ""


class DecisionRequest(BaseModel):
    session_id: str
    decision: str  # "approved" | "rejected"
    feedback: str = ""


@router.post("")
async def process_approval(req: ApprovalRequest):
    """承認/却下処理"""
    try:
        if not req.session_id or not req.session_id.strip():
            raise HTTPException(
                status_code=400,
                detail="session_id is required and cannot be empty or whitespace."
            )
        if req.approved:
            # 承認ログを記録
            history_manager.log_event(EventType.USER_INTERACTION, {
                "type": "DASHBOARD_APPROVAL",
                "approved": True,
                "session_id": req.session_id,
                "timestamp": req.timestamp
            })
            
            return {
                "status": "approved", 
                "message": "承認されました。処理を完了します。"
            }
        else:
            # 却下ログを記録
            history_manager.log_event(EventType.USER_INTERACTION, {
                "type": "DASHBOARD_REJECTION",
                "approved": False,
                "session_id": req.session_id,
                "feedback": req.feedback,
                "timestamp": req.timestamp
            })
            
            return {
                "status": "rejected", 
                "message": "却下されました。修正を適用します。", 
                "feedback": req.feedback
            }
    except HTTPException:
        raise
    except (ValueError, TypeError) as e:
        logger.error(f"Validation error in process_approval: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))
    except (RuntimeError, ValueError, TypeError, KeyError, AttributeError, OSError) as e:
        logger.error(f"Approval error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/decision")
async def record_decision(req: DecisionRequest):
    """判定を記録（レガシー互換）"""
    try:
        if not req.session_id or not req.session_id.strip():
            raise HTTPException(
                status_code=400,
                detail="session_id is required and cannot be empty or whitespace."
            )
        if req.decision not in ("approved", "rejected"):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid decision: '{req.decision}'. Must be 'approved' or 'rejected'."
            )
        history_manager.log_event(EventType.USER_INTERACTION, {
            "type": "DECISION",
            "session_id": req.session_id,
            "decision": req.decision,
            "feedback": req.feedback
        })
        
        return {
            "status": "recorded",
            "decision": req.decision,
            "session_id": req.session_id
        }
    except HTTPException:
        raise
    except (ValueError, TypeError) as e:
        logger.error(f"Validation error in record_decision: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))
    except (RuntimeError, ValueError, TypeError, KeyError, AttributeError, OSError) as e:
        logger.error(f"Decision recording error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
async def get_approval_history(limit: int = Query(10, ge=1, le=100)):
    """承認履歴を取得"""
    try:
        events = history_manager.get_recent_events(
            event_type=EventType.USER_INTERACTION,
            limit=limit
        )
        return {"history": events}
    except HTTPException:
        raise
    except (ValueError, TypeError) as e:
        logger.error(f"Validation error in get_approval_history: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))
    except (RuntimeError, ValueError, TypeError, KeyError, AttributeError, OSError) as e:
        logger.error(f"History retrieval error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
