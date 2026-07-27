import sys
import os
import importlib
from unittest.mock import MagicMock, patch
import pytest

@pytest.fixture
def restore_env():
    orig_cwd = os.getcwd()
    orig_path = list(sys.path)
    orig_modules = dict(sys.modules)
    
    # Remove from sys.modules so it gets re-executed on import
    sys.modules.pop("tests._debug_dashboard", None)
    sys.modules.pop("backend.tests._debug_dashboard", None)
    sys.modules.pop("_debug_dashboard", None)
    
    yield
    
    os.chdir(orig_cwd)
    sys.path = orig_path
    sys.modules.clear()
    sys.modules.update(orig_modules)

def test_debug_dashboard_success(restore_env, capsys):
    mock_tracker = MagicMock()
    mock_tracker.get_daily_summary.return_value = {
        "models": {"gpt-4": 10},
        "total": 10
    }
    
    mock_module = MagicMock()
    mock_module.usage_tracker = mock_tracker
    
    with patch.dict(sys.modules, {"usage_tracker": mock_module}):
        tests_dir = os.path.dirname(__file__); sys.path.insert(0, tests_dir) if tests_dir not in sys.path else None; import _debug_dashboard
        
        captured = capsys.readouterr()
        assert "summary keys: ['models', 'total']" in captured.out
        assert "models type: <class 'dict'>" in captured.out
        assert "models: {'gpt-4': 10}" in captured.out

def test_debug_dashboard_exception_in_get_daily_summary(restore_env):
    mock_tracker = MagicMock()
    mock_tracker.get_daily_summary.side_effect = Exception("Failed to get summary")
    
    mock_module = MagicMock()
    mock_module.usage_tracker = mock_tracker
    
    with patch.dict(sys.modules, {"usage_tracker": mock_module}):
        with patch("traceback.print_exc") as mock_print_exc:
            tests_dir = os.path.dirname(__file__); sys.path.insert(0, tests_dir) if tests_dir not in sys.path else None; import _debug_dashboard
            mock_print_exc.assert_called_once()

def test_debug_dashboard_import_error(restore_env):
    with patch.dict(sys.modules, {"usage_tracker": None}):
        with patch("traceback.print_exc") as mock_print_exc:
            tests_dir = os.path.dirname(__file__); sys.path.insert(0, tests_dir) if tests_dir not in sys.path else None; import _debug_dashboard
            mock_print_exc.assert_called_once()

def test_debug_dashboard_empty_summary(restore_env, capsys):
    mock_tracker = MagicMock()
    mock_tracker.get_daily_summary.return_value = {}
    
    mock_module = MagicMock()
    mock_module.usage_tracker = mock_tracker
    
    with patch.dict(sys.modules, {"usage_tracker": mock_module}):
        tests_dir = os.path.dirname(__file__); sys.path.insert(0, tests_dir) if tests_dir not in sys.path else None; import _debug_dashboard
        
        captured = capsys.readouterr()
        assert "summary keys: []" in captured.out
        assert "models type: <class 'NoneType'>" in captured.out
        assert "models: None" in captured.out

def test_debug_dashboard_none_summary(restore_env):
    mock_tracker = MagicMock()
    mock_tracker.get_daily_summary.return_value = None
    
    mock_module = MagicMock()
    mock_module.usage_tracker = mock_tracker
    
    with patch.dict(sys.modules, {"usage_tracker": mock_module}):
        with patch("traceback.print_exc") as mock_print_exc:
            tests_dir = os.path.dirname(__file__); sys.path.insert(0, tests_dir) if tests_dir not in sys.path else None; import _debug_dashboard
            mock_print_exc.assert_called_once()

def test_debug_dashboard_invalid_summary_type(restore_env):
    mock_tracker = MagicMock()
    mock_tracker.get_daily_summary.return_value = [1, 2, 3]  # AttributeError for keys()
    
    mock_module = MagicMock()
    mock_module.usage_tracker = mock_tracker
    
    with patch.dict(sys.modules, {"usage_tracker": mock_module}):
        with patch("traceback.print_exc") as mock_print_exc:
            tests_dir = os.path.dirname(__file__); sys.path.insert(0, tests_dir) if tests_dir not in sys.path else None; import _debug_dashboard
            mock_print_exc.assert_called_once()

def test_debug_dashboard_invalid_models_value(restore_env, capsys):
    mock_tracker = MagicMock()
    mock_tracker.get_daily_summary.return_value = {
        "models": "invalid_model_type",
        "total": 10
    }
    
    mock_module = MagicMock()
    mock_module.usage_tracker = mock_tracker
    
    with patch.dict(sys.modules, {"usage_tracker": mock_module}):
        tests_dir = os.path.dirname(__file__); sys.path.insert(0, tests_dir) if tests_dir not in sys.path else None; import _debug_dashboard
        
        captured = capsys.readouterr()
        assert "summary keys: ['models', 'total']" in captured.out
        assert "models type: <class 'str'>" in captured.out
        assert "models: invalid_model_type" in captured.out

