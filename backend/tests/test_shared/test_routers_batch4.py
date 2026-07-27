"""
ルーター群集中テスト — Batch 4 (フェーズC)

対象:
  1. legacy_production_router.py — 16テスト (validate_video_path, モデル, ヘルパー, エンドポイント)
  2. shorts.py — 8テスト (モデル, エンドポイント)
  3. smartcut.py — 8テスト (モデル, エンドポイント)
  4. segments.py — 10テスト (エンドポイント, _format_time)
  5. websocket.py — 8テスト (ConnectionManager)

合計: 50テスト
"""

import sys
from unittest.mock import MagicMock
sys.modules['google.adk'] = MagicMock()
sys.modules['mcp'] = MagicMock()
sys.modules['mcp.types'] = MagicMock()

# 実在しないモジュール 'subtitle_engine.transcriber' を偽装
mock_transcriber_module = MagicMock()
mock_transcriber_obj = MagicMock()
mock_transcriber_module.transcriber = mock_transcriber_obj
sys.modules["subtitle_engine.transcriber"] = mock_transcriber_module


import os
import json
import asyncio
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime

# backend ディレクトリをパスに追加
_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)


# ============================================================
# 1. Legacy Production Router (16テスト)
# ============================================================

class TestLegacyProductionRouter:
    """legacy_production_router.py のテスト"""

    # --- Pydantic Models ---
    def test_lpr_01_rhythm_request(self):
        """RhythmRequest モデル"""
        from routers.legacy_production_router import RhythmRequest
        req = RhythmRequest(text="テストテキスト")
        assert req.text == "テストテキスト"
        assert req.target_chars == 13  # default

    def test_lpr_02_transcribe_request(self):
        """TranscribeRequest モデル"""
        from routers.legacy_production_router import TranscribeRequest
        req = TranscribeRequest()
        assert req.language == "ja"
        assert req.with_proofreading is True

    def test_lpr_03_video_process_request(self):
        """VideoProcessRequest モデル"""
        from routers.legacy_production_router import VideoProcessRequest
        req = VideoProcessRequest(mood="elegant")
        assert req.mood == "elegant"
        assert req.video_paths == []
        assert req.output_name == "output"

    def test_lpr_04_preview_session_request(self):
        """PreviewSessionRequest モデル"""
        from routers.legacy_production_router import PreviewSessionRequest
        req = PreviewSessionRequest()
        assert req.session_id is None

    def test_lpr_05_realtime_preview_request(self):
        """RealtimePreviewRequest モデル"""
        from routers.legacy_production_router import RealtimePreviewRequest
        req = RealtimePreviewRequest(video_path="test.mp4", mood="elegant", duration=30)
        assert req.duration == 30

    # --- validate_video_path ---
    def test_lpr_06_validate_path_none_allowed(self):
        """validate_video_path — allow_none=True, パスなし"""
        from routers.legacy_production_router import validate_video_path
        result = validate_video_path("", allow_none=True)
        assert result is None

    def test_lpr_07_validate_path_empty_raises(self):
        """validate_video_path — 空パス"""
        from routers.legacy_production_router import validate_video_path
        with pytest.raises(ValueError, match="File path is required"):
            validate_video_path("")

    def test_lpr_08_validate_path_outside_dir(self, tmp_path):
        """validate_video_path — 許可ディレクトリ外"""
        from routers.legacy_production_router import validate_video_path
        fake = tmp_path / "test.mp4"
        fake.write_bytes(b"\x00" * 100)
        with pytest.raises(ValueError, match="Access denied"):
            validate_video_path(str(fake))

    def test_lpr_09_validate_path_not_exists(self):
        """validate_video_path — 存在しないファイル"""
        from routers.legacy_production_router import validate_video_path
        # ALLOWED_VIDEO_DIR 内だが存在しない
        fake_path = str(Path("C:/Users/PC_User/Desktop/script/video-automation/nonexistent.mp4"))
        with pytest.raises(FileNotFoundError):
            validate_video_path(fake_path)

    # --- Endpoint: transcription status ---
    def test_lpr_10_transcription_status_no_file(self, monkeypatch):
        """get_transcription_status — ステータスファイルなし"""
        lpr_mod = sys.modules["routers.legacy_production_router"]
        monkeypatch.setattr(lpr_mod, "SRC_DIR", "/nonexistent/dir")
        from routers.legacy_production_router import get_transcription_status
        result = get_transcription_status()
        assert result["status"] == "idle"

    def test_lpr_11_transcription_status_with_file(self, tmp_path, monkeypatch):
        """get_transcription_status — ステータスファイルあり"""
        lpr_mod = sys.modules["routers.legacy_production_router"]
        monkeypatch.setattr(lpr_mod, "SRC_DIR", str(tmp_path))
        status_file = tmp_path / "transcription_status.json"
        status_file.write_text('{"status": "completed", "message": "Done"}', encoding="utf-8")
        from routers.legacy_production_router import get_transcription_status
        result = get_transcription_status()
        assert result["status"] == "completed"

    # --- Endpoint: task status ---
    @pytest.mark.asyncio
    async def test_lpr_12_task_not_found(self, monkeypatch):
        """get_task_status — タスク不在で404"""
        from routers.legacy_production_router import get_task_status
        from fastapi import HTTPException
        mock_store = MagicMock()
        mock_store.get_task.return_value = None
        with patch("routers.legacy_production_router.task_store", mock_store, create=True):
            with pytest.raises(HTTPException) as exc_info:
                get_task_status("nonexistent-id")
            assert exc_info.value.status_code == 404

    # --- Endpoint: video tasks debug ---
    @pytest.mark.asyncio
    async def test_lpr_13_debug_video_tasks(self, monkeypatch):
        """debug_video_tasks — 空状態"""
        lpr_mod = sys.modules["routers.legacy_production_router"]
        monkeypatch.setattr(lpr_mod, "_video_tasks", {})
        from routers.legacy_production_router import debug_video_tasks
        result = await debug_video_tasks()
        assert result["task_count"] == 0

    # --- Endpoint: preview sessions ---
    @pytest.mark.asyncio
    async def test_lpr_14_list_preview_sessions(self, monkeypatch):
        """list_preview_sessions — 空状態"""
        lpr_mod = sys.modules["routers.legacy_production_router"]
        monkeypatch.setattr(lpr_mod, "_preview_sessions", {})
        from routers.legacy_production_router import list_preview_sessions
        result = await list_preview_sessions()
        assert result["count"] == 0
        assert result["sessions"] == []

    # --- Endpoint: list videos ---
    @pytest.mark.asyncio
    async def test_lpr_15_list_available_videos(self):
        """list_available_videos — 動画一覧（ディレクトリ不在時は空）"""
        from routers.legacy_production_router import list_available_videos
        result = await list_available_videos()
        assert "videos" in result
        assert "count" in result

    # --- Endpoint: video process status ---
    @pytest.mark.asyncio
    async def test_lpr_16_process_status_not_found(self, monkeypatch):
        """get_video_process_status — タスク不在で404"""
        lpr_mod = sys.modules["routers.legacy_production_router"]
        monkeypatch.setattr(lpr_mod, "_video_tasks", {})
        from routers.legacy_production_router import get_video_process_status
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await get_video_process_status("nonexistent")
        assert exc_info.value.status_code == 404

    # --- Additional Tests for Legacy Production Router (test_lpr_17 - test_lpr_51) ---
    def test_lpr_17_validate_path_invalid_format(self):
        """validate_video_path — Invalid path format"""
        from routers.legacy_production_router import validate_video_path
        with patch("routers.legacy_production_router.Path", side_effect=Exception("Invalid format")):
            with pytest.raises(ValueError, match="Invalid path format"):
                validate_video_path("invalid-path-format")

    def test_lpr_18_validate_path_too_large(self, tmp_path, monkeypatch):
        """validate_video_path — File too large"""
        from routers.legacy_production_router import validate_video_path
        lpr_mod = sys.modules["routers.legacy_production_router"]
        monkeypatch.setattr(lpr_mod, "ALLOWED_VIDEO_DIR", tmp_path)
        
        test_file = tmp_path / "large.mp4"
        test_file.write_bytes(b"\x00" * 100)
        
        mock_stat = MagicMock()
        mock_stat.st_size = 501 * 1024 * 1024
        
        with patch.object(Path, "stat", return_value=mock_stat):
            with pytest.raises(ValueError, match="File too large"):
                validate_video_path(str(test_file))

    def test_lpr_19_validate_path_invalid_extension(self, tmp_path, monkeypatch):
        """validate_video_path — Unsupported extension"""
        from routers.legacy_production_router import validate_video_path
        lpr_mod = sys.modules["routers.legacy_production_router"]
        monkeypatch.setattr(lpr_mod, "ALLOWED_VIDEO_DIR", tmp_path)
        
        test_file = tmp_path / "test.txt"
        test_file.write_bytes(b"\x00" * 10)
        
        with pytest.raises(ValueError, match="Unsupported file type"):
            validate_video_path(str(test_file))

    def test_lpr_20_validate_path_success(self, tmp_path, monkeypatch):
        """validate_video_path — Success"""
        from routers.legacy_production_router import validate_video_path
        lpr_mod = sys.modules["routers.legacy_production_router"]
        monkeypatch.setattr(lpr_mod, "ALLOWED_VIDEO_DIR", tmp_path)
        
        test_file = tmp_path / "test.mp4"
        test_file.write_bytes(b"\x00" * 10)
        
        result = validate_video_path(str(test_file))
        assert result.resolve() == test_file.resolve()

    @pytest.mark.asyncio
    async def test_lpr_21_rhythm_split_success(self):
        """rhythm_split — Success"""
        from routers.legacy_production_router import rhythm_split, RhythmRequest
        req = RhythmRequest(text="テストテキスト")
        mock_split = MagicMock(return_value=["テスト", "テキスト"])
        
        with patch.dict("sys.modules", {"ai_rhythm": MagicMock(semantic_split=mock_split)}):
            result = await rhythm_split(req)
            assert result == {"parts": ["テスト", "テキスト"]}
            mock_split.assert_called_once_with("テストテキスト", 13)

    @pytest.mark.asyncio
    async def test_lpr_22_rhythm_split_exception(self):
        """rhythm_split — Exception raises HTTP 500"""
        from routers.legacy_production_router import rhythm_split, RhythmRequest
        from fastapi import HTTPException
        req = RhythmRequest(text="テストテキスト")
        
        with patch.dict("sys.modules", {"ai_rhythm": MagicMock(semantic_split=MagicMock(side_effect=Exception("Split error")))}):
            with pytest.raises(HTTPException) as exc_info:
                await rhythm_split(req)
            assert exc_info.value.status_code == 500
            assert "Split error" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_lpr_23_trigger_transcription_success(self, tmp_path, monkeypatch):
        """trigger_transcription — Success with background task execution"""
        from routers.legacy_production_router import trigger_transcription, TranscribeRequest
        from fastapi import BackgroundTasks
        
        lpr_mod = sys.modules["routers.legacy_production_router"]
        monkeypatch.setattr(lpr_mod, "SRC_DIR", str(tmp_path))
        
        mock_settings = MagicMock()
        mock_settings.get_video_source.return_value = "dummy.mp4"
        
        mock_task_store = MagicMock()
        mock_task = MagicMock()
        mock_task.task_id = "test-task-id-12345"
        mock_task_store.create_task.return_value = mock_task
        
        mock_transcriber_inst = MagicMock()
        mock_transcriber_inst.transcribe_with_proofreading.return_value = "dummy_coro"
        mock_transcriber_cls = MagicMock(return_value=mock_transcriber_inst)
        
        mock_subtitle_engine = MagicMock()
        mock_subtitle_engine.WhisperTranscriber = mock_transcriber_cls
        
        mock_loop = MagicMock()
        mock_loop.run_until_complete.return_value = [{"text": "hello", "start": 0.0, "end": 1.0}]
        
        bg_tasks = BackgroundTasks()
        added_tasks = []
        monkeypatch.setattr(bg_tasks, "add_task", lambda func, *args, **kwargs: added_tasks.append((func, args, kwargs)))
        
        req = TranscribeRequest(video_path="dummy.mp4")
        
        with patch("os.path.exists", return_value=True), \
             patch("settings_manager.settings_manager", mock_settings), \
             patch("task_store.task_store", mock_task_store), \
             patch("routers.legacy_production_router.broadcaster", AsyncMock()), \
             patch.dict("sys.modules", {"subtitle_engine": mock_subtitle_engine}), \
             patch("asyncio.new_event_loop", return_value=mock_loop), \
             patch("asyncio.set_event_loop"):
             
            result = await trigger_transcription(bg_tasks, req)
            assert result["status"] == "started"
            assert result["task_id"] == "test-task-id-12345"
            assert len(added_tasks) == 1
            
            process_task_func = added_tasks[0][0]
            process_task_func()
                
            mock_loop.run_until_complete.assert_called_once_with("dummy_coro")
            mock_task_store.complete_task.assert_called_once_with("test-task-id-12345", result_path=os.path.join(str(tmp_path), "segments_test-tas.json"))

    @pytest.mark.asyncio
    async def test_lpr_24_trigger_transcription_source_not_found(self):
        """trigger_transcription — Video source not found HTTP 404"""
        from routers.legacy_production_router import trigger_transcription, TranscribeRequest
        from fastapi import BackgroundTasks, HTTPException
        
        req = TranscribeRequest(video_path="nonexistent.mp4")
        bg_tasks = BackgroundTasks()
        
        with patch("os.path.exists", return_value=False):
            with pytest.raises(HTTPException) as exc_info:
                await trigger_transcription(bg_tasks, req)
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_lpr_25_trigger_transcription_process_task_fails(self, tmp_path, monkeypatch):
        """trigger_transcription — background task fail path"""
        from routers.legacy_production_router import trigger_transcription, TranscribeRequest
        from fastapi import BackgroundTasks
        
        lpr_mod = sys.modules["routers.legacy_production_router"]
        monkeypatch.setattr(lpr_mod, "SRC_DIR", str(tmp_path))
        
        mock_task_store = MagicMock()
        mock_task = MagicMock()
        mock_task.task_id = "test-task-id-err"
        mock_task_store.create_task.return_value = mock_task
        
        mock_transcriber_inst = MagicMock()
        mock_transcriber_inst.transcribe_with_proofreading.return_value = "dummy_coro"
        
        mock_subtitle_engine = MagicMock()
        mock_subtitle_engine.WhisperTranscriber = MagicMock(return_value=mock_transcriber_inst)
        
        mock_loop = MagicMock()
        mock_loop.run_until_complete.side_effect = Exception("Whisper load failed")
        
        bg_tasks = BackgroundTasks()
        added_tasks = []
        monkeypatch.setattr(bg_tasks, "add_task", lambda func: added_tasks.append(func))
        
        req = TranscribeRequest(video_path="dummy.mp4")
        
        with patch("os.path.exists", return_value=True), \
             patch("task_store.task_store", mock_task_store), \
             patch.dict("sys.modules", {"subtitle_engine": mock_subtitle_engine}), \
             patch("asyncio.new_event_loop", return_value=mock_loop), \
             patch("asyncio.set_event_loop"):
             
            await trigger_transcription(bg_tasks, req)
            assert len(added_tasks) == 1
            
            process_task_func = added_tasks[0]
            process_task_func()
                
            mock_task_store.fail_task.assert_called_once_with("test-task-id-err", "Whisper load failed")

    def test_lpr_26_transcription_status_json_decode_error(self, tmp_path, monkeypatch):
        """get_transcription_status — JSON decode exception path"""
        lpr_mod = sys.modules["routers.legacy_production_router"]
        monkeypatch.setattr(lpr_mod, "SRC_DIR", str(tmp_path))
        
        status_file = tmp_path / "transcription_status.json"
        status_file.write_text("invalid json content", encoding="utf-8")
        
        from routers.legacy_production_router import get_transcription_status
        result = get_transcription_status()
        assert result["status"] == "unknown"
        assert "Reading status file failed" in result["message"]

    def test_lpr_27_get_task_status_success(self):
        """get_task_status — Success path"""
        from routers.legacy_production_router import get_task_status
        mock_task = MagicMock()
        mock_task.to_dict.return_value = {"task_id": "123", "status": "completed"}
        
        with patch("task_store.task_store.get_task", return_value=mock_task):
            result = get_task_status("123")
            assert result == {"task_id": "123", "status": "completed"}

    def test_lpr_28_list_tasks_with_status_filter(self):
        """list_tasks — With valid status filter"""
        from routers.legacy_production_router import list_tasks
        
        mock_list = MagicMock(return_value=[])
        with patch("task_store.task_store.list_tasks", mock_list):
            list_tasks(status="completed")
            from task_store import TaskStatus
            mock_list.assert_called_once_with(status=TaskStatus.COMPLETED)

    def test_lpr_29_list_tasks_with_invalid_status_filter(self):
        """list_tasks — With invalid status filter (ValueError ignored)"""
        from routers.legacy_production_router import list_tasks
        
        mock_list = MagicMock(return_value=[])
        with patch("task_store.task_store.list_tasks", mock_list):
            list_tasks(status="invalid_status_value")
            mock_list.assert_called_once_with(status=None)

    @pytest.mark.asyncio
    async def test_lpr_30_transcribe_video_success(self):
        """transcribe_video — Upload and transcribe success"""
        from routers.legacy_production_router import transcribe_video
        from fastapi import UploadFile
        
        mock_file = AsyncMock(spec=UploadFile)
        mock_file.filename = "test_video.mp4"
        mock_file.read.return_value = b"\x00\x00\x00\x18ftypmp42"
        
        mock_transcriber_inst = MagicMock()
        mock_transcriber_inst.transcribe_with_proofreading = AsyncMock(return_value=[{"text": "upload text", "start": 0.0, "end": 2.0}])
        
        mock_probe_res = MagicMock()
        mock_probe_res.stdout = '{"format": {"duration": "10.5"}}'
        
        mock_subtitle_engine = MagicMock()
        mock_subtitle_engine.WhisperTranscriber = MagicMock(return_value=mock_transcriber_inst)
        
        with patch.dict("sys.modules", {"subtitle_engine": mock_subtitle_engine}), \
             patch("subprocess.run", return_value=mock_probe_res) as mock_run:
              
            result = await transcribe_video(mock_file)
            assert result["segments_count"] == 1
            assert result["duration"] == 10.5
            assert result["subtitles"] == [{"text": "upload text", "start": 0.0, "end": 2.0}]
            
            args, kwargs = mock_run.call_args
            assert "ffprobe" in args[0]

    @pytest.mark.asyncio
    async def test_lpr_31_transcribe_video_exception(self):
        """transcribe_video — Exception raises HTTP 500"""
        from routers.legacy_production_router import transcribe_video
        from fastapi import UploadFile, HTTPException
        
        mock_file = AsyncMock(spec=UploadFile)
        mock_file.filename = "test_video.mp4"
        mock_file.read.side_effect = Exception("Read upload failed")
        
        mock_subtitle_engine = MagicMock()
        
        with patch.dict("sys.modules", {"subtitle_engine": mock_subtitle_engine}):
            with pytest.raises(HTTPException) as exc_info:
                await transcribe_video(mock_file)
            assert exc_info.value.status_code == 500
            assert "Transcription failed" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_lpr_32_export_subtitles_vtt(self):
        """export_subtitles — Export to VTT success"""
        from routers.legacy_production_router import export_subtitles
        subtitles = [{"text": "vtt text", "start": 0.0, "end": 1.0}]
        
        mock_formatter = MagicMock()
        mock_formatter.to_vtt.return_value = "WEBVTT\n\n1\n00:00:00.000 --> 00:00:01.000\nvtt text"
        mock_subtitle_engine = MagicMock()
        mock_subtitle_engine.SubtitleFormatter = mock_formatter
        
        with patch.dict("sys.modules", {"subtitle_engine": mock_subtitle_engine}):
            response = await export_subtitles("vtt", subtitles)
            assert response.media_type == "text/vtt"
            mock_formatter.to_vtt.assert_called_once_with(subtitles)

    @pytest.mark.asyncio
    async def test_lpr_33_export_subtitles_srt(self):
        """export_subtitles — Export to SRT success"""
        from routers.legacy_production_router import export_subtitles
        subtitles = [{"text": "srt text", "start": 0.0, "end": 1.0}]
        
        mock_formatter = MagicMock()
        mock_formatter.to_srt.return_value = "1\n00:00:00,000 --> 00:00:01,000\nsrt text"
        mock_subtitle_engine = MagicMock()
        mock_subtitle_engine.SubtitleFormatter = mock_formatter
        
        with patch.dict("sys.modules", {"subtitle_engine": mock_subtitle_engine}):
            response = await export_subtitles("srt", subtitles)
            assert response.media_type == "text/plain"
            mock_formatter.to_srt.assert_called_once_with(subtitles)

    @pytest.mark.asyncio
    async def test_lpr_34_export_subtitles_invalid_format(self):
        """export_subtitles — Invalid format raises HTTP 400"""
        from routers.legacy_production_router import export_subtitles
        from fastapi import HTTPException
        
        with pytest.raises(HTTPException) as exc_info:
            await export_subtitles("txt", [])
        assert exc_info.value.status_code == 400
        assert "Format must be" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_lpr_35_export_subtitles_exception(self):
        """export_subtitles — Exception raises HTTP 500"""
        from routers.legacy_production_router import export_subtitles
        from fastapi import HTTPException
        
        mock_formatter = MagicMock()
        mock_formatter.to_vtt.side_effect = Exception("Formatter error")
        mock_subtitle_engine = MagicMock()
        mock_subtitle_engine.SubtitleFormatter = mock_formatter
        
        with patch.dict("sys.modules", {"subtitle_engine": mock_subtitle_engine}):
            with pytest.raises(HTTPException) as exc_info:
                await export_subtitles("vtt", [])
            assert exc_info.value.status_code == 500
            assert "Export failed" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_lpr_36_create_preview_session(self):
        """create_preview_session — Success"""
        from routers.legacy_production_router import create_preview_session, PreviewSessionRequest, _preview_sessions
        
        mock_pp = MagicMock()
        mock_pp.session_id = "test-session-pp"
        mock_pp.output_dir = Path("dummy_dir")
        
        req = PreviewSessionRequest(session_id="test-session-pp")
        
        with patch("progressive_preview.ProgressivePreview", return_value=mock_pp):
            result = await create_preview_session(req)
            assert result["session_id"] == "test-session-pp"
            assert result["status"] == "created"
            assert _preview_sessions["test-session-pp"] == mock_pp

    @pytest.mark.asyncio
    async def test_lpr_37_capture_step_snapshot_success(self, monkeypatch):
        """capture_step_snapshot — Success"""
        from routers.legacy_production_router import capture_step_snapshot, StepSnapshotRequest
        
        mock_pp = MagicMock()
        mock_pp.output_dir = Path("dummy_dir")
        mock_pp.snapshot_step.return_value = {"comparisons": [1, 2, 3]}
        
        lpr_mod = sys.modules["routers.legacy_production_router"]
        monkeypatch.setattr(lpr_mod, "_preview_sessions", {"test-sess": mock_pp})
        
        req = StepSnapshotRequest(session_id="test-sess", step_name="step1", before_video="b.mp4", after_video="a.mp4", num_samples=3)
        
        result = await capture_step_snapshot(req)
        assert result["status"] == "success"
        assert result["comparisons"] == 3
        mock_pp.snapshot_step.assert_called_once_with(step_name="step1", before_video="b.mp4", after_video="a.mp4", num_samples=3)

    @pytest.mark.asyncio
    async def test_lpr_38_capture_step_snapshot_exception(self, monkeypatch):
        """capture_step_snapshot — Exception raises HTTP 500"""
        from routers.legacy_production_router import capture_step_snapshot, StepSnapshotRequest
        from fastapi import HTTPException
        
        mock_pp = MagicMock()
        mock_pp.snapshot_step.side_effect = Exception("Snapshot error")
        
        lpr_mod = sys.modules["routers.legacy_production_router"]
        monkeypatch.setattr(lpr_mod, "_preview_sessions", {"test-sess": mock_pp})
        
        req = StepSnapshotRequest(session_id="test-sess", step_name="step1", before_video="b.mp4", after_video="a.mp4")
        
        with pytest.raises(HTTPException) as exc_info:
            await capture_step_snapshot(req)
        assert exc_info.value.status_code == 500
        assert "Snapshot error" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_lpr_39_get_preview_report_success(self, monkeypatch):
        """get_preview_report — Success"""
        from routers.legacy_production_router import get_preview_report
        
        mock_pp = MagicMock()
        mock_pp.output_dir = Path("dummy_dir")
        
        lpr_mod = sys.modules["routers.legacy_production_router"]
        monkeypatch.setattr(lpr_mod, "_preview_sessions", {"test-sess": mock_pp})
        
        mock_generator = MagicMock()
        mock_generator.generate_from_session_dir.return_value = "report.html"
        
        with patch("progressive_preview_report.PreviewReportGenerator", return_value=mock_generator), \
             patch("routers.legacy_production_router.FileResponse", return_value="FileResponseObject"):
              
            result = await get_preview_report("test-sess")
            assert result == "FileResponseObject"
            mock_generator.generate_from_session_dir.assert_called_once_with("dummy_dir")

    @pytest.mark.asyncio
    async def test_lpr_40_get_preview_report_exception(self, monkeypatch):
        """get_preview_report — Exception raises HTTP 500"""
        from routers.legacy_production_router import get_preview_report
        from fastapi import HTTPException
        
        mock_pp = MagicMock()
        mock_pp.output_dir = Path("dummy_dir")
        
        lpr_mod = sys.modules["routers.legacy_production_router"]
        monkeypatch.setattr(lpr_mod, "_preview_sessions", {"test-sess": mock_pp})
        
        mock_generator = MagicMock()
        mock_generator.generate_from_session_dir.side_effect = Exception("Report gen error")
        
        with patch("progressive_preview_report.PreviewReportGenerator", return_value=mock_generator):
            with pytest.raises(HTTPException) as exc_info:
                await get_preview_report("test-sess")
            assert exc_info.value.status_code == 500
            assert "Report gen error" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_lpr_41_submit_preview_decision_existing_file(self, tmp_path, monkeypatch):
        """submit_preview_decision — Appends to existing json file"""
        from routers.legacy_production_router import submit_preview_decision, PreviewDecisionRequest
        
        # カレントディレクトリを変更してパス解決を tmp_path 内に誘導
        monkeypatch.chdir(tmp_path)
        
        decision_dir = tmp_path / "backend" / "temp" / "previews"
        decision_dir.mkdir(parents=True, exist_ok=True)
        decision_file = decision_dir / "decisions.json"
        decision_file.write_text('[{"session_id": "old-sess", "decision": "approved"}]', encoding="utf-8")
        
        req = PreviewDecisionRequest(session_id="new-sess", decision="rejected", feedback="bad timing")
        
        result = await submit_preview_decision(req)
        assert result["status"] == "recorded"
        assert result["decision"] == "rejected"
        
        content = json.loads(decision_file.read_text(encoding="utf-8"))
        assert len(content) == 2
        assert content[0]["session_id"] == "old-sess"
        assert content[1]["session_id"] == "new-sess"
        assert content[1]["feedback"] == "bad timing"

    @pytest.mark.asyncio
    async def test_lpr_42_submit_preview_decision_invalid_json(self, tmp_path, monkeypatch):
        """submit_preview_decision — Overwrites invalid json content"""
        from routers.legacy_production_router import submit_preview_decision, PreviewDecisionRequest
        
        monkeypatch.chdir(tmp_path)
        
        decision_dir = tmp_path / "backend" / "temp" / "previews"
        decision_dir.mkdir(parents=True, exist_ok=True)
        decision_file = decision_dir / "decisions.json"
        decision_file.write_text("invalid json content", encoding="utf-8")
        
        req = PreviewDecisionRequest(session_id="new-sess", decision="approved")
        
        result = await submit_preview_decision(req)
        assert result["status"] == "recorded"
        
        content = json.loads(decision_file.read_text(encoding="utf-8"))
        assert len(content) == 1
        assert content[0]["session_id"] == "new-sess"

    def test_lpr_43_apply_color_grading_success(self):
        """apply_color_grading — Success"""
        from routers.legacy_production_router import apply_color_grading
        
        mock_color = MagicMock()
        mock_color.apply_preset.return_value = "graded.mp4"
        
        mock_module = MagicMock()
        mock_module.color_grading = mock_color
        
        with patch.dict("sys.modules", {"color_grading": mock_module}):
            result = apply_color_grading("in.mp4", "cinematic")
            assert result == {"graded_video": "graded.mp4", "preset": "cinematic", "status": "success"}
            mock_color.apply_preset.assert_called_once_with("in.mp4", "cinematic")

    def test_lpr_44_apply_color_grading_exception(self):
        """apply_color_grading — Exception raises HTTP 500"""
        from routers.legacy_production_router import apply_color_grading
        from fastapi import HTTPException
        
        mock_color = MagicMock()
        mock_color.apply_preset.side_effect = Exception("Grading error")
        
        mock_module = MagicMock()
        mock_module.color_grading = mock_color
        
        with patch.dict("sys.modules", {"color_grading": mock_module}):
            with pytest.raises(HTTPException) as exc_info:
                apply_color_grading("in.mp4", "cinematic")
            assert exc_info.value.status_code == 500
            assert "Grading error" in exc_info.value.detail

    def test_lpr_45_get_color_presets(self):
        """get_color_presets — Success"""
        from routers.legacy_production_router import get_color_presets
        
        mock_color = MagicMock()
        mock_color.PRESETS = {"preset1": {}, "preset2": {}}
        
        mock_module = MagicMock()
        mock_module.color_grading = mock_color
        
        with patch.dict("sys.modules", {"color_grading": mock_module}):
            result = get_color_presets()
            assert result["presets"] == ["preset1", "preset2"]
            assert result["default"] == "cinematic"

    @pytest.mark.asyncio
    async def test_lpr_46_start_video_processing_success(self, monkeypatch):
        """start_video_processing — Success with background task execution"""
        from routers.legacy_production_router import start_video_processing, VideoProcessRequest
        from fastapi import BackgroundTasks
        
        mock_video_processor = MagicMock()
        mock_task = MagicMock()
        mock_video_processor.create_task.return_value = mock_task
        
        mock_settings = MagicMock()
        mock_settings.name = "Elegant"
        mock_settings.transition = "fade"
        mock_settings.telop_style = "default"
        
        bg_tasks = BackgroundTasks()
        added_tasks = []
        monkeypatch.setattr(bg_tasks, "add_task", lambda func: added_tasks.append(func))
        
        req = VideoProcessRequest(video_paths=["v1.mp4"], mood="elegant", output_name="out")
        
        with patch("routers.legacy_production_router.video_processor", mock_video_processor), \
             patch("routers.legacy_production_router.MOOD_SETTINGS", {"elegant": mock_settings}), \
             patch("routers.legacy_production_router.broadcaster", AsyncMock()) as mock_broadcaster:
             
            result = await start_video_processing(bg_tasks, req)
            assert result["status"] == "started"
            assert "task_id" in result
            assert len(added_tasks) == 1
            
            task_id = result["task_id"]
            process_video_task_func = added_tasks[0]
            
            def mock_process_video(tid):
                cb = mock_video_processor.set_progress_callback.call_args[0][0]
                t = MagicMock()
                t.phase.value = "processing"
                t.progress = 50
                t.current_step = "レンダリング中"
                t.output_path = "out.mp4"
                t.preview_url = "http://preview"
                t.error = None
                cb(t)
                
            mock_video_processor.process_video.side_effect = mock_process_video
            
            with patch("asyncio.get_event_loop", return_value=asyncio.get_event_loop()):
                process_video_task_func()
                
            mock_video_processor.process_video.assert_called_once_with(task_id)
            mock_broadcaster.broadcast.assert_called_once()

    @pytest.mark.asyncio
    async def test_lpr_47_start_video_processing_exception(self, monkeypatch):
        """start_video_processing — background task exception path"""
        from routers.legacy_production_router import start_video_processing, VideoProcessRequest, _video_tasks
        from fastapi import BackgroundTasks
        
        mock_video_processor = MagicMock()
        mock_video_processor.process_video.side_effect = Exception("Processing failed")
        
        bg_tasks = BackgroundTasks()
        added_tasks = []
        monkeypatch.setattr(bg_tasks, "add_task", lambda func: added_tasks.append(func))
        
        req = VideoProcessRequest(video_paths=["v1.mp4"], mood="elegant")
        
        with patch("routers.legacy_production_router.video_processor", mock_video_processor):
            result = await start_video_processing(bg_tasks, req)
            task_id = result["task_id"]
            
            process_video_task_func = added_tasks[0]
            process_video_task_func()
            
            assert _video_tasks[task_id]["status"] == "error"
            assert _video_tasks[task_id]["error"] == "Processing failed"

    @pytest.mark.asyncio
    async def test_lpr_48_get_video_process_status_success(self, monkeypatch):
        """get_video_process_status — Success"""
        from routers.legacy_production_router import get_video_process_status
        
        lpr_mod = sys.modules["routers.legacy_production_router"]
        monkeypatch.setattr(lpr_mod, "_video_tasks", {"task-123": {"status": "completed"}})
        
        result = await get_video_process_status("task-123")
        assert result == {"status": "completed"}

    @pytest.mark.asyncio
    async def test_lpr_49_generate_realtime_preview_success(self, monkeypatch):
        """generate_realtime_preview — Success path"""
        from routers.legacy_production_router import generate_realtime_preview, RealtimePreviewRequest
        from fastapi import BackgroundTasks
        
        bg_tasks = BackgroundTasks()
        added_tasks = []
        monkeypatch.setattr(bg_tasks, "add_task", lambda func: added_tasks.append(func))
        
        req = RealtimePreviewRequest(video_path="test_video.mp4", duration=15)
        
        mock_preview_engine = MagicMock()
        
        with patch("pathlib.Path.exists", return_value=True), \
             patch("preview_engine.preview_engine", mock_preview_engine):
             
            result = await generate_realtime_preview(bg_tasks, req)
            assert result["status"] == "generating"
            assert result["source"] == "test_video.mp4"
            assert len(added_tasks) == 1
            
            added_tasks[0]()
            mock_preview_engine.generate_preview.assert_called_once_with(source_video="test_video.mp4", duration=15)

    @pytest.mark.asyncio
    async def test_lpr_50_generate_realtime_preview_fallback(self, monkeypatch, tmp_path):
        """generate_realtime_preview — Fallbacks to demo dir if source not exists"""
        from routers.legacy_production_router import generate_realtime_preview, RealtimePreviewRequest
        from fastapi import BackgroundTasks
        
        bg_tasks = BackgroundTasks()
        added_tasks = []
        monkeypatch.setattr(bg_tasks, "add_task", lambda func: added_tasks.append(func))
        
        req = RealtimePreviewRequest(video_path="nonexistent.mp4", duration=15)
        
        demo_dir = tmp_path / "raw_videos" / "AI Studio アップロード用動画"
        demo_dir.mkdir(parents=True)
        demo_video = demo_dir / "demo.mp4"
        demo_video.write_bytes(b"\x00")
        
        mock_preview_engine = MagicMock()
        
        orig_exists = Path.exists
        def mock_exists(self):
            if "nonexistent.mp4" in str(self):
                return False
            if "raw_videos" in str(self) or "demo.mp4" in str(self):
                return True
            return orig_exists(self)
            
        with patch("pathlib.Path.exists", mock_exists), \
             patch("pathlib.Path.glob", return_value=[demo_video]), \
             patch("preview_engine.preview_engine", mock_preview_engine):
             
            result = await generate_realtime_preview(bg_tasks, req)
            assert result["status"] == "generating"
            assert result["source"] == "demo.mp4"

    @pytest.mark.asyncio
    async def test_lpr_51_generate_realtime_preview_exception(self, monkeypatch):
        """generate_realtime_preview — Logs error and doesn't crash on task failure"""
        from routers.legacy_production_router import generate_realtime_preview, RealtimePreviewRequest
        from fastapi import BackgroundTasks
        
        bg_tasks = BackgroundTasks()
        added_tasks = []
        monkeypatch.setattr(bg_tasks, "add_task", lambda func: added_tasks.append(func))
        
        req = RealtimePreviewRequest(video_path="test_video.mp4")
        
        mock_preview_engine = MagicMock()
        mock_preview_engine.generate_preview.side_effect = Exception("Preview generation crashed")
        
        mock_logger = MagicMock()
        
        with patch("pathlib.Path.exists", return_value=True), \
             patch("preview_engine.preview_engine", mock_preview_engine), \
             patch("routers.legacy_production_router.logger", mock_logger):
             
            await generate_realtime_preview(bg_tasks, req)
            added_tasks[0]()
            mock_logger.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_lpr_52_validate_path_http_exception(self):
        """validate_video_path — Path.resolve() が HTTPException を投げた場合にそのまま raise する"""
        from routers.legacy_production_router import validate_video_path
        from fastapi import HTTPException
        
        with patch("routers.legacy_production_router.Path") as mock_path_cls:
            mock_path_inst = mock_path_cls.return_value
            mock_path_inst.resolve.side_effect = HTTPException(status_code=400, detail="Path resolves to HTTP exception")
            with pytest.raises(HTTPException) as exc_info:
                validate_video_path("dummy.mp4")
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_lpr_53_rhythm_split_http_exception(self):
        """rhythm_split — semantic_split が HTTPException を投げた場合にそのまま raise する"""
        from routers.legacy_production_router import rhythm_split, RhythmRequest
        from fastapi import HTTPException
        req = RhythmRequest(text="テスト")
        mock_split = MagicMock(side_effect=HTTPException(status_code=400, detail="Semantic split HTTP exception"))
        
        with patch.dict("sys.modules", {"ai_rhythm": MagicMock(semantic_split=mock_split)}):
            with pytest.raises(HTTPException) as exc_info:
                await rhythm_split(req)
            assert exc_info.value.status_code == 400

    def test_lpr_54_transcription_status_http_exception(self, tmp_path, monkeypatch):
        """get_transcription_status — open 等で HTTPException が投げられた場合にそのまま raise する"""
        from routers.legacy_production_router import get_transcription_status
        from fastapi import HTTPException
        
        lpr_mod = sys.modules["routers.legacy_production_router"]
        monkeypatch.setattr(lpr_mod, "SRC_DIR", str(tmp_path))
        status_file = tmp_path / "transcription_status.json"
        status_file.write_text("{}", encoding="utf-8")
        
        mock_open = MagicMock(side_effect=HTTPException(status_code=401, detail="Unauthorized file open"))
        with patch("builtins.open", mock_open):
            with pytest.raises(HTTPException) as exc_info:
                get_transcription_status()
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_lpr_55_transcribe_video_http_exception(self):
        """transcribe_video — ファイル読み込み等で HTTPException が発生した場合にそのまま raise する"""
        from routers.legacy_production_router import transcribe_video
        from fastapi import UploadFile, HTTPException
        
        mock_file = AsyncMock(spec=UploadFile)
        mock_file.filename = "test.mp4"
        mock_file.read.side_effect = HTTPException(status_code=403, detail="Forbidden upload read")
        
        with pytest.raises(HTTPException) as exc_info:
            await transcribe_video(mock_file)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_lpr_56_capture_step_snapshot_session_not_exists(self, monkeypatch):
        """capture_step_snapshot — セッションが存在しない場合に新規作成する"""
        from routers.legacy_production_router import capture_step_snapshot, StepSnapshotRequest
        
        mock_pp = MagicMock()
        mock_pp.output_dir = Path("dummy_dir")
        mock_pp.snapshot_step.return_value = {"comparisons": [1]}
        
        lpr_mod = sys.modules["routers.legacy_production_router"]
        monkeypatch.setattr(lpr_mod, "_preview_sessions", {})
        
        req = StepSnapshotRequest(session_id="new-sess-id", step_name="step1", before_video="b.mp4", after_video="a.mp4")
        
        with patch("progressive_preview.ProgressivePreview", return_value=mock_pp):
            result = await capture_step_snapshot(req)
            assert result["status"] == "success"
            assert "new-sess-id" in lpr_mod._preview_sessions

    @pytest.mark.asyncio
    async def test_lpr_57_capture_step_snapshot_http_exception(self, monkeypatch):
        """capture_step_snapshot — snapshot_step が HTTPException を投げた場合にそのまま raise する"""
        from routers.legacy_production_router import capture_step_snapshot, StepSnapshotRequest
        from fastapi import HTTPException
        
        mock_pp = MagicMock()
        mock_pp.snapshot_step.side_effect = HTTPException(status_code=400, detail="Snapshot HTTP exception")
        
        lpr_mod = sys.modules["routers.legacy_production_router"]
        monkeypatch.setattr(lpr_mod, "_preview_sessions", {"test-sess": mock_pp})
        
        req = StepSnapshotRequest(session_id="test-sess", step_name="step1", before_video="b.mp4", after_video="a.mp4")
        
        with pytest.raises(HTTPException) as exc_info:
            await capture_step_snapshot(req)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_lpr_58_get_preview_report_session_not_found(self, monkeypatch):
        """get_preview_report — セッションが存在しない場合に HTTPException(404) を投げる"""
        from routers.legacy_production_router import get_preview_report
        from fastapi import HTTPException
        
        lpr_mod = sys.modules["routers.legacy_production_router"]
        monkeypatch.setattr(lpr_mod, "_preview_sessions", {})
        
        with pytest.raises(HTTPException) as exc_info:
            await get_preview_report("nonexistent-session")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_lpr_59_get_preview_report_http_exception(self, monkeypatch):
        """get_preview_report — レポート生成時に HTTPException が投げられた場合にそのまま raise する"""
        from routers.legacy_production_router import get_preview_report
        from fastapi import HTTPException
        
        mock_pp = MagicMock()
        mock_pp.output_dir = Path("dummy_dir")
        
        lpr_mod = sys.modules["routers.legacy_production_router"]
        monkeypatch.setattr(lpr_mod, "_preview_sessions", {"test-sess": mock_pp})
        
        mock_generator = MagicMock()
        mock_generator.generate_from_session_dir.side_effect = HTTPException(status_code=400, detail="Generator HTTP error")
        
        with patch("progressive_preview_report.PreviewReportGenerator", return_value=mock_generator):
            with pytest.raises(HTTPException) as exc_info:
                await get_preview_report("test-sess")
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_lpr_60_submit_preview_decision_http_exception(self, tmp_path, monkeypatch):
        """submit_preview_decision — 保存処理中に HTTPException が発生した場合にそのまま raise する"""
        from routers.legacy_production_router import submit_preview_decision, PreviewDecisionRequest
        from fastapi import HTTPException
        
        monkeypatch.chdir(tmp_path)
        decision_dir = tmp_path / "backend" / "temp" / "previews"
        decision_dir.mkdir(parents=True, exist_ok=True)
        decision_file = decision_dir / "decisions.json"
        decision_file.write_text("[]", encoding="utf-8")
        
        req = PreviewDecisionRequest(session_id="sess", decision="approved")
        
        mock_open = MagicMock(side_effect=HTTPException(status_code=403, detail="Forbidden decision write"))
        with patch("builtins.open", mock_open):
            with pytest.raises(HTTPException) as exc_info:
                await submit_preview_decision(req)
            assert exc_info.value.status_code == 403

    def test_lpr_61_apply_color_grading_http_exception(self):
        """apply_color_grading — color_grading が HTTPException を投げた場合にそのまま raise する"""
        from routers.legacy_production_router import apply_color_grading
        from fastapi import HTTPException
        
        mock_color = MagicMock()
        mock_color.apply_preset.side_effect = HTTPException(status_code=400, detail="Color grade HTTP exception")
        mock_module = MagicMock(color_grading=mock_color)
        
        with patch.dict("sys.modules", {"color_grading": mock_module}):
            with pytest.raises(HTTPException) as exc_info:
                apply_color_grading("in.mp4", "cinematic")
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_lpr_62_start_video_processing_broadcast_fails(self, monkeypatch):
        """start_video_processing — broadcaster.broadcast で例外が発生してもタスク処理が続行される"""
        from routers.legacy_production_router import start_video_processing, VideoProcessRequest, _video_tasks
        from fastapi import BackgroundTasks
        
        mock_video_processor = MagicMock()
        mock_task = MagicMock()
        mock_video_processor.create_task.return_value = mock_task
        
        bg_tasks = BackgroundTasks()
        added_tasks = []
        monkeypatch.setattr(bg_tasks, "add_task", lambda func: added_tasks.append(func))
        
        req = VideoProcessRequest(video_paths=["v1.mp4"], mood="elegant", output_name="out")
        
        mock_broadcaster = MagicMock()
        mock_broadcaster.broadcast.side_effect = Exception("Broadcast failed")
        
        with patch("routers.legacy_production_router.video_processor", mock_video_processor),              patch("routers.legacy_production_router.MOOD_SETTINGS", {"elegant": MagicMock(name="Elegant")}),              patch("routers.legacy_production_router.broadcaster", mock_broadcaster):
             
            result = await start_video_processing(bg_tasks, req)
            task_id = result["task_id"]
            process_video_task_func = added_tasks[0]
            
            def mock_process_video(tid):
                cb = mock_video_processor.set_progress_callback.call_args[0][0]
                t = MagicMock()
                t.phase.value = "processing"
                t.progress = 50
                t.current_step = "レンダリング中"
                t.output_path = "out.mp4"
                t.preview_url = "http://preview"
                t.error = None
                cb(t)
                
            mock_video_processor.process_video.side_effect = mock_process_video
            
            with patch("asyncio.get_event_loop", return_value=asyncio.get_event_loop()):
                process_video_task_func()
                
            mock_video_processor.process_video.assert_called_once_with(task_id)
            assert _video_tasks[task_id]["status"] == "processing"
            assert _video_tasks[task_id]["progress"] == 50

    @pytest.mark.asyncio
    async def test_lpr_63_generate_realtime_preview_video_not_found(self, monkeypatch):
        """generate_realtime_preview — 動画ファイルが存在せず、かつデモ動画も存在しない場合に HTTPException(400) を投げる"""
        from routers.legacy_production_router import generate_realtime_preview, RealtimePreviewRequest
        from fastapi import BackgroundTasks, HTTPException
        
        bg_tasks = BackgroundTasks()
        req = RealtimePreviewRequest(video_path="nonexistent_video.mp4")
        
        with patch("pathlib.Path.exists", return_value=False):
            with pytest.raises(HTTPException) as exc_info:
                await generate_realtime_preview(bg_tasks, req)
            assert exc_info.value.status_code == 400
            assert "動画ファイルが見つかりません" in exc_info.value.detail



