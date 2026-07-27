import sys
import os
from unittest.mock import MagicMock, patch
import pytest
import runpy

# プロジェクトルートのパス追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# モジュールのアンロード用ヘルパー
def unload_module():
    if "backend.scratch.mark_task_f076d6_005_done" in sys.modules:
        del sys.modules["backend.scratch.mark_task_f076d6_005_done"]

def test_initialize_project_environment():
    import backend.scratch.mark_task_f076d6_005_done as m
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    
    original_path = sys.path.copy()
    try:
        # sys.pathから完全にプロジェクトルートを削除
        while project_root in sys.path:
            sys.path.remove(project_root)
        while project_root + os.sep in sys.path:
            sys.path.remove(project_root + os.sep)
            
        # この状態で手動呼び出しすることで、8行目を実行させる
        m.initialize_project_environment()
        assert project_root in sys.path
    finally:
        sys.path = original_path

def test_create_orchestration_hub():
    import backend.scratch.mark_task_f076d6_005_done as m
    with patch("backend.scratch.mark_task_f076d6_005_done.OrchestrationHub") as mock_hub_cls:
        m.create_orchestration_hub()
        mock_hub_cls.assert_called_once()

def test_update_hub_heartbeat():
    import backend.scratch.mark_task_f076d6_005_done as m
    mock_hub = MagicMock()
    m.update_hub_heartbeat(mock_hub)
    mock_hub.flash_update_heartbeat.assert_called_once()

def test_send_task_done_status():
    import backend.scratch.mark_task_f076d6_005_done as m
    mock_hub = MagicMock()
    m.send_task_done_status(mock_hub, "task-1", {"some": "report"})
    mock_hub.mark_task_done.assert_called_once_with(
        task_id="task-1",
        result="pass",
        report={"some": "report"}
    )

def test_mark_task_as_completed():
    import backend.scratch.mark_task_f076d6_005_done as m
    mock_hub = MagicMock()
    with patch("backend.scratch.mark_task_f076d6_005_done.update_hub_heartbeat") as mock_heartbeat, \
         patch("backend.scratch.mark_task_f076d6_005_done.send_task_done_status") as mock_send:
        m.mark_task_as_completed(mock_hub)
        mock_heartbeat.assert_called_once_with(mock_hub)
        mock_send.assert_called_once_with(mock_hub, m.TARGET_TASK_ID, m.TASK_REPORT)

def test_instantiate_technical_debt_store():
    import backend.scratch.mark_task_f076d6_005_done as m
    with patch("backend.agents.memory.technical_debt.TechnicalDebtStore") as mock_store_cls:
        m.instantiate_technical_debt_store()
        mock_store_cls.assert_called_once()

def test_print_debt_registration_error(capsys):
    import backend.scratch.mark_task_f076d6_005_done as m
    err = Exception("Test Error")
    m.print_debt_registration_error(err)
    captured = capsys.readouterr()
    assert "Failed to register technical debt: Test Error" in captured.err

def test_record_debt_entry():
    import backend.scratch.mark_task_f076d6_005_done as m
    mock_store = MagicMock()
    err = Exception("Dummy Error")
    m.record_debt_entry(mock_store, 42, err)
    mock_store.register_debt.assert_called_once_with(
        category="MINOR_INFRA",
        file_path="scratch/mark_task_f076d6_005_done.py",
        line_number=42,
        pattern="except Exception as e:",
        registered_by="thumbnail_task",
        notes="Scratch script execution failure handler: Dummy Error"
    )

def test_log_technical_debt_on_failure_success():
    import backend.scratch.mark_task_f076d6_005_done as m
    mock_store = MagicMock()
    err = Exception("Test Error")
    with patch("backend.scratch.mark_task_f076d6_005_done.instantiate_technical_debt_store", return_value=mock_store) as mock_inst, \
         patch("backend.scratch.mark_task_f076d6_005_done.record_debt_entry") as mock_record:
        m.log_technical_debt_on_failure(100, err)
        mock_inst.assert_called_once()
        mock_record.assert_called_once_with(mock_store, 100, err)

def test_log_technical_debt_on_failure_inner_exception():
    import backend.scratch.mark_task_f076d6_005_done as m
    err = Exception("Outer Error")
    inner_err = Exception("Inner Error")
    with patch("backend.scratch.mark_task_f076d6_005_done.instantiate_technical_debt_store", side_effect=inner_err) as mock_inst, \
         patch("backend.scratch.mark_task_f076d6_005_done.print_debt_registration_error") as mock_print:
        m.log_technical_debt_on_failure(100, err)
        mock_inst.assert_called_once()
        mock_print.assert_called_once_with(inner_err)

def test_main_success():
    unload_module()
    import backend.scratch.mark_task_f076d6_005_done as m
    mock_hub = MagicMock()
    with patch("backend.scratch.mark_task_f076d6_005_done.create_orchestration_hub", return_value=mock_hub) as mock_create, \
         patch("backend.scratch.mark_task_f076d6_005_done.mark_task_as_completed") as mock_mark:
        res = m.main()
        assert res == 0
        mock_create.assert_called_once()
        mock_mark.assert_called_once_with(mock_hub)

def test_main_failure(capsys):
    unload_module()
    import backend.scratch.mark_task_f076d6_005_done as m
    err = Exception("Hub Error")
    with patch("backend.scratch.mark_task_f076d6_005_done.create_orchestration_hub", side_effect=err) as mock_create, \
         patch("backend.scratch.mark_task_f076d6_005_done.log_technical_debt_on_failure") as mock_log:
        res = m.main()
        assert res == 1
        mock_create.assert_called_once()
        mock_log.assert_called_once()
        args, kwargs = mock_log.call_args
        assert kwargs["error"] == err
        captured = capsys.readouterr()
        assert "Error marking task as done: Hub Error" in captured.err

def test_main_execution_as_script():
    unload_module()
    script_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "backend", "scratch", "mark_task_f076d6_005_done.py")
    )
    
    mock_hub = MagicMock()
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub) as mock_hub_class:
        with pytest.raises(SystemExit) as exc_info:
            runpy.run_path(script_path, run_name="__main__")
        assert exc_info.value.code == 0
        mock_hub_class.assert_called_once()
        mock_hub.flash_update_heartbeat.assert_called_once()
        mock_hub.mark_task_done.assert_called_once()
