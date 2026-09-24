"""R2-C1: 画面からの強制書き出しも承認を通す（2026-09-19）。

`POST /api/pipeline/force-render` は、憲法 §8.2 のバイパスとして**承認なしで**プレビューを
本番品質で書き出していた。R2-C1「承認していない動画は書き出せない」と正面から衝突するので、
R2 では書き出さず、承認の手順を案内する（品質が低いまま出す判断は**承認そのもの**）。

承認画面からの「承認して書き出す」は C5 で作る（中間ゲートの後）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.fixture
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.pipeline_router import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_完了していなければ従来どおり400(client):
    from routers.pipeline_router import _reset_state

    _reset_state()
    r = client.post("/api/pipeline/force-render", json={"session_id": "", "reason": "test"})
    assert r.status_code == 400


def test_承認を通さない強制書き出しは断る(client):
    """**書き出しの経路はすべて承認の門を通る。** CLI だけを塞いでも画面から抜けられては意味がない。"""
    from routers.pipeline_router import _pipeline_state, _reset_state

    _reset_state()
    _pipeline_state["status"] = "completed"
    _pipeline_state["result"] = {
        "run_id": "RID",
        "preview_path": "/tmp/preview.mp4",
        "quality_gate_report": {"status": "blocked", "score": 80, "threshold": 90},
    }
    r = client.post("/api/pipeline/force-render", json={"session_id": "", "reason": "出したい"})

    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert "承認" in detail
    assert "approval_gate" in detail, "承認の手順を案内していません"


def test_品質不合格の知らせは強制書き出しを勧めない():
    """結果と WebSocket の `force_render_available` は False（経路を閉じたので）。"""
    from agents.pipeline_coordinator import PipelineCoordinator
    from agents.pipeline_types import PipelineContext

    c = PipelineCoordinator()
    ctx = PipelineContext(video_path="/tmp/test.mp4")
    ctx.quality_score = 80
    ctx.quality_scored = True
    result = c._build_result(ctx, "awaiting_approval", 0.0)

    assert result["quality_gate_report"]["force_render_available"] is False
