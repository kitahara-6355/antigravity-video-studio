import pytest
from dataclasses import asdict
from typing import Dict

from agents.pipeline_types import (
    Segment,
    StageResult,
    PipelineContext,
    PipelineStageWorker,
)

# 1. Segment tests
def test_segment_to_dict():
    segment = Segment(
        start=1.5,
        end=4.5,
        text="?????",
        sourceStart=1.0,
        sourceEnd=5.0
    )
    d = segment.to_dict()
    assert d == {
        "start": 1.5,
        "end": 4.5,
        "text": "?????",
        "sourceStart": 1.0,
        "sourceEnd": 5.0
    }

def test_segment_durations():
    seg1 = Segment(start=2.0, end=5.5, text="???")
    assert seg1.duration == 3.5
    assert seg1.source_duration == 3.5

    seg2 = Segment(
        start=2.0,
        end=5.5,
        text="???",
        sourceStart=1.0,
        sourceEnd=6.0
    )
    assert seg2.duration == 3.5
    assert seg2.source_duration == 5.0

    seg3 = Segment(
        start=2.0,
        end=5.5,
        text="???",
        sourceStart=0.0,
        sourceEnd=5.0
    )
    assert seg3.duration == 3.5
    assert seg3.source_duration == 5.0

def test_segment_from_dict_error():
    with pytest.raises(KeyError):
        Segment.from_dict({"start": 1.0, "text": "error"})
    with pytest.raises(KeyError):
        Segment.from_dict({"end": 5.0, "text": "error"})

# 2. StageResult test
def test_stage_result():
    result = StageResult(
        stage_name="TestStage",
        success=True,
        detail="Completed",
        data={"key": "val"},
        duration_seconds=1.2,
        retries=1
    )
    assert result.stage_name == "TestStage"
    assert result.success is True
    assert result.detail == "Completed"
    assert result.data == {"key": "val"}
    assert result.duration_seconds == 1.2
    assert result.retries == 1

# 3. PipelineContext test
def test_pipeline_context():
    ctx = PipelineContext(
        video_path="path/to/video.mp4",
        target_minutes=15,
        session_id="session-123",
        started_at="2026-05-23T12:00:00",
        segments=[],
        selected_segments=[],
        preview_path="preview.mp4",
        final_path="final.mp4",
        quality_score=85,
        quality_feedback=["feedback"],
        metadata={"meta": "data"},
        stage_results=[],
        template_id="template-1",
        template_config={"cfg": True},
        skipped_features=["skip"],
        warnings=["warn"],
        render_mode="safe",
        quality_gate_report={"gate": "ok"}
    )
    assert ctx.video_path == "path/to/video.mp4"
    assert ctx.target_minutes == 15
    assert ctx.session_id == "session-123"
    assert ctx.started_at == "2026-05-23T12:00:00"
    assert ctx.preview_path == "preview.mp4"
    assert ctx.final_path == "final.mp4"
    assert ctx.quality_score == 85
    assert ctx.quality_feedback == ["feedback"]
    assert ctx.metadata == {"meta": "data"}
    assert ctx.template_id == "template-1"
    assert ctx.template_config == {"cfg": True}
    assert ctx.skipped_features == ["skip"]
    assert ctx.warnings == ["warn"]
    assert ctx.render_mode == "safe"
    assert ctx.quality_gate_report == {"gate": "ok"}

# 4. PipelineStageWorker test with Dummy implementation
class DummyWorker(PipelineStageWorker):
    async def execute(self, ctx: PipelineContext) -> StageResult:
        await super().execute(ctx)
        return StageResult(stage_name=self.name, success=True)

@pytest.mark.asyncio
async def test_pipeline_stage_worker():
    worker = DummyWorker(name="Dummy", icon="??", index=1)
    assert worker.name == "Dummy"
    assert worker.icon == "??"
    assert worker.index == 1

    ctx = PipelineContext(video_path="dummy.mp4")
    result = await worker.execute(ctx)
    assert result.stage_name == "Dummy"
    assert result.success is True

    dod = worker.get_definition_of_done()
    assert dod == "Dummy completed successfully"

    assert worker.verify(result) is True
    fail_result = StageResult(stage_name="Dummy", success=False)
    assert worker.verify(fail_result) is False
