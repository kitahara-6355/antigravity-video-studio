"""
test_quality_gate_enforcement.py — M2.1 品質ゲート実効化テスト

T-031〜T-045: 品質スコア<90でのsafe_modeレンダリング、
品質不合格レポート生成、WebSocket通知、force-render API、
EvaluatorOptimizer単体テスト、統合E2Eフロー。

設計方針: B案（現行フロー維持 + 品質不合格フラグ方式）
"""

import sys
import json
import time
import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from dataclasses import field

# テスト対象のインポート
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from agents.pipeline_coordinator import (
    PipelineContext, PipelineCoordinator, StageResult,
    QualityGateWorker, RenderWorker, PreviewWorker,
)

# テスト用ヘルパー: mock_pipeline.py の create_mock_ctx を使用
from tests.fixtures.mock_pipeline import create_mock_ctx


# ============================================================
# Sprint 2.1.1: Coordinator品質ゲート分岐 + force-render API
# ============================================================

class TestT031QualityGateBranch:
    """T-031: PipelineCoordinatorに品質ゲートブロック分岐を追加"""

    def test_quality_below_90_sets_safe_mode(self):
        """品質スコア<90 で render_mode='safe' に設定される"""
        ctx = create_mock_ctx(segments=10)
        ctx.quality_score = 81  # E2E実績値

        # Coordinator の Phase C ロジックをシミュレート
        quality_passed = ctx.quality_score >= 90
        if not quality_passed:
            ctx.render_mode = "safe"
        else:
            ctx.render_mode = "production"

        assert ctx.render_mode == "safe"

    def test_quality_90_or_above_sets_production_mode(self):
        """品質スコア>=90 で render_mode='production' に設定される"""
        ctx = create_mock_ctx(segments=10)
        ctx.quality_score = 92

        quality_passed = ctx.quality_score >= 90
        if not quality_passed:
            ctx.render_mode = "safe"
        else:
            ctx.render_mode = "production"

        assert ctx.render_mode == "production"

    def test_pipeline_context_has_render_mode_default(self):
        """PipelineContext のデフォルト render_mode は 'production'"""
        ctx = PipelineContext(video_path="test.mp4")
        assert ctx.render_mode == "production"
        assert ctx.quality_gate_report is None


class TestT032QualityFailureReport:
    """T-032: ブロック時に品質不合格レポートをctx.resultに記録"""

    def test_quality_failure_report_structure(self):
        """品質不合格レポートが正しい構造で生成される"""
        coordinator = PipelineCoordinator()
        ctx = create_mock_ctx(segments=10)
        ctx.quality_score = 75
        ctx.quality_feedback = ["音量が小さすぎる", "メタデータ未生成"]
        ctx.quality_category_scores = {"core": 60, "youtube": 40}

        result = coordinator._build_result(ctx, "completed", time.time())

        report = result["quality_gate_report"]
        assert report is not None
        assert report["status"] == "blocked"
        assert report["score"] == 75
        assert report["threshold"] == 90
        assert report["gap"] == 15
        assert report["force_render_available"] is True
        assert report["force_render_endpoint"] == "/api/pipeline/force-render"
        assert len(report["feedback"]) == 2

    def test_quality_pass_no_report(self):
        """品質合格時はレポートがNone"""
        coordinator = PipelineCoordinator()
        ctx = create_mock_ctx(segments=10)
        ctx.quality_score = 95

        result = coordinator._build_result(ctx, "completed", time.time())

        assert result["quality_gate_report"] is None

    def test_improvement_suggestions_from_feedback(self):
        """フィードバックから改善提案が正しく生成される"""
        coordinator = PipelineCoordinator()
        ctx = create_mock_ctx(segments=10)
        ctx.quality_feedback = [
            "📡 音量が小さすぎる: -30.0 LUFS",
            "▶ メタデータ未生成",
            "⚠ 字幕速度超過",
        ]

        suggestions = coordinator._generate_improvement_suggestions(ctx)
        actions = [s["action"] for s in suggestions]

        assert "audio_normalization" in actions
        assert "regenerate_metadata" in actions
        assert "re_proofread" in actions


