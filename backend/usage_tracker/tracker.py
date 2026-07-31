"""
Usage Tracker - API使用量追跡

SSoT: model_config.json（free_tier_limits セクション）

4段階エスカレーション:
  - 60%: 情報ログ (INFO)
  - 80%: 警告アラート (WARNING)
  - 95%: ブロック推奨 (BLOCK)
  - 100%: API呼び出し禁止 (CRITICAL)

設計方針:
  - free_tier_config.json は廃止 → model_config.json に統合
  - モデル別 RPD は model_config.json の free_tier_limits から動的取得
"""
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# SSoT: model_config.json
MODEL_CONFIG_PATH = Path(__file__).parent.parent / "model_config.json"

# デフォルトアラート閾値
DEFAULT_THRESHOLDS = {
    "info": 0.6,
    "warning": 0.8,
    "block": 0.95,
    "critical": 1.0,
}


@dataclass
class UsageRecord:
    """使用量レコード"""
    model: str
    requests: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class DailyUsage:
    """日次使用量"""
    date: str
    models: dict[str, dict[str, int]] = field(default_factory=dict)

    def add_request(self, model: str, tokens_in: int = 0, tokens_out: int = 0):
        if not model:
            raise ValueError("Model name cannot be empty")
        tokens_in = max(0, tokens_in)
        tokens_out = max(0, tokens_out)
        if model not in self.models:
            self.models[model] = {"requests": 0, "tokens_in": 0, "tokens_out": 0}
        self.models[model]["requests"] += 1
        self.models[model]["tokens_in"] += tokens_in
        self.models[model]["tokens_out"] += tokens_out

    def get_requests(self, model: str) -> int:
        if not model:
            return 0
        return self.models.get(model, {}).get("requests", 0)


def _load_model_config(config_path: Path | None = None) -> dict:
    """model_config.json を読み込み（SSoT）"""
    path = config_path or MODEL_CONFIG_PATH
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, PermissionError) as e:
        logger.warning(f"UsageTracker: model_config.json load failed: {e}")
        return {}
    except OSError as e:
        logger.error(f"UsageTracker: model_config.json OS error: {e}")
        return {}


