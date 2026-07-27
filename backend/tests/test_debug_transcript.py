import json
import pytest
import sys
from unittest.mock import patch
from backend.scratch.debug_transcript import (
    read_transcript_lines,
    parse_transcript_line,
    format_transcript_data,
    print_transcript_range,
    main,
)


def test_read_transcript_lines_not_exist():
    # 存在しないパスの場合は空リストが返ること
    lines = read_transcript_lines("non_existent_file.jsonl")
    assert lines == []


def test_read_transcript_lines_exist(tmp_path):
    # 存在するパスの場合は行が読み込めること
    log_file = tmp_path / "test_log.jsonl"
    log_file.write_text("line1\nline2\n", encoding="utf-8")
    lines = read_transcript_lines(str(log_file))
    assert lines == ["line1\n", "line2\n"]


def test_parse_transcript_line():
    # JSONが正しくパースできること
    line = '{"source": "user", "type": "input", "status": "done"}'
    data = parse_transcript_line(line)
    assert data["source"] == "user"
    assert data["type"] == "input"
    assert data["status"] == "done"


def test_format_transcript_data():
    # データが正しくフォーマットされること
    data = {
        "source": "user",
        "type": "input",
        "status": "done",
        "content": "hello world",
        "tool_calls": [{"name": "some_tool"}],
    }
    formatted = format_transcript_data(data)
    assert "source=user type=input status=done" in formatted
    assert "content: hello world" in formatted
    assert 'tool_calls: [{"name": "some_tool"}]' in formatted


def test_print_transcript_range_not_found(capsys):
    # ファイルがない場合は "Error: Log file not found" が出力されること
    print_transcript_range("non_existent.jsonl")
    captured = capsys.readouterr()
    assert "Error: Log file not found\n" in captured.out


def test_print_transcript_range_success(tmp_path, capsys):
    # 正常に出力されること
    log_file = tmp_path / "test_log.jsonl"
    data1 = {"source": "user", "type": "input", "status": "done"}
    data2 = {"source": "system", "type": "output", "status": "success"}
    
    with open(log_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(data1) + "\n")
        f.write(json.dumps(data2) + "\n")
        
    print_transcript_range(str(log_file), start=0, end=2)
    captured = capsys.readouterr()
    assert "=== Line 0 ===" in captured.out
    assert "source=user type=input status=done" in captured.out
    assert "=== Line 1 ===" in captured.out
    assert "source=system type=output status=success" in captured.out


def test_print_transcript_range_parse_error(tmp_path, capsys):
    # パースエラー時にクラッシュしないこと
    log_file = tmp_path / "test_log.jsonl"
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("invalid json\n")
        
    print_transcript_range(str(log_file), start=0, end=1)
    captured = capsys.readouterr()
    assert "=== Line 0 ===" in captured.out
    assert "Error parsing line 0" in captured.out


def test_main(tmp_path, capsys):
    # main 関数の引数処理と実行をテスト
    log_file = tmp_path / "test_log.jsonl"
    log_file.write_text('{"source": "user", "type": "input", "status": "done"}\n', encoding="utf-8")
    
    test_args = ["prog", "--path", str(log_file), "--start", "0", "--end", "1"]
    with patch.object(sys, 'argv', test_args):
        main()
        
    captured = capsys.readouterr()
    assert "=== Line 0 ===" in captured.out
    assert "source=user type=input status=done" in captured.out


def test_read_transcript_lines_is_directory(tmp_path):
    # ディレクトリパスを指定した際にクラッシュせず空リストが返ること
    dir_path = tmp_path / "some_directory"
    dir_path.mkdir()
    lines = read_transcript_lines(str(dir_path))
    assert lines == []


def test_format_transcript_data_invalid_type():
    # 辞書型以外を渡した際に TypeError が発生すること
    with pytest.raises(TypeError, match="Input data must be a dictionary"):
        format_transcript_data("invalid data type")


def test_format_transcript_data_non_string_content():
    # content が文字列でなくても文字列にキャストされてクラッシュしないこと
    data = {
        "source": "user",
        "type": "input",
        "status": "done",
        "content": 12345,  # 整数値
        "tool_calls": "not a list",  # リストでない
    }
    formatted = format_transcript_data(data)
    assert "content: 12345" in formatted
    assert 'tool_calls: "not a list"' in formatted


