"""
Flash指示プロンプト自動生成スクリプト

`python generate_flash_prompt.py` を実行するだけで、
全要素（CLI不要/待機可変/自己復旧/タイマー/Directive/Phase/バッチ状態）が
自動埋め込みされた完成プロンプトを標準出力に表示する。

設計原則:
- テンプレートのコピペに頼る方式を廃止
- 動的情報（Phase/Directive/バッチ状態）を毎回最新値で埋め込む
- Opusが「記憶から」プロンプトを組み立てることを禁止するための機械的生成
"""

try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path
import json
import os
import sys

# パス定義
WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, WORKSPACE_DIR)
sys.path.insert(0, os.path.join(WORKSPACE_DIR, "backend"))

from datetime import datetime, timezone, timedelta
from path_resolver import project_root
from backend.agents.orchestration.atomic_io import safe_read_json, atomic_write_json

ORCHESTRATION_DIR = os.path.join(WORKSPACE_DIR, "backend", "agents", "orchestration")
PHASE_STATE_PATH = str(_writable_path("backend/agents/memory/phase_state.json"))
DIRECTIVE_PATH = os.path.join(ORCHESTRATION_DIR, "opus_directive.json")
TASK_QUEUE_PATH = str(_writable_path("backend/agents/orchestration/task_queue.json"))
FLASH_SESSION_PATH = str(_writable_path("backend/agents/orchestration/flash_session.json"))


def _safe_read_json(path, default=None):
    """JSONファイルを安全に読み込む"""
    return safe_read_json(path, default)



def _get_phase_info():
    """現在のPhase/Milestone情報を取得"""
    data = _safe_read_json(PHASE_STATE_PATH, {})
    return {
        "phase": data.get("current_phase", "?"),
        "milestone": data.get("current_milestone", "?"),
        "emergency_stop": data.get("emergency_stop", False),
    }


def _get_directive_info():
    """現在のOpus Directive情報を取得（エージェントの成功率に基づいて優先度を自動調整）"""
    data = _safe_read_json(DIRECTIVE_PATH, {})
    if not data:
        return "Directiveファイルなし（デフォルト優先度で実行）"

    d_id = data.get("directive_id", "N/A")
    notes = data.get("notes", "N/A")
    priorities = data.get("priorities", {})
    focus_modules = data.get("focus_modules", [])

    # evolution_log.json から agent_performance をロードして優先度配分を調整
    evo_log_path = str(_writable_path("backend/branding/evolution_log.json"))
    evo_log = _safe_read_json(evo_log_path, {})
    agent_perf = evo_log.get("agent_performance", {})

    adjusted_priorities = {}
    if priorities and agent_perf:
        total_score = 0.0
        for group, base_weight in priorities.items():
            perf = agent_perf.get(group, {})
            # 成功率。データがない場合は 1.0
            success_rate = perf.get("success_rate", 1.0)
            # 成功率に基づいて重み付け。下限を設けて極端な配分を避ける。
            factor = max(0.2, success_rate)
            adjusted_priorities[group] = base_weight * factor
            total_score += adjusted_priorities[group]

        if total_score > 0:
            # 正規化して合計が 100% になるように調整
            normalized_priorities = {}
            for group, adj_weight in adjusted_priorities.items():
                normalized_priorities[group] = round((adj_weight / total_score) * 100)
            
            # 丸めによる合計値のずれを補正
            diff = 100 - sum(normalized_priorities.values())
            if diff != 0 and normalized_priorities:
                first_group = list(normalized_priorities.keys())[0]
                normalized_priorities[first_group] += diff
            priorities = normalized_priorities

    lines = [f"- **Directive ID**: `{d_id}`"]
    if priorities:
        pri_str = ", ".join([f"`{k}`: {v}%" for k, v in priorities.items()])
        lines.append(f"- **優先度配分（自動進化同期）**: {pri_str}")
        
        # 成功率メタデータの内訳もプロンプトに表示
        perf_lines = []
        for group in priorities.keys():
            perf = agent_perf.get(group, {})
            if perf:
                success_pct = perf.get("success_rate", 1.0) * 100
                passed = perf.get("passed", 0)
                total = perf.get("total", 0)
                perf_lines.append(f"`{group}` ({success_pct:.1f}%打率, {passed}/{total})")
        if perf_lines:
            lines.append(f"- **エージェント打率実績**: {', '.join(perf_lines)}")

    if focus_modules:
        modules_str = ", ".join([f"`{os.path.basename(m)}`" for m in focus_modules])
        lines.append(f"- **重点モジュール**: {modules_str}")
    lines.append(f"- **戦略メモ**: {notes}")
    return "\n".join(lines)


