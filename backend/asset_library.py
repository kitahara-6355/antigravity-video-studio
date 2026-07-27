"""
Creative Asset Library
Phase 4: Asset Management（ベース）
Phase 5: Semantic Archive Search（拡張）

機能:
- 素材の自動インデックス化
- AI自動ラベリング（Vision API）
- 参照透明性レポート
- 素材充足度チェック
- セマンティック検索（tag_for_search / search_assets / build_search_index）
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime
import hashlib

from google import genai
from dotenv import load_dotenv
import os

from model_registry import get_model

load_dotenv()
logger = logging.getLogger(__name__)

# デフォルトのアセットルート
ASSET_ROOT = Path(__file__).parent.parent / "assets"

# HEXカラーコード → 色名の簡易マッピング（セマンティック検索用）
_COLOR_NAME_MAP = {
    "ff": "赤",    "ee": "赤",    "dd": "赤",
    "00ff": "緑",  "00ee": "緑",  "008000": "緑",
    "0000ff": "青", "0000ee": "青",
    "ffff00": "黄", "ffa500": "オレンジ",
    "800080": "紫", "ff00ff": "マゼンタ",
    "ffffff": "白", "000000": "黒",
    "808080": "グレー", "c0c0c0": "シルバー",
    "a52a2a": "茶", "ffd700": "ゴールド",
}

def _hex_to_color_name(hex_code: str) -> str:
    """HEXカラーコードを色名に変換する（簡易マッピング）"""
    h = hex_code.lstrip("#").lower()
    # 前方一致で最もよく合うものを探す
    for key, name in _COLOR_NAME_MAP.items():
        if h.startswith(key) or h == key:
            return name
    # 明度推定で暖色/寒色を判定（R > B なら暖色）
    try:
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
        brightness = (r + g + b) / 3
        if r > b + 30:
            return "暖色系"
        elif b > r + 30:
            return "寒色系"
        elif brightness > 200:
            return "明るい色"
        elif brightness < 60:
            return "暗い色"
    except (ValueError, IndexError):
        pass
    return ""


@dataclass
class AssetEntry:
    """アセットエントリ"""
    id: str
    path: str
    filename: str
    type: str  # photo, video, logo, text, template, audio
    category: str  # channel_owner, guest, brand, template
    labels: List[str] = field(default_factory=list)
    style_tags: List[str] = field(default_factory=list)
    colors: List[str] = field(default_factory=list)
    mood: str = "neutral"
    usage_for: List[str] = field(default_factory=list)
    usage_count: int = 0
    file_hash: str = ""
    indexed_at: str = field(default_factory=lambda: datetime.now().isoformat())
    # NOTE: embeddingはvector_index.jsonで管理する。AssetEntryには保持しない。


@dataclass
class GuestProfile:
    """ゲストプロファイル"""
    id: str
    name: str
    title: str
    specialty: str = ""
    bio: str = ""
    folder_path: str = ""


class CreativeAssetLibrary:
    """クリエイティブ資産ライブラリ"""

    LABELING_PROMPT = """
この画像を分析し、以下の情報を抽出してください。

## 分析項目
1. **type**: 画像の種類（portrait, work, activity, logo, product, scene）
2. **labels**: 内容を表すラベル（複数可）
3. **style_tags**: スタイルタグ（formal, casual, artistic, professional, etc.）
4. **colors**: 主要な色（HEXコード）
5. **mood**: 雰囲気（professional, creative, warm, cool, energetic, calm）
6. **usage_for**: 適した用途（thumbnail, profile, insert, opening, etc.）

## 出力形式（JSON）
{
  "type": "portrait",
  "labels": ["人物", "書道家", "和装"],
  "style_tags": ["formal", "artistic"],
  "colors": ["#1A1A1A", "#8B5CF6"],
  "mood": "professional",
  "usage_for": ["thumbnail", "profile"]
}
"""

    def __init__(self, asset_root: Path = ASSET_ROOT):
        self.asset_root = Path(asset_root)
        self.index_path = self.asset_root / "asset_index.json"
        self.assets: List[AssetEntry] = []
        self.guests: Dict[str, GuestProfile] = {}

        from gemini_client_factory import get_gemini_client
        self.client = get_gemini_client()
        self.model = get_model("quality_gate")  # Vision対応モデル

        self._ensure_structure()
        self._load_index()

    def _ensure_structure(self):
        """フォルダ構造を確保"""
        folders = [
            self.asset_root / "channel_owner" / "photos",
            self.asset_root / "channel_owner" / "videos",
            self.asset_root / "channel_owner" / "logos",
            self.asset_root / "guests",
            self.asset_root / "templates",
            self.asset_root / "brand" / "fonts",
            self.asset_root / "brand" / "music",
        ]
        for folder in folders:
            folder.mkdir(parents=True, exist_ok=True)

        readme_path = self.asset_root / "README.md"
        if not readme_path.exists():
            readme_path.write_text("""# Creative Asset Library

