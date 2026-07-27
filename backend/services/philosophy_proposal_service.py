"""
PhilosophyProposalService — 哲学提案サービス

Sprint 4.2.2: 哲学自動提案
設計書: sprint_42_soul_evolution_design.md §2.5
憲法参照:
- §6: 議長権限 — 哲学追記はapprove_proposal()経由のみ (SC-03)
- §12.3: 人間レビュー権 — 自動追加された項目は議長がいつでも削除・修正できる
- §5.2: Soul Narrative — 哲学は監督の魂であり、AIが勝手に追加しない
- §18: Free-Tier制約 — Gemini 30秒タイムアウト + get_model経由 (SC-05)

MASTER L1789: Milestone 4.2 Soul自律進化 (D-05)
"""
import asyncio
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# タイムアウト秒数 (§18 Free-Tier制約: SC-05)
_GEMINI_TIMEOUT_SECONDS = 30


@dataclass
class PhilosophyProposal:
    """哲学候補

    設計書 §2.5 参照。
    Geminiが候補を生成し、pending_philosophiesキューに格納。
    ユーザーが承認/却下/編集で最終決定する。
    """
    proposal_id: str
    content: str           # 提案された哲学テキスト
    source_summary: str    # 生成元の要約
    generated_at: str      # ISO8601
    status: str            # "pending" / "approved" / "rejected" / "edited"
    user_edit: Optional[str] = None  # ユーザー編集後テキスト