# ============================================================
# 2. Shorts Router (8テスト)
# ============================================================

class TestShortsRouter:
    """routers/shorts.py のテスト"""

    def test_sh_01_generate_shorts_request(self):
        """GenerateShortsRequest モデル"""
        from routers.shorts import GenerateShortsRequest
        req = GenerateShortsRequest(video_path="/test.mp4", highlights=[{"start": 0, "end": 10}])
        assert req.video_path == "/test.mp4"
        assert len(req.highlights) == 1

    def test_sh_02_export_shorts_request(self):
        """ExportShortsRequest モデル"""
        from routers.shorts import ExportShortsRequest
        req = ExportShortsRequest(clip_ids=["c1", "c2"])
        assert req.format == "mp4"
        assert len(req.clip_ids) == 2

    def test_sh_03_extract_candidates_request(self):
        """ExtractCandidatesRequest モデル"""
        from routers.shorts import ExtractCandidatesRequest
        req = ExtractCandidatesRequest(segments=[{"text": "hello"}])
        assert req.video_duration_sec == 300

    def test_sh_04_render_short_request(self):
        """RenderShortRequest モデル"""
        from routers.shorts import RenderShortRequest
        req = RenderShortRequest(video_path="/v.mp4", start_sec=5.0, end_sec=35.0)
        assert req.subtitle_text is None
        assert req.output_filename is None

    @pytest.mark.asyncio
    async def test_sh_05_health_check(self):
        """ヘルスチェック"""
        from routers.shorts import health_check
        result = await health_check()
        assert result["status"] == "ok"
        assert result["service"] == "shorts_generator"

    @pytest.mark.asyncio
    async def test_sh_06_extract_candidates_error(self):
        """extract_shorts_candidates — サービスエラー時500"""
        from routers.shorts import extract_shorts_candidates, ExtractCandidatesRequest
        from fastapi import HTTPException
        req = ExtractCandidatesRequest(segments=[])
        mock_sg = MagicMock()
        mock_sg.extract_shorts_candidates.side_effect = RuntimeError("service error")
        with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_sg)}):
            with pytest.raises(HTTPException) as exc_info:
                await extract_shorts_candidates(req)
            assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_sh_07_list_shorts_error(self):
        """list_shorts — サービスエラー時"""
        from routers.shorts import list_shorts
        from fastapi import HTTPException
        mock_sg = MagicMock()
        mock_sg.get_clip_list.side_effect = RuntimeError("no clips")
        with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_sg)}):
            with pytest.raises(HTTPException) as exc_info:
                await list_shorts(task_id="nonexistent")
            assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_sh_08_render_short_negative_duration(self):
        """render_short — duration≤0でHTTP 400"""
        from routers.shorts import render_short, RenderShortRequest
        from fastapi import HTTPException
        req = RenderShortRequest(video_path="/v.mp4", start_sec=10.0, end_sec=5.0)
        with pytest.raises(HTTPException) as exc_info:
            await render_short(req)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_sh_09_extract_candidates_success(self):
        """extract_shorts_candidates — 正常系"""
        from routers.shorts import extract_shorts_candidates, ExtractCandidatesRequest
        req = ExtractCandidatesRequest(segments=[{"text": "test"}])
        mock_sg = MagicMock()
        mock_sg.extract_shorts_candidates.return_value = {"candidates": []}
        with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_sg)}):
            result = await extract_shorts_candidates(req)
            assert result == {"candidates": []}
            mock_sg.extract_shorts_candidates.assert_called_once_with(
                segments=[{"text": "test"}],
                video_duration_sec=300,
                video_id=""
            )

    @pytest.mark.asyncio
    async def test_sh_10_extract_candidates_http_exception(self):
        """extract_shorts_candidates — HTTPException はそのままスルー"""
        from routers.shorts import extract_shorts_candidates, ExtractCandidatesRequest
        from fastapi import HTTPException
        req = ExtractCandidatesRequest(segments=[])
        mock_sg = MagicMock()
        mock_sg.extract_shorts_candidates.side_effect = HTTPException(status_code=400, detail="bad request")
        with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_sg)}):
            with pytest.raises(HTTPException) as exc_info:
                await extract_shorts_candidates(req)
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_sh_11_generate_shorts_success(self):
        """generate_shorts — 正常系"""
        from routers.shorts import generate_shorts, GenerateShortsRequest
        req = GenerateShortsRequest(video_path="v.mp4", highlights=[{"start": 0, "end": 5}])
        
        mock_clip = MagicMock()
        mock_clip.id = "c1"
        mock_clip.title = "title"
        mock_clip.highlight_type = "type"
        mock_clip.start_time = 0.0
        mock_clip.end_time = 5.0
        mock_clip.duration = 5.0
        mock_clip.output_path = "out.mp4"
        mock_clip.status = "done"

        mock_res = MagicMock()
        mock_res.total_clips = 1
        mock_res.completed_clips = 1
        mock_res.clips = [mock_clip]
        mock_res.output_dir = "out_dir"
        mock_res.message = "success"

        mock_sg = AsyncMock()
        mock_sg.generate_from_highlights.return_value = mock_res

        with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_sg)}):
            result = await generate_shorts(req)
            assert result["success"] is True
            assert result["total_clips"] == 1
            assert result["clips"][0]["id"] == "c1"
            assert result["output_dir"] == "out_dir"

    @pytest.mark.asyncio
    async def test_sh_12_generate_shorts_http_exception(self):
        """generate_shorts — HTTPException はそのままスルー"""
        from routers.shorts import generate_shorts, GenerateShortsRequest
        from fastapi import HTTPException
        req = GenerateShortsRequest(video_path="v.mp4", highlights=[])
        mock_sg = AsyncMock()
        mock_sg.generate_from_highlights.side_effect = HTTPException(status_code=403, detail="forbidden")
        with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_sg)}):
            with pytest.raises(HTTPException) as exc_info:
                await generate_shorts(req)
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_sh_13_generate_shorts_exception(self):
        """generate_shorts — 一般例外は500"""
        from routers.shorts import generate_shorts, GenerateShortsRequest
        from fastapi import HTTPException
        req = GenerateShortsRequest(video_path="v.mp4", highlights=[])
        mock_sg = AsyncMock()
        mock_sg.generate_from_highlights.side_effect = Exception("fatal error")
        with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_sg)}):
            with pytest.raises(HTTPException) as exc_info:
                await generate_shorts(req)
            assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_sh_14_list_shorts_success(self):
        """list_shorts — 正常系"""
        from routers.shorts import list_shorts
        mock_sg = MagicMock()
        mock_sg.get_clip_list.return_value = [{"id": "c1"}]
        with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_sg)}):
            result = await list_shorts(task_id="t1")
            assert result["success"] is True
            assert result["count"] == 1
            assert result["clips"] == [{"id": "c1"}]

    @pytest.mark.asyncio
    async def test_sh_15_list_shorts_http_exception(self):
        """list_shorts — HTTPException はそのままスルー"""
        from routers.shorts import list_shorts
        from fastapi import HTTPException
        mock_sg = MagicMock()
        mock_sg.get_clip_list.side_effect = HTTPException(status_code=401, detail="unauthorized")
        with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_sg)}):
            with pytest.raises(HTTPException) as exc_info:
                await list_shorts()
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_sh_16_export_shorts_success(self):
        """export_shorts — 正常系"""
        from routers.shorts import export_shorts, ExportShortsRequest
        req = ExportShortsRequest(clip_ids=["c1"], task_id="t1")
        mock_sg = MagicMock()
        mock_sg.get_clip_list.return_value = [{"id": "c1", "file": "c1.mp4"}]
        with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_sg)}):
            result = await export_shorts(req)
            assert result["success"] is True
            assert result["export_count"] == 1
            assert result["clips"] == [{"id": "c1", "file": "c1.mp4"}]

    @pytest.mark.asyncio
    async def test_sh_17_export_shorts_no_clips(self):
        """export_shorts — 指定されたクリップがない"""
        from routers.shorts import export_shorts, ExportShortsRequest
        req = ExportShortsRequest(clip_ids=["c2"], task_id="t1")
        mock_sg = MagicMock()
        mock_sg.get_clip_list.return_value = [{"id": "c1"}]
        with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_sg)}):
            result = await export_shorts(req)
            assert result["success"] is False
            assert "見つかりませんでした" in result["message"]

    @pytest.mark.asyncio
    async def test_sh_18_export_shorts_http_exception(self):
        """export_shorts — HTTPException はそのままスルー"""
        from routers.shorts import export_shorts, ExportShortsRequest
        from fastapi import HTTPException
        req = ExportShortsRequest(clip_ids=["c1"])
        mock_sg = MagicMock()
        mock_sg.get_clip_list.side_effect = HTTPException(status_code=403, detail="forbidden")
        with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_sg)}):
            with pytest.raises(HTTPException) as exc_info:
                await export_shorts(req)
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_sh_19_export_shorts_exception(self):
        """export_shorts — 一般例外は500"""
        from routers.shorts import export_shorts, ExportShortsRequest
        from fastapi import HTTPException
        req = ExportShortsRequest(clip_ids=["c1"])
        mock_sg = MagicMock()
        mock_sg.get_clip_list.side_effect = Exception("export error")
        with patch.dict("sys.modules", {"services.shorts_generator": MagicMock(shorts_generator=mock_sg)}):
            with pytest.raises(HTTPException) as exc_info:
                await export_shorts(req)
            assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_sh_20_render_short_success_with_output_filename(self, tmp_path):
        """render_short — 正常系: output_filename指定、FFmpeg成功"""
        from routers.shorts import render_short, RenderShortRequest
        req = RenderShortRequest(
            video_path="v.mp4",
            start_sec=10.0,
            end_sec=20.0,
            subtitle_text="Hello",
            output_filename="output.mp4"
        )
        
        # mock imports
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.is_available.return_value = True
        mock_ffmpeg._get_encode_args.return_value = ["-vcodec", "libx264"]
        
        # ffmpeg.run_command の side_effect でファイルを作成
        def side_effect(cmd, **kwargs):
            from pathlib import Path
            out_path = Path(cmd[-1])
            out_path.write_bytes(b"\x00" * 100)
            return True, "ffmpeg output"
        mock_ffmpeg.run_command.side_effect = side_effect
        
        mock_video_editor = MagicMock(ffmpeg=mock_ffmpeg)
        
        with patch("safe_io.VAULT_OUTPUTS_DIR", tmp_path), \
             patch.dict("sys.modules", {"video_editor_engine": MagicMock(video_editor=mock_video_editor)}):
            result = await render_short(req)
            assert result["success"] is True
            assert "output.mp4" in result["path"]
            assert result["duration_sec"] == 10.0
            assert result["resolution"] == "1080x1920"

    @pytest.mark.asyncio
    async def test_sh_21_render_short_success_no_filename_large_duration(self, tmp_path):
        """render_short — 正常系: ファイル名未指定、60秒を超えるdurationは60秒にクリップされる"""
        from routers.shorts import render_short, RenderShortRequest
        req = RenderShortRequest(
            video_path="v.mp4",
            start_sec=10.0,
            end_sec=100.0,  # duration 90s -> 60s に制限されるはず
            subtitle_text="Subtitle: Text"
        )
        
        # mock imports
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.is_available.return_value = True
        mock_ffmpeg._get_encode_args.return_value = ["-vcodec", "libx264"]
        
        # run_command が呼ばれた時に、出力先のmp4ファイルをモックで作成する
        def side_effect(cmd, **kwargs):
            out_path = cmd[-1]
            from pathlib import Path
            Path(out_path).write_bytes(b"\x00" * 50)
            return True, "ffmpeg success"
        
        mock_ffmpeg.run_command.side_effect = side_effect
        mock_video_editor = MagicMock(ffmpeg=mock_ffmpeg)
        
        with patch("safe_io.VAULT_OUTPUTS_DIR", tmp_path), \
             patch.dict("sys.modules", {"video_editor_engine": MagicMock(video_editor=mock_video_editor)}):
            result = await render_short(req)
            assert result["success"] is True
            assert result["duration_sec"] == 60.0 # 60秒に切り詰められる

    @pytest.mark.asyncio
    async def test_sh_22_render_short_ffmpeg_not_available(self, tmp_path):
        """render_short — FFmpeg利用不可の時エラー"""
        from routers.shorts import render_short, RenderShortRequest
        from fastapi import HTTPException
        req = RenderShortRequest(video_path="v.mp4", start_sec=10.0, end_sec=20.0)
        
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.is_available.return_value = False
        mock_video_editor = MagicMock(ffmpeg=mock_ffmpeg)
        
        with patch("safe_io.VAULT_OUTPUTS_DIR", tmp_path), \
             patch.dict("sys.modules", {"video_editor_engine": MagicMock(video_editor=mock_video_editor)}):
            with pytest.raises(HTTPException) as exc_info:
                await render_short(req)
            assert exc_info.value.status_code == 500
            assert "FFmpeg未検出" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_sh_23_render_short_ffmpeg_failed(self, tmp_path):
        """render_short — FFmpeg実行失敗"""
        from routers.shorts import render_short, RenderShortRequest
        from fastapi import HTTPException
        req = RenderShortRequest(video_path="v.mp4", start_sec=10.0, end_sec=20.0)
        
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.is_available.return_value = True
        mock_ffmpeg._get_encode_args.return_value = []
        mock_ffmpeg.run_command.return_value = (False, "FFmpeg error message")
        mock_video_editor = MagicMock(ffmpeg=mock_ffmpeg)
        
        with patch("safe_io.VAULT_OUTPUTS_DIR", tmp_path), \
             patch.dict("sys.modules", {"video_editor_engine": MagicMock(video_editor=mock_video_editor)}):
            with pytest.raises(HTTPException) as exc_info:
                await render_short(req)
            assert exc_info.value.status_code == 500
            assert "FFmpeg error message" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_sh_24_render_short_internal_exception(self, tmp_path):
        """render_short — 内部エラー発生"""
        from routers.shorts import render_short, RenderShortRequest
        from fastapi import HTTPException
        req = RenderShortRequest(video_path="v.mp4", start_sec=10.0, end_sec=20.0)
        
        with patch("safe_io.VAULT_OUTPUTS_DIR", tmp_path), \
             patch.dict("sys.modules", {"video_editor_engine": Exception("Severe Internal Error")}):
            with pytest.raises(HTTPException) as exc_info:
                await render_short(req)
            assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_sh_25_render_short_safe_io_import_error(self, tmp_path):
        """render_short — safe_ioのインポートエラー時に Path("output/shorts") を使用する"""
        from routers.shorts import render_short, RenderShortRequest
        from fastapi import HTTPException
        req = RenderShortRequest(video_path="v.mp4", start_sec=10.0, end_sec=20.0, output_filename="output.mp4")
        
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.is_available.return_value = True
        mock_ffmpeg._get_encode_args.return_value = []
        
        # 実際に Path("output/shorts/output.mp4") が作られるようにする
        def side_effect(cmd, **kwargs):
            from pathlib import Path
            out_file = Path("output/shorts/output.mp4")
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(b"\x00" * 100)
            return True, "success"
        
        mock_ffmpeg.run_command.side_effect = side_effect
        mock_video_editor = MagicMock(ffmpeg=mock_ffmpeg)
        
        # safe_io インポートエラーを模倣するため、sys.modules から削除するか patch で ImportError を発生させる
        def custom_import(name, *args, **kwargs):
            if name == "safe_io":
                raise ImportError("mocked import error")
            return orig_import(name, *args, **kwargs)
            
        import builtins
        orig_import = builtins.__import__
        
        with patch("builtins.__import__", side_effect=custom_import), \
             patch.dict("sys.modules", {"video_editor_engine": MagicMock(video_editor=mock_video_editor)}):
            try:
                result = await render_short(req)
                assert result["success"] is True
                assert "output/shorts" in result["path"].replace("\\", "/")
            finally:
                from pathlib import Path
                p = Path("output/shorts/output.mp4")
                if p.exists():
                    p.unlink()
                if p.parent.exists():
                    p.parent.rmdir()

    @pytest.mark.asyncio
    async def test_sh_26_thumbnail_success(self, tmp_path):
        """thumbnail — 正常系: 1280x720 16:9 サムネイル生成・品質検証・StageBoundAgent連携"""
        from routers.shorts import generate_thumbnail_api, GenerateThumbnailRequest
        db_file = tmp_path / "test_thumb.db"
        req = GenerateThumbnailRequest(
            video_path="v.mp4",
            task_id="t_api_ok",
            text="API Success",
            db_path=str(db_file)
        )
        
        from usage_tracker.alert_system import ThumbnailResolver
        orig_init = ThumbnailResolver.__init__
        def mock_init(self, project_root=None, output_dir=None):
            orig_init(self, project_root=tmp_path, output_dir=tmp_path)
            
        with patch.object(ThumbnailResolver, "__init__", mock_init):
            result = await generate_thumbnail_api(req)
            assert result["success"] is True
            assert result["task_id"] == "t_api_ok"
            assert result["status"] == "COMPLETED"
            assert result["result"]["width"] == 1280
            assert result["result"]["height"] == 720

    @pytest.mark.asyncio
    async def test_sh_27_thumbnail_validation_failure_retry(self, tmp_path):
        """thumbnail — 異常系: 無効な解像度の時にStageBoundAgentが自動リトライし最終的に失敗する"""
        from routers.shorts import generate_thumbnail_api, GenerateThumbnailRequest
        from fastapi import HTTPException
        db_file = tmp_path / "test_thumb_fail.db"
        req = GenerateThumbnailRequest(
            video_path="v.mp4",
            task_id="t_api_fail",
            text="API Fail",
            db_path=str(db_file)
        )
        
        from usage_tracker.alert_system import ThumbnailResolver
        def mock_generate(self, output_path, width=1280, height=720, text=""):
            from PIL import Image
            output_path.parent.mkdir(parents=True, exist_ok=True)
            img = Image.new("RGB", (640, 360), color=(100, 100, 100))
            img.save(output_path, "PNG")
            return output_path
            
        orig_init = ThumbnailResolver.__init__
        def mock_init(self, project_root=None, output_dir=None):
            orig_init(self, project_root=tmp_path, output_dir=tmp_path)
            
        with patch.object(ThumbnailResolver, "__init__", mock_init), \
             patch.object(ThumbnailResolver, "generate_thumbnail", mock_generate):
            with pytest.raises(HTTPException) as exc_info:
                await generate_thumbnail_api(req)
            assert exc_info.value.status_code == 500
            assert "Resolution must be at least 1280x720" in exc_info.value.detail



