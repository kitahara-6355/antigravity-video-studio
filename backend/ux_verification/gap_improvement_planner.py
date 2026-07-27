"""
ギャップ改善プランナー — GapReportから優先度付き改善タスクを自動生成

GapReport の FAIL/SKIP 項目を分析し、gap_type 分類・優先度計算・
修正戦略提案を行い、ImprovementPlan として出力する。
"""
import logging
from dataclasses import dataclass, field
from typing import List

from .gap_analyzer import GapCheckResult, GapReport

logger = logging.getLogger(__name__)

# ストーリーID → 優先度重み
# O-1〜O-8: パイプラインコア (×10)
# O-9〜O-12: 最適化 (×5)
# A-*: 管理 (×3)
_PRIORITY_WEIGHTS = {}
for i in range(1, 9):
    _PRIORITY_WEIGHTS[f"O-{i}"] = 10
for i in range(9, 13):
    _PRIORITY_WEIGHTS[f"O-{i}"] = 5
# A-* は動的に処理


def _get_story_weight(story_id: str) -> int:
    """ストーリーIDから優先度重みを取得"""
    if story_id in _PRIORITY_WEIGHTS:
        return _PRIORITY_WEIGHTS[story_id]
    if story_id.startswith("A-"):
        return 3
    return 1


@dataclass
class ImprovementTask:
    """個別の改善タスク"""
    story_id: str         # "O-6"
    item_id: str          # "O6-L1-01"
    gap_type: str         # "未接続" / "未実装" / "品質不足" / "シミュレーション"
    priority: int         # 優先度スコア (高いほど重要)
    estimated_effort: str  # "S" / "M" / "L"
    fix_strategy: str     # 推奨修正方針


@dataclass
class ImprovementPlan:
    """改善計画"""
    tasks: List[ImprovementTask] = field(default_factory=list)
    total_gaps: int = 0
    coverage_rate: float = 0.0
    estimated_new_coverage: float = 0.0


class GapImprovementPlanner:
    """ギャップ分析結果から改善計画を生成"""

    def generate_plan(self, gap_report: GapReport, design_stock_store=None) -> ImprovementPlan:
        """GapReportから改善計画を生成

        Args:
            gap_report: ギャップ分析レポート
            design_stock_store: 設計ストックストア (オプショナル)

        Returns:
            ImprovementPlan: 優先度順にソートされた改善タスクリスト
        """
        plan = ImprovementPlan()
        tasks: List[ImprovementTask] = []

        for result in gap_report.results:
            if result.status == "PASS":
                continue

            matched_item = self._find_matched_stock_item(result.item_id, design_stock_store)
            if matched_item:
                status = matched_item.get("status", "pending")
                # completed / dispatched の場合は改善計画から除外
                if status in ("completed", "dispatched"):
                    continue

            gap_type = self._classify_gap(result)
            priority = self._calc_priority(result, matched_item)
            fix_strategy = self._suggest_fix(result)
            effort = self._estimate_effort(result, matched_item)

            tasks.append(ImprovementTask(
                story_id=result.story_id,
                item_id=result.item_id,
                gap_type=gap_type,
                priority=priority,
                estimated_effort=effort,
                fix_strategy=fix_strategy,
            ))

        # 優先度降順でソート
        tasks.sort(key=lambda t: t.priority, reverse=True)

        plan.tasks = tasks
        plan.total_gaps = len(tasks)
        plan.coverage_rate = gap_report.pass_rate

        # 全ギャップ解消時の推定カバレッジ
        total_items = len(gap_report.results)
        if total_items > 0:
            plan.estimated_new_coverage = round(
                (gap_report.pass_count + plan.total_gaps) / total_items * 100, 2
            )
        else:
            plan.estimated_new_coverage = 0.0

        logger.info(
            f"改善計画生成: {plan.total_gaps}件のギャップ "
            f"(現在 {plan.coverage_rate}% → 推定 {plan.estimated_new_coverage}%)"
        )
        return plan

    def _find_matched_stock_item(self, item_id: str, design_stock_store) -> dict:
        """設計ストック上のタスクからitem_idに関連する項目を検索

        Args:
            item_id: ストーリー内の検証項目ID
            design_stock_store: 設計ストックストア

        Returns:
            dict: マッチした設計ストックアイテム (存在しない場合はNone)
        """
        if not design_stock_store:
            return None

        for item in design_stock_store.items:
            title = item.get("title", "")
            desc = item.get("description", "")
            if item_id in title or item_id in desc:
                return item

            for step in item.get("implementation_steps", []):
                step_desc = step if isinstance(step, str) else step.get("description", "")
                if item_id in step_desc:
                    return item

        return None

    def _classify_gap(self, result: GapCheckResult) -> str:
        """ギャップタイプの分類

        - SKIP + "結果データなし" → "未接続" (E2Eテスト自体が未実施)
        - SKIP + "存在しない" → "未実装" (テスト項目がE2Eスイートに未追加)
        - FAIL → "品質不足" (テストは存在するが不合格)
        - SKIP + その他 → "シミュレーション"
        """
        if result.status == "FAIL":
            return "品質不足"
        # SKIP の場合
        if "結果データなし" in result.message:
            return "未接続"
        if "存在しない" in result.message:
            return "未実装"
        return "シミュレーション"

    def _calc_priority(self, result: GapCheckResult, matched_item: dict = None) -> int:
        """優先度スコアの計算

        base_score = レイヤー重み × ストーリー重み
        レイヤー重み: L5=50, L4=40, L3=30, L2=20, L1=10
        ストーリー重み: O-1〜O-8=×10, O-9〜O-12=×5, A-*=×3
        FAILは×2ブースト (既存テストの不合格はSKIPより緊急度が高い)
        設計ストックが in_discussion の場合はさらに ×1.5 ブースト
        """
        layer_weight = max(result.layer, 1) * 10
        story_weight = _get_story_weight(result.story_id)
        base = layer_weight * story_weight

        if result.status == "FAIL":
            base *= 2

        if matched_item and matched_item.get("status") == "in_discussion":
            base = int(base * 1.5)

        return base

    def _suggest_fix(self, result: GapCheckResult) -> str:
        """推奨修正方針の提案"""
        gap_type = self._classify_gap(result)

        if gap_type == "未接続":
            return f"E2Eテストスイートに {result.item_id} の検証を追加"
        elif gap_type == "未実装":
            return f"{result.item_id} のテストケースを新規実装"
        elif gap_type == "品質不足":
            return f"{result.item_id} の不合格原因を調査し修正"
        else:
            return f"{result.item_id} のシミュレーション結果を確認"

    def _estimate_effort(self, result: GapCheckResult, matched_item: dict = None) -> str:
        """工数の概算

        設計ストックの難易度 (S/A/B/C) が紐づく場合はそれを優先:
        S/A -> L, B -> M, C -> S
        それ以外はレイヤーで判定:
        L1-L2: S (DOM確認/ビジュアルチェック)
        L3: M (インタラクション)
        L4-L5: L (状態遷移/E2E)
        """
        if matched_item:
            diff = matched_item.get("difficulty", "C")
            if diff in ("S", "A"):
                return "L"
            elif diff == "B":
                return "M"
            elif diff == "C":
                return "S"

        if result.layer <= 2:
            return "S"
        elif result.layer == 3:
            return "M"
        else:
            return "L"
