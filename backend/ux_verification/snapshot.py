"""UX検証スナップショット管理

検証状態のスナップショットを保存・ロードし、
ラチェット機構の比較元として使用する。

架空データ防御:
- PASS率100%かつ500項目超のスナップショットは自動拒否
- quarantined/ ディレクトリ内のファイルは自動除外
"""
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from packaging.version import Version, InvalidVersion

logger = logging.getLogger(__name__)

SNAPSHOTS_DIR = Path(__file__).parent / "snapshots"
QUARANTINED_DIR = SNAPSHOTS_DIR / "quarantined"

# 架空データ検出閾値
_FAKE_DATA_MIN_ITEMS = 500
_FAKE_DATA_PASS_RATE = 99.0


@dataclass
class VerificationItem:
    """個別の検証項目"""
    id: str = ""                   # "O2-L1-01"
    ux_story: str = ""             # "O-2"
    layer: int = 0                 # 1-5
    description: str = ""          # "Whisperモデルセレクトボックスが存在する"
    story_scene: str = ""          # "S1" — 紐付くUXストーリーのシーンID
    test_method: str = ""          # "dom_exists" / "visual_check" / "interaction" / "state_transition" / "e2e"
    passed: Optional[bool] = None
    evidence: str = ""

    def __post_init__(self):
        if self.layer is None:
            self.layer = 0

    def get(self, key: str, default=None):
        return getattr(self, key, default)

    def __getitem__(self, key: str):
        if not hasattr(self, key):
            raise KeyError(key)
        return getattr(self, key)

    def __contains__(self, key: str):
        return hasattr(self, key)


@dataclass
class UXVerificationSnapshot:
    """UX検証スナップショット — ある時点での検証状態を不変に記録"""
    version: str
    timestamp: str = ""
    items: List[VerificationItem] = field(default_factory=list)

    # 集計値（items から自動算出）
    total_items: int = 0
    pass_items: int = 0
    fail_items: int = 0
    skip_items: int = 0
    fulfillment_rate: float = 0.0
    correlation_rate: float = 0.0
    story_scenes_total: int = 0
    story_scenes_covered: int = 0

    # UXストーリー別の内訳
    items_per_story: Dict[str, int] = field(default_factory=dict)
    pass_per_story: Dict[str, int] = field(default_factory=dict)
    layer_distribution: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        new_items = []
        for item in self.items:
            if isinstance(item, dict):
                fields = VerificationItem.__dataclass_fields__
                filtered_item = {}
                for k, v in item.items():
                    if k in fields:
                        filtered_item[k] = v
                if filtered_item.get("layer") is None:
                    filtered_item["layer"] = 0
                new_items.append(VerificationItem(**filtered_item))
            elif isinstance(item, VerificationItem):
                if item.layer is None:
                    item.layer = 0
                new_items.append(item)
            else:
                raise TypeError(f"Invalid item type: {type(item)}")
        self.items = new_items

    def compute_aggregates(self):
        """items リストから集計値を再計算"""
        self.total_items = len(self.items)
        self.pass_items = sum(1 for i in self.items if i.get("passed") is True)
        self.fail_items = sum(1 for i in self.items if i.get("passed") is False)
        self.skip_items = sum(1 for i in self.items if i.get("passed") is None)

        if self.total_items > 0:
            self.fulfillment_rate = round(self.pass_items / self.total_items * 100, 2)
        else:
            self.fulfillment_rate = 0.0

        # 連動率: story_scene が空でない項目の割合
        correlated = sum(1 for i in self.items if i.get("story_scene", ""))
        self.correlation_rate = round(correlated / max(self.total_items, 1) * 100, 2)

        # UXストーリー別集計
        self.items_per_story = {}
        self.pass_per_story = {}
        for item in self.items:
            ux = item.get("ux_story", "unknown") or "unknown"
            self.items_per_story[ux] = self.items_per_story.get(ux, 0) + 1
            if item.get("passed") is True:
                self.pass_per_story[ux] = self.pass_per_story.get(ux, 0) + 1

        # レイヤー分布
        self.layer_distribution = {}
        for item in self.items:
            layer_val = item.get("layer", 0)
            if layer_val is None:
                layer_val = 0
            layer = f"L{layer_val}"
            self.layer_distribution[layer] = self.layer_distribution.get(layer, 0) + 1

        # ストーリーシーンカバレッジ
        all_scenes = set()
        covered_scenes = set()
        for item in self.items:
            scene = item.get("story_scene", "")
            if scene:
                key = f"{item.get('ux_story', '') or ''}:{scene}"
                all_scenes.add(key)
                if item.get("passed") is True:
                    covered_scenes.add(key)
        self.story_scenes_total = len(all_scenes)
        self.story_scenes_covered = len(covered_scenes)


