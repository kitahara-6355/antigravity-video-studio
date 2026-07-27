# -*- coding: utf-8 -*-
import sys
import os
import pytest
import json
import asyncio
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image

# パス追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# 依存関係のインポートを branding.history_manager に統一
from branding.history_manager import ImageValidationError
from backend.branding.analytics_manager import AnalyticsManager

@pytest.mark.asyncio
async def test_analytics_manager_generate_thumbnail_success(tmp_path):
    """正常系: 品質基準を満たした画像が生成され、StageBoundAgent連携による結果保存が行われることを確認"""
    db_file = tmp_path / "test_analytics_success.db"
    output_dir = tmp_path / "thumbnails"
    
    manager = AnalyticsManager()
    task_id = "test_task_success"
    title = "Antigravity Feature Video"
    text = "Antigravity Success Title"
    
    # 実行
    result = await manager.generate_and_validate_thumbnail(
        task_id=task_id,
        title=title,
        text=text,
        db_path=str(db_file),
        output_dir=output_dir,
        max_retries=1
    )
    
    # 戻り値の検証
    assert result["task_id"] == task_id
    assert Path(result["path"]).exists()
    assert result["width"] == 1280
    assert result["height"] == 720
    assert result["size_bytes"] < 4 * 1024 * 1024
    
    # ピクセルデータのデコードチェック
    with Image.open(result["path"]) as img:
        img.load()
        assert img.size == (1280, 720)
        
    # DB連携の検証
    conn = sqlite3.connect(str(db_file))
    try:
        # tasks テーブルの確認 (StageBoundAgent 連携)
        cursor = conn.execute("SELECT status, result, retry_count FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None
        status, result_str, retry_count = row
        assert status == "COMPLETED"
        assert retry_count == 0
        db_result = json.loads(result_str)
        assert db_result["task_id"] == task_id
        
        # thumbnail_results テーブルの確認 (DBマイグレーション連携)
        cursor2 = conn.execute("SELECT task_id, path, width, height, size_bytes FROM thumbnail_results WHERE task_id = ?", (task_id,))
        row2 = cursor2.fetchone()
        assert row2 is not None
        db_tid, db_path, db_w, db_h, db_size = row2
        assert db_tid == task_id
        assert db_w == 1280
        assert db_h == 720
        assert db_size == result["size_bytes"]
    finally:
        conn.close()

@pytest.mark.asyncio
async def test_analytics_manager_generate_thumbnail_invalid_title(tmp_path):
    """異常系: 空タイトルの場合に ValueError が発生することを確認"""
    manager = AnalyticsManager()
    with pytest.raises(ValueError, match="Video title cannot be empty"):
        await manager.generate_and_validate_thumbnail(
            task_id="test_task_empty",
            title="",
            db_path=str(tmp_path / "test.db")
        )

@pytest.mark.asyncio
async def test_analytics_manager_generate_thumbnail_corrupted(tmp_path):
    """異常系: 生成画像が破損している（Pillowでロード不可）場合に ImageValidationError が発生することを確認"""
    db_file = tmp_path / "test_analytics_corrupt.db"
    output_dir = tmp_path / "thumbnails"
    manager = AnalyticsManager()
    task_id = "test_task_corrupt"
    
    # patchのターゲットを branding.history_manager.PremiumThumbnailGenerator.generate に変更
    with patch("branding.history_manager.PremiumThumbnailGenerator.generate") as mock_gen:
        def fake_generate(output_path, *args, **kwargs):
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(b"not a valid png or jpeg header")
            return Path(output_path)
            
        mock_gen.side_effect = fake_generate
        
        with pytest.raises((ImageValidationError, RuntimeError)):
            await manager.generate_and_validate_thumbnail(
                task_id=task_id,
                title="Corrupted Test",
                db_path=str(db_file),
                output_dir=output_dir,
                max_retries=0
            )

@pytest.mark.asyncio
async def test_analytics_manager_generate_thumbnail_retry(tmp_path):
    """正常系: 1回目の生成で一時的な OSError が発生し、リトライで成功するケースを検証"""
    db_file = tmp_path / "test_analytics_retry.db"
    output_dir = tmp_path / "thumbnails"
    manager = AnalyticsManager()
    task_id = "test_task_retry"
    
    call_count = 0
    from branding.history_manager import PremiumThumbnailGenerator
    original_generate = PremiumThumbnailGenerator.generate
    
    def fake_generate(output_path, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise OSError("Simulated temporary filesystem error")
        return original_generate(output_path, *args, **kwargs)
        
    with patch("branding.history_manager.PremiumThumbnailGenerator.generate", side_effect=fake_generate):
        result = await manager.generate_and_validate_thumbnail(
            task_id=task_id,
            title="Retry Test",
            db_path=str(db_file),
            output_dir=output_dir,
            max_retries=2
        )
        
        assert result["task_id"] == task_id
        assert call_count == 2  # 2回実行されたはず
        
        # DB上のリトライカウントが 1 になっているか確認
        conn = sqlite3.connect(str(db_file))
        try:
            cursor = conn.execute("SELECT status, retry_count FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            assert row is not None
            status, retry_count = row
            assert status == "COMPLETED"
            assert retry_count == 1
        finally:
            conn.close()

@pytest.mark.asyncio
async def test_analytics_manager_generate_thumbnail_failed(tmp_path):
    """異常系: リトライ上限を超えてエラーが継続した場合、最終的に RuntimeError が発生することを確認"""
    db_file = tmp_path / "test_analytics_failed.db"
    output_dir = tmp_path / "thumbnails"
    manager = AnalyticsManager()
    task_id = "test_task_failed"
    
    # 常にエラーを返す
    with patch("branding.history_manager.PremiumThumbnailGenerator.generate", side_effect=OSError("Permanent error")):
        with pytest.raises(RuntimeError, match="Thumbnail generation task failed"):
            await manager.generate_and_validate_thumbnail(
                task_id=task_id,
                title="Fail Test",
                db_path=str(db_file),
                output_dir=output_dir,
                max_retries=1
            )
            
        # DB上で FAILED になっていることを確認
        conn = sqlite3.connect(str(db_file))
        try:
            cursor = conn.execute("SELECT status, retry_count FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            assert row is not None
            status, retry_count = row
            assert status == "FAILED"
            assert retry_count == 1
        finally:
            conn.close()
