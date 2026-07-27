"""
Quota Manager - クォータ管理とモデル自動切換え

SSoT: model_config.json（全モデル定義・フォールバック・RPD上限を一元管理）

3段階モデル方式:
  - Premium: 後発・高性能・枠限定 → 優先消費
  - Standard: 安定版 → 確実な処理
  - Batch: 軽量版 → 大量処理

設計方針:
  - ハードコード禁止: 全設定を model_config.json から動的読込
  - model_governance.py と連携してフォールバックを実行
"""
from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import logging

# Model Registry (SSoT: model_config.json)
try:
    from model_registry import get_model
except ImportError:
    def get_model(task): return "gemini-2.5-flash"

logger = logging.getLogger(__name__)

# SSoT: model_config.json
CONFIG_PATH = Path(__file__).parent.parent / "model_config.json"

# Constants for reset and JST conversions
JST_OFFSET_HOURS = 9
CAN_WAIT_THRESHOLD_HOURS = 12

# Constants for tier status warnings (hardcoded defaults)
STATUS_WARNING_THRESHOLD = 0.8
STATUS_CAUTION_THRESHOLD = 0.6






def _load_model_config() -> Dict:
    """model_config.json を読み込み（SSoT）"""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, PermissionError) as e:
        logger.warning(f"QuotaManager: model_config.json load failed: {e}")
        return {}
    except OSError as e:
        logger.error(f"QuotaManager: model_config.json OS error: {e}")
        return {}


