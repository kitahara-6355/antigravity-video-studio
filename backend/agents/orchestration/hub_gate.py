"""
Orchestration Hub — Phase Gate・進行管理 Mixin

orchestrator.py から抽出されたPhaseゲート判定、Phase進行、
ブラックリスト管理、緊急停止/復旧メソッドを提供する。
"""

import json
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from .hub_common import (
    logger, _now_iso, _append_jsonl, _read_jsonl,
    _safe_parse_iso, OpusQuotaExceededException, OPUS_DIRECTIVE_PATH,
    PHASE_STATE_PATH, PHASE_GATES_PATH, _MEMORY_DIR, _BASE_DIR,
    TASK_QUEUE_PATH, MESSAGE_BOX_PATH, FLASH_REPORTS_PATH, FLASH_SESSION_PATH,
)
from .atomic_io import safe_read_json, atomic_write_json
from .verifier import CodeVerifier


def _auto_commit_suppressed() -> bool:
    """自動 Git コミットを抑止すべき状況か判定する。

    submit_batch_report の自動計装は `_git_auto_commit` を呼ぶが、その中身は
    `git add -A` + `git commit` である。作業ツリー全体を巻き込むため、
    pytest 実行中に発火すると開発者の未コミット作業まで取り込んでしまう。
    2026-07-25 に cc/trinity-5.0 で実際に3件のコミットが発生した。

    抑止条件:
      - PYTEST_CURRENT_TEST: pytest がテスト実行中に自動設定する
      - ANTIGRAVITY_DISABLE_AUTO_COMMIT=1: CI 等での明示的な抑止
    """
    return bool(os.environ.get("PYTEST_CURRENT_TEST")) or \
        os.environ.get("ANTIGRAVITY_DISABLE_AUTO_COMMIT") == "1"


