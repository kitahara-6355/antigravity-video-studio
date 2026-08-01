"""
Anti-Hallucination Gate — 空想リスク排除の自己検証レイヤー

全ての「PASS」報告に対して証拠チェーンを要求し、
架空データ・偽PASS・検証なしの合格を構造的に排除する。

2026-06-28 制定 — 空想リスク排除規約に基づく
"""
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# プロジェクトルート
PROJECT_ROOT = Path(__file__).parent.parent.parent
SNAPSHOTS_DIR = PROJECT_ROOT / "backend" / "ux_verification" / "snapshots"
E2E_RESULTS_PATH = PROJECT_ROOT / "backend" / "tests" / "e2e_results.json"
HARNESS_STATUS_PATH = (
    _writable_path("backend/agents/orchestration/harness_audit_status.json")
)


@dataclass
class IntegrityViolation:
    """検出された空想リスク違反"""
    source: str          # "snapshot" / "harness" / "verified_facts"
    severity: str        # "CRITICAL" / "HIGH" / "MEDIUM"
    description: str
    evidence: str
    file_path: str = ""


@dataclass
class IntegrityReport:
    """空想リスク整合性レポート"""
    violations: List[IntegrityViolation] = field(default_factory=list)
    checks_performed: int = 0
    checks_passed: int = 0
    hallucination_score: float = 0.0  # 0.0 (安全) 〜 1.0 (完全空想)

    @property
    def is_clean(self) -> bool:
        return len(self.violations) == 0

    def compute_score(self) -> None:
        """空想リスクスコアを算出"""
        if self.checks_performed == 0:
            self.hallucination_score = 1.0  # 検証なし = 最大リスク
            return

        critical = sum(1 for v in self.violations if v.severity == "CRITICAL")
        high = sum(1 for v in self.violations if v.severity == "HIGH")
        medium = sum(1 for v in self.violations if v.severity == "MEDIUM")

        # 重み付きスコア: CRITICAL=1.0, HIGH=0.5, MEDIUM=0.2
        weighted = critical * 1.0 + high * 0.5 + medium * 0.2
        self.hallucination_score = min(1.0, weighted / max(self.checks_performed, 1))


