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
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .executor import L1Report

BASELINE_DIR = Path(__file__).parent / "snapshots"

# 「判定を厳しくしたから PASS が減った」と認めてよい**新しい**理由。
# これ以外の理由で PASS が減っていれば、それは実装の退行。
TIGHTENING_REASONS = ("field_not_found",)

# 前回すでに内容まで判定して PASS だった理由。ここから field_not_found に
# 落ちたのは「判定を厳しくした」ではなく**レスポンスからフィールドが消えた**。
# 新しい理由コードだけを見ていると、この2つが同じ顔で出てくる。
VERIFIED_PASS_REASONS = ("field_found",)

# 「レスポンス内容まで見て判定した」ことを示す理由コード。PASS でも FAIL でも、
# ここから外れたら判定の強さが落ちたということ。
CONTENT_JUDGED_REASONS = ("field_found", "field_not_found")


def _is_content_judged(reason: str | None) -> bool:
    return reason in CONTENT_JUDGED_REASONS


def baseline_path(persona: str) -> Path:
    return BASELINE_DIR / f"l1_{persona}_baseline.json"


def write_baseline(report: L1Report, path: Path,
                   tightenings: list | None = None) -> Path:
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
    }
    if tightenings:
        # 判定を厳しくして PASS が減った履歴。消すと「昔は緑だった」が
        # 見えなくなり、退行と区別が付かなくなる。
        payload["tightenings"] = tightenings
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
    kind: str  # "regressed" | "removed" | "weakened"
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
        lines.append(
            "\n  PASS だった項目が FAIL に戻っています。frontend から "
            "data-testid が消えたか、ストーリー側の testid が書き換わっています。"
            "意図した変更なら --update-baseline で締め直してください。"
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

        violations: list[L1Violation] = []
        improvements: list[str] = []

        for item_id, was in before.items():
            now = after.get(item_id)
            if now is None:
                violations.append(L1Violation("removed", item_id, was, "—"))
                continue
            if was == "PASS" and now != "PASS":
                violations.append(L1Violation("regressed", item_id, was, now))
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
            elif was != "PASS" and now == "PASS":
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
        if not result.valid:
            raise ValueError(
                "退行が残っているためベースラインを更新できません:\n"
                + "\n".join(f"  {v}" for v in result.violations)
            )
        return write_baseline(report, path,
                              (baseline or {}).get("tightenings"))

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
        return write_baseline(report, path, history)
