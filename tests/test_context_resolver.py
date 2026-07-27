import json
import os
import pytest
from unittest.mock import patch, mock_open

from backend.agents.context_resolver import ContextResolver

def test_resolve_subtitles_file_not_exists():
    with patch("os.path.exists", return_value=False):
        result = ContextResolver.resolve_subtitles("non_existent_file.json")
        assert result == "No subtitle data available."

def test_resolve_subtitles_not_list():
    invalid_data = {"text": "hello"}
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=json.dumps(invalid_data))):
            result = ContextResolver.resolve_subtitles("dummy.json")
            assert "Subtitle data is not a list" in result

def test_resolve_subtitles_valid_list():
    valid_data = [
        {"text": "Hello"},
        {"text": "World"}
    ]
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=json.dumps(valid_data))):
            result = ContextResolver.resolve_subtitles("dummy.json")
            assert result == "Hello World"

def test_resolve_subtitles_skip_non_dict():
    data_with_non_dict = [
        {"text": "Hello"},
        "invalid_element",
        {"text": "World"}
    ]
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=json.dumps(data_with_non_dict))):
            result = ContextResolver.resolve_subtitles("dummy.json")
            assert result == "Hello World"

def test_resolve_subtitles_missing_or_none_text():
    data_with_missing_text = [
        {"text": "Hello"},
        {"no_text": "here"},
        {"text": None},
        {"text": "World"}
    ]
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=json.dumps(data_with_missing_text))):
            result = ContextResolver.resolve_subtitles("dummy.json")
            assert result == "Hello   World"

def test_resolve_subtitles_non_string_text():
    data_with_number = [
        {"text": 123},
        {"text": True}
    ]
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=json.dumps(data_with_number))):
            result = ContextResolver.resolve_subtitles("dummy.json")
            assert result == "123 True"

def test_resolve_subtitles_exception_handling():
    with patch("os.path.exists", return_value=True):
        # OSError
        with patch("builtins.open", side_effect=OSError("Mock OSError")):
            result = ContextResolver.resolve_subtitles("dummy.json")
            assert "Error loading subtitles: Mock OSError" in result
            
        # json.JSONDecodeError
        with patch("builtins.open", mock_open(read_data="invalid json")):
            result = ContextResolver.resolve_subtitles("dummy.json")
            assert "Error loading subtitles:" in result

        # TypeError
        with patch("json.load", side_effect=TypeError("Mock TypeError")):
            with patch("builtins.open", mock_open(read_data="[]")):
                result = ContextResolver.resolve_subtitles("dummy.json")
                assert "Error loading subtitles: Mock TypeError" in result

        # ValueError
        with patch("json.load", side_effect=ValueError("Mock ValueError")):
            with patch("builtins.open", mock_open(read_data="[]")):
                result = ContextResolver.resolve_subtitles("dummy.json")
                assert "Error loading subtitles: Mock ValueError" in result

        # RuntimeError
        with patch("json.load", side_effect=RuntimeError("Mock RuntimeError")):
            with patch("builtins.open", mock_open(read_data="[]")):
                result = ContextResolver.resolve_subtitles("dummy.json")
                assert "Error loading subtitles: Mock RuntimeError" in result

        # AttributeError
        with patch("json.load", side_effect=AttributeError("Mock AttributeError")):
            with patch("builtins.open", mock_open(read_data="[]")):
                result = ContextResolver.resolve_subtitles("dummy.json")
                assert "Error loading subtitles: Mock AttributeError" in result

def test_get_deep_context_block_no_vision():
    valid_data = [{"text": "Hello"}, {"text": "World"}]
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=json.dumps(valid_data))):
            context = ContextResolver.get_deep_context_block("dummy.json")
            assert "No specific vision provided for this session." in context
            assert "Hello World" in context

