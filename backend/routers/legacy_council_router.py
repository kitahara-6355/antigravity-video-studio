"""
Legacy Council Router — ユニークエンドポイントのみ残存 (Phase C)

v4.0 collaboration.py と重複していたエンドポイントは削除済み。

残存ユニークエンドポイント:
- GET  /api/council/resolutions               — 議案一覧
- POST /api/council/resolutions/{id}/vote     — 投票記録
- POST /api/council/resolutions/{id}/gavel    — 議長決済
- POST /api/council/resolutions/thumbnail-proposal — サムネイル評価自動起票

削除済み（v4.0 routers/collaboration.py に移行済み）:
  /api/council/session, /api/council/decision
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Dict, Any

from branding_manager import branding_manager

router = APIRouter(tags=["Council Legacy"])


# /api/council/session と /api/council/decision は v4.0 collaboration.py に移行済み


@router.get("/api/council/resolutions")
async def list_resolutions(status: str = None):
    """議案一覧を取得"""
    from agents.resolution_tracker import resolution_tracker, ResolutionStatus
    try:
        status_filter = None
        if status:
            try:
                status_filter = ResolutionStatus(status)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
        resolutions = resolution_tracker.list_resolutions(status=status_filter)
        return {"status": "success", "resolutions": resolutions}
    except HTTPException:
        raise
    except (RuntimeError, ValueError, AttributeError, TypeError, KeyError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/council/resolutions/{resolution_id}/vote")
async def vote_resolution(resolution_id: str, request: Request):
    """エージェントの投票を記録"""
    from agents.resolution_tracker import resolution_tracker
    import json
    try:
        # 1. 議案の存在確認
        resolution = resolution_tracker.get_resolution(resolution_id)
        if not resolution:
            raise HTTPException(status_code=404, detail=f"Resolution {resolution_id} not found")

        # 2. JSONデータのパースと辞書チェック
        try:
            data = await request.json()
        except (json.JSONDecodeError, TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="JSON body must be a dictionary")

        # 3. フィールド検証
        agent_name = data.get("agent_name")
        vote = data.get("vote")

        if not agent_name or not isinstance(agent_name, str):
            raise HTTPException(status_code=400, detail="agent_name must be a non-empty string")
        
        if vote not in ("APPROVE", "REJECT"):
            raise HTTPException(status_code=400, detail="vote must be 'APPROVE' or 'REJECT'")

        # 4. 投票記録
        resolution_tracker.record_vote(resolution_id, agent_name, vote)
        return {"status": "success"}
    except HTTPException:
        raise
    except (RuntimeError, ValueError, AttributeError, TypeError, KeyError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/council/resolutions/{resolution_id}/gavel")
async def apply_gavel(resolution_id: str, request: Request):
    """議長決済（Gavel Ceremony）"""
    from agents.resolution_tracker import resolution_tracker
    import json
    try:
        # 1. 議案の存在確認
        resolution = resolution_tracker.get_resolution(resolution_id)
        if not resolution:
            raise HTTPException(status_code=404, detail=f"Resolution {resolution_id} not found")

        # 2. JSONデータのパースと辞書チェック
        try:
            data = await request.json()
        except (json.JSONDecodeError, TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="JSON body must be a dictionary")

        # 3. フィールド検証 (AUTO決済サポート)
        decision = data.get("decision")
        if decision == "AUTO":
            proposed_changes = resolution.proposed_changes or {}
            if proposed_changes.get("type") == "thumbnail_proposal" and proposed_changes.get("auto_approve"):
                decision = "APPROVE"
            else:
                raise HTTPException(
                    status_code=400,
                    detail="AUTO decision is only allowed for eligible thumbnail proposals with high quality score"
                )
        elif decision not in ("APPROVE", "REJECT"):
            raise HTTPException(status_code=400, detail="decision must be 'APPROVE', 'REJECT' or 'AUTO'")

        # 4. 議長決済の適用
        success = resolution_tracker.apply_gavel(resolution_id, decision)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to apply gavel decision")

        if decision == "APPROVE":
            branding_manager.evolve_constitution({
                "type": "council_resolution",
                "resolution_id": resolution_id,
                "value": resolution.title,
                "changes": resolution.proposed_changes
            })

        return {"status": "success", "decision": decision}
    except HTTPException:
        raise
    except (RuntimeError, ValueError, AttributeError, TypeError, KeyError) as e:
        raise HTTPException(status_code=500, detail=str(e))


class ThumbnailProposalRequest(BaseModel):
    session_id: str
    thumbnail_path: str
    quality_score: float = Field(..., ge=0.0, le=100.0)
    standards_compliance: Dict[str, bool]


@router.post("/api/council/resolutions/thumbnail-proposal")
async def propose_thumbnail(request: ThumbnailProposalRequest):
    """サムネイルの品質評価議案を自動起票"""
    from agents.resolution_tracker import resolution_tracker, ResolutionStatus
    try:
        title = f"Thumbnail Auto Proposal: {request.thumbnail_path}"
        description = (
            f"Automated quality evaluation for thumbnail {request.thumbnail_path}. "
            f"Quality Score: {request.quality_score}"
        )
        
        # 80点以上且つ全ての基準(NHK・YouTuber等)をクリアしている場合に自動決済対象とする
        auto_approve = request.quality_score >= 80.0 and all(request.standards_compliance.values())
        
        proposed_changes = {
            "type": "thumbnail_proposal",
            "thumbnail_path": request.thumbnail_path,
            "quality_score": request.quality_score,
            "standards_compliance": request.standards_compliance,
            "auto_approve": auto_approve
        }
        
        resolution = resolution_tracker.create_resolution(
            title=title,
            description=description,
            proposed_changes=proposed_changes,
            session_id=request.session_id
        )
        
        if auto_approve:
            resolution_tracker.update_status(resolution.id, ResolutionStatus.VOTING)
            
        return {
            "status": "success",
            "resolution_id": resolution.id,
            "auto_approve_eligible": auto_approve,
            "current_status": resolution.status
        }
    except HTTPException:
        raise
    except (RuntimeError, ValueError, AttributeError, TypeError, KeyError) as e:
        raise HTTPException(status_code=500, detail=str(e))
