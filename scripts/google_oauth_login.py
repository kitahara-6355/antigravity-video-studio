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

## 過程の資産を書くトークン（drive.file・2026-10-18）

    python scripts/google_oauth_login.py --assets

`drive.file` **だけ**を要求する（アプリが作ったファイルしか見えない・触れない）。
raw を読むトークンとは別に作る。`--readonly` とは同時に付けられない。
backend/data/google/token_assets_file.json に **1行の JSON** で保存する。

一度だけの手順:

1. 法人アカウント（info@kitahara-birei.com）でブラウザにログインしておく
2. 上のコマンドを実行し、同意画面（avs-prod-free-kb の `avs-raw-reader`・内部）で許可する。
   同意画面のスコープ一覧に drive.file が無ければ先に足しておく（内部なので審査は要らない）
3. ローカルはこのファイルのまま使える。クラウドのセッションでは中身（1行）を
   環境変数 `AVS_ASSETS_GOOGLE_TOKEN_JSON` に貼る（チャットには貼らない）
4. `python -m backend.asset_store check` で権限が drive.file だけか確かめる（外には出ない）

## 「動画制作」を整理するトークン（drive 全体・2026-10-22）

    python scripts/google_oauth_login.py --organize

`drive` **だけ**を要求する（人が置いたファイルも移せる・名前を変えられる）。北原さんが
2026-10-22 に「AI の書く鍵を Drive 全体に広げ、移動と名前の変更を任せる」と決めた。
使うのは `backend/drive_organize.py` だけで、そこには中身を変える・消す口が無い。
backend/data/google/token_drive_organizer.json に **1行の JSON** で保存する。
クラウドでは中身を環境変数 `AVS_DRIVE_ORGANIZER_TOKEN_JSON` に貼る。
法人アカウント（info@kitahara-birei.com）で許可する。

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
    ASSETS_TOKEN_JSON_ENV,
    DRIVE_FILE_SCOPES,
    DRIVE_READONLY_SCOPES,
    DRIVE_SCOPES,
    ORGANIZER_TOKEN_JSON_ENV,
    SHEETS_SCOPES,
    TOKEN_JSON_ENV,
    assets_token_path,
    client_secret_path,
    organizer_token_path,
    token_path,
)

SCOPES = list(DRIVE_SCOPES) + list(SHEETS_SCOPES)
READONLY_TOKEN_NAME = "token_raw_readonly.json"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Google の OAuth 同意を済ませてトークンを保存する")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--readonly", action="store_true",
        help="drive.readonly だけを要求する（raw を読むだけの口・クラウド用）",
    )
    mode.add_argument(
        "--assets", action="store_true",
        help="drive.file だけを要求する（過程の資産を書く口・クラウド用）",
    )
    mode.add_argument(
        "--organize", action="store_true",
        help="drive だけを要求する（動画制作を整理する口・移す/名前を変える・クラウド用）",
    )
    parser.add_argument(
        "--token", type=Path, default=None,
        help="トークンの保存先（既定: 通常は token.json、--readonly なら token_raw_readonly.json、"
             "--assets なら token_assets_file.json）",
    )
    return parser.parse_args(argv)


def resolve_plan(readonly: bool, token: Path | None,
                 assets: bool = False, organize: bool = False) -> tuple[list[str], Path]:
    """要求するスコープと保存先を決める。

    `--readonly` で読み書きのスコープが混ざることはない。混ざると
    クラウドのセッションに raw を消せるトークンを渡すことになる。
    `--assets` も drive.file だけ。読み取りの口と同じトークンにしない。
    """
    if sum((readonly, assets, organize)) > 1:
        raise ValueError("--readonly・--assets・--organize は同時に使えません（トークンを分ける）")
    if organize:
        return list(DRIVE_SCOPES), token or organizer_token_path()
    if readonly:
        return list(DRIVE_READONLY_SCOPES), token or (token_path().parent / READONLY_TOKEN_NAME)
    if assets:
        return list(DRIVE_FILE_SCOPES), token or assets_token_path()
    return list(SCOPES), token or token_path()


def serialize_token(credentials_json: str, *, one_line: bool) -> str:
    """トークンを保存用の文字列にする。読み取り専用は環境変数に貼るため1行にする。"""
    payload = json.loads(credentials_json)
    if one_line:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(payload, ensure_ascii=False, indent=2)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    scopes, out = resolve_plan(args.readonly, args.token, assets=args.assets, organize=args.organize)
    one_line = args.readonly or args.assets or args.organize

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
    if args.assets:
        print("（過程の資産を書くトークンです。アプリが作ったファイルだけ触れます。"
              "法人アカウントで同意してください）")
    if args.organize:
        print("（動画制作を整理するトークンです。Drive 全体に届きます。"
              "法人アカウントで同意してください）")

    flow = InstalledAppFlow.from_client_secrets_file(str(secret), scopes)
    credentials = flow.run_local_server(port=0)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        serialize_token(credentials.to_json(), one_line=one_line),
        encoding="utf-8",
    )
    if os.name == "posix":
        os.chmod(out, 0o600)

    print(f"\n完了しました。トークンを保存: {out}")
    print("このファイルは秘密です。共有しないでください。")
    if one_line:
        env_name = (ASSETS_TOKEN_JSON_ENV if args.assets else
                    ORGANIZER_TOKEN_JSON_ENV if args.organize else TOKEN_JSON_ENV)
        print(
            f"\nクラウドのセッションで使うには、このファイルの中身（1行）を\n"
            f"環境変数 {env_name} に貼ってください。チャットには貼らないでください。"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
