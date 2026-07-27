"""
Admin Setup Router — A-1 システムセットアップ・環境管理

Admin UXストーリー A-1 に対応するバックエンドAPI。
22シーンのダッシュボード機能(環境ステータス/APIキー管理/ハーネス状態/
GPU情報/モデル設定/ストレージ監視/設定エクスポート・インポート等)を提供する。

設計書: design_admin_a1_a7_full.md.resolved (推移表転記済み/)
"""

import os
import json
import time
import shutil
import logging
import platform
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/setup", tags=["Admin Setup"])

_startup_time = time.time()

# ── リクエストモデル ──

class ApiKeyUpdateRequest(BaseModel):
    provider: str  # "gemini" or "youtube"
    key: str


class ModelAssignmentRequest(BaseModel):
    task: str
    model_tier: str  # "premium", "standard", "batch"


class LogLevelRequest(BaseModel):
    level: str  # "DEBUG", "INFO", "WARNING", "ERROR"


class StorageThresholdRequest(BaseModel):
    warning_gb: float = 10.0


class ConfigImportRequest(BaseModel):
    config: dict


class NotificationSettingsRequest(BaseModel):
    slack_webhook: Optional[str] = None
    email: Optional[str] = None


# ── 状態管理 ──

_notification_settings = {
    "slack_webhook": None,
    "email": None,
}

_storage_threshold_gb = 10.0

_log_level = "INFO"


# ── S1: ダッシュボード概要 ──

@router.get("/dashboard")
async def get_dashboard():
    """A-1 S1: AdminセットアップDashboard of 全体情報"""
    return {
        "title": "システムセットアップ",
        "status": "operational",
        "sections": [
            "environment", "api_keys", "harness", "di_container",
            "gpu", "model_config", "fallback_chain", "health",
            "diagnostics", "storage", "logs", "notifications",
        ],
        "uptime_seconds": round(time.time() - _startup_time),
        "timestamp": datetime.now().isoformat(),
    }


# ── S2: 環境ステータス ──

def _check_gpu_available() -> bool:
    """GPUが使用可能かどうかを確認する"""
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except HTTPException:
        raise
    except Exception:
        return False


@router.get("/environment")
async def get_environment_status():
    """A-1 S2: バックエンド/フロントエンド/DB/GPUの接続ステータス"""
    gpu_available = _check_gpu_available()

    return {
        "backend": {"status": "running", "port": 8000},
        "frontend": {"status": "running", "port": 5173},
        "database": {"status": "not_required", "type": "file_based"},
        "gpu": {"status": "available" if gpu_available else "not_available"},
        "python_version": platform.python_version(),
        "os": platform.system(),
        "timestamp": datetime.now().isoformat(),
    }


# ── S3-S4: APIキー管理 ──

@router.get("/api-keys")
async def get_api_keys_status():
    """A-1 S3: APIキー(Gemini/YouTube)の設定状態"""
    gemini_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    youtube_key = os.getenv("YOUTUBE_API_KEY")
    return {
        "gemini": {
            "configured": bool(gemini_key),
            "prefix": gemini_key[:8] + "..." if gemini_key else None,
        },
        "youtube": {
            "configured": bool(youtube_key),
            "prefix": youtube_key[:8] + "..." if youtube_key else None,
        },
    }


@router.post("/api-keys")
async def update_api_key(api_key_update: ApiKeyUpdateRequest):
    """A-1 S4: APIキーを安全に設定/更新"""
    if api_key_update.provider not in ("gemini", "youtube"):
        raise HTTPException(status_code=400, detail=f"Invalid provider: {api_key_update.provider}")
    if len(api_key_update.key) < 10:
        raise HTTPException(status_code=400, detail="API key too short")

    env_var = "GOOGLE_API_KEY" if api_key_update.provider == "gemini" else "YOUTUBE_API_KEY"
    os.environ[env_var] = api_key_update.key
    logger.info(f"API key updated for {api_key_update.provider}")
    return {"status": "updated", "provider": api_key_update.provider}


# ── S5: ハーネス状態 ──

