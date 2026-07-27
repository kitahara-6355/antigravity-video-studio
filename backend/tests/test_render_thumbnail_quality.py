import os
import json
import sqlite3
import asyncio
import pytest
from pathlib import Path
from PIL import Image
from fastapi.testclient import TestClient

# バックエンドディレクトリをパスに追加してインポートできるようにする
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from routers.render import ThumbnailGenerateRequest
from agents.stage_bound_agent import StageBoundAgent
from branding_manager import branding_manager

# FastAPI TestClient
client = TestClient(app)

@pytest.fixture
def mock_genai_key(monkeypatch):
    """GOOGLE_API_KEYをモックしてImagen呼び出しがフォールバックされるようにする"""
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")

def test_api_thumbnail_generation_success(mock_genai_key, tmp_path):
    """/render/thumbnail エンドポイントが正常に動作し、品質基準を満たすサムネイルが生成されること"""
    # 1. APIリクエスト送信
    response = client.post(
        "/api/render/thumbnail",
        json={
            "video_title": "テスト動画タイトル: 自動生成サムネイルの品質検証",
            "video_description": "この動画はサムネイル生成機能の自動検証テスト用です。",
            "width": 1280,
            "height": 720,
            "quality": 90
        }
    )
    
    # 2. レスポンス検証
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["success"] is True
    assert "thumbnails" in res_data
    assert len(res_data["thumbnails"]) > 1
    
    # 生成されたサムネイルの品質検証
    thumb = res_data["thumbnails"][0]
    assert thumb["width"] >= 1280
    assert thumb["height"] >= 720
    
    # アスペクト比検証 (16:9)
    aspect_ratio = thumb["width"] / thumb["height"]
    assert abs(aspect_ratio - (16.0 / 9.0)) < 0.02
    
    # ファイルサイズ検証 (4MB未満)
    assert thumb["file_size_bytes"] < 4 * 1024 * 1024
    
    # ファイルの存在と破損チェック
    output_path = Path(thumb["path"])
    assert output_path.exists()
    
    # Pillowによるロードテスト
    try:
        with Image.open(output_path) as img:
            img.verify()
        with Image.open(output_path) as img:
            img.load()
            assert img.size == (thumb["width"], thumb["height"])
    except Exception as e:
        pytest.fail(f"Generated image is corrupted or cannot be loaded: {e}")

def test_api_thumbnail_invalid_resolution():
    """1280x720未満の解像度が指定された場合、400エラーが返ること"""
    response = client.post(
        "/api/render/thumbnail",
        json={
            "video_title": "低解像度テスト",
            "width": 640,
            "height": 360
        }
    )
    assert response.status_code == 400
    assert "Resolution must be at least 1280x720" in response.json()["detail"]

def test_api_thumbnail_invalid_aspect_ratio():
    """16:9でないアスペクト比が指定された場合、400エラーが返ること"""
    response = client.post(
        "/api/render/thumbnail",
        json={
            "video_title": "不正なアスペクト比テスト",
            "width": 1280,
            "height": 1020 # 4:3に近い比率
        }
    )
    assert response.status_code == 400
    assert "Aspect ratio must be 16:9" in response.json()["detail"]

@pytest.mark.anyio
async def test_stage_bound_agent_integration_in_render(tmp_path):
    """routers/render.py 内で StageBoundAgent が正常に動作し結果がDBに保存・リトライされること"""
    db_file = tmp_path / "test_render_tasks.db"
    
    # StageBoundAgentを起動してタスクを実行する
    agent = StageBoundAgent(
        stage_name="thumbnail",
        db_path=str(db_file),
        poll_interval=0.01
    )
    
    # タスクID
    task_id = "test_render_task_001"
    
    # タスク登録
    await agent.register_task(task_id, initial_status="READY", max_retries=2)
    
    # 解決関数を定義
    from routers.render import ThumbnailGenerateRequest
    req = ThumbnailGenerateRequest(
        video_title="Agentテストタイトル",
        video_description="Agent連携テスト用の詳細説明",
        width=1280,
        height=720
    )
    
    # routers/render.py の内部ロジックと同様のタスク処理をモック
    async def process_task(tid):
        from branding_manager import branding_manager
        # フォールバック生成
        fallback_res = branding_manager.generate_and_validate_thumbnail(
            req.video_title, req.video_description
        )
        import base64
        image_bytes = base64.b64decode(fallback_res["image_base64"])
        
        output_path = tmp_path / f"{tid}.jpg"
        with open(output_path, "wb") as f:
            f.write(image_bytes)
            
        val_result = branding_manager.validate_image_quality(output_path)
        
        return json.dumps({
            "path": str(output_path),
            "width": val_result["width"],
            "height": val_result["height"],
            "file_size_bytes": val_result["size_bytes"],
            "prompt": "fallback",
            "image_base64": fallback_res["image_base64"],
            "ctr_score": 5.0,
            "aspect_ratio": val_result["aspect_ratio"]
        })

    # Agent開始
    await agent.start(process_task)
    
    # 完了待機
    for _ in range(50):
        status = await agent.get_task_status(task_id)
        if status == "COMPLETED":
            break
        await asyncio.sleep(0.05)
        
    status = await agent.get_task_status(task_id)
    assert status == "COMPLETED"
    
    # DBから結果を確認
    conn = sqlite3.connect(str(db_file))
    cursor = conn.execute("SELECT result, retry_count FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    result_data = json.loads(row[0])
    assert result_data["width"] == 1280
    assert result_data["height"] == 720
    assert result_data["file_size_bytes"] < 4 * 1024 * 1024
    assert Path(result_data["path"]).exists()
    
    await agent.stop()
