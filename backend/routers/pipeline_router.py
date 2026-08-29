try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path

from routers.pipeline_default_states import (
    get_initial_pipeline_state,
    get_initial_transcription_state,
    get_initial_proofreading_state,
    get_initial_quality_gate_state,
    get_initial_improvement_state,
    get_default_transcription_segments,
    get_default_proofreading_segments,
)
"""
Pipeline Router — 制作パイプライン REST API
IMP-D05: フロントエンドからパイプラインを起動・監視・承認するための API

エンドポイント:
  POST /api/pipeline/start       パイプライン起動
  GET  /api/pipeline/status      ステータス取得（ポーリング）
  POST /api/pipeline/approve     チェックポイント承認
  GET  /api/pipeline/videos      vault-assets 動画リスト
  GET  /api/pipeline/stream/{type}  完了動画配信（preview/final）
"""
import json
import glob
import asyncio
import logging
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional, List
import subprocess

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from path_resolver import backend_dir, vault_assets_dir

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])

# ============================================================
# パイプライン状態管理（インメモリ）
# ============================================================

_pipeline_state = get_initial_pipeline_state()


def _reset_state():
    """パイプライン状態をリセット"""
    _pipeline_state.update({
        "session_id": None,
        "status": "idle",
        "current_stage": 0,
        "checkpoint": None,
        "video_path": "",
        "video_paths": [],
        "video_count": 0,
        "target_minutes": 20,
        "started_at": None,
        "completed_at": None,
        "error": None,
        "result": None,
    })
    for stage in _pipeline_state["stages"]:
        stage["status"] = "pending"
        stage["detail"] = ""


def _update_stage(index: int, status: str, detail: str = "", progress: int = -1, data: dict = None):
    """ステージ状態を更新"""
    if 0 <= index < len(_pipeline_state["stages"]):
        _pipeline_state["stages"][index]["status"] = status
        _pipeline_state["stages"][index]["detail"] = detail
        if progress >= 0:
            _pipeline_state["stages"][index]["progress"] = progress
        if data is not None:
            _pipeline_state["stages"][index]["data"] = data
        _pipeline_state["current_stage"] = index




# ============================================================
# WebSocket Pipeline Progress (Proposal 1)
# ============================================================

class PipelineWSManager:
    def __init__(self):
        self.connections: list = []

    async def connect(self, ws):
        await ws.accept()
        self.connections.append(ws)
        logger.info(f"Pipeline WS connected. Total: {len(self.connections)}")

    def disconnect(self, ws):
        if ws in self.connections:
            self.connections.remove(ws)

    async def broadcast(self, data: dict):
        dead = []
        for ws in self.connections:
            try:
                await ws.send_json(data)
            except HTTPException:
                raise
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)
            logger.debug(f"Pipeline WS dead connection removed. Remaining: {len(self.connections)}")

pipeline_ws = PipelineWSManager()


# Coordinator-Worker 統合 (唯一の実行パス)
from agents.pipeline_coordinator import pipeline_coordinator, PipelineContext

def _coordinator_progress(index, status, detail='', progress=-1, data=None):
    _update_stage(index, status, detail, progress, data)

pipeline_coordinator.set_progress_callback(_coordinator_progress)

async def _coordinator_ws_broadcast(data):
    await pipeline_ws.broadcast(data)

logger.info("PipelineCoordinator loaded (Harness-integrated single path)")


# ============================================================
# 複数動画結合
# ============================================================

def _probe_video_metadata(path: str, ffmpeg_path: str) -> dict:
    """FFprobeで解像度とFPSを取得"""
    import json as _json
    from pathlib import Path as _Path
    ffprobe_path = str(_Path(ffmpeg_path).parent / _Path(ffmpeg_path).name.replace("ffmpeg", "ffprobe"))
    if not _Path(ffprobe_path).exists():
        ffprobe_path = "ffprobe"  # PATH上のffprobeにフォールバック
    try:
        r = subprocess.run(
            [ffprobe_path, "-v", "quiet",
             "-print_format", "json", "-show_streams", path],
            capture_output=True, text=True, encoding="utf-8", timeout=30
        )
        data = _json.loads(r.stdout)
        for s in data.get("streams", []):
            if s.get("codec_type") == "video":
                w = int(s.get("width", 0))
                h = int(s.get("height", 0))
                fps_str = s.get("r_frame_rate", "30/1")
                try:
                    num, den = fps_str.split("/")
                    fps = round(int(num) / int(den), 2)
                except (ValueError, ZeroDivisionError):
                    fps = 30.0
                return {"width": w, "height": h, "fps": fps}
    except subprocess.TimeoutExpired as e:
        logger.error(f"⚠️ FFprobe probe timed out for path: {path}")
        raise HTTPException(500, f"FFprobe timeout expired for path: {path}") from e
    except Exception as e:
        logger.warning(f"⚠️ FFprobe probe failed for path {path}: {e}")
        return {"width": 0, "height": 0, "fps": 30.0}
    return {"width": 0, "height": 0, "fps": 30.0}


