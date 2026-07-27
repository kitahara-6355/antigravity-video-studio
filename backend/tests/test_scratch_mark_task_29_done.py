import sys
import os
import traceback
from unittest.mock import patch, MagicMock
import pytest

# テストコード自身でもプロジェクトルートを sys.path に確実に追加しておく
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

@pytest.fixture(autouse=True)
def clean_modules_and_path():
    # テスト実行前にキャッシュクリアと sys.path の退避
    original_path = list(sys.path)
    sys.modules.pop('backend.scratch.mark_task_29_done', None)
    yield
    # テスト実行後にも復元とキャッシュクリア
    sys.path = original_path
    sys.modules.pop('backend.scratch.mark_task_29_done', None)

def test_scratch_mark_task_29_done():
    # OrchestrationHub をモック化する
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        
        # setup_project_path() の追加動作を検証するため一時的に project_root を除去
        while project_root in sys.path:
            sys.path.remove(project_root)
        sys.path.insert(0, "")
            
        # モジュールを import して実行する
        import backend.scratch.mark_task_29_done
        res = backend.scratch.mark_task_29_done.main()
        assert res == 0
            
        # 呼び出しの検証
        mock_hub.flash_update_heartbeat.assert_called_once()
        mock_hub.mark_task_done.assert_called_once_with(
            task_id="T-batch_769699-thumbnail-029",
            result="pass",
            report={
                "message": "tests/_screenshot_dashboard.py: C0/ブランチカバレッジ 100% 維持。2つの新規テストケースを追加し堅牢性向上",
                "changed_files": ["backend/tests/test_screenshot_dashboard.py"]
            }
        )

def test_scratch_mark_task_29_done_main_error():
    # OrchestrationHub がエラーを発生させた場合の伝播と戻り値検証
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
        mock_hub = MagicMock()
        mock_hub.mark_task_done.side_effect = RuntimeError("Hub Error")
        mock_hub_class.return_value = mock_hub
        
        import backend.scratch.mark_task_29_done
        res = backend.scratch.mark_task_29_done.main()
        assert res == 1

def test_scratch_mark_task_29_done_main_exception_logged(capsys):
    # OrchestrationHub がエラーを発生させた場合の stderr 出力とトレースバック出力を検証
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
        mock_hub = MagicMock()
        mock_hub.mark_task_done.side_effect = RuntimeError("Hub Error Details")
        mock_hub_class.return_value = mock_hub
        
        import backend.scratch.mark_task_29_done
        res = backend.scratch.mark_task_29_done.main()
        assert res == 1
            
        captured = capsys.readouterr()
        assert "Error marking task as done due to orchestration/system issue: Hub Error Details" in captured.err
        assert "traceback" in captured.err.lower() or "tracebacktype" in captured.err.lower() or "runtimeerror" in captured.err.lower()

def test_scratch_mark_task_29_done_import_error(capsys):
    # OrchestrationHub のインポートエラーが発生した場合の挙動検証
    with patch.dict(sys.modules, {"backend.agents.orchestration": None}):
        import backend.scratch.mark_task_29_done
        res = backend.scratch.mark_task_29_done.main()
        assert res == 1
        
        captured = capsys.readouterr()
        assert "Import Error: Could not import OrchestrationHub" in captured.err

def test_scratch_mark_task_29_done_path_resolution():
    # パス解決が正しく行われているかの検証
    import backend.scratch.mark_task_29_done
    resolved_path = backend.scratch.mark_task_29_done.project_root
    assert os.path.isdir(resolved_path)
    assert os.path.exists(os.path.join(resolved_path, "backend"))

def test_scratch_mark_task_29_done_path_resolution_already_in_path():
    # すでに sys.path に存在している場合に重複追加されないことを検証
    # 一旦 project_root を sys.path の先頭に置いておく
    norm_project_root = os.path.normcase(os.path.abspath(project_root))
    initial_occurrences = sum(1 for p in sys.path if p and os.path.normcase(os.path.abspath(p)) == norm_project_root)
    if initial_occurrences == 0:
        sys.path.insert(0, project_root)
        initial_occurrences = 1
    
    import backend.scratch.mark_task_29_done
    # 重複して追加されていないか（件数が増えていないこと）
    occurrences = sum(1 for p in sys.path if p and os.path.normcase(os.path.abspath(p)) == norm_project_root)
    assert occurrences == initial_occurrences

def test_scratch_mark_task_29_done_path_resolution_no_file():
    # __file__ が globals() に定義されていない場合のパス解決検証
    import backend.scratch.mark_task_29_done
    
    # __file__ を隠蔽した状態で setup_project_path を実行する
    with patch.dict(backend.scratch.mark_task_29_done.__dict__, {"__file__": None}):
        backend.scratch.mark_task_29_done.setup_project_path()
        resolved = backend.scratch.mark_task_29_done.project_root
        assert os.path.isdir(resolved)

