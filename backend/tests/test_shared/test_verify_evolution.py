import pytest
import os
import sys
import json
from unittest.mock import patch, MagicMock

# backend ディレクトリを sys.path に追加してインポート可能にする
backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, backend_dir)

from agents.analyst import Analyst
from verify_evolution import verify_evolution, run_debate, trigger_learning, verify_persistence

@pytest.fixture(autouse=True)
def mock_dependencies():
    with patch("agents.agent_base.get_gemini_client") as mock_get, \
         patch("agents.analyst.Analyst._run_adk_bridge", side_effect=lambda x: x):
        mock_get.return_value = MagicMock()
        yield

def test_verify_evolution_success(tmp_path, capsys):
    """
    正常系テスト: Analyst の bias_weight が 1.0 より大きい状態で
    verify_evolution() を実行し、SUCCESS が出力されることを確認。
    """
    temp_soul_path = str(tmp_path / "Analyst.json")
    
    with open(temp_soul_path, "w", encoding="utf-8") as f:
        json.dump({
            "stats": {"debates": 0, "wins": 0, "losses": 0},
            "bias_weight": 1.05,
            "history": []
        }, f, indent=2, ensure_ascii=False)
        
    original_init = Analyst.__init__
    
    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.soul_path = temp_soul_path
        self.soul = self._load_soul()
        
    with patch.object(Analyst, "__init__", patched_init):
        res = verify_evolution()
        assert res is True
        
    captured = capsys.readouterr()
    assert "SUCCESS: Soul File persisted correctly" in captured.out
    assert "FAILURE" not in captured.out

def test_verify_evolution_failure_under_limit(tmp_path, capsys):
    """
    異常系テスト: Analyst の bias_weight が 1.0 以下の状態で
    verify_evolution() を実行し、FAILURE が出力されることを確認。
    """
    temp_soul_path = str(tmp_path / "Analyst.json")
    
    with open(temp_soul_path, "w", encoding="utf-8") as f:
        json.dump({
            "stats": {"debates": 0, "wins": 0, "losses": 0},
            "bias_weight": 0.95,
            "history": []
        }, f, indent=2, ensure_ascii=False)
        
    original_init = Analyst.__init__
    
    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.soul_path = temp_soul_path
        self.soul = self._load_soul()
        
    with patch.object(Analyst, "__init__", patched_init):
        res = verify_evolution()
        assert res is False
        
    captured = capsys.readouterr()
    assert "FAILURE: Persistence mismatch" in captured.out
    assert "SUCCESS" not in captured.out

def test_verify_evolution_main_run(tmp_path, capsys):
    """
    __main__ ブロックのテスト: verify_evolution.py を直接 exec() で実行し、
    スクリプトとしての実行とカバレッジを確実にカバーする。
    """
    temp_soul_path = str(tmp_path / "Analyst.json")
    
    with open(temp_soul_path, "w", encoding="utf-8") as f:
        json.dump({
            "stats": {"debates": 0, "wins": 0, "losses": 0},
            "bias_weight": 1.05,
            "history": []
        }, f, indent=2, ensure_ascii=False)
        
    original_init = Analyst.__init__
    
    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.soul_path = temp_soul_path
        self.soul = self._load_soul()
        
    import verify_evolution
    script_path = verify_evolution.__file__
    
    global_vars = {
        "__name__": "__main__",
        "__file__": script_path,
    }
    
    with patch.object(Analyst, "__init__", patched_init):
        with open(script_path, "r", encoding="utf-8") as f:
            code = compile(f.read(), script_path, "exec")
            exec(code, global_vars)
        
    captured = capsys.readouterr()
    assert "SUCCESS: Soul File persisted correctly" in captured.out
    assert "FAILURE" not in captured.out

def test_verify_evolution_with_injected_analyst(capsys):
    """
    依存性注入テスト: モックされた Analyst を直接 verify_evolution に注入し、
    正しく動作することを確認する。
    """
    mock_analyst = MagicMock(spec=Analyst)
    mock_analyst.soul = {"bias_weight": 1.2}
    mock_analyst.process.return_value = {"stance": "CONTRARIAN"}
    
    # verify_persistence をモック化して、リロード時の依存を回避
    with patch("verify_evolution.verify_persistence", return_value=(True, 1.2)):
        res = verify_evolution(analyst=mock_analyst)
        assert res is True
        
    mock_analyst.process.assert_called_once_with({}, {})
    mock_analyst.learn.assert_called_once()
    
    captured = capsys.readouterr()
    assert "Session ID" in captured.out

def test_verify_evolution_exception_handling(capsys):
    """
    例外ハンドリングテスト: 処理中に例外が発生した場合に
    verify_evolution() が False を返し、エラーメッセージを出力することを確認。
    """
    mock_analyst = MagicMock(spec=Analyst)
    mock_analyst.process.side_effect = RuntimeError("Simulated processing error")
    
    res = verify_evolution(analyst=mock_analyst)
    assert res is False
    
    captured = capsys.readouterr()
    assert "Unexpected exception occurred during verification" in captured.out
    assert "Simulated processing error" in captured.err

