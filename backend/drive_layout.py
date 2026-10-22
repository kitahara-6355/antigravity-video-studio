"""Google Drive の「動画制作」の決まりを点検し、AI が作る側のフォルダを用意する（2026-10-21）。

決まりの正典は `backend/config/drive_layout.json`（北原さん承認の構成案）。手順はスキル `drive-layout`。

    python -m backend.drive_layout check-id 20250922_久木田ヒロノブ   収録ID の形か（外に出ない）
    python -m backend.drive_layout audit [--json 出力]                決まりどおりか（読むだけ）
    python -m backend.drive_layout plan                               重複した raw を 90_保管 へ移す一覧（読むだけ）
    python -m backend.drive_layout prepare [--recording 収録ID]       AI が作る側のフォルダを用意する（書く）
    python -m backend.drive_layout hold <中身の名前> [--until 日付]   90_保管 に消す日つきの箱を作る（書く）
    python -m backend.drive_layout put finished <手元> --to <収録ID>  40_完成 や 00_使い方 へ送る（書く）
    python -m backend.drive_layout qc-record <動画の名前> --by 北原 --on 2026-10-19   目視で確かめた動画を台帳に控える
    python -m backend.drive_layout qc-list                            控えた動画が今も同じ中身か（読むだけ）

## 品質確認の控え（2026-10-22）

人が目視で確かめた動画は、そのときの md5 を `backend/config/qc_ledger.json` に控える。
`audit`・`qc-list` は今の md5 と比べ、中身が差し替わっていれば確認が外れたと知らせる（qc_changed）。
控えと md5 が合う動画は、見直さなくてよい。

## 2つの鍵を使い分ける

- `audit`・`plan` は raw を読む鍵（drive.readonly・`raw_source`）で「動画制作」の全体を読む。何も変えない
- `prepare`・`hold` は資産の鍵（drive.file・`asset_store`）でフォルダを作るだけ。
  drive.file は**アプリが作った物にしか触れない**ので、人が作ったフォルダ（動画制作・10_raw）にも
  raw にも書けない。AI が書くフォルダは AI が「30_AVS_作業」の中に作り、北原さんが「動画制作」へ移す。
  移した後も印（appProperties の `avs_layout`）で見つける
- **ファイルを動かす・消すことはしない。** 重複した raw を 90_保管 へ移すのは北原さん。`plan` はその一覧を出す

## 「動画制作」の見つけ方

raw のフォルダ（`AVS_RAW_DRIVE_FOLDER_ID`。今の「10_raw」）の親。名前は見ない。

終了コード: 0 = 決まりどおり・できた ／ 1 = 決まりと違う所がある・認証や Drive の失敗 ／ 2 = 引数の誤り。
**課金は発生しない**（Drive API は無料）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
LAYOUT_PATH = REPO_ROOT / "backend" / "config" / "drive_layout.json"
QC_LEDGER_PATH = REPO_ROOT / "backend" / "config" / "qc_ledger.json"
FOLDER_MIME = "application/vnd.google-apps.folder"
LAYOUT_MARK = "avs_layout"
JST = ZoneInfo("Asia/Tokyo")
# 「動画制作」の中を読む深さ。収録生動画-…/収録生動画/撮影生データ のような入れ子も届く深さ
MAX_DEPTH = 8


def load_layout(path: Path = LAYOUT_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def folder_names(layout: Mapping[str, Any]) -> dict[str, str]:
    """key → フォルダ名（`raw` → `10_raw` など）。"""
    return {f["key"]: f["name"] for f in layout["folders"]}


# --- 名前の決まり（外に出ない） ----------------------------------------------


def is_recording_id(name: str, layout: Mapping[str, Any]) -> bool:
    m = re.fullmatch(layout["recording_id"]["pattern"], name)
    if not m:
        return False
    try:
        dt.datetime.strptime(m.group(1), "%Y%m%d")
    except ValueError:
        return False
    return m.group(3) is None or int(m.group(3)) >= 2


def forbidden_word(name: str, layout: Mapping[str, Any]) -> str | None:
    """名前に入れない語（最新・テスト中・単独の「新」）が入っていればその語。"""
    rule = layout["forbidden_words"]
    for word in rule["words"]:
        if word in name:
            return word
    for token in rule["tokens"]:
        if re.search(rf"(^|[_\s\-（(]){re.escape(token)}($|[_\s\-）)])", name):
            return token
    return None


def finished_name_ok(name: str, recording: str, layout: Mapping[str, Any]) -> bool:
    pattern = layout["finished_name"]["pattern"].replace("{id}", re.escape(recording))
    return re.fullmatch(pattern, name) is not None


def hold_box_name(content: str, until: dt.date) -> str:
    return f"{until:%Y%m%d}削除予定_{content}"


def hold_box_date(name: str, layout: Mapping[str, Any]) -> dt.date | None:
    m = re.fullmatch(layout["hold_box"]["pattern"], name)
    if not m:
        return None
    try:
        return dt.datetime.strptime(m.group(1), "%Y%m%d").date()
    except ValueError:
        return None


# --- 木（読み取った「動画制作」） --------------------------------------------


@dataclass
class Node:
    id: str
    name: str
    folder: bool
    path: str
    md5: str | None = None
    size: int = 0
    video: bool = False
    children: list[Node] = field(default_factory=list)
    # 根（動画制作）だけが持つ。raw のフォルダの id。名前を変える前（01-input）でも raw と分かる
    raw_id: str | None = None

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


def read_tree(service: Any, base_id: str, base_name: str = "動画制作",
              raw_id: str | None = None) -> Node:
    """`base_id` の下を読む（読むだけ）。ゴミ箱は除く。"""
    from backend.raw_source import _list_files

    root = Node(id=base_id, name=base_name, folder=True, path=base_name, raw_id=raw_id)

    def fill(node: Node, depth: int) -> None:
        query = f"'{node.id}' in parents and trashed = false"
        for f in _list_files(service, query, "id, name, mimeType, size, md5Checksum"):
            is_folder = f.get("mimeType") == FOLDER_MIME
            child = Node(id=str(f["id"]), name=str(f.get("name", "?")), folder=is_folder,
                         path=f"{node.path}/{f.get('name', '?')}", md5=f.get("md5Checksum"),
                         size=int(f.get("size") or 0),
                         video=str(f.get("mimeType", "")).startswith("video/"))
            node.children.append(child)
            if is_folder and depth < MAX_DEPTH:
                fill(child, depth + 1)

    fill(root, 1)
    return root


def _top(root: Node, name: str) -> Node | None:
    hits = [c for c in root.children if c.folder and c.name == name]
    return hits[0] if len(hits) == 1 else None


def raw_top(root: Node, layout: Mapping[str, Any]) -> Node | None:
    """raw のフォルダ。id が分かればそれ（名前を変える前でも）、無ければ名前で。"""
    if root.raw_id:
        return next((c for c in root.children if c.id == root.raw_id), None)
    return _top(root, folder_names(layout)["raw"])


def _inside(node: Node, top: Node | None) -> bool:
    return top is not None and node.path.startswith(top.path + "/")


# --- 点検 --------------------------------------------------------------------


@dataclass
class Finding:
    level: str  # FAIL / WARN
    code: str
    path: str
    message: str


def audit(root: Node, layout: Mapping[str, Any], today: dt.date | None = None) -> list[Finding]:
    """決まりと違う所を挙げる。FAIL は直すまで運用に入らない物、WARN は気づいたら直す物。"""
    today = today or dt.datetime.now(JST).date()
    names = folder_names(layout)
    out: list[Finding] = []

    raw = raw_top(root, layout)
    if raw is not None and raw.name != names["raw"]:
        out.append(Finding("FAIL", "raw_name", raw.path,
                           f"raw のフォルダの名前を「{names['raw']}」に変える（id は変わらないので設定はそのまま）"))
    for key, name in names.items():
        hits = [c for c in root.children if c.folder and c.name == name]
        if key == "raw" and raw is not None:
            hits = [raw]
        if not hits:
            out.append(Finding("FAIL", "missing_folder", f"{root.path}/{name}",
                               f"「{name}」がありません（{_holds(layout, key)}）"))
        elif len(hits) > 1:
            out.append(Finding("FAIL", "two_folders", f"{root.path}/{name}",
                               f"「{name}」が {len(hits)} つあります。1つにしてください"))

    if raw:
        for c in raw.children:
            if c.video:
                out.append(Finding("FAIL", "raw_loose_video", c.path,
                                   f"raw が収録ID のフォルダに入っていません。"
                                   f"「{names['raw']}/<収録ID>/」へ（例 {layout['recording_id']['example']}）"))
            elif c.folder and not is_recording_id(c.name, layout):
                out.append(Finding("FAIL", "raw_bad_id", c.path,
                                   f"「{c.name}」は収録ID の形ではありません（{layout['recording_id']['rule']}）"))

    material = _top(root, names["material"])
    if material:
        shared = next(f.get("shared") for f in layout["folders"] if f["key"] == "material")
        for c in material.children:
            if c.folder and c.name != shared and not is_recording_id(c.name, layout):
                out.append(Finding("WARN", "material_bad_id", c.path,
                                   f"「{c.name}」は「{shared}」でも収録ID でもありません"))

    finished = _top(root, names["finished"])
    if finished:
        for c in finished.children:
            if not c.folder:
                out.append(Finding("WARN", "finished_loose", c.path, "完成動画は収録ID のフォルダに入れる"))
                continue
            if not is_recording_id(c.name, layout):
                out.append(Finding("WARN", "finished_bad_id", c.path, f"「{c.name}」は収録ID の形ではありません"))
                continue
            for f in c.children:
                if f.video and not finished_name_ok(f.name, c.name, layout):
                    out.append(Finding("WARN", "finished_bad_name", f.path,
                                       f"名前は <収録ID>_v<版>_<用途>.mp4（例 {layout['finished_name']['example']}）"))

    hold = _top(root, names["hold"])
    if hold:
        for c in hold.children:
            until = hold_box_date(c.name, layout)
            if until is None:
                out.append(Finding("WARN", "hold_no_date", c.path,
                                   f"消す日が名前にありません（例 {layout['hold_box']['example']}）"))
            elif until < today:
                out.append(Finding("WARN", "hold_overdue", c.path,
                                   f"消す日（{until:%Y-%m-%d}）を過ぎています。消す前に同じ物が 10_raw にあるか確かめる"))

    for node in root.walk():
        if node is root or not node.folder:
            continue
        word = forbidden_word(node.name, layout)
        if word and not _inside(node, _top(root, names["hold"])):
            out.append(Finding("WARN", "forbidden_word", node.path,
                               f"名前に「{word}」を入れない（{layout['forbidden_words']['why']}）"))

    for unit in plan_moves(root, layout):
        count = sum(1 for x in unit.walk() if x.video)
        out.append(Finding("FAIL", "duplicate_raw", unit.path,
                           f"10_raw と同じ動画が {count} 本ある。90_保管 の箱へ移す（python -m backend.drive_layout plan）"))
    for group in duplicate_groups(root, layout):
        if not any(_inside(n, raw) for n in group):
            out.append(Finding("FAIL", "duplicate_unkept", group[0].path,
                               f"同じ動画が {len(group)} か所にあり、10_raw には無い: "
                               + "、".join(n.path for n in group) + "。どれを raw にするか決める"))
    return out


# --- 品質確認の控え -------------------------------------------------------------


def load_qc(path: Path = QC_LEDGER_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"checked": []}
    return json.loads(path.read_text(encoding="utf-8"))


def qc_findings(root: Node, ledger: Mapping[str, Any]) -> list[Finding]:
    """控えた動画が今も同じ中身か。id で探すので、移しても名前を変えても追える。"""
    by_id = {n.id: n for n in root.walk()}
    out: list[Finding] = []
    for e in ledger.get("checked", []):
        node = by_id.get(e["id"])
        if node is None:
            out.append(Finding("WARN", "qc_missing", e["name"],
                               f"{e['checked_on']} に確かめた動画が「{root.name}」の中にありません（消えた・外へ移した）"))
        elif node.md5 != e["md5"]:
            out.append(Finding("FAIL", "qc_changed", node.path,
                               f"{e['checked_on']} に {e['checked_by']} さんが確かめた後に中身が変わっています"
                               f"（md5 {e['md5'][:8]} → {(node.md5 or '?')[:8]}）。確認は外れました。見直しが要ります"))
    return out


def qc_entry(node: Node, by: str, on: dt.date, state: str, note: str = "") -> dict[str, Any]:
    if not node.video or not node.md5:
        raise ValueError(f"「{node.path}」は md5 のある動画ではありません")
    entry = {"id": node.id, "name": node.name, "path": node.path, "md5": node.md5, "size": node.size,
             "state": state, "checked_by": by, "checked_on": on.isoformat()}
    if note:
        entry["note"] = note
    return entry


def _holds(layout: Mapping[str, Any], key: str) -> str:
    return next(f["holds"] for f in layout["folders"] if f["key"] == key)


def duplicate_groups(root: Node, layout: Mapping[str, Any]) -> list[list[Node]]:
    """同じ md5 の動画が2か所以上にある組。90_保管 の中は数えない（消すのを待っている物）。"""
    hold = _top(root, folder_names(layout)["hold"])
    by_md5: dict[str, list[Node]] = defaultdict(list)
    for n in root.walk():
        if n.video and n.md5 and not _inside(n, hold):
            by_md5[n.md5].append(n)
    return [sorted(g, key=lambda n: n.path) for g in by_md5.values() if len(g) > 1]


# --- 重複した raw を 90_保管 へ移す一覧 --------------------------------------


def plan_moves(root: Node, layout: Mapping[str, Any]) -> list[Node]:
    """90_保管 へ移す物（フォルダかファイル）を、北原さんがドラッグする単位で返す。

    10_raw に同じ md5 がある動画を「余分」とし、中身が余分だけのフォルダは一番外側までまとめる。
    「動画制作」直下の工程のフォルダ（00〜90）と「動画制作」そのものは動かさない。
    10_raw に無い動画どうしの重複は、どれを残すか決めないので挙げない（audit が FAIL で知らせる）。
    """
    names = folder_names(layout)
    raw = raw_top(root, layout)
    hold = _top(root, names["hold"])
    keep_md5 = {n.md5 for n in root.walk() if n.video and n.md5 and _inside(n, raw)}
    parent: dict[str, Node] = {}
    for n in root.walk():
        for c in n.children:
            parent[c.id] = n
    tops = {root.id} | {c.id for c in root.children if c.folder and c.name in names.values()}
    if raw is not None:
        tops.add(raw.id)

    memo: dict[str, bool] = {}

    def redundant(n: Node) -> bool:
        if n.id not in memo:
            if n.folder:
                memo[n.id] = all(redundant(c) for c in n.children) and any(
                    not c.folder or redundant(c) for c in n.children)
            else:
                memo[n.id] = n.video and n.md5 in keep_md5
        return memo[n.id]

    picked: dict[str, Node] = {}
    for n in root.walk():
        if not (n.video and n.md5 in keep_md5):
            continue
        if _inside(n, raw) or _inside(n, hold):
            continue
        unit = n
        while parent.get(unit.id) and parent[unit.id].id not in tops and redundant(parent[unit.id]):
            unit = parent[unit.id]
        picked[unit.id] = unit
    return sorted(picked.values(), key=lambda n: n.path)


# --- AI が作る側のフォルダ（drive.file） --------------------------------------


def _find_marked(service: Any, key: str) -> list[dict[str, Any]]:
    response = service.files().list(
        q=(f"trashed = false and mimeType = '{FOLDER_MIME}' and "
           f"appProperties has {{ key='{LAYOUT_MARK}' and value='{key}' }}"),
        fields="files(id, name, parents)", pageSize=10,
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    return response.get("files", [])


def _create_folder(service: Any, name: str, parent: str, key: str | None = None) -> str:
    body: dict[str, Any] = {"name": name, "mimeType": FOLDER_MIME, "parents": [parent]}
    if key:
        body["appProperties"] = {LAYOUT_MARK: key}
    return str(service.files().create(body=body, fields="id", supportsAllDrives=True).execute()["id"])


def _parent_of(service: Any, file_id: str) -> str | None:
    got = service.files().get(fileId=file_id, fields="parents", supportsAllDrives=True).execute()
    parents = got.get("parents") or []
    return str(parents[0]) if parents else None


def ensure_marked_folder(service: Any, key: str, name: str, work_id: str) -> tuple[str, str]:
    """印 `avs_layout=key` の付いたフォルダを返す。無ければ 30_AVS_作業 の中に作る。

    Returns:
        (id, 状態)。状態は created（作った）／ in_work（まだ 30_AVS_作業 の中）／ placed（移してある）。
    """
    from backend.asset_store import PathError

    found = _find_marked(service, key)
    if len(found) > 1:
        raise PathError(f"印の付いた「{name}」が {len(found)} つあります。1つにしてください")
    if not found:
        return _create_folder(service, name, work_id, key), "created"
    folder_id = str(found[0]["id"])
    parents = found[0].get("parents") or []
    return folder_id, ("in_work" if work_id in parents else "placed")


def prepare(service: Any, layout: Mapping[str, Any], recording: str | None = None) -> list[str]:
    """AI が作る側のフォルダ（30_AVS_作業 以外の made_by=ai）を用意し、収録ID の下も作る。"""
    from backend import asset_store

    lines: list[str] = []
    work_id = asset_store.ensure_root(service)
    base_id = _parent_of(service, work_id)
    ids: dict[str, str] = {}
    for f in layout["folders"]:
        if f["made_by"] != "ai" or f["key"] == "work":
            continue
        folder_id, state = ensure_marked_folder(service, f["key"], f["name"], work_id)
        ids[f["key"]] = folder_id
        word = {"created": "作った（30_AVS_作業 の中。動画制作へ移してください）",
                "in_work": "30_AVS_作業 の中にある（動画制作へ移してください）",
                "placed": "置いてある" if base_id is None else "動画制作へ移してある"}[state]
        lines.append(f"  {f['name']}: {word}")
        if f.get("shared"):
            asset_store.ensure_path(service, folder_id, f["shared"])
    if recording:
        if not is_recording_id(recording, layout):
            raise ValueError(f"「{recording}」は収録ID の形ではありません（{layout['recording_id']['rule']}）")
        for f in layout["folders"]:
            if f.get("per_recording") and f["key"] in ids:
                asset_store.ensure_path(service, ids[f["key"]], recording)
                lines.append(f"  {f['name']}/{recording}: 用意した")
        asset_store.ensure_path(service, work_id, f"収録/{recording}")
        lines.append(f"  30_AVS_作業/収録/{recording}: 用意した")
        raw = folder_names(layout)["raw"]
        lines.append(f"  {raw}/{recording}: 人が作るフォルダ（AI は raw に書けない）。北原さんが作って raw を入れる")
    return lines


def make_hold_box(service: Any, layout: Mapping[str, Any], content: str, until: dt.date) -> tuple[str, str]:
    """90_保管 に消す日つきの箱を作る（中身は入れない。入れるのは北原さん）。"""
    from backend import asset_store

    if "/" in content or not content.strip():
        raise ValueError(f"箱の名前が不正です: {content!r}")
    hold = next(f for f in layout["folders"] if f["key"] == "hold")
    work_id = asset_store.ensure_root(service)
    hold_id, _ = ensure_marked_folder(service, "hold", hold["name"], work_id)
    name = hold_box_name(content, until)
    return asset_store.ensure_path(service, hold_id, name), name


def put_to(service: Any, layout: Mapping[str, Any], key: str, local_dir: str | Path,
           sub: str = "") -> list[dict[str, Any]]:
    """AI が書くフォルダ（00_使い方・40_完成）へ送る。30_AVS_作業 は asset_store put を使う。"""
    from backend import asset_store

    spec = next((f for f in layout["folders"] if f["key"] == key), None)
    if spec is None or spec["ai"] != "write" or key == "work":
        allowed = [f["key"] for f in layout["folders"] if f["ai"] == "write" and f["key"] != "work"]
        raise ValueError(f"「{key}」へは送れません（送れるのは {', '.join(allowed)}）")
    work_id = asset_store.ensure_root(service)
    folder_id, _ = ensure_marked_folder(service, key, spec["name"], work_id)
    return asset_store.put_tree(service, local_dir, sub, root_id=folder_id)


# --- CLI ---------------------------------------------------------------------


def _base_id(env: Mapping[str, str]) -> tuple[Any, str, str]:
    from backend import raw_source

    raw_id = env.get(raw_source.FOLDER_ENV, "")
    if not raw_id:
        raise LookupError(f"{raw_source.FOLDER_ENV} が未設定です（raw のフォルダの id）")
    service = raw_source._build_drive()
    got = service.files().get(fileId=raw_id, fields="parents", supportsAllDrives=True).execute()
    parents = got.get("parents") or []
    if not parents:
        raise LookupError("raw のフォルダの親（動画制作）が見つかりません")
    return service, str(parents[0]), raw_id


def _read(env: Mapping[str, str], layout: Mapping[str, Any]) -> Node:
    service, base, raw_id = _base_id(env)
    return read_tree(service, base, layout["base"]["name"], raw_id)


def _errors() -> tuple[type[BaseException], ...]:
    from backend.asset_store import PathError
    from backend.raw_source import _api_error_types
    from backend.services.google_oauth import GoogleAuthError

    return (GoogleAuthError, PathError, LookupError, ValueError, ImportError, *_api_error_types())


def run_audit(env: Mapping[str, str], json_path: str | None) -> int:
    layout = load_layout()
    try:
        root = _read(env, layout)
    except _errors() as e:
        print(f"🚫 {e}", file=sys.stderr)
        return 1
    findings = audit(root, layout) + qc_findings(root, load_qc())
    fails = [f for f in findings if f.level == "FAIL"]
    for f in findings:
        print(f"{'❌' if f.level == 'FAIL' else '⚠️ '} [{f.code}] {f.path}\n     {f.message}")
    print(f"\n{root.name}: FAIL {len(fails)} 件・WARN {len(findings) - len(fails)} 件")
    if json_path:
        Path(json_path).write_text(json.dumps([f.__dict__ for f in findings], ensure_ascii=False, indent=2) + "\n",
                                   encoding="utf-8")
    return 1 if fails else 0


def run_plan(env: Mapping[str, str]) -> int:
    layout = load_layout()
    try:
        root = _read(env, layout)
    except _errors() as e:
        print(f"🚫 {e}", file=sys.stderr)
        return 1
    moves = plan_moves(root, layout)
    hold = folder_names(layout)["hold"]
    if not moves:
        print("90_保管 へ移す重複した raw はありません")
        return 0
    print(f"{hold} の箱へ移す物（{len(moves)} 件。動かすのは人。AI は raw を動かせない）:")
    for n in moves:
        count = sum(1 for x in n.walk() if x.video)
        size = sum(x.size for x in n.walk() if x.video) / 1e6
        print(f"  {n.path}  （動画 {count} 本・{size:,.1f} MB・全部 10_raw と同じ md5）")
    return 0


def run_prepare(recording: str | None) -> int:
    from backend import asset_store

    layout = load_layout()
    try:
        service = asset_store._build_drive()
        lines = prepare(service, layout, recording)
    except _errors() as e:
        print(f"🚫 {e}", file=sys.stderr)
        return 1
    print("AI が作る側のフォルダ:")
    print("\n".join(lines))
    return 0


def run_hold(content: str, until: str | None) -> int:
    from backend import asset_store

    layout = load_layout()
    try:
        day = (dt.date.fromisoformat(until) if until else
               dt.datetime.now(JST).date() + dt.timedelta(days=int(layout["hold_box"]["default_days"])))
        service = asset_store._build_drive()
        _, name = make_hold_box(service, layout, content, day)
    except _errors() as e:
        print(f"🚫 {e}", file=sys.stderr)
        return 1
    print(f"90_保管/{name}: 用意した（中身を入れるのは人）")
    return 0


def run_put(key: str, local_dir: str, sub: str) -> int:
    from backend import asset_store

    layout = load_layout()
    try:
        service = asset_store._build_drive()
        manifest = put_to(service, layout, key, local_dir, sub)
    except (*_errors(), asset_store.UploadError) as e:
        print(f"🚫 {e}", file=sys.stderr)
        return 1
    print(json.dumps({"folder": folder_names(layout)[key], "dest": sub, "files": manifest},
                     ensure_ascii=False, indent=2))
    return 0


def _find_video(root: Node, name: str) -> Node:
    hits = [n for n in root.walk() if n.video and (n.name == name or n.id == name)]
    if not hits:
        raise LookupError(f"動画「{name}」が見つかりません")
    if len(hits) > 1:
        raise LookupError(f"「{name}」が {len(hits)} か所にあります: " + "、".join(n.path for n in hits)
                          + "。id で指定してください")
    return hits[0]


def run_qc_record(env: Mapping[str, str], name: str, by: str, on: str, state: str, note: str) -> int:
    layout = load_layout()
    try:
        node = _find_video(_read(env, layout), name)
        entry = qc_entry(node, by, dt.date.fromisoformat(on), state, note)
    except _errors() as e:
        print(f"🚫 {e}", file=sys.stderr)
        return 1
    ledger = load_qc()
    ledger["checked"] = [e for e in ledger.get("checked", []) if e["id"] != entry["id"]] + [entry]
    QC_LEDGER_PATH.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"控えた: {node.path}（md5 {entry['md5'][:8]}・{state}・{by}・{on}）")
    return 0


def run_qc_list(env: Mapping[str, str]) -> int:
    layout = load_layout()
    try:
        root = _read(env, layout)
    except _errors() as e:
        print(f"🚫 {e}", file=sys.stderr)
        return 1
    ledger = load_qc()
    bad = {f.path: f for f in qc_findings(root, ledger)}
    by_id = {n.id: n for n in root.walk()}
    for e in ledger.get("checked", []):
        node = by_id.get(e["id"])
        where = node.path if node else e["name"]
        mark = "❌" if where in bad and bad[where].level == "FAIL" else ("⚠️ " if where in bad else "✅")
        print(f"{mark} {where}  {e['state']}・{e['checked_by']}・{e['checked_on']}")
    fails = [f for f in bad.values() if f.level == "FAIL"]
    print(f"\n控え {len(ledger.get('checked', []))} 件・確認が外れた {len(fails)} 件")
    return 1 if fails else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Drive の「動画制作」の決まりを点検する・フォルダを用意する")
    sub = parser.add_subparsers(dest="command")
    p_id = sub.add_parser("check-id", help="収録ID の形か（外に出ない）")
    p_id.add_argument("name")
    p_audit = sub.add_parser("audit", help="決まりどおりか（読むだけ）")
    p_audit.add_argument("--json", default=None, help="結果の JSON の書き出し先")
    sub.add_parser("plan", help="重複した raw を 90_保管 へ移す一覧（読むだけ）")
    p_prep = sub.add_parser("prepare", help="AI が作る側のフォルダを用意する")
    p_prep.add_argument("--recording", default=None, help="収録ID（20_素材・40_完成・30_AVS_作業/収録 の下を作る）")
    p_hold = sub.add_parser("hold", help="90_保管 に消す日つきの箱を作る")
    p_hold.add_argument("content", help="中身の名前（例 重複raw_20250922_久木田ヒロノブ）")
    p_hold.add_argument("--until", default=None, help="消す日 YYYY-MM-DD（既定は今日から default_days 日後）")
    p_put = sub.add_parser("put", help="00_使い方・40_完成 へ送る")
    p_put.add_argument("key", help="guide（00_使い方）か finished（40_完成）")
    p_put.add_argument("local_dir", help="送るフォルダ")
    p_put.add_argument("--to", default="", dest="sub", help="その中の行き先（例 収録ID）")
    p_qc = sub.add_parser("qc-record", help="目視で確かめた動画を台帳に控える（md5 を記録）")
    p_qc.add_argument("name", help="動画の名前か id（動画制作の中で1つに決まること）")
    p_qc.add_argument("--by", required=True, help="確かめた人")
    p_qc.add_argument("--on", required=True, help="確かめた日 YYYY-MM-DD")
    p_qc.add_argument("--state", default="目視OK", help="目視OK（既定）か 要直し")
    p_qc.add_argument("--note", default="", help="メモ")
    sub.add_parser("qc-list", help="控えた動画が今も同じ中身か（読むだけ）")
    args = parser.parse_args(argv)
    if args.command == "check-id":
        layout = load_layout()
        ok = is_recording_id(args.name, layout)
        word = forbidden_word(args.name, layout)
        if ok and not word:
            print(f"✅ 「{args.name}」は収録ID の形です")
            return 0
        reason = f"「{word}」を入れない" if word else layout["recording_id"]["rule"]
        print(f"❌ 「{args.name}」は収録ID にできません（{reason}。例 {layout['recording_id']['example']}）")
        return 1
    if args.command == "audit":
        return run_audit(os.environ, args.json)
    if args.command == "plan":
        return run_plan(os.environ)
    if args.command == "prepare":
        return run_prepare(args.recording)
    if args.command == "hold":
        return run_hold(args.content, args.until)
    if args.command == "put":
        return run_put(args.key, args.local_dir, args.sub)
    if args.command == "qc-record":
        return run_qc_record(os.environ, args.name, args.by, args.on, args.state, args.note)
    if args.command == "qc-list":
        return run_qc_list(os.environ)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
