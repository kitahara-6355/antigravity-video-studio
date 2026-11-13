"""チャンネル主（美麗さん）の好みを、二択の答えから学ぶ（AI を呼ばない・0円）。

2026-11-13 北原さん承認。曲を「選んでもらう」のをやめて、同じ場面で曲だけ変えた 2 本を
「比べてもらう」。答えは info@ のウェブアプリ（apps-script/taste-picker）がシートに書き、
ここで読んで順位と「好みカルテ」の行にする。

- ``clips``: 番組 OP（曲なし）に候補曲を 1 曲ずつ敷いた見本を作る。曲の山は番組名の出だしに合わせる（music.fit）。
  曲の特徴（速さ・明るさ・音の密度・山の上がり方）も測って、見本の控え（taste_pack.json）に書く
- ``put``: 見本と控えを Drive の 30_AVS_作業/好みカルテ/<名前>/見本 に置く（drive.file）
- ``report``: 答え（シートを CSV で書き出した物か、JSON）から順位を出し、勝った曲に共通する特徴を言葉にする。
  ``--karte`` で好みカルテ（backend/config/taste/<人>.json）に「未確認」の行として足す

使い方（リポジトリ直下で）::

    python -m backend.program_package.taste clips --base 番組OP.mp4 --songs 候補曲 --sources 候補曲/sources.json \\
        --program backend/config/program/美麗の書道対談.json --out OUT --name OP曲えらび_20261113
    python -m backend.program_package.taste put OUT --dest 好みカルテ/OP曲えらび_20261113/見本
    python -m backend.program_package.taste report --pack OUT/taste_pack.json --answers 答え.csv [--karte 美麗]

YouTube など、使ってよいと決まっていない音は解析しない（規約）。候補曲は出どころの分かる無料曲だけ。
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from backend.program_package import music

PACK = "taste_pack.json"
KARTE_DIR = Path(__file__).resolve().parents[1] / "config" / "taste"
LUFS = -16.0          # 見本の曲の大きさをそろえる（大きい方を「良い」と感じる癖を消す）
FADE_IN, FADE_OUT = 0.3, 1.5
WIDTH = 640


class TasteError(RuntimeError):
    """見本が作れない・答えが読めない。"""


# --- 曲の特徴 ---------------------------------------------------------------

def features(x: np.ndarray) -> dict:
    """聞こえる区間の特徴。どれも曲どうしを比べるための目安（絶対の値ではない）。

    - bpm: 速さ
    - brightness: 音の明るさ（周波数の重心・Hz）。高いほどキラキラ、低いほど落ち着いた音
    - density: 1 秒あたりの音の立ち上がりの数。多いほど細かく弾む
    - steadiness: 拍の安定（0〜1）。低いほど途中でリズムが止まる・揺れる
    - dynamics_db: 大きい所と小さい所の差
    """
    sr = music.SR
    f = music._frames(x)
    mag = np.abs(np.fft.rfft(f * np.hanning(music.WIN), axis=1))
    freqs = np.fft.rfftfreq(music.WIN, 1 / sr)
    energy = mag.sum(axis=1)
    loud = energy > energy.max() * 0.05 if energy.size and energy.max() > 0 else np.zeros(len(energy), bool)
    cent = (mag[loud] * freqs).sum(axis=1) / (energy[loud] + 1e-9) if loud.any() else np.array([0.0])
    on = music.onsets(x)
    thr = on.mean() + on.std()
    peaks = np.where((on[1:-1] > thr) & (on[1:-1] >= on[:-2]) & (on[1:-1] >= on[2:]))[0]
    seconds = len(x) / sr
    db = music.loudness(x)
    voiced = db[db > db.max() - 40] if db.size else db
    # 拍の安定: 1 秒ごとの立ち上がりの強さが、どれだけ途切れずに続くか
    per = int(music.FPS)
    blocks = [on[i:i + per].sum() for i in range(0, max(0, len(on) - per + 1), per)]
    blocks = np.array(blocks) if blocks else np.array([0.0])
    steady = float(1 - min(1.0, blocks.std() / (blocks.mean() + 1e-9))) if blocks.mean() > 0 else 0.0
    return {
        "bpm": music.tempo(on),
        "brightness": round(float(np.median(cent)), 0),
        "density": round(len(peaks) / seconds, 2) if seconds else 0.0,
        "steadiness": round(steady, 2),
        "dynamics_db": round(float(np.percentile(voiced, 95) - np.percentile(voiced, 10)), 1) if voiced.size else 0.0,
    }


# 特徴を、美麗さんに見せる言葉にする（高い側・低い側）
WORDS = {
    "bpm": ("速め", "ゆっくり"),
    "brightness": ("明るくキラキラした音", "落ち着いた低めの音"),
    "density": ("細かく弾む", "音数が少なくゆったり"),
    "steadiness": ("リズムが途切れず続く", "リズムが止まったり揺れたりする"),
    "dynamics_db": ("盛り上がりの差が大きい", "大きさが一定"),
}


# --- 見本を作る ---------------------------------------------------------------

def _run(cmd: list[str]) -> None:
    p = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if p.returncode:
        raise TasteError(f"ffmpeg が失敗しました: {p.stderr.strip()[-400:]}")


def _duration(path: Path) -> float:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       check=False, capture_output=True, text=True)
    try:
        return float(p.stdout.strip())
    except ValueError as e:
        raise TasteError(f"長さが読めません: {path}") from e


def choose_start(song: Path, at: float, total: float) -> dict:
    """曲の使い始め。山の入りを番組名の出だし（at 秒）に合わせる。合う山が無ければ曲の頭から。"""
    a = music.analyze(song)
    try:
        f = music.fit(a, at, total)
        return {"start": max(0.0, f["start"]), "how": f"山の入り {f['climax']['at']}秒を番組名に合わせた",
                "rise_db": f["climax"]["rise_db"], "duration": a["duration"]}
    except music.MusicError:
        return {"start": 0.0, "how": "合う山が無いので曲の頭から", "rise_db": None, "duration": a["duration"]}


def measure_lufs(song: Path, start: float, total: float) -> float:
    """使う区間の大きさ（LUFS）。"""
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-ss", f"{start:.3f}", "-t", f"{total:.3f}",
                        "-i", str(song), "-vn", "-af", "ebur128", "-f", "null", "-"], check=False, capture_output=True, text=True)
    try:
        return float(p.stderr.rsplit("I:", 1)[1].split("LUFS")[0])
    except (IndexError, ValueError) as e:
        raise TasteError(f"大きさが測れません: {song}") from e


def render(base: Path, song: Path, start: float, total: float, out: Path) -> None:
    """番組 OP の絵（音は捨てる）に曲を敷いた、軽い見本（幅 640）。

    大きさは区間全体を一律に上げ下げしてそろえる（曲の中の盛り上がりはつぶさない）。
    """
    gain = max(-30.0, min(30.0, LUFS - measure_lufs(song, start, total)))
    af = (f"volume={gain:.2f}dB,alimiter=limit=0.89:level=false,afade=t=in:d={FADE_IN},"
          f"afade=t=out:st={total - FADE_OUT:.2f}:d={FADE_OUT},aresample=44100")
    _run(["ffmpeg", "-v", "error", "-y", "-i", str(base), "-ss", f"{start:.3f}", "-t", f"{total:.3f}",
          "-i", str(song), "-map", "0:v:0", "-map", "1:a:0", "-t", f"{total:.3f}",
          "-vf", f"scale={WIDTH}:-2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
          "-pix_fmt", "yuv420p", "-af", af, "-c:a", "aac", "-b:a", "128k", "-ac", "2",
          "-movflags", "+faststart", str(out)])


def make_clips(base: str | Path, songs_dir: str | Path, sources: list[dict], program: dict,
               out_dir: str | Path, name: str, question: str) -> dict:
    """候補曲ごとの見本と、控え（taste_pack.json）を作る。"""
    base, songs_dir, out_dir = Path(base), Path(songs_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    total = _duration(base)
    at = music.title_at(program)
    items = []
    for i, s in enumerate(sources):
        if s.get("skipped"):
            continue
        song = songs_dir / s["file"]
        if not song.exists():
            raise TasteError(f"曲のファイルがありません: {song}")
        st = choose_start(song, at, total)
        if st["duration"] < total:
            raise TasteError(f"曲が OP より短い: {s['file']}（{st['duration']}秒）")
        start = min(st["start"], max(0.0, st["duration"] - total))
        clip = f"{Path(s['file']).stem}.mp4"
        render(base, song, start, total, out_dir / clip)
        feat = features(music.read(song, start, total))
        rise = music.check(out_dir / clip, at)
        items.append({
            "id": Path(s["file"]).stem, "clip": clip, "title": s.get("title"), "artist": s.get("artist"),
            "track": s.get("track"), "page_url": s.get("page_url"), "page_tags": s.get("page_tags"),
            "creator_terms": s.get("creator_terms"), "start": round(start, 2), "start_how": st["how"],
            "title_rise_db": rise["rise_db"], "features": feat,
        })
    if len(items) < 2:
        raise TasteError("比べるには 2 曲以上要ります")
    pack = {
        "kind": "music", "role": "op", "name": name, "question": question,
        "program": program.get("name"), "at_title": at, "seconds": total,
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "rounds": 10, "items": items,
        "note": "曲の大きさは見本ごとに -16 LUFS にそろえた（大きい方を良いと感じる癖を消すため）",
    }
    (out_dir / PACK).write_text(json.dumps(pack, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return pack


# --- 答えから学ぶ -------------------------------------------------------------

def read_answers(path: str | Path) -> list[dict]:
    """答え。シートを CSV で書き出した物（列 json に 1 回分）か、JSON の配列。"""
    p = Path(path)
    text = p.read_text(encoding="utf-8-sig")
    if p.suffix.lower() == ".json":
        rows = json.loads(text)
    else:
        reader = csv.DictReader(text.splitlines())
        if "json" not in (reader.fieldnames or []):
            raise TasteError(f"答えのシートに json の列がありません: {path}")
        rows = [json.loads(r["json"]) for r in reader if r["json"] and r["json"].strip()]
    out = [r for r in rows if r.get("a") and r.get("b") and r.get("pick") in ("a", "b", "both", "neither")]
    if not out:
        raise TasteError(f"答えがありません: {path}")
    return out


def bradley_terry(ids: list[str], answers: list[dict], iters: int = 200) -> dict[str, float]:
    """二択の勝ち負けから、各曲の強さ（対数）。引き分け（どちらも好き・どちらも違う）は半分ずつ。

    答えの少ない曲が極端にならないよう、全曲に「仮の 1 引き分け」を足してならす。
    """
    idx = {k: i for i, k in enumerate(ids)}
    n = len(ids)
    w = np.full((n, n), 0.0)
    for r in answers:
        a, b = idx.get(r["a"]), idx.get(r["b"])
        if a is None or b is None or a == b:
            continue
        if r["pick"] == "a":
            w[a, b] += 1
        elif r["pick"] == "b":
            w[b, a] += 1
        else:
            w[a, b] += 0.5
            w[b, a] += 0.5
    w += 0.5 * (1 - np.eye(n)) / max(1, n - 1)   # ならし
    p = np.ones(n)
    games = w + w.T
    for _ in range(iters):
        wins = w.sum(axis=1)
        denom = np.array([sum(games[i, j] / (p[i] + p[j]) for j in range(n) if j != i) for i in range(n)])
        p = np.where(denom > 0, wins / denom, p)
        p /= np.exp(np.mean(np.log(p)))
    return {k: round(float(math.log(p[idx[k]])), 3) for k in ids}


def tendencies(items: list[dict], answers: list[dict], min_pairs: int = 4) -> list[dict]:
    """勝った曲の方が、その特徴が高かった（低かった）割合。偏りの強い順。

    はっきり差のある組（差が特徴の幅の 15% 以上）だけ数える。
    """
    feat = {it["id"]: it["features"] for it in items}
    out = []
    for key, (hi, lo) in WORDS.items():
        vals = [f[key] for f in feat.values() if f.get(key) is not None]
        if not vals:
            continue
        span = (max(vals) - min(vals)) or 1.0
        up = down = 0
        for r in answers:
            if r["pick"] not in ("a", "b"):
                continue
            win, lose = (r["a"], r["b"]) if r["pick"] == "a" else (r["b"], r["a"])
            if win not in feat or lose not in feat:
                continue
            d = feat[win][key] - feat[lose][key]
            if abs(d) < 0.15 * span:
                continue
            up += d > 0
            down += d < 0
        n = up + down
        if n < min_pairs:
            continue
        share = max(up, down) / n
        if share < 0.7:
            continue
        out.append({"feature": key, "word": hi if up > down else lo, "share": round(share, 2), "pairs": n})
    return sorted(out, key=lambda t: (-t["share"], -t["pairs"]))


def report(pack: dict, answers: list[dict]) -> dict:
    items = pack["items"]
    ids = [it["id"] for it in items]
    strength = bradley_terry(ids, answers)
    shown = {k: 0 for k in ids}
    won = {k: 0.0 for k in ids}
    for r in answers:
        for side in ("a", "b"):
            if r[side] in shown:
                shown[r[side]] += 1
        if r["pick"] in ("a", "b") and r[r["pick"]] in won:
            won[r[r["pick"]]] += 1
    by = {it["id"]: it for it in items}
    ranking = sorted(ids, key=lambda k: (-strength[k], -won[k]))
    notes = [{"at": r.get("at"), "a": r["a"], "b": r["b"], "pick": r["pick"], "note": r["note"]}
             for r in answers if (r.get("note") or "").strip()]
    decided = [r for r in answers if r.get("decided")]
    return {
        "name": pack.get("name"), "answers": len(answers),
        "ranking": [{"id": k, "title": by[k].get("title"), "track": by[k].get("track"),
                     "strength": strength[k], "won": won[k], "shown": shown[k]} for k in ranking],
        "top3": ranking[:3],
        "decided": decided[-1]["decided"] if decided else None,
        "tendencies": tendencies(items, answers),
        "notes": notes,
    }


def karte_lines(rep: dict, role_word: str, who: str, when: str) -> list[dict]:
    """好みカルテに足す行（未確認）。美麗さんが「そう／違う」を押すまで、決まりとしては使わない。"""
    lines = []
    top = [r for r in rep["ranking"][:3]]
    if top:
        names = "、".join(f"「{r['title']}」" + (f"（{r['track']}）" if r.get("track") else "") for r in top)
        lines.append({"topic": role_word, "statement": f"{role_word}の好きな曲の上位は {names}",
                      "evidence": f"二択 {rep['answers']} 回", "from": f"{who}・二択・{when}", "status": "未確認"})
    for t in rep["tendencies"]:
        lines.append({"topic": role_word, "statement": f"{role_word}は{t['word']}曲を選びがち",
                      "evidence": f"はっきり差のあった {t['pairs']} 組のうち {round(t['share'] * 100)}%",
                      "from": f"{who}・二択・{when}", "status": "未確認", "feature": t["feature"]})
    for n in rep["notes"]:
        lines.append({"topic": role_word, "statement": n["note"], "evidence": f"{n['a']} と {n['b']} を比べたときの一言",
                      "from": f"{who}・一言・{n.get('at') or when}", "status": "未確認"})
    return lines


def add_to_karte(person: str, lines: list[dict], karte_dir: Path = KARTE_DIR) -> Path:
    path = karte_dir / f"{person}.json"
    karte = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "_doc": "チャンネル主の好みカルテ。行の status は 未確認 → そう（決まりとして使う）／違う（使わない）。"
                "そう・違うは本人が押す。AI は 未確認 の行を足すだけで、そう にはしない",
        "person": person, "lines": []}
    have = {(x["topic"], x["statement"]) for x in karte["lines"]}
    for ln in lines:
        if (ln["topic"], ln["statement"]) not in have:
            karte["lines"].append(ln)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(karte, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


# --- コマンド -----------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    from backend.program_package import opening
    p = argparse.ArgumentParser(description="二択の答えから、チャンネル主の好みを学ぶ")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("clips")
    c.add_argument("--base", required=True, help="番組 OP の動画（音は使わない）")
    c.add_argument("--songs", required=True)
    c.add_argument("--sources", required=True)
    c.add_argument("--program", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--name", required=True)
    c.add_argument("--question", default="番組のはじまりに合う曲は、どっち？")
    u = sub.add_parser("put")
    u.add_argument("out")
    u.add_argument("--dest", required=True, help="30_AVS_作業 の下の場所")
    r = sub.add_parser("report")
    r.add_argument("--pack", required=True)
    r.add_argument("--answers", required=True)
    r.add_argument("--karte", help="好みカルテに足す人の名前（例 美麗）")
    r.add_argument("--role-word", default="番組のはじまり（OP）")
    a = p.parse_args(argv)
    try:
        if a.cmd == "clips":
            src = json.loads(Path(a.sources).read_text(encoding="utf-8-sig"))
            src = src.get("tracks", src) if isinstance(src, dict) else src
            pack = make_clips(a.base, a.songs, src, opening.load(a.program), a.out, a.name, a.question)
            for it in pack["items"]:
                print(f"{it['id']}: start {it['start']}秒（{it['start_how']}）・番組名で {it['title_rise_db']} dB 上がる・"
                      f"{json.dumps(it['features'], ensure_ascii=False)}")
            return 0
        if a.cmd == "put":
            from backend import asset_store
            manifest = asset_store.put_tree(asset_store._build_drive(), a.out, a.dest)
            print(json.dumps(manifest, ensure_ascii=False, indent=1))
            return 0
        pack = json.loads(Path(a.pack).read_text(encoding="utf-8"))
        rep = report(pack, read_answers(a.answers))
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        if a.karte:
            when = datetime.now().strftime("%Y-%m-%d")
            path = add_to_karte(a.karte, karte_lines(rep, a.role_word, f"{a.karte}さん", when))
            print(f"好みカルテに足しました（未確認）: {path}", file=sys.stderr)
    except (TasteError, music.MusicError) as e:
        print(f"止めました: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
