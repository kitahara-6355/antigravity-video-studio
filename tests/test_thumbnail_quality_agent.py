# -*- coding: utf-8 -*-
import sys
import os
import pytest
import json
import asyncio
import sqlite3
import base64
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image

# パス追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.agents.stage_bound_agent import StageBoundAgent
from backend.thumbnail_engine.generator import (
    generator as thumbnail_generator,
    resolve_generator_thumbnail_task
)

def create_dummy_image(width: int, height: int, target_size_bytes: int = 0) -> bytes:
    """テスト用のダミーJPEG画像バイナリを生成"""
    img = Image.new("RGB", (width, height), color="blue")
    import io
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='JPEG', quality=95)
    data = img_byte_arr.getvalue()
    if len(data) < target_size_bytes:
        data += b'\x00' * (target_size_bytes - len(data))
    return data

@pytest.mark.asyncio
async def test_generator_stage_bound_agent_integration(tmp_path):
    """resolve_generator_thumbnail_task を使用した StageBoundAgent の統合テスト"""
    db_file = tmp_path / "test_generator_agent.db"
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    agent.output_dir = tmp_path
    agent.video_title = "Integration Test Video Title"
    agent.video_description = "Testing with StageBoundAgent and Imagen Generator"
    
    task_id = "gen_agent_task_001"
    
    # generateのモック（1280x720のダミー画像）
    dummy_img = create_dummy_image(1280, 720)
    
    with patch.object(thumbnail_generator, "generate") as mock_generate:
        mock_generate.return_value = [
            {
                "id": "thumb_test_0",
                "concept_name": "テストコンセプト",
                "description": "テスト説明",
                "prompt": "A beautiful cinematic thumbnail",
                "image_base64": base64.b64encode(dummy_img).decode("utf-8"),
                "ctr_score": 8.5
            }
        ]
        
        # タスクを READY 状態で登録
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=1)
        
        async def process_func(tid):
            return await resolve_generator_thumbnail_task(agent, tid)
            
        await agent.start(process_func)
        
        # 完了または失敗まで待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status in ("COMPLETED", "FAILED"):
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
        assert final_status == "COMPLETED"
        
        # 1. 生成された画像ファイルの存在確認
        output_file = tmp_path / f"{task_id}.jpg"
        assert output_file.exists()
        
        # 2. Pillowによる破損チェックとロード確認
        with Image.open(output_file) as img:
            img.verify()
        with Image.open(output_file) as img:
            img.load()
            width, height = img.size
            
        # 3. 解像度の検証 (1280x720 以上)
        assert width >= 1280
        assert height >= 720
        
        # 4. アスペクト比の検証 (16:9)
        aspect_ratio = width / height
        assert abs(aspect_ratio - (16.0 / 9.0)) < 0.01
        
        # 5. ファイルサイズが 4MB 未完であることの検証
        file_size_bytes = output_file.stat().st_size
        assert file_size_bytes < 4 * 1024 * 1024
        
        # 6. DBマイグレーション＆結果保存の検証
        conn = sqlite3.connect(str(db_file))
        try:
            # 連携タスク結果の保存先
            cursor = conn.execute("SELECT task_id, path, width, height, size_bytes FROM thumbnail_results WHERE task_id = ?", (task_id,))
            row = cursor.fetchone()
            assert row is not None
            tid_db, path_db, width_db, height_db, size_db = row
            assert tid_db == task_id
            assert path_db == str(output_file)
            assert width_db == width
            assert height_db == height
            assert size_db == file_size_bytes
        finally:
            conn.close()

@pytest.mark.asyncio
async def test_generator_agent_retry_on_failure(tmp_path):
    """一時的失敗からの自動リトライフローの検証"""
    db_file = tmp_path / "test_generator_retry.db"
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    agent.output_dir = tmp_path
    
    task_id = "gen_retry_task"
    
    call_count = 0
    dummy_img = create_dummy_image(1280, 720)
    
    async def process_func(tid):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # 最初の呼び出しで一時的エラーを模倣
            raise OSError("Temporary storage or API timeout failure")
        
        # 2回目は成功させるため、モックを設定
        with patch.object(thumbnail_generator, "generate") as mock_generate:
            mock_generate.return_value = [
                {
                    "id": "thumb_test_retry",
                    "concept_name": "リトライコンセプト",
                    "description": "リトライ説明",
                    "prompt": "Cinematic thumbnail retry",
                    "image_base64": base64.b64encode(dummy_img).decode("utf-8"),
                    "ctr_score": 8.0
                }
            ]
            return await resolve_generator_thumbnail_task(agent, tid)

    # 最大リトライ回数を 2 に設定して登録
    await agent.register_task(task_id=task_id, initial_status="READY", max_retries=2)
    
    await agent.start(process_func)
    
    for _ in range(50):
        status = await agent.get_task_status(task_id)
        if status == "COMPLETED":
            break
        await asyncio.sleep(0.05)
        
    final_status = await agent.get_task_status(task_id)
    await agent.stop()
    
    assert final_status == "COMPLETED"
    assert call_count == 2
    
    # DBでリトライ回数が1であることを検証
    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.execute("SELECT retry_count, status FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None
        retry_count, status = row
        assert status == "COMPLETED"
        assert retry_count == 1
    finally:
        conn.close()
