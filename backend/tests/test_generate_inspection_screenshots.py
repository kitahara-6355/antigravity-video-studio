import sys
import os
import runpy
from unittest import mock
import pytest
from pathlib import Path

# PYTHONPATHが通っていることを前提に、backendパッケージからインポートします
from backend.generate_inspection_screenshots import get_video_duration, extract_frame, main


@mock.patch("subprocess.run")
def test_get_video_duration_success(mock_run):
    # ffprobeの出力をシミュレート
    mock_stdout = '{"format": {"duration": "123.45"}}'
    mock_run.return_value = mock.Mock(stdout=mock_stdout, returncode=0)

    duration = get_video_duration("dummy_video.mp4")
    assert duration == 123.45
    mock_run.assert_called_once_with(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "dummy_video.mp4"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30
    )



@mock.patch("subprocess.run")
def test_get_video_duration_missing_duration(mock_run):
    # duration情報がない場合、0.0が返ることを確認
    mock_stdout = '{"format": {}}'
    mock_run.return_value = mock.Mock(stdout=mock_stdout, returncode=0)
    
    duration = get_video_duration("dummy_video.mp4")
    assert duration == 0.0


@mock.patch("subprocess.run")
@mock.patch("backend.generate_inspection_screenshots.Path.exists")
def test_extract_frame_success(mock_exists, mock_run):
    mock_exists.return_value = True
    mock_run.return_value = mock.Mock(returncode=0)
    
    result = extract_frame("dummy_video.mp4", 10.0, "dummy_frame.jpg")
    
    assert result is True
    mock_run.assert_called_once_with(
        ["ffmpeg", "-y", "-ss", "10.0", "-i", "dummy_video.mp4",
         "-frames:v", "1", "-q:v", "2", "dummy_frame.jpg"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30
    )


@mock.patch("subprocess.run")
@mock.patch("backend.generate_inspection_screenshots.Path.exists")
def test_extract_frame_failure(mock_exists, mock_run):
    mock_exists.return_value = False
    mock_run.return_value = mock.Mock(returncode=0)
    
    result = extract_frame("dummy_video.mp4", 10.0, "dummy_frame.jpg")
    
    assert result is False


@mock.patch("glob.glob")
def test_main_no_previews(mock_glob):
    mock_glob.return_value = []
    
    with mock.patch("sys.argv", ["generate_inspection_screenshots.py"]):
        with pytest.raises(SystemExit) as excinfo:
            main()
    
    assert excinfo.value.code == 1


@mock.patch("glob.glob")
@mock.patch("backend.generate_inspection_screenshots.get_video_duration")
@mock.patch("backend.generate_inspection_screenshots.extract_frame")
@mock.patch("backend.generate_inspection_screenshots.Path.mkdir")
@mock.patch("builtins.open", new_callable=mock.mock_open)
@mock.patch("json.dump")
def test_main_success(mock_json_dump, mock_open, mock_mkdir, mock_extract, mock_duration, mock_glob):
    mock_glob.return_value = ["/dummy/preview_001.mp4"]
    mock_duration.return_value = 35.0  # 10秒ごと: 0.0, 10.0, 20.0, 30.0 秒の4枚
    mock_extract.return_value = True

    with mock.patch("sys.argv", ["generate_inspection_screenshots.py"]):
        output_dir, generated = main()
    
    assert output_dir.endswith(os.path.join("artifacts", "inspection_screenshots"))
    assert len(generated) == 4
    assert generated[0][0] == 0.0
    assert generated[1][0] == 10.0
    assert generated[2][0] == 20.0
    assert generated[3][0] == 30.0

    mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
    assert mock_extract.call_count == 4
    mock_open.assert_called_once_with(
        os.path.join(output_dir, "index.json"), "w", encoding="utf-8"
    )


@mock.patch("glob.glob")
@mock.patch("backend.generate_inspection_screenshots.get_video_duration")
@mock.patch("backend.generate_inspection_screenshots.extract_frame")
@mock.patch("backend.generate_inspection_screenshots.Path.mkdir")
@mock.patch("builtins.open", new_callable=mock.mock_open)
@mock.patch("json.dump")
def test_main_many_frames(mock_json_dump, mock_open, mock_mkdir, mock_extract, mock_duration, mock_glob):
    mock_glob.return_value = ["/dummy/preview_001.mp4"]
    # duration が 210.0 の場合、t < 210.0 でループするため、t = 0, 10, ..., 200 の 21 枚になります。
    mock_duration.return_value = 210.0
    mock_extract.return_value = True

    with mock.patch("sys.argv", ["generate_inspection_screenshots.py"]):
        output_dir, generated = main()
    
    assert len(generated) == 21
    assert mock_extract.call_count == 21


@mock.patch("glob.glob")
@mock.patch("subprocess.run")
@mock.patch("backend.generate_inspection_screenshots.Path.mkdir")
@mock.patch("builtins.open", new_callable=mock.mock_open)
@mock.patch("json.dump")
@mock.patch("backend.generate_inspection_screenshots.Path.exists")
def test_script_execution(mock_exists, mock_json_dump, mock_open, mock_mkdir, mock_run, mock_glob):
    mock_glob.return_value = ["/dummy/preview_001.mp4"]
    mock_exists.return_value = True
    
    # ffprobe (duration=15.0) と ffmpeg (2回実行) のレスポンスをシミュレート
    mock_ffprobe_res = mock.Mock(stdout='{"format": {"duration": "15.0"}}', returncode=0)
    mock_ffmpeg_res = mock.Mock(returncode=0)
    mock_run.side_effect = [mock_ffprobe_res, mock_ffmpeg_res, mock_ffmpeg_res]

    # runpy.run_path を用いて __main__ ルートの実行をカバーします
    script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "generate_inspection_screenshots.py"))
    with mock.patch("sys.argv", ["generate_inspection_screenshots.py"]):
        run_globals = runpy.run_path(script_path, run_name="__main__")
    assert "main" in run_globals


