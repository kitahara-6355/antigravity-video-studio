"""
DS-035: モック自動生成エンジン

依存クラスをAST解析で抽出し、MagicMock/patchを使ったモックテストコードを自動生成する。
既存の ASTTestGenerator (DS-034) をコンポジションで利用。

機能:
1. 関数/メソッド内部の外部依存呼び出しをAST走査で検出
2. __init__ の self.xxx = YYY パターンから属性→型マッピングを構築
3. @patch デコレータ + MagicMock 設定のテストコードを生成
4. subprocess.Popen 検出時は safe_popen_mock fixture を自動挿入 (GEMINI.md規約)
5. InlineCoverageExtender 経由の安全なファイル書き込み
"""

import ast
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any

import logging

logger = logging.getLogger(__name__)

# stdlib モジュール一覧（主要なもの）
STDLIB_MODULES = frozenset({
    "os", "sys", "json", "re", "math", "datetime", "time", "pathlib",
    "subprocess", "tempfile", "shutil", "io", "collections", "itertools",
    "functools", "typing", "abc", "copy", "hashlib", "hmac", "logging",
    "unittest", "threading", "multiprocessing", "socket", "http",
    "urllib", "email", "csv", "sqlite3", "xml", "html", "argparse",
    "configparser", "secrets", "uuid", "enum", "dataclasses", "contextlib",
    "textwrap", "string", "struct", "codecs", "base64", "glob",
    "fnmatch", "stat", "signal", "traceback", "warnings", "inspect",
    "ast", "dis", "pdb", "profile", "pstats",
})


@dataclass
class DependencyCall:
    """関数内で検出された外部依存呼び出し"""
    module_path: str
    class_or_func: str
    method_name: Optional[str]
    is_stdlib: bool
    patch_target: str


@dataclass
class DependencyMap:
    """モジュール全体の依存関係マップ"""
    function_deps: Dict[str, List[DependencyCall]] = field(default_factory=dict)
    class_method_deps: Dict[str, Dict[str, List[DependencyCall]]] = field(default_factory=dict)
    init_assignments: Dict[str, Dict[str, str]] = field(default_factory=dict)


