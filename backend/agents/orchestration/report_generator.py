"""レポート生成エントリポイントモジュール — DS-038 レポート分割 Phase 1

generate_subagent_reports.py からのメインエントリ関数の段階的分離。
Phase 1: 元ファイルからの再エクスポート（後方互換維持）
Phase 2: 関数コードの物理移動（次回Flash実行時）

ユーティリティ関数（parse_iso_datetime, format_duration, extract_date, 
get_week_range_str, find_latest_brain_report）も含む。
"""

import os
import sys

# パスの定義（デフォルトは相対パス）
WORKSPACE_DIR_LOCAL = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if WORKSPACE_DIR_LOCAL not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR_LOCAL)
backend_path = os.path.join(WORKSPACE_DIR_LOCAL, "backend")
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

# Phase 1: 元モジュールからの再エクスポート
from backend.agents.orchestration.generate_subagent_reports import (
    main,
    generate_dashboard_quick,
    find_latest_brain_report,
    parse_iso_datetime,
    format_duration,
    extract_date,
    get_week_range_str,
    # パス定数
    WORKSPACE_DIR,
    ORCHESTRATION_DIR,
    TASK_QUEUE_PATH,
    FLASH_SESSION_PATH,
    FLASH_REPORTS_PATH,
    OFFICIAL_ARTIFACT_DIR,
    REPORT_BASE_DIR,
    PERIODIC_REPORT_DIR,
    BULLETIN_REPORT_DIR,
    RANKING_REPORT_DIR,
)

__all__ = [
    "main",
    "generate_dashboard_quick",
    "find_latest_brain_report",
    "parse_iso_datetime",
    "format_duration",
    "extract_date",
    "get_week_range_str",
    "WORKSPACE_DIR",
    "ORCHESTRATION_DIR",
    "TASK_QUEUE_PATH",
    "FLASH_SESSION_PATH",
    "FLASH_REPORTS_PATH",
    "OFFICIAL_ARTIFACT_DIR",
    "REPORT_BASE_DIR",
    "PERIODIC_REPORT_DIR",
    "BULLETIN_REPORT_DIR",
    "RANKING_REPORT_DIR",
]

if __name__ == "__main__":
    main()
