"""通しで見る人のための字幕の控え（レビュー画面が読む）と、画面で付けた印を校正台帳の直しにする。

1. ``export``: 書き出しの字幕（``*.subtitles.json``）から、画面が読む控え（``review_captions.json``）を作る。
   字幕ごとに、出来上がりの秒・素材の秒（``ranges`` でつないだ所を戻す）・字を持つ。
2. 人が画面で、違和感のある字幕に印を付け、正しい字を書く（``{cap, src, text, fix, note, state}``）。
3. ``to_corrections``: 印を校正台帳（`review_ledger`）の直しにする。字幕の字と直した字の違う所だけを、
   前後の字を少し付けて ``from``・``to`` にする。整形の割り付けが変わっても行の中で当たるように短くする。

使い方（リポジトリ直下で）::

    python -m backend.subtitle_engine.review_sheet export SIDECAR --run r53 --label 53回目 \\
        --video raw4_concat_preview_360p.mp4 --asr pipeline_work/concat/_align_rz_XXXX.json \\
        --out DIR/review_captions.json
    python -m backend.subtitle_engine.review_sheet import MARKS.json --ledger backend/config/reviews/X.json \\
        --by 北原 --day 2026-10-18
    python -m backend.subtitle_engine.review_sheet compare APPROVED.subtitles.json AGAIN.subtitles.json
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

# 直した所の前後に付ける字数（同じ字の並びが近くにあっても、直す所を1つに決められるように）
CONTEXT_CHARS = 3
# 字幕で句読点を外した跡（全角スペース）と改行。直しの字では句読点に戻す
_BREAKS = "\n"
_GAP = "\u3000"


def source_time(t: float, ranges: list) -> float:
    """出来上がりの秒 ``t`` を素材の秒に戻す（``ranges`` は素材の [始, 終] をつないだ順）。"""
    acc = 0.0
    for a, b in ranges:
        span = float(b) - float(a)
        if t <= acc + span:
            return round(float(a) + max(0.0, t - acc), 2)
        acc += span
    return round(float(ranges[-1][1]), 2) if ranges else round(float(t), 2)


def export(sidecar: dict, run: str, label: str, video: str, tokens: list | None = None) -> dict:
    """画面が読む字幕の控え。``captions`` の ``src`` は字幕の真ん中の素材の秒（直しの ``at`` になる）。

    ``tokens``（別の音声認識の ``[字, 素材の秒]``）があれば、食い違う字幕に機械の要確認（``flags``）を付ける。
    """
    ranges = sidecar.get("ranges") or []
    caps = []
    for i, s in enumerate(sidecar.get("segments") or []):
        a, b = float(s["start"]), float(s["end"])
        caps.append({"i": i, "s": round(a, 2), "e": round(b, 2),
                     "src": source_time((a + b) / 2, ranges), "t": s.get("text", "")})
    sheet = {"version": 1, "run": run, "label": label, "video": video,
             "duration": round(sum(float(b) - float(a) for a, b in ranges), 2) if ranges else None,
             "captions": caps}
    if tokens:
        from subtitle_engine import review_flags
        spans = [{"i": c["i"], "t": c["t"], "a": source_time(c["s"], ranges), "b": source_time(c["e"], ranges)}
                 for c in caps]
        sheet["flags"] = review_flags.flag_captions(spans, tokens)
    return sheet


def _parts(text: str) -> list[str]:
    """字幕の字を、句読点を外した跡（改行・全角スペース）で分けた塊。"""
    return [p for p in text.replace(_GAP, _BREAKS).split(_BREAKS) if p.strip()]


def _diff_part(a: str, b: str, context: int) -> tuple[str, str] | None:
    if a == b:
        return None
    head = 0
    while head < min(len(a), len(b)) and a[head] == b[head]:
        head += 1
    tail = 0
    while tail < min(len(a), len(b)) - head and a[-1 - tail] == b[-1 - tail]:
        tail += 1
    lo = max(0, head - context)
    keep_tail = max(0, tail - context)
    return a[lo:len(a) - keep_tail], b[lo:len(b) - keep_tail]


def _diff(text: str, fix: str, context: int = CONTEXT_CHARS) -> list[tuple[str, str]]:
    """字幕の字 ``text`` を ``fix`` に直すときの（from, to）の組。違う所と前後の字だけ。

    句読点を外した跡（改行・全角スペース）をまたがない: 台帳は整形の前の行に当て、またぐと行の句読点ごと
    置き換わる（「「新・日本」と、あと」の「、」が消える）。塊の数が同じなら塊ごとに比べ、違えば
    全体を1組にする。そのときも塊の切れ目は「、」に戻す（直しで足した切れ目「そうそう　そうです」を消さない）。

    台帳の直しは1つずつ順に当たるので、組どうしが同じ塊を使ってはいけない（先の直しで後の直しの「from」が
    無くなる）。短い直しが付けた隣の塊も直した所なら、重なった塊の全体を1組にする。
    """
    pa, pb = _parts(text), _parts(fix)
    if len(pa) != len(pb):
        pa, pb = ["、".join(pa)], ["、".join(pb)]
    groups: list[list] = []  # [始めの塊, 終わりの塊, (from, to)]
    for k, (a, b) in enumerate(zip(pa, pb)):
        pair = _diff_part(a, b, context)
        if not pair:
            continue
        src, dst = pair
        lo = hi = k
        # 短すぎると行の中で決まらない（「ね」）。隣の塊を「、」でつないで付ける
        if len(src) < context and k > 0:
            lo, src, dst = k - 1, f"{pa[k - 1]}、{src}", f"{pb[k - 1]}、{dst}"
        elif len(src) < context and k + 1 < len(pa):
            hi, src, dst = k + 1, f"{src}、{pa[k + 1]}", f"{dst}、{pb[k + 1]}"
        if groups and lo <= groups[-1][1]:
            lo, hi = groups[-1][0], max(hi, groups[-1][1])
            groups[-1] = [lo, hi, ("、".join(pa[lo:hi + 1]), "、".join(pb[lo:hi + 1]))]
        elif src:
            groups.append([lo, hi, (src, dst)])
    return [pair for _, _, pair in groups]


def _clock(sec: float) -> str:
    return f"{int(sec) // 60}:{int(sec) % 60:02d}"


def to_corrections(marks: list[dict], *, by: str, day: str, label: str, start: int = 1) -> tuple[list, list]:
    """印から台帳の直しを作る。返り値は（直し, 直しにならなかった印）。

    直しにならないのは、正しい字が書かれていない印（「問題なし」・メモだけ）。人が読む所なので捨てずに返す。
    """
    out, rest = [], []
    n = start
    for m in sorted(marks, key=lambda m: float(m.get("src") or 0.0)):
        pairs = _diff(m.get("text", ""), m.get("fix", "")) if m.get("fix") and m.get("state") != "ok" else []
        if not pairs:
            rest.append(m)
            continue
        for src, dst in pairs:
            entry = {"id": f"{day}-{n:02d}", "at": float(m["src"]), "from": src, "to": dst,
                     "by": by, "seen": f"{label} {_clock(float(m.get('t') or 0.0))}"}
            if m.get("note"):
                entry["note"] = m["note"]
            out.append(entry)
            n += 1
    return out, rest


def dump_ledger(data: dict) -> str:
    """台帳を人が読み書きしやすい形で書く（直しと用語は1件1行）。"""
    lines = ["{"]
    keys = list(data)
    for k, key in enumerate(keys):
        comma = "," if k < len(keys) - 1 else ""
        value = data[key]
        if key in ("corrections", "glossary") and isinstance(value, list):
            lines.append(f'  "{key}": [')
            for j, item in enumerate(value):
                tail = "," if j < len(value) - 1 else ""
                lines.append("    " + json.dumps(item, ensure_ascii=False) + tail)
            lines.append("  ]" + comma)
        else:
            body = json.dumps(value, ensure_ascii=False, indent=2).replace("\n", "\n  ")
            lines.append(f'  "{key}": {body}{comma}')
    lines.append("}")
    return "\n".join(lines) + "\n"


def compare(approved: dict, again: dict) -> list[dict]:
    """承認した書き出しと、作り直した書き出しの字幕の違い（素材の秒・前の字・後の字）。同じなら空。

    キャッシュ無しで作り直したときに、人が見直す所を出す（要望③の再現の確かめ）。
    """
    def rows(side):
        ranges = side.get("ranges") or []
        return [(source_time(float(s["start"]), ranges), s.get("text", "")) for s in side.get("segments") or []]
    a, b = rows(approved), rows(again)
    out = []
    sm = difflib.SequenceMatcher(None, [t for _, t in a], [t for _, t in b], autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        at = a[i1][0] if i1 < len(a) else (b[j1][0] if j1 < len(b) else 0.0)
        out.append({"src": at, "approved": [t for _, t in a[i1:i2]], "again": [t for _, t in b[j1:j2]]})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="字幕のレビュー画面の控えを作る・画面の印を校正台帳に入れる")
    sub = parser.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export", help="書き出しの字幕から画面の控えを作る")
    ex.add_argument("sidecar")
    ex.add_argument("--run", required=True)
    ex.add_argument("--label", required=True)
    ex.add_argument("--video", required=True, help="画面が読む動画のファイル名（控えと同じフォルダ）")
    ex.add_argument("--out", required=True)
    ex.add_argument("--asr", default="", help="別の音声認識の字と時刻（ReazonSpeech の _align_rz_*.json）。機械の要確認を付ける")
    im = sub.add_parser("import", help="画面の印（JSON の配列）を校正台帳の直しに足す")
    im.add_argument("marks")
    im.add_argument("--ledger", required=True)
    im.add_argument("--by", required=True)
    im.add_argument("--day", required=True, help="直しの id の頭（例 2026-10-18）")
    im.add_argument("--label", default="", help="seen に書く書き出しの名前（既定は印の run）")
    cp = sub.add_parser("compare", help="承認した書き出しと作り直した書き出しの字幕を比べる（違えば終了コード 1）")
    cp.add_argument("approved")
    cp.add_argument("again")
    args = parser.parse_args(argv)

    if args.cmd == "compare":
        diff = compare(*(json.loads(Path(p).read_text(encoding="utf-8")) for p in (args.approved, args.again)))
        for d in diff:
            show = lambda ts: " / ".join(t.replace(_BREAKS, " ") for t in ts) or "（なし）"  # noqa: E731
            print(f"素材 {_clock(d['src'])}  承認: {show(d['approved'])}\n          作り直し: {show(d['again'])}")
        print(f"違い {len(diff)} か所" if diff else "字幕は承認したものと同じです")
        return 1 if diff else 0

    if args.cmd == "export":
        sidecar = json.loads(Path(args.sidecar).read_text(encoding="utf-8"))
        tokens = json.loads(Path(args.asr).read_text(encoding="utf-8"))["tokens"] if args.asr else None
        sheet = export(sidecar, args.run, args.label, args.video, tokens)
        Path(args.out).write_text(json.dumps(sheet, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        flags = f"・機械の要確認 {len(sheet['flags'])} 枚" if "flags" in sheet else ""
        print(f"字幕 {len(sheet['captions'])} 枚{flags} → {args.out}")
        return 0

    marks = json.loads(Path(args.marks).read_text(encoding="utf-8"))
    ledger_path = Path(args.ledger)
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    taken = {c.get("id") for c in ledger.get("corrections", [])}
    start = 1 + sum(1 for i in taken if str(i).startswith(args.day))
    label = args.label or (marks[0].get("label", "") if marks else "")
    new, rest = to_corrections(marks, by=args.by, day=args.day, label=label, start=start)
    ledger.setdefault("corrections", []).extend(new)
    ledger_path.write_text(dump_ledger(ledger), encoding="utf-8")
    print(f"直し {len(new)} 件を足しました → {ledger_path}")
    for m in rest:
        print(f"  直しにならない印（人が見る）: {_clock(float(m.get('t') or 0))} {m.get('text', '')!r}"
              f" 状態={m.get('state')} メモ={m.get('note', '')!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
