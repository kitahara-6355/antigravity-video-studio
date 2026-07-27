import os
import sys
import unittest
from unittest.mock import patch, MagicMock
import subprocess
from pathlib import Path
import tempfile
import json

# backend ディレクトリを sys.path に追加して phase0_preflight をインポートできるようにする
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(TESTS_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import phase0_preflight


class TestPhase0Preflight(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        
    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("os.path.exists")
    @patch("phase0_preflight._GetShortPathNameW")
    def test_get_short_path_success(self, mock_get_short_path, mock_exists):
        mock_exists.return_value = True
        
        # GetShortPathNameW が返す長さをシミュレート
        def set_val(path, buf, size):
            buf.value = "C:\\SHORTPA~1"
            return 12
        mock_get_short_path.side_effect = set_val
        
        short = phase0_preflight.get_short_path("C:\\Long Path Name")
        self.assertEqual(short, "C:\\SHORTPA~1")

    @patch("os.path.exists")
    @patch("phase0_preflight._GetShortPathNameW")
    def test_get_short_path_not_exists(self, mock_get_short_path, mock_exists):
        mock_exists.return_value = False
        short = phase0_preflight.get_short_path("C:\\NonExistentPath")
        self.assertEqual(short, os.path.abspath("C:\\NonExistentPath"))
        mock_get_short_path.assert_not_called()

    @patch("os.path.exists")
    @patch("phase0_preflight._GetShortPathNameW")
    def test_get_short_path_buffer_expansion(self, mock_get_short_path, mock_exists):
        mock_exists.return_value = True
        
        # 初回はサイズ不足 (needed > size)、2回目で成功
        call_count = 0
        def side_effect(path, buf, size):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return 300  # バッファサイズ 256 より大きい値を返す
            else:
                buf.value = "C:\\SHORTPA~1"
                return 12
                
        mock_get_short_path.side_effect = side_effect
        
        short = phase0_preflight.get_short_path("C:\\Long Path Name")
        self.assertEqual(short, "C:\\SHORTPA~1")
        self.assertEqual(call_count, 2)

    @patch("os.path.exists")
    @patch("phase0_preflight._GetShortPathNameW")
    def test_get_short_path_api_failed(self, mock_get_short_path, mock_exists):
        mock_exists.return_value = True
        mock_get_short_path.return_value = 0  # 失敗
        
        long_path = "C:\\Long Path Name"
        short = phase0_preflight.get_short_path(long_path)
        self.assertEqual(short, os.path.abspath(long_path))

    @patch("subprocess.run")
    def test_run_ffmpeg_success(self, mock_run):
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_run.return_value = mock_res
        
        success, out, err = phase0_preflight.run_ffmpeg_with_retry(["ffmpeg", "-i", "input"], "Test Run")
        self.assertTrue(success)
        self.assertIsNone(out)
        self.assertIsNone(err)
        mock_run.assert_called_once()

    @patch("subprocess.run")
    @patch("time.sleep")
    def test_run_ffmpeg_retry_on_fail(self, mock_sleep, mock_run):
        mock_res_fail = MagicMock()
        mock_res_fail.returncode = 1
        mock_res_fail.stderr = "FFmpeg conversion error"
        
        mock_res_success = MagicMock()
        mock_res_success.returncode = 0
        
        mock_run.side_effect = [mock_res_fail, mock_res_fail, mock_res_success]
        
        success, out, err = phase0_preflight.run_ffmpeg_with_retry(
            ["ffmpeg", "-i", "input"], "Test Retry", max_retries=3
        )
        self.assertTrue(success)
        self.assertEqual(mock_run.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("subprocess.run")
    @patch("time.sleep")
    def test_run_ffmpeg_all_fails(self, mock_sleep, mock_run):
        mock_res = MagicMock()
        mock_res.returncode = 1
        mock_res.stderr = "Fatal FFmpeg error"
        mock_run.return_value = mock_res
        
        success, out, err = phase0_preflight.run_ffmpeg_with_retry(
            ["ffmpeg", "-i", "input"], "Test Fails", max_retries=2
        )
        self.assertFalse(success)
        self.assertEqual(mock_run.call_count, 2)
        self.assertEqual(err, "Failed after 2 attempts")

    @patch("subprocess.run")
    @patch("time.sleep")
    def test_run_ffmpeg_timeout(self, mock_sleep, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(["ffmpeg"], 10)
        
        success, out, err = phase0_preflight.run_ffmpeg_with_retry(
            ["ffmpeg", "-i", "input"], "Test Timeout", max_retries=2
        )
        self.assertFalse(success)
        self.assertEqual(mock_run.call_count, 2)

    @patch("subprocess.run")
    @patch("time.sleep")
    def test_run_ffmpeg_subprocess_error(self, mock_sleep, mock_run):
        # 修正された例外ハンドリング (subprocess.SubprocessError) のテスト
        mock_run.side_effect = [subprocess.SubprocessError("Subprocess failed"), MagicMock(returncode=0)]
        
        success, out, err = phase0_preflight.run_ffmpeg_with_retry(
            ["ffmpeg", "-i", "input"], "Test SubprocessError", max_retries=2
        )
        self.assertTrue(success)
        self.assertEqual(mock_run.call_count, 2)
        mock_sleep.assert_called_once_with(2)

    @patch("subprocess.run")
    @patch("time.sleep")
    def test_run_ffmpeg_os_error(self, mock_sleep, mock_run):
        # 修正された例外ハンドリング (OSError) のテスト
        mock_run.side_effect = [OSError("OS failed"), MagicMock(returncode=0)]
        
        success, out, err = phase0_preflight.run_ffmpeg_with_retry(
            ["ffmpeg", "-i", "input"], "Test OSError", max_retries=2
        )
        self.assertTrue(success)
        self.assertEqual(mock_run.call_count, 2)

    @patch("subprocess.run")
    @patch("time.sleep")
    def test_run_ffmpeg_value_error(self, mock_sleep, mock_run):
        # 修正された例外ハンドリング (ValueError) のテスト
        mock_run.side_effect = [ValueError("Value invalid"), MagicMock(returncode=0)]
        
        success, out, err = phase0_preflight.run_ffmpeg_with_retry(
            ["ffmpeg", "-i", "input"], "Test ValueError", max_retries=2
        )
        self.assertTrue(success)
        self.assertEqual(mock_run.call_count, 2)

    @patch("phase0_preflight.get_short_path")
    @patch("phase0_preflight.run_ffmpeg_with_retry")
    @patch("os.path.exists")
    def test_phase0_preflight_check_success(self, mock_exists, mock_run_ffmpeg, mock_get_short):
        # テスト用のディレクトリとファイルのモックを設定
        raw_dir = self.base_path / "raw_videos" / "AI Studio アップロード用動画"
        raw_dir.mkdir(parents=True, exist_ok=True)
        
        input_video = raw_dir / "シーン01_前編.mp4"
        input_video.touch()
        
        # モックの振る舞い
        mock_get_short.return_value = "C:\\SHORTPA~1\\scene01.mp4"
        mock_exists.side_effect = lambda path: True
        mock_run_ffmpeg.return_value = (True, None, None)
        
        mock_stat_1min = MagicMock()
        mock_stat_1min.st_size = 200000
        mock_stat_5min = MagicMock()
        mock_stat_5min.st_size = 600000
        
        def mock_stat(self_path, *args, **kwargs):
            if "test_1min" in str(self_path):
                return mock_stat_1min
            return mock_stat_5min
            
        with patch.object(Path, "stat", mock_stat):
            with patch.dict(os.environ, {"VIDEO_AUTOMATION_BASE_DIR": str(self.base_path)}):
                results = phase0_preflight.phase0_preflight_check()
                
                self.assertTrue(results["short_path_test"])
                self.assertTrue(results["1min_preview"])
                self.assertTrue(results["5min_chunk"])
                self.assertTrue(results["overall_success"])
                
                json_path = self.base_path / "backend" / "temp" / "phase0_check" / "phase0_results.json"
                self.assertTrue(json_path.exists())
                with open(json_path, "r") as f:
                    saved_results = json.load(f)
                self.assertTrue(saved_results["overall_success"])

    @patch("os.path.exists")
    def test_phase0_preflight_check_missing_input(self, mock_exists):
        mock_exists.return_value = False
        with patch.dict(os.environ, {"VIDEO_AUTOMATION_BASE_DIR": str(self.base_path)}):
            results = phase0_preflight.phase0_preflight_check()
            self.assertFalse(results["overall_success"])

    @patch("phase0_preflight.get_short_path")
    @patch("os.path.exists")
    def test_phase0_preflight_check_short_path_failed(self, mock_exists, mock_get_short):
        raw_dir = self.base_path / "raw_videos" / "AI Studio アップロード用動画"
        raw_dir.mkdir(parents=True, exist_ok=True)
        input_video = raw_dir / "シーン01_前編.mp4"
        input_video.touch()
        
        mock_get_short.return_value = "C:\\SHORTPA~1\\scene01.mp4"
        
        # input_video.exists() -> True
        # short_path.exists() -> False
        mock_exists.side_effect = lambda path: True if str(input_video) in str(path) else False
        
        with patch.dict(os.environ, {"VIDEO_AUTOMATION_BASE_DIR": str(self.base_path)}):
            results = phase0_preflight.phase0_preflight_check()
            self.assertFalse(results["short_path_test"])
            self.assertFalse(results["overall_success"])

    @patch("phase0_preflight.get_short_path")
    @patch("phase0_preflight.run_ffmpeg_with_retry")
    @patch("os.path.exists")
    def test_phase0_preflight_check_1min_preview_failed(self, mock_exists, mock_run_ffmpeg, mock_get_short):
        raw_dir = self.base_path / "raw_videos" / "AI Studio アップロード用動画"
        raw_dir.mkdir(parents=True, exist_ok=True)
        input_video = raw_dir / "シーン01_前編.mp4"
        input_video.touch()
        
        mock_get_short.return_value = "C:\\SHORTPA~1\\scene01.mp4"
        mock_exists.return_value = True
        mock_run_ffmpeg.return_value = (False, None, "FFmpeg failed")
        
        with patch.dict(os.environ, {"VIDEO_AUTOMATION_BASE_DIR": str(self.base_path)}):
            results = phase0_preflight.phase0_preflight_check()
            self.assertTrue(results["short_path_test"])
            self.assertFalse(results["1min_preview"])
            self.assertFalse(results["overall_success"])

    @patch("phase0_preflight.get_short_path")
    @patch("phase0_preflight.run_ffmpeg_with_retry")
    @patch("os.path.exists")
    def test_phase0_preflight_check_5min_chunk_failed(self, mock_exists, mock_run_ffmpeg, mock_get_short):
        raw_dir = self.base_path / "raw_videos" / "AI Studio アップロード用動画"
        raw_dir.mkdir(parents=True, exist_ok=True)
        input_video = raw_dir / "シーン01_前編.mp4"
        input_video.touch()
        
        mock_get_short.return_value = "C:\\SHORTPA~1\\scene01.mp4"
        mock_exists.return_value = True
        
        # 1min preview は成功、5min chunk は失敗
        mock_run_ffmpeg.side_effect = [(True, None, None), (False, None, "FFmpeg failed")]
        
        mock_stat_1min = MagicMock()
        mock_stat_1min.st_size = 200000
        
        def mock_stat(self_path, *args, **kwargs):
            return mock_stat_1min
            
        with patch.object(Path, "stat", mock_stat):
            with patch.dict(os.environ, {"VIDEO_AUTOMATION_BASE_DIR": str(self.base_path)}):
                results = phase0_preflight.phase0_preflight_check()
                self.assertTrue(results["short_path_test"])
                self.assertTrue(results["1min_preview"])
                self.assertFalse(results["5min_chunk"])
                self.assertFalse(results["overall_success"])

    @patch("os.path.exists")
    def test_phase0_preflight_check_default_path_missing(self, mock_exists):
        # 環境変数なしでデフォルトパスにフォールバックすることを確認するテスト
        mock_exists.return_value = False
        with patch.dict(os.environ, {}, clear=True):
            results = phase0_preflight.phase0_preflight_check()
            self.assertFalse(results["overall_success"])

    @patch("subprocess.run")
    @patch("time.sleep")
    @patch("time.time")
    def test_main_block(self, mock_time, mock_sleep, mock_run):
        import runpy
        raw_dir = self.base_path / "raw_videos" / "AI Studio アップロード用動画"
        raw_dir.mkdir(parents=True, exist_ok=True)
        input_video = raw_dir / "シーン01_前編.mp4"
        input_video.touch()

        mock_time.side_effect = [100.0, 105.5]

        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_run.return_value = mock_res

        output_dir = self.base_path / "backend" / "temp" / "phase0_check"
        output_dir.mkdir(parents=True, exist_ok=True)

        preview_1min = output_dir / "test_1min.mp4"
        chunk_5min = output_dir / "test_5min.mp4"

        preview_1min.touch()
        chunk_5min.touch()

        import stat
        mock_stat_1min = MagicMock()
        mock_stat_1min.st_size = 200000
        mock_stat_1min.st_mode = stat.S_IFREG
        mock_stat_5min = MagicMock()
        mock_stat_5min.st_size = 600000
        mock_stat_5min.st_mode = stat.S_IFREG

        orig_stat = Path.stat
        def mock_stat(self_path, *args, **kwargs):
            path_str = str(self_path)
            if "test_1min" in path_str:
                return mock_stat_1min
            elif "test_5min" in path_str:
                return mock_stat_5min
            return orig_stat(self_path, *args, **kwargs)

        with patch.object(Path, "stat", mock_stat):
            with patch.dict(os.environ, {"VIDEO_AUTOMATION_BASE_DIR": str(self.base_path)}):
                runpy.run_module("phase0_preflight", run_name="__main__")

        self.assertEqual(mock_run.call_count, 2)

    @patch("phase0_preflight._GetShortPathNameW", None)
    @patch("os.path.exists")
    def test_get_short_path_api_unavailable(self, mock_exists):
        # APIが利用不可能な場合（Noneの場合）、元のパスがそのまま返されることを検証
        mock_exists.return_value = True
        long_path = "C:\\Long Path Name"
        short = phase0_preflight.get_short_path(long_path)
        self.assertEqual(short, os.path.abspath(long_path))

    @patch("subprocess.run")
    @patch("time.sleep")
    def test_run_ffmpeg_type_error(self, mock_sleep, mock_run):
        # TypeErrorが発生した場合に、適切にキャッチされてリトライされることを検証
        mock_run.side_effect = [TypeError("Type error invalid arg"), MagicMock(returncode=0)]
        success, out, err = phase0_preflight.run_ffmpeg_with_retry(
            ["ffmpeg", "-i", "input"], "Test TypeError", max_retries=2
        )
        self.assertTrue(success)
        self.assertEqual(mock_run.call_count, 2)

    @patch("pathlib.Path.mkdir")
    @patch("os.path.exists")
    def test_phase0_preflight_mkdir_failed(self, mock_exists, mock_mkdir):
        # output_dir.mkdirがOSErrorを発生させた場合に、全体がクラッシュせずoverall_successがFalseになることを検証
        mock_exists.return_value = True
        mock_mkdir.side_effect = OSError("Permission denied")
        with patch.dict(os.environ, {"VIDEO_AUTOMATION_BASE_DIR": str(self.base_path)}):
            results = phase0_preflight.phase0_preflight_check()
            self.assertFalse(results["overall_success"])

    @patch("phase0_preflight.get_short_path")
    @patch("phase0_preflight.run_ffmpeg_with_retry")
    @patch("os.path.exists")
    @patch("builtins.open")
    def test_phase0_preflight_json_write_failed(self, mock_open, mock_exists, mock_run_ffmpeg, mock_get_short):
        # JSON保存時にOSErrorが発生した場合に、処理自体は続行され、例外でクラッシュしないことを検証
        raw_dir = self.base_path / "raw_videos" / "AI Studio アップロード用動画"
        raw_dir.mkdir(parents=True, exist_ok=True)
        input_video = raw_dir / "シーン01_前編.mp4"
        input_video.touch()

        mock_get_short.return_value = "C:\\SHORTPA~1\\scene01.mp4"
        mock_exists.return_value = True
        mock_run_ffmpeg.return_value = (True, None, None)
        mock_open.side_effect = OSError("Disk full")

        mock_stat_1min = MagicMock()
        mock_stat_1min.st_size = 200000
        mock_stat_5min = MagicMock()
        mock_stat_5min.st_size = 600000

        def mock_stat(self_path, *args, **kwargs):
            if "test_1min" in str(self_path):
                return mock_stat_1min
            return mock_stat_5min

        with patch.object(Path, "stat", mock_stat):
            with patch.dict(os.environ, {"VIDEO_AUTOMATION_BASE_DIR": str(self.base_path)}):
                results = phase0_preflight.phase0_preflight_check()
                self.assertTrue(results["overall_success"])


if __name__ == "__main__":
    unittest.main()
