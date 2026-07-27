"""
test_whisper_fixed.py — whisper_fixed.py の単体テストおよびカバレッジ向上用テストコード
"""

import sys
import os
import json
import pytest
import io
from pathlib import Path
from unittest.mock import MagicMock, patch
import importlib
import runpy

# io.TextIOWrapper をモック化し、pytest のキャプチャ破損を防ぐ
original_text_io_wrapper = io.TextIOWrapper

def dummy_text_io_wrapper(buffer, encoding=None, errors=None, **kwargs):
    try:
        stdout_buf = getattr(sys.stdout, "buffer", None)
        stderr_buf = getattr(sys.stderr, "buffer", None)
        if stdout_buf is not None and buffer == stdout_buf:
            return sys.stdout
        if stderr_buf is not None and buffer == stderr_buf:
            return sys.stderr
    except Exception:
        pass
    return original_text_io_wrapper(buffer, encoding=encoding, errors=errors, **kwargs)

io.TextIOWrapper = dummy_text_io_wrapper

# backend ディレクトリを sys.path に追加
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# faster_whisper のインポートをモック化
mock_faster_whisper = MagicMock()
mock_whisper_model_class = MagicMock()
mock_faster_whisper.WhisperModel = mock_whisper_model_class
sys.modules['faster_whisper'] = mock_faster_whisper

# whisper_fixed をインポート
import whisper_fixed


def test_transcribe_video_file_not_found(capsys):
    """動画ファイルが存在しない場合のハンドリングをテスト"""
    result = whisper_fixed.transcribe_video("non_existent_file.mp4")
    assert result is None
    
    captured = capsys.readouterr()
    assert "エラー: ファイルが見つかりません" in captured.out


