# -*- coding: utf-8 -*-
import pytest
from backend.agents.orchestration import dashboard_generator
from backend.agents.orchestration import generate_subagent_reports

def test_dashboard_generator_reexports():
    """dashboard_generatorがすべての関数を正しく再エクスポートしているか検証"""
    expected_functions = [
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
    
    # __all__ に定義されていることを確認
    assert hasattr(dashboard_generator, "__all__")
    for func_name in expected_functions:
        assert func_name in dashboard_generator.__all__
        
        # 実際に属性として存在することを確認
        assert hasattr(dashboard_generator, func_name)
        
        # 実体が generate_subagent_reports 内のものと同一であることを確認
        func_from_gen = getattr(dashboard_generator, func_name)
        func_from_reports = getattr(generate_subagent_reports, func_name)
        assert func_from_gen is func_from_reports
