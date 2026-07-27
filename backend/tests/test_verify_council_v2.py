"""tests/test_verify_council_v2.py

Unit tests for verify_council_v2.py to achieve 100% coverage.
"""

import sys
import pytest
import runpy
from unittest.mock import patch, MagicMock
import requests

from verify_council_v2 import verify_council_session, main



def test_verify_council_session_success(capsys):
    """Test successful API call with requests."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "session_id": "test-session-123",
        "synthesis": "This is a mock synthesis text.",
        "debate_flow": [
            {"agent": "Analyst", "summary": "We need more views."},
            {"agent": "Strategist", "summary": "Improve thumbnail."}
        ]
    }

    with patch("requests.post", return_value=mock_response) as mock_post:
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        
        assert success is True
        mock_post.assert_called_once_with(
            "http://mock-url/api",
            params={"query": "test query"},
            timeout=10.0
        )
        
        captured = capsys.readouterr()
        assert "📡 Sending request to http://mock-url/api..." in captured.out
        assert "✅ Success!" in captured.out
        assert "Session ID: test-session-123" in captured.out
        assert "Synthesis: This is a mock synthesis text." in captured.out
        assert "Debate Flow: 2 responses received." in captured.out
        assert "  [0] Analyst: We need more views." in captured.out
        assert "  [1] Strategist: Improve thumbnail." in captured.out

def test_verify_council_session_success_with_session(capsys):
    """Test successful API call using requests.Session."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "session_id": "test-session-session",
        "synthesis": "Session synthesis",
        "debate_flow": []
    }

    mock_session_instance = MagicMock()
    mock_session_instance.post.return_value = mock_response
    mock_session_instance.__enter__.return_value = mock_session_instance

    with patch("requests.Session", return_value=mock_session_instance) as mock_session_cls:
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query session",
            timeout=5.0,
            use_session=True
        )
        
        assert success is True
        mock_session_cls.assert_called_once()
        mock_session_instance.post.assert_called_once_with(
            "http://mock-url/api",
            params={"query": "test query session"},
            timeout=5.0
        )

def test_verify_council_session_failed_status(capsys):
    """Test API call returning non-200 status code."""
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.text = "Bad Request Detail"
    
    # raise_for_status must raise HTTPError
    http_error = requests.exceptions.HTTPError("400 Client Error: Bad Request")
    http_error.response = mock_response
    mock_response.raise_for_status.side_effect = http_error

    with patch("requests.post", return_value=mock_response) as mock_post:
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        
        assert success is False
        captured = capsys.readouterr()
        assert "❌ HTTP Error: 400 Client Error: Bad Request" in captured.out
        assert "❌ Failed: 400" in captured.out
        assert "Bad Request Detail" in captured.out

def test_verify_council_session_timeout(capsys):
    """Test API call raising a Timeout exception."""
    with patch("requests.post", side_effect=requests.exceptions.Timeout("Timeout error")):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Timeout Error: Timeout error" in captured.out

def test_main_success():
    """Test main function executing successfully (exit code 0)."""
    test_args = ["verify_council_v2.py", "--url", "http://test-main/api", "--query", "main query", "--timeout", "15"]
    with patch("sys.argv", test_args):
        with patch("verify_council_v2.verify_council_session", return_value=True) as mock_verify:
            main()
            mock_verify.assert_called_once_with(
                url="http://test-main/api",
                query="main query",
                timeout=15.0,
                use_session=False,
                debug=False,
                send_as_json=False
            )

def test_main_failure():
    """Test main function exiting with status 1 on failure by patching sys.exit in the module."""
    test_args = ["verify_council_v2.py", "--use-session"]
    with patch("sys.argv", test_args):
        with patch("verify_council_v2.verify_council_session", return_value=False) as mock_verify:
            with patch("verify_council_v2.sys.exit") as mock_exit:
                main()
                mock_exit.assert_called_once_with(1)
            mock_verify.assert_called_once_with(
                url="http://localhost:8000/api/council/session",
                query="最近の動画の視聴維持率を上げるための具体的な編集テクニックを教えてください。",
                timeout=30.0,
                use_session=True,
                debug=False,
                send_as_json=False
            )

def test_main_block_execution():
    """Test execution of the __main__ block using runpy to cover main script execution path."""
    test_args = ["verify_council_v2.py", "--url", "http://test-main-block/api", "--query", "block query", "--timeout", "5"]
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "session_id": "test-session-123",
        "synthesis": "This is a mock synthesis text.",
        "debate_flow": []
    }
    
    with patch("sys.argv", test_args):
        with patch("requests.post", return_value=mock_response) as mock_post:
            import os
            current_dir = os.path.dirname(__file__)
            target_path = os.path.abspath(os.path.join(current_dir, "..", "verify_council_v2.py"))
            runpy.run_path(target_path, run_name="__main__")
            mock_post.assert_called_once_with(
                "http://test-main-block/api",
                params={"query": "block query"},
                timeout=5.0
            )

def test_verify_council_session_connection_error(capsys):
    """Test API call raising a ConnectionError."""
    with patch("requests.post", side_effect=requests.exceptions.ConnectionError("Connection failed")):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Connection Error: Connection failed" in captured.out

def test_verify_council_session_http_error(capsys):
    """Test API call raising an HTTPError."""
    with patch("requests.post", side_effect=requests.exceptions.HTTPError("HTTP error occurred")):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ HTTP Error: HTTP error occurred" in captured.out

def test_verify_council_session_json_decode_error(capsys):
    """Test API call with invalid JSON response."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.side_effect = ValueError("No JSON object could be decoded")

    with patch("requests.post", return_value=mock_response):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Error: Failed to decode JSON: No JSON object could be decoded" in captured.out

def test_verify_council_session_json_not_a_dict(capsys):
    """Test API call when JSON response is not a dictionary."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = ["not", "a", "dict"]

    with patch("requests.post", return_value=mock_response):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Error: Response JSON is not a dictionary" in captured.out