def test_debug_dashboard_env_side_effects(restore_env):
    mock_tracker = MagicMock()
    mock_tracker.get_daily_summary.return_value = {}
    mock_module = MagicMock()
    mock_module.usage_tracker = mock_tracker
    
    with patch.dict(sys.modules, {"usage_tracker": mock_module}):
        tests_dir = os.path.dirname(__file__); sys.path.insert(0, tests_dir) if tests_dir not in sys.path else None; import _debug_dashboard
        
        expected_dir = os.path.abspath(os.path.join(os.path.dirname(_debug_dashboard.__file__), ".."))
        assert os.path.abspath(os.getcwd()) == expected_dir
        assert expected_dir in sys.path

def test_debug_dashboard_no_mock(restore_env, capsys):
    # Test without mocking usage_tracker to ensure integration works
    # and the try-except block successfully handles any real-world database/config exceptions.
    tests_dir = os.path.dirname(__file__); sys.path.insert(0, tests_dir) if tests_dir not in sys.path else None; import _debug_dashboard
    captured = capsys.readouterr()
    # It should either succeed (print summary keys) or print exception traceback.
    # It must not crash the test suite in either case.
    assert ("summary keys:" in captured.out) or ("Traceback" in captured.err or "Traceback" in captured.out)



def test_debug_dashboard_chdir_called_always(restore_env):
    mock_tracker = MagicMock()
    mock_tracker.get_daily_summary.side_effect = Exception("Failed")
    mock_module = MagicMock()
    mock_module.usage_tracker = mock_tracker
    
    with patch.dict(sys.modules, {"usage_tracker": mock_module}):
        tests_dir = os.path.dirname(__file__); sys.path.insert(0, tests_dir) if tests_dir not in sys.path else None; import _debug_dashboard
        
        expected_dir = os.path.abspath(os.path.join(os.path.dirname(_debug_dashboard.__file__), ".."))
        assert os.path.abspath(os.getcwd()) == expected_dir

def test_debug_dashboard_multiple_models_output(restore_env, capsys):
    mock_tracker = MagicMock()
    mock_tracker.get_daily_summary.return_value = {
        "models": {"gpt-4": 10, "gemini-1.5": 5},
        "total": 15
    }
    
    mock_module = MagicMock()
    mock_module.usage_tracker = mock_tracker
    
    with patch.dict(sys.modules, {"usage_tracker": mock_module}):
        tests_dir = os.path.dirname(__file__); sys.path.insert(0, tests_dir) if tests_dir not in sys.path else None; import _debug_dashboard
        
        captured = capsys.readouterr()
        assert "summary keys: ['models', 'total']" in captured.out
        assert "models type: <class 'dict'>" in captured.out
        assert "models: {'gpt-4': 10, 'gemini-1.5': 5}" in captured.out

def test_debug_dashboard_missing_models_key(restore_env, capsys):
    mock_tracker = MagicMock()
    mock_tracker.get_daily_summary.return_value = {
        "total": 10
    }
    
    mock_module = MagicMock()
    mock_module.usage_tracker = mock_tracker
    
    with patch.dict(sys.modules, {"usage_tracker": mock_module}):
        tests_dir = os.path.dirname(__file__); sys.path.insert(0, tests_dir) if tests_dir not in sys.path else None; import _debug_dashboard
        
        captured = capsys.readouterr()
        assert "summary keys: ['total']" in captured.out
        assert "models type: <class 'NoneType'>" in captured.out
        assert "models: None" in captured.out

def test_debug_dashboard_import_error_direct(restore_env):
    real_import = __import__
    def mock_import(name, *args, **kwargs):
        if name == "usage_tracker":
            raise ImportError("Mocked ImportError")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        with patch("traceback.print_exc") as mock_print_exc:
            tests_dir = os.path.dirname(__file__); sys.path.insert(0, tests_dir) if tests_dir not in sys.path else None; import _debug_dashboard
            mock_print_exc.assert_called_once()

def test_debug_dashboard_exception_traceback_content(restore_env, capsys):
    mock_tracker = MagicMock()
    mock_tracker.get_daily_summary.side_effect = ValueError("Specific value error")
    
    mock_module = MagicMock()
    mock_module.usage_tracker = mock_tracker
    
    with patch.dict(sys.modules, {"usage_tracker": mock_module}):
        tests_dir = os.path.dirname(__file__); sys.path.insert(0, tests_dir) if tests_dir not in sys.path else None; import _debug_dashboard
        
        captured = capsys.readouterr()
        assert "ValueError: Specific value error" in captured.err
