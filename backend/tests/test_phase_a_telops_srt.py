import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path as RealPath
from PIL import Image, ImageFont
import re
from datetime import timedelta

# テスト対象のインポート
from phase_a_telops_srt import create_theme_telop, add_dynamic_telops, create_combined_srt

def test_create_theme_telop_success(tmp_path):
    output_path = tmp_path / "test_telop.png"
    result = create_theme_telop("テストテキスト", output_path, width=300, height=50)
    
    assert RealPath(result).exists()
    assert str(result) == str(output_path)
    
    with Image.open(result) as img:
        assert img.mode == "RGBA"
        assert img.size == (300, 50)

def test_create_theme_telop_font_fallback(tmp_path):
    output_path = tmp_path / "test_fallback.png"
    
    original_truetype = ImageFont.truetype
    
    def mock_truetype(*args, **kwargs):
        if args and args[0] == "C:\\Windows\\Fonts\\msgothic.ttc":
            raise OSError("Font not found")
        return original_truetype(*args, **kwargs)
    
    # phase_a_telops_srt でインポートされた ImageFont.truetype をモック化
    with patch("phase_a_telops_srt.ImageFont.truetype", side_effect=mock_truetype):
        result = create_theme_telop("フォールバックテスト", output_path)
        assert RealPath(result).exists()
        
        with Image.open(result) as img:
            assert img.mode == "RGBA"

def test_add_dynamic_telops_success(tmp_path):
    base_mock = tmp_path / "video-automation"
    
    input_video = base_mock / "soul_narrative_FINAL_EDITED.mp4"
    output_video = base_mock / "soul_narrative_WITH_TELOPS.mp4"
    
    # 必要なディレクトリとダミーファイルを作成
    (base_mock / "backend" / "branding" / "theme_telops").mkdir(parents=True, exist_ok=True)
    (base_mock / "backend" / "branding" / "logos").mkdir(parents=True, exist_ok=True)
    
    input_video.touch()
    (base_mock / "backend" / "branding" / "logos" / "brand_logo.png").touch()
    
    def mock_run(cmd, **kwargs):
        output_video.touch()
        output_video.write_bytes(b"dummy video")
        mock = MagicMock()
        mock.returncode = 0
        mock.stderr = ""
        return mock
        
        
    with patch("phase_a_telops_srt.project_root", return_value=base_mock),          patch("subprocess.run", side_effect=mock_run) as mock_subprocess:
        
        result = add_dynamic_telops()
        
        assert result == str(output_video)
        assert mock_subprocess.called

def test_add_dynamic_telops_failure(tmp_path):
    base_mock = tmp_path / "video-automation"
    (base_mock / "backend" / "branding" / "theme_telops").mkdir(parents=True, exist_ok=True)
    (base_mock / "backend" / "branding" / "logos").mkdir(parents=True, exist_ok=True)
    (base_mock / "backend" / "branding" / "logos" / "brand_logo.png").touch()
    
        
    with patch("phase_a_telops_srt.project_root", return_value=base_mock),          patch("subprocess.run", return_value=MagicMock(returncode=1, stderr="FFmpeg failed")):
        
        result = add_dynamic_telops()
        assert result is None

def test_create_combined_srt_success(tmp_path):
    base_mock = tmp_path / "video-automation"
    raw_dir = base_mock / "raw_videos" / "AI Studio アップロード用動画"
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    # 00:30:50,000 (1850秒) は 1848秒を超えるため除外されるはず
    srt_content_1 = (
        "1\n"
        "00:00:10,000 --> 00:00:15,000\n"
        "シーン1の字幕です\n\n"
        "2\n"
        "00:30:50,000 --> 00:30:55,000\n"
        "シーン1の後半字幕です（これはカットされるはず）\n\n"
    )
    
    srt_content_3 = (
        "1\n"
        "00:00:05,000 --> 00:00:10,000\n"
        "シーン3の字幕です\n\n"
        "2\n"
        "00:10:00,000 --> 00:10:05,000\n"
        "シーン3の後半字幕です（これもカットされるはず）\n\n"
    )
    
    srt_content_4 = (
        "1\n"
        "00:00:01,000 --> 00:00:03,000\n"
        "シーン4の字幕です\n\n"
    )
    
    (raw_dir / "シーン01_前編_whisper_semantic.srt").write_text(srt_content_1, encoding="utf-8-sig")
    (raw_dir / "シーン03_後編01_whisper_semantic.srt").write_text(srt_content_3, encoding="utf-8-sig")
    (raw_dir / "シーン04_後編02_whisper_semantic.srt").write_text(srt_content_4, encoding="utf-8-sig")
    
    output_srt = base_mock / "soul_narrative_subtitles.srt"
    
        
    with patch("phase_a_telops_srt.project_root", return_value=base_mock):
        result = create_combined_srt()
        
        assert result == str(output_srt)
        assert output_srt.exists()
        
        content = output_srt.read_text(encoding="utf-8")
        assert "シーン1の字幕です" in content
        assert "シーン3の字幕です" in content
        assert "シーン4の字幕です" in content
        assert "シーン1の後半字幕です" not in content
        assert "シーン3の後半字幕です" not in content

