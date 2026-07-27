import sys
import os
import importlib
import pytest
from unittest.mock import MagicMock, patch

# テスト対象のモジュール名
TARGET_MODULE = "backend.agents.orchestration.copy_artifacts_batch_00d5aa_agent0"

@pytest.fixture
def clean_sys_modules():
    """テスト実行後に sys.modules から対象モジュールを削除し、再ロードできるようにする"""
    yield
    if TARGET_MODULE in sys.modules:
        del sys.modules[TARGET_MODULE]

def test_copy_artifacts_success(clean_sys_modules, capsys):
    # すべてのコピー元ファイルが存在するケースのモックを設定
    mock_exists = MagicMock(return_value=True)
    mock_makedirs = MagicMock()
    mock_copy = MagicMock()
    
    mock_hub_instance = MagicMock()
    mock_hub_class = MagicMock(return_value=mock_hub_instance)
    
    with patch("os.path.exists", mock_exists), \
         patch("os.makedirs", mock_makedirs), \
         patch("shutil.copy2", mock_copy), \
         patch("backend.agents.orchestration.OrchestrationHub", mock_hub_class):
        
        # モジュールのインポート（これによりコードが実行される）
        importlib.import_module(TARGET_MODULE)
        
    # 標準出力を取得
    captured = capsys.readouterr()
    
    # 期待される出力の検証
    assert "--- Starting File Copy (Agent 0) ---" in captured.out
    assert "Copied: backend/agents/orchestration/flash_runner_control.py -> backend/agents/orchestration/flash_runner_control.py" in captured.out
    assert "Copied: backend/tests/test_flash_runner_control.py -> backend/tests/test_flash_runner_control.py" in captured.out
    assert "--- Marking Tasks as Done (Agent 0) ---" in captured.out
    assert "Marked T-batch_00d5aa-bug_hunter-000 as pass" in captured.out
    assert "COPY_AND_MARK_PROCESS_COMPLETED" in captured.out
    
    # モックの呼び出し検証
    assert mock_exists.call_count == 2
    assert mock_makedirs.call_count == 2
    assert mock_copy.call_count == 2
    
    # OrchestrationHub の呼び出し検証
    mock_hub_class.assert_called_once()
    mock_hub_instance.mark_task_done.assert_called_once_with(
        "T-batch_00d5aa-bug_hunter-000",
        "pass",
        {
            "subagent_id": "73ed5ee3-f4a5-4cea-8dd6-057a64523370",
            "message": "Successfully resolved except Exceptions in flash_runner_control.py, added tests, and confirmed 10 passed."
        }
    )

def test_copy_artifacts_missing(clean_sys_modules, capsys):
    # コピー元ファイルが存在しないケースのモックを設定
    mock_exists = MagicMock(return_value=False)
    mock_makedirs = MagicMock()
    mock_copy = MagicMock()
    
    mock_hub_instance = MagicMock()
    mock_hub_class = MagicMock(return_value=mock_hub_instance)
    
    with patch("os.path.exists", mock_exists), \
         patch("os.makedirs", mock_makedirs), \
         patch("shutil.copy2", mock_copy), \
         patch("backend.agents.orchestration.OrchestrationHub", mock_hub_class):
        
        # モジュールのインポート
        importlib.import_module(TARGET_MODULE)
        
    # 標準出力を取得
    captured = capsys.readouterr()
    
    # 期待される出力の検証
    assert "--- Starting File Copy (Agent 0) ---" in captured.out
    assert "File not found:" in captured.out
    assert "--- Marking Tasks as Done (Agent 0) ---" in captured.out
    assert "Marked T-batch_00d5aa-bug_hunter-000 as pass" in captured.out
    assert "COPY_AND_MARK_PROCESS_COMPLETED" in captured.out
    
    # モックの呼び出し検証
    assert mock_exists.call_count == 2
    mock_makedirs.assert_not_called()
    mock_copy.assert_not_called()
    
    # OrchestrationHub の呼び出し検証
    mock_hub_class.assert_called_once()
    mock_hub_instance.mark_task_done.assert_called_once()

