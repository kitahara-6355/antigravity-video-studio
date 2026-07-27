"""
supervisor.py — 後方互換ラッパー (Phase A 移行)

Supervisor の役割は ADK版 CouncilSupervisor に統合済み。
このファイルは旧コードからの import を壊さないためのラッパー。
"""

import warnings
import logging

logger = logging.getLogger(__name__)

warnings.warn(
    "agents.supervisor は非推奨です。agents.council_graph.run_council() を使用してください。",
    DeprecationWarning,
    stacklevel=2,
)


class SupervisorAgent:
    """
    [DEPRECATED] ADK版 CouncilSupervisor に移行済み。
    互換性のためスタブとして残置。
    """
    def __init__(self):
        logger.warning("SupervisorAgent は非推奨です。council_graph.run_council() に移行してください。")

    def route(self, messages: list):
        from pydantic import BaseModel
        from typing import Literal

        class Route(BaseModel):
            next: Literal["Analyst", "Strategist", "Director", "FINISH"]
            reason: str

        return Route(next="FINISH", reason="SupervisorAgent は非推奨です。ADK版に移行済み。")
