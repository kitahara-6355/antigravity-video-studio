"""番組の雰囲気を「案を見て選ぶだけ」で決めるための見本を作る（AI を呼ばない・0円）。

- 選べる軸（opening.CHOICES）ごとに、ほかは今の形のまま、その軸だけを変えた短い見本（mp4 と静止画）を作る
- おすすめの組み合わせ（PRESETS）は OP の全体を見本にする
- 北原さんが選んだら、番組の指定（backend/config/program/<番組>.json）の style に書く。
  Shorts と本編は同じ指定を読むので、選んだ雰囲気はどちらにも効く
- 選んだ理由はソウル・ナラティブ（判断の記録）に残す（decision_logger）

使い方（リポジトリ直下で）::

    python -m backend.program_package.style_picker PROGRAM.json --out DIR          # 見本を作る
    python -m backend.program_package.style_picker PROGRAM.json --apply PICK.json  # 選んだ形を書き込む

PICK.json は選択画面（Artifact）の db の picks/latest をそのまま保存したもの（reveal・background・finish・note・at）。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from backend.program_package import opening as op

PREVIEW_W = 640  # 見本はスマホで見るので小さく軽く
PRESETS = {  # おすすめの組み合わせ（どれも薄紫・金・明朝の方向性の中）
    "now": {"label": "今の形（10-23 に OK）", "style": {"reveal": "brush", "background": "glow", "finish": "sweep"}},
    "quiet": {"label": "静かな格調", "style": {"reveal": "rise", "background": "washi", "finish": "seal"}},
    "festive": {"label": "華やか", "style": {"reveal": "stagger", "background": "gold_dust", "finish": "halo"}},
    "cinema": {"label": "映画のように", "style": {"reveal": "blur", "background": "drift", "finish": "brush_line"}},
}


def variants(program: dict) -> list[dict]:
    """作る見本の一覧。軸ごとの見本は言葉1枚＋番組名に縮めて、違いを見比べやすくする。"""
    base = op.style_of(program)
    short = {**program, "slides": program["slides"][:1], "music": None}
    out = []
    for axis, choices in op.CHOICES.items():
        for key, label in choices.items():
            out.append({"id": f"{axis}-{key}", "axis": axis, "choice": key, "label": label,
                        "current": base[axis] == key, "program": {**short, "style": {**base, axis: key}}})
    for key, p in PRESETS.items():
        out.append({"id": f"preset-{key}", "axis": "preset", "choice": key, "label": p["label"],
                    "style": p["style"], "current": p["style"] == base, "program": {**program, "style": p["style"]}})
    return out


def poster_time(program: dict) -> float:
    """静止画の時刻。番組名が出そろって、締めの動きが見える所。"""
    st = op.style_of(program)
    n = len(op.char_edges(program["name"], op.th.font("mincho", 116), 0)) - 1
    done = 0.2 + op._reveal_length(st["reveal"], n, program.get("title_char_seconds", 0.24)) + 0.3
    lag = {"sweep": 0.35, "seal": 0.4, "brush_line": 0.4, "halo": 0.9}[st["finish"]]
    return min(len(program["slides"]) * program["slide_seconds"] + done + lag, op.length(program) - 0.7)


def write_preview(program: dict, dst: Path, poster: Path, form: str = "横", at: float | None = None) -> float:
    """見本を1本（小さく・軽く）。静止画は番組名が出そろった所。"""
    with tempfile.TemporaryDirectory() as tmp:
        full = Path(tmp) / "full.mp4"
        total = op.render(program, full, form)
        h = round(PREVIEW_W * op.SIZES[form][1] / op.SIZES[form][0] / 2) * 2
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(full), "-vf", f"scale={PREVIEW_W}:{h}",
                        "-c:v", "libx264", "-crf", "30", "-preset", "slow", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(dst)], check=True)
        at = poster_time(program) if at is None else at
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{at:.2f}", "-i", str(full), "-frames:v", "1",
                        "-vf", f"scale={PREVIEW_W}:{h}", "-q:v", "4", str(poster)], check=True)
    return total


def apply(program_path: Path, pick: dict, log=None) -> dict:
    """選んだ形を番組の指定の style に書き、理由をソウル・ナラティブ（判断の記録）に残す。"""
    program = op.load(program_path)
    style = {k: pick[k] for k in op.STYLE}
    op.style_of({"style": style})  # 知らない選択肢なら止まる
    before = op.style_of(program)
    program["style"] = style
    when = str(pick.get("at", ""))[:10]
    program.setdefault("history", []).append(
        f"{when} 雰囲気えらびで " + "・".join(op.CHOICES[k][v] for k, v in style.items())
        + (f"（ひとこと: {pick['note']}）" if pick.get("note") else ""))
    program_path.write_text(json.dumps(program, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if log is None:
        from backend.decision_logger import DecisionLogger
        log = DecisionLogger()
    changed = {k: [before[k], v] for k, v in style.items() if before[k] != v}
    log.record_decision(target_type="program_style", target_path=str(program_path),
                        target_description=f"{program['name']} の番組共通 OP の雰囲気（見本から選択）",
                        decision="modify" if changed else "approve", reason=pick.get("note") or "（ひとことなし）",
                        mood_settings={"style": style, "changed": changed, "picked_at": pick.get("at")},
                        tags=["番組OP", "雰囲気えらび", *changed])
    log.sync_to_soul_narrative()
    return program


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="番組の雰囲気を選ぶための見本を作る")
    p.add_argument("program")
    p.add_argument("--out")
    p.add_argument("--apply", help="選択画面で決めた形（picks/latest を保存した JSON）を番組の指定に書き込む")
    p.add_argument("--only", nargs="*", help="作る見本の id（例 reveal-rise preset-quiet）")
    a = p.parse_args(argv)
    if a.apply:
        prog = apply(Path(a.program), json.loads(Path(a.apply).read_text(encoding="utf-8")))
        print(json.dumps(prog["style"], ensure_ascii=False))
        return 0
    if not a.out:
        p.error("--out か --apply のどちらかが要ります")
    program = op.load(a.program)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for v in variants(program):
        if a.only and v["id"] not in a.only:
            continue
        # 現れ方は、出てくる途中を静止画にする
        at = {"brush": 0.8, "rise": 0.45, "blur": 0.4, "stagger": 0.7}[v["choice"]] if v["axis"] == "reveal" else None
        sec = write_preview(v["program"], out / f"{v['id']}.mp4", out / f"{v['id']}.jpg", at=at)
        rows.append({k: v[k] for k in ("id", "axis", "choice", "label", "current")} | {"seconds": round(sec, 1)})
        print(v["id"], f"{sec:.1f}s")
    (out / "picker.json").write_text(json.dumps({"program": program["name"], "axes": {
        k: list(c) for k, c in op.CHOICES.items()}, "items": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
