"""Google Drive / Sheets の初回 OAuth 同意を済ませ、トークンを保存する。

一度だけ手で実行する。以降は `google_oauth.load_credentials()` が
リフレッシュを自動で行うので、再実行は不要（同意を取り消した場合を除く）。

## 事前に必要なもの

GCP コンソールでの作業。ここは自動化できない。

1. プロジェクトを作る（既存でもよい）
2. 「API とサービス」→ Google Drive API と Google Sheets API を有効化
3. 「OAuth 同意画面」を設定する
   - User Type: 外部 / 公開ステータス: テスト のままでよい
   - **テストユーザーに自分の Gmail アドレスを追加する。**
     ここを忘れると同意画面で弾かれる
4. 「認証情報」→ OAuth クライアント ID を作成
   - アプリケーションの種類: **デスクトップアプリ**
5. JSON をダウンロードし、下記の場所に置く

       backend/data/google/client_secret.json

   別の場所に置くなら ANTIGRAVITY_GOOGLE_CLIENT_SECRET を設定する。

## 実行

    python scripts/google_oauth_login.py

ブラウザが開く。同意すると backend/data/google/token.json が作られる。
このファイルは秘密。`.gitignore` 済みだが、共有しないこと。

## raw を読むだけのトークン（M2・クラウドのセッション用）

    python scripts/google_oauth_login.py --readonly

`drive.readonly` だけを要求し、backend/data/google/token_raw_readonly.json に
**1行の JSON** で保存する。クラウドの環境変数 `ANTIGRAVITY_GOOGLE_TOKEN_JSON` に
中身をそのまま貼れるようにするため（手順書 docs/M2_STORAGE_SETUP_20260927.md §3・§4）。
保存先は `--token` で変えられる。法人 Workspace の同意画面を「内部」にしていれば、
下の「7日で失効」は当たらない。

## 注意

公開ステータスが「テスト」の間、リフレッシュトークンは **7日で失効する**。
継続運用するなら同意画面を「本番環境」に公開する（審査は、機微スコープを
使わない限り不要なことが多い）。失効したらこのスクリプトを再実行すればよい。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.google_oauth import (
    DRIVE_READONLY_SCOPES,
    DRIVE_SCOPES,
    SHEETS_SCOPES,
    TOKEN_JSON_ENV,
    client_secret_path,
    token_path,
)

SCOPES = list(DRIVE_SCOPES) + list(SHEETS_SCOPES)
READONLY_TOKEN_NAME = "token_raw_readonly.json"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Google の OAuth 同意を済ませてトークンを保存する")
    parser.add_argument(
        "--readonly", action="store_true",
        help="drive.readonly だけを要求する（raw を読むだけの口・クラウド用）",
    )
    parser.add_argument(
        "--token", type=Path, default=None,
        help="トークンの保存先（既定: 通常は token.json、--readonly なら token_raw_readonly.json）",
    )
    return parser.parse_args(argv)


def resolve_plan(readonly: bool, token: Path | None) -> tuple[list[str], Path]:
    """要求するスコープと保存先を決める。

    `--readonly` で読み書きのスコープが混ざることはない。混ざると
    クラウドのセッションに raw を消せるトークンを渡すことになる。
    """
    if readonly:
        return list(DRIVE_READONLY_SCOPES), token or (token_path().parent / READONLY_TOKEN_NAME)
    return list(SCOPES), token or token_path()


def serialize_token(credentials_json: str, *, one_line: bool) -> str:
    """トークンを保存用の文字列にする。読み取り専用は環境変数に貼るため1行にする。"""
    payload = json.loads(credentials_json)
    if one_line:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(payload, ensure_ascii=False, indent=2)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    scopes, out = resolve_plan(args.readonly, args.token)

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print(
            "google-auth-oauthlib が入っていません。\n"
            "  pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1

    secret = client_secret_path()
    if not secret.exists():
        print(
            f"OAuth クライアント秘密が見つかりません: {secret}\n\n"
            "このファイルの作り方はこのスクリプトの docstring を読んでください。\n"
            "別の場所に置く場合は ANTIGRAVITY_GOOGLE_CLIENT_SECRET を設定します。",
            file=sys.stderr,
        )
        return 1

    print("要求するスコープ:")
    for s in scopes:
        print(f"  - {s}")
    print("\nブラウザを開きます。Google の同意画面で許可してください。")
    if args.readonly:
        print("（raw を読むだけのトークンです。法人アカウントで同意してください）")

    flow = InstalledAppFlow.from_client_secrets_file(str(secret), scopes)
    credentials = flow.run_local_server(port=0)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        serialize_token(credentials.to_json(), one_line=args.readonly),
        encoding="utf-8",
    )
    if os.name == "posix":
        os.chmod(out, 0o600)

    print(f"\n完了しました。トークンを保存: {out}")
    print("このファイルは秘密です。共有しないでください。")
    if args.readonly:
        print(
            f"\nクラウドのセッションで使うには、このファイルの中身（1行）を\n"
            f"環境変数 {TOKEN_JSON_ENV} に貼ってください。チャットには貼らないでください。"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
