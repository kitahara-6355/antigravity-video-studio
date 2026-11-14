"""backend/gas_deploy.py（Apps Script をクラウドから送り込む・2026-11-13）。外には出ない。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend import gas_deploy as gd

S1 = "https://www.googleapis.com/auth/drive"
S2 = "https://mail.google.com/"


def _manifest(scopes):
    return json.dumps({"timeZone": "Asia/Tokyo", "oauthScopes": scopes})


def _src(tmp_path: Path, scopes=(S1,), extra=None) -> Path:
    src = tmp_path / "gas"
    src.mkdir()
    (src / "appsscript.json").write_text(_manifest(list(scopes)), encoding="utf-8")
    (src / "Code.js").write_text("function a(){}", encoding="utf-8")
    (src / "Index.html").write_text("<p>hi</p>", encoding="utf-8")
    for name, body in (extra or {}).items():
        p = src / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return src


class FakeClient:
    def __init__(self, remote):
        self.remote = remote
        self.calls = []

    def get_content(self, sid):
        self.calls.append(("get", sid))
        return self.remote

    def put_content(self, sid, files):
        self.calls.append(("put", sid, [f["name"] for f in files]))

    def create_version(self, sid, desc):
        self.calls.append(("version", sid, desc))
        return 7

    def update_deployment(self, sid, did, version, desc):
        self.calls.append(("deploy", sid, did, version))


def _remote(scopes=(S1,), code="function old(){}", extra=()):
    files = [{"name": "appsscript", "type": "JSON", "source": _manifest(list(scopes))},
             {"name": "Code", "type": "SERVER_JS", "source": code},
             {"name": "Index", "type": "HTML", "source": "<p>hi</p>"}]
    return files + list(extra)


def _entry(src, **kw):
    e = {"name": "t", "scriptId": "SID", "source": str(src), "account": "info@kitahara-birei.com"}
    e.update(kw)
    return e


def test_collect_maps_types_like_clasp(tmp_path):
    src = _src(tmp_path, extra={"sub/b.gs": "x", "README.md": "no", ".hidden.js": "no",
                                "node_modules/m.js": "no"})
    got = {(f["name"], f["type"]) for f in gd.collect_files(src)}
    assert got == {("appsscript", "JSON"), ("Code", "SERVER_JS"), ("Index", "HTML"),
                   ("sub/b", "SERVER_JS")}


def test_claspignore_with_negation_sends_only_listed(tmp_path):
    """caption-review の .claspignore（全部無視して ! で戻す）と同じ動き。"""
    src = _src(tmp_path, extra={"build.js": "x",
                                ".claspignore": "**/**\n!appsscript.json\n!Code.js\n!Index.html\n"})
    assert {f["name"] for f in gd.collect_files(src)} == {"appsscript", "Code", "Index"}


def test_include_overrides_everything(tmp_path):
    src = _src(tmp_path, extra={"まとめて貼る用.gs": "dup"})
    names = {f["name"] for f in gd.collect_files(src, ["Code.js", "appsscript.json"])}
    assert names == {"appsscript", "Code"}


def test_missing_manifest_is_refused(tmp_path):
    (tmp_path / "a.js").write_text("x")
    with pytest.raises(gd.GuardError):
        gd.collect_files(tmp_path)


def test_plan_lists_changes_and_new_scopes(tmp_path):
    local = gd.collect_files(_src(tmp_path, scopes=(S1, S2)))
    plan = gd.plan_push(local, _remote(extra=[{"name": "Old", "type": "SERVER_JS", "source": ""}]))
    assert plan.changed == ["Code.js", "appsscript.json"]
    assert plan.removed == ["Old.js"]
    assert plan.new_scopes == [S2]


def test_new_scope_stops_before_anything_changes(tmp_path):
    client = FakeClient(_remote())
    with pytest.raises(gd.GuardError, match="新しい権限"):
        gd.push(client, _entry(_src(tmp_path, scopes=(S1, S2))), backup_dir=tmp_path / "bk",
                say=lambda _: None)
    assert [c[0] for c in client.calls] == ["get"]


def test_removed_file_stops_unless_allowed(tmp_path):
    remote = _remote(extra=[{"name": "Backfill", "type": "SERVER_JS", "source": "x"}])
    with pytest.raises(gd.GuardError, match="消えます"):
        gd.push(FakeClient(remote), _entry(_src(tmp_path)), backup_dir=tmp_path / "bk",
                say=lambda _: None)
    assert gd.push(FakeClient(remote), _entry(tmp_path / "gas"), allow_remove=True,
                   backup_dir=tmp_path / "bk", label="git x", say=lambda _: None) == 7


def test_push_backs_up_then_versions_with_label(tmp_path):
    client = FakeClient(_remote())
    v = gd.push(client, _entry(_src(tmp_path)), backup_dir=tmp_path / "bk", label="git abc",
                say=lambda _: None)
    assert v == 7
    assert [c[0] for c in client.calls] == ["get", "put", "version"]
    assert "git abc" in client.calls[2][2]
    saved = list((tmp_path / "bk" / "SID").glob("*.json"))
    assert len(saved) == 1 and json.loads(saved[0].read_text())["files"][1]["source"] == "function old(){}"


def test_dry_run_and_no_change_send_nothing(tmp_path):
    src = _src(tmp_path)
    client = FakeClient(_remote())
    assert gd.push(client, _entry(src), dry_run=True, say=lambda _: None) is None
    same = FakeClient(gd.collect_files(src))
    assert gd.push(same, _entry(src), say=lambda _: None) is None
    assert [c[0] for c in client.calls + same.calls] == ["get", "get"]


def test_deploy_moves_the_same_deployment(tmp_path):
    client = FakeClient(_remote())
    gd.deploy(client, _entry(_src(tmp_path), deploymentId="DID"), backup_dir=tmp_path / "bk",
              label="git abc", say=lambda _: None)
    assert client.calls[-1] == ("deploy", "SID", "DID", 7)


def test_deploy_without_deployment_id_is_refused(tmp_path):
    with pytest.raises(gd.GuardError):
        gd.deploy(FakeClient(_remote()), _entry(_src(tmp_path)), say=lambda _: None)


def test_scope_check_requires_both_script_scopes():
    gd.check_scope({"scopes": list(gd.SCRIPT_SCOPES)})
    with pytest.raises(gd.GoogleAuthError):
        gd.check_scope({"scopes": [gd.SCRIPT_SCOPES[0]]})


def test_check_reads_env_without_network(monkeypatch, capsys):
    monkeypatch.setenv(gd.SCRIPT_TOKEN_JSON_ENV, json.dumps({"scopes": list(gd.SCRIPT_SCOPES)}))
    assert gd.main(["check"]) == 0
    assert "OK" in capsys.readouterr().out


def test_registry_is_valid_and_personal_is_refused(capsys):
    reg = gd.load_registry()
    assert {"caption-review", "dream-interview", "office-automation"} <= set(reg)
    for e in reg.values():
        assert e["account"] in ("info@kitahara-birei.com", "personal")
        assert "token" not in json.dumps(e).lower()
    assert gd.main(["push", "rss-learning-log"]) == 2
