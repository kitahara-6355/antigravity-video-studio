"""
投稿スケジュール管理サービス（BIZ-6）

週2-3本の安定投稿を支援するための制作カレンダー管理。
- 投稿スケジュールの登録・取得
- 次回期限リマインダー
- 投稿ペース分析
"""
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "branding"
SCHEDULE_FILE = DATA_DIR / "publish_schedule.json"


class PublishScheduler:
    """投稿スケジュール管理"""

    VALID_STATUSES = ["draft", "in_progress", "ready", "published"]

    @property
    def _store(self):
        if not hasattr(self, "_cached_store") or self._cached_store.path != SCHEDULE_FILE:
            from safe_io import SafeJsonStore
            self._cached_store = SafeJsonStore(
                SCHEDULE_FILE,
                default={"schedule": [], "settings": {"target_per_week": 2, "preferred_days": ["水", "土"]}}
            )
        return self._cached_store

    def _load(self) -> dict:
        data = self._store.load()
        
        # JSON構造のバリデーションとフォーマット補正
        if not isinstance(data, dict):
            logger.warning("📅 BIZ-6: Loaded schedule data is not a dictionary. Resetting to default.")
            data = {"schedule": [], "settings": {"target_per_week": 2, "preferred_days": ["水", "土"]}}
            
        if "schedule" not in data or not isinstance(data["schedule"], list):
            data["schedule"] = []
            
        if "settings" not in data or not isinstance(data["settings"], dict):
            data["settings"] = {"target_per_week": 2, "preferred_days": ["水", "土"]}
            
        return data

    def _save(self, data: dict):
        if not isinstance(data, dict):
            raise TypeError("Data to save must be a dictionary")
        self._store.save(data)

    def add_entry(self, title: str, planned_date: str, status: str = "draft") -> dict:
        """投稿予定を追加"""
        if not title or not title.strip():
            raise ValueError("Title cannot be empty")
        
        try:
            datetime.strptime(planned_date, "%Y-%m-%d")
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid planned_date format '{planned_date}', must be YYYY-MM-DD") from e
            
        if status not in self.VALID_STATUSES:
            raise ValueError(f"Invalid status '{status}', must be one of {self.VALID_STATUSES}")

        entry = {
            "id": f"pub_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "title": title,
            "planned_date": planned_date,
            "status": status,  # draft / in_progress / ready / published
            "created_at": datetime.now().isoformat(),
        }

        def updater(data: dict):
            if not isinstance(data, dict):
                data = {"schedule": [], "settings": {"target_per_week": 2, "preferred_days": ["水", "土"]}}
            if "schedule" not in data or not isinstance(data["schedule"], list):
                data["schedule"] = []
            data["schedule"].append(entry)
            return data

        self._store.update(updater)
        logger.info(f"📅 BIZ-6: 投稿予定追加: {title} → {planned_date}")
        return entry

    def get_schedule(self, upcoming_only: bool = True) -> list[dict]:
        """投稿スケジュールを取得"""
        data = self._load()
        entries = data.get("schedule", [])
        if upcoming_only:
            today = datetime.now().strftime("%Y-%m-%d")
            entries = [e for e in entries if e.get("planned_date", "") >= today]
        return sorted(entries, key=lambda x: x.get("planned_date", ""))

    def get_next_deadline(self) -> dict[str, Any]:
        """次の投稿期限までの日数を返す"""
        upcoming = self.get_schedule(upcoming_only=True)
        
        valid_entry = None
        days_left = 0
        for entry in upcoming:
            try:
                planned_date = datetime.strptime(entry.get("planned_date", ""), "%Y-%m-%d").date()
                today_date = datetime.now().date()
                days_left = (planned_date - today_date).days
                valid_entry = entry
                break
            except (ValueError, TypeError) as e:
                logger.warning(f"📅 BIZ-6: Invalid planned_date format in entry {entry.get('id')}: {e}")
                continue

        if not valid_entry:
            return {
                "has_deadline": False,
                "message": "📅 投稿予定がありません。/youtube/schedule/add で追加してください。",
            }
            
        urgency = "🔴 今日！" if days_left <= 0 else "🟡 あと{}日".format(days_left) if days_left <= 3 else "🟢 あと{}日".format(days_left)
        return {
            "has_deadline": True,
            "next_title": valid_entry["title"],
            "planned_date": valid_entry["planned_date"],
            "days_left": max(days_left, 0),
            "urgency": urgency,
            "status": valid_entry.get("status", "draft"),
        }

    def analyze_pace(self) -> dict[str, Any]:
        """投稿ペースを分析"""
        data = self._load()
        entries = data.get("schedule", [])
        published = [e for e in entries if e.get("status") == "published"]

        if len(published) < 2:
            return {"enough_data": False, "message": "分析には2本以上の公開済み動画が必要です。"}

        # 投稿間隔を計算
        dates = []
        for e in published:
            try:
                dt = datetime.strptime(e.get("planned_date", ""), "%Y-%m-%d")
                dates.append(dt)
            except (ValueError, TypeError) as err:
                logger.warning(f"📅 BIZ-6: Invalid planned_date format in published entry {e.get('id')}: {err}")
                continue

        dates.sort()

        if len(dates) < 2:
            return {"enough_data": False, "message": "分析には2本以上の公開済み動画が必要です。"}

        intervals = [(dates[i+1] - dates[i]).days for i in range(len(dates) - 1)]
        avg_interval = sum(intervals) / len(intervals)

        target = data.get("settings", {}).get("target_per_week", 2)
        target_interval = 7 / target

        return {
            "enough_data": True,
            "total_published": len(published),
            "avg_interval_days": round(avg_interval, 1),
            "target_interval_days": round(target_interval, 1),
            "on_track": avg_interval <= target_interval * 1.2,
            "recommendation": (
                f"✅ 目標ペース達成中（平均{avg_interval:.1f}日/本 ≤ 目標{target_interval:.1f}日/本）"
                if avg_interval <= target_interval * 1.2
                else f"⚠️ 投稿ペース低下（平均{avg_interval:.1f}日/本 > 目標{target_interval:.1f}日/本）"
            ),
        }

    def update_status(self, entry_id: str, status: str) -> bool:
        """投稿ステータスを更新"""
        if status not in self.VALID_STATUSES:
            raise ValueError(f"Invalid status '{status}', must be one of {self.VALID_STATUSES}")

        success = [False]

        def updater(data: dict):
            if not isinstance(data, dict) or "schedule" not in data or not isinstance(data["schedule"], list):
                return data
            for entry in data["schedule"]:
                if entry.get("id") == entry_id:
                    entry["status"] = status
                    if status == "published":
                        entry["published_at"] = datetime.now().isoformat()
                    success[0] = True
                    break
            return data

        self._store.update(updater)
        return success[0]

    # ━━━ IMP-008: 目標頻度設定 ━━━

    def get_settings(self) -> dict[str, Any]:
        """投稿目標設定を取得"""
        data = self._load()
        settings = data.get("settings", {})
        return {
            "target_per_week": settings.get("target_per_week", 2),
            "preferred_days": settings.get("preferred_days", ["水", "土"]),
            "reminder_hours_before": settings.get("reminder_hours_before", 24),
            "auto_schedule": settings.get("auto_schedule", False),
        }

    def update_settings(
        self,
        target_per_week: int = None,
        preferred_days: list[str] = None,
        reminder_hours_before: int = None,
        auto_schedule: bool = None,
    ) -> dict[str, Any]:
        """投稿目標設定を更新"""
        updated_settings = {}

        def updater(data: dict):
            if not isinstance(data, dict):
                data = {"schedule": [], "settings": {"target_per_week": 2, "preferred_days": ["水", "土"]}}
            if "settings" not in data or not isinstance(data["settings"], dict):
                data["settings"] = {"target_per_week": 2, "preferred_days": ["水", "土"]}
                
            settings = data["settings"]

            if target_per_week is not None:
                settings["target_per_week"] = max(1, min(target_per_week, 7))
            if preferred_days is not None:
                valid_days = ["月", "火", "水", "木", "金", "土", "日"]
                settings["preferred_days"] = [d for d in preferred_days if d in valid_days]
            if reminder_hours_before is not None:
                settings["reminder_hours_before"] = max(1, min(reminder_hours_before, 168))
            if auto_schedule is not None:
                settings["auto_schedule"] = auto_schedule

            data["settings"] = settings
            updated_settings.update(settings)
            return data

        self._store.update(updater)
        logger.info(f"📅 IMP-008: 投稿目標設定更新: {updated_settings}")
        return updated_settings


publish_scheduler = PublishScheduler()