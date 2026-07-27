import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

from backend.harness.evaluator_optimizer import (
    orchestrator_evaluator_optimizer,
    QualityEvaluator,
    QualityOptimizer,
    ImprovementExecutor,
    EvaluatorOptimizerWorkflow,
    QualityDiagnosis,
    ImprovementAction,
    ImprovementPlan,
    OptimizationResult,
    evaluator_optimizer
)
from backend.agents.orchestration.design_stock import DesignStockStore

@pytest.fixture
def temp_design_stock(tmp_path):
    """一時的な design_stock.json をセットアップする fixture"""
    stock_file = tmp_path / "design_stock.json"
    initial_data = {
        "config": {
            "target_stock_count": 10,
            "phases_ahead": 3,
            "stale_days_sa": 3,
            "stale_days_bc": 7
        },
        "stock_items": []
    }
    with open(stock_file, "w", encoding="utf-8") as f:
        json.dump(initial_data, f, indent=2)
    return str(stock_file)

@pytest.fixture
def mock_phase_state(tmp_path):
    """一時的な phase_state.json をモックする"""
    state_file = tmp_path / "phase_state.json"
    state_data = {
        "current_phase": 27,
        "metrics": {
            "coverage_pct": 85.0
        }
    }
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state_data, f, indent=2)
    return str(state_file)


def test_no_bottlenecks(temp_design_stock, mock_phase_state):
    """ボトルネックがない場合、設計ストックが追加されないことをテスト"""
    results = {"passed": 5, "failed": 0, "total": 5}
    report = {
        "batch_id": "batch_ok_001",
        "git_diff_summary": {"files_changed": 3}
    }

    # safe_read_json の phase_state 読込をパッチしてカバレッジを高水準にする
    with patch("backend.agents.orchestration.atomic_io.safe_read_json") as mock_read:
        # safe_read_json が呼ばれたら mock_phase_state の内容を返す
        def side_effect(path, default=None):
            if "phase_state.json" in path:
                return {"current_phase": 27, "metrics": {"coverage_pct": 85.0}}
            elif "design_stock.json" in path:
                with open(temp_design_stock, "r", encoding="utf-8") as f:
                    return json.load(f)
            return default or {}
        mock_read.side_effect = side_effect

        orchestrator_evaluator_optimizer.analyze_and_suggest(
            batch_id="batch_ok_001",
            results=results,
            report=report,
            store_path=temp_design_stock
        )

        store = DesignStockStore(temp_design_stock)
        assert len(store.items) == 0


def test_detect_failure_bottleneck(temp_design_stock):
    """タスク失敗を検知して設計ストックが自動起票されることをテスト"""
    results = {"passed": 3, "failed": 1, "total": 4}
    report = {
        "batch_id": "batch_fail_001",
        "git_diff_summary": {"files_changed": 2}
    }

    with patch("backend.agents.orchestration.atomic_io.safe_read_json") as mock_read:
        def side_effect(path, default=None):
            if "phase_state.json" in path:
                return {"current_phase": 27, "metrics": {"coverage_pct": 85.0}}
            elif "design_stock.json" in path:
                with open(temp_design_stock, "r", encoding="utf-8") as f:
                    return json.load(f)
            return default or {}
        mock_read.side_effect = side_effect

        orchestrator_evaluator_optimizer.analyze_and_suggest(
            batch_id="batch_fail_001",
            results=results,
            report=report,
            store_path=temp_design_stock
        )

        store = DesignStockStore(temp_design_stock)
        assert len(store.items) == 1
        item = store.items[0]
        assert "バッチ失敗に伴うデバッグ" in item["title"]
        assert item["difficulty"] == "C"
        assert item["status"] == "pending"


def test_detect_heavy_changes_bottleneck(temp_design_stock):
    """大規模ファイル変更を検知して設計ストックが自動起票されることをテスト"""
    results = {"passed": 5, "failed": 0, "total": 5}
    report = {
        "batch_id": "batch_heavy_001",
        "git_diff_summary": {"files_changed": 16}
    }

    with patch("backend.agents.orchestration.atomic_io.safe_read_json") as mock_read:
        def side_effect(path, default=None):
            if "phase_state.json" in path:
                return {"current_phase": 27, "metrics": {"coverage_pct": 85.0}}
            elif "design_stock.json" in path:
                with open(temp_design_stock, "r", encoding="utf-8") as f:
                    return json.load(f)
            return default or {}
        mock_read.side_effect = side_effect

        orchestrator_evaluator_optimizer.analyze_and_suggest(
            batch_id="batch_heavy_001",
            results=results,
            report=report,
            store_path=temp_design_stock
        )

        store = DesignStockStore(temp_design_stock)
        assert len(store.items) == 1
        item = store.items[0]
        assert "大規模変更タスク" in item["title"]
        assert item["difficulty"] == "B"
        assert item["status"] == "pending"


def test_detect_coverage_debt_bottleneck(temp_design_stock):
    """カバレッジ不足を検知して設計ストックが自動起票されることをテスト"""
    results = {"passed": 5, "failed": 0, "total": 5}
    report = {
        "batch_id": "batch_cov_001",
        "git_diff_summary": {"files_changed": 2}
    }

    with patch("backend.agents.orchestration.atomic_io.safe_read_json") as mock_read:
        def side_effect(path, default=None):
            if "phase_state.json" in path:
                # カバレッジ 25% (30%未満)
                return {"current_phase": 27, "metrics": {"coverage_pct": 25.0}}
            elif "design_stock.json" in path:
                with open(temp_design_stock, "r", encoding="utf-8") as f:
                    return json.load(f)
            return default or {}
        mock_read.side_effect = side_effect

        orchestrator_evaluator_optimizer.analyze_and_suggest(
            batch_id="batch_cov_001",
            results=results,
            report=report,
            store_path=temp_design_stock
        )

        store = DesignStockStore(temp_design_stock)
        assert len(store.items) == 1
        item = store.items[0]
        assert "未カバー領域" in item["title"]
        assert item["difficulty"] == "B"
        assert item["status"] == "pending"


