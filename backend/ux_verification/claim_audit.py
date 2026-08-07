"""主張と判定手段の対応を突き合わせる（P3 C-1）。

P2 では「充足率 90% 以上」を終了条件にしたが、**数え方に依存する値**だったため
検証のたびに数字が動いた。gate-verifier は3回とも「走査範囲の外に同型の偽 PASS が
残っている」と指摘し、そのたびに新しいポケットが出てきた:

    1回目: 37件が未判定 → 68.0%
    2回目:  6件が未判定 → 89.34%
    3回目:  7件が未判定 → 86.07%

**同じ実装のまま、数え方だけで 68% にも 89% にもなる。**
原因は「どの項目が何を主張しているか」を人間が description を読んで数えていたこと。
3回とも数え漏れた。

そこで主張の種類を項目自身に `claim` として書かせ、**宣言された判定手段で
その主張を判定できるか**を機械的に突き合わせる。

    python -m backend.ux_verification.claim_audit --persona owner

## 判定できるかの規則

`CLAIM_METHODS` が「この主張を判定するには何の宣言が要るか」を持つ。値は3通り:

- **タプル** — その宣言があれば判定できる
- **空タプル** — 判定手段が**まだ無い**（実装すれば埋まる）
- **`None`** — 静的走査では**原理的に判定できないと結論した**

最後の2つを混ぜないのが肝。同じ扱いにすると、実装をサボったものと結論を出した
ものが区別できず、「あと何を作れば終わるのか」が分からなくなる。

`None` の項目は対応が取れているとみなすが、**PASS には逃がさない。**
executor が `unjudgeable` の FAIL として出す。判定していないものを緑にするのが、
P2 で3回潰した偽 PASS そのものだから。

対応が取れていない理由は4種類:

- `no_claim`      — `claim` が書かれていない（**新しい項目の取りこぼしはここで出る**）
- `unknown_claim` — 知らない種類
- `no_method`     — その主張を判定する手段が実装されていない
- `not_declared`  — 手段はあるが、項目が必要な宣言を持っていない

`not_declared` が P2 で3回とも見落とした型。`O1-L1-01`「動画一覧APIが正常応答を
返す」は経路の主張なのに `testid` しか持たず、DOM 要素の実在だけで PASS していた。
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# 主張の種類 → その主張を判定するために項目が宣言すべきもの。
# 空タプル = 判定手段がまだ無い。
CLAIM_METHODS: dict[str, tuple[str, ...] | None] = {
    "dom_exists": ("testid",),
    "route_exists": ("endpoint",),
    "response_field": ("endpoint", "response_field"),
    "storage_key": ("storage_key",),
    "value_constraint": ("endpoint", "value_literals"),
    "request_contract": ("endpoint", "request_field"),
    # 値そのものの主張（`success=true`）。フィールドの実在では測れない。
    "response_value": ("endpoint", "response_field", "expected_value"),
    # 集合の主張（「対応拡張子**のみ**」）。値が現れることでは「のみ」を測れない。
    "value_exclusive": ("endpoint", "value_set"),
    # None = **静的走査では原理的に判定できないと結論した**主張。
    # 空タプル（未実装）とは別物で、こちらは実装しても埋まらない。
    # 該当項目は PASS に逃がさず、理由つきで FAIL にする（P3 C-3）。
    "element_count": None,
    "idempotency": None,
    "parameter_coverage": None,
    "spec_incomplete": None,
    # 状態遷移（「更新される」）。前後を比べる必要があり、1回の静的走査では
    # 「返る」との区別が付かない。ユーザー判断（2026-08-07）で FAIL とした。
    "state_transition": None,
}

# 各 claim が**何を確かめ、何を確かめないか**。
# ここを書かずに分類だけしていると、「正常応答を返す」を経路の実在で PASS に
# しているのが妥当なのか読み手に分からない。判定の意味を言葉で固定する。
CLAIM_SEMANTICS: dict[str, tuple[str, str]] = {
    "dom_exists": (
        "その data-testid が、エントリから到達できるソースに書かれている",
        "実行時に本当に描画されるか（条件分岐で一度も出ない要素も PASS になる）",
    ),
    "route_exists": (
        "そのエンドポイントが定義され、アプリに include_router されている",
        "**呼んで 200 が返るか。** ハンドラが例外を投げるかは静的には分からない。"
        "L1 が保証するのは『呼び先が存在し、404 にはならない』ところまで",
    ),
    "response_field": (
        "宣言されたフィールドが、ハンドラの返り値（呼び先を一段展開）に現れる",
        "その値が何であるか。空配列でもフィールドが在れば PASS になる",
    ),
    "storage_key": (
        "その localStorage キーの読み書きが、到達できるソースにある",
        "実行時に実際に書かれるか",
    ),
    "value_constraint": (
        "宣言された値が、エンドポイントの実装（参照するモジュール変数を含む）に現れる",
        "実行時にその値だけが返るか（「〜のみ」の『のみ』は確かめていない）",
    ),
    "request_contract": (
        "そのフィールドがリクエストモデルに定義されている",
        "その値域が受理されるか",
    ),
    "response_value": (
        "宣言されたフィールドに、宣言された値**以外のリテラルを返す経路が"
        "ハンドラのソースに無い**",
        "実行時に必ずその値になるか。ソースに無いだけで、動的に組み立てた値までは"
        "追えない",
    ),
    "value_exclusive": (
        "宣言した集合と**完全に一致する**リスト・リテラルが実装にある"
        "（余分な要素が無い）",
        "実行時にその集合だけが返るか。リストを作ったあとで足す経路は追えない",
    ),
    "element_count": (
        "（判定手段なし）",
        "**描画される件数。** 既定データの件数なら静的に数えられるが、"
        "主張は『表示される』で、実際の描画件数は実行時のデータ次第。"
        "既定データで代用するのは別の主張への置き換えになる",
    ),
    "idempotency": (
        "（判定手段なし）",
        "2回呼んで同じ結果になるか。実行しないと分からない",
    ),
    "parameter_coverage": (
        "（判定手段なし）",
        "**特定の入力値の集合が受理されるか。** 型が int としか書かれておらず、"
        "受理する値の集合が実装のどこにも宣言されていない場合、"
        "静的走査には照合する相手が無い",
    ),
    "spec_incomplete": (
        "（判定手段なし）",
        "何を照合すべきかが仕様に書かれていない。"
        "推測で照合先を書けば判定は出るが、それは実装ではなく判定の捏造",
    ),
    "state_transition": (
        "（判定手段なし）",
        "**呼ぶ前と後で値が変わったか。** 1回の静的走査では『返る』としか言えず、"
        "『更新される』と区別が付かない。実行層（L2）が要る",
    ),
}

# 主張の**述語**の語彙。ここに載っていない書き方の description は通さない（P3 C-3）。
#
# claim は人が貼るラベルなので、弱いラベルを選べば主張の一部を捨てたまま PASS に
# できた。`description: "success=true"` に `claim: response_field`（＝値は見ないと
# CLAIM_SEMANTICS が自ら明記している）を貼れば、主張の半分が消えても緑になる
# （gate-verifier 5回目）。**ラベルの妥当性を機械で見る層がもう1枚要る。**
#
# 日本語を解析するのではなく、**述語の書き方そのものを閉じた集合にする。**
# ユーザー判断（2026-08-07）: マーカー検出では、辞書に無い語で強い主張を書くと
# 素通りする（実際、当初のパターン表は「4カテゴリ」を拾えなかった）。
# 未登録の書き方は `unparsed` として落とし、**辞書に足して判定手段を決めるか、
# 登録済みの語で書き直すか**を選ばせる。
#
# 並び順が意味を持つ。**強い述語を先に置く**（「〜のみ含まれる」は「〜含まれる」
# にも当たるので、先に「のみ」で捕まえないと弱いほうに落ちる）。
DESCRIPTION_GRAMMAR: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    # --- 強い述語（値・集合・件数・遷移）---
    ("値の指定", r"^[\w_.]+\s*[=＝]\s*\S+$", ("response_value",)),
    ("〜のみ", r"(のみ|だけ)", ("value_exclusive",)),
    ("件数", r"\d+\s*件(以上|以下|ちょうど)?", ("element_count",)),
    ("プリセット網羅", r"\d+\s*種.*プリセット|プリセット.*\d+\s*種", ("parameter_coverage",)),
    ("状態遷移", r"(更新される|変わる|反映される|切り替わる|増える|減る)", ("state_transition",)),
    ("可能である", r"(が可能|できる)", ("idempotency",)),
    # --- 列挙の実在（「4カテゴリ(a/b/c/d)が存在する」）---
    # 個数を書いていても列挙が並んでいれば「その列挙が在ること」の主張と読む。
    # ユーザー判断（2026-08-07）: 「のみ」と書いていない以上、排他性は主張していない。
    ("列挙の実在", r"^\d+\s*(カテゴリ|種類)\s*[（(].+[)）]が存在する$", ("value_constraint",)),
    # --- 経路とレスポンス ---
    ("経路＋フィールド", r"正常応答し.+(が返る|を返す|が含まれる|含む)$",
     ("response_field",)),
    ("経路のみ", r"^.*?正常応答(を返す|する)?$", ("route_exists",)),
    ("リクエスト契約", r"(を受け付ける|を受け取る)$", ("request_contract",)),
    ("フィールドの実在",
     r"(を返す|が返る|が含まれる|含む|フィールドが存在する?|オブジェクト含む|配列含む)$",
     ("response_field",)),
    # 「localStorage に〜が存在する」は DOM の主張ではない。要素の実在より先に置く。
    ("保存キーの実在", r"(localStorage|sessionStorage).*(が存在する?|存在)$",
     ("storage_key",)),
    # 「〜が存在する」は DOM の要素にも、レスポンスのフィールドにも使われている。
    # どちらを測るかは claim が決めるので、両方を許す。
    ("要素の実在", r"(が存在する?|存在)$", ("dom_exists", "response_field")),
)


def parse_description(description: str) -> tuple[str, tuple[str, ...]] | None:
    """description の述語を語彙に照らし、要求される claim を返す。

    返り値は (述語の名前, 許される claim の並び)。語彙に無ければ `None`。
    """
    text = (description or "").strip()
    if not text:
        return None
    for name, pattern, claims in DESCRIPTION_GRAMMAR:
        if re.search(pattern, text):
            return name, claims
    return None


# 項目が「何を照合先にするか」を宣言しているキー。**CLAIM_METHODS から導く。**
# ここを手で並べると、新しい判定手段を足したときに片方だけ増えて、
# 増えたほうがラチェットの外に落ちる（走査範囲の外のポケットの型）。
DECLARATION_KEYS: tuple[str, ...] = ("claim",) + tuple(sorted(
    {key for required in CLAIM_METHODS.values() if required for key in required}
))


def declaration_of(item: dict) -> dict:
    """項目の**宣言内容**を取り出す。「何を測ると言っているか」そのもの。

    ラチェットがこれを固定する。verdict と理由コードだけを記録していた頃は、
    `response_field` を `hook_score` → `success` のような**実在するが別の
    フィールド**に差し替えるだけで FAIL が PASS になり、違反ゼロ・改善1件として
    記録された（P3 C-4 / gate-verifier 5回目）。description は変わっていないので、
    項目が要求する内容だけが静かに緩む。
    """
    return {k: item[k] for k in DECLARATION_KEYS if item.get(k)}


# 判定手段がまだ無い主張（実装すれば埋まる）。ここが空でないと C-3 を満たせない。
UNSUPPORTED_CLAIMS = tuple(k for k, v in CLAIM_METHODS.items() if v == ())

# 静的には判定できないと結論した主張。FAIL として出すことで対応が取れたとみなす。
UNJUDGEABLE_CLAIMS = tuple(k for k, v in CLAIM_METHODS.items() if v is None)


@dataclass(frozen=True)
class ClaimRow:
    item_id: str
    ux_story: str
    description: str
    claim: str
    declared: tuple[str, ...]
    reason: str  # "" = 対応が取れている

    @property
    def matched(self) -> bool:
        return not self.reason

    def as_text(self) -> str:
        why = {
            "no_claim": "claim が書かれていない",
            "unknown_claim": f"知らない主張の種類（{self.claim}）",
            "no_method": f"{self.claim} を判定する手段が無い",
            "not_declared": (
                f"{self.claim} を判定するには "
                f"{'・'.join(CLAIM_METHODS.get(self.claim) or ())} が要るが、"
                f"持っているのは {'・'.join(self.declared) or 'なし'}"
            ),
            "unparsed": (
                "description の述語が語彙に無い。"
                "DESCRIPTION_GRAMMAR に足して判定手段を決めるか、"
                "登録済みの書き方に直す"
            ),
            "claim_too_weak": (
                f"description の述語『{(parse_description(self.description) or ('?', ()))[0]}』は "
                f"{'・'.join((parse_description(self.description) or ('', ()))[1])} を要求するが、"
                f"貼られているのは {self.claim}"
                f"（{CLAIM_SEMANTICS.get(self.claim, ('', '?'))[1]}）"
            ),
        }.get(self.reason, self.reason)
        return f"{self.item_id:<11} {self.description}\n      → {why}"


@dataclass
class ClaimAuditReport:
    persona: str
    rows: list[ClaimRow] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.rows)

    @property
    def mismatched(self) -> list[ClaimRow]:
        return [r for r in self.rows if not r.matched]

    def by_claim(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.rows:
            out[r.claim or "(未記入)"] = out.get(r.claim or "(未記入)", 0) + 1
        return out

    def keys(self) -> list[str]:
        return sorted(r.item_id for r in self.mismatched)


def audit(stories_dir: Path, persona: str = "owner") -> ClaimAuditReport:
    """**判定側と同じ列挙**で走査する。

    別々に列挙していた頃は監査の範囲のほうが狭く、その隙間に置いた claim 無しの
    項目が実行系では PASS になるのに監査に現れなかった。範囲がずれていると、
    「対応ゼロ」は「監査が見ている範囲では対応ゼロ」という意味しか持たない。
    """
    from .executor import iter_l1_items

    report = ClaimAuditReport(persona=persona)
    prefix = "O" if persona == "owner" else "A"
    for ux_id, item in iter_l1_items(stories_dir, prefix):
        item_id = item.get("id") or item.get("item_id") or ""
        report.rows.append(_judge(item_id, ux_id, item))
    report.rows.sort(key=_sort_key)
    return report


def _judge(item_id: str, story: str, item: dict) -> ClaimRow:
    claim = (item.get("claim") or "").strip()
    declared = tuple(k for k in DECLARATION_KEYS
                     if k != "claim" and item.get(k))
    common = {
        "item_id": item_id, "ux_story": story,
        "description": item.get("description", ""),
        "claim": claim, "declared": declared,
    }

    if not claim:
        return ClaimRow(**common, reason="no_claim")
    if claim not in CLAIM_METHODS:
        return ClaimRow(**common, reason="unknown_claim")

    # **description の述語と claim の対応。** ここが無かったので、弱いラベルを
    # 貼るだけで主張の一部を捨てたまま PASS にできた（gate-verifier 5回目）。
    parsed = parse_description(common["description"])
    if parsed is None:
        return ClaimRow(**common, reason="unparsed")
    if CLAIM_METHODS[claim] == ():
        # 判定手段がそもそも無いなら、ラベルの当否より先にそれを言う。
        return ClaimRow(**common, reason="no_method")
    _, allowed = parsed
    # 「そもそも測れない」は述語の種類とは別の軸。**どの述語にも貼れる。**
    # ユーザー判断（2026-08-07）: 必ず FAIL に落ちるので偽の緑は作れず、
    # 付け替えはラチェットの substituted が捕まえて --redeclare の理由が残る。
    # PASS だった項目を落とすには --tighten も要る。
    if claim not in allowed and claim not in UNJUDGEABLE_CLAIMS:
        return ClaimRow(**common, reason="claim_too_weak")

    required = CLAIM_METHODS[claim]
    if required is None:
        # 判定できないと**結論した**もの。結論も対応のうちなので mismatch にしない。
        # ただし PASS には逃がさず FAIL として出すことが前提（executor 側）。
        return ClaimRow(**common, reason="")
    if not required:
        return ClaimRow(**common, reason="no_method")
    if any(r not in declared for r in required):
        return ClaimRow(**common, reason="not_declared")
    return ClaimRow(**common, reason="")



def _sort_key(row: ClaimRow):
    try:
        head, tail = row.item_id.split("-L1-")
        return (int(head[1:]), int(tail))
    except (ValueError, IndexError):
        return (999, 0)


def _project_root() -> Path:
    try:
        from backend.path_resolver import project_root

        return Path(project_root())
    except (ImportError, OSError, ValueError):
        return Path(__file__).resolve().parents[2]


def for_repo(persona: str = "owner") -> ClaimAuditReport:
    return audit(_project_root() / "backend" / "ux_verification" / "stories", persona)


# --- CLI ---------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="検証項目の主張と判定手段の対応を突き合わせる",
    )
    parser.add_argument("--persona", default="owner", choices=["owner", "admin"])
    parser.add_argument("--json", action="store_true",
                        help="対応が取れていない項目の ID だけを JSON で出す")
    parser.add_argument("--gate", action="store_true",
                        help="対応が取れていない項目が1件でもあれば exit 1")
    parser.add_argument("--semantics", action="store_true",
                        help="各 claim が何を確かめ、何を確かめないかを出す")
    args = parser.parse_args(argv)

    if args.semantics:
        for claim in CLAIM_METHODS:
            verifies, does_not = CLAIM_SEMANTICS[claim]
            mark = "⛔" if claim in UNJUDGEABLE_CLAIMS else "  "
            print(f"{mark} {claim}")
            print(f"     確かめる  : {verifies}")
            print(f"     確かめない: {does_not}\n")
        return 0

    report = for_repo(args.persona)

    if args.json:
        print(json.dumps(report.keys(), ensure_ascii=False, indent=2))
        return 0

    print(f"主張と判定手段の対応 — persona={report.persona} / L1 {report.total} 項目")
    for claim, count in sorted(report.by_claim().items(), key=lambda kv: -kv[1]):
        if claim in UNSUPPORTED_CLAIMS:
            mark = "  ⚠️"          # 判定手段が未実装
        elif claim in UNJUDGEABLE_CLAIMS:
            mark = "  ⛔"          # 静的には判定できないと結論した
        else:
            mark = "    "
        print(f"{mark} {claim:<18}{count:>4} 件")

    bad = report.mismatched
    print(f"\n  対応が取れていない項目: {len(bad)} 件")
    for row in bad:
        print(f"    {row.as_text()}")
    if not bad:
        print("    なし。すべての主張が、それを判定できる手段で測られている。")

    if args.gate:
        # 走査が成立していないことを 0 件として通さない。項目が1つも取れて
        # いなければ、ストーリーを見失っただけで緑になってしまう。
        if report.total == 0:
            print("\n🚫 検証項目を1件も読み取れませんでした。"
                  "走査できなかったことを『対応ゼロ』として通しません。")
            return 1
        if bad:
            print("\n🚫 主張と判定手段の対応が取れていない項目があります。"
                  "判定していないものを PASS にしないでください。")
            return 1
        print(f"\n✅ {report.total} 項目すべてで対応が取れています。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