# ============================================================
# 3. SmartCut Router (8テスト)
# ============================================================

class TestSmartCutRouter:
    """routers/smartcut.py のテスト"""

    def test_sc_01_init_request(self):
        """InitRequest モデル"""
        from routers.smartcut import InitRequest
        req = InitRequest(segments=[{"start": 0, "end": 10, "text": "test"}])
        assert req.opening_duration == 10.0
        assert req.ending_duration == 20.0

    def test_sc_02_recommend_request(self):
        """RecommendRequest モデル"""
        from routers.smartcut import RecommendRequest
        req = RecommendRequest(target_duration_minutes=30)
        assert req.target_duration_minutes == 30

    def test_sc_03_lock_request(self):
        """LockRequest モデル"""
        from routers.smartcut import LockRequest
        req = LockRequest(segment_id="s1", title="重要", start_time=0, end_time=60)
        assert req.reason == ""

    def test_sc_04_unlock_request(self):
        """UnlockRequest モデル"""
        from routers.smartcut import UnlockRequest
        req = UnlockRequest(segment_id="s1")
        assert req.segment_id == "s1"

    @pytest.mark.asyncio
    async def test_sc_05_health_check(self):
        """ヘルスチェック"""
        from routers.smartcut import health_check
        result = await health_check()
        assert result["status"] == "ok"
        assert result["service"] == "smartcut"

    @pytest.mark.asyncio
    async def test_sc_06_recommend_not_initialized(self, monkeypatch):
        """recommend — 未初期化で400"""
        from routers.smartcut import get_recommendation, RecommendRequest
        from fastapi import HTTPException
        import routers.smartcut as sc_mod

        mock_sc = MagicMock()
        mock_sc._context = None
        monkeypatch.setattr(sc_mod, "_smart_cut_instance", mock_sc)

        req = RecommendRequest(target_duration_minutes=15)
        with pytest.raises(HTTPException) as exc_info:
            await get_recommendation(req)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_sc_07_all_candidates_not_initialized(self, monkeypatch):
        """all_candidates — 未初期化で400(HTTPException guardにより正しくリレイ)"""
        from routers.smartcut import get_all_candidates
        from fastapi import HTTPException
        import routers.smartcut as sc_mod

        mock_sc = MagicMock()
        mock_sc._context = None
        monkeypatch.setattr(sc_mod, "_smart_cut_instance", mock_sc)

        with pytest.raises(HTTPException) as exc_info:
            await get_all_candidates()
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_sc_08_finalize_not_initialized(self, monkeypatch):
        """finalize — 未初期化で400(HTTPException guardにより正しくリレイ)"""
        from routers.smartcut import finalize
        from fastapi import HTTPException
        import routers.smartcut as sc_mod

        mock_sc = MagicMock()
        mock_sc._context = None
        monkeypatch.setattr(sc_mod, "_smart_cut_instance", mock_sc)

        with pytest.raises(HTTPException) as exc_info:
            await finalize()
        assert exc_info.value.status_code == 400


