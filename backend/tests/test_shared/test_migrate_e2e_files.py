import os
import sys
import runpy
import pytest
from tests.scratch.migrate_e2e_files import migrate, MAPPING

def test_migrate_success(tmp_path):
    # 準備：移行元のファイルを用意する
    e2e_dir = str(tmp_path)
    
    # ダミーの内容
    dummy_content = "def test_dummy(): pass"
    
    for src_name in MAPPING.keys():
        src_path = os.path.join(e2e_dir, src_name)
        with open(src_path, "w", encoding="utf-8") as f:
            f.write(dummy_content)
            
    # 実行
    migrate(e2e_dir)
    
    # 検証：すべての移行先ファイルがコピーされ、内容が一致すること
    for src_name, dest_name in MAPPING.items():
        dest_path = os.path.join(e2e_dir, dest_name)
        assert os.path.exists(dest_path)
        with open(dest_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert content == dummy_content

def test_migrate_warning(tmp_path, capsys):
    # 準備：移行元のファイルを配置しない
    e2e_dir = str(tmp_path)
    
    # 実行
    migrate(e2e_dir)
    
    # 検証：標準出力にWarningが出ていること
    captured = capsys.readouterr()
    for src_name in MAPPING.keys():
        assert f"Warning: {src_name} does not exist!" in captured.out
    assert "Migration copy completed." in captured.out

def test_migrate_main_execution(tmp_path, monkeypatch, capsys):
    # if __name__ == "__main__": ブロックの実行をテストする
    e2e_dir = str(tmp_path)
    
    # 環境変数を monkeypatch で差し替える
    monkeypatch.setenv("ANTIGRAVITY_E2E_DIR", e2e_dir)
    
    target_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "scratch", "migrate_e2e_files.py")
    )
    
    # スクリプトを直接実行
    runpy.run_path(target_path, run_name="__main__")
    
    # 標準出力に警告が含まれていることを確認
    captured = capsys.readouterr()
    for src_name in MAPPING.keys():
        assert f"Warning: {src_name} does not exist!" in captured.out
    assert "Migration copy completed." in captured.out

def test_migrate_overwrite(tmp_path):
    # 準備：移行元のファイルと、すでに存在する移行先のファイルを用意する
    e2e_dir = str(tmp_path)
    
    src_content = "def test_new(): pass"
    old_dest_content = "def test_old(): pass"
    
    for src_name, dest_name in MAPPING.items():
        src_path = os.path.join(e2e_dir, src_name)
        dest_path = os.path.join(e2e_dir, dest_name)
        
        with open(src_path, "w", encoding="utf-8") as f:
            f.write(src_content)
            
        with open(dest_path, "w", encoding="utf-8") as f:
            f.write(old_dest_content)
            
    # 実行
    migrate(e2e_dir)
    
    # 検証：すべての移行先ファイルが上書きコピーされ、新しい内容と一致すること
    for dest_name in MAPPING.values():
        dest_path = os.path.join(e2e_dir, dest_name)
        assert os.path.exists(dest_path)
        with open(dest_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert content == src_content

def test_migrate_io_error(tmp_path, capsys, monkeypatch):
    # 準備：移行元のファイルを用意する
    e2e_dir = str(tmp_path)
    src_name = list(MAPPING.keys())[0]
    src_path = os.path.join(e2e_dir, src_name)
    
    with open(src_path, "w", encoding="utf-8") as f:
        f.write("dummy")
        
    # open() が OSError を投げるように monkeypatch する
    original_open = open
    def mock_open(file, mode="r", *args, **kwargs):
        if "w" in mode and str(file).endswith(".py"):
            raise OSError("Mock disk full error")
        return original_open(file, mode, *args, **kwargs)
        
    import builtins
    monkeypatch.setattr(builtins, "open", mock_open)
    
    # 実行
    migrate(e2e_dir)
    
    # 検証：例外が発生してもクラッシュせず、エラーメッセージが標準出力に出ていること
    captured = capsys.readouterr()
    assert "Error migrating" in captured.out
    assert "Mock disk full error" in captured.out

