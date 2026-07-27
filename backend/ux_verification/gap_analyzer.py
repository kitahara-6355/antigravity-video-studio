"""
UXギャップ分析 — 全UXストーリーとE2Eテスト結果の照合

全ストーリーJSONを読み込み、E2Eテスト結果と照合して
カバレッジギャップを自動検出する。
"""
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

STORIES_DIR = Path(__file__).parent / "stories"

# test_method → e2e_results のキーマッピング
_METHOD_TO_KEY = {
    "dom_exists": "dom_checks",
    "visual_check": "visual_checks",
    "interaction": "interaction_checks",
    "state_transition": "state_checks",
    "e2e": "e2e_checks",
}


@dataclass
class GapCheckResult:
    """個別検証項目のギャップチェック結果"""
    item_id: str          # "O6-L1-01"
    story_id: str         # "O-6"
    status: str           # "PASS" / "FAIL" / "SKIP"
    message: str
    layer: int = 0


@dataclass
class GapReport:
    """ギャップ分析レポート"""
    results: List[GapCheckResult] = field(default_factory=list)
    pass_count: int = 0
    fail_count: int = 0
    skip_count: int = 0
    pass_rate: float = 0.0
    story_summary: Dict[str, Dict] = field(default_factory=dict)

    def compute_aggregates(self) -> None:
        """results リストから集計値を再計算"""
        self.pass_count = sum(1 for r in self.results if r.status == "PASS")
        self.fail_count = sum(1 for r in self.results if r.status == "FAIL")
        self.skip_count = sum(1 for r in self.results if r.status == "SKIP")

        total = len(self.results)
        if total > 0:
            self.pass_rate = round(self.pass_count / total * 100, 2)
        else:
            self.pass_rate = 0.0

        # ストーリー別集計
        self.story_summary = {}
        for r in self.results:
            if r.story_id not in self.story_summary:
                self.story_summary[r.story_id] = {
                    "total": 0, "pass": 0, "fail": 0, "skip": 0,
                }
            self.story_summary[r.story_id]["total"] += 1
            if r.status == "PASS":
                self.story_summary[r.story_id]["pass"] += 1
            elif r.status == "FAIL":
                self.story_summary[r.story_id]["fail"] += 1
            else:
                self.story_summary[r.story_id]["skip"] += 1


class UXGapAnalyzer:
    """UXストーリー × E2Eテスト結果のギャップ分析"""

    def __init__(self, stories_dir: Optional[Path] = None):
        self.stories_dir = stories_dir or STORIES_DIR
        self.stories: List[dict] = []
        self._load_stories()

    def _load_stories(self) -> None:
        """storiesディレクトリから全JSONを読み込み"""
        stories_path = Path(self.stories_dir)
        if not stories_path.exists():
            logger.warning(f"ストーリーディレクトリが存在しません: {stories_path}")
            return

        for json_file in sorted(stories_path.glob("*.json")):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "ux_id" in data and "verification_items" in data:
                    self.stories.append(data)
                    logger.debug(
                        f"ストーリー読込: {data['ux_id']} - {data.get('name', '')} "
                        f"({len(data['verification_items'])}項目)"
                    )
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"ストーリーJSON読込エラー: {json_file.name}: {e}")

        logger.info(f"UXストーリー {len(self.stories)} 件読込完了")

    def analyze(self, e2e_results: Optional[Dict] = None) -> GapReport:
        """全ストーリーの検証項目をE2E結果と照合

        Args:
            e2e_results: E2Eテスト結果辞書。Noneの場合は全項目SKIPとして報告。
                形式: {"dom_checks": {"O6-L1-01": True, ...}, ...}

        Returns:
            GapReport: ギャップ分析結果
        """
        report = GapReport()

        for story in self.stories:
            story_id = story["ux_id"]
            items = story.get("verification_items", [])

            for item in items:
                item_id = item["id"]
                layer = item.get("layer", 0)
                test_method = item.get("test_method", "")

                if e2e_results is None:
                    result = GapCheckResult(
                        item_id=item_id,
                        story_id=story_id,
                        status="SKIP",
                        message="E2Eテスト未実施 — 結果データなし",
                        layer=layer,
                    )
                else:
                    result = self._check_item(
                        item_id, story_id, layer, test_method, e2e_results
                    )

                report.results.append(result)

        report.compute_aggregates()

        logger.info(
            f"ギャップ分析完了: {report.pass_count}PASS / "
            f"{report.fail_count}FAIL / {report.skip_count}SKIP "
            f"(PASS率 {report.pass_rate}%)"
        )
        return report

    def _check_item(
        self,
        item_id: str,
        story_id: str,
        layer: int,
        test_method: str,
        e2e_results: Dict,
    ) -> GapCheckResult:
        """個別項目のE2E結果照合"""
        check_key = _METHOD_TO_KEY.get(test_method)

        if check_key is None:
            return GapCheckResult(
                item_id=item_id,
                story_id=story_id,
                status="SKIP",
                message=f"不明なtest_method: {test_method}",
                layer=layer,
            )

        checks = e2e_results.get(check_key, {})

        if item_id not in checks:
            return GapCheckResult(
                item_id=item_id,
                story_id=story_id,
                status="SKIP",
                message=f"E2E結果に {item_id} が存在しない ({check_key})",
                layer=layer,
            )

        passed = checks[item_id]
        if passed:
            return GapCheckResult(
                item_id=item_id,
                story_id=story_id,
                status="PASS",
                message="E2Eテスト合格",
                layer=layer,
            )
        else:
            return GapCheckResult(
                item_id=item_id,
                story_id=story_id,
                status="FAIL",
                message=f"E2Eテスト不合格 ({check_key})",
                layer=layer,
            )

    def generate_gap_matrix(self) -> str:
        """Markdown形式のギャップマトリクス表を生成"""
        lines = [
            "# UXストーリー × E2E ギャップマトリクス",
            "",
            "| ストーリーID | ストーリー名 | L1 | L2 | L3 | L4 | L5 | 合計 |",
            "|---|---|---|---|---|---|---|---|",
        ]

        for story in self.stories:
            story_id = story["ux_id"]
            story_name = story.get("name", "")
            items = story.get("verification_items", [])

            # レイヤー別集計
            layer_counts: Dict[int, int] = {}
            for item in items:
                layer = item.get("layer", 0)
                layer_counts[layer] = layer_counts.get(layer, 0) + 1

            total = len(items)
            l1 = layer_counts.get(1, 0)
            l2 = layer_counts.get(2, 0)
            l3 = layer_counts.get(3, 0)
            l4 = layer_counts.get(4, 0)
            l5 = layer_counts.get(5, 0)

            lines.append(
                f"| {story_id} | {story_name} | {l1} | {l2} | {l3} | {l4} | {l5} | {total} |"
            )

        return "\n".join(lines)

    def get_story_summary(self) -> List[dict]:
        """全ストーリーのサマリリストを返す

        Returns:
            list[dict]: 各要素に id, name, total_items, pass_count, fail_count, completion_rate
        """
        summaries = []
        for story in self.stories:
            story_id = story["ux_id"]
            story_name = story.get("name", "")
            items = story.get("verification_items", [])
            total = len(items)

            summaries.append({
                "id": story_id,
                "name": story_name,
                "total_items": total,
                "pass_count": 0,
                "fail_count": 0,
                "completion_rate": 0.0,
            })

        return summaries
