import os
import time
import pytest
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open, PropertyMock

from video_processor import (
    ProcessingPhase,
    VideoMood,
    MoodSettings,
    ProcessingTask,
    VideoProcessor,
    video_processor,
    MOOD_SETTINGS
)

def test_enums():
    # ProcessingPhase, VideoMood, MoodSettings, ProcessingTask
    assert ProcessingPhase.IDLE.value == "idle"
    assert VideoMood.ELEGANT.value == "elegant"
    
    settings = MoodSettings(name="test", color_preset="test", transition="test", music_style="test", telop_style="test")
    assert settings.logo_opacity == 0.6
    
    task = ProcessingTask(task_id="t1", video_paths=["/path/to/v1"], mood="elegant")
    assert task.phase == ProcessingPhase.IDLE

def test_videoprocessor_init_and_callback():
    # __init__ with default and custom dir
    vp_default = VideoProcessor()
    # verify directory is created (mocked mkdir)
    with patch("pathlib.Path.mkdir") as mock_mkdir:
        vp_custom = VideoProcessor(output_dir="/custom/dir")
        assert vp_custom.output_dir == Path("/custom/dir")
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
    
    # Callback
    cb = MagicMock()
    vp_custom.set_progress_callback(cb)
    task = ProcessingTask(task_id="t1", video_paths=[], mood="elegant")
    vp_custom._notify_progress(task)
    cb.assert_called_once_with(task)

def test_get_mood_settings():
    vp = VideoProcessor()
    # case-insensitive
    settings = vp.get_mood_settings("ELEGANT")
    assert settings.name == "エレガント"
    
    # fallback
    settings_fallback = vp.get_mood_settings("nonexistent")
    assert settings_fallback.name == "エレガント"

def test_create_and_get_task():
    vp = VideoProcessor()
    task = vp.create_task("t1", ["v1"], "elegant", ["asset1"], "custom_out")
    assert task.task_id == "t1"
    assert task.video_paths == ["v1"]
    assert task.mood == "elegant"
    assert task.guest_assets == ["asset1"]
    assert task.output_name == "custom_out"
    
    assert vp.get_task("t1") == task
    assert vp.get_task("nonexistent") is None

@patch("builtins.open", new_callable=mock_open, read_data='{"entries": [], "philosophies": []}')
def test_record_soul_narrative(mock_file):
    # record soul narrative success (exists=True)
    vp = VideoProcessor()
    settings = MOOD_SETTINGS["elegant"]
    
    with patch("json.load", return_value={"entries": list(range(12)), "philosophies": []}) as mock_json_load, \
         patch("json.dump") as mock_json_dump, \
         patch("pathlib.Path.exists", return_value=True):
        vp._record_soul_narrative("t1", "out", settings, 3)
        mock_json_dump.assert_called_once()
        args, kwargs = mock_json_dump.call_args
        assert len(args[0]["entries"]) == 10

@patch("builtins.open", new_callable=mock_open)
def test_record_soul_narrative_log_not_exists(mock_file):
    # record soul narrative when log file does not exist (exists=False)
    vp = VideoProcessor()
    settings = MOOD_SETTINGS["elegant"]
    
    with patch("json.dump") as mock_json_dump, \
         patch("pathlib.Path.exists", return_value=False):
        vp._record_soul_narrative("t1", "out", settings, 3)
        mock_json_dump.assert_called_once()
        args, kwargs = mock_json_dump.call_args
        assert len(args[0]["entries"]) == 1

@patch("builtins.open", side_effect=Exception("File error"))
def test_record_soul_narrative_exception(mock_open_func):
    # Exception check
    vp = VideoProcessor()
    settings = MOOD_SETTINGS["elegant"]
    # should log warning but not raise
    vp._record_soul_narrative("t1", "out", settings, 3)

def test_get_color_filter():
    vp = VideoProcessor()
    settings = MagicMock()
    
    settings.color_preset = "warm"
    assert vp._get_color_filter(settings) != ""
    
    settings.color_preset = "vibrant"
    assert vp._get_color_filter(settings) != ""
    
    settings.color_preset = "nonexistent"
    assert vp._get_color_filter(settings) == ""

