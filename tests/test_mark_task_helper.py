import sys
import json
import pytest
import runpy
from unittest.mock import MagicMock, patch
from backend.agents.orchestration import mark_task_helper

def test_main_insufficient_arguments(capsys):
    # 引数が足りない場合 (len(sys.argv) < 4)
    # sys.exit(1) が発生することを確認
    test_args = ["mark_task_helper.py", "task-123", "done"]  # 3つ
    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit) as excinfo:
            mark_task_helper.main()
        assert excinfo.value.code == 1
    
    captured = capsys.readouterr()
    assert "Usage: python mark_task_helper.py <task_id> <status> <result_json>" in captured.err

def test_main_success_with_json_result(capsys):
    # 引数が十分にあり、かつ json パースに成功する場合
    test_args = ["mark_task_helper.py", "task-123", "success", '{"key": "value"}']
    
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "mock_status_string"}
    
    with patch.object(sys, "argv", test_args):
        with patch("backend.agents.orchestration.mark_task_helper.OrchestrationHub", return_value=mock_hub_instance):
            mark_task_helper.main()
            
    # モックされた呼び出しの検証
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("ce05d36d-f2c8-452b-8ea9-9053a1e718a0")
    mock_hub_instance.mark_task_done.assert_called_once_with("task-123", "success", {"key": "value"})
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    mock_hub_instance.generate_flash_status.assert_called_once()
    
    captured = capsys.readouterr()
    assert "TASK_MARKED_DONE:task-123:success" in captured.out
    assert "mock_status_string" in captured.out

def test_main_fallback_value_error(capsys):
    # 引数が十分にあり、かつ json パースに失敗する（ValueError）場合
    test_args = ["mark_task_helper.py", "task-123", "failed", "plain_text_error"]
    
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "mock_status_string"}
    
    with patch.object(sys, "argv", test_args):
        with patch("backend.agents.orchestration.mark_task_helper.OrchestrationHub", return_value=mock_hub_instance):
            mark_task_helper.main()
            
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("ce05d36d-f2c8-452b-8ea9-9053a1e718a0")
    # result が {"message": "plain_text_error"} になっていることを検証
    mock_hub_instance.mark_task_done.assert_called_once_with("task-123", "failed", {"message": "plain_text_error"})
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    mock_hub_instance.generate_flash_status.assert_called_once()
    
    captured = capsys.readouterr()
    assert "TASK_MARKED_DONE:task-123:failed" in captured.out
    assert "mock_status_string" in captured.out

def test_main_fallback_type_error(capsys):
    # TypeError が json.loads で発生する場合を検証するために、json.loads をモックする
    test_args = ["mark_task_helper.py", "task-123", "failed", "some_raw"]
    
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "mock_status_string"}
    
    with patch.object(sys, "argv", test_args):
        with patch("backend.agents.orchestration.mark_task_helper.OrchestrationHub", return_value=mock_hub_instance):
            with patch("json.loads", side_effect=TypeError("mocked type error")):
                mark_task_helper.main()
                
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("ce05d36d-f2c8-452b-8ea9-9053a1e718a0")
    mock_hub_instance.mark_task_done.assert_called_once_with("task-123", "failed", {"message": "some_raw"})
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    mock_hub_instance.generate_flash_status.assert_called_once()
    
    captured = capsys.readouterr()
    assert "TASK_MARKED_DONE:task-123:failed" in captured.out
    assert "mock_status_string" in captured.out

def test_main_as_script(capsys):
    # スクリプトとして直接実行された場合 (__name__ == "__main__")
    # 引数が不足しているケースで sys.exit(1) になることを検証する
    test_args = ["mark_task_helper.py"]
    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit) as excinfo:
            # RuntimeWarning 回避のために一時的にモジュールを除去
            with patch.dict(sys.modules):
                sys.modules.pop("backend.agents.orchestration.mark_task_helper", None)
                runpy.run_module("backend.agents.orchestration.mark_task_helper", run_name="__main__")
        assert excinfo.value.code == 1
    
    captured = capsys.readouterr()
    assert "Usage: python mark_task_helper.py <task_id> <status> <result_json>" in captured.err


