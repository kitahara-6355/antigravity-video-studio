import sys
from unittest.mock import MagicMock

# Inject dummy modules to prevent ModuleNotFoundError when auto_full_build is imported
sys.modules['graded_previews'] = MagicMock()
sys.modules['graded_previews.youtuber_grade_scorer'] = MagicMock()

import os
import shutil
import subprocess
import pytest
from unittest.mock import patch, MagicMock
from backend.silence_trimmer import detect_silence, trim_silence_and_srt, SilenceDetectionError, VideoTrimError

@patch("os.path.exists")
@patch("subprocess.run")
def test_detect_silence_success(mock_run, mock_exists):
    mock_exists.return_value = True
    
    # ffmpeg silencedetect の出力をシミュレート
    mock_stderr = """
[silencedetect @ 000001f234567890] silence_start: 10.5
[silencedetect @ 000001f234567890] silence_end: 15.5 | silence_duration: 5.0
[silencedetect @ 000001f234567890] silence_start: 30.0
[silencedetect @ 000001f234567890] silence_end: 32.5 | silence_duration: 2.5
    """
    mock_run.return_value = MagicMock(stdout="", stderr=mock_stderr, returncode=0)
    
    silences = detect_silence("dummy.mp4")
    
    assert len(silences) == 2
    assert silences[0]["start"] == 10.5
    assert silences[0]["end"] == 15.5
    assert silences[0]["duration"] == 5.0
    assert silences[1]["start"] == 30.0
    assert silences[1]["end"] == 32.5
    assert silences[1]["duration"] == 2.5


@patch("os.path.exists")
@patch("shutil.copy2")
@patch("backend.silence_trimmer.detect_silence")
def test_trim_silence_and_srt_no_silence(mock_detect, mock_copy, mock_exists):
    mock_exists.return_value = True
    mock_detect.return_value = []
    
    trim_silence_and_srt(
        video_path="input.mp4",
        srt_path="input.srt",
        output_video_path="output.mp4",
        output_srt_path="output.srt"
    )
    
    # 無音がないので直接コピーされる
    assert mock_copy.call_count == 2
    mock_copy.assert_any_call("input.mp4", "output.mp4")
    mock_copy.assert_any_call("input.srt", "output.srt")


@patch("os.path.exists")
@patch("subprocess.run")
@patch("backend.silence_trimmer.detect_silence")
@patch("video_editor_engine.video_editor.ffmpeg.get_duration")
@patch("auto_full_build.parse_srt")
@patch("auto_full_build.write_srt")
def test_trim_silence_and_srt_with_silence(
    mock_write_srt, mock_parse_srt, mock_get_duration, mock_detect, mock_run, mock_exists
):
    mock_exists.return_value = True
    
    # 10.0秒から15.0秒（長さ5.0秒）の無音を検出
    # min_silence_len=1.5, keep_silence_len=0.5 のため、
    # 削る部分は 10.25秒から 14.75秒（4.5秒間）
    mock_detect.return_value = [{
        "start": 10.0,
        "end": 15.0,
        "duration": 5.0
    }]
    
    # 動画全体の長さを 30.0秒 とする
    mock_get_duration.return_value = 30.0
    
    # 元のSRTセグメント
    # 1. 0.0s - 5.0s (カット前、変化なし)
    # 2. 12.0s - 13.0s (カット区間内部、削られる部分なので c_start に寄せて消滅する)
    # 3. 20.0s - 25.0s (カット後、-4.5秒される -> 15.5s - 20.5s)
    mock_parse_srt.return_value = [
        {"start": 0.0, "end": 5.0, "text": "Hello"},
        {"start": 12.0, "end": 13.0, "text": "Silence"},
        {"start": 20.0, "end": 25.0, "text": "World"}
    ]
    
    trim_silence_and_srt(
        video_path="input.mp4",
        srt_path="input.srt",
        output_video_path="output.mp4",
        output_srt_path="output.srt",
        noise_db=-40,
        min_silence_len=1.5,
        keep_silence_len=0.5
    )
    
    # FFmpeg の trim コマンドが実行されたことを確認
    # (subprocess.run は ffmpeg の1回のみ)
    assert mock_run.call_count == 1
    
    # write_srt が呼び出され、タイムスタンプが調整されていることを検証
    mock_write_srt.assert_called_once()
    adjusted_segs = mock_write_srt.call_args[0][0]
    
    # 2番目のセグメントは new_end - new_start < 0.1 のため除外されている
    assert len(adjusted_segs) == 2
    
    # 1つ目のセグメント
    assert adjusted_segs[0]["start"] == 0.0
    assert adjusted_segs[0]["end"] == 5.0
    assert adjusted_segs[0]["text"] == "Hello"
    
    # 2つ目のセグメント (元の3つ目、20.0 - 4.5 = 15.5)
    assert adjusted_segs[1]["start"] == pytest.approx(15.5)
    assert adjusted_segs[1]["end"] == pytest.approx(20.5)
    assert adjusted_segs[1]["text"] == "World"


