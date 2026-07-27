import sys
import os
import json
import pytest
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

# backend ディレクトリを sys.path に追加
backend_dir = Path(__file__).parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# ─── Pydantic Python 3.13 KeyError 回避ハック ───
import pydantic
sys.modules['pydantic.root_model'] = pydantic

# ─── google.genai と mcp をインポート前にモック化（Pydantic 3.13 MROエラー回避） ───
mock_google = MagicMock()
mock_google.__path__ = []
sys.modules['google.genai'] = mock_google
sys.modules['google.genai.types'] = MagicMock()
sys.modules['google.genai.errors'] = MagicMock()
sys.modules['mcp'] = MagicMock()
sys.modules['mcp.types'] = MagicMock()
sys.modules['mcp.server'] = MagicMock()
sys.modules['mcp.server.fastmcp'] = MagicMock()

# ─── NumPy 3.13 回避のための faster_whisper と ctranslate2 の事前モック ───
mock_faster_whisper = MagicMock()
mock_whisper_model_class = MagicMock()
mock_faster_whisper.WhisperModel = mock_whisper_model_class
mock_ctranslate2 = MagicMock()
sys.modules['faster_whisper'] = mock_faster_whisper
sys.modules['ctranslate2'] = mock_ctranslate2

# ─── pyannote.audio と torch のモック化 ───
mock_torch = MagicMock()
mock_torch.cuda.is_available.return_value = True
sys.modules['torch'] = mock_torch

mock_pyannote = MagicMock()
mock_pyannote_audio = MagicMock()
mock_pipeline_class = MagicMock()
mock_pipeline_instance = MagicMock()
mock_pipeline_class.from_pretrained.return_value = mock_pipeline_instance
mock_pyannote_audio.Pipeline = mock_pipeline_class
sys.modules['pyannote'] = mock_pyannote
sys.modules['pyannote.audio'] = mock_pyannote_audio

# 対象モジュールのインポート
from subtitle_engine.speaker_diarizer import SpeakerDiarizer, SpeakerSegment, DiarizationResult, speaker_diarizer

# ─── スレッド内でも有効な subprocess.run モックの差し替え ───
import subtitle_engine.speaker_diarizer
mock_subprocess_run = MagicMock()
subtitle_engine.speaker_diarizer.subprocess.run = mock_subprocess_run


@pytest.fixture(autouse=True)
def concurrency_mock():
    """ThreadPoolExecutor や BaseEventLoop.run_in_executor を同期実行にモック化し、カバレッジ計測漏れを防ぐ"""
    import asyncio
    
    # run_in_executor の同期化
    async def mock_run_in_executor(self, executor, func, *args, **kwargs):
        if asyncio.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        else:
            return func(*args, **kwargs)
            
    # ThreadPoolExecutor の同期化
    class DummyFuture:
        def __init__(self, result):
            self._result = result
        def result(self):
            return self._result
            
    class DummyExecutor:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def submit(self, func, *args, **kwargs):
            res = func(*args, **kwargs)
            return DummyFuture(res)
            
    with patch("asyncio.base_events.BaseEventLoop.run_in_executor", mock_run_in_executor), \
         patch("concurrent.futures.ThreadPoolExecutor", DummyExecutor):
        yield


class DummyTurn:
    def __init__(self, start, end):
        self.start = start
        self.end = end


@pytest.fixture(autouse=True)
def reset_mocks():
    """各テスト前にモックの状態をリセット"""
    mock_torch.reset_mock()
    mock_pipeline_class.reset_mock()
    mock_pipeline_instance.reset_mock()
    mock_subprocess_run.reset_mock()
    
    # デフォルト設定
    mock_torch.cuda.is_available.return_value = True
    mock_pipeline_class.from_pretrained.return_value = mock_pipeline_instance
    
    # ダミーのitertracksジェネレータを持つダイアリゼーション結果オブジェクト
    mock_diarization = MagicMock()
    mock_pipeline_instance.return_value = mock_diarization
    mock_diarization.itertracks.return_value = [
        (DummyTurn(0.0, 1.0), None, "speaker_0"),
        (DummyTurn(1.5, 3.0), None, "speaker_1"),
    ]


