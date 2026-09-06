"""
Unit tests for backend/routers/admin_setup_router.py
Provides 100% coverage by testing all endpoints and error-handling branches.
"""

import os
import sys
import json
import shutil
import pytest
from unittest.mock import MagicMock, patch, mock_open
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from types import ModuleType

# Ensure the backend directory is in python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.admin_setup_router import (
    router,
    perf_router,
    _get_package_version,
    _notification_settings,
    _storage_threshold_gb,
    _log_level,
)

# Crucial: routers/__init__.py overrides the attribute to the APIRouter instance,
# so we must retrieve the original module object directly from sys.modules.
import routers.admin_setup_router
admin_module = sys.modules["routers.admin_setup_router"]

@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    app.include_router(perf_router)
    return TestClient(app)

# S1: Dashboard
def test_get_dashboard(client):
    response = client.get("/api/admin/setup/dashboard")
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "システムセットアップ"
    assert "sections" in data
    assert "uptime_seconds" in data

# S2: Environment Status
def test_get_environment_status_gpu_available(client, monkeypatch):
    def mock_run(*args, **kwargs):
        return MagicMock(returncode=0)
    monkeypatch.setattr("subprocess.run", mock_run)
    response = client.get("/api/admin/setup/environment")
    assert response.status_code == 200
    assert response.json()["gpu"]["status"] == "available"

def test_get_environment_status_gpu_not_available(client, monkeypatch):
    def mock_run(*args, **kwargs):
        return MagicMock(returncode=1)
    monkeypatch.setattr("subprocess.run", mock_run)
    response = client.get("/api/admin/setup/environment")
    assert response.status_code == 200
    assert response.json()["gpu"]["status"] == "not_available"

def test_get_environment_status_exception(client, monkeypatch):
    def mock_run(*args, **kwargs):
        raise Exception("subprocess run failed")
    monkeypatch.setattr("subprocess.run", mock_run)
    response = client.get("/api/admin/setup/environment")
    assert response.status_code == 200
    assert response.json()["gpu"]["status"] == "not_available"

def test_get_environment_status_http_exception(client, monkeypatch):
    def mock_run(*args, **kwargs):
        raise HTTPException(status_code=500, detail="http_err")
    monkeypatch.setattr("subprocess.run", mock_run)
    response = client.get("/api/admin/setup/environment")
    assert response.status_code == 500

# S3-S4: API Key Management
def test_api_keys_flow(client, monkeypatch):
    # Setting values
    monkeypatch.setenv("GOOGLE_API_KEY", "gemini_key_long_value_here")
    monkeypatch.setenv("YOUTUBE_API_KEY", "youtube_key_long_value_here")
    response = client.get("/api/admin/setup/api-keys")
    assert response.status_code == 200
    data = response.json()
    assert data["gemini"]["configured"] is True
    assert data["gemini"]["prefix"] == "gemini_k..."
    assert data["youtube"]["configured"] is True
    assert data["youtube"]["prefix"] == "youtube_..."

    # Clearing values
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    response = client.get("/api/admin/setup/api-keys")
    assert response.status_code == 200
    data = response.json()
    assert data["gemini"]["configured"] is False
    assert data["gemini"]["prefix"] is None

    # Update Gemini
    response = client.post("/api/admin/setup/api-keys", json={"provider": "gemini", "key": "new_gemini_key_value"})
    assert response.status_code == 200
    assert response.json()["status"] == "updated"
    assert os.getenv("GOOGLE_API_KEY") == "new_gemini_key_value"

    # Update YouTube
    response = client.post("/api/admin/setup/api-keys", json={"provider": "youtube", "key": "new_youtube_key_value"})
    assert response.status_code == 200
    assert response.json()["status"] == "updated"
    assert os.getenv("YOUTUBE_API_KEY") == "new_youtube_key_value"

    # Invalid provider
    response = client.post("/api/admin/setup/api-keys", json={"provider": "invalid", "key": "new_youtube_key_value"})
    assert response.status_code == 400

    # Key too short
    response = client.post("/api/admin/setup/api-keys", json={"provider": "gemini", "key": "short"})
    assert response.status_code == 400

