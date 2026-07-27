import os
import json
import tempfile
import pytest
from scratch.find_tdr import find_tdr_entries, get_default_tdr_path, main
from unittest.mock import patch, mock_open
import runpy

def test_find_tdr_entries_success():
    dummy_data = {
        "entries": [
            {
                "debt_id": "TD001",
                "file_path": "backend/agents/cleanup_disk.py",
                "line_number": 42,
                "status": "pending",
                "category": "performance"
            },
            {
                "debt_id": "TD002",
                "file_path": "backend/agents/other.py",
                "line_number": 10,
                "status": "resolved",
                "category": "refactor"
            }
        ]
    }
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', encoding='utf-8') as tmp:
        json.dump(dummy_data, tmp)
        tmp_name = tmp.name

    try:
        matches = find_tdr_entries(tmp_name)
        assert len(matches) == 1
        assert matches[0]["debt_id"] == "TD001"
        assert "cleanup_disk.py" in matches[0]["file_path"]
    finally:
        os.unlink(tmp_name)

def test_find_tdr_entries_no_match():
    dummy_data = {
        "entries": [
            {
                "debt_id": "TD002",
                "file_path": "backend/agents/other.py",
                "line_number": 10,
                "status": "resolved",
                "category": "refactor"
            }
        ]
    }
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', encoding='utf-8') as tmp:
        json.dump(dummy_data, tmp)
        tmp_name = tmp.name

    try:
        matches = find_tdr_entries(tmp_name)
        assert len(matches) == 0
    finally:
        os.unlink(tmp_name)

def test_find_tdr_entries_file_not_found():
    matches = find_tdr_entries("non_existent_file.json")
    assert len(matches) == 0

def test_find_tdr_entries_json_decode_error(capsys):
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', encoding='utf-8') as tmp:
        tmp.write("invalid json content")
        tmp_name = tmp.name

    try:
        matches = find_tdr_entries(tmp_name)
        assert len(matches) == 0
        captured = capsys.readouterr()
        assert "Error parsing JSON" in captured.out
    finally:
        os.unlink(tmp_name)

def test_find_tdr_entries_invalid_root_type(capsys):
    dummy_data = ["not", "a", "dict"]
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', encoding='utf-8') as tmp:
        json.dump(dummy_data, tmp)
        tmp_name = tmp.name

    try:
        matches = find_tdr_entries(tmp_name)
        assert len(matches) == 0
        captured = capsys.readouterr()
        assert "Invalid data format" in captured.out
    finally:
        os.unlink(tmp_name)

def test_find_tdr_entries_invalid_entries_type(capsys):
    dummy_data = {"entries": "not a list"}
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', encoding='utf-8') as tmp:
        json.dump(dummy_data, tmp)
        tmp_name = tmp.name

    try:
        matches = find_tdr_entries(tmp_name)
        assert len(matches) == 0
        captured = capsys.readouterr()
        assert "Invalid entries format" in captured.out
    finally:
        os.unlink(tmp_name)

def test_find_tdr_entries_invalid_entry_format():
    dummy_data = {
        "entries": [
            "not a dict entry",
            {"debt_id": "TD003", "file_path": 12345}
        ]
    }
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', encoding='utf-8') as tmp:
        json.dump(dummy_data, tmp)
        tmp_name = tmp.name

    try:
        matches = find_tdr_entries(tmp_name)
        assert len(matches) == 0
    finally:
        os.unlink(tmp_name)


def test_get_default_tdr_path():
    path = get_default_tdr_path()
    assert path.endswith(os.path.join("agents", "memory", "technical_debt_index.json"))


def test_find_tdr_entries_env_path():
    dummy_data = {"entries": [{"debt_id": "TD001", "file_path": "backend/agents/cleanup_disk.py"}]}
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', encoding='utf-8') as tmp:
        json.dump(dummy_data, tmp)
        tmp_name = tmp.name

    try:
        with patch.dict(os.environ, {"TDR_INDEX_PATH": tmp_name}):
            matches = find_tdr_entries(None)
            assert len(matches) == 1
            assert matches[0]["debt_id"] == "TD001"
    finally:
        os.unlink(tmp_name)


