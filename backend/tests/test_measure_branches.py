# Test file for backend/tests/test_measure_branches.py
import sys
import os
import ast
import runpy
from unittest.mock import patch

# Ensure backend root is in sys.path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
project_root = os.path.dirname(backend_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from backend.scripts import measure_branches

def test_count_branches_not_exist():
    # 存在しないファイルの場合は 0, 0 を返す
    b, m = measure_branches.count_branches("non_existent_file_xyz.py")
    assert b == 0
    assert m == 0

def test_count_branches_success(tmp_path):
    # テスト用の一時ファイルを作成し、正しくカウントされるか検証
    code = """
def test_func():
    if True:
        for i in range(1):
            while False:
                try:
                    with open("a") as f:
                        assert True
                except Exception:
                    pass

async def test_async_func():
    pass
"""
    test_file = tmp_path / "dummy_test.py"
    test_file.write_text(code, encoding="utf-8")
    
    b, m = measure_branches.count_branches(str(test_file))
    
    # if, for, while, except, with, assert = 6
    # def, async def = 2
    assert b == 6
    assert m == 2

def test_count_branches_syntax_error(tmp_path):
    # 構文エラーのファイル
    code = "invalid syntax (("
    test_file = tmp_path / "dummy_error.py"
    test_file.write_text(code, encoding="utf-8")
    
    b, m = measure_branches.count_branches(str(test_file))
    assert b == 0
    assert m == 0

def test_count_branches_read_error():
    # 読み取り時に例外が発生する場合の検証
    # mock を使って open をモック化し OSError を発生させる
    with patch("builtins.open", side_effect=OSError("Permission denied")):
        b, m = measure_branches.count_branches("some_file.py")
        assert b == 0
        assert m == 0

def test_main_function(monkeypatch, capsys, tmp_path):
    # worker_engines と shared_infra をテスト用データにモック
    # 重複パスやプリセットあり・なしなど、分岐をすべて網羅するように設定
    test_file1 = tmp_path / "test_file1.py"
    test_file1.write_text("def f():\n    if True: pass", encoding="utf-8") # b=1, m=1
    
    test_file2 = tmp_path / "test_file2.py"
    test_file2.write_text("def f2(): pass", encoding="utf-8") # b=0, m=1
    
    test_worker_engines = {
        'TestWorker': {
            'worker_branches': 10,
            'engines': [
                ('test_file1.py', str(test_file1)),
                ('test_file1_dup.py', str(test_file1)), # 重複パス (already in seen)
            ]
        }
    }
    
    test_shared_infra = [
        ('PresetShared', None, 5), # preset が None でない (pre-counted)
        ('DynamicShared', str(test_file2), None), # preset が None (count_branches)
    ]
    
    monkeypatch.setattr(measure_branches, "worker_engines", test_worker_engines)
    monkeypatch.setattr(measure_branches, "shared_infra", test_shared_infra)
    
    # main を実行
    measure_branches.main()
    
    captured = capsys.readouterr()
    output = captured.out
    
    # 期待される出力の検証
    assert "TestWorker: Worker=10 + Engines=1 = **11**" in output
    assert "test_file1_dup.py: (counted elsewhere)" in output
    assert "PresetShared: 5 branches (pre-counted)" in output
    assert "DynamicShared: 0 branches, 1 methods" in output
    assert "Worker系合計: 11" in output
    assert "共有基盤合計: 5" in output
    assert "総計: 16" in output

def test_run_as_main(monkeypatch, capsys, caplog):
    # runpy を使ってスクリプト全体を実行し、 __main__ ブロックを網羅
    # 実行速度向上のため os.path.exists が False を返すようにモックして、
    # 実際のファイルシステムへの依存を切り離す
    monkeypatch.setattr(os.path, "exists", lambda path: False)
    
    script_path = os.path.abspath(measure_branches.__file__)
    runpy.run_path(script_path, run_name="__main__")
    
    captured = capsys.readouterr()
    output = captured.out
    
    assert "Worker系合計: " in output

def test_count_branches_read_error_logging(caplog, tmp_path):
    # 読み取り時に例外が発生し、かつログにエラーが出力されることを検証
    import logging
    test_file = tmp_path / "read_error_test.py"
    test_file.write_text("def dummy(): pass", encoding="utf-8")
    with caplog.at_level(logging.ERROR, logger="measure_branches"):
        with patch("builtins.open", side_effect=OSError("Permission denied")):
            b, m = measure_branches.count_branches(str(test_file))
            assert b == 0
            assert m == 0
            assert len(caplog.records) > 0
            assert "Failed to parse branches for" in caplog.text

def test_count_branches_not_exist_logging(caplog):
    # 存在しないファイルの場合に警告ログが出力されることを検証
    import logging
    with caplog.at_level(logging.WARNING, logger="measure_branches"):
        b, m = measure_branches.count_branches("non_existent_file_xyz.py")
        assert b == 0
        assert m == 0
        assert len(caplog.records) > 0
        assert "File does not exist: non_existent_file_xyz.py" in caplog.text

def test_measure_worker_branches(tmp_path):
    # measure_worker_branches の動作を検証
    test_file = tmp_path / "dummy_worker.py"
    test_file.write_text("def f(): pass", encoding="utf-8")
    
    from backend.scripts.measure_branches import measure_worker_branches
    
    test_worker_engines = {
        'DummyWorker': {
            'worker_branches': 3,
            'engines': [
                ('dummy_worker.py', str(test_file))
            ]
        }
    }
    
    with patch("backend.scripts.measure_branches.worker_engines", test_worker_engines):
        seen = set()
        worker_total, details = measure_worker_branches(str(tmp_path), seen)
        # Worker(3) + Engine(0 branches) = 3
        assert worker_total == 3
        assert len(details) == 1
        assert "DummyWorker: Worker=3 + Engines=0 = **3**" in details[0][0]

def test_measure_shared_infra_branches(tmp_path):
    # measure_shared_infra_branches の動作を検証
    test_file = tmp_path / "dummy_shared.py"
    test_file.write_text("def f():\n    if True:\n        pass", encoding="utf-8") # branch=1
    
    from backend.scripts.measure_branches import measure_shared_infra_branches
    
    test_shared_infra = [
        ('PresetShared', None, 10),
        ('DynamicShared', str(test_file), None)
    ]
    
    with patch("backend.scripts.measure_branches.shared_infra", test_shared_infra):
        seen = set()
        shared_total, details = measure_shared_infra_branches(str(tmp_path), seen)
        # Preset(10) + Dynamic(1 branch) = 11
        assert shared_total == 11
        assert len(details) == 2
        assert "PresetShared: 10 branches (pre-counted)" in details[0]
        assert "DynamicShared: 1 branches, 1 methods" in details[1]
        
        expected_path = os.path.normcase(os.path.abspath(os.path.normpath(os.path.join(str(tmp_path), str(test_file)))))
        assert expected_path in seen

def test_measure_shared_infra_branches_duplicate(tmp_path):
    # すでに seen に登録されているファイルは 0 分岐としてカウントされることを検証
    test_file = tmp_path / "dummy_shared_dup.py"
    test_file.write_text("def f():\n    if True:\n        pass", encoding="utf-8") # branch=1
    
    from backend.scripts.measure_branches import measure_shared_infra_branches
    
    test_shared_infra = [
        ('DynamicShared', str(test_file), None)
    ]
    
    with patch("backend.scripts.measure_branches.shared_infra", test_shared_infra):
        expected_path = os.path.normcase(os.path.abspath(os.path.normpath(os.path.join(str(tmp_path), str(test_file)))))
        seen = {expected_path}
        shared_total, details = measure_shared_infra_branches(str(tmp_path), seen)
        # すでに seen に登録されているので、0 としてカウントされ、(counted elsewhere) が表示される
        assert shared_total == 0
        assert len(details) == 1
        assert "DynamicShared: (counted elsewhere)" in details[0]

def test_print_results(capsys):
    # print_results の動作を検証
    from backend.scripts.measure_branches import print_results
    
    worker_total = 10
    worker_details = [
        ["WorkerA: Worker=8 + Engines=2 = **10**", "  eng1: 2 branches, 1 methods"]
    ]
    shared_total = 5
    shared_details = [
        "SharedA: 5 branches (pre-counted)"
    ]
    
    print_results(worker_total, worker_details, shared_total, shared_details)
    
    captured = capsys.readouterr()
    output = captured.out
    
    assert "WorkerA: Worker=8 + Engines=2 = **10**" in output
    assert "  eng1: 2 branches, 1 methods" in output
    assert "SharedA: 5 branches (pre-counted)" in output
    assert "Worker系合計: 10" in output
    assert "共有基盤合計: 5" in output
    assert "総計: 15" in output

def test_count_branches_unicode_decode_error(tmp_path, caplog):
    # UTF-8 でない不正なバイトを含むファイル
    import logging
    test_file = tmp_path / "bad_encoding.py"
    with open(test_file, "wb") as f:
        f.write(b"\xff\xfe\x00\x00")  # UTF-32 BOM または UTF-8で無効なバイト
        
    with caplog.at_level(logging.ERROR, logger="measure_branches"):
        b, m = measure_branches.count_branches(str(test_file))
        assert b == 0
        assert m == 0
        assert len(caplog.records) > 0
        assert "Failed to parse branches for" in caplog.text

def test_count_branches_is_directory(tmp_path, caplog):
    # ディレクトリパスを渡した場合
    import logging
    with caplog.at_level(logging.WARNING, logger="measure_branches"):
        b, m = measure_branches.count_branches(str(tmp_path))
        assert b == 0
        assert m == 0
        assert len(caplog.records) > 0
        assert "Path is a directory" in caplog.text

def test_measure_branches_path_normalization_duplicates(tmp_path):
    # 大文字小文字の表記揺れによる重複が排除されることを検証
    # Windows などの case-insensitive 環境を想定
    test_file = tmp_path / "dummy_norm.py"
    test_file.write_text("def f():\n    if True: pass", encoding="utf-8") # b=1, m=1
    
    # 異なるケースのパス表現を作成
    path_lower = str(test_file).lower()
    path_upper = str(test_file).upper()
    
    test_worker_engines = {
        'TestWorker': {
            'worker_branches': 0,
            'engines': [
                ('norm1.py', path_lower),
                ('norm2.py', path_upper),
            ]
        }
    }
    
    with patch("backend.scripts.measure_branches.worker_engines", test_worker_engines):
        seen = set()
        worker_total, details = measure_branches.measure_worker_branches(str(tmp_path), seen)
        # norm1.py で 1回カウントされ、norm2.py は重複として 0 になるはず
        # よって worker_total は 1
        assert worker_total == 1
        assert "norm2.py: (counted elsewhere)" in details[0][2]

def test_shared_infra_none_path_and_preset(caplog):
    # preset が None かつ path も None の場合の検証
    import logging
    test_shared_infra = [
        ('InvalidShared', None, None)
    ]
    with patch("backend.scripts.measure_branches.shared_infra", test_shared_infra):
        seen = set()
        with caplog.at_level(logging.WARNING, logger="measure_branches"):
            shared_total, details = measure_branches.measure_shared_infra_branches("dummy_root", seen)
            assert shared_total == 0
            assert len(details) == 1
            assert "InvalidShared: (empty path)" in details[0]
            assert "Shared infra path is empty for: InvalidShared" in caplog.text

def test_process_single_engine_empty_path(caplog):
    # engine_path が None の場合の検証
    import logging
    from backend.scripts.measure_branches import _process_single_engine
    seen = set()
    with caplog.at_level(logging.WARNING, logger="measure_branches"):
        branch_count, detail = _process_single_engine("dummy_root", "EmptyEngine", None, seen)
        assert branch_count == 0
        assert "EmptyEngine: (empty path)" in detail
        assert "Engine path is empty for engine: EmptyEngine" in caplog.text

def test_count_branches_value_error(tmp_path, caplog):
    # ValueErrorが発生した場合の検証
    import logging
    test_file = tmp_path / "value_error_test.py"
    test_file.write_text("def dummy(): pass", encoding="utf-8")
    with caplog.at_level(logging.ERROR, logger="measure_branches"):
        with patch("ast.parse", side_effect=ValueError("Invalid AST node value")):
            b, m = measure_branches.count_branches(str(test_file))
            assert b == 0
            assert m == 0
            assert len(caplog.records) > 0
            assert "Failed to parse branches for" in caplog.text
            assert "Invalid AST node value" in caplog.text

def test_count_branches_empty_file(tmp_path):
    # 空ファイルの場合の検証
    test_file = tmp_path / "empty.py"
    test_file.write_text("", encoding="utf-8")
    b, m = measure_branches.count_branches(str(test_file))
    assert b == 0
    assert m == 0

def test_measure_branches_empty_configs():
    # 設定（worker_engines, shared_infra）が空の場合の検証
    with patch("backend.scripts.measure_branches.worker_engines", {}):
        worker_total, details = measure_branches.measure_worker_branches("dummy_root", set())
        assert worker_total == 0
        assert len(details) == 0

    with patch("backend.scripts.measure_branches.shared_infra", []):
        shared_total, details = measure_branches.measure_shared_infra_branches("dummy_root", set())
        assert shared_total == 0
        assert len(details) == 0


def test_count_branches_syntax_error_logging(caplog, tmp_path):
    # SyntaxError発生時のログ検証
    import logging
    test_file = tmp_path / "syntax_error_test.py"
    test_file.write_text("invalid syntax ((", encoding="utf-8")
    with caplog.at_level(logging.ERROR, logger="measure_branches"):
        b, m = measure_branches.count_branches(str(test_file))
        assert b == 0
        assert m == 0
        assert len(caplog.records) > 0
        assert "Failed to parse branches for" in caplog.text


def test_is_branch_node_direct():
    # _is_branch_node の個別検証
    from backend.scripts.measure_branches import _is_branch_node
    
    # ast.parse を使って適切な AST ノードを生成し、警告を回避する
    tree = ast.parse("if True: pass\nfor x in []: pass\nwhile False: pass\ntry: pass\nexcept Exception: pass\nwith x: pass\nassert True")
    nodes = list(ast.walk(tree))
    
    ifs = [n for n in nodes if isinstance(n, ast.If)]
    fors = [n for n in nodes if isinstance(n, ast.For)]
    whiles = [n for n in nodes if isinstance(n, ast.While)]
    excepts = [n for n in nodes if isinstance(n, ast.ExceptHandler)]
    withs = [n for n in nodes if isinstance(n, ast.With)]
    asserts = [n for n in nodes if isinstance(n, ast.Assert)]
    
    assert ifs and _is_branch_node(ifs[0])
    assert fors and _is_branch_node(fors[0])
    assert whiles and _is_branch_node(whiles[0])
    assert excepts and _is_branch_node(excepts[0])
    assert withs and _is_branch_node(withs[0])
    assert asserts and _is_branch_node(asserts[0])
    
    # 対象外のノード
    tree_assign = ast.parse("x = 1\ndef f(): pass")
    assign_node = next(n for n in ast.walk(tree_assign) if isinstance(n, ast.Assign))
    func_node = next(n for n in ast.walk(tree_assign) if isinstance(n, ast.FunctionDef))
    assert not _is_branch_node(assign_node)
    assert not _is_branch_node(func_node)


def test_is_method_node_direct():
    # _is_method_node の個別検証
    from backend.scripts.measure_branches import _is_method_node
    
    tree = ast.parse("def f(): pass\nasync def g(): pass")
    nodes = list(ast.walk(tree))
    
    funcs = [n for n in nodes if isinstance(n, ast.FunctionDef)]
    async_funcs = [n for n in nodes if isinstance(n, ast.AsyncFunctionDef)]
    
    assert funcs and _is_method_node(funcs[0])
    assert async_funcs and _is_method_node(async_funcs[0])
    
    # 対象外のノード
    tree_other = ast.parse("if True: pass\nx = 1")
    if_node = next(n for n in ast.walk(tree_other) if isinstance(n, ast.If))
    assign_node = next(n for n in ast.walk(tree_other) if isinstance(n, ast.Assign))
    assert not _is_method_node(if_node)
    assert not _is_method_node(assign_node)


def test_process_single_shared_infra_direct(tmp_path):
    # _process_single_shared_infra の個別検証
    from backend.scripts.measure_branches import _process_single_shared_infra
    
    # preset がある場合
    b, detail = _process_single_shared_infra(str(tmp_path), "PresetTest", None, 42, set())
    assert b == 42
    assert "PresetTest: 42 branches (pre-counted)" in detail
    
    # path がない場合 (preset も None)
    b, detail = _process_single_shared_infra(str(tmp_path), "NoPathTest", None, None, set())
    assert b == 0
    assert "NoPathTest: (empty path)" in detail
    
    # 正常系 (preset が None で path がある場合)
    test_file = tmp_path / "infra.py"
    test_file.write_text("def f():\n    if True: pass", encoding="utf-8")
    seen = set()
    b, detail = _process_single_shared_infra(str(tmp_path), "InfraTest", str(test_file), None, seen)
    assert b == 1
    assert "InfraTest: 1 branches, 1 methods" in detail
    assert os.path.normcase(os.path.abspath(test_file)) in seen
    
    # 重複の場合
    b, detail = _process_single_shared_infra(str(tmp_path), "InfraTest", str(test_file), None, seen)
    assert b == 0
    assert "InfraTest: (counted elsewhere)" in detail


def test_main_no_mock_run():
    # 実環境での main() 実行の安全性の検証
    try:
        measure_branches.main()
    except Exception as e:
        import pytest
        pytest.fail(f"main() raised an exception unexpectedly: {e}")


def test_is_branch_node_invalid_input():
    # _is_branch_node に AST ノード以外のオブジェクトが渡された場合の検証
    from backend.scripts.measure_branches import _is_branch_node
    assert not _is_branch_node(None)
    assert not _is_branch_node("not a node")
    assert not _is_branch_node(123)


def test_is_method_node_invalid_input():
    # _is_method_node に AST ノード以外のオブジェクトが渡された場合の検証
    from backend.scripts.measure_branches import _is_method_node
    assert not _is_method_node(None)
    assert not _is_method_node("not a node")
    assert not _is_method_node(123)


def test_count_branches_empty_and_whitespace_path(caplog):
    # 空パスや空白パスが渡された場合の挙動をテスト
    import logging
    # 空文字
    with caplog.at_level(logging.WARNING, logger="measure_branches"):
        b, m = measure_branches.count_branches("")
        assert b == 0
        assert m == 0
        assert "File does not exist" in caplog.text

    # 空白のみ
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="measure_branches"):
        b, m = measure_branches.count_branches("   ")
        assert b == 0
        assert m == 0
        assert "File does not exist" in caplog.text


