import os
import io
import pytest
import sqlite3
import json
from unittest.mock import MagicMock, patch
from PIL import Image
from backend.agents.orchestration import mark_tasks_p27_bug_hunter_b88

def test_verify_thumbnail_quality_invalid_input():
    with pytest.raises(ValueError, match="Invalid input type"):
        mark_tasks_p27_bug_hunter_b88.verify_thumbnail_quality(123)

def test_verify_thumbnail_quality_not_found(tmp_path):
    non_existent = tmp_path / "non_existent.png"
    with pytest.raises(FileNotFoundError):
        mark_tasks_p27_bug_hunter_b88.verify_thumbnail_quality(non_existent)

def test_verify_thumbnail_quality_corrupted_bytes():
    corrupted_bytes = b"not an image"
    with pytest.raises(ValueError, match="Image is corrupted"):
        mark_tasks_p27_bug_hunter_b88.verify_thumbnail_quality(corrupted_bytes)

def test_verify_thumbnail_quality_corrupted_file(tmp_path):
    corrupted_file = tmp_path / "corrupted.png"
    corrupted_file.write_bytes(b"not an image")
    with pytest.raises(ValueError, match="Image is corrupted"):
        mark_tasks_p27_bug_hunter_b88.verify_thumbnail_quality(corrupted_file)

def test_verify_thumbnail_quality_too_large(tmp_path):
    img = Image.new("RGB", (1280, 720), color="blue")
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="PNG")
    large_bytes = img_byte_arr.getvalue() + (b"\x00" * 4 * 1024 * 1024)
    with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
        mark_tasks_p27_bug_hunter_b88.verify_thumbnail_quality(large_bytes)

def test_verify_thumbnail_quality_low_resolution():
    img = Image.new("RGB", (640, 360), color="blue")
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="PNG")
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        mark_tasks_p27_bug_hunter_b88.verify_thumbnail_quality(img_byte_arr.getvalue())

def test_verify_thumbnail_quality_invalid_aspect_ratio():
    img = Image.new("RGB", (1280, 1280), color="blue")
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        mark_tasks_p27_bug_hunter_b88.verify_thumbnail_quality(img_byte_arr.getvalue())

