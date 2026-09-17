"""R1.5-C4b の判定 — **面と鍵をまるごとラチェットする**（2026-09-17 ユーザー承認）。

**4カテゴリの数字が外に出るとき、必ず出所を名乗る。**

## なぜこの形なのか

| 周 | 無限性の在処 | 有界化 |
|---|---|---|
| 〜20 | どの site か | 台帳（limits #17） |
| 21〜23 | どの**書き方**か | 定義で閉じる（#18）→ 応答の観測へ（#19） |
| 24〜25 | どの**鍵名**・どの**出力面**か | **この形** |

25周目の診断: 判定を静的述語から観測へ移しても、**母集団の定義が「意味」で
書かれている限り無限性は残る**。「4カテゴリの数字か？」という述語が残る限り、
そこが破られる（D-1 台帳で外したパス全体 / D-2 サイドカーの未採点分岐 /
D-3 200 以外と HTML / D-4 列挙外の鍵名）。

そこで**述語を無くす**。検出は機械的にし、意味の判断は査読（台帳への記入）にだけ残す。

1. **面を列挙する。** 面 = 出力口（GET の応答・サイドカー）＋入力条件。
   台帳 `c4_response_faces.json` に全部載せる。**増えても消えても落ちる**
2. **面ごとに鍵の集合をまるごとラチェットする。** 鍵の道と値の種類
   （`$.stats.views:num`）。HTML は見える文字の行。
   **新しい鍵が出たら、人が査読して台帳に入れるまで落ちる**
3. **鍵名をすべて分類する。** 4カテゴリ（印が要る）か、それ以外か。
   **分類されていない鍵名が出たら落ちる。** 4カテゴリの鍵の下にある値も4カテゴリ
   （`category_scores: {"core": 77.8}` の `core` は鍵名だけでは分からない）

その代わり、API の形が変わるたびに台帳の更新が要る（churn）。それが有界性の対価。

## 門は状態を書き換えない（25周目 D-5）

286 本の副作用ルートを叩かない理由は「門は状態を書き換えない」という原則だった。
**それを門自身が破っていた** — 1回走らせるだけで `assets/asset_index.json` /
`usage_data.json` / `logs/backend.log` / chroma の DB が書き換わった。

そこで門は**追跡ファイルの複製**（`git ls-files` の作業ツリー版。無視したファイルは
入れない）の上でアプリを起こす。副産物として、**手元と CI で同じデータを測る**
（手元にしかないデータ・キャッシュ・`~/.gemini` を読まない）。**OS と機材の差は残る** —
2026-09-17 の CI（Linux）で2面に出た（`gpu-detect` の `gpu_name` は GPU の有無で変わるので
台帳に両方の形の和を載せた。`open-folder` は下の理由で揃えた）。
それでも本物のリポジトリが変わったら落とす（最後の一枚）。

**利用者のデスクトップにも触らない。** `GET /api/pipeline/open-folder` は `os.startfile()` で
エクスプローラーを開くので、Windows で門を走らせるたびに窓が開いていた。子プロセスでは
`os.startfile` と `webbrowser` を拒む関数に差し替える（どの OS でも同じ形の応答になる）。

## 入力条件

- **既定** — アプリを起こしたまま
- **パス引数** — 合成値 `c4-gate-probe` と、**台帳（`path_values`）で対応づけた一覧 API が
  実際に返す値**（26周目: `ch-001` のように API 自身が列挙する ID でしか開かない面を見ていなかった。
  2026-09-17 ユーザー承認）。テンプレート付きのルートは全部、値の出どころか、出どころが無い理由を台帳に書く
- **実走後（合格・不合格・未採点）** — `_pipeline_state` に実走の結果を差す。結果は本番の
  `_build_result` に作らせ、品質の工程は**本番の QualityGateWorker に採点させて**、本番の配線
  （`_notify_result` → `_update_stage`）で工程の状態まで進める（26周目: `stages[].data` を見ていなかった）
- **点数だけを変えた2回を比べる。** 同じ条件で点数を2通りにして、出力のどこが点数に連れて動くかを見る。
  **動いた所は出所の印に覆われていなければ落とす**（未採点では、画面の文字が動いただけで落とす）。
  以前は番兵の完全一致を探していて、`:.1f` の書式や HTML の属性ですり抜けた（26周目 M6/M10）。
  時刻のように点数と関係なく揺れる所は、同じ点数でもう1回叩いて除く
- サイドカーは書き出し口を**分岐ごとに**、同じく点数を2通りにして呼ぶ

外部接続は `net_guard` で遮断する（**課金しない**。憲法第3条）。キーは常に
`dummy_key_for_ci` にする（手元の実キーを使わせない）。

    python -m backend.c4_response_gate --gate           # 判定（違反があれば exit 1）
    python -m backend.c4_response_gate --show           # 面と印の一覧
    python -m backend.c4_response_gate --write-faces    # 面の台帳を書き直す（差分を査読する）
    python -m backend.c4_response_gate --unclassified   # 分類されていない鍵名と出現箇所

台帳: `backend/config/c4_response_gate.json`（人の判断）/
`backend/config/c4_response_faces.json`（観測した面の形）
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import html.parser
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LEDGER_PATH = REPO_ROOT / "backend" / "config" / "c4_response_gate.json"
FACES_PATH = REPO_ROOT / "backend" / "config" / "c4_response_faces.json"

# 出所の印に使われる鍵。**`measured` だけは台帳の承認が要る**（正典 C4b）。
# 値の語彙は閉じていない — 実測（2026-09-13）で `sample` / `derived` /
# `unavailable` / `gemini` / `gemini_vision` / `measured` が使われている。
# **閉じた語彙を強制すると、正直に `gemini` と名乗っている4箇所が落ちる。**
MARK_KEYS = frozenset((
    "is_real", "data_source", "skip_reason", "scored", "quality_scored", "measured",
    "checked", "is_mock", "is_sample", "is_stub", "is_placeholder", "is_estimated",
    "estimated",
))


def _risk_key_re():
    """**危険鍵の定義は `c4_inventory` と同じものを使う。**

    21周目の指摘は「網の内部で定義が食い違っていた」ことだった。
    ここでは「必ず4カテゴリとして扱う鍵名」の核に使う（台帳の分類で増やせるが、
    減らせない — 対象外にするなら面ごとの `exemptions` に理由を書く）。
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_c4_inventory_for_keys", REPO_ROOT / "backend" / "c4_inventory.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.RISK_KEY_RE


RISK_KEY_RE = _risk_key_re()

# **査読の深さを決めるだけの語。検出には使わない。**
# これに当たる鍵名を「対象外」にするなら、一括ではなく個別に理由を書く。
# 当たらない鍵名は一括で「対象外」にしてよい（新しい鍵名は面のラチェットで必ず止まる）。
STRONG_VOCAB_RE = re.compile(
    r"view|subscri|watch|retention|retain|ctr|click|impression|engagement|score|quality"
    r"|like|comment|share|revenue|rpm|cpm|grade|rating|upload|publish|video_?id|url"
    r"|audience|drop.?off",
    re.IGNORECASE,
)

探り値 = "c4-gate-probe"   # パス引数に入れる合成の値

既定 = "既定"
合格 = "実走後・採点済み（合格）"
不合格 = "実走後・採点済み（不合格）"
未採点 = "実走後・未採点"
条件の一覧 = (既定, 合格, 不合格, 未採点)

# **同じ条件の中で点数だけを変えた2つの変種。** 出力のどこが点数に連れて動くかを比べる。
# 合格・不合格は品質ゲートの閾値（90点）の同じ側に置き、分岐を変えずに値だけを動かす。
# 未採点の 0 は本番の既定値（`PipelineContext.quality_score`）
点数の変種: dict[str, tuple[float, float]] = {
    合格: (92, 97), 不合格: (85, 81), 未採点: (0, 73.21),
}


def load_ledger(path: Path | None = None) -> dict:
    p = Path(path or LEDGER_PATH)
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def load_faces(path: Path | None = None) -> dict:
    p = Path(path or FACES_PATH)
    if not p.is_file():
        return {"faces": {}}
    return json.loads(p.read_text(encoding="utf-8"))


# ─────────────────────────── 形（鍵の集合） ───────────────────────────

_素の鍵 = re.compile(r"^[^.\[\]\"':\s]+$")


def _鍵を書く(鍵: str) -> str:
    """道の1段。記号を含む鍵は JSON で括る（モデル ID の `.` で道が割れないように）。"""
    return "." + 鍵 if _素の鍵.match(鍵) else "[" + json.dumps(鍵, ensure_ascii=False) + "]"


