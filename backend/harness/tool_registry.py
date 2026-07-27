"""
ToolRegistry — MCP準拠のツール定義レジストリ

Anthropic推奨の ACI（Agent-Computer Interface）パターンを実装。
Claude Agent SDK の @tool + create_sdk_mcp_server の概念を
SDK非依存で再現する。

設計思想（Anthropic "Building Effective Agents" Appendix 2 準拠）:
  - ツールの description にHCIと同レベルの投資をする
  - ジュニアエンジニアが読んでも使い方が明確な docstring
  - Poka-yoke: 引数検証でミスを構造的に不可能にする
  - 絶対パスを強制（相対パスからのバグを根絶）
  - エラー時は is_error フラグでエージェントループを生存させる

Usage:
    from harness.tool_registry import tool_registry

    @tool_registry.register(
        name="transcribe_video",
        description="動画ファイルを文字起こしし、タイムスタンプ付き字幕データを返す",
        input_schema={"video_path": str, "language": str},
        annotations={"readOnlyHint": False, "destructiveHint": False},
    )
    async def transcribe_video(args: dict) -> dict:
        ...

    # 実行
    result = await tool_registry.execute("transcribe_video", {"video_path": "...", "language": "ja"})
"""

import json
import logging
import time
import asyncio
import functools
from pathlib import Path
from typing import (
    Any, Callable, Dict, List, Optional, Set,
)
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


# ============================================================
# データ構造
# ============================================================

@dataclass
class ToolAnnotations:
    """MCP Tool Annotations 準拠のツールメタデータ"""
    readOnlyHint: bool = False      # 読み取り専用ツール（バッチ実行可能）
    destructiveHint: bool = False   # 破壊的操作（確認が必要）
    idempotentHint: bool = True     # 冪等性（リトライ安全）
    openWorldHint: bool = False     # 外部リソースアクセス


@dataclass
class ToolDefinition:
    """
    MCP準拠のツール定義。

    Claude Agent SDK の @tool デコレータが生成するメタデータと同等の情報を保持。
    description は日本語で精緻に定義し、ACI品質を最大化する。
    """
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Callable
    annotations: ToolAnnotations = field(default_factory=ToolAnnotations)
    # ACI強化: 使用例とエッジケース
    examples: List[Dict] = field(default_factory=list)
    error_hints: List[str] = field(default_factory=list)
    # ガバナンス: 必要な権限スコープ
    required_scopes: Set[str] = field(default_factory=set)
    # 統計
    call_count: int = 0
    total_duration_seconds: float = 0.0
    error_count: int = 0


@dataclass
class ToolResult:
    """ツール実行結果（MCP content 形式準拠）"""
    content: List[Dict[str, Any]]
    is_error: bool = False
    duration_seconds: float = 0.0
    tool_name: str = ""


# ============================================================
# ツールレジストリ
# ============================================================

