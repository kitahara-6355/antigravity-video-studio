try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _wp
except ImportError:
    from path_resolver import writable_path as _wp

import os
import io
import pytest
import sqlite3
import json
from unittest.mock import MagicMock, patch
from PIL import Image
from backend.agents.orchestration import mark_tasks_p27_refactor_b88

def test_verify_thumbnail_quality_invalid_input():
    with pytest.raises(TypeError, match="Invalid input type"):
        mark_tasks_p27_refactor_b88.verify_thumbnail_quality(123)

def test_verify_thumbnail_quality_not_found(tmp_path):
    non_existent = tmp_path / "non_existent.png"
    with pytest.raises(FileNotFoundError):
        mark_tasks_p27_refactor_b88.verify_thumbnail_quality(non_existent)

def test_verify_thumbnail_quality_corrupted_bytes():
    corrupted_bytes = b"not an image"
    with pytest.raises(ValueError, match="Image is corrupted"):
        mark_tasks_p27_refactor_b88.verify_thumbnail_quality(corrupted_bytes)

def test_verify_thumbnail_quality_corrupted_file(tmp_path):
    corrupted_file = tmp_path / "corrupted.png"
    corrupted_file.write_bytes(b"not an image")
    with pytest.raises(ValueError, match="Image is corrupted"):
        mark_tasks_p27_refactor_b88.verify_thumbnail_quality(corrupted_file)

def test_verify_thumbnail_quality_too_large(tmp_path):
    img = Image.new("RGB", (1280, 720), color="blue")
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="PNG")
    large_bytes = img_byte_arr.getvalue() + (b"\\x00" * 4 * 1024 * 1024)
    with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
        mark_tasks_p27_refactor_b88.verify_thumbnail_quality(large_bytes)

def test_verify_thumbnail_quality_low_resolution():
    img = Image.new("RGB", (640, 360), color="blue")
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="PNG")
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        mark_tasks_p27_refactor_b88.verify_thumbnail_quality(img_byte_arr.getvalue())

def test_verify_thumbnail_quality_invalid_aspect_ratio():
    img = Image.new("RGB", (1280, 1280), color="blue")
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        mark_tasks_p27_refactor_b88.verify_thumbnail_quality(img_byte_arr.getvalue())

