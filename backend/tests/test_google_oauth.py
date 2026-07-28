"""backend/services/google_oauth.py のテスト。

実際の Google には一切接続しない。接続しようとしたら失敗する、という
性質そのものをテストしている（黙ってスタブに落ちない）。
"""
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.services import google_oauth
from backend.services.google_oauth import (
    CredentialsNotFoundError,
    GoogleAuthError,
    client_secret_path,
    load_credentials,
    token_path,
)

# ---- 保存先の解決 ----

def test_token_path_uses_path_resolver(monkeypatch, tmp_path):
    """トークンの保存先は ANTIGRAVITY_BASE_DIR に追随する（直書きしない）。"""
    monkeypatch.setenv("ANTIGRAVITY_BASE_DIR", str(tmp_path))
    assert token_path().is_relative_to(tmp_path)


def test_token_path_env_override(monkeypatch, tmp_path):
    """明示指定が最優先。"""
    target = tmp_path / "somewhere" / "tok.json"
    monkeypatch.setenv("ANTIGRAVITY_GOOGLE_TOKEN", str(target))
    assert token_path() == target


def test_client_secret_path_env_override(monkeypatch, tmp_path):
    target = tmp_path / "cs.json"
    monkeypatch.setenv("ANTIGRAVITY_GOOGLE_CLIENT_SECRET", str(target))
    assert client_secret_path() == target


def test_old_env_name_still_accepted(monkeypatch, tmp_path):
    """旧名も受ける。片方に寄せると既存の差し替えが黙って効かなくなる。"""
    monkeypatch.delenv("ANTIGRAVITY_GOOGLE_TOKEN", raising=False)
    monkeypatch.setenv("ANTIGRAVITY_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("VIDEO_AUTOMATION_BASE_DIR", str(tmp_path / "old"))
    # 新名が優先されるので tmp_path 側
    assert token_path().is_relative_to(tmp_path)


# ---- 認証情報が無いとき ----

def test_load_credentials_raises_when_token_missing(monkeypatch, tmp_path):
    """トークンが無ければ例外。スタブを返してはいけない。"""
    monkeypatch.setenv("ANTIGRAVITY_GOOGLE_TOKEN", str(tmp_path / "absent.json"))
    with pytest.raises(CredentialsNotFoundError) as exc:
        load_credentials(["https://www.googleapis.com/auth/drive"])
    # 何をすればよいかがメッセージに出ている
    assert "ANTIGRAVITY_GOOGLE_TOKEN" in str(exc.value) or "認証" in str(exc.value)


def test_credentials_not_found_is_a_google_auth_error():
    """呼び出し側が GoogleAuthError だけ捕まえれば済むようにする。"""
    assert issubclass(CredentialsNotFoundError, GoogleAuthError)


def test_load_credentials_raises_on_broken_json(monkeypatch, tmp_path):
    tok = tmp_path / "tok.json"
    tok.write_text("{ this is not json", encoding="utf-8")
    monkeypatch.setenv("ANTIGRAVITY_GOOGLE_TOKEN", str(tok))
    with pytest.raises(GoogleAuthError):
        load_credentials(["https://www.googleapis.com/auth/drive"])


# ---- 正常系（Google には接続しない） ----

def _write_token(tmp_path):
    tok = tmp_path / "tok.json"
    tok.write_text(json.dumps({
        "token": "at",
        "refresh_token": "rt",
        "client_id": "cid",
        "client_secret": "cs",
        "scopes": ["https://www.googleapis.com/auth/drive"],
    }), encoding="utf-8")
    return tok


def test_load_credentials_returns_credentials(monkeypatch, tmp_path):
    tok = _write_token(tmp_path)
    monkeypatch.setenv("ANTIGRAVITY_GOOGLE_TOKEN", str(tok))

    fake = MagicMock(expired=False, valid=True)
    with patch.object(google_oauth, "_credentials_from_info", return_value=fake) as m:
        creds = load_credentials(["https://www.googleapis.com/auth/drive"])
    assert creds is fake
    # 要求したスコープが渡っている
    assert m.call_args[0][1] == ["https://www.googleapis.com/auth/drive"]


def test_expired_credentials_are_refreshed_and_saved(monkeypatch, tmp_path):
    """期限切れならリフレッシュし、更新後のトークンを書き戻す。"""
    tok = _write_token(tmp_path)
    monkeypatch.setenv("ANTIGRAVITY_GOOGLE_TOKEN", str(tok))

    fake = MagicMock(expired=True, valid=True, refresh_token="rt")
    fake.to_json.return_value = json.dumps({"token": "NEW", "refresh_token": "rt"})

    with patch.object(google_oauth, "_credentials_from_info", return_value=fake), \
         patch.object(google_oauth, "_transport_request", return_value=MagicMock()):
        load_credentials(["https://www.googleapis.com/auth/drive"])

    fake.refresh.assert_called_once()
    assert json.loads(tok.read_text(encoding="utf-8"))["token"] == "NEW"


def test_expired_without_refresh_token_raises(monkeypatch, tmp_path):
    """リフレッシュできないなら例外。黙って期限切れのまま返さない。"""
    tok = _write_token(tmp_path)
    monkeypatch.setenv("ANTIGRAVITY_GOOGLE_TOKEN", str(tok))

    fake = MagicMock(expired=True, valid=False, refresh_token=None)
    with patch.object(google_oauth, "_credentials_from_info", return_value=fake), \
         pytest.raises(GoogleAuthError):
        load_credentials(["https://www.googleapis.com/auth/drive"])


def test_token_file_is_written_with_owner_only_permissions(monkeypatch, tmp_path):
    """トークンは秘密。保存時にパーミッションを絞る（POSIX のみ検証）。"""
    tok = _write_token(tmp_path)
    monkeypatch.setenv("ANTIGRAVITY_GOOGLE_TOKEN", str(tok))

    fake = MagicMock(expired=True, valid=True, refresh_token="rt")
    fake.to_json.return_value = json.dumps({"token": "NEW"})
    with patch.object(google_oauth, "_credentials_from_info", return_value=fake), \
         patch.object(google_oauth, "_transport_request", return_value=MagicMock()):
        load_credentials(["https://www.googleapis.com/auth/drive"])

    if os.name == "posix":
        assert (tok.stat().st_mode & 0o077) == 0


# ---- スコープ ----

def test_scopes_are_explicit_constants():
    """スコープは定数。呼び出し側で文字列を直書きさせない。"""
    assert google_oauth.DRIVE_SCOPES
    assert google_oauth.SHEETS_SCOPES
    for s in list(google_oauth.DRIVE_SCOPES) + list(google_oauth.SHEETS_SCOPES):
        assert s.startswith("https://www.googleapis.com/auth/")


def test_drive_scope_allows_reading_preexisting_files():
    """drive.file は「アプリが作ったファイル」しか見えない。
    手で置いた素材を読む用途なので、それでは足りない。"""
    assert not any(s.endswith("/drive.file") for s in google_oauth.DRIVE_SCOPES)
