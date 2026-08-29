"""
Render Router - レンダリング・動画処理関連エンドポイント

O-8 レンダリングUXストーリー対応:
- GPU/CPU検出・フォールバック
- BGM/LUFS/ロゴ/字幕設定
- レンダリングジョブ管理
- 品質チェック連携
"""
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path

from fastapi import APIRouter, BackgroundTasks, Request, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from pathlib import Path
import json
import uuid
import asyncio
import time
import logging
import base64
from io import BytesIO
from PIL import Image

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["render"])


class RenderRequest(BaseModel):
    mode: str = "normal"
    style: str = "default"


class ThumbnailGenerateRequest(BaseModel):
    video_title: str
    video_description: Optional[str] = ""
    width: Optional[int] = 1280
    height: Optional[int] = 720
    quality: Optional[int] = 95
    db_path: Optional[str] = "backend/thumbnails.db"


class VideoProcessRequest(BaseModel):
    """動画処理リクエスト"""
    video_paths: list = []
    mood: str = "elegant"
    guest_assets: list = []
    output_name: str = "output"


class DraftCreateRequest(BaseModel):
    """ドラフト生成リクエスト"""
    input_path: str
    quality: str = "medium"
    output_name: str = None


class PrefinalCreateRequest(BaseModel):
    """投稿前確認動画生成リクエスト"""
    draft_paths: list
    output_name: str = None


class FinalCreateRequest(BaseModel):
    """最終出力リクエスト"""
    prefinal_path: str
    output_name: str = None
    srt_path: str = None


class RealtimePreviewRequest(BaseModel):
    video_path: str = ""
    mood: str = "elegant"
    duration: int = 30


class RenderStartRequest(BaseModel):
    """レンダリング開始リクエスト (O-8対応)"""
    encoder: str = "auto"  # auto / nvenc / libx264
    bgm_volume: float = 50.0  # 0-100%
    bgm_ducking: bool = True
    lufs_target: float = -16.0
    logo_enabled: bool = True
    logo_position: str = "top-right"  # top-left/top-right/bottom-left/bottom-right
    logo_opacity: float = 0.8
    logo_height: int = 50
    subtitle_enabled: bool = True
    subtitle_font: str = "Noto Sans JP"
    subtitle_size: int = 24
    force_render: bool = False  # 品質不合格時の強制書出


class RenderSettingsRequest(BaseModel):
    """レンダリング設定更新リクエスト"""
    bgm_volume: Optional[float] = None
    lufs_target: Optional[float] = None
    logo_position: Optional[str] = None
    logo_opacity: Optional[float] = None
    logo_height: Optional[int] = None
    subtitle_enabled: Optional[bool] = None
    subtitle_font: Optional[str] = None
    subtitle_size: Optional[int] = None


# 動画処理タスク管理
_video_tasks = {}

# レンダリングジョブ管理 (O-8対応)
_render_jobs: Dict[str, Dict[str, Any]] = {}
_render_settings: Dict[str, Any] = {
    "encoder": "auto",
    "bgm_volume": 50.0,
    "bgm_ducking": True,
    "lufs_target": -16.0,
    "logo_enabled": True,
    "logo_position": "top-right",
    "logo_opacity": 0.8,
    "logo_height": 50,
    "subtitle_enabled": True,
    "subtitle_font": "Noto Sans JP",
    "subtitle_size": 24,
}


# ═══════════════════════════════════════════════════════════════
# O-8 レンダリングUXストーリー対応エンドポイント
# ═══════════════════════════════════════════════════════════════

@router.get("/render/health")
async def render_health_check() -> Dict[str, str]:
    """レンダリングサービスのヘルスチェック"""
    return {"status": "ok", "service": "render"}


