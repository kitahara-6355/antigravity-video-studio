import pytest
import sys
from pathlib import Path

# プロジェクトのルートディレクトリと backend ディレクトリを PYTHONPATH に追加
project_root = str(Path(__file__).parent.parent.resolve())
backend_dir = str(Path(__file__).parent.parent.resolve() / "backend")
if project_root not in sys.path:
    sys.path.insert(0, project_root)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from unittest.mock import MagicMock, patch, AsyncMock
from dataclasses import replace

# 対象モジュールのインポート
from backend.harness.evaluator_optimizer import (
    QualityDiagnosis,
    ImprovementAction,
    ImprovementPlan,
    OptimizationResult,
    QualityEvaluator,
    QualityOptimizer,
    ImprovementExecutor,
    EvaluatorOptimizerWorkflow,
    evaluator_optimizer
)

# PipelineContextのダミークラス
class DummyContext:
    def __init__(self):
        self.preview_path = None
        self.segments = []
        self.selected_segments = []


def test_data_structures():
    """データ構造の基本テスト"""
    diagnosis = QualityDiagnosis(score=80, rank="B", passed=False)
    assert diagnosis.score == 80
    assert diagnosis.rank == "B"
    assert not diagnosis.passed
    assert diagnosis.improvable
    assert diagnosis.improvement_potential == 0

    action = ImprovementAction(
        action_id="act_01",
        category="audio",
        description="test action",
        priority=1,
        estimated_gain=10
    )
    assert action.action_id == "act_01"
    assert action.priority == 1

    plan = ImprovementPlan(strategy="Strategy A")
    assert plan.strategy == "Strategy A"
    assert len(plan.actions) == 0

    result = OptimizationResult(initial_score=80, final_score=90, iterations=1)
    assert result.initial_score == 80
    assert result.final_score == 90
    assert result.iterations == 1
    assert not result.success


def test_quality_evaluator_evaluate():
    """QualityEvaluatorの診断テスト"""
    evaluator = QualityEvaluator()
    ctx = DummyContext()

    # パスするケース (score >= 90)
    res_passed = {
        "score": 92,
        "rank": "S",
        "feedback": ["良好な音声品質"],
        "category_scores": {"audio_quality": 95}
    }
    diag = evaluator.evaluate(res_passed, ctx)
    assert diag.passed
    assert diag.score == 92
    assert diag.rank == "S"

    # パスしないケースで、改善可能な問題が含まれる
    res_failed = {
        "score": 80,
        "rank": "B",
        "feedback": ["音声のラウドネスが低い", "字幕テキストに誤字"],
        "category_scores": {"audio_quality": 85, "subtitle_accuracy": 88}
    }
    diag = evaluator.evaluate(res_failed, ctx)
    assert not diag.passed
    assert diag.score == 80
    assert diag.improvable
    # audio(10) + subtitle(8) = 18.
    assert diag.improvement_potential == 18
    assert len(diag.issues) == 2
    assert diag.issues[0]["category"] == "audio"
    assert diag.issues[0]["action"] == "audio_normalization"
    assert diag.issues[1]["category"] == "subtitle"
    assert diag.issues[1]["action"] == "re_proofread"

    # カテゴリスコアが 70 未満のときの追加問題検出
    res_low_score = {
        "score": 75,
        "rank": "C",
        "feedback": ["構成バランス調整"],
        "category_scores": {"structure_balance": 50}
    }
    diag = evaluator.evaluate(res_low_score, ctx)
    assert len(diag.issues) == 2
    assert diag.issues[0]["category"] == "structure"
    assert diag.issues[1]["category"] == "structure"

    # 全カテゴリのキーワードマッピングの網羅テスト
    res_all_categories = {
        "score": 60,
        "rank": "C",
        "feedback": [
            "ラウドネスが低いです", # audio
            "校閲が必要です",       # subtitle
            "冗長なセグメントがあります", # structure
            "チャプターを追加してください", # metadata
            "フォーマットが正しくありません", # file
            "不明なフィードバック"  # unknown
        ],
        "category_scores": {}
    }
    diag_all = evaluator.evaluate(res_all_categories, ctx)
    assert len(diag_all.issues) == 6
    assert diag_all.issues[0]["category"] == "audio"
    assert diag_all.issues[1]["category"] == "subtitle"
    assert diag_all.issues[2]["category"] == "structure"
    assert diag_all.issues[3]["category"] == "metadata"
    assert diag_all.issues[4]["category"] == "file"
    assert diag_all.issues[5]["category"] == "unknown"