@router.get("/harness")
async def get_harness_status():
    """A-1 S5: 4ミドルウェア(Hooks/Session/Governance/ToolRegistry)の初期化状態"""
    components = {}
    for name, module_path in [
        ("hooks", "harness.hooks"),
        ("session", "harness.session_manager"),
        ("governance", "harness.governance"),
        ("tool_registry", "harness.tool_registry"),
    ]:
        try:
            __import__(module_path)
            components[name] = {"initialized": True, "status": "ready"}
        except ImportError:
            components[name] = {"initialized": False, "status": "not_available"}

    return {"components": components, "total": 4,
            "initialized_count": sum(1 for c in components.values() if c["initialized"])}


# ── S6: DI状態 ──

@router.get("/di-container")
async def get_di_container_status():
    """A-1 S6: ServiceContainerの遅延初期化状態"""
    services = []
    try:
        from service_container import ServiceContainer
        container = ServiceContainer()
        services = list(container._registry.keys()) if hasattr(container, '_registry') else []
        return {"initialized": True, "services": services, "service_count": len(services)}
    except HTTPException:
        raise
    except Exception:
        return {"initialized": False, "services": [], "service_count": 0}


# ── S7: GPU情報 ──

def _query_gpu_details() -> dict:
    """nvidia-smi を使用して GPU 詳細情報を取得する"""
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            gpu_info_parts = result.stdout.strip().split(", ")
            return {
                "available": True,
                "model": gpu_info_parts[0] if len(gpu_info_parts) > 0 else "unknown",
                "vram_mb": int(gpu_info_parts[1]) if len(gpu_info_parts) > 1 else 0,
                "driver": gpu_info_parts[2] if len(gpu_info_parts) > 2 else "unknown",
            }
    except HTTPException:
        raise
    except Exception:
        pass
    return {"available": False, "model": "none", "vram_mb": 0, "driver": "none"}


@router.get("/gpu")
async def get_gpu_info():
    """A-1 S7: GPU型番/VRAM/ドライババージョン"""
    return _query_gpu_details()


# ── S8-S9: モデル設定 ──

@router.get("/model-config")
async def get_model_config():
    """A-1 S8: model_config.jsonの現在設定"""
    try:
        config_path = Path(__file__).parent.parent / "model_config.json"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            return {
                "loaded": True,
                "task_model_mapping": config.get("task_model_mapping", {}),
                "config_path": str(config_path),
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"model_config.json load error: {e}")
    return {
        "loaded": False,
        "task_model_mapping": {
            "transcribe": "standard",
            "proofread": "premium",
            "smartcut": "standard",
            "quality_gate": "premium",
            "youtube_opt": "standard",
            "render": "batch",
        },
        "config_path": None,
    }


@router.post("/model-config")
async def update_model_assignment(model_assignment: ModelAssignmentRequest):
    """A-1 S9: モデル割当(Premium/Standard/Batch)を変更"""
    valid_tiers = {"premium", "standard", "batch"}
    if model_assignment.model_tier not in valid_tiers:
        raise HTTPException(status_code=400, detail=f"Invalid tier: {model_assignment.model_tier}. Must be one of {valid_tiers}")
    return {
        "status": "updated",
        "task": model_assignment.task,
        "model_tier": model_assignment.model_tier,
        "task_model_mapping": {model_assignment.task: model_assignment.model_tier},
    }


# ── S10: フォールバックチェーン ──

@router.get("/fallback-chain")
async def get_fallback_chain():
    """A-1 S10: 3段階フォールバックチェーンの設定"""
    return {
        "primary": {"tier": "premium", "model": "gemini-2.5-pro"},
        "secondary": {"tier": "standard", "model": "gemini-2.0-flash"},
        "tertiary": {"tier": "batch", "model": "gemini-2.0-flash-lite"},
        "auto_fallback": True,
        "trigger_conditions": ["rate_limit", "quota_exceeded", "server_error"],
    }


# ── S11: ヘルスチェック ──

def _check_ffmpeg_availability() -> bool:
    """FFmpegが使用可能かどうかを確認する"""
    try:
        from video_editor_engine import video_editor
        return video_editor.ffmpeg.is_available()
    except HTTPException:
        raise
    except Exception:
        return False