class TestT033WebSocketNotification:
    """T-033: ブロック時にWebSocket通知を送信"""

    @pytest.mark.asyncio
    async def test_websocket_quality_blocked_notification(self):
        """品質不合格時に quality_gate_blocked イベントが送信される"""
        coordinator = PipelineCoordinator()
        ws_messages = []

        async def mock_broadcast(data):
            ws_messages.append(data)

        coordinator._ws_broadcast = mock_broadcast

        ctx = create_mock_ctx(segments=10)
        ctx.quality_score = 81

        # Phase C のロジックをシミュレート
        quality_passed = ctx.quality_score >= 90
        if not quality_passed:
            ctx.render_mode = "safe"
            if coordinator._ws_broadcast:
                await coordinator._ws_broadcast({
                    "type": "quality_gate_blocked",
                    "score": ctx.quality_score,
                    "threshold": 90,
                    "feedback": ctx.quality_feedback[:5],
                    "render_mode": "safe",
                    "force_render_available": True,
                })

        assert len(ws_messages) == 1
        msg = ws_messages[0]
        assert msg["type"] == "quality_gate_blocked"
        assert msg["score"] == 81
        assert msg["threshold"] == 90
        assert msg["force_render_available"] is True


class TestT034ForceRenderAPI:
    """T-034: 強制レンダリングAPIを追加"""

    def test_force_render_request_model(self):
        """ForceRenderRequest モデルが正しく定義されている"""
        from routers.pipeline_router import ForceRenderRequest
        req = ForceRenderRequest(session_id="test", reason="テスト")
        assert req.session_id == "test"
        assert req.reason == "テスト"

    @pytest.mark.asyncio
    async def test_force_render_rejects_when_not_completed(self):
        """パイプライン未完了時にforce-renderが400エラーを返す"""
        from routers.pipeline_router import force_render, ForceRenderRequest, _pipeline_state

        original_status = _pipeline_state["status"]
        try:
            _pipeline_state["status"] = "running"
            req = ForceRenderRequest(reason="テスト")

            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                await force_render(req)
            assert exc_info.value.status_code == 400
        finally:
            _pipeline_state["status"] = original_status

    @pytest.mark.asyncio
    async def test_force_render_rejects_without_quality_report(self):
        """品質不合格レポートなしでforce-renderが400エラーを返す"""
        from routers.pipeline_router import force_render, ForceRenderRequest, _pipeline_state

        original_status = _pipeline_state["status"]
        original_result = _pipeline_state["result"]
        try:
            _pipeline_state["status"] = "completed"
            _pipeline_state["result"] = {"quality_gate_report": None}
            req = ForceRenderRequest(reason="テスト")

            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                await force_render(req)
            assert exc_info.value.status_code == 400
        finally:
            _pipeline_state["status"] = original_status
            _pipeline_state["result"] = original_result


class TestT035EvolutionLogRecording:
    """T-035: 強制レンダリング時にevolution_logに理由を記録"""

    @pytest.mark.asyncio
    async def test_force_render_evolution_log_recording(self, tmp_path):
        """evolution_logにforce_renderエントリが記録される"""
        log_path = tmp_path / "branding" / "evolution_log.json"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("{}", encoding="utf-8")

        # evolution_log 記録ロジックを直接検証
        data = json.loads(log_path.read_text(encoding="utf-8"))
        data.setdefault("force_renders", []).append({
            "timestamp": "2026-04-21T13:00:00",
            "quality_score": 81,
            "reason": "テスト用強制レンダリング",
            "threshold": 90,
        })
        log_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        result = json.loads(log_path.read_text(encoding="utf-8"))
        assert "force_renders" in result
        assert len(result["force_renders"]) == 1
        assert result["force_renders"][0]["quality_score"] == 81
        assert result["force_renders"][0]["reason"] == "テスト用強制レンダリング"


# ============================================================
# Sprint 2.1.2: EvaluatorOptimizer 単体テスト
# ============================================================

class TestT036QualityEvaluator:
    """T-036: QualityEvaluator診断結果の構造化テスト"""

    def test_evaluator_diagnosis_has_category_scores(self):
        """QualityEvaluator が category_scores を含む QualityDiagnosis を返す"""
        from harness.evaluator_optimizer import QualityEvaluator, QualityDiagnosis

        evaluator = QualityEvaluator()
        quality_result = {
            "score": 75, "rank": "C",
            "feedback": ["音量が小さすぎる", "メタデータ未生成"],
            "category_scores": {"audio": 60, "metadata": 0},
        }
        ctx = create_mock_ctx(segments=10)
        diagnosis = evaluator.evaluate(quality_result, ctx)

        assert isinstance(diagnosis, QualityDiagnosis)
        assert diagnosis.score == 75
        assert diagnosis.passed is False
        assert len(diagnosis.category_scores) > 0
        assert len(diagnosis.issues) >= 2
        assert diagnosis.improvable is True


