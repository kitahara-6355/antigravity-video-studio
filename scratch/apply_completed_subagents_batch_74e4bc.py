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
    
    # マップ定義: (ワークツリー名, コピーする相対パスのリスト)
    copy_map = {
        "subagent-bug-hunter-Agent-000-self-cf98bc71": [
            "backend/agents/orchestration/wave_scheduler.py",
            "backend/tests/test_wave_scheduler.py"
        ],
        "subagent-bug-hunter-Agent-001-self-300ba289": [
            "backend/agents/orchestration/flash_assign_subagents_8.py",
            "backend/tests/test_flash_assign_subagents_8.py"
        ],
        "subagent-bug-hunter-Agent-003-self-9e45882a": [
            "backend/agents/orchestration/run_session_end.py",
            "backend/tests/test_run_session_end.py"
        ],
        "subagent-bug-hunter-Agent-004-self-00bcc407": [
            "backend/tests/_e2e_cycle3.py",
            "backend/tests/test_e2e_cycle3.py"
        ],
        "subagent-bug-hunter-Agent-005-self-a4538148": [
            "backend/agents/council_graph.py",
            "backend/tests/test_council_graph.py"
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
            # もし `backend/tests/` ではなく `tests/` に置かれている場合も考慮して、ワークツリー内に存在しない場合はフォールバック
            if not src_file.exists():
                # 例: backend/tests/test_run_session_end.py -> tests/test_run_session_end.py
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
