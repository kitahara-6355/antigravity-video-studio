"""
Orchestration Hub — Flashセッション管理 Mixin

Flashセッションのライフサイクル管理（開始・心拍・終了）、
リアルタイム活動ステータス更新、問題診断、改善指示送信を担当する。

orchestrator.py L1333-1667 から抽出。
"""

import json
import os
from datetime import datetime, timezone
from typing import Optional

from .hub_common import (
    logger, _read_json, _write_json, _now_iso, _safe_parse_iso,
    FLASH_SESSION_PATH, OPUS_DIRECTIVE_PATH, _BASE_DIR,
)
from .atomic_io import safe_read_json, atomic_write_json, FileLock


class SessionMixin:
    """Flashセッション管理のMixin"""

    def flash_session_start(self) -> None:
        """Flash側が自走ループ開始時に呼ぶ。セッション開始を記録する。"""
        lock_path = str(FLASH_SESSION_PATH) + ".lock"
        with FileLock(lock_path):
            session = {
                "session_started_at": _now_iso(),
                "session_ended_at": None,
                "exit_reason": None,
                "last_heartbeat": _now_iso(),
                "status": "running",
                "batches_in_session": 0,
                "tasks_completed_in_session": 0,
                # --- リアルタイム活動ステータス ---
                "current_activity": "initializing",
                "current_step": "Step 0: 初期化中",
                "current_batch_id": None,
                "current_task_group": None,
                "progress_pct": 0,
                "subagents_running": 0,
                "subagents_completed": 0,
                "recent_errors": [],
                "stall_count": 0,
                # --- コンテキスト・アーカイブ状態リセット ---
                "context_consumption_pct": 0,
                "context_pct_history": [],
                "archive_urgency": "ok",
                "auto_stop_reason": None,
            }
            atomic_write_json(str(FLASH_SESSION_PATH), session)

    def flash_update_status(self, activity: str, step: str,
                            batch_id: Optional[str] = None,
                            task_group: Optional[str] = None,
                            progress_pct: int = 0,
                            subagents_running: int = 0,
                            subagents_completed: int = 0) -> None:
        """
        Flash側が各処理ステップごとに呼ぶ。リアルタイム活動を記録する。
        
        Args:
            activity: 現在の活動種別（"dispatching", "executing", "quality_gate", "phase_gate", "waiting"等）
            step: 現在のステップ説明（"Step 1: バッチ生成中", "Step 2: 品質ゲート検証中"等）
            batch_id: 現在のバッチID
            task_group: 現在処理中のタスクグループ
            progress_pct: 現在バッチの進捗率（0-100）
            subagents_running: 稼働中のサブエージェント数
            subagents_completed: 完了済みサブエージェント数
        """
        lock_path = str(FLASH_SESSION_PATH) + ".lock"
        with FileLock(lock_path):
            session = safe_read_json(str(FLASH_SESSION_PATH), {})
            session["last_heartbeat"] = _now_iso()
            session["current_activity"] = activity
            session["current_step"] = step
            if batch_id is not None:
                session["current_batch_id"] = batch_id
            if task_group is not None:
                session["current_task_group"] = task_group
            session["progress_pct"] = progress_pct
            session["subagents_running"] = subagents_running
            session["subagents_completed"] = subagents_completed
            atomic_write_json(str(FLASH_SESSION_PATH), session)

    def flash_report_error(self, error_summary: str,
                           module: Optional[str] = None) -> None:
        """Flash側がエラー発生時に呼ぶ。直近エラーを記録する（最大10件保持）。"""
        lock_path = str(FLASH_SESSION_PATH) + ".lock"
        with FileLock(lock_path):
            session = safe_read_json(str(FLASH_SESSION_PATH), {})
            session["last_heartbeat"] = _now_iso()
            errors = session.get("recent_errors", [])
            errors.append({
                "timestamp": _now_iso(),
                "error": error_summary,
                "module": module,
            })
            session["recent_errors"] = errors[-10:]  # 最新10件のみ保持
            session["stall_count"] = session.get("stall_count", 0) + 1
            atomic_write_json(str(FLASH_SESSION_PATH), session)

    def flash_heartbeat(self) -> None:
        """Flash側が各バッチ完了時に呼ぶ。生存を通知する。
        
        Auto-recovery: auto_stopped状態の場合、心拍更新時に自動的にrunningへ復旧する。
        これにより、PCリソース逼迫でOpusに自動停止されても、Flash側が生き返った際に
        Hub連携が自動復旧する。
        """
        lock_path = str(FLASH_SESSION_PATH) + ".lock"
        with FileLock(lock_path):
            session = safe_read_json(str(FLASH_SESSION_PATH), {})
            session["last_heartbeat"] = _now_iso()
            session["batches_in_session"] = session.get("batches_in_session", 0) + 1
            session["stall_count"] = 0  # バッチ完了でストール回数リセット
            
            # Auto-recovery: auto_stopped → running
            if session.get("status") == "stopped" and session.get("auto_stop_reason") and session.get("auto_stop_reason") != "new_session_requested":
                session["status"] = "running"
                session["auto_stopped_at"] = None
                session["auto_stop_reason"] = None
                # Log recovery event
                try:
                    event_log = os.path.join(os.path.dirname(FLASH_SESSION_PATH), "event_log.jsonl")
                    event = {
                        "timestamp": _now_iso(),
                        "lifecycle": "AUTO_RECOVERED",
                        "health": "🟢 AUTO_RECOVERED",
                        "change": ["auto_recovery: stopped → running (心拍更新により自動復旧)"]
                    }
                    with open(event_log, "a", encoding="utf-8") as f:
                        f.write(json.dumps(event, ensure_ascii=False) + "\n")
                except OSError:
                    pass
            
            # Clear heartbeat_warning if present
            session.pop("heartbeat_warning", None)
            session.pop("heartbeat_warning_at", None)
            
            # コンテキスト飽和情報をOpus側に伝達 + context_pct_history追記
            try:
                status = self.generate_flash_status()
                ctx_pct = status.get("context_pct", 0)
                session["archive_urgency"] = status.get("archive_urgency", "ok")
                session["context_consumption_pct"] = ctx_pct
                # context_pct_history にバッチ完了時のctx%を追記（アダプティブ判定用）
                history = session.get("context_pct_history", [])
                history.append(ctx_pct)
                session["context_pct_history"] = history
            except (Exception,) as e:
                logger.exception("Failed to generate flash status during flash_heartbeat: %s", e)
            
            atomic_write_json(str(FLASH_SESSION_PATH), session)

    def register_flash_conversation_id(self, conversation_id: str) -> None:
        """Flashセッション起動時にconversation_idをflash_session.jsonに登録する。
        
        Opus側のhealth_check_cron.pyがAUTO_NUDGEを送信する際に、
        Antigravity send_message APIの宛先として使用される。
        
        Args:
            conversation_id: Flashセッション自身のAntigravity conversation ID
        """
        lock_path = str(FLASH_SESSION_PATH) + ".lock"
        with FileLock(lock_path):
            session = safe_read_json(str(FLASH_SESSION_PATH), {})
            session["conversation_id"] = conversation_id
            atomic_write_json(str(FLASH_SESSION_PATH), session)

    def flash_update_heartbeat(self, context_pct: Optional[int] = None) -> None:
        """心拍のみ更新する（バッチカウントは増やさない）。
        
        バッチ処理とは独立に心拍を更新するための軽量メソッド。
        タイマー発火時にFlashが呼ぶことで、バッチ処理が遅延しても
        心拍途絶を防止する。
        
        Args:
            context_pct: Flashが報告するコンテキスト消費率（0-100）。
                         指定された場合、推定値を上書きする。
        
        Auto-recovery: auto_stopped状態の場合も自動復旧する。
        """
        lock_path = str(FLASH_SESSION_PATH) + ".lock"
        with FileLock(lock_path):
            session = safe_read_json(str(FLASH_SESSION_PATH), {})
            session["last_heartbeat"] = _now_iso()
            
            # Auto-recovery: auto_stopped → running
            if session.get("status") == "stopped" and session.get("auto_stop_reason") and session.get("auto_stop_reason") != "new_session_requested":
                session["status"] = "running"
                session["auto_stopped_at"] = None
                session["auto_stop_reason"] = None
                try:
                    event_log = os.path.join(os.path.dirname(FLASH_SESSION_PATH), "event_log.jsonl")
                    event = {
                        "timestamp": _now_iso(),
                        "lifecycle": "AUTO_RECOVERED",
                        "health": "🟢 AUTO_RECOVERED",
                        "change": ["auto_recovery: stopped → running (heartbeat更新により自動復旧)"]
                    }
                    with open(event_log, "a", encoding="utf-8") as f:
                        f.write(json.dumps(event, ensure_ascii=False) + "\n")
                except OSError:
                    pass
            
            # Clear heartbeat_warning if present
            session.pop("heartbeat_warning", None)
            session.pop("heartbeat_warning_at", None)
            
            # コンテキスト飽和情報をOpus側に伝達
            try:
                status = self.generate_flash_status()
                ctx = context_pct if context_pct is not None else status.get("context_pct", 0)
                session["archive_urgency"] = status.get("archive_urgency", "ok")
                session["context_consumption_pct"] = ctx
            except (Exception,) as e:
                logger.exception("Failed to generate flash status during flash_update_heartbeat: %s", e)
            
            atomic_write_json(str(FLASH_SESSION_PATH), session)

    def flash_session_end(self, exit_reason: str) -> None:
        """Flash側がセッション終了時に呼ぶ。終了理由を記録する。"""
        lock_path = str(FLASH_SESSION_PATH) + ".lock"
        with FileLock(lock_path):
            session = safe_read_json(str(FLASH_SESSION_PATH), {})
            session["session_ended_at"] = _now_iso()
            session["exit_reason"] = exit_reason
            session["status"] = "ended"
            session["current_activity"] = "ended"
            session["current_step"] = f"終了: {exit_reason}"
            atomic_write_json(str(FLASH_SESSION_PATH), session)
        self.send_message("flash", "opus",
            f"Flash セッション終了: {exit_reason}", priority="urgent")

    def get_flash_session(self) -> dict:
        """Flashセッションの全情報を返す"""
        return safe_read_json(str(FLASH_SESSION_PATH), {})

    def check_flash_alive(self, timeout_minutes: int = 30) -> dict:
        """Flashが生存しているかをチェックする（Opus側ポーリング用）。"""
        session = safe_read_json(str(FLASH_SESSION_PATH), {})
        status = session.get("status") if session else "not_started"
        if not status:
            status = "not_started"
        if not session or status != "running":
            return {
                "alive": False, "status": status,
                "last_heartbeat": session.get("last_heartbeat") if session else None,
                "minutes_since": None,
                "exit_reason": session.get("exit_reason") if session else None,
                "current_activity": session.get("current_activity") if session else None,
                "current_step": session.get("current_step") if session else None,
            }
        last_hb = session.get("last_heartbeat", "")
        delta_minutes = 999
        if last_hb:
            hb_time = _safe_parse_iso(last_hb)
            if hb_time:
                now = datetime.now(timezone.utc)
                delta_minutes = (now - hb_time).total_seconds() / 60
        return {
            "alive": delta_minutes < timeout_minutes,
            "status": "running" if delta_minutes < timeout_minutes else "stale",
            "last_heartbeat": last_hb,
            "minutes_since": round(delta_minutes, 1),
            "exit_reason": session.get("exit_reason"),
            "current_activity": session.get("current_activity"),
            "current_step": session.get("current_step"),
            "progress_pct": session.get("progress_pct", 0),
            "subagents_running": session.get("subagents_running", 0),
            "recent_errors": session.get("recent_errors", []),
            "stall_count": session.get("stall_count", 0),
        }

    # =========================================================================
    # Opus側: Flash問題診断・改善指示（Opus → Flash）
    # =========================================================================

    def diagnose_flash_issues(self) -> dict:
        """
        Opus側がFlashの状態を診断し、問題と推奨アクションを返す。
        
        Returns:
            {
                "issues": [{"type": str, "severity": str, "description": str, "recommended_action": str}],
                "flash_status": dict,
                "needs_intervention": bool,
            }
        """
        alive = self.check_flash_alive()
        session = self.get_flash_session()
        state = self.get_phase_state()
        issues = []

        # 1. Flash停止検知
        if not alive.get("alive") and alive.get("status") == "not_started":
            issues.append({
                "type": "not_started",
                "severity": "critical",
                "description": "Flashが起動されていません。",
                "recommended_action": "プロジェクト2で flash-autonomous-entry.md を実行してください。",
            })
        elif not alive.get("alive") and alive.get("status") == "ended":
            issues.append({
                "type": "session_ended",
                "severity": "critical",
                "description": f"Flashセッションが終了しています。理由: {alive.get('exit_reason', '不明')}",
                "recommended_action": "プロジェクト2で「続行して」と入力して再起動してください。",
            })
        elif not alive.get("alive") and alive.get("status") == "stale":
            issues.append({
                "type": "stale",
                "severity": "high",
                "description": f"Flashが{alive.get('minutes_since', '?')}分間応答なし。最後の活動: {alive.get('current_step', '不明')}",
                "recommended_action": "プロジェクト2のチャットを確認し、エラーで停止していないか確認してください。",
            })

        # 2. 連続エラー検知
        stall_count = session.get("stall_count", 0)
        if stall_count >= 3:
            recent_errors = session.get("recent_errors", [])
            error_summary = "; ".join([e.get("error", "")[:50] for e in recent_errors[-3:]])
            issues.append({
                "type": "repeated_errors",
                "severity": "high",
                "description": f"連続{stall_count}回のエラー発生。直近: {error_summary}",
                "recommended_action": "エラー原因モジュールのブラックリスト化、またはタスク配分の変更を推奨。",
            })

        # 3. 進捗停滞検知
        if (alive.get("alive") and alive.get("progress_pct", 0) == 0
                and alive.get("minutes_since", 0) and alive["minutes_since"] > 10):
            issues.append({
                "type": "no_progress",
                "severity": "medium",
                "description": f"10分以上進捗0%。現在のステップ: {alive.get('current_step', '不明')}",
                "recommended_action": "タスクの粒度が大きすぎる可能性。バッチサイズの縮小を検討。",
            })

        # 4. Emergency Stop検知
        if state.get("emergency_stop"):
            issues.append({
                "type": "emergency_stop",
                "severity": "critical",
                "description": f"緊急停止中。理由: {state.get('stop_reason', '不明')}",
                "recommended_action": "hub.resume_from_stop() で復旧し、原因モジュールをブラックリスト化。",
            })

        return {
            "issues": issues,
            "flash_status": alive,
            "needs_intervention": any(i["severity"] in ("critical", "high") for i in issues),
        }

    def send_improvement_directive(self, problem_type: str,
                                   instructions: str) -> str:
        """
        Opus側がFlashに改善指示を送る。
        Flashは次のループイテレーション開始時にこれを読み取る。
        
        Args:
            problem_type: 問題の種別（"stall", "error_pattern", "strategy_change"等）
            instructions: Flash向けの具体的な改善指示テキスト
        
        Returns:
            メッセージID
        """
        msg_id = self.send_message(
            "opus", "flash",
            f"[改善指示/{problem_type}] {instructions}",
            priority="urgent"
        )
        return msg_id