class UsageTracker:
    """
    使用量追跡システム（model_config.json SSoT 参照型）

    free_tier_limits から各モデルの RPD を取得し、
    使用率に応じた4段階エスカレーションを実行する。
    """

    def __init__(self, usage_path: Path | None = None, model_config_path: Path | None = None):
        # 実行のたびに書き換わるファイルなので writable_path で解決する。
        # 以前は Path(__file__).parent 固定だったため、テストが本番の
        # usage_data.json を上書きしていた（Git 追跡下のファイル）。
        self._usage_path = usage_path or _writable_path("backend/usage_tracker/usage_data.json")
        self._model_config_path = model_config_path or MODEL_CONFIG_PATH
        self._free_tier_limits: dict = {}
        self._alert_thresholds: dict = dict(DEFAULT_THRESHOLDS)
        self._daily_usage: DailyUsage | None = None
        self._callbacks: list[callable] = []

        self._load_config()
        self._load_or_create_daily_usage()

    def _load_config(self):
        """model_config.json の free_tier_limits を読み込み"""
        config = _load_model_config(self._model_config_path)
        self._free_tier_limits = config.get("free_tier_limits", {})

        # alert_thresholds があれば上書き
        thresholds = config.get("alert_thresholds", {})
        if thresholds:
            self._alert_thresholds.update(thresholds)

    def _get_rpd(self, model: str) -> int:
        """モデルの日次リクエスト上限 (RPD) を取得"""
        if not model:
            return 1000
        model_limits = self._free_tier_limits.get(model, {})
        return model_limits.get("rpd", 1000)  # デフォルト1000

    def _load_existing_usage_data(self) -> DailyUsage | None:
        """既存の使用量データをロードする（存在しない、またはエラーの場合は None を返す）"""
        if not self._usage_path.exists():
            return None
        try:
            with open(self._usage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            today = date.today().isoformat()
            if data.get("date") == today:
                return DailyUsage(
                    date=data["date"],
                    models=data.get("models", {})
                )
        except (json.JSONDecodeError, KeyError, PermissionError) as e:
            logger.warning(f"Failed to decode or parse usage data: {e}")
        except OSError as e:
            logger.error(f"OS error loading usage data: {e}")
        return None

    def _load_or_create_daily_usage(self):
        """日次使用量をロードまたは作成"""
        loaded = self._load_existing_usage_data()
        if loaded is not None:
            self._daily_usage = loaded
            return

        self._daily_usage = DailyUsage(date=date.today().isoformat())
        self._save_usage()

    def _save_usage(self):
        """使用量を保存"""
        try:
            data = {
                "date": self._daily_usage.date,
                "models": self._daily_usage.models,
                "last_updated": datetime.now().isoformat()
            }
            # 保存先が writable_path で差し替えられている場合、親が無いことがある。
            self._usage_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._usage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except TypeError as e:
            logger.error(f"Failed to serialize usage data: {e}")
        except OSError as e:
            logger.error(f"OS error saving usage data: {e}")

    def _reset_usage_if_date_changed(self, today: str):
        """日付が変わっていたら使用状況をリセットする"""
        if self._daily_usage.date != today:
            self._daily_usage = DailyUsage(date=today)

    def _dispatch_alert_callbacks(self, result: dict[str, Any]):
        """登録されたコールバックにアラート結果を送信する"""
        for callback in self._callbacks:
            try:
                callback(result)
            except Exception as e:
                logger.error(f"Alert callback failed: {e}", exc_info=True)

    def track_request(
        self,
        model: str,
        tokens_in: int = 0,
        tokens_out: int = 0
    ) -> dict[str, Any]:
        """リクエストを追跡"""
        if not model:
            raise ValueError("Model name cannot be empty")
        tokens_in = max(0, tokens_in)
        tokens_out = max(0, tokens_out)

        today = date.today().isoformat()
        self._reset_usage_if_date_changed(today)

        self._daily_usage.add_request(model, tokens_in, tokens_out)
        self._save_usage()

        usage_ratio = self.get_usage_ratio(model)
        alert_level = self._get_alert_level(usage_ratio)

        result = {
            "model": model,
            "requests_today": self._daily_usage.get_requests(model),
            "usage_ratio": usage_ratio,
            "alert_level": alert_level,
            "blocked": alert_level == "critical"
        }

        self._log_alert(result)
        self._dispatch_alert_callbacks(result)

        return result

    def get_usage_ratio(self, model: str) -> float:
        """使用率を取得（0.0 - 1.0）"""
        if not model:
            return 0.0
        rpd = self._get_rpd(model)
        current = self._daily_usage.get_requests(model)
        return min(current / rpd, 1.0) if rpd > 0 else 0.0

    def _get_alert_level(self, ratio: float) -> str:
        """アラートレベルを判定"""
        if ratio >= self._alert_thresholds.get("critical", 1.0):
            return "critical"
        elif ratio >= self._alert_thresholds.get("block", 0.95):
            return "block"
        elif ratio >= self._alert_thresholds.get("warning", 0.8):
            return "warning"
        elif ratio >= self._alert_thresholds.get("info", 0.6):
            return "info"
        return "normal"

    def _log_alert(self, result: dict):
        """アラートをログ"""
        level = result["alert_level"]
        model = result["model"]
        ratio = result["usage_ratio"]

        if level == "critical":
            logger.critical(f"🛑 [{model}] 無料枠100%到達！API呼び出し禁止: {ratio:.1%}")
        elif level == "block":
            logger.error(f"🛑 [{model}] 無料枠95%到達！処理停止: {ratio:.1%}")
        elif level == "warning":
            logger.warning(f"⚠️ [{model}] 無料枠80%警告: {ratio:.1%}")
        elif level == "info":
            logger.info(f"ℹ️ [{model}] 無料枠60%通知: {ratio:.1%}")

    def can_make_request(self, model: str) -> bool:
        """リクエスト可能かチェック"""
        if not model:
            return False
        ratio = self.get_usage_ratio(model)
        threshold = self._alert_thresholds.get("block", 0.95)
        return ratio < threshold

    def get_remaining_requests(self, model: str) -> int:
        """残りリクエスト数を取得"""
        if not model:
            return 0
        rpd = self._get_rpd(model)
        current = self._daily_usage.get_requests(model)
        return max(0, rpd - current)

    def get_daily_summary(self) -> dict[str, Any]:
        """日次サマリーを取得（全モデル）"""
        summary = {
            "date": self._daily_usage.date,
            "models": {}
        }

        for model, limits in self._free_tier_limits.items():
            rpd = limits.get("rpd", 0)
            if rpd == 0:
                continue  # quota=0 のモデルは除外
            current = self._daily_usage.get_requests(model)
            ratio = self.get_usage_ratio(model)
            summary["models"][model] = {
                "used": current,
                "limit": rpd,
                "remaining": max(0, rpd - current),
                "usage_ratio": ratio,
                "alert_level": self._get_alert_level(ratio),
                "tier": limits.get("tier", "unknown"),
            }

        return summary

    def register_alert_callback(self, callback: callable):
        """アラートコールバックを登録"""
        if not callback or not callable(callback):
            raise TypeError("Callback must be callable")
        self._callbacks.append(callback)

    def _resolve_preferred_model(self, task: str) -> str:
        """レジストリから優先モデルを取得する（取得失敗時はデフォルトを返す）"""
        try:
            from model_registry import get_model
            return get_model(task)
        except (ImportError, AttributeError, NameError):
            return "gemini-2.5-flash"
        except Exception as e:
            logger.error(f"Error in model_registry: {e}", exc_info=True)
            return "gemini-2.5-flash"

    def _resolve_fallback_model(self, preferred: str) -> str | None:
        """制限に達したモデルのフォールバック先を取得する"""
        config = _load_model_config(self._model_config_path)
        fallback_chain = {}
        for cat in ["text_generation", "image_generation", "video_generation"]:
            chain = config.get(cat, {}).get("fallback_chain", {})
            if chain:
                fallback_chain.update(chain)

        fallback = fallback_chain.get(preferred)
        if fallback and self.can_make_request(fallback):
            return fallback
        return None

    def get_model_recommendation(self, task: str) -> str:
        """
        タスクに対する推奨モデルを取得

        model_registry 経由 + 使用率によるフォールバック
        """
        if not task:
            raise ValueError("Task name cannot be empty")

        preferred = self._resolve_preferred_model(task)

        if not self.can_make_request(preferred):
            fallback = self._resolve_fallback_model(preferred)
            if fallback:
                logger.warning(
                    f"Falling back from {preferred} to {fallback} due to quota"
                )
                return fallback

        return preferred


# シングルトンインスタンス
usage_tracker = UsageTracker()
