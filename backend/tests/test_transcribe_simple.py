import sys
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import runpy

# テスト対象のインポートが正しく動くように sys.path を設定
sys.path.insert(0, str(Path(__file__).parent.parent))

from transcribe_simple import transcribe_simple


def test_transcribe_simple_success(tmp_path):
    video_path = tmp_path / "test_video.mp4"
    video_path.write_text("dummy video content")
    
    # 51個のセグメントを用意し、i % 50 == 0 の進捗表示をカバーする
    expected_segments = []
    for i in range(1, 52):
        expected_segments.append({
            "start": float(i - 1),
            "end": float(i),
            "text": f"segment {i}"
        })
    
    # WhisperModel をモック化
    mock_model_inst = MagicMock()
    
    # transcribe メソッドの戻り値をモック
    # segments_iter はイテラブルである必要があり、各要素は start, end, text 属性を持つオブジェクト
    class MockSegment:
        def __init__(self, start, end, text):
            self.start = start
            self.end = end
            self.text = text

    mock_segments_iter = [MockSegment(seg["start"], seg["end"], seg["text"]) for seg in expected_segments]
    
    mock_info = MagicMock()
    mock_info.language = "ja"
    
    mock_model_inst.transcribe.return_value = (mock_segments_iter, mock_info)
    
    with patch("faster_whisper.WhisperModel", return_value=mock_model_inst), \
         patch("transcribe_simple.WhisperModel", return_value=mock_model_inst):
        result = transcribe_simple(str(video_path), model_size="tiny")
        
        # 戻り値の検証
        assert len(result) == 51
        assert result[0]["text"] == "segment 1"
        assert result[50]["text"] == "segment 51"
        
        # 保存されたJSONファイルの検証
        output_json_path = tmp_path / "test_video_whisper.json"
        assert output_json_path.exists()
        
        with open(output_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert data["video"] == str(video_path)
            assert data["model"] == "tiny"
            assert data["language"] == "ja"
            assert len(data["segments"]) == 51
            assert data["segments"][0]["text"] == "segment 1"


def test_transcribe_simple_exception(tmp_path):
    video_path = tmp_path / "test_video.mp4"
    video_path.write_text("dummy video content")
    
    mock_model_inst = MagicMock()
    mock_model_inst.transcribe.side_effect = RuntimeError("Whisper error")
    
    with patch("faster_whisper.WhisperModel", return_value=mock_model_inst), \
         patch("transcribe_simple.WhisperModel", return_value=mock_model_inst):
        with pytest.raises(RuntimeError, match="Whisper error"):
            transcribe_simple(str(video_path), model_size="tiny")
            
        # 例外発生時は JSON ファイルが生成されないことを確認
        output_json_path = tmp_path / "test_video_whisper.json"
        assert not output_json_path.exists()


def test_main_execution_success(tmp_path):
    video_path = tmp_path / "test_video.mp4"
    video_path.write_text("dummy video content")
    
    class MockSegment:
        def __init__(self, start, end, text):
            self.start = start
            self.end = end
            self.text = text

    mock_segments_iter = [MockSegment(0.0, 1.0, "main test")]
    mock_info = MagicMock()
    mock_info.language = "ja"
    
    mock_model_inst = MagicMock()
    mock_model_inst.transcribe.return_value = (mock_segments_iter, mock_info)
    
    # sys.argv と WhisperModel をモックして実行
    test_args = ["transcribe_simple.py", str(video_path), "small"]
    with patch("sys.argv", test_args), \
         patch("faster_whisper.WhisperModel", return_value=mock_model_inst), \
         patch("transcribe_simple.WhisperModel", return_value=mock_model_inst):
        # run_pathで __main__ を実行
        runpy.run_path(str(Path(__file__).parent.parent / "transcribe_simple.py"), run_name="__main__")
        
    # 保存されたJSONファイルの検証
    output_json_path = tmp_path / "test_video_whisper.json"
    assert output_json_path.exists()
    with open(output_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["segments"][0]["text"] == "main test"
        assert data["model"] == "small"


def test_main_execution_default_model(tmp_path):
    video_path = tmp_path / "test_video.mp4"
    video_path.write_text("dummy video content")
    
    class MockSegment:
        def __init__(self, start, end, text):
            self.start = start
            self.end = end
            self.text = text

    mock_segments_iter = [MockSegment(0.0, 1.0, "default test")]
    mock_info = MagicMock()
    mock_info.language = "ja"
    
    mock_model_inst = MagicMock()
    mock_model_inst.transcribe.return_value = (mock_segments_iter, mock_info)
    
    # 引数が2つの場合（model_size省略）
    test_args = ["transcribe_simple.py", str(video_path)]
    with patch("sys.argv", test_args), \
         patch("faster_whisper.WhisperModel", return_value=mock_model_inst), \
         patch("transcribe_simple.WhisperModel", return_value=mock_model_inst):
        runpy.run_path(str(Path(__file__).parent.parent / "transcribe_simple.py"), run_name="__main__")
        
    # 保存されたJSONファイルの検証
    output_json_path = tmp_path / "test_video_whisper.json"
    assert output_json_path.exists()
    with open(output_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["segments"][0]["text"] == "default test"
        assert data["model"] == "medium"  # デフォルト値


def test_main_execution_no_args():
    # 引数が足りない場合は sys.exit(1) で終了することを確認
    test_args = ["transcribe_simple.py"]
    with patch("sys.argv", test_args):
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_path(str(Path(__file__).parent.parent / "transcribe_simple.py"), run_name="__main__")
        assert excinfo.value.code == 1


def test_transcribe_simple_file_not_found():
    # 存在しないパスを渡したときに FileNotFoundError が発生することを確認
    non_existent_path = "non_existent_video.mp4"
    with pytest.raises(FileNotFoundError, match="Video file not found"):
        transcribe_simple(non_existent_path)


def test_main_execution_file_not_found():
    # コマンドライン実行で存在しない動画パスを指定した際、sys.exit(1) で終了することを確認
    non_existent_path = "non_existent_video.mp4"
    test_args = ["transcribe_simple.py", non_existent_path]
    with patch("sys.argv", test_args):
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_path(str(Path(__file__).parent.parent / "transcribe_simple.py"), run_name="__main__")
        assert excinfo.value.code == 1


def test_transcribe_simple_directory_input(tmp_path):
    # ディレクトリを渡したときに FileNotFoundError が発生することを確認
    dir_path = tmp_path / "sub_dir"
    dir_path.mkdir()
    with pytest.raises(FileNotFoundError, match="Video file not found or is not a file"):
        transcribe_simple(str(dir_path))


def test_transcribe_simple_invalid_model_size(tmp_path):
    # 無効なモデルサイズを渡したときに ValueError が発生することを確認
    video_path = tmp_path / "test_video.mp4"
    video_path.write_text("dummy video content")
    with pytest.raises(ValueError, match="Invalid model size"):
        transcribe_simple(str(video_path), model_size="invalid_size")


def test_main_execution_invalid_model_size(tmp_path):
    # コマンドライン実行で無効なモデルサイズを指定した際、sys.exit(1) で終了することを確認
    video_path = tmp_path / "test_video.mp4"
    video_path.write_text("dummy video content")
    test_args = ["transcribe_simple.py", str(video_path), "invalid_size"]
    with patch("sys.argv", test_args):
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_path(str(Path(__file__).parent.parent / "transcribe_simple.py"), run_name="__main__")
        assert excinfo.value.code == 1


def test_main_execution_runtime_error(tmp_path):
    # WhisperModelでRuntimeErrorが起きた場合、sys.exit(1) で終了することを確認
    video_path = tmp_path / "test_video.mp4"
    video_path.write_text("dummy video content")
    
    mock_model_inst = MagicMock()
    mock_model_inst.transcribe.side_effect = RuntimeError("Whisper runtime fail")
    
    test_args = ["transcribe_simple.py", str(video_path), "tiny"]
    with patch("sys.argv", test_args),          patch("faster_whisper.WhisperModel", return_value=mock_model_inst),          patch("transcribe_simple.WhisperModel", return_value=mock_model_inst):
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_path(str(Path(__file__).parent.parent / "transcribe_simple.py"), run_name="__main__")
        assert excinfo.value.code == 1



def test_transcribe_simple_model_load_exception(tmp_path):
    # WhisperModelのロード時に例外が発生した場合のハンドリング検証
    video_path = tmp_path / "test_video.mp4"
    video_path.write_text("dummy video content")
    
    with patch("transcribe_simple.WhisperModel", side_effect=Exception("Model load fail")):
        with pytest.raises(RuntimeError, match="Failed to load Whisper model 'tiny'"):
            transcribe_simple(str(video_path), model_size="tiny")


def test_transcribe_simple_transcribe_loop_exception(tmp_path):
    # 文字起こしループ中に例外が発生した場合のハンドリング検証
    video_path = tmp_path / "test_video.mp4"
    video_path.write_text("dummy video content")
    
    mock_model_inst = MagicMock()
    # イテレータの途中で例外を投げるようにする
    def dummy_transcribe(*args, **kwargs):
        class BadIter:
            def __iter__(self):
                return self
            def __next__(self):
                raise Exception("Iteration fail")
        return BadIter(), MagicMock()
        
    mock_model_inst.transcribe = dummy_transcribe
    
    with patch("transcribe_simple.WhisperModel", return_value=mock_model_inst):
        with pytest.raises(RuntimeError, match="Error during Whisper transcription"):
            transcribe_simple(str(video_path), model_size="tiny")


def test_transcribe_simple_json_write_exception(tmp_path):
    # JSON保存時にOSErrorが発生した場合のハンドリング検証
    video_path = tmp_path / "test_video.mp4"
    video_path.write_text("dummy video content")
    
    class MockSegment:
        def __init__(self, start, end, text):
            self.start = start
            self.end = end
            self.text = text

    mock_segments_iter = [MockSegment(0.0, 1.0, "segment")]
    mock_info = MagicMock()
    mock_info.language = "ja"
    mock_model_inst = MagicMock()
    mock_model_inst.transcribe.return_value = (mock_segments_iter, mock_info)
    
    # builtins.openをモックして書き込み時にOSErrorを発生させる
    # ただし、モックの影響範囲を狭めるため、特定のファイル書き込み時のみOSErrorにする
    original_open = open
    def mock_open(file, *args, **kwargs):
        if str(file).endswith("_whisper.json"):
            raise OSError("Write permission denied")
        return original_open(file, *args, **kwargs)
    
    with patch("transcribe_simple.WhisperModel", return_value=mock_model_inst),          patch("builtins.open", mock_open):
        with pytest.raises(OSError, match="Failed to save transcription JSON"):
            transcribe_simple(str(video_path), model_size="tiny")


def test_main_execution_unexpected_exception(tmp_path):
    # メインブロック実行時に予期せぬ例外が発生し、except Exceptionでキャッチされてsys.exit(1)になることを検証
    video_path = tmp_path / "test_video.mp4"
    video_path.write_text("dummy video content")
    
    # Path.is_file が KeyError (標準例外で既知の4つ以外) を投げるようにモックする
    # これにより transcribe_simple() から KeyError が直接発生する
    with patch("transcribe_simple.Path.is_file", side_effect=KeyError("Unexpected KeyError")):
        test_args = ["transcribe_simple.py", str(video_path), "tiny"]
        with patch("sys.argv", test_args):
            with pytest.raises(SystemExit) as excinfo:
                runpy.run_path(str(Path(__file__).parent.parent / "transcribe_simple.py"), run_name="__main__")
            assert excinfo.value.code == 1


def test_main_execution_os_error(tmp_path):
    # コマンドライン実行で OSError が発生した際、sys.exit(1) で終了することを確認
    video_path = tmp_path / "test_video.mp4"
    video_path.write_text("dummy video content")
    
    class MockSegment:
        def __init__(self, start, end, text):
            self.start = start
            self.end = end
            self.text = text

    mock_segments_iter = [MockSegment(0.0, 1.0, "segment")]
    mock_info = MagicMock()
    mock_info.language = "ja"
    mock_model_inst = MagicMock()
    mock_model_inst.transcribe.return_value = (mock_segments_iter, mock_info)
    
    # builtins.openをモックして書き込み時にOSErrorを発生させる
    original_open = open
    def mock_open(file, *args, **kwargs):
        if str(file).endswith("_whisper.json"):
            raise OSError("Write permission denied")
        return original_open(file, *args, **kwargs)
    
    test_args = ["transcribe_simple.py", str(video_path), "tiny"]
    with patch("sys.argv", test_args), \
         patch("faster_whisper.WhisperModel", return_value=mock_model_inst), \
         patch("transcribe_simple.WhisperModel", return_value=mock_model_inst), \
         patch("builtins.open", mock_open):
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_path(str(Path(__file__).parent.parent / "transcribe_simple.py"), run_name="__main__")
        assert excinfo.value.code == 1
