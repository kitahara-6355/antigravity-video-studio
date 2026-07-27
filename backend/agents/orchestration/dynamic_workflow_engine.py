# satisfies: REQ-WAVE-06, REQ-WAVE-07, REQ-CONV-07
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Callable, Awaitable
from agents.orchestration.task_dag import TaskDAG
from agents.orchestration.wave_scheduler import WaveScheduler
from agents.orchestration.workflow_checkpoint import WorkflowCheckpoint
from agents.orchestration.workflow_planner import WorkflowPlanner, CircularDependencyError
from agents.orchestration.convergence_loop import ConvergenceLoop

logger = logging.getLogger(__name__)

class DynamicWorkflowEngine:
    """DAGに基づき、並列ウェーブ実行、リソース制限、リトライ、動的リプラン、一時停止・再開を制御するエンジン。
    
    # satisfies: REQ-WAVE-06
    """
    def __init__(
        self,
        workflow_id: str,
        checkpoint_manager: WorkflowCheckpoint,
        planner: WorkflowPlanner,
        wave_size: int = 15,
        max_retries: int = 3,
        orchestrator_hub: Optional[Any] = None
    ) -> None:
        """
        Args:
            workflow_id: ワークフローの一意のID
            checkpoint_manager: 状態保存用管理クラス
            planner: プラン生成およびリプラン用プランナークラス
            wave_size: 同時実行数制限（ウェーブサイズ）
            max_retries: 1タスクあたりの最大リトライ数
            orchestrator_hub: OrchestrationHubへの参照
        """
        self.workflow_id = workflow_id
        self.checkpoint_manager = checkpoint_manager
        self.planner = planner
        self.wave_size = wave_size
        self.max_retries = max_retries
        self.hub = orchestrator_hub
        self.dag: Optional[TaskDAG] = None
        self.context: Dict[str, Any] = {}
        self.is_paused: bool = False
        
        # テストや実行時にタスク処理を差し替えるためのワーカー関数フック
        self.worker_func: Optional[Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]] = None

    def initialize_workflow(self, goals: List[Dict[str, Any]]) -> None:
        """初期の目標リストからDAGを構築し、初期チェックポイントを保存する"""
        self.dag = self.planner.generate_initial_plan(goals)
        self.context = {
            "workflow_id": self.workflow_id,
            "goals": goals,
            "status": "initialized",
            "progress_pct": 0,
            "execution_history": []
        }
        self.checkpoint_manager.save(self.workflow_id, self.dag, self.context)
        logger.info(f"Initialized workflow {self.workflow_id} with {len(self.dag.tasks)} tasks.")

    async def start(self) -> bool:
        """ワークフローの並列実行ループを開始する。
        
        # satisfies: REQ-WAVE-06
        """
        if not self.dag:
            raise ValueError("Workflow has not been initialized.")
            
        self.context["status"] = "running"
        self.checkpoint_manager.save(self.workflow_id, self.dag, self.context)
        
        # 並列スロットリング用の非同期セマフォ
        # satisfies: REQ-WAVE-07
        semaphore = asyncio.Semaphore(self.wave_size)
        
        while not self.dag.is_complete():
            if self.is_paused:
                self.context["status"] = "paused"
                self.checkpoint_manager.save(self.workflow_id, self.dag, self.context)
                logger.info(f"Workflow {self.workflow_id} suspended.")
                return True

            executable = self.dag.get_executable_tasks()
            if not executable:
                # 実行中のタスクがあるかチェック
                running_tasks = [t for t in self.dag.tasks.values() if t.get("status") == "running"]
                if not running_tasks:
                    # 未完了タスクがあるにも関わらず実行可能も実行中もなければ、デッドロック/異常終了
                    self.context["status"] = "stalled"
                    self.checkpoint_manager.save(self.workflow_id, self.dag, self.context)
                    logger.error("Workflow stalled: no ready tasks and no running tasks.")
                    return False
                # 待機
                await asyncio.sleep(0.1)
                continue

            # ウェーブスケジュールによる順序制御
            scheduler = WaveScheduler(default_wave_size=self.wave_size)
            waves = scheduler.schedule_waves(executable, wave_size=self.wave_size)
            
            # 第一ウェーブを実行
            current_wave = waves[0]
            await self._execute_wave(current_wave, semaphore)
            
            # 定期チェックポイントの保存
            self._update_progress()
            self.checkpoint_manager.save(self.workflow_id, self.dag, self.context)
            
        self.context["status"] = "completed"
        self.checkpoint_manager.save(self.workflow_id, self.dag, self.context)
        logger.info(f"Workflow {self.workflow_id} completed successfully.")
        return True

    def pause(self) -> None:
        """ワークフローの実行を一時停止（サスペンド）する"""
        self.is_paused = True

    async def resume(self) -> bool:
        """最新チェックポイントから状態をロードして実行を再開する"""
        self.is_paused = False
        latest_cp_id = f"cp_latest_{self.workflow_id}"
        try:
            self.dag, self.context = self.checkpoint_manager.load(latest_cp_id)
            # クラッシュまたは停止時にrunningだったタスクはpendingに戻す
            for task in self.dag.tasks.values():
                if task.get("status") == "running":
                    task["status"] = "pending"
            logger.info(f"Resumed workflow {self.workflow_id} from checkpoint.")
            return await self.start()
        except Exception as e:
            logger.error(f"Failed to resume workflow {self.workflow_id}: {e}")
            return False

    async def rollback(self, target_checkpoint_id: str, clean_files: Optional[List[str]] = None) -> bool:
        """指定したチェックポイントまで状態をロールバックする"""
        try:
            self.dag, self.context = self.checkpoint_manager.rollback(self.workflow_id, target_checkpoint_id, clean_files)
            logger.info(f"Rolled back workflow {self.workflow_id} to checkpoint {target_checkpoint_id}.")
            return True
        except Exception as e:
            logger.error(f"Failed to rollback workflow {self.workflow_id}: {e}")
            return False

    async def _execute_wave(self, wave: List[Dict[str, Any]], semaphore: asyncio.Semaphore) -> None:
        """ウェーブ内のタスクをセマフォ制限下で並列に実行する。
        
        # satisfies: REQ-WAVE-07
        """
        async def run_with_semaphore(task: Dict[str, Any]):
            async with semaphore:
                # 重複実行の防止
                if self.dag.tasks[task["id"]]["status"] != "pending":
                    return
                self.dag.mark_task_status(task["id"], "running")
                task["started_at"] = datetime.now(timezone.utc).isoformat()
                
                try:
                    if self.worker_func:
                        result = await self.worker_func(task)
                        success = result.get("success", False)
                        report = result.get("report", {})
                    else:
                        # デフォルトのダミー成功
                        success = True
                        report = {"message": "Dummy success"}
                        
                    await self._handle_task_result(task["id"], success, report)
                except Exception as e:
                    logger.error(f"Exception during execution of task {task['id']}: {e}")
                    await self._handle_task_result(task["id"], False, {"error": str(e)})

        # ウェーブ内のタスクを並列スケジュール
        tasks = [asyncio.create_task(run_with_semaphore(t)) for t in wave]
        await asyncio.gather(*tasks)

    async def _handle_task_result(self, task_id: str, success: bool, report: Dict[str, Any]) -> None:
        """個別のタスク実行結果を処理する"""
        if success:
            self.dag.mark_task_status(task_id, "pass")
            if self.hub:
                # OrchestrationHub を介してタスクを完了にマーク
                try:
                    self.hub.mark_task_done(task_id, "pass", report)
                except Exception:
                    pass
        else:
            await self._handle_task_failure(task_id, report)

    async def _handle_task_failure(self, task_id: str, error_report: Dict[str, Any]) -> None:
        """タスク失敗時のリトライ、カスケードスキップ、および動的リプラン処理。
        
        # satisfies: REQ-CONV-07
        """
        task = self.dag.tasks.get(task_id)
        if not task:
            return
            
        conv_loop = ConvergenceLoop(max_retries=self.max_retries)
        decision = conv_loop.should_retry(task, error_report)
        
        if decision["retry"]:
            # リトライ試行
            conv_loop.prepare_retry(task_id, decision["feedback_prompt"])
            # DAG内部状態の更新
            task["status"] = "pending"
            task["retry_count"] = decision["retry_count"] + 1
            conv_loop.record_retry_event(task_id, task["retry_count"], "retry_fail", error_report.get("error", ""))
            logger.info(f"Retrying task {task_id} (attempt {task['retry_count']}/{self.max_retries})")
        else:
            # リトライ回数上限超過 -> プランナーによる動的リプランをトリガー
            conv_loop.record_retry_event(task_id, task.get("retry_count", 0), "retry_exhausted", error_report.get("error", ""))
            
            try:
                # プランナーによる動的リプラン (代替DAGの差し替え)
                new_dag = self.planner.replan_on_failure(self.dag, task_id, error_report)
                self.dag = new_dag
                logger.info(f"Dynamic replanning successfully applied for failed task {task_id}")
            except CircularDependencyError as e:
                # 循環参照が検出された、または代替プランがない場合
                # カスケード失敗（下流タスクをすべてスキップ）をトリガーする
                logger.warning(f"Replanning rejected due to cycle or no path. Cascading failure from {task_id}: {e}")
                self.dag.mark_task_status(task_id, "failed")
                
                # 下流の依存関係タスクは自動的に skipped に遷移 (TaskDAG._cascade_failure)
                if self.hub:
                    try:
                        self.hub.flash_report_error(f"Workflow task {task_id} failed permanently. Cascaded downstream.")
                    except Exception:
                        pass

    def _update_progress(self) -> None:
        """進捗割合の計算と更新"""
        if not self.dag:
            return
        total = len(self.dag.tasks)
        if total == 0:
            return
        completed = sum(1 for t in self.dag.tasks.values() if t.get("status") in ("pass", "failed", "failed_replanned", "skipped"))
        self.context["progress_pct"] = int((completed / total) * 100)
