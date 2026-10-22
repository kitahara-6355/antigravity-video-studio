"""backend/drive_layout.py — Drive の「動画制作」の決まり（2026-10-21 北原さん承認）。

守りたい性質:

1. 収録ID は「撮影日_ゲスト名」（同じ日の2本目は _2）。「最新」「テスト中」「新」は名前に入れない
2. raw のフォルダは名前ではなく id で分かる（名前を 10_raw に変える前でも）
3. 10_raw と同じ md5 の動画は「余分」。中身が余分だけのフォルダは一番外側までまとめて、
   北原さんが1回のドラッグで 90_保管 へ移せる単位にする。工程のフォルダと「動画制作」は動かさない
4. 10_raw に無い動画どうしの重複は、どれを残すか決めずに知らせる
5. AI が作る側のフォルダは印で見つけ、何度用意しても1つ。30_AVS_作業 の中に作る
6. 90_保管 の箱は名前に消す日が入り、過ぎたら知らせる

Google には接続しない。
"""
from __future__ import annotations

import datetime as dt
import itertools
import json

import pytest

from backend import asset_store, drive_layout as dl
from backend.drive_layout import Node

LAYOUT = dl.load_layout()
TODAY = dt.date(2026, 10, 21)
_ids = itertools.count(1)


def folder(name, *children):
    return Node(id=f"d{next(_ids)}", name=name, folder=True, path=name, children=list(children))


def video(name, md5, size=100):
    return Node(id=f"f{next(_ids)}", name=name, folder=False, path=name, md5=md5, size=size, video=True)


def doc(name):
    return Node(id=f"f{next(_ids)}", name=name, folder=False, path=name, md5="x" + name)


def base(*children, raw_id=None):
    root = folder("動画制作", *children)
    root.raw_id = raw_id

    def fix(n, prefix):
        n.path = f"{prefix}/{n.name}" if prefix else n.name
        for c in n.children:
            fix(c, n.path)
    fix(root, "")
    return root


def raw4():
    return [video("2025-09-22_16-34-33.mp4", "m1"), video("2025-09-22_17-09-02.mp4", "m2")]


def tidy(*extra, raw_children=None):
    """決まりどおりの「動画制作」。"""
    raw = folder("10_raw", *(raw_children if raw_children is not None
                             else [folder("20250922_久木田ヒロノブ", *raw4())]))
    return base(folder("00_使い方"), raw, folder("20_素材", folder("共通")), folder("30_AVS_作業"),
                folder("40_完成"), folder("90_保管"), *extra, raw_id=raw.id)


def codes(findings):
    return sorted(f.code for f in findings)


# --- 1. 名前 ----------------------------------------------------------------------


@pytest.mark.parametrize("name, ok", [
    ("20250922_久木田ヒロノブ", True),
    ("20250922_久木田ヒロノブ_2", True),
    ("20250922_久木田ヒロノブ_1", False),   # 2本目から
    ("20251322_久木田ヒロノブ", False),     # 13月は無い
    ("2025-09-22_久木田ヒロノブ", False),
    ("Raw最新_久木田収録", False),
    ("20250922", False),
    ("20250922_久木田 ヒロノブ", False),
])
def test_recording_id_shape(name, ok):
    assert dl.is_recording_id(name, LAYOUT) is ok


@pytest.mark.parametrize("name, word", [
    ("Raw最新_久木田収録", "最新"),
    ("000_テスト中", "テスト中"),
    ("新_編集", "新"),
    ("編集（新）", "新"),
    ("新規_素材", None),       # 単独の「新」でなければよい
    ("20250922_久木田ヒロノブ", None),
])
def test_forbidden_words(name, word):
    assert dl.forbidden_word(name, LAYOUT) == word


def test_finished_and_hold_names():
    assert dl.finished_name_ok("20250922_久木田ヒロノブ_v61_確認用360p.mp4", "20250922_久木田ヒロノブ", LAYOUT)
    assert not dl.finished_name_ok("完成動画_フェーズ１.mp4", "20250922_久木田ヒロノブ", LAYOUT)
    name = dl.hold_box_name("重複raw_20250922_久木田ヒロノブ", dt.date(2026, 11, 21))
    assert name == "20261121削除予定_重複raw_20250922_久木田ヒロノブ"
    assert dl.hold_box_date(name, LAYOUT) == dt.date(2026, 11, 21)
    assert dl.hold_box_date("古いもの", LAYOUT) is None


# --- 2〜4. 点検と移す一覧 ------------------------------------------------------------


def test_a_tidy_drive_has_no_findings():
    assert dl.audit(tidy(), LAYOUT, TODAY) == []


