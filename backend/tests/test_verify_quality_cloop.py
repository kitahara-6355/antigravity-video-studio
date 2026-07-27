import os
import sys
import json
import pytest
from unittest.mock import patch
from backend.verify_quality_cloop import parse_srt, compare_results

# テスト用の一時ファイルを作成するフィクスチャ
@pytest.fixture
def temp_srt_file(tmp_path):
    def _create_file(content, encoding='utf-8'):
        file_path = tmp_path / "test.srt"
        with open(file_path, "w", encoding=encoding, newline='') as f:
            f.write(content)
        return str(file_path)
    return _create_file

@pytest.fixture
def temp_json_file(tmp_path):
    def _create_file(data):
        file_path = tmp_path / "test.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        return str(file_path)
    return _create_file

def test_parse_srt_normal(temp_srt_file):
    # 通常のSRTパース（発言者名あり・なしの混在）
    srt_content = (
        "1\n"
        "00:00:01,000 --> 00:00:04,000\n"
        "北原：こんにちは、皆さん。\n\n"
        "2\n"
        "00:00:04,000 --> 00:00:08,000\n"
        "本日のテーマは書道です。\n\n"
        "3\n"
        "00:00:08,000 --> 00:00:12,000\n"
        "久喜田：書を通して学びます。\n"
    )
    path = temp_srt_file(srt_content)
    segments = parse_srt(path)
    
    assert len(segments) == 3
    assert segments[0] == "こんにちは、皆さん。"
    assert segments[1] == "本日のテーマは書道です。"
    assert segments[2] == "書を通して学びます。"

def test_parse_srt_crlf(temp_srt_file):
    # 改行コードが CRLF (\r\n) の場合
    srt_content = (
        "1\r\n"
        "00:00:01,000 --> 00:00:04,000\r\n"
        "北原：こんにちは、皆さん。\r\n\r\n"
        "2\r\n"
        "00:00:04,000 --> 00:00:08,000\r\n"
        "久喜田：書を通して学びます。\r\n"
    )
    path = temp_srt_file(srt_content)
    segments = parse_srt(path)
    
    assert len(segments) == 2
    assert segments[0] == "こんにちは、皆さん。"
    assert segments[1] == "書を通して学びます。"

def test_parse_srt_bom(temp_srt_file):
    # BOM付きUTF-8の場合
    srt_content = (
        "1\n"
        "00:00:01,000 --> 00:00:04,000\n"
        "北原：こんにちは。\n"
    )
    path = temp_srt_file(srt_content, encoding='utf-8-sig')
    segments = parse_srt(path)
    
    assert len(segments) == 1
    assert segments[0] == "こんにちは。"

def test_parse_srt_short_block(temp_srt_file):
    # 3行未満の不正なブロックがある場合（スキップされるべき）
    srt_content = (
        "1\n"
        "00:00:01,000 --> 00:00:04,000\n"
        "北原：こんにちは。\n\n"
        "不正なブロック\n"
        "行数が足りない\n\n"
        "2\n"
        "00:00:04,000 --> 00:00:08,000\n"
        "正常なブロック。\n"
    )
    path = temp_srt_file(srt_content)
    segments = parse_srt(path)
    
    assert len(segments) == 2
    assert segments[0] == "こんにちは。"
    assert segments[1] == "正常なブロック。"

def test_compare_results_normal(temp_json_file, temp_srt_file, capsys):
    json_data = [
        {"text": "これは書家の作品です。"},
        {"text": "書を通して表現します。"},
        {"text": "久喜田さんが説明します。"},
        {"text": "その他のテキスト。"}
    ]
    srt_content = (
        "1\n"
        "00:00:01,000 --> 00:00:04,000\n"
        "北原：書家の作品です。\n\n"
        "2\n"
        "00:00:04,000 --> 00:00:08,000\n"
        "久喜田：書を通して表現します。\n"
    )
    
    json_path = temp_json_file(json_data)
    srt_path = temp_srt_file(srt_content)
    
    compare_results(json_path, srt_path)
    
    captured = capsys.readouterr()
    assert "JSONセグメント数: 4" in captured.out
    assert "SRTセグメント数: 2" in captured.out
    assert "FOUND KEYWORD: 書家の (SUCCESS)" in captured.out
    assert "FOUND KEYWORD: 書を通して (SUCCESS)" in captured.out
    assert "FOUND KEYWORD: 久喜田 (SUCCESS)" in captured.out
    assert "検証完了" in captured.out

