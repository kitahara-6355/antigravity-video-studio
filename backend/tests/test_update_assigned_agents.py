import sys
import json
import pytest
import runpy
from pathlib import Path
from backend.agents.orchestration.update_assigned_agents import (
    main,
    parse_arguments,
    load_task_queue,
    update_tasks,
    save_task_queue,
)

def test_main_missing_arguments(monkeypatch, capsys):
    # 引数が足りない場合
    monkeypatch.setattr(sys, "argv", ["update_assigned_agents.py"])
    
    with pytest.raises(SystemExit) as exc_info:
        main()
        
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Usage:" in captured.out

def test_main_queue_file_not_found(monkeypatch, tmp_path, capsys):
    # 引数はあるが、ファイルが存在しない場合
    monkeypatch.setattr(sys, "argv", ["update_assigned_agents.py", '{"task_1": "agent_1"}'])
    
    # 一時ディレクトリに移動し、カレントディレクトリからの相対パスでファイルがない状態を作る
    monkeypatch.chdir(tmp_path)
    
    with pytest.raises(SystemExit) as exc_info:
        main()
        
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Queue path not found" in captured.out

def test_main_successful_update(monkeypatch, tmp_path, capsys):
    # 正常な更新
    monkeypatch.setattr(sys, "argv", ["update_assigned_agents.py", '{"task_1": "agent_1", "task_2": "agent_2"}'])
    
    # 一時ディレクトリに移動し、ディレクトリ構造とファイルを作成
    monkeypatch.chdir(tmp_path)
    queue_dir = tmp_path / "backend" / "agents" / "orchestration"
    queue_dir.mkdir(parents=True, exist_ok=True)
    
    initial_queue = {
        "tasks": [
            {"id": "task_1", "assigned_agent": "old_agent"},
            {"id": "task_3", "assigned_agent": "some_agent"}
        ]
    }
    queue_file = queue_dir / "task_queue.json"
    with open(queue_file, "w", encoding="utf-8") as f:
        json.dump(initial_queue, f)
        
    main()
    
    captured = capsys.readouterr()
    assert "Successfully updated assigned_agents in task_queue.json" in captured.out
    
    # ファイルの更新内容を確認
    with open(queue_file, "r", encoding="utf-8") as f:
        updated_queue = json.load(f)
        
    assert updated_queue["tasks"][0]["assigned_agent"] == "agent_1"
    assert updated_queue["tasks"][1]["assigned_agent"] == "some_agent"

def test_main_no_tasks_updated(monkeypatch, tmp_path, capsys):
    # 一致するタスクがなく、更新が行われない場合
    monkeypatch.setattr(sys, "argv", ["update_assigned_agents.py", '{"task_99": "agent_99"}'])
    
    monkeypatch.chdir(tmp_path)
    queue_dir = tmp_path / "backend" / "agents" / "orchestration"
    queue_dir.mkdir(parents=True, exist_ok=True)
    
    initial_queue = {
        "tasks": [
            {"id": "task_1", "assigned_agent": "old_agent"}
        ]
    }
    queue_file = queue_dir / "task_queue.json"
    with open(queue_file, "w", encoding="utf-8") as f:
        json.dump(initial_queue, f)
        
    main()
    
    captured = capsys.readouterr()
    assert "No tasks updated" in captured.out
    
    # ファイルが変更されていないことを確認
    with open(queue_file, "r", encoding="utf-8") as f:
        updated_queue = json.load(f)
    assert updated_queue == initial_queue

def test_main_invalid_json(monkeypatch, tmp_path, capsys):
    # JSONパースエラー
    monkeypatch.setattr(sys, "argv", ["update_assigned_agents.py", 'invalid-json'])
    monkeypatch.chdir(tmp_path)
    
    with pytest.raises(SystemExit) as exc_info:
        main()
        
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error: Invalid JSON mapping format" in captured.out

def test_run_as_script(monkeypatch, tmp_path, capsys):
    # __name__ == "__main__" のルートを確認するためのテスト
    import os
    script_path = os.path.abspath("backend/agents/orchestration/update_assigned_agents.py")
    monkeypatch.setattr(sys, "argv", ["update_assigned_agents.py"])
    monkeypatch.chdir(tmp_path)
    
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(script_path, run_name="__main__")
        
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Usage:" in captured.out


def test_parse_arguments_success():
    args = ["update_assigned_agents.py", '{"task_1": "agent_1"}']
    result = parse_arguments(args)
    assert result == {"task_1": "agent_1"}