def test_create_combined_srt_missing_files(tmp_path):
    base_mock = tmp_path / "video-automation"
    raw_dir = base_mock / "raw_videos" / "AI Studio アップロード用動画"
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    srt_content_1 = (
        "1\n"
        "00:00:10,000 --> 00:00:15,000\n"
        "シーン1の字幕のみ\n\n"
    )
    (raw_dir / "シーン01_前編_whisper_semantic.srt").write_text(srt_content_1, encoding="utf-8-sig")
    
    output_srt = base_mock / "soul_narrative_subtitles.srt"
    
        
    with patch("phase_a_telops_srt.project_root", return_value=base_mock):
        result = create_combined_srt()
        
        assert result == str(output_srt)
        assert output_srt.exists()
        
        content = output_srt.read_text(encoding="utf-8")
        assert "シーン1の字幕のみ" in content


def test_main_success():
    with patch("phase_a_telops_srt.add_dynamic_telops", return_value="dummy_video.mp4") as mock_telops, \
         patch("phase_a_telops_srt.create_combined_srt", return_value="dummy_subtitles.srt") as mock_srt:
        from phase_a_telops_srt import main
        assert main() is True
        mock_telops.assert_called_once()
        mock_srt.assert_called_once()

def test_main_failure_telops():
    with patch("phase_a_telops_srt.add_dynamic_telops", return_value=None) as mock_telops, \
         patch("phase_a_telops_srt.create_combined_srt", return_value="dummy_subtitles.srt") as mock_srt:
        from phase_a_telops_srt import main
        assert main() is False

def test_main_failure_srt():
    with patch("phase_a_telops_srt.add_dynamic_telops", return_value="dummy_video.mp4") as mock_telops, \
         patch("phase_a_telops_srt.create_combined_srt", return_value=None) as mock_srt:
        from phase_a_telops_srt import main
        assert main() is False

def test_create_combined_srt_io_error(tmp_path):
    base_mock = tmp_path / "video-automation"
    raw_dir = base_mock / "raw_videos" / "AI Studio アップロード用動画"
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    # 全てのシーンのダミーファイルを作成
    (raw_dir / "シーン01_前編_whisper_semantic.srt").touch()
    (raw_dir / "シーン03_後編01_whisper_semantic.srt").touch()
    (raw_dir / "シーン04_後編02_whisper_semantic.srt").touch()
    
    
    # 全てのシーンファイルで OSError を発生させる
    def mock_read_text(self, *args, **kwargs):
        if "シーン01" in self.name or "シーン03" in self.name or "シーン04" in self.name:
            raise OSError("Read error")
        return ""
        
    with patch("phase_a_telops_srt.project_root", return_value=base_mock), \
         patch.object(RealPath, "read_text", mock_read_text):
         
         # 各シーンでOSErrorが発生しても、処理全体はクラッシュせず
         # 警告を出力して正常に空でフォールバックして処理が完了することを確認する
         result = create_combined_srt()
         assert result == str(base_mock / "soul_narrative_subtitles.srt")

def test_create_combined_srt_invalid_blocks(tmp_path):
    base_mock = tmp_path / "video-automation"
    raw_dir = base_mock / "raw_videos" / "AI Studio アップロード用動画"
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. 3行未満のブロック (lines < 3) -> 153->151 分岐の検証
    # 2. 時間フォーマット不正 (time_match is None) -> 155->151 分岐の検証
    # 3. 正常なブロック
    srt_content = (
        # 3行未満の不正ブロック
        "1\n"
        "00:00:10,000 --> 00:00:15,000\n\n"
        
        # 時間フォーマット不正ブロック
        "2\n"
        "00:00:10.000 --> 00:00:15.000\n"
        "不正時間フォーマットの字幕\n\n"
        
        # 正常ブロック
        "3\n"
        "00:00:20,000 --> 00:00:25,000\n"
        "正常な字幕です\n"
    )
    
    (raw_dir / "シーン01_前編_whisper_semantic.srt").write_text(srt_content, encoding="utf-8-sig")
    
        
    with patch("phase_a_telops_srt.project_root", return_value=base_mock):
        result = create_combined_srt()
        
        output_srt = base_mock / "soul_narrative_subtitles.srt"
        assert result == str(output_srt)
        assert output_srt.exists()
        
        content = output_srt.read_text(encoding="utf-8")
        assert "正常な字幕です" in content
        assert "不正時間フォーマットの字幕" not in content


