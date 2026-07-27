"""統計・メトリクス収集モジュール — DS-038 レポート分割 Phase 2

generate_subagent_reports.py からの統計収集関数の物理移動。
"""

import os
import sys
import json
import re
import glob
import subprocess
from datetime import datetime, timezone, timedelta

# パスの定義（デフォルトは相対パス）
WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
ORCHESTRATION_DIR = os.path.join(WORKSPACE_DIR, "backend", "agents", "orchestration")
FLASH_SESSION_PATH = os.path.join(ORCHESTRATION_DIR, "flash_session.json")
FLASH_REPORTS_PATH = os.path.join(ORCHESTRATION_DIR, "flash_reports.jsonl")

# link_validator から get_rel_link をインポート
from backend.agents.orchestration.jst_time import jst_date
from backend.agents.orchestration.link_validator import get_rel_link


# ── 動的属性解決ヘルパー ──

def _get_gsr_attr(name, default):
    """gsrモジュールがロードされている場合、その属性（monkeypatch等で書き換えられた値）を動的に取得する。"""
    try:
        gsr = sys.modules.get("backend.agents.orchestration.generate_subagent_reports")
        if gsr and hasattr(gsr, name):
            val = getattr(gsr, name)
            if val is not None:
                return val
    except Exception:
        pass
    return default


# ── 内部ヘルパー関数 ──

def parse_iso_datetime(dt_str):
    """ISO8601形式の文字列をdatetimeオブジェクト（UTC）に変換する。

    ログにはオフセット付き（...Z / +09:00）と無し（...T12:00:00）が混在する。
    そのまま返すと naive と aware が混ざり、引き算が TypeError になって
    ダッシュボードのセクションが丸ごと欠落する。オフセット無しは UTC とみなして
    **常に aware** で返す。
    """
    if not dt_str:
        return None
    try:
        dt_str = dt_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(dt_str)
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def format_duration(seconds):
    """秒数を読みやすい文字列表記（Hh Mm や Mm Ss）に変換する。"""
    if seconds is None or seconds < 0:
        return "0s"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}h {m}m"
    elif m > 0:
        return f"{m}m {s}s"
    else:
        return f"{s}s"


def extract_date(fpath):
    """ファイル名から日付文字列 (YYYY-MM-DD) を抽出する。
    
    例: daily_report_2026-05-22.md -> '2026-05-22'
    """
    if not fpath:
        return "1970-01-01"
    filename = os.path.basename(fpath)
    match = re.search(r"20\d{6}", filename)
    if match:
        d_str = match.group(0)
        return f"{d_str[0:4]}-{d_str[4:6]}-{d_str[6:8]}"
    try:
        # mtime も現在時刻も JST で解釈する。ローカル時刻だと UTC 環境で日付が 1 日ずれ、
        # 同じレポートが別の日・別の週に並ぶ（表示揺れ）。
        return jst_date(os.path.getmtime(fpath))
    except Exception:
        return jst_date()


