"""承認工程（R2）— 承認していない動画は書き出せない。

設計 `docs/specs/2026-09-19-r2-approval-design.md`。

本線（agents の coordinator）は書き出さずに**提案**を残し、`awaiting_approval` で止まる。
人がプレビューを見て承認し、承認があるときだけ書き出す。

    python -m backend.agents.pipeline_coordinator <素材>   # 提案で止まる
    （人がプレビューを見る。直すなら working/ の YouTube メタデータを直す）

置き場は実行記録と同じ `output/runs/<run_id>/`:

- `proposal.json` — 承認と書き出しに要るもの（プレビュー・品質・書き出しのモード・AI の出力・使ったモデル）
- `proposal/` — AI の出力の写し（**人が直す前の姿**）
- `working/` — 人が直す現物。承認のときに `proposal/` との差分を取る
"""
from __future__ import annotations

import difflib
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROPOSAL = "proposal.json"
APPROVAL = "approval.json"
APPROVAL_HISTORY = "approval_history"
EXPORT = "export.json"
PROPOSAL_DIR = "proposal"
WORKING_DIR = "working"
STATUS_AWAITING_APPROVAL = "awaiting_approval"

# 品質ゲートの合格線。書き出しのモードはこれで決まる（T-031 と同じ線）。
QUALITY_THRESHOLD = 90


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: str | Path | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")


def write_proposal(run_dir: str | Path, ctx: Any, *, run_id: str,
                   models_used: list[str],
                   degraded_stages: list[str] | None = None,
                   quality_detail: dict | None = None) -> dict:
    """提案を残す — **書き出しの前に、人が見て決めるための材料**。

    品質と書き出しのモードは、品質改善ループの**後**の値（D-41）。以前はループが
    書き出しの後に回っていて、ループで合格しても書き出しは safe のまま残っていた。

    `degraded_stages`（前半で落ちた工程）は、書き出した後の状態を決めるのに要る —
    前半で落ちた工程があれば、書き出しても完走（completed）とは呼ばない（R1.5-C1b）。
    `quality_detail`（講評など）は、書き出しの時点で品質のサイドカーを書くのに要る。
    """
    run_dir = Path(run_dir)
    ai_outputs = []
    metadata = getattr(ctx, "metadata", None) or {}
    if metadata:
        text = json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
        for sub in (PROPOSAL_DIR, WORKING_DIR):
            (run_dir / sub).mkdir(parents=True, exist_ok=True)
            (run_dir / sub / "youtube_metadata.json").write_text(
                text, encoding="utf-8", newline="\n")
        ai_outputs.append({
            "name": "youtube_metadata",
            "proposal": f"{PROPOSAL_DIR}/youtube_metadata.json",
            "working": f"{WORKING_DIR}/youtube_metadata.json",
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        })

    preview_path = getattr(ctx, "preview_path", None)
    preview_sha = _sha256_file(preview_path)
    score = getattr(ctx, "quality_score", 0)
    passed = score >= QUALITY_THRESHOLD
    proposal = {
        "run_id": run_id,
        "status": STATUS_AWAITING_APPROVAL,
        "created_at": _now(),
        "video_path": ctx.video_path,
        "session_id": getattr(ctx, "session_id", ""),
        "preview": ({"path": str(preview_path), "sha256": preview_sha}
                    if preview_sha else None),
        "quality": {"score": score,
                    "scored": bool(getattr(ctx, "quality_scored", False)),
                    "passed": passed},
        "render_mode": "production" if passed else "safe",
        "skipped_features": list(getattr(ctx, "skipped_features", None) or []),
        "degraded_stages": list(degraded_stages or []),
        "warnings": list(getattr(ctx, "warnings", None) or []),
        "quality_detail": dict(quality_detail or {}),
        "ai_outputs": ai_outputs,
        "models_used": list(models_used),
    }
    _write_json(run_dir / PROPOSAL, proposal)
    return proposal


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _ai_used_for(run_dir: Path) -> list[dict]:
    """**AI を使った工程**を実行記録から機械的に作る（開示の材料・R2-C3）。

    ローカルの道具（`local:*`）は AI 生成ではないので入れない。
    """
    path = run_dir / "run.json"
    if not path.is_file():
        return []
    seen: list[dict] = []
    for stage in _read_json(path).get("stages") or []:
        model = stage.get("model") or ""
        if not model or model.startswith("local:"):
            continue
        row = {"stage": stage.get("name"), "model": model}
        if row not in seen:
            seen.append(row)
    return seen


