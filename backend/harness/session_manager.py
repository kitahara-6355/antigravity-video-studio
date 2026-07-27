"""
SessionManager — セッション持続性管理

Claude Agent SDK の Sessions / resume 機能の概念を
SDK非依存で再現。

機能:
  - パイプラインセッションの作成・管理・リジューム
  - 接続切断時にセッションIDで状態を復元
  - PipelineContext と セッション状態の双方向同期
  - セッション履歴のディスク永続化

設計思想:
  - Claude Agent SDK の session_id / resume パターン準拠
  - 既存の WebSocket ハンドラとの橋渡し
  - JSONLベースの軽量永続化（DBなし）
"""

import json
import logging
import uuid
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# セッションデータの保存先
SESSION_DIR = Path(__file__).parent.parent / "data" / "sessions"


# ============================================================
# データ構造
# ============================================================

@dataclass
class SessionState:
    """セッションの状態"""
    session_id: str
    created_at: str
    last_active_at: str
    status: str = "active"  # active, paused, completed, error
    # パイプラインコンテキスト
    video_path: Optional[str] = None
    current_stage: int = 0
    total_stages: int = 7
    quality_score: int = 0
    # ツール実行履歴（直近50件）
    tool_history: List[Dict] = field(default_factory=list)
    # カスタムデータ
    metadata: Dict[str, Any] = field(default_factory=dict)
    # スケジュール
    pipeline_started_at: Optional[str] = None
    pipeline_completed_at: Optional[str] = None


# ============================================================
# SessionManager
# ============================================================

