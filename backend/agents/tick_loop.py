"""
TickLoop — Claude Code KAIROS の Antigravity 移植版

Claude Code 流出コードから判明した「常駐型バックグラウンドエンジン」を実装。
ユーザーの指示を待つのではなく、自律的に「心拍（Tick）」を持ち、
適切なタイミングで能動的にアクションを実行する。

KAIROS の核心的な設計思想:
    - <tick> を自分自身に送信する自律的な鼓動
    - 15秒ブロッキング予算: バックグラウンド処理はユーザーを邪魔しない
    - SleepTool: 何もすることがなければ省電力待機
    - フォアグラウンド作業中は Tick を抑制

Antigravity 版の Tick アクション候補:
    - DreamEngine のトリガー判定・実行
    - usage_tracker のコスト警告
    - プロジェクトファイルの整合性チェック
    - 品質スコアのトレンド分析
    - 未使用アセットの検出
"""

try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path

import json
import logging
import asyncio
import time
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

# ============================================================
# 定数（Claude Code KAIROS 準拠）
# ============================================================
TICK_INTERVAL_SECONDS = 60          # 通常時: 1分ごと
SLEEP_INTERVAL_SECONDS = 300        # アイドル時: 5分ごと
BLOCKING_BUDGET_SECONDS = 15        # Claude Code 準拠: 15秒
MAX_CONSECUTIVE_IDLE = 10           # idle が10回続いたらスリープモード
TICK_LOG_DIR = Path(__file__).parent / "logs" / "tick_loop"


# ============================================================
# データ構造
# ============================================================

class TickActionType(Enum):
    """Tick で実行可能なアクション"""
    DREAM_CHECK = "dream_check"             # DreamEngine トリガー判定
    COST_MONITOR = "cost_monitor"           # API コスト監視
    FILE_INTEGRITY = "file_integrity"       # ファイル整合性チェック
    QUALITY_TREND = "quality_trend"         # 品質トレンド分析
    PIPELINE_KNOWLEDGE = "pipeline_knowledge"  # 制作ナレッジ学習
    TDR_RESOLVE = "tdr_resolve"             # 技術負債の自動解消
    IDLE = "idle"                           # 何もしない
    SLEEP = "sleep"                         # スリープモードに入る


@dataclass
class TickResult:
    """Tick 実行結果"""
    tick_id: int
    action: str
    timestamp: str
    duration_seconds: float
    result: Dict = field(default_factory=dict)
    alerts: List[str] = field(default_factory=list)


@dataclass
class TickLoopState:
    """TickLoop の状態"""
    is_running: bool = False
    is_sleeping: bool = False
    total_ticks: int = 0
    consecutive_idle: int = 0
    last_tick_at: Optional[str] = None
    last_action: Optional[str] = None
    started_at: Optional[str] = None
    alerts_sent: int = 0


# ============================================================
# メインクラス
# ============================================================

