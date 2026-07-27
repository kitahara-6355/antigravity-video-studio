
"""
Shorts Router - ショート動画生成APIエンドポイント

PROJECT_CONSTITUTION §23 YouTube最適化規約準拠:
- ハイライトからショート動画を生成
- 生成済みクリップ一覧取得
- エクスポート機能
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import logging
import asyncio
from pathlib import Path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/shorts", tags=["Shorts Generator"])


class GenerateThumbnailRequest(BaseModel):
    """サムネイル画像生成リクエスト"""
    video_path: str
    task_id: str
    text: str = "Thumbnail"
    db_path: Optional[str] = None


class GenerateShortsRequest(BaseModel):
    """ショート動画生成リクエスト"""
    video_path: str
    highlights: List[Dict[str, Any]]
    task_id: str = ""


class ExportShortsRequest(BaseModel):
    """ショート動画エクスポートリクエスト"""
    clip_ids: List[str]
    format: str = "mp4"  # mp4, webm
    task_id: str = ""


class ExtractCandidatesRequest(BaseModel):
    """Shorts候補抽出リクエスト"""
    segments: List[Dict[str, Any]]
    video_duration_sec: int = 300
    video_id: str = ""


class RenderShortRequest(BaseModel):
    """Shorts縦型レンダリングリクエスト"""
    video_path: str
    start_sec: float
    end_sec: float
    subtitle_text: Optional[str] = None
    output_filename: Optional[str] = None


def _format_clip_to_dict(clip: Any) -> Dict[str, Any]:
    """クリップオブジェクトをAPIレスポンス用の辞書形式に変換する"""
    return {
        "id": clip.id,
        "title": clip.title,
        "highlight_type": clip.highlight_type,
        "start_time": clip.start_time,
        "end_time": clip.end_time,
        "duration": clip.duration,
        "output_path": clip.output_path,
        "status": clip.status
    }


def _get_shorts_output_path(output_filename: Optional[str] = None) -> Path:
    """Shorts用の出力ファイルパスを決定する"""
    try:
        from safe_io import VAULT_OUTPUTS_DIR
        shorts_dir = VAULT_OUTPUTS_DIR / "shorts"
    except ImportError:
        shorts_dir = Path("output/shorts")

    shorts_dir.mkdir(parents=True, exist_ok=True)

    if output_filename:
        return shorts_dir / output_filename
    else:
        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        return shorts_dir / f"short_{ts}.mp4"


def _build_ffmpeg_filters(subtitle_text: Optional[str], duration: float) -> str:
    """縦型変換および字幕焼き込み用のFFmpegビデオフィルター文字列を構築する"""
    vf_filters = [
        "crop=ih*9/16:ih",
        "scale=1080:1920",
    ]

    if subtitle_text:
        escaped_text = subtitle_text.replace("'", "\\'").replace(":", "\\:")
        vf_filters.append(
            f"drawtext=text='{escaped_text}'"
            f":fontsize=56:fontcolor=white"
            f":borderw=3:bordercolor=black"
            f":x=(w-text_w)/2:y=(h-text_h)/2"
            f":enable='between(t,0,{duration})'"
        )

    return ",".join(vf_filters)


def _execute_ffmpeg_render(
    video_path: str,
    start_sec: float,
    duration: float,
    vf_str: str,
    output_path: Path
) -> Dict[str, Any]:
    """FFmpegコマンドを組み立てて実行し、結果を評価する"""
    from video_editor_engine import video_editor
    ffmpeg = video_editor.ffmpeg

    if not ffmpeg.is_available():
        return {"success": False, "error": "FFmpeg未検出"}

    encode_args = ffmpeg._get_encode_args("balanced")

    cmd = [
        "-y",
        "-ss", str(start_sec),
        "-i", video_path,
        "-t", str(duration),
        "-vf", vf_str,
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
    ] + encode_args + [
        str(output_path)
    ]

    success, output = ffmpeg.run_command(cmd, timeout=300)
    if success and output_path.exists():
        size_mb = output_path.stat().st_size / 1024 / 1024
        return {
            "success": True,
            "path": str(output_path),
            "size_mb": round(size_mb, 1),
            "duration_sec": round(duration, 1),
            "resolution": "1080x1920",
            "aspect_ratio": "9:16",
        }
    else:
        return {"success": False, "error": output[:300] if output else "Unknown error"}


@router.post("/candidates")
async def extract_shorts_candidates(req: ExtractCandidatesRequest) -> Dict[str, Any]:
    """
    本編のセグメントからShorts候補を自動抽出。
    フック/ハイライト/まとめの3戦略で最大5件を返す。
    """
    try:
        from services.shorts_generator import shorts_generator

        result = shorts_generator.extract_shorts_candidates(
            segments=req.segments,
            video_duration_sec=req.video_duration_sec,
            video_id=req.video_id,
        )
        return result

    except HTTPException:
        raise
    except (ValueError, TypeError, KeyError) as e:
        logger.error(f"Invalid inputs in extract_shorts_candidates: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except (ImportError, ModuleNotFoundError) as e:
        logger.error(f"Import error in extract_shorts_candidates: {e}")
        raise HTTPException(status_code=500, detail="Required service module not found")
    except RuntimeError as e:
        logger.error(f"Runtime error in extract_shorts_candidates: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate")
async def generate_shorts(req: GenerateShortsRequest) -> Dict[str, Any]:
    """
    ハイライトからショート動画を生成
    
    各ハイライトから60秒以内のクリップを抽出し、
    縦型フォーマット（9:16）に変換する。
    """
    try:
        from services.shorts_generator import shorts_generator
        
        result = await shorts_generator.generate_from_highlights(
            video_path=req.video_path,
            highlights=req.highlights,
            task_id=req.task_id
        )
        
        return {
            "success": True,
            "total_clips": result.total_clips,
            "completed_clips": result.completed_clips,
            "clips": [_format_clip_to_dict(clip) for clip in result.clips],
            "output_dir": result.output_dir,
            "message": result.message
        }
        
    except HTTPException:
        raise
    except (ValueError, TypeError, KeyError) as e:
        logger.error(f"Invalid inputs in generate_shorts: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except (ImportError, ModuleNotFoundError, AttributeError) as e:
        logger.error(f"Import or configuration error in generate_shorts: {e}")
        raise HTTPException(status_code=500, detail="Service configuration or layout error")
    except RuntimeError as e:
        logger.error(f"Runtime error in generate_shorts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list")
async def list_shorts(task_id: str = "") -> Dict[str, Any]:
    """生成済みショート動画一覧を取得"""
    try:
        from services.shorts_generator import shorts_generator
        
        clips = shorts_generator.get_clip_list(task_id=task_id)
        
        return {
            "success": True,
            "count": len(clips),
            "clips": clips
        }
        
    except HTTPException:
        raise
    except (ValueError, KeyError) as e:
        logger.error(f"Invalid inputs in list_shorts: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except (ImportError, ModuleNotFoundError) as e:
        logger.error(f"Import error in list_shorts: {e}")
        raise HTTPException(status_code=500, detail="Required service module not found")
    except RuntimeError as e:
        logger.error(f"Runtime error in list_shorts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/export")
async def export_shorts(req: ExportShortsRequest) -> Dict[str, Any]:
    """
    ショート動画をエクスポート
    
    指定されたクリップをZIPアーカイブまたは個別ファイルとしてエクスポート
    """
    try:
        from services.shorts_generator import shorts_generator
        
        clips = shorts_generator.get_clip_list(task_id=req.task_id)
        
        # 指定されたクリップをフィルタ
        export_clips = [c for c in clips if c["id"] in req.clip_ids]
        
        if not export_clips:
            return {
                "success": False,
                "message": "指定されたクリップが見つかりませんでした"
            }
        
        return {
            "success": True,
            "export_count": len(export_clips),
            "clips": export_clips,
            "message": f"{len(export_clips)}個のクリップをエクスポート準備完了"
        }
        
    except HTTPException:
        raise
    except (ValueError, KeyError) as e:
        logger.error(f"Invalid inputs in export_shorts: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except (ImportError, ModuleNotFoundError) as e:
        logger.error(f"Import error in export_shorts: {e}")
        raise HTTPException(status_code=500, detail="Required service module not found")
    except RuntimeError as e:
        logger.error(f"Runtime error in export_shorts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/render")
async def render_short(req: RenderShortRequest) -> Dict[str, Any]:
    """
    HR-2: Shorts候補を縦型（9:16, 1080x1920）でレンダリング。

    FFmpeg filtergraph:
    1. 指定範囲をカット（最大60秒）
    2. crop=ih*9/16:ih → scale=1080:1920 (センタークロップ)
    3. 字幕焼き込み（画面中央・大文字・太字白文字・黒縁取り）
    4. 音声ラウドネス正規化(-14 LUFS — Shorts推奨)
    """
    # 60秒制限
    duration = min(req.end_sec - req.start_sec, 60.0)
    if duration <= 0:
        raise HTTPException(status_code=400, detail="end_sec must be greater than start_sec")

    output_path = _get_shorts_output_path(req.output_filename)
    loop = asyncio.get_running_loop()

    def _do_render():
        try:
            vf_str = _build_ffmpeg_filters(req.subtitle_text, duration)
            return _execute_ffmpeg_render(
                video_path=req.video_path,
                start_sec=req.start_sec,
                duration=duration,
                vf_str=vf_str,
                output_path=output_path
            )
        except (ValueError, KeyError) as e:
            logger.error(f"Invalid render parameter: {e}")
            return {"success": False, "error": f"Invalid parameter: {e}"}
        except (ImportError, ModuleNotFoundError) as e:
            logger.error(f"Import failed during render execution: {e}")
            return {"success": False, "error": f"Import failed: {e}"}
        except (RuntimeError, OSError) as e:
            logger.error(f"Shorts render execution error: {e}")
            return {"success": False, "error": str(e)}

    result = await loop.run_in_executor(None, _do_render)

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Render failed"))

    return result


@router.post("/thumbnail")
async def generate_thumbnail_api(req: GenerateThumbnailRequest) -> Dict[str, Any]:
    """
    サムネイル画像生成および品質検証の自動化エンドポイント。
    StageBoundAgentと連携して動作する。
    """
    from usage_tracker.alert_system import ThumbnailResolver
    from agents.stage_bound_agent import StageBoundAgent
    import sqlite3
    import json
    
    db_path = req.db_path or "output/thumbnail_agent.db"
    resolver = ThumbnailResolver()
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=db_path)
    
    # タスクの登録
    await agent.register_task(task_id=req.task_id, initial_status="READY")
    
    # 実行
    await agent.start(resolver.resolve_thumbnail_task)
    
    # テストの同期実行をシミュレート、あるいは結果を待つための待機
    for _ in range(50):
        status = await agent.get_task_status(req.task_id)
        if status in ("COMPLETED", "FAILED"):
            break
        await asyncio.sleep(0.05)
        
    final_status = await agent.get_task_status(req.task_id)
    await agent.stop()
    
    if final_status == "FAILED":
        # エラー詳細を取得
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute("SELECT error FROM tasks WHERE id = ?", (req.task_id,))
            row = cursor.fetchone()
            error_msg = row[0] if row else "Unknown error"
        finally:
            conn.close()
        raise HTTPException(status_code=500, detail=f"Thumbnail task failed: {error_msg}")
        
    # 成功時の結果取得
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute("SELECT result FROM tasks WHERE id = ?", (req.task_id,))
        row = cursor.fetchone()
        result_data = json.loads(row[0]) if row and row[0] else {}
    finally:
        conn.close()
        
    return {
        "success": True,
        "task_id": req.task_id,
        "status": final_status,
        "result": result_data
    }


@router.get("/health")
async def health_check() -> Dict[str, str]:
    """ヘルスチェック"""
    return {"status": "ok", "service": "shorts_generator"}
