"""
API使用量トラッカー — 無料枠（500 RPD）の消費を監視

機能:
- API呼び出し回数を日次でカウント
- 4段階エスカレーション（60%/80%/95%/100%）
- 95%サスペンド（待機モード移行）および 100%強制ブロック（Banned）
- パイプライン実行前に残り回数を確認
"""
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path
import json
import logging
from datetime import date
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

USAGE_FILE = _writable_path("backend/usage_tracker/daily_usage.json")
FREE_TIER_LIMIT = 500  # Gemini 2.5-flash 無料枠 RPD


# ============================================================
# 4段階エスカレーション（U-02）
# ============================================================

class EscalationLevel(Enum):
    """使用量エスカレーションレベル"""
    NORMAL = "normal"       # 0-59%: 通常
    INFO = "info"           # 60-79%: 情報通知
    WARNING = "warning"     # 80-94%: 警告
    BLOCKED = "blocked"     # 95-99%: 危険（自動サスペンド）
    BANNED = "banned"       # 100%〜: 強制禁止（API呼び出し制限）


class APIUsageTracker:
    """Gemini API 使用量トラッカー（4段階エスカレーション対応）"""

    def __init__(self, usage_path: Path = USAGE_FILE):
        self.usage_path = usage_path
        self._data = self._load()
        self._last_escalation: EscalationLevel | None = None
        self.override_active = False
        self.thresholds = {
            "info": 0.60,
            "warning": 0.80,
            "critical": 0.95
        }

    def get_escalation_thresholds(self) -> list[tuple[float, EscalationLevel, str]]:
        """現在の閾値設定に基づく閾値リストを生成して返す"""
        return [
            (1.00, EscalationLevel.BANNED,   "🛑 API使用量上限到達: {used}/{limit} RPD — パイプライン実行を強制禁止 (Banned)"),
            (self.thresholds["critical"], EscalationLevel.BLOCKED,  "🔴 API使用量危険: 残り{remaining}回 ({pct:.0%}) — パイプライン処理を自動サスペンド"),
            (self.thresholds["warning"], EscalationLevel.WARNING,  "🟡 API使用量警告: 残り{remaining}回 ({pct:.0%})"),
            (self.thresholds["info"], EscalationLevel.INFO,     "📊 API使用量通知: {used}/{limit} RPD ({pct:.0%})"),
        ]

    def update_thresholds(self, info: float, warning: float, critical: float):
        """閾値を更新（入力ガードレール付き）"""
        if not (0.0 <= info < warning < critical <= 1.0):
            raise ValueError("Thresholds must satisfy 0.0 <= info < warning < critical <= 1.0")
        self.thresholds["info"] = info
        self.thresholds["warning"] = warning
        self.thresholds["critical"] = critical

    def set_override(self, active: bool):
        """自動サスペンドのオーバーライド状態を設定"""
        self.override_active = active

    def _load(self) -> dict:
        """使用量データを読み込み"""
        if self.usage_path.exists():
            try:
                with open(self.usage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict) and "daily" in data:
                        if "limit" not in data:
                            data["limit"] = FREE_TIER_LIMIT
                        return data
                    else:
                        logger.warning("Usage data in %s is invalid format. Using default.", self.usage_path)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load usage file %s: %s", self.usage_path, e)
        return {"daily": {}, "limit": FREE_TIER_LIMIT}

    def _save(self):
        """使用量データを保存"""
        self.usage_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.usage_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def _today(self) -> str:
        return date.today().isoformat()

    def record_calls(self, count: int = 1, source: str = "unknown"):
        """API呼び出しを記録"""
        if count <= 0:
            raise ValueError("API call count must be positive")
        today = self._today()
        if today not in self._data["daily"]:
            self._data["daily"][today] = {"total": 0, "sources": {}}

        self._data["daily"][today]["total"] += count
        sources = self._data["daily"][today]["sources"]
        sources[source] = sources.get(source, 0) + count
        self._save()

        # 4段階エスカレーションチェック
        self._check_escalation()

    def _check_escalation(self):
        """4段階エスカレーション判定"""
        usage = self.get_today_usage()
        used = usage["used"]
        limit = usage["limit"]
        remaining = usage["remaining"]
        pct = used / limit if limit > 0 else 0

        for threshold, level, msg_template in self.get_escalation_thresholds():
            if pct >= threshold:
                # 同じレベルのエスカレーションは繰り返さない
                if self._last_escalation == level:
                    return

                msg = msg_template.format(
                    used=used, limit=limit, remaining=remaining, pct=pct
                )

                if level == EscalationLevel.BANNED:
                    logger.critical(msg)
                elif level == EscalationLevel.BLOCKED:
                    logger.error(msg)
                elif level == EscalationLevel.WARNING:
                    logger.warning(msg)
                else:
                    logger.info(msg)

                self._last_escalation = level
                return

        # 60%未満: NORMAL
        self._last_escalation = EscalationLevel.NORMAL

    def should_block(self) -> bool:
        """API使用量がサスペンド閾値(95%)に達している場合 True。ただしオーバーライド時は100%未満なら False"""
        today = self._today()
        daily = self._data["daily"].get(today, {"total": 0})
        used = daily["total"]
        limit = self._data.get("limit", FREE_TIER_LIMIT)
        pct = used / limit if limit > 0 else 0

        if pct >= 1.00:
            return True
        if pct >= self.thresholds["critical"]:
            return not self.override_active
        return False

    def _calc_usage_pct(self) -> float:
        """現在の使用率を計算（再帰しない内部メソッド）"""
        today = self._today()
        daily = self._data["daily"].get(today, {"total": 0})
        used = daily["total"]
        limit = self._data.get("limit", FREE_TIER_LIMIT)
        return used / limit if limit > 0 else 0

    def get_escalation_level(self) -> EscalationLevel:
        """現在のエスカレーションレベルを返す"""
        pct = self._calc_usage_pct()
        for threshold, level, _ in self.get_escalation_thresholds():
            if pct >= threshold:
                return level
        return EscalationLevel.NORMAL

    def get_today_usage(self) -> dict:
        """今日の使用状況を取得"""
        today = self._today()
        daily = self._data["daily"].get(today, {"total": 0, "sources": {}})
        used = daily["total"]
        limit = self._data.get("limit", FREE_TIER_LIMIT)
        remaining = limit - used
        pct = self._calc_usage_pct()

        # エスカレーションレベルを再帰なしで計算
        level = EscalationLevel.NORMAL
        for threshold, lv, _ in self.get_escalation_thresholds():
            if pct >= threshold:
                level = lv
                break

        return {
            "date": today,
            "used": used,
            "limit": limit,
            "remaining": remaining,
            "usage_pct": round(pct * 100, 1),
            "escalation_level": level.value,
            "sources": daily.get("sources", {}),
            "can_run_pipeline": not self.should_block() and remaining > 0,
        }

    def estimate_pipeline_cost(self, segment_count: int) -> dict:
        """パイプライン実行に必要なAPIコール数を推定"""
        batch_size = 50
        ai_proofread_calls = (segment_count + batch_size - 1) // batch_size
        smartcut_calls = 1
        youtube_calls = 1
        quality_check_calls = 1
        total = ai_proofread_calls + smartcut_calls + youtube_calls + quality_check_calls

        usage = self.get_today_usage()
        limit = usage["limit"]
        after_pct = (usage["used"] + total) / limit if limit > 0 else 0
        
        is_blocked_after = False
        if after_pct >= 1.00:
            is_blocked_after = True
        elif after_pct >= self.thresholds["critical"]:
            is_blocked_after = not self.override_active

        return {
            "estimated_calls": total,
            "breakdown": {
                "ai_proofread": ai_proofread_calls,
                "smartcut": smartcut_calls,
                "youtube_optimizer": youtube_calls,
                "quality_check": quality_check_calls
            },
            "remaining_after": usage["remaining"] - total,
            "can_proceed": usage["remaining"] >= total and not self.should_block() and not is_blocked_after,
            "escalation_level": usage["escalation_level"],
        }

    def cleanup_old_data(self, keep_days: int = 30):
        """古いデータを削除"""
        if keep_days <= 0:
            raise ValueError("keep_days must be positive")
        cutoff = date.today().isoformat()
        # 日付キーをソートして時系列順にする
        keys_to_remove = sorted([
            k for k in self._data["daily"]
            if k < cutoff
        ])
        
        total_count = len(self._data["daily"])
        if total_count > keep_days:
            remove_count = total_count - keep_days
            to_delete = keys_to_remove[:remove_count]
            for k in to_delete:
                del self._data["daily"][k]
            if to_delete:
                self._save()


# シングルトン
usage_tracker = APIUsageTracker()


def record_api_call(count: int = 1, source: str = "unknown"):
    """API呼び出しを記録（簡易関数）"""
    usage_tracker.record_calls(count, source)


def get_usage_status() -> dict:
    """使用状況を取得（簡易関数）"""
    return usage_tracker.get_today_usage()


def should_block_api() -> bool:
    """API使用をブロックすべきか判定（簡易関数）"""
    return usage_tracker.should_block()
