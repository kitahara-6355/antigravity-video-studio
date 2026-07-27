import pytest
from unittest.mock import patch
import subprocess
import json
import runpy
from gcp_cost_monitor import check_gcp_costs


def test_check_gcp_costs_success():
    """正常系: プロジェクトがあり、Cloud Runサービスもある場合"""
    def mock_run_side_effect(args, **kwargs):
        cmd = args[0:3]
        if cmd == ["gcloud", "projects", "list"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps([{"projectId": "proj-1", "name": "Project 1"}]),
                stderr=""
            )
        elif cmd == ["gcloud", "run", "services"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps([
                    {
                        "metadata": {
                            "name": "service-1",
                            "labels": {"cloud.googleapis.com/location": "us-central1"},
                            "creationTimestamp": "2026-05-22T00:00:00Z"
                        }
                    }
                ]),
                stderr=""
            )
        raise ValueError(f"Unexpected args: {args}")

    with patch("subprocess.run", side_effect=mock_run_side_effect):
        result = check_gcp_costs()
        assert result is not None
        assert "projects" in result
        assert "proj-1" in result["projects"]


def test_check_gcp_costs_no_services():
    """正常系: プロジェクトはあるが、Cloud Runサービスがない場合"""
    def mock_run_side_effect(args, **kwargs):
        cmd = args[0:3]
        if cmd == ["gcloud", "projects", "list"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps([{"projectId": "proj-2", "name": "Project 2"}]),
                stderr=""
            )
        elif cmd == ["gcloud", "run", "services"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="[]",
                stderr=""
            )
        raise ValueError(f"Unexpected args: {args}")

    with patch("subprocess.run", side_effect=mock_run_side_effect):
        result = check_gcp_costs()
        assert result is not None
        assert "proj-2" in result["projects"]


def test_check_gcp_costs_no_projects():
    """異常系: プロジェクトが見つからない場合"""
    def mock_run_side_effect(args, **kwargs):
        cmd = args[0:3]
        if cmd == ["gcloud", "projects", "list"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="[]",
                stderr=""
            )
        raise ValueError(f"Unexpected args: {args}")

    with patch("subprocess.run", side_effect=mock_run_side_effect):
        result = check_gcp_costs()
        assert result is None


def test_check_gcp_costs_projects_error():
    """異常系: プロジェクト一覧取得でエラーが発生した場合"""
    with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, ["gcloud", "projects", "list"])):
        result = check_gcp_costs()
        assert result is None


def test_check_gcp_costs_services_error():
    """異常系: Cloud Runサービス一覧取得でエラーが発生した場合(他プロジェクトは続行)"""
    def mock_run_side_effect(args, **kwargs):
        cmd = args[0:3]
        if cmd == ["gcloud", "projects", "list"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps([
                    {"projectId": "proj-error", "name": "Error Project"},
                    {"projectId": "proj-ok", "name": "OK Project"}
                ]),
                stderr=""
            )
        elif cmd == ["gcloud", "run", "services"]:
            project_arg = [arg for arg in args if arg.startswith("--project=")][0]
            if "proj-error" in project_arg:
                raise subprocess.CalledProcessError(1, args)
            else:
                return subprocess.CompletedProcess(
                    args=args,
                    returncode=0,
                    stdout="[]",
                    stderr=""
                )
        raise ValueError(f"Unexpected args: {args}")

    with patch("subprocess.run", side_effect=mock_run_side_effect):
        result = check_gcp_costs()
        assert result is not None
        assert "proj-error" in result["projects"]
        assert "proj-ok" in result["projects"]


def test_main_block():
    """__main__ブロックの実行テスト"""
    with patch("subprocess.run") as mock_run:
        # check_gcp_costsの内部で呼ばれるsubprocess.runをモック化
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="[]", stderr=""
        )
        runpy.run_path("backend/gcp_cost_monitor.py", run_name="__main__")
        mock_run.assert_called()


def test_check_gcp_costs_invalid_json():
    """異常系: プロジェクト一覧のJSONが破損している場合"""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["gcloud", "projects", "list"],
            returncode=0,
            stdout="invalid-json-content",
            stderr=""
        )
        result = check_gcp_costs()
        assert result is None


