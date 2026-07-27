"""
ヘルスチェックルーターのユニットテスト
対象: backend/routers/health.py
"""

import sys
import os
import shutil
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI, HTTPException
try:
    import faster_whisper
except ImportError:
    pass
from fastapi.testclient import TestClient

# 対象ワークスペースの backend ディレクトリを sys.path に追加
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from routers.health import router as health_router

# テスト用のクリーンな FastAPI アプリケーションとクライアントを作成
app = FastAPI()
app.include_router(health_router)
client = TestClient(app)


def test_health_check_healthy(monkeypatch):
    """
    GET /health: すべて正常なケース (healthy)
    """
    # 1. Gemini環境変数をセット
    monkeypatch.setenv("GOOGLE_API_KEY", "AIzaSyTestKey123456")

    # 2. FFmpeg のモック
    mock_video_editor_module = MagicMock()
    mock_video_editor = MagicMock()
    mock_ffmpeg = MagicMock()
    mock_ffmpeg.is_available.return_value = True
    mock_ffmpeg.ffmpeg_path = "/usr/bin/ffmpeg"
    mock_ffmpeg.use_gpu = True
    
    mock_video_editor.ffmpeg = mock_ffmpeg
    mock_video_editor_module.video_editor = mock_video_editor

    # 3. ディスク容量のモック
    mock_usage = MagicMock()
    mock_usage.free = 20 * (1024 ** 3)  # 20 GB
    mock_usage.total = 100 * (1024 ** 3)  # 100 GB

    # sys.modules へのパッチ適用
    modules_patch = {
        "video_editor_engine": mock_video_editor_module,
        "safe_io": MagicMock(VAULT_OUTPUTS_DIR="vault_dir")
    }

    with patch.dict(sys.modules, modules_patch):
        with patch("shutil.disk_usage", return_value=mock_usage):
            response = client.get("/health")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["checks"]["ffmpeg"]["available"] is True
            assert data["checks"]["ffmpeg"]["gpu_nvenc"] is True
            assert data["checks"]["gemini"]["key_configured"] is True
            assert data["checks"]["gemini"]["key_prefix"] == "AIzaSyTe..."
            assert data["checks"]["disk"]["free_gb"] == 20.0
            assert data["checks"]["disk"]["warning"] is False


def test_health_check_degraded_due_to_gemini(monkeypatch):
    """
    GET /health: Gemini APIキーが設定されていないケース (degraded)
    """
    # Gemini環境変数を削除
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    # FFmpeg のモック (正常)
    mock_video_editor_module = MagicMock()
    mock_video_editor = MagicMock()
    mock_ffmpeg = MagicMock()
    mock_ffmpeg.is_available.return_value = True
    mock_ffmpeg.ffmpeg_path = "/usr/bin/ffmpeg"
    mock_ffmpeg.use_gpu = False
    
    mock_video_editor.ffmpeg = mock_ffmpeg
    mock_video_editor_module.video_editor = mock_video_editor

    # ディスク容量のモック (正常)
    mock_usage = MagicMock()
    mock_usage.free = 50 * (1024 ** 3)
    mock_usage.total = 100 * (1024 ** 3)

    modules_patch = {
        "video_editor_engine": mock_video_editor_module,
        "safe_io": MagicMock(VAULT_OUTPUTS_DIR="vault_dir")
    }

    with patch.dict(sys.modules, modules_patch):
        with patch("shutil.disk_usage", return_value=mock_usage):
            response = client.get("/health")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "degraded"
            assert data["checks"]["gemini"]["key_configured"] is False
            assert data["checks"]["disk"]["warning"] is False


