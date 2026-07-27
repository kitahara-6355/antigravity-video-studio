"""
SmartCutWorker スモークテスト

Phase 1 M1.1 T-008: モックデータでSmartCutWorkerが動作することを確認。
Phase 2 Sprint 2.2.3 の前提条件として、基本的な動作保証を行う。
"""

import pytest
import asyncio
import sys
import os

# パス設定
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from agents.pipeline_coordinator import SmartCutWorker, PipelineContext
from fixtures.mock_pipeline import create_mock_ctx
from fixtures.mock_data import get_preset_ctx


class TestSmartCutSmoke:
    """SmartCutWorker の基本動作テスト"""

    @pytest.mark.worker
    @pytest.mark.asyncio
    async def test_md03_standard_segments(self):
        """MD-03: 10セグメント標準入力で動作する"""
        ctx = create_mock_ctx(segments=10, target_minutes=5)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)
        assert result.success
        assert len(ctx.selected_segments) > 0

    @pytest.mark.worker
    @pytest.mark.asyncio
    async def test_md01_empty_segments(self):
        """MD-01: 0セグメントで安全にfailする"""
        ctx = create_mock_ctx(segments=0)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)
        assert not result.success
        assert "セグメントなし" in result.detail

    @pytest.mark.worker
    @pytest.mark.asyncio
    async def test_md02_minimal_segment(self):
        """MD-02: 1セグメントでカット不要パスを通る"""
        ctx = create_mock_ctx(segments=1, target_minutes=20)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)
        assert result.success
        assert len(ctx.selected_segments) == 1

    @pytest.mark.worker
    @pytest.mark.asyncio
    async def test_md04_large_segments(self):
        """MD-04: 50セグメントで動作する"""
        ctx = create_mock_ctx(segments=50, target_minutes=5)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)
        assert result.success
        assert len(ctx.selected_segments) > 0
        assert len(ctx.selected_segments) <= 50

    @pytest.mark.worker
    @pytest.mark.asyncio
    async def test_md07_long_segments(self):
        """MD-07: 100セグメント(30分相当)で動作する"""
        ctx = get_preset_ctx("MD-07", target_minutes=10)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)
        assert result.success
        assert len(ctx.selected_segments) > 0

    @pytest.mark.worker
    @pytest.mark.asyncio
    async def test_preset_api(self):
        """get_preset_ctx が全プリセットで PipelineContext を返す"""
        from fixtures.mock_data import PRESETS
        for preset_id in PRESETS:
            ctx = get_preset_ctx(preset_id)
            assert isinstance(ctx, PipelineContext), f"{preset_id} failed"

    @pytest.mark.worker
    @pytest.mark.asyncio
    async def test_selected_subset_of_original(self):
        """selected_segments ⊆ segments であること"""
        ctx = create_mock_ctx(segments=20, target_minutes=3)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)
        assert result.success
        # 各 selected が元の segments に含まれること
        original_texts = {s.get("text") for s in ctx.segments}
        for seg in ctx.selected_segments:
            assert seg.get("text") in original_texts

    @pytest.mark.worker
    @pytest.mark.asyncio
    async def test_stage_result_data_fields(self):
        """StageResult.data に segments, duration, cut_percent が含まれる"""
        ctx = create_mock_ctx(segments=20, target_minutes=3)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)
        assert result.success
        assert "segments" in result.data
        assert "duration" in result.data
        assert "cut_percent" in result.data
