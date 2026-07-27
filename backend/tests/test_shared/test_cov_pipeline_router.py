"""
Sprint 3.7.2 Batch A — pipeline_router.py カバレッジ改善テスト
対象: missing 140行
重点: O-2/O-3/O-6/O-7 APIエンドポイント, stream_video, force_render,
      _merge_videos, _format_duration, _format_srt_time, dictionary CRUD
"""
import pytest
import json
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from pathlib import Path
from types import SimpleNamespace


# ============================================================
# _format_duration / _format_srt_time ユーティリティ
# ============================================================

class TestFormatDuration:
    def test_hours_format(self):
        from routers.pipeline_router import _format_duration
        assert _format_duration(3661) == "1:01:01"

    def test_minutes_only(self):
        from routers.pipeline_router import _format_duration
        assert _format_duration(125) == "2:05"

    def test_zero(self):
        from routers.pipeline_router import _format_duration
        assert _format_duration(0) == "0:00"


class TestFormatSrtTime:
    def test_basic(self):
        from routers.pipeline_router import _format_srt_time
        assert _format_srt_time(3661.5) == "01:01:01,500"

    def test_zero(self):
        from routers.pipeline_router import _format_srt_time
        assert _format_srt_time(0) == "00:00:00,000"


# ============================================================
# O-2: 文字起こし API
# ============================================================

