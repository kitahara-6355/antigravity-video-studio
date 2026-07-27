import os
import tempfile
import json
import pytest
from backend.agents.orchestration.generator import TaskGenerator
from backend.agents.orchestration.verifier import CodeVerifier
from backend.agents.orchestration.orchestrator import OrchestrationHub

def test_task_generator():
    generator = TaskGenerator()
    stock_items = [
        {
            "id": "DS-999",
            "title": "テスト設計項目",
            "difficulty": "B",
            "description": "テスト用の説明です。",
            "implementation_steps": [
                {"title": "ステップ1", "description": "テスト用のステップ1です。", "target_module": "dummy_module_1.py"},
                {"title": "ステップ2", "description": "テスト用のステップ2です。", "target_module": "dummy_module_2.py"}
            ]
        }
    ]
    tasks = generator.create_batch_tasks("batch_test", stock_items)
    assert len(tasks) == 2
    assert tasks[0]["id"] == "T-batch_test-ds-ds-999-000"
    assert tasks[0]["group"] == "design_stock"
    assert tasks[0]["level"] == "L2"
    assert tasks[0]["target_module"] == "dummy_module_1.py"
    assert "テスト用のステップ1です。" in tasks[0]["instruction"]

def test_code_verifier_static(tmp_path):
    # ダミーファイルの作成
    dummy_file = tmp_path / "dummy.py"
    dummy_file.write_text("def test():\n    try:\n        pass\n    except Exception as e:\n        print(e)\n", encoding="utf-8")
    
    verifier = CodeVerifier(workspace_path=str(tmp_path))
    res = verifier.verify_static("dummy.py")
    assert res["passed"] is False
    assert len(res["errors"]) == 1
    assert "Broad exception handler detected" in res["errors"][0]

def test_code_verifier_dynamic():
    verifier = CodeVerifier()
    # 存在しないテストで失敗することを確認
    res = verifier.verify_dynamic("non_existent_test.py")
    assert res["passed"] is False

def test_orchestration_hub_integration():
    hub = OrchestrationHub()
    # 統合メソッドが存在することを確認
    assert hasattr(hub, "verify_file")
    assert hasattr(hub, "verify_test_suite")
    assert hasattr(hub, "generate_tasks_for_batch")

def test_root_orchestration_hub_integration():
    import importlib.util
    import sys
    from pathlib import Path
    
    import backend.agents.orchestration.report_compressor
    sys.modules['agents.orchestration.report_compressor'] = backend.agents.orchestration.report_compressor
    
    root_dir = Path(__file__).parent.parent.parent
    orchestrator_path = root_dir / "agents" / "orchestration" / "orchestrator.py"
    
    spec = importlib.util.spec_from_file_location("agents.orchestration.orchestrator", str(orchestrator_path))
    root_orchestrator = importlib.util.module_from_spec(spec)
    root_orchestrator.__package__ = "agents.orchestration"
    sys.modules["agents.orchestration.orchestrator"] = root_orchestrator
    spec.loader.exec_module(root_orchestrator)
    
    hub = root_orchestrator.OrchestrationHub()
    # 統合メソッドが存在することを確認
    assert hasattr(hub, "verify_file")
    assert hasattr(hub, "verify_test_suite")
    assert hasattr(hub, "generate_tasks_for_batch")

def test_decompose_by_dependency(tmp_path):
    from backend.agents.orchestration.ds_task_decomposer import decompose_by_dependency
    
    # ダミーのモジュール作成
    dummy_dir = tmp_path / "backend"
    dummy_dir.mkdir(parents=True, exist_ok=True)
    dummy_file = dummy_dir / "dummy_dep.py"
    dummy_file.write_text("import sys\nimport os\nfrom datetime import datetime\nimport json\nimport uuid\n", encoding="utf-8")
    
    task = {
        "id": "T-test-dep",
        "target_module": "dummy_dep.py",
        "instruction": "ダミー実装指示",
        "group": "refactor",
        "level": "L2"
    }
    
    sub_tasks = decompose_by_dependency(task, workspace_path=str(tmp_path))
    # 依存インポートが 5 件（sys, os, datetime, json, uuid）あるため、3分割されること
    assert len(sub_tasks) == 3
    assert "dep0" in sub_tasks[0]["id"]
    assert "sys, os, datetime, json, uuid" in sub_tasks[0]["instruction"]