def test_transcribe_video_success_default_dir(tmp_path):
    """正常系動作のテスト (デフォルト出力ディレクトリ)"""
    # ダミー動画ファイルを作成
    video_file = tmp_path / "test_video.mp4"
    video_file.write_bytes(b"\x00" * 100)

    # WhisperModel のモック設定
    mock_model_instance = MagicMock()
    mock_whisper_model_class.return_value = mock_model_instance

    mock_info = MagicMock()
    mock_info.language = "ja"
    mock_info.duration = 10.5

    # 10セグメント未満（例: 2セグメント）を返す
    dummy_segments = []
    for i in range(1, 3):
        seg = MagicMock()
        seg.start = (i - 1) * 2.0
        seg.end = i * 2.0
        seg.text = f" segment {i}"
        dummy_segments.append(seg)

    mock_model_instance.transcribe.return_value = (dummy_segments, mock_info)

    # transcribe_video を呼び出し
    output_path_str = whisper_fixed.transcribe_video(str(video_file), model_size="dummy_model")
    
    # 期待値検証
    expected_output_path = tmp_path / "test_video_whisper.json"
    assert output_path_str == str(expected_output_path)
    assert expected_output_path.exists()

    with open(expected_output_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["video"] == "test_video.mp4"
        assert data["model"] == "dummy_model"
        assert data["language"] == "ja"
        assert data["duration"] == 10.5
        assert data["total_segments"] == 2
        assert len(data["segments"]) == 2
        assert data["segments"][0]["text"] == "segment 1"


def test_transcribe_video_success_with_output_dir_and_progress(tmp_path, capsys):
    """正常系動作のテスト (進捗表示と出力ディレクトリ指定)"""
    # ダミー動画ファイルを作成
    video_file = tmp_path / "test_video_progress.mp4"
    video_file.write_bytes(b"\x00" * 100)

    # 出力ディレクトリを作成
    output_dir = tmp_path / "output_json"
    output_dir.mkdir()

    # WhisperModel のモック設定
    mock_model_instance = MagicMock()
    mock_whisper_model_class.return_value = mock_model_instance

    mock_info = MagicMock()
    mock_info.language = "en"
    mock_info.duration = 60.0

    # 10セグメント以上（例: 11セグメント）を返して進捗表示を発生させる
    dummy_segments = []
    for i in range(1, 12):
        seg = MagicMock()
        seg.start = (i - 1) * 5.0
        seg.end = i * 5.0
        seg.text = f"seg_{i}"
        dummy_segments.append(seg)

    mock_model_instance.transcribe.return_value = (dummy_segments, mock_info)

    # transcribe_video を呼び出し
    output_path_str = whisper_fixed.transcribe_video(
        str(video_file), 
        model_size="dummy_model_large", 
        output_dir=str(output_dir)
    )

    # 期待値検証
    expected_output_path = output_dir / "test_video_progress_whisper.json"
    assert output_path_str == str(expected_output_path)
    assert expected_output_path.exists()

    with open(expected_output_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["total_segments"] == 11

    # 進捗表示の出力を確認
    captured = capsys.readouterr()
    assert "10 セグメント処理済み..." in captured.out
    assert "最初の5セグメント:" in captured.out


def test_transcribe_all_videos(tmp_path, capsys):
    """transcribe_all_videos のテスト (正常系と異常系)"""
    video_dir = tmp_path / "videos"
    video_dir.mkdir()

    # 2つのダミー動画ファイルを作成
    video1 = video_dir / "video1.mp4"
    video1.write_bytes(b"\x00" * 100)
    video2 = video_dir / "video2.mp4"
    video2.write_bytes(b"\x00" * 100)

    # WhisperModel のモック設定
    mock_model_instance = MagicMock()
    mock_whisper_model_class.return_value = mock_model_instance

    mock_info = MagicMock()
    mock_info.language = "ja"
    mock_info.duration = 5.0

    # transcribe_video 自体をパッチして、正常系と異常系をシミュレートする
    def mock_transcribe_video(video_path: str, model_size: str = "medium", output_dir: str = None):
        if "video2.mp4" in video_path:
            raise RuntimeError("Mock transcribe error")
        return f"{video_path}_whisper.json"

    with patch("whisper_fixed.transcribe_video", side_effect=mock_transcribe_video):
        results = whisper_fixed.transcribe_all_videos(str(video_dir), model_size="medium")

    # 結果の検証
    assert len(results) == 2
    
    # ファイル名順とは限らないため、検索して検証
    res_video1 = next(r for r in results if r["file"] == "video1.mp4")
    res_video2 = next(r for r in results if r["file"] == "video2.mp4")

    assert res_video1["status"] == "success"
    assert "video1.mp4_whisper.json" in res_video1["output"]
    
    assert res_video2["status"] == "failed"
    assert "Mock transcribe error" in res_video2["error"]

    # サマリー表示を確認
    captured = capsys.readouterr()
    assert "成功: 1/2" in captured.out


def test_main_execution_no_args(capsys):
    """コマンドライン引数なしでの実行 (SystemExitコード1を期待)"""
    script_path = str(backend_dir / "whisper_fixed.py")
    with patch.object(sys, "argv", ["whisper_fixed.py"]):
        with pytest.raises(SystemExit) as exc_info:
            runpy.run_path(script_path, run_name="__main__")
        assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "使用方法:" in captured.out


def test_main_execution_single_file(tmp_path):
    """単一ファイル実行モードのテスト"""
    script_path = str(backend_dir / "whisper_fixed.py")
    video_file = tmp_path / "main_single.mp4"
    video_file.write_bytes(b"\x00" * 100)

    # WhisperModel のモック設定
    mock_model_instance = MagicMock()
    mock_whisper_model_class.return_value = mock_model_instance

    mock_info = MagicMock()
    mock_info.language = "ja"
    mock_info.duration = 5.0

    seg = MagicMock()
    seg.start = 0.0
    seg.end = 2.0
    seg.text = "test_main"

    mock_model_instance.transcribe.return_value = ([seg], mock_info)

    # argv を設定して runpy で実行
    with patch.object(sys, "argv", ["whisper_fixed.py", str(video_file), "large"]):
        runpy.run_path(script_path, run_name="__main__")
        
    expected_output_path = tmp_path / "main_single_whisper.json"
    assert expected_output_path.exists()

    with open(expected_output_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["video"] == "main_single.mp4"
        assert data["model"] == "large"
        assert len(data["segments"]) == 1
        assert data["segments"][0]["text"] == "test_main"


def test_main_execution_all_videos(tmp_path, capsys):
    """全ファイル一括実行モードのテスト"""
    script_path = str(backend_dir / "whisper_fixed.py")
    video_dir = tmp_path / "main_dir"
    video_dir.mkdir()

    video_file = video_dir / "main_dir_video.mp4"
    video_file.write_bytes(b"\x00" * 100)

    # WhisperModel のモック設定
    mock_model_instance = MagicMock()
    mock_whisper_model_class.return_value = mock_model_instance

    mock_info = MagicMock()
    mock_info.language = "ja"
    mock_info.duration = 8.0

    seg = MagicMock()
    seg.start = 0.0
    seg.end = 4.0
    seg.text = "test_dir"

    mock_model_instance.transcribe.return_value = ([seg], mock_info)

    with patch.object(sys, "argv", ["whisper_fixed.py", "--all", str(video_dir), "base"]):
        runpy.run_path(script_path, run_name="__main__")
        
    expected_output_path = video_dir / "main_dir_video_whisper.json"
    assert expected_output_path.exists()

    captured = capsys.readouterr()
    assert "成功: 1/1" in captured.out
