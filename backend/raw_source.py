"""raw 素材の読み口（M2・R2.5-C5）。**読むだけ。書かない・消さない。**

raw 4本は法人 Workspace の共有ドライブに置いてある（2026-09-27 ユーザー決定。
手順書 `docs/M2_STORAGE_SETUP_20260927.md`）。クラウドのセッションはそこから
素材を取ってくる。ここはその入口で、いまは一覧（`--list`）だけを持つ。
取得（ダウンロード）と置き場は次の PR で足す。

## 読み取り専用を二重に守る

1. トークンは `drive.readonly` だけで作る（`scripts/google_oauth_login.py --readonly`）
2. ここでも**トークンに記録されたスコープを読む前に確かめ**、読み書きの権限が
   混ざっていたら API を呼ぶ前に止める（憲法 §11「raw は聖域」）

## 使い方

    python -m backend.raw_source --list

| 環境変数 | 中身 |
|---|---|
| `AVS_RAW_DRIVE_FOLDER_ID` | raw を置いたフォルダの ID |
| `ANTIGRAVITY_GOOGLE_TOKEN_JSON` | 読み取り専用トークンの中身（クラウド）。ローカルはトークンファイルでもよい |

終了コード: 0 = 動画が1本以上見えた ／ 1 = 読めたが動画が無い・権限が広すぎる・認証失敗 ／
2 = フォルダ ID が未設定。**課金は発生しない**（Drive API は無料）。
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping
from typing import Any

from backend.services.google_oauth import (
    DRIVE_READONLY_SCOPES,
    GoogleAuthError,
    load_credentials,
    read_token_info,
    token_scopes,
)

FOLDER_ENV = "AVS_RAW_DRIVE_FOLDER_ID"


class TooBroadScopeError(GoogleAuthError):
    """読み取り専用の口に、書ける権限を持ったトークンが渡された。"""


def check_read_only(info: Mapping[str, Any]) -> None:
    """トークンのスコープが `drive.readonly` だけであることを確かめる。

    スコープの記録が無いトークンも通さない。何ができるか分からないものを
    raw に向けない。
    """
    granted = token_scopes(dict(info))
    allowed = set(DRIVE_READONLY_SCOPES)
    if not granted:
        raise TooBroadScopeError(
            "トークンにスコープの記録がありません。"
            "python scripts/google_oauth_login.py --readonly で作り直してください"
        )
    extra = sorted(granted - allowed)
    if extra:
        raise TooBroadScopeError(
            "トークンに読み取り専用以外の権限が含まれています: "
            + ", ".join(extra)
            + "。raw は読むだけなので、--readonly で作ったトークンを使ってください"
        )


def _build_drive() -> Any:
    """認証済みの Drive クライアント。テストはここを差し替える。"""
    from googleapiclient.discovery import build

    credentials = load_credentials(DRIVE_READONLY_SCOPES)
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _api_error_types() -> tuple[type[BaseException], ...]:
    """Drive API の呼び出しが投げうる例外（フォルダが無い・権限が無い・通信断）。"""
    try:
        from googleapiclient.errors import HttpError
    except ImportError:
        return (OSError,)
    return (HttpError, OSError)


def list_videos(service: Any, folder_id: str) -> list[dict[str, Any]]:
    """フォルダ直下の動画を列挙する（ゴミ箱は除く・ページングを辿る）。

    `video/` で始まる MIME をすべて拾う。撮影 raw は mp4 とは限らない（mov など）。
    """
    query = f"'{folder_id}' in parents and mimeType contains 'video/' and trashed = false"
    files: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        response = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name, size, mimeType, modifiedTime)",
            pageToken=page_token,
            pageSize=100,
            orderBy="name",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        files.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            return files


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"  # 到達しない（型のため）


def format_listing(files: list[dict[str, Any]], folder_id: str) -> str:
    """一覧の表示。フォルダ ID は末尾4文字だけ出す（台帳と同じ流儀）。"""
    lines = [f"raw のフォルダ（ID 末尾 {folder_id[-4:]}）", ""]
    total = 0
    for f in files:
        size = int(f.get("size") or 0)
        total += size
        lines.append(f"  {f.get('name', '?')}  {_human_size(size)}  ({size:,} bytes)")
    lines += ["", f"  {len(files)} 本・合計 {_human_size(total)}"]
    return "\n".join(lines)


def run_list(env: Mapping[str, str]) -> int:
    folder_id = env.get(FOLDER_ENV, "")
    if not folder_id:
        print(f"{FOLDER_ENV} が未設定です（手順書 §4）", file=sys.stderr)
        return 2
    try:
        info, source, _ = read_token_info()
        check_read_only(info)
        files = list_videos(_build_drive(), folder_id)
    except GoogleAuthError as e:
        print(f"🚫 {e}", file=sys.stderr)
        return 1
    except ImportError as e:
        print(f"🚫 google-api-python-client が入っていません: {e}", file=sys.stderr)
        return 1
    except _api_error_types() as e:
        print(f"🚫 Drive から読めませんでした: {e}", file=sys.stderr)
        return 1
    print(format_listing(files, folder_id))
    print(f"\n  トークン: {source}（読み取り専用）")
    if not files:
        print("🚫 動画が見つかりません。フォルダ ID と共有ドライブの権限を確かめてください",
              file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="raw 素材の読み口（読むだけ）")
    parser.add_argument("--list", action="store_true", help="raw の名前と大きさを読む")
    args = parser.parse_args(argv)
    if args.list:
        return run_list(os.environ)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
