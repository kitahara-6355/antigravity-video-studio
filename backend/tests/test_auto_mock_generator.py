import sys
import ast
import os
import runpy
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from agents.orchestration.auto_mock_generator import (
    ImportInfo,
    ExternalCall,
    ModuleAnalysis,
    MockFixture,
    GenerationResult,
    AutoMockGenerator,
)


def test_import_info():
    """ImportInfo のテスト"""
    imp1 = ImportInfo(
        module="os",
        name=None,
        alias=None,
        is_from_import=False,
        lineno=10,
    )
    assert imp1.full_path == "os"

    imp2 = ImportInfo(
        module="pathlib",
        name="Path",
        alias="P",
        is_from_import=True,
        lineno=12,
    )
    assert imp2.full_path == "pathlib.Path"


def test_module_analysis():
    """ModuleAnalysis のテスト"""
    analysis = ModuleAnalysis(module_path="test_module")
    assert not analysis.has_dependencies
    assert analysis.summary == {
        "db": 0,
        "http": 0,
        "subprocess": 0,
        "file_io": 0,
        "total_imports": 0,
        "total_external_calls": 0,
    }

    analysis.db_dependencies.append("get_db")
    assert analysis.has_dependencies
    assert analysis.summary["db"] == 1


def test_to_snake_case():
    """_to_snake_case ユーティリティのテスト"""
    assert AutoMockGenerator._to_snake_case("CamelCase") == "camel_case"
    assert AutoMockGenerator._to_snake_case("HTTPClient") == "http_client"
    assert AutoMockGenerator._to_snake_case("simple") == "simple"


def test_detect_project_root():
    """_detect_project_root のテスト"""
    gen = AutoMockGenerator()
    root = gen._detect_project_root()
    assert root.exists()
    assert (root / "backend").exists() or root.name == "video-automation"

    # フォールバック処理 (909行目) のカバー
    # backend ディレクトリが存在しないと判定させて Path.cwd() を返させる
    with patch.object(Path, "exists", return_value=False):
        fallback_root = gen._detect_project_root()
        assert fallback_root == Path.cwd()


def test_resolve_path():
    """_resolve_path のテスト"""
    root = Path.cwd().resolve()
    gen = AutoMockGenerator(project_root=str(root))
    
    # 絶対パスの場合
    abs_p = root.parent
    assert gen._resolve_path(str(abs_p)) == abs_p

    # 相対パスの場合
    rel_p = "backend/services/video.py"
    resolved = gen._resolve_path(rel_p)
    assert resolved == root / rel_p


def test_path_to_module_name():
    """_path_to_module_name のテスト"""
    root = Path.cwd().resolve()
    gen = AutoMockGenerator(project_root=str(root))
    
    abs_path = root / "backend" / "services" / "video.py"
    assert gen._path_to_module_name(abs_path) == "backend.services.video"

    # __init__.py (896行目 pop) のカバー
    abs_init = root / "backend" / "__init__.py"
    assert gen._path_to_module_name(abs_init) == "backend"

    # プロジェクトルート外のパスの場合 (ValueErrorフォールバック)
    out_path = Path("/another/root/video.py").resolve()
    res = gen._path_to_module_name(out_path)
    assert "video" in res


def test_extract_imports():
    """_extract_imports のテスト"""
    source = """
import os
import sys as system
from pathlib import Path
from collections import namedtuple as nt
"""
    tree = ast.parse(source)
    gen = AutoMockGenerator()
    imports = gen._extract_imports(tree)

    assert len(imports) == 4
    # os
    assert imports[0].module == "os"
    assert not imports[0].is_from_import
    # sys as system
    assert imports[1].module == "sys"
    assert imports[1].alias == "system"
    # from pathlib import Path
    assert imports[2].module == "pathlib"
    assert imports[2].name == "Path"
    assert imports[2].is_from_import
    # from collections import namedtuple as nt
    assert imports[3].module == "collections"
    assert imports[3].name == "namedtuple"
    assert imports[3].alias == "nt"


