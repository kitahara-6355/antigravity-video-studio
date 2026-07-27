"""StatusMixin – ステータス生成・ETA計算・レポートのMixin.

orchestrator.py から抽出されたメソッド群。
OrchestrationHub が本 Mixin を継承することで、既存の self.xxx() 呼び出しが解決される。
"""

import json
import os
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from .hub_common import (
    logger, _read_json, _write_json, _now_iso, _safe_parse_iso,
    _append_jsonl, _read_jsonl, _get_flash_profile,
    FLASH_SESSION_PATH, FLASH_REPORTS_PATH, TASK_QUEUE_PATH,
    PHASE_STATE_PATH, OPUS_DIRECTIVE_PATH, ETA_STORE_PATH,
    USER_SCHEDULE_PATH, _BASE_DIR, _MEMORY_DIR, _PROJECT_ROOT,
    PHASE_ROADMAP, INBOX_DIR,
)
from .report_compressor import ReportCompressor
from .atomic_io import FileLock


class StatusMixin:
    """ステータス生成・ETA計算・レポートのMixin"""

    # ファイルパスから (機能名, ユーザー向け説明, 品質指標) を推定
    # 形式: pattern -> (機能名, ユーザー目線の説明, 憲法/UXストーリー参照)
    _DOMAIN_MAP = {
        "routers/smartcut":   ("動画自動編集",     "動画の不要部分を自動カットする機能",       "UXストーリー O-2"),
        "routers/":           ("API操作画面",      "ブラウザから操作する全機能の応答",         "UXストーリー O-1〜O-3"),
        "services/vector":    ("素材検索",         "過去動画や素材をAIで高速検索する機能",     "コンテンツ検索精度"),
        "services/":          ("バックエンド処理", "動画処理・変換等の裏側の共通処理",         "システム安定性"),
        "agents/strategist":  ("AI編集戦略",       "AIが動画構成を自動判断する頭脳部分",       "憲法§5（AI知性）"),
        "agents/orchestration":("自律改善エンジン","AIが自分自身を改善し続ける仕組み",         "憲法§26（無限改善）"),
        "agents/memory":      ("知識記憶",         "AIの学習結果・判断履歴を保存する仕組み",   "意思決定の証拠保全"),
        "branding/":          ("品質記録",         "動画品質の変遷を記録・追跡する仕組み",     "憲法§1（NHK品質）"),
        "phase0_preflight":   ("起動前チェック",   "動画処理を始める前の安全確認機能",         "パイプライン安全性"),
        "smartcut":           ("スマートカット",   "AIが動画の最適なカット位置を自動判定",     "UXストーリー O-2"),
        "wagamama":           ("わがままモード",   "ユーザーの細かい好みを反映する機能",       "UXストーリー O-4"),
        "production_preview": ("最終プレビュー",   "書き出し前に仕上がりを確認する機能",       "UXストーリー O-5"),
        "comment_analyzer":   ("コメント分析",     "視聴者の反応を自動で分析する機能",         "視聴者FB自動解析"),
        "thumbnail":          ("サムネイル",       "動画のサムネイル画像を自動生成する機能",   "UXストーリー O-6"),
        "history_manager":    ("操作履歴",         "過去の操作をやり直せるようにする機能",     "追跡可能性"),
        "legacy_production":  ("旧システム統合",   "古いコードを新しい仕組みに統合する作業",   "技術負債解消"),
        "test_":              ("品質テスト",       "機能が壊れていないか自動で確認する仕組み", "品質ゲート達成"),
        "conftest":           ("テスト基盤",       "自動テストを安定して実行する基盤",         "テスト安定化"),
        ".coveragerc":        ("計測設定",         "テスト網羅率の計測精度を上げる設定",       "計測精度向上"),
    }

    # (icon, label, user_effect, mission)
    _GROUP_LABELS = {
        "bug_hunter":  ("🔧", "バグ修正",         "不具合を修正し、動作が安定します",
                        "コード内の潜在バグを自動検出し、修正とテストを一括実施するサブエージェント"),
        "test_weaver": ("🧪", "テスト追加",       "自動テストが増え、将来の不具合を早期発見できます",
                        "テスト未カバーの機能を検出し、自動テストを新規作成するサブエージェント"),
        "edge_case":   ("🛡️", "エッジケース対策", "想定外の操作でもクラッシュしなくなります",
                        "異常入力や境界値など想定外の使い方に対するテストを追加するサブエージェント"),
        "refactor":    ("♻️", "リファクタリング", "コードが整理され、今後の機能追加が容易になります",
                        "複雑なコードを整理し、保守性を向上させるサブエージェント"),
        "performance": ("⚡", "パフォーマンス改善","処理速度が向上し、待ち時間が短縮されます",
                        "ボトルネックを検出し、処理速度を最適化するサブエージェント"),
        "tdr_cleanup": ("🧹", "技術負債解消",     "古い問題を解消し、システム全体の信頼性が向上します",
                        "技術負債台帳の未解消項目を自動修正するサブエージェント"),
    }

    def generate_flash_status(self) -> dict:
        """
        Flashが表示するシステムステータスの全データを計算済みで返す。
        
        Flashは自分で何も計算せず、この戻り値をテンプレートに流し込むだけ。
        アーカイブ判定ロジックも内蔵。
        
        Returns:
            dict: テンプレート埋め込み用の全フィールド
        """
        session = _read_json(FLASH_SESSION_PATH)
        queue = _read_json(TASK_QUEUE_PATH)
        state = _read_json(PHASE_STATE_PATH)
        tasks = queue.get("tasks", [])
        
        # バッチ内タスク状況
        batch_total = len(tasks)
        completed = sum(1 for t in tasks if t.get("status") in ("pass", "fail", "skip"))
        running = sum(1 for t in tasks if t.get("status") == "running")
        passed = sum(1 for t in tasks if t.get("status") == "pass")
        failed = sum(1 for t in tasks if t.get("status") == "fail")
        dispatched = completed + running
        
        # セッション累計
        session_tasks = session.get("tasks_completed_in_session", 0)
        session_batches = session.get("batches_in_session", 0)
        subagents_running = session.get("subagents_running", 0)
        
        # 稼働時間
        uptime_str = "不明"
        uptime_hours = 0.0
        started_at_str = session.get("session_started_at")
        if started_at_str:
            started_at = _safe_parse_iso(started_at_str)
            if started_at:
                elapsed = datetime.now(timezone.utc) - started_at
                hours = int(elapsed.total_seconds() // 3600)
                mins = int((elapsed.total_seconds() % 3600) // 60)
                uptime_str = f"{hours}h {mins}m"
                uptime_hours = elapsed.total_seconds() / 3600
        
        # 通算タスク数
        global_tasks = state.get("flash_tasks_total", 0)
        global_passed = state.get("flash_tasks_passed", 0)
        global_failed = state.get("flash_tasks_failed", 0)
        
        # 成功率
        total_done = passed + failed
        success_rate = int(passed / total_done * 100) if total_done > 0 else 100
        
        # Phase/Milestone
        phase = state.get("current_phase", "?")
        milestone = state.get("current_milestone", "?")
        batch_id = queue.get("current_batch_id", "N/A")
        # モードプロファイルからパラメータを取得
        profile = _get_flash_profile()
        batch_size = profile.get("batch_size", 6)
        context_pct_per_batch = profile.get("context_pct_per_batch", 4)
        ARCHIVE_BATCH_THRESHOLD = profile.get("archive_batches", 30)
        ARCHIVE_HOUR_THRESHOLD = profile.get("archive_hours", 5.0)
        
        # 残タスク推定（Phase内の残モジュール数から計算）
        remaining_tasks = "算出中"
        remaining_batches = "算出中"
        try:
            # 欠陥C修正: _get_available_modules()は blacklisted:set を1引数で受け取る
            bl_set = set(state.get("blacklisted_modules", []))
            available = self._get_available_modules(bl_set)
            remaining_count = len(available) if available else 0
            remaining_tasks = str(remaining_count)
            remaining_batches = str(max(1, remaining_count // batch_size)) if remaining_count > 0 else "0"
        except (TypeError, ValueError, KeyError, AttributeError, OSError, RuntimeError) as e:
            logger.warning("Failed to estimate remaining tasks: %s", e, exc_info=True)
        
        # コンテキスト消費率の推定（バッチ数ベース）
        # プロファイルの context_pct_per_batch を使用（初期推定）
        context_pct = min(100, int(session_batches * context_pct_per_batch))
        
        # --- アダプティブ・アーカイブ判定 ---
        # 層1: コンテキスト予測エンジン（主軸）
        ctx_history = session.get("context_pct_history", [])
        CONTEXT_TARGET = profile.get("context_target_pct", 70)
        CONTEXT_WARN = profile.get("context_warn_pct", 60)
        
        # 移動平均で次バッチ後のコンテキスト消費率を予測
        if len(ctx_history) >= 3:
            recent = ctx_history[-3:]
            deltas = [recent[i+1] - recent[i] for i in range(len(recent)-1)]
            avg_delta = sum(deltas) / len(deltas) if deltas else context_pct_per_batch
        elif len(ctx_history) >= 2:
            avg_delta = ctx_history[-1] - ctx_history[-2]
        else:
            avg_delta = context_pct_per_batch  # データ不足→固定推定フォールバック
        
        avg_delta = max(1, avg_delta)  # ゼロ除算防止
        estimated_next = context_pct + avg_delta
        remaining_batches_est = max(0, int((CONTEXT_TARGET - context_pct) / avg_delta))
        
        # 層2: ハードキャップ（安全弁）
        archive_reasons = []
        if session_batches >= ARCHIVE_BATCH_THRESHOLD:
            archive_reasons.append(f"ハードキャップ: {ARCHIVE_BATCH_THRESHOLD}バッチ到達")
        if uptime_hours >= ARCHIVE_HOUR_THRESHOLD:
            archive_reasons.append(f"ハードキャップ: {ARCHIVE_HOUR_THRESHOLD}時間経過")
        
        # 層1+層2の統合判定
        if archive_reasons:
            archive_suggestion = f"⚠️ アーカイブ推奨（{', '.join(archive_reasons)}）。完遂プロトコル準備を開始してください"
            archive_urgency = "warn"
        elif estimated_next >= CONTEXT_TARGET:
            archive_suggestion = (
                f"⚠️ コンテキスト予測 {estimated_next:.0f}% → {CONTEXT_TARGET}%超過見込み。"
                f" 現在 {context_pct}% / {session_batches}バッチ（Δ平均 {avg_delta:.1f}%/batch）"
            )
            archive_urgency = "warn"
        elif context_pct >= CONTEXT_WARN or estimated_next >= CONTEXT_WARN:
            archive_suggestion = (
                f"ℹ️ コンテキスト {context_pct}% — 残り推定 {remaining_batches_est}バッチ"
                f"（Δ平均 {avg_delta:.1f}%/batch）"
            )
            archive_urgency = "info"
        else:
            archive_suggestion = (
                f"✅ 継続稼働OK（ctx {context_pct}%、残推定 {remaining_batches_est}バッチ、"
                f"Δ平均 {avg_delta:.1f}%/batch）"
            )
            archive_urgency = "ok"
        
        # B2: ハングタスク検知
        hang_warnings = []
        now_utc = datetime.now(timezone.utc)
        for task in tasks:
            if task.get("status") == "running":
                started_at_str = task.get("started_at")
                if started_at_str:
                    started_at = _safe_parse_iso(started_at_str)
                    if started_at:
                        elapsed_sec = (now_utc - started_at).total_seconds()
                        elapsed_min = int(elapsed_sec / 60)
                        task_id = task.get("id", "?")
                        target_mod = task.get("target_module") or "?"
                        module = target_mod.split("/")[-1]
                        if elapsed_sec >= 600:  # 10分超
                            hang_warnings.append(f"   ⚠️ {task_id} ({module}) — {elapsed_min}分経過")
        
        hang_section = ""
        if hang_warnings:
            hang_section = (
                f"\n🚨 ハングタスク検知: {len(hang_warnings)}件 (10分超)\n"
                + "\n".join(hang_warnings)
                + f"\n   👉 manage_task → kill し、対応タスクを fail にせよ\n"
            )

        # 待機情報
        wait_info = ""
        if session.get("current_activity") == "waiting":
            wait_info = f"⏳ 待機中: {session.get('current_step', '次バッチ準備中')}"
        elif running > 0:
            wait_info = f"⏳ {running}タスク実行中... 完了を待機"
        
        return {
            "phase": phase,
            "milestone": milestone,
            "batch_id": batch_id,
            "batch_total": batch_total,
            "batch_completed": completed,
            "batch_running": running,
            "batch_passed": passed,
            "batch_failed": failed,
            "dispatched": dispatched,
            "subagents_running": subagents_running,
            "success_rate": success_rate,
            "session_tasks": session_tasks,
            "session_batches": session_batches,
            "uptime": uptime_str,
            "uptime_hours": round(uptime_hours, 2),
            "global_tasks": global_tasks,
            "global_passed": global_passed,
            "global_failed": global_failed,
            "remaining_tasks": remaining_tasks,
            "remaining_batches": remaining_batches,
            "batch_size": batch_size,
            "context_pct": context_pct,
            "archive_suggestion": archive_suggestion,
            "archive_urgency": archive_urgency,
            "wait_info": wait_info,
            "hang_warnings": hang_warnings,
            "has_hang": len(hang_warnings) > 0,
            # テンプレート用の完成済み文字列
            "formatted": (
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📡 Flash System Status — Batch {batch_id}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"{hang_section}\n"
                f"📍 Phase {phase} / {milestone}\n"
                f"🔄 バッチ {batch_id}: {completed}/{batch_total} タスク完了\n"
                f"👥 サブエージェント: {running}/{subagents_running} 稼働中\n"
                f"📊 成功率: {passed}/{total_done} ({success_rate}%)\n"
                f"\n"
                f"📈 セッション累計:\n"
                f"   タスク: {session_tasks}件 / {session_batches}バッチ\n"
                f"   稼働時間: {uptime_str}\n"
                f"   通算: {global_tasks}件（全セッション累計）\n"
                f"\n"
                f"⏳ セッション寿命:\n"
                f"   推定残バッチ: {remaining_batches}（Phase {phase} 残タスク {remaining_tasks} / batch_size {batch_size}）\n"
                f"   コンテキスト消費: ~{context_pct}%（推定）\n"
                f"   💡 {archive_suggestion}\n"
                f"\n"
                f"{wait_info}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            ),
        }


    def generate_status_summary(self) -> str:
        """
        現在の全体状況をMarkdown形式のサマリーとして返す。
        Opusがユーザーに報告するために使用する。
        """
        state = self.get_phase_state()
        queue_status = self.get_queue_status()
        messages = self.read_messages("opus", unread_only=True)
        metrics = state.get("metrics", {})
        flash_alive = self.check_flash_alive()
        
        urgent_msgs = [m for m in messages if m.get("priority") == "urgent"]
        
        if flash_alive["alive"]:
            flash_status = f"🟢 稼働中（最終HB: {flash_alive['minutes_since']}分前）"
        elif flash_alive["status"] == "ended":
            flash_status = f"🔴 終了 — {flash_alive.get('exit_reason', '不明')}"
        elif flash_alive["status"] == "stale":
            flash_status = f"⚠️ 応答なし（{flash_alive['minutes_since']}分前が最終）"
        else:
            flash_status = "⚪ 未起動"
        
        summary = f"""## 📊 自律実行ステータスサマリー

| 項目 | 値 |
|:---|:---|
| **Flash状態** | {flash_status} |
| **現在Phase** | Phase {state.get('current_phase', '?')} / {state.get('current_milestone', '?')} |
| **緊急停止** | {'🚨 YES — ' + state.get('stop_reason', '') if state.get('emergency_stop') else '✅ 正常稼働'} |
| **完了バッチ数** | {state.get('flash_batches_completed', 0)} |
| **タスク成功/失敗** | {state.get('flash_tasks_passed', 0)} / {state.get('flash_tasks_failed', 0)} |
| **カバレッジ** | {metrics.get('coverage_pct', 0)}% |
| **テスト数** | {metrics.get('test_count', 0)} |
| **CRITICAL負債** | {metrics.get('critical_debt', 0)}件 |
| **連続FAIL** | {state.get('flash_consecutive_failures', 0)} |
| **ブラックリスト** | {len(state.get('blacklisted_modules', []))}モジュール |

### キュー状況
- バッチID: `{queue_status.get('batch_id', 'N/A')}`
- 残タスク: {queue_status.get('status_counts', {}).get('pending', 0)}件

### 未読メッセージ
- 合計: {len(messages)}件 (うち緊急: {len(urgent_msgs)}件)
"""
        # Flash活動詳細
        if flash_alive.get("alive") or flash_alive.get("status") == "stale":
            summary += f"""
### Flash 活動詳細
- 現在のステップ: {flash_alive.get('current_step', '不明')}
- 活動種別: {flash_alive.get('current_activity', '不明')}
- 進捗率: {flash_alive.get('progress_pct', 0)}%
- サブエージェント: {flash_alive.get('subagents_running', 0)}稼働中
- ストールカウント: {flash_alive.get('stall_count', 0)}
"""
            recent_errors = flash_alive.get("recent_errors", [])
            if recent_errors:
                summary += "\n#### 直近エラー\n"
                for e in recent_errors[-3:]:
                    summary += f"- [{e.get('timestamp', '')}] {e.get('error', '')} (module: {e.get('module', 'N/A')})\n"

        # 緊急メッセージ
        if urgent_msgs:
            summary += "\n#### 🚨 緊急メッセージ\n"
            for m in urgent_msgs[:5]:
                summary += f"- [{m.get('from')}] {m.get('content')}\n"
        
        # 問題診断
        diagnosis = self.diagnose_flash_issues()
        if diagnosis["issues"]:
            summary += "\n### ⚠️ 問題診断\n"
            for issue in diagnosis["issues"]:
                icon = "🔴" if issue["severity"] == "critical" else "🟡" if issue["severity"] == "high" else "🟠"
                summary += f"- {icon} **{issue['type']}**: {issue['description']}\n"
                summary += f"  → 推奨: {issue['recommended_action']}\n"
        
        return summary

    def _compute_eta_and_next_check(self, now_dt: Optional[datetime] = None) -> dict:
        """処理完了予想時刻（ETA）と次回確認推奨時刻を計算する。"""
        if now_dt is not None:
            if not isinstance(now_dt, datetime):
                raise TypeError("now_dt must be a datetime object")
            if now_dt.tzinfo is None:
                now_dt = now_dt.replace(tzinfo=timezone.utc)
        else:
            now_dt = datetime.now(timezone.utc)

        jst = timezone(timedelta(hours=9))
        now_jst = now_dt.astimezone(jst)

        session = {}
        queue = {}
        state = {}
        user_schedule = {}

        try:
            session = _read_json(FLASH_SESSION_PATH)
        except Exception as e:
            logger.error(f"Error reading flash session: {e}")
        try:
            queue = _read_json(TASK_QUEUE_PATH)
        except Exception as e:
            logger.error(f"Error reading task queue: {e}")
        try:
            state = _read_json(PHASE_STATE_PATH)
        except Exception as e:
            logger.error(f"Error reading phase state: {e}")
        try:
            user_schedule = _read_json(USER_SCHEDULE_PATH)
        except Exception as e:
            logger.error(f"Error reading user schedule: {e}")

        tasks = queue.get("tasks", [])
        pending = sum(1 for t in tasks if t.get("status") == "pending")
        running = sum(1 for t in tasks if t.get("status") == "running")
        remaining = pending + running

        throughput_tph = 0.0
        if FLASH_REPORTS_PATH.exists():
            try:
                cutoff_1h = now_dt - timedelta(hours=1)
                tasks_1h = 0
                records = _read_jsonl(FLASH_REPORTS_PATH)
                for entry in records:
                    ts_str = entry.get("timestamp")
                    if ts_str:
                        ts = _safe_parse_iso(ts_str)
                        if ts and ts >= cutoff_1h:
                            r = entry.get("results", {})
                            if isinstance(r, dict):
                                try:
                                    passed = int(r.get("passed", 0))
                                except (ValueError, TypeError):
                                    passed = 0
                                try:
                                    failed = int(r.get("failed", 0))
                                except (ValueError, TypeError):
                                    failed = 0
                                tasks_1h += passed + failed
                if tasks_1h > 0:
                    elapsed_h = min(1.0, (now_dt - cutoff_1h).total_seconds() / 3600)
                    throughput_tph = tasks_1h / elapsed_h if elapsed_h > 0 else tasks_1h
            except Exception as e:
                logger.error(f"Error calculating throughput from reports: {e}")

        if throughput_tph == 0.0:
            completed = session.get("tasks_completed_in_session", 0)
            started_str = session.get("session_started_at")
            started = _safe_parse_iso(started_str) if started_str else None
            if completed > 0 and started:
                try:
                    session_hours = (now_dt - started).total_seconds() / 3600
                    if session_hours > 0:
                        throughput_tph = completed / session_hours
                except Exception as e:
                    logger.error(f"Error calculating session throughput fallback: {e}")

        result = {
            "eta_jst": None, "eta_minutes": None,
            "next_check_jst": None, "next_check_minutes": None,
            "reason": "", "drift_minutes": 0, "drift_reason": "",
            "throughput_tph": throughput_tph, "remaining": remaining,
        }

        status = session.get("status", "unknown")
        if status in ("stopped", "ended"):
            result["reason"] = "セッション完遂済み"
            result["next_check_jst"] = "今すぐ（新規セッション開設が必要）"
            result["next_check_minutes"] = 0
            return result

        if remaining == 0:
            result["reason"] = "残タスクなし（新バッチ生成 or 完遂待ち）"
            result["eta_minutes"] = 5
            eta_dt = now_dt + timedelta(minutes=5)
            result["eta_jst"] = eta_dt.astimezone(jst).strftime("%H:%M")
            next_dt = now_dt + timedelta(minutes=10)
            result["next_check_jst"] = next_dt.astimezone(jst).strftime("%H:%M")
            result["next_check_minutes"] = 10
            return result

        if throughput_tph <= 0:
            result["reason"] = "スループット計測不能（開始直後の可能性）"
            next_dt = now_dt + timedelta(minutes=15)
            result["next_check_jst"] = next_dt.astimezone(jst).strftime("%H:%M")
            result["next_check_minutes"] = 15
            try:
                profile = _get_flash_profile()
                context_target = profile.get("context_target_pct", 70)
                context_pct_per_batch = profile.get("context_pct_per_batch", 4)
                batch_size = profile.get("batch_size", 6)
            except Exception:
                context_target = 70
                context_pct_per_batch = 4
                batch_size = 6
            tasks_completed = session.get("tasks_completed_in_session", 0)
            context_pct = session.get("context_consumption_pct", 0)
            remaining_by_context = 0
            if context_pct > 0 and tasks_completed > 0:
                tasks_per_pct = tasks_completed / context_pct
                remaining_by_context = max(0, int((context_target - context_pct) * tasks_per_pct))
            else:
                remaining_by_context = max(0, int(context_target / max(1, context_pct_per_batch) * batch_size))
            result["session_remaining_tasks"] = remaining_by_context
            result["session_capacity_pct"] = context_pct
            result["session_eta_minutes"] = 0
            result["session_eta_jst"] = None
            result["recommended_return_jst"] = None
            result["recommended_return_reason"] = "データ不足により算出不可"
            return result

        eta_hours = remaining / throughput_tph
        eta_minutes = int(eta_hours * 60)
        eta_dt = now_dt + timedelta(minutes=eta_minutes)
        result["eta_minutes"] = eta_minutes
        result["eta_jst"] = eta_dt.astimezone(jst).strftime("%H:%M")
        result["reason"] = f"残{remaining}タスク / {throughput_tph:.1f}タスク/時"

        if eta_minutes > 30:
            buffer = max(10, eta_minutes // 6)
            next_minutes = eta_minutes - buffer
        elif eta_minutes > 10:
            next_minutes = eta_minutes - 5
        else:
            next_minutes = max(5, eta_minutes)
        next_dt = now_dt + timedelta(minutes=next_minutes)
        result["next_check_jst"] = next_dt.astimezone(jst).strftime("%H:%M")
        result["next_check_minutes"] = next_minutes

        try:
            prev_eta = _read_json(ETA_STORE_PATH)
            prev_eta_min = prev_eta.get("eta_minutes")
            prev_ts_str = prev_eta.get("timestamp")
            if prev_eta_min is not None and prev_ts_str:
                prev_ts = _safe_parse_iso(prev_ts_str)
                if prev_ts:
                    elapsed_since_prev = (now_dt - prev_ts).total_seconds() / 60
                    expected_remaining = prev_eta_min - elapsed_since_prev
                    drift = eta_minutes - expected_remaining
                    if abs(drift) > 5:
                        result["drift_minutes"] = int(drift)
                        if drift > 0:
                            reasons = []
                            if throughput_tph < prev_eta.get("throughput_tph", 0) * 0.8:
                                reasons.append("処理速度低下")
                            if remaining > prev_eta.get("remaining", 0):
                                reasons.append(f"新規タスク追加(+{remaining - prev_eta.get('remaining', 0)}件)")
                            if not reasons:
                                reasons.append("待機時間ロス")
                            result["drift_reason"] = " / ".join(reasons)
                        else:
                            result["drift_reason"] = "処理効率向上"
        except Exception as e:
            logger.error(f"Error tracking drift: {e}")

        try:
            profile = _get_flash_profile()
            context_target = profile.get("context_target_pct", 70)
            context_pct_per_batch = profile.get("context_pct_per_batch", 4)
            batch_size = profile.get("batch_size", 6)
        except Exception:
            context_target = 70
            context_pct_per_batch = 4
            batch_size = 6

        tasks_completed = session.get("tasks_completed_in_session", 0)
        context_pct = session.get("context_consumption_pct", 0)

        remaining_by_context = 0
        if context_pct > 0 and tasks_completed > 0:
            tasks_per_pct = tasks_completed / context_pct
            remaining_by_context = max(0, int((context_target - context_pct) * tasks_per_pct))
        else:
            remaining_by_context = max(0, int(context_target / max(1, context_pct_per_batch) * batch_size))

        session_remaining = remaining_by_context

        if throughput_tph > 0 and session_remaining > 0:
            session_eta_hours = session_remaining / throughput_tph
            session_eta_minutes = int(session_eta_hours * 60)
            session_eta_dt = now_dt + timedelta(minutes=session_eta_minutes)
            result["session_eta_minutes"] = session_eta_minutes
            result["session_eta_jst"] = session_eta_dt.astimezone(jst).strftime("%H:%M")
            result["session_remaining_tasks"] = session_remaining
            result["session_capacity_pct"] = context_pct

            eta_local = session_eta_dt.astimezone(jst)
            day_of_week = eta_local.weekday()
            if "weekday" in user_schedule:
                if day_of_week >= 5:
                    user_windows = user_schedule.get("weekend", {}).get("windows", [])
                else:
                    user_windows = user_schedule.get("weekday", {}).get("windows", [])
            else:
                user_windows = user_schedule.get("windows", [])
            eta_hhmm = eta_local.strftime("%H:%M")

            recommended = None
            recommended_label = ""
            if user_windows:
                best_window = None
                eta_in_window = False
                for w in user_windows:
                    if w["start"] <= eta_hhmm <= w["end"]:
                        best_window = w
                        eta_in_window = True
                        break
                    elif w["start"] > eta_hhmm:
                        best_window = w
                        break
                if not best_window:
                    best_window = user_windows[0]

                if eta_in_window:
                    if eta_local.minute <= 15:
                        rec_dt = eta_local.replace(minute=0, second=0, microsecond=0)
                    else:
                        rec_dt = eta_local.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                    recommended = rec_dt.strftime("%H:%M")
                    recommended_label = f"{best_window.get('label', '')}窓内"
                else:
                    recommended = best_window["start"]
                    recommended_label = best_window.get("label", "")

            if not recommended:
                if eta_local.minute <= 15:
                    recommended_dt = eta_local.replace(minute=0, second=0, microsecond=0)
                else:
                    recommended_dt = eta_local.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                recommended = recommended_dt.strftime("%H:%M")

            result["recommended_return_jst"] = recommended
            reason_parts = [f"セッションETA {result['session_eta_jst']}"]
            if recommended_label:
                reason_parts.append(f"→ {recommended} ({recommended_label})")
            else:
                reason_parts.append(f"→ {recommended}")
            result["recommended_return_reason"] = " ".join(reason_parts)
        else:
            result["session_eta_minutes"] = 0
            result["session_eta_jst"] = None
            result["session_remaining_tasks"] = session_remaining
            result["session_capacity_pct"] = context_pct
            result["recommended_return_jst"] = None
            result["recommended_return_reason"] = "データ不足により算出不可"

        try:
            eta_store = {
                "timestamp": now_dt.isoformat(),
                "eta_minutes": eta_minutes,
                "remaining": remaining,
                "throughput_tph": throughput_tph,
                "session_eta_minutes": result.get("session_eta_minutes", 0),
            }
            _write_json(ETA_STORE_PATH, eta_store)
        except Exception as e:
            logger.error(f"Error saving eta tracker: {e}")

        return result

    def get_user_intervention_forecast(self, now_dt: Optional[datetime] = None) -> str:
        """ユーザー介入見通しのマークダウンサマリーを自動生成して返す。"""
        if now_dt is not None:
            if not isinstance(now_dt, datetime):
                raise TypeError("now_dt must be a datetime object")
            if now_dt.tzinfo is None:
                now_dt = now_dt.replace(tzinfo=timezone.utc)
        else:
            now_dt = datetime.now(timezone.utc)

        jst = timezone(timedelta(hours=9))
        now_jst = now_dt.astimezone(jst)

        session = {}
        try:
            session = _read_json(FLASH_SESSION_PATH)
        except Exception as e:
            logger.error(f"Error reading flash session for forecast: {e}")

        try:
            eta = self._compute_eta_and_next_check(now_dt)
            self._last_eta = eta
        except Exception as e:
            logger.error(f"Error computing ETA for forecast: {e}")
            eta = {}

        tasks_completed = session.get("tasks_completed_in_session", 0)
        context_pct = session.get("context_consumption_pct", 0)

        session_remaining = eta.get("session_remaining_tasks", 0)
        session_eta_jst = eta.get("session_eta_jst")
        session_eta_minutes = eta.get("session_eta_minutes", 0)
        recommended_return_jst = eta.get("recommended_return_jst")
        recommended_return_reason = eta.get("recommended_return_reason", "データ不足により算出不可")

        session_eta_jst_str = session_eta_jst if session_eta_jst else "N/A"
        recommended_return_jst_str = recommended_return_jst if recommended_return_jst else "N/A"

        flash_status_str = session.get("status", "unknown")
        if flash_status_str == "ended" or session_remaining == 0:
            action_message = "完遂後、新規Flashプロンプトの貼り付けが必要になります"
        else:
            action_message = "状況に応じて進捗を確認してください"

        now_hhmm = now_jst.strftime("%H:%M")
        is_night = now_hhmm >= "22:00" or now_hhmm <= "06:30"

        night_mode_section = ""
        if is_night:
            night_mode_section = f"\n* **夜間モード（22:00以降の場合）**: 現在は夜間デッドタイムです。セッション残寿命は約{session_eta_minutes}分ですが、夜間は自動運転で進行します。"

        markdown = f"""---
### 🙋‍♂️ ユーザー介入見通し
* **現状**: Flash {tasks_completed}タスク完了 / コンテキスト{context_pct}% / セッション残容量{session_remaining}タスク
* **セッションETA**: {session_eta_jst_str} JST（約{session_eta_minutes}分後）
* **🪑 次回着席推奨: {recommended_return_jst_str} JST** — {recommended_return_reason}
  * {action_message}{night_mode_section}"""

        return markdown

    def _update_subagent_dashboard(self) -> None:
        """サブエージェント体制報告ダッシュボード README.md を自動更新する"""
        try:
            from .generate_subagent_reports import main as run_report_generator
            # テスト実行中で、かつレポートジェネレータがモックされていない場合はスキップ
            # (本番のダッシュボードファイルがテストダミーデータで汚染されるのを防止)
            import sys
            if "pytest" in sys.modules:
                is_real_generator = (
                    "generate_subagent_reports" in getattr(run_report_generator, "__module__", "")
                    and getattr(run_report_generator, "__name__", "") == "main"
                )
                if is_real_generator:
                    logger.info("Test execution detected. Skipping subagent dashboard auto-update to prevent pollution.")
                    return
            run_report_generator()
        except Exception as e:
            logger.error(f"Failed to auto-update subagent report dashboard: {e}")

    def generate_hourly_report(self) -> Path:
        """
        直近1時間の全バッチを集約した**詳細レポート**を受信トレイに生成する。
        Opus側のcronジョブから呼ばれる。
        """
        INBOX_DIR.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        from datetime import timezone as py_timezone, timedelta as py_timedelta
        jst = py_timezone(py_timedelta(hours=9))
        now_jst = datetime.now(jst)
        filename = f"hourly_report_{now_jst.strftime('%Y%m%d_%H%M')}_jst.md"
        filepath = INBOX_DIR / filename
        
        state = _read_json(PHASE_STATE_PATH)
        metrics = state.get("metrics", {})
        session = _read_json(FLASH_SESSION_PATH)
        reports = _read_jsonl(FLASH_REPORTS_PATH)
        queue = _read_json(TASK_QUEUE_PATH)
        
        # 直近1時間のレポートを抽出
        from datetime import timedelta
        one_hour_ago = (now - timedelta(hours=1)).isoformat(timespec="seconds")
        recent = [r for r in reports if r.get("timestamp", "") >= one_hour_ago]
        
        total_passed = sum(r.get("results", {}).get("passed", 0) for r in recent)
        total_failed = sum(r.get("results", {}).get("failed", 0) for r in recent)
        total_tasks = total_passed + total_failed
        # 完了タスクから成功率を計算（バッチレポートが0の場合はtask_queueから取得）
        completed_tasks_all = [t for t in queue.get("tasks", []) if t.get("status") in ("pass", "fail")]
        ct_passed = len([t for t in completed_tasks_all if t.get("status") == "pass"])
        ct_failed = len([t for t in completed_tasks_all if t.get("status") == "fail"])
        ct_total = ct_passed + ct_failed
        if total_tasks > 0:
            success_rate = round(total_passed / total_tasks * 100, 1)
        elif ct_total > 0:
            success_rate = round(ct_passed / ct_total * 100, 1)
            total_passed = ct_passed
            total_failed = ct_failed
            total_tasks = ct_total
        else:
            success_rate = 0
        
        # Flash状態
        alive = self.check_flash_alive()
        if alive.get("alive"):
            flash_status = f"🟢 稼働中（{alive.get('current_step', '')}）"
        elif alive.get("status") == "ended":
            flash_status = f"🔴 終了 — {alive.get('exit_reason', '')}"
        else:
            flash_status = f"⚠️ {alive.get('status', 'unknown')}"
        
        # Git log 詳細（--stat付き）
        git_log = ""
        git_log_stat = ""
        lock_path = _PROJECT_ROOT / ".git_lock"
        try:
            with FileLock(str(lock_path), timeout=30.0):
                result = subprocess.run(
                    ["git", "log", "--oneline", "--since=1.hour"],
                    capture_output=True, text=True, timeout=10,
                    cwd=str(_PROJECT_ROOT),
                    encoding="utf-8", errors="replace"
                )
                git_log = result.stdout.strip()
                result2 = subprocess.run(
                    ["git", "log", "--stat", "--since=1.hour", "--format=%h %ci %s"],
                    capture_output=True, text=True, timeout=10,
                    cwd=str(_PROJECT_ROOT),
                    encoding="utf-8", errors="replace"
                )
                git_log_stat = result2.stdout.strip()
        except Exception:
            git_log = "(取得失敗)"
        
        # git diff --stat（未コミット変更）
        git_uncommitted = ""
        try:
            with FileLock(str(lock_path), timeout=30.0):
                result3 = subprocess.run(
                    ["git", "diff", "--stat", "HEAD"],
                    capture_output=True, text=True, timeout=10,
                    cwd=str(_PROJECT_ROOT),
                    encoding="utf-8", errors="replace"
                )
                git_uncommitted = result3.stdout.strip()
        except Exception:
            pass
        
        # --- サブエージェント活動の集計 ---
        tasks = queue.get("tasks", [])
        completed_tasks = [t for t in tasks if t.get("status") in ("pass", "fail")]
        group_summary = {}
        task_details = []
        for t in completed_tasks:
            group = t.get("group", "unknown")
            status = t.get("status", "unknown")
            if group not in group_summary:
                group_summary[group] = {"pass": 0, "fail": 0}
            group_summary[group][status] = group_summary[group].get(status, 0) + 1
            report = t.get("report")
            module = t.get("target_module", "N/A") or "N/A"
            detail = {
                "id": t.get("id", ""),
                "group": group,
                "module": module,
                "status": status,
            }
            if isinstance(report, dict):
                msg = report.get("message") or report.get("error") or ""
                detail["message"] = str(msg)[:120]
                detail["changed_files"] = report.get("changed_files", [])
            task_details.append(detail)
        
        # Phaseゲート状況
        gate = self.check_phase_gate(state.get("current_phase", 5))
        
        total_tasks_in_batch = len(tasks)
        running_tasks = [t for t in tasks if t.get("status") == "pending"]
        passed_tasks = [t for t in completed_tasks if t.get("status") == "pass"]
        failed_tasks_all = [t for t in completed_tasks if t.get("status") == "fail"]
        
        # Gitコミット数（サブエージェントの成果物）
        commit_count = len([l for l in git_log.split("\n") if l.strip()]) if git_log and git_log != "(取得失敗)" else 0
        
        # サブエージェントの動的行動を検出
        dynamic_behaviors = []
        recent_errors = [e for e in session.get("recent_errors", []) if e.get("timestamp", "") >= one_hour_ago]
        if recent_errors:
            rate_limit_errors = [e for e in recent_errors if "429" in str(e.get("error", "")) or "capacity" in str(e.get("error", "")).lower()]
            other_errors = [e for e in recent_errors if e not in rate_limit_errors]
            if rate_limit_errors:
                dynamic_behaviors.append(f"🔄 APIレート制限 {len(rate_limit_errors)}回 → 自動リトライで復旧")
            if other_errors:
                dynamic_behaviors.append(f"⚠️ エラー {len(other_errors)}件 → 自動検知・報告済み")
        
        if alive.get("current_activity") == "phase_advanced":
            dynamic_behaviors.append(f"🎉 Phase自動進行 — 品質ゲート通過を検知し次Phaseに移行")
        
        batches_completed = session.get("batches_in_session", 0)
        if batches_completed > 1:
            dynamic_behaviors.append(f"🔁 {batches_completed}バッチを連続処理（自動ループ稼働中）")
        
        # --- 全体まとめ + ロードマップ図 + 注目ポイント ---
        task_summaries = self._extract_task_summaries_from_git(git_log_stat, state)
        
        # 重複排除後に5件未満なら過去コミットに拡張
        seen_keys = set()
        unique_summaries = []
        for ts in task_summaries:
            key = ts['domain_name']
            if key not in seen_keys:
                seen_keys.add(key)
                unique_summaries.append(ts)
        
        if len(unique_summaries) < 5:
            try:
                with FileLock(str(lock_path), timeout=30.0):
                    result_ext = subprocess.run(
                        ["git", "log", "--stat", "-n", "30", "--format=%h %ci %s"],
                        capture_output=True, text=True, timeout=10,
                        cwd=str(_PROJECT_ROOT),
                        encoding="utf-8", errors="replace"
                    )
                    extended_summaries = self._extract_task_summaries_from_git(
                        result_ext.stdout.strip(), state
                    )
                for ts in extended_summaries:
                    key = ts['domain_name']
                    if key not in seen_keys:
                        seen_keys.add(key)
                        unique_summaries.append(ts)
                    if len(unique_summaries) >= 5:
                        break
            except Exception:
                pass
        
        task_summaries = unique_summaries
        failed_tasks = [d for d in task_details if d["status"] == "fail"]
        routine_count = len(task_details) - len(failed_tasks)
        
        # --- レポート本文の組み立て ---
        content = self._build_hourly_agent_activity(
            now_jst, state, metrics, flash_status, total_tasks_in_batch,
            passed_tasks, failed_tasks_all, running_tasks, commit_count,
            dynamic_behaviors
        )
        
        content += self._build_hourly_focus_points(
            alive, failed_tasks, completed_tasks, task_summaries, total_tasks,
            success_rate, total_failed, state, gate, group_summary, total_passed
        )
        
        content += self._build_hourly_subagent_summary(
            group_summary, failed_tasks, routine_count, recent, gate,
            git_log_stat, git_log, git_uncommitted, session, now, state
        )
        
        with open(filepath, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        # ダッシュボード自動更新
        self._update_subagent_dashboard()
        return filepath

    def _build_hourly_agent_activity(self, now_jst: datetime, state: dict, metrics: dict,
                                     flash_status: str, total_tasks_in_batch: int,
                                     passed_tasks: list, failed_tasks_all: list,
                                     running_tasks: list, commit_count: int,
                                     dynamic_behaviors: list) -> str:
        """ロボットサブエージェント活動セクションのマークダウンを構築する"""
        content = f"""# 📊 1時間セッションレポート — {now_jst.strftime('%Y-%m-%d %H:%M')} JST

> **Phase {state.get('current_phase', '?')}** / {state.get('current_milestone', '?')} | Flash: {flash_status}

---

## 🤖 サブエージェント活動

| 指標 | 値 |
|:---|:---|
| **バッチ内タスク総数** | {total_tasks_in_batch} |
| **完了サブエージェント** | ✅ {len(passed_tasks)} PASS / ❌ {len(failed_tasks_all)} FAIL |
| **実行中サブエージェント** | 🔄 {len(running_tasks)} |
| **Gitコミット数** | 📝 {commit_count}件（サブエージェントの成果物） |
| **現在Phase** | Phase {state.get('current_phase', '?')} / {state.get('current_milestone', '?')} |
| **カバレッジ** | {metrics.get('coverage_pct', 0)}% / テスト {metrics.get('test_count', 0)}件 |

"""
        if dynamic_behaviors:
            content += "### ⚡ サブエージェントの動的行動\n\n"
            for db in dynamic_behaviors:
                content += f"- {db}\n"
            content += "\n"
        return content

    def _build_hourly_focus_points(self, alive: dict, failed_tasks: list, completed_tasks: list,
                                   task_summaries: list, total_tasks: int, success_rate: float,
                                   total_failed: int, state: dict, gate: dict, group_summary: dict,
                                   total_passed: int) -> str:
        """注目ポイントおよびまとめ、ロードマップマークダウンを構築する"""
        content = ""
        # --- 全体まとめ3行 ---
        content += "## 📋 この1時間のまとめ\n\n"
        content += self._generate_executive_summary(
            task_summaries, failed_tasks, group_summary,
            total_passed, total_failed, success_rate, state, gate, alive
        )
        content += "\n"
        
        # --- ロードマップ位置図 ---
        content += "## 🗺️ ロードマップ上の位置\n\n"
        content += self._generate_roadmap_mermaid(state, task_summaries)
        content += "\n"
        
        # --- 注目ポイント詳細 ---
        content += "## 🔔 注目ポイント\n\n"
        
        if alive.get("current_activity") == "phase_advanced":
            content += f"> 🎉 **Phase進行**: {alive.get('current_step', '')}\n\n"
        
        if failed_tasks:
            # ReportCompressorでクラスタリング
            compressor = ReportCompressor()
            summary = compressor.compress(completed_tasks)
            clustered = summary.get("clustered_errors", [])
            for ce in clustered[:3]:
                module_name = ce['module'].split('/')[-1] if ce.get('module') else '不明'
                content += (
                    f"### ❌ 「{module_name}」FAIL (件数: {ce['count']}回)\n"
                    f"**エラー概要**: {ce['error']}\n"
                    f"**ユーザーへの影響**: この機能に関連する処理が不安定な可能性あり。Opus層で原因調査を自動実行\n\n"
                )
        
        if task_summaries:
            for ts in task_summaries:
                content += (
                    f"### {ts['icon']} {ts['agent_id']}\n"
                    f"**役割**: {ts['domain_name']}\n"
                    f"**稼働時間**: {ts['duration']}\n"
                    f"**ユーザーへの効果**: {ts['user_impact']}\n\n"
                )
        elif not failed_tasks:
            if total_tasks > 0:
                content += "> ✅ **順調** — 全タスクPASS、異常なし\n\n"
            else:
                content += "> ⏸️ **この1時間のバッチ完了なし** — 実行中または待機中\n\n"
        
        if state.get("blacklisted_modules"):
            content += f"> 🚫 **ブラックリスト**: {len(state['blacklisted_modules'])}モジュール\n\n"
        if gate and not gate.get("all_passed"):
            failed_conds = [c for c, v in gate.get("conditions", {}).items() if not v]
            content += f"> 🚧 **Phaseゲート未達**: {', '.join(failed_conds)}\n\n"
        if total_tasks > 0 and success_rate < 100:
            content += f"> 📉 **成功率低下**: {success_rate}%（{total_failed}件失敗）\n\n"
            
        return content

    def _build_hourly_subagent_summary(self, group_summary: dict, important_tasks: list,
                                       routine_count: int, recent: list, gate: dict,
                                       git_log_stat: str, git_log: str, git_uncommitted: str,
                                       session: dict, now: datetime, state: dict) -> str:
        """サブエージェント別成果、要対応タスク、Git詳細などのマークダウンを構築する"""
        content = ""
        # サブエージェント別成果サマリー
        if group_summary:
            content += "## 🤖 サブエージェント別成果\n\n"
            content += "| サブエージェント | 目的 | ✅ | ❌ | 成果 |\n|:---|:---|:---|:---|:---|\n"
            for group, counts in sorted(group_summary.items()):
                g_info = self._GROUP_LABELS.get(group, ("📦", "タスク", "", "汎用タスク"))
                p = counts.get("pass", 0)
                f = counts.get("fail", 0)
                mission_short = g_info[3][:20] + "…" if len(g_info[3]) > 20 else g_info[3]
                result_icon = "✅ 全成功" if f == 0 else f"⚠️ {f}件失敗"
                content += f"| **{group}** | {mission_short} | {p} | {f} | {result_icon} |\n"
            content += "\n"
        
        # 影響の大きいタスクのみ詳細表示（FAIL / プロダクション変更あり）
        if important_tasks:
            content += "## ⚡ 要対応タスク\n\n"
            content += "| ID | グループ | 対象モジュール | 結果 | エラー内容 |\n|:---|:---|:---|:---|:---|\n"
            for d in important_tasks[:15]:
                module_short = str(d["module"]).split("/")[-1] if d["module"] != "N/A" else "N/A"
                msg = d.get("message", "（報告なし）")[:60]
                content += f"| `{d['id'][-12:]}` | {d['group']} | `{module_short}` | ❌ | {msg} |\n"
            content += "\n"
        
        if routine_count > 0:
            content += f"> ✅ 他 {routine_count} 件のタスクは全て PASS\n\n"
        
        # バッチ別サマリー
        if recent:
            content += "## バッチ別結果\n\n"
            content += "| バッチID | 成功 | 失敗 | 変更ファイル数 | 時刻 |\n|:---|:---|:---|:---|:---|\n"
            for r in recent:
                res = r.get("results", {})
                diff = r.get("git_diff_summary", {})
                content += (
                    f"| `{r.get('batch_id', 'N/A')}` "
                    f"| {res.get('passed', 0)} "
                    f"| {res.get('failed', 0)} "
                    f"| {diff.get('files_changed', 0)} "
                    f"| {r.get('timestamp', '')[:16]} |\n"
                )
            content += "\n"
        
        # Phaseゲート達成状況
        content += "## Phaseゲート達成状況\n\n"
        content += f"| 条件 | 状態 |\n|:---|:---|\n"
        for cond, passed in gate.get("conditions", {}).items():
            icon = "✅" if passed else "❌"
            content += f"| {cond} | {icon} |\n"
        content += f"\n**全条件通過**: {'✅ はい' if gate.get('all_passed') else '❌ いいえ'}\n\n"
        
        # Gitコミット詳細（折りたたみ）
        if git_log_stat:
            content += "<details>\n<summary>📝 Gitコミット詳細（直近1時間）— クリックで展開</summary>\n\n"
            content += f"```\n{git_log_stat[:3000]}\n```\n\n</details>\n\n"
        elif git_log:
            content += "<details>\n<summary>📝 Gitコミット（直近1時間）— クリックで展開</summary>\n\n"
            content += f"```\n{git_log}\n```\n\n</details>\n\n"
        
        # 未コミット変更（折りたたみ）
        if git_uncommitted:
            content += "<details>\n<summary>📂 未コミット変更 — クリックで展開</summary>\n\n"
            content += f"```\n{git_uncommitted[:2000]}\n```\n\n</details>\n\n"
        
        # エラー詳細（直近24時間以内のエラーのみを最大5件表示）
        twenty_four_hours_ago = (now - timedelta(hours=24)).isoformat(timespec="seconds")
        recent_errors_24h = [e for e in session.get("recent_errors", []) if e.get("timestamp", "") >= twenty_four_hours_ago]
        if recent_errors_24h:
            content += "## 直近エラー詳細\n\n"
            for e in recent_errors_24h[-5:]:
                content += (
                    f"### {e.get('timestamp', '')[:16]} — `{e.get('module', 'N/A')}`\n\n"
                    f"```\n{e.get('error', '')[:500]}\n```\n\n"
                )
        
        # 問題診断
        diagnosis = self.diagnose_flash_issues()
        if diagnosis["issues"]:
            content += "## ⚠️ 検出された問題\n\n"
            for issue in diagnosis["issues"]:
                severity_icon = {"critical": "🔴", "high": "🟡", "medium": "🔵"}.get(issue["severity"], "⚪")
                content += (
                    f"### {severity_icon} {issue['type']} ({issue['severity']})\n\n"
                    f"{issue['description']}\n\n"
                    f"**推奨アクション**: {issue['recommended_action']}\n\n"
                )
        
        content += f"""---
*自動生成 by OrchestrationHub | Phase {state.get('current_phase', '?')} | {now.strftime('%Y-%m-%d %H:%M')} UTC*
"""
        return content

    def _generate_executive_summary(self, task_summaries, failed_tasks,
                                     group_summary, passed, failed,
                                     success_rate, state, gate, alive) -> str:
        """全タスクの3行総括を生成する"""
        phase = state.get('current_phase', 0)
        if not isinstance(phase, (int, float)):
            phase = 0
        milestone = state.get('current_milestone', '?')
        
        # 機能領域の集計
        domains_touched = set()
        for ts in task_summaries:
            domains_touched.add(ts.get("domain_name", "一般"))
        domains_str = "・".join(list(domains_touched)[:4]) if domains_touched else "各機能"
        
        # グループ別の件数
        group_counts = []
        for g, counts in sorted(group_summary.items()):
            g_info = self._GROUP_LABELS.get(g, ("📦", "タスク", "", ""))
            label = g_info[1]
            total = counts.get("pass", 0) + counts.get("fail", 0)
            group_counts.append(f"{label}{total}件")
        groups_str = "、".join(group_counts) if group_counts else "タスクなし"
        
        # ゲート状態
        gate_str = "全条件達成済み ✅" if gate.get("all_passed") else "一部未達 🚧"
        
        lines = []
        if alive.get("current_activity") == "phase_advanced":
            lines.append(f"🎉 **Phase {phase-1} が完了し、Phase {phase} に進行しました。**")
        
        lines.append(
            f"**{domains_str}** を中心に {groups_str} を実施。"
            f"成功率 {success_rate}%。"
        )
        
        if failed_tasks:
            lines.append(f"❌ {len(failed_tasks)}件の失敗あり。原因調査を自動実行中。")
        else:
            lines.append(f"全タスク正常完了。品質ゲートは{gate_str}。")
        
        lines.append(
            f"Phase {phase}（{milestone}）はロードマップの"
            f"「{'品質卓越' if phase <= 6 else '機能拡張' if phase <= 12 else '最適化' if phase <= 16 else '完成' if phase <= 20 else '自走運用'}」"
            f"段階を進行中。"
        )
        
        return "\n".join(f"> {l}" for l in lines) + "\n"

    def _generate_roadmap_mermaid(self, state, task_summaries) -> str:
        """テキストベースでロードマップ上の現在位置を図示する"""
        phase = state.get('current_phase', 5)
        
        phase_groups = [
            ("foundation", "基盤構築",   5,  5),
            ("quality",    "品質卓越",   6,  6),
            ("stability",  "安定化",     7,  8),
            ("expansion",  "機能拡張",   9, 12),
            ("optimize",   "最適化",    13, 16),
            ("completion", "完成",      17, 20),
            ("evolution",  "自走運用",  21, 22),
        ]
        
        # プログレスバー生成
        total_phases = 18  # Phase 5〜22
        completed = max(0, phase - 5)
        pct = round(completed / total_phases * 100)
        pct = min(100, pct)
        bar_len = 20
        filled = round(bar_len * completed / total_phases)
        filled = min(bar_len, filled)
        bar = "█" * filled + "░" * (bar_len - filled)
        
        result = f"```\n{bar}  {pct}%  (Phase {phase} / 22)\n```\n\n"
        
        # 各段階の状態を表示
        result += "| 段階 | Phase | 状態 |\n|:---|:---|:---|\n"
        for _, label, start, end, in phase_groups:
            phase_range = f"P{start}" if start == end else f"P{start}-{end}"
            if phase > end:
                result += f"| {label} | {phase_range} | ✅ 完了 |\n"
            elif start <= phase <= end:
                result += f"| **▶ {label}** | **{phase_range}** | **🔶 進行中** |\n"
            else:
                result += f"| {label} | {phase_range} | ⬜ 未着手 |\n"
        result += "\n"
        
        # 今回の作業が触れた機能領域
        if task_summaries:
            domains = set(ts.get("domain_name", "") for ts in task_summaries if ts.get("domain_name"))
            if domains:
                result += f"> 📍 今回の作業領域: **{'、'.join(domains)}**\n"
        
        return result
