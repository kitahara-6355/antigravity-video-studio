import shutil
from pathlib import Path

def copy_file(src, dst):
    src = Path(src)
    dst = Path(dst)
    if not src.exists():
        print(f"Source not found: {src}")
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print(f"Copied: {src.name} -> {dst}")
    return True

def main():
    base_wt = Path(r"C:\Users\PC_User\.gemini\antigravity\brain\316e6dfa-76e7-4c82-8418-c658b676d7df\.system_generated\worktrees")
    main_dir = Path(r"c:\Users\PC_User\Desktop\script\video-automation")
    
    # コピーマップ定義: (wt_name, relative_path)
    copy_map = [
        # Bug-Hunter-Agent-1
        ("subagent-Bug-Hunter-Agent-1-self-b528c457", "backend/branding/user_model.json"),
        ("subagent-Bug-Hunter-Agent-1-self-b528c457", "backend/tests/test_shared/test_core_plugin.py"),
        
        # Bug-Hunter-Agent-2 (念のため再コピー)
        ("subagent-Bug-Hunter-Agent-2-self-b20827c9", "backend/branding/constitution.json"),
        ("subagent-Bug-Hunter-Agent-2-self-b20827c9", "backend/branding/design_tokens_history.json"),
        ("subagent-Bug-Hunter-Agent-2-self-b20827c9", "backend/branding/evolution_log.json"),
        ("subagent-Bug-Hunter-Agent-2-self-b20827c9", "backend/tests/test_shared/test_routers_batch2.py"),
        
        # TDR-Cleanup-Agent
        ("subagent-TDR-Cleanup-Agent-self-3f0718e9", "backend/TECHNICAL_DEBT_REGISTRY.md"),
        ("subagent-TDR-Cleanup-Agent-self-3f0718e9", "backend/agents/memory/technical_debt_index.json"),
        ("subagent-TDR-Cleanup-Agent-self-3f0718e9", "backend/agents/workers/transcribe_worker.py"),
        
        # Test-Weaver-Agent-1
        ("subagent-Test-Weaver-Agent-1-self-472d97af", "backend/tests/test_shared/test_cov_smartcut_trinity.py"),
        
        # Test-Weaver-Agent-2
        ("subagent-Test-Weaver-Agent-2-self-8fc901e4", "backend/tests/test_e2e_cycle2_unit.py"),
    ]
    
    success_count = 0
    for wt_name, rel_path in copy_map:
        src_path = base_wt / wt_name / rel_path
        dst_path = main_dir / rel_path
        if copy_file(src_path, dst_path):
            success_count += 1
            
    print(f"\nCompleted copying {success_count} files.")

if __name__ == "__main__":
    main()
