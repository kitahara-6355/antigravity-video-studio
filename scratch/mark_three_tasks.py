import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    conv_id = "78b44067-a11c-4c04-9106-db3d8f632741"
    hub.register_flash_conversation_id(conv_id)
    
    # 1. Mark refactor-000
    task_id_ref = "T-batch_556530-refactor-000"
    report_ref = {
        "message": "agents/workers/transcribe_worker.py 内の _run_whisper_subprocess での pipe.close() 例外処理を修正し、テストで発生するモックの Exception を正しく処理するように改善。TDRに TD-1068 を登録し、全テストPASSを確認。",
        "changed_files": ["backend/agents/workers/transcribe_worker.py"]
    }
    print(f"Marking task {task_id_ref} as pass...")
    hub.mark_task_done(task_id_ref, "pass", report_ref)

    # 2. Mark test_weaver-001
    task_id_weaver = "T-batch_556530-test_weaver-001"
    report_weaver = {
        "message": "agents/orchestration/mark_tasks_p27_multi7.py のテストコードを記述・改善し、カバレッジ向上。全テストPASSを確認。",
        "changed_files": ["backend/tests/test_mark_tasks_p27_multi7.py"]
    }
    print(f"Marking task {task_id_weaver} as pass...")
    hub.mark_task_done(task_id_weaver, "pass", report_weaver)

    # 3. Mark thumbnail-000
    task_id_thumb = "T-batch_556530-thumbnail-000"
    report_thumb = {
        "message": "thumbnail_engine/generator.py に対し、解像度 1280x720 以上、アスペクト比 16:9、ファイルサイズ 4MB 未満、Pillow健全ロード、StageBoundAgent連携を含む自動検証テストをクリア。例外ハンドリングのTDR登録も実施。",
        "changed_files": ["backend/thumbnail_engine/generator.py"]
    }
    print(f"Marking task {task_id_thumb} as pass...")
    hub.mark_task_done(task_id_thumb, "pass", report_thumb)

    # 心拍とステータス更新
    hub.flash_update_heartbeat()
    status = hub.generate_flash_status()
    print("--- Flash Status After Marking ---")
    print(status.get("formatted", ""))

if __name__ == "__main__":
    main()
