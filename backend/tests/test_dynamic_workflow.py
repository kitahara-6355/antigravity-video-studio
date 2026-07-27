# -*- coding: utf-8 -*-
# verifies: REQ-WAVE-06, REQ-WAVE-07, REQ-CONV-07
# verifies: REQ-CHK-01, REQ-CHK-02, REQ-CHK-03
# verifies: REQ-DAG-06, REQ-DAG-07, REQ-DAG-08
import asyncio
import os
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from agents.orchestration.task_dag import TaskDAG
from agents.orchestration.dynamic_decomposer import DynamicDecomposer
from agents.orchestration.dynamic_workflow_engine import DynamicWorkflowEngine
from agents.orchestration.workflow_checkpoint import WorkflowCheckpoint
from agents.orchestration.workflow_planner import WorkflowPlanner, CircularDependencyError

# =====================================================================
# 1. DynamicWorkflowEngine のテスト
# =====================================================================

class TestDynamicWorkflowEngine:
    """DynamicWorkflowEngineの並列実行ウェーブ、リソース制限、リトライとカスケード失敗のテスト"""

    @pytest.mark.asyncio
    async def test_wave_parallel_execution(self, tmp_path):
        """DAG依存性に基づくウェーブ並列実行が正しく順序制御されることを検証"""
        # verifies: REQ-WAVE-06
        checkpoint_mgr = WorkflowCheckpoint(checkpoint_dir=str(tmp_path))
        decomposer = DynamicDecomposer()
        planner = WorkflowPlanner(decomposer=decomposer)
        
        engine = DynamicWorkflowEngine(
            workflow_id="test_wave",
            checkpoint_manager=checkpoint_mgr,
            planner=planner,
            wave_size=5,
            max_retries=1
        )
        
        # 目標: G1, G2 (独立並列) -> G3 (G1, G2に依存)
        goals = [
            {"id": "G1", "target_module": "t1.py", "dependencies": [], "instruction": "Task 1"},
            {"id": "G2", "target_module": "t2.py", "dependencies": [], "instruction": "Task 2"},
            {"id": "G3", "target_module": "t3.py", "dependencies": ["T-G1", "T-G2"], "instruction": "Task 3"},
        ]
        
        engine.initialize_workflow(goals)
        
        # 実行監視用データ
        running_tasks = set()
        execution_order = []
        
        async def mock_worker(task):
            running_tasks.add(task["id"])
            # A, Bの並列実行時間を作るためのウェイト
            await asyncio.sleep(0.1)
            execution_order.append(task["id"])
            running_tasks.remove(task["id"])
            return {"success": True, "report": {"status": "ok"}}
            
        engine.worker_func = mock_worker
        
        success = await engine.start()
        assert success
        assert engine.dag.is_complete()
        
        # T-G1 と T-G2 が T-G3 より先に実行されていることを確認
        assert execution_order.index("T-G1") < execution_order.index("T-G3")
        assert execution_order.index("T-G2") < execution_order.index("T-G3")

    @pytest.mark.asyncio
    async def test_resource_pool_exhaustion_throttling(self, tmp_path):
        """スレッド制限数（wave_size）を超えてタスクが同時に動かないことを検証"""
        # verifies: REQ-WAVE-07
        checkpoint_mgr = WorkflowCheckpoint(checkpoint_dir=str(tmp_path))
        decomposer = DynamicDecomposer()
        planner = WorkflowPlanner(decomposer=decomposer)
        
        # wave_size = 2 でスロット数を制限
        engine = DynamicWorkflowEngine(
            workflow_id="test_throttle",
            checkpoint_manager=checkpoint_mgr,
            planner=planner,
            wave_size=2,
            max_retries=1
        )
        
        # 5個の独立した並列タスク
        goals = [
            {"id": f"G{i}", "target_module": f"t{i}.py", "dependencies": [], "instruction": f"Task {i}"}
            for i in range(5)
        ]
        engine.initialize_workflow(goals)
        
        max_concurrent = 0
        current_concurrent = 0
        
        async def mock_worker(task):
            nonlocal current_concurrent, max_concurrent
            current_concurrent += 1
            max_concurrent = max(max_concurrent, current_concurrent)
            await asyncio.sleep(0.05)
            current_concurrent -= 1
            return {"success": True}
            
        engine.worker_func = mock_worker
        
        await engine.start()
        # 同時実行タスク数が wave_size (2) を超えていないことを検証
        assert max_concurrent <= 2

    @pytest.mark.asyncio
    async def test_retry_and_cascade_skipping(self, tmp_path):
        """タスクエラー時のリトライ失敗および下流のカスケードスキップを検証"""
        # verifies: REQ-CONV-07
        checkpoint_mgr = WorkflowCheckpoint(checkpoint_dir=str(tmp_path))
        decomposer = DynamicDecomposer()
        planner = WorkflowPlanner(decomposer=decomposer)
        
        # リトライ上限を2回に設定
        engine = DynamicWorkflowEngine(
            workflow_id="test_cascade",
            checkpoint_manager=checkpoint_mgr,
            planner=planner,
            wave_size=5,
            max_retries=2
        )
        
        # T-G1 (失敗・リプラン不可で永久失敗) -> T-G2 (T-G1に依存) / T-G3 (独立正常)
        goals = [
            {"id": "G1", "target_module": "t1.py", "dependencies": [], "instruction": "Fail Task"},
            {"id": "G2", "target_module": "t2.py", "dependencies": ["T-G1"], "instruction": "Dependent Task"},
            {"id": "G3", "target_module": "t3.py", "dependencies": [], "instruction": "Independent Normal Task"},
        ]
        
        engine.initialize_workflow(goals)
        
        attempts = 0
        async def mock_worker(task):
            nonlocal attempts
            if task["id"] == "T-G1":
                attempts += 1
                return {"success": False, "report": {"error": "Perm failure"}}
            return {"success": True}
            
        engine.worker_func = mock_worker
        
        # プランナーのリプランを強制例外にしてリプラン不可（カスケード発生）にする
        with patch.object(planner, "replan_on_failure", side_effect=CircularDependencyError("No bypass")):
            await engine.start()
            
        # 1回目 + リトライ2回 = 計3回実行されたこと
        assert attempts == 3
        # T-G1 は failed
        assert engine.dag.tasks["T-G1"]["status"] == "failed"
        # 依存する T-G2 は skipped になっていること
        assert engine.dag.tasks["T-G2"]["status"] == "skipped"
        # 依存関係のない T-G3 は正常に pass になっていること
        assert engine.dag.tasks["T-G3"]["status"] == "pass"


