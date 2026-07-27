"""
Antigravity 3.0 API Router
ブラウザからAntigravity全機能を操作するためのエンドポイント
"""

from fastapi import APIRouter, HTTPException, UploadFile, File, BackgroundTasks
from pydantic import BaseModel
from typing import List, Dict, Optional
from pathlib import Path
import json
import logging
import shutil

# Antigravity 3.0 モジュール
from proper_noun_dict import proper_noun_dict, apply_dictionary
from subtitle_normalizer import SRTExporter
from semantic_store import create_semantic_store
from telop_proposal_engine import extract_telops, propose_scenes
from asset_library import asset_library
from generation_engine import generate_thumbnail, generate_opening, generate_ending, GenerationEngine
from self_review_engine import self_review_engine
from learning_loop import learning_loop, record_approval, record_rejection
from video_editor_engine import video_editor, check_ffmpeg
from antigravity_pipeline import AntigravityPipeline

logger = logging.getLogger(__name__)

def validate_safe_path(path_str: str) -> Path:
    """
    指定されたパス文字列がプロジェクトルート配下のディレクトリ内に収まっていることを検証する。
    """
    if not path_str:
        raise HTTPException(status_code=400, detail="Path cannot be empty.")
    try:
        target_path = Path(path_str).resolve()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid path representation: {str(e)}")
    
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    try:
        target_path.relative_to(project_root)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Access denied to path: {path_str}")
    return target_path

router = APIRouter(prefix="/api/antigravity", tags=["Antigravity 3.0"])


# === Request/Response Models ===

class ProperNounEntry(BaseModel):
    incorrect: str
    correct: str
    type: str = "word"
    context_hint: str = ""


class TelopApprovalRequest(BaseModel):
    action: str  # "approve" or "reject"
    permanent: bool = False


class GenerateThumbnailRequest(BaseModel):
    title: str
    context: Dict = {}
    style: str = "professional"


class GenerateVideoRequest(BaseModel):
    channel_name: str = "美麗書院"
    duration_sec: float = 5.0


class CreateFinalVideoRequest(BaseModel):
    main_video: str
    opening: Optional[str] = None
    ending: Optional[str] = None
    telops: List[Dict] = []
    output_name: str = "final_video.mp4"


class LearningApprovalRequest(BaseModel):
    proposal_id: str
    action: str  # "approve" or "reject"
    permanent: bool = False


# === Phase 1: 固有名詞辞書 ===

@router.get("/proper-nouns")
async def get_proper_nouns():
    """固有名詞辞書を取得"""
    entries = proper_noun_dict.get_all_entries()
    return {
        "count": len(entries),
        "entries": [
            {
                "id": getattr(e, 'id', ''),
                "incorrect": getattr(e, 'incorrect', ''),
                "correct": getattr(e, 'correct', ''),
                "type": getattr(e, 'type', ''),
                "context_hint": getattr(e, 'context_hint', ''),
                "confirmed": getattr(e, 'confirmed', False),
                "usage_count": getattr(e, 'usage_count', 0)
            }
            for e in entries
        ]
    }


@router.post("/proper-nouns")
async def add_proper_noun(entry: ProperNounEntry):
    """固有名詞エントリを追加"""
    try:
        if not entry.incorrect.strip() or not entry.correct.strip():
            raise HTTPException(status_code=400, detail="Incorrect and correct fields cannot be empty.")
        new_entry = proper_noun_dict.add_entry(
            incorrect=entry.incorrect,
            correct=entry.correct,
            entry_type=entry.type,
            context_hint=entry.context_hint
        )
        return {"success": True, "entry": new_entry}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/process-srt")
async def process_srt(file: UploadFile = File(...)):
    """SRTファイルを統合パイプラインで処理"""
    try:
        filename = Path(file.filename).name
        if not filename:
            raise HTTPException(status_code=400, detail="Invalid filename")
        if not filename.lower().endswith(".srt"):
            raise HTTPException(status_code=400, detail="Only SRT files are allowed")
        
        # 一時保存
        temp_path = Path("temp") / filename
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        
        # ファイルサイズ制限（最大 10MB）
        MAX_FILE_SIZE = 10 * 1024 * 1024
        file_content = await file.read()
        if len(file_content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail="File size exceeds the 10MB limit")
        
        with open(temp_path, "wb") as f:
            f.write(file_content)
        
        # パイプライン実行
        pipeline = AntigravityPipeline()
        result = pipeline.process_srt(temp_path)
        
        # 一時ファイル削除
        temp_path.unlink()
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# === Phase 3: テロップ提案 ===

@router.get("/telop-proposals")
async def get_telop_proposals():
    """テロップ提案を取得"""
    proposal_path = Path("output/proposals")
    proposals = []
    
    if proposal_path.exists():
        for f in proposal_path.glob("*_proposals.json"):
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
                proposals.append({
                    "file": f.name,
                    "telop_candidates": data.get("telop_candidates", []),
                    "scene_proposals": data.get("scene_proposals", [])
                })
    
    return {"proposals": proposals}


