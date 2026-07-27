import sys
import os
import json
import urllib.error
import urllib.request
from pathlib import Path
import unittest
from unittest.mock import patch, MagicMock

# テスト対象モジュールをインポート可能にするために sys.path に追加
sys.path.insert(0, str(Path(__file__).parent))
import quick_verify


class TestQuickVerifyRecovery(unittest.TestCase):

    def setUp(self):
        import sys
        sys.modules.pop("video_editor_engine", None)

    def tearDown(self):
        import sys
        sys.modules.pop("video_editor_engine", None)

    @patch("urllib.request.urlopen")
    def test_api_request_success(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"status": "ok"}'
        mock_urlopen.return_value = mock_response

        res = quick_verify.api_get("/test")
        self.assertEqual(res, {"status": "ok"})
        mock_urlopen.assert_called_once()

    @patch("urllib.request.urlopen")
    @patch("time.sleep")
    def test_api_request_retry_on_temporary_error(self, mock_sleep, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"status": "ok"}'

        mock_urlopen.side_effect = [
            urllib.error.URLError("Temporary connection refused"),
            urllib.error.HTTPError("http://localhost/test", 503, "Service Unavailable", None, None),
            mock_response
        ]

        res = quick_verify.api_get("/test")
        self.assertEqual(res, {"status": "ok"})
        self.assertEqual(mock_urlopen.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("urllib.request.urlopen")
    @patch("time.sleep")
    def test_api_request_no_retry_on_4xx_error(self, mock_sleep, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "http://localhost/test", 400, "Bad Request", None, None
        )

        res = quick_verify.api_get("/test")
        self.assertIn("error", res)
        self.assertEqual(mock_urlopen.call_count, 1)
        mock_sleep.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_api_request_post_data_encoding(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"status": "created"}'
        mock_urlopen.return_value = mock_response

        data = {"foo": "bar"}
        res = quick_verify.api_post("/create", data)
        self.assertEqual(res, {"status": "created"})
        
        call_args = mock_urlopen.call_args[0]
        req = call_args[0]
        self.assertIsInstance(req, urllib.request.Request)
        self.assertEqual(req.method, "POST")
        self.assertEqual(req.data, b'{"foo": "bar"}')
        self.assertEqual(req.headers.get("Content-type"), "application/json")

    @patch("urllib.request.urlopen")
    @patch("time.sleep")
    def test_api_request_max_retries_exceeded(self, mock_sleep, mock_urlopen):
        # 5回連続でリトライ可能なエラーを発生させる
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "http://localhost/test", 503, "Service Unavailable", None, None
        )

        res = quick_verify.api_get("/test")
        self.assertEqual(res, {"error": "HTTP Error 503: Service Unavailable"})
        self.assertEqual(mock_urlopen.call_count, 5)
        self.assertEqual(mock_sleep.call_count, 4)

    @patch("subprocess.run")
    @patch("video_editor_engine.FFmpegEditor")
    def test_create_dummy_video(self, mock_editor_cls, mock_run):
        import tempfile
        from pathlib import Path

        mock_editor = MagicMock()
        mock_editor.ffmpeg_path = "mock_ffmpeg_path"
        mock_editor_cls.return_value = mock_editor

        def side_effect(cmd, *args, **kwargs):
            self.assertEqual(cmd[0], "mock_ffmpeg_path")
            out_path = cmd[-1]
            with open(out_path, "wb") as f:
                f.write(b"fake video data")
            return MagicMock(returncode=0)

        mock_run.side_effect = side_effect

        with tempfile.TemporaryDirectory() as tmpdir:
            target_path = Path(tmpdir) / "dummy.mp4"
            quick_verify.create_dummy_video(target_path, target_size_mb=2)

            self.assertTrue(target_path.exists())
            self.assertGreaterEqual(target_path.stat().st_size, 2 * 1024 * 1024)
            mock_editor_cls.assert_called_once()

    @patch("subprocess.run")
    def test_create_dummy_video_import_error(self, mock_run):
        import tempfile
        from pathlib import Path

        def side_effect(cmd, *args, **kwargs):
            out_path = cmd[-1]
            with open(out_path, "wb") as f:
                f.write(b"fake video data")
            return MagicMock(returncode=0)

        mock_run.side_effect = side_effect

        # video_editor_engine インポート例外を発生させる
        original_import = __builtins__['__import__']
        def mock_import(name, *args, **kwargs):
            if name == 'video_editor_engine':
                raise ImportError("Mocked import error")
            return original_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=mock_import):
            with tempfile.TemporaryDirectory() as tmpdir:
                target_path = Path(tmpdir) / "dummy.mp4"
                quick_verify.create_dummy_video(target_path, target_size_mb=1)
                self.assertTrue(target_path.exists())

    @patch("subprocess.run")
    def test_create_dummy_video_ffmpeg_failure(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.SubprocessError("FFmpeg failed")
        
        with self.assertRaises(RuntimeError) as ctx:
            quick_verify.create_dummy_video("dummy.mp4", target_size_mb=1)
        self.assertIn("FFmpegによるダミー動画生成に失敗しました", str(ctx.exception))

    @patch("quick_verify.api_get")
    @patch("quick_verify.api_post")
    @patch("quick_verify.create_dummy_video")
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.stat")
    @patch("time.sleep")
    def test_main_self_recovery_on_missing_video(
        self, mock_sleep, mock_path_stat, mock_path_exists, mock_create_dummy, mock_post, mock_get
    ):
        mock_get.side_effect = [
            {"videos": []},
            {"status": "completed", "current_stage": 7, "stages": [], "result": {"quality_score": 95}},
            {"hooks": {}, "sessions": {}}
        ]
        
        mock_post.return_value = {"status": "started", "harness_mode": "test"}
        mock_path_exists.return_value = False
        
        stat_mock = MagicMock()
        stat_mock.st_size = 20 * 1024 * 1024
        mock_path_stat.return_value = stat_mock

        res = quick_verify.main()
        self.assertEqual(res, 0)
        
        mock_create_dummy.assert_called_once()
        mock_post.assert_called_once()

    @patch("quick_verify.api_get")
    @patch("quick_verify.create_dummy_video")
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.stat")
    def test_main_self_recovery_existing_valid_video(
        self, mock_path_stat, mock_path_exists, mock_create_dummy, mock_get
    ):
        mock_get.side_effect = [
            {"videos": []},
            {"status": "completed", "current_stage": 7, "stages": [], "result": {"quality_score": 95}},
            {"hooks": {}, "sessions": {}}
        ]
        mock_path_exists.return_value = True
        
        stat_mock = MagicMock()
        stat_mock.st_size = 20 * 1024 * 1024
        mock_path_stat.return_value = stat_mock

        with patch("quick_verify.api_post") as mock_post:
            mock_post.return_value = {"status": "started", "harness_mode": "test"}
            res = quick_verify.main()
            self.assertEqual(res, 0)
            mock_create_dummy.assert_not_called()

    @patch("quick_verify.api_get")
    @patch("pathlib.Path.exists")
    @patch("quick_verify.create_dummy_video")
    def test_main_self_recovery_failure(self, mock_create_dummy, mock_path_exists, mock_get):
        mock_get.return_value = {"videos": []}
        mock_path_exists.return_value = False
        mock_create_dummy.side_effect = RuntimeError("Recovery error")

        res = quick_verify.main()
        self.assertEqual(res, 1)

    @patch("quick_verify.api_get")
    @patch("quick_verify.api_post")
    def test_main_pipeline_start_error(self, mock_post, mock_get):
        mock_get.return_value = {"videos": [{"name": "test.mp4", "path": "test.mp4", "size_mb": 50}]}
        mock_post.return_value = {"error": "Failed to start pipeline"}

        res = quick_verify.main()
        self.assertEqual(res, 1)

    @patch("quick_verify.api_get")
    @patch("quick_verify.api_post")
    @patch("time.sleep")
    def test_main_progress_monitoring_api_temporary_error(
        self, mock_sleep, mock_post, mock_get
    ):
        mock_get.side_effect = [
            {"videos": [{"name": "test.mp4", "path": "test.mp4", "size_mb": 50}]},
            {"status": "running", "current_stage": 1, "stages": []},
            {"error": "Connection refused"},
            {"status": "completed", "current_stage": 7, "stages": [], "result": {"quality_score": 95}},
            {"hooks": {}, "sessions": {}}
        ]
        mock_post.return_value = {"status": "started", "harness_mode": "test"}

        res = quick_verify.main()
        self.assertEqual(res, 0)
        self.assertEqual(mock_get.call_count, 5)

    @patch("quick_verify.api_get")
    @patch("quick_verify.api_post")
    @patch("time.sleep")
    def test_main_monitoring_consecutive_errors(self, mock_sleep, mock_post, mock_get):
        mock_get.side_effect = [
            {"videos": [{"name": "test.mp4", "path": "test.mp4", "size_mb": 50}]},
            {"error": "Err 1"},
            {"error": "Err 2"},
            {"error": "Err 3"},
            {"error": "Err 4"},
            {"error": "Err 5"}
        ]
        mock_post.return_value = {"status": "started", "harness_mode": "test"}

        res = quick_verify.main()
        self.assertEqual(res, 1)
        self.assertEqual(mock_get.call_count, 6)

    @patch("quick_verify.api_get")
    @patch("quick_verify.api_post")
    @patch("time.sleep")
    def test_main_stage_changes_print(self, mock_sleep, mock_post, mock_get):
        mock_get.side_effect = [
            {"videos": [{"name": "test.mp4", "path": "test.mp4", "size_mb": 50}]},
            {
                "status": "running",
                "current_stage": 0,
                "stages": [
                    {"status": "running", "icon": "🎬", "name": "Stage 1"},
                    {"status": "pending", "icon": "🎙️", "name": "Stage 2"}
                ]
            },
            {
                "status": "completed",
                "current_stage": 2,
                "stages": [
                    {"status": "completed", "icon": "🎬", "name": "Stage 1", "detail": "done"},
                    {"status": "completed", "icon": "🎙️", "name": "Stage 2", "detail": "done2"}
                ],
                "result": {"quality_score": 95, "stage_results": [
                    {"name": "Stage 1", "success": True, "detail": "done"},
                    {"name": "Stage 2", "success": True, "detail": "done2"}
                ]}
            },
            {"hooks": {}, "sessions": {}}
        ]
        mock_post.return_value = {"status": "started", "harness_mode": "test"}

        with patch("sys.stdout", new_callable=MagicMock) as mock_stdout:
            res = quick_verify.main()
            self.assertEqual(res, 0)
            
            printed_lines = [call[0][0] for call in mock_stdout.write.call_args_list]
            printed_text = "".join(printed_lines)
            self.assertIn("▶ 🎬 Stage 1", printed_text)
            self.assertIn("✅ 🎙️ Stage 2 done2", printed_text)

    @patch("quick_verify.api_get")
    @patch("quick_verify.api_post")
    @patch("time.sleep")
    def test_main_pipeline_error_status(self, mock_sleep, mock_post, mock_get):
        mock_get.side_effect = [
            {"videos": [{"name": "test.mp4", "path": "test.mp4", "size_mb": 50}]},
            {"status": "error", "error": "Internal process failed"}
        ]
        mock_post.return_value = {"status": "started", "harness_mode": "test"}

        res = quick_verify.main()
        self.assertEqual(res, 1)

    @patch("quick_verify.api_get")
    @patch("quick_verify.api_post")
    @patch("time.sleep")
    def test_main_monitoring_timeout(self, mock_sleep, mock_post, mock_get):
        responses = [{"videos": [{"name": "test.mp4", "path": "test.mp4", "size_mb": 50}]}]
        for _ in range(90):
            responses.append({"status": "running", "current_stage": 1, "stages": []})
        mock_get.side_effect = responses
        mock_post.return_value = {"status": "started", "harness_mode": "test"}

        res = quick_verify.main()
        self.assertEqual(res, 1)

    @patch("quick_verify.api_get")
    @patch("quick_verify.api_post")
    @patch("time.sleep")
    def test_main_result_not_dict(self, mock_sleep, mock_post, mock_get):
        mock_get.side_effect = [
            {"videos": [{"name": "test.mp4", "path": "test.mp4", "size_mb": 50}]},
            {"status": "completed", "current_stage": 7, "stages": [], "result": None},
            {"hooks": {}, "sessions": {}}
        ]
        mock_post.return_value = {"status": "started", "harness_mode": "test"}

        res = quick_verify.main()
        self.assertEqual(res, 0)

    @patch("quick_verify.api_get")
    @patch("quick_verify.api_post")
    @patch("time.sleep")
    def test_main_stage_results_success_and_failure(self, mock_sleep, mock_post, mock_get):
        mock_get.side_effect = [
            {"videos": [{"name": "test.mp4", "path": "test.mp4", "size_mb": 50}]},
            {
                "status": "completed",
                "current_stage": 7,
                "stages": [],
                "result": {
                    "quality_score": 50,
                    "stage_results": [
                        {"name": "品質チェック", "success": False, "detail": "low quality"},
                        {"name": "字幕生成", "success": False, "detail": "failed"}
                    ]
                }
            },
            {"hooks": {}, "sessions": {}}
        ]
        mock_post.return_value = {"status": "started", "harness_mode": "test"}

        res = quick_verify.main()
        self.assertEqual(res, 1)

    @patch("quick_verify.api_get")
    @patch("quick_verify.api_post")
    @patch("time.sleep")
    def test_main_harness_path_no_score(self, mock_sleep, mock_post, mock_get):
        mock_get.side_effect = [
            {"videos": [{"name": "test.mp4", "path": "test.mp4", "size_mb": 50}]},
            {"status": "completed", "current_stage": 7, "stages": [], "result": "harness_result_string"},
            {"hooks": {}, "sessions": {}}
        ]
        mock_post.return_value = {"status": "success", "harness_mode": "harness"}

        res = quick_verify.main()
        self.assertEqual(res, 0)

    @patch("quick_verify.api_get")
    @patch("quick_verify.api_post")
    @patch("time.sleep")
    def test_main_harness_stats_failure_safely_ignored(self, mock_sleep, mock_post, mock_get):
        mock_get.side_effect = [
            {"videos": [{"name": "test.mp4", "path": "test.mp4", "size_mb": 50}]},
            {"status": "completed", "current_stage": 7, "stages": [], "result": {"quality_score": 80, "stage_results": []}},
            OSError("Stats endpoint not found")
        ]
        mock_post.return_value = {"status": "started", "harness_mode": "test"}

        res = quick_verify.main()
        self.assertEqual(res, 0)

    @patch("quick_verify.api_get")
    @patch("quick_verify.api_post")
    @patch("time.sleep")
    def test_main_harness_stats_error_dict(self, mock_sleep, mock_post, mock_get):
        mock_get.side_effect = [
            {"videos": [{"name": "test.mp4", "path": "test.mp4", "size_mb": 50}]},
            {"status": "completed", "current_stage": 7, "stages": [], "result": {"quality_score": 80, "stage_results": []}},
            {"error": "Unauthorized"}
        ]
        mock_post.return_value = {"status": "started", "harness_mode": "test"}

        res = quick_verify.main()
        self.assertEqual(res, 0)

    @patch("urllib.request.urlopen")
    @patch("time.sleep")
    @patch("subprocess.run")
    @patch("sys.exit")
    def test_cli_execution_block(self, mock_exit, mock_run, mock_sleep, mock_urlopen):
        import runpy
        import io
        
        mock_videos = MagicMock()
        mock_videos.read.return_value = b'{"videos": [{"name": "test.mp4", "path": "test.mp4", "size_mb": 50}]}'
        
        mock_start = MagicMock()
        mock_start.read.return_value = b'{"status": "started", "harness_mode": "test"}'
        
        mock_status = MagicMock()
        mock_status.read.return_value = b'{"status": "completed", "current_stage": 7, "stages": [], "result": {"quality_score": 80, "stage_results": []}}'
        
        mock_stats = MagicMock()
        mock_stats.read.return_value = b'{"hooks": {}, "sessions": {}}'
        
        mock_urlopen.side_effect = [
            mock_videos,
            mock_start,
            mock_status,
            mock_stats
        ]
        
        quick_verify_path = str(Path(quick_verify.__file__).resolve())
        
        with patch("sys.stdout", new_callable=io.StringIO):
            try:
                runpy.run_path(quick_verify_path, run_name="__main__")
            except SystemExit:
                pass
            
        mock_exit.assert_called_once_with(0)

    @patch("urllib.request.urlopen")
    def test_api_request_zero_retries(self, mock_urlopen):
        res = quick_verify.api_request("GET", "/test", max_retries=0)
        self.assertIsNone(res)
        mock_urlopen.assert_not_called()

    @patch("subprocess.run")
    def test_create_dummy_video_no_padding(self, mock_run):
        import tempfile
        from pathlib import Path

        def side_effect(cmd, *args, **kwargs):
            out_path = cmd[-1]
            with open(out_path, "wb") as f:
                f.write(b"a" * 10)
            return MagicMock(returncode=0)

        mock_run.side_effect = side_effect

        with tempfile.TemporaryDirectory() as tmpdir:
            target_path = Path(tmpdir) / "dummy_no_pad.mp4"
            quick_verify.create_dummy_video(target_path, target_size_mb=0)

            self.assertTrue(target_path.exists())
            self.assertEqual(target_path.stat().st_size, 10)

    @patch("quick_verify.api_get")
    @patch("quick_verify.api_post")
    @patch("time.sleep")
    def test_main_stage_results_duplicate_stages(self, mock_sleep, mock_post, mock_get):
        mock_get.side_effect = [
            {"videos": [{"name": "test.mp4", "path": "test.mp4", "size_mb": 50}]},
            {
                "status": "completed",
                "current_stage": 7,
                "stages": [],
                "result": {
                    "quality_score": 95,
                    "stage_results": [
                        {"name": "品質チェック", "success": True, "detail": "good"},
                        {"name": "品質チェック", "success": True, "detail": "already done"}
                    ]
                }
            },
            {"hooks": {}, "sessions": {}}
        ]
        mock_post.return_value = {"status": "started", "harness_mode": "test"}

        res = quick_verify.main()
        self.assertEqual(res, 0)

    @patch("urllib.request.urlopen")
    @patch("time.sleep")
    def test_api_request_retry_on_408_and_429(self, mock_sleep, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"status": "ok"}'

        mock_urlopen.side_effect = [
            urllib.error.HTTPError("http://localhost/test", 408, "Request Timeout", None, None),
            urllib.error.HTTPError("http://localhost/test", 429, "Too Many Requests", None, None),
            mock_response
        ]

        res = quick_verify.api_get("/test")
        self.assertEqual(res, {"status": "ok"})
        self.assertEqual(mock_urlopen.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("subprocess.run")
    def test_create_dummy_video_padding_exact_and_fraction(self, mock_run):
        import tempfile
        from pathlib import Path

        def side_effect(cmd, *args, **kwargs):
            out_path = cmd[-1]
            with open(out_path, "wb") as f:
                f.write(b"a" * 10)
            return MagicMock(returncode=0)

        mock_run.side_effect = side_effect

        with tempfile.TemporaryDirectory() as tmpdir:
            target_path = Path(tmpdir) / "dummy_pad_exact.mp4"
            quick_verify.create_dummy_video(target_path, target_size_mb=1)
            self.assertEqual(target_path.stat().st_size, 1024 * 1024)

            target_path2 = Path(tmpdir) / "dummy_pad_multi.mp4"
            quick_verify.create_dummy_video(target_path2, target_size_mb=3)
            self.assertEqual(target_path2.stat().st_size, 3 * 1024 * 1024)

    @patch("quick_verify.api_get")
    @patch("quick_verify.api_post")
    @patch("time.sleep")
    def test_main_video_selection_priority(self, mock_sleep, mock_post, mock_get):
        mock_get.side_effect = [
            {
                "videos": [
                    {"name": "large.mp4", "path": "large.mp4", "size_mb": 200},
                    {"name": "small.mp4", "path": "small.mp4", "size_mb": 20},
                    {"name": "medium.mp4", "path": "medium.mp4", "size_mb": 50},
                ]
            },
            {"status": "completed", "current_stage": 7, "stages": [], "result": {"quality_score": 95}},
            {"hooks": {}, "sessions": {}}
        ]
        mock_post.return_value = {"status": "started", "harness_mode": "test"}

        res = quick_verify.main()
        self.assertEqual(res, 0)
        mock_post.assert_called_once_with("/api/pipeline/start", {
            "video_path": "small.mp4", "target_minutes": 3
        })

    @patch("urllib.request.urlopen")
    @patch("time.sleep")
    def test_api_request_retry_on_json_decode_error(self, mock_sleep, mock_urlopen):
        mock_invalid = MagicMock()
        mock_invalid.read.return_value = b'invalid json'
        
        mock_valid = MagicMock()
        mock_valid.read.return_value = b'{"status": "ok"}'

        mock_urlopen.side_effect = [mock_invalid, mock_valid]

        res = quick_verify.api_get("/test")
        self.assertEqual(res, {"status": "ok"})
        self.assertEqual(mock_urlopen.call_count, 2)
        self.assertEqual(mock_sleep.call_count, 1)

    @patch("subprocess.run")
    def test_create_dummy_video_subprocess_error(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.CalledProcessError(1, "ffmpeg", stderr=b"ffmpeg error")

        with self.assertRaises(RuntimeError) as ctx:
            quick_verify.create_dummy_video("dummy.mp4", target_size_mb=1)
        self.assertIn("FFmpegによるダミー動画生成に失敗しました", str(ctx.exception))



    @patch("subprocess.run")
    @patch("video_editor_engine.FFmpegEditor")
    def test_create_dummy_video_attribute_error(self, mock_editor_cls, mock_run):
        import tempfile
        from pathlib import Path

        class DummyFFmpegEditor:
            def __init__(self):
                pass
            @property
            def ffmpeg_path(self):
                raise AttributeError("Mocked attribute error")

        mock_editor_cls.return_value = DummyFFmpegEditor()

        def side_effect(cmd, *args, **kwargs):
            self.assertEqual(cmd[0], "ffmpeg")
            out_path = cmd[-1]
            with open(out_path, "wb") as f:
                f.write(b"fake video data")
            return MagicMock(returncode=0)

        mock_run.side_effect = side_effect

        with tempfile.TemporaryDirectory() as tmpdir:
            target_path = Path(tmpdir) / "dummy_attr.mp4"
            quick_verify.create_dummy_video(target_path, target_size_mb=1)
            self.assertTrue(target_path.exists())

    @patch("urllib.request.urlopen")
    @patch("time.sleep")
    def test_api_request_os_error_max_retries_exceeded(self, mock_sleep, mock_urlopen):
        mock_urlopen.side_effect = OSError("Connection refused")

        res = quick_verify.api_get("/test")
        self.assertEqual(res, {"error": "Connection refused"})
        self.assertEqual(mock_urlopen.call_count, 5)
        self.assertEqual(mock_sleep.call_count, 4)


    @patch("quick_verify.api_get")
    @patch("pathlib.Path.exists")
    @patch("quick_verify.create_dummy_video")
    def test_main_self_recovery_os_error(self, mock_create_dummy, mock_path_exists, mock_get):
        # OSError が投げられた時に正常にキャッチして 1 を返すことの検証
        mock_get.return_value = {"videos": []}
        mock_path_exists.return_value = False
        mock_create_dummy.side_effect = OSError("OS recovery error")

        res = quick_verify.main()
        self.assertEqual(res, 1)

    @patch("quick_verify.api_get")
    @patch("quick_verify.api_post")
    @patch("time.sleep")
    def test_main_harness_stats_specific_exceptions_safely_ignored(self, mock_sleep, mock_post, mock_get):
        # ハーネス監査の統計取得中に ValueError, AttributeError, KeyError, TypeError が投げられても
        # 正常に無視されて main が 0 (PASS) を返すことの検証
        exceptions_to_test = [
            ValueError("Invalid response value"),
            AttributeError("NoneType has no attribute get"),
            KeyError("missing key"),
            TypeError("unsupported operand type")
        ]
        
        for exc in exceptions_to_test:
            mock_get.reset_mock()
            mock_post.reset_mock()
            
            mock_get.side_effect = [
                {"videos": [{"name": "test.mp4", "path": "test.mp4", "size_mb": 50}]},
                {"status": "completed", "current_stage": 7, "stages": [], "result": {"quality_score": 80, "stage_results": []}},
                exc
            ]
            mock_post.return_value = {"status": "started", "harness_mode": "test"}
            
            res = quick_verify.main()
            self.assertEqual(res, 0, f"Failed for exception: {type(exc).__name__}")


if __name__ == "__main__":
    unittest.main()
