"""
Alert System - 無料枠アラートシステム

PROJECT_CONSTITUTION §18.4 準拠
"""
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class AlertLevel(Enum):
    """アラートレベル"""
    NORMAL = "normal"
    INFO = "info"
    WARNING = "warning"
    BLOCK = "block"
    CRITICAL = "critical"


class AlertSystem:
    """
    アラートシステム
    
    使用量に応じてアラートを発動し、
    必要に応じて処理をブロックする。
    """
    
    # ログ出力用マッピングテーブル (レベル -> (loggerメソッド名, プレフィックス))
    # テストによる logger のパッチを有効にするため、メソッド名文字列で保持する
    _LOG_MAP = {
        AlertLevel.CRITICAL: ("critical", "🛑 CRITICAL"),
        AlertLevel.BLOCK: ("error", "🛑 BLOCK"),
        AlertLevel.WARNING: ("warning", "⚠️ WARNING"),
        AlertLevel.INFO: ("info", "ℹ️ INFO"),
    }
    
    def __init__(self):
        self._handlers: Dict[AlertLevel, List[Callable[[Dict[str, Any]], None]]] = {
            level: [] for level in AlertLevel
        }
        self._history: List[Dict[str, Any]] = []
        self._max_history: int = 100
    
    def register_handler(
        self,
        level: AlertLevel,
        handler: Callable[[Dict[str, Any]], None]
    ) -> None:
        """アラートハンドラーを登録"""
        self._handlers[level].append(handler)
    
    def emit(
        self,
        level: AlertLevel,
        model: str,
        message: str,
        data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        アラートを発行
        
        Args:
            level: アラートレベル
            model: モデル名
            message: メッセージ
            data: 追加データ
        
        Returns:
            アラート情報
        """
        alert = {
            "timestamp": datetime.now().isoformat(),
            "level": level.value,
            "model": model,
            "message": message,
            "data": data or {}
        }
        
        self._add_to_history(alert)
        self._log_alert(level, model, message)
        self._run_handlers(level, alert)
        
        return alert

    def _add_to_history(self, alert: Dict[str, Any]) -> None:
        """アラートを履歴に追加し、上限を超えた場合は古いものを切り捨てる"""
        self._history.append(alert)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

    def _run_handlers(self, level: AlertLevel, alert: Dict[str, Any]) -> None:
        """登録されたハンドラーを順に実行する"""
        for handler in self._handlers.get(level, []):
            try:
                handler(alert)
            except Exception as e:
                logger.error(f"Alert handler failed: {e}")

    def _log_alert(self, level: AlertLevel, model: str, message: str) -> None:
        """アラートレベルに応じたログ出力"""
        if log_info := self._LOG_MAP.get(level):
            method_name, prefix = log_info
            log_func = getattr(logger, method_name)
            log_func(f"{prefix} [{model}]: {message}")
    
    def get_recent_alerts(
        self,
        level: Optional[AlertLevel] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """最近のアラートを取得"""
        alerts = self._history
        
        if level:
            alerts = [a for a in alerts if a["level"] == level.value]
        
        return alerts[-limit:]
    
    def _is_active_block_alert(
        self,
        alert: dict,
        model: str,
        today: str,
        block_levels: set
    ) -> bool:
        """指定したアラートが今日の指定モデルに対するアクティブなブロックアラートであるか判定"""
        return (
            alert["model"] == model and
            alert["level"] in block_levels and
            alert["timestamp"].startswith(today)
        )

    def has_active_block(self, model: str) -> bool:
        """ブロックアラートがアクティブか"""
        today = datetime.now().date().isoformat()
        block_levels = {AlertLevel.BLOCK.value, AlertLevel.CRITICAL.value}
        
        return any(
            self._is_active_block_alert(alert, model, today, block_levels)
            for alert in reversed(self._history)
        )


# シングルトンインスタンス
alert_system = AlertSystem()


# 便利なヘルパー関数
def emit_info(model: str, message: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """INFO アラートを発行"""
    return alert_system.emit(AlertLevel.INFO, model, message, data)


def emit_warning(model: str, message: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """WARNING アラートを発行"""
    return alert_system.emit(AlertLevel.WARNING, model, message, data)


def emit_block(model: str, message: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """BLOCK アラートを発行"""
    return alert_system.emit(AlertLevel.BLOCK, model, message, data)


def emit_critical(model: str, message: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """CRITICAL アラートを発行"""
    return alert_system.emit(AlertLevel.CRITICAL, model, message, data)



from agents.council_graph import ThumbnailResolver