def test_get_deep_context_block_with_vision():
    valid_data = [{"text": "Hello"}, {"text": "World"}]
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=json.dumps(valid_data))):
            context = ContextResolver.get_deep_context_block("dummy.json", vision="My Vision")
            assert "My Vision" in context
            assert "Hello World" in context

def test_get_deep_context_block_truncated():
    valid_data = [{"text": "A" * 100}]
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=json.dumps(valid_data))):
            context = ContextResolver.get_deep_context_block("dummy.json", max_length=50)
            assert "A" * 50 + "... (truncated)" in context


def test_resolve_subtitles_invalid_path_types_mock(caplog):
    import logging
    # Test with None as file_path
    with caplog.at_level(logging.WARNING):
        result = ContextResolver.resolve_subtitles(None)
    assert result == "No subtitle data available."
    assert any("Subtitle file invalid path type" in record.message for record in caplog.records)

    # Test with int as file_path
    with caplog.at_level(logging.WARNING):
        result = ContextResolver.resolve_subtitles(123)
    assert result == "No subtitle data available."
    assert any("Subtitle file invalid path type" in record.message for record in caplog.records)


def test_resolve_subtitles_specific_exception_logging(caplog):
    import logging
    with patch("os.path.exists", return_value=True):
        # JSONDecodeError
        with patch("builtins.open", mock_open(read_data="invalid json")):
            with caplog.at_level(logging.ERROR):
                caplog.clear()
                result = ContextResolver.resolve_subtitles("dummy.json")
                assert "Error loading subtitles:" in result
                assert any("Subtitle JSON format invalid" in record.message for record in caplog.records)

        # UnicodeDecodeError
        with patch("json.load", side_effect=UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")):
            with patch("builtins.open", mock_open(read_data="")):
                with caplog.at_level(logging.ERROR):
                    caplog.clear()
                    result = ContextResolver.resolve_subtitles("dummy.json")
                    assert "Error loading subtitles:" in result
                    assert any("Subtitle file encoding error" in record.message for record in caplog.records)

        # OSError (e.g. PermissionError)
        with patch("builtins.open", side_effect=PermissionError("Mock PermissionError")):
            with caplog.at_level(logging.ERROR):
                caplog.clear()
                result = ContextResolver.resolve_subtitles("dummy.json")
                assert "Error loading subtitles:" in result
                assert any("Subtitle file access error" in record.message for record in caplog.records)

        # TypeError
        with patch("json.load", side_effect=TypeError("Mock TypeError")):
            with patch("builtins.open", mock_open(read_data="[]")):
                with caplog.at_level(logging.ERROR):
                    caplog.clear()
                    result = ContextResolver.resolve_subtitles("dummy.json")
                    assert "Error loading subtitles:" in result
                    assert any("Subtitle structure conversion error" in record.message for record in caplog.records)

        # RuntimeError
        with patch("json.load", side_effect=RuntimeError("Mock RuntimeError")):
            with patch("builtins.open", mock_open(read_data="[]")):
                with caplog.at_level(logging.ERROR):
                    caplog.clear()
                    result = ContextResolver.resolve_subtitles("dummy.json")
                    assert "Error loading subtitles:" in result
                    assert any("Subtitle processing runtime error" in record.message for record in caplog.records)

def test_resolve_subtitles_real_json_error(tmp_path):
    # Create invalid JSON file
    bad_json_file = tmp_path / "bad.json"
    bad_json_file.write_text("{invalid json", encoding="utf-8")
    
    result = ContextResolver.resolve_subtitles(str(bad_json_file))
    assert "Error loading subtitles:" in result

def test_resolve_subtitles_real_unicode_error(tmp_path):
    # Create file with non-utf8 content (shift-jis)
    bad_encoding_file = tmp_path / "bad_encoding.json"
    with open(bad_encoding_file, "wb") as f:
        f.write("あいうえお".encode("shift_jis"))
        
    result = ContextResolver.resolve_subtitles(str(bad_encoding_file))
    assert "Error loading subtitles:" in result
