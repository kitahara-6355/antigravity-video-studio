import sys
import os
import json
import sqlite3
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

# backend ディレクトリをパスに追加
_backend_dir = str(Path(__file__).resolve().parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from main import app
from PIL import Image

client = TestClient(app)

def test_smartcut_thumbnail_generation_success(tmp_path):
    """正常系: /api/smartcut/thumbnail エンドポイントを呼び出し、画像が品質基準を満たすことを確認"""
    # 実際のエンドポイント呼び出し
    response = client.post(
        "/api/smartcut/thumbnail",
        json={
            "session_id": "test_session_smartcut",
            "task_id": "test_smartcut_task_success",
            "width": 1280,
            "height": 720,
            "text": "Integrated SmartCut Thumbnail Test"
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["status"] == "COMPLETED"
    
    # レスポンス内の検証データを確認
    thumb_info = data["thumbnail"]
    assert thumb_info["width"] == 1280
    assert thumb_info["height"] == 720
    assert thumb_info["size_bytes"] < 4 * 1024 * 1024
    
    # 物理ファイルが存在し、破損していないか確認
    output_path = Path("backend/temp_thumbnails/test_smartcut_task_success.png")
    if not output_path.exists():
        output_path = Path("temp_thumbnails/test_smartcut_task_success.png")
        
    assert output_path.exists()
    
    # Pillowによる破損ロード検証とアスペクト比検証
    with Image.open(output_path) as img:
        img.verify()
        w, h = img.size
        assert w >= 1280
        assert h >= 720
        # アスペクト比 16:9
        assert abs(w / h - 16 / 9) < 0.01
        
    # ファイルサイズが 4MB 未満
    assert output_path.stat().st_size < 4 * 1024 * 1024
    
    # DBに結果が正しく保存されているか確認
    db_path = "backend/temp/smartcut_stage.db"
    if not os.path.exists(db_path):
        db_path = "temp/smartcut_stage.db"
        
    assert os.path.exists(db_path)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("SELECT status, result FROM tasks WHERE id = ?", ("test_smartcut_task_success",))
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    assert row[0] == "COMPLETED"
    result_data = json.loads(row[1])
    assert result_data["width"] == 1280

def test_smartcut_thumbnail_validation_failure():
    """異常系: 解像度不足による Pydantic バリデーションエラー"""
    response = client.post(
        "/api/smartcut/thumbnail",
        json={
            "session_id": "test_session_smartcut",
            "task_id": "test_smartcut_task_fail",
            "width": 640,  # 制限 1280 未満
            "height": 360, # 制限 720 未満
            "text": "Bad Thumbnail"
        }
    )
    # Pydanticのバリデーションエラー(422)が返ることを期待
    assert response.status_code == 422

def test_smartcut_thumbnail_sqlite_failure(monkeypatch):
    """異常系: SQLite接続失敗時にエラーがログ出力され、UnboundLocalErrorを伴わずに500エラーが返ることを確認"""
    # sqlite3.connect が例外を投げるようにモック
    def mock_connect(*args, **kwargs):
        raise sqlite3.OperationalError("Mocked database connection failure")
        
    monkeypatch.setattr(sqlite3, "connect", mock_connect)
    
    response = client.post(
        "/api/smartcut/thumbnail",
        json={
            "session_id": "test_session_smartcut",
            "task_id": "test_smartcut_task_sqlite_fail",
            "width": 1280,
            "height": 720,
            "text": "SQLite Failure Test"
        }
    )
    print("DEBUG RESPONSE JSON:", response.json())
    assert response.status_code == 500
    assert "Mocked database connection failure" in response.json()["error"]

def test_smartcut_thumbnail_agent_stop_on_exception():
    """異常系: エージェント処理中に例外が発生した場合でも、agent.stop()が確実に呼び出されることを確認"""
    from unittest.mock import AsyncMock, patch
    
    # 意図的に例外をスローさせるために register_task をモック
    with patch("agents.stage_bound_agent.StageBoundAgent.register_task", new_callable=AsyncMock) as mock_register, \
         patch("agents.stage_bound_agent.StageBoundAgent.stop", new_callable=AsyncMock) as mock_stop:
        
        mock_register.side_effect = Exception("Intended crash during registration")
        
        response = client.post(
            "/api/smartcut/thumbnail",
            json={
                "session_id": "test_session_smartcut",
                "task_id": "test_smartcut_task_crash",
                "width": 1280,
                "height": 720,
                "text": "Crash Test"
            }
        )
        
        # 500エラーになることを確認
        assert response.status_code == 500
        # register_task が呼ばれたことを確認
        mock_register.assert_called_once()
        # 例外が発生したにもかかわらず、finallyブロックで stop が呼ばれたことを確認
        mock_stop.assert_called_once()

def test_smartcut_thumbnail_sqlite_select_failure(monkeypatch):
    """異常系: 結果取得(SELECT)時にのみ SQLite エラーが発生した場合、適切な500エラーが返ることを確認"""
    import sqlite3
    
    original_connect = sqlite3.connect
    
    class MockConnection:
        def __init__(self, conn):
            self.conn = conn
            
        def execute(self, sql, *args, **kwargs):
            if "SELECT result FROM tasks" in sql:
                raise sqlite3.OperationalError("Mocked SELECT failure")
            return self.conn.execute(sql, *args, **kwargs)
            
        def commit(self):
            return self.conn.commit()
            
        def close(self):
            return self.conn.close()
            
        def __getattr__(self, name):
            return getattr(self.conn, name)
            
    def mock_connect(database, *args, **kwargs):
        conn = original_connect(database, *args, **kwargs)
        return MockConnection(conn)
        
    monkeypatch.setattr(sqlite3, "connect", mock_connect)
    
    response = client.post(
        "/api/smartcut/thumbnail",
        json={
            "session_id": "test_session_smartcut",
            "task_id": "test_smartcut_task_select_fail",
            "width": 1280,
            "height": 720,
            "text": "SQLite SELECT Failure Test"
        }
    )
    
    assert response.status_code == 500
    assert "Database error while fetching result" in response.json()["error"]
    assert "Mocked SELECT failure" in response.json()["error"]

def test_smartcut_init_plugin_import_failure(monkeypatch):
    """異常系: プラグインロード時に ImportError が発生した場合、適切な500エラーが返ることを確認"""
    def mock_import(*args, **kwargs):
        raise ImportError("Mocked plugin import failure")
        
    # LightweightScanPlugin のロードをシミュレートするため、該当箇所のインポートをフック
    import builtins
    original_import = builtins.__import__
    
    def patched_import(name, *args, **kwargs):
        if "LightweightScanPlugin" in name or "lightweight_scan_plugin" in name:
            raise ImportError("Mocked plugin import failure")
        return original_import(name, *args, **kwargs)
        
    monkeypatch.setattr(builtins, "__import__", patched_import)
    
    response = client.post(
        "/api/smartcut/init",
        json={
            "segments": [],
            "opening_duration": 10.0,
            "ending_duration": 20.0
        }
    )
    
    assert response.status_code == 500
    assert "Failed to load required plugins" in response.json()["error"]
    assert "Mocked plugin import failure" in response.json()["error"]


def test_smartcut_thumbnail_result_null_handling():
    """異常系: resultカラムがNULL（None）の場合に500エラーでクラッシュせず、適切に処理（フォールバック）されることを確認"""
    import routers.smartcut
    
    original_safe_query = routers.smartcut._safe_sqlite_query
    
    async def mock_safe_query(db_path, query, params=(), is_select=False, retries=3):
        if "SELECT result FROM tasks" in query:
            return (None,)
        return await original_safe_query(db_path, query, params, is_select, retries)
        
    try:
        routers.smartcut._safe_sqlite_query = mock_safe_query
        
        response = client.post(
            "/api/smartcut/thumbnail",
            json={
                "session_id": "test_session_smartcut",
                "task_id": "test_smartcut_task_null_result",
                "width": 1280,
                "height": 720,
                "text": "Null Result Test"
            }
        )
        
        assert response.status_code == 500
        assert "Thumbnail task completed but no result found" in response.json()["error"]
    finally:
        routers.smartcut._safe_sqlite_query = original_safe_query


def test_smartcut_empty_exception_message():
    """異常系: エラーメッセージが空の例外が発生した場合でも、フォールバックメッセージが返ることを確認"""
    import routers.smartcut
    from unittest.mock import patch
    
    with patch("plugins.smart_cut_plugin.SmartCutPlugin.update_recommendation") as mock_recommend:
        mock_recommend.side_effect = Exception("")
        
        from plugins.smart_cut_plugin import SmartCutContext
        sc = routers.smartcut._get_smart_cut()
        sc._context = SmartCutContext(all_highlights=[], all_chapters=[])
        
        response = client.post(
            "/api/smartcut/recommend",
            json={"target_duration_minutes": 15}
        )
        
        assert response.status_code == 500
        assert response.json()["error"] == "Unknown internal error occurred during recommendation"



@pytest.mark.anyio
async def test_safe_sqlite_query_retries(monkeypatch):
    """異常系/リトライ: _safe_sqlite_query が OperationalError 時にリトライすることを確認"""
    from routers.smartcut import _safe_sqlite_query
    import sqlite3
    import os

    call_count = 0
    original_connect = sqlite3.connect

    def mock_connect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise sqlite3.OperationalError("Mocked locking error")
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", mock_connect)

    db_path = "backend/temp/smartcut_test_retry.db" if os.path.exists("backend") else "temp/smartcut_test_retry.db"
    
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except OSError:
            pass

    res = await _safe_sqlite_query(db_path, "SELECT 1", is_select=True, retries=3)
    assert res == (1,)
    assert call_count == 3


def test_smartcut_thumbnail_special_characters_success():
    """正常系: 特殊文字や絵文字を含むテキストが渡された場合でも、正常にサムネイルが生成されることを確認"""
    response = client.post(
        "/api/smartcut/thumbnail",
        json={
            "session_id": "test_session_smartcut",
            "task_id": "test_smartcut_task_special_char",
            "width": 1280,
            "height": 720,
            "text": "🎨絵文字 & Special Characters! 漢字・ひらがな・カタカナ"
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["status"] == "COMPLETED"
    
    import os
    from pathlib import Path
    output_path = Path("backend/temp_thumbnails/test_smartcut_task_special_char.png")
    if not output_path.exists():
        output_path = Path("temp_thumbnails/test_smartcut_task_special_char.png")
        
    assert output_path.exists()