def approve(run_dir: str | Path, *, synthetic: bool | None, by: str,
            note: str = "") -> dict:
    """提案を承認する — **人が見て決めたこと**を残す（R2-C2・C3）。

    - 提案の指紋（`proposal.json` の sha256）。承認の後に提案が変わったら書き出さない
    - 人が手を入れた差分: AI の出力の写し（`proposal/`）と、人が直す現物（`working/`）の差。
      **差分が空でも「直さずに承認した」ことが残る**
    - 開示の判断: 合成メディアを含むか（**人が決める。省けない**）と、AI を使った工程

    **承認し直せるのは、前の承認が古くなったときだけ**（承認の後に提案・プレビュー・
    直す現物のどれかが変わった）。前の承認は `approval_history/` に移して残す —
    上書きで証跡を消さない。書き出した後は承認し直せない。
    """
    run_dir = Path(run_dir)
    proposal_path = run_dir / PROPOSAL
    if not proposal_path.is_file():
        raise FileNotFoundError(f"提案がありません: {proposal_path}")
    if synthetic is None:
        raise ValueError("合成メディアを含むかを人が決めてください（--synthetic yes|no）。"
                         "開示ラベルの要否はコンテンツによるので、機械は決めません")
    if not isinstance(synthetic, bool):
        raise TypeError(f"合成メディアの判断は真偽値で渡してください: {synthetic!r}")
    approval_path = run_dir / APPROVAL
    if approval_path.exists():
        if (run_dir / EXPORT).exists():
            raise ValueError(f"書き出し済みの実走は承認し直せません: {run_dir / EXPORT}")
        if export_allowed(run_dir)[0]:
            raise ValueError(f"すでに承認されています（まだ有効です）: {approval_path}")
        # 古くなった承認は履歴へ移す（消さない）
        history = run_dir / APPROVAL_HISTORY
        history.mkdir(exist_ok=True)
        stamp = str(_read_json(approval_path).get("approved_at") or _now())
        approval_path.replace(history / (stamp.replace(":", "-") + ".json"))

    proposal = _read_json(proposal_path)
    edits = []
    for out in proposal.get("ai_outputs") or []:
        before = (run_dir / out["proposal"]).read_text(encoding="utf-8")
        after_path = run_dir / out["working"]
        after = after_path.read_text(encoding="utf-8")
        diff = "".join(difflib.unified_diff(
            before.splitlines(keepends=True), after.splitlines(keepends=True),
            fromfile=out["proposal"], tofile=out["working"]))
        edits.append({"name": out["name"], "changed": before != after, "diff": diff,
                      "working_sha256": _sha256_file(after_path)})

    now = _now()
    approval = {
        "run_id": proposal.get("run_id"),
        "approved_at": now,
        "approved_by": by,
        "note": note,
        "proposal_sha256": _sha256_file(proposal_path),
        "edits": edits,
        "ai_disclosure": {
            "contains_synthetic_media": synthetic,
            "decided_by": by,
            "decided_at": now,
            "ai_used_for": _ai_used_for(run_dir),
        },
    }
    _write_json(run_dir / APPROVAL, approval)
    return approval