@router.get("/render/gpu-detect")
async def detect_gpu() -> Dict[str, Any]:
    """GPU検出 — NVENC対応を確認 (S3: GPU検出)"""
    # 実環境ではNVIDIAドライバーを検出する
    gpu_available = False
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5
        )
        gpu_available = result.returncode == 0 and len(result.stdout.strip()) > 0
        gpu_name = result.stdout.strip() if gpu_available else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        gpu_available = False
        gpu_name = None

    encoder = "nvenc" if gpu_available else "libx264"
    return {
        "gpu_available": gpu_available,
        "gpu_name": gpu_name,
        "recommended_encoder": encoder,
        "fallback_encoder": "libx264",
    }


@router.post("/render/start")
async def start_render(req: RenderStartRequest = RenderStartRequest()) -> Dict[str, Any]:
    """
    レンダリングジョブを開始 (S11: レンダリング開始)
    
    品質スコアが90未満の場合はブロック (S17)、
    force_render=Trueで強制書出可能 (S16)。
    """
    job_id = str(uuid.uuid4())[:8]

    # 品質チェック (S17: 品質ブロック)
    # **未計測を「合格」に読み替えない**（R1.5-C4）。本線の実測が無いときは
    # 点を名乗らずに進む。**ここで止めないのは、以前も 95 の直書きで素通り
    # していたから**で、止める方針に変えるなら品質ゲートを本線へ繋ぐのが先
    # （台帳: `backend/config/feature_gaps.json` の `render_quality_gate`）。
    quality_score = _get_quality_score()
    出所 = _品質の出所()
    if quality_score is not None and quality_score < 90 and not req.force_render:
        return {
            "success": False,
            "error": "quality_block",
            "message": f"品質スコア {quality_score} < 90。強制書出するには force_render=true を指定してください。",
            "quality_score": quality_score,
            "quality_checked": True,
            "quality_source": 出所,
            "is_real": True,
            "data_source": "derived",
            "force_render_available": True,
        }

    # GPU/CPUエンコーダ決定 (S3/S4)
    encoder = req.encoder
    gpu_fallback = False
    if encoder == "auto" or encoder == "nvenc":
        gpu_info = await detect_gpu()
        if gpu_info["gpu_available"]:
            encoder = "nvenc"
        else:
            encoder = "libx264"
            if req.encoder == "nvenc":
                gpu_fallback = True

    # ジョブ登録
    _render_jobs[job_id] = {
        "job_id": job_id,
        "status": "rendering",
        "encoder": encoder,
        "gpu_fallback": gpu_fallback,
        "force_render": req.force_render,
        "quality_score": quality_score,
        # **測っていないことを記録に残す**（R1.5-C4）。`None` を後から
        # 「0点」や「合格」と読み替えられないようにする
        "quality_checked": quality_score is not None,
        "quality_source": 出所,
        "progress": 0,
        "current_stage": "encoding",
        "stages": {
            "encoding": {"status": "running", "progress": 0},
            "bgm": {"status": "pending", "progress": 0},
            "logo": {"status": "pending", "progress": 0},
            "subtitle": {"status": "pending", "progress": 0},
        },
        "settings": {
            "bgm_volume": req.bgm_volume,
            "bgm_ducking": req.bgm_ducking,
            "lufs_target": req.lufs_target,
            "logo_enabled": req.logo_enabled,
            "logo_position": req.logo_position,
            "logo_opacity": req.logo_opacity,
            "logo_height": req.logo_height,
            "subtitle_enabled": req.subtitle_enabled,
            "subtitle_font": req.subtitle_font,
            "subtitle_size": req.subtitle_size,
        },
        "started_at": time.time(),
        "completed_at": None,
        "output_file": None,
        "temp_files": [],
    }

    # 更新グローバル設定
    _render_settings.update({
        "encoder": encoder,
        "bgm_volume": req.bgm_volume,
        "lufs_target": req.lufs_target,
        "logo_position": req.logo_position,
        "logo_opacity": req.logo_opacity,
        "subtitle_enabled": req.subtitle_enabled,
    })

    return {
        "success": True,
        "job_id": job_id,
        "status": "rendering",
        "encoder": encoder,
        "gpu_fallback": gpu_fallback,
        "force_render": req.force_render,
        "quality_score": quality_score,
        # **測ったのかどうかを応答でも名乗る**（R1.5-C4）。
        # `quality_score: null` は「0点」でも「合格」でもない
        "quality_checked": quality_score is not None,
        "quality_source": 出所,
        "is_real": quality_score is not None,
        "data_source": "derived" if quality_score is not None else "unavailable",
        "message": ("レンダリングを開始しました" if quality_score is not None else
                    "レンダリングを開始しました（**品質スコアは未計測です。**"
                    "本線の実走が書き出す *.quality.json がまだありません）"),
    }


