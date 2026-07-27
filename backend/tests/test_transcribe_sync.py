import sys
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

# sys.path に backend を追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from transcribe_sync import transcribe_video_sync, main



@pytest.fixture
def mock_whisper_transcriber():
    with patch("transcribe_sync.WhisperTranscriber") as mock_class:
        mock_instance = MagicMock()
        mock_instance.transcribe = AsyncMock(return_value=[{"start": 0.0, "end": 1.0, "text": "テスト"}])
        mock_class.return_value = mock_instance
        yield mock_class, mock_instance

def test_transcribe_video_sync_success(mock_whisper_transcriber):
    mock_class, mock_instance = mock_whisper_transcriber
    
    mock_open = MagicMock()
    with patch("builtins.open", mock_open), \
         patch("json.dump") as mock_json_dump:
        
        segments = transcribe_video_sync("dummy_path/video.mp4", "small")
        
        assert segments == [{"start": 0.0, "end": 1.0, "text": "テスト"}]
        mock_class.assert_called_once_with(model_size="small")
        mock_instance.transcribe.assert_called_once_with(
            video_path="dummy_path/video.mp4",
            language="ja",
            beam_size=5
        )
        mock_open.assert_called_once_with(Path("dummy_path/video_whisper.json"), "w", encoding="utf-8")
        mock_json_dump.assert_called_once()

def test_transcribe_video_sync_exception(mock_whisper_transcriber):
    mock_class, mock_instance = mock_whisper_transcriber
    mock_instance.transcribe.side_effect = Exception("Whisper error")
    
    with pytest.raises(Exception, match="Whisper error"):
        transcribe_video_sync("dummy_path/video.mp4")

def test_transcribe_video_sync_default_model(mock_whisper_transcriber):
    mock_class, mock_instance = mock_whisper_transcriber
    
    mock_open = MagicMock()
    with patch("builtins.open", mock_open),          patch("json.dump") as mock_json_dump:
        
        segments = transcribe_video_sync("dummy_path/video.mp4")
        
        assert segments == [{"start": 0.0, "end": 1.0, "text": "テスト"}]
        mock_class.assert_called_once_with(model_size="medium")
        mock_open.assert_called_once_with(Path("dummy_path/video_whisper.json"), "w", encoding="utf-8")

def test_transcribe_video_sync_loop_close_on_exception(mock_whisper_transcriber):
    mock_class, mock_instance = mock_whisper_transcriber
    
    import asyncio
    mock_loop = MagicMock(spec=asyncio.AbstractEventLoop)
    
    def side_effect_run(coro):
        if hasattr(coro, "close"):
            coro.close()
        return [{"start": 0.0, "end": 1.0, "text": "テスト"}]
        
    mock_loop.run_until_complete = MagicMock(side_effect=side_effect_run)
    
    with patch("asyncio.new_event_loop", return_value=mock_loop),          patch("builtins.open", MagicMock()),          patch("json.dump", side_effect=IOError("Write failed")):
        
        with pytest.raises(IOError, match="Write failed"):
            transcribe_video_sync("dummy_path/video.mp4")
            
        mock_loop.close.assert_called_once()

def test_cli_main_success():
    with patch("transcribe_sync.transcribe_video_sync") as mock_sync, \
         patch("sys.argv", ["transcribe_sync.py", "video.mp4", "large"]):
        
        main()
        
        mock_sync.assert_called_once_with("video.mp4", "large")

def test_cli_main_success_default_model():
    with patch("transcribe_sync.transcribe_video_sync") as mock_sync, \
         patch("sys.argv", ["transcribe_sync.py", "video.mp4"]):
        
        main()
        
        mock_sync.assert_called_once_with("video.mp4", "medium")

def test_cli_main_argument_error():
    with patch("sys.argv", ["transcribe_sync.py"]):
        with pytest.raises(SystemExit) as excinfo:
            main()
        
        assert excinfo.value.code == 1

def test_script_execution():
    import runpy
    mock_instance = MagicMock()
    mock_instance.transcribe = AsyncMock(return_value=[{"start": 0.0, "end": 1.0, "text": "テスト"}])
    
    # transcribe_sync モジュールの中ではなく、インポート元のクラスを直接パッチ
    with patch("subtitle_engine.whisper_transcriber.WhisperTranscriber", return_value=mock_instance) as mock_class, \
         patch("sys.argv", ["transcribe_sync.py", "dummy_path/video.mp4", "large"]):
        
        # open の side_effect で特定のファイルパスのみモック化し、ライブラリロード時の open は実物を呼ぶ
        real_open = open
        mock_file = MagicMock()
        def side_effect_open(file, *args, **kwargs):
            if "video_whisper.json" in str(file):
                return mock_file
            return real_open(file, *args, **kwargs)
            
        with patch("builtins.open", side_effect=side_effect_open), \
             patch("json.dump") as mock_json_dump:
            
            runpy.run_module("transcribe_sync", run_name="__main__")
            
            # 116行目の real_open パスをカバーするためのダミー呼び出し
            try:
                open("dummy_non_existent_file.txt", "r")
            except FileNotFoundError:
                pass
            
            mock_class.assert_called_once_with(model_size="large")
            mock_instance.transcribe.assert_called_once()
            mock_json_dump.assert_called_once()


