"""
M2.6 Batch 2: subtitle_engine テスト（0%脱出）

対象:
- subtitle_engine/whisper_subprocess.py (154 stmts, 0%)
- subtitle_engine/speaker_diarizer.py (154 stmts, 0%)
"""

import pytest
import sys
import json
import queue
from pathlib import Path
from unittest.mock import patch, MagicMock

_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from subtitle_engine.speaker_diarizer import (
    SpeakerDiarizer, SpeakerSegment, DiarizationResult,
)
from subtitle_engine.whisper_subprocess import (
    extract_audio_wav, split_wav_chunks, transcribe_chunk,
    CHUNK_DURATION, CHUNK_TIMEOUT,
)
from subtitle_engine.video_hash import (
    compute_video_hash, get_checkpoint_path, OLD_CHECKPOINT_NAME,
)
from subtitle_engine.formatter import SubtitleFormatter


# ============================================================
# speaker_diarizer.py テスト
# ============================================================

class TestSpeakerDiarizer:

    def test_init_no_pyannote(self):
        d = SpeakerDiarizer()
        # pyannote未インストール環境ではFalse
        assert isinstance(d._pyannote_available, bool)

    def test_parse_silence_detect_empty(self):
        d = SpeakerDiarizer()
        assert d._parse_silence_detect("") == []

    def test_parse_silence_detect_normal(self):
        stderr = (
            "silence_start: 1.5\n"
            "silence_end: 3.2\n"
            "silence_start: 8.0\n"
            "silence_end: 9.5\n"
        )
        d = SpeakerDiarizer()
        intervals = d._parse_silence_detect(stderr)
        assert len(intervals) == 2
        assert intervals[0] == (1.5, 3.2)
        assert intervals[1] == (8.0, 9.5)

    def test_invert_intervals_empty(self):
        d = SpeakerDiarizer()
        result = d._invert_intervals([], 60.0)
        assert result == [(0.0, 60.0)]

    def test_invert_intervals_single(self):
        d = SpeakerDiarizer()
        result = d._invert_intervals([(5.0, 10.0)], 20.0)
        assert result == [(0.0, 5.0), (10.0, 20.0)]

    def test_invert_intervals_full_silence(self):
        d = SpeakerDiarizer()
        result = d._invert_intervals([(0.0, 60.0)], 60.0)
        assert result == []

    def test_invert_intervals_multiple(self):
        d = SpeakerDiarizer()
        result = d._invert_intervals([(2.0, 4.0), (8.0, 10.0)], 15.0)
        assert result == [(0.0, 2.0), (4.0, 8.0), (10.0, 15.0)]

    def test_get_duration_success(self):
        d = SpeakerDiarizer()
        mock_result = MagicMock()
        mock_result.stdout = json.dumps({"format": {"duration": "120.5"}})
        with patch("subtitle_engine.speaker_diarizer.subprocess.run", return_value=mock_result):
            dur = d._get_duration("/test.mp4")
        assert dur == 120.5

    def test_get_duration_fallback(self):
        d = SpeakerDiarizer()
        with patch("subtitle_engine.speaker_diarizer.subprocess.run", side_effect=OSError("err")):
            dur = d._get_duration("/test.mp4")
        assert dur == 3600.0  # フォールバック

    def test_parse_energy_from_stderr(self):
        d = SpeakerDiarizer()
        stderr = "silence_start: 5.0\nsilence_end: 10.0\n"
        result = d._parse_energy_from_stderr(stderr, 20.0, 0.5)
        assert result == [(0.0, 5.0), (10.0, 20.0)]

    def test_assign_speakers_empty_diarization(self):
        d = SpeakerDiarizer()
        segs = [{"start": 0, "end": 5, "text": "hello"}]
        dr = DiarizationResult(segments=[], num_speakers=0)
        result = d.assign_speakers_to_segments(segs, dr)
        assert result == segs  # unchanged

    def test_assign_speakers_midpoint_match(self):
        d = SpeakerDiarizer()
        segs = [
            {"start": 0, "end": 4, "text": "first"},
            {"start": 6, "end": 10, "text": "second"},
        ]
        dr = DiarizationResult(
            segments=[
                SpeakerSegment(start=0, end=5, speaker_id="speaker_0", confidence=0.9),
                SpeakerSegment(start=5, end=12, speaker_id="speaker_1", confidence=0.8),
            ],
            num_speakers=2,
            method="vad",
        )
        result = d.assign_speakers_to_segments(segs, dr)
        assert result[0]["speaker_id"] == "speaker_0"
        assert result[1]["speaker_id"] == "speaker_1"

    def test_assign_speakers_closest_fallback(self):
        d = SpeakerDiarizer()
        segs = [{"start": 100, "end": 105, "text": "far away"}]
        dr = DiarizationResult(
            segments=[
                SpeakerSegment(start=0, end=5, speaker_id="speaker_0", confidence=0.9),
            ],
            num_speakers=1,
        )
        result = d.assign_speakers_to_segments(segs, dr)
        assert result[0]["speaker_id"] == "speaker_0"
        assert result[0]["speaker_confidence"] < 0.9  # reduced confidence

    @pytest.mark.asyncio
    async def test_diarize_vad(self):
        d = SpeakerDiarizer()
        d._pyannote_available = False
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = "silence_start: 5.0\nsilence_end: 8.0\n"
        with patch("subtitle_engine.speaker_diarizer.subprocess.run", return_value=mock_result):
            with patch.object(d, "_get_duration", return_value=20.0):
                result = await d.diarize("/test.mp4", method="vad")
        assert result.method == "vad"
        assert result.num_speakers == 2
        assert len(result.segments) > 0

    @pytest.mark.asyncio
    async def test_diarize_stereo_success(self):
        d = SpeakerDiarizer()
        
        # ffprobe モック: ステレオ 2チャンネル, duration=60.0
        mock_probe = MagicMock()
        mock_probe.stdout = json.dumps({
            "streams": [{"channels": 2, "duration": "60.0"}]
        })
        
        # ffmpeg silencedetect モック
        # Lチャンネル(0): 10〜20秒が無音 -> 発話は 0〜10, 20〜60
        # Rチャンネル(1): 30〜40秒が無音 -> 発話は 0〜30, 40〜60
        mock_ffmpeg_L = MagicMock()
        mock_ffmpeg_L.stderr = "silence_start: 10.0\nsilence_end: 20.0\n"
        
        mock_ffmpeg_R = MagicMock()
        mock_ffmpeg_R.stderr = "silence_start: 30.0\nsilence_end: 40.0\n"
        
        # subprocess.run 呼び出し回数に応じてモックを切り替える
        def mock_run(cmd, **kwargs):
            if "ffprobe" in cmd[0]:
                return mock_probe
            elif "ffmpeg" in cmd[0]:
                # pan=mono|c0=c0 なら Lチャンネル、c1 なら Rチャンネル
                af_arg = cmd[cmd.index("-af") + 1]
                if "c0" in af_arg:
                    return mock_ffmpeg_L
                elif "c1" in af_arg:
                    return mock_ffmpeg_R
            return MagicMock(stdout="", stderr="")

        with patch("subtitle_engine.speaker_diarizer.subprocess.run", side_effect=mock_run):
            result = await d.diarize("/test.mp4", method="stereo")
            
        assert result.method == "stereo"
        assert result.num_speakers == 2
        # Lの発話(0~10, 20~60), Rの発話(0~30, 40~60) -> 合計4セグメント
        assert len(result.segments) == 4
        # 時系列順ソートの検証
        starts = [s.start for s in result.segments]
        assert starts == sorted(starts)
        
        # speaker_0 と speaker_1 が含まれていること
        speakers = set(s.speaker_id for s in result.segments)
        assert speakers == {"speaker_0", "speaker_1"}

    @pytest.mark.asyncio
    async def test_diarize_stereo_mono_fallback(self):
        d = SpeakerDiarizer()
        
        # ffprobe モック: モノラル 1チャンネル
        mock_probe = MagicMock()
        mock_probe.stdout = json.dumps({
            "streams": [{"channels": 1, "duration": "60.0"}]
        })
        
        # VAD 用の ffmpeg モック
        mock_vad = MagicMock()
        mock_vad.stderr = "silence_start: 10.0\nsilence_end: 20.0\n"
        
        def mock_run(cmd, **kwargs):
            if "ffprobe" in cmd[0]:
                return mock_probe
            return mock_vad

        with patch("subtitle_engine.speaker_diarizer.subprocess.run", side_effect=mock_run):
            with patch.object(d, "_get_duration", return_value=60.0):
                # stereo を指定するが、Monoのため VAD にフォールバックする
                result = await d.diarize("/test.mp4", method="stereo")
                
        assert result.method == "vad"

    @pytest.mark.asyncio
    async def test_diarize_pyannote_success(self):
        # pyannote.audio と torch をモック
        mock_pipeline = MagicMock()
        mock_diarization = MagicMock()
        
        class MockTurn:
            def __init__(self, start, end):
                self.start = start
                self.end = end
                
        mock_diarization.itertracks.return_value = [
            (MockTurn(1.0, 5.0), None, "speaker_0"),
            (MockTurn(5.0, 10.0), None, "speaker_1")
        ]
        mock_pipeline.return_value = mock_diarization
        
        mock_pipeline_class = MagicMock()
        mock_pipeline_class.from_pretrained.return_value = mock_pipeline

        import sys
        mock_pyannote = MagicMock()
        mock_pyannote.audio = MagicMock()
        mock_pyannote.audio.Pipeline = mock_pipeline_class
        
        mock_torch = MagicMock()
        mock_torch.cuda = MagicMock()
        mock_torch.cuda.is_available.return_value = True

        with patch.dict(sys.modules, {
            "pyannote": mock_pyannote,
            "pyannote.audio": mock_pyannote.audio,
            "torch": mock_torch
        }):
            d = SpeakerDiarizer()
            d._pyannote_available = True
            
            result = await d._diarize_pyannote("/test.mp4", num_speakers=2)
            
            assert result.method == "pyannote"
            assert result.num_speakers == 2
            assert len(result.segments) == 2
            assert result.segments[0].speaker_id == "speaker_0"
            assert result.segments[1].speaker_id == "speaker_1"

    @pytest.mark.asyncio
    async def test_diarize_pyannote_failure_fallback(self):
        mock_pipeline_class = MagicMock()
        mock_pipeline_class.from_pretrained.side_effect = RuntimeError("GPU error")

        import sys
        mock_pyannote = MagicMock()
        mock_pyannote.audio = MagicMock()
        mock_pyannote.audio.Pipeline = mock_pipeline_class
        
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False

        mock_vad = MagicMock()
        mock_vad.stderr = "silence_start: 10.0\nsilence_end: 20.0\n"

        with patch.dict(sys.modules, {
            "pyannote": mock_pyannote,
            "pyannote.audio": mock_pyannote.audio,
            "torch": mock_torch
        }):
            d = SpeakerDiarizer()
            d._pyannote_available = True
            
            with patch("subtitle_engine.speaker_diarizer.subprocess.run", return_value=mock_vad):
                with patch.object(d, "_get_duration", return_value=60.0):
                    result = await d.diarize("/test.mp4", method="pyannote")
            
            assert result.method == "vad"

    @pytest.mark.asyncio
    async def test_diarize_stereo_failure_fallback(self):
        d = SpeakerDiarizer()
        
        mock_probe = MagicMock()
        mock_probe.stdout = json.dumps({
            "streams": [{"channels": 2, "duration": "60.0"}]
        })
        
        mock_vad_result = MagicMock()
        mock_vad_result.stderr = "silence_start: 10.0\nsilence_end: 20.0\n"
        
        def mock_run_selective(cmd, **kwargs):
            if "ffprobe" in cmd[0]:
                return mock_probe
            elif "ffmpeg" in cmd[0]:
                if "pan=" in cmd[cmd.index("-af") + 1]:
                    raise OSError("stereo ffmpeg failed")
                else:
                    return mock_vad_result
            return MagicMock(stdout="", stderr="")

        with patch("subtitle_engine.speaker_diarizer.subprocess.run", side_effect=mock_run_selective):
            with patch.object(d, "_get_duration", return_value=60.0):
                result = await d.diarize("/test.mp4", method="stereo")
                
        assert result.method == "vad"

    def test_assign_speakers_closest_fallback_idx_less_than_len(self):
        d = SpeakerDiarizer()
        segs = [{"start": 0, "end": 5, "text": "start"}]
        dr = DiarizationResult(
            segments=[
                SpeakerSegment(start=10, end=15, speaker_id="speaker_0", confidence=0.9),
            ],
            num_speakers=1,
        )
        result = d.assign_speakers_to_segments(segs, dr)
        assert result[0]["speaker_id"] == "speaker_0"

    @pytest.mark.asyncio
    async def test_diarize_pyannote_no_cuda_and_no_speakers(self):
        mock_pipeline = MagicMock()
        mock_diarization = MagicMock()
        
        class MockTurn:
            def __init__(self, start, end):
                self.start = start
                self.end = end
                
        mock_diarization.itertracks.return_value = [
            (MockTurn(1.0, 5.0), None, "speaker_0"),
        ]
        mock_pipeline.return_value = mock_diarization
        
        mock_pipeline_class = MagicMock()
        mock_pipeline_class.from_pretrained.return_value = mock_pipeline

        import sys
        mock_pyannote = MagicMock()
        mock_pyannote.audio = MagicMock()
        mock_pyannote.audio.Pipeline = mock_pipeline_class
        
        mock_torch = MagicMock()
        mock_torch.cuda = MagicMock()
        mock_torch.cuda.is_available.return_value = False

        with patch.dict(sys.modules, {
            "pyannote": mock_pyannote,
            "pyannote.audio": mock_pyannote.audio,
            "torch": mock_torch
        }):
            d = SpeakerDiarizer()
            d._pyannote_available = True
            
            result = await d._diarize_pyannote("/test.mp4", num_speakers=None)
            
            assert result.method == "pyannote"
            assert result.num_speakers == 1
            mock_pipeline.assert_called_once_with("/test.mp4")

    @pytest.mark.asyncio
    async def test_diarize_vad_gap_less_than_one(self):
        d = SpeakerDiarizer()
        d._pyannote_available = False
        
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = "silence_start: 5.0\nsilence_end: 5.5\n"
        with patch("subtitle_engine.speaker_diarizer.subprocess.run", return_value=mock_result):
            with patch.object(d, "_get_duration", return_value=10.0):
                result = await d.diarize("/test.mp4", method="vad", num_speakers=2)
                
        assert result.method == "vad"
        assert result.num_speakers == 2
        assert len(result.segments) == 2
        assert result.segments[0].speaker_id == "speaker_0"
        assert result.segments[1].speaker_id == "speaker_0"


