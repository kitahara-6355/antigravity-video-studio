import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from backend.agents.orchestration.orchestrator import OrchestrationHub

def test_ensure_files_exist_when_not_exist(tmp_path, monkeypatch):
    task_queue = tmp_path / "task_queue.json"
    opus_directive = tmp_path / "opus_directive.json"
    flash_reports = tmp_path / "flash_reports.jsonl"
    message_box = tmp_path / "message_box.jsonl"
    flash_session = tmp_path / "flash_session.json"
    phase_gates = tmp_path / "phase_gates.json"

    # orchestrator モジュールのパス変数を monkeypatch で一時フォルダに変更
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.TASK_QUEUE_PATH", task_queue)
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.OPUS_DIRECTIVE_PATH", opus_directive)
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.FLASH_REPORTS_PATH", flash_reports)
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.MESSAGE_BOX_PATH", message_box)
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.FLASH_SESSION_PATH", flash_session)
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.PHASE_GATES_PATH", phase_gates)

    assert not task_queue.exists()
    assert not opus_directive.exists()
    assert not flash_reports.exists()
    assert not message_box.exists()
    assert not flash_session.exists()
    assert not phase_gates.exists()

    hub = OrchestrationHub()

    assert task_queue.exists()
    assert opus_directive.exists()
    assert flash_reports.exists()
    assert message_box.exists()
    assert flash_session.exists()
    assert phase_gates.exists()

@pytest.mark.parametrize("invalid_path", [
    "/abs/path",
    "\\abs\\path",
    "some/../path",
])
def test_verify_file_invalid_path(invalid_path, tmp_path, monkeypatch):
    # パスが自動生成されるので、一時フォルダで回避
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.TASK_QUEUE_PATH", tmp_path / "t.json")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.OPUS_DIRECTIVE_PATH", tmp_path / "o.json")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.FLASH_REPORTS_PATH", tmp_path / "f.jsonl")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.MESSAGE_BOX_PATH", tmp_path / "m.jsonl")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.FLASH_SESSION_PATH", tmp_path / "s.json")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.PHASE_GATES_PATH", tmp_path / "g.json")
    pass

def test_verify_file_invalid_paths_actual(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.TASK_QUEUE_PATH", tmp_path / "t.json")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.OPUS_DIRECTIVE_PATH", tmp_path / "o.json")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.FLASH_REPORTS_PATH", tmp_path / "f.jsonl")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.MESSAGE_BOX_PATH", tmp_path / "m.jsonl")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.FLASH_SESSION_PATH", tmp_path / "s.json")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.PHASE_GATES_PATH", tmp_path / "g.json")

    hub = OrchestrationHub()

    # Windows で絶対パスと判定されるもの
    abs_path_win = "C:\\absolute\\path"
    res = hub.verify_file(abs_path_win)
    assert res["passed"] is False
    assert "Invalid file path" in res["error"]

    # `/` で始まるパス
    res = hub.verify_file("/leading/slash")
    assert res["passed"] is False
    assert "Invalid file path" in res["error"]

    # `\` で始まるパス
    res = hub.verify_file("\\leading\\backslash")
    assert res["passed"] is False
    assert "Invalid file path" in res["error"]

    # `..` を含むパス
    res = hub.verify_file("normal/../path")
    assert res["passed"] is False
    assert "Invalid file path" in res["error"]

def test_verify_file_exceeds_size_limit(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.TASK_QUEUE_PATH", tmp_path / "t.json")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.OPUS_DIRECTIVE_PATH", tmp_path / "o.json")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.FLASH_REPORTS_PATH", tmp_path / "f.jsonl")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.MESSAGE_BOX_PATH", tmp_path / "m.jsonl")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.FLASH_SESSION_PATH", tmp_path / "s.json")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.PHASE_GATES_PATH", tmp_path / "g.json")

    # _PROJECT_ROOT を tmp_path に変更
    monkeypatch.setattr("backend.agents.orchestration.orchestrator._PROJECT_ROOT", tmp_path)

    hub = OrchestrationHub()

    # 1MB 超えのファイルを作成
    huge_file_name = "huge_file.py"
    huge_file_path = tmp_path / huge_file_name
    huge_file_path.write_bytes(b"x" * (1024 * 1024 + 1))

    res = hub.verify_file(huge_file_name)
    assert res["passed"] is False
    assert "exceeds 1MB limit" in res["error"]

