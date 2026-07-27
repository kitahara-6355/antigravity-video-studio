"""
特定のハングタスクを強制的に失敗としてマークするためのモジュール。

このモジュールは、実行時間が想定時間を超えたタスクや、ハングして応答しないタスクに対して、
OrchestrationHubを介して明示的に失敗ステータスとエラーレポートを記録します。
"""

import argparse
from backend.agents.orchestration import OrchestrationHub

# モジュール定数
DEFAULT_TIMEOUT_TASK_ID = "T-batch_6d239c-bug_hunter-004"
TIMEOUT_ERROR_MESSAGE = (
    "SUBAGENT_TIMEOUT: 600秒（10分）を超過したためハングタスクとして強制終了されました。"
)


def _normalize_changed_files(changed_files: list[str] | None) -> list[str]:
    """
    変更ファイルリストを正規化します。Noneの場合は空のリストを返します。
    """
    return changed_files if changed_files is not None else []


def create_timeout_report_payload(
    error_message: str = TIMEOUT_ERROR_MESSAGE,
    changed_files: list[str] = None
) -> dict:
    """
    タイムアウト失敗時のレポート用ペイロード（辞書）を作成します。

    Args:
        error_message (str): レポートに記録するエラーメッセージ。
        changed_files (list[str]): 変更されたファイルのリスト。デフォルトはNone（空リストとして処理）。

    Returns:
        dict: エラーメッセージと変更ファイル情報を含む辞書オブジェクト。
    """
    return {
        "error": error_message,
        "changed_files": _normalize_changed_files(changed_files)
    }


def _report_failure_to_hub(
    hub: OrchestrationHub,
    task_id: str,
    payload: dict
) -> None:
    """
    OrchestrationHubに失敗レポートを送信します。
    """
    hub.mark_task_done(task_id, "fail", payload)


def mark_timeout_failure(
    task_id: str = DEFAULT_TIMEOUT_TASK_ID,
    error_message: str = TIMEOUT_ERROR_MESSAGE,
    changed_files: list[str] = None
) -> None:
    """
    指定されたタスクをタイムアウトエラーとして失敗（fail）マークします。

    Args:
        task_id (str): 失敗マークを付与する対象のタスクID。
        error_message (str): 失敗の原因を示すエラーメッセージ。
        changed_files (list[str]): 変更されたファイルのリスト。
    """
    hub = OrchestrationHub()
    fail_report = create_timeout_report_payload(
        error_message=error_message,
        changed_files=changed_files
    )
    _report_failure_to_hub(hub, task_id, fail_report)
    print(f"Marked {task_id} as fail due to timeout")


def parse_arguments(args: list[str] = None) -> argparse.Namespace:
    """
    コマンドライン引数を解析して解析結果の名前空間を返します。

    Args:
        args (list[str]): コマンドライン引数のリスト。Noneの場合は空リストとして処理します。

    Returns:
        argparse.Namespace: パースされた引数の名前空間。
    """
    parser = argparse.ArgumentParser(
        description="特定のハングタスクを強制的に失敗としてマークします。"
    )
    parser.add_argument(
        "--task-id",
        default=DEFAULT_TIMEOUT_TASK_ID,
        help=f"失敗としてマークするタスクID (デフォルト: {DEFAULT_TIMEOUT_TASK_ID})"
    )
    parser.add_argument(
        "--error",
        default=TIMEOUT_ERROR_MESSAGE,
        help="エラーメッセージ"
    )
    parser.add_argument(
        "--changed-files",
        nargs="*",
        default=None,
        help="変更ファイルリスト（スペース区切り）"
    )

    clean_args = args if args is not None else []
    return parser.parse_args(clean_args)


def main(args: list[str] = None) -> None:
    """
    メイン実行エントリーポイント。

    コマンドライン引数を解析し、指定されたタスクの失敗マーク処理を実行します。

    Args:
        args (list[str]): コマンドライン引数のリスト。テストまたはプログラム内部から指定します。
    """
    parsed_args = parse_arguments(args)

    mark_timeout_failure(
        task_id=parsed_args.task_id,
        error_message=parsed_args.error,
        changed_files=parsed_args.changed_files
    )


if __name__ == "__main__":
    import sys
    from pathlib import Path

    # スクリプトを直接実行する場合のパス解決
    root_path = str(Path(__file__).resolve().parents[3])
    if root_path not in sys.path:
        sys.path.insert(0, root_path)
    main(sys.argv[1:])