class SessionManager:
    """
    セッション持続性管理。

    Claude Agent SDK の resume 機能に相当:
    - セッション作成時に session_id を発行
    - 接続切断時に session_id でリジューム
    - パイプライン進捗をセッション状態として永続化

    Usage:
        from harness.session_manager import session_manager

        # セッション作成
        session = session_manager.create_session(video_path="/path/to/video.mp4")

        # 進捗更新
        session_manager.update_stage(session.session_id, stage=2, detail="AI校閲完了")

        # リジューム（接続復旧時）
        session = session_manager.resume_session("session-id-here")
    """

    CLEANUP_DAYS = 30  # 古いセッションの自動削除日数
    MAX_TOOL_HISTORY = 50

    def __init__(self, session_dir: Optional[Path] = None):
        self._session_dir = session_dir or SESSION_DIR
        self._session_dir.mkdir(parents=True, exist_ok=True)
        self._active_sessions: Dict[str, SessionState] = {}

        # ディスクから既存セッションを復元
        self._load_active_sessions()

    # ============================================================
    # セッション作成
    # ============================================================

    def create_session(
        self,
        video_path: Optional[str] = None,
        metadata: Optional[Dict] = None,
        session_id: Optional[str] = None,
    ) -> SessionState:
        """
        新しいセッションを作成。

        Args:
            video_path: 処理対象の動画パス
            metadata: 追加メタデータ
            session_id: 明示的なセッションID（省略時は自動生成）

        Returns:
            SessionState
        """
        sid = session_id or str(uuid.uuid4())
        now = datetime.now().isoformat()

        session = SessionState(
            session_id=sid,
            created_at=now,
            last_active_at=now,
            video_path=video_path,
            metadata=metadata or {},
            pipeline_started_at=now,
        )

        self._active_sessions[sid] = session
        self._save_session(session)

        logger.info(f"📋 Session created: {sid[:8]}...")
        return session

    # ============================================================
    # セッション操作
    # ============================================================

    def get_session(self, session_id: str) -> Optional[SessionState]:
        """セッションを取得"""
        return self._active_sessions.get(session_id)

    def resume_session(self, session_id: str) -> Optional[SessionState]:
        """
        セッションをリジューム（Claude Agent SDK の resume 相当）。

        メモリ上にない場合はディスクから復元。
        """
        # メモリ上にある場合
        session = self._active_sessions.get(session_id)
        if session:
            session.last_active_at = datetime.now().isoformat()
            if session.status == "paused":
                session.status = "active"
            self._save_session(session)
            logger.info(f"▶️ Session resumed (memory): {session_id[:8]}...")
            return session

        # ディスクから復元
        session_path = self._session_dir / f"{session_id}.json"
        if session_path.exists():
            try:
                data = json.loads(session_path.read_text(encoding="utf-8"))
                session = SessionState(**data)
                session.last_active_at = datetime.now().isoformat()
                session.status = "active"
                self._active_sessions[session_id] = session
                self._save_session(session)
                logger.info(f"▶️ Session resumed (disk): {session_id[:8]}...")
                return session
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                logger.error(f"Session resume failed due to corrupted data: {e}", exc_info=True)
                try:
                    bad_path = session_path.with_suffix(".json.bad")
                    session_path.rename(bad_path)
                    logger.warning(f"Corrupted session file isolated to {bad_path.name}")
                except OSError as rename_err:
                    logger.error(f"Failed to isolate corrupted session file: {rename_err}", exc_info=True)
            except OSError as e:
                logger.error(f"Session resume failed due to I/O error: {e}", exc_info=True)

        return None

    def update_stage(
        self,
        session_id: str,
        stage: int,
        detail: str = "",
        data: Optional[Dict] = None,
    ) -> None:
        """パイプラインステージの進捗を更新"""
        session = self._active_sessions.get(session_id)
        if not session:
            return

        session.current_stage = stage
        session.last_active_at = datetime.now().isoformat()

        if data:
            session.metadata.update(data)

        # ツール履歴に記録
        session.tool_history.append({
            "stage": stage,
            "detail": detail,
            "timestamp": datetime.now().isoformat(),
            "data": data or {},
        })

        # 履歴の上限管理
        if len(session.tool_history) > self.MAX_TOOL_HISTORY:
            session.tool_history = session.tool_history[-self.MAX_TOOL_HISTORY:]

        self._save_session(session)

    def record_tool_call(
        self,
        session_id: str,
        tool_name: str,
        args: Dict,
        result: Any,
        duration_seconds: float,
        is_error: bool = False,
    ) -> None:
        """ツール呼び出しをセッションに記録"""
        session = self._active_sessions.get(session_id)
        if not session:
            return

        session.tool_history.append({
            "type": "tool_call",
            "tool_name": tool_name,
            "args_summary": {k: str(v)[:100] for k, v in args.items()},
            "is_error": is_error,
            "duration_s": round(duration_seconds, 2),
            "timestamp": datetime.now().isoformat(),
        })

        if len(session.tool_history) > self.MAX_TOOL_HISTORY:
            session.tool_history = session.tool_history[-self.MAX_TOOL_HISTORY:]

        session.last_active_at = datetime.now().isoformat()
        self._save_session(session)

    def complete_session(
        self,
        session_id: str,
        quality_score: int = 0,
        final_data: Optional[Dict] = None,
    ) -> None:
        """セッションを完了"""
        session = self._active_sessions.get(session_id)
        if not session:
            return

        session.status = "completed"
        session.quality_score = quality_score
        session.pipeline_completed_at = datetime.now().isoformat()
        if final_data:
            session.metadata.update(final_data)

        self._save_session(session)
        logger.info(
            f"✅ Session completed: {session_id[:8]}... "
            f"(quality={quality_score})"
        )

    def pause_session(self, session_id: str) -> None:
        """セッションを一時停止（接続切断時）"""
        session = self._active_sessions.get(session_id)
        if session:
            session.status = "paused"
            session.last_active_at = datetime.now().isoformat()
            self._save_session(session)
            logger.info(f"⏸️ Session paused: {session_id[:8]}...")

    def error_session(self, session_id: str, error: str) -> None:
        """セッションをエラー状態にする"""
        session = self._active_sessions.get(session_id)
        if session:
            session.status = "error"
            session.metadata["last_error"] = error
            session.last_active_at = datetime.now().isoformat()
            self._save_session(session)

    # ============================================================
    # セッション一覧・統計
    # ============================================================

    def list_sessions(
        self,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict]:
        """セッション一覧"""
        sessions = list(self._active_sessions.values())
        if status:
            sessions = [s for s in sessions if s.status == status]

        sessions.sort(key=lambda s: s.last_active_at, reverse=True)
        return [
            {
                "session_id": s.session_id,
                "status": s.status,
                "current_stage": s.current_stage,
                "total_stages": s.total_stages,
                "quality_score": s.quality_score,
                "video_path": s.video_path,
                "created_at": s.created_at,
                "last_active_at": s.last_active_at,
            }
            for s in sessions[:limit]
        ]

    def get_stats(self) -> Dict[str, Any]:
        """セッション統計"""
        sessions = list(self._active_sessions.values())
        return {
            "total": len(sessions),
            "active": len([s for s in sessions if s.status == "active"]),
            "paused": len([s for s in sessions if s.status == "paused"]),
            "completed": len([s for s in sessions if s.status == "completed"]),
            "error": len([s for s in sessions if s.status == "error"]),
        }

    # ============================================================
    # 永続化
    # ============================================================

    def _save_session(self, session: SessionState) -> bool:
        """
        セッションをディスクに保存。

        Returns:
            bool: 保存成功時は True、失敗時は False
        """
        try:
            path = self._session_dir / f"{session.session_id}.json"
            data = asdict(session)
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return True
        except (OSError, TypeError) as e:
            logger.error(f"Session save failed: {e}", exc_info=True)
            return False

    def _load_active_sessions(self) -> None:
        """ディスクから最近のセッションを復元"""
        cutoff = datetime.now() - timedelta(days=self.CLEANUP_DAYS)

        for session_file in self._session_dir.glob("*.json"):
            try:
                data = json.loads(session_file.read_text(encoding="utf-8"))
                last_active_str = data.get("last_active_at", "")
                if not last_active_str:
                    raise ValueError("last_active_at is missing or empty")
                last_active = datetime.fromisoformat(last_active_str)
                if last_active < cutoff:
                    session_file.unlink()  # 古いセッションを削除
                    continue

                session = SessionState(**data)
                # 前回実行中だったセッションは paused に
                if session.status == "active":
                    session.status = "paused"

                self._active_sessions[session.session_id] = session

            except (json.JSONDecodeError, TypeError, ValueError) as e:
                logger.error(f"Failed to load active session from {session_file} due to corrupted data: {e}", exc_info=True)
                try:
                    bad_path = session_file.with_suffix(".json.bad")
                    session_file.rename(bad_path)
                    logger.warning(f"Corrupted active session file isolated to {bad_path.name}")
                except OSError as rename_err:
                    logger.error(f"Failed to isolate corrupted active session file: {rename_err}", exc_info=True)
            except OSError as e:
                logger.error(f"Failed to load active session from {session_file} due to I/O error: {e}", exc_info=True)

        loaded = len(self._active_sessions)
        if loaded > 0:
            logger.info(f"📋 {loaded} sessions restored from disk")

    def cleanup_old_sessions(self) -> int:
        """古いセッションをクリーンアップ"""
        cutoff = datetime.now() - timedelta(days=self.CLEANUP_DAYS)
        removed = 0

        for session_file in self._session_dir.glob("*.json"):
            try:
                data = json.loads(session_file.read_text(encoding="utf-8"))
                last_active_str = data.get("last_active_at", "")
                if not last_active_str:
                    raise ValueError("last_active_at is missing or empty")
                last_active = datetime.fromisoformat(last_active_str)
                if last_active < cutoff:
                    sid = data.get("session_id", "")
                    self._active_sessions.pop(sid, None)
                    session_file.unlink()
                    removed += 1
            except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
                logger.error(f"Failed to cleanup session {session_file} due to corrupted data: {e}", exc_info=True)
                try:
                    bad_path = session_file.with_suffix(".json.bad")
                    session_file.rename(bad_path)
                    logger.warning(f"Corrupted old session file isolated to {bad_path.name}")
                except OSError as rename_err:
                    logger.error(f"Failed to isolate corrupted old session file: {rename_err}", exc_info=True)
            except OSError as e:
                logger.error(f"Failed to cleanup session {session_file} due to I/O error: {e}", exc_info=True)

        if removed > 0:
            logger.info(f"🧹 {removed} old sessions cleaned up")
        return removed


# ============================================================
# シングルトン
# ============================================================
session_manager = SessionManager()
