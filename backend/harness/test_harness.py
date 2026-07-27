"""
Harness Integration Test — 全モジュールの機能検証
"""
import asyncio
import json
import sys
import os

# backend ディレクトリをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def test_harness():
    from harness.tool_registry import tool_registry, ToolResult
    from harness.hooks import hook_system, HookEvent, HookInput
    from harness.session_manager import session_manager
    from harness.governance import governance_engine

    print("=" * 60)
    print("Harness Integration Test")
    print("=" * 60)
    passed = 0
    failed = 0

    # 1. Tool Registry Test
    print("\n--- 1. ToolRegistry ---")
    try:
        @tool_registry.register(
            name="test_echo",
            description="テスト用エコーツール",
            input_schema={"message": str},
        )
        async def test_echo(args):
            msg = args["message"]
            return {"content": [{"type": "text", "text": f"Echo: {msg}"}]}

        result = await tool_registry.execute("test_echo", {"message": "Hello Harness!"})
        assert result.content[0]["text"] == "Echo: Hello Harness!", "Echo mismatch"
        assert not result.is_error, "Should not be error"
        tools = tool_registry.list_tools()
        assert len(tools) >= 1, "No tools listed"
        print(f"  Result: {result.content[0]['text']}")
        print(f"  Tools listed: {len(tools)}")
        print("  ✅ ToolRegistry OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ ToolRegistry FAILED: {e}")
        failed += 1

    # 2. Poka-yoke Test
    print("\n--- 2. Poka-yoke ---")
    try:
        @tool_registry.register(
            name="test_path",
            description="パス検証テスト",
            input_schema={"video_path": str},
        )
        async def test_path(args):
            vp = args["video_path"]
            return {"content": [{"type": "text", "text": vp}]}

        result = await tool_registry.execute("test_path", {"video_path": "relative/path.mp4"})
        converted_path = result.content[0]["text"]
        is_abs = os.path.isabs(converted_path)
        print(f"  Input:  relative/path.mp4")
        print(f"  Output: {converted_path}")
        print(f"  Absolute: {is_abs}")
        assert is_abs, "Should be converted to absolute path"
        print("  ✅ Poka-yoke OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ Poka-yoke FAILED: {e}")
        failed += 1

    # 3. Missing arg validation
    print("\n--- 3. Validation ---")
    try:
        result = await tool_registry.execute("test_echo", {})  # missing "message"
        assert result.is_error, "Should be error for missing arg"
        print(f"  Missing arg error: {result.content[0]['text'][:60]}")
        print("  ✅ Validation OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ Validation FAILED: {e}")
        failed += 1

    # 4. Unknown tool
    print("\n--- 4. Unknown tool ---")
    try:
        result = await tool_registry.execute("nonexistent_tool", {})
        assert result.is_error, "Should be error for unknown tool"
        print(f"  Error message: {result.content[0]['text'][:60]}")
        print("  ✅ Unknown tool OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ Unknown tool FAILED: {e}")
        failed += 1

    # 5. Hook System Test
    print("\n--- 5. HookSystem ---")
    try:
        hook_log = []

        async def test_hook_cb(hook_input):
            hook_log.append(hook_input.tool_name)
            return None

        hook_system.register(HookEvent.PRE_TOOL_USE, callback=test_hook_cb, matcher="test_.*")
        output = await hook_system.fire(
            HookEvent.PRE_TOOL_USE,
            HookInput(tool_name="test_echo", tool_input={"msg": "hi"}),
        )
        assert "test_echo" in hook_log, "Hook did not fire"

        # 同期フック (def) のテストを追加
        sync_hook_log = []
        def test_sync_hook_cb(hook_input_sync):
            sync_hook_log.append(hook_input_sync.tool_name)
            return None
        
        hook_system.register(HookEvent.PRE_TOOL_USE, callback=test_sync_hook_cb, matcher="test_sync_.*")
        output_sync = await hook_system.fire(
            HookEvent.PRE_TOOL_USE,
            HookInput(tool_name="test_sync_tool", tool_input={"msg": "hi"}),
        )
        assert "test_sync_tool" in sync_hook_log, "Sync hook did not fire"

        audit = hook_system.get_audit_log()
        print(f"  Hook fired for: {hook_log}")
        print(f"  Audit log: {len(audit)} entries")
        print("  ✅ HookSystem OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ HookSystem FAILED: {e}")
        failed += 1

    # 6. Hook deny test
    print("\n--- 6. Hook Deny ---")
    try:
        from harness.hooks import HookOutput

        async def deny_hook(hook_input):
            if hook_input.tool_name == "dangerous_tool":
                return HookOutput(
                    permission_decision="deny",
                    permission_decision_reason="テスト: 危険なツールをブロック",
                )
            return None

        hook_system.register(HookEvent.PRE_TOOL_USE, callback=deny_hook, matcher="dangerous.*")
        output = await hook_system.fire(
            HookEvent.PRE_TOOL_USE,
            HookInput(tool_name="dangerous_tool"),
        )
        assert output.permission_decision == "deny", "Should be denied"
        print(f"  Decision: {output.permission_decision}")
        print(f"  Reason: {output.permission_decision_reason}")
        print("  ✅ Hook Deny OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ Hook Deny FAILED: {e}")
        failed += 1

    # 7. Builtin hooks
    print("\n--- 7. Builtin Hooks ---")
    try:
        hook_system.register_builtin_hooks()
        stats = hook_system.get_stats()
        print(f"  Registered hooks: {stats['registered_hooks']}")
        print("  ✅ Builtin Hooks OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ Builtin Hooks FAILED: {e}")
        failed += 1

    # 8. Session Manager Test
    print("\n--- 8. SessionManager ---")
    try:
        session = session_manager.create_session(video_path="/test/video.mp4")
        sid = session.session_id
        print(f"  Session ID: {sid[:8]}...")

        session_manager.update_stage(sid, 1, "Stage 1 完了")
        session_manager.record_tool_call(sid, "test_echo", {"msg": "hi"}, {}, 0.5)

        resumed = session_manager.resume_session(sid)
        assert resumed is not None, "Resume failed"
        assert len(resumed.tool_history) >= 2, "Tool history missing"
        print(f"  Resumed: True")
        print(f"  Tool history: {len(resumed.tool_history)} entries")

        session_manager.complete_session(sid, quality_score=85)
        completed = session_manager.get_session(sid)
        assert completed.status == "completed", "Should be completed"
        print(f"  Status: {completed.status}, Score: {completed.quality_score}")

        stats = session_manager.get_stats()
        print(f"  Stats: {stats}")
        print("  ✅ SessionManager OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ SessionManager FAILED: {e}")
        failed += 1

    # 9. Session pause/resume
    print("\n--- 9. Session Pause/Resume ---")
    try:
        s2 = session_manager.create_session(video_path="/test/video2.mp4")
        session_manager.pause_session(s2.session_id)
        paused = session_manager.get_session(s2.session_id)
        assert paused.status == "paused", "Should be paused"

        resumed2 = session_manager.resume_session(s2.session_id)
        assert resumed2.status == "active", "Should be active after resume"
        print(f"  Pause → Resume: {paused.status} → {resumed2.status}")
        print("  ✅ Session Pause/Resume OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ Session Pause/Resume FAILED: {e}")
        failed += 1

    # 10. Governance: Permission
    print("\n--- 10. Governance Permission ---")
    try:
        can_transcribe = governance_engine.check_permission("transcriber", "transcribe_video")
        cant_render = governance_engine.check_permission("transcriber", "render_final")
        cant_proofread = governance_engine.check_permission("renderer", "proofread_subtitles")
        can_render = governance_engine.check_permission("renderer", "render_final")
        no_scope = governance_engine.check_permission("unknown_agent", "anything")

        print(f"  transcriber -> transcribe_video: {can_transcribe} (expected: True)")
        print(f"  transcriber -> render_final:     {cant_render} (expected: False)")
        print(f"  renderer -> proofread_subtitles: {cant_proofread} (expected: False)")
        print(f"  renderer -> render_final:        {can_render} (expected: True)")
        print(f"  unknown -> anything:             {no_scope} (expected: True)")

        assert can_transcribe is True
        assert cant_render is False
        assert cant_proofread is False
        assert can_render is True
        assert no_scope is True
        print("  ✅ Governance Permission OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ Governance Permission FAILED: {e}")
        failed += 1

    # 11. Governance: Rate Limit
    print("\n--- 11. Rate Limit ---")
    try:
        governance_engine.reset_api_counters()
        # proofreader has max_api_calls=50
        for i in range(50):
            governance_engine.check_rate_limit("proofreader")
        over_limit = governance_engine.check_rate_limit("proofreader")
        assert over_limit is False, "Should be rate limited"
        print(f"  50 calls OK, 51st blocked: {not over_limit}")
        governance_engine.reset_api_counters()
        print("  ✅ Rate Limit OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ Rate Limit FAILED: {e}")
        failed += 1

    # 12. Governance: Trace spans
    print("\n--- 12. Trace Spans ---")
    try:
        span_id = governance_engine.start_span("test_op", "test_echo")
        governance_engine.add_span_event(span_id, "test_event", {"key": "val"})
        governance_engine.end_span(span_id, status="ok")
        traces = governance_engine.get_recent_traces()
        assert len(traces) >= 1, "No traces"
        last_trace = traces[-1]
        print(f"  Span: {last_trace['operation']}/{last_trace['tool_name']}")
        print(f"  Duration: {last_trace['duration_ms']:.0f}ms")
        print(f"  Total traces: {len(traces)}")
        print("  ✅ Trace Spans OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ Trace Spans FAILED: {e}")
        failed += 1

    # 13. Tool stats
    print("\n--- 13. Stats Summary ---")
    try:
        ts = tool_registry.get_stats()
        print(f"  Tool count: {ts['tool_count']}")
        print(f"  Server: {ts['server']} v{ts['version']}")
        gs = governance_engine.get_stats()
        print(f"  Scopes: {len(gs['scopes'])}")
        print(f"  Spans completed: {gs['completed_spans']}")
        print("  ✅ Stats OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ Stats FAILED: {e}")
        failed += 1

    # 14. Tool Registry Coverage Test
    print("\n--- 14. ToolRegistry Coverage ---")
    try:
        await test_tool_registry_coverage()
        print("  ✅ ToolRegistry Coverage OK")
        passed += 1
    except Exception as e:
        print(f"  ❌ ToolRegistry Coverage FAILED: {e}")
        failed += 1

    # Final Summary
    print("\n" + "=" * 60)
    total = passed + failed
    if failed == 0:
        print(f"✅ ALL {passed}/{total} TESTS PASSED")
    else:
        print(f"❌ {failed}/{total} TESTS FAILED, {passed} passed")
    print("=" * 60)
    return failed == 0


