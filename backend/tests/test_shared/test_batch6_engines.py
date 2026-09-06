"""
Batch 6: video_processor / whisper_subprocess / subtitle_normalizer / telop_proposal_engine / thumbnail_engine

対象:
  1. video_processor.py              — 15テスト
  2. subtitle_engine/whisper_subprocess.py — 10テスト
  3. subtitle_normalizer.py          — 10テスト
  4. telop_proposal_engine.py        — 10テスト
  5. thumbnail_engine/generator.py   — 7テスト

合計: 52テスト
"""
import sys, os, json, time, pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from dataclasses import asdict

_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)


# ============================================================
# 1. VideoProcessor (15テスト)
# ============================================================

class TestVideoProcessorInit:
    def test_vp_01_default_output_dir(self, tmp_path):
        from video_processor import VideoProcessor
        vp = VideoProcessor(output_dir=str(tmp_path / "out"))
        assert vp.output_dir.exists()

    def test_vp_02_mood_settings_elegant(self):
        from video_processor import VideoProcessor
        vp = VideoProcessor(output_dir="test_tmp_vp")
        s = vp.get_mood_settings("elegant")
        assert s.name == "エレガント"
        assert s.color_preset == "warm"

    def test_vp_03_mood_settings_dynamic(self):
        from video_processor import VideoProcessor
        vp = VideoProcessor(output_dir="test_tmp_vp")
        s = vp.get_mood_settings("dynamic")
        assert s.name == "ダイナミック"

    def test_vp_04_mood_settings_fallback(self):
        from video_processor import VideoProcessor
        vp = VideoProcessor(output_dir="test_tmp_vp")
        s = vp.get_mood_settings("unknown_mood")
        assert s.name == "エレガント"  # fallback

    def test_vp_05_create_task(self, tmp_path):
        from video_processor import VideoProcessor, ProcessingPhase
        vp = VideoProcessor(output_dir=str(tmp_path))
        task = vp.create_task("t1", ["/a.mp4"], "elegant")
        assert task.task_id == "t1"
        assert task.phase == ProcessingPhase.IDLE
        assert "t1" in vp.tasks

    def test_vp_06_get_task(self, tmp_path):
        from video_processor import VideoProcessor
        vp = VideoProcessor(output_dir=str(tmp_path))
        vp.create_task("t2", ["/a.mp4"], "dynamic")
        assert vp.get_task("t2") is not None
        assert vp.get_task("nonexistent") is None

    def test_vp_07_set_progress_callback(self, tmp_path):
        from video_processor import VideoProcessor
        vp = VideoProcessor(output_dir=str(tmp_path))
        cb = MagicMock()
        vp.set_progress_callback(cb)
        assert vp._progress_callback is cb

    def test_vp_08_notify_progress(self, tmp_path):
        from video_processor import VideoProcessor
        vp = VideoProcessor(output_dir=str(tmp_path))
        cb = MagicMock()
        vp.set_progress_callback(cb)
        task = vp.create_task("t3", [], "elegant")
        vp._notify_progress(task)
        cb.assert_called_once_with(task)

    def test_vp_09_color_filter_warm(self, tmp_path):
        from video_processor import VideoProcessor, MOOD_SETTINGS
        vp = VideoProcessor(output_dir=str(tmp_path))
        f = vp._get_color_filter(MOOD_SETTINGS["elegant"])
        assert "colorbalance" in f

    def test_vp_10_color_filter_vibrant(self, tmp_path):
        from video_processor import VideoProcessor, MOOD_SETTINGS
        vp = VideoProcessor(output_dir=str(tmp_path))
        f = vp._get_color_filter(MOOD_SETTINGS["dynamic"])
        assert "saturation" in f

    def test_vp_11_color_filter_cinematic(self, tmp_path):
        from video_processor import VideoProcessor, MOOD_SETTINGS
        vp = VideoProcessor(output_dir=str(tmp_path))
        f = vp._get_color_filter(MOOD_SETTINGS["dramatic"])
        assert "contrast" in f

    def test_vp_12_process_video_no_task(self, tmp_path):
        from video_processor import VideoProcessor
        vp = VideoProcessor(output_dir=str(tmp_path))
        assert vp.process_video("nonexistent") is False

    def test_vp_13_run_ffmpeg_timeout(self, tmp_path, safe_popen_mock):
        from video_processor import VideoProcessor
        vp = VideoProcessor(output_dir=str(tmp_path))
        proc = safe_popen_mock(returncode=0)
        with patch("video_processor.subprocess.Popen", return_value=proc):
            result = vp._run_ffmpeg(["ffmpeg", "-version"], "test")
            assert result is True

    def test_vp_14_run_ffmpeg_failure(self, tmp_path, safe_popen_mock):
        from video_processor import VideoProcessor
        vp = VideoProcessor(output_dir=str(tmp_path))
        proc = safe_popen_mock(returncode=1, stderr_text="error")
        with patch("video_processor.subprocess.Popen", return_value=proc):
            result = vp._run_ffmpeg(["ffmpeg"], "fail-test")
            assert result is False

    def test_vp_15_audio_normalize_args_no_template(self, tmp_path):
        from video_processor import VideoProcessor
        vp = VideoProcessor(output_dir=str(tmp_path))
        with patch.dict("sys.modules", {"template_config": None}):
            args = vp._get_audio_normalize_args("/fake.mp4")
            assert args == []