def test_check_gcp_costs_metadata_none():
    """正常系: サービスの metadata や labels が None の場合でもクラッシュしないこと"""
    def mock_run_side_effect(args, **kwargs):
        cmd = args[0:3]
        if cmd == ["gcloud", "projects", "list"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps([{"projectId": "proj-none", "name": "None Project"}]),
                stderr=""
            )
        elif cmd == ["gcloud", "run", "services"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps([
                    {
                        "metadata": None  # metadata が None
                    },
                    {
                        "metadata": {
                            "name": "service-no-labels",
                            "labels": None  # labels が None
                        }
                    }
                ]),
                stderr=""
            )
        raise ValueError(f"Unexpected args: {args}")

    with patch("subprocess.run", side_effect=mock_run_side_effect):
        result = check_gcp_costs()
        assert result is not None
        assert "proj-none" in result["projects"]


def test_check_gcp_costs_services_invalid_json():
    """異常系: サービス一覧のJSONが破損している場合（他のプロジェクト処理は続行）。プロジェクトIDが無効な場合はスキップされることも確認。"""
    def mock_run_side_effect(args, **kwargs):
        cmd = args[0:3]
        if cmd == ["gcloud", "projects", "list"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps([
                    {"projectId": "proj-bad-json", "name": "Bad JSON Project"},
                    {"projectId": "proj-good-json", "name": "Good JSON Project"},
                    {"name": "No Project ID Project"},
                    {"projectId": "N/A", "name": "N/A Project ID Project"}
                ]),
                stderr=""
            )
        elif cmd == ["gcloud", "run", "services"]:
            project_arg = [arg for arg in args if arg.startswith("--project=")][0]
            if "proj-bad-json" in project_arg:
                return subprocess.CompletedProcess(
                    args=args,
                    returncode=0,
                    stdout="invalid-services-json",
                    stderr=""
                )
            else:
                return subprocess.CompletedProcess(
                    args=args,
                    returncode=0,
                    stdout="[]",
                    stderr=""
                )
        raise ValueError(f"Unexpected args: {args}")

    with patch("subprocess.run", side_effect=mock_run_side_effect):
        result = check_gcp_costs()
        assert result is not None
        assert "proj-bad-json" in result["projects"]
        assert "proj-good-json" in result["projects"]
        assert "N/A" not in result["projects"]
        assert None not in result["projects"]


def test_create_report_image_success():
    from gcp_cost_monitor import _create_report_image
    # 正常系 (デフォルトテキスト)
    img = _create_report_image(1280, 720)
    assert img.size == (1280, 720)
    
    # 正常系 (カスタムテキスト)
    img2 = _create_report_image("1280", "720", text="Custom Text")
    assert img2.size == (1280, 720)


def test_create_report_image_invalid_types():
    from gcp_cost_monitor import _create_report_image
    with pytest.raises(ValueError):
        _create_report_image("invalid", 720)


def test_create_report_image_non_positive():
    from gcp_cost_monitor import _create_report_image
    with pytest.raises(ValueError):
        _create_report_image(0, 720)
    with pytest.raises(ValueError):
        _create_report_image(1280, -10)


def test_save_image_atomically_success(tmp_path):
    from gcp_cost_monitor import _create_report_image, _save_image_atomically
    img = _create_report_image(1280, 720)
    file_path = tmp_path / "report.png"
    
    # 正常系
    _save_image_atomically(img, file_path)
    assert file_path.exists()
    
    # 正常系 (上書き)
    _save_image_atomically(img, file_path)
    assert file_path.exists()


def test_save_image_atomically_save_error(tmp_path):
    from gcp_cost_monitor import _save_image_atomically
    from unittest.mock import MagicMock
    
    img = MagicMock()
    img.save.side_effect = Exception("Save failed")
    file_path = tmp_path / "error_report.png"
    
    with pytest.raises(Exception, match="Save failed"):
        _save_image_atomically(img, file_path)
    
    temp_files = list(tmp_path.glob("*.tmp"))
    assert len(temp_files) == 0


def test_save_image_atomically_rename_error(tmp_path):
    from gcp_cost_monitor import _create_report_image, _save_image_atomically
    from unittest.mock import patch
    
    img = _create_report_image(100, 100)
    file_path = tmp_path / "rename_error.png"
    
    with patch("pathlib.Path.rename", side_effect=Exception("Rename failed")):
        with pytest.raises(Exception, match="Rename failed"):
            _save_image_atomically(img, file_path)
            
    temp_files = list(tmp_path.glob("*.tmp"))
    assert len(temp_files) == 0


