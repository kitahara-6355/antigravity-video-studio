import sys
import os
import pytest
import importlib
from unittest.mock import patch, MagicMock

# プロジェクトルートとbackendをsys.pathに追加してインポート可能にする
root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root_path not in sys.path:
    sys.path.insert(0, root_path)
if os.path.join(root_path, "backend") not in sys.path:
    sys.path.insert(0, os.path.join(root_path, "backend"))

TARGET_MODULE = "backend.agents.orchestration.copy_artifacts_batch_00d5aa_agent0"


def test_copy_artifacts_batch_00d5aa_agent0_success():
    """コピー元ファイルが存在し、正常にコピーおよびマーク処理が実行されることを検証します。"""
    # インポート済みの場合は削除して再ロード時にモジュールレベルコードを走らせる
    if TARGET_MODULE in sys.modules:
        del sys.modules[TARGET_MODULE]

    with patch("shutil.copy2") as mock_copy, \
         patch("os.path.exists", return_value=True) as mock_exists, \
         patch("os.makedirs") as mock_makedirs, \
         patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:

        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub

        # モジュールをインポート（これにより中の処理が走る）
        target = importlib.import_module(TARGET_MODULE)

        # 期待される動作の検証
        assert mock_exists.call_count == len(target.copy_targets)
        assert mock_copy.call_count == len(target.copy_targets)
        assert mock_makedirs.call_count == len(target.copy_targets)
        
        mock_hub.mark_task_done.assert_called_once_with(
            "T-batch_00d5aa-bug_hunter-000",
            "pass",
            {
                "subagent_id": "73ed5ee3-f4a5-4cea-8dd6-057a64523370",
                "message": "Successfully resolved except Exceptions in flash_runner_control.py, added tests, and confirmed 10 passed."
            }
        )


def test_copy_artifacts_batch_00d5aa_agent0_file_not_found():
    """コピー元ファイルが存在せず、コピーがスキップされることを検証します。"""
    # インポート済みの場合は削除
    if TARGET_MODULE in sys.modules:
        del sys.modules[TARGET_MODULE]

    with patch("shutil.copy2") as mock_copy, \
         patch("os.path.exists", return_value=False) as mock_exists, \
         patch("os.makedirs") as mock_makedirs, \
         patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:

        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub

        # モジュールをインポート
        target = importlib.import_module(TARGET_MODULE)

        # コピーがスキップされたことを検証
        assert mock_exists.call_count == len(target.copy_targets)
        mock_copy.assert_not_called()
        mock_makedirs.assert_not_called()
        
        # コピーがスキップされてもマーク処理は行われることを検証
        mock_hub.mark_task_done.assert_called_once_with(
            "T-batch_00d5aa-bug_hunter-000",
            "pass",
            {
                "subagent_id": "73ed5ee3-f4a5-4cea-8dd6-057a64523370",
                "message": "Successfully resolved except Exceptions in flash_runner_control.py, added tests, and confirmed 10 passed."
            }
        )


def test_copy_artifacts_batch_00d5aa_agent0_mixed():
    """一部のコピー元ファイルのみが存在し、存在するファイルのみがコピーされることを検証します。"""
    # インポート済みの場合は削除
    if TARGET_MODULE in sys.modules:
        del sys.modules[TARGET_MODULE]

    with patch("shutil.copy2") as mock_copy, \
         patch("os.path.exists", side_effect=[True, False]) as mock_exists, \
         patch("os.makedirs") as mock_makedirs, \
         patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:

        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub

        # モジュールをインポート
        target = importlib.import_module(TARGET_MODULE)

        # 1つ目のファイルだけがコピーされたことを検証
        assert mock_exists.call_count == len(target.copy_targets)
        assert mock_copy.call_count == 1
        assert mock_makedirs.call_count == 1
        
        # マーク処理が行われることを検証
        mock_hub.mark_task_done.assert_called_once_with(
            "T-batch_00d5aa-bug_hunter-000",
            "pass",
            {
                "subagent_id": "73ed5ee3-f4a5-4cea-8dd6-057a64523370",
                "message": "Successfully resolved except Exceptions in flash_runner_control.py, added tests, and confirmed 10 passed."
            }
        )

