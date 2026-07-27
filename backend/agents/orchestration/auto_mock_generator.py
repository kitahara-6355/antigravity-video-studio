"""
Phase 34 M34.2: モック自動生成エンジン (auto_mock_generator.py)

AST解析でモジュールの外部依存（DB/HTTP/subprocess/ファイルI/O）を自動検出し、
pytest fixture 形式のモックコードを生成する。

既存の mock_test_generator.py (DS-035) が「テストコード全体の生成」を担うのに対し、
本モジュールは「conftest.py 用フィクスチャの自動生成」に特化する。

機能:
1. analyze_module: AST走査でimport/外部呼び出し/DB/HTTP/subprocess/ファイルI/Oを検出
2. generate_mocks: 検出結果からカテゴリ別にMockFixtureを生成
3. generate_conftest: 複数のMockFixtureをconftest.py形式に集約
4. auto_generate_for_module: 上記を一括実行する統合API

GEMINI.md準拠:
- subprocess.Popen モック安全規約: poll()=0即座終了、readline()=""
- ファイルI/O安全規約: UTF-8エンコーディング明示
"""

import ast
import os
import sys
import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any, Set

logger = logging.getLogger(__name__)

# =========================================================================
# 定数
# =========================================================================

# stdlib モジュール一覧（mock_test_generator.py と統一）
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

# DB関連パターン
DB_PATTERNS = frozenset({
    "get_db", "Session", "engine", "create_engine",
    "sessionmaker", "AsyncSession", "create_async_engine",
})

# HTTPクライアントパターン
HTTP_MODULES = frozenset({
    "httpx", "requests", "aiohttp", "urllib3",
})

HTTP_PATTERNS = frozenset({
    "get", "post", "put", "delete", "patch", "head", "options",
    "request", "AsyncClient", "Client",
})

# subprocessパターン
SUBPROCESS_PATTERNS = frozenset({
    "subprocess.run", "subprocess.Popen", "subprocess.call",
    "subprocess.check_output", "subprocess.check_call",
})

# ファイルI/Oパターン
FILE_IO_PATTERNS = frozenset({
    "open", "read_text", "write_text", "read_bytes", "write_bytes",
    "read_file", "write_file",
})


# =========================================================================
# データクラス
# =========================================================================

@dataclass
class ImportInfo:
    """モジュール内のインポート情報"""
    module: str
    name: Optional[str]
    alias: Optional[str]
    is_from_import: bool
    lineno: int

    @property
    def full_path(self) -> str:
        """完全なドットパスを返す"""
        if self.is_from_import and self.name:
            return f"{self.module}.{self.name}"
        return self.module


@dataclass
class ExternalCall:
    """外部依存呼び出し"""
    func_name: str
    module_path: str
    full_call: str
    lineno: int
    category: str  # "db", "http", "subprocess", "file_io", "other"
    in_function: Optional[str] = None
    in_class: Optional[str] = None


@dataclass
class ModuleAnalysis:
    """モジュール全体の解析結果"""
    module_path: str
    imports: List[ImportInfo] = field(default_factory=list)
    external_calls: List[ExternalCall] = field(default_factory=list)
    db_dependencies: List[str] = field(default_factory=list)
    http_dependencies: List[str] = field(default_factory=list)
    subprocess_calls: List[str] = field(default_factory=list)
    file_io_calls: List[str] = field(default_factory=list)

    @property
    def has_dependencies(self) -> bool:
        """外部依存が存在するかどうか"""
        return bool(
            self.db_dependencies
            or self.http_dependencies
            or self.subprocess_calls
            or self.file_io_calls
        )

    @property
    def summary(self) -> Dict[str, int]:
        """カテゴリ別の依存数サマリ"""
        return {
            "db": len(self.db_dependencies),
            "http": len(self.http_dependencies),
            "subprocess": len(self.subprocess_calls),
            "file_io": len(self.file_io_calls),
            "total_imports": len(self.imports),
            "total_external_calls": len(self.external_calls),
        }


@dataclass
class MockFixture:
    """生成されたpytestフィクスチャ"""
    name: str
    target: str
    fixture_code: str
    category: str  # "db", "http", "subprocess", "file_io"
    description: str