def test_health_check_degraded_due_to_disk(monkeypatch):
    """
    GET /health: ディスク残容量が10GB未満のケース (degraded)
    """
    monkeypatch.setenv("GEMINI_API_KEY", "GeminiKey123")

    mock_video_editor_module = MagicMock()
    mock_video_editor = MagicMock()
    mock_ffmpeg = MagicMock()
    mock_ffmpeg.is_available.return_value = True
    mock_ffmpeg.ffmpeg_path = "/usr/bin/ffmpeg"
    mock_ffmpeg.use_gpu = False
    
    mock_video_editor.ffmpeg = mock_ffmpeg
    mock_video_editor_module.video_editor = mock_video_editor

    # ディスク容量のモック (警告状態: 残り5GB)
    mock_usage = MagicMock()
    mock_usage.free = 5 * (1024 ** 3)
    mock_usage.total = 100 * (1024 ** 3)

    modules_patch = {
        "video_editor_engine": mock_video_editor_module,
        "safe_io": MagicMock(VAULT_OUTPUTS_DIR="vault_dir")
    }

    with patch.dict(sys.modules, modules_patch):
        with patch("shutil.disk_usage", return_value=mock_usage):
            response = client.get("/health")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "degraded"
            assert data["checks"]["disk"]["warning"] is True


def test_health_check_unhealthy(monkeypatch):
    """
    GET /health: FFmpeg が利用不可のケース (unhealthy)
    """
    monkeypatch.setenv("GOOGLE_API_KEY", "Key123")

    # FFmpeg 利用不可
    mock_video_editor_module = MagicMock()
    mock_video_editor = MagicMock()
    mock_ffmpeg = MagicMock()
    mock_ffmpeg.is_available.return_value = False
    mock_ffmpeg.ffmpeg_path = ""
    mock_ffmpeg.use_gpu = False
    
    mock_video_editor.ffmpeg = mock_ffmpeg
    mock_video_editor_module.video_editor = mock_video_editor

    mock_usage = MagicMock()
    mock_usage.free = 20 * (1024 ** 3)
    mock_usage.total = 100 * (1024 ** 3)

    modules_patch = {
        "video_editor_engine": mock_video_editor_module,
        "safe_io": MagicMock(VAULT_OUTPUTS_DIR="vault_dir")
    }

    with patch.dict(sys.modules, modules_patch):
        with patch("shutil.disk_usage", return_value=mock_usage):
            response = client.get("/health")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "unhealthy"


def test_ffmpeg_exception_handling():
    """
    _check_ffmpeg(): インポート時や呼び出し時の一般例外のテスト
    """
    with patch.dict(sys.modules, {"video_editor_engine": None}):
        mock_broken = MagicMock()
        type(mock_broken).video_editor = property(lambda self: (_ for _ in ()).throw(ValueError("FFmpeg Load Error")))
        
        with patch.dict(sys.modules, {"video_editor_engine": mock_broken}):
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["checks"]["ffmpeg"]["available"] is False
            assert "FFmpeg Load Error" in data["checks"]["ffmpeg"]["error"]


def test_ffmpeg_http_exception_pass_through():
    """
    _check_ffmpeg(): HTTPException が発生した場合はそのまま透過されることの検証
    """
    mock_broken = MagicMock()
    type(mock_broken).video_editor = property(lambda self: (_ for _ in ()).throw(HTTPException(status_code=500, detail="HTTP Error")))
    
    with patch.dict(sys.modules, {"video_editor_engine": mock_broken}):
        response = client.get("/health")
        assert response.status_code == 500
        assert response.json()["detail"] == "HTTP Error"


def test_disk_space_import_error():
    """
    _check_disk_space(): safe_io インポートエラー時のフォールバック検証
    """
    with patch.dict(sys.modules, {"safe_io": None}):
        mock_video_editor_module = MagicMock()
        mock_video_editor = MagicMock()
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.is_available.return_value = True
        
        mock_video_editor.ffmpeg = mock_ffmpeg
        mock_video_editor_module.video_editor = mock_video_editor
        
        mock_usage = MagicMock()
        mock_usage.free = 20 * (1024 ** 3)
        mock_usage.total = 100 * (1024 ** 3)
        
        with patch.dict(sys.modules, {"video_editor_engine": mock_video_editor_module}):
            with patch("shutil.disk_usage", return_value=mock_usage) as mock_disk:
                response = client.get("/health")
                assert response.status_code == 200
                mock_disk.assert_called_with(".")