class SimulatedCrashError(BaseException):
    """クラッシュテスト用のBaseException"""
    pass


# =====================================================================
# 2. WorkflowCheckpoint のテスト
# =====================================================================

class TestWorkflowCheckpoint:
    """WorkflowCheckpointの状態永続化、アトミック性、レジューム、ロールバック検証"""

    def test_atomic_file_write_and_recovery(self, tmp_path):
        """書き込み中の例外発生でも既存チェックポイントが破損しないことを検証"""
        # verifies: REQ-CHK-01
        checkpoint_mgr = WorkflowCheckpoint(checkpoint_dir=str(tmp_path))
        dag = TaskDAG()
        dag.add_task("task1", {"id": "task1", "status": "pending"})
        
        # 1. 最初のチェックポイントは正常に保存
        cp_id = checkpoint_mgr.save("wf_atomic", dag, {"step": 1})
        assert cp_id
        
        latest_file = tmp_path / "cp_latest_wf_atomic.json"
        assert latest_file.exists()
        
        # 元のファイルを読み込み
        with open(latest_file, "r", encoding="utf-8") as f:
            original_data = json.load(f)
            
        # 2. 二回目の保存で、json.dump時に疑似エラーを発生させる
        with patch("json.dump", side_effect=OSError("Disk full")):
            with pytest.raises(OSError):
                checkpoint_mgr.save("wf_atomic", dag, {"step": 2})
                
        # 3. 失敗後も、最新ファイルが前回のデータで保護されていることを検証
        with open(latest_file, "r", encoding="utf-8") as f:
            current_data = json.load(f)
            
        assert current_data["context"]["step"] == 1
        assert current_data == original_data

    @pytest.mark.asyncio
    async def test_crash_recovery_and_resume(self, tmp_path):
        """プロセスクラッシュ発生後のチェックポイント再開（Resume）を検証"""
        # verifies: REQ-CHK-02
        checkpoint_mgr = WorkflowCheckpoint(checkpoint_dir=str(tmp_path))
        decomposer = DynamicDecomposer()
        planner = WorkflowPlanner(decomposer=decomposer)
        
        engine = DynamicWorkflowEngine(
            workflow_id="wf_crash",
            checkpoint_manager=checkpoint_mgr,
            planner=planner,
            wave_size=1,
            max_retries=1
        )
        
        goals = [
            {"id": "G1", "target_module": "t1.py", "dependencies": [], "instruction": "Task 1"},
            {"id": "G2", "target_module": "t2.py", "dependencies": ["T-G1"], "instruction": "Task 2"},
        ]
        
        engine.initialize_workflow(goals)
        
        # T-G1 が完了した時点でクラッシュ（例外）させる
        g1_executed = False
        g2_executed = False
        
        async def mock_worker_1(task):
            nonlocal g1_executed
            if task["id"] == "T-G1":
                g1_executed = True
                return {"success": True}
            elif task["id"] == "T-G2":
                raise SimulatedCrashError("Simulated Crash!")
            return {"success": True}
            
        engine.worker_func = mock_worker_1
        
        # クラッシュ実行
        with pytest.raises(SimulatedCrashError):
            await engine.start()
            
        assert g1_executed
        assert not g2_executed
        
        # 新しいエンジンで再開
        new_engine = DynamicWorkflowEngine(
            workflow_id="wf_crash",
            checkpoint_manager=checkpoint_mgr,
            planner=planner,
            wave_size=1,
            max_retries=1
        )
        
        async def mock_worker_2(task):
            nonlocal g2_executed
            if task["id"] == "T-G2":
                g2_executed = True
            return {"success": True}
            
        new_engine.worker_func = mock_worker_2
        
        # 再開（完了済みのT-G1はスキップされ、T-G2のみが実行される）
        resumed = await new_engine.resume()
        assert resumed
        assert g2_executed
        assert new_engine.dag.tasks["T-G1"]["status"] == "pass"
        assert new_engine.dag.tasks["T-G2"]["status"] == "pass"

    def test_fatal_error_rollback(self, tmp_path):
        """特定チェックポイントへのロールバックと中間ファイル削除を検証"""
        # verifies: REQ-CHK-03
        checkpoint_mgr = WorkflowCheckpoint(checkpoint_dir=str(tmp_path))
        dag = TaskDAG()
        dag.add_task("task1", {"id": "task1", "status": "pass"})
        
        # 初期状態保存
        cp_id = checkpoint_mgr.save("wf_rollback", dag, {"step": 1})
        
        # 中間成果物ファイルを作成
        temp_video = tmp_path / "temp_video.mp4"
        temp_video.write_text("dummy video content")
        assert temp_video.exists()
        
        # 状態変更
        dag.tasks["task1"]["status"] = "fail"
        checkpoint_mgr.save("wf_rollback", dag, {"step": 2})
        
        # ロールバック実行（中間ファイル削除付き）
        rolled_dag, rolled_ctx = checkpoint_mgr.rollback(
            workflow_id="wf_rollback",
            target_checkpoint_id=cp_id,
            clean_files=[str(temp_video)]
        )
        
        # 状態が復元され、ファイルが削除されていることを確認
        assert rolled_dag.tasks["task1"]["status"] == "pass"
        assert rolled_ctx["step"] == 1
        assert not temp_video.exists()


