"""
DS-034: ASTTestGenerator のユニットテスト

ast_test_generator.py の全主要機能をテストする。
"""

import ast
import os
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.orchestration.ast_test_generator import (
    ASTTestGenerator,
    ModuleInfo,
    ClassInfo,
    FunctionInfo,
)


@pytest.fixture
def generator(tmp_path):
    """ASTTestGenerator インスタンスを返す fixture"""
    return ASTTestGenerator(workspace_path=str(tmp_path))


@pytest.fixture
def sample_module(tmp_path):
    """テスト用のPythonモジュールを生成する fixture"""
    code = '''"""Sample module for testing."""

import os
from pathlib import Path
from typing import List, Optional, Dict


class SampleService:
    """A sample service class."""
    
    def __init__(self, name: str = "default"):
        self.name = name
    
    def process(self, data: List[str], count: int = 10) -> Dict[str, int]:
        """Process data and return results."""
        return {item: len(item) for item in data[:count]}
    
    def validate(self, path: str) -> bool:
        """Validate the given path."""
        return os.path.exists(path)
    
    async def fetch_data(self, url: str) -> Optional[str]:
        """Fetch data from URL."""
        return None
    
    def _internal_method(self):
        """Internal method, should be skipped."""
        pass


class AnotherClass:
    """Another class with no public methods."""
    
    def __init__(self):
        pass


def helper_function(value: int, name: str = "test") -> str:
    """A standalone helper function."""
    return f"{name}:{value}"


def _private_function():
    """Private function, should be skipped."""
    pass
'''
    module_dir = tmp_path / "backend" / "services"
    module_dir.mkdir(parents=True)
    module_file = module_dir / "sample_service.py"
    module_file.write_text(code, encoding="utf-8")
    return "backend/services/sample_service.py"


class TestAnalyzeModule:
    """analyze_module() のテスト"""

    def test_analyze_basic_module(self, generator, sample_module):
        """基本的なモジュール解析が動作すること"""
        info = generator.analyze_module(sample_module)
        
        assert isinstance(info, ModuleInfo)
        assert info.file_path == sample_module
        assert info.module_name == "backend.services.sample_service"
        assert len(info.classes) == 2
        assert len(info.imports) >= 3  # os, pathlib.Path, typing

    def test_analyze_class_extraction(self, generator, sample_module):
        """クラスの抽出が正しいこと"""
        info = generator.analyze_module(sample_module)
        
        sample_cls = next(c for c in info.classes if c.name == "SampleService")
        assert sample_cls.docstring == "A sample service class."
        assert len(sample_cls.methods) >= 4  # __init__, process, validate, fetch_data, _internal

    def test_analyze_method_extraction(self, generator, sample_module):
        """メソッドの引数・型ヒント・デコレータの抽出が正しいこと"""
        info = generator.analyze_module(sample_module)
        sample_cls = next(c for c in info.classes if c.name == "SampleService")
        
        process_method = next(m for m in sample_cls.methods if m.name == "process")
        assert process_method.is_method is True
        assert "data" in process_method.args
        assert "count" in process_method.args
        assert process_method.defaults_count == 1
        assert process_method.return_annotation is not None
        assert "List[str]" in process_method.arg_annotations.get("data", "")

    def test_analyze_async_method(self, generator, sample_module):
        """asyncメソッドが正しく検出されること"""
        info = generator.analyze_module(sample_module)
        sample_cls = next(c for c in info.classes if c.name == "SampleService")
        
        fetch_method = next(m for m in sample_cls.methods if m.name == "fetch_data")
        assert fetch_method.is_async is True

    def test_analyze_standalone_functions(self, generator, sample_module):
        """トップレベル関数の抽出"""
        info = generator.analyze_module(sample_module)
        
        func_names = [f.name for f in info.functions]
        assert "helper_function" in func_names
        assert "_private_function" in func_names

    def test_analyze_nonexistent_file(self, generator):
        """存在しないファイルでFileNotFoundError"""
        with pytest.raises(FileNotFoundError):
            generator.analyze_module("nonexistent/module.py")

    def test_analyze_syntax_error_file(self, generator, tmp_path):
        """構文エラーのファイルでSyntaxError"""
        bad_file = tmp_path / "bad_syntax.py"
        bad_file.write_text("def broken(:\n    pass", encoding="utf-8")
        
        with pytest.raises(SyntaxError):
            generator.analyze_module("bad_syntax.py")