def test_worker_engines_and_shared_infra_static_paths():
    # ハードコードされたパスが実際にプロジェクト内に存在すること（またはプリセット）を検証
    # これにより設定ミスやファイル削除に伴う不整合を検知する
    import os
    
    script_dir = os.path.dirname(measure_branches.__file__)
    project_root = os.path.abspath(os.path.join(script_dir, '..', '..'))
    
    # 1. worker_engines のパス検証
    for worker_name, worker_data in measure_branches.worker_engines.items():
        for engine_name, engine_path in worker_data.get('engines', []):
            if engine_path:
                full_path = os.path.abspath(os.path.normpath(os.path.join(project_root, engine_path)))
                assert os.path.exists(full_path), f"Engine file does not exist: {full_path} (Worker: {worker_name})"

    # 2. shared_infra のパス検証
    for name, path, preset in measure_branches.shared_infra:
        if preset is None and path:
            full_path = os.path.abspath(os.path.normpath(os.path.join(project_root, path)))
            assert os.path.exists(full_path), f"Shared infra file does not exist: {full_path} (Infra: {name})"


def test_count_branches_complex_constructs(tmp_path):
    # try-except-finally やネストされた with など、複雑な構文を含むファイルのカウントテスト
    code = """
try:
    with open("a") as f1, open("b") as f2:
        assert 1 == 1
except ValueError:
    pass
except TypeError:
    pass
finally:
    assert True
"""
    test_file = tmp_path / "complex_test.py"
    test_file.write_text(code, encoding="utf-8")
    
    b, m = measure_branches.count_branches(str(test_file))
    
    # 期待されるブランチノード:
    # 1. with (ast.With)
    # 2. assert 1 == 1 (ast.Assert)
    # 3. except ValueError (ast.ExceptHandler)
    # 4. except TypeError (ast.ExceptHandler)
    # 5. assert True (ast.Assert)
    # (try-finally 自体は _is_branch_node の対象外。 ast.Try は対象外で、ExceptHandler のみが対象)
    # 合計 5 branches, 0 methods
    assert b == 5
    assert m == 0