def test_quality_optimizer_plan():
    """QualityOptimizerの改善計画テスト"""
    optimizer = QualityOptimizer()

    # 既に合格している場合
    passed_diag = QualityDiagnosis(score=95, rank="S", passed=True)
    plan = optimizer.plan(passed_diag)
    assert len(plan.actions) == 0
    assert "合格済み" in plan.strategy

    # 不合格時のプランニング
    issues = [
        {"feedback": "low audio", "category": "audio", "improvable": True, "action": "audio_normalization", "estimated_gain": 10},
        {"feedback": "typo", "category": "subtitle", "improvable": True, "action": "re_proofread", "estimated_gain": 8},
        {"feedback": "bad structure", "category": "structure", "improvable": True, "action": "restructure_segments", "estimated_gain": 12},
        # 重複するアクション
        {"feedback": "another low audio", "category": "audio", "improvable": True, "action": "audio_normalization", "estimated_gain": 10},
        # 改善不可のアクション
        {"feedback": "missing file", "category": "file", "improvable": False, "action": "manual_fix", "estimated_gain": 0},
    ]
    diag = QualityDiagnosis(score=70, rank="C", passed=False, issues=issues, improvable=True)
    plan = optimizer.plan(diag)

    assert len(plan.actions) == 3
    assert plan.actions[0].action_id == "audio_normalization"
    assert plan.actions[1].action_id == "restructure_segments"
    assert plan.actions[2].action_id == "re_proofread"
    assert plan.total_estimated_gain == 30
    assert "合格到達可能" in plan.strategy


@pytest.mark.asyncio
async def test_improvement_executor_unknown_action():
    """未知のアクションおよび例外ハンドラ (TD-449) のテスト"""
    executor = ImprovementExecutor()
    ctx = DummyContext()
    action = ImprovementAction(
        action_id="unknown_action_id",
        category="audio",
        description="unknown",
        priority=3,
        estimated_gain=5
    )
    res = await executor.execute_action(action, ctx)
    assert not res

    # 例外発生時のハンドリング (TD-449 のカバー - Exception)
    # _action_handlersの中のハンドラ自体が例外を投げるように設定
    action_known = ImprovementAction(
        action_id="audio_normalization",
        category="audio",
        description="normal",
        priority=1,
        estimated_gain=10
    )
    mock_err_handler = AsyncMock(side_effect=RuntimeError("FFmpeg critical crash"))
    with patch.dict(executor._action_handlers, {"audio_normalization": mock_err_handler}):
        res_err = await executor.execute_action(action_known, ctx)
        assert not res_err

    # インポートエラー発生時のハンドリング (TD-449 のカバー - ImportError)
    mock_imp_handler = AsyncMock(side_effect=ImportError("Failed to import engine"))
    with patch.dict(executor._action_handlers, {"audio_normalization": mock_imp_handler}):
        res_imp = await executor.execute_action(action_known, ctx)
        assert not res_imp


@pytest.mark.asyncio
async def test_action_restructure_segments():
    """restructure_segments アクションのテスト"""
    executor = ImprovementExecutor()
    ctx = DummyContext()

    # 1. selected_segments が空のとき
    assert not await executor.execute_action(
        ImprovementAction("restructure_segments", "structure", "desc", 2, 12), ctx
    )

    # 2. 有効なセグメントが含まれ、かつ削除対象がある場合
    ctx.selected_segments = [
        {"start": 0.0, "end": 2.0, "text": "Valid segment"},
        {"start": 2.0, "end": 2.5, "text": "Too short"},
        {"start": 2.5, "end": 5.0, "text": ""},
        {"start": 5.0, "end": 7.0, "text": "   "},
        {"start": 7.0, "end": 9.0, "text": "Another valid"},
    ]

    res = await executor.execute_action(
        ImprovementAction("restructure_segments", "structure", "desc", 2, 12), ctx
    )
    assert res
    assert len(ctx.selected_segments) == 2

    # 3. 削除対象のセグメントがなく、単に False を返すケース (Line 466 のカバー)
    ctx.selected_segments = [
        {"start": 0.0, "end": 2.0, "text": "Valid segment"},
        {"start": 2.0, "end": 5.0, "text": "Another valid"},
    ]
    res_no_change = await executor.execute_action(
        ImprovementAction("restructure_segments", "structure", "desc", 2, 12), ctx
    )
    assert not res_no_change


