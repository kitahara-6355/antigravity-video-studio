"""
Final Integration Test — Phase 1+2+3 全テスト一括実行
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def run_all():
    print("=" * 60)
    print("FINAL INTEGRATION TEST — All Phases")
    print("=" * 60)

    results = {}

    # Phase 1
    print("\n>>> Phase 1: Harness Foundation <<<")
    from harness.test_harness import test_harness
    results["Phase 1"] = await test_harness()

    # Phase 2
    print("\n>>> Phase 2: Agent Integration <<<")
    from harness.test_phase2 import test_phase2
    results["Phase 2"] = await test_phase2()

    # Phase 3
    print("\n>>> Phase 3: ADK Bridge <<<")
    from harness.test_phase3 import test_phase3
    results["Phase 3"] = await test_phase3()

    # Summary
    print("\n" + "=" * 60)
    print("FINAL SUMMARY")
    print("=" * 60)
    all_pass = True
    for phase, ok in results.items():
        status = "PASS" if ok else "FAIL"
        icon = "✅" if ok else "❌"
        print(f"  {icon} {phase}: {status}")
        if not ok:
            all_pass = False

    print()
    if all_pass:
        print("✅ ALL PHASES PASSED — Production Ready")
    else:
        print("❌ SOME PHASES FAILED")
    print("=" * 60)
    return all_pass


if __name__ == "__main__":
    success = asyncio.run(run_all())
    sys.exit(0 if success else 1)
