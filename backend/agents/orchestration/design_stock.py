"""
設計ストック管理 API (Design Stock Manager)

難易度S/A/B/Cの設計タスクを10個ストックとして管理し、
Opus/Flashセッションへの動的投入と滞留検知を行う。

難易度体系:
  S: 最高難度（演出還流・自律協議体等） → Opus必須 + ユーザー合意
  A: 高難度（ビジョンスコアリング・複雑API等） → Opus必須 + 3大論点チェック
  B: 中難度（新機能実装・設計判断あり） → Opus設計 → Flash実装
  C: 低難度（テスト追加・リファクタ・バグ修正等） → Flash即投入

使い方:
  store = DesignStockStore()
  store.add_item("タイトル", phase=27, difficulty="B", description="...")
  store.update_status("DS-001", "designed")
  summary = store.get_dashboard_summary()
"""

import json
import os
from datetime import datetime, timezone
from .atomic_io import safe_read_json, atomic_write_json

STOCK_PATH = os.path.join(os.path.dirname(__file__), "design_stock.json")

DIFFICULTY_ORDER = {"S": 0, "A": 1, "B": 2, "C": 3}
DIFFICULTY_LABELS = {
    "S": "🔴 最高難度",
    "A": "🟠 高難度",
    "B": "🟡 中難度",
    "C": "🟢 低難度",
}
SESSION_MAP = {
    "S": "opus",
    "A": "opus",
    "B": "opus_then_flash",
    "C": "flash",
}
STATUS_LABELS = {
    "pending": "📋 未着手",
    "in_discussion": "💬 議論中",
    "designed": "✅ 設計完了",
    "dispatched": "🚀 投入済み",
    "deferred": "⏸️ 保留",
    "completed": "✅ 完了",
}


