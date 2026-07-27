import shutil
import os

dst_dir = r"c:\Users\PC_User\Desktop\script\video-automation"

# 001
src_001 = r"C:\Users\PC_User\.gemini\antigravity\brain\1fe5c38d-969d-4748-a05a-e6165883543c\.system_generated\worktrees\subagent-bug-hunter-T-batch-fb00a7-bug-hunter-001-self-4fe268fa"
files_001 = [
    r"backend/agents/director.py",
    r"tests/test_director_boundary.py"
]

# 002
src_002 = r"C:\Users\PC_User\.gemini\antigravity\brain\1fe5c38d-969d-4748-a05a-e6165883543c\.system_generated\worktrees\subagent-bug-hunter-T-batch-fb00a7-bug-hunter-002-self-bb3f1e42"
files_002 = [
    r"backend/tests/_e2e_cycle3.py",
    r"backend/tests/test_e2e_cycle3.py"
]

def merge_files(src, files):
    for f in files:
        src_path = os.path.join(src, f)
        dst_path = os.path.join(dst_dir, f)
        
        # 稀にファイル名の大文字小文字やパスの違いがあるためチェック
        if not os.path.exists(src_path):
            # もし tests/ 側に直接ある場合はそれも探す
            alt_f = f.replace("backend/", "")
            src_alt = os.path.join(src, alt_f)
            if os.path.exists(src_alt):
                src_path = src_alt
                dst_path = os.path.join(dst_dir, alt_f)
                
        print(f"Copying {src_path} -> {dst_path}")
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        shutil.copy2(src_path, dst_path)

print("Merging 001...")
merge_files(src_001, files_001)

print("Merging 002...")
merge_files(src_002, files_002)

print("Merge copy completed.")
