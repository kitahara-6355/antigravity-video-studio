"""
HookSystem — Anthropic推奨の Hook パターンによるツール実行制御

Claude Agent SDK の Hooks（PreToolUse, PostToolUse, PostToolUseFailure）の
概念を SDK非依存で再現。

既存の SelfHealingTool を Hook パターンに統合し、以下を実現:
  - PreToolUse:  ツール実行前のガードレール（ディスク残量、GPU状態チェック）
  - PostToolUse: ツール実行後の監査ログ・学習ループ連携
  - PostToolUseFailure: 失敗時のセルフヒーリング（スクラッチパッド連携）
  - Stop: パイプライン完了時の後処理
  - Notification: 外部通知（WebSocket→フロントエンド）

設計原則:
  - Matcher でフック発火を制御（ツール名でフィルタリング）
  - 複数フックをチェイン可能（priority 順に実行）
  - フック内からツール呼び出しをブロック/許可/変更可能
  - 非同期対応（asyncio）
"""

import json
import logging
import asyncio
import re
import shutil
from pathlib import Path
from typing import (
    Any, Callable, Dict, List, Optional, Awaitable, Union,
)
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


# ============================================================
# Hook イベント定義
# ============================================================

class HookEvent(str, Enum):
    """利用可能なフックイベント（Claude Agent SDK 準拠）

    各イベントは、パイプラインのライフサイクルにおいて特定のタイミングでトリガーされます。
    """
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    POST_TOOL_USE_FAILURE = "PostToolUseFailure"
    STOP = "Stop"
    NOTIFICATION = "Notification"
    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"


class PermissionDecision(str, Enum):
    """ツール実行の許可/拒否判定。

    フック判定の結果として、ツールをそのまま実行する(ALLOW)、
    実行を拒否する(DENY)、あるいは人間に実行の確認を求める(ASK)のいずれかを指定します。
    """
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"  # 人間に確認を求める


# ============================================================
# データ構造
# ============================================================

@dataclass
class HookInput:
    """フックコールバックへの入力データ構造。

    フックイベント発生時のコンテキスト情報を保持します。

    Attributes:
        hook_event_name (str): 発生したフックイベント名（例: "PreToolUse"）。
        tool_name (str): 対象のツール名。
        tool_input (Dict[str, Any]): ツールに渡された引数情報。
        tool_output (Optional[Any]): ツールの実行結果出力（PostToolUse のみ設定）。
        error (Optional[str]): ツール実行時に発生したエラーメッセージ（PostToolUseFailure のみ設定）。
        session_id (str): 現在のセッションID。
        cwd (str): 現在の作業ディレクトリパス。
        agent_id (Optional[str], optional): サブエージェント内で発火した場合のそのエージェントのID。
        agent_type (Optional[str], optional): サブエージェントのタイプ。
        metadata (Dict[str, Any]): 追加のメタデータコンテキスト。
    """
    hook_event_name: str = ""
    tool_name: str = ""
    tool_input: Dict[str, Any] = field(default_factory=dict)
    tool_output: Optional[Any] = None
    error: Optional[str] = None
    session_id: str = ""
    cwd: str = ""
    # サブエージェント内で発火した場合
    agent_id: Optional[str] = None
    agent_type: Optional[str] = None
    # 追加コンテキスト
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HookOutput:
    """フックコールバックからの出力および実行制御指示。

    フックでの処理結果に基づいて、ツールの実行可否や、パイプラインの継続制御を指定します。

    Attributes:
        permission_decision (Optional[str], optional): 実行判定。"allow", "deny", "ask" のいずれか。
        permission_decision_reason (Optional[str], optional): 実行判定に至った理由。
        updated_input (Optional[Dict[str, Any]], optional): 更新されたツールへの入力（PreToolUse のみ有効）。
        additional_context (Optional[str], optional): 出力に追加するコンテキストメッセージ（PostToolUse のみ有効）。
        system_message (Optional[str], optional): エージェントへ注入するシステムメッセージ。
        continue_pipeline (bool): パイプラインを継続して実行するかどうか。デフォルトは True。
    """
    # ツール実行の制御
    permission_decision: Optional[str] = None  # "allow", "deny", "ask"
    permission_decision_reason: Optional[str] = None
    # 入力の変更（PreToolUse のみ）
    updated_input: Optional[Dict[str, Any]] = None
    # 出力への追加コンテキスト（PostToolUse のみ）
    additional_context: Optional[str] = None
    # システムメッセージの注入
    system_message: Optional[str] = None
    # パイプライン継続の制御
    continue_pipeline: bool = True