def test_today_drive_before_the_move():
    """2026-10-21 の実際の並び（01-input・重複4か所）。"""
    inp = folder("01-input", *raw4())
    root = base(
        folder("000_テスト中",
               folder("収録生動画-20260826T131940Z-1-001",
                      folder("収録生動画", *raw4(), folder("2025-09-22_撮影生データ", *raw4()))),
               folder("スライド用素材", doc("a.png"))),
        folder("000_収録動画", folder("Raw最新_久木田収録", *raw4())),
        inp, folder("30_AVS_作業"),
        raw_id=inp.id)

    moves = [n.path for n in dl.plan_moves(root, LAYOUT)]
    assert moves == ["動画制作/000_テスト中/収録生動画-20260826T131940Z-1-001", "動画制作/000_収録動画"]

    found = dl.audit(root, LAYOUT, TODAY)
    assert codes(found) == sorted(
        ["raw_name"] + ["missing_folder"] * 4 + ["raw_loose_video"] * 2
        + ["forbidden_word"] * 2 + ["duplicate_raw"] * 2)
    assert next(f for f in found if f.code == "raw_name").path == "動画制作/01-input"


def test_a_folder_with_other_files_is_not_moved_whole():
    root = tidy(folder("古い", folder("収録", *raw4(), doc("メモ.txt"))))
    moves = [n.path for n in dl.plan_moves(root, LAYOUT)]
    assert moves == ["動画制作/古い/収録/2025-09-22_16-34-33.mp4", "動画制作/古い/収録/2025-09-22_17-09-02.mp4"]


def test_a_partial_set_folder_is_moved_and_stage_folders_never_are():
    root = tidy(folder("x", video("2025-09-22_16-34-33.mp4", "m1")))
    root.children[2].children.append(video("dup.mp4", "m1"))  # 20_素材 の直下
    for n in root.walk():
        for c in n.children:
            c.path = f"{n.path}/{c.name}"
    moves = [n.path for n in dl.plan_moves(root, LAYOUT)]
    assert moves == ["動画制作/20_素材/dup.mp4", "動画制作/x"]


def test_duplicates_already_in_hold_are_not_counted():
    root = tidy()
    hold = next(c for c in root.children if c.name == "90_保管")
    box = folder("20261121削除予定_重複raw", *raw4())
    hold.children.append(box)
    base_fix = base(*root.children, raw_id=root.raw_id)
    assert dl.plan_moves(base_fix, LAYOUT) == []
    assert dl.audit(base_fix, LAYOUT, TODAY) == []


def test_duplicates_with_no_copy_in_raw_are_reported_not_planned():
    root = tidy(folder("a", video("x.mp4", "zz")), folder("b", video("x.mp4", "zz")))
    assert dl.plan_moves(root, LAYOUT) == []
    assert codes(dl.audit(root, LAYOUT, TODAY)) == ["duplicate_unkept"]


def test_raw_must_be_in_recording_id_folders():
    root = tidy(raw_children=[folder("Raw最新_久木田収録", *raw4())])
    assert codes(dl.audit(root, LAYOUT, TODAY)) == ["forbidden_word", "raw_bad_id"]


def test_hold_box_overdue_and_undated():
    root = tidy()
    hold = next(c for c in root.children if c.name == "90_保管")
    hold.children += [folder("20261001削除予定_古い版"), folder("あとで消す")]
    root = base(*root.children, raw_id=root.raw_id)
    assert codes(dl.audit(root, LAYOUT, TODAY)) == ["hold_no_date", "hold_overdue"]


def test_finished_names():
    root = tidy()
    fin = next(c for c in root.children if c.name == "40_完成")
    fin.children += [folder("20250922_久木田ヒロノブ",
                            video("20250922_久木田ヒロノブ_v61_確認用360p.mp4", "a1"),
                            video("完成動画_フェーズ１.mp4", "a2")),
                     video("loose.mp4", "a3")]
    root = base(*root.children, raw_id=root.raw_id)
    assert codes(dl.audit(root, LAYOUT, TODAY)) == ["finished_bad_name", "finished_loose"]


# --- 5〜6. AI が作る側のフォルダ（偽の Drive） ----------------------------------------


class _Req:
    def __init__(self, fn):
        self._fn = fn

    def execute(self, num_retries=0):
        return self._fn()


