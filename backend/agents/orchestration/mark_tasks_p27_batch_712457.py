# -*- coding: utf-8 -*-
"""
Orchestration task marking script for batch 712457.
Provides modularized methods to initialize orchestration hub, mark tasks as complete or skipped,
and finalize the session with status printing and heartbeat updates.
"""

import sys
import json
from typing import Dict, List, Any

# Ensure backend directory is in path
sys.path.insert(0, '.')
from backend.agents.orchestration import OrchestrationHub


# Conversation ID of the Flash session
FLASH_CONVERSATION_ID = "0c00ce38-f479-4e0c-853e-22aa566d725e"

# Tasks definition for batch 712457
BATCH_TASKS = [
    {
        "task_id": "T-batch_712457-test_weaver-002",
        "status": "pass",
        "report": {
            "message": "data_migration.pyへの境界条件、複数キー欠落時の警告、OSError例外ルートなどのカバレッジ向上テストを追加。46passedを確認。",
            "changed_files": ["tests/test_data_migration_extra.py"]
        }
    },
    {
        "task_id": "T-batch_712457-refactor-001",
        "status": "pass",
        "report": {
            "message": "mark_tasks_p27_batch_d21647.pyを関数分割しリファクタリング。テストコードも追加し、カバレッジ100%を維持しながら全テストPASSを確認。",
            "changed_files": [
                "backend/agents/orchestration/mark_tasks_p27_batch_d21647.py",
                "tests/test_mark_tasks_p27_batch_d21647.py"
            ]
        }
    },
    {
        "task_id": "T-batch_712457-refactor-000",
        "status": "pass",
        "report": {
            "message": "flash_runner_next_batch_5.pyの関数分割、命名改善、具体的例外処理(TD-1013)による頑健化。カバレッジ100%維持を確認。",
            "changed_files": [
                "backend/agents/orchestration/flash_runner_next_batch_5.py",
                "tests/test_flash_runner_next_batch_5.py"
            ]
        }
    },
    {
        "task_id": "T-batch_712457-bug_hunter-002",
        "status": "pass",
        "report": {
            "message": "test_main_coverage.pyの絶対パスハードコード解消、およびtest_api.pyのTestApprovalAPIへのsession_id追加によるテストFAILバグの修正。",
            "changed_files": [
                "backend/tests/test_main_coverage.py",
                "backend/tests/test_api.py"
            ]
        }
    },
    {
        "task_id": "T-batch_712457-bug_hunter-000",
        "status": "pass",
        "report": {
            "message": "test_flash_assign_subagents_10.pyにおけるインポートプレフィックス不整合バグを動的解決に修正。テスト全PASSを確認。",
            "changed_files": ["backend/tests/test_flash_assign_subagents_10.py"]
        }
    },
    {
        "task_id": "T-batch_712457-tdr_cleanup-000",
        "status": "pass",
        "report": {
            "message": "speaker_diarizer.pyの特定例外処理とデフォルトフォールバックを安全化。TDR TD-243の解消ステータス更新を確認。",
            "changed_files": [
                "backend/subtitle_engine/speaker_diarizer.py",
                "backend/tests/test_speaker_diarizer.py",
                "backend/tests/test_shared/test_subtitle_engines.py"
            ]
        }
    },
    {
        "task_id": "T-batch_712457-test_weaver-001",
        "status": "pass",
        "report": {
            "message": "preview_report_generator.pyのエラーハンドリングやPillow互換性パスに対するテスト10件を追加し、カバレッジ100%を達成。",
            "changed_files": ["backend/tests/test_shared/test_preview_system.py"]
        }
    },
    {
        "task_id": "T-batch_712457-test_weaver-003",
        "status": "pass",
        "report": {
            "message": "ai_rhythm.py に対するユニットテストの追加、境界値検証や無効型の例外処理などエッジケースを検証する3テストを追加。38 passedを確認。",
            "changed_files": ["backend/tests/test_shared/test_ai_rhythm.py"]
        }
    },
    {
        "task_id": "T-batch_712457-test_weaver-000",
        "status": "pass",
        "report": {
            "message": "main.pyテストの絶対パスハードコード動的化、およびrequest_id未設定やCORS空値、ネスト例外ログフォーマット等の補強テストを追加。23 passedを確認。",
            "changed_files": ["backend/tests/test_main_coverage.py"]
        }
    },
    {
        "task_id": "T-batch_712457-thumbnail-000",
        "status": "pass",
        "report": {
            "message": "logo_overlay.pyの黒背景パディング指定、ロゴはみ出し防止自動クリップ、単色無効画像検証などの機能改善と、品質検証仕様に基づく堅牢テストを追加。",
            "changed_files": [
                "backend/logo_overlay.py",
                "backend/tests/test_logo_overlay.py"
            ]
        }
    },
    {
        "task_id": "T-batch_712457-tdr_cleanup-001",
        "status": "pass",
        "report": {
            "message": "test_thumbnail_api.py の ValueError マッチパターン不整合によるテストFAILバグを修正。全35テストPASSを確認。",
            "changed_files": ["backend/tests/test_thumbnail_api.py"]
        }
    },
    {
        "task_id": "T-batch_712457-bug_hunter-001",
        "status": "skip",
        "report": {
            "message": "サブエージェントが 720 秒のタイムアウト制限（夜間モード）を超過したため、タスクを skip としてマーク。",
            "changed_files": []
        }
    }
]