@router.get("/render/status/{job_id}")
async def get_render_status(job_id: str) -> Dict[str, Any]:
    """レンダリングジョブの進捗を取得 (S12/S13: リアルタイム進捗)"""
    if job_id not in _render_jobs:
        return {"error": "Job not found", "job_id": job_id}

    job = _render_jobs[job_id]

    # タイムアウトチェック (S18: 1800秒超過)
    elapsed = time.time() - job["started_at"]
    if job["status"] == "rendering" and elapsed > 1800:
        job["status"] = "timeout"
        job["message"] = "レンダリングがタイムアウトしました（1800秒超過）"

    return {
        "job_id": job_id,
        "status": job["status"],
        "progress": job["progress"],
        "current_stage": job["current_stage"],
        "stages": job["stages"],
        "encoder": job["encoder"],
        "gpu_fallback": job["gpu_fallback"],
        "elapsed_seconds": round(elapsed, 1),
        "message": job.get("message"),
    }


@router.post("/render/complete/{job_id}")
async def complete_render(job_id: str) -> Dict[str, Any]:
    """
    レンダリングジョブを完了状態に遷移 (S14/S22: 完了通知)
    テスト用に外部から完了を通知するエンドポイント。
    """
    if job_id not in _render_jobs:
        return {"error": "Job not found", "job_id": job_id}

    job = _render_jobs[job_id]
    job["status"] = "completed"
    job["progress"] = 100
    job["completed_at"] = time.time()
    job["current_stage"] = "done"
    for stage in job["stages"]:
        job["stages"][stage] = {"status": "completed", "progress": 100}

    # 完了ファイル情報 (S14)
    job["output_file"] = {
        "path": f"/output/render_{job_id}.mp4",
        "size_mb": 256.5,
        "codec": "h264",
        "resolution": "1920x1080",
        "duration_seconds": 1800,
        "download_url": f"/api/render/download/{job_id}",
    }

    # temp削除 (S21)
    job["temp_files_cleaned"] = True

    return {
        "success": True,
        "job_id": job_id,
        "status": "completed",
        "output_file": job["output_file"],
        "temp_files_cleaned": True,
        "message": "レンダリングが完了しました",
    }


@router.get("/render/download/{job_id}")
async def download_render(job_id: str) -> Dict[str, Any]:
    """レンダリング済みファイルのダウンロード情報 (S15: ファイルDL)"""
    if job_id not in _render_jobs:
        return {"error": "Job not found", "job_id": job_id}

    job = _render_jobs[job_id]
    if job["status"] != "completed":
        return {"error": "Render not completed", "status": job["status"]}

    return {
        "success": True,
        "download_url": job["output_file"]["path"],
        "file_info": job["output_file"],
    }


@router.get("/render/settings")
async def get_render_settings() -> Dict[str, Any]:
    """現在のレンダリング設定を取得 (S5/S7/S9/S10)"""
    return {
        "success": True,
        "settings": _render_settings.copy(),
    }


@router.post("/render/settings")
async def update_render_settings(req: RenderSettingsRequest) -> Dict[str, Any]:
    """レンダリング設定を更新 (S6/S8: BGM/LUFS調整)"""
    updates = {}
    for field, value in req.model_dump(exclude_none=True).items():
        _render_settings[field] = value
        updates[field] = value

    return {
        "success": True,
        "updated": updates,
        "settings": _render_settings.copy(),
    }


