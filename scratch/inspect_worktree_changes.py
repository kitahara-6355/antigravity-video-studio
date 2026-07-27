import subprocess
from pathlib import Path

def get_git_changes(wt_path):
    wt_path = Path(wt_path)
    if not wt_path.exists():
        return f"Directory not found: {wt_path}"
    
    output = []
    try:
        # Run git status --porcelain
        res_status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=wt_path,
            capture_output=True,
            text=True,
            check=True
        )
        status_out = res_status.stdout.strip()
        if status_out:
            output.append("--- Uncommitted changes ---")
            output.append(status_out)
            
        # Get latest commit hash and subject
        res_log = subprocess.run(
            ["git", "log", "-n", "1", "--oneline"],
            cwd=wt_path,
            capture_output=True,
            text=True,
            check=True
        )
        log_out = res_log.stdout.strip()
        if log_out:
            output.append(f"--- Latest commit: {log_out} ---")
            
        # Get files changed in the latest commit
        res_diff = subprocess.run(
            ["git", "diff", "HEAD~1", "--name-only"],
            cwd=wt_path,
            capture_output=True,
            text=True,
            check=True
        )
        diff_out = res_diff.stdout.strip()
        if diff_out:
            output.append("--- Files modified in latest commit ---")
            output.append(diff_out)
            
        return "\n".join(output)
    except Exception as e:
        return f"Error running git: {e}"

def main():
    wt_base = Path(r"C:\Users\PC_User\.gemini\antigravity\brain\ddc38d7b-e9dc-4aaf-b3d4-0642d02ef4b1\.system_generated\worktrees")
    agents = [
        "subagent-bug-hunter-Agent-000-self-702035ef",
        "subagent-bug-hunter-Agent-001-self-ac71a7cc",
        "subagent-bug-hunter-Agent-002-self-caa96693",
        "subagent-bug-hunter-Agent-003-self-7c327dcc",
        "subagent-bug-hunter-Agent-004-self-eb0999fe",
        "subagent-bug-hunter-Agent-005-self-05bf4556"
    ]
    
    for wt_name in agents:
        wt_path = wt_base / wt_name
        print(f"\n=== Worktree: {wt_name} ===")
        changes = get_git_changes(wt_path)
        if changes:
            print(changes)
        else:
            print("No changes or error.")

if __name__ == "__main__":
    main()
