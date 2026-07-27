import json
import subprocess
from pathlib import Path
import pathlib
import pytest
from unittest.mock import MagicMock, patch
from PIL import Image
import runpy
import os
import sys

# プロジェクトルートをパスに追加
backend_dir = Path(__file__).resolve().parents[1] / 'backend'
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.gcp_cost_monitor import (
    _get_nested_value,
    check_gcp_costs,
    generate_gcp_cost_report_thumbnail,
    validate_thumbnail,
    resolve_gcp_cost_monitor_task,
)

# 1. _get_nested_value 関数のテスト
def test_get_nested_value():
    d = {"a": {"b": {"c": 1}}}
    assert _get_nested_value(d, "a", "b", "c") == 1
    assert _get_nested_value(d, "a", "b", "d") == "N/A"
    assert _get_nested_value(d, "a", "b", "d", default="Fallback") == "Fallback"
    assert _get_nested_value(d, "x") == "N/A"
    assert _get_nested_value(None, "a") == "N/A"
    d_none = {"a": None}
    assert _get_nested_value(d_none, "a") == "N/A"
    d_str = {"a": "string"}
    assert _get_nested_value(d_str, "a", "b") == "N/A"

# 2. check_gcp_costs 関数のテスト
@patch("backend.gcp_cost_monitor.subprocess.run")
def test_check_gcp_costs_success(mock_run):
    # 正常系: プロジェクトあり、Cloud Runサービスあり/なし、N/Aプロジェクトのスキップ
    mock_proj_stdout = '[{"projectId": "proj-1", "name": "Project One"}, {"projectId": "N/A", "name": "N/A Proj"}, {"name": "No ID Proj"}, {"projectId": "proj-2", "name": "Project Two"}]'
    mock_run_stdout_1 = '[{"metadata": {"name": "run-service", "labels": {"cloud.googleapis.com/location": "us-central1"}, "creationTimestamp": "2026-05-30T00:00:00Z"}}]'
    mock_run_stdout_2 = '[]'
    
    mock_run.side_effect = [
        MagicMock(stdout=mock_proj_stdout),
        MagicMock(stdout=mock_run_stdout_1),
        MagicMock(stdout=mock_run_stdout_2)
    ]
    
    res = check_gcp_costs()
    assert res is not None
    assert "timestamp" in res
    assert res["projects"] == ["proj-1", "proj-2"]

@patch("backend.gcp_cost_monitor.subprocess.run")
def test_check_gcp_costs_no_projects(mock_run):
    mock_proj_stdout = '[]'
    mock_run.return_value = MagicMock(stdout=mock_proj_stdout)
    res = check_gcp_costs()
    assert res is None

@patch("backend.gcp_cost_monitor.subprocess.run")
def test_check_gcp_costs_proj_json_error(mock_run):
    mock_proj_stdout = 'invalid json'
    mock_run.return_value = MagicMock(stdout=mock_proj_stdout)
    res = check_gcp_costs()
    assert res is None

@patch("backend.gcp_cost_monitor.subprocess.run")
def test_check_gcp_costs_proj_called_process_error(mock_run):
    mock_run.side_effect = subprocess.CalledProcessError(1, ["gcloud", "projects", "list"])
    res = check_gcp_costs()
    assert res is None

@patch("backend.gcp_cost_monitor.subprocess.run")
def test_check_gcp_costs_run_json_error(mock_run):
    mock_proj_stdout = '[{"projectId": "proj-1", "name": "Project One"}]'
    mock_run.side_effect = [
        MagicMock(stdout=mock_proj_stdout),
        MagicMock(stdout="invalid json")
    ]
    res = check_gcp_costs()
    assert res is not None
    assert res["projects"] == ["proj-1"]

@patch("backend.gcp_cost_monitor.subprocess.run")
def test_check_gcp_costs_run_called_process_error(mock_run):
    mock_proj_stdout = '[{"projectId": "proj-1", "name": "Project One"}]'
    mock_run.side_effect = [
        MagicMock(stdout=mock_proj_stdout),
        subprocess.CalledProcessError(1, ["gcloud", "run", "services", "list"])
    ]
    res = check_gcp_costs()
    assert res is not None
    assert res["projects"] == ["proj-1"]

# 3. generate_gcp_cost_report_thumbnail 関数のテスト
def test_generate_gcp_cost_report_thumbnail_success(tmp_path):
    output_file = tmp_path / "thumb.png"
    res_path = generate_gcp_cost_report_thumbnail(output_file)
    assert res_path == output_file
    assert output_file.exists()
    res_path_overwrite = generate_gcp_cost_report_thumbnail(output_file, text="Custom Text")
    assert res_path_overwrite == output_file
    assert output_file.exists()

def test_generate_gcp_cost_report_thumbnail_invalid_size():
    with pytest.raises(ValueError, match="Width and height must be integers"):
        generate_gcp_cost_report_thumbnail("dummy.png", width="invalid", height=720)
    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        generate_gcp_cost_report_thumbnail("dummy.png", width=0, height=720)
    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        generate_gcp_cost_report_thumbnail("dummy.png", width=1280, height=-10)

def test_generate_gcp_cost_report_thumbnail_save_exception(tmp_path):
    output_file = tmp_path / "error_thumb.png"
    with patch("PIL.Image.Image.save", side_effect=RuntimeError("Save failed")):
        with pytest.raises(RuntimeError, match="Save failed"):
            generate_gcp_cost_report_thumbnail(output_file)
    assert not output_file.exists()
    temp_files = list(tmp_path.glob("*.tmp"))
    assert len(temp_files) == 0

