# -*- coding: utf-8 -*-
import os
import sys
from pathlib import Path
current_file = Path(__file__).resolve()
backend_dir = current_file.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import asyncio
import sqlite3
import pytest
from PIL import Image
import json

from backend.project_archiver import ProjectArchiver
from backend.agents.stage_bound_agent import StageBoundAgent

def test_thumbnail_generation_success(tmp_path):
    output_path = tmp_path / "test_thumb.png"
    archiver = ProjectArchiver()
    
    res_path = archiver.generate_thumbnail(output_path, text="Project Thumb")
    assert res_path.exists()
    
    with Image.open(res_path) as img:
        assert img.size == (1280, 720)


def test_thumbnail_validation(tmp_path):
    archiver = ProjectArchiver()
    
    # 1. 正常な画像
    ok_path = tmp_path / "ok.png"
    archiver.generate_thumbnail(ok_path, width=1280, height=720)
    result = archiver.validate_thumbnail(ok_path)
    assert result["width"] == 1280
    assert result["height"] == 720
    
    # 2. 低解像度の画像 (1280x720未満)
    bad_res_path = tmp_path / "bad_res.png"
    archiver.generate_thumbnail(bad_res_path, width=640, height=360)
    with pytest.raises(ValueError) as exc:
        archiver.validate_thumbnail(bad_res_path)
    assert "Resolution must be at least 1280x720" in str(exc.value)
    
    # 3. アスペクト比が正しくない (16:10 など)
    bad_aspect_path = tmp_path / "bad_aspect.png"
    archiver.generate_thumbnail(bad_aspect_path, width=1280, height=800)
    with pytest.raises(ValueError) as exc:
        archiver.validate_thumbnail(bad_aspect_path)
    assert "Aspect ratio must be 16:9" in str(exc.value)
    
    # 4. ファイルが存在しない
    non_existent = tmp_path / "ghost.png"
    with pytest.raises(FileNotFoundError):
        archiver.validate_thumbnail(non_existent)
        
    # 5. 破損画像
    corrupted_path = tmp_path / "corrupt.png"
    corrupted_path.write_text("not an image at all", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        archiver.validate_thumbnail(corrupted_path)
    assert "Image is corrupted" in str(exc.value)

    # 6. 4MB以上のファイルサイズ制限の検証
    large_file = tmp_path / "large_file.png"
    large_file.write_bytes(b"\x00" * (4 * 1024 * 1024 + 10))
    with pytest.raises(ValueError) as exc:
        archiver.validate_thumbnail(large_file)
    assert "File size exceeds 4MB limit" in str(exc.value)


@pytest.mark.asyncio
async def test_thumbnail_stage_bound_agent_integration(tmp_path):
    db_file = tmp_path / "thumbnail_agent.db"
    archiver = ProjectArchiver()
    archiver.output_dir = tmp_path
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    
    task_id = "t_archiver_thumb_ok"
    await agent.register_task(task_id=task_id, initial_status="READY")
    
    await agent.start(archiver.resolve_thumbnail_task)
    
    for _ in range(20):
        status = await agent.get_task_status(task_id)
        if status in ("COMPLETED", "FAILED"):
            break
        await asyncio.sleep(0.05)
        
    final_status = await agent.get_task_status(task_id)
    assert final_status == "COMPLETED"
    
    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.execute("SELECT result, error, retry_count FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None
        result_data = json.loads(row[0])
        assert result_data["width"] == 1280
        assert result_data["height"] == 720
        assert row[1] is None
        assert row[2] == 0
    finally:
        conn.close()
        
    await agent.stop()


@pytest.mark.asyncio
async def test_thumbnail_stage_bound_agent_retry_on_failure(tmp_path):
    db_file = tmp_path / "thumbnail_retry.db"
    
    archiver = ProjectArchiver()
    archiver.output_dir = Path("C:/invalid_dir_?:*")
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    
    task_id = "t_archiver_thumb_fail"
    await agent.register_task(task_id=task_id, initial_status="READY", max_retries=2)
    
    await agent.start(archiver.resolve_thumbnail_task)
    
    for _ in range(20):
        status = await agent.get_task_status(task_id)
        if status == "FAILED":
            break
        await asyncio.sleep(0.05)
        
    final_status = await agent.get_task_status(task_id)
    assert final_status == "FAILED"
    
    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.execute("SELECT retry_count, status, error FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == 2
        assert row[1] == "FAILED"
        assert row[2] is not None
    finally:
        conn.close()
        
    await agent.stop()


def test_validate_thumbnail_failed_to_load_size(tmp_path):
    from unittest.mock import patch
    archiver = ProjectArchiver()
    
    # 正常な画像を作成
    ok_path = tmp_path / "ok.png"
    archiver.generate_thumbnail(ok_path, width=1280, height=720)
    
    # 2回目の Image.open 呼び出しで例外を発生させる
    original_open = Image.open
    calls = []
    
    def mock_open(*args, **kwargs):
        calls.append(args)
        if len(calls) == 2:
            raise RuntimeError("Mocked size load failure")
        return original_open(*args, **kwargs)
        
    with patch("PIL.Image.open", side_effect=mock_open):
        with pytest.raises(ValueError) as exc:
            archiver.validate_thumbnail(ok_path)
        assert "Failed to load image for resolution check" in str(exc.value)

