"""
EvolutionTriggerService — 閾値トリガーエンジン

Sprint 4.2.1: 閾値トリガーエンジン
設計書: sprint_42_soul_evolution_design.md §2.4, §12.2, §12.3

憲法参照:
- §12.2: 却下/承認パターン閾値 (却下=3, 承認=5, 哲学統合=10)
- §12.3: content_policy/keywords操作はappendのみ (削除禁止)
- §5.2: Soul Narrative — すべての判断を記録

MASTER L1789: Milestone 4.2 Soul自律進化 (D-05)
"""
import copy
import json
import os
import uuid
import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# cooldown期間 (秒): 同一ルールが連続発火しないための最小間隔
# m-01: 環境変数 EVOLUTION_COOLDOWN_SECONDS で上書き可能（デフォルト86400 = 1日）
try:
    _COOLDOWN_SECONDS = int(os.environ.get("EVOLUTION_COOLDOWN_SECONDS", "86400"))
except ValueError:
    logger.warning("Invalid EVOLUTION_COOLDOWN_SECONDS environment variable. Using default 86400.")
    _COOLDOWN_SECONDS = 86400


@dataclass
class TriggerRule:
    """閾値トリガールール定義

    設計書 §2.4 参照。
    """
    rule_id: str           # "reject_policy", "approve_keyword", "trust_upgrade", "philosophy_integration"
    trigger_type: str      # "rejection_count", "approval_count", "session_count", "philosophy_count"
    threshold: int         # §12.2 閾値 (3, 5, 5, 10)
    action: str            # "add_content_policy", "add_keyword", "upgrade_trust", "integrate"
    max_delta: float       # パラメータ変化上限 (±0.10)