def test_print_transcript_range_invalid_indices(capsys):
    # インデックスがマイナスまたは start > end の場合にエラーメッセージが出力されること
    print_transcript_range("some_file.jsonl", start=-1, end=5)
    captured = capsys.readouterr()
    assert "Error: Indices must be non-negative" in captured.out

    print_transcript_range("some_file.jsonl", start=5, end=3)
    captured = capsys.readouterr()
    assert "Error: Start index must be less than or equal to end index" in captured.out


def test_print_transcript_range_json_decode_error(tmp_path, capsys):
    # JSONデコードエラー時に個別のエラーメッセージが出力されること
    log_file = tmp_path / "test_log.jsonl"
    log_file.write_text("not a valid json line\n", encoding="utf-8")
    
    print_transcript_range(str(log_file), start=0, end=1)
    captured = capsys.readouterr()
    assert "Error parsing line 0 as JSON" in captured.out


def test_read_transcript_lines_unicode_decode_error(tmp_path):
    # デコードエラーが起きるバイト列でもクラッシュせず、errors="replace" によって代替文字で読み込めること
    log_file = tmp_path / "invalid_utf8.jsonl"
    with open(log_file, "wb") as f:
        f.write(b"\xff\xff\xff\xff\n")
    
    lines = read_transcript_lines(str(log_file))
    assert len(lines) == 1
    assert "" in lines[0]


def test_print_transcript_range_specific_errors(tmp_path, capsys):
    # KeyError, AttributeError, ValueError が発生した際に
    # print_transcript_range がそれらをキャッチしてクラッシュしないこと
    log_file = tmp_path / "test_log.jsonl"
    log_file.write_text('{"source": "user"}\n', encoding="utf-8")
    
    # format_transcript_data が KeyError を投げるようにパッチする
    with patch("backend.scratch.debug_transcript.format_transcript_data", side_effect=KeyError("dummy key error")):
        print_transcript_range(str(log_file), start=0, end=1)
    
    captured = capsys.readouterr()
    assert "Unexpected error on line 0: 'dummy key error'" in captured.out

    # format_transcript_data が AttributeError を投げるようにパッチする
    with patch("backend.scratch.debug_transcript.format_transcript_data", side_effect=AttributeError("dummy attribute error")):
        print_transcript_range(str(log_file), start=0, end=1)
    
    captured = capsys.readouterr()
    assert "Unexpected error on line 0: dummy attribute error" in captured.out


def test_read_transcript_lines_unicode_replace(tmp_path):
    # 一部デコードできないバイト列があっても、errors="replace" によって諦めずに読み込めること
    log_file = tmp_path / "broken_utf8.jsonl"
    with open(log_file, "wb") as f:
        f.write(b'{"source": "user", "type": "input", "status": "done"}\n')
        f.write(b"invalid \xff\xff bytes\n")
        f.write(b'{"source": "system", "type": "output", "status": "success"}\n')
        
    lines = read_transcript_lines(str(log_file))
    assert len(lines) == 3
    assert "user" in lines[0]
    assert "" in lines[1]
    assert "system" in lines[2]


def test_parse_transcript_line_not_dict():
    # 辞書型以外の JSON の場合に ValueError が発生すること
    with pytest.raises(ValueError, match="Parsed JSON must be a dictionary"):
        parse_transcript_line("[1, 2, 3]")
        
    with pytest.raises(ValueError, match="Parsed JSON must be a dictionary"):
        parse_transcript_line('"string"')


def test_format_transcript_data_missing_fields():
    # フィールドが欠損している場合に <missing> とフォーマットされること
    data = {}
    formatted = format_transcript_data(data)
    assert "source=<missing> type=<missing> status=<missing>" in formatted


def test_print_transcript_range_out_of_bounds(tmp_path, capsys):
    # start が総行数以上の時に Warning が出力されること
    log_file = tmp_path / "test_log.jsonl"
    log_file.write_text('{"source": "user", "type": "input", "status": "done"}\n', encoding="utf-8")
    
    print_transcript_range(str(log_file), start=5, end=10)
    captured = capsys.readouterr()
    assert "Warning: Start index 5 is out of bounds (total lines: 1)" in captured.out


