"""
共通処理機構 改善提案分析器 (Improvement Analyzer)

1日間のメトリクスを前期と比較し、改善提案を日本語で生成する。
ダッシュボード更新時に自動トリガーされ、1日経過ごとに新規レポートを生成。
自動生成時はユーザーにサジェストして承認を求める。

使い方:
    python improvement_analyzer.py              # 通常実行（1日チェック付き）
    python improvement_analyzer.py --force      # 強制生成（チェック無視）
"""

try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import official_artifact_dir as _official_artifact_dir
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import official_artifact_dir as _official_artifact_dir
    from path_resolver import writable_path as _writable_path
import json
import os
import glob
from datetime import datetime, timezone, timedelta

WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
ORCHESTRATION_DIR = os.path.join(WORKSPACE_DIR, "backend", "agents", "orchestration")
FLASH_REPORTS_PATH = os.path.join(ORCHESTRATION_DIR, "flash_reports.jsonl")
FLASH_SESSION_PATH = str(_writable_path("backend/agents/orchestration/flash_session.json"))

REPORT_BASE_DIR = os.path.join(str(_official_artifact_dir()), "サブエージェント体制報告")
PROPOSAL_DIR = os.path.join(REPORT_BASE_DIR, "改善提案")
EVENT_LOG_PATH = os.path.join(REPORT_BASE_DIR, "event_log.jsonl")


def _parse_iso(ts_str):
    """Parse ISO 8601 timestamp."""
    if not ts_str:
        return None
    try:
        ts_str = ts_str.replace("Z", "+00:00")
        return datetime.fromisoformat(ts_str)
    except ValueError:
        return None


def _parse_event_ts(ts_str):
    """Parse event log timestamp: '2026-05-25 23:15 JST'."""
    if not ts_str:
        return None
    try:
        clean = ts_str.replace(" JST", "").strip()
        dt = datetime.strptime(clean, "%Y-%m-%d %H:%M")
        return dt.replace(tzinfo=timezone(timedelta(hours=9)))
    except ValueError:
        return None


