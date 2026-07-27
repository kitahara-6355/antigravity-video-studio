import sys
from pathlib import Path

# プロジェクトルートを sys.path の先頭に追加して backend パッケージとしてインポート可能にする
TESTS_DIR = Path(__file__).parent
BACKEND_DIR = TESTS_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from unittest.mock import patch, MagicMock, mock_open
import builtins
import re

from backend import phase_a_telops_srt

# --- create_theme_telop のテスト ---

def test_create_theme_telop_success(tmp_path):
    output_path = tmp_path / "test_telop.png"
    result = phase_a_telops_srt.create_theme_telop("Test Text", output_path)
    assert result == output_path
    assert output_path.exists()

def test_create_theme_telop_font_fallback(tmp_path):
    output_path = tmp_path / "test_telop_fallback.png"
    from PIL import ImageFont
    original_truetype = ImageFont.truetype
    
    def side_effect(font, *args, **kwargs):
        if "msgothic.ttc" in str(font):
            raise OSError("Font not found")
        return original_truetype(font, *args, **kwargs)
        
    # ImageFont.truetype が msgothic に対してのみ例外を投げるようにする
    # これにより load_default() 内部での truetype 呼び出しは成功する
    with patch("PIL.ImageFont.truetype", side_effect=side_effect):
        result = phase_a_telops_srt.create_theme_telop("Test Text", output_path)
        assert result == output_path
        assert output_path.exists()


# --- add_dynamic_telops のテスト ---

def test_add_dynamic_telops_success():
    with patch("backend.phase_a_telops_srt.create_theme_telop") as mock_create_telop, \
         patch("pathlib.Path.mkdir") as mock_mkdir, \
         patch("subprocess.run") as mock_run, \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.stat") as mock_stat:
        
        # subprocess.run の戻り値
        mock_completed = MagicMock()
        mock_completed.returncode = 0
        mock_run.return_value = mock_completed
        
        # Path.stat の戻り値
        mock_stat_res = MagicMock()
        mock_stat_res.st_size = 1024 * 1024 * 5 # 5MB
        mock_stat.return_value = mock_stat_res
        
        res = phase_a_telops_srt.add_dynamic_telops()
        
        assert res is not None
        assert "soul_narrative_WITH_TELOPS.mp4" in res
        mock_run.assert_called_once()

def test_add_dynamic_telops_failure():
    with patch("backend.phase_a_telops_srt.create_theme_telop") as mock_create_telop, \
         patch("pathlib.Path.mkdir") as mock_mkdir, \
         patch("subprocess.run") as mock_run, \
         patch("pathlib.Path.exists") as mock_exists:
        
        # 1. subprocess.run が失敗コードを返すケース
        mock_completed = MagicMock()
        mock_completed.returncode = 1
        mock_completed.stderr = "FFmpeg error"
        mock_run.return_value = mock_completed
        mock_exists.return_value = True
        
        res = phase_a_telops_srt.add_dynamic_telops()
        assert res is None
        
        # 2. subprocess.run は成功したが、出力ファイルが存在しないケース
        mock_completed.returncode = 0
        mock_exists.return_value = False
        
        res = phase_a_telops_srt.add_dynamic_telops()
        assert res is None


# --- create_combined_srt のテスト ---

DUMMY_SRT_CONTENT = """1
00:00:10,000 --> 00:00:15,000
こんにちは

2
00:00:20,000 --> 00:00:25,000
世界

3
短すぎるブロック

4
00:00:30,000 --> invalid_time
マッチしない時間
"""

class MockPathEnvironment:
    def __init__(self, exists_map, read_text_map):
        self.exists_map = exists_map
        self.read_text_map = read_text_map
        self.original_exists = Path.exists
        self.original_read_text = Path.read_text

    def __enter__(self):
        def _exists(path_obj):
            for pattern, val in self.exists_map.items():
                if pattern in str(path_obj).replace('\\', '/'):
                    return val
            return self.original_exists(path_obj)
            
        def _read_text(path_obj, *args, **kwargs):
            for pattern, val in self.read_text_map.items():
                if pattern in str(path_obj).replace('\\', '/'):
                    if isinstance(val, Exception):
                        raise val
                    return val
            return self.original_read_text(path_obj, *args, **kwargs)

        Path.exists = _exists
        Path.read_text = _read_text
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        Path.exists = self.original_exists
        Path.read_text = self.original_read_text


def test_create_combined_srt_all_success():
    exists_map = {
        "シーン01": True,
        "シーン03": True,
        "シーン04": True,
    }
    read_text_map = {
        "シーン01": DUMMY_SRT_CONTENT,
        "シーン03": DUMMY_SRT_CONTENT,
        "シーン04": DUMMY_SRT_CONTENT,
    }
    
    with MockPathEnvironment(exists_map, read_text_map):
        with patch("builtins.open", mock_open()) as mock_file:
            res = phase_a_telops_srt.create_combined_srt()
            assert res is not None
            assert "soul_narrative_subtitles.srt" in res
            mock_file.assert_called()


def test_create_combined_srt_missing_files():
    exists_map = {
        "シーン01": False,
        "シーン03": False,
        "シーン04": False,
    }
    read_text_map = {}
    
    with MockPathEnvironment(exists_map, read_text_map):
        with patch("builtins.open", mock_open()) as mock_file:
            res = phase_a_telops_srt.create_combined_srt()
            assert res is not None
            assert "soul_narrative_subtitles.srt" in res


def test_create_combined_srt_exceptions():
    exists_map = {
        "シーン01": True,
        "シーン03": True,
        "シーン04": True,
    }
    read_text_map = {
        "シーン01": ValueError("Simulated ValueError"),
        "シーン03": UnicodeDecodeError("utf-8", b"", 0, 1, "invalid"),
        "シーン04": OSError("Simulated OSError"),
    }
    
    with MockPathEnvironment(exists_map, read_text_map):
        with patch("builtins.open", mock_open()) as mock_file:
            res = phase_a_telops_srt.create_combined_srt()
            assert res is not None
            assert "soul_narrative_subtitles.srt" in res


# --- main のテスト ---

def test_main_success():
    with patch("backend.phase_a_telops_srt.add_dynamic_telops", return_value="dummy_video.mp4") as mock_add, \
         patch("backend.phase_a_telops_srt.create_combined_srt", return_value="dummy_srt.srt") as mock_create:
        res = phase_a_telops_srt.main()
        assert res is True
        mock_add.assert_called_once()
        mock_create.assert_called_once()

def test_main_failure_no_video():
    with patch("backend.phase_a_telops_srt.add_dynamic_telops", return_value=None) as mock_add, \
         patch("backend.phase_a_telops_srt.create_combined_srt", return_value="dummy_srt.srt") as mock_create:
        res = phase_a_telops_srt.main()
        assert res is False

def test_main_failure_no_srt():
    with patch("backend.phase_a_telops_srt.add_dynamic_telops", return_value="dummy_video.mp4") as mock_add, \
         patch("backend.phase_a_telops_srt.create_combined_srt", return_value=None) as mock_create:
        res = phase_a_telops_srt.main()
        assert res is False
