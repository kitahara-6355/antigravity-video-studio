"""
Task Store - タスク状態管理モジュール
Phase 18+ Architecture: 両憲法準拠プラン

既存資産:
- redis_config.py の StateStore を活用
- websocket_handler.py の ProgressBroadcaster と連携

技術憲法準拠:
- 5.1 自律回復: プロセス再起動耐性
- 5.2 魂の継承: evolution_log への自動記録
- 10.1 記録 of 義務: 全タスク状態を永続化
"""

import time
import uuid
import logging
import asyncio
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum, StrEnum

from redis_config import StateStore, get_redis

try:
    import redis
    redis_exceptions = (redis.exceptions.RedisError,)
except ImportError:
    redis_exceptions = ()

logger = logging.getLogger(__name__)


def _fire_and_forget(coro):
    """同期コンテキストから非同期コルーチンをバックグラウンド実行する（警告防止付き）"""
    loop = None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        pass

    if loop and loop.is_running() and not loop.is_closed():
        try:
            import threading
            if threading.current_thread() is threading.main_thread():
                loop.create_task(coro)
            else:
                asyncio.run_coroutine_threadsafe(coro, loop)
            return
        except (RuntimeError, TypeError, ValueError):
            try:
                loop.create_task(coro)
                return
            except (RuntimeError, TypeError):
                pass
    
    # イベントループが実行中でない場合は、coroutineをクローズしてRuntimeWarningを防止する
    try:
        coro.close()
    except (RuntimeError, AttributeError):
        pass


