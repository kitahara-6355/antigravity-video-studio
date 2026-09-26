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
    # **見ていないものは承認できない**ので、プレビューを持たせる（4周目の反例B）
    preview = tmp_path / f"preview_{run_id}.mp4"
    preview.write_bytes(b"preview-" + run_id.encode())
    ctx = SimpleNamespace(video_path="in.mp4", session_id="s", metadata={}, preview_path=str(preview),
                          quality_score=95, quality_scored=True, skipped_features=[], warnings=[])
    ag.write_proposal(run_dir, ctx, run_id=run_id, models_used=[])
    ag.approve(run_dir, synthetic=False, by="北原")
    final = vault / "final" / name
    final.write_bytes(b"approved-final-" + run_id.encode())
    # **開示の出力が欠けた完成品は承認に辿れない**（2026-09-26・9周目の C3-1）ので、付属物も置く
    sidecar = final.with_suffix(".youtube.json")
    sidecar.write_text(json.dumps({"title": "題", "ai_disclosure": {
        "contains_synthetic_media": False, "decided_by": "北原",
        "decided_at": "2026-09-25T00:00:00+00:00", "ai_used_for": []}}, ensure_ascii=False),
        encoding="utf-8")
    ag.write_export(run_dir, final_path=str(final), metadata_sidecar=str(sidecar),
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

    assert ag.publish_audit(tmp_path / "runs", vault, baseline={}, output_root=tmp_path / 'output') == []


def test_承認に辿れない完成品を見つける(tmp_path):
    """**これが本体。** どんな書き方でも、置き場に出たものは捕まる。"""
    vault = _置き場(tmp_path)
    _承認して書き出した(tmp_path, vault)
    (vault / "final" / "誰かが書いた.mp4").write_bytes(b"no-approval")

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={}, output_root=tmp_path / 'output')

    assert len(problems) == 1, problems
    assert "誰かが書いた.mp4" in problems[0] and "承認に辿れない" in problems[0]


def test_shorts_の置き場も見る(tmp_path):
    """1周目の反例（承認ゼロの縦型 mp4）が出る置き場。"""
    vault = _置き場(tmp_path)
    (vault / "shorts" / "short_1.mp4").write_bytes(b"vertical")

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={}, output_root=tmp_path / 'output')

    assert any("short_1.mp4" in p for p in problems), problems


def test_書き出した後に差し替えた完成品を見つける(tmp_path):
    """承認した動画と、いま置き場にある動画が同じものであること（指紋で見る）。"""
    vault = _置き場(tmp_path)
    final = _承認して書き出した(tmp_path, vault)
    final.write_bytes(b"swapped-after-export")

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={}, output_root=tmp_path / 'output')

    assert any("差し替" in p for p in problems), problems


def test_門を通る前からあった動画は基準線で扱う(tmp_path):
    """承認の仕組みができる前の完成品は、**名前と指紋で**基準線に載せる。"""
    vault = _置き場(tmp_path)
    old = vault / "final" / "final_20260919_012200.mp4"
    old.write_bytes(b"legacy")
    baseline = {"final/final_20260919_012200.mp4": hashlib.sha256(b"legacy").hexdigest()}

    assert ag.publish_audit(tmp_path / "runs", vault, baseline=baseline, output_root=tmp_path / 'output') == []


def test_基準線の名前で別の動画を置いても通さない(tmp_path):
    """**基準線は名前だけでは通さない。** 同じ名前で中身を替えたら、それは新しい完成品。"""
    vault = _置き場(tmp_path)
    (vault / "final" / "final_20260919_012200.mp4").write_bytes(b"replaced")
    baseline = {"final/final_20260919_012200.mp4": hashlib.sha256(b"legacy").hexdigest()}

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline=baseline, output_root=tmp_path / 'output')

    assert len(problems) == 1, problems


