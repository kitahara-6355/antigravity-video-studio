"""目視OKの完成版から、番組の飾り・承認済みの画像インサート・曲まで入った「承認待ちの1本」を通しで作る（AI なし・0円）。

1. 飾り（episode）: 番組 OP・今回の OP・章の見出し・名前のポップ・テロップ・ED。
   承認済みの画像インサート（inserts）があれば一緒に重ねる
2. 曲（music → remix）: 曲の台帳から音の指定を作り、OP の曲・インタビュー中の BGM（声の下で下げる）・ED の曲・音割れ止め
3. 確かめ: 飾りと差し込みが頭に掛かっていないか（地図があれば）、番組名の所で曲が上がっているか、品質ゲート（実測）
4. 控え: 何を入れたか・何を確かめたかを ``<版>_仕上げの控え.json`` に残す

できた物は **承認待ち**。40_完成 の投稿する棚に置くには、いつもどおり ``program_gate`` の提案と北原さんの承認が要る。

使い方（リポジトリ直下で）::

    python -m backend.program_package.finish backend/config/episode/<収録ID>.json --version v68 --out OUT \\
        --music-dir 曲の置き場 [--map 地図.json] [--audio AUDIO.json] [--no-music] [--review]

``--audio`` を渡すと、曲の台帳ではなくその指定をそのまま使う（打ち合わせで決めた音量を再現するとき）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from backend.program_package import episode as ep
from backend.program_package import inserts as ins
from backend.program_package import music as mu
from backend.program_package import remix as rx
from backend.program_package import vision


def audio_of(spec: dict, music_dir: str | None, audio_path: str | None, m: dict | None, body_seconds: float) -> dict:
    """音の指定。--audio があればそれ。無ければ曲の台帳から作る（色紙の場面は BGM を止めない — 人が決める所）。"""
    if audio_path:
        audio = json.loads(Path(audio_path).read_text(encoding="utf-8"))
        gone = [str((audio.get(k) or {}).get("path")) for k in mu.ROLES.values()
                if audio.get(k) and not Path(str(audio[k].get("path", ""))).is_file()]
        if gone:  # 長い書き出しの前に分かる事は先に止める
            raise mu.MusicError("音の指定の曲のファイルがありません: " + " / ".join(gone))
        return audio
    program = ep.program_of(spec)
    if not program:
        raise mu.MusicError("この回の指定に番組（program）がありません")
    ledger = json.loads(mu.LEDGER.read_text(encoding="utf-8"))
    quiet = spec.get("bgm_quiet") or []
    return mu.plan(program, ledger, music_dir or os.environ.get("AVS_MUSIC_DIR"), quiet, body_seconds)


def finish(spec: dict, out: Path, version: str, *, music_dir: str | None = None, audio_path: str | None = None,
           map_path: str | None = None, music: bool = True, review: bool = False) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    spec = {**spec, "version": version}
    m = vision.load(map_path) if map_path else None
    note: dict = {"recording": spec["recording"], "version": version, "steps": [], "checks": []}

    # 先に確かめられる物は書き出す前に確かめる（書き出しは長い）
    plan_path = Path(spec["inserts"]) if spec.get("inserts") else ins.store_of(spec)
    items = ins.ready(ins.load_plan(plan_path), spec) if spec.get("inserts") is not False and plan_path.exists() else []
    note["inserts"] = [{k: it[k] for k in ("id", "at", "seconds", "mode", "keyword")} |
                       {"approved_by": it["decision"]["by"], "evidence": it["decision"]["evidence"]} for it in items]
    if m:
        bad = [f"{b.get('label')} {b.get('at')}" for b in vision.check(spec, m, vision._body(spec)) if b["level"] == "掛かる"]
        bad += [f"差し込み {i}" for i in ins.head_hits(items, m)]
        note["checks"].append({"id": "heads", "label": "飾りと差し込みが頭に掛かっていない", "ok": not bad, "detail": bad})
    else:
        note["checks"].append({"id": "heads", "label": "飾りと差し込みが頭に掛かっていない", "ok": False,
                               "detail": "地図（--map）が無いので確かめていない"})
    audio = None
    if music:
        body_seconds = rx.duration(spec["source"])
        audio = audio_of(spec, music_dir, audio_path, m, body_seconds)

    if audio and audio.get("op_music"):
        spec["program_silent"] = True  # OP の曲は remix が入れる
    base = ep.build(spec, out / "_飾りまで")
    note["steps"].append({"step": "飾り", "file": base.name, "inserts": len(items)})
    final = base
    if audio:
        final = rx.remix(spec, base, audio, version, out)
        note["steps"].append({"step": "曲", "file": final.name,
                              "tracks": audio.get("tracks") or {k: (audio.get(k) or {}).get("path") for k in mu.ROLES.values()}})
        if audio.get("op_music"):
            c = mu.check(final, mu.title_at(ep.program_of(spec)))
            note["checks"].append({"id": "op_climax", "label": "番組名の所で曲が上がっている", "ok": c["ok"],
                                   "detail": f"{c['rise_db']} dB"})
    else:
        final = out / base.name
        base.replace(final)
    from backend.revenue import program_quality as pq
    q = pq.measure("episode", final)
    note["checks"].append({"id": "quality", "label": "品質ゲート（実測）", "ok": bool(q["passed"]),
                           "detail": pq.format_report(q)})
    if review:
        note["review"] = rx.review_copy(final).name
    note["file"] = final.name
    note["music"] = bool(audio)
    ai = [f"{role}: {t.get('title')}（{t.get('made_with')}）" for role, t in ((audio or {}).get("tracks") or {}).items()
          if isinstance(t, dict) and t.get("ai_generated")]
    if ai:  # 止めはしない。公開のときに人が決める事を控えに出す
        note["ai_music"] = {"tracks": ai, "todo": "AI で作った曲が入っている。公開の前に、使ってよい条件と YouTube の開示の要否を確かめる"}
    note["state"] = "承認待ち（program_gate propose → 北原さんの承認 → 置く）" + ("" if audio else "。曲は入っていない")
    (out / f"{spec['recording']}_{version}_仕上げの控え.json").write_text(
        json.dumps(note, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return note


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="飾り・画像インサート・曲まで入った承認待ちの1本を通しで作る")
    p.add_argument("spec")
    p.add_argument("--version", required=True)
    p.add_argument("--out", default=".")
    p.add_argument("--music-dir")
    p.add_argument("--audio")
    p.add_argument("--map")
    p.add_argument("--no-music", action="store_true")
    p.add_argument("--review", action="store_true")
    a = p.parse_args(argv)
    spec = json.loads(Path(a.spec).read_text(encoding="utf-8"))
    try:
        note = finish(spec, Path(a.out), a.version, music_dir=a.music_dir, audio_path=a.audio, map_path=a.map,
                      music=not a.no_music, review=a.review)
    except (mu.MusicError, ins.InsertError, vision.VisionError, ValueError) as e:
        print(f"止めました: {e}", file=sys.stderr)
        return 1
    print(json.dumps(note, ensure_ascii=False, indent=1))
    return 0 if all(c["ok"] for c in note["checks"]) else 2


if __name__ == "__main__":
    sys.exit(main())