def test_check_pyannote_not_available():
    """pyannote.audioがインストールされていない場合の検出"""
    with patch.dict("sys.modules", {"pyannote.audio": None}):
        diarizer = SpeakerDiarizer()
        assert diarizer._check_pyannote() is False


def test_check_pyannote_available():
    """pyannote.audioがインストールされている場合の検出"""
    diarizer = SpeakerDiarizer()
    assert diarizer._check_pyannote() is True


@pytest.mark.asyncio
async def test_diarize_pyannote_success():
    """pyannoteモードでのダイアリゼーション正常系"""
    diarizer = SpeakerDiarizer()
    diarizer._pyannote_available = True
    
    result = await diarizer.diarize("dummy.wav", num_speakers=2, method="pyannote")
    
    assert isinstance(result, DiarizationResult)
    assert result.method == "pyannote"
    assert result.num_speakers == 2
    assert len(result.segments) == 2
    assert result.segments[0].speaker_id == "speaker_0"
    assert result.segments[0].start == 0.0
    assert result.segments[0].end == 1.0
    assert result.segments[1].speaker_id == "speaker_1"
    assert result.segments[1].start == 1.5
    assert result.segments[1].end == 3.0
    assert result.duration == 3.0


@pytest.mark.asyncio
async def test_diarize_pyannote_empty_segments():
    """pyannoteの結果が空の場合のduration確認"""
    diarizer = SpeakerDiarizer()
    
    mock_diarization = MagicMock()
    mock_pipeline_instance.return_value = mock_diarization
    mock_diarization.itertracks.return_value = []
    
    result = await diarizer.diarize("dummy.wav", num_speakers=None, method="pyannote")
    assert len(result.segments) == 0
    assert result.duration == 0.0


@pytest.mark.asyncio
async def test_diarize_pyannote_cuda_disabled():
    """CUDAが使えない環境でのpyannote動作"""
    mock_torch.cuda.is_available.return_value = False
    diarizer = SpeakerDiarizer()
    
    result = await diarizer.diarize("dummy.wav", num_speakers=2, method="pyannote")
    assert result.method == "pyannote"
    mock_torch.device.assert_not_called()


@pytest.mark.asyncio
async def test_diarize_pyannote_failure_fallback():
    """pyannoteがエラーを吐いた場合にVADへフォールバックすることの検証"""
    diarizer = SpeakerDiarizer()
    diarizer._pyannote_available = True
    
    with patch.object(diarizer, "_diarize_pyannote", side_effect=RuntimeError("Pyannote error")):
        mock_vad = MagicMock()
        with patch.object(diarizer, "_diarize_vad", return_value=mock_vad) as mock_vad_method:
            result = await diarizer.diarize("dummy.wav", method="pyannote")
            mock_vad_method.assert_called_once_with("dummy.wav", 2)
            assert result == mock_vad


@pytest.mark.asyncio
async def test_diarize_stereo_success():
    """ステレオモードでのダイアリゼーション正常系"""
    diarizer = SpeakerDiarizer()
    
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock()
        res.returncode = 0
        if "ffprobe" in cmd:
            res.stdout = '{"streams": [{"channels": 2, "duration": "15.5"}]}'
        elif "ffmpeg" in cmd:
            af_arg = cmd[cmd.index("-af") + 1]
            if "c0=c0" in af_arg:
                res.stderr = "silence_start: 1.0\nsilence_end: 3.0\nsilence_start: 8.0\nsilence_end: 10.0\n"
            elif "c0=c1" in af_arg:
                res.stderr = "silence_start: 4.0\nsilence_end: 6.0\n"
            else:
                res.stderr = ""
        return res

    mock_subprocess_run.side_effect = mock_run
    
    result = await diarizer.diarize("dummy.wav", method="stereo")
        
    assert isinstance(result, DiarizationResult)
    assert result.method == "stereo"
    assert result.num_speakers == 2
    assert result.duration == 15.5
    
    assert len(result.segments) > 0
    starts = [s.start for s in result.segments]
    assert starts == sorted(starts)