def test_取り残された途中のファイルも完成品として数える(tmp_path):
    """`*.mp4.bgm.mp4` のような途中のファイルも、置き場にあれば人が投稿しうる。"""
    vault = _置き場(tmp_path)
    (vault / "final" / "final_X.mp4.bgm.mp4").write_bytes(b"temp")

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={}, output_root=tmp_path / 'output')

    assert any("bgm" in p for p in problems), problems


def test_置き場の外は見ない(tmp_path):
    """プレビュー・中間物は正典の定義で対象外（承認の材料そのもの）。"""
    vault = _置き場(tmp_path)
    for sub in ("preview", "edited", "merged"):
        (vault / sub).mkdir()
        (vault / sub / "x.mp4").write_bytes(b"intermediate")

    assert ag.publish_audit(tmp_path / "runs", vault, baseline={}, output_root=tmp_path / 'output') == []


def test_gate_は置き場の監査も通す(tmp_path, capsys):
    """C1 の verify コマンド（`--gate`）そのものが置き場を見ること。"""
    vault = _置き場(tmp_path)
    _承認して書き出した(tmp_path, vault)
    (vault / "final" / "未承認.mp4").write_bytes(b"x")

    rc = ag.main(["--gate", "--runs-dir", str(tmp_path / "runs"), "--vault-dir", str(vault),
                  "--baseline", str(tmp_path / "無い.json"), "--output-dir", str(tmp_path / "output")])
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

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={}, output_root=tmp_path / 'output')

    assert any("承認に辿れない" in p for p in problems), problems


def test_gate_は実走が緑でも置き場に未承認があれば落ちる(tmp_path, capsys):
    """**実走の門だけ緑でも C1 は満たさない。** 置き場に承認の無い完成品があれば exit 1。"""
    vault = _置き場(tmp_path)
    _開示つきで書き出した(tmp_path, vault)
    args = ["--gate", "--runs-dir", str(tmp_path / "runs"), "--vault-dir", str(vault),
            "--baseline", str(tmp_path / "無い.json"), "--output-dir", str(tmp_path / "output")]

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

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={}, output_root=tmp_path / 'output')

    assert any("edited/clip.mp4" in p for p in problems), problems


def test_基準線には門ができる前の動画しか載っていない():
    """**基準線は抜け道にしてはいけない。** 門の後に承認なしで出た動画を足すと、監査が意味を失う。

    境界は**門の最初のコミット**（88603e3・2026-09-19 12:10:29 +0900）。それより後の時刻を
    持つ動画は基準線に載せない — 承認を通して書き出すこと（以前の境界は最初の書き出しの
    2026-09-24 で、09-19 12:10〜09-23 の動画を弾けなかった。4周目の gate-verifier の付記）。
    """
    base = json.loads(ag.PUBLISH_BASELINE.read_text(encoding="utf-8"))
    assert base["files"], "基準線が空（置き場の監査が本物の置き場で赤いはず）"
    門ができた = "2026-09-19T12:10:29"
    後 = [f for f in base["files"] if f["mtime"] >= 門ができた]
    assert not 後, f"門ができた後の動画が基準線に載っている: {[f['path'] for f in 後]}"
    for f in base["files"]:
        assert len(f["sha256"]) == 64 and f["path"].startswith(("final/", "shorts/")), f


# --- 4周目の反証（2026-09-25）への手当て -------------------------------------

import pytest


@pytest.mark.parametrize("置き方", [
    "shorts/probe.webm",            # VP9 の縦型（Shorts の書き手は format: mp4 | webm を受ける）
    "final/sub/final_probe.mp4",    # 置き場のサブディレクトリ
    "final/probe.mov",
    "final/probe.MKV",              # 大文字の拡張子
    "shorts/run/clip_01.m4v",
])
def test_置き場の中なら入れ物や深さに依らず見る(tmp_path, 置き方):
    """**置き場の定義はディレクトリ単位で、拡張子も深さも限定していない**（4周目の反例A）。"""
    vault = _置き場(tmp_path)
    f = vault / 置き方
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"unapproved")

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={}, output_root=tmp_path / "output")

    assert any(置き方 in p for p in problems), problems


