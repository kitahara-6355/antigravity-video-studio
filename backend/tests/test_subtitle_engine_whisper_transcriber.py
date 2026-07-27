import sys
import os
import json
import pytest
import subprocess
import time
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
mock_google.__path__ = []  # パッケージとして振る舞わせる
sys.modules['google.genai'] = mock_google
sys.modules['google.genai.types'] = MagicMock()
sys.modules['google.genai.errors'] = MagicMock()
sys.modules['mcp'] = MagicMock()
sys.modules['mcp.types'] = MagicMock()
sys.modules['mcp.server'] = MagicMock()
sys.modules['mcp.server.fastmcp'] = MagicMock()

# ─── 依存モジュールの事前モック注入 ───
mock_faster_whisper = MagicMock()
mock_whisper_model_class = MagicMock()
mock_faster_whisper.WhisperModel = mock_whisper_model_class
mock_ctranslate2 = MagicMock()

sys.modules['faster_whisper'] = mock_faster_whisper
sys.modules['ctranslate2'] = mock_ctranslate2

# ─── 対象モジュールのトップレベルインポート ───
from subtitle_engine.whisper_transcriber import WhisperTranscriber


@pytest.fixture(autouse=True)
def reset_mocks():
    """各テスト実行前にモックをクリーンな状態にリセット"""
    mock_ctranslate2.reset_mock(side_effect=True, return_value=True)
    mock_whisper_model_class.reset_mock(side_effect=True, return_value=True)
    
    # デフォルト設定
    mock_ctranslate2.get_supported_compute_types.side_effect = None
    mock_ctranslate2.get_supported_compute_types.return_value = ["float16"]
    mock_whisper_model_class.side_effect = None
    mock_whisper_model_class.return_value = MagicMock()


def test_detect_gpu_device_normal():
    """_detect_gpu_device が cuda サポート時に cuda を返すテスト"""
    mock_ctranslate2.get_supported_compute_types.return_value = ["float16"]
    transcriber = WhisperTranscriber()
    device, compute_type = transcriber._detect_gpu_device()
    assert device == "cuda"
    assert compute_type == "float16"


def test_detect_gpu_device_fallback():
    """_detect_gpu_device が cuda 未サポート時に cpu を返すテスト"""
    mock_ctranslate2.get_supported_compute_types.side_effect = ImportError("no cuda")
    transcriber = WhisperTranscriber()
    device, compute_type = transcriber._detect_gpu_device()
    assert device == "cpu"
    assert compute_type == "int8"


def test_instantiate_model_cuda_success():
    """_instantiate_model が cuda で正常にインスタンス化するテスト"""
    transcriber = WhisperTranscriber()
    mock_model_instance = MagicMock()
    mock_whisper_model_class.return_value = mock_model_instance
    transcriber._instantiate_model("cuda", "float16")
    assert transcriber.model == mock_model_instance
    mock_whisper_model_class.assert_called_with("large-v3", device="cuda", compute_type="float16")


@pytest.mark.asyncio
async def test_write_segments_to_checkpoint_normal(tmp_path):
    """_write_segments_to_checkpoint が正しくファイル出力と進捗更新を行うテスト"""
    transcriber = WhisperTranscriber()
    checkpoint_path = tmp_path / "_test_write_segments.jsonl"
    
    segment_1 = MagicMock()
    segment_1.start = 0.0
    segment_1.end = 2.0
    segment_1.text = "Hello"
    
    progress_calls = []
    def progress_cb(status, msg, progress):
        progress_calls.append((status, msg, progress))
        
    # time.time() のモックで0.5秒以上経過させて進捗コールバックを発火させる
    with patch("time.time", side_effect=[100.0, 100.7, 100.7]):
        count = transcriber._write_segments_to_checkpoint(
            segments_iter=[segment_1],
            total_duration=10.0,
            checkpoint_path=str(checkpoint_path),
            progress_callback=progress_cb
        )
        
    assert count == 1
    assert checkpoint_path.exists()
    with open(checkpoint_path, "r", encoding="utf-8") as f:
        data = json.loads(f.read().strip())
        assert data["text"] == "Hello"
    assert len(progress_calls) > 0



def test_load_model_cuda_detected():
    """ctranslate2 が cuda をサポートしている場合の GPU 準備"""
    mock_ctranslate2.get_supported_compute_types.return_value = ["float16"]
    
    transcriber = WhisperTranscriber()
    
    # WhisperModelのインスタンス化をモック
    mock_model_instance = MagicMock()
    mock_whisper_model_class.return_value = mock_model_instance
    
    # DLL検索パスの存在判定を False にしてPATH追加処理をスルー
    with patch.object(Path, "exists", return_value=False):
        transcriber._load_model()
        
    assert transcriber.model == mock_model_instance
    mock_whisper_model_class.assert_called_with("large-v3", device="cuda", compute_type="float16")


def test_load_model_cuda_import_error():
    """ctranslate2 インポートエラーまたは未対応時の CPU フォールバック"""
    # get_supported_compute_types が ImportError を投げる
    mock_ctranslate2.get_supported_compute_types.side_effect = ImportError("no ctranslate2")
    
    transcriber = WhisperTranscriber()
    mock_model_instance = MagicMock()
    mock_whisper_model_class.return_value = mock_model_instance
    
    with patch.object(Path, "exists", return_value=False):
        transcriber._load_model()
        
    assert transcriber.model == mock_model_instance
    mock_whisper_model_class.assert_called_with("large-v3", device="cpu", compute_type="int8")


