"""
Legacy Production Router — ユニークエンドポイントのみ残存 (Phase C)

v4.0 ルーターと重複していたエンドポイントは削除済み。

残存ユニークエンドポイント:
- POST /api/rhythm/split
- POST /api/transcribe
- GET  /api/transcribe/status
- GET  /api/task/{task_id}
- GET  /api/tasks
- POST /api/subtitle/transcribe
- POST /api/subtitle/export/{format}
- POST /api/preview/session
- POST /api/preview/step
- GET  /api/preview/report/{session_id}
- POST /api/preview/decision
- GET  /api/preview/sessions
- POST /api/video/color-grade
- GET  /api/video/color-presets
- POST /api/video/process/start
- GET  /api/video/process/status/{task_id}
- GET  /api/debug/video-tasks
- POST /api/video/realtime-preview
- GET  /api/video/list

削除済み（v4.0 routers/ に移行済み）:
  /api/render, /api/thumbnail/generate, /api/preview/generate,
  /api/preview/{preview_id}, /api/preview/cleanup, /api/audio/master,
  /api/video/preview/{task_id}, /api/video/download/{task_id}
"""

import os
import sys
import json
import asyncio
import logging
import uuid
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, BackgroundTasks, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from pydantic import BaseModel

from path_resolver import project_root, raw_videos_dir
from video_processor import video_processor, MOOD_SETTINGS
from websocket_handler import broadcaster

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Production Legacy"])

# --- Path setup ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "src")
DATA_PATH = os.path.join(SRC_DIR, "segments_a_plus_plus.json")
VIDEO_PATH = os.path.join(SRC_DIR, "sample_raw.mp4")

# --- Security & Limits ---
MAX_VIDEO_SIZE_MB = 500
# パストラバーサル防止の許可ルート。旧リポジトリの絶対パスが直書きされており、
# リポジトリを作り直した時点で「実在しない場所」を指していた。
# それはこの検査が常に不許可を返すことを意味する（安全側だが機能しない）。
ALLOWED_VIDEO_DIR = project_root().resolve()
ALLOWED_EXTENSIONS = [".mp4", ".mov", ".avi", ".mkv", ".mp3", ".wav"]
preview_semaphore = asyncio.Semaphore(2)

# --- グローバル状態 ---
_preview_sessions: dict = {}
_video_tasks = {}


# --- Request Models ---
class RenderRequest(BaseModel):
    mode: str
    style: str = "default"

class RhythmRequest(BaseModel):
    text: str
    target_chars: int = 13

class TranscribeRequest(BaseModel):
    video_path: Optional[str] = None
    language: str = "ja"
    with_proofreading: bool = True

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

class PreviewSessionRequest(BaseModel):
    session_id: Optional[str] = None

class StepSnapshotRequest(BaseModel):
    session_id: str
    step_name: str
    before_video: str
    after_video: str
    num_samples: int = 3
    srt_path: Optional[str] = None

class PreviewDecisionRequest(BaseModel):
    session_id: str
    decision: str
    feedback: str = ""

class VideoProcessRequest(BaseModel):
    video_paths: list = []
    mood: str = "elegant"
    guest_assets: list = []
    output_name: str = "output"

class RealtimePreviewRequest(BaseModel):
    video_path: str = ""
    mood: str = "elegant"
    duration: int = 30


# --- Utility ---
def validate_video_path(path: str, allow_none: bool = False) -> Path:
    """動画パスの検証（セキュリティ強化）"""
    if allow_none and not path:
        return None
    if not path:
        raise ValueError("File path is required")
    try:
        video_path = Path(path).resolve()
    except HTTPException:
        raise
    except Exception:
        raise ValueError(f"Invalid path format: {path}")
    try:
        video_path.relative_to(ALLOWED_VIDEO_DIR)
    except ValueError:
        raise ValueError("Access denied: Path outside allowed directory")
    if not video_path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    size_mb = video_path.stat().st_size / (1024 * 1024)
    if size_mb > MAX_VIDEO_SIZE_MB:
        raise ValueError(f"File too large: {size_mb:.1f}MB (max: {MAX_VIDEO_SIZE_MB}MB)")
    if video_path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {video_path.suffix}")
    return video_path