def test_サイドカーの組は動画の入れ物に依らない(tmp_path):
    """`x.mov` と `x.youtube.json` の組も手動投稿用の完成品（定義の後半）。"""
    vault = _置き場(tmp_path)
    (vault / "edited").mkdir()
    (vault / "edited" / "x.mov").write_bytes(b"x")
    (vault / "edited" / "x.youtube.json").write_text("{}", encoding="utf-8")

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={}, output_root=tmp_path / "output")

    assert any("edited/x.mov" in p for p in problems), problems


def test_退避先の置き場も見る(tmp_path):
    """safe_io を読めないときの書き手の退避先（`output/final`・`output/shorts`）も置き場。"""
    vault = _置き場(tmp_path)
    out = tmp_path / "output"
    (out / "shorts").mkdir(parents=True)
    (out / "shorts" / "short_x.mp4").write_bytes(b"x")
    (out / "clips").mkdir()
    (out / "clips" / "y.webm").write_bytes(b"y")
    (out / "clips" / "y.youtube.json").write_text("{}", encoding="utf-8")

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={}, output_root=out)

    assert any("output/shorts/short_x.mp4" in p for p in problems), problems
    assert any("output/clips/y.webm" in p for p in problems), problems


def test_中身の無い承認では辿れたと言わない(tmp_path):
    """**承認は、その提案の承認として成り立っていること**（4周目の反例C）。

    中身が `{}` の承認と、それを指す書き出しの記録を手で置いても、承認に辿れたとは言わない。
    docstring は「承認がいまも有効」と書いていたのに確かめていなかった（私の誤り）。
    """
    vault = _置き場(tmp_path)
    run_dir = tmp_path / "runs" / "FORGED"
    run_dir.mkdir(parents=True)
    video = vault / "final" / "forged.mp4"
    video.write_bytes(b"forged")
    (run_dir / "approval.json").write_text("{}", encoding="utf-8")
    ag.write_export(run_dir, final_path=str(video), metadata_sidecar=None,
                    quality_sidecar=None, render_mode="production")

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={}, output_root=tmp_path / "output")

    assert any("forged.mp4" in p for p in problems), problems


def test_別の提案の承認では辿れたと言わない(tmp_path):
    """承認が指す提案と、いまの提案が違えば、承認したものを書き出した証拠にならない。"""
    vault = _置き場(tmp_path)
    _承認して書き出した(tmp_path, vault)
    proposal = tmp_path / "runs" / "RID" / "proposal.json"
    d = json.loads(proposal.read_text(encoding="utf-8"))
    d["render_mode"] = "safe"
    proposal.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={}, output_root=tmp_path / "output")

    assert any("final_A.mp4" in p for p in problems), problems


def test_開示の欠けた承認では辿れたと言わない(tmp_path):
    """承認に開示の判断が無い = C3 の門を通っていない。そのまま書き出した記録は辿れたと言わない。"""
    vault = _置き場(tmp_path)
    run_dir = tmp_path / "runs" / "RID"
    run_dir.mkdir(parents=True)
    preview = tmp_path / "preview.mp4"
    preview.write_bytes(b"preview")
    ctx = SimpleNamespace(video_path="in.mp4", session_id="s", metadata={}, preview_path=str(preview),
                          quality_score=95, quality_scored=True, skipped_features=[], warnings=[])
    ag.write_proposal(run_dir, ctx, run_id="RID", models_used=[])
    ag.approve(run_dir, synthetic=False, by="北原")
    a = json.loads((run_dir / "approval.json").read_text(encoding="utf-8"))
    del a["ai_disclosure"]
    (run_dir / "approval.json").write_text(json.dumps(a, ensure_ascii=False), encoding="utf-8")
    video = vault / "final" / "no_disclosure.mp4"
    video.write_bytes(b"x")
    # 開示の欠けた承認を指す書き出しの記録（承認の指紋は一致させる）
    ag.write_export(run_dir, final_path=str(video), metadata_sidecar=None,
                    quality_sidecar=None, render_mode="production")

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={}, output_root=tmp_path / "output")

    assert any("no_disclosure.mp4" in p for p in problems), problems