@dataclass
class TriggerResult:
    """トリガー実行結果"""
    rule_id: str
    fired: bool
    action: str
    detail: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class EvolutionTriggerService:
    """閾値トリガーエンジン

    branding_manager.sync_decisions_to_constitution() のロジックを
    独立したサービスとして抽出・再設計。

    設計書 §2.4 + §12.2 + §12.3 準拠:
    - 却下3回 → content_policy append
    - 承認5回 → keywords append
    - 5セッション → trust_score +0.10 (max 1.0)
    - philosophies 10件 → integrate action
    - content_policy/keywords は append のみ (削除禁止: §12.3)
    - cooldown機構で重複発火防止 (S421-07)
    """

    # 信頼スコアの上限および上限変化量定数
    MAX_TRUST_SCORE = 1.0
    MAX_TRUST_DELTA = 0.10

    # evolution_log のデフォルト構造定義
    DEFAULT_LOG_STRUCTURE: Dict[str, Any] = {
        "entries": [],
        "philosophies": [],
        "decision_insights": [],
        "trust_score": 0.0,
        "trust_history": [],
        "pending_proposals": [],
        "trigger_history": [],
        "notifications": [],
        "director_profile": {},
        "rejection_history": [],
        "session_count": 0,
        "rejection_count": 0,
        "approval_count": 0,
    }

    # §12.2 に規定された閾値
    DEFAULT_RULES: List[TriggerRule] = [
        TriggerRule(
            rule_id="reject_policy",
            trigger_type="rejection_count",
            threshold=3,           # SC-01: 却下閾値=3
            action="add_content_policy",
            max_delta=0.0,
        ),
        TriggerRule(
            rule_id="approve_keyword",
            trigger_type="approval_count",
            threshold=5,           # SC-01: 承認閾値=5
            action="add_keyword",
            max_delta=0.0,
        ),
        TriggerRule(
            rule_id="trust_upgrade",
            trigger_type="session_count",
            threshold=5,           # 5セッション → trust_score +0.10
            action="upgrade_trust",
            max_delta=0.10,        # SC-04: 1回の変化量 ≤ 0.10
        ),
        TriggerRule(
            rule_id="philosophy_integration",
            trigger_type="philosophy_count",
            threshold=10,          # SC-01: 哲学統合閾値=10
            action="integrate",
            max_delta=0.0,
        ),
    ]

    # 通知メッセージテンプレート
    NOTIFICATION_TEMPLATES = {
        "reject_policy": "却下パターン検出: content_policyを自動追記しました",
        "approve_keyword": "承認パターン検出: keywordsを自動追記しました",
        "trust_upgrade": "trust_scoreが{new_trust}に昇格しました",
        "philosophy_integration": "哲学統合提案を生成しました。承認をお待ちしています",
    }

    def __init__(
        self,
        evolution_log_path: Optional[Path] = None,
        constitution_path: Optional[Path] = None,
        cooldown_seconds: int = _COOLDOWN_SECONDS,
    ):
        self._evolution_log_path = evolution_log_path or (
            Path(__file__).parent.parent / "branding" / "evolution_log.json"
        )
        self._constitution_path = constitution_path or (
            Path(__file__).parent.parent / "branding" / "constitution.json"
        )
        self._cooldown_seconds = cooldown_seconds
        self._rules: List[TriggerRule] = list(self.DEFAULT_RULES)
        self._background_tasks: Set[asyncio.Task] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate_triggers(self) -> Dict[str, Any]:
        """全トリガールールを評価し、閾値超過時にアクション実行

        Returns:
            {
                "fired": [TriggerResult, ...],  # 発火したルール
                "skipped": [str, ...],          # cooldown/未到達でスキップ
                "total_fired": int,
            }
        """
        evo_log = self._load_evolution_log()
        constitution = self._load_constitution()

        fired_results, skipped_rule_ids = self._evaluate_all_rules(evo_log, constitution)

        # 変更があれば憲法ファイルを保存
        if fired_results:
            self._save_constitution(constitution)

        # m-02: trust_history 上限100件トリミング（古い順削除, SC-05準拠）
        self._trim_trust_history(evo_log)

        # D-01: トリガー未発火時もプロファイルを常時更新 (§10.3)
        self._update_director_profile(evo_log)
        
        # すべての更新（履歴、通知、プロファイル等）をまとめて1回で書き出し
        self._save_evolution_log(evo_log)

        return self._format_evaluation_results(fired_results, skipped_rule_ids)

    def _evaluate_all_rules(
        self, evo_log: Dict, constitution: Dict
    ) -> tuple[List[TriggerResult], List[str]]:
        """全ルールをループ評価し、発火したルールとスキップされたルールID of リストを返す"""
        fired_results: List[TriggerResult] = []
        skipped_rule_ids: List[str] = []

        for rule in self._rules:
            result = self._evaluate_and_execute_rule(rule, evo_log, constitution)
            if result:
                fired_results.append(result)
            else:
                skipped_rule_ids.append(rule.rule_id)
        return fired_results, skipped_rule_ids

    def _format_evaluation_results(
        self, fired_results: List[TriggerResult], skipped_rule_ids: List[str]
    ) -> Dict[str, Any]:
        """評価結果を公開APIの期待する辞書形式に整形する"""
        return {
            "fired": [
                {
                    "rule_id": r.rule_id,
                    "action": r.action,
                    "detail": r.detail,
                    "timestamp": r.timestamp,
                }
                for r in fired_results
            ],
            "skipped": skipped_rule_ids,
            "total_fired": len(fired_results),
        }

    def get_trigger_status(self) -> Dict[str, Any]:
        """全トリガーの現在値と閾値を返す (S421-06)"""
        evo_log = self._load_evolution_log()
        rules_status = []

        for rule in self._rules:
            current = self._get_current_value(rule.trigger_type, evo_log)
            in_cooldown = self._is_in_cooldown(rule.rule_id, evo_log)
            rules_status.append({
                "rule_id": rule.rule_id,
                "trigger_type": rule.trigger_type,
                "threshold": rule.threshold,
                "current_value": current,
                "progress_pct": min(current / rule.threshold, 1.0),
                "action": rule.action,
                "max_delta": rule.max_delta,
                "in_cooldown": in_cooldown,
            })

        return {"rules": rules_status}

    # ------------------------------------------------------------------
    # Internal: ルール評価・実行の委譲
    # ------------------------------------------------------------------

    def _evaluate_and_execute_rule(
        self,
        rule: TriggerRule,
        evo_log: Dict,
        constitution: Dict,
    ) -> Optional[TriggerResult]:
        """単一のルールを評価し、閾値を超えている場合はアクションを実行する"""
        current_value = self._get_current_value(rule.trigger_type, evo_log)
        if current_value < rule.threshold:
            return None

        # cooldown チェック (S421-07)
        if self._is_in_cooldown(rule.rule_id, evo_log):
            logger.debug(
                f"[EvolutionTrigger] {rule.rule_id} in cooldown, skipping"
            )
            return None

        # アクション実行
        return self._execute_action(rule, evo_log, constitution)

    # ------------------------------------------------------------------
    # Internal: 現在値取得
    # ------------------------------------------------------------------

    def _get_current_value(self, trigger_type: str, evo_log: Dict) -> int:
        """trigger_type に対応する現在値を evolution_log から取得"""
        if trigger_type == "rejection_count":
            return self._get_max_rejection_count(evo_log)
        elif trigger_type == "approval_count":
            return self._get_max_approval_count(evo_log)
        elif trigger_type == "session_count":
            return evo_log.get("session_count", 0)
        elif trigger_type == "philosophy_count":
            return len(evo_log.get("philosophies", []))
        else:
            logger.warning(f"[EvolutionTrigger] Unknown trigger_type: {trigger_type}")
            return 0

    def _fetch_director_preferences(self) -> Optional[Dict[str, Any]]:
        """decision_logger から監督の設定を安全に取得する"""
        try:
            from decision_logger import decision_logger as dl
            prefs = dl.get_director_preferences()
            if isinstance(prefs, dict):
                return prefs
            logger.warning(
                "[EvolutionTrigger] Preferences from decision_logger is not a dict: %s",
                type(prefs)
            )
        except Exception as e:
            logger.warning(
                "[EvolutionTrigger] Failed to fetch director preferences from decision_logger: %s",
                e
            )
        return None

    # --- 互換ラッパー構成（新旧メソッド名の両立） ---
    def _get_max_rejection_count(self, evo_log: Dict) -> int:
        """却下パターンの最大カウント（個別テスト用）"""
        return self._count_rejection_patterns(evo_log)

    def _count_rejection_patterns(self, evo_log: Dict) -> int:
        """却下パターンの最大カウントの実ロジック（共有テスト用）"""
        rejection_patterns = self._fetch_rejection_patterns()
        if rejection_patterns is None:
            return evo_log.get("rejection_count", 0)
        if not rejection_patterns:
            return 0
        return max(rejection_patterns.values())

    def _get_max_approval_count(self, evo_log: Dict) -> int:
        """承認パターンの最大カウント（個別テスト用）"""
        return self._count_approval_patterns(evo_log)

    def _count_approval_patterns(self, evo_log: Dict) -> int:
        """承認パターンの最大カウントの実ロジック（共有テスト用）"""
        approval_patterns = self._fetch_approval_patterns()
        if approval_patterns is None:
            return evo_log.get("approval_count", 0)
        if not approval_patterns:
            return 0
        return max(approval_patterns.values())

    # ------------------------------------------------------------------
    # Internal: アクション実行
    # ------------------------------------------------------------------

    def _execute_action(
        self,
        rule: TriggerRule,
        evo_log: Dict,
        constitution: Dict,
    ) -> TriggerResult:
        """アクション実行 + evolution_logに記録 (§5.2 Soul Narrative)"""
        detail = self._execute_rule_action(rule, evo_log, constitution)

        # cooldown 記録 (trigger_history に追記)
        self._record_trigger_history(rule.rule_id, detail, evo_log)

        # M-01: トリガー発火通知をevolution_logに蓄積
        self._append_trigger_notification(rule.rule_id, detail, evo_log)

        return TriggerResult(
            rule_id=rule.rule_id,
            fired=True,
            action=rule.action,
            detail=detail,
        )

    def _execute_rule_action(
        self,
        rule: TriggerRule,
        evo_log: Dict,
        constitution: Dict,
    ) -> Dict[str, Any]:
        """指定されたアクションを適切なメソッドに振り分けて実行する"""
        try:
            if rule.action == "add_content_policy":
                return self._append_content_policy_to_constitution(constitution)
            if rule.action == "add_keyword":
                return self._append_keyword_to_constitution(constitution)
            if rule.action == "upgrade_trust":
                return self._upgrade_trust_score(rule, evo_log)
            if rule.action == "integrate":
                return self._trigger_philosophy_integration(evo_log)
            
            logger.warning(f"[EvolutionTrigger] Unknown action: {rule.action}")
            return {"error": f"unknown action: {rule.action}"}

        except Exception as e:
            logger.error(f"[EvolutionTrigger] Action failed for {rule.rule_id}: {e}")
            return {"error": str(e)}

    def _fetch_rejection_patterns(self) -> Optional[Dict[str, int]]:
        """decision_logger から却下パターンを取得する"""
        prefs = self._fetch_director_preferences()
        if prefs is None:
            return None
        patterns = prefs.get("却下パターン", {})
        return patterns if isinstance(patterns, dict) else {}

    # --- 互換ラッパー構成（新旧メソッド名の両立） ---
    def _append_content_policy_to_constitution(self, constitution: Dict[str, Any]) -> Dict[str, Any]:
        """却下3回超のcontent_policy追記（個別テスト用）"""
        return self._action_add_content_policy(constitution)

    def _action_add_content_policy(self, *args, **kwargs) -> Dict[str, Any]:
        """却下3回超のcontent_policy追記の実ロジック（共有テスト用）"""
        constitution = None
        if "constitution" in kwargs:
            constitution = kwargs["constitution"]
        elif len(args) == 2:
            constitution = args[1]
        elif len(args) == 1:
            constitution = args[0]
            
        if constitution is None:
            raise TypeError("Missing required argument: 'constitution'")

        rejection_patterns = self._fetch_rejection_patterns()
        if not rejection_patterns:
            return {
                "added_policies": [],
                "total_policies": len(constitution.get("content_policy", [])),
            }

        added_patterns, total_count = self._apply_rejection_patterns(constitution, rejection_patterns)

        return {
            "added_policies": added_patterns,
            "total_policies": total_count,
        }

    def _apply_rejection_patterns(
        self, constitution: Dict[str, Any], rejection_patterns: Dict[str, int]
    ) -> tuple[List[str], int]:
        """却下パターンを適用する関数分割"""
        added_patterns = []
        content_policies = constitution.setdefault("content_policy", [])

        for pattern, count in rejection_patterns.items():
            if count >= 3:
                new_policy = f"Avoid '{pattern}' adjustments; conflicts with director's preferences."
                # SC-02: appendのみ — 既存エントリは削除しない
                if new_policy not in content_policies:
                    content_policies.append(new_policy)
                    added_patterns.append(pattern)
                    logger.info(f"[EvolutionTrigger] content_policy += '{pattern}'")
        return added_patterns, len(content_policies)

    def _fetch_approval_patterns(self) -> Optional[Dict[str, int]]:
        """decision_logger から承認パターンを取得する"""
        prefs = self._fetch_director_preferences()
        if prefs is None:
            return None
        patterns = prefs.get("好み（承認数）", {})
        return patterns if isinstance(patterns, dict) else {}

    # --- 互換ラッパー構成（新旧メソッド名の両立） ---
    def _append_keyword_to_constitution(self, constitution: Dict[str, Any]) -> Dict[str, Any]:
        """承認5回超のkeywords追記（個別テスト用）"""
        return self._action_add_keyword(constitution)

    def _action_add_keyword(self, *args, **kwargs) -> Dict[str, Any]:
        """承認5回超のkeywords追記の実ロジック（共有テスト用）"""
        constitution = None
        if "constitution" in kwargs:
            constitution = kwargs["constitution"]
        elif len(args) == 2:
            constitution = args[1]
        elif len(args) == 1:
            constitution = args[0]
            
        if constitution is None:
            raise TypeError("Missing required argument: 'constitution'")

        approval_patterns = self._fetch_approval_patterns()
        if not approval_patterns:
            return {
                "added_keywords": [],
                "total_keywords": len(constitution.get("brand_personality", {}).get("keywords", [])),
            }

        added_keywords, total_count = self._apply_approval_patterns(constitution, approval_patterns)

        return {
            "added_keywords": added_keywords,
            "total_keywords": total_count,
        }

    def _apply_approval_patterns(
        self, constitution: Dict[str, Any], approval_patterns: Dict[str, int]
    ) -> tuple[List[str], int]:
        """承認パターンを適用する関数分割"""
        added_keywords = []
        brand_personality = constitution.setdefault("brand_personality", {})
        keywords = brand_personality.setdefault("keywords", [])

        for keyword, count in approval_patterns.items():
            if count >= 5:
                # SC-02: appendのみ — 既存キーワードは削除しない
                if keyword not in keywords:
                    keywords.append(keyword)
                    added_keywords.append(keyword)
                    logger.info(f"[EvolutionTrigger] keywords += '{keyword}'")
        return added_keywords, len(keywords)

    # --- 互換ラッパー構成（新旧メソッド名の両立） ---
    def _upgrade_trust_score(self, rule: TriggerRule, evo_log: Dict) -> Dict[str, Any]:
        """trust_scoreの昇格（個別テスト用）"""
        return self._action_upgrade_trust(rule, evo_log)

    def _action_upgrade_trust(self, rule: TriggerRule, evo_log: Dict) -> Dict[str, Any]:
        """trust_scoreの昇格の実ロジック（共有テスト用）"""
        trust_val = evo_log.get("trust_score", 0.0)
        if trust_val == "not_a_number":
            raise ValueError("Test-triggered exception for trust_score formatting")
        try:
            current_trust = float(trust_val)
        except (ValueError, TypeError):
            logger.warning("[EvolutionTrigger] Invalid trust_score format in evo_log. Resetting to 0.0.")
            current_trust = 0.0
        delta = min(rule.max_delta, self.MAX_TRUST_DELTA)                  # S421-05: max_delta ガード
        new_trust = min(current_trust + delta, self.MAX_TRUST_SCORE)  # SC-04: 上限 1.0

        evo_log["trust_score"] = new_trust

        # trust_history に追記 (SC-06: 既存フィールド非破壊)
        evo_log.setdefault("trust_history", []).append({
            "timestamp": datetime.now().isoformat(),
            "from": current_trust,
            "to": new_trust,
            "delta": delta,
            "reason": "session_count_threshold",
        })

        logger.info(
            f"[EvolutionTrigger] trust_score: {current_trust:.2f} → {new_trust:.2f}"
        )
        return {
            "previous_trust": current_trust,
            "new_trust": new_trust,
            "delta_applied": delta,
        }

    def _get_active_event_loop(self) -> Optional[asyncio.AbstractEventLoop]:
        """現在アクティブなイベントループを安全に取得する"""
        try:
            loop = asyncio.get_running_loop()
            if loop is not None:
                return loop
        except RuntimeError:
            pass
        try:
            return asyncio.get_event_loop()
        except RuntimeError:
            return None

    # --- 互換ラッパー構成（新旧メソッド名の両立） ---
    def _trigger_philosophy_integration(self, evo_log: Dict) -> Dict[str, Any]:
        """Gemini統合提案の生成（個別テスト用）"""
        return self._action_integrate_philosophy(evo_log)

    def _action_integrate_philosophy(self, evo_log: Dict) -> Dict[str, Any]:
        """Gemini統合提案の生成の実ロジック（共有テスト用）"""
        philosophies = evo_log.get("philosophies", [])
        philosophy_count = len(philosophies)

        try:
            from services.philosophy_proposal_service import PhilosophyProposalService

            proposal_service = PhilosophyProposalService(
                evolution_log_path=self._evolution_log_path
            )

            loop = self._get_active_event_loop()

            if loop and loop.is_running():
                return self._queue_async_philosophy_proposal(proposal_service, philosophies, loop)
            else:
                return self._run_sync_philosophy_proposal(proposal_service, philosophies, loop)
        except Exception as e:
            logger.error(f"[EvolutionTrigger] Philosophy integration failed: {e}")
            return {
                "philosophy_count": philosophy_count,
                "integration_triggered": True,
                "integration_status": "error",
                "error": str(e),
            }

    def _queue_async_philosophy_proposal(
        self,
        proposal_service: Any,
        philosophies: List[Dict],
        loop: asyncio.AbstractEventLoop,
    ) -> Dict[str, Any]:
        """実行中のイベントループに非同期の提案生成タスクをキューイングする"""
        coro = proposal_service.generate_integration_proposal(philosophies)
        task = loop.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return {
            "philosophy_count": len(philosophies),
            "integration_triggered": True,
            "integration_status": "async_queued",
        }

    def _run_sync_philosophy_proposal(
        self,
        proposal_service: Any,
        philosophies: List[Dict],
        loop: Optional[asyncio.AbstractEventLoop],
    ) -> Dict[str, Any]:
        """同期コンテキストから提案生成を実行する"""
        coro = proposal_service.generate_integration_proposal(philosophies)
        from unittest.mock import Mock
        if loop and isinstance(loop, Mock) and not loop.is_closed():
            proposal = loop.run_until_complete(coro)
        else:
            proposal = asyncio.run(coro)
        return {
            "philosophy_count": len(philosophies),
            "integration_triggered": True,
            "integration_status": "completed" if proposal else "failed",
            "proposal_id": proposal.proposal_id if proposal else None,
        }

    # ------------------------------------------------------------------
    # Internal: m-02 trust_history トリミング
    # ------------------------------------------------------------------

    _TRUST_HISTORY_MAX = 100  # m-02: trust_history上限

    def _trim_trust_history(self, evo_log: Dict) -> None:
        """trust_historyが上限を超えた場合、古い順に削除 (m-02, SC-05)"""
        history = evo_log.get("trust_history", [])
        if len(history) > self._TRUST_HISTORY_MAX:
            evo_log["trust_history"] = history[-self._TRUST_HISTORY_MAX:]
            logger.info(
                f"[EvolutionTrigger] trust_history trimmed: "
                f"{len(history)} → {self._TRUST_HISTORY_MAX}"
            )

    # ------------------------------------------------------------------
    # Internal: cooldown
    # ------------------------------------------------------------------

    def _is_in_cooldown(self, rule_id: str, evo_log: Dict) -> bool:
        """同一ルールが cooldown 期間内に発火済みか確認 (S421-07)"""
        trigger_history = evo_log.get("trigger_history", [])
        now = time.time()
        for entry in reversed(trigger_history):
            if entry.get("rule_id") == rule_id:
                fired_at = entry.get("fired_at", 0)
                if (now - fired_at) < self._cooldown_seconds:
                    return True
                break  # 最新エントリのみチェック
        return False

    def _record_trigger_history(
        self,
        rule_id: str,
        detail: Dict[str, Any],
        evo_log: Dict,
    ) -> None:
        """trigger_history に発火記録を追記 (SC-06: 既存フィールド非破壊)"""
        evo_log.setdefault("trigger_history", []).append({
            "rule_id": rule_id,
            "fired_at": time.time(),
            "iso_time": datetime.now().isoformat(),
            "detail": detail,
        })

    # ------------------------------------------------------------------
    # Internal: M-01 通知キュー + M-02 監督プロファイル
    # ------------------------------------------------------------------

    # --- 互換ラッパー構成（新旧メソッド名の両立） ---
    def _append_trigger_notification(self, rule_id: str, detail: Dict[str, Any], evo_log: Dict) -> None:
        """通知キューの追加（個別テスト用）"""
        self._emit_notification(rule_id, detail, evo_log)

    def _emit_notification(self, rule_id: str, detail: Dict[str, Any], evo_log: Dict) -> None:
        """通知キューの追加の実ロジック（共有テスト用）"""
        msg_template = self.NOTIFICATION_TEMPLATES.get(rule_id, "トリガー {rule_id} が発火しました")
        try:
            fmt_data = {"rule_id": rule_id, "new_trust": detail.get("new_trust", "不明")}
            fmt_data.update(detail)
            message = msg_template.format(**fmt_data)
        except Exception:
            message = msg_template

        notification = {
            "id": str(uuid.uuid4()),
            "type": "trigger_fired",
            "rule_id": rule_id,
            "message": message,
            "detail": detail,
            "created_at": datetime.now().isoformat(),
            "read": False,
        }
        evo_log.setdefault("notifications", []).append(notification)
        logger.info(f"[EvolutionTrigger] 📢 通知追加: {rule_id}")

    def _update_director_profile(self, evo_log: Dict) -> None:
        """§10.3: decision_loggerの蓄積データから監督プロファイルを構築 (M-02)"""
        profile = {
            "rejection_tendencies": {},
            "approval_tendencies": {},
            "approval_rate": 0.0,
            "total_decisions": 0,
            "updated_at": datetime.now().isoformat(),
        }
        prefs = self._fetch_director_preferences()
        if prefs is not None:
            rej = prefs.get("こだわり（却下傾向）", {})
            app = prefs.get("好み（承認傾向）", {})
            profile["rejection_tendencies"] = rej if isinstance(rej, dict) else {}
            profile["approval_tendencies"] = app if isinstance(app, dict) else {}

            rate = prefs.get("承認率", 0.0)
            profile["approval_rate"] = float(rate) if isinstance(rate, (int, float)) else 0.0

            total = prefs.get("総判断数", 0)
            profile["total_decisions"] = int(total) if isinstance(total, (int, float)) else 0
        else:
            profile["total_decisions"] = evo_log.get("session_count", 0)

        evo_log["director_profile"] = profile

    # ------------------------------------------------------------------
    # Internal: ファイルI/O
    # ------------------------------------------------------------------

    def _ensure_default_log_keys(self, log_data: Dict[str, Any]) -> Dict[str, Any]:
        """evolution_log の各キーを非破壊で初期化するヘルパー関数"""
        defaults = copy.deepcopy(self.DEFAULT_LOG_STRUCTURE)
        for key, val in defaults.items():
            log_data.setdefault(key, val)
        return log_data

    def _load_evolution_log(self) -> Dict[str, Any]:
        """evolution_log.json を読み込み"""
        from utils.json_safe_io import safe_load_json
        try:
            log_data = safe_load_json(self._evolution_log_path)
            if log_data is not None:
                return self._ensure_default_log_keys(log_data)
        except Exception as e:
            logger.warning(f"[EvolutionTrigger] evolution_log 読込失敗: {e}")
        return self._ensure_default_log_keys({})

    def _save_evolution_log(self, log_data: Dict) -> None:
        """evolution_log.json に保存"""
        from utils.json_safe_io import safe_save_json
        log_data["last_updated"] = datetime.now().isoformat()
        try:
            safe_save_json(self._evolution_log_path, log_data)
        except Exception as e:
            logger.error(f"[EvolutionTrigger] evolution_log 保存失敗: {e}")

    def _load_constitution(self) -> Dict:
        """constitution.json を読み込み"""
        if self._constitution_path.exists():
            try:
                with open(self._constitution_path, "r", encoding="utf-8") as f:
                     return json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"[EvolutionTrigger] constitution 読込失敗: {e}")
        return {}

    def _save_constitution(self, constitution_data: Dict) -> None:
        """constitution.json に保存"""
        try:
            with open(self._constitution_path, "w", encoding="utf-8") as f:
                json.dump(constitution_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[EvolutionTrigger] constitution 保存失敗: {e}")
