"""生成クリップの検品: 最初と最後のコマを指定して作った動画が、指定どおりに動いたかを機械で見る（0円）。

Flow などで「最初のコマ → 最後のコマ」を指定して作ったクリップは、次の失敗が多い。
人がコマ一覧を見て気づいていたものを、先に機械でふるいに掛ける。**採用を決めるのは人**。
ここで「不採用」と出たものは見るまでもなく作り直し、「採用候補」だけを人が見る。

見る所（どれも指定の2コマとの比較。絵柄は問わないので実写でもアニメでも使える）:

- **大きさ**: キャラ（背景と違う色のかたまり）の大きさが、指定のコマから変わっていないか（途中ズーム）
- **到達**: 最後のコマに届いたか（全体だけでなく、表情など一部が最初のコマのまま終わっていないか）
- **戻り**: 最後のコマへ向かった後で、最初のコマに戻っていないか
- **背景**: 絵の縁（背景）が指定のコマから変わっていないか（カメラの切り替え・引き寄せ）

使い方（リポジトリ直下で）::

    python -m backend.program_package.clip_check CLIP.mp4 --start 最初.png --end 最後.png [--json]

終了コード: 0 = 採用候補 ／ 1 = 不採用 ／ 2 = 読めない。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from backend.program_package import vision

SIZE = 240            # 比べるときの長辺
SCALE_TOLERANCE = 0.10  # 大きさがこの割合を超えて変わったら「変わった」
REACH = 0.45          # 最後のコマとの違いが「最初と最後の違い」のこの割合以下なら届いた
BORDER_TOLERANCE = 14.0  # 縁の色の違い（0〜255）がこれを超えたら背景が変わった
CELL = 12             # 部分ごとに比べるときのますの大きさ
CELL_GAP = 12.0       # 最初と最後のコマで、ますの違いがこれを超える所を「変わるはずの所」とする
STALE = 0.15          # 変わるはずの所のうち、最初のコマのままの割合がこれを超えたら届いていない
HOLD = 0.6            # これより短い外れは数えない（秒）


def _fit(im: Image.Image, size: tuple[int, int]) -> np.ndarray:
    return np.asarray(im.convert("RGB").resize(size, Image.LANCZOS)).astype(np.int16)


def _blur(a: np.ndarray) -> np.ndarray:
    import cv2
    return cv2.GaussianBlur(a.astype(np.float32), (0, 0), 1.5)


def figure_area(rgb: np.ndarray) -> int:
    """キャラの面積。各行の左右の端の色を背景とみなし、それと違う色のいちばん大きいかたまりを数える。"""
    import cv2
    a = _blur(rgb)
    k = max(2, a.shape[1] // 25)
    bg = np.median(np.concatenate([a[:, :k], a[:, -k:]], axis=1), axis=1)[:, None, :]
    m = (np.abs(a - bg).max(axis=2) > 28).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    return int(stats[1:, 4].max()) if n > 1 else 0


def _border(a: np.ndarray) -> np.ndarray:
    k = max(2, min(a.shape[:2]) // 14)
    return np.concatenate([a[:k].reshape(-1, 3), a[:, :k].reshape(-1, 3), a[:, -k:].reshape(-1, 3)])


def _dist(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.abs(_blur(a) - _blur(b)).mean())


def _cells(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """絵を CELL 角のますに分け、ますごとの違いを返す。"""
    d = np.abs(_blur(a) - _blur(b)).mean(axis=2)
    h, w = (d.shape[0] // CELL) * CELL, (d.shape[1] // CELL) * CELL
    return d[:h, :w].reshape(h // CELL, CELL, w // CELL, CELL).mean(axis=(1, 3))


def stale_share(f: np.ndarray, start: np.ndarray, end: np.ndarray) -> float:
    """最初と最後のコマで絵が違う所のうち、このコマがまだ最初のコマに近い所の割合（0〜1）。

    全体では最後のコマに似ていても、表情だけ最初のまま、という失敗をここで拾う。
    """
    changed = _cells(start, end) > CELL_GAP
    if not changed.any():
        return 0.0
    return float((_cells(f, start) < _cells(f, end))[changed].mean())


def measure(frames: list[tuple[float, np.ndarray]], start: np.ndarray, end: np.ndarray) -> list[dict]:
    """コマごとの数字: 最初・最後のコマとの違い、キャラの大きさ（最初のコマ比）、縁の違い。"""
    a0 = max(1, figure_area(start))
    rows = []
    for t, f in frames:
        rows.append({
            "t": round(t, 2),
            "d_start": round(_dist(f, start), 2),
            "d_end": round(_dist(f, end), 2),
            "scale": round(float(np.sqrt(figure_area(f) / a0)), 3),
            "stale": round(stale_share(f, start, end), 3),
            "border": round(min(float(np.abs(_border(f) - _border(k)).mean()) for k in (start, end)), 2),
        })
    return rows


def _runs(rows: list[dict], bad) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    prev = False
    for r in rows:
        now = bool(bad(r))
        if now and prev:
            out[-1][1] = r["t"]
        elif now:
            out.append([r["t"], r["t"]])
        prev = now
    return [(a, b) for a, b in out]


def judge(rows: list[dict], key_gap: float, end_scale: float) -> dict:
    """数字から合否と理由を出す。key_gap は最初と最後のコマの違い、end_scale は最後のコマの大きさ（最初比）。"""
    if not rows:
        return {"ok": False, "reasons": ["コマが読めない"], "use": [0.0, 0.0]}
    step = rows[1]["t"] - rows[0]["t"] if len(rows) > 1 else 1.0
    need = max(1, round(HOLD / step))
    lo, hi = min(1.0, end_scale) * (1 - SCALE_TOLERANCE), max(1.0, end_scale) * (1 + SCALE_TOLERANCE)
    reasons = []
    first_bad = rows[-1]["t"] + step

    def long_runs(bad):
        return [(a, b) for a, b in _runs(rows, bad) if round((b - a) / step) + 1 >= need]

    size = long_runs(lambda r: not (lo <= r["scale"] <= hi))
    if size:
        a, b = size[0]
        peak = max((r["scale"] for r in rows if a <= r["t"] <= b), key=lambda s: abs(s - 1))
        reasons.append(f"キャラの大きさが変わる（{a:.1f} 秒から・{peak:.2f} 倍）")
        first_bad = min(first_bad, a)
    border = long_runs(lambda r: r["border"] > BORDER_TOLERANCE)
    if border:
        reasons.append(f"背景が指定のコマと違う（{border[0][0]:.1f} 秒から）")
        first_bad = min(first_bad, border[0][0])
    best = min(rows, key=lambda r: r["d_end"])
    near = best["d_end"] <= max(2.0, REACH * key_gap)
    reached = near and best.get("stale", 0.0) <= STALE
    if near and not reached:
        reasons.append(f"最後のコマと一部が違う（変わるはずの所の {best['stale']:.0%} が最初のコマのまま。表情など）")
    elif not reached:
        reasons.append(f"最後のコマに届かない（いちばん近いコマでも違いが {best['d_end']:.1f}・"
                       f"最初と最後の違いは {key_gap:.1f}）")
    else:
        # 届いた後で、最後のコマより最初のコマに近くなったら戻っている
        back = [(a, b) for a, b in long_runs(lambda r: r["t"] > best["t"] and r["d_start"] < r["d_end"])]
        if back:
            reasons.append(f"最初のコマに戻る（{back[0][0]:.1f} 秒から）")
            first_bad = min(first_bad, back[0][0])
        away = long_runs(lambda r: r["t"] > best["t"] and r["d_end"] > max(2.0, REACH * key_gap) * 1.6)
        if away and not back:
            reasons.append(f"最後のコマで止まらない（{away[0][0]:.1f} 秒から別の絵になる）")
            first_bad = min(first_bad, away[0][0])
    return {"ok": not reasons, "reasons": reasons, "reached_at": best["t"] if reached else None,
            "use": [0.0, round(max(0.0, first_bad - step / 2), 2)]}


def check_frames(frames: list[tuple[float, np.ndarray]], start: Image.Image, end: Image.Image) -> dict:
    """(時刻, RGB のコマ) の並びを検品する。コマは同じ大きさであること。"""
    if not frames:
        return {**judge([], 0, 1), "rows": []}
    h, w = frames[0][1].shape[:2]
    k = SIZE / max(w, h)
    size = (max(8, round(w * k)), max(8, round(h * k)))
    s, e = _fit(start, size), _fit(end, size)
    small = [(t, _fit(Image.fromarray(f.astype(np.uint8)), size)) for t, f in frames]
    rows = measure(small, s, e)
    out = judge(rows, _dist(s, e), float(np.sqrt(max(1, figure_area(e)) / max(1, figure_area(s)))))
    return {**out, "rows": rows}


def check(clip: Path, start: Path, end: Path, fps: float = 4.0) -> dict:
    frames = [(t, bgr[..., ::-1]) for t, bgr in vision.frames(clip, fps, width=SIZE * 2)]
    return check_frames(frames, Image.open(start), Image.open(end))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="生成クリップが指定の2コマどおりに動いたかを見る")
    p.add_argument("clip")
    p.add_argument("--start", required=True, help="指定した最初のコマ")
    p.add_argument("--end", required=True, help="指定した最後のコマ")
    p.add_argument("--fps", type=float, default=4.0)
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    try:
        r = check(Path(a.clip), Path(a.start), Path(a.end), a.fps)
    except (OSError, vision.VisionError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(r, ensure_ascii=False))
    else:
        print("採用候補（人が見て決める）" if r["ok"] else "不採用")
        for s in r["reasons"]:
            print("  - " + s)
        print(f"  使える区間: {r['use'][0]:.1f}〜{r['use'][1]:.1f} 秒")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
