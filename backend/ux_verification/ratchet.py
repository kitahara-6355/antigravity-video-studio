"""
ラチェット機構 — UX検証の単調増加保証（レガシー）

⚠️ 注意: このモジュールはレガシーラチェット機構です。
新規のラチェット検証は gap_ratchet.py (GapRatchetValidator) を使用してください。
ベースライン参照は v*_baseline.json (gap系フォーマット) が正規です。

旧スナップショット (v1.0〜v5.0) はレガシーデータであり、
v6.0以降の架空データは quarantined/ に隔離済みです。

3つの指標が前回スナップショットを下回らないことを保証:
1. 検証項目数 (total_items)
2. 連動率 (correlation_rate)
3. PASS数 (pass_items)
"""
import logging
from dataclasses import dataclass, field
from typing import List

from .snapshot import UXVerificationSnapshot

logger = logging.getLogger(__name__)


@dataclass
class RatchetViolation:
    """ラチェット違反の詳細"""
    metric: str           # "total_items" / "correlation_rate" / "pass_items"
    previous_value: float
    current_value: float
    delta: float
    message: str


@dataclass
class RatchetResult:
    """ラチェット検証結果"""
    valid: bool
    violations: List[RatchetViolation] = field(default_factory=list)
    delta_items: int = 0
    delta_correlation: float = 0.0
    delta_pass: int = 0
    report: str = ""

    def __str__(self):
        if self.valid:
            return (
                f"✅ ラチェット検証PASS: "
                f"項目+{self.delta_items}, "
                f"連動率+{self.delta_correlation:.1f}%, "
                f"PASS+{self.delta_pass}"
            )
        return (
            f"❌ ラチェット検証FAIL: {len(self.violations)}件の違反\n"
            + "\n".join(f"  - {v.message}" for v in self.violations)
        )


