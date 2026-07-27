import sys
import os
from unittest.mock import patch, MagicMock
import urllib.error
import pytest

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import runpy

def run_check_quota():
    """
    Helper function to execute tests._check_quota via runpy.
    This ensures the script runs in the current process and coverage can track it.
    """
    script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "_check_quota.py"))
    runpy.run_path(script_path, run_name="__main__")

def test_check_quota_success(capsys):
    """
    Test successful execution of check_quota.py where both endpoints return 200 OK.
    Also verifies alert_level fallback when alert_level is missing.
    """
    with patch("urllib.request.urlopen") as mock_urlopen:
        # First call: api/usage/dashboard
        mock_response_1 = MagicMock()
        mock_response_1.read.return_value = b'{"models": [' \
                                            b'  {"model": "gemini-2.5", "used": 50, "daily_limit": 100, "alert_level": "WARNING"},' \
                                            b'  {"model": "claude-3", "used": 10, "daily_limit": 50}' \
                                            b']}'
        
        # Second call: api/pipeline/status
        mock_response_2 = MagicMock()
        mock_response_2.status = 200
        
        mock_urlopen.side_effect = [mock_response_1, mock_response_2]
        
        # Run the script
        run_check_quota()
        
        # Capture outputs
        captured = capsys.readouterr()
        
        # Assertions
        assert "gemini-2.5: 50/100 (WARNING)" in captured.out
        assert "claude-3: 10/50 (?)" in captured.out
        assert "Pipeline status: OK (200)" in captured.out


def test_check_quota_dashboard_http_error(capsys):
    """
    Test when api/usage/dashboard returns an HTTPError.
    Verifies decoding error response body (including non-UTF8 bytes replaced).
    """
    with patch("urllib.request.urlopen") as mock_urlopen:
        # Simulate HTTPError with invalid UTF8 bytes in response body
        fp = MagicMock()
        fp.read.return_value = b"Quota Exceeded \xff Error"
        
        http_error = urllib.error.HTTPError(
            "http://localhost:8000/api/usage/dashboard",
            429,
            "Too Many Requests",
            {},
            fp
        )
        
        # Second call: api/pipeline/status
        mock_response_2 = MagicMock()
        mock_response_2.status = 200
        
        mock_urlopen.side_effect = [http_error, mock_response_2]
        
        # Run the script
        run_check_quota()
        
        captured = capsys.readouterr()
        
        # Check HTTPError handling and byte replacement (replace character used for \xff is \ufffd or ?)
        assert "ERROR 429: Quota Exceeded \ufffd Error" in captured.out
        assert "Pipeline status: OK (200)" in captured.out


def test_check_quota_dashboard_generic_exception(capsys):
    """
    Test when api/usage/dashboard raises a generic Exception/URLError (no read attribute).
    """
    with patch("urllib.request.urlopen") as mock_urlopen:
        # URLError (has no read attribute)
        url_error = urllib.error.URLError("Connection refused")
        
        # Second call: api/pipeline/status
        mock_response_2 = MagicMock()
        mock_response_2.status = 200
        
        mock_urlopen.side_effect = [url_error, mock_response_2]
        
        # Run the script
        run_check_quota()
        
        captured = capsys.readouterr()
        
        assert "ERROR: <urlopen error Connection refused>" in captured.out
        assert "Pipeline status: OK (200)" in captured.out


def test_check_quota_pipeline_error(capsys):
    """
    Test when api/pipeline/status raises an Exception.
    """
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response_1 = MagicMock()
        mock_response_1.read.return_value = b'{"models": []}'
        
        # Second call raises URLError
        url_error = urllib.error.URLError("Timeout")
        
        mock_urlopen.side_effect = [mock_response_1, url_error]
        
        # Run the script
        run_check_quota()
        
        captured = capsys.readouterr()
        
        assert "Pipeline status: <urlopen error Timeout>" in captured.out


def test_check_quota_invalid_json(capsys):
    """
    Test when api/usage/dashboard returns invalid JSON.
    Verifies that JSONDecodeError is caught and handled in the generic exception block.
    """
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response_1 = MagicMock()
        mock_response_1.read.return_value = b"invalid json"
        
        mock_response_2 = MagicMock()
        mock_response_2.status = 200
        
        mock_urlopen.side_effect = [mock_response_1, mock_response_2]
        
        run_check_quota()
        
        captured = capsys.readouterr()
        
        assert "ERROR: Expecting value: line 1 column 1 (char 0)" in captured.out
        assert "Pipeline status: OK (200)" in captured.out


def test_check_quota_missing_keys(capsys):
    """
    Test when api/usage/dashboard returns models with missing keys (KeyError).
    Verifies that KeyError is caught and handled in the generic exception block.
    """
    with patch("urllib.request.urlopen") as mock_urlopen:
        # missing 'model' key in the model
        mock_response_1 = MagicMock()
        mock_response_1.read.return_value = b'{"models": ['                                             b'  {"used": 50, "daily_limit": 100}'                                             b']}'
        
        mock_response_2 = MagicMock()
        mock_response_2.status = 200
        
        mock_urlopen.side_effect = [mock_response_1, mock_response_2]
        
        run_check_quota()
        
        captured = capsys.readouterr()
        
        assert "ERROR: 'model'" in captured.out
        assert "Pipeline status: OK (200)" in captured.out


def test_check_quota_dashboard_http_error_truncated(capsys):
    """
    Test when api/usage/dashboard returns an HTTPError with a body longer than 300 characters.
    Verifies that the printed error body is truncated to 300 characters.
    """
    with patch("urllib.request.urlopen") as mock_urlopen:
        fp = MagicMock()
        # Create a body of 350 characters
        long_body = b"A" * 350
        fp.read.return_value = long_body
        
        http_error = urllib.error.HTTPError(
            "http://localhost:8000/api/usage/dashboard",
            500,
            "Internal Server Error",
            {},
            fp
        )
        
        mock_response_2 = MagicMock()
        mock_response_2.status = 200
        
        mock_urlopen.side_effect = [http_error, mock_response_2]
        
        run_check_quota()
        
        captured = capsys.readouterr()
        
        expected_body = "A" * 300
        assert f"ERROR 500: {expected_body}" in captured.out
        # Make sure it doesn't contain the full 350 characters
        assert "A" * 301 not in captured.out


def test_check_quota_dashboard_missing_models_key(capsys):
    """
    Test when api/usage/dashboard returns JSON without the 'models' key.
    Verifies that it defaults to an empty list and proceeds without raising an exception.
    """
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response_1 = MagicMock()
        # JSON without 'models' key
        mock_response_1.read.return_value = b'{"status": "ok"}'
        
        mock_response_2 = MagicMock()
        mock_response_2.status = 200
        
        mock_urlopen.side_effect = [mock_response_1, mock_response_2]
        
        run_check_quota()
        
        captured = capsys.readouterr()
        
        # Dashboard models should not print anything, but pipeline status should be OK
        assert "Pipeline status: OK (200)" in captured.out

