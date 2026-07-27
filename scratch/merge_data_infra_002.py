import shutil
import os

worktree_path = r"C:\Users\PC_User\.gemini\antigravity\brain\0e95a029-d93d-49ca-9da7-a1a8aaf448fd\.system_generated\worktrees\subagent-data-infra-Agent-self-0e2f4044"
repo_path = r"c:\Users\PC_User\Desktop\script\video-automation"

# 1. ソースコードとテストコード、メモリ、TDRのコピー
files_to_copy = [
    r"backend/routers/pipeline_router.py",
    r"backend/tests/test_shared/test_cov_pipeline_router.py",
    r"backend/TECHNICAL_DEBT_REGISTRY.md",
    r"backend/agents/memory/technical_debt_index.json",
    r"backend/agents/memory/verified_facts_index.json",
    r"backend/agents/memory/VERIFIED_FACTS.md",
    r"backend/technical_debt_snapshots/tdr_v8.1.json"
]

for rel_path in files_to_copy:
    src = os.path.join(worktree_path, rel_path.replace("/", os.sep))
    dst = os.path.join(repo_path, rel_path.replace("/", os.sep))
    
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    print(f"Copied {src} -> {dst}")

# 2. Human01_Official Artifact の同期
# メインリポジトリの "Human01_Official Artifact" フォルダを一旦退避させず、
# 作業ツリー側の内容で完全に同期（受信トレイから移動されたファイルを削除し、未転記以下にコピー）
# 安全のため、メインリポジトリの受信トレイから作業ツリー側で削除されたファイルを削除する。
# また、未転記フォルダを作業ツリーからメインに丸ごとコピーする。

src_artifact_dir = os.path.join(worktree_path, "Human01_Official Artifact")
dst_artifact_dir = os.path.join(repo_path, "Human01_Official Artifact")

# 削除されたファイルをメインからも削除する
# git status で deleted になっていたファイルを特定して削除する
deleted_files = [
    "daily_digest_20260521.md",
    "error_20260521_1012_T-batch_d6d052-test_weaver-004.md",
    "error_20260521_1012_T-batch_d6d052-test_weaver-006.md",
    "error_20260521_1543_T1.md",
    "error_20260521_1543_T2.md",
    "error_20260521_1543_T3.md",
    "error_20260521_2229_T-batch_27b234-ci_cd-002.md",
    "hourly_report_20260521_0337.md",
    "hourly_report_20260521_0401.md",
    "hourly_report_20260521_0500.md",
    "hourly_report_20260521_0600.md",
    "hourly_report_20260521_0700.md",
    "hourly_report_20260521_0800.md",
    "hourly_report_20260521_0822.md",
    "hourly_report_20260521_0900.md",
    "hourly_report_20260521_0923.md",
    "hourly_report_20260521_0924.md",
    "hourly_report_20260521_0932.md",
    "hourly_report_20260521_0938.md",
    "hourly_report_20260521_0941.md",
    "hourly_report_20260521_0949.md",
    "hourly_report_20260521_0954.md",
    "hourly_report_20260521_0956.md",
    "hourly_report_20260521_0959.md",
    "hourly_report_20260521_1001.md",
    "hourly_report_20260521_1007.md",
    "hourly_report_20260521_1011.md",
    "hourly_report_20260521_1100.md",
    "hourly_report_20260521_1152.md",
    "hourly_report_20260521_1156.md",
    "hourly_report_20260521_1200.md",
    "hourly_report_20260521_1433.md",
    "hourly_report_20260521_1438.md",
    "hourly_report_20260522_0200.md",
    "hourly_report_20260522_0300.md",
    "hourly_report_20260522_0500.md",
    "phase_5_completion_20260521.md",
    "phase_6_completion_20260521.md",
    "phase_7_completion_20260521.md",
    "session_report_sprint51_initialization.md"
]

inbox_dir = os.path.join(dst_artifact_dir, "受信トレイ")
for filename in deleted_files:
    filepath = os.path.join(inbox_dir, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
        print(f"Removed from repo: {filepath}")

# 未転記フォルダを丸ごとコピーする
src_untranscribed = os.path.join(src_artifact_dir, "未転記")
dst_untranscribed = os.path.join(dst_artifact_dir, "未転記")

if os.path.exists(dst_untranscribed):
    shutil.rmtree(dst_untranscribed)

shutil.copytree(src_untranscribed, dst_untranscribed)
print(f"Synced '未転記' folder: {src_untranscribed} -> {dst_untranscribed}")

print("Merge completed successfully.")