@pytest.mark.asyncio
async def test_diarize_stereo_mono_error():
    """ステレオモードでモノラル音声が渡された場合のエラーフォールバック"""
    diarizer = SpeakerDiarizer()
    
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock()
        res.returncode = 0
        if "ffprobe" in cmd:
            res.stdout = '{"streams": [{"channels": 1, "duration": "10.0"}]}'
        return res

    mock_subprocess_run.side_effect = mock_run

    mock_vad = MagicMock()
    with patch.object(diarizer, "_diarize_vad", return_value=mock_vad) as mock_vad_method:
        result = await diarizer.diarize("dummy.wav", method="stereo")
        mock_vad_method.assert_called_once_with("dummy.wav", 2)
        assert result == mock_vad


@pytest.mark.asyncio
async def test_diarize_stereo_failure_fallback():
    """ステレオ処理中にFFmpegがエラーになった場合のフォールバック"""
    diarizer = SpeakerDiarizer()
    
    def mock_run(cmd, *args, **kwargs):
        if "ffprobe" in cmd:
            res = MagicMock()
            res.stdout = '{"streams": [{"channels": 2, "duration": "10.0"}]}'
            return res
        raise subprocess.SubprocessError("FFmpeg timeout")

    mock_subprocess_run.side_effect = mock_run

    mock_vad = MagicMock()
    with patch.object(diarizer, "_diarize_vad", return_value=mock_vad) as mock_vad_method:
        result = await diarizer.diarize("dummy.wav", method="stereo")
        mock_vad_method.assert_called_once_with("dummy.wav", 2)
        assert result == mock_vad


@pytest.mark.asyncio
async def test_diarize_vad_success():
    """VADモードでのダイアリゼーション正常系"""
    diarizer = SpeakerDiarizer()
    
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock()
        res.returncode = 0
        if "ffprobe" in cmd:
            res.stdout = '{"format": {"duration": "12.0"}}'
        elif "ffmpeg" in cmd:
            res.stderr = "silence_start: 2.0\nsilence_end: 3.0\nsilence_start: 7.0\nsilence_end: 8.0\n"
        return res

    mock_subprocess_run.side_effect = mock_run

    result = await diarizer.diarize("dummy.wav", num_speakers=3, method="vad")
        
    assert isinstance(result, DiarizationResult)
    assert result.method == "vad"
    assert result.num_speakers == 3
    assert result.duration == 12.0
    assert len(result.segments) == 3
    assert result.segments[0].speaker_id == "speaker_0"
    assert result.segments[1].speaker_id == "speaker_0"
    assert result.segments[2].speaker_id == "speaker_0"


@pytest.mark.asyncio
async def test_diarize_vad_speaker_alternation():
    """VADモードでの無音が長い場合の話者交代"""
    diarizer = SpeakerDiarizer()
    
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock()
        res.returncode = 0
        if "ffprobe" in cmd:
            res.stdout = '{"format": {"duration": "15.0"}}'
        elif "ffmpeg" in cmd:
            res.stderr = "silence_start: 2.0\nsilence_end: 4.0\nsilence_start: 8.0\nsilence_end: 10.0\n"
        return res

    mock_subprocess_run.side_effect = mock_run

    result = await diarizer.diarize("dummy.wav", num_speakers=2, method="vad")
        
    assert len(result.segments) == 3
    assert result.segments[0].speaker_id == "speaker_0"
    assert result.segments[1].speaker_id == "speaker_1"
    assert result.segments[2].speaker_id == "speaker_0"


@pytest.mark.asyncio
async def test_diarize_default_routing():
    """methodが指定されていない場合の自動ルーティングの検証"""
    diarizer = SpeakerDiarizer()
    
    diarizer._pyannote_available = True
    mock_pyannote = MagicMock()
    with patch.object(diarizer, "_diarize_pyannote", return_value=mock_pyannote) as mock_py_method:
        res = await diarizer.diarize("dummy.wav")
        mock_py_method.assert_called_once_with("dummy.wav", None)
        assert res == mock_py_method.return_value
    
    diarizer._pyannote_available = False
    mock_stereo = MagicMock()
    with patch.object(diarizer, "_diarize_stereo", return_value=mock_stereo) as mock_stereo_method:
        res = await diarizer.diarize("dummy.wav", num_speakers=2)
        mock_stereo_method.assert_called_once_with("dummy.wav")
        assert res == mock_stereo
        
    mock_vad = MagicMock()
    with patch.object(diarizer, "_diarize_vad", return_value=mock_vad) as mock_vad_method:
        res = await diarizer.diarize("dummy.wav", num_speakers=3)
        mock_vad_method.assert_called_once_with("dummy.wav", 3)
        assert res == mock_vad


