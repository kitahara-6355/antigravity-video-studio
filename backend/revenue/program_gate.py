"""番組化の承認の門 — **承認していない仕上げ版・Shorts・サムネは、置き場（Drive の 40_完成）に出ない**（V2・2026-11-10）。

本線の門（`approval_gate`・R2）は `vault-outputs/final`・`shorts` を守る。10月にできた番組化の道具
（`backend/program_package/` の episode・shorts・thumbnail）は本線の外にあり、出力は
`drive_layout put finished` で Drive の「40_完成」へ送る。ここがその門（D-16・D-07・D-48）。

## 流れ（1本ごと。Shorts は切り出し1本が1件）

    提案    python -m backend.revenue.program_gate propose --recording <収録ID> --kind short --key S1 \\
                --publish <投稿する mp4> [--review <確認用の縮小版>] [--spec <指定ファイル>]
            → 実測の品質ゲート（`program_quality`）に通ったものだけが「承認待ち」になる
    見せる  確認用・候補のフォルダへ送る（`drive_layout put finished <フォルダ> --to "<収録ID>/Shorts候補_<案>"`）
    承認    python -m backend.revenue.program_gate approve --recording <収録ID> --key S1 \\
                --by 北原 --synthetic no --evidence "チャット 2026-11-12「S1 と S5 を出す」"
            （Drive のラベル「品質確認」が付いた確認用があるなら --from-qc）
    置く    drive_layout put finished <フォルダ> --to "<収録ID>/Shorts_投稿用"
            → **承認済みの中身（指紋が一致）だけが通る。**1つでも未承認があれば何も送らない
    点検    python -m backend.revenue.program_gate gate [--tree <控え>]
            → 40_完成 にある動画と画像が、1つ残らず承認（か門の前からの基準線）に辿れるか

## 2つの棚

40_完成 には「見てもらう物」と「投稿する物」が並ぶ。**見てもらう物は承認の材料なので止めない**
（本線の門でプレビューを止めないのと同じ）。名前か、収録ID より下のフォルダ名に
`確認用`・`候補`・`見本` の印があれば見てもらう物（印は `_` で区切った語として見る。
話題に字が入っただけの名前は数えない — `_has_mark`）。**それ以外の動画と画像はすべて投稿する物**で、
承認に辿れなければ置けない。入れ物（拡張子）は列挙しない — Drive が動画・画像と見る物すべてを問う。

## 守ること

- **AI は承認しない**（憲法第4条）。`--by` は台帳の `approvers`（人の名前）だけが通る。既定値で埋めない。
  チャットの承認を Claude が控えるときは、いつ・どの言葉で承認されたかを `--evidence` に書く
- 承認は中身に結びつく（sha256 と md5）。提案し直す（中身が変わる）と承認は外れ、前の承認は履歴に残る
- 合成メディアを含むか（開示）は人が決める。省けない
- 台帳は `backend/config/program_approvals.json`。コンテナは消えるので、承認はリポジトリに残す

終了コード: 0 = できた・緑 ／ 1 = 断った・赤・見られなかった ／ 2 = 引数の誤り。**課金は発生しない。**
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from backend.revenue import program_quality

LEDGER_PATH = Path(__file__).resolve().parent.parent / "config" / "program_approvals.json"
KINDS = program_quality.KINDS
WAITING, APPROVED = "承認待ち", "承認済み"
# 画像と動画（置き場で問う物）。手元のファイルは拡張子でしか種類が分からないので、
# **外す側（付属物）を列挙する** — 知らない拡張子は問う側に倒す
COMPANION_EXT = {".txt", ".md", ".json", ".srt", ".vtt", ".ass", ".csv", ".html", ".pdf"}


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def fingerprint(path: str | Path) -> dict[str, Any]:
    """中身の指紋。Drive は md5 を返すので、手元の sha256 と両方控える。"""
    p = Path(path)
    sha, md5 = hashlib.sha256(), hashlib.md5()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            sha.update(chunk)
            md5.update(chunk)
    return {"name": p.name, "sha256": sha.hexdigest(), "md5": md5.hexdigest(), "size": p.stat().st_size}


def load(path: str | Path | None = None) -> dict:
    path = Path(path or LEDGER_PATH)
    if not path.is_file():
        return {"approvers": [], "review_marks": ["確認用", "候補", "見本"], "baseline": [], "items": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save(ledger: Mapping[str, Any], path: str | Path | None = None) -> None:
    Path(path or LEDGER_PATH).write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def find(ledger: Mapping[str, Any], recording: str, key: str) -> dict | None:
    return next((i for i in ledger.get("items", [])
                 if i["recording"] == recording and i["key"] == key), None)


# --- 提案 ---------------------------------------------------------------------


def propose(ledger: dict, *, recording: str, kind: str, key: str, publish: str | Path,
            review: str | Path | None = None, spec: str | Path | None = None,
            by: str = "claude-code", note: str = "", quality_cfg: dict | None = None) -> dict:
    """1件を「承認待ち」にする。**実測の品質ゲートに通らなければ提案にならない。**

    同じ（収録ID・キー）を出し直すと、前の提案と承認は履歴へ移る（消さない）。
    中身が同じ出し直しは何も変えない（承認も残る）。
    """
    if kind not in KINDS:
        raise ValueError(f"種類は {'・'.join(KINDS)} のどれか: {kind}")
    report = program_quality.measure(kind, publish, cfg=quality_cfg)
    reports = [dict(report, role="publish")]
    if review:
        reports.append(dict(program_quality.measure(kind, review, review=True, cfg=quality_cfg), role="review"))
    bad = [r for r in reports if not r["passed"]]
    if bad:
        lines = [ln for r in bad for ln in program_quality.format_report(r)]
        raise QualityError("品質ゲートが不合格なので、提案にしません（直して出し直す）:\n" + "\n".join(lines), reports)
    if review and kind != "thumbnail":
        # 確認用は「同じ書き出しの縮小版」でなければ承認の材料にならない。前の版の確認用を付けたまま
        # 提案すると、人が見ていない投稿版に目視OK の承認が付く（gate-verifier 1 周目の反例 2）
        secs = [next((c["value"] for c in r["checks"] if c["id"] == "duration"), None) for r in reports]
        limit = (quality_cfg or program_quality.load_config())["video"].get("review_gap_max_seconds", 1.0)
        if None in secs or abs(secs[0] - secs[1]) > limit:
            raise QualityError(
                f"確認用と投稿する物の長さが合いません（{secs[0]}秒 と {secs[1]}秒・差は {limit}秒まで）。"
                "同じ書き出しの確認用を付けてください（前の版の確認用では承認の材料になりません）", reports)

    files = [dict(fingerprint(publish), role="publish")]
    if review:
        files.append(dict(fingerprint(review), role="review"))
    old = find(ledger, recording, key)
    if old and [(f["role"], f["sha256"]) for f in old["files"]] == [(f["role"], f["sha256"]) for f in files]:
        return old
    item = {
        "recording": recording, "kind": kind, "key": key, "state": WAITING,
        "files": files,
        "spec": ({"path": str(spec), "sha256": fingerprint(spec)["sha256"]} if spec else None),
        "quality": [{"role": r["role"], "file": r["file"], "passed": r["passed"], "checks": r["checks"]}
                    for r in reports],
        "proposed_at": _now(), "proposed_by": by, "note": note,
        "approval": None, "history": [],
    }
    if old:
        item["history"] = list(old.get("history", [])) + [
            {k: old.get(k) for k in ("state", "files", "proposed_at", "approval")}]
        ledger["items"][ledger["items"].index(old)] = item
    else:
        ledger.setdefault("items", []).append(item)
    return item


class QualityError(ValueError):
    def __init__(self, message: str, reports: list[dict]):
        super().__init__(message)
        self.reports = reports


# --- 承認 ---------------------------------------------------------------------


def approve(ledger: dict, *, recording: str, key: str, by: str, synthetic: bool | None,
            evidence: str, on: str | None = None, note: str = "") -> dict:
    """人が見て決めたことを控える。**AI の名前では承認できない。**"""
    item = find(ledger, recording, key)
    if item is None:
        raise LookupError(f"提案がありません: {recording} / {key}（先に propose）")
    by = (by or "").strip()
    approvers = ledger.get("approvers", [])
    if by not in approvers:
        raise ValueError(f"承認できるのは {'・'.join(approvers) or '(台帳に approvers がありません)'} だけです: 「{by}」"
                         "（AI は承認しない。自分の書き出しを自分で通さない — 憲法第4条）")
    if not isinstance(synthetic, bool):
        raise ValueError("合成メディアを含むかを人が決めてください（--synthetic yes|no）。機械は決めません")
    if not (evidence or "").strip():
        raise ValueError("どこで承認されたかを --evidence に書いてください（チャットの日時と言葉、ラベルなど）")
    if item["state"] == APPROVED:
        raise ValueError(f"すでに承認されています: {recording} / {key}（{item['approval']['by']}・{item['approval']['on']}）")
    now = _now()
    item["approval"] = {
        "by": by, "on": on or dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat(),
        "recorded_at": now, "evidence": evidence.strip(), "note": note,
        "files_sha256": [f["sha256"] for f in item["files"]],
        "ai_disclosure": {"contains_synthetic_media": synthetic, "decided_by": by, "decided_at": now,
                          # 番組化の道具は AI を呼ばない（切る・重ねる・並べるだけ）
                          "ai_used_for": []},
    }
    item["state"] = APPROVED
    return item


def approve_from_qc(ledger: dict, qc: Mapping[str, Any], *, recording: str, key: str,
                    synthetic: bool | None) -> dict:
    """Drive のラベル「品質確認」（`qc_ledger.json`）の目視OK を承認として控える。

    確認用（か投稿する物）の md5 が、目視OK の控えの md5 と一致するときだけ。
    """
    item = find(ledger, recording, key)
    if item is None:
        raise LookupError(f"提案がありません: {recording} / {key}（先に propose）")
    by_md5 = {e["md5"]: e for e in qc.get("checked", []) if e.get("state") == "目視OK"}
    hit = next((by_md5[f["md5"]] for f in item["files"] if f["md5"] in by_md5), None)
    if hit is None:
        raise LookupError("ラベル「品質確認」が目視OK の控えに、この提案の中身と同じ動画がありません"
                          "（python -m backend.drive_layout qc-sync で控えを新しくする）")
    jst = dt.timezone(dt.timedelta(hours=9))
    proposed_on = dt.datetime.fromisoformat(item["proposed_at"]).astimezone(jst).date().isoformat()
    publish_md5 = {f["md5"] for f in item["files"] if f["role"] == "publish"}
    if hit["md5"] not in publish_md5 and str(hit.get("checked_on") or "") < proposed_on:
        # 投稿する物そのものを見た目視OK なら日付は問わない。確認用を見た目視OK は、この提案より前の物を数えない
        raise LookupError(f"目視OK（{hit.get('checked_on')}）が、この提案（{proposed_on}）より前です。"
                          "前の版を見たときの目視OK は使えません。北原さんに今の確認用を見てもらってください")
    return approve(ledger, recording=recording, key=key, by=hit["checked_by"], synthetic=synthetic,
                   on=hit["checked_on"], evidence=f"Drive のラベル「品質確認」目視OK（{hit['name']}・id {hit['id']}）")


# --- 置き場の規則 ---------------------------------------------------------------


def _has_mark(name: str, marks: Iterable[str], *, folder: bool) -> bool:
    """名前に「見てもらう物」の印があるか。**印は `_` で区切った語として見る**（部分一致にしない）。

    話題から付けた名前（`S11_選挙の候補者.mp4`）に印の字がたまたま入っても、見てもらう物にしない。
    - ファイル: 区切った語が印そのもの。画質の添え字だけ許す（`…_確認用.mp4`・`…_確認用360p.mp4`）
    - フォルダ: 区切った語が印で終わる（`Shorts候補_I_…`・`番組化の見本`）
    """
    stem = name if folder else (name.rsplit(".", 1)[0] if "." in name else name)
    for token in stem.split("_"):
        for m in marks:
            if token == m or (folder and token.endswith(m)):
                return True
            if not folder and token.startswith(m) and re.fullmatch(r"\d{3,4}p", token[len(m):]):
                return True
    return False


def is_review(parts: Iterable[str], ledger: Mapping[str, Any]) -> bool:
    """見てもらう物か。`parts` は収録ID より下のフォルダ名と、最後にファイル名。"""
    parts = list(parts)
    marks = ledger.get("review_marks", [])
    return any(_has_mark(p, marks, folder=i < len(parts) - 1) for i, p in enumerate(parts))


def approved_files(ledger: Mapping[str, Any], recording: str) -> list[dict]:
    """その収録の、承認済みの「投稿する物」の指紋。承認の後に提案の中身が変わっていたら数えない。"""
    out = []
    for i in ledger.get("items", []):
        if i["recording"] != recording or i["state"] != APPROVED or not i.get("approval"):
            continue
        if i["approval"].get("files_sha256") != [f["sha256"] for f in i["files"]]:
            continue
        out += [dict(f, key=i["key"]) for f in i["files"] if f["role"] == "publish"]
    return out


def put_problems(local_dir: str | Path, dest: str, ledger: Mapping[str, Any] | None = None) -> list[str]:
    """`drive_layout put finished <local_dir> --to <dest>` で送ってよいか。断る理由を全部返す。

    見てもらう物（名前か行き先のフォルダ名に 確認用・候補・見本）と付属物（文章・字幕など）は通す。
    それ以外は、承認済みの「投稿する物」と sha256 が一致するときだけ通す。
    """
    ledger = load() if ledger is None else ledger
    local_dir = Path(local_dir)
    segs = [s for s in str(dest).replace("\\", "/").split("/") if s]
    recording, below = (segs[0] if segs else ""), segs[1:]
    problems = []
    approved = {f["sha256"]: f for f in approved_files(ledger, recording)}
    for p in sorted(x for x in local_dir.rglob("*") if x.is_file()):
        rel = p.relative_to(local_dir).as_posix()
        if p.suffix.lower() in COMPANION_EXT or is_review([*below, *rel.split("/")], ledger):
            continue
        if not recording:
            problems.append(f"{rel}: 行き先に収録ID がありません（--to \"<収録ID>/…\"）。承認を確かめられないので送りません")
        elif (sha := fingerprint(p)["sha256"]) not in approved:
            waiting = [i["key"] for i in ledger.get("items", [])
                       if i["recording"] == recording and i["state"] == WAITING
                       and any(f["sha256"] == sha for f in i["files"])]
            hint = (f"（{'・'.join(waiting)} は承認待ち。北原さんの承認を approve で控えてから）" if waiting
                    else "（承認済みの中身と一致しません。propose → 承認 → approve の後に送る。"
                         "見てもらうだけなら、名前か行き先に 確認用・候補 を入れる）")
            problems.append(f"{rel}: **承認していない物は置き場に出せません**{hint}")
    return problems


# --- 置き場（Drive の 40_完成）の点検 ----------------------------------------------


def finished_name(layout: Mapping[str, Any]) -> str:
    return next(f["name"] for f in layout["folders"] if f["key"] == "finished")


def node_problem(node: Any, path: str, layout: Mapping[str, Any], ledger: Mapping[str, Any]) -> dict | None:
    """`path`（`動画制作/40_完成/<収録ID>/…/名前`）に `node` があるとして、置いてよいか。だめなら理由。

    点検（今ある場所）にも、移す・名前を変える前の下見（行き先の場所）にも使う。
    """
    parts = path.split("/")
    if node.folder or not (node.video or getattr(node, "image", False)):
        return None
    if len(parts) < 3 or parts[1] != finished_name(layout):
        return None                                   # 40_完成 の外は、この門の守る場所ではない
    rest = parts[2:]                                  # [収録ID, …, 名前]（収録ID の外に直に置いた物は [名前]）
    recording, below = (rest[0], rest[1:]) if len(rest) > 1 else ("", rest)
    if is_review(below, ledger):
        return None
    b = next((x for x in ledger.get("baseline", []) if x["id"] == node.id), None)
    if b is not None:
        same = (b.get("size") == node.size
                and (not b.get("md5") or not node.md5 or b["md5"] == node.md5))
        return None if same else {
            "code": "baseline_changed", "path": path,
            "message": "門ができる前からあった物ですが、中身が変わっています（新しい物として承認が要る）"}
    if not node.md5:
        return {"code": "unreadable", "path": path,
                "message": "中身の指紋（md5）が読めないので、承認に辿れるか確かめられません"}
    if node.md5 not in {f["md5"] for f in approved_files(ledger, recording)}:
        return {"code": "unapproved", "path": path,
                "message": "**承認に辿れない物**です（投稿する棚に置けるのは承認済みだけ。"
                           "見てもらう物なら名前かフォルダ名に 確認用・候補 を入れる）"}
    return None


def drive_findings(root: Any, layout: Mapping[str, Any], ledger: Mapping[str, Any] | None = None) -> list[dict]:
    """40_完成 にある動画と画像が、1つ残らず承認（か基準線）に辿れるか。辿れない物を返す。"""
    ledger = load() if ledger is None else ledger
    name = finished_name(layout)
    top = next((c for c in root.children if c.folder and c.name == name), None)
    if top is None:
        return [{"code": "no_shelf", "path": f"{root.path}/{name}", "message": f"「{name}」がありません（見ていない）"}]
    return [f for f in (node_problem(n, n.path, layout, ledger) for n in top.walk()) if f]


def move_problems(node: Any, path_after: str, layout: Mapping[str, Any],
                  ledger: Mapping[str, Any] | None = None) -> list[dict]:
    """`node`（ファイルかフォルダ）を `path_after` へ移す・その名前に変えるとき、投稿する棚に出てしまう未承認の物。

    見てもらう棚から投稿する棚へ移す、名前から「確認用」を外す、も「置き場に出す」と同じなので問う。
    """
    ledger = load() if ledger is None else ledger
    out = []
    for n in node.walk():
        f = node_problem(n, path_after + n.path[len(node.path):], layout, ledger)
        if f:
            out.append(f)
    return out


def tree_from_json(data: Mapping[str, Any], path: str = "") -> Any:
    """控え（`snapshot` の出力）から木を作る。"""
    from backend.drive_layout import Node

    here = f"{path}/{data['name']}" if path else data["name"]
    folder = bool(data.get("folder"))
    video, image = data.get("video"), data.get("image")
    if not folder and video is None and image is None:
        # 種類の印が無い控え（手で組んだ控えなど）は、名前から推す。**付属物と分かる物だけを外し、
        # あとは問う側に倒す** — 印の書き忘れで未承認の動画が緑になるのを防ぐ（反例 3）
        video = _asked_by_name(data["name"])
    node = Node(id=str(data.get("id", "")), name=data["name"], folder=folder, path=here,
                md5=data.get("md5"), size=int(data.get("size") or 0), video=bool(video), image=bool(image))
    node.children = [tree_from_json(c, here) for c in data.get("children", [])]
    return node


def _asked_by_name(name: str) -> bool:
    """種類の印が無いファイルを、名前だけで「問う物」と見るか。拡張子の無い物（Google ドキュメントなど）と付属物は外す。"""
    suffix = Path(name).suffix.lower()
    return bool(suffix) and suffix not in COMPANION_EXT


def tree_to_json(node: Any) -> dict:
    d: dict[str, Any] = {"id": node.id, "name": node.name}
    if node.folder:
        d["folder"] = True
        d["children"] = [tree_to_json(c) for c in node.children]
    else:
        d.update({k: v for k, v in (("size", node.size), ("md5", node.md5)) if v})
        # 種類は「違う」も書く（書かないと、読み戻すときに名前から推すことになる）
        d.update({"video": bool(node.video), "image": bool(getattr(node, "image", False))})
    return d


def _read_drive(env: Mapping[str, str]) -> tuple[Any, dict]:
    from backend import drive_layout

    layout = drive_layout.load_layout()
    return drive_layout._read(env, layout), layout


# --- 表示 ---------------------------------------------------------------------


def trace(item: Mapping[str, Any]) -> list[str]:
    lines = [f"番組化の承認の証跡: {item['recording']} / {item['key']}（{item['kind']}）", "", "■ 提案",
             f"  出した時刻: {item['proposed_at']}（{item['proposed_by']}）"]
    for f in item["files"]:
        role = "投稿する物" if f["role"] == "publish" else "確認用"
        lines.append(f"  {role}: {f['name']}（sha256 {f['sha256'][:12]}・md5 {f['md5'][:8]}・{f['size']:,} バイト）")
    if item.get("spec"):
        lines.append(f"  指定ファイル: {item['spec']['path']}（sha256 {item['spec']['sha256'][:12]}）")
    lines.append("■ 品質ゲート（実測）")
    for q in item.get("quality", []):
        lines += ["  " + ln for ln in program_quality.format_report(
            {"kind": item["kind"], "review": q["role"] == "review", **q})]
    lines.append("■ 承認")
    a = item.get("approval")
    if not a:
        lines.append("  承認されていません（承認待ち）")
    else:
        d = a["ai_disclosure"]
        lines += [f"  承認した人: {a['by']}（{a['on']}）", f"  根拠      : {a['evidence']}",
                  (f"  開示      : 合成メディアを含む = {'はい' if d['contains_synthetic_media'] else 'いいえ'}"
                   f"（{d['decided_by']} が決めた）・AI を使った工程 なし")]
        if a.get("note"):
            lines.append(f"  メモ      : {a['note']}")
    for h in item.get("history", []):
        ha = h.get("approval") or {}
        lines.append(f"  （前の提案 {h.get('proposed_at')}: {h.get('state')}"
                     + (f"・{ha.get('by')} {ha.get('on')}" if ha else "") + "）")
    return lines


def summary(ledger: Mapping[str, Any]) -> list[str]:
    lines = []
    for i in ledger.get("items", []):
        a = i.get("approval") or {}
        tail = f"{a.get('by')}・{a.get('on')}" if a else "北原さんの承認を待っています"
        lines.append(f"  {'✅' if i['state'] == APPROVED else '⏳'} {i['recording']} / {i['key']}（{i['kind']}）"
                     f" {i['state']} — {tail}")
    return lines or ["  （提案はまだありません）"]


# --- CLI ----------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="番組化の承認の門 — 承認していない仕上げ版・Shorts・サムネは置き場に出ない")
    p.add_argument("--ledger", default=None, help="台帳（既定 backend/config/program_approvals.json）")
    sub = p.add_subparsers(dest="command")
    s = sub.add_parser("propose", help="実測の品質ゲートに通して「承認待ち」にする")
    s.add_argument("--recording", required=True)
    s.add_argument("--kind", required=True, choices=KINDS)
    s.add_argument("--key", required=True, help="版や切り出しの名前（v67・S1・サムネ_P1 など）")
    s.add_argument("--publish", required=True, help="投稿する物")
    s.add_argument("--review", default=None, help="確認用の縮小版（あれば）")
    s.add_argument("--spec", default=None, help="元にした指定ファイル")
    s.add_argument("--note", default="")
    s = sub.add_parser("approve", help="人の承認を控える")
    s.add_argument("--recording", required=True)
    s.add_argument("--key", required=True)
    s.add_argument("--by", default=None, help="承認した人（台帳の approvers。**既定値で埋めない**）")
    s.add_argument("--on", default=None, help="承認した日 YYYY-MM-DD（既定は今日）")
    s.add_argument("--synthetic", choices=("yes", "no"), help="合成メディアを含むか（人が決める。必須）")
    s.add_argument("--evidence", default="", help="どこで承認されたか（チャットの日時と言葉など）")
    s.add_argument("--from-qc", action="store_true", help="Drive のラベル「品質確認」の目視OK を承認として控える")
    s.add_argument("--note", default="")
    sub.add_parser("list", help="提案と承認の一覧")
    s = sub.add_parser("trace", help="1件の証跡（提案・実測・承認）")
    s.add_argument("--recording", required=True)
    s.add_argument("--key", required=True)
    s = sub.add_parser("check-put", help="送ってよいか下見する（送らない）")
    s.add_argument("local_dir")
    s.add_argument("--to", required=True, dest="dest")
    s = sub.add_parser("gate", help="40_完成 の動画と画像が1つ残らず承認に辿れるか")
    s.add_argument("--tree", default=None, help="Drive の控え（snapshot の出力）。無ければ Drive を読む")
    s = sub.add_parser("snapshot", help="Drive の「動画制作」の今の姿を控える（読むだけ）")
    s.add_argument("--out", required=True)
    a = p.parse_args(argv)
    ledger = load(a.ledger)

    if a.command == "propose":
        try:
            item = propose(ledger, recording=a.recording, kind=a.kind, key=a.key, publish=a.publish,
                           review=a.review, spec=a.spec, note=a.note)
        except (ValueError, OSError) as e:
            print(f"🚫 {e}")
            return 1
        save(ledger, a.ledger)
        print(f"⏳ 提案しました: {a.recording} / {a.key} — {item['state']}")
        for q in item["quality"]:
            print("\n".join("  " + ln for ln in program_quality.format_report(
                {"kind": item["kind"], "review": q["role"] == "review", **q})))
        return 0
    if a.command == "approve":
        try:
            if a.from_qc:
                from backend import drive_layout
                item = approve_from_qc(ledger, drive_layout.load_qc(), recording=a.recording, key=a.key,
                                       synthetic=None if a.synthetic is None else a.synthetic == "yes")
            else:
                item = approve(ledger, recording=a.recording, key=a.key, by=a.by or "",
                               synthetic=None if a.synthetic is None else a.synthetic == "yes",
                               evidence=a.evidence, on=a.on, note=a.note)
        except (ValueError, LookupError) as e:
            print(f"🚫 {e}")
            return 1
        save(ledger, a.ledger)
        print(f"✅ 承認を控えました: {a.recording} / {a.key}（{item['approval']['by']}・{item['approval']['on']}）")
        return 0
    if a.command == "list":
        print("\n".join(summary(ledger)))
        return 0
    if a.command == "trace":
        item = find(ledger, a.recording, a.key)
        if item is None:
            print(f"🚫 提案がありません: {a.recording} / {a.key}")
            return 1
        print("\n".join(trace(item)))
        return 0 if item["state"] == APPROVED else 1
    if a.command == "check-put":
        problems = put_problems(a.local_dir, a.dest, ledger)
        print("\n".join(f"🚫 {x}" for x in problems) or "✅ 送れます（承認の要る物は、すべて承認済み）")
        return 1 if problems else 0
    if a.command in ("gate", "snapshot"):
        from backend import drive_layout

        layout = drive_layout.load_layout()
        try:
            if a.command == "gate" and a.tree:
                root = tree_from_json(json.loads(Path(a.tree).read_text(encoding="utf-8")))
                looked = f"控え {a.tree}"
            else:
                root = drive_layout._read(os.environ, layout)
                looked = "Drive（今の姿）"
        except drive_layout._errors() as e:
            # **見ていないのに緑にしない**
            print(f"🚫 Drive を読めませんでした（見ていないので合否は出しません）: {e}")
            return 1
        if a.command == "snapshot":
            Path(a.out).write_text(json.dumps(tree_to_json(root), ensure_ascii=False, indent=1) + "\n",
                                   encoding="utf-8", newline="\n")
            print(f"控えた: {a.out}")
            return 0
        findings = drive_findings(root, layout, ledger)
        print("番組化の承認の門 — 40_完成 の動画と画像が、1つ残らず承認に辿れるか")
        print(f"  見た場所: {looked}")
        print(f"  基準線（門の前からあった物）: {len(ledger.get('baseline', []))} 件")
        print("提案と承認")
        print("\n".join(summary(ledger)))
        print("置き場")
        if not findings:
            print("  ✅ 投稿する棚の動画と画像は、すべて承認済みか基準線です")
        for f in findings:
            print(f"  🚫 {f['path']}: {f['message']}")
        return 1 if findings else 0
    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
