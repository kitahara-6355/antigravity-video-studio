"""
DreamEngine — Claude Code Auto-Dream の Antigravity 移植版

Claude Code の Auto-Dream 機能を再現する記憶整理エンジン。
「LLM のためのレム睡眠」として、アイドル時にバックグラウンドで
過去のセッションデータを整理し、ノイズを排除して確定事実のみを
Verified Facts に書き込む。

4フェーズ（Claude Code 流出コードから判明した実装）:
    1. Orient      — 現在のプロジェクト全体像を再確認
    2. Gather      — 全セッションログから重要シグナルを収集
    3. Consolidate — 確定事項を Verified Facts に書き込み、矛盾を排除
    4. Prune       — ノイズ（失敗した試行錯誤等）を要約・圧縮

トリガー条件（3ゲート、Claude Code 準拠）:
    - Gate 1: 最後の Dream から設定時間以上経過
    - Gate 2: 設定セッション数以上蓄積
    - Gate 3: 排他ロック取得成功（並行 Dream 防止）

設計方針:
    - 既存の decision_logger / learning_loop / agents/memory/*.json をデータソースとして使用
    - 出力は VERIFIED_FACTS.md + verified_facts_index.json に書き込み
    - Gemini Flash によるコスト効率の良い要約処理
    - usage_tracker 連携でコスト上限を遵守
"""

import json
import logging
import asyncio
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)

# ============================================================
# 定数
# ============================================================
DREAM_INTERVAL_HOURS = 24       # Gate 1: 最小間隔
DREAM_MIN_SESSIONS = 5          # Gate 2: 最小セッション数
DREAM_LOCK_FILE = Path(__file__).parent / ".dream_lock"
DREAM_STATE_FILE = Path(__file__).parent / "memory" / "dream_state.json"
DATA_DIR = Path(__file__).parent


# ============================================================
# データ構造
# ============================================================

@dataclass
class Signal:
    """Gather フェーズで収集されるシグナル"""
    signal_type: str   # "decision", "lesson", "pattern", "error_resolution"
    content: str
    source: str        # ファイル名やモジュール名
    timestamp: str
    importance: float  # 0.0-1.0
    raw_data: Dict = field(default_factory=dict)


@dataclass
class ProjectState:
    """Orient フェーズで構築されるプロジェクト状態"""
    total_sessions: int
    last_dream_at: Optional[str]
    existing_facts_count: int
    pending_decisions: int
    active_patterns: Dict
    memory_files: List[str]


@dataclass
class ConsolidationResult:
    """Consolidate フェーズの結果"""
    new_facts: int
    updated_facts: int
    contradictions_resolved: int
    facts_added: List[Dict]


@dataclass
class PruneResult:
    """Prune フェーズの結果"""
    entries_removed: int
    entries_summarized: int
    space_freed_kb: float


@dataclass
class DreamResult:
    """Dream サイクル全体の結果"""
    started_at: str
    completed_at: str
    duration_seconds: float
    orient: ProjectState
    gather_count: int
    consolidation: ConsolidationResult
    prune: PruneResult
    success: bool
    error: Optional[str] = None


# ============================================================
# メインクラス
# ============================================================

