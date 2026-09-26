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


# --- PR3: 画面から承認する（CLI と同じ門） ------------------------------------------------

def _approve(client, run_id="RID", **body):
    payload = {"by": "claude-code", "synthetic": False, "note": ""}
    payload.update(body)
    return client.post(f"/api/r2/runs/{run_id}/approve", json=payload)


def test_画面から承認するとCLIと同じ承認の記録が残る(client, tmp_path):
    d = _run(tmp_path)

    r = _approve(client, note="画面から")

    assert r.status_code == 200, r.text
    a = json.loads((d / "approval.json").read_text(encoding="utf-8"))
    assert a["approved_by"] == "claude-code" and a["note"] == "画面から"
    assert a["ai_disclosure"]["contains_synthetic_media"] is False
    assert a["ai_disclosure"]["decided_by"] == "claude-code"
    assert ag.export_allowed(d) == (True, "")
    body = r.json()
    assert body["approved_by"] == "claude-code" and body["export_allowed"] is True


def test_承認者は既定値で埋めない(client, tmp_path):
    _run(tmp_path)
    r = _approve(client, by="  ")
    assert r.status_code == 400 and "--by" in r.json()["detail"] or "承認する人" in r.json()["detail"]
    assert not (tmp_path / "runs" / "RID" / "approval.json").exists()


def test_合成メディアの判断は人が決める(client, tmp_path):
    _run(tmp_path)
    r = client.post("/api/r2/runs/RID/approve", json={"by": "claude-code", "note": ""})
    assert r.status_code == 400 and "合成メディア" in r.json()["detail"]
    r = client.post("/api/r2/runs/RID/approve", json={"by": "claude-code", "synthetic": "yes"})
    assert r.status_code == 422, "文字列の yes を True に丸めない（CLI の --synthetic と同じ厳密さ）"
    assert not (tmp_path / "runs" / "RID" / "approval.json").exists()


def test_有効な承認があるうちは承認し直せない(client, tmp_path):
    _run(tmp_path, approve=True)
    r = _approve(client)
    assert r.status_code == 409 and "すでに承認" in r.json()["detail"]


def test_プレビューが無い提案は画面からも承認できない(client, tmp_path):
    """**見ていないものは承認できない**（4周目の反例B）は画面でも同じ門。"""
    _run(tmp_path, preview=False)
    r = _approve(client)
    assert r.status_code == 409 and "見ていないもの" in r.json()["detail"]


def test_無い実走は承認できない(client):
    assert _approve(client, "NOPE").status_code == 404


def test_人が直したメタデータは差分として承認に残る(client, tmp_path):
    """R2-C2: **人が手を入れた差分**が画面からの承認でも見える。"""
    d = _run(tmp_path)

    r = client.get("/api/r2/runs/RID/working")
    assert r.status_code == 200
    w = r.json()["outputs"][0]
    assert w["name"] == "youtube_metadata" and json.loads(w["working"])["title"] == "AI の題"

    text = json.dumps({"title": "人が直した題"}, ensure_ascii=False, indent=2) + "\n"
    r = client.put("/api/r2/runs/RID/working/youtube_metadata", json={"text": text})
    assert r.status_code == 200, r.text
    assert (d / "working" / "youtube_metadata.json").read_text(encoding="utf-8") == text

    r = _approve(client)
    assert r.status_code == 200
    e = r.json()["edits"][0]
    assert e["changed"] is True and '+  "title": "人が直した題"' in e["diff"]


def test_直す現物はJSONでなければ受けない(client, tmp_path):
    _run(tmp_path)
    r = client.put("/api/r2/runs/RID/working/youtube_metadata", json={"text": "{not json"})
    assert r.status_code == 400
    r = client.put("/api/r2/runs/RID/working/nope", json={"text": "{}"})
    assert r.status_code == 404


def test_書き出した後は直せない(client, tmp_path):
    d = _run(tmp_path, approve=True)
    ag.write_export(d, final_path=None, metadata_sidecar=None, quality_sidecar=None, render_mode="production")
    r = client.put("/api/r2/runs/RID/working/youtube_metadata", json={"text": "{}"})
    assert r.status_code == 409


def test_画面に承認の操作がある(client):
    body = client.get("/r2/approve").text
    for 語 in ("承認する", "合成メディア", "承認する人", "直す"):
        assert 語 in body, 語
