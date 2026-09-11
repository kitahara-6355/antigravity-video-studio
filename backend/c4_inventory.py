"""R1.5-C4 の台帳と点検（2026-09-07 ユーザー決定・案D）。

**4カテゴリの数字を作る／永続化する本番の site を全件列挙し、
「印がある」か「対象外の理由がある」かを機械が確かめる。**

## なぜ台帳にしたのか

`gate-verifier` を20周使って全部 not_met だった。毎回「実在する反例」で、
欠陥が尽きなかったわけではない — **終了条件が無かった。**

掃引していた母集団は `except` 3,869 + 既定値 2,986 + フロント式 1,787 ≒ **8,642 site**。
この大きさの静的解析に対して「反例を1つ挙げよ」は、残存欠陥の密度と無関係に
**原理的にいつでも成功する**（`verification_policy` が想定していた状況そのもの）。

そこで問いを変える — 「反例はあるか」ではなく **「この台帳に漏れはあるか」**。
台帳は有限なので答えが出る。漏れを指摘されても「台帳に足す」という**有界な**修正で閉じる。

## なぜ抽出を毎回走らせるのか

**掃引の完了宣言は、修正コミットごとに無効化される**（20周目の最大の発見）。
20周目の反例3件のうち2件は「掃き終わった」と宣言した面の内側から出ており、
1件は**19周目の修正が作った**偽だった。

だから台帳に「掃いた」と書くだけでは足りない。`--gate` は**そのときのソースから
候補を作り直して**台帳と突き合わせる。関数の危険形の内訳（`fingerprint`）が
変わったら、その site は**再確認が要る**として落ちる。
自分の修正が新しい既定値を持ち込めば、その周のうちに赤くなる。

    python -m backend.c4_inventory --show     # 一覧
    python -m backend.c4_inventory --gate     # 点検（違反があれば exit 1）
    python -m backend.c4_inventory --scan     # 候補の抽出だけ（台帳は書き換えない）

台帳: `backend/config/c4_inventory.json`
"""
from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INVENTORY_PATH = REPO_ROOT / "backend" / "config" / "c4_inventory.json"

# 条件文が名指しする4カテゴリ。**ここを増やさない**（範囲は正典が決める）
CATEGORIES = ("投稿", "チャンネル統計", "品質スコア", "retention")

# 候補を拾う網。**過剰包含に倒す** — 台帳の完全性は攻められる点なので、
# 「網が狭かった」より「網は広く、外した理由が台帳にある」を選ぶ。
CATEGORY_PATTERNS = {
    "投稿": r"upload_video|placeholder_video_id|youtube_upload|upload_result|video_id",
    "チャンネル統計": (
        r"watch_time|subscriber|channel_stat|view_count|viewCount|impressions|ctr\b|CTR"
    ),
    "品質スコア": (
        r"quality_score|qualityScore|quality_gate|overall_score|quality_report|is_acceptable"
    ),
    "retention": r"retention|維持率|avg_view_duration|average_view",
}
CATEGORY_RE = {k: re.compile(v, re.IGNORECASE) for k, v in CATEGORY_PATTERNS.items()}

# 数値を直書きされたら偽 success になりうる鍵
RISK_KEY_RE = re.compile(
    r"^(quality_score|overall_score|score|watch_time_hours|watch_time|subscriber_count|"
    r"subscribers|view_count|views|impressions|ctr|click_through_rate|retention|"
    r"retention_rate|avg_view_duration|video_id|url|is_acceptable|predicted_retention)$",
    re.IGNORECASE,
)

SKIP_DIR_RE = re.compile(
    r"(^|[\\/])(__pycache__|archives|antigravity_phase18_stable_v1|"
    r"antigravity_phase19_experimental_v1|node_modules|\.git|vault-assets|vault-outputs|"
    r"_archives|snapshots|tests?)([\\/]|$)"
)
SKIP_FILE_RE = re.compile(r"(^|[\\/])(test_[^\\/]*|conftest)\.py$")