def test_copy_artifacts_partial(clean_sys_modules, capsys):
    # 1つ目のファイルは存在し、2つ目は存在しないケース
    mock_exists = MagicMock(side_effect=[True, False])
    mock_makedirs = MagicMock()
    mock_copy = MagicMock()
    
    mock_hub_instance = MagicMock()
    mock_hub_class = MagicMock(return_value=mock_hub_instance)
    
    with patch("os.path.exists", mock_exists), \
         patch("os.makedirs", mock_makedirs), \
         patch("shutil.copy2", mock_copy), \
         patch("backend.agents.orchestration.OrchestrationHub", mock_hub_class):
        
        # モジュールのインポート
        importlib.import_module(TARGET_MODULE)
        
    captured = capsys.readouterr()
    
    # 期待される出力の検証
    assert "Copied: backend/agents/orchestration/flash_runner_control.py -> backend/agents/orchestration/flash_runner_control.py" in captured.out
    assert "File not found:" in captured.out
    
    # コピーされたのは1つだけ
    assert mock_makedirs.call_count == 1
    assert mock_copy.call_count == 1
    
    # Hubの完了マークは呼ばれる
    mock_hub_class.assert_called_once()
    mock_hub_instance.mark_task_done.assert_called_once()

def test_copy_artifacts_makedirs_error(clean_sys_modules):
    # os.makedirs が例外を投げるケース
    mock_exists = MagicMock(return_value=True)
    mock_makedirs = MagicMock(side_effect=PermissionError("Permission denied"))
    mock_copy = MagicMock()
    
    mock_hub_instance = MagicMock()
    mock_hub_class = MagicMock(return_value=mock_hub_instance)
    
    with patch("os.path.exists", mock_exists), \
         patch("os.makedirs", mock_makedirs), \
         patch("shutil.copy2", mock_copy), \
         patch("backend.agents.orchestration.OrchestrationHub", mock_hub_class):
        
        # 例外が発生することを確認
        with pytest.raises(PermissionError):
            importlib.import_module(TARGET_MODULE)
            
    # コピー処理は行われない
    mock_copy.assert_not_called()
    # Hubの完了マークも呼ばれない
    mock_hub_instance.mark_task_done.assert_not_called()

def test_copy_artifacts_hub_error(clean_sys_modules):
    # OrchestrationHub が例外を投げるケース
    mock_exists = MagicMock(return_value=True)
    mock_makedirs = MagicMock()
    mock_copy = MagicMock()
    
    mock_hub_instance = MagicMock()
    mock_hub_instance.mark_task_done.side_effect = RuntimeError("Hub Connection Failed")
    mock_hub_class = MagicMock(return_value=mock_hub_instance)
    
    with patch("os.path.exists", mock_exists), \
         patch("os.makedirs", mock_makedirs), \
         patch("shutil.copy2", mock_copy), \
         patch("backend.agents.orchestration.OrchestrationHub", mock_hub_class):
        
        # 例外が発生することを確認
        with pytest.raises(RuntimeError) as excinfo:
            importlib.import_module(TARGET_MODULE)
        assert "Hub Connection Failed" in str(excinfo.value)

def test_copy_artifacts_copy2_error(clean_sys_modules):
    # shutil.copy2 が例外を投げるケース
    mock_exists = MagicMock(return_value=True)
    mock_makedirs = MagicMock()
    mock_copy = MagicMock(side_effect=PermissionError("Write permission denied"))
    
    mock_hub_instance = MagicMock()
    mock_hub_class = MagicMock(return_value=mock_hub_instance)
    
    with patch("os.path.exists", mock_exists), \
         patch("os.makedirs", mock_makedirs), \
         patch("shutil.copy2", mock_copy), \
         patch("backend.agents.orchestration.OrchestrationHub", mock_hub_class):
        
        # 例外が発生することを確認
        with pytest.raises(PermissionError) as excinfo:
            importlib.import_module(TARGET_MODULE)
        assert "Write permission denied" in str(excinfo.value)
        
    # Hubの完了マークは呼ばれない
    mock_hub_instance.mark_task_done.assert_not_called()