def test_disk_space_exception_handling():
    """
    _check_disk_space(): disk_usage で一般例外が発生したときの検証
    """
    mock_video_editor_module = MagicMock()
    mock_video_editor = MagicMock()
    mock_video_editor.ffmpeg.is_available.return_value = True
    mock_video_editor_module.video_editor = mock_video_editor

    with patch.dict(sys.modules, {"video_editor_engine": mock_video_editor_module, "safe_io": MagicMock()}):
        with patch("shutil.disk_usage", side_effect=OSError("Disk Unreadable")):
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert "Disk Unreadable" in data["checks"]["disk"]["error"]


def test_disk_space_http_exception_pass_through():
    """
    _check_disk_space(): disk_usage で HTTPException が発生したときの透過検証
    """
    mock_video_editor_module = MagicMock()
    mock_video_editor = MagicMock()
    mock_video_editor.ffmpeg.is_available.return_value = True
    mock_video_editor_module.video_editor = mock_video_editor

    with patch.dict(sys.modules, {"video_editor_engine": mock_video_editor_module, "safe_io": MagicMock()}):
        with patch("shutil.disk_usage", side_effect=HTTPException(status_code=400, detail="Disk HTTP Error")):
            response = client.get("/health")
            assert response.status_code == 400
            assert response.json()["detail"] == "Disk HTTP Error"


def test_health_check_deep_all_ok(monkeypatch):
    """
    GET /health/deep: すべてのコンポーネントが正常なケース
    """
    monkeypatch.setenv("GOOGLE_API_KEY", "DeepTestKey")

    mock_video_editor_module = MagicMock()
    mock_video_editor = MagicMock()
    mock_video_editor.ffmpeg.is_available.return_value = True
    mock_video_editor.ffmpeg.ffmpeg_path = "/usr/bin/ffmpeg"
    mock_video_editor.ffmpeg.use_gpu = True
    mock_video_editor_module.video_editor = mock_video_editor

    mock_usage = MagicMock()
    mock_usage.free = 30 * (1024 ** 3)
    mock_usage.total = 100 * (1024 ** 3)

    mock_whisper = MagicMock()
    mock_whisper.__version__ = "1.2.3"

    mock_coordinator = MagicMock()

    mock_template = MagicMock()
    mock_template.template_config.is_active = True
    mock_template.template_config.active_id = "test_template_001"

    modules_patch = {
        "video_editor_engine": mock_video_editor_module,
        "safe_io": MagicMock(VAULT_OUTPUTS_DIR="vault"),
        "faster_whisper": mock_whisper,
        "harness.adk_bridge": MagicMock(),
        "agents.pipeline_coordinator": mock_coordinator,
        "template_config": mock_template
    }

    with patch.dict(sys.modules, modules_patch):
        with patch("shutil.disk_usage", return_value=mock_usage):
            response = client.get("/health/deep")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "detailed"
            assert data["checks"]["whisper"]["available"] is True
            assert data["checks"]["whisper"]["version"] == "1.2.3"
            assert data["checks"]["pipeline"]["harness_available"] is True
            assert data["checks"]["pipeline"]["coordinator_available"] is True
            assert data["checks"]["template"]["active"] is True
            assert data["checks"]["template"]["template_id"] == "test_template_001"


