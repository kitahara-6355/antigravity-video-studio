"""V2（2026-11-10）の本線の直し — 書き出しのモード（D-47）と品質改善ループ（D-04）。

守りたい性質:

1. 書き出しのエンコード設定は `ctx.render_mode` で変わる（production と safe が同じ設定にならない）。
   実際に使った設定が文脈と書き出しの記録に残り、証跡（--trace）に出る
2. 知らないモードは控えめな側に倒す。焼き直せなかったとき（プレビューの写し）はそう記録する
3. 品質改善ループは、作り直しても点も講評も変わらなければ、同じことを繰り返さずに止まる。
   回数・点の推移・効いたかが提案に載り、証跡に出る
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from backend.revenue import approval_gate as ag

# --- 1・2: 書き出しのモード（D-47） ---------------------------------------------


@pytest.fixture
def worker_and_ffmpeg(monkeypatch):
    import video_editor_engine
    from agents.workers.render_worker import RenderWorker

    calls = []
    ffmpeg = MagicMock()
    ffmpeg.is_available.return_value = True
    ffmpeg._get_encode_args.side_effect = lambda name: ["-c:v", "libx264", "-preset", name, "-c:a", "aac"]
    ffmpeg.run_command.side_effect = lambda cmd, timeout=None: (calls.append(cmd) or (True, ""))
    monkeypatch.setattr(video_editor_engine, "video_editor", SimpleNamespace(ffmpeg=ffmpeg))
    return RenderWorker(), ffmpeg, calls


def _ctx(mode):
    return SimpleNamespace(render_mode=mode, render_encode=None, skipped_features=[])


def test_production_and_safe_use_different_encode_settings(worker_and_ffmpeg, tmp_path):
    worker, ffmpeg, calls = worker_and_ffmpeg
    used = {}
    for mode in ("production", "safe"):
        ctx = _ctx(mode)
        worker._encode_video_production_quality(str(tmp_path / "p.mp4"), str(tmp_path / f"{mode}.mp4"), ctx)
        used[mode] = ctx.render_encode
    assert used["production"]["encode"] == "quality" and used["safe"]["encode"] == "balanced"
    assert used["production"]["args"] != used["safe"]["args"]
    assert [c.args[0] for c in ffmpeg._get_encode_args.call_args_list] == ["quality", "balanced"]
    assert "quality" in calls[0] and "balanced" in calls[1]          # 実際に ffmpeg へ渡った
    assert not used["production"]["fallback"]


def test_settings_come_from_the_config_file():
    from agents.workers.render_worker import RenderWorker

    cfg = json.loads((Path(backend_path) / "config" / "render_modes.json").read_text(encoding="utf-8"))
    for mode, spec in cfg["modes"].items():
        assert RenderWorker._encode_setting(_ctx(mode)) == (mode, spec["encode"])
    assert cfg["modes"]["production"]["encode"] != cfg["modes"]["safe"]["encode"]


def test_unknown_mode_falls_to_the_modest_side():
    from agents.workers.render_worker import RenderWorker

    assert RenderWorker._encode_setting(_ctx("force")) == ("safe", "balanced")
    assert RenderWorker._encode_setting(None)[0] == "production"   # 文脈が無い呼び出しは既定のモード


def test_copy_fallback_is_recorded(worker_and_ffmpeg, tmp_path):
    worker, ffmpeg, _ = worker_and_ffmpeg
    ffmpeg.run_command.side_effect = lambda cmd, timeout=None: (False, "boom")
    src = tmp_path / "p.mp4"
    src.write_bytes(b"preview")
    ctx = _ctx("production")
    worker._encode_video_production_quality(str(src), str(tmp_path / "f.mp4"), ctx)
    assert ctx.render_encode["fallback"] is True and (tmp_path / "f.mp4").read_bytes() == b"preview"
    assert "写し" in worker._encode_label(ctx)


def _run_with_proposal(tmp_path, **ctx_kw):
    run_dir = tmp_path / "runs" / "RID"
    run_dir.mkdir(parents=True)
    preview = tmp_path / "preview.mp4"
    preview.write_bytes(b"preview-bytes")
    ctx = SimpleNamespace(video_path=str(tmp_path / "入力.mp4"), session_id="s", preview_path=str(preview),
                          metadata={"title": "題"}, quality_score=92, quality_scored=True,
                          skipped_features=[], **ctx_kw)
    ag.write_proposal(run_dir, ctx, run_id="RID", models_used=[])
    return run_dir


def test_export_record_and_trace_show_the_encode_actually_used(tmp_path):
    run_dir = _run_with_proposal(tmp_path)
    ag.approve(run_dir, synthetic=False, by="北原")
    final = tmp_path / "final.mp4"
    final.write_bytes(b"final")
    ag.write_export(run_dir, final_path=str(final), metadata_sidecar=None, quality_sidecar=None,
                    render_mode="production",
                    encode={"mode": "production", "encode": "quality", "fallback": False,
                            "args": ["-c:v", "libx264", "-preset", "slow", "-crf", "18"]})
    assert json.loads((run_dir / "export.json").read_text(encoding="utf-8"))["encode"]["encode"] == "quality"
    text = ag.trace(run_dir)[1]
    assert "エンコード    : quality（-c:v libx264 -preset slow -crf 18）" in text

    (run_dir / "export.json").unlink()
    ag.write_export(run_dir, final_path=str(final), metadata_sidecar=None, quality_sidecar=None,
                    render_mode="production")
    assert "記録なし — D-47 より前" in ag.trace(run_dir)[1]


# --- 3: 品質改善ループ（D-04） ---------------------------------------------------


def _coordinator_with_scores(scores, feedbacks):
    """採点し直すたびに scores・feedbacks を順に返す coordinator。"""
    from agents.pipeline_coordinator import PipelineCoordinator
    from agents.pipeline_types import PipelineContext, StageResult
    from agents.workers import PreviewWorker, QualityGateWorker

    pc = PipelineCoordinator()
    qg, pv = pc._find_worker(QualityGateWorker), pc._find_worker(PreviewWorker)
    ctx = PipelineContext(video_path="x.mp4", target_minutes=10, session_id="s")
    ctx.quality_score = scores[0]
    ctx.stage_results.append(StageResult(stage_name=qg.name, success=True, data={"feedback": feedbacks[0]}))
    later = list(zip(scores[1:], feedbacks[1:]))

    async def recheck(c):
        score, fb = later.pop(0)
        c.quality_score = score
        return StageResult(stage_name=qg.name, success=True, data={"feedback": fb})

    qg.execute = AsyncMock(side_effect=recheck)
    qg.verify = MagicMock(side_effect=lambda r: ctx.quality_score >= 90)
    pv.execute = AsyncMock(return_value=StageResult(stage_name=pv.name, success=True))
    pc._ensure_allowed = AsyncMock(return_value=True)
    pc._notify = AsyncMock()
    pc._notify_retry = AsyncMock()
    return pc, ctx, pv


@pytest.mark.asyncio
async def test_loop_stops_when_nothing_changes():
    """2026-09-19 の実走: 3 回回って 89 点のまま。同じ結果を繰り返さない。"""
    pc, ctx, pv = _coordinator_with_scores([89, 89, 89, 89], [["音量が小さい"]] * 4)
    assert await pc._quality_improvement_loop(ctx) is False
    assert pv.execute.await_count == 1                      # 以前は上限（3回）まで作り直していた
    assert ctx.quality_loop["iterations"] == 1 and ctx.quality_loop["scores"] == [89, 89]
    assert ctx.quality_loop["improved"] is False and "変わらない" in ctx.quality_loop["stopped"]


@pytest.mark.asyncio
async def test_loop_keeps_going_while_the_result_moves_and_reports_success():
    pc, ctx, pv = _coordinator_with_scores([85, 88, 91], [["a", "b"], ["b"], []])
    assert await pc._quality_improvement_loop(ctx) is True
    assert pv.execute.await_count == 2
    assert ctx.quality_loop == {"ran": True, "scores": [85, 88, 91], "iterations": 2,
                                "improved": True, "stopped": "合格"}


@pytest.mark.asyncio
async def test_loop_that_moves_but_never_passes_says_it_hit_the_limit():
    pc, ctx, _ = _coordinator_with_scores([80, 82, 84, 86, 88], [["a"], ["b"], ["c"], ["d"], ["e"]])
    assert await pc._quality_improvement_loop(ctx) is False
    assert ctx.quality_loop["iterations"] == pc.MAX_QUALITY_RETRIES
    assert ctx.quality_loop["stopped"] == "上限まで回した"


def test_proposal_and_trace_say_whether_the_loop_worked(tmp_path):
    run_dir = _run_with_proposal(tmp_path, quality_loop={
        "ran": True, "scores": [89, 89], "iterations": 1, "improved": False,
        "stopped": "作り直しても点も講評も変わらない（このループは動画を直す操作を持たない）"})
    assert json.loads((run_dir / "proposal.json").read_text(encoding="utf-8"))["quality_loop"]["iterations"] == 1
    assert "改善ループ  : 1 回（89 → 89 点）— **効いていない**" in ag.trace(run_dir)[1]

    plain = _run_with_proposal(tmp_path / "b")
    assert json.loads((plain / "proposal.json").read_text(encoding="utf-8"))["quality_loop"] is None
    assert "改善ループ" not in ag.trace(plain)[1]


def test_logo_overlay_reencodes_with_the_mode_setting_and_records_it(monkeypatch, tmp_path):
    """ロゴを重ねる焼き直しが、production の設定を medium/crf23 に戻さない（gate-verifier 1 周目の反例 4）。"""
    import logo_overlay
    import logo_policy
    from agents.workers.render_worker import RenderWorker

    calls = []

    class FakeOverlay:
        def apply_logo(self, **kw):
            calls.append(kw)
            Path(kw["output_path"]).write_bytes(b"x")
            return kw["output_path"]

    monkeypatch.setattr(logo_policy, "logo_enabled", lambda: True)
    monkeypatch.setattr(logo_overlay, "LogoOverlay", FakeOverlay)
    final = tmp_path / "final.mp4"
    final.write_bytes(b"v")
    args = ["-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p"]
    ctx = SimpleNamespace(render_encode={"mode": "production", "encode": "quality", "args": args, "fallback": False})
    RenderWorker()._overlay_logo(str(final), ctx)
    if not calls:
        pytest.skip("ロゴの画像が無い（branding/logos/brand_logo.png）")
    assert calls[0]["video_args"] == args
    assert ctx.render_encode["logo"] == {"reencoded": True, "args": args}


def test_logo_overlay_default_encode_is_unchanged_for_other_callers():
    import inspect

    import logo_overlay

    assert inspect.signature(logo_overlay.LogoOverlay.apply_logo).parameters["video_args"].default is None