def _種類(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "num"
    if isinstance(v, str):
        return "str"
    if isinstance(v, dict):
        return "dict"
    if isinstance(v, list):
        return "list"
    return type(v).__name__


def 形(本文) -> list[str]:
    """**応答の鍵の集合をまるごと。** 道と値の種類（`$.a[].b:num`）。

    種類まで持つのは、既存の鍵の中身を差し替える形を止めるため
    （`stats: {...}` を `stats: 15200` にしても道は変わらない）。
    """
    出た: set[str] = set()

    def 降りる(o, 道):
        出た.add(f"{道}:{_種類(o)}")
        if isinstance(o, dict):
            for k, v in o.items():
                降りる(v, 道 + _鍵を書く(str(k)))
        elif isinstance(o, list):
            for v in o:
                降りる(v, 道 + "[]")

    降りる(本文, "$")
    return sorted(出た)


def 鍵名(本文) -> set[str]:
    """本文に出てくる鍵名をすべて（値の種類によらない）。"""
    出た: set[str] = set()

    def 降りる(o):
        if isinstance(o, dict):
            for k, v in o.items():
                出た.add(str(k))
                降りる(v)
        elif isinstance(o, list):
            for v in o:
                降りる(v)

    降りる(本文)
    return 出た


# ─────────────────────────── 印 ───────────────────────────

def 印を持つか(obj: dict) -> bool:
    """出所の印を持つか。

    **空の申告は印に数えない。** `data_source: None` や `data_source: ""` は
    何も言っていないので、それで数字を通すと印を付ける意味が消える。
    真偽の印（`is_real` / `checked` / `scored` / `is_mock` …）は
    `False` でも「測れていない」という情報なので数える。
    """
    for k, v in obj.items():
        if k not in MARK_KEYS:
            continue
        if k == "data_source":
            if isinstance(v, str) and v.strip():
                return True
            continue
        return True
    return False


def 値がある(v) -> bool:
    """数字か空でない文字列。**真偽値は数字として数えない**（`passed: True`）。"""
    return (isinstance(v, (int, float)) and not isinstance(v, bool)) or (
        isinstance(v, str) and v != "")


def 葉を歩く(本文):
    """値ごとに (道, 名, 名の道, 値, 印で覆われているか, 祖先) を出す。

    - 名は値にいちばん近い鍵名。**配列の中の値も出す**（`views: [100, 200]`）
    - 名の道は鍵そのものの道（配列の `[]` を含まない）。面ごとの例外はこれで引く
    - 祖先は (鍵名, 鍵の道) の列。4カテゴリの鍵の下にある値を見分けるのに使う
    - 印は祖先で立てても良い（`{**DATA_SOURCE, ...}` は応答の先頭に置かれる）
    """
    def 降りる(o, 道, 名, 名の道, 印, 祖先):
        if isinstance(o, dict):
            ここ = 印 or 印を持つか(o)
            次 = (*祖先, (名, 名の道)) if 名 is not None else 祖先
            for k, v in o.items():
                子 = 道 + _鍵を書く(str(k))
                yield from 降りる(v, 子, str(k), 子, ここ, 次)
        elif isinstance(o, list):
            for v in o:
                yield from 降りる(v, 道 + "[]", 名, 名の道, 印, 祖先)
        elif 名 is not None:
            yield 道, 名, 名の道, o, 印, 祖先

    yield from 降りる(本文, "$", None, None, False, ())


def _危険鍵か(名: str) -> bool:
    return bool(RISK_KEY_RE.match(名))


def 名乗らない数字(本文, カテゴリか=None, 外す道=frozenset()) -> list[str]:
    """**出所を名乗っていない 4カテゴリの値**を列挙する。

    4カテゴリかどうかは、値の鍵名か、**祖先の鍵名**で決まる。
    `外す道` は面ごとの例外（台帳 `exemptions`）。**その鍵だけ**を外す —
    25周目 D-1 は、鍵1つの理由でパス全体を素通しにしていた。
    """
    カテゴリか = カテゴリか or _危険鍵か
    出た: list[str] = []
    for 道, 名, 名の道, 値, 覆われ, 祖先 in 葉を歩く(本文):
        if 覆われ or not 値がある(値) or 名の道 in 外す道:
            continue
        if カテゴリか(名) or any(カテゴリか(a) and ad not in 外す道 for a, ad in 祖先):
            出た.append(f"{道} = {値!r}")
    return 出た


def _実測を名乗っているか(値) -> bool:
    """`measured` の名乗りか。**大小文字と前後の空白で抜けさせない。**

    2026-09-13 の指摘 — `Measured` / `MEASURED` / `"measured "` はすべて素通りしていた。
    """
    return isinstance(値, str) and 値.strip().lower() == "measured"


def measured_を名乗る箇所(本文, 道: str = "$") -> list[str]:
    出た: list[str] = []
    if isinstance(本文, dict):
        if _実測を名乗っているか(本文.get("data_source")):
            出た.append(道)
        for k, v in 本文.items():
            出た += measured_を名乗る箇所(v, 道 + _鍵を書く(str(k)))
    elif isinstance(本文, list):
        for v in 本文:
            出た += measured_を名乗る箇所(v, 道 + "[]")
    return 出た


# ─────────────────────────── 点数に連れて動く所 ───────────────────────────

def _比べる形(v):
    """比べる前にそろえる。**文字列の日時は伏せる**（毎回変わる）。真偽値は数と分ける。"""
    if isinstance(v, bool):
        return ("bool", v)
    if isinstance(v, (int, float)):
        return ("num", float(v))
    if isinstance(v, str):
        return ("str", _日時.sub("<日時>", v))
    return (_種類(v), None if v is None else repr(v))


def 違う所(甲, 乙) -> list[tuple]:
    """2つの本文で**値か形が違う場所**の道（段の列）。配列は位置で比べる。"""
    出た: list[tuple] = []

    def 降りる(a, b, 道):
        if isinstance(a, dict) and isinstance(b, dict):
            for k in sorted(set(a) | set(b), key=str):
                if k in a and k in b:
                    降りる(a[k], b[k], (*道, k))
                else:
                    出た.append((*道, k))
        elif isinstance(a, list) and isinstance(b, list):
            for i in range(max(len(a), len(b))):
                if i < len(a) and i < len(b):
                    降りる(a[i], b[i], (*道, i))
                else:
                    出た.append((*道, i))
        elif _比べる形(a) != _比べる形(b):
            出た.append(道)

    降りる(甲, 乙, ())
    return 出た


def 道を書く(道: tuple) -> str:
    return "$" + "".join(f"[{s}]" if isinstance(s, int) else _鍵を書く(str(s)) for s in 道)


def 印で覆われているか(本文, 道: tuple) -> bool:
    """道の途中（その場所自身を含む）のどこかの辞書が出所の印を持つか。"""
    o = 本文
    for s in (*道, None):
        if isinstance(o, dict) and 印を持つか(o):
            return True
        if s is None:
            return False
        辞書で辿れる = isinstance(o, dict) and s in o
        配列で辿れる = isinstance(o, list) and isinstance(s, int) and 0 <= s < len(o)
        if not (辞書で辿れる or 配列で辿れる):
            return False
        o = o[s]
    return False


def 点数に連れて動く所(甲: dict, 乙: dict, 甲2: dict | None = None) -> dict:
    """同じ条件で**点数だけを変えた2回（甲・乙）**と、**甲をもう一度（甲2）**を比べる。

    - 甲と甲2で違う所は、点数と関係なく揺れる所（経過秒など）なので除く
    - JSON: 残った違いのうち、**印で覆われていない所が「漏れ」**
    - 文字（HTML）: 見える行の違いと、見えない所（属性など）の違い
    - 出口（status と種類）が変わったら、それ自体を報告する（点数で分岐している）
    """
    結果: dict = {"漏れ": [], "覆われた": 0, "文字": [], "見えない所": False, "出口": False}
    if (甲.get("status"), 甲.get("kind")) != (乙.get("status"), 乙.get("kind")):
        結果["出口"] = True
        return 結果
    if 甲.get("kind") == "json":
        揺れ = (set(違う所(甲.get("body"), 甲2.get("body")))
                if 甲2 and 甲2.get("kind") == "json" else set())
        for 道 in 違う所(甲.get("body"), 乙.get("body")):
            if 道 in 揺れ:
                continue
            if 印で覆われているか(甲.get("body"), 道) and 印で覆われているか(乙.get("body"), 道):
                結果["覆われた"] += 1
            else:
                結果["漏れ"].append(道を書く(道))
        return 結果
    行甲 = set(甲.get("lines") or ())
    揺れる行 = (行甲 ^ set(甲2.get("lines") or ())) if 甲2 else set()
    結果["文字"] = sorted((行甲 ^ set(乙.get("lines") or ())) - 揺れる行)
    生が揺れる = bool(甲2) and 甲.get("raw") != 甲2.get("raw")
    結果["見えない所"] = (not 結果["文字"] and not 生が揺れる
                         and 甲.get("raw") != 乙.get("raw"))
    return 結果


# ─────────────────────────── 本文の読み方 ───────────────────────────

_区切りタグ = frozenset((
    "p", "div", "tr", "li", "ul", "ol", "table", "br", "section", "header", "footer",
    "h1", "h2", "h3", "h4", "h5", "h6", "title", "body", "html", "head",
))
_日時 = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?")


class _見える文字(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.行: list[str] = []
        self._今: list[str] = []
        self._飛ばす = 0

    def _切る(self):
        s = " ".join("".join(self._今).split())
        if s:
            self.行.append(s)
        self._今 = []

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script"):
            self._飛ばす += 1
        if tag in _区切りタグ:
            self._切る()
        elif tag in ("td", "th"):
            self._今.append(" ")   # 表のセルは同じ行に空白で並べる

    def handle_endtag(self, tag):
        if tag in ("style", "script"):
            self._飛ばす = max(0, self._飛ばす - 1)
        if tag in _区切りタグ:
            self._切る()

    def handle_data(self, data):
        if not self._飛ばす:
            self._今.append(data)


def 文字の行(本文: str, html_か: bool) -> list[str]:
    """利用者に見える文字を行に分ける。**生成日時だけは伏せる**（毎回変わるため）。"""
    if html_か:
        p = _見える文字()
        p.feed(本文)
        p.close()
        p._切る()
        行 = p.行
    else:
        行 = [" ".join(s.split()) for s in 本文.splitlines()]
    return [_日時.sub("<日時>", s) for s in 行 if s]


def 本文を読む(res) -> dict:
    """**200 以外も読む**（25周目 D-3: 404 の本文に数字を載せても門は見ていなかった）。"""
    種類 = (res.headers.get("content-type") or "").split(";")[0].strip().lower()
    生 = res.content or b""
    if 種類 == "application/json" or 種類.endswith("+json"):
        try:
            return {"kind": "json", "body": res.json()}
        except ValueError:
            return {"kind": "text", "lines": ["（JSON と名乗っているが読めない）",
                                               *文字の行(res.text, False)],
                    "raw": _日時.sub("<日時>", res.text)}
    if not 生:
        行 = []
        if res.headers.get("location"):
            行.append(f"Location: {res.headers['location']}")
        return {"kind": "none", "lines": 行}
    if 種類.startswith("text/"):
        # 生の本文も持つ — 見える文字だけだと `<meter value="73.2">` のような
        # 属性の中の点数を見落とす（26周目 M10）
        return {"kind": "text", "lines": 文字の行(res.text, 種類 == "text/html"),
                "raw": _日時.sub("<日時>", res.text)}
    return {"kind": "binary", "lines": [種類 or "（content-type なし）"]}


def 形を取る(観測: dict) -> list[str]:
    if 観測.get("kind") == "json":
        return 形(観測.get("body"))
    return sorted(set(観測.get("lines") or ()))


# ─────────────────────────── ルート ───────────────────────────

def ルート一覧(app) -> list[tuple[str, str]]:
    """`/api` の (method, path テンプレート) を全部。**版に依存しない拾い方をする。**

    fastapi 0.141.1 / starlette 1.6.0 の `include_router` はルートを
    `app.routes` へ平坦化せず `_IncludedRouter` を1個置くだけになった
    （2026-09-13 に CI で母集団が 0 件になった原因）。そこで `app.openapi()` を主にし、
    `include_in_schema=False` を拾うためにルート走査との和を取る。
    """
    出た: set[tuple[str, str]] = set()
    try:
        paths = (app.openapi() or {}).get("paths", {}) or {}
    except Exception:  # noqa: BLE001 — 片方が壊れてももう片方で拾う
        paths = {}
    for path, ops in paths.items():
        if not str(path).startswith("/api/"):
            continue
        for m in ops or ():
            M = str(m).upper()
            if M not in ("HEAD", "OPTIONS"):
                出た.add((M, str(path)))

    def 降りる(routes, 接頭: str = ""):
        for r in routes or ():
            # fastapi 0.141 の include_router は `_IncludedRouter` を置き、中身は
            # `original_router`、付けた接頭辞は `include_context.prefix` にある。
            # ここを辿らないと、openapi に出ないルート（WebSocket・
            # include_in_schema=False）が CI の版では1本も見えなかった
            内 = getattr(r, "original_router", None)
            if 内 is not None:
                前 = getattr(getattr(r, "include_context", None), "prefix", "") or ""
                降りる(getattr(内, "routes", None), 接頭 + str(前))
                continue
            path = 接頭 + (getattr(r, "path", "") or "")
            子 = getattr(r, "routes", None)
            if 子:
                降りる(子, path)
                continue
            if not path.startswith("/api/"):
                continue
            # **WebSocket も母集団の外として数える**（26周目: 内訳に出ていなかった）
            if "WebSocket" in type(r).__name__:
                出た.add(("WEBSOCKET", path))
                continue
            for m in getattr(r, "methods", None) or ():
                if m not in ("HEAD", "OPTIONS"):
                    出た.add((m, path))

    降りる(getattr(app, "routes", None))
    return sorted(出た)


_引数 = re.compile(r"\{[^}]*\}")


def GETのテンプレート(app) -> list[str]:
    """パス引数を持つ `/api` の GET（テンプレートのまま）。"""
    return sorted(p for m, p in ルート一覧(app) if m == "GET" and _引数.search(p))


def _埋める(テンプレート: str, 値: str) -> str:
    符号 = urllib.parse.quote(str(値), safe="")
    return _引数.sub(lambda _m: 符号, テンプレート)


def 母集団(app, 値: dict[str, list[str]] | None = None) -> list[str]:
    """**叩ける `/api` の GET。** パス引数には合成の値と、台帳で対応づけた値を入れる。

    **副作用のあるメソッド（POST / PUT / DELETE）と WebSocket は入れない。**
    理由は都合ではなく原則 — **門が状態を書き換えてはいけない。**
    そこに残る盲点は台帳の `side_effect_blind_spot` で一覧を固定する。
    """
    値 = 値 or {}
    出た: set[str] = set()
    for m, path in ルート一覧(app):
        if m != "GET":
            continue
        出た.add(_埋める(path, 探り値) if _引数.search(path) else path)
        for v in 値.get(f"GET {path}", ()):
            出た.add(_埋める(path, v))
    return sorted(出た)


def _取り出す(本文, 式: str) -> list[str]:
    """`$.a.b[].c` の形の式で値を取り出す（`[]` は配列の全要素）。"""
    if not str(式).startswith("$"):
        raise ValueError(f"式は $ で始める: {式}")
    段 = re.findall(r"\.[^.\[\]]+|\[\]", 式[1:])
    if "".join(段) != 式[1:]:
        raise ValueError(f"読めない式: {式}")
    今 = [本文]
    for s in 段:
        次: list = []
        for o in 今:
            if s == "[]":
                if isinstance(o, list):
                    次.extend(o)
            elif isinstance(o, dict) and s[1:] in o:
                次.append(o[s[1:]])
        今 = 次
    return [str(v) for v in 今
            if isinstance(v, (str, int)) and not isinstance(v, bool) and str(v) != ""]


def パス引数の値(テンプレート: list[str], 既定の観測: list[dict],
                 台帳: dict) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """テンプレートごとに叩く値と、台帳との食い違い。

    台帳 `path_values` の書き方（キーは `GET <テンプレート>`）:
    - `{"from": "<一覧の面>", "take": "$.channels[].id", "limit": 3}` — 一覧 API が実際に返す値
      （一覧の並びのまま先頭から。**並びが環境で変わる一覧**（更新時刻順など）は
      `"order": "name"` を足すと、名前順に並べてから上限で切る）
    - `{"values": [...], "reason": "..."}` — コードで決まっている値
    - `{"none": "..."}` — 値の出どころが無い理由（合成の値だけで叩く）
    """
    宣言 = 台帳.get("path_values") or {}
    本文 = {o["face"]: o for o in 既定の観測}
    値: dict[str, list[str]] = {}
    問題: dict[str, list[str]] = {"未宣言": [], "値が取れない": [], "使われていない宣言": []}
    for t in テンプレート:
        経路 = f"GET {t}"
        spec = 宣言.get(経路)
        if spec is None:
            問題["未宣言"].append(経路)
            continue
        if "from" in spec:
            o = 本文.get(str(spec["from"])) or {}
            try:
                vs = _取り出す(o.get("body"), str(spec.get("take", ""))) if o.get("kind") == "json" else []
            except ValueError:
                vs = []
            vs = list(dict.fromkeys(vs))
            if spec.get("order") == "name":
                vs = sorted(vs)
            vs = vs[: int(spec.get("limit", 2))]
            if not vs:
                問題["値が取れない"].append(f"{経路} ← {spec['from']} {spec.get('take')}")
            値[経路] = vs
        elif "values" in spec:
            値[経路] = [str(v) for v in spec.get("values") or ()]
    テンプレートの経路 = {f"GET {t}" for t in テンプレート}
    問題["使われていない宣言"] = sorted(k for k in 宣言 if k not in テンプレートの経路)
    return 値, 問題


def 除外の内訳(app) -> dict[str, int]:
    """母集団に入れなかった (method, path) の内訳。**黙って外さない。**"""
    出た: dict[str, int] = {}
    for m, _ in ルート一覧(app):
        if m != "GET":
            出た[m] = 出た.get(m, 0) + 1
    return dict(sorted(出た.items()))


def 盲点の一覧(app) -> list[str]:
    """**外したもののうち、4カテゴリの語に当たるもの。** ここが残る盲点。"""
    語 = re.compile(
        r"quality|score|retention|ctr|watch.?time|subscriber|view|impression"
        r"|upload|publish|analytics", re.IGNORECASE)
    return sorted({f"{m} {p}" for m, p in ルート一覧(app)
                   if m != "GET" and (m == "WEBSOCKET" or 語.search(p))})


def 面の名前(経路: str, 条件: str) -> str:
    return 経路 if 条件 == 既定 else f"{経路}［{条件}］"


# ─────────────────────────── 隔離 ───────────────────────────

_走査で飛ばす = frozenset((
    ".git", "__pycache__", "node_modules", ".pytest_cache", ".ruff_cache", ".mypy_cache",
))


def 状態の指紋(root: Path) -> dict[str, tuple[int, int]]:
    """リポジトリのファイル（無視したものも含む）の大きさと更新時刻。"""
    出た: dict[str, tuple[int, int]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _走査で飛ばす]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            try:
                st = os.stat(p)
            except OSError:
                continue
            出た[os.path.relpath(p, root).replace(os.sep, "/")] = (st.st_size, st.st_mtime_ns)
    return 出た


def 書き換わったもの(前: dict, 後: dict) -> list[str]:
    return sorted(
        [f"変更 {p}" for p in 後 if p in 前 and 後[p] != 前[p]]
        + [f"作成 {p}" for p in 後 if p not in 前]
        + [f"削除 {p}" for p in 前 if p not in 後]
    )


def 追跡ファイル(root: Path) -> list[str]:
    """`git ls-files` の追跡ファイル＋未追跡だが無視していないもの。

    **無視したもの（`.env`・手元のデータ・ログ）は入れない。** CI のチェックアウトと
    同じものだけで測る。作業ツリーの変更（未コミット）は入る。
    """
    r = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others",
         "--exclude-standard"],
        capture_output=True, check=True)
    return sorted({p for p in r.stdout.decode("utf-8").split("\0") if p})


