# -*- coding: utf-8 -*-
import sys
from pathlib import Path

# backend ディレクトリの親を sys.path に追加して、backend.xxxxx としてインポートできるようにする
_parent_dir = str(Path(__file__).resolve().parent.parent.parent)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

# backend ディレクトリ自体も sys.path に追加
_backend_dir = str(Path(__file__).resolve().parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

import pytest
from unittest.mock import patch, mock_open
import runpy
from backend.ux_verification.scratch.update_user_manual_5stages import decode_line, main

def test_decode_line_utf8():
    # UTF-8デコード
    text = "こんにちは"
    assert decode_line(text.encode("utf-8")) == text

def test_decode_line_cp932():
    # CP932デコード (UTF-8ではデコードできないバイト列)
    text = "こんにちは"
    cp932_bytes = text.encode("cp932")
    assert decode_line(cp932_bytes) == text

def test_decode_line_fallback():
    # 両方デコードできない場合の errors="replace" フォールバック
    # b"\x81\x00" は UTF-8 でも CP932 でもデコードエラーになる
    bad_bytes = b"\x81\x00"
    res = decode_line(bad_bytes)
    assert "\ufffd" in res

def test_main_success(tmp_path):
    # 置換成功ケース
    dummy_manual = tmp_path / "USER_MANUAL.md"
    content = "### 🎤 チャンネル主のUXストーリー\n古いストーリー\n### 🛠️ 管理者のUXストーリー\n管理者用"
    dummy_manual.write_text(content, encoding="utf-8")

    # MANUAL_PATHをパッチしてmainを実行
    with patch("backend.ux_verification.scratch.update_user_manual_5stages.MANUAL_PATH", dummy_manual):
        main()

    # 置換されているか確認
    updated_content = dummy_manual.read_text(encoding="utf-8")
    assert "5つのステップ" in updated_content
    assert "### 🛠️ 管理者のUXストーリー" in updated_content
    assert "古いストーリー" not in updated_content

def test_main_no_match(tmp_path, capsys):
    # 置換対象がないケース
    dummy_manual = tmp_path / "USER_MANUAL.md"
    content = "### 置換対象がないドキュメント\n管理者用"
    dummy_manual.write_text(content, encoding="utf-8")

    with patch("backend.ux_verification.scratch.update_user_manual_5stages.MANUAL_PATH", dummy_manual):
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 1

    # 警告メッセージが出力されていること
    captured = capsys.readouterr()
    assert "置換対象セクションが見つかりませんでした" in captured.out
    
    # 内容が変わっていないこと
    assert dummy_manual.read_text(encoding="utf-8") == content

def test_main_file_not_found(tmp_path, capsys):
    # MANUAL_PATHが存在しない場合のケース
    dummy_manual = tmp_path / "NON_EXISTENT_USER_MANUAL.md"
    
    with patch("backend.ux_verification.scratch.update_user_manual_5stages.MANUAL_PATH", dummy_manual):
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 1

    # エラーメッセージが標準出力に表示されていること
    captured = capsys.readouterr()
    assert "USER_MANUAL.md が見つかりませんでした" in captured.out

def test_run_as_main(tmp_path):
    # if __name__ == "__main__": のパスをカバーする
    # builtins.openをモックして実ファイルへのアクセスを避ける
    dummy_content = "### 🎤 チャンネル主のUXストーリー\n古いストーリー\n### 🛠️ 管理者のUXストーリー\n管理者用"
    
    m = mock_open(read_data=dummy_content.encode("utf-8"))
    
    with patch("builtins.open", m):
        # スクリプトのパスを取得
        current_dir = Path(__file__).resolve().parent
        script_path = current_dir.parent / "ux_verification" / "scratch" / "update_user_manual_5stages.py"
        
        runpy.run_path(str(script_path), run_name="__main__")

    # 書き込みが行われ、期待する文字列が含まれていることの検証
    # m().write は書き込みモードで開かれたファイルオブジェクトに対するwrite呼び出し
    write_calls = [call.args[0] for call in m().write.call_args_list]
    assert any("5つのステップ" in text for text in write_calls)


def test_decode_line_invalid_type():
    # 引数が bytes または bytearray ではない場合の TypeError 検証
    with pytest.raises(TypeError) as excinfo:
        decode_line("not bytes")
    assert "line_bytes must be bytes or bytearray" in str(excinfo.value)

    with pytest.raises(TypeError):
        decode_line(None)

def test_main_read_oserror(tmp_path, capsys):
    # ファイル読み込み時に OSError が発生するケース
    dummy_manual = tmp_path / "USER_MANUAL.md"
    dummy_manual.write_text("dummy", encoding="utf-8")

    with patch("backend.ux_verification.scratch.update_user_manual_5stages.MANUAL_PATH", dummy_manual):
        with patch("builtins.open", side_effect=OSError("Read error")):
            with pytest.raises(SystemExit) as excinfo:
                main()
            assert excinfo.value.code == 1

    captured = capsys.readouterr()
    assert "読み込み中にエラーが発生しました" in captured.out

def test_main_write_oserror(tmp_path, capsys):
    # ファイル書き込み時に OSError が発生するケース
    dummy_manual = tmp_path / "USER_MANUAL.md"
    content = "### 🎤 チャンネル主のUXストーリー\n古いストーリー\n### 🛠️ 管理者のUXストーリー\n管理者用"
    dummy_manual.write_text(content, encoding="utf-8")

    original_open = open
    def mock_open_func(file, mode="r", *args, **kwargs):
        if "w" in mode:
            raise OSError("Write error")
        return original_open(file, mode, *args, **kwargs)

    with patch("backend.ux_verification.scratch.update_user_manual_5stages.MANUAL_PATH", dummy_manual):
        with patch("builtins.open", side_effect=mock_open_func):
            with pytest.raises(SystemExit) as excinfo:
                main()
            assert excinfo.value.code == 1

    captured = capsys.readouterr()
    assert "書き込み中にエラーが発生しました" in captured.out
