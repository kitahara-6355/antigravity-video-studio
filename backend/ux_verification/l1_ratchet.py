"""L1 判定結果のラチェット — 項目ごとの非退行を保証する。

集計値だけを見るラチェットは「1件 PASS が消えて別の1件が PASS になった」を
見逃す。PASS 数は変わらないのに、保証していたはずの UX が1つ失われている。
ここでは**項目ごと**にベースラインと突き合わせ、PASS だった項目が FAIL に
なることと、項目そのものが消えることを違反として扱う。

    python -m backend.ux_verification.executor --persona owner --ratchet
    python -m backend.ux_verification.executor --persona owner --update-baseline

ベースラインは `backend/ux_verification/snapshots/l1_{persona}_baseline.json`。
判定が静的走査で環境に依存しないため、fs-guard のベースラインと違って
手元の実行値をそのまま使ってよい。

## 何を固定するか（3層）

1. **verdict** — PASS だった項目が FAIL に戻らない
2. **判定理由** — 内容まで見て判定していた項目が、経路の実在だけの判定に
   戻らない（`weakened`）
3. **宣言内容** — 項目が「何を測ると言っているか」そのもの（`substituted`）

3層目が P3 C-4 で足りていなかった。1・2 は宣言の**削除**を捕まえるが、
**差し替え**を素通りさせる。`response_field` を `hook_score` → `success` の
ような**実在するが別のフィールド**に付け替えると、`field_not_found` の FAIL が
`field_found` の PASS になり、理由コードは強いままなので違反ゼロ・
**改善1件**として記録される。description は変わっていないので、その項目が
要求する内容だけが静かに緩む（gate-verifier 5回目の指摘）。

宣言を変えること自体は禁じない。**黙って変えられないようにする。**
`--redeclare "理由"` で理由と before/after を履歴に残して締め直す。

## 記録の不在は「変化なし」ではない

3層はどれもベースラインの記録との比較なので、**記録を消せば比較が消える。**
`items` / `reasons` / `declarations` のどれか1冊から1行消すだけで、その項目の
退行・弱化・差し替えがまとめて見えなくなる（`items` から消せば「新しい項目」に
化け、比較ループにすら入らない）。そこで**いま在る項目が3冊すべてにピンされて
いること**を不変条件にし、欠けていれば `unpinned` として落とす。

3冊すべてに無いもの（＝まだピンしていない新しい項目）だけは `unpinned_new` と
区別して `--update-baseline` で通す。一部の冊にだけ残っているのは記録を消した跡
なので、理由を書かせる。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .executor import L1Report

BASELINE_DIR = Path(__file__).parent / "snapshots"

# 「判定を厳しくしたから PASS が減った」と認めてよい**新しい**理由。
# これ以外の理由で PASS が減っていれば、それは実装の退行。
TIGHTENING_REASONS = (
    "field_not_found", "value_not_found", "request_field_not_found",
    "storage_key_not_found",
    # 「静的には判定できない」と結論した結果の FAIL。判定していないものを
    # PASS に逃がさない側の変更なので、厳格化として受け入れる。
    "unjudgeable",
)

# 前回すでに内容まで判定して PASS だった理由。ここから field_not_found に
# 落ちたのは「判定を厳しくした」ではなく**レスポンスからフィールドが消えた**。
# 新しい理由コードだけを見ていると、この2つが同じ顔で出てくる。
VERIFIED_PASS_REASONS = (
    "field_found", "value_found", "request_field_found", "storage_key_found",
)

# 「レスポンス内容まで見て判定した」ことを示す理由コード。PASS でも FAIL でも、
# ここから外れたら判定の強さが落ちたということ。
CONTENT_JUDGED_REASONS = (
    "field_found", "field_not_found",
    "value_found", "value_not_found",
    "request_field_found", "request_field_not_found",
    "storage_key_found", "storage_key_not_found",
    # 判定できないと結論した状態も「主張に向き合った」側。ここから
    # 経路の実在だけの found へ戻るのは、向き合うのをやめたということ。
    "unjudgeable",
)


def _is_content_judged(reason: str | None) -> bool:
    return reason in CONTENT_JUDGED_REASONS


def _render_declaration(declaration: dict | None) -> str:
    if not declaration:
        return "（宣言なし）"
    return " ".join(
        f"{k}={json.dumps(v, ensure_ascii=False)}" if not isinstance(v, str) else f"{k}={v}"
        for k, v in sorted(declaration.items())
    )


def baseline_path(persona: str) -> Path:
    return BASELINE_DIR / f"l1_{persona}_baseline.json"


def write_baseline(report: L1Report, path: Path,
                   tightenings: list | None = None,
                   redeclarations: list | None = None) -> Path:
    """判定を項目ごとに書き出す。

    タイムスタンプは入れない。毎回書き換わる欄があると、実質的な変化が
    差分に埋もれて読めなくなる。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "persona": report.persona,
        "layer": 1,
        "method": report.method,
        "total": report.total,
        "pass": report.pass_count,
        "fail": report.fail_count,
        "items": {r.item_id: r.verdict.value for r in report.results},
        # 判定理由も残す。PASS/FAIL だけでは「経路の実在で PASS」と
        # 「内容まで見て PASS」を区別できず、--tighten が内容の退行を
        # 厳格化として受理してしまう。
        "reasons": {r.item_id: r.reason for r in report.results},
        # 宣言内容も残す。理由コードは「何を測ったか」の**種類**しか持たず、
        # 「どれを測ったか」を持たない。差し替えはここでしか見えない。
        "declarations": {r.item_id: r.declaration for r in report.results},
    }
    if tightenings:
        # 判定を厳しくして PASS が減った履歴。消すと「昔は緑だった」が
        # 見えなくなり、退行と区別が付かなくなる。
        payload["tightenings"] = tightenings
    if redeclarations:
        # 宣言を差し替えた履歴。理由と before/after を残す。
        payload["redeclarations"] = redeclarations
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")
    return path


