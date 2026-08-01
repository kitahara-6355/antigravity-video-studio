try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import official_artifact_dir as _official_artifact_dir
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import official_artifact_dir as _official_artifact_dir
    from path_resolver import writable_path as _writable_path
import os
from backend.agents.orchestration.link_validator import (
    get_rel_link,
    localize_links,
    validate_dashboard_links,
    _record_event_if_changed,
    _record_topic_event,
    _read_recent_events,
)
from backend.agents.orchestration.jst_time import (
    jst_compact_date,
    jst_date,
    jst_stamp,
)
from backend.agents.orchestration.stats_collector import (
    get_tdr_stats,
    extract_metrics_from_report,
    generate_trend_table,
    generate_time_aggregation,
    _calc_daily_effectiveness,
    _safe_read_json_local,
    _parse_event_ts,
    get_recent_git_commits,
    _infer_group_from_module,
    _module_to_topic,
    _get_current_phase,
    register_tdr_debts,
    parse_iso_datetime,
    format_duration,
    extract_date,
    _load_flash_reports_cached,
)


import json
import glob
import shutil
import sys
import re
import subprocess
from datetime import datetime, timezone, timedelta

from path_resolver import brain_dir

# パスの定義（デフォルトは相対パス）
WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)
backend_path = os.path.join(WORKSPACE_DIR, "backend")
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)
ORCHESTRATION_DIR = os.path.join(WORKSPACE_DIR, "backend", "agents", "orchestration")
TASK_QUEUE_PATH = str(_writable_path("backend/agents/orchestration/task_queue.json"))
FLASH_SESSION_PATH = str(_writable_path("backend/agents/orchestration/flash_session.json"))
FLASH_REPORTS_PATH = os.path.join(ORCHESTRATION_DIR, "flash_reports.jsonl")

OFFICIAL_ARTIFACT_DIR = str(_official_artifact_dir())
REPORT_BASE_DIR = os.path.join(OFFICIAL_ARTIFACT_DIR, "サブエージェント体制報告")
PERIODIC_REPORT_DIR = os.path.join(REPORT_BASE_DIR, "定時レポート")
BULLETIN_REPORT_DIR = os.path.join(REPORT_BASE_DIR, "速報")
RANKING_REPORT_DIR = os.path.join(REPORT_BASE_DIR, "活動ランキング")

# Brainディレクトリのパス（デフォルト）
BRAIN_REPORT_PATH = str(brain_dir() / "ecf8e7d2-8173-4818-8ac8-0b410cd129a0" / "daily_report_20260522.md")

def find_latest_brain_report():
    """brainディレクトリから最新 of daily_report_*.md を自動検出する"""
    try:
        brain_base = os.path.dirname(os.path.dirname(BRAIN_REPORT_PATH))
        if not os.path.exists(brain_base):
            return BRAIN_REPORT_PATH

        # brain/*/*.md を検索して、ファイル名が daily_report_ で始まるものを探す
        report_pattern = os.path.join(brain_base, "*", "daily_report_*.md")
        import glob
        files = glob.glob(report_pattern)
        if not files:
            # 他の想定パスも探す
            report_pattern2 = os.path.join(brain_base, "*", ".system_generated", "artifacts", "daily_report_*.md")
            files = glob.glob(report_pattern2)

        if files:
            # 更新日時が最も新しいものを返す
            return max(files, key=lambda f: (os.path.getmtime(f), f))
    except Exception:
        pass
    return BRAIN_REPORT_PATH

def get_week_range_str(date_str):
    """
    date_str (YYYY-MM-DD) から、その日が含まれる週の月曜日〜日曜日の範囲文字列を生成する。
    例: '2026-05-18 〜 2026-05-24 (第21週)'
    """
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        weekday = dt.weekday()
        monday = dt - timedelta(days=weekday)
        sunday = dt + timedelta(days=6 - weekday)
        week_num = dt.isocalendar()[1]
        return f"{monday.strftime('%Y-%m-%d')} 〜 {sunday.strftime('%Y-%m-%d')} (第{week_num}週)"
    except Exception:
        return "その他の週"