def test_run_debate_success():
    """run_debate() が正常に動作することを確認。"""
    mock_analyst = MagicMock(spec=Analyst)
    mock_analyst.soul = {"bias_weight": 1.1}
    mock_analyst.process.return_value = {"stance": "AGREE"}
    
    res = run_debate(mock_analyst)
    assert res == {"stance": "AGREE"}
    mock_analyst.process.assert_called_once_with({}, {})

def test_run_debate_exception():
    """run_debate() で例外が発生した際に適切に伝播することを確認。"""
    mock_analyst = MagicMock(spec=Analyst)
    mock_analyst.process.side_effect = ValueError("Process failed")
    
    with pytest.raises(ValueError, match="Process failed"):
        run_debate(mock_analyst)

def test_trigger_learning_success():
    """trigger_learning() が正常に動作し、bias_weight の変化が返ることを確認。"""
    mock_analyst = MagicMock(spec=Analyst)
    mock_analyst.soul = {"bias_weight": 1.0}
    
    def mock_learn(session_id, stance, outcome):
        mock_analyst.soul["bias_weight"] = 1.2
        
    mock_analyst.learn.side_effect = mock_learn
    
    old_w, new_w = trigger_learning(mock_analyst, "session-123", "AGREE", "APPROVE")
    assert old_w == 1.0
    assert new_w == 1.2
    mock_analyst.learn.assert_called_once_with("session-123", "AGREE", "APPROVE")

def test_trigger_learning_exception():
    """trigger_learning() で例外が発生した際に適切に伝播することを確認。"""
    mock_analyst = MagicMock(spec=Analyst)
    mock_analyst.soul = {"bias_weight": 1.0}
    mock_analyst.learn.side_effect = RuntimeError("Learn error")
    
    with pytest.raises(RuntimeError, match="Learn error"):
        trigger_learning(mock_analyst, "session-123", "AGREE", "APPROVE")

def test_verify_persistence_success():
    """verify_persistence() が正常に永続化成功と判定することを確認。"""
    mock_analyst_instance = MagicMock(spec=Analyst)
    mock_analyst_instance.soul = {"bias_weight": 1.5}
    
    with patch("verify_evolution.Analyst", return_value=mock_analyst_instance):
        success, saved_weight = verify_persistence(1.5)
        assert success is True
        assert saved_weight == 1.5

def test_verify_persistence_failure_mismatch():
    """verify_persistence() が値の不一致で永続化失敗と判定することを確認。"""
    mock_analyst_instance = MagicMock(spec=Analyst)
    mock_analyst_instance.soul = {"bias_weight": 1.4}
    
    with patch("verify_evolution.Analyst", return_value=mock_analyst_instance):
        success, saved_weight = verify_persistence(1.5)
        assert success is False
        assert saved_weight == 1.4

def test_verify_persistence_failure_under_limit():
    """verify_persistence() が値が1.0以下であるため永続化失敗と判定することを確認。"""
    mock_analyst_instance = MagicMock(spec=Analyst)
    mock_analyst_instance.soul = {"bias_weight": 0.9}
    
    with patch("verify_evolution.Analyst", return_value=mock_analyst_instance):
        success, saved_weight = verify_persistence(0.9)
        assert success is False
        assert saved_weight == 0.9

def test_verify_persistence_exception():
    """verify_persistence() 内で Analyst() が例外を投げた際に適切に伝播することを確認。"""
    with patch("verify_evolution.Analyst", side_effect=ImportError("Failed to import")):
        with pytest.raises(ImportError, match="Failed to import"):
            verify_persistence(1.5)

def test_verify_evolution_outcome_reject(capsys):
    """verify_evolution() で outcome='REJECT' の際の挙動を検証。"""
    mock_analyst = MagicMock(spec=Analyst)
    mock_analyst.soul = {"bias_weight": 1.2}
    mock_analyst.process.return_value = {"stance": "DISAGREE"}
    
    with patch("verify_evolution.trigger_learning", return_value=(1.2, 1.3)) as mock_trigger,          patch("verify_evolution.verify_persistence", return_value=(True, 1.3)) as mock_persist:
         
        res = verify_evolution(analyst=mock_analyst, outcome="REJECT")
        assert res is True
        
        args, kwargs = mock_trigger.call_args
        assert args[0] == mock_analyst
        assert isinstance(args[1], str)
        assert args[2] == "DISAGREE"
        assert args[3] == "REJECT"

