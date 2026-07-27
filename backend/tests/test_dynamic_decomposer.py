# verifies: REQ-DAG-01
# verifies: REQ-DAG-02
# verifies: REQ-DAG-04
# satisfies: REQ-DAG-04
import pytest
import os
import tempfile
from pathlib import Path
from agents.orchestration.task_dag import TaskDAG
from agents.orchestration.dynamic_decomposer import DynamicDecomposer

def test_task_dag_basic():
    dag = TaskDAG()
    
    # Add tasks
    dag.add_task("task1", {"id": "task1", "status": "pending"})
    dag.add_task("task2", {"id": "task2", "status": "pending"}, dependencies=["task1"])
    
    assert "task1" in dag.tasks
    assert "task2" in dag.tasks
    assert "task1" in dag.dependencies["task2"]
    assert "task2" in dag.dependents["task1"]

def test_task_dag_cycle_detection():
    dag = TaskDAG()
    dag.add_task("task1", {"id": "task1"})
    dag.add_task("task2", {"id": "task2"}, dependencies=["task1"])
    
    # Adding task3 that depends on task2 is fine
    dag.add_task("task3", {"id": "task3"}, dependencies=["task2"])
    
    # Introducing cycle: task1 depends on task3 should raise ValueError
    with pytest.raises(ValueError, match="introduces a cyclic dependency"):
        dag.add_task("task1", {"id": "task1"}, dependencies=["task3"])

def test_task_dag_topological_sort():
    dag = TaskDAG()
    dag.add_task("task3", {"id": "task3"}, dependencies=["task2"])
    dag.add_task("task2", {"id": "task2"}, dependencies=["task1"])
    dag.add_task("task1", {"id": "task1"})
    
    order = dag.topological_sort()
    assert order.index("task1") < order.index("task2")
    assert order.index("task2") < order.index("task3")

def test_task_dag_executable_tasks():
    dag = TaskDAG()
    dag.add_task("task1", {"id": "task1", "status": "pending"})
    dag.add_task("task2", {"id": "task2", "status": "pending"}, dependencies=["task1"])
    
    # task1 has no dependencies, so it should be executable
    executables = dag.get_executable_tasks()
    assert len(executables) == 1
    assert executables[0]["id"] == "task1"
    
    # Mark task1 as completed/pass
    dag.mark_task_status("task1", "pass")
    
    # Now task2 should be executable
    executables = dag.get_executable_tasks()
    assert len(executables) == 1
    assert executables[0]["id"] == "task2"

def test_task_dag_cascade_failure():
    dag = TaskDAG()
    dag.add_task("task1", {"id": "task1", "status": "pending"})
    dag.add_task("task2", {"id": "task2", "status": "pending"}, dependencies=["task1"])
    dag.add_task("task3", {"id": "task3", "status": "pending"}, dependencies=["task2"])
    
    # Mark task1 as failed
    dag.mark_task_status("task1", "fail")
    
    # task2 and task3 should be skipped due to dependency failure
    assert dag.tasks["task2"]["status"] == "skipped"
    assert dag.tasks["task3"]["status"] == "skipped"
    assert dag.is_complete()

def test_dynamic_decomposer_ast_parsing():
    # Create a dummy python file with imports
    with tempfile.TemporaryDirectory() as tmpdir:
        dummy_file = Path(tmpdir) / "dummy_module.py"
        dummy_file.write_text("import sys\nfrom os import path\nimport json", encoding="utf-8")
        
        decomposer = DynamicDecomposer(workspace_path=tmpdir)
        # Pass path relative to workspace or direct to dummy
        deps = decomposer.analyze_dependency("dummy_module.py")
        assert "sys" in deps
        assert "os" in deps
        assert "json" in deps

        # Test SyntaxError parsing recovery
        invalid_file = Path(tmpdir) / "invalid_syntax.py"
        invalid_file.write_text("import sys\nthis is invalid syntax\nimport json", encoding="utf-8")
        deps_invalid = decomposer.analyze_dependency("invalid_syntax.py")
        assert deps_invalid == []


