"""
DS-035: モック自動生成エンジンのユニットテスト

TDD Red Phase: テストを先に作成し、実装でGreenにする。
"""

import ast
import os
import tempfile
import textwrap

import pytest

from backend.agents.orchestration.mock_test_generator import (
    DependencyCall,
    DependencyMap,
    MockTestGenerator,
)


# =============================================================================
# テスト用サンプルコード（文字列として定義し、AST解析に渡す）
# =============================================================================

SAMPLE_SERVICE_CODE = textwrap.dedent("""\
    import os
    import json
    from backend.services.external_api import ExternalAPI

    class SomeService:
        def __init__(self, api: ExternalAPI):
            self.api = api
            self.cache = {}

        def process_data(self, data: str) -> dict:
            result = self.api.fetch(data)
            if os.path.exists("/tmp/cache.json"):
                with open("/tmp/cache.json") as f:
                    cached = json.load(f)
            return result

        async def async_process(self, item: str) -> list:
            return await self.api.async_fetch(item)

    def standalone_helper(path: str) -> bool:
        return os.path.exists(path)
""")

SAMPLE_SUBPROCESS_CODE = textwrap.dedent("""\
    import subprocess

    class FFmpegRunner:
        def run_command(self, cmd: list) -> int:
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            while process.poll() is None:
                line = process.stdout.readline()
            return process.returncode
""")

SAMPLE_SIMPLE_CODE = textwrap.dedent("""\
    class SimpleClass:
        def __init__(self):
            self.value = 42

        def get_value(self) -> int:
            return self.value
""")

SAMPLE_FACTORY_CODE = textwrap.dedent("""\
    from backend.factories.widget import WidgetFactory

    class Builder:
        def build(self, name: str) -> dict:
            widget = WidgetFactory.create(name)
            return widget.to_dict()
""")


# =============================================================================
# TestDependencyCall — データクラスの基本テスト
# =============================================================================

class TestDependencyCall:
    """DependencyCall データクラスの生成とプロパティ確認"""

    def test_create_basic(self):
        """基本的な DependencyCall の生成"""
        dep = DependencyCall(
            module_path="backend.services.external_api",
            class_or_func="ExternalAPI",
            method_name="fetch",
            is_stdlib=False,
            patch_target="backend.services.external_api.ExternalAPI",
        )
        assert dep.module_path == "backend.services.external_api"
        assert dep.class_or_func == "ExternalAPI"
        assert dep.method_name == "fetch"
        assert dep.is_stdlib is False
        assert dep.patch_target == "backend.services.external_api.ExternalAPI"

    def test_create_stdlib(self):
        """stdlib の DependencyCall"""
        dep = DependencyCall(
            module_path="os.path",
            class_or_func="exists",
            method_name=None,
            is_stdlib=True,
            patch_target="os.path.exists",
        )
        assert dep.is_stdlib is True
        assert dep.method_name is None

    def test_patch_target_format(self):
        """patch_target がドット区切りの正しいフォーマットであること"""
        dep = DependencyCall(
            module_path="json",
            class_or_func="loads",
            method_name=None,
            is_stdlib=True,
            patch_target="json.loads",
        )
        assert "." in dep.patch_target
        # patch_target はインポート可能な形式であるべき
        parts = dep.patch_target.split(".")
        assert all(part.isidentifier() for part in parts)


# =============================================================================
# TestAnalyzeDependencies — 依存関係抽出のコアテスト
# =============================================================================