class QuotaManager:
    """
    クォータ管理（model_config.json SSoT 参照型）

    全設定を model_config.json から動的に読み込む。
    ハードコードされたモデル名・RPD値は持たない。
    """

    # 日次リセット時刻（日本時間0時 = UTC 15:00）
    DAILY_RESET_HOUR_UTC = 15

    def __init__(self):
        self._usage_tracker = None
        self._config: Dict = {}
        self._reload_config()

    def _reload_config(self):
        """model_config.json からティア・フォールバック・RPD を読み込み"""
        self._config = _load_model_config()

    @property
    def model_tiers(self) -> Dict[str, Dict]:
        """model_config.json の tiers を返す"""
        return self._config.get("text_generation", {}).get("tiers", {})

    @property
    def fallback_chain(self) -> Dict[str, Optional[str]]:
        """model_config.json の fallback_chain を返す"""
        return self._config.get("text_generation", {}).get("fallback_chain", {})

    @property
    def usage_tracker(self):
        if self._usage_tracker is None:
            from usage_tracker.tracker import usage_tracker
            self._usage_tracker = usage_tracker
        return self._usage_tracker

    def _build_reset_time_response(self, reset_time: datetime, hours: int, minutes: int) -> Dict[str, Any]:
        """リセット時間情報の表示用レスポンスを構築"""
        return {
            "reset_time_utc": reset_time.isoformat(),
            "reset_time_jst": (reset_time + timedelta(hours=JST_OFFSET_HOURS)).strftime("%Y-%m-%d %H:%M"),
            "remaining_hours": hours,
            "remaining_minutes": minutes,
            "remaining_display": f"{hours}時間{minutes}分",
            "can_wait": hours < CAN_WAIT_THRESHOLD_HOURS
        }

    def get_time_until_reset(self) -> Dict[str, Any]:
        """日次リセットまでの時間を取得"""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        reset_time = now.replace(
            hour=self.DAILY_RESET_HOUR_UTC,
            minute=0, second=0, microsecond=0
        )
        if now >= reset_time:
            reset_time += timedelta(days=1)

        remaining = reset_time - now
        total_seconds = int(remaining.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60

        return self._build_reset_time_response(reset_time, hours, minutes)

    def _resolve_tier_config(self, preferred_tier: str) -> tuple[str, float]:
        """ティア設定の解決とモデル・温存比率の取得"""
        tiers = self.model_tiers
        if not isinstance(tiers, dict):
            logger.error("QuotaManager: model_tiers configuration is missing or not a dictionary")
            tiers = {}

        tier_config = tiers.get(preferred_tier)
        if not isinstance(tier_config, dict):
            tier_config = tiers.get("standard", {})
        if not isinstance(tier_config, dict):
            logger.error(f"QuotaManager: config for tier '{preferred_tier}' and fallback 'standard' are invalid")
            tier_config = {}

        preferred_model = tier_config.get("model") or get_model("proofreader")
        preserve_ratio = tier_config.get("preserve_ratio") or 0.0
        if not isinstance(preserve_ratio, (int, float)):
            preserve_ratio = 0.0

        return preferred_model, preserve_ratio

    def _build_preserve_response(
        self,
        preferred_model: str,
        preferred_tier: str,
        allow_fallback: bool
    ) -> Dict[str, Any]:
        """Premium温存時のレスポンス構築"""
        remaining = self.usage_tracker.get_remaining_requests(preferred_model)
        reset_info = self.get_time_until_reset()
        fallback_chain = self.fallback_chain
        if not isinstance(fallback_chain, dict):
            fallback_chain = {}
        fallback_model = fallback_chain.get(preferred_model)

        return {
            "model": fallback_model if allow_fallback else None,
            "tier": preferred_tier,
            "available": False,
            "reason": "premium_preserved",
            "message": f"Premiumモデルの枠を温存中です（残り{remaining}回）",
            "options": {
                "wait": {
                    "available": True,
                    "message": f"リセットまで待機: {reset_info['remaining_display']}",
                    "reset_time": reset_info["reset_time_jst"],
                    "recommended": reset_info["can_wait"]
                },
                "fallback": {
                    "available": allow_fallback and fallback_model is not None,
                    "model": fallback_model,
                    "tier": "standard",
                    "message": "Standardモデルで続行（品質低下の可能性）"
                },
                "force": {
                    "available": remaining > 0,
                    "message": f"Premiumを強制使用（残り{remaining}回）"
                }
            }
        }

    def _build_exhausted_response(
        self,
        preferred_model: str,
        allow_fallback: bool
    ) -> Dict[str, Any]:
        """完全に枠切れ（Exhausted）時のレスポンス構築"""
        reset_info = self.get_time_until_reset()
        fallback_chain = self.fallback_chain
        if not isinstance(fallback_chain, dict):
            fallback_chain = {}
        fallback_model = fallback_chain.get(preferred_model)

        try:
            can_use_fallback = fallback_model and self.usage_tracker.can_make_request(fallback_model)
        except AttributeError:
            can_use_fallback = False

        if fallback_model and can_use_fallback:
            return {
                "model": fallback_model if allow_fallback else None,
                "tier": "standard",
                "available": False,
                "reason": "quota_exhausted",
                "message": f"{preferred_model}の日次枠を使い切りました",
                "switched": allow_fallback,
                "options": {
                    "wait": {
                        "available": True,
                        "message": f"リセットまで待機: {reset_info['remaining_display']}",
                        "reset_time": reset_info["reset_time_jst"],
                        "recommended": reset_info["can_wait"]
                    },
                    "fallback": {
                        "available": allow_fallback,
                        "model": fallback_model,
                        "tier": "standard",
                        "message": "Standardモデルで続行"
                    }
                }
            }
        else:
            return {
                "model": None,
                "tier": None,
                "available": False,
                "reason": "all_exhausted",
                "message": "全モデルの日次枠を使い切りました",
                "options": {
                    "wait": {
                        "available": True,
                        "message": f"リセットまで待機: {reset_info['remaining_display']}",
                        "reset_time": reset_info["reset_time_jst"],
                        "recommended": True
                    }
                }
            }

    def _build_available_response(
        self,
        preferred_model: str,
        preferred_tier: str,
        usage_ratio: float
    ) -> Dict[str, Any]:
        """通常利用可能時のレスポンス構築"""
        return {
            "model": preferred_model,
            "tier": preferred_tier,
            "available": True,
            "usage_percent": round(usage_ratio * 100, 1),
            "remaining": self.usage_tracker.get_remaining_requests(preferred_model)
        }

    def get_model_with_wait_option(
        self,
        preferred_tier: str = "premium",
        task: str = "",
        allow_fallback: bool = True
    ) -> Dict[str, Any]:
        """
        3段階モデル選定方式に基づいて、現在利用可能なモデルを取得します（待機オプション情報付き）。

        全設定は `model_config.json`（SSoT）から動的に読み込まれます。

        Args:
            preferred_tier (str): 希望するティア（"premium", "standard", "batch"）。デフォルトは "premium"。
            task (str): 実行タスク名。互換性維持のために定義されていますが、内部ロジックでは現在使用されていません。
            allow_fallback (bool): 希望するモデルのクォータを超過している場合に、フォールバックチェーンに沿って
                                 下位ティアのモデルへ切り替えることを許可するかどうか。デフォルトは True。

        Returns:
            Dict[str, Any]: 選定されたモデル、その利用可能性、およびリセット待機や代替モデルでの実行オプションを含む辞書。
        """
        preferred_model, preserve_ratio = self._resolve_tier_config(preferred_tier)

        try:
            usage_ratio = self.usage_tracker.get_usage_ratio(preferred_model)
            can_use = self.usage_tracker.can_make_request(preferred_model)

            # Premium温存チェック
            if preferred_tier == "premium" and usage_ratio > (1.0 - preserve_ratio):
                return self._build_preserve_response(preferred_model, preferred_tier, allow_fallback)

            # 完全に枠切れ
            if not can_use:
                return self._build_exhausted_response(preferred_model, allow_fallback)

            # 通常使用可能
            return self._build_available_response(preferred_model, preferred_tier, usage_ratio)
        except AttributeError as e:
            logger.error(f"QuotaManager: usage_tracker is invalid or missing required methods: {e}")
            return {
                "model": preferred_model,
                "tier": preferred_tier,
                "available": True,
                "usage_percent": 0.0,
                "remaining": 999
            }

    def _calculate_tier_capacities(
        self,
        remaining: int,
        usage_ratio: float,
        preserve_ratio: float
    ) -> tuple[int, int]:
        """温存数と利用可能数の計算"""
        limit = remaining / (1.0 - usage_ratio) if usage_ratio < 1.0 else 0
        preserve_count = int(limit * preserve_ratio)
        available_count = max(0, remaining - preserve_count)
        return preserve_count, available_count

    def _build_tier_status_info(self, tier_name: str, tier_config: dict) -> Optional[Dict[str, Any]]:
        """個別ティアのステータス情報を構築"""
        if not isinstance(tier_config, dict):
            logger.warning(f"QuotaManager: tier config for '{tier_name}' is not a dictionary")
            return None

        model = tier_config.get("model", "")
        try:
            usage_ratio = self.usage_tracker.get_usage_ratio(model)
            remaining = self.usage_tracker.get_remaining_requests(model)
        except AttributeError as e:
            logger.error(f"QuotaManager: usage_tracker error in get_two_tier_status for model '{model}': {e}")
            usage_ratio = 0.0
            remaining = 0

        preserve_ratio = tier_config.get("preserve_ratio", 0.0)
        if not isinstance(preserve_ratio, (int, float)):
            preserve_ratio = 0.0

        preserve_count, available_count = self._calculate_tier_capacities(
            remaining, usage_ratio, preserve_ratio
        )

        return {
            "model": model,
            "label": tier_config.get("label", tier_name),
            "description": tier_config.get("description", ""),
            "usage_percent": round(usage_ratio * 100, 1),
            "remaining": remaining,
            "preserved": preserve_count,
            "available_for_use": available_count,
            "status": self._get_tier_status(usage_ratio, preserve_ratio)
        }

    def get_all_tiers_status(self) -> Dict[str, Any]:
        """
        全モデルティアの現在の利用ステータスおよび制限情報を一括取得します。

        各ティアの現在消費率、残枠数、温存指定枠数、最終ステータス（"normal", "caution", "warning", "preserved", "exhausted"）を算出します。

        Returns:
            Dict[str, Any]: 現在のタイムスタンプ、リセットまでの残り時間、および各ティアの詳細ステータスを含む辞書。
        """
        reset_info = self.get_time_until_reset()
        status = {
            "timestamp": datetime.now().isoformat(),
            "reset_info": reset_info,
            "tiers": {}
        }

        tiers = self.model_tiers
        if not isinstance(tiers, dict):
            logger.error("QuotaManager: model_tiers is missing or not a dictionary")
            return status

        for tier_name, tier_config in tiers.items():
            tier_status = self._build_tier_status_info(tier_name, tier_config)
            if tier_status is not None:
                status["tiers"][tier_name] = tier_status

        return status

    def get_two_tier_status(self) -> Dict[str, Any]:
        """全ティアのステータスを取得（互換性維持用のエイリアス）"""
        return self.get_all_tiers_status()

    def _get_tier_status(self, usage_ratio: float, preserve_ratio: float) -> str:
        if usage_ratio >= 1.0:
            return "exhausted"
        elif usage_ratio >= (1.0 - preserve_ratio):
            return "preserved"
        elif usage_ratio >= STATUS_WARNING_THRESHOLD:
            return "warning"
        elif usage_ratio >= STATUS_CAUTION_THRESHOLD:
            return "caution"
        return "normal"

    def _lookup_tier_by_model(self, preferred_model: str) -> str:
        """モデル名からティア名を逆引き"""
        for tn, tc in self.model_tiers.items():
            if isinstance(tc, dict) and tc.get("model") == preferred_model:
                return tn
        return "standard"

    def get_available_model(
        self, preferred_model: str, task: str = ""
    ) -> Dict[str, Any]:
        """
        指定された優先モデルに基づいて、利用可能なモデルを取得します（後方互換性維持用）。

        Args:
            preferred_model (str): 優先的に使用したいモデル名。このモデルに対応するティアを逆引きして解決します。
            task (str): 実行タスク名。互換性維持のために定義されていますが、内部ロジックでは現在使用されていません。

        Returns:
            Dict[str, Any]: 利用可能なモデル名、切り替え（フォールバック）が発生したかどうかのフラグ、
                             元の優先モデル名、および利用可能かどうかの判定を含む辞書。
        """
        tier_name = self._lookup_tier_by_model(preferred_model)

        result = self.get_model_with_wait_option(tier_name, task, allow_fallback=True)
        return {
            "model": result.get("model"),
            "switched": result.get("switched", False),
            "original": preferred_model,
            "available": result.get("available", False)
        }

    def get_all_models_status(self) -> Dict[str, Any]:
        """全モデルのステータスを取得（互換性維持用のエイリアス）"""
        return self.get_all_tiers_status()


# シングルトンインスタンス
quota_manager = QuotaManager()