def test_classify_external_call():
    """_classify_external_call のテスト"""
    source = """
import httpx as client
import some_db_module as get_db
from db_module import Session
import subprocess
from pathlib import Path
import json

def func():
    open("test.txt", "r")
    subprocess.Popen(["ls"])
    subprocess.run(["ls"])
    get_db()
    Session()  # name一致DBインポート (591行目カバー)
    engine()   # インポートなしDB呼び出し (594行目カバー)
    client.get("https://example.com")
    Path("test.txt").read_text()
    Path("test.txt").write_text()
    Path("test.txt").read_bytes()
    Path("test.txt").write_bytes()
    json.loads("{}") # stdlibなのでスキップされるはず (563行目カバー)
    unknown_function() # 未分類呼び出しの末尾フォールバック (572行目カバー)
    self.method() # スキップされるはず
"""
    tree = ast.parse(source)
    gen = AutoMockGenerator()
    imports = gen._extract_imports(tree)
    calls = gen._extract_external_calls(tree, imports)

    # 各要素の詳細確認とカバー
    open_call = next(c for c in calls if c.func_name == "open")
    assert open_call.module_path == "builtins"

    popen_call = next(c for c in calls if c.func_name == "Popen")
    assert popen_call.module_path == "subprocess"

    # get_db (592-593行目 aliasカバー)
    db_call = next(c for c in calls if c.func_name == "get_db")
    assert db_call.category == "db"
    assert db_call.module_path == "some_db_module"

    # Session (591行目 nameカバー)
    session_call = next(c for c in calls if c.func_name == "Session")
    assert session_call.category == "db"
    assert session_call.module_path == "db_module"

    # engine (594行目 Noneカバー)
    engine_call = next(c for c in calls if c.func_name == "engine")
    assert engine_call.category == "db"
    assert engine_call.module_path == "engine"

    # client.get (580行目 http_call startswith カバー)
    http_call = next(c for c in calls if c.func_name == "get")
    assert http_call.module_path == "client"

    read_text_call = next(c for c in calls if c.func_name == "read_text")
    assert read_text_call.category == "file_io"
    assert read_text_call.module_path == "pathlib.Path"

    # unparse 例外ハンドラ (493-494行目カバー)
    node = ast.Call(func="invalid_func_node", args=[], keywords=[])
    assert gen._classify_external_call(node, set(), []) is None


def test_attach_scope():
    """_attach_scope のクラスおよび関数所属検出テスト"""
    source = """
class MyClass:
    def method(self):
        open("test.txt")

def normal_func():
    subprocess.run(["ls"])
"""
    tree = ast.parse(source)
    gen = AutoMockGenerator()
    imports = [
        ImportInfo(module="subprocess", name=None, alias=None, is_from_import=False, lineno=1)
    ]
    calls = gen._extract_external_calls(tree, imports)

    # normal_func 内の subprocess.run
    func_call = next(c for c in calls if c.func_name == "run")
    assert func_call.in_function == "normal_func"
    assert func_call.in_class is None

    # MyClass.method 内の open (609-611行目クラスメソッドスコープカバー)
    method_call = next(c for c in calls if c.func_name == "open")
    assert method_call.in_class == "MyClass"
    assert method_call.in_function == "method"


def test_categorize_dependencies():
    """_categorize_dependencies のテスト"""
    gen = AutoMockGenerator()
    analysis = ModuleAnalysis(module_path="test_module")
    analysis.external_calls = [
        ExternalCall("get_db", "db", "get_db", 10, "db"),
        ExternalCall("get", "httpx", "httpx.get", 11, "http"),
        ExternalCall("Popen", "subprocess", "subprocess.Popen", 12, "subprocess"),
        ExternalCall("run", "subprocess", "subprocess.run", 13, "subprocess"),
        ExternalCall("open", "builtins", "open", 14, "file_io"),
        ExternalCall("read_text", "pathlib.Path", "Path.read_text", 15, "file_io"),
    ]

    gen._categorize_dependencies(analysis)

    assert "get_db" in analysis.db_dependencies
    assert "httpx.get" in analysis.http_dependencies
    assert "subprocess.Popen" in analysis.subprocess_calls
    assert "subprocess.run" in analysis.subprocess_calls
    assert "open" in analysis.file_io_calls
    assert "Path.read_text" in analysis.file_io_calls