def test_load_model_cuda_unexpected_error():
    """想定外の例外が発生した場合の CPU 使用ログ出力の確認"""
    mock_ctranslate2.get_supported_compute_types.side_effect = OSError("Strange error")
    
    transcriber = WhisperTranscriber()
    mock_model_instance = MagicMock()
    mock_whisper_model_class.return_value = mock_model_instance
    
    with patch.object(Path, "exists", return_value=False):
        transcriber._load_model()
        
    assert transcriber.model == mock_model_instance
    mock_whisper_model_class.assert_called_with("large-v3", device="cpu", compute_type="int8")


def test_load_model_gpu_fails_fallback_to_cpu():
    """GPUでのロードが失敗した場合に CPU にフォールバックする挙動"""
    mock_ctranslate2.get_supported_compute_types.return_value = ["float16"]
    
    # 最初の WhisperModel 呼び出し (cuda) は RuntimeError を投げる
    # 2回目の呼び出し (cpu) は正常にモデルインスタンスを返す
    mock_cpu_model = MagicMock()
    mock_whisper_model_class.side_effect = [RuntimeError("GPU load error"), mock_cpu_model]
    
    transcriber = WhisperTranscriber()
    
    with patch.object(Path, "exists", return_value=False):
        transcriber._load_model()
        
    assert transcriber.model == mock_cpu_model
    # 2回呼ばれたことを確認
    assert mock_whisper_model_class.call_count == 2


def test_load_model_cpu_fails():
    """CPUでのロード自体が失敗した場合に例外を投げる挙動"""
    mock_ctranslate2.get_supported_compute_types.side_effect = ImportError("no cuda")
    
    # WhisperModel 呼び出しで RuntimeError
    mock_whisper_model_class.side_effect = RuntimeError("CPU load error")
    
    transcriber = WhisperTranscriber()
    
    with patch.object(Path, "exists", return_value=False):
        with pytest.raises(RuntimeError) as exc_info:
            transcriber._load_model()
        assert "CPU load error" in str(exc_info.value)


def test_load_model_unexpected_exception():
    """モデルロード中に想定外の例外（AttributeError等）が発生した場合に raise されるか"""
    mock_ctranslate2.get_supported_compute_types.side_effect = ImportError("no cuda")
    mock_whisper_model_class.side_effect = AttributeError("Unexpected mock attribute error")
    
    transcriber = WhisperTranscriber()
    with patch.object(Path, "exists", return_value=False):
        with pytest.raises(AttributeError):
            transcriber._load_model()


def test_load_model_cuda_dll_addition():
    """CUDA DLL 検索パスが存在する場合に PATH 環境変数に追加される動作"""
    mock_ctranslate2.get_supported_compute_types.side_effect = ImportError("no cuda")
    
    transcriber = WhisperTranscriber()
    mock_model_instance = MagicMock()
    mock_whisper_model_class.side_effect = None
    mock_whisper_model_class.return_value = mock_model_instance
    
    original_path = os.environ.get("PATH", "")
    
    # Path.exists が True を返すようにモック
    # Path / sub が PATH に追加されるようにする
    with patch.object(Path, "exists", return_value=True):
        transcriber._load_model()
        
    # PATH が更新されているか確認
    updated_path = os.environ.get("PATH", "")
    assert updated_path != original_path
    
    # 元に戻す
    os.environ["PATH"] = original_path


def test_get_video_duration_success():
    """ffprobe が正常に実行されて動画の長さを返すケース"""
    transcriber = WhisperTranscriber()
    
    mock_completed_process = MagicMock()
    mock_completed_process.stdout = '{"format": {"duration": "123.45"}}'
    
    with patch("subprocess.run", return_value=mock_completed_process):
        duration = transcriber._get_video_duration("dummy.mp4")
        
    assert duration == 123.45


def test_get_video_duration_subprocess_error():
    """ffprobe 実行で例外（SubprocessError）が発生した場合のフォールバック"""
    transcriber = WhisperTranscriber()
    
    with patch("subprocess.run", side_effect=subprocess.SubprocessError("error")):
        duration = transcriber._get_video_duration("dummy.mp4")
        
    assert duration == 1800.0


def test_get_video_duration_json_decode_error():
    """ffprobe の出力が JSON ではない場合のフォールバック"""
    transcriber = WhisperTranscriber()
    
    mock_completed_process = MagicMock()
    mock_completed_process.stdout = 'invalid json'
    
    with patch("subprocess.run", return_value=mock_completed_process):
        duration = transcriber._get_video_duration("dummy.mp4")
        
    assert duration == 1800.0


def test_get_video_duration_key_error():
    """ffprobe の JSON に duration キーが存在しない場合のフォールバック"""
    transcriber = WhisperTranscriber()
    
    mock_completed_process = MagicMock()
    mock_completed_process.stdout = '{"format": {}}'
    
    with patch("subprocess.run", return_value=mock_completed_process):
        duration = transcriber._get_video_duration("dummy.mp4")
        
    assert duration == 1800.0


def test_get_video_duration_unexpected_error():
    """ffprobe 実行中に予期せぬ例外が発生した場合のフォールバック"""
    transcriber = WhisperTranscriber()
    
    with patch("subprocess.run", side_effect=OSError("Unexpected")):
        duration = transcriber._get_video_duration("dummy.mp4")
        
    assert duration == 1800.0


