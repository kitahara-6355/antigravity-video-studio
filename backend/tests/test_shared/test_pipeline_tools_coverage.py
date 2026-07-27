import pytest
import json
from unittest.mock import patch, MagicMock, AsyncMock
from harness.tool_registry import tool_registry
from harness.pipeline_tools import register_pipeline_tools

class DummyResult:
    def __init__(self, success=True, detail="OK", data=None, duration_seconds=1.0):
        self.success = success
        self.detail = detail
        self.data = data or {}
        self.duration_seconds = duration_seconds

@pytest.fixture(autouse=True)
def setup_tools():
    # ツール登録を確実に実行
    register_pipeline_tools()

@pytest.mark.asyncio
async def test_transcribe_video_tool_success():
    dummy_res = DummyResult(success=True, detail="Transcribe completed", data={"segment_count": 10}, duration_seconds=5.0)
    
    async def mock_execute(ctx):
        ctx.segments = [{"start": 0.0, "end": 2.0, "text": "Hello"}]
        return dummy_res

    with patch("agents.pipeline_coordinator.TranscribeWorker") as mock_worker_cls:
        mock_worker = MagicMock()
        mock_worker.execute = AsyncMock(side_effect=mock_execute)
        mock_worker_cls.return_value = mock_worker

        result = await tool_registry.execute(
            "transcribe_video",
            {"video_path": "/absolute/path/to/video.mp4", "target_minutes": 10}
        )
        
        assert result.is_error is False
        data = json.loads(result.content[0]["text"])
        assert data["success"] is True
        assert data["segment_count"] == 10
        assert len(data["segments"]) == 1
        assert data["segments"][0]["text"] == "Hello"

@pytest.mark.asyncio
async def test_transcribe_video_tool_failure():
    dummy_res = DummyResult(success=False, detail="Transcribe failed", data={}, duration_seconds=2.0)
    
    with patch("agents.pipeline_coordinator.TranscribeWorker") as mock_worker_cls:
        mock_worker = MagicMock()
        mock_worker.execute = AsyncMock(return_value=dummy_res)
        mock_worker_cls.return_value = mock_worker

        result = await tool_registry.execute(
            "transcribe_video",
            {"video_path": "/absolute/path/to/video.mp4"}
        )
        
        assert result.is_error is True
        data = json.loads(result.content[0]["text"])
        assert data["success"] is False
        assert data["detail"] == "Transcribe failed"

@pytest.mark.asyncio
async def test_proofread_subtitles_tool_success():
    dummy_res = DummyResult(success=True, detail="Proofread completed", data={"corrections_count": 2}, duration_seconds=1.5)
    
    with patch("agents.pipeline_coordinator.ProofreadWorker") as mock_worker_cls:
        mock_worker = MagicMock()
        mock_worker.execute = AsyncMock(return_value=dummy_res)
        mock_worker_cls.return_value = mock_worker

        result = await tool_registry.execute(
            "proofread_subtitles",
            {
                "video_path": "/absolute/path/to/video.mp4",
                "segments": [{"start": 0, "end": 1, "text": "test"}]
            }
        )
        
        assert result.is_error is False
        data = json.loads(result.content[0]["text"])
        assert data["success"] is True
        assert data["corrections"]["corrections_count"] == 2

@pytest.mark.asyncio
async def test_proofread_subtitles_tool_failure():
    dummy_res = DummyResult(success=False, detail="Proofread error", data=None, duration_seconds=0.5)
    
    with patch("agents.pipeline_coordinator.ProofreadWorker") as mock_worker_cls:
        mock_worker = MagicMock()
        mock_worker.execute = AsyncMock(return_value=dummy_res)
        mock_worker_cls.return_value = mock_worker

        result = await tool_registry.execute(
            "proofread_subtitles",
            {
                "video_path": "/absolute/path/to/video.mp4",
                "segments": []
            }
        )
        
        assert result.is_error is True
        data = json.loads(result.content[0]["text"])
        assert data["success"] is False