def test_parse_arguments_missing(capsys):
    args = ["update_assigned_agents.py"]
    with pytest.raises(SystemExit) as exc_info:
        parse_arguments(args)
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Usage:" in captured.out

def test_load_task_queue_success(tmp_path):
    path = tmp_path / "queue.json"
    data = {"tasks": []}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    result = load_task_queue(path)
    assert result == data

def test_load_task_queue_not_found(tmp_path, capsys):
    path = tmp_path / "nonexistent.json"
    with pytest.raises(SystemExit) as exc_info:
        load_task_queue(path)
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Queue path not found" in captured.out

def test_update_tasks():
    task_queue = {
        "tasks": [
            {"id": "t1", "assigned_agent": "a1"},
            {"id": "t2", "assigned_agent": "a2"}
        ]
    }
    task_to_agent_map = {"t1": "new_a1", "t3": "new_a3"}
    updated_queue, is_updated = update_tasks(task_queue, task_to_agent_map)
    assert is_updated is True
    assert updated_queue["tasks"][0]["assigned_agent"] == "new_a1"
    assert updated_queue["tasks"][1]["assigned_agent"] == "a2"

def test_save_task_queue(tmp_path):
    path = tmp_path / "queue.json"
    data = {"test": "data"}
    save_task_queue(path, data)
    with open(path, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded == data

def test_parse_arguments_not_dict():
    # 辞書以外のJSONオブジェクト
    args = ["update_assigned_agents.py", '["not", "a", "dict"]']
    with pytest.raises(SystemExit) as exc_info:
        parse_arguments(args)
    assert exc_info.value.code == 1

def test_parse_arguments_non_string_values():
    # キーや値が文字列ではない
    args = ["update_assigned_agents.py", '{"task_1": 123}']
    with pytest.raises(SystemExit) as exc_info:
        parse_arguments(args)
    assert exc_info.value.code == 1

def test_load_task_queue_corrupted(tmp_path, capsys):
    # ファイル破損
    path = tmp_path / "corrupted.json"
    with open(path, "w", encoding="utf-8") as f:
        f.write("{invalid json")
        
    with pytest.raises(SystemExit) as exc_info:
        load_task_queue(path)
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error: Task queue file is corrupted" in captured.out

def test_load_task_queue_not_dict(tmp_path, capsys):
    # 辞書ではない
    path = tmp_path / "list.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump([1, 2, 3], f)
        
    with pytest.raises(SystemExit) as exc_info:
        load_task_queue(path)
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error: Task queue content must be a JSON dictionary object." in captured.out

def test_load_task_queue_missing_tasks_key(tmp_path, capsys):
    # tasksキーが欠損
    path = tmp_path / "no_tasks.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"not_tasks": []}, f)
        
    with pytest.raises(SystemExit) as exc_info:
        load_task_queue(path)
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error: Task queue is missing required 'tasks' key." in captured.out

def test_load_task_queue_tasks_not_list(tmp_path, capsys):
    # tasksがリストではない
    path = tmp_path / "tasks_not_list.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"tasks": "not a list"}, f)
        
    with pytest.raises(SystemExit) as exc_info:
        load_task_queue(path)
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error: 'tasks' in task queue must be a list." in captured.out

def test_update_tasks_tasks_not_list():
    # update_tasksにリスト以外のtasksキーを持つ辞書を渡した場合
    task_queue = {"tasks": "not a list"}
    with pytest.raises(SystemExit) as exc_info:
        update_tasks(task_queue, {})
    assert exc_info.value.code == 1

def test_update_tasks_item_not_dict(capsys):
    # tasksの要素が辞書ではない場合
    task_queue = {
        "tasks": [
            "not a dict",
            {"id": "t1", "assigned_agent": "a1"}
        ]
    }
    updated_queue, is_updated = update_tasks(task_queue, {"t1": "new_a1"})
    assert is_updated is True
    assert updated_queue["tasks"][1]["assigned_agent"] == "new_a1"
    captured = capsys.readouterr()
    assert "Warning: Task at index 0 is not a dictionary. Skipping." in captured.out

def test_save_task_queue_os_error(tmp_path, capsys):
    # 保存時のOSError（例: ディレクトリパスを指定して書き込み）
    invalid_path = tmp_path / "dir_path"
    invalid_path.mkdir()
    
    with pytest.raises(SystemExit) as exc_info:
        save_task_queue(invalid_path, {"test": "data"})
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error: Failed to save task queue file." in captured.out
