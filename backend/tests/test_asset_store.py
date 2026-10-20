"""backend/asset_store.py — 過程の資産の置き場（Drive・drive.file）。

守りたい性質:

1. **drive.file ちょうどのトークンでなければ、何も送らずに止まる**（読み取り用・Drive 全体・混ざったもの）
2. 資産の口は資産のトークンだけを見る。読み取り用のトークンには落ちない
3. フォルダは何度用意しても1つ。同じ md5 の物は送り直さない
4. Drive の md5・大きさが手元と違えば成功と言わない。同じ名前で中身が違えば新しい版にする
5. ディレクトリを相対パスのまま送り、マニフェストを返す

Google には接続しない（Drive は下の偽物）。
"""
from __future__ import annotations

import hashlib
import json
import re

import pytest

from backend import asset_store, raw_source
from backend.services import google_oauth

FILE = "https://www.googleapis.com/auth/drive.file"
READONLY = "https://www.googleapis.com/auth/drive.readonly"
FULL = "https://www.googleapis.com/auth/drive"
FOLDER = asset_store.FOLDER_MIME


def _token(scopes) -> str:
    return json.dumps({"token": "at", "refresh_token": "SECRET-RT", "client_id": "cid",
                       "client_secret": "cs", "scopes": scopes})


@pytest.fixture(autouse=True)
def _isolated_tokens(monkeypatch, tmp_path):
    """実行環境の本物のトークンを読まない。ローカルの保存先も tmp に向ける。"""
    for name in (google_oauth.TOKEN_JSON_ENV, google_oauth.ASSETS_TOKEN_JSON_ENV,
                 asset_store.ROOT_NAME_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ANTIGRAVITY_GOOGLE_TOKEN", str(tmp_path / "google" / "token.json"))


# --- 偽の Drive ----------------------------------------------------------------


class _Req:
    def __init__(self, fn, chunks=1):
        self._fn = fn
        self._chunks = chunks
        self.calls = 0

    def execute(self, num_retries=0):
        return self._fn()

    def next_chunk(self, num_retries=0):
        self.calls += 1
        if self.calls < self._chunks:
            return object(), None
        return None, self._fn()


class _Media:
    def __init__(self, path, resumable):
        self.path = path
        self.resumable = resumable


class FakeDrive:
    """files().list / create / update だけを持つ偽物。検索式は asset_store が作る形だけ読む。

    `corrupt` に名前を入れると、その名前の送信は中身を1バイト欠かして保存する（途中で切れた）。
    """

    def __init__(self):
        self.items: dict[str, dict] = {}
        self.corrupt: set[str] = set()
        self.creates = 0
        self.updates = 0
        self.lists: list[str] = []
        self._n = 0

    def files(self):
        return self

    def _new_id(self):
        self._n += 1
        return f"id{self._n:04d}"

    @staticmethod
    def _content(name, media, corrupt):
        data = media.path.read_bytes()
        if name in corrupt:
            data = data[:-1]
        return {"md5Checksum": hashlib.md5(data).hexdigest(), "size": str(len(data))}

    def list(self, q, fields, pageToken=None, pageSize=100, orderBy=None, **_):
        self.lists.append(q)

        def run():
            hits = [dict(f) for f in self.items.values() if _matches(f, q)]
            hits.sort(key=lambda f: f["name"])
            return {"files": hits}
        return _Req(run)

    def create(self, body, fields, media_body=None, **_):
        def run():
            self.creates += 1
            f = {"id": self._new_id(), "name": body["name"],
                 "mimeType": body.get("mimeType", "application/octet-stream"),
                 "parents": body.get("parents", ["root"]), "trashed": False,
                 "appProperties": body.get("appProperties", {})}
            if media_body is not None:
                f.update(self._content(body["name"], media_body, self.corrupt))
            self.items[f["id"]] = f
            return dict(f)
        return _Req(run, chunks=3 if media_body is not None and media_body.resumable else 1)

    def update(self, fileId, media_body, fields, **_):
        def run():
            self.updates += 1
            f = self.items[fileId]
            f.update(self._content(f["name"], media_body, self.corrupt))
            return dict(f)
        return _Req(run, chunks=2 if media_body.resumable else 1)

    # 便利: 名前のパスで物を探す（テストの確認用）
    def named(self, name, parent=None):
        return [f for f in self.items.values()
                if f["name"] == name and (parent is None or parent in f["parents"])]


def _unquote(s):
    return s.replace("\\'", "'").replace("\\\\", "\\")


def _matches(f, q):
    for term in q.split(" and "):
        term = term.strip()
        if term == "trashed = false":
            if f.get("trashed"):
                return False
        elif m := re.fullmatch(r"name = '((?:[^'\\]|\\.)*)'", term):
            if f["name"] != _unquote(m.group(1)):
                return False
        elif m := re.fullmatch(r"'((?:[^'\\]|\\.)*)' in parents", term):
            if _unquote(m.group(1)) not in f.get("parents", []):
                return False
        elif m := re.fullmatch(r"mimeType (=|!=) '([^']*)'", term):
            same = f.get("mimeType") == m.group(2)
            if same != (m.group(1) == "="):
                return False
        elif term.startswith("appProperties has {"):
            # 「appProperties has { key='k' and value='v' }」は " and " で2つに割れる
            key = re.search(r"key='([^']*)'", term).group(1)
            if key not in f.get("appProperties", {}):
                return False
        elif m := re.fullmatch(r"value='([^']*)' }", term):
            if m.group(1) not in f.get("appProperties", {}).values():
                return False
        else:
            raise AssertionError(f"偽の Drive が読めない検索式: {term}")
    return True


@pytest.fixture()
def drive(monkeypatch):
    monkeypatch.setattr(asset_store, "_media", lambda path, resumable: _Media(path, resumable))
    return FakeDrive()


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


# --- 1. 権限の確認 ---------------------------------------------------------------


def test_a_drive_file_token_passes(monkeypatch):
    monkeypatch.setenv(google_oauth.ASSETS_TOKEN_JSON_ENV, _token([FILE]))
    _, source = asset_store.load_token_info()
    assert google_oauth.ASSETS_TOKEN_JSON_ENV in source


@pytest.mark.parametrize("scopes", [
    [READONLY],
    [FULL],
    [FILE, READONLY],
    [FILE, FULL],
    [FILE, "https://www.googleapis.com/auth/spreadsheets"],
    [],
])
def test_a_token_other_than_exactly_drive_file_is_refused(monkeypatch, scopes):
    monkeypatch.setenv(google_oauth.ASSETS_TOKEN_JSON_ENV, _token(scopes))
    with pytest.raises(asset_store.ScopeError) as exc:
        asset_store.load_token_info()
    assert "--assets" in str(exc.value)
    assert "何も送っていません" in str(exc.value)
    assert "SECRET-RT" not in str(exc.value)


def test_a_missing_token_is_refused_with_the_login_hint():
    with pytest.raises(google_oauth.CredentialsNotFoundError) as exc:
        asset_store.load_token_info()
    assert google_oauth.ASSETS_TOKEN_JSON_ENV in str(exc.value)
    assert "--assets" in str(exc.value)


def test_the_readonly_token_is_never_used_as_the_assets_token(monkeypatch):
    """読み取り用の口に drive.file のトークンが入っていても、資産の口は拾わない。"""
    monkeypatch.setenv(google_oauth.TOKEN_JSON_ENV, _token([FILE]))
    with pytest.raises(google_oauth.CredentialsNotFoundError):
        asset_store.load_token_info()


def test_the_local_token_file_is_read(monkeypatch, tmp_path):
    path = google_oauth.assets_token_path()
    path.parent.mkdir(parents=True)
    path.write_text(_token([FILE]), encoding="utf-8")
    _, source = asset_store.load_token_info()
    assert source == str(path)
    assert path.name == "token_assets_file.json"


def test_build_drive_checks_the_scope_before_loading_credentials(monkeypatch):
    """広すぎるトークンでは認証の段まで進まない（API にも届かない）。"""
    monkeypatch.setenv(google_oauth.ASSETS_TOKEN_JSON_ENV, _token([FULL]))
    monkeypatch.setattr(asset_store, "load_credentials",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("認証へ進んだ")))
    with pytest.raises(asset_store.ScopeError):
        asset_store._build_drive()


