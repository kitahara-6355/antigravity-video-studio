"""サムネの顔えらび（2026-11-21 北原さん「サムネも好みカルテのように、美麗さんに候補を見てもらい直していく」）。

好みえらびのページ（taste-picker）をそのまま使い、曲の動画の代わりに顔の写真を 2 枚並べて比べてもらう。
答えから「どんな顔を選びがちか」の重みを学び、次の回の候補（vision thumbs --learned）に返す。
AI は呼ばない・0円。

    python -m backend.program_package.thumb_pick pack --map map.json --video 本編.mp4 --side left \\
        --person 美麗 --name サムネの顔_YYYYMMDD --out OUT [--from 40 --to 2590]
    python -m backend.program_package.taste put OUT --dest 好みカルテ/サムネの顔_YYYYMMDD/見本
    python -m backend.program_package.thumb_pick learn --pack OUT/taste_pack.json --answers 答え.csv \\
        --learned backend/config/taste/サムネの顔.json [--karte 美麗]
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from backend.program_package import taste, vision

FEATURES = ("smile", "sharp", "eyes", "mouth", "both")
WORDS = {
    "smile": ("大きな笑顔", "控えめな笑顔"),
    "sharp": ("くっきり写った", "やわらかい写り"),
    "eyes": ("目がはっきり開いた", "目を細めた"),
    "mouth": ("口を大きく開けた", "口を閉じ気味の"),
    "both": ("二人とも笑っている", "一人だけ笑っている"),
}
REASONS = ["笑顔が自然", "目が細い", "口が開きすぎ", "表情がかたい", "暗い・ぼやけ", "顔の向きがいい"]
SCALE = 4.0      # 重み 1 の差 ＝ 勝ちやすさ 4（対数オッズ）。初期値の強さを決める
PRIOR = 1.0      # 初期値（2026-11-15 設計の重み）に引き戻す強さ。答えが少ないうちは初期値のまま


class ThumbPickError(RuntimeError):
    pass


def crop_box(box: list[int], w: int = vision.W, h: int = vision.H) -> tuple[int, int, int, int]:
    """顔の矩形から、頭と肩まで入る縦長（4:5）の切り抜き。画面の外には出さない。"""
    x0, y0, x1, y1 = box
    fh = max(1, y1 - y0)
    ch = min(h, int(fh * 3.4))
    cw = min(w, int(ch * 0.8))
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2 + int(fh * 0.55)
    left = min(max(0, cx - cw // 2), w - cw)
    top = min(max(0, cy - ch // 2), h - ch)
    return left, top, cw, ch


def grab(video: Path, t: float, box: list[int], out: Path) -> None:
    x, y, cw, ch = crop_box(box)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                    "-vf", f"scale={vision.W}:{vision.H},crop={cw}:{ch}:{x}:{y},scale=640:800", "-q:v", "3",
                    str(out)], check=True)


def choose(m: dict, side: str, n: int = 10, extra: int = 4) -> list[dict]:
    """比べる顔。いまの選び方の上位 n と、学ぶための「ためし」extra（笑顔の基準を半分までゆるめた所から、時刻をばらして）。"""
    main = vision.smile_candidates(m, side, n=n)
    wide = [c for c in vision.smile_candidates(m, side, n=n * 6, top=0.5)
            if all(abs(c["t"] - x["t"]) >= 20 for x in main)]
    wide.sort(key=lambda c: c["t"])
    step = max(1, len(wide) // max(1, extra))
    trial = wide[::step][:extra]
    for c in trial:
        c["trial"] = True
    return main + trial


def make_pack(m: dict, video: str | Path, side: str, person: str, name: str, out_dir: str | Path,
              n: int = 10, extra: int = 4) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    picks = choose(m, side, n, extra)
    if len(picks) < 2:
        raise ThumbPickError("比べる顔が 2 つ以上見つかりませんでした")
    items = []
    for c in picks:
        cid = f"t{c['t']:07.1f}".replace(".", "_")
        grab(Path(video), c["t"], c["box"], out / f"{cid}.jpg")
        items.append({"id": cid, "clip": f"{cid}.jpg", "title": f"{int(c['t'] // 60)}:{int(c['t'] % 60):02d}",
                      "t": c["t"], "score": c["score"], "features": c["feat"], "trial": bool(c.get("trial"))})
    pack = {
        "kind": "thumb", "role": "thumb_face", "side": side, "person": person, "name": name,
        "title": "サムネの顔えらび",
        "question": "サムネに使いたいのは、どっちの顔？",
        "steps": ["動画の中の同じ人の顔が 2 枚出ます", "サムネに使いたい方を押してください"],
        "words": {"lead": "音は出ません", "minutes": "3 分ほど", "top": "いま好きな順に並べた上の 3 枚です。この中に「これ」という顔があれば、決めてください",
                  "decide": "この顔に決める", "decided": "決めた顔を記録しました。北原さんに伝わります ✦"},
        "reasons": REASONS, "rounds": 10, "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "weights_used": dict(vision.SMILE_WEIGHTS), "items": items,
    }
    (out / taste.PACK).write_text(json.dumps(pack, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return pack


def learn_weights(items: list[dict], answers: list[dict], prior: dict | None = None,
                  iters: int = 400, lr: float = 0.5) -> dict:
    """二択の答えから、特徴の重みを学ぶ（勝った顔の特徴 − 負けた顔の特徴 のロジスティック回帰）。

    初期値に PRIOR の強さで引き戻すので、答えが少ないうちは初期値から大きく動かない。
    どちらも好き・どちらも違う は半分ずつ。
    """
    prior = {**vision.SMILE_WEIGHTS, **(prior or {})}
    feat = {it["id"]: np.array([float(it["features"].get(k, 0.0)) for k in FEATURES]) for it in items}
    rows, ys = [], []
    for r in answers:
        if r.get("a") in feat and r.get("b") in feat and r.get("pick") in ("a", "b", "both", "neither"):
            rows.append(feat[r["a"]] - feat[r["b"]])
            ys.append({"a": 1.0, "b": 0.0}.get(r["pick"], 0.5))
    b0 = SCALE * np.array([prior[k] for k in FEATURES])
    b = b0.copy()
    if rows:
        x, y = np.array(rows), np.array(ys)
        for _ in range(iters):
            p = 1 / (1 + np.exp(-x @ b))
            g = x.T @ (p - y) / len(y) + PRIOR * (b - b0) / len(y)
            b -= lr * g
    return {"weights": {k: round(float(v / SCALE), 3) for k, v in zip(FEATURES, b)}, "answers": len(rows)}


def report(pack: dict, answers: list[dict], prior: dict | None = None) -> dict:
    rep = taste.report(pack, answers)
    rep["tendencies"] = taste.tendencies(pack["items"], answers, words=WORDS)
    rep["learned"] = learn_weights(pack["items"], answers, prior)
    tags: dict[str, int] = {}
    for r in answers:
        for t in r.get("tags") or []:
            tags[t] = tags.get(t, 0) + 1
    rep["tags"] = dict(sorted(tags.items(), key=lambda kv: -kv[1]))
    return rep


def karte_lines(rep: dict, who: str, when: str) -> list[dict]:
    topic = "サムネの顔"
    lines = []
    for t in rep["tendencies"]:
        lines.append({"topic": topic, "statement": f"サムネには{t['word']}顔を選びがち",
                      "evidence": f"はっきり差のあった {t['pairs']} 組のうち {round(t['share'] * 100)}%",
                      "from": f"{who}・二択・{when}", "status": "未確認", "feature": t["feature"]})
    for tag, k in rep["tags"].items():
        if k >= 2:
            lines.append({"topic": topic, "statement": f"気になったところ「{tag}」", "evidence": f"{k} 回押した",
                          "from": f"{who}・二択・{when}", "status": "未確認"})
    for n in rep["notes"]:
        lines.append({"topic": topic, "statement": n["note"], "evidence": f"{n['a']} と {n['b']} を比べたときの一言",
                      "from": f"{who}・一言・{n.get('at') or when}", "status": "未確認"})
    return lines


def save_learned(path: str | Path, side: str, person: str, learned: dict, pack_name: str) -> Path:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {
        "_doc": "サムネの顔えらび（二択）で学んだ点の重み。vision thumbs --learned で使う。人の側（left/right）ごと"}
    data[side] = {"person": person, "weights": learned["weights"], "answers": learned["answers"],
                  "from": pack_name, "at": datetime.now().strftime("%Y-%m-%d")}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="サムネの顔えらび（二択で好みを学ぶ）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("pack", help="比べる顔の写真と控え（taste_pack.json）を作る")
    c.add_argument("--map", required=True)
    c.add_argument("--video", required=True, help="地図と同じ時刻の本編（720p 以上がよい）")
    c.add_argument("--side", choices=["left", "right"], required=True)
    c.add_argument("--person", required=True)
    c.add_argument("--name", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("-n", type=int, default=10)
    c.add_argument("--extra", type=int, default=4)
    c.add_argument("--from", dest="body_from", type=float, default=0.0)
    c.add_argument("--to", dest="body_to", type=float)
    r = sub.add_parser("learn", help="答えから重みと好みカルテの行を作る")
    r.add_argument("--pack", required=True)
    r.add_argument("--answers", required=True)
    r.add_argument("--learned", help="学んだ重みを書く先（例 backend/config/taste/サムネの顔.json）")
    r.add_argument("--karte", help="好みカルテに足す人の名前（例 美麗）")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "pack":
            m = vision.trim(vision.load(a.map), a.body_from, a.body_to)
            pack = make_pack(m, a.video, a.side, a.person, a.name, a.out, a.n, a.extra)
            for it in pack["items"]:
                print(f"{it['id']} {it['title']} 点 {it['score']}{'（ためし）' if it['trial'] else ''} {it['features']}")
            return 0
        pack = json.loads(Path(a.pack).read_text(encoding="utf-8"))
        prior = None
        if a.learned and Path(a.learned).exists():
            prior = (json.loads(Path(a.learned).read_text(encoding="utf-8")).get(pack["side"]) or {}).get("weights")
        rep = report(pack, taste.read_answers(a.answers), prior)
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        if a.learned:
            save_learned(a.learned, pack["side"], pack["person"], rep["learned"], pack.get("name", ""))
        if a.karte:
            when = datetime.now().strftime("%Y-%m-%d")
            path = taste.add_to_karte(a.karte, karte_lines(rep, f"{a.karte}さん", when))
            print(f"好みカルテに足しました（未確認）: {path}", file=sys.stderr)
    except (ThumbPickError, taste.TasteError, vision.VisionError) as e:
        print(f"止めました: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
