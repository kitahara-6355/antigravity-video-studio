import sys
import json
import os
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

# テスト対象をインポートできるように sys.path を設定
root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", ".."))
# もし上記の相対パスが正しくない場合のために絶対パスも考慮
workspace_root = r"C:\Users\PC_User\.gemini\antigravity\brain\39640fa1-98e0-42f5-8c76-60254ee602a3\.system_generated\worktrees\subagent-bug-hunter-Agent--assign-task-agents-py--self-178ddf5a"
if workspace_root not in sys.path:
    sys.path.insert(0, workspace_root)
    sys.path.insert(0, os.path.join(workspace_root, "backend"))

from backend.agents.orchestration.assign_task_agents import main
from backend.agents.orchestration.hub_common import TASK_QUEUE_PATH
from backend.agents.orchestration.atomic_io import safe_read_json, atomic_write_json

@pytest.fixture
def temp_task_queue(tmp_path, monkeypatch):
    # 一時的な task_queue.json のパスを設定
    temp_queue_file = tmp_path / "task_queue.json"
    
    # テスト用に初期のタスクデータを書き込む
    initial_data = {
        "tasks": [
            {"id": "task_1", "assigned_agent": None},
            {"id": "task_2", "assigned_agent": "AgentA"},
            {"id": "task_3", "assigned_agent": None}
        ]
    }
    atomic_write_json(str(temp_queue_file), initial_data)
    
    # hub_common.TASK_QUEUE_PATH を一時パスに差し替える
    import backend.agents.orchestration.assign_task_agents as ata
    monkeypatch.setattr(ata, "TASK_QUEUE_PATH", temp_queue_file)
    
    return temp_queue_file

def test_assign_via_stdin(temp_task_queue, monkeypatch, capsys):
    # stdin から json を読み込む場合
    monkeypatch.setattr(sys, "argv", ["assign_task_agents.py"])
    
    # sys.stdin.read をモック
    mock_input = json.dumps({"task_1": "AgentX", "task_3": "AgentY"})
    monkeypatch.setattr(sys.stdin, "read", lambda: mock_input)
    
    main()
    
    # 結果の確認
    updated_queue = safe_read_json(str(temp_task_queue))
    tasks = {t["id"]: t.get("assigned_agent") for t in updated_queue["tasks"]}
    
    assert tasks["task_1"] == "AgentX"
    assert tasks["task_2"] == "AgentA"  # 変更なし
    assert tasks["task_3"] == "AgentY"
    
    captured = capsys.readouterr()
    assert "Successfully updated" in captured.out

def test_assign_via_json_file(temp_task_queue, monkeypatch, tmp_path, capsys):
    # 引数として JSON ファイルパスを渡す場合
    assignment_file = tmp_path / "assignments.json"
    assignment_data = {"task_1": "AgentZ"}
    with open(assignment_file, "w", encoding="utf-8") as f:
        json.dump(assignment_data, f)
        
    monkeypatch.setattr(sys, "argv", ["assign_task_agents.py", str(assignment_file)])
    
    main()
    
    updated_queue = safe_read_json(str(temp_task_queue))
    tasks = {t["id"]: t.get("assigned_agent") for t in updated_queue["tasks"]}
    
    assert tasks["task_1"] == "AgentZ"
    
    captured = capsys.readouterr()
    assert "Successfully updated" in captured.out

def test_assign_via_json_string(temp_task_queue, monkeypatch, capsys):
    # 引数として直接 JSON 文字列を渡す場合
    json_str = json.dumps({"task_3": "AgentW"})
    monkeypatch.setattr(sys, "argv", ["assign_task_agents.py", json_str])
    
    main()
    
    updated_queue = safe_read_json(str(temp_task_queue))
    tasks = {t["id"]: t.get("assigned_agent") for t in updated_queue["tasks"]}
    
    assert tasks["task_3"] == "AgentW"
    
    captured = capsys.readouterr()
    assert "Successfully updated" in captured.out

def test_invalid_stdin_json(temp_task_queue, monkeypatch, capsys):
    # stdin に不正な JSON が渡された場合
    monkeypatch.setattr(sys, "argv", ["assign_task_agents.py"])
    monkeypatch.setattr(sys.stdin, "read", lambda: "{invalid json")
    
    with pytest.raises(SystemExit) as excinfo:
        main()
    
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Failed to parse JSON from stdin" in captured.out

def test_invalid_file_json(temp_task_queue, monkeypatch, tmp_path, capsys):
    # 引数のファイルの中身が不正な JSON の場合
    assignment_file = tmp_path / "assignments.json"
    with open(assignment_file, "w", encoding="utf-8") as f:
        f.write("{invalid json")
        
    monkeypatch.setattr(sys, "argv", ["assign_task_agents.py", str(assignment_file)])
    
    with pytest.raises(SystemExit) as excinfo:
        main()
        
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Failed to parse JSON from file" in captured.out

def test_missing_file(temp_task_queue, monkeypatch, tmp_path, capsys):
    # 引数のファイルが存在しない場合 (.json で終わる場合)
    # os.path.exists が False になるため、直接引数文字列のパースを試み、
    # パス文字列は JSON としてパースエラーになる
    non_existent_file = tmp_path / "non_existent.json"
    monkeypatch.setattr(sys, "argv", ["assign_task_agents.py", str(non_existent_file)])
    
    with pytest.raises(SystemExit) as excinfo:
        main()
        
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Failed to parse JSON argument" in captured.out

def test_invalid_arg_json_string(temp_task_queue, monkeypatch, capsys):
    # 引数のJSON文字列が不正な場合
    monkeypatch.setattr(sys, "argv", ["assign_task_agents.py", "{invalid json"])
    
    with pytest.raises(SystemExit) as excinfo:
        main()
        
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Failed to parse JSON argument" in captured.out

def test_not_dictionary_json(temp_task_queue, monkeypatch, capsys):
    # JSON であるが、辞書型ではない場合
    json_list = json.dumps(["task_1", "AgentX"])
    monkeypatch.setattr(sys, "argv", ["assign_task_agents.py", json_list])
    
    with pytest.raises(SystemExit) as excinfo:
        main()
        
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Invalid assignments format: Expected a JSON object" in captured.out

def test_no_matching_tasks(temp_task_queue, monkeypatch, capsys):
    # 割り当てはあるが、task_queue にマッチするタスクIDがない場合
    json_str = json.dumps({"non_existent_task": "AgentX"})
    monkeypatch.setattr(sys, "argv", ["assign_task_agents.py", json_str])
    
    main()
    
    updated_queue = safe_read_json(str(temp_task_queue))
    tasks = {t["id"]: t.get("assigned_agent") for t in updated_queue["tasks"]}
    assert tasks["task_1"] is None
    
    captured = capsys.readouterr()
    assert "No matching tasks found to update." in captured.out
