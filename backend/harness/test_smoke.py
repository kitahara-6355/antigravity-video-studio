"""Harness Startup Smoke Test — サーバー起動時の初期化検証"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    print("=== Harness Startup Smoke Test ===\n")

    # 1. Import
    print("1. Importing harness modules...")
    from harness import (
        tool_registry, hook_system, session_manager, governance_engine,
        register_pipeline_tools, get_evaluator_optimizer,
    )
    print("   OK: All imports")

    # 2. Builtin hooks
    print("2. Registering builtin hooks...")
    hook_system.register_builtin_hooks()
    hs = hook_system.get_stats()
    rh = hs["registered_hooks"]
    print(f"   OK: Hooks registered: {rh}")

    # 3. Pipeline tools
    print("3. Registering pipeline tools...")
    register_pipeline_tools()
    tools = tool_registry.list_tools()
    print(f"   OK: {len(tools)} tools registered")
    for t in tools:
        name = t["name"].split("__")[-1]
        print(f"      - {name}")

    # 4. Evaluator-Optimizer
    print("4. Initializing Evaluator-Optimizer...")
    eo = get_evaluator_optimizer()
    print(f"   OK: {type(eo).__name__} (max_iter={eo.MAX_ITERATIONS})")

    # 5. Governance scopes
    print("5. Governance scopes...")
    stats = governance_engine.get_stats()
    for agent_id, info in stats["scopes"].items():
        tools_list = info["allowed_tools"]
        print(f"   {agent_id}: {info['name']} -> {tools_list}")

    # 6. Session manager
    print("6. Session manager...")
    sm = session_manager.get_stats()
    print(f"   OK: {sm}")

    # 7. PipelineCoordinator
    print("7. Verifying PipelineCoordinator integration...")
    from agents.pipeline_coordinator import pipeline_coordinator
    assert hasattr(pipeline_coordinator, "execute_with_harness")
    print("   OK: execute_with_harness() available")

    # 8. HARNESS_MODE
    print("8. HARNESS_MODE check...")
    mode = os.environ.get("HARNESS_MODE", "enabled")
    print(f"   OK: HARNESS_MODE={mode}")

    print("\n" + "=" * 50)
    print("ALL CHECKS PASSED — Ready for production")
    print("=" * 50)

if __name__ == "__main__":
    main()
