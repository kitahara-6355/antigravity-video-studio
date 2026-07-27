import sys
import os
import shutil
import subprocess

PROJECT_ROOT = r"C:\Users\PC_User\Desktop\script\video-automation"
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    hub.flash_update_heartbeat()
    print("Heartbeat updated.")

    agents_config = [
        {
            "id": "T-batch_a576c2-bug_hunter-000",
            "wt": r"C:\Users\PC_User\.gemini\antigravity\brain\790758f1-d405-4a07-86c1-ef5fe4705438\.system_generated\worktrees\subagent-bug-hunter-Agent-T-batch-a576c2-bug-hunter-000-self-09066c2f",
            "files": [
                ("backend/agents/orchestration/mark_tasks_p27_multi14.py", "backend/agents/orchestration/mark_tasks_p27_multi14.py"),
                ("tests/test_mark_tasks_p27_multi14.py", "tests/test_mark_tasks_p27_multi14.py"),
                ("pytest.ini", "pytest.ini")
            ],
            "tests": ["tests/test_mark_tasks_p27_multi14.py"],
            "msg": "mark_tasks_p27_multi14.py のバグ修正と、対応するテスト tests/test_mark_tasks_p27_multi14.py を追加しました。"
        },
        {
            "id": "T-batch_a576c2-bug_hunter-001",
            "wt": r"C:\Users\PC_User\.gemini\antigravity\brain\790758f1-d405-4a07-86c1-ef5fe4705438\.system_generated\worktrees\subagent-bug-hunter-Agent-T-batch-a576c2-bug-hunter-001-self-c5898541",
            "files": [
                ("backend/agents/orchestration/generate_subagent_reports.py", "backend/agents/orchestration/generate_subagent_reports.py"),
                ("backend/tests/test_generate_subagent_reports.py", "backend/tests/test_generate_subagent_reports.py")
            ],
            "tests": ["backend/tests/test_generate_subagent_reports.py"],
            "msg": "generate_subagent_reports.py の sys.path 設定部分に WORKSPACE_DIR/backend を追加して、 ModuleNotFoundError: No module named 'agents.orchestration.task_dag' を解消し、テスト test_sys_path_contains_backend を追加しました。"
        },
        {
            "id": "T-batch_a576c2-bug_hunter-002",
            "wt": r"C:\Users\PC_User\.gemini\antigravity\brain\790758f1-d405-4a07-86c1-ef5fe4705438\.system_generated\worktrees\subagent-bug-hunter-Agent-T-batch-a576c2-bug-hunter-002-self-f5dc8869",
            "files": [
                ("backend/minimal_telop_generator.py", "backend/minimal_telop_generator.py"),
                ("backend/theme_telop.py", "backend/theme_telop.py"),
                ("backend/tests/test_minimal_telop_generator.py", "backend/tests/test_minimal_telop_generator.py")
            ],
            "tests": ["backend/tests/test_minimal_telop_generator.py"],
            "msg": "minimal_telop_generator.py の generate_minimal_telop にパラメータバリデーションと getbbox/getsize 互換処理を追加し、theme_telop.py のフォント取得例外キャッチを堅牢化しました。また、新規テスト test_minimal_telop_generator.py を追加し 100% PASS を確認しました。"
        },
        {
            "id": "T-batch_a576c2-bug_hunter-003",
            "wt": r"C:\Users\PC_User\.gemini\antigravity\brain\790758f1-d405-4a07-86c1-ef5fe4705438\.system_generated\worktrees\subagent-bug-hunter-Agent-T-batch-a576c2-bug-hunter-003-self-d5113e3d",
            "files": [
                ("backend/aligned_preview_generator.py", "backend/aligned_preview_generator.py"),
                ("backend/tests/test_aligned_preview_generator.py", "backend/tests/test_aligned_preview_generator.py")
            ],
            "tests": ["backend/tests/test_aligned_preview_generator.py"],
            "msg": "aligned_preview_generator.py の create_aligned_preview() において、引数 input_video および output_dir を指定可能にし、黒背景回避ロジックにおけるパス参照を一般化しました。あわせて単体テスト test_create_aligned_preview_custom_paths 等を追加しました。"
        },
        {
            "id": "T-batch_a576c2-bug_hunter-004",
            "wt": r"C:\Users\PC_User\.gemini\antigravity\brain\790758f1-d405-4a07-86c1-ef5fe4705438\.system_generated\worktrees\subagent-bug-hunter-Agent-T-batch-a576c2-bug-hunter-004-self-58a2b476",
            "files": [
                ("backend/usage_tracker/api_usage_tracker.py", "backend/usage_tracker/api_usage_tracker.py"),
                ("backend/tests/test_shared/test_api_usage_tracker.py", "backend/tests/test_shared/test_api_usage_tracker.py"),
                ("backend/tests/test_sdk_checker.py", "backend/tests/test_sdk_checker.py"),
                ("backend/agents/memory/technical_debt_index.json", "backend/agents/memory/technical_debt_index.json"),
                ("backend/TECHNICAL_DEBT_REGISTRY.md", "backend/TECHNICAL_DEBT_REGISTRY.md")
            ],
            "tests": ["backend/tests/test_shared/test_api_usage_tracker.py", "backend/tests/test_sdk_checker.py"],
            "msg": "api_usage_tracker.py の cleanup_old_data ガードレール補強と test_sdk_checker.py の worktree パス解決を修正し、TDR 台帳の TD-866 を解消済みにしました。"
        },
        {
            "id": "T-batch_a576c2-bug_hunter-005",
            "wt": r"C:\Users\PC_User\.gemini\antigravity\brain\790758f1-d405-4a07-86c1-ef5fe4705438\.system_generated\worktrees\subagent-bug-hunter-Agent-T-batch-a576c2-bug-hunter-005-self-f9b975d0",
            "files": [
                ("backend/archives/archive_stable_v3.0_20260118_0953/video_processor.py", "backend/archives/archive_stable_v3.0_20260118_0953/video_processor.py"),
                ("backend/tests/archives/test_archive_video_processor.py", "backend/tests/archives/test_archive_video_processor.py")
            ],
            "tests": ["backend/tests/archives/test_archive_video_processor.py"],
            "msg": "video_processor.py の MoodSettings に tempo フィールドを追加し、test_archive_video_processor.py の動的代入不具合隠蔽をクリーンアップして 100% PASS を確認しました。"
        },
        {
            "id": "T-batch_a576c2-bug_hunter-006",
            "wt": r"C:\Users\PC_User\.gemini\antigravity\brain\790758f1-d405-4a07-86c1-ef5fe4705438\.system_generated\worktrees\subagent-bug-hunter-Agent-T-batch-a576c2-bug-hunter-006-self-ef09ea29",
            "files": [
                ("backend/tests/test_shared/test_themes_router_coverage.py", "backend/tests/test_shared/test_themes_router_coverage.py"),
                ("backend/tests/test_shared/test_template_recommender.py", "backend/tests/test_shared/test_template_recommender.py")
            ],
            "tests": ["backend/tests/test_shared/test_themes_router_coverage.py", "backend/tests/test_shared/test_template_recommender.py"],
            "msg": "test_themes_router_coverage.py の evolution_log.json パス解決時の APIRouter 上書きによる AttributeError を解消し、test_template_recommender.py 内の重複テスト関数をクリーンアップしました。"
        },
        {
            "id": "T-batch_a576c2-bug_hunter-007",
            "wt": r"C:\Users\PC_User\.gemini\antigravity\brain\790758f1-d405-4a07-86c1-ef5fe4705438\.system_generated\worktrees\subagent-bug-hunter-Agent-T-batch-a576c2-bug-hunter-007-self-e688de2e",
            "files": [
                ("backend/verify_e2e_workflow.py", "backend/verify_e2e_workflow.py"),
                ("backend/tests/test_verify_e2e_workflow.py", "backend/tests/test_verify_e2e_workflow.py"),
                ("backend/tests/test_scratch_verify_e2e_workflow.py", "backend/tests/test_scratch_verify_e2e_workflow.py")
            ],
            "tests": ["backend/tests/test_verify_e2e_workflow.py", "backend/tests/test_scratch_verify_e2e_workflow.py"],
            "msg": "verify_e2e_workflow.py のロード時環境変数評価を動的評価に変更し、タイムアウト値の適正化、Windows以外のOS用パス切り出しの堅牢化を行い、テストを追加して 100% PASS を確認しました。"
        },
        {
            "id": "T-batch_a576c2-bug_hunter-008",
            "wt": r"C:\Users\PC_User\.gemini\antigravity\brain\790758f1-d405-4a07-86c1-ef5fe4705438\.system_generated\worktrees\subagent-bug-hunter-Agent-T-batch-a576c2-bug-hunter-008-self-071fb9b9",
            "files": [
                ("backend/subtitle_engine/whisper_subprocess.py", "backend/subtitle_engine/whisper_subprocess.py"),
                ("backend/tests/test_shared/test_subtitle_engines.py", "backend/tests/test_shared/test_subtitle_engines.py")
            ],
            "tests": ["backend/tests/test_shared/test_subtitle_engines.py"],
            "msg": "whisper_subprocess.py において、GPUロードスレッドとタイムアウトフォールバック間の競合バグを修正し、テスト test_main_gpu_load_timeout_thread_safety を追加して 100% PASS を確認しました。"
        },
        {
            "id": "T-batch_a576c2-bug_hunter-009",
            "wt": r"C:\Users\PC_User\.gemini\antigravity\brain\790758f1-d405-4a07-86c1-ef5fe4705438\.system_generated\worktrees\subagent-bug-hunter-Agent-T-batch-a576c2-bug-hunter-009-self-65bc8e5d",
            "files": [
                ("backend/routers/youtube_upload.py", "backend/routers/youtube_upload.py"),
                ("tests/test_youtube_upload.py", "tests/test_youtube_upload.py"),
                ("backend/tests/test_youtube_upload.py", "backend/tests/test_youtube_upload.py")
            ],
            "tests": ["tests/test_youtube_upload.py", "backend/tests/test_youtube_upload.py"],
            "msg": "tests/test_youtube_upload.py 実行時の sys.modules['backend.routers'] 差し替えによる他テストへのグローバルステート汚染を解消（退避・復元処理の実装）、および Pydantic ConfigDict 追加による DeprecationWarning を解消しました。"
        }
    ]

    for config in agents_config:
        task_id = config["id"]
        wt_path = config["wt"]
        print(f"\n=== Syncing {task_id} ===")
        
        # コピー実行
        for src_rel, dest_rel in config["files"]:
            src_path = os.path.join(wt_path, src_rel)
            if not os.path.exists(src_path):
                src_path = os.path.join(wt_path, src_rel.replace("backend/", ""))
                
            dest_path = os.path.join(PROJECT_ROOT, dest_rel)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            shutil.copy2(src_path, dest_path)
            print(f"Copied: {src_path} -> {dest_path}")

        # テスト実行
        all_passed = True
        env = os.environ.copy()
        python_path = f"{PROJECT_ROOT};{os.path.join(PROJECT_ROOT, 'backend')}"
        if "PYTHONPATH" in env:
            env["PYTHONPATH"] = f"{python_path};{env['PYTHONPATH']}"
        else:
            env["PYTHONPATH"] = python_path

        for test_file in config["tests"]:
            print(f"Running pytest for {test_file}...")
            res = subprocess.run(["pytest", test_file, "--timeout=300"], capture_output=True, text=True, env=env)
            if res.returncode == 0:
                print(f"Test {test_file} passed.")
            else:
                print(f"Test {test_file} failed. Output:")
                print(res.stdout)
                print(res.stderr)
                all_passed = False
                break

        if all_passed:
            report = {
                "message": config["msg"],
                "changed_files": [os.path.join(PROJECT_ROOT, f[1]) for f in config["files"]]
            }
            hub.mark_task_done(task_id, "pass", report)
            print(f"Marked task {task_id} as pass.")

if __name__ == "__main__":
    main()
