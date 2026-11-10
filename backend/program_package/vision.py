"""映像を見る目: 顔と頭の位置・動きを測り、飾りの置き場を自動で決める（AI を呼ばない・0円）。

これまで名前のポップを置くたびに、完成版のコマを1秒ごとに並べて「頭の来る所」を人が測っていた
（指定ファイルの avoid）。ここを機械に置き換える。GPU も課金も要らない。

- 顔の検出は OpenCV の YuNet（`models/face_detection_yunet_2023mar.onnx`・MIT・232KB）。
  CPU で 1コマ 10ms 前後。実写の対談（斜め向きの二人）で使えることを 2026-11-10 に確かめた
- 測った結果は「地図」（JSON）に残す。1コマごとの顔・頭の矩形、動きの大きさ、場面の切れ目、
  色紙や作品が大きく映る区間。座標はどの大きさの動画から測っても 1280x720 に直す
- 地図から、ある時間帯に頭が来る所（avoid）を出し、名前のポップをそこに掛からない所へ置く。
  章の見出し・補足のテロップが頭に掛かる所も一覧にする
- サムネの人物コマの候補（左右）も地図から出す。**選ぶのは人**（候補を並べるまで）

使い方（リポジトリ直下で）::

    python -m backend.program_package.vision scan 完成版.mp4 --out map.json
    python -m backend.program_package.vision place SPEC.json --map map.json [--write]
    python -m backend.program_package.vision check SPEC.json --map map.json
    python -m backend.program_package.vision thumbs --map map.json [--video 完成版.mp4 --out DIR]
    python -m backend.program_package.vision sheet 完成版.mp4 --map map.json --at 45 --seconds 8 --out a.jpg

`place` は書き換える中身を出すだけ。`--write` を付けたときだけ指定ファイルを書き換える。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import numpy as np

W, H = 1280, 720
MODEL = Path(__file__).resolve().parent / "models" / "face_detection_yunet_2023mar.onnx"
MAP_VERSION = 1
SCAN_WIDTH = 960      # 顔を探すときの横幅。360p の確認用でも顔が 30px 以上になる
MIN_SCORE = 0.6
FLOOR = 560           # 頭の来る所は、頭からこの高さまで（体）を含める。これより下は字幕の所
CUT_MOTION = 0.12     # 動きがこれを超えたら場面の切れ目とみなす
HEAD_PAD = (0.22, 0.42, 0.22, 0.12)  # 顔の矩形から頭（髪）へ広げる割合: 左・上・右・下
CHECK_MARGIN = 0                     # 掛かるかどうかは測った頭そのもので見る（置き場を探すときは 14 の余白）
NEAR_MARGIN = 12                     # 頭までこの距離より近い飾りは「近い」として知らせる
FRONT_TRIM = 0.14                    # 横向きのとき、顔の向いている側を狭める割合
BACK_PAD = 0.35                      # 横向きのとき、後ろ頭の側へさらに広げる割合


class VisionError(RuntimeError):
    pass


# ---- 動画を読む ----

def probe(video: Path) -> tuple[int, int, float]:
    """(横, 縦, 長さ秒)。"""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:format=duration", "-of", "json", str(video)],
        capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    s = j["streams"][0]
    return int(s["width"]), int(s["height"]), float(j["format"]["duration"])


def frames(video: Path, fps: float, width: int = SCAN_WIDTH, start: float = 0.0,
           seconds: float | None = None) -> Iterator[tuple[float, np.ndarray]]:
    """(時刻, BGR のコマ) を fps 間隔で順に返す。ffmpeg から生のコマを受け取る。"""
    vw, vh, _ = probe(video)
    height = round(width * vh / vw / 2) * 2
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{start:.3f}"]
    if seconds is not None:
        cmd += ["-t", f"{seconds:.3f}"]
    cmd += ["-i", str(video), "-vf", f"fps={fps},scale={width}:{height}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    size = width * height * 3
    with subprocess.Popen(cmd, stdout=subprocess.PIPE) as p:
        i = 0
        while True:
            buf = p.stdout.read(size)
            if len(buf) < size:
                break
            yield start + i / fps, np.frombuffer(buf, np.uint8).reshape(height, width, 3)
            i += 1


# ---- 顔と頭 ----

class Eye:
    """YuNet の顔検出。返す座標は 1280x720。"""

    def __init__(self, min_score: float = MIN_SCORE):
        try:
            import cv2
        except ImportError as e:  # pragma: no cover - 入っていない環境への案内
            raise VisionError("opencv-python-headless が要ります（pip install opencv-python-headless）") from e
        if not MODEL.exists():
            raise VisionError(f"顔検出のモデルがありません: {MODEL}")
        self.cv2 = cv2
        self.min_score = min_score
        self._det = None
        self._size: tuple[int, int] | None = None

    def faces(self, bgr: np.ndarray) -> list[dict]:
        h, w = bgr.shape[:2]
        if self._size != (w, h):
            self._det = self.cv2.FaceDetectorYN.create(str(MODEL), "", (w, h), self.min_score, 0.3, 50)
            self._size = (w, h)
        _, found = self._det.detect(bgr)
        out = []
        for f in (found if found is not None else []):
            x, y, fw, fh = (float(v) for v in f[:4])
            if not (0.03 * h <= fh <= 0.7 * h):  # 小さすぎる・大きすぎるものは顔とみなさない
                continue
            k = W / w
            out.append({
                "box": [round(x * k), round(y * k), round((x + fw) * k), round((y + fh) * k)],
                "score": round(float(f[-1]), 3),
                "marks": [round(float(v) * k) for v in f[4:14]],  # 右目・左目・鼻・口の右・口の左
            })
        return sorted(out, key=lambda d: d["box"][0])


def head_box(face: list[int], marks: list[int] | None = None) -> list[int]:
    """顔の矩形から、髪まで含めた頭の矩形にする。

    横を向いた顔は、後ろ頭（髪）が顔の矩形の外に大きく出る。鼻の位置で向きを見て、後ろ側を広く取る。
    """
    x0, y0, x1, y1 = face
    w, h = x1 - x0, y1 - y0
    left, top, right, bottom = HEAD_PAD
    if marks:
        turn = (marks[4] - (x0 + x1) / 2) / max(1, w)  # 鼻が右に寄る＝右向き＝後ろ頭は左
        back_left, back_right = min(1.0, max(0.0, turn * 4)), min(1.0, max(0.0, -turn * 4))
        # 後ろ頭の側は広く、顔の向いている側は狭く（顔の矩形が鼻先まで含んでいる）
        left += BACK_PAD * back_left - FRONT_TRIM * back_right
        right += BACK_PAD * back_right - FRONT_TRIM * back_left
    return [max(0, round(x0 - left * w)), max(0, round(y0 - top * h)), min(W, round(x1 + right * w)), min(H, round(y1 + bottom * h))]


def motion_of(prev: np.ndarray | None, cur: np.ndarray) -> float:
    """前のコマとの違いの大きさ（0〜1）。小さく縮めた白黒で比べる。"""
    if prev is None:
        return 0.0
    return round(float(np.abs(cur.astype(np.int16) - prev.astype(np.int16)).mean()) / 255, 4)


def board_box(bgr: np.ndarray) -> list[int] | None:
    """色紙や作品（白い紙に墨）が大きく映っていれば、その矩形（1280x720）。無ければ None。

    白くて四角く、中に墨（暗い所）がある大きな面を探す。墨で欠けた所は面の内側として数える
    （外側の輪郭で見る）。白い上着や明るい机は、四角くないか白さが足りないので外れる。
    """
    import cv2
    h, w = bgr.shape[:2]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    white = ((hsv[..., 2] > 200) & (hsv[..., 1] < 35)).astype(np.uint8)
    white = cv2.morphologyEx(white, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for c in contours:
        x, y, bw, bh = cv2.boundingRect(c)
        if bw * bh < 0.04 * w * h or bw < 0.12 * w or bh < 0.2 * h:
            continue
        if cv2.contourArea(c) / (bw * bh) < 0.85 or not (0.45 <= bw / bh <= 2.2):
            continue
        gray = cv2.cvtColor(bgr[y:y + bh, x:x + bw], cv2.COLOR_BGR2GRAY)
        ink = float((gray < 90).mean())
        if not (0.015 <= ink <= 0.45):
            continue
        if best is None or bw * bh > best[0]:
            k = W / w
            best = (bw * bh, [round(x * k), round(y * k), round((x + bw) * k), round((y + bh) * k)])
    return best[1] if best else None


# ---- 地図を作る ----

def scan(video: Path, fps: float = 2.0, start: float = 0.0, seconds: float | None = None,
         progress: bool = False) -> dict:
    """動画を fps 間隔で見て、地図を作る。"""
    import cv2
    eye = Eye()
    vw, vh, dur = probe(video)
    rows = []
    prev = None
    for t, bgr in frames(video, fps, start=start, seconds=seconds):
        small = cv2.cvtColor(cv2.resize(bgr, (160, 90), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        row = {"t": round(t, 3), "faces": eye.faces(bgr), "motion": motion_of(prev, small)}
        b = board_box(bgr)
        if b:
            row["board"] = b
        rows.append(row)
        prev = small
        if progress and len(rows) % 500 == 0:
            print(f"  {t:7.1f} 秒 / {dur:.0f} 秒", file=sys.stderr)
    return {"version": MAP_VERSION, "video": Path(video).name, "source_size": [vw, vh], "size": [W, H],
            "fps": fps, "duration": round(dur, 3), "frames": rows}


def load(path: str | Path) -> dict:
    m = json.loads(Path(path).read_text(encoding="utf-8"))
    if m.get("version") != MAP_VERSION:
        raise VisionError(f"地図の版が違います: {m.get('version')}（作り直してください）")
    return m


def window(m: dict, at: float, seconds: float, pad: float = 0.5) -> list[dict]:
    return [r for r in m["frames"] if at - pad <= r["t"] <= at + seconds + pad]


def cuts(m: dict) -> list[float]:
    """場面の切れ目の時刻。"""
    return [r["t"] for r in m["frames"] if r["motion"] >= CUT_MOTION]


def spans(times: list[float], step: float, gap: float = 2.0, shortest: float = 1.0) -> list[list[float]]:
    """とびとびの時刻を、続いている区間にまとめる。"""
    out: list[list[float]] = []
    for t in times:
        if out and t - out[-1][1] <= gap:
            out[-1][1] = t
        else:
            out.append([t, t])
    return [[a, round(b + step, 3)] for a, b in out if b - a + step >= shortest]


def board_spans(m: dict) -> list[list[float]]:
    """色紙や作品が大きく映っている区間。"""
    return spans([r["t"] for r in m["frames"] if r.get("board")], 1 / m["fps"])


# ---- 頭の来る所 ----

def _iou(a: list[int], b: list[int]) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def _union(a: list[int], b: list[int]) -> list[int]:
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def steady_heads(rows: list[dict], min_score: float = MIN_SCORE) -> list[list[int]]:
    """区間の中の頭の矩形。1コマだけ現れる誤検出（花・小物）は、前後に近い顔が無ければ捨てる。"""
    per = [[head_box(f["box"], f.get("marks")) for f in r["faces"] if f["score"] >= min_score] for r in rows]
    out = []
    for i, heads in enumerate(per):
        near = [h for j in (i - 1, i + 1) if 0 <= j < len(per) for h in per[j]]
        for h in heads:
            if len(per) < 3 or any(_iou(h, o) > 0.2 for o in near):
                out.append(h)
    return out


def head_zones(m: dict, at: float, seconds: float, margin: int = 14, floor: int = FLOOR) -> list[list[int]]:
    """時刻 at から seconds 秒のあいだに頭が来る所（avoid に入れる矩形）。

    近い頭どうしを1つにまとめ（同じ人の小さな動き）、離れた所（身を乗り出した先）は別の矩形にする。
    下端は floor まで伸ばす（頭の下には体があるので、そこにも文字を置かない）。
    """
    zones: list[list[int]] = []
    for h in sorted(steady_heads(window(m, at, seconds)), key=lambda b: (b[0], b[1])):
        for i, z in enumerate(zones):
            if _iou(h, z) > 0.25:
                zones[i] = _union(z, h)
                break
        else:
            zones.append(list(h))
    merged = True
    while merged:  # まとめた結果どうしが重なったら、もう一度まとめる
        merged = False
        for i in range(len(zones)):
            for j in range(i + 1, len(zones)):
                if _iou(zones[i], zones[j]) > 0.25:
                    zones[i] = _union(zones[i], zones.pop(j))
                    merged = True
                    break
            if merged:
                break
    return [[max(0, z[0] - margin), max(0, z[1] - margin), min(W, z[2] + margin), max(min(H, z[3] + margin), floor)]
            for z in sorted(zones)]


def head_mask(m: dict, at: float, seconds: float, margin: int = CHECK_MARGIN) -> np.ndarray:
    """時刻 at から seconds 秒のあいだに頭が通る所（1280x720 の真偽の絵）。

    頭は矩形ではなく丸いので、頭の矩形に内接する楕円で見る。矩形の角に文字の端が
    触れただけのものを「掛かる」と言わないため。
    """
    import cv2
    mask = np.zeros((H, W), np.uint8)
    for x0, y0, x1, y1 in steady_heads(window(m, at, seconds)):
        cv2.ellipse(mask, ((x0 + x1) // 2, (y0 + y1) // 2), ((x1 - x0) // 2 + margin, (y1 - y0) // 2 + margin),
                    0, 0, 360, 255, -1)
    return mask > 0


def covered(alpha: np.ndarray, mask: np.ndarray) -> list[int] | None:
    """飾り（透明度）が頭に掛かる所の矩形。掛からなければ None。"""
    ys, xs = np.where((alpha > 0) & mask)
    if len(xs) < 12:  # 縁取りの数画素は数えない
        return None
    return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]


def people(m: dict, at: float, seconds: float) -> dict[str, list[int]]:
    """区間にいる人の頭（まとめた矩形）。画面の左半分にいれば left、右半分なら right。"""
    out: dict[str, list[int]] = {}
    for h in steady_heads(window(m, at, seconds)):
        side = "left" if (h[0] + h[2]) / 2 < W / 2 else "right"
        out[side] = _union(out[side], h) if side in out else list(h)
    return out


# ---- 飾りの置き場 ----

def _hit(alpha: np.ndarray, zones: list[list[int]]) -> bool:
    return any(alpha[z[1]:z[3], z[0]:z[2]].any() for z in zones)


def place_pop(pop: dict, zones: list[list[int]], target: list[int] | None = None,
              busy: list[list[int]] | None = None, step: int = 12, gap: int = 8) -> dict | None:
    """名前のポップを、頭の来る所（zones）にも他の飾り（busy）にも掛からない所へ置く。

    いちばん大きい文字のまま置ける所を先に探し、無ければ行の間隔と名前を少し詰める。
    target（その人の頭）に近い所を選ぶ。置ける所が無ければ None。
    """
    from backend.program_package import episode as ep
    fx0, fy0, fx1, _ = ep.th.FRAME
    blocked = zones + (busy or [])
    # 探すときは gap だけ広げた矩形で見る（ぎりぎりに置かない）
    wide = [[z[0] - gap, z[1] - gap, z[2] + gap, z[3] + gap] for z in blocked]
    styles = [(pop.get("pitch", 30), pop.get("size", 56)), (26, 50), (24, 44)]
    for pitch, size in dict.fromkeys(styles):
        base = {**pop, "pitch": pitch, "size": size, "y": 200, "right": 1000}  # 端で切れない所で形を測る
        a = np.asarray(ep.pop_card(base))[..., 3]
        ys, xs = np.where(a)
        if not len(xs):
            return None
        cw, chh = int(xs.max() - xs.min()) + 1, int(ys.max() - ys.min()) + 1
        top0, left0 = int(ys.min()), int(xs.min())
        card = a[top0:top0 + chh, left0:left0 + cw]
        best = None
        for y in range(fy0 + 4, FLOOR - chh, step):
            for x in range(fx0 + 8, fx1 - 8 - cw, step):
                if any(not (x + cw <= z[0] or z[2] <= x or y + chh <= z[1] or z[3] <= y)
                       and card[max(0, z[1] - y):z[3] - y, max(0, z[0] - x):z[2] - x].any() for z in wide):
                    continue
                if target:
                    tx, ty = (target[0] + target[2]) / 2, target[1]
                    # 頭の真上か、横の壁。離れるほど悪い。高さのずれは横より重く見る
                    cost = abs(x + cw / 2 - tx) + 1.5 * abs(y + chh / 2 - max(fy0 + chh / 2, ty - chh / 2))
                else:
                    cost = y + abs(x + cw / 2 - (fx0 + fx1) / 2) * 0.2
                if best is None or cost < best[0]:
                    best = (cost, x, y)
        if best:
            _, x, y = best
            placed = {**pop, "pitch": pitch, "size": size, "y": y - (top0 - 200), "right": x + cw + (1000 - left0 - cw)}
            if not _hit(np.asarray(ep.pop_card(placed))[..., 3], blocked):
                return placed
    return None


def overlay_times(spec: dict, body: list[tuple[float, str]]) -> list[dict]:
    """本編に出す飾り（章の見出し・テロップ・名前のポップ）の一覧。時刻は完成版の時刻。"""
    from backend.program_package import episode as ep
    out = []
    for n, (t, title) in enumerate(body, start=1):
        if title not in spec.get("chapters_skip", []):
            out.append({"kind": "chapter", "n": n, "label": f"第{n}章 {title}", "at": t + (0.5 if n == 1 else 1.0),
                        "seconds": spec.get("chapter_seconds", 4.0),
                        "card": lambda n=n, title=title, right=None: ep.chapter_card(
                            n, title, (n in spec.get("chapters_right", [])) if right is None else right)})
    for tp in spec.get("telops", []):
        out.append({"kind": "telop", "label": tp["head"], "at": tp["at"], "seconds": tp.get("seconds", 5.0),
                    "card": lambda tp=tp: ep.telop_card(tp["head"], tp["body"])})
    for i, pop in enumerate(spec.get("name_pops", [])):
        out.append({"kind": "pop", "i": i, "label": pop["name"], "at": pop["at"], "seconds": pop.get("seconds", 7.0),
                    "card": lambda pop=pop: ep.pop_card(pop)})
    return out


def _bbox(im) -> list[int] | None:
    b = im.getbbox()
    return list(b) if b else None


def check(spec: dict, m: dict, body: list[tuple[float, str]]) -> list[dict]:
    """飾りが頭に掛かる所（level「掛かる」）と、掛からないが頭のすぐそばの所（「近い」）の一覧。"""
    out = []
    for o in overlay_times(spec, body):
        alpha = np.asarray(o["card"]())[..., 3]
        for level, margin in (("掛かる", CHECK_MARGIN), ("近い", NEAR_MARGIN)):
            hit = covered(alpha, head_mask(m, o["at"], o["seconds"], margin))
            if hit:
                out.append({"kind": o["kind"], "label": o["label"], "at": o["at"], "level": level, "hits": [hit]})
                break
    return out


def place(spec: dict, m: dict, body: list[tuple[float, str]]) -> dict:
    """指定ファイルの飾りを、地図に合わせて置き直した案を返す。

    - 名前のポップ: avoid を測った値に入れ替え、掛かるなら置き直す
    - 章の見出し: 左上で頭に掛かるなら右上へ（chapters_right）
    変えた所は changes に残す。置けなかったものは unplaced に残す（人が見て決める）。
    """
    new = json.loads(json.dumps(spec))
    changes, unplaced = [], []
    overlays = overlay_times(new, body)
    # 章の見出し
    right = set(new.get("chapters_right", []))
    for o in [o for o in overlays if o["kind"] == "chapter"]:
        heads = head_mask(m, o["at"], o["seconds"])
        free = {r: covered(np.asarray(o["card"](right=r))[..., 3], heads) is None for r in (False, True)}
        want = (o["n"] in right)
        if not free[want] and free[not want]:
            (right.add if not want else right.discard)(o["n"])
            changes.append(f"{o['label']}: 見出しを{'右上' if not want else '左上'}へ")
        elif not free[want]:
            unplaced.append(f"{o['label']}: 左上も右上も頭に掛かる")
    if right or "chapters_right" in new:
        new["chapters_right"] = sorted(right)
    # 名前のポップ
    overlays = overlay_times(new, body)
    for i, pop in enumerate(new.get("name_pops", [])):
        at, sec = pop["at"], pop.get("seconds", 7.0)
        zones = head_zones(m, at, sec)
        if not zones:
            unplaced.append(f"{pop['name']}: この時間帯に顔が見つからない（置き場は元のまま）")
            continue
        who = people(m, at, sec)
        side = pop.get("side") or (next(iter(who)) if len(who) == 1 else None)
        if side is None and pop.get("right"):
            side = "left" if pop["right"] < W / 2 else "right"
        busy = [b for o in overlays if o["kind"] != "pop" and o["at"] < at + sec and at < o["at"] + o["seconds"]
                for b in [_bbox(o["card"]())] if b]
        measured = {**pop, "avoid": zones,
                    "avoid_note": f"この{sec:g}秒に頭が来る所。映像から自動で測った（vision・{m['video']}）"}
        from backend.program_package import episode as ep
        if not _hit(np.asarray(ep.pop_card(measured))[..., 3], zones + busy):
            new["name_pops"][i] = measured
            if measured.get("avoid") != pop.get("avoid"):
                changes.append(f"{pop['name']}: avoid を測った値に（置き場はそのまま）")
            continue
        if pop.get("avoid") and not _hit(np.asarray(ep.pop_card(pop))[..., 3], busy) and \
                covered(np.asarray(ep.pop_card(pop))[..., 3], head_mask(m, at, sec)) is None:
            continue  # 余白は狭いが、測った頭そのものには掛からない。人が決めた置き場を動かさない
        placed = place_pop(measured, zones, who.get(side) if side else None, busy)
        if placed:
            new["name_pops"][i] = placed
            changes.append(f"{pop['name']}: 頭に掛かるので置き直し（y={placed['y']}・right={placed['right']}・"
                           f"名前の大きさ {placed['size']}）")
        else:
            new["name_pops"][i] = measured
            unplaced.append(f"{pop['name']}: 掛からない置き場が見つからない")
    return {"spec": new, "changes": changes, "unplaced": unplaced}


# ---- サムネの人物コマの候補 ----

def face_quality(f: dict) -> float:
    """顔1つの「サムネ向き」の点。大きく・はっきり検出され・こちらを向き・口が開いている（笑顔）ほど高い。"""
    _, y0, _, y1 = f["box"]
    mk = f["marks"]
    eye = max(1.0, abs(mk[2] - mk[0]))
    mid = (mk[0] + mk[2]) / 2
    front = max(0.0, 1 - abs(mk[4] - mid) / eye)          # 鼻が両目の真ん中に近いほど正面
    smile = min(1.5, abs(mk[8] - mk[6]) / eye)            # 口の幅 ÷ 目の間隔
    size = min(1.0, (y1 - y0) / 140)
    return round(f["score"] * (0.35 + 0.65 * front) * (0.5 + 0.5 * size) * (0.6 + 0.4 * smile), 4)


def thumb_candidates(m: dict, side: str, n: int = 12, apart: float = 20.0) -> list[dict]:
    """左（left）か右（right）の人の、サムネ向きのコマの候補。時刻が近いものは1つにする。"""
    found = []
    rows = m["frames"]
    for i, r in enumerate(rows):
        if r.get("board") or r["motion"] >= CUT_MOTION:
            continue
        still = 1 - min(1.0, max(r["motion"], rows[i + 1]["motion"] if i + 1 < len(rows) else 0) / 0.03)
        for f in r["faces"]:
            cx = (f["box"][0] + f["box"][2]) / 2
            if (cx < W / 2) == (side == "left"):
                found.append({"t": r["t"], "score": round(face_quality(f) * (0.7 + 0.3 * still), 4), "box": f["box"]})
    picked: list[dict] = []
    for c in sorted(found, key=lambda c: -c["score"]):
        if all(abs(c["t"] - p["t"]) >= apart for p in picked):
            picked.append(c)
            if len(picked) == n:
                break
    return picked


# ---- 目で確かめる一覧 ----

def sheet(video: Path, m: dict, at: float, seconds: float, out: Path, zones: list[list[int]] | None = None,
          card=None, cols: int = 4) -> Path:
    """区間のコマを1秒ごとに並べ、測った頭（緑）と頭の来る所（赤）、置いた飾りを重ねた一覧を作る。"""
    import cv2
    zones = head_zones(m, at, seconds) if zones is None else zones
    tiles = []
    over = None
    if card is not None:
        over = np.asarray(card.convert("RGBA").resize((640, 360)))
    for t, bgr in frames(video, 1.0, width=640, start=at, seconds=seconds):
        im = bgr.copy()
        if over is not None:
            al = over[..., 3:4] / 255.0
            im = (im * (1 - al) + over[..., 2::-1] * al).astype(np.uint8)
        near = min(m["frames"], key=lambda r: abs(r["t"] - t))
        for f in near["faces"]:
            x0, y0, x1, y1 = (v // 2 for v in head_box(f["box"], f.get("marks")))
            cv2.rectangle(im, (x0, y0), (x1, y1), (60, 220, 60), 2)
        for z in zones:
            cv2.rectangle(im, (z[0] // 2, z[1] // 2), (z[2] // 2, z[3] // 2), (60, 60, 235), 1)
        cv2.putText(im, f"{t:.1f}s", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        tiles.append(im)
    if not tiles:
        raise VisionError("この区間にコマがありません")
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    grid = np.vstack([np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)])
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), grid)
    return out


# ---- コマンド ----

def _body(spec: dict) -> list[tuple[float, str]]:
    from backend.program_package import chapters as ch
    return ch.parse(Path(spec["package"]).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="映像を見る目: 顔と頭を測り、飾りの置き場を決める")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="動画を見て地図を作る")
    s.add_argument("video")
    s.add_argument("--out", required=True)
    s.add_argument("--fps", type=float, default=2.0)
    s.add_argument("--start", type=float, default=0.0)
    s.add_argument("--seconds", type=float)
    for name, text in (("place", "飾りを置き直した案を出す"), ("check", "飾りが頭に掛かる所を出す")):
        s = sub.add_parser(name, help=text)
        s.add_argument("spec")
        s.add_argument("--map", required=True)
        if name == "place":
            s.add_argument("--write", action="store_true", help="指定ファイルを書き換える")
    s = sub.add_parser("thumbs", help="サムネの人物コマの候補を出す")
    s.add_argument("--map", required=True)
    s.add_argument("-n", type=int, default=12)
    s = sub.add_parser("sheet", help="測った結果をコマの一覧に重ねる")
    s.add_argument("video")
    s.add_argument("--map", required=True)
    s.add_argument("--at", type=float, required=True)
    s.add_argument("--seconds", type=float, default=8.0)
    s.add_argument("--out", required=True)
    a = p.parse_args(argv)
    try:
        if a.cmd == "scan":
            m = scan(Path(a.video), a.fps, a.start, a.seconds, progress=True)
            Path(a.out).write_text(json.dumps(m, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            found = sum(1 for r in m["frames"] if r["faces"])
            print(f"{a.out}: {len(m['frames'])} コマ（顔あり {found}）・場面の切れ目 {len(cuts(m))}・"
                  f"色紙や作品の区間 {len(board_spans(m))}")
            return 0
        m = load(a.map)
        if a.cmd == "thumbs":
            for side, name in (("left", "左"), ("right", "右")):
                print(f"{name}: " + " ".join(f"{c['t']:.1f}({c['score']:.2f})" for c in thumb_candidates(m, side, a.n)))
            return 0
        if a.cmd == "sheet":
            print(sheet(Path(a.video), m, a.at, a.seconds, Path(a.out)))
            return 0
        spec = json.loads(Path(a.spec).read_text(encoding="utf-8"))
        if a.cmd == "check":
            found = check(spec, m, _body(spec))
            for b in found:
                print(f"{b['level']}: {b['label']}（{b['at']:.1f} 秒）{b['hits']}")
            bad = [b for b in found if b["level"] == "掛かる"]
            print("頭に掛かる飾りはありません" if not bad else f"掛かる {len(bad)} 件")
            return 1 if bad else 0
        r = place(spec, m, _body(spec))
        for c in r["changes"]:
            print("変更: " + c)
        for u in r["unplaced"]:
            print("未決: " + u)
        if not r["changes"] and not r["unplaced"]:
            print("変更なし（いまの置き場で頭に掛からない）")
        if a.write and r["changes"]:
            Path(a.spec).write_text(json.dumps(r["spec"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"書き換えました: {a.spec}")
        return 1 if r["unplaced"] else 0
    except VisionError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
