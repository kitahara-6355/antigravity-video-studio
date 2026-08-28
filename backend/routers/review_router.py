"""
Progressive Review Router - 段階的レビューAPI

PROJECT_CONSTITUTION §16 拡張:
- 各ステージのレビュー取得
- 承認/修正指示
- レポート生成
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
from enum import Enum
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/review", tags=["Progressive Review"])


class ReviewStage(str, Enum):
    """レビューステージ"""
    SUBTITLE = "subtitle"
    TELOP = "telop"
    VISUAL = "visual"
    VIDEO = "video"
    FINAL = "final"


class RevisionRequest(BaseModel):
    """修正リクエスト"""
    stage: ReviewStage
    notes: str
    items: Optional[List[str]] = None  # 修正対象の項目ID


def _get_plugin_components():
    """プラグインから必要なコンポーネントを遅延ロードするヘルパー"""
    from plugins.progressive_review_plugin import progressive_review, ReviewStage as PluginStage
    return progressive_review, PluginStage


def _get_context(task_id: str):
    """ProductionContext を遅延ロードするヘルパー"""
    from core import ProductionContext
    return ProductionContext(task_id=task_id)


# ステージ情報
STAGE_INFO = {
    ReviewStage.SUBTITLE: {
        "name": "字幕統一感チェック",
        "description": "全字幕のスタイル・表示時間・文字数を確認",
        "icon": "📝",
        "order": 1
    },
    ReviewStage.TELOP: {
        "name": "テロップデザインチェック",
        "description": "テロップのデザインとブランド整合性を確認",
        "icon": "🎨",
        "order": 2
    },
    ReviewStage.VISUAL: {
        "name": "サムネイル・画像チェック",
        "description": "サムネイル候補とシーン画像のトーン統一を確認",
        "icon": "🖼️",
        "order": 3
    },
    ReviewStage.VIDEO: {
        "name": "OP/ED・トランジションチェック",
        "description": "動画素材とトランジション効果を確認",
        "icon": "🎬",
        "order": 4
    },
    ReviewStage.FINAL: {
        "name": "最終統合チェック",
        "description": "全素材の統合プレビューと品質スコア確認",
        "icon": "✅",
        "order": 5
    }
}


@router.get("/stages")
async def get_all_stages() -> Dict[str, Any]:
    """
    全ステージの情報を取得
    """
    return {
        "stages": [
            {
                "id": stage.value,
                **STAGE_INFO[stage]
            }
            for stage in ReviewStage
        ],
        "total": len(ReviewStage)
    }


@router.get("/stages/{stage}")
async def get_stage_info(stage: ReviewStage) -> Dict[str, Any]:
    """
    特定ステージの情報を取得
    """
    info = STAGE_INFO.get(stage)
    if not info:
        raise HTTPException(status_code=404, detail="Stage not found")
    
    return {
        "id": stage.value,
        **info
    }


@router.get("/stages/{stage}/report")
async def get_stage_report(stage: ReviewStage) -> Dict[str, Any]:
    """
    特定ステージのレビューレポートを取得
    
    Returns:
        カルーセル形式のMarkdownレポートとレビュー項目
    """
    try:
        progressive_review, plugin_stage_cls = _get_plugin_components()
        context = _get_context("review_session")
        
        # ステージに対応するプラグインのステージを取得
        plugin_stage = plugin_stage_cls(stage.value)
        
        # レポートを生成
        report_md = progressive_review.generate_stage_report(plugin_stage, context)
        
        return {
            "stage": stage.value,
            "stage_info": STAGE_INFO[stage],
            "report_markdown": report_md,
            "status": "generated"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate report for {stage}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stages/{stage}/approve")
async def approve_stage(stage: ReviewStage) -> Dict[str, Any]:
    """
    ステージを承認
    """
    try:
        progressive_review, plugin_stage_cls = _get_plugin_components()
        
        plugin_stage = plugin_stage_cls(stage.value)
        success = progressive_review.approve_stage(plugin_stage)
        
        if success:
            return {
                "stage": stage.value,
                "approved": True,
                "message": f"{STAGE_INFO[stage]['name']}を承認しました"
            }
        else:
            raise HTTPException(status_code=400, detail="Approval failed")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to approve {stage}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stages/{stage}/revision")
async def request_revision(
    stage: ReviewStage,
    request: RevisionRequest
) -> Dict[str, Any]:
    """
    修正を要求
    """
    try:
        progressive_review, plugin_stage_cls = _get_plugin_components()
        
        plugin_stage = plugin_stage_cls(stage.value)
        success = progressive_review.request_revision(plugin_stage, request.notes)
        
        if success:
            return {
                "stage": stage.value,
                "revision_requested": True,
                "notes": request.notes,
                "message": f"{STAGE_INFO[stage]['name']}の修正を受け付けました"
            }
        else:
            raise HTTPException(status_code=400, detail="Revision request failed")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to request revision for {stage}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_review_status() -> Dict[str, Any]:
    """
    全ステージのレビュー状況を取得
    """
    try:
        progressive_review, _ = _get_plugin_components()
        
        pending = progressive_review.get_pending_stages()
        
        return {
            "pending_stages": [s.value for s in pending],
            "pending_count": len(pending),
            "all_approved": len(pending) == 0,
            "stages": {
                stage.value: {
                    "name": STAGE_INFO[stage]["name"],
                    "pending": any(s.value == stage.value for s in pending)
                }
                for stage in ReviewStage
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get review status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary")
async def get_review_summary() -> Dict[str, Any]:
    """
    レビューサマリーを取得
    """
    try:
        progressive_review, _ = _get_plugin_components()
        context = _get_context("review_session")
        
        # プラグインを実行してサマリーを取得
        context = progressive_review.execute(context)
        
        summary = context.get_extension("progressive_review_summary", {})
        
        # **1つも採点していないのに「レンダリング準備完了」と言わない**（R1.5-C4）。
        # `pending_revisions == 0` だけを見ていたので、**何も測っていない
        # セッションでも true** になっていた（修正を要求した人が誰もいない、
        # という意味でしかない）。採点できたステージが1つも無ければ判定不能。
        採点済み = summary.get("scored_stages") or []
        修正待ちなし = summary.get("pending_revisions", 1) == 0
        return {
            "summary": summary,
            "ready_for_render": bool(採点済み) and 修正待ちなし,
            "ready_for_render_reason": (
                "採点できたステージがありません（品質ゲートが繋がっていません）"
                if not 採点済み else
                ("修正待ちのステージがあります" if not 修正待ちなし else "")
            ),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get review summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))
