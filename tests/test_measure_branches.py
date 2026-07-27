import sys
import os
import ast
import logging
import runpy
import pytest
from unittest.mock import patch, MagicMock

# パスの追加
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 対象モジュールをインポート
import backend.scripts.measure_branches as mb

# 1. _is_branch_node のテスト
def test_is_branch_node():
    assert mb._is_branch_node(ast.parse("if x:\n    pass").body[0]) is True
    assert mb._is_branch_node(ast.parse("for x in y:\n    pass").body[0]) is True
    assert mb._is_branch_node(ast.parse("while x:\n    pass").body[0]) is True
    assert mb._is_branch_node(ast.parse("try:\n    pass\nexcept Exception:\n    pass").body[0].handlers[0]) is True
    assert mb._is_branch_node(ast.parse("with x:\n    pass").body[0]) is True
    assert mb._is_branch_node(ast.parse("assert x").body[0]) is True
    assert mb._is_branch_node(ast.parse("pass").body[0]) is False
    assert mb._is_branch_node(ast.parse("x = 1").body[0]) is False

# 2. _is_method_node のテスト
def test_is_method_node():
    assert mb._is_method_node(ast.parse("def f():\n    pass").body[0]) is True
    assert mb._is_method_node(ast.parse("async def f():\n    pass").body[0]) is True
    assert mb._is_method_node(ast.parse("class C:\n    pass").body[0]) is False
    assert mb._is_method_node(ast.parse("pass").body[0]) is False

# 3. count_branches のテスト
def test_count_branches_success(tmp_path):
    # テスト用の一時ファイルを作成
    test_code = """
def my_func(x):
    if x > 0:
        return True
    else:
        return False
"""
    file_path = tmp_path / "dummy.py"
    file_path.write_text(test_code, encoding="utf-8")
    
    branches, methods = mb.count_branches(str(file_path))
    assert branches == 1
    assert methods == 1

def test_count_branches_not_exists(caplog):
    # 存在しないファイル
    with caplog.at_level(logging.WARNING):
        branches, methods = mb.count_branches("non_existent_file.py")
    assert branches == 0
    assert methods == 0
    assert "File does not exist" in caplog.text

def test_count_branches_is_dir(tmp_path, caplog):
    # ディレクトリを指定
    with caplog.at_level(logging.WARNING):
        branches, methods = mb.count_branches(str(tmp_path))
    assert branches == 0
    assert methods == 0
    assert "Path is a directory" in caplog.text

def test_count_branches_syntax_error(tmp_path, caplog):
    # 構文エラーのファイル
    test_code = "if x > 0"  # コロンがない
    file_path = tmp_path / "invalid.py"
    file_path.write_text(test_code, encoding="utf-8")
    
    with caplog.at_level(logging.ERROR):
        branches, methods = mb.count_branches(str(file_path))
    assert branches == 0
    assert methods == 0
    assert "Failed to parse branches" in caplog.text

def test_count_branches_os_error(tmp_path, caplog):
    # open が OSError を投げる場合をモック
    file_path = tmp_path / "dummy.py"
    file_path.write_text("pass", encoding="utf-8")
    
    with patch("builtins.open", side_effect=OSError("Mocked OS Error")):
        with caplog.at_level(logging.ERROR):
            branches, methods = mb.count_branches(str(file_path))
    assert branches == 0
    assert methods == 0
    assert "Failed to parse branches" in caplog.text

# 4. _process_single_engine のテスト
def test_process_single_engine_empty_path(caplog):
    seen = set()
    with caplog.at_level(logging.WARNING):
        branches, detail = mb._process_single_engine("dummy_root", "dummy_engine", "", seen)
    assert branches == 0
    assert "empty path" in detail
    assert "Engine path is empty" in caplog.text

def test_process_single_engine_seen():
    seen = {os.path.normcase(os.path.abspath("dummy_root/path.py"))}
    branches, detail = mb._process_single_engine("dummy_root", "dummy_engine", "path.py", seen)
    assert branches == 0
    assert "counted elsewhere" in detail