def test_compare_results_missing_text_key(temp_json_file, temp_srt_file, capsys):
    # JSONデータに text キーが欠けている場合
    json_data = [
        {"not_text": "無視されるべき"},
        {"text": "久喜田さんが登場。"}
    ]
    srt_content = (
        "1\n"
        "00:00:01,000 --> 00:00:04,000\n"
        "北原：こんにちは。\n"
    )
    json_path = temp_json_file(json_data)
    srt_path = temp_srt_file(srt_content)
    
    compare_results(json_path, srt_path)
    
    captured = capsys.readouterr()
    assert "FOUND KEYWORD: 久喜田 (SUCCESS)" in captured.out

def test_main_execution(temp_json_file, temp_srt_file, capsys):
    json_data = [{"text": "テストデータ"}]
    srt_content = (
        "1\n"
        "00:00:01,000 --> 00:00:04,000\n"
        "北原：こんにちは。\n"
    )
    json_path = temp_json_file(json_data)
    srt_path = temp_srt_file(srt_content)
    
    import runpy
    script_path = os.path.join(os.path.dirname(__file__), "..", "verify_quality_cloop.py")
    test_args = ["verify_quality_cloop.py", json_path, srt_path]
    with patch.object(sys, 'argv', test_args):
        runpy.run_path(script_path, run_name="__main__")
        
    captured = capsys.readouterr()
    assert "JSONセグメント数: 1" in captured.out
    assert "SRTセグメント数: 1" in captured.out
    assert "検証完了" in captured.out

# --- 新規追加テスト ---

def test_parse_srt_file_not_found():
    # 存在しないSRTファイル
    with pytest.raises(FileNotFoundError):
        parse_srt("non_existent_file.srt")