def test_is_branch_node_more_invalid_types():
    # 様々な無効な型やオブジェクトに対する _is_branch_node / _is_method_node の動作検証
    from backend.scripts.measure_branches import _is_branch_node, _is_method_node
    
    class DummyObj:
        pass
        
    invalid_inputs = [
        [], {}, (), set(), DummyObj(), object(), 3.14, True, False
    ]
    for inp in invalid_inputs:
        assert not _is_branch_node(inp)
        assert not _is_method_node(inp)


def test_path_normalization_slashes(tmp_path):
    # スラッシュとバックスラッシュの表記揺れによる重複排除が機能するか検証
    test_file = tmp_path / "dummy_slashes.py"
    test_file.write_text("def f():\n    if True: pass", encoding="utf-8")
    
    path_str = str(test_file)
    # バックスラッシュをスラッシュに置換したものと、通常のパス
    path_slashes = path_str.replace("\\", "/")
    path_backslashes = path_str.replace("/", "\\")
    
    test_worker_engines = {
        'SlashWorker': {
            'worker_branches': 0,
            'engines': [
                ('slash.py', path_slashes),
                ('backslash.py', path_backslashes),
            ]
        }
    }
    
    with patch("backend.scripts.measure_branches.worker_engines", test_worker_engines):
        seen = set()
        worker_total, details = measure_branches.measure_worker_branches(str(tmp_path), seen)
        # 一方でカウントされ、もう一方は重複として除外されるため、合計は 1
        assert worker_total == 1
        assert "backslash.py: (counted elsewhere)" in details[0][2]


