"""
OrchestrationHubを使用して、特定のFlashタスクを完了マークするためのスクリプト。

デフォルトでは特定のサムネイル処理改善タスクを完了マークしますが、
引数を指定することで任意のタスクや会話IDに対して処理を実行できます。

本モジュールは、OrchestrationHubと連携して動的タスク実行、状態管理、
および進捗状況のダッシュボードへの書き出しをサポートする、システムオーケストレーションの
重要なユーティリティコンポーネントです。
"""

import os
import sys
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from backend.agents.orchestration import OrchestrationHub
from backend.agents.orchestration.hub_common import OpusQuotaExceededException
import json
from typing import List, Optional, Literal

# ロガーの設定
logger = logging.getLogger(__name__)

DEFAULT_MESSAGE = "Task marked done via mark_tasks_001"

def main(
    hub: Optional[OrchestrationHub] = None,
    conversation_id: Optional[str] = None,
    task_id: Optional[str] = None,
    status_str: Literal["pass", "fail"] = "pass",
    message: Optional[str] = None,
    changed_files: Optional[List[str]] = None
) -> int:
    """
    指定されたFlashタスクを完了マークし、心拍を更新して最新のステータスを出力します。

    OrchestrationHubを通じて指定タスクのステータスを "pass" または "fail" に更新し、
    タスク実行中に変更されたファイルの一覧 (changed_files) を記録します。また、
    該当セッションの心拍 (heartbeat) を更新することで、Opus戦略層に対して
    Flash実行層が生存していることを通知し、タイムアウトによる自動停止を防止します。

    Args:
        hub (Optional[OrchestrationHub]): オーケストレーションハブのインスタンス。
            指定しない場合は新規に初期化されます。
        conversation_id (Optional[str]): 対象のFlash会話ID。
            指定しない場合は環境変数 `FLASH_CONVERSATION_ID` から自動取得します。
        task_id (Optional[str]): 完了マークするタスクの識別子（タスクID）。
            指定しない場合は環境変数 `FLASH_TASK_ID` から自動取得します。
        status_str (Literal["pass", "fail"]): タスクの終了状態。
            "pass" (成功) または "fail" (失敗) のいずれかの文字列を指定します。
        message (Optional[str]): タスク実行に関する詳細メッセージ、またはエラー時の概要。
            指定しない場合はデフォルトメッセージ `DEFAULT_MESSAGE` が適用されます。
        changed_files (Optional[List[str]]): このタスクによって変更されたファイルパスのリスト。
            カンマ区切り文字列やリスト型を受け入れ、内部でトリムおよびクレンジングが実行されます。

    Returns:
        int: 実行結果ステータスコード。成功した場合は 0、無効な引数や処理中のエラーで失敗した場合は 1。
    """
    # 環境変数からのフォールバック
    conversation_id = conversation_id or os.environ.get("FLASH_CONVERSATION_ID")
    task_id = task_id or os.environ.get("FLASH_TASK_ID")

    if not conversation_id:
        logger.error("エラー: conversation_id が指定されておらず、環境変数 FLASH_CONVERSATION_ID も設定されていません。")
        return 1
    if not task_id:
        logger.error("エラー: task_id が指定されておらず、環境変数 FLASH_TASK_ID も設定されていません。")
        return 1

    # ステータスのバリデーションと正規化
    if status_str is None or not isinstance(status_str, str):
        logger.error(f"エラー: 無効なステータス型 '{type(status_str)}' が指定されました。'pass' または 'fail' (文字列) を指定してください。")
        return 1

    normalized_status = status_str.strip().lower()
    if normalized_status not in ("pass", "fail"):
        logger.error(f"エラー: 無効なステータス '{status_str}' が指定されました。'pass' または 'fail' を指定してください。")
        return 1

    message = message or DEFAULT_MESSAGE
    
    # 変更ファイルのパースとクレンジング（カンマ区切り対応、トリム処理、空要素除外）
    cleaned_changed_files = []
    if changed_files is not None:
        if isinstance(changed_files, str):
            items = [changed_files]
        elif not isinstance(changed_files, (list, tuple)):
            items = [str(changed_files)]
        else:
            items = changed_files

        for item in items:
            if not isinstance(item, str):
                item = str(item)
            if not item:
                continue
            cleaned_changed_files.extend(
                [f.strip() for f in item.split(",") if f.strip()]
            )

    try:
        logger.info(f"OrchestrationHubの初期化を開始します (conversation_id: {conversation_id})")
        if hub is None:
            hub = OrchestrationHub()
        hub.register_flash_conversation_id(conversation_id)
        
        # 心拍更新
        logger.info("心拍更新を実行中...")
        hub.flash_update_heartbeat()
        
        # タスク完了マーク
        logger.info(f"タスク {task_id} をステータス {normalized_status} で完了マーク中...")
        hub.mark_task_done(task_id, normalized_status, {
            "message": message,
            "changed_files": cleaned_changed_files
        })
        
        print("TASK_MARKED_DONE")

        # 最新ステータス表示
        status = hub.generate_flash_status()
        print("FLASH_STATUS:" + json.dumps(status))
        return 0
    except OpusQuotaExceededException as e:
        logger.error(f"エラー: Claude Opus APIのクォータ制限を超過しました: {str(e)}")
        return 1
    except Exception as e:
        # TD-1441: コマンドライン最外周でのクラッシュ防止用 generic exception
        logger.exception(f"エラー: 実行中に想定外のエラーが発生しました: {str(e)}")
        return 1

if __name__ == "__main__":
    import argparse
    # コマンドライン実行時の簡易ロギング設定
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    
    parser = argparse.ArgumentParser(description="OrchestrationHubを使用して、特定のFlashタスクを完了マークするためのスクリプト。")
    parser.add_argument("--conversation-id", "-c", type=str, default=None, help="対象のFlash会話ID")
    parser.add_argument("--task-id", "-t", type=str, default=None, help="完了マークするタスクID")
    parser.add_argument("--status", "-s", type=str, default="pass", help="タスクのステータス（'pass' または 'fail'）")
    parser.add_argument("--message", "-m", type=str, default=None, help="完了メッセージ")
    parser.add_argument("--changed-files", "-f", nargs="*", default=None, help="変更されたファイルパスのリスト")
    
    args = parser.parse_args()
    
    sys.exit(
        main(
            conversation_id=args.conversation_id,
            task_id=args.task_id,
            status_str=args.status,
            message=args.message,
            changed_files=args.changed_files
        )
    )