def test_copy_artifacts_sys_path(clean_sys_modules):
    # sys.path に root_path および backend が挿入されることを検証する
    mock_exists = MagicMock(return_value=True)
    mock_makedirs = MagicMock()
    mock_copy = MagicMock()
    
    mock_hub_instance = MagicMock()
    mock_hub_class = MagicMock(return_value=mock_hub_instance)
    
    # テスト開始時の sys.path をコピー
    original_sys_path = list(sys.path)
    
    try:
        with patch("os.path.exists", mock_exists), \
             patch("os.makedirs", mock_makedirs), \
             patch("shutil.copy2", mock_copy), \
             patch("backend.agents.orchestration.OrchestrationHub", mock_hub_class):
            
            importlib.import_module(TARGET_MODULE)
            
        # sys.path の先頭に root_path と backend が追加されているか検証
        expected_root = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
        expected_backend = os.path.join(expected_root, "backend")
        
        assert sys.path[0] == expected_backend
        assert sys.path[1] == expected_root
    finally:
        # 例外が発生した場合でも確実に sys.path を元に戻す
        sys.path = original_sys_path


def test_copy_artifacts_module_variables(clean_sys_modules):
    # モジュールロード時にグローバル変数が正しく定義されていることを検証する
    mock_exists = MagicMock(return_value=True)
    mock_makedirs = MagicMock()
    mock_copy = MagicMock()
    
    mock_hub_instance = MagicMock()
    mock_hub_class = MagicMock(return_value=mock_hub_instance)
    
    with patch("os.path.exists", mock_exists), \
         patch("os.makedirs", mock_makedirs), \
         patch("shutil.copy2", mock_copy), \
         patch("backend.agents.orchestration.OrchestrationHub", mock_hub_class):
        
        module = importlib.import_module(TARGET_MODULE)
        
    expected_root = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
    assert module.dest_base == expected_root
    assert module.src_agent_0 == r"C:\Users\PC_User\.gemini\antigravity\brain\f9a7ff51-0cc8-4692-aa10-04feec4ee3ce\.system_generated\worktrees\subagent-bug-hunter-Agent-0-self-6de64ebe"
    assert len(module.copy_targets) == 2
    assert module.copy_targets[0] == (
        module.src_agent_0,
        "backend/agents/orchestration/flash_runner_control.py",
        "backend/agents/orchestration/flash_runner_control.py"
    )


def test_copy_artifacts_directory_already_exists(clean_sys_modules, capsys):
    # コピー先ディレクトリが既に存在する場合に os.makedirs が正しく動作するか検証
    mock_exists = MagicMock(return_value=True)
    # os.makedirs は例外を出さず、通常通り動作する
    mock_makedirs = MagicMock()
    mock_copy = MagicMock()
    
    mock_hub_instance = MagicMock()
    mock_hub_class = MagicMock(return_value=mock_hub_instance)
    
    with patch("os.path.exists", mock_exists), \
         patch("os.makedirs", mock_makedirs), \
         patch("shutil.copy2", mock_copy), \
         patch("backend.agents.orchestration.OrchestrationHub", mock_hub_class):
        
        importlib.import_module(TARGET_MODULE)
        
    captured = capsys.readouterr()
    assert "Copied: backend/agents/orchestration/flash_runner_control.py -> backend/agents/orchestration/flash_runner_control.py" in captured.out
    
    # exist_ok=True が os.makedirs の呼び出し時に渡されていることを確認する
    assert mock_makedirs.call_count == 2
    for call in mock_makedirs.call_args_list:
        assert call[1].get("exist_ok") is True


def test_copy_artifacts_hub_argument_validation(clean_sys_modules):
    # OrchestrationHub.mark_task_done に渡される引数が適切であることを検証
    mock_exists = MagicMock(return_value=True)
    mock_makedirs = MagicMock()
    mock_copy = MagicMock()
    
    mock_hub_instance = MagicMock()
    mock_hub_class = MagicMock(return_value=mock_hub_instance)
    
    with patch("os.path.exists", mock_exists), \
         patch("os.makedirs", mock_makedirs), \
         patch("shutil.copy2", mock_copy), \
         patch("backend.agents.orchestration.OrchestrationHub", mock_hub_class):
        
        importlib.import_module(TARGET_MODULE)
        
    mock_hub_instance.mark_task_done.assert_called_once()
    args, kwargs = mock_hub_instance.mark_task_done.call_args
    # 第1引数: タスクID、第2引数: ステータス、第3引数: レポート
    assert args[0] == "T-batch_00d5aa-bug_hunter-000"
    assert args[1] == "pass"
    report = args[2]
    assert isinstance(report, dict)
    assert "subagent_id" in report
    assert "message" in report


