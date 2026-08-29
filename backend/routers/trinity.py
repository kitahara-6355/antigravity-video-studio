"""
Trinity Router - ステータス・アナリティクス・進化関連エンドポイント

Sprint 4.1.4: EvolutionSyncService経由にリファクタリング
設計書: sprint_41_design.md §Q3 仮説B
"""
from fastapi import APIRouter, HTTPException, Body

router = APIRouter(prefix="/api", tags=["trinity"])


# **チャンネル統計は YouTube に繋がっていない**（R1.5-C4・gate-verifier 6周目 指摘2）。
# 出所は `branding/analytics_manager.py` の `mock_my_stats`（登録者 150・総再生 4,500）。
# `admin_channel_router` の `watch_time_hours: 15200` を直したのと同じクラスが、
# **本番の別ルーターに無印で残っていた。**
# 台帳: `backend/config/feature_gaps.json` の `channel_stats`
ANALYTICS_DATA_SOURCE = {
    "data_source": "sample",
    "is_real": False,
    "note": "**YouTube から取得した実績ではありません。**Analytics API に一度も"
            "接続していません。収益化の到達度の判断に使わないでください",
}


def _register_router_debt(line_number: int, pattern: str, error_msg: str, endpoint_name: str):
    import sys
    import logging
    import traceback
    
    logger = logging.getLogger(__name__)
    exc_type, exc_value, exc_tb = sys.exc_info()
    
    # サーバーログに例外スタックトレースを出力
    if exc_value:
        logger.error(f"Unexpected error in {endpoint_name}: {error_msg}", exc_info=(exc_type, exc_value, exc_tb))
        tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        full_notes = f"Unexpected error in {endpoint_name}: {error_msg}\nTraceback:\n{tb_str}"
    else:
        logger.error(f"Unexpected error in {endpoint_name}: {error_msg}")
        full_notes = f"Unexpected error in {endpoint_name}: {error_msg}"

    try:
        from pathlib import Path
        from agents.memory.technical_debt import TechnicalDebtStore
        store = TechnicalDebtStore(Path(__file__).parent.parent / "agents/memory")
        store.register_debt(
            category="CRITICAL_ROUTER",
            file_path="routers/trinity.py",
            line_number=line_number,
            pattern=pattern,
            cause_pattern="DP-01",
            fix_pattern="except HTTPException: raise を配置",
            registered_by="thumbnail_task",
            notes=full_notes,
        )
    except Exception as e:
        logger.error(f"Failed to register TDR debt: {e}")



@router.get("/status")
async def get_trinity_status():
    """Returns the full User Model including Ranks and Analytics."""
    from branding_manager import branding_manager
    try:
        model = branding_manager.user_model
        if model is None:
            raise HTTPException(status_code=404, detail="User Model not found")
        return model
    except HTTPException:
        raise
    except (AttributeError, ValueError, TypeError, ImportError, OSError) as e:
        _register_router_debt(44, "except (AttributeError, ValueError, TypeError, ImportError, OSError) as e:", str(e), "get_trinity_status")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")


@router.post("/analytics/sync")
async def sync_analytics():
    """Triggers the Real-World Link: Analytics -> Biz Rank update.

    **「Real-World Link」と言っているが、実世界には繋がっていない**
    （R1.5-C4・gate-verifier 6周目 指摘2）。出所は
    `branding/analytics_manager.py` の `mock_my_stats` で、YouTube Analytics に
    一度も接続していない。**登録者数と総再生数は収益化の到達度そのもの**なので、
    包みの側でも名乗る。台帳: `backend/config/feature_gaps.json` の `channel_stats`
    """
    from branding_manager import branding_manager
    try:
        result = branding_manager.process_analytics_update()
        if result is None:
            raise HTTPException(status_code=500, detail="Failed to process analytics update")
        return {**ANALYTICS_DATA_SOURCE, **result}
    except HTTPException:
        raise
    except Exception as e:
        _register_router_debt(60, "except Exception as e:", str(e), "sync_analytics")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")