@pytest.mark.asyncio
async def test_propose_smart_cut_tool_success():
    dummy_res = DummyResult(success=True, detail="SmartCut proposed", data={"reason": "good"}, duration_seconds=0.8)
    
    async def mock_execute(ctx):
        ctx.selected_segments = [{"start": 0, "end": 1}]
        return dummy_res

    with patch("agents.pipeline_coordinator.SmartCutWorker") as mock_worker_cls:
        mock_worker = MagicMock()
        mock_worker.execute = AsyncMock(side_effect=mock_execute)
        mock_worker_cls.return_value = mock_worker

        result = await tool_registry.execute(
            "propose_smart_cut",
            {
                "video_path": "/absolute/path/to/video.mp4",
                "segments": [{"start": 0, "end": 1, "text": "test"}],
                "target_minutes": 15
            }
        )
        
        assert result.is_error is False
        data = json.loads(result.content[0]["text"])
        assert data["success"] is True
        assert data["selected_count"] == 1
        assert data["data"]["reason"] == "good"

@pytest.mark.asyncio
async def test_propose_smart_cut_tool_failure():
    dummy_res = DummyResult(success=False, detail="SmartCut failed", data=None, duration_seconds=0.3)
    
    with patch("agents.pipeline_coordinator.SmartCutWorker") as mock_worker_cls:
        mock_worker = MagicMock()
        mock_worker.execute = AsyncMock(return_value=dummy_res)
        mock_worker_cls.return_value = mock_worker

        result = await tool_registry.execute(
            "propose_smart_cut",
            {"video_path": "/absolute/path/to/video.mp4"}
        )
        
        assert result.is_error is True

@pytest.mark.asyncio
async def test_generate_preview_tool_success():
    dummy_res = DummyResult(success=True, detail="Preview generated", data={}, duration_seconds=3.0)
    
    async def mock_execute(ctx):
        ctx.preview_path = "/absolute/path/to/preview.mp4"
        return dummy_res

    with patch("agents.pipeline_coordinator.PreviewWorker") as mock_worker_cls:
        mock_worker = MagicMock()
        mock_worker.execute = AsyncMock(side_effect=mock_execute)
        mock_worker_cls.return_value = mock_worker

        result = await tool_registry.execute(
            "generate_preview",
            {
                "video_path": "/absolute/path/to/video.mp4",
                "selected_segments": [{"start": 0, "end": 1}]
            }
        )
        
        assert result.is_error is False
        data = json.loads(result.content[0]["text"])
        assert data["success"] is True
        assert data["preview_path"] == "/absolute/path/to/preview.mp4"

@pytest.mark.asyncio
async def test_generate_preview_tool_failure():
    dummy_res = DummyResult(success=False, detail="Preview failed", data=None, duration_seconds=1.0)
    
    with patch("agents.pipeline_coordinator.PreviewWorker") as mock_worker_cls:
        mock_worker = MagicMock()
        mock_worker.execute = AsyncMock(return_value=dummy_res)
        mock_worker_cls.return_value = mock_worker

        result = await tool_registry.execute(
            "generate_preview",
            {"video_path": "/absolute/path/to/video.mp4"}
        )
        
        assert result.is_error is True

@pytest.mark.asyncio
async def test_optimize_youtube_tool_success():
    dummy_res = DummyResult(success=True, detail="Optimization finished", data={}, duration_seconds=1.2)
    
    async def mock_execute(ctx):
        ctx.metadata = {"title": "Best Video"}
        return dummy_res

    with patch("agents.pipeline_coordinator.YouTubeOptWorker") as mock_worker_cls:
        mock_worker = MagicMock()
        mock_worker.execute = AsyncMock(side_effect=mock_execute)
        mock_worker_cls.return_value = mock_worker

        result = await tool_registry.execute(
            "optimize_youtube",
            {
                "video_path": "/absolute/path/to/video.mp4",
                "segments": []
            }
        )
        
        assert result.is_error is False
        data = json.loads(result.content[0]["text"])
        assert data["success"] is True
        assert data["metadata"]["title"] == "Best Video"