# --- 追加テストケース (カバレッジ向上用) ---
from backend.generate_inspection_screenshots import resolve_paths, save_index
import subprocess

@mock.patch("subprocess.run")
def test_get_video_duration_exception(mock_run):
    mock_run.side_effect = FileNotFoundError("dummy error")
    duration = get_video_duration("dummy_video.mp4")
    assert duration == 0.0


@mock.patch("subprocess.run")
def test_get_video_duration_json_error(mock_run):
    mock_run.return_value = mock.Mock(stdout="invalid json", returncode=0)
    duration = get_video_duration("dummy_video.mp4")
    assert duration == 0.0


@mock.patch("subprocess.run")
def test_extract_frame_ffmpeg_failure(mock_run):
    mock_run.return_value = mock.Mock(returncode=1, stderr="ffmpeg dummy error")
    result = extract_frame("dummy_video.mp4", 10.0, "dummy_frame.jpg")
    assert result is False


@mock.patch("subprocess.run")
def test_extract_frame_exception(mock_run):
    mock_run.side_effect = subprocess.SubprocessError("dummy subprocess error")
    result = extract_frame("dummy_video.mp4", 10.0, "dummy_frame.jpg")
    assert result is False


@mock.patch("backend.generate_inspection_screenshots.os.path.exists")
def test_resolve_paths_with_args(mock_exists):
    mock_exists.return_value = True
    args = ["generate_inspection_screenshots.py", "test_video.mp4", "test_output_dir"]
    video_path, output_dir = resolve_paths(args)
    assert video_path == "test_video.mp4"
    assert output_dir == "test_output_dir"


@mock.patch("backend.generate_inspection_screenshots.get_video_duration")
@mock.patch("backend.generate_inspection_screenshots.extract_frame")
@mock.patch("backend.generate_inspection_screenshots.Path.mkdir")
@mock.patch("builtins.open", new_callable=mock.mock_open)
@mock.patch("json.dump")
@mock.patch("backend.generate_inspection_screenshots.os.path.exists")
def test_main_with_arguments(mock_exists, mock_json_dump, mock_open, mock_mkdir, mock_extract, mock_duration):
    mock_exists.return_value = True
    mock_duration.return_value = 15.0
    mock_extract.return_value = True

    with mock.patch("sys.argv", ["generate_inspection_screenshots.py", "arg_video.mp4", "arg_output_dir"]):
        output_dir, generated = main()
    
    assert output_dir == "arg_output_dir"


