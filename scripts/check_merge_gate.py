#!/usr/bin/env python3
"""main マージ可否の機械判定。

## なぜ必要か

品質基準は3層で明文化されている:
  - .agent/skills/gate-keeper-v2/SKILL.md  … 全Phase共通の基本条件
  - .agent/skills/phase-completion/SKILL.md … フェーズ完了条件
  - backend/branding/PROJECT_CONSTITUTION.md §20.4 … 品質ゲート基準

しかし判定は人手で行われ、記録も残っていなかった（phase_state.json の
gate_checklist / gate_conditions はどちらも空）。結果、Phase A/B/C は
すべて完了したのに main へマージされないまま2,120コミットが積み上がった。

このスクリプトは基準を機械的に判定し、記録可能な形で出力する。

## 使い方

    # テスト成果物から判定（CI 向け）
    pytest -q --junitxml=test-results.xml
    pytest -q --cov=backend --cov-report=json:coverage.json
    python scripts/check_merge_gate.py --junit test-results.xml --coverage coverage.json

    # 成果物なしで判定できる条件だけ見る
    python scripts/check_merge_gate.py

    # JSON 出力（phase_state.json への記録用）
    python scripts/check_merge_gate.py --junit test-results.xml --json

終了コード: 0 = 全条件クリア / 1 = 未達あり / 2 = 判定不能
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEMORY = ROOT / "backend" / "agents" / "memory"

PHASE_STATE = MEMORY / "phase_state.json"
PHASE_GATES = MEMORY / "phase_gates.json"
DEBT_INDEX = MEMORY / "technical_debt_index.json"

# Gate Keeper v2 基本条件のカバレッジ閾値。
# 注意: phase_gates.json の Phase 2 定義は 50% を要求しており値が食い違う。
# 厳しい方（SKILL.md の 70%）を採用する。
COVERAGE_MIN = 70.0

UX_RATCHET_FILE = "test_ux_ratchet"


@dataclass
class Check:
    name: str
    description: str
    passed: bool | None  # None = 判定不能
    actual: str
    required: str

    @property
    def mark(self) -> str:
        return {True: "PASS", False: "FAIL", None: "判定不能"}[self.passed]


def _load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def check_emergency_stop() -> Check:
    state = _load(PHASE_STATE)
    if state is None:
        return Check("emergency_stop", "緊急停止フラグ", None, "phase_state.json 読込失敗", "False")
    value = state.get("emergency_stop")
    return Check("emergency_stop", "緊急停止フラグ", value is False, str(value), "False")


def check_critical_debt() -> Check:
    """CRITICAL 系技術負債の open 件数。

    Gate Keeper SKILL.md は「技術的負債が許容値以下 (0件)」とだけ書いており、
    全 open を指すのか CRITICAL のみかが曖昧。phase_state.json の指標名が
    critical_debt であることから CRITICAL 系のみと解釈する。
    参考値として全 open 件数も併記する。
    """
    data = _load(DEBT_INDEX)
    if data is None:
        return Check("critical_debt", "CRITICAL技術負債", None, "index 読込失敗", "0件")
    entries = data.get("entries", [])
    crit_open = sum(
        1 for e in entries
        if str(e.get("category", "")).startswith("CRITICAL") and e.get("status") == "open"
    )
    all_open = sum(1 for e in entries if e.get("status") == "open")
    return Check(
        "critical_debt", "CRITICAL技術負債",
        crit_open == 0,
        f"{crit_open}件（参考: 全open {all_open}件）", "0件",
    )


def _parse_junit(path: Path) -> tuple[int, int, int, int] | None:
    """(total, failures, errors, ux_ratchet_failures) を返す。"""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return None
    total = failures = errors = ux_fail = 0
    for tc in root.iter("testcase"):
        total += 1
        f = len(tc.findall("failure"))
        e = len(tc.findall("error"))
        failures += f
        errors += e
        if (f or e) and UX_RATCHET_FILE in (tc.get("file") or tc.get("classname") or ""):
            ux_fail += 1
    return total, failures, errors, ux_fail


def check_tests(junit: Path | None) -> list[Check]:
    if junit is None:
        return [
            Check("tests_all_pass", "テスト全PASS", None, "--junit 未指定", "失敗0件"),
            Check("ux_ratchet_pass", "UXラチェット全PASS", None, "--junit 未指定", "失敗0件"),
        ]
    parsed = _parse_junit(junit)
    if parsed is None:
        return [
            Check("tests_all_pass", "テスト全PASS", None, f"{junit} 解析失敗", "失敗0件"),
            Check("ux_ratchet_pass", "UXラチェット全PASS", None, f"{junit} 解析失敗", "失敗0件"),
        ]
    total, failures, errors, ux_fail = parsed
    bad = failures + errors
    return [
        Check("tests_all_pass", "テスト全PASS", bad == 0,
              f"{total}件中 失敗{failures} エラー{errors}", "失敗0件"),
        Check("ux_ratchet_pass", "UXラチェット全PASS", ux_fail == 0,
              f"失敗{ux_fail}件", "失敗0件"),
    ]


def check_coverage(cov: Path | None) -> Check:
    if cov is None:
        return Check("coverage_pct", "カバレッジ", None, "--coverage 未指定", f"{COVERAGE_MIN}%以上")
    data = _load(cov)
    if data is None:
        return Check("coverage_pct", "カバレッジ", None, f"{cov} 読込失敗", f"{COVERAGE_MIN}%以上")
    pct = data.get("totals", {}).get("percent_covered")
    if pct is None:
        return Check("coverage_pct", "カバレッジ", None, "totals.percent_covered 不在", f"{COVERAGE_MIN}%以上")
    return Check("coverage_pct", "カバレッジ", pct >= COVERAGE_MIN, f"{pct:.1f}%", f"{COVERAGE_MIN}%以上")


def phase_context() -> str:
    state = _load(PHASE_STATE) or {}
    gates = _load(PHASE_GATES) or {}
    ev = gates.get("evolution_roadmap", {}).get("phases", {})
    ev_phase = state.get("evolution_phase")
    ev_name = state.get("evolution_phase_name", "")
    ev_status = ev.get(ev_phase, {}).get("status", "?")
    return (
        f"45フェーズ体系: Phase {state.get('current_phase')} / {state.get('current_milestone')}\n"
        f"進化ロードマップ: Phase {ev_phase} ({ev_name}) — status={ev_status}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--junit", type=Path, help="pytest --junitxml の出力")
    ap.add_argument("--coverage", type=Path, help="pytest --cov-report=json の出力")
    ap.add_argument("--json", action="store_true", help="JSON で出力する")
    args = ap.parse_args()

    checks = [
        check_emergency_stop(),
        check_critical_debt(),
        *check_tests(args.junit),
        check_coverage(args.coverage),
    ]

    failed = [c for c in checks if c.passed is False]
    unknown = [c for c in checks if c.passed is None]

    if args.json:
        print(json.dumps({
            "checks": [asdict(c) for c in checks],
            "passed": not failed and not unknown,
            "failed_count": len(failed),
            "unknown_count": len(unknown),
        }, ensure_ascii=False, indent=2))
    else:
        print("=" * 72)
        print("main マージゲート判定")
        print("=" * 72)
        print(phase_context())
        print("-" * 72)
        print(f"{'条件':<22}{'判定':<10}{'実測':<28}{'要求'}")
        print("-" * 72)
        for c in checks:
            print(f"{c.description:<22}{c.mark:<10}{c.actual:<28}{c.required}")
        print("-" * 72)
        if failed:
            print(f"未達 {len(failed)} 件: " + ", ".join(c.description for c in failed))
        if unknown:
            print(f"判定不能 {len(unknown)} 件: " + ", ".join(c.description for c in unknown))
            print("  → --junit / --coverage に成果物を渡すと判定できます")
        if not failed and not unknown:
            print("全条件クリア。main へのマージ条件を満たしています。")

    if unknown:
        return 2
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
