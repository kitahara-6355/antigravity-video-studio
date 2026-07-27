"""DS Task Decomposer のテスト"""
import json
import pytest
from pathlib import Path
from backend.agents.orchestration.ds_task_decomposer import (
    decompose_ds_item,
    _decompose_from_description,
    _decompose_from_steps,
    _difficulty_to_level,
    add_implementation_steps,
    get_decomposition_summary,
)


class TestDecomposeDsItem:

    def test_difficulty_s_creates_3_tasks(self):
        """難易度S → 3タスク（設計→実装→テスト）"""
        ds = {"id": "DS-099", "title": "大規模設計", "description": "テスト",
              "difficulty": "S"}
        tasks = decompose_ds_item(ds, "batch_test")
        assert len(tasks) == 3
        assert any("設計" in t["instruction"] for t in tasks)
        assert any("実装" in t["instruction"] for t in tasks)
        assert any("テスト" in t["instruction"] for t in tasks)

    def test_difficulty_a_creates_3_tasks(self):
        """難易度A → 3タスク"""
        ds = {"id": "DS-100", "title": "A級タスク", "description": "テスト",
              "difficulty": "A"}
        tasks = decompose_ds_item(ds, "batch_test")
        assert len(tasks) == 3

    def test_difficulty_b_creates_2_tasks(self):
        """難易度B → 2タスク（実装→テスト）"""
        ds = {"id": "DS-101", "title": "B級タスク", "description": "テスト",
              "difficulty": "B"}
        tasks = decompose_ds_item(ds, "batch_test")
        assert len(tasks) == 2

    def test_difficulty_c_creates_1_task(self):
        """難易度C → 1タスク"""
        ds = {"id": "DS-102", "title": "C級タスク", "description": "テスト",
              "difficulty": "C"}
        tasks = decompose_ds_item(ds, "batch_test")
        assert len(tasks) == 1

    def test_implementation_steps_override(self):
        """implementation_stepsがある場合はそれを優先"""
        ds = {
            "id": "DS-103", "title": "ステップ指定",
            "description": "テスト", "difficulty": "S",
            "implementation_steps": [
                "ステップ1: 型定義",
                "ステップ2: 実装",
            ]
        }
        tasks = decompose_ds_item(ds, "batch_test")
        assert len(tasks) == 2
        assert "ステップ1" in tasks[0]["instruction"]
        assert "ステップ2" in tasks[1]["instruction"]

    def test_implementation_steps_dict_format(self):
        """implementation_stepsがdict形式でも動作"""
        ds = {
            "id": "DS-104", "title": "Dict形式",
            "description": "テスト", "difficulty": "B",
            "implementation_steps": [
                {"description": "設計", "target_file": "services/foo.py"},
                {"description": "テスト", "target_module": "tests/test_foo.py"},
            ]
        }
        tasks = decompose_ds_item(ds, "batch_test")
        assert len(tasks) == 2
        assert tasks[0]["target_module"] == "services/foo.py"
        assert tasks[1]["target_module"] == "tests/test_foo.py"

    def test_task_ids_are_unique(self):
        """タスクIDが一意"""
        ds = {"id": "DS-105", "title": "ID", "description": "テスト",
              "difficulty": "S"}
        tasks = decompose_ds_item(ds, "batch_test")
        ids = [t["id"] for t in tasks]
        assert len(ids) == len(set(ids))

    def test_max_tasks_limit(self):
        """max_tasksで生成数が制限される"""
        ds = {
            "id": "DS-106", "title": "制限テスト",
            "description": "テスト", "difficulty": "S",
            "implementation_steps": ["s1", "s2", "s3", "s4", "s5"],
        }
        tasks = decompose_ds_item(ds, "batch_test", max_tasks=2)
        assert len(tasks) == 2

    def test_constraint_in_instruction(self):
        """制約が指示に含まれる"""
        ds = {"id": "DS-107", "title": "制約", "description": "テスト",
              "difficulty": "C"}
        tasks = decompose_ds_item(ds, "batch_test")
        assert "3ファイル" in tasks[0]["instruction"]

    def test_level_mapping(self):
        """難易度→レベル変換"""
        assert _difficulty_to_level("S") == "L4"
        assert _difficulty_to_level("A") == "L3"
        assert _difficulty_to_level("B") == "L2"
        assert _difficulty_to_level("C") == "L1"

    def test_get_decomposition_summary(self):
        """サマリーが正常に生成される"""
        ds = {"id": "DS-108", "title": "サマリー", "description": "テスト",
              "difficulty": "B"}
        summary = get_decomposition_summary(ds)
        assert "DS-108" in summary
        assert "2タスク" in summary