def test_cli_put_with_a_broad_token_sends_nothing(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(google_oauth.ASSETS_TOKEN_JSON_ENV, _token([FULL]))
    monkeypatch.setattr(asset_store, "load_credentials",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("認証へ進んだ")))
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    assert asset_store.main(["put", str(tmp_path), "--to", "job"]) == 1
    assert "drive.file" in capsys.readouterr().err


def test_raw_source_refuses_the_drive_file_token():
    """逆向きの混同も止まる: 資産のトークンでは raw を読まない。"""
    with pytest.raises(raw_source.TooBroadScopeError):
        raw_source.check_read_only({"scopes": [FILE]})


# --- 2. CLI check（外に出ない） ---------------------------------------------------


def test_cli_check_passes_with_a_drive_file_token(monkeypatch, capsys):
    monkeypatch.setenv(google_oauth.ASSETS_TOKEN_JSON_ENV, _token([FILE]))
    monkeypatch.setattr(asset_store, "_build_drive",
                        lambda: (_ for _ in ()).throw(AssertionError("check で Drive を作った")))
    assert asset_store.main(["check"]) == 0
    out = capsys.readouterr().out
    assert "drive.file" in out and "AVS 過程の資産" in out
    assert "SECRET-RT" not in out


def test_cli_check_fails_without_a_token(capsys):
    assert asset_store.main(["check"]) == 1
    assert "--assets" in capsys.readouterr().err


