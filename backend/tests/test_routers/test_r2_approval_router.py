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


# --- PR4: 昇格してやり直す ------------------------------------------------------------

@pytest.fixture
def policy_sandbox(tmp_path, monkeypatch):
    """現物の段の設定・上書き・履歴に触らない。"""
    from backend import model_policy

    config = {"text_generation": {"default_model": "m-standard",
                                  "tier_order": ["batch", "standard", "premium", "pro"],
                                  "tiers": {"batch": {"model": "m-batch"}, "standard": {"model": "m-standard"},
                                            "premium": {"model": "m-premium"}, "pro": {"model": "m-pro"}}},
              "task_mapping": {"proofreader": "standard", "youtube_optimization": "premium"}}
    (tmp_path / "model_config.json").write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(model_policy, "CONFIG_PATH", tmp_path / "model_config.json")
    monkeypatch.setattr(model_policy, "OVERRIDES_PATH", tmp_path / "model_overrides.json")
    monkeypatch.setattr(model_policy, "HISTORY_PATH", tmp_path / "history.jsonl")
    import importlib
    r2 = importlib.import_module("routers.r2_approval_router")   # routers/__init__ の同名 APIRouter と区別する
    monkeypatch.setattr(r2, "_PRICES", {"m-batch": (0.1, 0.4, True), "m-standard": (1.5, 7.5, True),
                                        "m-premium": (0.75, 3.75, True), "m-pro": (2.0, 12.0, False)})
    return tmp_path


def _stages_with_task():
    return [{"name": "transcribe", "model": "local:whisper", "status": "success"},
            {"name": "proofread", "model": "m-standard", "tier": "standard", "task": "proofreader",
             "status": "success", "model_reason": "declared", "fallbacks": [], "calls": 2, "cost_jpy": 0.30},
            {"name": "youtube_opt", "model": "m-premium", "tier": "premium", "task": "youtube_optimization",
             "status": "success", "model_reason": "declared", "fallbacks": [], "calls": 1, "cost_jpy": 0.10}]


def test_見積もりだけなら段は動かない(client, tmp_path, policy_sandbox):
    _run(tmp_path, stages=_stages_with_task())

    r = client.post("/api/r2/runs/RID/escalate", json={"stage": "proofread", "reason": "字幕が固い", "dry_run": True})

    assert r.status_code == 200, r.text
    b = r.json()
    assert b["from"] == {"tier": "standard", "model": "m-standard"}
    assert b["to"] == {"tier": "premium", "model": "m-premium"}
    assert b["billable"] is False and b["estimate_jpy"] == pytest.approx(0.30 * 0.5, abs=1e-4)
    assert b["applied"] is False
    assert not (policy_sandbox / "model_overrides.json").exists()


def test_昇格すると段の上書きと履歴と実走の記録に残る(client, tmp_path, policy_sandbox):
    d = _run(tmp_path, stages=_stages_with_task())

    r = client.post("/api/r2/runs/RID/escalate", json={"stage": "proofread", "reason": "字幕が固い"})

    assert r.status_code == 200, r.text
    assert r.json()["applied"] is True and r.json()["to"]["tier"] == "premium"
    ov = json.loads((policy_sandbox / "model_overrides.json").read_text(encoding="utf-8"))
    assert ov["tasks"]["proofreader"]["tier"] == "premium" and ov["tasks"]["proofreader"]["reason"] == "字幕が固い"
    hist = [json.loads(line) for line in (policy_sandbox / "history.jsonl").read_text(encoding="utf-8").splitlines()]
    assert hist[-1]["action"] == "escalate" and hist[-1]["task"] == "proofreader"
    esc = json.loads((d / "escalations.json").read_text(encoding="utf-8"))
    assert esc[0]["stage"] == "proofread" and esc[0]["to"]["tier"] == "premium" and esc[0]["reason"] == "字幕が固い"
    assert client.get("/api/r2/runs/RID").json()["escalations"][0]["stage"] == "proofread"


def test_理由が無ければ昇格できない(client, tmp_path, policy_sandbox):
    _run(tmp_path, stages=_stages_with_task())
    r = client.post("/api/r2/runs/RID/escalate", json={"stage": "proofread", "reason": "  "})
    assert r.status_code == 400 and not (policy_sandbox / "model_overrides.json").exists()


def test_AIの工程でなければ昇格できない(client, tmp_path, policy_sandbox):
    _run(tmp_path, stages=_stages_with_task())
    r = client.post("/api/r2/runs/RID/escalate", json={"stage": "transcribe", "reason": "遅い"})
    assert r.status_code == 400 and "段" in r.json()["detail"]
    r = client.post("/api/r2/runs/RID/escalate", json={"stage": "nope", "reason": "x"})
    assert r.status_code == 404


def test_課金の段へは予算が無ければ上げられない(client, tmp_path, policy_sandbox, monkeypatch):
    """**pro は課金。** 予算が無い・足りないなら押せない（fail-closed・憲法第3条）。"""
    from backend import cost_guard
    _run(tmp_path, stages=_stages_with_task())

    monkeypatch.setattr(cost_guard, "load_active_budget", lambda *a, **k: None)
    r = client.post("/api/r2/runs/RID/escalate", json={"stage": "youtube_opt", "reason": "題が弱い"})
    assert r.status_code == 402, r.text
    assert r.json()["detail"]["billable"] is True and "予算" in r.json()["detail"]["why"]
    assert not (policy_sandbox / "model_overrides.json").exists()

    monkeypatch.setattr(cost_guard, "load_active_budget",
                        lambda *a, **k: {"id": "B", "limit_jpy": 1.0, "spent_jpy": 0.9})
    r = client.post("/api/r2/runs/RID/escalate", json={"stage": "youtube_opt", "reason": "題が弱い"})
    assert r.status_code == 402 and "残" in r.json()["detail"]["why"]


