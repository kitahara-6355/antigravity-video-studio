"""
ContextCompressor — Claude Code 5段階コンテキスト圧縮パイプライン

Claude Code 流出コードから判明した5段階のコンテキスト管理戦略を
Antigravity のエージェントセッションに適用する。

5段階圧縮戦略（順次適用）:
    1. Snip        — 明らかに不要な古いメッセージを除去
    2. MicroCompact — ツール出力を切り詰め（LLM 呼び出し不要）
    3. Collapse     — 関連メッセージ群を1つの要約に統合
    4. AutoCompact  — トークン上限 95% で発動する要約圧縮
    5. FullCompact  — 全履歴を圧縮し高優先度項目のみ再注入

重要ルール（Claude Code 由来）:
    - 直近に編集した5つのファイルの内容は圧縮対象から除外
    - Circuit Breaker: 圧縮失敗3回連続で停止・エスカレーション

設計方針:
    - ADK の session.state と連携
    - Gemini のコンテキストウィンドウに最適化
    - usage_tracker 連携で API コスト管理
"""

import json
import logging
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime

# Model Registry (SSoT: model_config.json)
try:
    from model_registry import get_model
except ImportError:
    def get_model(task): return "gemini-2.5-flash"

logger = logging.getLogger(__name__)

# ============================================================
# 定数（Gemini 2.5 Flash 向け調整）
# ============================================================
TOKEN_LIMIT = 1_000_000         # Gemini 2.5 Flash の上限
AUTOCOMPACT_THRESHOLD = 0.80    # 80% で AutoCompact 発動
FULLCOMPACT_THRESHOLD = 0.95    # 95% で FullCompact 発動
PROTECTED_FILE_COUNT = 5        # 直近5ファイルは圧縮除外
CIRCUIT_BREAKER_LIMIT = 3       # 連続失敗でブレーカー発動

TOOL_OUTPUT_MAX_CHARS = 5000    # MicroCompact: ツール出力の上限
POST_COMPACT_BUDGET = 50_000    # FullCompact 後の残存トークン数
SUMMARY_MAX_TOKENS = 20_000     # AutoCompact 要約の上限


# ============================================================
# データ構造
# ============================================================

@dataclass
class Message:
    """セッション内のメッセージ"""
    role: str               # "user", "agent", "tool_result"
    content: str
    timestamp: str
    metadata: Dict = field(default_factory=dict)
    is_protected: bool = False  # True なら圧縮除外
    token_estimate: int = 0


@dataclass
class CompressedContext:
    """圧縮結果"""
    messages: List[Message]
    summary: Optional[str]
    total_tokens: int
    compression_applied: List[str]  # どの段階が発動したか
    protected_files: List[str]
    circuit_breaker_tripped: bool = False


@dataclass
class CompressionStats:
    """圧縮統計"""
    original_tokens: int
    final_tokens: int
    ratio: float
    stages_applied: List[str]
    duration_ms: int


# ============================================================
# メインクラス
# ============================================================

