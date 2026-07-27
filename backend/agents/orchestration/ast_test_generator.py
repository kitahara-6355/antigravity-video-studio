"""
DS-034: AST解析からのテスト自動生成エンジン

プロダクションコードのAST解析に基づいてユニットテストの雛形を自動作成する。
InlineCoverageExtender と連携して安全なファイル書き込みを行う。

機能:
1. プロダクションコードのAST解析（クラス/関数/メソッドの抽出）
2. 引数シグネチャの解析（型ヒント含む）
3. テスト雛形コードの生成
4. InlineCoverageExtender経由の安全な書き込み
"""

import ast
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any

import logging

logger = logging.getLogger(__name__)


@dataclass
class FunctionInfo:
    """AST解析で抽出された関数/メソッド情報"""
    name: str
    args: List[str]
    defaults_count: int
    decorators: List[str]
    is_method: bool
    is_async: bool
    docstring: Optional[str]
    line_number: int
    return_annotation: Optional[str] = None
    arg_annotations: Dict[str, str] = field(default_factory=dict)


@dataclass
class ClassInfo:
    """AST解析で抽出されたクラス情報"""
    name: str
    methods: List[FunctionInfo]
    base_classes: List[str]
    line_number: int
    docstring: Optional[str] = None


@dataclass
class ModuleInfo:
    """AST解析で抽出されたモジュール情報"""
    file_path: str
    module_name: str
    classes: List[ClassInfo]
    functions: List[FunctionInfo]
    imports: List[str]