@patch("video_processor.subprocess.run")
def test_get_audio_normalize_args(mock_run):
    vp = VideoProcessor()
    
    # 2pass success case
    mock_res = MagicMock()
    mock_res.stderr = 'some stderr with json {\n"input_i": "-14.0"\n}\n'
    mock_run.return_value = mock_res
    
    args = vp._get_audio_normalize_args("in.mp4")
    assert "-af" in args
    
    # 2pass fail case (no json in stderr)
    mock_res.stderr = 'some error without json'
    args_fail = vp._get_audio_normalize_args("in.mp4")
    assert "-af" in args_fail
    
    # subprocess exception case
    mock_run.side_effect = Exception("sub error")
    args_exc = vp._get_audio_normalize_args("in.mp4")
    assert args_exc == []

# subprocess.Popen mock tests (safe_popen_mock is fixture from backend/tests/conftest.py)
def test_run_ffmpeg_success(safe_popen_mock):
    vp = VideoProcessor()
    proc = safe_popen_mock(returncode=0, stderr_text="Duration: 00:00:10.00\ntime=00:00:05.00\n")
    
    # mock subprocess.Popen
    with patch("video_processor.subprocess.Popen", return_value=proc):
        task = MagicMock()
        success = vp._run_ffmpeg(["ffmpeg"], "test run", task=task, base_progress=10, progress_range=10)
        assert success is True

def test_run_ffmpeg_fail(safe_popen_mock):
    vp = VideoProcessor()
    proc = safe_popen_mock(returncode=1, stderr_text="ffmpeg error")
    with patch("video_processor.subprocess.Popen", return_value=proc):
        success = vp._run_ffmpeg(["ffmpeg"], "test run")
        assert success is False

def test_run_ffmpeg_timeout(safe_popen_mock):
    vp = VideoProcessor()
    proc = safe_popen_mock(returncode=0)
    proc.wait.side_effect = subprocess.TimeoutExpired(["cmd"], 10)
    with patch("video_processor.subprocess.Popen", return_value=proc):
        success = vp._run_ffmpeg(["ffmpeg"], "test run", timeout=1)
        assert success is False
        proc.kill.assert_called_once()

def test_run_ffmpeg_exception():
    vp = VideoProcessor()
    with patch("video_processor.subprocess.Popen", side_effect=Exception("spawn error")):
        success = vp._run_ffmpeg(["ffmpeg"], "test run")
        assert success is False

@patch("shutil.copy")
def test_process_scene(mock_copy, safe_popen_mock):
    vp = VideoProcessor()
    settings = MOOD_SETTINGS["elegant"]
    
    # success case
    proc = safe_popen_mock(returncode=0)
    with patch("video_processor.subprocess.Popen", return_value=proc), \
         patch("video_processor.VideoProcessor._get_audio_normalize_args", return_value=["-af", "loudnorm"]):
        vp._process_scene("in.mp4", "out.mp4", settings)
        mock_copy.assert_not_called()
        
    # fail case -> fallback copy
    proc_fail = safe_popen_mock(returncode=1)
    with patch("video_processor.subprocess.Popen", return_value=proc_fail):
        vp._process_scene("in.mp4", "out.mp4", settings)
        mock_copy.assert_called_once_with("in.mp4", "out.mp4")

@patch("shutil.copy")
def test_process_scene_copy_failed(mock_copy, safe_popen_mock):
    vp = VideoProcessor()
    settings = MOOD_SETTINGS["elegant"]
    
    proc_fail = safe_popen_mock(returncode=1)
    mock_copy.side_effect = Exception("Copy error")
    with patch("video_processor.subprocess.Popen", return_value=proc_fail):
        # should catch copy exception and log it
        vp._process_scene("in.mp4", "out.mp4", settings)
        mock_copy.assert_called_once_with("in.mp4", "out.mp4")

@patch("shutil.copy")
def test_process_scene_color_filter_empty(mock_copy, safe_popen_mock):
    vp = VideoProcessor()
    # mood settings with color_preset that generates empty filter
    settings = MoodSettings(name="test", color_preset="nonexistent", transition="fade", music_style="classical", telop_style="minimal")
    
    proc = safe_popen_mock(returncode=0)
    with patch("video_processor.subprocess.Popen", return_value=proc):
        vp._process_scene("in.mp4", "out.mp4", settings)
        mock_copy.assert_not_called()