# ============================================================
# whisper_subprocess.py テスト
# ============================================================

class TestWhisperSubprocess:

    def test_extract_audio_wav_cached(self, tmp_path):
        """既存WAVが新しい場合は再利用"""
        from subtitle_engine.whisper_subprocess import get_video_hash
        vid = tmp_path / "video.mp4"
        vid.write_bytes(b"fake")
        video_hash = get_video_hash(str(vid))
        import time
        time.sleep(0.05)
        wav = tmp_path / f"_whisper_audio_{video_hash}.wav"
        wav.write_bytes(b"RIFF" + b"\x00" * 100)
        result = extract_audio_wav(str(vid), str(tmp_path))
        assert result.endswith(f"_whisper_audio_{video_hash}.wav")

    def test_extract_audio_wav_ffmpeg_fail(self, tmp_path):
        with patch("subprocess.run", return_value=MagicMock(returncode=1, stderr="error")):
            with pytest.raises(RuntimeError, match="FFmpeg failed"):
                extract_audio_wav(str(tmp_path / "v.mp4"), str(tmp_path))

    def test_split_wav_chunks_short(self, tmp_path):
        """短い音声はチャンク分割不要"""
        with patch("subprocess.run", return_value=MagicMock(stdout="120.0\n")):
            wav = str(tmp_path / "audio.wav")
            result = split_wav_chunks(wav, str(tmp_path), 300)
        assert len(result) == 1
        assert result[0] == (wav, 0.0, 120.0)

    def test_split_wav_chunks_long(self, tmp_path):
        """長い音声はチャンク分割"""
        with patch("subprocess.run", return_value=MagicMock(stdout="600.0\n")):
            for i in range(2):
                chunk = tmp_path / f"_chunk_{i:03d}.wav"
                chunk.write_bytes(b"RIFF" + b"\x00" * 2000)
            result = split_wav_chunks(str(tmp_path / "audio.wav"), str(tmp_path), 300)
        assert len(result) == 2

    def test_transcribe_chunk_success(self):
        model = MagicMock()
        seg1 = MagicMock(start=0.0, end=2.5, text=" こんにちは")
        model.transcribe.return_value = (iter([seg1]), None)
        result = transcribe_chunk(model, "/chunk.wav", 10.0, "ja", 0, 1)
        assert len(result) == 1
        assert result[0]["start"] == 10.0  # offset applied
        assert result[0]["text"] == "こんにちは"

    def test_transcribe_chunk_error(self):
        model = MagicMock()
        model.transcribe.side_effect = Exception("GPU error")
        result = transcribe_chunk(model, "/chunk.wav", 0.0, "ja", 0, 1)
        assert result == []

    def test_transcribe_chunk_timeout(self):
        """transcribe_chunk: モデルが永久にブロック → タイムアウト"""
        import subtitle_engine.whisper_subprocess as ws
        original_timeout = ws.CHUNK_TIMEOUT
        ws.CHUNK_TIMEOUT = 1  # 1秒タイムアウトに短縮

        model = MagicMock()
        import time as _time
        def slow_transcribe(*a, **kw):
            _time.sleep(5)  # タイムアウトより長い
            return (iter([]), None)
        model.transcribe.side_effect = slow_transcribe

        result = transcribe_chunk(model, "/chunk.wav", 0.0, "ja", 0, 1)
        ws.CHUNK_TIMEOUT = original_timeout
        assert result == []

    def test_extract_audio_wav_success(self, tmp_path):
        from subtitle_engine.whisper_subprocess import get_video_hash
        vid = tmp_path / "video.mp4"
        vid.write_bytes(b"fake")
        video_hash = get_video_hash(str(vid))
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            # 実際のWAVファイルを作成してサイズ取得でエラーにならないようにする
            def create_wav(*args, **kwargs):
                wav = tmp_path / f"_whisper_audio_{video_hash}.wav"
                wav.write_bytes(b"RIFF" + bytes([0]) * 1024) # 1KB
                return MagicMock(returncode=0, stderr="")
            mock_run.side_effect = create_wav
            
            result = extract_audio_wav(str(vid), str(tmp_path))
            assert result.endswith(f"_whisper_audio_{video_hash}.wav")
            assert Path(result).exists()

    def test_transcribe_chunk_with_words(self):
        model = MagicMock()
        word_mock = MagicMock()
        word_mock.word = " こんにちは "
        word_mock.start = 0.5
        word_mock.end = 1.5
        
        seg1 = MagicMock(start=0.0, end=2.5, text=" こんにちは")
        seg1.words = [word_mock]
        
        model.transcribe.return_value = (iter([seg1]), None)
        result = transcribe_chunk(model, "/chunk.wav", 10.0, "ja", 0, 1)
        assert len(result) == 1
        assert result[0]["start"] == 10.0
        assert result[0]["text"] == "こんにちは"
        assert len(result[0]["words"]) == 1
        assert result[0]["words"][0]["word"] == "こんにちは"
        assert result[0]["words"][0]["start"] == 10.5
        assert result[0]["words"][0]["end"] == 11.5

    def test_main_usage_error(self):
        from subtitle_engine.whisper_subprocess import main
        with patch("sys.argv", ["whisper_subprocess.py"]):
            with patch("sys.exit", side_effect=SystemExit) as mock_exit:
                with pytest.raises(SystemExit):
                    main()
                mock_exit.assert_called_once_with(1)

    def test_main_success_flow(self, tmp_path):
        from subtitle_engine.whisper_subprocess import main
        video_file = tmp_path / "video.mp4"
        video_file.write_bytes(b"dummy")
        output_jsonl = tmp_path / "output.jsonl"
        
        # path のモック
        original_exists = Path.exists
        def mock_path_exists(self_path):
            if "site-packages/nvidia" in str(self_path) or "cublas/bin" in str(self_path):
                return True
            return original_exists(self_path)
            
        # ctranslate2のモック
        mock_ctranslate = MagicMock()
        mock_ctranslate.get_supported_compute_types.return_value = ["float16"]
        
        with patch("sys.argv", ["whisper_subprocess.py", str(video_file), str(output_jsonl), "small", "ja"]),              patch("os._exit") as mock_exit,              patch("subprocess.run") as mock_run,              patch("faster_whisper.WhisperModel") as mock_model_class,              patch("subtitle_engine.whisper_subprocess.extract_audio_wav") as mock_extract,              patch("subtitle_engine.whisper_subprocess.split_wav_chunks") as mock_split,              patch("subtitle_engine.whisper_subprocess.transcribe_chunk") as mock_transcribe,              patch.dict("sys.modules", {"ctranslate2": mock_ctranslate}),              patch.object(Path, "exists", autospec=True, side_effect=mock_path_exists):
             
            # ffprobeのモック
            mock_run.return_value = MagicMock(returncode=0, stdout="180.0" + chr(10))
            
            dummy_wav = tmp_path / "audio.wav"
            dummy_wav.write_bytes(b"riff")
            mock_extract.return_value = str(dummy_wav)
            
            # チャンクを2つ返す（WAVファイル削除、進捗率ログなどもカバーする）
            dummy_chunk1 = tmp_path / "_chunk_000.wav"
            dummy_chunk1.write_bytes(b"chunk1")
            dummy_chunk2 = tmp_path / "_chunk_001.wav"
            dummy_chunk2.write_bytes(b"chunk2")
            
            mock_split.return_value = [
                (str(dummy_chunk1), 0.0, 90.0),
                (str(dummy_chunk2), 90.0, 180.0)
            ]
            
            # 1つ目は成功、2つ目はスキップ(空リストを返す)
            mock_transcribe.side_effect = [
                [{"start": 1.0, "end": 2.5, "text": "テスト", "sourceStart": 1.0, "sourceEnd": 2.5, "words": []}],
                []
            ]
            
            mock_model = MagicMock()
            mock_model_class.return_value = mock_model
            
            # スレッドjoinのモック（is_aliveがTrueを返すようにしてGPUタイムアウトCPUフォールバックをカバー）
            with patch("threading.Thread.is_alive", return_value=True):
                main()
            
            mock_exit.assert_called_once_with(0)
            
            # 結果がファイルに書かれたか確認
            assert output_jsonl.exists()
            content = output_jsonl.read_text(encoding="utf-8").strip()
            lines = content.splitlines()
            assert len(lines) == 1
            data = json.loads(lines[0])
            assert data["text"] == "テスト"
            assert data["start"] == 1.0

    def test_main_model_load_exception_fallback(self, tmp_path):
        from subtitle_engine.whisper_subprocess import main
        video_file = tmp_path / "video.mp4"
        video_file.write_bytes(b"dummy")
        output_jsonl = tmp_path / "output.jsonl"
        
        # WhisperModel の1回目のロードで例外、2回目(CPU)で成功するよう設定
        mock_model = MagicMock()
        
        def mock_model_init(*args, **kwargs):
            if kwargs.get("device") == "cuda":
                raise ValueError("GPU Load Err")
            return mock_model
            
        with patch("sys.argv", ["whisper_subprocess.py", str(video_file), str(output_jsonl)]),              patch("os._exit") as mock_exit,              patch("subprocess.run") as mock_run,              patch("faster_whisper.WhisperModel", side_effect=mock_model_init),              patch("subtitle_engine.whisper_subprocess.extract_audio_wav") as mock_extract,              patch("subtitle_engine.whisper_subprocess.split_wav_chunks") as mock_split,              patch("subtitle_engine.whisper_subprocess.transcribe_chunk") as mock_transcribe:
             
            mock_run.return_value = MagicMock(returncode=0, stdout="180.0" + chr(10))
            mock_extract.return_value = str(tmp_path / "audio.wav")
            mock_split.return_value = [("/chunk.wav", 0.0, 180.0)]
            mock_transcribe.return_value = []
            
            # CUDA サポートをモック
            mock_ctranslate = MagicMock()
            mock_ctranslate.get_supported_compute_types.return_value = ["float16"]
            
            with patch.dict("sys.modules", {"ctranslate2": mock_ctranslate}):
                main()
                
            mock_exit.assert_called_once_with(0)

    def test_main_exception_flow(self, tmp_path):
        from subtitle_engine.whisper_subprocess import main
        video_file = tmp_path / "video.mp4"
        video_file.write_bytes(b"dummy")
        output_jsonl = tmp_path / "output.jsonl"
        
        # ctranslate2のインポートで例外が発生する（CPU fallback）
        with patch("sys.argv", ["whisper_subprocess.py", str(video_file), str(output_jsonl)]),              patch("os._exit") as mock_exit,              patch("subprocess.run") as mock_run,              patch("faster_whisper.WhisperModel") as mock_model_class,              patch("subtitle_engine.whisper_subprocess.extract_audio_wav") as mock_extract,              patch("subtitle_engine.whisper_subprocess.split_wav_chunks") as mock_split,              patch("subtitle_engine.whisper_subprocess.transcribe_chunk") as mock_transcribe,              patch.dict("sys.modules", {"ctranslate2": None}):
             
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            
            dummy_wav = tmp_path / "audio.wav"
            dummy_wav.write_bytes(b"riff")
            mock_extract.return_value = str(dummy_wav)
            
            mock_split.return_value = [
                (str(dummy_wav), 0.0, 180.0)
            ]
            mock_transcribe.return_value = []
            
            main()
            
            mock_exit.assert_called_once_with(0)
            
    def test_main_top_level_exception_flow(self, tmp_path):
        from subtitle_engine.whisper_subprocess import main
        video_file = tmp_path / "video.mp4"
        video_file.write_bytes(b"dummy")
        output_jsonl = tmp_path / "output.jsonl"
        
        # extract_audio_wav が例外を投げるようにして、例外ハンドラに入ることを検証
        with patch("sys.argv", ["whisper_subprocess.py", str(video_file), str(output_jsonl)]),              patch("os._exit") as mock_exit,              patch("subprocess.run") as mock_run,              patch("subtitle_engine.whisper_subprocess.extract_audio_wav", side_effect=ValueError("Test Exception")):
             
            mock_run.return_value = MagicMock(returncode=0, stdout="180.0" + chr(10))
            
            main()
            
            mock_exit.assert_called_once_with(1)

    def test_get_video_hash_fallback(self):
        from subtitle_engine.whisper_subprocess import get_video_hash
        with patch("os.path.abspath", side_effect=ValueError("mock path error")):
            h = get_video_hash("dummy_video.mp4")
            assert len(h) == 12

    def test_get_video_hash_path_object(self, tmp_path):
        from subtitle_engine.whisper_subprocess import get_video_hash
        vid_path = tmp_path / "dummy_path.mp4"
        h = get_video_hash(vid_path)
        assert len(h) == 12

    def test_main_unlink_oserror_handling(self, tmp_path):
        """WAV/チャンク削除で OSError が起きてもクラッシュしないこと"""
        from subtitle_engine.whisper_subprocess import main
        video_file = tmp_path / "video.mp4"
        video_file.write_bytes(b"dummy")
        output_jsonl = tmp_path / "output.jsonl"
        
        with patch("sys.argv", ["whisper_subprocess.py", str(video_file), str(output_jsonl)]), \
             patch("os._exit") as mock_exit, \
             patch("subprocess.run") as mock_run, \
             patch("faster_whisper.WhisperModel") as mock_model_class, \
             patch("subtitle_engine.whisper_subprocess.extract_audio_wav") as mock_extract, \
             patch("subtitle_engine.whisper_subprocess.split_wav_chunks") as mock_split, \
             patch("subtitle_engine.whisper_subprocess.transcribe_chunk") as mock_transcribe, \
             patch.object(Path, "unlink", side_effect=OSError("Permission denied")):
             
            mock_run.return_value = MagicMock(returncode=0, stdout="180.0\n")
            dummy_wav = tmp_path / "audio.wav"
            dummy_wav.write_bytes(b"riff")
            mock_extract.return_value = str(dummy_wav)
            
            dummy_chunk = tmp_path / "_chunk_000.wav"
            dummy_chunk.write_bytes(b"chunk")
            mock_split.return_value = [(str(dummy_chunk), 0.0, 180.0)]
            mock_transcribe.return_value = [{"start": 1.0, "end": 2.5, "text": "テスト", "sourceStart": 1.0, "sourceEnd": 2.5, "words": []}]
            
            main()
            mock_exit.assert_called_once_with(0)

    def test_main_gpu_load_timeout_thread_safety(self, tmp_path):
        """GPUロードがタイムアウトした際、スレッド遅延完了によりmodel変数が上書きされないことを検証"""
        from subtitle_engine.whisper_subprocess import main
        import time as _time
        import threading
        from unittest.mock import MagicMock, patch

        video_file = tmp_path / "video.mp4"
        video_file.write_bytes(b"dummy")
        output_jsonl = tmp_path / "output.jsonl"

        cpu_model = MagicMock()
        cuda_model = MagicMock()

        # sys.argv の設定
        with patch("sys.argv", ["whisper_subprocess.py", str(video_file), str(output_jsonl)]), \
             patch("os._exit") as mock_exit, \
             patch("subprocess.run") as mock_run, \
             patch("faster_whisper.WhisperModel") as mock_whisper_model, \
             patch("subtitle_engine.whisper_subprocess.extract_audio_wav") as mock_extract, \
             patch("subtitle_engine.whisper_subprocess.split_wav_chunks") as mock_split, \
             patch("subtitle_engine.whisper_subprocess.transcribe_chunk") as mock_transcribe, \
             patch("threading.Thread.join") as mock_join:

            mock_run.return_value = MagicMock(returncode=0, stdout="180.0\n")
            mock_extract.return_value = str(tmp_path / "audio.wav")
            # 2つのチャンクを用意する
            mock_split.return_value = [
                ("/chunk1.wav", 0.0, 90.0),
                ("/chunk2.wav", 90.0, 180.0)
            ]
            
            # 1番目のチャンク処理時にはスレッドが完了するように少し待機を入れる
            def mock_transcribe_chunk(model_arg, chunk_path, offset, language, chunk_idx, total_chunks):
                if chunk_idx == 0:
                    _time.sleep(0.2)  # cudaスレッドが確実に完了して上書きするのを待つ
                return [{"start": 1.0, "end": 2.0, "text": "test"}]
                
            mock_transcribe.side_effect = mock_transcribe_chunk

            # Thread.join が即座に戻るようにする（タイムアウト模擬）
            mock_join.return_value = None

            # WhisperModelが呼ばれたときの動作
            # 1回目 (cuda): 遅延スレッドから呼ばれる。cuda_modelを返す（がスレッドの中）
            # 2回目 (cpu): メインスレッドから呼ばれる。cpu_modelを返す
            def mock_model_init(model_size, device, compute_type):
                if device == "cuda":
                    _time.sleep(0.05) # join後にスレッドが完了するように少し待つ
                    return cuda_model
                return cpu_model

            mock_whisper_model.side_effect = mock_model_init

            # CUDAを有効にする
            mock_ctranslate = MagicMock()
            mock_ctranslate.get_supported_compute_types.return_value = ["float16"]

            with patch.dict("sys.modules", {"ctranslate2": mock_ctranslate}):
                main()

            mock_exit.assert_called_once_with(0)

            # transcribe_chunk に渡されたモデルが両方とも cpu_model であることを確認する
            # もしスレッド競合バグがあれば、2回目の呼び出しで model_arg は cuda_model になってしまっている
            assert mock_transcribe.call_count == 2
            
            first_call_model = mock_transcribe.call_args_list[0][0][0]
            second_call_model = mock_transcribe.call_args_list[1][0][0]
            
            assert first_call_model == cpu_model
            assert second_call_model == cpu_model
            assert second_call_model != cuda_model