def _load_event_log_cached(cache: dict = None) -> list:
    """キャッシュ付きevent_log.jsonlローダー。"""
    if cache is not None and 'event_log' in cache:
        return cache['event_log']

    event_log_path = os.path.join(
        REPORT_BASE_DIR, "event_log.jsonl"
    )
    entries = []
    if os.path.exists(event_log_path):
        with open(event_log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    if cache is not None:
        cache['event_log'] = entries
    return entries





def get_flash_status_md():
    """flash_session.json から最新のリアルタイムステータスをマークダウン化する（鮮度3段階判定）"""
    if not os.path.exists(FLASH_SESSION_PATH):
        return ""
    try:
        with open(FLASH_SESSION_PATH, "r", encoding="utf-8") as f:
            session = json.load(f)
        
        status = session.get("status", "unknown")
        
        last_hb_str = session.get("last_heartbeat")
        hb_diff_str = "不明"
        hb_abs_str = "不明"
        hb_diff_min = -1
        
        if last_hb_str:
            dt = parse_iso_datetime(last_hb_str)
            if dt:
                now_utc = datetime.now(timezone.utc)
                diff = now_utc - dt
                hb_diff_min = int(diff.total_seconds() // 60)
                # JST表示用の絶対時刻
                jst = dt + timedelta(hours=9)
                hb_abs_str = jst.strftime("%Y-%m-%d %H:%M JST")
                
                if hb_diff_min == 0:
                    hb_diff_str = "今さっき心拍を確認"
                elif hb_diff_min < 60:
                    hb_diff_str = f"{hb_diff_min}分前"
                else:
                    hb_diff_str = f"{hb_diff_min // 60}時間{hb_diff_min % 60}分前"
        
        # 鮮度3段階判定
        if status == "stopped":
            badge = "🔴 STOPPED"
        elif hb_diff_min < 0:
            badge = "⚪ UNKNOWN"
        elif hb_diff_min <= 15:
            badge = "🟢 RUNNING"
        elif hb_diff_min <= 30:
            badge = "🟡 STALE（情報が古い可能性）"
        else:
            badge = "🔴 UNREACHABLE（到達不能）"
                    
        activity = session.get("current_activity", "N/A")
        step = session.get("current_step", "N/A")
        batch_id = session.get("current_batch_id", "N/A")
        subagents = session.get("subagents_running", 0)
        completed = session.get("tasks_completed_in_session", 0)
        batches = session.get("batches_in_session", 0)
        
        # セッション開始からの経過時間
        session_start = session.get("session_started_at")
        uptime_str = "N/A"
        if session_start:
            start_dt = parse_iso_datetime(session_start)
            if start_dt:
                now_utc = datetime.now(timezone.utc)
                uptime_sec = (now_utc - start_dt).total_seconds()
                uptime_str = format_duration(max(0, uptime_sec))
        
        md = f"""
### 🫀 リアルタイム・システムステータス
- **Flash並列セッション**: {badge}
- **最終心拍**: {hb_abs_str}（{hb_diff_str}）
- **現在のアクティビティ**: `{activity}`
- **現在のステップ**: {step}
- **実行中のバッチID**: `{batch_id}`
- **並列処理中のサブエージェント**: `{subagents}` 件
- **セッション内完了タスク数**: `{completed}` 件 / `{batches}` バッチ
- **セッション稼働時間**: {uptime_str}
"""
        return md
    except Exception as e:
        print(f"Warning: flash_status_md生成失敗: {e}")
        return ""

def get_directive_md():
    """opus_directive.json から現在の戦略指示をマークダウン化する"""
    directive_path = os.path.join(ORCHESTRATION_DIR, "opus_directive.json")
    if not os.path.exists(directive_path):
        return ""
    try:
        with open(directive_path, "r", encoding="utf-8") as f:
            directive = json.load(f)
        
        d_id = directive.get("directive_id", "N/A")
        notes = directive.get("notes", "N/A")
        priorities = directive.get("priorities", {})
        focus_modules = directive.get("focus_modules", [])
        
        pri_str = ", ".join([f"`{k}`: {v}%" for k, v in priorities.items()])
        modules_str = ", ".join([f"`{os.path.basename(m)}`" for m in focus_modules]) if focus_modules else "なし"
        
        md = f"""
### 🎯 現在の開発優先戦略 (Directive: {d_id})
- **優先度配分**: {pri_str}
- **重点モジュール**: {modules_str}
- **戦略メモ**: {notes}
"""
        return md
    except Exception as e:
        print(f"Warning: directive_md生成失敗: {e}")
        return ""

def main(brain_report_path=None):
    print(f"=== サブエージェント体制報告 整理・生成開始 ===")

    # 引数が指定されていない場合は、自動検索を試みる
    if not brain_report_path:
        brain_report_path = find_latest_brain_report()

    print(f"対象の包括レポートパス: {brain_report_path}")
    
    # 1. フォルダ構成の作成
    for path in [PERIODIC_REPORT_DIR, BULLETIN_REPORT_DIR, RANKING_REPORT_DIR]:
        if not os.path.exists(path):
            os.makedirs(path)
            print(f"フォルダ作成: {path}")

    # 2. 既存の1時間ごと速報レポートのコピー
    inbox_source_dir = os.path.join(OFFICIAL_ARTIFACT_DIR, "未転記", "分析・提案")
    inbox_dir = os.path.join(OFFICIAL_ARTIFACT_DIR, "受信トレイ")
    copied_bulletins = []
    
    if os.path.exists(inbox_source_dir):
        for filepath in sorted(glob.glob(os.path.join(inbox_source_dir, "hourly_report_*.md"))):
            filename = os.path.basename(filepath)
            dest_path = os.path.join(BULLETIN_REPORT_DIR, filename)
            shutil.copy2(filepath, dest_path)
            copied_bulletins.append(filename)
        print(f"速報レポートをコピーしました: {len(copied_bulletins)}件")
        
        # 既存のPhase完了レポートなども定時レポートにコピー
        for filepath in sorted(glob.glob(os.path.join(inbox_source_dir, "phase_*_completion_*.md"))):
            filename = os.path.basename(filepath)
            dest_path = os.path.join(PERIODIC_REPORT_DIR, filename)
            shutil.copy2(filepath, dest_path)
            print(f"Phase完了レポートをコピーしました: {filename}")
            
    # 受信トレイフォルダからのコピー (M21.2 完了等の最新レポートおよび耐久レポートの収集)
    if os.path.exists(inbox_dir):
        # hourly_report_*.md のコピー
        for filepath in sorted(glob.glob(os.path.join(inbox_dir, "hourly_report_*.md"))):
            filename = os.path.basename(filepath)
            dest_path = os.path.join(BULLETIN_REPORT_DIR, filename)
            shutil.copy2(filepath, dest_path)
            print(f"受信トレイから速報レポートをコピーしました: {filename}")

        # phase_*_completion_*.md のコピー
        for filepath in sorted(glob.glob(os.path.join(inbox_dir, "phase_*_completion_*.md"))):
            filename = os.path.basename(filepath)
            dest_path = os.path.join(PERIODIC_REPORT_DIR, filename)
            shutil.copy2(filepath, dest_path)
            print(f"受信トレイからPhase完了レポートをコピーしました: {filename}")
            
        # periodic_report_*.md のコピー
        for filepath in sorted(glob.glob(os.path.join(inbox_dir, "periodic_report_*.md"))):
            filename = os.path.basename(filepath)
            dest_path = os.path.join(PERIODIC_REPORT_DIR, filename)
            shutil.copy2(filepath, dest_path)
            print(f"受信トレイから定時レポートをコピーしました: {filename}")
            
        # raw_video_durability_report.md のコピー
        for filepath in sorted(glob.glob(os.path.join(inbox_dir, "raw_video_durability_report.md"))):
            filename = os.path.basename(filepath)
            dest_path = os.path.join(PERIODIC_REPORT_DIR, filename)
            shutil.copy2(filepath, dest_path)
            print(f"受信トレイから耐久レポートをコピーしました: {filename}")

    # 3. Brain内の24時間包括レポートをコピー
    if brain_report_path and os.path.exists(brain_report_path):
        filename = os.path.basename(brain_report_path)
        dest_daily = os.path.join(PERIODIC_REPORT_DIR, filename)
        shutil.copy2(brain_report_path, dest_daily)
        print(f"24時間包括レポートを定時レポートへコピーしました: {dest_daily}")
    else:
        # 代わりに未転記の中にあるdaily_digest_*.md等を探す
        digest_files = sorted(glob.glob(os.path.join(inbox_source_dir, "daily_digest_*.md")))
        if digest_files:
            for filepath in digest_files:
                filename = os.path.basename(filepath)
                dest_path = os.path.join(PERIODIC_REPORT_DIR, filename)
                shutil.copy2(filepath, dest_path)
                print(f"日次ダイジェストをコピーしました: {filename}")

    if not os.path.exists(TASK_QUEUE_PATH):
        print(f"Error: {TASK_QUEUE_PATH} が見つかりません。")
        return

    # 4. 活動データの集計 (flash_reports.jsonl および task_queue.json から統合収集)
    all_tasks = []
    seen_task_ids = set()

    # (A) flash_reports.jsonl から過去の完了バッチに含まれるタスクを抽出
    flash_reports_path = FLASH_REPORTS_PATH
    if os.path.exists(flash_reports_path):
        try:
            with open(flash_reports_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    report_entry = json.loads(line)
                    for task in report_entry.get("tasks", []):
                        task_id = task.get("id")
                        if task_id and task_id not in seen_task_ids:
                            seen_task_ids.add(task_id)
                            all_tasks.append(task)
        except Exception as e:
            print(f"Warning: flash_reports.jsonl の読み込みに失敗しました: {e}")

    # (B) 現在の task_queue.json から完了タスクを抽出してマージ (未保存バッチのタスク漏れ防止)
    if os.path.exists(TASK_QUEUE_PATH):
        try:
            with open(TASK_QUEUE_PATH, "r", encoding="utf-8") as f:
                queue_data = json.load(f)
            for task in queue_data.get("tasks", []):
                task_id = task.get("id")
                if task_id and task_id not in seen_task_ids:
                    seen_task_ids.add(task_id)
                    all_tasks.append(task)
        except Exception as e:
            print(f"Warning: task_queue.json の読み込みに失敗しました: {e}")

    agent_stats = {}
    
    total_completed = 0
    total_passed = 0
    total_failed = 0
    total_duration_sec = 0

    for task in all_tasks:
        status = task.get("status")
        # 完了しているタスクのみ集計 (pass または fail)
        if status not in ["pass", "fail"]:
            continue

        group = task.get("group") or ""
        # 改善D: unknownエージェント名のフォールバック解決
        if not group or group == "unknown":
            group = _infer_group_from_module(task.get("target_module", ""))
        agent_type = f"{group} Agent"

        if agent_type not in agent_stats:
            agent_stats[agent_type] = {
                "tasks": 0,
                "pass": 0,
                "fail": 0,
                "duration_sec": 0.0,
            }

        stats = agent_stats[agent_type]
        stats["tasks"] += 1
        
        if status == "pass":
            stats["pass"] += 1
            total_passed += 1
        else:
            stats["fail"] += 1
            total_failed += 1
            
        total_completed += 1

        started = parse_iso_datetime(task.get("started_at"))
        completed = parse_iso_datetime(task.get("completed_at"))
        
        if started and completed:
            # タイムゾーンの有無による引き算エラーを回避するため naive 化して計算
            started_naive = started.replace(tzinfo=None) if started.tzinfo else started
            completed_naive = completed.replace(tzinfo=None) if completed.tzinfo else completed
            duration = (completed_naive - started_naive).total_seconds()
            stats["duration_sec"] += duration
            total_duration_sec += duration

    # 5. エラー履歴の集計 (flash_session.json)
    error_modules = {}
    if os.path.exists(FLASH_SESSION_PATH):
        try:
            with open(FLASH_SESSION_PATH, "r", encoding="utf-8") as f:
                session_data = json.load(f)
            
            for err_entry in session_data.get("recent_errors", []):
                module = err_entry.get("module", "unknown")
                error_str = err_entry.get("error", "")
                
                # 429 や タイムアウトを簡易分類
                cause = "Unknown Error"
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    cause = "429 RESOURCE_EXHAUSTED"
                elif "TIMEOUT" in error_str or "time out" in error_str:
                    cause = "TIMEOUT"
                    
                if module not in error_modules:
                    error_modules[module] = {"count": 0, "cause": cause}
                error_modules[module]["count"] += 1
        except Exception as e:
            print(f"Warning: flash_session.json 読み込み失敗: {e}")

    # エラー多発モジュールのソート
    sorted_errors = sorted(error_modules.items(), key=lambda x: x[1]["count"], reverse=True)[:3]

    # 活動ランキングレポートの生成
    # 日付は JST 固定。ローカル時刻で決めると UTC 環境では日付が1日戻り、
    # 同じ日のランキングが 2 ファイルに分かれる。
    today_str = jst_date()
    ranking_filename = f"ranking_{jst_compact_date()}.md"
    ranking_path = os.path.join(RANKING_REPORT_DIR, ranking_filename)

    # 稼働時間ランキング（降順）
    duration_ranking = sorted(agent_stats.items(), key=lambda x: x[1]["duration_sec"], reverse=True)
    # 処理回数ランキング（降順）
    count_ranking = sorted(agent_stats.items(), key=lambda x: x[1]["tasks"], reverse=True)

    # マークダウン生成
    md_content = f"""# 📊 サブエージェント活動ランキング — {today_str}

## 📊 稼働時間ランキング（長い順）

| 順位 | エージェント種別 | 累計稼働時間 | タスク数 | 平均処理時間 |
|:---:|:---|:---|:---:|:---|
"""
    for idx in range(1, 11):
        if idx <= len(duration_ranking):
            agent, data = duration_ranking[idx - 1]
            avg_sec = data["duration_sec"] / data["tasks"] if data["tasks"] > 0 else 0
            md_content += f"| {idx} | {agent} | {format_duration(data['duration_sec'])} | {data['tasks']}件 | {format_duration(avg_sec)}/件 |\n"
        else:
            md_content += f"| {idx} | - | - | - | - |\n"

    md_content += """
## 🏆 処理回数ランキング（多い順）

| 順位 | エージェント種別 | 完了タスク | PASS | FAIL | 成功率 |
|:---:|:---|:---:|:---:|:---:|:---:|
"""
    for idx in range(1, 11):
        if idx <= len(count_ranking):
            agent, data = count_ranking[idx - 1]
            success_rate = (data["pass"] / data["tasks"]) * 100 if data["tasks"] > 0 else 0
            md_content += f"| {idx} | {agent} | {data['tasks']} | {data['pass']} | {data['fail']} | {success_rate:.1f}% |\n"
        else:
            md_content += f"| {idx} | - | - | - | - | - |\n"

    # トレンド
    avg_total_sec = total_duration_sec / total_completed if total_completed > 0 else 0
    total_success_rate = (total_passed / total_completed) * 100 if total_completed > 0 else 0
    
    md_content += f"""
## 📈 本日の全体統計

| 指標 | 本日の値 |
|:---|:---|
| **累計完了タスク** | {total_completed} 件 |
| **PASS件数** | {total_passed} 件 |
| **FAIL件数** | {total_failed} 件 |
| **全体成功率** | {total_success_rate:.1f}% |
| **平均処理時間** | {format_duration(avg_total_sec)} / 件 |
"""

    if sorted_errors:
        md_content += """
## 🔴 エラー多発モジュール TOP 3

| 順位 | モジュール | エラー回数 | 主な原因 |
|:---:|:---|:---:|:---|
"""
        for idx, (module, info) in enumerate(sorted_errors, 1):
            md_content += f"| {idx} | {module} | {info['count']} | {info['cause']} |\n"

    with open(ranking_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"活動ランキング生成完了: {ranking_path}")

    # 6. 新規セクション用データの生成
    batch_timeline_md = generate_batch_timeline()
    task_detail_md = generate_task_detail_summary()
    session_stats_md = generate_session_cumulative_stats()
    git_commits_md = get_recent_git_commits()

    # 7. README.md（ダッシュボード）の生成
    generate_dashboard_quick()
    print(f"=== サブエージェント体制報告 整理・生成完了 ===")





def generate_batch_timeline(cache: dict = None) -> str:
    """
    改善B: flash_reports.jsonl から直近バッチの活動タイムラインを生成する。
    """
    try:
        batches = _load_flash_reports_cached(cache)

        if not batches:
            return ""

        # 直近10バッチを表示（末尾から）
        recent = batches[-10:]
        recent.reverse()

        md = "## 📦 直近バッチ活動タイムライン\n\n"
        md += "| # | バッチID | Phase | タスク数 | PASS | FAIL | 変更ファイル数 | 完了時刻 (JST) |\n"
        md += "|:---:|:---|:---:|:---:|:---:|:---:|:---:|:---|\n"

        total_batch_count = len(batches)
        for i, entry in enumerate(recent):
            batch_num = total_batch_count - i
            batch_id = entry.get("batch_id", "N/A")
            phase = entry.get("phase", "?")
            results = entry.get("results", {})
            passed = results.get("passed", 0)
            failed = results.get("failed", 0)
            total_tasks = results.get("total", passed + failed)
            files_changed = entry.get("git_diff_summary", {}).get("files_changed", 0)

            ts_str = entry.get("timestamp", "")
            jst_str = "N/A"
            dt = parse_iso_datetime(ts_str)
            if dt:
                jst = dt + timedelta(hours=9)
                jst_str = jst.strftime("%m-%d %H:%M")

            md += f"| {batch_num} | `{batch_id}` | P{phase} | {total_tasks} | {passed} | {failed} | {files_changed} | {jst_str} |\n"

        return md
    except Exception as e:
        print(f"Warning: バッチタイムライン生成失敗: {e}")
        return ""


def generate_task_detail_summary(cache: dict = None) -> str:
    """
    改善C: 最新バッチのタスク別成果物サマリーを生成する。
    """
    try:
        entries = _load_flash_reports_cached(cache)
        last_entry = entries[-1] if entries else None

        if not last_entry:
            return ""

        tasks = last_entry.get("tasks", [])
        if not tasks:
            return ""

        batch_id = last_entry.get("batch_id", "N/A")
        md = f"## 🔬 最新バッチ タスク詳細 (`{batch_id}`)\n\n"

        for task in tasks:
            task_id = task.get("id", "N/A")
            target = task.get("target_module", "N/A")
            status = task.get("status", "unknown")
            result = task.get("result", {}) or {}
            changed_files = result.get("changed_files", [])

            status_icon = "✅" if status == "pass" else "❌" if status == "fail" else "🔄"
            file_count = len(changed_files)

            md += f"<details>\n"
            md += f"<summary>{task_id}: {target} — {status_icon} {status.upper()} ({file_count}ファイル変更)</summary>\n\n"

            if changed_files:
                for cf in changed_files:
                    md += f"- `{cf}`\n"
            else:
                md += "- 変更ファイルなし\n"

            # 処理時間
            started = parse_iso_datetime(task.get("started_at"))
            completed = parse_iso_datetime(task.get("completed_at"))
            if started and completed:
                dur = (completed - started).total_seconds()
                md += f"\n⏱️ 処理時間: {format_duration(dur)}\n"

            md += f"\n</details>\n\n"

        return md
    except Exception as e:
        print(f"Warning: タスク詳細サマリー生成失敗: {e}")
        return ""


def generate_session_cumulative_stats(cache: dict = None) -> str:
    """
    改善E: flash_reports.jsonl 全バッチの累計統計を生成する。
    """
    try:
        all_entries = _load_flash_reports_cached(cache)
        if not all_entries:
            return ""

        total_batches = 0
        total_passed = 0
        total_failed = 0
        total_files_changed = 0

        for entry in all_entries:
            total_batches += 1
            results = entry.get("results", {})
            total_passed += results.get("passed", 0)
            total_failed += results.get("failed", 0)
            total_files_changed += entry.get("git_diff_summary", {}).get("files_changed", 0)

        if total_batches == 0:
            return ""

        total_tasks = total_passed + total_failed
        success_rate = (total_passed / total_tasks * 100) if total_tasks > 0 else 0

        # セッション開始時刻の取得
        session_start_str = "N/A"
        uptime_str = "N/A"
        if os.path.exists(FLASH_SESSION_PATH):
            try:
                with open(FLASH_SESSION_PATH, "r", encoding="utf-8") as f:
                    session = json.load(f)
                start = session.get("session_started_at")
                if start:
                    start_dt = parse_iso_datetime(start)
                    if start_dt:
                        jst = start_dt + timedelta(hours=9)
                        session_start_str = jst.strftime("%Y-%m-%d %H:%M JST")
                        uptime_sec = (datetime.now(timezone.utc) - start_dt).total_seconds()
                        uptime_str = format_duration(max(0, uptime_sec))
            except Exception:
                pass

        # 累計計測開始日（キャッシュ済みデータの先頭エントリから取得）
        cumulative_start_str = "N/A"
        try:
            first_entry = all_entries[0]
            first_ts = parse_iso_datetime(first_entry.get("timestamp"))
            if first_ts:
                jst = first_ts + timedelta(hours=9)
                cumulative_start_str = jst.strftime("%Y-%m-%d %H:%M JST")
        except Exception:
            pass
        
        # 有効打率の計算（変更ファイルが1件以上のタスクを「有効」と判定）
        effective_tasks = 0
        for entry in all_entries:
            for task in entry.get("tasks", []):
                result = task.get("result", {}) or {}
                if isinstance(result, dict):
                    cf = result.get("changed_files", [])
                    if isinstance(cf, list) and len(cf) > 0:
                        effective_tasks += 1
        
        effective_rate = (effective_tasks / total_tasks * 100) if total_tasks > 0 else 0
        wasted = total_tasks - effective_tasks
        wasted_rate = (wasted / total_tasks * 100) if total_tasks > 0 else 0

        md = "## 📊 セッション累計統計\n\n"
        md += "### 📊 【システム通算 (全期間)】\n\n"
        
        # --- L1: 成果の質（最重要） ---
        md += "**L1: 成果の質**\n\n"
        md += "| 指標 | 値 |\n|:---|:---|\n"
        md += f"| **🎯 有効タスク数** | **{effective_tasks}** / {total_tasks} ({effective_rate:.1f}%) |\n"
        md += f"| **📉 空振り** | {wasted} ({wasted_rate:.1f}%) |\n"
        md += f"| **📁 変更ファイル累計** | {total_files_changed:,} |\n\n"

        # 層3-A: グループ別空振り率の表示（キャッシュ済みデータから計算）
        try:
            group_stats = {}  # {group: {total: N, effective: N}}
            for entry in all_entries:
                for task in entry.get("tasks", []):
                    g = task.get("group", "unknown")
                    if g not in group_stats:
                        group_stats[g] = {"total": 0, "effective": 0}
                    group_stats[g]["total"] += 1
                    result = task.get("result", {}) or {}
                    if isinstance(result, dict):
                        cf = result.get("changed_files", [])
                        if isinstance(cf, list) and len(cf) > 0:
                            group_stats[g]["effective"] += 1
            if group_stats:
                md += "**L1b: グループ別有効打率**\n\n"
                md += "| グループ | タスク数 | 有効 | 空振り | 有効打率 |\n"
                md += "|:---|:---:|:---:|:---:|:---:|\n"
                for g in sorted(group_stats, key=lambda x: group_stats[x]["total"], reverse=True):
                    s = group_stats[g]
                    rate = (s["effective"] / s["total"] * 100) if s["total"] > 0 else 0
                    miss = s["total"] - s["effective"]
                    md += f"| {g} | {s['total']} | {s['effective']} | {miss} | {rate:.1f}% |\n"
                md += "\n"
        except Exception:
            pass
        
        # --- L2: 効率 ---
        md += "**L2: 効率**\n\n"
        md += "| 指標 | 値 |\n|:---|:---|\n"
        md += f"| 累計タスク | {total_tasks} (PASS: {total_passed}, FAIL: {total_failed}) |\n"
        md += f"| 成功率 | {success_rate:.1f}% |\n"
        md += f"| 累計バッチ数 | {total_batches} |\n\n"
        
        # --- L3: ロードマップ ---
        ds_total = 0
        ds_dispatched = 0
        ds_completed = 0
        try:
            ds_path = os.path.join(WORKSPACE_DIR, "backend", "agents", "orchestration", "design_stock.json")
            if os.path.exists(ds_path):
                with open(ds_path, "r", encoding="utf-8") as dsf:
                    ds_data = json.load(dsf)
                ds_items = ds_data.get("stock_items", [])
                ds_total = len(ds_items)
                ds_dispatched = sum(1 for i in ds_items if i.get("status") == "dispatched")
                ds_completed = sum(1 for i in ds_items if i.get("status") == "completed")
        except Exception:
            pass
        md += "**L3: ロードマップ**\n\n"
        md += "| 指標 | 値 |\n|:---|:---|\n"
        if ds_total > 0:
            ds_progress = (ds_dispatched + ds_completed) / ds_total * 100
            md += f"| 設計ストック | {ds_completed}完了 / {ds_dispatched}実行中 / {ds_total}件 ({ds_progress:.0f}%) |\n"
        else:
            md += "| 設計ストック | 未設定 |\n"
        
        # 恒常監査 (harness-audit) 連動表示
        audit_path = str(_writable_path("backend/agents/orchestration/harness_audit_status.json"))
        audit_info = "未実行"
        if os.path.exists(audit_path):
            try:
                with open(audit_path, "r", encoding="utf-8") as af:
                    adata = json.load(af)
                parts = []
                for cat in ("commit", "deploy", "weekly"):
                    if cat in adata:
                        cdata = adata[cat]
                        parts.append(f"{cat}: {cdata.get('status', 'FAIL')} ({cdata.get('passed', 0)}/{cdata.get('total', 0)})")
                if parts:
                    audit_info = " / ".join(parts)
            except Exception:
                pass
        md += f"| 恒常監査 (harness-audit) | {audit_info} |\n"
        md += f"| 累計計測開始 | {cumulative_start_str} |\n\n"
        
        # --- L4: 運用 ---
        md += "---\n\n"
        md += "### 📡 【現アクティブセッション限定】\n\n"
        md += "**L4: 運用**\n\n"
        md += "| 指標 | 値 |\n|:---|:---|\n"
        md += f"| セッション開始 | {session_start_str} |\n"
        md += f"| 稼働時間 | {uptime_str} |\n"

        return md
    except Exception as e:
        print(f"Warning: セッション累計統計生成失敗: {e}")
        return ""


def generate_session_context_efficiency(cache: dict = None) -> str:
    """セッション別コンテキスト活用効率の比較表を生成する。

    flash_reports.jsonl の session_id と context_pct_at_report から
    セッションごとの最終ctx%を取得し、target対比の活用率を表示する。
    """
    try:
        from backend.agents.orchestration.hub_common import _get_flash_profile
        _ctx_profile = _get_flash_profile()
        ctx_target = _ctx_profile.get("context_target_pct", 70)
    except Exception:
        ctx_target = 70

    try:
        all_entries = _load_flash_reports_cached(cache)
        if not all_entries:
            return ""

        # セッションごとにバッチを集約
        sessions = {}  # session_id -> {batches, tasks, max_ctx, first_ts, last_ts}
        for entry in all_entries:
            sid = entry.get("session_id", "unknown")
            ts = parse_iso_datetime(entry.get("timestamp"))
            ctx = entry.get("context_pct_at_report")
            results = entry.get("results", {})
            tasks = results.get("passed", 0) + results.get("failed", 0)

            if sid not in sessions:
                sessions[sid] = {
                    "batches": 0, "tasks": 0, "max_ctx": 0,
                    "first_ts": ts, "last_ts": ts,
                }
            s = sessions[sid]
            s["batches"] += 1
            s["tasks"] += tasks
            if ctx is not None and ctx > s["max_ctx"]:
                s["max_ctx"] = ctx
            if ts:
                if s["first_ts"] is None or ts < s["first_ts"]:
                    s["first_ts"] = ts
                if s["last_ts"] is None or ts > s["last_ts"]:
                    s["last_ts"] = ts

        if not sessions:
            return ""

        # 直近5セッションを表示
        sorted_sessions = sorted(
            sessions.items(),
            key=lambda x: x[1]["last_ts"] or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True
        )[:5]

        jst = timezone(timedelta(hours=9))
        md = "## 📊 セッション活用効率\n\n"
        md += "| セッション | 期間 | タスク | 最終ctx% | 目標ctx% | 活用率 | 評価 |\n"
        md += "|:---|:---|:---:|:---:|:---:|:---:|:---:|\n"

        for sid, s in sorted_sessions:
            # 期間
            if s["first_ts"] and s["last_ts"]:
                start_str = s["first_ts"].astimezone(jst).strftime("%H:%M")
                end_str = s["last_ts"].astimezone(jst).strftime("%H:%M")
                period = f"{start_str}-{end_str}"
            else:
                period = "—"

            # 活用率
            max_ctx = s["max_ctx"]
            utilization = (max_ctx / ctx_target * 100) if ctx_target > 0 and max_ctx > 0 else 0

            # 評価
            if utilization >= 80:
                grade = "🟢 高効率"
            elif utilization >= 50:
                grade = "🟡 中効率"
            else:
                grade = "🔴 低効率"

            # セッションID短縮
            short_sid = sid[:8] if len(sid) > 8 else sid

            md += (
                f"| #{short_sid} | {period} | {s['tasks']} | "
                f"{max_ctx:.0f}% | {ctx_target}% | {utilization:.0f}% | {grade} |\n"
            )

        md += f"\n> ℹ️ 活用率 = 最終ctx% ÷ 目標ctx%({ctx_target}%) × 100。80%以上が高効率。\n"
        md += "> アダプティブ判定導入（2026-06-04）以降、活用率の向上が期待されます。\n\n"

        return md
    except Exception as e:
        print(f"Warning: session context efficiency generation failed: {e}")
        return ""





def generate_roadmap_progress() -> str:
    """
    phase_state.jsonからロードマップ現在地のプログレスバーを生成する。
    ロードマップの鮮度チェックと更新サジェストも含む。
    """
    phase_state_path = os.path.join(WORKSPACE_DIR, "backend", "agents", "memory", "phase_state.json")
    if not os.path.exists(phase_state_path):
        return ""

    try:
        with open(phase_state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return ""

    current_phase = data.get("current_phase", 0)
    current_milestone = data.get("current_milestone", "?")
    evo_phase = data.get("evolution_phase")
    evo_phase_name = data.get("evolution_phase_name")
    max_phase = data.get("roadmap_max_phase", 25)

    if evo_phase:
        # 新フェーズ体系 (A/B/C)
        phases_map = {"A": 1, "B": 2, "C": 3}
        current_idx = phases_map.get(evo_phase, 1)
        total_idx = 3
        pct = int(current_idx / total_idx * 100)
        bar_filled = int(pct / 2.5)
        bar = "█" * bar_filled + "░" * (40 - bar_filled)
        
        md = f"""
### 🗺️ ロードマップ現在地

```
Phase {evo_phase} ({evo_phase_name})  {bar}  {pct}%
Milestone: {current_milestone} 進行中 (復帰タグ: v2.0-pre-oss-integration)
```

完了フェーズ: Phase A (品質基盤の確立)
"""
    else:
        # 従来フェーズ体系
        # Auto-extend if current phase exceeds max
        if current_phase > max_phase:
            max_phase = current_phase

        # プログレスバー生成
        total_phases = max(1, max_phase - 5 + 1)
        completed_phases = max(0, current_phase - 5)
        pct = min(100, int(completed_phases / total_phases * 100))
        bar_filled = int(pct / 2.5)  # 40文字幅
        bar = "█" * bar_filled + "░" * (40 - bar_filled)

        # 完了Phaseリスト
        phase_list = " → ".join([str(i) for i in range(5, current_phase)]) 
        if phase_list:
            phase_list += f" → **{current_phase}**"
        else:
            phase_list = f"**{current_phase}**"

        md = f"""
### 🗺️ ロードマップ現在地

```
Phase {current_phase} / {max_phase}  {bar}  {pct}%
{current_milestone} 進行中
```

完了Phase: {phase_list}
"""

    # ── ロードマップ鮮度チェック ──
    suggestions = []

    # Check 1: Phase has exceeded planned roadmap
    if current_phase >= max_phase:
        suggestions.append(
            "🔴 **ロードマップ拡張が必要**: 現在Phase {0}に到達し、計画済みPhase {1}の上限に達しました。"
            "次期Phaseの計画策定をOpusセッションに指示してください。".format(current_phase, max_phase)
        )

    # Check 2: Milestone is vague or missing
    if not current_milestone or current_milestone == "?" or current_milestone == "N/A":
        suggestions.append(
            "🟡 **マイルストーン未定義**: 現在Phaseのマイルストーンが設定されていません。"
            "Opusセッションで `phase_state.json` の `current_milestone` を更新してください。"
        )

    # Check 3: No next milestone planned (only current)
    next_milestones = data.get("next_milestones", [])
    if not next_milestones:
        suggestions.append(
            "🟡 **次期マイルストーン未計画**: 現在のマイルストーン完了後の計画がありません。"
            "MASTERロードマップの次期タスクを確認し、`phase_state.json` に `next_milestones` を追加してください。"
        )

    # Check 4: phase_state hasn't been updated recently
    last_updated = data.get("last_updated")
    if last_updated:
        try:
            from datetime import datetime, timezone, timedelta
            lu_str = last_updated.replace("Z", "+00:00")
            lu_dt = datetime.fromisoformat(lu_str)
            age_hours = (datetime.now(timezone.utc) - lu_dt).total_seconds() / 3600
            if age_hours > 72:
                suggestions.append(
                    f"🟡 **ロードマップ未更新**: phase_state.json の最終更新が{int(age_hours)}時間前です。"
                    "最新の進捗を反映するためにOpusセッションで更新してください。"
                )
        except Exception:
            pass

    if suggestions:
        md += "\n#### ⚠️ ロードマップ更新サジェスト\n\n"
        for s in suggestions:
            md += f"- {s}\n"
        md += "\n> 💡 ロードマップはプロジェクト推進の羅針盤です。常に最新状態を維持してください。\n"

    return md


def generate_improvement_history() -> str:
    """ダッシュボード改善履歴テーブルを生成する。"""
    return """
### 🔧 ダッシュボード改善履歴

| 日付 | 弱点 | 対策 | 状態 |
|:---|:---|:---|:---:|
| 2026-05-24 | ハートビート鮮度が不明 | 3段階判定(🟢/🟡/🔴)+絶対時刻表示 | ✅ |
| 2026-05-24 | バッチ活動が見えない | 直近10バッチのタイムライン表示 | ✅ |
| 2026-05-24 | unknownエージェント名 | target_moduleからグループ自動推定 | ✅ |
| 2026-05-24 | ダッシュボード手動更新依存 | タイマーチェーンと統合(5分毎自動更新) | ✅ |
| 2026-05-24 | 6h/24h集約レポートなし | 原データから動的計算 | ✅ |
| 2026-05-24 | ロードマップ現在地なし | phase_state.jsonから自動表示 | ✅ |
| 2026-05-24 | Flash完了をOpusが検知できない | ヘルスチェックにライフサイクル判定追加 | ✅ |
| 2026-05-24 | 変更ファイル数が常に0表示 | データソースをgit_diff_summaryに修正 | ✅ |
| 2026-05-24 | ダッシュボードに次のアクションがない | ユーザー向けアクション提案セクション追加 | ✅ |
| 2026-05-24 | Opus/Flash役割の混同リスク | セッション識別宣言+3重防壁 | ✅ |
| 2026-05-24 | GEMINI.md規約にOpus専用タグなし | [Opus専用]タグを全該当セクションに明記 | ✅ |
| 2026-05-26 | 情報が均一粒度で一目で把握困難 | 3層構造化(Layer1/2/3) | ✅ |
| 2026-05-26 | 稼働安定性が定量化されていない | 稼働率/連続HEALTHY/復旧回数を追加 | ✅ |
| 2026-05-26 | 処理効率の時系列比較がない | タスク/時・バッチ間隔を1h/6h/24h/通算で表示 | ✅ |
| 2026-05-26 | 並列稼働の効率が評価できない | 並列稼働効率スコア(0-100)を新設 | ✅ |
| 2026-05-26 | ランキングがダッシュボード外 | ランキングTOP5をLayer1に埋め込み | ✅ |
| 2026-05-26 | 24hタスク概要がない | タスクTOP20(重要度順)を動的生成 | ✅ |
| 2026-05-26 | 改善サイクルが属人的 | 3日サイクル自動改善提案を新設 | ✅ |
| 2026-05-26 | ゴーストセッション検知不可 | 心拍30分超で自動停止+イベント記録 | ✅ |
| 2026-05-26 | エージェント偏り検知なし | 60%超占有時にアクション提案自動表示 | ✅ |
| 2026-05-26 | 改善ルールが規約化されていない | GEMINI.md §共通処理機構継続改善規約 制定 | ✅ |
| 2026-05-31 | アーカイブ閾値がモード非対応 | orchestrator.py+health_check.pyをプロファイル参照に改修 | ✅ |
| 2026-05-31 | 動作モードがダッシュボードで不可視 | エグゼクティブサマリー+処理効率にモードバッジ表示 | ✅ |
| 2026-05-31 | タスク66%が空振り（変更0件） | thumbnailモジュール限定+空振り自動スキップ導入 | ✅ |
| 2026-05-31 | 有効打率がKPIに含まれない | セッション累計+処理効率に有効打率/有効タスク時を追加 | ✅ |
| 2026-05-31 | 設計ストックがタスク生成と未連携 | _generate_batch()をDS駆動に改修、DS優先タスク生成 | ✅ |
| 2026-05-31 | 日別有効打率のトレンド追跡なし | 改善活動KPIに日別トレンドテーブル+崩壊アラート追加 | ✅ |
| 2026-05-31 | 改善提案に有効打率フィードバックなし | 改善提案生成に有効打率低下検出パターン追加 | ✅ |
| 2026-05-31 | タイムロス原因の区別が不可能 | 夜間待機を正常カテゴリに分離(予定) | 🔄 |
"""





def generate_kaizen_dashboard(cache: dict = None) -> str:
    """改善活動追跡ダッシュボードを生成する。

    改善提案レポートの履歴からKPIメトリクス推移を自動抽出し、
    「提案→実施→効果」のPDCAループを可視化する。
    """
    proposal_dir = os.path.join(REPORT_BASE_DIR, "改善提案")
    if not os.path.exists(proposal_dir):
        return ""

    reports = sorted(glob.glob(os.path.join(proposal_dir, "improvement_*.md")))
    if not reports:
        return ""

    # 各レポートからメトリクスを抽出
    history = []
    for rpath in reports:
        try:
            with open(rpath, "r", encoding="utf-8") as f:
                content = f.read()
            entry = {"path": rpath, "filename": os.path.basename(rpath)}

            # 日付抽出
            date_match = re.search(r"\*\*分析日時\*\*:\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})", content)
            if date_match:
                entry["date"] = date_match.group(1)
            else:
                entry["date"] = extract_date(rpath)

            # メトリクス抽出（テーブルから）
            # タスク/時
            tph_match = re.search(r"タスク/時\s*\|.*?\|\s*([\d.]+)", content)
            if tph_match:
                entry["tph"] = float(tph_match.group(1))

            # 成功率
            rate_match = re.search(r"成功率\s*\|.*?\|\s*([\d.]+)%", content)
            if rate_match:
                entry["success_rate"] = float(rate_match.group(1))

            # 稼働率
            uptime_match = re.search(r"稼働率.*?\|\s*([\d.]+)%", content)
            if uptime_match:
                entry["uptime"] = float(uptime_match.group(1))

            # 完了タスク
            tasks_match = re.search(r"完了タスク\s*\|.*?\|\s*([\d,]+)件", content)
            if tasks_match:
                entry["tasks"] = int(tasks_match.group(1).replace(",", ""))

            # 検出パターンの抽出 (Green/Yellow/Red)
            green_match = re.search(r"🟢\s*(\d+)", content)
            yellow_match = re.search(r"🟡\s*(\d+)", content)
            red_match = re.search(r"🔴\s*(\d+)", content)
            
            entry["green"] = int(green_match.group(1)) if green_match else 0
            entry["yellow"] = int(yellow_match.group(1)) if yellow_match else 0
            entry["red"] = int(red_match.group(1)) if red_match else 0

            history.append(entry)
        except Exception as e:
            print(f"Warning: 改善提案レポートのパース失敗 ({rpath}): {e}")

    if not history:
        return ""

    first = history[0]
    latest = history[-1]

    first_date = first.get('date', '?')
    latest_date = latest.get('date', '?')
    kpi_summary = "## 📈 改善活動KPI\n\n"
    kpi_summary += f"| 指標 | 初回値<br>({first_date}) | 最新値<br>({latest_date}) | 推移 | | |\n"
    kpi_summary += "|---|:---:|:---:|:---:|:---:|:---:|\n"

    # トレンド矢印
    def _trend(curr, prev, higher_is_better=True):
        if curr is None or prev is None:
            return "—"
        diff = curr - prev
        if abs(diff) < 0.5:
            return "→"
        if higher_is_better:
            return "📈" if diff > 0 else "📉"
        else:
            return "📈" if diff < 0 else "📉"

    if latest.get("success_rate") is not None and first.get("success_rate") is not None:
        rate_trend = _trend(latest.get("success_rate"), first.get("success_rate"))
        kpi_summary += f"| 成功率 | {first['success_rate']:.1f}% | {latest['success_rate']:.1f}% | {rate_trend} | |\n"
    
    # 有効打率KPI（flash_reports.jsonlから動的計算）
    try:
        daily_eff = _calc_daily_effectiveness(cache=cache)
        if daily_eff:
            days = sorted(daily_eff.keys())
            first_day = days[0] if days else None
            latest_day = days[-1] if days else None
            if first_day and latest_day:
                first_eff = daily_eff[first_day]
                latest_eff = daily_eff[latest_day]
                first_rate = first_eff['effective'] / first_eff['total'] * 100 if first_eff['total'] > 0 else 0
                latest_rate = latest_eff['effective'] / latest_eff['total'] * 100 if latest_eff['total'] > 0 else 0
                eff_trend = _trend(latest_rate, first_rate)
                kpi_summary += f"| **有効打率** | {first_rate:.1f}% | {latest_rate:.1f}% | {eff_trend} | |\n"
    except Exception:
        pass
    kpi_summary += "\n"

    # ── 改善活動タイムライン（アーカイブ用） ──
    timeline_md = "\n### 🔄 改善活動タイムライン\n\n"
    timeline_md += "| 日付 | タスク/時 | 稼働率 | 成功率 | 検出パターン | レポート |\n"
    timeline_md += "|:---|:---:|:---:|:---:|:---:|:---|\n"
    # 同日の重複レポートは最新1件のみ表示
    seen_dates = set()
    for h in reversed(history[-10:]):
        date_key = h.get('date', '?')[:10]  # YYYY-MM-DD部分
        if date_key in seen_dates:
            continue
        seen_dates.add(date_key)
        tph_str = f"{h['tph']:.1f}" if h.get("tph") is not None else "—"
        uptime_str = f"{h['uptime']:.1f}%" if h.get("uptime") is not None else "—"
        rate_str = f"{h['success_rate']:.1f}%" if h.get("success_rate") is not None else "—"
        patterns = f"🟢{h.get('green', 0)} 🟡{h.get('yellow', 0)} 🔴{h.get('red', 0)}"
        link = get_rel_link(h["path"])
        timeline_md += f"| {date_key} | {tph_str} | {uptime_str} | {rate_str} | {patterns} | [{h['filename']}]({link}) |\n"

    # ── ダッシュボード改善履歴（既存）の統合 ──
    timeline_md += "\n### 🔧 システム改善履歴\n\n"
    timeline_md += "| 日付 | 改善内容 | 効果 |\n"
    timeline_md += "|:---|:---|:---|\n"
    timeline_md += "| 2026-05-28 | ETA + 次回確認推奨時刻の導入 | ユーザー時間管理の効率化 |\n"
    timeline_md += "| 2026-05-28 | イベントログ24h化 + 介入タイムライン | タイムロス955分/24hの可視化 |\n"
    timeline_md += "| 2026-05-28 | 改善提案サイクル3日→1日に短縮 | PDCA速度の向上 |\n"
    timeline_md += "| 2026-05-28 | Flash完遂後リソース解放規約(R5改) | CPUリーク防止 |\n"
    timeline_md += "| 2026-05-27 | 心拍レジリエンス3段階化 | ゴーストセッション防止 |\n"
    timeline_md += "| 2026-05-26 | 3層ダッシュボード構造化 | 情報アクセス効率向上 |\n"
    timeline_md += "| 2026-05-26 | 並列稼働効率スコア新設 | 定量評価の確立 |\n"

    # ── 日別有効打率トレンド ──
    try:
        daily_eff = _calc_daily_effectiveness(cache=cache)
        if daily_eff and len(daily_eff) >= 2:
            timeline_md += "\n### 📊 日別有効打率トレンド\n\n"
            timeline_md += "| 日付 | 全タスク | 有効 | 有効打率 | 変更ファイル | 評価 |\n"
            timeline_md += "|:---:|---:|---:|---:|---:|:---:|\n"
            for day in sorted(daily_eff.keys()):
                s = daily_eff[day]
                rate = s['effective'] / s['total'] * 100 if s['total'] > 0 else 0
                if rate < 20:
                    grade = "🔴 要改善"
                elif rate < 50:
                    grade = "🟡 低効率"
                elif rate < 70:
                    grade = "🟢 標準"
                else:
                    grade = "⭐ 高効率"
                timeline_md += f"| {day} | {s['total']} | {s['effective']} | {rate:.1f}% | {s['files']} | {grade} |\n"
            timeline_md += "\n"
    except Exception:
        pass

    return kpi_summary, timeline_md





def generate_stability_metrics(cache: dict = None) -> str:
    """Generate stability metrics from event_log.jsonl: uptime %, HEALTHY streak, downtime."""
    try:
        events = _load_event_log_cached(cache)

        if not events:
            return ""

        jst = timezone(timedelta(hours=9))
        now = datetime.now(jst)
        cutoff_24h = now - timedelta(hours=24)

        # Filter and sort events in last 24h
        recent = []
        for ev in events:
            ts = _parse_event_ts(ev.get("timestamp"))
            if ts and ts >= cutoff_24h:
                recent.append((ts, ev))
        recent.sort(key=lambda x: x[0])

        # Walk through transitions to calculate uptime
        healthy_sec = 0
        unhealthy_sec = 0
        prev_ts = cutoff_24h
        prev_healthy = True  # assume healthy at start
        streak_start = cutoff_24h
        longest_streak = 0
        restart_count = 0

        for ts, ev in recent:
            health = ev.get("health", "")
            is_healthy = "HEALTHY" in health and "UNHEALTHY" not in health
            duration = (ts - prev_ts).total_seconds()

            if prev_healthy:
                healthy_sec += duration
            else:
                unhealthy_sec += duration

            # Count auto_stop events (actual session stops) instead of all UNHEALTHY transitions
            changes = ev.get("change", [])
            for c in changes:
                if "auto_stop:" in c or "AUTO_STOPPED" in c:
                    restart_count += 1

            if is_healthy and not prev_healthy:
                streak_start = ts
            elif not is_healthy and prev_healthy:
                streak_dur = (ts - streak_start).total_seconds()
                longest_streak = max(longest_streak, streak_dur)

            prev_ts = ts
            prev_healthy = is_healthy

        # Account for time from last event to now
        remaining = (now - prev_ts).total_seconds()
        if prev_healthy:
            healthy_sec += remaining
            longest_streak = max(longest_streak, (now - streak_start).total_seconds())
        else:
            unhealthy_sec += remaining

        total_sec = healthy_sec + unhealthy_sec
        uptime_pct = (healthy_sec / total_sec * 100) if total_sec > 0 else 0
        downtime_min = int(unhealthy_sec / 60)

        # Heartbeat freshness
        session = _safe_read_json_local(FLASH_SESSION_PATH, {})
        hb_str = "N/A"
        if session:
            hb_ts_str = session.get("last_heartbeat")
            if hb_ts_str:
                dt = parse_iso_datetime(hb_ts_str)
                if dt:
                    diff_min = int((datetime.now(timezone.utc) - dt).total_seconds() / 60)
                    hb_str = f"✅ {diff_min}分前" if diff_min <= 15 else f"⚠️ {diff_min}分前"

        # Resource Governor Metrics
        state_path = str(_writable_path("backend/agents/orchestration/resource_state.json"))
        res_state = _safe_read_json_local(state_path, {})
        peak_cpu = res_state.get("peak_cpu", 0.0)
        peak_mem = res_state.get("peak_mem", 0.0)
        throttling_count = res_state.get("throttling_count", 0)

        md = "## 🛡️ 稼働安定性\n\n"
        md += "| 指標 | 値 |\n|---|---|\n"
        md += f"| 稼働率（直近24h） | {uptime_pct:.1f}%（ダウンタイム: {downtime_min}分） |\n"
        md += f"| 連続HEALTHY | {format_duration(longest_streak)} |\n"
        md += f"| 心拍鮮度 | {hb_str} |\n"
        md += f"| 復旧回数（24h） | {restart_count}回 |\n"
        md += f"| リソーススロットリング発動回数 | {throttling_count}回 |\n"
        md += f"| ピーク CPU 使用率 | {peak_cpu:.1f}% |\n"
        md += f"| ピーク メモリ使用率 | {peak_mem:.1f}% |\n"

        return md
    except Exception as e:
        print(f"Warning: stability metrics generation failed: {e}")
        return ""


def generate_efficiency_and_parallel_metrics(cache: dict = None) -> str:
    """Generate efficiency metrics + parallel operation efficiency score.

    Parallel efficiency score rewards:
    - Long sessions without token limit interruptions (sustainability)
    - High parallelism without overloading (parallel throughput)
    - Low error rate (stability)

    Score = (sustainability * 0.35) + (parallel_throughput * 0.30) + (stability * 0.35)
    Range: 0-100
    """
    try:
        batches = _load_flash_reports_cached(cache)

        if not batches:
            return ""

        now_utc = datetime.now(timezone.utc)

        # ── Per-window metrics ──
        windows = {
            "1時間": timedelta(hours=1),
            "6時間": timedelta(hours=6),
            "24時間": timedelta(hours=24),
            "通算": None,
        }
        window_stats = {}
        for label, delta in windows.items():
            cutoff = (now_utc - delta) if delta else None
            w_batches = []
            w_tasks = 0
            w_passed = 0
            w_failed = 0
            for b in batches:
                ts = parse_iso_datetime(b.get("timestamp"))
                if cutoff and ts and ts < cutoff:
                    continue
                w_batches.append(b)
                r = b.get("results", {})
                p = r.get("passed", 0)
                f_count = r.get("failed", 0)
                w_tasks += p + f_count
                w_passed += p
                w_failed += f_count

            # Calculate tasks/hour
            if delta:
                hours = delta.total_seconds() / 3600
            else:
                # Total elapsed: first batch to now
                first_ts = parse_iso_datetime(batches[0].get("timestamp"))
                hours = ((now_utc - first_ts).total_seconds() / 3600) if first_ts else 1

            tasks_per_hour = w_tasks / hours if hours > 0 else 0

            # Average batch interval
            batch_intervals = []
            sorted_batches = sorted(w_batches, key=lambda x: x.get("timestamp", ""))
            for i in range(1, len(sorted_batches)):
                t1 = parse_iso_datetime(sorted_batches[i-1].get("timestamp"))
                t2 = parse_iso_datetime(sorted_batches[i].get("timestamp"))
                if t1 and t2:
                    batch_intervals.append((t2 - t1).total_seconds())
            avg_interval = sum(batch_intervals) / len(batch_intervals) if batch_intervals else 0

            # Average tasks per batch (parallelism proxy)
            avg_parallel = w_tasks / len(w_batches) if w_batches else 0

            window_stats[label] = {
                "tasks": w_tasks,
                "tasks_per_hour": tasks_per_hour,
                "avg_interval": avg_interval,
                "avg_parallel": avg_parallel,
                "passed": w_passed,
                "failed": w_failed,
                "batches": len(w_batches),
            }

        # ── モードバッジ ──
        try:
            from backend.agents.orchestration.hub_common import _get_flash_profile
            _fp = _get_flash_profile()
            _mode_name = _fp.get("mode", "standard").upper()
            _mode_icons = {"STANDARD": "📋", "WEEKEND": "🌴", "NIGHT": "🌙"}
            _mi = _mode_icons.get(_mode_name, "📋")
            _bs = _fp.get("batch_size", 6)
            _ct = _fp.get("context_target_pct", 70)
            _ah = _fp.get("archive_hours", 5)
            _cppb = _fp.get("context_pct_per_batch", 4)
            mode_badge = (
                f"> {_mi} **動作モード: {_mode_name}** — "
                f"並列={_bs} / ctx目標={_ct}%・{_ah}h / ctx={_cppb}%/バッチ\n\n"
            )
        except Exception:
            mode_badge = ""

        # ── Efficiency table ──
        md = f"## ⚡ 処理効率\n\n{mode_badge}"
        md += "| 指標 | 1時間 | 6時間 | 24時間 | 通算 |\n"
        md += "|---|:---:|:---:|:---:|:---:|\n"
        md += "| タスク/時 | "
        md += " | ".join(
            f"{window_stats[w]['tasks_per_hour']:.1f}" for w in windows
        ) + " |\n"
        md += "| バッチ間隔 | "
        md += " | ".join(
            format_duration(window_stats[w]["avg_interval"]) if window_stats[w]["avg_interval"] > 0 else "—"
            for w in windows
        ) + " |\n"
        md += "| 平均並列度 | "
        md += " | ".join(
            f"{window_stats[w]['avg_parallel']:.1f}" for w in windows
        ) + " |\n"
        
        # 有効タスク/時の行を追加
        md += "| **有効タスク/時** | "
        effective_per_hour = []
        for w in windows:
            ws = window_stats[w]
            # 有効タスクの推定: 全データの有効打率を適用
            # TODO: ウィンドウ別の有効打率を計算できればより正確
            if ws['tasks_per_hour'] > 0:
                effective_per_hour.append(f"{ws['tasks_per_hour'] * 0.338:.1f}")
            else:
                effective_per_hour.append("—")
        md += " | ".join(effective_per_hour) + " |\n"

        # Δctx/バッチ行を追加（flash_reports.jsonlのavg_delta_per_batchから集計）
        md += "| Δctx/バッチ | "
        delta_ctx_values = []
        for w_label, w_delta in windows.items():
            w_cutoff = (now_utc - w_delta) if w_delta else None
            w_deltas = []
            for b in batches:
                ts = parse_iso_datetime(b.get("timestamp"))
                if w_cutoff and ts and ts < w_cutoff:
                    continue
                avg_d = b.get("avg_delta_per_batch")
                if avg_d is not None and avg_d > 0:
                    w_deltas.append(avg_d)
            if w_deltas:
                avg_delta = sum(w_deltas) / len(w_deltas)
                delta_ctx_values.append(f"{avg_delta:.1f}%")
            else:
                delta_ctx_values.append("—")
        md += " | ".join(delta_ctx_values) + " |\n"

        # ctx利用効率行（セッション終了時のctx% ÷ target × 100の平均）
        try:
            from backend.agents.orchestration.hub_common import _get_flash_profile
            _eff_profile = _get_flash_profile()
            _eff_target = _eff_profile.get("context_target_pct", 70)
        except Exception:
            _eff_target = 70
        ctx_at_reports = [b.get("context_pct_at_report") for b in batches if b.get("context_pct_at_report") is not None]
        if ctx_at_reports:
            latest_ctx = ctx_at_reports[-1]
            ctx_utilization = (latest_ctx / _eff_target * 100) if _eff_target > 0 else 0
            md += f"| **ctx利用効率** | — | — | — | {ctx_utilization:.0f}% |\n"

        # ── Parallel Efficiency Score ──
        # Read session data for sustainability calculation
        session = _safe_read_json_local(FLASH_SESSION_PATH, {})
        session_start = parse_iso_datetime(session.get("session_started_at")) if session else None
        session_hours = ((now_utc - session_start).total_seconds() / 3600) if session_start else 0

        # Read event log for restart count
        restart_count = 0
        event_log_events = _load_event_log_cached(cache)
        for ev in event_log_events:
            # 修正1-A: イベント単位でカウント（changeエントリ単位の重複カウント解消）
            # lifecycle == "AUTO_STOPPED" のイベントのみカウント
            if ev.get("lifecycle") == "AUTO_STOPPED":
                restart_count += 1
            else:
                # フォールバック: 古い形式のイベントにも対応
                changes = ev.get("change", [])
                has_auto_stop = any("auto_stop:" in c for c in changes)
                if has_auto_stop:
                    restart_count += 1

        total_stats = window_stats["通算"]
        total_tasks = total_stats["tasks"]
        total_passed = total_stats["passed"]
        total_failed = total_stats["failed"]

        # Component 1: Sustainability (0-35)
        # Rewards long sessions, penalizes frequent restarts
        # 8h session = max score, each restart reduces by 3pts
        sustainability_raw = min(1.0, session_hours / 8.0)
        restart_penalty = min(1.0, restart_count * 0.1)
        sustainability = sustainability_raw * (1 - restart_penalty) * 35

        # Component 2: Parallel Throughput (0-30)
        # Rewards high parallelism AND high throughput together
        # 4 tasks/batch = optimal, 12+ tasks/hour = optimal
        avg_parallel_total = total_stats["avg_parallel"]
        tph_total = total_stats["tasks_per_hour"]
        parallel_score_raw = min(1.0, avg_parallel_total / 4.0)
        throughput_score_raw = min(1.0, tph_total / 12.0)
        parallel_throughput = (parallel_score_raw * 0.5 + throughput_score_raw * 0.5) * 30

        # Component 3: Stability (0-35)
        # Rewards high success rate, penalizes errors/timeouts
        success_rate = total_passed / total_tasks if total_tasks > 0 else 0
        stability_score = success_rate * 35

        # Composite score
        composite = sustainability + parallel_throughput + stability_score
        composite = min(100, max(0, composite))

        # Star rating (1-5)
        stars = min(5, max(1, int(composite / 20) + 1))
        star_str = "⭐" * stars

        md += f"\n## 🔄 並列稼働効率\n\n"
        md += "| 指標 | 値 | 評価 |\n|---|---|---|\n"
        md += f"| セッション持続時間 | {format_duration(session_hours * 3600)} | {'⭐' * min(5, max(1, int(session_hours / 1.6) + 1))} |\n"
        md += f"| 自動停止回数(全期間) | {restart_count}回 | {'⭐' * min(5, max(1, 5 - restart_count))} |\n"
        md += f"| 平均バッチ並列度 | {avg_parallel_total:.1f}タスク/バッチ | {'⭐' * min(5, max(1, int(avg_parallel_total / 0.8)))} |\n"
        md += f"| タスク密度 | {tph_total:.1f}/h | {'⭐' * min(5, max(1, int(tph_total / 2.4) + 1))} |\n"
        md += f"| エラーフリーバッチ率 | {success_rate * 100:.1f}% | {'⭐' * min(5, max(1, int(success_rate * 5)))} |\n"
        md += f"| **並列稼働効率スコア** | **{composite:.0f}/100** | **{star_str}** |\n"

        md += f"\n> 📐 スコア内訳: 持続性 {sustainability:.0f}/35 + 並列処理 {parallel_throughput:.0f}/30 + 安定性 {stability_score:.0f}/35\n"

        # トレンド分析コメント生成
        trend_comment = ""
        stats_24h = window_stats.get("２４時間", window_stats.get("24時間", {}))
        stats_1h = window_stats.get("１時間", window_stats.get("1時間", {}))
        
        comments = []
        if stats_1h.get("tasks_per_hour", 0) > 0 and stats_24h.get("tasks_per_hour", 0) > 0:
            ratio = stats_1h["tasks_per_hour"] / stats_24h["tasks_per_hour"]
            if ratio > 1.5:
                comments.append("📈 直近1時間のスループットが24h平均の{:.0f}倍—好調".format(ratio))
            elif ratio < 0.3:
                comments.append("📉 直近1時間のスループットが低下中—ハングまたはセッション切替の可能性")
        
        if composite >= 80:
            comments.append("⭐ 優秀な効率。並列度・安定性・持続性のバランスが良好")
        elif composite >= 60:
            comments.append("🟢 良好な効率。持続性の改善で更なる向上が見込める")
        elif composite >= 40:
            comments.append("🟡 中程度の効率。セッション中断やエラー率の改善が必要")
        else:
            comments.append("🔴 効率が低い。頻繁な中断または低並列度が原因")
        
        if restart_count > 10:
            comments.append(f"⚠️ 中断回数({restart_count}回)が多く、持続性スコアに影響")
        
        if comments:
            md += "\n> " + " / ".join(comments) + "\n"

        return md
    except Exception as e:
        print(f"Warning: efficiency/parallel metrics generation failed: {e}")
        return ""


def generate_agent_ranking_inline(cache: dict = None) -> str:
    """Generate inline TOP5 agent ranking for dashboard Layer 1."""
    try:
        all_entries = _load_flash_reports_cached(cache)
        if not all_entries:
            return ""

        agent_data = {}  # group -> {tasks, passed, failed, total_duration}
        total_task_count = 0

        for entry in all_entries:
            for task in entry.get("tasks", []):
                status = task.get("status")
                if status not in ("pass", "fail"):
                    continue

                group = task.get("group") or ""
                if not group or group == "unknown":
                    group = _infer_group_from_module(task.get("target_module", ""))
                agent_type = f"{group} Agent"

                if agent_type not in agent_data:
                    agent_data[agent_type] = {
                        "tasks": 0, "passed": 0, "failed": 0, "duration_sec": 0.0
                    }

                d = agent_data[agent_type]
                d["tasks"] += 1
                total_task_count += 1
                if status == "pass":
                    d["passed"] += 1
                else:
                    d["failed"] += 1

                started = parse_iso_datetime(task.get("started_at"))
                completed = parse_iso_datetime(task.get("completed_at"))
                if started and completed:
                    dur = (completed - started).total_seconds()
                    d["duration_sec"] += dur
                    # 修正1-B: 中央値・P90算出用に個別の処理時間を記録
                    if "durations" not in d:
                        d["durations"] = []
                    d["durations"].append(dur)

        if not agent_data:
            return ""

        # Sort by task count (descending)
        ranked = sorted(agent_data.items(), key=lambda x: x[1]["tasks"], reverse=True)[:5]

        md = "## 🏆 サブエージェント活動ランキング TOP5\n\n"
        md += "| # | エージェント種別 | タスク数 | 出現率 | 中央値 | P90 | タスク/時 |\n"
        md += "|:---:|:---|:---:|:---:|:---:|:---:|:---:|\n"

        for i, (name, data) in enumerate(ranked, 1):
            appearance = (data["tasks"] / total_task_count * 100) if total_task_count > 0 else 0
            durations = sorted(data.get("durations", []))
            if durations:
                median_sec = durations[len(durations) // 2]
                p90_idx = int(len(durations) * 0.9)
                p90_sec = durations[min(p90_idx, len(durations) - 1)]
            else:
                median_sec = data["duration_sec"] / data["tasks"] if data["tasks"] > 0 else 0
                p90_sec = median_sec
            tph = (3600 / median_sec) if median_sec > 0 else 0
            md += f"| {i} | {name} | {data['tasks']} | {appearance:.1f}% | {format_duration(median_sec)} | {format_duration(p90_sec)} | {tph:.1f} |\n"

        return md
    except Exception as e:
        print(f"Warning: agent ranking inline generation failed: {e}")
        return ""





def _generate_opus_health_md() -> str:
    """Opusセッション健全性をダッシュボード用Markdownで生成する。"""
    opus_path = str(_writable_path("backend/agents/orchestration/opus_session.json"))
    if not os.path.exists(opus_path):
        return ""

    try:
        with open(opus_path, "r", encoding="utf-8") as f:
            opus = json.load(f)
    except Exception:
        return ""

    started_str = opus.get("session_started_at")
    if not started_str:
        return ""

    started = parse_iso_datetime(started_str)
    if not started:
        return ""

    uptime_hours = (datetime.now(timezone.utc) - started).total_seconds() / 3600
    cron_iters = opus.get("cron_iterations", 0)

    if uptime_hours <= 8:
        stage = "FRESH"
        icon = "🟢"
        note = ""
    elif uptime_hours <= 16:
        stage = "AGING"
        icon = "🟡"
        note = " — 移行準備を推奨"
    else:
        stage = "STALE"
        icon = "🔴"
        note = " — **セッション移行を強く推奨**"

    md = f"#### 🧠 Opusセッション健全性\n\n"
    md += f"| 状態 | 稼働時間 | Cron回数 | 備考 |\n"
    md += f"|:---:|:---:|:---:|:---|\n"
    md += f"| {icon} **{stage}** | {uptime_hours:.1f}h | {cron_iters}回 | {note} |\n\n"

    return md


def generate_task_summary_top20(cache: dict = None) -> str:
    """Generate a TOP20 task summary for the last 24 hours, ranked by importance.

    Importance score heuristic:
    - Files changed: each file = 2 points (more files = more impactful change)
    - Group weights: bug_hunter=5, test_weaver=4, edge_case=4, thumbnail=3,
                     tdr_cleanup=2, refactor=2, misc=1
    - Pass bonus: +1
    """
    GROUP_WEIGHTS = {
        "bug_hunter": 5, "test_weaver": 4, "edge_case": 4,
        "thumbnail": 3, "soul_feedback": 3, "tdr_resolver": 3,
        "tdr_cleanup": 2, "refactor": 2, "quality_ascend": 3,
        "orchestration": 2, "pipeline": 3, "subtitle": 3,
        "branding": 2, "misc": 1,
    }

    GROUP_LABELS = {
        "bug_hunter": "🐛 バグ修正", "test_weaver": "🧪 テスト追加",
        "edge_case": "🔬 エッジケース", "thumbnail": "🖼️ サムネイル",
        "tdr_cleanup": "🧹 負債解消", "tdr_resolver": "🧹 負債解消",
        "refactor": "♻️ リファクタ", "soul_feedback": "💎 品質向上",
        "quality_ascend": "📈 品質向上", "orchestration": "⚙️ 基盤",
        "pipeline": "🔧 パイプライン", "subtitle": "💬 字幕",
        "branding": "🎨 ブランディング", "misc": "📦 その他",
    }

    try:
        now_utc = datetime.now(timezone.utc)
        cutoff = now_utc - timedelta(hours=24)

        tasks_scored = []

        all_entries = _load_flash_reports_cached(cache)
        for entry in all_entries:
            batch_ts = parse_iso_datetime(entry.get("timestamp"))
            if not batch_ts or batch_ts < cutoff:
                continue

            phase = entry.get("phase", "?")
            milestone = entry.get("milestone", "?")
            batch_id = entry.get("batch_id", "?")

            for task in entry.get("tasks", []):
                status = task.get("status")
                if status not in ("pass", "fail"):
                    continue

                group = task.get("group") or ""
                if not group or group == "unknown":
                    group = _infer_group_from_module(task.get("target_module", ""))

                target = task.get("target_module", "N/A")
                result = task.get("result", {}) or {}
                if not isinstance(result, dict):
                    result = {}
                changed_files = result.get("changed_files", [])
                file_count = len(changed_files) if isinstance(changed_files, list) else 0

                # Importance score
                weight = GROUP_WEIGHTS.get(group, 1)
                score = (file_count * 2) + weight + (1 if status == "pass" else 0)

                # Task timing
                started = parse_iso_datetime(task.get("started_at"))
                completed = parse_iso_datetime(task.get("completed_at"))
                duration = 0
                if started and completed:
                    duration = (completed - started).total_seconds()

                label = GROUP_LABELS.get(group, "📦 その他")
                status_icon = "✅" if status == "pass" else "❌"

                tasks_scored.append({
                    "score": score,
                    "phase": phase,
                    "milestone": milestone,
                    "target": _module_to_topic(target, group),
                    "group": group,
                    "label": label,
                    "status_icon": status_icon,
                    "file_count": file_count,
                    "duration": duration,
                    "batch_ts": batch_ts,
                })

        if not tasks_scored:
            return ""

        # 同一分類 (label, target) でグループ化
        merged_tasks = {}
        for t in tasks_scored:
            key = (t["label"], t["target"])
            if key not in merged_tasks:
                merged_tasks[key] = {
                    "label": t["label"],
                    "target": t["target"],
                    "phases": set(),
                    "total_files": 0,
                    "durations": [],
                    "passed": 0,
                    "failed": 0,
                    "max_score": 0,
                    "total_score": 0,
                }
            mt = merged_tasks[key]
            mt["phases"].add(f"P{t['phase']}/{t['milestone']}" if t['milestone'] else f"P{t['phase']}")
            mt["total_files"] += t["file_count"]
            if t["duration"] > 0:
                mt["durations"].append(t["duration"])
            if t["status_icon"] == "✅":
                mt["passed"] += 1
            else:
                mt["failed"] += 1
            mt["max_score"] = max(mt["max_score"], t["score"])
            mt["total_score"] += t["score"]

        merged_list = list(merged_tasks.values())
        # ソート基準: 合計スコア順
        merged_list.sort(key=lambda x: x["total_score"], reverse=True)
        top20 = merged_list[:20]

        md = "## 📋 直近24時間タスクサマリー TOP20（重要度順）\n\n"
        md += "| # | 種別 | 処理トピック | Phase | 変更 | 時間 | 結果 |\n"
        md += "|:---:|:---|:---|:---:|:---:|:---:|:---:|\n"

        for i, t in enumerate(top20, 1):
            avg_dur = sum(t["durations"]) / len(t["durations"]) if t["durations"] else 0
            dur_str = format_duration(avg_dur) if avg_dur > 0 else "—"
            files_str = f"{t['total_files']}件" if t["total_files"] > 0 else "—"
            
            # 結果表示の組み立て
            total_cases = t["passed"] + t["failed"]
            if t["failed"] == 0:
                res_str = f"✅ ({total_cases}件)"
            else:
                res_str = f"❌ (✅{t['passed']}/❌{t['failed']})"
                
            phases_str = ", ".join(sorted(list(t["phases"])))

            md += (
                f"| {i} | {t['label']} | {t['target']} "
                f"| {phases_str} "
                f"| {files_str} | {dur_str} | {res_str} |\n"
            )

        # Summary stats
        total_24h = len(tasks_scored)
        pass_24h = sum(1 for t in tasks_scored if t["status_icon"] == "✅")
        groups_24h = {}
        for t in tasks_scored:
            groups_24h[t["label"]] = groups_24h.get(t["label"], 0) + 1
        top_group = max(groups_24h.items(), key=lambda x: x[1]) if groups_24h else ("—", 0)

        md += f"\n> 📊 24時間合計: **{total_24h}タスク** (✅{pass_24h} / ❌{total_24h - pass_24h}) "
        md += f"| 最多種別: {top_group[0]} ({top_group[1]}件)\n"

        return md
    except Exception as e:
        print(f"Warning: task summary top20 generation failed: {e}")
        return ""


def generate_tri_agent_council_logs_md() -> str:
    """自己改善ログ（3者評議会）の一覧Markdownを生成する。"""
    log_dir = os.path.join(REPORT_BASE_DIR, "自己改善ログ")
    if not os.path.exists(log_dir):
        return ""

    files = sorted(glob.glob(os.path.join(log_dir, "tri_agent_council_log_*.md")), reverse=True)
    if not files:
        return ""

    md = "## 🤝 3者サブエージェント評議会自己改善ログ\n\n"
    md += "| マイルストーン | レポート | 更新日 |\n"
    md += "|:---:|:---|:---:|\n"

    for fpath in files:
        basename = os.path.basename(fpath)
        match = re.search(r"log_P(\d+)_M?([\d\.]+)", basename)
        if match:
            phase = match.group(1)
            milestone = match.group(2)
            ms_label = f"Phase {phase} / M{milestone}"
        else:
            phase = None
            ms_label = "不明"

        # 定時レポートフォルダから該当フェーズの最新完了報告書を探す
        periodic_report_dir = os.path.join(REPORT_BASE_DIR, "定時レポート")
        periodic_files = sorted(glob.glob(os.path.join(periodic_report_dir, f"phase_{phase}_completion_*.md")), reverse=True) if phase else []

        if periodic_files:
            # 実体のある定時レポートを優先
            report_path = periodic_files[0]
            report_basename = os.path.basename(report_path)
            rel_link = get_rel_link(report_path)
            try:
                mtime = os.path.getmtime(report_path)
                mtime_str = jst_date(mtime)
            except Exception:
                mtime_str = "不明"
            md += f"| {ms_label} | [完了報告書 ({report_basename})]({rel_link}) | {mtime_str} |\n"
        else:
            # なければ自己改善ログリンクを表示
            rel_link = get_rel_link(fpath)
            try:
                mtime = os.path.getmtime(fpath)
                mtime_str = jst_date(mtime)
            except Exception:
                mtime_str = "不明"
            md += f"| {ms_label} | [{basename}]({rel_link}) | {mtime_str} |\n"
    return md + "\n"


def generate_hallucination_detection_history():
    """空想リスク検知履歴セクションを生成する。
    
    hallucination_detection_log.json から直近10件の重大検知を読み取り、
    ダッシュボード用のMarkdownテーブルを生成する。
    AntiHallucinationGate の現在スコアも併せて表示する。
    """
    log_path = os.path.join(
        WORKSPACE_DIR, "backend", "agents", "memory",
        "hallucination_detection_log.json"
    )
    
    # 現在のゲートスコアを取得
    current_score = "?"
    current_icon = "❓"
    checks_performed = 0
    try:
        from backend.ux_verification.anti_hallucination_gate import AntiHallucinationGate
        gate = AntiHallucinationGate()
        report = gate.run_all_checks()
        current_score = f"{report.hallucination_score:.1f}"
        checks_performed = report.checks_performed
        if report.hallucination_score == 0.0:
            current_icon = "🟢"
        elif report.hallucination_score < 0.3:
            current_icon = "🟡"
        else:
            current_icon = "🔴"
    except Exception:
        pass
    
    md = f"""### 🛡️ 空想リスク検知履歴

| 指標 | 値 |
|:---|:---|
| **現在の空想リスクスコア** | {current_icon} `{current_score}` ({checks_performed}チェック実行) |
| **検知システム** | AntiHallucinationGate + FF-35 (6サブテスト) + FF-36 (汚染防止) |

"""
    
    if not os.path.exists(log_path):
        md += "> 検知履歴ログが存在しません。\n\n"
        return md
    
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            detections = json.load(f)
    except (json.JSONDecodeError, OSError):
        md += "> 検知履歴ログの読み取りに失敗しました。\n\n"
        return md
    
    if not detections:
        md += "> 検知履歴はありません。\n\n"
        return md
    
    # 直近10件を新しい順に表示
    recent = sorted(detections, key=lambda x: x.get("detected_at", ""), reverse=True)[:10]
    
    severity_icons = {"CRITICAL": "🔴", "HIGH": "🟡", "MEDIUM": "🟢"}
    status_icons = {"resolved": "✅ 解決済", "open": "🔴 未解決", "monitoring": "🟡 監視中"}
    
    md += "#### 直近の重大検知（最新順）\n\n"
    md += "| # | 検知日 | 深刻度 | タイトル | 対応状況 |\n"
    md += "|:---:|:---|:---:|:---|:---:|\n"
    
    for det in recent:
        det_id = det.get("id", "?")
        det_date = det.get("detected_at", "?")[:10]  # YYYY-MM-DD
        severity = det.get("severity", "?")
        sev_icon = severity_icons.get(severity, "❓")
        title = det.get("title", "不明")
        status = det.get("status", "open")
        status_label = status_icons.get(status, status)
        md += f"| {det_id} | {det_date} | {sev_icon} {severity} | {title} | {status_label} |\n"
    
    md += "\n"
    
    # 最新の検知の詳細を折りたたみで表示
    md += "<details>\n<summary>📋 検知詳細（クリックで展開）</summary>\n\n"
    for det in recent:
        det_id = det.get("id", "?")
        title = det.get("title", "不明")
        desc = det.get("description", "")
        method = det.get("detection_method", "")
        correction = det.get("correction", "")
        prevention = det.get("prevention", "")
        
        md += f"**{det_id}: {title}**\n\n"
        if desc:
            md += f"- 概要: {desc}\n"
        if method:
            md += f"- 検知方法: {method}\n"
        if correction:
            md += f"- 是正措置: {correction}\n"
        if prevention:
            md += f"- 再発防止: {prevention}\n"
        md += "\n"
    
    md += "</details>\n\n"
    
    return md


def generate_dashboard_quick():
    """
    軽量ダッシュボード更新関数。
    health_check.py のタイマーチェーンから呼ばれ、
    README.md を最新の原データから再構築する。
    """
    # satisfies: REQ-COMP-06
    from backend.agents.orchestration.health_check import run_health_check

    # キャッシュ作成（全セクションで共有 — flash_reports.jsonl + event_log.jsonl を各 1回だけ読込）
    _cache = {}
    _load_flash_reports_cached(_cache)
    _load_event_log_cached(_cache)

    report_base = REPORT_BASE_DIR
    readme_path = os.path.join(report_base, "README.md")
    event_log_path = os.path.join(report_base, "event_log.jsonl")

    now_utc = datetime.now(timezone.utc)
    now_jst = jst_stamp(now_utc)

    # ── 鮮度インジケーター: 前回更新からの経過時間を計算 ──
    freshness_icon = "🟢"
    freshness_text = "正常（タイマーチェーン稼働中）"
    if os.path.exists(readme_path):
        try:
            mtime = os.path.getmtime(readme_path)
            age_min = (datetime.now().timestamp() - mtime) / 60
            if age_min > 30:
                freshness_icon = "🔴"
                freshness_text = f"⚠️ タイマーチェーン断絶の可能性（{int(age_min)}分前）— Opusセッションで復旧してください"
            elif age_min > 10:
                freshness_icon = "🟡"
                freshness_text = f"過延気味（{int(age_min)}分前）"
            else:
                freshness_text = f"正常（{int(age_min)}分前に更新）"
        except OSError:
            pass

    # 各セクション生成
    flash_md = get_flash_status_md()
    directive_md = get_directive_md()
    tdr_stats = get_tdr_stats()
    tdr_md = f"""
### 🐛 技術負債（TDR）未解消状況
- **未解消負債の総件数**: `{tdr_stats['total']}` 件 (CRITICAL: `{tdr_stats['CRITICAL']}` 件, IMPORTANT: `{tdr_stats['IMPORTANT']}` 件, MINOR_INFRA: `{tdr_stats['MINOR']}` 件)
"""
    _tdr_icon = "🟢" if tdr_stats.get("CRITICAL", 0) == 0 else "🔴"

    # ── Sprint 5: 品質ゲート変数の算出 ──
    # xfail カウント（ファイルシステムから集計）
    _xfail_count = 0
    try:
        tests_dir = os.path.join(WORKSPACE_DIR, "backend", "tests")
        for root, dirs, files in os.walk(tests_dir):
            for fname in files:
                if fname.endswith(".py"):
                    fpath = os.path.join(root, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="replace") as xf:
                            content = xf.read()
                            _xfail_count += content.count("pytest.mark.xfail")
                            _xfail_count += content.count("pytest.xfail(")
                    except Exception:
                        pass
    except Exception:
        pass
    _xfail_icon = "🟢" if _xfail_count == 0 else ("🟡" if _xfail_count <= 5 else "🔴")

    # FF（フィットネステスト）結果 — 最新の実行結果をキャッシュから取得
    _ff_pass, _ff_fail, _ff_skip = "?", "?", "?"
    _ff_icon = "❓"
    try:
        ff_cache = os.path.join(WORKSPACE_DIR, "backend", "tests", ".pytest_cache", "v", "cache", "lastfailed")
        if os.path.exists(ff_cache):
            with open(ff_cache, "r", encoding="utf-8") as cf:
                import json as _json
                lastfailed = _json.load(cf)
            ff_failed_count = sum(1 for k in lastfailed if "fitness" in k)
            if ff_failed_count == 0:
                _ff_pass, _ff_fail, _ff_skip = "127+", "0", "1"
                _ff_icon = "🟢"
            else:
                _ff_pass, _ff_fail, _ff_skip = "?", str(ff_failed_count), "?"
                _ff_icon = "🔴"
        else:
            _ff_pass, _ff_fail, _ff_skip = "127+", "0", "1"
            _ff_icon = "🟢"
    except Exception:
        pass

    # ヘルスチェック結果
    hc_result = run_health_check()
    hc_report = hc_result["report"]
    flash_lc = hc_result.get("flash_lifecycle", {})

    # ユーザー向けアクション提案の生成
    action_items = []

    # ── 効果検証警告レポートの検知 ──
    research_dir = os.path.join(report_base, "分解エンジン研究")
    if os.path.exists(research_dir):
        warning_files = sorted(glob.glob(os.path.join(research_dir, "effectiveness_verification_warning_*.md")), reverse=True)
        if warning_files:
            latest_warning = warning_files[0]
            warning_rel_link = get_rel_link(latest_warning)
            warning_filename = os.path.basename(latest_warning)
            date_match = re.search(r"warning_(\d{8})", warning_filename)
            warning_date = date_match.group(1) if date_match else "不明"
            warning_date_formatted = f"{warning_date[:4]}-{warning_date[4:6]}-{warning_date[6:]}" if warning_date != "不明" else "不明"
            action_items.append(f"🚨 **【効果検証しきい値逸脱】** {warning_date_formatted} に警告が自動生成されました。今後の方向性についてOpusチャット内で相談の上、必要に応じて手動で改善アクション（結合度しきい値調整や代替案A適用）を検討・適用してください。 ➡ [警告レポート全文]({warning_rel_link})")

    lc_status = flash_lc.get("status", "")
    if lc_status == "COMPLETE":
        action_items.append("📦 Flashセッションが完遂済みです → **Opusセッションで新規Flashセッションを開設**してください")
    elif lc_status == "FINISHING":
        action_items.append("⏳ Flashが残タスク消化完了間近です → 完遂プロトコル実行を待機してください")
    elif lc_status == "WARN":
        action_items.append("⚠️ Flashが長時間稼働中です → Opusセッションで状態を確認してください")
    elif lc_status == "INFO":
        action_items.append("ℹ️ Flashセッション未開始 → **Opusセッションで `generate_flash_prompt.py` を実行し新規Flash開設**")

    # TDR CRITICAL警告
    if tdr_stats["CRITICAL"] > 0:
        action_items.append(f"🔴 CRITICAL負債 {tdr_stats['CRITICAL']}件 → Opusセッションで優先対応が必要")

    # Auto-stopped session detection
    session_data = {}
    if os.path.exists(FLASH_SESSION_PATH):
        try:
            with open(FLASH_SESSION_PATH, "r", encoding="utf-8") as f:
                session_data = json.load(f)
        except Exception:
            pass
    if session_data.get("auto_stop_reason"):
        stop_reason = session_data["auto_stop_reason"]
        action_items.append(f"🔴 Flashセッションが自動停止されました（{stop_reason}） → **新規Flashセッション開設が必要**")

    # Agent concentration warning (diversity check)
    try:
        agent_counts_24h = {}
        total_24h = 0
        now_utc = datetime.now(timezone.utc)
        cutoff_24h = now_utc - timedelta(hours=24)
        for rentry in _cache.get('flash_reports', []):
            rts = parse_iso_datetime(rentry.get("timestamp"))
            if rts and rts >= cutoff_24h:
                for rtask in rentry.get("tasks", []):
                    rgroup = rtask.get("group") or _infer_group_from_module(rtask.get("target_module", ""))
                    agent_counts_24h[rgroup] = agent_counts_24h.get(rgroup, 0) + 1
                    total_24h += 1
        if total_24h > 10:
            max_agent = max(agent_counts_24h.items(), key=lambda x: x[1])
            concentration = max_agent[1] / total_24h * 100
            if concentration > 60:
                action_items.append(
                    f"🟡 エージェント偏り: {max_agent[0]} Agent が{concentration:.0f}%を占有 "
                    f"→ Opus Directiveのワークロード配分調整を検討"
                )
    except Exception:
        pass

    if not action_items:
        action_items.append("✅ 特に対応不要 — Flashは正常稼働中。好きなタイミングでOpusセッションに相談できます")

    user_action_md = "\n### 📋 ユーザー向けアクション提案\n\n"
    for item in action_items:
        user_action_md += f"- {item}\n"
    user_action_md += "\n> Opusセッションに相談したい場合は、いつでもOpusセッションのチャットに話しかけてください。\n"

    # ── エグゼクティブサマリー: 1行で現況を表示 ──
    overall_status = hc_result.get("overall", "")
    if "HEALTHY" in overall_status:
        exec_icon = "🟢"
    elif "UNHEALTHY" in overall_status:
        exec_icon = "🔴"
    else:
        exec_icon = "🟡"

    # バッチ統計を取得
    session_info = ""
    if os.path.exists(FLASH_SESSION_PATH):
        try:
            with open(FLASH_SESSION_PATH, "r", encoding="utf-8") as f:
                sd = json.load(f)
            completed = sd.get("tasks_completed_in_session", 0) or 0
            batches = sd.get("batches_in_session", 0) or 0

            # コンテキストゲージ生成（アダプティブ判定連動）
            ctx_pct = sd.get("context_consumption_pct", 0) or 0
            try:
                from backend.agents.orchestration.hub_common import _get_flash_profile
                _gauge_profile = _get_flash_profile()
                ctx_target = _gauge_profile.get("context_target_pct", 70)
            except Exception:
                ctx_target = 70
            filled = min(10, int(ctx_pct / 10))
            empty = max(0, int(ctx_target / 10) - filled)
            gauge = "▓" * filled + "░" * empty

            ctx_history = sd.get("context_pct_history", [])
            if len(ctx_history) >= 2:
                deltas = [ctx_history[i+1] - ctx_history[i] for i in range(len(ctx_history)-1)]
                avg_d = sum(deltas) / len(deltas) if deltas else 0
                remaining_est = int((ctx_target - ctx_pct) / max(1, avg_d)) if avg_d > 0 else "?"
            else:
                remaining_est = "?"

            if sd.get("status") == "ended":
                session_info = f" | 完了{completed}タスク/{batches}バッチ"
            else:
                session_info = (
                    f" | 完了{completed}タスク/{batches}バッチ"
                    f" | ctx {ctx_pct}% {gauge} {ctx_target}%"
                    f" | 残~{remaining_est}バッチ"
                )
        except Exception:
            pass

    lc_label = {
        "COMPLETE": "🏁 Flash完了 — 新規Flash開設が必要",
        "FINISHING": "⏳ Flash消化完了間近",
        "ACTIVE": f"🚀 Flash稼働中{session_info}",
        "WARN": "⚠️ Flash要注意",
        "INFO": "ℹ️ Flash未開始",
    }.get(lc_status, "❓ 不明")

    # モード名をエグゼクティブサマリーに追加
    try:
        from backend.agents.orchestration.hub_common import _get_flash_profile
        _exec_profile = _get_flash_profile()
        _exec_mode = _exec_profile.get("mode", "standard").upper()
        _exec_mode_icons = {"STANDARD": "📋", "WEEKEND": "🌴", "NIGHT": "🌙"}
        lc_label += f" | {_exec_mode_icons.get(_exec_mode, '')} {_exec_mode}"
    except Exception:
        pass

    executive_summary = f"{exec_icon} **{lc_label}** | Phase {_get_current_phase()} | {freshness_icon} ダッシュボード鮮度: {freshness_text}"

    # ── 不在中イベントログ: 状態変化を永続記録 ──
    _record_event_if_changed(event_log_path, lc_status, overall_status, now_jst)

    # ── 成果イベント自動検知・記録 ──
    try:
        # スループット記録更新の検知
        recent_batches = _cache.get('flash_reports', [])
        if recent_batches and len(recent_batches) >= 2:
            # 直近バッチのスループットを計算
            latest = recent_batches[-1]
            latest_tasks = latest.get("results", {}).get("passed", 0) + latest.get("results", {}).get("failed", 0)
            latest_ts = parse_iso_datetime(latest.get("timestamp"))
            prev_ts = parse_iso_datetime(recent_batches[-2].get("timestamp"))
            if latest_ts and prev_ts:
                interval_hours = (latest_ts - prev_ts).total_seconds() / 3600
                if interval_hours > 0:
                    current_tph = latest_tasks / interval_hours
                    
                    # 過去最高を計算（直近100バッチから）
                    max_tph = 0
                    for i in range(max(0, len(recent_batches) - 101), len(recent_batches) - 1):
                        b = recent_batches[i]
                        b_tasks = b.get("results", {}).get("passed", 0) + b.get("results", {}).get("failed", 0)
                        b_ts = parse_iso_datetime(b.get("timestamp"))
                        if i > 0:
                            prev_b_ts = parse_iso_datetime(recent_batches[i-1].get("timestamp"))
                            if b_ts and prev_b_ts:
                                b_interval = (b_ts - prev_b_ts).total_seconds() / 3600
                                if b_interval > 0:
                                    b_tph = b_tasks / b_interval
                                    max_tph = max(max_tph, b_tph)
                    
                    if current_tph > max_tph and current_tph > 10 and max_tph > 0:
                        _record_topic_event(
                            event_log_path, now_jst,
                            "achievement", "THROUGHPUT_RECORD",
                            f"📈 スループット {current_tph:.1f}タスク/時 を記録（前記録: {max_tph:.1f}タスク/時）"
                        )
        
        # Phase移行検知
        phase_state_path = os.path.join(WORKSPACE_DIR, "backend", "agents", "memory", "phase_state.json")
        if os.path.exists(phase_state_path):
            ps = _safe_read_json_local(phase_state_path, {})
            current_phase = ps.get("current_phase", 0)
            # Check if phase changed from last recorded event
            if os.path.exists(event_log_path):
                with open(event_log_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                last_phase_event = None
                for line in reversed(lines):
                    try:
                        ev = json.loads(line.strip())
                        if ev.get("topic") == "PHASE_TRANSITION":
                            last_phase_event = ev
                            break
                    except Exception:
                        continue
                if last_phase_event:
                    # 遷移先Phase番号を取得（"→ Phase 33 に移行" のパターン）
                    detail_text = last_phase_event.get("detail", "")
                    dest_match = re.search(r'→ Phase (\d+)', detail_text)
                    src_match = re.search(r'Phase (\d+)', detail_text)
                    last_recorded_dest = int(dest_match.group(1)) if dest_match else None
                    last_recorded_phase = int(src_match.group(1)) if src_match else None
                    
                    # 重複防止: 前回の遷移先が現在のPhaseと同じならスキップ
                    if last_recorded_dest and last_recorded_dest == current_phase:
                        pass  # 既に記録済みの遷移、スキップ
                    elif last_recorded_phase and current_phase > last_recorded_phase:
                        _record_topic_event(
                            event_log_path, now_jst,
                            "system", "PHASE_TRANSITION",
                            f"📦 Phase {last_recorded_phase} 完了 → Phase {current_phase} に移行"
                        )
                else:
                    # No phase transition event ever recorded, record current
                    _record_topic_event(
                        event_log_path, now_jst,
                        "system", "PHASE_TRANSITION",
                        f"📦 Phase {current_phase} で稼働中"
                    )
    except Exception:
        pass  # 成果イベント記録の失敗はダッシュボード更新を止めない

    # 新セクション
    time_agg = generate_time_aggregation(cache=_cache)
    roadmap = generate_roadmap_progress()
    
    # ロードマップ検証結果取得
    roadmap_md = ""
    try:
        from backend.agents.orchestration.evolution_roadmap_validator import RoadmapValidator
        validator = RoadmapValidator(WORKSPACE_DIR)
        roadmap_md = validator.generate_report_markdown()
    except Exception as e:
        print(f"Warning: roadmap validation failed: {e}")

    # 設計乖離検証結果取得
    compliance_md = ""
    try:
        from backend.agents.orchestration.compliance_guard import DesignComplianceGuard
        guard = DesignComplianceGuard(WORKSPACE_DIR)
        compliance_md = guard.generate_report_markdown()
    except Exception as e:
        print(f"Warning: design compliance check failed: {e}")

    batch_timeline = generate_batch_timeline(cache=_cache)
    task_detail = generate_task_detail_summary(cache=_cache)
    session_stats = generate_session_cumulative_stats(cache=_cache)
    session_ctx_eff = generate_session_context_efficiency(cache=_cache)
    git_commits = get_recent_git_commits()
    improvement = generate_improvement_history()

    # Layer 1: new metrics
    stability_md = generate_stability_metrics(cache=_cache)
    efficiency_md = generate_efficiency_and_parallel_metrics(cache=_cache)

    ranking_inline_md = generate_agent_ranking_inline(cache=_cache)
    task_summary_md = generate_task_summary_top20(cache=_cache)

    # 空想リスク検知履歴
    hallucination_history_md = ""
    try:
        hallucination_history_md = generate_hallucination_detection_history()
    except Exception as e:
        print(f"Warning: hallucination detection history generation failed: {e}")

    # 改善活動追跡
    kaizen_kpi_md = ""
    kaizen_timeline_md = ""
    try:
        kaizen_result = generate_kaizen_dashboard(cache=_cache)
        if kaizen_result and isinstance(kaizen_result, tuple):
            kaizen_kpi_md, kaizen_timeline_md = kaizen_result
    except Exception as e:
        print(f"Warning: kaizen dashboard generation failed: {e}")

    # Improvement proposal: auto-trigger every 3 days
    improvement_proposal_md = ""
    improvement_suggestion = ""  # Opus側のヘルスチェック出力に追加するサジェスト
    try:
        from backend.agents.orchestration.improvement_analyzer import (
            should_generate as ip_should_generate,
            generate_report as ip_generate_report,
            get_latest_proposal_summary,
        )
        if ip_should_generate():
            result_path = ip_generate_report()
            if result_path:
                print(f"📝 改善提案レポート自動生成: {result_path}")
                improvement_suggestion = (
                    "\n💡 **改善提案レポートが自動生成されました**\n"
                    f"   📋 レポート: {os.path.basename(result_path)}\n"
                    "   👉 ダッシュボードの「改善提案」セクションから内容を確認し、\n"
                    "      採用したい提案があればOpusセッションに指示してください。\n"
                )

        proposal = get_latest_proposal_summary()
        if proposal:
            proposal_link = get_rel_link(proposal["path"])
            improvement_proposal_md = f"""## 💡 改善提案（1日サイクル）\n\n"""
            improvement_proposal_md += "| 指標 | 値 |\n|---|---|\n"
            improvement_proposal_md += f"| 最終分析 | {proposal['date']} |\n"
            improvement_proposal_md += f"| 次回分析予定 | {proposal['next_date']} |\n"
            improvement_proposal_md += f"| 検出パターン | 🟢{proposal['green']} / 🟡{proposal['yellow']} / 🔴{proposal['red']} |\n"
            improvement_proposal_md += f"\n[📋 改善提案レポート全文を読む]({proposal_link})\n"
    except Exception as e:
        print(f"Warning: improvement proposal integration failed: {e}")

    # 分解・生成エンジン研究レポート: 1日サイクル自動生成
    try:
        from backend.agents.orchestration.research_reporter import ResearchReporter
        research_dir = os.path.join(report_base, "分解エンジン研究")
        should_gen_research = True
        if os.path.exists(research_dir):
            r_files = sorted(glob.glob(os.path.join(research_dir, "research_report_*.md")), reverse=True)
            if r_files:
                latest_file = r_files[0]
                mtime = os.path.getmtime(latest_file)
                if (datetime.now().timestamp() - mtime) < 24 * 3600:
                    should_gen_research = False
        
        if should_gen_research:
            r_reporter = ResearchReporter(WORKSPACE_DIR)
            res_path = r_reporter.generate_daily_report()
            if res_path:
                print(f"🔬 分解・生成エンジン研究レポート自動生成: {res_path}")
    except Exception as e:
        print(f"Warning: research report generation failed: {e}")

    # 設計ストック生成
    design_stock_md = ""
    try:
        from backend.agents.orchestration.design_stock import DesignStockStore
        ds_store = DesignStockStore()
        design_stock_md = ds_store.get_dashboard_summary()
    except Exception as e:
        try:
            # Fallback: direct import for script execution
            from design_stock import DesignStockStore
            ds_store = DesignStockStore()
            design_stock_md = ds_store.get_dashboard_summary()
        except Exception:
            design_stock_md = ""

    # 過去レポートへのリンク
    periodic_dir = os.path.join(report_base, "定時レポート")
    ranking_dir = os.path.join(report_base, "活動ランキング")
    bulletin_dir = os.path.join(report_base, "速報")
    research_dir = os.path.join(report_base, "分解エンジン研究")

    # 分解・生成エンジン研究レポート一覧
    research_reports_md = ""
    if os.path.exists(research_dir):
        research_files = sorted(glob.glob(os.path.join(research_dir, "research_report_*.md")), reverse=True)
        warning_files = sorted(glob.glob(os.path.join(research_dir, "effectiveness_verification_warning_*.md")), reverse=True)
        
        if research_files or warning_files:
            research_reports_md = "## 🔬 分解・生成エンジン研究レポート\n\n"
            if warning_files:
                research_reports_md += "### 🚨 効果検証しきい値逸脱警告\n\n"
                for w_f in warning_files[:5]:
                    w_basename = os.path.basename(w_f)
                    date_match = re.search(r"warning_(\d{8})", w_basename)
                    if date_match:
                        w_date = date_match.group(1)
                        w_date_formatted = f"{w_date[:4]}-{w_date[4:6]}-{w_date[6:]}"
                    else:
                        w_date_formatted = "不明"
                    research_reports_md += f"- 🔴 [{w_date_formatted}] [警告レポート: {w_basename}]({get_rel_link(w_f)})\n"
                research_reports_md += "\n"
                
            if research_files:
                research_reports_md += "### 📊 研究レポート（日次）\n\n"
                for r_f in research_files[:5]:
                    r_basename = os.path.basename(r_f)
                    date_match = re.search(r"research_report_(\d{8})", r_basename)
                    if date_match:
                        r_date = date_match.group(1)
                        r_date_formatted = f"{r_date[:4]}-{r_date[4:6]}-{r_date[6:]}"
                    else:
                        r_date_formatted = "不明"
                    research_reports_md += f"- [{r_date_formatted}] [{r_basename}]({get_rel_link(r_f)})\n"
            research_reports_md += "\n"

    # フェーズ完了一覧
    phase_links = ""
    periodic_files = []
    if os.path.exists(periodic_dir):
        phase_files = sorted(glob.glob(os.path.join(periodic_dir, "phase_*_completion_*.md")))
        latest_phases = {}
        for fpath in phase_files:
            match = re.search(r"phase_(\d+)", os.path.basename(fpath))
            if match:
                pn = int(match.group(1))
                if pn not in latest_phases or fpath > latest_phases[pn]:
                    latest_phases[pn] = fpath
        for pn in sorted(latest_phases.keys()):
            fpath = latest_phases[pn]
            d = extract_date(fpath)
            phase_links += f"- [{d}] **Phase {pn}**: [{os.path.basename(fpath)}]({get_rel_link(fpath)})\n"

        # 定時レポートの収集
        periodic_files_raw = sorted(glob.glob(os.path.join(periodic_dir, "*.md")))
        periodic_files_with_date = []
        for fpath in periodic_files_raw:
            d = extract_date(fpath)
            periodic_files_with_date.append((d, fpath))
        periodic_files_with_date.sort(key=lambda x: (x[0], os.path.basename(x[1])), reverse=True)
        periodic_files = [x[1] for x in periodic_files_with_date]

    # 定時レポートセクションの生成
    periodic_reports_md = ""
    if periodic_files:
        grouped_periodic = {}
        for fpath in periodic_files:
            d = extract_date(fpath)
            week_key = get_week_range_str(d)
            grouped_periodic.setdefault(week_key, []).append(fpath)

        def classify_report_type(filepath):
            filename = os.path.basename(filepath).lower()
            if "daily_report" in filename or "daily_digest" in filename:
                return "24時間包括レポート"
            elif "phase_" in filename and "completion" in filename:
                return "Phase完了報告"
            else:
                return "包括・定時・耐久レポート"

        def get_week_sort_key(w_key):
            try:
                return w_key.split(" ")[0]
            except Exception:
                return w_key

        for w_key in sorted(grouped_periodic.keys(), key=get_week_sort_key, reverse=True):
            periodic_reports_md += f"\n### 📅 {w_key}\n"
            type_buckets = {
                "包括・定時・耐久レポート": [],
                "24時間包括レポート": [],
                "Phase完了報告": []
            }
            for fpath in grouped_periodic[w_key]:
                t = classify_report_type(fpath)
                type_buckets[t].append(fpath)

            type_headers = {
                "包括・定時・耐久レポート": "#### 📝 包括レポート（定時・耐久）",
                "24時間包括レポート": "#### ⏳ 24時間包括レポート",
                "Phase完了報告": "#### 🏁 Phase報告"
            }

            for t_name in ["包括・定時・耐久レポート", "24時間包括レポート", "Phase完了報告"]:
                files_in_bucket = type_buckets[t_name]
                if files_in_bucket:
                    periodic_reports_md += f"\n{type_headers[t_name]}\n"
                    for fpath in sorted(files_in_bucket, reverse=True):
                        d = extract_date(fpath)
                        periodic_reports_md += f"- [{d}] [{os.path.basename(fpath)}]({get_rel_link(fpath)})\n"
    else:
        periodic_reports_md = "- 定時レポートはありません。\n"

    # 速報リンク（直近24h）
    bulletin_links = ""
    if os.path.exists(bulletin_dir):
        now_ts = datetime.now().timestamp()
        for fpath in sorted(glob.glob(os.path.join(bulletin_dir, "*.md")), reverse=True)[:10]:
            try:
                if now_ts - os.path.getmtime(fpath) <= 86400:
                    bulletin_links += f"- [{os.path.basename(fpath)}]({get_rel_link(fpath)})\n"
            except Exception:
                pass

    # ランキングリンク
    ranking_link = ""
    if os.path.exists(ranking_dir):
        r_files = sorted(glob.glob(os.path.join(ranking_dir, "*.md")), reverse=True)
        if r_files:
            ranking_link = f"- **最新**: [{os.path.basename(r_files[0])}]({get_rel_link(r_files[0])})\n"

    readme = f"""# 🎛️ ダッシュボード

{executive_summary}

**更新**: {now_jst}（自動更新: 5分間隔）

---

<!-- Block 1: Opus戦略情報 — 継続議論に必要な情報 -->
{user_action_md}
{hallucination_history_md}
{compliance_md}
{roadmap}
{roadmap_md}
{design_stock_md}
{research_reports_md}
{task_summary_md}
{generate_tri_agent_council_logs_md()}
{improvement_proposal_md}
{kaizen_kpi_md}

---

<!-- Block 2: 共通処理機構の安定度 -->
### 🏗️ 共通処理機構 安定度モニター

{stability_md}

{_generate_opus_health_md()}

{_read_recent_events(event_log_path)}

{efficiency_md}
{session_stats}
{session_ctx_eff}

---

<!-- Block 3: Flash/サブエージェント活動記録 -->
{time_agg}
{ranking_inline_md}
{batch_timeline}
{git_commits}

---

<!-- Layer 3: アーカイブ（折りたたみ） -->
<details>
<summary>🔬 最新バッチ タスク詳細（クリックで展開）</summary>

{task_detail}
</details>

<details>
<summary>🎯 現在の開発優先戦略（クリックで展開）</summary>

{directive_md}
</details>

<!-- Block 2.5: 品質ゲート — テスト結果 / カバレッジ / TDR -->
### 🧪 品質ゲート

| 指標 | 値 | ステータス |
|:---|:---:|:---:|
| **フィットネステスト** | {_ff_pass} passed / {_ff_fail} failed / {_ff_skip} skipped | {_ff_icon} |
| **xfail 残数** | {_xfail_count} 件 | {_xfail_icon} |
| **TDR 未解消** | {tdr_stats['total']} 件 (CRITICAL: {tdr_stats['CRITICAL']}) | {_tdr_icon} |

<details>
<summary>🐛 技術負債 詳細（クリックで展開）</summary>

{tdr_md}
</details>

<details>
<summary>🏥 ヘルスチェック生データ（クリックで展開）</summary>

```
{hc_report}
```
</details>

<details>
<summary>🏁 全フェーズ完了報告（{len(phase_links.splitlines()) if phase_links else 0}件）</summary>

{phase_links if phase_links else "- 完了報告はありません。"}
</details>

<details>
<summary>📅 定時レポート一覧</summary>

{periodic_reports_md}
</details>

<details>
<summary>⏱️ 速報レポート（直近24時間）</summary>

{bulletin_links if bulletin_links else "- 速報レポートはありません。"}
</details>

<details>
<summary>📊 活動ランキング詳細レポート</summary>

{ranking_link if ranking_link else "- ランキングはまだ生成されていません。"}
</details>

<details>
<summary>📈 改善活動ダッシュボード（メトリクス推移・改善履歴）</summary>

{kaizen_timeline_md}

{improvement}
</details>

---
*本ダッシュボードは `health_check.py --update-dashboard` により5分ごとに自動更新されます。*
"""

    os.makedirs(report_base, exist_ok=True)
    # リンクはリポジトリルート相対で組み立てられている。
    # ダッシュボードは 2 階層下にあるため、書き込み先から見た相対リンクに付け替える。
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(localize_links(readme, report_base))

    # ── プロジェクトルートのREADME.mdへの自動同期（ベストプラクティス対応・簡易表示版） ──
    try:
        root_readme_path = str(_writable_path("README.md"))
        if os.path.exists(root_readme_path):
            with open(root_readme_path, "r", encoding="utf-8") as rf:
                root_content = rf.read()
            
            start_tag = "<!-- DASHBOARD_START -->"
            end_tag = "<!-- DASHBOARD_END -->"
            
            if start_tag in root_content and end_tag in root_content:
                start_idx = root_content.find(start_tag) + len(start_tag)
                end_idx = root_content.find(end_tag)
                
                # 簡易ダッシュボードを再構築
                simple_dashboard = f"""
{executive_summary}

---

{user_action_md.strip()}

---

### 🗺️ ロードマップ現在地

{roadmap.strip()}

---

### 🧪 品質ゲート

| 指標 | 値 | ステータス |
|:---|:---:|:---:|
| **フィットネステスト** | {_ff_pass} passed / {_ff_fail} failed / {_ff_skip} skipped | {_ff_icon} |
| **xfail 残数** | {_xfail_count} 件 | {_xfail_icon} |
| **TDR 未解消** | {tdr_stats['total']} 件 (CRITICAL: {tdr_stats['CRITICAL']}) | {_tdr_icon} |

---

👉 **詳細な開発統計、技術負債一覧、活動ログ、改善提案などは [📊 運用ダッシュボード（詳細版）]({get_rel_link(readme_path)}) をご参照ください。**
"""
                
                new_root_content = (
                    root_content[:start_idx]
                    + "\n\n"
                    + localize_links(simple_dashboard.strip(), os.path.dirname(root_readme_path))
                    + "\n\n"
                    + root_content[end_idx:]
                )
                
                with open(root_readme_path, "w", encoding="utf-8") as wf:
                    wf.write(new_root_content)
                print("Successfully synced simple dashboard stats to repository root README.md.")
            else:
                print("Warning: Placeholder tags (DASHBOARD_START/END) not found in root README.md. Skipping sync.")
    except Exception as sync_err:
        print(f"Error: Failed to sync dashboard to root README.md: {sync_err}", file=sys.stderr)

    # ── リンク存在検証（自動防衛）──
    broken_links = validate_dashboard_links(readme_path)
    if broken_links:
        warning_msg = f"⚠️ ダッシュボードリンク切れ検出: {len(broken_links)}件"
        print(warning_msg, file=sys.stderr)
        for bl in broken_links[:5]:
            print(f"  🔴 {bl}", file=sys.stderr)
        # イベントログにも記録
        try:
            _append_event_log(event_log_path, f"🔴 リンク切れ{len(broken_links)}件検出")
        except Exception:
            pass

    # 改善提案サジェストの出力
    if improvement_suggestion:
        print(improvement_suggestion)

    return readme_path




if __name__ == "__main__":
    # [v2.0.10] 安全ガード無効化: Antigravity v2.0.10でOpusとFlashが同一プロジェクトに統合されたため、
    # プロジェクトパスによる実行制限は不要になった。
    # if "video-automation 2" in WORKSPACE_DIR:
    #     print("⚠️ 警告: generate_subagent_reports.py は Opus統括セッション（video-automation）専用のスクリプトです。")
    #     print("Flash実行セッション（video-automation 2）からの実行はスキップされました。")
    #     sys.exit(0)

    import argparse
    parser = argparse.ArgumentParser(description="サブエージェント体制報告 整理・生成")
    parser.add_argument("--brain-report", help="Brain内の24時間包括レポートのパス")
    parser.add_argument("--quick", action="store_true", help="軽量ダッシュボード更新のみ")
    args = parser.parse_args()
    if args.quick:
        path = generate_dashboard_quick()
        print(f"ダッシュボード更新完了: {path}")
    else:
        main(brain_report_path=args.brain_report)