import os
import tempfile
import json
import pytest
import runpy
import warnings
from backend.tests.scratch.read_log import read_user_inputs


def test_read_user_inputs_success():
    # テンポラリファイルを作成
    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".jsonl", encoding="utf-8") as temp:
        # 正しいデータと、異なるtypeのデータ、破損したJSONデータを書き込む
        temp.write(json.dumps({"type": "USER_INPUT", "content": "hello world\nline2"}) + "\n")
        temp.write(json.dumps({"type": "MODEL_OUTPUT", "content": "response"}) + "\n")
        temp.write("invalid json line\n")
        temp_path = temp.name

    try:
        # テスト実行
        inputs = read_user_inputs(temp_path)
        assert len(inputs) == 1
        assert inputs[0]["content"] == "hello world\nline2"
    finally:
        os.remove(temp_path)


def test_read_user_inputs_file_not_exist(capsys):
    inputs = read_user_inputs("non_existent_file_path_12345.jsonl")
    assert inputs == []
    captured = capsys.readouterr()
    assert "Log path does not exist!" in captured.out


def test_main_execution(monkeypatch, capsys):
    # DEFAULT_LOG_PATH が存在しない場合もあるので、モックするか、一時ファイルを用意して monkeypatch する
    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".jsonl", encoding="utf-8") as temp:
        temp.write(json.dumps({"type": "USER_INPUT", "content": "test content"}) + "\n")
        temp_path = temp.name

    try:
        # sys.argv をモックして一時ファイルのパスを渡す
        monkeypatch.setattr("sys.argv", ["read_log.py", temp_path])

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            # runpy でスクリプトを実行
            runpy.run_module("backend.tests.scratch.read_log", run_name="__main__")

        captured = capsys.readouterr()
        assert "Found 1 user inputs:" in captured.out
        assert "User Input 0: test content" in captured.out
    finally:
        os.remove(temp_path)


def test_read_user_inputs_non_dict_json():
    # 辞書ではない有効なJSONデータ（数値、文字列、配列）を含む一時ファイルを作成
    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".jsonl", encoding="utf-8") as temp:
        temp.write("123\n")
        temp.write('"just a string"\n')
        temp.write('[1, 2, 3]\n')
        temp_path = temp.name

    try:
        inputs = read_user_inputs(temp_path)
        # クラッシュせずに空のリストが返ることを確認
        assert inputs == []
    finally:
        os.remove(temp_path)
