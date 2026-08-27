"""
PipelineCoordinator — Coordinator-Worker パターン（Harness統合済み）

パイプライン制御の唯一の実行パス。
Anthropic推奨の設計パターンを適用:
  - Prompt Chaining: Worker順次実行 + ゲートチェック
  - Guardrails: Pre/Post Hook による自動ガードレール
  - Evaluator-Optimizer: 品質ゲート改善ループ

設計思想:
  - 各 Worker は単一責務（1ステージ = 1 Worker）
  - Worker 実装は agents/workers/ に分離（Sprint D）
  - 後方互換: 全 Worker クラスを re-export
  - Harness (Hook/Governance/Session) をグレースフルに統合
  - Harness が利用不可でもミドルウェアなしで正常動作
  - TaskContract (DoD) による成功条件検証
  - SelfHealingTool による自動リトライ
  - WebSocket によるリアルタイム進捗通知
  - パイプライン完了時に DreamEngine への学習フック
"""
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path



import os
import json
import logging
import asyncio
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Callable, Any
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)


# ============================================================
# データ構造 — pipeline_types.py に分離（Sprint B-1）
# 後方互換: 既存の40+箇所の import を変更不要にするため re-export
# ============================================================

from agents.pipeline_types import (  # noqa: F401 — re-export
    Segment,
    StageResult,
    PipelineContext,
    PipelineStageWorker,
)


# ============================================================
# 7つの Worker 実装 — agents/workers/ に分離（Sprint D）
# 後方互換: 既存の40+箇所の import を変更不要にするため re-export
# ============================================================

from agents.workers import (  # noqa: F401 — re-export
    TranscribeWorker,
    ProofreadWorker,
    SmartCutWorker,
    PreviewWorker,
    QualityGateWorker,
    RenderWorker,
    YouTubeOptWorker,
)

from backend.revenue.run_record import RunRecorder


# ============================================================
# 実行記録（R1.5-C1）
# ============================================================
#
# **R1 で硬化したのは2つあるパイプラインの片方だった。** 本線はこちらなので、
# R1 の保証（工程ごとの記録・モデルの見える化・失敗を握り潰さない）をここへ移す。

class _StageFailed(RuntimeError):
    """worker の `success=False` を `RunRecorder.stage` へ伝えるための内部例外。

    worker は例外ではなく `StageResult` で失敗を返す。記録側は例外で失敗を
    検知するので、境界でここに変換する。**外へは漏らさない。**
    """


# 工程名（記録に残る安定した名前）と、**モデルの出どころ**。
# 段（tier）に紐づけるのが正で、モデル名の直書きはしない — 直書きだと
# 入替のたびに全工程を書き換えることになる。
STAGE_RECORD: Dict[str, tuple] = {
    "TranscribeWorker": ("transcribe", {"model": "local:whisper"}),
    "ProofreadWorker": ("proofread", {"task": "proofreader"}),
    "SmartCutWorker": ("smart_cut", {"model": "local:auto-editor"}),
    "PreviewWorker": ("preview", {"model": "local:ffmpeg"}),
    "YouTubeOptWorker": ("youtube_opt", {"task": "youtube_optimization"}),
    # **品質ゲートは規則ベース。** 減点式のプラグイン群で、LLM は下位の
    # `AIRuleCheck` プラグイン（`quality_gate_ai`）が呼ぶ任意経路にしかない。
    # `task_mapping` の `quality_gate: premium` はその下位経路のための宣言で、
    # 工程そのものの宣言ではない。ここを premium と書くと、
    # **一度も API を呼んでいないのに「3.7-flash で判定した」と記録に残る**
    # （成果物ゲートが `model_unverified` で落とす）。
    # AI が実際に効くようにするのは R1.5-C3 の担当。
    "QualityGateWorker": ("quality_gate", {"model": "local:rule-based"}),
    "RenderWorker": ("render", {"model": "local:ffmpeg"}),
}

# **これが落ちたら成果物が無い。** 続けても意味が無いので中断する。
FATAL_WORKERS = {"TranscribeWorker", "SmartCutWorker", "RenderWorker"}
FATAL_STAGES = {STAGE_RECORD[w][0] for w in FATAL_WORKERS}

# 落ちても**動画は作れる**工程。中断はしないが、**完走とも呼ばない**。
# 結果は `degraded` になり、落ちた工程は `health.skipped_features` に出る。
# （プレビューの継続は T-020b の既存決定。ここではその範囲を広げただけ）
#
# **旧実装はここを全部「completed」と言っていた。** 最終レンダリングが落ちても
# 完了扱いで、テストにもそう書いてあった（C9-01）。動画が無いのに成功と
# 言うのが「偽の success」そのものなので、R1.5-C1 で作り直した。
STATUS_COMPLETED = "completed"
STATUS_DEGRADED = "degraded"


# ============================================================
# Coordinator（司令塔）
# ============================================================

