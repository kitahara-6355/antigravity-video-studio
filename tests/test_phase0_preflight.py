import pytest
import os
import subprocess
import json
import ctypes
from pathlib import Path
from unittest.mock import MagicMock, patch
import backend.phase0_preflight
from backend.phase0_preflight import (
    get_short_path,
    run_ffmpeg_with_retry,
    phase0_preflight_check
)

# =========================================================================
# get_short_path のテスト
# =========================================================================

def test_get_short_path_not_exists():
    """存在しないパスが渡されたとき、元のパスがそのまま返ることを検証"""
    path = "C:\\non_existent_path_xyz_123"
    assert get_short_path(path) == os.path.abspath(path)

def test_get_short_path_exists_real(tmp_path):
    """存在するパスが渡されたとき、パスが正常に返ることを検証"""
    temp_file = tmp_path / "test_file.txt"
    temp_file.write_text("hello")
    res = get_short_path(str(temp_file))
    assert os.path.exists(res)

def test_get_short_path_buffer_resize():
    """バッファサイズが不足している場合（needed > output_buf_size）、バッファが自動拡張されることを検証"""
    # os.path.exists が True を返すようにモック
    with patch("os.path.exists", return_value=True):
        mock_get_short = MagicMock()
        
        def side_effect(path, buf, size):
            # 1回目はバッファサイズ256に対して300を返し、バッファ拡張をトリガーする
            if size == 256:
                return 300
            else:
                # 拡張されたバッファに値を格納する
                buf.value = "C:\\SHORT~1\\test.txt"
                return len(buf.value)
                
        mock_get_short.side_effect = side_effect
        
        with patch("backend.phase0_preflight._GetShortPathNameW", mock_get_short):
            res = get_short_path("C:\\some_long_path\\test.txt")
            assert res == "C:\\SHORT~1\\test.txt"

# =========================================================================
# run_ffmpeg_with_retry のテスト
# =========================================================================

def test_run_ffmpeg_success():
    """FFmpegコマンドが1回の試行で成功するケース"""
    mock_result = MagicMock()
    mock_result.returncode = 0
    
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        success, out, err = run_ffmpeg_with_retry(["ffmpeg", "-i", "in.mp4"], "test_desc")
        assert success is True
        assert out is None
        assert err is None
        mock_run.assert_called_once()

def test_run_ffmpeg_retry_and_fail():
    """リトライ回数上限まで失敗し続けるケース"""
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "FFmpeg error message"
    
    with patch("subprocess.run", return_value=mock_result) as mock_run, \
         patch("time.sleep") as mock_sleep:
        success, out, err = run_ffmpeg_with_retry(["ffmpeg"], "test_desc", max_retries=3)
        assert success is False
        assert err == "Failed after 3 attempts"
        assert mock_run.call_count == 3
        # リトライ間のウェイトは2回発生するはず
        assert mock_sleep.call_count == 2

def test_run_ffmpeg_retry_and_success():
    """失敗した後にリトライで成功するケース"""
    mock_fail = MagicMock()
    mock_fail.returncode = 1
    mock_fail.stderr = "FFmpeg error"
    
    mock_success = MagicMock()
    mock_success.returncode = 0
    
    with patch("subprocess.run", side_effect=[mock_fail, mock_success]) as mock_run, \
         patch("time.sleep") as mock_sleep:
        success, out, err = run_ffmpeg_with_retry(["ffmpeg"], "test_desc", max_retries=3)
        assert success is True
        assert mock_run.call_count == 2
        assert mock_sleep.call_count == 1

def test_run_ffmpeg_timeout():
    """TimeoutExpired例外が発生した場合のリトライと最終失敗"""
    timeout_err = subprocess.TimeoutExpired(["ffmpeg"], 10)
    
    with patch("subprocess.run", side_effect=timeout_err) as mock_run, \
         patch("time.sleep") as mock_sleep:
        success, out, err = run_ffmpeg_with_retry(["ffmpeg"], "test_desc", max_retries=2)
        assert success is False
        assert mock_run.call_count == 2
        # TimeoutExpired の except ブロックでは sleep を呼ばない設計のため 0 回
        assert mock_sleep.call_count == 0

def test_run_ffmpeg_os_error():
    """OSError/SubprocessError等の例外が発生した場合のリトライと最終失敗"""
    os_err = OSError("No such file or directory")
    
    with patch("subprocess.run", side_effect=os_err) as mock_run, \
         patch("time.sleep") as mock_sleep:
        success, out, err = run_ffmpeg_with_retry(["ffmpeg"], "test_desc", max_retries=2)
        assert success is False
        assert mock_run.call_count == 2
        assert mock_sleep.call_count == 1

# =========================================================================
# phase0_preflight_check のテスト
# =========================================================================

def test_preflight_check_input_not_found(tmp_path, monkeypatch):
    """入力動画ファイルが存在しないとき、プレフライトチェック全体が失敗することを検証"""
    monkeypatch.setenv("VIDEO_AUTOMATION_BASE_DIR", str(tmp_path))
    
    results = phase0_preflight_check()
    
    assert results["short_path_test"] is False
    assert results["1min_preview"] is False
    assert results["5min_chunk"] is False
    assert results["overall_success"] is False
    
    # 結果の JSON ファイルが正しく作成されていること
    json_file = tmp_path / "backend" / "temp" / "phase0_check" / "phase0_results.json"
    assert json_file.exists()
    
    with open(json_file, "r") as f:
        data = json.load(f)
        assert data == results

