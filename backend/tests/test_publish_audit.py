"""R2-C1: **完成品の置き場の監査**（`approval_gate.publish_audit`・2026-09-25）。

## なぜ書き方ではなく置き場を見るか

3周の gate-verifier は、いずれも「承認を通さずに書ける場所」で C1 を崩した。
1周目・2周目は経路（`/api/shorts/render`・`/api/video/process/start`）、3周目は
走査ゲートの検出漏れ（`subprocess.run`・`open().write`・`os.replace` …）。
**書き方を列挙する限り、次の書き方が必ず出る。**

そこで結果を見る。正典の定義で「書き出し」は **`vault-outputs/final`・`vault-outputs/shorts`
への出力**。どんな書き方でも完成品はここに出るので、**ここにある mp4 が1本残らず承認に
辿れること**を確かめれば、書き方に依らず C1 を測れる。

2026-09-25 に置き場を実測したら、R2 以降の 29本のうち承認に辿れたのは4本だけだった
（残りは主に**テストが本番の置き場に書いた偽物**）。走査では一度も見えていなかった。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.revenue import approval_gate as ag


def _置き場(tmp_path) -> Path:
    vault = tmp_path / "vault"
    (vault / "final").mkdir(parents=True)
    (vault / "shorts").mkdir(parents=True)
    return vault


def _承認して書き出した(tmp_path, vault: Path, name="final_A.mp4", run_id="RID") -> Path:
    """提案 → 承認 → 書き出しを、置き場の中に完成品を置く形でファイルだけで作る。"""
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(json.dumps({"run_id": run_id, "status": "completed"}),
                                      encoding="utf-8")
    ctx = SimpleNamespace(video_path="in.mp4", session_id="s", metadata={}, preview_path=None,
                          quality_score=95, quality_scored=True, skipped_features=[], warnings=[])
    ag.write_proposal(run_dir, ctx, run_id=run_id, models_used=[])
    ag.approve(run_dir, synthetic=False, by="北原")
    final = vault / "final" / name
    final.write_bytes(b"approved-final-" + run_id.encode())
    ag.write_export(run_dir, final_path=str(final), metadata_sidecar=None,
                    quality_sidecar=None, render_mode="production")
    return final


def _開示つきで書き出した(tmp_path, vault: Path) -> Path:
    """**実走の門も緑になる**書き出し（手動投稿用サイドカーに開示の4項目がある）。"""
    final = _承認して書き出した(tmp_path, vault)
    run_dir = tmp_path / "runs" / "RID"
    sidecar = vault / "final" / "final_A.youtube.json"
    sidecar.write_text(json.dumps({"title": "題", "ai_disclosure": {
        "contains_synthetic_media": False, "decided_by": "北原",
        "decided_at": "2026-09-25T00:00:00+00:00", "ai_used_for": []}}, ensure_ascii=False),
        encoding="utf-8")
    ag.write_export(run_dir, final_path=str(final), metadata_sidecar=str(sidecar),
                    quality_sidecar=None, render_mode="production")
    return final


def test_承認に辿れる完成品だけなら問題なし(tmp_path):
    vault = _置き場(tmp_path)
    _承認して書き出した(tmp_path, vault)

    assert ag.publish_audit(tmp_path / "runs", vault, baseline={}) == []


def test_承認に辿れない完成品を見つける(tmp_path):
    """**これが本体。** どんな書き方でも、置き場に出たものは捕まる。"""
    vault = _置き場(tmp_path)
    _承認して書き出した(tmp_path, vault)
    (vault / "final" / "誰かが書いた.mp4").write_bytes(b"no-approval")

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={})

    assert len(problems) == 1, problems
    assert "誰かが書いた.mp4" in problems[0] and "承認に辿れない" in problems[0]


def test_shorts_の置き場も見る(tmp_path):
    """1周目の反例（承認ゼロの縦型 mp4）が出る置き場。"""
    vault = _置き場(tmp_path)
    (vault / "shorts" / "short_1.mp4").write_bytes(b"vertical")

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={})

    assert any("short_1.mp4" in p for p in problems), problems


def test_書き出した後に差し替えた完成品を見つける(tmp_path):
    """承認した動画と、いま置き場にある動画が同じものであること（指紋で見る）。"""
    vault = _置き場(tmp_path)
    final = _承認して書き出した(tmp_path, vault)
    final.write_bytes(b"swapped-after-export")

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={})

    assert any("差し替" in p for p in problems), problems


def test_門を通る前からあった動画は基準線で扱う(tmp_path):
    """承認の仕組みができる前の完成品は、**名前と指紋で**基準線に載せる。"""
    vault = _置き場(tmp_path)
    old = vault / "final" / "final_20260919_012200.mp4"
    old.write_bytes(b"legacy")
    baseline = {"final/final_20260919_012200.mp4": hashlib.sha256(b"legacy").hexdigest()}

    assert ag.publish_audit(tmp_path / "runs", vault, baseline=baseline) == []


def test_基準線の名前で別の動画を置いても通さない(tmp_path):
    """**基準線は名前だけでは通さない。** 同じ名前で中身を替えたら、それは新しい完成品。"""
    vault = _置き場(tmp_path)
    (vault / "final" / "final_20260919_012200.mp4").write_bytes(b"replaced")
    baseline = {"final/final_20260919_012200.mp4": hashlib.sha256(b"legacy").hexdigest()}

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline=baseline)

    assert len(problems) == 1, problems


def test_取り残された途中のファイルも完成品として数える(tmp_path):
    """`*.mp4.bgm.mp4` のような途中のファイルも、置き場にあれば人が投稿しうる。"""
    vault = _置き場(tmp_path)
    (vault / "final" / "final_X.mp4.bgm.mp4").write_bytes(b"temp")

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={})

    assert any("bgm" in p for p in problems), problems


def test_置き場の外は見ない(tmp_path):
    """プレビュー・中間物は正典の定義で対象外（承認の材料そのもの）。"""
    vault = _置き場(tmp_path)
    for sub in ("preview", "edited", "merged"):
        (vault / sub).mkdir()
        (vault / sub / "x.mp4").write_bytes(b"intermediate")

    assert ag.publish_audit(tmp_path / "runs", vault, baseline={}) == []


def test_gate_は置き場の監査も通す(tmp_path, capsys):
    """C1 の verify コマンド（`--gate`）そのものが置き場を見ること。"""
    vault = _置き場(tmp_path)
    _承認して書き出した(tmp_path, vault)
    (vault / "final" / "未承認.mp4").write_bytes(b"x")

    rc = ag.main(["--gate", "--runs-dir", str(tmp_path / "runs"), "--vault-dir", str(vault),
                  "--baseline", str(tmp_path / "無い.json")])
    out = capsys.readouterr().out

    assert rc == 1, out
    assert "未承認.mp4" in out


def test_承認が書き出しの後に差し替わった実走は辿れたと言わない(tmp_path):
    """書き出しの記録が指す承認と、いまの承認が違う = 承認したものを書き出した証拠が無い。"""
    vault = _置き場(tmp_path)
    _承認して書き出した(tmp_path, vault)
    approval = tmp_path / "runs" / "RID" / "approval.json"
    a = json.loads(approval.read_text(encoding="utf-8"))
    a["note"] = "書き出しの後に書き換えた"
    approval.write_text(json.dumps(a, ensure_ascii=False), encoding="utf-8")

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={})

    assert any("承認に辿れない" in p for p in problems), problems


def test_gate_は実走が緑でも置き場に未承認があれば落ちる(tmp_path, capsys):
    """**実走の門だけ緑でも C1 は満たさない。** 置き場に承認の無い完成品があれば exit 1。"""
    vault = _置き場(tmp_path)
    _開示つきで書き出した(tmp_path, vault)
    args = ["--gate", "--runs-dir", str(tmp_path / "runs"), "--vault-dir", str(vault),
            "--baseline", str(tmp_path / "無い.json")]

    # 陽性対照: 置き場がきれいなら緑
    assert ag.main(args) == 0, capsys.readouterr().out
    capsys.readouterr()

    (vault / "final" / "未承認.mp4").write_bytes(b"x")
    rc = ag.main(args)
    out = capsys.readouterr().out

    assert rc == 1, out
    assert "最新の実走は承認を通って書き出され" in out, "実走の門は緑のはず"
    assert "未承認.mp4" in out


def test_置き場の外でも投稿用サイドカーが付いた動画は完成品として見る(tmp_path):
    """正典の定義の後半 — **手動投稿用サイドカーを伴う出力**も書き出し。

    置き場（final / shorts）の外に書かれても、`*.youtube.json` が隣にあれば人はそのまま投稿できる。
    """
    vault = _置き場(tmp_path)
    (vault / "edited").mkdir()
    (vault / "edited" / "clip.mp4").write_bytes(b"x")
    (vault / "edited" / "clip.youtube.json").write_text("{}", encoding="utf-8")

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={})

    assert any("edited/clip.mp4" in p for p in problems), problems


def test_基準線には門ができる前の動画しか載っていない():
    """**基準線は抜け道にしてはいけない。** 門の後に承認なしで出た動画を足すと、監査が意味を失う。

    承認の流れで最初に書き出したのは 2026-09-24（実走 20260924T051318897986-0000）。
    それより後の時刻を持つ動画は基準線に載せない — 承認を通して書き出すこと。
    """
    base = json.loads(ag.PUBLISH_BASELINE.read_text(encoding="utf-8"))
    assert base["files"], "基準線が空（置き場の監査が本物の置き場で赤いはず）"
    門ができた = "2026-09-24T00:00:00"
    後 = [f for f in base["files"] if f["mtime"] >= 門ができた]
    assert not 後, f"門ができた後の動画が基準線に載っている: {[f['path'] for f in 後]}"
    for f in base["files"]:
        assert len(f["sha256"]) == 64 and f["path"].startswith(("final/", "shorts/")), f
