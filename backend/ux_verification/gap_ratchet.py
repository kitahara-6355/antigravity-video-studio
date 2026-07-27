"""
ギャップラチェット — GapReport 4指標の単調増加（非退行）保証

検証指標:
1. total_pass_items — PASS項目数
2. story_completion_rate — ストーリー完了率
3. component_integration_count — コンポーネント統合数 (SKIP以外)
4. e2e_visual_coverage — E2Eビジュアルカバレッジ
"""
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .gap_analyzer import GapReport

logger = logging.getLogger(__name__)


@dataclass
class GapRatchetViolation:
    """ギャップラチェット違反の詳細"""
    metric: str           # 違反した指標名
    previous_value: float
    current_value: float
    delta: float
    message: str


@dataclass
class GapRatchetResult:
    """ギャップラチェット検証結果"""
    valid: bool
    violations: List[GapRatchetViolation] = field(default_factory=list)
    delta_pass_items: int = 0
    delta_completion_rate: float = 0.0
    delta_integration_count: int = 0
    delta_visual_coverage: float = 0.0

    def __str__(self):
        if self.valid:
            return (
                f"✅ ギャップラチェット検証PASS: "
                f"PASS数+{self.delta_pass_items}, "
                f"完了率+{self.delta_completion_rate:.1f}%, "
                f"統合数+{self.delta_integration_count}, "
                f"ビジュアル+{self.delta_visual_coverage:.1f}%"
            )
        return (
            f"❌ ギャップラチェット検証FAIL: {len(self.violations)}件の違反\n"
            + "\n".join(f"  - {v.message}" for v in self.violations)
        )


def _extract_metrics(report: GapReport) -> Dict[str, float]:
    """GapReport から4指標を抽出"""
    report.compute_aggregates()

    total = len(report.results)
    pass_count = report.pass_count

    # ストーリー完了率: 全ストーリーのうちFAIL/SKIPが0のストーリーの割合
    completed_stories = 0
    total_stories = len(report.story_summary) if report.story_summary else 0
    for story_id, summary in report.story_summary.items():
        if summary["fail"] == 0 and summary["skip"] == 0 and summary["total"] > 0:
            completed_stories += 1
    completion_rate = round(
        completed_stories / max(total_stories, 1) * 100, 2
    )

    # コンポーネント統合数: SKIP以外 (PASS + FAIL) の項目数
    integration_count = pass_count + report.fail_count

    # E2Eビジュアルカバレッジ: layer >= 2 かつ PASS の項目数 / layer >= 2 の全項目数
    visual_total = sum(1 for r in report.results if r.layer >= 2)
    visual_pass = sum(
        1 for r in report.results if r.layer >= 2 and r.status == "PASS"
    )
    visual_coverage = round(
        visual_pass / max(visual_total, 1) * 100, 2
    )

    return {
        "total_pass_items": float(pass_count),
        "story_completion_rate": completion_rate,
        "component_integration_count": float(integration_count),
        "e2e_visual_coverage": visual_coverage,
    }


class GapRatchetValidator:
    """ギャップラチェット: 4指標の非退行を検証"""

    _METRIC_LABELS = {
        "total_pass_items": "PASS項目数",
        "story_completion_rate": "ストーリー完了率",
        "component_integration_count": "コンポーネント統合数",
        "e2e_visual_coverage": "E2Eビジュアルカバレッジ",
    }

    def validate(
        self,
        previous_report: GapReport,
        current_report: GapReport,
    ) -> GapRatchetResult:
        """前回と今回のGapReportを比較し、4指標の非退行を検証"""
        prev_metrics = _extract_metrics(previous_report)
        curr_metrics = _extract_metrics(current_report)

        violations: List[GapRatchetViolation] = []

        for metric_key in self._METRIC_LABELS:
            prev_val = prev_metrics[metric_key]
            curr_val = curr_metrics[metric_key]
            delta = curr_val - prev_val

            if curr_val < prev_val:
                label = self._METRIC_LABELS[metric_key]
                violations.append(GapRatchetViolation(
                    metric=metric_key,
                    previous_value=prev_val,
                    current_value=curr_val,
                    delta=delta,
                    message=f"{label}が減少: {prev_val} → {curr_val} (Δ{delta})",
                ))

        result = GapRatchetResult(
            valid=len(violations) == 0,
            violations=violations,
            delta_pass_items=int(
                curr_metrics["total_pass_items"] - prev_metrics["total_pass_items"]
            ),
            delta_completion_rate=(
                curr_metrics["story_completion_rate"]
                - prev_metrics["story_completion_rate"]
            ),
            delta_integration_count=int(
                curr_metrics["component_integration_count"]
                - prev_metrics["component_integration_count"]
            ),
            delta_visual_coverage=(
                curr_metrics["e2e_visual_coverage"]
                - prev_metrics["e2e_visual_coverage"]
            ),
        )

        if result.valid:
            logger.info(str(result))
        else:
            logger.warning(str(result))

        return result

    def save_snapshot(self, report: GapReport, path: str) -> None:
        """GapReport のメトリクスをJSONスナップショットとして保存"""
        metrics = _extract_metrics(report)
        snapshot_data = {
            "timestamp": datetime.now().isoformat(),
            "metrics": metrics,
            "pass_count": report.pass_count,
            "fail_count": report.fail_count,
            "skip_count": report.skip_count,
            "pass_rate": report.pass_rate,
            "story_summary": report.story_summary,
        }

        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(snapshot_data, f, ensure_ascii=False, indent=2)

        logger.info(f"ギャップスナップショット保存: {out_path.name}")

    def load_snapshot(self, path: str) -> Optional[GapReport]:
        """JSONスナップショットからGapReportを復元

        注意: results リストは復元されない（メトリクスのみ）。
        ラチェット比較用の集計値のみ復元される。
        """
        snap_path = Path(path)
        if not snap_path.exists():
            logger.warning(f"スナップショットが存在しません: {snap_path}")
            return None

        with open(snap_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        report = GapReport()
        report.pass_count = data.get("pass_count", 0)
        report.fail_count = data.get("fail_count", 0)
        report.skip_count = data.get("skip_count", 0)
        report.pass_rate = data.get("pass_rate", 0.0)
        report.story_summary = data.get("story_summary", {})

        logger.info(f"ギャップスナップショット読込: {snap_path.name}")
        return report