@mock.patch("builtins.open")
def test_save_index_io_error(mock_open):
    mock_open.side_effect = IOError("dummy permission error")
    save_index("dummy_dir", "dummy_video.mp4", 10.0, [])


@mock.patch("glob.glob")
@mock.patch("backend.generate_inspection_screenshots.get_video_duration")
@mock.patch("backend.generate_inspection_screenshots.extract_frame")
@mock.patch("backend.generate_inspection_screenshots.Path.mkdir")
@mock.patch("builtins.open", new_callable=mock.mock_open)
@mock.patch("json.dump")
def test_main_extract_frame_some_failures(mock_json_dump, mock_open, mock_mkdir, mock_extract, mock_duration, mock_glob):
    mock_glob.return_value = ["/dummy/preview_001.mp4"]
    mock_duration.return_value = 25.0  # 10s interval -> 0.0, 10.0, 20.0 (3 frames)
    # 0.0s は成功、10.0s は失敗、20.0s は成功
    mock_extract.side_effect = [True, False, True]

    with mock.patch("sys.argv", ["generate_inspection_screenshots.py"]):
        output_dir, generated = main()

    # 失敗したフレーム (10.0s) が除外され、成功した2フレームのみになるはず
    assert len(generated) == 2
    assert generated[0][0] == 0.0
    assert generated[1][0] == 20.0
    assert mock_extract.call_count == 3


@mock.patch("glob.glob")
def test_resolve_paths_auto_detect_success(mock_glob):
    mock_glob.return_value = ["/dummy/preview_001.mp4", "/dummy/preview_002.mp4"]
    
    video_path, output_dir = resolve_paths([])
    assert video_path == "/dummy/preview_002.mp4"
    assert "inspection_screenshots" in output_dir


@mock.patch("glob.glob")
def test_resolve_paths_auto_detect_no_previews(mock_glob):
    mock_glob.return_value = []
    
    with pytest.raises(FileNotFoundError) as excinfo:
        resolve_paths([])
    assert "プレビュー動画が見つかりません" in str(excinfo.value)


@mock.patch("glob.glob")
@mock.patch("backend.generate_inspection_screenshots.get_video_duration")
@mock.patch("backend.generate_inspection_screenshots.Path.mkdir")
def test_main_resolve_paths_failure(mock_mkdir, mock_duration, mock_glob):
    mock_glob.return_value = []
    with mock.patch("sys.argv", ["generate_inspection_screenshots.py"]):
        with pytest.raises(SystemExit) as excinfo:
            main()
    assert excinfo.value.code == 1


@mock.patch("glob.glob")
@mock.patch("backend.generate_inspection_screenshots.get_video_duration")
@mock.patch("backend.generate_inspection_screenshots.Path.mkdir")
def test_main_mkdir_failure(mock_mkdir, mock_duration, mock_glob):
    mock_glob.return_value = ["/dummy/preview_001.mp4"]
    mock_mkdir.side_effect = OSError("permission denied")
    with mock.patch("sys.argv", ["generate_inspection_screenshots.py"]):
        with pytest.raises(SystemExit) as excinfo:
            main()
    assert excinfo.value.code == 1


@mock.patch("glob.glob")
@mock.patch("backend.generate_inspection_screenshots.get_video_duration")
@mock.patch("backend.generate_inspection_screenshots.Path.mkdir")
def test_main_invalid_duration(mock_mkdir, mock_duration, mock_glob):
    mock_glob.return_value = ["/dummy/preview_001.mp4"]
    mock_duration.return_value = 0.0
    with mock.patch("sys.argv", ["generate_inspection_screenshots.py"]):
        with pytest.raises(SystemExit) as excinfo:
            main()
    assert excinfo.value.code == 1


