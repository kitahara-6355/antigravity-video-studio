"""Cronヘルスチェック用ラッパースクリプト（構造化サマリー方式 v3）。

毎回同一コマンドで実行されることで、Antigravityの権限承認が
1回で済むようにする（python -c の都度変更問題を解消）。

v3: health_check.py --json の構造化データから状態に応じた
    リッチなサマリーを独自生成。キーワードフィルタ方式を廃止。
"""
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path
import json
import subprocess
import sys
import os
from datetime import datetime, timezone, timedelta

ORCHESTRATION_DIR = os.path.dirname(os.path.abspath(__file__))
FLASH_SESSION_PATH = str(_writable_path("backend/agents/orchestration/flash_session.json"))
OPUS_SESSION_PATH = str(_writable_path("backend/agents/orchestration/opus_session.json"))
USER_SCHEDULE_PATH = os.path.join(ORCHESTRATION_DIR, "user_schedule.json")

# AUTO_NUDGE 発動の閾値（分）
AUTO_NUDGE_THRESHOLD_MINUTES = 20
# 重複防止の間隔（分）
AUTO_NUDGE_COOLDOWN_MINUTES = 10


def _safe_read_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as e:
        sys.stderr.write(f"[Warning] Failed to read or parse JSON at {path}: {e}\n")
        return default