class TestAnalyzeDependencies:
    """MockTestGenerator.analyze_dependencies() のテスト"""

    @pytest.fixture
    def generator(self):
        return MockTestGenerator()

    @pytest.fixture
    def service_tree(self):
        return ast.parse(SAMPLE_SERVICE_CODE)

    def test_detect_self_attribute_call(self, generator):
        """パターン1: self.xxx.method() の検出"""
        tree = ast.parse(SAMPLE_SERVICE_CODE)
        dep_map = generator.analyze_dependencies_from_tree(
            tree, "backend.services.some_service",
            imports=["os", "json", "backend.services.external_api"],
        )
        # SomeService.process_data には self.api.fetch() がある
        assert "SomeService" in dep_map.class_method_deps
        process_deps = dep_map.class_method_deps["SomeService"].get("process_data", [])
        attr_deps = [d for d in process_deps if d.class_or_func == "ExternalAPI" or "api" in d.patch_target.lower()]
        assert len(attr_deps) >= 1, f"self.api.fetch() が検出されるべき: {process_deps}"

    def test_detect_module_function_call(self, generator):
        """パターン2: os.path.exists() の検出"""
        tree = ast.parse(SAMPLE_SERVICE_CODE)
        dep_map = generator.analyze_dependencies_from_tree(
            tree, "backend.services.some_service",
            imports=["os", "json", "backend.services.external_api"],
        )
        process_deps = dep_map.class_method_deps.get("SomeService", {}).get("process_data", [])
        os_deps = [d for d in process_deps if "os.path" in d.patch_target]
        assert len(os_deps) >= 1, f"os.path.exists() が検出されるべき: {process_deps}"

    def test_detect_json_load(self, generator):
        """パターン2: json.load() の検出"""
        tree = ast.parse(SAMPLE_SERVICE_CODE)
        dep_map = generator.analyze_dependencies_from_tree(
            tree, "backend.services.some_service",
            imports=["os", "json", "backend.services.external_api"],
        )
        process_deps = dep_map.class_method_deps.get("SomeService", {}).get("process_data", [])
        json_deps = [d for d in process_deps if "json" in d.patch_target]
        assert len(json_deps) >= 1, f"json.load() が検出されるべき: {process_deps}"

    def test_detect_standalone_function_deps(self, generator):
        """トップレベル関数の依存検出"""
        tree = ast.parse(SAMPLE_SERVICE_CODE)
        dep_map = generator.analyze_dependencies_from_tree(
            tree, "backend.services.some_service",
            imports=["os", "json", "backend.services.external_api"],
        )
        func_deps = dep_map.function_deps.get("standalone_helper", [])
        os_deps = [d for d in func_deps if "os.path" in d.patch_target]
        assert len(os_deps) >= 1, f"standalone_helper の os.path.exists 依存が検出されるべき: {func_deps}"

    def test_detect_class_direct_call(self, generator):
        """パターン3: ClassName.method() 直接呼び出しの検出"""
        tree = ast.parse(SAMPLE_FACTORY_CODE)
        dep_map = generator.analyze_dependencies_from_tree(
            tree, "backend.builders.builder",
            imports=["backend.factories.widget"],
        )
        build_deps = dep_map.class_method_deps.get("Builder", {}).get("build", [])
        factory_deps = [d for d in build_deps if "WidgetFactory" in d.patch_target or "WidgetFactory" in d.class_or_func]
        assert len(factory_deps) >= 1, f"WidgetFactory.create() が検出されるべき: {build_deps}"

    def test_no_deps_for_simple_class(self, generator):
        """外部依存のないクラスでは空の依存マップが返る"""
        tree = ast.parse(SAMPLE_SIMPLE_CODE)
        dep_map = generator.analyze_dependencies_from_tree(
            tree, "backend.simple",
            imports=[],
        )
        simple_deps = dep_map.class_method_deps.get("SimpleClass", {}).get("get_value", [])
        assert len(simple_deps) == 0

    def test_async_method_detected(self, generator):
        """async メソッドの依存も検出される"""
        tree = ast.parse(SAMPLE_SERVICE_CODE)
        dep_map = generator.analyze_dependencies_from_tree(
            tree, "backend.services.some_service",
            imports=["os", "json", "backend.services.external_api"],
        )
        async_deps = dep_map.class_method_deps.get("SomeService", {}).get("async_process", [])
        assert len(async_deps) >= 1, f"async_process の依存が検出されるべき: {async_deps}"

    def test_stdlib_classification(self, generator):
        """stdlib モジュールが正しく分類される"""
        tree = ast.parse(SAMPLE_SERVICE_CODE)
        dep_map = generator.analyze_dependencies_from_tree(
            tree, "backend.services.some_service",
            imports=["os", "json", "backend.services.external_api"],
        )
        all_deps = []
        for deps in dep_map.class_method_deps.get("SomeService", {}).values():
            all_deps.extend(deps)
        stdlib_deps = [d for d in all_deps if d.is_stdlib]
        non_stdlib = [d for d in all_deps if not d.is_stdlib]
        assert len(stdlib_deps) >= 1, "stdlib依存が1つ以上検出されるべき"
        assert len(non_stdlib) >= 1, "非stdlib依存が1つ以上検出されるべき"


