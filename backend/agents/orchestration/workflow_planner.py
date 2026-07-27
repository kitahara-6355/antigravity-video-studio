# satisfies: REQ-DAG-06, REQ-DAG-07, REQ-DAG-08
import logging
import copy
from typing import Dict, List, Any, Optional
from agents.orchestration.task_dag import TaskDAG
from agents.orchestration.dynamic_decomposer import DynamicDecomposer

logger = logging.getLogger(__name__)

class CircularDependencyError(ValueError):
    """動的リプラン時に循環参照（閉路）が検出された場合にスローされる例外。"""
    pass

class WorkflowPlanner:
    """初期計画の生成、およびエラー検出時の動的な計画変更（リプランニング）を担当するクラス。
    
    # satisfies: REQ-DAG-06
    """
    def __init__(self, decomposer: DynamicDecomposer, orchestrator_hub: Optional[Any] = None) -> None:
        """
        Args:
            decomposer: タスク分解器 (DynamicDecomposer) インスタンス
            orchestrator_hub: システム状態参照用の OrchestrationHub
        """
        self.decomposer = decomposer
        self.hub = orchestrator_hub

    def generate_initial_plan(self, goals: List[Dict[str, Any]]) -> TaskDAG:
        """与えられた目標リストからタスクリストを作成し、DynamicDecomposerを用いてDAGを構築する。
        
        # satisfies: REQ-DAG-06
        """
        tasks = []
        for goal in goals:
            if not isinstance(goal, dict) or "id" not in goal:
                logger.warning(f"Invalid goal encountered and skipped: {goal}")
                continue
            task = {
                "id": f"T-{goal['id']}",
                "target_module": goal.get("target_module"),
                "group": goal.get("group", "general"),
                "status": "pending",
                "dependencies": goal.get("dependencies", []),
                "instruction": goal.get("instruction", "Execute validation.")
            }
            tasks.append(task)
            
        dag = self.decomposer.build_dag_from_tasks(tasks)
        return dag

    def replan_on_failure(self, dag: TaskDAG, failed_task_id: str, error_report: Dict[str, Any]) -> TaskDAG:
        """タスク失敗（リトライ上限到達など）を検知した際、DAGに修復用タスクを挿入して動的に再構築する。
        
        # satisfies: REQ-DAG-07
        """
        if not isinstance(error_report, dict):
            logger.warning(f"Invalid error_report type: {type(error_report)}. Fallback to empty dict.")
            error_report = {}
            
        failed_task = dag.tasks.get(failed_task_id)
        if not failed_task:
            logger.warning(f"Task {failed_task_id} not found in DAG during replan. No-op.")
            return dag
            
        logger.info(f"Initiating dynamic replanning on task failure: {failed_task_id}")
        
        # トランザクションロールバックのためのディープコピー
        dag_backup = copy.deepcopy(dag)
        
        # 1. 原因分析と修復プランの策定
        remediation_plans = self._analyze_remediation_needs(error_report)
        if not remediation_plans:
            raise ValueError(f"No viable remediation path for task {failed_task_id}")
            
        # 2. 修復タスクの生成
        remediation_tasks = []
        for idx, plan in enumerate(remediation_plans):
            task_id = f"T-replan-{failed_task_id}-{idx:03d}"
            task_data = {
                "id": task_id,
                "target_module": plan.get("target_module", failed_task.get("target_module")),
                "group": "remediation",
                "status": "pending",
                "instruction": plan["instruction"],
                "retry_count": 0
            }
            remediation_tasks.append(task_data)

        # 3. 依存関係の付け替えと閉路検証
        # 失敗タスクの下流（dependent）タスクを退避
        downstream_ids = list(dag.dependents.get(failed_task_id, set()))
        
        # 失敗タスク自体を 'failed_replanned' 状態として終了扱いにする
        dag.tasks[failed_task_id]["status"] = "failed_replanned"

        # 閉路検証のため、一時的な追加テスト
        # satisfies: REQ-DAG-08
        try:
            # 3.1 修復タスクを追加
            prev_id = failed_task_id
            for rem_task in remediation_tasks:
                dag.add_task(rem_task["id"], rem_task, dependencies=[prev_id])
                prev_id = rem_task["id"]
                
            # 3.2 下流タスクの依存先を修復タスクの末尾に接続
            for down_id in downstream_ids:
                if failed_task_id in dag.dependencies[down_id]:
                    # 古い依存関係の解消
                    dag.dependencies[down_id].remove(failed_task_id)
                    if failed_task_id in dag.dependents:
                        dag.dependents[failed_task_id].discard(down_id)
                # 新しい依存関係の適用
                dag.dependencies[down_id].add(prev_id)
                dag.dependents[prev_id].add(down_id)

            # 3.3 閉路（循環参照）のチェック
            if dag.has_cycle():
                raise CircularDependencyError(f"Dynamic replanning introduced circular dependencies for task {failed_task_id}")
                
        except (ValueError, CircularDependencyError) as e:
            # ロールバック (バックアップから完全に復元)
            logger.error(f"Replanning rejected due to graph validation failure: {e}")
            dag.tasks = dag_backup.tasks
            dag.dependencies = dag_backup.dependencies
            dag.dependents = dag_backup.dependents
            raise CircularDependencyError(f"Replanning failed: circular reference detected. {e}")

        logger.info(f"Successfully replanned DAG for failure of task {failed_task_id}. Inserted remediation chain ending in {prev_id}")
        return dag

    def _analyze_remediation_needs(self, error_report: Dict[str, Any]) -> List[Dict[str, Any]]:
        """エラーログのパターンを解析し、具体的な修復タスク指示書を決定する"""
        if not isinstance(error_report, dict):
            error_report = {}
        error_msg = error_report.get("error", "")
        if not isinstance(error_msg, str):
            error_msg = str(error_msg)
        error_msg = error_msg.lower()
        
        plans = []
        if "connection" in error_msg or "timeout" in error_msg:
            plans.append({
                "target_module": "tests/mocks/mock_gateway.py",
                "instruction": "外部ネットワーク接続障害またはAPIタイムアウトを検知しました。該当モジュール境界にモックまたはスタブ環境を導入し、テストスイートのネットワーク依存を排除してください。"
            })
        elif "attributeerror" in error_msg or "importerror" in error_msg:
            plans.append({
                "instruction": "モジュールインポート時の属性エラーまたはインポートエラーを検知しました。対象APIのシグネチャ、型ヒント定義を確認し、インターフェースの整合性を確保してください。"
            })
        else:
            plans.append({
                "instruction": "タスクがリトライ上限に達してもテスト合格しませんでした。エラーログおよびスタックトレースを再度精読し、エッジケースまたはバグの原因を修正してください。"
            })
            
        return plans
