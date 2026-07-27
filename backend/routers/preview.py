"""
Preview Router - プレビュー・カラーグレーディング・オーディオ関連エンドポイント
"""
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
from pathlib import Path
import asyncio

router = APIRouter(prefix="/api", tags=["preview"])


class SubtitleItem(BaseModel):
    text: str
    start: float
    end: float


class PreviewRequest(BaseModel):
    source_video: str
    bgm_path: Optional[str] = None
    duration: Optional[int] = None
    subtitles: Optional[List[SubtitleItem]] = None
    color_preset: Optional[str] = None


# 同時実行制限
preview_semaphore = asyncio.Semaphore(2)

# 許可されたディレクトリ
ALLOWED_VIDEO_DIR = Path("C:/Users/PC_User/Desktop/script/video-automation").resolve()
ALLOWED_EXTENSIONS = [".mp4", ".mov", ".avi", ".mkv", ".mp3", ".wav"]


def validate_video_path(path: str, allow_none: bool = False) -> Optional[Path]:
    """動画パスの検証（セキュリティ強化）"""
    if path is None:
        if allow_none:
            return None
        raise ValueError("Path is required")
    
    resolved = Path(path).resolve()
    
    # パストラバーサル防止
    if not str(resolved).startswith(str(ALLOWED_VIDEO_DIR)):
        raise ValueError(f"Path outside allowed directory: {path}")
    
    # 拡張子チェック
    if resolved.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Invalid file extension: {resolved.suffix}")
    
    # 存在チェック
    if not resolved.exists():
        raise FileNotFoundError(f"File not found: {path}")
    
    return resolved


@router.post("/preview/generate")
async def generate_preview(req: PreviewRequest):
    """
    Generate an enhanced preview (480p proxy) of the source video.
    Supports optional background music, animated subtitles, and color grading presets (Phase 28).
    """
    from preview_engine import preview_engine
    
    async with preview_semaphore:
        try:
            source = validate_video_path(req.source_video)
            bgm = validate_video_path(req.bgm_path, allow_none=True)
            
            result = preview_engine.generate(
                source_video=str(source),
                bgm_path=str(bgm) if bgm else None,
                duration=req.duration,
                subtitles=[s.dict() for s in req.subtitles] if req.subtitles else None,
                color_preset=req.color_preset
            )
            
            return result
            
        except ValueError as e:
            return {"error": str(e), "type": "validation_error"}
        except FileNotFoundError as e:
            return {"error": str(e), "type": "file_not_found"}
        except HTTPException:
            raise
        except Exception as e:
            return {"error": str(e), "type": "internal_error"}


@router.get("/preview/{preview_id}")
async def get_preview(preview_id: str):
    """Get the generated preview video."""
    preview_dir = Path(__file__).parent.parent / "previews"
    preview_path = preview_dir / f"{preview_id}.mp4"
    
    if preview_path.exists():
        return FileResponse(preview_path, media_type="video/mp4")
    
    return {"error": "Preview not found"}


@router.delete("/preview/cleanup")
async def cleanup_old_previews(days: int = 7):
    """Clean up preview files older than specified days."""
    from preview_engine import preview_engine
    result = preview_engine.cleanup_old(days=days)
    return result


# === Audio & Video Enhancement Endpoints (Phase 28) ===

@router.post("/audio/master")
async def master_audio(
    audio_path: str,
    normalize: bool = True,
    denoise: bool = True,
    target_lufs: float = -16.0,
    noise_reduction: float = 0.5
):
    """Audio mastering with normalization and noise removal."""
    from audio_master import audio_master
    
    try:
        validated_path = validate_video_path(audio_path)
        
        result = audio_master.process(
            input_path=str(validated_path),
            normalize=normalize,
            denoise=denoise,
            target_lufs=target_lufs,
            noise_reduction=noise_reduction
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        return {"error": str(e)}


@router.post("/color/apply")
async def apply_color_grading(
    video_path: str,
    preset: str = "cinematic"
):
    """Apply color grading preset to video."""
    from color_grading import color_grading
    
    try:
        validated_path = validate_video_path(video_path)
        
        result = color_grading.apply_preset(
            input_path=str(validated_path),
            preset=preset
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        return {"error": str(e)}


@router.get("/color/presets")
async def get_color_presets():
    """Get available color grading presets."""
    return {
        "presets": ["cinematic", "warm", "cool", "vintage", "vibrant", "none"],
        "default": "cinematic"
    }


# === Thumbnail Generation (Phase 25) ===

class ThumbnailGenerateRequestLocal(BaseModel):
    video_title: str
    video_description: Optional[str] = ""
    num_variants: Optional[int] = 3

@router.post("/thumbnail/generate")
async def generate_thumbnail(req: ThumbnailGenerateRequestLocal):
    """サムネイル生成エンドポイント（Phase 25）"""
    from thumbnail_engine.generator import generator as thumbnail_generator
    
    if not thumbnail_generator.api_key:
        raise HTTPException(
            status_code=500,
            detail="Google AI API Key is not configured. Please set GOOGLE_GENERATIVE_AI_API_KEY."
        )
        
    result = await thumbnail_generator.generate(
        video_title=req.video_title,
        video_description=req.video_description,
        num_variants=req.num_variants
    )
    
    return result


# === Progressive Preview System ===

@router.post("/progressive-preview/start")
async def start_progressive_preview(request: Request):
    """Progressive Previewセッションを開始"""
    from progressive_preview import ProgressivePreview
    
    data = await request.json()
    session_id = data.get("session_id", "default")
    
    preview = ProgressivePreview(session_id)
    # セッション管理はグローバル変数で行う（本格実装では Redis 等を使用）
    
    return {"session_id": session_id, "status": "started"}


@router.post("/progressive-preview/snapshot")
async def capture_snapshot(request: Request):
    """スナップショットを撮影"""
    data = await request.json()
    session_id = data.get("session_id", "default")
    timestamp = data.get("timestamp", 0)
    
    # スナップショット処理
    return {"session_id": session_id, "timestamp": timestamp, "status": "captured"}


@router.get("/progressive-preview/report/{session_id}")
async def get_preview_report(session_id: str):
    """プレビューレポートを取得"""
    from preview_report_generator import PreviewReportGenerator
    
    generator = PreviewReportGenerator()
    report = generator.generate_report(session_id)
    
    return report
