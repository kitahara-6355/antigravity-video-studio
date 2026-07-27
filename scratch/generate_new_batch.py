import json
import time
from pathlib import Path

def main():
    queue_path = Path("backend/agents/orchestration/task_queue.json")
    if not queue_path.exists():
        print("task_queue.json not found")
        return
        
    now = time.time()
    
    new_data = {
        "schema_version": "1.0",
        "current_batch_id": "batch_db4802",
        "generated_at": json.dumps(now), # JSON形式のISO時刻またはエポック秒
        "phase": 22,
        "milestone": "M22.6",
        "tasks": [
            {
                "id": "T-batch_db4802-throttle-000",
                "group": "bug_hunter",
                "level": "L2",
                "target_module": "agents/orchestration/throttle_harness.py",
                "instruction": "Milestone 22.6 / Task A — APIクォータおよびシステムリソースの動的スロットリングと自動クールダウンを実装する throttle_harness.py とそのテストを作成し、カバレッジ100%を達成すること。",
                "status": "pending",
                "assigned_agent": None,
                "result": None,
                "created_at": now
            },
            {
                "id": "T-batch_db4802-coverage-001",
                "group": "test_weaver",
                "level": "L1",
                "target_module": "tests/test_coverage_validator.py",
                "instruction": "Milestone 22.6 / Task B — 変更対象行の未カバー行0件チェックおよびBranchカバレッジ非退行自動検証テストを test_coverage_validator.py に実装すること。",
                "status": "pending",
                "assigned_agent": None,
                "result": None,
                "created_at": now
            },
            {
                "id": "T-batch_db4802-error_boundary-002",
                "group": "tdr_cleanup",
                "level": "L2",
                "target_module": "agents/pipeline_types.py",
                "instruction": "Milestone 22.6 / Task C — 各種例外を標準エラー型にラップし、例外時のTDR自動登録ガードを統合した共通エラー境界 PipelineErrorBoundary を pipeline_types.py に実装し、そのテストを作成してカバレッジ100%を達成すること。",
                "status": "pending",
                "assigned_agent": None,
                "result": None,
                "created_at": now
            }
        ],
        "blacklisted_modules": [],
        "assigned_modules": [
            "agents/orchestration/throttle_harness.py",
            "tests/test_coverage_validator.py",
            "agents/pipeline_types.py"
        ],
        "batch_config": {
            "max_parallel": 30,
            "groups": {
                "bug_hunter": 40,
                "test_weaver": 40,
                "tdr_cleanup": 20
            }
        }
    }
    
    # ISO8601フォーマットで生成日時を設定
    new_data["generated_at"] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now))
    for t in new_data["tasks"]:
        t["created_at"] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now))
        
    with open(queue_path, "w", encoding="utf-8") as f:
        json.dump(new_data, f, ensure_ascii=False, indent=2)
        
    print("Successfully generated new batch in task_queue.json.")

if __name__ == "__main__":
    main()
