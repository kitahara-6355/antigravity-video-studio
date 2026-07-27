"""Coverage gap analysis: identify highest-impact modules for 70% target."""

# Data from full test coverage run (49%, 17688 stmts, 9053 missed)
modules = [
    ("routers/youtube_optimizer.py", 680, 202, 70),
    ("quality_gate_plugins.py", 468, 67, 86),
    ("routers/pipeline_router.py", 398, 258, 35),
    ("routers/themes_router.py", 359, 191, 47),
    ("video_processor.py", 297, 218, 27),
    ("director_engine.py", 439, 264, 40),
    ("video_editor_engine.py", 261, 111, 57),
    ("routers/legacy_production_router.py", 290, 101, 65),
    ("routers/usage_router.py", 276, 139, 50),
    ("branding_manager.py", 297, 124, 58),
    ("interactive_preview.py", 281, 111, 61),
    ("routers/shorts.py", 121, 97, 20),
    ("routers/smartcut.py", 121, 82, 32),
    ("subtitle_engine/whisper_subprocess.py", 154, 154, 0),
    ("subtitle_engine/speaker_diarizer.py", 154, 154, 0),
    ("wagamama_manager.py", 118, 81, 31),
    ("routers/soul_router.py", 98, 68, 31),
    ("subtitle_normalizer.py", 121, 70, 42),
    ("telop_proposal_engine.py", 127, 76, 40),
    ("template_recommender.py", 112, 112, 0),
    ("thumbnail_engine/generator.py", 78, 78, 0),
    ("routers/segments.py", 45, 34, 24),
    ("usage_tracker/quota_manager.py", 116, 74, 36),
    ("usage_tracker/sdk_checker.py", 114, 88, 23),
    ("routers/pipeline_report.py", 190, 19, 90),
    ("routers/review_router.py", 107, 15, 86),
    ("draft_manager.py", 138, 75, 46),
    ("asset_library.py", 264, 177, 33),
    ("generation_engine.py", 184, 140, 24),
    ("philosophy_manager.py", 209, 172, 18),
    ("routers/quality.py", 63, 63, 0),
    ("routers/render.py", 75, 64, 15),
    ("routers/preview.py", 82, 38, 54),
    ("routers/director.py", 39, 23, 41),
    ("cleanup_manager.py", 92, 59, 36),
    ("services/preview_report_generator.py", 164, 109, 34),
    ("routers/collaboration.py", 85, 55, 35),
    ("routers/dashboard_router.py", 35, 24, 31),
    ("routers/legacy_management_router.py", 137, 98, 28),
    ("routers/legacy_council_router.py", 36, 22, 39),
    ("routers/legacy_director_router.py", 47, 27, 43),
    ("routers/legacy_live_websocket.py", 35, 26, 26),
    ("routers/approval_router.py", 42, 26, 38),
    ("routers/websocket.py", 55, 40, 27),
    ("routers/youtube_upload.py", 64, 54, 16),
    ("routers/philosophy_router.py", 38, 24, 37),
    ("routers/ab_test_tracker.py", 98, 78, 20),
    ("routers/trinity.py", 31, 18, 42),
    ("mcp_server.py", 104, 83, 20),
    ("data_migration.py", 72, 55, 24),
    ("disk_manager.py", 66, 42, 36),
    ("dispatch_enhancer.py", 87, 59, 32),
    ("subtitle_confirmation.py", 91, 61, 33),
    ("ai_rhythm.py", 19, 12, 37),
    ("log_manager.py", 55, 40, 27),
    ("live_api_handler.py", 35, 23, 34),
    ("safe_io.py", 44, 16, 64),
    ("gcp_cost_monitor.py", 36, 28, 22),
    ("cache_manager.py", 45, 30, 33),
    ("antigravity_api.py", 70, 29, 59),
    ("antigravity_pipeline.py", 59, 38, 36),
    ("api_versioning.py", 27, 15, 44),
    ("main.py", 107, 56, 48),
    ("logging_middleware.py", 31, 19, 39),
    ("settings_manager.py", 48, 23, 52),
    ("quality_gate_agent.py", 98, 56, 43),
    ("core/state_store.py", 63, 16, 75),
    ("self_review_engine.py", 115, 78, 32),
    ("agents/dream_engine.py", 192, 149, 22),
    ("agents/advisor_gate.py", 75, 56, 25),
    ("error_reporter.py", 95, 15, 84),
    ("logo_overlay.py", 73, 48, 34),
    ("audio_master.py", 67, 28, 58),
    ("phase1_full_processing.py", 56, 30, 46),
    ("gemini_client_factory.py", 38, 18, 53),
    ("project_archiver.py", 35, 24, 31),
    ("tutorial_system.py", 29, 29, 0),
    ("manager_monitoring.py", 24, 18, 25),
]