def 複製する(root: Path, 先: Path) -> int:
    n = 0
    for rel in 追跡ファイル(root):
        src = root / rel
        if not src.is_file():   # 作業ツリーで消したもの
            continue
        dst = 先 / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        n += 1
    return n


def _下にある(p: Path, 親: Path) -> bool:
    try:
        p.relative_to(親)
        return True
    except ValueError:
        return False


_資格情報らしい = re.compile(r"API_KEY|TOKEN|SECRET|CREDENTIAL|PASSWORD", re.IGNORECASE)


def 隔離の環境変数(作業場: Path, 複製: Path, 元: dict | None = None) -> dict[str, str]:
    """子プロセスの環境。書き込み先と読み込み元を複製と作業場に向ける。"""
    env = dict(os.environ if 元 is None else 元)
    # **鍵・トークン・資格情報らしい変数は名前で全部消す**（名指しの列挙では漏れる）。
    # `ANTIGRAVITY_ALLOW_NETWORK` は net_guard を丸ごと外すので必ず消す
    for k in list(env):
        if _資格情報らしい.search(k) or k in (
                "ANTIGRAVITY_ALLOW_NETWORK", "VIDEO_AUTOMATION_BASE_DIR",
                "ANTIGRAVITY_APP_DATA", "PYTHONHOME"):
            env.pop(k)
    家 = 作業場 / "home"
    env.update({
        # 課金しない（憲法第3条）。手元の実キーを使わせない
        "GOOGLE_API_KEY": "dummy_key_for_ci",
        "ANTIGRAVITY_DISABLE_AUTO_COMMIT": "1",
        "ANTIGRAVITY_BASE_DIR": str(複製),
        "ANTIGRAVITY_WRITABLE_ROOT": str(複製),
        "ANTIGRAVITY_VAULT_OUTPUTS": str(複製 / "vault-outputs"),
        "ANTIGRAVITY_VAULT_ASSETS": str(作業場 / "vault-assets"),
        "ANTIGRAVITY_VAULT_ENVIRONMENTS": str(作業場 / "vault-environments"),
        "ANTIGRAVITY_APP_DATA_DIR": str(作業場 / "app-data"),
        # 手元のキャッシュや `~/.gemini` を読まない（CI と同じ条件にする）
        "HOME": str(家),
        "USERPROFILE": str(家),
        # 順序は CI と同じ（`backend` が先）。`backend/tests` は道に入れない —
        # テスト用の小さなモジュールが本番の名前を覆うことがある
        "PYTHONPATH": os.pathsep.join((str(複製 / "backend"), str(複製))),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        # 集合の並びを起動ごとに変えない（文字の面が実行のたびに揺れた — 2026-09-17）
        "PYTHONHASHSEED": "0",
    })
    return env


