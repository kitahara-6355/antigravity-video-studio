import json
from unittest import mock
import pytest
import os

from backend.scratch import debug_mapping3

def test_log_file_not_found(capsys):
    """Tests that read_transcript_lines returns None when log file does not exist."""
    with mock.patch("os.path.exists", return_value=False):
        res = debug_mapping3.read_transcript_lines("dummy_path")
        assert res is None
        captured = capsys.readouterr()
        assert "Not found" in captured.out

def test_no_dispatch_log_found(capsys):
    """Tests that analyze_transcript prints appropriate message when no dispatch log is found."""
    mock_data = [
        '{"type": "SOME_OTHER_EVENT", "status": "DONE"}',
        '{"type": "INVOKE_SUBAGENT", "status": "FAILED"}'
    ]
    mock_file = mock.mock_open(read_data="\n".join(mock_data))
    
    with mock.patch("os.path.exists", return_value=True), \
         mock.patch("builtins.open", mock_file):
        res = debug_mapping3.analyze_transcript("dummy_path")
        captured = capsys.readouterr()
        assert "No dispatch log found" in captured.out
        assert res == []

def test_dispatch_log_found_and_matched(capsys):
    """Tests that analyze_transcript successfully parses conversation ID and worktree path."""
    content_payload = (
        'Some intro text... "conversationId": "conv-1234" '
        '"workspaceUris": ["file:///C:/Users/PC_User/workspace/subagent-thumbnail-Agent-self-12d50add"] '
        'subagent-thumbnail-Agent-self-12d50add'
    )
    log_entry = {
        "type": "INVOKE_SUBAGENT",
        "status": "DONE",
        "content": content_payload
    }
    mock_data = [
        json.dumps(log_entry)
    ]
    mock_file = mock.mock_open(read_data="\n".join(mock_data))
    
    with mock.patch("os.path.exists", return_value=True), \
         mock.patch("builtins.open", mock_file):
        res = debug_mapping3.analyze_transcript("dummy_path")
        captured = capsys.readouterr()
        assert "Found dispatch log at Line 0" in captured.out
        assert "conv_id: conv-1234" in captured.out
        assert "wt_path: C:/Users/PC_User/workspace/subagent-thumbnail-Agent-self-12d50add" in captured.out
        assert "group_raw: thumbnail" in captured.out
        
        assert len(res) == 1
        assert res[0]["conv_id"] == "conv-1234"
        assert res[0]["wt_path"] == "C:/Users/PC_User/workspace/subagent-thumbnail-Agent-self-12d50add"
        assert res[0]["group_raw"] == "thumbnail"

def test_dispatch_log_partial_match(capsys):
    """Tests partial match case where only conversation ID is present."""
    content_payload = (
        'Some intro text... "conversationId": "conv-1234" '
        'other fields but no workspaceUris and no subagent match'
    )
    log_entry = {
        "type": "INVOKE_SUBAGENT",
        "status": "DONE",
        "content": content_payload
    }
    mock_data = [
        json.dumps(log_entry)
    ]
    mock_file = mock.mock_open(read_data="\n".join(mock_data))
    
    with mock.patch("os.path.exists", return_value=True), \
         mock.patch("builtins.open", mock_file):
        res = debug_mapping3.analyze_transcript("dummy_path")
        captured = capsys.readouterr()
        assert "Found dispatch log at Line 0" in captured.out
        assert "conv_id: conv-1234" in captured.out
        assert "wt_path: None" in captured.out
        
        assert len(res) == 1
        assert res[0]["conv_id"] == "conv-1234"
        assert res[0]["wt_path"] == "None"

def test_json_loads_exception(capsys):
    """Tests that JSON decode errors are safely ignored and search continues."""
    mock_data = [
        json.dumps({
            "type": "INVOKE_SUBAGENT",
            "status": "DONE",
            "content": '"conversationId": "conv-5678" "workspaceUris": ["file:///path"] subagent-core-Agent-'
        }),
        "invalid json { {"
    ]
    mock_file = mock.mock_open(read_data="\n".join(mock_data))
    
    with mock.patch("os.path.exists", return_value=True), \
         mock.patch("builtins.open", mock_file):
        res = debug_mapping3.analyze_transcript("dummy_path")
        captured = capsys.readouterr()
        assert "Found dispatch log at Line 0" in captured.out
        assert len(res) == 1

def test_content_not_string(capsys):
    """Tests that non-string content yields an appropriate warning print."""
    log_entry = {
        "type": "INVOKE_SUBAGENT",
        "status": "DONE",
        "content": {"not_a_string": True}
    }
    mock_data = [
        json.dumps(log_entry)
    ]
    mock_file = mock.mock_open(read_data="\n".join(mock_data))
    
    with mock.patch("os.path.exists", return_value=True), \
         mock.patch("builtins.open", mock_file):
        res = debug_mapping3.analyze_transcript("dummy_path")
        captured = capsys.readouterr()
        assert "Found dispatch log at Line 0" in captured.out
        assert "Content is not a string" in captured.out
        assert res == []

