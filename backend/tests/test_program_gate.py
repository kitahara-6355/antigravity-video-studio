"""backend/revenue/program_gate.py・program_quality.py — 番組化の承認の門と実測の品質ゲート（V2）。

守りたい性質:

1. 承認していない仕上げ版・Shorts・サムネは、置き場（40_完成 の投稿する棚）へ送れない。
   1つでも未承認があれば何も送らない
2. 見てもらう物（確認用・候補・見本）と文章の付属物は、承認の前でも送れる
3. AI の名前では承認できない。開示の判断と、どこで承認されたか（根拠）が無い承認は控えない
4. 承認は中身に結びつく。中身を変えて出し直すと承認は外れ、前の承認は履歴に残る
5. 品質ゲートは実測で合否を出す。測れない物・線を外れた物は提案にならない
6. 置き場の点検は、動画と画像が1つ残らず承認か基準線に辿れるかを見る。見られなければ緑にしない

Google には接続しない。動画は ffmpeg でその場で作る。
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from backend import drive_layout as dl
from backend.drive_layout import Node
from backend.revenue import program_gate as pg
from backend.revenue import program_quality as pq

REC = "20250922_久木田ヒロノブ"
LAYOUT = dl.load_layout()
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg が無い")

TODAY = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat()   # 日本の今日


def make_video(path: Path, size: str = "1080x1920", seconds: float = 2.0, *, audio: bool = True,
               pix_fmt: str = "yuv420p", color: str | None = None, volume: str = "2.0", seed: int = 0) -> Path:
    src = f"color=c={color}:s={size}:d={seconds}:r=10" if color else f"testsrc2=s={size}:d={seconds}:r=10"
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=f={440 + seed}:d={seconds}", "-af", f"volume={volume}", "-c:a", "aac"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", pix_fmt, "-shortest", str(path)]
    subprocess.run(cmd, check=True)
    return path


@pytest.fixture(scope="module")
def clips(tmp_path_factory):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg が無い")
    d = tmp_path_factory.mktemp("clips")
    return {"s1": make_video(d / f"{REC}_S1.mp4", seed=1),
            "s2": make_video(d / f"{REC}_S2.mp4", seed=2),
            "s1b": make_video(d / "S1_直した版.mp4", seed=3)}


@pytest.fixture
def ledger():
    return {"approvers": ["北原", "北原克洋"], "review_marks": ["確認用", "候補", "見本"],
            "baseline": [], "items": []}


def approve(ledger, key="S1", **kw):
    args = dict(recording=REC, key=key, by="北原", synthetic=False, evidence="チャット 2026-11-12「S1 を出す」")
    return pg.approve(ledger, **{**args, **kw})


# --- 1・2: 置き場へ送るとき ---------------------------------------------------


def test_unapproved_short_cannot_be_put(ledger, clips, tmp_path):
    shutil.copy(clips["s1"], tmp_path / "01_S1_鬼滅の刃.mp4")
    problems = pg.put_problems(tmp_path, f"{REC}/Shorts_投稿用", ledger)
    assert len(problems) == 1 and "承認していない物は置き場に出せません" in problems[0]


def test_waiting_item_is_named_in_the_refusal(ledger, clips, tmp_path):
    pg.propose(ledger, recording=REC, kind="short", key="S1", publish=clips["s1"])
    shutil.copy(clips["s1"], tmp_path / clips["s1"].name)
    assert "S1 は承認待ち" in pg.put_problems(tmp_path, f"{REC}/Shorts_投稿用", ledger)[0]


def test_approved_short_can_be_put_under_any_name(ledger, clips, tmp_path):
    pg.propose(ledger, recording=REC, kind="short", key="S1", publish=clips["s1"])
    approve(ledger)
    shutil.copy(clips["s1"], tmp_path / "01_S1_鬼滅の刃.mp4")   # 投稿の順番の番号を付けた写し
    assert pg.put_problems(tmp_path, f"{REC}/Shorts_投稿用", ledger) == []


def test_one_unapproved_file_blocks_the_whole_put(ledger, clips, tmp_path, monkeypatch):
    pg.propose(ledger, recording=REC, kind="short", key="S1", publish=clips["s1"])
    approve(ledger)
    shutil.copy(clips["s1"], tmp_path / "01_S1.mp4")
    shutil.copy(clips["s2"], tmp_path / "02_S2.mp4")
    monkeypatch.setattr(pg, "load", lambda path=None: ledger)
    sent = []
    monkeypatch.setattr("backend.asset_store.put_tree", lambda *a, **k: sent.append(a) or [])
    monkeypatch.setattr("backend.asset_store.ensure_root", lambda service: "root")
    monkeypatch.setattr(dl, "ensure_marked_folder", lambda *a, **k: ("fid", "40_完成"))
    with pytest.raises(ValueError, match="何も送っていません"):
        dl.put_to(object(), LAYOUT, "finished", tmp_path, f"{REC}/Shorts_投稿用")
    assert sent == []
    (tmp_path / "02_S2.mp4").unlink()
    dl.put_to(object(), LAYOUT, "finished", tmp_path, f"{REC}/Shorts_投稿用")
    assert len(sent) == 1


def test_review_material_and_companions_pass_without_approval(ledger, clips, tmp_path):
    shutil.copy(clips["s1"], tmp_path / "Shorts_I_S1.mp4")
    (tmp_path / "投稿文.txt").write_text("x", encoding="utf-8")
    assert pg.put_problems(tmp_path, f"{REC}/Shorts候補_I_額縁", ledger) == []      # 行き先が候補
    named = tmp_path / "sub"
    named.mkdir()
    shutil.copy(clips["s1"], named / "_v67_番組仕上げ_確認用.mp4")
    assert pg.put_problems(named, REC, ledger) == []                              # 名前が確認用


def test_approval_of_another_recording_does_not_count(ledger, clips, tmp_path):
    pg.propose(ledger, recording=REC, kind="short", key="S1", publish=clips["s1"])
    approve(ledger)
    shutil.copy(clips["s1"], tmp_path / "S1.mp4")
    assert pg.put_problems(tmp_path, "20251201_別の人/Shorts_投稿用", ledger)
    assert "収録ID がありません" in pg.put_problems(tmp_path, "", ledger)[0]


def test_review_copy_is_not_a_publishable(ledger, clips, tmp_path):
    """確認用として承認の材料にした縮小版を、投稿する棚に置くことはできない。"""
    pg.propose(ledger, recording=REC, kind="short", key="S1", publish=clips["s1"], review=clips["s2"])
    approve(ledger)
    shutil.copy(clips["s2"], tmp_path / "S1.mp4")
    assert pg.put_problems(tmp_path, f"{REC}/Shorts_投稿用", ledger)


# --- 3: 承認 ------------------------------------------------------------------


def test_ai_cannot_approve(ledger, clips):
    pg.propose(ledger, recording=REC, kind="short", key="S1", publish=clips["s1"])
    for by in ("claude-code", "", "Claude"):
        with pytest.raises(ValueError, match="AI は承認しない"):
            approve(ledger, by=by)
    assert pg.find(ledger, REC, "S1")["state"] == pg.WAITING


def test_approval_needs_disclosure_and_evidence(ledger, clips):
    pg.propose(ledger, recording=REC, kind="short", key="S1", publish=clips["s1"])
    with pytest.raises(ValueError, match="合成メディア"):
        approve(ledger, synthetic=None)
    with pytest.raises(ValueError, match="evidence"):
        approve(ledger, evidence="  ")
    item = approve(ledger)
    d = item["approval"]["ai_disclosure"]
    assert d["contains_synthetic_media"] is False and d["decided_by"] == "北原" and d["ai_used_for"] == []
    with pytest.raises(ValueError, match="すでに承認"):
        approve(ledger)


def test_approval_without_proposal_is_refused(ledger):
    with pytest.raises(LookupError, match="提案がありません"):
        approve(ledger)


def test_qc_label_counts_as_approval_only_for_the_same_bytes(ledger, clips):
    item = pg.propose(ledger, recording=REC, kind="short", key="S1", publish=clips["s1"], review=clips["s2"])
    review_md5 = next(f["md5"] for f in item["files"] if f["role"] == "review")
    qc = {"checked": [{"id": "x1", "name": "確認用.mp4", "md5": "0" * 32, "state": "目視OK",
                       "checked_by": "北原克洋", "checked_on": TODAY},
                      {"id": "x2", "name": "確認用.mp4", "md5": review_md5, "state": "要直し",
                       "checked_by": "北原克洋", "checked_on": TODAY}]}
    with pytest.raises(LookupError, match="同じ動画がありません"):
        pg.approve_from_qc(ledger, qc, recording=REC, key="S1", synthetic=False)
    qc["checked"][1]["state"] = "目視OK"
    item = pg.approve_from_qc(ledger, qc, recording=REC, key="S1", synthetic=False)
    assert item["approval"]["by"] == "北原克洋" and "品質確認" in item["approval"]["evidence"]


# --- 4: 中身に結びつく ---------------------------------------------------------


def test_reproposing_changed_bytes_drops_the_approval_and_keeps_history(ledger, clips, tmp_path):
    pg.propose(ledger, recording=REC, kind="short", key="S1", publish=clips["s1"])
    approve(ledger)
    assert pg.propose(ledger, recording=REC, kind="short", key="S1", publish=clips["s1"])["state"] == pg.APPROVED
    item = pg.propose(ledger, recording=REC, kind="short", key="S1", publish=clips["s1b"])
    assert item["state"] == pg.WAITING and item["approval"] is None
    assert item["history"][0]["approval"]["by"] == "北原"
    assert len(ledger["items"]) == 1
    shutil.copy(clips["s1"], tmp_path / "S1.mp4")       # 前の版はもう承認済みではない
    assert pg.put_problems(tmp_path, f"{REC}/Shorts_投稿用", ledger)


def test_hand_edited_item_loses_its_approval(ledger, clips, tmp_path):
    pg.propose(ledger, recording=REC, kind="short", key="S1", publish=clips["s1"])
    approve(ledger)
    edited = copy.deepcopy(ledger)
    edited["items"][0]["files"][0].update(pg.fingerprint(clips["s2"]))   # 承認の後に中身だけ差し替える
    shutil.copy(clips["s2"], tmp_path / "S1.mp4")
    assert pg.put_problems(tmp_path, f"{REC}/Shorts_投稿用", edited)


# --- 5: 実測の品質ゲート -------------------------------------------------------


@needs_ffmpeg
def test_quality_measures_and_passes_a_good_short(clips):
    r = pq.measure("short", clips["s1"])
    assert r["passed"], r["failed"]
    by = {c["id"]: c for c in r["checks"]}
    assert by["size"]["value"] == "1080x1920" and by["duration"]["value"] <= 60
    assert by["loudness"]["measured"] and by["black"]["value"] == "なし"


@needs_ffmpeg
@pytest.mark.parametrize("kw, failed", [
    (dict(size="1920x1080"), "size"),
    (dict(pix_fmt="yuv444p"), "pix_fmt"),
    (dict(audio=False), "audio"),
    (dict(color="black", seconds=4), "black"),
    (dict(volume="0.0001", seconds=3), "loudness"),
])
def test_quality_fails_on_measured_defects(tmp_path, kw, failed):
    r = pq.measure("short", make_video(tmp_path / "x.mp4", **kw))
    assert not r["passed"] and failed in r["failed"]


@needs_ffmpeg
def test_too_long_short_fails(tmp_path, clips):
    cfg = pq.load_config()
    cfg["kinds"]["short"]["max_seconds"] = 1
    r = pq.measure("short", clips["s1"], cfg=cfg)
    assert r["failed"] == ["duration"]


def test_unreadable_file_is_not_passed(tmp_path):
    bad = tmp_path / "壊れ.mp4"
    bad.write_bytes(b"not a video")
    r = pq.measure("short", bad)
    assert not r["passed"] and r["checks"][0]["measured"] is False
    assert not pq.measure("short", tmp_path / "無い.mp4")["passed"]


def test_review_copy_is_not_asked_its_size(clips, tmp_path):
    small = make_video(tmp_path / "確認用360p.mp4", size="640x360")
    assert pq.measure("episode", small, review=True, cfg=_short_episode())["passed"]
    assert "size" in pq.measure("episode", small, cfg=_short_episode())["failed"]


def _short_episode():
    cfg = pq.load_config()
    cfg["kinds"]["episode"]["min_seconds"] = 1
    return cfg


def test_thumbnail_is_measured(tmp_path):
    from PIL import Image

    good, small = tmp_path / "サムネ.png", tmp_path / "小さい.png"
    Image.new("RGB", (1280, 720), (200, 180, 220)).save(good)
    Image.new("RGB", (640, 360)).save(small)
    assert pq.measure("thumbnail", good)["passed"]
    assert pq.measure("thumbnail", small)["failed"] == ["size"]
    (tmp_path / "壊れ.png").write_bytes(b"x")
    assert not pq.measure("thumbnail", tmp_path / "壊れ.png")["passed"]


@needs_ffmpeg
def test_failing_quality_never_becomes_a_proposal(ledger, tmp_path):
    wide = make_video(tmp_path / "横.mp4", size="1920x1080")
    with pytest.raises(pg.QualityError, match="品質ゲートが不合格"):
        pg.propose(ledger, recording=REC, kind="short", key="S9", publish=wide)
    assert ledger["items"] == []


def test_proposal_records_measured_values(ledger, clips):
    item = pg.propose(ledger, recording=REC, kind="short", key="S1", publish=clips["s1"])
    q = item["quality"][0]
    assert q["passed"] and {c["id"] for c in q["checks"]} >= {"codec", "pix_fmt", "size", "duration", "loudness"}
    assert "実測" in "\n".join(pg.trace(item))


# --- 6: 置き場の点検 -----------------------------------------------------------


def tree(*children):
    def fix(node, path):
        node.path = f"{path}/{node.name}"
        for c in node.children:
            fix(c, node.path)
    rec = Node("d1", REC, True, "", children=list(children))
    root = Node("d0", "動画制作", True, "動画制作", children=[Node("d2", "40_完成", True, "", children=[rec])])
    for c in root.children:
        fix(c, root.path)
    return root


def vid(name, md5, id_=None, size=10):
    return Node(id_ or "f" + md5, name, False, "", md5=md5, size=size, video=True)


def img(name, md5, id_=None, size=10):
    return Node(id_ or "f" + md5, name, False, "", md5=md5, size=size, image=True)


def box(name, *children):
    return Node("d" + name, name, True, "", children=list(children))


def test_shelf_audit_finds_only_untraceable_publishables(ledger, clips):
    pg.propose(ledger, recording=REC, kind="short", key="S1", publish=clips["s1"])
    approve(ledger)
    md5 = pg.fingerprint(clips["s1"])["md5"]
    ledger["baseline"] = [{"id": "old1", "name": "v62.mp4", "size": 10}]
    root = tree(vid("_v67_確認用.mp4", "a1"), vid(f"{REC}_v62.mp4", "a2", id_="old1"),
                vid(f"{REC}_v67.mp4", "a3"), img("サムネ_P1.png", "a4"),
                Node("t1", "チャプター.txt", False, "", md5="a5"),
                box("Shorts候補_I", vid("S9.mp4", "a6")),
                box("Shorts_投稿用", vid("01_S1.mp4", md5), vid("02_S2.mp4", "a7")))
    found = {f["path"].rsplit("/", 1)[-1]: f["code"] for f in pg.drive_findings(root, LAYOUT, ledger)}
    assert found == {f"{REC}_v67.mp4": "unapproved", "サムネ_P1.png": "unapproved", "02_S2.mp4": "unapproved"}


def test_baseline_holds_only_while_unchanged(ledger):
    ledger["baseline"] = [{"id": "old1", "name": "v62.mp4", "size": 10, "md5": "m1"}]
    assert pg.drive_findings(tree(vid("v62.mp4", "m1", id_="old1")), LAYOUT, ledger) == []
    assert pg.drive_findings(tree(vid("v62.mp4", None, id_="old1")), LAYOUT, ledger) == []   # md5 が読めない控え
    for changed in (vid("v62.mp4", "m2", id_="old1"), vid("v62.mp4", "m1", id_="old1", size=11)):
        assert pg.drive_findings(tree(changed), LAYOUT, ledger)[0]["code"] == "baseline_changed"
    # 同じ中身でも別のファイル（id が違う）は基準線ではない
    assert pg.drive_findings(tree(vid("v62.mp4", "m1", id_="new")), LAYOUT, ledger)[0]["code"] == "unapproved"


def test_shelf_audit_never_passes_what_it_cannot_read(ledger):
    assert pg.drive_findings(tree(vid("v67.mp4", None, id_="n1")), LAYOUT, ledger)[0]["code"] == "unreadable"
    empty = Node("d0", "動画制作", True, "動画制作")
    assert pg.drive_findings(empty, LAYOUT, ledger)[0]["code"] == "no_shelf"


def test_gate_cli_is_red_without_drive_and_green_on_the_recorded_shelf(monkeypatch, capsys):
    monkeypatch.delenv("AVS_RAW_DRIVE_FOLDER_ID", raising=False)
    assert pg.main(["gate"]) == 1
    assert "見ていないので合否は出しません" in capsys.readouterr().out
    snap = Path(__file__).resolve().parents[2] / "docs" / "evidence" / "v2_drive_40_完成_久木田回_20261110.json"
    assert pg.main(["gate", "--tree", str(snap)]) == 0


def test_snapshot_round_trips(ledger):
    root = tree(vid("a.mp4", "m1"), box("Shorts_投稿用", img("b.png", "m2")))
    again = pg.tree_from_json(json.loads(json.dumps(pg.tree_to_json(root))))
    assert [(n.path, n.md5, n.video, n.image) for n in again.walk()] == \
           [(n.path, n.md5, n.video, n.image) for n in root.walk()]


def test_cli_flow_propose_approve_trace(clips, tmp_path, capsys):
    led = tmp_path / "ledger.json"
    led.write_text(json.dumps({"approvers": ["北原"], "review_marks": ["確認用", "候補"], "baseline": [],
                               "items": []}, ensure_ascii=False), encoding="utf-8")
    base = ["--ledger", str(led)]
    assert pg.main([*base, "propose", "--recording", REC, "--kind", "short", "--key", "S1",
                    "--publish", str(clips["s1"])]) == 0
    assert pg.main([*base, "trace", "--recording", REC, "--key", "S1"]) == 1          # まだ承認待ち
    assert pg.main([*base, "approve", "--recording", REC, "--key", "S1", "--synthetic", "no",
                    "--evidence", "チャット"]) == 1                                    # --by を既定値で埋めない
    assert pg.main([*base, "approve", "--recording", REC, "--key", "S1", "--by", "北原", "--synthetic", "no",
                    "--evidence", "チャット 2026-11-12"]) == 0
    assert pg.main([*base, "trace", "--recording", REC, "--key", "S1"]) == 0
    out = capsys.readouterr().out
    assert "承認した人: 北原" in out and "合成メディアを含む = いいえ" in out
    put = tmp_path / "put"
    put.mkdir()
    shutil.copy(clips["s1"], put / "01_S1.mp4")
    assert pg.main([*base, "check-put", str(put), "--to", f"{REC}/Shorts_投稿用"]) == 0
    shutil.copy(clips["s2"], put / "02_S2.mp4")
    assert pg.main([*base, "check-put", str(put), "--to", f"{REC}/Shorts_投稿用"]) == 1


# --- 移す・名前を変える（drive_organize）でも、未承認の物は投稿する棚に出ない -----------


def organize_tree(*finished):
    from backend import drive_organize as org

    root = tree(*finished)
    root.children += [Node("d9", "90_保管", True, "動画制作/90_保管")]
    return org.Tree(root, LAYOUT)


def test_moving_or_renaming_onto_the_publish_shelf_needs_approval(ledger, clips, monkeypatch):
    from backend import drive_organize as org

    monkeypatch.setattr(pg, "load", lambda path=None: ledger)
    md5 = pg.fingerprint(clips["s1"])["md5"]
    t = organize_tree(box("Shorts候補_I", vid("S1.mp4", md5), vid("S2.mp4", "zz")), box("Shorts_投稿用"),
                      vid("_v67_確認用.mp4", "yy"))
    base = f"40_完成/{REC}"
    s1, s2 = t.get(f"{base}/Shorts候補_I/S1.mp4"), t.get(f"{base}/Shorts候補_I/S2.mp4")
    shelf = t.get(f"{base}/Shorts_投稿用")
    with pytest.raises(org.GuardError, match="承認の門が断りました"):
        t.check_move(s1, shelf, "01_S1.mp4")                       # まだ承認していない
    with pytest.raises(org.GuardError, match="承認の門が断りました"):
        org.rename(None, t, t.get(f"{base}/_v67_確認用.mp4"), f"{REC}_v67.mp4")     # 「確認用」を外す
    with pytest.raises(org.GuardError, match="承認の門が断りました"):
        org.rename(None, t, t.get(f"{base}/Shorts候補_I"), "Shorts_まとめ")          # フォルダごと棚を替える

    pg.propose(ledger, recording=REC, kind="short", key="S1", publish=clips["s1"])
    approve(ledger)
    t.check_move(s1, shelf, "01_S1.mp4")                           # 承認済みは通る
    with pytest.raises(org.GuardError):
        t.check_move(s2, shelf, None)
    # 見てもらう棚の中・40_完成 の外（90_保管）へは、承認が無くても動かせる
    org.rename(None, t, s2, "S2_直し.mp4")
    t.check_move(s2, t.get("90_保管"), None)


# --- gate-verifier 1 周目の反例（うっかり型）-------------------------------------

@pytest.mark.parametrize("name", ["S11_選挙の候補者.mp4", "S12_見本市の話.mp4", "S13_確認用紙の書き方.mp4",
                                  "S14_候補.backup.mp4"])
def test_a_topic_that_happens_to_contain_a_mark_is_not_review_material(ledger, clips, tmp_path, name):
    """話題から付けた名前に印の字が入っても、投稿する棚では承認が要る（部分一致にしない）。"""
    shutil.copy(clips["s1"], tmp_path / name)
    assert pg.put_problems(tmp_path, f"{REC}/Shorts_投稿用", ledger)


@pytest.mark.parametrize("parts", [["_v66_番組仕上げ_仮曲入り_確認用.mp4"], [f"{REC}_v62_ロゴなし_確認用360p.mp4"],
                                   ["Shorts候補_I_額縁と明るい薄紫", "S1.mp4"], ["番組化の見本", "章見出しC2.jpg"]])
def test_the_real_review_names_on_drive_still_count(ledger, parts):
    assert pg.is_review(parts, ledger)


def test_a_folder_named_after_a_topic_is_not_a_review_shelf(ledger):
    assert not pg.is_review(["候補者の話", "S1.mp4"], ledger)
    assert not pg.is_review(["Shorts_投稿用", "S11_選挙の候補者.mp4"], ledger)


def test_review_copy_of_another_cut_cannot_back_a_proposal(ledger, clips, tmp_path):
    """前の版の確認用（長さが違う）を付けた提案は断る — 見ていない投稿版に目視OK が付くのを防ぐ。"""
    longer = make_video(tmp_path / "前の版_確認用360p.mp4", size="640x360", seconds=9)
    with pytest.raises(pg.QualityError, match="長さが合いません"):
        pg.propose(ledger, recording=REC, kind="short", key="S1", publish=clips["s1"], review=longer)
    assert ledger["items"] == []


def test_qc_label_older_than_the_proposal_does_not_count(ledger, clips):
    item = pg.propose(ledger, recording=REC, kind="short", key="S1", publish=clips["s1"], review=clips["s2"])
    md5 = {f["role"]: f["md5"] for f in item["files"]}
    old = {"id": "x", "name": "確認用.mp4", "md5": md5["review"], "state": "目視OK",
           "checked_by": "北原克洋", "checked_on": "2026-10-23"}
    with pytest.raises(LookupError, match="より前です"):
        pg.approve_from_qc(ledger, {"checked": [old]}, recording=REC, key="S1", synthetic=False)
    # 投稿する物そのものを見た目視OK なら、日付は問わない
    pg.approve_from_qc(ledger, {"checked": [dict(old, md5=md5["publish"])]}, recording=REC, key="S1",
                       synthetic=False)


def test_a_snapshot_without_kind_flags_still_asks_about_videos(ledger):
    """種類の印（video / image）を書き忘れた控えで、未承認の動画が緑にならない。"""
    data = {"id": "r", "name": "動画制作", "folder": True, "children": [
        {"id": "f", "name": "40_完成", "folder": True, "children": [
            {"id": "rec", "name": REC, "folder": True, "children": [
                {"id": "sp", "name": "Shorts_投稿用", "folder": True, "children": [
                    {"id": "NEW1", "name": "09_S9_新作.mp4", "size": 123, "md5": "deadbeef"},
                    {"id": "T1", "name": "投稿文.txt", "size": 5},
                    {"id": "G1", "name": "投稿の順番", "size": 0}]}]}]}]}
    found = pg.drive_findings(pg.tree_from_json(data), LAYOUT, ledger)
    assert [f["code"] for f in found] == ["unapproved"] and "09_S9_新作.mp4" in found[0]["path"]


def test_snapshot_writes_the_kind_even_when_it_is_not_media():
    node = pg.tree_from_json({"id": "z", "name": "資料.zip", "size": 9, "video": False, "image": False})
    assert pg.tree_to_json(node)["video"] is False and not node.video
