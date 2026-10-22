"""backend/drive_organize.py — 「動画制作」を整理する道具の歯止め（2026-10-22）。

鍵は Drive 全体（drive）に届くので、raw を守るのはこの道具の側。守りたい性質:

1. 10_raw の中の物は外へ出さない。外の物を 10_raw へ入れない
2. 10_raw の中のファイルの名前は変えない。中のフォルダは収録ID の名前だけ
3. 「動画制作」と工程のフォルダは動かさない・名前を変えない
4. 行き先に同じ名前があれば止まる
5. 既定は下見で Drive を呼ばない。--apply のときだけ変え、md5 を照合し、記録に残す
6. 鍵の権限は drive ちょうど
7. 消す口・ゴミ箱へ入れる口を持たない

Google には接続しない。
"""
from __future__ import annotations

import datetime as dt
import itertools
import json
import re
from pathlib import Path

import pytest

from backend import drive_layout as dl
from backend import drive_organize as org
from backend.drive_layout import Node
from backend.services.google_oauth import GoogleAuthError

LAYOUT = dl.load_layout()
_ids = itertools.count(1)


def folder(name, *children):
    return Node(id=f"d{next(_ids)}", name=name, folder=True, path=name, children=list(children))


def video(name, md5, size=100):
    return Node(id=f"f{next(_ids)}", name=name, folder=False, path=name, md5=md5, size=size, video=True)


def tree(*extra, finished=()):
    raw = folder("10_raw", folder("20250922_久木田ヒロノブ",
                                  video("2025-09-22_16-34-33.mp4", "m1"),
                                  video("2025-09-22_17-09-02.mp4", "m2")))
    root = folder("動画制作", folder("00_使い方"), raw, folder("20_素材", folder("共通")),
                  folder("30_AVS_作業"),
                  folder("40_完成", folder("20250922_久木田ヒロノブ", *finished)),
                  folder("90_保管"), *extra)
    root.raw_id = raw.id

    def fix(n, prefix):
        n.path = f"{prefix}/{n.name}" if prefix else n.name
        for c in n.children:
            fix(c, n.path)
    fix(root, "")
    return org.Tree(root, LAYOUT)


class FakeDrive:
    """呼ばれた書き込みを控え、get には木の md5 を返す（変えたい id は tamper で）。"""

    def __init__(self, t: org.Tree | None = None):
        self.calls: list[tuple[str, dict]] = []
        self.md5 = {n.id: (n.md5, n.size) for n in t.root.walk()} if t else {}
        self.tamper: dict[str, str] = {}

    def files(self):
        return self

    def _ret(self, value):
        class _Req:
            def execute(_self):
                return value
        return _Req()

    def update(self, **kw):
        self.calls.append(("update", kw))
        return self._ret({"id": kw["fileId"]})

    def create(self, **kw):
        self.calls.append(("create", kw))
        return self._ret({"id": "made1"})

    def get(self, **kw):
        md5, size = self.md5.get(kw["fileId"], (None, 0))
        return self._ret({"md5Checksum": self.tamper.get(kw["fileId"], md5), "size": str(size)})

    def writes(self):
        return [c for c in self.calls if c[0] in ("update", "create")]


V61 = "20250922久木田ヒロノブv61確認用360p.mp4"
DONE = "40_完成/20250922_久木田ヒロノブ"


# --- 1. raw の出入り ------------------------------------------------------------------


def test_raw_is_never_moved_out_of_10_raw(tmp_path):
    t = tree()
    src = t.get("10_raw/20250922_久木田ヒロノブ/2025-09-22_16-34-33.mp4")
    with pytest.raises(org.GuardError, match="raw"):
        org.move(FakeDrive(t), t, src, t.get("90_保管"), apply=True, journal=tmp_path / "j")
    with pytest.raises(org.GuardError):
        org.move(FakeDrive(t), t, t.get("10_raw/20250922_久木田ヒロノブ"), t.get("30_AVS_作業"))


def test_nothing_from_outside_goes_into_10_raw():
    t = tree(folder("000_収録動画", video("a.mp4", "m1")))
    with pytest.raises(org.GuardError, match="10_raw に入れるのは人"):
        org.move(FakeDrive(t), t, t.get("000_収録動画"), t.get("10_raw"))