def test_課金の段でも予算があれば見積もりつきで上がる(client, tmp_path, policy_sandbox, monkeypatch):
    from backend import cost_guard
    _run(tmp_path, stages=_stages_with_task())
    monkeypatch.setattr(cost_guard, "load_active_budget",
                        lambda *a, **k: {"id": "B", "limit_jpy": 1000.0, "spent_jpy": 4.71})

    r = client.post("/api/r2/runs/RID/escalate", json={"stage": "youtube_opt", "reason": "題が弱い"})

    assert r.status_code == 200, r.text
    b = r.json()
    assert b["billable"] is True and b["budget"]["id"] == "B" and b["budget"]["remaining_jpy"] == pytest.approx(995.29)
    assert b["estimate_jpy"] == pytest.approx(0.10 * (2.0 + 12.0) / (0.75 + 3.75), abs=1e-4)


def test_やり直しは同じ素材で新しい実走を起こし古い記録に結ぶ(client, tmp_path, policy_sandbox, monkeypatch):
    d = _run(tmp_path, stages=_stages_with_task())
    (tmp_path / "in.mp4").write_bytes(b"video")
    called = {}

    async def fake_start(req):
        called["paths"] = req.video_paths
        called["minutes"] = req.target_minutes
        return {"status": "started", "session_id": "SESSION-NEW", "video_count": 1}

    import importlib
    pr = importlib.import_module("routers.pipeline_router")
    monkeypatch.setattr(pr, "start_pipeline", fake_start)

    r = client.post("/api/r2/runs/RID/rerun", json={"reason": "昇格した proofread でやり直す"})

    assert r.status_code == 200, r.text
    assert r.json()["session_id"] == "SESSION-NEW"
    assert called["paths"] == [str(tmp_path / "in.mp4")]
    rr = json.loads((d / "rerun.json").read_text(encoding="utf-8"))
    assert rr["session_id"] == "SESSION-NEW" and rr["reason"] == "昇格した proofread でやり直す"
    assert client.get("/api/r2/runs/RID").json()["rerun"]["session_id"] == "SESSION-NEW"

    # 新しい実走は session_id で古い実走に結ばれる
    _run(tmp_path, "RID2", stages=_stages_with_task())
    run2 = json.loads((tmp_path / "runs" / "RID2" / "run.json").read_text(encoding="utf-8"))
    run2["inputs"]["session_id"] = "SESSION-NEW"
    (tmp_path / "runs" / "RID2" / "run.json").write_text(json.dumps(run2), encoding="utf-8")
    runs = {x["run_id"]: x for x in client.get("/api/r2/runs").json()["runs"]}
    assert runs["RID2"]["supersedes"] == "RID" and runs["RID"]["superseded_by"] == "RID2"


def test_素材が無ければやり直せない(client, tmp_path, policy_sandbox):
    _run(tmp_path, stages=_stages_with_task())
    r = client.post("/api/r2/runs/RID/rerun", json={"reason": "x"})
    assert r.status_code == 404 and "素材" in r.json()["detail"]


def test_やり直しは既に走っていれば断る(client, tmp_path, policy_sandbox, monkeypatch):
    from fastapi import HTTPException
    _run(tmp_path, stages=_stages_with_task())
    (tmp_path / "in.mp4").write_bytes(b"video")

    async def busy(req):
        raise HTTPException(400, "パイプラインは既に実行中です")

    import importlib
    pr = importlib.import_module("routers.pipeline_router")
    monkeypatch.setattr(pr, "start_pipeline", busy)
    r = client.post("/api/r2/runs/RID/rerun", json={"reason": "x"})
    assert r.status_code == 409


def test_画面に昇格とやり直しの操作がある(client):
    body = client.get("/r2/approve").text
    for 語 in ("1段上げる", "やり直す", "見積もり"):
        assert 語 in body, 語


# --- 検証1周目（U1・U2）: 実測が宣言と違う／一度も呼ばれていない、を「宣言どおり」と言わない -----------

def test_実測が宣言と違えば画面のAPIは実際に動いたモデルを出す(client, tmp_path):
    _run(tmp_path, stages=[
        {"name": "proofread", "model": "gemini-3.6-flash", "tier": "standard", "status": "success",
         "model_reason": "mismatch", "models_observed": ["gemini-3.5-flash-lite"], "model_mismatch": True,
         "fallbacks": [], "calls": 1, "cost_jpy": 0.1},
        {"name": "youtube_opt", "model": "gemini-3.6-flash", "tier": "standard", "status": "success",
         "model_reason": "unverified", "models_observed": [], "model_unverified": True, "fallbacks": []}])

    by = {s["name"]: s for s in client.get("/api/r2/runs/RID").json()["stages"]}

    assert by["proofread"]["model_reason"] == "mismatch"
    assert by["proofread"]["models_observed"] == ["gemini-3.5-flash-lite"]
    assert by["youtube_opt"]["model_reason"] == "unverified"
    body = client.get("/r2/approve").text
    assert "実測が宣言と違う" in body and "未検証" in body and "実際に動いた" in body


def test_スタブに替わった工程は画面でも宣言どおりと言わない(client, tmp_path):
    _run(tmp_path, stages=[{"name": "youtube_opt", "model": "gemini-3.6-flash", "tier": "standard",
                            "status": "success", "model_reason": "stub", "ai_skipped": True,
                            "models_observed": ["gemini-3.6-flash"], "fallbacks": [], "calls": 1, "cost_jpy": 0.01}])
    d = client.get("/api/r2/runs/RID").json()
    assert d["stages"][0]["model_reason"] == "stub" and d["stages"][0]["ai_skipped"] is True
    assert "スタブ" in client.get("/r2/approve").text
