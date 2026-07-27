# -*- coding: utf-8 -*-
import os
import sys
import traceback
from typing import Any, Dict, List, Tuple
from pathlib import Path

# プロジェクトルートを PYTHONPATH に追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from backend.agents.orchestration import OrchestrationHub

# マーク対象のタスク一覧をデータとして構造化
TASKS_TO_MARK: List[Dict[str, Any]] = [
    {
        "task_id": "T-batch_4ab330-test_weaver-000",
        "status": "pass",
        "report": {
            "message": "scratch/debug_mapping2.py に対するテスト追加タスク完了。エッジケースおよび境界値のテストを追加し、カバレッジ100%を維持。",
            "changed_files": [
                "backend/tests/test_scratch_debug_mapping2.py"
            ]
        }
    },
    {
        "task_id": "T-batch_4ab330-test_weaver-001",
        "status": "pass",
        "report": {
            "message": "verify_rank.py に対するテスト追加タスク完了。例外処理のエラーハンドリング部分へのモック適用により、カバレッジを90%から100%に向上。プロダクションコード変更なし(L1遵守)。",
            "changed_files": []
        }
    },
    {
        "task_id": "T-batch_4ab330-thumbnail-000",
        "status": "pass",
        "report": {
            "message": "thumbnail_engine/generator.py に対する品質基準検証および統合テストの追加タスク完了。Pillow等を用いた出力画像の解像度(1280x720以上)、アスペクト比(16:9)、ファイルサイズ(4MB未満)の自動検証テストを実装し、全PASSを確認。StageBoundAgentと自動リトライ/結果保存/DBマイグレーションの連携を検証した。",
            "changed_files": [
                "backend/tests/test_thumbnail_generator.py"
            ]
        }
    },
    {
        "task_id": "T-batch_4ab330-thumbnail-001",
        "status": "pass",
        "report": {
            "message": "services/thumbnail_analyzer.py に対する品質基準検証および統合テスト完了。解像度(1280x720以上)、アスペクト比(16:9)、ファイルサイズ(4MB未満)、破損チェック等の自動検証テストがPASSし、StageBoundAgent連携による非同期タスク処理(resolve_thumbnail_task)のSQLite指数バックオフ・最大5回リトライを含む正常動作を確認した。プロダクションコード変更なし(L2遵守)。",
            "changed_files": []
        }
    },
    {
        "task_id": "T-batch_4ab330-bug_hunter-000",
        "status": "skip",
        "report": {
            "message": "600秒タイムアウト（テスト実行のハング）のため強制終了。",
            "changed_files": []
        }
    },
    {
        "task_id": "T-batch_4ab330-refactor-000",
        "status": "skip",
        "report": {
            "message": "600秒タイムアウト（git log --all --name-only パイプラインコマンドのハング）のため強制終了。",
            "changed_files": []
        }
    }
]

# 定数定義
FLASH_CONVERSATION_ID = "bfbcc0d8-d1d7-4f54-9cd5-19a067e58a87"

def _get_exception_line(tb, default_line: int) -> int:
    """例外のトレースバックから、このファイル内での発生行番号を抽出する"""
    if not tb:
        return default_line
    this_file = Path(__file__).name
    tb_list = traceback.extract_tb(tb)
    for fs in reversed(tb_list):
        if Path(fs.filename).name == this_file:
            return fs.lineno
    return default_line

def register_technical_debt(line_number: int, pattern: str, notes: str, exception: Exception | None = None, _store=None) -> None:
    """例外に対する汎用catchが発生した際に技術負債を登録する。
    ただし、環境エラーや通信エラーなどのインフラ要因エラーは技術負債として登録しない。
    """
    if exception is not None:
        if isinstance(exception, (ConnectionError, TimeoutError, OSError)):
            return
    try:
        if _store is None:
            from backend.agents.memory.technical_debt import TechnicalDebtStore
            _store = TechnicalDebtStore()
        _store.register_debt(
            category="MINOR_INFRA",
            file_path="backend/agents/orchestration/mark_tasks_p27_batch_4ab330.py",
            line_number=line_number,
            pattern=pattern,
            cause_pattern="DP-01",
            fix_pattern="例外の厳密な個別型ハンドリングとバリデーションを適用する",
            registered_by="sprint_bug_hunter",
            notes=notes,
            tags=["bug_hunter", "except_exception"]
        )
    except Exception as register_err:
        print(f"Failed to register technical debt: {register_err}", file=sys.stderr)

