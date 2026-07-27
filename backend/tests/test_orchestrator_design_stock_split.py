# -*- coding: utf-8 -*-
import pytest
from unittest.mock import MagicMock, patch
from agents.orchestration.orchestrator import OrchestrationHub

def test_create_tasks_from_design_stock_no_steps():
    orchestrator = OrchestrationHub()
    ds_item = {
        "id": "DS-100",
        "title": "Test Single",
        "difficulty": "C",
        "description": "desc",
        "source_phase_task": "source"
    }
    with patch.object(orchestrator, "_create_task_from_design_stock") as mock_single:
        mock_single.return_value = {"id": "T-batch-ds-ds-100"}
        res = orchestrator._create_tasks_from_design_stock(ds_item, "batch_123", 27)
        assert len(res) == 1
        assert res[0]["id"] == "T-batch-ds-ds-100"
        mock_single.assert_called_once_with(ds_item, "batch_123", 27)

def test_create_tasks_from_design_stock_with_steps():
    orchestrator = OrchestrationHub()
    ds_item = {
        "id": "DS-101",
        "title": "Test Multi",
        "difficulty": "B",
        "description": "desc",
        "implementation_steps": [
            "Step 1: Fix Foo",
            {"title": "Step 2: Fix Bar", "description": "bar desc", "target_module": "backend/bar.py"}
        ]
    }
    with patch("agents.orchestration.orchestrator._now_iso", return_value="2026-05-31T00:00:00Z"):
        res = orchestrator._create_tasks_from_design_stock(ds_item, "batch_123", 27)
        assert len(res) == 2
        assert res[0]["id"] == "T-batch_123-ds-ds-101-000"
        assert "Step 1: Fix Foo" in res[0]["instruction"]
        assert res[0]["target_module"] is None
        assert res[0]["step_index"] == 0
        assert res[1]["id"] == "T-batch_123-ds-ds-101-001"
        assert "Step 2: Fix Bar" in res[1]["instruction"]
        assert res[1]["target_module"] == "backend/bar.py"
        assert res[1]["step_index"] == 1

def test_task_generator_direct():
    from agents.orchestration.generator import TaskGenerator
    generator = TaskGenerator()
    ds_item = {
        "id": "DS-102",
        "title": "Test Direct",
        "difficulty": "A",
        "description": "desc",
        "implementation_steps": [
            "Step 1",
            {"title": "Step 2", "target_module": "backend/foo.py"}
        ]
    }
    tasks = generator.create_batch_tasks("batch_999", [ds_item], phase=30)
    assert len(tasks) == 2
    assert tasks[0]["id"] == "T-batch_999-ds-ds-102-000"
    assert tasks[0]["design_stock_id"] == "DS-102"
    assert tasks[0]["step_index"] == 0
    assert "Step 1" in tasks[0]["instruction"]
    assert "Phase 30" in tasks[0]["instruction"]
    
    assert tasks[1]["id"] == "T-batch_999-ds-ds-102-001"
    assert tasks[1]["design_stock_id"] == "DS-102"
    assert tasks[1]["step_index"] == 1
    assert "Step 2" in tasks[1]["instruction"]
    assert tasks[1]["target_module"] == "backend/foo.py"

def test_code_verifier_static(tmp_path):
    from agents.orchestration.verifier import CodeVerifier
    
    good_file = tmp_path / "good.py"
    good_file.write_text("def test():\n    pass\n", encoding="utf-8")
    
    bad_file = tmp_path / "bad.py"
    bad_file.write_text("try:\n    do_something()\nexcept Exception:\n    pass\n", encoding="utf-8")
    
    verifier = CodeVerifier(workspace_path=str(tmp_path))
    
    res_good = verifier.verify_static("good.py")
    assert res_good["passed"] is True
    
    res_bad = verifier.verify_static("bad.py")
    assert res_bad["passed"] is False
    assert any("Broad exception handler detected" in err for err in res_bad["errors"])

def test_code_verifier_dynamic():
    from agents.orchestration.verifier import CodeVerifier
    verifier = CodeVerifier()
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="PASSED", stderr="")
        res = verifier.verify_dynamic("backend/tests/test_dummy.py")
        assert res["passed"] is True
        assert res["exit_code"] == 0
        mock_run.assert_called_once()