def test_verify_thumbnail_quality_success():
    img = Image.new("RGB", (1280, 720), color="blue")
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="PNG")
    result = mark_tasks_p27_bug_hunter_b88.verify_thumbnail_quality(img_byte_arr.getvalue())
    assert result["valid"] is True
    assert result["width"] == 1280
    assert result["height"] == 720

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_success(tmp_path):
    db_file = tmp_path / "test.db"
    task_id = "test_task_123"
    
    with patch("backend.agents.orchestration.mark_tasks_p27_bug_hunter_b88.emit_critical") as mock_emit_critical:
        result_str = await mark_tasks_p27_bug_hunter_b88.run_thumbnail_stage_task(task_id, db_path=str(db_file))
        
        # 結果の検証
        result = json.loads(result_str)
        assert result["valid"] is True
        assert result["width"] == 1280
        assert result["height"] == 720
        
        # DBの検証
        conn = sqlite3.connect(str(db_file))
        cursor = conn.cursor()
        cursor.execute("SELECT task_id, path, width, height FROM thumbnail_results WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == task_id
        assert row[2] == 1280
        assert row[3] == 720
        conn.close()
        
        mock_emit_critical.assert_not_called()

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_validation_error(tmp_path):
    db_file = tmp_path / "test.db"
    task_id = "test_task_invalid"
    
    with patch("backend.agents.orchestration.mark_tasks_p27_bug_hunter_b88.verify_thumbnail_quality", side_effect=ValueError("Mocked validation error")):
        with patch("backend.agents.orchestration.mark_tasks_p27_bug_hunter_b88.emit_critical") as mock_emit_critical, \
             patch("backend.agents.orchestration.mark_tasks_p27_bug_hunter_b88.register_technical_debt") as mock_register_debt:
            
            with pytest.raises(ValueError, match="Mocked validation error"):
                await mark_tasks_p27_bug_hunter_b88.run_thumbnail_stage_task(task_id, db_path=str(db_file))
            
            # エラーハンドリングの改善により、ValueError のときは register_debt も emit_critical も呼ばれない
            mock_register_debt.assert_not_called()
            mock_emit_critical.assert_not_called()

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_db_error(tmp_path):
    db_file = tmp_path / "test.db"
    task_id = "test_task_db_err"
    
    with patch("sqlite3.connect", side_effect=sqlite3.Error("Mocked DB error")):
        with patch("backend.agents.orchestration.mark_tasks_p27_bug_hunter_b88.emit_critical") as mock_emit_critical, \
             patch("backend.agents.orchestration.mark_tasks_p27_bug_hunter_b88.register_technical_debt") as mock_register_debt:
            
            with pytest.raises(sqlite3.Error, match="Mocked DB error"):
                await mark_tasks_p27_bug_hunter_b88.run_thumbnail_stage_task(task_id, db_path=str(db_file))
            
            # sqlite3.Error による DB操作エラー用の emit_critical は呼ばれる
            mock_emit_critical.assert_any_call("thumbnail", "Database operation failed: Mocked DB error")
            # ただし、外側の except Exception には捕まらないため、register_debt は呼ばれない
            mock_register_debt.assert_not_called()

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_unexpected_error(tmp_path):
    db_file = tmp_path / "test.db"
    task_id = "test_task_unexpected"
    
    with patch("PIL.Image.new", side_effect=AttributeError("Unexpected Pillow error")):
        with patch("backend.agents.orchestration.mark_tasks_p27_bug_hunter_b88.emit_critical") as mock_emit_critical, \
             patch("backend.agents.orchestration.mark_tasks_p27_bug_hunter_b88.register_technical_debt") as mock_register_debt:
            
            with pytest.raises(AttributeError, match="Unexpected Pillow error"):
                await mark_tasks_p27_bug_hunter_b88.run_thumbnail_stage_task(task_id, db_path=str(db_file))
            
            # 予期せぬエラーなので、技術負債登録と emit_critical が呼ばれる
            mock_register_debt.assert_called_once()
            args, kwargs = mock_register_debt.call_args
            assert isinstance(kwargs["line_number"], int) and kwargs["line_number"] > 0
            assert kwargs["pattern"] == "except Exception as e:"
            assert "Unexpected Pillow error" in kwargs["notes"]
            mock_emit_critical.assert_called_once()

def test_main_success(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "FLASH_STATUS_OK"}
    
    with patch("backend.agents.orchestration.mark_tasks_p27_bug_hunter_b88.OrchestrationHub", return_value=mock_hub_instance):
        mark_tasks_p27_bug_hunter_b88.main()
        
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("c31cf144-1cbf-4278-a5dd-7155df0da84c")
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    
    mock_hub_instance.mark_task_done.assert_called_once_with(
        "T-batch_773817-bug_hunter-004",
        "pass",
        {
            "message": "mark_tasks_p27_bug_hunter_b88.py のエラーハンドリング強化、例外処理の改善、テストの追加、およびタスクIDの更新。",
            "changed_files": [
                "backend/agents/orchestration/mark_tasks_p27_bug_hunter_b88.py",
                "backend/tests/test_mark_tasks_p27_bug_hunter_b88.py",
                "tests/test_mark_tasks_p27_bug_hunter_b88_root.py"
            ]
        }
    )
    
    captured = capsys.readouterr()
    assert "TASK_MARKED_DONE" in captured.out
    assert "FLASH_STATUS:{\"formatted\": \"FLASH_STATUS_OK\"}" in captured.out

def test_main_failure(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.mark_task_done.side_effect = AttributeError("Mocked main error")
    
    with patch("backend.agents.orchestration.mark_tasks_p27_bug_hunter_b88.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.mark_tasks_p27_bug_hunter_b88.register_technical_debt") as mock_register_debt:
            with pytest.raises(SystemExit) as excinfo:
                mark_tasks_p27_bug_hunter_b88.main()
            
            assert excinfo.value.code == 1
            mock_register_debt.assert_called_once()
            args, kwargs = mock_register_debt.call_args
            assert isinstance(kwargs["line_number"], int) and kwargs["line_number"] > 0
            assert kwargs["pattern"] == "except Exception as e:"
            assert "Mocked main error" in kwargs["notes"]
            
    captured = capsys.readouterr()
    assert "Unexpected execution failed: Mocked main error" in captured.err

@pytest.mark.asyncio
async def test_sqlite_connect_failure_no_name_error():
    with patch("sqlite3.connect", side_effect=sqlite3.Error("Mocked Connection Refused")):
        with pytest.raises(sqlite3.Error, match="Mocked Connection Refused"):
            await mark_tasks_p27_bug_hunter_b88.run_thumbnail_stage_task("task_conn_fail", db_path="invalid_path")

def test_cleanup_file_handles_os_error():
    with patch("pathlib.Path.exists", side_effect=OSError("Permission Denied")):
        try:
            mark_tasks_p27_bug_hunter_b88._cleanup_file("some_locked_file.png")
        except Exception as e:
            pytest.fail(f"_cleanup_file raised an unexpected exception: {e}")