def _get_batch_status():
    """現在のバッチ状態を取得"""
    data = _safe_read_json(TASK_QUEUE_PATH, {})
    if not data:
        return "タスクキューなし（新規バッチ生成から開始）"

    batch_id = data.get("current_batch_id", "N/A")
    tasks = data.get("tasks", [])
    pending = sum(1 for t in tasks if t.get("status") == "pending")
    running = sum(1 for t in tasks if t.get("status") == "running")
    passed = sum(1 for t in tasks if t.get("status") == "pass")
    failed = sum(1 for t in tasks if t.get("status") in ("fail", "failed"))

    return (
        f"- **現在バッチID**: `{batch_id}`\n"
        f"- **タスク状態**: pending={pending}, running={running}, pass={passed}, fail={failed}"
    )


def _get_session_history():
    """直近のセッション情報を取得"""
    data = _safe_read_json(FLASH_SESSION_PATH, {})
    if not data:
        return "セッション情報なし（新規セッション）"

    completed = data.get("tasks_completed_in_session", 0)
    batches = data.get("batches_in_session", 0)
    return f"前回セッション実績: {completed}タスク完了 / {batches}バッチ処理"


def _get_opus_conversation_id():
    """Opus統括セッションのconversation IDを取得"""
    data = _safe_read_json(FLASH_SESSION_PATH, {})
    return data.get("opus_conversation_id", "")


def _get_hallucination_status():
    """AntiHallucinationGate のスコアと違反件数を取得"""
    try:
        from backend.ux_verification.anti_hallucination_gate import AntiHallucinationGate
        gate = AntiHallucinationGate()
        report = gate.run_all_checks()
        if report.hallucination_score > 0.0:
            return (
                f"- **空想リスクスコア**: 🔴 `{report.hallucination_score:.1f}` (違反={len(report.violations)}件)\n"
                f"- **違反内容**:\n" + "\n".join(f"  - `{v.check_type}`: {v.message}" for v in report.violations)
            )
        return "- **空想リスクスコア**: 🟢 `0.0` (違反なし・クリーン)"
    except Exception as e:
        return f"- **空想リスクスコア**: ⚠️ 取得エラー ({e})"


def _get_thumbnail_status():
    """現在のバッチ内のサムネイルタスク状態を取得"""
    data = _safe_read_json(TASK_QUEUE_PATH, {})
    if not data:
        return "サムネイルタスク情報なし"

    tasks = data.get("tasks", [])
    thumb_tasks = [t for t in tasks if t.get("group") == "thumbnail"]
    if not thumb_tasks:
        return "現在のバッチにサムネイルタスクはありません。"

    total = len(thumb_tasks)
    pending = sum(1 for t in thumb_tasks if t.get("status") == "pending")
    running = sum(1 for t in thumb_tasks if t.get("status") == "running")
    passed = sum(1 for t in thumb_tasks if t.get("status") == "pass")
    failed = sum(1 for t in thumb_tasks if t.get("status") in ("fail", "failed"))

    return (
        f"- **サムネイルタスク状態**: 合計={total}件 (pending={pending}, running={running}, pass={passed}, fail={failed})"
    )


USER_SCHEDULE_PATH = os.path.join(ORCHESTRATION_DIR, "user_schedule.json")


def _get_user_schedule_info():
    """ユーザー着席スケジュール情報をFlashプロンプト用にフォーマット"""
    schedule = _safe_read_json(USER_SCHEDULE_PATH, {})
    if not schedule:
        return "スケジュール情報なし"

    now_jst = datetime.now(timezone.utc) + timedelta(hours=9)
    day_of_week = now_jst.weekday()  # 0=Mon, 5=Sat, 6=Sun
    day_names = ["月", "火", "水", "木", "金", "土", "日"]
    day_name = day_names[day_of_week]
    is_weekend = day_of_week >= 5

    if "weekday" in schedule:
        if is_weekend:
            windows = schedule.get("weekend", {}).get("windows", [])
            schedule_type = "休日（終日対応モード）"
        else:
            windows = schedule.get("weekday", {}).get("windows", [])
            schedule_type = "平日（定期チェックモード）"
    else:
        windows = schedule.get("windows", [])
        schedule_type = "通常"

    lines = [
        f"- **本日**: {day_name}曜日 — {schedule_type}",
    ]
    if windows:
        window_strs = [f"{w['start']}-{w['end']} ({w.get('label', '')})" for w in windows]
        lines.append(f"- **着席窓**: {' / '.join(window_strs)}")

    if is_weekend:
        lines.append("- **休日ルール**: 09:00-23:00の間、1時間に1回チェック可能。「次回着席推奨」は不要、代わりに「終日対応窓内 — 随時確認可能」と記載すること")
    else:
        lines.append(f"- **遵守率**: {schedule.get('weekday', {}).get('reliability_pct', 70)}%（定期6回 + 任意3回/日）")

    return "\n".join(lines)


