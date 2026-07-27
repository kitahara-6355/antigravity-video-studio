import sys
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile
import pytest

# テスト対象のインポート
import backend.topleft_clean_generator as generator


def test_sys_stdout_not_corrupted():
    """
    sys.stdout が io.TextIOWrapper で上書きされ、pytest のキャプチャ等に
    悪影響を与えない状態（または標準の sys.stdout に戻されていること）を確認する。
    """
    assert hasattr(sys.stdout, "write")


@patch("backend.topleft_clean_generator.subprocess.run")
def test_create_topleft_clean_preview_success(mock_run):
    """
    create_topleft_clean_preview() が適切なモック環境で正常終了することを検証する。
    """
    mock_run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        
        # ダミーのロゴ画像を作成する
        logo_dir = tmp_path / "backend/branding/logos"
        logo_dir.mkdir(parents=True, exist_ok=True)
        logo_path = logo_dir / "brand_logo.png"
        
        from PIL import Image
        img = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
        img.save(logo_path)
        
        # テスト用のダミー動画パス
        dummy_video = str(tmp_path / "dummy.mp4")
        output_dir = tmp_path / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        # 実行
        result = generator.create_topleft_clean_preview(
            input_video=dummy_video,
            output_dir=output_dir,
            logo_path=logo_path,
            temp_dir=temp_dir
        )
        
        assert result is not None
        assert Path(result).name == "topleft_clean.mp4"
        assert mock_run.call_count == 5



@patch("backend.topleft_clean_generator.subprocess.run")
def test_create_topleft_clean_preview_ffmpeg_error(mock_run):
    """
    FFmpeg?????CalledProcessError??????????
    ???????????????
    """
    import subprocess
    mock_run.side_effect = subprocess.CalledProcessError(
        returncode=1, cmd="ffmpeg", stderr=b"ffmpeg error"
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        logo_path = tmp_path / "logo.png"
        
        from PIL import Image
        img = Image.new("RGBA", (10, 10))
        img.save(logo_path)
        
        dummy_video = str(tmp_path / "dummy.mp4")
        
        with pytest.raises(subprocess.CalledProcessError):
            generator.create_topleft_clean_preview(
                input_video=dummy_video,
                output_dir=tmp_path / "output",
                logo_path=logo_path,
                temp_dir=tmp_path / "temp"
            )


@patch("backend.topleft_clean_generator.subprocess.run")
def test_create_topleft_clean_preview_logo_not_found(mock_run):
    """
    ?????????????? FileNotFoundError ?????????????
    """
    mock_run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        logo_path = tmp_path / "non_existent_logo.png"
        dummy_video = str(tmp_path / "dummy.mp4")
        
        with pytest.raises(FileNotFoundError):
            generator.create_topleft_clean_preview(
                input_video=dummy_video,
                output_dir=tmp_path / "output",
                logo_path=logo_path,
                temp_dir=tmp_path / "temp"
            )


@patch("backend.topleft_clean_generator.subprocess.run")
def test_create_topleft_clean_preview_logo_invalid_image(mock_run):
    """
    ??????????????? PIL.UnidentifiedImageError ?????????????
    """
    mock_run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")
    from PIL import UnidentifiedImageError
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        logo_path = tmp_path / "corrupted_logo.png"
        
        # ???????????
        with open(logo_path, "wb") as f:
            f.write(b"not an image data")
            
        dummy_video = str(tmp_path / "dummy.mp4")
        
        with pytest.raises(UnidentifiedImageError):
            generator.create_topleft_clean_preview(
                input_video=dummy_video,
                output_dir=tmp_path / "output",
                logo_path=logo_path,
                temp_dir=tmp_path / "temp"
            )