# S5: Harness Status
def test_get_harness_status_success(client):
    mock_modules = [
        "harness",
        "harness.hooks",
        "harness.session_manager",
        "harness.governance",
        "harness.tool_registry"
    ]
    with patch.dict("sys.modules", {m: ModuleType(m) for m in mock_modules}):
        response = client.get("/api/admin/setup/harness")
        assert response.status_code == 200
        data = response.json()
        assert data["initialized_count"] == 4

def test_get_harness_status_import_error(client):
    mock_modules = [
        "harness",
        "harness.hooks",
        "harness.session_manager",
        "harness.governance",
        "harness.tool_registry"
    ]
    with patch.dict("sys.modules", {m: None for m in mock_modules}):
        response = client.get("/api/admin/setup/harness")
        assert response.status_code == 200
        data = response.json()
        assert data["initialized_count"] == 0

# S6: DI Container
def test_get_di_container_status_success(client):
    class MockContainer:
        _registry = {"service_a": "value_a"}
    with patch("service_container.ServiceContainer", MockContainer):
        response = client.get("/api/admin/setup/di-container")
        assert response.status_code == 200
        assert response.json()["initialized"] is True
        assert response.json()["services"] == ["service_a"]

def test_get_di_container_status_exception(client):
    def mock_init(self):
        raise Exception("mocked init error")
    with patch("service_container.ServiceContainer.__init__", mock_init):
        response = client.get("/api/admin/setup/di-container")
        assert response.status_code == 200
        assert response.json()["initialized"] is False

def test_get_di_container_status_http_exception(client):
    def mock_init(self):
        raise HTTPException(status_code=500, detail="http_err")
    with patch("service_container.ServiceContainer.__init__", mock_init):
        response = client.get("/api/admin/setup/di-container")
        assert response.status_code == 500

# S7: GPU Info
def test_get_gpu_info_success(client, monkeypatch):
    def mock_run(*args, **kwargs):
        return MagicMock(returncode=0, stdout="GeForce RTX 4090, 24576, 550.54\n")
    monkeypatch.setattr("subprocess.run", mock_run)
    response = client.get("/api/admin/setup/gpu")
    assert response.status_code == 200
    data = response.json()
    assert data["available"] is True
    assert data["model"] == "GeForce RTX 4090"
    assert data["vram_mb"] == 24576
    assert data["driver"] == "550.54"

def test_get_gpu_info_parts_short(client, monkeypatch):
    def mock_run(*args, **kwargs):
        return MagicMock(returncode=0, stdout="GeForce RTX 4090\n")
    monkeypatch.setattr("subprocess.run", mock_run)
    response = client.get("/api/admin/setup/gpu")
    assert response.status_code == 200
    data = response.json()
    assert data["available"] is True
    assert data["model"] == "GeForce RTX 4090"
    assert data["vram_mb"] == 0
    assert data["driver"] == "unknown"

def test_get_gpu_info_not_available(client, monkeypatch):
    def mock_run(*args, **kwargs):
        return MagicMock(returncode=1, stdout="")
    monkeypatch.setattr("subprocess.run", mock_run)
    response = client.get("/api/admin/setup/gpu")
    assert response.status_code == 200
    assert response.json()["available"] is False

def test_get_gpu_info_exception(client, monkeypatch):
    def mock_run(*args, **kwargs):
        raise Exception("error")
    monkeypatch.setattr("subprocess.run", mock_run)
    response = client.get("/api/admin/setup/gpu")
    assert response.status_code == 200
    assert response.json()["available"] is False

def test_get_gpu_info_http_exception(client, monkeypatch):
    def mock_run(*args, **kwargs):
        raise HTTPException(status_code=500, detail="http_err")
    monkeypatch.setattr("subprocess.run", mock_run)
    response = client.get("/api/admin/setup/gpu")
    assert response.status_code == 500