def test_verify_evolution_outcome_neutral():
    """verify_evolution() で outcome='NEUTRAL' の際の挙動を検証。"""
    mock_analyst = MagicMock(spec=Analyst)
    mock_analyst.soul = {"bias_weight": 1.2}
    mock_analyst.process.return_value = {"stance": "NEUTRAL"}
    
    with patch("verify_evolution.trigger_learning", return_value=(1.2, 1.2)) as mock_trigger,          patch("verify_evolution.verify_persistence", return_value=(True, 1.2)) as mock_persist:
         
        res = verify_evolution(analyst=mock_analyst, outcome="NEUTRAL")
        assert res is True

def test_verify_evolution_init_analyst_exception(capsys):
    """verify_evolution() で Analyst の新規初期化自体が失敗した場合の例外ハンドリングを確認。"""
    with patch("verify_evolution.Analyst", side_effect=RuntimeError("Analyst init failed")):
        res = verify_evolution(analyst=None)
        assert res is False
        
    captured = capsys.readouterr()
    assert "Unexpected exception occurred during verification: Analyst init failed" in captured.out

def test_verify_evolution_trigger_learning_exception(capsys):
    """verify_evolution() 内で trigger_learning が例外を投げた場合のフォールバックを検証。"""
    mock_analyst = MagicMock(spec=Analyst)
    mock_analyst.soul = {"bias_weight": 1.2}
    mock_analyst.process.return_value = {"stance": "AGREE"}
    
    with patch("verify_evolution.trigger_learning", side_effect=ValueError("Learning failure")):
        res = verify_evolution(analyst=mock_analyst)
        assert res is False
        
    captured = capsys.readouterr()
    assert "Value validation error: Learning failure" in captured.out

def test_verify_evolution_verify_persistence_exception(capsys):
    """verify_evolution() 内で verify_persistence が例外を投げた場合のフォールバックを検証。"""
    mock_analyst = MagicMock(spec=Analyst)
    mock_analyst.soul = {"bias_weight": 1.2}
    mock_analyst.process.return_value = {"stance": "AGREE"}
    
    with patch("verify_evolution.trigger_learning", return_value=(1.2, 1.3)),          patch("verify_evolution.verify_persistence", side_effect=KeyError("Persistence key error")):
        res = verify_evolution(analyst=mock_analyst)
        assert res is False
        
    captured = capsys.readouterr()
    assert "Data structure error (Missing key: 'Persistence key error') occurred during verification" in captured.out


def test_verify_evolution_missing_bias_weight_exception(capsys):
    """
    異常系テスト: Analyst の soul 辞書に 'bias_weight' キーが存在しない場合、
    KeyError が発生し、それが verify_evolution() の例外ハンドリングでキャッチされ、
    False を返すことを確認する。
    """
    mock_analyst = MagicMock(spec=Analyst)
    mock_analyst.soul = {}
    mock_analyst.process.return_value = {"stance": "AGREE"}
    
    res = verify_evolution(analyst=mock_analyst)
    assert res is False
    
    captured = capsys.readouterr()
    assert "Data structure error (Missing key: 'bias_weight') occurred during verification" in captured.out


def test_verify_evolution_invalid_outcome_handling(capsys):
    """
    境界系テスト: 不正な outcome 文字列が引き渡された場合でも、
    例外が発生せずに適切に処理、または発生した例外がハンドリングされることを検証する。
    """
    mock_analyst = MagicMock(spec=Analyst)
    mock_analyst.soul = {"bias_weight": 1.1}
    mock_analyst.process.return_value = {"stance": "AGREE"}
    
    with patch("verify_evolution.trigger_learning", return_value=(1.1, 1.2)), \
         patch("verify_evolution.verify_persistence", return_value=(True, 1.2)):
        res = verify_evolution(analyst=mock_analyst, outcome="INVALID_OUTCOME")
        assert res is True
        
    captured = capsys.readouterr()
    assert "The Chairman Decision -> INVALID_OUTCOME" in captured.out

def test_verify_evolution_missing_stance_in_debate_result(capsys):
    """
    異常系テスト: run_debate() で analyst.process が 'stance' キーのない結果を返した場合、
    KeyError が発生し、verify_evolution() が適切に例外をキャッチして False を返すことを確認。
    """
    mock_analyst = MagicMock(spec=Analyst)
    mock_analyst.soul = {"bias_weight": 1.2}
    mock_analyst.process.return_value = {}  # 'stance' キーがない辞書
    
    res = verify_evolution(analyst=mock_analyst)
    assert res is False
    
    captured = capsys.readouterr()
    assert "Data structure error (Missing key: 'stance') occurred during verification" in captured.out


def test_verify_evolution_traceback_output(capsys):
    """例外発生時に標準エラー出力にスタックトレースが出力されることを検証。"""
    mock_analyst = MagicMock(spec=Analyst)
    mock_analyst.process.side_effect = RuntimeError("Traceback test error")
    
    res = verify_evolution(analyst=mock_analyst)
    assert res is False
    
    captured = capsys.readouterr()
    assert "Traceback (most recent call last):" in captured.err
    assert "RuntimeError: Traceback test error" in captured.err