class FakeDrive:
    """drive.file で見える物だけを持つ偽物。検索式は drive_layout・asset_store が作る形だけ読む。"""

    def __init__(self):
        self.items = {"base": {"id": "base", "name": "動画制作", "mimeType": dl.FOLDER_MIME,
                               "parents": [], "appProperties": {}}}
        self._n = 0

    def files(self):
        return self

    def list(self, q, fields, **_):
        terms = [t.strip() for t in q.split(" and ")]

        def ok(f):
            if f.get("trashed"):
                return False
            for t in terms:
                if t.startswith("name = '") and f["name"] != t[8:-1].replace("\\'", "'"):
                    return False
                if t.endswith("' in parents") and t[1:-len("' in parents")] not in f["parents"]:
                    return False
                if t.startswith("mimeType = ") and f["mimeType"] != t.split("'")[1]:
                    return False
                if t.startswith("appProperties has {") and t.split("'")[1] not in f["appProperties"]:
                    return False
                if t.startswith("value='") and t.split("'")[1] not in f["appProperties"].values():
                    return False
            return True
        return _Req(lambda: {"files": [dict(f) for f in self.items.values() if ok(f)]})

    def create(self, body, fields, **_):
        def run():
            self._n += 1
            f = {"id": f"n{self._n}", "name": body["name"], "mimeType": body.get("mimeType"),
                 "parents": body.get("parents", ["mydrive"]), "appProperties": body.get("appProperties", {})}
            self.items[f["id"]] = f
            return dict(f)
        return _Req(run)

    def get(self, fileId, fields, **_):
        return _Req(lambda: {"parents": self.items[fileId]["parents"]})

    def named(self, name):
        return [f for f in self.items.values() if f["name"] == name]


@pytest.fixture()
def drive(monkeypatch):
    monkeypatch.delenv(asset_store.ROOT_NAME_ENV, raising=False)
    d = FakeDrive()
    root = asset_store.ensure_root(d)
    d.items[root]["parents"] = ["base"]  # 30_AVS_作業 は動画制作へ移してある
    return d


def test_prepare_creates_ai_folders_inside_the_work_root_once(drive):
    work = next(f["id"] for f in drive.items.values() if f["appProperties"].get("avs_assets_root"))
    lines = dl.prepare(drive, LAYOUT)
    made = {f["name"]: f for f in drive.items.values() if f["appProperties"].get(dl.LAYOUT_MARK)}
    assert sorted(made) == ["00_使い方", "20_素材", "40_完成", "90_保管"]  # 10_raw・30 は作らない
    assert all(f["parents"] == [work] for f in made.values())
    assert any("作った" in line for line in lines)
    assert len(drive.named("共通")) == 1

    # 北原さんが動画制作へ移した後
    for f in made.values():
        f["parents"] = ["base"]
    count = len(drive.items)
    lines = dl.prepare(drive, LAYOUT)
    assert len(drive.items) == count
    assert all("移してある" in line for line in lines)


def test_prepare_with_a_recording_makes_its_folders_but_never_raw(drive):
    lines = dl.prepare(drive, LAYOUT, "20250922_久木田ヒロノブ")
    parents = {drive.items[f["parents"][0]]["name"] for f in drive.named("20250922_久木田ヒロノブ")}
    assert parents == {"20_素材", "40_完成", "収録"}
    assert any("10_raw/20250922_久木田ヒロノブ: 人が作る" in line for line in lines)
    with pytest.raises(ValueError, match="収録ID"):
        dl.prepare(drive, LAYOUT, "Raw最新_久木田収録")


def test_hold_box_is_made_in_90_with_the_date(drive):
    _, name = dl.make_hold_box(drive, LAYOUT, "重複raw_20250922_久木田ヒロノブ", dt.date(2026, 11, 21))
    box = drive.named(name)[0]
    assert drive.items[box["parents"][0]]["name"] == "90_保管"
    assert name == "20261121削除予定_重複raw_20250922_久木田ヒロノブ"
    dl.make_hold_box(drive, LAYOUT, "重複raw_20250922_久木田ヒロノブ", dt.date(2026, 11, 21))
    assert len(drive.named(name)) == 1
    with pytest.raises(ValueError):
        dl.make_hold_box(drive, LAYOUT, "a/b", dt.date(2026, 11, 21))


def test_put_goes_only_to_ai_written_folders(drive, monkeypatch, tmp_path):
    sent = {}
    monkeypatch.setattr(asset_store, "put_tree",
                        lambda service, local, sub, root_id: sent.update(root=root_id, sub=sub) or [])
    dl.put_to(drive, LAYOUT, "finished", tmp_path, "20250922_久木田ヒロノブ")
    assert drive.items[sent["root"]]["name"] == "40_完成"
    assert sent["sub"] == "20250922_久木田ヒロノブ"
    for key in ("raw", "material", "hold", "work"):
        with pytest.raises(ValueError, match="送れません"):
            dl.put_to(drive, LAYOUT, key, tmp_path)


# --- 7. 品質確認の控え（2026-10-22） -----------------------------------------------------