def test_detect_silence_video_not_found():
    with pytest.raises(FileNotFoundError):
        detect_silence("non_existent_video.mp4")


@patch("os.path.exists")
@patch("subprocess.run")
def test_detect_silence_ffmpeg_error(mock_run, mock_exists):
    mock_exists.return_value = True
    # subprocess.run が CalledProcessError を発生させるようにモック
    mock_run.side_effect = subprocess.CalledProcessError(
        returncode=1,
        cmd="ffmpeg",
        stderr="Mock error"
    )
    
    with pytest.raises(SilenceDetectionError):
        detect_silence("dummy.mp4")


def test_trim_silence_and_srt_video_not_found():
    with pytest.raises(FileNotFoundError):
        trim_silence_and_srt(
            video_path="non_existent_video.mp4",
            srt_path="dummy.srt",
            output_video_path="output.mp4",
            output_srt_path="output.srt"
        )


@patch("os.path.exists")
@patch("subprocess.run")
@patch("backend.silence_trimmer.detect_silence")
@patch("video_editor_engine.video_editor.ffmpeg.get_duration")
@patch("auto_full_build.parse_srt")
@patch("auto_full_build.write_srt")
def test_trim_silence_and_srt_duration_fallback_success(
    mock_write_srt, mock_parse_srt, mock_get_duration, mock_detect, mock_run, mock_exists
):
    mock_exists.return_value = True
    
    mock_detect.return_value = [{
        "start": 10.0,
        "end": 15.0,
        "duration": 5.0
    }]
    
    # video_editor からの取得で AttributeError を投げ、フォールバックをトリガー
    mock_get_duration.side_effect = AttributeError("Mock attribute error")
    
    # ffprobe と ffmpeg trim の2回 subprocess.run が呼ばれる
    mock_run.side_effect = [
        MagicMock(stdout="30.0\n", stderr="", returncode=0), # ffprobe
        MagicMock(stdout="", stderr="", returncode=0)        # ffmpeg trim
    ]
    
    mock_parse_srt.return_value = [
        {"start": 0.0, "end": 5.0, "text": "Hello"},
        {"start": 20.0, "end": 25.0, "text": "World"}
    ]
    
    trim_silence_and_srt(
        video_path="input.mp4",
        srt_path="input.srt",
        output_video_path="output.mp4",
        output_srt_path="output.srt",
        noise_db=-40,
        min_silence_len=1.5,
        keep_silence_len=0.5
    )
    
    assert mock_run.call_count == 2
    mock_write_srt.assert_called_once()


@patch("os.path.exists")
@patch("subprocess.run")
@patch("backend.silence_trimmer.detect_silence")
@patch("video_editor_engine.video_editor.ffmpeg.get_duration")
@patch("auto_full_build.parse_srt")
@patch("auto_full_build.write_srt")
def test_trim_silence_and_srt_duration_fallback_failure(
    mock_write_srt, mock_parse_srt, mock_get_duration, mock_detect, mock_run, mock_exists
):
    mock_exists.return_value = True
    
    mock_detect.return_value = [{
        "start": 10.0,
        "end": 15.0,
        "duration": 5.0
    }]
    
    # video_editor からの取得失敗
    mock_get_duration.side_effect = ValueError("Mock value error")
    
    # ffprobe がエラーを返す、および ffmpeg trim は正常終了
    mock_run.side_effect = [
        subprocess.CalledProcessError(returncode=1, cmd="ffprobe", stderr="Mock ffprobe error"), # ffprobe 失敗
        MagicMock(stdout="", stderr="", returncode=0)                                            # ffmpeg trim
    ]
    
    mock_parse_srt.return_value = [
        {"start": 0.0, "end": 5.0, "text": "Hello"},
        {"start": 20.0, "end": 25.0, "text": "World"}
    ]
    
    trim_silence_and_srt(
        video_path="input.mp4",
        srt_path="input.srt",
        output_video_path="output.mp4",
        output_srt_path="output.srt",
        noise_db=-40,
        min_silence_len=1.5,
        keep_silence_len=0.5
    )
    
    # ffprobe失敗により、duration = 9999.0 にフォールバックされる
    assert mock_run.call_count == 2
    mock_write_srt.assert_called_once()