class TestGenerateTests:
    """generate_tests() のテスト"""

    def test_generate_basic_tests(self, generator, sample_module):
        """基本的なテスト生成が動作すること"""
        info = generator.analyze_module(sample_module)
        code = generator.generate_tests(info)
        
        assert "import pytest" in code
        assert "class TestSampleService:" in code
        assert "def test_process" in code
        assert "def test_validate" in code

    def test_generate_skips_private_methods(self, generator, sample_module):
        """プライベートメソッドがスキップされること"""
        info = generator.analyze_module(sample_module)
        code = generator.generate_tests(info)
        
        assert "test__internal_method" not in code

    def test_generate_skips_dunder_methods(self, generator, sample_module):
        """ダンダーメソッドがスキップされること"""
        info = generator.analyze_module(sample_module)
        code = generator.generate_tests(info)
        
        assert "test___init__" not in code

    def test_generate_async_test(self, generator, sample_module):
        """asyncメソッドにpytest.mark.asyncioが付くこと"""
        info = generator.analyze_module(sample_module)
        code = generator.generate_tests(info)
        
        assert "@pytest.mark.asyncio" in code
        assert "async def test_fetch_data" in code

    def test_generate_standalone_function_tests(self, generator, sample_module):
        """トップレベル関数のテストが生成されること"""
        info = generator.analyze_module(sample_module)
        code = generator.generate_tests(info)
        
        assert "def test_helper_function" in code
        assert "test__private_function" not in code

    def test_generated_code_is_valid_python(self, generator, sample_module):
        """生成されたコードがPython構文として正しいこと"""
        info = generator.analyze_module(sample_module)
        code = generator.generate_tests(info)
        
        # 構文チェック（SyntaxErrorが出なければOK）
        ast.parse(code)

    def test_generate_class_without_public_methods(self, generator, sample_module):
        """パブリックメソッドのないクラスにもインスタンス化テストが生成されること"""
        info = generator.analyze_module(sample_module)
        code = generator.generate_tests(info)
        
        assert "class TestAnotherClass:" in code
        assert "test_instantiation" in code

    def test_generate_type_hint_default_values(self, generator, sample_module):
        """型ヒントからデフォルトテスト値が生成されること"""
        info = generator.analyze_module(sample_module)
        code = generator.generate_tests(info)
        
        # process メソッドの data 引数は List[str] なので [] が使われるはず
        assert "data=[]" in code


class TestTypeToDefaultValue:
    """_type_to_default_value() のテスト"""

    def test_str_type(self, generator):
        assert generator._type_to_default_value("str", "name") == '"test_value"'

    def test_int_type(self, generator):
        assert generator._type_to_default_value("int", "count") == "1"

    def test_float_type(self, generator):
        assert generator._type_to_default_value("float", "score") == "1.0"

    def test_bool_type(self, generator):
        assert generator._type_to_default_value("bool", "flag") == "True"

    def test_list_type(self, generator):
        assert generator._type_to_default_value("List[str]", "items") == "[]"

    def test_dict_type(self, generator):
        assert generator._type_to_default_value("Dict[str, int]", "data") == "{}"

    def test_optional_type(self, generator):
        assert generator._type_to_default_value("Optional[str]", "name") == "None"

    def test_path_arg_name_inference(self, generator):
        """型ヒントなしでも引数名からパスを推定"""
        result = generator._type_to_default_value("", "file_path")
        assert "/tmp/test" in result

    def test_count_arg_name_inference(self, generator):
        """型ヒントなしでも引数名からintを推定"""
        result = generator._type_to_default_value("", "item_count")
        assert result == "1"

    def test_bool_arg_name_inference(self, generator):
        """型ヒントなしでも is_ プレフィックスからboolを推定"""
        result = generator._type_to_default_value("", "is_active")
        assert result == "True"

    def test_unknown_type(self, generator):
        """不明な型はNone + TODOコメント"""
        result = generator._type_to_default_value("CustomClass", "obj")
        assert "None" in result
        assert "TODO" in result