def setup_orchestration_hub(conversation_id: str) -> OrchestrationHub:
    """OrchestrationHubを初期化し、セッション会話IDを設定する"""
    try:
        hub = OrchestrationHub()
        hub.register_flash_conversation_id(conversation_id)
        return hub
    except (OSError, ValueError) as e:
        print(f"Failed to setup OrchestrationHub with conversation ID '{conversation_id}': {e}", file=sys.stderr)
        raise
    except Exception as e:
        line_no = _get_exception_line(e.__traceback__, sys._getframe().f_lineno)
        register_technical_debt(
            line_number=line_no,
            pattern="except Exception as e:",
            notes=f"Failed to setup OrchestrationHub due to unexpected error: {e}",
            exception=e
        )
        print(f"Unexpected error in setup_orchestration_hub: {e}", file=sys.stderr)
        traceback.print_exc()
        raise

def extract_task_components(task_info: Dict[str, Any]) -> Tuple[str, str, Dict[str, Any]]:
    """タスク辞書からタスクID、ステータス、およびレポート内容を抽出する"""
    try:
        return task_info["task_id"], task_info["status"], task_info["report"]
    except KeyError as e:
        print(f"Failed to extract task components due to missing key in task_info: {e}", file=sys.stderr)
        raise
    except TypeError as e:
        print(f"Failed to extract task components: {e}", file=sys.stderr)
        raise
    except Exception as e:
        line_no = _get_exception_line(e.__traceback__, sys._getframe().f_lineno)
        register_technical_debt(
            line_number=line_no,
            pattern="except Exception as e:",
            notes=f"Failed to extract task components due to unexpected error: {e}",
            exception=e
        )
        print(f"Unexpected error in extract_task_components: {e}", file=sys.stderr)
        traceback.print_exc()
        raise

def register_task_status(hub: OrchestrationHub, task_info: Dict[str, Any]) -> None:
    """単一のタスクを OrchestrationHub に完了またはスキップとして登録する"""
    try:
        task_id, status, report = extract_task_components(task_info)
        hub.mark_task_done(task_id, status, report)
        print(f"Marked {task_id} as {status}")
    except (KeyError, TypeError, ValueError, OSError) as e:
        print(f"Failed to register task status for task_info: {task_info}. Error: {e}", file=sys.stderr)
        raise
    except Exception as e:
        line_no = _get_exception_line(e.__traceback__, sys._getframe().f_lineno)
        register_technical_debt(
            line_number=line_no,
            pattern="except Exception as e:",
            notes=f"Failed to register task status due to unexpected error: {e}",
            exception=e
        )
        print(f"Unexpected error in register_task_status: {e}", file=sys.stderr)
        traceback.print_exc()
        raise

def register_all_tasks_status(hub: OrchestrationHub, task_list: List[Dict[str, Any]]) -> None:
    """指定されたすべてのタスクのステータスを登録する"""
    for task_info in task_list:
        register_task_status(hub, task_info)

def update_session_heartbeat(hub: OrchestrationHub) -> None:
    """セッションの心拍（Heartbeat）を更新する"""
    hub.flash_update_heartbeat()

def display_session_status(hub: OrchestrationHub) -> None:
    """現在のセッションステータスを取得し、標準出力に表示する"""
    status_data = hub.generate_flash_status()
    print(status_data["formatted"])

def main() -> None:
    try:
        hub = setup_orchestration_hub(FLASH_CONVERSATION_ID)
        register_all_tasks_status(hub, TASKS_TO_MARK)
        update_session_heartbeat(hub)
        display_session_status(hub)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as e:
        print(f"Execution failed in main: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        line_no = _get_exception_line(e.__traceback__, sys._getframe().f_lineno)
        register_technical_debt(
            line_number=line_no,
            pattern="except Exception as e:",
            notes=f"Main execution failed due to unexpected error: {e}",
            exception=e
        )
        print(f"Unexpected error in main: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