def test_duplicate_prevention(temp_design_stock):
    """同じボトルネックの重複起票が防止されることをテスト"""
    results = {"passed": 3, "failed": 1, "total": 4}
    report = {
        "batch_id": "batch_fail_002",
        "git_diff_summary": {"files_changed": 2}
    }

    with patch("backend.agents.orchestration.atomic_io.safe_read_json") as mock_read:
        def side_effect(path, default=None):
            if "phase_state.json" in path:
                return {"current_phase": 27, "metrics": {"coverage_pct": 85.0}}
            elif "design_stock.json" in path:
                with open(temp_design_stock, "r", encoding="utf-8") as f:
                    return json.load(f)
            return default or {}
        mock_read.side_effect = side_effect

        # 1回目の起票
        orchestrator_evaluator_optimizer.analyze_and_suggest(
            batch_id="batch_fail_002",
            results=results,
            report=report,
            store_path=temp_design_stock
        )

        # 2回目の起票 (同じ失敗が再度検知される)
        orchestrator_evaluator_optimizer.analyze_and_suggest(
            batch_id="batch_fail_003",
            results=results,
            report=report,
            store_path=temp_design_stock
        )

        store = DesignStockStore(temp_design_stock)
        # 重複が防止されているため、アイテム数は 1 のはず
        assert len(store.items) == 1



# ============================================================
# QualityEvaluator テスト
# ============================================================

def test_quality_evaluator_classify_issues():
    evaluator = QualityEvaluator()
    feedback = [
        "音声ラウドネスが基準を超えています",
        "字幕テキストに誤字があります",
        "セグメント構成のバランスが悪いです",
        "メタデータにタイトルがありません",
        "ファイルが存在しません",
        "サムネイルの解像度が低いです",
        "未知のエラーが発生しました"
    ]
    category_scores = {
        "audio_quality": 60,  # 70未満なので要改善
        "structure_balance": 80,
    }
    
    # ダミーの context オブジェクト
    ctx = MagicMock()
    
    quality_result = {
        "score": 75,
        "rank": "B",
        "feedback": feedback,
        "category_scores": category_scores
    }
    
    diagnosis = evaluator.evaluate(quality_result, ctx)
    
    assert diagnosis.score == 75
    assert diagnosis.rank == "B"
    assert diagnosis.passed is False
    assert diagnosis.improvable is True
    
    # 改善可能性やアクションの分類をチェック
    issues = diagnosis.issues
    # feedback の各要素が正しく分類されているか
    categories = [i["category"] for i in issues]
    assert "audio" in categories
    assert "subtitle" in categories
    assert "structure" in categories
    assert "metadata" in categories
    assert "file" in categories
    assert "thumbnail" in categories
    assert "unknown" in categories
    
    # カテゴリスコア 70未満 (audio_quality) からの自動起票
    assert any("audio_quality スコア低下" in i["feedback"] for i in issues)

# ============================================================
# QualityOptimizer テスト
# ============================================================

def test_quality_optimizer_plan():
    optimizer = QualityOptimizer()
    
    # ケース1: 合格済みの場合
    passed_diagnosis = QualityDiagnosis(score=95, rank="S", passed=True)
    plan_passed = optimizer.plan(passed_diagnosis)
    assert plan_passed.total_estimated_gain == 0
    assert "合格済み" in plan_passed.strategy
    
    # ケース2: 不合格の場合
    issues = [
        {"feedback": "音声問題", "category": "audio", "improvable": True, "action": "audio_normalization", "estimated_gain": 10},
        {"feedback": "重複音声問題", "category": "audio", "improvable": True, "action": "audio_normalization", "estimated_gain": 10}, # 重複
        {"feedback": "字幕問題", "category": "subtitle", "improvable": True, "action": "re_proofread", "estimated_gain": 8},
        {"feedback": "改善不可能ファイル問題", "category": "file", "improvable": False, "action": "manual_fix", "estimated_gain": 0}, # 改善不可
    ]
    failed_diagnosis = QualityDiagnosis(
        score=75, rank="B", passed=False, issues=issues, improvable=True, improvement_potential=15
    )
    
    plan_failed = optimizer.plan(failed_diagnosis)
    
    # アクションは audio_normalization と re_proofread のみ (重複と改善不可は除外)
    assert len(plan_failed.actions) == 2
    action_ids = [a.action_id for a in plan_failed.actions]
    assert "audio_normalization" in action_ids
    assert "re_proofread" in action_ids
    
    # 優先度とゲイン
    assert plan_failed.actions[0].action_id == "audio_normalization"
    assert plan_failed.total_estimated_gain == 18
    assert "推定改善: +18pt" in plan_failed.strategy

# ============================================================
# ImprovementExecutor テスト
# ============================================================

@pytest.mark.asyncio
async def test_improvement_executor_execute_action():
    executor = ImprovementExecutor()
    ctx = MagicMock()
    
    # 未知のアクション
    action_unknown = ImprovementAction(
        action_id="unknown_action", category="unknown", description="test", priority=3, estimated_gain=0
    )
    success = await executor.execute_action(action_unknown, ctx)
    assert success is False

@pytest.mark.asyncio
async def test_action_audio_normalization(tmp_path):
    executor = ImprovementExecutor()
    ctx = MagicMock()
    
    # プレビューパスがない場合は失敗
    ctx.preview_path = None
    action = ImprovementAction(
        action_id="audio_normalization", category="audio", description="test", priority=1, estimated_gain=10
    )
    assert await executor.execute_action(action, ctx) is False
    
    # パスが存在しない場合も失敗
    ctx.preview_path = str(tmp_path / "nonexistent.mp4")
    assert await executor.execute_action(action, ctx) is False
    
    # パスが存在する場合
    preview_file = tmp_path / "preview.mp4"
    preview_file.write_text("dummy video")
    ctx.preview_path = str(preview_file)
    
    # ffmpeg モック
    mock_editor = MagicMock()
    mock_editor.ffmpeg.is_available.return_value = True
    
    # run_command が成功した場合
    mock_editor.ffmpeg.run_command.return_value = (True, "")
    
    # video_editor_engine からインポートされる video_editor をモック
    with patch("video_editor_engine.video_editor", mock_editor), \
         patch("shutil.move") as mock_move, \
         patch("pathlib.Path.exists", return_value=True):
        success = await executor.execute_action(action, ctx)
        assert success is True
        mock_move.assert_called_once()
        
    # run_command が失敗した場合
    mock_editor.ffmpeg.run_command.return_value = (False, "error")
    with patch("video_editor_engine.video_editor", mock_editor):
        # exists を True、ただし成否は False にして temp_path の削除を確認
        with patch("pathlib.Path.exists", side_effect=[True, True, True, True]), \
             patch("pathlib.Path.unlink") as mock_unlink:
            success = await executor.execute_action(action, ctx)
            assert success is False

