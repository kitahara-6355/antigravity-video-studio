"""scripts/google_oauth_login.py の `--readonly` / `--assets` / `--token`（M2）。

同意画面は開かない。スコープと保存先の決め方、保存形式だけを見る。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "google_oauth_login.py"


@pytest.fixture(scope="module")
def login():
    spec = importlib.util.spec_from_file_location("google_oauth_login", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["google_oauth_login"] = module
    spec.loader.exec_module(module)
    return module


def test_readonly_requests_only_drive_readonly(login):
    """読み取り専用の口に、読み書きのスコープを混ぜない。"""
    scopes, _ = login.resolve_plan(readonly=True, token=None)
    assert scopes == ["https://www.googleapis.com/auth/drive.readonly"]


def test_readonly_has_its_own_default_file(login, monkeypatch, tmp_path):
    """通常のトークン（読み書き）を上書きしない。"""
    monkeypatch.setenv("ANTIGRAVITY_GOOGLE_TOKEN", str(tmp_path / "token.json"))
    _, out = login.resolve_plan(readonly=True, token=None)
    assert out == tmp_path / "token_raw_readonly.json"


def test_token_flag_overrides_the_destination(login, tmp_path):
    target = tmp_path / "x" / "t.json"
    assert login.resolve_plan(readonly=True, token=target)[1] == target
    assert login.resolve_plan(readonly=False, token=target)[1] == target


def test_default_mode_is_unchanged(login, monkeypatch, tmp_path):
    """既存の使い方（引数なし）は従来どおり drive + sheets を token.json に。"""
    monkeypatch.setenv("ANTIGRAVITY_GOOGLE_TOKEN", str(tmp_path / "token.json"))
    scopes, out = login.resolve_plan(readonly=False, token=None)
    assert scopes == login.SCOPES
    assert out == tmp_path / "token.json"


def test_readonly_token_is_saved_on_one_line(login):
    """環境変数に貼るので1行。中身は損なわない。"""
    src = json.dumps({"token": "at", "refresh_token": "rt", "scopes": ["s"]}, indent=4)
    one = login.serialize_token(src, one_line=True)
    assert "\n" not in one
    assert json.loads(one) == json.loads(src)
    assert "\n" in login.serialize_token(src, one_line=False)


def test_args_are_parsed(login, tmp_path):
    args = login._parse_args(["--readonly", "--token", str(tmp_path / "t.json")])
    assert args.readonly is True
    assert args.token == tmp_path / "t.json"
    assert login._parse_args([]).readonly is False


# --- --assets（過程の資産を書く口・drive.file） ------------------------------------


def test_assets_requests_only_drive_file(login):
    scopes, _ = login.resolve_plan(readonly=False, token=None, assets=True)
    assert scopes == ["https://www.googleapis.com/auth/drive.file"]


def test_assets_has_its_own_default_file(login, monkeypatch, tmp_path):
    """読み取り用・通常のトークンを上書きしない。"""
    monkeypatch.setenv("ANTIGRAVITY_GOOGLE_TOKEN", str(tmp_path / "token.json"))
    _, out = login.resolve_plan(readonly=False, token=None, assets=True)
    assert out == tmp_path / "token_assets_file.json"
    assert out != login.resolve_plan(readonly=True, token=None)[1]


def test_token_flag_overrides_the_assets_destination(login, tmp_path):
    target = tmp_path / "a.json"
    assert login.resolve_plan(readonly=False, token=target, assets=True)[1] == target


def test_readonly_and_assets_cannot_be_combined(login, capsys):
    """1本のトークンに読みと書きを混ぜない。"""
    with pytest.raises(SystemExit):
        login._parse_args(["--readonly", "--assets"])
    assert "--assets" in capsys.readouterr().err
    with pytest.raises(ValueError):
        login.resolve_plan(readonly=True, token=None, assets=True)


def test_assets_flag_is_parsed(login):
    assert login._parse_args(["--assets"]).assets is True
    assert login._parse_args([]).assets is False


def test_assets_token_is_saved_on_one_line_and_names_its_env(login, monkeypatch, tmp_path, capsys):
    """同意の流れを偽物にして、保存の形と案内だけを見る（ブラウザも Google も使わない）。"""
    import types

    secret = tmp_path / "client_secret.json"
    secret.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ANTIGRAVITY_GOOGLE_CLIENT_SECRET", str(secret))
    monkeypatch.setenv("ANTIGRAVITY_GOOGLE_TOKEN", str(tmp_path / "token.json"))
    asked = {}

    class _Flow:
        @classmethod
        def from_client_secrets_file(cls, path, scopes):
            asked["scopes"] = scopes
            return cls()

        def run_local_server(self, port):
            return types.SimpleNamespace(to_json=lambda: json.dumps(
                {"refresh_token": "SECRET-RT", "scopes": asked["scopes"]}, indent=2))

    fake = types.ModuleType("google_auth_oauthlib.flow")
    fake.InstalledAppFlow = _Flow
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib.flow", fake)

    assert login.main(["--assets"]) == 0

    out = tmp_path / "token_assets_file.json"
    text = out.read_text(encoding="utf-8")
    assert "\n" not in text
    assert json.loads(text)["scopes"] == ["https://www.googleapis.com/auth/drive.file"]
    printed = capsys.readouterr().out
    assert "AVS_ASSETS_GOOGLE_TOKEN_JSON" in printed
    assert "SECRET-RT" not in printed