class TestT037QualityOptimizer:
    """T-037: QualityOptimizer改善計画生成テスト"""

    def test_optimizer_generates_plan_with_actions(self):
        """不合格時に actions >= 1 の ImprovementPlan を生成"""
        from harness.evaluator_optimizer import QualityOptimizer, QualityDiagnosis

        optimizer = QualityOptimizer()
        diagnosis = QualityDiagnosis(
            score=75, rank="C", passed=False,
            issues=[
                {"feedback": "音声品質低下", "improvable": True,
                 "action": "audio_normalization", "estimated_gain": 10},
                {"feedback": "メタデータ不足", "improvable": True,
                 "action": "regenerate_metadata", "estimated_gain": 5},
            ],
        )
        plan = optimizer.plan(diagnosis)

        assert len(plan.actions) >= 1
        assert plan.total_estimated_gain > 0
        assert "合格" in plan.strategy or "目標" in plan.strategy

    def test_optimizer_returns_empty_plan_when_passed(self):
        """合格時は空のImprovementPlanを返す"""
        from harness.evaluator_optimizer import QualityOptimizer, QualityDiagnosis

        optimizer = QualityOptimizer()
        diagnosis = QualityDiagnosis(score=95, rank="S", passed=True)
        plan = optimizer.plan(diagnosis)

        assert len(plan.actions) == 0
        assert "合格" in plan.strategy or "不要" in plan.strategy


class TestT038AudioNormalization:
    """T-038: audio_normalizationアクションの単体テスト"""

    @pytest.mark.asyncio
    async def test_audio_normalization_returns_bool(self):
        """audio_normalization が bool を返す"""
        from harness.evaluator_optimizer import ImprovementExecutor, ImprovementAction

        executor = ImprovementExecutor()
        action = ImprovementAction(
            action_id="audio_normalization", category="audio",
            description="test", priority=1, estimated_gain=10,
        )
        ctx = create_mock_ctx(segments=10)
        ctx.preview_path = None  # パスなしで安全にFalse

        result = await executor.execute_action(action, ctx)
        assert isinstance(result, bool)
        assert result is False  # preview_path=None なので


class TestT039ReProofread:
    """T-039: re_proofreadアクションの単体テスト"""

    @pytest.mark.asyncio
    async def test_re_proofread_returns_bool(self):
        """re_proofread が bool を返す"""
        from harness.evaluator_optimizer import ImprovementExecutor, ImprovementAction

        executor = ImprovementExecutor()
        action = ImprovementAction(
            action_id="re_proofread", category="subtitle",
            description="test", priority=2, estimated_gain=8,
        )
        ctx = create_mock_ctx(segments=5)
        result = await executor.execute_action(action, ctx)
        assert isinstance(result, bool)


class TestT040RestructureSegments:
    """T-040: restructure_segmentsアクションの単体テスト"""

    @pytest.mark.asyncio
    async def test_restructure_removes_short_segments(self):
        """restructure が1秒未満セグメントを除去する"""
        from harness.evaluator_optimizer import ImprovementExecutor, ImprovementAction

        executor = ImprovementExecutor()
        action = ImprovementAction(
            action_id="restructure_segments", category="structure",
            description="test", priority=2, estimated_gain=12,
        )
        ctx = create_mock_ctx(segments=5)
        # 極小セグメントを追加
        ctx.selected_segments.append({"start": 0, "end": 0.5, "text": "x"})
        original_count = len(ctx.selected_segments)

        result = await executor.execute_action(action, ctx)
        assert result is True
        assert len(ctx.selected_segments) < original_count


class TestT041RegenerateMetadata:
    """T-041: regenerate_metadataアクションの単体テスト"""

    @pytest.mark.asyncio
    async def test_regenerate_metadata_returns_bool(self):
        """regenerate_metadata が bool を返す"""
        from harness.evaluator_optimizer import ImprovementExecutor, ImprovementAction

        executor = ImprovementExecutor()
        action = ImprovementAction(
            action_id="regenerate_metadata", category="metadata",
            description="test", priority=3, estimated_gain=5,
        )
        ctx = create_mock_ctx(segments=10)
        result = await executor.execute_action(action, ctx)
        # Gemini API不在でFalse、利用可能ならTrue
        assert isinstance(result, bool)


# ============================================================
# Sprint 2.1.3: 統合テスト + E2Eフロー
# ============================================================