def test_verify_council_session_missing_fields(capsys):
    """Test API call with missing fields in response JSON."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {}

    with patch("requests.post", return_value=mock_response):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is True
        captured = capsys.readouterr()
        assert "Session ID: None" in captured.out
        assert "Synthesis:" in captured.out
        assert "Debate Flow: 0 responses received." in captured.out

def test_verify_council_session_invalid_debate_flow_type(capsys):
    """Test API call where debate_flow is not iterable as expected (e.g. integer or dict)."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "session_id": "test-123",
        "synthesis": "Synthesis text",
        "debate_flow": 12345
    }

    with patch("requests.post", return_value=mock_response):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Error:" in captured.out

def test_verify_council_session_long_synthesis(capsys):
    """Test API call with synthesis exactly and over 200 characters to verify slicing."""
    long_synthesis = "a" * 250
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "session_id": "test-123",
        "synthesis": long_synthesis,
        "debate_flow": []
    }

    with patch("requests.post", return_value=mock_response):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is True
        captured = capsys.readouterr()
        expected_synthesis_print = "Synthesis: " + ("a" * 200) + "..."
        assert expected_synthesis_print in captured.out

def test_main_invalid_timeout_argument():
    """Test that main function fails with SystemExit when an invalid timeout string is passed."""
    test_args = ["verify_council_v2.py", "--timeout", "not-a-float"]
    with patch("sys.argv", test_args):
        with pytest.raises(SystemExit):
            main()

def test_verify_council_session_debate_flow_missing_keys(capsys):
    """Test API call where debate_flow entries are missing 'agent' or 'summary' keys."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "session_id": "test-missing-keys",
        "synthesis": "Synthesis with missing keys in debate flow.",
        "debate_flow": [
            {"agent": "Analyst"},  # summary key missing
        ]
    }

    with patch("requests.post", return_value=mock_response):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Error: debate_flow entry at index 0 is missing 'summary' key" in captured.out

    mock_response_agent_missing = MagicMock()
    mock_response_agent_missing.status_code = 200
    mock_response_agent_missing.json.return_value = {
        "session_id": "test-missing-keys-2",
        "synthesis": "Synthesis with missing keys in debate flow.",
        "debate_flow": [
            {"summary": "Improve description."},  # agent key missing
        ]
    }

    with patch("requests.post", return_value=mock_response_agent_missing):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Error: debate_flow entry at index 0 is missing 'agent' key" in captured.out

def test_verify_council_session_debate_flow_invalid_types(capsys):
    """Test API call where debate_flow entry values are not strings."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "session_id": "test-invalid-types",
        "synthesis": "Synthesis with invalid type values in debate flow.",
        "debate_flow": [
            {"agent": 12345, "summary": "Valid summary"},  # agent is not a string
        ]
    }

    with patch("requests.post", return_value=mock_response):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Error: debate_flow entry at index 0 'agent' is not a string" in captured.out
        
    mock_response2 = MagicMock()
    mock_response2.status_code = 200
    mock_response2.json.return_value = {
        "session_id": "test-invalid-types2",
        "synthesis": "Synthesis with invalid type values in debate flow.",
        "debate_flow": [
            {"agent": "Analyst", "summary": {"not": "a string"}},  # summary is not a string
        ]
    }

    with patch("requests.post", return_value=mock_response2):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Error: debate_flow entry at index 0 'summary' is not a string" in captured.out

def test_verify_council_session_generic_request_exception(capsys):
    """Test API call raising a generic requests.exceptions.RequestException."""
    with patch("requests.post", side_effect=requests.exceptions.RequestException("Generic request error")):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Request Error: Generic request error" in captured.out

def test_verify_council_session_synthesis_none(capsys):
    """Test API call when synthesis is None."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "session_id": "test-none-synthesis",
        "synthesis": None,
        "debate_flow": []
    }
    with patch("requests.post", return_value=mock_response):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is True
        captured = capsys.readouterr()
        assert "Synthesis:" in captured.out

def test_verify_council_session_debate_flow_none(capsys):
    """Test API call when debate_flow is None."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "session_id": "test-none-debate-flow",
        "synthesis": "Synthesis text",
        "debate_flow": None
    }
    with patch("requests.post", return_value=mock_response):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is True
        captured = capsys.readouterr()
        assert "Debate Flow: 0 responses received." in captured.out

def test_verify_council_session_debate_flow_elements_invalid(capsys):
    """Test API call when debate_flow elements are not dictionaries."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "session_id": "test-invalid-elements",
        "synthesis": "Synthesis text",
        "debate_flow": [
            None,
            "not a dict",
            {"agent": "Analyst"}  # summary missing
        ]
    }
    with patch("requests.post", return_value=mock_response):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Error: debate_flow entry at index 0 is not a dictionary" in captured.out

def test_verify_council_session_synthesis_invalid_type(capsys):
    """Test API call when synthesis is of invalid type (not a string)."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "session_id": "test-invalid-synthesis",
        "synthesis": 12345,
        "debate_flow": []
    }
    with patch("requests.post", return_value=mock_response):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Error: 'synthesis' field is not a string" in captured.out