# --- 5周目の反証（2026-09-25）への手当て: 置き場の監査を裏返す -------------------

@pytest.mark.parametrize("名前", [
    "final/zz.wmv", "final/zz.mpg", "final/zz.mpeg", "final/zz.flv", "final/zz.3gp",
    "shorts/zz.ts", "final/zz.bin", "final/notes.txt",
])
def test_置き場には承認済みの完成品と付属物しか置けない(tmp_path, 名前):
    """**入れ物を列挙しない。** 5周目の反例: 許可リスト（mp4/mov/…）に無い `.wmv` などの
    未承認動画が置き場にあっても `--gate` が緑だった。列挙する限り次の入れ物が出るので、
    **置き場に置けるのは「承認済みの完成品」と「その付属物」だけ**、それ以外は全部赤にする。
    """
    vault = _置き場(tmp_path)
    f = vault / 名前
    f.write_bytes(b"unknown")

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={}, output_root=tmp_path / "output")

    assert any(名前 in p for p in problems), problems


def test_承認済みの完成品の付属物は通す(tmp_path):
    vault = _置き場(tmp_path)
    _承認して書き出した(tmp_path, vault)   # final_A.youtube.json（開示つき）も置く
    (vault / "final" / "final_A.quality.json").write_text("{}", encoding="utf-8")

    assert ag.publish_audit(tmp_path / "runs", vault, baseline={},
                            output_root=tmp_path / "output") == []


def test_動画の無い付属物を見つける(tmp_path):
    """付属物だけが残っている = 何かが消えたか、承認の無い何かの残骸。黙って通さない。"""
    vault = _置き場(tmp_path)
    (vault / "final" / "消えた.youtube.json").write_text("{}", encoding="utf-8")

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={}, output_root=tmp_path / "output")

    assert any("消えた.youtube.json" in p for p in problems), problems


def test_角括弧の名前でもサイドカーの組を見つける(tmp_path):
    """glob の特殊文字（`[` `]`）で組を見失わない（5周目の所見）。"""
    vault = _置き場(tmp_path)
    (vault / "edited").mkdir()
    (vault / "edited" / "clip[1].mp4").write_bytes(b"x")
    (vault / "edited" / "clip[1].youtube.json").write_text("{}", encoding="utf-8")

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={}, output_root=tmp_path / "output")

    assert any("edited/clip[1].mp4" in p for p in problems), problems


def test_置き場の外のサイドカーの組も入れ物を問わない(tmp_path):
    vault = _置き場(tmp_path)
    (vault / "edited").mkdir()
    (vault / "edited" / "y.wmv").write_bytes(b"x")
    (vault / "edited" / "y.youtube.json").write_text("{}", encoding="utf-8")

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={}, output_root=tmp_path / "output")

    assert any("edited/y.wmv" in p for p in problems), problems


# --- 6周目の反証（2026-09-26）への手当て -------------------------------------

def test_書き出した場所を監査していなければ赤(tmp_path):
    """**置き場の取り違えで緑に倒れない**（6周目の U1）。

    `ANTIGRAVITY_VAULT_OUTPUTS` が空・存在しない場所を指したまま `--gate` を回すと、監査する場所を
    取り違えたまま緑だった。書き出しの記録が指す完成品が、監査した場所の外にあれば赤にする。
    """
    vault = _置き場(tmp_path)
    別の置き場 = tmp_path / "別の置き場"
    (別の置き場 / "final").mkdir(parents=True)
    _承認して書き出した(tmp_path, 別の置き場)

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={}, output_root=tmp_path / "output")

    assert any("監査していません" in p for p in problems), problems