# Report Formatting Constants
REPORT_MODULE_WIDTH = 50
REPORT_LINE_WIDTH = 80
GAP_THRESHOLD = 50


def _validate_inputs(
    coverage_modules,
    total_statements,
    total_missed_statements,
    target_coverage_pct,
):
    """Validate argument types and ranges."""
    if not (0 <= target_coverage_pct <= 100):
        raise ValueError("target_pct must be between 0 and 100")
    if total_statements < 0 or total_missed_statements < 0:
        raise ValueError("total_stmts and current_missed must be non-negative")
    if not isinstance(coverage_modules, list):
        raise TypeError("coverage_modules must be a list")
    for idx, item in enumerate(coverage_modules):
        if not isinstance(item, (tuple, list)) or len(item) != 4:
            raise ValueError(f"Module item at index {idx} must be a tuple/list of length 4")
        # Validate that values inside the tuple are of correct types (str, int, int, int)
        if not isinstance(item[0], str) or not all(isinstance(val, int) for val in item[1:4]):
            raise TypeError("Module tuple types must be (str, int, int, int)")


def _calculate_gap_metrics(sorted_modules, needed_to_cover):
    """Compute gap percentages and markers for sorted modules."""
    results = []
    for name, statements, missed_statements, coverage_pct in sorted_modules:
        gap_percentage = (
            (missed_statements / needed_to_cover * 100)
            if needed_to_cover > 0
            else 0.0
        )
        marker = " <<<" if missed_statements >= GAP_THRESHOLD else ""
        results.append({
            "name": name,
            "statements": statements,
            "missed_statements": missed_statements,
            "coverage_pct": coverage_pct,
            "gap_percentage": gap_percentage,
            "marker": marker
        })
    return results


def _calculate_final_coverage(
    total_statements, total_missed_statements, total_missed_listed
):
    """Calculate the final coverage percentage assuming listed misses are covered."""
    if total_statements <= 0:
        return 0.0
    remaining_missed = total_missed_statements - total_missed_listed
    return (total_statements - remaining_missed) / total_statements * 100


def calculate_gap(
    coverage_modules,
    total_statements=17688,
    total_missed_statements=9053,
    target_coverage_pct=70,
):
    """Calculate the coverage gap to achieve target_coverage_pct."""
    _validate_inputs(
        coverage_modules,
        total_statements,
        total_missed_statements,
        target_coverage_pct,
    )

    sorted_modules = sorted(coverage_modules, key=lambda x: x[2], reverse=True)
    max_missed_statements = int(
        total_statements * (100 - target_coverage_pct) / 100
    )
    needed_to_cover = total_missed_statements - max_missed_statements

    results = _calculate_gap_metrics(sorted_modules, needed_to_cover)
    total_missed_listed = sum(m[2] for m in sorted_modules)
    final_coverage = _calculate_final_coverage(
        total_statements, total_missed_statements, total_missed_listed
    )

    return {
        "sorted_modules": results,
        "max_missed_statements": max_missed_statements,
        "needed_to_cover": needed_to_cover,
        "total_missed_listed": total_missed_listed,
        "final_coverage_pct": final_coverage,
    }


def print_report(
    results,
    total_statements=17688,
    total_missed_statements=9053,
    target_coverage_pct=70,
):
    """Print the gap analysis report to stdout."""
    print(
        f"Current: 49% ({total_statements} stmts, {total_missed_statements} missed)"
    )
    print(
        f"Target: {target_coverage_pct}% (max {results['max_missed_statements']} missed)"
    )
    print(
        f"Need to cover: {results['needed_to_cover']} additional stmts"
    )
    print()
    print(
        f"{'Module':<{REPORT_MODULE_WIDTH}} {'Stmts':>6} {'Miss':>6} {'Cov%':>5} {'%Gap':>6}"
    )
    print("-" * REPORT_LINE_WIDTH)

    for r in results["sorted_modules"]:
        print(
            f"{r['name']:<{REPORT_MODULE_WIDTH}} {r['statements']:>6} {r['missed_statements']:>6} {r['coverage_pct']:>4}% {r['gap_percentage']:>5.1f}%{r['marker']}"
        )

    print("-" * REPORT_LINE_WIDTH)
    print(f"Total missed in listed modules: {results['total_missed_listed']}")
    print(
        f"Cumulative coverage after covering all: {results['final_coverage_pct']:.1f}%"
    )


def main():
    """Main execution function."""
    res = calculate_gap(modules)
    print_report(res)


if __name__ == "__main__":  # pragma: no cover
    main()



