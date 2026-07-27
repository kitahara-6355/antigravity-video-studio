import pytest
from unittest.mock import patch, MagicMock
import subprocess
from pathlib import Path
import shutil
import logging
from backend.audio_master import AudioMaster

class MockTemplateConfig:
    def __init__(self, is_active=True, audio_config=None):
        self.is_active = is_active
        self._audio_config = audio_config

    def get_audio_config(self):
        return self._audio_config

def test_init_ffmpeg_found():
    with patch("backend.audio_master.shutil.which", return_value="/usr/bin/ffmpeg"):
        master = AudioMaster()
        assert master.ffmpeg == "/usr/bin/ffmpeg"

def test_init_ffmpeg_local_exists():
    local_dir = Path('./backend/bin')
    local_ffmpeg = local_dir / "ffmpeg.exe"
    
    dir_existed = local_dir.exists()
    file_existed = local_ffmpeg.exists()
    
    if not dir_existed:
        local_dir.mkdir(parents=True, exist_ok=True)
    if not file_existed:
        local_ffmpeg.write_text("")
        
    try:
        with patch("backend.audio_master.shutil.which", return_value=None):
            master = AudioMaster()
            assert master.ffmpeg == str(Path('./backend/bin/ffmpeg.exe'))
    finally:
        if not file_existed and local_ffmpeg.exists():
            local_ffmpeg.unlink()
        if not dir_existed and local_dir.exists():
            try:
                local_dir.rmdir()
            except OSError:
                pass

def test_init_ffmpeg_not_found(caplog):
    with patch("backend.audio_master.shutil.which", return_value=None), \
         patch.object(Path, "exists", return_value=False):
        
        with caplog.at_level(logging.WARNING):
            master = AudioMaster()
            assert master.ffmpeg is None
            assert "AudioMaster: FFmpeg not found" in caplog.text

def test_ensure_ffmpeg():
    with patch("backend.audio_master.shutil.which", return_value=None), \
         patch.object(Path, "exists", return_value=False):
        master = AudioMaster()
        with pytest.raises(RuntimeError, match="AudioMaster: FFmpeg not available"):
            master._ensure_ffmpeg()

def test_verify_file_exists():
    master = AudioMaster()
    with pytest.raises(FileNotFoundError, match="動画ファイルが見つかりません"):
        master._verify_file_exists("non_existent.mp4")
    with pytest.raises(FileNotFoundError, match="Audio file not found"):
        master._verify_file_exists("non_existent.mp3")

def test_run_ffmpeg_error():
    master = AudioMaster()
    master.ffmpeg = "/mock/ffmpeg"
    
    with patch("backend.audio_master.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=["ffmpeg"],
            stderr=b"Some ffmpeg error message"
        )
        with pytest.raises(RuntimeError, match="FFmpeg operation failed: Some ffmpeg error message"):
            master._run_ffmpeg(["ffmpeg"], "testing error")

def test_normalize_loudness(tmp_path):
    input_file = tmp_path / "input.mp3"
    input_file.write_text("dummy")
    
    master = AudioMaster()
    master.ffmpeg = "/mock/ffmpeg"
    master.output_dir = tmp_path
    
    with patch.object(master, "_run_ffmpeg") as mock_run_ffmpeg:
        # 1. target_lufs 指定あり
        out = master.normalize_loudness(str(input_file), target_lufs=-14.0)
        assert Path(out).parent == tmp_path
        cmd = mock_run_ffmpeg.call_args[0][0]
        assert "loudnorm=I=-14.0:TP=-1.5:LRA=11" in cmd[4]
        
        # 2. target_lufs なし、template_config なし -> デフォルト -16.0
        master.normalize_loudness(str(input_file))
        cmd = mock_run_ffmpeg.call_args[0][0]
        assert "loudnorm=I=-16.0:TP=-1.5:LRA=11" in cmd[4]
        
        # 3. target_lufs なし、template_config 有効かつ設定あり
        cfg = MockTemplateConfig(is_active=True, audio_config={"target_lufs": -12.0})
        master.normalize_loudness(str(input_file), template_config=cfg)
        cmd = mock_run_ffmpeg.call_args[0][0]
        assert "loudnorm=I=-12.0:TP=-1.5:LRA=11" in cmd[4]

        # 4. target_lufs なし、template_config 有効だが設定が辞書ではない
        cfg_invalid = MockTemplateConfig(is_active=True, audio_config="not a dict")
        master.normalize_loudness(str(input_file), template_config=cfg_invalid)
        cmd = mock_run_ffmpeg.call_args[0][0]
        assert "loudnorm=I=-16.0:TP=-1.5:LRA=11" in cmd[4]
        
        # 5. target_lufs なし、template_config 無効
        cfg_inactive = MockTemplateConfig(is_active=False)
        master.normalize_loudness(str(input_file), template_config=cfg_inactive)
        cmd = mock_run_ffmpeg.call_args[0][0]
        assert "loudnorm=I=-16.0:TP=-1.5:LRA=11" in cmd[4]

