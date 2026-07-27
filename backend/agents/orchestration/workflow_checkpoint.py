# satisfies: REQ-CHK-01, REQ-CHK-02, REQ-CHK-03
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional
from agents.orchestration.task_dag import TaskDAG

logger = logging.getLogger(__name__)

def _now_iso() -> str:
    """現在時刻をISO 8601形式で返す"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _write_json_atomic(path: Path, data: dict) -> None:
    """JSONファイルをUTF-8かつアトミックに書き込む（ファイルI/O安全規約に準拠）"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f".tmp-{uuid.uuid4().hex}")
    try:
        with open(temp_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        temp_path.replace(path)
    except OSError as e:
        logger.error(f"Failed to write json atomically to {path}: {e}")
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise e

class WorkflowCheckpoint:
    """ワークフロー状態の永続化、ロールバック、および再開（Resume）を管理するクラス。
    
    # satisfies: REQ-CHK-01
    """
    def __init__(self, checkpoint_dir: Optional[str] = None) -> None:
        """
        Args:
            checkpoint_dir: チェックポイントファイルを保存するディレクトリ
        """
        self.checkpoint_dir = Path(checkpoint_dir) if checkpoint_dir else Path(__file__).resolve().parent / "checkpoints"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def save(self, workflow_id: str, dag: TaskDAG, context: Dict[str, Any]) -> str:
        """現在のDAG構造、各タスクステータス、およびコンテキストをJSONとして永続化する。
        
        # satisfies: REQ-CHK-01
        """
        checkpoint_id = f"cp_{workflow_id}_{uuid.uuid4().hex[:8]}"
        
        # set型オブジェクトをJSONシリアライズ可能にするためlistに変換
        serialized_dag = {
            "tasks": dag.tasks,
            "dependencies": {k: list(v) for k, v in dag.dependencies.items()},
            "dependents": {k: list(v) for k, v in dag.dependents.items()}
        }
        
        checkpoint_data = {
            "checkpoint_id": checkpoint_id,
            "workflow_id": workflow_id,
            "timestamp": _now_iso(),
            "context": context,
            "dag": serialized_dag
        }
        
        # 個別チェックポイントの保存
        cp_path = self.checkpoint_dir / f"{checkpoint_id}.json"
        _write_json_atomic(cp_path, checkpoint_data)
        
        # 最新チェックポイントへのリンク（上書きコピー）
        latest_path = self.checkpoint_dir / f"cp_latest_{workflow_id}.json"
        _write_json_atomic(latest_path, checkpoint_data)
        
        logger.info(f"Saved checkpoint: {checkpoint_id} (workflow={workflow_id})")
        return checkpoint_id

    def load(self, checkpoint_id: str) -> Tuple[TaskDAG, Dict[str, Any]]:
        """指定したチェックポイントから DAG とコンテキストを復元する。
        
        # satisfies: REQ-CHK-02
        """
        cp_path = self.checkpoint_dir / f"{checkpoint_id}.json"
        if not cp_path.exists():
            raise FileNotFoundError(f"Checkpoint file not found: {cp_path}")
            
        try:
            with open(cp_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to read checkpoint {checkpoint_id}: {e}")
            raise e
            
        # TaskDAGの再構築
        dag = TaskDAG()
        dag.tasks = data["dag"]["tasks"]
        dag.dependencies = {k: set(v) for k, v in data["dag"]["dependencies"].items()}
        dag.dependents = {k: set(v) for k, v in data["dag"]["dependents"].items()}
        
        return dag, data["context"]

    def rollback(self, workflow_id: str, target_checkpoint_id: str, clean_files: Optional[List[str]] = None) -> Tuple[TaskDAG, Dict[str, Any]]:
        """特定のチェックポイントまで状態をロールバックし、指定された中間生成物を削除する。
        
        # satisfies: REQ-CHK-03
        """
        dag, context = self.load(target_checkpoint_id)
        
        # 中間成果物等のクリーンアップ処理
        if clean_files:
            for filepath in clean_files:
                p = Path(filepath)
                if p.exists():
                    try:
                        p.unlink()
                        logger.info(f"Cleaned up intermediate file on rollback: {filepath}")
                    except OSError as e:
                        logger.warning(f"Failed to remove intermediate file {filepath} on rollback: {e}")
                        
        # 履歴の記録
        if "execution_history" not in context:
            context["execution_history"] = []
            
        context["execution_history"].append({
            "event": "rolled_back",
            "from_timestamp": _now_iso(),
            "target_checkpoint": target_checkpoint_id
        })
        
        # ロールバック後の状態を最新チェックポイントとして保存
        self.save(workflow_id, dag, context)
        logger.info(f"Rolled back workflow {workflow_id} to checkpoint {target_checkpoint_id}")
        return dag, context

    def list_checkpoints(self, workflow_id: str) -> List[Dict[str, Any]]:
        """特定のワークフローIDに属するチェックポイント一覧を取得する"""
        results = []
        if not self.checkpoint_dir.exists():
            return results
            
        for file in self.checkpoint_dir.glob(f"cp_{workflow_id}_*.json"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    results.append({
                        "checkpoint_id": data["checkpoint_id"],
                        "timestamp": data["timestamp"],
                        "status": data["context"].get("status"),
                        "progress": data["context"].get("progress_pct", 0)
                    })
            except (json.JSONDecodeError, OSError, KeyError, TypeError, AttributeError) as e:
                logger.warning(f"Skipping invalid checkpoint file {file}: {e}")
                continue
        return sorted(results, key=lambda x: x["timestamp"], reverse=True)