@patch("backend.agents.orchestration.orchestrator.CodeVerifier")
def test_verify_file_success(mock_verifier_class, tmp_path, monkeypatch):
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.TASK_QUEUE_PATH", tmp_path / "t.json")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.OPUS_DIRECTIVE_PATH", tmp_path / "o.json")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.FLASH_REPORTS_PATH", tmp_path / "f.jsonl")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.MESSAGE_BOX_PATH", tmp_path / "m.jsonl")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.FLASH_SESSION_PATH", tmp_path / "s.json")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.PHASE_GATES_PATH", tmp_path / "g.json")

    # _PROJECT_ROOT を tmp_path に変更
    monkeypatch.setattr("backend.agents.orchestration.orchestrator._PROJECT_ROOT", tmp_path)

    mock_verifier = MagicMock()
    mock_verifier.verify_static.return_value = {"passed": True, "details": "all good"}
    mock_verifier_class.return_value = mock_verifier

    # 正常なサイズのファイルを作成
    normal_file_name = "normal_file.py"
    normal_file_path = tmp_path / normal_file_name
    normal_file_path.write_text("print('hello')", encoding="utf-8")

    hub = OrchestrationHub()
    res = hub.verify_file(normal_file_name)

    assert res == {"passed": True, "details": "all good"}
    mock_verifier.verify_static.assert_called_once_with(normal_file_name)

@patch("backend.agents.orchestration.orchestrator.CodeVerifier")
def test_verify_test_suite_success(mock_verifier_class, tmp_path, monkeypatch):
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.TASK_QUEUE_PATH", tmp_path / "t.json")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.OPUS_DIRECTIVE_PATH", tmp_path / "o.json")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.FLASH_REPORTS_PATH", tmp_path / "f.jsonl")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.MESSAGE_BOX_PATH", tmp_path / "m.jsonl")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.FLASH_SESSION_PATH", tmp_path / "s.json")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.PHASE_GATES_PATH", tmp_path / "g.json")

    mock_verifier = MagicMock()
    mock_verifier.verify_dynamic.return_value = {"passed": True, "coverage": 85}
    mock_verifier_class.return_value = mock_verifier

    hub = OrchestrationHub()
    res = hub.verify_test_suite("test_pattern")

    assert res == {"passed": True, "coverage": 85}
    mock_verifier.verify_dynamic.assert_called_once_with("test_pattern")

@patch("backend.agents.orchestration.orchestrator.CodeVerifier")
def test_verify_test_suite_exception(mock_verifier_class, tmp_path, monkeypatch):
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.TASK_QUEUE_PATH", tmp_path / "t.json")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.OPUS_DIRECTIVE_PATH", tmp_path / "o.json")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.FLASH_REPORTS_PATH", tmp_path / "f.jsonl")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.MESSAGE_BOX_PATH", tmp_path / "m.jsonl")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.FLASH_SESSION_PATH", tmp_path / "s.json")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.PHASE_GATES_PATH", tmp_path / "g.json")

    mock_verifier = MagicMock()
    mock_verifier.verify_dynamic.side_effect = Exception("pytest crash")
    mock_verifier_class.return_value = mock_verifier

    hub = OrchestrationHub()
    res = hub.verify_test_suite("test_pattern")

    assert res == {"passed": False, "error": "Test execution failed: pytest crash"}
    mock_verifier.verify_dynamic.assert_called_once_with("test_pattern")

@patch("backend.agents.orchestration.orchestrator.TaskGenerator")
@patch("backend.agents.orchestration.orchestrator.DynamicDecomposer")
def test_generate_tasks_for_batch(mock_decomposer_class, mock_generator_class, tmp_path, monkeypatch):
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.TASK_QUEUE_PATH", tmp_path / "t.json")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.OPUS_DIRECTIVE_PATH", tmp_path / "o.json")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.FLASH_REPORTS_PATH", tmp_path / "f.jsonl")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.MESSAGE_BOX_PATH", tmp_path / "m.jsonl")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.FLASH_SESSION_PATH", tmp_path / "s.json")
    monkeypatch.setattr("backend.agents.orchestration.orchestrator.PHASE_GATES_PATH", tmp_path / "g.json")

    # generator のモック
    mock_generator = MagicMock()
    mock_generator.create_batch_tasks.return_value = [
        {"design_stock_id": "stock_s"},
        {"design_stock_id": "stock_c"},
        {"design_stock_id": "stock_missing"},
    ]
    mock_generator_class.return_value = mock_generator

    # decomposer のモック (分解せずにそのまま返す)
    mock_decomposer = MagicMock()
    mock_decomposer.decompose_task.side_effect = lambda t: [t]
    mock_decomposer_class.return_value = mock_decomposer

    stock_items = [
        {"id": "stock_s", "difficulty": "S"},
        {"id": "stock_c", "difficulty": "C"},
    ]

    hub = OrchestrationHub()
    decomposed = hub.generate_tasks_for_batch("batch_123", stock_items)

    assert len(decomposed) == 3

    assert decomposed[0]["design_stock_id"] == "stock_s"
    assert decomposed[0]["level"] == "L2"

    assert decomposed[1]["design_stock_id"] == "stock_c"
    assert decomposed[1]["level"] == "L1"

    assert decomposed[2]["design_stock_id"] == "stock_missing"
    assert decomposed[2]["level"] == "L1"

    mock_generator.create_batch_tasks.assert_called_once_with("batch_123", stock_items)
    assert mock_decomposer.decompose_task.call_count == 3