def test_find_tdr_entries_default_path_exists():
    dummy_data = {"entries": [{"debt_id": "TD001", "file_path": "backend/agents/cleanup_disk.py"}]}
    default_path = get_default_tdr_path()
    
    def mock_exists(path):
        if path == default_path:
            return True
        return False

    mock_data_str = json.dumps(dummy_data)
    
    with patch.dict(os.environ, {}, clear=True), \
         patch('scratch.find_tdr.os.path.exists', side_effect=mock_exists), \
         patch('builtins.open', mock_open(read_data=mock_data_str)):
        matches = find_tdr_entries(None)
        assert len(matches) == 1
        assert matches[0]["debt_id"] == "TD001"


def test_find_tdr_entries_fallback_path_exists():
    dummy_data = {"entries": [{"debt_id": "TD001", "file_path": "backend/agents/cleanup_disk.py"}]}
    fallback_path = r"C:\Users\PC_User\Desktop\script\video-automation\backend\agents\memory\technical_debt_index.json"
    
    def mock_exists(path):
        if path == fallback_path:
            return True
        return False

    mock_data_str = json.dumps(dummy_data)
    
    with patch.dict(os.environ, {}, clear=True), \
         patch('scratch.find_tdr.get_default_tdr_path', return_value="non_existent_default_path.json"), \
         patch('scratch.find_tdr.os.path.exists', side_effect=mock_exists), \
         patch('builtins.open', mock_open(read_data=mock_data_str)):
        matches = find_tdr_entries(None)
        assert len(matches) == 1
        assert matches[0]["debt_id"] == "TD001"


def test_find_tdr_entries_general_exception(capsys):
    with patch('scratch.find_tdr.os.path.exists', return_value=True), \
         patch('builtins.open', side_effect=PermissionError("Permission denied")):
        matches = find_tdr_entries("some_file.json")
        assert matches == []
        captured = capsys.readouterr()
        assert "Error reading file" in captured.out


def test_main_path_exists(capsys):
    dummy_data = {"entries": [{"debt_id": "TD001", "file_path": "backend/agents/cleanup_disk.py", "line_number": 42, "status": "pending", "category": "performance"}]}
    mock_data_str = json.dumps(dummy_data)
    
    with patch.dict(os.environ, {"TDR_INDEX_PATH": "dummy_path.json"}), \
         patch('scratch.find_tdr.os.path.exists', return_value=True), \
         patch('builtins.open', mock_open(read_data=mock_data_str)):
        main()
        captured = capsys.readouterr()
        assert "Found 1 entries matching cleanup_disk.py:" in captured.out
        assert "TD001" in captured.out


def test_main_fallback_exists(capsys):
    dummy_data = {"entries": [{"debt_id": "TD001", "file_path": "backend/agents/cleanup_disk.py", "line_number": 42, "status": "pending", "category": "performance"}]}
    fallback_path = r"C:\Users\PC_User\Desktop\script\video-automation\backend\agents\memory\technical_debt_index.json"
    
    def mock_exists(path):
        if path == fallback_path:
            return True
        return False
        
    mock_data_str = json.dumps(dummy_data)
    
    with patch.dict(os.environ, {}, clear=True), \
         patch('scratch.find_tdr.get_default_tdr_path', return_value="non_existent_default_path.json"), \
         patch('scratch.find_tdr.os.path.exists', side_effect=mock_exists), \
         patch('builtins.open', mock_open(read_data=mock_data_str)):
        main()
        captured = capsys.readouterr()
        assert "Found 1 entries matching cleanup_disk.py:" in captured.out
        assert "TD001" in captured.out


def test_main_not_found(capsys):
    with patch.dict(os.environ, {}, clear=True), \
         patch('scratch.find_tdr.os.path.exists', return_value=False):
        main()
        captured = capsys.readouterr()
        assert "Not found" in captured.out


def test_main_execution_via_entrypoint():
    import scratch.find_tdr
    module_path = scratch.find_tdr.__file__
    
    with patch('scratch.find_tdr.os.path.exists', return_value=False), \
         patch('builtins.print') as mock_print:
        runpy.run_path(module_path, run_name="__main__")
        mock_print.assert_called_with("Not found")


def test_find_tdr_entries_no_paths_exist():
    with patch.dict(os.environ, {}, clear=True), \
         patch('scratch.find_tdr.os.path.exists', return_value=False):
        matches = find_tdr_entries(None)
        assert matches == []