def test_count_branches_utf8_with_japanese(tmp_path):
    # 日本語文字を含むコードの解析が UTF-8 で正しくパースできることをテスト
    code = """
# 日本語のコメント
def 日本語関数():
    # ブランチ
    if True:
        assert "テスト" == "テスト"
"""
    test_file = tmp_path / "japanese_test.py"
    test_file.write_text(code, encoding="utf-8")
    b, m = measure_branches.count_branches(str(test_file))
    # if, assert = 2 branches
    # def = 1 method
    assert b == 2
    assert m == 1


def test_process_single_engine_relative_paths(tmp_path):
    # 相対パス表記が混在していても、正しく絶対パスとして正規化され、seen で重複排除されるかテスト
    from backend.scripts.measure_branches import _process_single_engine
    test_file = tmp_path / "relative_engine.py"
    test_file.write_text("def f():\n    if True: pass", encoding="utf-8")
    
    seen = set()
    # ../ を使って相対的な表現にする
    base_name = tmp_path.name
    rel_path = os.path.join("..", base_name, "relative_engine.py")
    
    # 1回目：カウントされる
    b1, d1 = _process_single_engine(str(tmp_path), "RelEngine", rel_path, seen)
    assert b1 == 1
    assert "RelEngine: 1 branches, 1 methods" in d1
    
    # 2回目：正規化された絶対パスが seen にあるため (counted elsewhere) になるはず
    # 異なる表現（直接の絶対パスなど）で呼び出す
    b2, d2 = _process_single_engine(str(tmp_path), "RelEngine", str(test_file), seen)
    assert b2 == 0
    assert "RelEngine: (counted elsewhere)" in d2


