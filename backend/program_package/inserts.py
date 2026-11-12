"""B ロール（画像インサート）の案を字幕から自動で出し、承認した分だけ差し込む（AI を呼ばない・0円）。

- 話の内容（承認済みの字幕）から、差し込む絵と時刻・長さ・入れ方（小窓か全画面）を決める
- 絵は2種類: **収録の中の絵**（色紙や作品が大きく映ったコマ。映像を見る目の地図から自動で拾う）と、
  **素材**（写真・資料・作品。素材の一覧 materials に、権利と人の写り込みを書いた物だけ）
- 使えない素材は案に出さない: 権利が未確認・他社の物、人の写り込みが未確認、AI が作った絵、動画
- 小窓は頭に掛からない所へ置く（地図の「頭の来る所」と字幕の帯を避ける）。置けなければ全画面
  （字幕の帯は残す）
- 始まりと終わりは字幕の切れ目。場面の切れ目・章の見出し・テロップ・名前のポップとは重ねない
- 収録の中の絵は、それが映った後の話にだけ出す（先に見せない）
- 絵が無い言葉は「素材待ち」に出す（撮る・借りる物の一覧になる）
- **案は承認されるまで入らない。** 承認は人だけ（承認できる人は program_approvals.json の approvers）。
  承認の後に時刻や絵が変わった案は、承認が外れる

使い方（リポジトリ直下で）::

    python -m backend.program_package.inserts propose SPEC.json --captions LOCK.json --map 地図.json
    python -m backend.program_package.inserts sheet SPEC.json --video 完成版.mp4 --out 案の一覧.jpg
    python -m backend.program_package.inserts approve SPEC.json --ids i01,i03 --by 北原 --evidence "11/12 チャット「1と3を入れて」"
    python -m backend.program_package.inserts reject SPEC.json --ids i02 --by 北原 --evidence "…"
    python -m backend.program_package.inserts render SPEC.json --video 完成版.mp4 --out 差し込み版.mp4

案の置き場は ``backend/config/inserts/<収録ID>.json``（``setup`` は人が書く所、``items`` 以下は propose が書く）。
時刻はすべて完成版（OP を付ける前）の時刻。OP 付きの版に差し込むときは ``--offset`` に OP の長さを渡す。
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from backend.program_package import vision

ROOT = Path(__file__).resolve().parents[2]
STORE = ROOT / "backend" / "config" / "inserts"
APPROVERS = ROOT / "backend" / "config" / "program_approvals.json"
W, H = vision.W, vision.H
FRAME = (24, 37, 1163, 683)   # 収録の絵がある所（thumbnail.FRAME と同じ）
FLOOR = vision.FLOOR          # これより下は字幕の帯
FADE = 0.4
MIN_SECONDS, MAX_SECONDS = 4.0, 8.0
SHORTEST = 2.5                # 切れ目で詰めた結果これより短くなる案は出さない
CLUSTER_GAP = 45.0            # 同じ言葉がこの秒数以内に続いたら、ひとまとまりの話とみなす
APART = 20.0                  # 差し込みどうしの間隔
GENERIC = 12                  # これより多く出てくる言葉は、話題ではなく地の言葉とみなして素材待ちに出さない
PIP_HEIGHTS = (330, 290, 250, 210)
PIP_MAX_W = 520
PIP_MARGIN = 12
OK_RIGHTS = ("own", "permitted")
OK_PEOPLE = ("none", "consented")
PROPOSED, APPROVED, REJECTED = "proposed", "approved", "rejected"


class InsertError(RuntimeError):
    """案が作れない・承認できない・書き出せない。"""


# ---- 言葉 ----

def norm(s: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or "")).lower()


def tags_of(package_text: str) -> list[str]:
    """投稿パッケージの「■ タグ」の行。"""
    m = re.search(r"■\s*タグ\s*\n(.+)", package_text or "")
    return [t.strip() for t in re.split(r"[,、]", m.group(1)) if t.strip()] if m else []


def topic_words(spec: dict, package_text: str, setup: dict) -> list[str]:
    """絵があると伝わりやすい言葉の候補: テロップの見出し（かぎ括弧の中も）・タグ・人が足した言葉。

    人の名前と番組名は除く（顔は映っている）。
    """
    words: list[str] = []
    for tp in spec.get("telops", []):
        inner = re.findall(r"[「『]([^」』]+)[」』]", tp["head"])
        words += inner or [tp["head"]]
    words += tags_of(package_text) + list(setup.get("extra_keywords", []))
    title = norm(" ".join(str(v) for v in (spec.get("title") or {}).values()))
    skip = {norm(w) for w in setup.get("skip_keywords", [])}
    out: list[str] = []
    for w in words:
        n = norm(w)
        if n and n not in skip and n not in title and n not in {norm(o) for o in out}:
            out.append(w)
    return out


def mentions(captions: list[dict], word: str) -> list[int]:
    n = norm(word)
    return [i for i, c in enumerate(captions) if n in norm(c["text"])]


def clusters(idx: list[int], captions: list[dict], gap: float = CLUSTER_GAP) -> list[list[int]]:
    out: list[list[int]] = []
    for i in idx:
        if out and captions[i]["start"] - captions[out[-1][-1]]["end"] <= gap:
            out[-1].append(i)
        else:
            out.append([i])
    return out


def slot(captions: list[dict], i: int, breaks: list[float]) -> tuple[float, float] | None:
    """字幕 i から始まる差し込みの区間。字幕の切れ目で終え、場面の切れ目はまたがない。"""
    start = captions[i]["start"]
    end = captions[i]["end"]
    j = i
    while end - start < MIN_SECONDS and j + 1 < len(captions) and captions[j + 1]["start"] - end < 1.0:
        j += 1
        end = captions[j]["end"]
    end = min(max(end, start + MIN_SECONDS), start + MAX_SECONDS)
    for b in breaks:
        if start < b < end:
            end = b - 0.2
    return (round(start, 2), round(end, 2)) if end - start >= SHORTEST else None


# ---- 絵（収録の中・素材） ----

def unusable(mat: dict) -> str | None:
    """素材が案に出せない理由。出せるなら None。"""
    if mat.get("ai_generated"):
        return "AI が作った絵は使わない"
    if mat.get("kind", "image") != "image":
        return "動画の素材はまだ扱わない（後送）"
    if mat.get("rights") not in OK_RIGHTS:
        return f"権利が未確認（rights: {mat.get('rights', '未記入')}。自社の物 own か、許可を得た物 permitted だけ）"
    if mat.get("people") not in OK_PEOPLE:
        return f"人の写り込みが未確認（people: {mat.get('people', '未記入')}。写っていない none か、了解済み consented だけ）"
    return None


def board_sources(m: dict, setup: dict) -> list[dict]:
    """収録の中で色紙や作品が大きく映った所を、差し込む絵にする。いちばん長く映った区間の真ん中のコマ。"""
    words = setup.get("board_keywords", [])
    sp = vision.board_spans(m) if m else []
    if not words or not sp:
        return []
    a, b = max(sp, key=lambda s: s[1] - s[0])
    rows = [r for r in m["frames"] if a <= r["t"] <= b and r.get("board")]
    row = rows[len(rows) // 2]
    return [{"id": "board", "kind": "recording", "at": row["t"], "crop": row["board"], "keywords": words,
             "title": setup.get("board_title", ""), "visible_from": sp[0][0], "spans": sp}]


def extra_sources(setup: dict) -> list[dict]:
    """人が指した収録の中の絵（setup.recording_sources: id・at・crop・keywords）。"""
    return [{"kind": "recording", "visible_from": s["at"], "spans": [[s["at"], s["at"]]], **s}
            for s in setup.get("recording_sources", [])]


# ---- 置き場 ----

def _clash(box: list[int], zones: list[list[int]], margin: int) -> bool:
    return any(box[0] - margin < z[2] and z[0] < box[2] + margin and box[1] - margin < z[3] and z[1] < box[3] + margin
               for z in zones)


def place(zones: list[list[int]], aspect: float) -> tuple[str, list[int]]:
    """小窓の置き場（頭に掛からず、字幕の帯に入らない、いちばん大きい所）。無ければ全画面。"""
    x0, y0, x1, y1 = FRAME[0] + PIP_MARGIN, FRAME[1] + PIP_MARGIN, FRAME[2] - PIP_MARGIN, FLOOR - PIP_MARGIN
    for h in PIP_HEIGHTS:
        w = round(h * aspect)
        if w > PIP_MAX_W:
            w, h = PIP_MAX_W, round(PIP_MAX_W / aspect)
        best = None
        for y in range(y0, y1 - h + 1, 16):
            for x in range(x0, x1 - w + 1, 16):
                box = [x, y, x + w, y + h]
                if _clash(box, zones, PIP_MARGIN):
                    continue
                # 頭からいちばん離れた所。同じなら上・外側
                far = min((max(z[0] - box[2], box[0] - z[2], z[1] - box[3], box[1] - z[3]) for z in zones), default=0)
                key = (far, -y, abs(x + w / 2 - W / 2))
                if best is None or key > best[0]:
                    best = (key, box)
        if best:
            return "pip", best[1]
    return "full", full_box(aspect)


def full_box(aspect: float) -> list[int]:
    x0, y0, x1, y1 = FRAME[0] + 60, FRAME[1] + 16, FRAME[2] - 60, FLOOR - 16
    h = y1 - y0
    w = round(h * aspect)
    if w > x1 - x0:
        w, h = x1 - x0, round((x1 - x0) / aspect)
    x, y = (x0 + x1 - w) // 2, (y0 + y1 - h) // 2
    return [x, y, x + w, y + h]


def aspect_of(src: dict, root: Path | None = None) -> float:
    if src["kind"] == "recording":
        c = src.get("crop") or [0, 0, W, H]
        return (c[2] - c[0]) / (c[3] - c[1])
    if src.get("size"):
        return src["size"][0] / src["size"][1]
    with Image.open(_file(src, root)) as im:
        return im.width / im.height


def _file(src: dict, root: Path | None) -> Path:
    p = Path(src["file"])
    return p if p.is_absolute() else (root or ROOT) / p


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---- 案 ----

def fingerprint(item: dict) -> str:
    core = {k: item.get(k) for k in ("at", "seconds", "mode", "box", "source")}
    return hashlib.sha256(json.dumps(core, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def propose(spec: dict, captions: list[dict], m: dict | None, setup: dict | None = None,
            materials: list[dict] | None = None, package_text: str = "", root: Path | None = None) -> dict:
    """字幕と地図と素材の一覧から、差し込みの案・素材待ち・外した素材を出す。"""
    setup = setup or {}
    excluded = [{"id": mt.get("id"), "title": mt.get("title", ""), "reason": r}
                for mt in materials or [] if (r := unusable(mt))]
    sources = board_sources(m, setup) + extra_sources(setup) + [
        {"kind": "material", **mt} for mt in materials or [] if not unusable(mt)]
    body = vision._body(spec) if spec.get("package") else []
    busy = sorted((o["at"], o["at"] + o["seconds"], o["label"]) for o in vision.overlay_times(spec, body)) \
        if spec.get("package") else []
    breaks = sorted(set((vision.cuts(m) if m else []) + list(setup.get("cut_points", []))))

    cands, skipped = [], []
    for src in sources:
        per = 0
        for word in src.get("keywords", []):
            for cl in clusters(mentions(captions, word), captions):
                if per >= setup.get("max_per_source", 2):
                    break
                got, why = None, ""
                for i in cl:
                    c = captions[i]
                    if src["kind"] == "recording" and c["start"] < src["visible_from"]:
                        why = "まだ映っていない絵は先に見せない"
                        continue
                    if any(a - 1 <= c["start"] <= b + 1 for a, b in src.get("spans", [])):
                        why = "いま映っている"
                        continue
                    s = slot(captions, i, breaks)
                    if not s:
                        why = "場面の切れ目が近くて短い"
                        continue
                    hit = next((lab for a, b, lab in busy if s[0] < b + 0.5 and a - 0.5 < s[1]), None)
                    if hit:
                        why = f"ほかの飾りと重なる（{hit}）"
                        continue
                    got = (i, s)
                    break
                if got:
                    cands.append((got[1][0], got[1][1], word, src, captions[got[0]]["text"]))
                    per += 1
                else:
                    skipped.append({"keyword": word, "source": src["id"], "at": captions[cl[0]]["start"], "reason": why})

    items, last = [], -1e9
    for a, b, word, src, text in sorted(cands, key=lambda c: c[0]):
        if a < last + APART:
            skipped.append({"keyword": word, "source": src["id"], "at": a, "reason": f"前の差し込みから {APART:.0f} 秒以内"})
            continue
        zones = vision.head_zones(m, a, b - a) if m else []
        mode, box = place(zones, aspect_of(src, root))
        source = {k: src[k] for k in ("kind", "id", "at", "crop", "file", "title") if src.get(k) not in (None, "")}
        if src["kind"] == "material":
            source["sha256"] = _sha(_file(src, root))
        item = {"id": f"i{len(items) + 1:02d}", "at": a, "seconds": round(b - a, 2), "mode": mode, "box": box,
                "keyword": word, "caption": text.replace("\n", " "), "source": source, "state": PROPOSED,
                "reason": f"「{word}」の話に合わせて{'小窓' if mode == 'pip' else '全画面（小窓の置ける壁が無い）'}で出す"}
        item["fingerprint"] = fingerprint(item)
        items.append(item)
        last = b

    have = {norm(w) for s in sources for w in s.get("keywords", [])}
    wanted = []
    for word in topic_words(spec, package_text, setup):
        idx = mentions(captions, word)
        if norm(word) in have or not idx or len(idx) > GENERIC:
            continue
        c = captions[idx[0]]
        wanted.append({"keyword": word, "at": round(c["start"], 2), "mentions": len(idx),
                       "caption": c["text"].replace("\n", " "),
                       "note": "絵が無い。自社の物か、許可を得た物があれば materials に足す"})
    return {"items": items, "wanted": sorted(wanted, key=lambda w: w["at"]), "excluded": excluded, "skipped": skipped}


def merge(old: dict | None, new: dict) -> dict:
    """前の案の承認・見送りを、中身が同じ案にだけ引き継ぐ。変わった案は「提案」に戻る。"""
    kept = {it["fingerprint"]: it for it in (old or {}).get("items", []) if it.get("state") != PROPOSED}
    for it in new["items"]:
        prev = kept.get(it["fingerprint"])
        if prev:
            it["state"], it["decision"] = prev["state"], prev.get("decision")
    return {"setup": (old or {}).get("setup", {}), **new}


def approvers() -> list[str]:
    return json.loads(APPROVERS.read_text(encoding="utf-8")).get("approvers", [])


def decide(plan: dict, ids: list[str], state: str, *, by: str, evidence: str, people: list[str] | None = None) -> dict:
    """人が見て決めたことを控える。AI の名前では決められない。"""
    people = approvers() if people is None else people
    by = (by or "").strip()
    if by not in people:
        raise InsertError(f"決められるのは {'・'.join(people)} だけです: 「{by}」（AI は承認しない — 憲法第4条）")
    if not (evidence or "").strip():
        raise InsertError("どこで決まったかを --evidence に書いてください（チャットの日時と言葉）")
    known = {it["id"]: it for it in plan["items"]}
    missing = [i for i in ids if i not in known]
    if missing:
        raise InsertError(f"案がありません: {'・'.join(missing)}")
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="seconds")
    for i in ids:
        known[i]["state"] = state
        known[i]["decision"] = {"by": by, "at": now, "evidence": evidence.strip(), "fingerprint": fingerprint(known[i])}
    return plan


def approved(plan: dict) -> list[dict]:
    """差し込んでよい案（承認済みで、承認の後に中身が変わっていない物）。"""
    return [it for it in plan.get("items", []) if it.get("state") == APPROVED
            and (it.get("decision") or {}).get("fingerprint") == fingerprint(it)]


# ---- 絵にする ----

def picture(item: dict, video: Path | None, offset: float = 0.0, root: Path | None = None) -> Image.Image:
    src = item["source"]
    if src["kind"] == "material":
        if _sha(_file(src, root)) != src.get("sha256"):
            raise InsertError(f"素材の中身が、案を出したときと違います: {src['id']}（propose からやり直す）")
        return Image.open(_file(src, root)).convert("RGB")
    if video is None:
        raise InsertError("収録の中の絵には --video が要ります")
    png = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{src['at'] + offset:.3f}", "-i", str(video), "-frames:v", "1",
                          "-vf", f"scale={W}:{H}", "-f", "image2pipe", "-c:v", "png", "-"],
                         capture_output=True, check=True).stdout
    import io
    im = Image.open(io.BytesIO(png)).convert("RGB")
    return im.crop(tuple(src["crop"])) if src.get("crop") else im


def card(item: dict, pic: Image.Image) -> Image.Image:
    """差し込みの1枚（透明の 1280x720）。白い縁と金の線、うすい影。全画面は絵の所を暗くする。"""
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    x0, y0, x1, y1 = item["box"]
    if item["mode"] == "full":
        ImageDraw.Draw(im).rectangle([FRAME[0], FRAME[1], FRAME[2], FLOOR], fill=(20, 8, 18, 215))
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rectangle([x0 + 4, y0 + 6, x1 + 10, y1 + 12], fill=(0, 0, 0, 130))
    im.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(6)))
    d = ImageDraw.Draw(im)
    d.rectangle([x0 - 6, y0 - 6, x1 + 6, y1 + 6], fill=(214, 164, 70, 255))
    d.rectangle([x0 - 4, y0 - 4, x1 + 4, y1 + 4], fill=(255, 255, 255, 255))
    im.paste(pic.resize((x1 - x0, y1 - y0), Image.LANCZOS), (x0, y0))
    return im


def shows(items: list[dict], video: Path | None, tmp: Path, offset: float = 0.0, root: Path | None = None
          ) -> list[tuple[Path, float, float]]:
    """本編に重ねる (絵, 時刻, 秒) の一覧。episode の飾りと同じ形（V5 でそのまま足せる）。"""
    out = []
    for it in items:
        png = tmp / f"{it['id']}.png"
        card(it, picture(it, video, offset, root)).save(png)
        out.append((png, it["at"] + offset, it["seconds"]))
    return out


def render(plan: dict, video: Path, out: Path, offset: float = 0.0, root: Path | None = None,
           crf: int = 18, preset: str = "medium") -> Path:
    """承認した案だけを重ねた版を書き出す。音はそのまま写す。"""
    items = approved(plan)
    if not items:
        raise InsertError("承認済みの案がありません（approve で控えてから）")
    vw, vh, _ = vision.probe(video)
    with tempfile.TemporaryDirectory() as t:
        inputs, g, cur = ["-i", str(video)], [], "0:v"
        for k, (png, at, sec) in enumerate(shows(items, video, Path(t), offset, root), start=1):
            inputs += ["-loop", "1", "-framerate", "30", "-t", f"{sec:.2f}", "-i", str(png)]
            g.append(f"[{k}:v]format=rgba,scale={vw}:{vh},fade=in:st=0:d={FADE}:alpha=1,"
                     f"fade=out:st={sec - FADE:.2f}:d={FADE}:alpha=1,setpts=PTS+{at:.3f}/TB[s{k}];"
                     f"[{cur}][s{k}]overlay=0:0:eof_action=pass[m{k}]")
            cur = f"m{k}"
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(g), "-map", f"[{cur}]",
                        "-map", "0:a?", "-c:v", "libx264", "-crf", str(crf), "-preset", preset, "-pix_fmt", "yuv420p",
                        "-c:a", "copy", "-movflags", "+faststart", str(out)], check=True)
    return out


def sheet(plan: dict, video: Path, out: Path, offset: float = 0.0, root: Path | None = None, cols: int = 3) -> Path:
    """案を1枚ずつ、差し込んだ見え方で並べた一覧（承認のときに見る絵）。"""
    from backend.program_package import thumbnail as th
    tiles = []
    for it in plan["items"]:
        at = it["at"] + offset + min(1.0, it["seconds"] / 2)
        png = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{at:.3f}", "-i", str(video), "-frames:v", "1",
                              "-vf", f"scale={W}:{H}", "-f", "image2pipe", "-c:v", "png", "-"],
                             capture_output=True, check=True).stdout
        import io
        base = Image.open(io.BytesIO(png)).convert("RGBA")
        base.alpha_composite(card(it, picture(it, video, offset, root)))
        tile = Image.new("RGB", (640, 400), (24, 24, 28))
        tile.paste(base.convert("RGB").resize((640, 360)), (0, 40))
        mark = {APPROVED: "承認", REJECTED: "見送り"}.get(it["state"], "提案")
        label = f"{it['id']}  {int(it['at']) // 60}:{int(it['at']) % 60:02d}  {it['seconds']:.1f}秒  " \
                f"{'小窓' if it['mode'] == 'pip' else '全画面'}  「{it['keyword']}」  {mark}"
        try:
            f = th.font("gothic", 22)
        except OSError:
            f, label = None, label.encode("ascii", "ignore").decode()
        ImageDraw.Draw(tile).text((10, 8), label, font=f, fill="white")
        tiles.append(tile)
    if not tiles:
        raise InsertError("案がありません")
    cols = min(cols, len(tiles))
    rows = -(-len(tiles) // cols)
    grid = Image.new("RGB", (640 * cols, 400 * rows), (24, 24, 28))
    for i, t in enumerate(tiles):
        grid.paste(t, (640 * (i % cols), 400 * (i // cols)))
    out.parent.mkdir(parents=True, exist_ok=True)
    grid.save(out, quality=88)
    return out


# ---- コマンド ----

def store_of(spec: dict) -> Path:
    return STORE / f"{spec['recording']}.json"


def load_plan(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"setup": {}, "items": []}


def save_plan(path: Path, plan: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def report(plan: dict) -> str:
    def ts(t):
        return f"{int(t) // 60}:{int(t) % 60:02d}"
    lines = [f"差し込みの案 {len(plan['items'])} 件"]
    lines += [f"  {it['id']} {ts(it['at'])} {it['seconds']:.1f}秒 {'小窓' if it['mode'] == 'pip' else '全画面'} "
              f"「{it['keyword']}」← {it['source']['id']}（{it['state']}）  {it['caption']}" for it in plan["items"]]
    lines.append(f"素材待ち {len(plan.get('wanted', []))} 件")
    lines += [f"  {ts(w['at'])} 「{w['keyword']}」{w['mentions']}回  {w['caption']}" for w in plan.get("wanted", [])]
    if plan.get("excluded"):
        lines.append(f"外した素材 {len(plan['excluded'])} 件")
        lines += [f"  {e['id']} {e['reason']}" for e in plan["excluded"]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="B ロール（画像インサート）の案を出し、承認した分だけ差し込む")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("propose", "sheet", "approve", "reject", "render", "list"):
        s = sub.add_parser(name)
        s.add_argument("spec")
        s.add_argument("--plan", help="案の置き場（既定は backend/config/inserts/<収録ID>.json）")
        if name == "propose":
            s.add_argument("--captions", required=True, help="承認済みの字幕（固定 lock か *.subtitles.json）")
            s.add_argument("--map", help="映像を見る目の地図（vision scan）")
            s.add_argument("--materials", help="素材の一覧（JSON の配列）")
        if name in ("sheet", "render"):
            s.add_argument("--video", required=True)
            s.add_argument("--out", required=True)
            s.add_argument("--offset", type=float, default=0.0, help="OP 付きの版なら OP の長さ（秒）")
            s.add_argument("--materials-root", help="素材の file が相対のときの基準")
        if name in ("approve", "reject"):
            s.add_argument("--ids", required=True)
            s.add_argument("--by", required=True)
            s.add_argument("--evidence", required=True)
    a = p.parse_args(argv)
    spec = json.loads(Path(a.spec).read_text(encoding="utf-8"))
    path = Path(a.plan) if a.plan else store_of(spec)
    plan = load_plan(path)
    try:
        if a.cmd == "propose":
            caps = json.loads(Path(a.captions).read_text(encoding="utf-8"))["segments"]
            mats = json.loads(Path(a.materials).read_text(encoding="utf-8")) if a.materials else []
            pkg = Path(spec["package"]).read_text(encoding="utf-8") if spec.get("package") else ""
            m = vision.load(a.map) if a.map else None
            root = Path(a.materials).parent if a.materials else None
            plan = merge(plan, propose(spec, caps, m, plan.get("setup"), mats, pkg, root))
            save_plan(path, plan)
        elif a.cmd in ("approve", "reject"):
            decide(plan, a.ids.split(","), APPROVED if a.cmd == "approve" else REJECTED, by=a.by, evidence=a.evidence)
            save_plan(path, plan)
        elif a.cmd == "sheet":
            print(sheet(plan, Path(a.video), Path(a.out), a.offset, Path(a.materials_root) if a.materials_root else None))
            return 0
        elif a.cmd == "render":
            print(render(plan, Path(a.video), Path(a.out), a.offset, Path(a.materials_root) if a.materials_root else None))
            return 0
    except (InsertError, vision.VisionError) as e:
        print(f"止めました: {e}", file=sys.stderr)
        return 1
    print(report(plan))
    return 0


if __name__ == "__main__":
    sys.exit(main())