@router.post("/analytics/simulate")
async def simulate_analytics(views: int = 1000):
    """Debug: Simulates obtaining views.

    **注入した数字が `sync` から実績の顔で出てくる**（R1.5-C4・6周目 指摘2）。
    `views=500000` を入れると `sync` の `stats.subscribers` が 5,150 になり、
    **収益化の閾値（登録者1,000人）を任意に超えた数字が通っていた。**
    """
    if views < 0:
        raise HTTPException(status_code=400, detail="Views must be non-negative")
    if views > 1000000000:
        raise HTTPException(status_code=400, detail="Views parameter too large")
    
    from branding.analytics_manager import analytics_manager
    from branding_manager import branding_manager
    try:
        result = analytics_manager.sim_add_views(views)
        sync_result = branding_manager.process_analytics_update()
        return {
            **ANALYTICS_DATA_SOURCE,
            "simulation": result,
            "sync": sync_result
        }
    except HTTPException:
        raise
    except Exception as e:
        _register_router_debt(84, "except Exception as e:", str(e), "simulate_analytics")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")


@router.get("/models")
async def get_models():
    """Returns available Gemini models via ModelRegistry (§14.1)."""
    from list_models import list_gemini_models
    try:
        models = list_gemini_models()
        if models is None:
            raise HTTPException(status_code=404, detail="No models found")
        return {"models": models}
    except HTTPException:
        raise
    except Exception as e:
        _register_router_debt(100, "except Exception as e:", str(e), "get_models")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")


@router.get("/evolution")
async def get_evolution():
    """Returns the qualitative growth narrative log.

    **`post_publish_feedbacks` には作り物の「実績」が焼き付いている**
    （R1.5-C4・gate-verifier 6周目 指摘1）。`YOUTUBE_API_MODE=mock` 時代に
    `random` で組み立てた CTR・維持率・再生数が12件、`actual_*` の名前で
    `evolution_log.json`（Git 追跡下）に残っている。書き込みは止めたが、
    **既にある行は消さずに印を付ける**（記録は残す・ペルソナ #23 選択的保持）。
    `is_real: true` が無い行は作り物とみなす（fail-closed）。
    """
    from branding_manager import branding_manager
    try:
        log = branding_manager.get_evolution_log_for_display()
        if log is None:
            raise HTTPException(status_code=404, detail="Evolution log not found")
        return log
    except HTTPException:
        raise
    except Exception as e:
        _register_router_debt(116, "except Exception as e:", str(e), "get_evolution")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")


@router.post("/evolution/sync")
async def sync_evolution():
    """全ての自動進化処理を実行 — EvolutionSyncService経由

    Sprint 4.1.4: trinity.pyを薄いプロキシに変更
    旧実装: decision_logger/branding_manager を直接呼出し
    新実装: EvolutionSyncService.sync_all() に統合委譲
    """
    from services.evolution_sync_service import EvolutionSyncService
    try:
        service = EvolutionSyncService()
        result = service.sync_all()
        if result is None:
            raise HTTPException(status_code=500, detail="Failed to sync evolution")
        return result
    except HTTPException:
        raise
    except Exception as e:
        _register_router_debt(138, "except Exception as e:", str(e), "sync_evolution")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")


@router.get("/evolution/status")
async def get_evolution_status():
    """自動進化システムのステータスを取得 — EvolutionSyncService経由

    Sprint 4.1.4: ロジックをEvolutionSyncServiceに移譲
    """
    from services.evolution_sync_service import EvolutionSyncService
    try:
        service = EvolutionSyncService()
        status = service.get_evolution_status()
        if status is None:
            raise HTTPException(status_code=404, detail="Evolution status not found")
        return status
    except HTTPException:
        raise
    except Exception as e:
        _register_router_debt(158, "except Exception as e:", str(e), "get_evolution_status")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")


# ------------------------------------------------------------------
# Sprint 4.2.2: 哲学提案エンドポイント
# 設計書: sprint_42_soul_evolution_design.md §2.6
# ------------------------------------------------------------------