@pytest.fixture
def pipeline_client():
    """FastAPI TestClient for pipeline_router"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.pipeline_router import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestTranscriptionAPI:
    def test_get_whisper_models(self, pipeline_client):
        resp = pipeline_client.get("/api/pipeline/transcription/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "models" in data
        assert len(data["models"]) == 5
        assert "recommended" in data

    def test_get_segments_default(self, pipeline_client):
        resp = pipeline_client.get("/api/pipeline/transcription/segments")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
        assert "segments" in data

    def test_update_segment_success(self, pipeline_client):
        # Ensure segments exist
        pipeline_client.get("/api/pipeline/transcription/segments")
        resp = pipeline_client.put(
            "/api/pipeline/transcription/segments/0",
            json={"text": "更新テキスト"}
        )
        assert resp.status_code == 200
        assert resp.json()["new_text"] == "更新テキスト"

    def test_update_segment_not_found(self, pipeline_client):
        resp = pipeline_client.put(
            "/api/pipeline/transcription/segments/999",
            json={"text": "存在しない"}
        )
        assert resp.status_code == 404

    def test_get_transcription_status(self, pipeline_client):
        resp = pipeline_client.get("/api/pipeline/transcription/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "progress" in data

    def test_set_model_valid(self, pipeline_client):
        resp = pipeline_client.post(
            "/api/pipeline/transcription/model",
            json={"model": "small"}
        )
        assert resp.status_code == 200
        assert resp.json()["model"] == "small"

    def test_set_model_invalid(self, pipeline_client):
        resp = pipeline_client.post(
            "/api/pipeline/transcription/model",
            json={"model": "nonexistent"}
        )
        assert resp.status_code == 400


# ============================================================
# O-3: AI校閲 API
# ============================================================

class TestProofreadingAPI:
    def test_get_result_default(self, pipeline_client):
        resp = pipeline_client.get("/api/pipeline/proofreading/result")
        assert resp.status_code == 200
        data = resp.json()
        assert "segments" in data
        assert "approved_count" in data
        assert "pending_count" in data

    def test_approve_segment(self, pipeline_client):
        pipeline_client.get("/api/pipeline/proofreading/result")
        resp = pipeline_client.post(
            "/api/pipeline/proofreading/approve",
            json={"segment_id": 0}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

    def test_approve_segment_not_found(self, pipeline_client):
        resp = pipeline_client.post(
            "/api/pipeline/proofreading/approve",
            json={"segment_id": 999}
        )
        assert resp.status_code == 404

    def test_reject_segment(self, pipeline_client):
        pipeline_client.get("/api/pipeline/proofreading/result")
        resp = pipeline_client.post(
            "/api/pipeline/proofreading/reject",
            json={"segment_id": 1}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

    def test_reject_segment_not_found(self, pipeline_client):
        resp = pipeline_client.post(
            "/api/pipeline/proofreading/reject",
            json={"segment_id": 999}
        )
        assert resp.status_code == 404

    def test_approve_all(self, pipeline_client):
        pipeline_client.get("/api/pipeline/proofreading/result")
        resp = pipeline_client.post("/api/pipeline/proofreading/approve-all")
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved_all"

    def test_reject_all(self, pipeline_client):
        pipeline_client.get("/api/pipeline/proofreading/result")
        resp = pipeline_client.post("/api/pipeline/proofreading/reject-all")
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected_all"

    def test_get_status(self, pipeline_client):
        resp = pipeline_client.get("/api/pipeline/proofreading/status")
        assert resp.status_code == 200
        assert "total_segments" in resp.json()

    def test_toggle_skip(self, pipeline_client):
        resp = pipeline_client.post(
            "/api/pipeline/proofreading/skip",
            json={"skip": True}
        )
        assert resp.status_code == 200
        assert resp.json()["skip"] is True

    def test_export_srt(self, pipeline_client):
        pipeline_client.get("/api/pipeline/proofreading/result")
        resp = pipeline_client.get("/api/pipeline/proofreading/export/srt")
        assert resp.status_code == 200
        assert "-->" in resp.text

    def test_export_txt(self, pipeline_client):
        pipeline_client.get("/api/pipeline/proofreading/result")
        resp = pipeline_client.get("/api/pipeline/proofreading/export/txt")
        assert resp.status_code == 200

    def test_export_invalid_format(self, pipeline_client):
        pipeline_client.get("/api/pipeline/proofreading/result")
        resp = pipeline_client.get("/api/pipeline/proofreading/export/pdf")
        assert resp.status_code == 400

    def test_export_no_segments(self, pipeline_client):
        from routers.pipeline_router import _proofreading_state
        old = _proofreading_state["segments"]
        _proofreading_state["segments"] = []
        try:
            resp = pipeline_client.get("/api/pipeline/proofreading/export/srt")
            assert resp.status_code == 404
        finally:
            _proofreading_state["segments"] = old


# ============================================================
# O-6: 品質チェック API
# ============================================================

class TestQualityGateAPI:
    def test_get_status(self, pipeline_client):
        resp = pipeline_client.get("/api/pipeline/quality-gate/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "overall_score" in data
        assert "passed" in data

    def test_get_scores(self, pipeline_client):
        resp = pipeline_client.get("/api/pipeline/quality-gate/scores")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["categories"]) == 4
        for cat in data["categories"]:
            assert "weighted_score" in cat

    def test_drilldown_valid(self, pipeline_client):
        resp = pipeline_client.get("/api/pipeline/quality-gate/drilldown/audio")
        assert resp.status_code == 200
        assert resp.json()["category"] == "audio"

    def test_drilldown_invalid(self, pipeline_client):
        resp = pipeline_client.get("/api/pipeline/quality-gate/drilldown/nonexistent")
        assert resp.status_code == 404

    def test_improve_all(self, pipeline_client):
        resp = pipeline_client.post(
            "/api/pipeline/quality-gate/improve",
            json={}
        )
        assert resp.status_code == 200
        assert "suggestions" in resp.json()

    def test_improve_specific_category(self, pipeline_client):
        resp = pipeline_client.post(
            "/api/pipeline/quality-gate/improve",
            json={"category": "video"}
        )
        assert resp.status_code == 200

    def test_get_history(self, pipeline_client):
        resp = pipeline_client.get("/api/pipeline/quality-gate/history")
        assert resp.status_code == 200
        data = resp.json()
        assert "history" in data
        assert "improvement" in data

    def test_run_check(self, pipeline_client):
        resp = pipeline_client.post("/api/pipeline/quality-gate/check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("passed", "failed")
        assert "overall_score" in data


# ============================================================
# O-7: 改善ループ API
# ============================================================

class TestImprovementAPI:
    def test_get_status(self, pipeline_client):
        resp = pipeline_client.get("/api/pipeline/improvement/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "iteration" in data
        assert "completed_actions" in data

    def test_get_actions(self, pipeline_client):
        resp = pipeline_client.get("/api/pipeline/improvement/actions")
        assert resp.status_code == 200
        assert "actions" in resp.json()

    def test_apply_action_success(self, pipeline_client):
        # Reset first
        pipeline_client.post("/api/pipeline/improvement/reset")
        resp = pipeline_client.post("/api/pipeline/improvement/apply/act-001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "applied"
        assert data["improvement"] > 0

    def test_apply_action_already_applied(self, pipeline_client):
        # act-001 was applied above, apply again
        resp = pipeline_client.post("/api/pipeline/improvement/apply/act-001")
        assert resp.status_code == 400

    def test_apply_action_not_found(self, pipeline_client):
        resp = pipeline_client.post("/api/pipeline/improvement/apply/nonexistent")
        assert resp.status_code == 404

    def test_score_change(self, pipeline_client):
        resp = pipeline_client.get("/api/pipeline/improvement/score-change")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_improvement" in data
        assert "score_history" in data

    def test_abort(self, pipeline_client):
        pipeline_client.post("/api/pipeline/improvement/reset")
        resp = pipeline_client.post("/api/pipeline/improvement/abort")
        assert resp.status_code == 200
        assert resp.json()["status"] == "aborted"

    def test_abort_already_aborted(self, pipeline_client):
        resp = pipeline_client.post("/api/pipeline/improvement/abort")
        assert resp.status_code == 200
        assert resp.json()["status"] == "already_aborted"

    def test_reset(self, pipeline_client):
        resp = pipeline_client.post("/api/pipeline/improvement/reset")
        assert resp.status_code == 200
        assert resp.json()["status"] == "reset"


# ============================================================
# stream_video エンドポイント分岐
# ============================================================

class TestStreamVideo:
    def test_stream_preview_success(self, pipeline_client, tmp_path):
        from routers.pipeline_router import _pipeline_state
        f = tmp_path / "preview.mp4"
        f.write_bytes(b"\x00" * 2048)
        _pipeline_state["result"] = {"preview_path": str(f)}
        resp = pipeline_client.get("/api/pipeline/stream/preview")
        assert resp.status_code == 200
        assert len(resp.content) == 2048

    def test_stream_with_range(self, pipeline_client, tmp_path):
        from routers.pipeline_router import _pipeline_state
        f = tmp_path / "preview.mp4"
        f.write_bytes(b"\x00" * 4096)
        _pipeline_state["result"] = {"preview_path": str(f)}
        resp = pipeline_client.get(
            "/api/pipeline/stream/preview",
            headers={"Range": "bytes=0-1023"}
        )
        assert resp.status_code == 206
        assert len(resp.content) == 1024

    def test_stream_file_not_found(self, pipeline_client):
        from routers.pipeline_router import _pipeline_state
        _pipeline_state["result"] = {"preview_path": "/nonexistent.mp4"}
        resp = pipeline_client.get("/api/pipeline/stream/preview")
        assert resp.status_code == 404


# ============================================================
# force_render エンドポイント
# ============================================================

class TestForceRender:
    def test_not_completed(self, pipeline_client):
        from routers.pipeline_router import _pipeline_state
        _pipeline_state["status"] = "idle"
        resp = pipeline_client.post(
            "/api/pipeline/force-render",
            json={"reason": "test"}
        )
        assert resp.status_code == 400

    def test_no_quality_report(self, pipeline_client):
        from routers.pipeline_router import _pipeline_state
        _pipeline_state["status"] = "completed"
        _pipeline_state["result"] = {}
        resp = pipeline_client.post(
            "/api/pipeline/force-render",
            json={"reason": "test"}
        )
        assert resp.status_code == 400

    def test_preview_not_found(self, pipeline_client):
        from routers.pipeline_router import _pipeline_state
        _pipeline_state["status"] = "completed"
        _pipeline_state["result"] = {
            "quality_gate_report": {"score": 70},
            "preview_path": "/nonexistent.mp4"
        }
        resp = pipeline_client.post(
            "/api/pipeline/force-render",
            json={"reason": "test"}
        )
        assert resp.status_code == 404


# ============================================================
# Dictionary CRUD
# ============================================================

class TestDictionaryAPI:
    def test_get_dictionary_import_error(self, pipeline_client):
        with patch.dict("sys.modules", {"proper_noun_dict": None}):
            resp = pipeline_client.get("/api/pipeline/dictionary")
            assert resp.status_code == 200
            # Falls back to error response
            data = resp.json()
            assert "entries" in data or "error" in data


# ============================================================
# validate_videos エンドポイント
# ============================================================

class TestValidateVideos:
    def test_file_not_exists(self, pipeline_client):
        resp = pipeline_client.post(
            "/api/pipeline/videos/validate",
            json={"video_paths": ["/nonexistent.mp4"]}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["invalid"] == 1

    def test_empty_file(self, pipeline_client, tmp_path):
        f = tmp_path / "empty.mp4"
        f.write_bytes(b"")
        resp = pipeline_client.post(
            "/api/pipeline/videos/validate",
            json={"video_paths": [str(f)]}
        )
        assert resp.status_code == 200
        assert resp.json()["results"][0]["valid"] is False

    def test_tiny_file(self, pipeline_client, tmp_path):
        f = tmp_path / "tiny.mp4"
        f.write_bytes(b"\x00" * 100)
        resp = pipeline_client.post(
            "/api/pipeline/videos/validate",
            json={"video_paths": [str(f)]}
        )
        assert resp.status_code == 200
        assert resp.json()["results"][0]["valid"] is False


# ============================================================
# video metadata
# ============================================================

class TestVideoMetadata:
    def test_file_not_found(self, pipeline_client):
        resp = pipeline_client.post(
            "/api/pipeline/videos/metadata",
            json={"video_path": "/nonexistent.mp4"}
        )
        assert resp.status_code == 404

    def test_empty_file(self, pipeline_client, tmp_path):
        f = tmp_path / "empty.mp4"
        f.write_bytes(b"")
        resp = pipeline_client.post(
            "/api/pipeline/videos/metadata",
            json={"video_path": str(f)}
        )
        assert resp.status_code == 400


# ============================================================
# PipelineWSManager
# ============================================================

class TestPipelineWSManager:
    def test_disconnect_removes(self):
        from routers.pipeline_router import PipelineWSManager
        mgr = PipelineWSManager()
        ws = MagicMock()
        mgr.connections.append(ws)
        mgr.disconnect(ws)
        assert ws not in mgr.connections

    def test_disconnect_not_present(self):
        from routers.pipeline_router import PipelineWSManager
        mgr = PipelineWSManager()
        mgr.disconnect(MagicMock())  # should not raise

    @pytest.mark.asyncio
    async def test_broadcast_removes_dead(self):
        from routers.pipeline_router import PipelineWSManager
        mgr = PipelineWSManager()
        dead_ws = AsyncMock()
        dead_ws.send_json.side_effect = Exception("dead")
        mgr.connections.append(dead_ws)
        await mgr.broadcast({"type": "test"})
        assert dead_ws not in mgr.connections

    @pytest.mark.asyncio
    async def test_broadcast_raises_http_exception(self):
        from routers.pipeline_router import PipelineWSManager
        from fastapi import HTTPException
        mgr = PipelineWSManager()
        err_ws = AsyncMock()
        err_ws.send_json.side_effect = HTTPException(status_code=400, detail="bad request")
        mgr.connections.append(err_ws)
        with pytest.raises(HTTPException):
            await mgr.broadcast({"type": "test"})


# ============================================================
# Phase 7: カオス耐性・ロバストネス向上検証テスト
# ============================================================

import subprocess
from datetime import datetime, timedelta

class TestChaosRobustness:
    def test_force_reset_endpoint(self, pipeline_client):
        from routers.pipeline_router import _pipeline_state
        _pipeline_state["status"] = "running"
        _pipeline_state["session_id"] = "test_chaos_session"
        
        # force-reset を実行
        resp = pipeline_client.post("/api/pipeline/force-reset")
        assert resp.status_code == 200
        assert resp.json()["status"] == "reset_success"
        
        # 状態が idle に戻っていることを確認
        assert _pipeline_state["status"] == "idle"
        assert _pipeline_state["session_id"] is None

    def test_status_zombie_auto_recovery(self, pipeline_client):
        from routers.pipeline_router import _pipeline_state
        _pipeline_state["status"] = "running"
        # 2時間前に開始されたゾンビ状態をシミュレート
        two_hours_ago = (datetime.now() - timedelta(hours=2)).isoformat()
        _pipeline_state["started_at"] = two_hours_ago
        _pipeline_state["error"] = None
        
        # status にアクセスすると自動で修復（error）に遷移するはず
        resp = pipeline_client.get("/api/pipeline/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "ゾンビプロセス検知" in data["error"]

    def test_status_running_not_expired(self, pipeline_client):
        from routers.pipeline_router import _pipeline_state
        _pipeline_state["status"] = "running"
        # 10分前に開始された正常な実行をシミュレート
        ten_mins_ago = (datetime.now() - timedelta(minutes=10)).isoformat()
        _pipeline_state["started_at"] = ten_mins_ago
        _pipeline_state["error"] = None
        
        resp = pipeline_client.get("/api/pipeline/status")
        assert resp.status_code == 200
        data = resp.json()
        # タイムアウトしていないので running のまま
        assert data["status"] == "running"
        assert data["error"] is None

    @pytest.mark.asyncio
    async def test_ffprobe_timeout_in_merge_videos(self, tmp_path):
        from routers.pipeline_router import _merge_videos
        from fastapi import HTTPException
        
        f1 = tmp_path / "video1.mp4"
        f1.write_bytes(b"\x00" * 20480)
        f2 = tmp_path / "video2.mp4"
        f2.write_bytes(b"\x00" * 20480)
        
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ffprobe", timeout=30)):
            with pytest.raises(HTTPException) as excinfo:
                await _merge_videos([str(f1), str(f2)])
            assert excinfo.value.status_code == 500

    def test_ffprobe_timeout_in_metadata(self, pipeline_client, tmp_path):
        f = tmp_path / "timeout.mp4"
        f.write_bytes(b"\x00" * 20480)
        
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ffprobe", timeout=30)):
            resp = pipeline_client.post(
                "/api/pipeline/videos/metadata",
                json={"video_path": str(f)}
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["probe_success"] is False
            assert "timeout expired" in data["probe_error"]

    def test_ffprobe_timeout_in_validate(self, pipeline_client, tmp_path):
        f = tmp_path / "timeout_validate.mp4"
        f.write_bytes(b"\x00" * 20480)
        
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ffprobe", timeout=15)):
            resp = pipeline_client.post(
                "/api/pipeline/videos/validate",
                json={"video_paths": [str(f)]}
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["invalid"] == 1
            assert "検証タイムアウト" in data["results"][0]["errors"][0]
    def test_probe_video_metadata_success(self):
        from routers.pipeline_router import _probe_video_metadata
        mock_stdout = '{"streams": [{"codec_type": "video", "width": 1280, "height": 720, "r_frame_rate": "30/1"}]}'
        mock_process = MagicMock()
        mock_process.stdout = mock_stdout
        with patch("subprocess.run", return_value=mock_process):
            res = _probe_video_metadata("dummy.mp4", "dummy_ffmpeg")
            assert res == {"width": 1280, "height": 720, "fps": 30.0}

    def test_probe_video_metadata_invalid_fps(self):
        from routers.pipeline_router import _probe_video_metadata
        # FPSのパースで ZeroDivisionError を引き起こすような r_frame_rate: "30/0"
        mock_stdout = '{"streams": [{"codec_type": "video", "width": 1280, "height": 720, "r_frame_rate": "30/0"}]}'
        mock_process = MagicMock()
        mock_process.stdout = mock_stdout
        with patch("subprocess.run", return_value=mock_process):
            res = _probe_video_metadata("dummy.mp4", "dummy_ffmpeg")
            assert res == {"width": 1280, "height": 720, "fps": 30.0}

    def test_probe_video_metadata_exception(self):
        from routers.pipeline_router import _probe_video_metadata
        with patch("subprocess.run", side_effect=OSError("Permission denied")):
            res = _probe_video_metadata("dummy.mp4", "dummy_ffmpeg")
            assert res == {"width": 0, "height": 0, "fps": 30.0}

    def test_probe_video_metadata_ffprobe_fallback(self):
        from routers.pipeline_router import _probe_video_metadata
        # Path.exists() を Mock して False を返すことで fallback_path = "ffprobe" を通す
        mock_stdout = '{"streams": [{"codec_type": "video", "width": 640, "height": 360, "r_frame_rate": "24/1"}]}'
        mock_process = MagicMock()
        mock_process.stdout = mock_stdout
        with patch("pathlib.Path.exists", return_value=False):
            with patch("subprocess.run", return_value=mock_process) as mock_run:
                res = _probe_video_metadata("dummy.mp4", "dummy_ffmpeg")
                assert res == {"width": 640, "height": 360, "fps": 24.0}
                # 呼び出された ffprobe コマンドを確認
                called_args = mock_run.call_args[0][0]
                assert called_args[0] == "ffprobe"

    def test_probe_video_metadata_no_video_stream(self):
        from routers.pipeline_router import _probe_video_metadata
        # ビデオストリームが含まれず、オーディオストリームのみが含まれるJSON
        mock_stdout = '{"streams": [{"codec_type": "audio", "sample_rate": "44100"}]}'
        mock_process = MagicMock()
        mock_process.stdout = mock_stdout
        with patch("subprocess.run", return_value=mock_process):
            res = _probe_video_metadata("dummy.mp4", "dummy_ffmpeg")
            assert res == {"width": 0, "height": 0, "fps": 30.0}

    @pytest.mark.asyncio
    async def test_run_pipeline_background_http_exception(self):
        from routers.pipeline_router import _run_pipeline_background, _pipeline_state
        from fastapi import HTTPException

        _pipeline_state["status"] = "running"
        _pipeline_state["session_id"] = "test_session_id"
        _pipeline_state["error"] = None

        with patch("agents.pipeline_coordinator.pipeline_coordinator.execute", side_effect=HTTPException(status_code=400, detail="Coord error")):
            await _run_pipeline_background("dummy.mp4", 20)

        assert _pipeline_state["status"] == "error"
        assert _pipeline_state["error"] == "Coord error"

    @pytest.mark.asyncio
    async def test_merge_and_run_pipeline_http_exception(self, tmp_path):
        from routers.pipeline_router import _merge_and_run_pipeline, _pipeline_state
        from fastapi import HTTPException

        _pipeline_state["status"] = "running"
        _pipeline_state["error"] = None

        f1 = tmp_path / "v1.mp4"
        f1.write_bytes(b"\x00" * 1024)
        f2 = tmp_path / "v2.mp4"
        f2.write_bytes(b"\x00" * 1024)

        with patch("routers.pipeline_router._merge_videos", side_effect=HTTPException(status_code=500, detail="Merge timeout")):
            with patch("routers.pipeline_router._ensure_disk_space"):
                await _merge_and_run_pipeline([str(f1), str(f2)], 20)

        assert _pipeline_state["status"] == "error"
        assert _pipeline_state["error"] == "Merge timeout"