@pytest.mark.asyncio
async def test_transcribe_success(tmp_path):
    """正常系での音声認識処理と JSONLines 保存処理（0.5秒進捗更新分岐のカバー）"""
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"dummy")
    
    transcriber = WhisperTranscriber()
    
    # _load_model と _get_video_duration をモック
    transcriber._load_model = MagicMock()
    transcriber._get_video_duration = MagicMock(return_value=10.0)
    
    # WhisperModel のモック設定
    mock_model_instance = MagicMock()
    transcriber.model = mock_model_instance
    
    mock_info = MagicMock()
    mock_info.language = "ja"
    
    segment_1 = MagicMock()
    segment_1.start = 0.0
    segment_1.end = 2.0
    segment_1.text = "こんにちは"
    
    segment_2 = MagicMock()
    segment_2.start = 2.0
    segment_2.end = 5.0
    segment_2.text = "さようなら"
    
    mock_model_instance.transcribe.return_value = ([segment_1, segment_2], mock_info)
    
    progress_calls = []
    def progress_cb(status, msg, progress):
        progress_calls.append((status, msg, progress))
        
    # time.time() をモックして、1回目のループと2回目のループで 0.6秒 経過するように見せる
    # side_effect の値：
    # 1. 176行目の time.time() -> 100.0
    # 2. 185行目の 1回目 time.time() -> 100.1 (差分 0.1秒)
    # 3. 185行目の 2回目 time.time() -> 100.7 (差分 0.6秒 -> 条件合致)
    # 4. 188行目の time.time() -> 100.7 (更新)
    with patch("time.time", side_effect=[100.0, 100.1, 100.7, 100.7]):
        checkpoint_path = await transcriber.transcribe(
            video_path=str(video_path),
            progress_callback=progress_cb
        )
    
    expected_checkpoint_path = str(tmp_path / "_whisper_segments.jsonl")
    assert checkpoint_path == expected_checkpoint_path
    
    # ファイルに正しく JSONLines が保存されたか検証
    assert Path(checkpoint_path).exists()
    with open(checkpoint_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        assert len(lines) == 2
        d1 = json.loads(lines[0])
        d2 = json.loads(lines[1])
        assert d1["text"] == "こんにちは"
        assert d2["text"] == "さようなら"
        
    # コールバックの呼び出し履歴を検証
    assert len(progress_calls) >= 4
    # 0.5秒条件により progress_cb("processing", "Transcribing... 50%", 50) が呼ばれたことを確認
    transcribe_progress_calls = [x for x in progress_calls if "%" in str(x[1])]
    assert len(transcribe_progress_calls) > 0


@pytest.mark.asyncio
async def test_transcribe_file_not_found(tmp_path):
    """動画ファイルが見つからない場合の FileNotFoundError ガード"""
    transcriber = WhisperTranscriber()
    transcriber._load_model = MagicMock()
    transcriber._get_video_duration = MagicMock(side_effect=FileNotFoundError("file not found"))
    
    progress_calls = []
    def progress_cb(status, msg, progress):
        progress_calls.append((status, msg, progress))
        
    result = await transcriber.transcribe(
        video_path="nonexistent.mp4",
        progress_callback=progress_cb
    )
    
    assert isinstance(result, list)
    assert "音声認識に失敗しました" in result[0]["text"]
    assert progress_calls[-1][0] == "failed"


@pytest.mark.asyncio
async def test_transcribe_general_exception(tmp_path):
    """音声認識中に一般的な例外が発生した場合のフォールバック"""
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"dummy")
    
    transcriber = WhisperTranscriber()
    transcriber._load_model = MagicMock()
    transcriber._get_video_duration = MagicMock(return_value=10.0)
    
    # transcribe() で例外を投げる
    mock_model_instance = MagicMock()
    mock_model_instance.transcribe.side_effect = RuntimeError("Transcribe failed")
    transcriber.model = mock_model_instance
    
    progress_calls = []
    def progress_cb(status, msg, progress):
        progress_calls.append((status, msg, progress))
        
    result = await transcriber.transcribe(
        video_path=str(video_path),
        progress_callback=progress_cb
    )
    
    assert isinstance(result, list)
    assert "音声認識に失敗しました" in result[0]["text"]
    assert progress_calls[-1][0] == "failed"


@pytest.mark.asyncio
async def test_transcribe_with_proofreading(tmp_path):
    """校閲統合機能のテスト"""
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"dummy")
    
    checkpoint_path = tmp_path / "_whisper_segments.jsonl"
    dummy_segments = [
        {"start": 0.0, "end": 2.0, "text": "元のテキスト", "sourceStart": 0.0, "sourceEnd": 2.0}
    ]
    with open(checkpoint_path, "w", encoding="utf-8") as f:
        for seg in dummy_segments:
            f.write(json.dumps(seg, ensure_ascii=False) + "\n")
            
    transcriber = WhisperTranscriber()
    
    # transcribe メソッドを AsyncMock でモックして、ダミーのチェックポイントパスを返す
    from unittest.mock import AsyncMock
    transcriber.transcribe = AsyncMock(return_value=str(checkpoint_path))
    
    progress_calls = []
    def progress_cb(status, msg, progress):
        progress_calls.append((status, msg, progress))
        
    # ai_proofreader.proofread_segments をモック
    mock_proofread_segments = MagicMock(return_value=[{"start": 0.0, "end": 2.0, "text": "校閲済み"}])
    
    with patch("subtitle_engine.ai_proofreader.proofread_segments", mock_proofread_segments):
        result = await transcriber.transcribe_with_proofreading(
            video_path=str(video_path),
            progress_callback=progress_cb
        )
        
    assert result == [{"start": 0.0, "end": 2.0, "text": "校閲済み"}]
    mock_proofread_segments.assert_called_with(dummy_segments, update_callback=progress_cb)
    
    assert progress_calls[-2][1] == "AI校閲を実行中 (Gemini 3.0)..."
    assert progress_calls[-1][0] == "completed"