def _check_auto_nudge():
    """心拍が閾値以上古い場合、多層ナッジを実行する。
    
    層1: nudge_flash.json ファイルを書き出し（Python側で完結）
    層2: AUTO_NUDGE_REQUIRED マーカーを出力（Opusがsend_messageで実行）
    
    Returns:
        bool: ナッジを発動した場合 True
    """
    session = _safe_read_json(FLASH_SESSION_PATH, {})
    if not session:
        return False
    
    # running 状態でなければナッジ不要
    if session.get("status") != "running":
        return False
    
    # conversation_id が未登録ならナッジ不可
    conv_id = session.get("conversation_id", "")
    if not conv_id:
        return False
    
    # 心拍鮮度を計算
    last_hb = session.get("last_heartbeat")
    if not last_hb:
        return False
    
    try:
        hb_dt = datetime.fromisoformat(last_hb.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        hb_minutes = (now - hb_dt).total_seconds() / 60
    except (ValueError, TypeError) as e:
        sys.stderr.write(f"[Warning] Failed to parse heartbeat datetime '{last_hb}': {e}\n")
        return False
    
    # 閾値未満ならナッジ不要
    if hb_minutes < AUTO_NUDGE_THRESHOLD_MINUTES:
        return False
    
    # 重複防止: last_auto_nudge_at を確認
    last_nudge = session.get("last_auto_nudge_at")
    if last_nudge:
        try:
            nudge_dt = datetime.fromisoformat(last_nudge.replace("Z", "+00:00"))
            elapsed = (now - nudge_dt).total_seconds() / 60
            if elapsed < AUTO_NUDGE_COOLDOWN_MINUTES:
                return False  # クールダウン中
        except (ValueError, TypeError) as e:
            sys.stderr.write(f"[Warning] Failed to parse last nudge datetime '{last_nudge}': {e}\n")
    
    # ナッジ回数を追跡
    nudge_count = session.get("auto_nudge_count", 0) + 1
    session["auto_nudge_count"] = nudge_count
    session["last_auto_nudge_at"] = now.isoformat()
    try:
        with open(FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)
    except OSError as e:
        sys.stderr.write(f"[Warning] Failed to write session to {FLASH_SESSION_PATH}: {e}\n")
    
    # ── 層1: ファイルベースナッジ（Python側で完結） ──
    nudge_path = os.path.join(ORCHESTRATION_DIR, "nudge_flash.json")
    nudge_message = (
        "心拍が古くなっています。以下を実行してください: "
        "1) 残りのサブエージェントの完了状況を確認 "
        "2) 完了済みのタスクは結果を反映 "
        "3) 未完了のタスクは300秒のタイマーを設定して待機 "
        "4) hub.flash_update_heartbeat() で心拍を更新"
    )
    try:
        nudge_data = {
            "nudge_at": now.isoformat(),
            "reason": f"heartbeat_stale_{int(hb_minutes)}min",
            "conversation_id": conv_id,
            "message": nudge_message,
            "nudge_count": nudge_count,
        }
        with open(nudge_path, "w", encoding="utf-8") as f:
            json.dump(nudge_data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        sys.stderr.write(f"[Warning] Failed to write nudge info to {nudge_path}: {e}\n")
    
    # ── 層2: Opus向けマーカー出力 ──
    print(f"AUTO_NUDGE_REQUIRED:{conv_id}")
    
    # ── 層3: 2回連続ナッジ失敗時はユーザー介入依頼 ──
    if nudge_count >= 2:
        print(
            f"🚨 AUTO_NUDGE {nudge_count}回連続失敗 — ユーザー介入依頼:\n"
            f"   Flashチャットに以下を貼り付けてください:\n"
            f"   「{nudge_message}」"
        )
    
    return True


def _get_current_windows():
    """現在の曜日に応じた着席窓リストを返す（平日/週末分岐）。"""
    schedule = _safe_read_json(USER_SCHEDULE_PATH, {})

    now_jst = datetime.now(timezone(timedelta(hours=9)))
    day_of_week = now_jst.weekday()  # 0=Mon, 5=Sat, 6=Sun

    # v2.0: weekday/weekend 分岐
    if "weekday" in schedule:
        if day_of_week >= 5:  # 土日
            return schedule.get("weekend", {}).get("windows", [])
        else:
            return schedule.get("weekday", {}).get("windows", [])

    # v1.0 互換: フラットな windows
    return schedule.get("windows", [])


def _is_in_user_window():
    """現在時刻がユーザー着席窓内かどうかを判定する。"""
    windows = _get_current_windows()
    if not windows:
        return True  # スケジュール未定義なら常に出力

    now_jst = datetime.now(timezone(timedelta(hours=9)))
    now_hhmm = now_jst.strftime("%H:%M")

    for w in windows:
        if w["start"] <= now_hhmm <= w["end"]:
            return True
    return False


def _next_user_window():
    """次のユーザー着席窓を返す。"""
    windows = _get_current_windows()
    if not windows:
        return None

    now_jst = datetime.now(timezone(timedelta(hours=9)))
    now_hhmm = now_jst.strftime("%H:%M")

    for w in windows:
        if w["start"] > now_hhmm:
            return w
    # 翌日の最初の窓
    return windows[0]


def _is_night_time() -> bool:
    """現在時刻が夜間帯（22:00〜翌06:30 JST）かどうかを判定する。"""
    now_jst = datetime.now(timezone(timedelta(hours=9)))
    now_hhmm = now_jst.strftime("%H:%M")
    return now_hhmm >= "22:00" or now_hhmm <= "06:30"


def _should_output(flash_status: str, overall: str, opus_stage: str) -> tuple:
    """動的出力制御: Flash状態、Opus状態、およびユーザー着席窓に基づいて出力を判定する。

    Returns:
        (should_output: bool, reason: str)
    """
    # 異常時またはOpusセッションがSTALE（移行推奨）の場合は常に出力（スキップ禁止）
    if "UNHEALTHY" in overall or "DEGRADED" in overall:
        return True, "異常検知 → 即時出力"

    if opus_stage == "STALE":
        return True, "Opusセッション STALE（移行推奨） → 即時出力"

    # 夜間帯の判定 (22:00〜06:30 JST)
    if _is_night_time():
        opus = _safe_read_json(OPUS_SESSION_PATH, {})
        iters = opus.get("cron_iterations", 0)
        # 1時間に1回（5分おき実行なので12回に1回）
        if iters % 12 == 0:
            return True, "夜間帯 → 60分出力"
        return False, "夜間帯 → スキップ"

    in_window = _is_in_user_window()
    opus = _safe_read_json(OPUS_SESSION_PATH, {})
    iters = opus.get("cron_iterations", 0)

    if flash_status in ("ACTIVE", "TRANSITIONING", "FINISHING"):
        if in_window:
            return True, "ACTIVE+着席窓 → 5分出力"
        else:
            # 離席中: 15分に1回（iteration % 3 == 0）
            if iters % 3 == 0:
                return True, "ACTIVE+離席中 → 15分出力"
            return False, "ACTIVE+離席中 → スキップ"

    elif flash_status in ("COMPLETE", "STOPPED"):
        if in_window:
            # 着席窓: 10分に1回（iteration % 2 == 0）
            if iters % 2 == 0:
                return True, "COMPLETE+着席窓 → 10分出力"
            return False, "COMPLETE+着席窓 → スキップ"
        else:
            # 離席中+COMPLETE: 30分に1回（iteration % 6 == 0）
            if iters % 6 == 0:
                return True, "COMPLETE+離席中 → 30分出力"
            return False, "COMPLETE+離席中 → スキップ"

    return True, "デフォルト → 出力"


def _build_structured_summary(data: dict) -> str:
    """health_check --json の結果から構造化サマリーを生成する。"""
    overall = data.get("overall", "❓ 不明")
    checks = data.get("checks", {})
    flash_lc = data.get("flash_lifecycle", {})
    eta = data.get("eta", {})
    suggestions = data.get("suggestions", [])
    phase = data.get("phase", "?")
    milestone = data.get("milestone", "?")

    # milestoneが既に"M"で始まる場合は二重にしない
    m_prefix = "" if str(milestone).startswith("M") else "M"

    # 総合ステータスアイコン判定
    has_hallucination = False
    hallucination_score = 0.0
    violations_count = 0
    try:
        from backend.ux_verification.anti_hallucination_gate import AntiHallucinationGate
        gate = AntiHallucinationGate()
        report = gate.run_all_checks()
        hallucination_score = report.hallucination_score
        violations_count = len(report.violations)
        if hallucination_score > 0.0:
            has_hallucination = True
    except (ImportError, AttributeError, FileNotFoundError, NameError, TypeError, ValueError):
        pass

    if has_hallucination:
        status_line = f"🟡 DEGRADED — Phase {phase} / {m_prefix}{milestone} (⚠️ 空想リスク違反 {violations_count}件検出)"
    elif "HEALTHY" in overall:
        status_line = f"🟢 HEALTHY — Phase {phase} / {m_prefix}{milestone}"
    elif "UNHEALTHY" in overall:
        status_line = f"🔴 UNHEALTHY — Phase {phase} / {m_prefix}{milestone}"
    elif "DEGRADED" in overall:
        status_line = f"🟡 DEGRADED — Phase {phase} / {m_prefix}{milestone}"
    else:
        status_line = f"❓ {overall}"

    bar = "━" * 36
    lines = [bar, status_line, bar, ""]

    # ── 心拍 & Flash状態 ──
    hb = checks.get("心拍鮮度", {})
    hb_detail = hb.get("detail", "不明")
    hb_minutes = hb.get("minutes_ago", "?")

    git = checks.get("Git最新コミット", {})
    git_detail = git.get("detail", "不明")

    lc_status = flash_lc.get("status", "?")
    lc_detail = flash_lc.get("detail", "")
    lc_icons = {"COMPLETE": "🏁", "FINISHING": "⏳", "ACTIVE": "🔄", "WARN": "⚠️", "INFO": "ℹ️", "TRANSITIONING": "🔄"}
    lc_icon = lc_icons.get(lc_status, "❓")

    # lc_detailから先頭のアイコンを除去（二重表示防止）
    lc_detail_clean = lc_detail
    for icon_char in lc_icons.values():
        if lc_detail_clean.startswith(icon_char):
            lc_detail_clean = lc_detail_clean[len(icon_char):].strip()
            break

    lines.append(f"📡 Flash: {lc_icon} {lc_detail_clean}")
    lines.append(f"   心拍 {hb_detail} | Git {git_detail}")

    # ── 進捗 ──
    batch = checks.get("バッチ整合", {})
    tasks = batch.get("report_tasks", "?")
    session_tasks = batch.get("session_tasks", "?")
    lines.append(f"📊 通算{tasks}タスク完了 (セッション内: {session_tasks}件)")

    # ── 空想リスク (Σ-4 G-2) ──
    if has_hallucination:
        lines.append(f"🛡️ 空想リスク: 🔴 違反 {violations_count}件 (スコア: {hallucination_score:.1f})")
    else:
        lines.append("🛡️ 空想リスク: 🟢 0.0 (クリーン)")

    # ── ユーザー介入見通し（API統合） ──
    forecast = data.get("forecast")
    if forecast:
        lines.append(forecast)
    else:
        # フォールバック
        eta_jst = eta.get("eta_jst")
        if eta_jst:
            eta_min = eta.get("eta_minutes", "?")
            eta_reason = eta.get("reason")
            reason_suffix = f" — {eta_reason}" if eta_reason else ""
            lines.append(f"📍 ETA: {eta_jst}（約{eta_min}分後）{reason_suffix}")

        session_eta = eta.get("session_eta_jst")
        if session_eta:
            lines.append(f"📐 セッションETA: {session_eta}")

        rec_return = eta.get("recommended_return_jst")
        if rec_return:
            suffix = "" if "JST" in rec_return else " JST"
            lines.append(f"🪑 次回着席推奨: {rec_return}{suffix}")

    # ── Opusセッション健全性 ──
    opus_health = data.get("opus_health", {})
    opus_stage = opus_health.get("stage", "UNKNOWN")
    if opus_stage != "UNKNOWN":
        opus_icon = {"FRESH": "🟢", "AGING": "🟡", "STALE": "🔴"}.get(opus_stage, "❓")
        opus_uptime = opus_health.get("uptime_hours", 0)
        opus_cron = opus_health.get("cron_iterations", 0)
        lines.append(f"🧠 Opus: {opus_icon} {opus_stage} — {opus_uptime}h / Cron {opus_cron}回")

    # ── サジェスト ──
    if suggestions:
        lines.append("")
        for s in suggestions:
            lines.append(f"💡 {s}")

    # ── アクション判定 ──
    lines.append("")
    if lc_status == "COMPLETE":
        lines.append("🚨 要対応: Flash側チャットを閉じてCPU解放")
        lines.append("   → 新規セッション: generate_flash_prompt.py を実行")
    elif lc_status == "TRANSITIONING":
        lines.append("✅ 新セッションへの遷移中 — アクション不要")
    elif "UNHEALTHY" in overall:
        lc_rec = flash_lc.get("recommendation", "状況を確認してください")
        lines.append(f"🚨 要確認: {lc_rec}")
    elif "DEGRADED" in overall:
        lines.append("⚠️ 自動復旧を試行中 — 2回失敗で介入依頼します")
    else:
        lines.append("✅ アクション不要 — 正常稼働中")

    return "\n".join(lines)


def _fallback_keyword_filter(stdout_text: str) -> str:
    """JSON解析に失敗した場合のフォールバック（旧方式）。"""
    keywords = [
        "HEALTHY", "UNHEALTHY", "DEGRADED", "COMPLETE",
        "通算", "完了=", "完了予想", "心拍", "Git最新",
        "Flashセッション", "要対応", "要確認", "Phase",
    ]
    result_lines = []
    for line in stdout_text.split("\n"):
        if any(k in line for k in keywords):
            result_lines.append(line.rstrip())
    return "\n".join(result_lines) if result_lines else stdout_text[:500]


def main():
    script = os.path.join(
        os.path.dirname(__file__), "health_check.py"
    )

    summary = ""
    success = False

    try:
        # Step 1: --json で構造化データを取得
        res_json = subprocess.run(
            [sys.executable, script, "--json"],
            capture_output=True,
        )

        # Step 2: --update-dashboard でダッシュボード更新（非表示）
        # Flashがrunning状態のときはダッシュボード更新を2回に1回に間引く（リソース分離）
        should_update_dashboard = True
        flash_session_data = _safe_read_json(FLASH_SESSION_PATH, {})
        if flash_session_data and flash_session_data.get("status") == "running":
            opus_session_data = _safe_read_json(OPUS_SESSION_PATH, {})
            # cron_iterations に基づいて奇数回をスキップ
            cron_iterations = 0
            if opus_session_data:
                cron_iterations = opus_session_data.get("opus_health", {}).get("cron_iterations", 0)
            if cron_iterations % 2 != 0:
                should_update_dashboard = False

        if should_update_dashboard:
            subprocess.run(
                [sys.executable, script, "--update-dashboard"],
                capture_output=True,
            )

        stdout = res_json.stdout.decode("utf-8", errors="replace")
        try:
            data = json.loads(stdout)
            summary = _build_structured_summary(data)
            success = True

            # Step 3.5: 動的出力制御 — Flash状態とユーザー着席窓に基づいてスキップ判定
            flash_lc = data.get("flash_lifecycle", {})
            lc_status = flash_lc.get("status", "ACTIVE")
            overall = data.get("overall", "")
            opus_health = data.get("opus_health", {})
            opus_stage = opus_health.get("stage", "UNKNOWN")
            should_out, reason = _should_output(lc_status, overall, opus_stage)

            if not should_out:
                # スキップ: 最小限の1行ステータスのみ出力（Opusコンテキスト節約）
                opus_health = data.get("opus_health", {})
                cron_n = opus_health.get("cron_iterations", "?")
                next_w = _next_user_window()
                next_label = f" | 次窓: {next_w['start']} ({next_w['label']})" if next_w else ""
                print(f"⏸️ Cron #{cron_n} スキップ ({reason}){next_label}")
                # AUTO_NUDGE チェックはスキップ時も実行
                _check_auto_nudge()
                return

        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            # JSON解析失敗時はテキストモードにフォールバックするために success = False のまま進む
            sys.stderr.write(f"[Warning] JSON decode failed, falling back to text mode: {e}\n")
            stderr_out = res_json.stderr.decode("utf-8", errors="replace") if 'res_json' in locals() else ""
            if stderr_out:
                sys.stderr.write(f"--- Subprocess Stderr ---\n{stderr_out}-------------------------\n")

    except (subprocess.SubprocessError, OSError) as e:
        print(f"Error executing health check command: {e}", file=sys.stderr)

    if not success:
        # フォールバック: テキストモードで再取得
        try:
            res_text = subprocess.run(
                [sys.executable, script],
                capture_output=True,
            )
            text_out = res_text.stdout.decode("utf-8", errors="replace")
            summary = _fallback_keyword_filter(text_out)
        except (subprocess.SubprocessError, OSError) as e:
            sys.stderr.write(f"[Error] Fallback execution failed: {e}\n")
            summary = f"⚠️ ヘルスチェックコマンドの実行に失敗しました: {e}"

    print(summary)

    # AUTO_NUDGE チェック
    _check_auto_nudge()


if __name__ == "__main__":
    main()