def test_generate_mocks_with_duplicates():
    """generate_mocks における重複除外の検証 (264-267, 278-281, 285-288カバー)"""
    gen = AutoMockGenerator()
    analysis = ModuleAnalysis(module_path="services.video")
    
    # 同一カテゴリ・同一名のフィクスチャが複数生成されるように重複データを仕込む
    analysis.db_dependencies = ["get_db", "get_db"]
    analysis.subprocess_calls = ["subprocess.run", "subprocess.run"]
    analysis.file_io_calls = ["open", "open"]

    fixtures = gen.generate_mocks(analysis)
    
    # 重複除外されて各1つずつになっていることを確認
    db_fixtures = [f for f in fixtures if f.category == "db"]
    sub_fixtures = [f for f in fixtures if f.category == "subprocess"]
    io_fixtures = [f for f in fixtures if f.category == "file_io"]

    assert len(db_fixtures) == 1
    assert len(sub_fixtures) == 1
    assert len(io_fixtures) == 1


def test_generate_fixtures():
    """各モックフィクスチャの生成コード検証"""
    gen = AutoMockGenerator()

    # DBフィクスチャ
    db_fix = gen._generate_db_fixture("get_db", "services.video")
    assert db_fix.name == "mock_get_db"
    assert "@pytest.fixture" in db_fix.fixture_code
    assert "MagicMock()" in db_fix.fixture_code

    # HTTPフィクスチャ
    http_fix = gen._generate_http_fixture("httpx.get", "services.video")
    assert http_fix.name == "mock_httpx_client"
    assert "status_code = 200" in http_fix.fixture_code

    # Subprocess Popen フィクスチャ (GEMINI.md subprocess.Popen モック安全規約に準拠しているか)
    popen_fix = gen._generate_subprocess_fixture("subprocess.Popen", "services.video")
    assert popen_fix.name == "safe_popen_mock"
    assert "proc.poll.return_value = 0" in popen_fix.fixture_code
    assert 'proc.stdout.readline.return_value = ""' in popen_fix.fixture_code

    # Subprocess run フィクスチャ
    run_fix = gen._generate_subprocess_fixture("subprocess.run", "services.video")
    assert run_fix.name == "mock_subprocess_run"

    # File I/O open フィクスチャ
    open_fix = gen._generate_file_io_fixture("open", "services.video")
    assert open_fix.name == "mock_open_file"
    assert "builtins.open" in open_fix.fixture_code

    # File I/O read_text フィクスチャ
    read_text_fix = gen._generate_file_io_fixture("read_text", "services.video")
    assert read_text_fix.name == "mock_path_read_text"

    # File I/O write_text フィクスチャ
    write_text_fix = gen._generate_file_io_fixture("write_text", "services.video")
    assert write_text_fix.name == "mock_path_write_text"
    assert "None" in write_text_fix.fixture_code

    # File I/O その他 (e.g. read_file)
    custom_io_fix = gen._generate_file_io_fixture("read_file", "services.video")
    assert custom_io_fix.name == "mock_read_file"


def test_generate_conftest():
    """generate_conftest のテスト"""
    gen = AutoMockGenerator()
    fixtures = [
        MockFixture("mock_get_db", "db.get_db", "def mock_get_db(): pass", "db", "DB"),
        MockFixture("safe_popen_mock", "subprocess.Popen", "def safe_popen_mock(): MagicMock()", "subprocess", "Subprocess"),
    ]

    code = gen.generate_conftest(fixtures)
    assert "import pytest" in code
    assert "MagicMock" in code
    assert "def mock_get_db():" in code
    assert "def safe_popen_mock():" in code

    # 構文エラーを発生させる
    bad_fixtures = [
        MockFixture("bad", "bad", "def bad(invalid syntax", "db", "Bad"),
    ]
    with pytest.raises(SyntaxError):
        gen.generate_conftest(bad_fixtures)


