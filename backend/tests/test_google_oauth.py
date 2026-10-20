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

@pytest.fixture(autouse=True)
def _no_real_token(monkeypatch):
    """実行環境に本物のトークンが入っていても読まない。

    クラウドのセッションには `ANTIGRAVITY_GOOGLE_TOKEN_JSON` が実際に入っている。
    残したままだとファイルより優先され、本物でリフレッシュしに外へ出る（2026-10-18 に踏んだ）。
    """
    monkeypatch.delenv(google_oauth.TOKEN_JSON_ENV, raising=False)
    monkeypatch.delenv(google_oauth.ASSETS_TOKEN_JSON_ENV, raising=False)


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


# ---- クラウド用: トークンの中身を環境変数で受ける（M2） ----

_TOKEN_INFO = {
    "token": "at",
    "refresh_token": "rt",
    "client_id": "cid",
    "client_secret": "cs",
    "scopes": ["https://www.googleapis.com/auth/drive.readonly"],
}


def test_drive_readonly_scope_is_read_only():
    """raw を読む口は drive.readonly だけ。書ける権限を混ぜない。"""
    assert google_oauth.DRIVE_READONLY_SCOPES == (
        "https://www.googleapis.com/auth/drive.readonly",
    )


def test_token_json_env_is_preferred_over_the_file(monkeypatch, tmp_path):
    """環境変数に中身があれば、ファイルより優先する（クラウドにはファイルが無い）。"""
    tok = _write_token(tmp_path)  # こちらは drive（読み書き）
    monkeypatch.setenv("ANTIGRAVITY_GOOGLE_TOKEN", str(tok))
    monkeypatch.setenv(google_oauth.TOKEN_JSON_ENV, json.dumps(_TOKEN_INFO))

    info, source, save_to = google_oauth.read_token_info()

    assert info["scopes"] == _TOKEN_INFO["scopes"]
    assert google_oauth.TOKEN_JSON_ENV in source
    assert save_to is None


def test_token_json_env_is_refreshed_but_never_written_anywhere(monkeypatch, tmp_path):
    """環境変数から読んだトークンは、リフレッシュしても書き戻さない。"""
    tok = tmp_path / "tok.json"
    monkeypatch.setenv("ANTIGRAVITY_GOOGLE_TOKEN", str(tok))
    monkeypatch.setenv(google_oauth.TOKEN_JSON_ENV, json.dumps(_TOKEN_INFO))

    fake = MagicMock(expired=True, valid=True, refresh_token="rt")
    with patch.object(google_oauth, "_credentials_from_info", return_value=fake), \
         patch.object(google_oauth, "_transport_request", return_value=MagicMock()), \
         patch.object(google_oauth, "_save_token") as save:
        load_credentials(google_oauth.DRIVE_READONLY_SCOPES)

    fake.refresh.assert_called_once()
    save.assert_not_called()
    assert not tok.exists()


def test_broken_token_json_env_raises_without_echoing_the_secret(monkeypatch):
    """壊れた中身は例外。メッセージに中身（秘密）を出さない。"""
    secret = '{"refresh_token": "SECRET-RT-123", oops'
    monkeypatch.setenv(google_oauth.TOKEN_JSON_ENV, secret)

    with pytest.raises(GoogleAuthError) as exc:
        load_credentials(google_oauth.DRIVE_READONLY_SCOPES)

    assert "SECRET-RT-123" not in str(exc.value)
    assert exc.value.__cause__ is None


def test_token_json_env_must_be_an_object(monkeypatch):
    monkeypatch.setenv(google_oauth.TOKEN_JSON_ENV, '["not", "an", "object"]')
    with pytest.raises(GoogleAuthError):
        google_oauth.read_token_info()


def test_empty_token_json_env_falls_back_to_the_file(monkeypatch, tmp_path):
    """空文字は未設定扱い（他の環境変数と同じ）。"""
    tok = _write_token(tmp_path)
    monkeypatch.setenv("ANTIGRAVITY_GOOGLE_TOKEN", str(tok))
    monkeypatch.setenv(google_oauth.TOKEN_JSON_ENV, "")

    _, source, save_to = google_oauth.read_token_info()

    assert save_to == tok
    assert source == str(tok)