def test_create_combined_srt_missing_scene01(tmp_path):
    base_mock = tmp_path / "video-automation"
    raw_dir = base_mock / "raw_videos" / "AI Studio アップロード用動画"
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    # シーン01のSRTは存在しない (166->177 分岐の検証)
    # シーン03のSRTは存在する
    srt_content_3 = (
        "1\n"
        "00:00:05,000 --> 00:00:10,000\n"
        "シーン3の字幕です\n\n"
    )
    (raw_dir / "シーン03_後編01_whisper_semantic.srt").write_text(srt_content_3, encoding="utf-8-sig")
    
        
    with patch("phase_a_telops_srt.project_root", return_value=base_mock):
        result = create_combined_srt()
        
        output_srt = base_mock / "soul_narrative_subtitles.srt"
        assert result == str(output_srt)
        assert output_srt.exists()
        
        content = output_srt.read_text(encoding="utf-8")
        assert "シーン3の字幕です" in content


def test_create_theme_telop_empty_and_long_text(tmp_path):
    output_path_empty = tmp_path / "empty.png"
    output_path_long = tmp_path / "long.png"
    
    # 空テキスト
    result_empty = create_theme_telop("", output_path_empty)
    assert RealPath(result_empty).exists()
    
    # 非常に長いテキスト
    long_text = "あ" * 1000
    result_long = create_theme_telop(long_text, output_path_long)
    assert RealPath(result_long).exists()

def test_create_combined_srt_boundary_values(tmp_path):
    base_mock = tmp_path / "video-automation"
    raw_dir = base_mock / "raw_videos" / "AI Studio アップロード用動画"
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    # シーン01の境界値テスト
    # 1848秒境界: 00:30:47,999 (1847.999s) -> 保持、00:30:48,000 (1848s) -> 除外
    srt_content_1 = (
        "1\n"
        "00:30:47,999 --> 00:30:47,999\n"
        "シーン1の境界内エントリ\n\n"
        "2\n"
        "00:30:48,000 --> 00:30:48,000\n"
        "シーン1の境界外エントリ\n\n"
    )
    
    # シーン03の境界値テスト
    # shift = 1902
    # 2258秒境界: 2258 - 1902 = 356秒
    # 00:05:55,999 (355.999s) -> 保持、00:05:56,000 (356.000s) -> 除外
    srt_content_3 = (
        "1\n"
        "00:05:55,999 --> 00:05:55,999\n"
        "シーン3の境界内エントリ\n\n"
        "2\n"
        "00:05:56,000 --> 00:05:56,000\n"
        "シーン3の境界外エントリ\n\n"
    )
    
    (raw_dir / "シーン01_前編_whisper_semantic.srt").write_text(srt_content_1, encoding="utf-8-sig")
    (raw_dir / "シーン03_後編01_whisper_semantic.srt").write_text(srt_content_3, encoding="utf-8-sig")
    
    output_srt = base_mock / "soul_narrative_subtitles.srt"
    
        
    with patch("phase_a_telops_srt.project_root", return_value=base_mock):
        result = create_combined_srt()
        
        assert result == str(output_srt)
        assert output_srt.exists()
        
        content = output_srt.read_text(encoding="utf-8")
        assert "シーン1の境界内エントリ" in content
        assert "シーン1の境界外エントリ" not in content
        assert "シーン3の境界内エントリ" in content
        assert "シーン3の境界外エントリ" not in content

def test_create_combined_srt_encoding_variations(tmp_path):
    base_mock = tmp_path / "video-automation"
    raw_dir = base_mock / "raw_videos" / "AI Studio アップロード用動画"
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    srt_content = (
        "1\n"
        "00:00:10,000 --> 00:00:15,000\n"
        "BOMなしUTF8エントリ\n\n"
    )
    
    # encoding="utf-8" (BOMなし) で書き込み
    (raw_dir / "シーン01_前編_whisper_semantic.srt").write_text(srt_content, encoding="utf-8")
    
    output_srt = base_mock / "soul_narrative_subtitles.srt"
    
        
    with patch("phase_a_telops_srt.project_root", return_value=base_mock):
        result = create_combined_srt()
        content = output_srt.read_text(encoding="utf-8")
        assert "BOMなしUTF8エントリ" in content

