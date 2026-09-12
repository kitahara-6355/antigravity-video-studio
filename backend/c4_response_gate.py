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


def measured_を名乗る箇所(本文, 道: str = "") -> list[str]:
    出た: list[str] = []
    if isinstance(本文, dict):
        if 本文.get("data_source") == "measured":
            出た.append(道 or "(応答の先頭)")
        for k, v in 本文.items():
            出た += measured_を名乗る箇所(v, f"{道}.{k}" if 道 else str(k))
    elif isinstance(本文, list):
        for i, v in enumerate(本文):
            出た += measured_を名乗る箇所(v, f"{道}[{i}]")
    return 出た


def 母集団(app) -> list[str]:
    """**引数なし GET の `/api` ルート。**

    POST とパス引数のあるものは fixture が要るので、初回の母集団から外す
    （正典 C4b の decision）。**外した先は台帳に書く** — 隠さないことが条件。
    """
    出た = set()
    for r in app.routes:
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None) or set()
        if not path or "GET" not in methods:
            continue
        if "{" in path or not path.startswith("/api/"):
            continue
        出た.add(path)
    return sorted(出た)


def 応答を集める() -> list[tuple[str, int, object]]:
    os.environ.setdefault("GOOGLE_API_KEY", "dummy_key_for_ci")
    _遮断する()
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT / "backend"))
    from fastapi.testclient import TestClient
    from main import app

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

def audit(応答, サイドカー, 台帳) -> tuple[list[str], list[str]]:
    """返り値は (違反, 情報)。"""
    違反: list[str] = []
    情報: list[str] = []
    外した = {e["path"] for e in 台帳.get("out_of_population", [])}
    承認済み = {e["path"] for e in 台帳.get("measured_claims", [])}
    # **鍵のラチェット。** 台帳に載っている鍵の集合を超えたら落ちる
    既知の鍵 = {e["path"]: set(e.get("keys") or []) for e in 台帳.get("observed", [])}

    for path, code, body in 応答:
        if code == -1:
            違反.append(f"呼び出せませんでした: {path} — {body}")
            continue
        if code != 200 or body is None:
            情報.append(f"{path}: status {code}（4カテゴリの数字を運んでいない）")
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

    for e in 台帳.get("out_of_population", []):
        if len(str(e.get("reason", ""))) < 10:
            違反.append(f"母集団の外に置くなら理由を書く: {e.get('path')}")
    for e in 台帳.get("measured_claims", []):
        if len(str(e.get("reason", ""))) < 10:
            違反.append(f"`measured` を名乗るなら何を測ったか書く: {e.get('path')}")

    return 違反, 情報


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="R1.5-C4b: 出ていく数字が出所を名乗るか")
    ap.add_argument("--gate", action="store_true", help="違反があれば exit 1")
    ap.add_argument("--show", action="store_true", help="母集団と印の一覧を出す")
    ap.add_argument("--baseline", action="store_true",
                    help="いま出ている鍵を台帳の observed の形で出す（人が中身を確かめて貼る）")
    args = ap.parse_args(argv)

    台帳 = load_ledger()
    応答 = 応答を集める()
    サイドカー = サイドカーを書かせる()

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

    違反, 情報 = audit(応答, サイドカー, 台帳)
    if 情報:
        print(f"  ℹ {len(情報)} 件は 4カテゴリの数字を運んでいません（違反ではありません）")
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
