"""R1.5-C4b の判定（2026-09-13 ユーザー承認・案A）。

**4カテゴリの数字が外に出るとき、必ず出所を名乗る。**

## なぜソースを見るのをやめたのか

`c4_inventory`（limits #17）は母集団を 8,642 site から有限にしたが、
**各 site の中身が安全かの判定を静的述語に委ねた**ので、無限性が site の内側へ移った。
`gate-verifier` の指摘は3周続けて「書き方」の話だった:

    21周目  キーワード引数・属性代入の数値
    22周目  文字列・真偽値・モジュール定数・定数への呼び出し
    23周目  1段のローカル束縛・タプル返し・f-string・定数畳み込み

`watch = 15200` と一度置くだけでゲートは緑になる（23周目の実測）。
**「4カテゴリのどこにも偽の success が無い」を静的に示すことは、母集団が本番ソース
全体である限り有界化できない。**

そこで判定を「**出ていく数字が出所を名乗るか**」に置き換える。
間接参照・タプル・f-string・定数畳み込みは**応答本文の前では消える**ので決定可能になる。

## 何を見るか

1. **マウントしたアプリの応答本文** — 引数なし GET の `/api` を実際に叩く
2. **書き出されたサイドカー** — 書き出し口を実際に呼んで中身を見る

外部接続は `net_guard` で遮断する（**課金しない**。憲法第3条）。

## 印の語彙

門が見るのは2点だけ。**名乗っているか**と、**`measured` が台帳で承認済みか**。

`measured` は台帳で個別に承認したものだけが名乗れる。この門は外部接続を遮断した
環境で走るので、実測を名乗るなら「何をローカルで測ったか」が言えなければならない。
台帳に無い `measured` は FAIL
（`sample` → `measured` の反転を落とす。gate-verifier 22周目 M2 の形）。

**値の語彙は閉じていない。** 実測（2026-09-13）で使われているのは
`sample`（103）/ `derived`（7）/ `measured`（1）で、ソースには `unavailable` /
`gemini` / `gemini_vision` もある。閉じた語彙を強制すると、
**正直に `gemini` と名乗っている4箇所が落ちる。**

    python -m backend.c4_response_gate --show     # 母集団と印の一覧
    python -m backend.c4_response_gate --gate     # 判定（違反があれば exit 1）

台帳: `backend/config/c4_response_gate.json`
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parent.parent
LEDGER_PATH = REPO_ROOT / "backend" / "config" / "c4_response_gate.json"

# 出所の印に使われる鍵。**`measured` だけは台帳の承認が要る**（正典 C4b）。
# 値の語彙は閉じていない — 実測（2026-09-13）で `sample` / `derived` /
# `unavailable` / `gemini` / `gemini_vision` / `measured` が使われている。
# **閉じた語彙を強制すると、正直に `gemini` と名乗っている4箇所が落ちる。**
# 門が見るのは「名乗っているか」と「`measured` が承認済みか」の2点。
MARK_KEYS = frozenset((
    "is_real", "data_source", "skip_reason", "scored", "quality_scored", "measured",
    "checked", "is_mock", "is_sample", "is_stub", "is_placeholder", "is_estimated",
    "estimated",
))


def _risk_key_re():
    """**危険鍵の定義は `c4_inventory` と同じものを使う。**

    21周目の指摘は「網の内部で定義が食い違っていた」ことだった
    （`RISK_KEY_RE` は `score` を数えるのにカテゴリ語は数えていなかった）。
    2つのゲートで別々に定義すると同じ失敗を繰り返すので、正典を1つにする。
    """
    sys.path.insert(0, str(REPO_ROOT / "backend"))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_c4_inventory_for_keys", REPO_ROOT / "backend" / "c4_inventory.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.RISK_KEY_RE


RISK_KEY_RE = _risk_key_re()


def _遮断する() -> None:
    """外部接続を例外にする。**この門は課金してはいけない**（憲法第3条）。"""
    sys.path.insert(0, str(REPO_ROOT / "backend" / "tests"))
    from net_guard import install
    install()


def load_ledger(path: Path | None = None) -> dict:
    p = Path(path or LEDGER_PATH)
    if not p.is_file():
        return {"out_of_population": [], "measured_claims": []}
    return json.loads(p.read_text(encoding="utf-8"))


# ─────────────────────────── 応答本文 ───────────────────────────

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


def 名乗らない数字(本文, 祖先に印: bool = False, 道: str = "") -> list[str]:
    """**出所を名乗っていない 4カテゴリの値**を列挙する。

    印は祖先で立てても良い（`{**DATA_SOURCE, ...}` は応答の先頭に置かれる）。
    数字だけでなく**空でない文字列も見る** — 条件文の第1例
    `video_id="placeholder_video_id"` が文字列だから。
    """
    出た: list[str] = []
    if isinstance(本文, dict):
        ここに印 = 祖先に印 or 印を持つか(本文)
        for k, v in 本文.items():
            子の道 = f"{道}.{k}" if 道 else str(k)
            if isinstance(k, str) and RISK_KEY_RE.match(k) and not ここに印:
                危険 = (
                    (isinstance(v, (int, float)) and not isinstance(v, bool))
                    or (isinstance(v, str) and v != "")
                )
                if 危険:
                    出た.append(f"{子の道} = {v!r}")
            出た += 名乗らない数字(v, ここに印, 子の道)
    elif isinstance(本文, list):
        for i, v in enumerate(本文):
            出た += 名乗らない数字(v, 祖先に印, f"{道}[{i}]")
    return 出た


def 出ている鍵(本文) -> list[str]:
    """応答に**実際に載っている 4カテゴリの鍵**を並べる（印の有無に関係なく）。

    ## なぜ印の有無だけでは足りないか

    包括的な印（応答の先頭の `{**DATA_SOURCE, ...}`）は、その下の数字を全部覆う。
    だから**印を持つエンドポイントに新しい数字を足すと、名乗らせないまま通る。**
    実測で確かめた: `admin/setup/diagnostics`（`data_source: "measured"`）に
    `偽 = 7.7` を経由して `predicted_ctr` を足すと、門は緑のままだった。
    これは gate-verifier 23周目が静的側で突いたのと**同じ形**（1段のローカル束縛）。

    そこで**鍵の集合をラチェットにする。** 新しい 4カテゴリの鍵が出てきたら、
    実測かどうかを確かめて台帳に載せるまで落ちる。
    **鍵は応答から観測する**ので、間接参照・タプル・f-string・定数畳み込みでは隠れられない。
    """
    出た: set[str] = set()

    def 降りる(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(k, str) and RISK_KEY_RE.match(k):
                    危険 = (
                        (isinstance(v, (int, float)) and not isinstance(v, bool))
                        or (isinstance(v, str) and v != "")
                    )
                    if 危険:
                        出た.add(k)
                降りる(v)
        elif isinstance(o, list):
            for v in o:
                降りる(v)

    降りる(本文)
    return sorted(出た)


def _実測を名乗っているか(値) -> bool:
    """`measured` の名乗りか。**大小文字と前後の空白で抜けさせない。**

    2026-09-13 の指摘 — `Measured` / `MEASURED` / `"measured "` はすべて素通りしていた。
    この比較は `sample` → `measured` の反転を落とすために置いたものなので、
    表記ゆれで抜けるなら目的を果たしていない。
    """
    return isinstance(値, str) and 値.strip().lower() == "measured"


def measured_を名乗る箇所(本文, 道: str = "") -> list[str]:
    出た: list[str] = []
    if isinstance(本文, dict):
        if _実測を名乗っているか(本文.get("data_source")):
            出た.append(道 or "(応答の先頭)")
        for k, v in 本文.items():
            出た += measured_を名乗る箇所(v, f"{道}.{k}" if 道 else str(k))
    elif isinstance(本文, list):
        for i, v in enumerate(本文):
            出た += measured_を名乗る箇所(v, f"{道}[{i}]")
    return 出た


探り値 = "c4-gate-probe"   # パス引数に入れる合成の値


def ルート一覧(app) -> list[tuple[str, str]]:
    """`/api` の (method, path テンプレート) を全部。**版に依存しない拾い方をする。**

    2026-09-13 に CI で母集団が 0 件になり、それを success として通していた
    （fastapi 0.141.1 / starlette 1.6.0。手元は 0.135.3 / 0.52.1）。

    **原因を観測で特定した。** 新しい FastAPI の `include_router` は
    ルートを `app.routes` へ平坦化せず、`_IncludedRouter` を1個置くだけになった
    （`path=None` / `methods=None` / `routes` 属性なし）。
    `app.routes` を歩く実装では**何も見つからない。**

    そこで **`app.openapi()` を主にする** — 公開 API で、両方の版で同じ形
    （`paths: {パス: {メソッド: ...}}`）を返すことを実測で確かめた。
    ただし `include_in_schema=False` のルートは openapi に出ないので、
    **ルート走査との和**を取る。

    根本の欠陥は版ずれではなく「測れなかったことを緑にしたこと」なので、
    そちらは `population_floor` で塞いである。
    """
    出た: set[tuple[str, str]] = set()

    # 1. openapi（公開 API・版に安定）
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

    # 2. ルート走査（`include_in_schema=False` を拾う。旧版ではこちらが主だった）
    def 降りる(routes, 接頭: str = ""):
        for r in routes or ():
            path = 接頭 + (getattr(r, "path", "") or "")
            子 = getattr(r, "routes", None)
            if 子:
                降りる(子, path)
                continue
            for m in getattr(r, "methods", None) or ():
                if m not in ("HEAD", "OPTIONS") and path.startswith("/api/"):
                    出た.add((m, path))

    降りる(getattr(app, "routes", None))
    return sorted(出た)


def 母集団(app) -> list[str]:
    """**叩ける `/api` の GET。** パス引数には合成の値を入れて叩く。

    2026-09-13 に広げた（ユーザー承認）。以前は「引数なし GET」だけで、
    パス引数のある 34 本が母集団の外にあった。gate-verifier は**まさにそこ**
    （`/api/pipeline/quality-gate/drilldown/{category}`）に印の無い偽 success を
    置いて、両方の門が緑のままになることを実測で示した。

    **副作用のあるメソッド（POST / PUT / DELETE）は入れない。**
    理由は都合ではなく原則 — **門が状態を書き換えてはいけない。**
    そこに残る盲点は台帳の `side_effect_blind_spot` で一覧を固定する。

    **限界**: パス引数には合成の値しか入れないので、`if category == "live"` の
    ように**特定の値でだけ通る枝**は踏めない。これは正典 limits に明記してある。
    """
    出た = set()
    for m, path in ルート一覧(app):
        if m != "GET":
            continue
        出た.add(re.sub(r"\{[^}]*\}", 探り値, path))
    return sorted(出た)


def 除外の内訳(app) -> dict[str, int]:
    """母集団に入れなかった (method, path) の内訳。**黙って外さない。**"""
    出た: dict[str, int] = {}
    for m, _ in ルート一覧(app):
        if m == "GET":
            continue
        出た[m] = 出た.get(m, 0) + 1
    return dict(sorted(出た.items()))


def 盲点の一覧(app) -> list[str]:
    """**外したもののうち、4カテゴリの語に当たるもの。** ここが残る盲点。"""
    語 = re.compile(
        r"quality|score|retention|ctr|watch.?time|subscriber|view|impression"
        r"|upload|publish|analytics", re.IGNORECASE)
    return sorted({f"{m} {p}" for m, p in ルート一覧(app)
                   if m != "GET" and 語.search(p)})


def アプリ():
    os.environ.setdefault("GOOGLE_API_KEY", "dummy_key_for_ci")
    _遮断する()
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT / "backend"))
    from main import app
    return app


def 応答を集める(app=None) -> list[tuple[str, int, object]]:
    from fastapi.testclient import TestClient
    app = app if app is not None else アプリ()

    client = TestClient(app, raise_server_exceptions=False)
    出た = []
    for path in 母集団(app):
        try:
            res = client.get(path)
        except Exception as e:  # noqa: BLE001 — 1本の失敗で門を止めない
            出た.append((path, -1, {"_呼び出し例外": f"{type(e).__name__}: {e}"}))
            continue
        try:
            body = res.json()
        except Exception:  # noqa: BLE001 — JSON でない応答は 4カテゴリの数字を運べない
            body = None
        出た.append((path, res.status_code, body))
    return 出た


# ─────────────────────────── サイドカー ───────────────────────────

def サイドカーを書かせる() -> list[tuple[str, object]]:
    """**書き出し口を実際に呼んで中身を見る。**

    過去に書かれたファイルを読んでも、いまの書き出し口が何を書くかは分からない
    （凍結した成果物は後から印を足せない）。呼んで、書かれたものを読む。
    """
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT / "backend"))
    from agents.pipeline_coordinator import PipelineCoordinator

    # `__init__` は重い（モデル解決・エンジン初期化）。書き出し口だけ使う
    coord = PipelineCoordinator.__new__(PipelineCoordinator)
    出た: list[tuple[str, object]] = []
    with tempfile.TemporaryDirectory() as d:
        final = Path(d) / "final_test.mp4"
        final.write_bytes(b"fake")
        ctx = SimpleNamespace(
            final_path=str(final),
            quality_score=89,
            quality_feedback=["講評"],
            quality_gate_report={"raw_score": 89},
            quality_category_scores={"template": 100.0},
            quality_scored=True,
            metadata={"title": "t", "tags": ["a"]},
        )
        # **メソッド名は getattr で解決する。** 直接書くと、改名で門そのものが
        # 落ちて「違反なし」にも「違反あり」にもならない（沈黙は緑ではない）
        for 名, メソッド名 in (("*.quality.json", "_write_quality_sidecar"),
                              ("*.youtube.json", "_write_metadata_sidecar")):
            呼ぶ = getattr(coord, メソッド名, None)
            if 呼ぶ is None:
                出た.append((名, {"_呼び出し例外": f"{メソッド名} がありません（改名？）"}))
                continue
            try:
                p = 呼ぶ(ctx)
            except Exception as e:  # noqa: BLE001
                出た.append((名, {"_呼び出し例外": f"{type(e).__name__}: {e}"}))
                continue
            if not p:
                出た.append((名, None))
                continue
            出た.append((名, json.loads(Path(p).read_text(encoding="utf-8"))))
    return 出た


# ─────────────────────────── 判定 ───────────────────────────

def audit(応答, サイドカー, 台帳, 内訳: dict | None = None,
          盲点: list[str] | None = None) -> tuple[list[str], list[str]]:
    """返り値は (違反, 情報)。"""
    違反: list[str] = []
    情報: list[str] = []

    # ── **測れていないのに緑にしない。** これが最優先の検査 ──────────────
    #
    # 2026-09-13、CI でこの門は「✅ 0 ルートとサイドカー 2 件」を出して
    # exit 0 を返していた（所要 約1秒・HTTP リクエスト 0本）。手元は 304 ルート。
    # 依存の版ずれで母集団が空になったのに、**空を成功として報告した。**
    # 契約には「沈黙は緑ではない」と書いておきながら、母集団そのものが
    # 0 になる経路を塞いでいなかった。
    下限 = int(台帳.get("population_floor") or 0)
    if len(応答) < 下限:
        違反.append(
            f"**母集団が下限を割りました**: {len(応答)} < {下限}。"
            f"門が測れていないので、緑にはしません。"
            f"ルートが正当に減ったのなら台帳の population_floor を更新してください"
        )

    # ── 外したものを黙って隠さない ────────────────────────────────
    if 内訳 is not None:
        宣言 = 台帳.get("side_effect_methods") or []
        知らない = [m for m in 内訳 if m not in 宣言]
        if 知らない:
            違反.append(
                f"台帳に宣言していない method を母集団から外しています: {知らない}。"
                f"外すなら side_effect_methods に理由とともに載せてください"
            )
    if 盲点 is not None:
        既知 = set(台帳.get("side_effect_blind_spot") or [])
        増えた = sorted(set(盲点) - 既知)
        減った = sorted(既知 - set(盲点))
        if 増えた:
            違反.append(
                f"**測れない盲点が増えました**（4カテゴリの語に当たる副作用ルート）: "
                f"{増えた[:6]}"
                + (f" ほか {len(増えた) - 6} 件" if len(増えた) > 6 else "")
                + "。増やすなら台帳の side_effect_blind_spot に載せて自覚してください"
            )
        if 減った:
            情報.append(f"盲点が減りました（台帳を掃除できます）: {減った[:6]}")
    外した = {e["path"] for e in 台帳.get("out_of_population", [])}
    承認済み = {e["path"] for e in 台帳.get("measured_claims", [])}
    # **鍵のラチェット。** 台帳に載っている鍵の集合を超えたら落ちる
    既知の鍵 = {e["path"]: set(e.get("keys") or []) for e in 台帳.get("observed", [])}

    for path, code, body in 応答:
        if code == -1:
            違反.append(f"呼び出せませんでした: {path} — {body}")
            continue
        if code != 200 or body is None:
            # **「運んでいない」と断定しない。** 本文を解析していないのだから
            # 分かっているのは「JSON として読めなかった」ことだけ。
            # 2026-09-13 の指摘 — ここに 500 が9本入っていたのに、門は
            # 「4カテゴリの数字を運んでいません」と言い切って情報に落としていた。
            既知 = {f"{e.get('path')} ({e.get('status')})": e
                    for e in (台帳.get("unreadable") or [])}
            印 = f"{path} ({code})"
            if 印 in 既知:
                情報.append(f"{印}: {既知[印].get('reason', '')[:60]}")
            else:
                違反.append(
                    f"**読めない応答が増えました**: {印}。"
                    f"中身を確かめていないので「数字を運んでいない」とは言えません。"
                    f"台帳の unreadable に**理由つきで**載せるか、読めるように直してください"
                )
            continue
        if path in 外した:
            情報.append(f"{path}: 台帳で母集団の外に置いています")
            continue
        無印 = 名乗らない数字(body)
        if 無印:
            違反.append(
                f"出所を名乗っていない 4カテゴリの値: {path} — "
                + ", ".join(無印[:4]) + (f" ほか {len(無印) - 4} 件" if len(無印) > 4 else "")
            )
        # **鍵のラチェット** — 印で覆われていても、新しい数字は adjudication が要る
        いまの鍵 = set(出ている鍵(body))
        if いまの鍵:
            if path not in 既知の鍵:
                違反.append(
                    f"台帳に無いルートが 4カテゴリの数字を返しています: {path} — "
                    f"{sorted(いまの鍵)}。実測かどうか確かめて台帳の observed に載せてください"
                )
            else:
                増えた = sorted(いまの鍵 - 既知の鍵[path])
                減った = sorted(既知の鍵[path] - いまの鍵)
                if 増えた:
                    違反.append(
                        f"新しい 4カテゴリの数字が出ています: {path} — 増えた: {増えた}。"
                        f"**包括的な印はこれを覆ってしまう**ので、実測かどうかを確かめて"
                        f"台帳の observed を更新してください"
                    )
                if 減った:
                    # 減るのは前進（出す数字が減った）。**台帳の掃除を促すだけ**
                    情報.append(f"{path}: 出なくなった鍵があります（台帳を掃除できます）: {減った}")

        for 箇所 in measured_を名乗る箇所(body):
            if path not in 承認済み:
                違反.append(
                    f"台帳に無い `measured` の名乗り: {path} の {箇所}。"
                    f"外部接続を遮断した環境で実測を名乗るなら、"
                    f"**何をローカルで測ったか**を台帳に書いてください"
                )

    for 名, 中身 in サイドカー:
        # サイドカーにも同じラチェットを掛ける（包括的な印で覆う穴は同じ形で開く）
        if isinstance(中身, dict) and "_呼び出し例外" not in 中身:
            いまの鍵 = set(出ている鍵(中身))
            if いまの鍵:
                if 名 not in 既知の鍵:
                    違反.append(
                        f"台帳に無いサイドカーが 4カテゴリの数字を書いています: {名} — "
                        f"{sorted(いまの鍵)}"
                    )
                else:
                    増えた = sorted(いまの鍵 - 既知の鍵[名])
                    if 増えた:
                        違反.append(
                            f"サイドカーに新しい 4カテゴリの数字が出ています: {名} — "
                            f"増えた: {増えた}"
                        )
        if 中身 is None:
            情報.append(f"{名}: 書き出されませんでした（空なら作らない仕様）")
            continue
        if isinstance(中身, dict) and "_呼び出し例外" in 中身:
            違反.append(f"サイドカーの書き出し口を呼べませんでした: {名} — {中身}")
            continue
        無印 = 名乗らない数字(中身)
        if 無印:
            違反.append(
                f"出所を名乗っていないサイドカー: {名} — " + ", ".join(無印[:4])
                + (f" ほか {len(無印) - 4} 件" if len(無印) > 4 else "")
            )
        # **サイドカーにも `measured` の承認を要求する。**
        # 2026-09-13 まで、このループは `measured_を名乗る箇所` を呼んでおらず、
        # `*.quality.json` が未承認で `measured` を名乗っていた（私が足したもの）。
        # 条文は母集団を「エンドポイント＋成果物ライタ」と定義しているので、半分だけ
        # 施行しているのは条文違反。
        for 箇所 in measured_を名乗る箇所(中身):
            if 名 not in 承認済み:
                違反.append(
                    f"台帳に無い `measured` の名乗り: サイドカー {名} の {箇所}。"
                    f"何をローカルで測ったかを台帳に書いてください"
                )

    for e in 台帳.get("out_of_population", []):
        if len(str(e.get("reason", ""))) < 10:
            違反.append(f"母集団の外に置くなら理由を書く: {e.get('path')}")
    for e in 台帳.get("measured_claims", []):
        if len(str(e.get("reason", ""))) < 10:
            違反.append(f"`measured` を名乗るなら何を測ったか書く: {e.get('path')}")
    # **読めない応答も理由なしには載せられない。** 一覧に足すだけなら
    # 「壊れているものを追認する」ことになる（500 が11件ある）
    for e in 台帳.get("unreadable", []):
        if len(str(e.get("reason", ""))) < 10:
            違反.append(f"読めない応答を台帳に載せるなら理由を書く: {e.get('path')}")

    return 違反, 情報


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="R1.5-C4b: 出ていく数字が出所を名乗るか")
    ap.add_argument("--gate", action="store_true", help="違反があれば exit 1")
    ap.add_argument("--show", action="store_true", help="母集団と印の一覧を出す")
    ap.add_argument("--baseline", action="store_true",
                    help="いま出ている鍵を台帳の observed の形で出す（人が中身を確かめて貼る）")
    args = ap.parse_args(argv)

    台帳 = load_ledger()
    app = アプリ()
    応答 = 応答を集める(app)
    サイドカー = サイドカーを書かせる()
    内訳 = 除外の内訳(app)
    盲点 = 盲点の一覧(app)

    # **外した先を必ず見せる。** 隠さないことが母集団を狭める条件（正典 C4b）
    print(f"母集団: {len(応答)} ルート（`/api` の GET。パス引数には合成値を入れて叩く）"
          f" / サイドカー {len(サイドカー)} 件")
    print(f"母集団の外: {sum(内訳.values())} 件 {内訳}"
          f" — 門は状態を書き換えないので副作用のあるメソッドは叩かない")
    print(f"  うち 4カテゴリの語に当たる（測れない盲点）: {len(盲点)} 件")
    print()

    if args.baseline:
        外した = {e["path"] for e in 台帳.get("out_of_population", [])}
        出た = []
        for path, code, body in 応答:
            if code != 200 or body is None or path in 外した:
                continue
            鍵 = 出ている鍵(body)
            if 鍵:
                出た.append({"path": path, "keys": 鍵})
        for 名, 中身 in サイドカー:
            if isinstance(中身, dict) and "_呼び出し例外" not in 中身:
                鍵 = 出ている鍵(中身)
                if 鍵:
                    出た.append({"path": 名, "keys": 鍵})
        print(json.dumps(出た, ensure_ascii=False, indent=1))
        return 0

    if args.show:
        print(f"母集団（引数なし GET の /api）: {len(応答)} ルート")
        print(f"サイドカーの書き出し口: {len(サイドカー)} 件")
        print()
        for p, c, b in 応答:
            if c != 200 or b is None:
                continue
            無印 = 名乗らない数字(b)
            m = measured_を名乗る箇所(b)
            if 無印 or m:
                print(f"  {p}")
                if 無印:
                    print(f"      名乗っていない: {無印[:3]}")
                if m:
                    print(f"      measured: {m[:3]}")
        return 0

    違反, 情報 = audit(応答, サイドカー, 台帳, 内訳, 盲点)
    if 情報:
        print(f"  ℹ {len(情報)} 件は台帳で自覚済みです"
              f"（読めない応答・母集団の外・鍵が減った、など。違反ではありません）")
    if 違反:
        print(f"🚫 **R1.5-C4b: 出所を名乗っていない数字があります**（{len(違反)} 件）:")
        for m in 違反[:40]:
            print(f"    - {m}")
        if len(違反) > 40:
            print(f"    … ほか {len(違反) - 40} 件")
        print()
        print("  数字を出すなら `data_source`（measured / derived / sample / unavailable）と")
        print("  `is_real` を同じ応答に載せてください。母集団から外すなら台帳に理由を書きます。")
        return 1 if args.gate else 0

    print(f"✅ {len(応答)} ルートとサイドカー {len(サイドカー)} 件で、"
          f"4カテゴリの数字はすべて出所を名乗っています。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