def test_health_check_deep_missing_components():
    """
    GET /health/deep: 任意コンポーネントが未インストールの場合の検証
    """
    mock_video_editor_module = MagicMock()
    mock_video_editor = MagicMock()
    mock_video_editor.ffmpeg.is_available.return_value = True
    mock_video_editor_module.video_editor = mock_video_editor

    mock_usage = MagicMock()
    mock_usage.free = 30 * (1024 ** 3)
    mock_usage.total = 100 * (1024 ** 3)

    modules_patch = {
        "video_editor_engine": mock_video_editor_module,
        "safe_io": MagicMock(VAULT_OUTPUTS_DIR="vault"),
        "faster_whisper": None,
        "harness.adk_bridge": None,
        "agents.pipeline_coordinator": None,
        "template_config": None
    }

    with patch.dict(sys.modules, modules_patch):
        with patch("shutil.disk_usage", return_value=mock_usage):
            response = client.get("/health/deep")
            
            assert response.status_code == 200
            data = response.json()
            assert data["checks"]["whisper"]["available"] is False
            assert data["checks"]["pipeline"]["harness_available"] is False
            assert data["checks"]["pipeline"]["coordinator_available"] is False
            assert data["checks"]["template"]["active"] is False


def test_health_check_deep_exceptions_handling():
    """
    GET /health/deep: インポートされたコンポーネントから一般例外が発生した場合の検証
    """
    mock_video_editor_module = MagicMock()
    mock_video_editor = MagicMock()
    mock_video_editor.ffmpeg.is_available.return_value = True
    mock_video_editor_module.video_editor = mock_video_editor
    
    mock_usage = MagicMock()
    mock_usage.free = 30 * (1024 ** 3)
    mock_usage.total = 100 * (1024 ** 3)

    mock_harness_bridge = MagicMock()
    type(mock_harness_bridge).build_harness_pipeline = property(lambda self: (_ for _ in ()).throw(ValueError("Harness Error")))

    mock_coord_module = MagicMock()
    type(mock_coord_module).PipelineCoordinator = property(lambda self: (_ for _ in ()).throw(KeyError("Coordinator Error")))

    mock_temp_config = MagicMock()
    type(mock_temp_config).template_config = property(lambda self: (_ for _ in ()).throw(RuntimeError("Template Error")))

    modules_patch = {
        "video_editor_engine": mock_video_editor_module,
        "safe_io": MagicMock(VAULT_OUTPUTS_DIR="vault"),
        "faster_whisper": None,
        "harness.adk_bridge": mock_harness_bridge,
        "agents.pipeline_coordinator": mock_coord_module,
        "template_config": mock_temp_config
    }

    with patch.dict(sys.modules, modules_patch):
        with patch("shutil.disk_usage", return_value=mock_usage):
            response = client.get("/health/deep")
            
            assert response.status_code == 200
            data = response.json()
            assert data["checks"]["pipeline"]["harness_available"] is False
            assert data["checks"]["pipeline"]["coordinator_available"] is False
            assert data["checks"]["template"]["active"] is False