class DesignStockStore:
    def __init__(self, path=None):
        self.path = path or STOCK_PATH
        self._data = self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return {"config": {"target_stock_count": 10, "phases_ahead": 3,
                               "stale_days_sa": 3, "stale_days_bc": 7},
                    "stock_items": []}
        return safe_read_json(self.path, default={"config": {}, "stock_items": []})

    def _save(self):
        atomic_write_json(self.path, self._data)

    def _next_id(self):
        items = self._data.get("stock_items", [])
        if not items:
            return "DS-001"
        nums = []
        for item in items:
            parts = item["id"].split("-")
            if len(parts) >= 2 and parts[0] == "DS":
                try:
                    nums.append(int(parts[1]))
                except ValueError:
                    pass
        max_num = max(nums) if nums else 0
        return f"DS-{max_num + 1:03d}"

    @property
    def config(self):
        return self._data.get("config", {})

    @property
    def items(self):
        return self._data.get("stock_items", [])

    def add_item(self, title, phase, difficulty, description="",
                 milestone="", source_phase_task="", implementation_steps=None):
        """Add a new design stock item."""
        if difficulty not in DIFFICULTY_ORDER:
            raise ValueError(f"Invalid difficulty: {difficulty}. Must be S/A/B/C")

        now = datetime.now(timezone.utc).isoformat()
        item = {
            "id": self._next_id(),
            "title": title,
            "phase": phase,
            "milestone": milestone,
            "difficulty": difficulty,
            "session_target": SESSION_MAP[difficulty],
            "status": "pending",
            "created_at": now,
            "last_activity": now,
            "description": description,
            "source_phase_task": source_phase_task,
            "implementation_steps": implementation_steps or [],
        }
        # S/A items need 3-point check
        if difficulty in ("S", "A"):
            item["three_point_check"] = {
                "quantitative_mapping": False,
                "safety_fallback": False,
                "input_guardrail": False,
            }

        self._data["stock_items"].append(item)
        self._save()
        return item

    def update_status(self, item_id, new_status):
        """Update item status."""
        for item in self.items:
            if item["id"] == item_id:
                item["status"] = new_status
                item["last_activity"] = datetime.now(timezone.utc).isoformat()
                self._save()
                return True
        return False

    def update_three_point_check(self, item_id, check_name, value=True):
        """Update a 3-point check for S/A items."""
        for item in self.items:
            if item["id"] == item_id and "three_point_check" in item:
                if check_name in item["three_point_check"]:
                    item["three_point_check"][check_name] = value
                    item["last_activity"] = datetime.now(timezone.utc).isoformat()
                    self._save()
                    return True
        return False

    def remove_item(self, item_id):
        """Remove an item (after dispatch or cancellation)."""
        self._data["stock_items"] = [
            i for i in self.items if i["id"] != item_id
        ]
        self._save()

    def get_sorted_items(self):
        """Get items sorted by difficulty (S first, then A, B, C)."""
        return sorted(self.items, key=lambda x: DIFFICULTY_ORDER.get(x.get("difficulty", "C"), 3))

    def _calculate_age_days(self, last_activity_str, now):
        """Calculate the age in days from an ISO format timestamp string."""
        if not last_activity_str:
            return None
        try:
            dt = datetime.fromisoformat(last_activity_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return (now - dt).total_seconds() / 86400
        except (ValueError, TypeError, AttributeError):
            return None

    def get_stale_items(self):
        """Detect items that have been sitting too long without progress."""
        now = datetime.now(timezone.utc)
        stale = []
        sa_days = self.config.get("stale_days_sa", 3)
        bc_days = self.config.get("stale_days_bc", 7)

        for item in self.items:
            if item["status"] in ("dispatched", "deferred", "completed"):
                continue
            last = item.get("last_activity") or item.get("created_at")
            age_days = self._calculate_age_days(last, now)
            if age_days is None:
                continue

            threshold = sa_days if item.get("difficulty") in ("S", "A") else bc_days
            if age_days >= threshold:
                stale.append({
                    **item,
                    "stale_days": int(age_days),
                    "threshold": threshold,
                })
        return stale

    def get_stock_health(self):
        """Check stock health: count, distribution, gaps."""
        active = [i for i in self.items if i["status"] not in ("dispatched",)]
        total = len(active)
        target = self.config.get("target_stock_count", 10)

        by_diff = {"S": 0, "A": 0, "B": 0, "C": 0}
        by_status = {}
        phases = set()
        for item in active:
            d = item.get("difficulty", "C")
            by_diff[d] = by_diff.get(d, 0) + 1
            s = item.get("status", "pending")
            by_status[s] = by_status.get(s, 0) + 1
            phases.add(item.get("phase", 0))

        return {
            "total_active": total,
            "target": target,
            "shortage": max(0, target - total),
            "by_difficulty": by_diff,
            "by_status": by_status,
            "phases_covered": sorted(phases),
            "stale_items": self.get_stale_items(),
        }


    def get_dashboard_summary(self):
        """Generate dashboard markdown for design stock status."""
        health = self.get_stock_health()
        active_items = [i for i in self.items if i["status"] != "dispatched"]
        sorted_items = sorted(active_items,
                              key=lambda x: DIFFICULTY_ORDER.get(x.get("difficulty", "C"), 3))

        # Header
        stock_icon = "🟢" if health["shortage"] == 0 else "🟡" if health["shortage"] <= 3 else "🔴"
        md = f"## 📐 設計ストック ({health['total_active']}/{health['target']}個) {stock_icon}\n\n"

        if not sorted_items:
            md += "> ⚠️ 設計ストックが空です。MASTERロードマップから先3Phase分のタスクを補充してください。\n\n"
            return md

        # Ranking table
        md += "| # | 難易度 | タイトル | Phase | 投入先 | 状態 | 経過 |\n"
        md += "|:---:|:---:|:---|:---:|:---:|:---:|:---:|\n"

        now = datetime.now(timezone.utc)
        for i, item in enumerate(sorted_items, 1):
            diff_label = DIFFICULTY_LABELS.get(item["difficulty"], "?")
            status_label = STATUS_LABELS.get(item["status"], "?")
            session = {"opus": "🧠 Opus", "flash": "⚡ Flash",
                       "opus_then_flash": "🧠→⚡"}.get(item.get("session_target", ""), "?")

            # Age calculation
            created = item.get("created_at", "")
            age_days = self._calculate_age_days(created, now)
            if age_days is not None:
                age_days_int = int(age_days)
                age_str = f"{age_days_int}日" if age_days_int > 0 else "今日"
            else:
                age_str = "—"

            title = item["title"][:25]
            md += f"| {i} | {diff_label} | {title} | P{item.get('phase', '?')} | {session} | {status_label} | {age_str} |\n"

        # 統合サジェスト & スケジュールテーブル
        stale_items = health.get("stale_items", [])
        # ストック不足等の一般警告
        general_warnings = []
        if health["shortage"] > 0:
            general_warnings.append(
                f"🔴 **ストック不足**: 現在{health['total_active']}個（目標{health['target']}個）。"
                f"MASTERロードマップから**{health['shortage']}個**を補充してください。"
            )
        sa_count = health["by_difficulty"].get("S", 0) + health["by_difficulty"].get("A", 0)
        if sa_count == 0 and health["total_active"] > 0:
            general_warnings.append(
                "🟡 **高難度タスクなし**: S/Aランクが0件です。"
            )

        if general_warnings:
            md += "\n"
            for w in general_warnings:
                md += f"- {w}\n"

        if stale_items:
            # 優先度ソート
            stale_sorted = sorted(
                stale_items,
                key=lambda x: (DIFFICULTY_ORDER.get(x.get("difficulty", "C"), 3), -x.get("stale_days", 0)),
            )[:5]

            # 営業日割当
            today = datetime.now()
            weekday = today.weekday()
            weekday_names = ["月曜", "火曜", "水曜", "木曜", "金曜"]
            remaining_days = weekday_names[weekday:] if weekday <= 4 else weekday_names[:]

            md += "\n#### ⚠️ 滞留設計 & 解消スケジュール\n\n"
            md += "| 優先 | アイテム | 滞留 | 概要 | 推奨日 | 見積 |\n"
            md += "|:---:|:---|:---:|:---|:---|:---:|\n"

            for i, item in enumerate(stale_sorted):
                title = item['title'][:20]
                desc = item.get('description', '')
                desc_short = (desc[:40] + '...') if len(desc) > 40 else desc
                day = remaining_days[i % len(remaining_days)]
                est = "45分" if item.get("difficulty") in ("S", "A") else "30分"
                md += f"| {i+1} | [{item['id']}] {title} | {item['stale_days']}日 | {desc_short} | {day} | {est} |\n"
            md += "\n"

        return md

