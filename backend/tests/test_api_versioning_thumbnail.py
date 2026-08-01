try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _wp
except ImportError:
    from path_resolver import writable_path as _wp

import os
import sys
import json
import pytest
import asyncio
from pathlib import Path
from PIL import Image

# backend ディレクトリをパスに追加
_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)


# 遅延インポート用のグローバル宣言
generate_api_thumbnail = None
validate_api_thumbnail = None
resolve_api_thumbnail_task = None
v1_router = None

def setup_module(module):
    global generate_api_thumbnail, validate_api_thumbnail, resolve_api_thumbnail_task, v1_router
    import sys
    from unittest.mock import MagicMock
    
    # sys.modules 内で google 関連が Mock/MagicMock になっているものを特定し退避
    modules_to_clear = []
    for name, mod in list(sys.modules.items()):
        if name.startswith("google"):
            # MagicMock かどうか、またはオブジェクトの型名に 'Mock' が含まれるか確認
            if isinstance(mod, MagicMock) or "Mock" in type(mod).__name__:
                modules_to_clear.append(name)
                
    saved_modules = {}
    for name in modules_to_clear:
        saved_modules[name] = sys.modules.pop(name)
        
    try:
        import api_versioning
        generate_api_thumbnail = api_versioning.generate_api_thumbnail
        validate_api_thumbnail = api_versioning.validate_api_thumbnail
        resolve_api_thumbnail_task = api_versioning.resolve_api_thumbnail_task
        v1_router = api_versioning.v1_router
    finally:
        # 退避したモックを復元
        for name, mod in saved_modules.items():
            sys.modules[name] = mod

from agents.stage_bound_agent import StageBoundAgent

@pytest.fixture
def temp_dir(tmp_path):
    d = tmp_path / "thumbnails"
    d.mkdir(parents=True, exist_ok=True)
    return d

def test_thumbnail_generation_and_validation_success(temp_dir):
    """品質基準を満たすサムネイルが正常に生成され、検証をパスすること"""
    output_path = temp_dir / "valid_thumb.png"
    
    # 1. 画像の生成
    generate_api_thumbnail(output_path, width=1280, height=720, text="Valid UI")
    assert output_path.exists()
    
    # 2. 生成された画像の検証
    result = validate_api_thumbnail(output_path)
    assert result["width"] == 1280
    assert result["height"] == 720
    assert result["size_bytes"] < 4 * 1024 * 1024
    
    # 3. Pillowで正常ロード可能か
    with Image.open(output_path) as img:
        img.load()
        assert img.size == (1280, 720)

def test_thumbnail_validation_fails_resolution(temp_dir):
    """解像度不足の画像が検証で拒絶されること"""
    output_path = temp_dir / "low_res.png"
    
    # 1280x720 未満 (例: 800x450)
    generate_api_thumbnail(output_path, width=800, height=450)
    
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        validate_api_thumbnail(output_path)

def test_thumbnail_validation_fails_aspect_ratio(temp_dir):
    """アスペクト比が16:9でない画像が検証で拒絶されること"""
    output_path = temp_dir / "bad_aspect.png"
    
    # 4:3 アスペクト比 (1280x960)
    generate_api_thumbnail(output_path, width=1280, height=960)
    
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        validate_api_thumbnail(output_path)

def test_thumbnail_validation_fails_corrupted(temp_dir):
    """破損した画像ファイルが検証で拒絶されること"""
    output_path = temp_dir / "corrupted.png"
    
    # 不完全なファイル
    output_path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 20)
    
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        validate_api_thumbnail(output_path)