def test_verify_council_session_missing_schema(capsys):
    """Test API call raising a MissingSchema exception."""
    with patch("requests.post", side_effect=requests.exceptions.MissingSchema("Missing schema")):
        success = verify_council_session(
            url="invalid-url",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "\u274c URL Error: Missing schema in URL: Missing schema" in captured.out

def test_verify_council_session_invalid_schema(capsys):
    """Test API call raising an InvalidSchema exception."""
    with patch("requests.post", side_effect=requests.exceptions.InvalidSchema("Invalid schema")):
        success = verify_council_session(
            url="ftp://mock-url",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "\u274c URL Error: Invalid schema in URL: Invalid schema" in captured.out

def test_verify_council_session_invalid_url(capsys):
    """Test API call raising an InvalidURL exception."""
    with patch("requests.post", side_effect=requests.exceptions.InvalidURL("Invalid URL")):
        success = verify_council_session(
            url="http://[invalid-url",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "\u274c URL Error: Invalid URL format: Invalid URL" in captured.out

def test_verify_council_session_invalid_session_id_type(capsys):
    """Test API call when session_id is of invalid type (not a string)."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "session_id": 12345,
        "synthesis": "Synthesis text",
        "debate_flow": []
    }
    with patch("requests.post", return_value=mock_response):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "\u274c Error: 'session_id' field is not a string" in captured.out

def test_verify_council_session_generic_exception_debug_mode(capsys):
    """Test API call raising a generic exception with debug=True, verifying traceback print."""
    with patch("requests.post", side_effect=ZeroDivisionError("Unexpected calculation error")):
        with patch("traceback.print_exc") as mock_print_exc:
            success = verify_council_session(
                url="http://mock-url/api",
                query="test query",
                timeout=10.0,
                use_session=False,
                debug=True
            )
            assert success is False
            captured = capsys.readouterr()
            assert "❌ Unexpected Error (ZeroDivisionError) at verify_council_v2.py:" in captured.out
            assert "Unexpected calculation error" in captured.out
            mock_print_exc.assert_called_once()

def test_verify_council_session_http_error_with_response_text(capsys):
    """Test API call raising HTTPError and verify response body is printed."""
    mock_response = MagicMock()
    mock_response.text = "Error Details from Server"
    
    error = requests.exceptions.HTTPError("HTTP error")
    error.response = mock_response
    
    with patch("requests.post", side_effect=error):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "\u274c HTTP Error: HTTP error" in captured.out
        assert "Error Details from Server" in captured.out

def test_main_debug_flag_passed():
    """Test that main function passes debug=True when --debug is specified."""
    test_args = ["verify_council_v2.py", "--debug"]
    with patch("sys.argv", test_args):
        with patch("verify_council_v2.verify_council_session", return_value=True) as mock_verify:
            main()
            mock_verify.assert_called_once_with(
                url="http://localhost:8000/api/council/session",
                query="最近の動画の視聴維持率を上げるための具体的な編集テクニックを教えてください。",
                timeout=30.0,
                use_session=False,
                debug=True,
                send_as_json=False
            )


def test_verify_council_session_invalid_timeout(capsys):
    """Test API call with invalid timeout <= 0."""
    success = verify_council_session(
        url="http://mock-url/api",
        query="test query",
        timeout=0.0,
        use_session=False
    )
    assert success is False
    captured = capsys.readouterr()
    assert "❌ Error: Timeout must be a positive number" in captured.out

    success_neg = verify_council_session(
        url="http://mock-url/api",
        query="test query",
        timeout=-5.0,
        use_session=False
    )
    assert success_neg is False
    captured_neg = capsys.readouterr()
    assert "❌ Error: Timeout must be a positive number" in captured_neg.out


def test_verify_council_session_timeout_none(capsys):
    """Test API call with timeout=None."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "session_id": "test-session-none",
        "synthesis": "Synthesis with None timeout",
        "debate_flow": []
    }

    with patch("requests.post", return_value=mock_response) as mock_post:
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query none",
            timeout=None,
            use_session=False
        )
        assert success is True
        mock_post.assert_called_once_with(
            "http://mock-url/api",
            params={"query": "test query none"},
            timeout=None
        )

def test_verify_council_session_http_error_from_response(capsys):
    """Test API call when server returns 500 Internal Server Error."""
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"
    
    # raise_for_status must raise HTTPError
    http_error = requests.exceptions.HTTPError("500 Server Error: Internal Server Error")
    http_error.response = mock_response
    mock_response.raise_for_status.side_effect = http_error

    with patch("requests.post", return_value=mock_response):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query error",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ HTTP Error: 500 Server Error: Internal Server Error" in captured.out
        assert "❌ Failed: 500" in captured.out
        assert "Internal Server Error" in captured.out


def test_verify_council_session_success_201_status(capsys):
    """Test successful API call with 201 Created status code."""
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.json.return_value = {
        "session_id": "test-session-201",
        "synthesis": "Synthesis for 201 status code.",
        "debate_flow": []
    }

    with patch("requests.post", return_value=mock_response) as mock_post:
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query 201",
            timeout=10.0,
            use_session=False
        )
        assert success is True
        captured = capsys.readouterr()
        assert "Session ID: test-session-201" in captured.out

def test_verify_council_session_success_204_status(capsys):
    """Test successful API call with 204 No Content status code."""
    mock_response = MagicMock()
    mock_response.status_code = 204

    with patch("requests.post", return_value=mock_response) as mock_post:
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query 204",
            timeout=10.0,
            use_session=False
        )
        assert success is True
        captured = capsys.readouterr()
        assert "Session ID: None" in captured.out
        assert "Debate Flow: 0 responses received." in captured.out

