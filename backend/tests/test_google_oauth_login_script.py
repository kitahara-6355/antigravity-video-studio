"""scripts/google_oauth_login.py の `--readonly` / `--token`（M2）。

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
