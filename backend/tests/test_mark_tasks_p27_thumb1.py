# -*- coding: utf-8 -*-
import sys
import os
import io
import json
import sqlite3
import asyncio
import time
import pytest
from pathlib import Path
from PIL import Image
from unittest.mock import patch, MagicMock

# backend ディレクトリを sys.path に追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from agents.orchestration.mark_tasks_p27_thumb1 import (
    verify_thumbnail_quality,
    run_thumbnail_stage_task
)
from agents.stage_bound_agent import StageBoundAgent
from usage_tracker.alert_system import emit_warning, emit_critical

@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_stage_thumb1.db"
    return str(db_file)

@pytest.fixture
def valid_image_bytes():
    # 1280x720, 16:9 の正常な画像をメモリ上に生成
    with Image.new("RGB", (1280, 720), color=(100, 100, 100)) as img:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

def test_verify_thumbnail_quality_success(valid_image_bytes):
    """正常系: 1280x720, 16:9, 小サイズで正常ロード可能なバイト列"""
    res = verify_thumbnail_quality(valid_image_bytes)
    assert res["valid"] is True
    assert res["width"] == 1280
    assert res["height"] == 720

def test_verify_thumbnail_quality_file_success(tmp_path):
    """正常系: ファイルパス指定"""
    with Image.new("RGB", (1920, 1080), color=(100, 100, 100)) as img:
        path = tmp_path / "valid_image.png"
        img.save(path, format="PNG")
    
    res = verify_thumbnail_quality(path)
    assert res["valid"] is True
    assert res["width"] == 1920
    assert res["height"] == 1080

def test_verify_thumbnail_quality_corrupted():
    """異常系: 破損したバイト列"""
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        verify_thumbnail_quality(b"invalid corrupted bytes")

def test_verify_thumbnail_quality_file_not_found():
    """異常系: 存在しないファイルパス"""
    with pytest.raises(FileNotFoundError, match="Thumbnail file not found"):
        verify_thumbnail_quality("non_existent_file_path_123.jpg")

def test_verify_thumbnail_quality_resolution_fail(tmp_path):
    """異常系: 低解像度 (1280x720 未満)"""
    with Image.new("RGB", (1000, 562), color=(100, 100, 100)) as img: # 約16:9だが低解像度
        path = tmp_path / "low_res.png"
        img.save(path, format="PNG")
    
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        verify_thumbnail_quality(path)

def test_verify_thumbnail_quality_aspect_ratio_fail(tmp_path):
    """異常系: アスペクト比が 16:9 ではない"""
    with Image.new("RGB", (1280, 1000), color=(100, 100, 100)) as img: # 1280x720以上だが比率が違う
        path = tmp_path / "wrong_aspect.png"
        img.save(path, format="PNG")
    
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        verify_thumbnail_quality(path)

def test_verify_thumbnail_quality_size_fail(tmp_path):
    """異常系: ファイルサイズが 4MB 以上"""
    with Image.new("RGB", (1280, 720), color=(100, 100, 100)) as img:
        path = tmp_path / "large_file.png"
        img.save(path, format="PNG")
    
    with patch("pathlib.Path.stat") as mock_stat:
        mock_meta = MagicMock()
        mock_meta.st_size = 4 * 1024 * 1024 + 10  # 4MB超
        mock_stat.return_value = mock_meta
        
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            verify_thumbnail_quality(path)

def test_verify_thumbnail_quality_os_error(tmp_path):
    """異常系: Image.open で OSError が発生した場合の検証 (カバレッジ追加)"""
    path = tmp_path / "test_os_error.png"
    # 空ファイルを作成して Image.open(path) が OSError を投げるようにする
    path.touch()
    
    with patch("PIL.Image.open", side_effect=OSError("Mock OS Error")):
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            verify_thumbnail_quality(path)

def test_verify_thumbnail_quality_size_get_fail(tmp_path):
    """異常系: 画像のロードは成功するが、img.size 取得で OSError が発生した場合の検証 (カバレッジ追加)"""
    with Image.new("RGB", (1280, 720), color=(100, 100, 100)) as img:
        path = tmp_path / "size_fail.png"
        img.save(path, format="PNG")
    
    # img.size アクセス時に OSError を発生させるために、Image オブジェクトをモック
    mock_img = MagicMock()
    # size プロパティにアクセスした際に OSError を投げるプロパティモック
    type(mock_img).size = property(lambda self: (_ for _ in ()).throw(OSError("Size OS Error")))
    mock_img.__enter__.return_value = mock_img
    mock_img.__exit__.return_value = False

    with patch("PIL.Image.open", return_value=mock_img):
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            verify_thumbnail_quality(path)

@pytest.mark.anyio
async def test_run_thumbnail_stage_task_success(temp_db):
    """run_thumbnail_stage_task が正常終了し、DBに結果が正しく書き込まれ、プレミアム品質画像が生成されることを検証"""
    res_str = await run_thumbnail_stage_task("task_thumb1_001", db_path=temp_db)
    res = json.loads(res_str)
    assert res["valid"] is True
    assert res["width"] == 1280
    assert res["height"] == 720
    
    # 生成された画像の存在と内容の検証 (対角グラデーション背景)
    project_root = Path(__file__).resolve().parents[2]
    image_path = project_root / "temp_thumbnails" / "task_thumb1_001.png"
    assert image_path.exists()
    
    with Image.open(image_path) as img:
        # 斜めグラデーションのため、左上・右上・左下のピクセル色がそれぞれ異なるか検証
        color_tl = img.getpixel((10, 10))
        color_tr = img.getpixel((1270, 10))
        color_bl = img.getpixel((10, 710))
        assert color_tl != color_tr
        assert color_tl != color_bl
    
    # DB連携と結果保存の検証
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM thumbnail_results WHERE task_id = 'task_thumb1_001'")
    row = cursor.fetchone()
    assert row is not None
    assert "task_thumb1_001" in row[0]
    assert 1280 == row[2]
    assert 720 == row[3]
    conn.close()