def test_cli_without_a_command_shows_help():
    assert asset_store.main([]) == 2


# --- 3. フォルダ ------------------------------------------------------------------


def test_the_root_is_created_once_in_my_drive_and_found_again(drive):
    first = asset_store.ensure_root(drive)
    second = asset_store.ensure_root(drive)

    assert first == second
    [root] = drive.named("AVS 過程の資産")
    assert root["parents"] == ["root"]  # parents を付けずに作る = マイドライブ
    assert root["mimeType"] == FOLDER
    assert drive.creates == 1


def test_the_root_name_comes_from_the_env(drive, monkeypatch):
    monkeypatch.setenv(asset_store.ROOT_NAME_ENV, "試しの置き場")
    asset_store.ensure_root(drive)
    assert drive.named("試しの置き場")


def test_a_subfolder_with_the_root_name_is_not_taken_for_the_root(drive):
    root = asset_store.ensure_root(drive)
    asset_store.ensure_path(drive, root, "AVS 過程の資産")  # 下に同じ名前
    assert asset_store.ensure_root(drive) == root


def test_a_trashed_root_is_not_reused(drive):
    old = asset_store.ensure_root(drive)
    drive.items[old]["trashed"] = True
    assert asset_store.ensure_root(drive) != old


def test_two_roots_with_the_same_name_stop(drive):
    asset_store.ensure_root(drive)
    for f in list(drive.items.values()):
        dup = dict(f, id="dup")
        drive.items["dup"] = dup
    with pytest.raises(asset_store.PathError):
        asset_store.ensure_root(drive)


def test_ensure_path_is_idempotent(drive):
    root = asset_store.ensure_root(drive)
    a = asset_store.ensure_path(drive, root, "job/sub/dir")
    created = drive.creates
    b = asset_store.ensure_path(drive, root, "job/sub/dir")
    c = asset_store.ensure_path(drive, root, "/job//sub/dir/")

    assert a == b == c
    assert drive.creates == created
    [job] = drive.named("job", root)
    [sub] = drive.named("sub", job["id"])
    assert drive.named("dir", sub["id"])[0]["id"] == a


def test_ensure_path_with_an_empty_path_is_the_root(drive):
    root = asset_store.ensure_root(drive)
    assert asset_store.ensure_path(drive, root, "") == root


@pytest.mark.parametrize("bad", ["../x", "a/../b", "./a"])
def test_ensure_path_refuses_dot_segments(drive, bad):
    with pytest.raises(asset_store.PathError):
        asset_store.ensure_path(drive, "root-id", bad)


def test_names_with_quotes_are_escaped_in_the_query(drive):
    root = asset_store.ensure_root(drive)
    a = asset_store.ensure_path(drive, root, "北原's 対談")
    assert asset_store.ensure_path(drive, root, "北原's 対談") == a
    assert any("北原\\'s" in q for q in drive.lists)


# --- 4. 1ファイルの送信 ------------------------------------------------------------


def test_put_uploads_resumably_and_checks_md5_and_size(drive, tmp_path):
    root = asset_store.ensure_root(drive)
    p = tmp_path / "captions.srt"
    p.write_bytes(b"1\n00:00:00,000 --> 00:00:01,000\n\xe3\x81\x82\n")

    entry = asset_store.put(drive, p, root)

    assert entry["state"] == "uploaded" and entry["new_version"] is False
    assert entry["md5"] == _md5(p.read_bytes())
    assert entry["size"] == p.stat().st_size
    assert drive.items[entry["id"]]["parents"] == [root]