def test_print_transcript_range_empty_vs_not_exist(tmp_path, capsys):
    # ファイルが存在しない場合
    print_transcript_range("non_existent_file.jsonl", start=0, end=5)
    captured = capsys.readouterr()
    assert "Error: Log file not found" in captured.out
    
    # ファイルが空の場合
    log_file = tmp_path / "empty_log.jsonl"
    log_file.write_text("", encoding="utf-8")
    print_transcript_range(str(log_file), start=0, end=5)
    captured = capsys.readouterr()
    assert "Warning: Log file is empty or could not be read" in captured.out


def test_read_transcript_lines_os_error(tmp_path):
    # openがOSErrorを投げた場合に空リストが返ること
    log_file = tmp_path / "exist.jsonl"
    log_file.write_text("dummy", encoding="utf-8")
    with patch("builtins.open", side_effect=OSError("Permission denied")):
        lines = read_transcript_lines(str(log_file))
        assert lines == []


def test_format_transcript_data_json_dumps_error():
    # tool_calls の JSON シリアライズが例外を投げた場合にフォールバックすること
    data = {
        "source": "user",
        "type": "input",
        "status": "done",
        "tool_calls": {"unserializable": object()}
    }
    formatted = format_transcript_data(data)
    assert "tool_calls: " in formatted
    assert "unserializable" in formatted


def test_print_transcript_range_directory(tmp_path, capsys):
    # ディレクトリパスが指定された場合にエラーが出力されること
    dir_path = tmp_path / "test_dir"
    dir_path.mkdir()
    print_transcript_range(str(dir_path))
    captured = capsys.readouterr()
    assert "Error: Path is a directory" in captured.out


def test_print_transcript_range_type_error(tmp_path, capsys):
    # format_transcript_data が TypeError を投げた際にキャッチされること
    log_file = tmp_path / "test_log.jsonl"
    log_file.write_text('{"source": "user"}\n', encoding="utf-8")
    
    with patch("backend.scratch.debug_transcript.format_transcript_data", side_effect=TypeError("Dummy TypeError")):
        print_transcript_range(str(log_file), start=0, end=1)
        
    captured = capsys.readouterr()
    assert "Type error on line 0: Dummy TypeError" in captured.out


def test_print_transcript_range_value_error(tmp_path, capsys):
    # JSONが辞書型以外で ValueError が投げられた際にキャッチされること
    log_file = tmp_path / "test_log.jsonl"
    log_file.write_text("[1, 2, 3]\n", encoding="utf-8")
    
    print_transcript_range(str(log_file), start=0, end=1)
    
    captured = capsys.readouterr()
    assert "Value error on line 0:" in captured.out


def test_main_execution_as_main():
    # runpy を使用して __name__ == "__main__" のルートを実行する
    import runpy
    import sys
    import os
    from unittest.mock import patch
    
    test_args = ["prog", "--help"]
    script_path = os.path.abspath("backend/scratch/debug_transcript.py")
    with patch.object(sys, 'argv', test_args):
        try:
            runpy.run_path(script_path, run_name="__main__")
        except SystemExit:
            pass


def test_main_default_path_not_exists(capsys):
    # 引数なしで DEFAULT_LOG_PATH が存在しない場合の挙動をテスト
    with patch("os.path.exists", return_value=False), patch("sys.argv", ["prog"]):
        main()
    captured = capsys.readouterr()
    assert "Error: Log file not found" in captured.out


def test_main_default_path_exists(tmp_path, capsys):
    # 引数なしで DEFAULT_LOG_PATH が存在する場合の挙動をテスト
    log_file = tmp_path / "transcript.jsonl"
    log_file.write_text('{"source": "user", "type": "input", "status": "done"}\n', encoding="utf-8")
    
    # DEFAULT_LOG_PATH を一時ファイルに差し替える
    with patch("backend.scratch.debug_transcript.DEFAULT_LOG_PATH", str(log_file)), \
         patch("sys.argv", ["prog", "--start", "0", "--end", "1"]):
        main()
    
    captured = capsys.readouterr()
    assert "=== Line 0 ===" in captured.out
    assert "source=user type=input status=done" in captured.out