def test_add_dynamic_telops_subprocess_stderr_coverage(tmp_path):
    base_mock = tmp_path / "video-automation"
    (base_mock / "backend" / "branding" / "theme_telops").mkdir(parents=True, exist_ok=True)
    (base_mock / "backend" / "branding" / "logos").mkdir(parents=True, exist_ok=True)
    (base_mock / "backend" / "branding" / "logos" / "brand_logo.png").touch()
    
        
    # subprocess.run が失敗して、かつ stderr が存在する場合の出力検証
    mock_run = MagicMock()
    mock_run.returncode = 1
    mock_run.stderr = "FFmpeg error message which is long enough to verify the slicing log output."
    
    with patch("phase_a_telops_srt.project_root", return_value=base_mock), \
         patch("subprocess.run", return_value=mock_run):
        
        result = add_dynamic_telops()
        assert result is None


def test_escape_ffmpeg_path():
    from phase_a_telops_srt import escape_ffmpeg_path
    # Windows path replacement
    assert escape_ffmpeg_path("C:\\path\\to\\file.png") == "C\\:/path/to/file.png"
    # Single quote replacement
    assert escape_ffmpeg_path("C:\\path'to\\file.png") == "C\\:/path'\\\\''to/file.png"

def test_add_dynamic_telops_file_not_found_error(tmp_path):
    base_mock = tmp_path / "video-automation"
    (base_mock / "backend" / "branding" / "theme_telops").mkdir(parents=True, exist_ok=True)
    (base_mock / "backend" / "branding" / "logos").mkdir(parents=True, exist_ok=True)
    (base_mock / "backend" / "branding" / "logos" / "brand_logo.png").touch()
    
        
    with patch("phase_a_telops_srt.project_root", return_value=base_mock),          patch("subprocess.run", side_effect=FileNotFoundError("ffmpeg not found")):
        
        result = add_dynamic_telops()
        assert result is None

def test_add_dynamic_telops_unexpected_exception_tdr(tmp_path):
    base_mock = tmp_path / "video-automation"
    (base_mock / "backend" / "branding" / "theme_telops").mkdir(parents=True, exist_ok=True)
    (base_mock / "backend" / "branding" / "logos").mkdir(parents=True, exist_ok=True)
    (base_mock / "backend" / "branding" / "logos" / "brand_logo.png").touch()
    
        
    mock_store = MagicMock()
    
    with patch("phase_a_telops_srt.project_root", return_value=base_mock), \
         patch("subprocess.run", side_effect=OSError("Subprocess failed abnormally")), \
         patch("agents.memory.technical_debt.technical_debt_store.register_debt", mock_store.register_debt):
        
        result = add_dynamic_telops()
        assert result is None
        mock_store.register_debt.assert_called_once()
        args, kwargs = mock_store.register_debt.call_args
        assert kwargs.get("category") == "MINOR_INFRA"
        assert "phase_a_telops_srt.py" in kwargs.get("file_path")

def test_create_combined_srt_encoding_cp932(tmp_path):
    base_mock = tmp_path / "video-automation"
    raw_dir = base_mock / "raw_videos" / "AI Studio アップロード用動画"
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    srt_content = (
        "1\n"
        "00:00:10,000 --> 00:00:15,000\n"
        "日本語の文字（CP932エンコード）\n\n"
    )
    (raw_dir / "シーン01_前編_whisper_semantic.srt").write_text(srt_content, encoding="cp932")
    
    output_srt = base_mock / "soul_narrative_subtitles.srt"
    
        
    with patch("phase_a_telops_srt.project_root", return_value=base_mock):
        result = create_combined_srt()
        assert result == str(output_srt)
        assert output_srt.exists()
        
        content = output_srt.read_text(encoding="utf-8")
        assert "日本語の文字（CP932エンコード）" in content

def test_parse_srt_time_invalid_format(tmp_path):
    base_mock = tmp_path / "video-automation"
    raw_dir = base_mock / "raw_videos" / "AI Studio アップロード用動画"
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    srt_content = (
        "1\n"
        "00:00:10 --> 00:00:15,000\n"
        "不正な時間フォーマット\n\n"
    )
    (raw_dir / "シーン01_前編_whisper_semantic.srt").write_text(srt_content, encoding="utf-8-sig")
    
        
    with patch("phase_a_telops_srt.project_root", return_value=base_mock):
        result = create_combined_srt()
        output_srt = base_mock / "soul_narrative_subtitles.srt"
        assert result == str(output_srt)
        assert output_srt.exists()
        content = output_srt.read_text(encoding="utf-8")
        assert "不正な時間フォーマット" not in content