async def _merge_videos(paths: List[str], needs_normalize: bool = False) -> str:
    """複数動画を FFmpeg concat で結合

    BUG-PV05修正: 結合前に解像度/FPSを検査し、不一致がある場合は
    全ファイルを統一フォーマット(720p/30fps)に正規化してから結合する。
    """
    try:
        from video_editor_engine import FFmpegEditor
        ffmpeg_editor = FFmpegEditor()
        ffmpeg_path = ffmpeg_editor.ffmpeg_path
        use_gpu = ffmpeg_editor.use_gpu
    except HTTPException:
        raise
    except Exception:
        ffmpeg_path = "ffmpeg"
        use_gpu = False

    try:
        from safe_io import VAULT_OUTPUTS_DIR
        merge_dir = VAULT_OUTPUTS_DIR / "merged"
    except ImportError:
        merge_dir = Path("output/merged")
    merge_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    merged_output = str(merge_dir / f"merged_{timestamp}.mp4")

    loop = asyncio.get_running_loop()

    # ━━━ BUG-PV05: 解像度/FPS検査 + 正規化 ━━━
    # 全ファイルの解像度/FPSを検査
    probes = await loop.run_in_executor(None, lambda: [_probe_video_metadata(p, ffmpeg_path) for p in paths])
    logger.info(f"📐 動画プローブ結果: {probes}")

    # 不一致検出
    widths = set(p["width"] for p in probes)
    heights = set(p["height"] for p in probes)
    fpses = set(p["fps"] for p in probes)
    needs_normalize = len(widths) > 1 or len(heights) > 1 or len(fpses) > 1

    if needs_normalize:
        logger.warning(f"⚠️ 解像度/FPS不一致検出: {widths}x{heights} @ {fpses}fps — 正規化実行")
        # 最も一般的な解像度を採用(720p/30fps)
        target_w, target_h, target_fps = 1280, 720, 30

        normalized_paths = []
        for i, p in enumerate(paths):
            probe = probes[i]
            if probe["width"] != target_w or probe["height"] != target_h or probe["fps"] != target_fps:
                norm_path = str(merge_dir / f"_norm_{i:02d}_{timestamp}.mp4")
                encode_args = (["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23"]
                               if use_gpu else
                               ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"])
                norm_cmd = [
                    ffmpeg_path, "-y", "-i", p,
                    "-vf", f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,fps={target_fps}",
                    *encode_args, "-c:a", "aac", "-ar", "48000", "-ac", "2",
                    norm_path
                ]
                logger.info(f"📐 正規化中 [{i+1}/{len(paths)}]: {Path(p).name} ({probe['width']}x{probe['height']}@{probe['fps']}fps → {target_w}x{target_h}@{target_fps}fps)")
                r = await loop.run_in_executor(
                    None, lambda cmd=norm_cmd: subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
                )
                if r.returncode == 0 and Path(norm_path).exists():
                    normalized_paths.append(norm_path)
                else:
                    logger.error(f"正規化失敗 [{i}]: {r.stderr[:200]}")
                    normalized_paths.append(p)  # フォールバック: 元ファイル使用
            else:
                normalized_paths.append(p)

        concat_paths = normalized_paths
    else:
        concat_paths = paths
        logger.info(f"📐 解像度/FPS統一 — 正規化不要")

    # concat list 作成
    concat_list = merge_dir / f"concat_{timestamp}.txt"
    with open(concat_list, "w", encoding="utf-8") as f:
        for p in concat_paths:
            escaped = str(p).replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")

    # FFmpeg concat demuxer で結合
    # 正規化済みの場合はコーデックコピー可能、未正規化でも再エンコードフォールバック
    cmd = [
        ffmpeg_path, "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy",
        merged_output
    ]

    logger.info(f"動画結合: {len(concat_paths)}本 -> {merged_output}")

    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    )

    merged_path = Path(merged_output)
    min_expected_size = 1024 * 1024

    if result.returncode != 0:
        if merged_path.exists() and merged_path.stat().st_size > min_expected_size:
            size_mb = merged_path.stat().st_size / 1024 / 1024
            logger.warning(f"⚠️ FFmpeg非ゼロ終了コード({result.returncode})だが出力は有効 ({size_mb:.0f}MB)")
        else:
            logger.warning(f"⚠️ コピーconcat失敗、再エンコードにフォールバック")
            encode_args = (["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23", "-c:a", "aac"]
                           if use_gpu else
                           ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac"])
            cmd_reencode = [
                ffmpeg_path, "-y",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_list),
                *encode_args,
                merged_output
            ]
            result2 = await loop.run_in_executor(
                None,
                lambda: subprocess.run(cmd_reencode, capture_output=True, text=True, timeout=3600)
            )
            if result2.returncode != 0 and not (merged_path.exists() and merged_path.stat().st_size > min_expected_size):
                logger.error(f"Merge failed (reencode): {result2.stderr[:300]}")
                raise RuntimeError(f"動画結合失敗: {result2.stderr[:200]}")

    # 一時ファイル削除 (正規化ファイル含む)
    concat_list.unlink(missing_ok=True)
    if needs_normalize:
        for np in normalized_paths:
            if np not in paths:  # 元ファイルは削除しない
                try:
                    Path(np).unlink(missing_ok=True)
                except HTTPException:
                    raise
                except Exception as e:
                    logger.debug(f"Failed to unlink normalized file {np}: {e}")

    size_mb = merged_path.stat().st_size / 1024 / 1024 if merged_path.exists() else 0
    logger.info(f"✅ 動画結合完了: {merged_output} ({size_mb:.0f}MB)")
    return merged_output


# ============================================================
# バックグラウンドパイプライン実行
# ============================================================

async def _run_pipeline_background(video_path: str, target_minutes: int):
    """パイプラインをバックグラウンドで実行 — 単一パス。

    PipelineCoordinator.execute() を唯一の実行パスとして使用。
    Harness (Hook/Governance/Session) は Coordinator 内部で
    グレースフルに統合されている。
    """
    try:
        # テンプレートID取得
        _current_template_id = None
        try:
            from template_config import template_config as _tc
            if _tc.is_active:
                _current_template_id = _tc.template_id
        except ImportError:
            pass

        ctx = PipelineContext(
            video_path=video_path,
            target_minutes=target_minutes,
            session_id=_pipeline_state.get("session_id", ""),
            template_id=_current_template_id,
        )
        pipeline_coordinator.set_ws_broadcast(_coordinator_ws_broadcast)

        # WebSocket で開始通知
        await pipeline_ws.broadcast({
            "type": "pipeline_start",
            "mode": "coordinator",
            "video_path": video_path,
        })

        result = await pipeline_coordinator.execute(ctx)

        _pipeline_state["status"] = result.get("status", "completed")
        _pipeline_state["result"] = result
        _pipeline_state["completed_at"] = datetime.now().isoformat()

        if result.get("status") == "error":
            _pipeline_state["status"] = "error"
            _pipeline_state["error"] = result.get("error", "パイプライン実行エラー")
            logger.error(f"❌ Pipeline error: {result.get('error')}")
        else:
            stages = result.get("stage_results", [])
            skipped = [s.get("name") for s in stages if not s.get("success", True)]
            if skipped:
                logger.warning(f"⚠️ 一部ステージが不合格: {skipped} — 改善余地あり")
            logger.info(
                f"✅ Pipeline completed: "
                f"duration={result.get('duration_seconds', 0)}s"
            )

        # WebSocket で完了/エラー通知
        await pipeline_ws.broadcast({
            "type": "pipeline_complete",
            "status": _pipeline_state["status"],
            "result": result,
        })

        # [C-04] §12.5: パイプライン完了時に自動進化発動
        try:
            from services.evolution_sync_service import EvolutionSyncService
            evolution_result = EvolutionSyncService().sync_all()
            logger.info(
                f"🔄 [§12.5] 自動進化発動: "
                f"triggers={len(evolution_result.get('result', {}).get('trigger_results', []))}"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"[§12.5] 自動進化発動失敗（非致命的）: {e}")

        # [Sprint 4.3.2] §11: パイプライン完了時にストレージ自動クリーンアップ
        try:
            from cleanup_manager import cleanup_manager as _cm
            cleanup_result = _cm.auto_cleanup()
            logger.info(
                f"🧹 [§11] ストレージ自動クリーンアップ: "
                f"deleted={len(cleanup_result.get('deleted', []))}, "
                f"freed={cleanup_result.get('freed_bytes', 0) / (1024*1024):.1f}MB"
            )
        except HTTPException as e:
            logger.error(f"[§11] ストレージ自動クリーンアップHTTPエラー: {e.detail}")
        except Exception as e:
            logger.warning(f"[§11] ストレージ自動クリーンアップ失敗（非致命的）: {e}")

    except HTTPException as e:
        _pipeline_state["status"] = "error"
        _pipeline_state["error"] = e.detail
        _pipeline_state["completed_at"] = datetime.now().isoformat()
        logger.error(f"❌ Pipeline HTTP error: {e.detail}")
    except Exception as e:
        _pipeline_state["status"] = "error"
        _pipeline_state["error"] = str(e)
        _pipeline_state["completed_at"] = datetime.now().isoformat()
        logger.error(f"❌ Pipeline fatal error: {e}", exc_info=True)