# =============================================================================
# TestResolveSelfAttribute — __init__ 属性マッピング
# =============================================================================

class TestResolveSelfAttribute:
    """__init__ 内の self.xxx = YYY() パターンの解析"""

    @pytest.fixture
    def generator(self):
        return MockTestGenerator()

    def test_resolve_typed_attribute(self, generator):
        """型ヒント付きの self.api = api の解決"""
        tree = ast.parse(SAMPLE_SERVICE_CODE)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "SomeService":
                attrs = generator._resolve_self_attributes(node)
                # self.api = api (引数から ExternalAPI 型)
                assert "api" in attrs
                break

    def test_resolve_literal_attribute(self, generator):
        """self.cache = {} のようなリテラル代入"""
        tree = ast.parse(SAMPLE_SERVICE_CODE)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "SomeService":
                attrs = generator._resolve_self_attributes(node)
                # self.cache = {} はリテラルなのでモック不要
                assert "cache" not in attrs or attrs.get("cache") is None
                break

    def test_no_init(self, generator):
        """__init__ がないクラスでも空の辞書が返る"""
        code = textwrap.dedent("""\
            class NoInit:
                def method(self):
                    pass
        """)
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "NoInit":
                attrs = generator._resolve_self_attributes(node)
                assert attrs == {}
                break

    def test_multiple_attributes(self, generator):
        """複数の依存属性を持つクラス"""
        code = textwrap.dedent("""\
            from a import A
            from b import B
            class Multi:
                def __init__(self, svc_a: A, svc_b: B):
                    self.svc_a = svc_a
                    self.svc_b = svc_b
        """)
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "Multi":
                attrs = generator._resolve_self_attributes(node)
                assert "svc_a" in attrs
                assert "svc_b" in attrs
                break


# =============================================================================
# TestGenerateMockTests — テストコード生成の正確性
# =============================================================================

class TestGenerateMockTests:
    """generate_mock_tests() が正しいテストコードを生成するか"""

    @pytest.fixture
    def generator(self):
        return MockTestGenerator()

    def test_generates_valid_python(self, generator):
        """生成コードが構文的に正しいPythonであること"""
        tree = ast.parse(SAMPLE_SERVICE_CODE)
        dep_map = generator.analyze_dependencies_from_tree(
            tree, "backend.services.some_service",
            imports=["os", "json", "backend.services.external_api"],
        )
        code = generator.generate_mock_tests_from_tree(
            tree, "backend.services.some_service", dep_map,
        )
        # 構文検証
        ast.parse(code)

    def test_contains_patch_decorator(self, generator):
        """@patch デコレータが含まれること"""
        tree = ast.parse(SAMPLE_SERVICE_CODE)
        dep_map = generator.analyze_dependencies_from_tree(
            tree, "backend.services.some_service",
            imports=["os", "json", "backend.services.external_api"],
        )
        code = generator.generate_mock_tests_from_tree(
            tree, "backend.services.some_service", dep_map,
        )
        assert "@patch(" in code, f"@patch デコレータが含まれるべき:\n{code[:500]}"

    def test_contains_mock_import(self, generator):
        """unittest.mock のインポートが含まれること"""
        tree = ast.parse(SAMPLE_SERVICE_CODE)
        dep_map = generator.analyze_dependencies_from_tree(
            tree, "backend.services.some_service",
            imports=["os", "json", "backend.services.external_api"],
        )
        code = generator.generate_mock_tests_from_tree(
            tree, "backend.services.some_service", dep_map,
        )
        assert "from unittest.mock import" in code

    def test_async_uses_async_mock(self, generator):
        """async メソッドには AsyncMock が使われること"""
        tree = ast.parse(SAMPLE_SERVICE_CODE)
        dep_map = generator.analyze_dependencies_from_tree(
            tree, "backend.services.some_service",
            imports=["os", "json", "backend.services.external_api"],
        )
        code = generator.generate_mock_tests_from_tree(
            tree, "backend.services.some_service", dep_map,
        )
        # async_process のテストにはAsyncMockまたはpytest.mark.asyncioが含まれるべき
        assert "asyncio" in code or "AsyncMock" in code

    def test_no_deps_no_patch(self, generator):
        """依存のないクラスには @patch が生成されないこと"""
        tree = ast.parse(SAMPLE_SIMPLE_CODE)
        dep_map = generator.analyze_dependencies_from_tree(
            tree, "backend.simple", imports=[],
        )
        code = generator.generate_mock_tests_from_tree(
            tree, "backend.simple", dep_map,
        )
        assert "@patch(" not in code

    def test_mock_return_value_from_type_hint(self, generator):
        """型ヒントから return_value が推定されること"""
        tree = ast.parse(SAMPLE_SERVICE_CODE)
        dep_map = generator.analyze_dependencies_from_tree(
            tree, "backend.services.some_service",
            imports=["os", "json", "backend.services.external_api"],
        )
        code = generator.generate_mock_tests_from_tree(
            tree, "backend.services.some_service", dep_map,
        )
        # process_data は dict を返す → return_value に dict 関連が含まれるべき
        assert "return_value" in code


