import subprocess
from pathlib import Path

def inspect_agent(wt_path):
    wt_path = Path(wt_path)
    if not wt_path.exists():
        return f"Not found: {wt_path}"
    
    out = []
    # status
    res = subprocess.run(["git", "status", "--porcelain"], cwd=wt_path, capture_output=True, text=True)
    out.append("Status:")
    out.append(res.stdout.strip() or "(None)")
    
    # recent 2 commits
    res = subprocess.run(["git", "log", "-n", "2", "--oneline"], cwd=wt_path, capture_output=True, text=True)
    out.append("Log:")
    out.append(res.stdout.strip() or "(None)")
    
    return "\n".join(out)

def main():
    wt_base = Path(r"C:\Users\PC_User\.gemini\antigravity\brain\ddc38d7b-e9dc-4aaf-b3d4-0642d02ef4b1\.system_generated\worktrees")
    agents = {
        "Agent-001": "subagent-bug-hunter-Agent-001-self-ac71a7cc",
        "Agent-003": "subagent-bug-hunter-Agent-003-self-7c327dcc",
    }
    
    for name, path in agents.items():
        print(f"\n================ {name} ({path}) ================")
        print(inspect_agent(wt_base / path))

if __name__ == "__main__":
    main()