@pytest.mark.asyncio
async def test_action_re_proofread():
    executor = ImprovementExecutor()
    ctx = MagicMock()
    
    # segments がない場合
    ctx.segments = None
    action = ImprovementAction(
        action_id="re_proofread", category="subtitle", description="test", priority=2, estimated_gain=8
    )
    assert await executor.execute_action(action, ctx) is False
    
    # segments がある場合
    ctx.segments = [{"text": "今日ハ晴れです"}]
    
    # proper_noun_dict モック
    mock_apply_dict = MagicMock(return_value=("今日は晴れです", ["ハ->は"]))
    with patch("proper_noun_dict.apply_dictionary", mock_apply_dict):
        success = await executor.execute_action(action, ctx)
        assert success is True
        assert ctx.segments[0]["text"] == "今日は晴れです"
        
    # 例外発生時
    with patch("proper_noun_dict.apply_dictionary", side_effect=Exception("mock error")):
        success = await executor.execute_action(action, ctx)
        assert success is False

@pytest.mark.asyncio
async def test_action_restructure_segments():
    executor = ImprovementExecutor()
    ctx = MagicMock()
    
    # selected_segments がない場合
    ctx.selected_segments = None
    action = ImprovementAction(
        action_id="restructure_segments", category="structure", description="test", priority=2, estimated_gain=12
    )
    assert await executor.execute_action(action, ctx) is False
    
    # 正常ケース: フィルタリング
    ctx.selected_segments = [
        {"start": 0.0, "end": 0.5, "text": "short"},  # 0.5秒なので削除
        {"start": 1.0, "end": 3.0, "text": ""},       # 空白テキストなので削除
        {"start": 3.0, "end": 5.0, "text": "valid"},  # キープ
    ]
    success = await executor.execute_action(action, ctx)
    assert success is True
    assert len(ctx.selected_segments) == 1
    assert ctx.selected_segments[0]["text"] == "valid"
    
    # 削除するものがない場合
    ctx.selected_segments = [{"start": 0.0, "end": 2.0, "text": "keep"}]
    success = await executor.execute_action(action, ctx)
    assert success is False

@pytest.mark.asyncio
async def test_action_regenerate_metadata():
    executor = ImprovementExecutor()
    ctx = MagicMock()
    action = ImprovementAction(
        action_id="regenerate_metadata", category="metadata", description="test", priority=3, estimated_gain=5
    )
    
    # 成功ケース
    mock_worker = MagicMock()
    mock_worker.execute = AsyncMock(return_value=MagicMock(success=True))
    with patch("agents.pipeline_coordinator.YouTubeOptWorker", return_value=mock_worker):
        success = await executor.execute_action(action, ctx)
        assert success is True
        
    # 失敗ケース (ImportError)
    with patch("agents.pipeline_coordinator.YouTubeOptWorker", side_effect=ImportError("mock")):
        success = await executor.execute_action(action, ctx)
        assert success is False

@pytest.mark.asyncio
async def test_action_thumbnail_optimize(tmp_path):
    executor = ImprovementExecutor()
    ctx = MagicMock()
    action = ImprovementAction(
        action_id="thumbnail_optimize", category="thumbnail", description="test", priority=1, estimated_gain=15
    )
    
    # パス未指定
    ctx.thumbnail_path = None
    ctx.metadata = {}
    assert await executor.execute_action(action, ctx) is False
    
    # 新規作成ケース
    thumb_file = tmp_path / "thumb.png"
    ctx.thumbnail_path = str(thumb_file)
    
    # PIL Image モック
    mock_img_new = MagicMock()
    with patch("PIL.Image.new", return_value=mock_img_new), \
         patch("PIL.Image.open") as mock_open:
        # ファイルがない場合は Image.new が呼ばれる
        success = await executor.execute_action(action, ctx)
        assert success is True
        mock_new_img_inst = mock_img_new
        mock_new_img_inst.save.assert_called_once()
        
    # 既存画像のリサイズおよび圧縮クオリティ低下ケース (aspect_ratio < target_ratio)
    thumb_file.write_text("dummy image data")
    
    mock_opened_img = MagicMock()
    mock_opened_img.__enter__.return_value = mock_opened_img
    mock_opened_img.size = (1920, 1200) # リサイズ必要 (aspect_ratio < target_ratio)
    mock_opened_img.crop.return_value = mock_opened_img
    mock_opened_img.resize.return_value = mock_opened_img
    
    # パス存在確認とサイズ確認のモック
    with patch("PIL.Image.open", return_value=mock_opened_img), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.stat") as mock_stat:
        
        # 1回目は 5MB (4MB超え)、2回目は 3MB (4MB未満)
        stat_5mb = MagicMock(st_size=5 * 1024 * 1024)
        stat_3mb = MagicMock(st_size=3 * 1024 * 1024)
        mock_stat.side_effect = [stat_5mb, stat_3mb]
        
        with patch("pathlib.Path.unlink") as mock_unlink, \
             patch("pathlib.Path.rename") as mock_rename:
            success = await executor.execute_action(action, ctx)
            assert success is True
            mock_opened_img.resize.assert_called_once()
            # クオリティ低下ループに入り、JPEG保存が試行されたはず
            mock_opened_img.convert.assert_called_once()
            mock_rename.assert_called_once()

    # 既存画像のリサイズケース (aspect_ratio > target_ratio)
    mock_opened_img_wide = MagicMock()
    mock_opened_img_wide.__enter__.return_value = mock_opened_img_wide
    mock_opened_img_wide.size = (2000, 1000) # aspect_ratio > target_ratio
    mock_opened_img_wide.crop.return_value = mock_opened_img_wide
    mock_opened_img_wide.resize.return_value = mock_opened_img_wide
    
    with patch("PIL.Image.open", return_value=mock_opened_img_wide), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.stat") as mock_stat:
        
        mock_stat.return_value = MagicMock(st_size=1 * 1024 * 1024) # 最初から4MB未満
        with patch("pathlib.Path.unlink") as mock_unlink, \
             patch("pathlib.Path.rename") as mock_rename:
            success = await executor.execute_action(action, ctx)
            assert success is True
            mock_opened_img_wide.crop.assert_called_once()
            mock_opened_img_wide.resize.assert_called_once()
            mock_rename.assert_called_once()

    # 圧縮に失敗し続けるケース
    mock_opened_img.convert.reset_mock()
    with patch("PIL.Image.open", return_value=mock_opened_img), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.stat") as mock_stat:
        mock_stat.side_effect = None
        mock_stat.return_value = MagicMock(st_size=5 * 1024 * 1024) # 常に5MB
        with patch("pathlib.Path.unlink") as mock_unlink, \
             patch("pathlib.Path.rename") as mock_rename:
            success = await executor.execute_action(action, ctx)
            assert success is False

