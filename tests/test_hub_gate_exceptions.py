import pytest
import json
import subprocess
from unittest.mock import patch, MagicMock
from pathlib import Path
from agents.orchestration.hub_gate import GateMixin

class DummyGateMixin(GateMixin):
    def flash_heartbeat(self):
        pass
    def flash_update_status(self, *args, **kwargs):
        pass
    def _git_auto_commit(self, *args, **kwargs):
        pass
    def _auto_measure_coverage(self, *args, **kwargs):
        pass
    def _capture_git_diff(self, *args, **kwargs):
        return {"files_changed": 0}
    def _safe_instrument(self, name, func, *args, **kwargs):
        try:
            func(*args, **kwargs)
        except Exception:
            pass
    def _get_module_miss_counts(self):
        return {}
    def generate_hourly_report(self, *args, **kwargs):
        pass
    def _update_subagent_dashboard(self, *args, **kwargs):
        pass
    def _emit_harness_audit_log(self, *args, **kwargs):
        pass

@pytest.fixture
def dummy_gate():
    return DummyGateMixin()

def test_check_phase_gate_coverage_exception(dummy_gate):
    with patch("agents.orchestration.hub_gate.safe_read_json") as mock_read, \
         patch("agents.orchestration.hub_common._read_jsonl") as mock_read_jsonl, \
         patch("agents.orchestration.hub_gate.logger") as mock_logger:
        
        def side_effect(path, default=None):
            path_str = str(path).lower()
            if "gate" in path_str:
                return {"5": {"conditions": []}}
            return {
                "metrics": {},
                "emergency_stop": False,
                "gate_checklist": {}
            }
        mock_read.side_effect = side_effect
        
        mock_read_jsonl.side_effect = OSError("Mock disk error")
        
        result = dummy_gate.check_phase_gate(5)
        
        assert result["phase"] == 5
        assert result["conditions"]["changed_line_coverage"] is True
        mock_logger.warning.assert_any_call("[GateKeeper] カバレッジ検証エラー: Mock disk error")

def test_check_phase_gate_ux_ratchet_exception(dummy_gate):
    with patch("agents.orchestration.hub_gate.safe_read_json") as mock_read, \
         patch("subprocess.run") as mock_run, \
         patch("agents.orchestration.hub_gate.logger") as mock_logger:
        
        def side_effect(path, default=None):
            path_str = str(path).lower()
            if "gate" in path_str:
                return {"5": {"conditions": []}}
            return {
                "metrics": {},
                "emergency_stop": False,
                "gate_checklist": {}
            }
        mock_read.side_effect = side_effect
        
        mock_run.side_effect = subprocess.SubprocessError("Mock subprocess error")
        
        result = dummy_gate.check_phase_gate(5)
        
        assert result["phase"] == 5
        assert result["conditions"]["ux_ratchet_pass"] is False
        mock_logger.warning.assert_any_call("[GateKeeper] UXラチェット検証エラー: Mock subprocess error")

def test_get_actual_critical_debt_count_exception(dummy_gate):
    with patch("agents.orchestration.hub_gate.safe_read_json") as mock_read:
        mock_read.side_effect = json.JSONDecodeError("Expecting value", "doc", 0)
        
        count = dummy_gate._get_actual_critical_debt_count()
        assert count == 0

def test_submit_batch_report_read_exception(dummy_gate):
    with patch("agents.orchestration.hub_gate.safe_read_json") as mock_read, \
         patch("agents.orchestration.hub_gate.atomic_write_json") as mock_atomic_write, \
         patch("agents.orchestration.hub_gate.logger") as mock_logger:
        
        def side_effect(path, default=None):
            path_str = str(path).lower()
            if "queue" in path_str:
                raise json.JSONDecodeError("Expecting value", "doc", 0)
            return {
                "metrics": {},
                "emergency_stop": False,
                "current_phase": 5
            }
        mock_read.side_effect = side_effect
        
        with patch.object(dummy_gate, "_get_actual_critical_debt_count", return_value=0), \
             patch.object(dummy_gate, "check_phase_gate", return_value={"all_passed": False}), \
             patch.object(dummy_gate, "flash_heartbeat"), \
             patch.object(dummy_gate, "flash_update_status"), \
             patch("agents.orchestration.hub_gate._append_jsonl"), \
             patch("backend.harness.governance.governance_engine.validate_batch_quality"):
            
            dummy_gate.submit_batch_report("dummy_batch", {"passed": 1, "failed": 0})
