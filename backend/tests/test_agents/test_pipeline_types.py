import pytest
from agents.pipeline_types import (
    Segment,
    StageResult,
    PipelineContext,
    PipelineStageWorker
)

def test_segment_post_init():
    # sourceStart/sourceEnd が None の場合
    seg = Segment(start=1.0, end=5.0, text="Hello")
    assert seg.sourceStart == 1.0
    assert seg.sourceEnd == 5.0

    # sourceStart/sourceEnd が指定されている場合
    seg2 = Segment(start=1.0, end=5.0, text="Hello", sourceStart=0.5, sourceEnd=6.0)
    assert seg2.sourceStart == 0.5
    assert seg2.sourceEnd == 6.0

def test_segment_to_dict():
    seg = Segment(start=1.0, end=5.0, text="Hello", sourceStart=1.0, sourceEnd=5.0)
    d = seg.to_dict()
    assert d == {
        "start": 1.0,
        "end": 5.0,
        "text": "Hello",
        "sourceStart": 1.0,
        "sourceEnd": 5.0
    }

def test_segment_from_dict():
    # 最小限のキー
    d = {"start": 2.0, "end": 4.0}
    seg = Segment.from_dict(d)
    assert seg.start == 2.0
    assert seg.end == 4.0
    assert seg.text == ""
    assert seg.sourceStart == 2.0
    assert seg.sourceEnd == 4.0

    # すべてのキー
    d2 = {
        "start": 2.0,
        "end": 4.0,
        "text": "World",
        "sourceStart": 1.5,
        "sourceEnd": 4.5
    }
    seg2 = Segment.from_dict(d2)
    assert seg2.start == 2.0
    assert seg2.end == 4.0
    assert seg2.text == "World"
    assert seg2.sourceStart == 1.5
    assert seg2.sourceEnd == 4.5

    # 必須キー欠損による KeyError
    with pytest.raises(KeyError):
        Segment.from_dict({"start": 2.0})
    with pytest.raises(KeyError):
        Segment.from_dict({"end": 4.0})

def test_segment_properties():
    seg = Segment(start=1.0, end=3.5, text="Test")
    assert seg.duration == 2.5
    # sourceStart, sourceEnd が指定されていない場合は end - start と同じ
    assert seg.source_duration == 2.5

    # sourceStart, sourceEnd が指定されている場合
    seg2 = Segment(start=1.0, end=3.5, text="Test", sourceStart=0.5, sourceEnd=4.0)
    assert seg2.duration == 2.5
    assert seg2.source_duration == 3.5

    seg3 = Segment(start=1.0, end=3.5, text="Test", sourceStart=0.0, sourceEnd=3.0)
    assert seg3.duration == 2.5
    assert seg3.source_duration == 3.0

def test_stage_result():
    res = StageResult(stage_name="TestStage", success=True)
    assert res.stage_name == "TestStage"
    assert res.success is True
    assert res.detail == ""
    assert res.data == {}
    assert res.duration_seconds == 0.0
    assert res.retries == 0

    res2 = StageResult(
        stage_name="TestStage2",
        success=False,
        detail="Error",
        data={"err": "info"},
        duration_seconds=1.5,
        retries=2
    )
    assert res2.stage_name == "TestStage2"
    assert res2.success is False
    assert res2.detail == "Error"
    assert res2.data == {"err": "info"}
    assert res2.duration_seconds == 1.5
    assert res2.retries == 2

def test_pipeline_context():
    ctx = PipelineContext(video_path="/path/to/video.mp4")
    assert ctx.video_path == "/path/to/video.mp4"
    assert ctx.target_minutes == 20
    assert ctx.session_id == ""
    assert ctx.started_at == ""
    assert ctx.segments == []
    assert ctx.selected_segments == []
    assert ctx.preview_path is None
    assert ctx.final_path is None
    assert ctx.quality_score == 0
    assert ctx.quality_feedback == []
    assert ctx.metadata == {}
    assert ctx.stage_results == []
    assert ctx.template_id is None
    assert ctx.template_config is None
    assert ctx.skipped_features == []
    assert ctx.warnings == []
    assert ctx.render_mode == "production"
    assert ctx.quality_gate_report is None

class DummyStageWorker(PipelineStageWorker):
    async def execute(self, ctx: PipelineContext) -> StageResult:
        return StageResult(stage_name=self.name, success=True, detail="Executed")

@pytest.mark.asyncio
async def test_pipeline_stage_worker():
    worker = DummyStageWorker(name="Dummy", icon="😀", index=1)
    assert worker.name == "Dummy"
    assert worker.icon == "😀"
    assert worker.index == 1

    ctx = PipelineContext(video_path="test.mp4")
    res = await worker.execute(ctx)
    assert res.stage_name == "Dummy"
    assert res.success is True
    assert res.detail == "Executed"

    # 基底クラスの execute() を呼び出して、pass 行をカバーする
    await PipelineStageWorker.execute(worker, ctx)

    assert worker.get_definition_of_done() == "Dummy completed successfully"
    assert worker.verify(res) is True

    failed_res = StageResult(stage_name="Dummy", success=False)
    assert worker.verify(failed_res) is False