@mock.patch("subprocess.run")
def test_get_video_duration_format_malformed(mock_run):
    mock_run.return_value = mock.Mock(stdout='{"format": "not_a_dict"}', returncode=0)
    assert get_video_duration("dummy_video.mp4") == 0.0

    mock_run.return_value = mock.Mock(stdout='{}', returncode=0)
    assert get_video_duration("dummy_video.mp4") == 0.0


def test_resolve_paths_nonexistent_video():
    args = ["generate_inspection_screenshots.py", "nonexistent_video.mp4", "test_output_dir"]
    with pytest.raises(FileNotFoundError) as excinfo:
        resolve_paths(args)
    assert "指定された動画ファイルが見つかりません" in str(excinfo.value)


@mock.patch("subprocess.run")
def test_get_video_duration_ffprobe_not_found(mock_run, capsys):
    mock_run.side_effect = FileNotFoundError("ffprobe not found")
    duration = get_video_duration("dummy_video.mp4")
    assert duration == 0.0
    captured = capsys.readouterr()
    assert "ffprobe コマンドが見つかりません" in captured.out


@mock.patch("subprocess.run")
def test_extract_frame_ffmpeg_not_found(mock_run, capsys):
    mock_run.side_effect = FileNotFoundError("ffmpeg not found")
    result = extract_frame("dummy_video.mp4", 10.0, "dummy_frame.jpg")
    assert result is False
    captured = capsys.readouterr()
    assert "ffmpeg コマンドが見つかりません" in captured.out


@mock.patch("json.dumps")
def test_save_index_serialize_error(mock_dumps, capsys):
    mock_dumps.side_effect = TypeError("serialize error")
    save_index("dummy_dir", "dummy_video.mp4", 10.0, [("timestamp", "file")])
    captured = capsys.readouterr()
    assert "インデックスデータのJSONシリアライズに失敗しました" in captured.out


@mock.patch("subprocess.run")
def test_get_video_duration_value_error(mock_run, capsys):
    mock_run.side_effect = ValueError("decode error")
    duration = get_video_duration("dummy_video.mp4")
    assert duration == 0.0
    captured = capsys.readouterr()
    assert "ffprobe 実行中にエラーが発生しました" in captured.out


@mock.patch("subprocess.run")
def test_extract_frame_value_error(mock_run, capsys):
    mock_run.side_effect = ValueError("decode error")
    result = extract_frame("dummy_video.mp4", 10.0, "dummy_frame.jpg")
    assert result is False
    captured = capsys.readouterr()
    assert "ffmpeg 実行中にエラーが発生しました" in captured.out


@mock.patch("backend.generate_inspection_screenshots.os.path.exists")
@mock.patch("backend.generate_inspection_screenshots.os.path.isdir")
def test_resolve_paths_directory_error(mock_isdir, mock_exists):
    mock_exists.return_value = True
    mock_isdir.return_value = True
    args = ["generate_inspection_screenshots.py", "test_directory", "test_output_dir"]
    with pytest.raises(ValueError) as excinfo:
        resolve_paths(args)
    assert "指定されたパスはファイルではなくディレクトリです" in str(excinfo.value)


@mock.patch("backend.generate_inspection_screenshots.resolve_paths")
def test_main_value_error_handling(mock_resolve):
    mock_resolve.side_effect = ValueError("dummy value error")
    with mock.patch("sys.argv", ["generate_inspection_screenshots.py"]):
        with pytest.raises(SystemExit) as excinfo:
            main()
    assert excinfo.value.code == 1


@mock.patch("glob.glob")
@mock.patch("backend.generate_inspection_screenshots.get_video_duration")
@mock.patch("backend.generate_inspection_screenshots.extract_frame")
@mock.patch("backend.generate_inspection_screenshots.Path.mkdir")
def test_main_all_frames_failed(mock_mkdir, mock_extract, mock_duration, mock_glob):
    mock_glob.return_value = ["/dummy/preview_001.mp4"]
    mock_duration.return_value = 15.0
    mock_extract.return_value = False  # すべて失敗

    with mock.patch("sys.argv", ["generate_inspection_screenshots.py"]):
        with pytest.raises(SystemExit) as excinfo:
            main()
    assert excinfo.value.code == 1