class GateMixin:
    '''Phase Gate・進行管理のMixin'''

    def get_phase_state(self) -> dict:
        """現在のPhase状態を返す"""
        return safe_read_json(str(PHASE_STATE_PATH), {})

    def update_phase_state(self, updates: dict) -> dict:
        """Phase状態を部分更新する"""
        state = safe_read_json(str(PHASE_STATE_PATH), {})
        state.update(updates)
        atomic_write_json(str(PHASE_STATE_PATH), state)
        return state

    def check_phase_gate(self, phase: int) -> dict:
        """
        Phaseゲート条件をチェックし、結果を返す。
        
        conditions配列の各条件を実際のメトリクスと比較する。
        未知のメトリクスはFalse（安全側に倒す）。
        
        追加2層ゲート（DS-037統合）:
        - 変更行カバレッジ100%検証
        - UXラチェットテスト
        
        Returns:
            {
                "phase": 5,
                "all_passed": True/False,
                "conditions": {条件名: True/False, ...},
                "fallback_applied": True/False  (ゲート定義不在時)
            }
        """
        import subprocess
        import sys
        from .hub_common import _PROJECT_ROOT

        gates = safe_read_json(str(PHASE_GATES_PATH), {})
        state = safe_read_json(str(PHASE_STATE_PATH), {})
        
        phase_key = str(phase)
        # 既存のphase_gates.jsonが「phases」キー配下にネストされている場合のフォールバック
        gate_def = (
            gates.get(phase_key)
            or gates.get(f"phase_{phase}")
            or gates.get("phases", {}).get(phase_key)
            or {}
        )
        
        # フェイルセーフ: ゲート定義が存在しない場合は通過させない
        # （ゲート未定義Phaseへの自動進行を防止 — 成果検証レポート §7.2.3）
        if not gate_def:
            return {
                "phase": phase,
                "all_passed": False,
                "conditions": {"gate_definition_exists": False},
                "fallback_applied": True,
                "blocked_reason": f"Phase {phase} のゲート定義が phase_gates.json に存在しません。進行をブロックします。",
            }
        
        results = {}
        metrics = state.get("metrics", {})
        
        # --- TDR CRITICAL件数を正確に取得（APIのキー不整合を回避）---
        actual_critical_debt = self._get_actual_critical_debt_count()
        
        # 基本条件（全Phase共通）
        results["no_emergency_stop"] = not state.get("emergency_stop", False)
        
        # min_coverage / max_critical_debt がある場合（Phase 21+形式）
        if "min_coverage" in gate_def:
            results["coverage_target"] = metrics.get("coverage_pct", 0) >= gate_def["min_coverage"]
        if "max_critical_debt" in gate_def:
            results["no_critical_debt"] = actual_critical_debt <= gate_def["max_critical_debt"]
        
        # --- conditions配列の評価（Phase 5-20 + Phase 21+で使用）---
        conditions = gate_def.get("conditions", [])
        gate_checklist = state.get("gate_checklist", {})
        
        for cond in conditions:
            name = cond.get("name", "")
            operator = cond.get("operator", "==")
            expected = cond.get("value")
            
            if not name:
                continue
            
            # メトリクスからの自動取得を試行
            actual = None
            if name == "coverage_pct":
                actual = metrics.get("coverage_pct", 0)
            elif name == "coverage_branch_pct":
                actual = metrics.get("coverage_branch_pct", 0)
            elif name == "critical_debt":
                actual = actual_critical_debt
            elif name == "test_count":
                actual = metrics.get("test_count", 0)
            elif name == "quality_score":
                actual = metrics.get("quality_score", 0)
            elif name == "ratchet_items":
                actual = metrics.get("ratchet_items", 0)
            else:
                # gate_checklistから手動/自動設定された値を取得
                actual = gate_checklist.get(name)
            
            # 未知のメトリクスはFalse（安全側に倒す）
            if actual is None:
                results[name] = False
                continue
            
            # 比較演算
            try:
                if operator == ">=":
                    results[name] = actual >= expected
                elif operator == "<=":
                    results[name] = actual <= expected
                elif operator == "==":
                    results[name] = actual == expected
                elif operator == ">":
                    results[name] = actual > expected
                elif operator == "<":
                    results[name] = actual < expected
                elif operator == "!=":
                    results[name] = actual != expected
                else:
                    results[name] = False
            except (TypeError, ValueError):
                results[name] = False
        
        # --- 2層目ゲート ① 変更行カバレッジ100%検証（DS-037統合） ---
        results["changed_line_coverage"] = True
        try:
            from .hub_common import _read_jsonl
            reports = _read_jsonl(FLASH_REPORTS_PATH)
            if reports:
                last_report = reports[-1]
                git_diff = last_report.get("git_diff_summary", {})
                changed_files = git_diff.get("changed_files", []) if isinstance(git_diff, dict) else []
                cov_path = _PROJECT_ROOT / "coverage.json"
                if cov_path.exists() and changed_files:
                    cov_data = safe_read_json(str(cov_path), {})
                    files_cov = cov_data.get("files", {})
                    for f in changed_files:
                        norm_f = f.replace("/", "\\")
                        cov_entry = files_cov.get(norm_f) or files_cov.get(f)
                        if cov_entry:
                            pct = cov_entry.get("summary", {}).get("percent_covered", 100.0)
                            if float(pct) < 100.0:
                                results["changed_line_coverage"] = False
                                logger.warning(f"[GateKeeper] 変更ファイル {f} のカバレッジが100%未満 ({pct}%)")
                                break
        except (OSError, json.JSONDecodeError, IndexError, KeyError, TypeError, ValueError, AttributeError) as e:
            logger.warning(f"[GateKeeper] カバレッジ検証エラー: {e}")

        # --- 2層目ゲート ② UXストーリー検証（DS-037統合） ---
        results["ux_ratchet_pass"] = True
        try:
            res = subprocess.run(
                [sys.executable, "-m", "pytest", "backend/tests/test_ux_ratchet.py", "-q"],
                capture_output=True,
                text=True,
                timeout=30
            )
            if res.returncode != 0:
                results["ux_ratchet_pass"] = False
                logger.warning("[GateKeeper] UXラチェットテスト (test_ux_ratchet.py) が不合格")
        except (subprocess.SubprocessError, OSError) as e:
            results["ux_ratchet_pass"] = False
            logger.warning(f"[GateKeeper] UXラチェット検証エラー: {e}")
        
        return {
            "phase": phase,
            "all_passed": all(results.values()),
            "conditions": results,
            "fallback_applied": False,
        }

    def _get_actual_critical_debt_count(self) -> int:
        """TDR CRITICAL件数を正確に取得する（APIキー不整合を回避）"""
        try:
            tdr_path = PHASE_STATE_PATH.parent / "technical_debt_index.json"
            if not tdr_path.exists():
                return 0
            tdr = safe_read_json(str(tdr_path), {})
            # entries キー（実データ）を直接読む
            entries = tdr.get("entries", tdr.get("items", tdr.get("debts", [])))
            count = 0
            for entry in entries:
                if entry.get("status") in ("fixed", "resolved", "accepted"):
                    continue
                sev = entry.get("severity", entry.get("category", ""))
                if "CRITICAL" in str(sev).upper():
                    count += 1
            return count
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError):
            return 0

    def advance_phase(self) -> int:
        """次のPhaseに進む。新しいPhase番号を返す。
        
        【ハードゲート限定モデル（Σ-2a改修）】
        ゲート条件を全て満たした場合のみPhase進行を許可する。
        ソフトゲート（ゲート未通過でも進行）は空想リスク排除のため廃止。
        
        Returns:
            int: 新しいPhase番号（進行した場合）、または現在のPhase番号（ブロックされた場合）
        """
        state = safe_read_json(str(PHASE_STATE_PATH), {})
        current_phase = state.get("current_phase", 1)
        
        # ゲート判定
        gate_result = self.check_phase_gate(current_phase)
        
        if not gate_result["all_passed"]:
            # ハードゲート: ゲート未通過 = 進行不可（例外なし）
            self._record_valley_report(current_phase, gate_result, state)
            logger.warning(
                f"[HardGate] Phase {current_phase} ゲート未通過でブロック。"
                f"未通過条件: {[k for k, v in gate_result.get('conditions', {}).items() if not v]}"
            )
            return current_phase  # 進行しない
        
        # ゲート通過 → Phase進行
        new_phase = current_phase + 1
        state["current_phase"] = new_phase
        state["current_milestone"] = f"M{new_phase}.1"
        state["phase_started_at"] = _now_iso()
        # バッチカウンタリセット
        state["flash_batches_completed"] = 0
        state["flash_tasks_total"] = 0
        state["flash_tasks_passed"] = 0
        state["flash_tasks_failed"] = 0
        state["flash_consecutive_failures"] = 0
        state["blacklisted_modules"] = []
        # DS枯渇フラグリセット（新Phaseの設計書が使えるようになる）
        state.pop("ds_exhausted", None)
        state.pop("ds_exhausted_at", None)
        # ゲート通過証跡を記録
        state["last_gate_passed"] = {
            "phase": current_phase,
            "passed_at": _now_iso(),
            "conditions": gate_result.get("conditions", {})
        }
        atomic_write_json(str(PHASE_STATE_PATH), state)
        logger.info(f"[HardGate] Phase {current_phase} -> {new_phase} ゲート通過・進行")
        return new_phase


    def _record_valley_report(self, phase: int, gate_result: dict,
                               state: dict) -> None:
        """フェーズ谷レポートを自動生成する。
        
        Phase移行時にクリティカルエラー・未通過ゲート条件・BL状況を
        構造化JSONとして保存。Opusがフェーズの谷でバッチ対処するための情報源。
        """
        from pathlib import Path
        
        valley_dir = _BASE_DIR / "valley_reports"
        valley_dir.mkdir(exist_ok=True)
        
        # 未通過条件の抽出
        failed_conditions = [
            k for k, v in gate_result.get("conditions", {}).items() if not v
        ]
        
        # クリティカルエラーの収集（直近バッチレポートから）
        critical_errors = []
        try:
            reports = _read_jsonl(FLASH_REPORTS_PATH)
            for report in reports[-10:]:  # 直近10バッチ
                for task in report.get("tasks", []):
                    if task.get("status") == "fail":
                        error_info = ""
                        if isinstance(task.get("result"), dict):
                            error_info = task["result"].get("error", "")[:300]
                        critical_errors.append({
                            "task_id": task.get("id", ""),
                            "group": task.get("group", ""),
                            "module": task.get("target_module", ""),
                            "error": error_info,
                            "batch_id": report.get("batch_id", ""),
                        })
        except Exception as e:
            logger.warning(f"Valley report: Failed to collect errors: {e}")
        
        # BL状況
        bl_modules = state.get("blacklisted_modules", [])
        
        # 統計
        total = state.get("flash_tasks_total", 0)
        passed = state.get("flash_tasks_passed", 0)
        failed = state.get("flash_tasks_failed", 0)
        pass_rate = (passed / total * 100) if total > 0 else 0
        
        # Opus対処が必要な項目を優先度付きで列挙
        opus_actions = []
        for cond in failed_conditions:
            opus_actions.append({
                "priority": "critical" if cond in ("coverage_target", "no_critical_debt") else "medium",
                "type": "gate_failure",
                "condition": cond,
                "description": f"Phase {phase} ゲート条件 '{cond}' が未通過",
            })
        if len(critical_errors) > 10:
            opus_actions.append({
                "priority": "high",
                "type": "error_accumulation",
                "count": len(critical_errors),
                "description": f"{len(critical_errors)}件のクリティカルエラーが蓄積",
            })
        if len(bl_modules) > 20:
            opus_actions.append({
                "priority": "medium",
                "type": "blacklist_saturation",
                "count": len(bl_modules),
                "description": f"BL {len(bl_modules)}件 — クリーンアップ推奨",
            })
        
        report = {
            "phase": phase,
            "generated_at": _now_iso(),
            "gate_result": {
                "all_passed": gate_result.get("all_passed", False),
                "failed_conditions": failed_conditions,
                "conditions": gate_result.get("conditions", {}),
            },
            "flash_stats": {
                "batches_completed": state.get("flash_batches_completed", 0),
                "tasks_total": total,
                "tasks_passed": passed,
                "tasks_failed": failed,
                "pass_rate_pct": round(pass_rate, 1),
            },
            "blacklisted_modules": bl_modules[:30],  # 上位30件
            "blacklist_count": len(bl_modules),
            "critical_errors": critical_errors[:20],  # 上位20件
            "critical_error_count": len(critical_errors),
            "opus_action_required": opus_actions,
            "opus_action_count": len(opus_actions),
        }
        
        report_path = valley_dir / f"valley_phase_{phase}.json"
        atomic_write_json(str(report_path), report)
        logger.info(
            f"[ValleyReport] Phase {phase} 谷レポート生成: "
            f"未通過{len(failed_conditions)}件, エラー{len(critical_errors)}件, "
            f"Opus対処{len(opus_actions)}件"
        )

    # =========================================================================
    # ブラックリスト管理（自動回避）
    # =========================================================================

    def blacklist_module(self, module_path: str, reason: str) -> None:
        """モジュールをブラックリストに追加（自動回避用）"""
        queue = safe_read_json(str(TASK_QUEUE_PATH), {})
        bl = queue.get("blacklisted_modules", [])
        entry = {"module": module_path, "reason": reason, "added_at": _now_iso()}
        if not any((b["module"] if isinstance(b, dict) else b) == module_path for b in bl):
            bl.append(entry)
        queue["blacklisted_modules"] = bl
        atomic_write_json(str(TASK_QUEUE_PATH), queue)

        
        # phase_state にも反映
        state = safe_read_json(str(PHASE_STATE_PATH), {})
        state_bl = state.get("blacklisted_modules", [])
        if module_path not in state_bl:
            state_bl.append(module_path)
        state["blacklisted_modules"] = state_bl
        atomic_write_json(str(PHASE_STATE_PATH), state)

    def unblacklist_module(self, module_path: str) -> None:
        """モジュールをブラックリストから解除"""
        queue = safe_read_json(str(TASK_QUEUE_PATH), {})
        queue["blacklisted_modules"] = [
            b for b in queue.get("blacklisted_modules", [])
            if (b["module"] if isinstance(b, dict) else b) != module_path
        ]
        atomic_write_json(str(TASK_QUEUE_PATH), queue)
        
        state = safe_read_json(str(PHASE_STATE_PATH), {})
        state["blacklisted_modules"] = [
            m for m in state.get("blacklisted_modules", [])
            if m != module_path
        ]
        atomic_write_json(str(PHASE_STATE_PATH), state)

    # =========================================================================
    # Emergency Stop
    # =========================================================================

    def trigger_emergency_stop(self, reason: str) -> None:
        """緊急停止をトリガーする"""
        state = safe_read_json(str(PHASE_STATE_PATH), {})
        state["emergency_stop"] = True
        state["stop_reason"] = reason
        atomic_write_json(str(PHASE_STATE_PATH), state)
        
        # Opusに緊急通知
        self.send_message(
            "flash", "opus",
            f"🚨 Emergency Stop: {reason}",
            priority="urgent"
        )

    def resume_from_stop(self) -> None:
        """緊急停止からの復旧"""
        state = safe_read_json(str(PHASE_STATE_PATH), {})
        state["emergency_stop"] = False
        state["stop_reason"] = None
        state["flash_consecutive_failures"] = 0
        atomic_write_json(str(PHASE_STATE_PATH), state)

    # =========================================================================
    # メッセージボックス
    # =========================================================================

    def send_message(self, sender: str, recipient: str,
                     content: str, priority: str = "normal") -> str:
        """
        メッセージを送信する。
        
        Args:
            sender: "flash", "opus", "user" のいずれか
            recipient: "flash", "opus", "user" のいずれか
            content: メッセージ本文
            priority: "normal" または "urgent"
        
        Returns:
            メッセージID
        """
        msg_id = f"M-{uuid.uuid4().hex[:8]}"
        record = {
            "id": msg_id,
            "from": sender,
            "to": recipient,
            "priority": priority,
            "content": content,
            "timestamp": _now_iso(),
            "ack": False,
        }
        _append_jsonl(MESSAGE_BOX_PATH, record)
        return msg_id

    def read_messages(self, recipient: str,
                      unread_only: bool = True) -> list[dict]:
        """
        指定された受信者宛のメッセージを読む。
        
        Args:
            recipient: "flash", "opus", "user" のいずれか
            unread_only: True の場合、未確認メッセージのみ返す
        """
        messages = _read_jsonl(MESSAGE_BOX_PATH)
        filtered = [
            m for m in messages
            if m.get("to") == recipient
            and (not unread_only or not m.get("ack", False))
        ]
        # urgent を先に並べる
        filtered.sort(key=lambda m: (0 if m.get("priority") == "urgent" else 1))
        return filtered

    def acknowledge_message(self, message_id: str) -> None:
        """メッセージを既読にする"""
        messages = _read_jsonl(MESSAGE_BOX_PATH)
        updated = []
        for m in messages:
            if m.get("id") == message_id:
                m["ack"] = True
            updated.append(m)
        # 全書き換え（JSONL更新）
        with open(MESSAGE_BOX_PATH, "w", encoding="utf-8", newline="\n") as f:
            for record in updated:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # =========================================================================
    # 報告管理
    # =========================================================================

    def submit_batch_report(self, batch_id: str, results: dict) -> None:
        """
        バッチ完了報告を追記する。
        
        【自動計装】以下が自動実行される:
        - ハートビート送信（ストールカウントリセット）
        - Phaseゲート自動チェック（通過時はOpus通知）
        - ステータス更新
        - Git自動コミット（品質ゲート通過時のみ）
        - 受信トレイへのレポート生成（エラー時 or 5バッチごと）
        """
        # Git diff を取得（コミット前に記録）
        git_diff_summary = self._capture_git_diff()
        
        # task_queue.json から完了したタスクの情報を取得
        tasks_in_batch = []
        if TASK_QUEUE_PATH.exists():
            try:
                queue = safe_read_json(str(TASK_QUEUE_PATH), {})
                for task in queue.get("tasks", []):
                    status = task.get("status")
                    if status in ["pass", "fail"]:
                        result = task.get("result")
                        # DS-037統合: 空PASS（変更なし）の検知とstatus上書き
                        if status == "pass":
                            changed_files = []
                            if isinstance(result, dict):
                                changed_files = result.get("changed_files", [])
                            if not changed_files:
                                status = "skip"
                        tasks_in_batch.append({
                            "id": task.get("id"),
                            "group": task.get("group"),
                            "target_module": task.get("target_module"),
                            "instruction": task.get("instruction"),
                            "status": status,
                            "result": result,
                            "started_at": task.get("started_at"),
                            "completed_at": task.get("completed_at"),
                        })
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                pass

        state = safe_read_json(str(PHASE_STATE_PATH), {})
        phase = state.get("current_phase", 5)
        metrics = state.get("metrics", {})
        
        # コンテキスト消費率をレポートに記録（アダプティブ判定の学習データ）
        session_for_report = safe_read_json(str(FLASH_SESSION_PATH), {})
        ctx_pct_at_report = session_for_report.get("context_consumption_pct", 0)
        batches_at_report = session_for_report.get("batches_in_session", 0)
        ctx_history = session_for_report.get("context_pct_history", [])
        avg_delta = 0.0
        if len(ctx_history) >= 2:
            deltas = [ctx_history[i+1] - ctx_history[i] for i in range(len(ctx_history)-1)]
            avg_delta = round(sum(deltas) / len(deltas), 2) if deltas else 0.0

        report = {
            "batch_id": batch_id,
            "phase": phase,
            "timestamp": _now_iso(),
            "results": results,
            "git_diff_summary": git_diff_summary,
            "tasks": tasks_in_batch,
            "metrics": metrics,
            "context_pct_at_report": ctx_pct_at_report,
            "session_batches_at_report": batches_at_report,
            "avg_delta_per_batch": avg_delta,
        }

        # 大規模変更タスクの検出と記録（DS-016 / DS-026）
        large_change_modules = []
        if TASK_QUEUE_PATH.exists():
            try:
                queue = safe_read_json(str(TASK_QUEUE_PATH), {})
                large_change_modules = queue.get("large_change_modules", [])
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError):
                pass

        has_new_large_change = False
        for t in tasks_in_batch:
            t_result = t.get("result") or {}
            changed_files = t_result.get("changed_files", [])
            if len(changed_files) > 3:
                target_module = t.get("target_module")
                if target_module and target_module not in large_change_modules:
                    large_change_modules.append(target_module)
                    has_new_large_change = True
                    logger.info(f"[Orchestrator] Large change detected in task {t.get('id')} for module {target_module} (files: {len(changed_files)})")

        if has_new_large_change:
            try:
                queue = safe_read_json(str(TASK_QUEUE_PATH), {})
                queue["large_change_modules"] = large_change_modules
                atomic_write_json(str(TASK_QUEUE_PATH), queue)
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError) as e:
                logger.warning(f"Failed to save large_change_modules to task_queue: {e}")
        
        # --- 自動計装: ハーネス品質ゲート検証（DS-011 Stage 2） ---
        from backend.harness.governance import governance_engine
        governance_engine.validate_batch_quality(results, report)
        
        _append_jsonl(FLASH_REPORTS_PATH, report)
        
        # phase_state のバッチカウントとブラックリストを更新
        state = safe_read_json(str(PHASE_STATE_PATH), {})
        
        # --- DS-037統合: Loop Detector (auto_blacklist_expiry管理) ---
        auto_expiry = state.get("auto_blacklist_expiry", {})
        blacklisted = state.get("blacklisted_modules", [])
        
        new_auto_expiry = {}
        for mod, remaining in auto_expiry.items():
            if remaining > 1:
                new_auto_expiry[mod] = remaining - 1
            else:
                if mod in blacklisted:
                    blacklisted.remove(mod)
                    logger.info(f"[LoopDetector] モジュール {mod} の一時ブラックリスト期限切れ。解除")
                    
        miss_counts = self._get_module_miss_counts()
        for mod, c in miss_counts.items():
            if c >= 3:
                if mod not in blacklisted and len(blacklisted) < 30:
                    blacklisted.append(mod)
                    logger.info(f"[LoopDetector] モジュール {mod} が3回連続空PASSのため3バッチ間ブラックリスト化")
                elif len(blacklisted) >= 30:
                    logger.info(f"[LoopDetector] ブラックリスト上限(30)到達。{mod} の除外をスキップ")
                new_auto_expiry[mod] = 3
                
        state["blacklisted_modules"] = blacklisted
        state["auto_blacklist_expiry"] = new_auto_expiry
        state["metrics"] = metrics  # 更新したメトリクスを書き戻す
        
        state["flash_batches_completed"] = state.get("flash_batches_completed", 0) + 1
        state["last_batch_id"] = batch_id
        atomic_write_json(str(PHASE_STATE_PATH), state)
        
        # --- G-3: 自動計装: 空想リスクゲート検証 (5バッチに1回実行、かつ初回) ---
        batches_completed = state.get("flash_batches_completed", 0)
        if batches_completed == 0 or batches_completed % 5 == 0:
            try:
                from backend.ux_verification.anti_hallucination_gate import AntiHallucinationGate
                gate = AntiHallucinationGate()
                report_gate = gate.run_all_checks()
                if report_gate.hallucination_score > 0.0:
                    logger.warning(
                        f"[GateKeeper] ⚠️ バッチ {batch_id} 完了後に空想リスク検出! "
                        f"スコア: {report_gate.hallucination_score:.1f} (違反: {len(report_gate.violations)}件)"
                    )
                    # レポートメタデータに警告を付与
                    report["hallucination_warning"] = {
                        "score": report_gate.hallucination_score,
                        "violations": [v.description for v in report_gate.violations]
                    }
                    # --- 検知履歴への自動記録 (ダッシュボード連動) ---
                    try:
                        _det_log_path = _PROJECT_ROOT / "backend" / "agents" / "memory" / "hallucination_detection_log.json"
                        _det_entries = []
                        if _det_log_path.exists():
                            with open(_det_log_path, "r", encoding="utf-8") as _df:
                                _det_entries = json.load(_df)
                        _next_num = len(_det_entries) + 1
                        for v in report_gate.violations:
                            _det_entries.append({
                                "id": f"HD-{_next_num:03d}",
                                "detected_at": _now_iso(),
                                "severity": v.severity,
                                "type": "AUTO_DETECTED",
                                "title": f"バッチ {batch_id} 完了時検出: {v.source}",
                                "description": v.description,
                                "detection_method": f"AntiHallucinationGate (バッチ {batch_id}, 自動計装G-3)",
                                "correction": "",
                                "prevention": "",
                                "related_files": [v.file_path] if v.file_path else [],
                                "status": "open"
                            })
                            _next_num += 1
                        atomic_write_json(str(_det_log_path), _det_entries)
                        logger.info(f"[GateKeeper] 検知履歴に {len(report_gate.violations)} 件を記録")
                    except Exception as _det_err:
                        logger.error(f"[GateKeeper] 検知履歴記録エラー: {_det_err}")
            except Exception as e:
                logger.error(f"[GateKeeper] 空想リスクゲート実行エラー: {e}")

        # --- 自動計装: ハートビート ---
        self.flash_heartbeat()
        
        # --- 自動計装: Phaseゲート自動チェック ---
        phase = state.get("current_phase", 5)
        gate = self.check_phase_gate(phase)
        if gate["all_passed"]:
            new_phase = self.advance_phase()
            self.send_message("flash", "opus",
                f"🎉 Phase {phase} ゲート通過。Phase {new_phase} 開始。",
                priority="normal")
            self.flash_update_status(
                "phase_advanced",
                f"Phase {phase} 完了 → Phase {new_phase} 開始"
            )
            self._generate_phase_report(phase)
        else:
            self.flash_update_status(
                "batch_complete",
                f"バッチ {batch_id} 完了。次バッチ準備中",
                progress_pct=100
            )
        
        # --- 【S2-1】自動計装: カバレッジ自動測定 → Phase Gate連動 ---
        self._safe_instrument("coverage_measurement", self._auto_measure_coverage, state)

        # --- 自動計装: Git自動コミット ---
        def _git_commit_task():
            if _auto_commit_suppressed():
                return
            if git_diff_summary.get("files_changed", 0) > 0:
                passed = results.get("passed", 0)
                failed = results.get("failed", 0)
                batch_label = batch_id if batch_id.startswith("batch_") else f"batch_{batch_id}"
                commit_msg = (
                    f"[Flash/{batch_label}] P{phase}/M{state.get('current_milestone','?')} "
                    f"| {passed}pass/{failed}fail "
                    f"| files:{git_diff_summary.get('files_changed', 0)}"
                )
                self._git_auto_commit(commit_msg)
        self._safe_instrument("git_auto_commit", _git_commit_task)
        
        # --- 自動計装: 受信トレイへのレポート生成 ---
        def _report_gen_task():
            has_failures = results.get("failed", 0) > 0
            batch_num = state.get("flash_batches_completed", 0)
            is_milestone = batch_num % 5 == 0
            if has_failures or is_milestone:
                self._generate_batch_report_file(batch_id, results, state)
        self._safe_instrument("batch_report_gen", _report_gen_task)

        # --- 自動計装: 毎時速報レポート ---
        self._safe_instrument("hourly_report", self.generate_hourly_report)

        # --- 自動計装: サブエージェントダッシュボード自動更新 ---
        self._safe_instrument("subagent_dashboard", self._update_subagent_dashboard)

        # --- 自動計装: ハーネス監査ログ連動（DS-011 Stage 1） ---
        self._safe_instrument("harness_audit_log", 
                             self._emit_harness_audit_log, batch_id, results, report)

        # --- 自動計装: ハーネス Stage 3 Evaluator-Optimizer ---
        def _evaluator_task():
            from backend.harness.evaluator_optimizer import orchestrator_evaluator_optimizer
            orchestrator_evaluator_optimizer.analyze_and_suggest(batch_id, results, report)
        self._safe_instrument("evaluator_optimizer", _evaluator_task)

        # --- 自動計装: 学習エンジンキャッシュ更新 ---
        def _learning_refresh_task():
            from backend.agents.orchestration.learning_integration import refresh_and_cache
            refresh_and_cache()
        self._safe_instrument("learning_cache_refresh", _learning_refresh_task)

    def set_directive(self, priorities: dict, phase_advance: bool = False,
                      focus_modules: Optional[list] = None,
                      notes: str = "") -> str:
        """
        OpusがFlashへの戦略指示を設定する。
        
        Args:
            priorities: グループ別配分 (例: {"test_weaver": 40, "bug_hunter": 20, ...})
            phase_advance: True の場合、次Phase移行を指示
            focus_modules: 重点対象モジュール
            notes: 戦略メモ
        
        Returns:
            指示ID
        """
        directive_id = f"D-{uuid.uuid4().hex[:8]}"
        directive = {
            "directive_id": directive_id,
            "issued_at": _now_iso(),
            "issued_by": "opus",
            "priorities": priorities,
            "phase_advance": phase_advance,
            "focus_modules": focus_modules or [],
            "blacklist_override": [],
            "resume": True,
            "notes": notes,
        }
        atomic_write_json(str(OPUS_DIRECTIVE_PATH), directive)
        return directive_id

    def get_current_directive(self) -> Optional[dict]:
        """現在の戦略指示を読む。指示がない場合は None。"""
        directive = safe_read_json(str(OPUS_DIRECTIVE_PATH), {})
        if not directive or not directive.get("directive_id"):
            return None
        return directive

    def should_trigger_opus_review(self) -> bool:
        """
        Opus 4.6 による自動レビューを起動すべきか判定する。
        """
        if not PHASE_STATE_PATH.exists():
            return False
        
        state = safe_read_json(str(PHASE_STATE_PATH), {})
        
        # 0. 手動/すでに awaiting_opus が True の場合
        if state.get("awaiting_opus") is True:
            return True
            
        # 1. 時間ベース判定 — 無効化 (イベント駆動モデルに移行)
        # 理由: Opus介入を最小化するため、定期レビュー（5時間ごと）を廃止。
        # Phase完了時（条件3）とエスカレーション累積時（条件2）のみ発動に変更。
        # 旧ロジック:
        # last_review_str = state.get("last_opus_review")
        # if last_review_str:
        #     last_review = _safe_parse_iso(last_review_str)
        #     if last_review:
        #         now = datetime.now(timezone.utc)
        #         if (now - last_review) >= timedelta(hours=5):
        #             state["awaiting_opus"] = True
        #             atomic_write_json(str(PHASE_STATE_PATH), state)
        #             return True
                
        # 2. 異常蓄積ベース (連続5回以上のFAIL または 累積エラー15件以上)
        if state.get("flash_consecutive_failures", 0) >= 5:
            state["awaiting_opus"] = True
            atomic_write_json(str(PHASE_STATE_PATH), state)
            return True
            
        if state.get("flash_tasks_failed", 0) >= 15:
            state["awaiting_opus"] = True
            atomic_write_json(str(PHASE_STATE_PATH), state)
            return True

        # 3. Milestone完了ゲート判定
        if TASK_QUEUE_PATH.exists():
            queue = safe_read_json(str(TASK_QUEUE_PATH), {})
            tasks = queue.get("tasks", [])
            if tasks:
                all_done = all(t.get("status") in ("pass", "fail") for t in tasks)
                if all_done:
                    state["awaiting_opus"] = True
                    atomic_write_json(str(PHASE_STATE_PATH), state)
                    return True

        # 4. DS枯渇トリガー（施策3: hub_batch.pyが設定したフラグを検知）
        if state.get("ds_exhausted") is True:
            state["awaiting_opus"] = True
            state["opus_review_reason"] = "DS枯渇: 設計ストックが完全に枯渇。新規タスクの方針決定が必要"
            atomic_write_json(str(PHASE_STATE_PATH), state)
            return True

        # 5. カバレッジ停滞トリガー（5バッチ連続でcoverage_pctが変化なし）
        coverage_history = state.get("coverage_history", [])
        if len(coverage_history) >= 5:
            last_5 = coverage_history[-5:]
            if len(set(last_5)) == 1:  # 全て同じ値 = 停滞
                state["awaiting_opus"] = True
                state["opus_review_reason"] = (
                    f"カバレッジ停滞: 直近5バッチで coverage_pct={last_5[0]}% のまま変化なし。"
                    f"ゲート達成のための戦略変更が必要"
                )
                atomic_write_json(str(PHASE_STATE_PATH), state)
                return True

        return False

    def trigger_opus_review_now(self) -> None:
        """
        手動で Opus レビューを即時強制起動する。
        """
        if PHASE_STATE_PATH.exists():
            state = safe_read_json(str(PHASE_STATE_PATH), {})
            state["awaiting_opus"] = True
            atomic_write_json(str(PHASE_STATE_PATH), state)

    def start_opus_review(self, predicted_hours: float = 0.0) -> None:
        """
        Opusレビューの実行を開始する。
        週5時間の制限時間チェックと自動リセット、および超過時のブロックを行う。
        """
        if not PHASE_STATE_PATH.exists():
            return

        state = safe_read_json(str(PHASE_STATE_PATH), {})
        now = datetime.now(timezone.utc)

        # 週の開始時刻のチェックとリセット
        week_start_str = state.get("opus_week_start")
        should_reset = False
        if not week_start_str:
            should_reset = True
        else:
            week_start = _safe_parse_iso(week_start_str)
            if not week_start or (now - week_start) >= timedelta(days=7):
                should_reset = True

        if should_reset:
            logger.info("Opus週カウンタをリセットします（7日以上経過）。")
            state["opus_hours_used_this_week"] = 0.0
            state["opus_reviews_this_week"] = 0
            state["opus_week_start"] = now.isoformat(timespec="seconds")
            atomic_write_json(str(PHASE_STATE_PATH), state)

        # 累積使用時間のチェック
        # デフォルト上限: 5.0 時間
        MAX_OPUS_HOURS = 5.0
        current_hours = state.get("opus_hours_used_this_week", 0.0)
        
        if current_hours >= MAX_OPUS_HOURS or (current_hours + predicted_hours) > MAX_OPUS_HOURS:
            logger.error(
                f"Opus週時間制限を超過しました。 "
                f"現在: {current_hours:.2f}時間 / 上限: {MAX_OPUS_HOURS}時間 (予測: {predicted_hours:.2f}時間)"
            )
            raise OpusQuotaExceededException(
                f"Opus週時間制限を超過しました。現在: {current_hours:.2f}時間 / 上限: {MAX_OPUS_HOURS}時間"
            )

        # 状態更新
        state["awaiting_opus"] = True
        atomic_write_json(str(PHASE_STATE_PATH), state)

    def end_opus_review(self, duration_seconds: float) -> None:
        """
        Opusレビューの実行を終了し、使用時間を累積加算する。
        """
        if not PHASE_STATE_PATH.exists():
            return

        state = safe_read_json(str(PHASE_STATE_PATH), {})
        
        # 実行時間の時間換算
        hours_used = duration_seconds / 3600.0
        
        # 累積
        state["opus_hours_used_this_week"] = state.get("opus_hours_used_this_week", 0.0) + hours_used
        state["opus_reviews_this_week"] = state.get("opus_reviews_this_week", 0) + 1
        state["last_opus_review"] = _now_iso()
        state["awaiting_opus"] = False

        # アトミック書き込み
        atomic_write_json(str(PHASE_STATE_PATH), state)
        logger.info(f"Opusレビュー完了。使用時間: {hours_used:.4f}時間 (累計: {state['opus_hours_used_this_week']:.4f}時間)")

    def verify_file(self, file_path: str) -> dict:
        """Verifier を使用して指定されたファイルの静的検証を行う"""
        verifier = CodeVerifier()
        return verifier.verify_static(file_path)

    def verify_test_suite(self, test_pattern: str) -> dict:
        """Verifier を使用して pytest スイートを実行し動的検証を行う"""
        verifier = CodeVerifier()
        return verifier.verify_dynamic(test_pattern)