class ContextCompressor:
    """
    5段階コンテキスト圧縮パイプライン。

    Usage:
        compressor = ContextCompressor()
        result = compressor.compress(messages, token_count=180_000)

        # 圧縮されたメッセージを ADK に渡す
        for msg in result.messages:
            ...
    """

    def __init__(
        self,
        token_limit: int = TOKEN_LIMIT,
        autocompact_threshold: float = AUTOCOMPACT_THRESHOLD,
        fullcompact_threshold: float = FULLCOMPACT_THRESHOLD,
    ):
        self.token_limit = token_limit
        self.autocompact_threshold = autocompact_threshold
        self.fullcompact_threshold = fullcompact_threshold
        self._consecutive_failures = 0

    def compress(
        self,
        messages: List[Message],
        token_count: int,
        recent_files: Optional[List[str]] = None,
    ) -> CompressedContext:
        """
        メッセージリストを圧縮する。

        段階的に圧縮を適用し、トークン数がしきい値以下になったら停止。

        Args:
            messages: セッション内のメッセージリスト
            token_count: 現在の推定トークン数
            recent_files: 直近に編集したファイルパスリスト（圧縮除外）

        Returns:
            CompressedContext
        """
        recent_files = recent_files or []
        protected = recent_files[:PROTECTED_FILE_COUNT]
        stages_applied = []
        current_messages = list(messages)

        # 保護フラグの設定
        self._mark_protected(current_messages, protected)

        # Circuit Breaker チェック
        if self._consecutive_failures >= CIRCUIT_BREAKER_LIMIT:
            logger.warning(
                f"⚡ Circuit Breaker 発動: {self._consecutive_failures}回連続失敗"
            )
            return CompressedContext(
                messages=current_messages,
                summary=None,
                total_tokens=token_count,
                compression_applied=[],
                protected_files=protected,
                circuit_breaker_tripped=True,
            )

        try:
            # Stage 1: Snip — 不要メッセージの除去
            if self._needs_compression(token_count, self.autocompact_threshold):
                current_messages, token_count = self._snip(current_messages, token_count)
                stages_applied.append("snip")

            # Stage 2: MicroCompact — ツール出力の切り詰め
            if self._needs_compression(token_count, self.autocompact_threshold):
                current_messages, token_count = self._microcompact(current_messages, token_count)
                stages_applied.append("microcompact")

            # Stage 3: Collapse — メッセージグループの統合
            if self._needs_compression(token_count, self.autocompact_threshold):
                current_messages, token_count = self._collapse(current_messages, token_count)
                stages_applied.append("collapse")

            # Stage 4: AutoCompact — LLM 要約圧縮
            if self._needs_compression(token_count, self.fullcompact_threshold):
                current_messages, token_count, summary = self._autocompact(
                    current_messages, token_count
                )
                stages_applied.append("autocompact")

            # Stage 5: FullCompact — 全履歴圧縮（緊急）
            if self._needs_compression(token_count, 1.0):
                current_messages, token_count, summary = self._fullcompact(
                    current_messages, token_count
                )
                stages_applied.append("fullcompact")

            self._consecutive_failures = 0  # 成功時にリセット

        except Exception as e:
            self._consecutive_failures += 1
            logger.error(
                f"圧縮エラー (連続{self._consecutive_failures}回): {e}"
            )

        return CompressedContext(
            messages=current_messages,
            summary=None,
            total_tokens=token_count,
            compression_applied=stages_applied,
            protected_files=protected,
        )

    # ============================================================
    # Stage 1: Snip
    # ============================================================

    def _snip(
        self, messages: List[Message], token_count: int
    ) -> tuple[List[Message], int]:
        """
        不要メッセージの外科的除去。

        - 古いシステムメッセージ
        - 空の応答
        - 重複するツール呼び出し結果
        """
        original_count = len(messages)
        result = []
        removed_tokens = 0

        for msg in messages:
            if msg.is_protected:
                result.append(msg)
                continue

            # 空メッセージの除去
            if not msg.content or msg.content.strip() == "":
                removed_tokens += msg.token_estimate
                continue

            # 古い（先頭20%以内の）低価値メッセージの除去
            index = messages.index(msg)
            is_old = index < len(messages) * 0.2
            is_low_value = msg.role == "tool_result" and len(msg.content) > 2000

            if is_old and is_low_value:
                removed_tokens += msg.token_estimate
                continue

            result.append(msg)

        new_token_count = token_count - removed_tokens
        logger.info(
            f"  Snip: {original_count}→{len(result)} messages, "
            f"freed ~{removed_tokens} tokens"
        )
        return result, max(new_token_count, 0)

    # ============================================================
    # Stage 2: MicroCompact
    # ============================================================

    def _microcompact(
        self, messages: List[Message], token_count: int
    ) -> tuple[List[Message], int]:
        """
        ツール出力の切り詰め（LLM 呼び出し不要）。

        大きなファイル読み取り結果やターミナル出力を
        上限文字数で切り詰め、参照のみ残す。
        """
        saved_tokens = 0

        for msg in messages:
            if msg.is_protected:
                continue
            if msg.role == "tool_result" and len(msg.content) > TOOL_OUTPUT_MAX_CHARS:
                original_len = len(msg.content)
                msg.content = (
                    msg.content[:TOOL_OUTPUT_MAX_CHARS]
                    + f"\n\n... [MicroCompact: {original_len - TOOL_OUTPUT_MAX_CHARS}文字切り詰め]"
                )
                saved_tokens += (original_len - TOOL_OUTPUT_MAX_CHARS) // 4

        new_token_count = token_count - saved_tokens
        logger.info(f"  MicroCompact: freed ~{saved_tokens} tokens")
        return messages, max(new_token_count, 0)

    # ============================================================
    # Stage 3: Collapse
    # ============================================================

    def _collapse(
        self, messages: List[Message], token_count: int
    ) -> tuple[List[Message], int]:
        """
        関連メッセージ群を1つの要約に統合。

        ツール呼び出し → 結果 → 分析 のシーケンスを
        1つの要約メッセージに統合する。
        """
        result = []
        i = 0
        collapsed_tokens = 0

        while i < len(messages):
            msg = messages[i]

            if msg.is_protected:
                result.append(msg)
                i += 1
                continue

            # tool_call → tool_result → analysis のパターンを検出
            if (
                msg.role == "agent"
                and i + 2 < len(messages)
                and messages[i + 1].role == "tool_result"
                and messages[i + 2].role == "agent"
                and not messages[i + 1].is_protected
                and not messages[i + 2].is_protected
            ):
                # 3メッセージを1つに統合
                collapsed = Message(
                    role="agent",
                    content=(
                        f"[Collapsed] ツール実行と分析: "
                        f"{msg.content[:200]}... → "
                        f"結果: {messages[i+1].content[:200]}... → "
                        f"分析: {messages[i+2].content[:200]}..."
                    ),
                    timestamp=msg.timestamp,
                    metadata={"collapsed_from": 3},
                )
                original_tokens = sum(
                    m.token_estimate for m in messages[i : i + 3]
                )
                collapsed.token_estimate = len(collapsed.content) // 4
                collapsed_tokens += original_tokens - collapsed.token_estimate
                result.append(collapsed)
                i += 3
            else:
                result.append(msg)
                i += 1

        new_token_count = token_count - collapsed_tokens
        logger.info(
            f"  Collapse: {len(messages)}→{len(result)} messages, "
            f"freed ~{collapsed_tokens} tokens"
        )
        return result, max(new_token_count, 0)

    # ============================================================
    # Stage 4: AutoCompact
    # ============================================================

    def _autocompact(
        self, messages: List[Message], token_count: int
    ) -> tuple[List[Message], int, Optional[str]]:
        """
        LLM による要約圧縮。

        Claude Code では ~13,000 トークンのバッファを確保し、
        ~20,000 トークンの要約を生成していた。

        Antigravity 版: Gemini Flash で要約生成。
        """
        try:
            from gemini_client_factory import get_gemini_client
            from google.genai import types

            client = get_gemini_client()

            # 保護されていないメッセージのテキストを集約
            old_messages = [m for m in messages if not m.is_protected]
            protected_messages = [m for m in messages if m.is_protected]

            if not old_messages:
                return messages, token_count, None

            history_text = "\n".join(
                f"[{m.role}] {m.content[:500]}" for m in old_messages[:50]
            )

            prompt = f"""以下の対話履歴を、重要な決定事項と結果のみを残して要約してください。
試行錯誤やエラーの詳細は省略し、最終的な結論のみを記録してください。

要約は日本語で、箇条書き形式で出力してください。

対話履歴:
{history_text}"""

            response = client.models.generate_content(
                model=get_model("bulk_processing"),
                contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=SUMMARY_MAX_TOKENS,
                ),
            )

            summary = response.text.strip()

            # 要約メッセージで古いメッセージを置換
            summary_msg = Message(
                role="agent",
                content=f"[AutoCompact Summary]\n{summary}",
                timestamp=datetime.now().isoformat(),
                metadata={"autocompact": True, "original_count": len(old_messages)},
                token_estimate=len(summary) // 4,
            )

            new_messages = [summary_msg] + protected_messages
            new_token_count = sum(m.token_estimate for m in new_messages)

            logger.info(
                f"  AutoCompact: {len(messages)}→{len(new_messages)} messages, "
                f"{token_count}→{new_token_count} tokens"
            )

            return new_messages, new_token_count, summary

        except Exception as e:
            logger.error(f"AutoCompact エラー: {e}")
            return messages, token_count, None

    # ============================================================
    # Stage 5: FullCompact（緊急圧縮）
    # ============================================================

    def _fullcompact(
        self, messages: List[Message], token_count: int
    ) -> tuple[List[Message], int, Optional[str]]:
        """
        全履歴を圧縮し、高優先度項目のみを再注入。

        Claude Code では ~50,000 トークンの残存予算で運用。
        直近5ファイルの内容 (各5,000トークン上限) は再注入。
        """
        try:
            from gemini_client_factory import get_gemini_client
            from agents.memory.verified_facts import verified_facts_store

            client = get_gemini_client()

            # 全メッセージのダイジェスト生成
            all_text = "\n".join(
                f"[{m.role}] {m.content[:300]}" for m in messages[:30]
            )

            prompt = f"""これは緊急のコンテキスト圧縮です。
以下の全対話履歴を、核心的な結論と現在のタスク状態のみに圧縮してください。
出力は500文字以内の日本語で。

対話履歴:
{all_text}"""

            from google.genai import types
            response = client.models.generate_content(
                model=get_model("bulk_processing"),
                contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=2000,
                ),
            )

            ultra_summary = response.text.strip()

            # 再注入: Verified Facts + 超要約 + 保護メッセージ
            verified_context = verified_facts_store.get_facts_for_context()

            core_msg = Message(
                role="agent",
                content=(
                    f"[FullCompact — 緊急圧縮実行]\n\n"
                    f"{verified_context}\n\n"
                    f"## セッション要約\n{ultra_summary}"
                ),
                timestamp=datetime.now().isoformat(),
                metadata={"fullcompact": True},
                token_estimate=len(ultra_summary) // 4 + len(verified_context) // 4,
            )

            protected = [m for m in messages if m.is_protected]
            new_messages = [core_msg] + protected[-PROTECTED_FILE_COUNT:]
            new_token_count = sum(m.token_estimate for m in new_messages)

            logger.info(
                f"  FullCompact: 緊急圧縮完了 {token_count}→{new_token_count} tokens"
            )

            return new_messages, new_token_count, ultra_summary

        except Exception as e:
            logger.error(f"FullCompact エラー: {e}")
            return messages, token_count, None

    # ============================================================
    # ヘルパー
    # ============================================================

    def _needs_compression(self, token_count: int, threshold: float) -> bool:
        """圧縮が必要か判定"""
        return token_count > self.token_limit * threshold

    def _mark_protected(self, messages: List[Message], protected_files: List[str]):
        """保護対象メッセージにフラグを設定"""
        for msg in messages:
            file_ref = msg.metadata.get("file_path", "")
            if file_ref in protected_files:
                msg.is_protected = True

    def estimate_tokens(self, text: str) -> int:
        """トークン数を簡易推定（4文字≒1トークン）"""
        return len(text) // 4

    def reset_circuit_breaker(self):
        """Circuit Breaker を手動リセット"""
        self._consecutive_failures = 0
        logger.info("⚡ Circuit Breaker リセット")


# ============================================================
# シングルトンインスタンス
# ============================================================
context_compressor = ContextCompressor()