class TestAddImplementationSteps:

    def test_add_steps_to_existing_item(self, tmp_path):
        """既存DS項目にstepsを追加"""
        ds_path = tmp_path / "design_stock.json"
        data = {"stock_items": [
            {"id": "DS-001", "title": "テスト", "status": "pending"},
        ]}
        ds_path.write_text(json.dumps(data), encoding="utf-8")

        # パスをモンキーパッチ
        import backend.agents.orchestration.ds_task_decomposer as mod
        orig = mod._DESIGN_STOCK_PATH
        mod._DESIGN_STOCK_PATH = ds_path
        try:
            result = add_implementation_steps("DS-001", ["step1", "step2"])
            assert result is True
            updated = json.loads(ds_path.read_text(encoding="utf-8"))
            assert updated["stock_items"][0]["implementation_steps"] == ["step1", "step2"]
        finally:
            mod._DESIGN_STOCK_PATH = orig

    def test_add_steps_nonexistent_item(self, tmp_path):
        """存在しないDS項目にstepsを追加→False"""
        ds_path = tmp_path / "design_stock.json"
        data = {"stock_items": []}
        ds_path.write_text(json.dumps(data), encoding="utf-8")

        import backend.agents.orchestration.ds_task_decomposer as mod
        orig = mod._DESIGN_STOCK_PATH
        mod._DESIGN_STOCK_PATH = ds_path
        try:
            result = add_implementation_steps("DS-999", ["step1"])
            assert result is False
        finally:
            mod._DESIGN_STOCK_PATH = orig

    def test_add_steps_json_decode_error(self, tmp_path, caplog):
        """JSON破損時に例外をキャッチしてFalseを返すか検証"""
        ds_path = tmp_path / "design_stock.json"
        ds_path.write_text("{ invalid json", encoding="utf-8")

        import backend.agents.orchestration.ds_task_decomposer as mod
        orig = mod._DESIGN_STOCK_PATH
        mod._DESIGN_STOCK_PATH = ds_path
        try:
            import logging
            with caplog.at_level(logging.WARNING):
                result = add_implementation_steps("DS-001", ["step1"])
                assert result is False
                assert "Failed to add steps" in caplog.text
        finally:
            mod._DESIGN_STOCK_PATH = orig

    def test_add_steps_os_error(self, tmp_path, caplog):
        """書き込み不可などのOSError時に例外をキャッチしてFalseを返すか検証"""
        ds_path = tmp_path / "design_stock.json"
        data = {"stock_items": [
            {"id": "DS-001", "title": "テスト", "status": "pending"},
        ]}
        ds_path.write_text(json.dumps(data), encoding="utf-8")

        import backend.agents.orchestration.ds_task_decomposer as mod
        orig = mod._DESIGN_STOCK_PATH
        mod._DESIGN_STOCK_PATH = ds_path
        
        from unittest.mock import patch
        try:
            import logging
            with caplog.at_level(logging.WARNING):
                with patch.object(Path, "write_text", side_effect=OSError("Mock disk full")):
                    result = add_implementation_steps("DS-001", ["step1"])
                    assert result is False
                    assert "Failed to add steps" in caplog.text
                    assert "Mock disk full" in caplog.text
        finally:
            mod._DESIGN_STOCK_PATH = orig