def test_the_real_media_is_resumable_and_chunked(tmp_path):
    """本物の MediaFileUpload を作るだけ（送らない）。分割の大きさは 256KB の倍数。"""
    pytest.importorskip("googleapiclient")
    p = tmp_path / "a.bin"
    p.write_bytes(b"x" * 10)
    media = asset_store._media(p, True)
    assert media.resumable() is True
    assert media.chunksize() == asset_store.CHUNK_BYTES
    assert asset_store.CHUNK_BYTES % (256 * 1024) == 0


def test_put_skips_a_file_already_there_with_the_same_md5(drive, tmp_path):
    root = asset_store.ensure_root(drive)
    p = tmp_path / "run.json"
    p.write_text('{"ok": true}', encoding="utf-8")
    first = asset_store.put(drive, p, root)
    creates = drive.creates

    again = asset_store.put(drive, p, root)

    assert again["state"] == "already" and again["id"] == first["id"]
    assert drive.creates == creates and drive.updates == 0


def test_a_mismatch_after_upload_is_an_error_not_a_success(drive, tmp_path):
    root = asset_store.ensure_root(drive)
    p = tmp_path / "broken.bin"
    p.write_bytes(b"0123456789")
    drive.corrupt.add("broken.bin")

    with pytest.raises(asset_store.UploadError) as exc:
        asset_store.put(drive, p, root)
    assert "成功ではありません" in str(exc.value)


def test_same_name_different_md5_becomes_a_new_version(drive, tmp_path):
    """別のファイルを増やさず、既存のファイルの中身を差し替える。"""
    root = asset_store.ensure_root(drive)
    p = tmp_path / "notes.txt"
    p.write_text("v1", encoding="utf-8")
    first = asset_store.put(drive, p, root)
    p.write_text("v2 — 直した", encoding="utf-8")

    second = asset_store.put(drive, p, root)

    assert second["state"] == "uploaded" and second["new_version"] is True
    assert second["id"] == first["id"]
    assert drive.updates == 1
    assert len(drive.named("notes.txt", root)) == 1
    assert drive.items[first["id"]]["md5Checksum"] == _md5("v2 — 直した".encode())


def test_a_broken_upload_is_repaired_by_putting_again(drive, tmp_path):
    root = asset_store.ensure_root(drive)
    p = tmp_path / "x.bin"
    p.write_bytes(b"abcdef")
    drive.corrupt.add("x.bin")
    with pytest.raises(asset_store.UploadError):
        asset_store.put(drive, p, root)
    drive.corrupt.clear()

    entry = asset_store.put(drive, p, root)

    assert entry["state"] == "uploaded" and entry["new_version"] is True


def test_a_mismatch_on_the_new_version_is_also_an_error(drive, tmp_path):
    root = asset_store.ensure_root(drive)
    p = tmp_path / "y.bin"
    p.write_bytes(b"one")
    asset_store.put(drive, p, root)
    p.write_bytes(b"two!")
    drive.corrupt.add("y.bin")
    with pytest.raises(asset_store.UploadError):
        asset_store.put(drive, p, root)


def test_two_files_with_the_same_name_stop_without_sending(drive, tmp_path):
    root = asset_store.ensure_root(drive)
    for i in (1, 2):
        drive.items[f"d{i}"] = {"id": f"d{i}", "name": "dup.txt", "mimeType": "text/plain",
                                "parents": [root], "md5Checksum": f"{i}" * 32, "size": "1"}
    p = tmp_path / "dup.txt"
    p.write_text("new", encoding="utf-8")
    with pytest.raises(asset_store.UploadError):
        asset_store.put(drive, p, root)
    assert drive.updates == 0


def test_an_empty_file_is_sent_in_one_request(drive, tmp_path):
    root = asset_store.ensure_root(drive)
    p = tmp_path / "empty.log"
    p.write_bytes(b"")
    entry = asset_store.put(drive, p, root)
    assert entry["state"] == "uploaded" and entry["size"] == 0


# --- 5. ディレクトリの送信とマニフェスト -----------------------------------------------


def _tree(base):
    (base / "captions").mkdir(parents=True)
    (base / "ai" / "council").mkdir(parents=True)
    (base / "empty").mkdir()
    (base / "run.json").write_text('{"model": "standard"}', encoding="utf-8")
    (base / "captions" / "final.srt").write_text("1\n字幕\n", encoding="utf-8")
    (base / "ai" / "council" / "notes.md").write_text("提案", encoding="utf-8")
    return base


