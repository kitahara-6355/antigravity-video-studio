"""
Antigravity 3.0 API Router
ブラウザからAntigravity全機能を操作するためのエンドポイント
"""

try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path

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
                "id": e.get('id', ''),
                "incorrect": e.get('incorrect', ''),
                "correct": e.get('correct', ''),
                "type": e.get('type', ''),
                "context_hint": e.get('context_hint', ''),
                "confirmed": e.get('confirmed', False),
                "usage_count": e.get('usage_count', 0)
            }
            for e in entries
        ]
    }


@router.post("/proper-nouns")
async def add_proper_noun(entry: ProperNounEntry):
    """固有名詞エントリを追加"""
    try:
        new_entry = proper_noun_dict.add_entry(
            incorrect=entry.incorrect,
            correct=entry.correct,
            entry_type=entry.type,
            context_hint=entry.context_hint
        )
        return {"success": True, "entry": new_entry}
    except HTTPException:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/process-srt")
async def process_srt(file: UploadFile = File(...)):
    """SRTファイルを統合パイプラインで処理

    アップロード名は信用しない。以前は `Path("temp") / file.filename` と
    連結していたため、`../../` を含む名前を送られると temp/ の外へ書けた
    （filename はクライアントが自由に指定できる）。ディレクトリ部分を捨てる。

    保存先が相対パスだったため、サーバの起動ディレクトリ次第で書き込み先が
    変わってもいた。`writable_path` で固定する。
    """
    safe_name = Path(file.filename or "upload.srt").name
    if not safe_name or safe_name in (".", ".."):
        raise HTTPException(status_code=400, detail="ファイル名が不正です")

    temp_path = _writable_path("temp") / safe_name
    try:
        # 一時保存
        temp_path.parent.mkdir(parents=True, exist_ok=True)

        with open(temp_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        # パイプライン実行
        pipeline = AntigravityPipeline()
        result = pipeline.process_srt(temp_path)
        
        return result
    except HTTPException:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError) as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if temp_path.exists():
            temp_path.unlink()


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
            record_approval({"proposal_id": proposal_id, "type": "telop"}, tags=["telop"], permanent=req.permanent)
        return {"success": True, "action": "approved", "permanent": req.permanent}
    else:
        record_rejection({"proposal_id": proposal_id, "type": "telop"}, reason="rejected", tags=["telop"])
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
        result = generate_thumbnail(req.title, req.context)
        return result
    except HTTPException:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate/opening")
async def api_generate_opening(req: GenerateVideoRequest, background_tasks: BackgroundTasks):
    """オープニング生成（非同期）"""
    try:
        result = generate_opening(req.channel_name)
        return result
    except HTTPException:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate/ending")
async def api_generate_ending(req: GenerateVideoRequest, background_tasks: BackgroundTasks):
    """エンディング生成（非同期）"""
    try:
        result = generate_ending(req.channel_name)
        return result
    except HTTPException:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError) as e:
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
        詳細 = getattr(result.score, "details", None) or {}
        return {
            # **レビューできなかったことを応答で名乗る**（R1.5-C4）。
            # 以前は AI が落ちても `passed: true / score: 0.75` が返っていた
            "scored": 詳細.get("scored", True),
            "is_real": 詳細.get("is_real", True),
            "passed": result.passed,
            "score": result.score.overall,
            "issues": result.issues
        }
    except HTTPException:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError) as e:
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
        record_approval({"proposal_id": req.proposal_id, "type": "learning"}, permanent=req.permanent)
        return {"success": True, "action": "approved"}
    else:
        record_rejection({"proposal_id": req.proposal_id, "type": "learning"})
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
        result = video_editor.create_final_video(
            main_video=Path(req.main_video),
            opening=Path(req.opening) if req.opening else None,
            ending=Path(req.ending) if req.ending else None,
            telops=req.telops,
            output_name=req.output_name
        )
        return result
    except HTTPException:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError) as e:
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