# --- タイムアウトや不正引数などの新規テスト ---
@mock.patch("subprocess.run")
def test_get_video_duration_timeout(mock_run, capsys):
    mock_run.side_effect = subprocess.TimeoutExpired(["ffprobe"], 30)
    duration = get_video_duration("dummy_video.mp4")
    assert duration == 0.0
    captured = capsys.readouterr()
    assert "ffprobe の実行がタイムアウト" in captured.out


def test_get_video_duration_empty_path(capsys):
    duration = get_video_duration("")
    assert duration == 0.0
    captured = capsys.readouterr()
    assert "動画ファイルパスが空です" in captured.out


@mock.patch("subprocess.run")
def test_extract_frame_timeout(mock_run, capsys):
    mock_run.side_effect = subprocess.TimeoutExpired(["ffmpeg"], 30)
    result = extract_frame("dummy_video.mp4", 10.0, "dummy_frame.jpg")
    assert result is False
    captured = capsys.readouterr()
    assert "ffmpeg の実行がタイムアウト" in captured.out


def test_extract_frame_negative_timestamp(capsys):
    result = extract_frame("dummy_video.mp4", -1.0, "dummy_frame.jpg")
    assert result is False
    captured = capsys.readouterr()
    assert "無効なタイムスタンプが指定されました" in captured.out


@mock.patch("backend.generate_inspection_screenshots.os.path.exists")
def test_resolve_paths_two_args(mock_exists):
    mock_exists.return_value = True
    args = ["generate_inspection_screenshots.py", "test_video.mp4"]
    video_path, output_dir = resolve_paths(args)
    assert video_path == "test_video.mp4"
    assert "inspection_screenshots" in output_dir


def test_resolve_paths_invalid_types():
    with pytest.raises(TypeError):
        resolve_paths(["generate_inspection_screenshots.py", 123])
    with mock.patch("backend.generate_inspection_screenshots.os.path.exists", return_value=True):
        with pytest.raises(TypeError):
            resolve_paths(["generate_inspection_screenshots.py", "video.mp4", 123])


@mock.patch("subprocess.run")
def test_get_video_duration_returncode_error(mock_run, capsys):
    mock_run.return_value = mock.Mock(returncode=1, stderr="ffprobe error details")
    duration = get_video_duration("dummy_video.mp4")
    assert duration == 0.0
    captured = capsys.readouterr()
    assert "ffprobe 失敗" in captured.out


@mock.patch("subprocess.run")
def test_get_video_duration_float_conversion_error(mock_run, capsys):
    mock_stdout = '{"format": {"duration": "invalid_float"}}'
    mock_run.return_value = mock.Mock(stdout=mock_stdout, returncode=0)
    duration = get_video_duration("dummy_video.mp4")
    assert duration == 0.0
    captured = capsys.readouterr()
    assert "duration の数値変換に失敗しました" in captured.out


@mock.patch("subprocess.run")
@mock.patch("backend.generate_inspection_screenshots.Path.exists")
def test_extract_frame_exists_os_error(mock_exists, mock_run, capsys):
    mock_exists.side_effect = OSError("Disk error")
    mock_run.return_value = mock.Mock(returncode=0)
    result = extract_frame("dummy_video.mp4", 10.0, "dummy_frame.jpg")
    assert result is False
    captured = capsys.readouterr()
    assert "出力ファイルの存在確認に失敗しました" in captured.out


@mock.patch("subprocess.run")
def test_get_video_duration_permission_error(mock_run, capsys):
    mock_run.side_effect = PermissionError("Permission denied")
    duration = get_video_duration("dummy_video.mp4")
    assert duration == 0.0
    captured = capsys.readouterr()
    assert "ffprobe コマンドの実行権限がありません" in captured.out


@mock.patch("subprocess.run")
def test_get_video_duration_negative(mock_run, capsys):
    mock_stdout = '{"format": {"duration": "-10.0"}}'
    mock_run.return_value = mock.Mock(stdout=mock_stdout, returncode=0)
    duration = get_video_duration("dummy_video.mp4")
    assert duration == 0.0
    captured = capsys.readouterr()
    assert "duration が負の値です" in captured.out


