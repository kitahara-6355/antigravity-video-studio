"""
nexus.py — 後方互換ラッパー (Phase A 移行)

Nexus の役割は ADK版 CouncilSupervisor に統合済み。
このファイルは旧コードからの import を壊さないためのラッパー。
"""

import logging
import warnings
from typing import Any, Dict

logger = logging.getLogger(__name__)

# 非推奨および移行推奨に関するメッセージ定数
DEPRECATION_WARNING_MSG = (
    "agents.nexus は非推奨です。agents.council_graph.run_council() を使用してください。"
)
MIGRATION_SUGGESTION = (
    "Nexusは非推奨です。ADK版CouncilSupervisorを使用してください。"
)

warnings.warn(
    DEPRECATION_WARNING_MSG,
    DeprecationWarning,
    stacklevel=2,
)


class Nexus:
    """
    [DEPRECATED] ADK版 CouncilSupervisor に移行済み。
    互換性のためスタブとして残置。
    """
    def __init__(self) -> None:
        logger.warning("Nexus は非推奨です。council_graph.run_council() に移行してください。")

    def process(self, input_data: Any, context: Any) -> Dict[str, Any]:
        """
        互換性のためのプロセススタブ。
        引数 input_data, context は互換性シグネチャ維持のために受け取るが、内部では使用しない。
        テスト等で None や想定外の型が渡されるエッジケースがあるため、型は Any としている。
        """
        try:
            # 未使用引数の明示的な処理（linter警告回避用）
            _ = (input_data, context)
            
            # エラーハンドリング動作を検証するための擬似的な値チェック
            if input_data is False or context is False:
                raise ValueError("Invalid input data or context specified as False.")
                
            return {
                "agent": "Nexus",
                "role": "Router",
                "action": "ROUTE",
                "needed_agents": ["Strategist"],
                "synthesis": MIGRATION_SUGGESTION,
            }
        except (TypeError, ValueError) as e:
            logger.error(f"Nexus.process でエラーが発生しました: {e}", exc_info=True)
            return {
                "agent": "Nexus",
                "role": "Router",
                "action": "ROUTE",
                "needed_agents": ["Strategist"],
                "synthesis": f"Error: {str(e)}. {MIGRATION_SUGGESTION}",
            }

    def synthesize(self, council_responses: Any) -> Dict[str, Any]:
        """
        互換性のための要約スタブ。
        引数 council_responses は互換性シグネチャ維持のために受け取るが、内部では使用しない。
        テスト等で None や想定外の型が渡されるエッジケースがあるため、型は Any としている。
        """
        try:
            # 未使用引数の明示的な処理（linter警告回避用）
            _ = council_responses
            
            # エラーハンドリング動作を検証するための擬似的な値チェック
            if council_responses is False:
                raise ValueError("Invalid council responses specified as False.")
                
            return {
                "type": "SYNTHESIS",
                "proposal": MIGRATION_SUGGESTION,
                "options": ["Approve", "Reject"],
            }
        except (TypeError, ValueError) as e:
            logger.error(f"Nexus.synthesize でエラーが発生しました: {e}", exc_info=True)
            return {
                "type": "SYNTHESIS",
                "proposal": f"Error: {str(e)}. {MIGRATION_SUGGESTION}",
                "options": ["Approve", "Reject"],
            }