def test_health_check_deep_http_exceptions_pass_through():
    """
    GET /health/deep: 各コンポーネント呼び出し時の HTTPException が透過されることの検証
    """
    mock_video_editor_module = MagicMock()
    mock_video_editor = MagicMock()
    mock_video_editor.ffmpeg.is_available.return_value = True
    mock_video_editor_module.video_editor = mock_video_editor
    
    mock_usage = MagicMock()
    mock_usage.free = 30 * (1024 ** 3)
    mock_usage.total = 100 * (1024 ** 3)

    # 1. Harness 処理時に HTTPException が投げられるケース
    mock_harness_bridge = MagicMock()
    type(mock_harness_bridge).build_harness_pipeline = property(
        lambda self: (_ for _ in ()).throw(HTTPException(status_code=403, detail="Harness Forbidden"))
    )

    modules_patch = {
        "video_editor_engine": mock_video_editor_module,
        "safe_io": MagicMock(VAULT_OUTPUTS_DIR="vault"),
        "harness.adk_bridge": mock_harness_bridge,
    }

    with patch.dict(sys.modules, modules_patch):
        with patch("shutil.disk_usage", return_value=mock_usage):
            response = client.get("/health/deep")
            assert response.status_code == 403
            assert response.json()["detail"] == "Harness Forbidden"

    # 2. PipelineCoordinator 処理時に HTTPException が投げられるケース
    mock_coord_module = MagicMock()
    type(mock_coord_module).PipelineCoordinator = property(
        lambda self: (_ for _ in ()).throw(HTTPException(status_code=401, detail="Coordinator Unauthorized"))
    )

    modules_patch = {
        "video_editor_engine": mock_video_editor_module,
        "safe_io": MagicMock(VAULT_OUTPUTS_DIR="vault"),
        "agents.pipeline_coordinator": mock_coord_module,
    }

    with patch.dict(sys.modules, modules_patch):
        with patch("shutil.disk_usage", return_value=mock_usage):
            response = client.get("/health/deep")
            assert response.status_code == 401
            assert response.json()["detail"] == "Coordinator Unauthorized"

    # 3. template_config 処理時に HTTPException が投げられるケース
    mock_temp_config = MagicMock()
    type(mock_temp_config).template_config = property(
        lambda self: (_ for _ in ()).throw(HTTPException(status_code=400, detail="Template Bad Request"))
    )

    modules_patch = {
        "video_editor_engine": mock_video_editor_module,
        "safe_io": MagicMock(VAULT_OUTPUTS_DIR="vault"),
        "template_config": mock_temp_config,
    }

    with patch.dict(sys.modules, modules_patch):
        with patch("shutil.disk_usage", return_value=mock_usage):
            response = client.get("/health/deep")
            assert response.status_code == 400
            assert response.json()["detail"] == "Template Bad Request"


# ==============================================================
# サムネイル品質検証ヘルスチェックの追加テスト
# ==============================================================

def test_health_check_deep_with_thumbnail_ok(monkeypatch):
    """
    GET /health/deep: サムネイルエンジンが正常にロードされ、品質検証もパスするケース
    """
    monkeypatch.setenv("GOOGLE_API_KEY", "DeepTestKey")

    mock_video_editor_module = MagicMock()
    mock_video_editor = MagicMock()
    mock_video_editor.ffmpeg.is_available.return_value = True
    mock_video_editor.ffmpeg.ffmpeg_path = "/usr/bin/ffmpeg"
    mock_video_editor.ffmpeg.use_gpu = True
    mock_video_editor_module.video_editor = mock_video_editor

    mock_usage = MagicMock()
    mock_usage.free = 30 * (1024 ** 3)
    mock_usage.total = 100 * (1024 ** 3)

    # 実際の ThumbnailResolver を動作させるためのモック
    mock_resolver_instance = MagicMock()
    mock_resolver_instance.generate_thumbnail.side_effect = lambda path, width, height, text: Path(path).touch()
    mock_resolver_instance.validate_thumbnail.return_value = {
        "width": 1280,
        "height": 720,
        "size_bytes": 1024,
    }
    
    mock_council_graph = MagicMock()
    mock_council_graph.ThumbnailResolver.return_value = mock_resolver_instance

    mock_stage_agent = MagicMock()

    modules_patch = {
        "video_editor_engine": mock_video_editor_module,
        "safe_io": MagicMock(VAULT_OUTPUTS_DIR="vault"),
        "faster_whisper": None,
        "harness.adk_bridge": None,
        "agents.pipeline_coordinator": None,
        "template_config": None,
        "agents.council_graph": mock_council_graph,
        "agents.stage_bound_agent": mock_stage_agent,
    }

    with patch.dict(sys.modules, modules_patch):
        with patch("shutil.disk_usage", return_value=mock_usage):
            response = client.get("/health/deep")
            assert response.status_code == 200
            data = response.json()
            thumb_check = data["checks"]["thumbnail"]
            assert thumb_check["available"] is True
            assert thumb_check["stage_bound_agent_integration"] is True
            assert thumb_check["validation"]["passed"] is True
            assert thumb_check["validation"]["details"]["width"] == 1280
            assert thumb_check["validation"]["details"]["height"] == 720