def test_dynamic_decomposer_build_dag():
    decomposer = DynamicDecomposer()
    
    tasks = [
        {"id": "T1", "instruction": "Test task", "target_module": "agents/orchestration/compliance_guard.py"},
        {"id": "T2", "instruction": "Another test", "is_large_change": True, "target_module": "dummy.py"}
    ]
    
    dag = decomposer.build_dag_from_tasks(tasks)
    assert dag is not None
    
    # T1 might not be decomposed unless it has >=5 imports
    # T2 should be decomposed because is_large_change is True
    t2_split0 = "T2-split0"
    t2_split1 = "T2-split1"
    t2_split2 = "T2-split2"
    
    assert t2_split0 in dag.tasks
    assert t2_split1 in dag.tasks
    assert t2_split2 in dag.tasks
    assert t2_split0 in dag.dependencies[t2_split1]
    assert t2_split1 in dag.dependencies[t2_split2]

# verifies: REQ-DAG-03
def test_orchestrator_dag_integration():
    from agents.orchestration.orchestrator import OrchestrationHub
    from unittest.mock import MagicMock, patch
    
    hub = OrchestrationHub()
    
    # Mock task queue data
    mock_queue = {
        "tasks": [
            {"id": "T1", "status": "pending", "dependencies": []},
            {"id": "T2", "status": "pending", "dependencies": ["T1"]}
        ],
        "current_batch_id": "test_batch",
        "phase": 1,
        "milestone": "M1"
    }
    
    with patch("agents.orchestration.hub_batch.safe_read_json", return_value=mock_queue), \
         patch("agents.orchestration.hub_batch.atomic_write_json") as mock_write, \
         patch.object(hub, "flash_session_start"), \
         patch.object(hub, "flash_update_status"), \
         patch.object(hub, "get_current_directive", return_value=None), \
         patch.object(hub, "read_messages", return_value=[]), \
         patch.object(hub, "acknowledge_message"), \
         patch("agents.orchestration.hub_batch._now_iso", return_value="2026-06-06T12:00:00Z"):
             
        # T1 has no dependencies, so it should be returned.
        # T2 has dependency on T1 (pending), so it should NOT be returned yet.
        batch = hub.get_next_batch(phase=1, milestone="M1", batch_size=5)
        assert len(batch) == 1
        assert batch[0]["id"] == "T1"

# verifies: REQ-DAG-03
def test_orchestrator_cascade_failure():
    from agents.orchestration.orchestrator import OrchestrationHub
    from unittest.mock import MagicMock, patch
    
    hub = OrchestrationHub()
    
    # Mock task queue data
    mock_queue = {
        "tasks": [
            {"id": "T1", "status": "running", "dependencies": []},
            {"id": "T2", "status": "pending", "dependencies": ["T1"]}
        ]
    }
    
    written_queues = []
    def mock_write_fn(path, data):
        written_queues.append(data)
        
    mock_conv = MagicMock()
    mock_conv.should_retry.return_value = {"retry": False, "retry_count": 0, "reason": "exhausted"}
    
    with patch("agents.orchestration.hub_batch.safe_read_json", return_value=mock_queue), \
         patch("agents.orchestration.hub_batch.atomic_write_json", side_effect=mock_write_fn), \
         patch("agents.orchestration.hub_batch.ConvergenceLoop", return_value=mock_conv), \
         patch("agents.orchestration.hub_batch._now_iso", return_value="2026-06-06T12:00:00Z"), \
         patch.object(hub, "flash_report_error"), \
         patch.object(hub, "flash_heartbeat"):
             
        # T1 fails, not retried. Downstream T2 should be skipped.
        hub.mark_task_done("T1", "fail", report={"error": "Something went wrong"})
        
        # Check if T2 status was updated to skipped in the written queues
        found_skipped = False
        for q in written_queues:
            for t in q.get("tasks", []):
                if t["id"] == "T2" and t["status"] == "skipped":
                    found_skipped = True
        
        assert found_skipped, "Downstream task T2 should be marked as skipped"