def test_generate_conftest_with_output(tmp_path):
    """ファイル出力を伴う generate_conftest のテスト"""
    gen = AutoMockGenerator()
    fixtures = [
        MockFixture("mock_get_db", "db.get_db", "def mock_get_db(): pass", "db", "DB"),
    ]
    out_file = tmp_path / "conftest.py"
    gen.generate_conftest(fixtures, output_path=str(out_file))

    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "def mock_get_db():" in content


def test_auto_generate_for_module_success(tmp_path):
    """auto_generate_for_module 成功ケース"""
    gen = AutoMockGenerator()
    dummy_module = tmp_path / "dummy.py"
    dummy_module.write_text("import httpx\nhttpx.get('url')", encoding="utf-8")

    result = gen.auto_generate_for_module(str(dummy_module))
    assert result.success
    assert len(result.fixtures) == 1
    assert result.fixtures[0].category == "http"
    assert "mock_httpx_client" in result.conftest_code


def test_auto_generate_for_module_failure():
    """auto_generate_for_module 失敗ケース (ファイルが存在しない場合)"""
    gen = AutoMockGenerator()
    result = gen.auto_generate_for_module("non_existent_file.py")
    assert not result.success
    assert result.error is not None


def test_cli_main_runpy(tmp_path):
    """runpy を使用した CLI エントリポイントの動作検証 (923-977行目のカバレッジカバー)"""
    # ダミーファイルを生成して解析させる
    dummy_module = tmp_path / "dummy_cli.py"
    dummy_module.write_text("import httpx\nhttpx.get('url')", encoding="utf-8")
    out_conftest = tmp_path / "conftest.py"

    # 1. 正常系 (dry-run & output 指定)
    test_args = [
        "auto_mock_generator.py",
        str(dummy_module),
        "-o",
        str(out_conftest),
        "--project-root",
        str(Path.cwd()),
    ]
    
    with patch("sys.argv", test_args):
        runpy.run_module(
            "agents.orchestration.auto_mock_generator",
            run_name="__main__",
            alter_sys=True
        )
    
    assert out_conftest.exists()

    # 2. 正常系 (dry-run のみ、出力指定なし -> 標準出力に表示するルート 974行目カバー)
    test_args_stdout = [
        "auto_mock_generator.py",
        str(dummy_module),
        "--dry-run",
        "--project-root",
        str(Path.cwd()),
    ]
    with patch("sys.argv", test_args_stdout), patch("builtins.print") as mock_print:
        runpy.run_module(
            "agents.orchestration.auto_mock_generator",
            run_name="__main__",
            alter_sys=True
        )
        mock_print.assert_called()

    # 3. 異常系 (ファイルなし -> sys.exit(1) で終了することの確認)
    test_args_fail = [
        "auto_mock_generator.py",
        "non_existent_module.py",
        "--dry-run"
    ]
    with patch("sys.argv", test_args_fail):
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_module(
                "agents.orchestration.auto_mock_generator",
                run_name="__main__",
                alter_sys=True
            )
        assert excinfo.value.code == 1



def test_to_snake_case_edge_cases():
    """_to_snake_case のエッジケース"""
    assert AutoMockGenerator._to_snake_case("") == ""
    assert AutoMockGenerator._to_snake_case("1234") == "1234"
    assert AutoMockGenerator._to_snake_case("A") == "a"
    assert AutoMockGenerator._to_snake_case("a") == "a"
    assert AutoMockGenerator._to_snake_case("MyAPIClientTest") == "my_api_client_test"
    assert AutoMockGenerator._to_snake_case("Camel-Case_Pascal") == "camel-_case__pascal"