def test_create_combined_srt_shift_srt_os_error(tmp_path):
    base_mock = tmp_path / "video-automation"
    raw_dir = base_mock / "raw_videos" / "AI Studio アップロード用動画"
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    srt_01 = raw_dir / "シーン01_前編_whisper_semantic.srt"
    srt_01.mkdir()
    srt_03 = raw_dir / "シーン03_後編01_whisper_semantic.srt"
    srt_03.mkdir()
    srt_04 = raw_dir / "シーン04_後編02_whisper_semantic.srt"
    srt_04.mkdir()
    
        
    with patch("phase_a_telops_srt.project_root", return_value=base_mock):
        result = create_combined_srt()
        output_srt = base_mock / "soul_narrative_subtitles.srt"
        assert result == str(output_srt)
        assert output_srt.exists()


def test_add_dynamic_telops_image_generation_error(tmp_path):
    base_mock = tmp_path / "video-automation"
    (base_mock / "backend" / "branding" / "theme_telops").mkdir(parents=True, exist_ok=True)
    (base_mock / "backend" / "branding" / "logos").mkdir(parents=True, exist_ok=True)
    (base_mock / "backend" / "branding" / "logos" / "brand_logo.png").touch()
    
        
    with patch("phase_a_telops_srt.project_root", return_value=base_mock), \
         patch("phase_a_telops_srt.create_theme_telop", side_effect=OSError("Disk full or permission denied")):
         
         result = add_dynamic_telops()
         assert result is None


def test_create_combined_srt_write_error(tmp_path):
    base_mock = tmp_path / "video-automation"
    raw_dir = base_mock / "raw_videos" / "AI Studio アップロード用動画"
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    # 正常なダミーファイルを作成
    (raw_dir / "シーン01_前編_whisper_semantic.srt").touch()
    
        
    # builtins.open が書き込みモードで開かれた時に OSError を投げるようにする
    original_open = open
    def mock_open(file, mode="r", *args, **kwargs):
        if "soul_narrative_subtitles.srt" in str(file) and "w" in mode:
            raise OSError("Write permission denied")
        return original_open(file, mode, *args, **kwargs)
        
    with patch("phase_a_telops_srt.project_root", return_value=base_mock), \
         patch("builtins.open", mock_open):
         
         result = create_combined_srt()
         assert result is None



def test_register_ffmpeg_tdr_debt_exception_handling():
    from phase_a_telops_srt import _register_ffmpeg_tdr_debt
    import sys
    
    cached_modules = {}
    for key in list(sys.modules.keys()):
        if "agents" in key:
            cached_modules[key] = sys.modules.pop(key)
            
    try:
        original_import = __import__
        def mock_import(name, *args, **kwargs):
            if "agents" in name:
                raise ImportError("Mocked import error for TDR")
            return original_import(name, *args, **kwargs)
            
        with patch("builtins.__import__", side_effect=mock_import):
            _register_ffmpeg_tdr_debt(Exception("Test dummy error"))
    finally:
        for key, mod in cached_modules.items():
            sys.modules[key] = mod


def test_parse_srt_time_value_error_handling():
    from phase_a_telops_srt import _parse_srt_time
    import pytest
    
    with pytest.raises(ValueError, match="Invalid SRT time format '00:00'"):
        _parse_srt_time("00:00")
        
    with pytest.raises(ValueError, match="Invalid SRT time format '00:00:10'"):
        _parse_srt_time("00:00:10")
        
    with pytest.raises(ValueError, match="Invalid SRT time format 'aa:bb:cc,ddd'"):
        _parse_srt_time("aa:bb:cc,ddd")


def test_shift_srt_content_is_none():
    from phase_a_telops_srt import _shift_srt
    with patch("phase_a_telops_srt.Path.read_text", return_value=None):
        res = _shift_srt("dummy.srt", 10)
        assert res == []

def test_shift_srt_all_decoding_fails():
    from phase_a_telops_srt import _shift_srt
    with patch("phase_a_telops_srt.Path.read_text", side_effect=OSError("Read error")):
        res = _shift_srt("dummy.srt", 10)
        assert res == []
