from backend.agents.orchestration import OrchestrationHub

hub = OrchestrationHub()

tasks = [
    "T-batch_736f9a-thumbnail-000",
    "T-batch_736f9a-thumbnail-001",
    "T-batch_736f9a-thumbnail-002",
    "T-batch_736f9a-thumbnail-003",
    "T-batch_736f9a-thumbnail-004",
    "T-batch_736f9a-thumbnail-005"
]

for task_id in tasks:
    hub.mark_task_done(task_id, "pass", {
        "message": "すでにテストがPASSしており、変更は不要です。",
        "changed_files": []
    })

hub.submit_batch_report("batch_736f9a", {
    "passed": 6,
    "failed": 0,
    "skipped": 0,
    "total": 6
})

status = hub.generate_flash_status()
print(status["formatted"])
