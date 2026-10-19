"""raw 素材の読み口（M2・R2.5-C5）。**読むだけ。書かない・消さない。**

raw 4本は法人 Workspace の共有ドライブに置いてある（2026-09-27 ユーザー決定。
手順書 `docs/M2_STORAGE_SETUP_20260927.md`）。クラウドのセッションはそこから
素材を取ってくる。ここはその入口で、一覧（`--list`）と取得（`--fetch <取得先>`）を持つ。
取得先はクラウドの作業場（git の外・`pipeline_work/` など）。Drive には何も書かない。

## 読み取り専用を二重に守る

1. トークンは `drive.readonly` だけで作る（`scripts/google_oauth_login.py --readonly`）
2. ここでも**トークンに記録されたスコープを読む前に確かめ**、読み書きの権限が
   混ざっていたら API を呼ぶ前に止める（憲法 §11「raw は聖域」）

## 使い方

    python -m backend.raw_source --list
    python -m backend.raw_source --fetch pipeline_work/raw   # 同じ大きさの物があれば取り直さない
    python -m backend.raw_source --list --folder 2025-09-22_撮影生データ   # 中のフォルダの素材
    python -m backend.raw_source --fetch pipeline_work/camera --folder 2025-09-22_撮影生データ

素材ごとのフォルダ（撮影生データ・別の対談）は raw のフォルダの中に作る（2026-10-18）。
`--folder` は名前で1つ選び、無い・同じ名前が2つあるときは何も落とさずに止まる。
一覧には解像度と長さ（Drive の記録）も出す。取得は、落とす前に作業場の空きを確かめ
（`FETCH_MARGIN_BYTES` を残せなければ1本も落とさない）、落とした後は大きさと md5 を Drive と照合する。

| 環境変数 | 中身 |
|---|---|
| `AVS_RAW_DRIVE_FOLDER_ID` | raw を置いたフォルダの ID |
| `ANTIGRAVITY_GOOGLE_TOKEN_JSON` | 読み取り専用トークンの中身（クラウド）。ローカルはトークンファイルでもよい |

終了コード: 0 = 動画が1本以上見えた ／ 1 = 読めたが動画が無い・権限が広すぎる・認証失敗 ／
2 = フォルダ ID が未設定。**課金は発生しない**（Drive API は無料）。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from backend.services.google_oauth import (
    DRIVE_READONLY_SCOPES,
    GoogleAuthError,
    load_credentials,
    read_token_info,
    token_scopes,
)

FOLDER_ENV = "AVS_RAW_DRIVE_FOLDER_ID"
FOLDER_MIME = "application/vnd.google-apps.folder"

# 取り込んだ後にも作業場に残す空き。書き出しは空きが1GB未満だと始まらず、
# 字幕を焼き込んだ書き出しと中間ファイルも置くので、その分を見込む。
FETCH_MARGIN_BYTES = 3 * 1024 ** 3


class TooBroadScopeError(GoogleAuthError):
    """読み取り専用の口に、書ける権限を持ったトークンが渡された。"""


class FetchError(RuntimeError):
    """取得した大きさ・md5 が Drive の記録と合わない（途中で切れた・壊れた）、または空きが足りない。"""


class FolderError(RuntimeError):
    """素材のフォルダが見つからない・同じ名前が2つある。"""


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


def _list_files(service: Any, query: str, fields: str) -> list[dict[str, Any]]:
    """Drive の一覧をページングで最後まで読む（共有ドライブも・名前順）。"""
    files: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        response = service.files().list(
            q=query,
            fields=f"nextPageToken, files({fields})",
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


def list_videos(service: Any, folder_id: str) -> list[dict[str, Any]]:
    """フォルダ直下の動画を列挙する（ゴミ箱は除く・ページングを辿る）。

    `video/` で始まる MIME をすべて拾う。撮影 raw は mp4 とは限らない（mov など）。
    md5 は取得の照合に、`videoMediaMetadata`（幅・高さ・長さ）は取り込む前の見積もりに使う。
    Drive が動画を処理し終えるまで `videoMediaMetadata` は付かないことがある。
    """
    query = f"'{folder_id}' in parents and mimeType contains 'video/' and trashed = false"
    return _list_files(service, query,
                       "id, name, size, mimeType, modifiedTime, md5Checksum, videoMediaMetadata")


def list_folders(service: Any, parent_id: str) -> list[dict[str, Any]]:
    """フォルダ直下のフォルダ（素材ごとのフォルダ）を名前順に列挙する。"""
    query = f"'{parent_id}' in parents and mimeType = '{FOLDER_MIME}' and trashed = false"
    return _list_files(service, query, "id, name")


def find_folder(service: Any, parent_id: str, name: str) -> str:
    """中のフォルダを名前で1つ選ぶ。**無い・2つある**ときはどれを読むか決めずに止まる。"""
    matches = [f for f in list_folders(service, parent_id) if f.get("name") == name]
    if not matches:
        raise FolderError(f"フォルダ「{name}」が raw のフォルダの中にありません")
    if len(matches) > 1:
        raise FolderError(f"フォルダ「{name}」が {len(matches)} つあります。名前を1つにしてください")
    return str(matches[0]["id"])


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"  # 到達しない（型のため）


def _clock(seconds: float) -> str:
    whole = int(seconds)
    h, rest = divmod(whole, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _video_info(f: dict[str, Any]) -> tuple[str, float | None]:
    """Drive の記録から「幅x高さ  長さ」と長さ（秒）を返す。記録が無ければ ("", None)。"""
    meta = f.get("videoMediaMetadata") or {}
    parts = []
    if meta.get("width") and meta.get("height"):
        parts.append(f"{meta['width']}x{meta['height']}")
    seconds = None
    if meta.get("durationMillis"):
        seconds = int(meta["durationMillis"]) / 1000
        parts.append(_clock(seconds))
    return "  ".join(parts), seconds


def format_listing(files: list[dict[str, Any]], folder_id: str,
                   folders: list[dict[str, Any]] | None = None) -> str:
    """一覧の表示。フォルダ ID は末尾4文字だけ出す（台帳と同じ流儀）。"""
    lines = [f"raw のフォルダ（ID 末尾 {folder_id[-4:]}）", ""]
    total = 0
    length = 0.0
    unknown = 0
    for f in files:
        size = int(f.get("size") or 0)
        total += size
        info, seconds = _video_info(f)
        if seconds is None:
            unknown += 1
        else:
            length += seconds
        lines.append(f"  {f.get('name', '?')}  {_human_size(size)}  ({size:,} bytes)"
                     + (f"  {info}" if info else ""))
    summary = f"  {len(files)} 本・合計 {_human_size(total)}"
    if length:
        summary += f"・長さ {_clock(length)}" + (f"（{unknown} 本は長さの記録なし）" if unknown else "")
    lines += ["", summary]
    if folders:
        lines += ["", "  中のフォルダ（--folder で選ぶ）:"]
        lines += [f"    {f.get('name', '?')}" for f in folders]
    return "\n".join(lines)


def _download(service: Any, file_id: str, dest: Path) -> None:
    """1本を `dest` に落とす（分割取得）。テストはここを差し替える。"""
    from googleapiclient.http import MediaIoBaseDownload

    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    with dest.open("wb") as f:
        downloader = MediaIoBaseDownload(f, request, chunksize=64 * 1024 * 1024)
        done = False
        while not done:
            _, done = downloader.next_chunk(num_retries=3)


def _md5_of(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def fetch_videos(service: Any, files: list[dict[str, Any]], dest_dir: str | Path,
                 *, download: Callable[[Any, str, Path], None] | None = None,
                 free_bytes: Callable[[Path], int] | None = None) -> list[Path]:
    """一覧の動画を `dest_dir` に取ってくる。**Drive 側には何もしない。**

    - 同じ名前・同じ大きさの物がもうあれば取り直さない（18分素材の取り直しは重い）
    - 落とす前に空きを確かめる。これから落とす分と `FETCH_MARGIN_BYTES` が入らなければ
      1本も落とさずに `FetchError`（撮影データは大きい。作業場を埋めると書き出しも止まる）
    - `.part` に書いてから名前を付ける。大きさか md5 が Drive と違えば消して `FetchError`
    - Drive 上の名前はファイル名の部分だけ使う（取得先の外に書かない）
    """
    download = download or _download
    free_bytes = free_bytes or _free_bytes
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    plan = []
    for f in files:
        name = Path(str(f.get("name") or f["id"])).name
        expected = int(f.get("size") or 0)
        dest = dest_dir / name
        plan.append((f, name, expected, dest, dest.is_file() and dest.stat().st_size == expected))
    needed = sum(expected for _, _, expected, _, have in plan if not have)
    free = free_bytes(dest_dir)
    if needed and free < needed + FETCH_MARGIN_BYTES:
        raise FetchError(
            f"作業場の空きが足りません（空き {_human_size(free)} / 取得 {_human_size(needed)}"
            f" ＋ 残す {_human_size(FETCH_MARGIN_BYTES)}）。1本も落としていません")
    paths: list[Path] = []
    for f, name, expected, dest, have in plan:
        if have:
            print(f"  {name}: 取得済み（{_human_size(expected)}）")
            paths.append(dest)
            continue
        part = dest.with_name(dest.name + ".part")
        try:
            download(service, f["id"], part)
            got = part.stat().st_size
            if got != expected:
                raise FetchError(f"{name}: 大きさが合いません（Drive {expected:,} / 取得 {got:,} bytes）")
            md5 = f.get("md5Checksum")
            if md5 and _md5_of(part) != md5:
                raise FetchError(f"{name}: 中身が Drive と合いません（md5 が違う）")
            part.replace(dest)
        finally:
            part.unlink(missing_ok=True)
        print(f"  {name}: 取得（{_human_size(expected)}" + ("・md5 一致）" if f.get("md5Checksum") else "）"))
        paths.append(dest)
    return paths


def run_fetch(env: Mapping[str, str], dest_dir: str | Path, folder: str | None = None) -> int:
    folder_id = env.get(FOLDER_ENV, "")
    if not folder_id:
        print(f"{FOLDER_ENV} が未設定です（手順書 §4）", file=sys.stderr)
        return 2
    try:
        info, _, _ = read_token_info()
        check_read_only(info)
        service = _build_drive()
        source = find_folder(service, folder_id, folder) if folder else folder_id
        files = list_videos(service, source)
        if not files:
            print("🚫 動画が見つかりません", file=sys.stderr)
            return 1
        where = f"「{folder}」" if folder else f"（ID 末尾 {folder_id[-4:]}）"
        print(f"raw のフォルダ{where}から {len(files)} 本を {dest_dir} へ")
        fetch_videos(service, files, dest_dir, download=_download)
    except (GoogleAuthError, FetchError, FolderError) as e:
        print(f"🚫 {e}", file=sys.stderr)
        return 1
    except ImportError as e:
        print(f"🚫 google-api-python-client が入っていません: {e}", file=sys.stderr)
        return 1
    except _api_error_types() as e:
        print(f"🚫 Drive から読めませんでした: {e}", file=sys.stderr)
        return 1
    return 0


def run_list(env: Mapping[str, str], folder: str | None = None) -> int:
    folder_id = env.get(FOLDER_ENV, "")
    if not folder_id:
        print(f"{FOLDER_ENV} が未設定です（手順書 §4）", file=sys.stderr)
        return 2
    try:
        info, source, _ = read_token_info()
        check_read_only(info)
        service = _build_drive()
        if folder:
            files = list_videos(service, find_folder(service, folder_id, folder))
            folders = []
        else:
            files = list_videos(service, folder_id)
            folders = list_folders(service, folder_id)
    except (GoogleAuthError, FolderError) as e:
        print(f"🚫 {e}", file=sys.stderr)
        return 1
    except ImportError as e:
        print(f"🚫 google-api-python-client が入っていません: {e}", file=sys.stderr)
        return 1
    except _api_error_types() as e:
        print(f"🚫 Drive から読めませんでした: {e}", file=sys.stderr)
        return 1
    if folder:
        print(f"中のフォルダ「{folder}」")
    print(format_listing(files, folder_id, folders))
    print(f"\n  トークン: {source}（読み取り専用）")
    if not files:
        print("🚫 動画が見つかりません。フォルダ ID と共有ドライブの権限を確かめてください",
              file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="raw 素材の読み口（読むだけ）")
    parser.add_argument("--list", action="store_true", help="raw の名前と大きさを読む")
    parser.add_argument("--fetch", metavar="DIR", help="raw を DIR に取ってくる（Drive には書かない）")
    parser.add_argument("--folder", metavar="NAME",
                        help="raw のフォルダの中の、この名前のフォルダを読む（素材ごとのフォルダ）")
    args = parser.parse_args(argv)
    if args.list:
        return run_list(os.environ, folder=args.folder)
    if args.fetch:
        return run_fetch(os.environ, args.fetch, folder=args.folder)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
