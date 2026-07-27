import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

from safe_io import SafeJsonStore, BRANDING_DIR
from PIL import Image, ImageDraw
import uuid

logger = logging.getLogger(__name__)

SERIES_REGISTRY_FILE = BRANDING_DIR / "series_registry.json"

class SeriesPlanner:
    """
    [Phase 4: Series Planner]
    動画のシリーズ管理、セッション継続のための次回予告提案、
    プレイリスト最適化を担当するサービス。
    （Strategistエージェントの役割を兼ねる）
    """
    def __init__(self):
        self._store = SafeJsonStore(
            SERIES_REGISTRY_FILE,
            default={"version": "1.0", "description": "YouTube Series and Continuity Registry", "series": {}}
        )
        self.series_data = self._load()

    def _load(self) -> Dict[str, Any]:
        return self._store.load()

    def _save(self):
        self._store.save(self.series_data)

    def register_series(self, series_id: str, title: str, theme: str, target_persona: str = "All") -> Dict[str, Any]:
        """[4.1 Series Registry] シリーズを新規登録する"""
        # Fix①: 各メソッド実行時にファイルから最新データを再読込（キャッシュ陳腐化防止）
        self.series_data = self._load()

        if "series" not in self.series_data:
            self.series_data["series"] = {}

        if series_id in self.series_data["series"]:
            logger.warning(f"⚠️ [Series Planner] シリーズ '{series_id}' はすでに登録されています。")
            return self.series_data["series"][series_id]

        new_series = {
            "title": title,
            "theme": theme,
            "target_persona": target_persona,
            "created_at": datetime.now().isoformat(),
            "videos": [],
            "playlist_url": ""
        }
        self.series_data["series"][series_id] = new_series
        self._save()
        logger.info(f"📚 [Series Planner] シリーズ登録完了: {series_id} ({title})")
        return new_series

    def add_video_to_series(self, series_id: str, video_id: str, video_title: str) -> bool:
        """指定したシリーズに動画を追加する"""
        # Fix①: キャッシュ陳腐化防止
        self.series_data = self._load()

        series = self.series_data.get("series", {}).get(series_id)
        if not series:
            logger.error(f"❌ [Series Planner] シリーズ '{series_id}' が見つかりません。")
            return False

        # 重複チェック
        for v in series["videos"]:
            if v["video_id"] == video_id:
                logger.info(f"ℹ️ [Series Planner] 動画 {video_id} はすでに {series_id} に登録済みです。")
                return True

        series["videos"].append({
            "video_id": video_id,
            "title": video_title,
            "added_at": datetime.now().isoformat()
        })
        self._save()
        logger.info(f"🔗 [Series Planner] 動画 {video_id} をシリーズ {series_id} に追加しました。")
        return True

    def suggest_next_video(self, series_id: str, current_video_id: str, current_context: str) -> Dict[str, Any]:
        """
        [4.2 Next-Video Suggester]
        現在制作中の動画の末尾に挿入するべき、次回予告やCall to Action (CTA) を提案する。
        ※ 動画のシリーズへの追加は別途 add_video_to_series を呼ぶこと（副作用の分離）。
        """
        # Fix①: キャッシュ陳腐化防止
        self.series_data = self._load()

        series = self.series_data.get("series", {}).get(series_id)
        if not series:
            return {
                "success": False,
                "message": f"シリーズ '{series_id}' が見つかりません。",
                "teaser_text": "チャンネル登録と高評価をお願いします！"  # フォールバックCTA
            }

        theme = series.get("theme", "不明なテーマ")
        
        # Prevention 2: モックであることを明示する
        logger.warning("[STUB] Next-Video Suggester は現在モック生成です。将来的にStrategist/LLMと統合予定。")
        
        teaser_text = (
            f"次回は、この「{theme}」についてさらに深掘りします！\n"
            "今回の内容を踏まえ、より実践的なテクニックを公開予定です。\n"
            "見逃さないように、チャンネル登録をチェックしてお待ちください！"
        )
        
        cta_suggestion = {
            "visual_recommendation": "画面右側に次回作を暗示するモザイク画像やシルエットを表示",
            "audio_recommendation": "フェードアウト直前に「次回」を予感させるSE（ブシュッ、シャキーン等）を挿入"
        }

        logger.info(f"💡 [Series Planner] 次回予告を生成しました: {current_video_id} (シリーズ: {series_id})")
        
        return {
            "success": True,
            "series_id": series_id,
            "current_video_id": current_video_id,
            "teaser_text": teaser_text,
            "cta_suggestion": cta_suggestion
        }

    def optimize_playlist(self, series_id: str) -> Dict[str, Any]:
        """
        [4.3 Playlist Optimizer]
        シリーズ内の全動画を分析し、最適な再生順序や終了画面（End-Screen）の推奨を生成する。
        """
        # Fix①: キャッシュ陳腐化防止
        self.series_data = self._load()

        series = self.series_data.get("series", {}).get(series_id)
        if not series:
            return {"success": False, "message": f"シリーズ '{series_id}' が見つかりません。"}

        videos = series.get("videos", [])
        
        if len(videos) == 0:
            return {"success": False, "message": "このシリーズにはまだ動画が登録されていません。"}

        if len(videos) == 1:
            return {
                "success": True,
                "overall_message": "これはシリーズ第一作目です。次回作公開後に再生リストが最適化されます。",
                "end_screen_recommendation": "チャンネル登録ボタン ＋ 最新のアップロード動画"
            }

        first_video = videos[0]  # Fix⑤: latest_video（未使用変数）を削除し、first_videoのみ残す
        
        if len(videos) >= 3:
            recommendation = f"左: シリーズ第1回('{first_video['title']}')の復習 / 右: チャンネル登録"
        else:
            recommendation = "左: 前回の動画 / 右: チャンネル登録"

        logger.info(f"🔄 [Series Planner] プレイリスト最適化完了: {series_id} ({len(videos)}本)")

        return {
            "success": True,
            "series_id": series_id,
            "video_count": len(videos),
            "suggested_order": [v["video_id"] for v in videos],
            "end_screen_recommendation": recommendation,
            "playlist_note": "新規視聴者は第1回から、既存視聴者は最新回から再生されるようにリストURLを分けて共有することを推奨します。"
        }

    def generate_series_thumbnail(
        self,
        output_path,
        width: int = 1280,
        height: int = 720,
        text: str = "Series Thumbnail"
    ):
        """Pillowを使用して、指定された解像度とテキストでサムネイル画像を生成する"""
        try:
            width = int(width)
            height = int(height)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Width and height must be integers: {e}")
            
        if width <= 0 or height <= 0:
            raise ValueError(f"Width and height must be positive integers. Got {width}x{height}")
            
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 原子的な書き込み
        temp_path = output_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        try:
            img = Image.new("RGB", (width, height), color=(73, 109, 137))
            d = ImageDraw.Draw(img)
            d.text((10, 10), text, fill=(255, 255, 0))
            img.save(temp_path, "PNG")
            
            if output_path.exists():
                output_path.unlink()
            temp_path.rename(output_path)
        except Exception as e:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            logger.error(f"Failed to generate series thumbnail atomically: {e}")
            raise
            
        return output_path

    def validate_thumbnail_quality(self, file_path) -> dict:
        """サムネイル画像の品質要件を検証する"""
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Thumbnail file not found: {file_path}")
            
        size_bytes = file_path.stat().st_size
        if size_bytes >= 4 * 1024 * 1024:
            raise ValueError(f"File size exceeds 4MB limit: {size_bytes} bytes")
            
        try:
            with Image.open(file_path) as img:
                img.verify()
        except Exception as e:
            raise ValueError(f"Image is corrupted or invalid format: {e}")
            
        try:
            with Image.open(file_path) as img:
                img.load()
                width, height = img.size
        except Exception as e:
            raise ValueError(f"Image is corrupted or invalid format: {e}")
            
        if width < 1280 or height < 720:
            raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
            
        aspect_ratio = width / height
        target_ratio = 16.0 / 9.0
        if abs(aspect_ratio - target_ratio) > 0.01:
            raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}")
            
        return {
            "path": str(file_path),
            "width": width,
            "height": height,
            "size_bytes": size_bytes
        }

    async def resolve_series_thumbnail_task(self, task_id: str) -> str:
        """StageBoundAgent の process_func として動作する非同期タスク処理"""
        import json
        output_dir = Path(getattr(self, "output_dir", None) or "backend/temp_thumbnails")
        output_path = output_dir / f"{task_id}.png"
        
        width = getattr(self, "width", 1280)
        height = getattr(self, "height", 720)
        text = getattr(self, "text", "Series Thumbnail")
        
        self.generate_series_thumbnail(output_path, width=width, height=height, text=text)
        result_info = self.validate_thumbnail_quality(output_path)
        return json.dumps(result_info)


# Singleton
series_planner = SeriesPlanner()