@pytest.mark.asyncio
async def test_stage_bound_agent_integration(temp_dir, monkeypatch):
    """StageBoundAgent にタスク登録され、結果がDB保存されること"""
    # resolve_api_thumbnail_task が temp_thumbnails を書き出す先をテスト用にモックする
    original_resolve = resolve_api_thumbnail_task
    
    async def mock_resolve_task(task_id: str) -> str:
        # 出力先を temp_dir に向ける
        output_path = temp_dir / f"api_versioning_{task_id}.png"
        generate_api_thumbnail(output_path, width=1280, height=720, text=f"Test {task_id}")
        res = validate_api_thumbnail(output_path)
        return json.dumps(res)
        
    monkeypatch.setattr("api_versioning.resolve_api_thumbnail_task", mock_resolve_task)
    
    # インメモリ SQLite DB
    agent = StageBoundAgent(stage_name="thumbnail", db_path=":memory:", poll_interval=0.01)
    
    task_id = "task_stage_bound_test"
    await agent.register_task(task_id, initial_status="READY", max_retries=1)
    
    # ポーリング開始
    await agent.start(resolve_api_thumbnail_task)
    
    # 完了を待つ (タイムアウト 5 秒)
    for _ in range(50):
        status = await agent.get_task_status(task_id)
        if status in ("COMPLETED", "FAILED"):
            break
        await asyncio.sleep(0.1)
        
    status = await agent.get_task_status(task_id)
    assert status == "COMPLETED"
    
    # DBに保存された結果を検証
    conn = agent._get_conn()
    cursor = conn.execute("SELECT result, error, retry_count FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    assert row is not None
    result_json = row[0]
    error_msg = row[1]
    retry_cnt = row[2]
    
    assert error_msg is None
    assert retry_cnt == 0
    
    result_data = json.loads(result_json)
    assert "width" in result_data
    assert result_data["width"] == 1280
    assert result_data["height"] == 720
    
    await agent.stop()

@pytest.mark.asyncio
async def test_stage_bound_agent_retry_and_fail(temp_dir, monkeypatch):
    """タスク失敗時に自動リトライされ、最大リトライ数超過で FAILED になること"""
    # 意図的に例外を投げる process_func
    call_count = 0
    async def mock_process_fail(task_id: str):
        nonlocal call_count
        call_count += 1
        raise ValueError("Simulated processing error")
        
    agent = StageBoundAgent(stage_name="thumbnail", db_path=":memory:", poll_interval=0.01)
    
    task_id = "task_retry_test"
    await agent.register_task(task_id, initial_status="READY", max_retries=2)
    
    await agent.start(mock_process_fail)
    
    # 完了を待つ
    for _ in range(50):
        status = await agent.get_task_status(task_id)
        if status == "FAILED":
            break
        await asyncio.sleep(0.1)
        
    status = await agent.get_task_status(task_id)
    assert status == "FAILED"
    
    # 試行回数の検証：初回（1回）＋リトライ（2回）＝ 計3回呼び出されるはず
    assert call_count == 3
    
    # DBの状態確認
    conn = agent._get_conn()
    cursor = conn.execute("SELECT retry_count, error FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    assert row[0] == 2
    assert "Simulated processing error" in row[1]
    
    await agent.stop()


# FastAPI 関連のインポート追加
from fastapi import FastAPI
from fastapi.testclient import TestClient

import pathlib

@pytest.fixture
def api_client():
    app = FastAPI()
    app.include_router(v1_router)
    return TestClient(app)

@pytest.fixture
def clean_thumbnail_file():
    created_files = []
    def register(path):
        created_files.append(Path(path))
    yield register
    for p in created_files:
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass

def test_get_api_version_success(api_client):
    """GET /api/v1/version が正常メタデータを返すこと"""
    response = api_client.get("/api/v1/version")
    assert response.status_code == 200
    data = response.json()
    assert data["api_version"] == "v1"
    assert data["codename"] == "Trinity"

def test_get_api_version_exception(api_client, monkeypatch):
    """get_api_version が例外発生時にTDR登録を行い500エラーを返すこと"""
    def mock_metadata():
        raise ValueError("Simulated version error")
    
    monkeypatch.setattr("api_versioning._get_version_metadata", mock_metadata)
    
    from agents.memory.technical_debt import TechnicalDebtStore
    registered = []
    def mock_register_debt(*args, **kwargs):
        registered.append((args, kwargs))
        
    monkeypatch.setattr(TechnicalDebtStore, "register_debt", mock_register_debt)
    
    response = api_client.get("/api/v1/version")
    assert response.status_code == 500
    assert "Simulated version error" in response.json()["detail"]
    assert len(registered) == 1
    assert registered[0][1]["category"] == "CRITICAL_ROUTER"
    assert registered[0][1]["line_number"] == 134

def test_generate_v1_thumbnail_success(api_client, clean_thumbnail_file):
    """POST /api/v1/thumbnail/generate の正常系"""
    task_id = "test_endpoint_success"
    payload = {
        "task_id": task_id,
        "text": "Hello Endpoint",
        "width": 1280,
        "height": 720
    }
    
    expected_path = _wp("backend/temp_thumbnails") / f"api_versioning_{task_id}.png"
    clean_thumbnail_file(expected_path)
    
    response = api_client.post("/api/v1/thumbnail/generate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["result"]["width"] == 1280
    assert data["result"]["height"] == 720

def test_generate_v1_thumbnail_exception(api_client, monkeypatch):
    """POST /api/v1/thumbnail/generate が例外発生時にTDR登録を行い500エラーを返すこと"""
    def mock_generate(*args, **kwargs):
        raise ValueError("Simulated generate error")
        
    monkeypatch.setattr("api_versioning.generate_api_thumbnail", mock_generate)
    
    from agents.memory.technical_debt import TechnicalDebtStore
    registered = []
    def mock_register_debt(*args, **kwargs):
        registered.append((args, kwargs))
        
    monkeypatch.setattr(TechnicalDebtStore, "register_debt", mock_register_debt)
    
    payload = {
        "task_id": "test_endpoint_fail",
        "text": "Hello Endpoint Error",
        "width": 1280,
        "height": 720
    }
    
    response = api_client.post("/api/v1/thumbnail/generate", json=payload)
    assert response.status_code == 500
    assert "Simulated generate error" in response.json()["detail"]
    assert len(registered) == 1
    assert registered[0][1]["category"] == "CRITICAL_ROUTER"
    assert registered[0][1]["line_number"] == 325

def test_register_v1_routes_exception(monkeypatch):
    """register_v1_routes が例外発生時にTDR登録を行い例外を再レイズすること"""
    from fastapi import APIRouter
    mock_router = APIRouter()
    
    def mock_include_router(*args, **kwargs):
        raise RuntimeError("Simulated routing crash")
        
    monkeypatch.setattr(mock_router, "include_router", mock_include_router)
    
    from agents.memory.technical_debt import TechnicalDebtStore
    registered = []
    def mock_register_debt(*args, **kwargs):
        registered.append((args, kwargs))
        
    monkeypatch.setattr(TechnicalDebtStore, "register_debt", mock_register_debt)
    
    from api_versioning import register_v1_routes
    with pytest.raises(RuntimeError, match="Simulated routing crash"):
        register_v1_routes(mock_router)
        
    assert len(registered) == 1
    assert registered[0][1]["category"] == "CRITICAL_ROUTER"
    assert registered[0][1]["line_number"] == 87

def test_generate_api_thumbnail_invalid_size(temp_dir):
    """width/height が無効な値の場合に ValueError を投げること"""
    output_path = temp_dir / "invalid_size.png"
    
    with pytest.raises(ValueError, match="Width and height must be integers"):
        generate_api_thumbnail(output_path, width="not_an_int", height=720)
        
    with pytest.raises(ValueError, match="Width and height must be integers"):
        generate_api_thumbnail(output_path, width=1280, height=None)

def test_generate_api_thumbnail_negative_size(temp_dir):
    """width/height が 0 以下の値の場合に ValueError を投げること"""
    output_path = temp_dir / "negative_size.png"
    
    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        generate_api_thumbnail(output_path, width=0, height=720)
        
    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        generate_api_thumbnail(output_path, width=1280, height=-10)

def test_generate_api_thumbnail_os_error_and_unlink_fail(temp_dir, monkeypatch):
    """rename 時に OSError が発生し、かつ temp_path.unlink でも OSError が発生した場合の挙動"""
    output_path = temp_dir / "os_error.png"
    
    import pathlib
    original_rename = pathlib.Path.rename
    original_unlink = pathlib.Path.unlink
    
    # OSに応じたPath具象クラスを取得
    path_cls = type(pathlib.Path())
    
    def mock_rename(self, *args, **kwargs):
        if "os_error" in str(self) or "tmp" in str(self):
            raise OSError("Simulated rename error")
        return original_rename(self, *args, **kwargs)
        
    def mock_unlink(self, *args, **kwargs):
        if "os_error" in str(self) or "tmp" in str(self):
            raise OSError("Simulated unlink error")
        return original_unlink(self, *args, **kwargs)
        
    monkeypatch.setattr(path_cls, "rename", mock_rename)
    monkeypatch.setattr(path_cls, "unlink", mock_unlink)
    
    with pytest.raises(OSError, match="Simulated rename error"):
        generate_api_thumbnail(output_path, width=1280, height=720)

def test_validate_api_thumbnail_not_found():
    """存在しないファイルパスを検証したときに FileNotFoundError を投げること"""
    with pytest.raises(FileNotFoundError, match="Thumbnail file not found"):
        validate_api_thumbnail("non_existent_file.png")

def test_validate_api_thumbnail_file_too_large(temp_dir, monkeypatch):
    """ファイルサイズが 4MB 制限を超える場合に ValueError を投げること"""
    output_path = temp_dir / "too_large.png"
    output_path.write_text("dummy")
    
    import pathlib
    original_stat = pathlib.Path.stat
    path_cls = type(pathlib.Path())
    
    class MockStat:
        def __init__(self, size):
            self.st_size = size
            
    def mock_stat(self, *args, **kwargs):
        if "too_large.png" in str(self):
            return MockStat(4 * 1024 * 1024 + 1)
        return original_stat(self, *args, **kwargs)
        
    monkeypatch.setattr(path_cls, "stat", mock_stat)
    
    with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
        validate_api_thumbnail(output_path)

def test_validate_api_thumbnail_load_fails(temp_dir, monkeypatch):
    """画像のピクセルロード（img.load）時に例外が発生した場合に ValueError を投げること"""
    output_path = temp_dir / "load_fail.png"
    generate_api_thumbnail(output_path, width=1280, height=720)
    
    from PIL import Image
    
    def mock_load(self, *args, **kwargs):
        raise OSError("Simulated pixel load failure")
        
    monkeypatch.setattr(Image.Image, "load", mock_load)
    
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        validate_api_thumbnail(output_path)

def test_register_v1_routes_http_exception(monkeypatch):
    """register_v1_routes で HTTPException が発生した場合、TDR登録せずにそのまま raise すること"""
    from fastapi import APIRouter, HTTPException
    mock_router = APIRouter()
    
    def mock_include_router(*args, **kwargs):
        raise HTTPException(status_code=400, detail="Simulated HTTP error")
        
    monkeypatch.setattr(mock_router, "include_router", mock_include_router)
    
    from api_versioning import register_v1_routes
    with pytest.raises(HTTPException) as exc_info:
        register_v1_routes(mock_router)
    assert exc_info.value.status_code == 400

def test_register_v1_routes_tdr_registration_fail(monkeypatch):
    """register_v1_routes で例外発生時、TDR登録が失敗しても、元の例外が再レイズされること"""
    from fastapi import APIRouter
    mock_router = APIRouter()
    
    def mock_include_router(*args, **kwargs):
        raise RuntimeError("Original routing error")
        
    monkeypatch.setattr(mock_router, "include_router", mock_include_router)
    
    from agents.memory.technical_debt import TechnicalDebtStore
    def mock_register_debt(*args, **kwargs):
        raise ValueError("TDR write failed")
        
    monkeypatch.setattr(TechnicalDebtStore, "register_debt", mock_register_debt)
    
    from api_versioning import register_v1_routes
    with pytest.raises(RuntimeError, match="Original routing error"):
        register_v1_routes(mock_router)

def test_get_api_version_http_exception(api_client, monkeypatch):
    """get_api_version で HTTPException が発生した場合、TDR登録せずにそのまま raise すること"""
    from fastapi import HTTPException
    def mock_metadata():
        raise HTTPException(status_code=403, detail="Forbidden version")
        
    monkeypatch.setattr("api_versioning._get_version_metadata", mock_metadata)
    
    response = api_client.get("/api/v1/version")
    assert response.status_code == 403
    assert "Forbidden version" in response.json()["detail"]

def test_get_api_version_tdr_registration_fail(api_client, monkeypatch):
    """get_api_version で例外発生時、TDR登録が失敗しても、500エラーが返されること"""
    def mock_metadata():
        raise ValueError("Original version error")
        
    monkeypatch.setattr("api_versioning._get_version_metadata", mock_metadata)
    
    from agents.memory.technical_debt import TechnicalDebtStore
    def mock_register_debt(*args, **kwargs):
        raise ValueError("TDR write failed")
        
    monkeypatch.setattr(TechnicalDebtStore, "register_debt", mock_register_debt)
    
    response = api_client.get("/api/v1/version")
    assert response.status_code == 500
    assert "Original version error" in response.json()["detail"]

def test_generate_v1_thumbnail_http_exception(api_client, monkeypatch):
    """generate_v1_thumbnail で HTTPException が発生した場合、TDR登録せずにそのまま raise すること"""
    from fastapi import HTTPException
    def mock_generate(*args, **kwargs):
        raise HTTPException(status_code=400, detail="Invalid thumbnail configuration")
        
    monkeypatch.setattr("api_versioning.generate_api_thumbnail", mock_generate)
    
    payload = {
        "task_id": "test_http_fail",
        "text": "HTTP Fail",
        "width": 1280,
        "height": 720
    }
    
    response = api_client.post("/api/v1/thumbnail/generate", json=payload)
    assert response.status_code == 400
    assert "Invalid thumbnail configuration" in response.json()["detail"]

def test_generate_v1_thumbnail_tdr_registration_fail(api_client, monkeypatch):
    """generate_v1_thumbnail で例外発生時、TDR登録が失敗しても、500エラーが返されること"""
    def mock_generate(*args, **kwargs):
        raise ValueError("Original generate error")
        
    monkeypatch.setattr("api_versioning.generate_api_thumbnail", mock_generate)
    
    from agents.memory.technical_debt import TechnicalDebtStore
    def mock_register_debt(*args, **kwargs):
        raise ValueError("TDR write failed")
        
    monkeypatch.setattr(TechnicalDebtStore, "register_debt", mock_register_debt)
    
    payload = {
        "task_id": "test_tdr_fail",
        "text": "TDR Fail",
        "width": 1280,
        "height": 720
    }
    
    response = api_client.post("/api/v1/thumbnail/generate", json=payload)
    assert response.status_code == 500
    assert "Original generate error" in response.json()["detail"]


def test_generate_api_thumbnail_invalid_text_type(temp_dir):
    """text が文字列でない場合に TypeError を投げること"""
    output_path = temp_dir / "invalid_text_type.png"
    with pytest.raises(TypeError, match="Text must be a string"):
        generate_api_thumbnail(output_path, text=123)


def test_generate_api_thumbnail_empty_text(temp_dir):
    """text が空文字または空白のみの場合に ValueError を投げること"""
    output_path = temp_dir / "empty_text.png"
    with pytest.raises(ValueError, match="Text must not be empty or whitespace only"):
        generate_api_thumbnail(output_path, text="")
    with pytest.raises(ValueError, match="Text must not be empty or whitespace only"):
        generate_api_thumbnail(output_path, text="   ")


def test_generate_api_thumbnail_too_long_text(temp_dir):
    """text が 100 文字を超える場合に ValueError を投げること"""
    output_path = temp_dir / "too_long_text.png"
    long_text = "a" * 101
    with pytest.raises(ValueError, match="Text length must not exceed 100 characters"):
        generate_api_thumbnail(output_path, text=long_text)

def test_template_config_injection_failure_coverage(monkeypatch, caplog):
    """api_versioning.py のモジュール初期化時 (L22-32) に template_config への
    定数注入が失敗した場合の例外ハンドリング (L31-32) を検証する。
    """
    import sys
    import importlib
    import logging
    
    class MockBadTemplateConfig:
        def __setattr__(self, name, value):
            raise RuntimeError("Simulated template_config injection failure")
            
    original_modules = sys.modules.copy()
    
    try:
        mock_config = MockBadTemplateConfig()
        sys.modules["template_config"] = mock_config
        
        with caplog.at_level(logging.ERROR, logger="api_versioning"):
            import api_versioning
            importlib.reload(api_versioning)
            
        assert any("Failed to inject template constants to template_config" in r.message for r in caplog.records)
    finally:
        sys.modules.clear()
        sys.modules.update(original_modules)
        
        import api_versioning
        importlib.reload(api_versioning)



def test_template_injection_exception(monkeypatch):
    """template_configインポート失敗時に例外をキャッチしてログ出力すること"""
    import builtins
    import importlib
    import api_versioning

    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "template_config":
            raise ImportError("Simulated import error")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)

    # リロードを実行して例外ルートを通過させる
    importlib.reload(api_versioning)