# 出所の印。`is_real` / `data_source` が基本形だが、品質ゲートのプラグイン層は
# **`checked: False` + `skip_reason`** を印として使う（「この検査は走っていない」を
# 集計側が `checked is False` で拾い、本文に「検査されていません」を出す）。
# ここを `is_real` だけにすると、正しく印を付けた 17 箇所が「印なし」に見える。
MARK_RE = re.compile(r"""['"](is_real|data_source|skip_reason)['"]""")

# `honest` は「4カテゴリだが、実測しているので印が要らない」site。
# **`marked` にすると印の存在を要求してしまい、正直な計算経路が落ちる。**
VALID_STATUS = ("marked", "honest", "out_of_scope", "unresolved")
REQUIRED_FIELDS = ("id", "file", "symbol", "category", "status", "reason", "fingerprint")


# ─────────────────────────── 抽出 ───────────────────────────

def _production_py() -> list[str]:
    出た: list[str] = []
    for path in (REPO_ROOT / "backend").rglob("*.py"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if SKIP_DIR_RE.search(rel) or SKIP_FILE_RE.search(rel):
            continue
        出た.append(rel)
    return sorted(出た)


def _is_number(node: ast.AST) -> bool:
    """数値リテラル（単項マイナス込み）か。`True` は数値に数えない。"""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (int, float)) and not isinstance(node.value, bool)
    return (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and _is_number(node.operand)
    )


def _risk_kinds(fn: ast.AST) -> list[str]:
    """偽 success を生みうる形を数える。

    **行番号は入れない。** 入れると無関係な編集で台帳が毎回ずれる。
    見たいのは「どういう形が何個あるか」であって、それがどこにあるかではない。
    """
    出た: list[str] = []
    for node in ast.walk(fn):
        # 1. except が値を返す（19・20周目の主犯）
        if isinstance(node, ast.ExceptHandler):
            for inner in ast.walk(node):
                if isinstance(inner, ast.Return) and inner.value is not None:
                    出た.append("except_returns")
        # 2. カテゴリ鍵に数値リテラルを直書きした dict
        #    （条件文が名指しする `watch_time_hours: 15200` がこれ）
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                    and RISK_KEY_RE.match(key.value)
                    and _is_number(value)
                ):
                    出た.append(f"const_dict:{key.value.lower()}")
        # 3. `.get(鍵, 既定値)` / `setdefault`
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("get", "setdefault")
            and len(node.args) == 2
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and RISK_KEY_RE.match(node.args[0].value)
        ):
            出た.append(f"default:{node.args[0].value.lower()}")
        # 4. `getattr(o, 名, 既定値)`
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) == 3
        ):
            出た.append("getattr_default")
        # 5. `x or 既定値`
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            for value in node.values[1:]:
                if _is_number(value) or (
                    isinstance(value, ast.Constant) and isinstance(value.value, str)
                ):
                    出た.append("or_default")
        # 6. 数値リテラルをそのまま返す（条件文の「常に 0.0 になる quality_score」）
        if isinstance(node, ast.Return) and node.value is not None and _is_number(node.value):
            出た.append("const_return")
    return sorted(出た)


def _walk_functions(tree: ast.AST):
    """関数を**修飾名つき**で辿る（`Klass.method` / `outer.<locals>.inner`）。

    `ast.walk` だと名前しか取れず、**別クラスの同名メソッドが同じ id になる。**
    台帳の1行が2つの実体を指すと、片方の退行を見逃す。
    """
    def 降りる(node: ast.AST, 親: list[str]):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                yield from 降りる(child, 親 + [child.name])
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield child, ".".join(親 + [child.name])
                yield from 降りる(child, 親 + [child.name, "<locals>"])
            else:
                yield from 降りる(child, 親)

    yield from 降りる(tree, [])


