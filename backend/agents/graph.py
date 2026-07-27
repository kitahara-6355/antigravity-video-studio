"""
graph.py — 後方互換ラッパー (Phase A-3 移行)

LangGraph 実装は council_graph.py (ADK版) に完全移行済み。
このファイルは旧コードとの互換性のため残置し、新実装に委譲する。

旧依存（削除済み）:
  - langgraph.graph.StateGraph
  - langchain_core.messages.BaseMessage / HumanMessage / AIMessage
  - langchain_core.messages.add_messages
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ADK版を公開 API として再エクスポート
from agents.council_graph import run_council, _fallback_response  # noqa: F401


async def run_graph(
    query: str,
    council_mode: str = "post_production",
    session_id: Optional[str] = None,
) -> dict:
    """
    旧 council_graph.stream() の代替。
    ADK版 run_council() に委譲する。
    """
    try:
        # 入力バリデーションガード
        if query is None or not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string.")
        if council_mode not in ("pre_production", "post_production"):
            raise ValueError("council_mode must be 'pre_production' or 'post_production'.")
        if session_id is not None and (not isinstance(session_id, str) or not session_id.strip()):
            raise ValueError("session_id must be a non-empty string if provided.")

        logger.info(f"[graph.py] run_graph → council_graph.run_council に委譲 (mode={council_mode})")
        return await run_council(
            user_query=query,
            council_mode=council_mode,
            session_id=session_id,
        )
    except ValueError:
        # バリデーションエラーおよび明示的なValueErrorはそのまま伝播
        raise
    except Exception as e:
        logger.error(f"[graph.py] Unexpected error in run_graph: {e}", exc_info=True)
        try:
            from agents.memory.technical_debt import technical_debt_store
            technical_debt_store.register_debt(
                category="MINOR_INFRA",
                file_path="backend/agents/graph.py",
                line_number=49,
                pattern="except Exception as e: in run_graph",
                cause_pattern="DP-01",
                fix_pattern="例外の再送出",
                registered_by="thumbnail_task_22",
                notes=f"run_graphで想定外のエラーが発生: {str(e)}",
            )
        except Exception as tdr_err:
            logger.error(f"Failed to register debt in run_graph: {tdr_err}")
        raise
