"""
evolution_log_migration — evolution_logスキーマバージョニング

Sprint 4.3.1 m-04: schema_version管理 + マイグレーション関数

設計書: sprint_43_storage_coverage_design.md §3.2
憲法: §12.3 上書き禁止(appendのみ) — マイグレーションは既存フィールドを非破壊で初期化
"""
import logging
from typing import Dict, Optional


logger = logging.getLogger(__name__)

# 現行スキーマバージョン
CURRENT_SCHEMA_VERSION = "2.0"

# スキーマ2.0で必須のフィールドとデフォルト値
_SCHEMA_2_0_DEFAULTS = {
    "entries": [],
    "philosophies": [],
    "decision_insights": [],
    "trust_score": 0.0,
    "trust_history": [],
    "pending_proposals": [],
    "trigger_history": [],
    "notifications": [],
    "director_profile": {},
    "rejection_history": [],
    "session_count": 0,
    "rejection_count": 0,
    "approval_count": 0,
}


def _validate_and_initialize(evo_log: Optional[Dict]) -> Dict:
    """入力引数を検証し、辞書として初期化する。"""
    if evo_log is None:
        return {}
    if not isinstance(evo_log, dict):
        raise TypeError("evo_log must be a dictionary or None")
    return evo_log


def _log_migration_start(current_version: Optional[str]) -> None:
    """マイグレーション開始時のログを出力する。"""
    if current_version is None:
        logger.info(
            "[EvolutionLogMigration] schema_version未設定 → 2.0にマイグレーション"
        )
    else:
        logger.info(
            f"[EvolutionLogMigration] schema_version {current_version} → 2.0"
        )


def _apply_schema_defaults(evo_log: Dict) -> None:
    """スキーマ2.0のデフォルト必須フィールドを非破壊的に適用する。"""
    evo_log["schema_version"] = CURRENT_SCHEMA_VERSION
    for field_name, default_value in _SCHEMA_2_0_DEFAULTS.items():
        evo_log.setdefault(field_name, default_value)


def migrate_evolution_log(evo_log: Optional[Dict]) -> Dict:
    """evolution_logをスキーマ2.0にマイグレーション (m-04)

    schema_version未設定 → "2.0" に昇格。
    全必須フィールドを非破壊で初期化(setdefault)。

    §12.3準拠: 既存データを上書きせず、欠落フィールドのみ追加。

    Args:
        evo_log: evolution_logの辞書データ、またはNone

    Returns:
        マイグレーション済みのevo_log
    """
    try:
        evo_log = _validate_and_initialize(evo_log)

        current_version = evo_log.get("schema_version")
        if current_version == CURRENT_SCHEMA_VERSION:
            return evo_log

        _log_migration_start(current_version)
        _apply_schema_defaults(evo_log)

        return evo_log
    except Exception as e:
        logger.error(
            f"[EvolutionLogMigration] マイグレーション実行中に例外が発生しました: {e}",
            exc_info=True
        )
        raise
