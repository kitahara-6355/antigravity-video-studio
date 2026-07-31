"""Google API のユーザー認証（OAuth）を一箇所に集約する。

## なぜサービスアカウントではないのか

素材の置き場は AI Pro 契約の**個人 Drive**（5TB）。サービスアカウントは
それ自身の容量枠を持たず、個人 Drive の枠も使えない。共有ドライブに逃がす
手もあるが、共有ドライブは Google Workspace の機能で AI Pro には無い。
したがって「ユーザー本人として動く」OAuth 以外の経路が無い。

旧 `workspace_sync.py` は `from_service_account_file` だけを見ており、
認証に失敗すると黙ってスタブへ落ちていた。その設計はここで打ち切る。

## 認証情報は2種類ある

| ファイル | 中身 | 作る人 |
|---|---|---|
| クライアント秘密 | GCP で発行する OAuth クライアント ID | ユーザー（GCP コンソール） |
| トークン | 同意後に得る access/refresh token | `scripts/google_oauth_login.py` |

どちらも秘密。`.gitignore` で塞いであるが、リポジトリ外に置くのが望ましい。
`ANTIGRAVITY_GOOGLE_CLIENT_SECRET` / `ANTIGRAVITY_GOOGLE_TOKEN` で差し替わる。

## 失敗したら例外を上げる

このモジュールは**フォールバックしない**。認証できないまま処理を続けると、
他人の動画を預かる運用で「成功したように見えて何もしていない」状態になる。
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

try:
    from backend.path_resolver import project_root
except ImportError:  # backend/ を直接 sys.path に載せている経路向け
    from path_resolver import project_root

logger = logging.getLogger(__name__)

__all__ = [
    "DRIVE_SCOPES",
    "SHEETS_SCOPES",
    "CredentialsNotFoundError",
    "GoogleAuthError",
    "client_secret_path",
    "load_credentials",
    "token_path",
]


class GoogleAuthError(RuntimeError):
    """Google 認証まわりの失敗。呼び出し側はこれだけ捕まえればよい。"""


class CredentialsNotFoundError(GoogleAuthError):
    """認証情報がまだ用意されていない（初回セットアップ未実施）。"""


# ---- スコープ ----
#
# `drive.file` はアプリ自身が作成したファイルにしかアクセスできない。
# 手で Drive に置いた撮影 RAW を読む用途があるので使えない。
# 読み取りと書き込みの両方が要るため `drive` を使う。
DRIVE_SCOPES: tuple[str, ...] = ("https://www.googleapis.com/auth/drive",)

# 進捗の書き戻しがあるので readonly では足りない。
SHEETS_SCOPES: tuple[str, ...] = ("https://www.googleapis.com/auth/spreadsheets",)


def _from_env(*names: str) -> Path | None:
    """環境変数を順に見て、最初の非空値を返す。空文字は未設定扱い。"""
    for name in names:
        value = os.environ.get(name)
        if value:
            return Path(value)
    return None


def _default_dir() -> Path:
    """既定の保存先（`<project_root>/backend/data/google`）。"""
    return project_root() / "backend" / "data" / "google"


def client_secret_path() -> Path:
    """GCP で発行した OAuth クライアント秘密の場所。"""
    return _from_env("ANTIGRAVITY_GOOGLE_CLIENT_SECRET") or (
        _default_dir() / "client_secret.json"
    )


def token_path() -> Path:
    """同意後に得たトークンの保存先。"""
    return _from_env("ANTIGRAVITY_GOOGLE_TOKEN") or (_default_dir() / "token.json")


# 実物の import をこの2関数に閉じ込める。テストはここを差し替えるだけで済み、
# googleapiclient が無い環境でもテストが動く。
def _credentials_from_info(info: dict[str, Any], scopes: Sequence[str]) -> Any:
    from google.oauth2.credentials import Credentials

    return Credentials.from_authorized_user_info(info, list(scopes))


def _transport_request() -> Any:
    from google.auth.transport.requests import Request

    return Request()


def _refresh_error_types() -> tuple[type[BaseException], ...]:
    """`credentials.refresh()` が投げうる例外の型。

    以前ここは全例外を受ける広い catch だった。フィットネス関数 FF-26 が
    「技術的負債レジストリに未登録の広い catch」として検出する。
    実際に投げられるのは google.auth の例外階層と、その下で起きる OSError なので、
    そこまで絞れば十分で、全例外を受ける必要はない。

    ライブラリ未導入時は import 自体が先に失敗するため、ここは呼ばれない。
    """
    from google.auth import exceptions as google_auth_exceptions

    return (google_auth_exceptions.GoogleAuthError, OSError)


def _save_token(path: Path, credentials: Any) -> None:
    """更新後のトークンを書き戻す。

    パーミッションを 0600 に絞る。POSIX でのみ意味があるが、CI(Linux) が
    基準環境なので Windows 前提にはしない。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(credentials.to_json())
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if os.name == "posix":
        os.chmod(path, 0o600)


def load_credentials(scopes: Sequence[str]) -> Any:
    """保存済みトークンを読み、必要ならリフレッシュして返す。

    Raises:
        CredentialsNotFoundError: トークン未作成。初回セットアップが必要。
        GoogleAuthError: 読み取り不能、またはリフレッシュ不能。
    """
    path = token_path()
    if not path.exists():
        raise CredentialsNotFoundError(
            f"Google の認証トークンがありません: {path}\n"
            "初回セットアップを実行してください: python scripts/google_oauth_login.py\n"
            "保存先を変えるには ANTIGRAVITY_GOOGLE_TOKEN を設定します。"
        )

    try:
        info = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise GoogleAuthError(f"認証トークンを読めません ({path}): {e}") from e

    try:
        credentials = _credentials_from_info(info, scopes)
    except (ValueError, KeyError) as e:
        raise GoogleAuthError(f"認証トークンの形式が不正です ({path}): {e}") from e

    if getattr(credentials, "expired", False):
        if not getattr(credentials, "refresh_token", None):
            raise GoogleAuthError(
                f"認証トークンが期限切れで、リフレッシュトークンがありません ({path})。"
                "再度 python scripts/google_oauth_login.py を実行してください。"
            )
        try:
            credentials.refresh(_transport_request())
        except _refresh_error_types() as e:
            raise GoogleAuthError(f"認証トークンのリフレッシュに失敗しました: {e}") from e
        _save_token(path, credentials)
        logger.info("[Google OAuth] トークンをリフレッシュしました")

    return credentials
