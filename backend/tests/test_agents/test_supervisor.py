import sys
import importlib
import warnings
import logging
import pytest

def test_supervisor_deprecation_warning():
    # warnings をキャッチしてモジュールインポート時の警告を確認
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        
        # 既にインポートされている可能性に備えて reload するか、新規に import する
        if 'agents.supervisor' in sys.modules:
            importlib.reload(sys.modules['agents.supervisor'])
        else:
            importlib.import_module('agents.supervisor')
            
        # DeprecationWarning が発生していることを確認
        deprecation_warnings = [
            warn for warn in w 
            if issubclass(warn.category, DeprecationWarning) and "agents.supervisor" in str(warn.message)
        ]
        assert len(deprecation_warnings) > 0


def test_supervisor_agent_init(caplog):
    from agents.supervisor import SupervisorAgent
    
    with caplog.at_level(logging.WARNING):
        agent = SupervisorAgent()
        
        # ログメッセージの確認
        assert any(
            "SupervisorAgent は非推奨です。council_graph.run_council() に移行してください。" in record.message
            for record in caplog.records
        )


def test_supervisor_agent_route():
    from agents.supervisor import SupervisorAgent
    
    agent = SupervisorAgent()
    route_result = agent.route([])
    
    assert route_result.next == "FINISH"
    assert "SupervisorAgent は非推奨です。" in route_result.reason