@pytest.mark.asyncio
async def test_action_re_proofread():
    """re_proofread アクションのテスト"""
    executor = ImprovementExecutor()
    ctx = DummyContext()

    # 1. segments が空のとき
    assert not await executor.execute_action(
        ImprovementAction("re_proofread", "subtitle", "desc", 2, 8), ctx
    )

    # 2. segments があり、辞書適用で修正がある場合
    ctx.segments = [
        {"text": "これはテストです。"}
    ]

    dummy_apply = MagicMock(return_value=("これはテスト（修正）です。", ["テスト"]))
    with patch.dict("sys.modules", {"proper_noun_dict": MagicMock(apply_dictionary=dummy_apply)}):
        res = await executor.execute_action(
            ImprovementAction("re_proofread", "subtitle", "desc", 2, 8), ctx
        )
        assert res
        assert ctx.segments[0]["text"] == "これはテスト（修正）です。"

    # 3. 修正がない場合
    ctx.segments = [
        {"text": "修正なし"}
    ]
    dummy_apply_no_corr = MagicMock(return_value=("修正なし", []))
    with patch.dict("sys.modules", {"proper_noun_dict": MagicMock(apply_dictionary=dummy_apply_no_corr)}):
        res = await executor.execute_action(
            ImprovementAction("re_proofread", "subtitle", "desc", 2, 8), ctx
        )
        assert not res

    # 4. 例外発生ケースのテスト (Line 439-440 のカバー)
    ctx.segments = [{"text": "エラーテスト"}]
    with patch.dict("sys.modules", {"proper_noun_dict": None}):  # インポートエラーを誘発
        res_ex = await executor.execute_action(
            ImprovementAction("re_proofread", "subtitle", "desc", 2, 8), ctx
        )
        assert not res_ex