# ============================================================
# EvaluatorOptimizerWorkflow テスト
# ============================================================

@pytest.mark.asyncio
async def test_workflow_run_immediate_pass():
    workflow = EvaluatorOptimizerWorkflow()
    ctx = MagicMock()
    
    # 初回で合格するケース
    initial_check = {"score": 92, "rank": "S", "feedback": [], "category_scores": {}}
    workflow._run_quality_check = AsyncMock(return_value=initial_check)
    
    result = await workflow.run(ctx)
    assert result.success is True
    assert result.initial_score == 92
    assert result.final_score == 92
    assert result.iterations == 0

@pytest.mark.asyncio
async def test_workflow_run_loop_success():
    workflow = EvaluatorOptimizerWorkflow()
    ctx = MagicMock()
    
    # 1回目のチェックは不合格、2回目で合格
    check_1 = {"score": 75, "rank": "B", "feedback": ["音声が小さい"], "category_scores": {"audio_quality": 60}}
    check_2 = {"score": 95, "rank": "S", "feedback": [], "category_scores": {"audio_quality": 95}}
    
    workflow._run_quality_check = AsyncMock(side_effect=[check_1, check_2])
    workflow._regenerate_preview = AsyncMock(return_value=True)
    
    # Executor は常に成功を返すようにモック
    workflow.executor.execute_action = AsyncMock(return_value=True)
    
    result = await workflow.run(ctx)
    assert result.success is True
    assert result.initial_score == 75
    assert result.final_score == 95
    assert result.iterations == 1
    assert len(result.improvements_applied) == 1

@pytest.mark.asyncio
async def test_workflow_run_loop_early_termination():
    workflow = EvaluatorOptimizerWorkflow()
    ctx = MagicMock()
    
    # 早期終了ケース1: 改善アクションがない場合
    # 改善不可のアクションのみ
    check_1 = {"score": 75, "rank": "B", "feedback": ["ファイル破損"], "category_scores": {"file_integrity": 50}}
    workflow._run_quality_check = AsyncMock(return_value=check_1)
    
    result = await workflow.run(ctx)
    assert result.success is False
    assert result.iterations == 1  # 計画段階でアクションなしと判断され終了
    
    # 早期終了ケース2: スコア悪化の場合
    # 改善を試みるが、2回目のスコアが下がる
    check_1 = {"score": 75, "rank": "B", "feedback": ["音声が小さい"], "category_scores": {"audio_quality": 60}}
    check_2 = {"score": 70, "rank": "B", "feedback": ["音声が非常に小さい"], "category_scores": {"audio_quality": 50}}
    
    workflow._run_quality_check = AsyncMock(side_effect=[check_1, check_2])
    workflow._regenerate_preview = AsyncMock(return_value=True)
    workflow.executor.execute_action = AsyncMock(return_value=True)
    
    result = await workflow.run(ctx)
    assert result.success is False
    assert result.iterations == 1 # 悪化により1イテレーションで終了
    assert result.final_score == 70

@pytest.mark.asyncio
async def test_workflow_error_handling():
    workflow = EvaluatorOptimizerWorkflow()
    ctx = MagicMock()
    
    # _run_quality_check での ImportError や例外発生
    with patch("agents.pipeline_coordinator.QualityGateWorker", side_effect=ImportError("mock import error")):
        res = await workflow._run_quality_check(ctx)
        assert res["score"] == 0
        assert "ImportError" in res["feedback"][0]
        
    with patch("agents.pipeline_coordinator.QualityGateWorker", side_effect=RuntimeError("unknown error")):
        res = await workflow._run_quality_check(ctx)
        assert res["score"] == 0
        assert "unknown error" in res["feedback"][0]

    # _regenerate_preview での ImportError や例外発生
    with patch("agents.pipeline_coordinator.PreviewWorker", side_effect=ImportError("mock import error")):
        res = await workflow._regenerate_preview(ctx)
        assert res is False
        
    with patch("agents.pipeline_coordinator.PreviewWorker", side_effect=RuntimeError("unknown error")):
        res = await workflow._regenerate_preview(ctx)
        assert res is False

# ============================================================
# OrchestratorEvaluatorOptimizer 例外ハンドリング テスト
# ============================================================

def test_orchestrator_exceptions(temp_design_stock):
    # _detect_coverage_debt で例外が発生しても analyze_and_suggest 全体は中断しないことを確認
    results = {"passed": 5, "failed": 0, "total": 5}
    report = {
        "batch_id": "batch_exc_001",
        "git_diff_summary": {"files_changed": 3}
    }
    
    with patch("backend.agents.orchestration.atomic_io.safe_read_json", side_effect=OSError("corrupt json")), \
         patch("backend.harness.evaluator_optimizer.logger") as mock_logger:
        
        orchestrator_evaluator_optimizer.analyze_and_suggest(
            batch_id="batch_exc_001",
            results=results,
            report=report,
            store_path=temp_design_stock
        )
        mock_logger.warning.assert_any_call("[Stage 3] カバレッジ測定データの読み込みに失敗しました: corrupt json")
        
    # _register_suggested_stock で例外が発生した場合も全体はクラッシュしない
    results_fail = {"passed": 3, "failed": 1, "total": 4} # 失敗を検知させて起票を試みさせる
    with patch("backend.harness.evaluator_optimizer.OrchestratorEvaluatorOptimizer._register_suggested_stock", side_effect=OSError("db error")), \
         patch("backend.harness.evaluator_optimizer.logger") as mock_logger:
         
        orchestrator_evaluator_optimizer.analyze_and_suggest(
            batch_id="batch_exc_002",
            results=results_fail,
            report=report,
            store_path=temp_design_stock
        )
        mock_logger.error.assert_any_call("❌ [Stage 3] 設計ストック起票に失敗しました: db error", exc_info=True)


