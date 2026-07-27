import json
import logging
import pytest
from agents.context_resolver import ContextResolver

def test_resolve_subtitles_success(tmp_path):
    subtitle_file = tmp_path / "subtitles.json"
    data = [
        {"text": "Hello"},
        {"text": "world"},
        {"text": "this is"},
        {"text": "a test."}
    ]
    with open(subtitle_file, "w", encoding="utf-8") as f:
        json.dump(data, f)

    result = ContextResolver.resolve_subtitles(str(subtitle_file))
    assert result == "Hello world this is a test."

def test_resolve_subtitles_file_not_found(caplog):
    non_existent_file = "non_existent_file_12345.json"
    with caplog.at_level(logging.WARNING):
        result = ContextResolver.resolve_subtitles(non_existent_file)
    
    assert result == "No subtitle data available."
    assert any("Subtitle file not found at" in record.message for record in caplog.records)

def test_resolve_subtitles_corrupted_json(tmp_path, caplog):
    corrupted_file = tmp_path / "corrupted.json"
    with open(corrupted_file, "w", encoding="utf-8") as f:
        f.write("{invalid json")

    with caplog.at_level(logging.ERROR):
        result = ContextResolver.resolve_subtitles(str(corrupted_file))

    assert "Error loading subtitles:" in result
    assert any("Subtitle JSON format invalid:" in record.message for record in caplog.records)

def test_get_deep_context_block_with_vision(tmp_path):
    subtitle_file = tmp_path / "subtitles.json"
    data = [{"text": "Hello world"}]
    with open(subtitle_file, "w", encoding="utf-8") as f:
        json.dump(data, f)

    vision = "To test context resolver"
    result = ContextResolver.get_deep_context_block(str(subtitle_file), vision=vision)

    assert "## 🕯️ DEEP CONTEXT: CURRENT VIDEO SOUL" in result
    assert f'- **Vision/Commitment**: "{vision}"' in result
    assert "Hello world" in result

def test_get_deep_context_block_without_vision(tmp_path):
    subtitle_file = tmp_path / "subtitles.json"
    data = [{"text": "Hello world"}]
    with open(subtitle_file, "w", encoding="utf-8") as f:
        json.dump(data, f)

    result = ContextResolver.get_deep_context_block(str(subtitle_file))

    assert "## 🕯️ DEEP CONTEXT: CURRENT VIDEO SOUL" in result
    assert '- **Vision/Commitment**: "No specific vision provided for this session."' in result
    assert "Hello world" in result

def test_get_deep_context_block_truncation(tmp_path):
    subtitle_file = tmp_path / "subtitles.json"
    long_text = "a" * 10005
    data = [{"text": long_text}]
    with open(subtitle_file, "w", encoding="utf-8") as f:
        json.dump(data, f)

    result = ContextResolver.get_deep_context_block(str(subtitle_file))

    expected_substring = "a" * 10000 + "... (truncated)"
    assert expected_substring in result


def test_resolve_subtitles_non_list_json(tmp_path, caplog):
    subtitle_file = tmp_path / "invalid_dict.json"
    data = {"error": "not a list"}
    with open(subtitle_file, "w", encoding="utf-8") as f:
        json.dump(data, f)

    with caplog.at_level(logging.ERROR):
        result = ContextResolver.resolve_subtitles(str(subtitle_file))

    assert "Error loading subtitles:" in result
    assert "Subtitle data is not a list" in result
    assert any("Subtitle data is not a list" in record.message for record in caplog.records)

def test_resolve_subtitles_none_value(tmp_path):
    subtitle_file = tmp_path / "none_value.json"
    data = [{"text": "Hello"}, {"text": None}, {"text": "World"}]
    with open(subtitle_file, "w", encoding="utf-8") as f:
        json.dump(data, f)

    result = ContextResolver.resolve_subtitles(str(subtitle_file))
    assert result == "Hello  World"

def test_resolve_subtitles_invalid_element(tmp_path, caplog):
    subtitle_file = tmp_path / "invalid_element.json"
    data = [{"text": "Hello"}, "invalid_string_element", {"text": "World"}]
    with open(subtitle_file, "w", encoding="utf-8") as f:
        json.dump(data, f)

    with caplog.at_level(logging.WARNING):
        result = ContextResolver.resolve_subtitles(str(subtitle_file))

    assert result == "Hello World"
    assert any("Skipping non-dict segment in subtitles:" in record.message for record in caplog.records)

def test_get_deep_context_block_custom_truncation(tmp_path):
    subtitle_file = tmp_path / "subtitles.json"
    long_text = "a" * 55
    data = [{"text": long_text}]
    with open(subtitle_file, "w", encoding="utf-8") as f:
        json.dump(data, f)

    result = ContextResolver.get_deep_context_block(str(subtitle_file), max_length=50)

    expected_substring = "a" * 50 + "... (truncated)"
    assert expected_substring in result


def test_resolve_subtitles_invalid_path_types(caplog):
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