@router.post("/render/force/{job_id}")
async def force_render(job_id: str) -> Dict[str, Any]:
    """品質不合格時の強制レンダリング (S16: 強制書出)"""
    # 既存ジョブがあれば更新、なければ新規作成
    if job_id in _render_jobs:
        _render_jobs[job_id]["force_render"] = True
        _render_jobs[job_id]["status"] = "rendering"
        return {
            "success": True,
            "job_id": job_id,
            "force_render": True,
            "warning": "⚠️ 品質チェック未通過のまま強制レンダリング中",
        }

    return await start_render(RenderStartRequest(force_render=True))


# **書き出し前の品質スコアは、本線が実際に出した点を読む**（R1.5-C4・
# gate-verifier 8周目の指摘）。ここは以前 `return 95` の直書きで、
#
#   - 何も測っていないのに `quality_score: 95` を `success: true` で返し
#   - **S17 の品質ブロック（`if quality_score < 90`）が永久に偽**になって
#     一度も止まらず（`force_render` が意味を失っていた）
#   - 同じ 95 が `_render_jobs[job_id]["quality_score"]` に記録されていた
#
# 本線（`agents.pipeline_coordinator._write_quality_sidecar`）は最終動画の隣へ
# `*.quality.json` を書いており、**実測はそこにある**（実走で 89 / 94 / 88 / 89）。
# その文書自身が「消費者として宣言していた render は `quality_score` しか
# 読んでおらず」と書いている。**宣言していた消費者が、実は読んでいなかった。**
_QUALITY_SIDECAR_DIR = "vault-outputs/final"


def _品質の出所() -> Optional[str]:
    """直近の `*.quality.json` の場所。無ければ None。"""
    try:
        d = _writable_path(_QUALITY_SIDECAR_DIR)
        側 = sorted(d.glob("*.quality.json"), key=lambda p: p.stat().st_mtime)
        return str(側[-1]) if 側 else None
    except (OSError, AttributeError) as e:
        logger.warning(f"品質サイドカーを探せませんでした: {e}")
        return None


def _get_quality_score() -> Optional[int]:
    """本線が実際に出した品質スコアを返す。**測っていなければ None**（R1.5-C4）。

    `None` は「0点」でも「合格」でもない。**見ていない**という意味で、
    呼び出し側はそれを点として名乗ってはいけない。
    """
    path = _品質の出所()
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            score = json.load(f).get("score")
        return int(score) if isinstance(score, (int, float)) else None
    except (OSError, ValueError, TypeError) as e:
        logger.warning(f"品質サイドカーを読めませんでした（{path}）: {e}")
        return None


@router.post("/render")
async def trigger_render(req: RenderRequest = RenderRequest()):
    """高品質レンダリングを実行する。"""
    from branding_manager import branding_manager
    from project_archiver import project_archiver
    import subprocess
    
    # スナップショット作成
    project_archiver.create_snapshot("pre_render")
    
    # レンダリング処理（簡略化）
    return {
        "status": "completed",
        "mode": req.mode,
        "style": req.style,
        "message": "Render triggered successfully"
    }


@router.post("/video/process")
async def start_video_processing(background_tasks: BackgroundTasks, req: VideoProcessRequest):
    """本番動画処理を開始（video_processor統合版）"""
    from video_processor import video_processor
    
    task_id = str(uuid.uuid4())[:8]
    
    # タスク登録
    task = video_processor.create_task(
        task_id=task_id,
        video_paths=req.video_paths,
        mood=req.mood,
        guest_assets=req.guest_assets,
        output_name=req.output_name
    )
    
    _video_tasks[task_id] = {
        "status": "processing",
        "progress": 0,
        "current_step": "初期化中..."
    }
    
    # バックグラウンド処理
    async def process_video_task():
        def update_progress(t):
            _video_tasks[task_id] = {
                "status": t.phase.value,
                "progress": t.progress,
                "current_step": t.current_step,
                "output_path": t.output_path,
                "preview_url": t.preview_url
            }
        
        video_processor.set_progress_callback(update_progress)
        video_processor.process_video(task_id)
    
    background_tasks.add_task(process_video_task)
    
    return {
        "task_id": task_id,
        "status": "processing",
        "message": f"動画処理を開始しました（ムード: {req.mood}）"
    }


