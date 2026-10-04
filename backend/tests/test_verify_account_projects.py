"""`verify_account --projects` — 台帳と環境変数の突き合わせ（M0・R2.5-C5 の verify）。

CLAUDE.md「API プロジェクトとキーの管理」の未実装項目。守りたい性質:

1. **台帳にキー本体が無い**（末尾4文字だけ）
2. 食い違いは **FAIL** で出る — 台帳にないキー／請求先の想定違い／旧式の変数名／
   クラウドに置いてはいけないキー／保管のトークンが揃っていない
3. 揃っていれば exit 0。**ダミーキーは合格ではない**
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from backend import verify_account
from backend.verify_account import check_projects, key_suffix

LEDGER = Path(__file__).resolve().parents[1] / "config" / "api_projects.json"


def _ledger() -> dict:
    return {
        "cloud_allowed_env": ["GOOGLE_API_KEY", "R2_ACCOUNT_ID",
                              "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
                              "R2_BUCKET"],
        "deprecated_env": ["GEMINI_API_KEY"],
        "projects": [
            {"id": "avs-prod-free", "billing": False, "env": "GOOGLE_API_KEY",
             "key_suffix": "AbCd", "status": "active"},
            {"id": "avs-prod-paid", "billing": True, "env": "GOOGLE_API_KEY_PRO",
             "key_suffix": "PaId", "status": "planned"},
            {"id": "avs-dev-free", "billing": False, "env": "GOOGLE_API_KEY",
             "key_suffix": None, "status": "planned"},
        ],
        "storage": [
            {"id": "avs-raw", "env": ["R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID",
                                      "R2_SECRET_ACCESS_KEY", "R2_BUCKET"],
             "suffix_env": "R2_ACCESS_KEY_ID", "key_suffix": "r2Ok",
             "status": "planned"},
        ],
    }


def _fails(findings) -> list[str]:
    return [text for level, text in findings if level == "FAIL"]


GOOD = {"GOOGLE_API_KEY": "AIzaSyLOOKS_REAL_ENOUGH_000AbCd"}


# --- 1. 台帳にキー本体が無い --------------------------------------------------


def test_the_real_ledger_holds_no_key_body():
    text = LEDGER.read_text(encoding="utf-8")
    ledger = json.loads(text)

    assert not re.search(r"AIza[0-9A-Za-z_\-]{20,}", text), "キー本体が台帳にある"
    for row in ledger["projects"] + ledger["storage"]:
        suffix = row["key_suffix"]
        assert suffix is None or (isinstance(suffix, str) and len(suffix) == 4), row


def test_the_real_ledger_names_the_three_projects_and_the_raw_bucket():
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    ids = {p["id"] for p in ledger["projects"]}

    assert {"avs-prod-free", "avs-prod-paid", "avs-dev-free"} <= ids
    raw = ledger["storage"][0]
    assert raw["id"] == "avs-raw"
    assert raw["provider"] == "google_drive" and raw["read_only"] is True
    assert "GOOGLE_API_KEY_PRO" not in ledger["cloud_allowed_env"]


def test_key_suffix_is_the_last_four_characters_only():
    assert key_suffix("AIzaSyLOOKS_REAL_ENOUGH_000AbCd") == "AbCd"
    assert key_suffix("abc") == "abc"


# --- 2. 食い違いは FAIL ---------------------------------------------------------


def test_a_matching_key_passes_and_names_the_project():
    findings = check_projects(GOOD, _ledger(), cloud=False)

    assert _fails(findings) == []
    assert any("avs-prod-free" in t for _, t in findings)


def test_a_key_missing_from_the_ledger_fails():
    env = {"GOOGLE_API_KEY": "AIzaSyLOOKS_REAL_ENOUGH_000ZZZZ"}

    fails = _fails(check_projects(env, _ledger(), cloud=False))

    assert any("台帳にない" in t and "ZZZZ" in t for t in fails)


def test_a_paid_key_in_the_free_slot_fails():
    """**請求先の想定違い。** 課金するキーを無料枠の口に入れると Tier 1 で回る。"""
    ledger = _ledger()
    ledger["projects"][0]["billing"] = True  # avs-prod-free に請求先が付いてしまった

    fails = _fails(check_projects(GOOD, ledger, cloud=False))

    assert any("請求先" in t for t in fails)


def test_the_old_variable_name_fails():
    env = dict(GOOD, GEMINI_API_KEY="AIzaSyOLD_NAME_000000000000AbCd")

    fails = _fails(check_projects(env, _ledger(), cloud=False))

    assert any("GEMINI_API_KEY" in t and "旧" in t for t in fails)


def test_the_active_project_key_must_be_set():
    fails = _fails(check_projects({}, _ledger(), cloud=False))

    assert any("GOOGLE_API_KEY" in t and "未設定" in t for t in fails)


def test_a_dummy_key_is_not_a_pass():
    fails = _fails(check_projects({"GOOGLE_API_KEY": "dummy_key_for_ci"},
                                  _ledger(), cloud=False))

    assert any("ダミー" in t for t in fails)


def test_the_pro_key_must_not_be_in_the_cloud():
    """クラウドの Secrets は avs-prod-free だけ（2026-09-26 ユーザー決定）。"""
    env = dict(GOOD, GOOGLE_API_KEY_PRO="AIzaSyPAID_KEY_00000000000PaId")

    local = _fails(check_projects(env, _ledger(), cloud=False))
    cloud = _fails(check_projects(env, _ledger(), cloud=True))

    assert local == []
    assert any("GOOGLE_API_KEY_PRO" in t and "クラウド" in t for t in cloud)


def test_a_partial_storage_token_fails():
    env = dict(GOOD, R2_ACCOUNT_ID="acct", R2_BUCKET="avs-raw")

    fails = _fails(check_projects(env, _ledger(), cloud=False))

    assert any("R2_ACCESS_KEY_ID" in t and "揃って" in t for t in fails)


def test_a_complete_storage_token_is_checked_by_suffix():
    env = dict(GOOD, R2_ACCOUNT_ID="acct", R2_ACCESS_KEY_ID="0123456789r2Ok",
               R2_SECRET_ACCESS_KEY="s", R2_BUCKET="avs-raw")
    assert _fails(check_projects(env, _ledger(), cloud=False)) == []

    env["R2_ACCESS_KEY_ID"] = "0123456789BAD1"
    fails = _fails(check_projects(env, _ledger(), cloud=False))
    assert any("avs-raw" in t and "BAD1" in t for t in fails)


def test_no_storage_token_is_only_informational():
    findings = check_projects(GOOD, _ledger(), cloud=False)

    assert _fails(findings) == []
    assert any(level == "INFO" and "avs-raw" in t for level, t in findings)


# --- 3. CLI ----------------------------------------------------------------------


def _clean_env(monkeypatch):
    for name in ("GOOGLE_API_KEY", "GOOGLE_API_KEY_PRO", "GEMINI_API_KEY",
                 "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
                 "R2_BUCKET", "CCR_SESSION_PROFILE"):
        monkeypatch.delenv(name, raising=False)


def test_projects_mode_exits_zero_when_everything_matches(monkeypatch, capsys):
    _clean_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", GOOD["GOOGLE_API_KEY"])
    monkeypatch.setattr(verify_account, "load_ledger", lambda: _ledger())

    code = verify_account.main(["--projects"])
    out = capsys.readouterr().out

    assert code == 0
    assert "avs-prod-free" in out


def test_projects_mode_exits_one_on_a_mismatch(monkeypatch, capsys):
    _clean_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", "AIzaSyLOOKS_REAL_ENOUGH_000ZZZZ")
    monkeypatch.setattr(verify_account, "load_ledger", lambda: _ledger())

    code = verify_account.main(["--projects"])

    assert code == 1
    assert "FAIL" in capsys.readouterr().out


def test_projects_mode_detects_the_cloud_session(monkeypatch, capsys):
    _clean_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", GOOD["GOOGLE_API_KEY"])
    monkeypatch.setenv("GOOGLE_API_KEY_PRO", "AIzaSyPAID_KEY_00000000000PaId")
    monkeypatch.setenv("CCR_SESSION_PROFILE", "default")
    monkeypatch.setattr(verify_account, "load_ledger", lambda: _ledger())

    code = verify_account.main(["--projects"])

    assert code == 1
    assert "クラウド" in capsys.readouterr().out


def test_an_empty_cloud_marker_still_counts_as_the_cloud(monkeypatch):
    """実測: クラウドのセッションでは `CCR_SESSION_PROFILE` が**空文字で**存在する。"""
    assert verify_account.is_cloud_session({"CCR_SESSION_PROFILE": ""})
    assert not verify_account.is_cloud_session({})


def test_projects_mode_never_prints_a_key_body(monkeypatch, capsys):
    _clean_env(monkeypatch)
    secret = "AIzaSyLOOKS_REAL_ENOUGH_000AbCd"
    monkeypatch.setenv("GOOGLE_API_KEY", secret)
    monkeypatch.setattr(verify_account, "load_ledger", lambda: _ledger())

    verify_account.main(["--projects"])

    assert secret not in capsys.readouterr().out


@pytest.mark.parametrize("flag", ["--projects"])
def test_projects_mode_does_not_call_the_api(monkeypatch, flag):
    """突き合わせは環境変数と台帳だけで済む。**外に出ない。**"""
    _clean_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", GOOD["GOOGLE_API_KEY"])
    monkeypatch.setattr(verify_account, "load_ledger", lambda: _ledger())
    monkeypatch.setattr(verify_account.model_policy, "live_model_ids",
                        lambda: (_ for _ in ()).throw(AssertionError("API を叩いた")))

    assert verify_account.main([flag]) == 0


# --- 4. raw の Drive トークンは読み取り専用（M2） -----------------------------------

_READONLY = "https://www.googleapis.com/auth/drive.readonly"


def _drive_ledger() -> dict:
    ledger = _ledger()
    ledger["storage"] = [{
        "id": "avs-raw", "provider": "google_drive",
        "env": ["ANTIGRAVITY_GOOGLE_TOKEN_JSON", "AVS_RAW_DRIVE_FOLDER_ID"],
        "token_env": "ANTIGRAVITY_GOOGLE_TOKEN_JSON",
        "suffix_env": "AVS_RAW_DRIVE_FOLDER_ID", "key_suffix": "2h-z",
        "oauth_scope": _READONLY, "read_only": True, "status": "planned",
    }]
    return ledger


def _drive_env(token) -> dict:
    value = token if isinstance(token, str) else json.dumps(token)
    return dict(GOOD, ANTIGRAVITY_GOOGLE_TOKEN_JSON=value,
                AVS_RAW_DRIVE_FOLDER_ID="1AbCdEfGh2h-z")


def test_a_readonly_drive_token_passes():
    env = _drive_env({"refresh_token": "SECRET-RT", "scopes": [_READONLY]})
    findings = check_projects(env, _drive_ledger(), cloud=True)

    assert _fails(findings) == []
    assert any(level == "OK" and "avs-raw" in t for level, t in findings)


@pytest.mark.parametrize("scopes", [
    ["https://www.googleapis.com/auth/drive"],
    [_READONLY, "https://www.googleapis.com/auth/spreadsheets"],
    [],
])
def test_a_drive_token_that_is_not_readonly_fails(scopes):
    env = _drive_env({"refresh_token": "SECRET-RT", "scopes": scopes})
    fails = _fails(check_projects(env, _drive_ledger(), cloud=True))

    assert any("avs-raw" in t and "権限" in t for t in fails)
    assert not any("SECRET-RT" in t for t in fails)


def test_a_broken_drive_token_fails_without_echoing_it():
    env = _drive_env('{"refresh_token": "SECRET-RT", oops')
    fails = _fails(check_projects(env, _drive_ledger(), cloud=True))

    assert any("JSON" in t for t in fails)
    assert not any("SECRET-RT" in t for t in fails)


def test_the_real_ledger_checks_the_drive_token_scope():
    """実台帳の raw 行が、スコープの点検の対象になっている。"""
    row = next(r for r in json.loads(LEDGER.read_text(encoding="utf-8"))["storage"]
               if r["id"] == "avs-raw")
    assert row["token_env"] in row["env"]
    assert row["oauth_scope"] == _READONLY