def test_compare_results_json_file_not_found(tmp_path):
    # 存在しないJSONファイル
    srt_path = tmp_path / "test.srt"
    srt_path.write_text("1\n00:00:01 --> 00:00:02\n北原：テスト\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        compare_results("non_existent_file.json", str(srt_path))

def test_compare_results_invalid_json(temp_srt_file, tmp_path):
    # 不正なJSON
    srt_path = temp_srt_file("1\n00:00:01 --> 00:00:02\n北原：テスト\n")
    json_path = tmp_path / "invalid.json"
    json_path.write_text("invalid json content", encoding="utf-8")
    with pytest.raises(ValueError, match="JSONのデコードに失敗しました"):
        compare_results(str(json_path), srt_path)

def test_compare_results_non_list_json(temp_srt_file, temp_json_file):
    # リストではないJSON
    srt_path = temp_srt_file("1\n00:00:01 --> 00:00:02\n北原：テスト\n")
    json_path = temp_json_file({"not_a_list": True})
    with pytest.raises(ValueError, match="JSONデータのルートはリスト形式である必要があります"):
        compare_results(json_path, srt_path)

def test_main_execution_missing_arguments(capsys):
    # 引数が足りない場合
    import runpy
    script_path = os.path.join(os.path.dirname(__file__), "..", "verify_quality_cloop.py")
    test_args = ["verify_quality_cloop.py"]
    with patch.object(sys, 'argv', test_args):
        with pytest.raises(SystemExit) as exc_info:
            runpy.run_path(script_path, run_name="__main__")
        assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "使用法: python verify_quality_cloop.py" in captured.err

def test_main_execution_file_not_found_handling(capsys):
    # ファイル不在時のメイン処理のエラーハンドリング
    import runpy
    script_path = os.path.join(os.path.dirname(__file__), "..", "verify_quality_cloop.py")
    test_args = ["verify_quality_cloop.py", "non_existent.json", "non_existent.srt"]
    with patch.object(sys, 'argv', test_args):
        with pytest.raises(SystemExit) as exc_info:
            runpy.run_path(script_path, run_name="__main__")
        assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "エラー: JSONファイルが見つかりません" in captured.err

def test_parse_srt_os_error(temp_srt_file):
    # openでOSErrorが発生する場合
    srt_path = temp_srt_file("1\n00:00:01 --> 00:00:02\n北原：テスト\n")
    with patch("builtins.open", side_effect=OSError("Read error")):
        with pytest.raises(OSError, match="SRTファイルの読み込みに失敗しました"):
            parse_srt(srt_path)

def test_compare_results_json_os_error(temp_json_file, temp_srt_file):
    # openでOSErrorが発生する場合
    json_path = temp_json_file([{"text": "テスト"}])
    srt_path = temp_srt_file("1\n00:00:01 --> 00:00:02\n北原：テスト\n")
    with patch("builtins.open", side_effect=OSError("Read error")):
        with pytest.raises(OSError, match="JSONファイルの読み込みに失敗しました"):
            compare_results(json_path, srt_path)

def test_compare_results_contains_non_dict_element(temp_json_file, temp_srt_file, capsys):
    # JSONリスト内に辞書ではない要素が含まれる場合
    json_data = [
        {"text": "正常データ"},
        "文字列データ",  # dictではないのでスキップされるべき
        {"text": "もう一つの正常データ"}
    ]
    srt_content = (
        "1\n"
        "00:00:01,000 --> 00:00:04,000\n"
        "北原：こんにちは。\n"
    )
    json_path = temp_json_file(json_data)
    srt_path = temp_srt_file(srt_content)
    
    compare_results(json_path, srt_path)
    
    captured = capsys.readouterr()
    assert "JSONセグメント数: 3" in captured.out
    assert "正常データ" in captured.out
    assert "もう一つの正常データ" in captured.out


def test_parse_srt_speaker_regex(temp_srt_file):
    # 話者名置換の境界値テスト
    # 1. 通常の話者名
    srt1 = "1\n00:00:01 --> 00:00:02\n北原：こんにちは\n"
    path1 = temp_srt_file(srt1)
    assert parse_srt(path1)[0] == "こんにちは"

    # 2. 数字を含む話者名（置換されないべき）
    srt2 = "1\n00:00:01 --> 00:00:02\n12：こんにちは\n"
    path2 = temp_srt_file(srt2)
    assert parse_srt(path2)[0] == "12：こんにちは"

    # 3. 複数のコロン（最初の話者名のみ置換されるべき）
    srt3 = "1\n00:00:01 --> 00:00:02\n北原：久喜田：こんにちは\n"
    path3 = temp_srt_file(srt3)
    assert parse_srt(path3)[0] == "久喜田：こんにちは"


def test_parse_srt_multiline_text(temp_srt_file):
    # 字幕テキストの複数行結合テスト
    srt = (
        "1\n"
        "00:00:01,000 --> 00:00:04,000\n"
        "こんにちは\n"
        "世界\n"
        "皆さん\n"
    )
    path = temp_srt_file(srt)
    assert parse_srt(path)[0] == "こんにちは 世界 皆さん"


def test_compare_results_more_than_20_nodes(temp_json_file, temp_srt_file, capsys):
    # JSONデータが20ノードを超える場合
    json_data = [{"text": f"データ_{i}"} for i in range(25)]
    srt_content = "1\n00:00:01 --> 00:00:02\nテスト\n"
    
    json_path = temp_json_file(json_data)
    srt_path = temp_srt_file(srt_content)
    
    compare_results(json_path, srt_path)
    
    captured = capsys.readouterr()
    assert "JSONセグメント数: 25" in captured.out
    # 最初の20ノードは表示される
    assert "[0] データ_0" in captured.out
    assert "[19] データ_19" in captured.out
    # 20ノード目以降は表示されない
    assert "[20] データ_20" not in captured.out


def test_compare_results_empty_json_list(temp_json_file, temp_srt_file, capsys):
    # JSONデータが空リストの場合
    json_path = temp_json_file([])
    srt_path = temp_srt_file("1\n00:00:01 --> 00:00:02\nテスト\n")
    
    compare_results(json_path, srt_path)
    
    captured = capsys.readouterr()
    assert "JSONセグメント数: 0" in captured.out
    assert "検証完了" in captured.out


def test_compare_results_no_matching_keywords(temp_json_file, temp_srt_file, capsys):
    # キーワードがマッチしない場合
    json_data = [{"text": "無関係なテキスト"}]
    srt_path = temp_srt_file("1\n00:00:01 --> 00:00:02\nテスト\n")
    json_path = temp_json_file(json_data)
    
    compare_results(json_path, srt_path)
    
    captured = capsys.readouterr()
    assert "FOUND KEYWORD" not in captured.out
    assert "検証完了" in captured.out

def test_compare_results_null_or_non_string_text(temp_json_file, temp_srt_file, capsys):
    # JSONデータのtextキーの値がNoneや文字列以外の場合
    json_data = [
        {"text": None},
        {"text": 123},
        {"text": "久喜田さんが登場。"}
    ]
    srt_content = "1\n00:00:01 --> 00:00:02\nテスト\n"
    json_path = temp_json_file(json_data)
    srt_path = temp_srt_file(srt_content)
    
    # 修正後はエラーにならず、文字列以外の箇所はスキップされて検証完了することを確認
    compare_results(json_path, srt_path)
    
    captured = capsys.readouterr()
    assert "FOUND KEYWORD: 久喜田 (SUCCESS)" in captured.out
    assert "検証完了" in captured.out


def test_main_direct_missing_args(capsys):
    import sys
    from backend.verify_quality_cloop import main
    test_args = ["verify_quality_cloop.py"]
    with patch.object(sys, 'argv', test_args):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "使用法: python verify_quality_cloop.py" in captured.err


def test_main_direct_success(temp_json_file, temp_srt_file, capsys):
    import sys
    from backend.verify_quality_cloop import main
    json_data = [{"text": "テストデータ"}]
    srt_content = "1\\n00:00:01,000 --> 00:00:04,000\\n北原：こんにちは。\\n"
    json_path = temp_json_file(json_data)
    srt_path = temp_srt_file(srt_content)
    test_args = ["verify_quality_cloop.py", json_path, srt_path]
    with patch.object(sys, 'argv', test_args):
        main()
    captured = capsys.readouterr()
    assert "JSONセグメント数: 1" in captured.out
    assert "検証完了" in captured.out


def test_main_direct_file_not_found(capsys):
    import sys
    from backend.verify_quality_cloop import main
    test_args = ["verify_quality_cloop.py", "non_existent.json", "non_existent.srt"]
    with patch.object(sys, 'argv', test_args):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "エラー: JSONファイルが見つかりません" in captured.err


def test_run_as_main_module(temp_json_file, temp_srt_file, capsys):
    import sys
    import runpy
    json_data = [{"text": "テストデータ"}]
    srt_content = "1\\n00:00:01,000 --> 00:00:04,000\\n北原：こんにちは。\\n"
    json_path = temp_json_file(json_data)
    srt_path = temp_srt_file(srt_content)
    test_args = ["verify_quality_cloop.py", json_path, srt_path]
    
    # 警告を避けるため、一時的に sys.modules から削除する
    sys_modules_backup = sys.modules.get("backend.verify_quality_cloop")
    if "backend.verify_quality_cloop" in sys.modules:
        del sys.modules["backend.verify_quality_cloop"]
        
    try:
        with patch.object(sys, 'argv', test_args):
            runpy.run_module("backend.verify_quality_cloop", run_name="__main__")
    finally:
        if sys_modules_backup is not None:
            sys.modules["backend.verify_quality_cloop"] = sys_modules_backup
            
    captured = capsys.readouterr()
    assert "JSONセグメント数: 1" in captured.out
    assert "検証完了" in captured.out


def test_parse_srt_unicode_decode_error(tmp_path):
    # UTF-8ではないエンコーディング（例えば Shift_JIS）で書き込み、UnicodeDecodeError を発生させる
    srt_path = tmp_path / "shift_jis.srt"
    with open(srt_path, "w", encoding="shift_jis") as f:
        f.write("1\n00:00:01 --> 00:00:02\n日本語テスト\n")
    with pytest.raises(ValueError, match="SRTファイルのエンコーディングが正しくありません"):
        parse_srt(str(srt_path))


def test_compare_results_json_unicode_decode_error(tmp_path, temp_srt_file):
    # UTF-8ではないエンコーディングでJSONを書き込む
    json_path = tmp_path / "shift_jis.json"
    with open(json_path, "w", encoding="shift_jis") as f:
        f.write('{"text": "日本語"}')
    srt_path = temp_srt_file("1\n00:00:01 --> 00:00:02\nテスト\n")
    with pytest.raises(ValueError, match="JSONファイルのエンコーディングが正しくありません"):
        compare_results(str(json_path), srt_path)


def test_main_direct_unexpected_exception(capsys):
    import sys
    from backend.verify_quality_cloop import main
    # compare_results が予期しない例外（TypeError）を投げた場合の main でのキャッチ
    with patch("backend.verify_quality_cloop.compare_results", side_effect=TypeError("Unexpected error")):
        test_args = ["verify_quality_cloop.py", "dummy.json", "dummy.srt"]
        with patch.object(sys, 'argv', test_args):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "予期しないエラー: Unexpected error" in captured.err

def test_main_direct_unexpected_key_error(capsys):
    import sys
    from backend.verify_quality_cloop import main
    # compare_results が KeyError を投げた場合の main でのキャッチ
    with patch("backend.verify_quality_cloop.compare_results", side_effect=KeyError("Key not found")):
        test_args = ["verify_quality_cloop.py", "dummy.json", "dummy.srt"]
        with patch.object(sys, 'argv', test_args):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "予期しないエラー" in captured.err

def test_main_direct_uncaught_runtime_error():
    import sys
    from backend.verify_quality_cloop import main
    # compare_results が RuntimeError を投げた場合、main はキャッチせずそのまま例外をスルーする
    with patch("backend.verify_quality_cloop.compare_results", side_effect=RuntimeError("Fatal system error")):
        test_args = ["verify_quality_cloop.py", "dummy.json", "dummy.srt"]
        with patch.object(sys, 'argv', test_args):
            with pytest.raises(RuntimeError, match="Fatal system error"):
                main()

