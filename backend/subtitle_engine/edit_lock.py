"""承認した編集の固定 — 承認した書き出しの「残す区間」と「字幕」を、素材と結び付けて残し、そのまま作り直す。

文字起こしと校閲（AI）は呼ぶたびに揺れる。人が見て直した所は校正台帳で毎回同じに当たるが、
人が見ていない所の字は、AI の控え（キャッシュ）が無いと揺れる（raw4 で 13% の字が違った・2026-10-19）。
承認した編集そのものを残せば、控えが無くても、コードが変わっても、raw から同じ字幕の動画を作り直せる。

- ``make``: 承認した書き出しの字幕（``*.subtitles.json``）と素材の鍵から、固定（lock）を作る
- ``render``: 素材を固定の区間で切り、固定の字幕を焼く（本線のプレビューと同じ切り方・焼き方）。
  横に置く字幕（``.subtitles.json``）は固定と同じなので、``review_sheet compare`` で違い 0 になる

AI は呼ばない（課金なし）。素材が違えば（中身の鍵が違えば）作らずに止まる。

使い方（リポジトリ直下で）::

    python -m backend.subtitle_engine.edit_lock make APPROVED.subtitles.json --material RAW.mp4 \\
        --run r61 --label 61回目 --out LOCK.json
    python -m backend.subtitle_engine.edit_lock render LOCK.json --material RAW.mp4 --out OUT.mp4
    python -m backend.subtitle_engine.edit_lock amend LOCK.json --fixes FIXES.json --by 北原 \\
        --evidence "<日時と言葉>" --out LOCK2.json

- ``amend``: 承認した後の字幕の直し（人の指示）を固定に足す。直しは完成版の時刻と「違う字だけ」。
  区間（カット）は変えない。直しの記録（誰が・いつ・何を）と、直す前の固定の鍵が残る
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

VERSION = 1


class LockError(RuntimeError):
    """固定と素材が合わない・固定が壊れている。"""


def _sidecar_sha(sidecar: dict) -> str:
    return hashlib.sha256(json.dumps(sidecar, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def make(sidecar: dict, material: str | Path, *, run: str, label: str) -> dict:
    """承認した書き出しの字幕 ``sidecar`` を、素材 ``material`` に結び付けた固定にする。"""
    from subtitle_engine.video_hash import content_digest

    ranges = sidecar.get("ranges") or []
    segments = sidecar.get("segments") or []
    if not ranges or not segments:
        raise LockError("残す区間か字幕が無い書き出しは固定できません")
    return {"version": VERSION, "material": {"name": Path(material).name, "key": content_digest(Path(material))},
            "approved": {"run": run, "label": label, "sha256": _sidecar_sha(sidecar)},
            "ranges": ranges, "segments": segments,
            **{k: sidecar[k] for k in ("cut_points", "estimated", "gone") if k in sidecar}}


def sidecar_of(lock: dict) -> dict:
    """固定から、承認した書き出しと同じ字幕（``*.subtitles.json`` の中身）を戻す。"""
    return {k: lock[k] for k in ("segments", "ranges", "estimated", "cut_points", "gone") if k in lock}


def check(lock: dict, material: str | Path) -> None:
    """固定が読める形で、素材が固定を作った素材と同じ中身か。違えば ``LockError``。"""
    from subtitle_engine.video_hash import content_digest

    if lock.get("version") != VERSION or not lock.get("ranges") or not lock.get("segments"):
        raise LockError("固定の形が違います（version・ranges・segments）")
    if _sidecar_sha(sidecar_of(lock)) != (lock.get("approved") or {}).get("sha256"):
        raise LockError("固定の字幕が、承認したときと変わっています")
    key = content_digest(Path(material))
    if key != (lock.get("material") or {}).get("key"):
        raise LockError(f"素材が違います（固定は {lock['material'].get('name')}・鍵 {lock['material'].get('key', '')[:8]}、"
                        f"渡された素材の鍵 {key[:8]}）")


def render(lock: dict, material: str | Path, out: str | Path, ffmpeg=None) -> Path:
    """素材を固定の区間で切り、固定の字幕を焼いて ``out`` に書く。返り値は横に置いた字幕の場所。"""
    import smart_cut_engine as sce

    check(lock, material)
    if ffmpeg is None:
        from video_editor_engine import video_editor
        ffmpeg = video_editor.ffmpeg
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cut = out.with_name(out.stem + ".cut.tmp.mp4")
    ranges = [(float(a), float(b)) for a, b in lock["ranges"]]
    try:
        if not sce._cut_kept_ranges_exact(ffmpeg, Path(material), ranges, cut):
            raise LockError("残す区間で切れませんでした（ffmpeg）")
        # 焼けなければ字幕なしでコピーして "fallback_no_subtitle" を返す作りなので、True だけを成功とみる
        if sce._burn_subtitles_ffmpeg(str(cut), [dict(s) for s in lock["segments"]], str(out), ffmpeg) is not True:
            raise LockError("字幕を焼けませんでした（ffmpeg）")
    finally:
        cut.unlink(missing_ok=True)
    side = sce.subtitle_sidecar_path(out)
    side.write_text(json.dumps(sidecar_of(lock), ensure_ascii=False, indent=1), encoding="utf-8")
    return side


def _find_segment(segments: list[dict], at: float, old: str) -> int:
    """``at`` 秒に出ている字幕のうち、``old`` を含むもの。無ければ前後 3 秒の中で一番近いもの。"""
    hits = [(0.0 if s["start"] <= at <= s["end"] else min(abs(at - s["start"]), abs(at - s["end"])), i)
            for i, s in enumerate(segments) if old in s["text"].replace("\n", "") or old in s["text"]]
    hits = [h for h in hits if h[0] <= 3.0]
    if not hits:
        raise LockError(f"{at:.1f} 秒の前後 3 秒に「{old}」を含む字幕がありません")
    return min(hits)[1]


def amend(lock: dict, fixes: list[dict], *, by: str, evidence: str) -> dict:
    """承認済みの固定の字幕を、人の直し ``fixes``（``at``・``from``・``to``）で直した新しい固定を返す。

    ``from`` は字幕の中の違う字だけ（改行をまたいでもよい）。``to`` が空なら消す。区間は変えない。
    当たらない直しがあれば何も変えずに止まる（黙って捨てない）。
    """
    if not by or not evidence:
        raise LockError("直しには、指示した人（--by）と証拠（--evidence）が要ります")
    segments = [dict(s) for s in lock["segments"]]
    done = []
    for f in fixes:
        at, old, new = float(f["at"]), str(f["from"]), str(f.get("to", ""))
        if not old:
            raise LockError(f"{at:.1f} 秒の直しに from（違う字）がありません")
        i = _find_segment(segments, at, old)
        text = segments[i]["text"]
        if old in text:
            text = text.replace(old, new, 1)
        else:  # 改行をまたぐ字。改行は直した字の後ろに置き直す
            flat = text.replace("\n", "")
            pos = flat.index(old)
            flat = flat[:pos] + new + flat[pos + len(old):]
            brk = pos + len(new)
            text = flat if brk >= len(flat) else flat[:brk] + "\n" + flat[brk:]
        done.append({"at": at, "segment": i, "before": segments[i]["text"], "after": text})
        segments[i]["text"] = text
    out = {**lock, "segments": segments}
    out["approved"] = {**lock["approved"], "sha256": _sidecar_sha(sidecar_of(out))}
    out["amendments"] = [*lock.get("amendments", []),
                         {"by": by, "evidence": evidence, "based_on": lock["approved"]["sha256"], "fixes": done}]
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="承認した編集を固定する・固定から作り直す（AI を呼ばない）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    mk = sub.add_parser("make", help="承認した書き出しの字幕から固定を作る")
    mk.add_argument("sidecar")
    mk.add_argument("--material", required=True)
    mk.add_argument("--run", required=True)
    mk.add_argument("--label", required=True)
    mk.add_argument("--out", required=True)
    rd = sub.add_parser("render", help="固定から動画を作り直す")
    rd.add_argument("lock")
    rd.add_argument("--material", required=True)
    rd.add_argument("--out", required=True)
    am = sub.add_parser("amend", help="承認した後の字幕の直しを固定に足す（区間は変えない）")
    am.add_argument("lock")
    am.add_argument("--fixes", required=True, help='[{"at": 秒, "from": "違う字", "to": "正しい字"}, ...]')
    am.add_argument("--by", required=True)
    am.add_argument("--evidence", required=True)
    am.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        if args.cmd == "amend":
            lock = amend(json.loads(Path(args.lock).read_text(encoding="utf-8")),
                         json.loads(Path(args.fixes).read_text(encoding="utf-8")), by=args.by, evidence=args.evidence)
            Path(args.out).write_text(json.dumps(lock, ensure_ascii=False, indent=1), encoding="utf-8")
            for f in lock["amendments"][-1]["fixes"]:
                print(f"{f['at']:8.1f}s  {f['before']!r} → {f['after']!r}")
            print(f"直しました: {len(lock['amendments'][-1]['fixes'])} 件 → {args.out}")
            return 0
        if args.cmd == "make":
            lock = make(json.loads(Path(args.sidecar).read_text(encoding="utf-8")), args.material,
                        run=args.run, label=args.label)
            Path(args.out).write_text(json.dumps(lock, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"固定しました: 区間 {len(lock['ranges'])}・字幕 {len(lock['segments'])} 枚 → {args.out}")
            return 0
        side = render(json.loads(Path(args.lock).read_text(encoding="utf-8")), args.material, args.out)
        print(f"作り直しました: {args.out}（字幕 {side}）")
        return 0
    except LockError as e:
        print(f"🚫 {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