# ===== Rhythm ===== (Renderは v4.0 render.py に移行済み)

@router.post("/api/rhythm/split")
async def rhythm_split(req: RhythmRequest):
    """Semantic Split for AI Rhythm Master"""
    try:
        from ai_rhythm import semantic_split
        parts = semantic_split(req.text, req.target_chars)
        return {"parts": parts}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===== Transcription =====

@router.post("/api/transcribe")
async def trigger_transcription(background_tasks: BackgroundTasks, req: TranscribeRequest = TranscribeRequest()):
    """字幕生成API"""
    from settings_manager import settings_manager
    from task_store import task_store, create_progress_callback, TaskPhase
    from subtitle_engine import WhisperTranscriber

    if req.video_path and os.path.exists(req.video_path):
        video_path = req.video_path
    else:
        video_path = settings_manager.get_video_source()

    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Video source not found")

    task = task_store.create_task(video_path=video_path)
    task_id = task.task_id
    output_path = os.path.join(SRC_DIR, f"segments_{task_id[:8]}.json")

    def process_task():
        try:
            progress_callback = create_progress_callback(task_id)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            task_store.update_progress(task_id, TaskPhase.MODEL_LOADING, 5, "Whisperモデルをロード中...")
            transcriber = WhisperTranscriber(model_size="medium")
            segments = loop.run_until_complete(
                transcriber.transcribe_with_proofreading(
                    video_path=video_path, language=req.language,
                    beam_size=1, progress_callback=progress_callback
                )
            )
            task_store.update_progress(task_id, TaskPhase.SAVING, 95, "結果を保存中...")
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(segments, f, ensure_ascii=False, indent=2)
            task_store.complete_task(task_id, result_path=output_path)
        except Exception as e:
            import traceback
            traceback.print_exc()
            task_store.fail_task(task_id, str(e))

    background_tasks.add_task(process_task)
    return {"status": "started", "task_id": task_id, "message": "字幕生成を開始しました。"}


@router.get("/api/transcribe/status")
def get_transcription_status():
    """Checks transcription status (後方互換)"""
    status_file = os.path.join(SRC_DIR, "transcription_status.json")
    if os.path.exists(status_file):
        try:
            with open(status_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except HTTPException:
            raise
        except Exception:
            return {"status": "unknown", "message": "Reading status file failed"}
    return {"status": "idle", "message": "No active transcription"}


@router.get("/api/task/{task_id}")
def get_task_status(task_id: str):
    """タスク状態取得API"""
    from task_store import task_store
    task = task_store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.to_dict()


@router.get("/api/tasks")
def list_tasks(status: str = None):
    """タスク一覧取得API"""
    from task_store import task_store, TaskStatus
    status_filter = None
    if status:
        try:
            status_filter = TaskStatus(status)
        except ValueError:
            pass
    return {"tasks": task_store.list_tasks(status=status_filter)}


# ===== Subtitle =====

@router.post("/api/subtitle/transcribe")
async def transcribe_video(file: UploadFile):
    """動画をアップロードして字幕を生成"""
    import tempfile
    import pathlib
    from subtitle_engine import WhisperTranscriber

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=pathlib.Path(file.filename).suffix) as video_file:
            content = await file.read()
            video_file.write(content)
            video_path = video_file.name

        try:
            transcriber = WhisperTranscriber(model_size="medium")
            subtitles = await transcriber.transcribe_with_proofreading(
                video_path=video_path, language="ja", beam_size=1
            )
            # Phase D: ffprobe で動画長を取得（MoviePy 不要）
            import subprocess as _sp, json as _json
            _probe = _sp.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "json", video_path],
                capture_output=True, text=True, timeout=30
            )
            duration = float(_json.loads(_probe.stdout)["format"]["duration"])
            return {"subtitles": subtitles, "duration": duration, "segments_count": len(subtitles)}
        finally:
            if os.path.exists(video_path):
                os.remove(video_path)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")