async def test_tool_registry_coverage():
    from harness.tool_registry import (
        ToolRegistry, ToolDefinition, ToolResult,
        _python_type_to_json_schema
    )

    # 1. デコレータで登録したツールを直接（ラッパー経由で）呼び出すテスト
    registry = ToolRegistry()
    
    @registry.register(
        name="test_direct",
        description="直接呼び出しテスト",
        input_schema={"val": int}
    )
    async def my_func(args):
        return args["val"] * 2
        
    res = await my_func({"val": 5})
    assert res == 10

    # 2. register_tool を用いた直接登録のテスト
    def my_handler(args):
        return f"Hello {args.get('name')}"
        
    tool_def = ToolDefinition(
        name="direct_tool",
        description="直接登録用ツール",
        input_schema={"name": str},
        handler=my_handler,
    )
    
    registry.register_tool(tool_def)
    assert registry.get_tool("direct_tool") is tool_def
    
    res = await registry.execute("direct_tool", {"name": "World"})
    assert res.content[0]["text"] == "Hello World"
    assert not res.is_error

    # 3. 権限スコープ検証エラーのテスト
    @registry.register(
        name="scoped_tool",
        description="スコープ付きツール",
        input_schema={},
        required_scopes={"admin", "editor"}
    )
    async def scoped_func(args):
        return "success"
        
    res = await registry.execute("scoped_tool", {}, caller_scopes=set())
    assert res.is_error
    assert "権限不足" in res.content[0]["text"]
    
    res_ok = await registry.execute("scoped_tool", {}, caller_scopes={"admin", "editor", "viewer"})
    assert not res_ok.is_error
    assert res_ok.content[0]["text"] == "success"

    # 4. 同期ハンドラ実行テスト
    @registry.register(
        name="sync_tool",
        description="同期ツール",
        input_schema={"a": int, "b": int}
    )
    def sync_add(args):
        return args["a"] + args["b"]
        
    res = await registry.execute("sync_tool", {"a": 3, "b": 4})
    assert not res.is_error
    assert res.content[0]["text"] == "7"

    # 5. ツール実行時の例外ハンドリング
    @registry.register(
        name="buggy_tool",
        description="バグのあるツール",
        input_schema={}
    )
    async def buggy_func(args):
        raise ValueError("意図的なエラー")
        
    res = await registry.execute("buggy_tool", {})
    assert res.is_error
    assert "ツール実行エラー: 意図的なエラー" in res.content[0]["text"]
    
    stats = registry.get_stats()
    assert stats["tools"]["buggy_tool"]["errors"] == 1

    # 6. 引数バリデーション (スキーマデフォルト値/Optional) のテスト
    @registry.register(
        name="complex_schema_tool",
        description="複雑なスキーマ",
        input_schema={
            "req": str,
            "opt_default": {"type": int, "default": 42},
            "opt_type": "Optional[str]",
            "none_type": "None"
        }
    )
    async def dummy(args):
        return "ok"
        
    res_fail = await registry.execute("complex_schema_tool", {})
    assert res_fail.is_error
    assert "必須引数 'req' が不足しています" in res_fail.content[0]["text"]
    
    res_ok = await registry.execute("complex_schema_tool", {"req": "hello"})
    assert not res_ok.is_error
    assert res_ok.content[0]["text"] == "ok"

    # 7. 戻り値正規化の各パターンのテスト
    @registry.register(name="return_tool_result", description="ToolResult返却", input_schema={})
    async def ret_result(args):
        return ToolResult(content=[{"type": "text", "text": "custom result"}], is_error=False)
        
    res1 = await registry.execute("return_tool_result", {})
    assert not res1.is_error
    assert res1.content[0]["text"] == "custom result"
    
    @registry.register(name="return_status_error", description="エラーstatus返却", input_schema={})
    async def ret_status_error(args):
        return {"status": "error", "message": "something went wrong"}
        
    res2 = await registry.execute("return_status_error", {})
    assert res2.is_error
    assert "something went wrong" in res2.content[0]["text"]
    
    @registry.register(name="return_normal_dict", description="通常dict返却", input_schema={})
    async def ret_normal_dict(args):
        return {"foo": "bar"}
        
    res3 = await registry.execute("return_normal_dict", {})
    assert not res3.is_error
    assert "foo" in res3.content[0]["text"]
    
    @registry.register(name="return_json_str", description="JSON文字列返却", input_schema={})
    async def ret_json_str(args):
        return '{"status": "error", "reason": "json error"}'
        
    res4 = await registry.execute("return_json_str", {})
    assert res4.is_error
    assert "json error" in res4.content[0]["text"]
    
    @registry.register(name="return_plain_str", description="通常文字列返却", input_schema={})
    async def ret_plain_str(args):
        return "plain text"
        
    res5 = await registry.execute("return_plain_str", {})
    assert not res5.is_error
    assert res5.content[0]["text"] == "plain text"
    
    @registry.register(name="return_other_type", description="その他型返称", input_schema={})
    async def ret_other_type(args):
        return 12345
        
    res6 = await registry.execute("return_other_type", {})
    assert not res6.is_error
    assert res6.content[0]["text"] == "12345"

    # 8. _python_type_to_json_schema の追加カバレッジ
    assert _python_type_to_json_schema({"type": int}) == "integer"
    assert _python_type_to_json_schema({"type": str}) == "string"
    assert _python_type_to_json_schema(list) == "array"
    assert _python_type_to_json_schema(dict) == "object"


if __name__ == "__main__":
    success = asyncio.run(test_harness())
    sys.exit(0 if success else 1)
