import sys
from pathlib import Path

# backend パスを sys.path に追加
backend_path = Path(__file__).resolve().parent.parent
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

try:
    from agents.orchestration.orchestrator import OrchestrationHub
except ImportError:
    sys.path.insert(0, str(backend_path.parent))
    from backend.agents.orchestration.orchestrator import OrchestrationHub

hub = OrchestrationHub()

# 6つの weaver タスクを完了マーク
tasks = [
    {
        "id": "T-batch_a620d7-test_weaver-000",
        "result": {
            "message": "conftest.pyのテストカバレッジを54%から100%に向上。IOCPハング対策、tv01_path分岐、slowスキップ処理などのユニットテストを追加し全PASS。",
            "changed_files": ["backend/tests/conftest.py"]
        }
    },
    {
        "id": "T-batch_a620d7-test_weaver-001",
        "result": {
            "message": "project_archiver.pyのカバレッジ100%を維持しつつ、堅牢性を向上させる異常系エッジケーステスト5件を追加。全PASSを確認。",
            "changed_files": ["backend/tests/test_shared/test_project_archiver_edge_cases.py"]
        }
    },
    {
        "id": "T-batch_a620d7-test_weaver-002",
        "result": {
            "message": "routers/admin_integration_router.pyの未カバー分岐を網羅するテストを6件追加。dashboardのpartial分岐やPydantic複数バリデーションなどを網羅し、計29テストが全PASS。",
            "changed_files": ["backend/tests/test_shared/test_admin_integration_edge_cases.py"]
        }
    },
    {
        "id": "T-batch_a620d7-test_weaver-003",
        "result": {
            "message": "plugins/report_generator_plugin.pyのエッジケーステスト5件を追加。型安全性の例外検証などを含め、計13テストすべてPASS。",
            "changed_files": ["backend/tests/test_shared/test_report_generator_plugin_edge_cases.py"]
        }
    },
    {
        "id": "T-batch_a620d7-test_weaver-004",
        "result": {
            "message": "inspect_video.pyのビデオ以外のストリーム分岐テストを追加し、ブランチカバレッジを94.4%から100%に向上。",
            "changed_files": ["backend/tests/test_shared/test_inspect_video_coverage.py"]
        }
    },
    {
        "id": "T-batch_a620d7-test_weaver-005",
        "result": {
            "message": "agents/advisor_gate.pyの新規ユニットテスト15件を実装し、カバレッジを0%から100%に向上。UXラチェット全PASS。",
            "changed_files": ["backend/tests/test_advisor_gate.py"]
        }
    }
]

print("Marking tasks as done...")
for t in tasks:
    hub.mark_task_done(t["id"], "pass", t["result"])
    print(f"Task {t['id']} marked as done.")

# バッチ完了報告
# バッチ全体の中で完了したタスクの集計を送信
batch_status = hub.get_queue_status()
batch_id = batch_status.get("batch_id", "batch_a620d7")

# bug_hunterの12タスクとweaverの6タスクがすべてPASS (計18タスク)
hub.submit_batch_report(batch_id, {
    "passed": 18,
    "failed": 0,
    "total": 18
})

print(f"Batch {batch_id} completion report submitted successfully!")
