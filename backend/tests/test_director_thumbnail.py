import sys
import os
import json
import asyncio
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock
from PIL import Image

# Ensure backend path is in sys.path
backend_path = Path(__file__).parent.parent
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from routers.director import (
    generate_director_thumbnail,
    validate_director_thumbnail,
    resolve_director_thumbnail_task
)
from agents.stage_bound_agent import StageBoundAgent

def create_valid_test_image(width=1280, height=720, fmt="PNG") -> Image.Image:
    return Image.new("RGB", (width, height), color=(73, 109, 137))

def test_generate_director_thumbnail_success(tmp_path):
    out_path = tmp_path / "test_thumb.png"
    res_path = generate_director_thumbnail(out_path)
    assert res_path == out_path
    assert out_path.exists()
    
    with Image.open(out_path) as img:
        assert img.size == (1280, 720)

def test_validate_director_thumbnail_success(tmp_path):
    out_path = tmp_path / "valid.png"
    img = create_valid_test_image(1280, 720)
    img.save(out_path, format="PNG")
    
    result = validate_director_thumbnail(out_path)
    assert result["width"] == 1280
    assert result["height"] == 720
    assert result["path"] == str(out_path)
    assert result["size_bytes"] > 0

def test_validate_director_thumbnail_failures(tmp_path):
    # 1. 存在しないファイル
    with pytest.raises(FileNotFoundError):
        validate_director_thumbnail(tmp_path / "missing.png")
        
    # 2. 解像度不足の画像
    low_res_path = tmp_path / "low_res.png"
    img = create_valid_test_image(640, 360)
    img.save(low_res_path, format="PNG")
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        validate_director_thumbnail(low_res_path)
        
    # 3. アスペクト比が異なる画像
    bad_ratio_path = tmp_path / "bad_ratio.png"
    img = create_valid_test_image(1280, 960) # 4:3
    img.save(bad_ratio_path, format="PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        validate_director_thumbnail(bad_ratio_path)
        
    # 4. ファイルサイズ制限 (4MB)
    valid_path = tmp_path / "valid.png"
    img = create_valid_test_image(1280, 720)
    img.save(valid_path, format="PNG")
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 5 * 1024 * 1024  # 5MB
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            validate_director_thumbnail(valid_path)

def test_resolve_director_thumbnail_task_stage_bound(tmp_path):
    db_file = tmp_path / "test_director_thumb.db"
    task_id = "director_thumb_test"
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    
    async def run_test():
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=1)
        
        # routers.director.THUMBNAIL_OUTPUT_DIR を tmp_path に一時的にパッチ
        import routers.director
        with patch.object(routers.director, "THUMBNAIL_OUTPUT_DIR", tmp_path):
            output_file = tmp_path / f"{task_id}.png"
            
            await agent.start(resolve_director_thumbnail_task)
            
            for _ in range(50):
                status = await agent.get_task_status(task_id)
                if status in ("COMPLETED", "FAILED"):
                    break
                await asyncio.sleep(0.05)
                
            final_status = await agent.get_task_status(task_id)
            await agent.stop()
            
            assert final_status == "COMPLETED"
            assert output_file.exists()
            
            # DBに保存された結果の検証
            import sqlite3
            conn = sqlite3.connect(str(db_file))
            try:
                cursor = conn.execute("SELECT status, result, retry_count FROM tasks WHERE id = ?", (task_id,))
                row = cursor.fetchone()
                assert row is not None
                status, result_str, retry_count = row
                assert status == "COMPLETED"
                
                result_data = json.loads(result_str)
                assert result_data["width"] == 1280
                assert result_data["height"] == 720
            finally:
                conn.close()
                
    asyncio.run(run_test())

