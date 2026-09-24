"""R2-C1: **動画を書き出す経路はすべて承認を通す**（2026-09-19 / 2026-09-25 追補）。

CLI の門だけでは足りない。**書き出すのは worker と router** なので、そこを直接叩ける経路が
残っていると「承認していない動画は書き出せない」は成立しない。2026-09-24 の gate-verifier が
実際に承認ゼロで 1080x1920 の mp4 を作って反証した（`POST /api/shorts/render`）。

閉じた経路（いずれも 409 で承認の手順へ案内する）:

| 経路 | 何を書いていたか |
|---|---|
| `POST /api/pipeline/force-render` | 憲法§8.2 のバイパス。プレビューを本番品質で `vault-outputs/final/` へ |
| `POST /api/shorts/render` | 承認ゼロで 1080x1920 の縦型 mp4 を `vault-outputs/shorts/` へ |
| `POST /api/video/process` | ffmpeg 3回で `backend/temp/video_output/` へ |

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


# --- Shorts（画面のカタログに載っている・実際に mp4 を作れた） ------------------

@pytest.fixture
def shorts_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.shorts import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def test_shorts_の書き出しは承認を通していないと断る(shorts_client, tmp_path):
    """**承認ゼロで縦型 mp4 が出ていた**（gate-verifier が 671,403 byte を実生成）。"""
    import routers.shorts as shorts

    素材 = tmp_path / "raw.mp4"
    素材.write_bytes(b"\x00" * 4096)
    呼ばれた = []
    original = shorts._execute_ffmpeg_render
    shorts._execute_ffmpeg_render = lambda **kw: 呼ばれた.append(kw) or {"success": True}
    try:
        r = shorts_client.post("/api/shorts/render", json={
            "video_path": str(素材), "start_sec": 0, "end_sec": 3,
        })
    finally:
        shorts._execute_ffmpeg_render = original

    assert r.status_code == 409, r.text
    assert 呼ばれた == [], "ffmpeg を呼んでいます（書き出している）"
    detail = r.json()["detail"]
    assert "承認" in detail and "approval_gate" in detail


def test_shorts_の候補抽出は閉じない(shorts_client):
    """**塞ぐのは書き出しだけ。** 候補を探すのは分析なので通す（R2-C1 は動画の書き出しの話）。"""
    r = shorts_client.post("/api/shorts/candidates", json={"video_id": "x", "segments": []})
    assert r.status_code != 409


# --- 旧 video_processor 経路（画面のカタログには無い） --------------------------

def test_video_process_は承認を通していないと断る():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.render import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    r = client.post("/api/video/process", json={
        "video_paths": ["v1.mp4"], "mood": "warm", "output_name": "final_vid",
    })

    assert r.status_code == 409, r.text
    assert "承認" in r.json()["detail"]


# --- 書き出す主体（worker）そのものに門を置く -----------------------------------

@pytest.mark.asyncio
async def test_worker_は承認を指せないと書き出さない(tmp_path):
    """**門を coordinator だけに置くと worker を直接呼ぶ経路が素通りする。**

    harness の `render_final` ツールは `RenderWorker().execute(ctx)` を直呼びしていて、
    `vault-outputs/final/` に承認なしで動画が出ていた（2026-09-24 の gate-verifier）。
    承認の記録を指せない文脈は fail-closed で断る。
    """
    from agents.pipeline_types import PipelineContext
    from agents.workers.render_worker import RenderWorker

    preview = tmp_path / "preview.mp4"
    preview.write_bytes(b"\x00" * 4096)
    ctx = PipelineContext(video_path=str(tmp_path / "in.mp4"))
    ctx.preview_path = str(preview)

    # 1. 実行記録を指していない（harness からの直呼び）
    result = await RenderWorker().execute(ctx)
    assert result.success is False
    assert "承認" in result.detail
    assert ctx.final_path is None, "書き出しています"

    # 2. 記録はあるが承認が無い
    run_dir = tmp_path / "runs" / "RID"
    run_dir.mkdir(parents=True)
    ctx.run_dir = str(run_dir)
    result = await RenderWorker().execute(ctx)
    assert result.success is False
    assert "承認" in result.detail
    assert ctx.final_path is None