def test_load_model_already_loaded():
    """すでにモデルがロードされている場合は早期リターンする"""
    transcriber = WhisperTranscriber()
    mock_existing_model = MagicMock()
    transcriber.model = mock_existing_model
    
    with patch("subtitle_engine.whisper_transcriber.WhisperModel") as mock_whisper:
        transcriber._load_model()
        mock_whisper.assert_not_called()
        
    assert transcriber.model == mock_existing_model


def test_load_model_dll_already_in_path():
    """追加対象の DLL パスがすでに PATH に含まれている場合、追加処理をスキップする"""
    transcriber = WhisperTranscriber()
    mock_model_instance = MagicMock()
    mock_whisper_model_class.side_effect = None
    mock_whisper_model_class.return_value = mock_model_instance
    
    import os, sys
    nvidia_dir = Path(sys.executable).parent.parent / "Lib" / "site-packages" / "nvidia"
    second_nvidia_dir = Path(r"C:\Users\PC_User\Desktop\script\vault-environments\.venv\Lib\site-packages\nvidia")
    
    dll_paths = [
        str(nvidia_dir / "cublas" / "bin"),
        str(nvidia_dir / "cudnn" / "bin"),
        str(nvidia_dir / "cuda_nvrtc" / "bin"),
        str(second_nvidia_dir / "cublas" / "bin"),
        str(second_nvidia_dir / "cudnn" / "bin"),
        str(second_nvidia_dir / "cuda_nvrtc" / "bin"),
    ]
    
    original_path = os.environ.get("PATH", "")
    prepended_path = os.pathsep.join(dll_paths)
    os.environ["PATH"] = prepended_path + os.pathsep + original_path
    current_path = os.environ["PATH"]
    
    try:
        with patch.object(Path, "exists", return_value=True):
            transcriber._load_model()
            
        assert os.environ.get("PATH", "") == current_path
    finally:
        os.environ["PATH"] = original_path


@pytest.mark.asyncio
async def test_transcribe_without_progress_callback(tmp_path):
    """progress_callback が None の状態での正常系文字起こし"""
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"dummy")
    
    transcriber = WhisperTranscriber()
    transcriber._load_model = MagicMock()
    transcriber._get_video_duration = MagicMock(return_value=10.0)
    
    mock_model_instance = MagicMock()
    transcriber.model = mock_model_instance
    
    mock_info = MagicMock()
    mock_info.language = "ja"
    
    segment = MagicMock()
    segment.start = 0.0
    segment.end = 2.0
    segment.text = "テスト"
    
    mock_model_instance.transcribe.return_value = ([segment], mock_info)
    
    with patch("time.time", side_effect=[100.0, 100.7, 100.7]):
        checkpoint_path = await transcriber.transcribe(
            video_path=str(video_path),
            progress_callback=None
        )
    
    assert Path(checkpoint_path).exists()


@pytest.mark.asyncio
async def test_transcribe_file_not_found_without_callback():
    """progress_callback が None の状態で FileNotFoundError が発生したケース"""
    transcriber = WhisperTranscriber()
    transcriber._load_model = MagicMock()
    transcriber._get_video_duration = MagicMock(side_effect=FileNotFoundError("file not found"))
    
    result = await transcriber.transcribe(
        video_path="nonexistent.mp4",
        progress_callback=None
    )
    
    assert isinstance(result, list)
    assert "音声認識に失敗しました" in result[0]["text"]


@pytest.mark.asyncio
async def test_transcribe_general_exception_without_callback(tmp_path):
    """progress_callback が None の状態で一般的例外が発生したケース"""
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"dummy")
    
    transcriber = WhisperTranscriber()
    transcriber._load_model = MagicMock()
    transcriber._get_video_duration = MagicMock(return_value=10.0)
    
    mock_model_instance = MagicMock()
    mock_model_instance.transcribe.side_effect = RuntimeError("Transcribe failed")
    transcriber.model = mock_model_instance
    
    result = await transcriber.transcribe(
        video_path=str(video_path),
        progress_callback=None
    )
    
    assert isinstance(result, list)
    assert "音声認識に失敗しました" in result[0]["text"]


@pytest.mark.asyncio
async def test_transcribe_with_proofreading_without_callback(tmp_path):
    """progress_callback が None の状態での校閲統合機能"""
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"dummy")
    
    checkpoint_path = tmp_path / "_whisper_segments.jsonl"
    dummy_segments = [
        {"start": 0.0, "end": 2.0, "text": "元のテキスト", "sourceStart": 0.0, "sourceEnd": 2.0}
    ]
    with open(checkpoint_path, "w", encoding="utf-8") as f:
        for seg in dummy_segments:
            f.write(json.dumps(seg, ensure_ascii=False) + "\n")
            
    transcriber = WhisperTranscriber()
    
    from unittest.mock import AsyncMock
    transcriber.transcribe = AsyncMock(return_value=str(checkpoint_path))
    
    mock_proofread_segments = MagicMock(return_value=[{"start": 0.0, "end": 2.0, "text": "校閲完了"}])
    
    with patch("subtitle_engine.ai_proofreader.proofread_segments", mock_proofread_segments):
        result = await transcriber.transcribe_with_proofreading(
            video_path=str(video_path),
            progress_callback=None
        )
        
    assert result == [{"start": 0.0, "end": 2.0, "text": "校閲完了"}]
    mock_proofread_segments.assert_called_with(dummy_segments, update_callback=None)