class AntiHallucinationGate:
    """全ての「PASS」報告に対して証拠チェーンを要求する自己検証ゲート"""

    # 架空データ検出の閾値
    FABRICATION_ITEM_THRESHOLD = 500    # 500項目超
    FABRICATION_PASS_RATE_THRESHOLD = 0.99  # 99%以上のPASS率

    def __init__(
        self,
        snapshots_dir: Optional[Path] = None,
        e2e_results_path: Optional[Path] = None,
        harness_status_path: Optional[Path] = None,
    ):
        self.snapshots_dir = snapshots_dir or SNAPSHOTS_DIR
        self.e2e_results_path = e2e_results_path or E2E_RESULTS_PATH
        self.harness_status_path = harness_status_path or HARNESS_STATUS_PATH

    def run_all_checks(self) -> IntegrityReport:
        """全検証チェックを実行"""
        report = IntegrityReport()

        self._check_snapshot_integrity(report)
        self._check_harness_integrity(report)
        self._check_e2e_consistency(report)

        report.compute_score()

        if report.violations:
            logger.warning(
                f"⚠️ AntiHallucinationGate: "
                f"{len(report.violations)}件の空想リスク違反を検出 "
                f"(スコア: {report.hallucination_score:.2f})"
            )
        else:
            logger.info(
                f"✅ AntiHallucinationGate: 全{report.checks_performed}チェック通過"
            )

        return report

    def verify_snapshot_integrity(self, snapshot_path: Path) -> Tuple[bool, str]:
        """個別スナップショットの架空データチェック

        Returns:
            (is_valid, message)
        """
        try:
            with open(snapshot_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            return False, f"スナップショット読込エラー: {e}"

        # quarantined ディレクトリ内のファイルは無条件拒否
        if "quarantined" in str(snapshot_path):
            return False, "隔離済みスナップショット — 使用禁止"

        # ストーリー内の全検証項目を走査
        all_items = []
        if isinstance(data, dict) and "stories" in data:
            for story in data["stories"]:
                items = story.get("verification_items", [])
                all_items.extend(items)
        elif isinstance(data, dict):
            # フラット構造の場合
            for key, value in data.items():
                if isinstance(value, dict) and "verification_items" in value:
                    all_items.extend(value["verification_items"])

        total = len(all_items)
        if total == 0:
            return True, "項目なし（空スナップショット）"

        passed = sum(1 for item in all_items if item.get("passed") is True)
        pass_rate = passed / total

        if (
            total > self.FABRICATION_ITEM_THRESHOLD
            and pass_rate >= self.FABRICATION_PASS_RATE_THRESHOLD
        ):
            return False, (
                f"架空データ検出: {total}項目中{passed}件PASS "
                f"(PASS率 {pass_rate*100:.1f}%) — "
                f"閾値超過 ({self.FABRICATION_ITEM_THRESHOLD}項目超 "
                f"× {self.FABRICATION_PASS_RATE_THRESHOLD*100:.0f}%超)"
            )

        return True, f"正常 ({total}項目, PASS率 {pass_rate*100:.1f}%)"

    def verify_harness_result(
        self,
        check_id: str,
        result: Optional[bool],
        evidence: str,
    ) -> Tuple[bool, str]:
        """ハーネス結果に証拠チェーンがあるか検証

        Args:
            check_id: チェックID (e.g., "C-01")
            result: True/False/None
            evidence: 証拠テキスト

        Returns:
            (is_valid, message)
        """
        # None = SKIP（正直な未実装）→ 有効
        if result is None:
            return True, f"{check_id}: SKIP（未実装 — 正直に報告）"

        if result is True:
            # 無条件True検出パターン
            _empty_evidence_patterns = [
                "未実装のためPASS",
                "未生成",
                "ログなし (PASS)",
                "ファイルなし",
                "警告付きPASS",
            ]
            for pattern in _empty_evidence_patterns:
                if pattern in evidence:
                    return False, (
                        f"{check_id}: 証拠なしのPASS — "
                        f"'{pattern}' パターン検出"
                    )

            # 証拠が空文字列または短すぎる
            if len(evidence.strip()) < 10:
                return False, (
                    f"{check_id}: 証拠テキストが不十分 "
                    f"({len(evidence.strip())}文字)"
                )

        return True, f"{check_id}: 検証済み"

    def verify_ux_story_pass(
        self,
        story_id: str,
        item_id: str,
        claimed_result: bool,
    ) -> Tuple[bool, str]:
        """UXストーリーPASS主張をe2e_results.jsonと照合"""
        if not self.e2e_results_path.exists():
            if claimed_result:
                return False, (
                    f"{item_id}: e2e_results.json不在でPASS主張 — 空想リスク"
                )
            return True, f"{item_id}: e2e_results.json不在（PASS主張なし）"

        try:
            with open(self.e2e_results_path, "r", encoding="utf-8") as f:
                e2e_results = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            if claimed_result:
                return False, f"{item_id}: e2e_results.json読込エラーでPASS主張"
            return True, f"{item_id}: 読込エラー（PASS主張なし）"

        # 全チェックカテゴリを横断検索
        found = False
        actual_result = None
        for category in e2e_results.values():
            if isinstance(category, dict) and item_id in category:
                found = True
                actual_result = category[item_id]
                break

        if not found:
            if claimed_result:
                return False, (
                    f"{item_id}: e2e_results.jsonに結果なしだがPASS主張 — 空想リスク"
                )
            return True, f"{item_id}: 未テスト（PASS主張なし）"

        if claimed_result and not actual_result:
            return False, (
                f"{item_id}: PASS主張だがe2e_results.jsonではFAIL — 矛盾"
            )

        return True, f"{item_id}: e2e_results.jsonと整合"

    def _check_snapshot_integrity(self, report: IntegrityReport) -> None:
        """全スナップショットの架空データチェック"""
        snapshots_path = Path(self.snapshots_dir)
        if not snapshots_path.exists():
            report.checks_performed += 1
            report.violations.append(IntegrityViolation(
                source="snapshot",
                severity="HIGH",
                description="スナップショットディレクトリが存在しない",
                evidence=str(snapshots_path),
            ))
            return

        for json_file in sorted(snapshots_path.glob("*.json")):
            report.checks_performed += 1
            is_valid, message = self.verify_snapshot_integrity(json_file)

            if is_valid:
                report.checks_passed += 1
            else:
                report.violations.append(IntegrityViolation(
                    source="snapshot",
                    severity="CRITICAL",
                    description=message,
                    evidence=f"ファイル: {json_file.name}",
                    file_path=str(json_file),
                ))

    def _check_harness_integrity(self, report: IntegrityReport) -> None:
        """ハーネス監査結果の偽PASS検出"""
        if not self.harness_status_path.exists():
            report.checks_performed += 1
            report.checks_passed += 1  # ファイル不在は正常（監査未実行）
            return

        try:
            with open(self.harness_status_path, "r", encoding="utf-8") as f:
                status = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            report.checks_performed += 1
            report.violations.append(IntegrityViolation(
                source="harness",
                severity="MEDIUM",
                description="harness_audit_status.json読込エラー",
                evidence=str(self.harness_status_path),
            ))
            return

        # 全チェック結果をスキャン
        checks = status.get("checks", status.get("results", []))
        if isinstance(checks, list):
            for check in checks:
                report.checks_performed += 1
                check_id = check.get("id", check.get("check_id", "unknown"))
                result = check.get("passed", check.get("result"))
                evidence = check.get("message", check.get("evidence", ""))

                is_valid, msg = self.verify_harness_result(check_id, result, evidence)
                if is_valid:
                    report.checks_passed += 1
                else:
                    report.violations.append(IntegrityViolation(
                        source="harness",
                        severity="HIGH",
                        description=msg,
                        evidence=f"check_id={check_id}",
                        file_path=str(self.harness_status_path),
                    ))

    def _check_e2e_consistency(self, report: IntegrityReport) -> None:
        """E2Eテスト結果の自己整合性チェック"""
        report.checks_performed += 1

        if not self.e2e_results_path.exists():
            report.checks_passed += 1  # 不在は正常（テスト未実行）
            return

        try:
            with open(self.e2e_results_path, "r", encoding="utf-8") as f:
                e2e_results = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            report.violations.append(IntegrityViolation(
                source="e2e",
                severity="MEDIUM",
                description="e2e_results.json読込エラー",
                evidence=str(self.e2e_results_path),
            ))
            return

        # E2E結果が空でないか確認
        total_items = 0
        for category in e2e_results.values():
            if isinstance(category, dict):
                total_items += len(category)

        if total_items == 0:
            report.violations.append(IntegrityViolation(
                source="e2e",
                severity="HIGH",
                description="e2e_results.jsonが空 — テスト結果が記録されていない",
                evidence=str(self.e2e_results_path),
            ))
        else:
            report.checks_passed += 1

    def generate_integrity_report(self) -> str:
        """Markdown形式の整合性レポートを生成"""
        report = self.run_all_checks()

        lines = [
            "# 🛡️ AntiHallucinationGate — 整合性レポート",
            "",
            f"**空想リスクスコア**: {report.hallucination_score:.2f} "
            f"({'🟢 安全' if report.hallucination_score < 0.1 else '🟡 注意' if report.hallucination_score < 0.3 else '🔴 危険'})",
            f"**チェック実行数**: {report.checks_performed}",
            f"**チェック合格数**: {report.checks_passed}",
            f"**違反検出数**: {len(report.violations)}",
            "",
        ]

        if report.violations:
            lines.append("## 検出された違反")
            lines.append("")
            lines.append("| # | ソース | 深刻度 | 説明 |")
            lines.append("|---|---|---|---|")
            for i, v in enumerate(report.violations, 1):
                lines.append(
                    f"| {i} | {v.source} | {v.severity} | {v.description} |"
                )
        else:
            lines.append("## ✅ 違反なし — 全チェック合格")

        return "\n".join(lines)


def main():
    """CLI実行用エントリポイント"""
    logging.basicConfig(level=logging.INFO)
    gate = AntiHallucinationGate()
    print(gate.generate_integrity_report())


if __name__ == "__main__":
    main()