def test_put_tree_keeps_relative_paths_and_returns_a_manifest(drive, tmp_path):
    local = _tree(tmp_path / "job1")
    logs = []

    manifest = asset_store.put_tree(drive, local, "jobs/job1", log=logs.append)

    assert [e["path"] for e in manifest] == [
        "ai/council/notes.md", "captions/final.srt", "run.json"]
    for e in manifest:
        assert e["state"] == "uploaded"
        assert e["md5"] == _md5((local / e["path"]).read_bytes())
        assert e["size"] == (local / e["path"]).stat().st_size
        assert set(e) >= {"path", "id", "md5", "size", "state"}
    root = asset_store.ensure_root(drive)
    job1 = asset_store.find_path(drive, root, "jobs/job1")
    council = asset_store.find_path(drive, root, "jobs/job1/ai/council")
    assert drive.items[manifest[0]["id"]]["parents"] == [council]
    assert asset_store.find_path(drive, root, "jobs/job1/empty") is not None  # 空のフォルダも作る
    assert drive.items[manifest[2]["id"]]["parents"] == [job1]
    # 送る前に件数と合計を出す
    assert logs[0].startswith("送る: 3 件・合計")


def test_put_tree_twice_sends_nothing_new(drive, tmp_path):
    local = _tree(tmp_path / "job1")
    asset_store.put_tree(drive, local, "jobs/job1", log=lambda _: None)
    creates = drive.creates

    again = asset_store.put_tree(drive, local, "jobs/job1", log=lambda _: None)

    assert {e["state"] for e in again} == {"already"}
    assert drive.creates == creates and drive.updates == 0


def test_put_tree_names_what_it_does_not_send(drive, tmp_path):
    local = _tree(tmp_path / "job1")
    (tmp_path / "elsewhere").mkdir()
    (local / "linked").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    logs = []

    asset_store.put_tree(drive, local, "jobs/job1", log=logs.append)

    assert any("送らない" in line and "linked" in line for line in logs)


def test_put_tree_refuses_a_missing_directory(drive, tmp_path):
    with pytest.raises(asset_store.UploadError):
        asset_store.put_tree(drive, tmp_path / "absent", "x", log=lambda _: None)


def test_list_tree_reads_back_what_was_put(drive, tmp_path):
    local = _tree(tmp_path / "job1")
    manifest = asset_store.put_tree(drive, local, "jobs/job1", log=lambda _: None)

    listed = asset_store.list_tree(drive, "jobs/job1")

    assert sorted((e["path"], e["md5"]) for e in listed) == sorted(
        (e["path"], e["md5"]) for e in manifest)
    with pytest.raises(asset_store.PathError):
        asset_store.list_tree(drive, "jobs/nope")


# --- 6. CLI put / list（Drive は偽物） ------------------------------------------------


def test_cli_put_writes_the_manifest_to_stdout(drive, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(asset_store, "_build_drive", lambda: drive)
    local = _tree(tmp_path / "job1")

    assert asset_store.main(["put", str(local), "--to", "jobs/job1"]) == 0

    captured = capsys.readouterr()
    doc = json.loads(captured.out)
    assert doc["root"] == "AVS 過程の資産" and doc["dest"] == "jobs/job1"
    assert len(doc["files"]) == 3
    assert "送る: 3 件" in captured.err


def test_cli_put_writes_the_manifest_to_a_file(drive, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(asset_store, "_build_drive", lambda: drive)
    local = _tree(tmp_path / "job1")
    out = tmp_path / "manifest.json"

    assert asset_store.main(["put", str(local), "--to", "jobs/job1", "--manifest", str(out)]) == 0

    assert len(json.loads(out.read_text(encoding="utf-8"))["files"]) == 3
    assert capsys.readouterr().out == ""


def test_cli_put_reports_a_mismatch_and_writes_no_manifest(drive, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(asset_store, "_build_drive", lambda: drive)
    local = _tree(tmp_path / "job1")
    drive.corrupt.add("run.json")
    out = tmp_path / "manifest.json"

    assert asset_store.main(["put", str(local), "--to", "jobs/job1", "--manifest", str(out)]) == 1

    assert not out.exists()
    assert "合いません" in capsys.readouterr().err


def test_cli_list_prints_the_files(drive, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(asset_store, "_build_drive", lambda: drive)
    asset_store.put_tree(drive, _tree(tmp_path / "job1"), "jobs/job1", log=lambda _: None)

    assert asset_store.main(["list", "jobs/job1"]) == 0
    out = capsys.readouterr().out
    assert "captions/final.srt" in out and "3 件" in out

    assert asset_store.main(["list", "jobs/nope"]) == 1