@router.get("/evolution/proposals")
async def get_evolution_proposals():
    """哲学候補一覧を取得 (S422-06)

    Sprint 4.2.2: PhilosophyProposalService経由
    """
    from services.philosophy_proposal_service import PhilosophyProposalService
    try:
        service = PhilosophyProposalService()
        proposals = service.get_pending_proposals()
        if proposals is None:
            return []
        return [
            {
                "proposal_id": p.proposal_id,
                "content": p.content,
                "source_summary": p.source_summary,
                "generated_at": p.generated_at,
                "status": p.status,
                "user_edit": p.user_edit,
            }
            for p in proposals
        ]
    except HTTPException:
        raise
    except Exception as e:
        _register_router_debt(193, "except Exception as e:", str(e), "get_evolution_proposals")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")


@router.post("/evolution/proposals/{proposal_id}/approve")
async def approve_evolution_proposal(proposal_id: str, body: dict | None = Body(None)):
    """哲学候補を承認 (S422-07)

    Sprint 4.2.2: SC-03 哲学追記パスはapprove_proposal()経由のみ
    """
    if not proposal_id or proposal_id.strip() == "":
        raise HTTPException(status_code=400, detail="Invalid proposal_id")
    from services.philosophy_proposal_service import PhilosophyProposalService
    try:
        service = PhilosophyProposalService()
        edited_text = (body or {}).get("edited_text")
        result = service.approve_proposal(proposal_id, edited=edited_text)
        if not result:
            raise HTTPException(status_code=404, detail=f"Proposal {proposal_id} not found or failed to approve")
        return {"approved": result, "proposal_id": proposal_id}
    except HTTPException:
        raise
    except Exception as e:
        _register_router_debt(216, "except Exception as e:", str(e), "approve_evolution_proposal")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")


@router.post("/evolution/proposals/{proposal_id}/reject")
async def reject_evolution_proposal(proposal_id: str, body: dict | None = Body(None)):
    """哲学候補を却下 (S422-05)

    Sprint 4.2.2: 却下理由をdecision_logに記録
    """
    if not proposal_id or proposal_id.strip() == "":
        raise HTTPException(status_code=400, detail="Invalid proposal_id")
    from services.philosophy_proposal_service import PhilosophyProposalService
    try:
        service = PhilosophyProposalService()
        reason = (body or {}).get("reason", "理由未記入")
        result = service.reject_proposal(proposal_id, reason=reason)
        if not result:
            raise HTTPException(status_code=404, detail=f"Proposal {proposal_id} not found or failed to reject")
        return {"rejected": result, "proposal_id": proposal_id}
    except HTTPException:
        raise
    except Exception as e:
        _register_router_debt(239, "except Exception as e:", str(e), "reject_evolution_proposal")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")


# ------------------------------------------------------------------
# Sprint 4.2.3: 進化ダッシュボードエンドポイント
# 設計書: sprint_42_soul_evolution_design.md §2.6
# ------------------------------------------------------------------

@router.get("/evolution/dashboard")
async def get_evolution_dashboard():
    """進化ダッシュボードデータを取得 (S423-05)

    Sprint 4.2.3: EvolutionSyncService.get_dashboard_data()に委譲
    trigger_status + proposals + trust + philosophy_timeline + trigger_history を集約
    """
    from services.evolution_sync_service import EvolutionSyncService
    try:
        service = EvolutionSyncService()
        data = service.get_dashboard_data()
        if data is None:
            raise HTTPException(status_code=404, detail="Dashboard data not found")
        return data
    except HTTPException:
        raise
    except Exception as e:
        _register_router_debt(265, "except Exception as e:", str(e), "get_evolution_dashboard")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")


# ------------------------------------------------------------------
# Sprint 4.2.5: トリガーステータスエンドポイント
# 設計書: sprint_425_medium_deficiency_design.md §4.5 (M-05)
# ------------------------------------------------------------------

@router.get("/evolution/triggers")
async def get_evolution_triggers():
    """トリガー状態一覧を取得 (M-05 / S421-06設計)

    Sprint 4.2.5: EvolutionTriggerService.get_trigger_status()に委譲
    """
    from services.evolution_trigger_service import EvolutionTriggerService
    try:
        service = EvolutionTriggerService()
        status = service.get_trigger_status()
        if status is None:
            raise HTTPException(status_code=404, detail="Evolution triggers not found")
        return status
    except HTTPException:
        raise
    except Exception as e:
        _register_router_debt(290, "except Exception as e:", str(e), "get_evolution_triggers")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")