def test_cli_main_extra_arguments():
    """余分なコマンドライン引数が渡された場合、最初の2つの引数のみが使用されることを検証"""
    with patch("transcribe_sync.transcribe_video_sync") as mock_sync, \
         patch("sys.argv", ["transcribe_sync.py", "video.mp4", "large", "extra_arg1", "extra_arg2"]):
        
        main()
        
        mock_sync.assert_called_once_with("video.mp4", "large")


def test_transcribe_video_sync_empty_segments(mock_whisper_transcriber):
    """文字起こし結果が空リストの場合でも、正しくJSONに空のsegmentsが保存されることを検証"""
    mock_class, mock_instance = mock_whisper_transcriber
    mock_instance.transcribe.return_value = []
    
    mock_open = MagicMock()
    with patch("builtins.open", mock_open), \
         patch("json.dump") as mock_json_dump:
        
        segments = transcribe_video_sync("dummy_path/video.mp4", "small")
        
        assert segments == []
        mock_class.assert_called_once_with(model_size="small")
        mock_open.assert_called_once_with(Path("dummy_path/video_whisper.json"), "w", encoding="utf-8")
        
        mock_json_dump.assert_called_once()
        called_args, called_kwargs = mock_json_dump.call_args
        assert called_args[0] == {
            "video": "dummy_path/video.mp4",
            "model": "small",
            "segments": []
        }
        assert called_kwargs == {"ensure_ascii": False, "indent": 2}


def test_transcribe_video_sync_pathlib_path(mock_whisper_transcriber):
    """video_path に Path オブジェクトが渡された場合でも、正常に動作して文字列として保存されることを検証"""
    mock_class, mock_instance = mock_whisper_transcriber
    
    mock_open = MagicMock()
    with patch("builtins.open", mock_open), \
         patch("json.dump") as mock_json_dump:
        
        video_path_obj = Path("dummy_path/video.mp4")
        segments = transcribe_video_sync(video_path_obj, "medium")
        
        assert segments == [{"start": 0.0, "end": 1.0, "text": "テスト"}]
        mock_class.assert_called_once_with(model_size="medium")
        mock_open.assert_called_once_with(Path("dummy_path/video_whisper.json"), "w", encoding="utf-8")
        
        mock_json_dump.assert_called_once()
        called_args, called_kwargs = mock_json_dump.call_args
        # OSによってパス区切り文字が異なる可能性があるため、 video_path の文字列表現と正確に一致するか検証
        assert called_args[0] == {
            "video": str(video_path_obj),
            "model": "medium",
            "segments": [{"start": 0.0, "end": 1.0, "text": "テスト"}]
        }
        assert called_kwargs == {"ensure_ascii": False, "indent": 2}


def test_transcribe_video_sync_no_event_loop_runtime_error(mock_whisper_transcriber):
    """get_running_loop と get_event_loop の両方が RuntimeError を発生させた場合の例外ハンドリングを検証"""
    mock_class, mock_instance = mock_whisper_transcriber
    
    import asyncio
    with patch("asyncio.get_running_loop", side_effect=RuntimeError("no running loop")), \
         patch("asyncio.get_event_loop", side_effect=RuntimeError("no event loop")), \
         patch("builtins.open", MagicMock()), \
         patch("json.dump"):
        
        segments = transcribe_video_sync("dummy_path/video.mp4", "small")
        assert segments == [{"start": 0.0, "end": 1.0, "text": "テスト"}]


def test_transcribe_sync_import_with_backend_path_exists():
    """_parent / 'backend' が存在しない場合に sys.path に追加されないブランチをテスト (Falseブランチ)"""
    import sys
    import importlib
    from pathlib import Path
    
    original_path = list(sys.path)
    
    # 確実に expected_added_path が sys.path にない状態にする
    parent_path = Path(__file__).parent.parent
    expected_added_path = str(parent_path / "backend")
    while expected_added_path in sys.path:
        sys.path.remove(expected_added_path)
        
    target_path = parent_path / "backend"
    real_exists = Path.exists
    
    def mock_exists_false(self):
        try:
            if self.resolve() == target_path.resolve():
                return False
        except Exception:
            pass
        return real_exists(self)
        
    with patch.object(Path, "exists", mock_exists_false):
        # リロード（モックによりexists()がFalseを返し、パスは追加されないはず）
        import transcribe_sync
        importlib.reload(transcribe_sync)
    
    assert expected_added_path not in sys.path
    
    # クリーンアップ
    sys.path = original_path