@pytest.mark.asyncio
async def test_optimize_youtube_tool_failure():
    dummy_res = DummyResult(success=False, detail="Optimization failed", data=None, duration_seconds=0.5)
    
    with patch("agents.pipeline_coordinator.YouTubeOptWorker") as mock_worker_cls:
        mock_worker = MagicMock()
        mock_worker.execute = AsyncMock(return_value=dummy_res)
        mock_worker_cls.return_value = mock_worker

        result = await tool_registry.execute(
            "optimize_youtube",
            {"video_path": "/absolute/path/to/video.mp4"}
        )
        
        assert result.is_error is True

@pytest.mark.asyncio
async def test_check_quality_tool_success():
    quality_data = {
        "score": 95,
        "rank": "S",
        "feedback": ["Awesome"],
        "category_scores": {"audio": 100}
    }
    dummy_res = DummyResult(success=True, detail="Quality check passed", data=quality_data, duration_seconds=2.0)
    
    with patch("agents.pipeline_coordinator.QualityGateWorker") as mock_worker_cls:
        mock_worker = MagicMock()
        mock_worker.execute = AsyncMock(return_value=dummy_res)
        mock_worker_cls.return_value = mock_worker

        result = await tool_registry.execute(
            "check_quality",
            {
                "video_path": "/absolute/path/to/video.mp4",
                "preview_path": "/absolute/path/to/preview.mp4",
                "segments": [],
                "selected_segments": [],
                "metadata": {}
            }
        )
        
        assert result.is_error is False
        data = json.loads(result.content[0]["text"])
        assert data["success"] is True
        assert data["score"] == 95
        assert data["rank"] == "S"
        assert data["feedback"] == ["Awesome"]
        assert data["category_scores"]["audio"] == 100

@pytest.mark.asyncio
async def test_check_quality_tool_failure():
    dummy_res = DummyResult(success=False, detail="Quality check error", data={}, duration_seconds=0.8)
    
    with patch("agents.pipeline_coordinator.QualityGateWorker") as mock_worker_cls:
        mock_worker = MagicMock()
        mock_worker.execute = AsyncMock(return_value=dummy_res)
        mock_worker_cls.return_value = mock_worker

        result = await tool_registry.execute(
            "check_quality",
            {
                "video_path": "/absolute/path/to/video.mp4",
                "preview_path": "/absolute/path/to/preview.mp4",
                "segments": []
            }
        )
        
        assert result.is_error is True

@pytest.mark.asyncio
async def test_render_final_tool_success():
    dummy_res = DummyResult(success=True, detail="Render finished", data={}, duration_seconds=10.0)
    
    async def mock_execute(ctx):
        ctx.final_path = "/absolute/path/to/final.mp4"
        return dummy_res

    with patch("agents.pipeline_coordinator.RenderWorker") as mock_worker_cls:
        mock_worker = MagicMock()
        mock_worker.execute = AsyncMock(side_effect=mock_execute)
        mock_worker_cls.return_value = mock_worker

        result = await tool_registry.execute(
            "render_final",
            {
                "video_path": "/absolute/path/to/video.mp4",
                "preview_path": "/absolute/path/to/preview.mp4"
            }
        )
        
        assert result.is_error is False
        data = json.loads(result.content[0]["text"])
        assert data["success"] is True
        assert data["final_path"] == "/absolute/path/to/final.mp4"

@pytest.mark.asyncio
async def test_render_final_tool_failure():
    dummy_res = DummyResult(success=False, detail="Render failed", data=None, duration_seconds=2.0)
    
    with patch("agents.pipeline_coordinator.RenderWorker") as mock_worker_cls:
        mock_worker = MagicMock()
        mock_worker.execute = AsyncMock(return_value=dummy_res)
        mock_worker_cls.return_value = mock_worker

        result = await tool_registry.execute(
            "render_final",
            {
                "video_path": "/absolute/path/to/video.mp4",
                "preview_path": "/absolute/path/to/preview.mp4"
            }
        )
        
        assert result.is_error is True

