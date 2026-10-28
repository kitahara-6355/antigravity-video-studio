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
import re
import sys
from pathlib import Path

# 直した所の前後に付ける字数（同じ字の並びが近くにあっても、直す所を1つに決められるように）
CONTEXT_CHARS = 3
# 字幕で句読点を外した跡（全角スペース）と改行。直しの字では句読点に戻す
_BREAKS = "\n"
_GAP = "\u3000"
# \u300c\u6b63\u3057\u304f\u306f\u300d\u306f\u65e5\u672c\u8a9e\u5165\u529b\u3067\u66f8\u304f\u306e\u3067\u6570\u5b57\u3068\u82f1\u5b57\u304c\u5168\u89d2\u306b\u306a\u308a\u3084\u3059\u3044\uff0859\u56de\u76ee\u306e\u300c\uff16\u65e5\u9593\u300d\uff09\u3002\u5b57\u5e55\u306e\u6570\u5b57\u3068\u82f1\u5b57\u306f
# \u534a\u89d2\u306a\u306e\u3067\u3001\u76f4\u3057\u3082\u534a\u89d2\u306b\u305d\u308d\u3048\u308b\u3002\u300c\uff1f\u300d\u300c\uff01\u300d\u3084\u5168\u89d2\u30b9\u30da\u30fc\u30b9\u306f\u5b57\u5e55\u306e\u5b57\u306a\u306e\u3067\u89e6\u3089\u306a\u3044
_HALF_WIDTH = str.maketrans({chr(c): chr(c - 0xFEE0)
                             for c in (*range(0xFF10, 0xFF1A), *range(0xFF21, 0xFF3B), *range(0xFF41, 0xFF5B))})


def source_time(t: float, ranges: list) -> float:
    """出来上がりの秒 ``t`` を素材の秒に戻す（``ranges`` は素材の [始, 終] をつないだ順）。"""
    acc = 0.0
    for a, b in ranges:
        span = float(b) - float(a)
        if t <= acc + span:
            return round(float(a) + max(0.0, t - acc), 2)
        acc += span
    return round(float(ranges[-1][1]), 2) if ranges else round(float(t), 2)


def export(sidecar: dict, run: str, label: str, video: str, tokens: list | None = None,
           readings: dict | None = None) -> dict:
    """画面が読む字幕の控え。``captions`` の ``src`` は字幕の真ん中の素材の秒（直しの ``at`` になる）。

    ``tokens``（別の音声認識の ``[字, 素材の秒]``）があれば、食い違う字幕に機械の要確認（``flags``）を付ける。
    ``readings``（名前 → 文字起こしの行）もあれば、それとも並べ、印にほかの聞き取りの字を候補として付ける
    （``review_flags.flag_with_readings``）。
    """
    ranges = sidecar.get("ranges") or []
    caps = []
    for i, s in enumerate(sidecar.get("segments") or []):
        a, b = float(s["start"]), float(s["end"])
        caps.append({"i": i, "s": round(a, 2), "e": round(b, 2),
                     "src": source_time((a + b) / 2, ranges), "t": s.get("text", ""),
                     "a": source_time(a, ranges), "b": source_time(b, ranges)})
    sheet = {"version": 1, "run": run, "label": label, "video": video,
             "duration": round(sum(float(b) - float(a) for a, b in ranges), 2) if ranges else None,
             "captions": caps}
    if tokens:
        from subtitle_engine import review_flags
        spans = [{"i": c["i"], "t": c["t"], "a": source_time(c["s"], ranges), "b": source_time(c["e"], ranges)}
                 for c in caps]
        if readings:
            sources = {review_flags.RECOGNISER: tokens,
                       **{name: review_flags.reading_tokens(segs) for name, segs in readings.items()}}
            sheet["flags"] = review_flags.flag_with_readings(spans, sources)
        else:
            sheet["flags"] = review_flags.flag_captions(spans, tokens)
    return sheet


# 印の候補に使う、素材の隣の文字起こしのキャッシュ（`transcribe_worker._gemini_checkpoint` の名前の区切りの印）
READINGS = (("2回目", "b2"), ("3回目", "c"), ("1回目", ""))


def readings_beside(material: str | Path) -> dict:
    """素材の隣にある文字起こしのキャッシュの行（名前 → 行）。無いものは入れない。3回目は区間ごとの控えも読む。"""
    from subtitle_engine import gemini_transcriber as gt
    from subtitle_engine.video_hash import material_cache

    material = Path(material)
    if not material.is_file():
        return {}
    out = {}
    for name, tag in READINGS:
        path = material_cache(material, f"_gemini_c{gt.CHUNK_SEC}{gt.CUT_TAG}{tag}_", ".jsonl")
        rows = []
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
        else:
            for segs, _model in gt.read_journal(gt.journal_path(path)).values():
                rows.extend(segs)
        if rows:
            out[name] = rows
    return out


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
        fix = str(m.get("fix") or "").translate(_HALF_WIDTH)
        pairs = _diff(m.get("text", ""), fix) if fix and m.get("state") != "ok" else []
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


