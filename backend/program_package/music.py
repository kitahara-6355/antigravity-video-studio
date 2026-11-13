"""曲を聞いて、番組 OP のどこから使うかを決める（AI を呼ばない・0円）。

番組 OP は最後に番組名が出る。曲の「山の入り」（音が大きくなって、そのまま続く所）が
番組名の出だしに重なるように、曲の使い始め（start）を決める。これまでは人が聞いて決めていた。

- ``analyze``: 曲の速さ（BPM）・拍・山の入りの候補を出す
- ``fit``: 番組の指定（backend/config/program/*.json）から番組名の出る時刻を読み、start を決める。
  ``--write AUDIO.json`` で remix の指定（op_music.start）に書く
- ``check``: 書き出した OP（または仕上げ版の頭）で、番組名の所で実際に音が上がっているかを測る

山の入りは拍に合わせる（いちばん近い音の立ち上がり）。曲の頭や終わりに近くて OP の長さが取れない山は使わない。

使い方（リポジトリ直下で）::

    python -m backend.program_package.music analyze 曲.m4a
    python -m backend.program_package.music fit 曲.m4a --program backend/config/program/美麗の書道対談.json [--write AUDIO.json]
    python -m backend.program_package.music check 番組OP.mp4 --program backend/config/program/美麗の書道対談.json
    python -m backend.program_package.music plan AUDIO.json --program backend/config/program/美麗の書道対談.json --music-dir 曲の置き場

``plan`` は曲の台帳（backend/config/music.json）から remix の指定を丸ごと作る（OP・BGM・ED）。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

SR = 11025
HOP = 256            # 約 23 ミリ秒
WIN = 1024
FPS = SR / HOP
BEFORE, AFTER = 4.0, 4.0   # 山の入りは「前の4秒」と「後の4秒」の音の大きさを比べる
MIN_RISE_DB = 3.0          # これより小さい上がり方は山とみなさない
APART = 8.0                # 山の候補どうしの間隔
SNAP = 0.35                # 山の入りを、この範囲のいちばん強い立ち上がりに合わせる
CHECK_RISE_DB = 2.0        # 書き出した OP で、番組名の所の音がこれだけ上がっていれば合っている


class MusicError(RuntimeError):
    """曲が読めない・合う山が無い。"""


def read(path: str | Path, start: float = 0.0, seconds: float | None = None) -> np.ndarray:
    """音を 1 本（モノラル・11,025Hz）の数の列にする。"""
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{start:.3f}"]
    if seconds is not None:
        cmd += ["-t", f"{seconds:.3f}"]
    cmd += ["-i", str(path), "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode or not p.stdout:
        raise MusicError(f"音が読めません: {path}")
    return np.frombuffer(p.stdout, np.float32)


def _frames(x: np.ndarray) -> np.ndarray:
    n = 1 + max(0, (len(x) - WIN) // HOP)
    idx = np.arange(WIN)[None, :] + HOP * np.arange(n)[:, None]
    return x[idx]


def loudness(x: np.ndarray) -> np.ndarray:
    """コマごとの音の大きさ（dB）。"""
    f = _frames(x)
    return 10 * np.log10(np.mean(f * f, axis=1) + 1e-10)


def onsets(x: np.ndarray) -> np.ndarray:
    """コマごとの音の立ち上がりの強さ（音の成分が増えた分）。"""
    mag = np.abs(np.fft.rfft(_frames(x) * np.hanning(WIN), axis=1))
    flux = np.maximum(0, np.diff(np.log1p(mag * 100), axis=0)).sum(axis=1)
    return np.concatenate([[0.0], flux])


def tempo(on: np.ndarray) -> float:
    """曲の速さ（BPM・60〜180）。立ち上がりの繰り返しの間隔から。"""
    o = on - on.mean()
    if not o.any():
        return 0.0
    lo, hi = int(FPS * 60 / 180), int(FPS * 60 / 60)
    ac = np.array([np.dot(o[:-k], o[k:]) for k in range(lo, hi + 1)])
    lag, div = lo + int(ac.argmax()), 1
    # 倍の遅さに聞き違えない: 半分の間隔でも同じくらい繰り返していれば、そちらを拍とする
    while (lag // (div * 2)) - 1 >= lo:
        h = lag // (div * 2) - lo
        if ac[max(0, h - 1):h + 2].max() < 0.6 * ac.max():
            break
        div *= 2
    return round(60 * FPS * div / lag, 1)


def _mean_db(db: np.ndarray, a: int, b: int) -> float:
    seg = db[max(0, a):max(0, b)]
    return float(10 * np.log10(np.mean(10 ** (seg / 10)))) if len(seg) else -100.0


def climaxes(db: np.ndarray, on: np.ndarray, top: int = 5) -> list[dict]:
    """山の入りの候補（時刻・上がり方 dB・その後の大きさ dB）。上がり方の大きい順。"""
    nb, na = int(BEFORE * FPS), int(AFTER * FPS)
    rise = np.full(len(db), -np.inf)
    for i in range(nb, len(db) - na):
        rise[i] = _mean_db(db, i, i + na) - _mean_db(db, i - nb, i)
    out: list[dict] = []
    order = np.argsort(rise)[::-1]
    for i in order:
        if rise[i] < MIN_RISE_DB or len(out) >= top:
            break
        if any(abs(i - c["_i"]) < APART * FPS for c in out):
            continue
        w = int(SNAP * FPS)
        j = max(0, i - w) + int(on[max(0, i - w):i + w + 1].argmax())  # いちばん近い強い立ち上がり（拍）へ
        out.append({"_i": int(i), "at": round(float(j / FPS), 2), "rise_db": round(float(rise[i]), 1),
                    "after_db": round(_mean_db(db, j, j + na), 1)})
    for c in out:
        del c["_i"]
    return out


def analyze(path: str | Path) -> dict:
    x = read(path)
    db, on = loudness(x), onsets(x)
    return {"duration": round(len(x) / SR, 2), "bpm": tempo(on), "climaxes": climaxes(db, on)}


def title_at(program: dict) -> float:
    """番組 OP の中で、番組名が出始める時刻。"""
    return len(program["slides"]) * program["slide_seconds"]


def fit(analysis: dict, at: float, total: float) -> dict:
    """山の入りが OP の at 秒に来るような、曲の使い始め（start）。使える山のうち、上がり方がいちばん大きい物。"""
    ok = [c for c in analysis["climaxes"]
          if c["at"] - at >= 0 and c["at"] - at + total <= analysis["duration"]]
    if not ok:
        raise MusicError(f"番組名（{at:.1f}秒）に合わせられる山がありません。"
                         f"候補: {[c['at'] for c in analysis['climaxes']] or 'なし'}（曲の長さ {analysis['duration']}秒）")
    best = ok[0]
    return {"start": round(best["at"] - at, 2), "climax": best,
            "others": [{"start": round(c["at"] - at, 2), **c} for c in ok[1:]]}


def check(path: str | Path, at: float, window: float = 2.5) -> dict:
    """書き出した OP で、at 秒の前後の音の大きさを比べる。上がっていれば合っている。"""
    x = read(path, max(0.0, at - window), 2 * window)
    db = loudness(x)
    mid = int(min(at, window) * FPS)
    rise = _mean_db(db, mid, len(db)) - _mean_db(db, 0, mid)
    return {"at": at, "rise_db": round(rise, 1), "ok": rise >= CHECK_RISE_DB}


LEDGER = Path(__file__).resolve().parents[1] / "config" / "music.json"
ROLES = {"op": "op_music", "bgm": "bgm", "ed": "ed_music"}


def plan(program: dict, ledger: dict, music_dir: str | Path | None, quiet: list[list[float]] | None = None,
         body_seconds: float | None = None) -> dict:
    """曲の台帳から、この番組の音の指定（remix の AUDIO.json）を作る。

    - OP: 台帳に start が無ければ、曲の山の入りを番組名の出だしに合わせる
    - BGM: 本編の全体に敷く。quiet（曲を止める区間・本編の秒）があれば、そこを避けて区間を分ける
    - 出どころ（source）の無い曲は使わない。provisional の曲は印を引き継ぐ（名前に「_仮曲入り」が付く）
    """
    from backend.program_package import opening
    use = (ledger.get("programs") or {}).get(program["name"])
    if not use:
        raise MusicError(f"曲の台帳に番組「{program['name']}」がありません")
    out: dict = {"op_music": None, "bgm": None, "ed_music": None, "peak_db": ledger.get("peak_db", -1.5), "tracks": {}}
    for role, key in ROLES.items():
        r = use.get(role)
        if not r:
            continue
        t = (ledger.get("tracks") or {}).get(r["track"])
        if not t:
            raise MusicError(f"曲の台帳に曲「{r['track']}」がありません（{role}）")
        if not (t.get("source") or "").strip():
            raise MusicError(f"出どころ（source）の無い曲は使いません: {t.get('title', r['track'])}")
        if not t.get("file"):
            raise MusicError(f"曲のファイルが決まっていません: {t['title']}（曲の台帳の tracks.{r['track']}.file）")
        if music_dir is None:
            raise MusicError("曲の置き場が分かりません（--music-dir か環境変数 AVS_MUSIC_DIR）")
        path = Path(music_dir) / t["file"]
        if not path.exists():
            raise MusicError(f"曲のファイルがありません: {path}")
        item = {k: v for k, v in r.items() if k not in ("track", "start_note") and v is not None}
        item.update(path=str(path), provisional=bool(t.get("provisional")))
        if role == "op" and r.get("start") is None:
            f = fit(analyze(path), title_at(program), opening.length(program))
            item["start"] = f["start"]
            item["start_note"] = f"music が決めた（山の入り {f['climax']['at']}秒を番組名に合わせる）"
        if role == "bgm" and quiet:
            if body_seconds is None:
                raise MusicError("曲を止める区間を使うには本編の長さが要ります")
            item["ranges"] = bgm_ranges(body_seconds, quiet, float(item.get("fade", 3.0)))
        out[key] = item
        out["tracks"][role] = {k: t.get(k) for k in ("title", "artist", "source")}
    return out


def bgm_ranges(body_seconds: float, quiet: list[list[float]], fade: float = 3.0) -> list[list[float]]:
    """本編のうち BGM を敷く区間。quiet の区間（揮毫など、曲を止めたい所）を避ける。短すぎる切れ端は捨てる。"""
    out, t = [], 0.0
    for a, b in sorted(quiet):
        if a - t > 2 * fade + 4:
            out.append([round(t, 2), round(a, 2)])
        t = max(t, b)
    if body_seconds - t > 2 * fade + 4:
        out.append([round(t, 2), round(body_seconds, 2)])
    return out


def main(argv: list[str] | None = None) -> int:
    from backend.program_package import opening
    p = argparse.ArgumentParser(description="曲を聞いて、番組 OP のどこから使うかを決める")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("analyze", "fit", "check", "plan"):
        s = sub.add_parser(name)
        s.add_argument("path", help="曲（plan のときは書き出す AUDIO.json）")
        if name == "plan":
            s.add_argument("--music-dir")
        if name != "analyze":
            s.add_argument("--program", required=True)
        if name == "fit":
            s.add_argument("--write", help="remix の指定（AUDIO.json）の op_music.path と start を書き換える")
    a = p.parse_args(argv)
    try:
        if a.cmd == "analyze":
            print(json.dumps(analyze(a.path), ensure_ascii=False, indent=1))
            return 0
        program = opening.load(a.program)
        if a.cmd == "plan":
            import os
            ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
            spec = plan(program, ledger, a.music_dir or os.environ.get("AVS_MUSIC_DIR"))
            Path(a.path).write_text(json.dumps(spec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print(json.dumps(spec, ensure_ascii=False, indent=1))
            return 0
        if a.cmd == "check":
            r = check(a.path, title_at(program))
            print(json.dumps(r, ensure_ascii=False))
            return 0 if r["ok"] else 1
        r = fit(analyze(a.path), title_at(program), opening.length(program))
        print(json.dumps(r, ensure_ascii=False, indent=1))
        if a.write:
            w = Path(a.write)
            spec = json.loads(w.read_text(encoding="utf-8")) if w.exists() else {"op_music": None, "bgm": None}
            spec["op_music"] = {"volume": 0.9, "fade_out": 1.5, "provisional": True, **(spec.get("op_music") or {}),
                                "path": str(a.path), "start": r["start"],
                                "start_note": f"music fit が決めた（山の入り {r['climax']['at']}秒を番組名に合わせる）"}
            w.write_text(json.dumps(spec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    except MusicError as e:
        print(f"止めました: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
