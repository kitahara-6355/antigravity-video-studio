try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _wp
except ImportError:
    from path_resolver import writable_path as _wp

import os
import sys
import sqlite3
import unittest
from unittest.mock import patch, MagicMock, Mock
import importlib
from pathlib import Path

# backend/tests を path に追加してモジュールをインポート可能にする
sys.path.insert(0, str(Path(__file__).parent))
import e2e_stability


class TestE2EStabilityDockerRobustness(unittest.TestCase):
    def setUp(self):
        # テスト毎に環境変数の変更を追跡するため、元に戻せるように退避
        self.original_env = os.environ.copy()

    def tearDown(self):
        # 環境変数を元に戻す
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_environment_variables_loading(self):
        """環境変数が正しく読み込まれ、モジュール変数に反映されることを確認"""
        os.environ["PASS_SCORE"] = "85"
        os.environ["API_BASE"] = "http://test-backend:9000"
        os.environ["LONG_VIDEO_PATH"] = "/workspace/test.mp4"

        # リロードして環境変数を再評価
        importlib.reload(e2e_stability)

        self.assertEqual(e2e_stability.PASS_SCORE, 85)
        self.assertEqual(e2e_stability.API_BASE, "http://test-backend:9000")
        self.assertEqual(e2e_stability.LONG_VIDEO, "/workspace/test.mp4")

    @patch("subprocess.run")
    @patch("pathlib.Path.exists", return_value=False)
    @patch("pathlib.Path.mkdir")
    def test_create_test_video_threads_and_preset(self, mock_mkdir, mock_exists, mock_run):
        """create_test_video が環境変数を反映した ffmpeg 引数を使用することを確認"""
        os.environ["FFMPEG_THREADS"] = "4"
        os.environ["FFMPEG_PRESET"] = "ultrafast"

        # モジュールをリロードして反映
        importlib.reload(e2e_stability)

        e2e_stability.create_test_video(duration=5, output_dir="/tmp/test_dir")

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        
        # コマンド内に -threads 4 と -preset ultrafast が含まれているか検証
        self.assertIn("-threads", cmd)
        self.assertEqual(cmd[cmd.index("-threads") + 1], "4")
        self.assertIn("-preset", cmd)
        self.assertEqual(cmd[cmd.index("-preset") + 1], "ultrafast")

    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_wait_backend_ready_success(self, mock_urlopen):
        """バックエンドが起動している場合、wait_backend_ready が True を返すこと"""
        # レスポンスのモック
        mock_resp = MagicMock()
        mock_urlopen.return_value = mock_resp

        result = e2e_stability.wait_backend_ready(max_wait=3)
        self.assertTrue(result)
        mock_urlopen.assert_called_with(f"{e2e_stability.API_BASE}/api/status", timeout=3)

    @patch("time.sleep")  # テスト高速化のために sleep をモック
    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_wait_backend_ready_failure_logging(self, mock_urlopen, mock_sleep):
        """バックエンドが起動していない場合、URLError などの詳細を出力し、False を返すこと"""
        import urllib.error
        # 接続拒否例外を発生させる
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        with patch("sys.stdout") as mock_stdout:
            result = e2e_stability.wait_backend_ready(max_wait=2)
            self.assertFalse(result)
            
            # stdout に 'Connection refused' や 'attempt 1/2' の文字列が含まれることを確認
            written_texts = "".join([call[0][0] for call in mock_stdout.write.call_args_list])
            self.assertIn("Connection refused", written_texts)
            self.assertIn("attempt 1/2", written_texts)

    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_run_pipeline_start_failure(self, mock_urlopen):
        """パイプライン開始時に API エラーが発生した場合、適切な辞書が返されること"""
        mock_urlopen.side_effect = Exception("HTTP 500 Internal Error")

        # video_path としてダミーのテンポラリファイルを使う
        dummy_video = "/tmp/dummy.mp4"
        with patch("pathlib.Path.unlink") as mock_unlink: # ファイル削除エラーを避けるため
            result = e2e_stability.run_pipeline(dummy_video, target_minutes=1, timeout=10)
            
            self.assertEqual(result["status"], "error")
            self.assertIn("Start failed: unexpected error Exception - HTTP 500 Internal Error", result["error"])

    @patch("time.sleep")
    @patch("time.time")
    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_run_pipeline_polling_timeout_with_last_error(self, mock_urlopen, mock_time_func, mock_sleep):
        """ポーリング中にエラーが発生しタイムアウトした際、エラー情報が含まれていること"""
        # time.time() のモック。ループ条件チェックで時間の経過を模擬する
        time_values = [1000.0, 1005.0, 1015.0]
        mock_time_func.side_effect = time_values + [1020.0] * 10

        # 開始は成功するが、ステータス取得でエラーを返すモック設計
        mock_start_resp = MagicMock()
        mock_start_resp.read.return_value = b'{"status": "started"}'
        
        mock_status_err = Exception("Connection lost during polling")
        mock_urlopen.side_effect = [mock_start_resp, mock_status_err]

        dummy_video = "/tmp/dummy.mp4"
        with patch("pathlib.Path.unlink"):
            result = e2e_stability.run_pipeline(dummy_video, target_minutes=1, timeout=10)
            
            self.assertEqual(result["status"], "error")
            self.assertIn("Timeout", result["error"])
            self.assertIn("Connection lost during polling", result["error"])

    @patch("pathlib.Path.exists", return_value=True)
    def test_create_test_video_exists(self, mock_exists):
        """すでにファイルが存在する場合、subprocess.runを呼ばずに即座に返す"""
        with patch("subprocess.run") as mock_run:
            res = e2e_stability.create_test_video(duration=5, output_dir="/tmp/test_dir")
            mock_run.assert_not_called()
            self.assertEqual(Path(res), Path("/tmp/test_dir") / "test_5s.mp4")

    @patch("subprocess.run")
    @patch("pathlib.Path.exists", return_value=False)
    @patch("pathlib.Path.mkdir")
    def test_create_test_video_default_dir(self, mock_mkdir, mock_exists, mock_run):
        """output_dirがNoneの場合、デフォルトのtestsディレクトリを使う"""
        # モジュールをリロードして反映
        importlib.reload(e2e_stability)
        res = e2e_stability.create_test_video(duration=5, output_dir=None)
        
        # tests/test_5s.mp4 が返されることを確認
        self.assertIn("tests", res)
        self.assertTrue(res.endswith("test_5s.mp4"))

    @patch("time.sleep")
    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_run_pipeline_success(self, mock_urlopen, mock_sleep):
        """API呼び出しに成功し、ポーリングにて completed を返す正常系"""
        # 開始成功レスポンス
        mock_start_resp = MagicMock()
        mock_start_resp.read.return_value = b'{"status": "started"}'
        
        # ステータスレスポンス
        mock_status_resp = MagicMock()
        mock_status_resp.read.return_value = b'{"status": "completed", "result": {"quality_score": 95}}'
        
        mock_urlopen.side_effect = [mock_start_resp, mock_status_resp]
        
        dummy_video = "/tmp/dummy.mp4"
        with patch("pathlib.Path.unlink"):
            result = e2e_stability.run_pipeline(dummy_video, target_minutes=1, timeout=10)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["result"]["quality_score"], 95)

    @patch("time.sleep")
    @patch("time.time")
    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_run_pipeline_polling_exception_logged(self, mock_urlopen, mock_time_func, mock_sleep):
        """ポーリング中に例外が発生した場合、警告がログ出力されタイムアウトへ移行すること"""
        # タイムアウトのための時間経過
        mock_time_func.side_effect = [1000.0, 1005.0, 1015.0, 1020.0]
        
        # 開始成功
        mock_start_resp = MagicMock()
        mock_start_resp.read.return_value = b'{"status": "started"}'
        
        # ポーリングでの例外
        mock_urlopen.side_effect = [mock_start_resp, Exception("Connection refused")]
        
        dummy_video = "/tmp/dummy.mp4"
        with patch("pathlib.Path.unlink"):
            with patch("sys.stdout") as mock_stdout:
                result = e2e_stability.run_pipeline(dummy_video, target_minutes=1, timeout=10)
                self.assertEqual(result["status"], "error")
                self.assertIn("Timeout", result["error"])
                
                # stdout に [Warning] が出力されているか
                written_texts = "".join([call[0][0] for call in mock_stdout.write.call_args_list])
                self.assertIn("[Warning] polling status failed with unexpected error (Exception): Connection refused", written_texts)
                self.assertIn("Traceback (most recent call last):", written_texts)

    @patch("time.sleep")
    @patch("time.time")
    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_run_pipeline_timeout_no_last_error(self, mock_urlopen, mock_time_func, mock_sleep):
        """一度も例外が発生せずにタイムアウトした場合の動作"""
        mock_time_func.side_effect = [1000.0, 1015.0, 1020.0]
        
        # 開始成功、ステータスは started のまま
        mock_start_resp = MagicMock()
        mock_start_resp.read.return_value = b'{"status": "started"}'
        
        mock_status_resp = MagicMock()
        mock_status_resp.read.return_value = b'{"status": "running"}'
        
        mock_urlopen.side_effect = [mock_start_resp, mock_status_resp, mock_status_resp]
        
        dummy_video = "/tmp/dummy.mp4"
        with patch("pathlib.Path.unlink"):
            result = e2e_stability.run_pipeline(dummy_video, target_minutes=1, timeout=10)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error"], "Timeout")

    def test_check_result_status_not_completed(self):
        """status が completed 以外の場合に False を返す"""
        result = {"status": "error", "error": "Something went wrong"}
        with patch("sys.stdout") as mock_stdout:
            res = e2e_stability.check_result(result, "テストラベル")
            self.assertFalse(res)
            
            written_texts = "".join([call[0][0] for call in mock_stdout.write.call_args_list])
            self.assertIn("テストラベル: パイプライン未完了", written_texts)

    def test_check_result_success(self):
        """スコアが基準値以上、かつ stability_score が 90点以上で合格"""
        result = {
            "status": "completed",
            "result": {
                "quality_score": 85,
                "segments_count": 10,
                "duration_seconds": 120.0,
                "quality_details": {
                    "category_report": [{"category": "stability", "score": 95}]
                }
            }
        }
        with patch("sys.stdout") as mock_stdout:
            res = e2e_stability.check_result(result, "テストラベル")
            self.assertTrue(res)
            
            written_texts = "".join([call[0][0] for call in mock_stdout.write.call_args_list])
            self.assertIn("テストラベル", written_texts)
            self.assertIn("スコア: 85点", written_texts)
            self.assertIn("安定稼働: 95点", written_texts)

    def test_check_result_low_score_with_feedback(self):
        """スコアが低く不合格となり、フィードバックが出力されること"""
        result = {
            "status": "completed",
            "result": {
                "quality_score": 60,
                "segments_count": 5,
                "duration_seconds": 60.0,
                "quality_details": {
                    "category_report": [{"category": "stability", "score": 90}],
                    "feedback": ["音声を強化してください", "画質が低いです"]
                }
            }
        }
        with patch("sys.stdout") as mock_stdout:
            res = e2e_stability.check_result(result, "テストラベル")
            self.assertFalse(res)
            
            written_texts = "".join([call[0][0] for call in mock_stdout.write.call_args_list])
            self.assertIn("音声を強化してください", written_texts)

    def test_check_result_low_stability_score(self):
        """stability_score が 90点未満で不合格になること"""
        result = {
            "status": "completed",
            "result": {
                "quality_score": 85,
                "segments_count": 10,
                "duration_seconds": 120.0,
                "quality_details": {
                    "category_report": [{"category": "stability", "score": 80}]
                }
            }
        }
        with patch("sys.stdout") as mock_stdout:
            res = e2e_stability.check_result(result, "テストラベル")
            self.assertFalse(res)

    @patch("time.sleep")
    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_wait_backend_ready_unexpected_exception(self, mock_urlopen, mock_sleep):
        """接続チェック中に URLError 以外の想定外例外が発生した場合のハンドリング"""
        mock_urlopen.side_effect = Exception("Out of memory")
        with patch("sys.stdout") as mock_stdout:
            res = e2e_stability.wait_backend_ready(max_wait=1)
            self.assertFalse(res)
            
            written_texts = "".join([call[0][0] for call in mock_stdout.write.call_args_list])
            self.assertIn("Unexpected error checking backend: Exception: Out of memory", written_texts)
            self.assertIn("Traceback (most recent call last):", written_texts)

    @patch("e2e_stability.wait_backend_ready", return_value=False)
    def test_main_backend_not_ready(self, mock_wait):
        """バックエンドが起動していない場合、sys.exit(1) で終了すること"""
        with self.assertRaises(SystemExit) as cm:
            e2e_stability.main()
        self.assertEqual(cm.exception.code, 1)

    @patch("e2e_stability.wait_backend_ready", return_value=True)
    @patch("e2e_stability.create_test_video", return_value="/tmp/test_13s.mp4")
    @patch("e2e_stability.run_pipeline")
    @patch("e2e_stability.check_result", return_value=True)
    @patch("pathlib.Path.exists", return_value=False) # LONG_VIDEO 存在しない
    def test_main_success_flow(self, mock_exists, mock_check, mock_run, mock_create, mock_wait):
        """全テストが合格（正常系）の場合、sys.exit(0) で終了すること"""
        # run_pipeline のモック結果を設定
        mock_run.return_value = {"status": "completed"}
        
        with patch("pathlib.Path.unlink"): # 連続安定性テスト内での unlink のモック
            with self.assertRaises(SystemExit) as cm:
                e2e_stability.main()
            self.assertEqual(cm.exception.code, 0)

    @patch("e2e_stability.wait_backend_ready", return_value=True)
    @patch("e2e_stability.create_test_video", return_value="/tmp/test_13s.mp4")
    @patch("e2e_stability.run_pipeline")
    @patch("e2e_stability.check_result")
    @patch("pathlib.Path.exists", return_value=False)
    def test_main_failure_flow(self, mock_exists, mock_check, mock_run, mock_create, mock_wait):
        """テストが一部不合格の場合、sys.exit(1) で終了すること"""
        mock_run.return_value = {"status": "completed"}
        # 最初の短尺テストは合格、次の連続テストで不合格を返すように設定
        mock_check.side_effect = [True, True, False, True] # 4回呼ばれる (短尺1, 連続1,2,3)
        
        with patch("pathlib.Path.unlink"):
            with self.assertRaises(SystemExit) as cm:
                e2e_stability.main()
            self.assertEqual(cm.exception.code, 1)

    @patch("e2e_stability.wait_backend_ready", return_value=True)
    @patch("e2e_stability.create_test_video", return_value="/tmp/test_13s.mp4")
    @patch("e2e_stability.run_pipeline")
    @patch("e2e_stability.check_result", return_value=True)
    @patch("pathlib.Path.exists", return_value=True)
    def test_main_with_long_video(self, mock_exists, mock_check, mock_run, mock_create, mock_wait):
        """LONG_VIDEO が存在する場合、長尺テストも実行されること"""
        mock_run.return_value = {"status": "completed"}
        
        with patch("pathlib.Path.unlink"):
            with self.assertRaises(SystemExit) as cm:
                e2e_stability.main()
            self.assertEqual(cm.exception.code, 0)
            
            # 長尺テストが実行され、check_result が5回呼ばれることを確認
            # (短尺1, 長尺1, 連続3)
            self.assertEqual(mock_check.call_count, 5)

    @patch("pathlib.Path.unlink")
    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_run_pipeline_unlink_exception(self, mock_urlopen, mock_unlink):
        """unlink時に例外が発生しても、処理が続行されること (行68のカバー)"""
        mock_unlink.side_effect = OSError("Unlink error")
        
        # 開始成功レスポンス
        mock_start_resp = MagicMock()
        mock_start_resp.read.return_value = b'{"status": "started"}'
        # ステータスレスポンス
        mock_status_resp = MagicMock()
        mock_status_resp.read.return_value = b'{"status": "completed", "result": {"quality_score": 95}}'
        mock_urlopen.side_effect = [mock_start_resp, mock_status_resp]
        
        dummy_video = "/tmp/dummy.mp4"
        result = e2e_stability.run_pipeline(dummy_video, target_minutes=1, timeout=10)
        self.assertEqual(result["status"], "completed")

    @patch("e2e_stability.wait_backend_ready", return_value=True)
    @patch("e2e_stability.create_test_video", return_value="/tmp/test_13s.mp4")
    @patch("e2e_stability.run_pipeline")
    @patch("e2e_stability.check_result", return_value=True)
    @patch("pathlib.Path.exists", return_value=False)
    @patch("pathlib.Path.unlink")
    def test_main_success_flow_with_unlink_exception(self, mock_unlink, mock_exists, mock_check, mock_run, mock_create, mock_wait):
        """main処理内の試行ループで unlink が例外を投げても、処理が続行されること (行198のカバー)"""
        mock_unlink.side_effect = OSError("Unlink failed in main")
        mock_run.return_value = {"status": "completed"}
        
        with self.assertRaises(SystemExit) as cm:
            e2e_stability.main()
        self.assertEqual(cm.exception.code, 0)

    @patch("time.sleep")
    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_direct_execution(self, mock_urlopen, mock_sleep):
        """__name__ == '__main__' の実行をカバーする (行223のカバー)"""
        import urllib.error
        import runpy
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        with self.assertRaises(SystemExit) as cm:
            runpy.run_path(str(Path(e2e_stability.__file__)), run_name="__main__")
        self.assertEqual(cm.exception.code, 1)

    @patch("subprocess.run")
    @patch("pathlib.Path.exists", return_value=False)
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.unlink")
    def test_create_test_video_timeout_expired(self, mock_unlink, mock_mkdir, mock_exists, mock_run):
        """create_test_video で TimeoutExpired が発生した際、unlink が実行され RuntimeError が送出されること"""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ffmpeg", timeout=30)
        
        with self.assertRaises(RuntimeError) as cm:
            e2e_stability.create_test_video(duration=5, output_dir="/tmp/test_dir")
        self.assertIn("FFmpeg process timed out", str(cm.exception))
        mock_unlink.assert_called_once()

    @patch("subprocess.run")
    @patch("pathlib.Path.exists", return_value=False)
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.unlink")
    def test_create_test_video_called_process_error(self, mock_unlink, mock_mkdir, mock_exists, mock_run):
        """create_test_video で CalledProcessError が発生した際、unlink が実行され RuntimeError が送出されること"""
        import subprocess
        mock_run.side_effect = subprocess.CalledProcessError(returncode=1, cmd="ffmpeg")
        
        with self.assertRaises(RuntimeError) as cm:
            e2e_stability.create_test_video(duration=5, output_dir="/tmp/test_dir")
        self.assertIn("FFmpeg process failed", str(cm.exception))
        mock_unlink.assert_called_once()

    @patch("subprocess.run")
    @patch("pathlib.Path.exists", return_value=False)
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.unlink")
    def test_create_test_video_unlink_exception(self, mock_unlink, mock_mkdir, mock_exists, mock_run):
        """create_test_video のエラーハンドリング内で unlink が例外を投げても、無視されて RuntimeError が送出されること"""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ffmpeg", timeout=30)
        mock_unlink.side_effect = OSError("Access denied")
        
        with self.assertRaises(RuntimeError) as cm:
            e2e_stability.create_test_video(duration=5, output_dir="/tmp/test_dir")
        self.assertIn("FFmpeg process timed out", str(cm.exception))

    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_run_pipeline_start_json_decode_error(self, mock_urlopen):
        """開始API呼び出しで JSONDecodeError が発生した場合"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'invalid json'
        mock_urlopen.return_value = mock_resp
        
        dummy_video = "/tmp/dummy.mp4"
        with patch("pathlib.Path.unlink"):
            result = e2e_stability.run_pipeline(dummy_video, target_minutes=1, timeout=10)
            self.assertEqual(result["status"], "error")
            self.assertIn("invalid json", result["error"])

    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_run_pipeline_start_timeout_error(self, mock_urlopen):
        """開始API呼び出しで TimeoutError が発生した場合"""
        mock_urlopen.side_effect = TimeoutError("Request timed out")
        
        dummy_video = "/tmp/dummy.mp4"
        with patch("pathlib.Path.unlink"):
            result = e2e_stability.run_pipeline(dummy_video, target_minutes=1, timeout=10)
            self.assertEqual(result["status"], "error")
            self.assertIn("Start timed out", result["error"])

    @patch("time.sleep")
    @patch("time.time")
    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_run_pipeline_polling_json_decode_error(self, mock_urlopen, mock_time_func, mock_sleep):
        """ポーリング中に JSONDecodeError が発生した場合"""
        mock_time_func.side_effect = [1000.0, 1005.0, 1015.0, 1020.0]
        mock_start_resp = MagicMock()
        mock_start_resp.read.return_value = b'{"status": "started"}'
        mock_status_resp = MagicMock()
        mock_status_resp.read.return_value = b'invalid json'
        mock_urlopen.side_effect = [mock_start_resp, mock_status_resp]
        
        dummy_video = "/tmp/dummy.mp4"
        with patch("pathlib.Path.unlink"):
            result = e2e_stability.run_pipeline(dummy_video, target_minutes=1, timeout=10)
            self.assertEqual(result["status"], "error")
            self.assertIn("Timeout", result["error"])

    @patch("time.sleep")
    @patch("time.time")
    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_run_pipeline_polling_timeout_error(self, mock_urlopen, mock_time_func, mock_sleep):
        """ポーリング中に TimeoutError が発生した場合"""
        mock_time_func.side_effect = [1000.0, 1005.0, 1015.0, 1020.0]
        mock_start_resp = MagicMock()
        mock_start_resp.read.return_value = b'{"status": "started"}'
        mock_urlopen.side_effect = [mock_start_resp, TimeoutError("Timeout checking status")]
        
        dummy_video = "/tmp/dummy.mp4"
        with patch("pathlib.Path.unlink"):
            result = e2e_stability.run_pipeline(dummy_video, target_minutes=1, timeout=10)
            self.assertEqual(result["status"], "error")
            self.assertIn("Timeout", result["error"])

    def test_check_result_not_dict(self):
        """check_result に辞書型ではない result を渡した場合"""
        res = e2e_stability.check_result("not a dict", "test_label")
        self.assertFalse(res)

    def test_check_result_details_not_dict(self):
        """result.result が辞書型ではない場合"""
        result = {"status": "completed", "result": "not a dict"}
        res = e2e_stability.check_result(result, "test_label")
        self.assertFalse(res)

    def test_check_result_quality_details_not_dict_or_missing(self):
        """result.result.quality_details が存在しない、または辞書ではない場合"""
        result = {
            "status": "completed",
            "result": {
                "quality_score": 85,
                "segments_count": 10,
                "duration_seconds": 120.0,
                "quality_details": "not a dict"
            }
        }
        res = e2e_stability.check_result(result, "test_label")
        self.assertTrue(res)

    def test_check_result_category_report_not_list(self):
        """category_report がリストではない場合"""
        result = {
            "status": "completed",
            "result": {
                "quality_score": 85,
                "segments_count": 10,
                "duration_seconds": 120.0,
                "quality_details": {
                    "category_report": "not a list"
                }
            }
        }
        res = e2e_stability.check_result(result, "test_label")
        self.assertTrue(res)

    def test_check_result_feedback_not_list(self):
        """feedback がリストではない場合"""
        result = {
            "status": "completed",
            "result": {
                "quality_score": 60,
                "segments_count": 10,
                "duration_seconds": 120.0,
                "quality_details": {
                    "feedback": "not a list"
                }
            }
        }
        res = e2e_stability.check_result(result, "test_label")
        self.assertFalse(res)

    @patch("time.sleep")
    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_wait_backend_ready_timeout_error(self, mock_urlopen, mock_sleep):
        """wait_backend_ready 中に TimeoutError が発生した場合"""
        mock_urlopen.side_effect = TimeoutError("Request timed out")
        res = e2e_stability.wait_backend_ready(max_wait=1)
        self.assertFalse(res)

    @patch("subprocess.run")
    @patch("pathlib.Path.exists", return_value=False)
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.unlink")
    def test_create_test_video_called_process_error_unlink_exception(self, mock_unlink, mock_mkdir, mock_exists, mock_run):
        """CalledProcessErrorが発生し、さらにunlinkでOSErrorが発生した場合"""
        import subprocess
        mock_run.side_effect = subprocess.CalledProcessError(returncode=1, cmd="ffmpeg")
        mock_unlink.side_effect = OSError("Permission denied")
        with self.assertRaises(RuntimeError) as cm:
            e2e_stability.create_test_video(duration=5, output_dir="/tmp/test_dir")
        self.assertIn("FFmpeg process failed", str(cm.exception))
        mock_unlink.assert_called_once()

    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_run_pipeline_start_url_error(self, mock_urlopen):
        """開始API呼び出しで URLError が発生した場合"""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        dummy_video = "/tmp/dummy.mp4"
        with patch("pathlib.Path.unlink"):
            result = e2e_stability.run_pipeline(dummy_video, target_minutes=1, timeout=10)
            self.assertEqual(result["status"], "error")
            self.assertIn("Start failed due to network", result["error"])

    @patch("time.sleep")
    @patch("time.time")
    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_run_pipeline_polling_url_error(self, mock_urlopen, mock_time_func, mock_sleep):
        """ポーリング中に URLError が発生した場合"""
        import urllib.error
        mock_time_func.side_effect = [1000.0, 1005.0, 1015.0, 1020.0]
        mock_start_resp = MagicMock()
        mock_start_resp.read.return_value = b'{"status": "started"}'
        mock_urlopen.side_effect = [mock_start_resp, urllib.error.URLError("Connection reset")]
        dummy_video = "/tmp/dummy.mp4"
        with patch("pathlib.Path.unlink"):
            result = e2e_stability.run_pipeline(dummy_video, target_minutes=1, timeout=10)
            self.assertEqual(result["status"], "error")
            self.assertIn("Timeout", result["error"])

    def test_verify_thumbnail_quality_success(self):
        """正常な画像（1280x720, 16:9, <4MB）が検証をPASSすること"""
        import io
        from PIL import Image
        img = Image.new("RGB", (1280, 720), color=(255, 0, 0))
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        data = img_bytes.getvalue()
        
        res = e2e_stability.verify_thumbnail_quality(data)
        self.assertTrue(res["valid"])
        self.assertEqual(res["width"], 1280)
        self.assertEqual(res["height"], 720)

    def test_verify_thumbnail_quality_invalid_resolution(self):
        """解像度が1280x720未満の場合にValueErrorを投げること"""
        import io
        from PIL import Image
        img = Image.new("RGB", (640, 360), color=(255, 0, 0))
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        data = img_bytes.getvalue()
        
        with self.assertRaises(ValueError) as cm:
            e2e_stability.verify_thumbnail_quality(data)
        self.assertIn("Resolution must be at least 1280x720", str(cm.exception))

    def test_verify_thumbnail_quality_invalid_aspect_ratio(self):
        """アスペクト比が16:9ではない場合にValueErrorを投げること"""
        import io
        from PIL import Image
        img = Image.new("RGB", (1280, 800), color=(255, 0, 0))
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        data = img_bytes.getvalue()
        
        with self.assertRaises(ValueError) as cm:
            e2e_stability.verify_thumbnail_quality(data)
        self.assertIn("Aspect ratio must be 16:9", str(cm.exception))

    def test_verify_thumbnail_quality_exceeds_size(self):
        """ファイルサイズが4MB以上の場合にValueErrorを投げること"""
        import io
        from PIL import Image
        img = Image.new("RGB", (2560, 1440), color=(255, 0, 0))
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="BMP")
        data = img_bytes.getvalue()
        
        if len(data) < 4 * 1024 * 1024:
            data = data + b"\x00" * (4 * 1024 * 1024 - len(data) + 100)
            
        with self.assertRaises(ValueError) as cm:
            e2e_stability.verify_thumbnail_quality(data)
        self.assertIn("File size exceeds 4MB limit", str(cm.exception))

    def test_verify_thumbnail_quality_corrupted(self):
        """破損した画像データの場合にValueErrorを投げること"""
        invalid_data = b"not a real image data"
        with self.assertRaises(ValueError) as cm:
            e2e_stability.verify_thumbnail_quality(invalid_data)
        self.assertIn("Image is corrupted or invalid format", str(cm.exception))

    def test_generate_thumbnail_success(self):
        """generate_thumbnailがアトミックに画像を生成すること"""
        import tempfile
        import time
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "thumb.png"
            res_path = e2e_stability.generate_thumbnail(out_path, width=1280, height=720, text="Test Atomicity")
            self.assertTrue(Path(res_path).exists())
            
            res = e2e_stability.verify_thumbnail_quality(Path(res_path))
            self.assertTrue(res["valid"])

    def test_stage_bound_agent_integration_with_retries_and_migration(self):
        """StageBoundAgent に登録され、自動リトライ、結果保存、DBマイグレーションの各機能と連携して動作すること"""
        import asyncio
        import sqlite3
        import tempfile
        import time
        import sys
        
        project_root = Path(__file__).resolve().parents[2]
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
            
        from backend.agents.stage_bound_agent import StageBoundAgent
        
        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = Path(tmpdir) / "test_stage_bound.db"
            db_path = str(db_file)
            
            agent = StageBoundAgent(stage_name="thumbnail_stage", db_path=db_path, poll_interval=0.01)
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                task_id = "task_test_p27"
                loop.run_until_complete(agent.register_task(task_id, initial_status="READY", max_retries=2))
                
                async def custom_process(tid):
                    return await e2e_stability.run_thumbnail_stage_task(tid, db_path=db_path)
                
                loop.run_until_complete(agent.start(custom_process))
                
                start_time = time.time()
                completed = False
                while time.time() - start_time < 5.0:
                    status = loop.run_until_complete(agent.get_task_status(task_id))
                    if status == "COMPLETED":
                        completed = True
                        break
                    time.sleep(0.05)
                
                self.assertTrue(completed, f"Task did not complete. Status: {status}")
                
                conn = sqlite3.connect(db_path)
                try:
                    cursor = conn.execute("SELECT * FROM thumbnail_results WHERE task_id = ?", (task_id,))
                    row = cursor.fetchone()
                    self.assertIsNotNone(row)
                    self.assertEqual(row[0], task_id)
                    self.assertIn(task_id, row[1])
                    self.assertEqual(row[2], 1280)
                    self.assertEqual(row[3], 720)
                finally:
                    conn.close()
                loop.run_until_complete(agent.stop())
                
                fail_task_id = "task_fail_p27"
                loop.run_until_complete(agent.register_task(fail_task_id, initial_status="READY", max_retries=2))
                
                fail_count = 0
                async def failing_process(tid):
                    nonlocal fail_count
                    fail_count += 1
                    raise ValueError("Simulated failure")
                
                agent = StageBoundAgent(stage_name="thumbnail_stage", db_path=db_path, poll_interval=0.01)
                loop.run_until_complete(agent.start(failing_process))
                
                start_time = time.time()
                failed_finally = False
                while time.time() - start_time < 5.0:
                    status = loop.run_until_complete(agent.get_task_status(fail_task_id))
                    if status == "FAILED":
                        failed_finally = True
                        break
                    time.sleep(0.05)
                
                self.assertTrue(failed_finally, f"Task did not fail. Status: {status}")
                self.assertEqual(fail_count, 3)
                
                loop.run_until_complete(agent.stop())
            finally:
                try:
                    loop.close()
                finally:
                    asyncio.set_event_loop(None)
                
            project_root = Path(__file__).resolve().parents[2]
            p = _wp("temp_thumbnails") / "task_test_p27.png"
            if p.exists():
                try: p.unlink()
                except OSError: pass

    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_run_pipeline_start_http_exception(self, mock_urlopen):
        """開始API呼び出しで HTTPException が発生した場合"""
        import http.client
        mock_urlopen.side_effect = http.client.HTTPException("HTTP error")
        dummy_video = "/tmp/dummy.mp4"
        with patch("pathlib.Path.unlink"):
            result = e2e_stability.run_pipeline(dummy_video, target_minutes=1, timeout=10)
            self.assertEqual(result["status"], "error")
            self.assertIn("Start failed due to request or decoding error", result["error"])

    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_run_pipeline_start_value_error(self, mock_urlopen):
        """開始API呼び出しで ValueError が発生した場合"""
        mock_urlopen.side_effect = ValueError("Invalid URL scheme")
        dummy_video = "/tmp/dummy.mp4"
        with patch("pathlib.Path.unlink"):
            result = e2e_stability.run_pipeline(dummy_video, target_minutes=1, timeout=10)
            self.assertEqual(result["status"], "error")
            self.assertIn("Start failed due to request or decoding error", result["error"])

    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_run_pipeline_start_unicode_decode_error(self, mock_urlopen):
        """開始API呼び出しで UnicodeDecodeError が発生した場合"""
        mock_urlopen.side_effect = UnicodeDecodeError("utf-8", b"", 0, 1, "invalid start byte")
        dummy_video = "/tmp/dummy.mp4"
        with patch("pathlib.Path.unlink"):
            result = e2e_stability.run_pipeline(dummy_video, target_minutes=1, timeout=10)
            self.assertEqual(result["status"], "error")
            self.assertIn("Start failed due to request or decoding error", result["error"])

    @patch("time.sleep")
    @patch("time.time")
    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_run_pipeline_polling_http_exception(self, mock_urlopen, mock_time_func, mock_sleep):
        """ポーリング中に HTTPException が発生した場合"""
        import http.client
        mock_time_func.side_effect = [1000.0, 1005.0, 1015.0, 1020.0]
        mock_start_resp = MagicMock()
        mock_start_resp.read.return_value = b'{"status": "started"}'
        mock_urlopen.side_effect = [mock_start_resp, http.client.HTTPException("HTTP connection reset")]
        dummy_video = "/tmp/dummy.mp4"
        with patch("pathlib.Path.unlink"):
            result = e2e_stability.run_pipeline(dummy_video, target_minutes=1, timeout=10)
            self.assertEqual(result["status"], "error")
            self.assertIn("Timeout", result["error"])

    @patch("time.sleep")
    @patch("time.time")
    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_run_pipeline_polling_value_error(self, mock_urlopen, mock_time_func, mock_sleep):
        """ポーリング中に ValueError が発生した場合"""
        mock_time_func.side_effect = [1000.0, 1005.0, 1015.0, 1020.0]
        mock_start_resp = MagicMock()
        mock_start_resp.read.return_value = b'{"status": "started"}'
        mock_urlopen.side_effect = [mock_start_resp, ValueError("Invalid state")]
        dummy_video = "/tmp/dummy.mp4"
        with patch("pathlib.Path.unlink"):
            result = e2e_stability.run_pipeline(dummy_video, target_minutes=1, timeout=10)
            self.assertEqual(result["status"], "error")
            self.assertIn("Timeout", result["error"])

    @patch("time.sleep")
    @patch("time.time")
    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_run_pipeline_polling_unicode_decode_error(self, mock_urlopen, mock_time_func, mock_sleep):
        """ポーリング中に UnicodeDecodeError が発生した場合"""
        mock_time_func.side_effect = [1000.0, 1005.0, 1015.0, 1020.0]
        mock_start_resp = MagicMock()
        mock_start_resp.read.return_value = b'{"status": "started"}'
        mock_urlopen.side_effect = [mock_start_resp, UnicodeDecodeError("utf-8", b"", 0, 1, "invalid byte")]
        dummy_video = "/tmp/dummy.mp4"
        with patch("pathlib.Path.unlink"):
            result = e2e_stability.run_pipeline(dummy_video, target_minutes=1, timeout=10)
            self.assertEqual(result["status"], "error")
            self.assertIn("Timeout", result["error"])

    @patch("time.sleep")
    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_wait_backend_ready_http_exception(self, mock_urlopen, mock_sleep):
        """wait_backend_ready 中に HTTPException が発生した場合"""
        import http.client
        mock_urlopen.side_effect = http.client.HTTPException("HTTP test exception")
        with patch("sys.stdout") as mock_stdout:
            res = e2e_stability.wait_backend_ready(max_wait=1)
            self.assertFalse(res)
            written_texts = "".join([call[0][0] for call in mock_stdout.write.call_args_list])
            self.assertIn("Expected error checking backend: HTTPException: HTTP test exception", written_texts)

    @patch("time.sleep")
    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_wait_backend_ready_value_error(self, mock_urlopen, mock_sleep):
        """wait_backend_ready 中に ValueError が発生した場合"""
        mock_urlopen.side_effect = ValueError("Invalid URL scheme")
        with patch("sys.stdout") as mock_stdout:
            res = e2e_stability.wait_backend_ready(max_wait=1)
            self.assertFalse(res)
            written_texts = "".join([call[0][0] for call in mock_stdout.write.call_args_list])
            self.assertIn("Expected error checking backend: ValueError: Invalid URL scheme", written_texts)

    def test_generate_thumbnail_type_error(self):
        """generate_thumbnailで引数タイプエラーを発生させる"""
        with self.assertRaises(ValueError):
            e2e_stability.generate_thumbnail("/tmp/thumb.png", width="invalid_width", height=720)

    @patch("e2e_stability.verify_thumbnail_quality", new_callable=Mock)
    def test_run_thumbnail_stage_task_type_error(self, mock_verify):
        """run_thumbnail_stage_taskでTypeErrorが発生した際のRuntimeErrorへのラップ検証"""
        import asyncio
        mock_verify.side_effect = TypeError("Mocked type error")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            with self.assertRaises(RuntimeError) as cm:
                loop.run_until_complete(e2e_stability.run_thumbnail_stage_task("test_task_type_err", ":memory:"))
            self.assertIn("Thumbnail task failed due to invalid type parameter for task test_task_type_err", str(cm.exception))
        finally:
            try:
                loop.close()
            finally:
                asyncio.set_event_loop(None)

    @patch("e2e_stability.verify_thumbnail_quality", new_callable=Mock)
    def test_run_thumbnail_stage_task_value_error(self, mock_verify):
        """run_thumbnail_stage_taskでValueErrorが発生した際のRuntimeErrorへのラップ検証"""
        import asyncio
        mock_verify.side_effect = ValueError("Mocked value error")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            with self.assertRaises(RuntimeError) as cm:
                loop.run_until_complete(e2e_stability.run_thumbnail_stage_task("test_task_val_err", ":memory:"))
            self.assertIn("Thumbnail task failed due to invalid value parameter for task test_task_val_err", str(cm.exception))
        finally:
            try:
                loop.close()
            finally:
                asyncio.set_event_loop(None)

    @patch("e2e_stability.verify_thumbnail_quality", new_callable=Mock)
    def test_run_thumbnail_stage_task_os_error(self, mock_verify):
        """run_thumbnail_stage_taskでOSErrorが発生した際のRuntimeErrorへのラップ検証"""
        import asyncio
        mock_verify.side_effect = OSError("Mocked I/O error")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            with self.assertRaises(RuntimeError) as cm:
                loop.run_until_complete(e2e_stability.run_thumbnail_stage_task("test_task_os_err", ":memory:"))
            self.assertIn("Thumbnail task file I/O failed for task test_task_os_err", str(cm.exception))
        finally:
            try:
                loop.close()
            finally:
                asyncio.set_event_loop(None)

    @patch("e2e_stability.verify_thumbnail_quality", new_callable=Mock)
    def test_run_thumbnail_stage_task_unexpected_exception(self, mock_verify):
        """run_thumbnail_stage_taskで想定外のExceptionが発生した際のRuntimeErrorへのラップ検証"""
        import asyncio
        mock_verify.side_effect = Exception("Mocked unexpected error")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            with patch("sys.stdout") as mock_stdout:
                with self.assertRaises(RuntimeError) as cm:
                    loop.run_until_complete(e2e_stability.run_thumbnail_stage_task("test_task_unexpected_err", ":memory:"))
                self.assertIn("Unexpected thumbnail task failure for task test_task_unexpected_err", str(cm.exception))
                self.assertIn("Exception - Mocked unexpected error", str(cm.exception))
                
                written_texts = "".join([call[0][0] for call in mock_stdout.write.call_args_list])
                self.assertIn("Unexpected error during run_thumbnail_stage_task for task test_task_unexpected_err", written_texts)
                self.assertIn("Traceback (most recent call last):", written_texts)
        finally:
            try:
                loop.close()
            finally:
                asyncio.set_event_loop(None)

    @patch("e2e_stability.verify_thumbnail_quality", new_callable=Mock)
    def test_run_thumbnail_stage_task_name_error(self, mock_verify):
        """run_thumbnail_stage_taskでNameErrorが発生した際にラップされずそのまま送出されること"""
        import asyncio
        mock_verify.side_effect = NameError("Mocked name error")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            with self.assertRaises(NameError) as cm:
                loop.run_until_complete(e2e_stability.run_thumbnail_stage_task("test_task_name_err", ":memory:"))
            self.assertEqual(str(cm.exception), "Mocked name error")
        finally:
            try:
                loop.close()
            finally:
                asyncio.set_event_loop(None)

    @patch("e2e_stability.verify_thumbnail_quality", new_callable=Mock)
    def test_run_thumbnail_stage_task_attribute_error(self, mock_verify):
        """run_thumbnail_stage_taskでAttributeErrorが発生した際にラップされずそのまま送出されること"""
        import asyncio
        mock_verify.side_effect = AttributeError("Mocked attribute error")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            with self.assertRaises(AttributeError) as cm:
                loop.run_until_complete(e2e_stability.run_thumbnail_stage_task("test_task_attr_err", ":memory:"))
            self.assertEqual(str(cm.exception), "Mocked attribute error")
        finally:
            try:
                loop.close()
            finally:
                asyncio.set_event_loop(None)

    def test_create_test_video_invalid_duration_type(self):
        """create_test_videoに不正な型のdurationを渡した場合にTypeErrorが発生することを確認"""
        with self.assertRaises(TypeError):
            e2e_stability.create_test_video(duration="not_an_int")
        with self.assertRaises(TypeError):
            e2e_stability.create_test_video(duration=True)  # bool型も弾くこと

    def test_create_test_video_invalid_duration_value(self):
        """create_test_videoに負またはゼロのdurationを渡した場合にValueErrorが発生することを確認"""
        with self.assertRaises(ValueError):
            e2e_stability.create_test_video(duration=0)
        with self.assertRaises(ValueError):
            e2e_stability.create_test_video(duration=-5)

    def test_create_test_video_invalid_output_dir_type(self):
        """create_test_videoに不正な型のoutput_dirを渡した場合にTypeErrorが発生することを確認"""
        with self.assertRaises(TypeError):
            e2e_stability.create_test_video(duration=5, output_dir={"invalid": "type"})

    def test_clean_pipeline_files_invalid_video_path_type(self):
        """_clean_pipeline_filesに不正な型のvideo_pathを渡した場合にTypeErrorが発生することを確認"""
        with self.assertRaises(TypeError):
            e2e_stability._clean_pipeline_files(None)

    def test_load_image_invalid_type(self):
        """_load_imageに不正な型のfile_path_or_bytesを渡した場合にTypeErrorが発生することを確認"""
        with self.assertRaises(TypeError):
            e2e_stability._load_image(None)

    @patch("os.path.exists", return_value=True)
    @patch("os.path.getsize", side_effect=OSError("Disk reading error"))
    def test_load_image_os_error_handling(self, mock_getsize, mock_exists):
        """_load_imageにおいてOSエラー（OSError）が発生した場合にOSErrorとして伝播されることを確認"""
        with self.assertRaises(OSError) as cm:
            e2e_stability._load_image("/dummy/path.png")
        self.assertIn("Failed to access thumbnail file", str(cm.exception))

    @patch("sqlite3.connect", new_callable=Mock, side_effect=sqlite3.OperationalError("Mocked db connect fail"))
    @patch("e2e_stability.verify_thumbnail_quality", new_callable=Mock, return_value={"width": 1280, "height": 720, "size_bytes": 100})
    def test_run_thumbnail_stage_task_db_connect_failure(self, mock_verify, mock_connect):
        """sqlite3.connectが失敗した際にUnboundLocalErrorにならず、想定通りRuntimeErrorが送出されること"""
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            with self.assertRaises(RuntimeError) as cm:
                loop.run_until_complete(e2e_stability.run_thumbnail_stage_task("test_task_db_fail", "/invalid/path.db"))
            self.assertIn("Thumbnail task database operation failed for task test_task_db_fail on /invalid/path.db", str(cm.exception))
            self.assertIn("Mocked db connect fail", str(cm.exception))
        finally:
            try:
                loop.close()
            finally:
                asyncio.set_event_loop(None)


    @patch("asyncio.new_event_loop")
    @patch("e2e_stability.run_thumbnail_stage_task", return_value='{"valid": true}', new_callable=MagicMock)
    def test_run_thumbnail_automation_test_closes_loop(self, mock_run, mock_new_loop):
        """_run_thumbnail_automation_test がイベントループを確実にクローズすることを確認"""
        import asyncio
        mock_loop = MagicMock(spec=asyncio.AbstractEventLoop)
        mock_loop.run_until_complete.return_value = '{"valid": true}'
        mock_new_loop.return_value = mock_loop
        
        e2e_stability._run_thumbnail_automation_test()
        
        mock_loop.close.assert_called_once()

    @patch("os.access", return_value=False)
    @patch("pathlib.Path.mkdir")
    def test_create_test_video_permission_error(self, mock_mkdir, mock_access):
        """create_test_video で output_dir に対する書き込み権限がない場合 PermissionError が発生すること"""
        with self.assertRaises(PermissionError):
            e2e_stability.create_test_video(duration=5, output_dir="/tmp/readonly_dir")

    @patch("subprocess.run")
    @patch("pathlib.Path.exists", return_value=False)
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.unlink")
    def test_create_test_video_ffmpeg_not_found(self, mock_unlink, mock_mkdir, mock_exists, mock_run):
        """create_test_video で FileNotFoundError (ffmpeg無し) が発生した際、RuntimeError が送出されること"""
        mock_run.side_effect = FileNotFoundError("[Errno 2] No such file or directory: 'ffmpeg'")
        with self.assertRaises(RuntimeError) as cm:
            e2e_stability.create_test_video(duration=5, output_dir="/tmp/test_dir")
        self.assertIn("FFmpeg executable not found or not executable", str(cm.exception))
        mock_unlink.assert_called_once()

    @patch("subprocess.run")
    @patch("pathlib.Path.exists", return_value=False)
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.unlink")
    def test_create_test_video_generic_os_error(self, mock_unlink, mock_mkdir, mock_exists, mock_run):
        """create_test_video で ffmpeg 実行中に OSError が発生した際、RuntimeError が送出されること"""
        mock_run.side_effect = OSError("Access denied or execution failure")
        with self.assertRaises(RuntimeError) as cm:
            e2e_stability.create_test_video(duration=5, output_dir="/tmp/test_dir")
        self.assertIn("OSError occurred while running FFmpeg", str(cm.exception))
        mock_unlink.assert_called_once()

    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_run_pipeline_start_http_error(self, mock_urlopen):
        """開始API呼び出しで HTTPError が発生した場合、HTTPステータスコードを含んだレスポンスが返ること"""
        import urllib.error
        from io import BytesIO
        fp = BytesIO(b"Internal Server Error")
        # code, msg, hdrs, fp, rfile
        mock_urlopen.side_effect = urllib.error.HTTPError("http://test/api", 500, "Internal Server Error", {}, fp)
        dummy_video = "/tmp/dummy.mp4"
        with patch("pathlib.Path.unlink"):
            result = e2e_stability.run_pipeline(dummy_video, target_minutes=1, timeout=10)
            self.assertEqual(result["status"], "error")
            self.assertIn("Start failed with HTTP status 500: Internal Server Error", result["error"])

    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_run_pipeline_start_connection_error(self, mock_urlopen):
        """開始API呼び出しで ConnectionError が発生した場合のハンドリング"""
        mock_urlopen.side_effect = ConnectionResetError("Connection reset by peer")
        dummy_video = "/tmp/dummy.mp4"
        with patch("pathlib.Path.unlink"):
            result = e2e_stability.run_pipeline(dummy_video, target_minutes=1, timeout=10)
            self.assertEqual(result["status"], "error")
            self.assertIn("Start failed due to connection error", result["error"])

    @patch("time.sleep")
    @patch("time.time")
    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_run_pipeline_polling_connection_error(self, mock_urlopen, mock_time_func, mock_sleep):
        """ポーリング中に ConnectionError が発生した場合の挙動"""
        mock_time_func.side_effect = [1000.0, 1005.0, 1015.0, 1020.0]
        mock_start_resp = MagicMock()
        mock_start_resp.read.return_value = b'{"status": "started"}'
        mock_urlopen.side_effect = [mock_start_resp, ConnectionAbortedError("Connection aborted")]
        dummy_video = "/tmp/dummy.mp4"
        with patch("pathlib.Path.unlink"):
            result = e2e_stability.run_pipeline(dummy_video, target_minutes=1, timeout=10)
            self.assertEqual(result["status"], "error")
            self.assertIn("Timeout", result["error"])

    @patch("time.sleep")
    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_wait_backend_ready_connection_error(self, mock_urlopen, mock_sleep):
        """wait_backend_ready 中に ConnectionError が発生した場合"""
        mock_urlopen.side_effect = ConnectionRefusedError("Connection refused")
        with patch("sys.stdout") as mock_stdout:
            res = e2e_stability.wait_backend_ready(max_wait=1)
            self.assertFalse(res)
            written_texts = "".join([call[0][0] for call in mock_stdout.write.call_args_list])
            self.assertIn("Backend connection failed (attempt 1/1): Connection refused", written_texts)

    @patch("time.sleep")
    @patch("time.time")
    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_run_pipeline_polling_http_error(self, mock_urlopen, mock_time_func, mock_sleep):
        """ポーリング中に HTTPError が発生した場合の挙動"""
        import urllib.error
        mock_time_func.side_effect = [1000.0, 1005.0, 1015.0, 1020.0]
        mock_start_resp = MagicMock()
        mock_start_resp.read.return_value = b'{"status": "started"}'
        
        http_error = urllib.error.HTTPError("http://test/status", 500, "Internal Server Error", {}, None)
        mock_urlopen.side_effect = [mock_start_resp, http_error]
        
        dummy_video = "/tmp/dummy.mp4"
        with patch("pathlib.Path.unlink"):
            result = e2e_stability.run_pipeline(dummy_video, target_minutes=1, timeout=10)
            self.assertEqual(result["status"], "error")
            self.assertIn("Timeout", result["error"])

    @patch("time.sleep")
    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_wait_backend_ready_http_error(self, mock_urlopen, mock_sleep):
        """wait_backend_ready 中に HTTPError が発生した場合"""
        import urllib.error
        http_error = urllib.error.HTTPError("http://test/ready", 500, "Internal Server Error", {}, None)
        mock_urlopen.side_effect = http_error
        with patch("sys.stdout") as mock_stdout:
            res = e2e_stability.wait_backend_ready(max_wait=1)
            self.assertFalse(res)
            written_texts = "".join([call[0][0] for call in mock_stdout.write.call_args_list])
            self.assertIn("Backend HTTP error (attempt 1/1): status 500", written_texts)

    @patch("os.path.exists", return_value=False)
    def test_load_image_file_not_found(self, mock_exists):
        """_load_imageでファイルが存在しない場合にFileNotFoundErrorが送出されること"""
        with self.assertRaises(FileNotFoundError):
            e2e_stability._load_image("/dummy/non_existent_file.png")

    @patch("e2e_stability._load_image")
    def test_validate_image_metrics_attribute_error(self, mock_load):
        """_validate_image_metrics で画像サイズ取得に失敗した際のValueErrorの発生を検証"""
        class BadImage:
            @property
            def size(self):
                raise AttributeError("Mocked size access failure")
        mock_load.return_value = (BadImage(), 100)
        with self.assertRaises(ValueError) as cm:
            e2e_stability.verify_thumbnail_quality("/dummy/path.png")
        self.assertIn("Failed to load image for resolution check: Mocked size access failure", str(cm.exception))

    def test_generate_thumbnail_invalid_dimensions(self):
        """generate_thumbnailに0以下のサイズを渡した場合にValueErrorが送出されること"""
        with self.assertRaises(ValueError):
            e2e_stability.generate_thumbnail("/tmp/thumb.png", width=0, height=720)
        with self.assertRaises(ValueError):
            e2e_stability.generate_thumbnail("/tmp/thumb.png", width=1280, height=-10)

    @patch("os.rename", side_effect=OSError("Rename failed"))
    @patch("os.path.exists", return_value=False)
    @patch("os.makedirs")
    @patch("e2e_stability._safe_unlink")
    def test_generate_thumbnail_rename_failure_raising(self, mock_unlink, mock_makedirs, mock_exists, mock_rename):
        """os.renameが失敗し、かつターゲットファイルが存在しない場合にOSErrorが送出されること"""
        with self.assertRaises(OSError):
            e2e_stability.generate_thumbnail("/tmp/output.png")

    @patch("sqlite3.connect", new_callable=Mock)
    @patch("e2e_stability.verify_thumbnail_quality", new_callable=Mock, return_value={"width": 1280, "height": 720, "size_bytes": 100})
    def test_run_thumbnail_stage_task_conn_close_error(self, mock_verify, mock_connect):
        """run_thumbnail_stage_taskでconn.close()時にsqlite3.Errorが発生しても処理が継続すること"""
        import asyncio
        import json
        mock_conn = MagicMock()
        mock_conn.close = MagicMock(side_effect=sqlite3.Error("Mocked close error"))
        mock_connect.return_value = mock_conn
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            res = loop.run_until_complete(e2e_stability.run_thumbnail_stage_task("test_close_err", ":memory:"))
            info = json.loads(res)
            self.assertEqual(info["width"], 1280)
            mock_conn.close.assert_called_once()
        finally:
            try:
                loop.close()
            finally:
                asyncio.set_event_loop(None)

    @patch("e2e_stability.run_thumbnail_stage_task", new_callable=Mock, side_effect=RuntimeError("Task execution failure"))
    @patch("asyncio.new_event_loop")
    def test_run_thumbnail_automation_test_exception(self, mock_new_loop, mock_run_task):
        """_run_thumbnail_automation_test内で例外が発生した際、passed = Falseが記録されること"""
        import asyncio
        mock_loop = MagicMock(spec=asyncio.AbstractEventLoop)
        mock_loop.run_until_complete.side_effect = RuntimeError("Task execution failure")
        mock_new_loop.return_value = mock_loop
        
        with patch("sys.stdout") as mock_stdout:
            e2e_stability._run_thumbnail_automation_test()
            written_texts = "".join([call[0][0] for call in mock_stdout.write.call_args_list])
            self.assertIn("サムネイル自動化テスト失敗: Task execution failure", written_texts)

    def test_run_pipeline_invalid_arguments(self):
        """run_pipelineに不正な引数を渡した際に適切な例外が発生することを確認"""
        with self.assertRaises(TypeError):
            e2e_stability.run_pipeline(None)
        with self.assertRaises(TypeError):
            e2e_stability.run_pipeline("/tmp/video.mp4", target_minutes="three")
        with self.assertRaises(ValueError):
            e2e_stability.run_pipeline("/tmp/video.mp4", target_minutes=0)
        with self.assertRaises(ValueError):
            e2e_stability.run_pipeline("/tmp/video.mp4", target_minutes=-1)
        with self.assertRaises(TypeError):
            e2e_stability.run_pipeline("/tmp/video.mp4", timeout="600")
        with self.assertRaises(ValueError):
            e2e_stability.run_pipeline("/tmp/video.mp4", timeout=0)
        with self.assertRaises(ValueError):
            e2e_stability.run_pipeline("/tmp/video.mp4", timeout=-10)


    @patch("time.sleep")
    @patch("time.time")
    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_poll_pipeline_status_swallows_no_programmatic_errors(self, mock_urlopen, mock_time_func, mock_sleep):
        """ポーリング中に TypeError が発生した場合に握り潰されずに再レイズされること"""
        mock_time_func.side_effect = [1000.0, 1005.0]
        mock_urlopen.side_effect = TypeError("Programmatic type error")
        
        dummy_video = "/tmp/dummy.mp4"
        with patch("pathlib.Path.unlink"):
            with self.assertRaises(TypeError) as cm:
                e2e_stability.run_pipeline(dummy_video, target_minutes=1, timeout=10)
            self.assertEqual(str(cm.exception), "Programmatic type error")

    @patch("time.sleep")
    @patch("urllib.request.urlopen", new_callable=Mock)
    def test_wait_backend_ready_swallows_no_programmatic_errors(self, mock_urlopen, mock_sleep):
        """wait_backend_ready 中に AttributeError が発生した場合に握り潰されずに再レイズされること"""
        mock_urlopen.side_effect = AttributeError("Programmatic attribute error")
        with self.assertRaises(AttributeError) as cm:
            e2e_stability.wait_backend_ready(max_wait=2)
        self.assertEqual(str(cm.exception), "Programmatic attribute error")

    @patch("urllib.request.urlopen")
    def test_urlopen_closed_after_use(self, mock_urlopen):
        """urlopen で取得したレスポンスが使用後に close されること"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"status": "completed", "result": {}}'
        mock_urlopen.return_value = mock_resp
        
        e2e_stability._trigger_pipeline_api("/tmp/dummy.mp4", target_minutes=1)
        mock_resp.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()


