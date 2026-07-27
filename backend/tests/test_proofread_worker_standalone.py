# -*- coding: utf-8 -*-
import pytest
import os
import sys
import asyncio
from unittest.mock import patch, MagicMock

# パス設定
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.pipeline_types import PipelineContext, StageResult
from agents.workers.proofread_worker import ProofreadWorker

def test_proofread_worker_init():
    worker = ProofreadWorker()
    assert worker.name == "AI校閲"
    assert worker.icon == "📝"
    assert "固有名詞誤りがゼロであること" in worker.get_definition_of_done()

@pytest.mark.asyncio
async def test_proofread_worker_empty_segments():
    ctx = PipelineContext(video_path="dummy.mp4")
    ctx.segments = []
    worker = ProofreadWorker()
    result = await worker.execute(ctx)
    assert result.success is True
    assert "セグメントなし" in result.detail

@pytest.mark.asyncio
async def test_proofread_worker_dict_and_ai_success():
    ctx = PipelineContext(video_path="dummy.mp4")
    ctx.segments = [
        {"id": 0, "text": "テスト。"},
        {"id": 1, "text": "二つ目。"}
    ]
    worker = ProofreadWorker()

    # モックの設定
    mock_apply = MagicMock(return_value=("テスト修正。", ["修正"]))
    # proofread_segments は (segments, retry_stats) を返す
    mock_ai = MagicMock(return_value=([{"id": 0, "text": "テスト修正。"}, {"id": 1, "text": "二つ目。"}], {"total_retries": 1, "failed_batches": 0, "total_batches": 2}))
    mock_format = MagicMock(return_value=[{"id": 0, "text": "テスト修正。"}, {"id": 1, "text": "二つ目。"}])
    mock_max_chars = MagicMock(return_value=18)
    mock_model = MagicMock(return_value="gemini-1.5-flash")

    with patch("proper_noun_dict.apply_dictionary", mock_apply), \
         patch("subtitle_engine.ai_proofreader.proofread_segments", mock_ai), \
         patch("subtitle_engine.text_formatter.format_segments", mock_format), \
         patch("subtitle_engine.text_formatter.get_max_chars_from_template", mock_max_chars), \
         patch("subtitle_engine.ai_proofreader._get_current_model", mock_model):
        
        result = await worker.execute(ctx)
        assert result.success is True
        assert "辞書2件 + AI1件" in result.detail

@pytest.mark.asyncio
async def test_proofread_worker_ai_retry_and_warnings():
    ctx = PipelineContext(video_path="dummy.mp4")
    ctx.segments = [{"id": 0, "text": "テスト。"}]
    worker = ProofreadWorker()

    mock_apply = MagicMock(side_effect=Exception("dict error"))
    mock_ai = MagicMock(return_value=([{"id": 0, "text": "テスト。"}], {"total_retries": 2, "failed_batches": 1, "total_batches": 2, "skipped": True}))
    mock_format = MagicMock(side_effect=Exception("format error"))
    mock_model = MagicMock(side_effect=Exception("model error"))

    with patch("proper_noun_dict.apply_dictionary", mock_apply), \
         patch("subtitle_engine.ai_proofreader.proofread_segments", mock_ai), \
         patch("subtitle_engine.text_formatter.format_segments", mock_format), \
         patch("subtitle_engine.ai_proofreader._get_current_model", mock_model):
        
        result = await worker.execute(ctx)
        assert result.success is True
        assert len(ctx.warnings) >= 2
        assert "AI校閲がAPI枠制限によりスキップされました" in ctx.warnings[1]
        assert "AI校閲(Gemini)" in ctx.skipped_features

@pytest.mark.asyncio
async def test_proofread_worker_timestamps_protection():
    ctx = PipelineContext(video_path="dummy.mp4")
    ctx.segments = [
        {"id": 0, "text": "非常に長いテキストで分割されます", "start": 0.0, "end": 4.0, "sourceStart": 0.0, "sourceEnd": 4.0}
    ]
    worker = ProofreadWorker()

    # format_segmentsで複数セグメントに分割される挙動を模倣
    def mock_format_segments(segments, max_chars=18):
        return [
            {"id": 0, "text": "非常に長いテキスト", "start": 0.0, "end": 2.0},
            {"id": 1, "text": "で分割されます", "start": 2.0, "end": 4.0}
        ]

    mock_apply = MagicMock(return_value=("非常に長いテキストで分割されます", []))
    mock_ai = MagicMock(return_value=([{"id": 0, "text": "非常に長いテキストで分割されます", "start": 0.0, "end": 4.0, "sourceStart": 0.0, "sourceEnd": 4.0}], {}))
    mock_max_chars = MagicMock(return_value=18)

    with patch("proper_noun_dict.apply_dictionary", mock_apply), \
         patch("subtitle_engine.ai_proofreader.proofread_segments", mock_ai), \
         patch("subtitle_engine.text_formatter.format_segments", side_effect=mock_format_segments), \
         patch("subtitle_engine.text_formatter.get_max_chars_from_template", mock_max_chars):
        
        result = await worker.execute(ctx)
        assert result.success is True
        assert len(ctx.segments) == 2
        assert ctx.segments[0]["sourceStart"] == 0.0
        assert ctx.segments[1]["sourceStart"] == 0.0
        assert ctx.segments[0]["sourceEnd"] == 4.0
        assert ctx.segments[1]["sourceEnd"] == 4.0