class TickLoop:
    """
    Claude Code KAIROS の Antigravity 移植版。

    Usage:
        loop = TickLoop()

        # FastAPI lifespan で起動
        async def lifespan(app):
            task = asyncio.create_task(loop.start())
            yield
            await loop.stop()

        # または手動 Tick
        result = await loop.tick()
    """

    def __init__(
        self,
        tick_interval: int = TICK_INTERVAL_SECONDS,
        sleep_interval: int = SLEEP_INTERVAL_SECONDS,
        blocking_budget: int = BLOCKING_BUDGET_SECONDS,
    ):
        self.tick_interval = tick_interval
        self.sleep_interval = sleep_interval
        self.blocking_budget = blocking_budget
        self.state = TickLoopState()
        self._task: Optional[asyncio.Task] = None
        self._stopped = asyncio.Event()
        self._foreground_active = False  # フォアグラウンド作業中フラグ

        # Tick アクションの登録
        self._actions: Dict[str, Callable[[], Awaitable[Dict]]] = {
            TickActionType.DREAM_CHECK.value: self._action_dream_check,
            TickActionType.COST_MONITOR.value: self._action_cost_monitor,
            TickActionType.FILE_INTEGRITY.value: self._action_file_integrity,
            TickActionType.QUALITY_TREND.value: self._action_quality_trend,
            TickActionType.PIPELINE_KNOWLEDGE.value: self._action_pipeline_knowledge,
            TickActionType.TDR_RESOLVE.value: self._action_tdr_resolve,
        }

    # ============================================================
    # ライフサイクル管理
    # ============================================================

    async def start(self):
        """TickLoop を開始"""
        if self.state.is_running:
            logger.warning("TickLoop は既に実行中です")
            return

        self.state.is_running = True
        self.state.started_at = datetime.now().isoformat()
        self._stopped.clear()

        logger.info(
            f"🫀 TickLoop 起動: interval={self.tick_interval}s, "
            f"budget={self.blocking_budget}s"
        )

        TICK_LOG_DIR.mkdir(parents=True, exist_ok=True)

        try:
            while not self._stopped.is_set():
                interval = (
                    self.sleep_interval
                    if self.state.is_sleeping
                    else self.tick_interval
                )

                try:
                    await asyncio.wait_for(
                        self._stopped.wait(), timeout=interval
                    )
                    break  # stopped が set された
                except asyncio.TimeoutError:
                    pass  # タイムアウト → Tick 実行

                await self._tick()

        except asyncio.CancelledError:
            pass
        finally:
            self.state.is_running = False
            logger.info("🫀 TickLoop 停止")

    async def stop(self):
        """TickLoop を停止"""
        self._stopped.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def set_foreground_active(self, active: bool):
        """フォアグラウンド作業中フラグの設定"""
        self._foreground_active = active

    # ============================================================
    # Tick 実行
    # ============================================================

    async def _tick(self) -> Optional[TickResult]:
        """
        1回の Tick を実行。

        Claude Code KAIROS の <tick> に相当:
        1. 「今、何かすべきか？」を判断
        2. 必要ならアクション実行（15秒予算内）
        3. 何もなければ idle カウントを増加
        """
        self.state.total_ticks += 1
        tick_id = self.state.total_ticks

        # フォアグラウンド作業中は抑制
        if self._foreground_active:
            logger.debug(f"🫀 Tick #{tick_id}: フォアグラウンド作業中 → スキップ")
            return None

        start_time = time.time()

        # アクション判定
        action = await self._should_act()

        if action == TickActionType.IDLE:
            self.state.consecutive_idle += 1

            # アイドルが続いたらスリープモードに移行
            if self.state.consecutive_idle >= MAX_CONSECUTIVE_IDLE:
                if not self.state.is_sleeping:
                    self.state.is_sleeping = True
                    logger.info(
                        f"😴 TickLoop スリープモード移行 "
                        f"(idle {self.state.consecutive_idle}回)"
                    )

            return TickResult(
                tick_id=tick_id,
                action="idle",
                timestamp=datetime.now().isoformat(),
                duration_seconds=0,
            )

        # スリープ解除
        if self.state.is_sleeping:
            self.state.is_sleeping = False
            logger.info("⏰ TickLoop スリープ解除")

        self.state.consecutive_idle = 0

        # アクション実行（15秒予算内）
        try:
            result = await asyncio.wait_for(
                self._execute_action(action),
                timeout=self.blocking_budget,
            )

            duration = time.time() - start_time
            self.state.last_tick_at = datetime.now().isoformat()
            self.state.last_action = action.value

            tick_result = TickResult(
                tick_id=tick_id,
                action=action.value,
                timestamp=datetime.now().isoformat(),
                duration_seconds=round(duration, 2),
                result=result.get("data", {}),
                alerts=result.get("alerts", []),
            )

            # アラートがある場合はログに出力
            for alert in tick_result.alerts:
                logger.warning(f"🔔 TickLoop Alert: {alert}")
                self.state.alerts_sent += 1

            return tick_result

        except asyncio.TimeoutError:
            logger.warning(
                f"⏱️ Tick #{tick_id}: ブロッキング予算超過 "
                f"({self.blocking_budget}s) → 強制中断"
            )
            return TickResult(
                tick_id=tick_id,
                action=action.value,
                timestamp=datetime.now().isoformat(),
                duration_seconds=self.blocking_budget,
                alerts=["ブロッキング予算超越で強制中断"],
            )

    # ============================================================
    # アクション判定
    # ============================================================

    async def _should_act(self) -> TickActionType:
        """
        今回の Tick で何をすべきか判断。

        優先順位（包含関係および優先順位順）:
        1. 品質トレンド（50 Tick ごと）
        2. DreamEngine チェック（20 Tick ごと ≒ 20分に1回）
        3. TDR_RESOLVE チェック（15 Tick ごと）
        4. ファイル整合性チェック（10 Tick ごと）
        5. コスト監視（5 Tick ごと ≒ 5分に1回）
        6. パイプラインナレッジ学習（7 Tick ごと ≒ 7分に1回）
        """
        tick_id = self.state.total_ticks

        # 1. 品質トレンド（50 Tick ごと）
        if tick_id % 50 == 0:
            return TickActionType.QUALITY_TREND

        # 2. DreamEngine チェック（20 Tick ごと ≒ 20分に1回）
        if tick_id % 20 == 0:
            try:
                from agents.dream_engine import dream_engine
                if await dream_engine.should_dream():
                    return TickActionType.DREAM_CHECK
            except (ImportError, Exception):
                pass

        # 3. TDR_RESOLVE チェック（15 Tick ごと）
        if tick_id % 15 == 0:
            return TickActionType.TDR_RESOLVE

        # 4. ファイル整合性チェック（10 Tick ごと）
        if tick_id % 10 == 0:
            return TickActionType.FILE_INTEGRITY

        # 5. コスト監視（5 Tick ごと ≒ 5分に1回）
        if tick_id % 5 == 0:
            return TickActionType.COST_MONITOR

        # 6. パイプラインナレッジ学習（7 Tick ごと ≒ 7分に1回）
        if tick_id % 7 == 0:
            knowledge_dir = _writable_path("backend/agents/logs/pipeline_knowledge")
            if knowledge_dir.exists() and list(knowledge_dir.glob("run_*.json")):
                return TickActionType.PIPELINE_KNOWLEDGE

        return TickActionType.IDLE

    # ============================================================
    # アクション実行
    # ============================================================

    async def _execute_action(self, action: TickActionType) -> Dict:
        """登録されたアクションを実行"""
        handler = self._actions.get(action.value)
        if handler:
            return await handler()
        return {"data": {}, "alerts": []}

    async def _action_dream_check(self) -> Dict:
        """DreamEngine のトリガー判定と実行"""
        alerts = []
        data = {}
        try:
            from agents.dream_engine import dream_engine
            if await dream_engine.should_dream():
                logger.info("🌙 TickLoop → DreamEngine 起動")
                result = await dream_engine.run_dream_cycle()
                data = {
                    "dream_success": result.success,
                    "new_facts": result.consolidation.new_facts if result.success else 0,
                    "duration": result.duration_seconds,
                }
                if result.success:
                    alerts.append(
                        f"🌙 Dream完了: {result.gather_count}シグナル処理, "
                        f"{result.consolidation.new_facts}件のVerified Facts追加"
                    )
        except (ImportError, Exception) as e:
            logger.warning(f"DreamEngine 実行失敗: {e}")
            data = {"error": str(e)}

        return {"data": data, "alerts": alerts}

    async def _action_cost_monitor(self) -> Dict:
        """API コスト監視"""
        alerts = []
        data = {}
        try:
            from usage_tracker.sdk_checker import get_usage_stats
            stats = get_usage_stats()
            data = stats

            # 残量が10%以下で警告
            if stats.get("remaining_pct", 100) < 10:
                alerts.append(
                    f"💰 API使用量警告: 残り{stats.get('remaining_pct', '?')}%"
                )
        except (ImportError, Exception):
            pass

        return {"data": data, "alerts": alerts}

    async def _action_file_integrity(self) -> Dict:
        """プロジェクトファイルの整合性チェック"""
        alerts = []
        data = {"checked_files": 0, "issues": []}

        critical_files = [
            Path(__file__).parent / "main.py",
            Path(__file__).parent / "antigravity_api.py",
            Path(__file__).parent / "model_config.json",
            Path(__file__).parent / "agents" / "council_graph.py",
            Path(__file__).parent / "agents" / "production_pipeline.py",
        ]

        for f in critical_files:
            data["checked_files"] += 1
            if not f.exists():
                issue = f"⚠️ 重要ファイル欠損: {f.name}"
                data["issues"].append(issue)
                alerts.append(issue)

        return {"data": data, "alerts": alerts}

    async def _action_quality_trend(self) -> Dict:
        """品質スコアのトレンド分析"""
        data = {}
        try:
            from agents.memory.verified_facts import verified_facts_store
            stats = verified_facts_store.get_stats()
            data = {
                "verified_facts": stats,
            }
        except (ImportError, Exception):
            pass

        return {"data": data, "alerts": []}

    async def _action_pipeline_knowledge(self) -> Dict:
        """提案3: パイプライン制作ナレッジを Verified Facts に変換"""
        alerts = []
        data = {"processed": 0, "new_facts": 0}

        knowledge_dir = _writable_path("backend/agents/logs/pipeline_knowledge")
        if not knowledge_dir.exists():
            return {"data": data, "alerts": alerts}

        processed_dir = knowledge_dir / "_processed"
        processed_dir.mkdir(parents=True, exist_ok=True)

        for knowledge_file in sorted(knowledge_dir.glob("run_*.json")):
            try:
                knowledge = json.loads(
                    knowledge_file.read_text(encoding="utf-8")
                )

                # Verified Facts に変換
                facts_added = 0
                try:
                    from agents.memory.verified_facts import verified_facts_store

                    video = knowledge.get("video", "unknown")
                    score = knowledge.get("quality_score", 0)
                    corrections = knowledge.get("total_corrections", 0)
                    retries = knowledge.get("retries_used", 0)

                    if score > 0:
                        verified_facts_store.add_fact(
                            category="lesson",
                            content=f"制作実績: {video} → 品質スコア{score}点",
                            evidence=f"ナレッジファイル {knowledge_file.name} より学習",
                            source="pipeline",
                        )
                        facts_added += 1

                    if corrections > 5:
                        verified_facts_store.add_fact(
                            category="lesson",
                            content=f"校閲傾向: {video} で{corrections}件の修正が必要だった",
                            evidence=f"ナレッジファイル {knowledge_file.name} より学習",
                            source="pipeline",
                        )
                        facts_added += 1

                    if retries > 0:
                        verified_facts_store.add_fact(
                            category="lesson",
                            content=f"障害記録: {video} で{retries}回のリトライが発生",
                            evidence=f"ナレッジファイル {knowledge_file.name} より学習",
                            source="pipeline",
                        )
                        facts_added += 1

                except (ImportError, Exception):
                    pass

                # 処理済みに移動
                shutil.move(str(knowledge_file), str(processed_dir / knowledge_file.name))

                data["processed"] += 1
                data["new_facts"] += facts_added

            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Knowledge processing failed due to format or I/O error: {e}")

        if data["processed"] > 0:
            alerts.append(
                f"📚 制作ナレッジ学習: {data['processed']}件処理, "
                f"{data['new_facts']}件のVerified Facts追加"
            )

        return {"data": data, "alerts": alerts}

    async def _action_tdr_resolve(self) -> Dict:
        """未解消の技術負債をスキャンし、解消されたものを自動的に fixed に更新する"""
        alerts = []
        data = {"resolved_count": 0, "resolved_ids": []}
        try:
            from agents.memory.technical_debt import technical_debt_store
            open_debts = technical_debt_store.get_open_entries()
            
            for debt in open_debts:
                # 該当ファイルが存在するか確認
                backend_path = Path(__file__).resolve().parent.parent
                file_path = backend_path / debt.file_path
                
                resolved = False
                reason = ""
                
                if not file_path.exists():
                    resolved = True
                    reason = f"ファイルが削除されたため解消: {debt.file_path}"
                else:
                    # ファイル内の指定パターンが含まれているか確認
                    try:
                        content = file_path.read_text(encoding="utf-8")
                        if debt.pattern not in content:
                            resolved = True
                            reason = f"コードからパターン '{debt.pattern}' が消滅したため解消"
                    except (OSError, UnicodeDecodeError):
                        pass
                
                if resolved:
                    technical_debt_store.resolve_debt(
                        debt_id=debt.debt_id,
                        fixed_by="tick_loop_tdr_resolve",
                        fix_evidence=reason
                    )
                    data["resolved_count"] += 1
                    data["resolved_ids"].append(debt.debt_id)
                    alerts.append(f"✅ 自動解消: {debt.debt_id} ({reason})")
                    
        except (ImportError, Exception) as e:
            logger.warning(f"TDR_RESOLVE アクション実行失敗: {e}")
            data["error"] = str(e)
            
        return {"data": data, "alerts": alerts}

    # ============================================================
    # ステータス
    # ============================================================

    def get_status(self) -> Dict:
        """TickLoop の現在の状態"""
        return {
            "is_running": self.state.is_running,
            "is_sleeping": self.state.is_sleeping,
            "total_ticks": self.state.total_ticks,
            "consecutive_idle": self.state.consecutive_idle,
            "last_tick_at": self.state.last_tick_at,
            "last_action": self.state.last_action,
            "started_at": self.state.started_at,
            "alerts_sent": self.state.alerts_sent,
            "foreground_active": self._foreground_active,
            "current_interval": (
                self.sleep_interval
                if self.state.is_sleeping
                else self.tick_interval
            ),
        }

    async def manual_tick(self) -> Optional[TickResult]:
        """手動で1回の Tick を実行（デバッグ用）"""
        return await self._tick()