class MockTestGenerator:
    """
    依存クラスをAST解析で抽出し、MagicMock/patchを使った
    モックテストコードを自動生成するエンジン。

    使い方:
        gen = MockTestGenerator()
        tree = ast.parse(source_code)
        dep_map = gen.analyze_dependencies_from_tree(tree, module_name, imports)
        test_code = gen.generate_mock_tests_from_tree(tree, module_name, dep_map)
    """

    # テスト生成から除外するメソッド名
    SKIP_METHODS = {"__init__", "__repr__", "__str__", "__eq__", "__hash__",
                    "__lt__", "__le__", "__gt__", "__ge__", "__ne__",
                    "__enter__", "__exit__", "__aenter__", "__aexit__"}

    SKIP_FUNCTIONS = {"main", "setup_logging", "configure"}

    def __init__(self):
        pass

    # =========================================================================
    # 依存関係抽出
    # =========================================================================

    def analyze_dependencies_from_tree(
        self,
        tree: ast.AST,
        module_name: str,
        imports: List[str],
    ) -> DependencyMap:
        """
        ASTツリーから依存関係を抽出する。

        Args:
            tree: ast.parse() の結果
            module_name: モジュールのドット区切り名（例: "backend.services.foo"）
            imports: モジュール内のインポート一覧

        Returns:
            DependencyMap: 関数/メソッドごとの依存呼び出しマップ
        """
        dep_map = DependencyMap()

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                class_name = node.name
                dep_map.class_method_deps[class_name] = {}
                # __init__ の self 属性を解析
                attrs = self._resolve_self_attributes(node)
                dep_map.init_assignments[class_name] = attrs

                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if item.name in self.SKIP_METHODS:
                            continue
                        deps = self._scan_function_body(
                            item, imports, attrs, module_name,
                        )
                        if deps:
                            dep_map.class_method_deps[class_name][item.name] = deps

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in self.SKIP_FUNCTIONS or node.name.startswith("_"):
                    continue
                deps = self._scan_function_body(
                    node, imports, {}, module_name,
                )
                if deps:
                    dep_map.function_deps[node.name] = deps

        return dep_map

    def _resolve_self_attributes(self, class_node: ast.ClassDef) -> Dict[str, str]:
        """
        __init__ 内の self.xxx = yyy パターンから
        属性名 → 型ヒント（またはクラス名）のマッピングを構築する。

        リテラル代入（self.cache = {}）は除外。
        """
        attrs = {}

        init_node = None
        for item in class_node.body:
            if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                init_node = item
                break

        if init_node is None:
            return attrs

        # 引数の型ヒントを収集
        arg_types = {}
        for arg in init_node.args.args:
            if arg.arg in ("self", "cls"):
                continue
            if arg.annotation:
                try:
                    arg_types[arg.arg] = ast.unparse(arg.annotation)
                except (ValueError, TypeError, AttributeError):
                    pass

        # self.xxx = yyy の解析
        for stmt in ast.walk(init_node):
            if not isinstance(stmt, ast.Assign):
                continue
            for target in stmt.targets:
                if not isinstance(target, ast.Attribute):
                    continue
                if not isinstance(target.value, ast.Name):
                    continue
                if target.value.id != "self":
                    continue

                attr_name = target.attr
                value = stmt.value

                # リテラル代入は除外 (self.cache = {}, self.count = 0 等)
                if isinstance(value, (ast.Constant, ast.Dict, ast.List,
                                     ast.Set, ast.Tuple)):
                    continue

                # self.xxx = xxx (引数からの代入) → 型ヒントを参照
                if isinstance(value, ast.Name) and value.id in arg_types:
                    attrs[attr_name] = arg_types[value.id]
                elif isinstance(value, ast.Call):
                    # self.xxx = SomeClass() 形式
                    try:
                        call_name = ast.unparse(value.func)
                        attrs[attr_name] = call_name
                    except (ValueError, TypeError, AttributeError):
                        pass

        return attrs

    def _scan_function_body(
        self,
        func_node: ast.AST,
        imports: List[str],
        self_attrs: Dict[str, str],
        module_name: str,
    ) -> List[DependencyCall]:
        """
        関数/メソッドのボディ内の外部依存呼び出しを検出する。

        検出パターン:
        1. self.xxx.method() — インスタンス属性経由
        2. module.func() — モジュール関数呼び出し (os.path.exists 等)
        3. ClassName.method() — クラス直接呼び出し
        """
        deps = []
        seen_targets = set()

        for node in ast.walk(func_node):
            if not isinstance(node, ast.Call):
                continue

            dep = self._classify_call(node, imports, self_attrs, module_name)
            if dep and dep.patch_target not in seen_targets:
                seen_targets.add(dep.patch_target)
                deps.append(dep)

        return deps

    def _classify_call(
        self,
        call_node: ast.Call,
        imports: List[str],
        self_attrs: Dict[str, str],
        module_name: str,
    ) -> Optional[DependencyCall]:
        """
        ast.Call ノードを分類し、DependencyCall を返す。
        内部呼び出しや分類不能なものは None を返す。
        """
        func = call_node.func

        # パターン1: self.xxx.method()
        if isinstance(func, ast.Attribute):
            # self.xxx.method() の場合
            if isinstance(func.value, ast.Attribute):
                if isinstance(func.value.value, ast.Name) and func.value.value.id == "self":
                    attr_name = func.value.attr
                    method_name = func.attr
                    if attr_name in self_attrs:
                        type_name = self_attrs[attr_name]
                        # インポートからモジュールパスを推定
                        mod_path = self._find_import_for_class(type_name, imports)
                        is_stdlib = self._is_stdlib(mod_path)
                        patch_target = f"{mod_path}.{type_name}" if mod_path else type_name
                        return DependencyCall(
                            module_path=mod_path or module_name,
                            class_or_func=type_name,
                            method_name=method_name,
                            is_stdlib=is_stdlib,
                            patch_target=patch_target,
                        )

            # パターン2: module.func() (例: os.path.exists(), json.load())
            if isinstance(func.value, ast.Attribute):
                # module.sub.func() パターン (os.path.exists)
                try:
                    full_call = ast.unparse(func)
                    parts = full_call.rsplit(".", 1)
                    if len(parts) == 2:
                        mod_part, func_part = parts
                        root_mod = mod_part.split(".")[0]
                        if root_mod in self._get_imported_roots(imports):
                            is_stdlib = self._is_stdlib(root_mod)
                            return DependencyCall(
                                module_path=mod_part,
                                class_or_func=func_part,
                                method_name=None,
                                is_stdlib=is_stdlib,
                                patch_target=full_call,
                            )
                except (ValueError, TypeError, AttributeError):
                    pass

            elif isinstance(func.value, ast.Name):
                mod_name = func.value.id
                func_name = func.attr
                # 大文字始まりはクラス名の可能性 → パターン3にフォールスルー
                if mod_name[0:1].isupper():
                    pass  # パターン3で処理
                elif mod_name in self._get_imported_roots(imports):
                    # module.func() パターン (json.loads, subprocess.Popen)
                    is_stdlib = self._is_stdlib(mod_name)
                    patch_target = f"{mod_name}.{func_name}"
                    return DependencyCall(
                        module_path=mod_name,
                        class_or_func=func_name,
                        method_name=None,
                        is_stdlib=is_stdlib,
                        patch_target=patch_target,
                    )

        # パターン3: ClassName.method() / ClassName()
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            class_name = func.value.id
            method_name = func.attr
            # インポートされたクラスかチェック
            mod_path = self._find_import_for_class(class_name, imports)
            if mod_path and not self._is_stdlib(mod_path):
                return DependencyCall(
                    module_path=mod_path,
                    class_or_func=class_name,
                    method_name=method_name,
                    is_stdlib=False,
                    patch_target=f"{mod_path}.{class_name}",
                )

        return None

    def _find_import_for_class(self, class_name: str, imports: List[str]) -> Optional[str]:
        """クラス名に対応するインポートモジュールパスを検索する。

        マッチ戦略:
        1. imports内にクラス名がモジュール末尾に含まれている場合 (from xxx import ClassName → xxx.ClassName 相当)
        2. imports内のモジュールパスの最後部分がクラス名と部分一致する場合
        3. フォールバック: クラス名の先頭をsnake_caseに変換して照合
        """
        # 戦略1: 完全一致 (例: "backend.factories.widget.WidgetFactory")
        for imp in imports:
            if imp.endswith(f".{class_name}"):
                return imp

        # 戦略2: クラス名のsnake_case変換でモジュール名と照合
        # WidgetFactory → widget_factory → widget に部分マッチ
        snake = self._camel_to_snake(class_name)
        for imp in imports:
            last_part = imp.rsplit(".", 1)[-1]
            # snake_case の先頭部分がモジュール名と一致
            if last_part == snake or snake.startswith(last_part):
                return imp

        # 戦略3: 大文字小文字無視の部分一致
        for imp in imports:
            if class_name.lower() in imp.lower():
                return imp

        return None

    @staticmethod
    def _camel_to_snake(name: str) -> str:
        """CamelCase を snake_case に変換する。"""
        import re
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

    def _is_stdlib(self, module_path: Optional[str]) -> bool:
        """モジュールがstdlibかどうかを判定する。"""
        if not module_path:
            return False
        root = module_path.split(".")[0]
        return root in STDLIB_MODULES

    def _get_imported_roots(self, imports: List[str]) -> set:
        """インポート一覧からルートモジュール名のセットを返す。"""
        roots = set()
        for imp in imports:
            root = imp.split(".")[0]
            roots.add(root)
        return roots

    # =========================================================================
    # テストコード生成
    # =========================================================================

    def generate_mock_tests_from_tree(
        self,
        tree: ast.AST,
        module_name: str,
        dep_map: DependencyMap,
    ) -> str:
        """
        ASTツリーと依存マップからモックテストコードを生成する。

        Args:
            tree: ast.parse() の結果
            module_name: モジュール名
            dep_map: analyze_dependencies_from_tree() の結果

        Returns:
            str: 生成されたテストコード
        """
        lines = []
        has_async = False
        has_popen = False

        # async メソッドの有無チェック
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                has_async = True
                break

        # subprocess.Popen の有無チェック
        for class_deps in dep_map.class_method_deps.values():
            for method_deps in class_deps.values():
                for dep in method_deps:
                    if dep.class_or_func == "Popen" and "subprocess" in dep.module_path:
                        has_popen = True
        for func_deps in dep_map.function_deps.values():
            for dep in func_deps:
                if dep.class_or_func == "Popen" and "subprocess" in dep.module_path:
                    has_popen = True

        # ヘッダー
        lines.append(f'"""Auto-generated mock tests for {module_name}"""')
        lines.append("")
        lines.append("import pytest")

        # Mock imports
        mock_imports = ["patch", "MagicMock"]
        if has_async:
            mock_imports.append("AsyncMock")
        lines.append(f"from unittest.mock import {', '.join(mock_imports)}")
        lines.append("")

        # モジュールインポート
        import_parts = module_name.rsplit(".", 1)
        classes_to_import = []
        funcs_to_import = []

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                classes_to_import.append(node.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name not in self.SKIP_FUNCTIONS and not node.name.startswith("_"):
                    funcs_to_import.append(node.name)

        if classes_to_import or funcs_to_import:
            lines.append(f"from {module_name} import (")
            for cls in classes_to_import:
                lines.append(f"    {cls},")
            for func in funcs_to_import:
                lines.append(f"    {func},")
            lines.append(")")
        lines.append("")
        lines.append("")

        # クラスごとのテスト
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                class_lines = self._generate_class_mock_tests(
                    node, module_name, dep_map, has_popen,
                )
                lines.extend(class_lines)
                lines.append("")

        # トップレベル関数のテスト
        standalone = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name not in self.SKIP_FUNCTIONS and not node.name.startswith("_"):
                    standalone.append(node)

        if standalone:
            func_lines = self._generate_standalone_mock_tests(
                standalone, module_name, dep_map,
            )
            lines.extend(func_lines)

        return "\n".join(lines)

    def _generate_class_mock_tests(
        self,
        class_node: ast.ClassDef,
        module_name: str,
        dep_map: DependencyMap,
        has_popen: bool,
    ) -> List[str]:
        """クラスのモックテストコードを生成する。"""
        lines = []
        class_name = class_node.name
        test_class_name = f"Test{class_name}"
        class_deps = dep_map.class_method_deps.get(class_name, {})

        lines.append(f"class {test_class_name}:")
        docstring = ast.get_docstring(class_node)
        if docstring:
            lines.append(f'    """Tests for {class_name}: {docstring[:80]}"""')
        else:
            lines.append(f'    """Tests for {class_name} with mocked dependencies"""')
        lines.append("")

        test_methods = [
            m for m in class_node.body
            if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
            and m.name not in self.SKIP_METHODS
            and not m.name.startswith("_")
        ]

        if not test_methods:
            lines.append("    def test_instantiation(self):")
            lines.append(f'        """Test that {class_name} can be instantiated."""')
            lines.append(f"        instance = {class_name}()")
            lines.append("        assert instance is not None")
            lines.append("")
            return lines

        for method in test_methods:
            method_deps = class_deps.get(method.name, [])
            method_lines = self._generate_method_mock_test(
                method, class_name, method_deps, module_name,
            )
            lines.extend(method_lines)
            lines.append("")

        return lines

    def _generate_method_mock_test(
        self,
        method_node: ast.AST,
        class_name: str,
        deps: List[DependencyCall],
        module_name: str,
    ) -> List[str]:
        """メソッドのモックテストコードを生成する。"""
        lines = []
        is_async = isinstance(method_node, ast.AsyncFunctionDef)
        method_name = method_node.name
        test_name = f"test_{method_name}"

        # subprocess.Popen の検出
        popen_deps = [d for d in deps if d.class_or_func == "Popen" and "subprocess" in d.module_path]
        non_popen_deps = [d for d in deps if d not in popen_deps]

        # @patch デコレータ（Popenは除外、safe_popen_mock fixtureで対応）
        for dep in reversed(non_popen_deps):
            lines.append(f"    @patch('{dep.patch_target}')")

        # メソッドシグネチャ
        params = ["self"]
        if popen_deps:
            params.append("safe_popen_mock")
        for dep in non_popen_deps:
            mock_param = f"mock_{dep.class_or_func.lower()}"
            params.append(mock_param)

        if is_async:
            lines.append(f"    @pytest.mark.asyncio")
            lines.append(f"    async def {test_name}({', '.join(params)}):")
        else:
            lines.append(f"    def {test_name}({', '.join(params)}):")

        # docstring
        args_str = self._get_method_args_str(method_node)
        lines.append(f'        """Test {class_name}.{method_name}({args_str})"""')

        # Mock setup
        if popen_deps:
            lines.append("        # safe_popen_mock fixture (GEMINI.md規約準拠)")
            lines.append("        proc = safe_popen_mock(returncode=0)")

        for dep in non_popen_deps:
            mock_param = f"mock_{dep.class_or_func.lower()}"
            if dep.method_name:
                lines.append(f"        # Mock {dep.class_or_func}.{dep.method_name}()")
                mock_instance = f"{mock_param}.return_value"
                ret_val = self._guess_return_value(method_node)
                lines.append(f"        {mock_instance}.{dep.method_name}.return_value = {ret_val}")
            else:
                lines.append(f"        # Mock {dep.patch_target}")
                ret_val = self._guess_return_value(method_node)
                lines.append(f"        {mock_param}.return_value = {ret_val}")

        lines.append("")

        # Execute
        lines.append("        # Execute")
        arg_values = self._generate_test_arg_values(method_node)
        if is_async:
            lines.append(f"        instance = {class_name}()")
            if arg_values:
                lines.append(f"        result = await instance.{method_name}({arg_values})")
            else:
                lines.append(f"        result = await instance.{method_name}()")
        else:
            lines.append(f"        instance = {class_name}()")
            if arg_values:
                lines.append(f"        result = instance.{method_name}({arg_values})")
            else:
                lines.append(f"        result = instance.{method_name}()")

        lines.append("")

        # Assert
        lines.append("        # Assert")
        return_annotation = None
        if method_node.returns:
            try:
                return_annotation = ast.unparse(method_node.returns)
            except (ValueError, TypeError, AttributeError):
                pass

        if return_annotation:
            lines.append(f"        # Expected return type: {return_annotation}")
        lines.append("        assert result is not None  # TODO: 具体的なアサーションに置換")

        # Mock verification
        for dep in non_popen_deps:
            mock_param = f"mock_{dep.class_or_func.lower()}"
            if dep.method_name:
                lines.append(f"        {mock_param}.return_value.{dep.method_name}.assert_called_once()")

        return lines

    def _generate_standalone_mock_tests(
        self,
        functions: List[ast.AST],
        module_name: str,
        dep_map: DependencyMap,
    ) -> List[str]:
        """トップレベル関数のモックテストコードを生成する。"""
        lines = []
        lines.append("class TestModuleFunctions:")
        lines.append(f'    """Tests for standalone functions in {module_name}"""')
        lines.append("")

        for func in functions:
            func_name = func.name
            func_deps = dep_map.function_deps.get(func_name, [])
            is_async = isinstance(func, ast.AsyncFunctionDef)

            # @patch デコレータ
            for dep in reversed(func_deps):
                lines.append(f"    @patch('{dep.patch_target}')")

            # メソッドシグネチャ
            params = ["self"]
            for dep in func_deps:
                params.append(f"mock_{dep.class_or_func.lower()}")

            if is_async:
                lines.append(f"    @pytest.mark.asyncio")
                lines.append(f"    async def test_{func_name}({', '.join(params)}):")
            else:
                lines.append(f"    def test_{func_name}({', '.join(params)}):")

            # docstring
            args_str = self._get_method_args_str(func)
            lines.append(f'        """Test {func_name}({args_str})"""')

            # Mock setup
            for dep in func_deps:
                mock_param = f"mock_{dep.class_or_func.lower()}"
                ret_val = self._guess_return_value(func)
                lines.append(f"        {mock_param}.return_value = {ret_val}")

            lines.append("")

            # Execute
            arg_values = self._generate_test_arg_values(func)
            if is_async:
                if arg_values:
                    lines.append(f"        result = await {func_name}({arg_values})")
                else:
                    lines.append(f"        result = await {func_name}()")
            else:
                if arg_values:
                    lines.append(f"        result = {func_name}({arg_values})")
                else:
                    lines.append(f"        result = {func_name}()")

            lines.append("")
            lines.append("        # Assert")
            lines.append("        assert result is not None  # TODO: 具体的なアサーションに置換")
            lines.append("")

        return lines

    # =========================================================================
    # ヘルパーメソッド
    # =========================================================================

    def _get_method_args_str(self, func_node: ast.AST) -> str:
        """メソッドの引数名を文字列で返す（self/cls除外）。"""
        args = []
        for arg in func_node.args.args:
            if arg.arg in ("self", "cls"):
                continue
            args.append(arg.arg)
        return ", ".join(args)

    def _generate_test_arg_values(self, func_node: ast.AST) -> str:
        """引数の型ヒントからテスト値を生成する。"""
        values = []
        required_count = len(func_node.args.args) - len(func_node.args.defaults)

        for i, arg in enumerate(func_node.args.args):
            if arg.arg in ("self", "cls"):
                continue
            if i >= required_count:
                break

            annotation = ""
            if arg.annotation:
                try:
                    annotation = ast.unparse(arg.annotation)
                except (ValueError, TypeError, AttributeError):
                    pass

            value = self._type_to_default_value(annotation, arg.arg)
            values.append(f"{arg.arg}={value}")

        return ", ".join(values)

    def _type_to_default_value(self, type_hint: str, arg_name: str) -> str:
        """型ヒントからデフォルトのテスト値を推定する。"""
        if not type_hint:
            name_lower = arg_name.lower()
            if "path" in name_lower or "file" in name_lower or "dir" in name_lower:
                return '"/tmp/test"'
            if "name" in name_lower or "title" in name_lower:
                return '"test_value"'
            if "count" in name_lower or "num" in name_lower or "size" in name_lower:
                return "1"
            if "cmd" in name_lower or "command" in name_lower:
                return '["echo", "test"]'
            if "enabled" in name_lower or "flag" in name_lower or name_lower.startswith("is_"):
                return "True"
            return "None  # TODO: 適切な値を設定"

        ordered_type_map = [
            ("Optional", "None"),
            ("List", "[]"),
            ("list", "[]"),
            ("Dict", "{}"),
            ("dict", "{}"),
            ("Path", 'Path("/tmp/test")'),
            ("bool", "True"),
            ("float", "1.0"),
            ("int", "1"),
            ("str", '"test_value"'),
        ]

        for key, value in ordered_type_map:
            if type_hint.startswith(key) or type_hint == key:
                return value

        return "None  # TODO: 適切な値を設定"

    def _guess_return_value(self, func_node: ast.AST) -> str:
        """関数の返り値型ヒントから適切なモック戻り値を推定する。"""
        if func_node.returns:
            try:
                ret_type = ast.unparse(func_node.returns)
                return self._type_to_default_value(ret_type, "")
            except (ValueError, TypeError, AttributeError):
                pass
        return "MagicMock()"

    # =========================================================================
    # 統合 API
    # =========================================================================

    def generate_and_save_mocked(
        self,
        source_path: str,
        output_path: str,
        module_name: str,
    ) -> str:
        """
        ソースファイルを解析してモックテストを生成し、ファイルに保存する。

        Args:
            source_path: 対象ソースファイルの絶対パス
            output_path: 出力先テストファイルの絶対パス
            module_name: モジュール名（ドット区切り）

        Returns:
            str: 出力先ファイルのパス
        """
        # ソース読み込み
        with open(source_path, "r", encoding="utf-8") as f:
            source = f.read()

        tree = ast.parse(source, filename=source_path)

        # インポート抽出
        imports = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)

        # 依存解析
        dep_map = self.analyze_dependencies_from_tree(tree, module_name, imports)

        # テストコード生成
        test_code = self.generate_mock_tests_from_tree(tree, module_name, dep_map)

        # 構文検証 + アトミック書き込み（DS-022: InlineCoverageExtender統合）
        from backend.agents.orchestration.inline_coverage_extender import InlineCoverageExtender
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        extender = InlineCoverageExtender(output_path)
        extender._verify_syntax(test_code)
        extender._write_atomic(test_code)

        logger.info(f"Generated mock test file (atomic): {output_path}")
        return output_path
