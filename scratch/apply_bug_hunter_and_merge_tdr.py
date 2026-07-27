import shutil
import os
import json
import subprocess

def main():
    wt_bug = r"C:\Users\PC_User\.gemini\antigravity\brain\d040406a-753e-4388-b488-b525cd358e85\.system_generated\worktrees\subagent-bug-hunter-Agent-self-1ac11ea0"
    project_dir = r"c:\Users\PC_User\Desktop\script\video-automation"

    # 1. Merge technical_debt_index.json (TD-830 status -> fixed)
    src_json_path = os.path.join(wt_bug, "backend/agents/memory/technical_debt_index.json")
    dst_json_path = os.path.join(project_dir, "backend/agents/memory/technical_debt_index.json")

    if os.path.exists(src_json_path) and os.path.exists(dst_json_path):
        with open(src_json_path, "r", encoding="utf-8") as f:
            src_data = json.load(f)
        with open(dst_json_path, "r", encoding="utf-8") as f:
            dst_data = json.load(f)

        # Find TD-830 in src_data (using entries and debt_id)
        td_830_src = None
        for debt in src_data.get("entries", []):
            if debt.get("debt_id") == "TD-830":
                td_830_src = debt
                break

        if td_830_src:
            # Update TD-830 in dst_data
            updated = False
            for debt in dst_data.get("entries", []):
                if debt.get("debt_id") == "TD-830":
                    debt["status"] = td_830_src.get("status")
                    debt["fixed_by"] = td_830_src.get("fixed_by")
                    debt["fix_evidence"] = td_830_src.get("fix_evidence")
                    debt["fixed_at"] = td_830_src.get("fixed_at")
                    updated = True
                    print("Updated TD-830 to fixed in parent technical_debt_index.json")
                    break
            
            if not updated:
                dst_data.setdefault("entries", []).append(td_830_src)
                print("Appended TD-830 to parent technical_debt_index.json")

            with open(dst_json_path, "w", encoding="utf-8") as f:
                json.dump(dst_data, f, indent=2, ensure_ascii=False)
        else:
            print("TD-830 not found in subagent's technical_debt_index.json")
    else:
        print("TDR JSON files not found for merging.")

    # 2. Regenerate TECHNICAL_DEBT_REGISTRY.md
    print("Regenerating TECHNICAL_DEBT_REGISTRY.md...")
    try:
        script_path = os.path.join(project_dir, "backend", "agents", "memory", "technical_debt.py")
        subprocess.run(["python", script_path], check=True, cwd=project_dir)
        print("TECHNICAL_DEBT_REGISTRY.md regenerated successfully.")
    except Exception as e:
        print(f"Failed to regenerate technical debt registry: {e}")

if __name__ == "__main__":
    main()
