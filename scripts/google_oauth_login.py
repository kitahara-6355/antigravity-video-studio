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

## 注意

公開ステータスが「テスト」の間、リフレッシュトークンは **7日で失効する**。
継続運用するなら同意画面を「本番環境」に公開する（審査は、機微スコープを
使わない限り不要なことが多い）。失効したらこのスクリプトを再実行すればよい。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.google_oauth import (
    DRIVE_SCOPES,
    SHEETS_SCOPES,
    client_secret_path,
    token_path,
)

SCOPES = list(DRIVE_SCOPES) + list(SHEETS_SCOPES)


def main() -> int:
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
    for s in SCOPES:
        print(f"  - {s}")
    print("\nブラウザを開きます。Google の同意画面で許可してください。")

    flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
    credentials = flow.run_local_server(port=0)

    out = token_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(json.loads(credentials.to_json()), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if os.name == "posix":
        os.chmod(out, 0o600)

    print(f"\n完了しました。トークンを保存: {out}")
    print("このファイルは秘密です。共有しないでください。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