class TestGenerateAndSave:
    """generate_and_save() のテスト"""

    def test_save_to_default_path(self, generator, sample_module, tmp_path):
        """デフォルトパスにファイルが保存されること"""
        output = generator.generate_and_save(sample_module)
        assert os.path.exists(output)
        assert "test_sample_service_auto.py" in output

    def test_save_to_custom_path(self, generator, sample_module, tmp_path):
        """カスタムパスにファイルが保存されること"""
        custom_path = str(tmp_path / "custom_tests" / "test_custom.py")
        output = generator.generate_and_save(sample_module, output_path=custom_path)
        assert os.path.exists(output)
        assert "test_custom.py" in output

    def test_saved_file_is_valid_python(self, generator, sample_module, tmp_path):
        """保存されたファイルが構文的に正しいこと"""
        output = generator.generate_and_save(sample_module)
        
        with open(output, "r", encoding="utf-8") as f:
            content = f.read()
        
        ast.parse(content)  # SyntaxError が出なければOK


class TestEdgeCases:
    """エッジケースのテスト"""

    def test_empty_module(self, generator, tmp_path):
        """空のモジュールでも正常に解析できること"""
        empty_file = tmp_path / "empty.py"
        empty_file.write_text("", encoding="utf-8")
        
        info = generator.analyze_module("empty.py")
        assert len(info.classes) == 0
        assert len(info.functions) == 0

    def test_module_with_only_imports(self, generator, tmp_path):
        """インポートのみのモジュール"""
        import_file = tmp_path / "only_imports.py"
        import_file.write_text("import os\nimport sys\n", encoding="utf-8")
        
        info = generator.analyze_module("only_imports.py")
        assert len(info.imports) == 2

    def test_deeply_nested_class(self, generator, tmp_path):
        """ネストされたクラスは直下のみ抽出"""
        nested_code = '''
class Outer:
    class Inner:
        def method(self):
            pass
    def outer_method(self):
        pass
'''
        nested_file = tmp_path / "nested.py"
        nested_file.write_text(nested_code, encoding="utf-8")
        
        info = generator.analyze_module("nested.py")
        outer = next(c for c in info.classes if c.name == "Outer")
        # Outer の直下メソッドのみが抽出される
        method_names = [m.name for m in outer.methods]
        assert "outer_method" in method_names