@pytest.mark.asyncio
async def test_transcribe_progress_callback_throttled(tmp_path):
    """進捗コールバックが0.5秒未満の頻度で呼ばれた場合にスロットリング（更新スキップ）されるか検証"""
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"dummy")
    
    transcriber = WhisperTranscriber()
    transcriber._load_model = MagicMock()
    transcriber._get_video_duration = MagicMock(return_value=10.0)
    
    mock_model_instance = MagicMock()
    transcriber.model = mock_model_instance
    
    mock_info = MagicMock()
    mock_info.language = "ja"
    
    segment_1 = MagicMock()
    segment_1.start = 0.0
    segment_1.end = 2.0
    segment_1.text = "こんにちは"
    
    segment_2 = MagicMock()
    segment_2.start = 2.0
    segment_2.end = 5.0
    segment_2.text = "さようなら"
    
    mock_model_instance.transcribe.return_value = ([segment_1, segment_2], mock_info)
    
    progress_calls = []
    def progress_cb(status, msg, progress):
        progress_calls.append((status, msg, progress))
        
    with patch("time.time", side_effect=[100.0, 100.1, 100.2]):
        checkpoint_path = await transcriber.transcribe(
            video_path=str(video_path),
            progress_callback=progress_cb
        )
        
    loop_progress_calls = [x for x in progress_calls if "Transcribing... " in str(x[1])]
    assert len(loop_progress_calls) == 0


@pytest.mark.asyncio
async def test_transcribe_with_proofreading_failure(tmp_path):
    """校閲処理中に例外が発生した場合に例外が伝播するか検証"""
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"dummy")
    
    checkpoint_path = tmp_path / "_whisper_segments.jsonl"
    checkpoint_path.write_text("", encoding="utf-8")
    
    transcriber = WhisperTranscriber()
    
    from unittest.mock import AsyncMock
    transcriber.transcribe = AsyncMock(return_value=str(checkpoint_path))
    
    with patch("subtitle_engine.ai_proofreader.proofread_segments", side_effect=ValueError("Proofread API error")):
        with pytest.raises(ValueError) as exc_info:
            await transcriber.transcribe_with_proofreading(
                video_path=str(video_path),
                progress_callback=None
            )
        assert "Proofread API error" in str(exc_info.value)


def test_get_video_duration_value_error():
    """ffprobe が返す duration が float 変換できない無効値の場合のフォールバック検証"""
    transcriber = WhisperTranscriber()
    
    mock_completed_process = MagicMock()
    mock_completed_process.stdout = '{"format": {"duration": "not_a_float"}}'
    
    with patch("subprocess.run", return_value=mock_completed_process):
        duration = transcriber._get_video_duration("dummy.mp4")
        
    assert duration == 1800.0


def test_load_model_gpu_fails_value_error():
    """GPUでのロードが ValueError で失敗した場合に CPU にフォールバックする挙動を検証"""
    mock_ctranslate2.get_supported_compute_types.return_value = ["float16"]
    
    mock_cpu_model = MagicMock()
    mock_whisper_model_class.side_effect = [ValueError("GPU load ValueError"), mock_cpu_model]
    
    transcriber = WhisperTranscriber()
    
    with patch.object(Path, "exists", return_value=False):
        transcriber._load_model()
        
    assert transcriber.model == mock_cpu_model
    assert mock_whisper_model_class.call_count == 2


def test_load_model_cpu_fails_value_error():
    """CPUでのロードが ValueError で失敗した場合に適切に raise されるか検証"""
    mock_ctranslate2.get_supported_compute_types.side_effect = ImportError("no cuda")
    mock_whisper_model_class.side_effect = ValueError("CPU load ValueError")
    
    transcriber = WhisperTranscriber()
    
    with patch.object(Path, "exists", return_value=False):
        with pytest.raises(ValueError) as exc_info:
            transcriber._load_model()
        assert "CPU load ValueError" in str(exc_info.value)


@pytest.mark.asyncio
async def test_transcribe_with_diarization_args(tmp_path):
    """enable_diarization などの引数を渡してもエラーにならず正常動作するか検証"""
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"dummy")
    
    transcriber = WhisperTranscriber()
    transcriber._load_model = MagicMock()
    transcriber._get_video_duration = MagicMock(return_value=10.0)
    
    mock_model_instance = MagicMock()
    transcriber.model = mock_model_instance
    
    mock_info = MagicMock()
    mock_info.language = "ja"
    
    segment = MagicMock()
    segment.start = 0.0
    segment.end = 2.0
    segment.text = "テスト"
    
    mock_model_instance.transcribe.return_value = ([segment], mock_info)
    
    checkpoint_path = await transcriber.transcribe(
        video_path=str(video_path),
        enable_diarization=True,
        num_speakers=2
    )
    
    assert Path(checkpoint_path).exists()