def test_path_to_module_name_edge_cases():
    """_path_to_module_name のエッジケース"""
    root = Path.cwd().resolve()
    gen = AutoMockGenerator(project_root=str(root))
    
    # プロジェクトルート外のパス
    abs_out = Path("/some/outside/path/to/module.py")
    res = gen._path_to_module_name(abs_out)
    assert "module" in res
    assert "outside" in res
    
    # .txtなどの異なる拡張子
    txt_path = root / "backend" / "notes.txt"
    assert gen._path_to_module_name(txt_path) == "backend.notes.txt"
    
    # __init__something.py の場合（末尾が__init__ではない）
    init_like = root / "backend" / "__init__custom.py"
    assert gen._path_to_module_name(init_like) == "backend.__init__custom"


def test_resolve_path_edge_cases():
    """_resolve_path のエッジケース"""
    gen = AutoMockGenerator(project_root=None) # project_root自動検出
    
    # ドット区切りのパス
    assert gen._resolve_path("./backend/services/video.py").is_absolute()
    # 空文字列のパス
    assert gen._resolve_path("").is_absolute()


def test_extract_imports_edge_cases():
    """_extract_imports の構文エラーや特殊インポートのテスト"""
    gen = AutoMockGenerator()
    
    # 空のソースコード
    tree_empty = ast.parse("")
    assert gen._extract_imports(tree_empty) == []

    # コメントのみのソースコード
    tree_comment = ast.parse("# this is a comment\n# another comment")
    assert gen._extract_imports(tree_comment) == []

    # 相対インポート
    tree_rel = ast.parse("from . import local_module\nfrom ..parent import sister")
    imports = gen._extract_imports(tree_rel)
    assert len(imports) == 2
    assert imports[0].module == ""
    assert imports[0].name == "local_module"
    assert imports[1].module == "parent"
    assert imports[1].name == "sister"


def test_classify_external_call_edge_cases():
    """_classify_external_call のエッジケース（特殊な呼び出し形式など）"""
    gen = AutoMockGenerator()
    
    # func(...)() のような呼び出し
    source = "func()()"
    tree = ast.parse(source)
    calls = gen._extract_external_calls(tree, [])
    assert len(calls) == 0

    # node が ast.Call ではない不正ノード
    node_not_call = ast.Pass()
    with pytest.raises(AttributeError):
        gen._classify_external_call(node_not_call, set(), [])


def test_collect_imports_edge_cases():
    """_collect_imports のエッジケース"""
    gen = AutoMockGenerator()
    
    # 空のリスト
    assert gen._collect_imports([]) == ["import pytest"]
    
    # patch や MagicMock を含まない fixture_code
    fixtures_simple = [
        MockFixture("mock_func", "module.func", "def mock_func(): pass", "custom", "Custom")
    ]
    assert gen._collect_imports(fixtures_simple) == ["import pytest"]

    # 重複する patch や MagicMock を含む fixture_code
    fixtures_dup = [
        MockFixture("mock_1", "module.func1", "patch('a'); MagicMock()", "custom", "Custom"),
        MockFixture("mock_2", "module.func2", "patch('b'); MagicMock()", "custom", "Custom"),
    ]
    imports = gen._collect_imports(fixtures_dup)
    assert "from unittest.mock import patch, MagicMock" in imports


def test_generate_subprocess_fixture_edge_cases():
    """_generate_subprocess_fixture のエッジケース（想定外の関数名）"""
    gen = AutoMockGenerator()
    
    # subprocess.call
    fix = gen._generate_subprocess_fixture("subprocess.call", "services.video")
    assert fix.name == "mock_subprocess_call"
    assert "subprocess.call" in fix.fixture_code


def test_generate_file_io_fixture_edge_cases():
    """_generate_file_io_fixture のエッジケース（想定外の関数名）"""
    gen = AutoMockGenerator()
    
    # 想定外の関数名
    fix = gen._generate_file_io_fixture("custom_io_func", "services.video")
    assert fix.name == "mock_custom_io_func"
    assert "custom_io_func" in fix.fixture_code


