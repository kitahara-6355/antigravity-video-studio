import shutil
import os
import subprocess
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

def run_cmd(cmd, cwd=None):
    print(f"Running: {cmd}")
    res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd)
    print(res.stdout)
    if res.returncode != 0:
        print(f"Error (code {res.returncode}):\n{res.stderr}")
    return res.returncode == 0

def main():
    session_id = "c62ea2d3-95c1-4525-8ffe-1a1776e680c2"
    base_wt = Path(rf"C:\Users\PC_User\.gemini\antigravity\brain\{session_id}\.system_generated\worktrees")
    main_dir = Path(r"c:\Users\PC_User\Desktop\script\video-automation")
    
    # マップ定義: (wt_folder, src_rel, dst_rel)
    copy_map = [
        # test_weaver-000 (agents/orchestration/mark_and_submit_batch4.py)
        ("subagent-test-weaver-Agent-000-self-e5e08df5", "tests/test_mark_and_submit_batch4.py", "backend/tests/test_mark_and_submit_batch4.py"),
        
        # thumbnail-000 (subtitle_preview.py)
        ("subagent-thumbnail-Agent-000-self-ae7cc76f", "backend/subtitle_preview.py", "backend/subtitle_preview.py"),
        ("subagent-thumbnail-Agent-000-self-ae7cc76f", "backend/tests/test_subtitle_preview.py", "backend/tests/test_subtitle_preview.py"),
        
        # thumbnail-001 (comprehensive_preview.py)
        ("subagent-thumbnail-Agent-001-self-5100b6a6", "backend/comprehensive_preview.py", "backend/comprehensive_preview.py"),
        ("subagent-thumbnail-Agent-001-self-5100b6a6", "backend/tests/test_comprehensive_preview.py", "backend/tests/test_comprehensive_preview.py"),
        
        # bug_hunter-000 (plugins/retention_map_plugin.py)
        ("subagent-bug-hunter-Agent-000-self-923470f8", "backend/plugins/retention_map_plugin.py", "backend/plugins/retention_map_plugin.py"),
        ("subagent-bug-hunter-Agent-000-self-923470f8", "backend/tests/test_quality_audit_fixes.py", "backend/tests/test_quality_audit_fixes.py"),
        
        # refactor-000 (routers/admin_analytics_router.py)
        ("subagent-refactor-Agent-000-self-aa8c7605", "backend/routers/admin_analytics_router.py", "backend/routers/admin_analytics_router.py"),
        ("subagent-refactor-Agent-000-self-aa8c7605", "backend/tests/test_admin_analytics_router.py", "backend/tests/test_admin_analytics_router.py"),
        
        # test_weaver-001 (scratch/get_status.py)
        ("subagent-test-weaver-Agent-001-self-9b73ae20", "backend/tests/test_scratch_get_status.py", "backend/tests/test_scratch_get_status.py"),
    ]
    
    print("=== Copying files from worktrees ===")
    success_count = 0
    for wt_folder, src_rel, dst_rel in copy_map:
        src_path = base_wt / wt_folder / src_rel
        if not src_path.exists():
            # ワークツリー内で backend/ を含む/含まないの違いを吸収
            if src_rel.startswith("backend/"):
                src_path = base_wt / wt_folder / src_rel[8:]
            else:
                src_path = base_wt / wt_folder / f"backend/{src_rel}"
        
        dst_path = main_dir / dst_rel
        if copy_file(src_path, dst_path):
            success_count += 1
            
    print(f"\nCompleted copying {success_count} files.")
    
    print("\n=== Running tests validation ===")
    test_files = [
        "backend/tests/test_mark_and_submit_batch4.py",
        "backend/tests/test_subtitle_preview.py",
        "backend/tests/test_comprehensive_preview.py",
        "backend/tests/test_admin_analytics_router.py",
        "backend/tests/test_scratch_get_status.py",
        "backend/tests/test_quality_audit_fixes.py",
    ]
    
    all_pass = True
    for tf in test_files:
        if os.path.exists(main_dir / tf):
            ok = run_cmd(f"pytest {tf} --timeout=300", cwd=main_dir)
            if not ok:
                all_pass = False
                print(f"TEST FAILED: {tf}")
        else:
            print(f"Test file not found: {tf}")
            
    if all_pass:
        print("\nAll batch validation tests PASSED!")
    else:
        print("\nSome tests FAILED.")

if __name__ == "__main__":
    main()
