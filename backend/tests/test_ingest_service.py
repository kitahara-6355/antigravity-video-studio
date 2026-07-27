import os
import sys
from pathlib import Path
from unittest.mock import patch
import pytest

# パス設定 (conftestで設定されるが、安全のため)
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from video_pipeline.ingest_service import IngestService, IngestResult, NormalizedMedia

# テスト動画のパス
FIXTURE_DIR = Path(backend_dir) / "tests" / "fixtures" / "raw_videos"
TEST_SHORT = FIXTURE_DIR / "test_short_15s.mp4"
TEST_MEDIUM = FIXTURE_DIR / "test_medium_30s.mp4"
TEST_LONG = FIXTURE_DIR / "test_long_60s.mp4"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# パラメータ化テスト用の入力データ設計 (6-10ケース)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@pytest.mark.parametrize(
    "file_type, expected_success, error_substring",
    [
        ("short_15s", True, None),            # 正常系1
        ("medium_30s", True, None),           # 正常系2
        ("long_60s", True, None),            # 正常系3
        ("non_existent", False, "ファイルが存在しません"), # 異常系1
        ("invalid_ext", False, "サポートされていない拡張子"),  # 異常系2
        ("zero_byte_video", False, "ファイルサイズが0バイトです"), # 境界値1
        ("zero_byte_audio", False, "ファイルサイズが0バイトです"), # 境界値2
    ]
)
def test_validate_input_cases(tmp_path, file_type, expected_success, error_substring):
    """validate_input の正常系、異常系、境界値に対するパラメータ化テスト"""
    service = IngestService(output_dir=str(tmp_path))
    
    # テスト対象ファイルの準備
    if file_type == "short_15s":
        target_path = str(TEST_SHORT)
    elif file_type == "medium_30s":
        target_path = str(TEST_MEDIUM)
    elif file_type == "long_60s":
        target_path = str(TEST_LONG)
    elif file_type == "non_existent":
        target_path = str(tmp_path / "non_existent_file.mp4")
    elif file_type == "invalid_ext":
        # 存在するがサポート外の拡張子
        invalid_file = tmp_path / "dummy.txt"
        invalid_file.write_text("dummy content")
        target_path = str(invalid_file)
    elif file_type == "zero_byte_video":
        # 0バイトのMP4ファイル
        zero_file = tmp_path / "zero.mp4"
        zero_file.write_bytes(b"")
        target_path = str(zero_file)
    elif file_type == "zero_byte_audio":
        # 0バイトのWAVファイル
        zero_file = tmp_path / "zero.wav"
        zero_file.write_bytes(b"")
        target_path = str(zero_file)
    else:
        pytest.fail(f"不明なファイルタイプ: {file_type}")
        
    result = service.validate_input(target_path)
    
    assert result.success == expected_success
    assert result.original_path == target_path
    
    if expected_success:
        assert result.error == ""
        assert result.file_size_bytes > 0
    else:
        assert result.error != ""
        if error_substring:
            assert error_substring in result.error


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# safe_popen_mock を使用したモックテスト
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def test_ingest_with_safe_popen_mock(tmp_path, safe_popen_mock):
    """safe_popen_mock を使用して、実際のFFmpeg呼び出しを行わずに ingest の流れを検証する"""
    service = IngestService(output_dir=str(tmp_path))
    
    # 正常なダミー入力ファイルを用意 (10バイト)
    dummy_input = tmp_path / "dummy_input.mp4"
    dummy_input.write_bytes(b"\x00" * 10)
    
    # Popen モックの準備
    proc = safe_popen_mock(returncode=0, stdout_text="ffmpeg version 4.4", stderr_text="")
    proc.communicate.return_value = ("ffmpeg version 4.4", "")
    
    with patch("subprocess.Popen", return_value=proc) as mock_popen:
        result = service.ingest(str(dummy_input))
        
        # 1. 成功することの検証
        assert result.success is True
        assert result.error == ""
        
        # 2. サポートされたモックが正しく呼ばれたかの検証
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert args[0] == "ffmpeg"
        assert "-c:v" in args
        assert "libx264" in args
        assert "-c:a" in args
        assert "aac" in args
        
        # 3. NormalizedMedia から IngestResult に引き継がれる各属性の検証
        assert result.normalized_path == str(Path(tmp_path) / "dummy_input_normalized.mp4")
        assert result.format_info["codec"] == "libx264"
        assert result.format_info["resolution"] == "1920x1080"
        assert result.format_info["fps"] == 30.0
        assert result.format_info["audio_codec"] == "aac"
        assert result.format_info["audio_channels"] == 2
        assert result.file_size_bytes == 10


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 実FFmpeg実行テスト (@pytest.mark.slow)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@pytest.mark.slow
def test_ingest_real_ffmpeg(tmp_path):
    """実際にFFmpegを実行して15秒の動画を正規化するテスト"""
    if not TEST_SHORT.exists():
        pytest.skip(f"テスト用の実動画ファイルが存在しません: {TEST_SHORT}")
        
    service = IngestService(output_dir=str(tmp_path))
    
    # 1. validate_input の検証
    validation = service.validate_input(str(TEST_SHORT))
    assert validation.success is True
    
    # 2. ingest の実行 (正規化処理)
    result = service.ingest(str(TEST_SHORT))
    
    # 3. 結果の検証
    assert result.success is True
    assert result.error == ""
    assert result.normalized_path != ""
    assert Path(result.normalized_path).exists()
    assert Path(result.normalized_path).stat().st_size > 0
    
    # 4. NormalizedMedia の各属性が正しく設定されているかの検証
    assert result.format_info["codec"] == "libx264"
    assert result.format_info["resolution"] == "1920x1080"
    assert result.format_info["fps"] == 30.0
    assert result.format_info["audio_codec"] == "aac"
    assert result.format_info["audio_channels"] == 2