def test_verify_council_session_string_timeout_valid(capsys):
    """Test API call with a valid string timeout that can be converted to float."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "session_id": "test-string-timeout",
        "synthesis": "",
        "debate_flow": []
    }

    with patch("requests.post", return_value=mock_response) as mock_post:
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout="15.5",
            use_session=False
        )
        assert success is True
        mock_post.assert_called_once_with(
            "http://mock-url/api",
            params={"query": "test query"},
            timeout=15.5
        )

def test_verify_council_session_string_timeout_invalid(capsys):
    """Test API call with an invalid string timeout that raises ValueError."""
    success = verify_council_session(
        url="http://mock-url/api",
        query="test query",
        timeout="not-a-float",
        use_session=False
    )
    assert success is False
    captured = capsys.readouterr()
    assert "❌ Error: Timeout must be a positive number" in captured.out


def test_verify_council_session_failed_404(capsys):
    """Test API call when server returns 404 Not Found."""
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.text = "Not Found"
    
    # raise_for_status must raise HTTPError
    http_error = requests.exceptions.HTTPError("404 Client Error: Not Found")
    http_error.response = mock_response
    mock_response.raise_for_status.side_effect = http_error

    with patch("requests.post", return_value=mock_response):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query 404",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ HTTP Error: 404 Client Error: Not Found" in captured.out
        assert "❌ Failed: 404" in captured.out
        assert "Not Found" in captured.out

def test_verify_council_session_boolean_timeout(capsys):
    """Test API call with a boolean timeout (True or False) which should fail."""
    success = verify_council_session(
        url="http://mock-url/api",
        query="test query",
        timeout=True,
        use_session=False
    )
    assert success is False
    captured = capsys.readouterr()
    assert "❌ Error: Timeout must be a positive number" in captured.out

    success_false = verify_council_session(
        url="http://mock-url/api",
        query="test query",
        timeout=False,
        use_session=False
    )
    assert success_false is False
    captured_false = capsys.readouterr()
    assert "❌ Error: Timeout must be a positive number" in captured_false.out


def test_verify_council_session_short_synthesis(capsys):
    """Test synthesis display when synthesis length is <= 200."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "session_id": "test-short",
        "synthesis": "Short synthesis text",
        "debate_flow": []
    }
    with patch("requests.post", return_value=mock_response):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is True
        captured = capsys.readouterr()
        assert "Synthesis: Short synthesis text" in captured.out
        assert "Synthesis: Short synthesis text..." not in captured.out

def test_verify_council_session_with_context_manager(capsys):
    """Test requests.Session context manager execution and auto-closing."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "session_id": "test-context",
        "synthesis": "context test",
        "debate_flow": []
    }
    mock_session_instance = MagicMock()
    mock_session_instance.post.return_value = mock_response
    mock_session_instance.__enter__.return_value = mock_session_instance

    with patch("requests.Session", return_value=mock_session_instance) as mock_session_cls:
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=True
        )
        assert success is True
        mock_session_cls.assert_called_once()
        mock_session_instance.__enter__.assert_called_once()
        mock_session_instance.__exit__.assert_called_once()

def test_verify_council_session_send_as_json(capsys):
    """Test query payload sent as JSON body instead of params when send_as_json=True."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "session_id": "test-json-payload",
        "synthesis": "json payload test",
        "debate_flow": []
    }

    with patch("requests.post", return_value=mock_response) as mock_post:
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query json",
            timeout=10.0,
            use_session=False,
            send_as_json=True
        )
        assert success is True
        mock_post.assert_called_once_with(
            "http://mock-url/api",
            json={"query": "test query json"},
            timeout=10.0
        )

