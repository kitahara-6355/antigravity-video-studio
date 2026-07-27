import json
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import pytest
import runpy

from model_guardian import (
    ModelGuardian,
    model_guardian,
    run_guardian_check,
    BACKEND_DIR,
    DEFAULT_DEPRECATED_MODELS,
    DEFAULT_CURRENT_MODELS,
)


def test_load_models_from_config_exceptions():
    # Test exceptions in _load_models_from_config
    
    # 1. json.JSONDecodeError
    with patch("builtins.open", mock_open(read_data="invalid json")), \
         patch("json.load", side_effect=json.JSONDecodeError("msg", "doc", 0)), \
         patch("model_guardian.logger.warning") as mock_warn:
        guardian = ModelGuardian()
        mock_warn.assert_called()
        assert "gemini-1.5-flash" in guardian._deprecated_models
        assert "gemini-3-flash-preview" in guardian._current_models

    # 2. FileNotFoundError (config_path does not exist)
    with patch("pathlib.Path.exists", return_value=False):
        guardian = ModelGuardian()
        assert "gemini-1.5-flash" in guardian._deprecated_models
        assert "gemini-3-flash-preview" in guardian._current_models

    # 3. KeyError, TypeError, ValueError, OSError, PermissionError
    exceptions = [
        KeyError("test"),
        TypeError("test"),
        ValueError("test"),
        OSError("test"),
        PermissionError("test"),
    ]
    for exc in exceptions:
        with patch("pathlib.Path.exists", return_value=True), \
             patch("builtins.open", mock_open(read_data="{}")), \
             patch("json.load", side_effect=exc), \
             patch("model_guardian.logger.warning") as mock_warn:
            guardian = ModelGuardian()
            mock_warn.assert_called()


