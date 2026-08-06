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
    # None = **静的走査では原理的に判定できないと結論した**主張。
    # 空タプル（未実装）とは別物で、こちらは実装しても埋まらない。
    # 該当項目は PASS に逃がさず、理由つきで FAIL にする（P3 C-3）。
    "element_count": None,      # 実行時に何件描画されるかはソースに書かれていない
    "idempotency": None,        # 2回呼んで同じかは実行しないと分からない
    "runtime_behavior": None,   # 特定の入力で 200 が返るかは実行しないと分からない
    "spec_incomplete": None,    # 何を照合すべきか仕様が決まっていない
}

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
    declared = tuple(k for k in ("testid", "endpoint", "response_field",
                                 "storage_key", "value_literals", "request_field")
                     if item.get(k))
    common = {
        "item_id": item_id, "ux_story": story,
        "description": item.get("description", ""),
        "claim": claim, "declared": declared,
    }

    if not claim:
        return ClaimRow(**common, reason="no_claim")
    if claim not in CLAIM_METHODS:
        return ClaimRow(**common, reason="unknown_claim")
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
    args = parser.parse_args(argv)

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