@dataclass
class HookMatcher:
    """フックの発火条件およびコールバック定義。

    指定されたツール名パターン（正規表現）に合致するツールが使用された際、
    登録されたコールバック関数を実行します。

    Attributes:
        matcher (Optional[str], optional): ツール名に対する正規表現パターン。None の場合はすべてのツールにマッチします。
        hooks (List[Callable]): 実行するコールバック関数のリスト。
        priority (int): フックの実行優先度。値が低いものが優先されます。
        timeout_seconds (int): コールバック実行のタイムアウト秒数。
    """
    matcher: Optional[str] = None
    hooks: List[Callable] = field(default_factory=list)
    priority: int = 0  # 低い値が先に実行
    timeout_seconds: int = 60


# ============================================================
# HookSystem 本体
# ============================================================

class HookSystem:
    """
    Anthropic推奨の Hook パターン実装。

    Claude Agent SDK の options.hooks と同等の機能を提供:
    - イベント駆動のフック登録
    - Matcher による発火フィルタリング
    - 複数フックのチェイン実行
    - 非同期対応

    Usage:
        from harness.hooks import hook_system, HookEvent

        # フック登録
        hook_system.register(
            HookEvent.PRE_TOOL_USE,
            matcher="transcribe_video|render_final",
            callback=my_guard_callback,
        )

        # フック実行（ToolRegistry から自動呼び出し）
        output = await hook_system.fire(
            HookEvent.PRE_TOOL_USE,
            HookInput(tool_name="transcribe_video", tool_input={...}),
        )
    """

    def __init__(self) -> None:
        """HookSystem を初期化します。

        各フックイベントごとの空の HookMatcher リスト、および監査ログをセットアップします。
        """
        self._hooks: Dict[str, List[HookMatcher]] = {
            event.value: [] for event in HookEvent
        }
        self._audit_log: List[Dict] = []
        self._audit_log_max = 500

    # ============================================================
    # フック登録
    # ============================================================

    def register(
        self,
        event: Union[HookEvent, str],
        callback: Callable[..., Union[Awaitable[Optional[HookOutput]], Awaitable[Optional[Dict]], Optional[HookOutput], Optional[Dict]]],
        matcher: Optional[str] = None,
        priority: int = 0,
        timeout_seconds: int = 60,
    ) -> None:
        """フックコールバックを登録します。

        Args:
            event (Union[HookEvent, str]): フックを登録する対象のイベントまたはイベント名の文字列。
            callback (Callable): 登録するコールバック関数。同期関数・非同期関数の両方をサポートします。
                callback(input: HookInput) -> Optional[HookOutput] (または dict / Awaitable) のシグネチャを推奨します。
            matcher (Optional[str], optional): ツール名の正規表現パターン。省略または None の場合は全ツールで発火します。
            priority (int, optional): フックの実行優先度。低い値ほど先に実行されます。デフォルトは 0。
            timeout_seconds (int, optional): コールバック実行のタイムアウト秒数。デフォルトは 60秒。
        """
        event_name = event.value if isinstance(event, HookEvent) else event
        hook_matcher = HookMatcher(
            matcher=matcher,
            hooks=[callback],
            priority=priority,
            timeout_seconds=timeout_seconds,
        )
        self._hooks.setdefault(event_name, []).append(hook_matcher)
        # 優先度順にソート
        self._hooks[event_name].sort(key=lambda m: m.priority)

        cb_name = getattr(callback, "__name__", str(callback))
        logger.info(
            f"🪝 Hook registered: {event_name} "
            f"[matcher={matcher or '*'}] → {cb_name}"
        )

    # ============================================================
    # フック実行
    # ============================================================

    async def fire(
        self, event: Union[HookEvent, str], hook_input: HookInput,
    ) -> HookOutput:
        """フックイベントを発火させ、登録されているマッチャーを順次実行して結果をマージします。

        登録された全マッチャーを優先度（priority）順に実行し、結果をマージした最終的な HookOutput を返却します。
        マージ時、いずれか1つのフックでも実行拒否 (DENY) を返した場合は全体として拒否されます。
        また、updated_input は最後に実行されたフックの更新内容が優先して適用されます。

        Args:
            event (Union[HookEvent, str]): 発火させるイベント。
            hook_input (HookInput): コールバックに渡す入力コンテキスト。

        Returns:
            HookOutput: マージされた最終的な制御出力。
        """
        event_name = event.value if isinstance(event, HookEvent) else event
        hook_input.hook_event_name = event_name

        matchers = self._hooks.get(event_name, [])
        final_output = HookOutput()

        for matcher_def in matchers:
            # Matcher フィルタリング
            if not self._matches(matcher_def.matcher, hook_input.tool_name):
                continue

            for callback in matcher_def.hooks:
                try:
                    result = await asyncio.wait_for(
                        self._call_hook(callback, hook_input),
                        timeout=matcher_def.timeout_seconds,
                    )
                    if result:
                        final_output = self._merge_outputs(final_output, result)

                except asyncio.TimeoutError:
                    cb_name = getattr(callback, "__name__", "unknown")
                    logger.warning(
                        f"⏱️ Hook timeout: {event_name}/{cb_name} "
                        f"({matcher_def.timeout_seconds}s)"
                    )
                except (AttributeError, TypeError, ValueError, KeyError, IndexError, RuntimeError, NameError, AssertionError, asyncio.TimeoutError) as e:
                    cb_name = getattr(callback, "__name__", "unknown")
                    logger.error(f"Hook error: {event_name}/{cb_name}: {e}")

        # 監査ログに記録
        self._record_audit(event_name, hook_input, final_output)

        return final_output

    async def _call_hook(
        self,
        callback: Callable[..., Any],
        hook_input: HookInput,
    ) -> Optional[HookOutput]:
        """コールバック関数を適切に呼び出し、戻り値を HookOutput に正規化します。

        同期関数または非同期関数のいずれでも適切に実行します。
        戻り値が dict の場合は自動的に HookOutput にマッピングします。

        Args:
            callback (Callable[..., Any]): 呼び出し対象のコールバック関数。
            hook_input (HookInput): コールバック関数への入力。

        Returns:
            Optional[HookOutput]: 正規化された HookOutput オブジェクト。無効な形式の場合は None。
        """
        import inspect
        if inspect.iscoroutinefunction(callback):
            result = await callback(hook_input)
        else:
            result = callback(hook_input)
            if inspect.isawaitable(result):
                result = await result

        if result is None:
            return None

        if isinstance(result, HookOutput):
            return result

        if isinstance(result, dict):
            # dict → HookOutput 変換
            specific = result.get("hookSpecificOutput", result)
            return HookOutput(
                permission_decision=specific.get("permissionDecision"),
                permission_decision_reason=specific.get("permissionDecisionReason"),
                updated_input=specific.get("updatedInput"),
                additional_context=specific.get("additionalContext"),
                system_message=result.get("systemMessage"),
                continue_pipeline=result.get("continue", True),
            )

        return None

    def _matches(self, pattern: Optional[str], tool_name: str) -> bool:
        """ツール名がマッチャーパターンに合致するか判定します。

        Args:
            pattern (Optional[str]): マッチングを行う正規表現パターン。None の場合は無条件にマッチします。
            tool_name (str): 判定対象のツール名。空の場合は非ツールイベントとして常にマッチします。

        Returns:
            bool: マッチした場合は True、そうでない場合は False。正規表現エラー時は部分一致でフォールバックします。
        """
        if pattern is None:
            return True  # パターンなし = 全ツールにマッチ
        if not tool_name:
            return True  # ツール名なし = 非ツールイベント
        try:
            return bool(re.search(pattern, tool_name))
        except re.error:
            return pattern in tool_name

    def _merge_outputs(
        self, current: HookOutput, new: HookOutput,
    ) -> HookOutput:
        """2つのフック出力をマージします。拒否判定 (deny) や pipeline 停止が優先されます。

        Args:
            current (HookOutput): 現在のマージ済み累積出力。
            new (HookOutput): 新しくマージするコールバックの出力。

        Returns:
            HookOutput: マージされた結果。引数の current オブジェクトが更新されて返却されます。
        """
        if new.permission_decision == PermissionDecision.DENY.value:
            current.permission_decision = PermissionDecision.DENY.value
            current.permission_decision_reason = new.permission_decision_reason
        elif new.permission_decision and current.permission_decision != PermissionDecision.DENY.value:
            current.permission_decision = new.permission_decision
            current.permission_decision_reason = new.permission_decision_reason

        if new.updated_input:
            current.updated_input = new.updated_input
        if new.additional_context:
            current.additional_context = new.additional_context
        if new.system_message:
            current.system_message = new.system_message
        if not new.continue_pipeline:
            current.continue_pipeline = False

        return current

    # ============================================================
    # 監査ログ
    # ============================================================

    def _record_audit(
        self,
        event_name: str,
        hook_input: HookInput,
        output: HookOutput,
    ) -> None:
        """フックの実行結果を監査ログバッファに記録します。

        Args:
            event_name (str): イベント名。
            hook_input (HookInput): 入力コンテキスト。
            output (HookOutput): 最終判定出力。
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "event": event_name,
            "tool_name": hook_input.tool_name,
            "permission": output.permission_decision,
            "session_id": hook_input.session_id,
        }
        self._audit_log.append(entry)

        if len(self._audit_log) > self._audit_log_max:
            self._audit_log = self._audit_log[-self._audit_log_max:]

    def get_audit_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """直近の監査ログを取得します。

        Args:
            limit (int, optional): 取得する最大件数。デフォルトは 50。

        Returns:
            List[Dict[str, Any]]: 監査ログエントリのリスト。
        """
        return self._audit_log[-limit:]

    # ============================================================
    # ビルトインフック
    # ============================================================

    def register_builtin_hooks(self) -> None:
        """システムに標準で組み込むビルトインフック（ディスク容量ガード、監査ロガー、失敗時スクラッチパッド記録）を登録します。"""

        # 1. ディスク容量ガード（全ツール）
        self.register(
            HookEvent.PRE_TOOL_USE,
            callback=_builtin_disk_guard,
            priority=0,
        )

        # 2. 監査ロガー（全ツール）
        self.register(
            HookEvent.POST_TOOL_USE,
            callback=_builtin_audit_logger,
            priority=0,
        )

        # 3. 失敗時のスクラッチパッド記録
        self.register(
            HookEvent.POST_TOOL_USE_FAILURE,
            callback=_builtin_failure_recorder,
            priority=0,
        )

        logger.info("🪝 ビルトインフック3件登録完了")

    def get_stats(self) -> Dict[str, Any]:
        """フックシステムの稼働統計情報を取得します。

        Returns:
            Dict[str, Any]: 登録フック件数や監査ログサイズを含む統計情報。
        """
        return {
            "registered_hooks": {
                event: len(matchers)
                for event, matchers in self._hooks.items()
                if matchers
            },
            "audit_log_size": len(self._audit_log),
        }


# ============================================================
# ビルトインフックコールバック
# ============================================================

async def _builtin_disk_guard(hook_input: HookInput) -> Optional[HookOutput]:
    """PreToolUse フック: ツール実行前のディスク空き容量チェックと自動クリーンアップ。

    読み取り専用ツールを除き、ツールの処理に必要な予測容量、あるいは最低限必要な容量（2GBまたは1GB）が
    ディスクにあるかを検証します。不足時は中間ファイル自動クリーンアップを試み、それでも不足する場合は
    ツールの実行を拒否 (DENY) します。

    Args:
        hook_input (HookInput): フック入力コンテキスト。

    Returns:
        Optional[HookOutput]: 容量不足で実行を拒否する場合は DENY 判定を含む出力、問題ない場合は None。
    """
    # 読み取り専用ツールはスキップ
    read_only_tools = {"check_quality", "list_tools", "get_stats"}
    if hook_input.tool_name in read_only_tools:
        return None

    try:
        from disk_manager import get_free_gb, estimate_needed_gb, cleanup_intermediates

        video_path = hook_input.tool_input.get("video_path", "")
        free_gb = get_free_gb()

        # 動的閾値: 入力ファイルがあれば推定、なければ最低2GB
        if video_path and Path(video_path).exists():
            needed_gb = estimate_needed_gb([video_path])
        else:
            needed_gb = 2.0

        if free_gb < needed_gb:
            # 段階1: 自動クリーンアップ（中間ファイルのみ、成果物は保護）
            freed_gb = cleanup_intermediates(keep_latest=1)
            free_gb = get_free_gb()

            logger.info(
                f"🧹 DiskGuard: 自動クリーンアップ {freed_gb:.1f}GB解放 → 空き{free_gb:.1f}GB "
                f"(tool={hook_input.tool_name})"
            )

            if free_gb < needed_gb:
                # 段階2: ブロック
                return HookOutput(
                    permission_decision=PermissionDecision.DENY.value,
                    permission_decision_reason=(
                        f"ディスク空き容量不足: {free_gb:.1f}GB "
                        f"(推定{needed_gb:.1f}GB必要)。"
                        f"自動クリーンアップで{freed_gb:.1f}GB解放済みだが不足。"
                    ),
                )
    except ImportError:
        # disk_manager が利用不可の場合は旧ロジックにフォールバック
        try:
            output_dir = Path(hook_input.tool_input.get("video_path", ".")).parent
            disk = shutil.disk_usage(str(output_dir))
            free_gb = disk.free / (1024 ** 3)
            if free_gb < 1.0:
                return HookOutput(
                    permission_decision=PermissionDecision.DENY.value,
                    permission_decision_reason=(
                        f"ディスク空き容量不足: {free_gb:.1f}GB（最低1GB必要）"
                    ),
                )
        except (OSError, ValueError, TypeError, RuntimeError):
            pass
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.warning(f"DiskGuard error: {e}")

    return None


async def _builtin_audit_logger(hook_input: HookInput) -> Optional[HookOutput]:
    """PostToolUse フック: ツールの正常終了ログを記録し、透明性を確保します。

    Args:
        hook_input (HookInput): フック入力コンテキスト。

    Returns:
        Optional[HookOutput]: 常に None。
    """
    logger.info(
        f"📋 Tool completed: {hook_input.tool_name} "
        f"[session={hook_input.session_id}]"
    )
    return None


async def _builtin_failure_recorder(hook_input: HookInput) -> Optional[HookOutput]:
    """PostToolUseFailure フック: ツール実行失敗時の内容を自己修復（SelfHealing）スクラッチパッドに記録します。

    Args:
        hook_input (HookInput): フック入力コンテキスト。

    Returns:
        Optional[HookOutput]: 失敗メッセージおよびリトライを促すシステムメッセージを含む制御出力。
    """
    logger.warning(
        f"⚠️ Tool failed: {hook_input.tool_name} — {hook_input.error}"
    )

    # SelfHealingTool との連携
    try:
        from agents.self_healing_tool import self_healing
        self_healing._record_scratchpad(
            tool_name=hook_input.tool_name,
            error=Exception(hook_input.error or "Unknown error"),
            strategy="hook_recorded",
            result="pending",
            args_snapshot=hook_input.tool_input,
        )
    except (ImportError, Exception):
        pass

    return HookOutput(
        system_message=(
            f"ツール {hook_input.tool_name} が失敗しました: "
            f"{hook_input.error or 'Unknown error'}. "
            f"リトライまたは別の方法を検討してください。"
        ),
    )


# ============================================================
# シングルトン
# ============================================================
hook_system = HookSystem()