# 印の状態（画面のボタン）。メモだけで指示された印は、メモの言葉で見分ける（2026-10-24 北原さんの朱入れ
# 「映像字幕ともにカット」「字幕なしにして」）
CUT_STATES = {"cut": "cut", "hide": "hide"}
# 「カットされている疑惑がある」（7分50秒・切れた声の指摘）は指示ではないので、「カット」の後ろが
# 「され」「しない」のものは見ない
CUT_WORDS = ((re.compile(r"字幕(なし|無し|だけ消|を消)"), "hide"), (re.compile(r"カット(?!され|しな)"), "cut"))
# 続けて指示された字幕の区間は、隣の字幕か、すき間がこれ以下なら1つの区間にする
CUT_JOIN_SEC = 1.0


def cut_mode(mark: dict) -> str | None:
    """印が「映像ごと切る」（cut）か「字幕だけ消す」（hide）か。どちらでもなければ None。"""
    state = str(mark.get("state") or "")
    if state in CUT_STATES:
        return CUT_STATES[state]
    if state == "fixed" and str(mark.get("fix") or "").strip():
        return None
    note = str(mark.get("note") or "")
    if note.startswith("機械の要確認"):
        return None
    return next((mode for word, mode in CUT_WORDS if word.search(note)), None)


def to_cuts(marks: list[dict], captions: dict[int, dict], *, by: str, day: str, label: str,
            start: int = 1) -> tuple[list, list]:
    """印から台帳の cuts（素材の秒の区間と mode）を作る。返り値は（cuts, 区間が分からなかった印）。

    区間は画面の字幕の素材の秒（控えの ``a``・``b``）。同じ mode で続く字幕はつなぐ。
    """
    rows, lost = [], []
    for m in sorted(marks, key=lambda m: float(m.get("src") or 0.0)):
        mode = cut_mode(m)
        if not mode:
            continue
        cap = captions.get(int(m.get("cap", -1)))
        if not cap or cap.get("a") is None or cap.get("b") is None:
            lost.append(m)
            continue
        rows.append([float(cap["a"]), float(cap["b"]), mode, [m]])
    merged: list[list] = []
    for a, b, mode, ms in rows:
        nextdoor = merged and int(ms[0].get("cap", -9)) == int(merged[-1][3][-1].get("cap", -9)) + 1
        if merged and merged[-1][2] == mode and (nextdoor or a - merged[-1][1] <= CUT_JOIN_SEC):
            merged[-1][1] = max(merged[-1][1], b)
            merged[-1][3].extend(ms)
        else:
            merged.append([a, b, mode, ms])
    out = []
    for n, (a, b, mode, ms) in enumerate(merged, start):
        text = " / ".join(str(m.get("text", "")).replace(_BREAKS, " ") for m in ms)
        entry = {"id": f"{day}-c{n:02d}", "start": round(a, 2), "end": round(b, 2), "mode": mode,
                 "text": text, "by": by, "seen": f"{label} {_clock(float(ms[0].get('t') or 0.0))}"}
        notes = sorted({str(m.get("note") or "") for m in ms} - {""})
        if notes:
            entry["note"] = "／".join(notes)
        out.append(entry)
    return out, lost


def _last_number(entries: list[dict], head: str) -> int:
    """id が head＋番号の項目の、一番大きい番号（無ければ 0）。直しを手でまとめて番号が飛んでいても重ならない。"""
    nums = [int(m.group(1)) for e in entries if (m := re.fullmatch(re.escape(head) + r"(\d+)", str(e.get("id", ""))))]
    return max(nums, default=0)


def dump_ledger(data: dict) -> str:
    """台帳を人が読み書きしやすい形で書く（直しと用語は1件1行）。"""
    lines = ["{"]
    keys = list(data)
    for k, key in enumerate(keys):
        comma = "," if k < len(keys) - 1 else ""
        value = data[key]
        if key in ("corrections", "glossary", "cuts") and isinstance(value, list):
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