@pytest.mark.parametrize("info, expected", [
    ({"scopes": ["a", "b"]}, {"a", "b"}),
    ({"scopes": "a b"}, {"a", "b"}),
    ({"scope": "a"}, {"a"}),
    ({}, set()),
])
def test_token_scopes_reads_list_or_space_separated(info, expected):
    assert google_oauth.token_scopes(info) == expected


# ---- 過程の資産を書く口（drive.file・2026-10-18） ----

_FILE_INFO = dict(_TOKEN_INFO, scopes=["https://www.googleapis.com/auth/drive.file"])


def test_drive_file_scope_is_only_drive_file():
    assert google_oauth.DRIVE_FILE_SCOPES == ("https://www.googleapis.com/auth/drive.file",)
    assert "DRIVE_FILE_SCOPES" in google_oauth.__all__
    assert "ASSETS_TOKEN_JSON_ENV" in google_oauth.__all__
    assert google_oauth.ASSETS_TOKEN_JSON_ENV == "AVS_ASSETS_GOOGLE_TOKEN_JSON"


def test_assets_token_file_sits_next_to_the_normal_token(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTIGRAVITY_GOOGLE_TOKEN", str(tmp_path / "token.json"))
    assert google_oauth.assets_token_path() == tmp_path / "token_assets_file.json"


def test_assets_env_is_read_only_when_asked(monkeypatch, tmp_path):
    """資産の口を指定したときだけ AVS_ASSETS_GOOGLE_TOKEN_JSON を読む。既定の口は従来どおり。"""
    monkeypatch.setenv(google_oauth.ASSETS_TOKEN_JSON_ENV, json.dumps(_FILE_INFO))
    monkeypatch.setenv(google_oauth.TOKEN_JSON_ENV, json.dumps(_TOKEN_INFO))

    info, source, save_to = google_oauth.read_token_info(
        google_oauth.ASSETS_TOKEN_JSON_ENV, tmp_path / "absent.json")
    assert info["scopes"] == _FILE_INFO["scopes"]
    assert google_oauth.ASSETS_TOKEN_JSON_ENV in source
    assert save_to is None

    default, _, _ = google_oauth.read_token_info()
    assert default["scopes"] == _TOKEN_INFO["scopes"]


def test_assets_port_never_falls_back_to_the_readonly_token(monkeypatch, tmp_path):
    """資産の口が空なら、読み取り用のトークンがあっても使わずに止まる。"""
    monkeypatch.setenv(google_oauth.TOKEN_JSON_ENV, json.dumps(_TOKEN_INFO))
    with pytest.raises(CredentialsNotFoundError) as exc:
        google_oauth.read_token_info(google_oauth.ASSETS_TOKEN_JSON_ENV, tmp_path / "absent.json")
    assert google_oauth.ASSETS_TOKEN_JSON_ENV in str(exc.value)


def test_assets_token_file_is_read_and_written_back(monkeypatch, tmp_path):
    """ローカルのファイルから読んだ資産のトークンは、リフレッシュ後にそのファイルへ書き戻す。"""
    tok = tmp_path / "token_assets_file.json"
    tok.write_text(json.dumps(_FILE_INFO), encoding="utf-8")
    fake = MagicMock(expired=True, valid=True, refresh_token="rt")
    fake.to_json.return_value = json.dumps({"token": "NEW"})
    with patch.object(google_oauth, "_credentials_from_info", return_value=fake) as m, \
         patch.object(google_oauth, "_transport_request", return_value=MagicMock()):
        google_oauth.load_credentials(google_oauth.DRIVE_FILE_SCOPES,
                                      json_env=google_oauth.ASSETS_TOKEN_JSON_ENV,
                                      token_file=tok)
    assert m.call_args[0][1] == google_oauth.DRIVE_FILE_SCOPES
    assert json.loads(tok.read_text(encoding="utf-8"))["token"] == "NEW"
