import shutil
import os
from pathlib import Path

def copy_file(src, dst):
    src = Path(src)
    dst = Path(dst)
    if not src.exists():
        print(f"Warning: Source not found: {src}")
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print(f"Copied: {src.name} -> {dst}")
    return True

def main():
    dest_root = Path(r"c:\Users\PC_User\Desktop\script\video-automation")
    wt_base = Path(r"C:\Users\PC_User\.gemini\antigravity\brain\ddc38d7b-e9dc-4aaf-b3d4-0642d02ef4b1\.system_generated\worktrees")
    
    # ワークツリーとコピー対象ファイルのマップ (batch_06b8f5)
    copy_map = {
        "subagent-bug-hunter-Agent-000-self-f08e9354": [
            "backend/agents/orchestration/wave_scheduler.py",
            "backend/tests/test_wave_scheduler.py",
            "backend/agents/orchestration/compliance_guard.py"
        ],
        "subagent-bug-hunter-Agent-001-self-bad9b587": [
            "backend/verify_council_v2.py",
            "backend/tests/test_verify_council_v2.py"
        ],
        "subagent-bug-hunter-Agent-002-self-f7508b95": [
            "backend/agents/orchestration/flash_assign_subagents_8.py",
            "tests/test_flash_assign_subagents_8.py"
        ],
        "subagent-bug-hunter-Agent-003-self-4db346f7": [
            "backend/agents/orchestration/run_session_end.py",
            "tests/test_run_session_end.py",
            "tests/test_health_check.py"
        ],
        "subagent-bug-hunter-Agent-004-self-0c85f2e2": [
            "backend/tests/_e2e_cycle3.py",
            "backend/tests/test_e2e_cycle3.py"
        ],
        "subagent-bug-hunter-Agent-005-self-d6dbd6bf": [
            "tests/test_council_graph.py",
            "backend/tests/test_shared/test_council_graph_extra.py"
        ]
    }
    
    success_count = 0
    for wt_name, files in copy_map.items():
        wt_path = wt_base / wt_name
        print(f"\n--- Merging from: {wt_name} ---")
        if not wt_path.exists():
            print(f"Error: Worktree path not found {wt_path}")
            continue
            
        for rel_path in files:
            src_file = wt_path / rel_path
            dst_file = dest_root / rel_path
            
            # Fallback check (if path structure differs)
            if not src_file.exists():
                fallback_rel = rel_path.replace("backend/", "")
                src_file_fb = wt_path / fallback_rel
                if src_file_fb.exists():
                    rel_path = fallback_rel
                    src_file = src_file_fb
            
            if copy_file(src_file, dest_root / rel_path):
                success_count += 1
                
    print(f"\nCompleted copying {success_count} files.")

if __name__ == "__main__":
    main()