def test_format_transcript_data_recursion_error():
    # tool_calls が極端に深いネスト、または循環参照を持つ場合に RecursionError (あるいは他のエラー) を引き起こし、
    # 文字列へのフォールバックが正しく行われることをテスト
    recursive_dict = {}
    recursive_dict["self"] = recursive_dict
    
    data = {
        "source": "user",
        "type": "input",
        "status": "done",
        "tool_calls": recursive_dict
    }
    
    formatted = format_transcript_data(data)
    assert "tool_calls: " in formatted
    # 循環参照オブジェクトの str 表現が含まれていること
    assert "self" in formatted or "..." in formatted or "{}" in formatted or "RecursionError" in formatted


def test_format_transcript_data_empty_dict():
    # 完全に空の辞書を渡した場合に適切に missing フィールドになること
    data = {}
    formatted = format_transcript_data(data)
    assert "source=<missing> type=<missing> status=<missing>" in formatted
    assert "content" not in formatted
    assert "tool_calls" not in formatted


def test_print_transcript_range_large_end(tmp_path, capsys):
    # end インデックスが総行数より大幅に大きい場合に、適切に総行数まで出力されること
    log_file = tmp_path / "test_log.jsonl"
    log_file.write_text('{"source": "user", "type": "input", "status": "done"}\n', encoding="utf-8")
    
    print_transcript_range(str(log_file), start=0, end=9999)
    captured = capsys.readouterr()
    assert "=== Line 0 ===" in captured.out
    assert "=== Line 1 ===" not in captured.out


def test_read_transcript_lines_invalid_types():
    # 引数として None や 数値 が渡された場合に、クラッシュせず空リストが返ること
    assert read_transcript_lines(None) == []
    assert read_transcript_lines(12345) == []  # type: ignore
    assert read_transcript_lines([]) == []  # type: ignore


def test_read_transcript_lines_empty_string():
    # 引数として空文字列が渡された場合に、クラッシュせず空リストが返ること
    assert read_transcript_lines("") == []


def test_print_transcript_range_empty_string_path(capsys):
    # 引数として空文字列が渡された場合に、Log file not found エラーが出力されること
    print_transcript_range("", start=0, end=5)
    captured = capsys.readouterr()
    assert "Error: Log file not found" in captured.out


def test_main_invalid_arguments():
    # 無効な引数が指定された場合に SystemExit が発生すること
    with patch("sys.argv", ["prog", "--start", "abc"]):
        with pytest.raises(SystemExit):
            main()


def test_format_transcript_data_content_truncation():
    # content が400文字を超える場合に正しく切り詰められること
    long_content = "A" * 500
    data = {
        "source": "user",
        "type": "input",
        "status": "done",
        "content": long_content,
    }
    formatted = format_transcript_data(data)
    expected_content_line = f"content: {'A' * 400}"
    assert expected_content_line in formatted
    assert f"content: {'A' * 401}" not in formatted


def test_format_transcript_data_tool_calls_truncation():
    # tool_calls が400文字を超える場合に正しく切り詰められること
    large_tool_calls = [{"name": "tool", "args": {"value": "B" * 500}}]
    data = {
        "source": "user",
        "type": "input",
        "status": "done",
        "tool_calls": large_tool_calls,
    }
    formatted = format_transcript_data(data)
    dumped = json.dumps(large_tool_calls)
    expected_tool_calls_line = f"tool_calls: {dumped[:400]}"
    assert expected_tool_calls_line in formatted
    assert f"tool_calls: {dumped[:401]}" not in formatted


def test_print_transcript_range_boundary_equal(tmp_path, capsys):
    # start == end の場合は出力が行われないこと
    log_file = tmp_path / "test_log.jsonl"
    log_file.write_text('{"source": "user", "type": "input", "status": "done"}\n', encoding="utf-8")
    
    print_transcript_range(str(log_file), start=0, end=0)
    captured = capsys.readouterr()
    assert captured.out == ""


def test_print_transcript_range_boundary_start_equals_len(tmp_path, capsys):
    # start がちょうど len(lines) の場合は警告が出力されること
    log_file = tmp_path / "test_log.jsonl"
    log_file.write_text('{"source": "user", "type": "input", "status": "done"}\n', encoding="utf-8")
    
    print_transcript_range(str(log_file), start=1, end=2)
    captured = capsys.readouterr()
    assert "Warning: Start index 1 is out of bounds (total lines: 1)" in captured.out


def test_parse_transcript_line_decode_error_type():
    # 無効な JSON の場合に json.JSONDecodeError が発生すること
    with pytest.raises(json.JSONDecodeError):
        parse_transcript_line("{invalid json}")




