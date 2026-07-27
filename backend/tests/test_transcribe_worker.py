import os
import json
import asyncio
import pytest
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from agents.pipeline_types import PipelineContext, StageResult
from agents.workers.transcribe_worker import TranscribeWorker


def test_transcribe_worker_metadata():
    worker = TranscribeWorker()
    assert worker.name == "\u6587\u5b57\u8d77\u3053\u3057"
    assert worker.get_definition_of_done() == "\u5b57\u5e55\u30bb\u30b0\u30e1\u30f3\u30c8\u304c1\u4ef6\u4ee5\u4e0a\u751f\u6210\u3055\u308c\u3001\u5404\u30bb\u30b0\u30e1\u30f3\u30c8\u306b\u30bf\u30a4\u30e0\u30b9\u30bf\u30f3\u30d7\u304c\u4ed8\u4e0e\u3055\u308c\u3066\u3044\u308b\u3053\u3068"
    
    res_ok = StageResult(stage_name="\u6587\u5b57\u8d77\u3053\u3057", success=True, data={"segment_count": 5})
    res_fail = StageResult(stage_name="\u6587\u5b57\u8d77\u3053\u3057", success=False, data={"segment_count": 5})
    res_zero = StageResult(stage_name="\u6587\u5b57\u8d77\u3053\u3057", success=True, data={"segment_count": 0})
    
    assert worker.verify(res_ok) is True
    assert worker.verify(res_fail) is False
    assert worker.verify(res_zero) is False


def test_load_segments_from_checkpoint(tmp_path):
    worker = TranscribeWorker()
    # 存在しないパス
    assert worker._load_segments_from_checkpoint(tmp_path / "not_exist.jsonl") == []
    
    # 正常なデータ
    cp_file = tmp_path / "chk.jsonl"
    segments = [
        {"start": 0.0, "end": 1.0, "text": "Hello"},
        {"start": 1.0, "end": 2.0, "text": "World"}
    ]
    with open(cp_file, "w", encoding="utf-8") as f:
        for seg in segments:
            f.write(json.dumps(seg) + "\n")
            
    loaded = worker._load_segments_from_checkpoint(cp_file)
    assert loaded == segments


def test_read_stdout_worker():
    worker = TranscribeWorker()
    
    # 正常なJSONのパース
    proc = MagicMock()
    proc.stdout = [
        '{"progress": 50}\n',
        '{"status": "completed", "device": "cuda", "model": "small"}\n',
        '\n',  # 空行
        'invalid json\n'  # パースエラー
    ]
    state = {"last_result": None, "thread_exception": None}
    worker._read_stdout_worker(proc, state)
    
    assert state["last_result"] == {"status": "completed", "device": "cuda", "model": "small"}
    assert state["thread_exception"] is None


def test_read_stdout_worker_io_error():
    worker = TranscribeWorker()
    
    # ValueError, OSError の例外発生テスト (スレッド内で安全にキャッチされること)
    class ErrorIterator:
        def __iter__(self):
            return self
        def __next__(self):
            raise OSError("mocked os error")
            
    proc = MagicMock()
    proc.stdout = ErrorIterator()
    state = {"last_result": None, "thread_exception": None}
    
    worker._read_stdout_worker(proc, state)
    assert state["thread_exception"] is None


def test_read_stdout_worker_unexpected_exception():
    worker = TranscribeWorker()
    
    # 予期しない例外のテスト (state["thread_exception"] に格納されること)
    class UnexpectedErrorIterator:
        def __iter__(self):
            return self
        def __next__(self):
            raise RuntimeError("unexpected error")
            
    proc = MagicMock()
    proc.stdout = UnexpectedErrorIterator()
    state = {"last_result": None, "thread_exception": None}
    
    worker._read_stdout_worker(proc, state)
    assert isinstance(state["thread_exception"], RuntimeError)