def test_remove_noise(tmp_path):
    input_file = tmp_path / "input.mp3"
    input_file.write_text("dummy")
    
    master = AudioMaster()
    master.ffmpeg = "/mock/ffmpeg"
    master.output_dir = tmp_path
    
    with patch.object(master, "_run_ffmpeg") as mock_run_ffmpeg:
        master.remove_noise(str(input_file), noise_reduction=0.5)
        assert "afftdn=nr=50:nf=-25" in mock_run_ffmpeg.call_args[0][0][4]
        
        master.remove_noise(str(input_file), noise_reduction=-0.5)
        assert "afftdn=nr=1:nf=-25" in mock_run_ffmpeg.call_args[0][0][4]
        
        master.remove_noise(str(input_file), noise_reduction=1.5)
        assert "afftdn=nr=97:nf=-25" in mock_run_ffmpeg.call_args[0][0][4]

def test_duck_bgm(tmp_path):
    voice_file = tmp_path / "voice.mp3"
    voice_file.write_text("dummy")
    bgm_file = tmp_path / "bgm.mp3"
    bgm_file.write_text("dummy")
    
    master = AudioMaster()
    master.ffmpeg = "/mock/ffmpeg"
    master.output_dir = tmp_path
    
    with patch.object(master, "_run_ffmpeg") as mock_run_ffmpeg:
        master.duck_bgm(str(voice_file), str(bgm_file), duck_amount=0.3)
        filter_str = mock_run_ffmpeg.call_args[0][0][6]
        assert "threshold=0.3:ratio=3" in filter_str
        
        master.duck_bgm(str(voice_file), str(bgm_file), duck_amount=0.0)
        filter_str = mock_run_ffmpeg.call_args[0][0][6]
        assert "threshold=0.0001:ratio=20" in filter_str
        
        master.duck_bgm(str(voice_file), str(bgm_file), duck_amount=2.0)
        filter_str = mock_run_ffmpeg.call_args[0][0][6]
        assert "threshold=1.0:ratio=1" in filter_str

def test_apply_filter(tmp_path):
    input_file = tmp_path / "input.mp3"
    input_file.write_text("dummy")
    
    master = AudioMaster()
    master.ffmpeg = "/mock/ffmpeg"
    master.output_dir = tmp_path
    
    with patch.object(master, "_run_ffmpeg") as mock_run_ffmpeg:
        master.apply_filter(str(input_file), filter_type="highpass", cutoff=150.0)
        assert "highpass=f=150.0" in mock_run_ffmpeg.call_args[0][0][4]
        
        master.apply_filter(str(input_file), filter_type="lowpass", cutoff=3000.0)
        assert "lowpass=f=3000.0" in mock_run_ffmpeg.call_args[0][0][4]
        
    with pytest.raises(ValueError, match="Invalid filter_type"):
        master.apply_filter(str(input_file), filter_type="midpass", cutoff=100.0)
        
    with pytest.raises(ValueError, match="Cutoff frequency must be greater than 0"):
        master.apply_filter(str(input_file), filter_type="highpass", cutoff=0.0)
        
    with pytest.raises(ValueError, match="Cutoff frequency must be greater than 0"):
        master.apply_filter(str(input_file), filter_type="highpass", cutoff=-10.0)

def test_master_audio(tmp_path):
    input_file = tmp_path / "input.mp3"
    input_file.write_text("dummy")
    
    master = AudioMaster()
    master.ffmpeg = "/mock/ffmpeg"
    master.output_dir = tmp_path
    
    with patch.object(master, "apply_filter", return_value="filtered.mp3") as mock_filter, \
         patch.object(master, "remove_noise", return_value="denoised.mp3") as mock_denoise, \
         patch.object(master, "normalize_loudness", return_value="normalized.mp3") as mock_norm:
         
        out = master.master_audio(
            audio_path=str(input_file),
            normalize=True,
            denoise=True,
            target_lufs=-14.0,
            noise_reduction=0.3,
            highpass_cutoff=100.0,
            lowpass_cutoff=8000.0
        )
        
        assert out == "normalized.mp3"
        mock_filter.assert_any_call(str(input_file), "highpass", 100.0)
        mock_filter.assert_any_call("filtered.mp3", "lowpass", 8000.0)
        mock_denoise.assert_called_once_with("filtered.mp3", 0.3)
        mock_norm.assert_called_once_with("denoised.mp3", -14.0, None)

def test_process_audio_only(tmp_path):
    input_file = tmp_path / "input.mp3"
    input_file.write_text("dummy")
    
    master = AudioMaster()
    master.ffmpeg = "/mock/ffmpeg"
    master.output_dir = tmp_path
    
    with patch.object(master, "master_audio", return_value="mastered.mp3") as mock_master:
        out = master.process(str(input_file), normalize=True, denoise=True)
        assert out == "mastered.mp3"
        mock_master.assert_called_once()