@pytest.mark.asyncio
async def test_action_audio_normalization_exceptions(tmp_path):
    executor = ImprovementExecutor()
    ctx = MagicMock()
    action = ImprovementAction(
        action_id="audio_normalization", category="audio", description="test", priority=1, estimated_gain=10
    )
    
    # 正常なファイルパス設定
    preview_file = tmp_path / "preview.mp4"
    preview_file.write_text("dummy")
    ctx.preview_path = str(preview_file)
    
    # ケース1: ffmpeg.is_available() が False のとき (416行目カバー)
    mock_editor = MagicMock()
    mock_editor.ffmpeg.is_available.return_value = False
    with patch("video_editor_engine.video_editor", mock_editor):
        success = await executor.execute_action(action, ctx)
        assert success is False

    # ケース2: インポートエラーなどによる例外 (433-434行目カバー)
    with patch("video_editor_engine.video_editor", side_effect=ImportError("mock")):
        success = await executor.execute_action(action, ctx)
        assert success is False

@pytest.mark.asyncio
async def test_action_thumbnail_optimize_exception():
    executor = ImprovementExecutor()
    ctx = MagicMock()
    action = ImprovementAction(
        action_id="thumbnail_optimize", category="thumbnail", description="test", priority=1, estimated_gain=15
    )
    ctx.thumbnail_path = "dummy.png"
    
    # PIL.Image.open が例外を投げる (566-568行目カバー)
    # かつ path.exists() を True にモックする
    with patch("PIL.Image.open", side_effect=OSError("mock open exception")), \
         patch("pathlib.Path.exists", return_value=True):
        success = await executor.execute_action(action, ctx)
        assert success is False

@pytest.mark.asyncio
async def test_improvement_executor_execute_action_exceptions():
    executor = ImprovementExecutor()
    ctx = MagicMock()
    
    # ハンドラが ImportError を投げる (399-401行目カバー)
    executor._action_handlers["mock_action"] = MagicMock(side_effect=ImportError("mock import"))
    action_imp_err = ImprovementAction("mock_action", "audio", "test", 1, 10)
    assert await executor.execute_action(action_imp_err, ctx) is False

    # ハンドラが Exception を投げる (402-404行目カバー)
    executor._action_handlers["mock_action"] = MagicMock(side_effect=RuntimeError("mock exception"))
    assert await executor.execute_action(action_imp_err, ctx) is False

@pytest.mark.asyncio
async def test_workflow_run_loop_early_termination_no_improvable():
    workflow = EvaluatorOptimizerWorkflow()
    ctx = MagicMock()
    
    # 1回目のチェック：不合格、改善可能 (audio 問題)
    check_1 = {"score": 75, "rank": "B", "feedback": ["音声が小さい"], "category_scores": {"audio_quality": 60}}
    # 2回目のチェック：不合格、かつ改善不可能 (file 問題)
    check_2 = {"score": 75, "rank": "B", "feedback": ["ファイル破損"], "category_scores": {"file_integrity": 50}}
    
    workflow._run_quality_check = AsyncMock(side_effect=[check_1, check_2])
    workflow._regenerate_preview = AsyncMock(return_value=True)
    workflow.executor.execute_action = AsyncMock(return_value=True)
    
    result = await workflow.run(ctx)
    # 2回目で improvable = False となりループを抜ける (695-697行目カバー)
    assert result.success is False
    assert result.iterations == 1
    assert result.final_score == 75

@pytest.mark.asyncio
async def test_workflow_run_loop_non_executable_action():
    workflow = EvaluatorOptimizerWorkflow()
    ctx = MagicMock()
    
    # 不合格だが、executable = False なアクションがある (669行目カバー)
    check_1 = {
        "score": 75, 
        "rank": "B", 
        "feedback": ["ファイル整合性が悪いです"], 
        "category_scores": {"file_integrity": 50}
    }
    
    workflow._run_quality_check = AsyncMock(return_value=check_1)
    
    # plan メソッドをモックして、executable=False なアクションを返すようにする
    non_exec_action = ImprovementAction(
        action_id="manual_fix",
        category="file",
        description="manual fix description",
        priority=1,
        estimated_gain=0,
        executable=False
    )
    workflow.optimizer.plan = MagicMock(return_value=ImprovementPlan(
        actions=[non_exec_action],
        strategy="Test non-executable action"
    ))
    
    result = await workflow.run(ctx)
    # アクションは manual_fix (executable=False) のみなので、実行スキップされる
    assert result.success is False
    assert result.iterations == 1


@pytest.mark.asyncio
async def test_workflow_workers_success_paths():
    """QualityGateWorker と PreviewWorker が正常にインポートできて実行されるパスをテスト (723-724, 737-738行目カバー)"""
    import sys
    workflow = EvaluatorOptimizerWorkflow()
    ctx = MagicMock()
    
    mock_coordinator = MagicMock()
    
    mock_quality_worker = MagicMock()
    mock_quality_worker.execute = AsyncMock(return_value=MagicMock(data={"score": 95, "rank": "S", "feedback": []}))
    mock_coordinator.QualityGateWorker.return_value = mock_quality_worker
    
    mock_preview_worker = MagicMock()
    mock_preview_worker.execute = AsyncMock(return_value=MagicMock(success=True))
    mock_coordinator.PreviewWorker.return_value = mock_preview_worker
    
    # sys.modules を一時的に退避してモックをインポート可能にする
    orig_agents = sys.modules.get("agents")
    orig_coordinator = sys.modules.get("agents.pipeline_coordinator")
    
    sys.modules["agents"] = MagicMock()
    sys.modules["agents.pipeline_coordinator"] = mock_coordinator
    
    try:
        res_check = await workflow._run_quality_check(ctx)
        assert res_check["score"] == 95
        
        res_preview = await workflow._regenerate_preview(ctx)
        assert res_preview is True
    finally:
        # sys.modules を元に戻す
        if orig_agents is not None:
            sys.modules["agents"] = orig_agents
        elif "agents" in sys.modules:
            del sys.modules["agents"]
            
        if orig_coordinator is not None:
            sys.modules["agents.pipeline_coordinator"] = orig_coordinator
        elif "agents.pipeline_coordinator" in sys.modules:
            del sys.modules["agents.pipeline_coordinator"]


def test_register_suggested_stock_pytest_prevent_pollution():
    """pytest 実行中で store_path が None のときの早期リターンをテスト (857-858行目カバー)"""
    with patch("backend.harness.evaluator_optimizer.logger") as mock_logger:
        orchestrator_evaluator_optimizer._register_suggested_stock(
            title="Pytest Pollution Test",
            difficulty="C",
            description="Testing pollution prevention",
            source="Test Source",
            store_path=None
        )
        mock_logger.info.assert_any_call(
            "Pytest run detected. Skipping real design_stock.json write for 'Pytest Pollution Test' to prevent pollution."
        )