class TestCoverageDetailed:
    """ast_test_generator.py のカバレッジ100%を達成するための詳細テストケース"""

    def test_extract_class_with_bases(self, generator):
        """1. 基底クラスが ast.Name / ast.Attribute の場合のテスト (L146-149)"""
        code = "class Child(Parent, pkg.Parent): pass"
        tree = ast.parse(code)
        class_node = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
        
        info = generator._extract_class(class_node)
        assert "Parent" in info.base_classes
        assert "pkg.Parent" in info.base_classes

    def test_extract_function_annotation_error(self, generator):
        """2. 引数アノテーションの ast.unparse が例外を投げる場合 (L176-177)"""
        code = "def my_func(x: int): pass"
        tree = ast.parse(code)
        func_node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
        
        original_unparse = ast.unparse
        
        def mock_unparse(node):
            if isinstance(node, ast.Name) and node.id == "int":
                raise ValueError("Mocked error")
            return original_unparse(node)
            
        with patch("ast.unparse", side_effect=mock_unparse):
            info = generator._extract_function(func_node, is_method=False)
            
        # 例外が握りつぶされ、arg_annotations['x'] には登録されない
        assert "x" not in info.arg_annotations

    def test_extract_function_decorator_error(self, generator):
        """3. デコレータの ast.unparse が例外を投げる場合 (L187-188)"""
        code = "@my_decorator\ndef my_func(): pass"
        tree = ast.parse(code)
        func_node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
        
        original_unparse = ast.unparse
        
        def mock_unparse(node):
            if isinstance(node, ast.Name) and node.id == "my_decorator":
                raise TypeError("Mocked error")
            return original_unparse(node)
            
        with patch("ast.unparse", side_effect=mock_unparse):
            info = generator._extract_function(func_node, is_method=False)
            
        # 例外が発生すると、decorators には "unknown" が登録される
        assert info.decorators == ["unknown"]

    def test_extract_function_returns_error(self, generator):
        """4. 返り値アノテーションの ast.unparse が例外を投げる場合 (L195-196)"""
        code = "def my_func() -> str: pass"
        tree = ast.parse(code)
        func_node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
        
        original_unparse = ast.unparse
        
        def mock_unparse(node):
            if isinstance(node, ast.Name) and node.id == "str":
                raise AttributeError("Mocked error")
            return original_unparse(node)
            
        with patch("ast.unparse", side_effect=mock_unparse):
            info = generator._extract_function(func_node, is_method=False)
            
        # 例外が握りつぶされ、return_annotation は None になる
        assert info.return_annotation is None

    def test_generate_tests_flat_module_name(self, generator):
        """5. モジュール名にドットが含まれない場合 (L246)"""
        info = ModuleInfo(
            file_path="mymodule.py",
            module_name="mymodule",
            classes=[],
            functions=[],
            imports=[]
        )
        code = generator.generate_tests(info)
        assert "import mymodule" in code

    def test_generate_class_tests_without_docstring(self, generator):
        """6. クラスに docstring がない場合 (L274)"""
        cls_info = ClassInfo(
            name="NoDocClass",
            methods=[],
            base_classes=[],
            line_number=1,
            docstring=None
        )
        module_info = ModuleInfo(
            file_path="dummy.py",
            module_name="dummy",
            classes=[cls_info],
            functions=[],
            imports=[]
        )
        code = generator.generate_tests(module_info)
        assert '"""Tests for NoDocClass"""' in code

    def test_generate_method_test_without_docstring_sync_no_args(self, generator):
        """7, 9. メソッドに docstring がなく、同期メソッドかつ引数がない場合 (L312, L329)"""
        method_info = FunctionInfo(
            name="my_method",
            args=[],
            defaults_count=0,
            decorators=[],
            is_method=True,
            is_async=False,
            docstring=None,
            line_number=5,
            return_annotation=None,
            arg_annotations={}
        )
        cls_info = ClassInfo(
            name="MyClass",
            methods=[method_info],
            base_classes=[],
            line_number=1,
            docstring=None
        )
        module_info = ModuleInfo(
            file_path="dummy.py",
            module_name="dummy.module",
            classes=[cls_info],
            functions=[],
            imports=[]
        )
        code = generator.generate_tests(module_info)
        assert '"""Test MyClass.my_method()"""' in code
        assert "result = instance.my_method()" in code

    def test_generate_method_test_async_no_args(self, generator):
        """8. async メソッドかつ引数がない場合 (L324)"""
        method_info = FunctionInfo(
            name="my_async_method",
            args=[],
            defaults_count=0,
            decorators=[],
            is_method=True,
            is_async=True,
            docstring=None,
            line_number=5,
            return_annotation=None,
            arg_annotations={}
        )
        cls_info = ClassInfo(
            name="MyClass",
            methods=[method_info],
            base_classes=[],
            line_number=1,
            docstring=None
        )
        module_info = ModuleInfo(
            file_path="dummy.py",
            module_name="dummy.module",
            classes=[cls_info],
            functions=[],
            imports=[]
        )
        code = generator.generate_tests(module_info)
        assert "result = await instance.my_async_method()" in code

    def test_generate_standalone_tests_async_with_without_args_no_docstring(self, generator):
        """10, 11, 12, 13. スタンドアロン async 関数 (引数あり・なし) で docstring なし、および同期関数の引数なしの場合 (L349-350, L357, L362-365, L370)"""
        # async, 引数あり, docstringあり
        func_async_args = FunctionInfo(
            name="async_args",
            args=["a", "b"],
            defaults_count=0,
            decorators=[],
            is_method=False,
            is_async=True,
            docstring="Docstring for async_args",
            line_number=1,
            return_annotation="str",
            arg_annotations={"a": "str", "b": "int"}
        )
        # async, 引数なし, docstringなし
        func_async_no_args = FunctionInfo(
            name="async_no_args",
            args=[],
            defaults_count=0,
            decorators=[],
            is_method=False,
            is_async=True,
            docstring=None,
            line_number=5,
            return_annotation=None,
            arg_annotations={}
        )
        # 同期, 引数なし, docstringなし
        func_sync_no_args = FunctionInfo(
            name="sync_no_args",
            args=[],
            defaults_count=0,
            decorators=[],
            is_method=False,
            is_async=False,
            docstring=None,
            line_number=10,
            return_annotation=None,
            arg_annotations={}
        )
        
        module_info = ModuleInfo(
            file_path="dummy.py",
            module_name="dummy.module",
            classes=[],
            functions=[func_async_args, func_async_no_args, func_sync_no_args],
            imports=[]
        )
        code = generator.generate_tests(module_info)
        
        # async_args (async, with args, return annotation, docstring)
        assert "async def test_async_args(self):" in code
        assert '"""Test async_args: Docstring for async_args"""' in code
        assert "result = await async_args(a=\"test_value\", b=1)" in code
        assert "# Expected return type: str" in code
        
        # async_no_args (async, no args, no docstring)
        assert "async def test_async_no_args(self):" in code
        assert '"""Test async_no_args()"""' in code
        assert "result = await async_no_args()" in code
        
        # sync_no_args (sync, no args, no docstring)
        assert "def test_sync_no_args(self):" in code
        assert '"""Test sync_no_args()"""' in code
        assert "result = sync_no_args()" in code

    def test_generate_arg_values_empty(self, generator):
        """14. _generate_arg_values で引数がない場合 (L382)"""
        func_info = FunctionInfo(
            name="no_args_func",
            args=[],
            defaults_count=0,
            decorators=[],
            is_method=False,
            is_async=False,
            docstring=None,
            line_number=1
        )
        res = generator._generate_arg_values(func_info)
        assert res == ""

    def test_type_to_default_value_title(self, generator):
        """15. _type_to_default_value で引数名に 'title' が含まれる場合 (L405)"""
        res = generator._type_to_default_value("", "video_title")
        assert res == '"test_value"'

    def test_type_to_default_value_fallback(self, generator):
        """16. _type_to_default_value でマッチする型ヒントも推論ルールもない場合 (L410)"""
        res = generator._type_to_default_value("", "param_xyz")
        assert "None" in res
        assert "TODO" in res

    def test_type_to_default_value_eq_only(self, generator):
        """17. _type_to_default_value で type_hint == key にのみマッチする場合 (L432)"""
        # startswith が False を返し、== が True を返すモックオブジェクトを渡す
        class MockTypeHint:
            def __init__(self, val):
                self.val = val
            def startswith(self, prefix):
                return False
            def __contains__(self, item):
                return False
            def __eq__(self, other):
                return self.val == other
                
        mock_hint = MockTypeHint("int")
        res = generator._type_to_default_value(mock_hint, "val")
        # "int" にマッチして "1" が返るはず
        assert res == "1"