def test_verify_council_session_send_as_json_with_session(capsys):
    """Test query payload sent as JSON body with requests.Session when send_as_json=True."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "session_id": "test-json-session",
        "synthesis": "json session test",
        "debate_flow": []
    }
    mock_session_instance = MagicMock()
    mock_session_instance.post.return_value = mock_response
    mock_session_instance.__enter__.return_value = mock_session_instance

    with patch("requests.Session", return_value=mock_session_instance):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query json",
            timeout=10.0,
            use_session=True,
            send_as_json=True
        )
        assert success is True
        mock_session_instance.post.assert_called_once_with(
            "http://mock-url/api",
            json={"query": "test query json"},
            timeout=10.0
        )

def test_main_json_flag_passed():
    """Test main function passes send_as_json=True when --json is specified."""
    test_args = ["verify_council_v2.py", "--json"]
    with patch("sys.argv", test_args):
        with patch("verify_council_v2.verify_council_session", return_value=True) as mock_verify:
            main()
            mock_verify.assert_called_once_with(
                url="http://localhost:8000/api/council/session",
                query="最近の動画の視聴維持率を上げるための具体的な編集テクニックを教えてください。",
                timeout=30.0,
                use_session=False,
                debug=False,
                send_as_json=True
            )

def test_main_timeout_none():
    """Test CLI argument parsing when --timeout None is specified."""
    test_args = ["verify_council_v2.py", "--timeout", "None"]
    with patch("sys.argv", test_args):
        with patch("verify_council_v2.verify_council_session", return_value=True) as mock_verify:
            main()
            mock_verify.assert_called_once_with(
                url="http://localhost:8000/api/council/session",
                query="最近の動画の視聴維持率を上げるための具体的な編集テクニックを教えてください。",
                timeout=None,
                use_session=False,
                debug=False,
                send_as_json=False
            )

def test_main_timeout_null():
    """Test CLI argument parsing when --timeout nUlL is specified."""
    test_args = ["verify_council_v2.py", "--timeout", "nUlL"]
    with patch("sys.argv", test_args):
        with patch("verify_council_v2.verify_council_session", return_value=True) as mock_verify:
            main()
            mock_verify.assert_called_once_with(
                url="http://localhost:8000/api/council/session",
                query="最近の動画の視聴維持率を上げるための具体的な編集テクニックを教えてください。",
                timeout=None,
                use_session=False,
                debug=False,
                send_as_json=False
            )

def test_main_timeout_valid_float():
    """Test CLI argument parsing when a valid float string --timeout 12.3 is specified."""
    test_args = ["verify_council_v2.py", "--timeout", "12.3"]
    with patch("sys.argv", test_args):
        with patch("verify_council_v2.verify_council_session", return_value=True) as mock_verify:
            main()
            mock_verify.assert_called_once_with(
                url="http://localhost:8000/api/council/session",
                query="最近の動画の視聴維持率を上げるための具体的な編集テクニックを教えてください。",
                timeout=12.3,
                use_session=False,
                debug=False,
                send_as_json=False
            )

def test_main_timeout_invalid_str():
    """Test CLI argument parsing raises argparse error when invalid timeout is specified."""
    test_args = ["verify_council_v2.py", "--timeout", "not-a-valid-timeout"]
    with patch("sys.argv", test_args):
        with pytest.raises(SystemExit):
            main()


def test_verify_council_session_empty_url(capsys):
    """Test verify_council_session when url is empty or whitespace."""
    success = verify_council_session(url="", query="test")
    assert success is False
    captured = capsys.readouterr()
    assert "❌ Error: URL cannot be empty" in captured.out

    success_space = verify_council_session(url="   ", query="test")
    assert success_space is False
    captured_space = capsys.readouterr()
    assert "❌ Error: URL cannot be empty" in captured_space.out

def test_verify_council_session_empty_query(capsys):
    """Test verify_council_session when query is empty or whitespace."""
    success = verify_council_session(url="http://test", query="")
    assert success is False
    captured = capsys.readouterr()
    assert "❌ Error: Query cannot be empty" in captured.out

    success_space = verify_council_session(url="http://test", query="   ")
    assert success_space is False
    captured_space = capsys.readouterr()
    assert "❌ Error: Query cannot be empty" in captured_space.out

def test_parse_timeout_negative_value():
    """Test parse_timeout raises ArgumentTypeError for negative or zero values."""
    from verify_council_v2 import parse_timeout
    import argparse
    with pytest.raises(argparse.ArgumentTypeError) as excinfo:
        parse_timeout("-5.0")
    assert "Timeout must be a positive number" in str(excinfo.value)

    with pytest.raises(argparse.ArgumentTypeError) as excinfo_zero:
        parse_timeout("0")
    assert "Timeout must be a positive number" in str(excinfo_zero.value)

def test_verify_council_session_http_error_with_mock_raise_for_status(capsys):
    """Test verify_council_session captures HTTPError when raise_for_status throws it."""
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.text = "Page Not Found"
    
    http_error = requests.exceptions.HTTPError("404 Client Error: Not Found")
    http_error.response = mock_response
    mock_response.raise_for_status.side_effect = http_error

    with patch("requests.post", return_value=mock_response):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ HTTP Error: 404 Client Error: Not Found" in captured.out
        assert "❌ Failed: 404" in captured.out
        assert "Page Not Found" in captured.out


def test_verify_council_session_invalid_url_type(capsys):
    """Test verify_council_session when url is not a string."""
    success = verify_council_session(url=123, query="test query")
    assert success is False
    captured = capsys.readouterr()
    assert "❌ Error: URL must be a string" in captured.out

def test_verify_council_session_invalid_query_type(capsys):
    """Test verify_council_session when query is not a string."""
    success = verify_council_session(url="http://mock-url", query=456)
    assert success is False
    captured = capsys.readouterr()
    assert "❌ Error: Query must be a string" in captured.out

def test_verify_council_session_invalid_use_session_type(capsys):
    """Test verify_council_session when use_session is not a boolean."""
    success = verify_council_session(url="http://mock-url", query="test query", use_session="not-a-bool")
    assert success is False
    captured = capsys.readouterr()
    assert "❌ Error: use_session must be a boolean" in captured.out

def test_verify_council_session_invalid_debug_type(capsys):
    """Test verify_council_session when debug is not a boolean."""
    success = verify_council_session(url="http://mock-url", query="test query", debug="not-a-bool")
    assert success is False
    captured = capsys.readouterr()
    assert "❌ Error: debug must be a boolean" in captured.out

def test_verify_council_session_invalid_send_as_json_type(capsys):
    """Test verify_council_session when send_as_json is not a boolean."""
    success = verify_council_session(url="http://mock-url", query="test query", send_as_json="not-a-bool")
    assert success is False
    captured = capsys.readouterr()
    assert "❌ Error: send_as_json must be a boolean" in captured.out


def test_verify_council_session_type_error_handling(capsys):
    """Test verify_council_session captures TypeError and prints appropriate message."""
    with patch("requests.post", side_effect=TypeError("Mock type error")):
        success = verify_council_session(url="http://mock-url", query="test query")
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Type Error at verify_council_v2.py:" in captured.out
        assert "Mock type error" in captured.out

def test_verify_council_session_value_error_handling(capsys):
    """Test verify_council_session captures ValueError and prints appropriate message."""
    with patch("requests.post", side_effect=ValueError("Mock value error")):
        success = verify_council_session(url="http://mock-url", query="test query")
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Value Error at verify_council_v2.py:" in captured.out
        assert "Mock value error" in captured.out

def test_verify_council_session_attribute_error_handling(capsys):
    """Test verify_council_session captures AttributeError and prints appropriate message."""
    with patch("requests.post", side_effect=AttributeError("Mock attribute error")):
        success = verify_council_session(url="http://mock-url", query="test query")
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Attribute Error at verify_council_v2.py:" in captured.out
        assert "Mock attribute error" in captured.out


def test_verify_council_session_type_error_debug_mode(capsys):
    """Test TypeError print_exc in debug mode."""
    with patch("requests.post", side_effect=TypeError("Mock type error")):
        with patch("traceback.print_exc") as mock_print_exc:
            success = verify_council_session(url="http://mock-url", query="test query", debug=True)
            assert success is False
            mock_print_exc.assert_called_once()

def test_verify_council_session_value_error_debug_mode(capsys):
    """Test ValueError print_exc in debug mode."""
    with patch("requests.post", side_effect=ValueError("Mock value error")):
        with patch("traceback.print_exc") as mock_print_exc:
            success = verify_council_session(url="http://mock-url", query="test query", debug=True)
            assert success is False
            mock_print_exc.assert_called_once()

def test_verify_council_session_attribute_error_debug_mode(capsys):
    """Test AttributeError print_exc in debug mode."""
    with patch("requests.post", side_effect=AttributeError("Mock attribute error")):
        with patch("traceback.print_exc") as mock_print_exc:
            success = verify_council_session(url="http://mock-url", query="test query", debug=True)
            assert success is False
            mock_print_exc.assert_called_once()


def test_verify_council_session_unexpected_error_traceback(capsys):
    """Test that unexpected error prints the file name and line number."""
    with patch("requests.post", side_effect=ZeroDivisionError("division by zero")):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Unexpected Error (ZeroDivisionError) at verify_council_v2.py:" in captured.out
        assert "division by zero" in captured.out

def test_verify_council_session_type_error_location(capsys):
    """Test that TypeError prints the file name and line number."""
    with patch("requests.post", side_effect=TypeError("Mock type error")):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Type Error at verify_council_v2.py:" in captured.out
        assert "Mock type error" in captured.out

def test_verify_council_session_value_error_location(capsys):
    """Test that ValueError prints the file name and line number."""
    with patch("requests.post", side_effect=ValueError("Mock value error")):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Value Error at verify_council_v2.py:" in captured.out
        assert "Mock value error" in captured.out

def test_verify_council_session_attribute_error_location(capsys):
    """Test that AttributeError prints the file name and line number."""
    with patch("requests.post", side_effect=AttributeError("Mock attribute error")):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Attribute Error at verify_council_v2.py:" in captured.out
        assert "Mock attribute error" in captured.out


def test_verify_council_session_nan_timeout(capsys):
    """Test verify_council_session with NaN timeout."""
    success = verify_council_session(
        url="http://mock-url/api",
        query="test query",
        timeout=float('nan'),
        use_session=False
    )
    assert success is False
    captured = capsys.readouterr()
    assert "❌ Error: Timeout must be a positive number" in captured.out

def test_verify_council_session_inf_timeout(capsys):
    """Test verify_council_session with infinity timeout."""
    success = verify_council_session(
        url="http://mock-url/api",
        query="test query",
        timeout=float('inf'),
        use_session=False
    )
    assert success is False
    captured = capsys.readouterr()
    assert "❌ Error: Timeout must be a positive number" in captured.out

def test_parse_timeout_nan_inf():
    """Test parse_timeout rejects NaN and infinity values."""
    from verify_council_v2 import parse_timeout
    import argparse
    with pytest.raises(argparse.ArgumentTypeError) as excinfo:
        parse_timeout("nan")
    assert "Timeout must be a positive number" in str(excinfo.value)

    with pytest.raises(argparse.ArgumentTypeError) as excinfo_inf:
        parse_timeout("inf")
    assert "Timeout must be a positive number" in str(excinfo_inf.value)


def test_verify_council_session_none_traceback():
    """Test that _get_exception_location returns ('unknown', 'unknown') if traceback is None."""
    from verify_council_v2 import _get_exception_location
    file_name, line_no = _get_exception_location(None)
    assert file_name == "unknown"
    assert line_no == "unknown"

def test_verify_council_session_corrupted_traceback():
    """Test that _get_exception_location handles traceback objects missing expected attributes gracefully."""
    from verify_council_v2 import _get_exception_location
    mock_tb = MagicMock(spec=[])
    file_name, line_no = _get_exception_location(mock_tb)
    assert file_name == "unknown"
    assert line_no == "unknown"

def test_verify_council_session_http_error_truncated_response(capsys):
    """Test that verify_council_session truncates long HTTPError response texts."""
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "A" * 1000
    
    http_error = requests.exceptions.HTTPError("500 Internal Server Error")
    http_error.response = mock_response
    mock_response.raise_for_status.side_effect = http_error

    with patch("requests.post", return_value=mock_response):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Failed: 500" in captured.out
        assert "... (truncated)" in captured.out
        assert len(captured.out.split("... (truncated)")[0]) <= 800

def test_verify_council_session_logging_output():
    """Test that verify_council_session logs errors to python logger when exceptions occur."""
    with patch("requests.post", side_effect=ValueError("Test log error")):
        with patch("verify_council_v2.logger.error") as mock_log_error:
            success = verify_council_session(
                url="http://mock-url/api",
                query="test query",
                timeout=10.0,
                use_session=False
            )
            assert success is False
            mock_log_error.assert_called()
            log_args = mock_log_error.call_args[0]
            assert "Value Error" in log_args[0]


def test_verify_council_session_traceback_missing_f_code():
    """Test that _get_exception_location returns ('unknown', 'unknown') if frame lacks f_code."""
    from verify_council_v2 import _get_exception_location
    mock_frame = MagicMock(spec=[])
    mock_tb = MagicMock()
    mock_tb.tb_frame = mock_frame
    mock_tb.tb_next = None
    
    file_name, line_no = _get_exception_location(mock_tb)
    assert file_name == "unknown"
    assert line_no == "unknown"


def test_verify_council_session_corrupted_traceback_loop(capsys):
    """Test that _get_exception_location handles tracebacks with loops without hanging."""
    from verify_council_v2 import _get_exception_location
    
    # tb_next points to itself to create a loop
    mock_tb = MagicMock()
    mock_tb.tb_frame = MagicMock()
    mock_tb.tb_frame.f_code = MagicMock()
    mock_tb.tb_frame.f_code.co_filename = "verify_council_v2.py"
    mock_tb.tb_next = mock_tb
    mock_tb.tb_lineno = 123
    
    file_name, line_no = _get_exception_location(mock_tb)
    # The loop should be broken and return target
    assert file_name == "verify_council_v2.py"
    assert line_no == "123"

def test_verify_council_session_traceback_throws_exception(capsys):
    """Test that _get_exception_location handles objects throwing exceptions safely."""
    from verify_council_v2 import _get_exception_location
    
    class BadTraceback:
        @property
        def tb_frame(self):
            raise AttributeError("Access denied")
        @property
        def tb_next(self):
            return None
        @property
        def tb_lineno(self):
            return 123

    bad_tb = BadTraceback()
    file_name, line_no = _get_exception_location(bad_tb)
    assert file_name == "unknown"
    assert line_no == "unknown"

def test_verify_council_session_http_error_decode_failed(capsys):
    """Test that verify_council_session handles HTTPError response text reading failure safely."""
    class BadResponse:
        status_code = 500
        @property
        def text(self):
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
        def raise_for_status(self):
            http_error = requests.exceptions.HTTPError("500 Internal Server Error")
            http_error.response = self
            raise http_error

    bad_response = BadResponse()
    with patch("requests.post", return_value=bad_response):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Failed: 500" in captured.out
        assert "<Failed to read response text:" in captured.out

def test_verify_council_session_tuple_timeout_success(capsys):
    """Test verify_council_session with valid tuple timeout."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "session_id": "test-tuple-timeout",
        "synthesis": "Synthesis text",
        "debate_flow": []
    }

    with patch("requests.post", return_value=mock_response) as mock_post:
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=(3.05, 27.0),
            use_session=False
        )
        assert success is True
        mock_post.assert_called_once_with(
            "http://mock-url/api",
            params={"query": "test query"},
            timeout=(3.05, 27.0)
        )