@patch("os.path.exists")
@patch("subprocess.run")
@patch("backend.silence_trimmer.detect_silence")
@patch("video_editor_engine.video_editor.ffmpeg.get_duration")
def test_trim_silence_and_srt_ffmpeg_trim_error(
    mock_get_duration, mock_detect, mock_run, mock_exists
):
    mock_exists.return_value = True
    
    mock_detect.return_value = [{
        "start": 10.0,
        "end": 15.0,
        "duration": 5.0
    }]
    
    mock_get_duration.return_value = 30.0
    
    # subprocess.run (ffmpeg trim) でエラーを発生させる
    mock_run.side_effect = subprocess.CalledProcessError(
        returncode=1,
        cmd="ffmpeg trim",
        stderr="Mock ffmpeg trim error"
    )
    
    with pytest.raises(VideoTrimError):
        trim_silence_and_srt(
            video_path="input.mp4",
            srt_path="input.srt",
            output_video_path="output.mp4",
            output_srt_path="output.srt",
            noise_db=-40,
            min_silence_len=1.5,
            keep_silence_len=0.5
        )


@patch("os.path.exists")
@patch("subprocess.run")
def test_detect_silence_unmatched_counts(mock_run, mock_exists):
    mock_exists.return_value = True
    
    # silence_start が3個に対し、silence_end が2個の不一致ケース
    mock_stderr = """
[silencedetect @ 000001f234567890] silence_start: 10.5
[silencedetect @ 000001f234567890] silence_end: 15.5 | silence_duration: 5.0
[silencedetect @ 000001f234567890] silence_start: 30.0
[silencedetect @ 000001f234567890] silence_end: 32.5 | silence_duration: 2.5
[silencedetect @ 000001f234567890] silence_start: 40.0
    """
    mock_run.return_value = MagicMock(stdout="", stderr=mock_stderr, returncode=0)
    
    silences = detect_silence("dummy.mp4")
    
    # 小さい方の個数 (2個) に制限されることを確認
    assert len(silences) == 2
    assert silences[0]["start"] == 10.5
    assert silences[1]["start"] == 30.0


@patch("os.path.exists")
@patch("shutil.copy2")
@patch("backend.silence_trimmer.detect_silence")
def test_trim_silence_and_srt_keep_greater_than_duration(mock_detect, mock_copy, mock_exists):
    mock_exists.return_value = True
    # 無音長 1.6 秒（min_silence_len=1.5 より大きい）
    # しかし keep_silence_len = 2.0 に設定されているため、
    # trim_start (10.0 + 1.0 = 11.0) >= trim_end (11.6 - 1.0 = 10.6) となり、
    # トリミング対象区間（cut_ranges）に追加されず、直接コピーされる。
    mock_detect.return_value = [{
        "start": 10.0,
        "end": 11.6,
        "duration": 1.6
    }]
    
    trim_silence_and_srt(
        video_path="input.mp4",
        srt_path="input.srt",
        output_video_path="output.mp4",
        output_srt_path="output.srt",
        min_silence_len=1.5,
        keep_silence_len=2.0
    )
    
    assert mock_copy.call_count == 2


@patch("os.path.exists")
@patch("shutil.copy2")
@patch("backend.silence_trimmer.detect_silence")
def test_trim_silence_and_srt_no_silence_no_srt_file(mock_detect, mock_copy, mock_exists):
    # video_path は存在するが、srt_path は存在しないケース
    def exists_side_effect(path):
        if path == "input.mp4":
            return True
        return False
    mock_exists.side_effect = exists_side_effect
    mock_detect.return_value = []
    
    trim_silence_and_srt(
        video_path="input.mp4",
        srt_path="input.srt",
        output_video_path="output.mp4",
        output_srt_path="output.srt"
    )
    
    # ビデオのみコピーされ、SRTはコピーされないことを確認
    assert mock_copy.call_count == 1
    mock_copy.assert_called_once_with("input.mp4", "output.mp4")