# ============================================================
# 2. Whisper Subprocess (10テスト)
# ============================================================

class TestWhisperSubprocess:
    def test_ws_01_extract_audio_wav_cached(self, tmp_path):
        """WAVがvideoより新しい → 再利用"""
        from subtitle_engine.whisper_subprocess import extract_audio_wav, get_video_hash
        video = tmp_path / "test.mp4"
        video.write_bytes(b"\x00" * 50)
        import time; time.sleep(0.05)  # ensure wav is newer
        video_hash = get_video_hash(str(video))
        wav = tmp_path / f"_whisper_audio_{video_hash}.wav"
        wav.write_bytes(b"\x00" * 100)
        result = extract_audio_wav(str(video), str(tmp_path))
        assert result == str(wav)

    def test_ws_02_extract_audio_wav_ffmpeg(self, tmp_path):
        from subtitle_engine.whisper_subprocess import extract_audio_wav, get_video_hash
        video = tmp_path / "test.mp4"
        video.write_bytes(b"\x00" * 50)
        video_hash = get_video_hash(str(video))
        wav_path = tmp_path / f"_whisper_audio_{video_hash}.wav"
        mock_result = MagicMock(returncode=0)
        def fake_run(*a, **kw):
            wav_path.write_bytes(b"\x00" * 1000)
            return mock_result
        with patch("subprocess.run", side_effect=fake_run):
            result = extract_audio_wav(str(video), str(tmp_path))
            assert f"_whisper_audio_{video_hash}.wav" in result

    def test_ws_03_extract_audio_wav_fail(self, tmp_path):
        from subtitle_engine.whisper_subprocess import extract_audio_wav
        video = tmp_path / "test.mp4"
        video.write_bytes(b"\x00" * 50)
        mock_result = MagicMock(returncode=1, stderr="error msg")
        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="FFmpeg failed"):
                extract_audio_wav(str(video), str(tmp_path))

    def test_ws_04_split_wav_short(self, tmp_path):
        from subtitle_engine.whisper_subprocess import split_wav_chunks
        wav = tmp_path / "short.wav"
        wav.write_bytes(b"\x00" * 100)
        mock_r = MagicMock(stdout="120.0\n")
        with patch("subprocess.run", return_value=mock_r):
            chunks = split_wav_chunks(str(wav), str(tmp_path), chunk_sec=300)
            assert len(chunks) == 1
            assert chunks[0][0] == str(wav)

    def test_ws_05_split_wav_multiple(self, tmp_path):
        from subtitle_engine.whisper_subprocess import split_wav_chunks
        wav = tmp_path / "long.wav"
        wav.write_bytes(b"\x00" * 100)
        call_count = [0]
        def mock_run(*args, **kwargs):
            call_count[0] += 1
            r = MagicMock(returncode=0, stdout="600.0\n")
            if call_count[0] == 1:
                return r  # ffprobe
            cmd = args[0] if args else kwargs.get("args", [])
            for c in cmd:
                if str(c).endswith(".wav") and "_chunk_" in str(c):
                    Path(c).write_bytes(b"\x00" * 2000)
            return MagicMock(returncode=0)
        with patch("subprocess.run", side_effect=mock_run):
            chunks = split_wav_chunks(str(wav), str(tmp_path), chunk_sec=300)
            assert len(chunks) == 2

    def test_ws_06_transcribe_chunk_success(self):
        from subtitle_engine.whisper_subprocess import transcribe_chunk
        mock_model = MagicMock()
        seg1 = MagicMock(start=0.0, end=5.0, text="テスト")
        mock_model.transcribe.return_value = (iter([seg1]), None)
        result = transcribe_chunk(mock_model, "/fake.wav", 10.0, "ja", 0, 1)
        assert len(result) == 1
        assert result[0]["start"] == 10.0
        assert result[0]["text"] == "テスト"

    def test_ws_07_transcribe_chunk_error(self):
        from subtitle_engine.whisper_subprocess import transcribe_chunk
        mock_model = MagicMock()
        mock_model.transcribe.side_effect = RuntimeError("GPU error")
        result = transcribe_chunk(mock_model, "/fake.wav", 0.0, "ja", 0, 1)
        assert result == []

    def test_ws_08_chunk_constants(self):
        from subtitle_engine.whisper_subprocess import CHUNK_DURATION, CHUNK_TIMEOUT
        assert CHUNK_DURATION == 300
        assert CHUNK_TIMEOUT == 180

    def test_ws_09_split_wav_empty_duration(self, tmp_path):
        from subtitle_engine.whisper_subprocess import split_wav_chunks
        wav = tmp_path / "empty.wav"
        wav.write_bytes(b"\x00" * 10)
        mock_r = MagicMock(stdout="")
        with patch("subprocess.run", return_value=mock_r):
            chunks = split_wav_chunks(str(wav), str(tmp_path), chunk_sec=300)
            assert len(chunks) == 1

    def test_ws_10_transcribe_chunk_offset_applied(self):
        from subtitle_engine.whisper_subprocess import transcribe_chunk
        mock_model = MagicMock()
        seg = MagicMock(start=1.0, end=3.0, text="hello")
        mock_model.transcribe.return_value = (iter([seg]), None)
        result = transcribe_chunk(mock_model, "/f.wav", 100.0, "ja", 0, 1)
        assert result[0]["start"] == 101.0
        assert result[0]["end"] == 103.0

    def test_ws_11_transcribe_chunk_value_error(self):
        from subtitle_engine.whisper_subprocess import transcribe_chunk
        mock_model = MagicMock()
        mock_model.transcribe.side_effect = ValueError("Invalid value test")
        result = transcribe_chunk(mock_model, "/fake.wav", 0.0, "ja", 0, 1)
        assert result == []