@mock.patch("subprocess.run")
def test_extract_frame_permission_error(mock_run, capsys):
    mock_run.side_effect = PermissionError("Permission denied")
    result = extract_frame("dummy_video.mp4", 10.0, "dummy_frame.jpg")
    assert result is False
    captured = capsys.readouterr()
    assert "ffmpeg コマンドの実行権限がありません" in captured.out


def test_generate_timestamps_invalid_interval():
    from backend.generate_inspection_screenshots import generate_timestamps
    with pytest.raises(ValueError) as excinfo:
        generate_timestamps(100.0, interval=0)
    assert "interval は 0 より大きい値である必要があります" in str(excinfo.value)

    with pytest.raises(ValueError) as excinfo:
        generate_timestamps(100.0, interval=-5)
    assert "interval は 0 より大きい値である必要があります" in str(excinfo.value)


@mock.patch("backend.generate_inspection_screenshots.resolve_paths")
def test_main_type_error_handling(mock_resolve):
    mock_resolve.side_effect = TypeError("dummy type error")
    with mock.patch("sys.argv", ["generate_inspection_screenshots.py"]):
        with pytest.raises(SystemExit) as excinfo:
            main()
    assert excinfo.value.code == 1


@mock.patch("glob.glob")
@mock.patch("backend.generate_inspection_screenshots.get_video_duration")
@mock.patch("backend.generate_inspection_screenshots.extract_frame")
@mock.patch("backend.generate_inspection_screenshots.Path.mkdir")
@mock.patch("backend.generate_inspection_screenshots.save_index")
def test_main_save_index_failure(mock_save, mock_mkdir, mock_extract, mock_duration, mock_glob, capsys):
    mock_glob.return_value = ["/dummy/preview_001.mp4"]
    mock_duration.return_value = 15.0
    mock_extract.return_value = True
    mock_save.return_value = False  # 保存失敗

    with mock.patch("sys.argv", ["generate_inspection_screenshots.py"]):
        with pytest.raises(SystemExit) as excinfo:
            main()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "インデックスJSONの保存に失敗しました" in captured.out


def test_save_index_invalid_frames(capsys):
    # Noneが渡された場合や、型が異なる場合
    res1 = save_index("dummy_dir", "dummy_video.mp4", 10.0, None)
    assert res1 is False
    captured = capsys.readouterr()
    assert "生成されたフレームのリストが無効です" in captured.out

    res2 = save_index("dummy_dir", "dummy_video.mp4", 10.0, [("timestamp",)])  # タプルの要素数が足りない
    assert res2 is False
    captured = capsys.readouterr()
    assert "インデックスデータのJSONシリアライズに失敗しました" in captured.out


def test_get_video_duration_type_error(capsys):
    # パスにNoneや非文字列を渡してTypeErrorが発生するケース
    duration = get_video_duration(None)
    assert duration == 0.0
    duration2 = get_video_duration(12345)
    assert duration2 == 0.0


def test_extract_frame_type_error(capsys):
    # タイムスタンプやパスに不正な型を渡してTypeErrorが発生するケース
    res = extract_frame(None, 10.0, "output.jpg")
    assert res is False
    res2 = extract_frame("video.mp4", "invalid_timestamp", "output.jpg")
    assert res2 is False


def test_resolve_paths_invalid_args_type():
    from backend.generate_inspection_screenshots import resolve_paths
    with pytest.raises(TypeError):
        resolve_paths(12345)
    with pytest.raises(TypeError):
        resolve_paths({"arg": "val"})


def test_generate_timestamps_invalid_duration_type():
    from backend.generate_inspection_screenshots import generate_timestamps
    with pytest.raises(TypeError) as excinfo:
        generate_timestamps("invalid_duration", interval=10)
    assert "duration は数値である必要があります" in str(excinfo.value)

    with pytest.raises(TypeError) as excinfo:
        generate_timestamps(None, interval=10)
    assert "duration は数値である必要があります" in str(excinfo.value)


