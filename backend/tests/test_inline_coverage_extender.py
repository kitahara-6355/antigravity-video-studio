import ast
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from agents.orchestration.inline_coverage_extender import InlineCoverageExtender


class TestInlineCoverageExtender(unittest.TestCase):
    def setUp(self):
        # テスト用の一時ディレクトリとファイルパスの作成
        self.test_dir = tempfile.mkdtemp()
        self.test_file_path = os.path.join(self.test_dir, "test_dummy.py")
        self.extender = InlineCoverageExtender(self.test_file_path)

    def tearDown(self):
        # 一時ディレクトリの削除
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_add_test_function_new_file(self):
        # 1. 存在しないファイルに対してテスト関数を追加
        func_code = (
            "def test_hello():\n"
            "    assert 1 == 1\n"
        )
        result = self.extender.add_test_function("test_hello", func_code)
        self.assertTrue(result)
        self.assertTrue(os.path.exists(self.test_file_path))

        with open(self.test_file_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content.strip(), func_code.strip())

    def test_add_test_function_existing_file(self):
        # 2. 既存のファイルに対してテスト関数を追記
        initial_code = (
            "def test_first():\n"
            "    assert True\n"
        )
        with open(self.test_file_path, "w", encoding="utf-8") as f:
            f.write(initial_code)

        new_func_code = (
            "def test_second():\n"
            "    assert 1 + 1 == 2\n"
        )
        result = self.extender.add_test_function("test_second", new_func_code)
        self.assertTrue(result)

        with open(self.test_file_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("test_first", content)
        self.assertIn("test_second", content)
        # 末尾に正しく追加されたか確認
        self.assertTrue(content.endswith("def test_second():\n    assert 1 + 1 == 2\n"))

    def test_add_test_function_duplicate(self):
        # 3. 重複した関数名が指定された場合のガード
        initial_code = (
            "def test_duplicate():\n"
            "    assert True\n"
        )
        with open(self.test_file_path, "w", encoding="utf-8") as f:
            f.write(initial_code)

        new_func_code = (
            "def test_duplicate():\n"
            "    assert False\n"
        )
        with self.assertRaises(ValueError) as ctx:
            self.extender.add_test_function("test_duplicate", new_func_code)
        self.assertIn("already exists", str(ctx.exception))

    def test_add_test_method_to_class(self):
        # 4. 既存のクラスに対してテストメソッドを追加
        initial_code = (
            "class TestSuite:\n"
            "    def test_one(self):\n"
            "        assert 1 == 1\n"
        )
        with open(self.test_file_path, "w", encoding="utf-8") as f:
            f.write(initial_code)

        method_code = (
            "def test_two(self):\n"
            "    assert 2 == 2"
        )
        result = self.extender.add_test_method("TestSuite", "test_two", method_code)
        self.assertTrue(result)

        with open(self.test_file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # インデントが正しく付与されて追加されたか確認
        expected_method = (
            "    def test_two(self):\n"
            "        assert 2 == 2"
        )
        self.assertIn(expected_method, content)

    def test_add_test_method_duplicate(self):
        # 5. 重複したメソッド名がクラス内で指定された場合のガード
        initial_code = (
            "class TestSuite:\n"
            "    def test_dup(self):\n"
            "        assert True\n"
        )
        with open(self.test_file_path, "w", encoding="utf-8") as f:
            f.write(initial_code)

        method_code = (
            "def test_dup(self):\n"
            "    assert False"
        )
        with self.assertRaises(ValueError) as ctx:
            self.extender.add_test_method("TestSuite", "test_dup", method_code)
        self.assertIn("already exists in class", str(ctx.exception))

    def test_add_test_method_class_not_found(self):
        # 6. 存在しないクラスを指定した場合の例外
        initial_code = (
            "class TestSuite:\n"
            "    def test_one(self):\n"
            "        assert True\n"
        )
        with open(self.test_file_path, "w", encoding="utf-8") as f:
            f.write(initial_code)

        method_code = (
            "def test_two(self):\n"
            "    assert True"
        )
        with self.assertRaises(ValueError) as ctx:
            self.extender.add_test_method("TestNonExistent", "test_two", method_code)
        self.assertIn("not found in the file", str(ctx.exception))

    def test_add_invalid_syntax_code(self):
        # 7. 不正な構文（SyntaxError）を検知し、ロールバックされるか確認
        initial_code = (
            "def test_ok():\n"
            "    assert True\n"
        )
        with open(self.test_file_path, "w", encoding="utf-8") as f:
            f.write(initial_code)

        invalid_code = (
            "def test_bad()\n"  # コロンがないため構文エラー
            "    assert True\n"
        )
        with self.assertRaises(ValueError) as ctx:
            self.extender.add_test_function("test_bad", invalid_code)
        self.assertIn("syntax error", str(ctx.exception).lower())

        # ファイルが変更されていない（ロールバックされている）ことを確認
        with open(self.test_file_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content, initial_code)

    def test_utf8_encoding_japanese(self):
        # 8. 日本語コメントなど非ASCII文字が含まれていても正しく処理されるか
        func_code = (
            "def test_japanese():\n"
            "    # 日本語のコメントテスト\n"
            "    assert '日本語' == '日本語'\n"
        )
        result = self.extender.add_test_function("test_japanese", func_code)
        self.assertTrue(result)

        with open(self.test_file_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("日本語のコメントテスト", content)

    def test_write_atomic_failure_rollback(self):
        # 9. 書き込みエラー時にバックアップから自動ロールバックされることを確認
        initial_code = (
            "def test_base():\n"
            "    assert True\n"
        )
        with open(self.test_file_path, "w", encoding="utf-8") as f:
            f.write(initial_code)

        # _write_atomic が例外を投げるようにモック化
        with patch.object(self.extender, "_write_atomic", side_effect=IOError("Disk Full")):
            with self.assertRaises(ValueError) as ctx:
                self.extender.add_test_function(
                    "test_new",
                    "def test_new():\n    assert True\n"
                )
            self.assertIn("Disk Full", str(ctx.exception))

        # ファイルがロールバックされており、元の状態に維持されていることを確認
        with open(self.test_file_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content, initial_code)

    # --- 追加された未カバー行用テストケース ---

    def test_write_atomic_cleanup_on_replace_failure(self):
        # os.replace が失敗したとき、_write_atomic 内部で一時ファイルが正しくクリーンアップされるか検証
        initial_code = "def test_ok(): assert True"
        with open(self.test_file_path, "w", encoding="utf-8") as f:
            f.write(initial_code)

        # os.replace で例外を発生させる
        with patch("os.replace", side_effect=OSError("Replace Failed")):
            # _write_atomic は内部例外を再スローするため、例外が発生する
            with self.assertRaises(OSError):
                self.extender._write_atomic("new code")

    def test_write_atomic_cleanup_unlink_error_ignored(self):
        # os.replace が失敗し、さらに os.unlink が失敗した時に、OSError が無視されることを検証 (76-77行)
        initial_code = "def test_ok(): assert True"
        with open(self.test_file_path, "w", encoding="utf-8") as f:
            f.write(initial_code)

        with patch("os.replace", side_effect=OSError("Replace Failed")):
            with patch("os.unlink", side_effect=OSError("Unlink Failed")):
                with self.assertRaises(OSError):
                    self.extender._write_atomic("new code")

    def test_add_test_function_existing_file_syntax_error(self):
        # 既存ファイルに構文エラーがある場合の add_test_function のエラーハンドリング (104-105行)
        invalid_existing_code = "def test_bad_existing("  # 不完全な構文
        with open(self.test_file_path, "w", encoding="utf-8") as f:
            f.write(invalid_existing_code)

        with self.assertRaises(ValueError) as ctx:
            self.extender.add_test_function("test_new", "def test_new(): pass")
        self.assertIn("Existing test file has a syntax error", str(ctx.exception))

    def test_add_test_method_existing_file_syntax_error(self):
        # 既存ファイルに構文エラーがある場合の add_test_method のエラーハンドリング (168-169行)
        invalid_existing_code = "class TestSuite:\n    def test_bad("
        with open(self.test_file_path, "w", encoding="utf-8") as f:
            f.write(invalid_existing_code)

        with self.assertRaises(ValueError) as ctx:
            self.extender.add_test_method("TestSuite", "test_new", "def test_new(): pass")
        self.assertIn("Existing test file has a syntax error", str(ctx.exception))

    def test_add_test_function_existing_file_empty(self):
        # ファイルは存在するが、中身が空の場合の add_test_function の動作 (117行)
        with open(self.test_file_path, "w", encoding="utf-8") as f:
            f.write("   \n  ")  # 空白のみのファイル

        func_code = "def test_empty(): pass"
        result = self.extender.add_test_function("test_empty", func_code)
        self.assertTrue(result)

        with open(self.test_file_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content.strip(), func_code)

    def test_remove_backup_os_error_ignored(self):
        # finally ブロックでの os.remove(bak_path) 時の OSError が無視されることを確認 (138-139行)
        initial_code = "def test_ok(): assert True"
        with open(self.test_file_path, "w", encoding="utf-8") as f:
            f.write(initial_code)

        # os.remove が OSError を投げるようにモックする
        with patch("os.remove", side_effect=OSError("Permission Denied")):
            # 正常に終了するはず（例外は無視される）
            result = self.extender.add_test_function("test_another", "def test_another(): pass")
            self.assertTrue(result)

    def test_add_test_method_file_not_exist_or_empty(self):
        # ファイルが存在しない（または空）状態で add_test_method を呼び出したときのエラーハンドリング (163行)
        # ファイルが存在しないケース
        with self.assertRaises(ValueError) as ctx:
            self.extender.add_test_method("TestSuite", "test_new", "def test_new(): pass")
        self.assertIn("Target file does not exist or is empty", str(ctx.exception))

        # ファイルが空のケース
        with open(self.test_file_path, "w", encoding="utf-8") as f:
            f.write("")
        with self.assertRaises(ValueError) as ctx:
            self.extender.add_test_method("TestSuite", "test_new", "def test_new(): pass")
        self.assertIn("Target file does not exist or is empty", str(ctx.exception))

    def test_add_test_method_code_body_with_empty_lines(self):
        # 追加するメソッドコードに空行が含まれている場合の動作 (201行)
        initial_code = (
            "class TestSuite:\n"
            "    def test_one(self):\n"
            "        assert True\n"
        )
        with open(self.test_file_path, "w", encoding="utf-8") as f:
            f.write(initial_code)

        method_code = (
            "def test_two(self):\n"
            "\n"  # 空行
            "    assert True"
        )
        result = self.extender.add_test_method("TestSuite", "test_two", method_code)
        self.assertTrue(result)

        with open(self.test_file_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("    def test_two(self):\n\n        assert True", content)

    def test_add_test_method_class_body_empty_fallback_indent(self):
        # class_node.body が空である場合のフォールバックインデント (201行)
        # AST上で class_node.body が空である特殊な状況をモックでシミュレートする
        initial_code = "class EmptyClass:\n    pass"
        with open(self.test_file_path, "w", encoding="utf-8") as f:
            f.write(initial_code)

        # ast.parse をモックして、ClassDef の body を空リストにする
        original_ast_parse = ast.parse

        def mock_ast_parse(source, *args, **kwargs):
            tree = original_ast_parse(source, *args, **kwargs)
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.ClassDef) and node.name == "EmptyClass":
                    node.body = []  # bodyを空にする
            return tree

        with patch("ast.parse", side_effect=mock_ast_parse):
            # モックされたパースにより、body が空の状態でインデント幅が決定される
            result = self.extender.add_test_method("EmptyClass", "test_new", "def test_new(self): pass")
            self.assertTrue(result)

        with open(self.test_file_path, "r", encoding="utf-8") as f:
            content = f.read()
        # デフォルトで 4スペースインデントされるはず
        self.assertIn("    def test_new(self): pass", content)

    def test_add_test_method_insert_line_out_of_bounds(self):
        # insert_line_idx > len(lines) の場合の安全策 (214行)
        initial_code = "class TestSuite:\n    def test_one(self): pass"
        with open(self.test_file_path, "w", encoding="utf-8") as f:
            f.write(initial_code)

        # ast.parse をモックして、TestSuite 内の FunctionDef の end_lineno を巨大な値にする
        original_ast_parse = ast.parse

        def mock_ast_parse(source, *args, **kwargs):
            tree = original_ast_parse(source, *args, **kwargs)
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.ClassDef) and node.name == "TestSuite":
                    for sub in node.body:
                        if isinstance(sub, ast.FunctionDef):
                            sub.end_lineno = 9999  # 巨大な行数
            return tree

        with patch("ast.parse", side_effect=mock_ast_parse):
            result = self.extender.add_test_method("TestSuite", "test_new", "def test_new(self): pass")
            self.assertTrue(result)

    def test_add_test_method_write_failure_rollback(self):
        # add_test_method 中に _write_atomic が失敗したときの例外処理とロールバック (233-236行)
        initial_code = "class TestSuite:\n    def test_one(self): pass"
        with open(self.test_file_path, "w", encoding="utf-8") as f:
            f.write(initial_code)

        with patch.object(self.extender, "_write_atomic", side_effect=IOError("Disk Full")):
            with self.assertRaises(ValueError) as ctx:
                self.extender.add_test_method("TestSuite", "test_new", "def test_new(self): pass")
            self.assertIn("Disk Full", str(ctx.exception))

        with open(self.test_file_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content, initial_code)

    def test_add_test_method_remove_backup_os_error_ignored(self):
        # add_test_method における os.remove(bak_path) 時の OSError が無視されることを確認 (241-242行)
        initial_code = "class TestSuite:\n    def test_one(self): pass"
        with open(self.test_file_path, "w", encoding="utf-8") as f:
            f.write(initial_code)

        with patch("os.remove", side_effect=OSError("Permission Denied")):
            result = self.extender.add_test_method("TestSuite", "test_new", "def test_new(self): pass")
            self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