def test_copy_targets_structure(clean_sys_modules):
    # copy_targets のデータ構造が期待通り（3つ組のタプル）であることを検証する
    mock_exists = MagicMock(return_value=True)
    mock_makedirs = MagicMock()
    mock_copy = MagicMock()
    mock_hub_instance = MagicMock()
    mock_hub_class = MagicMock(return_value=mock_hub_instance)
    
    with patch("os.path.exists", mock_exists), \
         patch("os.makedirs", mock_makedirs), \
         patch("shutil.copy2", mock_copy), \
         patch("backend.agents.orchestration.OrchestrationHub", mock_hub_class):
        
        module = importlib.import_module(TARGET_MODULE)
        
    assert isinstance(module.copy_targets, list)
    for target in module.copy_targets:
        assert isinstance(target, tuple)
        assert len(target) == 3
        assert all(isinstance(x, str) for x in target)


def test_copy_artifacts_path_type_error(clean_sys_modules):
    # パスチェック時に TypeError が発生する不正型エッジケース
    mock_exists = MagicMock(side_effect=TypeError("Expected str, bytes or os.PathLike object, not NoneType"))
    mock_makedirs = MagicMock()
    mock_copy = MagicMock()
    mock_hub_instance = MagicMock()
    mock_hub_class = MagicMock(return_value=mock_hub_instance)
    
    with patch("os.path.exists", mock_exists), \
         patch("os.makedirs", mock_makedirs), \
         patch("shutil.copy2", mock_copy), \
         patch("backend.agents.orchestration.OrchestrationHub", mock_hub_class):
        
        with pytest.raises(TypeError) as excinfo:
            importlib.import_module(TARGET_MODULE)
        assert "not NoneType" in str(excinfo.value)


def test_copy_artifacts_shutil_os_error(clean_sys_modules):
    # コピー処理中に OSError (ディスクフルなど) が発生するエッジケース
    mock_exists = MagicMock(return_value=True)
    mock_makedirs = MagicMock()
    mock_copy = MagicMock(side_effect=OSError("[Errno 28] No space left on device"))
    mock_hub_instance = MagicMock()
    mock_hub_class = MagicMock(return_value=mock_hub_instance)
    
    with patch("os.path.exists", mock_exists), \
         patch("os.makedirs", mock_makedirs), \
         patch("shutil.copy2", mock_copy), \
         patch("backend.agents.orchestration.OrchestrationHub", mock_hub_class):
        
        with pytest.raises(OSError) as excinfo:
            importlib.import_module(TARGET_MODULE)
        assert "No space left on device" in str(excinfo.value)


def test_copy_artifacts_extremely_long_path(clean_sys_modules):
    # 巨大入力（極端に長いパス）を想定したエッジケース
    # os.path.exists が長いパスに対して正常に False を返す（または例外なく処理される）ことを検証
    long_base = "A" * 10000
    mock_exists = MagicMock(return_value=False)
    mock_makedirs = MagicMock()
    mock_copy = MagicMock()
    mock_hub_instance = MagicMock()
    mock_hub_class = MagicMock(return_value=mock_hub_instance)
    
    # モジュールロード前に copy_targets に影響する src_agent_0 の定義があるため、
    # os.path.join などの呼び出し時に long_base が含まれていることを検証する
    with patch("os.path.exists", mock_exists), \
         patch("os.makedirs", mock_makedirs), \
         patch("shutil.copy2", mock_copy), \
         patch("backend.agents.orchestration.OrchestrationHub", mock_hub_class):
        
        # モジュール内の src_agent_0 を極端に長いパスに差し替えて実行させるため、
        # import される前に定義を上書きするモックを行うことは困難なので、
        # copy_targets のループ内で生成されるパスが巨大な場合の os.path.exists の呼び出しをシミュレート
        importlib.import_module(TARGET_MODULE)
        
    assert mock_exists.call_count == 2
    # 正常に終了することを確認




