"""書き出した Shorts を、投稿の順番に並べた投稿用フォルダにまとめる（AI を呼ばない・0円）。

- 動画は `NN_<key>_<名前>.mp4`（NN は投稿の順番）に写す。中身は変えない
- `投稿文.txt` に1本ずつタイトル・説明・ハッシュタグを書く。本編の URL は公開後に指定へ入れる
- 投稿は北原さんが手で行う（AI は投稿しない）

使い方（リポジトリ直下で）::

    python -m backend.program_package.shorts_kit SPEC.json --rendered DIR --out DIR
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

TITLE_MAX = 100  # YouTube のタイトルの上限（二次情報）
MAX_SECONDS = 60  # 北原さんの決まり（60秒以内）


def post_text(spec: dict, key: str) -> dict:
    """1本分の投稿文（title・description・tags）。{main} は本編の URL（未定なら【公開後に入れる】）。"""
    posts = spec["posts"]
    item = posts["items"][key]
    main = posts.get("main_url") or "【本編の公開後に URL を入れる】"
    tags = posts["tags"] + item.get("tags", [])
    lines = item["body"] + [""] + [s.replace("{main}", main) for s in posts["footer"]] + ["", " ".join(tags)]
    return {"title": item["title"], "description": "\n".join(lines), "tags": tags}


def problems(spec: dict) -> list[str]:
    """投稿文の不備（順番の漏れ・タイトルの長さ・タグの重なり）。空なら出せる。"""
    out = []
    order = spec["post_order"]["order"]
    keys = {c["key"] for c in spec["clips"]}
    if sorted(order) != sorted(keys):
        out.append(f"投稿の順番と切り出した本数が合わない: {order}")
    for k in order:
        if k not in spec["posts"]["items"]:
            out.append(f"{k}: 投稿文が無い")
            continue
        t = post_text(spec, k)
        if len(t["title"]) > TITLE_MAX:
            out.append(f"{k}: タイトルが {len(t['title'])} 字（{TITLE_MAX} 字まで）")
        if len(t["tags"]) != len(set(t["tags"])):
            out.append(f"{k}: ハッシュタグが重なっている")
    return out


def duration(mp4: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp4)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout)


def build(spec: dict, rendered: Path, out: Path) -> Path:
    bad = problems(spec)
    if bad:
        raise SystemExit("投稿文に不備があります:\n" + "\n".join(bad))
    rec = spec["recording"]
    long = [f"{k}: {d:.1f}秒" for k in spec["post_order"]["order"]
            if (d := duration(rendered / f"{rec}_{k}.mp4")) > MAX_SECONDS]
    if long:
        raise SystemExit(f"{MAX_SECONDS}秒を超えています（区間を詰めて書き出し直す）:\n" + "\n".join(long))
    out.mkdir(parents=True, exist_ok=True)
    doc = [f"Shorts 投稿用（{rec}）", f"順番: {' → '.join(spec['post_order']['order'])}・{spec['post_order']['pace']}", ""]
    for n, k in enumerate(spec["post_order"]["order"], 1):
        item = spec["posts"]["items"][k]
        name = f"{n:02d}_{k}_{item['label']}.mp4"
        shutil.copyfile(rendered / f"{rec}_{k}.mp4", out / name)
        t = post_text(spec, k)
        doc += [f"■ {n:02d} {name}", "【タイトル】", t["title"], "【説明】", t["description"], ""]
    (out / "投稿文.txt").write_text("\n".join(doc), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Shorts を投稿の順番の投稿用フォルダにまとめる")
    p.add_argument("spec")
    p.add_argument("--rendered", required=True, help="shorts で書き出した mp4 のフォルダ")
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    spec = json.loads(Path(a.spec).read_text(encoding="utf-8"))
    print(build(spec, Path(a.rendered), Path(a.out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