def test_gate_は監査した場所を名乗る(tmp_path, capsys):
    vault = _置き場(tmp_path)
    ag.main(["--gate", "--runs-dir", str(tmp_path / "runs"), "--vault-dir", str(vault),
             "--baseline", str(tmp_path / "無い.json"), "--output-dir", str(tmp_path / "output")])
    out = capsys.readouterr().out

    assert str(vault / "final") in out, "どこを監査したのか出ていない"


@pytest.mark.parametrize("動画, サイドカー", [
    ("clip.mp4", "clip.mp4.youtube.json"),     # 動画の名前をそのままサイドカーの名前にする形
    ("clip3.mp4", "Clip3.youtube.json"),        # 大文字小文字だけ違う
])
def test_サイドカーの組は名前の付け方に依らない(tmp_path, 動画, サイドカー):
    """置き場の外のサイドカーの組（6周目の U2）。アップローダの案内も `<動画名>.youtube.json`。"""
    vault = _置き場(tmp_path)
    (vault / "edited").mkdir()
    (vault / "edited" / 動画).write_bytes(b"x")
    (vault / "edited" / サイドカー).write_text("{}", encoding="utf-8")

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={}, output_root=tmp_path / "output")

    assert any(f"edited/{動画}" in p for p in problems), problems


def test_承認済みの完成品の付属物は名前の付け方に依らず通す(tmp_path):
    vault = _置き場(tmp_path)
    _承認して書き出した(tmp_path, vault)
    (vault / "final" / "final_A.mp4.youtube.json").write_text("{}", encoding="utf-8")
    (vault / "final" / "FINAL_A.quality.json").write_text("{}", encoding="utf-8")

    assert ag.publish_audit(tmp_path / "runs", vault, baseline={},
                            output_root=tmp_path / "output") == []


def test_付属物の名前をかぶせた動画を見つける(tmp_path):
    """付属物は名前だけで見ない — **中身が JSON であること**（6周目の I1）。"""
    vault = _置き場(tmp_path)
    _承認して書き出した(tmp_path, vault)
    (vault / "final" / "final_A.quality.json").write_bytes(b"\x00\x00\x00 ftypisom")

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={}, output_root=tmp_path / "output")

    assert any("final_A.quality.json" in p for p in problems), problems


def test_置き場のリンクは赤(tmp_path):
    """リンクの先は辿らないので、**リンクそのものを置かせない**（6周目の I2）。"""
    vault = _置き場(tmp_path)
    先 = tmp_path / "どこか"
    先.mkdir()
    (先 / "x.mp4").write_bytes(b"x")
    try:
        (vault / "final" / "link").symlink_to(先, target_is_directory=True)
    except OSError:
        pytest.skip("この環境ではシンボリックリンクを作れない")

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={}, output_root=tmp_path / "output")

    assert any("final/link" in p for p in problems), problems


def test_末尾がドットや空白の名前は赤(tmp_path):
    """Windows が名前を正規化するので、承認済みの本体と取り違える（6周目の I4）。"""
    import os
    vault = _置き場(tmp_path)
    名前 = vault / "final" / "final_A.mp4."
    try:
        # Windows では `\\?\` を付けないと末尾のドットが落とされる
        target = ("\\\\?\\" + str(名前)) if os.name == "nt" else str(名前)
        with open(target, "wb") as fh:
            fh.write(b"x")
    except OSError:
        pytest.skip("この環境では末尾がドットの名前を作れない")

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={}, output_root=tmp_path / "output")

    assert any("末尾" in p for p in problems), problems


# --- 7周目の反証（2026-09-26）への手当て -------------------------------------

