"""R2-C5（PR2）: 承認画面の読み取り API — **どのモデルで出たか・なぜそのモデルか**が見える。

画面は FastAPI が返す1枚の HTML。人が使う面は API で固める（frontend/ には CI が無い）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.revenue import approval_gate as ag


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.r2_approval_router import page_router, router

    monkeypatch.setenv("AVS_RUNS_DIR", str(tmp_path / "runs"))
    app = FastAPI()
    app.include_router(router)
    app.include_router(page_router)
    return TestClient(app)


def _run(tmp_path, run_id="RID", *, approve=False, stages=None, preview=True):
    d = tmp_path / "runs" / run_id
    d.mkdir(parents=True)
    stages = stages if stages is not None else [
        {"name": "transcribe", "model": "local:whisper", "status": "success"},
        {"name": "proofread", "model": "gemini-3.6-flash", "tier": "standard", "status": "success",
         "model_reason": "fallback", "models_observed": ["gemini-3.5-flash-lite"], "model_mismatch": True,
         "fallbacks": [{"from": "gemini-3.6-flash", "to": "gemini-3.5-flash-lite",
                        "reason": "503:サーバー混雑", "attempts": 3}], "calls": 1, "cost_jpy": 0.12},
        {"name": "youtube_opt", "model": "gemini-3.6-flash", "tier": "standard", "status": "success",
         "model_reason": "declared", "fallbacks": [], "calls": 1, "cost_jpy": 0.05},
    ]
    (d / "run.json").write_text(json.dumps({"run_id": run_id, "status": "awaiting_approval",
                                            "started_at": "2026-09-26T00:00:00+00:00",
                                            "inputs": {"video_path": "in.mp4"}, "stages": stages},
                                           ensure_ascii=False), encoding="utf-8")
    pv = tmp_path / f"preview_{run_id}.mp4"
    if preview:
        pv.write_bytes(b"preview-bytes-" + run_id.encode())
    ctx = SimpleNamespace(video_path=str(tmp_path / "in.mp4"), session_id="s",
                          preview_path=str(pv) if preview else None,
                          metadata={"title": "AI の題"}, quality_score=92, quality_scored=True,
                          skipped_features=[], warnings=[])
    ag.write_proposal(d, ctx, run_id=run_id, models_used=["gemini-3.6-flash", "local:whisper"])
    if approve:
        ag.approve(d, synthetic=False, by="claude-code")
    return d


def test_一覧は新しい順に実走を返し品質は出所を名乗る(client, tmp_path):
    _run(tmp_path, "20260926T000001-0000")
    _run(tmp_path, "20260926T000002-0000", approve=True)

    r = client.get("/api/r2/runs")

    assert r.status_code == 200
    runs = r.json()["runs"]
    assert [x["run_id"] for x in runs] == ["20260926T000002-0000", "20260926T000001-0000"]
    assert runs[0]["approved"] is True and runs[1]["approved"] is False
    q = runs[0]["quality"]
    assert q["score"] == 92 and q["is_real"] is True and q["data_source"] == "measured"


def test_一覧は実走が無ければ空(client):
    r = client.get("/api/r2/runs")
    assert r.status_code == 200 and r.json()["runs"] == []


def test_詳細に工程ごとのモデルと降格の理由が出る(client, tmp_path):
    """**なぜそのモデルになったか**（D-39）が画面の API から見える。"""
    _run(tmp_path)

    d = client.get("/api/r2/runs/RID").json()

    by = {s["name"]: s for s in d["stages"]}
    assert by["proofread"]["model_reason"] == "fallback"
    assert by["proofread"]["fallbacks"][0]["reason"] == "503:サーバー混雑"
    assert by["proofread"]["tier"] == "standard" and by["proofread"]["model_mismatch"] is True
    assert by["youtube_opt"]["model_reason"] == "declared"
    assert d["models_used"] == ["gemini-3.6-flash", "local:whisper"]
    assert d["proposal"]["preview_available"] is True
    assert d["approval"] is None and d["export"] is None
    assert d["export_allowed"] is False and "承認されていません" in d["export_blocker"]


def test_理由の記録が無い古い実走は推測で埋めない(client, tmp_path):
    _run(tmp_path, stages=[{"name": "proofread", "model": "gemini-3.6-flash", "status": "success"},
                           {"name": "soul", "model": "gemini-3.7-flash", "status": "success",
                            "model_unverified": True}])

    d = client.get("/api/r2/runs/RID").json()

    assert d["stages"][0]["model_reason"] == "unrecorded"
    assert d["stages"][1]["model_reason"] == "unverified"


def test_承認済みなら承認者と開示と書き出しの可否が出る(client, tmp_path):
    _run(tmp_path, approve=True)

    d = client.get("/api/r2/runs/RID").json()

    assert d["approval"]["approved_by"] == "claude-code"
    assert d["approval"]["ai_disclosure"]["contains_synthetic_media"] is False
    assert d["export_allowed"] is True and d["export_blocker"] is None


def test_採点していない提案の品質はNoneで出所を名乗る(client, tmp_path):
    d = _run(tmp_path)
    p = json.loads((d / "proposal.json").read_text(encoding="utf-8"))
    p["quality"] = {"score": 0, "scored": False, "passed": False}
    (d / "proposal.json").write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")

    q = client.get("/api/r2/runs/RID").json()["quality"]

    assert q["score"] is None and q["is_real"] is False and q["data_source"] == "unavailable"


def test_プレビューは提案が指す実物を返す(client, tmp_path):
    _run(tmp_path)

    r = client.get("/api/r2/runs/RID/preview")

    assert r.status_code == 200
    assert r.content == b"preview-bytes-RID"
    assert r.headers["content-type"].startswith("video/mp4")


def test_プレビューが無ければ404(client, tmp_path):
    _run(tmp_path, preview=False)
    r = client.get("/api/r2/runs/RID/preview")
    assert r.status_code == 404


def test_無い実走は404(client):
    assert client.get("/api/r2/runs/NOPE").status_code == 404
    assert client.get("/api/r2/runs/NOPE/preview").status_code == 404


def test_実走IDに区切りや上位参照は受けない(client, tmp_path):
    """記録の置き場の外を読まない。"""
    (tmp_path / "secret").mkdir()
    (tmp_path / "secret" / "run.json").write_text("{}", encoding="utf-8")
    for bad in ("..%2Fsecret", "../secret", "a/b", ".hidden", "%2E%2E"):
        r = client.get(f"/api/r2/runs/{bad}")
        assert r.status_code == 404, bad


def test_画面は依存なしの1枚でAPIを呼ぶ(client):
    r = client.get("/r2/approve")

    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    body = r.text
    assert "承認画面" in body
    assert "/api/r2/runs" in body
    assert "<script src=" not in body and "cdn" not in body.lower(), "外部の依存を読み込んでいる"
    assert "なぜこのモデルか" in body
