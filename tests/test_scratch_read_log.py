import sys
import os
# Ensure project root has higher priority in sys.path than backend to avoid import collision of tests.scratch.read_log
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_backend_dir = os.path.join(_project_root, "backend")
def _norm(p):
    return os.path.normcase(os.path.abspath(p))
sys.path = [p for p in sys.path if _norm(p) not in (_norm(_backend_dir), _norm(_project_root))]
sys.path.insert(0, _project_root)
sys.path.insert(1, _backend_dir)

import json
import runpy
from pathlib import Path
from unittest.mock import patch, mock_open
from tests.scratch.read_log import main

def test_main_path_not_exists(capsys):
    # Path.exists が False を返すようにモック化
    with patch.object(Path, "exists", return_value=False):
        main()
    captured = capsys.readouterr()
    assert "Log path not found:" in captured.out

def test_main_path_exists_and_log_processing(capsys):
    # Path.exists が True を返すようにモック化
    # 複数パターンを含むモックデータを定義
    log_data = [
        # 1. 正常データ (USER_INPUT) -> 出力されるはず
        json.dumps({"step_index": 10100, "source": "USER", "type": "USER_INPUT", "content": "Hello World"}),
        # 2. 正常データ (PLANNER_RESPONSE) -> 出力されるはず
        json.dumps({"step_index": 10153, "source": "MODEL", "type": "PLANNER_RESPONSE", "content": "Hi there"}),
        # 3. 正常範囲外のstep_index (低すぎる) -> 出力されないはず
        json.dumps({"step_index": 10099, "source": "USER", "type": "USER_INPUT", "content": "Ignore me - low"}),
        # 4. 正常範囲外のstep_index (高すぎる) -> 出力されないはず
        json.dumps({"step_index": 10154, "source": "USER", "type": "USER_INPUT", "content": "Ignore me - high"}),
        # 5. step_index が None -> 出力されないはず
        json.dumps({"source": "USER", "type": "USER_INPUT", "content": "No step index"}),
        # 6. type が対象外 -> 出力されないはず
        json.dumps({"step_index": 10110, "source": "SYSTEM", "type": "SYSTEM_LOG", "content": "System message"}),
        # 7. content が空文字列 -> 出力されないはず
        json.dumps({"step_index": 10111, "source": "USER", "type": "USER_INPUT", "content": ""}),
        # 8. content が存在しない -> 出力されないはず
        json.dumps({"step_index": 10112, "source": "USER", "type": "USER_INPUT"}),
        # 9. 無効なJSON行 (例外発生パスの検証) -> passされるはず
        "invalid json content {"
    ]
    mock_file_content = "\n".join(log_data)
    
    with patch.object(Path, "exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=mock_file_content)):
        main()
        
    captured = capsys.readouterr()
    
    # 正常データの出力確認
    assert "[10100] USER (USER_INPUT):" in captured.out
    assert "Hello World" in captured.out
    assert "[10153] MODEL (PLANNER_RESPONSE):" in captured.out
    assert "Hi there" in captured.out
    
    # 除外されるデータの出力がないことの確認
    assert "Ignore me" not in captured.out
    assert "No step index" not in captured.out
    assert "System message" not in captured.out

def test_main_as_script(capsys):
    # __name__ == "__main__" のパスをカバーする
    import warnings
    with patch.object(Path, "exists", return_value=False):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            runpy.run_module("tests.scratch.read_log", run_name="__main__")
        
    captured = capsys.readouterr()
    assert "Log path not found:" in captured.out

def test_main_non_dict_json(capsys):
    # JSONとしては有効だが、辞書型ではないデータ（数値、文字列、リスト）を含む場合
    log_data = [
        "123",
        '"just a string"',
        "[1, 2, 3]"
    ]
    mock_file_content = "\n".join(log_data)
    
    with patch.object(Path, "exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=mock_file_content)):
        main()
        
    captured = capsys.readouterr()
    # 何も出力されず、例外でクラッシュしないことを確認
    assert captured.out == ""