@dataclass
class GenerationResult:
    """自動生成の結果"""
    module_path: str
    analysis: ModuleAnalysis
    fixtures: List[MockFixture]
    conftest_code: str
    output_path: Optional[str] = None
    success: bool = True
    error: Optional[str] = None


# =========================================================================
# AutoMockGenerator
# =========================================================================

class AutoMockGenerator:
    """
    モジュールのAST解析から pytest fixture を自動生成するエンジン。

    既存の MockTestGenerator がテストコード全体を生成するのに対し、
    本クラスは conftest.py 用フィクスチャの自動生成に特化する。

    使い方:
        gen = AutoMockGenerator()
        result = gen.auto_generate_for_module("backend/services/video.py")
        print(result.conftest_code)

    パターン検出:
        1. DBセッション: get_db, Session, engine パターン
        2. HTTPクライアント: httpx, requests, aiohttp パターン
        3. subprocess: subprocess.run, subprocess.Popen → safe_popen_mock 準拠
        4. ファイルI/O: open(), Path.read_text() パターン
    """

    def __init__(self, project_root: str = None):
        """
        AutoMockGenerator を初期化する。

        Args:
            project_root: プロジェクトルートの絶対パス。
                          None の場合は自動検出する。
        """
        if project_root:
            self.project_root = Path(project_root).resolve()
        else:
            self.project_root = self._detect_project_root()

    # =====================================================================
    # Public API
    # =====================================================================

    def analyze_module(self, module_path: str) -> ModuleAnalysis:
        """
        モジュールをAST解析し、外部依存を検出する。

        Args:
            module_path: 対象モジュールの相対パスまたは絶対パス
                         (例: "backend/services/video.py")

        Returns:
            ModuleAnalysis: 解析結果

        Raises:
            FileNotFoundError: モジュールファイルが存在しない場合
            SyntaxError: Pythonコードの構文エラー
        """
        abs_path = self._resolve_path(module_path)
        if not abs_path.exists():
            raise FileNotFoundError(f"Module not found: {abs_path}")

        source = abs_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(abs_path))

        dot_path = self._path_to_module_name(abs_path)
        analysis = ModuleAnalysis(module_path=dot_path)

        # Phase 1: インポート解析
        analysis.imports = self._extract_imports(tree)

        # Phase 2: 外部呼び出し検出
        analysis.external_calls = self._extract_external_calls(
            tree, analysis.imports
        )

        # Phase 3: カテゴリ分類
        self._categorize_dependencies(analysis)

        logger.info(
            "Module analysis complete: %s — %s",
            dot_path, analysis.summary,
        )
        return analysis

    def generate_mocks(self, analysis: ModuleAnalysis) -> List[MockFixture]:
        """
        解析結果からカテゴリ別に MockFixture を生成する。

        Args:
            analysis: analyze_module() の返り値

        Returns:
            List[MockFixture]: 生成されたフィクスチャ一覧
        """
        fixtures: List[MockFixture] = []
        seen_names: Set[str] = set()

        # DB依存のフィクスチャ
        for dep in analysis.db_dependencies:
            fixture = self._generate_db_fixture(dep, analysis.module_path)
            if fixture and fixture.name not in seen_names:
                fixtures.append(fixture)
                seen_names.add(fixture.name)

        # HTTP依存のフィクスチャ
        for dep in analysis.http_dependencies:
            fixture = self._generate_http_fixture(dep, analysis.module_path)
            if fixture and fixture.name not in seen_names:
                fixtures.append(fixture)
                seen_names.add(fixture.name)

        # subprocess依存のフィクスチャ
        for dep in analysis.subprocess_calls:
            fixture = self._generate_subprocess_fixture(dep, analysis.module_path)
            if fixture and fixture.name not in seen_names:
                fixtures.append(fixture)
                seen_names.add(fixture.name)

        # ファイルI/O依存のフィクスチャ
        for dep in analysis.file_io_calls:
            fixture = self._generate_file_io_fixture(dep, analysis.module_path)
            if fixture and fixture.name not in seen_names:
                fixtures.append(fixture)
                seen_names.add(fixture.name)

        logger.info(
            "Generated %d fixtures for %s (db=%d, http=%d, subprocess=%d, file_io=%d)",
            len(fixtures), analysis.module_path,
            sum(1 for f in fixtures if f.category == "db"),
            sum(1 for f in fixtures if f.category == "http"),
            sum(1 for f in fixtures if f.category == "subprocess"),
            sum(1 for f in fixtures if f.category == "file_io"),
        )
        return fixtures

    def generate_conftest(
        self,
        fixtures: List[MockFixture],
        output_path: str = None,
    ) -> str:
        """
        MockFixture のリストを conftest.py 形式のコードに集約する。

        Args:
            fixtures: generate_mocks() の返り値
            output_path: ファイル出力先パス（Noneの場合はコード文字列のみ返す）

        Returns:
            str: 生成された conftest.py コード
        """
        lines: List[str] = []

        # ヘッダー
        lines.append('"""')
        lines.append("Auto-generated conftest.py — モック自動生成エンジン (Phase 34 M34.2)")
        lines.append("")
        lines.append("このファイルは AutoMockGenerator により自動生成されました。")
        lines.append("手動編集は次回の自動生成で上書きされる可能性があります。")
        lines.append('"""')
        lines.append("")

        # インポート収集
        needed_imports = self._collect_imports(fixtures)
        lines.extend(needed_imports)
        lines.append("")
        lines.append("")

        # カテゴリ別にフィクスチャを出力
        categories = ["db", "http", "subprocess", "file_io"]
        category_labels = {
            "db": "DB セッション",
            "http": "HTTP クライアント",
            "subprocess": "サブプロセス",
            "file_io": "ファイル I/O",
        }

        for category in categories:
            cat_fixtures = [f for f in fixtures if f.category == category]
            if not cat_fixtures:
                continue

            label = category_labels.get(category, category)
            lines.append(f"# {'=' * 69}")
            lines.append(f"# {label} モック")
            lines.append(f"# {'=' * 69}")
            lines.append("")

            for fixture in cat_fixtures:
                lines.append(fixture.fixture_code)
                lines.append("")
                lines.append("")

        code = "\n".join(lines).rstrip() + "\n"

        # 構文検証
        try:
            ast.parse(code)
        except SyntaxError as e:
            logger.error("Generated conftest.py has syntax error: %s", e)
            raise

        # ファイル出力
        if output_path:
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(code, encoding="utf-8")
            logger.info("Wrote conftest.py: %s (%d bytes)", output_path, len(code))

        return code

    def auto_generate_for_module(self, module_path: str) -> GenerationResult:
        """
        モジュール解析→フィクスチャ生成→conftest.py出力を一括実行する統合API。

        Args:
            module_path: 対象モジュールの相対パスまたは絶対パス

        Returns:
            GenerationResult: 生成結果（成功/失敗情報を含む）
        """
        try:
            analysis = self.analyze_module(module_path)
            fixtures = self.generate_mocks(analysis)
            conftest_code = self.generate_conftest(fixtures)

            return GenerationResult(
                module_path=module_path,
                analysis=analysis,
                fixtures=fixtures,
                conftest_code=conftest_code,
                success=True,
            )
        except Exception as e:
            logger.error("Auto-generation failed for %s: %s", module_path, e)
            return GenerationResult(
                module_path=module_path,
                analysis=ModuleAnalysis(module_path=module_path),
                fixtures=[],
                conftest_code="",
                success=False,
                error=str(e),
            )

    # =====================================================================
    # Phase 1: インポート解析
    # =====================================================================

    def _extract_imports(self, tree: ast.AST) -> List[ImportInfo]:
        """ASTからインポート文を抽出する。"""
        imports: List[ImportInfo] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(ImportInfo(
                        module=alias.name,
                        name=None,
                        alias=alias.asname,
                        is_from_import=False,
                        lineno=node.lineno,
                    ))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imports.append(ImportInfo(
                        module=module,
                        name=alias.name,
                        alias=alias.asname,
                        is_from_import=True,
                        lineno=node.lineno,
                    ))

        return imports

    # =====================================================================
    # Phase 2: 外部呼び出し検出
    # =====================================================================

    def _extract_external_calls(
        self,
        tree: ast.AST,
        imports: List[ImportInfo],
    ) -> List[ExternalCall]:
        """ASTから外部依存呼び出しを検出する。"""
        calls: List[ExternalCall] = []
        seen: Set[str] = set()

        # インポートされた名前のセットを構築
        imported_names = self._build_imported_names(imports)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            call_info = self._classify_external_call(
                node, imported_names, imports
            )
            if call_info and call_info.full_call not in seen:
                # 所属関数/クラスを特定
                call_info = self._attach_scope(tree, call_info, node.lineno)
                calls.append(call_info)
                seen.add(call_info.full_call)

        return calls

    def _build_imported_names(self, imports: List[ImportInfo]) -> Set[str]:
        """インポートされた名前のセットを構築する。"""
        names: Set[str] = set()
        for imp in imports:
            if imp.alias:
                names.add(imp.alias)
            elif imp.name:
                names.add(imp.name)
            else:
                names.add(imp.module.split(".")[0])
        return names

    def _classify_external_call(
        self,
        call_node: ast.Call,
        imported_names: Set[str],
        imports: List[ImportInfo],
    ) -> Optional[ExternalCall]:
        """ast.Call ノードを外部呼び出しとして分類する。"""
        func = call_node.func

        try:
            full_call = ast.unparse(func)
        except (ValueError, TypeError, AttributeError):
            return None

        # 呼び出しのルート名を取得
        root_name = full_call.split(".")[0]

        # self.xxx() / cls.xxx() はスキップ
        if root_name in ("self", "cls", "super"):
            return None

        # ローカル変数の呼び出し（インポートされていないもの）はスキップ
        # ただし、組み込み関数 (open 等) はチェックする
        lineno = getattr(call_node, "lineno", 0)

        # パターン1: open() — ビルトイン
        if full_call == "open":
            return ExternalCall(
                func_name="open",
                module_path="builtins",
                full_call="open",
                lineno=lineno,
                category="file_io",
            )

        # パターン2: subprocess.run / subprocess.Popen 等
        if full_call in SUBPROCESS_PATTERNS:
            return ExternalCall(
                func_name=full_call.split(".")[-1],
                module_path="subprocess",
                full_call=full_call,
                lineno=lineno,
                category="subprocess",
            )

        # パターン3: DB関連 (get_db, Session, engine等)
        func_basename = full_call.split(".")[-1]
        if func_basename in DB_PATTERNS:
            module_path = self._find_import_module(func_basename, imports)
            return ExternalCall(
                func_name=func_basename,
                module_path=module_path or full_call,
                full_call=full_call,
                lineno=lineno,
                category="db",
            )

        # パターン4: HTTPクライアント
        if root_name in HTTP_MODULES or self._is_http_call(full_call, imports):
            return ExternalCall(
                func_name=func_basename,
                module_path=root_name,
                full_call=full_call,
                lineno=lineno,
                category="http",
            )

        # パターン5: Path.read_text() / Path.write_text() 等
        if func_basename in FILE_IO_PATTERNS and func_basename != "open":
            return ExternalCall(
                func_name=func_basename,
                module_path="pathlib.Path" if "Path" in full_call else root_name,
                full_call=full_call,
                lineno=lineno,
                category="file_io",
            )

        # パターン6: インポートされたモジュール経由の呼び出し
        if root_name in imported_names:
            root_module = root_name.split(".")[0]
            if root_module in STDLIB_MODULES:
                return None  # stdlibは対象外（subprocess以外）
            return ExternalCall(
                func_name=func_basename,
                module_path=root_name,
                full_call=full_call,
                lineno=lineno,
                category="other",
            )

        return None

    def _is_http_call(self, full_call: str, imports: List[ImportInfo]) -> bool:
        """HTTP関連の呼び出しかどうかを判定する。"""
        for imp in imports:
            if imp.module in HTTP_MODULES:
                root = imp.alias or imp.name or imp.module.split(".")[0]
                if full_call.startswith(root):
                    return True
        return False

    def _find_import_module(
        self,
        name: str,
        imports: List[ImportInfo],
    ) -> Optional[str]:
        """名前に対応するインポートモジュールパスを検索する。"""
        for imp in imports:
            if imp.name == name:
                return imp.module
            if imp.alias == name:
                return imp.module
        return None

    def _attach_scope(
        self,
        tree: ast.AST,
        call: ExternalCall,
        lineno: int,
    ) -> ExternalCall:
        """呼び出しが所属する関数/クラスを特定する。"""
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if hasattr(item, "lineno") and hasattr(item, "end_lineno"):
                            if item.lineno <= lineno <= (item.end_lineno or item.lineno):
                                call.in_class = node.name
                                call.in_function = item.name
                                return call
            elif isinstance(item := node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if hasattr(item, "lineno") and hasattr(item, "end_lineno"):
                    if item.lineno <= lineno <= (item.end_lineno or item.lineno):
                        call.in_function = item.name
                        return call
        return call

    # =====================================================================
    # Phase 3: カテゴリ分類
    # =====================================================================

    def _categorize_dependencies(self, analysis: ModuleAnalysis) -> None:
        """外部呼び出しをカテゴリ別に分類してanalysisに格納する。"""
        seen_db: Set[str] = set()
        seen_http: Set[str] = set()
        seen_subprocess: Set[str] = set()
        seen_file_io: Set[str] = set()

        for call in analysis.external_calls:
            if call.category == "db" and call.full_call not in seen_db:
                analysis.db_dependencies.append(call.full_call)
                seen_db.add(call.full_call)
            elif call.category == "http" and call.full_call not in seen_http:
                analysis.http_dependencies.append(call.full_call)
                seen_http.add(call.full_call)
            elif call.category == "subprocess" and call.full_call not in seen_subprocess:
                analysis.subprocess_calls.append(call.full_call)
                seen_subprocess.add(call.full_call)
            elif call.category == "file_io" and call.full_call not in seen_file_io:
                analysis.file_io_calls.append(call.full_call)
                seen_file_io.add(call.full_call)

    # =====================================================================
    # フィクスチャ生成（カテゴリ別）
    # =====================================================================

    def _generate_db_fixture(
        self,
        dep: str,
        module_path: str,
    ) -> Optional[MockFixture]:
        """DB依存のpytestフィクスチャを生成する。"""
        func_name = dep.split(".")[-1]
        fixture_name = f"mock_{self._to_snake_case(func_name)}"

        # patch対象の決定
        patch_target = f"{module_path}.{func_name}" if "." not in dep else dep

        code_lines = [
            f"@pytest.fixture",
            f"def {fixture_name}():",
            f'    """DBセッションのモック ({func_name})"""',
            f"    with patch('{patch_target}') as mock:",
            f"        session = MagicMock()",
            f"        session.query.return_value = session",
            f"        session.filter.return_value = session",
            f"        session.all.return_value = []",
            f"        session.first.return_value = None",
            f"        session.commit.return_value = None",
            f"        session.rollback.return_value = None",
            f"        mock.return_value = session",
            f"        yield mock",
        ]

        return MockFixture(
            name=fixture_name,
            target=patch_target,
            fixture_code="\n".join(code_lines),
            category="db",
            description=f"DBセッション ({func_name}) のモック",
        )

    def _generate_http_fixture(
        self,
        dep: str,
        module_path: str,
    ) -> Optional[MockFixture]:
        """HTTP依存のpytestフィクスチャを生成する。"""
        func_name = dep.split(".")[-1]
        root_module = dep.split(".")[0]
        fixture_name = f"mock_{self._to_snake_case(root_module)}_client"

        # patch対象
        patch_target = dep if "." in dep else f"{module_path}.{dep}"

        code_lines = [
            f"@pytest.fixture",
            f"def {fixture_name}():",
            f'    """HTTPクライアントのモック ({root_module})"""',
            f"    with patch('{patch_target}') as mock:",
            f"        response = MagicMock()",
            f"        response.status_code = 200",
            f"        response.json.return_value = {{}}",
            f'        response.text = ""',
            f'        response.content = b""',
            f"        response.headers = {{}}",
            f"        response.raise_for_status.return_value = None",
            f"        mock.return_value = response",
            f"        yield mock",
        ]

        return MockFixture(
            name=fixture_name,
            target=patch_target,
            fixture_code="\n".join(code_lines),
            category="http",
            description=f"HTTPクライアント ({root_module}) のモック",
        )

    def _generate_subprocess_fixture(
        self,
        dep: str,
        module_path: str,
    ) -> Optional[MockFixture]:
        """
        subprocess依存のpytestフィクスチャを生成する。

        GEMINI.md subprocess.Popen モック安全規約に準拠:
        - poll() は return_value=0 で即座に終了コードを返す
        - readline() は空文字列 "" を返す
        - side_effect=[None, 0] は禁止
        """
        func_name = dep.split(".")[-1]

        if func_name == "Popen":
            # safe_popen_mock — GEMINI.md モック安全規約準拠
            fixture_name = "safe_popen_mock"
            patch_target = "subprocess.Popen"

            code_lines = [
                f"@pytest.fixture",
                f"def {fixture_name}():",
                f'    """subprocess.Popenの安全なモック (GEMINI.md規約準拠)"""',
                f"    with patch('{patch_target}') as mock:",
                f"        proc = MagicMock()",
                f"        proc.poll.return_value = 0  # 即座に終了",
                f"        proc.returncode = 0",
                f'        proc.stdout.readline.return_value = ""  # 空文字列',
                f'        proc.stderr.readline.return_value = ""',
                f'        proc.communicate.return_value = ("", "")',
                f"        proc.wait.return_value = 0",
                f"        mock.return_value = proc",
                f"        yield mock",
            ]
        else:
            # subprocess.run / subprocess.call 等
            fixture_name = f"mock_subprocess_{self._to_snake_case(func_name)}"
            patch_target = f"subprocess.{func_name}"

            code_lines = [
                f"@pytest.fixture",
                f"def {fixture_name}():",
                f'    """subprocess.{func_name} のモック"""',
                f"    with patch('{patch_target}') as mock:",
                f"        result = MagicMock()",
                f"        result.returncode = 0",
                f'        result.stdout = ""',
                f'        result.stderr = ""',
                f"        mock.return_value = result",
                f"        yield mock",
            ]

        return MockFixture(
            name=fixture_name,
            target=patch_target,
            fixture_code="\n".join(code_lines),
            category="subprocess",
            description=f"subprocess.{func_name} のモック",
        )

    def _generate_file_io_fixture(
        self,
        dep: str,
        module_path: str,
    ) -> Optional[MockFixture]:
        """ファイルI/O依存のpytestフィクスチャを生成する。"""
        func_name = dep.split(".")[-1]

        if func_name == "open":
            fixture_name = "mock_open_file"
            patch_target = "builtins.open"

            code_lines = [
                f"@pytest.fixture",
                f"def {fixture_name}():",
                f'    """builtins.open のモック"""',
                f"    mock_file = MagicMock()",
                f'    mock_file.read.return_value = ""',
                f"    mock_file.readlines.return_value = []",
                f'    mock_file.readline.return_value = ""',
                f"    mock_file.write.return_value = None",
                f"    mock_file.__enter__ = MagicMock(return_value=mock_file)",
                f"    mock_file.__exit__ = MagicMock(return_value=False)",
                f"    with patch('{patch_target}', return_value=mock_file) as mock:",
                f"        yield mock",
            ]
        elif func_name in ("read_text", "write_text", "read_bytes", "write_bytes"):
            fixture_name = f"mock_path_{self._to_snake_case(func_name)}"
            patch_target = f"pathlib.Path.{func_name}"

            default_return = '""' if "text" in func_name else 'b""'
            if "write" in func_name:
                default_return = "None"

            code_lines = [
                f"@pytest.fixture",
                f"def {fixture_name}():",
                f'    """pathlib.Path.{func_name} のモック"""',
                f"    with patch('{patch_target}') as mock:",
                f"        mock.return_value = {default_return}",
                f"        yield mock",
            ]
        else:
            fixture_name = f"mock_{self._to_snake_case(func_name)}"
            patch_target = f"{module_path}.{func_name}"

            code_lines = [
                f"@pytest.fixture",
                f"def {fixture_name}():",
                f'    """ファイルI/O ({func_name}) のモック"""',
                f"    with patch('{patch_target}') as mock:",
                f'        mock.return_value = ""',
                f"        yield mock",
            ]

        return MockFixture(
            name=fixture_name,
            target=patch_target,
            fixture_code="\n".join(code_lines),
            category="file_io",
            description=f"ファイルI/O ({func_name}) のモック",
        )

    # =====================================================================
    # conftest.py ヘルパー
    # =====================================================================

    def _collect_imports(self, fixtures: List[MockFixture]) -> List[str]:
        """フィクスチャが必要とするインポート文を収集する。"""
        lines = ["import pytest"]
        needs_patch = False
        needs_magicmock = False

        for f in fixtures:
            if "patch(" in f.fixture_code:
                needs_patch = True
            if "MagicMock" in f.fixture_code:
                needs_magicmock = True

        mock_parts = []
        if needs_patch:
            mock_parts.append("patch")
        if needs_magicmock:
            mock_parts.append("MagicMock")

        if mock_parts:
            lines.append(f"from unittest.mock import {', '.join(mock_parts)}")

        return lines

    # =====================================================================
    # ユーティリティ
    # =====================================================================

    def _resolve_path(self, module_path: str) -> Path:
        """モジュールパスを絶対パスに解決する。"""
        p = Path(module_path)
        if p.is_absolute():
            return p
        return self.project_root / p

    def _path_to_module_name(self, abs_path: Path) -> str:
        """絶対パスをPythonのドット区切りモジュール名に変換する。"""
        try:
            rel = abs_path.relative_to(self.project_root)
        except ValueError:
            rel = abs_path

        parts = list(rel.parts)
        # .py 拡張子を除去
        if parts and parts[-1].endswith(".py"):
            parts[-1] = parts[-1][:-3]
        # __init__ は除去
        if parts and parts[-1] == "__init__":
            parts.pop()

        return ".".join(parts)

    def _detect_project_root(self) -> Path:
        """プロジェクトルートを自動検出する。"""
        # 実行ファイルからの相対推定
        current = Path(__file__).resolve()
        # backend/agents/orchestration/ → 3階層上
        root = current.parent.parent.parent.parent
        if (root / "backend").exists():
            return root
        # フォールバック: カレントディレクトリ
        return Path.cwd()

    @staticmethod
    def _to_snake_case(name: str) -> str:
        """CamelCase / PascalCase を snake_case に変換する。"""
        s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
        return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


# =========================================================================
# CLI エントリポイント
# =========================================================================

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="モック自動生成エンジン (Phase 34 M34.2)",
    )
    parser.add_argument(
        "module",
        help="解析対象のPythonモジュールパス (例: backend/services/video.py)",
    )
    parser.add_argument(
        "-o", "--output",
        help="conftest.py の出力先パス",
        default=None,
    )
    parser.add_argument(
        "--project-root",
        help="プロジェクトルート (デフォルト: 自動検出)",
        default=None,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="生成コードを標準出力に表示するのみ（ファイル書き込みなし）",
    )

    args = parser.parse_args()

    gen = AutoMockGenerator(project_root=args.project_root)
    result = gen.auto_generate_for_module(args.module)

    if not result.success:
        print(f"ERROR: {result.error}", file=sys.stderr)
        sys.exit(1)

    # サマリ
    summary = result.analysis.summary
    print(f"\n{'=' * 60}")
    print(f"Module: {result.analysis.module_path}")
    print(f"DB deps:         {summary['db']}")
    print(f"HTTP deps:       {summary['http']}")
    print(f"Subprocess deps: {summary['subprocess']}")
    print(f"File I/O deps:   {summary['file_io']}")
    print(f"Fixtures:        {len(result.fixtures)}")
    print(f"{'=' * 60}\n")

    if args.dry_run or not args.output:
        print(result.conftest_code)
    else:
        gen.generate_conftest(result.fixtures, output_path=args.output)
        print(f"Wrote: {args.output}")
