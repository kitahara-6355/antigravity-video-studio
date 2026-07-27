"""
ヘルスチェック — PM-2: 実稼働準備

テレビ局の放送技術部要件:
  - 依存サービス（FFmpeg, Gemini, GPU）の死活監視
  - ディスク残容量のチェック
  - バックエンド起動時刻とアップタイムの表示

エンドポイント:
  GET /health       — 全体ステータス
  GET /health/deep  — 詳細チェック（起動時間を含む）
"""

import sys
import time
import shutil
import logging
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])

_startup_time = time.time()


def _register_tdr_debt(pattern: str, error_msg: str):
    try:
        # Retrieve the caller's line number dynamically
        frame = sys._getframe(1)
        line_number = frame.f_lineno
    except Exception:
        line_number = 0

    try:
        from pathlib import Path
        from agents.memory.technical_debt import TechnicalDebtStore
        # health.py is in backend/routers/health.py, so parent.parent is backend
        store = TechnicalDebtStore(Path(__file__).parent.parent / "agents/memory")
        store.register_debt(
            category="CRITICAL_ROUTER",
            file_path="routers/health.py",
            line_number=line_number,
            pattern=pattern,
            cause_pattern="DP-01",
            fix_pattern="HTTPException translation",
            registered_by="T-batch_b04d78-thumbnail-000",
            notes=f"Runtime exception in health router: {error_msg}",
        )
    except Exception as e:
        logger.error(f"Failed to register TDR debt: {e}")


def _check_thumbnail_engine() -> dict:
    """サムネイル生成・画像処理エンジンのヘルスチェック（品質検証・連携状況）"""
    status = {"available": False, "validation": None, "stage_bound_agent_integration": False}
    try:
        # 1. 必要なモジュールやリゾルバーがインポート可能かチェック
        from agents.council_graph import ThumbnailResolver
        from agents.stage_bound_agent import StageBoundAgent
        status["available"] = True
        status["stage_bound_agent_integration"] = True

        # 2. 一時ファイルディレクトリにダミー画像を生成し、品質要件を検証
        resolver = ThumbnailResolver()
        
        # テスト用のテンポラリ出力先
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir) / "health_check_thumb.png"
            # 1280x720 (16:9) の画像を生成
            resolver.generate_thumbnail(temp_path, width=1280, height=720, text="Health Check")
            
            # 品質検証の実行
            val_result = resolver.validate_thumbnail(temp_path)
            
            status["validation"] = {
                "passed": True,
                "details": {
                    "width": val_result.get("width"),
                    "height": val_result.get("height"),
                    "size_bytes": val_result.get("size_bytes"),
                    "aspect_ratio": "16:9",
                }
            }
    except HTTPException:
        raise
    except (ImportError, ModuleNotFoundError) as e:
        logger.warning(f"Thumbnail engine modules not available: {e}")
        status["validation"] = {
            "passed": False,
            "error": f"Module not found: {str(e)}"
        }
    except (OSError, ValueError) as e:
        logger.error(f"Thumbnail engine execution failed: {e}", exc_info=True)
        _register_tdr_debt("except (OSError, ValueError) as e", str(e))
        status["validation"] = {
            "passed": False,
            "error": f"Execution error: {str(e)}"
        }
    return status


def _check_ffmpeg() -> dict:
    """FFmpeg の利用可否と GPU 対応状況"""
    try:
        from video_editor_engine import video_editor
        ffmpeg = video_editor.ffmpeg
        return {
            "available": ffmpeg.is_available(),
            "path": ffmpeg.ffmpeg_path,
            "gpu_nvenc": ffmpeg.use_gpu,
        }
    except HTTPException:
        raise
    except (ImportError, ModuleNotFoundError) as e:
        return {"available": False, "error": f"Import error: {str(e)}"}
    except (AttributeError, ValueError, TypeError, OSError) as e:
        return {"available": False, "error": f"Engine execution error: {str(e)}"}
    except Exception as e:
        return {"available": False, "error": f"Unexpected error: {str(e)}"}


def _check_gemini() -> dict:
    """Gemini APIキーの存在確認"""
    import os
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    return {
        "key_configured": bool(api_key),
        "key_prefix": api_key[:8] + "..." if api_key else None,
    }


