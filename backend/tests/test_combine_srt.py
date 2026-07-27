import pytest
from pathlib import Path
from datetime import timedelta
import sys

# backend ディレクトリを sys.path に追加して combine_srt をインポート可能にする
sys.path.append(str(Path(__file__).parent.parent))

import combine_srt

def test_parse_srt_time():
    # 正常系
    assert combine_srt.parse_srt_time("01:23:45,678") == timedelta(hours=1, minutes=23, seconds=45, milliseconds=678)
    # 極端値
    assert combine_srt.parse_srt_time("00:00:00,000") == timedelta(0)

def test_format_srt_time():
    # 正常系
    td = timedelta(hours=1, minutes=23, seconds=45, milliseconds=678)
    assert combine_srt.format_srt_time(td) == "01:23:45,678"
    
    # ゼロ値
    td_zero = timedelta(0)
    assert combine_srt.format_srt_time(td_zero) == "00:00:00,000"

def test_shift_srt(tmp_path):
    # 正常なSRTフォーマット（UTF-8-SIG）のファイルを作成
    srt_content = (
        "1\n"
        "00:01:00,000 --> 00:01:05,000\n"
        "Hello World\n"
        "\n"
        "2\n"
        "00:02:00,000 --> 00:02:10,000\n"
        "Subtitle Line 1\n"
        "Subtitle Line 2\n"
    )
    file_path = tmp_path / "test.srt"
    file_path.write_text(srt_content, encoding="utf-8-sig")
    
    # 5秒シフト
    entries = combine_srt.shift_srt(file_path, 5)
    
    assert len(entries) == 2
    assert entries[0] == (
        timedelta(minutes=1, seconds=5),
        timedelta(minutes=1, seconds=10),
        "Hello World"
    )
    assert entries[1] == (
        timedelta(minutes=2, seconds=5),
        timedelta(minutes=2, seconds=15),
        "Subtitle Line 1\nSubtitle Line 2"
    )

def test_shift_srt_edge_cases(tmp_path):
    # 異常系・境界値：ブロックの行数が3行未満、またはタイムスタンプが正規表現にマッチしない
    srt_content = (
        "1\n"
        "00:01:00,000 --> 00:01:05,000\n"
        "Hello World\n"
        "\n"
        "Invalid Block\n"  # 3行未満のブロック
        "\n"
        "2\n"
        "invalid time format here\n"  # タイムスタンプがマッチしないブロック
        "Skipped Subtitle\n"
    )
    file_path = tmp_path / "test_edge.srt"
    file_path.write_text(srt_content, encoding="utf-8-sig")
    
    entries = combine_srt.shift_srt(file_path, 0)
    assert len(entries) == 1
    assert entries[0][2] == "Hello World"

def test_write_combined_srt(tmp_path):
    # ソート順がバラバラのエントリー
    all_entries = [
        (timedelta(seconds=20), timedelta(seconds=25), "Second"),
        (timedelta(seconds=10), timedelta(seconds=15), "First"),
    ]
    output_path = tmp_path / "output.srt"
    combine_srt.write_combined_srt(all_entries, output_path)
    
    content = output_path.read_text(encoding="utf-8")
    expected = (
        "1\n"
        "00:00:10,000 --> 00:00:15,000\n"
        "First\n\n"
        "2\n"
        "00:00:20,000 --> 00:00:25,000\n"
        "Second\n\n"
    )
    assert content == expected

def test_main_all_files_exist(monkeypatch, tmp_path):
    mock_base = tmp_path / "raw_videos" / "AI Studio アップロード用動画"
    mock_base.mkdir(parents=True)
    mock_output = tmp_path / "soul_narrative_combined.srt"
    
    # 各シーン用のダミーSRTファイルを用意
    dummy_srt = (
        "1\n"
        "00:00:10,000 --> 00:00:15,000\n"
        "Test Subtitle\n"
    )
    (mock_base / "シーン01_前編_whisper_semantic.srt").write_text(dummy_srt, encoding="utf-8-sig")
    (mock_base / "シーン03_後編01_whisper_semantic.srt").write_text(dummy_srt, encoding="utf-8-sig")
    (mock_base / "シーン04_後編02_whisper_semantic.srt").write_text(dummy_srt, encoding="utf-8-sig")
    
    # Path クラスの差し替えモック
    def mock_path(*args):
        if not args:
            return Path()
        path_str = str(args[0])
        if path_str == r"C:\Users\PC_User\Desktop\script\video-automation\raw_videos\AI Studio アップロード用動画":
            return mock_base
        elif path_str == r"C:\Users\PC_User\Desktop\script\video-automation\soul_narrative_combined.srt":
            return mock_output
        return Path(*args)
        
    monkeypatch.setattr(combine_srt, "Path", mock_path)
    
    # 実行
    combine_srt.main()
    
    assert mock_output.exists()
    content = mock_output.read_text(encoding="utf-8")
    assert "Test Subtitle" in content