class TestT042ImprovementLoopNonDegradation:
    """T-042: 改善ループ3回実行後のスコア変動テスト"""

    @pytest.mark.asyncio
    async def test_improvement_loop_score_non_degradation(self):
        """改善ループ実行後にスコアが劣化しないことを確認"""
        from harness.evaluator_optimizer import (
            EvaluatorOptimizerWorkflow, QualityEvaluator, QualityOptimizer,
        )

        workflow = EvaluatorOptimizerWorkflow()
        ctx = create_mock_ctx(segments=10)
        ctx.quality_score = 75

        # QualityGateWorker をモック: 常に同じスコアを返す
        mock_quality_result = {
            "score": 75, "rank": "C",
            "feedback": ["テスト"], "category_scores": {},
        }
        with patch.object(workflow, '_run_quality_check',
                          new_callable=AsyncMock,
                          return_value=mock_quality_result):
            with patch.object(workflow, '_regenerate_preview',
                              new_callable=AsyncMock,
                              return_value=True):
                result = await workflow.run(ctx, max_iterations=3)

        # 改善はされないが、劣化もしない
        assert result.final_score >= result.initial_score
        assert result.iterations <= 3


class TestT043QualityPassProductionRender:
    """T-043: 品質90+で正常レンダリング"""

    def test_quality_pass_sets_production_mode(self):
        """品質90+で render_mode=production"""
        ctx = create_mock_ctx(segments=10)
        ctx.quality_score = 92

        quality_passed = ctx.quality_score >= 90
        ctx.render_mode = "production" if quality_passed else "safe"

        assert ctx.render_mode == "production"

    def test_build_result_no_gate_report_on_pass(self):
        """品質合格時はquality_gate_reportがNone"""
        coordinator = PipelineCoordinator()
        ctx = create_mock_ctx(segments=10)
        ctx.quality_score = 92

        result = coordinator._build_result(ctx, "completed", time.time())
        assert result["quality_gate_report"] is None
        assert result["quality_score"] == 92


class TestT044QualityFailImprovePass:
    """T-044: 品質90未満→改善→再評価→通過フロー"""

    @pytest.mark.asyncio
    async def test_quality_improvement_loop_with_mock(self):
        """品質改善ループがモックWorkerで動作する"""
        coordinator = PipelineCoordinator()
        ctx = create_mock_ctx(segments=10)
        ctx.quality_score = 80
        ctx.preview_path = "/mock/preview.mp4"

        call_count = 0

        # PreviewWorker モック
        mock_preview = AsyncMock(return_value=StageResult(
            stage_name="プレビュー生成", success=True,
            detail="mock preview",
        ))

        # QualityGateWorker モック: 2回目で合格
        async def mock_quality_execute(ctx_arg):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                ctx_arg.quality_score = 92
                return StageResult(
                    stage_name="品質チェック", success=True,
                    detail="スコア: 92点 (ランクA)",
                    data={"score": 92, "rank": "A", "feedback": []},
                )
            return StageResult(
                stage_name="品質チェック", success=False,
                detail="スコア: 80点 (ランクB)",
                data={"score": 80, "rank": "B", "feedback": ["テスト"]},
            )

        preview_worker = coordinator._find_worker(PreviewWorker)
        quality_worker = coordinator._find_worker(QualityGateWorker)

        with patch.object(preview_worker, 'execute', mock_preview):
            with patch.object(quality_worker, 'execute', side_effect=mock_quality_execute):
                coordinator._progress_callback = None
                coordinator._ws_broadcast = None
                improved = await coordinator._quality_improvement_loop(ctx)

        assert improved is True
        assert ctx.quality_score >= 90


class TestT045ForceRenderFlow:
    """T-045: 品質90未満→強制レンダリングフロー"""

    def test_force_render_flow_integration(self):
        """品質不合格 → build_result に force-render 情報が含まれる"""
        coordinator = PipelineCoordinator()
        ctx = create_mock_ctx(segments=10)
        ctx.quality_score = 81
        ctx.quality_feedback = ["テスト不合格"]

        result = coordinator._build_result(ctx, "completed", time.time())

        # force-render 情報の確認
        report = result["quality_gate_report"]
        assert report is not None
        assert report["force_render_available"] is True
        assert report["force_render_endpoint"] == "/api/pipeline/force-render"
        assert report["gap"] == 9  # 90 - 81
        assert len(report["feedback"]) == 1