@pytest.mark.asyncio
async def test_cleanup_intermediates_tool():
    with patch("disk_manager.cleanup_intermediates") as mock_cleanup, \
         patch("disk_manager.get_free_gb") as mock_get_free:
         
        mock_cleanup.return_value = 12.34
        mock_get_free.return_value = 100.56
        
        result = await tool_registry.execute(
            "cleanup_intermediates",
            {
                "keep_latest": 2,
                "dry_run": False
            }
        )
        
        assert result.is_error is False
        data = json.loads(result.content[0]["text"])
        assert data["action"] == "削除済み"
        assert data["freed_gb"] == 12.34
        assert data["free_gb"] == 100.56
        
        mock_cleanup.assert_called_once_with(keep_latest=2, dry_run=False)

@pytest.mark.asyncio
async def test_cleanup_intermediates_tool_dry_run():
    with patch("disk_manager.cleanup_intermediates") as mock_cleanup, \
         patch("disk_manager.get_free_gb") as mock_get_free:
         
        mock_cleanup.return_value = 5.0
        mock_get_free.return_value = 80.0
        
        result = await tool_registry.execute(
            "cleanup_intermediates",
            {
                "dry_run": True
            }
        )
        
        assert result.is_error is False
        data = json.loads(result.content[0]["text"])
        assert data["action"] == "削除予定"
        assert data["freed_gb"] == 5.0
        assert data["free_gb"] == 80.0
        
        mock_cleanup.assert_called_once_with(keep_latest=1, dry_run=True)

@pytest.mark.asyncio
async def test_pipeline_tools_session_persistence():
    from harness.session_manager import session_manager
    from agents.pipeline_types import Segment
    
    session_id = "test-session-persistence-123"
    video_path = "/absolute/path/to/video.mp4"
    
    # 既存セッションをクリーンアップ
    if session_id in session_manager._active_sessions:
        del session_manager._active_sessions[session_id]
        
    dummy_res_transcribe = DummyResult(
        success=True,
        detail="Transcribe completed",
        data={"segment_count": 1},
        duration_seconds=1.0
    )
    
    async def mock_transcribe_execute(ctx):
        # Segmentオブジェクトをセットする（シリアライズ・デシリアライズのテストも兼ねる）
        ctx.segments = [Segment(start=0.0, end=1.5, text="First segment")]
        return dummy_res_transcribe
        
    # 1. transcribe_videoを実行して、セッションにsegmentsを保存させる
    with patch("agents.pipeline_coordinator.TranscribeWorker") as mock_transcribe_cls:
        mock_worker = MagicMock()
        mock_worker.execute = AsyncMock(side_effect=mock_transcribe_execute)
        mock_transcribe_cls.return_value = mock_worker
        
        res1 = await tool_registry.execute(
            "transcribe_video",
            {"video_path": video_path, "session_id": session_id}
        )
        assert res1.is_error is False
        
    # 2. propose_smart_cutをsegments引数なしで実行し、
    # セッションから復元されたsegmentsがSmartCutWorkerに引き渡されているかを検証する
    dummy_res_smart_cut = DummyResult(
        success=True,
        detail="SmartCut finished",
        data={"reason": "ok"},
        duration_seconds=1.0
    )
    
    restored_segments = []
    
    async def mock_smart_cut_execute(ctx):
        nonlocal restored_segments
        # 復元されたsegmentsを記録
        restored_segments = list(ctx.segments)
        ctx.selected_segments = [Segment(start=0.0, end=1.5, text="First segment")]
        return dummy_res_smart_cut
        
    with patch("agents.pipeline_coordinator.SmartCutWorker") as mock_smart_cut_cls:
        mock_worker = MagicMock()
        mock_worker.execute = AsyncMock(side_effect=mock_smart_cut_execute)
        mock_smart_cut_cls.return_value = mock_worker
        
        # segments引数を与えずに呼び出すことで、セッションからの復元をトリガーする
        res2 = await tool_registry.execute(
            "propose_smart_cut",
            {"video_path": video_path, "session_id": session_id}
        )
        assert res2.is_error is False
        
    # 検証：前回のセッションからsegmentsが正しく復元されていること
    assert len(restored_segments) == 1
    assert restored_segments[0].text == "First segment"
    assert restored_segments[0].start == 0.0
    assert restored_segments[0].end == 1.5