def load_baseline(path: Path) -> dict | None:
    path = Path(path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class L1Violation:
    kind: str  # "regressed" | "removed" | "weakened" | "substituted" | "unpinned"
    item_id: str
    before: str
    after: str

    def __str__(self) -> str:
        if self.kind == "removed":
            return f"[削除] {self.item_id}: {self.before} → 項目が存在しない"
        if self.kind == "weakened":
            return (
                f"[判定の弱化] {self.item_id}: {self.before} → {self.after}"
                "（レスポンス内容を見なくなった）"
            )
        if self.kind == "substituted":
            return (
                f"[宣言の差し替え] {self.item_id}: {self.before} → {self.after}"
                "（測る対象そのものが変わった）"
            )
        if self.kind == "unpinned":
            return (
                f"[固定されていない] {self.item_id}: {self.before}"
                "（ベースラインに記録が無く、変化を検出できない）"
            )
        if self.kind == "unpinned_new":
            return (
                f"[未ピン] {self.item_id}: ベースラインに無い新しい項目"
                "（--update-baseline でピンしてください）"
            )
        return f"[退行] {self.item_id}: {self.before} → {self.after}"


@dataclass
class L1RatchetResult:
    valid: bool
    violations: list[L1Violation] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    baseline_missing: bool = False
    before_pass: int = 0
    after_pass: int = 0

    def to_text(self) -> str:
        if self.baseline_missing:
            return (
                "🚫 ベースラインがありません。--update-baseline で作成してください"
                f"（現在 PASS {self.after_pass}件）。\n"
                "  ベースラインが無い状態を緑にすると、ファイルを消すだけで"
                "ラチェットを無効化できてしまうため失敗として扱います。"
            )
        head = (
            f"L1 ラチェット: PASS {self.before_pass} → {self.after_pass}"
            f"（改善 {len(self.improvements)} / 新規 {len(self.added)}）"
        )
        if self.valid:
            return f"✅ {head}"
        lines = [f"🚫 {head}", f"  {len(self.violations)}件の違反:"]
        lines += [f"    {v}" for v in self.violations]
        kinds = {v.kind for v in self.violations}
        if kinds - {"substituted", "unpinned", "unpinned_new"}:
            lines.append(
                "\n  PASS だった項目が FAIL に戻っています。frontend から "
                "data-testid が消えたか、ストーリー側の testid が書き換わっています。"
                "意図した変更なら --update-baseline で締め直してください。"
            )
        if kinds & {"substituted", "unpinned", "unpinned_new"}:
            lines.append(
                "\n  項目が**何を測ると宣言しているか**がベースラインと違います。"
                "verdict と理由コードは同じでも、要求している内容が変わっています。"
                "\n  意図した変更なら --redeclare \"理由\" で締め直してください"
                "（理由と before/after がベースラインに残ります）。"
            )
        return "\n".join(lines)


class L1Ratchet:
    """項目ごとの非退行を検証する。"""

    def check(self, report: L1Report, baseline: dict | None) -> L1RatchetResult:
        if baseline is None:
            return L1RatchetResult(
                valid=True, baseline_missing=True, after_pass=report.pass_count
            )

        before: dict[str, str] = baseline.get("items", {})
        after = {r.item_id: r.verdict.value for r in report.results}
        before_reasons: dict[str, str] = baseline.get("reasons") or {}
        after_reasons = {r.item_id: r.reason for r in report.results}
        before_decls: dict[str, dict] = baseline.get("declarations") or {}
        after_decls = {r.item_id: r.declaration for r in report.results}

        violations: list[L1Violation] = []
        improvements: list[str] = []

        # 3冊（items / reasons / declarations）と**現在の項目**が食い違っている
        # ものを先に洗い出す。記録が無いものは「変化なし」ではなく「分からない」。
        #
        # ここを項目単位で見るだけでは足りなかった。`items` から1行消すと、その
        # 項目は before に居なくなって `added` に落ち、下のループに一度も入らない。
        # PASS → FAIL の退行も宣言の差し替えも、まとめて緑で通る
        # （gate-verifier 6回目）。**現在ある項目が全部ピンされていること**を
        # 不変条件にして、3冊のどれから消しても違反になるようにする。
        pinned_books = (
            ("verdict がベースラインに無い", before),
            ("前回の判定理由がベースラインに無い", before_reasons),
            ("前回の宣言がベースラインに無い", before_decls),
        )
        unpinned_ids: set[str] = set()
        for item_id in sorted(set(after) | set(before) | set(before_reasons)
                              | set(before_decls)):
            if item_id not in after and item_id in before:
                continue  # 項目そのものの消滅は下のループが removed として出す
            missing = [label for label, book in pinned_books if item_id not in book]
            if not missing:
                continue
            unpinned_ids.add(item_id)
            # 3冊すべてに無ければ、単に**まだピンしていない新しい項目**。
            # 一部の冊にだけ残っているなら、記録を消した跡。前者は
            # --update-baseline でピンしてよく、後者は理由を書かせる。
            kind = "unpinned_new" if len(missing) == len(pinned_books) else "unpinned"
            violations.append(L1Violation(kind, item_id, "・".join(missing), "—"))

        for item_id, was in before.items():
            now = after.get(item_id)
            if now is None:
                violations.append(L1Violation("removed", item_id, was, "—"))
                continue

            # unpinned でも**ここで打ち切らない。** 記録の欠落を退行の目隠しに
            # 使えてしまう（`declarations` から1行消すと unpinned だけが出て
            # 退行が報告されず、--redeclare がそれを受理する）。
            if was == "PASS" and now != "PASS":
                violations.append(L1Violation("regressed", item_id, was, now))
                continue

            # 理由コードは「何を測ったか」の**種類**しか持たない。どれを測ったかは
            # 宣言にしかないので、宣言が変われば同じ理由コードのまま別物を
            # 測っている。FAIL → PASS になっていても、それは実装が良くなった
            # 証拠ではなく、要求を取り替えた結果でしかない。
            if (item_id in before_decls
                    and before_decls[item_id] != after_decls.get(item_id)):
                violations.append(L1Violation(
                    "substituted", item_id,
                    _render_declaration(before_decls[item_id]),
                    _render_declaration(after_decls.get(item_id)),
                ))
                continue

            # verdict だけを見ていると、**判定の強さ**が落ちたことに気づけない。
            # 項目から response_field を消せば field_found → found（PASS のまま）、
            # field_not_found → found（FAIL → PASS で「改善」に見える）。
            # どちらもラチェットは緑で、内容の判定が丸ごと巻き戻る。
            was_content = _is_content_judged(before_reasons.get(item_id))
            if was_content and not _is_content_judged(after_reasons.get(item_id)):
                violations.append(L1Violation(
                    "weakened", item_id,
                    before_reasons.get(item_id, "?"), after_reasons.get(item_id, "?"),
                ))
            elif was != "PASS" and now == "PASS" and item_id not in unpinned_ids:
                improvements.append(item_id)

        added = [i for i in after if i not in before]

        return L1RatchetResult(
            valid=not violations,
            violations=violations,
            improvements=improvements,
            added=added,
            before_pass=int(baseline.get("pass", 0)),
            after_pass=report.pass_count,
        )

    def update(self, report: L1Report, path: Path) -> Path:
        """ベースラインを現在値で締め直す。退行が残っていれば拒否する。

        退行したまま緩めれば、退行が無かったことになる。
        """
        baseline = load_baseline(path)
        result = self.check(report, baseline)
        # 未ピン（新しく足した項目、または3冊のどれかから記録が消えたもの）だけは
        # ここで締め直せる。それ以外が1件でも混じっていたら書かない——退行を
        # 未ピンに紛れ込ませて通せるようにすると、締め直しが抜け道になる。
        blocking = [v for v in result.violations if v.kind != "unpinned_new"]
        if blocking:
            raise ValueError(
                "退行が残っているためベースラインを更新できません:\n"
                + "\n".join(f"  {v}" for v in blocking)
            )
        return write_baseline(report, path,
                              (baseline or {}).get("tightenings"),
                              (baseline or {}).get("redeclarations"))

    def redeclare(self, report: L1Report, path: Path, reason: str) -> Path:
        """**宣言の差し替え**だけを受け入れて締め直す。

        宣言を変えること自体は正当な作業（誤った `response_field` を直す、
        判定手段を足して `claim` を強い側へ移す）。禁じるのは**黙って**
        変えることのほう。理由を必須にし、before/after を履歴に残す。

        受け入れるのは `substituted` と `unpinned` だけ。verdict の退行や
        判定の弱化が混じっていたら拒否する。宣言の差し替えに紛れ込ませて
        通せるようにすると、履歴を残す意味が無くなる。

        **これは「差し替えを禁止する」機能ではない。** C-4 が求めているのは
        検出であって禁止ではないので、通した記録が永久に残るところまでを
        保証する。FAIL → PASS を買う差し替えも、理由と before/after が
        ベースラインの差分に出る。
        """
        if not reason.strip():
            raise ValueError(
                "差し替えの理由は必須です。何を測る対象に変えたのかを書いてください")

        baseline = load_baseline(path)
        result = self.check(report, baseline)
        before_decls = (baseline or {}).get("declarations") or {}

        illegitimate = [v for v in result.violations
                        if v.kind not in ("substituted", "unpinned", "unpinned_new")]
        if illegitimate:
            raise ValueError(
                "宣言の差し替えでは説明できない違反が混じっています:\n"
                + "\n".join(f"  {v}" for v in illegitimate)
                + "\n  退行・判定の弱化は、宣言の差し替えとは分けて扱ってください。"
            )

        after_decls = {r.item_id: r.declaration for r in report.results}
        changed = [v.item_id for v in result.violations]
        history = list((baseline or {}).get("redeclarations") or [])
        history.append({
            "reason": reason.strip(),
            "items": {
                item_id: {
                    "before": before_decls.get(item_id),
                    "after": after_decls.get(item_id),
                }
                for item_id in sorted(changed)
            },
        })
        return write_baseline(report, path,
                              (baseline or {}).get("tightenings"), history)

    def tighten(self, report: L1Report, path: Path, reason: str,
                allowed_reasons: tuple = TIGHTENING_REASONS) -> Path:
        """**判定を厳しくしたことによる** PASS の減少だけを受け入れて締め直す。

        ラチェットは「実装が退行していないこと」を守る道具で、
        「測り方を厳しくしてはいけない」という意味ではない。だが両者は
        どちらも PASS の減少として現れるので、機械的に区別できないと
        「厳しくした」と言えば何でも通せてしまう。

        そこで2つの側から絞る。

        1. **新しい判定理由**が厳格化に由来するものだけ。`not_found`（実体が
           消えた）や `unregistered`（登録が外れた）や項目の削除は拒否する
        2. **前回の判定理由**が「内容まで見て PASS」でないこと。
           `field_found` → `field_not_found` は厳格化ではなく、
           **レスポンスからフィールドが消えた**——まさに守りたかった退行そのもの。
           新しい理由コードだけを見ていると、この2つが同じ顔で出てくる

        理由は必須で、ベースラインに履歴として残す。
        """
        if not reason.strip():
            raise ValueError(
                "厳格化の理由は必須です。何を厳しくしたのかを書いてください")

        baseline = load_baseline(path)
        result = self.check(report, baseline)
        reasons = {r.item_id: r.reason for r in report.results}
        before_reasons = (baseline or {}).get("reasons")

        if result.violations and before_reasons is None:
            raise ValueError(
                "ベースラインに判定理由（reasons）が記録されていないため、"
                "厳格化と退行を区別できません。\n"
                "  先に --update-baseline で理由付きのベースラインを作り直して"
                "ください。区別できないものを通すと、--tighten が"
                "何でも受理する抜け道になります。"
            )

        illegitimate = []
        for v in result.violations:
            if v.kind != "regressed" or reasons.get(v.item_id) not in allowed_reasons:
                illegitimate.append((v, reasons.get(v.item_id, "不明")))
            elif v.item_id not in (before_reasons or {}):
                # 辞書ごとの不在だけを見ていると、1項目分の理由を消すだけで
                # ここを素通りできる。項目単位でも「分からない」は通さない。
                illegitimate.append((v, "前回の判定理由がベースラインに無い"))
            elif before_reasons[v.item_id] in VERIFIED_PASS_REASONS:
                illegitimate.append((v, "前回は内容まで見て PASS だった"))
        if illegitimate:
            raise ValueError(
                "厳格化では説明できない退行が混じっています:\n"
                + "\n".join(f"  {v}（{why}）" for v, why in illegitimate)
                + "\n  実装の退行と、判定の厳格化は分けて扱ってください。"
            )

        history = list((baseline or {}).get("tightenings") or [])
        history.append({
            "reason": reason.strip(),
            "items": sorted(v.item_id for v in result.violations),
        })
        return write_baseline(report, path, history,
                              (baseline or {}).get("redeclarations"))
