"""consensus_engine.py — ファクトベース合意形成エンジン

エージェント間の合意形成を VerifiedFacts（検証済みファクト）に基づいて
構造的に管理するエンジン。

設計方針:
    - nexus_council_v3.py の SafetyFallback / InputGuardrail パターンを継承
    - resolution_tracker.py の Resolution / ResolutionTracker パターンを継承
    - fact_parser.py の矛盾検出を統合し、ファクト矛盾時は自動エスカレーション
    - asyncio ベースだが、同期ラッパー propose_sync() も提供
    - 議事録を JSON 形式で council_minutes/ に自動保存

使用例:
    engine = ConsensusEngine()

    # 非同期
    result = await engine.propose("FastAPIルーティングを再構成する", {"reason": "保守性向上"})
    await engine.vote(result.proposal_id, "Analyst", Vote.AGREE, "データ分析から有効", [])
    await engine.vote(result.proposal_id, "Strategist", Vote.AGREE, "ロードマップに適合", [])
    final = await engine.resolve(result.proposal_id)

    # 同期
    result = engine.propose_sync("新しいキャッシュ戦略を導入する", {"priority": "high"})
"""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ============================================================
# 定数
# ============================================================

# 議事録の保存先
DEFAULT_MINUTES_DIR = Path(__file__).resolve().parent.parent / "memory" / "council_minutes"

# 合意閾値: 3エージェント中2以上の賛成で合意
DEFAULT_QUORUM = 2
DEFAULT_TOTAL_AGENTS = 3

# タイムアウト設定
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_RETRIES = 3


# ============================================================
# 列挙型
# ============================================================

class Vote(str, Enum):
    """投票の選択肢。

    Attributes:
        AGREE: 賛成
        DISAGREE: 反対
        ABSTAIN: 棄権
    """
    AGREE = "agree"
    DISAGREE = "disagree"
    ABSTAIN = "abstain"


class Outcome(str, Enum):
    """合意判定の結果。

    Attributes:
        PENDING: 投票進行中
        APPROVED: 承認（多数決で賛成が閾値以上）
        REJECTED: 却下（反対が過半数）
        ESCALATED: エスカレーション（ファクト矛盾検出 / タイムアウト）
    """
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"


# ============================================================
# データ構造
# ============================================================

@dataclass
class VoteRecord:
    """個々の投票記録。

    Attributes:
        agent_id: 投票したエージェントのID
        vote: 投票内容（AGREE / DISAGREE / ABSTAIN）
        reason: 投票理由
        cited_facts: 引用したファクトIDのリスト
        timestamp: 投票日時（ISO8601）
    """
    agent_id: str
    vote: Vote
    reason: str
    cited_facts: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class ConsensusResult:
    """合意形成の結果。

    Attributes:
        proposal_id: 提案の一意ID
        proposal: 提案テキスト
        context: 提案に付随するコンテキスト情報
        outcome: 判定結果（PENDING / APPROVED / REJECTED / ESCALATED）
        votes: 投票記録のリスト
        cited_facts: 合議で引用されたファクト（全投票分を集約）
        contradictions: 検出された矛盾ファクトのリスト
        minutes_path: 議事録ファイルのパス
        created_at: 提案日時（ISO8601）
        resolved_at: 判定確定日時（ISO8601、未確定時は空文字）
        escalation_reason: エスカレーション理由（エスカレーション時のみ）
    """
    proposal_id: str
    proposal: str
    context: Dict[str, Any] = field(default_factory=dict)
    outcome: Outcome = Outcome.PENDING
    votes: List[VoteRecord] = field(default_factory=list)
    cited_facts: List[str] = field(default_factory=list)
    contradictions: List[Dict] = field(default_factory=list)
    minutes_path: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    resolved_at: str = ""
    escalation_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """辞書表現に変換する。

        Returns:
            ConsensusResult の辞書表現
        """
        data = asdict(self)
        # Enum を文字列に変換
        data["outcome"] = self.outcome.value
        for v in data["votes"]:
            if isinstance(v.get("vote"), Vote):
                v["vote"] = v["vote"].value
        return data