def test_parse_arguments_insufficient():
    with pytest.raises(SystemExit) as excinfo:
        mark_task_helper._parse_arguments(["mark_task_helper.py", "task-123", "done"])
    assert excinfo.value.code == 1

def test_parse_arguments_default_conv_id():
    task_id, status, result_raw, conv_id = mark_task_helper._parse_arguments(
        ["mark_task_helper.py", "task-123", "done", '{"key": "value"}']
    )
    assert task_id == "task-123"
    assert status == "done"
    assert result_raw == '{"key": "value"}'
    assert conv_id == "ce05d36d-f2c8-452b-8ea9-9053a1e718a0"

def test_parse_arguments_explicit_conv_id():
    task_id, status, result_raw, conv_id = mark_task_helper._parse_arguments(
        ["mark_task_helper.py", "task-123", "done", '{"key": "value"}', "custom-conv-id"]
    )
    assert task_id == "task-123"
    assert status == "done"
    assert result_raw == '{"key": "value"}'
    assert conv_id == "custom-conv-id"

def test_parse_result_payload_valid_json():
    res = mark_task_helper._parse_result_payload('{"foo": "bar"}')
    assert res == {"foo": "bar"}

def test_parse_result_payload_value_error():
    res = mark_task_helper._parse_result_payload("not-a-json")
    assert res == {"message": "not-a-json"}

def test_parse_result_payload_type_error():
    with patch("json.loads", side_effect=TypeError("mocked type error")):
        res = mark_task_helper._parse_result_payload(123)
    assert res == {"message": 123}

def test_mark_task_and_update_status(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "mock_status_string"}
    
    with patch("backend.agents.orchestration.mark_task_helper.OrchestrationHub", return_value=mock_hub_instance):
        mark_task_helper._mark_task_and_update_status(
            "task-123", "success", {"key": "value"}, "custom-conv-id"
        )
        
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("custom-conv-id")
    mock_hub_instance.mark_task_done.assert_called_once_with("task-123", "success", {"key": "value"})
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    mock_hub_instance.generate_flash_status.assert_called_once()
    
    captured = capsys.readouterr()
    assert "TASK_MARKED_DONE:task-123:success" in captured.out
    assert "mock_status_string" in captured.out

def test_main_success_with_explicit_conversation_id(capsys):
    test_args = ["mark_task_helper.py", "task-123", "success", '{"key": "value"}', "my-explicit-conv-id"]
    
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "mock_status_string"}
    
    with patch.object(sys, "argv", test_args):
        with patch("backend.agents.orchestration.mark_task_helper.OrchestrationHub", return_value=mock_hub_instance):
            mark_task_helper.main()
            
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("my-explicit-conv-id")
    mock_hub_instance.mark_task_done.assert_called_once_with("task-123", "success", {"key": "value"})
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    mock_hub_instance.generate_flash_status.assert_called_once()
    
    captured = capsys.readouterr()
    assert "TASK_MARKED_DONE:task-123:success" in captured.out
    assert "mock_status_string" in captured.out

def test_main_exception_handling(capsys):
    # main実行中に予期せぬ例外が発生した場合のハンドリング
    test_args = ["mark_task_helper.py", "task-123", "success", '{"key": "value"}']
    
    # OrchestrationHub で例外を発生させる
    mock_hub_instance = MagicMock()
    mock_hub_instance.mark_task_done.side_effect = RuntimeError("Mocked execution failure")
    mock_store_instance = MagicMock()
    
    with patch.object(sys, "argv", test_args):
        with patch("backend.agents.orchestration.mark_task_helper.OrchestrationHub", return_value=mock_hub_instance), \
             patch("backend.agents.memory.technical_debt.TechnicalDebtStore", return_value=mock_store_instance):
            with pytest.raises(SystemExit) as excinfo:
                mark_task_helper.main()
            assert excinfo.value.code == 1
            
    captured = capsys.readouterr()
    assert "Error: Mocked execution failure" in captured.err
    # 技術負債が正しく登録されたことを確認
    mock_store_instance.register_debt.assert_called_once()
    called_kwargs = mock_store_instance.register_debt.call_args.kwargs
    assert called_kwargs["category"] == "MINOR_INFRA"
    assert called_kwargs["file_path"] == "backend/agents/orchestration/mark_task_helper.py"
    assert called_kwargs["pattern"] == "except Exception as e:"
