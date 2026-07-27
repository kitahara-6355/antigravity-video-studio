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
from PIL import Image, ImageDraw
from unittest.mock import patch, MagicMock

# backend ディレクトリを sys.path に追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from agents.orchestration.mark_tasks_p27_refactor_b88 import (
    verify_thumbnail_quality,
    run_thumbnail_stage_task
)
from agents.stage_bound_agent import StageBoundAgent

@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_stage.db"
    return str(db_file)

@pytest.fixture
def valid_image_bytes():
    # 1280x720, 16:9 の正常な画像をメモリ上に生成
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
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
    img = Image.new("RGB", (1920, 1080), color=(100, 100, 100))
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
    img = Image.new("RGB", (1000, 562), color=(100, 100, 100)) # 約16:9だが低解像度
    path = tmp_path / "low_res.png"
    img.save(path, format="PNG")
    
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        verify_thumbnail_quality(path)

def test_verify_thumbnail_quality_aspect_ratio_fail(tmp_path):
    """異常系: アスペクト比が 16:9 ではない"""
    img = Image.new("RGB", (1280, 1000), color=(100, 100, 100)) # 1280x720以上だが比率が違う
    path = tmp_path / "wrong_aspect.png"
    img.save(path, format="PNG")
    
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        verify_thumbnail_quality(path)

def test_verify_thumbnail_quality_size_fail(tmp_path):
    """異常系: ファイルサイズが 4MB 以上"""
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    path = tmp_path / "large_file.png"
    img.save(path, format="PNG")
    
    with patch("pathlib.Path.stat") as mock_stat:
        mock_meta = MagicMock()
        mock_meta.st_size = 4 * 1024 * 1024 + 10  # 4MB超
        mock_stat.return_value = mock_meta
        
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            verify_thumbnail_quality(path)

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_success(temp_db):
    """run_thumbnail_stage_task が正常終了し、DBに結果が正しく書き込まれることを検証"""
    res_str = await run_thumbnail_stage_task("task_001", db_path=temp_db)
    res = json.loads(res_str)
    assert res["valid"] is True
    assert res["width"] == 1280
    assert res["height"] == 720
    
    # DB連携と結果保存の検証
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM thumbnail_results WHERE task_id = 'task_001'")
    row = cursor.fetchone()
    assert row is not None
    assert "task_001" in row[0]
    assert 1280 == row[2]
    assert 720 == row[3]
    conn.close()

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_failure(temp_db):
    """品質検証でシステムエラーが発生した際、emit_critical が呼ばれ例外が送出されることを検証"""
    with patch("agents.orchestration.mark_tasks_p27_refactor_b88.verify_thumbnail_quality", side_effect=OSError("Mock OS Error")), \
         patch("agents.orchestration.mark_tasks_p27_refactor_b88.emit_critical") as mock_emit_critical:
         
         with pytest.raises(OSError, match="Mock OS Error"):
             await run_thumbnail_stage_task("task_fail", db_path=temp_db)
         
         mock_emit_critical.assert_called_once_with("thumbnail", "Thumbnail task failed for task task_fail: Mock OS Error")

@pytest.mark.asyncio
async def test_stage_bound_agent_integration(temp_db):
    """StageBoundAgent にタスクを登録して自動リトライが動作することを検証"""
    agent = StageBoundAgent(
        stage_name="thumbnail",
        db_path=temp_db,
        poll_interval=0.01
    )
    
    # READYタスクを登録 (max_retries=2)
    await agent.register_task("task_retry_test", initial_status="READY", max_retries=2)
    
    # 最初の2回失敗し、3回目で成功するようなモック
    call_count = 0
    async def mock_process(task_id):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ValueError(f"Temporary Error {call_count}")
        return "SUCCESS_DATA"

    # エージェント開始
    await agent.start(mock_process)
    
    # 完了するかタイムアウトするまで待機
    start_time = time.time()
    while time.time() - start_time < 3.0:
        status = await agent.get_task_status("task_retry_test")
        if status == "COMPLETED":
            break
        await asyncio.sleep(0.05)
        
    await agent.stop()
    
    # 3回目でCOMPLETEDになったことを確認
    assert call_count == 3
    status = await agent.get_task_status("task_retry_test")
    assert status == "COMPLETED"
    
    # 最終的な結果の取得
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("SELECT * FROM tasks WHERE id = 'task_retry_test'")
    row = dict(cursor.fetchone())
    assert row["retry_count"] == 2
    assert row["result"] == "SUCCESS_DATA"
    conn.close()

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_unexpected_exception_registration(temp_db):
    """正常系/異常系: 予期せぬ例外（NameError等）が発生した際、TDRに登録され、かつ emit_critical が呼ばれることを検証"""
    with patch("agents.orchestration.mark_tasks_p27_refactor_b88.verify_thumbnail_quality", side_effect=NameError("Mock NameError")), \
         patch("agents.orchestration.mark_tasks_p27_refactor_b88.emit_critical") as mock_emit_critical, \
         patch("agents.orchestration.mark_tasks_p27_refactor_b88.register_technical_debt") as mock_register_debt:
         
         with pytest.raises(NameError, match="Mock NameError"):
             await run_thumbnail_stage_task("task_unexpected_err", db_path=temp_db)
         
         mock_emit_critical.assert_called_once_with(
             "thumbnail",
             "Thumbnail task failed for task task_unexpected_err: Mock NameError"
         )
         mock_register_debt.assert_called_once()
         args, kwargs = mock_register_debt.call_args
         assert kwargs["pattern"] == "except Exception as e:"
         assert "Mock NameError" in kwargs["notes"]

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_type_error_registration(temp_db):
    """異常系: TypeError が発生した際、except Exception でキャッチされ、TDRに登録され、かつ emit_critical が呼ばれることを検証"""
    with patch("agents.orchestration.mark_tasks_p27_refactor_b88.verify_thumbnail_quality", side_effect=TypeError("Mock TypeError")), \
         patch("agents.orchestration.mark_tasks_p27_refactor_b88.emit_critical") as mock_emit_critical, \
         patch("agents.orchestration.mark_tasks_p27_refactor_b88.register_technical_debt") as mock_register_debt:
         
         with pytest.raises(TypeError, match="Mock TypeError"):
             await run_thumbnail_stage_task("task_type_err", db_path=temp_db)
         
         mock_emit_critical.assert_called_once_with(
             "thumbnail",
             "Thumbnail task failed for task task_type_err: Mock TypeError"
         )
         mock_register_debt.assert_called_once()
         args, kwargs = mock_register_debt.call_args
         assert kwargs["pattern"] == "except Exception as e:"
         assert "Mock TypeError" in kwargs["notes"]

def test_main_unexpected_exception_handling():
    """main() で予期せぬ例外が発生した際、except Exception でキャッチされ、TDR登録されて sys.exit(1) になることを検証"""
    from agents.orchestration.mark_tasks_p27_refactor_b88 import main
    
    with patch("agents.orchestration.mark_tasks_p27_refactor_b88.OrchestrationHub", side_effect=ZeroDivisionError("Mock ZeroDivisionError")), \
         patch("agents.orchestration.mark_tasks_p27_refactor_b88.register_technical_debt") as mock_register_debt, \
         pytest.raises(SystemExit) as excinfo:
         
         main()
         
    assert excinfo.value.code == 1
    mock_register_debt.assert_called_once()
    args, kwargs = mock_register_debt.call_args
    assert kwargs["pattern"] == "except Exception as e:"
    assert "Mock ZeroDivisionError" in kwargs["notes"]