def export_allowed(run_dir: str | Path) -> tuple[bool, str]:
    """**書き出してよいか**（R2-C1 の門）。通さない理由を必ず言う。

    承認が無い・承認の後に提案やプレビューや直す現物が変わった・開示の判断が無い、
    のどれでも通さない。書き出しの工程の直前で呼ぶ（画面経由でも同じ門を通る）。
    """
    run_dir = Path(run_dir)
    proposal_path = run_dir / PROPOSAL
    if not proposal_path.is_file():
        return False, f"提案がありません: {proposal_path}"
    approval_path = run_dir / APPROVAL
    if not approval_path.is_file():
        return False, ("承認されていません。プレビューを見てから "
                       f"`python -m backend.revenue.approval_gate --approve {run_dir.name}` で承認してください")
    approval = _read_json(approval_path)
    if approval.get("proposal_sha256") != _sha256_file(proposal_path):
        return False, "提案が承認の後に変わっています。承認し直してください"
    proposal = _read_json(proposal_path)
    preview = proposal.get("preview") or {}
    if preview and _sha256_file(preview.get("path")) != preview.get("sha256"):
        return False, f"プレビューが承認の後に変わっています: {preview.get('path')}"
    working = {o["name"]: o["working"] for o in proposal.get("ai_outputs") or []}
    for edit in approval.get("edits") or []:
        path = run_dir / working.get(edit["name"], "")
        if _sha256_file(path) != edit.get("working_sha256"):
            return False, f"承認の後に直しています（{edit['name']}）。承認し直してください"
    disclosure = approval.get("ai_disclosure") or {}
    if not isinstance(disclosure.get("contains_synthetic_media"), bool):
        return False, "開示の判断がありません（合成メディアを含むかを承認のときに決めてください）"
    return True, ""


def write_export(run_dir: str | Path, *, final_path: str | None,
                 metadata_sidecar: str | None, quality_sidecar: str | None,
                 render_mode: str) -> dict:
    """書き出した記録を残す — **どの承認で、何を書き出したか**（R2-C2 の証跡の最後の段）。"""
    run_dir = Path(run_dir)
    data = {
        "run_id": run_dir.name,
        "exported_at": _now(),
        "final": ({"path": str(final_path), "sha256": _sha256_file(final_path)}
                  if final_path else None),
        "approval_sha256": _sha256_file(run_dir / APPROVAL),
        "metadata_sidecar": str(metadata_sidecar) if metadata_sidecar else None,
        "quality_sidecar": str(quality_sidecar) if quality_sidecar else None,
        "render_mode": render_mode,
    }
    _write_json(run_dir / EXPORT, data)
    return data


# --- 検査と証跡（R2-C1〜C3 の verify） -----------------------------------------

def gate(runs_dir: str | Path) -> tuple[bool, list[str]]:
    """**最新の実走が「承認して、承認したものを、開示つきで書き出した」か**（R2-C1・C3）。

    承認待ち・承認なしの書き出し・書き出した動画が記録と違う・開示が無い、のどれでも FAIL。
    判定は最新の1本で行う（成果物ゲートと同じ）。
    """
    runs = sorted(Path(runs_dir).glob("*/run.json"))
    if not runs:
        return False, [f"実行記録がありません: {runs_dir}"]
    run_dir = runs[-1].parent
    status = _read_json(runs[-1]).get("status")
    if status == STATUS_AWAITING_APPROVAL:
        return False, [(f"{run_dir.name}: 承認待ちです（書き出していません）。"
                        "プレビューを見て --approve、それから --export")]
    if status not in ("completed", "degraded"):
        return False, [f"{run_dir.name}: 状態が {status} です（書き出していません）"]
    export_path = run_dir / EXPORT
    if not export_path.is_file():
        return False, [(f"{run_dir.name}: 書き出しの記録（export.json）がありません — "
                        "承認の門を通らずに書き出しています")]
    export = _read_json(export_path)
    problems = []
    approval_path = run_dir / APPROVAL
    if not approval_path.is_file():
        problems.append("承認の記録（approval.json）が無いまま書き出しています")
    elif export.get("approval_sha256") != _sha256_file(approval_path):
        problems.append("書き出しの記録が指す承認と、いまの承認が食い違っています")
    final = export.get("final") or {}
    if not final or _sha256_file(final.get("path")) != final.get("sha256"):
        problems.append("書き出した動画が記録と違います（無いか、書き出しの後に変わった）: "
                        f"{final.get('path')}")
    sidecar = export.get("metadata_sidecar")
    disclosure = (_read_json(Path(sidecar)).get("ai_disclosure")
                  if sidecar and Path(sidecar).is_file() else None)
    if not isinstance((disclosure or {}).get("contains_synthetic_media"), bool):
        problems.append("手動投稿用のメタデータに AI 生成の開示（ai_disclosure）がありません")
    return (not problems), [f"{run_dir.name}: {p}" for p in problems]