def test_get_duration_exception_handling():
    """_get_duration メソッドのエラーハンドリングとデフォルトフォールバック"""
    diarizer = SpeakerDiarizer()
    
    def mock_run_json_error(cmd, *args, **kwargs):
        res = MagicMock()
        res.returncode = 0
        res.stdout = "invalid json"
        return res
    mock_subprocess_run.side_effect = mock_run_json_error
    assert diarizer._get_duration("dummy.wav") == 3600.0
        
    def mock_run_key_error(cmd, *args, **kwargs):
        res = MagicMock()
        res.returncode = 0
        res.stdout = '{"format": {}}'
        return res
    mock_subprocess_run.side_effect = mock_run_key_error
    assert diarizer._get_duration("dummy.wav") == 3600.0

    def mock_run_val_error(cmd, *args, **kwargs):
        res = MagicMock()
        res.returncode = 0
        res.stdout = '{"format": {"duration": "abc"}}'
        return res
    mock_subprocess_run.side_effect = mock_run_val_error
    assert diarizer._get_duration("dummy.wav") == 3600.0

    mock_subprocess_run.side_effect = subprocess.SubprocessError("timeout")
    assert diarizer._get_duration("dummy.wav") == 3600.0


def test_assign_speakers_to_segments_empty():
    """話者セグメントが空の場合、そのままウィスパーセグメントを返す"""
    diarizer = SpeakerDiarizer()
    whisper_segs = [{"start": 0.0, "end": 2.0, "text": "Hello"}]
    diarization_res = DiarizationResult(segments=[], num_speakers=0, method="vad")
    
    result = diarizer.assign_speakers_to_segments(whisper_segs, diarization_res)
    assert result == whisper_segs
    assert "speaker_id" not in result[0]


def test_assign_speakers_to_segments_success():
    """話者割り当ての正常系および二分探索・近似割り当ての検証"""
    diarizer = SpeakerDiarizer()
    
    diarization_res = DiarizationResult(
        segments=[
            SpeakerSegment(start=0.0, end=2.0, speaker_id="speaker_0", confidence=0.7),
            SpeakerSegment(start=3.0, end=5.0, speaker_id="speaker_1", confidence=0.8)
        ],
        num_speakers=2,
        method="vad"
    )
    
    whisper_segs = [
        {"start": 0.5, "end": 1.5, "text": "In speaker 0"},
        {"start": 2.0, "end": 3.0, "text": "In gap"},
        {"start": 5.5, "end": 6.5, "text": "After speaker 1"},
    ]
    
    result = diarizer.assign_speakers_to_segments(whisper_segs, diarization_res)
    
    assert result[0]["speaker_id"] == "speaker_0"
    assert result[0]["speaker_confidence"] == 0.7
    
    assert result[1]["speaker_id"] == "speaker_0"
    assert result[1]["speaker_confidence"] == 0.7 * 0.5
    
    assert result[2]["speaker_id"] == "speaker_1"
    assert result[2]["speaker_confidence"] == 0.8 * 0.5


def test_invert_intervals_edge_cases():
    """_invert_intervals のエッジケース（0秒開始の無音、ファイルの最後が無音）の検証"""
    diarizer = SpeakerDiarizer()
    silences = [(0.0, 2.0), (3.0, 5.0)]
    duration = 5.0
    
    # 最初の無音開始が 0.0 なので s_start > prev_end が False (325->327 未カバー分岐をカバー)
    # 最後の無音終了が 5.0 なので prev_end < duration が False (329->332 未カバー分岐をカバー)
    speech = diarizer._invert_intervals(silences, duration)
    assert speech == [(2.0, 3.0)]


