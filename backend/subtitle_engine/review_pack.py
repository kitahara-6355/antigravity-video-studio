"""スマホで見る朱入れ画面（info@ の Apps Script ウェブアプリ）に、確認用の動画と字幕の控えを渡す。

確認用 360p を数秒ずつの小分け（HLS）にして Drive に置き、画面は要る所だけ取って再生する。
Apps Script の 1 回 50MB の上限に掛からず、シークも速い。字幕の控えと小分けの一覧は
``review_pack.json`` 1 つにまとめ、小分けと同じフォルダに置く（画面はこのフォルダの id で開く）。

使い方（リポジトリ直下で。Drive に置くには AVS_ASSETS_GOOGLE_TOKEN_JSON = drive.file が要る）::

    # 前の版の控えを、新しい版の時間と直しに合わせる（久木田回 v62 → v67 は +33.674 秒）
    PYTHONPATH=./backend python -m backend.subtitle_engine.review_pack sheet review_captions.json --offset 33.674 \\
        --fixes fixes_v67.json --run v67 --label v67 --video v67_確認用360p.mp4 --duration 2612.05 \\
        --out v67_review_captions.json
    # 小分けにする（再エンコードしない）
    PYTHONPATH=./backend python -m backend.subtitle_engine.review_pack make v67_確認用360p.mp4 v67_review_captions.json OUTDIR
    # Drive の 40_完成/<回> に「_確認用_<label>_小分け」を作って置く
    PYTHONPATH=./backend python -m backend.subtitle_engine.review_pack upload OUTDIR --parent <40_完成/<回> の id>

字幕の全文はリポジトリに入れない（Drive にだけ置く）。
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

KIND = "avs.review_pack"
PACK = "review_pack.json"
SEG_SECONDS = 6
TOKEN_ENV = "AVS_ASSETS_GOOGLE_TOKEN_JSON"  # drive.file（アプリが作った物だけ書ける）
DRIVE = "https://www.googleapis.com/drive/v3/files"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"


def shift_sheet(sheet: dict, *, offset: float, fixes: list[dict], run: str, label: str,
                video: str, duration: float) -> dict:
    """前の版の控えの時間を ``offset`` 秒ずらし、字の直し（``{cap, from, to}``）を入れる。"""
    out = copy.deepcopy(sheet)
    by_i = {c["i"]: c for c in out["captions"]}
    for f in fixes:
        c = by_i.get(f["cap"])
        if c is None or c["t"] != f["from"]:
            raise ValueError(f"直しが字幕に当たりません: cap={f['cap']} from={f['from']!r}")
        c["t"] = f["to"]
    for c in out["captions"]:
        c["s"] = round(c["s"] + offset, 3)
        c["e"] = round(c["e"] + offset, 3)
    out.update(run=run, label=label, video=video, duration=duration, flags=[])
    return out


def parse_m3u8(text: str) -> list[dict]:
    segs, dur = [], None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#EXTINF:"):
            dur = float(line[8:].split(",")[0])
        elif line and not line.startswith("#"):
            segs.append({"name": line, "dur": dur})
            dur = None
    return segs


def pack(sheet: dict, segments: list[dict]) -> dict:
    return {"version": 1, "kind": KIND, "run": sheet.get("run", ""), "label": sheet.get("label", ""),
            "video": sheet.get("video", ""), "duration": sheet.get("duration"),
            "captions": sheet.get("captions", []), "flags": sheet.get("flags", []), "segments": segments}


def segment_cmd(ffmpeg: str, video: str | Path, outdir: str | Path, seconds: int = SEG_SECONDS) -> list[str]:
    outdir = Path(outdir)
    return [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video), "-c", "copy",
            "-f", "hls", "-hls_time", str(seconds), "-hls_playlist_type", "vod",
            "-hls_segment_filename", str(outdir / "seg_%04d.ts"), str(outdir / "index.m3u8")]


def make(video: str | Path, sheet_path: str | Path, outdir: str | Path, seconds: int = SEG_SECONDS) -> Path:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    subprocess.run(segment_cmd(shutil.which("ffmpeg") or "ffmpeg", video, outdir, seconds), check=True)
    segs = parse_m3u8((outdir / "index.m3u8").read_text(encoding="utf-8"))
    sheet = json.loads(Path(sheet_path).read_text(encoding="utf-8"))
    p = outdir / PACK
    p.write_text(json.dumps(pack(sheet, segs), ensure_ascii=False), encoding="utf-8")
    size = sum((outdir / s["name"]).stat().st_size for s in segs)
    print(f"小分け {len(segs)} 個（{size / 1048576:.1f} MB）・字幕 {len(sheet.get('captions', []))} 枚 → {p}")
    return p


# ---- Drive（鍵ファイルは作らない。環境のトークンから毎回アクセストークンを取る） ----

def access_token(env: str = TOKEN_ENV) -> str:
    d = json.loads(os.environ[env])
    body = urllib.parse.urlencode({"client_id": d["client_id"], "client_secret": d["client_secret"],
                                   "refresh_token": d["refresh_token"], "grant_type": "refresh_token"}).encode()
    with urllib.request.urlopen(d.get("token_uri") or "https://oauth2.googleapis.com/token", body) as r:
        return json.load(r)["access_token"]


def _create(token: str, meta: dict, data: bytes | None = None, mime: str = "application/octet-stream") -> dict:
    q = "?supportsAllDrives=true&fields=id,name"
    if data is None:
        req = urllib.request.Request(DRIVE + q, json.dumps(meta).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    else:
        b = "avs-review-pack"
        body = (f"--{b}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(meta)}\r\n"
                f"--{b}\r\nContent-Type: {mime}\r\n\r\n").encode() + data + f"\r\n--{b}--\r\n".encode()
        req = urllib.request.Request(UPLOAD + q + "&uploadType=multipart", body, method="POST",
                                     headers={"Authorization": f"Bearer {token}",
                                              "Content-Type": f"multipart/related; boundary={b}"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429 or attempt == 3:
                raise
        import time
        time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def upload(outdir: str | Path, parent: str, name: str | None = None) -> str:
    """小分けと控えを Drive に置き、フォルダの id を返す（画面はこの id で開く）。"""
    outdir = Path(outdir)
    p = json.loads((outdir / PACK).read_text(encoding="utf-8"))
    token = access_token()
    folder = _create(token, {"name": name or f"_確認用_{p['label']}_小分け", "parents": [parent],
                             "mimeType": "application/vnd.google-apps.folder"})["id"]
    for n, s in enumerate(p["segments"], 1):
        if n % 50 == 0:
            token = access_token()
        s["id"] = _create(token, {"name": s["name"], "parents": [folder]},
                          (outdir / s["name"]).read_bytes(), "video/mp2t")["id"]
        print(f"\r置いています {n}/{len(p['segments'])}", end="", flush=True)
    print()
    (outdir / PACK).write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    _create(token, {"name": PACK, "parents": [folder]}, (outdir / PACK).read_bytes(), "application/json")
    print(f"フォルダ {folder}（画面の URL に ?pack={folder} を付けて開く）")
    return folder


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="review_pack", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sheet")
    s.add_argument("sheet")
    s.add_argument("--offset", type=float, default=0.0)
    s.add_argument("--fixes")
    s.add_argument("--run", required=True)
    s.add_argument("--label", required=True)
    s.add_argument("--video", required=True)
    s.add_argument("--duration", type=float, required=True)
    s.add_argument("--out", required=True)
    m = sub.add_parser("make")
    m.add_argument("video")
    m.add_argument("sheet")
    m.add_argument("outdir")
    m.add_argument("--seconds", type=int, default=SEG_SECONDS)
    u = sub.add_parser("upload")
    u.add_argument("outdir")
    u.add_argument("--parent", required=True)
    u.add_argument("--name")
    a = ap.parse_args(argv)
    if a.cmd == "sheet":
        sheet = json.loads(Path(a.sheet).read_text(encoding="utf-8"))
        fixes = json.loads(Path(a.fixes).read_text(encoding="utf-8")) if a.fixes else []
        out = shift_sheet(sheet, offset=a.offset, fixes=fixes, run=a.run, label=a.label,
                          video=a.video, duration=a.duration)
        Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"字幕 {len(out['captions'])} 枚（直し {len(fixes)} 件・{a.offset:+.3f} 秒）→ {a.out}")
    elif a.cmd == "make":
        make(a.video, a.sheet, a.outdir, a.seconds)
    else:
        upload(a.outdir, a.parent, a.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