def test_print_results_edge_cases(capsys):
    # print_results において、合計値が負や 0、あるいはリストが空などの極端な場合の検証
    from backend.scripts.measure_branches import print_results
    print_results(-5, [], 0, [])
    captured = capsys.readouterr()
    output = captured.out
    assert "Worker系合計: -5" in output
    assert "共有基盤合計: 0" in output
    assert "総計: -5" in output


def test_count_branches_complex_ast_constructs(tmp_path):
    # async/await、デコレータ、ネストされたクラスメソッドなどの複雑な構文を含むコードの検証
    code = """
@decorator
async def outer():
    class Inner:
        def method(self):
            async for x in []:
                if x:
                    assert False
    return Inner
"""
    test_file = tmp_path / "complex_ast.py"
    test_file.write_text(code, encoding="utf-8")
    b, m = measure_branches.count_branches(str(test_file))
    # ブランチノード:
    # (async for は _is_branch_node の対象外)
    # 1. if x (ast.If)
    # 2. assert False (ast.Assert)
    # メソッドノード:
    # 1. async def outer (ast.AsyncFunctionDef)
    # 2. def method (ast.FunctionDef)
    assert b == 2
    assert m == 2


def test_count_branches_walk_exception(tmp_path, caplog):
    # ast.walk 実行中に例外が発生した場合の挙動を検証
    import logging
    test_file = tmp_path / "walk_exception.py"
    test_file.write_text("x = 1", encoding="utf-8")
    
    with caplog.at_level(logging.ERROR, logger="measure_branches"):
        with patch("ast.walk", side_effect=ValueError("Simulated Walk Error")):
            b, m = measure_branches.count_branches(str(test_file))
            assert b == 0
            assert m == 0
            assert len(caplog.records) > 0
            assert "Failed to parse branches for" in caplog.text
            assert "Simulated Walk Error" in caplog.text


