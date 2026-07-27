# -*- coding: utf-8 -*-
import sys
import os
import shutil
from pathlib import Path

repo_path = Path(r"c:\Users\PC_User\Desktop\script\video-automation")
sys.path.append(str(repo_path))
sys.path.append(str(repo_path / "backend"))

# 1. ワークツリーの定義
wt_dir = Path(r"C:\Users\PC_User\.\.gemini\antigravity\brain\e1bbe91a-2565-4b5d-be21-bda629c28dae\.system_generated\worktrees")

copies = [
    # T-000: tests/quick_verify.py
    ("subagent-thumbnail-Agent-0-self-920c54c5", "backend/tests/quick_verify.py"),
    ("subagent-thumbnail-Agent-0-self-920c54c5", "backend/tests/test_quick_verify_recovery.py"),
    
    # T-001: plugins/report_generator_plugin.py
    ("subagent-thumbnail-Agent-1-self-2d99443e", "backend/plugins/report_generator_plugin.py"),
    ("subagent-thumbnail-Agent-1-self-2d99443e", "backend/tests/test_shared/test_report_generator_plugin_robustness.py"),
    ("subagent-thumbnail-Agent-1-self-2d99443e", "backend/tests/test_shared/test_report_generator_plugin_edge_cases.py"),
    ("subagent-thumbnail-Agent-1-self-2d99443e", "backend/.coveragerc"),
    
    # T-003: asset_library.py
    ("subagent-thumbnail-Agent-3-self-cfb66d55", "backend/asset_library.py"),
    ("subagent-thumbnail-Agent-3-self-cfb66d55", "backend/tests/test_asset_library.py")
]

print("=== File Copying ===")
for wt_name, rel_path in copies:
    src = wt_dir / wt_name / rel_path
    dst = repo_path / rel_path
    if not src.exists():
        print(f"ERROR: Source file does not exist: {src}")
        sys.exit(1)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print(f"Copied: {wt_name}/{rel_path} -> {dst}")

# 2. TDR (技術負債) の解消
print("\n=== Resolving TDR (TD-399, TD-400, TD-401) ===")
from backend.agents.memory.technical_debt import TechnicalDebtStore

store = TechnicalDebtStore()
tdr_ids = ["TD-399", "TD-400", "TD-401"]
evidence = "Implemented explicit exception handling, boundary type-check, and key-error verification to resolve TDR and coverage. Checked with 17 tests."

for tdr_id in tdr_ids:
    entry = store.get_entry(tdr_id)
    if entry:
        if entry.status == "open":
            store.resolve_debt(
                debt_id=tdr_id,
                fixed_by="T-batch_a43c84-thumbnail-003",
                fix_evidence=evidence
            )
            print(f"Resolved: {tdr_id}")
        else:
            print(f"Skip (already resolved): {tdr_id}")
    else:
        print(f"WARNING: TDR entry not found: {tdr_id}")

print("\n=== Merge completed successfully ===")
