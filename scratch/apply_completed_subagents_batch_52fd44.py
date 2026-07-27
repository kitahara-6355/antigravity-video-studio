import os
import shutil
from pathlib import Path

def merge_file(src: Path, dest: Path):
    if not src.exists():
        print(f"Warning: Source {src} does not exist. Skipping.")
        return
    
    # 宛先ディレクトリが存在しない場合は作成
    dest.parent.mkdir(parents=True, exist_ok=True)
    
    # 単純上書きコピー（競合しないことが前提）
    # もし同一のファイルを編集している場合は警告を出して3-wayマージ等を検討
    if dest.exists():
        print(f"Overwriting {dest} with {src}")
    else:
        print(f"Copying {src} -> {dest}")
        
    shutil.copy2(src, dest)

def main():
    workspace_root = Path("c:/Users/PC_User/Desktop/script/video-automation")
    subagents_base = Path("C:/Users/PC_User/.gemini/antigravity/brain/ddc38d7b-e9dc-4aaf-b3d4-0642d02ef4b1/.system_generated/worktrees")
    
    # Agent フォルダ名
    worktrees = {
        "Agent 000": "subagent-bug-hunter-Agent-000-self-8ea3dec4",
        "Agent 001": "subagent-bug-hunter-Agent-001-self-64c452ba",
        "Agent 002": "subagent-bug-hunter-Agent-002-self-39a06bc0",
        "Agent 003": "subagent-bug-hunter-Agent-003-self-4e244ec4",
        "Agent 004": "subagent-bug-hunter-Agent-004-self-e76a08b5",
        "Agent 005": "subagent-bug-hunter-Agent-005-self-1f20dde6"
    }
    
    # コピー対象ファイル一覧
    files_to_merge = {
        "Agent 000": [
            "backend/error_reporter.py",
            "backend/agents/orchestration/flash_assign_subagents_8.py",
            "backend/tests/test_flash_assign_subagents_8.py"
        ],
        "Agent 001": [
            "backend/tests/test_learning_integration.py",
            "backend/tests/test_flash_assign_subagents_8.py"
        ],
        "Agent 002": [
            "backend/scratch/get_next_batch.py",
            "backend/tests/test_get_next_batch.py"
        ],
        "Agent 003": [
            "backend/agents/director.py",
            "backend/agents/agent_base.py",
            "tests/test_director.py"
        ],
        "Agent 004": [
            "backend/agents/orchestration/flash_assign_subagents_8.py",
            "backend/plugins/report_generator_plugin.py",
            "backend/tests/test_shared/test_report_generator_plugin_edge_cases.py"
        ],
        "Agent 005": [
            "backend/tests/test_shared/test_service_and_errors.py"
        ]
    }
    
    # 重複して変更されているファイルをチェック
    # flash_assign_subagents_8.py, test_flash_assign_subagents_8.py は Agent 000, 001, 004 などで競合しています！
    # 競合が発生するため、git diff などを確認するか、あるいは手動で正しくマージする必要があります。
    
    # 競合リスト:
    # 1. backend/agents/orchestration/flash_assign_subagents_8.py (Agent 000 と Agent 004 で編集)
    # 2. backend/tests/test_flash_assign_subagents_8.py (Agent 000 と Agent 001 と Agent 004 で編集)
    
    # 競合ファイルは単純上書きすると変更が消えてしまうため、
    # ワークツリー同士で競合をマージする必要があります。
    # ここでは、まず競合しないファイルをマージし、
    # 競合ファイルについては一旦コピーをスキップして、後で個別に処理します。

    print("=== Merging Non-Conflicting Files ===")
    for agent_name, files in files_to_merge.items():
        wt_dir = subagents_base / worktrees[agent_name]
        for f in files:
            # 競合ファイルを一旦スキップ
            if f in [
                "backend/agents/orchestration/flash_assign_subagents_8.py",
                "backend/tests/test_flash_assign_subagents_8.py"
            ]:
                print(f"Skipping potentially conflicting file: {f} from {agent_name}")
                continue
                
            src_file = wt_dir / f
            dest_file = workspace_root / f
            merge_file(src_file, dest_file)

if __name__ == "__main__":
    main()
