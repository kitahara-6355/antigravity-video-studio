"""
UXストーリー連動率分析

各検証項目がUXストーリーのどのシーン(文)に紐付くかを計算し、
連動率 ≥ 85% を保証する。
"""
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

STORIES_DIR = Path(__file__).parent / "stories"


@dataclass
class StoryScene:
    """UXストーリーの1シーン"""
    id: str             # "S1"
    text: str           # "OwnerはWhisperモデルを選択できる"
    linked_items: List[str] = None  # ["O2-L1-01", "O2-L3-01"]

    def __post_init__(self):
        if self.linked_items is None:
            self.linked_items = []


@dataclass
class CorrelationResult:
    """連動率分析結果"""
    ux_story: str
    total_items: int
    correlated_items: int
    uncorrelated_items: int
    correlation_rate: float   # 0.0 - 100.0
    total_scenes: int
    covered_scenes: int
    scene_coverage: float     # 0.0 - 100.0
    uncovered_scene_ids: List[str] = None
    uncorrelated_item_ids: List[str] = None

    def __post_init__(self):
        if self.uncovered_scene_ids is None:
            self.uncovered_scene_ids = []
        if self.uncorrelated_item_ids is None:
            self.uncorrelated_item_ids = []


class CorrelationAnalyzer:
    """UXストーリーと検証項目の連動率を分析"""

    def __init__(self, stories_dir: Optional[Path] = None):
        self.stories_dir = stories_dir or STORIES_DIR

    def load_story(self, ux_id: str) -> Optional[Dict]:
        """UXストーリー定義をロード (例: O-2 → o2_transcription.json)"""
        if not isinstance(ux_id, str):
            logger.warning(f"Invalid ux_id type in load_story (expected str): {type(ux_id)}")
            return None
        # ID正規化: O-2 → o2, O-10 → o10
        normalized = ux_id.lower().replace("-", "")
        # パストラバーサルやワイルドカードを防ぐため、英数字のみに限定
        if not normalized.isalnum():
            return None

        try:
            for path in self.stories_dir.glob(f"{normalized}_*.json"):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        return json.load(f)
                except (json.JSONDecodeError, OSError) as e:
                    logger.error(f"Failed to load or parse story file at {path}: {e}")
        except OSError as e:
            logger.error(f"Error scanning stories directory {self.stories_dir}: {e}")
        return None

    def analyze(self, ux_id: str, items: List[Dict]) -> CorrelationResult:
        """
        UXストーリーと検証項目の連動率を計算

        Args:
            ux_id: UXストーリーID (例: "O-2")
            items: 検証項目のリスト (各項目に story_scene キーが必要)

        Returns:
            CorrelationResult
        """
        if not isinstance(ux_id, str):
            logger.warning(f"Invalid ux_id type in analyze (expected str): {type(ux_id)}")
        story_data = self.load_story(ux_id)

        # ストーリーのシーンID一覧
        scenes: List[StoryScene] = []
        if isinstance(story_data, dict):
            scenes_list = story_data.get("scenes")
            if isinstance(scenes_list, list):
                for s in scenes_list:
                    if isinstance(s, dict) and "id" in s and "text" in s:
                        scenes.append(StoryScene(
                            id=str(s["id"]),
                            text=str(s["text"]),
                            linked_items=s.get("linked_items", []),
                        ))
                    else:
                        logger.warning(f"Invalid scene format in story data for {ux_id}: {s}")
            else:
                if scenes_list is not None:
                    logger.warning(f"scenes is not a list in story data for {ux_id}: {scenes_list}")
        elif story_data is not None:
            logger.warning(f"story_data is not a dict for {ux_id}: {story_data}")

        # 検証項目の連動チェックを1回のループに統合
        ux_items = []
        correlated = []
        uncorrelated = []
        if isinstance(items, list):
            for i in items:
                if not isinstance(i, dict):
                    logger.warning(f"Invalid item format in analyze (expected dict): {i}")
                    continue
                if i.get("ux_story") == ux_id:
                    ux_items.append(i)
                    if i.get("story_scene"):
                        correlated.append(i)
                    else:
                        uncorrelated.append(i)
        else:
            logger.warning(f"items is not a list: {items}")

        total = len(ux_items)
        corr_count = len(correlated)
        corr_rate = round(corr_count / max(total, 1) * 100, 2)

        # シーンカバレッジ (集合演算でシンプル化)
        scene_ids = {s.id for s in scenes}
        covered_scene_ids = {i.get("story_scene", "") for i in correlated if isinstance(i, dict)} & scene_ids
        uncovered = scene_ids - covered_scene_ids

        return CorrelationResult(
            ux_story=ux_id,
            total_items=total,
            correlated_items=corr_count,
            uncorrelated_items=len(uncorrelated),
            correlation_rate=corr_rate,
            total_scenes=len(scenes),
            covered_scenes=len(covered_scene_ids),
            scene_coverage=round(len(covered_scene_ids) / max(len(scenes), 1) * 100, 2),
            uncovered_scene_ids=sorted(uncovered),
            uncorrelated_item_ids=[i.get("id", "") for i in uncorrelated if isinstance(i, dict)],
        )

    def analyze_all(self, items: List[Dict]) -> Dict[str, CorrelationResult]:
        """全UXストーリーの連動率を一括分析"""
        if not isinstance(items, list):
            logger.warning(f"items is not a list in analyze_all: {items}")
            return {}
        
        valid_items = []
        for i in items:
            if isinstance(i, dict):
                valid_items.append(i)
            else:
                logger.warning(f"Invalid item format in analyze_all (expected dict): {i}")

        ux_ids = sorted(set(i.get("ux_story", "") for i in valid_items if i.get("ux_story") and isinstance(i.get("ux_story"), str)))
        results = {}
        for ux_id in ux_ids:
            results[ux_id] = self.analyze(ux_id, items)
        return results

    def validate_minimum_correlation(
        self, items: List[Dict], minimum: float = 85.0
    ) -> tuple:
        """
        全UXストーリーの連動率が最低基準を満たすか検証

        Returns:
            (passed: bool, violations: List[str])
        """
        if not isinstance(minimum, (int, float)):
            raise TypeError(f"minimum must be a number (got {type(minimum)})")
        if not (0.0 <= minimum <= 100.0):
            raise ValueError(f"minimum must be between 0.0 and 100.0 (got {minimum})")

        results = self.analyze_all(items)
        violations = []
        for ux_id, result in results.items():
            if result.correlation_rate < minimum:
                violations.append(
                    f"{ux_id}: 連動率 {result.correlation_rate}% < {minimum}% "
                    f"(未連動: {result.uncorrelated_item_ids})"
                )
        return (len(violations) == 0, violations)