# S8-S9: Model Config
def test_get_model_config_loaded(client):
    dummy_data = {
        "task_model_mapping": {
            "transcribe": "standard_mock",
            "proofread": "premium_mock"
        }
    }
    with patch("pathlib.Path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=json.dumps(dummy_data))):
            response = client.get("/api/admin/setup/model-config")
            assert response.status_code == 200
            data = response.json()
            assert data["loaded"] is True
            assert data["task_model_mapping"]["transcribe"] == "standard_mock"

def test_get_model_config_not_found(client):
    with patch("pathlib.Path.exists", return_value=False):
        response = client.get("/api/admin/setup/model-config")
        assert response.status_code == 200
        data = response.json()
        assert data["loaded"] is False
        assert data["task_model_mapping"]["transcribe"] == "standard"

def test_get_model_config_exception(client):
    with patch("pathlib.Path.exists", side_effect=Exception("path error")):
        response = client.get("/api/admin/setup/model-config")
        assert response.status_code == 200
        assert response.json()["loaded"] is False

def test_get_model_config_http_exception(client):
    with patch("pathlib.Path.exists", side_effect=HTTPException(status_code=500, detail="http_err")):
        response = client.get("/api/admin/setup/model-config")
        assert response.status_code == 500

def test_update_model_assignment(client):
    response = client.post("/api/admin/setup/model-config", json={"task": "transcribe", "model_tier": "premium"})
    assert response.status_code == 200
    assert response.json()["status"] == "updated"
    
    response = client.post("/api/admin/setup/model-config", json={"task": "transcribe", "model_tier": "invalid"})
    assert response.status_code == 400

# S10: Fallback Chain
def test_get_fallback_chain(client):
    response = client.get("/api/admin/setup/fallback-chain")
    assert response.status_code == 200
    assert response.json()["auto_fallback"] is True


def test_fallback_chainは正典の段から引く(client):
    """**定数を返さない**（R1.5-C6）。

    2026-08-28 まで `gemini-2.5-pro` / `gemini-2.0-flash` /
    `gemini-2.0-flash-lite` を直書きしていた。どれも段の実体と違ううえ、
    2.5 系は 2026-10-16 に提供終了する。API が返す値なので、画面には
    「いま動いているモデル」として出ていた。
    """
    from model_policy import tiers

    段 = tiers()
    payload = client.get("/api/admin/setup/fallback-chain").json()

    assert payload["primary"]["model"] == 段["premium"]["model"]
    assert payload["secondary"]["model"] == 段["standard"]["model"]
    assert payload["tertiary"]["model"] == 段["batch"]["model"]
    for 段名 in ("primary", "secondary", "tertiary"):
        assert not payload[段名]["model"].startswith("gemini-2.5"), payload[段名]


def test_fallback_chainは読めなければ定数で埋めない(client):
    """**読めなかったことを「これが現在の設定です」と言わない**（R1.5-C4）。"""
    with patch("routers.admin_setup_router._tier_models",
               side_effect=OSError("読めません")):
        response = client.get("/api/admin/setup/fallback-chain")

    assert response.status_code == 503, response.text

# S11: Health Check
def test_run_health_check_healthy(client, monkeypatch):
    class MockFFmpeg:
        def is_available(self):
            return True
    class MockVideoEditor:
        ffmpeg = MockFFmpeg()
    
    with patch("video_editor_engine.video_editor", MockVideoEditor()):
        monkeypatch.setenv("GOOGLE_API_KEY", "configured_key")
        
        def mock_disk_usage(path):
            return MagicMock(total=100 * (1024**3), free=50 * (1024**3))
        monkeypatch.setattr("shutil.disk_usage", mock_disk_usage)
        
        with patch.dict("sys.modules", {"faster_whisper": ModuleType("faster_whisper")}):
            response = client.get("/api/admin/setup/health-check")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["checks"]["ffmpeg"]["available"] is True
            assert data["checks"]["disk"]["warning"] is False

def test_run_health_check_degraded_ffmpeg_missing(client, monkeypatch):
    class MockFFmpeg:
        def is_available(self):
            return False
    class MockVideoEditor:
        ffmpeg = MockFFmpeg()
    
    with patch("video_editor_engine.video_editor", MockVideoEditor()):
        def mock_disk_usage(path):
            return MagicMock(total=100 * (1024**3), free=50 * (1024**3))
        monkeypatch.setattr("shutil.disk_usage", mock_disk_usage)
        
        response = client.get("/api/admin/setup/health-check")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["checks"]["ffmpeg"]["available"] is False

def test_run_health_check_degraded_disk_warning(client, monkeypatch):
    class MockFFmpeg:
        def is_available(self):
            return True
    class MockVideoEditor:
        ffmpeg = MockFFmpeg()
    
    with patch("video_editor_engine.video_editor", MockVideoEditor()):
        def mock_disk_usage(path):
            # free space = 5GB < threshold (10GB)
            return MagicMock(total=100 * (1024**3), free=5 * (1024**3))
        monkeypatch.setattr("shutil.disk_usage", mock_disk_usage)
        
        response = client.get("/api/admin/setup/health-check")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["checks"]["disk"]["warning"] is True

def test_run_health_check_exceptions(client, monkeypatch):
    mock_editor = MagicMock()
    mock_editor.ffmpeg.is_available.side_effect = Exception("video error")
    with patch("video_editor_engine.video_editor", mock_editor):
        monkeypatch.setattr("shutil.disk_usage", MagicMock(side_effect=Exception("disk error")))
        with patch.dict("sys.modules", {"faster_whisper": None}):
            response = client.get("/api/admin/setup/health-check")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "degraded"

def test_run_health_check_http_exception(client, monkeypatch):
    mock_editor = MagicMock()
    mock_editor.ffmpeg.is_available.side_effect = HTTPException(status_code=500, detail="http_err")
    with patch("video_editor_engine.video_editor", mock_editor):
        response = client.get("/api/admin/setup/health-check")
        assert response.status_code == 500

    class MockFFmpeg:
        def is_available(self):
            return True
    class MockVideoEditor:
        ffmpeg = MockFFmpeg()
    with patch("video_editor_engine.video_editor", MockVideoEditor()):
        monkeypatch.setattr("shutil.disk_usage", MagicMock(side_effect=HTTPException(status_code=500, detail="http_err")))
        response = client.get("/api/admin/setup/health-check")
        assert response.status_code == 500

# S12: Diagnostics
def test_run_diagnostics(client, monkeypatch):
    def mock_get_package_version(name):
        if name == "fastapi":
            return "0.100.0"
        elif name == "uvicorn":
            raise Exception("diagnostics error")
        return "1.0"
    
    monkeypatch.setattr(admin_module, "_get_package_version", mock_get_package_version)
    response = client.get("/api/admin/setup/diagnostics")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 4
    assert data["passed"] == 3

def test_run_diagnostics_http_exception(client, monkeypatch):
    def mock_get_package_version(name):
        raise HTTPException(status_code=500, detail="http_err")
    monkeypatch.setattr(admin_module, "_get_package_version", mock_get_package_version)
    response = client.get("/api/admin/setup/diagnostics")
    assert response.status_code == 500

# S13: Log Level
def test_log_level_flow(client):
    response = client.get("/api/admin/setup/log-level")
    assert response.status_code == 200
    
    response = client.post("/api/admin/setup/log-level", json={"level": "DEBUG"})
    assert response.status_code == 200
    assert response.json()["level"] == "DEBUG"
    
    response = client.post("/api/admin/setup/log-level", json={"level": "INVALID"})
    assert response.status_code == 400

# S14-S15: Storage Usage & Threshold
def test_get_storage_usage_success(client, monkeypatch):
    def mock_disk_usage(path):
        return MagicMock(total=100 * (1024**3), free=50 * (1024**3))
    monkeypatch.setattr("shutil.disk_usage", mock_disk_usage)
    response = client.get("/api/admin/setup/storage")
    assert response.status_code == 200
    assert response.json()["free_gb"] == 50.0

def test_get_storage_usage_exception(client, monkeypatch):
    monkeypatch.setattr("shutil.disk_usage", MagicMock(side_effect=Exception("storage error")))
    response = client.get("/api/admin/setup/storage")
    assert response.status_code == 500

def test_get_storage_usage_http_exception(client, monkeypatch):
    monkeypatch.setattr("shutil.disk_usage", MagicMock(side_effect=HTTPException(status_code=400, detail="http_err")))
    response = client.get("/api/admin/setup/storage")
    assert response.status_code == 400

def test_set_storage_threshold(client):
    response = client.post("/api/admin/setup/storage/threshold", json={"warning_gb": 15.0})
    assert response.status_code == 200

# S16: Cleanup
def test_run_cleanup(client, monkeypatch, tmp_path):
    tmp_file = tmp_path / "test.tmp"
    tmp_file.write_text("dummy")
    
    def mock_rglob(self, pattern):
        if pattern == "*.tmp":
            return [tmp_file]
        return []
    
    monkeypatch.setattr("pathlib.Path.rglob", mock_rglob)
    response = client.post("/api/admin/setup/cleanup")
    assert response.status_code == 200
    assert response.json()["cleaned_files"] == 1

def test_run_cleanup_exception(client, monkeypatch):
    monkeypatch.setattr("pathlib.Path.rglob", MagicMock(side_effect=Exception("rglob error")))
    response = client.post("/api/admin/setup/cleanup")
    assert response.status_code == 200

def test_run_cleanup_http_exception(client, monkeypatch):
    monkeypatch.setattr("pathlib.Path.rglob", MagicMock(side_effect=HTTPException(status_code=500, detail="http_err")))
    response = client.post("/api/admin/setup/cleanup")
    assert response.status_code == 500

# Storage Stats & Cleanup Delegation (Sprint 4.3.2)
def test_get_storage_stats(client):
    mock_stats = {"category": "test", "bytes": 100}
    with patch("cleanup_manager.cleanup_manager.get_storage_stats", return_value=mock_stats):
        response = client.get("/api/admin/setup/storage/stats")
        assert response.status_code == 200
        assert response.json() == mock_stats

def test_get_storage_stats_exception(client):
    with patch("cleanup_manager.cleanup_manager.get_storage_stats", side_effect=Exception("manager error")):
        response = client.get("/api/admin/setup/storage/stats")
        assert response.status_code == 500

def test_get_storage_stats_http_exception(client):
    with patch("cleanup_manager.cleanup_manager.get_storage_stats", side_effect=HTTPException(status_code=400, detail="http_err")):
        response = client.get("/api/admin/setup/storage/stats")
        assert response.status_code == 400

def test_run_storage_cleanup_dry_run(client):
    mock_result = {"cleaned": 0}
    with patch("cleanup_manager.cleanup_manager.cleanup", return_value=mock_result) as mock_cleanup:
        response = client.post("/api/admin/setup/storage/cleanup", json={"dry_run": True, "category": "drafts"})
        assert response.status_code == 200
        assert response.json() == mock_result
        mock_cleanup.assert_called_once_with(category="drafts", dry_run=True)

def test_run_storage_cleanup_real(client):
    mock_result = {"cleaned": 10}
    with patch("cleanup_manager.cleanup_manager.cleanup", return_value=mock_result) as mock_cleanup:
        with patch("cleanup_manager.cleanup_manager.report_to_evolution_log") as mock_report:
            response = client.post("/api/admin/setup/storage/cleanup", json={"dry_run": False, "category": "drafts"})
            assert response.status_code == 200
            assert response.json() == mock_result
            mock_cleanup.assert_called_once_with(category="drafts", dry_run=False)
            mock_report.assert_called_once_with(mock_result)

def test_run_storage_cleanup_exception(client):
    with patch("cleanup_manager.cleanup_manager.cleanup", side_effect=Exception("cleanup error")):
        response = client.post("/api/admin/setup/storage/cleanup", json={"dry_run": False})
        assert response.status_code == 500

def test_run_storage_cleanup_http_exception(client):
    with patch("cleanup_manager.cleanup_manager.cleanup", side_effect=HTTPException(status_code=400, detail="http_err")):
        response = client.post("/api/admin/setup/storage/cleanup", json={"dry_run": False})
        assert response.status_code == 400

# S17: System Versions
def test_get_versions(client, monkeypatch):
    def mock_get(name):
        return "1.2.3"
    monkeypatch.setattr(admin_module, "_get_package_version", mock_get)
    response = client.get("/api/admin/setup/versions")
    assert response.status_code == 200
    assert response.json()["fastapi"] == "1.2.3"

# S18-S19: Config Export/Import
def test_config_export_import(client):
    response = client.get("/api/admin/setup/config/export")
    assert response.status_code == 200
    exported = response.json()
    
    import_data = {
        "log_level": "DEBUG",
        "storage_threshold_gb": 20.0,
        "notification_settings": {
            "slack_webhook": "http://slack.com",
            "email": "test@test.com"
        }
    }
    response = client.post("/api/admin/setup/config/import", json={"config": import_data})
    assert response.status_code == 200
    assert "log_level" in response.json()["applied_keys"]

    # Invalid import format
    response = client.post("/api/admin/setup/config/import", json={"config": "not_a_dict"})
    assert response.status_code == 422  # Pydantic validation error

@pytest.mark.asyncio
async def test_import_config_invalid_format_direct():
    from routers.admin_setup_router import import_config, ConfigImportRequest
    req = MagicMock(spec=ConfigImportRequest)
    req.config = "not_a_dict"
    with pytest.raises(HTTPException) as exc_info:
        await import_config(req)
    assert exc_info.value.status_code == 400

# S20: Restart Component
def test_restart_component(client):
    response = client.post("/api/admin/setup/restart/harness")
    assert response.status_code == 200
    assert response.json()["status"] == "restarted"
    
    response = client.post("/api/admin/setup/restart/invalid")
    assert response.status_code == 400

# S21: Error Logs
def test_get_error_logs(client):
    response = client.get("/api/admin/setup/error-logs")
    assert response.status_code == 200
    assert response.json()["logs"] == []

# S22: Notifications
def test_notification_settings(client):
    response = client.get("/api/admin/setup/notifications")
    assert response.status_code == 200
    
    response = client.post("/api/admin/setup/notifications", json={"slack_webhook": "http://newslack", "email": "new@email.com"})
    assert response.status_code == 200
    assert response.json()["slack_webhook"] == "http://newslack"
    assert response.json()["email"] == "new@email.com"

# Performance Dashboard API (Sprint 4.4.2)
def test_performance_endpoints(client):
    mock_snapshot = {"snapshot": "ok"}
    mock_history = ["history1"]
    mock_config = {"budget": 10}
    
    mock_perf = MagicMock()
    mock_perf.get_progress_snapshot.return_value = mock_snapshot
    mock_perf.get_history.return_value = mock_history
    mock_perf.get_budget_config.return_value = mock_config
    mock_perf.update_budget_config.return_value = {"updated": True}
    
    with patch.object(admin_module, "_perf_manager", mock_perf):
        response = client.get("/api/admin/performance/current")
        assert response.status_code == 200
        assert response.json() == mock_snapshot
        
        response = client.get("/api/admin/performance/history")
        assert response.status_code == 200
        assert response.json() == mock_history
        
        response = client.get("/api/admin/performance/budget")
        assert response.status_code == 200
        assert response.json() == mock_config
        
        response = client.put("/api/admin/performance/budget", json={"total_budget_seconds": 100.0, "worker_budgets": {"worker": 10.0}})
        assert response.status_code == 200
        assert response.json() == {"updated": True}

# Internal Package Version Helpers
def test_get_package_version_helpers(monkeypatch):
    # Test importlib.metadata.version returning version
    with patch("importlib.metadata.version", return_value="9.9.9"):
        assert _get_package_version("fastapi") == "9.9.9"

    # Test HTTP Exception
    def mock_version_http_exception(package_name):
        raise HTTPException(status_code=500, detail="http_err")
    
    with patch("importlib.metadata.version", mock_version_http_exception):
        with pytest.raises(HTTPException):
            _get_package_version("fastapi")
            
    def mock_version_exception(package_name):
        raise Exception("not found")
    
    class DummyModule:
        __version__ = "dummy_version"
    
    # Test __import__ success with __version__
    with patch("importlib.metadata.version", mock_version_exception):
        with patch.dict("sys.modules", {"dummy_package": DummyModule()}):
            assert _get_package_version("dummy_package") == "dummy_version"
            
    class DummyModuleNoVersion:
        pass
        
    # Test __import__ success without __version__
    with patch("importlib.metadata.version", mock_version_exception):
        with patch.dict("sys.modules", {"dummy_package_no_ver": DummyModuleNoVersion()}):
            assert _get_package_version("dummy_package_no_ver") == "unknown"

    # Test __import__ ImportError
    with patch("importlib.metadata.version", mock_version_exception):
        with patch.dict("sys.modules", {"non_existent_package": None}):
            assert _get_package_version("non_existent_package") == "not_installed"