def test_preflight_check_no_base_dir_env(monkeypatch):
    """環境変数 VIDEO_AUTOMATION_BASE_DIR が未設定のときのフォールバックパスを検証"""
    monkeypatch.delenv("VIDEO_AUTOMATION_BASE_DIR", raising=False)
    
    # 余計なディレクトリ作成やファイルアクセスが発生しないよう、Pathオブジェクトのメソッド等をモック
    with patch.object(Path, "exists", return_value=False), \
         patch.object(Path, "mkdir") as mock_mkdir, \
         patch("backend.phase0_preflight.open", create=True) as mock_open:
        results = phase0_preflight_check()
        
    assert results["short_path_test"] is False

def test_preflight_check_short_path_exists_false(tmp_path, monkeypatch):
    """ショートパス変換後、その変換されたショートパスのファイルが存在しないと判定されたときを検証"""
    monkeypatch.setenv("VIDEO_AUTOMATION_BASE_DIR", str(tmp_path))
    
    raw_dir = tmp_path / "raw_videos" / "AI Studio アップロード用動画"
    raw_dir.mkdir(parents=True, exist_ok=True)
    input_video = raw_dir / "シーン01_前編.mp4"
    input_video.touch()
    
    dummy_short = str(tmp_path / "short_non_existent.mp4")
    
    # 元のファイル input_video に対する exists は True にするが、
    # dummy_short に対する os.path.exists は False を返すように制御
    orig_exists = os.path.exists
    def mock_exists(path):
        if path == dummy_short:
            return False
        return orig_exists(path)
        
    with patch("backend.phase0_preflight.get_short_path", return_value=dummy_short), \
         patch("os.path.exists", side_effect=mock_exists):
        results = phase0_preflight_check()
        
    assert results["short_path_test"] is False
    assert results["overall_success"] is False

def test_preflight_check_all_success(tmp_path, monkeypatch):
    """すべてのプレフライトステップ（ショートパス、プレビュー、チャンク）が成功したときを検証"""
    monkeypatch.setenv("VIDEO_AUTOMATION_BASE_DIR", str(tmp_path))
    
    # テスト用の入力ファイルを作成
    raw_dir = tmp_path / "raw_videos" / "AI Studio アップロード用動画"
    raw_dir.mkdir(parents=True, exist_ok=True)
    input_video = raw_dir / "シーン01_前編.mp4"
    input_video.touch()
    
    # FFmpeg コマンド実行時に擬似的に指定サイズ以上のファイルを生成するモック
    def mock_run_ffmpeg(cmd, description, max_retries=3, timeout_sec=300):
        out_path = cmd[-1]
        with open(out_path, "wb") as f:
            if "1-minute" in description:
                f.write(b"0" * 100001)  # 100,000バイト超
            else:
                f.write(b"0" * 500001)  # 500,000バイト超
        return (True, None, None)
        
    with patch("backend.phase0_preflight.run_ffmpeg_with_retry", side_effect=mock_run_ffmpeg), \
         patch("backend.phase0_preflight.get_short_path", return_value=str(input_video)):
        results = phase0_preflight_check()
        
    assert results["short_path_test"] is True
    assert results["1min_preview"] is True
    assert results["5min_chunk"] is True
    assert results["overall_success"] is True

def test_preflight_check_chunk_5min_fail(tmp_path, monkeypatch):
    """1分プレビューは成功するが、5分チャンクが失敗したときを検証"""
    monkeypatch.setenv("VIDEO_AUTOMATION_BASE_DIR", str(tmp_path))
    
    raw_dir = tmp_path / "raw_videos" / "AI Studio アップロード用動画"
    raw_dir.mkdir(parents=True, exist_ok=True)
    input_video = raw_dir / "シーン01_前編.mp4"
    input_video.touch()
    
    # 1分プレビューはファイルを生成して成功、5分チャンクは失敗を返す
    def mock_run_ffmpeg(cmd, description, max_retries=3, timeout_sec=300):
        out_path = cmd[-1]
        if "1-minute" in description:
            with open(out_path, "wb") as f:
                f.write(b"0" * 100001)
            return (True, None, None)
        else:
            return (False, None, "ffmpeg fail")
            
    with patch("backend.phase0_preflight.run_ffmpeg_with_retry", side_effect=mock_run_ffmpeg), \
         patch("backend.phase0_preflight.get_short_path", return_value=str(input_video)):
        results = phase0_preflight_check()
        
    assert results["short_path_test"] is True
    assert results["1min_preview"] is True
    assert results["5min_chunk"] is False
    assert results["overall_success"] is False

def test_preflight_check_partial_failure(tmp_path, monkeypatch):
    """一部のステップ（FFmpeg 実行等）が失敗したときに overall_success が False になることを検証"""
    monkeypatch.setenv("VIDEO_AUTOMATION_BASE_DIR", str(tmp_path))
    
    # 入力ファイルを作成
    raw_dir = tmp_path / "raw_videos" / "AI Studio アップロード用動画"
    raw_dir.mkdir(parents=True, exist_ok=True)
    input_video = raw_dir / "シーン01_前編.mp4"
    input_video.touch()
    
    # get_short_path は成功するが、FFmpeg 実行が False を返す
    with patch("backend.phase0_preflight.get_short_path", return_value=str(input_video)), \
         patch("backend.phase0_preflight.run_ffmpeg_with_retry", return_value=(False, None, "ffmpeg fail")):
        results = phase0_preflight_check()
        
    assert results["short_path_test"] is True
    assert results["1min_preview"] is False
    assert results["5min_chunk"] is False
    assert results["overall_success"] is False
