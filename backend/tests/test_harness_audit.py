"""
Test for HarnessAuditRunner
"""

import os
import json
import pytest
from backend.harness_audit_runner import HarnessAuditRunner

def test_harness_audit_runner_mock():
    runner = HarnessAuditRunner(mock_mode=True)
    summary = runner.run(trigger="all")
    
    assert summary["score"] == 10.0
    assert summary["passed"] == 57
    assert summary["failed"] == 0
    assert summary["skipped"] == 0
    assert summary["trigger"] == "all"
    
    # Check if files generated
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    results_path = os.path.join(base_dir, "backend", "quality_audit_results.json")
    assert os.path.exists(results_path)
    
    # Read output results
    try:
        with open(results_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert data["score"] == 10.0
    except (json.JSONDecodeError, OSError):
        pytest.fail("Failed to parse output JSON results.")

def test_harness_audit_runner_trigger_commit():
    runner = HarnessAuditRunner(mock_mode=True)
    summary = runner.run(trigger="commit")
    
    # Commit trigger has only 2 items targeted, rest skipped
    assert summary["passed"] == 2
    assert summary["skipped"] == 55
    assert summary["failed"] == 0

def test_harness_audit_runner_real():
    runner = HarnessAuditRunner(mock_mode=False)
    summary = runner.run(trigger="commit")
    
    # Real execution will run H-01 and E-01 checks
    # These should pass or fail based on actual codebase state.
    # Just asserting structure and completeness.
    assert "score" in summary
    assert "details" in summary
    assert "H-01" in summary["details"]
    assert "E-01" in summary["details"]


def test_harness_audit_runner_real_deploy():
    runner = HarnessAuditRunner(mock_mode=False)
    summary = runner.run(trigger="deploy")
    
    assert "score" in summary
    assert "details" in summary
    assert "H-02" in summary["details"]

from unittest.mock import patch

def test_harness_audit_runner_exception_handling():
    runner = HarnessAuditRunner(mock_mode=False)
    with patch("backend.harness.tool_registry.ToolRegistry.list_tools", side_effect=TypeError("Mocked TypeError")):
        summary = runner.run(trigger="deploy")
        
        assert "score" in summary
        details = summary["details"]
        assert details["H-02"]["status"] == "FAIL"
        assert "Mocked TypeError" in details["H-02"]["remarks"]



def test_harness_audit_runner_unexpected_exception():
    runner = HarnessAuditRunner(mock_mode=False)
    with patch("os.walk", side_effect=RuntimeError("Mocked RuntimeError")):
        with patch("backend.agents.memory.technical_debt.TechnicalDebtStore.register_debt") as mock_register:
            summary = runner.run(trigger="all")
            
            assert "score" in summary
            details = summary["details"]
            assert details["H-01"]["status"] == "FAIL"
            assert "Mocked RuntimeError" in details["H-01"]["remarks"]

            # Verify it got logged in TechnicalDebtStore
            mock_register.assert_called()
            args, kwargs = mock_register.call_args
            assert kwargs.get("category") == "MINOR_INFRA"
            assert "Mocked RuntimeError" in kwargs.get("notes", "")


def test_harness_audit_runner_os_error_handling():
    runner = HarnessAuditRunner(mock_mode=False)
    original_open = open

    def mock_open(file, *args, **kwargs):
        if "backend/routers" in str(file) or "backend\\routers" in str(file):
            raise OSError("Mocked OSError")
        return original_open(file, *args, **kwargs)

    with patch("builtins.open", side_effect=mock_open):
        summary = runner.run(trigger="all")
        
        assert "score" in summary
        details = summary["details"]
        assert details["H-01"]["status"] == "FAIL"
        assert "Mocked OSError" in details["H-01"]["remarks"]