class TestExtraEdgeCases:
    """ASTTestGenerator に対する追加のエッジケーステスト"""

    def test_init_invalid_workspace_path_type(self):
        """__init__ に不正な型の workspace_path を渡した場合、TypeErrorが発生すること"""
        with pytest.raises(TypeError):
            ASTTestGenerator(workspace_path=12345)  # type: ignore

    def test_analyze_module_none_path(self, generator):
        """analyze_module に None を渡した場合、TypeError が発生すること"""
        with pytest.raises(TypeError):
            generator.analyze_module(None)  # type: ignore

    def test_analyze_module_invalid_encoding(self, generator, tmp_path):
        """UTF-8以外の不正なエンコーディングのファイルを解析しようとしたとき UnicodeDecodeError が発生すること"""
        bad_enc_file = tmp_path / "bad_encoding.py"
        with open(bad_enc_file, "w", encoding="shift_jis") as f:
            f.write("# 日本語のコメント\nx = 1\n")
        
        gen_sjis = ASTTestGenerator(workspace_path=str(tmp_path))
        with pytest.raises(UnicodeDecodeError):
            gen_sjis.analyze_module("bad_encoding.py")

    def test_analyze_module_deeply_nested_structure(self, generator, tmp_path):
        """20層ネストされたクラスを正常に解析できること"""
        nested_code = ""
        indent = ""
        for i in range(20):
            nested_code += f"{indent}class Nest{i}:\n"
            indent += "    "
        nested_code += f"{indent}def leaf_method(self):\n{indent}    pass\n"
        
        nested_file = tmp_path / "deep_nest.py"
        nested_file.write_text(nested_code, encoding="utf-8")
        
        info = generator.analyze_module("deep_nest.py")
        assert len(info.classes) == 1
        assert info.classes[0].name == "Nest0"

    def test_type_to_default_value_none_arg_name(self, generator):
        """_type_to_default_value に arg_name=None を渡した場合、AttributeErrorが発生すること"""
        with pytest.raises(AttributeError):
            generator._type_to_default_value("", None)  # type: ignore

    def test_type_to_default_value_complex_types(self, generator):
        """複雑な複合型ヒントやネストされた型ヒントに対する推論結果"""
        res = generator._type_to_default_value("Callable[[CustomClass], float]", "callback")
        assert "None" in res
        
        res = generator._type_to_default_value("Union[int, str, None]", "data")
        assert "None" in res

        long_hint = "Dict[str, List[Tuple[int, Dict[str, Union[float, str]]]]]"
        res = generator._type_to_default_value(long_hint, "complex_arg")
        assert res == "{}"

    def test_generate_and_save_permission_error(self, generator, sample_module):
        """書き込み不可能なパスを指定した場合に OSError が発生すること"""
        with pytest.raises(OSError):
            generator.generate_and_save(sample_module, output_path="Z:\\invalid_drive_path\\test_auto.py")

    def test_analyze_varargs_kwargs(self, generator, tmp_path):
        """*args や **kwargs を含む関数の解析がエラーなく行われ、args から除外されること"""
        code = '''
def complex_args_func(a: int, b: str = "default", *args, **kwargs):
    pass
'''
        module_file = tmp_path / "complex_args.py"
        module_file.write_text(code, encoding="utf-8")
        
        gen_complex = ASTTestGenerator(workspace_path=str(tmp_path))
        info = gen_complex.analyze_module("complex_args.py")
        
        func_info = next(f for f in info.functions if f.name == "complex_args_func")
        assert "a" in func_info.args
        assert "b" in func_info.args
        assert "args" not in func_info.args
        assert "kwargs" not in func_info.args
        assert func_info.defaults_count == 1

    def test_analyze_relative_and_aliased_imports(self, generator, tmp_path):
        """相対インポートやエイリアス付きインポートが例外なく解析されること"""
        code = '''
from . import local_module
from ..parent import parent_module
import numpy as np
from math import sin as math_sin
'''
        module_file = tmp_path / "imports_test.py"
        module_file.write_text(code, encoding="utf-8")
        
        gen_imports = ASTTestGenerator(workspace_path=str(tmp_path))
        info = gen_imports.analyze_module("imports_test.py")
        assert "numpy" in info.imports
        assert "parent" in info.imports

    def test_type_to_default_value_huge_inputs(self, generator):
        """巨大な型ヒントや引数名が渡されても、クラッシュせずに正常にフォールバックされること"""
        huge_hint = "Union[" + ", ".join(["CustomType"] * 1000) + "]"
        res = generator._type_to_default_value(huge_hint, "param")
        assert "None" in res
        
        huge_name = "x" * 10000
        res = generator._type_to_default_value("", huge_name)
        assert "None" in res

    def test_generate_tests_invalid_type(self, generator):
        """generate_tests に不正な型のオブジェクトを渡したときに例外が発生すること"""
        with pytest.raises(AttributeError):
            generator.generate_tests(None)  # type: ignore
        with pytest.raises(AttributeError):
            generator.generate_tests(12345)  # type: ignore

    def test_extract_class_invalid_node(self, generator):
        """_extract_class や _extract_function に不正なノードを渡した際に例外が発生すること"""
        pass_node = ast.Pass()
        with pytest.raises(AttributeError):
            generator._extract_class(pass_node)  # type: ignore
        with pytest.raises(AttributeError):
            generator._extract_function(pass_node, is_method=False)  # type: ignore