def scan() -> list[dict]:
    """いまのソースから 4カテゴリの候補 site を作る。

    **台帳ではなく実態。** `--gate` は毎回これを作り直して台帳と突き合わせる。
    """
    候補: list[dict] = []
    for rel in _production_py():
        try:
            src = (REPO_ROOT / rel).read_text(encoding="utf-8")
            tree = ast.parse(src)
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        lines = src.splitlines()
        使った: dict[str, int] = {}
        for node, qualname in _walk_functions(tree):
            末尾 = node.end_lineno or node.lineno
            本文 = "\n".join(lines[node.lineno - 1:末尾])
            cats = [c for c, r in CATEGORY_RE.items() if r.search(本文)]
            if not cats:
                continue
            kinds = _risk_kinds(node)
            # **同名でも別物なら別の id にする。** `file::メソッド名` だけだと
            # 別クラスの同名メソッドが衝突し、台帳の1行が2つの実体を指してしまう
            # （`_deprecated/pipeline_coordinator.py::execute` が実際に衝突した）。
            使った[qualname] = 使った.get(qualname, 0) + 1
            連番 = "" if 使った[qualname] == 1 else f"#{使った[qualname]}"
            候補.append(
                {
                    "id": f"{rel}::{qualname}{連番}",
                    "file": rel,
                    "symbol": qualname,
                    "line": node.lineno,
                    "end": 末尾,
                    "categories": cats,
                    "fingerprint": kinds,
                    "has_mark": bool(MARK_RE.search(本文)),
                }
            )
    return sorted(候補, key=lambda c: c["id"])


# ─────────────────────────── 台帳 ───────────────────────────

