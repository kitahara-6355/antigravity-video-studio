'''
偽PASS検出ゲート (fake_pass_detector.py) の追加テストコード
'''
import sys
from pathlib import Path

# 親の backend パスを sys.path に追加
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from ux_verification.quality_gates.fake_pass_detector import (
    scan_file_for_assertion_density,
    scan_file_for_patterns,
    FakePassViolation,
    FakePassReport,
)

class TestFakePassDetectorAddition:
    '''偽PASS検出ゲートの堅牢性検証のための追加テスト'''

    def test_ast_non_function_nodes(self, tmp_path):
        '''関数以外のASTノード（クラス定義やグローバル変数など）が含まれる場合の挙動'''
        test_file = tmp_path / "test_class.py"
        test_file.write_text(
            "GLOBAL_VAR = 100\n"
            "class TestMyClass:\n"
            "    def helper(self):\n"
            "        pass\n"
            "    def test_method(self):\n"
            "        assert True\n",
            encoding="utf-8"
        )
        violations = scan_file_for_assertion_density(test_file)
        assert len(violations) == 0

    def test_non_test_function_ignored_in_density(self, tmp_path):
        '''test_ で始まらない関数はアサーション密度検証で無視されること'''
        test_file = tmp_path / "test_non_test.py"
        test_file.write_text(
            "def calculate_val():\n"
            "    x = 1 + 1\n"
            "    return x\n",
            encoding="utf-8"
        )
        violations = scan_file_for_assertion_density(test_file)
        assert len(violations) == 0

    def test_all_assertion_methods(self, tmp_path):
        '''_is_assertion_call のすべてのアサーション属性名が正しくアサーションとしてカウントされること'''
        test_file = tmp_path / "test_assertions_all.py"
        test_file.write_text(
            "def test_all():\n"
            "    import pytest\n"
            "    mock_obj.assert_called()\n"
            "    mock_obj.assert_called_once()\n"
            "    mock_obj.assert_called_with(1)\n"
            "    mock_obj.assert_called_once_with(2)\n"
            "    mock_obj.assert_not_called()\n"
            "    mock_obj.assert_any_call()\n"
            "    mock_obj.assert_has_calls()\n"
            "    with pytest.raises(ValueError):\n"
            "        pass\n"
            "    with pytest.warns(UserWarning):\n"
            "        pass\n",
            encoding="utf-8"
        )
        violations = scan_file_for_assertion_density(test_file)
        assert len(violations) == 0

    def test_main_execution_via_runpy(self, tmp_path):
        '''runpy を使用して if __name__ == '__main__' ブロックの実行を検証し、カバレッジ100%を達成する'''
        import runpy
        import sys
        from unittest.mock import patch

        # 存在しない一時ディレクトリを引数に指定して main が正常終了（コード0）することを確認
        non_existent_dir = tmp_path / "non_existent_e2e"
        test_args = ["fake_pass_detector.py", str(non_existent_dir)]

        # runpy実行時に渡す対象ファイルの絶対パス
        script_path = str(Path(__file__).parent.parent / "ux_verification" / "quality_gates" / "fake_pass_detector.py")

        with patch.object(sys, "argv", test_args):
            with pytest.raises(SystemExit) as excinfo:
                runpy.run_path(
                    script_path,
                    run_name="__main__"
                )
            assert excinfo.value.code == 0

    def test_report_properties(self):
        '''FakePassReport のプロパティが正しく動作すること'''
        # 空のレポート
        report = FakePassReport()
        assert not report.has_violations
        assert report.critical_count == 0
        assert report.warning_count == 0

        # 違反あり
        v1 = FakePassViolation("file1.py", 10, "test_1", "or True", "critical", "detail")
        v2 = FakePassViolation("file1.py", 20, "test_2", "pass-only", "warning", "detail")
        report.violations = [v1, v2]
        assert report.has_violations
        assert report.critical_count == 1
        assert report.warning_count == 1

    def test_scan_file_for_patterns_success(self, tmp_path):
        '''scan_file_for_patterns が各種の偽PASSパターンを正しくスキャンできること'''
        test_file = tmp_path / "test_patterns.py"
        content = (
            "def helper():\n"
            "    pass\n"
            "def test_func():\n"
            "    x = a or True\n"
            "    y = b or 1\n"
            "    assert True\n"
            "    assert True, 'error'\n"
            "    assert 1\n"
            "    assert 1, 'error'\n"
            "    pass\n"
        )
        test_file.write_text(content, encoding="utf-8")
        violations = scan_file_for_patterns(test_file)
        assert len(violations) == 7
        assert violations[0].pattern == "or True"
        assert violations[1].pattern == "or 1"
        assert violations[2].pattern == "assert True"
        assert violations[3].pattern == "assert True (msg)"
        assert violations[4].pattern == "assert 1"
        assert violations[5].pattern == "assert 1 (msg)"
        assert violations[6].pattern == "pass-only"

    def test_scan_file_for_patterns_exceptions(self, tmp_path):
        '''scan_file_for_patterns で例外が発生した場合に正しく空のリストを返すこと'''
        # 存在しないファイル
        non_existent = tmp_path / "non_existent.py"
        violations = scan_file_for_patterns(non_existent)
        assert violations == []

        # UnicodeDecodeError を起こすバイナリファイル
        binary_file = tmp_path / "test_binary.py"
        binary_file.write_bytes(bytes([255, 254, 253, 252]))
        violations = scan_file_for_patterns(binary_file)
        assert violations == []

    def test_scan_file_for_assertion_density_exceptions(self, tmp_path):
        '''scan_file_for_assertion_density で例外が発生した場合に正しく空のリストを返すこと'''
        # 存在しないファイル
        non_existent = tmp_path / "non_existent.py"
        violations = scan_file_for_assertion_density(non_existent)
        assert violations == []

        # 構文エラーのファイル (SyntaxError)
        syntax_error_file = tmp_path / "test_syntax.py"
        syntax_error_file.write_text("def test_func(\n", encoding="utf-8")
        violations = scan_file_for_assertion_density(syntax_error_file)
        assert len(violations) == 0

        # UnicodeDecodeError を起こすファイル
        binary_file = tmp_path / "test_binary.py"
        binary_file.write_bytes(bytes([255, 254, 253, 252]))
        violations = scan_file_for_assertion_density(binary_file)
        assert violations == []

    def test_compare_assertion_and_low_density(self, tmp_path):
        '''ast.Compare によるアサーション判定とアサーション密度不足による違反追加を検証'''
        # Compareアサーションがあるテスト関数 (密度を満たすので違反なし)
        test_file1 = tmp_path / "test_compare.py"
        content1 = (
            "def test_ok():\n"
            "    x = 1\n"
            "    y = 2\n"
            "    assert x == y\n"
        )
        test_file1.write_text(content1, encoding="utf-8")
        violations = scan_file_for_assertion_density(test_file1)
        assert len(violations) == 0

        # アサーション数が 0 個で密度不足のテスト関数 (1 違反)
        test_file2 = tmp_path / "test_low_density.py"
        content2 = (
            "def test_bad():\n"
            "    x = 1\n"
            "    y = 2\n"
        )
        test_file2.write_text(content2, encoding="utf-8")
        violations = scan_file_for_assertion_density(test_file2)
        assert len(violations) == 1
        assert violations[0].pattern == "low_assertion_density"

    def test_non_assertion_call_returns_false(self, tmp_path):
        '''アサーションではない通常の関数呼び出しがアサーションとしてカウントされないことを検証'''
        test_file = tmp_path / "test_normal_call.py"
        content = (
            "def test_normal():\n"
            "    print('hello')\n"
        )
        test_file.write_text(content, encoding="utf-8")
        violations = scan_file_for_assertion_density(test_file)
        assert len(violations) == 1
        assert violations[0].pattern == "low_assertion_density"

    def test_scan_directory(self, tmp_path):
        '''scan_directory によるファイル走査、例外キャッチ、結果の統合を検証'''
        from ux_verification.quality_gates.fake_pass_detector import scan_directory
        test_dir = tmp_path / "e2e"
        test_dir.mkdir()

        # 1. 正常なファイル
        f1 = test_dir / "test_e2e_ok.py"
        f1.write_text("def test_ok():\n    x = 1\n    assert x == 1\n", encoding="utf-8")

        # 2. 違反のあるファイル
        f2 = test_dir / "test_e2e_bad.py"
        f2.write_text("def test_bad():\n    x = a or True\n", encoding="utf-8")

        # 3. 構文エラーのファイル
        f3 = test_dir / "test_e2e_syntax.py"
        f3.write_text("def test_bad(\n", encoding="utf-8")

        report = scan_directory(test_dir, pattern="test_e2e_*.py")
        assert report.files_scanned == 3
        assert report.functions_scanned == 2  # test_ok, test_bad がカウントされる
        # f1: 正常系 (density を満たし、pattern にも該当しないため違反0)
        # f2: or True (pattern +1), low_assertion_density (density +1)
        # f3: 構文エラーで density 側は例外スルー、pattern 側はマッチなし
        assert len(report.violations) == 2

    def test_format_report(self):
        '''format_report によるレポートのフォーマット処理を検証'''
        from ux_verification.quality_gates.fake_pass_detector import format_report
        # 違反なしのケース
        report_ok = FakePassReport(files_scanned=2, functions_scanned=5, violations=[])
        formatted_ok = format_report(report_ok)
        assert "✅ 偽PASSパターンは検出されませんでした" in formatted_ok
        assert "スキャンファイル数: 2" in formatted_ok
        assert "スキャン関数数: 5" in formatted_ok

        # 違反ありのケース
        v1 = FakePassViolation("test_file.py", 10, "test_1", "or True", "critical", "detail critical")
        v2 = FakePassViolation("test_file.py", 20, "test_2", "pass-only", "warning", "detail warning")
        report_bad = FakePassReport(files_scanned=2, functions_scanned=5, violations=[v1, v2])
        formatted_bad = format_report(report_bad)
        assert "❌ 以下の偽PASSパターンが検出されました:" in formatted_bad
        assert "🔴 test_file.py:10 (test_1)" in formatted_bad
        assert "🟡 test_file.py:20 (test_2)" in formatted_bad

    def test_main_with_existing_directory(self, tmp_path):
        '''ディレクトリが存在する場合の main 関数の挙動（正常系および異常系）を検証'''
        from ux_verification.quality_gates.fake_pass_detector import main
        import sys
        from unittest.mock import patch

        test_dir = tmp_path / "e2e_test"
        test_dir.mkdir()
        
        # 正常なファイル
        f = test_dir / "test_e2e_ok.py"
        f.write_text("def test_ok():\n    x = 1\n    assert x == 1\n", encoding="utf-8")

        test_args = ["fake_pass_detector.py", str(test_dir)]
        
        # 正常系 (critical違反なし -> exit_code = 0)
        with patch.object(sys, "argv", test_args):
            exit_code = main(sys.argv)
        assert exit_code == 0

        # 異常系 (critical違反あり -> exit_code = 1)
        f_bad = test_dir / "test_e2e_bad.py"
        f_bad.write_text("def test_bad():\n    x = a or True\n", encoding="utf-8")
        
        with patch.object(sys, "argv", test_args):
            exit_code = main(sys.argv)
        assert exit_code == 1