def test_main_no_files_exist(monkeypatch, tmp_path):
    mock_base = tmp_path / "raw_videos" / "AI Studio アップロード用動画"
    mock_base.mkdir(parents=True)
    mock_output = tmp_path / "soul_narrative_combined.srt"
    
    # ファイルを置かずに Path をモック
    def mock_path(*args):
        if not args:
            return Path()
        path_str = str(args[0])
        if path_str == r"C:\Users\PC_User\Desktop\script\video-automation\raw_videos\AI Studio アップロード用動画":
            return mock_base
        elif path_str == r"C:\Users\PC_User\Desktop\script\video-automation\soul_narrative_combined.srt":
            return mock_output
        return Path(*args)
        
    monkeypatch.setattr(combine_srt, "Path", mock_path)
    
    # 実行
    combine_srt.main()
    
    assert mock_output.exists()
    content = mock_output.read_text(encoding="utf-8")
    # 読み込み対象がないため、空ファイルが出力されるはず
    assert content == ""

def test_main_as_script(tmp_path):
    import runpy
    from unittest.mock import patch
    mock_base = tmp_path / "raw_videos" / "AI Studio アップロード用動画"
    mock_base.mkdir(parents=True)
    mock_output = tmp_path / "soul_narrative_combined.srt"
    
    def mock_path(*args):
        if not args:
            return Path()
        path_str = str(args[0])
        if path_str == r"C:\Users\PC_User\Desktop\script\video-automation\raw_videos\AI Studio アップロード用動画":
            return mock_base
        elif path_str == r"C:\Users\PC_User\Desktop\script\video-automation\soul_narrative_combined.srt":
            return mock_output
        return Path(*args)
        
    # 実行スクリプトのパスを取得して __main__ として実行
    script_path = str(Path(combine_srt.__file__).resolve())
    with patch("pathlib.Path", side_effect=mock_path):
        runpy.run_path(script_path, run_name="__main__")
    
    assert mock_output.exists()

def test_shift_srt_crlf(tmp_path):
    # CRLF (\r\n) の改行コードを持つSRTファイルを作成
    srt_content = (
        "1\r\n"
        "00:01:00,000 --> 00:01:05,000\r\n"
        "Hello World\r\n"
        "\r\n"
        "2\r\n"
        "00:02:00,000 --> 00:02:10,000\r\n"
        "Subtitle Line 1\r\n"
        "Subtitle Line 2\r\n"
    )
    file_path = tmp_path / "test_crlf.srt"
    file_path.write_bytes(srt_content.encode("utf-8-sig"))
    
    entries = combine_srt.shift_srt(file_path, 5)
    
    assert len(entries) == 2
    assert entries[0] == (
        timedelta(minutes=1, seconds=5),
        timedelta(minutes=1, seconds=10),
        "Hello World"
    )
    assert entries[1] == (
        timedelta(minutes=2, seconds=5),
        timedelta(minutes=2, seconds=15),
        "Subtitle Line 1\nSubtitle Line 2"
    )


def test_parse_srt_time_exceptions():
    # 区切り文字 `:` が足りない
    with pytest.raises(ValueError):
        combine_srt.parse_srt_time("0123:45,678")
    
    # 区切り文字 `,` がない
    with pytest.raises(ValueError):
        combine_srt.parse_srt_time("01:23:45.678")
        
    # 数値以外の文字
    with pytest.raises(ValueError):
        combine_srt.parse_srt_time("aa:bb:cc,ddd")

