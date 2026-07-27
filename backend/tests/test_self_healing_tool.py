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
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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


# ============================================================
# 新規追加のテスト（境界値・極端な値・異常系・コードパス）
# ============================================================

def test_self_healing_empty_and_none_args():
    """正常系: 引数が None や空文字列、空辞書の場合に正常終了することを確認"""
    healer = SelfHealingTool(max_retries=3)
    
    @healer.wrap
    def dummy_tool(a, b, c):
        return f"a:{a}, b:{b}, c:{c}"
        
    res = dummy_tool(None, "", {})
    assert res == "a:None, b:, c:{}"
    assert len(healer.scratchpad) == 0

def test_self_healing_max_retries_zero():
    """境界値: max_retries が 0 の場合、即座に Circuit Breaker が発動することを確認"""
    healer = SelfHealingTool(max_retries=0)
    
    @healer.wrap
    def dummy_tool():
        raise ValueError("Should not run")
        
    res = dummy_tool()
    data = json.loads(res)
    assert data["status"] == "error"
    assert "Circuit Breaker" in data["error"]
    assert data["attempts"] == 0

def test_self_healing_tool_execution_error_json():
    """異常系: ツールがエラーJSON（status=error）を返す場合に ToolExecutionError が発生しリトライすること"""
    healer = SelfHealingTool(max_retries=3)
    
    call_count = 0
    @healer.wrap
    def dummy_tool():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return json.dumps({"status": "error", "error": "Temporary database issue"})
        return json.dumps({"status": "success", "data": "OK"})
        
    res = dummy_tool()
    data = json.loads(res)
    assert data["status"] == "success"
    assert call_count == 2
    assert len(healer.scratchpad) == 2
    assert healer.scratchpad[0].repair_result == "pending"
    assert healer.scratchpad[0].error_type == "ToolExecutionError"
    assert healer.scratchpad[1].repair_result == "success"

def test_self_healing_sig_bind_type_error_path():
    """境界値/コードパス: 引数不整合により sig.bind が TypeError を投げるケースの検証"""
    healer = SelfHealingTool(max_retries=3)
    
    @healer.wrap
    def dummy_tool(a, b):
        return f"a:{a}, b:{b}"

    res = dummy_tool(1)
    data = json.loads(res)
    assert data["status"] == "error"
    assert "セルフヒーリング失敗" in data["error"]

def test_snapshot_args_exception_safety():
    """境界値: _snapshot_args に例外を投げるオブジェクトが渡された場合の安全動作"""
    healer = SelfHealingTool()
    
    class EvilObject:
        def __str__(self):
            raise RuntimeError("Evil str method")
            
    res = healer._snapshot_args((EvilObject(),), {})
    assert res == {}

def test_determine_repair_strategy_fallback_on_unhandled_error():
    """異常系: ハンドリング対象外の例外タイプの場合にデフォルト of retry が選択されること"""
    healer = SelfHealingTool(max_retries=3)
    
    class CustomException(Exception):
        pass
        
    strategy = healer._determine_repair_strategy(
        tool_name="dummy",
        error=CustomException("something happened"),
        args=(),
        kwargs={},
        attempt=1
    )
    assert strategy.strategy_type == "retry"
    assert "戦略なしリトライ" in strategy.description


def test_self_healing_modify_args_exception_path():
    """境界値/コードパス: 引数修正中に例外が発生した場合、kwargs.update がフォールバックとして呼ばれること"""
    from collections import OrderedDict
    from unittest.mock import patch
    from backend.agents.self_healing_tool import RepairStrategy

    healer = SelfHealingTool(max_retries=2)
    
    @healer.wrap
    def dummy_tool(x):
        if x == "modified":
            return "success"
        raise ValueError("initial fail")

    class EvilOrderedDict(OrderedDict):
        def __init__(self, *args, **kwargs):
            self._initialized = False
            super().__init__(*args, **kwargs)
            self._initialized = True
        def __setitem__(self, key, value):
            if getattr(self, "_initialized", False):
                raise TypeError("Cannot set value")
            super().__setitem__(key, value)

    class MockBoundArguments:
        def __init__(self):
            self.arguments = EvilOrderedDict([("x", 1)])
        def apply_defaults(self):
            pass
        @property
        def args(self):
            return ()
        @property
        def kwargs(self):
            return {}

    def mock_determine(tool_name, error, args, kwargs, attempt):
        return RepairStrategy(
            strategy_type="modify_args",
            description="Force modify",
            modified_args={"x": "modified"}
        )

    mock_bound = MockBoundArguments()

    with patch("inspect.Signature.bind", return_value=mock_bound),          patch.object(healer, "_determine_repair_strategy", side_effect=mock_determine):
        
        res = dummy_tool(x=1)
        assert res == "success"


def test_self_healing_safety_valve_exception_safety():
    healer = SelfHealingTool(max_retries=1, enable_git_rollback=True)
    
    @healer.wrap
    def dummy_tool(x):
        raise ValueError("Triggering error")
        
    with patch.object(healer, '_trigger_safety_valve', side_effect=RuntimeError("Safety valve crash")):
        res = dummy_tool(10)
        data = json.loads(res)
        assert data["status"] == "error"
        assert "セルフヒーリング失敗" in data["error"]
        assert "Safety valve crash" in data["rollback_error"]