# ============================================================
# 3. SubtitleNormalizer (10テスト)
# ============================================================

class TestSubtitleNormalizer:
    def _mock_deps(self):
        """gemini_client + proper_noun_dict のモック"""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = '{"normalized_segments": [{"id": "seg_000", "text": "テスト"}], "uncertain_items": []}'
        mock_client.models.generate_content.return_value = mock_resp
        return mock_client

    def test_sn_01_parse_response_valid(self):
        from subtitle_normalizer import SubtitleNormalizer
        sn = SubtitleNormalizer.__new__(SubtitleNormalizer)
        result = sn._parse_response('{"normalized_segments": [{"id": "s1", "text": "ok"}], "uncertain_items": []}')
        assert len(result["normalized_segments"]) == 1

    def test_sn_02_parse_response_invalid(self):
        from subtitle_normalizer import SubtitleNormalizer
        sn = SubtitleNormalizer.__new__(SubtitleNormalizer)
        result = sn._parse_response("not json at all")
        assert result["normalized_segments"] == []

    def test_sn_03_fallback_normalize(self):
        from subtitle_normalizer import SubtitleNormalizer
        sn = SubtitleNormalizer.__new__(SubtitleNormalizer)
        segs = [{"id": "seg_000", "text": "テストテキスト"}]
        result = sn._fallback_normalize(segs)
        assert len(result["normalized_segments"]) == 1
        assert result["normalized_segments"][0]["id"] == "seg_000"

    def test_sn_04_apply_dictionary(self):
        from subtitle_normalizer import SubtitleNormalizer
        sn = SubtitleNormalizer.__new__(SubtitleNormalizer)
        result = {"normalized_segments": [{"id": "s1", "text": "テスト"}], "uncertain_items": []}
        original = [{"id": "s1", "text": "テスト"}]
        updated = sn._apply_dictionary(result, original)
        assert "normalized_segments" in updated

    def test_sn_05_srt_exporter_format_timestamp(self):
        from subtitle_normalizer import SRTExporter
        assert SRTExporter.format_timestamp(0.0) == "00:00:00,000"
        assert SRTExporter.format_timestamp(65.5) == "00:01:05,500"
        assert SRTExporter.format_timestamp(3661.123) == "01:01:01,123"

    def test_sn_06_srt_export(self, tmp_path):
        from subtitle_normalizer import SRTExporter
        segs = [{"start": 0, "end": 5, "text": "こんにちは"}]
        out = tmp_path / "test.srt"
        SRTExporter.export(segs, out)
        content = out.read_text(encoding="utf-8")
        assert "こんにちは" in content
        assert "00:00:00,000" in content

    def test_sn_07_vtt_export(self, tmp_path):
        from subtitle_normalizer import SRTExporter
        segs = [{"start": 1.5, "end": 4.2, "text": "テスト"}]
        out = tmp_path / "test.vtt"
        SRTExporter.export_vtt(segs, out)
        content = out.read_text(encoding="utf-8")
        assert "WEBVTT" in content
        assert "テスト" in content

    def test_sn_08_normalize_segments_dataclass(self):
        from subtitle_normalizer import NormalizedSegment
        ns = NormalizedSegment(id="s1", start=0, end=5, original_text="a", normalized_text="b", corrections=[])
        assert ns.confidence == 1.0

    def test_sn_09_uncertain_item_dataclass(self):
        from subtitle_normalizer import UncertainItem
        ui = UncertainItem(original="test", candidates=["a", "b"], context="ctx", segment_id="s1", confidence=0.5)
        assert ui.confidence == 0.5

    def test_sn_10_export_srt_convenience(self, tmp_path):
        from subtitle_normalizer import export_srt
        segs = [{"start": 0, "end": 3, "text": "hello"}]
        out = tmp_path / "conv.srt"
        result = export_srt(segs, out)
        assert result == out

    def test_sn_11_normalize_success(self):
        from subtitle_normalizer import SubtitleNormalizer
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = '{"normalized_segments": [{"id": "seg_000", "text": "テスト"}], "uncertain_items": []}'
        mock_client.models.generate_content.return_value = mock_resp

        with patch("subtitle_normalizer.get_gemini_client", return_value=mock_client), \
             patch("subtitle_normalizer.get_model", return_value="test-model"):
            sn = SubtitleNormalizer()
            with patch("subtitle_normalizer.proper_noun_dict.get_all_entries", return_value=[]):
                segs = [{"id": "seg_000", "text": "テスト"}]
                result = sn.normalize(segs, apply_dict=True)
                assert len(result["normalized_segments"]) == 1
                assert result["stats"]["total_segments"] == 1
                assert result["stats"]["normalized_segments"] == 1

                result_no_dict = sn.normalize(segs, apply_dict=False)
                assert len(result_no_dict["normalized_segments"]) == 1

    def test_sn_12_normalize_api_error_fallback(self):
        from subtitle_normalizer import SubtitleNormalizer
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("API error")

        with patch("subtitle_normalizer.get_gemini_client", return_value=mock_client), \
             patch("subtitle_normalizer.get_model", return_value="test-model"):
            sn = SubtitleNormalizer()
            segs = [{"id": "seg_000", "text": "テスト"}]
            result = sn.normalize(segs)
            assert len(result["normalized_segments"]) == 1
            assert result["normalized_segments"][0]["text"] == "テスト"

    def test_sn_13_parse_response_json_decode_error(self):
        from subtitle_normalizer import SubtitleNormalizer
        sn = SubtitleNormalizer.__new__(SubtitleNormalizer)
        result = sn._parse_response('{"normalized_segments": {invalid_json}}')
        assert result == {"normalized_segments": [], "uncertain_items": []}

    def test_sn_14_normalize_subtitles_convenience(self):
        import subtitle_normalizer
        from subtitle_normalizer import normalize_subtitles
        segs = [{"id": "seg_000", "text": "テスト"}]
        mock_normalize = MagicMock(return_value={"normalized_segments": []})
        with patch.object(subtitle_normalizer.subtitle_normalizer, "normalize", mock_normalize):
            result = normalize_subtitles(segs)
            mock_normalize.assert_called_once_with(segs)
            assert result == {"normalized_segments": []}