def test_init_invalid_types():
    """AutoMockGenerator.__init__ の不正型、None入力"""
    # None入力
    gen = AutoMockGenerator(project_root=None)
    assert gen.project_root is not None
    
    # 不正型 (int) -> TypeError
    with pytest.raises(TypeError):
        AutoMockGenerator(project_root=12345)


def test_analyze_module_edge_cases(tmp_path):
    """analyze_module のエッジケース（None、空文字、構文エラー、空ファイル）"""
    gen = AutoMockGenerator()

    # None入力 -> TypeError または AttributeError
    with pytest.raises((TypeError, AttributeError)):
        gen.analyze_module(None)

    # 空文字列 -> FileNotFoundError または PermissionError (Windowsフォルダ判定等)
    with pytest.raises((FileNotFoundError, PermissionError)):
        gen.analyze_module("")

    # 不正な型 (list) -> TypeError
    with pytest.raises(TypeError):
        gen.analyze_module(["some_path"])

    # 構文エラーのファイル
    bad_py = tmp_path / "bad_syntax.py"
    bad_py.write_text("class MyClass\n    pass", encoding="utf-8")
    with pytest.raises(SyntaxError):
        gen.analyze_module(str(bad_py))

    # 空のファイル (0バイト)
    empty_py = tmp_path / "empty.py"
    empty_py.write_text("", encoding="utf-8")
    analysis = gen.analyze_module(str(empty_py))
    assert analysis.module_path.endswith("empty")
    assert not analysis.has_dependencies
    assert analysis.summary["total_imports"] == 0
    assert analysis.summary["total_external_calls"] == 0


def test_generate_mocks_edge_cases():
    """generate_mocks のエッジケース（None、空リスト、不正型）"""
    gen = AutoMockGenerator()

    # None入力 -> AttributeError
    with pytest.raises(AttributeError):
        gen.generate_mocks(None)

    # 空のModuleAnalysis
    empty_analysis = ModuleAnalysis(module_path="test")
    fixtures = gen.generate_mocks(empty_analysis)
    assert len(fixtures) == 0

    # 巨大な入力
    large_analysis = ModuleAnalysis(module_path="large")
    large_analysis.db_dependencies = [f"get_db_{i}" for i in range(100)]
    large_analysis.http_dependencies = [f"client.get_{i}" for i in range(100)]
    large_analysis.subprocess_calls = [f"subprocess.run_{i}" for i in range(100)]
    large_analysis.file_io_calls = [f"open_{i}" for i in range(100)]

    fixtures = gen.generate_mocks(large_analysis)
    assert len(fixtures) == 301


def test_generate_conftest_edge_cases(tmp_path):
    """generate_conftest のエッジケース（None、空、不正型）"""
    gen = AutoMockGenerator()

    # None入力 -> TypeError
    with pytest.raises(TypeError):
        gen.generate_conftest(None)

    # 空リスト
    code = gen.generate_conftest([])
    assert "import pytest" in code
    
    # 存在しないディレクトリパスへの出力（自動的に親ディレクトリが作成されるか）
    nested_dir = tmp_path / "nested" / "deep" / "conftest.py"
    gen.generate_conftest([], output_path=str(nested_dir))
    assert nested_dir.exists()


def test_auto_generate_for_module_edge_cases(tmp_path):
    """auto_generate_for_module のエッジケース（None、構文エラー、例外ハンドリング）"""
    gen = AutoMockGenerator()

    # None入力 -> success=False, errorに例外メッセージ
    result = gen.auto_generate_for_module(None)
    assert not result.success
    assert result.error is not None
    assert any(x in result.error for x in ("TypeError", "AttributeError", "NoneType", "str"))

    # 構文エラーのあるファイル -> success=False
    bad_py = tmp_path / "bad_syntax_auto.py"
    bad_py.write_text("def invalid_syntax(:", encoding="utf-8")
    result = gen.auto_generate_for_module(str(bad_py))
    assert not result.success
    assert "invalid syntax" in result.error


