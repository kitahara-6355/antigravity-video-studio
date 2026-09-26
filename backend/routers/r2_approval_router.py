"""R2-C5: 承認画面 — **その提案がどのモデルで出たか・なぜそのモデルか**が見える（2026-09-26）。

計画: docs/plans/2026-09-26-master-plan-100.md の M1。設計: docs/specs/2026-09-26-r2-c5-approval-screen-design.md。

- 画面は **FastAPI が返す1枚の HTML**（依存なし）。既存の React（frontend/）には CI が無いので、
  人が使う画面は API を pytest で固め、画面は薄く保つ（2026-09-26 ユーザー決定）
- **読むだけ**（PR2）。承認（PR3）と昇格・やり直し（PR4）は後の PR で足す。承認の門は CLI と
  同じ関数（`approval_gate.approve` / `export_allowed`）を呼ぶ — 門を2つにしない
- 実走の記録は `run.json`（工程ごとのモデル・段・`model_reason`・`fallbacks`。D-39）と
  `proposal.json` / `approval.json` / `export.json`（`approval_gate`）から読む。**書かない**
- 品質の点数は 4カテゴリ（R1.5-C4b）なので、`is_real` / `data_source` を同じ応答に載せる
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from revenue.approval_gate import (
    APPROVAL, EXPORT, PROPOSAL, _read_json, export_allowed,
)
from revenue.run_record import RUNS_DIR

router = APIRouter(prefix="/api/r2", tags=["R2 承認"])
page_router = APIRouter(tags=["R2 承認"])

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")


def _runs_dir() -> Path:
    return Path(os.getenv("AVS_RUNS_DIR") or RUNS_DIR)


def _run_dir(run_id: str) -> Path:
    # **実走 ID は名前だけ**（`..` や区切りは受けない）。記録の置き場の外を読まない
    if not _RUN_ID.match(run_id):
        raise HTTPException(status_code=404, detail=f"実行記録がありません: {run_id}")
    d = _runs_dir() / run_id
    if not (d / "run.json").is_file():
        raise HTTPException(status_code=404, detail=f"実行記録がありません: {run_id}")
    return d


def _read(path: Path) -> dict | None:
    return _read_json(path) if path.is_file() else None


def _quality(proposal: dict | None) -> dict:
    """提案の品質を、**出所を名乗って**返す（R1.5-C4b）。採点していなければ None。"""
    q = (proposal or {}).get("quality") or {}
    scored = bool(q.get("scored"))
    return {
        "score": q.get("score") if scored else None,
        "passed": bool(q.get("passed")) if scored else None,
        "scored": scored,
        "is_real": scored,
        "data_source": "measured" if scored else "unavailable",
        "note": ("ローカルの品質ゲートで採点した点数（提案の quality）" if scored
                 else "**採点されていません。** この提案に品質ゲートは通っていません"),
    }


def _stage_view(stage: dict) -> dict:
    """工程1つ分: モデル・段・**なぜそのモデルか**（D-39）。"""
    reason = stage.get("model_reason") or ""
    if not reason:
        # D-39 より前の実走。理由の記録が無いことを名乗る（推測で埋めない）
        reason = "unverified" if stage.get("model_unverified") else "unrecorded"
    return {
        "name": stage.get("name"),
        "status": stage.get("status"),
        "model": stage.get("model") or None,
        "tier": stage.get("tier") or None,
        "task": stage.get("task") or None,
        "models_observed": list(stage.get("models_observed") or []),
        "model_reason": reason,
        "fallbacks": list(stage.get("fallbacks") or []),
        "model_mismatch": bool(stage.get("model_mismatch")),
        "model_unverified": bool(stage.get("model_unverified")),
        "calls": int(stage.get("calls") or 0),
        "cost_jpy": float(stage.get("cost_jpy") or 0.0),
        "duration_sec": float(stage.get("duration_sec") or 0.0),
    }


@router.get("/runs")
async def list_runs() -> dict[str, Any]:
    """承認に関わる実走の一覧（新しい順）。"""
    runs: list[dict] = []
    root = _runs_dir()
    if root.is_dir():
        for p in sorted(root.glob("*/run.json"), reverse=True):
            run = _read(p) or {}
            d = p.parent
            proposal = _read(d / PROPOSAL)
            runs.append({
                "run_id": d.name,
                "status": run.get("status"),
                "started_at": run.get("started_at"),
                "has_proposal": proposal is not None,
                "approved": (d / APPROVAL).is_file(),
                "exported": (d / EXPORT).is_file(),
                "quality": _quality(proposal),
            })
    return {"runs": runs, "runs_dir": str(root)}


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    """1本の実走: 提案・承認・書き出し・**工程ごとのモデルと理由**。"""
    d = _run_dir(run_id)
    run = _read(d / "run.json") or {}
    proposal = _read(d / PROPOSAL)
    approval = _read(d / APPROVAL)
    export = _read(d / EXPORT)
    ok, why = export_allowed(d) if proposal else (False, "提案がありません")
    preview = (proposal or {}).get("preview") or {}
    return {
        "run_id": run_id,
        "status": run.get("status"),
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
        "inputs": run.get("inputs") or {},
        "stages": [_stage_view(s) for s in (run.get("stages") or [])],
        "models_used": list((proposal or {}).get("models_used") or []),
        "proposal": ({
            "created_at": proposal.get("created_at"),
            "render_mode": proposal.get("render_mode"),
            "preview_available": bool(preview.get("path")) and Path(str(preview.get("path"))).is_file(),
            "skipped_features": list(proposal.get("skipped_features") or []),
            "degraded_stages": list(proposal.get("degraded_stages") or []),
            "ai_outputs": list(proposal.get("ai_outputs") or []),
        } if proposal else None),
        "quality": _quality(proposal),
        "approval": ({
            "approved_at": approval.get("approved_at"),
            "approved_by": approval.get("approved_by"),
            "note": approval.get("note") or "",
            "edits": list(approval.get("edits") or []),
            "ai_disclosure": approval.get("ai_disclosure") or {},
        } if approval else None),
        "export": ({
            "exported_at": export.get("exported_at"),
            "final_path": (export.get("final") or {}).get("path"),
            "render_mode": export.get("render_mode"),
            "metadata_sidecar": export.get("metadata_sidecar"),
        } if export else None),
        "export_allowed": bool(ok),
        "export_blocker": why or None,
    }


@router.get("/runs/{run_id}/preview")
async def get_preview(run_id: str):
    """承認の材料のプレビュー（提案が指す実物。**指紋が合うものだけ**）。"""
    d = _run_dir(run_id)
    proposal = _read(d / PROPOSAL)
    preview = (proposal or {}).get("preview") or {}
    path = Path(str(preview.get("path") or ""))
    if not preview.get("path") or not path.is_file():
        raise HTTPException(status_code=404, detail="プレビューがありません（見ていないものは承認できない）")
    return FileResponse(str(path), media_type="video/mp4", filename=path.name)


_PAGE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>承認画面 — R2</title>
<style>
 body{font-family:system-ui,sans-serif;margin:0;padding:16px;background:#fafafa;color:#222}
 h1{font-size:1.2rem;margin:0 0 12px}
 .row{display:flex;gap:16px;flex-wrap:wrap}
 .runs{min-width:260px;max-width:320px}
 .runs button{display:block;width:100%;text-align:left;padding:8px;margin:4px 0;border:1px solid #ccc;background:#fff;border-radius:6px;cursor:pointer}
 .runs button.sel{border-color:#333;background:#eef}
 .detail{flex:1;min-width:320px}
 table{border-collapse:collapse;width:100%;font-size:.9rem}
 th,td{border-bottom:1px solid #ddd;padding:6px 8px;text-align:left;vertical-align:top}
 .tag{display:inline-block;padding:2px 6px;border-radius:4px;font-size:.8rem}
 .declared{background:#e6f4ea}.fallback{background:#fdecea}.observed{background:#fff4e5}.unrecorded,.unverified{background:#eee}
 video{max-width:100%;background:#000;border-radius:6px}
 .muted{color:#777}
 .blocker{background:#fff4e5;padding:8px;border-radius:6px}
</style></head>
<body>
<h1>承認画面（R2-C5）</h1>
<p class="muted">提案ごとに、どのモデルで出たか・なぜそのモデルになったかを見る。承認と昇格はこの後の PR で足す。</p>
<div class="row">
 <div class="runs" id="runs"><p class="muted">実走を読み込み中…</p></div>
 <div class="detail" id="detail"><p class="muted">左の実走を選ぶ</p></div>
</div>
<script>
const REASON = {declared:"宣言どおり", fallback:"降格", observed:"宣言なし（実測だけ）", unverified:"未検証（一度も呼ばれていない）", unrecorded:"理由の記録なし"};
async function j(u){const r=await fetch(u);if(!r.ok)throw new Error(u+" "+r.status);return r.json();}
function esc(s){return String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}
async function loadRuns(){
  const d=await j("/api/r2/runs");const el=document.getElementById("runs");
  if(!d.runs.length){el.innerHTML='<p class="muted">実走がありません（'+esc(d.runs_dir)+'）</p>';return;}
  el.innerHTML=d.runs.map(r=>`<button data-id="${esc(r.run_id)}">${esc(r.run_id)}<br><small>${esc(r.status)}${r.approved?" ・承認済み":""}${r.exported?" ・書き出し済み":""}</small></button>`).join("");
  el.querySelectorAll("button").forEach(b=>b.onclick=()=>{el.querySelectorAll("button").forEach(x=>x.classList.remove("sel"));b.classList.add("sel");show(b.dataset.id);});
}
async function show(id){
  const d=await j("/api/r2/runs/"+encodeURIComponent(id));const q=d.quality;
  const stages=d.stages.filter(s=>s.model&&!String(s.model).startsWith("local:"));
  const rows=stages.map(s=>{
    const fb=(s.fallbacks||[]).map(f=>`${esc(f.from)} → ${esc(f.to)}（${esc(f.reason)}）`).join("<br>");
    return `<tr><td>${esc(s.name)}</td><td>${esc(s.model)}</td><td>${esc(s.tier||"")}</td><td><span class="tag ${esc(s.model_reason)}">${esc(REASON[s.model_reason]||s.model_reason)}</span>${fb?"<br>"+fb:""}</td><td>${s.calls}</td><td>${s.cost_jpy.toFixed(2)}</td></tr>`;
  }).join("");
  const el=document.getElementById("detail");
  el.innerHTML=`<h2>${esc(id)} <small class="muted">${esc(d.status)}</small></h2>
   ${d.proposal&&d.proposal.preview_available?`<video controls preload="metadata" src="/api/r2/runs/${encodeURIComponent(id)}/preview"></video>`:'<p class="muted">プレビューがありません</p>'}
   <p>品質: ${q.scored?esc(q.score)+" 点（"+(q.passed?"合格":"不合格")+"・"+esc(q.data_source)+"）":"採点されていません"} ／ 書き出しのモード: ${esc(d.proposal?d.proposal.render_mode:"-")}</p>
   <h3>工程ごとのモデル</h3>
   <table><thead><tr><th>工程</th><th>モデル</th><th>段</th><th>なぜこのモデルか</th><th>呼び出し</th><th>原価（円・上限見積もり）</th></tr></thead><tbody>${rows||'<tr><td colspan="6" class="muted">AI の工程がありません</td></tr>'}</tbody></table>
   <h3>承認</h3>
   ${d.approval?`<p>${esc(d.approval.approved_at)} に ${esc(d.approval.approved_by)} が承認${d.approval.note?"（"+esc(d.approval.note)+"）":""}</p>`:'<p class="muted">まだ承認されていません</p>'}
   ${d.export_allowed?'<p>書き出せます</p>':`<p class="blocker">書き出せません: ${esc(d.export_blocker)}</p>`}
   ${d.export?`<p>書き出し済み: ${esc(d.export.final_path)}（${esc(d.export.render_mode)}）</p>`:""}`;
}
loadRuns().catch(e=>{document.getElementById("runs").innerHTML='<p class="blocker">'+esc(e.message)+'</p>';});
</script>
</body></html>
"""


@page_router.get("/r2/approve", response_class=HTMLResponse, include_in_schema=False)
async def approve_page() -> HTMLResponse:
    """承認画面（1枚・依存なし）。"""
    return HTMLResponse(_PAGE)