class ToolRegistry:
    """
    MCP準拠のツールレジストリ。

    Anthropic の ACI（Agent-Computer Interface）ベストプラクティスに基づく:
    1. 全ツールの統一登録・検索
    2. 引数の自動バリデーション（Poka-yoke）
    3. 実行統計の蓄積
    4. Hookシステムとの連携ポイント

    Claude Agent SDK の create_sdk_mcp_server 相当の機能をSDK非依存で実現。
    """

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
        self._server_name: str = "antigravity_pipeline"
        self._server_version: str = "2.0.0"

    # ============================================================
    # ツール登録
    # ============================================================

    def register(
        self,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        annotations: Optional[Dict[str, bool]] = None,
        examples: Optional[List[Dict]] = None,
        error_hints: Optional[List[str]] = None,
        required_scopes: Optional[Set[str]] = None,
    ) -> Callable:
        """
        デコレータ: ツールをレジストリに登録。

        Usage:
            @tool_registry.register(
                name="transcribe_video",
                description="動画ファイルを文字起こし",
                input_schema={"video_path": str, "language": str},
            )
            async def transcribe_video(args: dict) -> dict:
                ...
        """
        def decorator(func: Callable) -> Callable:
            tool_annotations = ToolAnnotations(**(annotations or {}))
            tool_def = ToolDefinition(
                name=name,
                description=description,
                input_schema=input_schema,
                handler=func,
                annotations=tool_annotations,
                examples=examples or [],
                error_hints=error_hints or [],
                required_scopes=required_scopes or set(),
            )
            self._tools[name] = tool_def
            logger.info(f"🔧 Tool registered: {name}")

            func._tool_definition = tool_def
            return func

        return decorator

    def register_tool(self, tool_def: ToolDefinition) -> None:
        """直接 ToolDefinition を登録（プログラマティック登録）"""
        self._tools[tool_def.name] = tool_def
        logger.info(f"🔧 Tool registered (direct): {tool_def.name}")

    # ============================================================
    # ツール実行
    # ============================================================

    async def execute(
        self,
        tool_name: str,
        args: Dict[str, Any],
        caller_scopes: Optional[Set[str]] = None,
    ) -> ToolResult:
        """
        ツールを実行。

        実行フロー:
        1. ツール存在チェック
        2. 権限スコープ検証（ガバナンス）
        3. 引数バリデーション（Poka-yoke）
        4. ハンドラ実行
        5. 統計更新
        6. 結果をMCP content形式で返す

        Args:
            tool_name: ツール名
            args: ツール引数
            caller_scopes: 呼び出し元の権限スコープ

        Returns:
            ToolResult（MCP content形式）
        """
        tool_def = self._tools.get(tool_name)
        if not tool_def:
            return ToolResult(
                content=[{"type": "text", "text": f"ツール '{tool_name}' が見つかりません"}],
                is_error=True,
                tool_name=tool_name,
            )

        # ガバナンス: 権限スコープチェック
        scope_error = self._verify_scopes(tool_def, caller_scopes)
        if scope_error:
            return ToolResult(
                content=[{"type": "text", "text": scope_error}],
                is_error=True,
                tool_name=tool_name,
            )

        # Poka-yoke: 引数バリデーション
        validation_error = self._validate_args(tool_def, args)
        if validation_error:
            return ToolResult(
                content=[{"type": "text", "text": validation_error}],
                is_error=True,
                tool_name=tool_name,
            )

        # ツール実行と統計情報の更新
        return await self._execute_handler_with_metrics(tool_def, args)

    def _verify_scopes(
        self, tool_def: ToolDefinition, caller_scopes: Optional[Set[str]]
    ) -> Optional[str]:
        """権限スコープの検証を行う"""
        if tool_def.required_scopes and caller_scopes is not None:
            missing = tool_def.required_scopes - caller_scopes
            if missing:
                return f"権限不足: {tool_def.name} には {missing} スコープが必要です"
        return None

    async def _execute_handler_with_metrics(
        self, tool_def: ToolDefinition, args: Dict[str, Any]
    ) -> ToolResult:
        """ハンドラを実行し、実行統計の更新および結果の正規化を行う"""
        start = time.time()
        try:
            result = await self._call_handler(tool_def.handler, args)
            duration = round(time.time() - start, 2)

            # 統計更新
            tool_def.call_count += 1
            tool_def.total_duration_seconds += duration

            # 結果をMCP content形式に正規化
            return self._normalize_result(result, tool_def.name, duration)

        except (RuntimeError, ValueError, TypeError, KeyError, AttributeError, OSError, asyncio.TimeoutError) as e:
            duration = round(time.time() - start, 2)
            tool_def.error_count += 1

            logger.error(f"ツール実行エラー [{tool_def.name}]: {e}")
            return ToolResult(
                content=[{
                    "type": "text",
                    "text": f"ツール実行エラー: {str(e)[:500]}",
                }],
                is_error=True,
                duration_seconds=duration,
                tool_name=tool_def.name,
            )

    async def _call_handler(
        self, handler: Callable, args: Dict
    ) -> Any:
        """ハンドラを呼び出し（同期/非同期両対応）"""
        if asyncio.iscoroutinefunction(handler):
            return await handler(args)
        else:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, handler, args)

    # ============================================================
    # Poka-yoke バリデーション
    # ============================================================

    def _validate_args(self, tool_def: ToolDefinition, args: Dict) -> Optional[str]:
        """
        引数バリデーション（Poka-yoke）。

        Anthropic SWE-bench の教訓:
        「相対パスで呼ばれるとバグる→絶対パスを強制して誤用を構造的に不可能にした」
        """
        schema = tool_def.input_schema

        # 必須引数チェック
        for key, expected_type in schema.items():
            if key not in args:
                # デフォルト値があるスキーマ定義（dictの場合）は省略可能
                if isinstance(expected_type, dict) and "default" in expected_type:
                    continue
                # 型名がOptionalを含む場合はスキップ
                type_str = str(expected_type)
                if "Optional" in type_str or "None" in type_str:
                    continue
                return f"必須引数 '{key}' が不足しています（ツール: {tool_def.name}）"

        # パス引数の絶対パス強制（Poka-yoke）
        for key in ("video_path", "file_path", "path", "input_path", "output_path"):
            if key in args and isinstance(args[key], str):
                path_val = args[key]
                if path_val and not Path(path_val).is_absolute():
                    # 自動修正: 絶対パスに変換
                    args[key] = str(Path(path_val).resolve())
                    logger.info(
                        f"🔧 Poka-yoke: {key} を絶対パスに変換: {args[key]}"
                    )

        return None

    # ============================================================
    # 結果の正規化
    # ============================================================

    def _normalize_result(
        self, result: Any, tool_name: str, duration: float
    ) -> ToolResult:
        """結果をMCP content形式に正規化"""

        # 既にToolResult形式の場合
        if isinstance(result, ToolResult):
            result.duration_seconds = duration
            result.tool_name = tool_name
            return result

        # dict で content キーがある場合（MCP準拠の直接返却）
        if isinstance(result, dict):
            if "content" in result:
                return ToolResult(
                    content=result["content"],
                    is_error=result.get("is_error", False),
                    duration_seconds=duration,
                    tool_name=tool_name,
                )
            # status/error パターン（既存のJSON形式）
            if result.get("status") == "error":
                return ToolResult(
                    content=[{
                        "type": "text",
                        "text": json.dumps(result, ensure_ascii=False),
                    }],
                    is_error=True,
                    duration_seconds=duration,
                    tool_name=tool_name,
                )
            # 通常のdict結果
            return ToolResult(
                content=[{
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False),
                }],
                is_error=False,
                duration_seconds=duration,
                tool_name=tool_name,
            )

        # 文字列の場合
        if isinstance(result, str):
            try:
                parsed = json.loads(result)
                is_error = isinstance(parsed, dict) and parsed.get("status") == "error"
            except (json.JSONDecodeError, TypeError):
                is_error = False
            return ToolResult(
                content=[{"type": "text", "text": result}],
                is_error=is_error,
                duration_seconds=duration,
                tool_name=tool_name,
            )

        # その他の型
        return ToolResult(
            content=[{"type": "text", "text": str(result)}],
            duration_seconds=duration,
            tool_name=tool_name,
        )

    # ============================================================
    # ツール検索・一覧
    # ============================================================

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """ツール定義を取得"""
        return self._tools.get(name)

    def list_tools(self) -> List[Dict[str, Any]]:
        """
        全ツール一覧（MCP listTools レスポンス互換形式）。

        LLM のツール選択に最適化された情報を返す。
        """
        return [
            {
                "name": f"mcp__{self._server_name}__{t.name}",
                "description": t.description,
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        k: {"type": _python_type_to_json_schema(v)}
                        for k, v in t.input_schema.items()
                    },
                },
                "annotations": {
                    "readOnlyHint": t.annotations.readOnlyHint,
                    "destructiveHint": t.annotations.destructiveHint,
                    "idempotentHint": t.annotations.idempotentHint,
                },
            }
            for t in self._tools.values()
        ]

    def get_stats(self) -> Dict[str, Any]:
        """全ツールの実行統計"""
        return {
            "server": self._server_name,
            "version": self._server_version,
            "tool_count": len(self._tools),
            "tools": {
                name: {
                    "calls": t.call_count,
                    "errors": t.error_count,
                    "total_duration_s": round(t.total_duration_seconds, 1),
                    "avg_duration_s": round(
                        t.total_duration_seconds / max(t.call_count, 1), 2
                    ),
                }
                for name, t in self._tools.items()
            },
        }


# ============================================================
# ヘルパー
# ============================================================

def _python_type_to_json_schema(python_type: Any) -> str:
    """Python 型を JSON Schema type に変換。dict型のスキーマ定義にも対応。"""
    type_map = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }
    # dict型のスキーマ定義: {"type": int, "default": 20}
    if isinstance(python_type, dict):
        inner_type = python_type.get("type", str)
        return type_map.get(inner_type, "string")
    return type_map.get(python_type, "string")


# ============================================================
# シングルトン
# ============================================================
tool_registry = ToolRegistry()
