import os
import json
import pytest
from unittest.mock import patch, MagicMock
from backend.agents.self_healing_tool import SelfHealingTool, ScratchpadEntry

def test_self_healing_success():
    healer = SelfHealingTool(max_retries=3, enable_git_rollback=True)
    
    call_count = 0
    @healer.wrap
    def dummy_tool(x):
        nonlocal call_count
        call_count += 1
        return f"success {x}"
        
    res = dummy_tool(10)
    assert res == "success 10"
    assert call_count == 1
    assert len(healer.scratchpad) == 0

def test_self_healing_retry_success():
    healer = SelfHealingTool(max_retries=3, enable_git_rollback=True)
    
    call_count = 0
    @healer.wrap
    def dummy_tool(x):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ValueError("First call failed")
        return f"success {x}"
        
    res = dummy_tool(10)
    assert res == "success 10"
    assert call_count == 2
    # 失敗した1回目が pending で記録され、成功時に success に更新される
    assert len(healer.scratchpad) == 2
    assert healer.scratchpad[0].repair_result == "pending"
    assert healer.scratchpad[1].repair_result == "success"

def test_self_healing_circuit_breaker_fallback():
    healer = SelfHealingTool(max_retries=3, enable_git_rollback=True)
    
    call_count = 0
    @healer.wrap
    def dummy_tool(x):
        nonlocal call_count
        call_count += 1
        raise ValueError(f"Failed attempt {call_count}")
        
    with patch.object(healer, '_execute_git_rollback', return_value=(True, None)) as mock_rollback, \
         patch.object(healer, '_save_alternative_instructions') as mock_save:
         
        res = dummy_tool(10)
        
        # 結果はエラーJSONになるはず（3回失敗したためfallback_valueでリターンされる）
        data = json.loads(res)
        assert data["status"] == "error"
        assert "セルフヒーリング失敗" in data["error"]
        assert data["rollback_executed"] is True
        
        # モックの呼び出し確認
        mock_rollback.assert_called_once()
        mock_save.assert_called_once()
        
        # 引数が渡されていること
        args, kwargs = mock_save.call_args
        assert args[0] == "dummy_tool"
        assert "ValueError: Failed attempt 3" in args[1]
        assert "別アプローチ指示書" in args[1]

def test_self_healing_escalate_circuit_breaker():
    healer = SelfHealingTool(max_retries=3, enable_git_rollback=True)
    
    # 既に同じエラーが2回失敗しているレッスンを事前に登録しておくことで、
    # 1回目の失敗で escalate が選ばれるようにする
    healer._record_scratchpad(
        "dummy_tool", ValueError("Repeated error"), "retry", "failed", {}
    )
    healer._record_scratchpad(
        "dummy_tool", ValueError("Repeated error"), "retry", "failed", {}
    )
    
    @healer.wrap
    def dummy_tool(x):
        raise ValueError("Repeated error")
        
    with patch.object(healer, '_execute_git_rollback', return_value=(True, None)) as mock_rollback, \
         patch.object(healer, '_save_alternative_instructions') as mock_save:
         
        res = dummy_tool(10)
        
        # 結果はエラーJSONになるはず（escalateのためループを抜けてCircuit Breakerに到達する）
        data = json.loads(res)
        assert data["status"] == "error"
        assert "Circuit Breaker" in data["error"]
        assert data["rollback_executed"] is True
        
        # モックの呼び出し確認
        mock_rollback.assert_called_once()
        mock_save.assert_called_once()
        
        # 引数が渡されていること
        args, kwargs = mock_save.call_args
        assert args[0] == "dummy_tool"
        assert "ValueError: Repeated error" in args[1]
        assert "別アプローチ指示書" in args[1]

def test_alternative_instructions_generation():
    healer = SelfHealingTool(max_retries=3, enable_git_rollback=True)
    
    # FileNotFoundError の場合
    err = FileNotFoundError("file xyz not found")
    lessons = [
        ScratchpadEntry(
            tool_name="test_tool",
            error_type="FileNotFoundError",
            error_message="file xyz not found",
            repair_strategy="retry",
            repair_result="failed",
            timestamp="2026-06-05T12:00:00",
            args_snapshot={}
        )
    ]
    inst = healer._generate_alternative_instructions("test_tool", err, lessons)
    assert "ファイル未検出時の代替アプローチ" in inst
    assert "test_tool" in inst
    
    # TimeoutError の場合
    err_timeout = TimeoutError("request timed out")
    inst_timeout = healer._generate_alternative_instructions("test_tool", err_timeout, lessons)
    assert "タイムアウト時の代替アプローチ" in inst_timeout

def test_save_alternative_instructions_real():
    healer = SelfHealingTool(max_retries=3, enable_git_rollback=True)
    
    tool_name = "test_tool_real_save"
    inst = "This is a test instruction"
    
    # プロジェクトのベースディレクトリを正しく取得
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    expected_path = os.path.join(base_dir, "scratch", f"alternative_approach_{tool_name}.txt")
    if os.path.exists(expected_path):
        os.remove(expected_path)
        
    healer._save_alternative_instructions(tool_name, inst)
    
    assert os.path.exists(expected_path)
    with open(expected_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert content == inst
    
    # 後処理
    os.remove(expected_path)


def test_self_healing_safety_valve_unexpected_exception():
    healer = SelfHealingTool(max_retries=3, enable_git_rollback=True)
    
    call_count = 0
    @healer.wrap
    def dummy_tool(x):
        nonlocal call_count
        call_count += 1
        raise ValueError("Trigger safety valve")
        
    # _trigger_safety_valve 内で TypeError が発生するようにモックする
    with patch.object(healer, '_trigger_safety_valve', side_effect=TypeError("Safety valve mock error")) as mock_valve:
        res = dummy_tool(10)
        
        data = json.loads(res)
        assert data["status"] == "error"
        assert "Safety valve failed" in data["rollback_error"] or "Safety valve mock error" in data["rollback_error"]
        assert data["rollback_executed"] is False
        assert "予期しない例外が発生しました" in data["alternative_approach_instructions"]
        mock_valve.assert_called_once()