# ============================================================
# 4. Segments Router (10テスト)
# ============================================================

class TestSegmentsRouter:
    """routers/segments.py のテスト"""

    @pytest.mark.asyncio
    async def test_seg_01_get_segments_no_file(self, monkeypatch):
        """get_segments — ファイル不在で空リスト"""
        from routers.segments import get_segments
        import routers.segments as seg_mod
        monkeypatch.setattr(seg_mod, "SEGMENTS_PATH", Path("/nonexistent/path.json"))
        result = await get_segments()
        assert result == []

    @pytest.mark.asyncio
    async def test_seg_02_get_segments_with_file(self, tmp_path, monkeypatch):
        """get_segments — ファイルあり"""
        from routers.segments import get_segments
        import routers.segments as seg_mod
        seg_file = tmp_path / "segments.json"
        seg_file.write_text('[{"text": "hello", "start": 0, "end": 5}]', encoding="utf-8")
        monkeypatch.setattr(seg_mod, "SEGMENTS_PATH", seg_file)
        result = await get_segments()
        assert len(result) == 1
        assert result[0]["text"] == "hello"

    @pytest.mark.asyncio
    async def test_seg_03_save_segments(self, tmp_path, monkeypatch):
        """save_segments — 保存成功"""
        from routers.segments import save_segments
        import routers.segments as seg_mod
        seg_file = tmp_path / "segments.json"
        monkeypatch.setattr(seg_mod, "SEGMENTS_PATH", seg_file)

        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value=[
            {"text": "test1", "start": 0, "end": 5},
            {"text": "test2", "start": 5, "end": 10},
        ])
        result = await save_segments(mock_request)
        assert result["status"] == "saved"
        assert result["count"] == 2
        assert seg_file.exists()

    @pytest.mark.asyncio
    async def test_seg_04_export_subtitles_vtt(self):
        """export_subtitles — VTT形式"""
        from routers.segments import export_subtitles
        subtitles = [
            {"text": "こんにちは", "start": 0.0, "end": 5.0},
            {"text": "テスト", "start": 5.0, "end": 10.0},
        ]
        result = await export_subtitles("vtt", subtitles)
        assert result.media_type == "text/vtt"

    @pytest.mark.asyncio
    async def test_seg_05_export_subtitles_srt(self):
        """export_subtitles — SRT形式"""
        from routers.segments import export_subtitles
        subtitles = [
            {"text": "テスト字幕", "start": 1.5, "end": 4.2},
        ]
        result = await export_subtitles("srt", subtitles)
        assert result.media_type == "text/plain"

    @pytest.mark.asyncio
    async def test_seg_06_export_subtitles_unsupported(self):
        """export_subtitles — 未対応形式"""
        from routers.segments import export_subtitles
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await export_subtitles("ass", [])
        assert exc_info.value.status_code == 400
        assert "Unsupported format" in exc_info.value.detail

    def test_seg_07_format_time_vtt(self):
        """_format_time_vtt — タイムスタンプ"""
        from routers.segments import _format_time_vtt
        assert _format_time_vtt(0.0) == "00:00:00.000"
        assert _format_time_vtt(65.5) == "00:01:05.500"
        assert _format_time_vtt(3661.123) == "01:01:01.123"

    def test_seg_08_format_time_srt(self):
        """_format_time_srt — タイムスタンプ"""
        from routers.segments import _format_time_srt
        assert _format_time_srt(0.0) == "00:00:00,000"
        assert _format_time_srt(65.5) == "00:01:05,500"
        assert _format_time_srt(3661.123) == "01:01:01,123"

    def test_seg_09_format_time_vtt_large(self):
        """_format_time_vtt — 大きな値"""
        from routers.segments import _format_time_vtt
        result = _format_time_vtt(7200.0)
        assert result.startswith("02:00:")

    def test_seg_10_format_time_srt_edge(self):
        """_format_time_srt — 境界値"""
        from routers.segments import _format_time_srt
        result = _format_time_srt(59.999)
        assert "00:00:59" in result

    @pytest.mark.asyncio
    async def test_seg_11_transcribe_video_success(self, tmp_path, monkeypatch):
        """transcribe_video — 正常系"""
        from routers.segments import transcribe_video
        from fastapi import UploadFile
        import io

        mock_file = UploadFile(
            file=io.BytesIO(b"dummy video content"),
            filename="test_video.mp4"
        )

        mock_transcriber = MagicMock()
        mock_transcriber.transcribe.return_value = {"segments": [{"text": "hello"}]}

        with patch("subtitle_engine.transcriber.transcriber", mock_transcriber):
            result = await transcribe_video(mock_file)
            assert result == {"segments": [{"text": "hello"}]}
            mock_transcriber.transcribe.assert_called_once()

    @pytest.mark.asyncio
    async def test_seg_12_transcribe_video_value_error(self, tmp_path, monkeypatch):
        """transcribe_video — ValueError発生時にHTTP 400"""
        from routers.segments import transcribe_video
        from fastapi import UploadFile, HTTPException
        import io

        mock_file = UploadFile(
            file=io.BytesIO(b"dummy"),
            filename="invalid.mp4"
        )

        mock_transcriber = MagicMock()
        mock_transcriber.transcribe.side_effect = ValueError("Invalid audio format")

        with patch("subtitle_engine.transcriber.transcriber", mock_transcriber):
            with pytest.raises(HTTPException) as exc_info:
                await transcribe_video(mock_file)
            assert exc_info.value.status_code == 400
            assert "Invalid audio format" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_seg_13_transcribe_video_runtime_error(self, tmp_path, monkeypatch):
        """transcribe_video — RuntimeError発生時にHTTP 500"""
        from routers.segments import transcribe_video
        from fastapi import UploadFile, HTTPException
        import io

        mock_file = UploadFile(
            file=io.BytesIO(b"dummy"),
            filename="error.mp4"
        )

        mock_transcriber = MagicMock()
        mock_transcriber.transcribe.side_effect = RuntimeError("Engine failure")

        with patch("subtitle_engine.transcriber.transcriber", mock_transcriber):
            with pytest.raises(HTTPException) as exc_info:
                await transcribe_video(mock_file)
            assert exc_info.value.status_code == 500
            assert "Speech recognition engine error" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_seg_14_transcribe_video_type_error(self, tmp_path, monkeypatch):
        """transcribe_video — TypeError（構造エラー）発生時にHTTP 500"""
        from routers.segments import transcribe_video
        from fastapi import UploadFile, HTTPException
        import io

        mock_file = UploadFile(
            file=io.BytesIO(b"dummy"),
            filename="error.mp4"
        )

        mock_transcriber = MagicMock()
        mock_transcriber.transcribe.side_effect = TypeError("Invalid argument type")

        with patch("subtitle_engine.transcriber.transcriber", mock_transcriber):
            with pytest.raises(HTTPException) as exc_info:
                await transcribe_video(mock_file)
            assert exc_info.value.status_code == 500
            assert "Transcription processing error" in exc_info.value.detail

    def test_seg_15_subtitle_segment_validation_negative_start(self):
        """SubtitleSegment — startが負数の場合にValidationError"""
        from routers.segments import SubtitleSegment
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            SubtitleSegment(text="hello", start=-1.0, end=5.0)

    def test_seg_16_subtitle_segment_validation_end_before_start(self):
        """SubtitleSegment — end < start の場合にValidationError"""
        from routers.segments import SubtitleSegment
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            SubtitleSegment(text="hello", start=5.0, end=2.0)

    @pytest.mark.asyncio
    async def test_seg_17_save_segments_validation_error(self, tmp_path, monkeypatch):
        """save_segments — バリデーションエラー時にHTTP 400"""
        from routers.segments import save_segments
        import routers.segments as seg_mod
        seg_file = tmp_path / "segments.json"
        monkeypatch.setattr(seg_mod, "SEGMENTS_PATH", seg_file)

        mock_request = MagicMock()
        # end < start の無効なデータを送る
        mock_request.json = AsyncMock(return_value=[
            {"text": "invalid", "start": 5.0, "end": 2.0},
        ])
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await save_segments(mock_request)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_seg_18_export_subtitles_validation_error(self):
        """export_subtitles — バリデーションエラー時にHTTP 400"""
        from routers.segments import export_subtitles
        from fastapi import HTTPException
        # startが負数の無効なデータ
        subtitles = [
            {"text": "invalid", "start": -1.0, "end": 5.0},
        ]
        with pytest.raises(HTTPException) as exc_info:
            await export_subtitles("vtt", subtitles)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_seg_19_export_subtitles_non_list(self):
        """export_subtitles — subtitlesがリストではない場合にHTTP 400"""
        from routers.segments import export_subtitles
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await export_subtitles("vtt", "not-a-list")
        assert exc_info.value.status_code == 400
        assert "Subtitles parameter must be a JSON array" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_seg_20_get_segments_invalid_structure(self, tmp_path, monkeypatch):
        """get_segments — ファイルの中身がリストではない場合にHTTP 500"""
        from routers.segments import get_segments
        import routers.segments as seg_mod
        seg_file = tmp_path / "segments.json"
        seg_file.write_text('{"text": "not-a-list-but-dict"}', encoding="utf-8")
        monkeypatch.setattr(seg_mod, "SEGMENTS_PATH", seg_file)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await get_segments()
        assert exc_info.value.status_code == 500
        assert "Invalid data structure" in exc_info.value.detail