@router.post("/telop-proposals/{proposal_id}/approve")
async def approve_telop(proposal_id: str, req: TelopApprovalRequest):
    """テロップ提案を承認/却下"""
    if req.action == "approve":
        if req.permanent:
            record_approval(proposal_id, "telop")
        return {"success": True, "action": "approved", "permanent": req.permanent}
    else:
        record_rejection(proposal_id, "telop")
        return {"success": True, "action": "rejected"}


# === Phase 4: アセット管理 ===

@router.get("/assets")
async def get_assets():
    """アセット一覧"""
    asset_library.scan()
    return {
        "count": len(asset_library.assets),
        "assets": [
            {
                "id": a.id,
                "category": a.category,
                "path": str(a.path),
                "labels": a.labels,
                "style_tags": a.style_tags
            }
            for a in asset_library.assets
        ]
    }


@router.post("/assets/scan")
async def scan_assets():
    """アセット再スキャン"""
    asset_library.scan()
    return {"success": True, "count": len(asset_library.assets)}


@router.get("/assets/sufficiency")
async def get_asset_sufficiency():
    """充足度レポート"""
    asset_library.scan()
    return asset_library.get_sufficiency_report()


# === Phase 5: 生成 ===

@router.post("/generate/thumbnail")
async def api_generate_thumbnail(req: GenerateThumbnailRequest):
    """サムネイル生成"""
    try:
        if not req.title.strip():
            raise HTTPException(status_code=400, detail="Title cannot be empty")
        result = generate_thumbnail(req.title, req.context)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate/opening")
async def api_generate_opening(req: GenerateVideoRequest, background_tasks: BackgroundTasks):
    """オープニング生成（非同期）"""
    try:
        if not req.channel_name.strip():
            raise HTTPException(status_code=400, detail="Channel name cannot be empty")
        result = generate_opening(req.channel_name)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate/ending")
async def api_generate_ending(req: GenerateVideoRequest, background_tasks: BackgroundTasks):
    """エンディング生成（非同期）"""
    try:
        if not req.channel_name.strip():
            raise HTTPException(status_code=400, detail="Channel name cannot be empty")
        result = generate_ending(req.channel_name)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# === Phase 6: 品質チェック ===

@router.get("/self-review/status")
async def get_self_review_status():
    """Self-Review Engine状態"""
    return {
        "thresholds": self_review_engine.THRESHOLDS,
        "enabled": True
    }


@router.post("/self-review/check")
async def run_self_review(content: Dict):
    """品質チェック実行"""
    try:
        result = self_review_engine.review(
            content=content.get("content", ""),
            generation_type=content.get("type", "unknown"),
            context=content.get("context", {})
        )
        return {
            "passed": result.passed,
            "score": result.score.overall,
            "issues": result.issues
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# === Phase 7: 学習ループ ===

@router.get("/learning/pending")
async def get_pending_proposals():
    """未来議会議題を取得"""
    pending = learning_loop.get_pending_proposals()
    return {"count": len(pending), "proposals": pending}


@router.post("/learning/approve")
async def approve_learning(req: LearningApprovalRequest):
    """恒久化承認/却下"""
    if req.action == "approve":
        record_approval(req.proposal_id, permanent=req.permanent)
        return {"success": True, "action": "approved"}
    else:
        record_rejection(req.proposal_id)
        return {"success": True, "action": "rejected"}


@router.get("/learning/preferences")
async def get_preferences():
    """学習済みパターン"""
    return learning_loop.get_preferences()


# === Phase 8: 動画編集 ===

@router.get("/editor/status")
async def get_editor_status():
    """FFmpeg状態確認"""
    return {
        "ffmpeg_available": check_ffmpeg(),
        "output_dir": str(video_editor.output_dir)
    }


@router.post("/editor/create-final")
async def create_final_video(req: CreateFinalVideoRequest, background_tasks: BackgroundTasks):
    """最終動画生成"""
    try:
        main_video_path = validate_safe_path(req.main_video)
        opening_path = validate_safe_path(req.opening) if req.opening else None
        ending_path = validate_safe_path(req.ending) if req.ending else None
        
        output_name = Path(req.output_name).name
        if not output_name:
            raise HTTPException(status_code=400, detail="Invalid output name")
            
        result = video_editor.create_final_video(
            main_video=main_video_path,
            opening=opening_path,
            ending=ending_path,
            telops=req.telops,
            output_name=output_name
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# === Pipeline Status ===

@router.get("/status")
async def get_pipeline_status():
    """パイプライン全体ステータス"""
    pipeline = AntigravityPipeline()
    status = pipeline.get_pipeline_status()
    
    return {
        "proper_noun_entries": status["proper_noun_entries"],
        "pending_confirmations": status["pending_confirmations"],
        "available_assets": status["available_assets"],
        "pending_proposals": status["pending_proposals"],
        "ffmpeg_available": check_ffmpeg()
    }
