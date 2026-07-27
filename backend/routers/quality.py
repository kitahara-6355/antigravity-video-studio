"""
Quality Router - 品質チェック・クリーンアップ関連エンドポイント
"""
from fastapi import APIRouter, Request
from pydantic import BaseModel


router = APIRouter(prefix="/api/quality", tags=["quality"])


class QualityCheckRequest(BaseModel):
    """品質チェックリクエスト"""
    full_text: str = ""
    scenes: list = []
    segments: list = []


class CleanupRequest(BaseModel):
    """クリーンアップリクエスト"""
    category: str = None
    dry_run: bool = False


@router.post("/check")
async def run_quality_check(req: QualityCheckRequest):
    """
    品質ゲートを実行
    
    PROJECT_CONSTITUTION 8.2 に基づく品質チェック:
    - 誤字脱字チェック
    - ブランド整合性チェック
    - 字幕リズムチェック
    - シーン演出の論理性チェック
    
    スコア90点以上で合格、60点未満でブロック
    """
    from quality_gate_agent import quality_gate
    
    report_dict = quality_gate.comprehensive_check(
        full_text=req.full_text,
        scenes=req.scenes,
        segments=req.segments
    )
    
    return report_dict


@router.get("/threshold")
async def get_quality_threshold():
    """品質閾値を取得"""
    return {
        "pass_threshold": 90,
        "block_threshold": 60,
        "warning_threshold": 70
    }


@router.post("/verify")
async def verify_quality(request: Request):
    """Final quality check before render."""
    from quality_gate_agent import quality_gate
    data = await request.json()
    report_dict = quality_gate.pre_render_check(data)
    return report_dict


@router.post("/cleanup")
async def run_cleanup(req: CleanupRequest = None):
    """
    一時ファイルをクリーンアップ
    
    保持期間と最大件数に基づいて古いファイルを削除
    RAW動画と最終出力は絶対に削除しない（protected）
    """
    from cleanup_manager import cleanup_manager
    
    if req and req.dry_run:
        return cleanup_manager.preview_cleanup()
    
    result = cleanup_manager.cleanup(category=req.category if req else None)
    return result


@router.get("/cleanup/preview")
async def preview_cleanup():
    """
    クリーンアップのプレビュー
    
    実際には削除せず、削除予定のファイルをリスト表示
    """
    from cleanup_manager import cleanup_manager
    return cleanup_manager.preview_cleanup()


@router.get("/storage/stats")
async def get_storage_stats():
    """
    ストレージ使用状況を取得
    """
    from cleanup_manager import cleanup_manager
    return cleanup_manager.get_storage_stats()


# === AI Rhythm Engine ===

class RhythmRequest(BaseModel):
    text: str
    target_chars: int = 13


@router.post("/rhythm/split")
async def rhythm_split(req: RhythmRequest):
    """Semantic Split for AI Rhythm Master"""
    from ai_rhythm import semantic_split
    result = semantic_split(req.text, req.target_chars)
    return {"splits": result}


# === U-06: Quick Decision API ===

class QuickDecisionRequest(BaseModel):
    item_id: str
    action: str  # "approve", "reject", "skip"
    timestamp: str = ""
    comment: str = ""


@router.post("/decision/quick")
async def quick_decision(req: QuickDecisionRequest):
    """
    U-06: ワンクリック判断を記録
 
    Owner のレビュー決定をログに記録し、
    必要に応じてパイプラインにフィードバックする。
    """
    from datetime import datetime

    entry = {
        "item_id": req.item_id,
        "action": req.action,
        "timestamp": req.timestamp or datetime.now().isoformat(),
        "comment": req.comment,
    }

    _write_log_entry("decisions", "decisions", entry)

    return {"status": "ok", "decision": entry}


# === U-08: AI Suggestion Apply / Undo ===

class SuggestionActionRequest(BaseModel):
    suggestion: str
    index: int = 0


@router.post("/apply-suggestion")
async def apply_suggestion(req: SuggestionActionRequest):
    """U-08: AI改善提案を適用"""
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"AI提案適用: [{req.index}] {req.suggestion[:60]}")
    return {"status": "applied", "index": req.index}


@router.post("/undo-suggestion")
async def undo_suggestion(req: SuggestionActionRequest):
    """U-08: AI改善提案を取消"""
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"AI提案取消: [{req.index}] {req.suggestion[:60]}")
    return {"status": "undone", "index": req.index}


# === U-10: 段階的レビュー承認 ===

class ReviewApprovalRequest(BaseModel):
    stages: list = []
    approved_at: str = ""


@router.post("/review/approve")
async def approve_review(req: ReviewApprovalRequest):
    """
    U-10: 段階的レビューの最終承認を記録

    5段階チェック結果をログに保存し、
    レンダリング許可フラグを立てる。
    """
    import logging
    from datetime import datetime

    logger = logging.getLogger(__name__)

    entry = {
        "stages": req.stages,
        "approved_at": req.approved_at or datetime.now().isoformat(),
        "total_stages": len(req.stages),
        "completed_stages": sum(1 for s in req.stages if s.get("completed")),
    }

    _write_log_entry("reviews", "reviews", entry)

    logger.info(
        f"📋 段階的レビュー承認: {entry['completed_stages']}/{entry['total_stages']} stages"
    )

    return {"status": "approved", "entry": entry}


def _write_log_entry(dir_name: str, file_prefix: str, entry: dict) -> None:
    """
    JSONL形式でログファイルに追記する共通ヘルパー関数
    
    ファイルI/O安全規約に準拠するため、Pythonの open を UTF-8 エンコーディングで使用する。
    """
    import json
    from pathlib import Path
    from datetime import datetime

    log_dir = Path(__file__).parent.parent / "data" / dir_name
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{file_prefix}_{datetime.now().strftime('%Y%m%d')}.jsonl"

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