def test_health_check_deep_with_thumbnail_failure_validation(monkeypatch):
    """
    GET /health/deep: サムネイルエンジンの品質検証が失敗するケース
    """
    monkeypatch.setenv("GOOGLE_API_KEY", "DeepTestKey")

    mock_video_editor_module = MagicMock()
    mock_video_editor = MagicMock()
    mock_video_editor.ffmpeg.is_available.return_value = True
    mock_video_editor_module.video_editor = mock_video_editor

    mock_usage = MagicMock()
    mock_usage.free = 30 * (1024 ** 3)
    mock_usage.total = 100 * (1024 ** 3)

    mock_resolver_instance = MagicMock()
    mock_resolver_instance.generate_thumbnail.side_effect = lambda path, width, height, text: Path(path).touch()
    mock_resolver_instance.validate_thumbnail.side_effect = ValueError("Aspect ratio must be 16:9")
    
    mock_council_graph = MagicMock()
    mock_council_graph.ThumbnailResolver.return_value = mock_resolver_instance

    mock_stage_agent = MagicMock()

    # TDR登録のモック
    mock_tdr_store = MagicMock()

    modules_patch = {
        "video_editor_engine": mock_video_editor_module,
        "safe_io": MagicMock(VAULT_OUTPUTS_DIR="vault"),
        "faster_whisper": None,
        "harness.adk_bridge": None,
        "agents.pipeline_coordinator": None,
        "template_config": None,
        "agents.council_graph": mock_council_graph,
        "agents.stage_bound_agent": mock_stage_agent,
        "agents.memory.technical_debt": mock_tdr_store,
    }

    with patch.dict(sys.modules, modules_patch):
        with patch("shutil.disk_usage", return_value=mock_usage):
            response = client.get("/health/deep")
            assert response.status_code == 200
            data = response.json()
            thumb_check = data["checks"]["thumbnail"]
            assert thumb_check["available"] is True
            assert thumb_check["validation"]["passed"] is False
            assert "Aspect ratio must be 16:9" in thumb_check["validation"]["error"]
            # TDRへの登録を確認
            mock_tdr_store.TechnicalDebtStore().register_debt.assert_called_once()


def test_health_check_deep_with_thumbnail_missing_components(monkeypatch):
    """
    GET /health/deep: サムネイル品質検証に必要なモジュールがインポートできないケース
    """
    monkeypatch.setenv("GOOGLE_API_KEY", "DeepTestKey")

    mock_video_editor_module = MagicMock()
    mock_video_editor = MagicMock()
    mock_video_editor.ffmpeg.is_available.return_value = True
    mock_video_editor_module.video_editor = mock_video_editor

    mock_usage = MagicMock()
    mock_usage.free = 30 * (1024 ** 3)
    mock_usage.total = 100 * (1024 ** 3)

    modules_patch = {
        "video_editor_engine": mock_video_editor_module,
        "safe_io": MagicMock(VAULT_OUTPUTS_DIR="vault"),
        "faster_whisper": None,
        "harness.adk_bridge": None,
        "agents.pipeline_coordinator": None,
        "template_config": None,
        "agents.council_graph": None, # ロード不可
        "agents.stage_bound_agent": None, # ロード不可
    }

    with patch.dict(sys.modules, modules_patch):
        with patch("shutil.disk_usage", return_value=mock_usage):
            response = client.get("/health/deep")
            assert response.status_code == 200
            data = response.json()
            thumb_check = data["checks"]["thumbnail"]
            assert thumb_check["available"] is False
            assert thumb_check["stage_bound_agent_integration"] is False


