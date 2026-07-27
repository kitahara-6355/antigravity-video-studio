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
    
    # ワークツリーとコピー対象ファイルのマップ (batch_d899d9)
    copy_map = {
        "subagent-bug-hunter-Agent-000-self-5c637956": [
            "backend/routers/pipeline_default_states.py",
            "backend/tests/test_shared/test_cov_pipeline_default_states.py"
        ],
        "subagent-bug-hunter-Agent-001-self-424405dc": [
            "backend/agents/orchestration/mark_tasks_p27_multi13.py",
            "backend/tests/test_mark_tasks_p27_multi13.py"
        ],
        "subagent-bug-hunter-Agent-002-self-f318e102": [
            "backend/quality_gate_plugins.py",
            "backend/agents/workers/quality_gate_worker.py",
            "backend/tests/test_workers/test_quality_gate_worker.py"
        ],
        "subagent-bug-hunter-Agent-003-self-ae44ecbe": [
            "backend/tests/test_tdr_resolver.py"
        ],
        "subagent-bug-hunter-Agent-004-self-ccc8d337": [
            "backend/utils/json_safe_io.py",
            "backend/tests/test_json_safe_io.py"
        ],
        "subagent-bug-hunter-Agent-005-self-82df26c3": [
            "backend/dispatch_enhancer.py",
            "backend/tests/test_shared/test_batch7_zero_pct.py"
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