def test_handle_timeout(tmp_path):
    worker = TranscribeWorker()
    proc = MagicMock()
    
    # ケース1: チェックポイントファイルが存在しないか、サイズが小さい場合 -> RuntimeError
    checkpoint_path = tmp_path / "small_chk.jsonl"
    checkpoint_path.write_text("a" * 100)  # 500バイト未満
    
    with pytest.raises(RuntimeError) as excinfo:
        worker._handle_timeout(proc, str(checkpoint_path), "small", 600)
    assert "\u30bf\u30a4\u30e0\u30a2\u30a6\u30c8" in str(excinfo.value)
    proc.kill.assert_called_once()
    proc.wait.assert_called_once_with(timeout=10)

    # ケース2: proc.wait が TimeoutExpired をスローする場合 (ハング防止の検証)
    proc_timeout = MagicMock()
    proc_timeout.wait.side_effect = subprocess.TimeoutExpired(cmd="whisper", timeout=10)
    checkpoint_path_timeout = tmp_path / "small_chk_timeout.jsonl"
    checkpoint_path_timeout.write_text("a" * 100)
    with pytest.raises(RuntimeError):
        worker._handle_timeout(proc_timeout, str(checkpoint_path_timeout), "small", 600)
        
    # ケース3: チェックポイントファイルが十分大きい場合 -> 部分結果で続行
    checkpoint_path_ok = tmp_path / "large_chk.jsonl"
    checkpoint_path_ok.write_text("a" * 600)  # 500バイトより大きい
    
    proc_ok = MagicMock()
    result = worker._handle_timeout(proc_ok, str(checkpoint_path_ok), "small", 600)
    assert result == {"status": "completed", "device": "timeout_partial", "model": "small"}


@patch("agents.workers.transcribe_worker.subprocess.Popen")
def test_run_whisper_subprocess_success(mock_popen, tmp_path):
    worker = TranscribeWorker()
    
    # 正常終了のモック
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = MagicMock()
    proc.stdout.__iter__.return_value = ['{"status": "completed", "device": "cuda", "model": "small"}']
    proc.stderr = MagicMock()
    mock_popen.return_value = proc
    
    checkpoint_path = tmp_path / "dummy.jsonl"
    result = worker._run_whisper_subprocess("dummy.mp4", str(checkpoint_path), "small")
    
    assert result == {"status": "completed", "device": "cuda", "model": "small"}
    proc.stdout.close.assert_called_once()
    proc.stderr.close.assert_called_once()


@patch("agents.workers.transcribe_worker.subprocess.Popen")
def test_run_whisper_subprocess_timeout(mock_popen, tmp_path):
    worker = TranscribeWorker()
    
    # タイムアウトのモック
    proc = MagicMock()
    proc.wait.side_effect = subprocess.TimeoutExpired(cmd="whisper", timeout=600)
    proc.stdout = MagicMock()
    proc.stdout.__iter__.return_value = []
    proc.stderr = MagicMock()
    mock_popen.return_value = proc
    
    checkpoint_path = tmp_path / "dummy_timeout.jsonl"
    checkpoint_path.write_text("a" * 600)  # 部分結果がある状態
    
    result = worker._run_whisper_subprocess("dummy.mp4", str(checkpoint_path), "small")
    assert result == {"status": "completed", "device": "timeout_partial", "model": "small"}


@patch("agents.workers.transcribe_worker.subprocess.Popen")
def test_run_whisper_subprocess_thread_exception(mock_popen, tmp_path):
    worker = TranscribeWorker()
    
    # スレッド例外のモック
    class BuggyStdout:
        def __iter__(self):
            return self
        def __next__(self):
            raise RuntimeError("thread dead")
            
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = BuggyStdout()
    proc.stderr = MagicMock()
    mock_popen.return_value = proc
    
    checkpoint_path = tmp_path / "dummy_thread_error.jsonl"
    
    with pytest.raises(RuntimeError) as excinfo:
        worker._run_whisper_subprocess("dummy.mp4", str(checkpoint_path), "small")
    assert "stdout" in str(excinfo.value)


@patch("agents.workers.transcribe_worker.subprocess.Popen")
def test_run_whisper_subprocess_fallback(mock_popen, tmp_path):
    worker = TranscribeWorker()
    
    # last_result が completed でないが、returncode=0 でチェックポイントが存在する（フォールバック）
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = MagicMock()
    proc.stdout.__iter__.return_value = ['{"status": "unknown"}']  # completed ではない
    proc.stderr = MagicMock()
    mock_popen.return_value = proc
    
    checkpoint_path = tmp_path / "fallback.jsonl"
    checkpoint_path.write_text("a" * 1100)  # > 1000 バイト
    
    result = worker._run_whisper_subprocess("dummy.mp4", str(checkpoint_path), "small")
    assert result == {"status": "completed", "device": "unknown", "model": "small"}


