"""
EvolutionSyncService — 進化同期の統合ポイント

Sprint 4.1.4: EvolutionSyncService + trinity.pyリファクタリング
設計書: sprint_41_design.md §Q3 仮説B (統合設計)
憲法: §5.2 Soul Narrative / §10 意思決定の記録と学習 / §12 自動進化プロトコル

責務:
1. SmartCut Strategist + decision_logger + evolution_log の統合同期
2. CutStrategy のevolution_logへの記録
3. trinity.py を薄いプロキシに変更するための統合バックエンド

MASTER L1778-L1779 テスト:
- S414-01: sync_all() → decisions_synced + constitution_updates
- S414-02: finalize → evolution_logにstrategyエントリ
"""
import json
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Any
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class EvolutionSyncService:
    """SmartCut Strategist + decision_logger + evolution_log の統合同期

    憲法 §5.2 Soul Narrative: 固定理由の記録
    憲法 §10 意思決定の記録と学習
    憲法 §12 自動進化プロトコル

    設計書 sprint_41_design.md §Q3 仮説B:
    - 即座にメソッド名エイリアスを追加してtrinityを動作可能に
    - Phase 4で統合サービスを導入しtrinityを薄いプロキシに変更
    """

    def __init__(self, evolution_log_path: Path = None):
        self._evolution_log_path = evolution_log_path or (
            Path(__file__).parent.parent / "branding" / "evolution_log.json"
        )

    @contextmanager
    def _safe_execute(self, action_name: str):
        """例外を安全に捕捉して警告ログを出力するコンテキストマネージャ"""
        try:
            yield
        except ImportError as e:
            logger.warning(f"[EvolutionSync] {action_name} not available: {e}")
        except (AttributeError, KeyError, ValueError, TypeError, RuntimeError, OSError) as e:
            logger.warning(f"[EvolutionSync] {action_name} failed: {e}")

    def sync_all(self) -> Dict[str, Any]:
        """全自動進化処理を一括実行

        1. 意思決定をSoul Narrativeに同期 (decision_logger)
        2. constitution.json自動更新 (branding_manager)
        3. SmartCut戦略記録サマリー取得

        Returns:
            {"status": "success", "result": {decisions_synced, constitution_updates, ...}}
        """
        result = {
            "decisions_synced": 0,
            "constitution_updates": 0,
            "philosophy_triggered": False,
            "smartcut_strategies_recorded": 0,
            "trigger_results": [],
            "trust_score": 0.0,
        }

        # 1. 意思決定をSoul Narrativeに同期
        self._sync_decisions(result)

        # 2. constitution.json自動更新
        self._sync_branding_manager(result)

        # 共通でログをロード（ファイルI/Oの最適化）
        try:
            evolution_log = self._load_evolution_log()
        except Exception as e:
            logger.warning(f"[EvolutionSync] evolution_log読込失敗: {e}")
            evolution_log = {"entries": [], "philosophies": [], "decision_insights": []}

        # 3. 閾値トリガーエンジン評価 (Sprint 4.2.1)
        self._evaluate_evolution_triggers(result, evolution_log)

        # 4. SmartCut戦略記録数を取得
        self._record_strategy_counts(result, evolution_log)

        # 5. エージェント成功率同期 (DS-024)
        with self._safe_execute("agent_performance"):
            self.sync_agent_performance()

        return {"status": "success", "result": result}

    def _sync_decisions(self, result: Dict[str, Any]) -> None:
        """意思決定の同期ヘルパー"""
        with self._safe_execute("decision_logger"):
            from decision_logger import decision_logger
            sync_result = decision_logger.sync_to_soul_narrative()
            result["decisions_synced"] = sync_result.get("synced", 0)
            if sync_result.get("new_insights"):
                result["philosophy_triggered"] = True

    def _sync_branding_manager(self, result: Dict[str, Any]) -> None:
        """ブランドマネージャーの同期ヘルパー"""
        with self._safe_execute("branding_manager"):
            from branding_manager import branding_manager
            branding_update_result = branding_manager.process_analytics_update()
            result["constitution_updates"] = branding_update_result.get("updates", 0)

    def _evaluate_evolution_triggers(self, result: Dict[str, Any], evolution_log: Dict[str, Any]) -> None:
        """進化トリガーの評価ヘルパー"""
        with self._safe_execute("EvolutionTriggerService"):
            from services.evolution_trigger_service import EvolutionTriggerService
            trigger_svc = EvolutionTriggerService(
                evolution_log_path=self._evolution_log_path
            )
            trigger_result = trigger_svc.evaluate_triggers()
            result["trigger_results"] = trigger_result.get("fired", [])
            # trust_score を evolution_log から取得
            result["trust_score"] = evolution_log.get("trust_score", 0.0)

    def _record_strategy_counts(self, result: Dict[str, Any], evolution_log: Dict[str, Any]) -> None:
        """SmartCut戦略記録数のカウントヘルパー"""
        with self._safe_execute("strategy count"):
            strategy_entries = [
                entry for entry in evolution_log.get("entries", [])
                if entry.get("type") == "smartcut_strategy"
            ]
            result["smartcut_strategies_recorded"] = len(strategy_entries)

    def sync_agent_performance(self) -> Dict[str, Any]:
        """flash_reports.jsonl から各エージェントの成功率メタデータを集計し、
        evolution_log.json に同期・記録する。
        """
        reports_path = self._evolution_log_path.parent.parent / "agents" / "orchestration" / "flash_reports.jsonl"
        
        if not reports_path.exists():
            logger.warning(f"[EvolutionSync] flash_reports.jsonl が見つかりません: {reports_path}")
            return {}

        performance_summary = self._parse_and_aggregate_reports(reports_path)
        if not performance_summary:
            return {}

        try:
            evolution_log = self._load_evolution_log()
            evolution_log["agent_performance"] = performance_summary
            self._save_evolution_log(evolution_log)
            logger.info(f"[EvolutionSync] Agent performance synced: {performance_summary}")
            return performance_summary
        except (OSError, KeyError, TypeError, ValueError) as e:
            logger.error(f"[EvolutionSync] agent_performance を evolution_log に保存失敗: {e}")
            return {}

    def _parse_and_aggregate_reports(self, reports_path: Path) -> Dict[str, Any]:
        """flash_reports.jsonl を読み込んで集計するヘルパー"""
        performance_summary = {}
        try:
            with open(reports_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        batch_data = json.loads(line)
                        tasks = batch_data.get("tasks", [])
                        for task in tasks:
                            group = task.get("group")
                            status = task.get("status")
                            if not group or not status:
                                continue
                            
                            if group not in performance_summary:
                                performance_summary[group] = {"passed": 0, "failed": 0, "total": 0}
                            
                            performance_summary[group]["total"] += 1
                            if status == "pass":
                                performance_summary[group]["passed"] += 1
                            elif status in ("fail", "failed"):
                                performance_summary[group]["failed"] += 1
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
                        logger.warning(f"[EvolutionSync] flash_reports.jsonl 行パースエラー: {e}")
        except OSError as e:
            logger.error(f"[EvolutionSync] flash_reports.jsonl 読込失敗: {e}")
            return {}

        for group, stats in performance_summary.items():
            total = stats["total"]
            passed = stats["passed"]
            stats["success_rate"] = passed / total if total > 0 else 1.0

        return performance_summary

    def record_strategy(
        self,
        strategy: Any,
        session_id: str,
        finalize_result: Optional[Dict] = None,
    ) -> bool:
        """CutStrategy をevolution_logに記録

        §5.2 Soul Narrative: Strategistの判断を進化ログに反映
        §10: 意思决策記録

        Args:
            strategy: CutStrategy dataclass インスタンス
            session_id: SmartCutセッションID
            finalize_result: finalize結果（optional）

        Returns:
            True if recorded successfully
        """
        try:
            evolution_log = self._load_evolution_log()

            # strategyエントリを構築
            entry = {
                "timestamp": time.time(),
                "iso_time": datetime.now().isoformat(),
                "type": "smartcut_strategy",
                "session_id": session_id,
                "summary": f"SmartCut Strategist: {strategy.summary}",
                "insight": (
                    f"ブランド整合性: {strategy.brand_alignment_score:.2f}, "
                    f"推奨カット率: {strategy.recommended_cut_rate:.1%}, "
                    f"信頼スコア: {strategy.trust_score:.2f}"
                ),
                "stat_changes": [
                    f"Model: {strategy.model_used}",
                    f"Brand Alignment: {strategy.brand_alignment_score:.2f}",
                    f"Trust Score: {strategy.trust_score:.2f}",
                ],
                "strategy_detail": {
                    "position_weights": strategy.position_weights,
                    "brand_alignment_score": strategy.brand_alignment_score,
                    "recommended_cut_rate": strategy.recommended_cut_rate,
                    "applied_philosophies": strategy.applied_philosophies,
                    "model_used": strategy.model_used,
                    "trust_score": strategy.trust_score,
                    "generated_at": strategy.generated_at,
                },
            }

            # finalize結果があれば追加
            if finalize_result:
                final_segs = finalize_result.get("final_segments", [])
                if not isinstance(final_segs, list):
                    final_segs = []
                entry["finalize_summary"] = {
                    "total_duration": finalize_result.get("total_duration"),
                    "segment_count": len(final_segs),
                }

            evolution_log.setdefault("entries", []).append(entry)

            self._save_evolution_log(evolution_log)
            logger.info(
                f"[EvolutionSync] Strategy recorded for session {session_id}"
            )
            return True

        except (AttributeError, KeyError, TypeError, OSError, ValueError) as e:
            logger.error(f"[EvolutionSync] Strategy record failed: {e}")
            return False

    def get_evolution_status(self) -> Dict[str, Any]:
        """自動進化システムのステータスを取得

        trinity.py /evolution/status のバックエンドロジックを統合
        """
        evolution_log = self._load_evolution_log()

        decision_count = 0
        try:
            from decision_logger import decision_logger
            decision_count = decision_logger.get_stats().get("total_decisions", 0)
        except (ImportError, AttributeError, RuntimeError, KeyError, TypeError):
            pass

        strategy_count = len([
            entry for entry in evolution_log.get("entries", [])
            if entry.get("type") == "smartcut_strategy"
        ])

        return {
            "evolution_entries": len(evolution_log.get("entries", [])),
            "philosophies": len(evolution_log.get("philosophies", [])),
            "decision_count": decision_count,
            "last_sync": evolution_log.get("last_sync"),
            "smartcut_strategies": strategy_count,
        }

    def get_dashboard_data(self) -> Dict[str, Any]:
        """進化ダッシュボードデータを集約 (Sprint 4.2.3)

        設計書 §2.6: GET /api/evolution/dashboard のバックエンドロジック

        Returns:
            {
                "trigger_status": { "rules": [...] },
                "pending_proposals": [...],
                "trust_score": float,
                "trust_history": [...],
                "philosophy_timeline": [...],
                "trigger_history": [...],
                "evolution_entries_count": int,
                "philosophies_count": int,
            }
        """
        evolution_log = self._load_evolution_log()

        # 1. トリガーステータス取得
        trigger_status = self._get_trigger_status()

        # 2. 哲学提案一覧取得
        pending_proposals = self._get_pending_proposals()

        # 3. ログからデータを抽出
        trust_score = evolution_log.get("trust_score", 0.0)
        trust_history = evolution_log.get("trust_history", [])
        philosophy_timeline = evolution_log.get("philosophies", [])
        trigger_history = evolution_log.get("trigger_history", [])
        entries = evolution_log.get("entries", [])
        evolution_entries_count = len(entries)
        philosophies_count = len(philosophy_timeline)

        # 4. 未読通知 (M-01)
        notifications = self._get_unread_notifications(evolution_log)

        # 5. 監督プロファイル (M-02)
        director_profile = evolution_log.get("director_profile", {})

        return {
            # 既存フィールド（後方互換）
            "trigger_status": trigger_status,
            "pending_proposals": pending_proposals,
            "trust_score": trust_score,
            "trust_history": trust_history,
            "philosophy_timeline": philosophy_timeline,
            "trigger_history": trigger_history,
            "evolution_entries_count": evolution_entries_count,
            "philosophies_count": philosophies_count,
            # M-01: 通知
            "notifications": notifications,
            # M-02: 監督プロファイル
            "director_profile": director_profile,
            # M-04: O-12互換フィールド
            "evolution_entries": evolution_entries_count,  # O12-L2-05
            "entries": entries[-20:],                       # O12-L1-10
            "philosophies": philosophy_timeline,            # O12-L2-06
        }

    def _get_trigger_status(self) -> Dict[str, Any]:
        """トリガーステータス取得ヘルパー"""
        trigger_status = {"rules": []}
        with self._safe_execute("Trigger status"):
            from services.evolution_trigger_service import EvolutionTriggerService
            trigger_svc = EvolutionTriggerService(
                evolution_log_path=self._evolution_log_path
            )
            trigger_status = trigger_svc.get_trigger_status()
        return trigger_status

    def _get_pending_proposals(self) -> list:
        """哲学提案一覧取得ヘルパー"""
        pending_proposals = []
        with self._safe_execute("Proposal fetch"):
            from services.philosophy_proposal_service import PhilosophyProposalService
            proposal_svc = PhilosophyProposalService(
                evolution_log_path=self._evolution_log_path
            )
            proposals = proposal_svc.get_pending_proposals()
            pending_proposals = [
                {
                    "proposal_id": proposal.proposal_id,
                    "content": proposal.content,
                    "source_summary": proposal.source_summary,
                    "generated_at": proposal.generated_at,
                    "status": proposal.status,
                    "user_edit": proposal.user_edit,
                }
                for proposal in proposals
            ]
        return pending_proposals

    def _get_unread_notifications(self, evolution_log: Dict[str, Any]) -> list:
        """未読通知取得ヘルパー"""
        raw_notifications = evolution_log.get("notifications", [])
        if not isinstance(raw_notifications, list):
            raw_notifications = []
        return [
            notification for notification in raw_notifications
            if isinstance(notification, dict) and not notification.get("read", True)
        ]

    def _load_evolution_log(self) -> Dict:
        """evolution_log.jsonを読み込み (C-05: filelock)"""
        from utils.json_safe_io import safe_load_json
        try:
            data = safe_load_json(self._evolution_log_path)
            if data:
                return data
        except Exception as e:
            logger.warning(f"[EvolutionSync] evolution_log読込失敗: {e}")
        return {"entries": [], "philosophies": [], "decision_insights": []}

    def _save_evolution_log(self, data: Dict):
        """evolution_log.jsonに保存 (C-05: filelock)"""
        from utils.json_safe_io import safe_save_json
        data["last_sync"] = datetime.now().isoformat()
        safe_save_json(self._evolution_log_path, data)