def test_format_srt_time_negative_and_micro():
    # 負の timedelta
    td_neg = timedelta(seconds=-10)
    with pytest.raises(ValueError) as excinfo:
        combine_srt.format_srt_time(td_neg)
    assert "SRT time cannot be negative" in str(excinfo.value)

    # マイクロ秒の端数処理
    td_micro = timedelta(microseconds=1234)
    assert combine_srt.format_srt_time(td_micro) == "00:00:00,001"

def test_shift_srt_negative_and_empty(tmp_path):
    # 空ファイル
    empty_file = tmp_path / "empty.srt"
    empty_file.write_text("", encoding="utf-8-sig")
    assert combine_srt.shift_srt(empty_file, 5) == []

    # 改行のみ
    nl_file = tmp_path / "nl.srt"
    nl_file.write_text("\n\n\n", encoding="utf-8-sig")
    assert combine_srt.shift_srt(nl_file, 5) == []

    # 負のシフト
    srt_content = (
        "1\n"
        "00:01:00,000 --> 00:01:05,000\n"
        "Hello World\n"
    )
    file_path = tmp_path / "neg_shift.srt"
    file_path.write_text(srt_content, encoding="utf-8-sig")
    entries = combine_srt.shift_srt(file_path, -10)
    assert len(entries) == 1
    assert entries[0] == (
        timedelta(minutes=1) - timedelta(seconds=10),
        timedelta(minutes=1, seconds=5) - timedelta(seconds=10),
        "Hello World"
    )

def test_write_combined_srt_edge_cases(tmp_path):
    # 空リスト
    output_path = tmp_path / "empty_out.srt"
    combine_srt.write_combined_srt([], output_path)
    assert output_path.exists()
    assert output_path.read_text(encoding="utf-8") == ""

    # 同一開始時間の安定ソート検証
    entries = [
        (timedelta(seconds=10), timedelta(seconds=20), "Second (Orig)"),
        (timedelta(seconds=10), timedelta(seconds=15), "First (Orig)"),
    ]
    output_stable = tmp_path / "stable.srt"
    combine_srt.write_combined_srt(entries, output_stable)
    content = output_stable.read_text(encoding="utf-8")
    expected = (
        "1\n"
        "00:00:10,000 --> 00:00:20,000\n"
        "Second (Orig)\n\n"
        "2\n"
        "00:00:10,000 --> 00:00:15,000\n"
        "First (Orig)\n\n"
    )
    assert content == expected

    # 改行コードが \n (LF) であるかのバイナリ検証
    content_bytes = output_stable.read_bytes()
    assert b"\r\n" not in content_bytes
    assert b"\n" in content_bytes

def test_main_partial_files(monkeypatch, tmp_path):
    mock_base = tmp_path / "raw_videos" / "AI Studio アップロード用動画"
    mock_base.mkdir(parents=True)
    mock_output = tmp_path / "soul_narrative_combined.srt"
    
    dummy_srt = (
        "1\n"
        "00:00:10,000 --> 00:00:15,000\n"
        "Scene Subtitle\n"
    )
    
    # シーン01 と シーン04 は存在するが、シーン03 は存在しない
    (mock_base / "シーン01_前編_whisper_semantic.srt").write_text(dummy_srt, encoding="utf-8-sig")
    (mock_base / "シーン04_後編02_whisper_semantic.srt").write_text(dummy_srt, encoding="utf-8-sig")
    
    def mock_path(*args):
        if not args:
            return Path()
        path_str = str(args[0])
        if path_str == r"C:\Users\PC_User\Desktop\script\video-automation\raw_videos\AI Studio アップロード用動画":
            return mock_base
        elif path_str == r"C:\Users\PC_User\Desktop\script\video-automation\soul_narrative_combined.srt":
            return mock_output
        return Path(*args)
        
    monkeypatch.setattr(combine_srt, "Path", mock_path)
    
    combine_srt.main()
    
    assert mock_output.exists()
    content = mock_output.read_text(encoding="utf-8")
    assert "00:00:10,000 --> 00:00:15,000" in content
    assert "00:38:04,000 --> 00:38:09,000" in content
    assert "Scene Subtitle" in content


