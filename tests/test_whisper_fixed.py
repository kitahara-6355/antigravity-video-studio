import sys
import os
import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
import runpy
from dataclasses import dataclass

@dataclass
class MockSegment:
    start: float
    end: float
    text: str

@dataclass
class MockInfo:
    language: str
    duration: float

# faster_whisper のインポートをモック化 (runpy等で再インポートされてもモックが使われるようにする)
mock_faster_whisper = MagicMock()
mock_whisper_model_class = MagicMock()
mock_faster_whisper.WhisperModel = mock_whisper_model_class
sys.modules['faster_whisper'] = mock_faster_whisper

# デフォルトのモック挙動設定
mock_model_instance = MagicMock()
mock_whisper_model_class.return_value = mock_model_instance
mock_segments = [MockSegment(start=0.0, end=1.0, text="test segment")]
mock_info = MockInfo(language="ja", duration=1.0)
mock_model_instance.transcribe.return_value = (mock_segments, mock_info)

# backend.whisper_fixed をテスト対象とする

def test_transcribe_video_not_found(tmp_path):
    from backend.whisper_fixed import transcribe_video
    # 存在しないパス
    non_existent = tmp_path / "does_not_exist.mp4"
    result = transcribe_video(str(non_existent))
    assert result is None

@patch("backend.whisper_fixed.WhisperModel")
def test_transcribe_video_success_default_output(mock_whisper_cls, tmp_path):
    from backend.whisper_fixed import transcribe_video
    
    # モックの設定
    mock_model = MagicMock()
    mock_whisper_cls.return_value = mock_model
    
    # 11個のセグメントを返す（10セグメントごとの進捗表示ブランチをカバーするため）
    mock_segments_local = [MockSegment(start=float(i), end=float(i+1), text=f" segment {i} ") for i in range(11)]
    mock_info_local = MockInfo(language="ja", duration=11.0)
    mock_model.transcribe.return_value = (mock_segments_local, mock_info_local)
    
    # ダミー動画ファイル作成
    video_path = tmp_path / "dummy_video.mp4"
    video_path.write_text("dummy content")
    
    result = transcribe_video(str(video_path), model_size="tiny")
    
    # 結果の確認
    expected_output = tmp_path / "dummy_video_whisper.json"
    assert result == str(expected_output)
    assert expected_output.exists()
    
    with open(expected_output, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["video"] == "dummy_video.mp4"
        assert data["model"] == "tiny"
        assert data["language"] == "ja"
        assert data["duration"] == 11.0
        assert data["total_segments"] == 11
        assert len(data["segments"]) == 11
        assert data["segments"][0]["text"] == "segment 0"

@patch("backend.whisper_fixed.WhisperModel")
def test_transcribe_video_success_custom_output(mock_whisper_cls, tmp_path):
    from backend.whisper_fixed import transcribe_video
    
    mock_model = MagicMock()
    mock_whisper_cls.return_value = mock_model
    
    # 3個のセグメントを返す（最初の5セグメントプレビューの表示を5個未満でテスト）
    mock_segments_local = [MockSegment(start=float(i), end=float(i+1), text=f"seg {i}") for i in range(3)]
    mock_info_local = MockInfo(language="en", duration=3.0)
    mock_model.transcribe.return_value = (mock_segments_local, mock_info_local)
    
    video_path = tmp_path / "dummy_video.mp4"
    video_path.write_text("dummy")
    
    output_dir = tmp_path / "output_subdir"
    output_dir.mkdir()
    
    result = transcribe_video(str(video_path), model_size="base", output_dir=str(output_dir))
    
    expected_output = output_dir / "dummy_video_whisper.json"
    assert result == str(expected_output)
    assert expected_output.exists()
    
    with open(expected_output, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["language"] == "en"
        assert data["total_segments"] == 3

@patch("backend.whisper_fixed.transcribe_video")
def test_transcribe_all_videos(mock_transcribe_video, tmp_path):
    from backend.whisper_fixed import transcribe_all_videos
    
    # フォルダ内に動画を作成
    (tmp_path / "v1.mp4").write_text("v1")
    (tmp_path / "v2.mp4").write_text("v2")
    # mp4以外は無視されるはず
    (tmp_path / "v3.txt").write_text("v3")
    
    # モックの挙動：v1.mp4 は成功、v2.mp4 は例外発生
    def side_effect(video_path, model_size):
        if "v1.mp4" in video_path:
            return "v1_whisper.json"
        else:
            raise RuntimeError("transcribe error")
            
    mock_transcribe_video.side_effect = side_effect
    
    results = transcribe_all_videos(str(tmp_path), model_size="medium")
    
    assert len(results) == 2
    # 並び順は glob なので不定かもしれないが、v1 と v2 があるはず
    v1_res = [r for r in results if r["file"] == "v1.mp4"][0]
    v2_res = [r for r in results if r["file"] == "v2.mp4"][0]
    
    assert v1_res["status"] == "success"
    assert v1_res["output"] == "v1_whisper.json"
    
    assert v2_res["status"] == "failed"
    assert "transcribe error" in v2_res["error"]

def test_main_no_arguments():
    # 引数が足りない場合のテスト
    # sys.exit(1) が発生することを確認
    with patch("sys.argv", ["whisper_fixed.py"]):
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_module("backend.whisper_fixed", run_name="__main__")
        assert excinfo.value.code == 1

def test_main_single_file(tmp_path):
    # 通常の単一ファイル実行
    video_file = tmp_path / "video.mp4"
    video_file.write_text("dummy")
    
    with patch("sys.argv", ["whisper_fixed.py", str(video_file)]):
        runpy.run_module("backend.whisper_fixed", run_name="__main__")
        
    expected_output = tmp_path / "video_whisper.json"
    assert expected_output.exists()
    with open(expected_output, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["model"] == "medium"

def test_main_single_file_with_model(tmp_path):
    # モデルサイズ指定ありの単一ファイル実行
    video_file = tmp_path / "video.mp4"
    video_file.write_text("dummy")
    
    with patch("sys.argv", ["whisper_fixed.py", str(video_file), "large-v3"]):
        runpy.run_module("backend.whisper_fixed", run_name="__main__")
        
    expected_output = tmp_path / "video_whisper.json"
    assert expected_output.exists()
    with open(expected_output, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["model"] == "large-v3"

def test_main_all_videos_default_model(tmp_path):
    # --all でモデルサイズ指定なし
    video_dir = tmp_path / "my_dir"
    video_dir.mkdir()
    (video_dir / "video1.mp4").write_text("dummy")
    (video_dir / "video2.mp4").write_text("dummy")
    
    with patch("sys.argv", ["whisper_fixed.py", "--all", str(video_dir)]):
        runpy.run_module("backend.whisper_fixed", run_name="__main__")
        
    assert (video_dir / "video1_whisper.json").exists()
    assert (video_dir / "video2_whisper.json").exists()

def test_main_all_videos_with_model(tmp_path):
    # --all でモデルサイズ指定あり
    video_dir = tmp_path / "my_dir"
    video_dir.mkdir()
    (video_dir / "video1.mp4").write_text("dummy")
    
    with patch("sys.argv", ["whisper_fixed.py", "--all", str(video_dir), "large-v3"]):
        runpy.run_module("backend.whisper_fixed", run_name="__main__")
        
    expected_output = video_dir / "video1_whisper.json"
    assert expected_output.exists()
    with open(expected_output, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["model"] == "large-v3"

def test_main_all_videos_no_dir(tmp_path):
    # --all でディレクトリも指定なし (デフォルトは ".")
    video_file = tmp_path / "video_in_cwd.mp4"
    video_file.write_text("dummy")
    
    old_cwd = os.getcwd()
    os.chdir(str(tmp_path))
    try:
        with patch("sys.argv", ["whisper_fixed.py", "--all"]):
            runpy.run_module("backend.whisper_fixed", run_name="__main__")
    finally:
        os.chdir(old_cwd)
        
    assert (tmp_path / "video_in_cwd_whisper.json").exists()

def test_sys_stdout_not_corrupted_after_import():
    # whisper_fixed をインポートした後に sys.stdout / sys.stderr がクローズされておらず、書き込み可能であることを検証
    assert not sys.stdout.closed
    assert not sys.stderr.closed
    # 正常に書き込みができること
    sys.stdout.write("")
    sys.stderr.write("")
