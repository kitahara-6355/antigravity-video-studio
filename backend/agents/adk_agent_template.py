"""
ADK Agent テンプレート — Google Agent Development Kit 基盤

HI-01 対応: Phase 6 以降の新規エージェント開発で使用する
ADK ベース of テンプレート。

使い方:
    from agents.adk_agent_template import create_agent

    # 最小構成
    agent = create_agent(
        name="my_agent",
        instruction="あなたは○○の専門家です。",
        tools=[my_custom_tool]
    )

    # 実行
    from google.adk.runners import InMemoryRunner
    runner = InMemoryRunner(agent=agent, app_name="my_app")

設計方針:
- google.adk.agents.Agent をラップ
- GeminiClientFactory との共存（API Key ベース運用を維持）
- model_registry.py との連携
- 既存コードベースへの侵入ゼロ（新規エージェント専用）
"""

import os
import logging
from typing import List, Optional, Callable, Any

logger = logging.getLogger(__name__)

# ========================================================
# デフォルト設定と Model Registry 連携
# ========================================================
try:
    from model_registry import get_model
    HAS_MODEL_REGISTRY = True
except ImportError:
    HAS_MODEL_REGISTRY = False
    get_model = None

try:
    DEFAULT_MODEL = get_model("supervisor") if HAS_MODEL_REGISTRY and get_model is not None else "gemini-2.5-flash"
except (ValueError, TypeError, KeyError, AttributeError, RuntimeError) as e:
    logger.warning(f"Failed to get supervisor model from registry, falling back to gemini-2.5-flash: {e}")
    DEFAULT_MODEL = "gemini-2.5-flash"


def _resolve_model_from_registry(task: str = "supervisor") -> str:
    """Model Registry から推奨モデルを取得（フォールバック付き）"""
    if HAS_MODEL_REGISTRY and get_model is not None:
        try:
            return get_model(task)
        except (ValueError, TypeError, KeyError, AttributeError, RuntimeError) as e:
            logger.warning(f"Failed to get model for task '{task}' from registry, falling back to {DEFAULT_MODEL}: {e}")
            return DEFAULT_MODEL
    return DEFAULT_MODEL


# 後方互換性のためのエイリアス
_get_default_model = _resolve_model_from_registry


def _verify_adk_installed() -> Any:
    """
    google-adk パッケージのインストールを検証し、Agent クラスを返す。
    
    Raises:
        ImportError: パッケージがインストールされていない場合
    """
    try:
        from google.adk.agents import Agent
        return Agent
    except ImportError:
        logger.error(
            "google-adk パッケージがインストールされていません。"
            "pip install google-adk を実行してください。"
        )
        raise


def _build_agent_kwargs(
    name: str,
    instruction: str,
    model_name: str,
    description: str = "",
    tools: Optional[List[Callable]] = None,
    sub_agents: Optional[List] = None,
    output_key: Optional[str] = None,
) -> dict:
    """Agent 生成に必要なキーワード引数辞書を構築する。"""
    agent_kwargs = {
        "name": name,
        "model": model_name,
        "instruction": instruction,
        "description": description or f"{name} agent",
    }

    if tools:
        agent_kwargs["tools"] = tools

    if sub_agents:
        agent_kwargs["sub_agents"] = sub_agents

    if output_key:
        agent_kwargs["output_key"] = output_key

    return agent_kwargs


def create_agent(
    name: str,
    instruction: str,
    tools: Optional[List[Callable]] = None,
    model: Optional[str] = None,
    description: str = "",
    sub_agents: Optional[List] = None,
    output_key: Optional[str] = None,
) -> Any:
    """
    ADK Agent を生成するファクトリ関数。

    Args:
        name: エージェント名（英数字_のみ）
        instruction: システムプロンプト
        tools: エージェントが使用するツール関数のリスト
        model: 使用する Gemini モデル名（None の場合は Registry から取得）
        description: エージェントの説明
        sub_agents: サブエージェントのリスト（マルチエージェント構成用）
        output_key: 出力をセッション state に保存するキー名

    Returns:
        google.adk.agents.Agent インスタンス、または例外発生時は None

    Raises:
        ImportError: google-adk がインストールされていない場合
    """
    try:
        Agent = _verify_adk_installed()
        model_name = model or _resolve_model_from_registry()

        agent_kwargs = _build_agent_kwargs(
            name=name,
            instruction=instruction,
            model_name=model_name,
            description=description,
            tools=tools,
            sub_agents=sub_agents,
            output_key=output_key,
        )

        agent = Agent(**agent_kwargs)

        logger.info(
            f"✅ [ADK] エージェント作成: {name} "
            f"(model={model_name}, tools={len(tools or [])}, "
            f"sub_agents={len(sub_agents or [])})"
        )

        return agent
    except ImportError:
        raise
    except Exception as e:
        logger.exception(f"Failed to create agent '{name}': {e}")
        return None


def execute_agent_run(agent: Any, query: str) -> tuple[bool, Any]:
    """
    エージェントを実行し、結果を返す。例外発生時は適切にロギングとエラー返却を行う。

    Args:
        agent: 実行対象のエージェント
        query: クエリ文字列

    Returns:
        (success_flag, result) のタプル
    """
    try:
        result = agent.run(query)
        return True, result
    except Exception as e:
        logger.exception(f"Agent execution failed: {e}")
        return False, None



def _generate_council_instruction(role: str, expertise: str) -> str:
    """Council of Minds エージェント用のプロンプト (instruction) を生成する。"""
    return f"""あなたは「Council of Minds（議会）」の{role}です。

## 専門分野
{expertise}

## 行動規範
1. あなたの専門分野に基づいて、具体的かつ実行可能な提案をしてください。
2. ブランド憲法（Constitution）を常に尊重してください。
3. 他のエージェントとの協調を重視してください。
4. 回答は日本語で行ってください。
"""


def create_council_agent(
    name: str,
    role: str,
    expertise: str,
    tools: Optional[List[Callable]] = None,
    model: Optional[str] = None,
) -> Any:
    """
    Council of Minds 用の専門家エージェントを生成する。

    Args:
        name: エージェント名
        role: 役割（例: "Analyst", "Strategist", "Director"）
        expertise: 専門分野の説明
        tools: エージェントが使用するツール
        model: 使用モデル

    Returns:
        Agent インスタンス
    """
    instruction = _generate_council_instruction(role, expertise)

    return create_agent(
        name=name,
        instruction=instruction,
        description=f"Council of Minds - {role}: {expertise}",
        tools=tools,
        model=model,
    )


# ========================================================
# ユーティリティ: ツール定義ヘルパー
# ========================================================

def tool(func: Callable) -> Callable:
    """
    ADK ツールとして関数を登録するデコレータ。

    ADK は型ヒントと docstring からスキーマを自動生成するため、
    このデコレータは主にドキュメントとして機能する。

    Usage:
        @tool
        def search_assets(query: str, category: str = "all") -> str:
            \"\"\"アセットライブラリを検索します。\"\"\"
            ...
    """
    func._is_adk_tool = True
    return func
