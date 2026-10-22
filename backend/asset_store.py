"""過程の資産の置き場（Google Drive・`drive.file`）。**書く口。raw は読まない。**

AI の出力・字幕・実行記録を Drive に残す。クラウドの作業場は消えるので、
消える前にここへ送っておく（2026-10-18 北原さん決定）。

## トークンは raw を読むものと別

- 使うのは `drive.file` **だけ**のトークン（`scripts/google_oauth_login.py --assets`）。
  クラウドでは `AVS_ASSETS_GOOGLE_TOKEN_JSON`、ローカルでは
  `backend/data/google/token_assets_file.json` から読む。読み取り用のトークン
  （`ANTIGRAVITY_GOOGLE_TOKEN_JSON`）には落ちない
- 権限が drive.file ちょうどでなければ（Drive 全体・読み取り専用・混ざったもの）、
  **API を呼ぶ前に止まる。** Drive 全体に届くトークンを誤って使わない

## drive.file でできること・できないこと

- アプリが作ったファイルとフォルダだけが見え、触れる。raw にも他人のファイルにも届かない
- **アプリが作っていないフォルダの中には書けない**（共有ドライブの既存のフォルダなど）。
  だから置き場の一番上（ルート）のフォルダもアプリが自分で作る
- ルートは マイドライブ に `AVS_ASSETS_DRIVE_ROOT_NAME`（既定「AVS 過程の資産」）の名前で作る。
  作った後に北原さんが別の場所（共有ドライブなど）へ動かし、名前を変えてもよい
  （2026-10-20 の構成案では「動画制作 / 30_AVS_作業」）
- ルートの id は作ったときに付けた印（`ROOT_MARK`）で毎回引き直す。名前は見ないので、
  移しても名前を変えても同じ置き場を使い続ける。作業場は消えるので、
  手元に覚えておく先が無い。1回の実行の中では引いた id を使い回す。
  `AVS_ASSETS_DRIVE_ROOT_NAME` を指定したときだけ、名前と印の両方で探す（試しの置き場を分ける用）

## 送り方

- 分割して送る（resumable）。送った後、Drive が返す `md5Checksum` と大きさが
  手元と一致しなければ `UploadError`（成功とは言わない）
- 同じフォルダに**同じ名前・同じ md5** の物があれば送らない（`already`）
- 同じ名前で中身が違えば、**既存のファイルの新しい版として中身を差し替える**
  （別のファイルを増やさない。Drive の版の履歴に前の中身が残る）。
  同じ名前が2つ以上あるときは、どれを差し替えるか決めずに止まる
- 送る前に件数と合計の大きさを出す。送らない物（リンクのフォルダなど）も名前を出す

## 使い方

    python -m backend.asset_store check                       # トークンの有無と権限（外に出ない）
    python -m backend.asset_store put pipeline_work/job1 --to jobs/job1
    python -m backend.asset_store put pipeline_work/job1 --to jobs/job1 --manifest m.json
    python -m backend.asset_store list jobs/job1
    python -m backend.asset_store move raw4_20250922/repro_20261018 --to 収録/20250922_久木田ヒロノブ/再現_20261018

`move` は置き場の中で並べ直すだけ（アプリが作った物どうし）。中身は送り直さないので id と md5 は変わらない。
動かした後に空になった元のフォルダはゴミ箱へ入れる（Drive のゴミ箱から戻せる）。

終了コード: 0 = できた ／ 1 = 認証・権限・照合・Drive の失敗 ／ 2 = 引数の誤り。
**課金は発生しない**（Drive API は無料）。
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from backend.raw_source import _api_error_types, _human_size, _md5_of
from backend.services.google_oauth import (
    ASSETS_TOKEN_JSON_ENV,
    DRIVE_FILE_SCOPES,
    CredentialsNotFoundError,
    GoogleAuthError,
    assets_token_path,
    load_credentials,
    read_token_info,
    token_scopes,
)

ROOT_NAME_ENV = "AVS_ASSETS_DRIVE_ROOT_NAME"
DEFAULT_ROOT_NAME = "AVS 過程の資産"
FOLDER_MIME = "application/vnd.google-apps.folder"
# ルートに付ける印。下の階層に同じ名前のフォルダがあってもルートと取り違えない。
ROOT_MARK = ("avs_assets_root", "1")
# 分割の大きさ。256KB の倍数でないと Drive が受け付けない。
CHUNK_BYTES = 16 * 1024 * 1024
FILE_FIELDS = "id, name, mimeType, md5Checksum, size"

LOGIN_HINT = "python scripts/google_oauth_login.py --assets"


class ScopeError(GoogleAuthError):
    """資産の口に drive.file ちょうどでないトークンが渡された。"""


class UploadError(RuntimeError):
    """送った中身が手元と合わない・差し替え先が決められない・送る物が無い。"""


class PathError(RuntimeError):
    """行き先のパスが不正・見つからない・同じ名前のフォルダが2つある。"""


# --- トークン ----------------------------------------------------------------


def check_file_scope(info: Mapping[str, Any]) -> None:
    """トークンの権限が `drive.file` ちょうどであることを確かめる。

    Drive 全体（`drive`）・読み取り専用・それらが混ざったもの・記録なしは、すべて通さない。
    """
    granted = token_scopes(dict(info))
    if granted != set(DRIVE_FILE_SCOPES):
        shown = ", ".join(sorted(granted)) or "記録なし"
        raise ScopeError(
            f"過程の資産を書くトークンの権限が drive.file だけではありません: {shown}。"
            f"Drive 全体に届くトークンや raw を読むトークンは使いません。{LOGIN_HINT} で"
            "作り直してください。何も送っていません"
        )


def load_token_info() -> tuple[dict[str, Any], str]:
    """資産のトークンだけを読み、権限を確かめる。外には出ない。

    Returns:
        (中身, 出どころの説明)。出どころに中身は含めない。
    """
    path = assets_token_path()
    try:
        info, source, _ = read_token_info(ASSETS_TOKEN_JSON_ENV, path)
    except CredentialsNotFoundError:
        raise CredentialsNotFoundError(
            f"過程の資産を書くトークンがありません（環境変数 {ASSETS_TOKEN_JSON_ENV} も {path} も無い）。"
            f"{LOGIN_HINT} で作ってください。何も送っていません"
        ) from None
    check_file_scope(info)
    return info, source


def _build_drive() -> Any:
    """認証済みの Drive クライアント。**権限を確かめてから作る。** テストはここを差し替える。"""
    load_token_info()
    from googleapiclient.discovery import build

    credentials = load_credentials(DRIVE_FILE_SCOPES, json_env=ASSETS_TOKEN_JSON_ENV,
                                   token_file=assets_token_path())
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


# --- Drive の読み書き --------------------------------------------------------


def _quote(value: str) -> str:
    """Drive の検索式の文字列に入れる形にする（`\\` と `'` を逃がす）。"""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _find(service: Any, *, name: str | None = None, parent: str | None = None,
          folder: bool | None = None, root_mark: bool = False) -> list[dict[str, Any]]:
    """見える物（drive.file ならアプリが作った物だけ）を検索する。ゴミ箱は除く・ページングを辿る。"""
    terms = ["trashed = false"]
    if name is not None:
        terms.append(f"name = '{_quote(name)}'")
    if parent is not None:
        terms.append(f"'{_quote(parent)}' in parents")
    if folder is True:
        terms.append(f"mimeType = '{FOLDER_MIME}'")
    elif folder is False:
        terms.append(f"mimeType != '{FOLDER_MIME}'")
    if root_mark:
        key, value = ROOT_MARK
        terms.append(f"appProperties has {{ key='{key}' and value='{value}' }}")
    files: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        response = service.files().list(
            q=" and ".join(terms),
            fields=f"nextPageToken, files({FILE_FIELDS})",
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


def root_name(env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    return env.get(ROOT_NAME_ENV) or DEFAULT_ROOT_NAME


def ensure_root(service: Any, name: str | None = None) -> str:
    """置き場のルートのフォルダを見つける。無ければ マイドライブ に作る。

    ふだんは印（`ROOT_MARK`）だけで探す。共有ドライブへ移したり名前を変えたりしても
    同じ置き場を使い続けるため（2026-10-20）。名前を指定したとき（引数か `ROOT_NAME_ENV`）は
    名前と印の両方で探す。2つ見つかったらどちらにも書かずに止まる。
    """
    pinned = name or os.environ.get(ROOT_NAME_ENV) or None
    name = pinned or root_name()
    found = _find(service, name=pinned, folder=True, root_mark=True)
    if len(found) > 1:
        raise PathError(f"置き場のルート「{name}」が {len(found)} つあります。1つにしてください")
    if found:
        return str(found[0]["id"])
    key, value = ROOT_MARK
    created = service.files().create(
        body={"name": name, "mimeType": FOLDER_MIME, "appProperties": {key: value}},
        fields="id", supportsAllDrives=True,
    ).execute()
    return str(created["id"])


def _segments(path: str | Path) -> list[str]:
    """`a/b/c` をフォルダ名の並びにする。`.` と `..` は受けない（行き先の外に書かない）。"""
    parts = [p for p in str(path).replace("\\", "/").split("/") if p]
    if any(p in (".", "..") for p in parts):
        raise PathError(f"行き先のパスに . や .. は使えません: {path}")
    return parts


def _child_folder(service: Any, parent_id: str, name: str, *, create: bool) -> str | None:
    found = _find(service, name=name, parent=parent_id, folder=True)
    if len(found) > 1:
        raise PathError(f"フォルダ「{name}」が {len(found)} つあります。名前を1つにしてください")
    if found:
        return str(found[0]["id"])
    if not create:
        return None
    created = service.files().create(
        body={"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]},
        fields="id", supportsAllDrives=True,
    ).execute()
    return str(created["id"])


def ensure_path(service: Any, root_id: str, path: str | Path) -> str:
    """`root_id` の下に `job/sub/dir` のフォルダを順に用意する（何度呼んでも1つだけ）。"""
    parent = root_id
    for name in _segments(path):
        parent = _child_folder(service, parent, name, create=True)  # type: ignore[assignment]
    return parent


def find_path(service: Any, root_id: str, path: str | Path) -> str | None:
    """`ensure_path` の作らない版。途中が無ければ None。"""
    parent: str | None = root_id
    for name in _segments(path):
        parent = _child_folder(service, parent, name, create=False)  # type: ignore[arg-type]
        if parent is None:
            return None
    return parent


def _media(path: Path, resumable: bool) -> Any:
    """送る中身。テストはここを差し替える。"""
    from googleapiclient.http import MediaFileUpload

    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if resumable:
        return MediaFileUpload(str(path), mimetype=mime, resumable=True, chunksize=CHUNK_BYTES)
    return MediaFileUpload(str(path), mimetype=mime, resumable=False)


def _send(request: Any, resumable: bool) -> dict[str, Any]:
    """分割して最後まで送る。空のファイルは分割できないので1回で送る。"""
    if not resumable:
        return request.execute(num_retries=3)
    response = None
    while response is None:
        _, response = request.next_chunk(num_retries=3)
    return response


def put(service: Any, local_path: str | Path, folder_id: str) -> dict[str, Any]:
    """1つを `folder_id` に送り、Drive の md5 と大きさを手元と照合する。

    Returns:
        {path, id, md5, size, state, new_version}。state は uploaded / already。
        new_version は同じ名前の既存のファイルの中身を差し替えたとき True。

    Raises:
        UploadError: 照合が合わない（成功とは言わない）、同じ名前が2つ以上ある。
    """
    path = Path(local_path)
    if not path.is_file():
        raise UploadError(f"送るファイルがありません: {path}")
    name = path.name
    size = path.stat().st_size
    md5 = _md5_of(path)
    existing = _find(service, name=name, parent=folder_id, folder=False)
    for f in existing:
        if f.get("md5Checksum") == md5 and int(f.get("size") or -1) == size:
            return {"path": name, "id": str(f["id"]), "md5": md5, "size": size,
                    "state": "already", "new_version": False}
    if len(existing) > 1:
        raise UploadError(f"{name}: 同じ名前のファイルが {len(existing)} つあります。"
                          "どれを新しい版にするか決められないので送っていません")
    resumable = size > 0
    media = _media(path, resumable)
    files = service.files()
    if existing:
        request = files.update(fileId=existing[0]["id"], media_body=media,
                               fields=FILE_FIELDS, supportsAllDrives=True)
    else:
        request = files.create(body={"name": name, "parents": [folder_id]}, media_body=media,
                               fields=FILE_FIELDS, supportsAllDrives=True)
    response = _send(request, resumable)
    got_md5 = response.get("md5Checksum")
    got_size = int(response.get("size") or -1)
    if got_md5 != md5 or got_size != size:
        raise UploadError(
            f"{name}: 送った中身が手元と合いません（手元 {size:,} bytes・md5 {md5[:8]} / "
            f"Drive {got_size:,} bytes・md5 {(got_md5 or '記録なし')[:8]}）。成功ではありません。"
            "もう一度送れば新しい版で差し替わります")
    return {"path": name, "id": str(response["id"]), "md5": md5, "size": size,
            "state": "uploaded", "new_version": bool(existing)}


def _scan(local_dir: Path) -> tuple[list[Path], list[Path], list[Path]]:
    """送るファイル・作るフォルダ・送らない物（リンクのフォルダなど）に分ける。名前順。"""
    files: list[Path] = []
    dirs: list[Path] = []
    others: list[Path] = []
    for top, dirnames, filenames in os.walk(local_dir, followlinks=False):
        top_path = Path(top)
        dirnames.sort()
        for d in list(dirnames):
            p = top_path / d
            if p.is_symlink():
                others.append(p)
                dirnames.remove(d)
            else:
                dirs.append(p)
        for f in sorted(filenames):
            p = top_path / f
            (files if p.is_file() else others).append(p)
    return sorted(files), sorted(dirs), sorted(others)


def _stderr(message: str) -> None:
    print(message, file=sys.stderr)


def put_tree(service: Any, local_dir: str | Path, dest_path: str | Path, *,
             root_id: str | None = None,
             log: Callable[[str], None] | None = None) -> list[dict[str, Any]]:
    """ディレクトリをまるごと、相対パスを保って `ルート/dest_path` の下へ送る。

    Returns:
        マニフェスト。1ファイル1行で {path（相対・/ 区切り）, id, md5, size, state, new_version}。
    """
    log = log or _stderr
    local_dir = Path(local_dir)
    if not local_dir.is_dir():
        raise UploadError(f"送るフォルダがありません: {local_dir}")
    files, dirs, others = _scan(local_dir)
    total = sum(p.stat().st_size for p in files)
    log(f"送る: {len(files)} 件・合計 {_human_size(total)}（{total:,} bytes）"
        f" {local_dir} → {'/'.join(_segments(dest_path)) or '(ルート直下)'}")
    for p in others:
        log(f"  送らない（ファイルでもフォルダでもない・リンクのフォルダ）: {p.relative_to(local_dir).as_posix()}")

    root_id = root_id or ensure_root(service)
    folders: dict[str, str] = {"": ensure_path(service, root_id, dest_path)}

    def folder_for(rel: str) -> str:
        if rel not in folders:
            parent, _, name = rel.rpartition("/")
            folders[rel] = ensure_path(service, folder_for(parent), name)
        return folders[rel]

    for d in dirs:
        folder_for(d.relative_to(local_dir).as_posix())

    manifest: list[dict[str, Any]] = []
    for p in files:
        rel = p.relative_to(local_dir).as_posix()
        parent = rel.rpartition("/")[0]
        entry = put(service, p, folder_for(parent))
        entry["path"] = rel
        manifest.append(entry)
        word = {"already": "送信済み", "uploaded": "送信"}[entry["state"]]
        if entry["new_version"]:
            word = "新しい版で送信"
        log(f"  {rel}: {word}（{_human_size(entry['size'])}・md5 一致）")
    uploaded = sum(1 for e in manifest if e["state"] == "uploaded")
    log(f"完了: 送信 {uploaded} 件・送信済み {len(manifest) - uploaded} 件")
    return manifest


def list_tree(service: Any, dest_path: str | Path, *,
              root_id: str | None = None) -> list[dict[str, Any]]:
    """`ルート/dest_path` の下を再帰的に読む。無ければ `PathError`。"""
    root_id = root_id or ensure_root(service)
    base = find_path(service, root_id, dest_path)
    if base is None:
        raise PathError(f"置き場に「{dest_path}」がありません")
    out: list[dict[str, Any]] = []

    def walk(folder_id: str, prefix: str) -> None:
        for f in _find(service, parent=folder_id):
            rel = f"{prefix}{f.get('name', '?')}"
            if f.get("mimeType") == FOLDER_MIME:
                walk(str(f["id"]), rel + "/")
            else:
                out.append({"path": rel, "id": str(f["id"]), "md5": f.get("md5Checksum"),
                            "size": int(f.get("size") or 0)})

    walk(base, "")
    return out


def move(service: Any, src: str | Path, dest: str | Path, *,
         root_id: str | None = None) -> dict[str, Any]:
    """置き場の中の `src` を `dest` へ動かす（名前も変える）。行き先が既にあれば動かさずに止まる。

    Returns:
        {id, from, to, pruned}。pruned は空になってゴミ箱へ入れた元のフォルダ（下から順）。
    """
    root_id = root_id or ensure_root(service)
    src_parts, dest_parts = _segments(src), _segments(dest)
    if not src_parts or not dest_parts:
        raise PathError("置き場のルートそのものは動かせません")
    if dest_parts[:len(src_parts)] == src_parts:
        raise PathError(f"「{dest}」は「{src}」の中です。自分の中へは動かせません")
    src_parent = find_path(service, root_id, "/".join(src_parts[:-1])) if len(src_parts) > 1 else root_id
    found = _find(service, name=src_parts[-1], parent=src_parent) if src_parent else []
    if not found:
        raise PathError(f"置き場に「{src}」がありません")
    if len(found) > 1:
        raise PathError(f"「{src}」が {len(found)} つあります。どれを動かすか決められません")
    dest_parent = ensure_path(service, root_id, "/".join(dest_parts[:-1])) if len(dest_parts) > 1 else root_id
    if _find(service, name=dest_parts[-1], parent=dest_parent):
        raise PathError(f"行き先「{dest}」が既にあります。動かしていません")
    item_id = str(found[0]["id"])
    service.files().update(fileId=item_id, body={"name": dest_parts[-1]}, addParents=dest_parent,
                           removeParents=src_parent, fields="id", supportsAllDrives=True).execute()
    pruned: list[str] = []
    parts = src_parts[:-1]
    while parts:
        folder_id = find_path(service, root_id, "/".join(parts))
        if folder_id is None or _find(service, parent=folder_id):
            break
        service.files().update(fileId=folder_id, body={"trashed": True}, fields="id",
                               supportsAllDrives=True).execute()
        pruned.append("/".join(parts))
        parts = parts[:-1]
    return {"id": item_id, "from": "/".join(src_parts), "to": "/".join(dest_parts), "pruned": pruned}


# --- CLI ---------------------------------------------------------------------


def run_check() -> int:
    """トークンの有無と権限だけを見る。**外には出ない。**"""
    try:
        _, source = load_token_info()
    except GoogleAuthError as e:
        print(f"🚫 {e}", file=sys.stderr)
        return 1
    print(f"✅ 過程の資産のトークン: {source}（drive.file だけ）")
    print(f"   置き場のルート: 印の付いた「{root_name()}」（共有ドライブへ移しても・名前を変えても印で見つける。"
          "無ければ最初の put でマイドライブに作る）")
    return 0


def run_put(local_dir: str, dest: str, manifest_path: str | None) -> int:
    try:
        service = _build_drive()
        manifest = put_tree(service, local_dir, dest)
    except (GoogleAuthError, UploadError, PathError) as e:
        print(f"🚫 {e}", file=sys.stderr)
        return 1
    except ImportError as e:
        print(f"🚫 google-api-python-client が入っていません: {e}", file=sys.stderr)
        return 1
    except _api_error_types() as e:
        print(f"🚫 Drive に書けませんでした: {e}", file=sys.stderr)
        return 1
    text = json.dumps({"root": root_name(), "dest": "/".join(_segments(dest)), "files": manifest},
                      ensure_ascii=False, indent=2)
    if manifest_path:
        Path(manifest_path).write_text(text + "\n", encoding="utf-8")
        print(f"マニフェスト: {manifest_path}", file=sys.stderr)
    else:
        print(text)
    return 0


def run_list(dest: str) -> int:
    try:
        service = _build_drive()
        files = list_tree(service, dest)
    except (GoogleAuthError, PathError) as e:
        print(f"🚫 {e}", file=sys.stderr)
        return 1
    except ImportError as e:
        print(f"🚫 google-api-python-client が入っていません: {e}", file=sys.stderr)
        return 1
    except _api_error_types() as e:
        print(f"🚫 Drive から読めませんでした: {e}", file=sys.stderr)
        return 1
    print(f"置き場「{root_name()}」/ {dest}")
    total = 0
    for f in files:
        total += f["size"]
        print(f"  {f['path']}  {_human_size(f['size'])}  md5 {(f['md5'] or '記録なし')[:8]}")
    print(f"\n  {len(files)} 件・合計 {_human_size(total)}")
    return 0


def run_move(src: str, dest: str) -> int:
    try:
        service = _build_drive()
        done = move(service, src, dest)
    except (GoogleAuthError, PathError) as e:
        print(f"🚫 {e}", file=sys.stderr)
        return 1
    except ImportError as e:
        print(f"🚫 google-api-python-client が入っていません: {e}", file=sys.stderr)
        return 1
    except _api_error_types() as e:
        print(f"🚫 Drive で動かせませんでした: {e}", file=sys.stderr)
        return 1
    print(f"動かした: {done['from']} → {done['to']}")
    for p in done["pruned"]:
        print(f"  空になった「{p}」をゴミ箱へ（Drive のゴミ箱から戻せる）")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="過程の資産を Drive に置く（drive.file）")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("check", help="トークンの有無と権限を確かめる（外に出ない）")
    p_put = sub.add_parser("put", help="フォルダをまるごと送る")
    p_put.add_argument("local_dir", help="送るフォルダ")
    p_put.add_argument("--to", required=True, dest="dest", help="置き場のルートからの行き先（a/b/c）")
    p_put.add_argument("--manifest", default=None, help="マニフェストの書き出し先（既定は標準出力）")
    p_list = sub.add_parser("list", help="置き場の中を読む")
    p_list.add_argument("dest", help="置き場のルートからのパス")
    p_move = sub.add_parser("move", help="置き場の中で動かす・名前を変える")
    p_move.add_argument("src", help="動かす物（置き場のルートからのパス）")
    p_move.add_argument("--to", required=True, dest="dest", help="行き先（置き場のルートからのパス）")
    args = parser.parse_args(argv)
    if args.command == "check":
        return run_check()
    if args.command == "put":
        return run_put(args.local_dir, args.dest, args.manifest)
    if args.command == "list":
        return run_list(args.dest)
    if args.command == "move":
        return run_move(args.src, args.dest)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
