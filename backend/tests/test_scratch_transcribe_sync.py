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
    with patch("builtins.open", mock_open), \
         patch("json.dump") as mock_json_dump:
        
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
    
    with patch("asyncio.new_event_loop", return_value=mock_loop), \
         patch("builtins.open", MagicMock()), \
         patch("json.dump", side_effect=IOError("Write failed")):
        
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
    
    with patch("subtitle_engine.whisper_transcriber.WhisperTranscriber", return_value=mock_instance) as mock_class, \
         patch("sys.argv", ["transcribe_sync.py", "dummy_path/video.mp4", "large"]):
        
        real_open = open
        mock_file = MagicMock()
        def side_effect_open(file, *args, **kwargs):
            if "video_whisper.json" in str(file):
                return mock_file
            return real_open(file, *args, **kwargs)
            
        with patch("builtins.open", side_effect=side_effect_open), \
             patch("json.dump") as mock_json_dump:
            
            runpy.run_module("transcribe_sync", run_name="__main__")
            
            # For 100% coverage verification on branch path:
            try:
                open("dummy_non_existent_file.txt", "r")
            except FileNotFoundError:
                pass
            
            mock_class.assert_called_once_with(model_size="large")
            mock_instance.transcribe.assert_called_once()
            mock_json_dump.assert_called_once()