@patch("shutil.copy")
def test_process_scene_template_grading_exception(mock_copy, safe_popen_mock):
    vp = VideoProcessor()
    settings = MOOD_SETTINGS["elegant"]
    
    proc = safe_popen_mock(returncode=0)
    
    # Mock template_config to raise Exception on property access
    mock_template = MagicMock()
    type(mock_template).is_active = PropertyMock(side_effect=Exception("template property error"))
    
    with patch("video_processor.subprocess.Popen", return_value=proc), \
         patch("template_config.template_config", mock_template):
        vp._process_scene("in.mp4", "out.mp4", settings)
        mock_copy.assert_not_called()

@patch("shutil.copy")
@patch("pathlib.Path.exists")
def test_merge_scenes(mock_exists, mock_copy, safe_popen_mock):
    vp = VideoProcessor()
    
    # case 0: empty
    vp._merge_scenes([], "out.mp4")
    mock_copy.assert_not_called()
    
    # case 1: 1 scene
    mock_exists.return_value = True
    vp._merge_scenes(["s1.mp4"], "out.mp4")
    mock_copy.assert_called_once_with("s1.mp4", "out.mp4")
    mock_copy.reset_mock()
    
    # case 2: multiple scenes success
    proc = safe_popen_mock(returncode=0)
    with patch("video_processor.subprocess.Popen", return_value=proc), \
         patch("builtins.open", new_callable=mock_open) as mock_file:
        vp._merge_scenes(["s1.mp4", "s2.mp4"], "out.mp4")
        mock_file.assert_called_once()
        mock_copy.assert_not_called()
        
    # case 3: multiple scenes fail -> copy first scene
    proc_fail = safe_popen_mock(returncode=1)
    with patch("video_processor.subprocess.Popen", return_value=proc_fail), \
         patch("builtins.open", new_callable=mock_open):
        vp._merge_scenes(["s1.mp4", "s2.mp4"], "out.mp4")
        mock_copy.assert_called_once_with("s1.mp4", "out.mp4")

@patch("shutil.copy")
@patch("pathlib.Path.exists")
def test_apply_branding(mock_exists, mock_copy, safe_popen_mock):
    vp = VideoProcessor()
    settings = MOOD_SETTINGS["elegant"]
    
    # logo not exists
    mock_exists.return_value = False
    vp._apply_branding("in.mp4", "out.mp4", settings)
    mock_copy.assert_called_once_with("in.mp4", "out.mp4")
    mock_copy.reset_mock()
    
    # logo exists, ffmpeg success
    mock_exists.return_value = True
    proc = safe_popen_mock(returncode=0)
    with patch("video_processor.subprocess.Popen", return_value=proc):
        vp._apply_branding("in.mp4", "out.mp4", settings)
        mock_copy.assert_not_called()
        
    # logo exists, ffmpeg fail -> fallback copy
    proc_fail = safe_popen_mock(returncode=1)
    with patch("video_processor.subprocess.Popen", return_value=proc_fail):
        vp._apply_branding("in.mp4", "out.mp4", settings)
        mock_copy.assert_called_once_with("in.mp4", "out.mp4")

@patch("pathlib.Path.exists")
def test_process_video_not_found_task(mock_exists):
    vp = VideoProcessor()
    # task not found
    assert vp.process_video("nonexistent") is False

@patch("pathlib.Path.exists")
def test_process_video_success(mock_exists, safe_popen_mock):
    vp = VideoProcessor()
    task = vp.create_task("t1", ["v1.mp4", "v2.mp4"], "elegant")
    
    # mock all paths exist
    mock_exists.return_value = True
    
    # mock all sub ffmpeg runs to succeed
    proc = safe_popen_mock(returncode=0)
    
    with patch("video_processor.subprocess.Popen", return_value=proc), \
         patch("video_processor.VideoProcessor._record_soul_narrative") as mock_record, \
         patch("video_processor.time.sleep"):  # speed up tests
        success = vp.process_video("t1")
        assert success is True
        assert task.phase == ProcessingPhase.COMPLETE
        assert task.progress == 100
        mock_record.assert_called_once()

