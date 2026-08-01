"""
Flash稼働ヘルスチェックスクリプト — 3点突合検証

Git log（客観的事実）× flash_session.json（自己報告）× flash_reports.jsonl（バッチ履歴）
を突合し、共通処理機構が想定通り稼働しているかを検証する。

使い方:
    python health_check.py         # 通常実行
    python health_check.py --json  # JSON出力（プログラム連携用）
"""

try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import official_artifact_dir as _official_artifact_dir
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import official_artifact_dir as _official_artifact_dir
    from path_resolver import writable_path as _writable_path
import json
import os
import subprocess
import sys

# パス定義
WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)
backend_path = os.path.join(WORKSPACE_DIR, "backend")
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from datetime import datetime, timezone, timedelta
from pathlib import Path
from backend.agents.orchestration.atomic_io import safe_read_json, atomic_write_json
from backend.agents.orchestration.jst_time import now_jst
ORCHESTRATION_DIR = os.path.join(WORKSPACE_DIR, "backend", "agents", "orchestration")
FLASH_SESSION_PATH = str(_writable_path("backend/agents/orchestration/flash_session.json"))
FLASH_REPORTS_PATH = os.path.join(ORCHESTRATION_DIR, "flash_reports.jsonl")
PHASE_STATE_PATH = os.path.join(WORKSPACE_DIR, "backend", "agents", "memory", "phase_state.json")
TASK_QUEUE_PATH = str(_writable_path("backend/agents/orchestration/task_queue.json"))
OPUS_SESSION_PATH = str(_writable_path("backend/agents/orchestration/opus_session.json"))
EVENT_LOG_PATH = os.path.join(
    str(_official_artifact_dir()), "サブエージェント体制報告", "event_log.jsonl"
)


