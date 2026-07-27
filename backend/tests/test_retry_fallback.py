import os
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock, mock_open
import pytest

from backend.agents.orchestration.verifier import CodeVerifier

class TestRetryFallback(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.verifier = CodeVerifier(workspace_path=self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("subprocess.run")
    def test_timeout_extension_retry_success(self, mock_run):
        # 1回目の実行はタイムアウト (TimeoutExpired または returncode 非0でtimeoutを含む出力)
        # 2回目の延長実行で成功するケースをシミュレート
        first_res = MagicMock()
        first_res.returncode = 1
        first_res.stdout = "Test timed out during execution"
        first_res.stderr = ""

        second_res = MagicMock()
        second_res.returncode = 0
        second_res.stdout = "All tests passed after retry"
        second_res.stderr = ""

        mock_run.side_effect = [first_res, second_res]

        res = self.verifier.verify_dynamic("dummy_test.py")

        # 2回実行され、結果的に合格することを確認
        self.assertEqual(mock_run.call_count, 2)
        self.assertTrue(res["passed"])
        
        # 2回目のコマンドにタイムアウト延長や詳細表示(-vv)などの調整が含まれているか確認
        args_first = mock_run.call_args_list[0][0][0]
        args_second = mock_run.call_args_list[1][0][0]
        self.assertIn("300", args_first)
        self.assertIn("600", args_second)
        self.assertIn("-vv", args_second)

    @patch("subprocess.run")
    def test_granular_execution_retry_success(self, mock_run):
        # 全体テスト実行が失敗し、特定のテストファイルが失敗したログが出力されるケース
        # その後、失敗した個別テストを再実行して成功する
        overall_res = MagicMock()
        overall_res.returncode = 1
        # pytest 失敗時の出力例をシミュレート
        overall_res.stdout = """
============================= FAILURES =============================
___________________________ test_something ___________________________
def test_something():
>       assert False
E       AssertionError
FAILED backend/tests/test_target_file.py::test_something
FAILED backend/tests/test_another_file.py::test_another
===================== 2 failed, 98 passed in 10s =====================
"""
        overall_res.stderr = ""

        # 個別実行（2つの失敗テストファイル）でそれぞれ成功する
        sub_res1 = MagicMock()
        sub_res1.returncode = 0
        sub_res1.stdout = "PASSED"
        sub_res1.stderr = ""

        sub_res2 = MagicMock()
        sub_res2.returncode = 0
        sub_res2.stdout = "PASSED"
        sub_res2.stderr = ""

        mock_run.side_effect = [overall_res, sub_res1, sub_res2]

        res = self.verifier.verify_dynamic("backend/tests/")

        # 全体実行(1回) + 個別実行(2回) = 計3回実行され、結果合格となること
        self.assertEqual(mock_run.call_count, 3)
        self.assertTrue(res["passed"])

        # 呼び出された個別ファイル名が正しいか検証
        called_cmds = [call[0][0] for call in mock_run.call_args_list]
        self.assertIn("backend/tests/test_target_file.py", called_cmds[1])
        self.assertIn("backend/tests/test_another_file.py", called_cmds[2])

    @patch("subprocess.run")
    def test_fallback_git_rollback_and_instruction(self, mock_run):
        # すべてのリトライが失敗し、Gitロールバックと指示書生成が発生するケース
        fail_res = MagicMock()
        fail_res.returncode = 1
        fail_res.stdout = "FAILED backend/tests/test_fatal.py::test_fatal"
        fail_res.stderr = "Fatal error"

        # 1回目(全体) + 2回目(タイムアウト延長) + 3回目(個別テストリトライ)
        # すべて失敗とする
        mock_run.side_effect = [fail_res, fail_res, fail_res]

        # scratch ディレクトリをモック環境内に作成
        scratch_dir = os.path.join(self.temp_dir, "scratch")
        os.makedirs(scratch_dir, exist_ok=True)

        # git ロールバックコマンドのモック（実際のgitコマンドは実行しない）
        # verify_dynamic 内部で git コマンドも subprocess.run で実行されるはずなので、
        # side_effect の数を合わせるか、特定のコマンド名に応じてモックする
        # ここでは subprocess.run の mock 動作をコマンド名で振り分けるように定義し直す
        def side_effect_func(cmd, *args, **kwargs):
            res = MagicMock()
            if "git" in cmd:
                res.returncode = 0
                res.stdout = "Git command executed"
                res.stderr = ""
            else:
                res.returncode = 1
                res.stdout = "FAILED backend/tests/test_fatal.py::test_fatal"
                res.stderr = "Fatal error"
            return res

        mock_run.side_effect = side_effect_func

        res = self.verifier.verify_dynamic("backend/tests/test_fatal.py")

        # 合格していないこと
        self.assertFalse(res["passed"])
        # ロールバックが実行されたことを示すメタデータが含まれるか
        self.assertTrue(res.get("rollback_executed", False))
        
        # 代替アプローチ指示書が scratch/ ディレクトリに書き出されているか検証
        instruction_file = os.path.join(scratch_dir, "alternative_approach_test_suite.txt")
        self.assertTrue(os.path.exists(instruction_file))
        
        with open(instruction_file, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("test_fatal.py", content)
            self.assertIn("Fatal error", content)
            self.assertIn("代替アプローチ指示書", content)