def _外のアプリを起こさない() -> None:
    """**門は利用者のデスクトップに窓を開かない。**

    GET でも外のアプリを起こすものがある — `GET /api/pipeline/open-folder` は
    `os.startfile()` を呼ぶので、Windows で門を走らせるたびにエクスプローラーが
    開いていた（1回で最大6枚。2026-09-17 に CI との形の差から見つけた）。
    Linux には `os.startfile` が無いので、応答の形まで OS で変わっていた。
    **どの OS でも同じように拒む**（無い OS にも拒む関数を置く）。
    """
    def 拒む(*_a, **_k):
        raise OSError("C4b の門は外部のアプリを起こさない（os.startfile / webbrowser）")

    os.startfile = 拒む
    import webbrowser
    for 名 in ("open", "open_new", "open_new_tab"):
        setattr(webbrowser, 名, 拒む)


def 起こす(複製: Path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "net_guard", 複製 / "backend" / "tests" / "net_guard.py")
    net_guard = importlib.util.module_from_spec(spec)
    sys.modules["net_guard"] = net_guard
    spec.loader.exec_module(net_guard)
    net_guard.install()   # 外部接続を例外にする。**この門は課金してはいけない**
    _外のアプリを起こさない()
    import main
    if not _下にある(Path(main.__file__).resolve(), 複製.resolve()):
        raise RuntimeError(f"複製ではなく {main.__file__} を読みました（隔離できていません）")
    return main.app


def 漏れたモジュール(複製: Path, 本物: Path,
                    除外: tuple[Path, ...] | None = None) -> list[str]:
    """**複製の外（本物のリポジトリ）から読んだモジュール。** 隔離の漏れ。

    インタプリタ自身の置き場（`sys.prefix`）は除く — リポジトリの中に `.venv` を
    置いた開発機で、依存ライブラリ全部を漏れと呼ばないため。
    """
    本物 = 本物.resolve()
    写し = 複製.resolve()
    if 除外 is None:
        除外 = (Path(sys.prefix), Path(sys.base_prefix))
    除外 = tuple(Path(x).resolve() for x in 除外)
    出た = []
    for 名, m in list(sys.modules.items()):
        f = getattr(m, "__file__", None)
        if not f:
            continue
        try:
            p = Path(f).resolve()
        except OSError:
            continue
        if any(_下にある(p, x) for x in 除外):
            continue
        if _下にある(p, 本物) and not _下にある(p, 写し):
            出た.append(f"{名} ({p.relative_to(本物).as_posix()})")
    return sorted(出た)


# ─────────────────────────── 入力条件 ───────────────────────────

def _メタデータ() -> dict:
    """AI が使えないときに本番が作るメタデータ（`YouTubeOptWorker` のフォールバック）。"""
    from agents.workers.youtube_opt_worker import YouTubeOptWorker
    return YouTubeOptWorker()._generate_fallback_metadata(
        "C4b の門が合成した字幕の文です。品質ゲートの工程を確かめるために使います", [])