@patch("agents.workers.transcribe_worker.subprocess.Popen")
def test_run_whisper_subprocess_failure(mock_popen, tmp_path):
    worker = TranscribeWorker()
    
    # 完全に失敗するケース (returncode != 0 かつ checkpointなし)
    proc = MagicMock()
    proc.returncode = 1
    proc.stdout = MagicMock()
    proc.stdout.__iter__.return_value = []
    proc.stderr = MagicMock()
    proc.stderr.read.return_value = "Whisper CUDA Error!"
    mock_popen.return_value = proc
    
    checkpoint_path = tmp_path / "failed.jsonl"
    
    with pytest.raises(RuntimeError) as excinfo:
        worker._run_whisper_subprocess("dummy.mp4", str(checkpoint_path), "small")
    assert "Whisper\u30b5\u30d6\u30d7\u30ed\u30bb\u30b9\u5931\u6557" in str(excinfo.value)
    assert "Whisper CUDA Error!" in str(excinfo.value)


@patch("agents.workers.transcribe_worker.subprocess.Popen")
def test_run_whisper_subprocess_close_exceptions(mock_popen, tmp_path):
    worker = TranscribeWorker()
    
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = MagicMock()
    proc.stdout.__iter__.return_value = ['{"status": "completed", "device": "cuda", "model": "small"}']
    # close() 時に例外を発生させる
    proc.stdout.close.side_effect = OSError("stdout close error")
    
    proc.stderr = MagicMock()
    proc.stderr.close.side_effect = OSError("stderr close error")
    
    mock_popen.return_value = proc
    
    checkpoint_path = tmp_path / "close_err.jsonl"
    result = worker._run_whisper_subprocess("dummy.mp4", str(checkpoint_path), "small")
    
    # 例外が握りつぶされ、正常に結果が返ることを確認
    assert result == {"status": "completed", "device": "cuda", "model": "small"}
    proc.stdout.close.assert_called_once()
    proc.stderr.close.assert_called_once()


@pytest.mark.asyncio
async def test_execute_cached(tmp_path):
    # すでにチェックポイント（キャッシュ）が存在する場合
    worker = TranscribeWorker()
    
    video_path = tmp_path / "dummy.mp4"
    video_path.write_text("dummy video content")
    
    from subtitle_engine.video_hash import get_checkpoint_path, OLD_CHECKPOINT_NAME
    checkpoint_path = Path(get_checkpoint_path(video_path))
    
    # 旧形式キャッシュファイルも配置して、警告ログが出力されるルートを通す
    old_checkpoint = video_path.parent / OLD_CHECKPOINT_NAME
    old_checkpoint.write_text("old cache content")
    
    # 有効なチェックポイントファイル（> 1000 バイト）
    segments = [{"start": 0.0, "end": 2.0, "text": "Cached Hello"}]
    with open(checkpoint_path, "w", encoding="utf-8") as f:
        for seg in segments:
            f.write(json.dumps(seg) + "\n")
    # サイズを1000バイトより大きくするためパディングを足す
    checkpoint_path.write_text(checkpoint_path.read_text() + " " * 1100)
    
    ctx = PipelineContext(video_path=str(video_path))
    
    result = await worker.execute(ctx)
    assert result.success is True
    assert "\u30bb\u30b0\u30e1\u30f3\u30c8\u691c\u51fa (\u30ad\u30e3\u30c3\u30b7\u30e5)" in result.detail
    assert len(ctx.segments) == len(segments)
    assert ctx.segments[0]["start"] == segments[0]["start"]


@pytest.mark.asyncio
@patch("agents.workers.transcribe_worker.TranscribeWorker._run_whisper_subprocess")
async def test_execute_run_subprocess(mock_run_sub, tmp_path):
    # キャッシュが存在しないため、サブプロセスを実行するケース
    worker = TranscribeWorker()
    
    video_path = tmp_path / "dummy.mp4"
    video_path.write_text("dummy video content")
    
    from subtitle_engine.video_hash import get_checkpoint_path
    checkpoint_path = Path(get_checkpoint_path(video_path))
    
    # サブプロセスが完了した後にチェックポイントファイルが書かれるので、
    # _run_whisper_subprocess の side_effect としてチェックポイントファイルを書き出すようにする
    segments = [{"start": 0.0, "end": 3.0, "text": "Subprocess Hello"}]
    
    def side_effect(vid, cp, model):
        with open(cp, "w", encoding="utf-8") as f:
            for seg in segments:
                f.write(json.dumps(seg) + "\n")
        return {"status": "completed", "device": "cuda", "model": "small"}
        
    mock_run_sub.side_effect = side_effect
    
    ctx = PipelineContext(video_path=str(video_path))
    
    result = await worker.execute(ctx)
    assert result.success is True
    assert len(ctx.segments) == len(segments)
    assert ctx.segments[0]["start"] == segments[0]["start"]
    assert result.data["device"] == "cuda"
    assert result.data["model"] == "small"