def test_process_single_engine_new(tmp_path):
    seen = set()
    test_code = "if True: pass"
    file_path = tmp_path / "engine.py"
    file_path.write_text(test_code, encoding="utf-8")
    
    branches, detail = mb._process_single_engine(str(tmp_path), "engine.py", "engine.py", seen)
    assert branches == 1
    assert "engine.py: 1 branches, 0 methods" in detail
    assert len(seen) == 1

# 5. measure_worker_branches のテスト
def test_measure_worker_branches(tmp_path):
    mock_worker_engines = {
        'TestWorker': {
            'worker_branches': 5,
            'engines': [
                ('test_engine.py', 'test_engine.py'),
            ]
        }
    }
    
    test_code = "if True: pass"
    file_path = tmp_path / "test_engine.py"
    file_path.write_text(test_code, encoding="utf-8")
    
    seen = set()
    with patch.dict(mb.worker_engines, mock_worker_engines, clear=True):
        total, details = mb.measure_worker_branches(str(tmp_path), seen)
    
    assert total == 6
    assert len(details) == 1
    assert "TestWorker: Worker=5 + Engines=1 = **6**" in details[0][0]
    assert "test_engine.py: 1 branches, 0 methods" in details[0][1]

# 6. _process_single_shared_infra のテスト
def test_process_single_shared_infra_preset():
    seen = set()
    branches, detail = mb._process_single_shared_infra("dummy_root", "infra", None, 10, seen)
    assert branches == 10
    assert "10 branches (pre-counted)" in detail

def test_process_single_shared_infra_empty_path(caplog):
    seen = set()
    with caplog.at_level(logging.WARNING):
        branches, detail = mb._process_single_shared_infra("dummy_root", "infra", "", None, seen)
    assert branches == 0
    assert "empty path" in detail
    assert "Shared infra path is empty" in caplog.text

def test_process_single_shared_infra_seen():
    seen = {os.path.normcase(os.path.abspath("dummy_root/infra.py"))}
    branches, detail = mb._process_single_shared_infra("dummy_root", "infra", "infra.py", None, seen)
    assert branches == 0
    assert "counted elsewhere" in detail

def test_process_single_shared_infra_new(tmp_path):
    seen = set()
    test_code = "if True: pass"
    file_path = tmp_path / "infra.py"
    file_path.write_text(test_code, encoding="utf-8")
    
    branches, detail = mb._process_single_shared_infra(str(tmp_path), "infra", "infra.py", None, seen)
    assert branches == 1
    assert "infra: 1 branches, 0 methods" in detail
    assert len(seen) == 1

# 7. measure_shared_infra_branches のテスト
def test_measure_shared_infra_branches(tmp_path):
    mock_shared_infra = [
        ('infra_preset', None, 15),
        ('infra_file.py', 'infra_file.py', None),
    ]
    
    test_code = "if True: pass"
    file_path = tmp_path / "infra_file.py"
    file_path.write_text(test_code, encoding="utf-8")
    
    seen = set()
    with patch.object(mb, "shared_infra", mock_shared_infra):
        total, details = mb.measure_shared_infra_branches(str(tmp_path), seen)
        
    assert total == 16
    assert len(details) == 2
    assert "infra_preset: 15 branches" in details[0]
    assert "infra_file.py: 1 branches" in details[1]

# 8. print_results のテスト
def test_print_results(capsys):
    worker_details = [
        ["Worker1: Worker=5 + Engines=1 = **6**", "  engine.py: 1 branches, 0 methods"]
    ]
    shared_details = [
        "infra_preset: 15 branches (pre-counted)",
        "infra_file.py: 1 branches, 0 methods"
    ]
    
    mb.print_results(6, worker_details, 16, shared_details)
    captured = capsys.readouterr()
    assert "=== Worker別分岐数（実測） ===" in captured.out
    assert "Worker1: Worker=5 + Engines=1 = **6**" in captured.out
    assert "=== 共有基盤 ===" in captured.out
    assert "infra_preset: 15 branches" in captured.out
    assert "総計: 22" in captured.out