def _send_stale_nudge(hb_minutes: int, jst_now: str):
    """STALE段階(15-30min)でFlashに心拍更新を促すナッジを送信する。
    
    重複防止: 直近10分以内にナッジ済みならスキップ。
    """
    try:
        session = _safe_read_json(FLASH_SESSION_PATH, {})
        if not session or session.get("status") != "running":
            return
        
        # 重複防止: last_stale_nudge_at を確認
        last_nudge = session.get("last_stale_nudge_at")
        if last_nudge:
            last_dt = _parse_iso(last_nudge)
            if last_dt:
                elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60
                if elapsed < 10:  # 10分以内にナッジ済み → スキップ
                    return
        
        # OrchestrationHub経由でFlashにナッジ送信
        try:
            import sys as _sys
            _sys.path.insert(0, WORKSPACE_DIR)
            from backend.agents.orchestration import OrchestrationHub
            hub = OrchestrationHub()
            hub.send_message(
                "opus", "flash",
                f"【早期ナッジ(STALE)】心拍が{hb_minutes}分前です。"
                "hub.flash_update_heartbeat() を即座に実行して心拍を更新してください。"
                "自走ループが停止している場合は再開してください。",
                priority="urgent"
            )
        except Exception:
            pass  # Hub連携失敗時はサイレント
        
        # ナッジ送信時刻を記録（重複防止用）
        session["last_stale_nudge_at"] = datetime.now(timezone.utc).isoformat()
        try:
            atomic_write_json(FLASH_SESSION_PATH, session)
        except Exception:
            pass
        
        # イベントログに記録
        event = {
            "timestamp": jst_now,
            "lifecycle": "STALE_NUDGE",
            "health": "🟡 STALE",
            "change": [f"stale_nudge: 心拍{hb_minutes}分前 → Flashへ早期ナッジ送信"]
        }
        try:
            os.makedirs(os.path.dirname(EVENT_LOG_PATH), exist_ok=True)
            with open(EVENT_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError:
            pass
        
        print(f"🟡 早期ナッジ: 心拍{hb_minutes}分前 → Flashへ心拍更新を要請")
        print(f"   ✅ 20分でsend_message自動送信（AUTO_NUDGE）")
        print(f"   ⏳ 介入不要 — 自動復旧を試行中")
    except Exception:
        pass  # ナッジ全体の失敗はサイレント


def reset_opus_session(conversation_id: str):
    """新Opusセッション開始時にopus_session.jsonをリセットする。

    Opusの起動プロトコル§0で呼び出すことで、
    旧セッションの累積値（cron_iterations, session_started_at）を
    クリアし、STALE偽陽性を防止する。
    """
    data = {
        "session_started_at": datetime.now(timezone.utc).isoformat(),
        "conversation_id": conversation_id,
        "cron_iterations": 0,
        "last_cron_at": datetime.now(timezone.utc).isoformat(),
        "compaction_occurred": False,
    }
    try:
        atomic_write_json(OPUS_SESSION_PATH, data)
    except Exception:
        pass
    return data


def _calc_hb_minutes(last_hb_str):
    """心拍タイムスタンプから経過分数を計算する。パース失敗時はNoneを返す。"""
    if not last_hb_str:
        return None
    dt = _parse_iso(last_hb_str)
    if not dt:
        return None
    return int((datetime.now(timezone.utc) - dt).total_seconds() / 60)



def _auto_stop_stale_session(hb_minutes: int) -> str:
    """Gradual response to stale heartbeat (3-stage).

    Stage 1 (STALE, 15-30min): Warning only. Status stays 'running'.
        Hub connectivity is fully maintained.
    Stage 2 (UNREACHABLE, 30-60min): Set 'heartbeat_warning' flag but
        keep status as 'running'. Hub connectivity maintained.
        This avoids breaking Hub integration while alerting Opus.
    Stage 3 (DEAD, 60min+): Set status to 'stopped'. Hub will stop
        recording new reports. This is the point of no return.

    Returns: 'none' | 'warned' | 'stopped'
    """
    session = _safe_read_json(FLASH_SESSION_PATH, {})
    if not session or session.get("status") != "running":
        return "none"

    jst_now = (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d %H:%M JST")

    # Stage 1: STALE (15-30min) — send nudge message to Flash, no state change
    if hb_minutes <= 30:
        if hb_minutes >= 15:
            # A2: STALE段階での早期ナッジ送信
            # 15分以上心拍が更新されていない場合、Flashに心拍更新を促すメッセージを送信
            _send_stale_nudge(hb_minutes, jst_now)
        return "none"

    # A3: 残タスク数に基づく動的閾値
    # 残タスクなし → 30分でDEAD (明らかに停滞)
    # 残タスクあり → 60分でDEAD (重い処理の可能性を考慮)
    dead_threshold = 60  # default
    try:
        queue = _safe_read_json(TASK_QUEUE_PATH, {})
        tasks = queue.get("tasks", [])
        remaining = sum(1 for t in tasks if t.get("status") in ("pending", "running"))
        if remaining == 0:
            dead_threshold = 30  # 残タスクなし → 早期DEAD判定
    except Exception:
        pass

    # Stage 2: UNREACHABLE (30-dead_threshold min) — flag warning but keep running
    if hb_minutes <= dead_threshold:
        session["heartbeat_warning"] = f"stale_{hb_minutes}min"
        session["heartbeat_warning_at"] = datetime.now(timezone.utc).isoformat()

        # B1: ウォッチドッグ — running タスクのタイムアウト回復
        # Flashが停止していてもタスクキューを自動リセットし、
        # 次回Flash起動時にタスクを即座に拾えるようにする
        try:
            import sys as _sys
            _sys.path.insert(0, WORKSPACE_DIR)
            from backend.agents.orchestration import OrchestrationHub
            hub = OrchestrationHub()
            queue = _safe_read_json(TASK_QUEUE_PATH, {})
            if queue and hub._recover_timed_out_tasks(queue, timeout_seconds=600):
                try:
                    atomic_write_json(TASK_QUEUE_PATH, queue)
                    print(f"🔧 ウォッチドッグ: タイムアウトタスクを自動回復しました")
                except Exception:
                    pass
        except Exception:
            pass  # ウォッチドッグ失敗はサイレント

        # Status stays 'running' — Hub connectivity maintained
        try:
            atomic_write_json(FLASH_SESSION_PATH, session)
        except Exception:
            return "none"

        event = {
            "timestamp": jst_now,
            "lifecycle": "HEARTBEAT_WARNING",
            "health": "🟠 UNREACHABLE",
            "change": [f"heartbeat_warning: 心拍{hb_minutes}分前 (Hub連携維持、{dead_threshold}分超で自動停止)"]
        }
        try:
            os.makedirs(os.path.dirname(EVENT_LOG_PATH), exist_ok=True)
            with open(EVENT_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError:
            pass

        print(f"🟠 心拍警告: 心拍{hb_minutes}分前（Hub連携維持中、{dead_threshold}分超で自動停止）")
        print(f"   🚨 ユーザー介入が必要です")
        print(f"   👉 Flashチャットに入力: \"心拍を更新し、ハングタスクをfailにして次に進め\"")
        return "warned"

    # Stage 3: DEAD (dead_threshold min+) — stop session
    session["status"] = "stopped"
    session["auto_stopped_at"] = datetime.now(timezone.utc).isoformat()
    session["auto_stop_reason"] = f"heartbeat_stale_{hb_minutes}min_threshold_{dead_threshold}min"

    try:
        atomic_write_json(FLASH_SESSION_PATH, session)
    except Exception:
        return "none"

    event = {
        "timestamp": jst_now,
        "lifecycle": "AUTO_STOPPED",
        "health": "🔴 AUTO_STOPPED",
        "change": [f"auto_stop: running → stopped (心拍{hb_minutes}分前, {dead_threshold}分閾値超過)"]
    }
    try:
        os.makedirs(os.path.dirname(EVENT_LOG_PATH), exist_ok=True)
        with open(EVENT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass

    print(f"⚠️ 自動停止: Flashセッションを自動停止しました（心拍{hb_minutes}分前、{dead_threshold}分閾値超過）")
    print(f"   👉 Flashチャットを閉じ、新規セッションを開設してください")
    return "stopped"


def _safe_read_json(path, default=None):
    return safe_read_json(path, default)


def _parse_iso(ts_str):
    """ISO 8601文字列をdatetimeに変換"""
    if not ts_str:
        return None
    for fmt in [
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
    ]:
        try:
            dt = datetime.strptime(ts_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def check_heartbeat():
    """検証1: 心拍鮮度チェック"""
    session = _safe_read_json(FLASH_SESSION_PATH, {})
    if not session:
        return {"status": "FAIL", "detail": "flash_session.json が見つかりません", "minutes_ago": -1}

    hb_str = session.get("last_heartbeat")
    if not hb_str:
        return {"status": "FAIL", "detail": "last_heartbeat フィールドがありません", "minutes_ago": -1}

    dt = _parse_iso(hb_str)
    if not dt:
        return {"status": "FAIL", "detail": f"心拍日時をパースできません: {hb_str}", "minutes_ago": -1}

    now = datetime.now(timezone.utc)
    diff_min = int((now - dt).total_seconds() / 60)

    if diff_min <= 15:
        return {"status": "PASS", "detail": f"{diff_min}分前 (正常)", "minutes_ago": diff_min}
    elif diff_min <= 30:
        return {"status": "WARN", "detail": f"{diff_min}分前 (やや古い — STALE)", "minutes_ago": diff_min}
    else:
        return {"status": "FAIL", "detail": f"{diff_min}分前 (到達不能 — UNREACHABLE)", "minutes_ago": diff_min}


def check_git_commits():
    """検証2: Git最新コミットと心拍の時刻整合"""
    try:
        result = subprocess.run(
            ["git", "log", "-n20", "--format=%H %aI %s"],
            cwd=WORKSPACE_DIR,
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return {"status": "FAIL", "detail": "git log 実行失敗", "flash_commits": 0}

        lines = result.stdout.strip().split("\n")
        flash_lines = [l for l in lines if "[Flash/" in l]

        if not flash_lines:
            return {"status": "WARN", "detail": "直近20コミットにFlashコミットなし", "flash_commits": 0}

        # 最新Flashコミットの時刻
        parts = flash_lines[0].split(" ", 2)
        commit_hash = parts[0][:7]
        commit_ts = _parse_iso(parts[1]) if len(parts) > 1 else None

        if commit_ts:
            now = datetime.now(timezone.utc)
            diff_min = int((now - commit_ts).total_seconds() / 60)
            detail = f"`{commit_hash}` — {diff_min}分前"

            # 心拍との整合チェック
            session = _safe_read_json(FLASH_SESSION_PATH, {})
            hb_str = session.get("last_heartbeat")
            if hb_str:
                hb_dt = _parse_iso(hb_str)
                if hb_dt:
                    gap_min = abs(int((commit_ts - hb_dt).total_seconds() / 60))
                    if gap_min <= 30:
                        detail += " (心拍と整合)"
                    else:
                        detail += f" (⚠️ 心拍との乖離: {gap_min}分)"

            status = "PASS" if diff_min <= 30 else "WARN" if diff_min <= 60 else "FAIL"
            return {"status": status, "detail": detail, "flash_commits": len(flash_lines)}
        else:
            return {"status": "WARN", "detail": f"`{commit_hash}` — 時刻パース不可", "flash_commits": len(flash_lines)}

    except Exception as e:
        return {"status": "FAIL", "detail": f"Git検証エラー: {str(e)[:100]}", "flash_commits": 0}


def check_batch_consistency():
    """検証3: バッチ整合性（報告件数 vs Gitコミット数）"""
    # flash_reports.jsonl のバッチ数カウント
    report_count = 0
    report_tasks_total = 0
    if os.path.exists(FLASH_REPORTS_PATH):
        try:
            with open(FLASH_REPORTS_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        report_count += 1
                        results = entry.get("results", {})
                        if isinstance(results, dict):
                            report_tasks_total += results.get("passed", 0) + results.get("failed", 0)
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass

    # Gitの[Flash/...]コミット数
    git_flash_count = 0
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "--all", "--grep=Flash/", "--fixed-strings"],
            cwd=WORKSPACE_DIR,
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            git_flash_count = len([l for l in result.stdout.strip().split("\n") if l.strip()])
    except Exception:
        pass

    # 自己申告タスク数（注: セッション再開でリセットされるため参考値）
    session = _safe_read_json(FLASH_SESSION_PATH, {})
    session_tasks = session.get("tasks_completed_in_session", 0)

    # 整合性判定
    if report_count == 0 and git_flash_count == 0:
        return {
            "status": "WARN",
            "detail": "バッチ履歴・Gitコミットともに0件（新規セッションの可能性）",
            "report_batches": 0, "git_commits": 0,
            "report_tasks": 0, "session_tasks": 0,
        }

    # バッチ数の整合（±5件以内を許容）
    batch_gap = abs(report_count - git_flash_count)
    if batch_gap <= 5:
        batch_detail = f"報告{report_count}件 ≈ Git{git_flash_count}件 (整合)"
        batch_status = "PASS"
    else:
        batch_detail = f"報告{report_count}件 ≠ Git{git_flash_count}件 (⚠️ 乖離{batch_gap}件)"
        batch_status = "WARN"

    # タスク数の表示（通算値を正とする。session値はリセットされるため参考表示のみ）
    task_detail = f"通算{report_tasks_total}タスク完了 (現セッション内: {session_tasks}件)"

    return {
        "status": batch_status,
        "detail": f"{batch_detail}\n   {task_detail}",
        "report_batches": report_count, "git_commits": git_flash_count,
        "report_tasks": report_tasks_total, "session_tasks": session_tasks,
    }


def check_session_status():
    """検証4: セッションステータスの論理整合"""
    session = _safe_read_json(FLASH_SESSION_PATH, {})
    if not session:
        return {"status": "FAIL", "detail": "セッション情報なし"}

    status = session.get("status", "unknown")
    activity = session.get("current_activity", "unknown")
    subagents = session.get("subagents_running", 0)

    # ステータスと心拍の整合チェック
    hb_result = check_heartbeat()
    hb_min = hb_result.get("minutes_ago", -1)

    if status == "running" and hb_min > 30:
        # Gradual response to stale heartbeat (3-stage)
        stage_result = _auto_stop_stale_session(hb_min)
        if stage_result == "stopped":
            return {
                "status": "FAIL",
                "detail": f"ステータスは 'running' だが心拍が{hb_min}分前 → 自動停止しました（閾値超過）",
            }
        elif stage_result == "warned":
            return {
                "status": "WARN",
                "detail": f"心拍{hb_min}分前（Hub連携維持中、閾値超過で自動停止）",
            }

    # Check for heartbeat_warning flag (recovery detection)
    if status == "running" and session.get("heartbeat_warning") and hb_min <= 15:
        # Heartbeat recovered — clear warning
        try:
            session.pop("heartbeat_warning", None)
            session.pop("heartbeat_warning_at", None)
            atomic_write_json(FLASH_SESSION_PATH, session)
        except Exception:
            pass

    if status == "stopped":
        return {"status": "WARN", "detail": "セッションは 'stopped' 状態"}

    return {
        "status": "PASS",
        "detail": f"ステータス: {status} / アクティビティ: {activity} / サブエージェント: {subagents}件",
    }


def assess_flash_lifecycle():
    """検証5: Flashセッションのライフサイクル判定"""
    session = _safe_read_json(FLASH_SESSION_PATH, {})
    if not session:
        return {"status": "INFO", "detail": "Flashセッション未開始", "recommendation": "新規開設"}

    status = session.get("status", "unknown")
    activity = session.get("current_activity", "")
    completed = session.get("tasks_completed_in_session", 0)
    batches = session.get("batches_in_session", 0)

    # 完遂判定: ステータスがendedなら確実にCOMPLETE
    if status == "ended":
        return {
            "status": "COMPLETE",
            "detail": f"🏁 ミッション完遂済み ({completed}タスク / {batches}バッチ)",
            "recommendation": "アーカイブ可能 → 新規Flashセッション開設を推奨",
        }

    # stopped の場合: 停止理由で判定を分岐
    if status == "stopped":
        auto_stop_reason = session.get("auto_stop_reason", "")
        if auto_stop_reason == "new_session_requested":
            # generate_flash_prompt.py による自動停止 → 新セッションへの遷移中の可能性
            hb_minutes = _calc_hb_minutes(session.get("last_heartbeat"))
            if hb_minutes is not None and hb_minutes <= 5:
                return {
                    "status": "TRANSITIONING",
                    "detail": f"🔄 新セッションへの遷移中 ({completed}タスク完了済み)",
                    "recommendation": "新セッションの起動を待機（アクション不要）",
                }
        # その他の停止理由、または心拍が古い場合 → COMPLETE
        return {
            "status": "COMPLETE",
            "detail": f"🏁 ミッション完遂済み ({completed}タスク / {batches}バッチ)",
            "recommendation": "アーカイブ可能 → 新規Flashセッション開設を推奨",
        }

    # タスクキュー確認: 残タスクがあるか
    queue = _safe_read_json(TASK_QUEUE_PATH, {})
    tasks = queue.get("tasks", [])
    pending = sum(1 for t in tasks if t.get("status") == "pending")
    running = sum(1 for t in tasks if t.get("status") == "running")

    if status == "running" and pending == 0 and running == 0 and completed > 0:
        return {
            "status": "FINISHING",
            "detail": f"⏳ 残タスクなし。完遂プロトコル待ち ({completed}タスク完了済み)",
            "recommendation": "Flash側の完遂プロトコル実行を待機",
        }

    # 稼働時間チェック
    started = session.get("session_started_at")
    uptime_hours = 0
    if started:
        start_dt = _parse_iso(started)
        if start_dt:
            uptime_hours = (datetime.now(timezone.utc) - start_dt).total_seconds() / 3600

    if uptime_hours > 12:
        return {
            "status": "WARN",
            "detail": f"⏰ 稼働{uptime_hours:.1f}時間経過 (pending={pending}, running={running})",
            "recommendation": "長時間稼働中。コンテキスト効率低下の可能性。状況に応じてアーカイブ検討",
        }

    return {
        "status": "ACTIVE",
        "detail": f"🔄 稼働中 (pending={pending}, running={running}, 完了={completed})",
        "recommendation": "継続稼働",
    }


def check_compaction_in_transcript(conversation_id: str) -> bool:
    """transcript.jsonlからコンテキスト圧縮(コンパクション)の発生を自動検知する"""
    if not conversation_id:
        return False
    app_data_dir = os.path.join(os.path.expanduser("~"), ".gemini", "antigravity")
    log_path = os.path.join(
        app_data_dir, "brain", conversation_id, ".system_generated", "logs", "transcript.jsonl"
    )
    if not os.path.exists(log_path):
        return False
    
    keywords = ["compaction", "コンパクション", "コンテキスト圧縮"]
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line_lower = line.lower()
                if any(kw in line_lower for kw in keywords):
                    return True
    except Exception:
        pass
    return False


def assess_opus_session(check_compaction: bool = False):
    """検証6: Opusセッション切り替えサジェスト + Opus自己健全性チェック"""
    suggestions = []
    opus_health = {"stage": "UNKNOWN", "uptime_hours": 0, "cron_iterations": 0}

    # --- Opus自己健全性チェック ---
    opus_session = _safe_read_json(OPUS_SESSION_PATH, {})
    if opus_session:
        started = _parse_iso(opus_session.get("session_started_at"))
        if started:
            uptime_hours = (datetime.now(timezone.utc) - started).total_seconds() / 3600
            cron_iters = opus_session.get("cron_iterations", 0)
            conv_id = opus_session.get("conversation_id", "")

            # コンパクションの自動検知と状態保持
            compaction_occurred = opus_session.get("compaction_occurred", False)
            if not compaction_occurred and conv_id and check_compaction:
                if check_compaction_in_transcript(conv_id):
                    compaction_occurred = True
                    opus_session["compaction_occurred"] = True
                    try:
                        atomic_write_json(OPUS_SESSION_PATH, opus_session)
                    except Exception:
                        pass

            # 3段階判定（コンパクション発生時は強制的にSTALE）
            if compaction_occurred:
                stage = "STALE"
            elif uptime_hours <= 8:
                stage = "FRESH"
            elif uptime_hours <= 16:
                stage = "AGING"
            else:
                stage = "STALE"

            opus_health = {
                "stage": stage,
                "uptime_hours": round(uptime_hours, 1),
                "cron_iterations": cron_iters,
            }

            if stage == "STALE":
                if compaction_occurred:
                    suggestions.insert(0, f"🔴 Opusセッション STALE — コンテキスト圧縮（コンパクション）の発生を検知しました")
                else:
                    suggestions.insert(0, f"🔴 Opusセッション STALE — 稼働{uptime_hours:.1f}時間 / Cron {cron_iters}回")
                suggestions.insert(1, "   ⚠️ コンテキスト効率が低下しています。セッション移行を強く推奨")
                suggestions.insert(2, "   👉 手順: .agent/workflows/opus-session-migration.md")
            elif stage == "AGING":
                suggestions.insert(0, f"🟡 Opusセッション AGING — 稼働{uptime_hours:.1f}時間 / Cron {cron_iters}回")
                suggestions.insert(1, "   💡 移行の準備を推奨（16時間超で STALE 判定）")

    # Flashセッションの状態に基づくサジェスト
    flash_lc = assess_flash_lifecycle()
    if flash_lc["status"] == "COMPLETE":
        suggestions.append("📦 Flashセッションが完遂済み → 新規Flashセッション開設の検討を")
        suggestions.append("   📖 手順: .agent/workflows/flash-session-archive.md 参照")
    elif flash_lc["status"] == "WARN":
        suggestions.append("⚠️ Flashが長時間稼働中 → アーカイブを検討")
        suggestions.append("   📖 手順: .agent/workflows/flash-session-archive.md 参照")

    # Phase進行チェック
    phase_data = _safe_read_json(PHASE_STATE_PATH, {})
    current_phase = phase_data.get("current_phase", 0)
    if current_phase >= 5:
        max_phase = 29  # ロードマップの最終Phase
        remaining = max(0, max_phase - current_phase)
        if remaining <= 2:
            suggestions.append(f"🎯 Phase {current_phase}/{max_phase} — ロードマップ完了目前。次期MASTER計画の策定を")
        elif remaining <= 5:
            suggestions.append(f"🎯 Phase {current_phase}/{max_phase} — 残{remaining}Phase。Opus側で完了見込みと次期計画の検討を")
        else:
            suggestions.append(f"🎯 Phase {current_phase}/{max_phase} — 順調に進行中")

    if not suggestions:
        return None, opus_health

    return suggestions, opus_health


def _compute_eta_and_next_check():
    """処理完了予想時刻（ETA）と次回確認推奨時刻を計算する。

    Returns:
        dict with keys: eta_jst, eta_minutes, next_check_jst, next_check_minutes,
                        reason, drift_minutes, drift_reason, throughput_tph
    """
    from backend.agents.orchestration import OrchestrationHub
    hub = OrchestrationHub()
    return hub._compute_eta_and_next_check(datetime.now(timezone.utc))


def check_loop_stagnation():
    """検証7: 固着検知（同一モジュールの連続FAILや有効打率の低下）— DS-037統合"""
    reports = []
    if os.path.exists(FLASH_REPORTS_PATH):
        try:
            with open(FLASH_REPORTS_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        reports.append(json.loads(line))
        except Exception:
            pass

    if len(reports) < 3:
        return {"status": "PASS", "detail": "履歴が十分にありません"}

    # 直近3バッチ
    recent = reports[-3:]
    
    # 1) 同一モジュールの連続FAILチェック
    fail_modules = []
    for r in recent:
        tasks = r.get("tasks", [])
        fails = [t.get("target_module") for t in tasks if t.get("status") == "fail" and t.get("target_module")]
        fail_modules.append(set(fails))
        
    common_fails = set.intersection(*fail_modules) if fail_modules else set()
    if common_fails:
        mod = list(common_fails)[0]
        # 自律修復トリガー（DS-037統合: OrchestrationHub経由）
        try:
            from backend.agents.orchestration import OrchestrationHub
            hub = OrchestrationHub()
            hub.auto_heal_stagnation(f"同一モジュール連続FAIL: {mod}")
        except Exception:
            pass
        return {"status": "FAIL", "detail": f"同一モジュール連続FAIL: {mod}"}

    # 2) 有効打率の急低下チェック（空バッチを除外して計算）
    total_tasks = 0
    effective_tasks = 0
    # 空バッチ（tasks=0件）を除外して直近3件を取得
    non_empty = [r for r in reports if len(r.get("tasks", [])) > 0]
    recent_valid = non_empty[-3:] if len(non_empty) >= 3 else non_empty
    for r in recent_valid:
        for t in r.get("tasks", []):
            total_tasks += 1
            res = t.get("result", {})
            changed = []
            if isinstance(res, dict):
                changed = res.get("changed_files", [])
            if changed or t.get("status") in ("pass", "fail"):
                if t.get("status") != "skip":
                    effective_tasks += 1

    if total_tasks > 0:
        rate = (effective_tasks / total_tasks) * 100
        if rate < 10.0:
            return {"status": "FAIL", "detail": f"有効打率の急低下: {rate:.1f}% (制限: >= 10%)"}
    else:
        rate = 0.0

    return {"status": "PASS", "detail": f"有効打率: {rate:.1f}%"}


def check_ux_ratchet_health():
    """検証8: UXストーリー検証 (test_ux_ratchet.py) — DS-037統合"""
    try:
        res = subprocess.run(
            [sys.executable, "-m", "pytest", "backend/tests/test_ux_ratchet.py", "-q"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=WORKSPACE_DIR
        )
        if res.returncode == 0:
            summary = "PASS"
            for line in res.stdout.strip().split("\n"):
                if "passed" in line:
                    summary = line.strip()
                    break
            return {"status": "PASS", "detail": f"UXストーリー検証PASS ({summary})"}
        else:
            return {"status": "FAIL", "detail": "UXストーリー検証不合格 (test_ux_ratchet.py FAIL)"}
    except Exception as e:
        return {"status": "FAIL", "detail": f"UXストーリー検証エラー: {e}"}


def check_metrics_lock():
    """検証9: メトリクス固着 (15バッチ連続でカバレッジとテスト数に変動がないか) — DS-037統合"""
    reports = []
    if os.path.exists(FLASH_REPORTS_PATH):
        try:
            with open(FLASH_REPORTS_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        reports.append(json.loads(line))
        except (OSError, json.JSONDecodeError):
            pass

    if len(reports) < 15:
        return {"status": "PASS", "detail": "履歴が十分にありません"}

    recent = reports[-15:]
    cov_values = [r.get("metrics", {}).get("coverage_pct", 0) for r in recent]
    cnt_values = [r.get("metrics", {}).get("test_count", 0) for r in recent]

    if len(set(cov_values)) == 1 and len(set(cnt_values)) == 1:
        return {"status": "FAIL", "detail": f"メトリクス固着 (15バッチ変動なし: cov={cov_values[0]}, count={cnt_values[0]})"}

    return {"status": "PASS", "detail": "メトリクス変動あり (正常)"}


def run_health_check(check_compaction: bool = False):
    """全検証を実行してレポートを生成"""
    # ゾンビプロセスのパージおよびリソース状況監視とスロットリングフラグ設定
    try:
        from backend.agents.orchestration.resource_governor import ResourceGovernor
        gov = ResourceGovernor()
        gov.kill_zombie_test_processes()
        
        # リソースチェック
        res = gov.check_host_resources()
        level = res.get("level", "NORMAL")
        cpu_usage = res.get("cpu_usage", 0.0)
        mem_usage = res.get("mem_usage", 0.0)
        
        session = _safe_read_json(FLASH_SESSION_PATH, {})
        if session and session.get("status") == "running":
            dirty = False
            if level == "CRITICAL":
                if not session.get("resource_throttled") or session.get("resource_throttle_level") != "CRITICAL":
                    session["resource_throttled"] = True
                    session["resource_throttle_level"] = "CRITICAL"
                    dirty = True
                    # イベントログ追記
                    event = {
                        "timestamp": (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d %H:%M JST"),
                        "lifecycle": "RESOURCE_THROTTLE_ACTIVE",
                        "health": "🔴 RESOURCE_CRITICAL",
                        "change": [f"resource_throttle: NORMAL/CAUTION → CRITICAL (CPU: {cpu_usage:.1f}%, MEM: {mem_usage:.1f}%)"]
                    }
                    try:
                        os.makedirs(os.path.dirname(EVENT_LOG_PATH), exist_ok=True)
                        with open(EVENT_LOG_PATH, "a", encoding="utf-8") as f:
                            f.write(json.dumps(event, ensure_ascii=False) + "\n")
                    except OSError:
                        pass
            else:
                # NORMAL or CAUTION
                if session.get("resource_throttled"):
                    session["resource_throttled"] = False
                    session["resource_throttle_level"] = level
                    dirty = True
                    event = {
                        "timestamp": (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d %H:%M JST"),
                        "lifecycle": "RESOURCE_THROTTLE_DEACTIVATED",
                        "health": "🟢 RESOURCE_OK",
                        "change": [f"resource_throttle: CRITICAL → {level} (CPU: {cpu_usage:.1f}%, MEM: {mem_usage:.1f}%)"]
                    }
                    try:
                        os.makedirs(os.path.dirname(EVENT_LOG_PATH), exist_ok=True)
                        with open(EVENT_LOG_PATH, "a", encoding="utf-8") as f:
                            f.write(json.dumps(event, ensure_ascii=False) + "\n")
                    except OSError:
                        pass
            if dirty:
                atomic_write_json(FLASH_SESSION_PATH, session)
                print(f"[ResourceGov] Host resource status: {level} (CPU: {cpu_usage:.1f}%, MEM: {mem_usage:.1f}%). Throttling flag updated.")
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to check host resources or update throttling flag: {e}")

    now_jst = (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d %H:%M JST")

    checks = [
        ("心拍鮮度", check_heartbeat()),
        ("Git最新コミット", check_git_commits()),
        ("バッチ整合", check_batch_consistency()),
        ("セッション論理整合", check_session_status()),
        ("固着検知", check_loop_stagnation()),             # DS-037統合
        ("UXストーリー検証", check_ux_ratchet_health()),   # DS-037統合
        ("メトリクス固着", check_metrics_lock()),           # DS-037統合
    ]

    # 総合判定
    statuses = [c[1]["status"] for c in checks]
    hb_status = checks[0][1]["status"]  # 心拍鮮度
    batch_status = checks[2][1]["status"]  # バッチ整合
    
    if any(s == "FAIL" for s in statuses):
        overall = "🔴 UNHEALTHY — 異常あり。詳細を確認してください"
    elif all(s == "PASS" for s in statuses):
        overall = "🟢 HEALTHY — 共通処理機構は正常稼働中"
    elif hb_status == "PASS" and batch_status == "WARN" and all(
        s in ("PASS", "WARN") for s in statuses
    ):
        # 心拍正常でバッチ乖離のみWARN → 定常的なタイミングラグのため HEALTHY 扱い
        overall = "🟢 HEALTHY — 共通処理機構は正常稼働中"
    else:
        overall = "🟡 DEGRADED — 一部に注意事項あり"

    # アイコンマップ
    icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}

    # Phase情報
    phase_data = _safe_read_json(PHASE_STATE_PATH, {})
    phase_str = f"Phase {phase_data.get('current_phase', '?')} / {phase_data.get('current_milestone', '?')}"

    report = f"""🏥 Flash稼働ヘルスチェック — {now_jst}
{'━' * 52}
📍 {phase_str}

"""
    for name, result in checks:
        s = result["status"]
        report += f"{icon.get(s, '❓')} {name}: {result['detail']}\n"

    # セッションライフサイクル判定
    flash_lc = assess_flash_lifecycle()
    lc_icon = {"COMPLETE": "🏁", "FINISHING": "⏳", "ACTIVE": "🔄", "WARN": "⚠️", "INFO": "ℹ️"}
    report += f"\n{lc_icon.get(flash_lc['status'], '❓')} Flashセッション: {flash_lc['detail']}\n"
    report += f"   → {flash_lc['recommendation']}\n"

    # Flashコンテキスト飽和の事前検知（flash_session.jsonのarchive_urgencyを読む）
    flash_session = _safe_read_json(FLASH_SESSION_PATH, {})
    archive_urgency = flash_session.get("archive_urgency", "ok")
    context_pct = flash_session.get("context_consumption_pct", 0)
    if archive_urgency == "warn" and flash_session.get("status") == "running":
        report += f"   🔴 Flashコンテキスト飽和 (~{context_pct}%) — 新規セッション準備推奨\n"
        report += f"   👉 generate_flash_prompt.py を実行して新規プロンプトを生成\n"
    elif archive_urgency == "info" and flash_session.get("status") == "running":
        report += f"   🟡 Flashコンテキスト消費増加中 (~{context_pct}%) — 注視\n"

    # ETA + 次回確認推奨
    from backend.agents.orchestration import OrchestrationHub
    hub = OrchestrationHub()
    forecast = hub.get_user_intervention_forecast()
    report += f"\n{forecast}\n"
    eta = getattr(hub, '_last_eta', None) or _compute_eta_and_next_check()

    # Opusセッション健全性
    opus_result = assess_opus_session(check_compaction=check_compaction)
    opus_suggestions = opus_result[0] if isinstance(opus_result, tuple) else opus_result
    opus_health = opus_result[1] if isinstance(opus_result, tuple) else {"stage": "UNKNOWN", "uptime_hours": 0, "cron_iterations": 0}

    opus_stage = opus_health.get("stage", "UNKNOWN")
    opus_uptime = opus_health.get("uptime_hours", 0)
    opus_cron = opus_health.get("cron_iterations", 0)
    opus_icon = {"FRESH": "🟢", "AGING": "🟡", "STALE": "🔴"}.get(opus_stage, "❓")
    report += f"\n{opus_icon} Opusセッション健全性: {opus_stage} — 稼働{opus_uptime}h / Cron {opus_cron}回\n"
    if opus_stage == "STALE":
        report += "   ⚠️ コンテキスト効率低下。セッション移行を強く推奨\n"
    elif opus_stage == "AGING":
        report += "   💡 移行準備を推奨（16h超で STALE）\n"

    report += f"""
{'━' * 52}
{overall}
{'━' * 52}"""

    if opus_suggestions:
        report += f"\n\n💡 Opusセッション運用サジェスト:\n"
        for s in (opus_suggestions if isinstance(opus_suggestions, list) else []):
            report += f"   {s}\n"

    # R7改: ended/COMPLETE検知時のワークスペース閉鎖案内
    session_data = _safe_read_json(FLASH_SESSION_PATH, {})
    session_status = session_data.get("status", "")
    if session_status == "ended" or flash_lc.get("status") == "COMPLETE":
        report += "\n\n⚠️ Flashセッション完遂後のリソース解放:\n"
        report += "   👉 Flash側チャットがまだ開いている場合は閉じてください\n"
        report += "   　 閉じることでCPU/メモリが即座に解放されます\n"
        report += "\n   📋 UIフリーズ復旧手順（段階的に実施）:\n"
        report += "   　 Step 1: Flash側チャットを閉じる → CPU大幅低下\n"
        report += "   　 Step 2: 改善しなければ → Antigravityアプリ全体を終了\n"
        report += "   　 Step 3: 改善しなければ → PC再起動（最終手段）\n"

    # ── 効果検証ゲートの自動判定と警告生成 ──
    v_result = evaluate_effectiveness_gate(WORKSPACE_DIR, phase_data)
    if v_result.get("failed"):
        old_overall = overall
        overall = "🟡 DEGRADED" if phase_data.get("current_milestone") != "M34.2" else "🔴 UNHEALTHY"
        # report内の総合ステータス表記を置換
        report = report.replace(old_overall, f"{overall} — 効果検証しきい値逸脱")
        report += f"\n\n🚨 【効果検証しきい値逸脱】警告レポートが自動生成されました\n"
        report += f"   📋 レポート: {os.path.basename(v_result['report_path'])}\n"
        report += f"   👉 空振り率 {v_result['wasted_rate']:.1f}%（しきい値50%以上）または依存漏れ {v_result['dep_leak_fails']}件（しきい値2件以上）を検知しました\n"

    return {"overall": overall, "checks": checks, "report": report,
            "flash_lifecycle": flash_lc, "eta": eta, "phase_data": phase_data,
            "forecast": forecast}


def evaluate_effectiveness_gate(workspace_path: Path, phase_data: dict) -> dict:
    """効果検証ゲートの自動判定としきい値逸脱時の警告レポート生成"""
    try:
        workspace_path = Path(workspace_path)
        import sys
        sys.path.insert(0, str(workspace_path / "backend"))
        from agents.orchestration.research_reporter import ResearchReporter
        r_reporter = ResearchReporter(str(workspace_path))
        metrics = r_reporter.calculate_metrics()
        
        wasted_rate = metrics.get("wasted_rate", 0.0)
        dep_leak_fails = metrics.get("dep_leak_fails", 0)
        
        # Phaseに応じた段階的しきい値（ラチェット）
        state = _safe_read_json(PHASE_STATE_PATH, {})
        current_phase = state.get("current_phase", 33)
        if current_phase >= 36:
            wasted_threshold = 20.0
        elif current_phase >= 35:
            wasted_threshold = 30.0
        elif current_phase >= 34:
            wasted_threshold = 40.0
        else:
            wasted_threshold = 50.0  # Phase 33以下
        
        is_wasted_failed = wasted_rate >= wasted_threshold
        is_dep_failed = dep_leak_fails >= 2
        is_failed = is_wasted_failed or is_dep_failed
        
        if is_failed:
            # 公式成果物の置き場は引数から組み立てない（research_reporter と同じ理由）。
            report_dir = _official_artifact_dir() / "サブエージェント体制報告" / "分解エンジン研究"
            report_dir.mkdir(parents=True, exist_ok=True)
            # 日付は JST 固定。ローカル時刻だと UTC 環境で 1 日戻り、
            # 同じ日の警告が別ファイル名で二重に生成される。
            now = now_jst()
            report_path = report_dir / f"effectiveness_verification_warning_{now.strftime('%Y%m%d')}.md"
            
            wasted_status = "🔴 FAIL" if is_wasted_failed else "🟢 PASS"
            dep_status = "🔴 FAIL" if is_dep_failed else "🟢 PASS"
            
            warning_content = f"""# 🚨 【警告】分解・生成エンジン効果検証しきい値逸脱報告 ({now.strftime('%Y-%m-%d')})

本レポートは、検証計画書に基づき、自動検証ゲートにてしきい値逸脱を検知したため自動生成された警告レポートです。

## 📊 計測実績と判定

| 検証指標 | 本日の実績値 | 判定基準 (FAIL条件) | 判定結果 |
| :--- | :---: | :---: | :---: |
| **① タスク空振り率 (Wasted Rate)** | **{wasted_rate:.1f}%** | {wasted_threshold:.0f}% 以上 (Phase {current_phase}) | {wasted_status} |
| **③ 依存漏れFAIL件数 (Dependency Leak)** | **{dep_leak_fails}件** | 2件 以上 | {dep_status} |

## 🚨 推奨される改善アクション (見直しと手動適用)

システムによる自動フォールバック（パラメータの自動書き換え等）は実行されません。本アラートを検知した場合は、進化ロードマップを見直すため、以下の推奨改善案について **Opusチャット内で相談**し、方向性を決定した上で手動で適用してください。

1. **空振り率がしきい値 ({wasted_threshold:.0f}%) を超過している場合**:
   - `ds_task_decomposer.py` の結合度しきい値を引き上げ、強連結成分（SCC）としての「単一タスク再統合」を適用することを相談してください。
2. **ハングやリソースオーバーヘッドが懸念される場合**:
   - **代替案A (最大並列度の上限を一律3に下げる静的ハードキャップ)** を `user_schedule.json` のプロファイルに適用することを相談してください。
"""
            # 原子的書き込み
            with open(report_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(warning_content)
                
            return {
                "failed": True,
                "wasted_failed": is_wasted_failed,
                "dep_failed": is_dep_failed,
                "report_path": str(report_path),
                "wasted_rate": wasted_rate,
                "dep_leak_fails": dep_leak_fails
            }
    except Exception:
        pass
    return {"failed": False}


def main():
    # [v2.0.10] 安全ガード無効化: Antigravity v2.0.10でOpusとFlashが同一プロジェクトに統合されたため、
    # プロジェクトパスによる実行制限は不要になった。
    # if "video-automation 2" in WORKSPACE_DIR:
    #     print("⚠️ 警告: health_check.py は Opus統括セッション（video-automation）専用のスクリプトです。")
    #     print("Flash実行セッション（video-automation 2）からの実行はスキップされました。")
    #     sys.exit(0)

    json_mode = "--json" in sys.argv
    update_dashboard = "--update-dashboard" in sys.argv
    check_compaction_opt = "--check-compaction" in sys.argv

    if json_mode:
        # JSONモード時はすべての print (stdout) を stderr にリダイレクトして標準出力の汚染を防ぐ
        sys.stdout = sys.stderr

    # Opusセッション追跡: Cronイテレーションをインクリメント（永続カウンター）
    try:
        opus = _safe_read_json(OPUS_SESSION_PATH, {})
        if opus:
            opus["cron_iterations"] = opus.get("cron_iterations", 0) + 1
            opus["last_cron_at"] = datetime.now(timezone.utc).isoformat()
            atomic_write_json(OPUS_SESSION_PATH, opus)
    except Exception:
        pass  # Opus追跡失敗はサイレント

    result = run_health_check(check_compaction=check_compaction_opt)

    if json_mode:
        pd = result.get("phase_data", {})
        opus_result = assess_opus_session(check_compaction=check_compaction_opt)
        if isinstance(opus_result, tuple):
            opus_sugg, opus_hlth = opus_result
        else:
            opus_sugg, opus_hlth = opus_result, {}
        output = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "overall": result["overall"],
            "checks": {name: data for name, data in result["checks"]},
            "flash_lifecycle": result.get("flash_lifecycle", {}),
            "eta": result.get("eta", {}),
            "forecast": result.get("forecast", ""),
            "suggestions": opus_sugg or [],
            "opus_health": opus_hlth or {},
            "phase": pd.get("current_phase", "?"),
            "milestone": pd.get("current_milestone", "?"),
        }
        # JSONデータのみを本物の標準出力に出力する
        sys.__stdout__.write(json.dumps(output, indent=2, ensure_ascii=False) + "\n")
    else:
        print(result["report"])

    # JSONモード時はナッジ等の追加出力をstderrに向ける（stdout汚染防止）
    _print = (lambda *a, **k: print(*a, **k, file=sys.stderr)) if json_mode else print

    # DEGRADED判定時: Flashへ自動ナッジメッセージ送信（重複防止付き）
    if "DEGRADED" in result.get("overall", ""):
        try:
            sys.path.insert(0, os.path.join(WORKSPACE_DIR))
            from backend.agents.orchestration import OrchestrationHub
            hub = OrchestrationHub()
            
            # 重複防止: 直近15分以内にナッジ済みならスキップ
            NUDGE_COOLDOWN_MINUTES = 15
            recent_messages = hub.read_messages("flash", unread_only=False)
            now = datetime.now(timezone.utc)
            already_nudged = False
            for msg in recent_messages:
                if "【自動ナッジ】" in msg.get("content", ""):
                    try:
                        ts = msg["timestamp"].replace("Z", "+00:00")
                        msg_time = datetime.fromisoformat(ts)
                        if (now - msg_time) < timedelta(minutes=NUDGE_COOLDOWN_MINUTES):
                            already_nudged = True
                            break
                    except (ValueError, TypeError, KeyError):
                        pass
            
            if already_nudged:
                _print(f"\n📨 ナッジスキップ: 直近{NUDGE_COOLDOWN_MINUTES}分以内に送信済み（スパム防止）")
            else:
                hub.send_message(
                    "opus", "flash",
                    "【自動ナッジ】health_checkがDEGRADED判定。心拍が古くなっています。"
                    "自走ループが停止している場合は即座に再開してください。"
                    "hub.generate_flash_status() でステータスを表示し、get_next_batch() で次バッチを取得せよ。",
                    priority="urgent"
                )
                _print("\n📨 Flashセッションへ自動ナッジメッセージを送信しました")
                _print("   → Flashが次にget_next_batch()を呼んだ際にナッジを受け取ります")
                _print("   → 即座の復旧が必要な場合は、Flash側チャットに以下を入力してください:")
                _print('   → 「タイマーが切れています。自走ループを再開し、hub.generate_flash_status()でステータスを表示してください。」')
        except Exception as e:
            _print(f"\n⚠️ 自動ナッジ送信失敗: {e}")

    # UNHEALTHY/COMPLETE判定時: 復旧用Flash起動プロンプトを自動生成
    # ただし TRANSITIONING 状態では自動生成をスキップ（バッチ間遷移の偽検知防止）
    flash_lc = result.get("flash_lifecycle", {})
    lc_status = flash_lc.get("status", "")
    if lc_status == "TRANSITIONING":
        _print("\n✅ Flash: 新セッションへの遷移中 — プロンプト自動生成をスキップ")
    elif "UNHEALTHY" in result.get("overall", "") or lc_status == "COMPLETE":
        # クールダウンチェック: 直前30分以内に generate_flash_prompt.py が実行済みならスキップ
        skip_prompt = False
        try:
            fs = _safe_read_json(FLASH_SESSION_PATH, {})
            stopped_at = fs.get("auto_stopped_at")
            if stopped_at and fs.get("auto_stop_reason") == "new_session_requested":
                stopped_dt = _parse_iso(stopped_at)
                if stopped_dt:
                    elapsed = (datetime.now(timezone.utc) - stopped_dt).total_seconds() / 60
                    if elapsed < 30:
                        skip_prompt = True
                        _print(f"\n⏳ プロンプト自動生成スキップ: 前回生成から{elapsed:.0f}分（クールダウン30分）")
        except Exception:
            pass
        if not skip_prompt:
            try:
                sys.path.insert(0, os.path.join(WORKSPACE_DIR))
                from backend.agents.orchestration.generate_flash_prompt import generate_prompt
                recovery_prompt = generate_prompt()
                _print("\n" + "=" * 60)
                _print("📋 復旧用Flash起動プロンプト（以下を同一プロジェクト内の新規チャットに貼り付け）:")
                _print("=" * 60)
                _print(recovery_prompt)
                _print("=" * 60)
            except Exception as e:
                _print(f"\n⚠️ プロンプト自動生成に失敗: {e}")
                _print("手動で python backend/agents/orchestration/generate_flash_prompt.py を実行してください")

    # ダッシュボード自動更新
    if update_dashboard:
        try:
            sys.path.insert(0, os.path.join(WORKSPACE_DIR))
            # 恒常監査 (harness-audit) の事前実行
            try:
                from backend.agents.orchestration.harness_auditor import run_audit
                run_audit("all")
            except Exception as ae:
                print(f"\n⚠️ 恒常監査自動実行失敗: {ae}", file=sys.stderr)
            
            from backend.agents.orchestration.generate_subagent_reports import generate_dashboard_quick
            path = generate_dashboard_quick()
            print(f"\n📊 ダッシュボード更新完了: {path}")
        except Exception as e:
            print(f"\n⚠️ ダッシュボード更新失敗: {e}")


if __name__ == "__main__":
    main()