@pytest.mark.anyio
async def test_run_thumbnail_stage_task_failure(temp_db):
    """品質検証で失敗した際、emit_critical が呼ばれ例外が送出されることを検証"""
    with patch("agents.orchestration.mark_tasks_p27_thumb1.verify_thumbnail_quality", side_effect=ValueError("Mock Quality Error")), \
         patch("agents.orchestration.mark_tasks_p27_thumb1.emit_critical") as mock_emit_critical:
          
          with pytest.raises(ValueError, match="Mock Quality Error"):
              await run_thumbnail_stage_task("task_fail", db_path=temp_db)
          
          mock_emit_critical.assert_called_once_with("thumbnail", "Thumbnail task failed for task task_fail: Mock Quality Error")

@pytest.mark.anyio
async def test_stage_bound_agent_integration(temp_db):
    """StageBoundAgent にタスクを登録して自動リトライが動作することを検証"""
    agent = StageBoundAgent(
        stage_name="thumbnail",
        db_path=temp_db,
        poll_interval=0.01
    )
    
    await agent.register_task("task_retry_test", initial_status="READY", max_retries=2)
    
    call_count = 0
    async def mock_process(task_id):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ValueError(f"Temporary Error {call_count}")
        return "SUCCESS_DATA"

    await agent.start(mock_process)
    
    start_time = time.time()
    while time.time() - start_time < 3.0:
        status = await agent.get_task_status("task_retry_test")
        if status == "COMPLETED":
            break
        await asyncio.sleep(0.05)
        
    await agent.stop()
    
    assert call_count == 3
    status = await agent.get_task_status("task_retry_test")
    assert status == "COMPLETED"
    
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("SELECT * FROM tasks WHERE id = 'task_retry_test'")
    row = dict(cursor.fetchone())
    assert row["retry_count"] == 2
    assert row["result"] == "SUCCESS_DATA"
    conn.close()


def test_verify_thumbnail_quality_truncated_file(tmp_path):
    """異常系: ファイルは存在するが画像データが途中で切れている（部分破損）"""
    path = tmp_path / "truncated.png"
    # PNGのシグネチャとIHDRチャンクだけ書き込み、画像データは書き込まない
    path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 30)
    
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        verify_thumbnail_quality(path)


def test_verify_thumbnail_quality_bytes_os_error():
    """異常系: bytes で Image.open もしくは img.load で OSError が発生した場合の検証"""
    with patch("PIL.Image.open", side_effect=OSError("Mock Bytes OS Error")):
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            verify_thumbnail_quality(b"some bytes")


@pytest.mark.anyio
async def test_run_thumbnail_stage_task_unhandled_failure(temp_db):
    """キャッチ対象外の例外（KeyErrorなど）が発生した際、emit_critical が呼ばれずに例外がそのまま送出されることを検証"""
    with patch("agents.orchestration.mark_tasks_p27_thumb1.verify_thumbnail_quality", side_effect=KeyError("Mock Generic Error")), \
         patch("agents.orchestration.mark_tasks_p27_thumb1.emit_critical") as mock_emit_critical:
          
          with pytest.raises(KeyError, match="Mock Generic Error"):
              await run_thumbnail_stage_task("task_fail_generic", db_path=temp_db)
          
          mock_emit_critical.assert_not_called()

@pytest.mark.anyio
async def test_run_thumbnail_stage_task_sqlite_failure(temp_db):
    """sqlite3.Error が発生した際、emit_critical が呼ばれ例外が再送出されることを検証"""
    with patch("sqlite3.connect", side_effect=sqlite3.Error("Mock DB Error")), \
         patch("agents.orchestration.mark_tasks_p27_thumb1.emit_critical") as mock_emit_critical:
          
          with pytest.raises(sqlite3.Error, match="Mock DB Error"):
              await run_thumbnail_stage_task("task_fail_db", db_path=temp_db)
          
          mock_emit_critical.assert_called_once_with("thumbnail", "Thumbnail task failed for task task_fail_db: Mock DB Error")

@pytest.mark.anyio
async def test_run_thumbnail_stage_task_os_error_failure(temp_db):
    """OSError が発生した際、emit_critical が呼ばれ例外が再送出されることを検証"""
    with patch("agents.orchestration.mark_tasks_p27_thumb1.verify_thumbnail_quality", side_effect=OSError("Mock OS Error")), \
         patch("agents.orchestration.mark_tasks_p27_thumb1.emit_critical") as mock_emit_critical:
          
          with pytest.raises(OSError, match="Mock OS Error"):
              await run_thumbnail_stage_task("task_fail_os", db_path=temp_db)
          
          mock_emit_critical.assert_called_once_with("thumbnail", "Thumbnail task failed for task task_fail_os: Mock OS Error")

def test_verify_thumbnail_quality_invalid_type():
    """異常系: 引数に bytes, str, Path 以外の無効な型を渡した場合に TypeError が発生することを検証 (カバレッジ向上)"""
    with pytest.raises(TypeError, match="Invalid argument type"):
        verify_thumbnail_quality(12345)