# ============================================================
# メインクラス: ConsensusEngine
# ============================================================

class ConsensusEngine:
    """ファクトベースの合意形成エンジン。

    提案 → 投票 → 合意判定 のフローを管理し、
    VerifiedFacts との矛盾検出による自動エスカレーションを行う。

    Attributes:
        minutes_dir: 議事録の保存先ディレクトリ
        quorum: 合意に必要な最低賛成数
        total_agents: 投票に参加するエージェント総数
        timeout_seconds: 各操作のタイムアウト（秒）
        max_retries: タイムアウト時の最大リトライ回数
        _proposals: アクティブな提案のキャッシュ
    """

    def __init__(
        self,
        minutes_dir: Optional[Path] = None,
        quorum: int = DEFAULT_QUORUM,
        total_agents: int = DEFAULT_TOTAL_AGENTS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        """ConsensusEngine を初期化する。

        Args:
            minutes_dir: 議事録保存先。省略時はデフォルトパス。
            quorum: 合意に必要な最低賛成数（デフォルト: 2）
            total_agents: 投票参加エージェント総数（デフォルト: 3）
            timeout_seconds: タイムアウト秒数（デフォルト: 60）
            max_retries: 最大リトライ回数（デフォルト: 3）
        """
        self.minutes_dir = minutes_dir or DEFAULT_MINUTES_DIR
        self.quorum = quorum
        self.total_agents = total_agents
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._proposals: Dict[str, ConsensusResult] = {}

    # --------------------------------------------------------
    # パブリック API（非同期）
    # --------------------------------------------------------

    async def propose(
        self,
        proposal: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ConsensusResult:
        """提案を投票にかける。

        提案テキストに対して:
        1. fact_parser でファクト矛盾チェックを実行
        2. 矛盾が検出された場合は即座にエスカレーション
        3. 矛盾がなければ PENDING 状態で提案を登録

        Args:
            proposal: 提案テキスト
            context: 提案に付随するコンテキスト情報（省略可）

        Returns:
            生成された ConsensusResult（PENDING または ESCALATED）

        Raises:
            ValueError: 提案テキストが空の場合
            asyncio.TimeoutError: タイムアウト時（リトライ後もフェイルオーバー）
        """
        if not proposal or not proposal.strip():
            raise ValueError("提案テキストが空です。")

        proposal_id = f"cp_{uuid.uuid4().hex[:12]}"
        result = ConsensusResult(
            proposal_id=proposal_id,
            proposal=proposal.strip(),
            context=context or {},
        )

        # ファクト矛盾チェック（タイムアウト付き）
        contradictions = await self._check_contradictions_with_timeout(proposal)

        if contradictions:
            result.contradictions = contradictions
            result.outcome = Outcome.ESCALATED
            result.escalation_reason = (
                f"ファクト矛盾検出: {len(contradictions)}件の矛盾が検出されました。"
                f" 議長による判断が必要です。"
            )
            result.resolved_at = datetime.now().isoformat()
            logger.warning(
                f"⚠️ 提案 {proposal_id} がファクト矛盾によりエスカレーション: "
                f"{contradictions[0].get('contradiction_reason', '不明')}"
            )

        self._proposals[proposal_id] = result

        # 議事録の初期保存
        await self._save_minutes(result)

        return result

    async def vote(
        self,
        proposal_id: str,
        agent_id: str,
        vote: Vote,
        reason: str = "",
        cited_facts: Optional[List[str]] = None,
    ) -> None:
        """提案に対して投票する。

        Args:
            proposal_id: 提案ID
            agent_id: 投票するエージェントのID
            vote: 投票内容（Vote.AGREE / Vote.DISAGREE / Vote.ABSTAIN）
            reason: 投票理由
            cited_facts: 引用するファクトIDのリスト

        Raises:
            KeyError: 提案IDが存在しない場合
            ValueError: 既にエスカレーション済みまたは判定済みの提案に投票した場合
            ValueError: 同一エージェントが二重投票した場合
        """
        if proposal_id not in self._proposals:
            raise KeyError(f"提案 {proposal_id} が見つかりません。")

        result = self._proposals[proposal_id]

        if result.outcome != Outcome.PENDING:
            raise ValueError(
                f"提案 {proposal_id} は既に {result.outcome.value} 状態です。"
                f" 投票は受け付けられません。"
            )

        # 二重投票チェック
        for existing_vote in result.votes:
            if existing_vote.agent_id == agent_id:
                raise ValueError(
                    f"エージェント {agent_id} は既に提案 {proposal_id} に投票済みです。"
                )

        record = VoteRecord(
            agent_id=agent_id,
            vote=vote,
            reason=reason,
            cited_facts=cited_facts or [],
        )
        result.votes.append(record)

        # 引用ファクトの集約
        if cited_facts:
            result.cited_facts.extend(cited_facts)

        logger.info(
            f"🗳️ 投票: {agent_id} → {vote.value} (提案: {proposal_id})"
        )

        # 議事録更新
        await self._save_minutes(result)

    async def resolve(self, proposal_id: str) -> ConsensusResult:
        """合意判定を実行する。

        投票結果に基づいて多数決で判定:
        - 賛成 >= quorum → APPROVED
        - 反対 > total_agents - quorum → REJECTED
        - それ以外 → ESCALATED（合意不成立）

        Args:
            proposal_id: 提案ID

        Returns:
            判定済みの ConsensusResult

        Raises:
            KeyError: 提案IDが存在しない場合
        """
        if proposal_id not in self._proposals:
            raise KeyError(f"提案 {proposal_id} が見つかりません。")

        result = self._proposals[proposal_id]

        # 既に判定済みの場合はそのまま返す
        if result.outcome != Outcome.PENDING:
            return result

        # 投票集計
        agree_count = sum(1 for v in result.votes if v.vote == Vote.AGREE)
        disagree_count = sum(1 for v in result.votes if v.vote == Vote.DISAGREE)

        if agree_count >= self.quorum:
            result.outcome = Outcome.APPROVED
        elif disagree_count > self.total_agents - self.quorum:
            result.outcome = Outcome.REJECTED
        else:
            result.outcome = Outcome.ESCALATED
            result.escalation_reason = (
                f"合意不成立: 賛成{agree_count}件 / 反対{disagree_count}件 / "
                f"定足数{self.quorum}件に達しませんでした。"
            )

        result.resolved_at = datetime.now().isoformat()

        logger.info(
            f"📋 合意判定: {proposal_id} → {result.outcome.value} "
            f"(賛成={agree_count}, 反対={disagree_count})"
        )

        # 最終議事録保存
        await self._save_minutes(result)

        return result

    # --------------------------------------------------------
    # パブリック API（同期ラッパー）
    # --------------------------------------------------------

    def propose_sync(
        self,
        proposal: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ConsensusResult:
        """propose() の同期ラッパー。

        既存のイベントループが実行中の場合は新規スレッドで実行する。

        Args:
            proposal: 提案テキスト
            context: コンテキスト情報

        Returns:
            ConsensusResult
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # 既存ループ内 → 新規スレッドで実行
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, self.propose(proposal, context))
                return future.result(timeout=self.timeout_seconds + 10)
        else:
            return asyncio.run(self.propose(proposal, context))

    def vote_sync(
        self,
        proposal_id: str,
        agent_id: str,
        vote: Vote,
        reason: str = "",
        cited_facts: Optional[List[str]] = None,
    ) -> None:
        """vote() の同期ラッパー。

        Args:
            proposal_id: 提案ID
            agent_id: エージェントID
            vote: 投票内容
            reason: 投票理由
            cited_facts: 引用ファクトIDリスト
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    asyncio.run,
                    self.vote(proposal_id, agent_id, vote, reason, cited_facts),
                )
                future.result(timeout=self.timeout_seconds + 10)
        else:
            asyncio.run(self.vote(proposal_id, agent_id, vote, reason, cited_facts))

    def resolve_sync(self, proposal_id: str) -> ConsensusResult:
        """resolve() の同期ラッパー。

        Args:
            proposal_id: 提案ID

        Returns:
            ConsensusResult
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, self.resolve(proposal_id))
                return future.result(timeout=self.timeout_seconds + 10)
        else:
            return asyncio.run(self.resolve(proposal_id))

    # --------------------------------------------------------
    # ユーティリティ
    # --------------------------------------------------------

    def get_proposal(self, proposal_id: str) -> Optional[ConsensusResult]:
        """提案を取得する。

        Args:
            proposal_id: 提案ID

        Returns:
            ConsensusResult。存在しない場合は None。
        """
        return self._proposals.get(proposal_id)

    def list_proposals(
        self, outcome: Optional[Outcome] = None
    ) -> List[ConsensusResult]:
        """提案一覧を取得する。

        Args:
            outcome: フィルタする判定結果（省略時は全件）

        Returns:
            ConsensusResult のリスト（作成日時の降順）
        """
        proposals = list(self._proposals.values())
        if outcome is not None:
            proposals = [p for p in proposals if p.outcome == outcome]
        return sorted(proposals, key=lambda p: p.created_at, reverse=True)

    # --------------------------------------------------------
    # プライベート: ファクト矛盾チェック
    # --------------------------------------------------------

    async def _check_contradictions_with_timeout(
        self, proposal: str
    ) -> List[Dict]:
        """タイムアウト付きのファクト矛盾チェック。

        fact_parser.check_contradiction() を呼び出し、
        タイムアウトした場合はリトライ。
        最大リトライ回数を超えた場合は空リストを返す（フェイルオーバー）。

        Args:
            proposal: 提案テキスト

        Returns:
            矛盾ファクトのリスト（フェイルオーバー時は空リスト）
        """
        for attempt in range(1, self.max_retries + 1):
            try:
                contradictions = await asyncio.wait_for(
                    self._run_contradiction_check(proposal),
                    timeout=self.timeout_seconds,
                )
                return contradictions
            except asyncio.TimeoutError:
                logger.warning(
                    f"⏱️ ファクト矛盾チェックがタイムアウト "
                    f"(試行 {attempt}/{self.max_retries})"
                )
            except Exception as e:
                logger.error(
                    f"ファクト矛盾チェックでエラー (試行 {attempt}/{self.max_retries}): {e}",
                    exc_info=True,
                )

        # フェイルオーバー: チェック不能時は空リスト
        logger.warning(
            f"⚠️ ファクト矛盾チェックが{self.max_retries}回失敗 → フェイルオーバー（矛盾なしとして続行）"
        )
        return []

    async def _run_contradiction_check(self, proposal: str) -> List[Dict]:
        """fact_parser を使った矛盾チェックの実行。

        同期関数を asyncio.to_thread で非同期化。

        Args:
            proposal: 提案テキスト

        Returns:
            矛盾ファクトのリスト
        """
        try:
            from agents.memory.fact_parser import FactParser
            parser = FactParser()
            # 同期関数を別スレッドで実行
            contradictions = await asyncio.to_thread(
                parser.check_contradiction, proposal
            )
            return contradictions
        except ImportError:
            logger.warning("fact_parser モジュールのインポートに失敗。矛盾チェックをスキップ。")
            return []
        except Exception as e:
            logger.error(f"矛盾チェック実行エラー: {e}", exc_info=True)
            return []

    # --------------------------------------------------------
    # プライベート: 議事録保存
    # --------------------------------------------------------

    async def _save_minutes(self, result: ConsensusResult) -> None:
        """議事録を JSON ファイルとして保存する。

        保存先: {minutes_dir}/{proposal_id}.json

        議事録フォーマット:
        {
            "timestamp": "ISO8601",
            "proposal": "提案テキスト",
            "proposal_id": "cp_xxxx",
            "context": {...},
            "cited_facts": [...],
            "contradictions": [...],
            "votes": [{agent_id, vote, reason, cited_facts, timestamp}, ...],
            "final_outcome": "approved" / "rejected" / "escalated" / "pending",
            "escalation_reason": "...",
            "resolved_at": "ISO8601"
        }

        Args:
            result: 保存する ConsensusResult
        """
        try:
            self.minutes_dir.mkdir(parents=True, exist_ok=True)

            minutes = {
                "timestamp": datetime.now().isoformat(),
                "proposal": result.proposal,
                "proposal_id": result.proposal_id,
                "context": result.context,
                "cited_facts": list(set(result.cited_facts)),  # 重複排除
                "contradictions": result.contradictions,
                "votes": [
                    {
                        "agent_id": v.agent_id,
                        "vote": v.vote.value if isinstance(v.vote, Vote) else v.vote,
                        "reason": v.reason,
                        "cited_facts": v.cited_facts,
                        "timestamp": v.timestamp,
                    }
                    for v in result.votes
                ],
                "final_outcome": result.outcome.value,
                "escalation_reason": result.escalation_reason,
                "resolved_at": result.resolved_at,
                "created_at": result.created_at,
            }

            filepath = self.minutes_dir / f"{result.proposal_id}.json"
            result.minutes_path = str(filepath)

            # アトミック書き込み
            tmp_path = filepath.with_suffix(".json.tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(minutes, f, ensure_ascii=False, indent=2)
            tmp_path.replace(filepath)

            logger.debug(f"📝 議事録保存: {filepath}")

        except OSError as e:
            logger.error(f"議事録の保存に失敗: {e}", exc_info=True)


# ============================================================
# テスト・デバッグ用エントリポイント
# ============================================================

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    async def _demo():
        print("=" * 60)
        print("ConsensusEngine — ファクトベース合意形成エンジン デモ")
        print("=" * 60)

        # テスト用の一時ディレクトリに議事録を保存
        import tempfile
        tmp_dir = Path(tempfile.mkdtemp()) / "council_minutes"

        engine = ConsensusEngine(minutes_dir=tmp_dir)

        # 1. 提案
        print("\n📢 提案を投入...")
        result = await engine.propose(
            "FastAPI のルーティング構造をリファクタリングする",
            context={"reason": "保守性の向上", "priority": "medium"},
        )
        print(f"  提案ID: {result.proposal_id}")
        print(f"  ステータス: {result.outcome.value}")

        if result.outcome == Outcome.PENDING:
            # 2. 投票
            print("\n🗳️ 投票を実行...")
            await engine.vote(
                result.proposal_id, "Analyst", Vote.AGREE,
                "データ分析の観点から有効", ["vf_0001"],
            )
            await engine.vote(
                result.proposal_id, "Strategist", Vote.AGREE,
                "ロードマップに適合", ["vf_0002"],
            )
            await engine.vote(
                result.proposal_id, "Director", Vote.ABSTAIN,
                "演出面への影響なし",
            )

            # 3. 合意判定
            print("\n📋 合意判定...")
            final = await engine.resolve(result.proposal_id)
            print(f"  判定結果: {final.outcome.value}")
            print(f"  賛成: {sum(1 for v in final.votes if v.vote == Vote.AGREE)}")
            print(f"  反対: {sum(1 for v in final.votes if v.vote == Vote.DISAGREE)}")
            print(f"  棄権: {sum(1 for v in final.votes if v.vote == Vote.ABSTAIN)}")
            print(f"  議事録: {final.minutes_path}")

        elif result.outcome == Outcome.ESCALATED:
            print(f"  ⚠️ エスカレーション: {result.escalation_reason}")

        # 4. 却下テスト
        print("\n📢 却下テスト用の提案...")
        result2 = await engine.propose("テストを全て削除する", {})
        if result2.outcome == Outcome.PENDING:
            await engine.vote(result2.proposal_id, "Analyst", Vote.DISAGREE, "品質低下の懸念")
            await engine.vote(result2.proposal_id, "Strategist", Vote.DISAGREE, "ロードマップ違反")
            final2 = await engine.resolve(result2.proposal_id)
            print(f"  判定結果: {final2.outcome.value}")

        print(f"\n{'=' * 60}")
        print("デモ完了")

    asyncio.run(_demo())
    sys.exit(0)