import pathlib

class MockPathlibPath:
    def __init__(self, mock_path_inst):
        self.mock_path_inst = mock_path_inst
        self.original_path = pathlib.Path

    def __enter__(self):
        def dummy_path(*args, **kwargs):
            return self.mock_path_inst
        pathlib.Path = dummy_path
        return self.mock_path_inst

    def __exit__(self, exc_type, exc_val, exc_tb):
        pathlib.Path = self.original_path

def test_register_suggested_stock_phase_state_exception(temp_design_stock):
    """phase_state.json 読み込みで例外が発生したときの例外ハンドラをテスト (878-879行目カバー)"""
    mock_path_inst = MagicMock()
    mock_path_inst.exists.side_effect = OSError("Permission denied")
    mock_path_inst.resolve.return_value = mock_path_inst
    mock_path_inst.__truediv__.return_value = mock_path_inst
    mock_path_inst.parent = mock_path_inst
    mock_path_inst.parents = [mock_path_inst, mock_path_inst, mock_path_inst]

    with MockPathlibPath(mock_path_inst):
        orchestrator_evaluator_optimizer._register_suggested_stock(
            title="Exception Test Title",
            difficulty="C",
            description="Testing exception handler",
            source="Test Source",
            store_path=temp_design_stock
        )
        
        # design_stock.json にデフォルトの phase=27 で追加されていることを確認する
        store = DesignStockStore(temp_design_stock)
        added_item = next((item for item in store.items if item["title"] == "Exception Test Title"), None)
        assert added_item is not None
        assert added_item["phase"] == 27

def test_register_suggested_stock_phase_state_not_exists(temp_design_stock):
    """phase_state.json が存在しない場合、デフォルトの phase=27 で追加されていることを確認する (875->881行目カバー)"""
    mock_path_inst = MagicMock()
    mock_path_inst.exists.return_value = False
    mock_path_inst.resolve.return_value = mock_path_inst
    mock_path_inst.__truediv__.return_value = mock_path_inst
    mock_path_inst.parent = mock_path_inst
    mock_path_inst.parents = [mock_path_inst, mock_path_inst, mock_path_inst]

    with MockPathlibPath(mock_path_inst):
        orchestrator_evaluator_optimizer._register_suggested_stock(
            title="Not Exists Test Title",
            difficulty="C",
            description="Testing not exists path",
            source="Test Source",
            store_path=temp_design_stock
        )
        
        store = DesignStockStore(temp_design_stock)
        added_item = next((item for item in store.items if item["title"] == "Not Exists Test Title"), None)
        assert added_item is not None
        assert added_item["phase"] == 27


# ============================================================
# 追加ブランチカバレッジ向上テスト (Phase 27)
# ============================================================

def test_quality_evaluator_classify_issues_unmatched_category():
    evaluator = QualityEvaluator()
    # マッチしないキーワードを含むフィードバックと、70未満のカテゴリを指定
    feedback = ["未知のカテゴリの問題が発生しました"]
    category_scores = {
        "unmatched_quality_spec": 50  # 70未満だが improvement_map にマッチしないキー
    }
    ctx = MagicMock()
    quality_result = {
        "score": 80,
        "rank": "B",
        "feedback": feedback,
        "category_scores": category_scores
    }
    diagnosis = evaluator.evaluate(quality_result, ctx)
    # 問題の分類結果を確認（マッチしないため、categoryはunknown、actionはmanual_reviewになるはず）
    assert any(i["category"] == "unknown" for i in diagnosis.issues)

@pytest.mark.asyncio
async def test_action_audio_normalization_temp_not_exists(tmp_path):
    executor = ImprovementExecutor()
    ctx = MagicMock()
    preview_file = tmp_path / "preview.mp4"
    preview_file.write_text("dummy video")
    ctx.preview_path = str(preview_file)
    
    action = ImprovementAction(
        action_id="audio_normalization", category="audio", description="test", priority=1, estimated_gain=10
    )
    
    mock_editor = MagicMock()
    mock_editor.ffmpeg.is_available.return_value = True
    # ffmpeg 実行が失敗し、かつ一時ファイルが存在しない場合
    mock_editor.ffmpeg.run_command.return_value = (False, "error")
    
    with patch("video_editor_engine.video_editor", mock_editor),          patch("pathlib.Path.exists", side_effect=[True, False]): # preview_path=True, temp_path=False
        success = await executor.execute_action(action, ctx)
        assert success is False

@pytest.mark.asyncio
async def test_action_re_proofread_no_corrections():
    executor = ImprovementExecutor()
    ctx = MagicMock()
    # 修正がないセグメントと、修正があるセグメントを混ぜる
    ctx.segments = [
        {"text": "正しい文章です"},  # 修正なし
        {"text": "今日ハ晴れです"}  # 修正あり
    ]
    action = ImprovementAction(
        action_id="re_proofread", category="subtitle", description="test", priority=2, estimated_gain=8
    )
    
    # 1番目のセグメントは修正なし、2番目は修正あり
    mock_apply_dict = MagicMock(side_effect=[
        ("正しい文章です", []),
        ("今日は晴れです", ["ハ->は"])
    ])
    with patch("proper_noun_dict.apply_dictionary", mock_apply_dict):
        success = await executor.execute_action(action, ctx)
        assert success is True
        assert ctx.segments[0]["text"] == "正しい文章です"
        assert ctx.segments[1]["text"] == "今日は晴れです"

@pytest.mark.asyncio
async def test_action_re_proofread_zero_corrections_overall():
    executor = ImprovementExecutor()
    ctx = MagicMock()
    ctx.segments = [{"text": "正しい文章です"}]
    action = ImprovementAction(
        action_id="re_proofread", category="subtitle", description="test", priority=2, estimated_gain=8
    )
    mock_apply_dict = MagicMock(return_value=("正しい文章です", []))
    with patch("proper_noun_dict.apply_dictionary", mock_apply_dict):
        success = await executor.execute_action(action, ctx)
        # 全体で修正が 0 件なので False が返る
        assert success is False

@pytest.mark.asyncio
async def test_action_regenerate_metadata_failed():
    executor = ImprovementExecutor()
    ctx = MagicMock()
    action = ImprovementAction(
        action_id="regenerate_metadata", category="metadata", description="test", priority=3, estimated_gain=5
    )
    mock_worker = MagicMock()
    # worker が success=False を返すケース
    mock_worker.execute = AsyncMock(return_value=MagicMock(success=False))
    with patch("agents.pipeline_coordinator.YouTubeOptWorker", return_value=mock_worker):
        success = await executor.execute_action(action, ctx)
        assert success is False

