"""
expert_collaboration.py — Council of Minds マルチパス・コラボレーション
Phase A-1 改修: CouncilContext シングルトン廃止 → リクエストスコープに変更
  - モジュールレベルのシングルトン `council_context` を削除
  - 全関数が CouncilContext を生成・受け取るように変更
  - 並行リクエスト時のセッション状態混線を根本解消
"""
import logging
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class CouncilContext:
    """
    Council of Minds の共有メモリ。
    エージェントが知見を投稿し、互いの思考を参照するためのコンテキスト。

    リクエストスコープで生成すること（シングルトン禁止）。
    """
    def __init__(self):
        self.data: Dict[str, Any] = {
            "findings": {},        # { agent_name: findings_text }
            "shared_variables": {},  # { key: value }
            "last_update": time.time()
        }

    def post_finding(self, agent_name: str, text: str) -> None:
        self.data["findings"][agent_name] = text
        self.data["last_update"] = time.time()

    def get_findings(self) -> Dict[str, str]:
        return self.data["findings"]

    def clear(self) -> None:
        self.data["findings"] = {}
        self.data["last_update"] = time.time()


def new_context() -> CouncilContext:
    """
    リクエストごとに新しい CouncilContext を生成するファクトリ。
    FastAPI エンドポイントから呼び出す場合はここを使う。
    """
    return CouncilContext()


def _extract_finding(res: Dict[str, Any]) -> str:
    """エージェントのレスポンスから知見（finding）の文字列を抽出する"""
    return f"{res.get('stance', 'NEUTRAL')}: {res.get('summary', '')}"


def _process_parallel_pass1(agent: Any, input_data: Dict[str, Any]) -> tuple:
    """並列処理におけるPass 1の個別エージェント処理"""
    try:
        res = agent.process(input_data, {})
        finding = _extract_finding(res)
        return agent.name, finding, res
    except Exception as e:
        logger.warning(f"Parallel collaboration error in {agent.name} Pass 1: {e}", exc_info=True)
        return agent.name, "ERROR", {"error": str(e)}


def _process_parallel_pass2(agent: Any, input_data: Dict[str, Any], council_context: CouncilContext) -> tuple:
    """並列処理におけるPass 2の個別エージェント処理"""
    try:
        res = agent.process(input_data, {}, council_context=council_context)
        return agent.name, res
    except Exception as e:
        logger.warning(f"Parallel collaboration error in {agent.name} Pass 2: {e}", exc_info=True)
        return agent.name, {"error": str(e)}


async def _process_async(agent: Any, input_data: Dict[str, Any], pass_num: int, council_context: Optional[CouncilContext] = None) -> tuple:
    """非同期処理における個別エージェント処理"""
    loop = asyncio.get_event_loop()
    if pass_num == 1:
        result = await loop.run_in_executor(
            None,
            lambda: agent.process(input_data, {})
        )
    else:
        result = await loop.run_in_executor(
            None,
            lambda: agent.process(input_data, {}, council_context=council_context)
        )
    return agent.name, result


# ============================================
# Phase 7: マルチパス・コラボレーション（逐次実行）
# ============================================

def collaborate(
    agents: list,
    user_query: str,
    ctx: Optional[CouncilContext] = None,
) -> List[Dict[str, Any]]:
    """
    [DEPRECATED] ADK版 council_graph.run_council() に移行してください。

    逐次マルチパス・コラボレーション。

    Args:
        agents: エージェントのリスト
        user_query: ユーザークエリ
        ctx: CouncilContext（省略時は自動生成）

    Returns:
        各エージェントの最終回答リスト
    """
    council_context = ctx or CouncilContext()
    input_data = {"text": user_query}
    council_context.clear()

    # --- Pass 1: 個別インサイト ---
    for agent in agents:
        try:
            res = agent.process(input_data, {})
            finding = _extract_finding(res)
            council_context.post_finding(agent.name, finding)
        except Exception as e:
            logger.warning(f"Sequential collaboration error in {agent.name} Pass 1: {e}", exc_info=True)

    # --- Pass 2: 統合アドバイス ---
    final_responses = []
    for agent in agents:
        try:
            res = agent.process(input_data, {}, council_context=council_context)
            final_responses.append(res)
        except Exception as e:
            logger.warning(f"Sequential collaboration error in {agent.name} Pass 2: {e}", exc_info=True)

    return final_responses