# ============================================================
# video_hash.py テスト
# ============================================================

class TestVideoHash:

    def test_compute_video_hash_success(self, tmp_path):
        dummy_file = tmp_path / "dummy_video.mp4"
        dummy_file.write_bytes(b"hello world video content")
        
        h = compute_video_hash(str(dummy_file))
        assert len(h) == 8
        assert h == "ffe49e2f"
        
        h_long = compute_video_hash(str(dummy_file), length=16)
        assert len(h_long) == 16
        assert h_long == "ffe49e2fbe11f970"

    def test_compute_video_hash_file_not_found(self):
        with pytest.raises(FileNotFoundError, match="動画ファイルが見つかりません"):
            compute_video_hash("non_existent_file.mp4")

    def test_get_checkpoint_path(self, tmp_path):
        dummy_file = tmp_path / "dummy_video.mp4"
        dummy_file.write_bytes(b"hello world video content")
        
        expected_path = str(tmp_path / "_whisper_ffe49e2f.jsonl")
        assert get_checkpoint_path(str(dummy_file)) == expected_path

    def test_old_checkpoint_name(self):
        assert OLD_CHECKPOINT_NAME == "_whisper_segments.jsonl"

    def test_compute_video_hash_path_object(self, tmp_path):
        dummy_file = tmp_path / "dummy_video_path.mp4"
        dummy_file.write_bytes(b"path object content")
        
        # pathlib.Path を直接渡す
        h = compute_video_hash(dummy_file)
        assert len(h) == 8
        
        # get_checkpoint_path も pathlib.Path を渡す
        expected_path = str(tmp_path / f"_whisper_{h}.jsonl")
        assert get_checkpoint_path(dummy_file) == expected_path

    def test_compute_video_hash_is_directory(self, tmp_path):
        # tmp_path はディレクトリ
        with pytest.raises(ValueError, match="指定されたパスはファイルではありません"):
            compute_video_hash(tmp_path)

    def test_compute_video_hash_invalid_length(self, tmp_path):
        dummy_file = tmp_path / "dummy_len.mp4"
        dummy_file.write_bytes(b"some content")
        
        with pytest.raises(ValueError, match="ハッシュの長さは正の整数でなければなりません"):
            compute_video_hash(dummy_file, length=0)
            
        with pytest.raises(ValueError, match="ハッシュの長さは正の整数でなければなりません"):
            compute_video_hash(dummy_file, length=-5)

    def test_compute_video_hash_extreme_length(self, tmp_path):
        dummy_file = tmp_path / "dummy_len.mp4"
        dummy_file.write_bytes(b"some content")
        
        # SHA256の16進数文字数は64文字なので、それ以上を指定しても64文字で制限される
        h = compute_video_hash(dummy_file, length=100)
        assert len(h) == 64


