import pytest
from unittest.mock import MagicMock, patch
from agents.pipeline_types import PipelineContext, StageResult
from agents.workers.proofread_worker import ProofreadWorker

@pytest.mark.asyncio
async def test_proofread_worker_success():
    worker = ProofreadWorker()
    ctx = PipelineContext("test.mp4")
    ctx.segments = [
        {"text": "これはテストのテキストです。長文に分割されます。", "start": 0.0, "end": 4.0, "sourceStart": 0.0, "sourceEnd": 4.0}
    ]
    
    mock_result = (
        [{"text": "これはテストのテキストです。長文に分割されます。", "start": 0.0, "end": 4.0, "sourceStart": 0.0, "sourceEnd": 4.0}],
        {"total_retries": 0, "failed_batches": 0, "total_batches": 1}
    )
    with patch("subtitle_engine.ai_proofreader.proofread_segments", return_value=mock_result),          patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-1.5-flash"):
        
        res = await worker.execute(ctx)
        assert res.success is True
        assert len(ctx.segments) > 1
        for seg in ctx.segments:
            assert seg.get("sourceStart") == 0.0
            assert seg.get("sourceEnd") == 4.0

@pytest.mark.asyncio
async def test_proofread_worker_empty_segments():
    worker = ProofreadWorker()
    
    for val in [None, [], "not a list"]:
        ctx = PipelineContext("test.mp4")
        ctx.segments = val
        res = await worker.execute(ctx)
        assert res.success is True
        assert "校閲スキップ" in res.detail

@pytest.mark.asyncio
async def test_proofread_worker_invalid_elements():
    worker = ProofreadWorker()
    ctx = PipelineContext("test.mp4")
    ctx.segments = [
        None,
        {"text": "正常なテキスト", "start": 0.0, "end": 2.0, "sourceStart": 0.0, "sourceEnd": 2.0},
        "invalid string element"
    ]
    
    mock_result = (
        [{"text": "正常なテキスト", "start": 0.0, "end": 2.0, "sourceStart": 0.0, "sourceEnd": 2.0}],
        {"total_retries": 0, "failed_batches": 0, "total_batches": 1}
    )
    with patch("subtitle_engine.ai_proofreader.proofread_segments", return_value=mock_result),          patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-1.5-flash"):
        
        res = await worker.execute(ctx)
        assert res.success is True
        assert len(ctx.segments) == 1
        assert ctx.segments[0]["text"] == "正常なテキスト"

@pytest.mark.asyncio
async def test_proofread_worker_none_start():
    worker = ProofreadWorker()
    ctx = PipelineContext("test.mp4")
    ctx.segments = [
        {"text": "テストテキスト。長文分割されてstartがNoneの場合の検証用", "start": None, "end": 2.0, "sourceStart": 0.0, "sourceEnd": 2.0}
    ]
    
    mock_result = (
        [{"text": "テストテキスト。長文分割されてstartがNoneの場合の検証用", "start": None, "end": 2.0, "sourceStart": 0.0, "sourceEnd": 2.0}],
        {"total_retries": 0, "failed_batches": 0, "total_batches": 1}
    )
    with patch("subtitle_engine.ai_proofreader.proofread_segments", return_value=mock_result),          patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-1.5-flash"):
        
        res = await worker.execute(ctx)
        assert res.success is True

@pytest.mark.asyncio
async def test_proofread_worker_float_rounding_and_rounding_injection():
    worker = ProofreadWorker()
    ctx = PipelineContext("test.mp4")
    ctx.segments = [
        {"text": "元セグメント。長文分割されて誤差が発生する想定", "start": 0.0, "end": 2.0, "sourceStart": 0.0, "sourceEnd": 2.0}
    ]
    
    mock_format = [
        {"text": "分割1", "start": 0.0, "end": 1.0},
        {"text": "分割2", "start": 2.000005, "end": 3.0}
    ]
    
    mock_result = (
        [{"text": "元セグメント。長文分割されて誤差が発生する想定", "start": 0.0, "end": 2.0, "sourceStart": 0.0, "sourceEnd": 2.0}],
        {"total_retries": 0, "failed_batches": 0, "total_batches": 1}
    )
    
    with patch("subtitle_engine.ai_proofreader.proofread_segments", return_value=mock_result),          patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-1.5-flash"),          patch("subtitle_engine.text_formatter.format_segments", return_value=mock_format):
        
        res = await worker.execute(ctx)
        assert res.success is True
        assert ctx.segments[1].get("sourceStart") == 0.0
        assert ctx.segments[1].get("sourceEnd") == 2.0

@pytest.mark.asyncio
async def test_proofread_worker_partial_missing_source_timestamps():
    worker = ProofreadWorker()
    ctx = PipelineContext("test.mp4")
    ctx.segments = [
        {"text": "分割テスト用", "start": 0.0, "end": 2.0, "sourceStart": 0.0}
    ]
    
    mock_format = [
        {"text": "分割1", "start": 0.0, "end": 1.0}
    ]
    
    mock_result = (
        [{"text": "分割テスト用", "start": 0.0, "end": 2.0, "sourceStart": 0.0}],
        {"total_retries": 0, "failed_batches": 0, "total_batches": 1}
    )
    
    with patch("subtitle_engine.ai_proofreader.proofread_segments", return_value=mock_result),          patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-1.5-flash"),          patch("subtitle_engine.text_formatter.format_segments", return_value=mock_format):
        
        res = await worker.execute(ctx)
        assert res.success is True
        assert ctx.segments[0].get("sourceStart") == 0.0


@pytest.mark.asyncio
async def test_proofread_worker_segment_objects():
    from agents.pipeline_types import Segment
    worker = ProofreadWorker()
    ctx = PipelineContext("test.mp4")
    ctx.segments = [
        Segment(start=0.0, end=4.0, text="これはSegmentオブジェクトのテストです。", sourceStart=0.0, sourceEnd=4.0)
    ]
    
    mock_result = (
        [{"text": "これはSegmentオブジェクトのテストです。", "start": 0.0, "end": 4.0, "sourceStart": 0.0, "sourceEnd": 4.0}],
        {"total_retries": 0, "failed_batches": 0, "total_batches": 1}
    )
    with patch("subtitle_engine.ai_proofreader.proofread_segments", return_value=mock_result),          patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-1.5-flash"):
        
        res = await worker.execute(ctx)
        assert res.success is True
        assert len(ctx.segments) > 1
        for seg in ctx.segments:
            assert isinstance(seg, Segment)
            assert seg.sourceStart == 0.0
