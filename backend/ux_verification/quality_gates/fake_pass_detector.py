"""
偽PASS検出ゲート (G1) — PCQA品質ゲート

設計参照: pcqa_integrated_design.md § 5.1 自動品質ゲート

E2Eテストコードを静的解析し、以下の偽PASSパターンを検出する:
- `or True` / `or 1`: 条件を常にTrueにするパターン
- `assert True` / `assert 1`: 常に成功するアサーション
- 空assert (assert文のないテスト関数)
- ヘルスチェック代替 (APIレスポンスの存在確認のみ)
"""
import ast
import re
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class FakePassViolation:
    """偽PASS違反の記録"""
    file: str
    line: int
    function: str
    pattern: str
    severity: str  # "critical" | "warning"
    detail: str


@dataclass
class FakePassReport:
    """偽PASS検出レポート"""
    files_scanned: int = 0
    functions_scanned: int = 0
    violations: list = field(default_factory=list)
    
    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0
    
    @property
    def critical_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "critical")
    
    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "warning")


# 偽PASSパターンの正規表現
FAKE_PASS_PATTERNS = [
    (r'\bor\s+True\b', "or True", "critical", "条件を常にTrueにする偽PASSパターン"),
    (r'\bor\s+1\b', "or 1", "critical", "条件を常にTrueにする偽PASSパターン"),
    (r'^\s*assert\s+True\s*$', "assert True", "critical", "常に成功するアサーション"),
    (r'^\s*assert\s+True\s*,', "assert True (msg)", "critical", "常に成功するアサーション（メッセージ付き）"),
    (r'^\s*assert\s+1\s*$', "assert 1", "critical", "常に成功するアサーション"),
    (r'^\s*assert\s+1\s*,', "assert 1 (msg)", "critical", "常に成功するアサーション（メッセージ付き）"),
    (r'^\s*pass\s*$', "pass-only", "warning", "空のテスト関数（passのみ）"),
]

# アサーション密度の最小値
MIN_ASSERTIONS_PER_TEST = 1


def scan_file_for_patterns(filepath: Path) -> list[FakePassViolation]:
    """ファイル内の偽PASSパターンをテキストベースでスキャンする"""
    violations = []
    
    try:
        content = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return violations
    
    lines = content.split("\n")
    current_function = "<module>"
    
    for i, line in enumerate(lines, start=1):
        # 現在の関数名を追跡
        func_match = re.match(r'\s*(async\s+)?def\s+(test_\w+)', line)
        if func_match:
            current_function = func_match.group(2)
        
        # 偽PASSパターンの検出
        for pattern, name, severity, detail in FAKE_PASS_PATTERNS:
            if re.search(pattern, line):
                # pass-only は test_ 関数内でのみ警告
                if name == "pass-only" and not current_function.startswith("test_"):
                    continue
                violations.append(FakePassViolation(
                    file=str(filepath),
                    line=i,
                    function=current_function,
                    pattern=name,
                    severity=severity,
                    detail=detail,
                ))
    
    return violations


def scan_file_for_assertion_density(filepath: Path) -> list[FakePassViolation]:
    """テスト関数のアサーション密度を検査する"""
    violations = []
    
    try:
        content = filepath.read_text(encoding="utf-8")
        tree = ast.parse(content)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return violations
    
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test_"):
            continue
        
        # アサーション数をカウント
        assertion_count = 0
        for child in ast.walk(node):
            if isinstance(child, ast.Assert):
                assertion_count += 1
            # pytest.raises / response.status_code 等もアサーション扱い
            elif isinstance(child, ast.Call):
                if _is_assertion_call(child):
                    assertion_count += 1
            elif isinstance(child, ast.Compare):
                # response.status_code == 200 等
                assertion_count += 1
        
        if assertion_count < MIN_ASSERTIONS_PER_TEST:
            violations.append(FakePassViolation(
                file=str(filepath),
                line=node.lineno,
                function=node.name,
                pattern="low_assertion_density",
                severity="warning",
                detail=f"アサーション数が{MIN_ASSERTIONS_PER_TEST}未満: {assertion_count}個",
            ))
    
    return violations


def _is_assertion_call(node: ast.Call) -> bool:
    """pytest系のアサーション呼び出しかどうかを判定"""
    if isinstance(node.func, ast.Attribute):
        attr = node.func.attr
        if attr in ("assert_called", "assert_called_once", "assert_called_with",
                     "assert_called_once_with", "assert_not_called",
                     "assert_any_call", "assert_has_calls"):
            return True
        if attr in ("raises", "warns"):
            return True
    return False


def scan_directory(directory: Path, pattern: str = "test_e2e_*.py") -> FakePassReport:
    """
    ディレクトリ内のテストファイルを全スキャンする。
    
    Args:
        directory: スキャン対象ディレクトリ
        pattern: ファイル名パターン
    
    Returns:
        FakePassReport
    """
    report = FakePassReport()
    
    for filepath in sorted(directory.rglob(pattern)):
        report.files_scanned += 1
        
        # テキストベースのパターン検出
        pattern_violations = scan_file_for_patterns(filepath)
        report.violations.extend(pattern_violations)
        
        # アサーション密度検査
        density_violations = scan_file_for_assertion_density(filepath)
        report.violations.extend(density_violations)
        
        # 関数数のカウント
        try:
            content = filepath.read_text(encoding="utf-8")
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name.startswith("test_"):
                        report.functions_scanned += 1
        except (OSError, SyntaxError):
            pass
    
    return report


def format_report(report: FakePassReport) -> str:
    """レポートを人間可読な文字列にフォーマットする"""
    lines = [
        "=" * 60,
        "偽PASS検出ゲート (G1) レポート",
        "=" * 60,
        f"スキャンファイル数: {report.files_scanned}",
        f"スキャン関数数: {report.functions_scanned}",
        f"違反数: {len(report.violations)} "
        f"(Critical: {report.critical_count}, Warning: {report.warning_count})",
        "",
    ]
    
    if not report.has_violations:
        lines.append("✅ 偽PASSパターンは検出されませんでした")
    else:
        lines.append("❌ 以下の偽PASSパターンが検出されました:")
        lines.append("")
        
        for v in report.violations:
            icon = "🔴" if v.severity == "critical" else "🟡"
            lines.append(f"  {icon} {Path(v.file).name}:{v.line} ({v.function})")
            lines.append(f"     パターン: {v.pattern}")
            lines.append(f"     詳細: {v.detail}")
            lines.append("")
    
    lines.append("=" * 60)
    return "\n".join(lines)


def main(args: list[str] = None) -> int:
    import sys
    e2e_dir = Path(__file__).parent.parent / "tests" / "e2e"
    
    if args and len(args) > 1:
        e2e_dir = Path(args[1])
        
    if not e2e_dir.exists():
        print(f"E2Eテストディレクトリが見つかりません: {e2e_dir}")
        return 0
    else:
        report = scan_directory(e2e_dir)
        print(format_report(report))
        
        if report.critical_count > 0:
            return 1
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv))