# =============================================================================
# TestSafePopenMock — subprocess.Popen 特別処理
# =============================================================================

class TestSafePopenMock:
    """subprocess.Popen 検出時の safe_popen_mock 自動挿入"""

    @pytest.fixture
    def generator(self):
        return MockTestGenerator()

    def test_detect_subprocess_popen(self, generator):
        """subprocess.Popen の依存が検出されること"""
        tree = ast.parse(SAMPLE_SUBPROCESS_CODE)
        dep_map = generator.analyze_dependencies_from_tree(
            tree, "backend.runners.ffmpeg",
            imports=["subprocess"],
        )
        run_deps = dep_map.class_method_deps.get("FFmpegRunner", {}).get("run_command", [])
        popen_deps = [d for d in run_deps if "Popen" in d.class_or_func or "subprocess" in d.patch_target]
        assert len(popen_deps) >= 1, f"subprocess.Popen が検出されるべき: {run_deps}"

    def test_generates_safe_popen_fixture(self, generator):
        """subprocess.Popen 検出時に safe_popen_mock fixture が使われること"""
        tree = ast.parse(SAMPLE_SUBPROCESS_CODE)
        dep_map = generator.analyze_dependencies_from_tree(
            tree, "backend.runners.ffmpeg",
            imports=["subprocess"],
        )
        code = generator.generate_mock_tests_from_tree(
            tree, "backend.runners.ffmpeg", dep_map,
        )
        assert "safe_popen_mock" in code, f"safe_popen_mock が含まれるべき:\n{code}"

    def test_popen_mock_has_returncode(self, generator):
        """safe_popen_mock に returncode パラメータが含まれること"""
        tree = ast.parse(SAMPLE_SUBPROCESS_CODE)
        dep_map = generator.analyze_dependencies_from_tree(
            tree, "backend.runners.ffmpeg",
            imports=["subprocess"],
        )
        code = generator.generate_mock_tests_from_tree(
            tree, "backend.runners.ffmpeg", dep_map,
        )
        assert "returncode" in code, f"returncode が含まれるべき:\n{code}"


# =============================================================================
# TestGenerateAndSaveMocked — E2E: 解析→生成→書き込み→構文検証
# =============================================================================