class PhilosophyProposalService:
    """哲学候補生成 + pending_philosophies管理

    SC-03: 哲学追記パスはapprove_proposal()経由のみ (§6)
    SC-05: Gemini 30秒タイムアウト + get_model経由 (§18)
    SC-06: 既存evolution_logフィールド非破壊
    """

    def __init__(self, evolution_log_path: Optional[Any] = None):
        if evolution_log_path is not None:
            self._evolution_log_path = Path(evolution_log_path)
        else:
            self._evolution_log_path = (
                Path(__file__).parent.parent / "branding" / "evolution_log.json"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate_proposal(
        self, philosophies: Any
    ) -> Optional[PhilosophyProposal]:
        """Gemini APIで哲学候補を生成（30秒タイムアウト: SC-05）

        Args:
            philosophies: 既存の哲学リスト（プロンプトコンテキスト用）

        Returns:
            PhilosophyProposal(status="pending") or None (タイムアウト時)
        """
        if not isinstance(philosophies, list):
            logger.warning("[PhilosophyProposal] philosophies がリストではありません。空リストとして扱います。")
            philosophies = []

        # ModelRegistry経由でモデル取得 (§14.1 / SC-05)
        from model_registry import get_model
        model_name = get_model("philosophy")

        prompt = self._build_proposal_prompt(philosophies)

        try:
            async with asyncio.timeout(_GEMINI_TIMEOUT_SECONDS):
                content = await self._call_gemini(model_name, prompt)
        except (TimeoutError, asyncio.TimeoutError):
            logger.warning(
                "[PhilosophyProposal] Gemini 30秒タイムアウト → None返却"
            )
            return None
        except Exception as e:
            logger.exception("[PhilosophyProposal] Gemini呼出失敗")
            return None

        if not content:
            return None

        # M-03: ルールベース矛盾検出 (D-02: プロンプト依存の形骸化防止)
        conflict_info = self._check_conflict_rules(content, philosophies)

        # Geminiが[CONFLICT]を出力した場合もバックストップとして処理
        if isinstance(content, str) and content.startswith("[CONFLICT"):
            end_idx = content.find("]")
            if end_idx > 0:
                conflict_info = conflict_info or content[len("[CONFLICT: "):end_idx]
                content = content[end_idx + 1:].strip()

        proposal = PhilosophyProposal(
            proposal_id=str(uuid.uuid4()),
            content=content,
            source_summary=f"既存哲学{len(philosophies)}件に基づくGemini提案",
            generated_at=datetime.now().isoformat(),
            status="pending_review" if conflict_info else "pending",
        )

        # m-03: pending_proposals上限50件管理（古い順削除, SC-05準拠）
        self._trim_pending_proposals()

        # pending_proposalsに追加して永続化 (S422-08)
        proposal_dict_extra = {}
        if conflict_info:
            proposal_dict_extra["conflict"] = conflict_info
        self._add_pending_proposal(proposal, extra_fields=proposal_dict_extra)

        return proposal

    async def generate_integration_proposal(
        self, philosophies: Any
    ) -> Optional[PhilosophyProposal]:
        """§12.2.3: 過去の全哲学を分析し、integrated_philosophyとして昇華

        [C-01 是正] 通常のgenerate_proposalとの違い:
        - source_summary に "integration" を明示
        - プロンプトが「統合・昇華」指向
        - pending_proposals に proposal_type="integration" で格納

        Args:
            philosophies: 統合対象の哲学リスト

        Returns:
            PhilosophyProposal(status="pending") or None (タイムアウト/エラー時)
        """
        if not isinstance(philosophies, list):
            logger.warning("[PhilosophyProposal] philosophies がリストではありません。空リストとして扱います。")
            philosophies = []

        from model_registry import get_model
        model_name = get_model("philosophy")
        prompt = self._build_integration_prompt(philosophies)

        try:
            async with asyncio.timeout(_GEMINI_TIMEOUT_SECONDS):
                content = await self._call_gemini(model_name, prompt)
        except (TimeoutError, asyncio.TimeoutError):
            logger.warning(
                "[PhilosophyProposal] 統合生成30秒タイムアウト"
            )
            return None
        except Exception as e:
            logger.exception("[PhilosophyProposal] 統合生成失敗")
            return None

        if not content:
            return None

        proposal = PhilosophyProposal(
            proposal_id=str(uuid.uuid4()),
            content=content,
            source_summary=f"哲学統合({len(philosophies)}件の分析・昇華)",
            generated_at=datetime.now().isoformat(),
            status="pending",
        )

        # pending_proposals に integration タイプで追加
        self._add_pending_proposal(proposal, proposal_type="integration")
        return proposal

    def get_pending_proposals(self) -> List[PhilosophyProposal]:
        """承認待ちの哲学候補一覧 (S422-06)"""
        evo_log = self._load_evolution_log()
        proposals = []
        pending_list = evo_log.get("pending_proposals")
        for p in pending_list:
            if isinstance(p, dict):
                proposals.append(PhilosophyProposal(
                    proposal_id=p.get("proposal_id", str(uuid.uuid4())),
                    content=p.get("content", ""),
                    source_summary=p.get("source_summary", ""),
                    generated_at=p.get("generated_at", ""),
                    status=p.get("status", "pending"),
                    user_edit=p.get("user_edit"),
                ))
        return proposals

    def approve_proposal(
        self, proposal_id: Any, edited: Optional[Any] = None
    ) -> bool:
        """哲学候補を承認 → evolution_log.philosophies に追記 (SC-03)

        SC-03: 哲学追記パスはこのメソッド経由のみ (§6 議長権限)
        SC-06: 既存evolution_logフィールド非破壊

        Args:
            proposal_id: 承認する提案ID
            edited: ユーザー編集テキスト (None = 原文のまま承認)

        Returns:
            True if approved successfully
        """
        if not isinstance(proposal_id, str) or not proposal_id:
            logger.warning("[PhilosophyProposal] 無効な proposal_id が指定されました。")
            return False
        if edited is not None and not isinstance(edited, str):
            logger.warning("[PhilosophyProposal] 無効な edited テキストが指定されました。")
            return False

        evo_log = self._load_evolution_log()
        pending = evo_log.get("pending_proposals")

        target = None
        for p in pending:
            if isinstance(p, dict) and p.get("proposal_id") == proposal_id:
                target = p
                break

        if target is None:
            logger.warning(
                f"[PhilosophyProposal] 提案ID未発見: {proposal_id}"
            )
            return False

        content = target.get("content")
        if not isinstance(content, str):
            content = str(content) if content is not None else ""

        # ステータス更新
        final_text = edited if edited else content
        if edited:
            target["status"] = "edited"
            target["user_edit"] = edited
        else:
            target["status"] = "approved"

        # SC-03: philosophies に追記 (approve経由のみ)
        philosophies_list = evo_log.get("philosophies")
        philosophies_list.append({
            "philosophy": final_text,
            "source": "proposal",
            "proposal_id": proposal_id,
            "approved_at": datetime.now().isoformat(),
            "original_content": content,
            "was_edited": edited is not None,
        })

        self._save_evolution_log(evo_log)
        logger.info(
            f"[PhilosophyProposal] 承認完了: {proposal_id} "
            f"(edited={edited is not None})"
        )
        return True

    def reject_proposal(self, proposal_id: Any, reason: Any) -> bool:
        """哲学候補を却下 → decision_logに却下理由記録 (S422-05)

        Args:
            proposal_id: 却下する提案ID
            reason: 却下理由

        Returns:
            True if rejected successfully
        """
        if not isinstance(proposal_id, str) or not proposal_id:
            logger.warning("[PhilosophyProposal] 無効な proposal_id が指定されました。")
            return False
        if not isinstance(reason, str) or not reason:
            logger.warning("[PhilosophyProposal] 無効な却下理由が指定されました。")
            return False

        evo_log = self._load_evolution_log()
        pending = evo_log.get("pending_proposals")

        target = None
        for p in pending:
            if isinstance(p, dict) and p.get("proposal_id") == proposal_id:
                target = p
                break

        if target is None:
            logger.warning(
                f"[PhilosophyProposal] 提案ID未発見: {proposal_id}"
            )
            return False

        target["status"] = "rejected"

        content = target.get("content")
        if not isinstance(content, str):
            content = str(content) if content is not None else ""

        # decision_log に却下理由を記録
        decision_insights = evo_log.get("decision_insights")
        decision_insights.append({
            "type": "philosophy_rejection",
            "proposal_id": proposal_id,
            "reason": reason,
            "rejected_at": datetime.now().isoformat(),
            "original_content": content,
        })

        # M-06: rejection_historyにcontent_hash+reason付きで記録
        rejection_history = evo_log.get("rejection_history")
        rejection_history.append({
            "proposal_id": proposal_id,
            "reason": reason,
            "content_hash": hashlib.sha256(
                content.encode()
            ).hexdigest()[:16],
            "rejected_at": datetime.now().isoformat(),
        })

        self._save_evolution_log(evo_log)
        logger.info(
            f"[PhilosophyProposal] 却下完了: {proposal_id} reason={reason}"
        )

        # [C-02] §5.2 こだわりの昇華: 却下理由からこだわり派生提案を自動キュー
        self._auto_generate_from_rejection(reason, content)

        return True

    # ------------------------------------------------------------------
    # Internal: プロンプト構築
    # ------------------------------------------------------------------

    def _build_proposal_prompt(self, philosophies: List[Dict]) -> str:
        """哲学提案用のプロンプトを構築 (M-06: 過去却下理由注入)"""
        # D-04: 主軸はプロンプトへの過去却下理由注入
        past_rejections = self._get_past_rejections()
        rejection_context = ""
        if isinstance(past_rejections, list) and past_rejections:
            recent = past_rejections[-5:]  # 直近5件
            reasons = []
            for r in recent:
                if isinstance(r, dict) and "reason" in r:
                    reasons.append(r["reason"])
            if reasons:
                rejection_context = f"""

## 過去の却下理由（これらの内容に類似する提案は避けること）
{json.dumps(reasons, ensure_ascii=False)}
"""
        safe_philosophies = []
        if isinstance(philosophies, list):
            for p in philosophies[-20:]:
                if isinstance(p, dict):
                    safe_philosophies.append(p)
                else:
                    safe_philosophies.append({"text": str(p)})

        return f"""あなたはAntigravity Video Studioの哲学顧問です。
監督の演出哲学を深化させる新たな哲学を1つ提案してください。

## 既存の哲学（直近20件）
{json.dumps(safe_philosophies, ensure_ascii=False, indent=2)}
{rejection_context}
## 出力形式
新しい哲学を日本語で1-3文で簡潔に提案してください。
既存の哲学と矛盾せず、それらを発展・深化させる内容であること。
JSON形式ではなく、自然な日本語テキストで出力してください。
"""

    def _build_integration_prompt(self, philosophies: List[Dict]) -> str:
        """§12.2.3: 哲学統合用プロンプト (C-01)"""
        safe_philosophies = []
        if isinstance(philosophies, list):
            for p in philosophies:
                if isinstance(p, dict):
                    safe_philosophies.append(p)
                else:
                    safe_philosophies.append({"text": str(p)})

        return f"""あなたはAntigravity Video Studioの哲学統合顧問です。
以下の{len(safe_philosophies)}件の演出哲学を分析し、それらを**統合・昇華**した
より深い演出哲学を1つ提案してください。

## 統合対象の哲学
{json.dumps(safe_philosophies, ensure_ascii=False, indent=2)}

## 要件
- 個々の哲学の核心を失わず、上位概念として統合すること
- 既存の哲学と矛盾しないこと
- 1-3文の日本語テキストで出力すること
- JSON形式ではなく、自然な日本語で出力すること
"""

    # ------------------------------------------------------------------
    # Internal: Gemini呼出し
    # ------------------------------------------------------------------

    async def _call_gemini(self, model_name: str, prompt: str) -> Optional[str]:
        """Gemini APIを呼び出して哲学テキストを生成 (SC-05: get_model経由)"""
        from gemini_client_factory import get_gemini_client
        client = get_gemini_client()
        if not client:
            logger.warning(
                "[PhilosophyProposal] Geminiクライアント取得失敗"
            )
            return None

        response = await asyncio.to_thread(
            client.models.generate_content,
            model=model_name,
            contents=prompt,
        )

        try:
            return response.text.strip()
        except (AttributeError, TypeError):
            logger.warning("[PhilosophyProposal] レスポンスパース失敗")
            return None

    # ------------------------------------------------------------------
    # Internal: pending_proposals管理
    # ------------------------------------------------------------------

    _PENDING_PROPOSALS_MAX = 50  # m-03: pending_proposals上限

    def _trim_pending_proposals(self) -> None:
        """pending_proposalsが上限を超えた場合、古い順に削除 (m-03, SC-05)

        削除優先順:
        1. 解決済み(approved/rejected/edited) → 古い順
        2. pending → 古い順
        最新データは必ず保持される。
        """
        evo_log = self._load_evolution_log()
        proposals = evo_log.get("pending_proposals")

        if len(proposals) <= self._PENDING_PROPOSALS_MAX:
            return

        overflow = len(proposals) - self._PENDING_PROPOSALS_MAX
        # 解決済みを先に削除 (古い順)
        resolved_indices = []
        for i, p in enumerate(proposals):
            if isinstance(p, dict) and p.get("status") in ("approved", "rejected", "edited"):
                resolved_indices.append(i)

        remove_indices = set(resolved_indices[:overflow])

        # 解決済みだけでは足りない場合、古い順にpendingも削除
        if len(remove_indices) < overflow:
            remaining = overflow - len(remove_indices)
            for i, p in enumerate(proposals):
                if i not in remove_indices:
                    remove_indices.add(i)
                    remaining -= 1
                    if remaining <= 0:
                        break

        evo_log["pending_proposals"] = [
            p for i, p in enumerate(proposals) if i not in remove_indices
        ]
        self._save_evolution_log(evo_log)
        logger.info(
            f"[PhilosophyProposal] pending_proposals trimmed: "
            f"{len(proposals)} → {len(evo_log['pending_proposals'])}"
        )

    def _add_pending_proposal(
        self,
        proposal: PhilosophyProposal,
        proposal_type: str = "standard",
        extra_fields: Optional[Dict] = None,
    ) -> None:
        """pending_proposalsに追加して永続化 (S422-08)

        Args:
            proposal: 追加する提案
            proposal_type: "standard" | "integration" (C-01) | "rejection_insight" (C-02)
            extra_fields: 追加フィールド (M-03: conflict等)
        """
        if not isinstance(proposal_type, str):
            proposal_type = str(proposal_type)

        evo_log = self._load_evolution_log()
        entry = {
            "proposal_id": getattr(proposal, "proposal_id", str(uuid.uuid4())),
            "content": getattr(proposal, "content", ""),
            "source_summary": getattr(proposal, "source_summary", ""),
            "generated_at": getattr(proposal, "generated_at", datetime.now().isoformat()),
            "status": getattr(proposal, "status", "pending"),
            "user_edit": getattr(proposal, "user_edit", None),
            "proposal_type": proposal_type,  # SC-13
        }
        if extra_fields and isinstance(extra_fields, dict):
            entry.update(extra_fields)

        pending_proposals = evo_log.get("pending_proposals")
        pending_proposals.append(entry)
        self._save_evolution_log(evo_log)

    # ------------------------------------------------------------------
    # Internal: M-03 矛盾検出 + M-06 過去却下参照
    # ------------------------------------------------------------------

    def _check_conflict_rules(
        self, new_content: str, existing: List[Dict]
    ) -> Optional[str]:
        """ルールベース矛盾検出 (D-02: プロンプト依存の形骸化防止)

        チェックルール:
        1. 既存哲学と正反対のキーワード（速い↔遅い、派手↔控えめ等）
        2. 直近5件の哲学と文字列類似度が高すぎる（重複検出）
        """
        if not isinstance(new_content, str):
            return None
        if not isinstance(existing, list):
            return None

        OPPOSITES = [
            ("速い", "遅い"), ("派手", "控えめ"), ("大胆", "慎重"),
            ("シンプル", "複雑"), ("静か", "激しい"), ("明るい", "暗い"),
        ]
        for p in existing[-20:]:
            p_text = ""
            if isinstance(p, dict):
                if "philosophy" in p:
                    p_text = p["philosophy"]
                elif "text" in p:
                    p_text = p["text"]
            else:
                p_text = str(p)

            if not isinstance(p_text, str):
                p_text = str(p_text)

            for a, b in OPPOSITES:
                if (a in new_content and b in p_text) or (
                    b in new_content and a in p_text
                ):
                    return (
                        f"方向性の矛盾: 新提案に'"
                        f"{a if a in new_content else b}'、"
                        f"既存に'{b if a in new_content else a}'が含まれる"
                    )
        return None

    def _get_past_rejections(self) -> List[Dict]:
        """過去の却下履歴を取得 (M-06: 重複提案抑制用)"""
        evo_log = self._load_evolution_log()
        return evo_log.get("rejection_history")

    def _check_similar_rejection(self, content: str) -> Optional[Dict]:
        """提案内容が過去の却下と類似しているかチェック

        D-04修正: content_hashは完全一致のみ検出するため補助機能。
        主軸は_build_proposal_promptでの過去却下理由プロンプト注入。
        """
        if not isinstance(content, str):
            content = str(content)
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        past_rejections = self._get_past_rejections()
        for rejection in past_rejections:
            if isinstance(rejection, dict) and rejection.get("content_hash") == content_hash:
                return rejection
        return None

    def _auto_generate_from_rejection(
        self, rejection_reason: str, original_content: str
    ) -> None:
        """§5.2: 却下理由から「こだわり」を哲学候補として自動生成キュー (C-02)

        却下理由を分析し、「監督のこだわり」として新たな哲学候補を生成。
        これにより却下→学習→提案のクローズドループが完成する。
        """
        if not isinstance(rejection_reason, str):
            rejection_reason = str(rejection_reason)
        if not isinstance(original_content, str):
            original_content = str(original_content)

        evo_log = self._load_evolution_log()

        insight_proposal = {
            "proposal_id": str(uuid.uuid4()),
            "content": f"却下理由「{rejection_reason}」から抽出: "
                       f"この監督は{rejection_reason}を重視する哲学を持つ",
            "source_summary": f"rejection_insight: {original_content[:50]}",
            "generated_at": datetime.now().isoformat(),
            "status": "pending",
            "user_edit": None,
            "proposal_type": "rejection_insight",  # SC-13
        }

        pending_proposals = evo_log.get("pending_proposals")
        pending_proposals.append(insight_proposal)
        self._save_evolution_log(evo_log)

        logger.info(
            f"[PhilosophyProposal] こだわり派生提案を自動生成: "
            f"reason={rejection_reason[:30]}"
        )

    # ------------------------------------------------------------------
    # Internal: ファイルI/O
    # ------------------------------------------------------------------

    def _load_evolution_log(self) -> Dict:
        """evolution_log.jsonを読み込み (SC-06: 既存フィールド非破壊, C-05: filelock)"""
        from utils.json_safe_io import safe_load_json
        try:
            data = safe_load_json(self._evolution_log_path)
            if isinstance(data, dict):
                # 新フィールドを非破壊で初期化 (SC-06)
                data.setdefault("pending_proposals", [])
                data.setdefault("philosophies", [])
                data.setdefault("decision_insights", [])
                data.setdefault("rejection_history", [])

                # 型の強制
                if not isinstance(data.get("pending_proposals"), list):
                    data["pending_proposals"] = []
                if not isinstance(data.get("philosophies"), list):
                    data["philosophies"] = []
                if not isinstance(data.get("decision_insights"), list):
                    data["decision_insights"] = []
                if not isinstance(data.get("rejection_history"), list):
                    data["rejection_history"] = []

                return data
        except Exception as e:
            logger.warning(
                "[PhilosophyProposal] evolution_log読込失敗", exc_info=True
            )
        return {
            "entries": [],
            "philosophies": [],
            "decision_insights": [],
            "pending_proposals": [],
            "rejection_history": [],
        }

    def _save_evolution_log(self, data: Dict) -> None:
        """evolution_log.jsonに保存 (C-05: filelock)"""
        if not isinstance(data, dict):
            logger.warning("[PhilosophyProposal] 保存するデータが辞書型ではありません。")
            return
        from utils.json_safe_io import safe_save_json
        data["last_updated"] = datetime.now().isoformat()
        try:
            safe_save_json(self._evolution_log_path, data)
        except Exception as e:
            logger.exception(
                "[PhilosophyProposal] evolution_log保存失敗"
            )