def test_file_read_permission_error(capsys):
    """Tests file read permission error handling."""
    with mock.patch("os.path.exists", return_value=True), \
         mock.patch("builtins.open", side_effect=PermissionError("Permission denied")):
        res = debug_mapping3.analyze_transcript("dummy_path")
        captured = capsys.readouterr()
        assert "Error reading file: Permission denied" in captured.out
        assert res is None

def test_file_read_os_error(capsys):
    """Tests generic OSError file read handling."""
    with mock.patch("os.path.exists", return_value=True), \
         mock.patch("builtins.open", side_effect=OSError("Disk error")):
        res = debug_mapping3.analyze_transcript("dummy_path")
        captured = capsys.readouterr()
        assert "Error reading file: Disk error" in captured.out
        assert res is None

def test_non_dict_json_data(capsys):
    """Tests that non-dict JSON lines are ignored during transcript analysis."""
    mock_data = [
        json.dumps({
            "type": "INVOKE_SUBAGENT",
            "status": "DONE",
            "content": '"conversationId": "conv-1111"'
        }),
        "[1, 2, 3]",
        '"just a string"',
        "123"
    ]
    mock_file = mock.mock_open(read_data="\n".join(mock_data))
    
    with mock.patch("os.path.exists", return_value=True), \
         mock.patch("builtins.open", mock_file):
        res = debug_mapping3.analyze_transcript("dummy_path")
        captured = capsys.readouterr()
        assert "Found dispatch log at Line 0" in captured.out
        assert "conv_id: conv-1111" in captured.out
        assert len(res) == 1

def test_empty_file_transcript(capsys):
    """Tests empty transcript file handling."""
    mock_file = mock.mock_open(read_data="")
    with mock.patch("os.path.exists", return_value=True), \
         mock.patch("builtins.open", mock_file):
        res = debug_mapping3.analyze_transcript("dummy_path")
        captured = capsys.readouterr()
        assert "No dispatch log found" in captured.out
        assert res == []

def test_reverse_readline():
    """Tests the reverse_readline generator with multiple mock lines."""
    mock_data = b"line1\nline2\nline3\n"
    mock_file = mock.mock_open(read_data=mock_data)
    
    with mock.patch("builtins.open", mock_file):
        lines = list(debug_mapping3.reverse_readline("dummy_path", buf_size=2))
        # reverse_readline returns lines in reverse order, ignoring final trailing empty lines
        assert lines == ["line3", "line2", "line1"]

def test_workspace_uris_multiple_items(capsys):
    """Tests parsing workspaceUris when multiple items are present in the list."""
    content_payload = (
        '"conversationId": "conv-9999" '
        '"workspaceUris": ["file:///C:/Users/PC_User/workspace/subagent-1", "file:///C:/Users/PC_User/workspace/subagent-2"] '
        'subagent-test-Agent-self-123'
    )
    results = debug_mapping3.parse_and_print_subagent_info(content_payload)
    assert len(results) == 1
    assert results[0]["conv_id"] == "conv-9999"
    assert results[0]["wt_path"] == "C:/Users/PC_User/workspace/subagent-1"
    assert results[0]["group_raw"] == "test"

def test_workspace_uris_non_file_scheme(capsys):
    """Tests workspaceUris parsing when uri doesn't start with file:/// scheme."""
    content_payload = (
        '"conversationId": "conv-9999" '
        '"workspaceUris": ["C:/Users/PC_User/workspace/subagent-3"] '
    )
    results = debug_mapping3.parse_and_print_subagent_info(content_payload)
    assert len(results) == 1
    assert results[0]["wt_path"] == "C:/Users/PC_User/workspace/subagent-3"

def test_find_last_dispatch_log_efficient():
    """Tests find_last_dispatch_log_efficient parses the last matching log correctly."""
    mock_data = [
        json.dumps({"type": "INVOKE_SUBAGENT", "status": "DONE", "content": '"conversationId": "conv-9999"'}),
        json.dumps({"type": "INVOKE_SUBAGENT", "status": "FAILED", "content": '"conversationId": "conv-8888"'}),
        "invalid json line"
    ]
    # By mapping open to a binary mock, mock_open works with bytes if we provide binary read_data
    mock_file = mock.mock_open(read_data=b"\n".join([line.encode("utf-8") if isinstance(line, str) else line for line in mock_data]))
    
    with mock.patch("os.path.exists", return_value=True), \
         mock.patch("builtins.open", mock_file):
        line_idx, parsed_data = debug_mapping3.find_last_dispatch_log_efficient("dummy_path")
        # Line index 0 is INVOKE_SUBAGENT and status DONE
        assert line_idx == 0
        assert parsed_data is not None
        assert parsed_data["type"] == "INVOKE_SUBAGENT"
        assert parsed_data["status"] == "DONE"