@pytest.mark.asyncio
async def test_pipeline_tools_create_new_session_flow():
    from harness.session_manager import session_manager
    import uuid
    
    unique_session_id = f"test-new-session-{uuid.uuid4()}"
    unique_video_path = f"/absolute/path/to/nonexistent-video-{uuid.uuid4()}.mp4"
    
    dummy_res = DummyResult(success=True, detail="Transcribe completed", data={"segment_count": 0}, duration_seconds=1.0)
    
    with patch("agents.pipeline_coordinator.TranscribeWorker") as mock_worker_cls:
        mock_worker = MagicMock()
        mock_worker.execute = AsyncMock(return_value=dummy_res)
        mock_worker_cls.return_value = mock_worker
        
        # セッションがまだ存在しないことを確認
        assert unique_session_id not in session_manager._active_sessions
        
        result = await tool_registry.execute(
            "transcribe_video",
            {"video_path": unique_video_path, "session_id": unique_session_id}
        )
        
        assert result.is_error is False
        # 新しいセッションが登録されたことを検証 (60行目のカバー)
        assert unique_session_id in session_manager._active_sessions


@pytest.mark.asyncio
async def test_pipeline_tools_segment_object_passing():
    from agents.pipeline_types import Segment
    
    dummy_res = DummyResult(success=True, detail="SmartCut proposed", data={"reason": "good"}, duration_seconds=1.0)
    
    # Segmentオブジェクトを渡す (90-91行目, 97-98行目のカバー)
    seg1 = Segment(start=0.0, end=1.0, text="First")
    seg2 = Segment(start=1.0, end=2.0, text="Second")
    
    restored_segments = []
    restored_selected_segments = []
    
    async def mock_smart_cut_execute(ctx):
        nonlocal restored_segments, restored_selected_segments
        restored_segments = list(ctx.segments)
        restored_selected_segments = list(ctx.selected_segments)
        return dummy_res
        
    with patch("agents.pipeline_coordinator.SmartCutWorker") as mock_worker_cls:
        mock_worker = MagicMock()
        mock_worker.execute = AsyncMock(side_effect=mock_smart_cut_execute)
        mock_worker_cls.return_value = mock_worker
        
        result = await tool_registry.execute(
            "propose_smart_cut",
            {
                "video_path": "/absolute/path/to/video-segment-passing.mp4",
                "segments": [seg1],
                "selected_segments": [seg2],
            }
        )
        
        assert result.is_error is False
        # Segmentオブジェクトがそのまま渡されていることを検証
        assert len(restored_segments) == 1
        assert restored_segments[0] == seg1
        assert len(restored_selected_segments) == 1
        assert restored_selected_segments[0] == seg2


@pytest.mark.asyncio
async def test_pipeline_tools_serialize_fallback():
    import uuid
    from harness.session_manager import session_manager
    
    unique_id = str(uuid.uuid4())
    unique_path = f"/absolute/path/to/video-serialize-fallback-{unique_id}.mp4"
    dummy_res = DummyResult(success=True, detail="Transcribe completed", data={"segment_count": 1}, duration_seconds=1.0)
    
    async def mock_transcribe_execute(ctx):
        # to_dictを持たないオブジェクト（例えばプレーンな文字列）をsegmentsに追加する
        ctx.segments = ["Plain String Segment"]
        return dummy_res
        
    with patch("agents.pipeline_coordinator.TranscribeWorker") as mock_worker_cls:
        mock_worker = MagicMock()
        mock_worker.execute = AsyncMock(side_effect=mock_transcribe_execute)
        mock_worker_cls.return_value = mock_worker
        
        result = await tool_registry.execute(
            "transcribe_video",
            {
                "video_path": unique_path,
                "session_id": unique_id
            }
        )
        
        assert result.is_error is False
        # 例外が発生せずにシリアライズされ、値がそのまま残っていることを検証 (114行目のカバー)
        data = json.loads(result.content[0]["text"])
        assert data["total_segments"] == 1
        
        # テスト後に作成されたセッションをクリーンアップ
        session_manager._active_sessions.pop(unique_id, None)
        session_file = session_manager._session_dir / f"{unique_id}.json"
        if session_file.exists():
            session_file.unlink()
