"""番組化の出力の品質ゲート — **実測で合否を出す**（V2・2026-11-10）。

仕上げ版・Shorts・サムネを ffprobe / ffmpeg / Pillow で測り、線（`backend/config/program_quality.json`）
と比べる。AI は呼ばない。0円。

    python -m backend.revenue.program_quality short  <mp4>
    python -m backend.revenue.program_quality episode <mp4> [--review]
    python -m backend.revenue.program_quality thumbnail <png>

守ること:

- **点数を作らない。** 出すのは項目ごとの実測値と線と合否だけ（定数の点・加点の見せかけは作らない）
- **測れなかった項目は合格にしない**（`measured: false` は不合格と同じ扱い）。
  本線の品質ゲートで「検査していない」が「検査して問題なし」に化けていた（R1.5-C4）のを繰り返さない
- 線を変えるのは設定ファイルだけ。合否の式をここに散らさない

終了コード: 0 = 合格 ／ 1 = 不合格・測れない ／ 2 = 引数の誤り。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

CONFIG = Path(__file__).resolve().parent.parent / "config" / "program_quality.json"
KINDS = ("episode", "short", "thumbnail")


def load_config(path: Path = CONFIG) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _row(id_: str, label: str, value: Any, limit: str, ok: bool, measured: bool = True,
         note: str = "") -> dict:
    return {"id": id_, "label": label, "value": value, "limit": limit,
            "ok": bool(ok and measured), "measured": measured, **({"note": note} if note else {})}


def _unmeasured(id_: str, label: str, limit: str, why: str) -> dict:
    return _row(id_, label, None, limit, False, measured=False, note=why)


def probe(path: Path) -> dict:
    """ffprobe の結果（streams と format）。読めなければ例外。"""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def scan(path: Path, cfg: dict, has_audio: bool) -> dict:
    """全編を1回デコードして、音の大きさ・ピーク・黒い区間・無音の区間・壊れを測る。"""
    v = cfg["video"]
    graph = f"[0:v:0]blackdetect=d={v['black_max_seconds']}:pix_th=0.10[v]"
    maps = ["-map", "[v]", "-f", "null", "-"]
    if has_audio:
        graph += (f";[0:a:0]ebur128=peak=true,"
                  f"silencedetect=n={v['silence_floor_db']}dB:d={v['silence_max_seconds']}[a]")
        maps += ["-map", "[a]", "-f", "null", "-"]
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-v", "info", "-xerror", "-i", str(path),
                        "-filter_complex", graph, *maps],
                       capture_output=True, text=True, check=False)   # 終了コードは下で見る
    log = r.stderr
    out: dict[str, Any] = {"decoded": r.returncode == 0,
                           "decode_error": "" if r.returncode == 0 else log.strip().splitlines()[-1:]}
    out["black"] = [float(x) for x in re.findall(r"black_duration:([\d.]+)", log)]
    out["silence"] = [float(x) for x in re.findall(r"silence_duration: ([\d.]+)", log)]
    summary = log.rsplit("Summary:", 1)[-1] if "Summary:" in log else ""
    m = re.search(r"I:\s+(-?[\d.]+) LUFS", summary)
    out["lufs"] = float(m.group(1)) if m else None
    m = re.search(r"Peak:\s+(-?[\d.]+|-inf) dBFS", summary)
    out["peak"] = (float(m.group(1)) if m and m.group(1) != "-inf" else None)
    return out


def measure_video(kind: str, path: Path, cfg: dict, review: bool = False) -> list[dict]:
    v, k = cfg["video"], cfg["kinds"][kind]
    try:
        info = probe(path)
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError) as e:
        return [_unmeasured("readable", "動画として読める", "ffprobe が読める", f"読めません: {e}")]
    vs = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    au = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
    if vs is None:
        return [_row("readable", "動画として読める", "映像なし", "映像が1本ある", False)]
    rows = [_row("codec", "映像の形式", vs.get("codec_name"), "・".join(v["codec"]),
                 vs.get("codec_name") in v["codec"]),
            _row("pix_fmt", "色の形式", vs.get("pix_fmt"), "・".join(v["pix_fmt"]),
                 vs.get("pix_fmt") in v["pix_fmt"], note=v.get("pix_fmt_why", ""))]
    size = f"{vs.get('width')}x{vs.get('height')}"
    if review:
        rows.append(_row("size", "大きさ", size, "確認用は問わない", True))
    else:
        rows.append(_row("size", "大きさ", size, f"{k['width']}x{k['height']}",
                         (vs.get("width"), vs.get("height")) == (k["width"], k["height"])))
    try:
        seconds = float(info["format"]["duration"])
    except (KeyError, ValueError, TypeError):
        seconds = None
    if seconds is None:
        rows.append(_unmeasured("duration", "長さ", "測れること", "長さが読めません"))
    else:
        lo, hi = k.get("min_seconds"), k.get("max_seconds")
        limit = "・".join(x for x in (f"{lo}秒以上" if lo else "", f"{hi}秒以下" if hi else "") if x) or "問わない"
        rows.append(_row("duration", "長さ", round(seconds, 2), limit,
                         (lo is None or seconds >= lo) and (hi is None or seconds <= hi),
                         note=k.get("max_seconds_why", "")))
    rows.append(_row("audio", "音声", "あり" if au else "なし", "あり", au is not None))
    if au and seconds is not None:
        try:
            gap = abs(float(au.get("duration") or seconds) - float(vs.get("duration") or seconds))
            rows.append(_row("av_gap", "映像と音の長さの差", round(gap, 3),
                             f"{v['av_gap_max_seconds']}秒以下", gap <= v["av_gap_max_seconds"]))
        except (TypeError, ValueError):
            rows.append(_unmeasured("av_gap", "映像と音の長さの差", f"{v['av_gap_max_seconds']}秒以下", "読めません"))

    s = scan(path, cfg, au is not None)
    rows.append(_row("decode", "最後まで壊れずに再生できる", "できる" if s["decoded"] else "止まる",
                     "できる", s["decoded"], note="" if s["decoded"] else str(s["decode_error"])))
    if not s["decoded"]:
        # 途中で止まった測定は使わない（短い分だけ測って合格にしない）
        for id_, label in (("loudness", "全体の音の大きさ"), ("peak", "音のピーク"),
                           ("black", "黒い画面"), ("silence", "無音")):
            rows.append(_unmeasured(id_, label, "—", "最後まで再生できなかったので測っていません"))
        return rows
    if au:
        lo, hi = v["loudness_lufs"]
        if s["lufs"] is None:
            rows.append(_unmeasured("loudness", "全体の音の大きさ", f"{lo}〜{hi} LUFS", "測れません"))
        else:
            rows.append(_row("loudness", "全体の音の大きさ", f"{s['lufs']} LUFS", f"{lo}〜{hi} LUFS",
                             lo <= s["lufs"] <= hi, note=v.get("loudness_why", "")))
        if s["peak"] is None:
            rows.append(_unmeasured("peak", "音のピーク", f"{v['true_peak_max_dbfs']} dBFS 以下", "測れません"))
        else:
            rows.append(_row("peak", "音のピーク", f"{s['peak']} dBFS", f"{v['true_peak_max_dbfs']} dBFS 以下",
                             s["peak"] <= v["true_peak_max_dbfs"], note=v.get("true_peak_why", "")))
        worst = max(s["silence"], default=0.0)
        rows.append(_row("silence", "無音", f"最長 {round(worst, 1)}秒（{len(s['silence'])} か所）"
                         if s["silence"] else "なし", f"{v['silence_max_seconds']}秒以上の無音がない",
                         not s["silence"]))
    worst = max(s["black"], default=0.0)
    rows.append(_row("black", "黒い画面", f"最長 {round(worst, 1)}秒（{len(s['black'])} か所）"
                     if s["black"] else "なし", f"{v['black_max_seconds']}秒以上の黒がない", not s["black"]))
    return rows


def measure_thumbnail(path: Path, cfg: dict) -> list[dict]:
    k = cfg["kinds"]["thumbnail"]
    try:
        from PIL import Image
        with Image.open(path) as im:
            im.load()
            size, fmt = im.size, im.format
    except Exception as e:  # noqa: BLE001 — 壊れた画像の種類は列挙しきれない。測れないとして返す
        return [_unmeasured("readable", "画像として読める", "開ける", f"開けません: {e}")]
    bytes_ = path.stat().st_size
    return [_row("format", "画像の形式", fmt, "・".join(k["formats"]), fmt in k["formats"]),
            _row("size", "大きさ", f"{size[0]}x{size[1]}", f"{k['width']}x{k['height']}",
                 size == (k["width"], k["height"])),
            _row("bytes", "ファイルの大きさ", bytes_, f"{k['max_bytes']} バイト以下",
                 bytes_ <= k["max_bytes"], note=k.get("max_bytes_why", ""))]


def measure(kind: str, path: str | Path, *, review: bool = False, cfg: dict | None = None) -> dict:
    """1つのファイルを測って、項目ごとの結果と合否を返す。"""
    if kind not in KINDS:
        raise ValueError(f"種類は {'・'.join(KINDS)} のどれか: {kind}")
    cfg = cfg or load_config()
    path = Path(path)
    if not path.is_file():
        rows = [_unmeasured("exists", "ファイルがある", "ある", f"ありません: {path}")]
    elif kind == "thumbnail":
        rows = measure_thumbnail(path, cfg)
    else:
        rows = measure_video(kind, path, cfg, review)
    return {"kind": kind, "review": review, "file": path.name, "checks": rows,
            "passed": all(r["ok"] for r in rows),
            "failed": [r["id"] for r in rows if not r["ok"]]}


def format_report(report: dict) -> list[str]:
    label = load_config()["kinds"][report["kind"]]["label"] + ("（確認用）" if report.get("review") else "")
    lines = [f"{'✅ 合格' if report['passed'] else '🚫 不合格'}: {report['file']}（{label}）"]
    for r in report["checks"]:
        mark = "✅" if r["ok"] else ("❔" if not r["measured"] else "🚫")
        value = "測れない" if not r["measured"] else r["value"]
        lines.append(f"  {mark} {r['label']}: {value}（線: {r['limit']}）"
                     + (f" — {r['note']}" if r.get("note") and not r["ok"] else ""))
    return lines


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="番組化の出力を実測して合否を出す（AI なし・0円）")
    p.add_argument("kind", choices=KINDS)
    p.add_argument("file")
    p.add_argument("--review", action="store_true", help="確認用（縮小版）。大きさは問わない")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    report = measure(a.kind, a.file, review=a.review)
    print(json.dumps(report, ensure_ascii=False, indent=2) if a.json else "\n".join(format_report(report)))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
