# -*- coding: utf-8 -*-
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _wp
except ImportError:
    from path_resolver import writable_path as _wp

import pytest
import os
import sys
import time
import base64
import sqlite3
import json
import asyncio
from io import BytesIO
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image

# 未インポートの依存モジュールをダミー登録
sys.modules["branding_manager"] = MagicMock()
sys.modules["project_archiver"] = MagicMock()
sys.modules["video_processor"] = MagicMock()
sys.modules["google.adk"] = MagicMock()
sys.modules["google.genai"] = MagicMock()
sys.modules["mcp"] = MagicMock()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers.render import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)

DB_PATH = "backend/test_thumbnails.db"

@pytest.fixture(autouse=True)
def cleanup_test_db_and_temp():
    # テストDBと一時ファイルのクリーンアップ
    for p in [DB_PATH, "backend/thumbnails.db"]:
        path = Path(p)
        if path.exists():
            try:
                path.unlink()
            except Exception:
                pass
    
    temp_dir = _wp("backend/temp_thumbnails")
    if temp_dir.exists():
        for f in temp_dir.glob("*"):
            try:
                f.unlink()
            except Exception:
                pass
    yield
    # 事後クリーンアップ
    for p in [DB_PATH, "backend/thumbnails.db"]:
        path = Path(p)
        if path.exists():
            try:
                path.unlink()
            except Exception:
                pass
    if temp_dir.exists():
        for f in temp_dir.glob("*"):
            try:
                f.unlink()
            except Exception:
                pass

def create_dummy_image_base64(width: int, height: int, noisy: bool = False) -> str:
    # 指定サイズのダミー画像を作成してbase64で返す
    if noisy:
        # 圧縮しにくくファイルサイズが大きくなりやすいランダムノイズ画像
        import numpy as np
        rgb = np.random.randint(0, 256, (height, width, 3), dtype=np.uint8)
        img = Image.fromarray(rgb)
    else:
        img = Image.new("RGB", (width, height), color="white")
    
    out_io = BytesIO()
    img.save(out_io, format="JPEG", quality=95)
    return base64.b64encode(out_io.getvalue()).decode("utf-8")

def test_generate_thumbnail_quality_standards():
    # 正常系の品質基準テスト (1280x720, 16:9, <4MB, 正常にロード可能)
    dummy_b64 = create_dummy_image_base64(1920, 1080)
    mock_gen = MagicMock()
    async def dummy_generate(*args, **kwargs):
        return [{
            "id": "thumb_001",
            "concept_name": "Premium Mode",
            "description": "Standard Test Thumbnail",
            "prompt": "Test Prompt",
            "image_base64": dummy_b64,
            "ctr_score": 98.5
        }]
    mock_gen.generate = dummy_generate
    
    with patch("thumbnail_engine.generator.generator", mock_gen):
        response = client.post("/api/render/thumbnail", json={
            "video_title": "Test Title",
            "video_description": "Test Desc",
            "width": 1280,
            "height": 720,
            "quality": 95,
            "db_path": DB_PATH
        })
        
        assert response.status_code == 200, f"Failed: {response.text}"
        res_data = response.json()
        assert res_data["success"] is True
        assert len(res_data["thumbnails"]) == 1
        
        thumb = res_data["thumbnails"][0]
        assert thumb["width"] == 1280
        assert thumb["height"] == 720
        assert thumb["aspect_ratio"] == "1280:720"
        assert thumb["file_size_bytes"] < 4 * 1024 * 1024
        
        # Pillowによる正常ロード検証
        img_data = base64.b64decode(thumb["image_base64"])
        img = Image.open(BytesIO(img_data))
        img.verify()  # 破損していないこと

