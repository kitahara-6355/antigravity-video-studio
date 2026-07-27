"""ダッシュボードセクション生成モジュール — DS-038 レポート分割 Phase 1

generate_subagent_reports.py からのダッシュボード生成関数の段階的分離。
Phase 1: 元ファイルからの再エクスポート（後方互換維持）
Phase 2: 関数コードの物理移動（次回Flash実行時）
"""

# Phase 1: 元モジュールからの再エクスポート
from backend.agents.orchestration.generate_subagent_reports import (
    get_flash_status_md,
    get_directive_md,
    generate_batch_timeline,
    generate_task_detail_summary,
    generate_session_cumulative_stats,
    generate_session_context_efficiency,
    generate_roadmap_progress,
    generate_improvement_history,
    generate_kaizen_dashboard,
    generate_stability_metrics,
    generate_efficiency_and_parallel_metrics,
    generate_agent_ranking_inline,
    generate_task_summary_top20,
    generate_tri_agent_council_logs_md,
    _generate_opus_health_md,
)

__all__ = [
    "get_flash_status_md",
    "get_directive_md",
    "generate_batch_timeline",
    "generate_task_detail_summary",
    "generate_session_cumulative_stats",
    "generate_session_context_efficiency",
    "generate_roadmap_progress",
    "generate_improvement_history",
    "generate_kaizen_dashboard",
    "generate_stability_metrics",
    "generate_efficiency_and_parallel_metrics",
    "generate_agent_ranking_inline",
    "generate_task_summary_top20",
    "generate_tri_agent_council_logs_md",
    "_generate_opus_health_md",
]