# ============================================================
# API エンドポイント
# ============================================================

class PipelineStartRequest(BaseModel):
    video_paths: List[str] = []
    video_path: str = ""  # 後方互換
    target_minutes: int = 20


@router.get("/videos")
async def list_videos():
    """vault-assets 内の動画ファイルをリスト化"""
    vault_assets = vault_assets_dir() / "raw_videos"
    
    if not vault_assets.exists():
        return {"videos": [], "error": "vault-assets not found"}
    
    videos = []
    for ext in ["*.mp4", "*.mov", "*.mkv", "*.avi"]:
        for f in vault_assets.rglob(ext):
            try:
                stat = f.stat()
                size_mb = stat.st_size / 1024 / 1024
                if size_mb < 0.01:  # 空ファイルを除外
                    continue
                videos.append({
                    "path": str(f),
                    "name": f.name,
                    "folder": f.parent.name,
                    "size_mb": round(size_mb, 1),
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
            except HTTPException:
                raise
            except Exception:
                continue
    
    # サイズ順
    videos.sort(key=lambda v: v["size_mb"])
    
    return {"videos": videos, "count": len(videos)}


class VideoMetadataRequest(BaseModel):
    video_path: str


@router.post("/videos/metadata")
async def get_video_metadata(req: VideoMetadataRequest):
    """動画メタデータを FFprobe で取得（O1-02: codec/尺/解像度）"""
    file_path = Path(req.video_path)
    if not file_path.exists():
        raise HTTPException(404, f"ファイルが見つかりません: {req.video_path}")

    stat = file_path.stat()
    if stat.st_size == 0:
        raise HTTPException(400, "ファイルサイズが0バイトです")

    metadata = {
        "path": str(file_path),
        "name": file_path.name,
        "size_mb": round(stat.st_size / 1024 / 1024, 1),
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
    }

    # FFprobe でメタデータ取得
    try:
        ffprobe_path = "ffprobe"
        try:
            from video_editor_engine import FFmpegEditor
            editor = FFmpegEditor()
            ffprobe_candidate = str(Path(editor.ffmpeg_path).parent / "ffprobe")
            if Path(ffprobe_candidate + ".exe").exists() or Path(ffprobe_candidate).exists():
                ffprobe_path = ffprobe_candidate
        except ImportError:
            pass  # video_editor_engine未インストール時はデフォルトffprobeを使用

        cmd = [
            ffprobe_path, "-v", "quiet",
            "-print_format", "json",
            "-show_format", "-show_streams",
            str(file_path)
        ]
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            )

            if result.returncode == 0 and result.stdout:
                probe_data = json.loads(result.stdout)
                fmt = probe_data.get("format", {})
                streams = probe_data.get("streams", [])

                # 動画ストリーム情報
                video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
                audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

                metadata["duration_seconds"] = round(float(fmt.get("duration", 0)), 1)
                metadata["duration_display"] = _format_duration(float(fmt.get("duration", 0)))
                metadata["bitrate_kbps"] = round(int(fmt.get("bit_rate", 0)) / 1000)

                if video_stream:
                    metadata["video_codec"] = video_stream.get("codec_name", "unknown")
                    metadata["width"] = video_stream.get("width", 0)
                    metadata["height"] = video_stream.get("height", 0)
                    metadata["resolution"] = f"{video_stream.get('width', 0)}x{video_stream.get('height', 0)}"
                    fps_str = video_stream.get("r_frame_rate", "0/1")
                    try:
                        num, den = fps_str.split("/")
                        metadata["fps"] = round(int(num) / max(int(den), 1), 2)
                    except (ValueError, ZeroDivisionError):
                        metadata["fps"] = 0

                if audio_stream:
                    metadata["audio_codec"] = audio_stream.get("codec_name", "unknown")
                    metadata["sample_rate"] = int(audio_stream.get("sample_rate", 0))
                    metadata["channels"] = audio_stream.get("channels", 0)

                metadata["probe_success"] = True
            else:
                metadata["probe_success"] = False
                metadata["probe_error"] = (result.stderr or 'FFprobe failed')[:200]
        except subprocess.TimeoutExpired:
            metadata["probe_success"] = False
            metadata["probe_error"] = 'FFprobe timeout expired'

    except FileNotFoundError:
        metadata["probe_success"] = False
        metadata["probe_error"] = "FFprobe not found"
    except HTTPException:
        raise
    except Exception as e:
        metadata["probe_success"] = False
        metadata["probe_error"] = str(e)[:200]

    return metadata


def _format_duration(seconds: float) -> str:
    """秒数を HH:MM:SS 形式に変換"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


class VideoValidateRequest(BaseModel):
    video_paths: List[str]


@router.post("/videos/validate")
async def validate_videos(req: VideoValidateRequest):
    """動画ファイルのバリデーション（O1-06: 0バイト/破損検出）"""
    results = []
    for video_path in req.video_paths:
        p = Path(video_path)
        entry = {"path": video_path, "name": p.name, "valid": False, "errors": []}

        if not p.exists():
            entry["errors"].append("ファイルが存在しません")
            results.append(entry)
            continue

        stat = p.stat()
        if stat.st_size == 0:
            entry["errors"].append("ファイルサイズが0バイトです")
            results.append(entry)
            continue

        # 最小サイズチェック（10KB未満は破損の可能性）
        if stat.st_size < 10240:
            entry["errors"].append(f"ファイルサイズが極端に小さいです ({stat.st_size} bytes)")
            results.append(entry)
            continue

        # FFprobe による破損チェック
        try:
            ffprobe_path = "ffprobe"
            try:
                from video_editor_engine import FFmpegEditor
                editor = FFmpegEditor()
                ffprobe_candidate = str(Path(editor.ffmpeg_path).parent / "ffprobe")
                if Path(ffprobe_candidate + ".exe").exists() or Path(ffprobe_candidate).exists():
                    ffprobe_path = ffprobe_candidate
            except ImportError:
                pass  # video_editor_engine未インストール時はデフォルトffprobeを使用

            cmd = [
                ffprobe_path, "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_type",
                "-of", "csv=p=0",
                str(p)
            ]
            loop = asyncio.get_running_loop()
            try:
                result = await loop.run_in_executor(
                    None,
                    lambda cmd=cmd: subprocess.run(cmd, capture_output=True, text=True, timeout=15)
                )

                if result.returncode != 0:
                    stderr_msg = (result.stderr or "").strip()[:200]
                    entry["errors"].append(f"動画ファイルが破損している可能性があります: {stderr_msg}")
                elif not result.stdout.strip():
                    entry["errors"].append("動画ストリームが検出できません")
                else:
                    entry["valid"] = True
            except subprocess.TimeoutExpired:
                entry["errors"].append("検証タイムアウト: FFprobeの応答が時間内にありませんでした")

        except FileNotFoundError:
            # FFprobe未インストール — サイズのみで判定
            entry["valid"] = True
            entry["warnings"] = ["FFprobe未インストールのため破損チェックはスキップされました"]
        except HTTPException:
            raise
        except Exception as e:
            entry["errors"].append(f"検証エラー: {str(e)[:100]}")

        results.append(entry)

    valid_count = sum(1 for r in results if r["valid"])
    return {
        "results": results,
        "total": len(results),
        "valid": valid_count,
        "invalid": len(results) - valid_count,
    }


@router.post("/start")
async def start_pipeline(req: PipelineStartRequest):
    """パイプラインを起動（複数動画対応）"""
    if _pipeline_state["status"] == "running":
        raise HTTPException(400, "パイプラインは既に実行中です")
    
    # 動画パスの解決（video_paths 優先、後方互換で video_path も対応）
    paths = req.video_paths if req.video_paths else ([req.video_path] if req.video_path else [])
    if not paths:
        raise HTTPException(400, "動画ファイルが指定されていません")
    
    for p in paths:
        if not Path(p).exists():
            raise HTTPException(404, f"動画ファイルが見つかりません: {p}")
    
    _reset_state()
    _pipeline_state["session_id"] = str(uuid.uuid4())
    _pipeline_state["video_paths"] = paths
    _pipeline_state["video_count"] = len(paths)
    _pipeline_state["target_minutes"] = req.target_minutes
    _pipeline_state["started_at"] = datetime.now().isoformat()
    _pipeline_state["status"] = "running"
    
    # 結合 + パイプライン実行をバックグラウンドで一括実行
    asyncio.create_task(_merge_and_run_pipeline(paths, req.target_minutes))
    
    return {
        "status": "started",
        "session_id": _pipeline_state["session_id"],
        "video_count": len(paths),
    }


async def _merge_and_run_pipeline(paths: List[str], target_minutes: int):
    """結合 + パイプライン実行をバックグラウンドで実行"""
    try:
        # ディスク容量チェック（大容量テストで枯渇を防止）
        await _ensure_disk_space(paths)
        
        if len(paths) > 1:
            total_mb = sum(Path(p).stat().st_size / 1024 / 1024 for p in paths)
            _update_stage(0, "running", f"動画結合中 ({len(paths)}本, {total_mb:.0f}MB)...")
            merged_path = await _merge_videos(paths)
            _pipeline_state["video_path"] = merged_path
            logger.info(f"✅ 結合完了: {merged_path}")
        else:
            _pipeline_state["video_path"] = paths[0]
        
        await _run_pipeline_background(_pipeline_state["video_path"], target_minutes)
    except HTTPException as e:
        _pipeline_state["status"] = "error"
        _pipeline_state["error"] = e.detail
        _pipeline_state["completed_at"] = datetime.now().isoformat()
        logger.error(f"❌ Merge+Pipeline HTTP error: {e.detail}")
    except Exception as e:
        _pipeline_state["status"] = "error"
        _pipeline_state["error"] = str(e)
        _pipeline_state["completed_at"] = datetime.now().isoformat()
        logger.error(f"❌ Merge+Pipeline error: {e}", exc_info=True)


async def _ensure_disk_space(paths: List[str], min_free_gb: float = 10.0):
    """ディスク空き容量を確保（disk_manager統一モジュールに委譲）"""
    from disk_manager import ensure_disk_space
    ensure_disk_space(paths, min_free_gb=min_free_gb)


@router.get("/status")
async def get_status():
    """パイプラインの現在のステータスを返す"""
    # 🧟 ゾンビプロセス検知・自動修復 (Self-Healing)
    # 開始から1時間（3600秒）以上経過した running 状態のタスクをエラーに遷移させる
    if _pipeline_state["status"] == "running" and _pipeline_state["started_at"]:
        try:
            started_dt = datetime.fromisoformat(_pipeline_state["started_at"])
            elapsed = (datetime.now() - started_dt).total_seconds()
            if elapsed > 3600:
                _pipeline_state["status"] = "error"
                _pipeline_state["error"] = "パイプラインの実行がタイムアウト（ゾンビプロセス検知）したため自動回復しました"
                _pipeline_state["completed_at"] = datetime.now().isoformat()
                logger.warning("🧟 ゾンビ状態のパイプラインプロセスを検知し、自動エラー状態に修復しました。")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error in zombie self-healing check: {e}")

    return {
        "session_id": _pipeline_state["session_id"],
        "status": _pipeline_state["status"],
        "current_stage": _pipeline_state["current_stage"],
        "stages": _pipeline_state["stages"],
        "checkpoint": _pipeline_state["checkpoint"],
        "video_path": _pipeline_state["video_path"],
        "video_count": _pipeline_state["video_count"],
        "target_minutes": _pipeline_state["target_minutes"],
        "started_at": _pipeline_state["started_at"],
        "completed_at": _pipeline_state["completed_at"],
        "error": _pipeline_state["error"],
        "result": _pipeline_state["result"],
    }


@router.post("/force-reset")
async def force_reset_pipeline():
    """パイプラインの状態を強制リセットして idle に戻す"""
    _reset_state()
    return {"status": "reset_success", "message": "パイプラインの状態を強制リセットしました"}


@router.post("/approve")
async def approve_checkpoint():
    """チェックポイントを承認"""
    if _pipeline_state["checkpoint"] is None:
        return {"status": "no_checkpoint"}
    
    _pipeline_state["checkpoint"]["approved"] = True
    _pipeline_state["checkpoint"] = None
    
    return {"status": "approved"}


# ============================================================
# T-034/T-035: 強制レンダリング API（品質ゲート実効化）
# ============================================================

class ForceRenderRequest(BaseModel):
    session_id: str = ""
    reason: str = ""  # 強制レンダリングの理由（evolution_log に記録）


@router.post("/force-render")
async def force_render(req: ForceRenderRequest):
    """品質不合格時の強制レンダリング (憲法§8.2 バイパス権限)

    品質スコア<90のパイプライン完了後に、ユーザー判断で本番品質レンダリングを実行。
    理由は evolution_log.json に記録される。
    """
    if _pipeline_state["status"] != "completed":
        raise HTTPException(400, "パイプラインが完了していません")

    result = _pipeline_state.get("result", {})
    quality_report = result.get("quality_gate_report")
    if not quality_report:
        raise HTTPException(400, "品質ゲート不合格レポートが存在しません（品質合格済みの可能性）")

    preview_path = result.get("preview_path", "")
    if not preview_path or not Path(preview_path).exists():
        raise HTTPException(404, "プレビューファイルが見つかりません")

    # --- 本番品質レンダリング実行 ---
    try:
        from safe_io import VAULT_OUTPUTS_DIR
        final_dir = VAULT_OUTPUTS_DIR / "final"
    except ImportError:
        final_dir = Path("output/final")
    final_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    final_path = str(final_dir / f"force_render_{ts}.mp4")

    try:
        import shutil
        # 本番品質エンコード
        try:
            from video_editor_engine import video_editor
            ffmpeg = video_editor.ffmpeg
            if ffmpeg.is_available():
                encode_args = ffmpeg._get_encode_args("balanced")
                cmd = ["-y", "-i", preview_path] + encode_args + [final_path]
                success, output = ffmpeg.run_command(cmd, timeout=1800)
                if not success:
                    logger.warning(f"Force render encode failed, copying: {output[:200]}")
                    shutil.copy(preview_path, final_path)
            else:
                shutil.copy(preview_path, final_path)
        except ImportError:
            shutil.copy(preview_path, final_path)

        size_mb = Path(final_path).stat().st_size / 1024 / 1024

        # T-035: evolution_log に強制レンダリング理由を記録
        await _record_force_render(
            reason=req.reason or "理由未記入",
            quality_score=quality_report.get("score", 0),
        )

        # パイプライン結果を更新
        _pipeline_state["result"]["final_path"] = final_path
        _pipeline_state["result"]["force_rendered"] = True

        # WebSocket 通知
        await pipeline_ws.broadcast({
            "type": "force_render_complete",
            "final_path": final_path,
            "size_mb": round(size_mb, 1),
            "quality_score": quality_report.get("score", 0),
            "reason": req.reason,
        })

        logger.info(
            f"✅ [T-034] 強制レンダリング完了: {final_path} "
            f"({size_mb:.1f}MB, score={quality_report.get('score', 0)})"
        )

        return {
            "status": "force_rendered",
            "final_path": final_path,
            "size_mb": round(size_mb, 1),
            "reason": req.reason,
            "quality_score": quality_report.get("score", 0),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 強制レンダリング失敗: {e}", exc_info=True)
        raise HTTPException(500, f"強制レンダリング失敗: {e}")


async def _record_force_render(reason: str, quality_score: int):
    """T-035: evolution_log に強制レンダリング理由を記録"""
    try:
        log_path = _writable_path("backend/branding/evolution_log.json")
        if log_path.exists():
            data = json.loads(log_path.read_text(encoding="utf-8"))
        else:
            data = {}

        data.setdefault("force_renders", []).append({
            "timestamp": datetime.now().isoformat(),
            "quality_score": quality_score,
            "reason": reason,
            "threshold": 90,
        })

        log_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"📝 [T-035] evolution_log記録: force_render (score={quality_score}, reason={reason})")
    except HTTPException:
        raise
    except (IOError, OSError, json.JSONDecodeError) as e:
        logger.warning(f"evolution_log記録失敗（非致命的）: {e}")


@router.get("/api-usage")
async def get_api_usage():
    """API使用量（無料枠500 RPD）を取得"""
    try:
        from usage_tracker.api_usage_tracker import get_usage_status
        return get_usage_status()
    except HTTPException:
        raise
    except Exception as e:
        return {"error": str(e), "used": 0, "limit": 500, "remaining": 500}


@router.get("/open-folder")
async def open_output_folder():
    """UX-02: 出力フォルダをエクスプローラーで開く"""
    import os
    try:
        from safe_io import VAULT_OUTPUTS_DIR
        folder = str(VAULT_OUTPUTS_DIR / "final")
    except ImportError:
        folder = str(Path("output/final"))
    Path(folder).mkdir(parents=True, exist_ok=True)
    try:
        os.startfile(folder)
        return {"status": "opened", "path": folder}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"フォルダオープン失敗: {e}")
        return {"status": "error", "path": folder, "error": str(e)}


@router.websocket("/ws/pipeline")
async def websocket_pipeline_progress(ws: WebSocket):
    await pipeline_ws.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pipeline_ws.disconnect(ws)
    except HTTPException:
        raise
    except Exception:
        pipeline_ws.disconnect(ws)


@router.get("/stream/{video_type}")
async def stream_video(video_type: str, request: Request):
    """完了動画をストリーミング配信（Range 対応）
    
    video_type: "preview" or "final"
    """
    if video_type not in ("preview", "final"):
        raise HTTPException(400, "video_type must be 'preview' or 'final'")
    
    result = _pipeline_state.get("result")
    if not result:
        raise HTTPException(404, "パイプライン未完了")
    
    path_key = f"{video_type}_path"
    file_path = result.get(path_key)
    if not file_path or not Path(file_path).exists():
        raise HTTPException(404, f"{video_type} ファイルが見つかりません")
    
    file_size = Path(file_path).stat().st_size
    
    # Range ヘッダー対応（シーク可能）
    range_header = request.headers.get("range")
    if range_header:
        range_str = range_header.replace("bytes=", "")
        start_str, end_str = range_str.split("-")
        start = int(start_str)
        end = int(end_str) if end_str else min(start + 1024 * 1024, file_size - 1)
        
        def iter_range():
            with open(file_path, "rb") as f:
                f.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = f.read(min(8192, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk
        
        return StreamingResponse(
            iter_range(),
            status_code=206,
            media_type="video/mp4",
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(end - start + 1),
            }
        )
    else:
        def iter_file():
            with open(file_path, "rb") as f:
                while chunk := f.read(8192):
                    yield chunk
        
        return StreamingResponse(
            iter_file(),
            media_type="video/mp4",
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
            }
        )


# ============================================================
# O-2: 文字起こしステージ API
# ============================================================

# インメモリ文字起こし状態
_transcription_state = get_initial_transcription_state()


@router.get("/transcription/models")
async def get_whisper_models():
    """O2-01/O2-02: Whisperモデル一覧 + VRAM推奨"""
    models = [
        {"id": "tiny", "name": "Tiny", "vram_gb": 1, "speed": "最速", "accuracy": "低"},
        {"id": "base", "name": "Base", "vram_gb": 1, "speed": "高速", "accuracy": "やや低"},
        {"id": "small", "name": "Small", "vram_gb": 2, "speed": "中速", "accuracy": "中"},
        {"id": "medium", "name": "Medium", "vram_gb": 5, "speed": "やや遅い", "accuracy": "高"},
        {"id": "large-v3", "name": "Large-v3", "vram_gb": 10, "speed": "最遅", "accuracy": "最高"},
    ]

    # VRAM検出ベースの推奨
    recommended = "medium"
    try:
        import subprocess as _sp
        result = _sp.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            vram_mb = int(result.stdout.strip().split("\n")[0])
            if vram_mb >= 10240:
                recommended = "large-v3"
            elif vram_mb >= 5120:
                recommended = "medium"
            else:
                recommended = "small"
    except HTTPException:
        raise
    except Exception as _vram_err:
        logger.debug("VRAM検出スキップ (nvidia-smi不可): %s", _vram_err)

    return {
        "models": models,
        "recommended": recommended,
        "current": _transcription_state["model"],
    }


@router.get("/transcription/segments")
async def get_transcription_segments():
    """O2-04: セグメント一覧取得"""
    # パイプライン実行結果からセグメントを取得
    segments = _transcription_state.get("segments", [])
    if not segments:
        segments = get_default_transcription_segments()
        _transcription_state["segments"] = segments
    return {
        "segments": segments,
        "count": len(segments),
        "model": _transcription_state["model"],
    }


class SegmentUpdateRequest(BaseModel):
    text: str


@router.put("/transcription/segments/{segment_id}")
async def update_transcription_segment(segment_id: int, req: SegmentUpdateRequest):
    """O2-05: セグメントテキスト編集"""
    segments = _transcription_state.get("segments", [])
    for seg in segments:
        if seg.get("id") == segment_id:
            old_text = seg["text"]
            seg["text"] = req.text
            return {"status": "updated", "segment_id": segment_id, "old_text": old_text, "new_text": req.text}
    raise HTTPException(404, f"セグメント {segment_id} が見つかりません")


@router.get("/transcription/status")
async def get_transcription_status():
    """O2-03/O2-07: 文字起こし進捗 + 経過時間"""
    return {
        "status": _transcription_state["status"],
        "progress": _transcription_state["progress"],
        "elapsed_seconds": _transcription_state["elapsed_seconds"],
        "model": _transcription_state["model"],
        "error_message": _transcription_state.get("error_message"),
        "segment_count": len(_transcription_state.get("segments", [])),
    }


class TranscriptionModelRequest(BaseModel):
    model: str


@router.post("/transcription/model")
async def set_transcription_model(req: TranscriptionModelRequest):
    """O2-02: Whisperモデル選択"""
    valid_models = ["tiny", "base", "small", "medium", "large-v3"]
    if req.model not in valid_models:
        raise HTTPException(400, f"無効なモデル: {req.model}")
    _transcription_state["model"] = req.model
    return {"status": "updated", "model": req.model}


# ============================================================
# O-3: AI校閲ステージ API
# ============================================================

# インメモリ校閲状態
_proofreading_state = get_initial_proofreading_state()


@router.get("/proofreading/result")
async def get_proofreading_result():
    """O3-01/O3-02: 校閲結果 diff (before/after)"""
    segments = _proofreading_state.get("segments", [])
    if not segments:
        segments = get_default_proofreading_segments()
        _proofreading_state["segments"] = segments
    return {
        "segments": segments,
        "count": len(segments),
        "approved_count": sum(1 for s in segments if s["status"] == "approved"),
        "rejected_count": sum(1 for s in segments if s["status"] == "rejected"),
        "pending_count": sum(1 for s in segments if s["status"] == "pending"),
    }


class SegmentDecisionRequest(BaseModel):
    segment_id: int


@router.post("/proofreading/approve")
async def approve_proofreading_segment(req: SegmentDecisionRequest):
    """O3-03: セグメント承認"""
    segments = _proofreading_state.get("segments", [])
    for seg in segments:
        if seg.get("id") == req.segment_id:
            seg["status"] = "approved"
            return {"status": "approved", "segment_id": req.segment_id}
    raise HTTPException(404, f"セグメント {req.segment_id} が見つかりません")


@router.post("/proofreading/reject")
async def reject_proofreading_segment(req: SegmentDecisionRequest):
    """O3-03: セグメント却下"""
    segments = _proofreading_state.get("segments", [])
    for seg in segments:
        if seg.get("id") == req.segment_id:
            seg["status"] = "rejected"
            return {"status": "rejected", "segment_id": req.segment_id}
    raise HTTPException(404, f"セグメント {req.segment_id} が見つかりません")


@router.post("/proofreading/approve-all")
async def approve_all_proofreading():
    """O3-04: 一括承認"""
    segments = _proofreading_state.get("segments", [])
    count = 0
    for seg in segments:
        if seg.get("status") != "approved":
            seg["status"] = "approved"
            count += 1
    return {"status": "approved_all", "count": count}


@router.post("/proofreading/reject-all")
async def reject_all_proofreading():
    """O3-04: 一括却下"""
    segments = _proofreading_state.get("segments", [])
    count = 0
    for seg in segments:
        if seg.get("status") != "rejected":
            seg["status"] = "rejected"
            count += 1
    return {"status": "rejected_all", "count": count}


@router.get("/dictionary")
async def get_dictionary():
    """O3-05: 固有名詞辞書取得"""
    try:
        from proper_noun_dict import proper_noun_dict
        return {
            "entries": proper_noun_dict.get_all_entries(),
            "count": len(proper_noun_dict.entries),
            "pending": proper_noun_dict.get_pending(),
            "auto_learn": proper_noun_dict.auto_learn,
        }
    except HTTPException:
        raise
    except Exception as e:
        return {"entries": [], "count": 0, "error": str(e)}


class DictionaryEntryRequest(BaseModel):
    incorrect: str
    correct: str
    entry_type: str = "word"
    context_hint: str = ""


@router.post("/dictionary")
async def add_dictionary_entry(req: DictionaryEntryRequest):
    """O3-05: 辞書エントリ追加"""
    try:
        from proper_noun_dict import proper_noun_dict
        entry = proper_noun_dict.add_entry(
            incorrect=req.incorrect,
            correct=req.correct,
            entry_type=req.entry_type,
            context_hint=req.context_hint,
        )
        from dataclasses import asdict
        return {"status": "added", "entry": asdict(entry)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"辞書追加失敗: {e}")


class DictionaryUpdateRequest(BaseModel):
    incorrect: Optional[str] = None
    correct: Optional[str] = None


@router.put("/dictionary/{entry_id}")
async def update_dictionary_entry(entry_id: str, req: DictionaryUpdateRequest):
    """O3-05: 辞書エントリ更新"""
    try:
        from proper_noun_dict import proper_noun_dict
        for entry in proper_noun_dict.entries:
            if entry.id == entry_id:
                if req.incorrect is not None:
                    entry.incorrect = req.incorrect
                if req.correct is not None:
                    entry.correct = req.correct
                proper_noun_dict._save()
                from dataclasses import asdict
                return {"status": "updated", "entry": asdict(entry)}
        raise HTTPException(404, f"エントリ {entry_id} が見つかりません")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"辞書更新失敗: {e}")


@router.delete("/dictionary/{entry_id}")
async def delete_dictionary_entry(entry_id: str):
    """O3-05: 辞書エントリ削除"""
    try:
        from proper_noun_dict import proper_noun_dict
        if proper_noun_dict.remove_entry(entry_id):
            return {"status": "deleted", "entry_id": entry_id}
        raise HTTPException(404, f"エントリ {entry_id} が見つかりません")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"辞書削除失敗: {e}")


@router.get("/proofreading/export/{export_format}")
async def export_proofreading(export_format: str):
    """O3-09: 校閲結果のエクスポート (SRT/TXT)"""
    segments = _proofreading_state.get("segments", [])
    if not segments:
        raise HTTPException(404, "校閲結果がありません")

    if export_format.lower() == "srt":
        lines = []
        for i, seg in enumerate(segments):
            text = seg.get("corrected", seg.get("original", ""))
            start = _format_srt_time(seg.get("start", 0))
            end = _format_srt_time(seg.get("end", 0))
            lines.append(f"{i+1}")
            lines.append(f"{start} --> {end}")
            lines.append(text)
            lines.append("")
        content = "\n".join(lines)
        return StreamingResponse(
            iter([content.encode("utf-8")]),
            media_type="text/plain",
            headers={"Content-Disposition": "attachment; filename=subtitles.srt"}
        )
    elif export_format.lower() == "txt":
        lines = []
        for seg in segments:
            text = seg.get("corrected", seg.get("original", ""))
            lines.append(text)
        content = "\n".join(lines)
        return StreamingResponse(
            iter([content.encode("utf-8")]),
            media_type="text/plain",
            headers={"Content-Disposition": "attachment; filename=subtitles.txt"}
        )
    else:
        raise HTTPException(400, f"未対応フォーマット: {export_format} (srt/txt)")


def _format_srt_time(seconds: float) -> str:
    """秒数をSRT形式 (HH:MM:SS,mmm) に変換"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


@router.get("/proofreading/status")
async def get_proofreading_status():
    """O3-08: 校閲進捗"""
    segments = _proofreading_state.get("segments", [])
    total = len(segments) if segments else 0
    approved = sum(1 for s in segments if s.get("status") == "approved")
    return {
        "status": _proofreading_state["status"],
        "progress": _proofreading_state["progress"],
        "total_segments": total,
        "approved_segments": approved,
        "skip": _proofreading_state.get("skip", False),
    }


class ProofreadingSkipRequest(BaseModel):
    skip: bool


@router.post("/proofreading/skip")
async def toggle_proofreading_skip(req: ProofreadingSkipRequest):
    """O3-10: 校閲なしスキップオプション"""
    _proofreading_state["skip"] = req.skip
    return {"status": "updated", "skip": req.skip}


# ============================================================
# O-6: 品質チェックステージ API
# ============================================================

# **この品質スコアは動画を見て出した点ではない**（R1.5-C4・2026-08-28 ユーザー決定）。
# `pipeline_default_states.INITIAL_QUALITY_GATE_STATE` の定数（音声88 / 映像82 /
# 字幕90 / 構成80 → 加重平均 85）を返しているだけで、音声も映像も一切読まない。
# **本線（`agents.pipeline_coordinator`）の品質ゲートとは別物。**
# あちらは実走で 89・94 点を出しており、そちらが本物。
#
# ここは UI（`frontend/src/components/QualityGate.jsx`）が「QUALITY SCORE」として
# 表示する経路なので、**印を付けないと画面上は実測値と区別が付かない。**
# 台帳: `backend/config/feature_gaps.json` の `pipeline_quality_gate_ui`
QUALITY_GATE_DATA_SOURCE = {
    "data_source": "sample",
    "is_real": False,
    "note": "**動画を見て出した点ではありません。**この経路は UI の足場で、"
            "定数を返しています。本物の品質ゲートは本線（agents）側にあります",
}

_quality_gate_state = get_initial_quality_gate_state()


@router.get("/quality-gate/status")
async def get_quality_gate_status():
    """O6-01: 品質ゲートの状態取得"""
    return {
        **QUALITY_GATE_DATA_SOURCE,
        "status": _quality_gate_state["status"],
        "overall_score": _quality_gate_state["overall_score"],
        "threshold": _quality_gate_state["threshold"],
        "passed": _quality_gate_state["overall_score"] >= _quality_gate_state["threshold"],
        "category_count": len(_quality_gate_state["categories"]),
        "checked_at": _quality_gate_state.get("checked_at"),
    }


@router.get("/quality-gate/scores")
async def get_quality_gate_scores():
    """O6-02: カテゴリ別スコア詳細"""
    categories = _quality_gate_state["categories"]
    return {
        **QUALITY_GATE_DATA_SOURCE,
        "overall_score": _quality_gate_state["overall_score"],
        "threshold": _quality_gate_state["threshold"],
        "passed": _quality_gate_state["overall_score"] >= _quality_gate_state["threshold"],
        "categories": [
            {
                "id": c["id"],
                "name": c["name"],
                "score": c["score"],
                "weight": c["weight"],
                "weighted_score": round(c["score"] * c["weight"] / 100, 1),
                "detail_count": len(c.get("details", [])),
                "pass_count": sum(1 for d in c.get("details", []) if d["status"] == "pass"),
                "warning_count": sum(1 for d in c.get("details", []) if d["status"] == "warning"),
                "fail_count": sum(1 for d in c.get("details", []) if d["status"] == "fail"),
            }
            for c in categories
        ],
    }


@router.get("/quality-gate/drilldown/{category}")
async def get_quality_gate_drilldown(category: str):
    """O6-03: カテゴリドリルダウン詳細"""
    for c in _quality_gate_state["categories"]:
        if c["id"] == category:
            return {
                **QUALITY_GATE_DATA_SOURCE,
                "category": c["id"],
                "name": c["name"],
                "score": c["score"],
                "weight": c["weight"],
                "details": c.get("details", []),
                "detail_count": len(c.get("details", [])),
            }
    raise HTTPException(404, f"カテゴリ '{category}' が見つかりません")


class QualityImproveRequest(BaseModel):
    category: str = ""


@router.post("/quality-gate/improve")
async def get_quality_improvement(req: QualityImproveRequest):
    """O6-04: AI改善提案取得"""
    suggestions = []
    target_cats = [req.category] if req.category else [c["id"] for c in _quality_gate_state["categories"]]

    for c in _quality_gate_state["categories"]:
        if c["id"] in target_cats:
            for d in c.get("details", []):
                if d["status"] in ("warning", "fail"):
                    suggestions.append({
                        "category": c["id"],
                        "category_name": c["name"],
                        "item": d["item"],
                        "current_score": d["score"],
                        "suggestion": f"{d['item']}を改善: {d['description']}",
                        "estimated_improvement": min(100 - d["score"], 15),
                        "priority": "high" if d["status"] == "fail" else "medium",
                    })

    # --- SoulFeedbackEngine (LLM/文脈提案) を連携して動的追加 ---
    try:
        from backend.video_pipeline.soul_feedback_engine import SoulFeedbackEngine, ProductionContext
        srt_content = ""
        job_dir = backend_dir() / "work"
        srts = list(job_dir.glob("**/subtitles.srt"))
        if srts:
            try:
                srt_content = srts[0].read_text(encoding="utf-8")
            except Exception:
                pass

        if not srt_content:
            # フォールバック: 対談動画の文脈ダミー
            srt_content = "山田：今回の対談では、NHKの字幕とYouTuber基準の動画編集について議論しましょう。"

        engine = SoulFeedbackEngine()
        context = ProductionContext(
            video_id="current_job",
            category="対談",
            target_audience="一般",
            extra={"transcript": srt_content}
        )
        feedback_output = engine.generate_suggestions(context=context)
        
        for s in feedback_output.suggestions:
            suggestions.append({
                "category": "text" if s.category == "テキスト" else "tempo" if s.category == "テンポ" else "visual" if s.category == "ビジュアル" else "audio",
                "category_name": s.category,
                "item": "AI文脈演出",
                "current_score": 75,
                "suggestion": f"【AI文脈演出】{s.suggestion} (根拠: {s.evidence})",
                "estimated_improvement": 20,
                "priority": s.priority,
            })
    except Exception as e:
        logger.error("APIのSoulFeedbackEngine動的サジェスト連携でエラーが発生しました: %s", e)

    suggestions.sort(key=lambda s: s["estimated_improvement"], reverse=True)
    return {
        **QUALITY_GATE_DATA_SOURCE,
        "suggestions": suggestions,
        "count": len(suggestions),
        "estimated_total_improvement": sum(s["estimated_improvement"] for s in suggestions[:3]),
    }


@router.get("/quality-gate/history")
async def get_quality_gate_history():
    """O6-05: 品質スコア履歴"""
    return {
        **QUALITY_GATE_DATA_SOURCE,
        "history": _quality_gate_state.get("history", []),
        "count": len(_quality_gate_state.get("history", [])),
        "initial_score": _quality_gate_state["history"][0]["score"] if _quality_gate_state.get("history") else 0,
        "current_score": _quality_gate_state["overall_score"],
        "improvement": _quality_gate_state["overall_score"] - (
            _quality_gate_state["history"][0]["score"] if _quality_gate_state.get("history") else 0
        ),
    }


@router.post("/quality-gate/check")
async def run_quality_check():
    """O6-06: 品質チェック実行"""
    _quality_gate_state["status"] = "checking"
    # **検査していないのに「いま検査した」時刻を打たない**（R1.5-C4）。
    # 下でやっているのは定数の加重平均を取り直すことだけで、動画は見ていない。
    # 2周目・4周目で直した `last_sync = datetime.now()` と同型

    # 各カテゴリの重み付き平均を計算
    total_weighted = sum(c["score"] * c["weight"] for c in _quality_gate_state["categories"])
    total_weight = sum(c["weight"] for c in _quality_gate_state["categories"])
    overall = round(total_weighted / max(total_weight, 1))
    _quality_gate_state["overall_score"] = overall

    if overall >= _quality_gate_state["threshold"]:
        _quality_gate_state["status"] = "passed"
    else:
        _quality_gate_state["status"] = "failed"

    return {
        **QUALITY_GATE_DATA_SOURCE,
        "status": _quality_gate_state["status"],
        "overall_score": overall,
        "threshold": _quality_gate_state["threshold"],
        "passed": overall >= _quality_gate_state["threshold"],
    }


# ============================================================
# O-7: 品質改善ループ API
# ============================================================

# **このループは動画を直していない**（R1.5-C4）。
# `apply` がやっているのは `current_score` に定数 +4 を足すことだけで、
# 音量正規化もビットレート最適化も実際には走らない。初期値の 72 も
# `pipeline_default_states` の定数であって、何かを測った点ではない。
#
# 上の O-6（`QUALITY_GATE_DATA_SOURCE`）と**同じ定数群を出所にしている**のに、
# 5周目はこちらへ印を付け忘れた。O-6 の 190 行下にある。
# 台帳: `backend/config/feature_gaps.json` の `pipeline_quality_gate_ui`
IMPROVEMENT_DATA_SOURCE = {
    "data_source": "sample",
    "is_real": False,
    "note": "**動画を直した結果ではありません。**この改善ループは UI の足場で、"
            "加点をシミュレートしています。本物の品質ゲートは本線（agents）側にあります",
}

_improvement_state = get_initial_improvement_state()


@router.get("/improvement/status")
async def get_improvement_status():
    """O7-01: 改善ループ進捗"""
    return {
        **IMPROVEMENT_DATA_SOURCE,
        "status": _improvement_state["status"],
        "iteration": _improvement_state["iteration"],
        "max_iterations": _improvement_state["max_iterations"],
        "initial_score": _improvement_state["initial_score"],
        "current_score": _improvement_state["current_score"],
        "total_actions": len(_improvement_state["actions"]),
        "completed_actions": sum(1 for a in _improvement_state["actions"] if a["status"] == "completed"),
        "pending_actions": sum(1 for a in _improvement_state["actions"] if a["status"] == "pending"),
    }


@router.get("/improvement/actions")
async def get_improvement_actions():
    """O7-02: アクション一覧"""
    return {
        **IMPROVEMENT_DATA_SOURCE,
        "actions": _improvement_state["actions"],
        "count": len(_improvement_state["actions"]),
        "applied": _improvement_state["applied_actions"],
    }


class ApplyActionRequest(BaseModel):
    pass


@router.post("/improvement/apply/{action_id}")
async def apply_improvement_action(action_id: str):
    """O7-03: アクション適用"""
    for action in _improvement_state["actions"]:
        if action["id"] == action_id:
            if action["status"] == "completed":
                raise HTTPException(400, f"アクション '{action_id}' は既に適用済みです")

            # アクション適用をシミュレート
            action["status"] = "completed"
            action["score_before"] = _improvement_state["current_score"]
            improvement = 4  # シミュレーション: +4点
            new_score = min(_improvement_state["current_score"] + improvement, 100)
            action["score_after"] = new_score
            _improvement_state["current_score"] = new_score
            _improvement_state["iteration"] += 1
            _improvement_state["applied_actions"].append(action_id)

            # スコア履歴に追加
            _improvement_state["score_history"].append({
                "iteration": _improvement_state["iteration"],
                "score": new_score,
                "action": action["name"],
            })

            return {
                **IMPROVEMENT_DATA_SOURCE,
                "status": "applied",
                "action_id": action_id,
                "action_name": action["name"],
                "score_before": action["score_before"],
                "score_after": new_score,
                "improvement": improvement,
                "iteration": _improvement_state["iteration"],
            }

    raise HTTPException(404, f"アクション '{action_id}' が見つかりません")


@router.get("/improvement/score-change")
async def get_improvement_score_change():
    """O7-04: スコア変化推移"""
    return {
        **IMPROVEMENT_DATA_SOURCE,
        "score_history": _improvement_state["score_history"],
        "initial_score": _improvement_state["initial_score"],
        "current_score": _improvement_state["current_score"],
        "total_improvement": _improvement_state["current_score"] - _improvement_state["initial_score"],
        "iterations": len(_improvement_state["score_history"]),
    }


@router.post("/improvement/abort")
async def abort_improvement_loop():
    """O7-05: 改善ループ中止"""
    if _improvement_state["status"] == "aborted":
        return {**IMPROVEMENT_DATA_SOURCE,
                "status": "already_aborted", "message": "改善ループは既に中止されています"}

    _improvement_state["status"] = "aborted"
    # 未完了アクションをスキップ
    skipped_count = 0
    for action in _improvement_state["actions"]:
        if action["status"] == "pending":
            action["status"] = "skipped"
            skipped_count += 1

    return {
        **IMPROVEMENT_DATA_SOURCE,
        "status": "aborted",
        "message": "改善ループを中止しました",
        "skipped_actions": skipped_count,
        "final_score": _improvement_state["current_score"],
        "iteration": _improvement_state["iteration"],
    }


@router.post("/improvement/reset")
async def reset_improvement_loop():
    """O7-06: 改善ループリセット"""
    _improvement_state.update({
        "status": "idle",
        "iteration": 0,
        "initial_score": 72,
        "current_score": 72,
        "applied_actions": [],
        "score_history": [{"iteration": 0, "score": 72, "action": "初期状態"}],
    })
    for action in _improvement_state["actions"]:
        action["status"] = "pending"
        action["score_before"] = None
        action["score_after"] = None
    _improvement_state["actions"][0]["score_before"] = 72

    return {**IMPROVEMENT_DATA_SOURCE,
            "status": "reset", "message": "改善ループをリセットしました"}