def test_assign_speakers_to_segments_before_first_segment():
    """最初の話者セグメント開始前に発話がある場合（idx == 0）の挙動検証"""
    diarizer = SpeakerDiarizer()
    
    diarization_res = DiarizationResult(
        segments=[
            SpeakerSegment(start=2.0, end=4.0, speaker_id="speaker_0", confidence=0.8)
        ],
        num_speakers=1,
        method="vad"
    )
    
    # midpoint は 0.5。diarization_starts は [2.0] なので idx == 0 になる
    # idx > 0 が False (392->399 および 402->404 未カバー分岐をカバー)
    whisper_segs = [
        {"start": 0.0, "end": 1.0, "text": "Before first segment"},
    ]
    
    result = diarizer.assign_speakers_to_segments(whisper_segs, diarization_res)
    
    assert result[0]["speaker_id"] == "speaker_0"
    assert result[0]["speaker_confidence"] == 0.8 * 0.5


def test_check_pyannote_unexpected_exception():
    """pyannote.audioのインポート時に予期せぬ例外が発生した場合のハンドリング検証"""
    original_import = __import__
    def mock_import(name, *args, **kwargs):
        if name == "pyannote.audio":
            raise RuntimeError("Unexpected load failure")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        diarizer = SpeakerDiarizer()
        # _check_pyannote はクラッシュせずに False を返すこと
        assert diarizer._check_pyannote() is False


@pytest.mark.asyncio
async def test_diarize_pyannote_unexpected_exception():
    """pyannote処理中に予期せぬ例外(KeyError等)が発生した場合のVADへのフォールバック検証"""
    diarizer = SpeakerDiarizer()
    diarizer._pyannote_available = True
    
    with patch.object(diarizer, "_diarize_pyannote", side_effect=KeyError("Unexpected internal error")):
        mock_vad = MagicMock()
        with patch.object(diarizer, "_diarize_vad", return_value=mock_vad) as mock_vad_method:
            result = await diarizer.diarize("dummy.wav", method="pyannote")
            mock_vad_method.assert_called_once_with("dummy.wav", 2)
            assert result == mock_vad


@pytest.mark.asyncio
async def test_diarize_stereo_unexpected_exception():
    """stereo処理中に予期せぬ例外が発生した場合のVADへのフォールバック検証"""
    diarizer = SpeakerDiarizer()
    
    with patch.object(diarizer, "_diarize_stereo", side_effect=AttributeError("Unexpected attribute error")):
        mock_vad = MagicMock()
        with patch.object(diarizer, "_diarize_vad", return_value=mock_vad) as mock_vad_method:
            result = await diarizer.diarize("dummy.wav", num_speakers=2, method="stereo")
            mock_vad_method.assert_called_once_with("dummy.wav", 2)
            assert result == mock_vad


def test_generate_diarization_thumbnail_invalid_speaker_id(tmp_path):
    """speaker_id が非標準形式(末尾が数値でない等)の場合でもサムネイル生成がクラッシュしないことの検証"""
    diarizer = SpeakerDiarizer()
    diarization_res = DiarizationResult(
        segments=[
            SpeakerSegment(start=0.0, end=2.0, speaker_id="speaker_invalid_name", confidence=0.7),
            SpeakerSegment(start=2.0, end=4.0, speaker_id="customspeaker", confidence=0.8)
        ],
        num_speakers=2,
        method="vad",
        duration=4.0
    )
    
    output_file = tmp_path / "test_thumb.png"
    # 例外が発生せずに正常終了すること
    res_path = diarizer.generate_diarization_thumbnail(str(output_file), diarization_res)
    assert os.path.exists(res_path)