@patch("pathlib.Path.exists")
def test_process_video_demo_fallback(mock_exists, safe_popen_mock):
    vp = VideoProcessor()
    task = vp.create_task("t1", ["nonexistent.mp4"], "elegant")
    
    # Track Path.exists calls by order
    exists_calls = []
    def exists_side_effect():
        exists_calls.append(1)
        if len(exists_calls) == 1:
            return False  # nonexistent.mp4
        return True  # demo directory exists
        
    mock_exists.side_effect = exists_side_effect
    
    # mock glob to return 2 paths so it avoids shutil.copy in _merge_scenes
    mock_glob = MagicMock(return_value=[Path("demo1.mp4"), Path("demo2.mp4")])
    
    proc = safe_popen_mock(returncode=0)
    with patch("video_processor.subprocess.Popen", return_value=proc), \
         patch("pathlib.Path.glob", mock_glob), \
         patch("video_processor.VideoProcessor._record_soul_narrative"), \
         patch("video_processor.time.sleep"):
        success = vp.process_video("t1")
        assert success is True
        assert task.phase == ProcessingPhase.COMPLETE

@patch("pathlib.Path.exists")
def test_process_video_exception(mock_exists):
    vp = VideoProcessor()
    task = vp.create_task("t1", ["v1.mp4"], "elegant")
    mock_exists.side_effect = Exception("Disk error")
    
    success = vp.process_video("t1")
    assert success is False
    assert task.phase == ProcessingPhase.ERROR
    assert "Disk error" in task.error

# template_config configuration active tests
@patch("shutil.copy")
def test_process_scene_with_active_template(mock_copy, safe_popen_mock):
    vp = VideoProcessor()
    settings = MOOD_SETTINGS["elegant"]
    
    proc = safe_popen_mock(returncode=0)
    
    # Mock template_config module instance
    mock_template = MagicMock()
    mock_template.is_active = True
    mock_template.get_color_grading_filter.return_value = "eq=contrast=1.5"
    mock_template.template_id = "test_tmpl"
    
    with patch("video_processor.subprocess.Popen", return_value=proc), \
         patch("template_config.template_config", mock_template):
        vp._process_scene("in.mp4", "out.mp4", settings)
        mock_copy.assert_not_called()
        mock_template.get_color_grading_filter.assert_called_once()




def test_run_ffmpeg_timeout_resource_cleanup():
    """FFmpeg実行中にタイムアウトが発生した際、プロセスがキルされ回収されることを検証"""
    from backend.video_processor import VideoProcessor
    import subprocess
    from unittest.mock import MagicMock, patch
    
    vp = VideoProcessor()
    
    # Popenとプロセスのモック化
    mock_process = MagicMock()
    # process.wait() はタイムアウト時に subprocess.TimeoutExpired を投げる
    mock_process.wait.side_effect = subprocess.TimeoutExpired(cmd="ffmpeg", timeout=60)
    
    with patch("subprocess.Popen", return_value=mock_process):
        success = vp._run_ffmpeg(["ffmpeg", "-i", "input.mp4"], "Timeout Test", timeout=60)
    
    # 処理が失敗(False)を返し、プロセスがキルおよびwaitで回収されたか検証
    assert success is False
    mock_process.kill.assert_called_once()
    # ゾンビプロセス回収のために wait が2回呼び出されたはず（1回目は TimeoutExpired 用、2回目は回収用）
    assert mock_process.wait.call_count == 2
    mock_process.wait.assert_any_call(timeout=5)


def test_get_audio_normalize_args_file_not_found_fallback():
    """音声ノーマライズ計測時に FileNotFoundError (ffmpeg不在など) が発生した場合、1パスへフォールバックすることを検証"""
    from backend.video_processor import VideoProcessor
    from template_config import template_config
    from unittest.mock import patch
    
    vp = VideoProcessor()
    
    # subprocess.run が例外を投げるようにモック
    with patch("subprocess.run", side_effect=FileNotFoundError("ffmpeg not found")):
        with patch.object(template_config, "get_loudnorm_filter", return_value="loudnorm_1pass_filter"):
            args = vp._get_audio_normalize_args("input.mp4")
    
    # 例外が補足され、1パスフィルタが返されているか検証
    assert args == ["-af", "loudnorm_1pass_filter"]