class ASTTestGenerator:
    """
    プロダクションコードのAST解析からテスト雛形を自動生成するエンジン。
    
    使い方:
        gen = ASTTestGenerator()
        module_info = gen.analyze_module("backend/services/some_service.py")
        test_code = gen.generate_tests(module_info)
    """
    
    # テスト生成から除外するメソッド名パターン
    SKIP_METHODS = {"__init__", "__repr__", "__str__", "__eq__", "__hash__",
                    "__lt__", "__le__", "__gt__", "__ge__", "__ne__"}
    
    # テスト生成から除外する関数名パターン
    SKIP_FUNCTIONS = {"main", "setup_logging", "configure"}

    def __init__(self, workspace_path: str = None):
        self.workspace_path = Path(
            workspace_path or os.path.dirname(
                os.path.dirname(os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__))
                ))
            )
        )

    def analyze_module(self, module_path: str) -> ModuleInfo:
        """
        指定されたPythonモジュールをAST解析し、構造情報を抽出する。
        
        Args:
            module_path: ワークスペースルートからの相対パス
            
        Returns:
            ModuleInfo: モジュールの構造情報
            
        Raises:
            FileNotFoundError: モジュールが存在しない場合
            SyntaxError: モジュールにPython構文エラーがある場合
        """
        full_path = self.workspace_path / module_path
        if not full_path.exists():
            raise FileNotFoundError(f"Module not found: {full_path}")
        
        content = full_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(full_path))
        
        # モジュール名の導出（例: backend/services/foo.py → backend.services.foo）
        module_name = module_path.replace("/", ".").replace("\\", ".")
        if module_name.endswith(".py"):
            module_name = module_name[:-3]
        
        classes = []
        functions = []
        imports = []
        
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                classes.append(self._extract_class(node))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(self._extract_function(node, is_method=False))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
        
        return ModuleInfo(
            file_path=module_path,
            module_name=module_name,
            classes=classes,
            functions=functions,
            imports=imports,
        )

    def _extract_class(self, node: ast.ClassDef) -> ClassInfo:
        """クラスノードからClassInfoを抽出する。"""
        methods = []
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append(self._extract_function(item, is_method=True))
        
        base_classes = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                base_classes.append(base.id)
            elif isinstance(base, ast.Attribute):
                base_classes.append(ast.unparse(base))
        
        docstring = ast.get_docstring(node)
        
        return ClassInfo(
            name=node.name,
            methods=methods,
            base_classes=base_classes,
            line_number=node.lineno,
            docstring=docstring,
        )

    def _extract_function(self, node, is_method: bool) -> FunctionInfo:
        """関数/メソッドノードからFunctionInfoを抽出する。"""
        is_async = isinstance(node, ast.AsyncFunctionDef)
        
        # 引数名の抽出（selfは除外）
        args = []
        arg_annotations = {}
        for arg in node.args.args:
            name = arg.arg
            if name == "self" or name == "cls":
                continue
            args.append(name)
            if arg.annotation:
                try:
                    arg_annotations[name] = ast.unparse(arg.annotation)
                except (ValueError, TypeError, AttributeError):
                    pass
        
        # デフォルト値の数
        defaults_count = len(node.args.defaults)
        
        # デコレータ
        decorators = []
        for dec in node.decorator_list:
            try:
                decorators.append(ast.unparse(dec))
            except (ValueError, TypeError, AttributeError):
                decorators.append("unknown")
        
        # 返り値アノテーション
        return_annotation = None
        if node.returns:
            try:
                return_annotation = ast.unparse(node.returns)
            except (ValueError, TypeError, AttributeError):
                pass
        
        docstring = ast.get_docstring(node)
        
        return FunctionInfo(
            name=node.name,
            args=args,
            defaults_count=defaults_count,
            decorators=decorators,
            is_method=is_method,
            is_async=is_async,
            docstring=docstring,
            line_number=node.lineno,
            return_annotation=return_annotation,
            arg_annotations=arg_annotations,
        )

    def generate_tests(self, module_info: ModuleInfo) -> str:
        """
        ModuleInfoからテスト雛形コードを生成する。
        
        Args:
            module_info: analyze_module() で取得したモジュール情報
            
        Returns:
            str: 生成されたテストコード文字列
        """
        lines = []
        
        # ヘッダー
        lines.append(f'"""Auto-generated tests for {module_info.module_name}"""')
        lines.append("")
        lines.append("import pytest")
        lines.append("from unittest.mock import patch, MagicMock")
        lines.append("")
        
        # インポート
        import_parts = module_info.module_name.rsplit(".", 1)
        if len(import_parts) == 2:
            package, mod_name = import_parts
            lines.append(f"from {module_info.module_name} import (")
            # クラス名をインポート
            for cls in module_info.classes:
                lines.append(f"    {cls.name},")
            # トップレベル関数をインポート
            for func in module_info.functions:
                if func.name not in self.SKIP_FUNCTIONS and not func.name.startswith("_"):
                    lines.append(f"    {func.name},")
            lines.append(")")
        else:
            lines.append(f"import {module_info.module_name}")
        lines.append("")
        lines.append("")
        
        # クラスごとのテスト
        for cls in module_info.classes:
            lines.extend(self._generate_class_tests(cls, module_info))
            lines.append("")
        
        # トップレベル関数のテスト
        standalone_funcs = [
            f for f in module_info.functions
            if f.name not in self.SKIP_FUNCTIONS and not f.name.startswith("_")
        ]
        if standalone_funcs:
            lines.extend(self._generate_standalone_tests(standalone_funcs, module_info))
        
        return "\n".join(lines)

    def _generate_class_tests(self, cls: ClassInfo, module_info: ModuleInfo) -> List[str]:
        """クラスのテストコードを生成する。"""
        lines = []
        test_class_name = f"Test{cls.name}"
        lines.append(f"class {test_class_name}:")
        
        if cls.docstring:
            lines.append(f'    """Tests for {cls.name}: {cls.docstring[:80]}"""')
        else:
            lines.append(f'    """Tests for {cls.name}"""')
        lines.append("")
        
        # テスト対象メソッドのフィルタリング
        test_methods = [
            m for m in cls.methods
            if m.name not in self.SKIP_METHODS and not m.name.startswith("_")
        ]
        
        if not test_methods:
            lines.append("    def test_instantiation(self):")
            lines.append(f'        """Test that {cls.name} can be instantiated."""')
            lines.append(f"        instance = {cls.name}()")
            lines.append("        assert instance is not None")
            lines.append("")
        
        for method in test_methods:
            lines.extend(self._generate_method_test(method, cls.name))
            lines.append("")
        
        return lines

    def _generate_method_test(self, method: FunctionInfo, class_name: str) -> List[str]:
        """メソッドの個別テストコードを生成する。"""
        lines = []
        test_name = f"test_{method.name}"
        
        # async メソッドの場合
        if method.is_async:
            lines.append(f"    @pytest.mark.asyncio")
            lines.append(f"    async def {test_name}(self):")
        else:
            lines.append(f"    def {test_name}(self):")
        
        # ドキュメント
        if method.docstring:
            lines.append(f'        """Test {method.name}: {method.docstring[:60]}"""')
        else:
            lines.append(f'        """Test {class_name}.{method.name}({", ".join(method.args)})"""')
        
        # インスタンス生成
        lines.append(f"        instance = {class_name}()")
        
        # 引数の生成
        arg_values = self._generate_arg_values(method)
        
        if method.is_async:
            if arg_values:
                lines.append(f"        result = await instance.{method.name}({arg_values})")
            else:
                lines.append(f"        result = await instance.{method.name}()")
        else:
            if arg_values:
                lines.append(f"        result = instance.{method.name}({arg_values})")
            else:
                lines.append(f"        result = instance.{method.name}()")
        
        # 返り値のアサーション
        if method.return_annotation:
            lines.append(f"        # Expected return type: {method.return_annotation}")
        lines.append("        assert result is not None  # TODO: 具体的なアサーションに置換")
        
        return lines

    def _generate_standalone_tests(self, functions: List[FunctionInfo], module_info: ModuleInfo) -> List[str]:
        """トップレベル関数のテストコードを生成する。"""
        lines = []
        lines.append("class TestModuleFunctions:")
        lines.append(f'    """Tests for standalone functions in {module_info.module_name}"""')
        lines.append("")
        
        for func in functions:
            test_name = f"test_{func.name}"
            
            if func.is_async:
                lines.append(f"    @pytest.mark.asyncio")
                lines.append(f"    async def {test_name}(self):")
            else:
                lines.append(f"    def {test_name}(self):")
            
            if func.docstring:
                lines.append(f'        """Test {func.name}: {func.docstring[:60]}"""')
            else:
                lines.append(f'        """Test {func.name}({", ".join(func.args)})"""')
            
            arg_values = self._generate_arg_values(func)
            
            if func.is_async:
                if arg_values:
                    lines.append(f"        result = await {func.name}({arg_values})")
                else:
                    lines.append(f"        result = await {func.name}()")
            else:
                if arg_values:
                    lines.append(f"        result = {func.name}({arg_values})")
                else:
                    lines.append(f"        result = {func.name}()")
            
            if func.return_annotation:
                lines.append(f"        # Expected return type: {func.return_annotation}")
            lines.append("        assert result is not None  # TODO: 具体的なアサーションに置換")
            lines.append("")
        
        return lines

    def _generate_arg_values(self, func: FunctionInfo) -> str:
        """引数の型ヒントからデフォルトのテスト値を生成する。"""
        if not func.args:
            return ""
        
        values = []
        required_count = len(func.args) - func.defaults_count
        
        for i, arg in enumerate(func.args):
            if i >= required_count:
                break  # デフォルト値付き引数はスキップ
            
            annotation = func.arg_annotations.get(arg, "")
            value = self._type_to_default_value(annotation, arg)
            values.append(f"{arg}={value}")
        
        return ", ".join(values)

    def _type_to_default_value(self, type_hint: str, arg_name: str) -> str:
        """型ヒントからデフォルトのテスト値を推定する。"""
        if not type_hint:
            # 引数名から推定
            name_lower = arg_name.lower()
            if "path" in name_lower or "file" in name_lower or "dir" in name_lower:
                return '"/tmp/test"'
            if "name" in name_lower or "title" in name_lower:
                return '"test_value"'
            if "count" in name_lower or "num" in name_lower or "size" in name_lower:
                return "1"
            if "enabled" in name_lower or "flag" in name_lower or name_lower.startswith("is_"):
                return "True"
            return "None  # TODO: 適切な値を設定"
        
        # 型ヒントからマッピング（具体的な型を先に評価）
        # 順序が重要: List[str] が "str" にマッチしないよう、複合型を先にチェック
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
            if type_hint.startswith(key) or f"[{key}]" in type_hint:
                return value
            # 単純型の場合は完全一致も確認
            if type_hint == key:
                return value
        
        return "None  # TODO: 適切な値を設定"

    def generate_and_save(self, module_path: str, output_path: str = None) -> str:
        """
        モジュールを解析してテスト雛形を生成し、ファイルに保存する。
        
        InlineCoverageExtender 経由でアトミック書き込み+構文検証を実施。
        
        Args:
            module_path: 対象モジュールのパス
            output_path: 出力先テストファイルのパス（省略時は自動決定）
            
        Returns:
            str: 出力先ファイルのパス
        """
        module_info = self.analyze_module(module_path)
        test_code = self.generate_tests(module_info)
        
        if not output_path:
            # テストファイルパスの自動決定
            base = Path(module_path).stem
            test_dir = self.workspace_path / "backend" / "tests"
            output_path = str(test_dir / f"test_{base}_auto.py")
        
        full_output = self.workspace_path / output_path if not os.path.isabs(output_path) else Path(output_path)
        full_output.parent.mkdir(parents=True, exist_ok=True)
        
        # DS-022: InlineCoverageExtender 経由のアトミック書き込み
        from backend.agents.orchestration.inline_coverage_extender import InlineCoverageExtender
        extender = InlineCoverageExtender(str(full_output))
        extender._verify_syntax(test_code)
        extender._write_atomic(test_code)
        
        logger.info(f"Generated test file (atomic): {full_output}")
        return str(full_output)