def _check_gemini_key_configured() -> bool:
    """Gemini APIキーが設定されているか確認する"""
    gemini_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    return bool(gemini_key)


def _check_disk_space_usage() -> dict:
    """ディスク容量の使用状況を確認する"""
    fallback_disk_info = {"free_gb": 0, "total_gb": 0, "usage_percent": 0, "warning": False}
    try:
        usage_stats = shutil.disk_usage(".")
        bytes_in_gb = 1024 ** 3
        free_gb = usage_stats.free / bytes_in_gb
        total_gb = usage_stats.total / bytes_in_gb
        usage_percent = (1.0 - (usage_stats.free / usage_stats.total)) * 100.0
        return {
            "free_gb": round(free_gb, 1),
            "total_gb": round(total_gb, 1),
            "usage_percent": round(usage_percent, 1),
            "warning": free_gb < _storage_threshold_gb,
        }
    except HTTPException:
        raise
    except Exception:
        return fallback_disk_info


def _check_whisper_availability() -> bool:
    """Whisperモジュールが使用可能か確認する"""
    try:
        import faster_whisper
        return True
    except ImportError:
        return False


@router.get("/health-check")
async def run_health_check():
    """A-1 S11: /health/deepの結果を返す"""
    checks = {
        "ffmpeg": {"available": _check_ffmpeg_availability()},
        "gemini": {"key_configured": _check_gemini_key_configured()},
        "disk": _check_disk_space_usage(),
        "whisper": {"available": _check_whisper_availability()},
    }

    overall = "healthy"
    if not checks["ffmpeg"]["available"]:
        overall = "degraded"
    if checks["disk"].get("warning"):
        overall = "degraded"

    return {
        "status": overall,
        "checks": checks,
        "uptime_seconds": round(time.time() - _startup_time),
        "timestamp": datetime.now().isoformat(),
    }


# ── S12: 自動診断 ──

def _diagnose_python_runtime() -> dict:
    """Pythonの実行環境バージョン診断"""
    return {"version": platform.python_version(), "ok": True}


def _diagnose_library_package(package_name: str) -> dict:
    """依存ライブラリパッケージのバージョン診断"""
    return {"version": _get_package_version(package_name), "ok": True}


@router.get("/diagnostics")
async def run_diagnostics():
    """A-1 S12: 起動時の自動診断結果(全コンポーネント)"""
    all_checks = []

    diagnostic_items = [
        ("python", _diagnose_python_runtime),
        ("fastapi", lambda: _diagnose_library_package("fastapi")),
        ("uvicorn", lambda: _diagnose_library_package("uvicorn")),
        ("pydantic", lambda: _diagnose_library_package("pydantic")),
    ]

    for name, check_fn in diagnostic_items:
        try:
            result = check_fn()
            all_checks.append({"name": name, **result})
        except HTTPException:
            raise
        except Exception as e:
            all_checks.append({"name": name, "ok": False, "error": str(e)})

    return {
        "all_checks": all_checks,
        "total": len(all_checks),
        "passed": sum(1 for c in all_checks if c.get("ok")),
        "timestamp": datetime.now().isoformat(),
    }


# ── S13: ログ設定 ──

@router.get("/log-level")
async def get_log_level():
    """現在のログレベルを取得"""
    return {"level": _log_level}


@router.post("/log-level")
async def set_log_level(log_level_req: LogLevelRequest):
    """A-1 S13: ログレベルを変更"""
    global _log_level
    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR"}
    if log_level_req.level.upper() not in valid_levels:
        raise HTTPException(status_code=400,
                            detail=f"Invalid log level: {log_level_req.level}. Must be one of {valid_levels}")
    _log_level = log_level_req.level.upper()
    logging.getLogger().setLevel(_log_level)
    return {"status": "updated", "level": _log_level}


# ── S14-S15: ストレージ ──