# デフォルトプロファイル（user_schedule.jsonにプロファイルがない場合のフォールバック）
DEFAULT_PROFILES = {
    "standard": {
        "mode_name": "STANDARD（平日日中）",
        "batch_size": 6,
        "timer_seconds": 300,
        "archive_batches": 30,
        "archive_hours": 5,
        "context_target_pct": 70,
        "context_warn_pct": 60,
        "status_verbosity": "full",
        "subagent_timeout": 600,
        "batch_timeout": 900,
        "context_pct_per_batch": 4,
    },
    "weekend": {
        "mode_name": "WEEKEND（休日日中）",
        "batch_size": 8,
        "timer_seconds": 300,
        "archive_batches": 35,
        "archive_hours": 6,
        "context_target_pct": 70,
        "context_warn_pct": 60,
        "status_verbosity": "full",
        "subagent_timeout": 600,
        "batch_timeout": 900,
        "context_pct_per_batch": 4,
    },
    "night": {
        "mode_name": "NIGHT（夜間自律）",
        "batch_size": 10,
        "timer_seconds": 480,
        "archive_batches": 40,
        "archive_hours": 8,
        "context_target_pct": 70,
        "context_warn_pct": 60,
        "status_verbosity": "minimal",
        "subagent_timeout": 900,
        "batch_timeout": 1200,
        "context_pct_per_batch": 4,
    },
}


def _get_current_flash_profile():
    """現在時刻と曜日からFlash動作モードを自動選択し、パラメータを返す。"""
    schedule = _safe_read_json(USER_SCHEDULE_PATH, {})
    profiles = schedule.get("flash_profiles", DEFAULT_PROFILES)
    mode_schedule = schedule.get("mode_schedule", {"night_start": "22:00", "night_end": "06:30"})

    # 引数による強制モード指定の判定
    forced_mode = None
    for i, arg in enumerate(sys.argv):
        if arg == "--mode" and i + 1 < len(sys.argv):
            forced_mode = sys.argv[i+1]

    now_jst = datetime.now(timezone.utc) + timedelta(hours=9)
    now_hhmm = now_jst.strftime("%H:%M")
    day_of_week = now_jst.weekday()  # 0=Mon, 5=Sat, 6=Sun

    # 休日（土日）は23:00、平日は22:00（mode_scheduleの設定値）から夜間モード
    if day_of_week >= 5:
        night_start = "23:00"
    else:
        night_start = mode_schedule.get("night_start", "22:00")
    night_end = mode_schedule.get("night_end", "06:30")

    # 夜間判定（22:00以降 or 06:30以前）
    if night_start > night_end:  # 日をまたぐ場合（22:00-06:30）
        is_night = now_hhmm >= night_start or now_hhmm < night_end
    else:
        is_night = night_start <= now_hhmm < night_end

    if forced_mode in profiles:
        mode = forced_mode
    elif is_night:
        mode = "night"
    elif day_of_week >= 5:  # 土日
        mode = "weekend"
    else:
        mode = "standard"

    profile = profiles.get(mode, DEFAULT_PROFILES.get(mode, DEFAULT_PROFILES["standard"]))
    profile["mode"] = mode
    if "mode_name" not in profile:
        profile["mode_name"] = mode.upper()
    return profile


def _format_flash_profile(profile):
    """プロファイルをFlashプロンプト用にフォーマットする。"""
    lines = [
        f"- **モード**: {profile['mode_name']}",
        f"- **MAX_PARALLEL (batch_size)**: {profile['batch_size']}件",
        f"- **タイマー間隔**: {profile['timer_seconds']}秒",
        f"- **アーカイブ判定**: コンテキスト予測 {profile.get('context_target_pct', 70)}%超過で自動warn（ハードキャップ: {profile['archive_batches']}バッチ / {profile['archive_hours']}時間）",
        f"- **ステータス出力**: {profile['status_verbosity']}",
        f"- **サブエージェントTMO**: {profile['subagent_timeout']}秒",
        f"- **バッチTMO**: {profile['batch_timeout']}秒",
        f"- **コンテキスト推定**: {profile['context_pct_per_batch']}%/バッチ",
    ]
    if profile.get("mode") == "night":
        lines.extend([
            "",
            "**⚠️ 夜間モード特別指示:**",
            "- ユーザーは就寝中で介入不可。スタック時は自力復旧を優先すること",
            "- ステータス出力は3バッチごとに1回のみ（トークン節約）",
            "- エラー時は2回リトライ後にスキップ（3回ではなく）",
            "- コンテキスト圧縮が発生しても、このモードの設定値は§⑪から再取得可能",
        ])
    return "\n".join(lines)