class TestGenerateAndSaveMocked:
    """generate_and_save_mocked() のE2Eテスト"""

    @pytest.fixture
    def generator(self):
        return MockTestGenerator()

    @pytest.fixture
    def temp_module(self, tmp_path):
        """一時的なテスト用モジュールを作成"""
        mod_file = tmp_path / "sample_module.py"
        mod_file.write_text(SAMPLE_SERVICE_CODE, encoding="utf-8")
        return mod_file

    def test_save_generates_file(self, generator, temp_module, tmp_path):
        """ファイルが実際に生成されること"""
        output = tmp_path / "test_sample_module_mock.py"
        result_path = generator.generate_and_save_mocked(
            source_path=str(temp_module),
            output_path=str(output),
            module_name="backend.services.some_service",
        )
        assert os.path.exists(result_path)

    def test_saved_file_is_valid_python(self, generator, temp_module, tmp_path):
        """生成ファイルが構文的に正しいPythonであること"""
        output = tmp_path / "test_sample_module_mock.py"
        result_path = generator.generate_and_save_mocked(
            source_path=str(temp_module),
            output_path=str(output),
            module_name="backend.services.some_service",
        )
        content = open(result_path, encoding="utf-8").read()
        ast.parse(content)  # SyntaxError が出なければOK

    def test_saved_file_contains_test_class(self, generator, temp_module, tmp_path):
        """生成ファイルにテストクラスが含まれること"""
        output = tmp_path / "test_sample_module_mock.py"
        result_path = generator.generate_and_save_mocked(
            source_path=str(temp_module),
            output_path=str(output),
            module_name="backend.services.some_service",
        )
        content = open(result_path, encoding="utf-8").read()
        assert "class Test" in content

    def test_saved_file_utf8(self, generator, temp_module, tmp_path):
        """出力ファイルがUTF-8で書き込まれること（ファイルI/O安全規約）"""
        output = tmp_path / "test_sample_module_mock.py"
        result_path = generator.generate_and_save_mocked(
            source_path=str(temp_module),
            output_path=str(output),
            module_name="backend.services.some_service",
        )
        # UTF-8 で読めることを確認
        with open(result_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert len(content) > 0


# =============================================================================
# TestEdgeCases — エッジケース
# =============================================================================

class TestEdgeCases:
    """エッジケースのテスト"""

    @pytest.fixture
    def generator(self):
        return MockTestGenerator()

    def test_empty_module(self, generator):
        """空のモジュールでもエラーにならないこと"""
        tree = ast.parse("")
        dep_map = generator.analyze_dependencies_from_tree(
            tree, "backend.empty", imports=[],
        )
        assert len(dep_map.function_deps) == 0
        assert len(dep_map.class_method_deps) == 0

    def test_module_with_only_imports(self, generator):
        """インポートのみのモジュール"""
        code = "import os\nimport json\n"
        tree = ast.parse(code)
        dep_map = generator.analyze_dependencies_from_tree(
            tree, "backend.imports_only", imports=["os", "json"],
        )
        assert len(dep_map.function_deps) == 0
        assert len(dep_map.class_method_deps) == 0

    def test_nested_function_calls(self, generator):
        """ネストされた関数呼び出し"""
        code = textwrap.dedent("""\
            import json
            def nested(data: str) -> dict:
                return json.loads(json.dumps(data))
        """)
        tree = ast.parse(code)
        dep_map = generator.analyze_dependencies_from_tree(
            tree, "backend.nested", imports=["json"],
        )
        func_deps = dep_map.function_deps.get("nested", [])
        json_deps = [d for d in func_deps if "json" in d.patch_target]
        # json.loads と json.dumps の両方が検出されるべき
        assert len(json_deps) >= 2, f"ネストされたjson呼び出しが検出されるべき: {func_deps}"

    def test_decorator_not_treated_as_dependency(self, generator):
        """デコレータは依存として扱わない"""
        code = textwrap.dedent("""\
            import functools
            @functools.lru_cache
            def cached_func(x: int) -> int:
                return x * 2
        """)
        tree = ast.parse(code)
        dep_map = generator.analyze_dependencies_from_tree(
            tree, "backend.decorated", imports=["functools"],
        )
        func_deps = dep_map.function_deps.get("cached_func", [])
        # 関数ボディ内の依存のみ（デコレータは除外）
        assert len(func_deps) == 0, f"デコレータは依存に含めるべきでない: {func_deps}"

    def test_lambda_ignored(self, generator):
        """lambda内の呼び出しは依存として検出しない（複雑すぎるため）"""
        code = textwrap.dedent("""\
            import os
            def with_lambda(items: list) -> list:
                return list(filter(lambda x: os.path.exists(x), items))
        """)
        tree = ast.parse(code)
        dep_map = generator.analyze_dependencies_from_tree(
            tree, "backend.with_lambda", imports=["os"],
        )
        # lambda内のos.path.existsは検出してもしなくても良い（実装次第）
        # エラーにならないことが重要
        assert isinstance(dep_map, DependencyMap)