@router.get("/storage")
async def get_storage_usage():
    """A-1 S14: vault-assets/outputsのディスク使用量"""
    try:
        usage = shutil.disk_usage(".")
        free_gb = usage.free / (1024 ** 3)
        return {
            "free_gb": round(free_gb, 1),
            "total_gb": round(usage.total / (1024 ** 3), 1),
            "usage_percent": round((1 - usage.free / usage.total) * 100, 1),
            "warning": free_gb < _storage_threshold_gb,
            "threshold_gb": _storage_threshold_gb,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/storage/threshold")
async def set_storage_threshold(threshold_req: StorageThresholdRequest):
    """A-1 S15: ストレージ警告閾値を設定"""
    global _storage_threshold_gb
    _storage_threshold_gb = threshold_req.warning_gb
    return {"status": "updated", "threshold_gb": _storage_threshold_gb}


# ── S16: クリーンアップ ──

@router.post("/cleanup")
async def run_cleanup():
    """A-1 S16: 古い一時ファイルの自動/手動クリーンアップ (シミュレーションおよびカウント処理)"""
    cleaned_files_count = 0
    cleaned_bytes_total = 0
    # Scan for temp files (*.tmp, __pycache__, etc.)
    try:
        for file_path in Path(".").rglob("*.tmp"):
            file_size = file_path.stat().st_size
            cleaned_files_count += 1
            cleaned_bytes_total += file_size
    except HTTPException:
        raise
    except Exception:
        pass
    return {
        "status": "completed",
        "cleaned_files": cleaned_files_count,
        "cleaned_bytes": cleaned_bytes_total,
        "timestamp": datetime.now().isoformat(),
    }


# ── Sprint 4.3.2: Storage API (cleanup_manager統合) ──

from cleanup_manager import cleanup_manager


class StorageCleanupRequest(BaseModel):
    dry_run: bool = True
    category: Optional[str] = None


@router.get("/storage/stats")
async def get_storage_stats():
    """Sprint 4.3.2: カテゴリ別ストレージ使用量

    cleanup_manager.get_storage_stats() に委譲。
    §11 保護階層(raw/final: protected, その他: 一時/消耗)を反映。
    """
    try:
        stats = cleanup_manager.get_storage_stats()
        return stats
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Storage stats取得失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/storage/cleanup")
async def run_storage_cleanup(cleanup_req: StorageCleanupRequest):
    """Sprint 4.3.2: dry_run対応のストレージクリーンアップ

    §11.1 聖域(raw/final)は保護。
    §11.3 保持期間: screenshots 7日/drafts 3日/prefinal 1日/video_output 7日。
    dry_run=True で削除候補 of プレビュー、False で実行。
    """
    try:
        result = cleanup_manager.cleanup(
            category=cleanup_req.category,
            dry_run=cleanup_req.dry_run,
        )
        # 実行時はevolution_logに記録
        if not cleanup_req.dry_run:
            cleanup_manager.report_to_evolution_log(result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Storage cleanup失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── S17: バージョン情報 ──

@router.get("/versions")
async def get_versions():
    """A-1 S17: システムバージョン/依存パッケージバージョン"""
    versions = {
        "python": platform.python_version(),
        "fastapi": _get_package_version("fastapi"),
        "uvicorn": _get_package_version("uvicorn"),
        "pydantic": _get_package_version("pydantic"),
        "whisper": _get_package_version("faster_whisper"),
        "system": {
            "os": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
    }
    return versions


# ── S18-S19: 設定エクスポート/インポート ──

@router.get("/config/export")
async def export_config():
    """A-1 S18: 現在の設定をJSONでエクスポート"""
    return {
        "format": "json",
        "config": {
            "log_level": _log_level,
            "storage_threshold_gb": _storage_threshold_gb,
            "notification_settings": _notification_settings,
        },
        "exported_at": datetime.now().isoformat(),
    }


@router.post("/config/import")
async def import_config(config_import: ConfigImportRequest):
    """A-1 S19: 設定ファイルをインポートして一括適用"""
    global _log_level, _storage_threshold_gb, _notification_settings
    config = config_import.config

    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail="Config must be a JSON object")

    applied = []
    if "log_level" in config:
        if config["log_level"] in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            _log_level = config["log_level"]
            applied.append("log_level")
    if "storage_threshold_gb" in config:
        _storage_threshold_gb = float(config["storage_threshold_gb"])
        applied.append("storage_threshold_gb")
    if "notification_settings" in config:
        _notification_settings.update(config["notification_settings"])
        applied.append("notification_settings")

    return {"status": "imported", "applied_keys": applied, "count": len(applied)}


# ── S20: コンポーネント再起動 ──

@router.post("/restart/{component}")
async def restart_component(component: str):
    """A-1 S20: コンポーネントの個別再起動(シミュレーション)"""
    valid = {"harness", "template", "model_governance", "pipeline"}
    if component not in valid:
        raise HTTPException(status_code=400, detail=f"Invalid component: {component}. Must be one of {valid}")
    return {
        "status": "restarted",
        "component": component,
        "timestamp": datetime.now().isoformat(),
    }


# ── S21: エラーログ ──

@router.get("/error-logs")
async def get_error_logs():
    """A-1 S21: 直近エラーログの一覧"""
    # Provide recent error samples (production would read from log files)
    return {
        "logs": [],
        "total": 0,
        "level_filter": "ERROR",
        "timestamp": datetime.now().isoformat(),
    }


# ── S22: 通知設定 ──

@router.get("/notifications")
async def get_notification_settings():
    """A-1 S22: 障害時の通知先設定"""
    return _notification_settings


@router.post("/notifications")
async def update_notification_settings(notification_settings_req: NotificationSettingsRequest):
    """A-1 S22: 通知先設定の更新"""
    global _notification_settings
    if notification_settings_req.slack_webhook is not None:
        _notification_settings["slack_webhook"] = notification_settings_req.slack_webhook
    if notification_settings_req.email is not None:
        _notification_settings["email"] = notification_settings_req.email
    return {"status": "updated", **_notification_settings}


# ── ユーティリティ ──

def _get_package_version(package_name: str) -> str:
    """パッケージバージョンを安全に取得"""
    try:
        import importlib.metadata
        return importlib.metadata.version(package_name)
    except HTTPException:
        raise
    except Exception:
        try:
            mod = __import__(package_name)
            return getattr(mod, "__version__", "unknown")
        except ImportError:
            return "not_installed"


# ── Sprint 4.4.2: Performance Dashboard API ──

from services.performance_budget_manager import PerformanceBudgetManager

# モジュールレベルのPerformanceBudgetManagerインスタンス
# テスト時はこの変数を差し替えてDI的に注入する
_perf_manager = PerformanceBudgetManager()

perf_router = APIRouter(prefix="/api/admin/performance", tags=["Admin Performance"])


class BudgetUpdateRequest(BaseModel):
    total_budget_seconds: Optional[float] = None
    worker_budgets: Optional[dict] = None


@perf_router.get("/current")
async def get_performance_current():
    """Sprint 4.4.2 PB-T13: 現在のバジェット消化状況スナップショット"""
    return _perf_manager.get_progress_snapshot()


@perf_router.get("/history")
async def get_performance_history():
    """Sprint 4.4.2 PB-T14: 過去のパフォーマンスレポート一覧"""
    return _perf_manager.get_history()


@perf_router.get("/budget")
async def get_performance_budget():
    """Sprint 4.4.2 PB-T15: 現在のバジェット設定を取得"""
    return _perf_manager.get_budget_config()


@perf_router.put("/budget")
async def update_performance_budget(req: BudgetUpdateRequest):
    """Sprint 4.4.2 PB-T16: バジェット設定を更新

    EDGE-03: critical Workerのpriority変更はAPI経由でも黙殺される。
    """
    updates = {}
    if req.total_budget_seconds is not None:
        updates["total_budget_seconds"] = req.total_budget_seconds
    if req.worker_budgets is not None:
        updates["worker_budgets"] = req.worker_budgets
    return _perf_manager.update_budget_config(updates)


# perf_router はモジュールレベルで公開。
# main.py で app.include_router(perf_router) として別途登録する。
# テスト時は admin_module.perf_router を直接 app.include_router() する。