def test_merge_scenes_copy_failed(safe_popen_mock):
    """_merge_scenes でのコピー処理が失敗した際のエラーハンドリングを検証"""
    from backend.video_processor import VideoProcessor
    import shutil
    from unittest.mock import patch

    vp = VideoProcessor()

    # シーン1つの時にコピーが失敗するケース
    with patch("shutil.copy", side_effect=OSError("Copy error")),          patch("pathlib.Path.exists", return_value=True):
        vp._merge_scenes(["s1.mp4"], "out.mp4")

    # 複数シーンマージ失敗時のコピーが失敗するケース
    proc_fail = safe_popen_mock(returncode=1)
    with patch("shutil.copy", side_effect=OSError("Copy error")),          patch("pathlib.Path.exists", return_value=True),          patch("video_processor.subprocess.Popen", return_value=proc_fail),          patch("builtins.open", new_callable=mock_open):
        vp._merge_scenes(["s1.mp4", "s2.mp4"], "out.mp4")


def test_apply_branding_copy_failed():
    """_apply_branding でのコピー処理が失敗した際のエラーハンドリングを検証"""
    from backend.video_processor import VideoProcessor
    import shutil
    from unittest.mock import patch

    vp = VideoProcessor()
    settings = MOOD_SETTINGS["elegant"]

    # ロゴが存在せず、コピーが失敗するケース
    with patch("shutil.copy", side_effect=OSError("Copy error")),          patch("pathlib.Path.exists", return_value=False):
        vp._apply_branding("in.mp4", "out.mp4", settings)

    # ロゴが存在し、FFmpegが失敗した後のコピーが失敗するケース
    with patch("shutil.copy", side_effect=OSError("Copy error")), \
         patch("pathlib.Path.exists", return_value=True):
        with patch.object(vp, "_run_ffmpeg", return_value=False):
            vp._apply_branding("in.mp4", "out.mp4", settings)


def test_run_ffmpeg_timeout_kill_exception():
    """FFmpeg実行中にタイムアウトが発生し、かつキル処理で例外(OSErrorなど)が発生した際に、適切に捕捉されることを検証"""
    from backend.video_processor import VideoProcessor
    import subprocess
    from unittest.mock import MagicMock, patch
    
    vp = VideoProcessor()
    
    # Popenとプロセスのモック化
    mock_process = MagicMock()
    # process.wait() はタイムアウト時に subprocess.TimeoutExpired を投げる
    mock_process.wait.side_effect = subprocess.TimeoutExpired(cmd="ffmpeg", timeout=60)
    mock_process.kill.side_effect = OSError("Access denied")
    
    with patch("subprocess.Popen", return_value=mock_process):
        success = vp._run_ffmpeg(["ffmpeg", "-i", "input.mp4"], "Timeout Kill Exception Test", timeout=60)
    
    # 例外が補足され、処理が失敗(False)を返し、killが呼び出されたことを確認
    assert success is False
    mock_process.kill.assert_called_once()


def test_create_task_validation_errors():
    """create_task メソッドに無効な値が渡された際に ValueError が発生することを検証"""
    vp = VideoProcessor()
    
    # task_id が無効なケース
    with pytest.raises(ValueError, match="task_id must be a non-empty string"):
        vp.create_task("", ["v1.mp4"], "elegant")
    with pytest.raises(ValueError, match="task_id must be a non-empty string"):
        vp.create_task(None, ["v1.mp4"], "elegant")
        
    # video_paths が無効なケース (空、リスト以外、文字列以外の要素を含む)
    with pytest.raises(ValueError, match="video_paths must be a list of strings"):
        vp.create_task("t1", "v1.mp4", "elegant")
    with pytest.raises(ValueError, match="video_paths must not be empty"):
        vp.create_task("t1", [], "elegant")
    with pytest.raises(ValueError, match="all elements in video_paths must be strings"):
        vp.create_task("t1", ["v1.mp4", 123], "elegant")
        
    # mood が無効なケース
    with pytest.raises(ValueError, match="mood must be a non-empty string"):
        vp.create_task("t1", ["v1.mp4"], "")
    with pytest.raises(ValueError, match="mood must be a non-empty string"):
        vp.create_task("t1", ["v1.mp4"], 123)


