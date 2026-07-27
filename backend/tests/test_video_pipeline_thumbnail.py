import os
import subprocess
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

# Ensure backend path is in sys.path
import sys
backend_path = Path(__file__).parent.parent
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from video_pipeline.thumbnail_generator import ThumbnailGenerator, ThumbnailResult

# テストで使う実動画ファイルのパス（@pytest.mark.slow 用）
TEST_VIDEO_PATH = str(Path(__file__).parent / "test_13s.mp4")


@pytest.mark.parametrize(
    "case_name, title, pillow_available, duration_mock, ffprobe_fail, ffmpeg_fail, file_exists, expected_success",
    [
        # 正常系 (2ケース以上)
        ("normal_with_title", "Test Title", True, 10.0, False, False, True, True),
        ("normal_no_title", "", True, 10.0, False, False, True, True),
        ("normal_no_pillow", "Test Title", False, 10.0, False, False, True, True),
        # 境界値 (2ケース以上)
        ("boundary_empty_title", "   ", True, 10.0, False, False, True, True),
        ("boundary_long_title", "A" * 100, True, 10.0, False, False, True, True),
        ("boundary_long_duration", "Title", True, 10000.0, False, False, True, True),
        ("boundary_zero_duration", "Title", True, 0.0, False, False, True, True),
        # 異常系 (2ケース以上)
        ("error_file_not_found", "Title", True, 10.0, False, False, False, False),
        ("error_ffprobe_fail", "Title", True, 10.0, True, False, True, True),  # ffprobe失敗時はデフォルト10秒で成功するフォールバック
        ("error_ffmpeg_fail", "Title", True, 10.0, False, True, True, False),
    ]
)
def test_thumbnail_generator_parametrized(
    tmp_path,
    safe_popen_mock,
    case_name,
    title,
    pillow_available,
    duration_mock,
    ffprobe_fail,
    ffmpeg_fail,
    file_exists,
    expected_success
):
    """
    パラメータ化テスト: 正常系, 境界値, 異常系のケースを検証する。
    """
    output_dir = tmp_path / "thumbs"
    generator = ThumbnailGenerator(output_dir=str(output_dir))

    # テスト対象のダミー動画パス
    video_path = str(tmp_path / "dummy_video.mp4")
    if file_exists:
        with open(video_path, "wb") as f:
            f.write(b"dummy_content")

    # ffprobeとffmpegの出力をモック
    ffprobe_json = f'{{"format": {{"duration": "{duration_mock}"}}}}'

    # safe_popen_mockフィクスチャの利用 (規約遵守)
    mock_ffprobe_proc = safe_popen_mock(
        returncode=1 if ffprobe_fail else 0,
        stdout_text=ffprobe_json
    )
    # subprocess.run 内部での Popen.communicate() の呼び出しに対応
    mock_ffprobe_proc.communicate.return_value = (ffprobe_json, "")
    # with Popen(...) as process: で __enter__ が mock_ffprobe_proc 自体を返すように設定
    mock_ffprobe_proc.__enter__.return_value = mock_ffprobe_proc

    mock_ffmpeg_proc = safe_popen_mock(
        returncode=1 if ffmpeg_fail else 0
    )
    mock_ffmpeg_proc.communicate.return_value = ("", "")
    mock_ffmpeg_proc.__enter__.return_value = mock_ffmpeg_proc

    # Popenをパッチし、コマンドに応じて適切なプロセスモックを返す
    def popen_side_effect(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        cmd_str = " ".join(cmd)
        
        if "ffprobe" in cmd_str:
            return mock_ffprobe_proc
        elif "ffmpeg" in cmd_str:
            # ffmpeg成功時は出力JPEGファイルが生成される必要がある (空ファイルだとPillowがエラーになるため、10x10ピクセルの有効な画像を生成)
            if not ffmpeg_fail:
                video_name = Path(video_path).stem
                out_file = output_dir / f"thumb_{video_name}.jpg"
                from PIL import Image
                img = Image.new("RGB", (10, 10), color="blue")
                img.save(out_file, "JPEG")
            return mock_ffmpeg_proc
            
        return safe_popen_mock(returncode=0)

    # Pillowの利用可能性とsubprocess.Popenをモック化
    with patch.object(generator, "_is_pillow_available", return_value=pillow_available), \
         patch("subprocess.Popen", side_effect=popen_side_effect):
         
        # 実行
        result = generator.generate(video_path, title=title)

        # 検証
        assert result.success == expected_success
        if expected_success:
            assert os.path.exists(result.image_path)
            # ffprobe失敗時はデフォルト10秒で動作するため
            expected_duration = 10.0 if ffprobe_fail else duration_mock
            assert result.source_frame_time == expected_duration * 0.3
            if title and pillow_available:
                assert "_titled.jpg" in result.image_path
            else:
                assert "_titled.jpg" not in result.image_path



@pytest.mark.slow
def test_thumbnail_generator_real_ffmpeg(tmp_path):
    """
    FFmpegの実際のバイナリを呼び出すテスト (@pytest.mark.slow)。
    実際のテスト動画 test_13s.mp4 を使用する。
    """
    # テスト動画の存在チェック
    if not os.path.exists(TEST_VIDEO_PATH):
        pytest.skip(f"テスト動画ファイルが見つかりません: {TEST_VIDEO_PATH}")

    output_dir = tmp_path / "thumbs_real"
    generator = ThumbnailGenerator(output_dir=str(output_dir))

    # 実動画・タイトルありで生成を実行
    result = generator.generate(TEST_VIDEO_PATH, title="Real FFmpeg Test")

    # Pillowのインストール状態に関わらず、結果は成功するべき
    assert result.success is True
    assert os.path.exists(result.image_path)
    assert result.source_frame_time > 0.0
    assert result.file_size > 0
    # Pillowが有効ならタイトル付きのはず
    if generator._is_pillow_available():
        assert "_titled.jpg" in result.image_path