@patch("os.path.exists")
@patch("subprocess.run")
@patch("backend.silence_trimmer.detect_silence")
@patch("video_editor_engine.video_editor.ffmpeg.get_duration")
@patch("auto_full_build.parse_srt")
@patch("auto_full_build.write_srt")
def test_trim_silence_and_srt_srt_overlap(
    mock_write_srt, mock_parse_srt, mock_get_duration, mock_detect, mock_run, mock_exists
):
    mock_exists.return_value = True
    
    # 10.0秒から15.0秒（長さ5.0秒）の無音を検出
    # min_silence_len=1.5, keep_silence_len=0.5 のため、
    # 削る部分は 10.25秒から 14.75秒（4.5秒間）
    mock_detect.return_value = [{
        "start": 10.0,
        "end": 15.0,
        "duration": 5.0
    }]
    
    # 動画全体の長さを 30.0秒 とする
    mock_get_duration.return_value = 30.0
    
    # 元のSRTセグメント
    # 1. 8.0s - 12.0s (トリミング区間 10.25 - 14.75 に跨る)
    #    start (8.0) -> シフトなし = 8.0
    #    end (12.0) -> 10.25〜12.0の部分がシフト調整対象 -> 12.0 - (12.0 - 10.25) = 10.25
    #    new_start: 8.0, new_end: 10.25 (new_end > new_start + 0.1) -> 残る
    # 2. 12.0s - 16.0s (トリミング区間 10.25 - 14.75 に跨る)
    #    start (12.0) -> 12.0 - (12.0 - 10.25) = 10.25
    #    end (16.0) -> 16.0 - 4.5 = 11.5
    #    new_start: 10.25, new_end: 11.5 -> 残る
    # 3. 11.0s - 14.0s (トリミング区間に完全に含まれる)
    #    start (11.0) -> 11.0 - (11.0 - 10.25) = 10.25
    #    end (14.0) -> 14.0 - (14.0 - 10.25) = 10.25
    #    new_start: 10.25, new_end: 10.25 (逆転/短いので除外)
    mock_parse_srt.return_value = [
        {"start": 8.0, "end": 12.0, "text": "Overlap1"},
        {"start": 12.0, "end": 16.0, "text": "Overlap2"},
        {"start": 11.0, "end": 14.0, "text": "Overlap3"}
    ]
    
    trim_silence_and_srt(
        video_path="input.mp4",
        srt_path="input.srt",
        output_video_path="output.mp4",
        output_srt_path="output.srt",
        min_silence_len=1.5,
        keep_silence_len=0.5
    )
    
    adjusted_segs = mock_write_srt.call_args[0][0]
    
    assert len(adjusted_segs) == 2
    
    # Overlap1
    assert adjusted_segs[0]["start"] == 8.0
    assert adjusted_segs[0]["end"] == pytest.approx(10.25)
    assert adjusted_segs[0]["text"] == "Overlap1"
    
    # Overlap2
    assert adjusted_segs[1]["start"] == pytest.approx(10.25)
    assert adjusted_segs[1]["end"] == pytest.approx(11.5)
    assert adjusted_segs[1]["text"] == "Overlap2"



@patch("os.path.exists")
@patch("subprocess.run")
def test_detect_silence_ffmpeg_os_error(mock_run, mock_exists):
    mock_exists.return_value = True
    mock_run.side_effect = OSError("Mock OS error")
    
    with pytest.raises(SilenceDetectionError):
        detect_silence("dummy.mp4")


@patch("os.path.exists")
@patch("backend.silence_trimmer.detect_silence")
def test_trim_silence_and_srt_detect_error(mock_detect, mock_exists):
    mock_exists.return_value = True
    mock_detect.side_effect = SilenceDetectionError("Detection failed")
    
    with pytest.raises(SilenceDetectionError):
        trim_silence_and_srt(
            video_path="input.mp4",
            srt_path="input.srt",
            output_video_path="output.mp4",
            output_srt_path="output.srt"
        )