class TestDecomposeLargeChangeTask:

    def test_decompose_large_change_task_creates_3_tasks(self):
        """大規模変更タスクを3つのステップ（設計、実装、テスト）に分割できるか検証"""
        task = {
            "id": "T-batch_abc-refactor-000",
            "group": "refactor",
            "level": "L2",
            "target_module": "backend/cache_manager.py",
            "instruction": "cache_manager.pyのリファクタリングを行ってください。"
        }
        from backend.agents.orchestration.ds_task_decomposer import decompose_large_change_task
        tasks = decompose_large_change_task(task)
        assert len(tasks) == 3
        
        # 1つ目のタスク: 設計
        assert tasks[0]["id"] == "T-batch_abc-refactor-000-split0"
        assert tasks[0]["target_module"] == "backend/cache_manager.py"
        assert "設計" in tasks[0]["instruction"]
        assert tasks[0]["split_from"] == "T-batch_abc-refactor-000"
        
        # 2つ目のタスク: 実装
        assert tasks[1]["id"] == "T-batch_abc-refactor-000-split1"
        assert "実装" in tasks[1]["instruction"]
        
        # 3つ目のタスク: テスト
        assert tasks[2]["id"] == "T-batch_abc-refactor-000-split2"
        assert "テスト" in tasks[2]["instruction"]

    def test_decompose_large_change_task_max_tasks_limit(self):
        """max_tasks引数による分割数制限の検証"""
        task = {
            "id": "T-batch_abc-refactor-000",
            "group": "refactor",
            "level": "L2",
            "target_module": "backend/cache_manager.py",
            "instruction": "cache_manager.pyのリファクタリングを行ってください。"
        }
        from backend.agents.orchestration.ds_task_decomposer import decompose_large_change_task
        tasks = decompose_large_change_task(task, max_tasks=2)
        assert len(tasks) == 2


class TestDecomposeByDependency:

    def test_no_target_module(self):
        """target_moduleがない場合は分解せずそのまま返す"""
        task = {"id": "T-no-target", "instruction": "指示"}
        from backend.agents.orchestration.ds_task_decomposer import decompose_by_dependency
        res = decompose_by_dependency(task)
        assert res == [task]

    def test_nonexistent_target_module(self, tmp_path):
        """存在しないモジュールが指定された場合はそのまま返す"""
        task = {"id": "T-nonexistent", "target_module": "nonexistent.py", "instruction": "指示"}
        from backend.agents.orchestration.ds_task_decomposer import decompose_by_dependency
        res = decompose_by_dependency(task, workspace_path=str(tmp_path))
        assert res == [task]

    def test_low_dependency_creates_2_tasks(self, tmp_path):
        """依存が5件未満の場合は2分割される"""
        dummy_dir = tmp_path / "backend"
        dummy_dir.mkdir(parents=True, exist_ok=True)
        dummy_file = dummy_dir / "low_dep.py"
        dummy_file.write_text("import os\nimport sys\n", encoding="utf-8")

        task = {
            "id": "T-low-dep",
            "target_module": "low_dep.py",
            "instruction": "指示",
            "group": "refactor",
            "level": "L2"
        }
        from backend.agents.orchestration.ds_task_decomposer import decompose_by_dependency
        res = decompose_by_dependency(task, workspace_path=str(tmp_path))
        assert len(res) == 2
        assert "実装" in res[0]["instruction"]
        assert "テスト" in res[1]["instruction"]

    def test_high_dependency_creates_3_tasks(self, tmp_path):
        """依存が5件以上の場合は3分割される"""
        dummy_dir = tmp_path / "backend"
        dummy_dir.mkdir(parents=True, exist_ok=True)
        dummy_file = dummy_dir / "high_dep.py"
        dummy_file.write_text(
            "import os\nimport sys\nimport json\nimport math\nimport datetime\n",
            encoding="utf-8"
        )

        task = {
            "id": "T-high-dep",
            "target_module": "high_dep.py",
            "instruction": "指示",
            "group": "refactor",
            "level": "L2"
        }
        from backend.agents.orchestration.ds_task_decomposer import decompose_by_dependency
        res = decompose_by_dependency(task, workspace_path=str(tmp_path))
        assert len(res) == 3
        assert "モック設定" in res[0]["instruction"]
        assert "メインロジック" in res[1]["instruction"]
        assert "統合検証テスト" in res[2]["instruction"]

    def test_decompose_by_dependency_syntax_error(self, tmp_path, caplog):
        """SyntaxError発生時に例外をキャッチして安全にフォールバックするか検証"""
        dummy_dir = tmp_path / "backend"
        dummy_dir.mkdir(parents=True, exist_ok=True)
        dummy_file = dummy_dir / "bad_syntax.py"
        dummy_file.write_text("class BadSyntax:\n    def invalid syntax here ()\n", encoding="utf-8")

        task = {
            "id": "T-bad-syntax",
            "target_module": "bad_syntax.py",
            "instruction": "指示",
            "group": "refactor",
            "level": "L2"
        }
        from backend.agents.orchestration.ds_task_decomposer import decompose_by_dependency
        import logging
        with caplog.at_level(logging.WARNING):
            res = decompose_by_dependency(task, workspace_path=str(tmp_path))
            assert "AST parsing / dependency extraction failed" in caplog.text
            assert len(res) == 2