def trace(run_dir: str | Path) -> tuple[bool, str]:
    """**承認の証跡**（R2-C2）— 提案 → 承認（いつ・誰が・人が直した差分・開示の判断）→ 書き出し。"""
    run_dir = Path(run_dir)
    proposal_path = run_dir / PROPOSAL
    if not proposal_path.is_file():
        return False, f"提案がありません: {proposal_path}"
    p = _read_json(proposal_path)
    q = p.get("quality") or {}
    合否 = "合格" if q.get("passed") else "不合格"
    lines = [f"承認の証跡: {run_dir.name}", "",
             "■ 提案",
             f"  作った時刻  : {p.get('created_at')}",
             f"  プレビュー  : {(p.get('preview') or {}).get('path')}",
             f"  品質        : {q.get('score')} 点（{合否}）→ 書き出しのモード {p.get('render_mode')}",
             f"  使ったモデル: {', '.join(p.get('models_used') or []) or '(記録なし)'}"]

    history_dir = run_dir / APPROVAL_HISTORY
    for h in sorted(history_dir.glob("*.json")) if history_dir.is_dir() else []:
        old = _read_json(h)
        lines.append(f"  （古くなった承認: {old.get('approved_at')} {old.get('approved_by')}）")

    approval_path = run_dir / APPROVAL
    lines += ["", "■ 承認"]
    if not approval_path.is_file():
        lines.append("  承認されていません")
        return False, "\n".join(lines)
    a = _read_json(approval_path)
    d = a.get("ai_disclosure") or {}
    lines += [f"  承認した時刻: {a.get('approved_at')}",
              f"  承認した人  : {a.get('approved_by')}"]
    if a.get("note"):
        lines.append(f"  メモ        : {a['note']}")
    for e in a.get("edits") or []:
        if e.get("changed"):
            lines.append(f"  人が直したもの: {e['name']}")
            lines += ["    " + ln for ln in e.get("diff", "").splitlines()]
        else:
            lines.append(f"  人が直したもの: {e['name']} — 直さずに承認")
    used = ", ".join(f"{u.get('stage')}（{u.get('model')}）" for u in d.get("ai_used_for") or [])
    合成 = "はい" if d.get("contains_synthetic_media") else "いいえ"
    lines += [f"  開示        : 合成メディアを含む = {合成}（{d.get('decided_by')} が決めた）",
              f"  AI を使った工程: {used or 'なし'}"]

    lines += ["", "■ 書き出し"]
    export_path = run_dir / EXPORT
    if export_path.is_file():
        ex = _read_json(export_path)
        lines += [f"  書き出した時刻: {ex.get('exported_at')}",
                  f"  動画          : {(ex.get('final') or {}).get('path')}",
                  f"  モード        : {ex.get('render_mode')}"]
    else:
        lines.append("  まだ書き出していません")
    return True, "\n".join(lines)


