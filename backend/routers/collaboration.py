"""
Collaboration Router - フィードバック・ジャーナル・意思決定関連エンドポイント
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["collaboration"])


class FeedbackRequest(BaseModel):
    suggestion_id: str
    action: str
    role: str
    comment: str = ""


class JournalRequest(BaseModel):
    author: str
    content: str


class DecisionRequest(BaseModel):
    """意思決定記録リクエスト"""
    target_type: str
    target_path: str
    target_description: str
    decision: str
    reason: str
    scene_info: Optional[Dict[str, Any]] = None
    mood_settings: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None


class CouncilDecisionRequest(BaseModel):
    """意思決定データリクエスト（みらい議会）"""
    outcome: str = "UNKNOWN"
    session_id: str = ""


class CouncilSessionRequest(BaseModel):
    """Council of Minds セッション起動リクエスト"""
    query: str = "現在のチャンネル成長についての戦略的分析をお願いします。"
    council_mode: str = "post_production"


# --- 定義された定数 ---
BASE_DIR = Path(__file__).parent.parent
EVOLUTION_LOG_PATH = BASE_DIR / "branding" / "evolution_log.json"

DEFAULT_COUNCIL_QUERY = "現在のチャンネル成長についての戦略的分析をお願いします。"
DEFAULT_COUNCIL_MODE = "post_production"


def _get_branding_manager():
    """Get branding manager instance dynamically to avoid circular imports."""
    from branding_manager import branding_manager
    return branding_manager


def _get_decision_logger():
    """Get decision logger instance dynamically to avoid circular imports."""
    from decision_logger import decision_logger
    return decision_logger


def _read_json_file(path: Path) -> Dict[str, Any]:
    """指定されたファイルをJSONとして読み込む"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except (json.JSONDecodeError, FileNotFoundError, PermissionError):
        return {}


def _load_philosophies_from_file(log_path: Path) -> List[Any]:
    """進化ログJSONファイルから哲学リストをロードする"""
    if not log_path.exists():
        return []
    evo_log = _read_json_file(log_path)
    return evo_log.get("philosophies", [])


@router.post("/feedback")
async def process_feedback(feedback: FeedbackRequest):
    """
    Processes feedback from Admin or Owner on an AI suggestion.
    AIからの解説: 管理者やチャンネル主からのフィードバックを記録し、AIの成長に反映させます。
    """
    branding_manager = _get_branding_manager()
    result = branding_manager.register_feedback(
        suggestion_id=feedback.suggestion_id,
        action=feedback.action,
        role=feedback.role,
        comment=feedback.comment
    )
    return result


@router.get("/journal")
async def get_journal():
    """Returns the collaborative notes history."""
    branding_manager = _get_branding_manager()
    return branding_manager.get_journal()


@router.post("/journal")
async def add_journal_entry(journal_data: JournalRequest):
    """
    Adds a collaborative note/decision to the user model.
    AIからの解説: 管理者とチャンネル主の間で交わされた合意やメモを、AIの記憶に刻みます。
    """
    branding_manager = _get_branding_manager()
    result = branding_manager.add_journal_entry(journal_data.author, journal_data.content)
    return result


# === Decision Logger API ===

@router.post("/decision/record")
async def record_decision(decision_data: DecisionRequest):
    """
    意思決定を記録
    
    スクショやドラフトに対するユーザーの判断を記録し、
    AIが次回の提案に活用できるようにする
    """
    decision_logger_instance = _get_decision_logger()
    result = decision_logger_instance.record_decision(
        target_type=decision_data.target_type,
        target_path=decision_data.target_path,
        target_description=decision_data.target_description,
        decision=decision_data.decision,
        reason=decision_data.reason,
        scene_info=decision_data.scene_info,
        mood_settings=decision_data.mood_settings,
        tags=decision_data.tags
    )
    return {"status": "recorded", "decision_id": result}


@router.get("/decision/context")
async def get_decision_context(target_type: Optional[str] = None):
    """
    AIに渡すコンテキストを取得
    
    過去の意思決定を要約して、AIプロンプトに追加
    同じ質問の繰り返しを防止
    """
    decision_logger_instance = _get_decision_logger()
    return decision_logger_instance.get_ai_context(target_type)


@router.get("/decision/stats")
async def get_decision_stats():
    """意思決定統計を取得"""
    decision_logger_instance = _get_decision_logger()
    return decision_logger_instance.get_stats()


@router.post("/decision/sync")
async def sync_decisions():
    """
    意思決定をSoul Narrativeに同期
    
    却下理由を「こだわり」として哲学に昇華
    承認パターンを「好み」として記録
    """
    decision_logger_instance = _get_decision_logger()
    return decision_logger_instance.sync_to_evolution_log()


@router.get("/director-profile")
async def get_director_profile():
    """
    監督プロファイルを取得
    
    AIが提案する際に参照する「監督の好み・こだわり」
    """
    decision_logger_instance = _get_decision_logger()
    return decision_logger_instance.get_director_preferences()


# === Council of Minds Endpoints ===

@router.post("/council/session")
async def trigger_council_session(
    request_data: Optional[CouncilSessionRequest] = None,
    query: Optional[str] = None,
    council_mode: Optional[str] = None,
):
    """Triggers a Council of Minds session via ADK (Phase A: ADK移行済み)."""
    from agents.council_graph import run_council
    q = query or (request_data.query if request_data else None) or DEFAULT_COUNCIL_QUERY
    mode = council_mode or (request_data.council_mode if request_data else None) or DEFAULT_COUNCIL_MODE
    result = await run_council(user_query=q, council_mode=mode)
    return result


@router.post("/council/decision")
async def council_decision(decision_data: CouncilDecisionRequest):
    """Evolution Endpoint: Feedback Loop from Chairman to Agents."""
    branding_manager = _get_branding_manager()
    
    if decision_data.outcome == "APPROVE":
        branding_manager.apply_xp(50)
    
    return {
        "status": "processed",
        "outcome": decision_data.outcome,
        "session_id": decision_data.session_id
    }


# === Philosophy & Resolution API ===

@router.get("/philosophies")
async def list_philosophies():
    """哲学一覧を取得"""
    philosophies = _load_philosophies_from_file(EVOLUTION_LOG_PATH)
    return {"philosophies": philosophies}


@router.get("/resolutions")
async def list_resolutions(status: Optional[str] = None):
    """議案一覧を取得（みらい議会スタイル）"""
    branding_manager = _get_branding_manager()
    resolutions = branding_manager.get_resolutions(status)
    return {"resolutions": resolutions}


@router.post("/resolutions/{resolution_id}/vote")
async def vote_resolution(resolution_id: str, request: Request):
    """エージェントの投票を記録"""
    from fastapi import HTTPException
    branding_manager = _get_branding_manager()
    try:
        data = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    result = branding_manager.record_vote(resolution_id, data)
    return result


@router.post("/resolutions/{resolution_id}/gavel")
async def apply_gavel(resolution_id: str, request: Request):
    """議長決済（Gavel Ceremony）"""
    from fastapi import HTTPException
    branding_manager = _get_branding_manager()
    try:
        data = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    result = branding_manager.apply_gavel(resolution_id, data)
    return result