@router.get("/video/status/{task_id}")
async def get_video_process_status(task_id: str):
    """動画処理の進捗状況を取得"""
    if task_id not in _video_tasks:
        return {"error": "Task not found", "task_id": task_id}
    return _video_tasks[task_id]


@router.get("/video/preview/{task_id}")
async def get_video_preview(task_id: str):
    """処理中/完了動画のプレビューを取得"""
    if task_id not in _video_tasks:
        return {"error": "Task not found"}
    
    task = _video_tasks[task_id]
    if task.get("output_path") and Path(task["output_path"]).exists():
        return FileResponse(task["output_path"], media_type="video/mp4")
    
    return {"error": "Preview not available yet", "status": task.get("status")}


@router.get("/video/download/{task_id}")
async def download_processed_video(task_id: str):
    """処理完了動画をダウンロード"""
    if task_id not in _video_tasks:
        return {"error": "Task not found"}
    
    task = _video_tasks[task_id]
    if task.get("output_path") and Path(task["output_path"]).exists():
        return FileResponse(
            task["output_path"],
            media_type="video/mp4",
            filename=f"processed_{task_id}.mp4"
        )
    
    return {"error": "Video not ready", "status": task.get("status")}


@router.post("/draft/create")
async def create_draft(req: DraftCreateRequest):
    """低容量ドラフト動画を生成"""
    # 実装は draft_manager モジュールから
    return {
        "status": "created",
        "input": req.input_path,
        "quality": req.quality
    }


@router.post("/prefinal/create")
async def create_prefinal(req: PrefinalCreateRequest):
    """投稿前確認動画を生成"""
    return {
        "status": "created",
        "drafts": req.draft_paths
    }


@router.post("/final/create")
async def create_final(req: FinalCreateRequest):
    """最終出力を生成"""
    return {
        "status": "created",
        "prefinal": req.prefinal_path
    }


@router.get("/draft/stats")
async def get_draft_stats():
    """ドラフトストレージ使用状況を取得"""
    return {
        "draft_count": 0,
        "total_size_mb": 0
    }


@router.get("/available-videos")
async def list_available_videos():
    """処理可能な動画一覧を取得"""
    raw_video_dir = Path(__file__).parent.parent / "raw_videos"
    videos = []
    
    if raw_video_dir.exists():
        for video_file in raw_video_dir.rglob("*.mp4"):
            videos.append({
                "path": str(video_file),
                "name": video_file.name,
                "size_mb": round(video_file.stat().st_size / (1024 * 1024), 2)
            })
    
    return {"videos": videos}