# ============================================================
# 4. TelopProposalEngine (10テスト)
# ============================================================

class TestTelopProposalEngine:
    def test_tp_01_telop_candidate_dataclass(self):
        from telop_proposal_engine import TelopCandidate
        tc = TelopCandidate(id="t1", segment_id="s1", start=0, end=5, original_text="a", telop_text="b", importance=0.9)
        assert tc.style_suggestion == "default"
        assert tc.position_suggestion == "bottom_center"

    def test_tp_02_scene_proposal_dataclass(self):
        from telop_proposal_engine import SceneProposal
        sp = SceneProposal(id="sc1", name="Opening", start_time=0, end_time=60, duration_sec=60, telop_count=3)
        assert sp.mood == "neutral"

    def test_tp_03_fallback_extract(self):
        from telop_proposal_engine import TelopProposalEngine
        engine = TelopProposalEngine.__new__(TelopProposalEngine)
        segs = [
            {"id": "s1", "text": "これは大切なポイントです", "start": 0, "end": 5},
            {"id": "s2", "text": "普通の文章", "start": 5, "end": 10},
        ]
        candidates = engine._fallback_extract(segs)
        assert len(candidates) >= 1
        assert candidates[0].telop_text  # keyword match

    def test_tp_04_fallback_extract_no_match(self):
        from telop_proposal_engine import TelopProposalEngine
        engine = TelopProposalEngine.__new__(TelopProposalEngine)
        segs = [{"id": "s1", "text": "特に何もないテキスト", "start": 0, "end": 5}]
        candidates = engine._fallback_extract(segs)
        assert len(candidates) == 0

    def test_tp_05_fallback_scene_proposal(self):
        from telop_proposal_engine import TelopProposalEngine
        engine = TelopProposalEngine.__new__(TelopProposalEngine)
        segs = [{"id": f"s{i}", "text": f"text{i}", "start": i*10, "end": (i+1)*10} for i in range(100)]
        proposals = engine._fallback_scene_proposal(segs)
        assert len(proposals) >= 2

    def test_tp_06_parse_telop_response_valid(self):
        from telop_proposal_engine import TelopProposalEngine
        engine = TelopProposalEngine.__new__(TelopProposalEngine)
        segs = [{"id": "s1", "text": "test", "start": 0, "end": 5}]
        resp = '{"telop_candidates": [{"segment_id": "s1", "telop_text": "重要", "importance": 0.9}]}'
        candidates = engine._parse_telop_response(resp, segs)
        assert len(candidates) == 1

    def test_tp_07_parse_telop_response_invalid(self):
        from telop_proposal_engine import TelopProposalEngine
        engine = TelopProposalEngine.__new__(TelopProposalEngine)
        segs = [{"id": "s1", "text": "test", "start": 0, "end": 5}]
        candidates = engine._parse_telop_response("not json", segs)
        assert isinstance(candidates, list)

    def test_tp_08_parse_scene_response_valid(self):
        from telop_proposal_engine import TelopProposalEngine
        engine = TelopProposalEngine.__new__(TelopProposalEngine)
        segs = [{"id": "s1", "start": 0, "end": 60}, {"id": "s5", "start": 60, "end": 120}]
        resp = '{"scenes": [{"name": "Opening", "start_seg": "s1", "end_seg": "s5", "summary": "intro", "mood": "warm", "suggested_telops": 2}]}'
        proposals = engine._parse_scene_response(resp, segs)
        assert len(proposals) == 1
        assert proposals[0].name == "Opening"

    def test_tp_09_generate_proposal_report(self):
        from telop_proposal_engine import TelopProposalEngine, TelopCandidate, SceneProposal
        engine = TelopProposalEngine.__new__(TelopProposalEngine)
        tc = [TelopCandidate(id="t1", segment_id="s1", start=0, end=5, original_text="a", telop_text="b", importance=0.8)]
        sp = [SceneProposal(id="sc1", name="P1", start_time=0, end_time=60, duration_sec=60, telop_count=1)]
        report = engine.generate_proposal_report(tc, sp)
        assert report["summary"]["total_telops"] == 1
        assert report["summary"]["total_scenes"] == 1

    def test_tp_10_convenience_functions(self):
        from telop_proposal_engine import extract_telops, propose_scenes
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = '{"telop_candidates": []}'
        mock_client.models.generate_content.return_value = mock_resp
        with patch("telop_proposal_engine.get_gemini_client", return_value=mock_client):
            segs = [{"id": "s1", "text": "テスト", "start": 0, "end": 5}]
            # extract_telops uses singleton, so we patch it
            from telop_proposal_engine import telop_engine
            telop_engine.client = mock_client
            result = extract_telops(segs)
            assert isinstance(result, list)