# ============================================================
# 5. WebSocket Router (8テスト)
# ============================================================

class TestWebSocketRouter:
    """routers/websocket.py のテスト"""

    def test_ws_01_connection_manager_init(self):
        """ConnectionManager — 初期化"""
        from routers.websocket import ConnectionManager
        mgr = ConnectionManager()
        assert mgr.active_connections == []

    @pytest.mark.asyncio
    async def test_ws_02_connection_manager_connect(self):
        """ConnectionManager — connect"""
        from routers.websocket import ConnectionManager
        mgr = ConnectionManager()
        mock_ws = AsyncMock()
        await mgr.connect(mock_ws)
        assert len(mgr.active_connections) == 1
        mock_ws.accept.assert_called_once()

    def test_ws_03_connection_manager_disconnect(self):
        """ConnectionManager — disconnect"""
        from routers.websocket import ConnectionManager
        mgr = ConnectionManager()
        mock_ws = MagicMock()
        mgr.active_connections.append(mock_ws)
        mgr.disconnect(mock_ws)
        assert len(mgr.active_connections) == 0

    def test_ws_04_disconnect_nonexistent(self):
        """ConnectionManager — 存在しない接続のdisconnect"""
        from routers.websocket import ConnectionManager
        mgr = ConnectionManager()
        mock_ws = MagicMock()
        mgr.disconnect(mock_ws)  # エラーにならない
        assert len(mgr.active_connections) == 0

    @pytest.mark.asyncio
    async def test_ws_05_broadcast_single(self):
        """ConnectionManager — 1接続へのブロードキャスト"""
        from routers.websocket import ConnectionManager
        mgr = ConnectionManager()
        mock_ws = AsyncMock()
        mgr.active_connections.append(mock_ws)
        await mgr.broadcast({"type": "test", "data": "hello"})
        mock_ws.send_json.assert_called_once_with({"type": "test", "data": "hello"})

    @pytest.mark.asyncio
    async def test_ws_06_broadcast_multiple(self):
        """ConnectionManager — 複数接続へのブロードキャスト"""
        from routers.websocket import ConnectionManager
        mgr = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        mgr.active_connections.extend([ws1, ws2])
        await mgr.broadcast({"type": "progress", "value": 50})
        ws1.send_json.assert_called_once()
        ws2.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_ws_07_broadcast_with_error(self):
        """ConnectionManager — 送信エラー時もクラッシュしない"""
        from routers.websocket import ConnectionManager
        mgr = ConnectionManager()
        ws_good = AsyncMock()
        ws_bad = AsyncMock()
        ws_bad.send_json.side_effect = Exception("Connection lost")
        mgr.active_connections.extend([ws_bad, ws_good])
        await mgr.broadcast({"type": "test"})
        ws_good.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_ws_08_broadcast_progress_function(self):
        """broadcast_progress — グローバル関数"""
        from routers.websocket import broadcast_progress, manager
        mock_ws = AsyncMock()
        manager.active_connections.append(mock_ws)
        try:
            await broadcast_progress({"type": "progress", "value": 100})
            mock_ws.send_json.assert_called_once()
        finally:
            manager.active_connections.remove(mock_ws)