def _load_flash_reports_cached(cache: dict = None) -> list:
    """キャッシュ付きflash_reports.jsonlローダー。
    cache dictが渡された場合、'flash_reports'キーにデータをキャッシュ。
    2回目以降の呼出しではファイルI/Oをスキップ。
    """
    # インポート循環を避けつつ monkeypatch された関数があればそちらへ委譲
    gsr_loader = _get_gsr_attr("_load_flash_reports_cached", None)
    if gsr_loader and gsr_loader != _load_flash_reports_cached:
        return gsr_loader(cache)

    flash_reports_path = _get_gsr_attr("FLASH_REPORTS_PATH", FLASH_REPORTS_PATH)
    entries = []
    if os.path.exists(flash_reports_path):
        with open(flash_reports_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    if cache is not None:
        cache['flash_reports'] = entries
    return entries


# ── 公開 API ──

def get_tdr_stats():
    """TDR indexから未解消の負債数を集計する。
    
    Returns:
        dict: {CRITICAL, IMPORTANT, MINOR, total} 形式の未解消負債集計値
    """
    workspace_dir = _get_gsr_attr("WORKSPACE_DIR", WORKSPACE_DIR)
    tdr_path = os.path.join(workspace_dir, "backend", "agents", "memory", "technical_debt_index.json")
    stats = {"CRITICAL": 0, "IMPORTANT": 0, "MINOR": 0, "total": 0}
    if not os.path.exists(tdr_path):
        return stats
    try:
        with open(tdr_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for entry in data.get("entries", []):
            if entry.get("status") == "open":
                cat = entry.get("category", "")
                stats["total"] += 1
                if "CRITICAL" in cat:
                    stats["CRITICAL"] += 1
                elif "IMPORTANT" in cat:
                    stats["IMPORTANT"] += 1
                else:
                    stats["MINOR"] += 1
    except Exception as e:
        print(f"Warning: TDR集計失敗: {e}")
    return stats


def _infer_group_from_module(target_module: str) -> str:
    """target_module名からエージェントグループを推定する。
    
    Args:
        target_module (str): モジュール名またはモジュールパス
        
    Returns:
        str: 推定されたエージェントグループ名（misc, thumbnail, bug_hunter 等）
    """
    if not target_module:
        return "misc"

    module_lower = target_module.lower()

    # モジュール名からグループを推定するルールマップ
    inference_rules = [
        ("thumbnail", "thumbnail"),
        ("test_weaver", "test_weaver"),
        ("bug_hunter", "bug_hunter"),
        ("tdr_cleanup", "tdr_cleanup"),
        ("tdr_resolver", "tdr_resolver"),
        ("refactor", "refactor"),
        ("edge_case", "edge_case"),
        ("design_auto", "design_auto"),
        ("self_improve", "self_improve"),
        ("quality_ascend", "quality_ascend"),
        ("subtitle", "subtitle"),
        ("branding", "branding"),
        ("preview", "preview"),
        ("pipeline", "pipeline"),
        ("router", "router"),
        ("orchestrat", "orchestration"),
        ("quota", "quota"),
        ("cache", "cache"),
        ("archive", "archive"),
    ]

    for keyword, group_name in inference_rules:
        if keyword in module_lower:
            return group_name

    return "misc"


def get_recent_git_commits(n: int = 10) -> str:
    """直近のFlash層Gitコミットログを取得して表示する。
    
    Args:
        n (int): 取得する最大コミット数
        
    Returns:
        str: コミットログのマークダウンテーブル
    """
    workspace_dir = _get_gsr_attr("WORKSPACE_DIR", WORKSPACE_DIR)
    try:
        result = subprocess.run(
            ["git", "log", f"-n{n}", "--oneline", "--format=%h %ai %s"],
            cwd=workspace_dir,
            capture_output=True,
            text=True,
            timeout=15,
        )

        if result.returncode != 0:
            return ""

        lines = result.stdout.strip().split("\n")
        flash_commits = [l for l in lines if "[Flash/" in l]

        if not flash_commits:
            return ""

        md = "## 🔀 直近Gitコミット（Flash層）\n\n"
        md += "| ハッシュ | 日時 | メッセージ |\n"
        md += "|:---|:---|:---|\n"

        for commit_line in flash_commits[:5]:
            parts = commit_line.split(" ", 3)
            if len(parts) >= 4:
                hash_val = parts[0]
                date_str = parts[1]
                time_str = parts[2]
                msg = parts[3] if len(parts) > 3 else ""
                md += f"| `{hash_val}` | {date_str} {time_str[:5]} | {msg[:80]} |\n"
            else:
                md += f"| | | {commit_line[:80]} |\n"

        return md
    except Exception as e:
        print(f"Warning: Gitコミットログ取得失敗: {e}")
        return ""


def extract_metrics_from_report(filepath):
    """指定されたマークダウンファイルから品質スコア、テスト数、リソース使用量を抽出する。
    
    Args:
        filepath (str): 抽出対象のマークダウンファイルパス
        
    Returns:
        dict: {quality_score, test_count, resource_usage} の辞書
    """
    metrics = {
        "quality_score": None,
        "test_count": None,
        "resource_usage": None,
    }
    
    if not filepath or not os.path.exists(filepath):
        return metrics

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
            
        # 1. テスト数の抽出
        test_match = re.search(r"(?:\*\*?)?(?:最終|合計|総)?テスト(?:総|件)?数(?:\*\*?)?\s*\|\s*(?:[\d,\-\s\*\+/%]+?\|)?\s*([\d,]+)", content)
        if test_match:
            metrics["test_count"] = int(test_match.group(1).replace(",", ""))
        else:
            passed_match = re.search(r"(\d+)\s+passed", content)
            if passed_match:
                metrics["test_count"] = int(passed_match.group(1))

        # 2. 品質スコアの抽出
        pass_rate_match = re.search(r"(?:\*\*?)?(?:タスク)?(?:全体)?成功率(?:\*\*?)?\s*\|\s*(?:[\d,\-\s\*\+/%]+?\|)?\s*([\d\.]+)%", content)
        if not pass_rate_match:
            pass_rate_match = re.search(r"(?:\*\*?)?PASS率(?:\*\*?)?\s*\|\s*[^=]+=\s*(?:\*\*?)?([\d\.]+)%", content)
        if not pass_rate_match:
            pass_rate_match = re.search(r"(?:\*\*?)?PASS率(?:\*\*?)?\s*\|\s*(?:\*\*?)?([\d\.]+)%", content)
        if not pass_rate_match:
            pass_rate_match = re.search(r"(?:\*\*?)?(?:タスク)?(?:全体)?成功率(?:\*\*?)?\s*(?:[\d,\-\s\*\+/%]+?\|)?\s*([\d\.]+)%", content)
            
        if pass_rate_match:
            metrics["quality_score"] = float(pass_rate_match.group(1))

        # 3. リソース使用量の抽出
        task_match = re.search(r"(?:\*\*?)?(?:累計)?完了タスク(?:\*\*?)?\s*\|\s*(?:\*\*?)?([\d,]+)件", content)
        if not task_match:
            task_match = re.search(r"(?:\*\*?)?完了タスク(?:\*\*?)?\s*\|\s*([\d,]+)", content)
        if not task_match:
            task_match = re.search(r"(?:\*\*?)?完了バッチ数(?:\*\*?)?\s*\|\s*(?:[\d,\-\s\*\+/%]+?\|)?\s*([\d,]+)", content)
            
        if task_match:
            metrics["resource_usage"] = int(task_match.group(1).replace(",", ""))

        if metrics["resource_usage"] is None:
            total_tasks_match = re.search(r"(?:\*\*?)?(?:タスク)?(?:全体)?成功率(?:\*\*?)?\s*\|\s*(?:[\d\.]+%?\s*)?\(\s*\d+\s*/\s*(\d+)\s*\)", content)
            if total_tasks_match:
                metrics["resource_usage"] = int(total_tasks_match.group(1))
            
    except Exception as e:
        print(f"Warning: レポートのパースに失敗しました ({filepath}): {e}")
        
    return metrics


def register_tdr_debts(alerts):
    """検知した弱点アラートを TechnicalDebtStore に登録する。
    
    Args:
        alerts (list): アラート情報のリスト
    """
    if not alerts:
        return
        
    workspace_dir = _get_gsr_attr("WORKSPACE_DIR", WORKSPACE_DIR)
    try:
        backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        if backend_dir not in sys.path:
            sys.path.append(backend_dir)
            
        from agents.memory.technical_debt import TechnicalDebtStore
        store = TechnicalDebtStore()
        
        for alert in alerts:
            rel_file_path = os.path.relpath(alert["file_path"], workspace_dir).replace("\\", "/")
            
            category = "MINOR_INFRA"
            line_number = 1
            pattern = f"AUTOMATED_ALERT: {alert['type'].upper()}"
            
            store.register_debt(
                category=category,
                file_path=rel_file_path,
                line_number=line_number,
                pattern=pattern,
                cause_pattern="DP-06",
                fix_pattern="システム安定性の確認と品質/リソースの適正化",
                registered_by="generate_subagent_reports",
                notes=alert["msg"],
                tags=["alert", alert["type"]]
            )
    except Exception as e:
        print(f"Warning: TDRへの弱点登録に失敗しました: {e}")


def generate_trend_table(periodic_report_dir):
    """定時レポートフォルダ内のファイルからメトリクスを収集し、長期メトリクストレンド表のマークダウンを生成する。
    
    Args:
        periodic_report_dir (str): 定時レポートの格納ディレクトリパス
        
    Returns:
        str: 長期メトリクストレンド表のマークダウン文字列
    """
    report_files = []
    patterns = [
        os.path.join(periodic_report_dir, "daily_report_*.md"),
        os.path.join(periodic_report_dir, "periodic_report_*.md"),
        os.path.join(periodic_report_dir, "phase_*_completion_*.md")
    ]
    for pattern in patterns:
        report_files.extend(glob.glob(pattern))
        
    report_data = []
    seen_dates = set()
    extractor_date = _get_gsr_attr("extract_date", extract_date)
    for fpath in report_files:
        d = extractor_date(fpath)
        filename = os.path.basename(fpath)
        score = 0
        phase_num = 0
        if "daily_report" in filename:
            score = 3
        elif "periodic_report" in filename:
            score = 2
        elif "completion" in filename:
            score = 1
            match = re.search(r"phase_(\d+)", filename)
            if match:
                phase_num = int(match.group(1))
            
        report_data.append((d, score, phase_num, fpath))
        
    report_data.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    
    unique_report_data = []
    for d, score, phase_num, fpath in report_data:
        if d not in seen_dates:
            seen_dates.add(d)
            unique_report_data.append((d, fpath))
            
    trend_rows = []
    analysis_alerts = []
    
    metrics_extractor = _get_gsr_attr("extract_metrics_from_report", extract_metrics_from_report)
    link_resolver = _get_gsr_attr("get_rel_link", get_rel_link)
    for d, fpath in unique_report_data[:10]:
        filename = os.path.basename(fpath)
        metrics = metrics_extractor(fpath)
        
        q_score_str = f"{metrics['quality_score']:.1f}%" if metrics["quality_score"] is not None else "N/A"
        test_count_str = f"{metrics['test_count']:,}" if metrics["test_count"] is not None else "N/A"
        resource_str = f"{metrics['resource_usage']} 件" if metrics["resource_usage"] is not None else "N/A"
        
        rel_link = link_resolver(fpath)
        
        trend_rows.append(f"| {d} | [{filename}]({rel_link}) | {q_score_str} | {test_count_str} | {resource_str} |")
        
        if metrics["quality_score"] is not None and metrics["quality_score"] < 90.0:
            analysis_alerts.append({
                "type": "quality_drop",
                "file_path": fpath,
                "value": metrics["quality_score"],
                "threshold": 90.0,
                "msg": f"品質スコア低下（{metrics['quality_score']:.1f}%）が検知されました（しきい値: 90.0%）。"
            })
            
        if metrics["resource_usage"] is not None and metrics["resource_usage"] > 300:
            analysis_alerts.append({
                "type": "resource_overload",
                "file_path": fpath,
                "value": metrics["resource_usage"],
                "threshold": 300,
                "msg": f"リソース過多（完了タスク数: {metrics['resource_usage']}件）が検知されました（しきい値: 300件）。"
            })

    debt_registrar = _get_gsr_attr("register_tdr_debts", register_tdr_debts)
    debt_registrar(analysis_alerts)

    if trend_rows:
        table_md = "\n## 📈 長期メトリクストレンド\n\n| 日付 | 包括レポート | 品質スコア | テスト数 | リソース使用量 (タスク数) |\n|:---:|:---|:---:|:---:|:---|\n"
        table_md += "\n".join(trend_rows) + "\n"
        return table_md
    else:
        return ""


def generate_time_aggregation(cache: dict = None) -> str:
    """flash_reports.jsonlの原データから1h/6h/24h/通算の時間集約を動的計算する。
    
    過去レポートに依存せず、毎回原データから再計算。
    
    Args:
        cache (dict): キャッシュ用辞書
        
    Returns:
        str: 時間帯別活動サマリーのマークダウン文字列
    """
    loader = _get_gsr_attr("_load_flash_reports_cached", _load_flash_reports_cached)
    all_entries = loader(cache)
    if not all_entries:
        return ""

    now_utc = datetime.now(timezone.utc)
    buckets = {
        "直近1時間": {"hours": 1, "batches": 0, "passed": 0, "failed": 0, "files": 0},
        "直近6時間": {"hours": 6, "batches": 0, "passed": 0, "failed": 0, "files": 0},
        "直近24時間": {"hours": 24, "batches": 0, "passed": 0, "failed": 0, "files": 0},
        "セッション通算": {"hours": None, "batches": 0, "passed": 0, "failed": 0, "files": 0},
    }

    parser = _get_gsr_attr("parse_iso_datetime", parse_iso_datetime)
    for entry in all_entries:
        ts_str = entry.get("timestamp") or entry.get("completed_at")
        entry_dt = parser(ts_str) if ts_str else None
        results = entry.get("results", {})
        p = results.get("passed", 0)
        fa = results.get("failed", 0)
        git_diff = entry.get("git_diff_summary", {})
        files_count = git_diff.get("files_changed", 0)
        if isinstance(files_count, list):
            files_count = len(files_count)

        for label, bucket in buckets.items():
            if bucket["hours"] is None:
                bucket["batches"] += 1
                bucket["passed"] += p
                bucket["failed"] += fa
                bucket["files"] += files_count
            elif entry_dt:
                cutoff = now_utc - timedelta(hours=bucket["hours"])
                if entry_dt >= cutoff:
                    bucket["batches"] += 1
                    bucket["passed"] += p
                    bucket["failed"] += fa
                    bucket["files"] += files_count

    md = "\n### ⏱️ 時間帯別活動サマリー（原データから自動集計）\n\n"
    md += "| 時間帯 | バッチ数 | タスク完了 | 成功率 | 変更ファイル数 |\n"
    md += "|:---|:---:|:---:|:---:|:---:|\n"

    for label, bucket in buckets.items():
        total = bucket["passed"] + bucket["failed"]
        rate = f"{(bucket['passed'] / total * 100):.1f}%" if total > 0 else "N/A"
        md += f"| {label} | {bucket['batches']} | {total} | {rate} | {bucket['files']} |\n"

    return md


def _get_current_phase() -> str:
    """phase_state.jsonから現在のPhase番号を取得する。
    
    Returns:
        str: 現在のPhase番号文字列。取得できない場合は '?'
    """
    workspace_dir = _get_gsr_attr("WORKSPACE_DIR", WORKSPACE_DIR)
    path = os.path.join(workspace_dir, "backend", "agents", "memory", "phase_state.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            evo = data.get("evolution_phase")
            if evo:
                return str(evo)
            return str(data.get("current_phase", "?"))
    except Exception:
        return "?"


def _calc_daily_effectiveness(cache: dict = None) -> dict:
    """flash_reports.jsonlから日別の有効打率を計算する。
    
    Args:
        cache (dict): キャッシュ用辞書
        
    Returns:
        dict: {日付文字列: {'total': int, 'effective': int, 'files': int}}
    """
    from collections import defaultdict
    daily = defaultdict(lambda: {'total': 0, 'effective': 0, 'files': 0})
    
    try:
        loader = _get_gsr_attr("_load_flash_reports_cached", _load_flash_reports_cached)
        all_entries = loader(cache)
        parser = _get_gsr_attr("parse_iso_datetime", parse_iso_datetime)
        for entry in all_entries:
            ts = parser(entry.get("timestamp"))
            if not ts:
                continue
            day = (ts + timedelta(hours=9)).strftime("%m/%d")
            
            for task in entry.get("tasks", []):
                daily[day]['total'] += 1
                result = task.get("result", {}) or {}
                if isinstance(result, dict):
                    cf = result.get("changed_files", [])
                    if isinstance(cf, list) and len(cf) > 0:
                        daily[day]['effective'] += 1
                        daily[day]['files'] += len(cf)
    except Exception:
        pass
    
    return dict(daily)


def _safe_read_json_local(path, default=None):
    """ローカルのJSONファイルを安全に読み込む。
    
    Args:
        path (str): ファイルパス
        default (any): 読み込み失敗時のデフォルト値
        
    Returns:
        any: パースされたJSONオブジェクト、またはデフォルト値
    """
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _parse_event_ts(ts_str):
    """イベントログのタイムスタンプ形式 '2026-05-25 23:15 JST' を datetime オブジェクトに変換する。
    
    Args:
        ts_str (str): タイムスタンプ文字列
        
    Returns:
        datetime: タイムスタンプオブジェクト
    """
    if not ts_str:
        return None
    try:
        clean = ts_str.replace(" JST", "").strip()
        dt = datetime.strptime(clean, "%Y-%m-%d %H:%M")
        return dt.replace(tzinfo=timezone(timedelta(hours=9)))
    except ValueError:
        return None


def _module_to_topic(module_path: str, group: str = "") -> str:
    """モジュールのファイルパスを短い日本語のトピック解説に変換する。
    
    Args:
        module_path (str): モジュールのパス
        group (str): エージェントグループ
        
    Returns:
        str: 日本語のトピック解説
    """
    basename = os.path.basename(module_path).replace(".py", "") if module_path else ""
    if not basename or basename == "N/A":
        return "一般処理"

    TOPIC_MAP = {
        "ab_test_tracker": "ABテスト追跡",
        "context": "コンテキスト管理",
        "nexus": "Nexus統合基盤",
        "generator": "生成エンジン",
        "conftest": "テスト基盤設定",
        "health_check": "ヘルスチェック",
        "list_models": "モデル一覧管理",
        "video_hash": "動画ハッシュ算出",
        "admin_channel_router": "管理チャネルAPI",
        "lightweight_scan_plugin": "軽量スキャン",
        "design_system_plugin": "デザインシステム",
        "phase0_preflight": "Phase0事前チェック",
        "verify_learning": "学習検証",
        "analyze_coverage": "カバレッジ分析",
        "advisor_gate": "アドバイザ制御",
        "vector_search": "ベクトル検索",
        "get_next_batch": "バッチ取得",
        "integrated_preview": "統合プレビュー",
        "ast_branch_analysis": "AST分岐分析",
        "orchestration_hub": "共通処理機構",
        "generate_subagent_reports": "レポート生成",
        "improvement_analyzer": "改善分析",
        "flash_session": "Flashセッション管理",
        "generate_flash_prompt": "Flash指示生成",
        "task_queue": "タスクキュー管理",
        "technical_debt": "技術負債管理",
        "verified_facts": "検証済み事実",
        "phase_state": "Phase状態管理",
        "ratchet": "ラチェット検証",
        "subtitle_engine": "字幕エンジン",
        "video_editor": "動画編集",
        "audio_processor": "音声処理",
        "thumbnail_generator": "サムネイル生成",
        "branding_manager": "ブランド管理",
        "pipeline_runner": "パイプライン実行",
        "api_client": "API通信",
        "config": "設定管理",
        "utils": "ユーティリティ",
        "models": "データモデル",
        "schemas": "スキーマ定義",
        "main": "メインエントリ",
    }

    if basename in TOPIC_MAP:
        return TOPIC_MAP[basename]

    clean = basename
    if clean.startswith("test_"):
        clean = clean[5:]
        if clean in TOPIC_MAP:
            return TOPIC_MAP[clean] + "テスト"

    SUFFIX_MAP = {
        "_router": "APIルーティング",
        "_plugin": "プラグイン",
        "_engine": "エンジン",
        "_manager": "管理",
        "_handler": "ハンドラ",
        "_service": "サービス",
        "_store": "ストア",
        "_validator": "バリデーション",
        "_processor": "処理",
        "_generator": "生成",
        "_analyzer": "分析",
        "_tracker": "追跡",
    }
    for suffix, topic_suffix in SUFFIX_MAP.items():
        if clean.endswith(suffix):
            prefix = clean[:-len(suffix)].replace("_", " ").strip()
            return f"{prefix} {topic_suffix}".strip()

    return clean.replace("_", " ").title()[:20]


__all__ = [
    "get_tdr_stats",
    "extract_metrics_from_report",
    "generate_trend_table",
    "generate_time_aggregation",
    "_calc_daily_effectiveness",
    "_safe_read_json_local",
    "_parse_event_ts",
    "get_recent_git_commits",
    "_infer_group_from_module",
    "_module_to_topic",
    "_get_current_phase",
    "register_tdr_debts",
]
