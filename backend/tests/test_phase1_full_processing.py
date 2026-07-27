"""
test_phase1_full_processing.py — phase1_full_processing.py のユニットテスト
ヘルパー関数（get_short_path, run_ffmpeg_with_retry, process_chunk, concat_videos）をカバー。
"""
import sys
import pytest
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

_backend_dir = str(Path(__file__).resolve().parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from phase1_full_processing import (
    get_short_path,
    run_ffmpeg_with_retry,
    process_chunk,
    concat_videos,
)


class TestGetShortPath:
    """get_short_path() のテスト"""

    def test_nonexistent_path_returns_abspath(self):
        """存在しないパスの場合、absパスをそのまま返す"""
        result = get_short_path("nonexistent_file.mp4")
        assert Path(result).is_absolute()

    def test_existing_path(self, tmp_path):
        """存在するファイルの場合、短いパスを返す（Windowsのみ有効）"""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")
        result = get_short_path(str(test_file))
        assert len(result) > 0
        # Windows短縮パスは元パスと同じか短い
        assert Path(result).is_absolute()

    @patch("phase1_full_processing.os.path.exists", return_value=True)
    @patch("phase1_full_processing._GetShortPathNameW", return_value=0)
    def test_api_failure_returns_original_path(self, mock_get_short_path, mock_exists):
        """API呼び出しが失敗（0を返却）した場合、元のパスをそのまま返す"""
        import os
        result = get_short_path("C:\\some_existing_file.mp4")
        assert result == os.path.abspath("C:\\some_existing_file.mp4")


class TestRunFfmpegWithRetry:
    """run_ffmpeg_with_retry() のテスト"""

    @patch("phase1_full_processing.subprocess.run")
    def test_success_first_attempt(self, mock_run):
        """1回目で成功"""
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        success, _, error = run_ffmpeg_with_retry(["ffmpeg", "-version"], "test")
        assert success is True
        assert error is None
        assert mock_run.call_count == 1

    @patch("phase1_full_processing.subprocess.run")
    @patch("phase1_full_processing.time.sleep")
    def test_retry_then_success(self, mock_sleep, mock_run):
        """1回失敗して2回目で成功"""
        mock_run.side_effect = [
            MagicMock(returncode=1, stderr="error"),
            MagicMock(returncode=0, stderr=""),
        ]
        success, _, error = run_ffmpeg_with_retry(["ffmpeg"], "test", max_retries=2)
        assert success is True
        assert mock_run.call_count == 2

    @patch("phase1_full_processing.subprocess.run")
    @patch("phase1_full_processing.time.sleep")
    def test_all_retries_fail(self, mock_sleep, mock_run):
        """全リトライ失敗"""
        mock_run.return_value = MagicMock(returncode=1, stderr="persistent error")
        success, _, error = run_ffmpeg_with_retry(["ffmpeg"], "test", max_retries=3)
        assert success is False
        assert "Failed after 3 attempts" in error

    @patch("phase1_full_processing.subprocess.run")
    def test_timeout_handling(self, mock_run):
        """TimeoutExpired の処理"""
        mock_run.side_effect = subprocess.TimeoutExpired("ffmpeg", 300)
        success, _, error = run_ffmpeg_with_retry(["ffmpeg"], "test", max_retries=1, timeout_sec=300)
        assert success is False

    @patch("phase1_full_processing.subprocess.run")
    def test_general_exception(self, mock_run):
        """一般的な例外の処理"""
        mock_run.side_effect = OSError("disk full")
        success, _, error = run_ffmpeg_with_retry(["ffmpeg"], "test", max_retries=1)
        assert success is False

    @patch("phase1_full_processing.subprocess.run")
    def test_stderr_truncation(self, mock_run):
        """stderr が200文字に切り詰められる"""
        mock_run.return_value = MagicMock(returncode=1, stderr="x" * 500)
        success, _, error = run_ffmpeg_with_retry(["ffmpeg"], "test", max_retries=1)
        assert success is False

    @patch("phase1_full_processing.subprocess.run")
    def test_empty_stderr(self, mock_run):
        """stderr が空の場合"""
        mock_run.return_value = MagicMock(returncode=1, stderr="")
        success, _, error = run_ffmpeg_with_retry(["ffmpeg"], "test", max_retries=1)
        assert success is False

    @patch("phase1_full_processing.subprocess.run")
    def test_timeout_retry_until_fail(self, mock_run):
        """TimeoutExpired が連続して発生し、リトライ上限に達して失敗する"""
        mock_run.side_effect = subprocess.TimeoutExpired("ffmpeg", 300)
        success, _, error = run_ffmpeg_with_retry(["ffmpeg"], "test", max_retries=3)
        assert success is False
        assert mock_run.call_count == 3
        assert "Failed after 3 attempts" in error

    @patch("phase1_full_processing.subprocess.run")
    @patch("phase1_full_processing.time.sleep")
    def test_timeout_retry_then_success(self, mock_sleep, mock_run):
        """最初は TimeoutExpired が発生するが、リトライで成功する"""
        mock_run.side_effect = [
            subprocess.TimeoutExpired("ffmpeg", 300),
            MagicMock(returncode=0, stderr=""),
        ]
        success, _, error = run_ffmpeg_with_retry(["ffmpeg"], "test", max_retries=3)
        assert success is True
        assert mock_run.call_count == 2
        assert mock_sleep.call_count == 0

    @patch("phase1_full_processing.subprocess.run")
    def test_exception_retry_until_fail(self, mock_run):
        """一般例外（OSError）が連続して発生し、リトライ上限に達して失敗する"""
        mock_run.side_effect = OSError("disk full")
        success, _, error = run_ffmpeg_with_retry(["ffmpeg"], "test", max_retries=3)
        assert success is False
        assert mock_run.call_count == 3
        assert "Failed after 3 attempts" in error

    @patch("phase1_full_processing.subprocess.run")
    @patch("phase1_full_processing.time.sleep")
    def test_exception_retry_then_success(self, mock_sleep, mock_run):
        """最初は一般例外が発生するが、リトライで成功する"""
        mock_run.side_effect = [
            OSError("temporary network failure"),
            MagicMock(returncode=0, stderr=""),
        ]
        success, _, error = run_ffmpeg_with_retry(["ffmpeg"], "test", max_retries=3)
        assert success is True
        assert mock_run.call_count == 2
        assert mock_sleep.call_count == 0


class TestProcessChunk:
    """process_chunk() のテスト"""

    @patch("phase1_full_processing.run_ffmpeg_with_retry", return_value=(True, None, None))
    def test_success(self, mock_retry):
        result = process_chunk("input.mp4", "output.mp4", 0, 300, "Test chunk")
        assert result is True
        mock_retry.assert_called_once()

    @patch("phase1_full_processing.run_ffmpeg_with_retry", return_value=(False, None, "error"))
    def test_failure(self, mock_retry):
        result = process_chunk("input.mp4", "output.mp4", 0, 300, "Test chunk")
        assert result is False


class TestConcatVideos:
    """concat_videos() のテスト"""

    @patch("phase1_full_processing.run_ffmpeg_with_retry", return_value=(True, None, None))
    def test_success(self, mock_retry, tmp_path):
        files = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        for f in files:
            f.touch()
        output = tmp_path / "output.mp4"
        result = concat_videos(files, output)
        assert result is True
        # concat_list.txt が作成される
        assert (tmp_path / "concat_list.txt").exists()

    @patch("phase1_full_processing.run_ffmpeg_with_retry", return_value=(False, None, "error"))
    def test_failure(self, mock_retry, tmp_path):
        files = [tmp_path / "a.mp4"]
        files[0].touch()
        output = tmp_path / "output.mp4"
        result = concat_videos(files, output)
        assert result is False


class TestGetShortPathBufferExpansion:
    """get_short_path() のバッファ拡張ループのテスト"""

    @patch("phase1_full_processing.os.path.exists", return_value=True)
    @patch("phase1_full_processing._GetShortPathNameW")
    def test_buffer_expansion(self, mock_get_short_path, mock_exists):
        def side_effect(path, buf, size):
            if size == 256:
                return 300
            elif size == 300:
                buf.value = "C:\\SHORTP~1"
                return 10
            return 0

        mock_get_short_path.side_effect = side_effect
        result = get_short_path("C:\\LongPathNameThatNeedsExpansion")
        assert result == "C:\\SHORTP~1"
        assert mock_get_short_path.call_count == 2


class TestPhase1FullProcessing:
    """phase1_full_processing() 関数のテスト"""

    @patch("phase1_full_processing.get_short_path", side_effect=lambda x: x)
    @patch("phase1_full_processing.process_chunk")
    @patch("phase1_full_processing.concat_videos")
    @patch("phase1_full_processing.run_ffmpeg_with_retry")
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.exists", autospec=True)
    @patch("pathlib.Path.stat", autospec=True)
    @patch("builtins.open", new_callable=mock_open)
    def test_full_processing_success(
        self, mock_file, mock_stat, mock_exists, mock_mkdir,
        mock_ffmpeg, mock_concat, mock_process_chunk, mock_get_short
    ):
        """すべて成功する正常系シナリオ"""
        mock_process_chunk.return_value = True
        mock_concat.return_value = True
        mock_ffmpeg.return_value = (True, None, None)

        exists_dict = {}

        def exists_side_effect(path_self):
            name = path_self.name
            if "scene01_chunk" in name:
                if name not in exists_dict:
                    exists_dict[name] = True
                    return False
                return True
            return True

        mock_exists.side_effect = exists_side_effect

        mock_stat_res = MagicMock()
        mock_stat_res.st_size = 5000000
        mock_stat.side_effect = lambda self: mock_stat_res

        from phase1_full_processing import phase1_full_processing
        results = phase1_full_processing()

        assert results["scene01_chunks"] == [True] * 6
        assert results["scene02"] is True
        assert results["scene04"] is True
        assert results["final_concat"] is True

        mock_mkdir.assert_called()
        mock_file.assert_called()

    @patch("phase1_full_processing.get_short_path", side_effect=lambda x: x)
    @patch("phase1_full_processing.process_chunk")
    @patch("phase1_full_processing.concat_videos")
    @patch("phase1_full_processing.run_ffmpeg_with_retry")
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.exists", autospec=True)
    @patch("pathlib.Path.stat", autospec=True)
    @patch("builtins.open", new_callable=mock_open)
    def test_full_processing_chunks_exist(
        self, mock_file, mock_stat, mock_exists, mock_mkdir,
        mock_ffmpeg, mock_concat, mock_process_chunk, mock_get_short
    ):
        """すでにチャンクファイルが存在し、スキップされるシナリオ"""
        mock_process_chunk.return_value = True
        mock_concat.return_value = True
        mock_ffmpeg.return_value = (True, None, None)

        mock_exists.side_effect = lambda self: True

        mock_stat_res = MagicMock()
        mock_stat_res.st_size = 2000000
        mock_stat.side_effect = lambda self: mock_stat_res

        from phase1_full_processing import phase1_full_processing
        results = phase1_full_processing()

        assert results["scene01_chunks"] == [True] * 6
        mock_process_chunk.assert_not_called()

    @patch("phase1_full_processing.get_short_path", side_effect=lambda x: x)
    @patch("phase1_full_processing.process_chunk")
    @patch("phase1_full_processing.concat_videos")
    @patch("phase1_full_processing.run_ffmpeg_with_retry")
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.exists", autospec=True)
    @patch("pathlib.Path.stat", autospec=True)
    @patch("builtins.open", new_callable=mock_open)
    def test_full_processing_some_chunks_fail(
        self, mock_file, mock_stat, mock_exists, mock_mkdir,
        mock_ffmpeg, mock_concat, mock_process_chunk, mock_get_short
    ):
        """チャンクが一部失敗するが、5つ以上成功するため結合されるシナリオ"""
        mock_process_chunk.side_effect = [True, True, True, True, True, False]
        mock_concat.return_value = True
        mock_ffmpeg.return_value = (True, None, None)

        exists_dict = {}

        def exists_side_effect(path_self):
            name = path_self.name
            if name == "scene01_chunk6.mp4":
                return False
            if "scene01_chunk" in name:
                if name not in exists_dict:
                    exists_dict[name] = True
                    return False
                return True
            return True

        mock_exists.side_effect = exists_side_effect

        mock_stat_res = MagicMock()
        mock_stat_res.st_size = 5000000
        mock_stat.side_effect = lambda self: mock_stat_res

        from phase1_full_processing import phase1_full_processing
        results = phase1_full_processing()

        assert results["scene01_chunks"] == [True, True, True, True, True, False]
        mock_concat.assert_any_call(
            [
                Path(r"C:\Users\PC_User\Desktop\script\video-automation\backend\temp\phase1_final\scene01_chunk1.mp4"),
                Path(r"C:\Users\PC_User\Desktop\script\video-automation\backend\temp\phase1_final\scene01_chunk2.mp4"),
                Path(r"C:\Users\PC_User\Desktop\script\video-automation\backend\temp\phase1_final\scene01_chunk3.mp4"),
                Path(r"C:\Users\PC_User\Desktop\script\video-automation\backend\temp\phase1_final\scene01_chunk4.mp4"),
                Path(r"C:\Users\PC_User\Desktop\script\video-automation\backend\temp\phase1_final\scene01_chunk5.mp4"),
            ],
            Path(r"C:\Users\PC_User\Desktop\script\video-automation\backend\temp\phase1_final\scene01_final.mp4")
        )

    @patch("phase1_full_processing.get_short_path", side_effect=lambda x: x)
    @patch("phase1_full_processing.process_chunk")
    @patch("phase1_full_processing.concat_videos")
    @patch("phase1_full_processing.run_ffmpeg_with_retry")
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.exists", autospec=True)
    @patch("pathlib.Path.stat", autospec=True)
    @patch("builtins.open", new_callable=mock_open)
    def test_full_processing_too_many_failures(
        self, mock_file, mock_stat, mock_exists, mock_mkdir,
        mock_ffmpeg, mock_concat, mock_process_chunk, mock_get_short
    ):
        """チャンク失敗が多く（成功4以下）、シーン01の結合がスキップされるシナリオ"""
        mock_process_chunk.side_effect = [True, True, True, True, False, False]
        mock_concat.return_value = True
        mock_ffmpeg.return_value = (True, None, None)

        exists_dict = {}

        def exists_side_effect(path_self):
            name = path_self.name
            if name in ["scene01_chunk5.mp4", "scene01_chunk6.mp4", "scene01_final.mp4"]:
                return False
            if "scene01_chunk" in name:
                if name not in exists_dict:
                    exists_dict[name] = True
                    return False
                return True
            return True

        mock_exists.side_effect = exists_side_effect

        mock_stat_res = MagicMock()
        mock_stat_res.st_size = 5000000
        mock_stat.side_effect = lambda self: mock_stat_res

        from phase1_full_processing import phase1_full_processing
        results = phase1_full_processing()

        assert results["scene01_chunks"] == [True, True, True, True, False, False]
        assert results["final_concat"] is True

    @patch("phase1_full_processing.get_short_path", side_effect=lambda x: x)
    @patch("phase1_full_processing.process_chunk")
    @patch("phase1_full_processing.concat_videos")
    @patch("phase1_full_processing.run_ffmpeg_with_retry")
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.exists", autospec=True)
    @patch("pathlib.Path.stat", autospec=True)
    @patch("builtins.open", new_callable=mock_open)
    def test_full_processing_not_enough_scenes(
        self, mock_file, mock_stat, mock_exists, mock_mkdir,
        mock_ffmpeg, mock_concat, mock_process_chunk, mock_get_short
    ):
        """シーン数が足りず（3未満）、最終結合がスキップされるシナリオ"""
        mock_process_chunk.return_value = True
        mock_concat.return_value = True
        mock_ffmpeg.return_value = (True, None, None)

        mock_exists.side_effect = lambda self: False

        from phase1_full_processing import phase1_full_processing
        results = phase1_full_processing()

        assert results["final_concat"] is False

    @patch("phase1_full_processing.get_short_path", side_effect=lambda x: x)
    @patch("phase1_full_processing.process_chunk")
    @patch("phase1_full_processing.concat_videos")
    @patch("phase1_full_processing.run_ffmpeg_with_retry")
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.exists", autospec=True)
    @patch("pathlib.Path.stat", autospec=True)
    @patch("builtins.open", new_callable=mock_open)
    def test_full_processing_scene01_concat_fail(
        self, mock_file, mock_stat, mock_exists, mock_mkdir,
        mock_ffmpeg, mock_concat, mock_process_chunk, mock_get_short
    ):
        """シーン01の結合が失敗するシナリオ"""
        mock_process_chunk.return_value = True
        mock_concat.side_effect = [False, True]
        mock_ffmpeg.return_value = (True, None, None)

        exists_dict = {}

        def exists_side_effect(path_self):
            name = path_self.name
            if "scene01_chunk" in name:
                if name not in exists_dict:
                    exists_dict[name] = True
                    return False
                return True
            return True

        mock_exists.side_effect = exists_side_effect

        mock_stat_res = MagicMock()
        mock_stat_res.st_size = 5000000
        mock_stat.side_effect = lambda self: mock_stat_res

        from phase1_full_processing import phase1_full_processing
        results = phase1_full_processing()

        assert results["final_concat"] is True

    @patch("phase1_full_processing.get_short_path", side_effect=lambda x: x)
    @patch("phase1_full_processing.process_chunk")
    @patch("phase1_full_processing.concat_videos")
    @patch("phase1_full_processing.run_ffmpeg_with_retry")
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.exists", autospec=True)
    @patch("pathlib.Path.stat", autospec=True)
    @patch("builtins.open", new_callable=mock_open)
    def test_full_processing_final_concat_fail(
        self, mock_file, mock_stat, mock_exists, mock_mkdir,
        mock_ffmpeg, mock_concat, mock_process_chunk, mock_get_short
    ):
        """最終結合が失敗するシナリオ"""
        mock_process_chunk.return_value = True
        mock_concat.side_effect = [True, False]
        mock_ffmpeg.return_value = (True, None, None)

        exists_dict = {}

        def exists_side_effect(path_self):
            name = path_self.name
            if "scene01_chunk" in name:
                if name not in exists_dict:
                    exists_dict[name] = True
                    return False
                return True
            return True

        mock_exists.side_effect = exists_side_effect

        mock_stat_res = MagicMock()
        mock_stat_res.st_size = 5000000
        mock_stat.side_effect = lambda self: mock_stat_res

        from phase1_full_processing import phase1_full_processing
        results = phase1_full_processing()

        assert results["final_concat"] is False

    @patch("phase1_full_processing.get_short_path", side_effect=lambda x: x)
    @patch("phase1_full_processing.process_chunk")
    @patch("phase1_full_processing.concat_videos")
    @patch("phase1_full_processing.run_ffmpeg_with_retry")
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.exists", autospec=True)
    @patch("pathlib.Path.stat", autospec=True)
    @patch("builtins.open", new_callable=mock_open)
    def test_full_processing_chunks_exist_but_too_small(
        self, mock_file, mock_stat, mock_exists, mock_mkdir,
        mock_ffmpeg, mock_concat, mock_process_chunk, mock_get_short
    ):
        """チャンクファイルは存在するが、サイズが1MB以下（境界値）のため再処理される"""
        mock_process_chunk.return_value = True
        mock_concat.return_value = True
        mock_ffmpeg.return_value = (True, None, None)

        mock_exists.side_effect = lambda self: True

        # 1MB (1,000,000バイト) 以下のサイズに設定して境界値をテスト
        mock_stat_res = MagicMock()
        mock_stat_res.st_size = 999999
        mock_stat.side_effect = lambda self: mock_stat_res

        from phase1_full_processing import phase1_full_processing
        results = phase1_full_processing()

        # スキップされずに process_chunk が呼び出されること
        assert results["scene01_chunks"] == [True] * 6
        assert mock_process_chunk.call_count == 6

    @patch("phase1_full_processing.get_short_path", side_effect=lambda x: x)
    @patch("phase1_full_processing.process_chunk")
    @patch("phase1_full_processing.concat_videos")
    @patch("phase1_full_processing.run_ffmpeg_with_retry")
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.exists", autospec=True)
    @patch("pathlib.Path.stat", autospec=True)
    @patch("builtins.open", new_callable=mock_open)
    def test_full_processing_exactly_three_scenes(
        self, mock_file, mock_stat, mock_exists, mock_mkdir,
        mock_ffmpeg, mock_concat, mock_process_chunk, mock_get_short
    ):
        """シーン数がちょうど3つの場合、最終結合が実行される"""
        mock_process_chunk.return_value = True
        mock_concat.return_value = True
        mock_ffmpeg.return_value = (True, None, None)

        # scene03_final.mp4 は存在しないが、他の3つが存在する
        def exists_side_effect(path_self):
            name = path_self.name
            if name == "scene03_final.mp4":
                return False
            return True

        mock_exists.side_effect = exists_side_effect

        mock_stat_res = MagicMock()
        mock_stat_res.st_size = 5000000
        mock_stat.side_effect = lambda self: mock_stat_res

        from phase1_full_processing import phase1_full_processing
        results = phase1_full_processing()

        # ちょうど3つのシーンで concat_videos が呼ばれること
        assert results["final_concat"] is True
        mock_concat.assert_any_call(
            [
                Path(r"C:\Users\PC_User\Desktop\script\video-automation\backend\temp\phase1_final\scene01_final.mp4"),
                Path(r"C:\Users\PC_User\Desktop\script\video-automation\backend\temp\phase1_final\scene02_final.mp4"),
                Path(r"C:\Users\PC_User\Desktop\script\video-automation\backend\temp\phase1_final\scene04_final.mp4"),
            ],
            Path(r"C:\Users\PC_User\Desktop\script\video-automation\soul_narrative_complete.mp4")
        )


class TestPhase1MainBlock:
    """__main__ 実行ブロックのテスト"""

    @patch("subprocess.run")
    @patch("phase1_full_processing.get_short_path", side_effect=lambda x: x)
    @patch("phase1_full_processing.process_chunk")
    @patch("phase1_full_processing.concat_videos")
    @patch("phase1_full_processing.run_ffmpeg_with_retry")
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.exists", autospec=True)
    @patch("pathlib.Path.stat", autospec=True)
    @patch("builtins.open", new_callable=mock_open)
    def test_main_execution(
        self, mock_file, mock_stat, mock_exists, mock_mkdir,
        mock_ffmpeg, mock_concat, mock_process_chunk, mock_get_short,
        mock_sub_run
    ):
        import runpy

        mock_sub_run.return_value = MagicMock(returncode=0, stderr="")
        mock_process_chunk.return_value = True
        mock_concat.return_value = True
        mock_ffmpeg.return_value = (True, None, None)

        exists_dict = {}

        def exists_side_effect(path_self):
            name = path_self.name
            if "scene01_chunk" in name:
                if name not in exists_dict:
                    exists_dict[name] = True
                    return False
                return True
            return True

        mock_exists.side_effect = exists_side_effect

        mock_stat_res = MagicMock()
        mock_stat_res.st_size = 5000000
        mock_stat.side_effect = lambda self: mock_stat_res

        with patch("sys.argv", ["phase1_full_processing.py"]):
            runpy.run_path("backend/phase1_full_processing.py", run_name="__main__")




