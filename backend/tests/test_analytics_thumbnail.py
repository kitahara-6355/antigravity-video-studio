# -*- coding: utf-8 -*-
import sys
import os
import pytest
import asyncio
import sqlite3
import json
from pathlib import Path
from PIL import Image

# プロジェクトルートとbackendをパスに追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.branding.analytics_manager import analytics_manager
from backend.branding.history_manager import ImageValidationError, ThumbnailValidator
from backend.agents.stage_bound_agent import StageBoundAgent, validate_thumbnail

@pytest.mark.asyncio
async def test_generate_and_validate_thumbnail_success(tmp_path):
    """正常系: 正常なパラメータでサムネイルが生成され、品質基準を満たし、DB保存されることを確認"""
    db_file = tmp_path / "test_analytics_thumb.db"
    task_id = "test_analytics_task_001"
    
    # 実行
    result = await analytics_manager.generate_and_validate_thumbnail(
        task_id=task_id,
        title="Premium Video Title",
        text="Antigravity Studio",
        db_path=str(db_file),
        output_dir=tmp_path
    )
    
    # アサーション
    assert result["task_id"] == task_id
    assert Path(result["path"]).exists()
    assert result["width"] == 1280
    assert result["height"] == 720
    assert result["size_bytes"] < 4 * 1024 * 1024
    
    # Pillowロード確認
    with Image.open(result["path"]) as img:
        img.load()
        assert img.size == (1280, 720)
        
    # DB連携確認
    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.execute("SELECT * FROM thumbnail_results WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None
        tid, path, width, height, size_bytes, verified_at = row
        assert tid == task_id
        assert width == 1280
        assert height == 720
        assert size_bytes == result["size_bytes"]
    finally:
        conn.close()

@pytest.mark.asyncio
async def test_generate_and_validate_thumbnail_empty_title(tmp_path):
    """異常系: 空のタイトルが指定された場合に ValueError が発生することを確認"""
    db_file = tmp_path / "test_analytics_thumb.db"
    task_id = "test_analytics_task_err"
    
    with pytest.raises(ValueError, match="Video title cannot be empty"):
        await analytics_manager.generate_and_validate_thumbnail(
            task_id=task_id,
            title="",
            db_path=str(db_file),
            output_dir=tmp_path
        )

def test_stage_bound_agent_integration(tmp_path):
    """StageBoundAgentと連携したリトライフローおよびDB結果保存のテスト"""
    db_file = tmp_path / "test_agent_analytics.db"
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    agent.output_dir = tmp_path
    
    task_id = "agent_analytics_task"
    
    # 最初の1回は失敗し、2回目で成功させる process_func
    call_count = 0
    
    async def process_func(tid):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise OSError("Simulated temporary storage failure")
            
        # 2回目は正常完了
        from backend.branding.history_manager import resolve_thumbnail_task
        return await resolve_thumbnail_task(
            task_id=tid,
            db_path=str(db_file),
            output_dir=tmp_path
        )
        
    async def run_test():
        # 最大リトライ回数を 2 に設定してREADY状態で登録
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=2)
        
        await agent.start(process_func)
        
        # 完了するまで待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status == "COMPLETED":
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
        assert final_status == "COMPLETED"
        assert call_count == 2
        
        # DBでリトライカウントが 1、ステータスが COMPLETED であることを確認
        conn = sqlite3.connect(str(db_file))
        try:
            cursor = conn.execute("SELECT status, retry_count FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            assert row is not None
            status, retry_count = row
            assert status == "COMPLETED"
            assert retry_count == 1
            
            # 結果保存テーブルの確認
            cursor = conn.execute("SELECT * FROM thumbnail_results WHERE task_id = ?", (task_id,))
            row = cursor.fetchone()
            assert row is not None
            assert row[2] == 1280
            assert row[3] == 720
        finally:
            conn.close()

    asyncio.run(run_test())