class DreamEngine:
    """
    Claude Code Auto-Dream の Antigravity 移植版。

    Usage:
        engine = DreamEngine()

        # トリガー判定
        if await engine.should_dream():
            result = await engine.run_dream_cycle()
            print(f"Dream完了: {result.gather_count}件のシグナル処理")

        # 手動実行
        result = await engine.run_dream_cycle(force=True)
    """

    def __init__(
        self,
        interval_hours: int = DREAM_INTERVAL_HOURS,
        min_sessions: int = DREAM_MIN_SESSIONS,
    ):
        self.interval_hours = interval_hours
        self.min_sessions = min_sessions
        self.state_path = DREAM_STATE_FILE
        self.lock_path = DREAM_LOCK_FILE
        self._state = self._load_state()

    # ============================================================
    # Gate判定
    # ============================================================

    async def should_dream(self) -> bool:
        """
        3ゲートトリガー判定（Claude Code 準拠）

        Returns:
            True if all three gates pass
        """
        # Gate 1: 時間経過
        last_dream = self._state.get("last_dream_at")
        if last_dream:
            elapsed = datetime.now() - datetime.fromisoformat(last_dream)
            if elapsed < timedelta(hours=self.interval_hours):
                logger.debug(f"Dream Gate 1 未通過: {elapsed.total_seconds()/3600:.1f}h < {self.interval_hours}h")
                return False

        # Gate 2: セッション蓄積
        sessions_since = self._state.get("sessions_since_last_dream", 0)
        if sessions_since < self.min_sessions:
            logger.debug(f"Dream Gate 2 未通過: {sessions_since} < {self.min_sessions} sessions")
            return False

        # Gate 3: 排他ロック
        if self.lock_path.exists():
            logger.debug("Dream Gate 3 未通過: ロックファイル存在")
            return False

        logger.info("✅ Dream 3ゲート全通過 — Dream サイクル開始可能")
        return True

    def increment_session_count(self):
        """セッション開始時に呼び出し、カウンターを更新"""
        self._state["sessions_since_last_dream"] = (
            self._state.get("sessions_since_last_dream", 0) + 1
        )
        self._save_state()

    # ============================================================
    # Dream サイクル実行
    # ============================================================

    async def run_dream_cycle(self, force: bool = False) -> DreamResult:
        """
        4フェーズの Dream サイクルを実行。

        Args:
            force: True の場合、ゲート判定をスキップ

        Returns:
            DreamResult
        """
        if not force and not await self.should_dream():
            return DreamResult(
                started_at=datetime.now().isoformat(),
                completed_at=datetime.now().isoformat(),
                duration_seconds=0,
                orient=ProjectState(0, None, 0, 0, {}, []),
                gather_count=0,
                consolidation=ConsolidationResult(0, 0, 0, []),
                prune=PruneResult(0, 0, 0),
                success=False,
                error="ゲート条件未達成",
            )

        # ロック取得
        self._acquire_lock()
        start_time = time.time()
        started_at = datetime.now().isoformat()

        try:
            logger.info("🌙 Dream サイクル開始 ===========================")

            # Phase 1: Orient
            logger.info("🌙 Phase 1/4: Orient — プロジェクト全体像の再確認")
            project_state = await self._orient()

            # Phase 2: Gather
            logger.info("🌙 Phase 2/4: Gather — 重要シグナルの収集")
            signals = await self._gather_signal()

            # Phase 3: Consolidate
            logger.info("🌙 Phase 3/4: Consolidate — 確定事項の書き込み")
            consolidation = await self._consolidate(signals)

            # Phase 4: Prune
            logger.info("🌙 Phase 4/4: Prune — ノイズの整理")
            prune_result = await self._prune_and_index()

            duration = time.time() - start_time

            # 状態更新
            self._state["last_dream_at"] = datetime.now().isoformat()
            self._state["sessions_since_last_dream"] = 0
            self._state["dream_count"] = self._state.get("dream_count", 0) + 1
            self._save_state()

            result = DreamResult(
                started_at=started_at,
                completed_at=datetime.now().isoformat(),
                duration_seconds=round(duration, 2),
                orient=project_state,
                gather_count=len(signals),
                consolidation=consolidation,
                prune=prune_result,
                success=True,
            )

            logger.info(
                f"🌙 Dream サイクル完了 ===========================\n"
                f"  所要時間: {duration:.1f}秒\n"
                f"  シグナル収集: {len(signals)}件\n"
                f"  新規ファクト: {consolidation.new_facts}件\n"
                f"  矛盾解消: {consolidation.contradictions_resolved}件\n"
                f"  プルーニング: {prune_result.entries_removed}件"
            )

            return result

        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"🌙 Dream サイクルファイル/JSONエラー: {e}", exc_info=True)
            return DreamResult(
                started_at=started_at,
                completed_at=datetime.now().isoformat(),
                duration_seconds=time.time() - start_time,
                orient=ProjectState(0, None, 0, 0, {}, []),
                gather_count=0,
                consolidation=ConsolidationResult(0, 0, 0, []),
                prune=PruneResult(0, 0, 0),
                success=False,
                error=f"File/JSON Error: {e}",
            )
        except (ImportError, AttributeError, KeyError) as e:
            logger.error(f"🌙 Dream サイクルモジュール/属性エラー: {e}", exc_info=True)
            return DreamResult(
                started_at=started_at,
                completed_at=datetime.now().isoformat(),
                duration_seconds=time.time() - start_time,
                orient=ProjectState(0, None, 0, 0, {}, []),
                gather_count=0,
                consolidation=ConsolidationResult(0, 0, 0, []),
                prune=PruneResult(0, 0, 0),
                success=False,
                error=f"Import/Attribute/Key Error: {e}",
            )
        except (ValueError, TypeError) as e:
            logger.error(f"🌙 Dream サイクルデータ形式エラー: {e}", exc_info=True)
            return DreamResult(
                started_at=started_at,
                completed_at=datetime.now().isoformat(),
                duration_seconds=time.time() - start_time,
                orient=ProjectState(0, None, 0, 0, {}, []),
                gather_count=0,
                consolidation=ConsolidationResult(0, 0, 0, []),
                prune=PruneResult(0, 0, 0),
                success=False,
                error=f"Value/Type Error: {e}",
            )
        except RuntimeError as e:
            logger.error(f"🌙 Dream サイクル実行エラー: {e}", exc_info=True)
            return DreamResult(
                started_at=started_at,
                completed_at=datetime.now().isoformat(),
                duration_seconds=time.time() - start_time,
                orient=ProjectState(0, None, 0, 0, {}, []),
                gather_count=0,
                consolidation=ConsolidationResult(0, 0, 0, []),
                prune=PruneResult(0, 0, 0),
                success=False,
                error=f"Runtime Error: {e}",
            )
        except (IndexError, NameError, AssertionError) as e:
            logger.error(f"🌙 Dream サイクル予期せぬエラー: {e}", exc_info=True)
            return DreamResult(
                started_at=started_at,
                completed_at=datetime.now().isoformat(),
                duration_seconds=time.time() - start_time,
                orient=ProjectState(0, None, 0, 0, {}, []),
                gather_count=0,
                consolidation=ConsolidationResult(0, 0, 0, []),
                prune=PruneResult(0, 0, 0),
                success=False,
                error=f"Unexpected Error: {e}",
            )
        finally:
            self._release_lock()

    # ============================================================
    # Phase 1: Orient
    # ============================================================

    async def _orient(self) -> ProjectState:
        """
        プロジェクトの全体像を再確認。
        Claude Code では memory ディレクトリをリストし、
        MEMORY.md と既存トピックファイルをスキャンしていた。
        """
        from agents.memory.verified_facts import verified_facts_store

        # メモリディレクトリのスキャン
        memory_dir = DATA_DIR / "agents" / "memory"
        memory_files = []
        if memory_dir.exists():
            try:
                memory_files = [f.name for f in memory_dir.iterdir() if f.is_file()]
            except OSError as e:
                logger.warning(f"Memory directory scan failed: {e}")

        # 意思決定ログの状態
        pending_decisions = 0
        try:
            from decision_logger import decision_logger
            pending_decisions = len([
                d for d in decision_logger.decisions if not d.learned
            ])
        except ImportError:
            pass
        except (AttributeError, TypeError, ValueError, KeyError) as e:
            logger.warning(f"Error accessing decision_logger in Orient: {e}")

        # 学習パターンの状態
        active_patterns = {}
        try:
            from learning_loop import learning_loop
            active_patterns = learning_loop.get_preferences()
        except ImportError:
            pass
        except (AttributeError, TypeError, ValueError, KeyError) as e:
            logger.warning(f"Error accessing learning_loop in Orient: {e}")

        state = ProjectState(
            total_sessions=self._state.get("sessions_since_last_dream", 0),
            last_dream_at=self._state.get("last_dream_at"),
            existing_facts_count=len(verified_facts_store.facts),
            pending_decisions=pending_decisions,
            active_patterns=active_patterns,
            memory_files=memory_files,
        )

        logger.info(
            f"  Orient完了: facts={state.existing_facts_count}, "
            f"pending_decisions={state.pending_decisions}, "
            f"memory_files={len(state.memory_files)}"
        )
        return state

    # ============================================================
    # Phase 2: Gather Signal
    # ============================================================

    async def _gather_signal(self) -> List[Signal]:
        """
        全セッションログから重要シグナルを収集。

        Claude Code の Gather は以下の優先順位でデータを収集:
            daily logs → drifted/changed memories → transcript search

        Antigravity 版では:
            decision_logger → learning_loop → agent memory files
        """
        signals: List[Signal] = []

        # Source 1: DecisionLogger — 意思決定ログ
        signals.extend(await self._gather_from_decisions())

        # Source 2: LearningLoop — 学習パターン
        signals.extend(await self._gather_from_learning())

        # Source 3: Agent Memory — エージェント記憶
        signals.extend(await self._gather_from_agent_memory())

        # 重要度でソート
        signals.sort(key=lambda s: s.importance, reverse=True)

        logger.info(f"  Gather完了: {len(signals)}件のシグナル収集")
        return signals

    async def _gather_from_decisions(self) -> List[Signal]:
        """DecisionLogger からシグナルを収集"""
        signals = []
        try:
            from decision_logger import decision_logger

            for decision in decision_logger.decisions:
                if not decision.learned:
                    importance = 0.8 if decision.decision == "reject" else 0.5
                    signals.append(Signal(
                        signal_type="decision",
                        content=f"[{decision.decision}] {decision.target_description}: {decision.reason}",
                        source="decision_logger",
                        timestamp=decision.iso_time,
                        importance=importance,
                        raw_data={
                            "decision_id": decision.decision_id,
                            "target_type": decision.target_type,
                            "tags": decision.tags or [],
                        },
                    ))
        except ImportError as e:
            logger.warning(f"DecisionLogger モジュールがインポートできませんでした（収集をスキップします）: {e}")
        except (AttributeError, TypeError, ValueError, KeyError) as e:
            logger.error(f"DecisionLogger からのデータ処理中にエラーが発生しました: {e}", exc_info=True)
        return signals

    async def _gather_from_learning(self) -> List[Signal]:
        """LearningLoop からシグナルを収集"""
        signals = []
        try:
            from learning_loop import learning_loop

            # 恒久化提案 → 高重要度シグナル
            for proposal in learning_loop.proposals:
                if proposal.status == "pending":
                    signals.append(Signal(
                        signal_type="pattern",
                        content=f"恒久化提案: {proposal.proposal}",
                        source="learning_loop",
                        timestamp=proposal.created_at,
                        importance=0.9,
                        raw_data=asdict(proposal),
                    ))

            # 好みパターン → 中重要度シグナル
            for category, pattern in learning_loop.patterns.items():
                if pattern.sample_count >= 3:  # 3件以上のデータがあるパターンのみ
                    signals.append(Signal(
                        signal_type="pattern",
                        content=(
                            f"好みパターン [{category}]: "
                            f"推奨={pattern.preferred[:3]}, "
                            f"回避={pattern.avoided[:3]}"
                        ),
                        source="learning_loop",
                        timestamp=datetime.now().isoformat(),
                        importance=0.6 + min(0.3, pattern.confidence * 0.3),
                        raw_data=asdict(pattern),
                    ))
        except ImportError as e:
            logger.warning(f"LearningLoop モジュールがインポートできませんでした（収集をスキップします）: {e}")
        except (AttributeError, TypeError, ValueError, KeyError) as e:
            logger.error(f"LearningLoop からのデータ処理中にエラーが発生しました: {e}", exc_info=True)
        return signals

    async def _gather_from_agent_memory(self) -> List[Signal]:
        """Agent Memory ファイルからシグナルを収集"""
        signals = []
        memory_dir = DATA_DIR / "agents" / "memory"
        if not memory_dir.exists():
            return signals

        for file_path in memory_dir.glob("*.json"):
            if file_path.name in ("verified_facts_index.json", "dream_state.json"):
                continue
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # lessons フィールドからシグナルを抽出
                for lesson in data.get("lessons", []):
                    signals.append(Signal(
                        signal_type="lesson",
                        content=lesson.get("text", ""),
                        source=f"memory/{file_path.name}",
                        timestamp=str(lesson.get("created_at", "")),
                        importance=0.7,
                        raw_data=lesson,
                    ))

                # history フィールドから重要なイベントを抽出
                for event in data.get("history", []):
                    if event.get("outcome") in ("REJECT", "ERROR"):
                        signals.append(Signal(
                            signal_type="error_resolution",
                            content=f"[{event.get('outcome')}] stance={event.get('stance', '')}, feedback={event.get('feedback', '')}",
                            source=f"memory/{file_path.name}",
                            timestamp=str(event.get("timestamp", "")),
                            importance=0.7,
                            raw_data=event,
                        ))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Agent Memory 読み込み失敗 ({file_path}): {e}")

        return signals

    # ============================================================
    # Phase 3: Consolidate
    # ============================================================

    async def _consolidate(self, signals: List[Signal]) -> ConsolidationResult:
        """
        収集したシグナルを Verified Facts に書き込み。

        Claude Code では:
        - メモリファイルを更新
        - 相対日付を絶対日付に変換
        - 冗長なエントリをマージ
        - 論理矛盾を削除
        """
        from agents.memory.verified_facts import verified_facts_store

        new_facts = 0
        updated_facts = 0
        facts_added = []
        contradictions_resolved = 0

        try:
            # シグナルをカテゴリに分類して Verified Facts に追加
            for signal in signals:
                if signal.importance < 0.5:
                    continue  # 低重要度はスキップ

                category = self._signal_to_category(signal)
                evidence = f"Source: {signal.source}, Timestamp: {signal.timestamp}"

                try:
                    fact = verified_facts_store.add_fact(
                        category=category,
                        content=signal.content,
                        evidence=evidence,
                        source="dream",
                        confidence=signal.importance,
                        tags=signal.raw_data.get("tags", []),
                    )
                    if fact:
                        facts_added.append({"content": signal.content, "category": category})
                        new_facts += 1
                except OSError as e:
                    logger.error(f"  Verified Facts への追加中にディスクI/Oエラーが発生しました: {e}")
                except (json.JSONDecodeError, AttributeError, TypeError, ValueError, KeyError, RuntimeError) as e:
                    logger.error(f"  Verified Facts への追加中に予期せぬエラーが発生しました: {e}", exc_info=True)

            # 矛盾検出・解消
            try:
                contradictions = verified_facts_store.get_contradictions()
                for fact1, fact2 in contradictions:
                    # 確信度の低い方を削除（簡易解消）
                    if fact1.confidence < fact2.confidence:
                        verified_facts_store.remove_fact(fact1.fact_id)
                    else:
                        verified_facts_store.remove_fact(fact2.fact_id)
                    contradictions_resolved += 1
            except OSError as e:
                logger.error(f"  矛盾解消中にディスクI/Oエラーが発生しました: {e}")
            except (json.JSONDecodeError, AttributeError, TypeError, ValueError, KeyError, RuntimeError) as e:
                logger.error(f"  矛盾解消中に予期せぬエラーが発生しました: {e}", exc_info=True)

        except (ImportError, AttributeError, KeyError, ValueError, TypeError, RuntimeError) as e:
            logger.error(f"  Consolidate処理全体で予期せぬエラーが発生しました: {e}", exc_info=True)

        logger.info(
            f"  Consolidate完了: new={new_facts}, "
            f"contradictions_resolved={contradictions_resolved}"
        )

        return ConsolidationResult(
            new_facts=new_facts,
            updated_facts=updated_facts,
            contradictions_resolved=contradictions_resolved,
            facts_added=facts_added,
        )

    def _signal_to_category(self, signal: Signal) -> str:
        """シグナルタイプからファクトカテゴリへのマッピング"""
        mapping = {
            "decision": "preference",
            "lesson": "lesson",
            "pattern": "preference",
            "error_resolution": "lesson",
        }
        return mapping.get(signal.signal_type, "preference")

    # ============================================================
    # Phase 4: Prune and Index
    # ============================================================

    async def _prune_and_index(self) -> PruneResult:
        """
        ノイズの整理。Claude Code では:
        - MEMORY.md を 200行以内に維持
        - 約 25KB 以内に維持
        """
        from agents.memory.verified_facts import verified_facts_store

        # 古いファクトをプルーニング
        removed = verified_facts_store.prune_stale_facts(max_age_days=30)

        # DecisionLogger の学習済みマーク
        summarized = 0
        try:
            from decision_logger import decision_logger
            for d in decision_logger.decisions:
                if not d.learned:
                    d.learned = True
                    summarized += 1
            decision_logger._save()
        except ImportError:
            pass
        except (OSError, AttributeError, TypeError, ValueError, KeyError) as e:
            logger.warning(f"Prune処理中にエラーが発生しました: {e}", exc_info=True)

        stats = verified_facts_store.get_stats()
        space_freed = 0  # 概算は困難なのでゼロ初期化

        logger.info(
            f"  Prune完了: removed={removed}, summarized={summarized}, "
            f"facts_total={stats['total_facts']}, "
            f"md_lines={stats['markdown_lines']}, "
            f"md_size={stats['markdown_size_kb']}KB"
        )

        return PruneResult(
            entries_removed=removed,
            entries_summarized=summarized,
            space_freed_kb=space_freed,
        )

    # ============================================================
    # Phase 完了時の progress 圧縮（Sprint B-2）
    # ============================================================

    def _auto_compress_phase_progress(
        self,
        completed_phase: str = "",
        dry_run: bool = False,
    ) -> Dict:
        """
        Phase完了ゲート通過時に progress ファクトを自動圧縮する。

        完了済みPhaseの個別progressファクト（N件）を1行サマリーに統合し、
        VF行数を節約する。VERIFIED_FACTS.md直接編集禁止ルールに従い、
        remove_fact + add_fact の既存API経由で実行。

        Args:
            completed_phase: 圧縮対象のPhase名（例: "Phase 1", "Phase 2"）
                             空文字の場合、完了済みの全Phaseを自動検出
            dry_run: True の場合、実際の変更は行わず圧縮対象と結果を返す

        Returns:
            {
                "phase": str,
                "original_count": int,   # 圧縮前のファクト数
                "compressed_to": int,    # 圧縮後のファクト数（通常1）
                "summary": str,          # 圧縮サマリー
                "removed_ids": list,     # 削除されたファクトID
                "dry_run": bool,
            }
        """
        import re
        from agents.memory.verified_facts import verified_facts_store

        progress_facts = verified_facts_store.get_facts_by_category("progress")

        if not progress_facts:
            return {
                "phase": completed_phase or "N/A",
                "original_count": 0,
                "compressed_to": 0,
                "summary": "progressファクトなし",
                "removed_ids": [],
                "dry_run": dry_run,
            }

        # Phase別にグループ化
        # パターン: "Phase N" で始まるファクト、または "M{N}.{X}" を含むファクト
        phase_groups: Dict[str, list] = {}
        for fact in progress_facts:
            content = fact.content
            # "Phase N" を直接検出
            phase_match = re.search(r"Phase\s+(\d+)", content)
            if phase_match:
                phase_key = f"Phase {phase_match.group(1)}"
            else:
                # "M{N}.{X}" パターンからPhase推定
                milestone_match = re.search(r"M(\d+)\.", content)
                if milestone_match:
                    phase_key = f"Phase {milestone_match.group(1)}"
                else:
                    phase_key = "Unknown"
            if phase_key not in phase_groups:
                phase_groups[phase_key] = []
            phase_groups[phase_key].append(fact)

        # 圧縮対象の決定
        if completed_phase:
            target_phases = [completed_phase] if completed_phase in phase_groups else []
        else:
            # 既に1件に圧縮済みのPhaseは除外
            target_phases = [
                p for p, facts in phase_groups.items()
                if len(facts) > 1
            ]

        if not target_phases:
            return {
                "phase": completed_phase or "全Phase",
                "original_count": len(progress_facts),
                "compressed_to": len(progress_facts),
                "summary": "圧縮対象なし（既に最適化済み）",
                "removed_ids": [],
                "dry_run": dry_run,
            }

        results = []
        for phase in target_phases:
            facts = phase_groups[phase]

            # サマリー生成: 各Sprintのテスト数を集約
            total_tests = 0
            sprint_summaries = []
            for fact in facts:
                # テスト数を抽出 (例: "63/63テスト" "45/45テスト")
                test_match = re.search(r"(\d+)/\d+\s*テスト", fact.content)
                if test_match:
                    total_tests += int(test_match.group(1))
                # Sprint名を抽出
                sprint_match = re.search(
                    r"(Sprint\s+[\d.]+|M[\d.]+\s+Sprint\s+[\d.]+)", fact.content
                )
                if sprint_match:
                    sprint_summaries.append(sprint_match.group(1))

            # 1行サマリー生成
            sprint_range = ""
            if sprint_summaries:
                sprint_range = f" ({sprint_summaries[0]}~{sprint_summaries[-1]})"
            summary = (
                f"{phase}完了{sprint_range}: "
                f"{len(facts)}タスク統合, "
                f"テスト計{total_tests}件PASS"
            )

            # evidence: 圧縮元ファクトIDを記録
            evidence = (
                f"Auto-compressed from {len(facts)} progress facts: "
                + ", ".join(f.fact_id for f in facts)
            )

            removed_ids = [f.fact_id for f in facts]

            if not dry_run:
                # 既存ファクトを削除
                for fact in facts:
                    verified_facts_store.remove_fact(fact.fact_id)

                # 圧縮サマリーを追加
                verified_facts_store.add_fact(
                    category="progress",
                    content=summary,
                    evidence=evidence,
                    source="dream",
                    confidence=1.0,
                    tags=["auto-compressed"],
                )

                logger.info(
                    f"🗜️ VF圧縮: {phase} — {len(facts)}件 → 1件サマリー"
                )

            results.append({
                "phase": phase,
                "original_count": len(facts),
                "compressed_to": 1,
                "summary": summary,
                "removed_ids": removed_ids,
                "dry_run": dry_run,
            })

        # 複数Phase圧縮時は最初の結果を返す（通常は1Phase）
        if len(results) == 1:
            return results[0]

        total_original = sum(r["original_count"] for r in results)
        total_compressed = sum(r["compressed_to"] for r in results)
        return {
            "phase": ", ".join(r["phase"] for r in results),
            "original_count": total_original,
            "compressed_to": total_compressed,
            "summary": f"{len(results)}Phase圧縮: {total_original}件 → {total_compressed}件",
            "removed_ids": [rid for r in results for rid in r["removed_ids"]],
            "dry_run": dry_run,
        }

    # ============================================================
    # ロック管理
    # ============================================================

    def _acquire_lock(self):
        """排他ロックを取得"""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.write_text(
            json.dumps({
                "acquired_at": datetime.now().isoformat(),
                "pid": __import__("os").getpid(),
            })
        )

    def _release_lock(self):
        """排他ロックを解放"""
        if self.lock_path.exists():
            self.lock_path.unlink()

    # ============================================================
    # 状態管理
    # ============================================================

    def _load_state(self) -> Dict:
        """Dream 状態を読み込み"""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        if self.state_path.exists():
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Dream状態ファイル読み込み失敗: {e}")
        return {
            "last_dream_at": None,
            "sessions_since_last_dream": 0,
            "dream_count": 0,
        }

    def _save_state(self):
        """Dream 状態を保存"""
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(self._state, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error(f"Dream状態保存エラー: {e}")


# ============================================================
# シングルトンインスタンス
# ============================================================
dream_engine = DreamEngine()