def test_moving_within_10_raw_is_allowed():
    t = tree()
    raw = t.get("10_raw")
    raw.children.append(Node(id="d999", name="20251001_山田", folder=True, path="動画制作/10_raw/20251001_山田"))
    t = org.Tree(t.root, LAYOUT)
    line = org.move(FakeDrive(t), t, t.get("10_raw/20250922_久木田ヒロノブ/2025-09-22_16-34-33.mp4"),
                    t.get("10_raw/20251001_山田"))
    assert line.startswith("（下見）")


# --- 2. raw の名前 --------------------------------------------------------------------


def test_raw_files_are_never_renamed():
    t = tree()
    src = t.get("10_raw/20250922_久木田ヒロノブ/2025-09-22_16-34-33.mp4")
    with pytest.raises(org.GuardError, match="撮ったまま"):
        org.rename(FakeDrive(t), t, src, "1本目.mp4")
    with pytest.raises(org.GuardError, match="撮ったまま"):
        org.move(FakeDrive(t), t, src, t.get("10_raw/20250922_久木田ヒロノブ"), "x.mp4")


def test_folders_in_10_raw_take_only_recording_ids():
    t = tree()
    rec = t.get("10_raw/20250922_久木田ヒロノブ")
    with pytest.raises(org.GuardError, match="収録ID"):
        org.rename(FakeDrive(t), t, rec, "久木田収録_最新")
    assert org.rename(FakeDrive(t), t, rec, "20250922_久木田ヒロノブ_2").startswith("（下見）")
    with pytest.raises(org.GuardError, match="収録ID"):
        org.mkdir(FakeDrive(t), t, t.get("10_raw"), "新しいフォルダ")
    assert org.mkdir(FakeDrive(t), t, t.get("10_raw"), "20251001_山田").startswith("（下見）")


# --- 3. 動かさない物 --------------------------------------------------------------


@pytest.mark.parametrize("rel", ["", "00_使い方", "10_raw", "20_素材", "30_AVS_作業", "40_完成", "90_保管"])
def test_base_and_stage_folders_are_fixed(rel):
    t = tree()
    node = t.get(rel)
    with pytest.raises(org.GuardError, match="工程のフォルダ"):
        org.rename(FakeDrive(t), t, node, "x")
    with pytest.raises(org.GuardError, match="工程のフォルダ"):
        org.move(FakeDrive(t), t, node, t.get("90_保管" if rel != "90_保管" else "30_AVS_作業"))


def test_cannot_move_into_itself():
    t = tree(folder("000_テスト中", folder("中")))
    with pytest.raises(org.GuardError, match="自分の中"):
        org.move(FakeDrive(t), t, t.get("000_テスト中"), t.get("000_テスト中/中"))


def test_destination_must_be_a_folder():
    t = tree(finished=[video(V61, "q1"), video("b.mp4", "q2")])
    with pytest.raises(org.GuardError, match="フォルダではありません"):
        org.move(FakeDrive(t), t, t.get(f"{DONE}/b.mp4"), t.get(f"{DONE}/{V61}"))


# --- 4. 上書きしない -------------------------------------------------------------


def test_name_collision_stops():
    t = tree(finished=[video(V61, "q1"), video("20250922_久木田ヒロノブ_v61_確認用360p.mp4", "q2")])
    with pytest.raises(org.GuardError, match="既にあります"):
        org.rename(FakeDrive(t), t, t.get(f"{DONE}/{V61}"), "20250922_久木田ヒロノブ_v61_確認用360p.mp4")
    with pytest.raises(org.GuardError, match="既にあります"):
        org.mkdir(FakeDrive(t), t, t.get("40_完成"), "20250922_久木田ヒロノブ")


def test_bad_names_stop():
    t = tree(finished=[video(V61, "q1")])
    for bad in ("", "a/b"):
        with pytest.raises(org.GuardError, match="不正"):
            org.rename(FakeDrive(t), t, t.get(f"{DONE}/{V61}"), bad)


def test_unknown_or_ambiguous_path_stops():
    t = tree()
    with pytest.raises(org.GuardError, match="ありません"):
        t.get("40_完成/無い")
    t.root.children.append(Node(id="dz", name="00_使い方", folder=True, path="動画制作/00_使い方"))
    with pytest.raises(org.GuardError, match="2 つ"):
        t.get("00_使い方")
    assert t.get("動画制作/10_raw").name == "10_raw"


# --- 5. 下見・実行・照合・記録 ------------------------------------------------------