class TaskStatus(StrEnum):
    """タスク状態"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPhase(StrEnum):
    """処理フェーズ"""
    WAITING = "waiting"
    MODEL_LOADING = "model_loading"
    TRANSCRIBING = "transcribing"
    PROOFREADING = "proofreading"
    SAVING = "saving"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class TaskState:
    """タスク状態モデル"""
    task_id: str
    video_path: str
    status: str = TaskStatus.PENDING.value
    phase: str = TaskPhase.WAITING.value
    progress: int = 0
    message: str = "待機中..."
    
    # 詳細情報
    current_segment: Optional[int] = None
    total_segments: Optional[int] = None
    eta_seconds: Optional[int] = None
    
    # タイムスタンプ
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    
    # 結果
    result_path: Optional[str] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskState":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class TaskStore:
    """
    タスク状態管理ストア
    
    Features:
    - StateStore (Redis/FallbackCache) による永続化
    - WebSocket (ProgressBroadcaster) との連携
    - evolution_log への自動記録
    """
    
    TTL_SECONDS = 86400  # 24時間保持
    
    def __init__(self, prefix: str = "transcribe_task"):
        self._store = StateStore(prefix)
        self._broadcaster = None  # 遅延初期化
    
    def _get_broadcaster(self):
        """ProgressBroadcaster の遅延取得"""
        if self._broadcaster is None:
            try:
                from websocket_handler import progress_manager, ProgressBroadcaster
                self._broadcaster = ProgressBroadcaster(progress_manager)
            except ImportError:
                logger.warning("ProgressBroadcaster not available")
        return self._broadcaster
    
    def create_task(self, video_path: str, task_id: str = None) -> TaskState:
        """
        新規タスク作成
        
        Args:
            video_path: 動画ファイルパス
            task_id: タスクID（省略時は自動生成）
        
        Returns:
            TaskState: 作成されたタスク状態
        """
        if task_id is None:
            task_id = str(uuid.uuid4())
        
        task = TaskState(
            task_id=task_id,
            video_path=video_path
        )
        
        self._save(task)
        logger.info(f"Task created: {task_id}")
        
        return task
    
    def get_task(self, task_id: str) -> Optional[TaskState]:
        """タスク状態を取得"""
        data = self._store.get(task_id)
        if data is None:
            return None
        return TaskState.from_dict(data)
    
    def update_progress(
        self,
        task_id: str,
        phase: TaskPhase,
        progress: int,
        message: str = None,
        current_segment: int = None,
        total_segments: int = None,
        eta_seconds: int = None
    ) -> Optional[TaskState]:
        """
        進捗更新（StateStore + WebSocket 二重化）
        
        技術憲法 9.2 準拠: フェーズごとの進捗通知
        """
        task = self.get_task(task_id)
        if task is None:
            logger.warning(f"Task not found: {task_id}")
            return None
        
        # 状態更新
        task.status = TaskStatus.RUNNING.value
        task.phase = phase.value
        task.progress = progress
        if message:
            task.message = message
        if current_segment is not None:
            task.current_segment = current_segment
        if total_segments is not None:
            task.total_segments = total_segments
        if eta_seconds is not None:
            task.eta_seconds = eta_seconds
        
        if task.started_at is None:
            task.started_at = time.time()
        
        # StateStore に保存
        self._save(task)
        
        # WebSocket でブロードキャスト
        broadcaster = self._get_broadcaster()
        if broadcaster:
            try:
                _fire_and_forget(
                    broadcaster.update_phase(
                        phase=phase.value,
                        progress=progress,
                        step=message or f"{phase.value}...",
                        eta=eta_seconds
                    )
                )
            except (AttributeError, RuntimeError, TypeError, ValueError, ConnectionError, OSError) as e:
                logger.error(f"WebSocket broadcast failed: {e}", exc_info=True)
        
        return task
    
    def complete_task(
        self,
        task_id: str,
        result_path: str = None
    ) -> Optional[TaskState]:
        """
        タスク完了
        
        技術憲法 5.2 / 12.5 準拠: evolution_log への自動記録
        """
        task = self.get_task(task_id)
        if task is None:
            return None
        
        task.status = TaskStatus.COMPLETED.value
        task.phase = TaskPhase.COMPLETE.value
        task.progress = 100
        task.message = "完了"
        task.completed_at = time.time()
        task.result_path = result_path
        
        self._save(task)
        
        # WebSocket で完了通知
        broadcaster = self._get_broadcaster()
        if broadcaster:
            try:
                _fire_and_forget(
                    broadcaster.send_completion({
                        "task_id": task_id,
                        "result_path": result_path,
                        "duration": task.completed_at - (task.started_at or task.created_at)
                    })
                )
            except (AttributeError, RuntimeError, TypeError, ValueError, ConnectionError, OSError) as e:
                logger.error(f"WebSocket completion broadcast failed: {e}", exc_info=True)
        
        # evolution_log に記録
        self._record_to_evolution_log(task)
        
        logger.info(f"Task completed: {task_id}")
        return task
    
    def fail_task(self, task_id: str, error: str) -> Optional[TaskState]:
        """タスク失敗"""
        task = self.get_task(task_id)
        if task is None:
            return None
        
        task.status = TaskStatus.FAILED.value
        task.phase = TaskPhase.ERROR.value
        task.message = f"エラー: {error[:100]}"
        task.error = error
        task.completed_at = time.time()
        
        self._save(task)
        
        # WebSocket でエラー通知
        broadcaster = self._get_broadcaster()
        if broadcaster:
            try:
                _fire_and_forget(broadcaster.send_error(error))
            except (AttributeError, RuntimeError, TypeError, ValueError, ConnectionError, OSError) as e:
                logger.error(f"WebSocket error broadcast failed: {e}", exc_info=True)
        
        # evolution_log に記録
        self._record_to_evolution_log(task)
        
        logger.error(f"Task failed: {task_id} - {error}")
        return task
    
    def cancel_task(self, task_id: str) -> Optional[TaskState]:
        """タスクキャンセル"""
        task = self.get_task(task_id)
        if task is None:
            return None
        
        task.status = TaskStatus.CANCELLED.value
        task.message = "キャンセルされました"
        task.completed_at = time.time()
        
        self._save(task)
        logger.info(f"Task cancelled: {task_id}")
        return task
    
    def list_tasks(self, status: TaskStatus = None) -> list:
        """タスク一覧取得"""
        # Note: Redis keys() を使用するため、多数 of タスクがある場合は非効率
        try:
            client = get_redis()
            keys = client.keys(f"{self._store.prefix}:*")
        except redis_exceptions + (AttributeError, TypeError) as e:
            logger.error(f"Failed to list tasks from Redis: {e}", exc_info=True)
            return []
        
        tasks = []
        for key in keys:
            task_id = key.split(":")[-1] if isinstance(key, str) else key.decode().split(":")[-1]
            task = self.get_task(task_id)
            if task:
                target_status = status.value if hasattr(status, "value") else status
                if status is None or task.status == target_status:
                    tasks.append(task.to_dict())
        
        return sorted(tasks, key=lambda x: x.get("created_at", 0), reverse=True)
    
    def _save(self, task: TaskState):
        """StateStore に保存"""
        self._store.set(task.task_id, task.to_dict(), ttl=self.TTL_SECONDS)
    
    def _record_to_evolution_log(self, task: TaskState):
        """
        evolution_log に処理記録を追加
        
        技術憲法 5.2 魂の継承: 重要な意思決定を記録
        技術憲法 12.5 進化の発動: 処理完了時に自動発動
        """
        try:
            from branding_manager import branding_manager
            
            duration = (task.completed_at or time.time()) - (task.started_at or task.created_at)
            
            if task.status == TaskStatus.FAILED.value:
                event = "TRANSCRIPTION_FAILED"
                proposal = f"字幕生成失敗: {task.video_path} - {task.error[:50] if task.error else ''}"
            else:
                event = "TRANSCRIPTION_COMPLETED"
                proposal = f"字幕生成完了: {task.video_path}"
            
            branding_manager.log_evolution({
                "event": event,
                "task_id": task.task_id,
                "video_path": task.video_path,
                "duration_seconds": round(duration, 1),
                "segments_count": task.total_segments,
                "result_path": task.result_path,
                "error": task.error,
                "agenda_proposal": proposal
            })
            
            logger.info(f"Recorded to evolution_log: {task.task_id}")
            
        except (ImportError, AttributeError, KeyError, TypeError, ValueError) as e:
            logger.error(f"Failed to record to evolution_log: {e}", exc_info=True)


# シングルトンインスタンス
task_store = TaskStore()


def create_progress_callback(task_id: str) -> Callable:
    """
    WhisperTranscriber 用の進捗コールバック生成
    
    Usage:
        callback = create_progress_callback(task_id)
        transcriber.transcribe_with_proofreading(video_path, progress_callback=callback)
    """
    def callback(status: str, message: str, progress: int):
        # ステータスからフェーズを判定
        msg_str = (message or "").lower()
        if "loading" in msg_str or "model" in msg_str:
            phase = TaskPhase.MODEL_LOADING
        elif "transcrib" in msg_str:
            phase = TaskPhase.TRANSCRIBING
        elif "proofread" in msg_str or "ai" in msg_str:
            phase = TaskPhase.PROOFREADING
        elif "complet" in msg_str or "success" in msg_str:
            phase = TaskPhase.COMPLETE
        else:
            phase = TaskPhase.TRANSCRIBING
        
        task_store.update_progress(
            task_id=task_id,
            phase=phase,
            progress=progress,
            message=message
        )
    
    return callback