def test_health_check_simple_with_thumbnail_degraded(monkeypatch):
    """
    GET /health: サムネイルエンジンの品質検証失敗で degraded になるケース
    """
    monkeypatch.setenv("GOOGLE_API_KEY", "AIzaSyTestKey123456")

    mock_video_editor_module = MagicMock()
    mock_video_editor = MagicMock()
    mock_video_editor.ffmpeg.is_available.return_value = True
    mock_video_editor_module.video_editor = mock_video_editor

    mock_usage = MagicMock()
    mock_usage.free = 20 * (1024 ** 3)
    mock_usage.total = 100 * (1024 ** 3)

    mock_resolver_instance = MagicMock()
    mock_resolver_instance.generate_thumbnail.side_effect = lambda path, width, height, text: Path(path).touch()
    # 検証失敗
    mock_resolver_instance.validate_thumbnail.side_effect = ValueError("Resolution check failed")
    
    mock_council_graph = MagicMock()
    mock_council_graph.ThumbnailResolver.return_value = mock_resolver_instance

    mock_stage_agent = MagicMock()

    modules_patch = {
        "video_editor_engine": mock_video_editor_module,
        "safe_io": MagicMock(VAULT_OUTPUTS_DIR="vault"),
        "agents.council_graph": mock_council_graph,
        "agents.stage_bound_agent": mock_stage_agent,
    }

    with patch.dict(sys.modules, modules_patch):
        with patch("shutil.disk_usage", return_value=mock_usage):
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            # サムネイル品質検証がパスしていないため status が degraded になること
            assert data["status"] == "degraded"
            assert data["checks"]["thumbnail"]["validation"]["passed"] is False


def test_register_health_debt_exception(monkeypatch):
    """
    _register_health_debt で例外が発生した際にロガーがエラーを出力することを検証
    """
    mock_tdr_store = MagicMock()
    mock_tdr_store.TechnicalDebtStore.side_effect = RuntimeError("TDR Init Error")

    modules_patch = {
        "agents.memory.technical_debt": mock_tdr_store,
    }

    with patch("routers.health.logger.error") as mock_log_error:
        with patch.dict(sys.modules, modules_patch):
            mock_video_editor_module = MagicMock()
            mock_video_editor = MagicMock()
            mock_video_editor.ffmpeg.is_available.return_value = True
            mock_video_editor_module.video_editor = mock_video_editor

            mock_usage = MagicMock()
            mock_usage.free = 20 * (1024 ** 3)
            mock_usage.total = 100 * (1024 ** 3)

            mock_resolver_instance = MagicMock()
            mock_resolver_instance.generate_thumbnail.side_effect = lambda path, width, height, text: Path(path).touch()
            mock_resolver_instance.validate_thumbnail.side_effect = ValueError("Thumbnail Error")
            
            mock_council_graph = MagicMock()
            mock_council_graph.ThumbnailResolver.return_value = mock_resolver_instance

            inner_patch = {
                "video_editor_engine": mock_video_editor_module,
                "safe_io": MagicMock(VAULT_OUTPUTS_DIR="vault"),
                "agents.council_graph": mock_council_graph,
                "agents.stage_bound_agent": MagicMock(),
            }

            with patch.dict(sys.modules, inner_patch):
                with patch("shutil.disk_usage", return_value=mock_usage):
                    response = client.get("/health")
                    assert response.status_code == 200
                    mock_log_error.assert_called()
                    args, kwargs = mock_log_error.call_args
                    assert "Failed to register TDR debt" in args[0]


def test_health_check_general_exception(monkeypatch):
    """
    GET /health で予期しない例外が発生した際、500エラーが返り、TDRに登録されることを検証
    """
    mock_tdr_store = MagicMock()
    
    modules_patch = {
        "agents.memory.technical_debt": mock_tdr_store,
    }

    with patch.dict(sys.modules, modules_patch):
        with patch("routers.health._check_ffmpeg", side_effect=RuntimeError("Unexpected Fatal Error")):
            response = client.get("/health")
            assert response.status_code == 500
            assert "Health check failed: Unexpected Fatal Error" in response.json()["detail"]
            mock_tdr_store.TechnicalDebtStore().register_debt.assert_called_once()