def test_generate_diarization_thumbnail_write_error_cleanup(tmp_path):
    """サムネイル保存時に書き込みエラーが発生した場合に、一時ファイルがクリーンアップされ例外が再スローされることの検証"""
    diarizer = SpeakerDiarizer()
    diarization_res = DiarizationResult(
        segments=[SpeakerSegment(start=0.0, end=2.0, speaker_id="speaker_0", confidence=0.7)],
        num_speakers=1,
        method="vad",
        duration=2.0
    )
    
    output_file = tmp_path / "test_thumb.png"
    
    def mock_save(self, fp, format=None, **params):
        # 一時ファイルを作成してからエラーを投げる
        with open(fp, "w") as f:
            f.write("partial data")
        raise OSError("Disk full")
    
    # Image.save 自体をモック化
    with patch("PIL.Image.Image.save", mock_save):
        # 例外がスローされることの検証
        with pytest.raises(OSError):
            diarizer.generate_diarization_thumbnail(str(output_file), diarization_res)
        
    # tmp_path 内に一時ファイルが残っていないことを検証
    remaining_files = list(tmp_path.rglob("*.tmp"))
    assert len(remaining_files) == 0



def test_generate_diarization_thumbnail_resolution_error(tmp_path):
    """解像度バリデーションエラーのテスト"""
    diarizer = SpeakerDiarizer()
    diarization_res = DiarizationResult(duration=2.0)
    output_file = tmp_path / "test_thumb.png"
    
    with pytest.raises(ValueError) as excinfo:
        diarizer.generate_diarization_thumbnail(str(output_file), diarization_res, width=1000, height=720)
    assert "Resolution must be at least 1280x720" in str(excinfo.value)
    
    with pytest.raises(ValueError) as excinfo:
        diarizer.generate_diarization_thumbnail(str(output_file), diarization_res, width=1280, height=500)
    assert "Resolution must be at least 1280x720" in str(excinfo.value)


def test_generate_diarization_thumbnail_aspect_ratio_error(tmp_path):
    """アスペクト比バリデーションエラーのテスト"""
    diarizer = SpeakerDiarizer()
    diarization_res = DiarizationResult(duration=2.0)
    output_file = tmp_path / "test_thumb.png"
    
    # 1600/1000 = 1.6 (not 16:9 ratio)
    with pytest.raises(ValueError) as excinfo:
        diarizer.generate_diarization_thumbnail(str(output_file), diarization_res, width=1600, height=1000)
    assert "Aspect ratio must be 16:9" in str(excinfo.value)


def test_generate_diarization_thumbnail_segment_exceeds_duration(tmp_path):
    """セグメントの終了時刻が音声長を超過している場合にスキップされるテスト"""
    diarizer = SpeakerDiarizer()
    diarization_res = DiarizationResult(
        segments=[
            SpeakerSegment(start=1.0, end=3.0, speaker_id="speaker_0", confidence=0.7)  # end (3.0) > duration (2.0)
        ],
        num_speakers=1,
        method="vad",
        duration=2.0
    )
    output_file = tmp_path / "test_thumb.png"
    res_path = diarizer.generate_diarization_thumbnail(str(output_file), diarization_res)
    assert os.path.exists(res_path)


def test_generate_diarization_thumbnail_overwrite_existing(tmp_path):
    """すでにファイルが存在する場合に上書き（unlink/rename）されるテスト"""
    diarizer = SpeakerDiarizer()
    diarization_res = DiarizationResult(
        segments=[SpeakerSegment(start=0.0, end=2.0, speaker_id="speaker_0", confidence=0.7)],
        num_speakers=1,
        method="vad",
        duration=2.0
    )
    output_file = tmp_path / "test_thumb.png"
    
    # ダミーのファイルをあらかじめ作成
    with open(output_file, "w") as f:
        f.write("existing file contents")
        
    res_path = diarizer.generate_diarization_thumbnail(str(output_file), diarization_res)
    assert os.path.exists(res_path)
    # PNGファイルであることを検証する（シグニチャ確認）
    with open(output_file, "rb") as f:
        header = f.read(8)
    assert header.startswith(b"\x89PNG")


def test_generate_diarization_thumbnail_unexpected_error(tmp_path):
    """save処理中に予期せぬ例外が発生した際の例外伝播テスト"""
    diarizer = SpeakerDiarizer()
    diarization_res = DiarizationResult(
        segments=[SpeakerSegment(start=0.0, end=2.0, speaker_id="speaker_0", confidence=0.7)],
        num_speakers=1,
        method="vad",
        duration=2.0
    )
    output_file = tmp_path / "test_thumb.png"
    
    def mock_save(self, fp, format=None, **params):
        raise RuntimeError("Unexpected PIL error")
        
    with patch("PIL.Image.Image.save", mock_save):
        with pytest.raises(RuntimeError) as excinfo:
            diarizer.generate_diarization_thumbnail(str(output_file), diarization_res)
        assert "Unexpected PIL error" in str(excinfo.value)