def test_verify_thumbnail_quality_success():
    img = Image.new("RGB", (1280, 720), color="blue")
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="PNG")
    result = mark_tasks_p27_refactor_b88.verify_thumbnail_quality(img_byte_arr.getvalue())
    assert result["valid"] is True
    assert result["width"] == 1280
    assert result["height"] == 720

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_success(tmp_path):
    db_file = tmp_path / "test.db"
    task_id = "test_task_123"
    
    from pathlib import Path
    output_png = _wp("backend/temp_thumbnails") / f"{task_id}.png"
    
    try:
        with patch("backend.agents.orchestration.mark_tasks_p27_refactor_b88.emit_critical") as mock_emit_critical:
            result_str = await mark_tasks_p27_refactor_b88.run_thumbnail_stage_task(task_id, db_path=str(db_file))
            
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
    finally:
        if output_png.exists():
            output_png.unlink()

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_cleanup_on_error(tmp_path):
    db_file = tmp_path / "test.db"
    task_id = "test_task_cleanup_err"
    
    from pathlib import Path
    output_png = _wp("backend/temp_thumbnails") / f"{task_id}.png"
    
    with patch("backend.agents.orchestration.mark_tasks_p27_refactor_b88.verify_thumbnail_quality", side_effect=ValueError("Mocked validation error")):
        with pytest.raises(ValueError, match="Mocked validation error"):
            await mark_tasks_p27_refactor_b88.run_thumbnail_stage_task(task_id, db_path=str(db_file))
            
    # Windowsのファイル削除遅延対策として、最大1秒間待機する
    import time
    for _ in range(10):
        if not output_png.exists():
            break
        time.sleep(0.1)
        
    assert not output_png.exists()

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_validation_error(tmp_path):
    db_file = tmp_path / "test.db"
    task_id = "test_task_invalid"
    
    with patch("backend.agents.orchestration.mark_tasks_p27_refactor_b88.verify_thumbnail_quality", side_effect=ValueError("Mocked validation error")):
        with patch("backend.agents.orchestration.mark_tasks_p27_refactor_b88.emit_critical") as mock_emit_critical,              patch("backend.agents.orchestration.mark_tasks_p27_refactor_b88.register_technical_debt") as mock_register_debt:
            
            with pytest.raises(ValueError, match="Mocked validation error"):
                await mark_tasks_p27_refactor_b88.run_thumbnail_stage_task(task_id, db_path=str(db_file))
            
            mock_register_debt.assert_not_called()
            mock_emit_critical.assert_not_called()

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_db_error(tmp_path):
    db_file = tmp_path / "test.db"
    task_id = "test_task_db_err"
    
    with patch("sqlite3.connect", side_effect=sqlite3.Error("Mocked DB error")):
        with patch("backend.agents.orchestration.mark_tasks_p27_refactor_b88.emit_critical") as mock_emit_critical,              patch("backend.agents.orchestration.mark_tasks_p27_refactor_b88.register_technical_debt") as mock_register_debt:
            
            with pytest.raises(sqlite3.Error, match="Mocked DB error"):
                await mark_tasks_p27_refactor_b88.run_thumbnail_stage_task(task_id, db_path=str(db_file))
            
            mock_emit_critical.assert_any_call("thumbnail", "Database operation failed: Mocked DB error")
            mock_register_debt.assert_not_called()

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_unexpected_error(tmp_path):
    db_file = tmp_path / "test.db"
    task_id = "test_task_unexpected"
    
    with patch("PIL.Image.new", side_effect=AttributeError("Unexpected Pillow error")):
        with patch("backend.agents.orchestration.mark_tasks_p27_refactor_b88.emit_critical") as mock_emit_critical, \
             patch("backend.agents.orchestration.mark_tasks_p27_refactor_b88.register_technical_debt") as mock_register_debt:
            
            with pytest.raises(AttributeError, match="Unexpected Pillow error"):
                await mark_tasks_p27_refactor_b88.run_thumbnail_stage_task(task_id, db_path=str(db_file))
            
            mock_register_debt.assert_called_once()
            args, kwargs = mock_register_debt.call_args
            assert isinstance(kwargs["line_number"], int) and kwargs["line_number"] > 0
            assert kwargs["pattern"] == "except (TypeError, KeyError, AttributeError, IndexError, RuntimeError) as e:"
            assert "Unexpected Pillow error" in kwargs["notes"]
            mock_emit_critical.assert_called_once()

def test_main_success(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "FLASH_STATUS_OK"}
    
    with patch("backend.agents.orchestration.mark_tasks_p27_refactor_b88.OrchestrationHub", return_value=mock_hub_instance):
        with patch("sys.argv", ["script.py"]):
            mark_tasks_p27_refactor_b88.main()
        
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("d4ffa833-786b-4a2d-947a-1f0ae9624b60")
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    
    mock_hub_instance.mark_task_done.assert_called_once_with(
        "T-batch_b13ea7-bug_hunter-004",
        "pass",
        {
            "message": "mark_tasks_p27_refactor_b88.py の堅牢化（Pillowリソース漏れ防止、TDR連携、一時ファイル削除、例外ハンドリング強化など）およびテストの追加。",
            "changed_files": [
                "backend/agents/orchestration/mark_tasks_p27_refactor_b88.py",
                "tests/test_mark_tasks_p27_refactor_b88_root.py"
            ]
        }
    )
    
    captured = capsys.readouterr()
    assert "TASK_MARKED_DONE" in captured.out
    assert "FLASH_STATUS:{\"formatted\": \"FLASH_STATUS_OK\"}" in captured.out