def test_generate_gcp_cost_report_thumbnail_save_and_unlink_exception(tmp_path):
    output_file = tmp_path / "unlink_error_thumb.png"
    
    def mock_save(self, fp, format=None, **params):
        if isinstance(fp, (str, Path)):
            Path(fp).touch()
        raise RuntimeError("Save failed")
        
    original_remove = os.remove
    original_unlink = os.unlink
    
    def mock_remove(path, *args, **kwargs):
        path_str = str(path)
        if ".tmp" in path_str:
            raise RuntimeError("Remove failed")
        return original_remove(path, *args, **kwargs)
        
    def mock_unlink(path, *args, **kwargs):
        path_str = str(path)
        if ".tmp" in path_str:
            raise RuntimeError("Unlink failed")
        return original_unlink(path, *args, **kwargs)
        
    with patch("PIL.Image.Image.save", mock_save), \
         patch("os.remove", side_effect=mock_remove), \
         patch("os.unlink", side_effect=mock_unlink):
        with pytest.raises(RuntimeError, match="Save failed"):
            generate_gcp_cost_report_thumbnail(output_file)

# 4. validate_thumbnail 関数のテスト
def test_validate_thumbnail_not_found():
    with pytest.raises(FileNotFoundError, match="Thumbnail file not found"):
        validate_thumbnail("non_existent_file.png")

def test_validate_thumbnail_too_large(tmp_path):
    large_file = tmp_path / "large.png"
    with open(large_file, "wb") as f:
        f.seek(4 * 1024 * 1024 + 10)
        f.write(b"\0")
    with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
        validate_thumbnail(large_file)

def test_validate_thumbnail_corrupted(tmp_path):
    corrupted_file = tmp_path / "corrupted.png"
    corrupted_file.write_text("not an image")
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        validate_thumbnail(corrupted_file)

@patch("PIL.Image.open")
def test_validate_thumbnail_verify_fail(mock_open, tmp_path):
    output_file = tmp_path / "verify_fail.png"
    output_file.touch()
    
    mock_img = MagicMock()
    mock_img.verify.side_effect = Exception("Verify fail")
    mock_open.return_value.__enter__.return_value = mock_img
    
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        validate_thumbnail(output_file)

@patch("PIL.Image.open")
def test_validate_thumbnail_load_fail(mock_open, tmp_path):
    output_file = tmp_path / "load_fail.png"
    output_file.touch()
    
    mock_img = MagicMock()
    mock_img.verify.return_value = None
    mock_img.load.side_effect = Exception("Load fail")
    mock_open.return_value.__enter__.return_value = mock_img
    
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        validate_thumbnail(output_file)

def test_validate_thumbnail_resolution_too_low(tmp_path):
    output_file = tmp_path / "low_res.png"
    generate_gcp_cost_report_thumbnail(output_file, width=640, height=360)
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        validate_thumbnail(output_file)

def test_validate_thumbnail_aspect_ratio_invalid(tmp_path):
    output_file = tmp_path / "invalid_aspect.png"
    generate_gcp_cost_report_thumbnail(output_file, width=1280, height=1280)
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        validate_thumbnail(output_file)

def test_validate_thumbnail_success(tmp_path):
    output_file = tmp_path / "valid.png"
    generate_gcp_cost_report_thumbnail(output_file)
    res = validate_thumbnail(output_file)
    assert res["path"] == str(output_file)
    assert res["width"] == 1280
    assert res["height"] == 720
    assert "size_bytes" in res

# 5. resolve_gcp_cost_monitor_task 関数のテスト
@pytest.mark.asyncio
@patch("backend.gcp_cost_monitor.check_gcp_costs")
@patch("backend.gcp_cost_monitor.OUTPUT_DIR")
async def test_resolve_gcp_cost_monitor_task_success(mock_output_dir, mock_check, tmp_path):
    mock_output_dir_str = str(tmp_path)
    with patch("backend.gcp_cost_monitor.OUTPUT_DIR", mock_output_dir_str):
        mock_check.return_value = {
            "timestamp": "2026-05-30T00:00:00Z",
            "projects": ["proj-1", "proj-2"]
        }
        task_id = "test-task-1"
        res_json = await resolve_gcp_cost_monitor_task(task_id)
        res = json.loads(res_json)
        expected_path = tmp_path / f"{task_id}.png"
        assert res["path"] == str(expected_path)
        assert expected_path.exists()

@pytest.mark.asyncio
@patch("backend.gcp_cost_monitor.check_gcp_costs")
@patch("backend.gcp_cost_monitor.OUTPUT_DIR")
async def test_resolve_gcp_cost_monitor_task_warning(mock_output_dir, mock_check, tmp_path):
    mock_output_dir_str = str(tmp_path)
    with patch("backend.gcp_cost_monitor.OUTPUT_DIR", mock_output_dir_str):
        mock_check.return_value = None
        task_id = "test-task-2"
        res_json = await resolve_gcp_cost_monitor_task(task_id)
        res = json.loads(res_json)
        expected_path = tmp_path / f"{task_id}.png"
        assert res["path"] == str(expected_path)
        assert expected_path.exists()

# 6. メイン実行ブロック (__name__ == "__main__") のテスト (121行目のカバー)
@patch("backend.gcp_cost_monitor.subprocess.run")
def test_main_execution(mock_run):
    mock_run.return_value = MagicMock(stdout='[]')
    runpy.run_module("backend.gcp_cost_monitor", run_name="__main__")
    mock_run.assert_any_call(
        ["gcloud", "projects", "list", "--format=json"],
        capture_output=True,
        text=True,
        check=True
    )