# ============================================================
# formatter.py テスト
# ============================================================

class TestSubtitleFormatter:

    def test_to_vtt(self):
        subtitles = [
            {"start": 1.23, "end": 4.56, "text": "Hello World"},
            {"start": 3605.12, "end": 3610.99, "text": "One hour later"}
        ]
        vtt_output = SubtitleFormatter.to_vtt(subtitles)
        assert "WEBVTT" in vtt_output
        assert "1\n00:00:01.230 --> 00:00:04.560\nHello World" in vtt_output
        assert "2\n01:00:05.120 --> 01:00:10.990\nOne hour later" in vtt_output

    def test_to_srt(self):
        subtitles = [
            {"start": 1.23, "end": 4.56, "text": "Hello World"},
            {"start": 3605.12, "end": 3610.99, "text": "One hour later"}
        ]
        srt_output = SubtitleFormatter.to_srt(subtitles)
        assert "1\n00:00:01,230 --> 00:00:04,560\nHello World" in srt_output
        assert "2\n01:00:05,120 --> 01:00:10,990\nOne hour later" in srt_output

    def test_format_time_vtt_edge_cases(self):
        assert SubtitleFormatter._format_time_vtt(0.0) == "00:00:00.000"
        assert SubtitleFormatter._format_time_vtt(59.999) == "00:00:59.999"
        assert SubtitleFormatter._format_time_vtt(60.0) == "00:01:00.000"

    def test_empty_subtitles(self):
        assert SubtitleFormatter.to_vtt([]) == "WEBVTT\n\n"
        assert SubtitleFormatter.to_srt([]) == ""

    def test_format_time_large_values(self):
        assert SubtitleFormatter._format_time_vtt(360000.0) == "100:00:00.000"
        assert SubtitleFormatter._format_time_srt(360000.0) == "100:00:00,000"

    def test_missing_keys_raises_key_error(self):
        subtitles = [{"start": 1.0, "end": 2.0}]
        with pytest.raises(KeyError):
            SubtitleFormatter.to_vtt(subtitles)
        with pytest.raises(KeyError):
            SubtitleFormatter.to_srt(subtitles)