# 9. main のテスト
def test_main():
    with patch.object(mb, "measure_worker_branches", return_value=(10, [["w_detail"]])) as mock_worker, \
         patch.object(mb, "measure_shared_infra_branches", return_value=(20, ["s_detail"])) as mock_shared, \
         patch.object(mb, "print_results") as mock_print:
         
        mb.main()
        
        mock_worker.assert_called_once()
        mock_shared.assert_called_once()
        mock_print.assert_called_once_with(10, [["w_detail"]], 20, ["s_detail"])

# 10. スクリプトとしての実行テスト（if __name__ == '__main__': main() のカバー用）
def test_script_execution(capsys):
    script_path = os.path.abspath(os.path.join(project_root, "backend", "scripts", "measure_branches.py"))
    
    # runpy でスクリプトを __main__ 名前空間で直接ロードし実行する。
    runpy.run_path(script_path, run_name="__main__")
    
    # 実行が成功し、正しい出力が得られたことを検証
    captured = capsys.readouterr()
    assert "Worker別分岐数" in captured.out
    assert "共有基盤" in captured.out
    assert "総計" in captured.out


# 11. エッジケースのテスト

def test_count_branches_null_byte(tmp_path, caplog):
    # NULLバイトを含むファイル（ValueErrorを発生させる）
    file_path = tmp_path / "null_byte.py"
    file_path.write_bytes(b"\x00\x00\x00")
    
    with caplog.at_level(logging.ERROR):
        branches, methods = mb.count_branches(str(file_path))
    assert branches == 0
    assert methods == 0
    assert "Failed to parse branches" in caplog.text


def test_count_branches_non_ascii(tmp_path):
    # 非ASCII文字を含むファイル
    test_code = """
# 日本語のコメント
def 関数名():
    if 表示する:
        print("こんにちは")
"""
    file_path = tmp_path / "non_ascii.py"
    file_path.write_text(test_code, encoding="utf-8")
    
    branches, methods = mb.count_branches(str(file_path))
    assert branches == 1
    assert methods == 1


def test_count_branches_invalid_path_types():
    # 不正な型を渡した時の例外の伝播を確認
    with pytest.raises(TypeError):
        mb.count_branches(None)
    
    # 整数の場合は os.path.exists が False を返すため、(0, 0) が返る
    branches, methods = mb.count_branches(123)
    assert branches == 0
    assert methods == 0


def test_process_single_engine_invalid_types():
    # project_rootやengine_pathが不正な型の場合の例外の挙動
    seen = set()
    with pytest.raises(TypeError):
        mb._process_single_engine(None, "dummy", 123, seen)


def test_process_single_shared_infra_invalid_types():
    seen = set()
    with pytest.raises(TypeError):
        mb._process_single_shared_infra(None, "dummy", 123, None, seen)


def test_count_branches_huge_input(tmp_path):
    # 巨大なファイルのパース
    huge_code = "\n".join(["if True:\n    pass"] * 1000)
    file_path = tmp_path / "huge.py"
    file_path.write_text(huge_code, encoding="utf-8")
    
    branches, methods = mb.count_branches(str(file_path))
    assert branches == 1000
    assert methods == 0


def test_count_branches_empty_file(tmp_path):
    # 空ファイルのテスト
    file_path = tmp_path / "empty.py"
    file_path.write_text("", encoding="utf-8")
    
    branches, methods = mb.count_branches(str(file_path))
    assert branches == 0
    assert methods == 0


def test_process_single_shared_infra_preset_zero():
    # preset が 0 (Falsy) の場合、正しく 0 branches として動作するか
    seen = set()
    branches, detail = mb._process_single_shared_infra("dummy_root", "infra_zero", None, 0, seen)
    assert branches == 0
    assert "0 branches (pre-counted)" in detail


def test_print_results_empty(capsys):
    # 空のリストを渡したときの動作テスト
    mb.print_results(0, [], 0, [])
    captured = capsys.readouterr()
    assert "=== Worker別分岐数（実測） ===" in captured.out
    assert "=== 共有基盤 ===" in captured.out
    assert "総計: 0" in captured.out