# ============================================================
# シングルトンインスタンス
# ============================================================
tick_loop = TickLoop()


if __name__ == "__main__":  # pragma: no cover
    import argparse
    import sys
    
    # sys.path に backend ディレクトリを追加して、他のモジュールを正しくインポートできるようにする
    backend_path = Path(__file__).resolve().parent.parent
    if str(backend_path) not in sys.path:
        sys.path.insert(0, str(backend_path))
        
    parser = argparse.ArgumentParser(description="Antigravity TickLoop / Flash Heartbeat Runner")
    parser.add_argument("--mode", choices=["kairos", "flash"], default="kairos", help="実行モード")
    parser.add_argument("--session-id", default="default-session", help="セッションID")
    args = parser.parse_args()
    
    if args.mode == "flash":
        print(f"Starting Flash Heartbeat Process for session: {args.session_id}")
        
        # OrchestrationHub のインポート
        try:
            from agents.orchestration.orchestrator import OrchestrationHub
        except ImportError:
            sys.path.insert(0, str(backend_path.parent))
            from backend.agents.orchestration.orchestrator import OrchestrationHub
            
        hub = OrchestrationHub()
        
        # セッション開始（初回のみ）
        try:
            session = hub.get_flash_session()
            if not session or session.get("status") != "running":
                hub.flash_session_start(args.session_id)
                print(f"Started new flash session: {args.session_id}")
            else:
                print(f"Re-using active flash session: {session.get('session_id')}")
        except (ValueError, KeyError, OSError, RuntimeError) as e:
            print(f"Session init failed: {e}", file=sys.stderr)
            
        async def run_heartbeat_loop():
            print("Heartbeat loop started. Press Ctrl+C to exit.")
            while True:
                try:
                    session = hub.get_flash_session()
                    tasks_completed = session.get("tasks_completed_in_session", 0)
                    hub.flash_update_status(
                        activity="running",
                        step="Flash session heartbeat active",
                        progress_pct=100
                    )
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Heartbeat sent. Tasks completed: {tasks_completed}")
                except (ValueError, KeyError, OSError, RuntimeError) as e:
                    print(f"Error sending heartbeat: {e}", file=sys.stderr)
                await asyncio.sleep(300)  # 5分おき
                
        try:
            asyncio.run(run_heartbeat_loop())
        except KeyboardInterrupt:
            try:
                hub.flash_session_end("KeyboardInterrupt: ユーザーによる停止")
            except (ValueError, KeyError, OSError, RuntimeError):
                pass
            print("Heartbeat process stopped.")
    else:
        print("Starting KAIROS TickLoop...")
        try:
            asyncio.run(tick_loop.start())
        except KeyboardInterrupt:
            print("TickLoop stopped.")
