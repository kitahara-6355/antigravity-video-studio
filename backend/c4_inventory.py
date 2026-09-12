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
from collections import Counter
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
    # **裸の `score` と日本語も見る**（gate-verifier 21周目の指摘）。
    # `RISK_KEY_RE` は `score` を危険鍵に数えているのに、カテゴリ語が
    # `quality_score` 等に限られていたため、`{"score": 72}` を返す
    # `admin_channel_router.get_quality_improvement` が候補にすらならなかった。
    # **網の内部で定義が食い違っていた。**
    "品質スコア": (
        r"quality_score|qualityScore|quality_gate|overall_score|quality_report"
        r"|is_acceptable|\bscore\b|品質スコア|品質評価|採点"
    ),
    "retention": r"retention|維持率|avg_view_duration|average_view|視聴維持",
}
CATEGORY_RE = {k: re.compile(v, re.IGNORECASE) for k, v in CATEGORY_PATTERNS.items()}

# 数値を直書きされたら偽 success になりうる鍵
RISK_KEY_RE = re.compile(
    r"^(quality_score|overall_score|score|final_score|initial_score|current_score|"
    r"average_improvement|watch_time_hours|watch_time|subscriber_count|"
    r"subscribers|view_count|views|impressions|ctr|ctr_score|expected_ctr|predicted_ctr|"
    r"click_through_rate|retention|retention_rate|avg_retention|predicted_retention|"
    r"avg_view_duration|video_id|url|is_acceptable|is_ready|passed)$",
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
# `scored` / `quality_scored` / `measured` も「測ったか」の印。
# `quality_gate_agent` や `pipeline_coordinator` はこの形で未計測を表す。
MARK_RE = re.compile(
    r"""['"](is_real|data_source|skip_reason|scored|quality_scored|measured"""
    r"""|is_mock|is_sample|is_stub|is_placeholder|is_estimated|estimated)['"]"""
)

# **辞書の先頭で印を展開する形**（`{**DATA_SOURCE, ...}`）。
# `admin_channel_router` / `admin_analytics_router` はこの書き方で印を付けており、
# 文字列リテラルが本文に出てこない。これを見ないと、
# **`**DATA_SOURCE` を消しても「印は元から無い」と見なして素通りする**
# （gate-verifier 21周目の指摘。`watch_time_hours: 15200` が無印になる変異が通った）。
# 先頭の `[A-Za-z_]` を必須にすると **`**DATA_SOURCE` そのもの**が外れる
# （接頭辞の無い名前に一致できない）。`[\w.]*` は空でよい。
SPREAD_MARK_RE = re.compile(r"\*\*\s*[\w.]*(DATA_SOURCE|MARK|印)", re.IGNORECASE)


def _コメントを落とす(src: str) -> str:
    """コメントを取り除いた写しを返す。

    **印の検査をコメントで満たせてはいけない**（gate-verifier 21周目の指摘）。
    印を全部消して「`is_real` を消した」と書いたコメントだけ残す変異が通っていた。
    """
    import io as _io
    import tokenize as _tk

    try:
        出た = []
        for tok in _tk.generate_tokens(_io.StringIO(src).readline):
            if tok.type == _tk.COMMENT:
                continue
            出た.append(tok)
        return _tk.untokenize(出た)
    except (_tk.TokenError, IndentationError, SyntaxError):
        # 関数断片は単体で tokenize できないことがある。素朴に落とす
        落とした = [re.sub(r"(^|\s)#.*$", r"", ln) for ln in src.splitlines()]
        return chr(10).join(落とした)


# 印として使われる名前（属性代入で立てる形を拾うため）。
# `is_mock` 系も印。**作り物だと名乗っている**ので、消されたら偽 success になる
# （gate-verifier 22周目の M11: `post_publish_collector._generate_mock_data` から
#  `is_mock: True` を落とすと、乱数の CTR・維持率が実績として流れるのに緑だった）。
MARK_NAMES = frozenset(
    ("is_real", "data_source", "skip_reason", "scored", "quality_scored", "measured", "checked",
     "is_mock", "is_sample", "is_stub", "is_placeholder", "is_estimated", "estimated")
)


def _モジュール定数の印(tree: ast.AST) -> dict[str, list[str]]:
    """モジュール直下の `NAME = {...}` から、印にあたる項目を取り出す。

    `{**DATA_SOURCE, ...}` のように**印を定数で持って展開する**書き方があり、
    その定数は関数の外にある。関数の AST だけ見ていると、
    **`DATA_SOURCE` の中身を `is_real: True` へ反転しても関数側は何も変わらない**
    （gate-verifier 22周目の M2。固定値のチャンネル統計20経路が実測を名乗るのに緑だった）。
    """
    出た: dict[str, list[str]] = {}
    for node in getattr(tree, "body", []):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        名 = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if not 名:
            continue
        中身 = []
        for k, v in zip(node.value.keys, node.value.values):
            if isinstance(k, ast.Constant) and k.value in MARK_NAMES:
                中身.append(f"{k.value}={repr(v.value) if isinstance(v, ast.Constant) else '?'}")
        if 中身:
            出た[名[0]] = sorted(中身)
    return 出た


def _印の内訳(fn: ast.AST, モジュール印: dict[str, list[str]] | None = None) -> list[str]:
    """**印の名前と値**を並べる。`has_mark`（真偽）だけでは足りない。

    gate-verifier 22周目の M2 — `admin_channel_router` の固定値20経路に付いた
    `is_real: False` / `data_source: "unavailable"` を **`True` / `"measured"` へ
    反転**すると、作り物が実測を名乗るのに `--gate` は緑のままだった。
    印の**有無**しか見ていなかったため。値まで指紋に載せれば、反転も削除も落ちる。

    **ここで真偽の判定はしない。** 「どう名乗っているか」を記録するだけで、
    それが妥当かは台帳の adjudication（`status` と `reason`）が引き受ける。
    """
    def 値(node: ast.AST) -> str:
        if isinstance(node, ast.Constant):
            return repr(node.value)
        return "?"

    出た: list[str] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if k is None:
                    # `{**DATA_SOURCE, ...}` — 名前だけ記録する
                    名 = getattr(v, "id", None) or getattr(v, "attr", None)
                    if 名 and re.search(r"DATA_SOURCE|MARK|印", str(名), re.IGNORECASE):
                        出た.append(f"spread:{名}")
                        # **展開元の中身まで載せる。** 名前だけだと反転が見えない
                        for 項 in (モジュール印 or {}).get(str(名), []):
                            出た.append(f"{名}.{項}")
                elif isinstance(k, ast.Constant) and k.value in MARK_NAMES:
                    出た.append(f"{k.value}={値(v)}")
        elif isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg in MARK_NAMES:
                    出た.append(f"{kw.arg}={値(kw.value)}")
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            狙い = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in 狙い:
                名 = (t.attr if isinstance(t, ast.Attribute)
                      else t.id if isinstance(t, ast.Name) else None)
                if 名 in MARK_NAMES and node.value is not None:
                    出た.append(f"{名}={値(node.value)}")
    return sorted(出た)


def _印を属性で立てている(fn: ast.AST) -> bool:
    """`report.scored = False` のように**属性代入で印を立てる**形を拾う。

    文字列としての `"scored"` は `to_dict()` 側にしか出ないことがあり、
    関数本文の字面だけ見ると「印なし」に見える
    （`quality_gate_agent.run_gate` が実際にそうだった）。
    """
    for node in ast.walk(fn):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            狙い = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in 狙い:
                名 = (t.attr if isinstance(t, ast.Attribute)
                      else t.id if isinstance(t, ast.Name) else None)
                if 名 in MARK_NAMES:
                    return True
    return False


def _印がある(本文: str, fn: ast.AST | None = None) -> bool:
    """出所の印を持つか。**コメントは数えない。**"""
    素 = _コメントを落とす(本文)
    if MARK_RE.search(素) or SPREAD_MARK_RE.search(素):
        return True
    return bool(fn is not None and _印を属性で立てている(fn))

# **読まずに一括適用した定型文**を落とす（gate-verifier 22周目の指摘 C-3）。
#
# 対象外238件のうち76件が、掃引スクリプトの生成文1種類で除外されていた。
# 実査するとその文が事実と食い違う site が複数あった（`nhk_quality_scorer._score_cuts`
# は `AxisScore(score=100.0)` を返す品質スコア関数そのものだった）。
#
# **文言では判定しない。** 「数字を作らない」は、表示関数のように本当にそうである
# site では正しい理由になる。禁じるべきは*言い回し*ではなく
# **危険形を持つ site に同じ文を配って回ること**なので、次の2つで見る:
#
#   1. あの生成文そのもの（「同ファイルの所見」を含む形）
#   2. 危険形を持つ対象外 site で、**同じ理由が閾値を超えて使い回されている**こと
#
# 2 があるので、新しい定型文を作っても同じところで落ちる。
GENERATED_REASON_RE = re.compile(r"同ファイルの所見|と判断された（同ファイル")

# 危険形を持つ対象外 site が、同じ理由を何件まで共有してよいか。
# 凍結済みモジュールのように**正当に共有できる根拠**はあるので 0 にはしない。
SHARED_REASON_LIMIT = 5

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


def _束縛された名前(fn: ast.AST) -> frozenset[str]:
    """その関数の中で**値が決まる**名前（引数・代入・import・内側の定義・except の別名）。

    ここに無い `Name` は関数の外から来る＝**呼び出しの入力に依存しない。**
    """
    出た: set[str] = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            出た.add(n.id)
        elif isinstance(n, ast.arg):
            出た.add(n.arg)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for al in n.names:
                出た.add((al.asname or al.name).split(".")[0])
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if n is not fn:
                出た.add(n.name)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            出た.add(n.name)
    return frozenset(出た)


def _成功を名乗る値(node: ast.AST, 束縛: frozenset[str]) -> bool:
    """**入力に依存せず、かつ成功を名乗りうる値**か。

    ## なぜ「数値リテラル」ではないのか

    2026-09-12 まで、ここは数値リテラルだけを見ていた（`_is_number`）。
    危険な形を**列挙する**設計だったので、列挙から漏れた書き方は素通りした。
    gate-verifier は21周目に「キーワード引数の数値」を、22周目に
    **文字列・真偽値・モジュール定数・定数への呼び出し**を突いてきた。
    22周目は条件文の第1例そのもの（`video_id="placeholder_video_id"`）を
    戻してもゲートが緑のままだった。

    列挙を続けるかぎり次の書き方が必ず残るので、**定義で閉じる**ことにした
    （2026-09-12 ユーザー承認・案A）。条件文は「偽の success を返さない」
    なので、危険なのは次の2つを同時に満たす値:

    1. **呼び出しの入力に依存しない** — 何を渡しても同じ値が出る
    2. **成功を名乗りうる** — `False` / `None` / `""` は「無い・分からない」を
       言っているので偽の success ではない。**`0` は除かない**
       （条件文が名指しする「常に 0.0 になる quality_score」がまさにこれ）
    """
    if isinstance(node, ast.Constant):
        v = node.value
        if v is None or v is False or v == "":
            return False
        return isinstance(v, (int, float, str, bool))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return _成功を名乗る値(node.operand, 束縛)
    if isinstance(node, ast.Name):
        # 外から来る名前＝モジュール定数（`_FALLBACK_SCORE` / `DEFAULT_CTR`）。
        # **マジックナンバーを定数に括り出すのはレビューが薦める形**なので、
        # ここを見ないと「直した」はずの既定値が名前に化けて戻ってくる
        return node.id not in 束縛
    if isinstance(node, ast.Attribute):
        根 = node
        while isinstance(根, ast.Attribute):
            根 = 根.value
        return isinstance(根, ast.Name) and 根.id not in 束縛
    if isinstance(node, ast.Call):
        # `float(62.5)` のような、定数だけを包んだ呼び出し
        return (
            bool(node.args)
            and not node.keywords
            and all(_成功を名乗る値(a, 束縛) for a in node.args)
        )
    return False


def _risk_kinds(fn: ast.AST) -> list[str]:
    """偽 success を生みうる形を数える。

    **行番号は入れない。** 入れると無関係な編集で台帳が毎回ずれる。
    見たいのは「どういう形が何個あるか」であって、それがどこにあるかではない。
    """
    束縛 = _束縛された名前(fn)

    def 名乗る(node: ast.AST) -> bool:
        return _成功を名乗る値(node, 束縛)

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
                    and 名乗る(value)
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
                if 名乗る(value) or (
                    isinstance(value, ast.Constant) and isinstance(value.value, str)
                ):
                    出た.append("or_default")
        # 6. 数値リテラルをそのまま返す（条件文の「常に 0.0 になる quality_score」）
        if isinstance(node, ast.Return) and node.value is not None and 名乗る(node.value):
            出た.append("const_return")
        # 7. **カテゴリ鍵のキーワード引数に数値リテラル**（`quality_score=0.85`）。
        #    これが無かったので、直したばかりの `generation_engine` の 0.85 を
        #    戻してもゲートが素通りした（gate-verifier 21周目の指摘）
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg and RISK_KEY_RE.match(kw.arg) and 名乗る(kw.value):
                    出た.append(f"const_kwarg:{kw.arg.lower()}")
        # 8. **カテゴリ鍵への数値リテラル代入**（`result.quality_score = 0.85` /
        #    `score = 50.0`）。永続化の直前でこの形を取ることが多い
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            狙い = node.targets if isinstance(node, ast.Assign) else [node.target]
            値 = node.value
            if 値 is not None and 名乗る(値):
                for t in 狙い:
                    名 = (t.attr if isinstance(t, ast.Attribute)
                          else t.id if isinstance(t, ast.Name) else None)
                    if 名 and RISK_KEY_RE.match(名):
                        出た.append(f"const_assign:{名.lower()}")
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
        モジュール印 = _モジュール定数の印(tree)
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
                    "has_mark": _印がある(本文, node),
                    "marks": _印の内訳(node, モジュール印),
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
        # **理由が指紋と矛盾していたら落とす**（gate-verifier 22周目の指摘 C-3）。
        # 対象外238件のうち76件が「この関数は4カテゴリの数字・判定を作らない」という
        # 生成文1種類で除外されていた。危険形を持つ関数にこの文が付いていると
        # **自分で書いた指紋が自分の理由を否定している。**
        # 実査した例: `nhk_quality_scorer._score_cuts` は `AxisScore(score=100.0)` を
        # 返す品質スコア関数そのものなのに、この文で対象外になっていた。
        # 長さしか見ていなかったので CI で落ちなかった。
        if (status == "out_of_scope" and s.get("fingerprint")
                and GENERATED_REASON_RE.search(str(s.get("reason", "")))):
            出た.append(
                f"{rid}: 危険形 {len(s['fingerprint'])} 件を持つのに、掃引スクリプトの"
                f"生成文で対象外にしています。実物を読んだ個別の理由を書いてください"
                f"（指紋: {s['fingerprint']}）"
            )
        if s.get("category") not in CATEGORIES and status != "out_of_scope":
            出た.append(f"{rid}: category は {' / '.join(CATEGORIES)} のいずれか")
        if rid in 見た:
            出た.append(f"{rid}: id が重複しています")
        見た.add(rid)

    # **危険形を持つ対象外 site で、同じ理由が使い回されていないか。**
    # 生成文を1種類禁じるだけでは、次の定型文が作られたときに同じ穴が開く。
    使い回し = Counter(
        str(s.get("reason", "")) for s in sites
        if s.get("status") == "out_of_scope" and s.get("fingerprint")
    )
    for 理由, 件数 in 使い回し.items():
        if 件数 > SHARED_REASON_LIMIT:
            出た.append(
                f"危険形を持つ対象外 site {件数} 件が同じ理由を使い回しています"
                f"（上限 {SHARED_REASON_LIMIT}）: {理由[:70]}…"
            )
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

        # 5. **印の名乗り方が変わった。** 有無だけでは足りない
        #    （gate-verifier 22周目 M2: `is_real: False` を `True` に反転しても緑だった）
        台帳印 = sorted(s.get("marks") or [])
        現物印 = sorted(c.get("marks") or [])
        if 台帳印 != 現物印:
            違反.append(
                f"印の名乗り方が変わったので再確認が要ります: {sid}"
                f" / 台帳: {台帳印 or '(なし)'} → いま: {現物印 or '(なし)'}"
            )

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