@pytest.mark.asyncio
async def test_execute_exception(tmp_path):
    # 例外が発生した場合のテスト
    worker = TranscribeWorker()
    
    # 存在しない動画ファイルを設定すると、compute_video_hash で FileNotFoundError が発生する
    ctx = PipelineContext(video_path=str(tmp_path / "non_existent.mp4"))
    
    result = await worker.execute(ctx)
    assert result.success is False
    assert "\u52d5\u753b\u30d5\u30a1\u30a4\u30eb\u304c\u898b\u3064\u304b\u308a\u307e\u305b\u3093" in result.detail


def test_load_segments_from_checkpoint_parse_error(tmp_path):
    worker = TranscribeWorker()
    cp_file = tmp_path / "chk_bad.jsonl"
    
    with open(cp_file, "w", encoding="utf-8") as f:
        f.write('{"start": 0.0, "end": 1.0, "text": "Hello"}\n')
        f.write('invalid_json_here\n')
        f.write('\n')
        
    loaded = worker._load_segments_from_checkpoint(cp_file)
    assert len(loaded) == 1
    assert loaded[0]["text"] == "Hello"


@patch("agents.workers.transcribe_worker.subprocess.Popen")
def test_run_whisper_subprocess_still_running_normal(mock_popen, safe_popen_mock, tmp_path):
    worker = TranscribeWorker()
    
    proc = safe_popen_mock(returncode=0)
    proc.poll.return_value = None  # まだ実行中と判定させる
    proc.stdout.__iter__.return_value = []
    mock_popen.return_value = proc
    
    checkpoint_path = tmp_path / "still_running_ok.jsonl"
    checkpoint_path.write_text("a" * 1100)
    
    result = worker._run_whisper_subprocess("dummy.mp4", str(checkpoint_path), "small")
    assert result == {"status": "completed", "device": "unknown", "model": "small"}
    proc.kill.assert_called_once()
    proc.wait.assert_called_with(timeout=5)


@patch("agents.workers.transcribe_worker.subprocess.Popen")
def test_run_whisper_subprocess_still_running_oserror(mock_popen, safe_popen_mock, tmp_path):
    worker = TranscribeWorker()
    
    proc = safe_popen_mock(returncode=0)
    proc.poll.return_value = None  # まだ実行中と判定させる
    proc.kill.side_effect = OSError("mocked os error during kill")
    proc.stdout.__iter__.return_value = []
    mock_popen.return_value = proc
    
    checkpoint_path = tmp_path / "still_running_err.jsonl"
    checkpoint_path.write_text("a" * 1100)
    
    result = worker._run_whisper_subprocess("dummy.mp4", str(checkpoint_path), "small")
    assert result == {"status": "completed", "device": "unknown", "model": "small"}
    proc.kill.assert_called_once()


@patch("agents.workers.transcribe_worker.subprocess.Popen")
def test_run_whisper_subprocess_stderr_read_exception(mock_popen, tmp_path):
    worker = TranscribeWorker()
    
    # proc.stderr.read() 呼び出し時に OSError が発生するケース
    proc = MagicMock()
    proc.returncode = 1
    proc.stdout = MagicMock()
    proc.stdout.__iter__.return_value = []
    proc.stderr = MagicMock()
    proc.stderr.read.side_effect = OSError("read error")
    mock_popen.return_value = proc
    
    checkpoint_path = tmp_path / "read_failed.jsonl"
    
    with pytest.raises(RuntimeError) as excinfo:
        worker._run_whisper_subprocess("dummy.mp4", str(checkpoint_path), "small")
    assert "Whisperサブプロセス失敗" in str(excinfo.value)