@pytest.mark.asyncio
async def test_action_thumbnail_optimize_no_resize(tmp_path):
    executor = ImprovementExecutor()
    ctx = MagicMock()
    action = ImprovementAction(
        action_id="thumbnail_optimize", category="thumbnail", description="test", priority=1, estimated_gain=15
    )
    thumb_file = tmp_path / "thumb_no_resize.png"
    thumb_file.write_text("dummy")
    ctx.thumbnail_path = str(thumb_file)
    
    mock_opened_img = MagicMock()
    mock_opened_img.__enter__.return_value = mock_opened_img
    # 最初から 1280x720 なので needs_resize は False になる
    mock_opened_img.size = (1280, 720)
    
    with patch("PIL.Image.open", return_value=mock_opened_img),          patch("pathlib.Path.exists", return_value=True),          patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value = MagicMock(st_size=1 * 1024 * 1024)
        with patch("pathlib.Path.unlink"), patch("pathlib.Path.rename"):
            success = await executor.execute_action(action, ctx)
            assert success is True
            # crop や resize は呼ばれていないはず
            mock_opened_img.crop.assert_not_called()
            mock_opened_img.resize.assert_not_called()

@pytest.mark.asyncio
async def test_action_thumbnail_optimize_aspect_ratio_correct_but_needs_resize(tmp_path):
    executor = ImprovementExecutor()
    ctx = MagicMock()
    action = ImprovementAction(
        action_id="thumbnail_optimize", category="thumbnail", description="test", priority=1, estimated_gain=15
    )
    thumb_file = tmp_path / "thumb_small.png"
    thumb_file.write_text("dummy")
    ctx.thumbnail_path = str(thumb_file)
    
    mock_opened_img = MagicMock()
    mock_opened_img.__enter__.return_value = mock_opened_img
    # アスペクト比は 16:9 (1.777...) だがサイズが小さい (640x360) ので needs_resize は True、アスペクト比差分は 0.01 未満
    mock_opened_img.size = (640, 360)
    mock_opened_img.resize.return_value = mock_opened_img
    
    with patch("PIL.Image.open", return_value=mock_opened_img),          patch("pathlib.Path.exists", return_value=True),          patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value = MagicMock(st_size=1 * 1024 * 1024)
        with patch("pathlib.Path.unlink"), patch("pathlib.Path.rename"):
            success = await executor.execute_action(action, ctx)
            assert success is True
            # crop は呼ばれず、resize は呼ばれているはず
            mock_opened_img.crop.assert_not_called()
            mock_opened_img.resize.assert_called_once()

@pytest.mark.asyncio
async def test_action_thumbnail_optimize_path_not_exists_when_rename(tmp_path):
    executor = ImprovementExecutor()
    ctx = MagicMock()
    action = ImprovementAction(
        action_id="thumbnail_optimize", category="thumbnail", description="test", priority=1, estimated_gain=15
    )
    thumb_file = tmp_path / "thumb_rename.png"
    thumb_file.write_text("dummy")
    ctx.thumbnail_path = str(thumb_file)
    
    mock_opened_img = MagicMock()
    mock_opened_img.__enter__.return_value = mock_opened_img
    mock_opened_img.size = (1280, 720)
    
    with patch("PIL.Image.open", return_value=mock_opened_img),          patch("pathlib.Path.exists", side_effect=[True, False]),          patch("pathlib.Path.stat") as mock_stat: # exists() True (open時), False (rename前)
        mock_stat.return_value = MagicMock(st_size=1 * 1024 * 1024)
        with patch("pathlib.Path.unlink") as mock_unlink, patch("pathlib.Path.rename"):
            success = await executor.execute_action(action, ctx)
            assert success is True
            # path.exists() が False なので unlink は呼ばれない
            mock_unlink.assert_not_called()

@pytest.mark.asyncio
async def test_action_thumbnail_optimize_temp_path_not_exists_on_failure(tmp_path):
    executor = ImprovementExecutor()
    ctx = MagicMock()
    action = ImprovementAction(
        action_id="thumbnail_optimize", category="thumbnail", description="test", priority=1, estimated_gain=15
    )
    thumb_file = tmp_path / "thumb_fail_no_temp.png"
    thumb_file.write_text("dummy")
    ctx.thumbnail_path = str(thumb_file)
    
    mock_opened_img = MagicMock()
    mock_opened_img.__enter__.return_value = mock_opened_img
    mock_opened_img.size = (1280, 720)
    
    # 常に 4MB 超
    stat_large = MagicMock(st_size=5 * 1024 * 1024)
    
    with patch("PIL.Image.open", return_value=mock_opened_img),          patch("pathlib.Path.exists", return_value=True),          patch("pathlib.Path.stat", return_value=stat_large):
        # 1回目の unlink/exists などをパッチ
        with patch("pathlib.Path.unlink") as mock_unlink,              patch("pathlib.Path.rename"),              patch("pathlib.Path.with_suffix") as mock_with_suffix:
            
            mock_temp_path = MagicMock()
            mock_temp_path.exists.return_value = False  # temp_path.exists() は False
            mock_temp_path.stat.return_value = stat_large
            mock_with_suffix.return_value = mock_temp_path
            
            success = await executor.execute_action(action, ctx)
            assert success is False

@pytest.mark.asyncio
async def test_workflow_run_loop_exhausted_with_no_improvement():
    workflow = EvaluatorOptimizerWorkflow()
    ctx = MagicMock()
    
    # 改善アクションを実行するが、毎回スコアが全く同じで、3回イテレーションを繰り返して終了するケース
    check_1 = {"score": 75, "rank": "B", "feedback": ["音声が小さい"], "category_scores": {"audio_quality": 60}}
    check_2 = {"score": 75, "rank": "B", "feedback": ["音声が小さい"], "category_scores": {"audio_quality": 60}}
    check_3 = {"score": 75, "rank": "B", "feedback": ["音声が小さい"], "category_scores": {"audio_quality": 60}}
    check_4 = {"score": 75, "rank": "B", "feedback": ["音声が小さい"], "category_scores": {"audio_quality": 60}}
    
    workflow._run_quality_check = AsyncMock(side_effect=[check_1, check_2, check_3, check_4])
    workflow._regenerate_preview = AsyncMock(return_value=True)
    
    # executor は True を返すが、スコアは上がらない
    workflow.executor.execute_action = AsyncMock(return_value=True)
    
    result = await workflow.run(ctx, max_iterations=3)
    assert result.success is False
    assert result.iterations == 3  # 最大回数ループした
    assert result.final_score == 75