class RatchetValidator:
    """ラチェット検証: 3指標の単調増加を保証"""

    def validate(
        self,
        previous: UXVerificationSnapshot,
        current: UXVerificationSnapshot,
    ) -> RatchetResult:
        """前回と今回のスナップショットを比較し、単調増加を検証"""
        if previous is None or current is None:
            raise ValueError("previous および current スナップショットは None にできません。")

        previous.compute_aggregates()
        current.compute_aggregates()

        violations: List[RatchetViolation] = []

        # 各メトリクスのリグレッション検証を実行し、違反を収集
        self._collect_total_items_violations(previous, current, violations)
        self._collect_correlation_rate_violations(previous, current, violations)
        self._collect_pass_items_violations(previous, current, violations)

        result = RatchetResult(
            valid=len(violations) == 0,
            violations=violations,
            delta_items=current.total_items - previous.total_items,
            delta_correlation=current.correlation_rate - previous.correlation_rate,
            delta_pass=current.pass_items - previous.pass_items,
        )

        # レポート生成
        result.report = self._generate_report(previous, current)

        if result.valid:
            logger.info(str(result))
        else:
            logger.warning(str(result))

        return result

    def _collect_total_items_violations(
        self,
        previous: UXVerificationSnapshot,
        current: UXVerificationSnapshot,
        violations: List[RatchetViolation],
    ) -> None:
        """検証項目数の減少（退行）をチェックし、違反を収集"""
        if current.total_items < previous.total_items:
            delta = current.total_items - previous.total_items
            violations.append(RatchetViolation(
                metric="total_items",
                previous_value=previous.total_items,
                current_value=current.total_items,
                delta=delta,
                message=f"検証項目数が減少: {previous.total_items} → {current.total_items} (Δ{delta})",
            ))

    def _collect_correlation_rate_violations(
        self,
        previous: UXVerificationSnapshot,
        current: UXVerificationSnapshot,
        violations: List[RatchetViolation],
    ) -> None:
        """UXストーリー連動率の低下（退行）をチェックし、違反を収集"""
        if current.correlation_rate < previous.correlation_rate:
            delta = current.correlation_rate - previous.correlation_rate
            violations.append(RatchetViolation(
                metric="correlation_rate",
                previous_value=previous.correlation_rate,
                current_value=current.correlation_rate,
                delta=delta,
                message=f"UXストーリー連動率が低下: {previous.correlation_rate}% → {current.correlation_rate}% (Δ{delta:.1f}%)",
            ))

    def _collect_pass_items_violations(
        self,
        previous: UXVerificationSnapshot,
        current: UXVerificationSnapshot,
        violations: List[RatchetViolation],
    ) -> None:
        """PASS項目数の減少（退行）をチェックし、違反を収集"""
        if current.pass_items < previous.pass_items:
            delta = current.pass_items - previous.pass_items
            violations.append(RatchetViolation(
                metric="pass_items",
                previous_value=previous.pass_items,
                current_value=current.pass_items,
                delta=delta,
                message=f"PASS項目数が減少 (リグレッション): {previous.pass_items} → {current.pass_items} (Δ{delta})",
            ))

    def _generate_report(
        self,
        previous: UXVerificationSnapshot,
        current: UXVerificationSnapshot,
    ) -> str:
        """適合度差分レポートを生成"""
        lines = []
        lines.extend(self._generate_report_header(previous, current))
        lines.extend(self._generate_metrics_comparison(previous, current))
        lines.extend(self._generate_fulfillment_warning(previous, current))
        lines.extend(self._generate_gap_report(current))
        lines.append("╚══════════════════════════════════════════════════════╝")
        return "\n".join(lines)

    def _generate_report_header(
        self,
        previous: UXVerificationSnapshot,
        current: UXVerificationSnapshot,
    ) -> List[str]:
        """レポートのヘッダー部分を生成"""
        return [
            "╔══════════════════════════════════════════════════════╗",
            f"║  UX検証適合度差分レポート {previous.version} → {current.version}",
            "╠══════════════════════════════════════════════════════╣",
            "",
        ]

    def _generate_metrics_comparison(
        self,
        previous: UXVerificationSnapshot,
        current: UXVerificationSnapshot,
    ) -> List[str]:
        """各メトリクスの差分比較行を生成"""
        lines = []
        
        # 検証項目数
        delta_items = current.total_items - previous.total_items
        mark_items = "✅" if delta_items >= 0 else "❌"
        lines.append(
            f"  検証項目数:  {previous.total_items} → {current.total_items}  "
            f"({'+' if delta_items >= 0 else ''}{delta_items}) {mark_items}"
        )

        # 連動率
        delta_corr = current.correlation_rate - previous.correlation_rate
        mark_corr = "✅" if delta_corr >= 0 else "❌"
        lines.append(
            f"  連動率:      {previous.correlation_rate}% → {current.correlation_rate}%  "
            f"({'+' if delta_corr >= 0 else ''}{delta_corr:.1f}%) {mark_corr}"
        )

        # PASS数
        delta_pass = current.pass_items - previous.pass_items
        mark_pass = "✅" if delta_pass >= 0 else "❌"
        lines.append(
            f"  充足PASS:    {previous.pass_items} → {current.pass_items}  "
            f"({'+' if delta_pass >= 0 else ''}{delta_pass}) {mark_pass}"
        )

        # 充足率
        delta_rate = current.fulfillment_rate - previous.fulfillment_rate
        lines.append(
            f"  充足率:      {previous.fulfillment_rate}% → {current.fulfillment_rate}%  "
            f"({'+' if delta_rate >= 0 else ''}{delta_rate:.1f}%)"
        )
        
        return lines

    def _generate_fulfillment_warning(
        self,
        previous: UXVerificationSnapshot,
        current: UXVerificationSnapshot,
    ) -> List[str]:
        """充足率低下に関する警告を生成"""
        delta_rate = current.fulfillment_rate - previous.fulfillment_rate
        delta_items = current.total_items - previous.total_items
        
        lines = []
        if delta_rate < 0 and delta_items > 0:
            lines.extend([
                "",
                "  ⚠️ 充足率低下は正常: 検証項目増加による",
                "     (分母が増えたため分子が追いつくまで低下する)",
            ])
        return lines

    def _generate_gap_report(
        self,
        current: UXVerificationSnapshot,
    ) -> List[str]:
        """UXストーリー別ギャップレポートを生成"""
        lines = [
            "",
            "  システム適合度ギャップ:",
        ]
        
        for ux in sorted(current.items_per_story.keys()):
            total = current.items_per_story.get(ux, 0)
            passed = current.pass_per_story.get(ux, 0)
            rate = round(passed / max(total, 1) * 100)
            if rate < 100:
                unpassed_by_layer = {}
                for item in current.items:
                    if item.get("ux_story") == ux and item.get("passed") is not True:
                        l_val = item.get("layer", 0)
                        if l_val is None:
                            l_val = 0
                        layer_name = f"L{l_val}"
                        unpassed_by_layer[layer_name] = unpassed_by_layer.get(layer_name, 0) + 1
                
                details = []
                for l_key in sorted(unpassed_by_layer.keys()):
                    cnt = unpassed_by_layer[l_key]
                    details.append(f"{l_key}層で{cnt}件未PASS")
                
                detail_str = " — " + ", ".join(details) if details else ""
                lines.append(f"  {ux}: {passed}/{total} ({rate}%){detail_str}")
                
        return lines
