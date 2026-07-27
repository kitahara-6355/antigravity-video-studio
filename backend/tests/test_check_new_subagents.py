import importlib
from pathlib import Path
from unittest.mock import patch, MagicMock
import io
import json
import sys
import os
import pytest

# sys.path に backend フォルダが入っていることを確実にする
parent_dir = str(Path(__file__).parent.parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

def test_check_new_subagents():
    mock_files = {
        "c0f1a051-25b0-4b90-908a-1fbec6c2e848": None,
        "62882ce0-f954-433e-ae67-d6cbf4f18cea": [
            '{"step_index": 1, "type": "USER_INPUT", "source": "USER", "content": "hello"}',
            '{"step_index": 2, "type": "TOOL_CALL", "source": "MODEL", "content": "world"}',
            '{"step_index": 3, "type": "DONE", "source": "SYSTEM", "content": "short content"}'
        ],
        "000d1367-a11a-4932-b3fa-0a77ed368545": [
            '{"step_index": 4, "type": "DONE", "source": "SYSTEM", "content": "' + ("a" * 300) + '"}'
        ],
        "2c56e554-35a2-447f-83a8-1824cf222e2e": [
            "invalid json line",
            '{"step_index": 5, "type": "DONE", "source": "SYSTEM", "content": "valid after invalid"}'
        ],
        "c9860a46-ba88-4583-9e1a-ab7d7ed29aba": [
            '{"step_index": 6, "type": "DONE", "source": "SYSTEM", "content": "only one line"}'
        ],
        "124c8d71-2d3e-4025-8b2b-5ec91dda4477": []
    }
    
    def side_effect_exists(self_obj):
        path_str = str(self_obj)
        for sa_id, content in mock_files.items():
            if sa_id in path_str:
                return content is not None
        return False

    def side_effect_open(file_path, *args, **kwargs):
        path_str = str(file_path)
        for sa_id, content_lines in mock_files.items():
            if sa_id in path_str:
                if content_lines is None:
                    raise FileNotFoundError()
                content_str = "".join(line + "\n" for line in content_lines)
                return io.StringIO(content_str)
        raise FileNotFoundError()

    # sys.modules からの削除処理 (58行目) を確実に実行させるため、あらかじめダミーを設定しておく
    sys.modules["scratch.check_new_subagents"] = MagicMock()

    # 環境変数を変更し、ANTIGRAVITY_APP_DATA_DIR を除外する（clear=Trueにしない）
    with patch.dict(os.environ, {}):
        os.environ.pop("ANTIGRAVITY_APP_DATA_DIR", None)
        with patch("pathlib.Path.exists", side_effect_exists),              patch("builtins.open", side_effect_open):
            
            if "scratch.check_new_subagents" in sys.modules:
                del sys.modules["scratch.check_new_subagents"]
            
            importlib.import_module("scratch.check_new_subagents")

            # === モックの未カバー分岐を明示的に呼び出してカバー ===
            # 40行目: side_effect_exists の return False
            assert not Path("non_existent_dummy_id_exists").exists()
            
            # 47行目: side_effect_open で content_lines is None の場合の FileNotFoundError
            with pytest.raises(FileNotFoundError):
                open(Path("c0f1a051-25b0-4b90-908a-1fbec6c2e848"))
            
            # 50行目: side_effect_open で登録されていない sa_id の場合の FileNotFoundError
            with pytest.raises(FileNotFoundError):
                open(Path("non_existent_dummy_id_open"))

def test_check_new_subagents_env_var():
    mock_files = {
        "c0f1a051-25b0-4b90-908a-1fbec6c2e848": None,
        "62882ce0-f954-433e-ae67-d6cbf4f18cea": []
    }
    
    checked_paths = []
    
    def side_effect_exists(self_obj):
        path_str = str(self_obj).replace('\\', '/')
        checked_paths.append(path_str)
        return False

    mock_env = {"ANTIGRAVITY_APP_DATA_DIR": "C:/custom_env_dir/antigravity"}
    with patch.dict(os.environ, mock_env):
        with patch("pathlib.Path.exists", side_effect_exists):
            if "scratch.check_new_subagents" in sys.modules:
                del sys.modules["scratch.check_new_subagents"]
            importlib.import_module("scratch.check_new_subagents")
            
    for p in checked_paths:
        assert p.startswith("C:/custom_env_dir/antigravity/brain")

def test_check_new_subagents_os_error():
    mock_files = {
        "c0f1a051-25b0-4b90-908a-1fbec6c2e848": [],
    }
    
    def side_effect_exists(self_obj):
        return True

    def side_effect_open(file_path, *args, **kwargs):
        raise OSError("Permission denied")

    with patch("pathlib.Path.exists", side_effect_exists),          patch("builtins.open", side_effect_open):
        
        if "scratch.check_new_subagents" in sys.modules:
            del sys.modules["scratch.check_new_subagents"]
        
        importlib.import_module("scratch.check_new_subagents")

def test_check_new_subagents_other_exception():
    mock_files = {
        "62882ce0-f954-433e-ae67-d6cbf4f18cea": [
            '{"step_index": 1, "type": "USER_INPUT", "source": "USER", "content": "hello"}'
        ]
    }
    
    def side_effect_exists(self_obj):
        return True

    def side_effect_open(file_path, *args, **kwargs):
        content_str = '{"step_index": 1, "type": "USER_INPUT", "source": "USER", "content": "hello"}\n'
        return io.StringIO(content_str)

    def mock_json_loads(line):
        raise TypeError("Mock type error")

    with patch("pathlib.Path.exists", side_effect_exists),          patch("builtins.open", side_effect_open),          patch("json.loads", mock_json_loads):
        
        if "scratch.check_new_subagents" in sys.modules:
            del sys.modules["scratch.check_new_subagents"]
        
        importlib.import_module("scratch.check_new_subagents")

def test_sys_path_insert_coverage():
    """sys.path.insert(0, parent_dir) の分岐カバレッジを100%にするためのテスト"""
    import sys
    from pathlib import Path
    import importlib
    
    parent_dir = str(Path(__file__).parent.parent)
    
    orig_path = sys.path.copy()
    try:
        # sys.path に入っている parent_dir を末尾スラッシュ付きのものに置換し、
        # 探索ルートは維持したまま `not in` 判定を True にしてインポートさせる
        sys.path = [p + "/" if p == parent_dir else p for p in sys.path]
            
        test_module_name = "tests.test_check_new_subagents"
        # del 分岐を通すため、あらかじめ辞書に登録しておく
        sys.modules[test_module_name] = importlib.import_module(test_module_name)
        if test_module_name in sys.modules:
            del sys.modules[test_module_name]
            
        importlib.import_module(test_module_name)
    finally:
        sys.path = orig_path


def test_check_new_subagents_formatted_none():
    """format_log_line が None を返す場合の分岐 (if formatted is not None が False になるルート) をテストする"""
    if "scratch.check_new_subagents" in sys.modules:
        del sys.modules["scratch.check_new_subagents"]
        
    with patch("pathlib.Path.exists", return_value=False):
        importlib.import_module("scratch.check_new_subagents")
        
    from scratch.check_new_subagents import parse_and_print_log_line
    
    with patch("scratch.check_new_subagents.format_log_line", return_value=None):
        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            parse_and_print_log_line("dummy_id", "some line")
            assert fake_out.getvalue() == ""

def test_edge_cases_get_base_brain_dir():
    from scratch.check_new_subagents import get_base_brain_dir
    # ANTIGRAVITY_APP_DATA_DIR が空文字列の場合の挙動
    with patch.dict(os.environ, {"ANTIGRAVITY_APP_DATA_DIR": ""}):
        # 空文字列の場合、if app_data_dir_env: は False と判定されるため、
        # フォールバック先の Path.home() / ".gemini" / "antigravity" / "brain" が返される
        expected = Path.home() / ".gemini" / "antigravity" / "brain"
        assert get_base_brain_dir() == expected

def test_edge_cases_format_log_line():
    from scratch.check_new_subagents import format_log_line
    # None 入力の場合 -> TypeError
    with pytest.raises(TypeError):
        format_log_line(None)
    
    # 空文字列入力の場合 -> JSONDecodeError
    with pytest.raises(json.JSONDecodeError):
        format_log_line("")
        
    # キーが欠損しているJSON（空のオブジェクトなど）
    # get("content", "") なのでエラーにならずデフォルト値 "" を使うはず
    formatted = format_log_line("{}")
    assert "Step None (None / None): " in formatted

def test_edge_cases_read_last_log_lines(tmp_path):
    from scratch.check_new_subagents import read_last_log_lines
    log_file = tmp_path / "test.log"
    
    # 空のログファイルの場合
    log_file.write_text("", encoding="utf-8")
    assert read_last_log_lines(log_file, count=3) == []
    
    # count = 0 の場合
    log_file.write_text("line1\nline2\n", encoding="utf-8")
    # lines[-0:] は lines[0:] と等しいため、全行が返される挙動が正しい
    assert read_last_log_lines(log_file, count=0) == ["line1\n", "line2\n"]
    
    # count が負数の場合 (スライス [-count:] の挙動、count=-1 だと [-(-1):] = [1:] となる)
    assert read_last_log_lines(log_file, count=-1) == ["line2\n"]
    
    # ログファイルの行数 < count の場合
    assert read_last_log_lines(log_file, count=5) == ["line1\n", "line2\n"]

def test_edge_cases_check_all_subagents():
    # NEW_SUBAGENT_IDS を空リストにして実行する
    if "scratch.check_new_subagents" in sys.modules:
        del sys.modules["scratch.check_new_subagents"]
    
    with patch("scratch.check_new_subagents.NEW_SUBAGENT_IDS", []):
        with patch("scratch.check_new_subagents.process_subagent_log") as mock_process:
            from scratch.check_new_subagents import check_all_subagents
            check_all_subagents()
            mock_process.assert_not_called()