class PipelineCoordinator:
    """
    Coordinator-Worker パターンのメインコントローラ。

    責務:
    1. Worker を順次実行
    2. TaskContract (DoD) で結果検証
    3. 失敗時は SelfHealing リトライ
    4. WebSocket でリアルタイム進捗通知
    5. 完了後に DreamEngine 学習フック起動
    """

    MAX_RETRIES = 2
    MAX_QUALITY_RETRIES = 3  # U-03: 品質ゲート自動改善ループ

    def __init__(self):
        self.workers: List[PipelineStageWorker] = [
            TranscribeWorker(),
            ProofreadWorker(),
            SmartCutWorker(),
            PreviewWorker(),
            YouTubeOptWorker(),     # メタデータ生成を品質チェックの前に
            QualityGateWorker(),    # 全データ揃った状態で品質評価
            RenderWorker(),         # 品質合格後に本番レンダリング
        ]
        self._progress_callback: Optional[Callable] = None
        self._ws_broadcast: Optional[Callable] = None

        # 実行記録（R1.5-C1）。`runs_dir` を差し替えればテストは本番を汚さない。
        self.runs_dir: Optional[Path] = None
        self.ledger_path: Optional[Path] = None
        self._recorder: Optional[RunRecorder] = None
        # 工程名 → 最後の試行が通ったか。**リトライで通ったものは失敗にしない**
        self._outcomes: Dict[str, bool] = {}

    # --- 実行記録 -----------------------------------------------------------

    def _stage_args(self, worker: PipelineStageWorker,
                    ctx: PipelineContext) -> tuple:
        """記録に残す工程名と、モデルの出どころ、再開に要る入力。"""
        name, source = STAGE_RECORD.get(
            type(worker).__name__, (type(worker).__name__, {}))
        return name, {
            **source,
            "stage_input": {
                "video_path": ctx.video_path,
                "session_id": ctx.session_id,
                "target_minutes": ctx.target_minutes,
                "template_id": ctx.template_id,
                "render_mode": ctx.render_mode,
                "segments": len(ctx.segments or []),
                "selected_segments": len(ctx.selected_segments or []),
                "preview_path": ctx.preview_path,
                "final_path": ctx.final_path,
            },
        }

    def _stage_name(self, worker: PipelineStageWorker) -> str:
        return STAGE_RECORD.get(
            type(worker).__name__, (type(worker).__name__, {}))[0]

    def _record_outcome(self, worker: PipelineStageWorker, ok: bool) -> None:
        """**最後の試行が答え。**

        リトライで通ったものを失敗として数えない。品質改善ループのように
        同じ工程を何度も回す経路もあるので、上書きで最後の結果を残す
        （記録そのものは1試行ずつ全部残る）。
        """
        self._outcomes[self._stage_name(worker)] = ok

    def _record_dead_stage(self, worker: PipelineStageWorker,
                           ctx: PipelineContext, reason: str) -> None:
        """**動かなかった工程も記録に1件残す**（R1.5-C1b）。

        事前フックが断った・落ちたときは `_execute_worker` に入らないので、
        記録には何も残らなかった。**`status: failed` なのに落ちた工程が
        ゼロ**という記録ができ、`run_record --resume` が「失敗した工程は
        ありません」と言って exit 0 を返した（2026-08-27・gate-verifier の指摘1）。
        """
        if self._recorder is None:
            return
        name, kwargs = self._stage_args(worker, ctx)
        try:
            with self._recorder.stage(name, **kwargs):
                raise _StageFailed(f"{name}: {reason}")
        except _StageFailed:
            pass
        except Exception as e:  # noqa: BLE001 — 記録の失敗で実行を落とさない
            logger.warning(f"⚠️ 工程を記録できませんでした: {e}")

    async def _ensure_allowed(self, harness, worker: PipelineStageWorker,
                              ctx: PipelineContext) -> bool:
        """**改善ループもガバナンスを通す**（R1.5-C1b）。

        `_quality_improvement_loop` は `_execute_worker` を直接呼んでおり、
        **断られた工程を迂回して実行していた。** しかも成功で `_outcomes` を
        上書きするので `completed` に戻り、記録には拒否の痕跡が残らなかった
        （2026-08-27・gate-verifier の指摘2）。
        """
        try:
            denied, reason = await self._fire_pre_hook(harness, worker, ctx)
        except Exception as e:  # noqa: BLE001 — 確かめられないなら止める
            denied, reason = True, f"事前フックが落ちました: {e}"
        if denied:
            logger.warning(f"⛔ {worker.name} は許可されませんでした: {reason}")
            self._record_outcome(worker, False)
            self._record_dead_stage(worker, ctx, f"Hook denied: {reason}")
        return not denied

    def _normalized(self, worker: PipelineStageWorker,
                    result: Optional[StageResult]) -> StageResult:
        """**`None` は成功ではない**（R1.5-C1b）。

        記録側は `result is not None and not result.success` を見ていたので
        `None` だと `success` と書かれ、`_outcomes` は失敗という食い違いが
        起きた。直列側はさらに `result.retries` で AttributeError になり、
        **実行ごと落ちて記録が閉じられなかった**（`status: running` が残る）。
        """
        if result is None:
            return StageResult(
                stage_name=worker.name, success=False,
                detail=f"{worker.name} が結果を返しませんでした")
        return result

    async def _execute_worker(self, worker: PipelineStageWorker,
                              ctx: PipelineContext) -> StageResult:
        """**1工程 = 1記録。** 失敗も原因と入力ごと残す（R1.5-C1）。

        記録の書き出しが実行を落とさないよう、記録側の例外は飲む。
        **worker の失敗そのものは飲まない** — `StageResult` はそのまま返す。
        """
        if self._recorder is None:
            result = self._normalized(worker, await worker.execute(ctx))
            self._record_outcome(worker, result.success)
            return result

        name, kwargs = self._stage_args(worker, ctx)
        result: Optional[StageResult] = None
        try:
            with self._recorder.stage(name, **kwargs):
                result = await worker.execute(ctx)
                if result is None or not result.success:
                    raise _StageFailed(
                        f"{name}: "
                        f"{result.detail if result else '結果を返しませんでした'}")
        except _StageFailed:
            pass
        except Exception:
            # worker が例外で落ちた場合。記録には残っているので、
            # 呼び出し側が扱えるよう `StageResult` に均す。
            logger.exception(f"❌ {worker.name} が例外で落ちました")
            result = StageResult(stage_name=worker.name, success=False,
                                 detail=f"{worker.name} が例外で落ちました")

        result = self._normalized(worker, result)
        self._record_outcome(worker, result.success)
        return result

    def _settle_outcomes(self, ctx: PipelineContext) -> tuple:
        """**最後まで通らなかった工程**を、致命とそれ以外に分ける。

        呼ぶのは全工程が終わってから。途中で数えるとリトライで通ったものまで
        失敗に数える（2026-08-26 に一度そうしてしまい、CI が教えてくれた）。
        """
        落ちた = [name for name, ok in self._outcomes.items() if not ok]
        致命 = [n for n in 落ちた if n in FATAL_STAGES]
        劣化 = [n for n in 落ちた if n not in FATAL_STAGES]
        for name in 劣化:
            if name not in ctx.skipped_features:
                ctx.skipped_features.append(name)
        return 致命, 劣化

    def _find_worker(self, worker_type: type) -> Optional[PipelineStageWorker]:
        """Worker をタイプで検索（インデックス直値を避ける）"""
        for w in self.workers:
            if isinstance(w, worker_type):
                return w
        return None

    def set_progress_callback(self, callback: Callable):
        """進捗コールバックを設定（pipeline_routerから注入）"""
        self._progress_callback = callback

    def set_ws_broadcast(self, broadcast_fn: Callable):
        """WebSocket ブロードキャスト関数を設定"""
        self._ws_broadcast = broadcast_fn

    async def _notify(self, worker: PipelineStageWorker, status: str,
                      detail: str = "", progress: int = -1, data: dict = None):
        """進捗通知（コールバック + WebSocket 両方）"""
        if self._progress_callback:
            self._progress_callback(worker.index, status, detail, progress, data)

        if self._ws_broadcast:
            msg = {
                "type": "pipeline_progress",
                "stage_index": worker.index,
                "stage_name": worker.name,
                "stage_icon": worker.icon,
                "status": status,
                "detail": detail,
                "progress": progress,
                "timestamp": datetime.now().isoformat(),
            }
            if data:
                msg["data"] = data
            await self._ws_broadcast(msg)

    # ============================================================
    # Harness ヘルパー（グレースフル初期化）
    # ============================================================

    def _init_harness(self, ctx: PipelineContext):
        """Harness ミドルウェアの初期化。利用不可時は None を返す。"""
        try:
            from harness.hooks import hook_system, HookEvent, HookInput, HookOutput
            from harness.session_manager import session_manager
            from harness.governance import governance_engine

            # セッション作成/リジューム
            if ctx.session_id:
                session = session_manager.resume_session(ctx.session_id)
                if not session:
                    session = session_manager.create_session(
                        video_path=ctx.video_path,
                        session_id=ctx.session_id,
                    )
            else:
                session = session_manager.create_session(video_path=ctx.video_path)
                ctx.session_id = session.session_id

            # トレーススパン開始
            trace_span = governance_engine.start_span(
                operation="pipeline_execute",
                tool_name="PipelineCoordinator",
                attributes={"video_path": ctx.video_path},
            )

            logger.info(
                f"🪝 Harness初期化完了: session={ctx.session_id[:8]}..."
            )

            return {
                "hook_system": hook_system,
                "HookEvent": HookEvent,
                "HookInput": HookInput,
                "HookOutput": HookOutput,
                "session_manager": session_manager,
                "governance_engine": governance_engine,
                "trace_span": trace_span,
            }

        except ImportError:
            logger.info("Harness未インストール — ミドルウェアなしで実行")
            return None
        except Exception as e:
            logger.warning(f"Harness初期化スキップ: {e}")
            return None

    def _ensure_template(self, ctx: PipelineContext):
        """テンプレート初期化保証 (C-2修正)。

        ctxにtemplate_idが指定されており、かつ現在template_configがアクティブでない場合、
        PRODUCTION_TEMPLATESから対応する設定を読み込んでアクティブテンプレートとして復元します。

        Args:
            ctx (PipelineContext): パイプライン実行のコンテキスト
        """
        try:
            from template_config import template_config
            from template_constants import PRODUCTION_TEMPLATES
            if not template_config.is_active and ctx.template_id:
                tmpl_data = PRODUCTION_TEMPLATES.get(ctx.template_id)
                if tmpl_data:
                    template_config.set_active_template(
                        ctx.template_id, tmpl_data,
                        theme_id="warm"
                    )
                    logger.info(f"🔗 パイプライン開始時テンプレート復元: {ctx.template_id}")
        except (ImportError, Exception) as e:
            logger.debug(f"Template init skipped: {e}")

    # Worker名 → ガバナンススコープID マッピング
    _WORKER_SCOPE_MAP = {
        "文字起こし": "transcriber",
        "AI校閲": "proofreader",
        "SmartCut構成": "smartcut",
        "プレビュー生成": "renderer",
        "YouTube最適化": "optimizer",
        "品質チェック": "quality_gate",
        "最終レンダリング": "renderer",
    }

    async def _fire_pre_hook(self, harness, worker, ctx):
        """PreToolUse Hook を発火 + GovernanceEngine 権限チェック。deny なら True を返す。"""
        if not harness:
            return False, None

        # --- H-04: GovernanceEngine による権限・レート制限チェック ---
        scope_id = self._WORKER_SCOPE_MAP.get(worker.name)
        if scope_id:
            ge = harness["governance_engine"]

            # ツール名解決（pipeline_tools.py での登録名に合わせる）
            tool_name = {
                "transcriber": "transcribe_video",
                "proofreader": "proofread_subtitles",
                "smartcut": "propose_smart_cut",
                "renderer": "generate_preview" if worker.name == "プレビュー生成" else "render_final",
                "optimizer": "optimize_youtube",
                "quality_gate": "check_quality",
            }.get(scope_id, worker.name)

            if not ge.check_permission(scope_id, tool_name):
                logger.warning(
                    f"🚫 Governance denied: {worker.name} "
                    f"(scope={scope_id}, tool={tool_name})"
                )
                return True, f"Governance denied: scope={scope_id} has no permission for {tool_name}"

            if not ge.check_rate_limit(scope_id):
                logger.warning(
                    f"🚫 Rate limit exceeded: {worker.name} (scope={scope_id})"
                )
                return True, f"Rate limit exceeded for scope={scope_id}"

        # --- H-03: Hook 発火 ---
        hook_input = harness["HookInput"](
            tool_name=worker.name,
            tool_input={"video_path": ctx.video_path, "stage": worker.index},
            session_id=ctx.session_id,
        )
        pre_output = await harness["hook_system"].fire(
            harness["HookEvent"].PRE_TOOL_USE, hook_input
        )

        if pre_output.permission_decision == "deny":
            logger.warning(
                f"🚫 Hook denied: {worker.name} — "
                f"{pre_output.permission_decision_reason}"
            )
            return True, pre_output.permission_decision_reason

        # セッション進捗更新
        harness["session_manager"].update_stage(
            ctx.session_id, worker.index, f"{worker.name} 実行中",
        )

        return False, None

    async def _fire_post_hook(self, harness, worker, result, ctx):
        """PostToolUse / PostToolUseFailure Hook を発火。"""
        if not harness:
            return

        if result.success:
            post_input = harness["HookInput"](
                tool_name=worker.name,
                tool_output=result.data,
                session_id=ctx.session_id,
            )
            await harness["hook_system"].fire(
                harness["HookEvent"].POST_TOOL_USE, post_input
            )
            # セッションにツール呼び出し記録
            harness["session_manager"].record_tool_call(
                ctx.session_id, worker.name,
                {"stage": worker.index},
                result.data, result.duration_seconds,
            )
        else:
            fail_input = harness["HookInput"](
                tool_name=worker.name,
                error=result.detail,
                session_id=ctx.session_id,
            )
            await harness["hook_system"].fire(
                harness["HookEvent"].POST_TOOL_USE_FAILURE, fail_input
            )

    def _finalize_harness(self, harness, ctx, status: str = "ok"):
        """Harness セッションの完了処理。"""
        if not harness:
            return

        try:
            harness["governance_engine"].end_span(
                harness["trace_span"], status=status
            )

            if status == "ok":
                harness["session_manager"].complete_session(
                    ctx.session_id,
                    quality_score=ctx.quality_score,
                    final_data={
                        "stages_completed": len(ctx.stage_results),
                        "final_path": ctx.final_path,
                    },
                )
            elif status == "error":
                harness["session_manager"].error_session(
                    ctx.session_id,
                    ctx.warnings[-1] if ctx.warnings else "Pipeline error",
                )

            harness["governance_engine"].flush_traces(ctx.session_id)
        except Exception as e:
            logger.debug(f"Harness finalize skipped: {e}")

    # ============================================================
    # メインパイプライン実行 — 単一パス (Harness統合済み)
    # ============================================================

    async def execute(self, ctx: PipelineContext) -> Dict:
        """パイプライン実行 — Harness統合済み単一パス。

        設計:
          - Prompt Chaining パターン: Worker順次実行 + ゲートチェック
          - Guardrails パターン: Pre/Post Hook による自動ガードレール
          - Evaluator-Optimizer パターン: 品質ゲート改善ループ

        Harness利用不可時はミドルウェアなしでグレースフル実行。
        """
        ctx.started_at = datetime.now().isoformat()
        total_start = time.time()

        # ━━━ 0. 実行記録を開く（R1.5-C1）━━━
        # **どの工程がどのモデルで動き、どこで落ちたか。** これが無いと
        # 「動いた」を証拠で示せない。書き出しに失敗しても実行は続ける。
        self._open_recorder(ctx)

        # ━━━ 0. パフォーマンスバジェットマネージャー初期化 (PB-01) ━━━
        perf_manager = self._init_performance_budget_manager(ctx)

        # ━━━ 1. Harness ミドルウェア初期化 ━━━
        harness = self._init_harness(ctx)

        # ━━━ 2. ディスク空き容量チェック ━━━
        free_gb = self._check_disk_space(ctx)
        if free_gb is not None and free_gb < 1.0:
            self._finalize_harness(harness, ctx, "error")
            self._close_recorder(ctx, "failed")
            return self._build_result(ctx, "error", total_start,
                                      f"ディスク空き容量不足: {free_gb:.1f}GB")

        # ━━━ 3. テンプレート初期化保証 (C-2/K-01修正) ━━━
        self._ensure_template(ctx)

        # ━━━ 4. Worker DAG並列実行 (サステナブル10分アーキテクチャ) ━━━
        # 直列ステージ (S1→S2→S3)
        serial_error = await self._execute_serial_stages(ctx, harness, perf_manager)
        if serial_error:
            self._finalize_harness(harness, ctx, "error")
            self._close_recorder(ctx, "failed")
            return self._build_result(ctx, "error", total_start, serial_error)

        # 並列ステージ (S4 || S5 || S6)
        await self._execute_parallel_stages(ctx, harness, perf_manager)

        # 最終ステージ (品質ゲート連動 T-031)
        await self._execute_final_rendering_stage(ctx, harness, perf_manager)

        # 品質ゲート: Evaluator-Optimizer (並列実行結果から取得)
        await self._optimize_quality(ctx, harness, perf_manager)

        # ━━━ 4.5 失敗を握り潰さない（R1.5-C1）━━━
        # **落ちた工程があるのに "completed" を返さない。** 直列で中断するのは
        # 文字起こしだけで、校閲・スマートカット・メタデータ・品質・レンダリングの
        # 失敗はここまで素通りしていた。宣言済みの例外（プレビュー）は除く。
        致命, 劣化 = self._settle_outcomes(ctx)
        if 致命:
            self._finalize_harness(harness, ctx, "error")
            self._close_recorder(ctx, "failed")
            return self._build_result(
                ctx, "error", total_start,
                f"工程が失敗しました: {'、'.join(致命)}")

        # 落ちた工程はあるが動画は作れた場合。**完走とは呼ばない。**
        final_status = STATUS_DEGRADED if 劣化 else STATUS_COMPLETED

        # ━━━ 5. パイプライン後処理 ━━━
        retention_report = await self._run_retention_analysis(ctx)
        if retention_report:
            ctx.stage_results.append(retention_report)

        # DreamEngine 学習フック
        await self._trigger_dream_learning(ctx)

        # ━━━ 6. Harness 完了処理 ━━━
        self._finalize_harness(harness, ctx, "ok")

        # ━━━ 7. パフォーマンスバジェットレポート保存 (PB-01) ━━━
        perf_report_data = self._save_performance_report(ctx, perf_manager)

        self._close_recorder(ctx, final_status)

        result = self._build_result(ctx, final_status, total_start)
        if perf_report_data:
            result["performance_budget"] = perf_report_data
        return result

    # --- 実行記録の開閉 -----------------------------------------------------

    def _open_recorder(self, ctx: PipelineContext) -> None:
        """記録を開く。**開けなくても実行は続ける**（記録は実行を止めない）。"""
        self._recorder = None
        self._outcomes = {}
        try:
            kwargs = {"inputs": {
                "video_path": ctx.video_path,
                "session_id": ctx.session_id,
                "target_minutes": ctx.target_minutes,
                "template_id": ctx.template_id,
                "mainline": "agents",
            }}
            # **記録の置き場は差し替えられること。** 差し替えられないと、
            # コーディネータを動かすテストが本番の `output/runs/` に
            # ゴミを積む（2026-08-26 に238件積んだ）。
            runs_dir = self.runs_dir or os.getenv("AVS_RUNS_DIR")
            if runs_dir:
                kwargs["runs_dir"] = Path(runs_dir)
            if self.ledger_path is not None:
                kwargs["ledger_path"] = Path(self.ledger_path)
            self._recorder = RunRecorder(**kwargs)
            logger.info(f"📓 実行記録: {self._recorder.path}")
        except Exception as e:  # noqa: BLE001 — 記録の失敗で実行を落とさない
            logger.warning(f"⚠️ 実行記録を開けませんでした: {e}")

    def _intermediates(self, ctx: PipelineContext) -> list:
        """**AI が生み出したものが下流で使われたか**（R1.5-C3）。

        AI は金を使って中間成果物を作る。作ったものが誰にも読まれずに消えるなら、
        **その呼び出しは成果物に何も足していない。**

        - `subtitles`（校閲したテキスト）→ プレビューが焼き込む。
          実際に届いていることは SHA256 の比較で別途確かめている
          （`artifact_gate --ai-effect`）
        - `youtube_metadata` → **消費者は YouTube 投稿で、本線に工程が無い**
          （`backend/config/feature_gaps.json` の `youtube_upload`）。
          いまは必ず「使われていない」になる
        - `quality_feedback` → レンダリングモードの決定と改善ループが読む
        """
        使った工程 = {n for n, ok in self._outcomes.items() if ok}
        return [
            {"name": "subtitles", "produced_by": "proofread",
             "produced": bool(ctx.segments),
             "consumed_by": "preview",
             "consumed": "preview" in 使った工程},
            {"name": "youtube_metadata", "produced_by": "youtube_opt",
             "produced": bool(ctx.metadata),
             "consumed_by": "youtube_upload",
             "consumed": False},
            {"name": "quality_feedback", "produced_by": "quality_gate",
             "produced": bool(ctx.quality_feedback),
             "consumed_by": "render",
             "consumed": ctx.render_mode in ("safe", "production")},
        ]

    def _close_recorder(self, ctx: PipelineContext, status: str) -> None:
        """記録を閉じる。成果物のパスも残す。"""
        recorder = self._recorder
        if recorder is None:
            return
        try:
            for path in (ctx.final_path, ctx.preview_path):
                if path:
                    recorder.artifact(path)
            # **記録だけを見て「何が落ちたか」が分かること**（R1.5-C1b）。
            # `degraded` は残っていたが、何が落ちたのかは API の戻り値に
            # しか無く、記録からは追えなかった。
            # **致命工程も残す**（R1.5-C1b）。`skipped_features` には劣化しか
            # 入らないうえ、致命の早期 return では `_settle_outcomes` 自体を
            # 通らないので空のまま閉じていた。`_outcomes` なら着手した工程が
            # 全部入っている。
            落ちた = [n for n, ok in self._outcomes.items() if not ok]
            recorder.intermediates(self._intermediates(ctx))
            recorder.finish(status, health={
                "skipped_features": list(ctx.skipped_features),
                "failed_stages": 落ちた,
                "warnings": list(ctx.warnings),
                "all_features_active": not 落ちた and not ctx.skipped_features,
            })
        except Exception as e:  # noqa: BLE001 — 同上
            logger.warning(f"⚠️ 実行記録を閉じられませんでした: {e}")
        finally:
            self._recorder = None

    def _init_performance_budget_manager(self, ctx: PipelineContext) -> Optional[Any]:
        """パフォーマンスバジェットマネージャーを初期化します。(PB-01)"""
        try:
            from services.performance_budget_manager import PerformanceBudgetManager
            _budget_json = Path(__file__).parent.parent / "branding" / "performance_budget.json"
            _perf_output = Path(ctx.video_path).parent / "performance" if ctx.video_path else None
            return PerformanceBudgetManager(
                budget_path=_budget_json if _budget_json.exists() else None,
                output_dir=_perf_output,
                video_duration_min=getattr(ctx, 'video_duration_min', None),
            )
        except (ImportError, Exception):
            return None

    def _check_disk_space(self, ctx: PipelineContext) -> Optional[float]:
        """ディスク空き容量をチェックし、警告およびエラー判定を行います。二重防御。"""
        try:
            import shutil
            output_dir = Path(ctx.video_path).parent
            disk = shutil.disk_usage(str(output_dir))
            free_gb = disk.free / (1024 ** 3)
            if free_gb < 1.0:
                logger.error(f"❌ ディスク空き不足: {free_gb:.1f}GB (最低1GB必要)")
            elif free_gb < 5.0:
                ctx.warnings.append(f"ディスク残量注意: {free_gb:.1f}GB")
                logger.warning(f"⚠️ ディスク残量注意: {free_gb:.1f}GB")
            return free_gb
        except Exception as e:
            logger.debug(f"Disk check skipped: {e}")
            return None

    async def _execute_serial_stages(self, ctx: PipelineContext, harness: Optional[Dict],
                                     perf_manager: Optional[Any]) -> Optional[str]:
        """直列ステージ (S1→S2→S3) を順次実行。致命的エラー発生時はエラー詳細を返します。"""
        serial_workers = [w for w in self.workers
                          if isinstance(w, (TranscribeWorker, ProofreadWorker, SmartCutWorker))]

        for worker in serial_workers:
            # **着手した工程は、結果を返すまで「落ちた」扱い**（R1.5-C1b）。
            # 載っていない工程は `_settle_outcomes` が数えられない。
            self._record_outcome(worker, False)
            try:
                denied, deny_reason = await self._fire_pre_hook(
                    harness, worker, ctx)
            except Exception as e:  # noqa: BLE001 — 数えずに素通りさせない
                logger.exception(f"❌ {worker.name} の事前フックが落ちました")
                self._record_dead_stage(worker, ctx, f"事前フックが落ちました: {e}")
                ctx.stage_results.append(StageResult(
                    stage_name=worker.name, success=False,
                    detail=f"事前フックが落ちました: {e}"))
                if type(worker).__name__ in FATAL_WORKERS:
                    return f"事前フックが落ちました: {e}"
                continue
            if denied:
                # **断られた＝その工程は動いていない。** 成功に数えない
                self._record_outcome(worker, False)
                self._record_dead_stage(worker, ctx, f"Hook denied: {deny_reason}")
                ctx.stage_results.append(StageResult(
                    stage_name=worker.name, success=False,
                    detail=f"Hook denied: {deny_reason}",
                ))
                if type(worker).__name__ in FATAL_WORKERS:
                    return deny_reason
                continue

            await self._notify(worker, "running", f"{worker.name} 開始...")
            result = None
            for attempt in range(1, self.MAX_RETRIES + 1):
                _worker_start = time.time()
                result = await self._execute_worker(worker, ctx)
                _worker_dur = time.time() - _worker_start
                if perf_manager:
                    perf_manager.record_worker_time(worker.name, _worker_dur)
                result.retries = attempt - 1
                if worker.verify(result):
                    break
                if attempt < self.MAX_RETRIES:
                    logger.warning(f"🔄 {worker.name} リトライ {attempt}/{self.MAX_RETRIES}: {result.detail}")
                    await self._notify(worker, "retrying", f"リトライ {attempt}/{self.MAX_RETRIES}")
                    await asyncio.sleep(1)

            ctx.stage_results.append(result)
            await self._fire_post_hook(harness, worker, result, ctx)

            if result.success:
                await self._notify(worker, "completed", result.detail, 100, result.data)
            else:
                await self._notify(worker, "error", result.detail)
                if type(worker).__name__ in FATAL_WORKERS:
                    logger.error(f"❌ 致命的エラー: {worker.name} — 中断")
                    return result.detail
        return None

    async def _execute_parallel_stages(self, ctx: PipelineContext, harness: Optional[Dict],
                                       perf_manager: Optional[Any]):
        """並列ステージ (S4 || S5 || S6) を実行。"""
        parallel_workers = [w for w in self.workers
                            if isinstance(w, (PreviewWorker, YouTubeOptWorker, QualityGateWorker))]

        async def _run_parallel_worker(worker):
            """並列実行用のワーカーラッパー"""
            # **着手した工程は、結果を返すまで「落ちた」扱い**（R1.5-C1b）。
            # ここが無かったので、事前フックが例外で落ちた工程は `_outcomes`
            # に載らず、`gather(return_exceptions=True)` がログ1行に変えて
            # 捨てていた。**3工程が1つも動かなくても `completed`** になった。
            self._record_outcome(worker, False)
            try:
                denied, deny_reason = await self._fire_pre_hook(
                    harness, worker, ctx)
            except Exception as e:  # noqa: BLE001 — 数えずに素通りさせない
                logger.exception(f"❌ {worker.name} の事前フックが落ちました")
                self._record_dead_stage(worker, ctx, f"事前フックが落ちました: {e}")
                r = StageResult(stage_name=worker.name, success=False,
                                detail=f"事前フックが落ちました: {e}")
                ctx.stage_results.append(r)
                return r
            if denied:
                self._record_outcome(worker, False)
                self._record_dead_stage(worker, ctx, f"Hook denied: {deny_reason}")
                r = StageResult(stage_name=worker.name, success=False,
                                detail=f"Hook denied: {deny_reason}")
                ctx.stage_results.append(r)
                return r

            await self._notify(worker, "running", f"{worker.name} 開始...")
            result = None
            for attempt in range(1, self.MAX_RETRIES + 1):
                _pw_start = time.time()
                result = await self._execute_worker(worker, ctx)
                _pw_dur = time.time() - _pw_start
                if perf_manager:
                    perf_manager.record_worker_time(worker.name, _pw_dur)
                result.retries = attempt - 1
                if worker.verify(result):
                    break
                if attempt < self.MAX_RETRIES:
                    logger.warning(f"🔄 {worker.name} リトライ {attempt}/{self.MAX_RETRIES}: {result.detail}")
                    await asyncio.sleep(1)

            ctx.stage_results.append(result)
            await self._fire_post_hook(harness, worker, result, ctx)

            if result.success:
                await self._notify(worker, "completed", result.detail, 100, result.data)
            else:
                await self._notify(worker, "error", result.detail)
                if isinstance(worker, PreviewWorker):
                    logger.error(f"❌ 致命的エラー: {worker.name} (並列)")
            return result

        if parallel_workers:
            logger.info(f"⚡ DAG並列実行: {[w.name for w in parallel_workers]}")
            parallel_results = await asyncio.gather(
                *[_run_parallel_worker(w) for w in parallel_workers],
                return_exceptions=True,
            )
            # T-020b: PreviewWorker の失敗は警告のみ（パイプライン中断しない）
            for r in parallel_results:
                if isinstance(r, Exception):
                    logger.error(f"❌ 並列ステージ例外: {r}")
                elif isinstance(r, StageResult) and not r.success:
                    preview_worker = self._find_worker(PreviewWorker)
                    if preview_worker and r.stage_name == preview_worker.name:
                        logger.warning(
                            f"⚠️ [T-020b] PreviewWorker失敗 — パイプライン継続: {r.detail}"
                        )
                        ctx.warnings.append(f"プレビュー生成失敗: {r.detail}")

    async def _execute_final_rendering_stage(self, ctx: PipelineContext, harness: Optional[Dict],
                                             perf_manager: Optional[Any]):
        """最終ステージ (品質ゲート連動 T-031) のレンダリング処理。"""
        render_worker = self._find_worker(RenderWorker)
        if render_worker:
            # **着手した工程は、結果を返すまで「落ちた」扱い**（R1.5-C1b）
            self._record_outcome(render_worker, False)
            # T-031: 品質ゲート結果に基づくレンダリングモード判定
            quality_passed = ctx.quality_score >= 90
            if not quality_passed:
                ctx.render_mode = "safe"
                logger.warning(
                    f"⚠️ [T-031] 品質スコア{ctx.quality_score}点 < 90 — safe_modeレンダリング"
                )
                # T-033: WebSocket で品質不合格通知
                if self._ws_broadcast:
                    await self._ws_broadcast({
                        "type": "quality_gate_blocked",
                        "score": ctx.quality_score,
                        "threshold": 90,
                        "feedback": ctx.quality_feedback[:5],
                        "render_mode": "safe",
                        "force_render_available": True,
                    })
            else:
                ctx.render_mode = "production"

            await self._notify(render_worker, "running",
                               f"{render_worker.name} 開始... (mode={ctx.render_mode})")
            _render_start = time.time()
            result = await self._execute_worker(render_worker, ctx)
            _render_dur = time.time() - _render_start
            if perf_manager:
                perf_manager.record_worker_time(render_worker.name, _render_dur)
            ctx.stage_results.append(result)
            await self._fire_post_hook(harness, render_worker, result, ctx)
            if result.success:
                await self._notify(render_worker, "completed", result.detail, 100, result.data)
            else:
                await self._notify(render_worker, "error", result.detail)

    async def _optimize_quality(self, ctx: PipelineContext, harness: Optional[Dict],
                                perf_manager: Optional[Any]):
        """品質ゲートが不合格の場合に Evaluator-Optimizer を実行します。"""
        quality_worker = self._find_worker(QualityGateWorker)
        quality_result = next(
            (r for r in ctx.stage_results if r.stage_name == quality_worker.name),
            None
        ) if quality_worker else None

        if quality_result and not quality_worker.verify(quality_result):
            try:
                from harness.evaluator_optimizer import evaluator_optimizer
                opt_result = await evaluator_optimizer.run(ctx, max_iterations=3)
                if opt_result.success:
                    logger.info(
                        f"✅ Evaluator-Optimizer 成功: "
                        f"{opt_result.initial_score}→{opt_result.final_score}点 "
                        f"({opt_result.iterations}回)"
                    )
                    if harness:
                        harness["session_manager"].record_tool_call(
                            ctx.session_id, "evaluator_optimizer",
                            {"iterations": opt_result.iterations},
                            {"improvements": opt_result.improvements_applied},
                            opt_result.duration_seconds,
                        )
                else:
                    logger.warning(
                        f"⚠️ Evaluator-Optimizer 不合格のまま: "
                        f"{opt_result.final_score}点"
                    )
            except (ImportError, Exception):
                improved = await self._quality_improvement_loop(
                    ctx, perf_manager, harness=harness)
                if not improved:
                    logger.warning("品質改善ループ上限到達 — 現状で続行")

    def _save_performance_report(self, ctx: PipelineContext, perf_manager: Optional[Any]) -> Optional[Dict]:
        """パフォーマンスバジェットレポートを保存します。"""
        if perf_manager:
            try:
                perf_report = perf_manager.generate_report(ctx.session_id)
                perf_manager.save_report(perf_report)
                return {
                    "total_duration": perf_report.total_duration,
                    "total_budget": perf_report.total_budget,
                    "over_budget": perf_report.over_budget,
                    "worker_count": len(perf_report.workers),
                }
            except Exception as e:
                logger.debug(f"Performance report save skipped: {e}")
        return None

    async def _quality_improvement_loop(self, ctx: PipelineContext,
                                         perf_manager=None,
                                         harness: Optional[Dict] = None) -> bool:
        """
        U-03: 品質ゲート90点未満時の自動改善ループ。

        Preview再生成 → QualityGate再チェック を最大 MAX_QUALITY_RETRIES 回繰り返す。
        フィードバックを蓄積し、各イテレーションで改善を試みる。
        BUG-02修正: 各イテレーションの実行時間をperf_managerに計測記録する。
        """
        preview_worker = self._find_worker(PreviewWorker)
        quality_worker = self._find_worker(QualityGateWorker)

        if not preview_worker or not quality_worker:
            logger.error("品質改善ループ: PreviewWorker/QualityGateWorker が見つかりません")
            return False

        for qi in range(1, self.MAX_QUALITY_RETRIES + 1):
            # 前回の品質フィードバックを記録
            last_result = ctx.stage_results[-1] if ctx.stage_results else None
            if last_result and last_result.data.get("feedback"):
                ctx.quality_feedback.extend(last_result.data["feedback"])

            logger.info(
                f"🔄 品質改善ループ {qi}/{self.MAX_QUALITY_RETRIES}: "
                f"前回スコア={ctx.quality_score}点, "
                f"フィードバック={len(ctx.quality_feedback)}件"
            )
            await self._notify(
                quality_worker, "retrying",
                f"品質改善 {qi}/{self.MAX_QUALITY_RETRIES} (前回:{ctx.quality_score}点)"
            )

            # Preview 再生成 (BUG-02修正: 計測フック追加)
            await self._notify(preview_worker, "running", "品質改善のため再生成中...")
            # **断られた工程をここで迂回しない**（R1.5-C1b）
            if not await self._ensure_allowed(harness, preview_worker, ctx):
                return False
            _ql_preview_start = time.time()
            preview_result = await self._execute_worker(preview_worker, ctx)
            _ql_preview_dur = time.time() - _ql_preview_start
            if perf_manager:
                perf_manager.record_worker_time(preview_worker.name, _ql_preview_dur)
            if not preview_result.success:
                logger.warning(f"品質改善ループ: Preview再生成失敗 — {preview_result.detail}")
                continue

            # QualityGate 再チェック (BUG-02修正: 計測フック追加)
            await self._notify(quality_worker, "running", "品質再チェック...")
            if not await self._ensure_allowed(harness, quality_worker, ctx):
                return False
            _ql_quality_start = time.time()
            quality_result = await self._execute_worker(quality_worker, ctx)
            _ql_quality_dur = time.time() - _ql_quality_start
            if perf_manager:
                perf_manager.record_worker_time(quality_worker.name, _ql_quality_dur)
            ctx.stage_results.append(quality_result)

            if quality_worker.verify(quality_result):
                logger.info(
                    f"✅ 品質改善成功: {ctx.quality_score}点 "
                    f"({qi}回目のリトライ)"
                )
                await self._notify(
                    quality_worker, "completed",
                    f"品質改善成功: {ctx.quality_score}点", 100
                )
                return True

            logger.warning(
                f"品質改善ループ {qi}: まだ不合格 "
                f"({ctx.quality_score}点)"
            )

        return False

    def _build_result(self, ctx: PipelineContext, status: str,
                      total_start: float, error: str = "") -> Dict:
        # ━━━ D-6修正: 品質ゲート詳細をresultに含める ━━━
        # ctxから直接取得（StageResult.dataの伝達に依存しない）
        quality_details = {
            "score": ctx.quality_score,
            "feedback": getattr(ctx, 'quality_feedback', []),
            "category_report": getattr(ctx, 'quality_category_report', []),
            "category_scores": getattr(ctx, 'quality_category_scores', {}),
        }

        # T-032: 品質不合格レポートの構築
        quality_gate_report = None
        if ctx.quality_score < 90 and ctx.quality_score > 0:
            quality_gate_report = {
                "status": "blocked",
                "score": ctx.quality_score,
                "threshold": 90,
                "gap": 90 - ctx.quality_score,
                "feedback": getattr(ctx, 'quality_feedback', []),
                "category_scores": getattr(ctx, 'quality_category_scores', {}),
                "improvement_suggestions": self._generate_improvement_suggestions(ctx),
                "force_render_available": True,
                "force_render_endpoint": "/api/pipeline/force-render",
            }
        ctx.quality_gate_report = quality_gate_report

        return {
            "status": status,
            "session_id": ctx.session_id,
            "duration_seconds": round(time.time() - total_start, 1),
            "final_path": ctx.final_path,
            "preview_path": ctx.preview_path,
            "metadata": ctx.metadata,
            "quality_score": ctx.quality_score,
            "quality_details": quality_details,
            "quality_gate_report": quality_gate_report,  # T-032
            "segments_count": len(ctx.segments) if ctx.segments else 0,
            "stage_results": [
                {"name": r.stage_name, "success": r.success,
                 "detail": r.detail, "duration": r.duration_seconds,
                 "retries": r.retries}
                for r in ctx.stage_results
            ],
            "error": error,
            # Phase 4: 無人運用ヘルスレポート
            "health": {
                "skipped_features": ctx.skipped_features,
                "warnings": ctx.warnings,
                "all_features_active": len(ctx.skipped_features) == 0,
            },
        }

    def _generate_improvement_suggestions(self, ctx: PipelineContext) -> List[Dict]:
        """T-032: 品質フィードバックから改善提案を生成"""
        suggestions = []
        seen_actions = set()
        for fb in getattr(ctx, 'quality_feedback', []):
            action = None
            if any(kw in fb for kw in ["音", "LUFS", "ラウドネス", "サイレント"]):
                action = {"action": "audio_normalization", "description": "音声ラウドネス正規化で改善可能"}
            elif any(kw in fb for kw in ["字幕", "テキスト", "校閲"]):
                action = {"action": "re_proofread", "description": "AI再校閲で改善可能"}
            elif any(kw in fb for kw in ["メタデータ", "タイトル", "タグ"]):
                action = {"action": "regenerate_metadata", "description": "メタデータ再生成で改善可能"}
            elif any(kw in fb for kw in ["セグメント", "構成", "尺"]):
                action = {"action": "restructure_segments", "description": "セグメント構成最適化で改善可能"}
            if action and action["action"] not in seen_actions:
                seen_actions.add(action["action"])
                suggestions.append(action)
        return suggestions
    async def _run_retention_analysis(self, ctx: PipelineContext):
        """
        BIZ-4: パイプライン完了前にRetention Map分析を実行。
        離脱リスクの高いポイントを特定し、リエンゲージメント提案を生成。
        """
        try:
            from plugins.retention_map_plugin import retention_map_plugin

            video_id = Path(ctx.video_path).stem
            # 動画の総尺（セグメントから推定）
            duration_sec = 0
            if ctx.segments:
                last = ctx.segments[-1]
                if isinstance(last, dict):
                    last_end = last.get("end", last.get("start", 0))
                else:
                    last_end = getattr(last, "end", getattr(last, "start", 0))
                duration_sec = int(last_end + 5)
            if duration_sec < 30:
                duration_sec = ctx.target_minutes * 60  # フォールバック

            report = retention_map_plugin.analyze_retention_risks(
                video_id=video_id,
                duration_sec=duration_sec,
                video_path=ctx.video_path,
            )

            # パイプライン結果にRetentionデータを付加
            ctx.metadata["retention_analysis"] = {
                "overall_risk": report.overall_risk_assessment,
                "suggestions_count": len(report.suggestions),
                "high_risk_segments": [
                    {
                        "time": f"{s.start_time}-{s.end_time}s",
                        "risk": s.risk_level,
                        "label": s.label,
                    }
                    for s in report.segments
                    if s.risk_level >= 7
                ],
                "top_suggestions": report.suggestions[:3],
            }

            logger.info(
                f"📊 BIZ-4: Retention Map分析完了 — "
                f"リスク: {report.overall_risk_assessment}, "
                f"提案: {len(report.suggestions)}件"
            )

            # StageResult形式で返す
            return StageResult(
                stage_name="Retention分析",
                success=True,
                detail=f"リスク: {report.overall_risk_assessment} / 提案: {len(report.suggestions)}件",
                duration_seconds=0.1,
                data=ctx.metadata["retention_analysis"],
            )

        except (ImportError, Exception) as e:
            logger.debug(f"Retention分析スキップ（非致命的）: {e}")
            return None

    async def _trigger_dream_learning(self, ctx: PipelineContext):
        """提案3: パイプライン完了時に DreamEngine 学習フック"""
        # **実走のたびに追跡ファイルが書き換わる。** 2026-08-26 に1回起こした:
        # 比較のため走らせただけで `verified_facts_index.json` から138行、
        # `VERIFIED_FACTS.md` から28行が消えた（`8cd96ce` で復旧）。
        # 検証のための実走では止められるようにする。**既定は従来どおり動く** —
        # 学習を止めるかどうかは製品の判断なので、ここでは既定を変えない。
        if os.getenv("AVS_SKIP_LEARNING_SIDE_EFFECTS") == "1":
            logger.info("🌙 学習フックを止めました（AVS_SKIP_LEARNING_SIDE_EFFECTS=1）")
            ctx.skipped_features.append("dream_learning")
            return
        try:
            from agents.dream_engine import dream_engine

            # 制作ナレッジを構造化して記録
            knowledge = {
                "type": "pipeline_completion",
                "timestamp": datetime.now().isoformat(),
                "video": Path(ctx.video_path).name,
                "segments_total": len(ctx.segments),
                "segments_selected": len(ctx.selected_segments),
                "quality_score": ctx.quality_score,
                "stage_durations": {
                    r.stage_name: r.duration_seconds
                    for r in ctx.stage_results
                },
                "total_corrections": sum(
                    r.data.get("total", 0) for r in ctx.stage_results
                    if r.stage_name == "AI校閲"
                ),
                "retries_used": sum(r.retries for r in ctx.stage_results),
            }

            # DreamEngine のシグナルとして記録。実行のたびに増える記録なので
            # writable_path 経由にする（読み出す tick_loop 側も同じ経路）。
            knowledge_path = _writable_path("backend/agents/logs/pipeline_knowledge")
            knowledge_path.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            knowledge_file = knowledge_path / f"run_{ts}.json"
            knowledge_file.write_text(
                json.dumps(knowledge, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

            logger.info(f"🌙 制作ナレッジ記録: {knowledge_file.name}")

            # R-02: セッションカウンターを更新（Gate 2 通過のため必須）
            dream_engine.increment_session_count()

            # DreamEngine トリガー判定
            if await dream_engine.should_dream():
                logger.info("🌙 DreamEngine 起動条件充足 → 学習サイクル開始")
                asyncio.create_task(dream_engine.run_dream_cycle())

        except (ImportError, Exception) as e:
            logger.debug(f"DreamEngine learning hook skipped: {e}")



# シングルトン
pipeline_coordinator = PipelineCoordinator()


# --- Thumbnail Generation & Quality Validation for Phase 27 ---
THUMBNAIL_OUTPUT_DIR = _writable_path("backend/temp_thumbnails")

def generate_pipeline_coordinator_thumbnail(output_path, width=1280, height=720, text="Pipeline Coordinator Thumbnail"):
    """Pillowを使用して、指定された解像度とテキストでサムネイル画像を生成する"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (width, height), color=(60, 100, 60))
    d = ImageDraw.Draw(img)
    d.text((10, 10), text, fill=(255, 255, 255))
    img.save(output_path, "PNG")
    return output_path

def validate_pipeline_coordinator_thumbnail(file_path) -> dict:
    """サムネイル画像の品質要件（解像度、アスペクト比、ファイルサイズ、破損）を検証する"""
    file_path = Path(file_path)
    
    if not file_path.exists():
        raise FileNotFoundError(f"Thumbnail file not found: {file_path}")
        
    size_bytes = file_path.stat().st_size
    if size_bytes >= 4 * 1024 * 1024:
        raise ValueError(f"File size exceeds 4MB limit: {size_bytes} bytes")
        
    try:
        with Image.open(file_path) as img:
            img.verify()
    except Exception as e:
        raise ValueError(f"Image is corrupted or invalid format: {e}")
        
    try:
        with Image.open(file_path) as img:
            width, height = img.size
    except Exception as e:
        raise ValueError(f"Failed to load image for resolution check: {e}")
        
    if width < 1280 or height < 720:
        raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
        
    aspect_ratio = width / height
    target_ratio = 16.0 / 9.0
    if abs(aspect_ratio - target_ratio) > 1e-3:
        raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}")
        
    return {
        "path": str(file_path),
        "width": width,
        "height": height,
        "size_bytes": size_bytes
    }

async def resolve_pipeline_coordinator_thumbnail_task(task_id: str) -> str:
    """StageBoundAgent の process_func として動作する非同期タスク処理"""
    output_path = THUMBNAIL_OUTPUT_DIR / f"{task_id}.png"
    generate_pipeline_coordinator_thumbnail(output_path)
    result_info = validate_pipeline_coordinator_thumbnail(output_path)
    return json.dumps(result_info)


# ============================================================
# CLI — **本線をコマンドから走らせる**（R1.5-C1）
# ============================================================
#
#   PYTHONPATH=./backend python -m backend.agents.pipeline_coordinator <入力.mp4>
#
# **これは課金経路。** 校閲・メタデータ・品質ゲートが Gemini を呼ぶ。
# `cost_guard` が呼び出しごとに計上し、予算が尽きれば例外で止まる。

def _probe_duration_sec(video: Path) -> Optional[float]:
    """素材の尺を秒で返す。**読めなければ `None`。**

    既存の `aligned_preview_generator.get_video_duration()` は失敗を 15.0 秒に
    握り潰す。同じ形にすると、誤った目標尺が黙って入って品質ゲートが
    -50 点を打つ（2026-08-27 に実際にそうなった）。**読めなかったことは
    読めなかったと言う。**
    """
    import subprocess
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
            capture_output=True, text=True, check=True, timeout=30).stdout
        return float(out.strip())
    except Exception as e:  # noqa: BLE001 — 読めないことを 0 や既定値にしない
        logger.warning(f"⚠️ 素材の尺を読めませんでした: {e}")
        return None


def _auto_target_minutes(duration_sec: Optional[float]) -> Optional[int]:
    """**目標尺は素材から決める**（2026-08-27 ユーザー決定）。

    `--target-minutes` の既定は20分だった。30秒の素材に対して品質ゲートの
    QV-01 が「出力尺異常（目標20分, 差19.6分）」で満額 -50 を打ち、
    スコアが 2/100 に張り付いていた。**目標尺を素材に合わせるだけで 52点。**

    `target_minutes` は SmartCut では使われておらず、**品質ゲートが
    「出来上がりはこれくらいのはず」と照らす期待値**としてだけ効く。
    """
    if duration_sec is None or duration_sec <= 0:
        return None
    return max(1, round(duration_sec / 60))


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    import uuid

    parser = argparse.ArgumentParser(
        description="本線（agents）で動画を1本作る。**課金経路**")
    parser.add_argument("video", help="入力動画のパス")
    parser.add_argument("--target-minutes", type=int, default=None,
                        help="出来上がりの目安（分）。既定は素材の尺から決める")
    parser.add_argument("--runs-dir", default=None,
                        help="実行記録の置き場（既定 output/runs）")
    parser.add_argument("--no-ledger", action="store_true",
                        help="台帳に1本ぶんの要約を書かない（試し撃ち用）")
    args = parser.parse_args(argv)

    video = Path(args.video)
    if not video.is_file():
        print(f"🚫 入力がありません: {video}")
        return 1

    target_minutes = args.target_minutes
    if target_minutes is None:
        target_minutes = _auto_target_minutes(_probe_duration_sec(video))
        if target_minutes is None:
            print("🚫 素材の尺を読めないので目標尺を決められません。"
                  "`--target-minutes <分>` で明示してください")
            return 1
        print(f"📏 目標尺を素材から決めました: {target_minutes} 分")

    from backend import cost_guard as _cg
    _cg.load_env()

    coordinator = PipelineCoordinator()
    if args.runs_dir:
        coordinator.runs_dir = Path(args.runs_dir)
    if not args.no_ledger:
        coordinator.ledger_path = Path(_cg.LEDGER_PATH)

    ctx = PipelineContext(video_path=str(video),
                          target_minutes=target_minutes,
                          session_id=f"cli-{uuid.uuid4().hex[:8]}")

    result = asyncio.run(coordinator.execute(ctx))

    print()
    print(f"  状態      : {result['status']}")
    print(f"  所要      : {result['duration_seconds']} 秒")
    print(f"  成果物    : {result.get('final_path') or '(無し)'}")
    print(f"  プレビュー: {result.get('preview_path') or '(無し)'}")
    print(f"  品質      : {result.get('quality_score')}")
    if result["health"]["skipped_features"]:
        print(f"  落ちた工程: {', '.join(result['health']['skipped_features'])}")
    for w in result["health"]["warnings"]:
        print(f"  ⚠ {w}")
    if result.get("error"):
        print(f"  🚫 {result['error']}")
    return 0 if result["status"] in (STATUS_COMPLETED, STATUS_DEGRADED) else 1


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(main())
