import sys
from pathlib import Path

# backend ディレクトリを sys.path から一時的に除去し、mock_pipeline 側で挿入させる
_backend_dir = str(Path(__file__).resolve().parent.parent)
if _backend_dir in sys.path:
    while _backend_dir in sys.path:
        sys.path.remove(_backend_dir)

# すでにインポートされている場合は sys.modules から削除して再ロードさせる
if 'fixtures.mock_pipeline' in sys.modules:
    del sys.modules['fixtures.mock_pipeline']

import pytest
from fixtures.mock_pipeline import (
    create_mock_segments,
    create_mock_ctx,
    create_mock_stage_result
)
from agents.pipeline_coordinator import PipelineContext, StageResult

def test_create_mock_segments_defaults():
    segments = create_mock_segments()
    assert len(segments) == 10
    for seg in segments:
        assert "start" in seg
        assert "end" in seg
        assert "text" in seg
        assert "sourceStart" in seg
        assert "sourceEnd" in seg

def test_create_mock_segments_custom_count():
    assert len(create_mock_segments(count=0)) == 0
    assert len(create_mock_segments(count=1)) == 1
    assert len(create_mock_segments(count=50)) == 50

def test_create_mock_segments_no_source_times():
    segments = create_mock_segments(count=5, with_source_times=False)
    for seg in segments:
        assert "sourceStart" not in seg
        assert "sourceEnd" not in seg

def test_create_mock_segments_corrupt():
    # corrupt=True のとき、5個に1個の割合で破損
    # i % 5 == 3 で text フィールド欠落
    # i % 5 == 4 で start > end
    segments = create_mock_segments(count=10, corrupt=True)
    assert "text" not in segments[3]
    assert "text" not in segments[8]
    assert segments[4]["start"] > segments[4]["end"]
    assert segments[9]["start"] > segments[9]["end"]

def test_create_mock_segments_type_error():
    # type_error=True のとき、4個に1個の割合で型不正
    # i % 4 == 2 で start が str
    # i % 4 == 3 で end が None
    segments = create_mock_segments(count=10, type_error=True)
    assert isinstance(segments[2]["start"], str)
    assert isinstance(segments[6]["start"], str)
    assert segments[3]["end"] is None
    assert segments[7]["end"] is None

def test_create_mock_ctx_defaults():
    ctx = create_mock_ctx()
    assert isinstance(ctx, PipelineContext)
    assert len(ctx.segments) == 10
    assert ctx.target_minutes == 20
    assert ctx.session_id == "test-session-001"
    assert ctx.started_at == "2026-04-20T12:00:00"
    assert ctx.selected_segments == []
    assert ctx.template_id is None
    assert ctx.video_path != ""

def test_create_mock_ctx_custom_params():
    ctx = create_mock_ctx(
        segments=5,
        video_path="custom/path.mp4",
        target_minutes=15,
        session_id="custom-session",
        with_selected=True,
        template_id="custom-template"
    )
    assert len(ctx.segments) == 5
    assert ctx.video_path == "custom/path.mp4"
    assert ctx.target_minutes == 15
    assert ctx.session_id == "custom-session"
    assert ctx.template_id == "custom-template"
    assert len(ctx.selected_segments) == 5
    assert ctx.selected_segments[0]["start"] == ctx.segments[0]["start"]

def test_create_mock_ctx_corrupt_and_type_error():
    ctx = create_mock_ctx(segments=10, corrupt=True, type_error=True)
    # corrupt の影響
    assert "text" not in ctx.segments[3]
    # type_error の影響
    assert isinstance(ctx.segments[2]["start"], str)

def test_create_mock_stage_result_defaults():
    res = create_mock_stage_result()
    assert isinstance(res, StageResult)
    assert res.stage_name == "テスト"
    assert res.success is True
    assert res.detail == "テスト成功"
    assert res.data == {}
    assert res.duration_seconds == 1.0

def test_create_mock_stage_result_custom():
    res = create_mock_stage_result(
        stage_name="レンダリング",
        success=False,
        detail="エラーが発生しました",
        data={"error_code": 500},
        duration_seconds=12.5
    )
    assert res.stage_name == "レンダリング"
    assert res.success is False
    assert res.detail == "エラーが発生しました"
    assert res.data == {"error_code": 500}
    assert res.duration_seconds == 12.5