def test_verify_council_session_tuple_timeout_invalid(capsys):
    """Test verify_council_session with invalid tuple timeout elements."""
    # Invalid length
    success = verify_council_session(
        url="http://mock-url/api",
        query="test query",
        timeout=(3.05, 27.0, 10.0),
        use_session=False
    )
    assert success is False
    captured = capsys.readouterr()
    assert "❌ Error: Timeout tuple must contain exactly 2 elements" in captured.out

    # Boolean inside tuple
    success_bool = verify_council_session(
        url="http://mock-url/api",
        query="test query",
        timeout=(True, 27.0),
        use_session=False
    )
    assert success_bool is False
    captured_bool = capsys.readouterr()
    assert "❌ Error: Timeout elements must be positive numbers" in captured_bool.out

    # String inside tuple
    success_str = verify_council_session(
        url="http://mock-url/api",
        query="test query",
        timeout=("invalid", 27.0),
        use_session=False
    )
    assert success_str is False
    captured_str = capsys.readouterr()
    assert "❌ Error: Timeout elements must be positive numbers" in captured_str.out

    # Negative value inside tuple
    success_neg = verify_council_session(
        url="http://mock-url/api",
        query="test query",
        timeout=(3.05, -5.0),
        use_session=False
    )
    assert success_neg is False
    captured_neg = capsys.readouterr()
    assert "❌ Error: Timeout elements must be positive numbers" in captured_neg.out


