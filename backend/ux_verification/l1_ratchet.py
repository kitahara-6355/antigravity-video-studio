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


def baseline_path(persona: str) -> Path:
    return BASELINE_DIR / f"l1_{persona}_baseline.json"


def write_baseline(report: L1Report, path: Path) -> Path:
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
    }
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
    kind: str  # "regressed" | "removed"
    item_id: str
    before: str
    after: str

    def __str__(self) -> str:
        if self.kind == "removed":
            return f"[削除] {self.item_id}: {self.before} → 項目が存在しない"
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
                "ベースラインがありません。--update-baseline で作成してください"
                f"（現在 PASS {self.after_pass}件）。"
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

        violations: list[L1Violation] = []
        improvements: list[str] = []

        for item_id, was in before.items():
            now = after.get(item_id)
            if now is None:
                violations.append(L1Violation("removed", item_id, was, "—"))
            elif was == "PASS" and now != "PASS":
                violations.append(L1Violation("regressed", item_id, was, now))
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
        result = self.check(report, load_baseline(path))
        if not result.valid:
            raise ValueError(
                "退行が残っているためベースラインを更新できません:\n"
                + "\n".join(f"  {v}" for v in result.violations)
            )
        return write_baseline(report, path)