@pytest.mark.asyncio
async def test_get_video_duration_timeout_error():
    """ffprobe がタイムアウト（subprocess.TimeoutExpired）した場合のフォールバック検証"""
    transcriber = WhisperTranscriber()
    
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["ffprobe"], timeout=30)):
        duration = transcriber._get_video_duration("dummy.mp4")
        
    assert duration == 1800.0


@pytest.mark.asyncio
async def test_transcribe_callback_exception(tmp_path):
    """progress_callback が例外を投げた場合に例外が伝播するか検証"""
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"dummy")
    
    transcriber = WhisperTranscriber()
    transcriber._load_model = MagicMock()
    transcriber._get_video_duration = MagicMock(return_value=10.0)
    
    def bad_callback(status, msg, progress):
        raise ValueError("Callback crash")
        
    with pytest.raises(ValueError) as exc_info:
        await transcriber.transcribe(
            video_path=str(video_path),
            progress_callback=bad_callback
        )
    assert "Callback crash" in str(exc_info.value)


@pytest.mark.asyncio
async def test_transcribe_iteration_exception(tmp_path):
    """文字起こしのイテレーションループ途中で例外が発生した場合のハンドリング"""
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"dummy")
    
    transcriber = WhisperTranscriber()
    transcriber._load_model = MagicMock()
    transcriber._get_video_duration = MagicMock(return_value=10.0)
    
    mock_model_instance = MagicMock()
    transcriber.model = mock_model_instance
    
    mock_info = MagicMock()
    mock_info.language = "ja"
    
    # 1回目のループで正常なセグメントを返し、2回目のループで例外を投げるジェネレータ
    def generator_with_exception():
        segment = MagicMock()
        segment.start = 0.0
        segment.end = 2.0
        segment.text = "こんにちは"
        yield segment
        raise RuntimeError("Iteration crash")
        
    mock_model_instance.transcribe.return_value = (generator_with_exception(), mock_info)
    
    progress_calls = []
    def progress_cb(status, msg, progress):
        progress_calls.append((status, msg, progress))
        
    result = await transcriber.transcribe(
        video_path=str(video_path),
        progress_callback=progress_cb
    )
    
    # イテレーションエラーが発生したため、フォールバック結果のリストが返ることを確認
    assert isinstance(result, list)
    assert "音声認識に失敗しました" in result[0]["text"]
    assert progress_calls[-1][0] == "failed"
    assert "Iteration crash" in progress_calls[-1][1]


def test_load_model_partial_dll_path_exists():
    """NVIDIA DLLのディレクトリの一部だけが存在する場合、存在するパスのみがPATHに追加される挙動"""
    transcriber = WhisperTranscriber()
    mock_model_instance = MagicMock()
    mock_whisper_model_class.side_effect = None
    mock_whisper_model_class.return_value = mock_model_instance
    
    original_path = os.environ.get("PATH", "")
    
    # Path.exists の挙動をモック：特定の dll_path のみ True にする
    def exists_mock(self_path):
        p_str = str(self_path).replace("\\", "/")
        # vault-environments のパスが存在すると仮定
        if "vault-environments" in p_str:
            if p_str.endswith("nvidia"):
                return True
            if "cublas" in p_str:
                return True
        return False

    with patch.object(Path, "exists", autospec=True) as mock_exists:
        mock_exists.side_effect = exists_mock
        transcriber._load_model()
        
    updated_path = os.environ.get("PATH", "")
    
    # "cublas/bin" は追加されているが、"cudnn/bin" や "cuda_nvrtc/bin" は追加されていないことを検証
    assert "cublas/bin" in updated_path.replace("\\", "/")
    assert "cudnn/bin" not in updated_path.replace("\\", "/")
    
    # クリーンアップ
    os.environ["PATH"] = original_path




def test_load_model_cuda_attribute_error():
    """GPU検出時に AttributeError が発生した場合の挙動確認"""
    mock_ctranslate2.get_supported_compute_types.side_effect = AttributeError("Missing attribute")
    
    transcriber = WhisperTranscriber()
    mock_model_instance = MagicMock()
    mock_whisper_model_class.return_value = mock_model_instance
    
    with patch.object(Path, "exists", return_value=False):
        transcriber._load_model()
        
    assert transcriber.model == mock_model_instance
    mock_whisper_model_class.assert_called_with("large-v3", device="cpu", compute_type="int8")


def test_load_model_unexpected_key_error():
    """モデルロード中に KeyError が発生した場合に raise されるか"""
    mock_ctranslate2.get_supported_compute_types.side_effect = ImportError("no cuda")
    mock_whisper_model_class.side_effect = KeyError("Invalid setting key")
    
    transcriber = WhisperTranscriber()
    with patch.object(Path, "exists", return_value=False):
        with pytest.raises(KeyError):
            transcriber._load_model()


def test_get_video_duration_type_error():
    """ffprobe 実行中に TypeError が発生した場合のフォールバック"""
    transcriber = WhisperTranscriber()
    
    with patch("subprocess.run", side_effect=TypeError("Invalid type")):
        duration = transcriber._get_video_duration("dummy.mp4")
        
    assert duration == 1800.0