@pytest.mark.asyncio
async def test_action_audio_normalization(tmp_path):
    """audio_normalization アクションのテスト"""
    executor = ImprovementExecutor()
    ctx = DummyContext()

    # 1. preview_path が存在しないとき
    assert not await executor.execute_action(
        ImprovementAction("audio_normalization", "audio", "desc", 1, 10), ctx
    )

    # 2. preview_path が存在するが ffmpeg が利用不可のとき
    dummy_preview = tmp_path / "preview.mp4"
    dummy_preview.write_text("dummy video content")
    ctx.preview_path = str(dummy_preview)

    mock_ffmpeg = MagicMock()
    mock_ffmpeg.is_available.return_value = False
    mock_video_editor = MagicMock(ffmpeg=mock_ffmpeg)

    with patch.dict("sys.modules", {"video_editor_engine": MagicMock(video_editor=mock_video_editor)}):
        res = await executor.execute_action(
            ImprovementAction("audio_normalization", "audio", "desc", 1, 10), ctx
        )
        assert not res

    # 3-A. ffmpeg が利用可能で run_command が成功し、一時ファイルが生成されたとき
    mock_ffmpeg.is_available.return_value = True
    def create_temp_file(*args, **kwargs):
        norm_path = Path(ctx.preview_path + ".norm.mp4")
        norm_path.write_text("normalized content")
        return True, "success"

    mock_ffmpeg.run_command.side_effect = create_temp_file

    with patch.dict("sys.modules", {"video_editor_engine": MagicMock(video_editor=mock_video_editor)}):
        res = await executor.execute_action(
            ImprovementAction("audio_normalization", "audio", "desc", 1, 10), ctx
        )
        assert res
        assert dummy_preview.read_text() == "normalized content"
        assert not Path(ctx.preview_path + ".norm.mp4").exists()

    # 3-B. ffmpeg が利用可能で run_command は成功したが、一時ファイルが生成されなかったとき
    mock_ffmpeg.run_command.side_effect = None
    mock_ffmpeg.run_command.return_value = (True, "success but missing file")
    dummy_preview.write_text("dummy video content")

    with patch.dict("sys.modules", {"video_editor_engine": MagicMock(video_editor=mock_video_editor)}):
        res_missing = await executor.execute_action(
            ImprovementAction("audio_normalization", "audio", "desc", 1, 10), ctx
        )
        assert not res_missing
        assert dummy_preview.read_text() == "dummy video content"

    # 4. run_command が失敗して temp_path の削除が発生するケース (Line 415-420 のカバー)
    mock_ffmpeg.run_command.side_effect = None
    mock_ffmpeg.run_command.return_value = (False, "error")
    # 一時ファイルを作成して失敗をシミュレート
    def fail_with_temp_file(*args, **kwargs):
        norm_path = Path(ctx.preview_path + ".norm.mp4")
        norm_path.write_text("failed normalization temp file")
        return False, "ffmpeg failure"
    mock_ffmpeg.run_command.side_effect = fail_with_temp_file

    with patch.dict("sys.modules", {"video_editor_engine": MagicMock(video_editor=mock_video_editor)}):
        res_fail = await executor.execute_action(
            ImprovementAction("audio_normalization", "audio", "desc", 1, 10), ctx
        )
        assert not res_fail
        # 一時ファイルが削除されていることを確認
        assert not Path(ctx.preview_path + ".norm.mp4").exists()

    # 5. インポートエラー等で例外が発生するケース
    with patch.dict("sys.modules", {"video_editor_engine": None}):
        res_ex = await executor.execute_action(
            ImprovementAction("audio_normalization", "audio", "desc", 1, 10), ctx
        )
        assert not res_ex


@pytest.mark.asyncio
async def test_action_regenerate_metadata():
    """regenerate_metadata アクションのテスト"""
    executor = ImprovementExecutor()
    ctx = DummyContext()

    # 1. YouTubeOptWorker.execute が成功するケース (success=True)
    mock_worker_inst = MagicMock()
    mock_worker_inst.execute = AsyncMock(return_value=MagicMock(success=True))
    mock_worker_class = MagicMock(return_value=mock_worker_inst)

    with patch.dict("sys.modules", {"agents.pipeline_coordinator": MagicMock(YouTubeOptWorker=mock_worker_class)}):
        res = await executor.execute_action(
            ImprovementAction("regenerate_metadata", "metadata", "desc", 3, 5), ctx
        )
        assert res

    # 2. YouTubeOptWorker.execute が失敗するケース (success=False)
    mock_worker_inst_fail = MagicMock()
    mock_worker_inst_fail.execute = AsyncMock(return_value=MagicMock(success=False))
    mock_worker_class_fail = MagicMock(return_value=mock_worker_inst_fail)

    with patch.dict("sys.modules", {"agents.pipeline_coordinator": MagicMock(YouTubeOptWorker=mock_worker_class_fail)}):
        res_fail = await executor.execute_action(
            ImprovementAction("regenerate_metadata", "metadata", "desc", 3, 5), ctx
        )
        assert not res_fail

    # 3. 例外発生ケースのテスト (Line 477-480 のカバー)
    with patch.dict("sys.modules", {"agents.pipeline_coordinator": None}):
        res_ex = await executor.execute_action(
            ImprovementAction("regenerate_metadata", "metadata", "desc", 3, 5), ctx
        )
        assert not res_ex


@pytest.mark.asyncio
async def test_workflow_run_success():
    """EvaluatorOptimizerWorkflow.run の正常系（合格）のテスト"""
    workflow = EvaluatorOptimizerWorkflow()
    ctx = DummyContext()

    mock_quality_check = AsyncMock(return_value={"score": 92, "rank": "S", "feedback": [], "category_scores": {}})
    with patch.object(workflow, "_run_quality_check", mock_quality_check):
        result = await workflow.run(ctx)
        assert result.success
        assert result.initial_score == 92
        assert result.final_score == 92
        assert result.iterations == 0


