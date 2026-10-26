"""番組の雰囲気を「画像の案を見て選ぶだけ」で決めるための絵コンテを作る（AI を呼ばない・0円）。

2026-10-26 北原さん: ほぼ同じ形から選ぶのではなく、いろいろな形から選びたい。選んだ雰囲気に
カードで注文を付けたい。時間がかかるなら画像で決めて、試す時間そのものを短くしたい。
音楽は後で当てる。後々 ED も同じ作り方にしたい。

- 方向（DIRECTIONS）: 色・書体・置き方・現れ方・背景・締めの組み合わせ。どれも 4 コマの絵コンテ
  （書き足す途中 → 言葉が出そろう → 番組名が出る途中 → 締め）と縦の画面の1枚で見せる
- 注文（ORDERS）: 選んだ方向に足す手直し（言葉を大きく・ゆっくり・額縁など）。方向ごとに
  「注文を当てた1枚」を先に作っておくので、選択画面で押すとすぐ見比べられる
- 動画は1枚ずつ描けるので（opening.painter）、絵コンテは1案数秒で作れる。動画と曲は決まってから
- 選んだ形は番組の指定（backend/config/program/<番組>.json）の style と tune に書く。
  Shorts と本編は同じ指定を読むので、選んだ雰囲気はどちらにも効く
- 選んだ理由はソウル・ナラティブ（判断の記録）に残す（decision_logger）

使い方（リポジトリ直下で）::

    python -m backend.program_package.style_picker PROGRAM.json --out DIR          # 絵コンテを作る
    python -m backend.program_package.style_picker PROGRAM.json --apply PICK.json  # 選んだ形を書き込む

PICK.json は選択画面（Artifact）の db の picks/latest をそのまま保存したもの
（direction・style・orders・note・at）。
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

from backend.program_package import opening as op

TILE = (640, 360)  # 絵コンテの1コマ（スマホで見るので小さく軽く）
ORDER_TILE = (560, 315)
VERTICAL_TILE = (270, 480)
MOMENTS = ["書き足していく途中", "言葉が出そろう", "番組名が出る途中", "締め"]


def _d(palette, font, layout, reveal, background, finish):
    return {"palette": palette, "font": font, "layout": layout, "reveal": reveal, "background": background,
            "finish": finish}


# 方向の案。色・書体・置き方がばらけるように選んだ（どれも番組の言葉と番組名は同じ）
DIRECTIONS = {
    "now": {"label": "今の形", "mood": "10-23 に OK した形", "style": _d("murasaki", "mincho", "center", "brush", "glow", "sweep")},
    "sumi_tate": {"label": "墨と和紙の縦書き", "mood": "書道そのもの。静かで格調高い",
                  "style": _d("kinari", "fude", "vertical", "brush", "washi", "seal")},
    "kinari_fude": {"label": "生成りの筆文字", "mood": "白い紙に筆。素朴で温かい",
                    "style": _d("kinari", "fude", "center", "brush", "washi", "brush_line")},
    "kinari_left": {"label": "生成りの左寄せ", "mood": "雑誌のよう。余白が多く上品",
                    "style": _d("kinari", "mincho", "left", "rise", "washi", "brush_line")},
    "ai_night": {"label": "藍の夜", "mood": "深い藍に銀。映画の始まりのよう",
                 "style": _d("ai", "mincho", "center", "blur", "drift", "halo")},
    "ai_tate": {"label": "藍と銀の縦書き", "mood": "凛として涼しい",
                "style": _d("ai", "tokumin", "vertical", "rise", "glow", "sweep")},
    "ai_fude_left": {"label": "藍の筆・左寄せ", "mood": "力強く、現代的",
                     "style": _d("ai", "fude", "left", "blur", "washi", "seal")},
    "yoru_gold": {"label": "夜と金", "mood": "黒に金の粉。特別な場",
                  "style": _d("yoru", "mincho", "center", "brush", "gold_dust", "halo")},
    "yoru_tate": {"label": "夜の縦書き", "mood": "黒地に筆の縦書き。重厚",
                  "style": _d("yoru", "fude", "vertical", "brush", "drift", "seal")},
    "yoru_modern": {"label": "夜のゴシック", "mood": "テンポよく、今どき",
                    "style": _d("yoru", "gothic", "left", "stagger", "drift", "sweep")},
    "sakura_pen": {"label": "桜の手書き", "mood": "やわらかく、親しみやすい",
                   "style": _d("sakura", "pen", "center", "rise", "glow", "halo")},
    "sakura_tate": {"label": "桜の縦書き", "mood": "やさしい手紙のよう",
                    "style": _d("sakura", "pen", "vertical", "brush", "washi", "seal")},
    "murasaki_fude": {"label": "薄紫の筆文字", "mood": "今の色のまま、書体を筆に",
                      "style": _d("murasaki", "fude", "center", "brush", "glow", "sweep")},
    "murasaki_tate": {"label": "薄紫の縦書き", "mood": "今の色のまま、縦書きに",
                      "style": _d("murasaki", "mincho", "vertical", "brush", "glow", "seal")},
    "murasaki_left": {"label": "薄紫の飾り明朝", "mood": "今の色で、飾りのある書体を左に",
                      "style": _d("murasaki", "tokumin", "left", "rise", "drift", "brush_line")},
    "murasaki_gold": {"label": "薄紫の華やか", "mood": "金の粉と光。お祝いの場",
                      "style": _d("murasaki", "tokumin", "center", "stagger", "gold_dust", "halo")},
}

# 注文カード。group が同じものは1つだけ選べる（大きく と 控えめに は同時に選べない）
ORDERS = {
    "big_text": {"label": "言葉を大きく", "group": "size", "tune": {"text_scale": 1.2}, "at": 1},
    "small_text": {"label": "言葉を控えめに", "group": "size", "tune": {"text_scale": 0.85}, "at": 1},
    "big_title": {"label": "番組名を大きく", "group": "title", "tune": {"title_scale": 1.2}, "at": 3},
    "slower": {"label": "ゆっくり書く", "group": "pace", "tune": {"pace": 1.35}, "at": 0},
    "faster": {"label": "テンポよく", "group": "pace", "tune": {"pace": 0.75}, "at": 0},
    "brighter": {"label": "背景を明るく", "group": "bright", "tune": {"bright": 1}, "at": 1},
    "darker": {"label": "背景を暗く", "group": "bright", "tune": {"bright": -1}, "at": 1},
    "no_lines": {"label": "金の線をなくす", "group": "lines", "tune": {"lines": False}, "at": 1},
    "frame": {"label": "金の額縁を足す", "group": "frame", "tune": {"frame": True}, "at": 3},
    "seal": {"label": "落款を足す", "group": "seal", "tune": {"seal": True}, "at": 3},
}


def with_look(program: dict, style: dict, tune: dict | None = None) -> dict:
    return {**program, "style": {**op.STYLE, **style}, "tune": {**program.get("tune", {}), **(tune or {})}}


def moments(program: dict) -> list[float]:
    """絵コンテの4コマの時刻（MOMENTS の順）。"""
    st, tu = op.style_of(program), op.tune_of(program)
    sec, n = program["slide_seconds"], len(program["slides"])
    first = program["slides"][0]
    first = (first if isinstance(first, list) else [first])[0].split(" ")[0]
    step = program.get("char_seconds", 0.12) * tu["pace"]
    mid = 0.15 + op._reveal_length(st["reveal"], len(first), step) * 0.55
    tstep = program.get("title_char_seconds", 0.24) * tu["pace"]
    title_mid = n * sec + 0.2 + op._reveal_length(st["reveal"], len(program["name"]), tstep) * 0.5
    lag = {"sweep": 0.35, "seal": 0.4, "brush_line": 0.4, "halo": 0.9}[st["finish"]]
    if tu["seal"]:
        lag = max(lag, 0.4)
    end = min(n * sec + op.title_done(program) + lag, op.length(program) - 0.7)
    return [mid, (n - 1) * sec + sec - 0.6, title_mid, end]


def stills(program: dict, size: tuple[int, int], times: list[float]) -> list[Image.Image]:
    draw = op.painter(program, size)
    return [Image.fromarray((np.clip(draw(t), 0, 1) * 255).astype(np.uint8)) for t in times]


def _sheet(ims: list[Image.Image], tile: tuple[int, int], cols: int) -> Image.Image:
    rows = -(-len(ims) // cols)
    sheet = Image.new("RGB", (tile[0] * cols, tile[1] * rows), (0, 0, 0))
    for i, im in enumerate(ims):
        sheet.paste(im.resize(tile, Image.LANCZOS), (tile[0] * (i % cols), tile[1] * (i // cols)))
    return sheet


def board(program: dict, key: str, out: Path) -> dict:
    """1つの方向の絵コンテ（2x2）・縦の1枚・注文を当てた1枚ずつ（5x2）を書き出す。"""
    d = DIRECTIONS[key]
    base = with_look(program, d["style"])
    times = moments(base)
    frames = stills(base, op.SIZES["横"], times)
    _sheet(frames, TILE, 2).save(out / f"{key}-board.jpg", quality=82)
    stills(base, op.SIZES["縦"], [times[3]])[0].resize(VERTICAL_TILE, Image.LANCZOS).save(
        out / f"{key}-v.jpg", quality=82)
    orders = []
    for o in ORDERS.values():
        orders += stills(with_look(program, d["style"], o["tune"]), op.SIZES["横"], [times[o["at"]]])
    _sheet(orders, ORDER_TILE, 5).save(out / f"{key}-orders.jpg", quality=80)
    return {"id": key, "label": d["label"], "mood": d["mood"], "style": d["style"],
            "words": {k: op.CHOICES[k][v] for k, v in d["style"].items()}}


def make(program: dict, out: Path, only: list[str] | None = None, workers: int = 4) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    keys = [k for k in DIRECTIONS if not only or k in only]
    with ProcessPoolExecutor(workers) as ex:
        rows = list(ex.map(board, [program] * len(keys), keys, [out] * len(keys)))
    manifest = {"program": program["name"], "moments": MOMENTS, "current": op.style_of(program),
                "directions": rows,
                "orders": [{"id": k, "label": o["label"], "group": o["group"], "at": o["at"]} for k, o in ORDERS.items()]}
    (out / "board.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def tune_from(orders: list[str]) -> dict:
    groups = [ORDERS[o]["group"] for o in orders]
    if len(groups) != len(set(groups)):
        raise SystemExit(f"同時に選べない注文があります: {orders}")
    tune = {}
    for o in orders:
        tune.update(ORDERS[o]["tune"])
    return tune


def apply(program_path: Path, pick: dict, log=None) -> dict:
    """選んだ形を番組の指定の style と tune に書き、理由をソウル・ナラティブ（判断の記録）に残す。"""
    program = op.load(program_path)
    style = {**op.STYLE, **(pick.get("style") or {k: pick[k] for k in op.CHOICES if k in pick})}
    op.style_of({"style": style})  # 知らない選択肢なら止まる
    orders = [o for o in pick.get("orders", []) if o]
    unknown = [o for o in orders if o not in ORDERS]
    if unknown:
        raise SystemExit(f"知らない注文です: {unknown}")
    tune = tune_from(orders)
    before = op.style_of(program)
    program["style"] = style
    program["tune"] = tune
    when = str(pick.get("at", ""))[:10]
    label = DIRECTIONS.get(pick.get("direction"), {}).get("label")
    program.setdefault("history", []).append(
        f"{when} 雰囲気えらびで " + (f"「{label}」" if label else "・".join(op.CHOICES[k][v] for k, v in style.items()))
        + (f"＋注文 {'・'.join(ORDERS[o]['label'] for o in orders)}" if orders else "")
        + (f"（ひとこと: {pick['note']}）" if pick.get("note") else ""))
    program_path.write_text(json.dumps(program, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if log is None:
        from backend.decision_logger import DecisionLogger
        log = DecisionLogger()
    changed = {k: [before[k], v] for k, v in style.items() if before[k] != v}
    log.record_decision(target_type="program_style", target_path=str(program_path),
                        target_description=f"{program['name']} の番組共通 OP の雰囲気（絵コンテから選択）",
                        decision="modify" if changed or tune else "approve",
                        reason=pick.get("note") or "（ひとことなし）",
                        mood_settings={"direction": pick.get("direction"), "style": style, "changed": changed,
                                       "orders": orders, "tune": tune, "picked_at": pick.get("at")},
                        tags=["番組OP", "雰囲気えらび", *changed, *orders])
    log.sync_to_soul_narrative()
    return program


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="番組の雰囲気を選ぶための絵コンテを作る")
    p.add_argument("program")
    p.add_argument("--out")
    p.add_argument("--apply", help="選択画面で決めた形（picks/latest を保存した JSON）を番組の指定に書き込む")
    p.add_argument("--only", nargs="*", help="作る方向の id（例 now sumi_tate）")
    a = p.parse_args(argv)
    if a.apply:
        prog = apply(Path(a.program), json.loads(Path(a.apply).read_text(encoding="utf-8")))
        print(json.dumps({"style": prog["style"], "tune": prog["tune"]}, ensure_ascii=False))
        return 0
    if not a.out:
        p.error("--out か --apply のどちらかが要ります")
    m = make(op.load(a.program), Path(a.out), a.only)
    print(f"{len(m['directions'])} 案 → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