def test_save_image_atomically_unlink_error(tmp_path):
    from gcp_cost_monitor import _save_image_atomically
    from unittest.mock import MagicMock, patch
    from pathlib import Path
    
    img = MagicMock()
    img.save.side_effect = Exception("Save failed")
    file_path = tmp_path / "unlink_error.png"
    
    orig_exists = Path.exists
    orig_unlink = Path.unlink
    
    def mock_exists(self):
        if self.suffix.endswith(".tmp"):
            return True
        return orig_exists(self)
        
    def mock_unlink(self):
        if self.suffix.endswith(".tmp"):
            raise Exception("Unlink failed")
        return orig_unlink(self)
        
    with patch.object(Path, "exists", mock_exists), \
         patch.object(Path, "unlink", mock_unlink):
         
        with pytest.raises(Exception, match="Save failed"):
            _save_image_atomically(img, file_path)


def test_generate_gcp_cost_report_thumbnail(tmp_path):
    from gcp_cost_monitor import generate_gcp_cost_report_thumbnail
    output_file = tmp_path / "thumb.png"
    res = generate_gcp_cost_report_thumbnail(output_file, width=1280, height=720, text="Hello")
    assert res == output_file
    assert output_file.exists()


def test_verify_image_integrity_errors(tmp_path):
    from gcp_cost_monitor import _verify_image_integrity
    # 存在しないファイル
    with pytest.raises(FileNotFoundError):
        _verify_image_integrity(tmp_path / "non_existent.png")
        
    # ファイルサイズが4MB以上
    large_file = tmp_path / "large.png"
    large_file.write_bytes(b"0" * (4 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
        _verify_image_integrity(large_file)


def test_verify_image_integrity_corrupted_verify(tmp_path):
    from gcp_cost_monitor import _verify_image_integrity
    bad_file = tmp_path / "bad.png"
    bad_file.write_text("not an image")
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        _verify_image_integrity(bad_file)


def test_verify_image_integrity_corrupted_load(tmp_path):
    from gcp_cost_monitor import _verify_image_integrity
    from PIL import Image
    from unittest.mock import patch, MagicMock
    
    mock_img = MagicMock(spec=Image.Image)
    mock_img.size = (1280, 720)
    mock_img.verify.return_value = None
    mock_img.load.side_effect = Exception("Load error")
    
    dummy_file = tmp_path / "dummy.png"
    dummy_file.write_bytes(b"dummy data")
    
    mock_open = MagicMock()
    mock_open.return_value.__enter__.return_value = mock_img
    
    with patch("PIL.Image.open", mock_open):
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            _verify_image_integrity(dummy_file)


def test_verify_image_dimensions():
    from gcp_cost_monitor import _verify_image_dimensions
    # 正常系
    _verify_image_dimensions(1280, 720)
    _verify_image_dimensions(1920, 1080)
    
    # 異常系: 小さすぎる
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        _verify_image_dimensions(1000, 720)
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        _verify_image_dimensions(1280, 500)
        
    # 異常系: アスペクト比が違う
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        _verify_image_dimensions(1280, 800)


def test_validate_thumbnail_success(tmp_path):
    from gcp_cost_monitor import generate_gcp_cost_report_thumbnail, validate_thumbnail
    output_file = tmp_path / "valid.png"
    generate_gcp_cost_report_thumbnail(output_file, width=1280, height=720)
    
    res = validate_thumbnail(output_file)
    assert res["path"] == str(output_file)
    assert res["width"] == 1280
    assert res["height"] == 720
    assert res["size_bytes"] > 0


def test_format_report_text():
    from gcp_cost_monitor import _format_report_text
    
    # OKケース
    cost_info_ok = {"projects": ["p1", "p2"], "timestamp": "2026-06-03"}
    text_ok = _format_report_text(cost_info_ok)
    assert "Status: OK" in text_ok
    assert "p1, p2" in text_ok
    
    # WARNINGケース
    text_warn = _format_report_text(None)
    assert "Status: WARNING" in text_warn
    assert "Failed to retrieve cost details." in text_warn


@pytest.mark.asyncio
async def test_resolve_gcp_cost_monitor_task(tmp_path):
    from gcp_cost_monitor import resolve_gcp_cost_monitor_task
    from unittest.mock import patch
    
    task_id = "test_task_123"
    expected_output_path = tmp_path / f"{task_id}.png"
    
    mock_cost_info = {"projects": ["test-proj"], "timestamp": "2026-06-03T00:00:00"}
    
    with patch("gcp_cost_monitor.check_gcp_costs", return_value=mock_cost_info), \
         patch("gcp_cost_monitor.OUTPUT_DIR", str(tmp_path)):
        
        result_json = await resolve_gcp_cost_monitor_task(task_id)
        
        assert expected_output_path.exists()
        
        result = json.loads(result_json)
        assert result["path"] == str(expected_output_path)
        assert result["width"] == 1280
        assert result["height"] == 720