@pytest.mark.asyncio
async def test_workflow_run_improvement_loop():
    """EvaluatorOptimizerWorkflow.run で改善ループが回って合格するテスト"""
    workflow = EvaluatorOptimizerWorkflow()
    ctx = DummyContext()

    # イテレーションごとの品質スコア：初回75点、1回目改善後95点
    scores = [
        {"score": 75, "rank": "C", "feedback": ["音声のラウドネスが低い"], "category_scores": {}},
        {"score": 95, "rank": "S", "feedback": [], "category_scores": {}}
    ]
    mock_quality_check = AsyncMock(side_effect=scores)
    mock_regenerate = AsyncMock(return_value=True)
    mock_execute_action = AsyncMock(return_value=True)

    with patch.object(workflow, "_run_quality_check", mock_quality_check), \
         patch.object(workflow, "_regenerate_preview", mock_regenerate), \
         patch.object(workflow.executor, "execute_action", mock_execute_action):
        result = await workflow.run(ctx)
        assert result.success
        assert result.initial_score == 75
        assert result.final_score == 95
        assert result.iterations == 1
        assert len(result.improvements_applied) == 1

    # executable=False のアクションが含まれていて continue されるケース (Line 580 のカバー)
    ctx_non_exec = DummyContext()
    scores_non_exec = [
        {"score": 70, "rank": "C", "feedback": ["音声のラウドネスが低い"], "category_scores": {}},
        {"score": 70, "rank": "C", "feedback": ["音声のラウドネスが低い"], "category_scores": {}}
    ]
    mock_quality_check_non_exec = AsyncMock(side_effect=scores_non_exec)

    # AVAILABLE_ACTIONS を一時的に書き換えて executable=False にする
    mock_actions = {
        "audio_normalization": {
            "category": "audio",
            "description": "音声ラウドネスを正規化",
            "priority": 1,
            "estimated_gain": 20,
            "executable": False,
        }
    }

    with patch.object(workflow, "_run_quality_check", mock_quality_check_non_exec), \
         patch.object(workflow, "_regenerate_preview", mock_regenerate), \
         patch.object(workflow.executor, "execute_action", mock_execute_action), \
         patch.object(workflow.optimizer, "AVAILABLE_ACTIONS", mock_actions):
        result = await workflow.run(ctx_non_exec, max_iterations=1)
        # executable=Falseになったため、改善アクションが実行されず、
        # iterations は 1 だが success=False のまま早期終了する
        assert not result.success
        assert result.iterations == 1


@pytest.mark.asyncio
async def test_workflow_run_no_improvable_early_exit():
    """改善余地なし、またはスコア悪化による早期終了のテスト"""
    workflow = EvaluatorOptimizerWorkflow()
    ctx = DummyContext()

    # 1. 改善可能なアクションがない場合
    scores_no_action = [
        {"score": 80, "rank": "B", "feedback": ["改善不可能な問題"], "category_scores": {}}
    ]
    mock_quality_check = AsyncMock(side_effect=scores_no_action)
    with patch.object(workflow, "_run_quality_check", mock_quality_check):
        result = await workflow.run(ctx)
        assert not result.success
        assert result.iterations == 1

    # 2. 改善アクションを実行したが、再評価で改善不可と判定された場合（早期終了、Line 606-609のカバー）
    scores_no_improvable = [
        {"score": 80, "rank": "B", "feedback": ["音声のラウドネスが低い"], "category_scores": {}},
        {"score": 80, "rank": "B", "feedback": ["改善不可能な問題"], "category_scores": {}}
    ]
    mock_quality_check2 = AsyncMock(side_effect=scores_no_improvable)
    mock_regenerate = AsyncMock(return_value=True)
    mock_execute_action = AsyncMock(return_value=True)

    with patch.object(workflow, "_run_quality_check", mock_quality_check2), \
         patch.object(workflow, "_regenerate_preview", mock_regenerate), \
         patch.object(workflow.executor, "execute_action", mock_execute_action):
        result = await workflow.run(ctx)
        assert not result.success
        assert result.iterations == 1

    # 3. スコアが悪化した場合（早期終了、Line 610-616のカバー）
    scores_degraded = [
        {"score": 80, "rank": "B", "feedback": ["音声のラウドネスが低い"], "category_scores": {}},
        {"score": 75, "rank": "C", "feedback": ["音声のラウドネスが低い"], "category_scores": {}}
    ]
    mock_quality_check3 = AsyncMock(side_effect=scores_degraded)

    with patch.object(workflow, "_run_quality_check", mock_quality_check3), \
         patch.object(workflow, "_regenerate_preview", mock_regenerate), \
         patch.object(workflow.executor, "execute_action", mock_execute_action):
        result = await workflow.run(ctx)
        assert not result.success
        assert result.iterations == 1