def _文脈(最終パス: str, 採点: bool | None, 点: float = 0):
    """本番の `PipelineContext` を作る。`採点=None` は講評もメタデータも無い実走。

    採点済みの文脈は `品質ゲートを走らせる` が本番の Worker に作らせる。
    ここで手で作るのは**未採点**（Worker が点を出さなかった）とサイドカーの入力だけ。
    """
    from agents.pipeline_types import PipelineContext, StageResult
    ctx = PipelineContext(video_path="c4-gate-probe.mp4", session_id="c4gateprobe-0001",
                          final_path=最終パス, preview_path="c4-gate-probe/preview.mp4")
    if 採点 is None:
        return ctx
    ctx.quality_scored = 採点
    ctx.quality_score = 点
    ctx.quality_feedback = ["字幕の行長が長い箇所があります"]
    ctx.metadata = _メタデータ()
    ctx.stage_results = [StageResult(stage_name="品質チェック", success=False,
                                     detail="c4-gate-probe", duration_seconds=1.5)]
    return ctx


_基準の採点: dict | None = None


def _本物の採点() -> dict:
    """本番の `run_all_plugins` を合成の文脈で一度だけ走らせ、**結果の形**を借りる。"""
    global _基準の採点
    if _基準の採点 is None:
        import quality_gate_plugins as qgp
        try:
            from template_config import template_config as tc
        except Exception:  # noqa: BLE001 — 本番の Worker も読めなければ None で進む
            tc = None
        _基準の採点 = copy.deepcopy(qgp.run_all_plugins(_文脈("c4-gate-probe/final.mp4", None), tc))
    return copy.deepcopy(_基準の採点)


def _点に合わせる(採点: dict, 点: float) -> dict:
    """減点の合計を「点」に合わせ、カテゴリの点も点に連れて動かす（値だけ。形は本番のまま）。"""
    採点["total_deductions"] = 100 - 点
    倍 = 点 / 100
    for 行 in 採点.get("category_report") or ():
        v = 行.get("score") if isinstance(行, dict) else None
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            行["score"] = round(v * 倍, 1)
    カテゴリ = 採点.get("category_scores") or {}
    for k, v in list(カテゴリ.items()):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            カテゴリ[k] = round(v * 倍, 1)
    return 採点


def 品質ゲートを走らせる(点: float, 最終パス: str = "c4-gate-probe/final.mp4"):
    """**本番の QualityGateWorker に採点させる**（26周目: 工程の進み方を再現していなかった）。

    差し替えるのは外の検査だけ — FFprobe とサムネイルの物理検査（ファイルが無いので）と、
    プラグインの減点の合計（点を狙った値にするため。**結果の形は本番の `run_all_plugins`**）。
    返り値は (worker, StageResult, 採点後の PipelineContext)。
    """
    import asyncio

    import quality_gate_plugins as qgp
    from agents.workers.quality_gate_worker import QualityGateWorker
    基準 = _本物の採点()
    ctx = _文脈(最終パス, None)
    ctx.metadata = _メタデータ()
    worker = QualityGateWorker()
    worker._ffprobe_physical_check = lambda _c: {"failures": [], "warnings": []}
    worker._thumbnail_physical_check = lambda _c: {"failures": [], "warnings": []}
    元 = qgp.run_all_plugins
    qgp.run_all_plugins = lambda _c, _tc=None: _点に合わせる(copy.deepcopy(基準), 点)
    try:
        結果 = asyncio.run(worker.execute(ctx))
    finally:
        qgp.run_all_plugins = 元
    結果.duration_seconds = 1.5   # 実時間で揺れるので固定する（値であって形ではない）
    return worker, 結果, ctx


def 実走後の状態(条件: str, 点: float) -> tuple[dict, tuple | None]:
    """`_pipeline_state` に差す実走の結果と、工程の進み方（あれば）。

    **形は本番に作らせる** — 結果は `_build_result`、採点は `QualityGateWorker`、
    点を出せなかった工程の結果は coordinator の `_normalized`。
    """
    from agents.pipeline_coordinator import PipelineCoordinator, pipeline_coordinator
    from agents.workers.quality_gate_worker import QualityGateWorker
    from routers.pipeline_default_states import get_initial_pipeline_state
    coord = PipelineCoordinator.__new__(PipelineCoordinator)
    if 条件 == 未採点:
        ctx = _文脈("c4-gate-probe/final.mp4", False, 点)
        worker = QualityGateWorker()
        通知 = (worker, pipeline_coordinator._normalized(worker, None))   # 結果を返さなかった工程
    else:
        worker, 工程, ctx = 品質ゲートを走らせる(点)
        ctx.stage_results = [工程]
        通知 = (worker, 工程)
    結果 = coord._build_result(ctx, "completed", time.time())
    結果["duration_seconds"] = 12.3   # 実時間で揺れるので固定する（値であって形ではない）
    状態 = get_initial_pipeline_state(session_id="c4gateprobe-0001",
                                    video_path="c4-gate-probe.mp4")
    状態.update(status="completed", started_at="c4-gate-probe", completed_at="c4-gate-probe",
              result=結果)
    return 状態, 通知


def _工程を進める(通知: tuple) -> None:
    """**本番の配線で工程の状態を進める**（coordinator の `_notify_result` → router の `_update_stage`）。"""
    import asyncio

    from agents.pipeline_coordinator import pipeline_coordinator
    worker, 工程 = 通知
    asyncio.run(pipeline_coordinator._notify_result(worker, 工程))


@contextlib.contextmanager
def 状態を差す(新しい状態: dict):
    # `routers` パッケージはサブモジュール名を router 実体に再束縛するので、
    # 属性ではなく sys.modules から引く（引継ぎ §7 #3 の罠）
    pr = importlib.import_module("routers.pipeline_router")
    元 = copy.deepcopy(pr._pipeline_state)
    pr._pipeline_state.clear()
    pr._pipeline_state.update(copy.deepcopy(新しい状態))
    try:
        yield
    finally:
        pr._pipeline_state.clear()
        pr._pipeline_state.update(元)


def 応答を集める(app, 条件: str = 既定, 値: dict[str, list[str]] | None = None) -> list[dict]:
    from fastapi.testclient import TestClient
    # リダイレクトは追わない — 追うと `/api` の外の面を測ることになる
    client = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    出た = []
    for path in 母集団(app, 値):
        経路 = f"GET {path}"
        記録 = {"face": 面の名前(経路, 条件), "route": 経路, "condition": 条件}
        try:
            res = client.get(path)
        except Exception as e:  # noqa: BLE001 — 1本の失敗で門を止めない
            出た.append({**記録, "status": -1, "kind": "error",
                        "error": f"{type(e).__name__}: {e}"})
            continue
        出た.append({**記録, "status": res.status_code, **本文を読む(res)})
    return 出た


def _一回書かせる(coord, メソッド名: str, 置き場: Path, 採点: bool | None, 点: float) -> dict:
    置き場.mkdir(parents=True, exist_ok=True)
    final = 置き場 / "final_test.mp4"
    final.write_bytes(b"fake")
    # **メソッド名は getattr で解決する。** 改名で門が黙るのを止める
    呼ぶ = getattr(coord, メソッド名, None)
    if 呼ぶ is None:
        return {"kind": "error", "error": f"{メソッド名} がありません（改名？）"}
    try:
        if 採点:
            _, _, ctx = 品質ゲートを走らせる(点, str(final))
        else:
            ctx = _文脈(str(final), 採点, 点)
        p = 呼ぶ(ctx)
    except Exception as e:  # noqa: BLE001
        return {"kind": "error", "error": f"{type(e).__name__}: {e}"}
    if not p:
        return {"kind": "none", "lines": []}
    return {"kind": "json", "body": json.loads(Path(p).read_text(encoding="utf-8"))}


def サイドカーを書かせる(作業場: Path) -> list[dict]:
    """**書き出し口を分岐ごとに、点数を2通りにして実際に呼ぶ。**

    25周目 D-2 — 以前は採点済みの1形でしか呼んでいなかったので、
    未採点の分岐が無印の `score` を書いても門は緑だった。
    """
    from agents.pipeline_coordinator import PipelineCoordinator
    coord = PipelineCoordinator.__new__(PipelineCoordinator)
    出た: list[dict] = []
    分岐 = (
        ("*.quality.json", "_write_quality_sidecar", "採点済み", True, 点数の変種[合格]),
        ("*.quality.json", "_write_quality_sidecar", "未採点", False, 点数の変種[未採点]),
        ("*.quality.json", "_write_quality_sidecar", "講評なし", None, (0, 0)),
        ("*.youtube.json", "_write_metadata_sidecar", "メタデータあり", True, 点数の変種[合格]),
        ("*.youtube.json", "_write_metadata_sidecar", "メタデータなし", None, (0, 0)),
    )
    for i, (経路, メソッド名, 条件, 採点, (甲点, 乙点)) in enumerate(分岐):
        記録 = {"face": f"{経路}［{条件}］", "route": 経路, "condition": 条件,
                "status": None, "unscored": 採点 is False}
        回 = {印: _一回書かせる(coord, メソッド名, 作業場 / "sidecars" / f"{i}-{印}", 採点, 点)
              for 印, 点 in (("甲", 甲点), ("乙", 乙点), ("甲2", 甲点))}
        o = {**記録, **回["甲"]}
        if o["kind"] != "error":
            o["動いた"] = 点数に連れて動く所(
                {**記録, **回["甲"]}, {**記録, **回["乙"]}, {**記録, **回["甲2"]})
        出た.append(o)
    return 出た