class TestAdditionalEdgeCases:
    """追加のエッジケーステスト（None入力、極端な入力、特殊な引数、動的変更など）"""

    def test_init_with_path_object(self, tmp_path):
        """1. Path オブジェクトで初期化した場合でも正常に動作すること"""
        gen = ASTTestGenerator(workspace_path=tmp_path)
        assert isinstance(gen.workspace_path, Path)
        assert gen.workspace_path == tmp_path

    def test_analyze_posonly_and_kwonly_args(self, generator, tmp_path):
        """2. 位置専用引数(posonlyargs)やキーワード専用引数(kwonlyargs)を持つ関数の解析がクラッシュしないこと"""
        code = '''
def complex_sig(a, /, b, *, c=1):
    """Function with posonly and kwonly args."""
    return f"{a}:{b}:{c}"
'''
        module_file = tmp_path / "complex_sig.py"
        module_file.write_text(code, encoding="utf-8")
        
        gen_sig = ASTTestGenerator(workspace_path=str(tmp_path))
        info = gen_sig.analyze_module("complex_sig.py")
        func_info = next(f for f in info.functions if f.name == "complex_sig")
        # ast_test_generator は現在 node.args.args のみを抽出するため、a と b が抽出されるはず
        assert "b" in func_info.args
        assert "c" not in func_info.args

    def test_type_to_default_value_extreme_nesting_and_invalid_chars(self, generator):
        """3. 極端に深いジェネリックスのネストや、空の型ヒントに対してもクラッシュしないこと"""
        # 極端に深いネスト
        deep_hint = "Dict[str, List[Dict[str, List[Dict[str, List[int]]]]]]"
        res = generator._type_to_default_value(deep_hint, "deep_var")
        assert res == "{}"  # Dict が最外周のため

        # 特殊文字を含む不正な型ヒント名
        invalid_hint = "MyClass<Invalid>[Special]!!!"
        res = generator._type_to_default_value(invalid_hint, "invalid_var")
        assert "None" in res

    def test_dynamic_skip_patterns(self, generator, tmp_path):
        """4. SKIP_METHODS を動的に変更した場合に、テスト生成で反映されること"""
        code = '''
class DemoClass:
    def my_custom_skip(self):
        pass
    def normal_method(self):
        pass
'''
        module_file = tmp_path / "demo.py"
        module_file.write_text(code, encoding="utf-8")
        
        gen_skip = ASTTestGenerator(workspace_path=str(tmp_path))
        info = gen_skip.analyze_module("demo.py")
        
        # デフォルトでは my_custom_skip は生成されるはず
        code_default = gen_skip.generate_tests(info)
        assert "test_my_custom_skip" in code_default
        
        # SKIP_METHODS に my_custom_skip を追加
        gen_skip.SKIP_METHODS.add("my_custom_skip")
        code_skipped = gen_skip.generate_tests(info)
        assert "test_my_custom_skip" not in code_skipped
        assert "test_normal_method" in code_skipped
