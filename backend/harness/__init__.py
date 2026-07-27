"""
Antigravity Harness — Anthropic推奨パターンによるエージェント制御フレームワーク

Anthropic「Building Effective Agents」+ 「Claude Managed Agents」の設計思想を
既存の Gemini + FastAPI アーキテクチャに適用。

Phase 1 — 基盤層:
  1. ToolRegistry  — MCP準拠のツール定義（ACI最適化）
  2. HookSystem    — Pre/Post/Failure フックによるツール実行制御
  3. SessionManager — セッション持続性とリジューム
  4. Governance     — スコープ付き権限・実行トレース

Phase 2 — エージェント統合:
  5. pipeline_tools — 7ステージのMCP準拠ツール登録
  6. EvaluatorOptimizer — 品質改善ループの構造化

設計原則（Anthropic "Building Effective Agents" 準拠）:
  - シンプルさを維持: フレームワーク抽象を最小化
  - 透明性: 全ツール呼び出しをフックで監査ログ記録
  - ACI（Agent-Computer Interface）に投資: ツール定義を精緻化
  - Poka-yoke: 引数検証でミスを構造的に不可能にする
  - Evaluator-Optimizer: 品質改善を構造化されたループで実行
"""

__version__ = "2.0.0"

from harness.tool_registry import ToolRegistry, ToolDefinition, tool_registry
from harness.hooks import HookSystem, HookEvent, hook_system
from harness.session_manager import SessionManager, session_manager
from harness.governance import GovernanceEngine, governance_engine

__all__ = [
    # Phase 1 — 基盤層
    "ToolRegistry",
    "ToolDefinition",
    "tool_registry",
    "HookSystem",
    "HookEvent",
    "hook_system",
    "SessionManager",
    "session_manager",
    "GovernanceEngine",
    "governance_engine",
    # Phase 2 — エージェント統合（遅延import）
    "register_pipeline_tools",
    "evaluator_optimizer",
]


def register_pipeline_tools():
    """7つのパイプラインツールをToolRegistryに登録"""
    from harness.pipeline_tools import register_pipeline_tools as _register
    _register()


def get_evaluator_optimizer():
    """Evaluator-Optimizer ワークフローを取得（遅延import）"""
    from harness.evaluator_optimizer import evaluator_optimizer
    return evaluator_optimizer