def test_to_snake_case_invalid_types():
    """_to_snake_case の不正型入力"""
    with pytest.raises(TypeError):
        AutoMockGenerator._to_snake_case(None)
    with pytest.raises(TypeError):
        AutoMockGenerator._to_snake_case(12345)


def test_cli_main_invalid_args():
    """無効なコマンドライン引数を指定した場合の挙動"""
    test_args = [
        "auto_mock_generator.py",
        "--invalid-option-xyz",
    ]
    with patch("sys.argv", test_args):
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_module(
                "agents.orchestration.auto_mock_generator",
                run_name="__main__",
                alter_sys=True
            )
        assert excinfo.value.code != 0


def test_attach_scope_missing_attributes():
    """ASTノードに lineno や end_lineno 属性がない場合の検証"""
    gen = AutoMockGenerator()
    
    # 属性が欠落した関数ノードを作成 (警告回避のため arguments を明示)
    func_node = ast.FunctionDef(
        name="my_func",
        args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
        body=[]
    )
    # lineno, end_lineno を意図的に設定しない
    
    class_node = ast.ClassDef(
        name="MyClass",
        bases=[],
        keywords=[],
        body=[func_node],
        decorator_list=[]
    )
    
    # ダミーのASTツリー
    tree = ast.Module(body=[class_node, func_node], type_ignores=[])
    
    call = ExternalCall("open", "builtins", "open", 10, "file_io")
    
    # 例外を発生させずに安全に処理をスルーし、元のcallがそのまま返ることを確認
    result = gen._attach_scope(tree, call, 10)
    assert result.in_class is None
    assert result.in_function is None


def test_detect_project_root_shallow_path():
    """__file__ がルートディレクトリに近い浅いパスである場合の挙動"""
    gen = AutoMockGenerator()
    # __file__ をモックして浅いパスを指すようにする
    with patch("agents.orchestration.auto_mock_generator.__file__", "C:\\temp.py"):
        root = gen._detect_project_root()
        # 4階層上を辿ると C:\ になるはずで、そこに "backend" は通常存在しないため、
        # フォールバックとして Path.cwd() が返るはず。
        assert root == Path.cwd()


def test_classify_external_call_deep_nesting():
    """非常に深いドットチェーン呼び出しに対する判定の頑健性"""
    gen = AutoMockGenerator()
    # a.b.c.d.e.f.g() のような呼び出し
    source = "a.b.c.d.e.f.g()"
    tree = ast.parse(source)
    # a がインポートリストに存在しない場合、外部呼び出しとして検出されない（Noneが返る）
    calls = gen._extract_external_calls(tree, [])
    assert len(calls) == 0
    
    # a をインポートリストに含める
    imports = [
        ImportInfo(module="a", name=None, alias=None, is_from_import=False, lineno=1)
    ]
    calls = gen._extract_external_calls(tree, imports)
    assert len(calls) == 1
    assert calls[0].func_name == "g"
    assert calls[0].module_path == "a"


def test_generate_conftest_invalid_path():
    """無効なパスに conftest.py を書き出そうとした際のエラーハンドリング"""
    gen = AutoMockGenerator()
    # \x00 は Windows/Linux ともにファイル名として無効
    with pytest.raises((OSError, ValueError)):
        gen.generate_conftest([], output_path="invalid\x00file.py")


def test_analyze_module_with_invalid_encodings(tmp_path):
    """UTF-8でデコードできないエンコーディングのファイルを解析した時の挙動"""
    gen = AutoMockGenerator()
    bad_enc_file = tmp_path / "shift_jis.py"
    # Shift_JIS で日本語のコメントを書き込む
    bad_enc_file.write_text("# 日本語コメント\nprint('hello')", encoding="shift_jis")
    
    # UTF-8で読み込めないため UnicodeDecodeError が発生するはず
    with pytest.raises(UnicodeDecodeError):
        gen.analyze_module(str(bad_enc_file))
