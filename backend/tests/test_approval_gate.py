"""R2-C1〜C3: 承認の記録と書き出しの門（`backend.revenue.approval_gate`・2026-09-19）。

設計 docs/specs/2026-09-19-r2-approval-design.md。

- 承認（`approve`）は、提案の指紋・人が手を入れた差分（R2-C2）・開示の判断（R2-C3。人が決める）を残す
- 書き出しの門（`export_allowed`）は、承認が無い・承認の後に提案やプレビューや直す現物が変わった・
  開示の判断が無い、のどれでも通さない（R2-C1）
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.revenue import approval_gate as ag

METADATA = {"title": "AI が付けた題", "description": "AI が書いた説明", "tags": ["a", "b"]}


def _提案のある実走(tmp_path, run_id="RID"):
    """提案で止まった実走を1本作る（coordinator の代わりに write_proposal を直接呼ぶ）。"""
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    preview = tmp_path / "preview.mp4"
    preview.write_bytes(b"preview-bytes")
    (run_dir / "run.json").write_text(json.dumps({
        "run_id": run_id, "status": "awaiting_approval",
        "stages": [{"name": "transcribe", "model": "local:whisper", "status": "success"},
                   {"name": "proofread", "model": "gemini-3.6-flash", "status": "success"},
                   {"name": "youtube_opt", "model": "gemini-3.6-flash", "status": "success"}],
    }, ensure_ascii=False), encoding="utf-8")
    ctx = SimpleNamespace(video_path=str(tmp_path / "入力.mp4"), session_id="s",
                          preview_path=str(preview), metadata=dict(METADATA),
                          quality_score=92, quality_scored=True, skipped_features=[])
    ag.write_proposal(run_dir, ctx, run_id=run_id, models_used=["gemini-3.6-flash", "local:whisper"])
    return run_dir


def _承認(run_dir, **kw):
    kw.setdefault("synthetic", False)
    kw.setdefault("by", "北原")
    return ag.approve(run_dir, **kw)


# --- 承認（R2-C2・C3） -------------------------------------------------------

def test_承認は提案の指紋と人の差分と開示の判断を残す(tmp_path):
    run_dir = _提案のある実走(tmp_path)
    _承認(run_dir)
    a = json.loads((run_dir / "approval.json").read_text(encoding="utf-8"))

    assert a["run_id"] == "RID"
    assert a["approved_by"] == "北原" and a["approved_at"]
    assert a["proposal_sha256"] == hashlib.sha256((run_dir / "proposal.json").read_bytes()).hexdigest()
    assert a["edits"] == [{
        "name": "youtube_metadata", "changed": False, "diff": "",
        "working_sha256": hashlib.sha256((run_dir / "working" / "youtube_metadata.json").read_bytes()).hexdigest(),
    }], "直さずに承認したことが記録されていません"
    d = a["ai_disclosure"]
    assert d["contains_synthetic_media"] is False
    assert d["decided_by"] == "北原" and d["decided_at"]
    assert d["ai_used_for"] == [{"stage": "proofread", "model": "gemini-3.6-flash"},
                                {"stage": "youtube_opt", "model": "gemini-3.6-flash"}]


def test_人が直したらその差分が残る(tmp_path):
    run_dir = _提案のある実走(tmp_path)
    現物 = run_dir / "working" / "youtube_metadata.json"
    直した = dict(METADATA, title="人が直した題")
    現物.write_text(json.dumps(直した, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _承認(run_dir)
    edit = json.loads((run_dir / "approval.json").read_text(encoding="utf-8"))["edits"][0]

    assert edit["changed"] is True
    assert '-  "title": "AI が付けた題",' in edit["diff"]
    assert '+  "title": "人が直した題",' in edit["diff"]


def test_開示の判断は省けない(tmp_path):
    run_dir = _提案のある実走(tmp_path)
    with pytest.raises(ValueError, match="合成メディア"):
        _承認(run_dir, synthetic=None)
    assert not (run_dir / "approval.json").exists()


def test_提案が無ければ承認できない(tmp_path):
    with pytest.raises(FileNotFoundError):
        _承認(tmp_path / "runs" / "無い")


def test_有効な承認があれば二度は承認しない(tmp_path):
    """上書きで証跡を消さない。承認がまだ有効なら、承認し直す理由が無い。"""
    run_dir = _提案のある実走(tmp_path)
    _承認(run_dir)
    with pytest.raises(ValueError, match="すでに承認"):
        _承認(run_dir, by="別の人")
    assert json.loads((run_dir / "approval.json").read_text(encoding="utf-8"))["approved_by"] == "北原"


def test_承認の後に直したら承認し直せて前の承認は履歴に残る(tmp_path):
    """承認の後にタイトルを直しただけで、提案から作り直させない。**前の承認は消さない。**"""
    run_dir = _提案のある実走(tmp_path)
    _承認(run_dir)
    前 = (run_dir / "approval.json").read_bytes()
    (run_dir / "working" / "youtube_metadata.json").write_text(
        json.dumps(dict(METADATA, title="承認の後に直した題"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    assert ag.export_allowed(run_dir)[0] is False

    _承認(run_dir, by="別の人")
    assert ag.export_allowed(run_dir) == (True, "")
    履歴 = sorted((run_dir / "approval_history").glob("*.json"))
    assert [p.read_bytes() for p in 履歴] == [前], "前の承認が履歴に残っていません"


def test_書き出した後は承認し直せない(tmp_path):
    run_dir = _提案のある実走(tmp_path)
    _承認(run_dir)
    (run_dir / "export.json").write_text("{}", encoding="utf-8")
    (run_dir / "working" / "youtube_metadata.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="書き出し済み"):
        _承認(run_dir, by="別の人")


# --- 書き出しの門（R2-C1） ---------------------------------------------------

def test_承認が無ければ書き出せない(tmp_path):
    ok, why = ag.export_allowed(_提案のある実走(tmp_path))
    assert ok is False and "承認されていません" in why


def test_提案が無ければ書き出せない(tmp_path):
    ok, why = ag.export_allowed(tmp_path / "runs" / "無い")
    assert ok is False and "提案がありません" in why


def test_承認の後に提案が変わったら書き出せない(tmp_path):
    run_dir = _提案のある実走(tmp_path)
    _承認(run_dir)
    p = json.loads((run_dir / "proposal.json").read_text(encoding="utf-8"))
    p["render_mode"] = "production" if p["render_mode"] == "safe" else "safe"
    (run_dir / "proposal.json").write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    ok, why = ag.export_allowed(run_dir)
    assert ok is False and "提案が承認の後に変わっています" in why


def test_承認の後にプレビューが変わったら書き出せない(tmp_path):
    run_dir = _提案のある実走(tmp_path)
    _承認(run_dir)
    (tmp_path / "preview.mp4").write_bytes(b"swapped")
    ok, why = ag.export_allowed(run_dir)
    assert ok is False and "プレビューが承認の後に変わっています" in why


def test_承認の後に直したら書き出せない(tmp_path):
    run_dir = _提案のある実走(tmp_path)
    _承認(run_dir)
    (run_dir / "working" / "youtube_metadata.json").write_text("{}\n", encoding="utf-8")
    ok, why = ag.export_allowed(run_dir)
    assert ok is False and "承認の後に直しています" in why


def test_開示の判断が無ければ書き出せない(tmp_path):
    run_dir = _提案のある実走(tmp_path)
    _承認(run_dir)
    a = json.loads((run_dir / "approval.json").read_text(encoding="utf-8"))
    del a["ai_disclosure"]
    (run_dir / "approval.json").write_text(json.dumps(a, ensure_ascii=False), encoding="utf-8")
    ok, why = ag.export_allowed(run_dir)
    assert ok is False and "開示の判断がありません" in why


def test_そろっていれば書き出せる(tmp_path):
    run_dir = _提案のある実走(tmp_path)
    _承認(run_dir)
    assert ag.export_allowed(run_dir) == (True, "")


# --- CLI（R2-C1〜C3 の verify） ------------------------------------------------

def _書き出した実走(tmp_path, *, 開示=True, 承認=True):
    """承認して書き出した実走を、ファイルだけで作る（coordinator の書き出しの代わり）。"""
    run_dir = _提案のある実走(tmp_path)
    if 承認:
        _承認(run_dir)
    final = tmp_path / "final.mp4"
    final.write_bytes(b"final-bytes")
    sidecar = tmp_path / "final.youtube.json"
    meta = dict(METADATA)
    if 開示:
        meta["ai_disclosure"] = {"contains_synthetic_media": False, "decided_by": "北原",
                                 "decided_at": "t", "ai_used_for": []}
    sidecar.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    ag.write_export(run_dir, final_path=str(final), metadata_sidecar=str(sidecar),
                    quality_sidecar=None, render_mode="production")
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    run["status"] = "completed"
    (run_dir / "run.json").write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    return run_dir


def _gate(tmp_path, capsys):
    rc = ag.main(["--gate", "--runs-dir", str(tmp_path / "runs")])
    return rc, capsys.readouterr().out


def test_gate_承認待ちはFAIL(tmp_path, capsys):
    _提案のある実走(tmp_path)
    rc, out = _gate(tmp_path, capsys)
    assert rc == 1 and "承認待ち" in out


def test_gate_承認なしで書き出していたらFAIL(tmp_path, capsys):
    _書き出した実走(tmp_path, 承認=False)
    rc, out = _gate(tmp_path, capsys)
    assert rc == 1 and "承認" in out


def test_開示は中身が欠けても書き出せない(tmp_path):
    """**bool 1個だけでは開示ではない**（2026-09-24 の gate-verifier の指摘）。

    設計（docs/specs/2026-09-19-r2-approval-design.md §5）は開示の中身として
    「合成メディアを含むか・誰が決めたか・いつ決めたか・AI をどの工程に使ったか」を
    宣言している。機械が bool だけを見ていると、残り3つを削っても書き出せてしまう。
    """
    for 欠け in ("decided_by", "decided_at", "ai_used_for"):
        run_dir = _提案のある実走(tmp_path / 欠け)
        _承認(run_dir)
        path = run_dir / "approval.json"
        a = json.loads(path.read_text(encoding="utf-8"))
        del a["ai_disclosure"][欠け]
        path.write_text(json.dumps(a, ensure_ascii=False), encoding="utf-8")

        ok, why = ag.export_allowed(run_dir)

        assert ok is False, f"{欠け} が無くても書き出せます"
        assert 欠け in why or "開示" in why


def test_gate_出力の開示は中身が欠けていたらFAIL(tmp_path, capsys):
    """成果物側（サイドカー）も同じ。**bool だけ残して中身を削った開示は開示ではない。**"""
    run_dir = _書き出した実走(tmp_path)
    e = json.loads((run_dir / "export.json").read_text(encoding="utf-8"))
    sidecar = Path(e["metadata_sidecar"])
    m = json.loads(sidecar.read_text(encoding="utf-8"))
    m["ai_disclosure"] = {"contains_synthetic_media": False}
    sidecar.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")

    rc, out = _gate(tmp_path, capsys)

    assert rc == 1, out
    assert "開示" in out


def test_gate_書き出しの記録が無ければFAIL(tmp_path, capsys):
    """**完走を名乗っているのに書き出しの記録が無い** = 門を通らずに書き出している。

    承認の門は `write_export` を通ったときだけ記録を残す。記録が無いまま completed に
    なっている実走は、古い経路（force-render や自前のレンダリング）で出したということ。
    """
    run_dir = _書き出した実走(tmp_path)
    (run_dir / "export.json").unlink()
    rc, out = _gate(tmp_path, capsys)
    assert rc == 1
    assert "書き出しの記録" in out and "承認の門" in out


def test_gate_書き出したものが承認のときと違えばFAIL(tmp_path, capsys):
    _書き出した実走(tmp_path)
    (tmp_path / "final.mp4").write_bytes(b"swapped")
    rc, out = _gate(tmp_path, capsys)
    assert rc == 1 and "書き出した動画" in out


def test_gate_開示が無ければFAIL(tmp_path, capsys):
    _書き出した実走(tmp_path, 開示=False)
    rc, out = _gate(tmp_path, capsys)
    assert rc == 1 and "開示" in out


def test_gate_そろっていればPASS(tmp_path, capsys):
    _書き出した実走(tmp_path)
    rc, out = _gate(tmp_path, capsys)
    assert rc == 0, out
    assert "✅" in out


def test_gate_実走が無ければFAIL(tmp_path, capsys):
    rc, out = _gate(tmp_path, capsys)
    assert rc == 1 and "実行記録がありません" in out


def test_trace_提案と承認と差分と開示と書き出しが出る(tmp_path, capsys):
    run_dir = _提案のある実走(tmp_path)
    (run_dir / "working" / "youtube_metadata.json").write_text(
        json.dumps(dict(METADATA, title="人が直した題"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    _承認(run_dir)
    rc = ag.main(["--trace", "RID", "--runs-dir", str(tmp_path / "runs")])
    out = capsys.readouterr().out
    assert rc == 0
    for 語 in ("提案", "承認", "北原", '+  "title": "人が直した題",', "合成メディア", "いいえ",
               "書き出し"):
        assert 語 in out, f"{語!r} が出ていません"


def test_trace_承認が無ければexit1(tmp_path, capsys):
    _提案のある実走(tmp_path)
    rc = ag.main(["--trace", "RID", "--runs-dir", str(tmp_path / "runs")])
    assert rc == 1 and "承認されていません" in capsys.readouterr().out


def test_approve_CLIは開示の判断を省けない(tmp_path, capsys):
    run_dir = _提案のある実走(tmp_path)
    rc = ag.main(["--approve", "RID", "--runs-dir", str(tmp_path / "runs"), "--by", "北原"])
    assert rc == 1 and "合成メディア" in capsys.readouterr().out
    assert not (run_dir / "approval.json").exists()


def test_approve_CLIで承認できる(tmp_path, capsys):
    run_dir = _提案のある実走(tmp_path)
    rc = ag.main(["--approve", "RID", "--runs-dir", str(tmp_path / "runs"),
                  "--synthetic", "no", "--by", "北原"])
    assert rc == 0, capsys.readouterr().out
    assert json.loads((run_dir / "approval.json").read_text(encoding="utf-8"))[
        "ai_disclosure"]["contains_synthetic_media"] is False
