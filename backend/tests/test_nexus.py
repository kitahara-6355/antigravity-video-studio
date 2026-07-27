import importlib
import pytest
import warnings
import logging

def _get_nexus_class():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        import agents.nexus
        return agents.nexus.Nexus

def test_nexus_module_warning():
    """モジュールロード時の DeprecationWarning を検証"""
    with warnings.catch_warnings():
        warnings.simplefilter("always", DeprecationWarning)
        import agents.nexus
        with pytest.warns(DeprecationWarning) as record:
            importlib.reload(agents.nexus)
        assert len(record) > 0
        assert "agents.nexus は非推奨です" in str(record[0].message)

def test_nexus_init_logger_warning(caplog):
    """インスタンス化時の logger.warning 出力を検証"""
    Nexus = _get_nexus_class()
    with caplog.at_level(logging.WARNING):
        nexus = Nexus()
        assert len(caplog.records) > 0
        assert "Nexus は非推奨です" in caplog.text

def test_nexus_process():
    """process メソッドの返り値と互換性を検証"""
    Nexus = _get_nexus_class()
    nexus = Nexus()
    input_data = {"test": "data"}
    context = {}
    result = nexus.process(input_data, context)
    assert result == {
        "agent": "Nexus",
        "role": "Router",
        "action": "ROUTE",
        "needed_agents": ["Strategist"],
        "synthesis": "Nexusは非推奨です。ADK版CouncilSupervisorを使用してください。",
    }

def test_nexus_synthesize():
    """synthesize メソッドの返り値と互換性を検証"""
    Nexus = _get_nexus_class()
    nexus = Nexus()
    result = nexus.synthesize([])
    assert result == {
        "type": "SYNTHESIS",
        "proposal": "Nexusは非推奨です。ADK版CouncilSupervisorを使用してください。",
        "options": ["Approve", "Reject"],
    }

def test_nexus_process_edge_cases():
    """process メソッドに None や想定外の型を渡した場合の挙動を検証"""
    Nexus = _get_nexus_class()
    nexus = Nexus()
    result_none = nexus.process(None, None)
    assert result_none["agent"] == "Nexus"
    assert result_none["needed_agents"] == ["Strategist"]
    
    result_str = nexus.process("invalid_input", "invalid_context")
    assert result_str["agent"] == "Nexus"

def test_nexus_synthesize_edge_cases():
    """synthesize メソッドに None や想定外の型を渡した場合の挙動を検証"""
    Nexus = _get_nexus_class()
    nexus = Nexus()
    result_none = nexus.synthesize(None)
    assert result_none["type"] == "SYNTHESIS"
    assert result_none["options"] == ["Approve", "Reject"]
    
    result_str = nexus.synthesize("invalid_responses")
    assert result_str["type"] == "SYNTHESIS"

def test_nexus_process_error_handling(caplog):
    """TypeError/ValueError時のエラーハンドリングを検証"""
    Nexus = _get_nexus_class()
    nexus = Nexus()
    with caplog.at_level(logging.ERROR):
        result = nexus.process(False, False)
        assert "Error:" in result["synthesis"]
        assert "Invalid input data or context" in result["synthesis"]
        assert len(caplog.records) > 0
        assert "Nexus.process でエラーが発生しました" in caplog.text

def test_nexus_synthesize_error_handling(caplog):
    """TypeError/ValueError時のエラーハンドリングを検証"""
    Nexus = _get_nexus_class()
    nexus = Nexus()
    with caplog.at_level(logging.ERROR):
        result = nexus.synthesize(False)
        assert "Error:" in result["proposal"]
        assert "Invalid council responses" in result["proposal"]
        assert len(caplog.records) > 0
        assert "Nexus.synthesize でエラーが発生しました" in caplog.text
