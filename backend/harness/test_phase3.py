"""
Phase 3 Integration Test — Harness-ADK ブリッジ統合検証
"""
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def test_phase3():
    print("=" * 60)
    print("Phase 3 Integration Test — Harness-ADK Bridge")
    print("=" * 60)
    passed = 0
    failed = 0

    # 1. ADK import check
    print("\n--- 1. Google ADK Import ---")
    try:
        from google.adk.agents import Agent, SequentialAgent, LoopAgent
        from google.adk.runners import InMemoryRunner
        import google.adk
        ver = getattr(google.adk, "__version__", "unknown")
        print(f"  ADK version: {ver}")
        print(f"  Agent, SequentialAgent, LoopAgent: OK")
        print(f"  InMemoryRunner: OK")
        print("  ✅ ADK Import OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ FAILED: {e}")
        failed += 1

    # 2. ToolRegistry → ADK tool conversion
    print("\n--- 2. ToolRegistry → ADK Tool Conversion ---")
    try:
        from harness.pipeline_tools import register_pipeline_tools
        from harness.tool_registry import tool_registry
        from harness.adk_bridge import create_adk_tool_from_registry

        # ツール登録
        if not tool_registry.get_tool("transcribe_video"):
            register_pipeline_tools()

        # 変換テスト
        adk_tool = create_adk_tool_from_registry("transcribe_video", "transcriber")

        assert callable(adk_tool), "Should be callable"
        assert adk_tool.__name__ == "transcribe_video", "Name mismatch"
        assert adk_tool.__doc__ is not None, "Doc missing"
        assert "return" in adk_tool.__annotations__, "Missing return annotation"

        print(f"  Name: {adk_tool.__name__}")
        print(f"  Doc: {adk_tool.__doc__[:60]}...")
        print(f"  Annotations: {list(adk_tool.__annotations__.keys())}")
        print("  ✅ Tool Conversion OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ FAILED: {e}")
        failed += 1

    # 3. All 7 tools convert successfully
    print("\n--- 3. All 7 Tools Conversion ---")
    try:
        tool_names = [
            ("transcribe_video", "transcriber"),
            ("proofread_subtitles", "proofreader"),
            ("propose_smart_cut", "optimizer"),
            ("generate_preview", "renderer"),
            ("check_quality", "quality_gate"),
            ("optimize_youtube", "optimizer"),
            ("render_final", "renderer"),
        ]

        for name, scope in tool_names:
            tool = create_adk_tool_from_registry(name, scope)
            assert callable(tool), f"{name} not callable"
            assert tool.__name__ == name, f"{name} name mismatch"
            print(f"  ✓ {name} → scope={scope}")

        print("  ✅ All 7 Tools Conversion OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ FAILED: {e}")
        failed += 1

    # 4. Hook integration in tool wrapper
    print("\n--- 4. Hook Integration ---")
    try:
        from harness.hooks import hook_system, HookEvent, HookInput, HookOutput

        hook_fired = []

        async def test_hook(hi):
            hook_fired.append(hi.tool_name)
            return None

        hook_system.register(
            HookEvent.PRE_TOOL_USE,
            callback=test_hook,
            matcher="transcribe_video",
            priority=99,
        )

        # 変換済みツールを実行（実際のWhisperは呼べないのでエラーになるが、Hookは発火するはず）
        adk_transcribe = create_adk_tool_from_registry("transcribe_video", "transcriber")
        result = await adk_transcribe(video_path="/test/dummy.mp4")

        assert "transcribe_video" in hook_fired, "Hook did not fire"
        print(f"  Hook fired for: {hook_fired}")
        print(f"  Result type: {type(result).__name__}")
        print("  ✅ Hook Integration OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ FAILED: {e}")
        failed += 1

    # 5. Governance integration — permission deny
    print("\n--- 5. Governance Deny ---")
    try:
        from harness.governance import governance_engine

        # renderer は transcribe_video にアクセスできない
        adk_tool_wrong_scope = create_adk_tool_from_registry("transcribe_video", "renderer")
        result = await adk_tool_wrong_scope(video_path="/test/dummy.mp4")
        result_data = json.loads(result)

        assert result_data.get("success") is False, "Should be denied"
        assert "権限不足" in result_data.get("error", ""), "Should mention permission"

        print(f"  renderer → transcribe_video: DENIED")
        print(f"  Error: {result_data['error']}")
        print("  ✅ Governance Deny OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ FAILED: {e}")
        failed += 1

    # 6. Trace span creation
    print("\n--- 6. Trace Spans ---")
    try:
        traces = governance_engine.get_recent_traces()
        adk_traces = [t for t in traces if t.get("operation") == "adk_tool_call"]
        print(f"  ADK tool call traces: {len(adk_traces)}")
        if adk_traces:
            last = adk_traces[-1]
            print(f"  Last: {last['tool_name']} status={last['status']}")
        print("  ✅ Trace Spans OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ FAILED: {e}")
        failed += 1

    # 7. Pipeline build
    print("\n--- 7. Pipeline Build ---")
    try:
        from harness.adk_bridge import build_harness_pipeline

        pipeline = build_harness_pipeline()

        assert pipeline is not None, "Pipeline is None"
        assert pipeline.name == "HarnessProductionPipeline"
        assert len(pipeline.sub_agents) == 6, f"Expected 6 sub_agents (including ReviewLoop), got {len(pipeline.sub_agents)}"

        agent_names = [a.name for a in pipeline.sub_agents]
        print(f"  Pipeline: {pipeline.name}")
        print(f"  Sub-agents ({len(agent_names)}):")
        for name in agent_names:
            print(f"    - {name}")

        print("  ✅ Pipeline Build OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ FAILED: {e}")
        failed += 1

    # 8. Hook deny blocks tool execution
    print("\n--- 8. Hook Deny Blocks Execution ---")
    try:
        deny_fired = []

        async def deny_all_render(hi):
            if hi.tool_name == "render_final":
                deny_fired.append(True)
                return HookOutput(
                    permission_decision="deny",
                    permission_decision_reason="テスト: レンダリング禁止",
                )
            return None

        hook_system.register(
            HookEvent.PRE_TOOL_USE,
            callback=deny_all_render,
            matcher="render_final",
            priority=0,
        )

        adk_render = create_adk_tool_from_registry("render_final", "renderer")
        result = await adk_render(video_path="/test/dummy.mp4", preview_path="/test/preview.mp4")
        result_data = json.loads(result)

        assert result_data.get("success") is False, "Should be denied by hook"
        assert "実行拒否" in result_data.get("error", ""), "Should mention deny"
        assert len(deny_fired) > 0, "Deny hook should have fired"

        print(f"  Hook deny result: {result_data['error']}")
        print("  ✅ Hook Deny Blocks OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ FAILED: {e}")
        failed += 1

    # 9. Session integration
    print("\n--- 9. Session Integration ---")
    try:
        from harness.session_manager import session_manager

        stats = session_manager.get_stats()
        print(f"  Sessions: {stats}")
        print("  ✅ Session Integration OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ FAILED: {e}")
        failed += 1

    # 10. Audit log captures ADK tool calls
    print("\n--- 10. Audit Log ---")
    try:
        audit = hook_system.get_audit_log(limit=10)
        adk_entries = [a for a in audit if a.get("tool_name") in ("transcribe_video", "render_final")]
        print(f"  ADK tool entries in audit: {len(adk_entries)}")
        for entry in adk_entries[-3:]:
            print(f"    {entry['event']}: {entry['tool_name']} → {entry['permission']}")
        print("  ✅ Audit Log OK")
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
    success = asyncio.run(test_phase3())
    sys.exit(0 if success else 1)
