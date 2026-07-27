"""
CodeVerifier の単体テスト
"""

import os
import pytest
import subprocess
from unittest.mock import patch, MagicMock
from backend.agents.orchestration.verifier import CodeVerifier

@pytest.fixture
def temp_workspace(tmp_path):
    """一時ディレクトリをワークスペースとして提供するフィクスチャ"""
    return str(tmp_path)

def test_verify_static_success(temp_workspace):
    """静的チェックの正常系: except Exception がない場合"""
    verifier = CodeVerifier(workspace_path=temp_workspace)
    test_file = os.path.join(temp_workspace, "clean_code.py")
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("def dummy():\n    try:\n        pass\n    except ValueError:\n        pass\n")
    
    res = verifier.verify_static("clean_code.py")
    assert res["passed"] is True
    assert "errors" not in res or len(res["errors"]) == 0

def test_verify_static_fail_broad_exception(temp_workspace):
    """静的チェックの異常系: except Exception が含まれる場合"""
    verifier = CodeVerifier(workspace_path=temp_workspace)
    
    # パターン1: except Exception:
    test_file_1 = os.path.join(temp_workspace, "bad_code_1.py")
    with open(test_file_1, "w", encoding="utf-8") as f:
        f.write("def dummy():\n    try:\n        pass\n    except Exception:\n        pass\n")
    
    res1 = verifier.verify_static("bad_code_1.py")
    assert res1["passed"] is False
    assert any("Broad exception handler detected" in err for err in res1["errors"])

    # パターン2: except Exception as e
    test_file_2 = os.path.join(temp_workspace, "bad_code_2.py")
    with open(test_file_2, "w", encoding="utf-8") as f:
        f.write("def dummy():\n    try:\n        pass\n    except Exception as e:\n        pass\n")
    
    res2 = verifier.verify_static("bad_code_2.py")
    assert res2["passed"] is False
    assert any("Broad exception handler detected" in err for err in res2["errors"])

def test_verify_static_file_not_found(temp_workspace):
    """静的チェックの異常系: ファイルが存在しない場合"""
    verifier = CodeVerifier(workspace_path=temp_workspace)
    res = verifier.verify_static("non_existent.py")
    assert res["passed"] is False
    assert "File not found" in res["error"]

@patch("subprocess.run")
def test_verify_dynamic_success(mock_run, temp_workspace):
    """動的チェックの正常系: pytestが初回で成功する場合"""
    verifier = CodeVerifier(workspace_path=temp_workspace)
    mock_run.return_value = MagicMock(returncode=0, stdout="3 passed", stderr="")

    res = verifier.verify_dynamic("tests/test_clean.py")
    assert res["passed"] is True
    assert res["exit_code"] == 0
    assert "3 passed" in res["stdout"]
    assert mock_run.call_count == 1

@patch("subprocess.run")
def test_verify_dynamic_retry_on_timeout(mock_run, temp_workspace):
    """動的チェック of フォールバックパターン1: タイムアウト発生時に延長してリトライし成功する場合"""
    verifier = CodeVerifier(workspace_path=temp_workspace)
    
    # 1回目は TimeoutExpired 例外、2回目は成功 (returncode=0)
    mock_run.side_effect = [
        subprocess.TimeoutExpired(cmd="pytest", timeout=300),
        MagicMock(returncode=0, stdout="5 passed after retry", stderr="")
    ]

    res = verifier.verify_dynamic("tests/test_timeout.py")
    assert res["passed"] is True
    assert res["exit_code"] == 0
    assert "5 passed after retry" in res["stdout"]
    assert mock_run.call_count == 2
    # 2回目のタイムアウト値が600に延長されていることを確認
    _, kwargs = mock_run.call_args
    assert kwargs.get("timeout") == 600

@patch("subprocess.run")
def test_verify_dynamic_individual_retry(mock_run, temp_workspace):
    """動的チェック of フォールバックパターン2: 失敗テストファイルを特定し、個別に再実行して成功する場合"""
    verifier = CodeVerifier(workspace_path=temp_workspace)
    
    # 1回目は全体実行で失敗、stdout から失敗ファイルを抽出させる
    # 2回目・3回目は個別実行で成功
    first_stdout = (
        "=========================== FAILURES ===========================\n"
        "FAILED tests/test_fail1.py::test_a - AssertionError\n"
        "FAILED tests/test_fail2.py::test_b - AssertionError\n"
    )
    mock_run.side_effect = [
        MagicMock(returncode=1, stdout=first_stdout, stderr=""),
        MagicMock(returncode=0, stdout="test_fail1 passed", stderr=""),
        MagicMock(returncode=0, stdout="test_fail2 passed", stderr="")
    ]

    res = verifier.verify_dynamic("tests/")
    assert res["passed"] is True
    assert res["exit_code"] == 0
    assert "test_fail1 passed" in res["stdout"]
    assert "test_fail2 passed" in res["stdout"]
    assert mock_run.call_count == 3