def _format_duration(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


def _trend_arrow(current, previous):
    """Return trend arrow and percentage change."""
    if previous == 0:
        return "—", 0
    pct = ((current - previous) / previous) * 100
    if pct > 5:
        return "↑", pct
    elif pct < -5:
        return "↓", pct
    else:
        return "→", pct


def _sparkline(values, width=8):
    """Generate a text sparkline from values."""
    if not values:
        return "—"
    bars = "▁▂▃▄▅▆▇█"
    min_v = min(values)
    max_v = max(values)
    range_v = max_v - min_v if max_v > min_v else 1
    result = ""
    # Sample values to fit width
    step = max(1, len(values) // width)
    sampled = values[::step][:width]
    for v in sampled:
        idx = int((v - min_v) / range_v * (len(bars) - 1))
        result += bars[idx]
    return result


def compute_window_metrics(batches, start_utc, end_utc):
    """Compute metrics for a time window."""
    window_batches = []
    total_passed = 0
    total_failed = 0
    total_files = 0
    task_durations = []

    for b in batches:
        ts = _parse_iso(b.get("timestamp"))
        if not ts:
            continue
        if ts < start_utc or ts >= end_utc:
            continue
        window_batches.append(b)
        r = b.get("results", {})
        p = r.get("passed", 0)
        f = r.get("failed", 0)
        total_passed += p
        total_failed += f
        total_files += b.get("git_diff_summary", {}).get("files_changed", 0)

        for task in b.get("tasks", []):
            s = _parse_iso(task.get("started_at"))
            c = _parse_iso(task.get("completed_at"))
            if s and c:
                task_durations.append((c - s).total_seconds())

    total_tasks = total_passed + total_failed
    hours = (end_utc - start_utc).total_seconds() / 3600

    # Batch intervals
    intervals = []
    sorted_b = sorted(window_batches, key=lambda x: x.get("timestamp", ""))
    for i in range(1, len(sorted_b)):
        t1 = _parse_iso(sorted_b[i-1].get("timestamp"))
        t2 = _parse_iso(sorted_b[i].get("timestamp"))
        if t1 and t2:
            intervals.append((t2 - t1).total_seconds())

    # Agent distribution
    agent_counts = {}
    for b in window_batches:
        for task in b.get("tasks", []):
            group = task.get("group") or "misc"
            agent_counts[group] = agent_counts.get(group, 0) + 1

    # Parallel degree (tasks per batch)
    avg_parallel = total_tasks / len(window_batches) if window_batches else 0

    return {
        "batches": len(window_batches),
        "tasks": total_tasks,
        "passed": total_passed,
        "failed": total_failed,
        "files_changed": total_files,
        "tasks_per_hour": total_tasks / hours if hours > 0 else 0,
        "success_rate": (total_passed / total_tasks * 100) if total_tasks > 0 else 0,
        "avg_batch_interval": sum(intervals) / len(intervals) if intervals else 0,
        "avg_task_duration": sum(task_durations) / len(task_durations) if task_durations else 0,
        "avg_parallel": avg_parallel,
        "agent_counts": agent_counts,
        "total_agent_tasks": sum(agent_counts.values()),
    }


def compute_uptime(start_utc, end_utc):
    """Calculate uptime from event log for the given period."""
    if not os.path.exists(EVENT_LOG_PATH):
        return {"uptime_pct": 100.0, "downtime_min": 0, "restarts": 0}

    events = []
    try:
        with open(EVENT_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    ts = _parse_event_ts(ev.get("timestamp"))
                    if ts:
                        # Convert to UTC for comparison
                        ts_utc = ts.astimezone(timezone.utc)
                        if start_utc <= ts_utc < end_utc:
                            events.append((ts_utc, ev))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return {"uptime_pct": 100.0, "downtime_min": 0, "restarts": 0}

    events.sort(key=lambda x: x[0])

    healthy_sec = 0
    unhealthy_sec = 0
    prev_ts = start_utc
    prev_healthy = True
    restarts = 0

    for ts, ev in events:
        health = ev.get("health", "")
        is_healthy = "HEALTHY" in health and "UNHEALTHY" not in health
        duration = (ts - prev_ts).total_seconds()

        if prev_healthy:
            healthy_sec += duration
        else:
            unhealthy_sec += duration

        if is_healthy and not prev_healthy:
            restarts += 1

        prev_ts = ts
        prev_healthy = is_healthy

    remaining = (end_utc - prev_ts).total_seconds()
    if prev_healthy:
        healthy_sec += remaining
    else:
        unhealthy_sec += remaining

    total = healthy_sec + unhealthy_sec
    return {
        "uptime_pct": (healthy_sec / total * 100) if total > 0 else 100.0,
        "downtime_min": int(unhealthy_sec / 60),
        "restarts": restarts,
    }


def detect_patterns(current, previous, uptime_curr, uptime_prev):
    """Detect improvement/degradation patterns by comparing two periods."""
    patterns = []  # (severity, category, message, suggestion)

    # 1. Throughput change
    arrow, pct = _trend_arrow(current["tasks_per_hour"], previous["tasks_per_hour"])
    if pct < -10:
        patterns.append(("🔴", "スループット低下",
            f"タスク/時が前期比{abs(pct):.1f}%低下（{previous['tasks_per_hour']:.1f} → {current['tasks_per_hour']:.1f}）",
            "サブエージェント並列度の調整、またはバッチサイズの最適化を検討"))
    elif pct > 10:
        patterns.append(("🟢", "スループット改善",
            f"タスク/時が前期比{pct:.1f}%向上（{previous['tasks_per_hour']:.1f} → {current['tasks_per_hour']:.1f}）",
            "現在の設定を維持。効果の要因を記録し再現可能にすること"))
    else:
        patterns.append(("⚪", "スループット安定",
            f"タスク/時は安定（{current['tasks_per_hour']:.1f}/h）", ""))

    # 2. Uptime change
    uptime_diff = uptime_curr["uptime_pct"] - uptime_prev["uptime_pct"]
    if uptime_diff < -5:
        patterns.append(("🔴", "稼働率低下",
            f"稼働率が前期比{abs(uptime_diff):.1f}pt低下（{uptime_prev['uptime_pct']:.1f}% → {uptime_curr['uptime_pct']:.1f}%）",
            "トークン管理の改善、セッション復旧手順の自動化を検討"))
    elif uptime_diff > 5:
        patterns.append(("🟢", "稼働率改善",
            f"稼働率が前期比{uptime_diff:.1f}pt向上（{uptime_prev['uptime_pct']:.1f}% → {uptime_curr['uptime_pct']:.1f}%）",
            ""))

    # 3. Error rate change
    curr_err = 100 - current["success_rate"]
    prev_err = 100 - previous["success_rate"]
    if curr_err > prev_err + 1:
        patterns.append(("🟡", "エラー率増加",
            f"エラー率が前期比{curr_err - prev_err:.1f}pt増加（{prev_err:.1f}% → {curr_err:.1f}%）",
            "エラーハンドリングの強化、リトライ戦略の見直しを検討"))

    # 4. Batch interval change
    arrow, pct = _trend_arrow(current["avg_batch_interval"], previous["avg_batch_interval"])
    if pct > 20:
        patterns.append(("🟡", "バッチ間隔増加",
            f"バッチ間隔が前期比{pct:.1f}%増加（{_format_duration(previous['avg_batch_interval'])} → {_format_duration(current['avg_batch_interval'])}）",
            "タスクキュー生成の最適化、次バッチの先行生成を検討"))

    # 5. Agent concentration
    if current["total_agent_tasks"] > 0:
        max_agent = max(current["agent_counts"].items(), key=lambda x: x[1])
        concentration = max_agent[1] / current["total_agent_tasks"] * 100
        if concentration > 60:
            patterns.append(("🟡", "エージェント偏り",
                f"{max_agent[0]} Agentの出現率が{concentration:.1f}%（全タスクの6割超）",
                "Opus Directiveのワークロード配分を調整し、他カテゴリのタスクを増やすことを検討"))

    # 6. Session instability
    if uptime_curr["restarts"] > 5:
        patterns.append(("🟡", "セッション不安定",
            f"3日間で{uptime_curr['restarts']}回のセッション中断",
            "トークンリミット回避のためのセッション管理改善、クールダウン時間の最適化を検討"))

    return patterns


def compute_daily_throughput(batches, start_utc, days=6):
    """Compute daily throughput values for sparkline."""
    values = []
    for d in range(days):
        day_start = start_utc + timedelta(days=d)
        day_end = day_start + timedelta(days=1)
        count = 0
        for b in batches:
            ts = _parse_iso(b.get("timestamp"))
            if ts and day_start <= ts < day_end:
                r = b.get("results", {})
                count += r.get("passed", 0) + r.get("failed", 0)
        values.append(count)
    return values


def should_generate(force=False):
    """Check if a new report should be generated (1-day interval)."""
    if force:
        return True

    os.makedirs(PROPOSAL_DIR, exist_ok=True)
    existing = sorted(glob.glob(os.path.join(PROPOSAL_DIR, "improvement_*.md")), reverse=True)
    if not existing:
        return True

    # Check if latest report is older than 1 day
    try:
        mtime = os.path.getmtime(existing[0])
        age_hours = (datetime.now().timestamp() - mtime) / 3600
        return age_hours >= 24  # 1 day
    except OSError:
        return True


def get_latest_proposal_summary():
    """Get summary of the latest improvement proposal for dashboard embedding.
    Returns (date_str, pattern_summary, report_path, next_date_str) or None.
    """
    os.makedirs(PROPOSAL_DIR, exist_ok=True)
    existing = sorted(glob.glob(os.path.join(PROPOSAL_DIR, "improvement_*.md")), reverse=True)
    if not existing:
        return None

    latest = existing[0]
    try:
        mtime = os.path.getmtime(latest)
        dt = datetime.fromtimestamp(mtime)
        date_str = dt.strftime("%Y-%m-%d %H:%M JST")
        next_dt = dt + timedelta(days=1)
        next_str = next_dt.strftime("%Y-%m-%d %H:%M JST")

        # Quick parse for pattern counts
        green = 0
        yellow = 0
        red = 0
        with open(latest, "r", encoding="utf-8") as f:
            content = f.read()
            green = content.count("🟢")
            yellow = content.count("🟡")
            red = content.count("🔴")

        return {
            "date": date_str,
            "next_date": next_str,
            "green": green,
            "yellow": yellow,
            "red": red,
            "path": latest,
        }
    except (OSError, ValueError):
        return None


def generate_report(force=False):
    """Generate a 3-day improvement analysis report."""
    if not should_generate(force):
        return None

    # Load all batches
    batches = []
    if os.path.exists(FLASH_REPORTS_PATH):
        with open(FLASH_REPORTS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    batches.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    if not batches:
        return None

    now_utc = datetime.now(timezone.utc)
    curr_end = now_utc
    curr_start = now_utc - timedelta(days=1)
    prev_end = curr_start
    prev_start = curr_start - timedelta(days=1)

    # Compute metrics
    curr_metrics = compute_window_metrics(batches, curr_start, curr_end)
    prev_metrics = compute_window_metrics(batches, prev_start, prev_end)
    uptime_curr = compute_uptime(curr_start, curr_end)
    uptime_prev = compute_uptime(prev_start, prev_end)

    # Detect patterns
    patterns = detect_patterns(curr_metrics, prev_metrics, uptime_curr, uptime_prev)

    # Daily throughput sparklines
    daily_tasks = compute_daily_throughput(batches, prev_start, days=6)
    daily_uptime_vals = []
    for d in range(6):
        day_start = prev_start + timedelta(days=d)
        day_end = day_start + timedelta(days=1)
        up = compute_uptime(day_start, day_end)
        daily_uptime_vals.append(up["uptime_pct"])

    # Format dates
    jst = timezone(timedelta(hours=9))
    curr_start_jst = curr_start.astimezone(jst).strftime("%Y-%m-%d")
    curr_end_jst = curr_end.astimezone(jst).strftime("%Y-%m-%d")
    prev_start_jst = prev_start.astimezone(jst).strftime("%Y-%m-%d")
    prev_end_jst = prev_end.astimezone(jst).strftime("%Y-%m-%d")

    # Metric comparison table helpers
    def _row(label, curr_val, prev_val, fmt="{:.1f}", suffix=""):
        arrow, pct = _trend_arrow(curr_val, prev_val)
        return f"| {label} | {fmt.format(prev_val)}{suffix} | {fmt.format(curr_val)}{suffix} | {arrow} {pct:+.1f}% |"

    # Build report
    report = f"""# 🔄 共通処理機構 改善提案レポート

**分析日時**: {now_utc.astimezone(jst).strftime("%Y-%m-%d %H:%M JST")}
**今期**: {curr_start_jst} ~ {curr_end_jst} (1日間)
**前期**: {prev_start_jst} ~ {prev_end_jst} (1日間)

---

## 📊 期間メトリクス比較

| 指標 | 前期 | 今期 | 変化 |
|---|---|---|---|
{_row("完了タスク", curr_metrics["tasks"], prev_metrics["tasks"], "{:.0f}", "件")}
{_row("成功率", curr_metrics["success_rate"], prev_metrics["success_rate"], "{:.1f}", "%")}
{_row("タスク/時", curr_metrics["tasks_per_hour"], prev_metrics["tasks_per_hour"], "{:.1f}")}
{_row("バッチ数", curr_metrics["batches"], prev_metrics["batches"], "{:.0f}")}
| バッチ間隔 | {_format_duration(prev_metrics["avg_batch_interval"])} | {_format_duration(curr_metrics["avg_batch_interval"])} | — |
{_row("平均並列度", curr_metrics["avg_parallel"], prev_metrics["avg_parallel"], "{:.1f}")}
{_row("稼働率", uptime_curr["uptime_pct"], uptime_prev["uptime_pct"], "{:.1f}", "%")}
| セッション中断 | {uptime_prev["restarts"]}回 | {uptime_curr["restarts"]}回 | — |
{_row("変更ファイル数", curr_metrics["files_changed"], prev_metrics["files_changed"], "{:.0f}")}

## 📈 トレンド（6日間推移）

```
タスク/日: {_sparkline(daily_tasks)} ({' → '.join(str(v) for v in daily_tasks)})
稼働率:    {_sparkline(daily_uptime_vals)} ({' → '.join(f"{v:.0f}%" for v in daily_uptime_vals)})
```

---

## 🔍 検出パターンと改善提案

"""
    # Group patterns by severity
    greens = [(sev, cat, msg, sug) for sev, cat, msg, sug in patterns if sev == "🟢"]
    yellows = [(sev, cat, msg, sug) for sev, cat, msg, sug in patterns if sev == "🟡"]
    reds = [(sev, cat, msg, sug) for sev, cat, msg, sug in patterns if sev == "🔴"]

    if greens:
        report += "### 🟢 改善傾向\n"
        for sev, cat, msg, sug in greens:
            report += f"- **{cat}**: {msg}\n"
            if sug:
                report += f"  - 💡 {sug}\n"
        report += "\n"

    if yellows:
        report += "### 🟡 注意事項\n"
        for sev, cat, msg, sug in yellows:
            report += f"- **{cat}**: {msg}\n"
            if sug:
                report += f"  - 💡 {sug}\n"
        report += "\n"

    if reds:
        report += "### 🔴 要対応\n"
        for sev, cat, msg, sug in reds:
            report += f"- **{cat}**: {msg}\n"
            if sug:
                report += f"  - 💡 {sug}\n"
        report += "\n"

    if not greens and not yellows and not reds:
        report += "> 特筆すべき変化は検出されませんでした。\n\n"

    # Agent ranking changes
    report += "## 🏆 エージェント活動分布\n\n"
    report += "| エージェント | 前期タスク | 今期タスク | 変化 |\n"
    report += "|---|:---:|:---:|:---:|\n"

    all_agents = set(list(curr_metrics["agent_counts"].keys()) + list(prev_metrics["agent_counts"].keys()))
    agent_rows = []
    for agent in all_agents:
        c = curr_metrics["agent_counts"].get(agent, 0)
        p = prev_metrics["agent_counts"].get(agent, 0)
        arrow, pct = _trend_arrow(c, p)
        agent_rows.append((c, agent, p, arrow, pct))
    agent_rows.sort(key=lambda x: x[0], reverse=True)

    for c, agent, p, arrow, pct in agent_rows[:8]:
        report += f"| {agent} Agent | {p} | {c} | {arrow} {pct:+.0f}% |\n"

    # Concrete improvement actions
    actions = []
    for sev, cat, msg, sug in patterns:
        if sug and sev in ("🔴", "🟡"):
            actions.append((sev, sug))

    if actions:
        report += "\n## 💡 具体的な改善アクション（優先度順）\n\n"
        for i, (sev, action) in enumerate(actions, 1):
            report += f"{i}. {sev} **{action}**\n"

    report += f"""
---

## 📋 ユーザーへの推奨操作

1. 上記の改善提案を確認し、優先度の高いものから日本語で改善指示を出してください
2. 例: 「バッチ間隔を短縮するために、タスクキュー生成を最適化してください」
3. 改善指示はOpusセッションに直接入力するだけで実行されます

> 次回の改善分析: **{(now_utc + timedelta(days=1)).astimezone(jst).strftime("%Y-%m-%d %H:%M JST")}**

---
*本レポートは `improvement_analyzer.py` により自動生成されました。*
"""

    # Save report
    os.makedirs(PROPOSAL_DIR, exist_ok=True)
    filename = f"improvement_{now_utc.astimezone(jst).strftime('%Y%m%d_%H%M')}.md"
    filepath = os.path.join(PROPOSAL_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report)

    return filepath


if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv
    result = generate_report(force=force)
    if result:
        print(f"✅ 改善提案レポート生成完了: {result}")
    else:
        print("ℹ️ 1日未経過のため生成をスキップしました。--force で強制生成できます。")
