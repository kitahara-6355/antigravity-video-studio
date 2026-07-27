import pytest
import subprocess
from pathlib import Path
import json
from unittest.mock import MagicMock, patch
from backend.video_pipeline.audio_extractor import AudioExtractor, AudioResult

@pytest.fixture(scope="module")
def dummy_media(tmp_path_factory):
    """FFmpegを使用してテスト用の各種ダミーファイルを作成する"""
    tmp_dir = tmp_path_factory.mktemp("media")
    
    # 1. 音声あり動画 (2秒, stereo, 44100Hz)
    video_with_audio = tmp_dir / "video_with_audio.mp4"
    cmd1 = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=10",
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=2",
        "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
        str(video_with_audio)
    ]
    subprocess.run(cmd1, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # 2. 音声なし動画 (2秒)
    video_no_audio = tmp_dir / "video_no_audio.mp4"
    cmd2 = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=10",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(video_no_audio)
    ]
    subprocess.run(cmd2, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 3. 非常に短い動画 (0.1秒)
    video_short = tmp_dir / "video_short.mp4"
    cmd3 = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=0.1:size=320x240:rate=10",
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=0.1",
        "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
        str(video_short)
    ]
    subprocess.run(cmd3, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 4. 特殊文字やスペースを含むファイル名
    video_special_char = tmp_dir / "video space & special [char].mp4"
    cmd4 = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=10",
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=1",
        "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
        str(video_special_char)
    ]
    subprocess.run(cmd4, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 5. 音声のみのファイル (WAV, 2秒, stereo)
    audio_only = tmp_dir / "audio_only.wav"
    cmd5 = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=2:sample_rate=44100",
        "-ac", "2",
        str(audio_only)
    ]
    subprocess.run(cmd5, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 6. 壊れたファイル (テキストファイルをmp4として偽装)
    corrupted_file = tmp_dir / "corrupted.mp4"
    corrupted_file.write_text("This is not a video file.")

    return {
        "video_with_audio": str(video_with_audio),
        "video_no_audio": str(video_no_audio),
        "video_short": str(video_short),
        "video_special_char": str(video_special_char),
        "audio_only": str(audio_only),
        "corrupted": str(corrupted_file),
        "non_existent": str(tmp_dir / "non_existent.mp4")
    }


# 正常系、境界値、異常系を含むパラメータ化テストケース
@pytest.mark.parametrize(
    "case_name, file_key, expected_success, expected_format, expected_channels, expected_sample_rate",
    [
        ("正常系: 音声あり動画", "video_with_audio", True, "wav", 2, 44100),
        ("正常系: 音声のみファイル", "audio_only", True, "wav", 2, 44100),
        ("境界値: 短い動画(0.1s)", "video_short", True, "wav", 2, 44100),
        ("境界値: 特殊文字ファイル名", "video_special_char", True, "wav", 2, 44100),
        ("異常系: 存在しないパス", "non_existent", False, "", 0, 0),
        ("異常系: 音声なし動画", "video_no_audio", False, "", 0, 0),
        ("異常系: 壊れた動画ファイル", "corrupted", False, "", 0, 0),
        ("異常系: 空パス", "empty_path", False, "", 0, 0)
    ]
)
def test_audio_extractor_cases(
    case_name, file_key, expected_success, expected_format, expected_channels, expected_sample_rate,
    dummy_media, tmp_path
):
    extractor = AudioExtractor(output_dir=str(tmp_path))
    
    # 入力ファイルパスの設定
    if file_key == "empty_path":
        video_path = ""
    else:
        video_path = dummy_media[file_key]
        
    result = extractor.extract(video_path)
    
    assert result.success == expected_success, f"Failed case: {case_name}. Error: {result.error}"
    
    if expected_success:
        assert Path(result.audio_path).exists()
        assert result.format == expected_format
        assert result.channels == expected_channels
        assert result.sample_rate == expected_sample_rate
        assert result.duration_seconds > 0.0
        
        # チャンネル分離のテスト (正常系: split_channels -> L/R分離)
        channel_files = extractor.split_channels(result.audio_path)
        assert len(channel_files) == 2
        for f in channel_files:
            assert Path(f).exists()
    else:
        assert not result.audio_path


def test_safe_popen_mock_behavior(safe_popen_mock, tmp_path):
    """safe_popen_mock fixture を使用した、安全なモック動作のテスト"""
    extractor = AudioExtractor(output_dir=str(tmp_path))
    
    # 存在するダミーファイルを一時的に作成しておく（存在チェックを通過させるため）
    dummy_file = tmp_path / "mock_test_video.mp4"
    dummy_file.write_text("dummy video content")
    
    # safe_popen_mock が有効な場合、ffprobe/ffmpegの実行はモックされる。
    # safe_popen_mock は stdout.readline.return_value = "" を返すため、
    # _get_audio_stream_info 内の json.loads(res.stdout) は json.JSONDecodeError で失敗し、
    # 最終的に success=False を返すはず。
    result = extractor.extract(str(dummy_file))
    
    assert result.success is False
    assert "取得に失敗しました" in result.error or "音声ストリーム" in result.error


def test_mocked_ffprobe_success(tmp_path):
    """ffprobe/ffmpeg の呼び出しを完全にモックした正常系テスト"""
    extractor = AudioExtractor(output_dir=str(tmp_path))
    dummy_file = tmp_path / "mock_success.mp4"
    dummy_file.write_text("dummy")

    # ffprobe の戻り値をモック
    mock_ffprobe_res = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=json.dumps({
            "streams": [{
                "codec_type": "audio",
                "duration": "15.75",
                "sample_rate": "44100",
                "channels": 2
            }]
        }),
        stderr=""
    )

    with patch.object(extractor, "_run_ffprobe", return_value=mock_ffprobe_res) as mock_ffprobe, \
         patch.object(extractor, "_run_ffmpeg", return_value=subprocess.CompletedProcess([], 0)) as mock_ffmpeg:
         
        result = extractor.extract(str(dummy_file))
        
        assert result.success is True
        assert result.format == "wav"
        assert result.sample_rate == 44100
        assert result.channels == 2
        assert result.duration_seconds == 15.75
        
        mock_ffprobe.assert_called_once()
        mock_ffmpeg.assert_called_once()


def test_split_channels_error_handling(tmp_path):
    """split_channels 内の FFmpeg 実行エラーのハンドリングテスト"""
    extractor = AudioExtractor(output_dir=str(tmp_path))
    dummy_audio = tmp_path / "dummy_audio.wav"
    dummy_audio.write_text("dummy wav")
    
    # 実行がエラーを投げるようにモック
    with patch.object(extractor, "_run_ffmpeg", side_effect=subprocess.CalledProcessError(1, "ffmpeg")):
        channel_files = extractor.split_channels(str(dummy_audio))
        assert isinstance(channel_files, list)
