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
from unittest.mock import patch

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


def test_旧本番経路のもう1つの入口も断る():
    """**同じ実装への2本目の入口**（2026-09-25 の gate-verifier が実生成で反証）。

    `/api/video/process` を閉じても、`legacy_production_router` の
    `/api/video/process/start` が同じ `video_processor.process_video` を呼んでいて、
    承認ゼロで `backend/temp/video_output/` に mp4 が3本できた。
    **入口ごとに塞ぐのではなく、同じ実装へ向かう入口を全部塞ぐ。**
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.legacy_production_router import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    with patch("video_processor.video_processor") as vp:
        r = client.post("/api/video/process/start", json={
            "video_paths": ["v1.mp4"], "mood": "elegant", "output_name": "probe",
        })

    assert r.status_code == 409, r.text
    assert "承認" in r.json()["detail"]
    vp.create_task.assert_not_called()
    vp.process_video.assert_not_called()


def test_エディタの最終動画生成も断る():
    """**5つ目の口**（2026-09-25。走査ゲートが `create_final_video` の呼び口として出した）。

    `POST /editor/create-final` は opening + 本編 + ending + テロップを合成して
    `vault-outputs/edited/` に完成した動画を作る。置き場は `final/` ではないが、
    **人がそのまま投稿できる完成品**なので、承認を通さずに作れてよい理由が無い。
    画面からは呼ばれていない（`frontend/src` に該当なし）。
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from antigravity_api import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    with patch("video_editor_engine.video_editor") as ve:
        r = client.post("/api/antigravity/editor/create-final", json={"main_video": "v.mp4"})

    assert r.status_code == 409, r.text
    assert "承認" in r.json()["detail"]
    ve.create_final_video.assert_not_called()



# --- 6周目の U3: 書き手に残っていた T-022 の退避 ----------------------------------

@pytest.mark.asyncio
async def test_worker_は承認したプレビューが無いと素材から書き出さない(tmp_path, monkeypatch):
    """**T-022 の退避で書き出す道を閉じる**（6周目の U3）。

    門の確認の後にプレビューが消えると（容量不足のとき本線のフックが実際に消す）、以前は素材から
    直接レンダリングして completed になった。人が見たものではない動画が出る。
    """
    from agents.pipeline_types import PipelineContext
    from agents.workers.render_worker import RenderWorker
    from tests.fixtures.mock_pipeline import create_approved_run

    monkeypatch.setenv("ANTIGRAVITY_VAULT_OUTPUTS", str(tmp_path / "vault"))
    import importlib
    import safe_io
    importlib.reload(safe_io)
    try:
        source = tmp_path / "source.mp4"
        source.write_bytes(b"\x00" * 4096)
        ctx = PipelineContext(video_path=str(source))
        ctx.run_dir = create_approved_run(str(tmp_path / "runs" / "RID"))
        ctx.preview_path = None          # 承認したプレビューが消えた

        worker = RenderWorker()
        monkeypatch.setattr(RenderWorker, "_承認を確かめる", staticmethod(lambda c: (True, "")))
        result = await worker.execute(ctx)

        assert result.success is False
        assert "プレビュー" in result.detail
        assert ctx.final_path is None
        assert not list((tmp_path / "vault").rglob("*.mp4")), "素材から書き出している"
    finally:
        monkeypatch.undo()
        importlib.reload(safe_io)


@pytest.mark.asyncio
async def test_worker_は書き出しの途中でプレビューが変わったら捨てる(tmp_path, monkeypatch):
    """門の確認と書き出しの間の窓を閉じる — **書いた後にもう一度プレビューの指紋を見る**。"""
    from agents.pipeline_types import PipelineContext
    from agents.workers.render_worker import RenderWorker

    monkeypatch.setenv("ANTIGRAVITY_VAULT_OUTPUTS", str(tmp_path / "vault"))
    import importlib
    import safe_io
    importlib.reload(safe_io)
    try:
        preview = tmp_path / "preview.mp4"
        preview.write_bytes(b"approved-preview")
        ctx = PipelineContext(video_path=str(tmp_path / "source.mp4"))
        ctx.preview_path = str(preview)

        async def 途中で差し替わる(self, src, dst, _ctx):
            Path(dst).write_bytes(b"rendered-from-" + Path(src).read_bytes())
            preview.write_bytes(b"swapped-during-render")   # 書いている間に差し替わる
            return True

        monkeypatch.setattr(RenderWorker, "_承認を確かめる", staticmethod(lambda c: (True, "")))
        monkeypatch.setattr(RenderWorker, "_render_production_quality", 途中で差し替わる)
        result = await RenderWorker().execute(ctx)

        assert result.success is False
        assert "プレビュー" in result.detail
        assert ctx.final_path is None
        assert not list((tmp_path / "vault").rglob("*.mp4")), "差し替わったプレビューの書き出しを残している"
    finally:
        monkeypatch.undo()
        importlib.reload(safe_io)