def test__parse_and_shift_block():
    # 正常系
    block = (
        "1\n"
        "00:01:00,000 --> 00:01:05,000\n"
        "Hello World\n"
    )
    res = combine_srt._parse_and_shift_block(block, 5)
    assert res == (
        timedelta(minutes=1, seconds=5),
        timedelta(minutes=1, seconds=10),
        "Hello World"
    )

    # 異常系：3行未満
    assert combine_srt._parse_and_shift_block("1\n00:01:00,000 --> 00:01:05,000", 5) is None

    # 異常系：タイムスタンプ形式エラー
    block_invalid = (
        "1\n"
        "invalid_format\n"
        "Hello\n"
    )
    assert combine_srt._parse_and_shift_block(block_invalid, 5) is None


def test_shift_srt_negative_clip(tmp_path, capsys):
    # -70秒シフトして負になるケース
    srt_content = (
        "1\n"
        "00:01:00,000 --> 00:01:05,000\n"
        "Hello World\n"
    )
    file_path = tmp_path / "neg_clip.srt"
    file_path.write_text(srt_content, encoding="utf-8-sig")
    entries = combine_srt.shift_srt(file_path, -70)
    
    assert len(entries) == 1
    # 開始時間、終了時間ともに 0秒 にクリップされるはず
    assert entries[0] == (
        timedelta(0),
        timedelta(0),
        "Hello World"
    )
    captured = capsys.readouterr()
    assert "Warning: Shifting by -70s resulted in negative time" in captured.err


def test__parse_and_shift_block_warnings(capsys):
    # 3行未満のブロック
    combine_srt._parse_and_shift_block("1\n00:01:00,000 --> 00:01:05,000", 5)
    captured = capsys.readouterr()
    assert "Warning: Invalid SRT block" in captured.err

    # タイムスタンプフォーマットエラー
    block_invalid = "1\ninvalid_format\nHello\n"
    combine_srt._parse_and_shift_block(block_invalid, 5)
    captured = capsys.readouterr()
    assert "Warning: Invalid SRT time format in line 1" in captured.err


def test_write_combined_srt_creates_directory(tmp_path):
    # 存在しないサブディレクトリパスを指定
    nested_dir = tmp_path / "nested" / "sub"
    output_path = nested_dir / "output.srt"
    
    entries = [(timedelta(seconds=10), timedelta(seconds=15), "Nested Hello")]
    combine_srt.write_combined_srt(entries, output_path)
    
    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8")
    assert "Nested Hello" in content


def test_main_value_error_exit(monkeypatch, tmp_path):
    mock_base = tmp_path / "raw_videos" / "AI Studio アップロード用動画"
    mock_base.mkdir(parents=True)
    
    # ファイルを置いておく
    (mock_base / "シーン01_前編_whisper_semantic.srt").write_text("dummy", encoding="utf-8-sig")
    
    def mock_path(*args):
        if not args:
            return Path()
        path_str = str(args[0])
        if path_str == r"C:\Users\PC_User\Desktop\script\video-automation\raw_videos\AI Studio アップロード用動画":
            return mock_base
        elif path_str == r"C:\Users\PC_User\Desktop\script\video-automation\soul_narrative_combined.srt":
            return tmp_path / "soul_narrative_combined.srt"
        return Path(*args)
        
    monkeypatch.setattr(combine_srt, "Path", mock_path)
    
    # shift_srt が ValueError を投げるようにモックする
    def mock_shift_srt(*args, **kwargs):
        raise ValueError("Mocked parse error")
    monkeypatch.setattr(combine_srt, "shift_srt", mock_shift_srt)
    
    with pytest.raises(SystemExit) as excinfo:
        combine_srt.main()
    assert excinfo.value.code == 1



def test_parse_srt_time_ms_digits():
    # ミリ秒の桁数が3桁以外の場合の解釈テスト
    assert combine_srt.parse_srt_time("01:23:45,5") == timedelta(hours=1, minutes=23, seconds=45, milliseconds=500)
    assert combine_srt.parse_srt_time("01:23:45,50") == timedelta(hours=1, minutes=23, seconds=45, milliseconds=500)
    assert combine_srt.parse_srt_time("01:23:45,1234") == timedelta(hours=1, minutes=23, seconds=45, milliseconds=123)