def test_process_single_engine_path_normalization_edge_cases(tmp_path):
    # 相対パスや表記の異なるパス表現での seen 重複判定の多角的な検証
    from backend.scripts.measure_branches import _process_single_engine
    test_file = tmp_path / "norm_edge_cases.py"
    test_file.write_text("def f():\n    if True: pass", encoding="utf-8")
    
    seen = set()
    # 冗長なドットやスラッシュを含んだパス
    redundant_path = os.path.join(str(tmp_path), ".", "norm_edge_cases.py")
    
    # 1回目：カウントされる
    b1, d1 = _process_single_engine(str(tmp_path), "EngineEdge", redundant_path, seen)
    assert b1 == 1
    assert "EngineEdge: 1 branches, 1 methods" in d1
    
    # 2回目：正規化された絶対パスが seen にあるため、(counted elsewhere) になるはず
    # 異なるケースやバックスラッシュに置換したもの
    path_slashes = str(test_file).replace("\\", "/")
    b2, d2 = _process_single_engine(str(tmp_path), "EngineEdge", path_slashes, seen)
    assert b2 == 0
    assert "EngineEdge: (counted elsewhere)" in d2


def test_count_branches_deeply_nested_ast(tmp_path):
    # ラムダ式やリスト内包表記が混在するコードの検証
    code = """
def outer():
    lst = [x for x in range(10) if x % 2 == 0]
    func = lambda a: a if a > 0 else 0
    return lst, func
"""
    test_file = tmp_path / "deep_nested_ast.py"
    test_file.write_text(code, encoding="utf-8")
    b, m = measure_branches.count_branches(str(test_file))
    
    # リスト内包表記内の if (ast.If) や lambda 内の if-else (ast.IfExp)
    # _is_branch_node は isinstance(node, (ast.If, ast.For, ast.While, ast.ExceptHandler, ast.With, ast.Assert))
    # リスト内包表記の [x for ...] の for は ast.comprehension であり、ast.For ではない
    # リスト内包表記の if は ast.comprehension の ifs であり、ast.If ではない
    # lambda 内の if-else は ast.IfExp であり、ast.If ではない
    # よって、branch_count は 0 になるはず
    # メソッドノード: def outer = 1
    # lambda は ast.Lambda であり、_is_method_node (ast.FunctionDef, ast.AsyncFunctionDef) の対象外
    # よって、method_count は 1 になるはず
    assert b == 0
    assert m == 1