def test_process_video(tmp_path):
    input_video = tmp_path / "input.mp4"
    input_video.write_text("dummy")
    
    master = AudioMaster()
    master.ffmpeg = "/mock/ffmpeg"
    master.output_dir = tmp_path
    
    mastered_audio = tmp_path / "temp_mastered.mp3"
    mastered_audio.write_text("dummy mastered")
    
    with patch.object(master, "master_audio", return_value=str(mastered_audio)) as mock_master, \
         patch.object(master, "_run_ffmpeg") as mock_run_ffmpeg:
         
        out = master.process(str(input_video))
        assert out.endswith(".mp4")
        mock_run_ffmpeg.assert_called_once()
        assert not mastered_audio.exists()

def test_process_video_unlink_error(tmp_path):
    input_video = tmp_path / "input.mp4"
    input_video.write_text("dummy")
    
    master = AudioMaster()
    master.ffmpeg = "/mock/ffmpeg"
    master.output_dir = tmp_path
    
    mastered_audio = tmp_path / "temp_mastered.mp3"
    mastered_audio.write_text("dummy mastered")
    
    import pathlib
    with patch.object(master, "master_audio", return_value=str(mastered_audio)),          patch.object(master, "_run_ffmpeg"),          patch.object(pathlib.WindowsPath, "unlink", side_effect=OSError("Permission denied")),          patch.object(pathlib.PosixPath, "unlink", side_effect=OSError("Permission denied")):
         
        out = master.process(str(input_video))
        assert out.endswith(".mp4")


def test_master_audio_with_none_and_false(tmp_path):
    input_file = tmp_path / "input.mp3"
    input_file.write_text("dummy")
    
    master = AudioMaster()
    master.ffmpeg = "/mock/ffmpeg"
    master.output_dir = tmp_path
    
    with patch.object(master, "apply_filter") as mock_filter,          patch.object(master, "remove_noise") as mock_denoise,          patch.object(master, "normalize_loudness") as mock_norm:
         
        out = master.master_audio(
            audio_path=str(input_file),
            normalize=False,
            denoise=False,
            highpass_cutoff=None,
            lowpass_cutoff=None
        )
        
        assert out == str(input_file)
        mock_filter.assert_not_called()
        mock_denoise.assert_not_called()
        mock_norm.assert_not_called()


def test_audio_master_module_reload_no_ffmpeg():
    import importlib
    import backend.audio_master
    
    with patch("backend.audio_master.shutil.which", return_value=None),          patch("backend.audio_master.Path.exists", return_value=False):
        importlib.reload(backend.audio_master)
        assert backend.audio_master.audio_master.ffmpeg is None


def test_audio_master_module_reload_local_ffmpeg_exists():
    import importlib
    import backend.audio_master
    
    with patch("backend.audio_master.shutil.which", return_value=None),          patch("backend.audio_master.Path.exists", return_value=True):
        importlib.reload(backend.audio_master)
        assert backend.audio_master.audio_master.ffmpeg == str(Path('./backend/bin/ffmpeg.exe'))


def test_print_module_path():
    import backend.audio_master
    print(f"DEBUG_MODULE_PATH: {backend.audio_master.__file__}")


def test_process_video_temp_audio_not_exists(tmp_path):
    input_video = tmp_path / "input.mp4"
    input_video.write_text("dummy")
    
    master = AudioMaster()
    master.ffmpeg = "/mock/ffmpeg"
    master.output_dir = tmp_path
    
    non_existent_audio = tmp_path / "non_existent_temp.mp3"
    
    with patch.object(master, "master_audio", return_value=str(non_existent_audio)),          patch.object(master, "_run_ffmpeg"):
         
        out = master.process(str(input_video))
        assert out.endswith(".mp4")



def test_verify_file_exists_extended_formats():
    master = AudioMaster()
    formats = [".webm", ".mkv", ".avi", ".mov", ".flv"]
    for fmt in formats:
        with pytest.raises(FileNotFoundError, match="動画ファイルが見つかりません"):
            master._verify_file_exists(f"non_existent{fmt}")

def test_process_video_unlink_error_logs(tmp_path, caplog):
    input_video = tmp_path / "input.mp4"
    input_video.write_text("dummy")
    
    master = AudioMaster()
    master.ffmpeg = "/mock/ffmpeg"
    master.output_dir = tmp_path
    
    mastered_audio = tmp_path / "temp_mastered.mp3"
    mastered_audio.write_text("dummy mastered")
    
    with patch.object(master, "master_audio", return_value=str(mastered_audio)),          patch.object(master, "_run_ffmpeg"),          patch.object(Path, "unlink", side_effect=OSError("Permission denied")):
         
        with caplog.at_level(logging.WARNING):
            out = master.process(str(input_video))
            assert out.endswith(".mp4")
            assert "Failed to remove temporary mastered audio" in caplog.text