# --- 7周目の F2: 並列の書き出しで完成品の名前が衝突する ----------------------------

def _時刻を止める(monkeypatch, 時刻="20260926_101010"):
    import agents.workers.render_worker as rw

    class _止まった時計:
        @staticmethod
        def now():
            class _t:
                @staticmethod
                def strftime(fmt):
                    return 時刻
            return _t()

    monkeypatch.setattr(rw, "datetime", _止まった時計)


@pytest.mark.asyncio
async def test_worker_の完成品の名前は実走ごとに一意(tmp_path, monkeypatch):
    """**同じ秒に書き出しても衝突しない**（7周目の F2）。以前は `final_<秒>.mp4` で、
    承認済みの2本を並べて書き出すと同じ名前を取り合い、片方の承認済み動画が消えた。
    """
    from agents.pipeline_types import PipelineContext
    from agents.workers.render_worker import RenderWorker

    monkeypatch.setenv("ANTIGRAVITY_VAULT_OUTPUTS", str(tmp_path / "vault"))
    import importlib
    import safe_io
    importlib.reload(safe_io)
    try:
        _時刻を止める(monkeypatch)

        async def 書く(self, src, dst, _ctx):
            Path(dst).write_bytes(b"rendered-" + Path(src).read_bytes())
            return True

        monkeypatch.setattr(RenderWorker, "_承認を確かめる", staticmethod(lambda c: (True, "")))
        monkeypatch.setattr(RenderWorker, "_render_production_quality", 書く)
        書いた = []
        for rid in ("RUN_A", "RUN_B"):
            preview = tmp_path / f"preview_{rid}.mp4"
            preview.write_bytes(rid.encode())
            ctx = PipelineContext(video_path=str(tmp_path / "src.mp4"))
            ctx.preview_path = str(preview)
            ctx.run_dir = str(tmp_path / "runs" / rid)
            result = await RenderWorker().execute(ctx)
            assert result.success, result.detail
            書いた.append(ctx.final_path)

        assert 書いた[0] != 書いた[1], "同じ秒の書き出しが同じ名前を取り合っている"
        assert "RUN_A" in Path(書いた[0]).name and "RUN_B" in Path(書いた[1]).name
        assert Path(書いた[0]).read_bytes() == b"rendered-RUN_A"
    finally:
        monkeypatch.undo()
        importlib.reload(safe_io)


@pytest.mark.asyncio
async def test_worker_は既にある完成品を上書きしない(tmp_path, monkeypatch):
    """名前を**排他的に取る** — 既に同じ名前の完成品があれば、上書きせずに断る。"""
    from agents.pipeline_types import PipelineContext
    from agents.workers.render_worker import RenderWorker

    monkeypatch.setenv("ANTIGRAVITY_VAULT_OUTPUTS", str(tmp_path / "vault"))
    import importlib
    import safe_io
    importlib.reload(safe_io)
    try:
        _時刻を止める(monkeypatch)
        (tmp_path / "vault" / "final").mkdir(parents=True)
        先客 = tmp_path / "vault" / "final" / "final_20260926_101010_RUN_A.mp4"
        先客.write_bytes(b"approved-earlier")

        async def 書く(self, src, dst, _ctx):
            Path(dst).write_bytes(b"overwritten")
            return True

        monkeypatch.setattr(RenderWorker, "_承認を確かめる", staticmethod(lambda c: (True, "")))
        monkeypatch.setattr(RenderWorker, "_render_production_quality", 書く)
        preview = tmp_path / "preview.mp4"
        preview.write_bytes(b"p")
        ctx = PipelineContext(video_path=str(tmp_path / "src.mp4"))
        ctx.preview_path = str(preview)
        ctx.run_dir = str(tmp_path / "runs" / "RUN_A")
        result = await RenderWorker().execute(ctx)

        assert result.success is False
        assert 先客.read_bytes() == b"approved-earlier", "先にあった完成品を上書きした"
    finally:
        monkeypatch.undo()
        importlib.reload(safe_io)


@pytest.mark.asyncio
async def test_同じ実走の書き出しを重ねない(tmp_path):
    """同じ実走を2本並べて書き出さない — 書き出し中の印があれば断る（7周目の F2）。"""
    from agents.pipeline_coordinator import PipelineCoordinator
    from tests.fixtures.mock_pipeline import create_approved_run

    run_dir = Path(create_approved_run(str(tmp_path / "runs" / "RID")))
    (run_dir / ".export.lock").write_text("pid", encoding="utf-8")
    c = PipelineCoordinator()
    c.runs_dir = tmp_path / "runs"

    result = await c.export("RID")

    assert result["status"] == "error"
    assert "書き出し中" in result["error"]