def test_scratch_mark_task_29_done_run_as_script():
    # スクリプトとして直接実行された（__name__ == "__main__"）場合の検証
    import runpy
    
    # 7行目の sys.path.insert を確実に通すために、一旦 sys.path から project_root を除去する
    while project_root in sys.path:
        sys.path.remove(project_root)
        
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        
        # run_path でスクリプトを直接実行する
        script_path = os.path.join(project_root, "backend", "scratch", "mark_task_29_done.py")
        # 直接実行した場合は sys.exit(0) が呼ばれるはずなので SystemExit(0) が発生する
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_path(script_path, run_name="__main__")
            
        assert excinfo.value.code == 0
        
        # 呼び出しの検証
        mock_hub.flash_update_heartbeat.assert_called_once()
        mock_hub.mark_task_done.assert_called_once_with(
            task_id="T-batch_769699-thumbnail-029",
            result="pass",
            report={
                "message": "tests/_screenshot_dashboard.py: C0/ブランチカバレッジ 100% 維持。2つの新規テストケースを追加し堅牢性向上",
                "changed_files": ["backend/tests/test_screenshot_dashboard.py"]
            }
        )

def test_scratch_mark_task_29_done_run_as_script_exception():
    # スクリプトとして直接実行され、例外が発生したときに sys.exit(1) が呼ばれるかの検証
    import runpy
    
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
        mock_hub = MagicMock()
        mock_hub.mark_task_done.side_effect = RuntimeError("Main Exec Error")
        mock_hub_class.return_value = mock_hub
        
        script_path = os.path.join(project_root, "backend", "scratch", "mark_task_29_done.py")
        # sys.exit(1) が実行されるはずなので SystemExit(1) が発生する
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_path(script_path, run_name="__main__")
            
        assert excinfo.value.code == 1

def test_scratch_mark_task_29_done_validation_error(capsys):
    import backend.scratch.mark_task_29_done
    
    # 無効な形式の task_id
    res = backend.scratch.mark_task_29_done.main("invalid_task_id_format")
    assert res == 1
    
    captured = capsys.readouterr()
    assert "Validation Error: Invalid task_id format:" in captured.err

def test_scratch_mark_task_29_done_json_decode_error(capsys):
    import json
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
        mock_hub = MagicMock()
        mock_hub.mark_task_done.side_effect = json.JSONDecodeError("Expecting value", "", 0)
        mock_hub_class.return_value = mock_hub
        
        import backend.scratch.mark_task_29_done
        res = backend.scratch.mark_task_29_done.main()
        assert res == 1
        
        captured = capsys.readouterr()
        assert "JSON Decode Error: Managed JSON file is corrupted:" in captured.err

def test_scratch_mark_task_29_done_file_not_found_error(capsys):
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
        mock_hub = MagicMock()
        mock_hub.mark_task_done.side_effect = FileNotFoundError("Missing file")
        mock_hub_class.return_value = mock_hub
        
        import backend.scratch.mark_task_29_done
        res = backend.scratch.mark_task_29_done.main()
        assert res == 1
        
        captured = capsys.readouterr()
        assert "File Not Found Error: Orchestration file missing:" in captured.err

def test_scratch_mark_task_29_done_permission_error(capsys):
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
        mock_hub = MagicMock()
        mock_hub.mark_task_done.side_effect = PermissionError("Access denied")
        mock_hub_class.return_value = mock_hub
        
        import backend.scratch.mark_task_29_done
        res = backend.scratch.mark_task_29_done.main()
        assert res == 1
        
        captured = capsys.readouterr()
        assert "Permission Error: Access denied to orchestration files:" in captured.err

def test_scratch_mark_task_29_done_key_error(capsys):
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
        mock_hub = MagicMock()
        mock_hub.mark_task_done.side_effect = KeyError("Missing key")
        mock_hub_class.return_value = mock_hub
        
        import backend.scratch.mark_task_29_done
        res = backend.scratch.mark_task_29_done.main()
        assert res == 1
        
        captured = capsys.readouterr()
        assert "Key Error: Missing required key in orchestration data:" in captured.err

def test_scratch_mark_task_29_done_os_error(capsys):
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
        mock_hub = MagicMock()
        mock_hub.mark_task_done.side_effect = OSError("Disk full")
        mock_hub_class.return_value = mock_hub
        
        import backend.scratch.mark_task_29_done
        res = backend.scratch.mark_task_29_done.main()
        assert res == 1
        
        captured = capsys.readouterr()
        assert "Error marking task as done due to orchestration/system issue: Disk full" in captured.err

def test_scratch_mark_task_29_done_type_error(capsys):
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
        mock_hub = MagicMock()
        mock_hub.mark_task_done.side_effect = TypeError("Invalid argument type")
        mock_hub_class.return_value = mock_hub
        
        import backend.scratch.mark_task_29_done
        res = backend.scratch.mark_task_29_done.main()
        assert res == 1
        
        captured = capsys.readouterr()
        assert "Error marking task as done due to orchestration/system issue: Invalid argument type" in captured.err

def test_scratch_mark_task_29_done_path_resolution_normalization():
    import backend.scratch.mark_task_29_done
    resolved = backend.scratch.mark_task_29_done.project_root
    
    original_path = list(sys.path)
    try:
        alt_root_relative = os.path.relpath(resolved)
        alt_root_lower = resolved.lower()
        
        sys.path.append(alt_root_relative)
        sys.path.append(alt_root_lower)
        
        backend.scratch.mark_task_29_done.setup_project_path()
        
        norm_paths = [os.path.abspath(p) for p in sys.path if p]
        assert norm_paths.count(os.path.abspath(resolved)) >= 1
    finally:
        sys.path = original_path