def initialize_orchestration_hub(conversation_id: str = FLASH_CONVERSATION_ID) -> OrchestrationHub:
    """
    Initializes OrchestrationHub and registers the flash conversation ID.
    
    Args:
        conversation_id: The Flash conversation ID to register.
        
    Returns:
        OrchestrationHub: The initialized hub instance.
        
    Raises:
        ValueError: If conversation_id is invalid.
    """
    if not conversation_id or not isinstance(conversation_id, str):
        raise ValueError("conversation_id must be a non-empty string")
        
    hub = OrchestrationHub()
    hub.register_flash_conversation_id(conversation_id)
    return hub


def mark_single_task(hub: OrchestrationHub, task_info: Dict[str, Any]) -> None:
    """
    Marks a single task status as done on the orchestration hub.
    
    Args:
        hub: The orchestration hub instance.
        task_info: A dictionary containing task details.
        
    Raises:
        KeyError: If required keys are missing in task_info.
        TypeError: If task_info has incorrect data types.
    """
    if not isinstance(task_info, dict):
        raise TypeError("task_info must be a dictionary")
        
    required_keys = {"task_id", "status", "report"}
    missing_keys = required_keys - task_info.keys()
    if missing_keys:
        raise KeyError(f"task_info missing required keys: {missing_keys}")
        
    task_id = task_info["task_id"]
    status = task_info["status"]
    report = task_info["report"]
    
    if not isinstance(task_id, str) or not isinstance(status, str) or not isinstance(report, dict):
        raise TypeError("Invalid data types in task_info values")
        
    hub.mark_task_done(task_id, status, report)


def process_task_marking(hub: OrchestrationHub, tasks: List[Dict[str, Any]] = BATCH_TASKS) -> None:
    """
    Iterates and marks all batch tasks as done.
    
    Args:
        hub: The orchestration hub instance.
        tasks: The list of tasks to mark.
        
    Raises:
        TypeError: If tasks is not a list.
    """
    if not isinstance(tasks, list):
        raise TypeError("tasks must be a list")
        
    for task in tasks:
        mark_single_task(hub, task)


def finalize_hub_session(hub: OrchestrationHub) -> Dict[str, Any]:
    """
    Updates the session heartbeat, generates and prints status.
    
    Args:
        hub: The orchestration hub instance.
        
    Returns:
        Dict[str, Any]: The generated status dictionary.
    """
    # 心拍更新
    hub.flash_update_heartbeat()
    
    print("TASKS_MARKED_DONE")
    
    # 最新ステータス表示
    status = hub.generate_flash_status()
    print("FLASH_STATUS:" + json.dumps(status))
    return status


def main() -> None:
    """
    Main execution entry point.
    """
    try:
        hub = initialize_orchestration_hub()
        process_task_marking(hub)
        finalize_hub_session(hub)
    except (ValueError, TypeError, KeyError) as e:
        print(f"Validation error during orchestration marking: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error during orchestration marking: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