def test_load_models_from_config_success():
    # Test successful config loading
    mock_config = {
        "deprecated": {
            "gemini-deprecated-1": {"replacement": "gemini-current-1"}
        },
        "removed": {
            "gemini-removed-1": {}
        },
        "text_generation": {
            "default_model": "gemini-current-1",
            "tiers": {
                "tier1": {"model": "gemini-current-2"}
            }
        },
        "image_generation": {
            "default_model": "gemini-current-3"
        },
        "video_generation": {
            "default_model": "gemini-current-4"
        }
    }
    
    with patch("pathlib.Path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=json.dumps(mock_config))), \
         patch("json.load", return_value=mock_config):
        guardian = ModelGuardian()
        assert "gemini-deprecated-1" in guardian._deprecated_models
        assert "gemini-removed-1" in guardian._deprecated_models
        assert "gemini-current-1" in guardian._current_models
        assert "gemini-current-2" in guardian._current_models
        assert "gemini-current-3" in guardian._current_models
        assert "gemini-current-4" in guardian._current_models


def test_load_models_from_config_exclude_deprecated():
    # Test that deprecated models are excluded from current models list
    mock_config = {
        "deprecated": {
            "gemini-1.5-flash": {}
        },
        "text_generation": {
            "default_model": "gemini-1.5-flash"
        }
    }
    with patch("pathlib.Path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=json.dumps(mock_config))), \
         patch("json.load", return_value=mock_config):
        guardian = ModelGuardian()
        assert "gemini-1.5-flash" in guardian._deprecated_models
        assert "gemini-1.5-flash" not in guardian._current_models


def test_is_excluded():
    guardian = ModelGuardian()
    
    # Paths that should be excluded
    assert guardian._is_excluded(Path("backend/archives/old_code.py"))
    assert guardian._is_excluded(Path("backend/_deprecated_file.py"))
    assert guardian._is_excluded(Path("backend/__pycache__/main.pyc"))
    assert guardian._is_excluded(Path("backend/test_model_guardian.py"))
    assert guardian._is_excluded(Path("backend/.env"))
    
    # Paths that should not be excluded
    assert not guardian._is_excluded(Path("backend/main.py"))
    assert not guardian._is_excluded(Path("backend/services/video.py"))


def test_scan_file_exceptions():
    guardian = ModelGuardian()
    
    # PermissionError, FileNotFoundError, OSError in read_text
    for exc in [FileNotFoundError(), PermissionError(), OSError()]:
        with patch("pathlib.Path.read_text", side_effect=exc):
            # Should not raise exception
            guardian._scan_file(Path("dummy_path.py"))


def test_scan_file_content_logic(tmp_path):
    test_file = tmp_path / "test_module.py"
    
    content = """
# This is a comment and should be ignored even if it contains gemini-1.5-flash
  # another comment
  
# get_model( is allowed:
model = get_model("gemini-1.5-flash")

# ALLOW_PATTERNS matching:
# gemini-1.5-flash
MODEL_NAME = get_model("gemini-1.5-flash")

# Hardcoded deprecated model (should trigger ERROR)
x = "gemini-1.5-flash"

# Hardcoded current model (should trigger WARNING)
y = "gemini-3-flash-preview"

# Line too long with hardcoded model
z = "gemini-1.5-flash" # """ + ("a" * 150) + "\n"
    
    test_file.write_text(content, encoding="utf-8")
    
    guardian = ModelGuardian()
    with patch("model_guardian.BACKEND_DIR", tmp_path):
        guardian._scan_file(test_file)
    
    issues = guardian._issues
    assert len(issues) >= 3
    
    # x validation
    x_issues = [i for i in issues if i["model"] == "gemini-1.5-flash" and "x = " in i["content"]]
    assert len(x_issues) == 1
    assert x_issues[0]["severity"] == "ERROR"
    
    # y validation
    y_issues = [i for i in issues if i["model"] == "gemini-3-flash-preview"]
    assert len(y_issues) == 1
    assert y_issues[0]["severity"] == "WARNING"

    # z validation (content truncated to 120 chars)
    z_issues = [i for i in issues if "z = " in i["content"]]
    assert len(z_issues) == 1
    assert len(z_issues[0]["content"]) <= 120


def test_scan_with_issues(tmp_path):
    src_dir = tmp_path / "backend"
    src_dir.mkdir()
    
    test_file = src_dir / "bad_code.py"
    test_file.write_text('model = "gemini-1.5-flash"', encoding="utf-8")
    
    # Definition file (should be skipped)
    def_file = src_dir / "model_registry.py"
    def_file.write_text('model = "gemini-1.5-flash"', encoding="utf-8")
    
    # Excluded file (should be skipped)
    ex_file = src_dir / "test_model_guardian.py"
    ex_file.write_text('model = "gemini-1.5-flash"', encoding="utf-8")
    
    guardian = ModelGuardian()
    with patch("model_guardian.BACKEND_DIR", src_dir), \
         patch("model_guardian.logger.error") as mock_err, \
         patch("model_guardian.logger.warning") as mock_warn:
        issues = guardian.scan(root=src_dir)
        
        assert len(issues) == 1
        assert issues[0]["file"] == "bad_code.py"
        assert issues[0]["severity"] == "ERROR"
        mock_err.assert_called()


def test_scan_no_issues(tmp_path):
    src_dir = tmp_path / "backend"
    src_dir.mkdir()
    
    test_file = src_dir / "good_code.py"
    test_file.write_text('model = get_model("gemini-1.5-flash")', encoding="utf-8")
    
    guardian = ModelGuardian()
    with patch("model_guardian.BACKEND_DIR", src_dir), \
         patch("model_guardian.logger.info") as mock_info:
        issues = guardian.scan(root=src_dir)
        assert len(issues) == 0
        mock_info.assert_called_with("✅ ModelGuardian: 1 files scanned, no hardcoded model references found.")


def test_scan_with_warning(tmp_path):
    src_dir = tmp_path / "backend"
    src_dir.mkdir()
    
    test_file = src_dir / "warn_code.py"
    test_file.write_text('model = "gemini-3-flash-preview"', encoding="utf-8")
    
    guardian = ModelGuardian()
    with patch("model_guardian.BACKEND_DIR", src_dir), \
         patch("model_guardian.logger.warning") as mock_warn:
        issues = guardian.scan(root=src_dir)
        assert len(issues) == 1
        assert issues[0]["severity"] == "WARNING"
        mock_warn.assert_called()


def test_get_summary():
    guardian = ModelGuardian()
    
    guardian._issues = []
    guardian._scanned_files = 5
    assert guardian.get_summary() == "✅ ModelGuardian: 5 files clean"
    
    guardian._issues = [
        {"severity": "ERROR"},
        {"severity": "WARNING"}
    ]
    guardian._scanned_files = 5
    assert guardian.get_summary() == "ModelGuardian: 1 errors, 1 warnings in 5 files"


def test_run_guardian_check():
    with patch("model_guardian.model_guardian.scan", return_value=[]) as mock_scan:
        issues = run_guardian_check()
        assert issues == []
        mock_scan.assert_called_once()


def test_main_block():
    # Test __main__ entry point by running the script directly.
    # We patch builtins.print and logging to avoid messy test output, but allow actual scan.
    with patch("builtins.print") as mock_print:
        runpy.run_path(str(BACKEND_DIR / "model_guardian.py"), run_name="__main__")
        # Ensure that it ran and printed issues since there are actual hardcoded models in backend
        mock_print.assert_any_call("\n============================================================")