def _観測の本体(作業場: Path, 本物: Path) -> int:
    """**子プロセスの中身。** 複製の上でアプリを起こし、全条件の面を集めて書き出す。

    子に分けるのは、ログのファイルハンドルや chroma の DB が掴んだままでも
    **プロセスが終われば必ず放される**から（同じプロセスだと一時ツリーが消せずに残った）。
    `sys.modules` も親と混ざらない。
    """
    複製 = 作業場 / "repo"
    (作業場 / "home").mkdir(parents=True, exist_ok=True)
    app = 起こす(複製)
    台帳 = load_ledger(複製 / "backend" / "config" / "c4_response_gate.json")

    # 1. 既定（合成の値）→ 一覧 API の値を決める → 既定（台帳で対応づけた値）
    観測 = 応答を集める(app, 既定)
    値, パス引数 = パス引数の値(GETのテンプレート(app), 観測, 台帳)
    既に = {o["face"] for o in 観測}
    観測 += [o for o in 応答を集める(app, 既定, 値) if o["face"] not in 既に]

    # 2. 実走後の条件ごとに、点数だけを変えた3回（甲・乙・甲をもう一度）
    for 条件 in 条件の一覧[1:]:
        甲点, 乙点 = 点数の変種[条件]
        回: dict[str, dict[str, dict]] = {}
        for 印, 点 in (("甲", 甲点), ("乙", 乙点), ("甲2", 甲点)):
            状態, 通知 = 実走後の状態(条件, 点)
            with 状態を差す(状態):
                if 通知 is not None:
                    _工程を進める(通知)
                回[印] = {o["face"]: o for o in 応答を集める(app, 条件, 値)}
        for 名, o in 回["甲"].items():
            o["unscored"] = 条件 == 未採点
            o["動いた"] = 点数に連れて動く所(o, 回["乙"].get(名) or {}, 回["甲2"].get(名))
            観測.append(o)

    観測 += サイドカーを書かせる(作業場)
    付帯 = {"内訳": 除外の内訳(app), "盲点": 盲点の一覧(app), "パス引数": パス引数,
            "WebSocket": sorted(p for m, p in ルート一覧(app) if m == "WEBSOCKET"),
            "漏れたモジュール": 漏れたモジュール(複製, 本物)}
    (作業場 / "observed.json").write_text(
        json.dumps({"観測": 観測, "付帯": 付帯}, ensure_ascii=False), encoding="utf-8")
    return 0