def test_verify_council_session_traceback_too_deep(capsys):
    """Test that _get_exception_location breaks when traceback depth exceeds 100."""
    from verify_council_v2 import _get_exception_location
    
    # Create a chain of 105 traceback mock objects
    root_tb = MagicMock()
    curr = root_tb
    for _ in range(104):
        nxt = MagicMock()
        curr.tb_next = nxt
        curr = nxt
    curr.tb_next = None
    
    _get_exception_location(root_tb)

def test_verify_council_session_traceback_throws_exception_on_bool(capsys):
    """Test that _get_exception_location catches exceptions in the root logic safely."""
    from verify_council_v2 import _get_exception_location
    
    class ExceptionOnBool:
        def __bool__(self):
            raise RuntimeError("Forced bool exception")
            
    bad_tb = ExceptionOnBool()
    file_name, line_no = _get_exception_location(bad_tb)
    assert file_name == "unknown"
    assert line_no == "unknown"

def test_verify_council_session_close_called():
    """Test that verify_council_session calls close() on the response object to free resources."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "session_id": "test-session",
        "synthesis": "Test synthesis",
        "debate_flow": []
    }
    
    with patch("requests.post", return_value=mock_response) as mock_post:
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is True
        mock_response.close.assert_called_once()


def test_verify_council_session_http_error_attribute_error_safely(capsys):
    """Test that verify_council_session handles AttributeError on response text reading failure safely."""
    class BadResponseWithNoText:
        status_code = 500
        @property
        def text(self):
            raise AttributeError("Attribute 'text' is corrupted internally")
        def raise_for_status(self):
            http_error = requests.exceptions.HTTPError("500 Internal Server Error")
            http_error.response = self
            raise http_error

    bad_response = BadResponseWithNoText()
    with patch("requests.post", return_value=bad_response):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Failed: 500" in captured.out
        assert "<Failed to read response text: Attribute 'text' is corrupted internally>" in captured.out


def test_verify_council_session_http_error_content_decoding_error_leak(capsys):
    """Test that verify_council_session handles ContentDecodingError on response text reading safely without leaking it."""
    class BadResponseWithContentDecodingError:
        status_code = 500
        @property
        def text(self):
            import requests
            raise requests.exceptions.ContentDecodingError("Content decoding failed due to gzip corruption")
        def raise_for_status(self):
            import requests
            http_error = requests.exceptions.HTTPError("500 Internal Server Error")
            http_error.response = self
            raise http_error

    bad_response = BadResponseWithContentDecodingError()
    from unittest.mock import patch
    with patch("requests.post", return_value=bad_response):
        from verify_council_v2 import verify_council_session
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Failed: 500" in captured.out
        assert "<Failed to read response text: Content decoding failed due to gzip corruption>" in captured.out


def test_verify_council_session_ssl_error(capsys):
    """Test API call raising an SSLError."""
    with patch("requests.post", side_effect=requests.exceptions.SSLError("SSL verification failed")):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ SSL Error: SSL certificate verification failed" in captured.out


def test_verify_council_session_proxy_error(capsys):
    """Test API call raising a ProxyError."""
    with patch("requests.post", side_effect=requests.exceptions.ProxyError("Proxy connection failed")):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Proxy Error: Proxy connection failed" in captured.out


def test_verify_council_session_json_not_a_dict_detailed(capsys):
    """Test detailed message when response JSON is a list instead of a dict."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = ["not", "a", "dict"]

    with patch("requests.post", return_value=mock_response):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Error: Response JSON is not a dictionary (received type: list)" in captured.out