def test_generate_timestamps_invalid_interval_type():
    from backend.generate_inspection_screenshots import generate_timestamps
    with pytest.raises(TypeError) as excinfo:
        generate_timestamps(100.0, interval="invalid_interval")
    assert "interval は数値である必要があります" in str(excinfo.value)

    with pytest.raises(TypeError) as excinfo:
        generate_timestamps(100.0, interval=None)
    assert "interval は数値である必要があります" in str(excinfo.value)


@mock.patch("glob.glob")
@mock.patch("backend.generate_inspection_screenshots.get_video_duration")
@mock.patch("backend.generate_inspection_screenshots.Path.mkdir")
def test_main_invalid_duration_type_handling(mock_mkdir, mock_duration, mock_glob):
    mock_glob.return_value = ["/dummy/preview_001.mp4"]
    mock_duration.return_value = "invalid_duration"  # generate_timestamps で TypeError を発生させる
    with mock.patch("sys.argv", ["generate_inspection_screenshots.py"]):
        with pytest.raises(SystemExit) as excinfo:
            main()
    assert excinfo.value.code == 1


def test_generate_timestamps_inf_nan():
    from backend.generate_inspection_screenshots import generate_timestamps
    with pytest.raises(ValueError) as excinfo:
        generate_timestamps(float('inf'), interval=10)
    assert "duration" in str(excinfo.value)
    
    with pytest.raises(ValueError) as excinfo:
        generate_timestamps(100, interval=float('inf'))
    assert "interval" in str(excinfo.value)

    with pytest.raises(ValueError) as excinfo:
        generate_timestamps(float('nan'), interval=10)
    assert "duration" in str(excinfo.value)


def test_generate_timestamps_negative_duration():
    from backend.generate_inspection_screenshots import generate_timestamps
    with pytest.raises(ValueError) as excinfo:
        generate_timestamps(-10.0, interval=10)
    assert "duration" in str(excinfo.value)


def test_generate_timestamps_exceed_max_limit():
    from backend.generate_inspection_screenshots import generate_timestamps
    # 20000s / 10s = 2000 frames (exceeds max limit 1000)
    with pytest.raises(ValueError) as excinfo:
        generate_timestamps(20000.0, interval=10)
    assert "最大フレーム数" in str(excinfo.value)


@mock.patch("subprocess.run")
def test_get_video_duration_inf_nan(mock_run):
    mock_run.return_value = mock.Mock(stdout='{"format": {"duration": "inf"}}', returncode=0)
    assert get_video_duration("dummy.mp4") == 0.0

    mock_run.return_value = mock.Mock(stdout='{"format": {"duration": "nan"}}', returncode=0)
    assert get_video_duration("dummy.mp4") == 0.0


@mock.patch("backend.generate_inspection_screenshots.resolve_paths")
def test_main_os_error_handling(mock_resolve, capsys):
    mock_resolve.side_effect = OSError("Disk error")
    with mock.patch("sys.argv", ["generate_inspection_screenshots.py"]):
        with pytest.raises(SystemExit) as excinfo:
            main()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "エラーが発生しました" in captured.out or "失敗しました" in captured.out


def test_generate_timestamps_overflow_error():
    from backend.generate_inspection_screenshots import generate_timestamps
    with pytest.raises(ValueError) as excinfo:
        # 1e300 / 1e-10 -> 1e310 (exceeds float limit, results in inf, causing OverflowError in math.ceil)
        generate_timestamps(1e300, interval=1e-10)
    assert "オーバーフローが発生しました" in str(excinfo.value)


def test_save_index_type_error_on_path(capsys):
    from backend.generate_inspection_screenshots import save_index
    # output_dir が None の場合、TypeError が発生して安全に False を返すはず
    res = save_index(None, "dummy.mp4", 10.0, [("timestamp", "file.jpg")])
    assert res is False
    captured = capsys.readouterr()
    assert "無効な出力ディレクトリまたは動画ファイルパス" in captured.out


def test_extract_frame_type_error_on_output_path(capsys):
    from backend.generate_inspection_screenshots import extract_frame
    # output_path が None の場合、TypeError が発生して安全に False を返すはず
    res = extract_frame("dummy.mp4", 10.0, None)
    assert res is False
    captured = capsys.readouterr()
    assert "無効な動画ファイルパスまたは出力ファイルパス" in captured.out