def format_compare(diff: list[dict]) -> list[str]:
    """`compare` の違いを人が読む行にする（最後の行は違いの数）。"""
    def show(ts):
        return " / ".join(t.replace(_BREAKS, " ") for t in ts) or "（なし）"
    lines = [f"素材 {_clock(d['src'])}  承認: {show(d['approved'])}\n          作り直し: {show(d['again'])}"
             for d in diff]
    lines.append(f"違い {len(diff)} か所" if diff else "字幕は承認したものと同じです")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="字幕のレビュー画面の控えを作る・画面の印を校正台帳に入れる")
    sub = parser.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export", help="書き出しの字幕から画面の控えを作る")
    ex.add_argument("sidecar")
    ex.add_argument("--run", required=True)
    ex.add_argument("--label", required=True)
    ex.add_argument("--video", required=True, help="画面が読む動画のファイル名（控えと同じフォルダ）")
    ex.add_argument("--out", required=True)
    ex.add_argument("--asr", default="", help="別の音声認識の字と時刻（ReazonSpeech の _align_rz_*.json。素材の時間軸に"
                    "直して読む）。機械の要確認を付ける")
    ex.add_argument("--material", default="", help="素材（隣の文字起こしのキャッシュも並べ、要確認に候補の字を付ける）")
    im = sub.add_parser("import", help="画面の印（JSON の配列）を校正台帳の直しに足す")
    im.add_argument("marks")
    im.add_argument("--ledger", required=True)
    im.add_argument("--by", required=True)
    im.add_argument("--day", required=True, help="直しの id の頭（例 2026-10-18）")
    im.add_argument("--label", default="", help="seen に書く書き出しの名前（既定は印の run）")
    im.add_argument("--sheet", default="", help="画面の控え（review_captions.json）。カット・字幕なしの印の区間を読む")
    im.add_argument("--sidecar", default="", help="書き出しの字幕（*.subtitles.json）。控えに素材の秒が無いとき、"
                    "その ranges で戻す")
    cp = sub.add_parser("compare", help="承認した書き出しと作り直した書き出しの字幕を比べる（違えば終了コード 1）")
    cp.add_argument("approved")
    cp.add_argument("again")
    args = parser.parse_args(argv)

    if args.cmd == "compare":
        diff = compare(*(json.loads(Path(p).read_text(encoding="utf-8")) for p in (args.approved, args.again)))
        print("\n".join(format_compare(diff)))
        return 1 if diff else 0

    if args.cmd == "export":
        sidecar = json.loads(Path(args.sidecar).read_text(encoding="utf-8"))
        from subtitle_engine import aligner
        tokens = aligner.cached_tokens(args.asr) if args.asr else None
        readings = readings_beside(args.material) if args.material else None
        sheet = export(sidecar, args.run, args.label, args.video, tokens, readings=readings)
        Path(args.out).write_text(json.dumps(sheet, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        flags = f"・機械の要確認 {len(sheet['flags'])} 枚" if "flags" in sheet else ""
        print(f"字幕 {len(sheet['captions'])} 枚{flags} → {args.out}")
        return 0

    marks = json.loads(Path(args.marks).read_text(encoding="utf-8"))
    ledger_path = Path(args.ledger)
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    start = 1 + _last_number(ledger.get("corrections", []), f"{args.day}-")
    label = args.label or (marks[0].get("label", "") if marks else "")
    new, rest = to_corrections([m for m in marks if not cut_mode(m)], by=args.by, day=args.day, label=label,
                               start=start)
    ledger.setdefault("corrections", []).extend(new)
    cuts, lost = [], []
    if any(cut_mode(m) for m in marks):
        if not args.sheet:
            print("カット・字幕なしの印があります。--sheet（画面の控え）を付けてください", file=sys.stderr)
            return 2
        sheet = json.loads(Path(args.sheet).read_text(encoding="utf-8"))
        ranges = (json.loads(Path(args.sidecar).read_text(encoding="utf-8")).get("ranges") or []
                  if args.sidecar else [])
        captions = {}
        for c in sheet.get("captions") or []:
            if c.get("a") is None and ranges:
                c = dict(c, a=source_time(float(c["s"]), ranges), b=source_time(float(c["e"]), ranges))
            captions[int(c["i"])] = c
        first = 1 + _last_number(ledger.get("cuts", []), f"{args.day}-c")
        cuts, lost = to_cuts(marks, captions, by=args.by, day=args.day, label=label, start=first)
        ledger.setdefault("cuts", []).extend(cuts)
    ledger_path.write_text(dump_ledger(ledger), encoding="utf-8")
    print(f"直し {len(new)} 件・カット {sum(c['mode'] == 'cut' for c in cuts)} 区間・"
          f"字幕なし {sum(c['mode'] == 'hide' for c in cuts)} 区間を足しました → {ledger_path}")
    for m in lost:
        print(f"  区間が分からない印（人が見る）: {_clock(float(m.get('t') or 0))} {m.get('text', '')!r}")
    for m in rest:
        print(f"  直しにならない印（人が見る）: {_clock(float(m.get('t') or 0))} {m.get('text', '')!r}"
              f" 状態={m.get('state')} メモ={m.get('note', '')!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
