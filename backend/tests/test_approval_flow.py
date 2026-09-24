"""R2-C1: 承認していない動画は書き出せない — 本線は提案で止まる（2026-09-19）。

設計 docs/specs/2026-09-19-r2-approval-design.md。

- 本線（agents の coordinator）は**書き出しの工程を呼ばずに**、提案を残して `awaiting_approval` で止まる
- **品質改善ループは提案の前に回る**（D-41）。以前はループが書き出しの後に回っていて、ループで合格しても
  書き出しは不合格のときの safe モードのまま残っていた。書き出しのモードはループの後の品質で決まる
- 提案（`output/runs/<run_id>/proposal.json`）には、承認と書き出しに要るものがそろう
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.pipeline_coordinator import PipelineCoordinator
from agents.pipeline_types import PipelineContext, StageResult

METADATA = {"title": "AI が付けた題", "description": "AI が書いた説明", "tags": ["a", "b"]}


def _coordinator(tmp_path):
    """全 worker を差し替えた司令塔。**実際の処理はしない。**

    プレビューは一時ディレクトリに小さなファイルを作り、YouTube 最適化はメタデータを置く。
    書き出しの工程が呼ばれたら `rendered` に残す（呼ばれてはいけない）。
    """
    c = PipelineCoordinator()
    c.runs_dir = tmp_path / "runs"
    c.rendered = []
    c.落とす = set()
    preview = tmp_path / "preview.mp4"

    for w in c.workers:
        名前 = type(w).__name__

        async def _fake(ctx, _w=w, _名前=名前):
            if _名前 == "PreviewWorker":
                preview.write_bytes(b"preview-bytes")
                ctx.preview_path = str(preview)
            elif _名前 == "YouTubeOptWorker":
                ctx.metadata = dict(METADATA)
            elif _名前 == "RenderWorker":
                c.rendered.append(ctx.render_mode)
                final = tmp_path / "final.mp4"
                final.write_bytes(b"final-bytes")
                ctx.final_path = str(final)
            elif _名前 in c.落とす:
                return StageResult(stage_name=_w.name, success=False, detail="落ちた")
            return StageResult(stage_name=_w.name, success=True, detail="やった")

        w.execute = _fake
        w.verify = lambda r: r.success
    return c


def _run(coordinator, tmp_path, **patches):
    """ハーネスと後処理は止めて走らせる（test_agents_run_record.py と同じ形）。"""
    ctx = PipelineContext(video_path=str(tmp_path / "入力.mp4"), session_id="test-session")
    with patch.object(coordinator, "_init_harness", return_value=None), \
            patch.object(coordinator, "_run_retention_analysis", new=AsyncMock(return_value=None)):
        if "optimize" in patches:
            with patch.object(coordinator, "_optimize_quality", new=patches["optimize"]):
                return asyncio.run(coordinator.execute(ctx))
        return asyncio.run(coordinator.execute(ctx))


def _run_dir(tmp_path):
    dirs = sorted(p.parent for p in (tmp_path / "runs").glob("*/run.json"))
    assert dirs, "実行記録が1件も書かれていません"
    return dirs[-1]


@pytest.fixture(autouse=True)
def 学習の副作用を止める(monkeypatch):
    """実走のたびに学習の記憶（追跡ファイル）が書き換わる（D-44）。テストでは必ず止める。"""
    monkeypatch.setenv("AVS_SKIP_LEARNING_SIDE_EFFECTS", "1")


def test_本線は提案で止まり書き出さない(tmp_path):
    c = _coordinator(tmp_path)
    res = _run(c, tmp_path)

    assert res["status"] == "awaiting_approval", res.get("status")
    assert not c.rendered, "承認の前に書き出しの工程を呼んでいます"
    assert res.get("final_path") is None
    run = json.loads((_run_dir(tmp_path) / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "awaiting_approval"
    assert "render" not in [s["name"] for s in run["stages"]]


def test_改善ループは提案の前に回り書き出しのモードはループの後で決まる(tmp_path):
    """D-41: ループで合格したら、書き出しは safe ではなく production になる。"""
    順番 = []

    async def _ループで合格する(ctx, harness, perf_manager):
        順番.append("ループ")
        ctx.quality_score = 95
        ctx.quality_scored = True

    c = _coordinator(tmp_path)
    res = _run(c, tmp_path, optimize=_ループで合格する)

    assert 順番 == ["ループ"], "品質改善が提案の前に回っていません"
    proposal = json.loads((_run_dir(tmp_path) / "proposal.json").read_text(encoding="utf-8"))
    assert proposal["quality"] == {"score": 95, "scored": True, "passed": True}
    assert proposal["render_mode"] == "production"
    assert res["status"] == "awaiting_approval"


def test_ループで不合格なら書き出しのモードはsafe(tmp_path):
    async def _不合格のまま(ctx, harness, perf_manager):
        ctx.quality_score = 89
        ctx.quality_scored = True

    c = _coordinator(tmp_path)
    _run(c, tmp_path, optimize=_不合格のまま)
    proposal = json.loads((_run_dir(tmp_path) / "proposal.json").read_text(encoding="utf-8"))
    assert proposal["quality"]["passed"] is False
    assert proposal["render_mode"] == "safe"


def test_提案には承認と書き出しに要るものがそろう(tmp_path):
    c = _coordinator(tmp_path)
    res = _run(c, tmp_path)
    d = _run_dir(tmp_path)
    proposal = json.loads((d / "proposal.json").read_text(encoding="utf-8"))

    assert proposal["run_id"] == d.name
    assert proposal["status"] == "awaiting_approval"
    assert proposal["video_path"].endswith("入力.mp4")
    preview = tmp_path / "preview.mp4"
    assert proposal["preview"] == {
        "path": str(preview), "sha256": hashlib.sha256(preview.read_bytes()).hexdigest()}
    assert proposal["models_used"], "どのモデルの提案かが残っていません"
    assert proposal["created_at"]
    assert res.get("run_id") == d.name
    assert res.get("proposal_path") == str(d / "proposal.json")


def test_提案を残せなければ承認待ちにしない(tmp_path):
    """残せなかった提案は承認も書き出しもできない。**承認待ちのまま放置される実走を作らない。**"""
    c = _coordinator(tmp_path)
    with patch.object(c, "_write_proposal", return_value=None):
        res = _run(c, tmp_path)
    assert res["status"] == "error"
    assert "提案を残せませんでした" in res["error"]
    run = json.loads((_run_dir(tmp_path) / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "failed"


def test_CLIは承認待ちを失敗にせず次の手順を出す(tmp_path, monkeypatch, capsys):
    from agents import pipeline_coordinator as pc

    video = tmp_path / "入力.mp4"
    video.write_bytes(b"x")

    async def _提案で止まる(self, ctx):
        return {"status": "awaiting_approval", "duration_seconds": 1.0, "final_path": None,
                "preview_path": "p.mp4", "quality_score": 89, "run_id": "RID",
                "proposal_path": "runs/RID/proposal.json",
                "health": {"skipped_features": [], "warnings": []}}

    monkeypatch.setattr(pc.PipelineCoordinator, "execute", _提案で止まる)
    monkeypatch.setattr("backend.cost_guard.load_env", lambda: None)
    rc = pc.main([str(video), "--target-minutes", "1",
                  "--runs-dir", str(tmp_path / "runs"), "--no-ledger"])
    out = capsys.readouterr().out
    assert rc == 0, "承認待ちは失敗ではありません"
    assert "approval_gate --approve RID" in out
    assert "approval_gate --export RID" in out


def test_AIのメタデータは直す前の写しと直す現物に分けて残る(tmp_path):
    """R2-C2 の準備: 人が手を入れた差分は、写し（proposal/）と現物（working/）の差で取る。"""
    c = _coordinator(tmp_path)
    _run(c, tmp_path)
    d = _run_dir(tmp_path)
    proposal = json.loads((d / "proposal.json").read_text(encoding="utf-8"))

    写し = d / "proposal" / "youtube_metadata.json"
    現物 = d / "working" / "youtube_metadata.json"
    assert json.loads(写し.read_text(encoding="utf-8")) == METADATA
    assert 現物.read_bytes() == 写し.read_bytes()
    assert {"name": "youtube_metadata", "proposal": "proposal/youtube_metadata.json",
            "working": "working/youtube_metadata.json",
            "sha256": hashlib.sha256(写し.read_bytes()).hexdigest()} in proposal["ai_outputs"]


# --- 書き出し（承認の後） -----------------------------------------------------

def _export(coordinator, run_id):
    with patch.object(coordinator, "_run_retention_analysis", new=AsyncMock(return_value=None)):
        return asyncio.run(coordinator.export(run_id))


async def _合格(ctx, harness, perf_manager):
    ctx.quality_score = 95
    ctx.quality_scored = True
    ctx.quality_feedback = ["よい"]


def test_承認しなければ書き出さず記録は承認待ちのまま(tmp_path):
    c = _coordinator(tmp_path)
    res = _run(c, tmp_path, optimize=_合格)
    before = (_run_dir(tmp_path) / "run.json").read_bytes()

    out = _export(c, res["run_id"])
    assert out["status"] == "error" and "承認されていません" in out["error"]
    assert not c.rendered, "承認していない動画を書き出しています"
    assert (_run_dir(tmp_path) / "run.json").read_bytes() == before, "断った書き出しで記録を書き換えています"


def test_承認すれば書き出して同じ記録を閉じ直す(tmp_path):
    from backend.revenue import approval_gate as ag

    c = _coordinator(tmp_path)
    res = _run(c, tmp_path, optimize=_合格)
    d = _run_dir(tmp_path)
    現物 = d / "working" / "youtube_metadata.json"
    現物.write_text(json.dumps(dict(METADATA, title="人が直した題"), ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    ag.approve(d, synthetic=False, by="北原")

    out = _export(c, res["run_id"])
    assert out["status"] == "completed", out.get("error")
    assert c.rendered == ["production"], "ループで合格したのに safe で書き出しています（D-41）"

    run = json.loads((d / "run.json").read_text(encoding="utf-8"))
    assert run["run_id"] == res["run_id"] and run["status"] == "completed"
    assert "render" in [s["name"] for s in run["stages"]]

    ex = json.loads((d / "export.json").read_text(encoding="utf-8"))
    final = tmp_path / "final.mp4"
    assert ex["final"] == {"path": str(final), "sha256": hashlib.sha256(final.read_bytes()).hexdigest()}
    assert ex["approval_sha256"] == hashlib.sha256((d / "approval.json").read_bytes()).hexdigest()

    サイドカー = json.loads(Path(ex["metadata_sidecar"]).read_text(encoding="utf-8"))
    assert サイドカー["title"] == "人が直した題", "承認した（人が直した）メタデータで書き出していません"
    assert サイドカー["ai_disclosure"]["contains_synthetic_media"] is False


def test_前半で落ちた工程があれば書き出しても完走とは呼ばない(tmp_path):
    from backend.revenue import approval_gate as ag

    c = _coordinator(tmp_path)
    c.落とす = {"ProofreadWorker"}
    res = _run(c, tmp_path, optimize=_合格)
    assert res["status"] == "awaiting_approval"
    ag.approve(_run_dir(tmp_path), synthetic=False, by="北原")

    out = _export(c, res["run_id"])
    assert out["status"] == "degraded"


def test_書き出しの後は中間成果物を前半と合わせて数える(tmp_path):
    """前半でプレビューが使った字幕を、書き出しの時点で『使われていない』に上書きしない（R1.5-C3）。"""
    from backend.revenue import approval_gate as ag

    c = _coordinator(tmp_path)
    res = _run(c, tmp_path, optimize=_合格)
    d = _run_dir(tmp_path)
    前半 = {r["name"]: r for r in json.loads((d / "run.json").read_text(encoding="utf-8"))["intermediates"]}
    ag.approve(d, synthetic=False, by="北原")
    _export(c, res["run_id"])

    後 = {r["name"]: r for r in json.loads((d / "run.json").read_text(encoding="utf-8"))["intermediates"]}
    for name, row in 後.items():
        assert row["produced"] == 前半[name]["produced"], f"{name}: 作られたかが書き換わっています"
        if 前半[name]["consumed"]:
            assert row["consumed"], f"{name}: 前半で使われたのに使われていないことになっています"
    assert 後["youtube_metadata"]["consumed"], "書き出しでサイドカーに届いたのに数えていません"


def test_書き出しの工程の直前でも門を通す(tmp_path):
    """export の入口を通らない経路（画面の強制書き出しなど）でも、承認が無ければ書き出さない。"""
    from backend.revenue.run_record import RunRecorder

    c = _coordinator(tmp_path)
    res = _run(c, tmp_path, optimize=_合格)
    c._recorder = RunRecorder.reopen(res["run_id"], runs_dir=tmp_path / "runs")
    ctx = PipelineContext(video_path=str(tmp_path / "入力.mp4"),
                          preview_path=str(tmp_path / "preview.mp4"))
    asyncio.run(c._execute_final_rendering_stage(ctx, None, None))

    assert not c.rendered, "書き出しの工程の直前に門がありません"
    last = ctx.stage_results[-1]
    assert last.success is False and "承認" in last.detail


def test_二度は書き出さない(tmp_path):
    """書き出した後にもう一度書き出すと、最終の動画と記録を上書きしてしまう。"""
    from backend.revenue import approval_gate as ag

    c = _coordinator(tmp_path)
    res = _run(c, tmp_path, optimize=_合格)
    ag.approve(_run_dir(tmp_path), synthetic=False, by="北原")
    assert _export(c, res["run_id"])["status"] == "completed"

    again = _export(c, res["run_id"])
    assert again["status"] == "error" and "書き出し済み" in again["error"]
    assert c.rendered == ["production"], "二度書き出しています"


def test_前半で落ちた工程と警告は書き出した後の記録にも残る(tmp_path):
    """書き出しで記録を閉じ直しても、提案までに落ちた工程を消さない（R1.5-C1b を割らない）。"""
    from backend.revenue import approval_gate as ag

    c = _coordinator(tmp_path)
    c.落とす = {"ProofreadWorker"}

    async def _警告つきで合格(ctx, harness, perf_manager):
        await _合格(ctx, harness, perf_manager)
        ctx.warnings.append("前半の警告")

    res = _run(c, tmp_path, optimize=_警告つきで合格)
    ag.approve(_run_dir(tmp_path), synthetic=False, by="北原")
    out = _export(c, res["run_id"])

    rec = json.loads((_run_dir(tmp_path) / "run.json").read_text(encoding="utf-8"))
    assert "proofread" in rec["health"]["failed_stages"], rec["health"]
    assert "前半の警告" in rec["health"]["warnings"]
    assert "前半の警告" in out["health"]["warnings"]