def _default_approver() -> str:
    """承認した人の既定値: git の user.name（無ければ OS のユーザー名）。"""
    import getpass
    import subprocess
    try:
        name = subprocess.run(["git", "config", "user.name"], capture_output=True,
                              text=True, timeout=10, check=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        name = ""
    return name or getpass.getuser()


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os

    from backend.revenue.run_record import RUNS_DIR

    parser = argparse.ArgumentParser(
        description="承認工程（R2）— 承認していない動画は書き出せない")
    what = parser.add_mutually_exclusive_group(required=True)
    what.add_argument("--approve", metavar="RUN_ID", help="提案を承認する")
    what.add_argument("--export", metavar="RUN_ID",
                      help="承認した提案を書き出す（**課金経路**: 書き出しの後の学習が API を呼ぶことがある）")
    what.add_argument("--gate", action="store_true",
                      help="最新の実走が承認して開示つきで書き出したか（R2-C1・C3）")
    what.add_argument("--trace", metavar="RUN_ID", help="承認の証跡を出す（R2-C2）")
    parser.add_argument("--synthetic", choices=("yes", "no"),
                        help="合成メディアを含むか（--approve で必須。人が決める）")
    parser.add_argument("--by", default=None, help="承認した人（既定は git の user.name）")
    parser.add_argument("--note", default="", help="承認のメモ")
    parser.add_argument("--runs-dir", default=None, help="実行記録の置き場（既定 output/runs）")
    parser.add_argument("--no-ledger", action="store_true",
                        help="--export で台帳に1本ぶんの要約を書かない（試し撃ち用）")
    args = parser.parse_args(argv)
    runs_dir = Path(args.runs_dir or os.getenv("AVS_RUNS_DIR") or RUNS_DIR)

    if args.gate:
        ok, problems = gate(runs_dir)
        print("承認工程の門（R2）— 承認して、承認したものを、開示つきで書き出したか")
        print()
        if ok:
            print("  ✅ 最新の実走は承認を通って書き出され、開示があります")
            return 0
        for p in problems:
            print(f"  🚫 {p}")
        return 1

    if args.trace:
        ok, text = trace(runs_dir / args.trace)
        print(text)
        return 0 if ok else 1

    if args.approve:
        if args.synthetic is None:
            print("🚫 合成メディアを含むかを決めてください（--synthetic yes|no）。"
                  "開示ラベルの要否はコンテンツによるので、機械は決めません")
            return 1
        try:
            a = approve(runs_dir / args.approve, synthetic=(args.synthetic == "yes"),
                        by=args.by or _default_approver(), note=args.note)
        except (FileNotFoundError, ValueError) as e:
            print(f"🚫 {e}")
            return 1
        直した = [e["name"] for e in a["edits"] if e["changed"]]
        合成 = "はい" if args.synthetic == "yes" else "いいえ"
        print(f"✅ 承認しました: {args.approve}（{a['approved_by']}）")
        print(f"   人が直したもの: {', '.join(直した) or 'なし（直さずに承認）'}")
        print(f"   開示: 合成メディアを含む = {合成}")
        print(f"   書き出す: python -m backend.revenue.approval_gate --export {args.approve}")
        return 0

    # --export: 本線の coordinator は backend/ を import の起点にしている
    import asyncio
    import sys
    backend_dir = str(Path(__file__).resolve().parent.parent)
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    from backend import cost_guard
    cost_guard.load_env()
    from agents.pipeline_coordinator import PipelineCoordinator

    coordinator = PipelineCoordinator()
    coordinator.runs_dir = runs_dir
    if not args.no_ledger:
        coordinator.ledger_path = Path(cost_guard.LEDGER_PATH)
    result = asyncio.run(coordinator.export(args.export))
    print(f"  状態  : {result['status']}")
    print(f"  成果物: {result.get('final_path') or '(無し)'}")
    if result.get("error"):
        print(f"  🚫 {result['error']}")
    return 0 if result["status"] in ("completed", "degraded") else 1


if __name__ == "__main__":
    raise SystemExit(main())
