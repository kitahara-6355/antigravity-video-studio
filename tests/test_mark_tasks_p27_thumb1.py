# -*- coding: utf-8 -*-
import sys
import os
import json
import pytest
import sqlite3
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
from PIL import Image
import io

sys.path.insert(0, '.')
sys.path.insert(0, './backend')

from backend.agents.orchestration import mark_tasks_p27_thumb1
from backend.agents.orchestration.mark_tasks_p27_thumb1 import (
    verify_thumbnail_quality,
    run_thumbnail_stage_task
)

def create_test_image_bytes(width=1280, height=720, fmt="PNG"):
    img = Image.new("RGB", (width, height), color="red")
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()

@pytest.fixture
def temp_image_file(tmp_path):
    img_path = tmp_path / "temp_thumb.png"
    img = Image.new("RGB", (1280, 720), color="blue")
    img.save(img_path, format="PNG")
    return img_path

def test_verify_thumbnail_quality_success_bytes():
    img_bytes = create_test_image_bytes(1280, 720)
    result = verify_thumbnail_quality(img_bytes)
    assert result["valid"] is True
    assert result["width"] == 1280
    assert result["height"] == 720
    assert result["size_bytes"] == len(img_bytes)

def test_verify_thumbnail_quality_success_file(temp_image_file):
    result = verify_thumbnail_quality(temp_image_file)
    assert result["valid"] is True
    assert result["width"] == 1280
    assert result["height"] == 720

def test_verify_thumbnail_quality_invalid_type():
    with pytest.raises(TypeError, match="Invalid argument type"):
        verify_thumbnail_quality(None)
    with pytest.raises(TypeError, match="Invalid argument type"):
        verify_thumbnail_quality(123)

def test_verify_thumbnail_quality_corrupted_bytes():
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        verify_thumbnail_quality(b"invalid_corrupted_bytes_data")

def test_verify_thumbnail_quality_not_found():
    with pytest.raises(FileNotFoundError, match="Thumbnail file not found"):
        verify_thumbnail_quality("non_existent_file_path_12345.png")

def test_verify_thumbnail_quality_size_exceeded():
    with patch("PIL.Image.open") as mock_open:
        mock_img = MagicMock()
        mock_img.size = (1280, 720)
        mock_open.return_value.__enter__.return_value = mock_img
        
        large_data = b"\x00" * (4 * 1024 * 1024 + 100)
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            verify_thumbnail_quality(large_data)

def test_verify_thumbnail_quality_resolution_insufficient():
    img_bytes = create_test_image_bytes(1000, 720)
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        verify_thumbnail_quality(img_bytes)

def test_verify_thumbnail_quality_aspect_ratio_invalid():
    img_bytes = create_test_image_bytes(1280, 800)
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        verify_thumbnail_quality(img_bytes)

def test_verify_thumbnail_quality_zero_height():
    with patch("PIL.Image.open") as mock_open:
        mock_img = MagicMock()
        mock_img.size = (1280, 0)
        mock_open.return_value.__enter__.return_value = mock_img
        
        with pytest.raises(ValueError, match="Invalid image height"):
            verify_thumbnail_quality(b"dummy_bytes")

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_success():
    task_id = "test_task_001"
    res_str = await run_thumbnail_stage_task(task_id, db_path=":memory:")
    result = json.loads(res_str)
    
    assert result["valid"] is True
    assert result["width"] == 1280
    assert result["height"] == 720
    
    project_root = Path(mark_tasks_p27_thumb1.__file__).resolve().parents[3]
    expected_path = project_root / "temp_thumbnails" / f"{task_id}.png"
    assert expected_path.exists()
    
@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_db_integration(tmp_path):
    task_id = "test_task_db_002"
    db_file = tmp_path / "test_thumb.db"
    
    res_str = await run_thumbnail_stage_task(task_id, db_path=str(db_file))
    result = json.loads(res_str)
    
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.execute("SELECT task_id, width, height FROM thumbnail_results WHERE task_id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    assert row[0] == task_id
    assert row[1] == 1280
    assert row[2] == 720

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_db_error():
    with patch("sqlite3.connect", side_effect=sqlite3.OperationalError("Mocked DB connection error")):
        with pytest.raises(sqlite3.OperationalError, match="Mocked DB connection error"):
            await run_thumbnail_stage_task("test_task_fail", db_path=":memory:")

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_general_exception():
    with patch("numpy.meshgrid", side_effect=RuntimeError("Meshgrid calculation failed")):
        with pytest.raises(RuntimeError, match="Meshgrid calculation failed"):
            await run_thumbnail_stage_task("test_task_general_fail", db_path=":memory:")