def test_qc_entry_records_the_md5_and_a_changed_video_loses_its_check():
    root = tidy()
    fin = next(c for c in root.children if c.name == "40_完成")
    clip = video("20250922_久木田ヒロノブ_v61_確認用360p.mp4", "ok1")
    fin.children.append(folder("20250922_久木田ヒロノブ", clip))
    root = base(*root.children, raw_id=root.raw_id)
    entry = dl.qc_entry(clip, "北原", dt.date(2026, 10, 19), "目視OK")
    assert entry["md5"] == "ok1" and entry["id"] == clip.id
    ledger = {"checked": [entry]}
    assert dl.qc_findings(root, ledger) == []

    clip.md5 = "other"  # 同じ id のまま新しい版で差し替えられた
    found = dl.qc_findings(root, ledger)
    assert codes(found) == ["qc_changed"]
    assert "確認は外れました" in found[0].message


def test_qc_follows_the_id_when_moved_or_renamed_and_warns_when_gone():
    root = tidy()
    clip = video("a.mp4", "ok1")
    root.children[0].children.append(clip)
    entry = dl.qc_entry(clip, "北原", TODAY, "目視OK")
    clip.name = "b.mp4"
    assert dl.qc_findings(root, {"checked": [entry]}) == []
    root.children[0].children.clear()
    assert codes(dl.qc_findings(root, {"checked": [entry]})) == ["qc_missing"]


def test_qc_entry_needs_a_video_with_md5():
    with pytest.raises(ValueError):
        dl.qc_entry(doc("メモ.txt"), "北原", TODAY, "目視OK")


class _LabelDrive:
    """files().listLabels だけを持つ偽物。"""

    def __init__(self, labels):
        self._labels = labels

    def files(self):
        return self

    def listLabels(self, fileId):
        return _Req(lambda: {"labels": self._labels.get(fileId, [])})


def _label(choice, date="2026-10-20", by="北原克洋"):
    spec = LAYOUT["qc_label"]
    f = spec["fields"]
    return {"id": spec["id"], "fields": {
        f["state"]: {"selection": [choice]} if choice else {},
        f["date"]: {"dateString": [date]},
        f["by"]: {"user": [{"displayName": by, "emailAddress": "x@example.com"}]}}}


def _finished_tree(*clips):
    root = tidy()
    fin = next(c for c in root.children if c.name == "40_完成")
    fin.children.append(folder("20250922_久木田ヒロノブ", *clips))
    return base(*root.children, raw_id=root.raw_id)


def test_labels_are_read_only_on_finished_videos_and_mapped_to_states():
    ok, fix, other = video("v61.mp4", "a"), video("v60.mp4", "b"), video("x.mp4", "c")
    root = _finished_tree(ok, fix)
    root.children[0].children.append(other)  # 00_使い方 の動画は読まない
    service = _LabelDrive({ok.id: [_label(LAYOUT["qc_label"]["ok_choice"])],
                           fix.id: [_label("OTHER")], other.id: [_label(LAYOUT["qc_label"]["ok_choice"])]})
    got = dl.read_labels(service, root, LAYOUT)
    assert got == {ok.id: {"state": "目視OK", "date": "2026-10-20", "by": "北原克洋"},
                   fix.id: {"state": "要直し", "date": "2026-10-20", "by": "北原克洋"}}


def test_sync_adds_new_labels_and_never_rerecords_a_changed_video():
    clip, fresh = video("v61.mp4", "a"), video("v62.mp4", "n")
    root = _finished_tree(clip, fresh)
    old = dl.qc_entry(clip, "北原", dt.date(2026, 10, 20), "目視OK")
    lab = {"state": "目視OK", "date": "2026-10-22", "by": "北原克洋"}
    ledger, notes = dl.sync_qc(root, {clip.id: lab, fresh.id: lab}, {"checked": [old]})
    assert [e["id"] for e in ledger["checked"]] == [clip.id, fresh.id]
    assert ledger["checked"][1]["md5"] == "n" and ledger["checked"][1]["checked_on"] == "2026-10-22"
    assert "email" not in json.dumps(ledger)  # 台帳にメールアドレスを残さない

    clip.md5 = "changed"
    ledger2, notes2 = dl.sync_qc(root, {clip.id: lab}, ledger)
    assert ledger2["checked"][0]["md5"] == "a"  # 控え直さない
    assert any("確認は外れた" in n for n in notes2)
    assert codes(dl.qc_findings(root, ledger2)) == ["qc_changed"]


def test_check_id_cli():
    assert dl.main(["check-id", "20250922_久木田ヒロノブ"]) == 0
    assert dl.main(["check-id", "Raw最新_久木田収録"]) == 1


def test_layout_names_match_the_approved_plan():
    assert [f["name"] for f in LAYOUT["folders"]] == [
        "00_使い方", "10_raw", "20_素材", "30_AVS_作業", "40_完成", "90_保管"]
    assert [f["key"] for f in LAYOUT["folders"] if f["ai"] == "write"] == ["guide", "work", "finished"]