def test_verify_council_session_debate_flow_entry_not_a_dict_detailed(capsys):
    """Test detailed message when debate_flow entry is not a dict."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "session_id": "test-id",
        "synthesis": "text",
        "debate_flow": [123]
    }

    with patch("requests.post", return_value=mock_response):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Error: debate_flow entry at index 0 is not a dictionary (received type: int)" in captured.out


def test_verify_council_session_debate_flow_entry_agent_not_str_detailed(capsys):
    """Test detailed message when debate_flow entry agent is not a string."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "session_id": "test-id",
        "synthesis": "text",
        "debate_flow": [{"agent": 123, "summary": "summary"}]
    }

    with patch("requests.post", return_value=mock_response):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Error: debate_flow entry at index 0 'agent' is not a string (received type: int)" in captured.out


def test_verify_council_session_debate_flow_entry_summary_not_str_detailed(capsys):
    """Test detailed message when debate_flow entry summary is not a string."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "session_id": "test-id",
        "synthesis": "text",
        "debate_flow": [{"agent": "agent", "summary": 123}]
    }

    with patch("requests.post", return_value=mock_response):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Error: debate_flow entry at index 0 'summary' is not a string (received type: int)" in captured.out


def test_get_exception_location_dynamic_filename():
    """Test that _get_exception_location uses the module file name dynamically."""
    from verify_council_v2 import _get_exception_location
    import os
    from verify_council_v2 import __file__ as target_file
    
    mock_frame = MagicMock()
    mock_frame.f_code = MagicMock()
    mock_frame.f_code.co_filename = target_file
    
    mock_tb = MagicMock()
    mock_tb.tb_frame = mock_frame
    mock_tb.tb_next = None
    mock_tb.tb_lineno = 999
    
    fn, ln = _get_exception_location(mock_tb)
    assert fn == os.path.basename(target_file)
    assert ln == "999"


def test_handle_exception_direct(capsys):
    """Test that _handle_exception prints the formatted error and logs it."""
    from verify_council_v2 import _handle_exception
    from unittest.mock import patch
    
    # Create a dummy exception with a traceback
    try:
        raise ValueError("dummy error")
    except ValueError as e:
        err = e
        
    with patch("verify_council_v2.logger.error") as mock_log:
        _handle_exception(err, "Test Error Type", debug=True)
        
        captured = capsys.readouterr()
        assert "❌ Test Error Type at test_verify_council_v2.py:" in captured.out
        assert "dummy error" in captured.out
        mock_log.assert_called_once()
        # verify logs contain error type and message
        log_args = mock_log.call_args[0][0]
        assert "Test Error Type" in log_args
        assert "dummy error" in log_args

def test_get_exception_location_corrupted_traceback_logging():
    """Test that _get_exception_location safely handles errors and logs warnings when traversing corrupted traceback."""
    from verify_council_v2 import _get_exception_location
    from unittest.mock import patch
    
    # Create an object that raises an error when accessing tb_frame to trigger the safety net
    class BadTraceback:
        @property
        def tb_frame(self):
            raise RuntimeError("Corrupted traceback attribute access")
            
    bad_tb = BadTraceback()
    
    with patch("verify_council_v2.logger.warning") as mock_warning:
        fn, ln = _get_exception_location(bad_tb)
        assert fn == "unknown"
        assert ln == "unknown"
        mock_warning.assert_called_once()
        assert "Error traversing traceback" in mock_warning.call_args[0][0]


def test_verify_council_session_too_many_redirects(capsys):
    """Test API call raising TooManyRedirects exception."""
    with patch("requests.post", side_effect=requests.exceptions.TooManyRedirects("Too many redirects")):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Redirect Error: Too many redirects: Too many redirects" in captured.out

def test_verify_council_session_content_decoding_error(capsys):
    """Test API call raising ContentDecodingError exception."""
    with patch("requests.post", side_effect=requests.exceptions.ContentDecodingError("Content decoding failed")):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Content Decoding Error: Failed to decode response content: Content decoding failed" in captured.out

def test_verify_council_session_chunked_encoding_error(capsys):
    """Test API call raising ChunkedEncodingError exception."""
    with patch("requests.post", side_effect=requests.exceptions.ChunkedEncodingError("Chunked encoding broken")):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Chunked Encoding Error: Connection broken or incomplete chunk: Chunked encoding broken" in captured.out

def test_verify_council_session_process_response_request_exception(capsys):
    """Test when response.json() raises a RequestException during parsing."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.side_effect = requests.exceptions.RequestException("Stream connection broken during JSON read")

    with patch("requests.post", return_value=mock_response):
        success = verify_council_session(
            url="http://mock-url/api",
            query="test query",
            timeout=10.0,
            use_session=False
        )
        assert success is False
        captured = capsys.readouterr()
        assert "❌ Error: Failed to read response content: Stream connection broken during JSON read" in captured.out