@pytest.mark.parametrize("動画, サイドカー", [
    ("edit_20260926.mp4", "upload.youtube.json"),   # 名前がまったく違う
    ("clip.final.mp4", "clip.youtube.json"),         # 拡張子の前に別の点がある
])
def test_サイドカーのあるフォルダは置き場として扱う(tmp_path, 動画, サイドカー):
    """**名前で結ばない**（7周目の F1・U2 の塞ぎ残し）。

    手動投稿用サイドカーがあるフォルダは、そこから投稿される。サイドカーの名前と動画の名前が
    違っても「伴う出力」なので、フォルダの中身を置き場と同じ規則で全部問う。
    """
    vault = _置き場(tmp_path)
    (vault / "edited").mkdir()
    (vault / "edited" / 動画).write_bytes(b"x")
    (vault / "edited" / サイドカー).write_text("{}", encoding="utf-8")

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={}, output_root=tmp_path / "output")

    assert any(f"edited/{動画}" in p for p in problems), problems


def test_サイドカーのあるフォルダでも承認済みなら通す(tmp_path):
    """置き場の外に書き出した承認済みの完成品と、その付属物は通す（取り違えの赤にもしない）。"""
    vault = _置き場(tmp_path)
    (vault / "edited").mkdir()
    final = _承認して書き出した(tmp_path, vault, name="../edited/clip.mp4")
    assert (final.parent / "clip.youtube.json").is_file()   # 開示つきの付属物は書き出しが置く

    assert ag.publish_audit(tmp_path / "runs", vault, baseline={},
                            output_root=tmp_path / "output") == []


# --- 9周目の C3-1: 開示の出力が欠けた完成品 ------------------------------------------

def test_開示のサイドカーが無い完成品は承認に辿れない(tmp_path):
    """**開示が欠けたら書き出しは止まる**（R2-C3）を結果の側でも見る（9周目の C3-1）。

    書き手がサイドカーを書けずに完成品だけ置き場に残すと、次の実走を1本書き出した時点で
    `--gate`（最新の1本だけを見る）は緑に戻っていた。置き場の監査は全部を見るので、ここで捕まえる。
    """
    vault = _置き場(tmp_path)
    final = _承認して書き出した(tmp_path, vault)
    run_dir = tmp_path / "runs" / "RID"
    final.with_suffix(".youtube.json").unlink()
    ag.write_export(run_dir, final_path=str(final), metadata_sidecar=None,
                    quality_sidecar=None, render_mode="production")

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={}, output_root=tmp_path / "output")

    assert len(problems) == 1, problems
    assert "final_A.mp4" in problems[0] and "開示" in problems[0]


def test_開示のサイドカーが消えた完成品は承認に辿れない(tmp_path):
    """記録はサイドカーを指しているが、実物が無い（書き出しの後に消えた）。"""
    vault = _置き場(tmp_path)
    final = _承認して書き出した(tmp_path, vault)
    final.with_suffix(".youtube.json").unlink()

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={}, output_root=tmp_path / "output")

    assert len(problems) == 1, problems
    assert "開示" in problems[0]


def test_開示の中身が欠けたサイドカーの完成品は承認に辿れない(tmp_path):
    vault = _置き場(tmp_path)
    final = _承認して書き出した(tmp_path, vault)
    final.with_suffix(".youtube.json").write_text(json.dumps({"title": "題"}), encoding="utf-8")

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={}, output_root=tmp_path / "output")

    assert any("final_A.mp4" in p and "開示" in p for p in problems), problems


def test_別のフォルダのサイドカーを指す完成品は承認に辿れない(tmp_path):
    """開示は**投稿する動画の隣**に無ければ手動投稿で使われない。"""
    vault = _置き場(tmp_path)
    final = _承認して書き出した(tmp_path, vault)
    sc = final.with_suffix(".youtube.json")
    よそ = tmp_path / "elsewhere"
    よそ.mkdir()
    移した = よそ / sc.name
    sc.rename(移した)
    ag.write_export(tmp_path / "runs" / "RID", final_path=str(final), metadata_sidecar=str(移した),
                    quality_sidecar=None, render_mode="production")

    problems = ag.publish_audit(tmp_path / "runs", vault, baseline={}, output_root=tmp_path / "output")

    assert any("開示" in p and "final_A.mp4" in p for p in problems), problems