def _check_disk_space() -> dict:
    """Vault出力領域のディスク残容量"""
    try:
        from safe_io import VAULT_OUTPUTS_DIR
        check_path = VAULT_OUTPUTS_DIR
    except ImportError:
        check_path = Path(".")

    try:
        usage = shutil.disk_usage(str(check_path))
        free_gb = usage.free / (1024 ** 3)
        total_gb = usage.total / (1024 ** 3)
        return {
            "path": str(check_path),
            "free_gb": round(free_gb, 1),
            "total_gb": round(total_gb, 1),
            "usage_percent": round((1 - usage.free / usage.total) * 100, 1),
            "warning": free_gb < 10,
        }
    except HTTPException:
        raise
    except OSError as e:
        return {"error": str(e)}


def _check_whisper() -> dict:
    """faster-whisperの利用可否"""
    try:
        import faster_whisper
        return {"available": True, "version": getattr(faster_whisper, "__version__", "unknown")}
    except ImportError:
        return {"available": False}


def _check_pipeline_status() -> dict:
    """パイプライン状態の確認（Harness統合版）"""
    pipeline_status = {"harness_available": False, "coordinator_available": False}
    try:
        from harness.adk_bridge import build_harness_pipeline
        pipeline_status["harness_available"] = True
    except ImportError:
        pass
    except HTTPException:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, RuntimeError) as e:
        logger.warning(f"Expected harness pipeline resolution check failed: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Failed to load harness pipeline: {e}", exc_info=True)
        _register_tdr_debt("except Exception as e", str(e))
    try:
        from agents.pipeline_coordinator import PipelineCoordinator
        pipeline_status["coordinator_available"] = True
    except ImportError:
        pass
    except HTTPException:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, RuntimeError) as e:
        logger.warning(f"Expected pipeline coordinator resolution check failed: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Failed to load pipeline coordinator: {e}", exc_info=True)
        _register_tdr_debt("except Exception as e", str(e))
    return pipeline_status


def _check_template_status() -> dict:
    """テンプレート設定状態"""
    template_status = {"active": False}
    try:
        from template_config import template_config
        template_status["active"] = template_config.is_active
        if template_config.is_active:
            template_status["template_id"] = template_config.active_id
    except (ImportError, AttributeError):
        pass
    except HTTPException:
        raise
    except (ValueError, TypeError, KeyError, RuntimeError) as e:
        logger.warning(f"Expected template config resolution check failed: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Failed to load template config: {e}", exc_info=True)
        _register_tdr_debt("except Exception as e", str(e))
    return template_status


@router.get("/health")
async def get_simple_health():
    """
    簡易ヘルスチェック — 監視ツール向け

    Returns:
        status: "healthy" | "degraded" | "unhealthy"
    """
    try:
        ffmpeg = _check_ffmpeg()
        gemini = _check_gemini()
        disk = _check_disk_space()
        thumbnail = _check_thumbnail_engine()

        # 総合判定
        critical_ok = ffmpeg.get("available", False)
        warning = (
            disk.get("warning", False)
            or not gemini.get("key_configured", False)
            or not thumbnail.get("available", False)
            or (thumbnail.get("validation") and not thumbnail["validation"].get("passed", False))
        )

        if not critical_ok:
            status = "unhealthy"
        elif warning:
            status = "degraded"
        else:
            status = "healthy"

        uptime = round(time.time() - _startup_time)

        return {
            "status": status,
            "uptime_seconds": uptime,
            "timestamp": datetime.now().isoformat(),
            "checks": {
                "ffmpeg": ffmpeg,
                "gemini": gemini,
                "disk": disk,
                "thumbnail": thumbnail,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        _register_tdr_debt("broad_except", str(e))
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")


@router.get("/health/deep")
async def get_detailed_health():
    """
    詳細ヘルスチェック — 全コンポーネント検査

    テレビ局の放送技術部が要求する「5分以内に原因特定」を支援
    """
    try:
        ffmpeg = _check_ffmpeg()
        gemini = _check_gemini()
        disk = _check_disk_space()
        whisper = _check_whisper()
        thumbnail = _check_thumbnail_engine()
        pipeline_status = _check_pipeline_status()
        template_status = _check_template_status()

        uptime = round(time.time() - _startup_time)

        return {
            "status": "detailed",
            "uptime_seconds": uptime,
            "startup_time": datetime.fromtimestamp(_startup_time).isoformat(),
            "timestamp": datetime.now().isoformat(),
            "checks": {
                "ffmpeg": ffmpeg,
                "gemini": gemini,
                "disk": disk,
                "whisper": whisper,
                "pipeline": pipeline_status,
                "template": template_status,
                "thumbnail": thumbnail,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        _register_tdr_debt("broad_except", str(e))
        raise HTTPException(status_code=500, detail=f"Deep health check failed: {str(e)}")