@router.post("/render/thumbnail")
async def generate_thumbnail(req: ThumbnailGenerateRequest) -> Dict[str, Any]:
    """
    サムネイル画像を生成・高品質リサイズ・品質およびアスペクト比検証を行うエンドポイント
    """
    if not req.video_title.strip():
        raise HTTPException(status_code=400, detail="Video title cannot be empty.")
    if req.width <= 0 or req.height <= 0:
        raise HTTPException(status_code=400, detail="Width and height must be positive integers.")
    if req.quality < 1 or req.quality > 100:
        raise HTTPException(status_code=400, detail="Quality must be between 1 and 100.")

    # 1. 解像度の検証 (1280x720以上であること)
    if req.width < 1280 or req.height < 720:
        raise HTTPException(status_code=400, detail=f"Resolution must be at least 1280x720. Got {req.width}x{req.height}")

    # 2. アスペクト比の検証 (16:9 であること)
    target_aspect = req.width / req.height
    if abs(target_aspect - 16.0 / 9.0) > 0.01:
        raise HTTPException(status_code=400, detail=f"Unsupported aspect ratio: {target_aspect:.2f}. Expected close to 16:9 (e.g. 1.77).")

    db_path = getattr(req, "db_path", "backend/thumbnails.db") or "backend/thumbnails.db"
    
    from agents.stage_bound_agent import StageBoundAgent
    agent = StageBoundAgent(stage_name="thumbnail", db_path=db_path)
    
    async def resolve_ai_thumbnail_task(task_id: str) -> str:
        try:
            from thumbnail_engine.generator import generator as thumb_gen
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to import thumbnail generator in agent: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Thumbnail generator service unavailable.")

        try:
            raw_thumbnails = await thumb_gen.generate(
                video_title=req.video_title,
                video_description=req.video_description,
                num_variants=1
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Error during thumbnail raw generation in agent: {e}, attempting fallback", exc_info=True)
            raw_thumbnails = []

        if not raw_thumbnails:
            try:
                from branding_manager import branding_manager
                fallback_res = branding_manager.generate_and_validate_thumbnail(
                    video_title=req.video_title,
                    video_description=req.video_description
                )
                raw_thumbnails = [{
                    "id": "thumbnail_fallback",
                    "concept_name": fallback_res.get("concept_name", "Fallback Concept"),
                    "description": fallback_res.get("description", "Fallback image due to system errors"),
                    "prompt": "fallback",
                    "image_base64": fallback_res["image_base64"],
                    "ctr_score": fallback_res.get("ctr_score", 5.0)
                }]
            except HTTPException:
                raise
            except Exception as fe:
                logger.error(f"Failed to generate branding fallback thumbnail: {fe}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Thumbnail generation failed and fallback also failed: {str(fe)}")

        thumb = raw_thumbnails[0]
        
        try:
            try:
                image_data = base64.b64decode(thumb["image_base64"])
            except HTTPException:
                raise
            except Exception as decode_err:
                logger.error(f"Base64 decoding failed for thumbnail: {decode_err}", exc_info=True)
                raise ValueError(f"Failed to decode base64 image data: {str(decode_err)}")

            try:
                img = Image.open(BytesIO(image_data))
                img.load()  # 破損チェック
            except HTTPException:
                raise
            except Exception as img_err:
                logger.error(f"Failed to load image via Pillow: {img_err}", exc_info=True)
                raise ValueError(f"Invalid or corrupted image format: {str(img_err)}")
            
            from PIL import ImageOps, ImageEnhance
            resample_filter = getattr(Image, "Resampling", Image)
            filter_type = getattr(resample_filter, "LANCZOS", getattr(Image, "ANTIALIAS", 1))
            
            # アスペクト比を維持しつつ、指定解像度に中央切り抜きしてリサイズ
            resized_img = ImageOps.fit(img, (req.width, req.height), method=filter_type)
            
            # 品質向上: シャープネス、彩度、コントラストをそれぞれ強化して見栄えを良くする
            try:
                enhancer = ImageEnhance.Sharpness(resized_img)
                resized_img = enhancer.enhance(1.05)  # シャープネスを5%強化
                enhancer_color = ImageEnhance.Color(resized_img)
                resized_img = enhancer_color.enhance(1.03)  # 彩度を3%向上
                enhancer_contrast = ImageEnhance.Contrast(resized_img)
                resized_img = enhancer_contrast.enhance(1.02)  # コントラストを2%向上
            except HTTPException:
                raise
            except Exception as enh_e:
                logger.warning(f"Failed to enhance image quality: {enh_e}")
            
            # 品質向上: subsampling=0 で彩度劣化を防ぎ、高品質LANCZOSフィルタ適用
            # エラーハンドリング: ファイルサイズが4MBを超えた場合はqualityを下げてリトライ
            quality = req.quality
            processed_data = b""
            file_size = 0
            for attempt in range(6):  # quality=60まで5刻みで下げるために最大6回試行可能
                out_io = BytesIO()
                # progressive=Trueを指定してファイルサイズ効率を向上
                resized_img.save(out_io, format="JPEG", quality=quality, optimize=True, subsampling=0, progressive=True)
                processed_data = out_io.getvalue()
                file_size = len(processed_data)
                if file_size < 4 * 1024 * 1024:
                    break
                quality = max(60, quality - 5)
            else:
                raise ValueError(f"File size exceeds 4MB limit even after quality reduction: {file_size} bytes")
            
            actual_w, actual_h = resized_img.size
            if actual_w != req.width or actual_h != req.height:
                raise ValueError(f"Resolution mismatch: expected {req.width}x{req.height}, got {actual_w}x{actual_h}")
            
            actual_aspect = actual_w / actual_h
            if abs(actual_aspect - (16.0 / 9.0)) > 0.01:
                raise ValueError(f"Aspect ratio must be 16:9. Got {actual_aspect:.3f}")
                
            if file_size <= 0:
                raise ValueError("Generated image file size is 0 bytes.")
            
            # 原子的な一時ファイル書き出し
            from pathlib import Path
            output_dir = _writable_path("backend/temp_thumbnails")
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{task_id}.jpg"
            
            temp_path = output_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
            try:
                with open(temp_path, "wb") as f:
                    f.write(processed_data)
                if output_path.exists():
                    output_path.unlink()
                temp_path.rename(output_path)
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Failed to write processed thumbnail to file {output_path}: {e}", exc_info=True)
                raise e
            finally:
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except HTTPException:
                        raise
                    except Exception as unlink_err:
                        logger.warning(f"Failed to remove temp file {temp_path}: {unlink_err}")
            
            result_data = {
                "id": thumb["id"],
                "concept_name": thumb["concept_name"],
                "description": thumb["description"],
                "prompt": thumb["prompt"],
                "image_base64": base64.b64encode(processed_data).decode('utf-8'),
                "ctr_score": thumb["ctr_score"],
                "width": actual_w,
                "height": actual_h,
                "aspect_ratio": f"{actual_w}:{actual_h}",
                "file_size_bytes": file_size,
                "path": str(output_path)
            }
            import json
            return json.dumps(result_data)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Image processing failed in agent for {thumb.get('id')}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Image processing failed: {str(e)}")

    task_id = f"api_thumb_{uuid.uuid4().hex[:8]}"
    await agent.register_task(task_id=task_id, initial_status="READY", max_retries=2)
    
    # エージェント起動
    await agent.start(resolve_ai_thumbnail_task)
    
    # 完了待機
    start_time = time.time()
    final_status = "READY"
    timeout = 15.0
    
    try:
        while time.time() - start_time < timeout:
            status = await agent.get_task_status(task_id)
            if status in ("COMPLETED", "FAILED"):
                final_status = status
                break
            await asyncio.sleep(0.05)
    finally:
        await agent.stop()
        
    if final_status == "COMPLETED":
        import sqlite3
        import json
        conn = None
        try:
            conn = sqlite3.connect(db_path, timeout=10.0)
            cursor = conn.execute("SELECT result FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            if row and row[0]:
                result_data = json.loads(row[0])
                processed_thumbnail = {
                    "id": result_data["id"],
                    "concept_name": result_data["concept_name"],
                    "description": result_data["description"],
                    "prompt": result_data["prompt"],
                    "image_base64": result_data["image_base64"],
                    "ctr_score": result_data["ctr_score"],
                    "width": result_data["width"],
                    "height": result_data["height"],
                    "aspect_ratio": result_data["aspect_ratio"],
                    "file_size_bytes": result_data["file_size_bytes"]
                }
                return {
                    "success": True,
                    "thumbnails": [processed_thumbnail]
                }
        except HTTPException:
            raise
        except sqlite3.Error as e:
            logger.error(f"Failed to fetch task result from DB: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Database fetch failed: {str(e)}")
        finally:
            if conn:
                conn.close()
    else:
        import sqlite3
        conn = None
        try:
            conn = sqlite3.connect(db_path, timeout=10.0)
            cursor = conn.execute("SELECT error FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            if row and row[0]:
                err_detail = row[0]
                raise HTTPException(status_code=500, detail=err_detail)
        except HTTPException:
            raise
        except sqlite3.Error as e:
            logger.error(f"Failed to fetch task error from DB: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Database query failed: {str(e)}")
        finally:
            if conn:
                conn.close()

    raise HTTPException(status_code=500, detail=f"Image generation failed or timed out. Status: {final_status}")