def test_self_healing_safety_valve_exception_safety_circuit_breaker():
    healer = SelfHealingTool(max_retries=3, enable_git_rollback=True)
    
    # 同一エラーが2回失敗したレッスンを事前に登録して escalate させる
    healer._record_scratchpad(
        "dummy_tool", ValueError("Triggering error"), "retry", "failed", {}
    )
    healer._record_scratchpad(
        "dummy_tool", ValueError("Triggering error"), "retry", "failed", {}
    )
    
    @healer.wrap
    def dummy_tool(x):
        raise ValueError("Triggering error")
        
    with patch.object(healer, '_trigger_safety_valve', side_effect=RuntimeError("Safety valve crash CB")):
        res = dummy_tool(10)
        data = json.loads(res)
        assert data["status"] == "error"
        assert "Circuit Breaker" in data["error"]
        assert "Safety valve crash CB" in data["rollback_error"]


def test_self_healing_tool_subprocess_error():
    import subprocess
    healer = SelfHealingTool(max_retries=2)
    
    call_count = 0
    @healer.wrap
    def dummy_tool(x):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise subprocess.SubprocessError("Subprocess failed")
        return "success"
        
    res = dummy_tool(10)
    assert res == "success"
    assert call_count == 2
    assert len(healer.scratchpad) == 2
    assert healer.scratchpad[0].error_type == "SubprocessError"


def test_self_healing_safety_valve_subprocess_error():
    import subprocess
    healer = SelfHealingTool(max_retries=1, enable_git_rollback=True)
    
    @healer.wrap
    def dummy_tool(x):
        raise ValueError("Triggering error")
        
    with patch.object(healer, '_trigger_safety_valve', side_effect=subprocess.SubprocessError("Subprocess crash")):
        res = dummy_tool(10)
        data = json.loads(res)
        assert data["status"] == "error"
        assert "セルフヒーリング失敗" in data["error"]
        assert "Subprocess crash" in data["rollback_error"]



def test_self_healing_assertion_error():
    """AssertionErrorが発生した場合でも自己修復が働き、フォールバック値（セルフヒーリング失敗）を返すことを確認"""
    healer = SelfHealingTool(max_retries=3, enable_git_rollback=True)
    
    call_count = 0
    @healer.wrap
    def dummy_tool(x):
        nonlocal call_count
        call_count += 1
        assert False, f"Assertion failed {call_count}"
        
    with patch.object(healer, '_execute_git_rollback', return_value=(True, None)),          patch.object(healer, '_save_alternative_instructions'):
         
        res = dummy_tool(10)
        data = json.loads(res)
        assert data["status"] == "error"
        assert "セルフヒーリング失敗" in data["error"]
        assert call_count == 3


def test_self_healing_safety_valve_key_error_safety():
    """安全弁処理中に KeyError が発生した場合でもキャッチされ、Circuit Breakerが安全にフォールバックすることを確認"""
    healer = SelfHealingTool(max_retries=1, enable_git_rollback=True)
    
    @healer.wrap
    def dummy_tool(x):
        raise ValueError("Triggering error")
        
    with patch.object(healer, '_trigger_safety_valve', side_effect=KeyError("Missing safety configuration")):
        res = dummy_tool(10)
        data = json.loads(res)
        assert data["status"] == "error"
        assert "セルフヒーリング失敗" in data["error"]
        assert "Missing safety configuration" in data["rollback_error"]


def test_self_healing_safety_valve_os_error_safety():
    """安全弁処理中に OSError が発生した場合でもキャッチされ、Circuit Breakerが安全にフォールバックすることを確認"""
    healer = SelfHealingTool(max_retries=1, enable_git_rollback=True)
    
    @healer.wrap
    def dummy_tool(x):
        raise ValueError("Triggering error")
        
    with patch.object(healer, '_trigger_safety_valve', side_effect=OSError("Disk Full")):
        res = dummy_tool(10)
        data = json.loads(res)
        assert data["status"] == "error"
        assert "セルフヒーリング失敗" in data["error"]
        assert "Disk Full" in data["rollback_error"]


def test_self_healing_unhandled_runtime_error_healing():
    """明示的に列挙されていない ZeroDivisionError でも自己修復ループが働き、最終的にフォールバックされること"""
    healer = SelfHealingTool(max_retries=2, enable_git_rollback=True)
    
    call_count = 0
    @healer.wrap
    def dummy_tool(x):
        nonlocal call_count
        call_count += 1
        return 1 / 0
        
    with patch.object(healer, '_execute_git_rollback', return_value=(True, None)), \
         patch.object(healer, '_save_alternative_instructions'):
         
        res = dummy_tool(10)
        data = json.loads(res)
        assert data["status"] == "error"
        assert "セルフヒーリング失敗" in data["error"]
        assert call_count == 2