def 観測する() -> tuple[list[dict], dict]:
    """追跡ファイルの複製を作り、子プロセスでアプリを起こして全条件の面を集める。"""
    前 = 状態の指紋(REPO_ROOT)
    作業場 = Path(tempfile.mkdtemp(prefix="c4gate-"))
    try:
        複製 = 作業場 / "repo"
        件数 = 複製する(REPO_ROOT, 複製)
        記録 = 作業場 / "child.log"
        with open(記録, "wb") as log:
            r = subprocess.run(
                [sys.executable, "-P", str(複製 / "backend" / "c4_response_gate.py"),
                 "--_observe", str(作業場), "--_real-root", str(REPO_ROOT)],
                cwd=複製, env=隔離の環境変数(作業場, 複製),
                stdout=log, stderr=subprocess.STDOUT, timeout=1800, check=False)
        出力 = 作業場 / "observed.json"
        if r.returncode != 0 or not 出力.is_file():
            末尾 = 記録.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
            raise RuntimeError(
                f"観測の子プロセスが失敗しました（exit {r.returncode}）:\n" + "\n".join(末尾))
        中身 = json.loads(出力.read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(作業場, ignore_errors=True)
    付帯 = 中身["付帯"]
    付帯["複製したファイル"] = 件数
    付帯["一時ツリーが残った"] = 作業場.exists()
    付帯["書き換わったもの"] = 書き換わったもの(前, 状態の指紋(REPO_ROOT))
    return 中身["観測"], 付帯


# ─────────────────────────── 判定 ───────────────────────────

def _条件つきのGETか(観測: dict) -> bool:
    return 観測.get("condition") != 既定 and str(観測.get("route", "")).startswith("GET ")


def _既定と同じ形か(観測: dict, 既定の面: dict | None) -> bool:
    """条件つきの面が、既定の面の台帳に収まるか（収まるなら台帳に別に載せない）。"""
    if 既定の面 is None:
        return False
    return ((既定の面.get("status"), 既定の面.get("kind")) == (観測["status"], 観測["kind"])
            and set(形を取る(観測)) <= set(既定の面.get("shape") or ()))


def _印の道か(署名: str) -> bool:
    """形の署名（`$.a.data_source:str`）が出所の印の鍵を指すか。"""
    道 = 署名.rsplit(":", 1)[0]
    m = re.search(r'(?:\.([^.\[\]"\':\s]+)|\["((?:[^"\\]|\\.)*)"\])$', 道)
    if not m:
        return False
    鍵 = m.group(1) if m.group(1) is not None else json.loads(f'"{m.group(2)}"')
    return 鍵 in MARK_KEYS


def _並べる(xs, n: int = 6) -> str:
    xs = list(xs)
    return f"{xs[:n]}" + (f" ほか {len(xs) - n} 件" if len(xs) > n else "")


def audit(観測: list[dict], 台帳: dict, 面台帳: dict,
          付帯: dict | None = None) -> tuple[list[str], list[str]]:
    """返り値は (違反, 情報)。`観測` は `観測する()` の形。"""
    付帯 = 付帯 or {}
    違反: list[str] = []
    情報: list[str] = []

    # ── 門が状態を書き換えていないか・隔離できているか（25周目 D-5） ──
    for p in 付帯.get("書き換わったもの") or ():
        違反.append(f"**門がリポジトリを書き換えました**: {p}。門は状態を書き換えてはいけない"
                    f"（門の実行中に手で編集したファイルもここに出ます。その場合は走らせ直す）")
    for m in 付帯.get("漏れたモジュール") or ():
        違反.append(f"**複製の外のコードを読んでいます**（隔離の漏れ）: {m}")
    if 付帯.get("一時ツリーが残った"):
        情報.append("一時ツリーを消しきれませんでした（%TEMP% / $TMPDIR の c4gate-*）")

    # ── 測れていないのに緑にしない。**数えるのは本文を検査した面**（D-7） ──
    下限 = int(台帳.get("population_floor") or 0)
    検査した = [o for o in 観測
                if o.get("condition") == 既定 and str(o.get("route", "")).startswith("GET ")
                and o.get("kind") in ("json", "text")]
    if len(検査した) < 下限:
        違反.append(
            f"**本文を検査した面が下限を割りました**: {len(検査した)} < {下限}。"
            f"門が測れていないので、緑にはしません。"
            f"ルートが正当に減ったのなら台帳の population_floor を更新してください")

    # ── 外したものを黙って隠さない ──
    if 付帯.get("内訳") is not None:
        宣言 = set(台帳.get("side_effect_methods") or []) | set(台帳.get("excluded_transports") or {})
        知らない = [m for m in 付帯["内訳"] if m not in 宣言]
        if 知らない:
            違反.append(f"台帳に宣言していない method を母集団から外しています: {知らない}。"
                        f"外すなら side_effect_methods（WebSocket などは excluded_transports）に"
                        f"理由とともに載せてください")
    for 名, 理由 in sorted((台帳.get("excluded_transports") or {}).items()):
        if len(str(理由)) < 10:
            違反.append(f"母集団の外に置く通り道には理由を書く: {名}")

    # ── パス引数の値の出どころ（26周目: 一覧 API が返す ID でしか開かない面） ──
    引数 = 付帯.get("パス引数") or {}
    for 経路 in 引数.get("未宣言") or ():
        違反.append(f"**パス引数の値の出どころが台帳にありません**: {経路}。"
                    f"path_values に一覧 API（from / take）か、決まった値（values）か、"
                    f"出どころが無い理由（none）を書いてください")
    for x in 引数.get("値が取れない") or ():
        違反.append(f"**台帳で対応づけた一覧 API から値が取れません**: {x}。"
                    f"一覧の形が変わったか、空になった")
    for 経路 in 引数.get("使われていない宣言") or ():
        情報.append(f"使われていないパス引数の宣言があります（台帳を掃除できます）: {経路}")
    for 経路, spec in sorted((台帳.get("path_values") or {}).items()):
        if not isinstance(spec, dict) or not ({"from", "values", "none"} & set(spec)):
            違反.append(f"パス引数の宣言の形が読めません: {経路}")
            continue
        if "from" in spec and not str(spec.get("take", "")).startswith("$"):
            違反.append(f"一覧 API から取る値の道（take）を書く: {経路}")
        if "order" in spec and spec["order"] != "name":
            違反.append(f"一覧の並べ方（order）は name だけ: {経路}")
        if "values" in spec and len(str(spec.get("reason", ""))) < 10:
            違反.append(f"決まった値を使うなら理由を書く: {経路}")
        if "none" in spec and len(str(spec.get("none", ""))) < 10:
            違反.append(f"値の出どころが無いなら理由を書く: {経路}")
    if 付帯.get("盲点") is not None:
        既知 = set(台帳.get("side_effect_blind_spot") or [])
        増えた = sorted(set(付帯["盲点"]) - 既知)
        減った = sorted(既知 - set(付帯["盲点"]))
        if 増えた:
            違反.append(f"**測れない盲点が増えました**（4カテゴリの語に当たる副作用ルート）: "
                        f"{_並べる(増えた)}。増やすなら台帳の side_effect_blind_spot に載せて自覚してください")
        if 減った:
            情報.append(f"盲点が減りました（台帳を掃除できます）: {_並べる(減った)}")

    面 = (面台帳 or {}).get("faces") or {}
    カテゴリ名 = dict(台帳.get("category_names") or {})
    個別 = dict(台帳.get("non_category_names_reviewed") or {})
    一括 = set(台帳.get("non_category_names") or ())
    例外: dict[str, set[str]] = {}
    for e in 台帳.get("exemptions") or ():
        例外.setdefault(str(e.get("face")), set()).add(str(e.get("key")))
    承認済み = {str(e.get("face")) for e in 台帳.get("measured_claims") or ()}
    点数を見せる面 = dict(台帳.get("score_displays") or {})
    使った見せる面: set[str] = set()

    def カテゴリか(名: str) -> bool:
        return _危険鍵か(名) or 名 in カテゴリ名

    見た面: set[str] = set()
    出た名: set[str] = set()
    使った例外: set[tuple[str, str]] = set()

    for o in 観測:
        名 = o["face"]
        見た面.add(名)
        if o.get("kind") == "error":
            違反.append(f"呼び出せませんでした: {名} — {o.get('error')}")
            continue

        # ── 面のラチェット ──
        いまの形 = 形を取る(o)
        基準 = 面.get(名)
        if 基準 is None:
            if not (_条件つきのGETか(o) and _既定と同じ形か(o, 面.get(o["route"]))):
                違反.append(
                    f"**台帳に無い面です**: {名}（{o.get('status')} {o['kind']}・"
                    f"鍵 {len(いまの形)} 個）。中身を査読して `--write-faces` で台帳に載せてください")
        else:
            if (基準.get("status"), 基準.get("kind")) != (o.get("status"), o["kind"]):
                違反.append(
                    f"**面の出口が変わりました**: {名} — 台帳 {基準.get('status')} {基準.get('kind')}"
                    f" → いま {o.get('status')} {o['kind']}。中身を査読して台帳を更新してください")
            増えた = sorted(set(いまの形) - set(基準.get("shape") or ()))
            減った = sorted(set(基準.get("shape") or ()) - set(いまの形))
            if 増えた:
                違反.append(
                    f"**新しい鍵が出ています**: {名} — {_並べる(増えた)}。"
                    f"**包括的な印はこれを覆ってしまう**ので、4カテゴリかどうかを査読して台帳に載せてください")
            # **出所の印が消えるのは退行**（26周目への対処）。文字に埋まった点数
            # （障害の見出しの「85→72」）は鍵名では見えないので、印が消えたこと自体を止める
            消えた印 = [x for x in 減った if o["kind"] == "json" and _印の道か(x)]
            if 消えた印:
                違反.append(
                    f"**出所の印が消えました**: {名} — {_並べる(消えた印, 4)}。"
                    f"意図して外したなら査読して `--write-faces` で台帳を更新してください")
            減った = [x for x in 減った if x not in 消えた印]
            if 減った:
                情報.append(f"{名}: 出なくなった鍵があります（別の OS・機材でだけ出る鍵かもしれないので、"
                            f"CI の成果物と突き合わせてから掃除する）: {_並べる(減った, 3)}")

        # ── 点数に連れて動く所（26周目: 番兵の完全一致は書式ひとつで抜けた） ──
        動いた = o.get("動いた") or {}
        if 動いた.get("出口"):
            違反.append(f"**点数によって出口（status と種類）が変わります**: {名}。"
                        f"閾値の同じ側で値だけを変えたのに分岐している")
        if 動いた.get("漏れ"):
            違反.append(f"**点数に連れて動くのに出所を名乗っていない値**: {名} — "
                        f"{_並べる(動いた['漏れ'], 4)}")
        if 動いた.get("文字") or 動いた.get("見えない所"):
            差 = _並べる(動いた.get("文字") or ["（見えない所 — 属性など — が変わった）"], 3)
            if o.get("unscored"):
                違反.append(f"**未採点の点数が画面に出ています**: {名} — {差}")
            elif o.get("route") in 点数を見せる面:
                使った見せる面.add(o["route"])
            else:
                違反.append(f"**点数を文字で見せる面が台帳にありません**: {名} — {差}。"
                            f"採点した点を見せてよい面なら score_displays に理由つきで載せてください")

        if o["kind"] != "json":
            continue
        本文 = o.get("body")
        出た名 |= 鍵名(本文)

        # ── 印の検査（例外は面ごと・鍵ごと） ──
        外す道 = frozenset(例外.get(名, set()) | (
            例外.get(o["route"], set()) if _条件つきのGETか(o) else set()))
        for k in 外す道:
            使った例外.add((名, k))
        無印 = 名乗らない数字(本文, カテゴリか, 外す道)
        if 無印:
            違反.append(f"**出所を名乗っていない 4カテゴリの値**: {名} — {_並べる(無印, 4)}")

        # ── `measured` は台帳の承認が要る ──
        承認 = 名 in 承認済み or (_条件つきのGETか(o) and o["route"] in 承認済み)
        for 箇所 in measured_を名乗る箇所(本文):
            if not 承認:
                違反.append(
                    f"台帳に無い `measured` の名乗り: {名} の {箇所}。"
                    f"外部接続を遮断した環境で実測を名乗るなら、**何をローカルで測ったか**を台帳に書いてください")

    # ── 消えた面（ルートが消えた・書き出し口が消えた） ──
    for 名 in sorted(set(面) - 見た面):
        違反.append(f"**面が消えました**: {名}。意図した削除なら `--write-faces` で台帳から外してください")
    for 名 in sorted(set(面) & 見た面):
        o = next((x for x in 観測 if x["face"] == 名), None)
        if o is not None and _条件つきのGETか(o) and _既定と同じ形か(o, 面.get(o["route"])):
            情報.append(f"{名}: 既定と同じ形になりました（台帳から外せます）")

    # ── 鍵名の分類 ──
    # 印の鍵そのもの（`is_real` / `data_source` …）は分類済みとして扱う
    未分類 = sorted(n for n in 出た名 if not カテゴリか(n) and n not in MARK_KEYS
                 and n not in 個別 and n not in 一括)
    if 未分類:
        違反.append(
            f"**分類されていない鍵名があります**（{len(未分類)} 個）: {_並べる(未分類, 10)}。"
            f"4カテゴリなら category_names、違うなら non_category_names に載せてください"
            f"（`--unclassified` で出現箇所が見られます）")
    for n in sorted((set(個別) | 一括) & set(カテゴリ名)):
        違反.append(f"4カテゴリの鍵名を対象外にも分類しています: {n}。"
                    f"場所によって違うなら、面ごとの exemptions に理由を書いてください")
    for n in sorted(一括):
        if _危険鍵か(n):
            違反.append(f"危険鍵は一括で対象外にできません: {n}（面ごとの exemptions を使う）")
        elif STRONG_VOCAB_RE.search(n):
            違反.append(f"紛らわしい鍵名を一括で対象外にしています: {n}。"
                        f"non_category_names_reviewed に個別の理由を書いてください")
    for n, r in sorted(個別.items()):
        if _危険鍵か(n):
            違反.append(f"危険鍵は対象外にできません: {n}（面ごとの exemptions を使う）")
        if len(str(r)) < 10:
            違反.append(f"対象外にする理由を書く: {n}")
    for n, r in sorted(カテゴリ名.items()):
        if len(str(r)) < 10:
            違反.append(f"4カテゴリに入れる理由を書く: {n}")

    # ── 例外と承認は理由つき。使われていないものは掃除を促す ──
    for e in 台帳.get("exemptions") or ():
        if len(str(e.get("reason", ""))) < 10:
            違反.append(f"例外にするなら理由を書く: {e.get('face')} {e.get('key')}")
        if (str(e.get("face")), str(e.get("key"))) not in 使った例外:
            情報.append(f"使われていない例外があります（台帳を掃除できます）: {e.get('face')} {e.get('key')}")
    for e in 台帳.get("measured_claims") or ():
        if len(str(e.get("reason", ""))) < 10:
            違反.append(f"`measured` を名乗るなら何を測ったか書く: {e.get('face')}")
        if str(e.get("face")) not in 見た面:
            情報.append(f"観測されていない面の承認があります: {e.get('face')}")
    for 経路, 理由 in sorted(点数を見せる面.items()):
        if len(str(理由)) < 10:
            違反.append(f"点数を文字で見せてよい理由を書く: {経路}")
        if 経路 not in 使った見せる面:
            情報.append(f"点数を見せなかった面の宣言があります（台帳を掃除できます）: {経路}")

    return 違反, 情報


# ─────────────────────────── 台帳の書き出し ───────────────────────────

def 面台帳を作る(観測: list[dict], 既存: dict | None = None, 足すだけ: bool = False) -> dict:
    """観測から面の台帳を作る。**条件つきの面は既定と違うときだけ載せる。**

    `足すだけ` は既存の形に和を取る（別の環境で出た鍵を足すとき）。
    """
    既存 = 既存 or {}
    面: dict[str, dict] = {}
    既定の面 = {o["route"]: {"status": o.get("status"), "kind": o["kind"], "shape": 形を取る(o)}
               for o in 観測 if o.get("condition") == 既定 and o.get("kind") != "error"}
    for o in 観測:
        if o.get("kind") == "error":
            continue
        if _条件つきのGETか(o) and _既定と同じ形か(o, 既定の面.get(o["route"])):
            continue
        面[o["face"]] = {"status": o.get("status"), "kind": o["kind"], "shape": 形を取る(o)}
    if 足すだけ:
        for 名, 旧 in (既存.get("faces") or {}).items():
            if 名 in 面 and (旧.get("status"), 旧.get("kind")) == (面[名]["status"], 面[名]["kind"]):
                面[名]["shape"] = sorted(set(面[名]["shape"]) | set(旧.get("shape") or ()))
    出す = {k: v for k, v in 既存.items() if k != "faces"}
    出す["faces"] = dict(sorted(面.items()))
    return 出す


def 未分類の出現(観測: list[dict], 台帳: dict) -> dict[str, list[str]]:
    カテゴリ名 = set(台帳.get("category_names") or {})
    分類済み = カテゴリ名 | MARK_KEYS | set(台帳.get("non_category_names_reviewed") or {}) | set(
        台帳.get("non_category_names") or ())
    出た: dict[str, list[str]] = {}
    for o in 観測:
        if o.get("kind") != "json":
            continue
        for 道, 名, _, 値, 覆われ, _ in 葉を歩く(o.get("body")):
            if 名 in 分類済み or _危険鍵か(名):
                continue
            出た.setdefault(名, [])
            if len(出た[名]) < 3:
                出た[名].append(f"{o['face']} {道} = {値!r:.60}{'（印あり）' if 覆われ else ''}")
        for n in 鍵名(o.get("body")):
            if n not in 分類済み and not _危険鍵か(n):
                出た.setdefault(n, [])
    return dict(sorted(出た.items()))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="R1.5-C4b: 出ていく数字が出所を名乗るか（面と鍵のラチェット）")
    ap.add_argument("--gate", action="store_true", help="違反があれば exit 1")
    ap.add_argument("--show", action="store_true", help="面と印の一覧を出す")
    ap.add_argument("--write-faces", action="store_true",
                    help="面の台帳を観測で書き直す（差分を人が査読する）")
    ap.add_argument("--merge", action="store_true",
                    help="--write-faces で既存の形との和を取る（別の環境で出た鍵を足すとき）")
    ap.add_argument("--unclassified", action="store_true", help="分類されていない鍵名と出現箇所")
    ap.add_argument("--faces-out", help="観測した面を台帳と同じ形でこのパスへ書く（CI の成果物用）")
    ap.add_argument("--_observe", help=argparse.SUPPRESS)      # 子プロセス用
    ap.add_argument("--_real-root", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args._observe:
        return _観測の本体(Path(args._observe), Path(args._real_root))

    台帳 = load_ledger()
    面台帳 = load_faces()
    始め = time.time()
    観測, 付帯 = 観測する()
    所要 = time.time() - 始め

    既定の面 = [o for o in 観測 if o.get("condition") == 既定 and o["route"].startswith("GET ")]
    内訳 = 付帯.get("内訳") or {}
    print(f"母集団: GET {len(既定の面)} ルート × 入力条件 {len(条件の一覧)}"
          f"（{' / '.join(条件の一覧)}）＋ サイドカーの分岐 "
          f"{sum(1 for o in 観測 if not o['route'].startswith('GET '))} 件"
          f" — 複製 {付帯.get('複製したファイル')} ファイルの上で {所要:.1f} 秒")
    print(f"母集団の外: {sum(内訳.values())} 件 {内訳}"
          f" — 門は状態を書き換えないので副作用のあるメソッドは叩かない")
    print(f"  うち 4カテゴリの語に当たる（測れない盲点）: {len(付帯.get('盲点') or [])} 件"
          f"（WebSocket {len(付帯.get('WebSocket') or [])} 本を含む）")
    引数 = 付帯.get("パス引数") or {}
    print(f"パス引数: 合成の値と、台帳（path_values）で対応づけた一覧 API の値で叩く"
          f"（未宣言 {len(引数.get('未宣言') or [])} / 値が取れない {len(引数.get('値が取れない') or [])}）")
    print()

    if args.faces_out:
        # 台帳は書き換えない。別の環境（CI の Linux）で出た形を持ち帰るためのもの
        Path(args.faces_out).write_text(
            json.dumps(面台帳を作る(観測), ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8", newline="\n")

    if args.write_faces:
        出す = 面台帳を作る(観測, 面台帳, 足すだけ=args.merge)
        # 改行は OS によらず LF（Windows で CRLF になると全行差分に見える）
        FACES_PATH.write_text(json.dumps(出す, ensure_ascii=False, indent=1) + "\n",
                              encoding="utf-8", newline="\n")
        print(f"面の台帳を書きました: {FACES_PATH.relative_to(REPO_ROOT).as_posix()}"
              f"（{len(出す['faces'])} 面）。**git diff を査読してください**")
        return 0

    if args.unclassified:
        for 名, 例 in 未分類の出現(観測, 台帳).items():
            print(f"{名}{'  ← 紛らわしい語' if STRONG_VOCAB_RE.search(名) else ''}")
            for x in 例:
                print(f"    {x}")
        return 0

    if args.show:
        for o in 観測:
            if o.get("kind") != "json":
                print(f"  {o['face']}: {o.get('status')} {o['kind']}（{len(o.get('lines') or [])} 行）")
                continue
            m = measured_を名乗る箇所(o.get("body"))
            if m:
                print(f"  {o['face']}: measured {m[:3]}")
        return 0

    違反, 情報 = audit(観測, 台帳, 面台帳, 付帯)
    if 情報:
        print(f"  ℹ {len(情報)} 件の情報（台帳の掃除候補など。違反ではありません）")
        for m in 情報[:10]:
            print(f"    · {m}")
    if 違反:
        print(f"🚫 **R1.5-C4b: 違反があります**（{len(違反)} 件）:")
        for m in 違反[:60]:
            print(f"    - {m}")
        if len(違反) > 60:
            print(f"    … ほか {len(違反) - 60} 件")
        print()
        print("  数字を出すなら `data_source`（measured / derived / sample / unavailable）と")
        print("  `is_real` を同じ応答に載せてください。形が変わったなら査読して台帳を更新します。")
        return 1 if args.gate else 0

    print(f"✅ {len(観測)} 面（GET {len(既定の面)} ルート × {len(条件の一覧)} 条件＋サイドカー）で、"
          f"形は台帳どおり、4カテゴリの数字はすべて出所を名乗っています。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
