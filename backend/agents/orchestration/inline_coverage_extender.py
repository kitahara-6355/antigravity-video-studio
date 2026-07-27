"""
DS-022: カバレッジ98%達成テストのインライン展開
テストカバレッジ向上のためのテスト関数自動追加（テストテンプレート生成・追記）の安全なI/O実装。
"""

import ast
import os
import shutil
import tempfile
from typing import Optional


class InlineCoverageExtender:
    def __init__(self, test_file_path: str):
        """
        Args:
            test_file_path: 追記・挿入対象のテストファイルパス
        """
        self.test_file_path = os.path.abspath(test_file_path)

    def _read_file(self) -> str:
        """テストファイルの内容をUTF-8で読み込む。存在しない場合は空文字列を返す。"""
        if not os.path.exists(self.test_file_path):
            return ""
        with open(self.test_file_path, "r", encoding="utf-8") as f:
            return f.read()

    def _verify_syntax(self, content: str) -> None:
        """指定されたコンテンツが有効なPythonコードかAST解析で検証する。"""
        try:
            ast.parse(content)
        except SyntaxError as e:
            raise ValueError(f"Generated code results in a syntax error: {e}")

    def _create_backup(self) -> Optional[str]:
        """既存ファイルのバックアップを作成し、バックアップファイルのパスを返す。"""
        if os.path.exists(self.test_file_path):
            bak_path = self.test_file_path + ".bak"
            shutil.copy2(self.test_file_path, bak_path)
            return bak_path
        return None

    def _restore_backup(self, bak_path: str) -> None:
        """バックアップファイルから元のファイルを復元する。"""
        if os.path.exists(bak_path):
            shutil.copy2(bak_path, self.test_file_path)

    def _write_atomic(self, content: str) -> None:
        """
        一時ファイルを使用してアトミックにファイル書き換えを行う。
        ファイルI/O安全規約に則り、UTF-8で書き込む。
        """
        dir_name = os.path.dirname(self.test_file_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(
            suffix=".tmp",
            prefix=os.path.basename(self.test_file_path) + ".",
            dir=dir_name if dir_name else None,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.test_file_path)
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            raise

    def add_test_function(self, func_name: str, code_body: str) -> bool:
        """
        テストファイルの末尾にテスト関数を追加する。

        Args:
            func_name: 追加するテスト関数名
            code_body: 追加するテスト関数のソースコード (インデントのない状態)

        Returns:
            成功した場合は True

        Raises:
            ValueError: 構文エラーや重複が検知された場合
        """
        # 1. 構文チェック（追加するコード単体）
        self._verify_syntax(code_body)

        content = self._read_file()
        bak_path = None

        if content:
            # 2. 重複チェック
            try:
                tree = ast.parse(content)
            except SyntaxError as e:
                raise ValueError(f"Existing test file has a syntax error, aborting: {e}")

            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.FunctionDef) and node.name == func_name:
                    raise ValueError(f"Test function '{func_name}' already exists in the file.")

            # 3. 末尾に追記
            # 末尾の空行を調整
            content_stripped = content.rstrip()
            if content_stripped:
                new_content = content_stripped + "\n\n\n" + code_body.strip() + "\n"
            else:
                new_content = code_body.strip() + "\n"
        else:
            # 新規ファイル作成
            new_content = code_body.strip() + "\n"

        # 4. 全体の構文チェック
        self._verify_syntax(new_content)

        # 5. 安全な書き込み
        bak_path = self._create_backup()
        try:
            self._write_atomic(new_content)
            return True
        except Exception as e:
            if bak_path:
                self._restore_backup(bak_path)
            raise ValueError(f"Failed to write extended test file: {e}")
        finally:
            if bak_path and os.path.exists(bak_path):
                try:
                    os.remove(bak_path)
                except OSError:
                    pass

    def add_test_method(self, class_name: str, method_name: str, code_body: str) -> bool:
        """
        テストファイル内の指定されたテストクラスにテストメソッドを追加する。

        Args:
            class_name: 対象のテストクラス名
            method_name: 追加するテストメソッド名
            code_body: 追加するテストメソッドのソースコード（クラス内のインデントなし、def test_... から始まる）

        Returns:
            成功した場合は True

        Raises:
            ValueError: クラスが存在しない、メソッドが重複している、または構文エラーが検知された場合
        """
        # 1. 構文チェック（追加するコード単体）
        # クラスメソッドとしてパースするためにダミーのクラスで囲む
        dummy_class_code = f"class Dummy:\n" + "\n".join(f"    {line}" for line in code_body.splitlines())
        self._verify_syntax(dummy_class_code)

        content = self._read_file()
        if not content:
            raise ValueError(f"Target file does not exist or is empty, cannot add method to class '{class_name}'.")

        # 2. 既存ファイルのAST解析
        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            raise ValueError(f"Existing test file has a syntax error, aborting: {e}")

        class_node = None
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                class_node = node
                break

        if not class_node:
            raise ValueError(f"Target test class '{class_name}' not found in the file.")

        # 3. クラス内のメソッド重複チェック
        for sub_node in ast.iter_child_nodes(class_node):
            if isinstance(sub_node, ast.FunctionDef) and sub_node.name == method_name:
                raise ValueError(f"Method '{method_name}' already exists in class '{class_name}'.")

        # 4. インデントと挿入位置の決定
        # クラスのインデント幅を決定する
        # 最初の子要素の col_offset を基準にし、無ければデフォルトで4スペース
        indent_size = 4
        if class_node.body:
            first_child = class_node.body[0]
            indent_size = first_child.col_offset

        indent_str = " " * indent_size

        # インデントを付与して挿入用コードを生成
        indented_lines = []
        for line in code_body.splitlines():
            if line.strip():
                indented_lines.append(indent_str + line)
            else:
                indented_lines.append("")
        indented_code = "\n".join(indented_lines)

        # 挿入行の特定
        # 最後のノードの end_lineno を取得、無ければクラス定義ノードの end_lineno を使用
        if class_node.body:
            last_child = class_node.body[-1]
            insert_line_idx = last_child.end_lineno  # 1-indexed
        else:
            insert_line_idx = class_node.end_lineno

        # ファイルを行単位に分割
        lines = content.splitlines()

        # 安全対策：指定された行番号がファイル範囲内か確認
        if insert_line_idx > len(lines):
            insert_line_idx = len(lines)

        # 挿入位置より前と後に分割して結合
        # メソッドの前に空行を1行挟む
        before_part = lines[:insert_line_idx]
        after_part = lines[insert_line_idx:]

        # 結合処理
        # 前のパートの末尾に空行を追加し、その後にインデント済みコードを追加
        new_content = "\n".join(before_part) + "\n\n" + indented_code + "\n" + "\n".join(after_part)

        # 5. 全体の構文チェック
        self._verify_syntax(new_content)

        # 6. 安全な書き込み
        bak_path = self._create_backup()
        try:
            self._write_atomic(new_content)
            return True
        except Exception as e:
            if bak_path:
                self._restore_backup(bak_path)
            raise ValueError(f"Failed to write extended test file: {e}")
        finally:
            if bak_path and os.path.exists(bak_path):
                try:
                    os.remove(bak_path)
                except OSError:
                    pass