def load_inventory(path: Path | None = None) -> dict:
    p = Path(path or INVENTORY_PATH)
    if not p.is_file():
        raise FileNotFoundError(f"台帳がありません: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def check_entries(sites: list[dict]) -> list[str]:
    """**記載不備。**理由の無い項目は後から読めない（`feature_gaps` と同じ規則）。"""
    出た: list[str] = []
    見た: set[str] = set()
    for s in sites:
        rid = s.get("id") or "(id なし)"
        欠け = [k for k in REQUIRED_FIELDS if s.get(k) in (None, "", [])]
        # fingerprint は空リストが正常（危険形が無い site）なので別扱い
        if "fingerprint" in 欠け and isinstance(s.get("fingerprint"), list):
            欠け.remove("fingerprint")
        if 欠け:
            出た.append(f"{rid}: 項目が欠けています: {', '.join(欠け)}")
        status = s.get("status")
        if status not in VALID_STATUS:
            出た.append(f"{rid}: status は {' / '.join(VALID_STATUS)} のいずれか（いまは {status}）")
        if status in ("out_of_scope", "honest") and len(str(s.get("reason", ""))) < 10:
            出た.append(f"{rid}: {status} にするなら理由を書く（いまは {s.get('reason')!r}）")
        if s.get("category") not in CATEGORIES and status != "out_of_scope":
            出た.append(f"{rid}: category は {' / '.join(CATEGORIES)} のいずれか")
        if rid in 見た:
            出た.append(f"{rid}: id が重複しています")
        見た.add(rid)
    return 出た


def audit(sites: list[dict], 実態: list[dict] | None = None) -> tuple[list[str], list[str]]:
    """台帳と実態を突き合わせる。返り値は (違反, 情報)。

    落とすもの:

    1. **台帳に無い候補**（漏れ）— 掃引の完全性そのもの
    2. **`unresolved`** — 直っていないと分かっている偽 success
    3. **`fingerprint` の変化** — その関数に新しい危険形が入った／消えた。
       **自分の修正が作った偽を、その周のうちに落とすための門**
    4. **`marked` なのに印が消えた** — 退行
    """
    実態 = scan() if 実態 is None else 実態
    台帳 = {s["id"]: s for s in sites}
    現物 = {c["id"]: c for c in 実態}

    違反: list[str] = []
    情報: list[str] = []

    # 1. 台帳に無い候補
    for cid, c in 現物.items():
        if cid not in 台帳:
            違反.append(
                f"台帳に無い候補: {cid} "
                f"(L{c['line']} / {'+'.join(c['categories'])} / 危険形 {len(c['fingerprint'])}件)"
            )

    for sid, s in 台帳.items():
        c = 現物.get(sid)
        if c is None:
            # 消えた site は違反にしない。**掃除を促すだけ**（消したのは前進なので）
            情報.append(f"台帳にあるがソースに無い（消えたか改名された）: {sid}")
            continue

        # 3. 危険形の内訳が変わった＝この site は再確認が要る
        台帳側 = sorted(s.get("fingerprint") or [])
        現物側 = sorted(c["fingerprint"])
        if 台帳側 != 現物側:
            増 = [k for k in 現物側 if 現物側.count(k) > 台帳側.count(k)]
            減 = [k for k in 台帳側 if 台帳側.count(k) > 現物側.count(k)]
            違反.append(
                f"危険形が変わったので再確認が要ります: {sid}"
                + (f" / 増えた: {sorted(set(増))}" if 増 else "")
                + (f" / 減った: {sorted(set(減))}" if 減 else "")
            )

        # 4. 印が消えた
        if s.get("status") == "marked" and not c["has_mark"]:
            違反.append(f"印（is_real / data_source）が消えています: {sid}")

    # 2. 直っていないと分かっているもの
    for sid, s in 台帳.items():
        if s.get("status") == "unresolved":
            違反.append(f"未解決の偽 success: {sid} — {s.get('reason', '(理由なし)')}")

    return 違反, 情報


# ─────────────────────────── 表示 ───────────────────────────

def _format(inv: dict, 実態: list[dict]) -> str:
    sites = inv.get("sites", [])
    行: list[str] = []
    行.append("R1.5-C4 台帳 — 4カテゴリの本番 site")
    行.append("")
    行.append(f"  台帳: {len(sites)} 件 / いまのソースの候補: {len(実態)} 件")
    行.append("")
    for status, 見出し in (
        ("unresolved", "未解決（偽 success が残っている）"),
        ("marked", "印あり（出所を名乗っている）"),
        ("honest", "実測（印が要らない）"),
        ("out_of_scope", "対象外（理由つき）"),
    ):
        該当 = [s for s in sites if s.get("status") == status]
        行.append(f"  ## {見出し}: {len(該当)} 件")
        if status in ("marked", "honest"):
            # 一覧が長すぎるのでカテゴリ別の数だけ
            for cat in CATEGORIES:
                n = sum(1 for s in 該当 if s.get("category") == cat)
                if n:
                    行.append(f"      {cat}: {n} 件")
        else:
            for s in 該当[:40]:
                行.append(f"      - {s['id']}")
                行.append(f"          {s.get('reason', '')[:150]}")
            if len(該当) > 40:
                行.append(f"      … ほか {len(該当) - 40} 件")
        行.append("")
    return "\n".join(行)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="R1.5-C4 の台帳と点検")
    parser.add_argument("--show", action="store_true", help="一覧を出す")
    parser.add_argument("--gate", action="store_true", help="点検する（違反があれば exit 1）")
    parser.add_argument("--scan", action="store_true",
                        help="いまのソースから候補を抽出して出す（台帳は書き換えない）")
    args = parser.parse_args(argv)

    実態 = scan()

    if args.scan:
        print(json.dumps(実態, ensure_ascii=False, indent=1))
        return 0

    inv = load_inventory()
    sites = inv.get("sites", [])

    if args.show or not args.gate:
        print(_format(inv, 実態))
        if not args.gate:
            return 0

    不備 = check_entries(sites)
    違反, 情報 = audit(sites, 実態)
    全部 = 不備 + 違反

    if 情報:
        print(f"  ℹ 台帳の掃除ができます（{len(情報)} 件・違反ではありません）:")
        for m in 情報[:20]:
            print(f"      - {m}")
        if len(情報) > 20:
            print(f"      … ほか {len(情報) - 20} 件")
        print()

    if 全部:
        print(f"🚫 **R1.5-C4 の台帳と実態が食い違っています**（{len(全部)} 件）:")
        for m in 全部[:60]:
            print(f"    - {m}")
        if len(全部) > 60:
            print(f"    … ほか {len(全部) - 60} 件")
        print()
        print("  「台帳に無い候補」は**掃引の漏れ**です。1件ずつ見て、")
        print("  印を付けるか、対象外の理由を台帳に書いてください。")
        print("  「危険形が変わった」は**その関数に新しい既定値が入った**サインです。")
        print("  自分の修正が偽を作っていないか、その場で確かめてください。")
        return 1

    print(f"✅ 4カテゴリの本番 site {len(実態)} 件は、すべて印があるか対象外の理由があります。")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