@patch("subprocess.run")
def test_verify_dynamic_total_failure_with_rollback(mock_run, temp_workspace):
    """動的チェック of フォールバックパターン3: 個別再実行も失敗し、最終的にロールバックと指示書生成が行われる場合"""
    verifier = CodeVerifier(workspace_path=temp_workspace)
    
    first_stdout = (
        "FAILED tests/test_fail1.py::test_a - AssertionError\n"
    )
    # 1回目全体失敗、2回目個別失敗
    mock_run.side_effect = [
        MagicMock(returncode=1, stdout=first_stdout, stderr=""),
        MagicMock(returncode=1, stdout="test_fail1 failed again", stderr=""),
    ]

    with patch.dict(os.environ, {"PYTEST_CURRENT_TEST": "true"}):
        res = verifier.verify_dynamic("tests/")
    
    assert res["passed"] is False
    assert res["rollback_executed"] is True
    assert "alternative_approach_instructions" in res
    # 指示書が scratch ディレクトリに作成されたか確認
    instruction_file = os.path.join(temp_workspace, "scratch", "alternative_approach_test_suite.txt")
    assert os.path.exists(instruction_file)
    with open(instruction_file, "r", encoding="utf-8") as f:
        content = f.read()
        assert "【代替アプローチ指示書 - tests/】" in content
        assert "Assertion" in content or "assertion" in content.lower()


def test_verify_self_static():
    """verifier.py 自体に対する静的チェックを検証する（修正前は except Exception が含まれるため失敗する）"""
    verifier = CodeVerifier()
    res = verifier.verify_static("backend/agents/orchestration/verifier.py")
    assert res["passed"] is True


def test_verify_static_read_error(temp_workspace):
    """静的チェックの異常系: ファイル読み込みエラー(OSError)が発生した場合"""
    verifier = CodeVerifier(workspace_path=temp_workspace)
    test_file = os.path.join(temp_workspace, "read_error_code.py")
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("def dummy(): pass\n")
    
    with patch("builtins.open", side_effect=OSError("Permission denied")):
        res = verifier.verify_static("read_error_code.py")
    
    assert res["passed"] is False
    assert "File read or parse error" in res["error"]


@patch("subprocess.run")
def test_run_pytest_subprocess_error(mock_run, temp_workspace):
    """動的チェックの異常系: subprocess実行時にOSErrorが発生した場合"""
    verifier = CodeVerifier(workspace_path=temp_workspace)
    mock_run.side_effect = OSError("Subprocess failed to start")
    
    res = verifier.verify_dynamic("tests/test_dummy.py")
    assert res["passed"] is False
    assert "Test execution failed" in res["error"]


@patch("subprocess.run")
def test_execute_git_rollback_success_and_fail(mock_run, temp_workspace):
    """Gitロールバックの実処理とエラーハンドリングを検証する"""
    verifier = CodeVerifier(workspace_path=temp_workspace)
    
    env_mock = os.environ.copy()
    if "PYTEST_CURRENT_TEST" in env_mock:
        del env_mock["PYTEST_CURRENT_TEST"]
        
    with patch.dict(os.environ, env_mock, clear=True):
        # 1. 成功ケース
        mock_run.return_value = MagicMock(returncode=0)
        success, err = verifier._execute_git_rollback()
        assert success is True
        assert err is None
        assert mock_run.call_count == 2
        mock_run.assert_any_call(["git", "reset", "--hard", "HEAD"], cwd=temp_workspace, capture_output=True, text=True, check=True)
        mock_run.assert_any_call(["git", "clean", "-fd"], cwd=temp_workspace, capture_output=True, text=True, check=True)
        
        # 2. 失敗ケース (subprocess.SubprocessError)
        mock_run.reset_mock()
        mock_run.side_effect = subprocess.SubprocessError("git reset failed")
        success, err = verifier._execute_git_rollback()
        assert success is False
        assert "git reset failed" in err


def test_generate_alternative_instructions_variants(temp_workspace):
    """代替指示書生成の各アドバイス切り替え分岐を検証する"""
    verifier = CodeVerifier(workspace_path=temp_workspace)
    
    # タイムアウト分岐
    res_timeout = {"passed": False, "stdout": "Test timeout occurred", "error": "timeout"}
    inst1 = verifier._generate_alternative_instructions("test_path", res_timeout)
    assert "タイムアウト時の代替アプローチ" in inst1
    
    # インポートエラー分岐
    res_import = {"passed": False, "stdout": "ModuleNotFoundError: No module named foo", "stderr": "import error"}
    inst2 = verifier._generate_alternative_instructions("test_path", res_import)
    assert "インポートエラー時の代替アプローチ" in inst2


def test_save_alternative_instructions_io_error(temp_workspace):
    """指示書保存時にOSErrorが発生した場合のエラーハンドリングを検証する"""
    verifier = CodeVerifier(workspace_path=temp_workspace)
    
    with patch("builtins.open", side_effect=OSError("Read-only file system")):
        verifier._save_alternative_instructions("dummy instructions")