def test_generate_thumbnail_auto_quality_retry():
    # 圧縮しにくい巨大ノイズ画像を返すことで、ファイルサイズが4MBを超えた場合に
    # 自動的に品質を下げて4MB未満に抑えるリトライロジックが走ることを検証
    # (ここでは高解像度 4000x2250 の超高ノイズ画像を使用)
    dummy_b64 = create_dummy_image_base64(4000, 2250, noisy=True)
    mock_gen = MagicMock()
    async def dummy_generate(*args, **kwargs):
        return [{
            "id": "thumb_heavy",
            "concept_name": "Heavy Noise",
            "description": "Noisy Image for Size Test",
            "prompt": "Noise Prompt",
            "image_base64": dummy_b64,
            "ctr_score": 50.0
        }]
    mock_gen.generate = dummy_generate
    
    with patch("thumbnail_engine.generator.generator", mock_gen):
        response = client.post("/api/render/thumbnail", json={
            "video_title": "Test Heavy Image",
            "video_description": "Auto Quality Reducer Test",
            "width": 1920,
            "height": 1080,
            "quality": 98,
            "db_path": DB_PATH
        })
        
        assert response.status_code == 200, f"Failed: {response.text}"
        res_data = response.json()
        assert res_data["success"] is True
        thumb = res_data["thumbnails"][0]
        assert thumb["width"] == 1920
        assert thumb["height"] == 1080
        assert thumb["file_size_bytes"] < 4 * 1024 * 1024  # 4MB未満に収まっていること
        
        # 正常にロード可能か
        img_data = base64.b64decode(thumb["image_base64"])
        img = Image.open(BytesIO(img_data))
        img.load()
        assert img.size == (1920, 1080)

def test_generate_thumbnail_resolution_error():
    # 解像度不足 (1280x720 未満) の場合に HTTP 400 が返ることを検証
    response = client.post("/api/render/thumbnail", json={
        "video_title": "Low Res Test",
        "width": 1000,
        "height": 562,  # 16:9に近いが1280x720未満
        "quality": 95,
        "db_path": DB_PATH
    })
    assert response.status_code == 400
    assert "Resolution must be at least 1280x720" in response.json()["detail"]

def test_generate_thumbnail_aspect_ratio_error():
    # アスペクト比が 16:9 でない場合に HTTP 400 が返ることを検証
    response = client.post("/api/render/thumbnail", json={
        "video_title": "Wrong Aspect Test",
        "width": 1280,
        "height": 1024,  # 5:4
        "quality": 95,
        "db_path": DB_PATH
    })
    assert response.status_code == 400
    assert "Unsupported aspect ratio" in response.json()["detail"]

def test_generate_thumbnail_stage_bound_agent_integration():
    # StageBoundAgentによるDB格納、マイグレーション、およびリトライ履歴などの連携確認
    dummy_b64 = create_dummy_image_base64(1280, 720)
    mock_gen = MagicMock()
    async def dummy_generate(*args, **kwargs):
        return [{
            "id": "thumb_agent_01",
            "concept_name": "Agent Integrated Mode",
            "description": "Integration Test",
            "prompt": "Integration Prompt",
            "image_base64": dummy_b64,
            "ctr_score": 99.0
        }]
    mock_gen.generate = dummy_generate
    
    with patch("thumbnail_engine.generator.generator", mock_gen):
        response = client.post("/api/render/thumbnail", json={
            "video_title": "Agent Integration Title",
            "width": 1280,
            "height": 720,
            "quality": 95,
            "db_path": DB_PATH
        })
        
        assert response.status_code == 200
        
        # SQLite DBにレコードが保存されているか、DBスキーマ（マイグレーション）が正しく機能しているか確認
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute("SELECT id, stage, status, result, max_retries FROM tasks")
            rows = cursor.fetchall()
            assert len(rows) == 1
            task_id, stage, status, result, max_retries = rows[0]
            assert stage == "thumbnail"
            assert status == "COMPLETED"
            assert max_retries == 2
            
            # 結果JSONの検証
            result_data = json.loads(result)
            assert result_data["id"] == "thumb_agent_01"
            assert result_data["width"] == 1280
            assert result_data["height"] == 720
            assert "image_base64" in result_data
        finally:
            conn.close()