def _get_version_key(version_str: str) -> Version:
    """バージョン文字列をVersionオブジェクトに変換してソートキーとする"""
    clean_str = version_str.lstrip("v")
    try:
        return Version(clean_str)
    except InvalidVersion:
        return Version("0.0.0")


class SnapshotStore:
    """スナップショットの永続化"""

    def __init__(self, snapshots_dir: Optional[Path] = None):
        self.dir = snapshots_dir or SNAPSHOTS_DIR
        self.dir.mkdir(parents=True, exist_ok=True)

    def save(self, snapshot: UXVerificationSnapshot) -> Path:
        """スナップショットを保存"""
        if not snapshot.timestamp:
            snapshot.timestamp = datetime.now().isoformat()
        snapshot.compute_aggregates()
        
        # --- F-3: 架空データ・隔離保存ガード ---
        if self._is_fake_data(snapshot):
            raise ValueError(
                f"Cannot save fake snapshot (PASS rate >= 99% & items > 500): "
                f"{snapshot.pass_items}/{snapshot.total_items} passed ({snapshot.fulfillment_rate}%)"
            )
            
        # --- Σ-5d: 証拠なしPASS禁止ガード ---
        for item in snapshot.items:
            passed = item.get("passed") if isinstance(item, dict) else getattr(item, "passed", None)
            evidence = item.get("evidence") if isinstance(item, dict) else getattr(item, "evidence", "")
            if passed is True and (not evidence or len(str(evidence).strip()) < 5):
                item_id = item.get("id") if isinstance(item, dict) else getattr(item, "id", "")
                story = item.get("ux_story") if isinstance(item, dict) else getattr(item, "ux_story", "")
                raise ValueError(
                    f"Item {item_id} in story {story} is marked as passed but lacks valid evidence (空エビデンスでのPASSは禁止です)."
                )
        path = self.dir / f"{snapshot.version}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(snapshot), f, ensure_ascii=False, indent=2)
        logger.info(f"UXスナップショット保存: {path.name} ({snapshot.total_items}項目)")
        return path

    def load(self, version: str) -> Optional[UXVerificationSnapshot]:
        """バージョン指定でスナップショットをロード（架空データガード付き）"""
        path = self.dir / f"{version}.json"
        if not path.exists():
            return None
        if self._is_quarantined(path):
            logger.warning(f"🚫 隔離済みスナップショットを拒否: {path.name}")
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        snapshot = UXVerificationSnapshot(**{
            k: v for k, v in data.items()
            if k in UXVerificationSnapshot.__dataclass_fields__
        })
        if self._is_fake_data(snapshot):
            logger.warning(
                f"🚫 架空データ検出・自動拒否: {path.name} "
                f"(PASS率100%, {snapshot.total_items}項目 > {_FAKE_DATA_MIN_ITEMS})"
            )
            return None
        return snapshot

    def load_latest(self) -> Optional[UXVerificationSnapshot]:
        """最新のスナップショットをロード（架空データ・隔離ファイル自動除外）"""
        files = self._list_valid_files()
        if not files:
            return None
        files = sorted(files, key=lambda f: _get_version_key(f.stem), reverse=True)
        for f_path in files:
            with open(f_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            snapshot = UXVerificationSnapshot(**{
                k: v for k, v in data.items()
                if k in UXVerificationSnapshot.__dataclass_fields__
            })
            if not self._is_fake_data(snapshot):
                return snapshot
            logger.warning(
                f"🚫 架空データ検出・スキップ: {f_path.name} "
                f"(PASS率100%, {snapshot.total_items}項目)"
            )
        return None

    def list_versions(self) -> List[str]:
        """保存済みバージョン一覧（隔離ファイル除外）"""
        versions = [f.stem for f in self._list_valid_files()]
        return sorted(versions, key=_get_version_key)

    def _list_valid_files(self) -> List[Path]:
        """quarantined/ を除外したスナップショットファイル一覧"""
        return [
            f for f in self.dir.glob("v*.json")
            if not self._is_quarantined(f)
        ]

    @staticmethod
    def _is_quarantined(path: Path) -> bool:
        """ファイルがquarantinedディレクトリ内にあるかチェック"""
        return "quarantined" in path.parts

    @staticmethod
    def _is_fake_data(snapshot: UXVerificationSnapshot) -> bool:
        """架空データ判定: PASS率100%かつ項目数500超"""
        snapshot.compute_aggregates()
        if snapshot.total_items <= _FAKE_DATA_MIN_ITEMS:
            return False
        return snapshot.fulfillment_rate >= _FAKE_DATA_PASS_RATE