def test_health_check_deep_general_exception(monkeypatch):
    """
    GET /health/deep で予期しない例外が発生した際、500エラーが返り、TDRに登録されることを検証
    """
    mock_tdr_store = MagicMock()
    
    modules_patch = {
        "agents.memory.technical_debt": mock_tdr_store,
    }

    with patch.dict(sys.modules, modules_patch):
        with patch("routers.health._check_ffmpeg", side_effect=RuntimeError("Unexpected Deep Fatal Error")):
            response = client.get("/health/deep")
            assert response.status_code == 500
            assert "Deep health check failed: Unexpected Deep Fatal Error" in response.json()["detail"]
            mock_tdr_store.TechnicalDebtStore().register_debt.assert_called_once()


def test_thumbnail_engine_http_exception_pass_through():
    """
    _check_thumbnail_engine(): HTTPException が発生した場合はそのまま透過されることの検証
    """
    mock_broken_resolver = MagicMock()
    mock_broken_resolver.generate_thumbnail.side_effect = HTTPException(status_code=400, detail="Thumbnail HTTP Error")
    
    mock_council_graph = MagicMock()
    mock_council_graph.ThumbnailResolver.return_value = mock_broken_resolver

    mock_video_editor_module = MagicMock()
    mock_video_editor_module.video_editor.ffmpeg.is_available.return_value = True

    modules_patch = {
        "video_editor_engine": mock_video_editor_module,
        "safe_io": MagicMock(VAULT_OUTPUTS_DIR="vault"),
        "agents.council_graph": mock_council_graph,
        "agents.stage_bound_agent": MagicMock(),
    }

    with patch.dict(sys.modules, modules_patch):
        response = client.get("/health")
        assert response.status_code == 400
        assert response.json()["detail"] == "Thumbnail HTTP Error"


def test_deep_health_check_unexpected_import_exception():
    """
    GET /health/deep: インポート時に ImportError 以外の予期しない例外が発生した場合のキャッチ/TDR/200検証
    """
    mock_video_editor_module = MagicMock()
    mock_video_editor_module.video_editor.ffmpeg.is_available.return_value = True

    mock_template = MagicMock()
    type(mock_template).template_config = property(
        lambda self: (_ for _ in ()).throw(SystemError("Unexpected System Error in Import"))
    )

    mock_tdr_store = MagicMock()

    modules_patch = {
        "video_editor_engine": mock_video_editor_module,
        "safe_io": MagicMock(VAULT_OUTPUTS_DIR="vault"),
        "template_config": mock_template,
        "agents.memory.technical_debt": mock_tdr_store,
    }

    with patch.dict(sys.modules, modules_patch):
        response = client.get("/health/deep")
        assert response.status_code == 200
        data = response.json()
        assert data["checks"]["template"]["active"] is False
        mock_tdr_store.TechnicalDebtStore().register_debt.assert_called_once()


def test_health_check_ffmpeg_specific_exceptions():
    """
    _check_ffmpeg() が ImportError や ValueError, TypeError などの個別の例外を
    正しくキャッチして適切な error フィールドを返すことを検証する
    """
    # 1. ImportError の場合
    with patch.dict(sys.modules, {"video_editor_engine": None}):
        mock_broken = MagicMock()
        type(mock_broken).video_editor = property(lambda self: (_ for _ in ()).throw(ImportError("Cannot import video_editor_engine")))
        with patch.dict(sys.modules, {"video_editor_engine": mock_broken}):
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["checks"]["ffmpeg"]["available"] is False
            assert "Import error" in data["checks"]["ffmpeg"]["error"]

    # 2. ValueError の場合
    with patch.dict(sys.modules, {"video_editor_engine": None}):
        mock_broken = MagicMock()
        type(mock_broken).video_editor = property(lambda self: (_ for _ in ()).throw(ValueError("Invalid parameters for video_editor")))
        with patch.dict(sys.modules, {"video_editor_engine": mock_broken}):
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["checks"]["ffmpeg"]["available"] is False
            assert "Engine execution error" in data["checks"]["ffmpeg"]["error"]