# ============================================
# Phase 7: マルチパス・コラボレーション（並列実行）
# ============================================

def collaborate_parallel(
    agents: list,
    user_query: str,
    ctx: Optional[CouncilContext] = None,
) -> Dict[str, Any]:
    """
    [DEPRECATED] ADK版 council_graph.run_council() に移行してください。

    並列マルチパス・コラボレーション。

    Pass 1: 全エージェントが並列で初期分析
    Pass 2: 互いの結果を参照しながら再分析
    Pass 3: 結果の統合・合成

    Args:
        agents: エージェントのリスト
        user_query: ユーザークエリ
        ctx: CouncilContext（省略時は自動生成）

    Returns:
        統合されたレスポンスと各エージェントの知見
    """
    council_context = ctx or CouncilContext()
    input_data = {"text": user_query}
    council_context.clear()

    if not agents:
        return {
            "responses": {},
            "findings": {},
            "meta": {
                "total_time": 0.0,
                "pass1_time": 0.0,
                "pass2_time": 0.0,
                "agent_count": 0,
            },
        }

    start_time = time.time()

    # --- Pass 1: 並列初期分析 ---
    logger.info("Pass 1: 並列初期分析開始")

    with ThreadPoolExecutor(max_workers=len(agents)) as executor:
        pass1_results = list(executor.map(lambda a: _process_parallel_pass1(a, input_data), agents))

    for name, finding, _ in pass1_results:
        council_context.post_finding(name, finding)

    pass1_time = time.time() - start_time
    logger.info(f"Pass 1 完了: {pass1_time:.2f}秒")

    # --- Pass 2: 並列統合分析 ---
    logger.info("Pass 2: 他者の知見を参照して再分析開始")

    with ThreadPoolExecutor(max_workers=len(agents)) as executor:
        pass2_results = list(executor.map(lambda a: _process_parallel_pass2(a, input_data, council_context), agents))

    pass2_time = time.time() - start_time - pass1_time
    logger.info(f"Pass 2 完了: {pass2_time:.2f}秒")

    # --- Pass 3: 結果統合 ---
    final_responses = {name: res for name, res in pass2_results}
    total_time = time.time() - start_time

    return {
        "responses": final_responses,
        "findings": council_context.get_findings(),
        "meta": {
            "total_time": total_time,
            "pass1_time": pass1_time,
            "pass2_time": pass2_time,
            "agent_count": len(agents),
        },
    }


async def collaborate_async(
    agents: list,
    user_query: str,
    ctx: Optional[CouncilContext] = None,
) -> Dict[str, Any]:
    """
    [DEPRECATED] ADK版 council_graph.run_council() に移行してください。

    非同期版マルチパス・コラボレーション。

    Args:
        agents: エージェントのリスト
        user_query: ユーザークエリ
        ctx: CouncilContext（省略時は自動生成）

    Returns:
        統合されたレスポンスと各エージェントの知見
    """
    council_context = ctx or CouncilContext()
    input_data = {"text": user_query}
    council_context.clear()

    if not agents:
        return {
            "responses": {},
            "findings": {},
            "meta": {
                "total_time": 0.0,
                "async": True,
            },
        }

    start_time = time.time()

    # Pass 1
    logger.info("Async Pass 1 開始")
    tasks = [_process_async(agent, input_data, 1) for agent in agents]
    pass1_results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in pass1_results:
        if not isinstance(result, Exception):
            name, res = result
            finding = _extract_finding(res)
            council_context.post_finding(name, finding)

    # Pass 2
    logger.info("Async Pass 2 開始")
    tasks = [_process_async(agent, input_data, 2, council_context) for agent in agents]
    pass2_results = await asyncio.gather(*tasks, return_exceptions=True)

    final_responses = {}
    for result in pass2_results:
        if not isinstance(result, Exception):
            name, res = result
            final_responses[name] = res

    total_time = time.time() - start_time

    return {
        "responses": final_responses,
        "findings": council_context.get_findings(),
        "meta": {
            "total_time": total_time,
            "async": True,
        },
    }