# =====================================================================
# 3. WorkflowPlanner のテスト
# =====================================================================

class TestWorkflowPlanner:
    """WorkflowPlannerの計画生成、動的リプラン、および閉路検出検証"""

    def test_dynamic_dag_generation(self):
        """目標リストからの適正な初期DAG生成を検証"""
        # verifies: REQ-DAG-06
        decomposer = DynamicDecomposer()
        planner = WorkflowPlanner(decomposer=decomposer)
        
        goals = [
            {"id": "G1", "dependencies": []},
            {"id": "G2", "dependencies": ["T-G1"]},
        ]
        
        dag = planner.generate_initial_plan(goals)
        assert dag is not None
        assert "T-G1" in dag.tasks
        assert "T-G2" in dag.tasks
        assert "T-G1" in dag.dependencies["T-G2"]

    def test_dynamic_replanning_on_error(self):
        """エラー検知時における代替修復タスクの動的挿入を検証"""
        # verifies: REQ-DAG-07
        decomposer = DynamicDecomposer()
        planner = WorkflowPlanner(decomposer=decomposer)
        
        dag = TaskDAG()
        dag.add_task("T-G1", {"id": "T-G1", "status": "pending"})
        dag.add_task("T-G2", {"id": "T-G2", "status": "pending"}, dependencies=["T-G1"])
        
        error_report = {"error": "Timeout connection"}
        
        # T-G1でエラー発生しリプラン
        new_dag = planner.replan_on_failure(dag, "T-G1", error_report)
        
        # T-G1 のステータスは failed_replanned に変化していること
        assert new_dag.tasks["T-G1"]["status"] == "failed_replanned"
        
        # 修復タスク T-replan-T-G1-000 が挿入されていること
        replan_task_id = "T-replan-T-G1-000"
        assert replan_task_id in new_dag.tasks
        
        # T-replan-T-G1-000 は T-G1 に依存し、かつ T-G2 は T-replan-T-G1-000 に依存するように変更されていること
        assert "T-G1" in new_dag.dependencies[replan_task_id]
        assert replan_task_id in new_dag.dependencies["T-G2"]
        assert "T-G1" not in new_dag.dependencies["T-G2"] # 直接の依存は解除される

    def test_circular_dependency_detection(self):
        """動的リプランによる循環参照発生時の検知と適用遮断を検証"""
        # verifies: REQ-DAG-08
        decomposer = DynamicDecomposer()
        planner = WorkflowPlanner(decomposer=decomposer)
        
        dag = TaskDAG()
        dag.add_task("T-G1", {"id": "T-G1", "status": "pending"})
        dag.add_task("T-G2", {"id": "T-G2", "status": "pending"}, dependencies=["T-G1"])
        
        # リプラン時に、T-G1 が間接的に自分自身（T-G1）を依存先とするような循環を発生させるダミー修復タスク分析をモック
        def mock_remediation(error_report):
            return [{"target_module": "t1.py", "instruction": "mock"}]
            
        with patch.object(planner, "_analyze_remediation_needs", side_effect=mock_remediation):
            # 閉路を誘発させるため、下流のT-G2を一時的にT-G1の依存元とし、さらにT-G1がT-G2依存になるよう細工
            # T-G2 が T-G1 に依存し、修復タスクを介して循環参照が発生するケースをシミュレート
            # replan_on_failure 内部で dependencies の循環が発生すると CircularDependencyError になる
            with patch.object(TaskDAG, "has_cycle", return_value=True):
                with pytest.raises(CircularDependencyError, match="circular reference detected"):
                    planner.replan_on_failure(dag, "T-G1", {"error": "dummy"})
                    
                # 失敗した場合、元の依存関係が復元されていること
                assert "T-G1" in dag.dependencies["T-G2"]
                assert "T-replan-T-G1-000" not in dag.tasks

    def test_list_checkpoints_exception_handling(self, tmp_path):
        """list_checkpoints において、破損したJSON、キー欠損、アクセスエラー等の例外が発生しても、
        エラーが伝播せずに対象ファイルをスキップして正常に処理が継続されることを検証"""
        checkpoint_mgr = WorkflowCheckpoint(checkpoint_dir=str(tmp_path))
        dag = TaskDAG()
        dag.add_task("task1", {"id": "task1", "status": "pass"})
        
        # 1. 正常なチェックポイントを作成
        cp_id_normal = checkpoint_mgr.save("wf_list_test", dag, {"status": "running", "progress_pct": 50})
        
        # 2. 破損したJSONファイルを配置
        bad_json_path = tmp_path / "cp_wf_list_test_badjson.json"
        bad_json_path.write_text("{invalid json}", encoding="utf-8")
        
        # 3. 必要なキーが欠損したJSONファイルを配置
        missing_keys_path = tmp_path / "cp_wf_list_test_missingkeys.json"
        missing_keys_path.write_text(json.dumps({
            # checkpoint_id と timestamp が欠損
            "workflow_id": "wf_list_test",
            "context": {"status": "running"}
        }), encoding="utf-8")

        # 4. context が辞書ではなく不正な型のJSONファイルを配置
        bad_context_path = tmp_path / "cp_wf_list_test_badcontext.json"
        bad_context_path.write_text(json.dumps({
            "checkpoint_id": "cp_wf_list_test_badcontext",
            "timestamp": "2026-06-14T12:00:00Z",
            "workflow_id": "wf_list_test",
            "context": "not_a_dict"  # .get() で AttributeError や TypeError が発生しうる
        }), encoding="utf-8")
        
        # 5. list_checkpoints を実行
        results = checkpoint_mgr.list_checkpoints("wf_list_test")
        
        # 正常なものだけが1件リストアップされていることを検証
        assert len(results) == 1
        assert results[0]["checkpoint_id"] == cp_id_normal
        assert results[0]["status"] == "running"
        assert results[0]["progress"] == 50

    def test_replan_non_existent_task(self):
        """存在しないタスクIDを指定した場合の早期リターン検証"""
        decomposer = DynamicDecomposer()
        planner = WorkflowPlanner(decomposer=decomposer)
        dag = TaskDAG()
        dag.add_task("T-G1", {"id": "T-G1", "status": "pending"})
        
        # 存在しないタスクIDを指定して実行
        result_dag = planner.replan_on_failure(dag, "NON_EXISTENT_TASK", {})
        assert result_dag is dag

    def test_replan_no_remediation_plans(self):
        """修復プランが空の場合の ValueError 例外発生検証"""
        decomposer = DynamicDecomposer()
        planner = WorkflowPlanner(decomposer=decomposer)
        dag = TaskDAG()
        dag.add_task("T-G1", {"id": "T-G1", "status": "pending"})
        
        # remediation_plansが空のリストを返すようにモック
        with patch.object(planner, "_analyze_remediation_needs", return_value=[]):
            with pytest.raises(ValueError, match="No viable remediation path for task T-G1"):
                planner.replan_on_failure(dag, "T-G1", {})

    def test_circular_dependency_on_connection(self):
        """閉路検出時の CircularDependencyError スロー検証"""
        decomposer = DynamicDecomposer()
        planner = WorkflowPlanner(decomposer=decomposer)
        dag = TaskDAG()
        dag.add_task("T-G1", {"id": "T-G1", "status": "pending"})
        
        # TaskDAG.has_cycle を side_effect=[False, True] にモックし、
        # add_task 時（1回目）は False を返し、最後の dag.has_cycle() で True を返すように制御
        with patch.object(TaskDAG, "has_cycle", side_effect=[False, True]):
            with pytest.raises(CircularDependencyError, match="Dynamic replanning introduced circular dependencies"):
                planner.replan_on_failure(dag, "T-G1", {"error": "connection error"})

    def test_analyze_remediation_attribute_and_import_error(self):
        """AttributeError / ImportError 時のメッセージ生成検証"""
        decomposer = DynamicDecomposer()
        planner = WorkflowPlanner(decomposer=decomposer)
        
        # AttributeError の検証
        plans = planner._analyze_remediation_needs({"error": "AttributeError: module has no attribute"})
        assert len(plans) == 1
        assert "属性エラーまたはインポートエラー" in plans[0]["instruction"]
        
        # ImportError の検証
        plans_import = planner._analyze_remediation_needs({"error": "ImportError: cannot import name"})
        assert len(plans_import) == 1
        assert "属性エラーまたはインポートエラー" in plans_import[0]["instruction"]

    def test_invalid_inputs_handling(self):
        """不正な入力タイプに対する堅牢なエラーハンドリング検証"""
        decomposer = DynamicDecomposer()
        planner = WorkflowPlanner(decomposer=decomposer)
        
        # generate_initial_plan で goal が辞書でない場合、および id が欠損している場合のスキップ検証
        goals = [
            "not_a_dict",  # スキップされるべき
            {"no_id_key": "some_value"},  # スキップされるべき
            {"id": "G1", "dependencies": []}  # 正常に追加されるべき
        ]
        dag = planner.generate_initial_plan(goals)
        assert "T-G1" in dag.tasks
        assert len(dag.tasks) == 1

        # replan_on_failure で error_report が dict ではない場合のフォールバック検証
        dag_replan = TaskDAG()
        dag_replan.add_task("T-G1", {"id": "T-G1", "status": "pending"})
        # error_report に文字列を渡してもクラッシュせずデフォルトで処理されること
        result_dag = planner.replan_on_failure(dag_replan, "T-G1", "not_a_dict_error")
        assert result_dag.tasks["T-G1"]["status"] == "failed_replanned"
        assert "T-replan-T-G1-000" in result_dag.tasks

    def test_analyze_remediation_needs_invalid_inputs(self):
        """_analyze_remediation_needs における不正な入力タイプのカバーテスト"""
        decomposer = DynamicDecomposer()
        planner = WorkflowPlanner(decomposer=decomposer)
        
        # 1. error_report が辞書ではない場合（L134のカバー）
        plans_non_dict = planner._analyze_remediation_needs("not_a_dict")
        assert len(plans_non_dict) == 1
        assert "タスクがリトライ上限に達してもテスト合格しませんでした" in plans_non_dict[0]["instruction"]
        
        # 2. error_msg が文字列ではない場合（L137のカバー）
        plans_non_str = planner._analyze_remediation_needs({"error": 404})
        assert len(plans_non_str) == 1
        assert "タスクがリトライ上限に達してもテスト合格しませんでした" in plans_non_str[0]["instruction"]