def test_count_branches_null_byte():
    # パスにヌルバイトを含む場合の OSError/ValueError ハンドリング検証
    b, m = measure_branches.count_branches("invalid\x00file.py")
    assert b == 0
    assert m == 0


def test_count_branches_invalid_path_types():
    # パスに None やリストなどの不正な型を渡した場合の挙動
    import pytest
    with pytest.raises(TypeError):
        measure_branches.count_branches(None)
    with pytest.raises(TypeError):
        measure_branches.count_branches([])


def test_process_single_engine_invalid_types():
    # _process_single_engine の引数に不正な型や None を渡した場合
    import pytest
    from backend.scripts.measure_branches import _process_single_engine
    with pytest.raises(AttributeError):
        _process_single_engine("root", "eng", "path.py", frozenset())


def test_process_single_shared_infra_invalid_preset():
    # _process_single_shared_infra で preset に不正な型（文字列や負の数）が指定された場合
    from backend.scripts.measure_branches import _process_single_shared_infra
    # presetが非Noneならそのまま返す
    b, detail = _process_single_shared_infra("root", "infra", "path.py", -10, set())
    assert b == -10
    assert "infra: -10 branches (pre-counted)" in detail

    b, detail = _process_single_shared_infra("root", "infra", "path.py", "invalid_preset", set())
    assert b == "invalid_preset"
    assert "infra: invalid_preset branches (pre-counted)" in detail


def test_print_results_empty_and_weird_values(capsys):
    # print_results に None や特殊なオブジェクトが渡された場合の安定性
    import pytest
    from backend.scripts.measure_branches import print_results
    # worker_total や shared_branch_total が None の場合、加算で TypeError が発生することを確認
    with pytest.raises(TypeError):
        print_results(None, [["A", None]], None, [None])


def test_count_branches_only_newlines_and_spaces(tmp_path):
    # 改行とスペースのみのファイルに対する挙動
    test_file = tmp_path / "whitespace.py"
    test_file.write_text("   \n  \n\t\n", encoding="utf-8")
    b, m = measure_branches.count_branches(str(test_file))
    assert b == 0
    assert m == 0


def test_measure_worker_branches_seen_type_error():
    # seen が set ではなくメンバーシップチェックできない不正な型の場合の挙動
    import pytest
    from backend.scripts.measure_branches import measure_worker_branches
    with pytest.raises(TypeError):
        measure_worker_branches("dummy_root", seen=object())


def test_measure_shared_infra_branches_seen_type_error():
    # seen が set ではなくメンバーシップチェックできない不正な型の場合の挙動
    import pytest
    from backend.scripts.measure_branches import measure_shared_infra_branches
    with pytest.raises(TypeError):
        measure_shared_infra_branches("dummy_root", seen=object())


def test_count_branches_ast_parse_type_error(tmp_path):
    # ast.parse に不正な型が渡るようなモックの挙動 (TypeErrorは呼び出し元に伝播する)
    import pytest
    test_file = tmp_path / "parse_type_error.py"
    test_file.write_text("x = 1", encoding="utf-8")
    with patch("ast.parse", side_effect=TypeError("Simulated Type Error")):
        with pytest.raises(TypeError):
            measure_branches.count_branches(str(test_file))



def test_count_branches_huge_lines(tmp_path):
    # 巨大な行数のファイルを生成してパースするエッジケース
    huge_code = "\n".join(["# comment line"] * 10000)
    test_file = tmp_path / "huge_comments.py"
    test_file.write_text(huge_code, encoding="utf-8")
    b, m = measure_branches.count_branches(str(test_file))
    assert b == 0
    assert m == 0


def test_count_branches_recursion_error(tmp_path):
    # ast.parse が RecursionError を投げた場合の挙動の検証
    test_file = tmp_path / "recursion.py"
    test_file.write_text("pass", encoding="utf-8")
    with patch("ast.parse", side_effect=RecursionError("maximum recursion depth exceeded")):
        import pytest
        with pytest.raises(RecursionError):
            measure_branches.count_branches(str(test_file))


def test_process_single_engine_invalid_project_root():
    # project_root に None または不正な型を渡したときの挙動
    from backend.scripts.measure_branches import _process_single_engine
    seen = set()
    import pytest
    with pytest.raises(TypeError):
        _process_single_engine(None, "engine_name", "engine_path.py", seen)