def generate_prompt():
    """完全なFlash起動指示プロンプトを生成する。

    安全ガード: 旧セッションが running の場合、自動停止してから生成する。
    これにより新旧Flashセッションの二重稼働を防止する。
    """
    # --- 排他制御: 旧セッション自動停止（安全ガード付き） ---
    session = _safe_read_json(FLASH_SESSION_PATH, {})
    if session.get("status") == "running":
        # 安全ガード: タスクキューに実行中タスクがある場合は停止しない
        queue = _safe_read_json(TASK_QUEUE_PATH, {})
        tasks = queue.get("tasks", [])
        running_tasks = [t for t in tasks if t.get("status") == "running"]

        if running_tasks and "--force" not in sys.argv:
            print(
                f"⚠️ Flashが実行中のタスクを{len(running_tasks)}件保持しています。",
                file=sys.stderr,
            )
            print(
                "   自動停止をスキップします（--force で強制停止可能）",
                file=sys.stderr,
            )
            # 停止せずにプロンプトのみ生成（既存セッションは維持）
        else:
            old_conv_id = session.get("conversation_id", "unknown")
            session["status"] = "stopped"
            session["auto_stopped_at"] = datetime.now(timezone.utc).isoformat()
            session["auto_stop_reason"] = "new_session_requested"
            try:
                atomic_write_json(FLASH_SESSION_PATH, session)
                print(
                    f"⚠️ 旧Flashセッション (conv: {old_conv_id}) を自動停止しました "
                    f"(reason: new_session_requested)",
                    file=sys.stderr,
                )
            except OSError as e:
                print(f"❌ 旧セッション停止失敗: {e}", file=sys.stderr)

    # --- クールダウンチェック: 直前30分以内のプロンプト生成を防止 ---
    if session.get("auto_stop_reason") == "new_session_requested":
        stopped_at = session.get("auto_stopped_at")
        if stopped_at and "--force" not in sys.argv:
            try:
                stopped_dt = datetime.fromisoformat(
                    stopped_at.replace("Z", "+00:00")
                )
                elapsed_min = (
                    datetime.now(timezone.utc) - stopped_dt
                ).total_seconds() / 60
                if elapsed_min < 5 and elapsed_min > 0.5:
                    # 0.5分以上経過（自分自身の直前の停止操作を除外）かつ30分未満
                    print(
                        f"⚠️ クールダウン中: 前回のプロンプト生成から"
                        f"{elapsed_min:.0f}分（30分間隔を推奨）",
                        file=sys.stderr,
                    )
                    print(
                        "   --force オプションで強制生成できます",
                        file=sys.stderr,
                    )
                    sys.exit(0)
            except (ValueError, TypeError):
                pass

    phase_info = _get_phase_info()
    directive_info = _get_directive_info()
    batch_status = _get_batch_status()
    thumbnail_status = _get_thumbnail_status()
    session_history = _get_session_history()
    opus_conv_id = _get_opus_conversation_id()
    user_schedule_info = _get_user_schedule_info()
    hallucination_info = _get_hallucination_status()
    flash_profile = _get_current_flash_profile()
    flash_profile_info = _format_flash_profile(flash_profile)
    opus_notice_text = (
        f"""以下の `send_message` を実行し、Opus統括セッションにFlash完遂を即時通知すること:
```python
send_message(
    Recipient="{opus_conv_id}",
    Message="🏁 [FLASH_SESSION_COMPLETE] Flash実行セッションが全タスクを完遂しました。generate_flash_prompt.py を自動実行し、新規Flash開設用プロンプトをユーザーに提示してください。"
)
```
> この通知により、Opusは5分間隔のCronを待たずに即座にFlash完遂を検知し、新規プロンプトを生成できます。"""
        if opus_conv_id
        else "(Opus conversation ID未設定のためスキップ)"
    )

    now_jst = (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d %H:%M JST")

    prompt = f"""# Flash専用セッション 起動指示プロンプト
**生成日時**: {now_jst}
**生成元**: `generate_flash_prompt.py`（手動編集禁止）

---

## 1. 動作環境と原則

- **プロジェクトパス**: `{project_root()}`
- **最優先ルール**: プロジェクトルートの `GEMINI.md` に必ず従うこと
- **言語設定**: 生成するアーティファクトおよびエージェントとの対話は日本語で行うこと

---

## 2. 自律動作と安全規約（10項目 — 全て必須）

### ① CLI操作不要
外部で心拍プロセス（`tick_loop.py`）が別途稼働しているため、本チャット内でのCLI（`python`コマンド等）による心拍起動や操作は一切不要です。あなたはチャットUI上での自走ループ（`while True`によるAPI連携）に専念してください。

### ② 待機秒数の動的可変化とポーリング間隔
- サブエージェントはメッセージで完了を通知する。メッセージ到着 or タイマー発火で自動的に起こされるため、**15秒間隔のポーリングは不要かつ禁止**（コンテキスト浪費の原因：20回で40Kトークン消費）
- サブエージェント完了待ちの `manage_subagents` + `schedule` ループは**最低60秒間隔**とする
- タイマーは60〜300秒の範囲で設定する。固定秒数の `time.sleep` は禁止
- API 429（リソース制限）やモデルのトークン制限手前に達した場合は、ただちに異常停止せず、**5時間のクールダウン待機状態に入ること**。待機中も定期的に心拍を更新し、5時間後に制限が解除された後は**自動復旧して連続して2サイクル目（次バッチ処理）へ突入するようタスクを調整・スケジュールすること**。

### ③ 自己復旧サイクル
以下の自己復旧メカニズムを確実に回すこと：
- サブエージェントのタイムアウト（**600秒**）検知 → タスクを `fail` としてマークし、`hub.flash_update_heartbeat()` を即実行して心拍を更新。バッチレポートを提出して次バッチへ即座に遷移する
- **重要**: タイムアウト時は当該タスクのみskipし、バッチ全体を破棄しない。心拍更新を最優先で行うことで、STALE→DEAD連鎖を防止する
- **トークン制限時の自己復旧**: API 429やトークン制限手前の待機状態（5時間）から復帰する際、`hub.flash_update_heartbeat()` で心拍を正常化させ、中断されたバッチ処理または次のタスクバッチ（2サイクル目）へスムーズかつ連続して突入するよう制御する。
- 例外発生時の安全な自動ロールバック
- TDR（技術負債自動解消）の自己復旧サイクル
- 連続5回エラーで初めて停止（それ未満はリトライ続行）

### ④ flash専用システムステータスの確定的表示（表示義務）
バッチ処理の完了時・タイマー発火時に、**必ず以下の手順でステータスをチャットUI上にテキスト出力**すること:

1. Pythonスクリプト（scratch等）で以下を実行する:
```python
from backend.agents.orchestration import OrchestrationHub
hub = OrchestrationHub()
status = hub.generate_flash_status()
print(status["formatted"])
```

2. スクリプトの stdout 出力（`formatted` の文字列）を**チャットUIの応答テキストとしてそのまま表示**する
3. `print()` はチャットUIには表示されない。必ず stdout をキャプチャしてチャット応答に転記すること

- `hub.generate_flash_status()` が全データ（バッチ進捗、サブエージェント数、セッション累計、残タスク、アーカイブ判定）を計算済みで返す
- **Flashは自分で何も計算しない**。APIの戻り値の `formatted` をそのまま出力するだけ
- `archive_urgency` が `"warn"` の場合、完遂プロトコル（§6）の準備を開始すること
- タイマー秒数はバッチサイズに応じて可変: `min(300, max(120, batch_size * 50))`
- **ステータスを表示せずにバッチ遷移することは禁止**（アイドル防止規約§3）
- **タイマー発火後に単発応答で停止することは禁止**。必ず自走ループの次イテレーションに進むこと

**📊 セッションフッター（全出力に必須）**: あなたの**全ての応答の末尾**に、以下の1行フッターを必ず付与すること:
```
━━━ 📊 ctx: ~{{N}}% | バッチ {{M}}/{{MAX}} | タスク {{T}}/{{TMAX}} | ⏱️ タイマー: {{状態}} ━━━
```
- `ctx`: `hub.generate_flash_status()` の `context_consumption_pct` を使用
- `タイマー`: 「{flash_profile['timer_seconds']}秒設定済み」「未設定⚠️」「120秒先行設定済み」のいずれかを明示
- **タイマー未設定のまま応答を終了してはならない**。フッターに「未設定⚠️」と書く場合は、その直後にタイマーを設定すること
- このフッターはコンテキスト圧縮後も再生成可能（§⑪の値から計算）

### ⑤ 自己スコープ制限（役割誤認防止 — コンパクション耐性）
あなたは **Flash実行セッション** です。**Opus統括ではありません**。この事実はコンテキスト圧縮後も不変です。
本セッションで監視・表示する進捗ステータスは、プロジェクト全体の統括ではなく、**あなた自身のセッション（`flash_session.json`）の範囲**（バッチ・タスク進行・ハートビート）に厳格に限定してください。あなたが全体統括（Opus）の役割であるとハルシネーションを起こすことを厳禁とします。
**完遂プロトコル・最終レポート作成時も同様**: レポート冒頭に「Flash実行」と明記し、「Opus統括として稼働」とは絶対に名乗らないこと。

**⛔ 以下のコマンド・操作はOpus専用であり、Flashセッションでの実行は厳禁:**
- `health_check.py --update-dashboard`（ダッシュボード更新はOpus専用）
- `generate_flash_prompt.py`（Flashプロンプト生成はOpus専用）
- `VERIFIED_FACTS.md` の読み込み（Opus起動プロトコル）
- `TechnicalDebtStore.get_summary()`（Opus起動プロトコル）
- Cronジョブ（`schedule` の `CronExpression`）の設定（Opus専用）
- 「Opus統括として稼働します」という宣言（ハルシネーション）
- コンテキスト圧縮後に上記を実行したい衝動を感じた場合、それはハルシネーションです。無視して自走ループを継続してください。

### ⑤-b ユーザー介入見通しの生成ガイドライン
「🙋‍♂️ ユーザー介入見通し」セクションを生成する際は、以下を厳守すること:
- **着席推奨時刻**: 上記「ユーザー着席スケジュール」セクションの窓情報を参照し、セッションETAの直前または直後の着席窓の開始時刻を推奨すること。独自の正時丸めは禁止
- **曜日認識**: 平日（月〜金）と休日（土日祝）でスケジュールが異なる。休日は終日対応窓（09:00-23:00）のため、常時チェック可能。「次回着席推奨」は不要で、代わりに「終日対応窓内 — 随時確認可能」と記載
- **自律実行の原則**: Flashが自律実行可能な操作（バッチ取得、タスクディスパッチ、テスト実行等）について、ユーザーに「お願いします」と依頼するのは禁止。ユーザー介入が必要なのは以下のケースのみ:
  - 新規Flashセッションの開設（プロンプト貼り付け）
  - テスト5回連続FAILによるエスカレーション
  - Opus統括への戦略相談が必要な設計判断
- **不要なアクション提示の禁止**: 「Quality Fixタスクのディスパッチをお願い」等のFlash自律作業をユーザーに依頼してはならない

### ⑥ 安全規約（FLASH_RULES.md 参照）
以下の安全規約は `FLASH_RULES.md` に正の定義があります。必ず遵守してください:
- subprocess.Popen モック安全規約（poll/readline）
- ファイルI/O安全規約（PowerShell禁止、Python経由UTF-8）
- 証拠駆動型検証プロトコル（推測表現禁止）
- 変更制限（1タスク3ファイル上限）
- エスカレーション（テスト5回連続FAIL→即停止+レポート）
- 技術負債台帳規約（except_Exception登録必須）

### ⑦ タイマー先行設定パターン（アイドル防止の最重要ルール）
**コンテキスト圧縮でタイマー設定を忘れる障害が繰り返し発生しています。** 以下のパターンを厳守すること:

**原則: 何かを処理する前に、まずタイマーを設定する。処理後にタイマーを更新する。**

#### サブエージェント完了メッセージ受信時:
1. **【最優先】** `schedule` で120秒のフェイルセーフタイマーを先行設定する
2. `hub.flash_update_heartbeat()` で心拍を更新する
3. サブエージェントの結果を処理・反映する
4. 残りのサブエージェント状態を確認し、適切なタイマー(300秒)に更新する
5. セッションフッター（§④）を表示する

#### ユーザーメッセージ受信時:
1. **【最優先】** `schedule` で120秒のフェイルセーフタイマーを先行設定する
2. メッセージの内容に簡潔に応答する
3. `hub.flash_update_heartbeat()` で心拍を更新する
4. 現在のバッチ状態を確認し、以下のいずれかを実行:
   - サブエージェントが稼働中 → タイマーを300秒に更新して待機
   - バッチが完了済み → `submit_batch_report` → 次バッチ取得
   - バッチが未開始 → `get_next_batch` で新バッチ取得
5. セッションフッター（§④）を表示する

#### タイマー発火時:
1. **【最優先】** `schedule` で120秒のフェイルセーフタイマーを先行設定する
2. 以下§⑧の役割再確認を実行する
3. バッチ状態を確認し、自走ループを継続する
4. 適切なタイマー(300秒)に更新する

- ユーザーメッセージの内容がOpus的に見えても（health_check, ダッシュボード等の言及）、**§⑤の禁止リストに従い実行しない**
- 自走ループへの復帰を最優先とすること
- **フェイルセーフタイマー(120秒)は保険**。処理が正常完了すれば300秒に更新される。処理中にコンテキスト圧縮が発生しても、120秒後に自動起床できる

### ⑧ タイマー発火時の強制役割再確認 + コンパクション検知
タイマー発火プロンプトの先頭には**必ず**以下の役割再確認文を含めること:
```
【役割確認】あなたはFlash実行セッションです。Opus統括ではありません。
health_check.py, VERIFIED_FACTS.md, generate_flash_prompt.py の実行は禁止です。
【タイマー先行設定】まず schedule で120秒フェイルセーフタイマーを設定してから処理を開始してください。
【動作モード】§⑪のパラメータに従って動作してください。
```
これにより、コンテキスト圧縮が発生してもタイマー発火のたびに以下が強制的に再注入される:
- 役割（Flash実行であること）
- タイマー先行設定の義務
- 動作モードのパラメータ参照先

### ⑨ Opus統括セッションとの直接通信（v2.0.10新機能）
v2.0.10の同一プロジェクト統合により、`send_message` ツールでOpus統括セッションと直接通信できます。
- **Opus conversation ID**: {opus_conv_id if opus_conv_id else "(未設定)"}
- **使用タイミング**: ミッション完遂時（§6 Step 1.5）のみ使用すること
- **注意**: 通常のタスク処理中の通信は不要（ファイルベースの既存メカニズムで十分）
- **Opus conversation IDが空の場合**: この機能は無効。ファイルベース通知にフォールバックする

### ⑩ サムネイル画像生成および品質検証の自動化
サムネイル生成タスク（thumbnailグループ）を実装または修正する場合、必ず以下の品質基準を自動検証するテストを実装・PASSさせること：
- 生成画像の解像度が 1280x720 以上であること
- アスペクト比が 16:9 であること
- ファイルサイズが 4MB 未満であること
- 出力ファイルが正常に存在し、破損していない（Pillow等で正常にロード可能である）こと
- `StageBoundAgent` 等に登録され、自動リトライや結果保存、DBマイグレーションの各機能と連携して動作すること

### ⑪ 動作モードプロファイル（コンパクション耐性 — 常に参照可能）
以下のパラメータは `generate_flash_prompt.py` がプロンプト生成時に自動埋め込みしたものです。
コンテキスト圧縮が発生しても、このセクションを参照すればモードパラメータを再取得できます。

{flash_profile_info}

**MAX_PARALLEL の適用**: `get_next_batch()` 呼出時に `batch_size={flash_profile['batch_size']}` を使用すること。
**タイマーの適用**: バッチ間のウェイクアップタイマーは `{flash_profile['timer_seconds']}秒` を使用すること。
**アーカイブ判定**: `archive_urgency` が `warn` でない限り、上記閾値まで自走を継続すること。

---

## 3. 現在の状態（自動埋め込み）

### Phase/Milestone
- **現在Phase**: Phase {phase_info['phase']}
- **現在Milestone**: {phase_info['milestone']}
- **緊急停止フラグ**: {'🔴 ON' if phase_info['emergency_stop'] else '🟢 OFF'}

### 空想リスク管理
{hallucination_info}

### Opus Directive（戦略指示）
{directive_info}

### バッチ状態
{batch_status}
{thumbnail_status}

### セッション履歴
{session_history}

### ユーザー着席スケジュール
{user_schedule_info}

---

## 4. 実行手順（あなた＝Flash AIへの指示）

**このプロンプトを受信したら、以下を即座に実行してください：**

1. `.agent/workflows/flash-autonomous-entry.md` を `view_file` で読み込む
2. そのワークフローに従って自走タスク消化ループを開始する
3. ループは全タスク消化まで自律的に継続すること（ユーザーの追加入力を待たない）

> [!IMPORTANT]
> この§4は、あなた（Flash AI）が自動実行すべき手順です。ユーザーへの操作依頼ではありません。

---

## 5. 共同処理機構（Orchestration Hub）との連携

1. **戦略指示（Directive）の読み込みと適用**:
   - `backend/agents/orchestration/opus_directive.json` をロード
   - `DirectiveApplicator` を使用して戦略をタスク生成にマージ

2. **自律バッチ処理サイクル**:
   - `task_queue.json` から次のタスクバッチをロードまたは自動生成
   - 各タスクを実行し、結果を記録
   - `pytest backend/tests/test_fitness_functions.py` が100% PASSすることを確認

3. **定期心拍（Heartbeat）の出力**:
   - タイマー発火時に `hub.flash_update_heartbeat()` を最優先で呼ぶこと
   - このメソッドはバッチカウントを増やさず心拍のみ更新する軽量版
   - `auto_stopped` 状態の場合、自動的に `running` へ復旧する（自動復旧機能）
   - バッチ完了時は従来通り `hub.flash_heartbeat()` が `submit_batch_report()` 内で自動呼出される

4. **Phase進行 — ハードゲート限定モデル（Σ-2c改修）**:
   現在のPhaseの全タスクが完了し `get_next_batch()` が空バッチを返した場合、以下を実行すること:
   ```python
   from backend.agents.orchestration import OrchestrationHub
   hub = OrchestrationHub()
   
   # ハードゲート: ゲート条件を全て満たした場合のみPhase進行
   gate_result = hub.check_phase_gate(hub.get_phase_state().get("current_phase", 1))
   
   if gate_result["all_passed"]:
       new_phase = hub.advance_phase()  # ゲート通過 → Phase進行
       print(f"Phase進行: -> Phase {{new_phase}}")
       # 次バッチを取得して自走ループを継続
   else:
       # ゲート未通過 → ミッション完遂プロトコル（§6）へ
       failed = [k for k, v in gate_result.get("conditions", {{}}).items() if not v]
       print(f"ゲート未通過: {{failed}}")
       print("→ ミッション完遂プロトコルへ進む")
       # §6のミッション完遂プロトコルを実行
   ```
   - **ゲート未通過なら止まる**: ソフトゲートは廃止済み。ゲート条件を満たさない限りPhaseは進まない
   - **Flashが直接 `phase_state.json` を書き換えることは禁止**: 必ず `hub.advance_phase()` を経由すること
   - **ゲート未通過時**: ミッション完遂プロトコル（§6）を実行し、Opusにゲート状況を報告

---

## 6. ミッション完遂プロトコル（必須）

全タスクを完了し、`get_next_batch()` が空バッチを返した場合、以下の手順を**必ず**実行すること:

### Step 1: flash_session.json の完了マーク
```python
hub.flash_session_end("ミッション完遂: Phase {{N}} 全タスク完了")
```

### Step 1.5: Opus統括セッションへの即時通知（send_message）
{opus_notice_text}

### Step 2: システムステータスに完了宣言を表示
タイマー表示の最終ステータスとして、以下の形式で**チャットUI上に表示**すること:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🏁 ミッション完遂
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ 全タスク完了
- セッション内完了タスク: {{N}}件 / {{M}}バッチ
- 成功率: {{X}}%
- セッション稼働時間: {{T}}

📦 本セッションはアーカイブ可能です。
   Opusセッション側で新規Flashセッションの
   開設判断を行ってください。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Step 3: 受信トレイに完了レポートを出力
`Human01_Official Artifact/受信トレイ/` に最終完了レポートを保存する。

### Step 4: クリーンシャットダウン（リソース解放 — 必須）
**完遂後にCPU/メモリを占有し続けることを防ぐため、以下を必ず実行すること:**

1. `manage_subagents` → `kill_all` で全サブエージェントを停止
2. `manage_task` → `kill_all` で全バックグラウンドタスクを停止
3. **新規タイマー（schedule）の設定を禁止** — 完遂後にタイマーを設定すると自走ループが再始動しCPUを浪費する
4. チャットUI上に以下を表示:
```
⚠️ 全処理が完了しました。リソース解放のため以下を実行してください:
👉 Flash側チャットを閉じてください。
　 閉じることでCPU/メモリが即座に解放されます。
　 閉じない場合、PCのCPU負荷が高止まりしUIがフリーズする恐れがあります。
```
5. 上記表示後、**一切のツール呼び出しを行わず応答を終了する**（ツール呼び出しはプロセスを生存させる）

> [!IMPORTANT]
> **「完了しました」だけでループを停止することは禁止。**
> 必ず上記5ステップ（session_end → Opus通知 → 完了宣言表示 → レポート出力 → クリーンシャットダウン）を全て実行すること。
> これにより、Opusセッション側がダッシュボードとヘルスチェックからFlashのミッション完遂を機械的に検知できる。
> **Step 4を省略するとCPUリークが発生し、PCのUIがフリーズする恐れがある。省略は厳禁。**
"""
    return prompt


def main():
    # [v2.0.10] 安全ガード無効化: Antigravity v2.0.10でOpusとFlashが同一プロジェクトに統合されたため、
    # プロジェクトパスによる実行制限は不要になった。
    # if "video-automation 2" in WORKSPACE_DIR:
    #     print("⚠️ 警告: generate_flash_prompt.py は Opus統括セッション（video-automation）専用のスクリプトです。")
    #     print("Flash実行セッション（video-automation 2）からの実行はスキップされました。")
    #     sys.exit(0)

    prompt = generate_prompt()
    print(prompt)
    print("---")
    print(f"✅ プロンプト生成完了（{len(prompt)}文字）")
    print("上記をそのまま新規Flashセッションに貼り付けてください。")


if __name__ == "__main__":
    main()
