import sys
import importlib
import logging
import pytest
from backend.agents.nexus import Nexus

def test_nexus_deprecation_warning():
    # キャッシュをクリアして再ロードし、警告を検証する
    if "backend.agents.nexus" in sys.modules:
        del sys.modules["backend.agents.nexus"]
    
    with pytest.warns(DeprecationWarning) as record:
        importlib.import_module("backend.agents.nexus")
    
    assert len(record) > 0
    assert any("agents.nexus は非推奨です" in str(w.message) for w in record)

def test_nexus_init_logging(caplog):
    # Nexusクラスのインスタンス化時に警告ログが出力されることを検証
    with caplog.at_level(logging.WARNING):
        _ = Nexus()
    
    assert any("Nexus は非推奨です" in record.message for record in caplog.records)

def test_nexus_process():
    nexus_inst = Nexus()
    input_data = {"test": "data"}
    context = {"test": "context"}
    res = nexus_inst.process(input_data, context)
    
    assert res == {
        "agent": "Nexus",
        "role": "Router",
        "action": "ROUTE",
        "needed_agents": ["Strategist"],
        "synthesis": "Nexusは非推奨です。ADK版CouncilSupervisorを使用してください。",
    }

def test_nexus_synthesize():
    nexus_inst = Nexus()
    council_responses = [{"response": "ok"}]
    res = nexus_inst.synthesize(council_responses)
    
    assert res == {
        "type": "SYNTHESIS",
        "proposal": "Nexusは非推奨です。ADK版CouncilSupervisorを使用してください。",
        "options": ["Approve", "Reject"],
    }

def test_nexus_process_edge_cases():
    nexus_inst = Nexus()
    res_none = nexus_inst.process(None, None)
    assert res_none["agent"] == "Nexus"
    assert res_none["needed_agents"] == ["Strategist"]
    
    res_str = nexus_inst.process("invalid_input", "invalid_context")
    assert res_str["agent"] == "Nexus"

def test_nexus_synthesize_edge_cases():
    nexus_inst = Nexus()
    res_none = nexus_inst.synthesize(None)
    assert res_none["type"] == "SYNTHESIS"
    assert res_none["options"] == ["Approve", "Reject"]
    
    res_str = nexus_inst.synthesize("invalid_responses")
    assert res_str["type"] == "SYNTHESIS"