def test_process_single_shared_infra_invalid_types():
    # _process_single_shared_infra に不正な型を渡したときの挙動
    from backend.scripts.measure_branches import _process_single_shared_infra
    seen = set()
    import pytest
    with pytest.raises(TypeError):
        _process_single_shared_infra(None, "infra", "infra.py", None, seen)


def test_count_branches_binary_file(tmp_path, caplog):
    # バイナリファイル（GIFなど）を解析しようとした場合に例外がキャッチされ、0, 0 が返ることを検証
    import logging
    binary_data = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
    test_file = tmp_path / "test_image.gif"
    test_file.write_bytes(binary_data)
    
    with caplog.at_level(logging.ERROR, logger="measure_branches"):
        b, m = measure_branches.count_branches(str(test_file))
        assert b == 0
        assert m == 0
        assert len(caplog.records) > 0
        assert "Failed to parse branches for" in caplog.text


def test_count_branches_deep_nesting(tmp_path):
    # 深いネスト（20レベル）を持つ if 文の解析を検証（正常系）
    nest_level = 20
    code_lines = []
    for i in range(nest_level):
        indent = "    " * i
        code_lines.append(f"{indent}if True:")
    code_lines.append(f"{'    ' * nest_level}pass")
    code = "\n".join(code_lines)
    
    test_file = tmp_path / "deep_nesting.py"
    test_file.write_text(code, encoding="utf-8")
    
    b, m = measure_branches.count_branches(str(test_file))
    assert b == nest_level
    assert m == 0


def test_count_branches_excessive_nesting_syntax_error(tmp_path, caplog):
    # 制限を超える非常に深いネスト（150レベル）により SyntaxError になるエッジケース
    import logging
    nest_level = 150
    code_lines = []
    for i in range(nest_level):
        indent = "    " * i
        code_lines.append(f"{indent}if True:")
    code_lines.append(f"{'    ' * nest_level}pass")
    code = "\n".join(code_lines)
    
    test_file = tmp_path / "excessive_nesting.py"
    test_file.write_text(code, encoding="utf-8")
    
    with caplog.at_level(logging.ERROR, logger="measure_branches"):
        b, m = measure_branches.count_branches(str(test_file))
        assert b == 0
        assert m == 0
        assert len(caplog.records) > 0
        assert "Failed to parse branches for" in caplog.text
        assert "too many levels of indentation" in caplog.text


def test_process_single_engine_absolute_path(tmp_path):
    # _process_single_engine において engine_path が絶対パスの場合の検証
    from backend.scripts.measure_branches import _process_single_engine
    test_file = tmp_path / "abs_engine.py"
    test_file.write_text("def f():\n    if True: pass", encoding="utf-8")
    
    seen = set()
    # 絶対パスを engine_path として指定
    abs_path = os.path.abspath(test_file)
    b, detail = _process_single_engine(str(tmp_path), "AbsEngine", abs_path, seen)
    assert b == 1
    assert "AbsEngine: 1 branches, 1 methods" in detail
    assert os.path.normcase(abs_path) in seen


def test_process_single_shared_infra_empty_name(tmp_path):
    # _process_single_shared_infra において name が None または空文字列の場合の挙動
    from backend.scripts.measure_branches import _process_single_shared_infra
    test_file = tmp_path / "empty_name.py"
    test_file.write_text("def f(): pass", encoding="utf-8")
    
    seen = set()
    b, detail = _process_single_shared_infra(str(tmp_path), "", str(test_file), None, seen)
    assert b == 0
    assert ": 0 branches, 1 methods" in detail


def test_count_branches_control_characters(tmp_path, caplog):
    # 制御文字（\x01\x02など）を含むファイルを解析しようとした場合の挙動を検証
    import logging
    test_file = tmp_path / "control_chars.py"
    test_file.write_text("x = '\x01\x02'\nif True:\n    pass", encoding="utf-8")
    
    # 正常なPython構文の中に制御文字が文字列リテラルとして含まれている場合は正常に解析できるはず
    b, m = measure_branches.count_branches(str(test_file))
    assert b == 1
    assert m == 0

    # 構文として不正な場所に制御文字がある場合は SyntaxError になる
    test_file_invalid = tmp_path / "control_chars_invalid.py"
    test_file_invalid.write_text("\x01\x02 = 3", encoding="utf-8")
    with caplog.at_level(logging.ERROR, logger="measure_branches"):
        b, m = measure_branches.count_branches(str(test_file_invalid))
        assert b == 0
        assert m == 0
        assert "Failed to parse branches for" in caplog.text