def test_main_failure(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.mark_task_done.side_effect = AttributeError("Mocked main error")
    
    with patch("backend.agents.orchestration.mark_tasks_p27_refactor_b88.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.mark_tasks_p27_refactor_b88.register_technical_debt") as mock_register_debt:
            with patch("sys.argv", ["script.py"]):
                with pytest.raises(SystemExit) as excinfo:
                    mark_tasks_p27_refactor_b88.main()
            
            assert excinfo.value.code == 1
            mock_register_debt.assert_called_once()
            args, kwargs = mock_register_debt.call_args
            assert isinstance(kwargs["line_number"], int) and kwargs["line_number"] > 0
            assert kwargs["pattern"] == "except (KeyError, AttributeError, IndexError) as e:"
            assert "Mocked main error" in kwargs["notes"]
            
    captured = capsys.readouterr()
    assert "Attribute, index or key error during execution: Mocked main error" in captured.err

@pytest.mark.asyncio
async def test_sqlite_connect_failure_no_name_error():
    with patch("sqlite3.connect", side_effect=sqlite3.Error("Mocked Connection Refused")):
        with pytest.raises(sqlite3.Error, match="Mocked Connection Refused"):
            await mark_tasks_p27_refactor_b88.run_thumbnail_stage_task("task_conn_fail", db_path="invalid_path")

def test_cleanup_file_handles_os_error():
    with patch("pathlib.Path.exists", side_effect=OSError("Permission Denied")):
        mark_tasks_p27_refactor_b88._cleanup_file("some_locked_file.png")

def test_register_technical_debt_internal_errors(capsys):
    mock_store = MagicMock()
    mock_store.register_debt.side_effect = ValueError("Mocked store error")
    
    mark_tasks_p27_refactor_b88.register_technical_debt(
        line_number=10,
        pattern="test_pattern",
        notes="test_notes",
        _store=mock_store
    )
    
    captured = capsys.readouterr()
    assert "Failed to register technical debt: Mocked store error" in captured.err

def test_verify_thumbnail_quality_zero_width():
    mock_img = MagicMock()
    mock_img.size = (0, 720)
    mock_img.load.return_value = None
    
    mock_open = MagicMock()
    mock_open.__enter__.return_value = mock_img
    
    with patch("PIL.Image.open", return_value=mock_open):
        with pytest.raises(ValueError, match="Image width cannot be zero"):
            mark_tasks_p27_refactor_b88.verify_thumbnail_quality(b"fake_bytes")

def test_verify_thumbnail_quality_zero_height():
    mock_img = MagicMock()
    mock_img.size = (1280, 0)
    mock_img.load.return_value = None
    
    mock_open = MagicMock()
    mock_open.__enter__.return_value = mock_img
    
    with patch("PIL.Image.open", return_value=mock_open):
        with pytest.raises(ValueError, match="Image height cannot be zero"):
            mark_tasks_p27_refactor_b88.verify_thumbnail_quality(b"fake_bytes")

class PathLikeObject:
    def __init__(self, path):
        self.path = path
    def __fspath__(self):
        return str(self.path)

def test_verify_thumbnail_quality_path_like(tmp_path):
    img = Image.new("RGB", (1280, 720), color="blue")
    img_path = tmp_path / "test_path_like.png"
    img.save(img_path)
    
    path_like = PathLikeObject(img_path)
    result = mark_tasks_p27_refactor_b88.verify_thumbnail_quality(path_like)
    assert result["valid"] is True

def test_get_exception_line_edge_cases():
    # tb is None
    line = mark_tasks_p27_refactor_b88._get_exception_line(None, 42)
    assert line == 42

    # tb matches another file
    try:
        raise ValueError("test")
    except ValueError as e:
        tb = e.__traceback__
    
    line = mark_tasks_p27_refactor_b88._get_exception_line(tb, 99)
    assert line == 99

def test_cleanup_file_none():
    mark_tasks_p27_refactor_b88._cleanup_file(None)

def test_register_technical_debt_skips_infra_errors():
    mock_store = MagicMock()
    mark_tasks_p27_refactor_b88.register_technical_debt(
        line_number=10,
        pattern="pattern",
        notes="notes",
        exception=ConnectionError("conn error"),
        _store=mock_store
    )
    mock_store.register_debt.assert_not_called()

def test_register_technical_debt_store_none():
    mock_store_class = MagicMock()
    mock_store_instance = MagicMock()
    mock_store_class.return_value = mock_store_instance
    
    with patch("backend.agents.memory.technical_debt.TechnicalDebtStore", mock_store_class):
        mark_tasks_p27_refactor_b88.register_technical_debt(
            line_number=10,
            pattern="pattern",
            notes="notes",
            exception=ValueError("val error")
        )
    mock_store_class.assert_called_once()
    mock_store_instance.register_debt.assert_called_once()

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_os_error(tmp_path):
    db_file = tmp_path / "test.db"
    with patch("PIL.Image.new", side_effect=OSError("Pillow OS error")):
        with patch("backend.agents.orchestration.mark_tasks_p27_refactor_b88.emit_critical") as mock_emit_critical:
            with pytest.raises(OSError, match="Pillow OS error"):
                await mark_tasks_p27_refactor_b88.run_thumbnail_stage_task("task_os_err", db_path=str(db_file))
            mock_emit_critical.assert_called_once()

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_type_error(tmp_path):
    db_file = tmp_path / "test.db"
    with patch("PIL.Image.new", side_effect=TypeError("Pillow Type error")):
        with patch("backend.agents.orchestration.mark_tasks_p27_refactor_b88.emit_critical") as mock_emit_critical:
            with pytest.raises(TypeError, match="Pillow Type error"):
                await mark_tasks_p27_refactor_b88.run_thumbnail_stage_task("task_type_err", db_path=str(db_file))
            mock_emit_critical.assert_called_once()

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_key_error(tmp_path):
    db_file = tmp_path / "test.db"
    with patch("PIL.Image.new", side_effect=KeyError("Pillow Key error")):
        with patch("backend.agents.orchestration.mark_tasks_p27_refactor_b88.emit_critical") as mock_emit_critical:
            with pytest.raises(KeyError, match="Pillow Key error"):
                await mark_tasks_p27_refactor_b88.run_thumbnail_stage_task("task_key_err", db_path=str(db_file))
            mock_emit_critical.assert_called_once()

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_runtime_error(tmp_path):
    db_file = tmp_path / "test.db"
    with patch("PIL.Image.new", side_effect=RuntimeError("Pillow Runtime error")):
        with patch("backend.agents.orchestration.mark_tasks_p27_refactor_b88.emit_critical") as mock_emit_critical:
            with pytest.raises(RuntimeError, match="Pillow Runtime error"):
                await mark_tasks_p27_refactor_b88.run_thumbnail_stage_task("task_runtime_err", db_path=str(db_file))
            mock_emit_critical.assert_called_once()

def test_main_runtime_error(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.mark_task_done.side_effect = RuntimeError("Mocked runtime error")
    with patch("backend.agents.orchestration.mark_tasks_p27_refactor_b88.OrchestrationHub", return_value=mock_hub_instance):
        with patch("sys.argv", ["script.py"]):
            with pytest.raises(SystemExit) as excinfo:
                mark_tasks_p27_refactor_b88.main()
        assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Runtime execution failed: Mocked runtime error" in captured.err

def test_main_type_error(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.mark_task_done.side_effect = TypeError("Mocked type error")
    with patch("backend.agents.orchestration.mark_tasks_p27_refactor_b88.OrchestrationHub", return_value=mock_hub_instance):
        with patch("sys.argv", ["script.py"]):
            with pytest.raises(SystemExit) as excinfo:
                mark_tasks_p27_refactor_b88.main()
        assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Serialization failed: Mocked type error" in captured.err

def test_main_custom_task_id_env():
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {}
    with patch("backend.agents.orchestration.mark_tasks_p27_refactor_b88.OrchestrationHub", return_value=mock_hub_instance):
        with patch.dict(os.environ, {"TASK_ID": "T-custom-env-123"}):
            with patch("sys.argv", ["script.py"]):
                mark_tasks_p27_refactor_b88.main()
    args, kwargs = mock_hub_instance.mark_task_done.call_args
    assert args[0] == "T-custom-env-123"

def test_main_custom_task_id_argv():
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {}
    with patch("backend.agents.orchestration.mark_tasks_p27_refactor_b88.OrchestrationHub", return_value=mock_hub_instance):
        with patch("sys.argv", ["script.py", "T-custom-argv-456"]):
            mark_tasks_p27_refactor_b88.main()
    args, kwargs = mock_hub_instance.mark_task_done.call_args
    assert args[0] == "T-custom-argv-456"


def test_main_value_error(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.mark_task_done.side_effect = ValueError("Mocked value error")
    
    with patch("backend.agents.orchestration.mark_tasks_p27_refactor_b88.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.mark_tasks_p27_refactor_b88.register_technical_debt") as mock_register_debt:
            with patch("sys.argv", ["script.py"]):
                with pytest.raises(SystemExit) as excinfo:
                    mark_tasks_p27_refactor_b88.main()
            
            assert excinfo.value.code == 1
            mock_register_debt.assert_called_once()
            args, kwargs = mock_register_debt.call_args
            assert isinstance(kwargs["line_number"], int) and kwargs["line_number"] > 0
            assert kwargs["pattern"] == "except ValueError as e:"
            assert "Mocked value error" in kwargs["notes"]
            
    captured = capsys.readouterr()
    assert "ValueError during execution: Mocked value error" in captured.err


def test_main_os_error(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.mark_task_done.side_effect = OSError("Mocked OS error")
    
    with patch("backend.agents.orchestration.mark_tasks_p27_refactor_b88.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.mark_tasks_p27_refactor_b88.register_technical_debt") as mock_register_debt:
            with patch("sys.argv", ["script.py"]):
                with pytest.raises(SystemExit) as excinfo:
                    mark_tasks_p27_refactor_b88.main()
            
            assert excinfo.value.code == 1
            # OSErrorはTDR登録が不要（またはスキップされる）ため呼ばれない
            mock_register_debt.assert_not_called()
            
    captured = capsys.readouterr()
    assert "OS error during execution: Mocked OS error" in captured.err


@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_type_error_tdr(tmp_path):
    db_file = tmp_path / "test.db"
    task_id = "test_task_type_error_tdr"
    
    with patch("PIL.Image.new", side_effect=TypeError("Unexpected Type error")):
        with patch("backend.agents.orchestration.mark_tasks_p27_refactor_b88.emit_critical") as mock_emit_critical, \
             patch("backend.agents.orchestration.mark_tasks_p27_refactor_b88.register_technical_debt") as mock_register_debt:
            
            with pytest.raises(TypeError, match="Unexpected Type error"):
                await mark_tasks_p27_refactor_b88.run_thumbnail_stage_task(task_id, db_path=str(db_file))
            
            mock_register_debt.assert_called_once()
            args, kwargs = mock_register_debt.call_args
            assert isinstance(kwargs["line_number"], int) and kwargs["line_number"] > 0
            assert kwargs["pattern"] == "except (TypeError, KeyError, AttributeError, IndexError, RuntimeError) as e:"
            assert "Unexpected Type error" in kwargs["notes"]
            mock_emit_critical.assert_called_once()