## フォルダ構造

```
assets/
├── channel_owner/     ← チャンネル主の素材
│   ├── photos/        ← 写真
│   ├── videos/        ← 動画クリップ
│   └── logos/         ← ロゴ
├── guests/            ← ゲストの素材
│   └── [ゲスト名]/
│       ├── profile.json
│       ├── photos/
│       └── works/
├── templates/         ← テンプレート
│   ├── opening.mp4
│   └── ending.mp4
└── brand/             ← ブランド素材
    ├── fonts/
    └── music/
```

## 使い方

1. 素材をフォルダにドロップ
2. システムが自動でインデックス化
3. 生成時に自動参照
""", encoding="utf-8")

    def _load_index(self):
        """インデックスを読み込み"""
        if self.index_path.exists():
            try:
                with open(self.index_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                assets_raw = data.get("assets", [])
                self.assets = []
                for a in assets_raw:
                    # Phase 5以前のデータに embedding フィールドが残っていても安全に処理
                    a.pop("embedding", None)
                    self.assets.append(AssetEntry(**a))
                self.guests = {
                    k: GuestProfile(**v) for k, v in data.get("guests", {}).items()
                }
                logger.info(f"アセットインデックス読み込み: {len(self.assets)}件")
            except (json.JSONDecodeError, TypeError, KeyError, AttributeError, OSError) as e:
                logger.error(f"インデックス読み込みエラー: {e}")
                try:
                    backup_path = self.index_path.with_suffix(".corrupted")
                    self.index_path.replace(backup_path)
                    logger.warning(f"破損したインデックスをバックアップしました: {backup_path}")
                except OSError as backup_err:
                    logger.error(f"破損インデックスのバックアップ失敗: {backup_err}")
                self.assets = []
                self.guests = {}

    def _save_index(self):
        """インデックスを保存"""
        data = {
            "version": "2.0",
            "last_scan": datetime.now().isoformat(),
            "assets": [asdict(a) for a in self.assets],
            "guests": {k: asdict(v) for k, v in self.guests.items()}
        }
        tmp_path = self.index_path.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            tmp_path.replace(self.index_path)
            logger.info(f"アセットインデックス保存: {len(self.assets)}件")
        except OSError as e:
            logger.error(f"インデックスの保存に失敗しました: {e}")
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            raise

    def _get_file_hash(self, path: Path) -> str:
        """ファイルハッシュを取得"""
        with open(path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()

    def scan(self, auto_label: bool = True) -> Dict:
        """
        フォルダをスキャンしてインデックス化

        Args:
            auto_label: AIラベリングを行うか

        Returns:
            スキャン結果サマリー
        """
        new_assets = []
        updated_assets = []

        existing_hashes = {a.file_hash: a for a in self.assets}

        # サポートする拡張子（音声ファイルも含める）
        image_exts = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
        video_exts = {".mp4", ".mov", ".avi", ".webm"}
        audio_exts = {".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg"}

        for path in self.asset_root.rglob("*"):
            ext = path.suffix.lower()
            if path.is_file() and ext in image_exts | video_exts | audio_exts:
                try:
                    file_hash = self._get_file_hash(path)
                except OSError as e:
                    logger.error(f"ファイルハッシュの取得に失敗しました ({path}): {e}")
                    continue

                if file_hash in existing_hashes:
                    continue

                rel_path = path.relative_to(self.asset_root)
                parts = rel_path.parts

                if "channel_owner" in parts:
                    category = "channel_owner"
                elif "guests" in parts:
                    category = "guest"
                elif "templates" in parts:
                    category = "template"
                elif "brand" in parts:
                    category = "brand"
                else:
                    category = "other"

                if ext in image_exts:
                    asset_type = "photo"
                elif ext in video_exts:
                    asset_type = "video"
                else:
                    asset_type = "audio"

                entry = AssetEntry(
                    id=f"asset_{len(self.assets) + len(new_assets):04d}",
                    path=str(rel_path),
                    filename=path.name,
                    type=asset_type,
                    category=category,
                    file_hash=file_hash
                )

                if auto_label and asset_type == "photo":
                    labels = self._label_asset(path)
                    if labels:
                        entry.labels = labels.get("labels", [])
                        entry.style_tags = labels.get("style_tags", [])
                        entry.colors = labels.get("colors", [])
                        entry.mood = labels.get("mood", "neutral")
                        entry.usage_for = labels.get("usage_for", [])

                new_assets.append(entry)

        self.assets.extend(new_assets)
        self._save_index()

        return {
            "new_assets": len(new_assets),
            "total_assets": len(self.assets),
            "updated_assets": len(updated_assets)
        }

    def _label_asset(self, path: Path) -> Optional[Dict]:
        """AIでアセットをラベリング"""
        try:
            logger.info(f"ラベリング: {path.name}")

            # フォールバック: パスベースのラベリング
            labels = []
            stem = path.stem.lower()
            if "portrait" in stem or "profile" in stem:
                labels = ["portrait", "人物"]
            elif "logo" in stem:
                labels = ["logo"]
            elif "work" in stem:
                labels = ["work", "作品"]
            elif "opening" in stem:
                labels = ["opening"]
            elif "ending" in stem:
                labels = ["ending"]

            return {
                "labels": labels,
                "style_tags": [],
                "colors": [],
                "mood": "neutral",
                "usage_for": ["thumbnail"] if "portrait" in labels else []
            }
        except (AttributeError, TypeError) as e:
            logger.error(f"ラベリングエラー: {e}")
            return None

    def get_assets_for_task(self, task_type: str, context: Dict = None) -> Dict:
        """
        タスクに必要なアセットを取得（ルールベース）

        Args:
            task_type: thumbnail, opening, insert, etc.
            context: コンテキスト情報

        Returns:
            {
                "available": [...],
                "recommended": [...],
                "missing": [...]
            }
        """
        available = []
        recommended = []
        missing = []

        requirements = {
            "thumbnail": ["portrait", "logo"],
            "opening": ["logo", "template"],
            "insert": ["work", "activity"],
            "ending": ["logo", "template"]
        }

        required_types = requirements.get(task_type, [])

        for asset in self.assets:
            if task_type in asset.usage_for:
                recommended.append(asdict(asset))
            elif any(t in asset.labels for t in required_types):
                available.append(asdict(asset))

        available_labels = set()
        for a in self.assets:
            available_labels.update(a.labels)

        for req in required_types:
            if req not in available_labels:
                missing.append({
                    "type": req,
                    "suggestion": f"{req}素材を追加すると{task_type}の品質が向上します"
                })

        return {
            "available": available,
            "recommended": recommended,
            "missing": missing
        }

    def get_usage_report(self, referenced_assets: List[str]) -> Dict:
        """参照透明性レポートを生成"""
        referenced = []
        for asset_id in referenced_assets:
            asset = next((a for a in self.assets if a.id == asset_id), None)
            if asset:
                asset.usage_count += 1
                referenced.append(asdict(asset))

        self._save_index()

        return {
            "referenced_assets": referenced,
            "total_referenced": len(referenced)
        }

    def get_sufficiency_report(self) -> Dict:
        """素材充足度レポートを生成"""
        categories = {}
        for asset in self.assets:
            cat = asset.category
            if cat not in categories:
                categories[cat] = {"total": 0, "by_type": {}}
            categories[cat]["total"] += 1

            for label in asset.labels:
                if label not in categories[cat]["by_type"]:
                    categories[cat]["by_type"][label] = 0
                categories[cat]["by_type"][label] += 1

        recommendations = []
        required_types = {
            "channel_owner": ["portrait", "work", "activity", "logo"],
            "guest": ["portrait", "work"],
            "template": ["opening", "ending"]
        }

        for cat, types in required_types.items():
            if cat not in categories:
                recommendations.append({
                    "category": cat,
                    "missing": types,
                    "suggestion": f"{cat}フォルダに素材を追加してください"
                })
            else:
                for t in types:
                    if t not in categories[cat].get("by_type", {}):
                        recommendations.append({
                            "category": cat,
                            "missing": [t],
                            "suggestion": f"{cat}に{t}素材を追加すると品質が向上します"
                        })

        return {
            "categories": categories,
            "total_assets": len(self.assets),
            "recommendations": recommendations
        }

    # ===========================================================================
    # Phase 5: Semantic Archive Search
    # ===========================================================================

    def tag_for_search(self, asset: "AssetEntry", series_theme: str = "") -> str:
        """
        [Phase 5.1: Semantic Tagger]
        AssetEntryの全フィールドを結合し、Embedding生成のためのテキストサマリを作成する。

        改善点（Phase 5 ゼロベース設計）:
        - ファイル名を含める（視覚的に最も認識しやすい情報）
        - colors フィールドを色名に変換して含める（「暖色系」等の検索に対応）
        - series_theme を活用する（P4→P5 統合）

        Args:
            asset: 対象アセット
            series_theme: シリーズテーマ文字列（P4のSeriesPlannerから取得）

        Returns:
            検索用テキストサマリ
        """
        # 色名変換
        color_names = []
        for hex_code in asset.colors:
            name = _hex_to_color_name(hex_code)
            if name:
                color_names.append(name)

        parts = [
            f"ファイル名: {asset.filename}",
            f"種別: {asset.type}",
            f"カテゴリ: {asset.category}",
            f"ラベル: {', '.join(asset.labels)}" if asset.labels else "",
            f"スタイル: {', '.join(asset.style_tags)}" if asset.style_tags else "",
            f"色: {', '.join(color_names)}" if color_names else "",
            f"雰囲気: {asset.mood}" if asset.mood and asset.mood != "neutral" else "",
            f"用途: {', '.join(asset.usage_for)}" if asset.usage_for else "",
            f"シリーズテーマ: {series_theme}" if series_theme else "",
        ]
        return " / ".join(p for p in parts if p)

    def search_assets(self, query: str, top_k: int = 5) -> List[Dict]:
        """
        [Phase 5.4: Asset Library Integration]
        自然言語クエリでAsset Libraryを横断検索する。
        VectorSearchEngineを利用し、コサイン類似度上位top_k件を返す。
        既存の get_assets_for_task（ルールベース）と干渉しない独立したメソッド。
        """
        from services.vector_search import vector_search_engine

        # インデックスが空の場合は自動ビルド
        stats = vector_search_engine.get_index_stats()
        if stats["total_entries"] == 0:
            logger.info("🔧 [Asset Library] インデックスが空のため自動ビルドを実行します。")
            self.build_search_index(force_rebuild=False)

        results = vector_search_engine.search(query=query, top_k=top_k)
        matched = []
        for r in results:
            asset = next((a for a in self.assets if a.id == r.asset_id), None)
            if asset:
                entry = asdict(asset)
                entry["search_score"] = r.score
                entry["search_text_summary"] = r.text_summary
                matched.append(entry)

        logger.info(f"🔎 [Asset Library] 検索完了: '{query[:30]}' → {len(matched)}件")
        return matched

    def build_search_index(self, force_rebuild: bool = False) -> Dict:
        """
        [Phase 5.2: Vector Index Builder]
        全AssetEntryをベクトル化してインデックスを構築する。

        P4→P5 統合: SeriesPlanner のシリーズテーマを取得し、
        対応アセットの tag_for_search に付与する。

        Args:
            force_rebuild: True の場合、既存インデックスを破棄して全件再構築する。
        """
        from services.vector_search import vector_search_engine

        # P4→P5 統合: シリーズテーママップを構築
        series_theme_map: Dict[str, str] = {}
        try:
            from services.series_planner import series_planner
            series_data = series_planner.series_data.get("series", {})
            for series_id, series_info in series_data.items():
                theme = series_info.get("theme", "")
                # シリーズに登録済みの動画IDをキーとしてテーマを紐付け
                for video_entry in series_info.get("videos", []):
                    video_id = video_entry.get("video_id", "")
                    if video_id:
                        series_theme_map[video_id] = theme
        except (ImportError, AttributeError, KeyError, TypeError) as e:
            logger.warning(f"[Asset Library] シリーズテーマ取得をスキップ: {e}")

        asset_texts = []
        for a in self.assets:
            # シリーズテーマ: アセットのファイル名がシリーズ動画IDに含まれていれば付与
            series_theme = ""
            for vid_id, theme in series_theme_map.items():
                if vid_id in a.filename or vid_id in a.path:
                    series_theme = theme
                    break

            asset_texts.append({
                "asset_id": a.id,
                "text": self.tag_for_search(a, series_theme=series_theme),
                "metadata": {
                    "filename": a.filename,
                    "type": a.type,
                    "category": a.category,
                    "mood": a.mood,
                    "path": a.path
                }
            })

        if force_rebuild:
            result = vector_search_engine.rebuild_index(asset_texts)
        else:
            result = vector_search_engine.build_index(asset_texts)

        logger.info(f"📦 [Asset Library] 検索インデックス構築: {result}")
        return result


# シングルトンインスタンス
asset_library = CreativeAssetLibrary()


def scan_assets(auto_label: bool = True) -> Dict:
    """アセットをスキャン（簡易関数）"""
    return asset_library.scan(auto_label)


def get_assets_for(task_type: str, context: Dict = None) -> Dict:
    """タスク用アセットを取得（簡易関数）"""
    return asset_library.get_assets_for_task(task_type, context)