@pytest.mark.asyncio
async def test_workflow_run_action_failed_continues():
    workflow = EvaluatorOptimizerWorkflow()
    ctx = MagicMock()
    
    # アクション実行が失敗し、次のアクションに進むかループが継続するケース
    check_1 = {"score": 75, "rank": "B", "feedback": ["音声が小さい"], "category_scores": {"audio_quality": 60}}
    check_2 = {"score": 75, "rank": "B", "feedback": ["音声が小さい"], "category_scores": {"audio_quality": 60}}
    
    workflow._run_quality_check = AsyncMock(side_effect=[check_1, check_2])
    workflow._regenerate_preview = AsyncMock(return_value=True)
    
    # executor が False (失敗) を返す
    workflow.executor.execute_action = AsyncMock(return_value=False)
    
    result = await workflow.run(ctx, max_iterations=1)
    assert result.success is False
    assert len(result.improvements_applied) == 0

@pytest.mark.asyncio
async def test_workflow_run_score_improved_but_not_passed():
    workflow = EvaluatorOptimizerWorkflow()
    ctx = MagicMock()
    
    # 改善によりスコアは向上したが、合格点（90点）には達せず、ループ上限で終了する
    check_1 = {"score": 70, "rank": "B", "feedback": ["音声が小さい"], "category_scores": {"audio_quality": 60}}
    check_2 = {"score": 80, "rank": "B", "feedback": ["音声が小さい"], "category_scores": {"audio_quality": 70}}
    check_3 = {"score": 85, "rank": "B", "feedback": ["音声が小さい"], "category_scores": {"audio_quality": 75}}
    
    workflow._run_quality_check = AsyncMock(side_effect=[check_1, check_2, check_3])
    workflow._regenerate_preview = AsyncMock(return_value=True)
    workflow.executor.execute_action = AsyncMock(return_value=True)
    
    result = await workflow.run(ctx, max_iterations=2)
    assert result.success is False
    assert result.iterations == 2
    assert result.final_score == 85

def test_orchestrator_phase_state_not_exists(temp_design_stock):
    results = {"passed": 5, "failed": 0, "total": 5}
    report = {"batch_id": "batch_no_state_001", "git_diff_summary": {"files_changed": 3}}
    
    mock_path_inst = MagicMock()
    mock_path_inst.exists.return_value = False
    mock_path_inst.resolve.return_value = mock_path_inst
    mock_path_inst.__truediv__.return_value = mock_path_inst
    mock_path_inst.parent = mock_path_inst
    mock_path_inst.parents = [mock_path_inst, mock_path_inst, mock_path_inst]

    # phase_state.json が存在しない場合、かつ design_stock が正常動作することを確認
    with patch("backend.agents.orchestration.atomic_io.safe_read_json") as mock_read,          MockPathlibPath(mock_path_inst):
        
        def side_effect(path, default=None):
            if "design_stock.json" in path:
                with open(temp_design_stock, "r", encoding="utf-8") as f:
                    return json.load(f)
            return default or {}
        mock_read.side_effect = side_effect
        
        orchestrator_evaluator_optimizer.analyze_and_suggest(
            batch_id="batch_no_state_001",
            results=results,
            report=report,
            store_path=temp_design_stock
        )
        
        store = DesignStockStore(temp_design_stock)
        assert len(store.items) == 0

def test_orchestrator_duplicate_prevention_unmatched_item_status_or_title(temp_design_stock):
    results = {"passed": 3, "failed": 1, "total": 4}
    report = {"batch_id": "batch_fail_002", "git_diff_summary": {"files_changed": 2}}
    
    store = DesignStockStore(temp_design_stock)
    store.add_item(
        title="[AUTO-DETECT] バッチ失敗に伴うデバッグと自動改善",
        phase=27,
        difficulty="C",
        description="existing item",
        source_phase_task="old source"
    )
    store.items[0]["status"] = "resolved"
    store._save()
    
    with patch("backend.agents.orchestration.atomic_io.safe_read_json") as mock_read:
        def side_effect(path, default=None):
            if "phase_state.json" in path:
                return {"current_phase": 27, "metrics": {"coverage_pct": 85.0}}
            elif "design_stock.json" in path:
                with open(temp_design_stock, "r", encoding="utf-8") as f:
                    return json.load(f)
            return default or {}
        mock_read.side_effect = side_effect
        
        orchestrator_evaluator_optimizer.analyze_and_suggest(
            batch_id="batch_fail_002",
            results=results,
            report=report,
            store_path=temp_design_stock
        )
        
        store_new = DesignStockStore(temp_design_stock)
        assert len(store_new.items) == 2
        statuses = [item["status"] for item in store_new.items]
        assert "resolved" in statuses
        assert "pending" in statuses


def test_detect_coverage_debt_exception_handling():
    """_detect_coverage_debt で例外が発生した際に適切にキャッチされ、クラッシュしないことをテスト"""
    with patch("backend.agents.orchestration.atomic_io.safe_read_json", side_effect=OSError("Read error")):
        suggestions = orchestrator_evaluator_optimizer._detect_coverage_debt(batch_id="batch_exception_001")
        assert suggestions == []


def test_register_suggested_stock_exception_handling(temp_design_stock):
    """_register_suggested_stock で DesignStockStore 起票時に OSError が発生した際、適切に例外キャッチされクラッシュしないことをテスト"""
    results = {"passed": 3, "failed": 1, "total": 4}
    report = {
        "batch_id": "batch_exception_002",
        "git_diff_summary": {"files_changed": 2}
    }
    with patch("backend.agents.orchestration.atomic_io.safe_read_json") as mock_read, \
         patch("backend.agents.orchestration.design_stock.DesignStockStore", side_effect=OSError("Disk Full")):
        def side_effect(path, default=None):
            if "phase_state.json" in path:
                return {"current_phase": 27, "metrics": {"coverage_pct": 85.0}}
            return default or {}
        mock_read.side_effect = side_effect

        # 例外が発生しても、例外ハンドリングによりクラッシュせずに実行が完了するはず
        orchestrator_evaluator_optimizer.analyze_and_suggest(
            batch_id="batch_exception_002",
            results=results,
            report=report,
            store_path=temp_design_stock
        )