@pytest.mark.asyncio
async def test_transcribe_key_error(tmp_path):
    """文字起こし処理中に KeyError が発生した場合のフォールバック"""
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"dummy")
    
    transcriber = WhisperTranscriber()
    transcriber._load_model = MagicMock()
    transcriber._get_video_duration = MagicMock(return_value=10.0)
    
    mock_model_instance = MagicMock()
    transcriber.model = mock_model_instance
    
    # transcribe メソッドで KeyError をスローさせる
    mock_model_instance.transcribe.side_effect = KeyError("Mock key error")
    
    progress_calls = []
    def progress_cb(status, msg, progress):
        progress_calls.append((status, msg, progress))
        
    result = await transcriber.transcribe(
        video_path=str(video_path),
        progress_callback=progress_cb
    )
    
    assert isinstance(result, list)
    assert "音声認識に失敗しました" in result[0]["text"]
    assert progress_calls[-1][0] == "failed"
    assert "Mock key error" in progress_calls[-1][1]


@pytest.mark.asyncio
async def test_transcribe_with_proofreading_already_list(tmp_path):
    """transcribe がすでにリストを返す場合の動作検証（フォールバック時など）"""
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"dummy")
    
    transcriber = WhisperTranscriber()
    
    # すでにリストが返る場合
    fallback_segments = [{"start": 0.0, "end": 1.0, "text": "音声認識に失敗しました"}]
    from unittest.mock import AsyncMock
    transcriber.transcribe = AsyncMock(return_value=fallback_segments)
    
    mock_proofread_segments = MagicMock(return_value=[{"start": 0.0, "end": 1.0, "text": "校閲済み（フォールバック）"}])
    
    with patch("subtitle_engine.ai_proofreader.proofread_segments", mock_proofread_segments):
        result = await transcriber.transcribe_with_proofreading(
            video_path=str(video_path),
            progress_callback=None
        )
        
    assert result == [{"start": 0.0, "end": 1.0, "text": "校閲済み（フォールバック）"}]
    mock_proofread_segments.assert_called_with(fallback_segments, update_callback=None)


@pytest.mark.asyncio
async def test_transcribe_with_proofreading_checkpoint_missing(tmp_path):
    """チェックポイントファイルが存在しない場合、空リストに安全にフォールバックすることを確認"""
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"dummy")
    
    transcriber = WhisperTranscriber()
    
    # 存在しないチェックポイントパスを返すようにモック
    non_existent_path = tmp_path / "non_existent_file.jsonl"
    from unittest.mock import AsyncMock
    transcriber.transcribe = AsyncMock(return_value=str(non_existent_path))
    
    mock_proofread_segments = MagicMock(return_value=[])
    
    with patch("subtitle_engine.ai_proofreader.proofread_segments", mock_proofread_segments):
        result = await transcriber.transcribe_with_proofreading(
            video_path=str(video_path),
            progress_callback=None
        )
        
    assert result == []
    # 空のリストが proofread_segments に渡されていること
    mock_proofread_segments.assert_called_with([], update_callback=None)


@pytest.mark.asyncio
async def test_transcribe_with_proofreading_checkpoint_corrupted(tmp_path):
    """チェックポイントファイルが破損している（JSONとして不正）場合、安全にフォールバックすることを確認"""
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"dummy")
    
    # 不正なJSONデータをファイルに書き込む
    checkpoint_path = tmp_path / "corrupted_checkpoint.jsonl"
    checkpoint_path.write_text("invalid json lines\n{not even close}", encoding="utf-8")
    
    transcriber = WhisperTranscriber()
    
    from unittest.mock import AsyncMock
    transcriber.transcribe = AsyncMock(return_value=str(checkpoint_path))
    
    mock_proofread_segments = MagicMock(return_value=[])
    
    with patch("subtitle_engine.ai_proofreader.proofread_segments", mock_proofread_segments):
        result = await transcriber.transcribe_with_proofreading(
            video_path=str(video_path),
            progress_callback=None
        )
        
    assert result == []
    mock_proofread_segments.assert_called_with([], update_callback=None)


@pytest.mark.asyncio
async def test_transcribe_disk_full_exception(tmp_path):
    """_write_segments_to_checkpoint書き込み中に OSError (ディスクフル等) が発生した場合のフォールバック検証"""
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"dummy")
    
    transcriber = WhisperTranscriber()
    transcriber._load_model = MagicMock()
    transcriber._get_video_duration = MagicMock(return_value=10.0)
    
    mock_model_instance = MagicMock()
    transcriber.model = mock_model_instance
    
    mock_info = MagicMock()
    mock_info.language = "ja"
    
    segment = MagicMock()
    segment.start = 0.0
    segment.end = 2.0
    segment.text = "こんにちは"
    
    mock_model_instance.transcribe.return_value = ([segment], mock_info)
    
    with patch("builtins.open", side_effect=OSError("No space left on device")):
        result = await transcriber.transcribe(
            video_path=str(video_path),
            progress_callback=None
        )
        
    assert isinstance(result, list)
    assert "音声認識に失敗しました" in result[0]["text"]


@pytest.mark.asyncio
async def test_transcribe_with_proofreading_invalid_type(tmp_path):
    """transcribe が想定外の型 (dictなど) を返した場合に transcribe_with_proofreading が安全にハンドリングするか検証"""
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"dummy")
    
    transcriber = WhisperTranscriber()
    
    from unittest.mock import AsyncMock
    transcriber.transcribe = AsyncMock(return_value={"invalid": "type"})
    
    mock_proofread_segments = MagicMock(return_value=[])
    
    with patch("subtitle_engine.ai_proofreader.proofread_segments", mock_proofread_segments):
        result = await transcriber.transcribe_with_proofreading(
            video_path=str(video_path),
            progress_callback=None
        )
        
    assert result == []
    mock_proofread_segments.assert_called_with([], update_callback=None)


