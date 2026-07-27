import os
import runpy
import pytest
from tests.scratch.migrate_e2e_files import migrate, MAPPING

def test_migrate_success(tmp_path):
    # すべてのソースファイルを作成
    for src in MAPPING.keys():
        src_file = tmp_path / src
        src_file.write_text(f"content of {src}", encoding="utf-8")

    migrate(str(tmp_path))

    # すべてのデスティネーションファイルが作成され、中身が正しいことを確認
    for src, dest in MAPPING.items():
        dest_file = tmp_path / dest
        assert dest_file.exists()
        assert dest_file.read_text(encoding="utf-8") == f"content of {src}"

def test_migrate_missing(tmp_path, capsys):
    # ファイルが存在しない場合
    migrate(str(tmp_path))

    captured = capsys.readouterr()
    for src in MAPPING.keys():
        assert f"Warning: {src} does not exist!" in captured.out
    assert "Migration copy completed." in captured.out

def test_migrate_main(tmp_path, monkeypatch):
    # 環境変数を上書き
    monkeypatch.setenv("ANTIGRAVITY_E2E_DIR", str(tmp_path))
    
    # 少なくとも1つソースファイルを作成して、コピーのパスも通るようにする
    first_src = list(MAPPING.keys())[0]
    src_file = tmp_path / first_src
    src_file.write_text("main test content", encoding="utf-8")

    runpy.run_module("tests.scratch.migrate_e2e_files", run_name="__main__")

    # 移行先のファイルが作成されていることを確認
    first_dest = MAPPING[first_src]
    dest_file = tmp_path / first_dest
    assert dest_file.exists()
    assert dest_file.read_text(encoding="utf-8") == "main test content"

def test_migrate_io_error(tmp_path, capsys, monkeypatch):
    # 移行元のファイルを用意する
    src_name = list(MAPPING.keys())[0]
    src_file = tmp_path / src_name
    src_file.write_text("dummy", encoding="utf-8")
    
    # open() が OSError を投げるように monkeypatch する
    original_open = open
    def mock_open(file, mode="r", *args, **kwargs):
        # 書込みモードで開く時に例外を発生させる
        if "w" in mode and str(file).endswith(".py"):
            raise OSError("Mock disk full error")
        return original_open(file, mode, *args, **kwargs)
        
    import builtins
    monkeypatch.setattr(builtins, "open", mock_open)
    
    migrate(str(tmp_path))
    
    # 例外メッセージがキャプチャされていることを確認
    captured = capsys.readouterr()
    assert "Error migrating" in captured.out
    assert "Mock disk full error" in captured.out