def test_dry_run_calls_nothing(tmp_path):
    t = tree(finished=[video(V61, "q1")])
    drive = FakeDrive(t)
    journal = tmp_path / "j.jsonl"
    line = org.rename(drive, t, t.get(f"{DONE}/{V61}"), "20250922_久木田ヒロノブ_v61_確認用360p.mp4",
                      journal=journal)
    assert line.startswith("（下見）")
    assert drive.calls == []
    assert not journal.exists()


def test_apply_renames_verifies_and_journals(tmp_path):
    t = tree(finished=[video(V61, "q1")])
    drive = FakeDrive(t)
    journal = tmp_path / "j.jsonl"
    node = t.get(f"{DONE}/{V61}")
    org.rename(drive, t, node, "20250922_久木田ヒロノブ_v61_確認用360p.mp4", apply=True, journal=journal)
    assert drive.writes() == [("update", {"fileId": node.id,
                                          "body": {"name": "20250922_久木田ヒロノブ_v61_確認用360p.mp4"},
                                          "fields": "id, name", "supportsAllDrives": True})]
    rec = json.loads(journal.read_text(encoding="utf-8"))
    assert rec["op"] == "rename" and rec["id"] == node.id and rec["to"].endswith("v61_確認用360p.mp4")


def test_apply_move_uses_parents_and_checks_md5(tmp_path):
    t = tree(folder("000_収録動画", video("a.mp4", "m1"), video("b.mp4", "m2")))
    drive = FakeDrive(t)
    src, box = t.get("000_収録動画"), t.get("90_保管")
    line = org.move(drive, t, src, box, apply=True, journal=tmp_path / "j")
    (_, kw), = drive.writes()
    assert kw["addParents"] == box.id and kw["removeParents"] == t.root.id
    assert "動画 2 本の md5 一致" in line


def test_md5_mismatch_after_move_stops_and_is_not_journaled(tmp_path):
    t = tree(folder("000_収録動画", video("a.mp4", "m1")))
    drive = FakeDrive(t)
    src = t.get("000_収録動画")
    drive.tamper[src.children[0].id] = "changed"
    journal = tmp_path / "j"
    with pytest.raises(org.GuardError, match="md5"):
        org.move(drive, t, src, t.get("90_保管"), apply=True, journal=journal)
    assert not journal.exists()


def test_hold_moves_duplicates_into_a_dated_box(tmp_path):
    t = tree(folder("000_収録動画", video("a.mp4", "m1"), video("b.mp4", "m2")))
    drive = FakeDrive(t)
    lines = org.hold(drive, t, "重複raw_20250922_久木田ヒロノブ", dt.date(2026, 11, 21),
                     apply=True, journal=tmp_path / "j")
    assert lines[0].endswith("90_保管/20261121削除予定_重複raw_20250922_久木田ヒロノブ")
    create, move = drive.writes()
    assert create[0] == "create" and create[1]["body"]["parents"] == [t.get("90_保管").id]
    assert move[1]["fileId"] == t.get("000_収録動画").id and move[1]["addParents"] == "made1"


def test_hold_with_nothing_to_move():
    t = tree()
    assert org.hold(FakeDrive(t), t, "x", dt.date(2026, 11, 21)) == ["90_保管 へ移す重複した raw はありません"]


# --- 6. 鍵 ----------------------------------------------------------------------------


def test_scope_must_be_exactly_drive():
    org.check_scope({"scopes": ["https://www.googleapis.com/auth/drive"]})
    for scopes in ([], ["https://www.googleapis.com/auth/drive.file"],
                   ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/gmail.send"]):
        with pytest.raises(GoogleAuthError, match="--organize"):
            org.check_scope({"scopes": scopes})


def test_missing_token_fails_without_touching_drive(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("AVS_DRIVE_ORGANIZER_TOKEN_JSON", raising=False)
    monkeypatch.setattr(org, "organizer_token_path", lambda: tmp_path / "none.json")
    assert org.main(["rename", "40_完成/x", "y"]) == 1
    assert "🚫" in capsys.readouterr().err


def test_no_command_is_usage_error():
    assert org.main([]) == 2


# --- 7. 消す口が無い ------------------------------------------------------------------


def test_source_has_no_delete_or_trash():
    src = Path(org.__file__).read_text(encoding="utf-8")
    code = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("#"))
    code = re.sub(r'"""[\s\S]*?"""', "", code)
    assert ".delete(" not in code
    assert "emptyTrash" not in code
    assert '"trashed"' not in code and "'trashed'" not in code
    assert "media_body" not in code and "MediaFileUpload" not in code
