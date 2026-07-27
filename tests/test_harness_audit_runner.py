import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from backend.harness_audit_runner import HarnessAuditRunner, ALL_ITEMS, TRIGGER_MAP

def test_harness_audit_runner_mock_mode():
    runner = HarnessAuditRunner(mock_mode=True)
    summary = runner.run(trigger="all")
    
    assert summary["passed"] == len(ALL_ITEMS)
    assert summary["failed"] == 0
    assert summary["skipped"] == 0
    assert summary["score"] == 10.0
    assert isinstance(summary["timestamp"], str)

def test_harness_audit_runner_trigger_filtering():
    runner = HarnessAuditRunner(mock_mode=True)
    summary = runner.run(trigger="commit")
    
    details = summary["details"]
    for item in ALL_ITEMS:
        if item in ["D-01", "E-01"]:
            assert details[item]["status"] == "PASS"
        else:
            assert details[item]["status"] == "SKIP"
            assert details[item]["remarks"].startswith("Not targeted by trigger")
            
    assert summary["skipped"] == len(ALL_ITEMS) - 2

def test_check_item_h01_pass():
    runner = HarnessAuditRunner(mock_mode=False)
    
    with patch("os.walk") as mock_walk:
        mock_walk.return_value = [
            ("backend/routers", [], ["test_router.py"])
        ]
        with patch("builtins.open", create=True) as mock_open:
            mock_open.return_value.__enter__.return_value.read.return_value = "class ModernRouter:\n    pass"
            res = runner._check_item("H-01")
            assert res["status"] == "PASS"
            assert "No legacy path references found" in res["remarks"]

def test_check_item_h01_fail_legacy():
    runner = HarnessAuditRunner(mock_mode=False)
    
    with patch("os.walk") as mock_walk:
        mock_walk.return_value = [
            ("backend/routers", [], ["legacy_router.py"])
        ]
        with patch("builtins.open", create=True) as mock_open:
            mock_open.return_value.__enter__.return_value.read.return_value = "import SequentialAgent"
            res = runner._check_item("H-01")
            assert res["status"] == "FAIL"
            assert "Legacy sequential agent / legacy pipeline references found in routers" in res["remarks"]

def test_check_item_h01_fail_oserror():
    runner = HarnessAuditRunner(mock_mode=False)
    
    with patch("os.walk") as mock_walk:
        mock_walk.return_value = [
            ("backend/routers", [], ["broken_router.py"])
        ]
        with patch("builtins.open", side_effect=OSError("Read error")):
            res = runner._check_item("H-01")
            assert res["status"] == "FAIL"
            assert "Scan completed with read errors" in res["remarks"]

def test_check_item_h02_pass():
    runner = HarnessAuditRunner(mock_mode=False)
    
    mock_registry = MagicMock()
    mock_registry.list_tools.return_value = ["tool1", "tool2", "tool3", "tool4", "tool5"]
    
    with patch.dict("sys.modules", {"backend.harness.tool_registry": MagicMock()}):
        with patch("backend.harness.tool_registry.ToolRegistry", return_value=mock_registry):
            res = runner._check_item("H-02")
            assert res["status"] == "PASS"
            assert "ToolRegistry has 5 tools registered" in res["remarks"]

def test_check_item_h02_fail_import_error():
    runner = HarnessAuditRunner(mock_mode=False)
    
    with patch("sys.modules", {}):
        with patch("builtins.__import__", side_effect=ImportError("No module named tool_registry")):
            res = runner._check_item("H-02")
            assert res["status"] == "FAIL"
            assert "Failed to load ToolRegistry" in res["remarks"]

def test_check_item_h02_fail_validation_error():
    runner = HarnessAuditRunner(mock_mode=False)
    
    mock_registry = MagicMock()
    mock_registry.list_tools.side_effect = AttributeError("Mock attribute error")
    
    with patch.dict("sys.modules", {"backend.harness.tool_registry": MagicMock()}):
        with patch("backend.harness.tool_registry.ToolRegistry", return_value=mock_registry):
            res = runner._check_item("H-02")
            assert res["status"] == "FAIL"
            assert "ToolRegistry validation error" in res["remarks"]

def test_check_item_e01_pass():
    runner = HarnessAuditRunner(mock_mode=False)
    
    with patch("os.walk") as mock_walk:
        mock_walk.return_value = [
            ("backend", [], ["safe.py"])
        ]
        with patch("builtins.open", create=True) as mock_open:
            mock_open.return_value.__enter__.return_value.read.return_value = "API_KEY = os.getenv('API_KEY')"
            res = runner._check_item("E-01")
            assert res["status"] == "PASS"
            assert "No hardcoded API keys detected" in res["remarks"]

def test_check_item_e01_fail_hardcoded():
    runner = HarnessAuditRunner(mock_mode=False)
    
    with patch("os.walk") as mock_walk:
        mock_walk.return_value = [
            ("backend", [], ["unsafe.py"])
        ]
        with patch("builtins.open", create=True) as mock_open:
            mock_open.return_value.__enter__.return_value.read.return_value = "API_KEY = 'AIzaSyFakeKey'"
            res = runner._check_item("E-01")
            assert res["status"] == "FAIL"
            assert "API key pattern 'AIzaSy' found in production code" in res["remarks"]

def test_check_item_generic_exception_triggers_tdr():
    runner = HarnessAuditRunner(mock_mode=False)
    
    with patch("os.walk", side_effect=TypeError("Forced type error")):
        mock_store = MagicMock()
        with patch("backend.agents.memory.technical_debt.TechnicalDebtStore", return_value=mock_store):
            res = runner._check_item("H-01")
            assert res["status"] == "FAIL"
            assert "Exception occurred during verification" in res["remarks"]
            mock_store.register_debt.assert_called_once()
            args, kwargs = mock_store.register_debt.call_args
            assert kwargs["category"] == "MINOR_INFRA"
            assert "except (ImportError, AttributeError, TypeError, ValueError, OSError)" in kwargs["pattern"]