# ============================================================
# 5. ThumbnailGenerator (7テスト)
# ============================================================

class TestThumbnailGenerator:
    def test_tg_00_model_registry_import_error(self):
        import importlib
        import sys
        import thumbnail_engine.generator
        generator_module = sys.modules["thumbnail_engine.generator"]
        
        with patch.dict("sys.modules", {"model_registry": None}):
            importlib.reload(generator_module)
            
            # **直書きの既定値に逃げない**（R1.5-C6）。2026-08-28 まで
            # gemini-2.5-flash を直書きしており、2026-10-16 に提供終了する
            from model_policy import resolve
            assert generator_module.get_model("test") == resolve("test").model
            assert not generator_module.get_model("test").startswith("gemini-2.5")
            
        importlib.reload(generator_module)

    def test_tg_00_no_api_key_warning(self):
        from thumbnail_engine.generator import ThumbnailGenerator
        with patch.dict("os.environ", {}, clear=True), \
             patch("gemini_client_factory.get_gemini_client"), \
             patch("thumbnail_engine.generator.get_model", return_value="m"):
            
            gen = ThumbnailGenerator()
            assert gen.api_key is None

    def test_tg_01_get_brand_style_fallback(self):
        from thumbnail_engine.generator import ThumbnailGenerator
        gen = ThumbnailGenerator.__new__(ThumbnailGenerator)
        with patch.dict("sys.modules", {"branding_manager": None}):
            style = gen._get_brand_style()
            assert "professional" in style.lower() or "quality" in style.lower()

    @pytest.mark.asyncio
    async def test_tg_02_generate_concepts_fallback(self):
        from thumbnail_engine.generator import ThumbnailGenerator
        gen = ThumbnailGenerator.__new__(ThumbnailGenerator)
        gen.client = MagicMock()
        gen.chat_model = "test-model"
        gen.client.models.generate_content.side_effect = Exception("API error")
        concepts = await gen._generate_concepts("Test Title", "desc", 3)
        assert len(concepts) >= 1
        assert concepts[0]["id"] == "concept_fallback"

    @pytest.mark.asyncio
    async def test_tg_03_generate_concepts_success(self):
        from thumbnail_engine.generator import ThumbnailGenerator
        gen = ThumbnailGenerator.__new__(ThumbnailGenerator)
        gen.client = MagicMock()
        gen.chat_model = "test-model"
        mock_resp = MagicMock()
        mock_resp.text = json.dumps([{"id": "c1", "name": "test", "description": "d", "visual_prompt": "p", "expected_ctr": 7.0}])
        gen.client.models.generate_content.return_value = mock_resp
        concepts = await gen._generate_concepts("Title", "Desc", 1)
        assert len(concepts) == 1

    @pytest.mark.asyncio
    async def test_tg_04_generate_image_error(self):
        from thumbnail_engine.generator import ThumbnailGenerator
        gen = ThumbnailGenerator.__new__(ThumbnailGenerator)
        gen.client = MagicMock()
        gen.image_model = "test-imagen"
        gen.client.models.generate_images.side_effect = Exception("API error")
        result = await gen._generate_image("test prompt")
        assert result is None

    @pytest.mark.asyncio
    async def test_tg_05_generate_image_empty(self):
        from thumbnail_engine.generator import ThumbnailGenerator
        gen = ThumbnailGenerator.__new__(ThumbnailGenerator)
        gen.client = MagicMock()
        gen.image_model = "test-imagen"
        mock_resp = MagicMock()
        mock_resp.generated_images = []
        gen.client.models.generate_images.return_value = mock_resp
        result = await gen._generate_image("test prompt")
        assert result is None

    @pytest.mark.asyncio
    async def test_tg_06_generate_full_error(self):
        from thumbnail_engine.generator import ThumbnailGenerator
        gen = ThumbnailGenerator.__new__(ThumbnailGenerator)
        gen.client = MagicMock()
        gen.chat_model = "m"
        gen.image_model = "m"
        gen.client.models.generate_content.side_effect = Exception("fail")
        results = await gen.generate("Title", "Desc", 1)
        assert results == []  # graceful degradation

    @pytest.mark.asyncio
    async def test_tg_07_generate_image_success(self):
        from thumbnail_engine.generator import ThumbnailGenerator
        gen = ThumbnailGenerator.__new__(ThumbnailGenerator)
        gen.client = MagicMock()
        gen.image_model = "test-imagen"
        mock_img = MagicMock()
        mock_img.image.image_bytes = b"\x89PNG\r\n"
        mock_resp = MagicMock()
        mock_resp.generated_images = [mock_img]
        gen.client.models.generate_images.return_value = mock_resp
        result = await gen._generate_image("prompt")
        assert result == b"\x89PNG\r\n"

    @pytest.mark.asyncio
    async def test_tg_08_generate_success(self):
        import base64
        from thumbnail_engine.generator import ThumbnailGenerator
        gen = ThumbnailGenerator.__new__(ThumbnailGenerator)
        gen.client = MagicMock()
        gen.chat_model = "m"
        gen.image_model = "m"
        
        with patch.object(gen, '_get_brand_style', return_value="Brand Style"), \
             patch.object(gen, '_generate_concepts', new_callable=AsyncMock) as mock_concepts, \
             patch.object(gen, '_generate_image', new_callable=AsyncMock) as mock_image:
            
            mock_concepts.return_value = [
                {"name": "Concept A", "description": "Desc A", "visual_prompt": "Prompt A", "expected_ctr": 8.5}
            ]
            mock_image.return_value = b"\x89PNG\r\n"
            
            results = await gen.generate("Title", "Desc", 1)
            
            assert len(results) == 1
            assert results[0]["concept_name"] == "Concept A"
            assert results[0]["image_base64"] == base64.b64encode(b"\x89PNG\r\n").decode("utf-8")
            assert results[0]["ctr_score"] == 8.5

    @pytest.mark.asyncio
    async def test_tg_09_generate_api_error(self):
        from thumbnail_engine.generator import ThumbnailGenerator
        from google.genai.errors import APIError
        gen = ThumbnailGenerator.__new__(ThumbnailGenerator)
        
        with patch.object(gen, '_get_brand_style', side_effect=APIError(500, {"message": "API error"})):
            results = await gen.generate("Title", "Desc", 1)
            assert results == []

    @pytest.mark.asyncio
    async def test_tg_10_generate_unexpected_error(self):
        from thumbnail_engine.generator import ThumbnailGenerator
        gen = ThumbnailGenerator.__new__(ThumbnailGenerator)
        
        with patch.object(gen, '_get_brand_style', side_effect=ValueError("Unexpected")):
            results = await gen.generate("Title", "Desc", 1)
            assert results == []

    def test_tg_11_get_brand_style_unexpected_error(self):
        from thumbnail_engine.generator import ThumbnailGenerator
        gen = ThumbnailGenerator.__new__(ThumbnailGenerator)
        
        class BadManager:
            @property
            def constitution(self):
                raise ValueError("Fatal DB Error")
                
        with patch("branding_manager.branding_manager", new=BadManager()), \
             patch("thumbnail_engine.generator.logger") as mock_logger:
            style = gen._get_brand_style()
            assert style == "High quality, professional, 8k resolution"
            mock_logger.error.assert_called_with("Unexpected error loading brand style, applying fallback: Fatal DB Error", exc_info=True)

    @pytest.mark.asyncio
    async def test_tg_12_generate_concepts_json_decode_error(self):
        from thumbnail_engine.generator import ThumbnailGenerator
        gen = ThumbnailGenerator.__new__(ThumbnailGenerator)
        gen.client = MagicMock()
        gen.chat_model = "m"
        
        mock_resp = MagicMock()
        mock_resp.text = "invalid json"
        gen.client.models.generate_content.return_value = mock_resp
        
        with patch("thumbnail_engine.generator.logger") as mock_logger:
            concepts = await gen._generate_concepts("Title", "Desc", 1)
            assert len(concepts) == 1
            assert concepts[0]["id"] == "concept_fallback"
            mock_logger.error.assert_any_call("JSON decode error in concept response: Expecting value: line 1 column 1 (char 0). Raw response: invalid json", exc_info=True)

    @pytest.mark.asyncio
    async def test_tg_13_generate_concepts_unexpected_error(self):
        from thumbnail_engine.generator import ThumbnailGenerator
        gen = ThumbnailGenerator.__new__(ThumbnailGenerator)
        gen.client = MagicMock()
        gen.chat_model = "m"
        gen.client.models.generate_content.side_effect = TypeError("Unexpected Type Error")
        
        with patch("thumbnail_engine.generator.logger") as mock_logger:
            concepts = await gen._generate_concepts("Title", "Desc", 1)
            assert len(concepts) == 1
            assert concepts[0]["id"] == "concept_fallback"
            mock_logger.error.assert_called_with("Unexpected error during concept generation: Unexpected Type Error", exc_info=True)

    @pytest.mark.asyncio
    async def test_tg_14_generate_image_unexpected_error(self):
        from thumbnail_engine.generator import ThumbnailGenerator
        gen = ThumbnailGenerator.__new__(ThumbnailGenerator)
        gen.client = MagicMock()
        gen.image_model = "m"
        gen.client.models.generate_images.side_effect = RuntimeError("Fatal Image Error")
        
        with patch("thumbnail_engine.generator.logger") as mock_logger:
            result = await gen._generate_image("prompt")
            assert result is None
            mock_logger.error.assert_called_with("Unexpected error during image generation: Fatal Image Error", exc_info=True)

    @pytest.mark.asyncio
    async def test_tg_17_generate_concepts_api_error(self):
        from thumbnail_engine.generator import ThumbnailGenerator
        from google.genai.errors import APIError
        gen = ThumbnailGenerator.__new__(ThumbnailGenerator)
        gen.client = MagicMock()
        gen.chat_model = "m"
        gen.client.models.generate_content.side_effect = APIError(500, {"message": "API error"})
        
        with patch("thumbnail_engine.generator.logger") as mock_logger:
            concepts = await gen._generate_concepts("Title", "Desc", 1)
            assert len(concepts) == 1
            assert concepts[0]["id"] == "concept_fallback"
            mock_logger.error.assert_called_with("GenAI API error during concept generation: 500 None. {'message': 'API error'}", exc_info=True)

    @pytest.mark.asyncio
    async def test_tg_18_generate_image_api_error(self):
        from thumbnail_engine.generator import ThumbnailGenerator
        from google.genai.errors import APIError
        gen = ThumbnailGenerator.__new__(ThumbnailGenerator)
        gen.client = MagicMock()
        gen.image_model = "m"
        gen.client.models.generate_images.side_effect = APIError(500, {"message": "API error"})
        
        with patch("thumbnail_engine.generator.logger") as mock_logger:
            result = await gen._generate_image("prompt")
            assert result is None
            mock_logger.error.assert_called_with("GenAI API error during image generation: 500 None. {'message': 'API error'}", exc_info=True)