@router.post("/api/subtitle/export/{format}")
async def export_subtitles(format: str, subtitles: list):
    """字幕を指定形式でエクスポート"""
    from subtitle_engine import SubtitleFormatter

    try:
        if format.lower() == "vtt":
            content = SubtitleFormatter.to_vtt(subtitles)
            media_type = "text/vtt"
            filename = "subtitles.vtt"
        elif format.lower() == "srt":
            content = SubtitleFormatter.to_srt(subtitles)
            media_type = "text/plain"
            filename = "subtitles.srt"
        else:
            raise HTTPException(status_code=400, detail="Format must be 'vtt' or 'srt'")

        return StreamingResponse(
            iter([content]), media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")


# ===== Progressive Preview Sessions ===== (thumbnail/generate, preview/generate, preview/{id}, preview/cleanup は v4.0 preview.py に移行済み)

@router.post("/api/preview/session")
async def create_preview_session(req: PreviewSessionRequest):
    """新規プレビューセッションを作成"""
    from progressive_preview import ProgressivePreview
    preview = ProgressivePreview(session_id=req.session_id)
    _preview_sessions[preview.session_id] = preview
    return {"session_id": preview.session_id, "output_dir": str(preview.output_dir), "status": "created"}


@router.post("/api/preview/step")
async def capture_step_snapshot(req: StepSnapshotRequest):
    """処理ステップ完了時のスナップショットをキャプチャ"""
    from progressive_preview import ProgressivePreview
    if req.session_id not in _preview_sessions:
        _preview_sessions[req.session_id] = ProgressivePreview(session_id=req.session_id)
    preview = _preview_sessions[req.session_id]
    try:
        result = preview.snapshot_step(step_name=req.step_name, before_video=req.before_video, after_video=req.after_video, num_samples=req.num_samples)
        return {"status": "success", "step_name": req.step_name, "comparisons": len(result.get("comparisons", [])), "output_dir": str(preview.output_dir)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/preview/report/{session_id}")
async def get_preview_report(session_id: str):
    """セッションのHTMLレポートを生成・取得"""
    from progressive_preview_report import PreviewReportGenerator
    if session_id not in _preview_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    preview = _preview_sessions[session_id]
    try:
        generator = PreviewReportGenerator()
        report_path = generator.generate_from_session_dir(str(preview.output_dir))
        return FileResponse(report_path, media_type="text/html")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/preview/decision")
async def submit_preview_decision(req: PreviewDecisionRequest):
    """プレビューの承認/却下判定を記録"""
    decision_log = Path("backend/temp/previews") / "decisions.json"
    decision_log.parent.mkdir(parents=True, exist_ok=True)
    decisions = []
    if decision_log.exists():
        try:
            with open(decision_log, 'r', encoding='utf-8') as f:
                decisions = json.load(f)
        except HTTPException:
            raise
        except Exception:
            pass
    decisions.append({"session_id": req.session_id, "decision": req.decision, "feedback": req.feedback, "timestamp": datetime.now().isoformat()})
    with open(decision_log, 'w', encoding='utf-8') as f:
        json.dump(decisions, f, ensure_ascii=False, indent=2)
    return {"status": "recorded", "decision": req.decision, "session_id": req.session_id}


@router.get("/api/preview/sessions")
async def list_preview_sessions():
    """全プレビューセッション一覧"""
    return {"sessions": list(_preview_sessions.keys()), "count": len(_preview_sessions)}


# ===== Color Grading ===== (audio/master は v4.0 preview.py に移行済み)

@router.post("/api/video/color-grade")
def apply_color_grading(video_path: str, preset: str = "cinematic"):
    """Apply color grading preset to video."""
    from color_grading import color_grading
    try:
        graded_video = color_grading.apply_preset(video_path, preset)
        return {"graded_video": graded_video, "preset": preset, "status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/video/color-presets")
def get_color_presets():
    """Get available color grading presets."""
    from color_grading import color_grading
    return {"presets": list(color_grading.PRESETS.keys()), "default": "cinematic"}


# ===== Video Processing (Phase 11) =====

@router.post("/api/video/process/start")
async def start_video_processing(background_tasks: BackgroundTasks, req: VideoProcessRequest):
    """本番動画処理を開始"""
    import time

    task_id = str(uuid.uuid4())
    task = video_processor.create_task(task_id=task_id, video_paths=req.video_paths, mood=req.mood, guest_assets=req.guest_assets, output_name=req.output_name)

    _video_tasks[task_id] = {
        "status": "starting", "progress": 0, "current_step": "初期化中...",
        "mood": req.mood, "video_paths": req.video_paths,
        "output_path": None, "preview_url": None, "error": None, "created_at": time.time()
    }

    loop = asyncio.get_running_loop()

    def process_video_task():
        try:
            def update_progress(t):
                _video_tasks[task_id]["status"] = t.phase.value
                _video_tasks[task_id]["progress"] = t.progress
                _video_tasks[task_id]["current_step"] = t.current_step
                _video_tasks[task_id]["output_path"] = t.output_path
                _video_tasks[task_id]["preview_url"] = t.preview_url
                _video_tasks[task_id]["error"] = t.error
                try:
                    coro = broadcaster.broadcast({"type": "video_progress", "task_id": task_id, "phase": t.phase.value, "progress": t.progress, "current_step": t.current_step})
                    asyncio.run_coroutine_threadsafe(coro, loop)
                except Exception:
                    pass
            video_processor.set_progress_callback(update_progress)
            video_processor.process_video(task_id)
        except Exception as e:
            _video_tasks[task_id]["status"] = "error"
            _video_tasks[task_id]["error"] = str(e)
            logger.error(f"Video processing error: {e}")

    background_tasks.add_task(process_video_task)
    mood_settings = MOOD_SETTINGS.get(req.mood.lower(), MOOD_SETTINGS["elegant"])
    return {"task_id": task_id, "status": "started", "message": f"ムード '{mood_settings.name}' で動画処理を開始しました", "mood_settings": {"name": mood_settings.name, "transition": mood_settings.transition, "telop_style": mood_settings.telop_style}}


@router.get("/api/video/process/status/{task_id}")
async def get_video_process_status(task_id: str):
    """動画処理の進捗状況を取得"""
    if task_id not in _video_tasks:
        raise HTTPException(status_code=404, detail="タスクが見つかりません")
    return _video_tasks[task_id]


@router.get("/api/debug/video-tasks")
async def debug_video_tasks():
    """デバッグ用：_video_tasksの状態を確認"""
    return {"task_count": len(_video_tasks), "task_ids": list(_video_tasks.keys()), "tasks": {k: {"status": v.get("status"), "progress": v.get("progress")} for k, v in _video_tasks.items()}}


# video/preview と video/download は v4.0 render.py に移行済み

@router.post("/api/video/realtime-preview")
async def generate_realtime_preview(background_tasks: BackgroundTasks, req: RealtimePreviewRequest):
    """リアルタイムプレビューを生成"""
    from preview_engine import preview_engine

    preview_id = str(uuid.uuid4())[:8]
    video_path = req.video_path
    if not video_path or not Path(video_path).exists():
        demo_dir = Path("raw_videos/AI Studio アップロード用動画")
        if demo_dir.exists():
            videos = list(demo_dir.glob("*.mp4"))
            if videos:
                video_path = str(videos[0])
    if not video_path or not Path(video_path).exists():
        raise HTTPException(status_code=400, detail="動画ファイルが見つかりません")

    def generate_preview_task():
        try:
            preview_engine.generate_preview(source_video=video_path, duration=req.duration)
        except Exception as e:
            logger.error(f"Preview generation failed: {e}")

    background_tasks.add_task(generate_preview_task)
    return {"preview_id": preview_id, "status": "generating", "message": f"プレビュー生成中（{req.duration}秒）", "source": Path(video_path).name, "preview_url": f"/api/video/preview/{preview_id}"}


@router.get("/api/video/list")
async def list_available_videos():
    """処理可能な動画一覧を取得"""
    videos = []
    raw_dirs = [
        Path("raw_videos/AI Studio アップロード用動画"),
        raw_videos_dir() / "AI Studio アップロード用動画",
        Path("../raw_videos/AI Studio アップロード用動画"),
    ]
    for raw_dir in raw_dirs:
        if raw_dir.exists():
            for video in raw_dir.glob("*.mp4"):
                size_mb = video.stat().st_size / 1024 / 1024
                videos.append({"name": video.name, "path": str(video.absolute()), "size_mb": round(size_mb, 1)})
            if videos:
                break
    return {"videos": videos, "count": len(videos)}
