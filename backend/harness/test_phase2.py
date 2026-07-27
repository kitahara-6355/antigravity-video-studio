"""
Phase 2 Integration Test — パイプラインツール登録 & Evaluator-Optimizer
"""
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def test_phase2():
    print("=" * 60)
    print("Phase 2 Integration Test")
    print("=" * 60)
    passed = 0
    failed = 0

    # 1. Pipeline Tools Registration
    print("\n--- 1. Pipeline Tools Registration ---")
    try:
        from harness.pipeline_tools import register_pipeline_tools
        from harness.tool_registry import tool_registry

        register_pipeline_tools()
        tools = tool_registry.list_tools()
        tool_names = [t["name"] for t in tools]

        expected = [
            "mcp__antigravity_pipeline__transcribe_video",
            "mcp__antigravity_pipeline__proofread_subtitles",
            "mcp__antigravity_pipeline__propose_smart_cut",
            "mcp__antigravity_pipeline__generate_preview",
            "mcp__antigravity_pipeline__optimize_youtube",
            "mcp__antigravity_pipeline__check_quality",
            "mcp__antigravity_pipeline__render_final",
        ]

        registered = 0
        for exp in expected:
            if exp in tool_names:
                registered += 1
            else:
                print(f"  ⚠️ Missing: {exp}")

        print(f"  Registered: {registered}/{len(expected)} pipeline tools")
        print(f"  Total tools in registry: {len(tools)}")
        assert registered == len(expected), f"Only {registered}/{len(expected)} tools registered"
        print("  ✅ Pipeline Tools Registration OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ FAILED: {e}")
        failed += 1

    # 2. Tool Description Quality (ACI Check)
    print("\n--- 2. ACI Quality Check ---")
    try:
        tools = tool_registry.list_tools()
        pipeline_names = {"transcribe_video", "proofread_subtitles", "propose_smart_cut",
                          "generate_preview", "optimize_youtube", "check_quality", "render_final"}
        pipeline_tools = [t for t in tools if t["name"].split("__")[-1] in pipeline_names]

        all_have_desc = True
        for t in pipeline_tools:
            desc = t["description"]
            name = t["name"].split("__")[-1]
            has_jp = any(ord(c) > 127 for c in desc)
            has_newline = "\n" in desc
            long_enough = len(desc) > 30
            if not (has_jp and long_enough):
                print(f"  ⚠️ {name}: desc too short or not Japanese")
                all_have_desc = False
            else:
                print(f"  ✓ {name}: {len(desc)}chars, JP={has_jp}")

        assert all_have_desc, "Some tools have poor descriptions"
        print("  ✅ ACI Quality OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ FAILED: {e}")
        failed += 1

    # 3. Tool Annotations
    print("\n--- 3. Tool Annotations ---")
    try:
        render_tool = tool_registry.get_tool("render_final")
        check_tool = tool_registry.get_tool("check_quality")

        assert render_tool is not None, "render_final not found"
        assert check_tool is not None, "check_quality not found"

        # render は destructive
        assert render_tool.annotations.destructiveHint is True, "render should be destructive"
        # check は read-only
        assert check_tool.annotations.readOnlyHint is True, "check should be read-only"

        print(f"  render_final: destructive={render_tool.annotations.destructiveHint}")
        print(f"  check_quality: readOnly={check_tool.annotations.readOnlyHint}")
        print("  ✅ Tool Annotations OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ FAILED: {e}")
        failed += 1

    # 4. Tool Scopes
    print("\n--- 4. Tool Required Scopes ---")
    try:
        transcribe = tool_registry.get_tool("transcribe_video")
        proofread = tool_registry.get_tool("proofread_subtitles")

        assert "transcriber" in transcribe.required_scopes, "transcribe should require transcriber scope"
        assert "proofreader" in proofread.required_scopes, "proofread should require proofreader scope"

        print(f"  transcribe_video: scopes={transcribe.required_scopes}")
        print(f"  proofread_subtitles: scopes={proofread.required_scopes}")
        print("  ✅ Tool Scopes OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ FAILED: {e}")
        failed += 1

    # 5. Evaluator
    print("\n--- 5. QualityEvaluator ---")
    try:
        from harness.evaluator_optimizer import QualityEvaluator

        evaluator = QualityEvaluator()
        diagnosis = evaluator.evaluate(
            {
                "score": 65,
                "rank": "C",
                "feedback": [
                    "音声ラウドネスが基準外",
                    "字幕に固有名詞誤りあり",
                    "構成バランスが冗長",
                ],
                "category_scores": {"audio_quality": 50, "subtitle_accuracy": 60},
            },
            None,
        )

        assert diagnosis.score == 65, "Score mismatch"
        assert not diagnosis.passed, "Should not pass"
        assert diagnosis.improvable, "Should be improvable"
        assert len(diagnosis.issues) >= 3, "Should have issues"
        assert diagnosis.improvement_potential > 0, "Should have improvement potential"

        print(f"  Score: {diagnosis.score} (passed={diagnosis.passed})")
        print(f"  Issues: {len(diagnosis.issues)}")
        print(f"  Improvement potential: +{diagnosis.improvement_potential}pt")
        print(f"  Improvable: {diagnosis.improvable}")
        print("  ✅ QualityEvaluator OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ FAILED: {e}")
        failed += 1

    # 6. Optimizer
    print("\n--- 6. QualityOptimizer ---")
    try:
        from harness.evaluator_optimizer import QualityOptimizer

        optimizer = QualityOptimizer()
        plan = optimizer.plan(diagnosis)

        assert len(plan.actions) > 0, "Should have actions"
        assert plan.total_estimated_gain > 0, "Should have estimated gain"

        print(f"  Actions: {len(plan.actions)}")
        print(f"  Estimated gain: +{plan.total_estimated_gain}pt")
        print(f"  Strategy: {plan.strategy[:80]}...")
        for action in plan.actions:
            print(f"    [{action.priority}] {action.action_id}: +{action.estimated_gain}pt")
        print("  ✅ QualityOptimizer OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ FAILED: {e}")
        failed += 1

    # 7. Evaluator for passing score
    print("\n--- 7. Evaluator (Passing Score) ---")
    try:
        diagnosis_pass = evaluator.evaluate(
            {"score": 92, "rank": "A", "feedback": [], "category_scores": {}},
            None,
        )
        assert diagnosis_pass.passed, "Score 92 should pass"
        plan_pass = optimizer.plan(diagnosis_pass)
        assert len(plan_pass.actions) == 0, "No actions needed for passing"
        print(f"  Score: {diagnosis_pass.score} → passed={diagnosis_pass.passed}")
        print(f"  Plan: {plan_pass.strategy}")
        print("  ✅ Passing Score OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ FAILED: {e}")
        failed += 1

    # 8. EvaluatorOptimizer instantiation
    print("\n--- 8. EvaluatorOptimizer Workflow ---")
    try:
        from harness.evaluator_optimizer import evaluator_optimizer

        assert evaluator_optimizer is not None
        assert evaluator_optimizer.evaluator is not None
        assert evaluator_optimizer.optimizer is not None
        assert evaluator_optimizer.executor is not None
        print(f"  Workflow: {type(evaluator_optimizer).__name__}")
        print(f"  Max iterations: {evaluator_optimizer.MAX_ITERATIONS}")
        print("  ✅ EvaluatorOptimizer Workflow OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ FAILED: {e}")
        failed += 1

    # 9. Tool stats after registration
    print("\n--- 9. Registry Stats ---")
    try:
        stats = tool_registry.get_stats()
        print(f"  Server: {stats['server']} v{stats['version']}")
        print(f"  Total tools: {stats['tool_count']}")
        for name, ts in stats["tools"].items():
            print(f"    {name}: {ts['calls']} calls, {ts['errors']} errors")
        print("  ✅ Registry Stats OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ FAILED: {e}")
        failed += 1

    # Final
    print("\n" + "=" * 60)
    total = passed + failed
    if failed == 0:
        print(f"✅ ALL {passed}/{total} TESTS PASSED")
    else:
        print(f"❌ {failed}/{total} TESTS FAILED, {passed} passed")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(test_phase2())
    sys.exit(0 if success else 1)