@pytest.mark.asyncio
async def test_workflow_exceptions():
    """品質チェックやプレビュー生成で例外が発生したときのハンドリング (TD-450, TD-451)"""
    workflow = EvaluatorOptimizerWorkflow()
    ctx = DummyContext()

    # 1-A. _run_quality_check で例外発生 (TD-450 - Exception)
    mock_worker_inst = MagicMock()
    mock_worker_inst.execute = AsyncMock(side_effect=RuntimeError("QualityGate check failed"))
    mock_worker_class = MagicMock(return_value=mock_worker_inst)
    with patch("agents.pipeline_coordinator.QualityGateWorker", mock_worker_class):
        res_data = await workflow._run_quality_check(ctx)
        assert res_data["score"] == 0
        assert "QualityGate check failed" in res_data["feedback"][0]

    # 1-B. _run_quality_check でインポートエラー発生 (TD-450 - ImportError)
    mock_worker_inst_imp = MagicMock()
    mock_worker_inst_imp.execute = AsyncMock(side_effect=ImportError("Cannot import QualityGateWorker"))
    mock_worker_class_imp = MagicMock(return_value=mock_worker_inst_imp)
    with patch("agents.pipeline_coordinator.QualityGateWorker", mock_worker_class_imp):
        res_data_imp = await workflow._run_quality_check(ctx)
        assert res_data_imp["score"] == 0
        assert "ImportError" in res_data_imp["feedback"][0]

    # 2-A. _regenerate_preview で例外発生 (TD-451 - Exception)
    mock_preview_worker_inst = MagicMock()
    mock_preview_worker_inst.execute = AsyncMock(side_effect=RuntimeError("Preview generation failed"))
    mock_preview_worker_class = MagicMock(return_value=mock_preview_worker_inst)
    with patch("agents.pipeline_coordinator.PreviewWorker", mock_preview_worker_class):
        res_regen = await workflow._regenerate_preview(ctx)
        assert not res_regen

    # 2-B. _regenerate_preview でインポートエラー発生 (TD-451 - ImportError)
    mock_preview_worker_inst_imp = MagicMock()
    mock_preview_worker_inst_imp.execute = AsyncMock(side_effect=ImportError("Cannot import PreviewWorker"))
    mock_preview_worker_class_imp = MagicMock(return_value=mock_preview_worker_inst_imp)
    with patch("agents.pipeline_coordinator.PreviewWorker", mock_preview_worker_class_imp):
        res_regen_imp = await workflow._regenerate_preview(ctx)
        assert not res_regen_imp


@pytest.mark.asyncio
async def test_workflow_internal_methods_success():
    """_run_quality_check と _regenerate_preview の正常系パスをテスト"""
    workflow = EvaluatorOptimizerWorkflow()
    ctx = DummyContext()

    # 1. _run_quality_check の正常系 (Line 635 のカバー)
    mock_result_data = {"score": 95, "rank": "S", "feedback": [], "category_scores": {}}
    mock_worker_inst = MagicMock()
    mock_execute_res = MagicMock()
    mock_execute_res.data = mock_result_data
    mock_worker_inst.execute = AsyncMock(return_value=mock_execute_res)
    mock_worker_class = MagicMock(return_value=mock_worker_inst)

    with patch("agents.pipeline_coordinator.QualityGateWorker", mock_worker_class):
        res = await workflow._run_quality_check(ctx)
        assert res == mock_result_data

    # 2. _regenerate_preview の正常系 (Line 646 のカバー)
    mock_preview_worker_inst = MagicMock()
    mock_preview_res = MagicMock()
    mock_preview_res.success = True
    mock_preview_worker_inst.execute = AsyncMock(return_value=mock_preview_res)
    mock_preview_worker_class = MagicMock(return_value=mock_preview_worker_inst)

    with patch("agents.pipeline_coordinator.PreviewWorker", mock_preview_worker_class):
        res_regen = await workflow._regenerate_preview(ctx)
        assert res_regen is True


