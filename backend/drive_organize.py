"""「動画制作」を整理する（移す・名前を変える・フォルダを作る）。**中身は変えない。消さない。**

2026-10-22 に北原さんが「AI の書く鍵を Drive 全体に広げ、移動と名前の変更を任せる」と決めた。
鍵は Drive 全体（`drive`）に届くので、raw を守る歯止めはこの道具の側に置く。

    python -m backend.drive_organize mv <元> <行き先のフォルダ> [--name 新しい名前] [--apply]
    python -m backend.drive_organize rename <元> <新しい名前> [--apply]
    python -m backend.drive_organize mkdir <親のフォルダ> <名前> [--apply]
    python -m backend.drive_organize hold <箱の中身の名前> [--until 日付] [--apply]   重複した raw を 90_保管 の箱へ

パスは「動画制作」からの相対（`40_完成/20250922_久木田ヒロノブ/…`）。**既定は下見だけ**で、
`--apply` を付けたときだけ Drive を変える。

## 歯止め（どれも破ると何もせずに止まる）

1. 中身を変える口・消す口（ゴミ箱を含む）を持たない。消すのは人
2. 10_raw の中の物は 10_raw の外へ出さない。外の物を 10_raw へ入れない（raw を置くのは人）
3. 10_raw の中のファイルの名前は変えない（カメラの時刻がつなぐ順の手がかり）。
   10_raw の中に作る・名前を変えるフォルダは収録ID の形だけ
4. 「動画制作」と工程のフォルダ（00〜90）そのものは動かさない・名前を変えない。行き先は「動画制作」の中だけ
5. 動かす前後で、中の動画の md5 と大きさが変わっていないことを確かめる
6. 同じ名前の物が行き先にあれば止まる（上書き・取り違えをしない）
7. 変えたことは1行ずつ記録に残す（`--journal`、既定は pipeline_work/drive_ops/journal.jsonl）

## 鍵

`AVS_DRIVE_ORGANIZER_TOKEN_JSON`（クラウド）か backend/data/google/token_drive_organizer.json。
権限が `drive` ちょうどでなければ止まる。作り方は `scripts/google_oauth_login.py --organize`。

終了コード: 0 = できた（下見を含む） ／ 1 = 歯止め・認証・Drive の失敗 ／ 2 = 引数の誤り。
**課金は発生しない**（Drive API は無料）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from backend import drive_layout as dl
from backend.drive_layout import Node
from backend.services.google_oauth import (
    DRIVE_SCOPES,
    ORGANIZER_TOKEN_JSON_ENV,
    GoogleAuthError,
    load_credentials,
    organizer_token_path,
    read_token_info,
    token_scopes,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JOURNAL = REPO_ROOT / "pipeline_work" / "drive_ops" / "journal.jsonl"
LOGIN_HINT = "python scripts/google_oauth_login.py --organize"


class GuardError(RuntimeError):
    """歯止めに当たった。Drive は何も変えていない。"""


# --- 鍵 ----------------------------------------------------------------------


def check_scope(info: Mapping[str, Any]) -> None:
    granted = token_scopes(dict(info))
    if granted != set(DRIVE_SCOPES):
        raise GoogleAuthError(
            f"整理の鍵の権限が drive ちょうどではありません（{', '.join(sorted(granted)) or 'なし'}）。"
            f"何も変えていません。作り直し: {LOGIN_HINT}")


def _build_drive() -> Any:
    info, _, _ = read_token_info(ORGANIZER_TOKEN_JSON_ENV, organizer_token_path())
    check_scope(info)
    from googleapiclient.discovery import build

    credentials = load_credentials(DRIVE_SCOPES, json_env=ORGANIZER_TOKEN_JSON_ENV,
                                   token_file=organizer_token_path())
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


# --- 木の上での判定（Drive は呼ばない） ----------------------------------------


class Tree:
    """読み取った「動画制作」と、決まり。パスで引き、親を辿り、歯止めを判定する。"""

    def __init__(self, root: Node, layout: Mapping[str, Any]):
        self.root = root
        self.layout = layout
        self.parent: dict[str, Node] = {}
        for n in root.walk():
            for c in n.children:
                self.parent[c.id] = n
        self.raw = dl.raw_top(root, layout)
        names = dl.folder_names(layout)
        self.stages = {c.id for c in root.children if c.folder and c.name in names.values()}
        if self.raw is not None:
            self.stages.add(self.raw.id)

    def get(self, rel: str) -> Node:
        rel = rel.strip("/")
        if rel.startswith(self.root.name + "/"):
            rel = rel[len(self.root.name) + 1:]
        want = f"{self.root.path}/{rel}" if rel else self.root.path
        hits = [n for n in self.root.walk() if n.path == want]
        if not hits:
            raise GuardError(f"「{rel}」が {self.root.name} の中にありません")
        if len(hits) > 1:
            raise GuardError(f"「{rel}」が {len(hits)} つあります。どれか決められないので止めます")
        return hits[0]

    def in_raw(self, node: Node) -> bool:
        return self.raw is not None and (node.id == self.raw.id or node.path.startswith(self.raw.path + "/"))

    def videos(self, node: Node) -> dict[str, tuple[str | None, int]]:
        return {n.id: (n.md5, n.size) for n in node.walk() if n.video}

    def _fixed(self, node: Node, verb: str) -> None:
        if node.id == self.root.id or node.id in self.stages:
            raise GuardError(f"「{node.path}」は {self.root.name} か工程のフォルダなので{verb}ません")

    def _name_free(self, folder: Node, name: str) -> None:
        if any(c.name == name for c in folder.children):
            raise GuardError(f"「{folder.path}」に「{name}」が既にあります。上書きしません")

    def check_move(self, src: Node, dest: Node, new_name: str | None) -> None:
        self._fixed(src, "動かせ")
        if not dest.folder:
            raise GuardError(f"行き先「{dest.path}」はフォルダではありません")
        if dest.id == src.id or dest.path.startswith(src.path + "/"):
            raise GuardError("自分の中へは動かせません")
        if self.in_raw(src) and not self.in_raw(dest):
            raise GuardError(f"「{src.path}」は raw です。10_raw の外へは出しません")
        if not self.in_raw(src) and self.in_raw(dest):
            raise GuardError(f"10_raw に入れるのは人です（「{src.path}」は raw の外の物）")
        if new_name is not None:
            self.check_name(src, new_name)
        self._name_free(dest, new_name or src.name)

    def check_name(self, node: Node, new_name: str) -> None:
        self._fixed(node, "名前を変えられ")
        if not new_name or "/" in new_name:
            raise GuardError(f"名前が不正です: {new_name!r}")
        if self.in_raw(node) and new_name != node.name:
            if not node.folder:
                raise GuardError(f"「{node.path}」は撮ったままのファイルです。名前は変えません")
            if not dl.is_recording_id(new_name, self.layout):
                raise GuardError(f"10_raw の中のフォルダは収録ID の名前だけです（{new_name}）")

    def check_mkdir(self, parent: Node, name: str) -> None:
        if not parent.folder:
            raise GuardError(f"「{parent.path}」はフォルダではありません")
        if not name or "/" in name:
            raise GuardError(f"名前が不正です: {name!r}")
        if self.in_raw(parent) and not dl.is_recording_id(name, self.layout):
            raise GuardError(f"10_raw の中に作るフォルダは収録ID の名前だけです（{name}）")
        self._name_free(parent, name)


# --- Drive を変える（歯止めの後でだけ呼ぶ） --------------------------------------


def _journal(path: Path, op: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    op = {"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), **op}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(op, ensure_ascii=False) + "\n")


def _verify(service: Any, before: Mapping[str, tuple[str | None, int]]) -> None:
    for file_id, (md5, size) in before.items():
        got = service.files().get(fileId=file_id, fields="md5Checksum, size",
                                  supportsAllDrives=True).execute()
        if got.get("md5Checksum") != md5 or int(got.get("size") or 0) != size:
            raise GuardError(f"動かした後に md5 か大きさが合いません（id 末尾 {file_id[-4:]}）。止めます")


def move(service: Any, tree: Tree, src: Node, dest: Node, new_name: str | None = None, *,
         apply: bool = False, journal: Path = DEFAULT_JOURNAL) -> str:
    tree.check_move(src, dest, new_name)
    name = new_name or src.name
    line = f"移す: {src.path} → {dest.path}/{name}"
    if not apply:
        return "（下見）" + line
    before = tree.videos(src)
    body = {"name": name} if new_name else {}
    service.files().update(fileId=src.id, body=body, addParents=dest.id,
                           removeParents=tree.parent[src.id].id, fields="id, parents",
                           supportsAllDrives=True).execute()
    _verify(service, before)
    _journal(journal, {"op": "move", "id": src.id, "from": src.path, "to": f"{dest.path}/{name}",
                       "videos": len(before)})
    return line + f"（動画 {len(before)} 本の md5 一致）"


def rename(service: Any, tree: Tree, node: Node, new_name: str, *,
           apply: bool = False, journal: Path = DEFAULT_JOURNAL) -> str:
    tree.check_name(node, new_name)
    tree._name_free(tree.parent[node.id], new_name)
    line = f"名前を変える: {node.path} → {new_name}"
    if not apply:
        return "（下見）" + line
    before = tree.videos(node)
    service.files().update(fileId=node.id, body={"name": new_name}, fields="id, name",
                           supportsAllDrives=True).execute()
    _verify(service, before)
    _journal(journal, {"op": "rename", "id": node.id, "from": node.path, "to": new_name})
    return line


def mkdir(service: Any, tree: Tree, parent: Node, name: str, *,
          apply: bool = False, journal: Path = DEFAULT_JOURNAL) -> str:
    return _mkdir(service, tree, parent, name, apply=apply, journal=journal)[0]


def _mkdir(service: Any, tree: Tree, parent: Node, name: str, *,
           apply: bool, journal: Path) -> tuple[str, str | None]:
    tree.check_mkdir(parent, name)
    line = f"フォルダを作る: {parent.path}/{name}"
    if not apply:
        return "（下見）" + line, None
    made = service.files().create(body={"name": name, "mimeType": dl.FOLDER_MIME, "parents": [parent.id]},
                                  fields="id", supportsAllDrives=True).execute()
    _journal(journal, {"op": "mkdir", "id": made["id"], "path": f"{parent.path}/{name}"})
    return line, made["id"]


def hold(service: Any, tree: Tree, content: str, until: dt.date, *,
         apply: bool = False, journal: Path = DEFAULT_JOURNAL) -> list[str]:
    """`drive_layout.plan_moves` の物を、90_保管 の消す日つきの箱へ移す。"""
    names = dl.folder_names(tree.layout)
    hold_top = dl._top(tree.root, names["hold"])
    if hold_top is None:
        raise GuardError(f"「{names['hold']}」がありません")
    moves = dl.plan_moves(tree.root, tree.layout)
    if not moves:
        return ["90_保管 へ移す重複した raw はありません"]
    box_name = dl.hold_box_name(content, until)
    lines: list[str] = []
    box = next((c for c in hold_top.children if c.folder and c.name == box_name), None)
    if box is None:
        line, made = _mkdir(service, tree, hold_top, box_name, apply=apply, journal=journal)
        lines.append(line)
        box = Node(id=made or "(作る箱)", name=box_name, folder=True, path=f"{hold_top.path}/{box_name}")
    for unit in moves:
        lines.append(move(service, tree, unit, box, apply=apply, journal=journal))
    return lines


# --- CLI ---------------------------------------------------------------------


def _load(env: Mapping[str, str]) -> tuple[Any, Tree]:
    from backend import raw_source

    service = _build_drive()
    raw_id = env.get(raw_source.FOLDER_ENV, "")
    if not raw_id:
        raise LookupError(f"{raw_source.FOLDER_ENV} が未設定です（raw のフォルダの id）")
    got = service.files().get(fileId=raw_id, fields="parents", supportsAllDrives=True).execute()
    base = (got.get("parents") or [None])[0]
    if not base:
        raise LookupError("raw のフォルダの親（動画制作）が見つかりません")
    layout = dl.load_layout()
    return service, Tree(dl.read_tree(service, base, layout["base"]["name"], raw_id), layout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="「動画制作」を整理する（中身は変えない・消さない）")
    parser.add_argument("--apply", action="store_true", help="Drive を変える（無ければ下見だけ）")
    parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL, help="変えたことの記録")
    sub = parser.add_subparsers(dest="command")
    p_mv = sub.add_parser("mv", help="移す（名前も変えられる）")
    p_mv.add_argument("src")
    p_mv.add_argument("dest")
    p_mv.add_argument("--name", default=None)
    p_rn = sub.add_parser("rename", help="名前を変える")
    p_rn.add_argument("src")
    p_rn.add_argument("name")
    p_mk = sub.add_parser("mkdir", help="フォルダを作る")
    p_mk.add_argument("parent")
    p_mk.add_argument("name")
    p_hd = sub.add_parser("hold", help="重複した raw を 90_保管 の箱へ")
    p_hd.add_argument("content", help="箱の中身の名前（例 重複raw_20250922_久木田ヒロノブ）")
    p_hd.add_argument("--until", default=None, help="消す日 YYYY-MM-DD（既定は default_days 日後）")
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    from backend.raw_source import _api_error_types

    try:
        service, tree = _load(os.environ)
        if args.command == "mv":
            lines = [move(service, tree, tree.get(args.src), tree.get(args.dest), args.name,
                          apply=args.apply, journal=args.journal)]
        elif args.command == "rename":
            lines = [rename(service, tree, tree.get(args.src), args.name, apply=args.apply, journal=args.journal)]
        elif args.command == "mkdir":
            lines = [mkdir(service, tree, tree.get(args.parent), args.name, apply=args.apply, journal=args.journal)]
        else:
            days = int(tree.layout["hold_box"]["default_days"])
            until = (dt.date.fromisoformat(args.until) if args.until else
                     dt.datetime.now(dl.JST).date() + dt.timedelta(days=days))
            lines = hold(service, tree, args.content, until, apply=args.apply, journal=args.journal)
    except (GuardError, GoogleAuthError, LookupError, ValueError, ImportError, *_api_error_types()) as e:
        print(f"🚫 {e}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    if not args.apply:
        print("\n下見だけです。変えるときは --apply を付けます")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