def test_generate_diarization_thumbnail_cleanup_failure(tmp_path):
    """一時ファイル削除処理のクリーンアップ失敗例外処理のテスト"""
    diarizer = SpeakerDiarizer()
    diarization_res = DiarizationResult(
        segments=[SpeakerSegment(start=0.0, end=2.0, speaker_id="speaker_0", confidence=0.7)],
        num_speakers=1,
        method="vad",
        duration=2.0
    )
    output_file = tmp_path / "test_thumb.png"
    
    def mock_save(self, fp, format=None, **params):
        # クリーンアップが呼ばれるようにダミーの一時ファイルを作成
        with open(fp, "w") as f:
            f.write("partial data")
        raise OSError("Save error")
        
    original_unlink = os.unlink
    def mock_unlink(path):
        if ".tmp" in path:
            raise OSError("Unlink failed")
        return original_unlink(path)
        
    with patch("PIL.Image.Image.save", mock_save), patch("os.unlink", mock_unlink):
        with pytest.raises(OSError) as excinfo:
            diarizer.generate_diarization_thumbnail(str(output_file), diarization_res)
        assert "Save error" in str(excinfo.value)


def test_generate_diarization_thumbnail_size_limit(tmp_path):
    """4MBサイズ制限バリデーションのテスト"""
    diarizer = SpeakerDiarizer()
    diarization_res = DiarizationResult(
        segments=[SpeakerSegment(start=0.0, end=2.0, speaker_id="speaker_0", confidence=0.7)],
        num_speakers=1,
        method="vad",
        duration=2.0
    )
    output_file = tmp_path / "test_thumb.png"
    
    # getsize が 4MB 以上を返すようにモック
    with patch("os.path.getsize", return_value=4 * 1024 * 1024 + 1024):
        with pytest.raises(ValueError) as excinfo:
            diarizer.generate_diarization_thumbnail(str(output_file), diarization_res)
        assert "exceeds 4MB limit" in str(excinfo.value)


@pytest.mark.asyncio
async def test_run_diarizer_thumbnail_task(tmp_path):
    """run_diarizer_thumbnail_task 非同期タスクの全体テスト"""
    mock_validate = MagicMock(return_value={"status": "pass", "errors": []})
    
    diarization_data = {
        "segments": [
            {"start": 0.0, "end": 1.0, "speaker_id": "speaker_0", "confidence": 0.9}
        ],
        "num_speakers": 1,
        "method": "vad",
        "duration": 2.0
    }
    diarization_data_json = json.dumps(diarization_data)
    output_file = tmp_path / "task_thumb.png"
    
    with patch("agents.stage_bound_agent.validate_thumbnail", mock_validate):
        from subtitle_engine.speaker_diarizer import run_diarizer_thumbnail_task
        
        result_json = await run_diarizer_thumbnail_task(
            db_path="dummy_db",
            task_id="dummy_task",
            output_path=str(output_file),
            diarization_data_json=diarization_data_json,
            width=1280,
            height=720,
            title="Diarization Test Title"
        )
        
        result = json.loads(result_json)
        assert result["status"] == "pass"
        mock_validate.assert_called_once_with(os.path.abspath(str(output_file)))
        assert os.path.exists(output_file)

def test_parse_silence_detect_validation_handling():
    """_parse_silence_detect の開始・終了逆転値に対する例外ハンドリングとフィルタリング検証"""
    diarizer = SpeakerDiarizer()
    
    stderr = (
        "silence_start: 1.0\nsilence_end: 3.0\n"
        "silence_start: 5.0\nsilence_end: 2.0\n"
        "silence_start: 8.0\nsilence_end: 10.0\n"
    )
    
    intervals = diarizer._parse_silence_detect(stderr)
    
    assert intervals == [(1.0, 3.0), (8.0, 10.0)]