@pytest.mark.asyncio
async def test_action_thumbnail_optimize(tmp_path):
    """thumbnail_optimize アクションのテスト"""
    executor = ImprovementExecutor()
    ctx = DummyContext()

    # 1. thumbnail_path が設定されていない場合
    assert not await executor.execute_action(
        ImprovementAction("thumbnail_optimize", "thumbnail", "desc", 1, 15), ctx
    )

    # metadata から取得できる場合も確認
    ctx.metadata = {"thumbnail_path": None}
    assert not await executor.execute_action(
        ImprovementAction("thumbnail_optimize", "thumbnail", "desc", 1, 15), ctx
    )

    # 2. ファイルが存在しない場合（新規作成されるか）
    test_thumb_path = tmp_path / "new_thumb.png"
    ctx.thumbnail_path = str(test_thumb_path)
    res = await executor.execute_action(
        ImprovementAction("thumbnail_optimize", "thumbnail", "desc", 1, 15), ctx
    )
    assert res
    assert test_thumb_path.exists()

    # 画像の解像度チェック
    from PIL import Image
    with Image.open(test_thumb_path) as img:
        assert img.size == (1280, 720)

    # 3. サイズ・比率が異常な画像が与えられた場合（リサイズ＆クロップされるか）
    # 4:3 の 640x480 画像を作成
    bad_img = Image.new("RGB", (640, 480), color="red")
    bad_img.save(test_thumb_path)

    res = await executor.execute_action(
        ImprovementAction("thumbnail_optimize", "thumbnail", "desc", 1, 15), ctx
    )
    assert res
    with Image.open(test_thumb_path) as img:
        assert img.size == (1280, 720)

    # 横長すぎる 2:1 画像の場合のクロップ
    wide_img = Image.new("RGB", (1000, 500), color="blue")
    wide_img.save(test_thumb_path)
    res = await executor.execute_action(
        ImprovementAction("thumbnail_optimize", "thumbnail", "desc", 1, 15), ctx
    )
    assert res
    with Image.open(test_thumb_path) as img:
        assert img.size == (1280, 720)

    # 4. ファイルサイズが4MBを超える場合（段階的圧縮が動作するか - 圧縮成功）
    from unittest.mock import PropertyMock
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat_res = MagicMock()
        # PNG(5MB) -> q=90(5MB) -> q=80(3MB)
        type(mock_stat_res).st_size = PropertyMock(side_effect=[5 * 1024 * 1024, 5 * 1024 * 1024, 3 * 1024 * 1024])
        mock_stat.return_value = mock_stat_res
        
        res = await executor.execute_action(
            ImprovementAction("thumbnail_optimize", "thumbnail", "desc", 1, 15), ctx
        )
        assert res

    # 4-B. 段階的圧縮を全て試しても4MB未満にならない場合（圧縮失敗）
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat_res2 = MagicMock()
        type(mock_stat_res2).st_size = PropertyMock(return_value=5 * 1024 * 1024)
        mock_stat.return_value = mock_stat_res2
        
        res = await executor.execute_action(
            ImprovementAction("thumbnail_optimize", "thumbnail", "desc", 1, 15), ctx
        )
        assert not res

    # 5. 例外発生時のハンドリング
    with patch("PIL.Image.open", side_effect=OSError("Pillow crash")):
        res_ex = await executor.execute_action(
            ImprovementAction("thumbnail_optimize", "thumbnail", "desc", 1, 15), ctx
        )
        assert not res_ex
