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

本線（render_worker）も同じ台帳から BGM を引く（``mainline_bgm``）。曲をクラウドの作業場に持ってくるのは
``fetch``（Drive の 20_素材/共通 か 30_AVS_作業/番組資産/曲 から、台帳の file の名前で落とす・読み取り専用）::

    python -m backend.program_package.music fetch 曲の置き場
"""
from __future__ import annotations

import argparse
import json
import re
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


def load_ledger() -> dict:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def plan(program: dict, ledger: dict, music_dir: str | Path | None, quiet: list[list[float]] | None = None,
         body_seconds: float | None = None, roles: tuple[str, ...] | None = None) -> dict:
    """曲の台帳から、この番組の音の指定（remix の AUDIO.json）を作る。

    - OP: 台帳に start が無ければ、曲の山の入りを番組名の出だしに合わせる
    - BGM: 本編の全体に敷く。quiet（曲を止める区間・本編の秒）があれば、そこを避けて区間を分ける
    - 出どころ（source）の無い曲は使わない。provisional の曲は印を引き継ぐ（名前に「_仮曲入り」が付く）
    - roles を渡すと、その役（op・bgm・ed）だけを作る（本線は bgm だけ）
    """
    from backend.program_package import opening
    use = (ledger.get("programs") or {}).get(program["name"])
    if not use:
        raise MusicError(f"曲の台帳に番組「{program['name']}」がありません")
    out: dict = {"op_music": None, "bgm": None, "ed_music": None, "peak_db": ledger.get("peak_db", -1.5), "tracks": {}}
    for role, key in ROLES.items():
        r = use.get(role)
        if not r or (roles is not None and role not in roles):
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
        if t.get("ai_generated"):  # 公開のときに開示を考える印。控えまで運ぶ
            out["tracks"][role].update(ai_generated=True, made_with=t.get("made_with"))
    return out


def mainline_bgm(ledger: dict, music_dir: str | Path | None) -> dict:
    """本線（render_worker の最終レンダリング）が敷く BGM の指定。remix と同じ形（bgm だけ）。

    本線の動画には番組 OP も ED も無いので、台帳の ``mainline.program`` の番組の BGM を全体に敷く。
    曲が使えないときは理由つきの MusicError（本線はそれを記録に出して、曲なしで書き出す）。
    """
    name = (ledger.get("mainline") or {}).get("program")
    if not name:
        raise MusicError("曲の台帳に本線の番組（mainline.program）が書いてありません")
    spec = plan({"name": name}, ledger, music_dir, roles=("bgm",))
    if not spec["bgm"]:
        raise MusicError(f"曲の台帳の番組「{name}」に BGM がありません")
    return spec


# 曲を探す Drive の場所（「動画制作」の中）。20_素材 は北原さんが置く所、30_AVS_作業 は AI が置く所
DRIVE_PLACES = ("20_素材/共通", "30_AVS_作業/番組資産/曲")


def missing(ledger: dict, music_dir: str | Path) -> list[str]:
    """台帳の番組で使う曲のうち、置き場に無いファイルの名前。"""
    used = {r["track"] for p in (ledger.get("programs") or {}).values() for r in p.values()
            if isinstance(r, dict) and r.get("track")}
    names = sorted({t["file"] for k, t in (ledger.get("tracks") or {}).items() if k in used and t.get("file")})
    return [n for n in names if not (Path(music_dir) / n).exists()]


def fetch(ledger: dict, music_dir: str | Path, service=None, env=None) -> dict:
    """置き場に無い曲を Drive（DRIVE_PLACES・その下のフォルダも）から、台帳の file の名前で落とす。

    読み取り専用の鍵で読む（raw を読むのと同じ鍵）。同じ名前が 2 つあるときは、どちらか決めずに止まる。
    """
    import os

    from backend import raw_source as rs
    env = os.environ if env is None else env
    music_dir = Path(music_dir)
    music_dir.mkdir(parents=True, exist_ok=True)
    want = missing(ledger, music_dir)
    out: dict = {"dir": str(music_dir), "fetched": [], "not_found": [], "already": len(want) == 0}
    if not want:
        return out
    service = service or rs._build_drive()
    raw = env.get("AVS_RAW_DRIVE_FOLDER_ID")
    if not raw:
        raise MusicError("Drive の場所が分かりません（環境変数 AVS_RAW_DRIVE_FOLDER_ID）")
    base = (service.files().get(fileId=raw, fields="parents", supportsAllDrives=True).execute().get("parents") or [None])[0]
    todo, found = [], {}
    for place in ledger.get("drive") or DRIVE_PLACES:   # 無い場所は飛ばす（どこにも無ければ止まる）
        try:
            folder = base
            for name in place.split("/"):
                folder = rs.find_folder(service, folder, name)
            todo.append(folder)
        except rs.FolderError:
            continue
    if not todo:
        raise MusicError(f"Drive に曲の置き場がありません（{'・'.join(ledger.get('drive') or DRIVE_PLACES)}）")
    while todo:
        folder = todo.pop()
        todo += [f["id"] for f in rs.list_folders(service, folder)]
        for f in rs._list_files(service, f"'{folder}' in parents and trashed = false "
                                         f"and mimeType != '{rs.FOLDER_MIME}'", "id, name, md5Checksum"):
            if f["name"] in want:
                found.setdefault(f["name"], []).append(f)
    for name in want:
        hits = found.get(name) or []
        if len({h.get("md5Checksum") for h in hits}) > 1:
            raise MusicError(f"Drive に「{name}」が中身ちがいで {len(hits)} つあります。1 つにしてください")
        if not hits:
            out["not_found"].append(name)
            continue
        dest = music_dir / name
        part = dest.with_name(dest.name + ".part")
        rs._download(service, hits[0]["id"], part)
        if hits[0].get("md5Checksum") and rs._md5_of(part) != hits[0]["md5Checksum"]:
            part.unlink(missing_ok=True)
            raise MusicError(f"落とした「{name}」の中身が Drive と合いません")
        part.replace(dest)
        out["fetched"].append(name)
    return out


# AI で作った曲を公開に使ってよいのは、Google Workspace の規約の下で作った曲だけ（2026-11-14 一次情報で確認）:
# サービス固有規約 12.12 で生成物は顧客のデータ・Google は権利を主張しない、12.4 に商用の制限なし、
# 12.10 の補償の対象に Google Vids（有料の契約のみ）。個人の Google AI Pro は Workspace の規約の外。
AI_CLEAR_DOMAINS = ("kitahara-birei.com",)
AI_PUBLISH_TODO = ("AI で作った曲が入っている。投稿のときに YouTube の「改変・合成コンテンツ」を「はい」にする"
                   "（YouTube ヘルプ 14328491 で「AI で作った音楽」は開示が要る例）")


def _clear_ok(t: dict, account: str | None) -> None:
    if t.get("ai_generated") and (account or "").rsplit("@", 1)[-1] not in AI_CLEAR_DOMAINS:
        raise MusicError("AI で作った曲を公開に使えるのは法人の Workspace（info@ など）で作った曲だけ。"
                         f"作ったアカウント: {account or '書いていない'}（個人で作った曲は聞き比べ用の仮のまま）")


def clear_track(ledger: dict, key: str, cleared: str) -> dict:
    """使ってよい根拠を書いて、仮の曲を公開に使える曲にする。AI で作った曲は法人のアカウントで作った物だけ。"""
    t = (ledger.get("tracks") or {}).get(key)
    if not t:
        raise MusicError(f"曲の台帳に曲「{key}」がありません")
    if not cleared.strip():
        raise MusicError("使ってよい根拠（--cleared）を書いてください")
    _clear_ok(t, t.get("account"))
    t.update(cleared=cleared.strip(), provisional=False)
    return t


def extract_audio(video: str | Path, dest: str | Path) -> Path:
    """Vids で書き出した mp4 から音だけを取り出す（mp3・質は高め）。映像は使わない。"""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise MusicError(f"同じ名前のファイルがもうあります: {dest}（別の名前にする。前の曲は消さない）")
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(video), "-vn", "-c:a", "libmp3lame", "-q:a", "2",
                    str(dest)], check=True)
    return dest


def add_track(ledger: dict, key: str, *, title: str, file: str, source: str, by: str, artist: str | None = None,
              ai_generated: bool = False, made_with: str | None = None, prompt: str | None = None,
              cleared: str | None = None, today: str | None = None, account: str | None = None,
              original: str | None = None) -> dict:
    """曲を台帳に足す（人が作った・選んだ曲の控え）。

    Vids などで作った曲は ai_generated と、作った道具・指示文（prompt）を残す。指示文が資産になる。
    使ってよい根拠（cleared）を書くまでは provisional（公開に使わない・名前に「_仮曲入り」が付く）。
    """
    import datetime as dt
    if not re.fullmatch(r"[a-z0-9_]+", key):
        raise MusicError(f"曲の名前（key）は半角の小文字・数字・_ だけ: {key}")
    if key in (ledger.get("tracks") or {}):
        raise MusicError(f"同じ名前の曲がもうあります: {key}（別の名前で足す。前の曲は消さない）")
    if not source.strip() or not by.strip():
        raise MusicError("出どころ（--source）と、足した人（--by）を書いてください")
    if ai_generated and not ((made_with or "").strip() and (prompt or "").strip()):
        raise MusicError("AI で作った曲は、作った道具（--made-with）と指示文（--prompt）を残してください")
    t = {"title": title, "artist": artist, "source": source, "file": file, "provisional": not (cleared or "").strip(),
         "added": {"by": by, "on": today or dt.date.today().isoformat()}}
    if ai_generated:
        t.update(ai_generated=True, made_with=made_with, prompt=prompt)
        if account:
            t["account"] = account
        if original:  # Vids の書き出し（mp4）の置き場。指示文と並ぶ資産
            t["original"] = original
        if (cleared or "").strip():
            _clear_ok(t, account)
    if (cleared or "").strip():
        t["cleared"] = cleared.strip()
    ledger.setdefault("tracks", {})[key] = t
    return t


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
    s = sub.add_parser("add", help="曲を台帳に足す（Vids で作った曲は --ai と指示文つき）")
    s.add_argument("key")
    for flag in ("--title", "--file", "--source", "--by"):
        s.add_argument(flag, required=True)
    for flag in ("--artist", "--made-with", "--prompt", "--cleared", "--ledger", "--account", "--original"):
        s.add_argument(flag)
    s.add_argument("--ai", action="store_true")
    s.add_argument("--from-video", help="Vids で書き出した mp4。音だけ取り出して --music-dir に --file の名前で置く")
    s.add_argument("--music-dir")
    s = sub.add_parser("clear", help="使ってよい根拠を書いて、仮の曲を公開に使える曲にする")
    s.add_argument("key")
    s.add_argument("--cleared", required=True)
    s.add_argument("--ledger")
    for name in ("analyze", "fit", "check", "plan", "fetch"):
        s = sub.add_parser(name)
        s.add_argument("path", help="曲（plan のときは書き出す AUDIO.json・fetch のときは曲の置き場）")
        if name == "plan":
            s.add_argument("--music-dir")
        if name not in ("analyze", "fetch"):
            s.add_argument("--program", required=True)
        if name == "fit":
            s.add_argument("--write", help="remix の指定（AUDIO.json）の op_music.path と start を書き換える")
    a = p.parse_args(argv)
    try:
        if a.cmd == "clear":
            where = Path(a.ledger) if a.ledger else LEDGER
            ledger = json.loads(where.read_text(encoding="utf-8"))
            t = clear_track(ledger, a.key, a.cleared)
            where.write_text(json.dumps(ledger, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print(json.dumps({a.key: t}, ensure_ascii=False, indent=1))
            return 0
        if a.cmd == "add":
            where = Path(a.ledger) if a.ledger else LEDGER
            ledger = json.loads(where.read_text(encoding="utf-8"))
            t = add_track(ledger, a.key, title=a.title, file=a.file, source=a.source, by=a.by, artist=a.artist,
                          ai_generated=a.ai, made_with=a.made_with, prompt=a.prompt, cleared=a.cleared,
                          account=a.account, original=a.original or a.from_video)
            if a.from_video:  # 台帳の確かめが通ってから音を取り出す
                import os
                d = a.music_dir or os.environ.get("AVS_MUSIC_DIR")
                if not d:
                    raise MusicError("曲の置き場が分かりません（--music-dir か環境変数 AVS_MUSIC_DIR）")
                extract_audio(a.from_video, Path(d) / a.file)
            where.write_text(json.dumps(ledger, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print(json.dumps({a.key: t}, ensure_ascii=False, indent=1))
            return 0
        if a.cmd == "analyze":
            print(json.dumps(analyze(a.path), ensure_ascii=False, indent=1))
            return 0
        if a.cmd == "fetch":
            r = fetch(load_ledger(), a.path)
            print(json.dumps(r, ensure_ascii=False, indent=1))
            return 1 if r["not_found"] else 0
        program = opening.load(a.program)
        if a.cmd == "plan":
            import os
            ledger = load_ledger()
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