@pytest.mark.asyncio
async def test_transcribe_empty_path():
    """空文字列のパスが渡された場合に、FileNotFoundError として適切にガードされるか検証"""
    transcriber = WhisperTranscriber()
    transcriber._load_model = MagicMock()
    
    transcriber._get_video_duration = MagicMock(side_effect=FileNotFoundError("Empty path is invalid"))
    
    result = await transcriber.transcribe(
        video_path="",
        progress_callback=None
    )
    
    assert isinstance(result, list)
    assert "音声認識に失敗しました（ファイル未検出）" in result[0]["text"]


def test_load_model_unexpected_import_error():
    """ctranslate2 読み込み時に未知の ImportError が発生した場合でも CPU にフォールバックするか検証"""
    mock_ctranslate2.get_supported_compute_types.side_effect = ImportError("Unexpected module missing")
    
    transcriber = WhisperTranscriber()
    mock_model_instance = MagicMock()
    mock_whisper_model_class.return_value = mock_model_instance
    
    with patch.object(Path, "exists", return_value=False):
        transcriber._load_model()
        
    assert transcriber.model == mock_model_instance
    mock_whisper_model_class.assert_called_with("large-v3", device="cpu", compute_type="int8")


@pytest.mark.asyncio
async def test_transcribe_with_proofreading_checkpoint_io_error(tmp_path):
    """チェックポイントファイルの読み込み時に OSError が発生した場合、安全にフォールバックすることを確認"""
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"dummy")
    
    checkpoint_path = tmp_path / "io_error_checkpoint.jsonl"
    checkpoint_path.write_text('{"start": 0.0, "end": 1.0, "text": "test"}', encoding="utf-8")
    
    transcriber = WhisperTranscriber()
    
    from unittest.mock import AsyncMock
    transcriber.transcribe = AsyncMock(return_value=str(checkpoint_path))
    
    mock_proofread_segments = MagicMock(return_value=[])
    
    # open() が OSError を発生させるようにモック
    with patch("builtins.open", side_effect=OSError("Mock IO error")):
        with patch("subtitle_engine.ai_proofreader.proofread_segments", mock_proofread_segments):
            result = await transcriber.transcribe_with_proofreading(
                video_path=str(video_path),
                progress_callback=None
            )
            
    assert result == []
    mock_proofread_segments.assert_called_with([], update_callback=None)


@pytest.mark.asyncio
async def test_transcribe_disk_full_exception(tmp_path):
    """_write_segments_to_checkpoint書き込み中に OSError (ディスクフル等) が発生した場合のフォールバック検証"""
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"dummy")
    
    transcriber = WhisperTranscriber()
    transcriber._load_model = MagicMock()
    transcriber._get_video_duration = MagicMock(return_value=10.0)
    
    mock_model_instance = MagicMock()
    transcriber.model = mock_model_instance
    
    mock_info = MagicMock()
    mock_info.language = "ja"
    
    segment = MagicMock()
    segment.start = 0.0
    segment.end = 2.0
    segment.text = "こんにちは"
    
    mock_model_instance.transcribe.return_value = ([segment], mock_info)
    
    with patch("builtins.open", side_effect=OSError("No space left on device")):
        result = await transcriber.transcribe(
            video_path=str(video_path),
            progress_callback=None
        )
        
    assert isinstance(result, list)
    assert "音声認識に失敗しました" in result[0]["text"]


@pytest.mark.asyncio
async def test_transcribe_with_proofreading_invalid_type(tmp_path):
    """transcribe が想定外の型 (dictなど) を返した場合に transcribe_with_proofreading が安全にハンドリングするか検証"""
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"dummy")
    
    transcriber = WhisperTranscriber()
    
    from unittest.mock import AsyncMock
    transcriber.transcribe = AsyncMock(return_value={"invalid": "type"})
    
    mock_proofread_segments = MagicMock(return_value=[])
    
    with patch("subtitle_engine.ai_proofreader.proofread_segments", mock_proofread_segments):
        result = await transcriber.transcribe_with_proofreading(
            video_path=str(video_path),
            progress_callback=None
        )
        
    assert result == []
    mock_proofread_segments.assert_called_with([], update_callback=None)


@pytest.mark.asyncio
async def test_transcribe_empty_path():
    """空文字列のパスが渡された場合に、FileNotFoundError として適切にガードされるか検証"""
    transcriber = WhisperTranscriber()
    transcriber._load_model = MagicMock()
    
    transcriber._get_video_duration = MagicMock(side_effect=FileNotFoundError("Empty path is invalid"))
    
    result = await transcriber.transcribe(
        video_path="",
        progress_callback=None
    )
    
    assert isinstance(result, list)
    assert "音声認識に失敗しました（ファイル未検出）" in result[0]["text"]


def test_load_model_unexpected_import_error():
    """ctranslate2 読み込み時に未知の ImportError が発生した場合でも CPU にフォールバックするか検証"""
    mock_ctranslate2.get_supported_compute_types.side_effect = ImportError("Unexpected module missing")
    
    transcriber = WhisperTranscriber()
    mock_model_instance = MagicMock()
    mock_whisper_model_class.return_value = mock_model_instance
    
    with patch.object(Path, "exists", return_value=False):
        transcriber._load_model()
        
    assert transcriber.model == mock_model_instance
    mock_whisper_model_class.assert_called_with("large-v3", device="cpu", compute_type="int8")

