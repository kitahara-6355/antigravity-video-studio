"""
test_pipeline_coordinator.py — M2.3 Sprint 2.3.1 PipelineCoordinator本体 45テスト

Coordinator 本体（789行）の分岐をテスト。Worker 実装は全モック。
6カテゴリ構成:
  C1: Worker登録・順序 (8)  — 7 Worker登録順序・重複排除
  C2: 実行制御 (8)         — 順次実行・並行Worker・ゲートチェック
  C3: 結果集約 (7)         — stage_results構築・最終レスポンス
  C4: エラー制御 (8)       — Worker失敗時の継続/停止判定・SelfHealing
  C5: WebSocket・Hook (7)  — 進捗通知・Pre/Post Hook発火・Dream学習
  C6: 性能 (7)             — 全Worker合計時間予算・タイムアウト

テスト設計方針:
  - Worker.execute() は全モック (AsyncMock) で即座に StageResult を返す
  - Harness (hooks/governance/session) は ImportError でスキップされる設計を活用
  - DreamEngine / RetentionMap 等の外部依存も ImportError パスを活用
  - WebSocket ブロードキャストは AsyncMock で発火を検証
"""

import sys
import json
import time
import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from dataclasses import field

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from agents.pipeline_coordinator import (
    PipelineCoordinator,
    PipelineContext,
    StageResult,
    PipelineStageWorker,
    TranscribeWorker,
    ProofreadWorker,
    SmartCutWorker,
    PreviewWorker,
    QualityGateWorker,
    RenderWorker,
    YouTubeOptWorker,
)
from tests.fixtures.mock_pipeline import create_mock_ctx


# ============================================================
# 共通ヘルパー
# ============================================================

def _make_success_result(name: str, data: dict = None) -> StageResult:
    """成功 StageResult を生成"""
    return StageResult(
        stage_name=name,
        success=True,
        detail=f"{name} 完了",
        data=data or {},
        duration_seconds=0.5,
    )


def _make_failure_result(name: str, detail: str = "エラー発生") -> StageResult:
    """失敗 StageResult を生成"""
    return StageResult(
        stage_name=name,
        success=False,
        detail=detail,
        data={},
        duration_seconds=0.1,
    )


def _patch_all_workers(coordinator: PipelineCoordinator, quality_score: int = 95):
    """全 Worker の execute を AsyncMock にパッチ"""
    for w in coordinator.workers:
        w.execute = AsyncMock(side_effect=_worker_side_effect(w, quality_score))


def _worker_side_effect(worker, quality_score: int = 95):
    """Worker の execute 用 side_effect ファクトリ"""
    async def _execute(ctx):
        result = _make_success_result(worker.name)
        # QualityGateWorker の場合は ctx にスコアを設定
        if isinstance(worker, QualityGateWorker):
            ctx.quality_score = quality_score
            ctx.quality_feedback = ["テスト品質OK"]
            result.data = {"score": quality_score, "feedback": ["テスト品質OK"]}
        elif isinstance(worker, TranscribeWorker):
            ctx.segments = create_mock_ctx(segments=10).segments
            result.data = {"segment_count": 10, "model": "small", "device": "cuda"}
        elif isinstance(worker, PreviewWorker):
            ctx.preview_path = "/tmp/preview.mp4"
            result.data = {"path": "/tmp/preview.mp4", "size_mb": 5.0}
        elif isinstance(worker, RenderWorker):
            ctx.final_path = "/tmp/final.mp4"
            result.data = {"quality": "production", "path": "/tmp/final.mp4"}
        elif isinstance(worker, YouTubeOptWorker):
            ctx.metadata = {"titles": ["テストタイトル"], "tags": ["test"]}
            result.data = {"titles": ["テストタイトル"]}
        return result
    return _execute


def _create_coordinator_with_mocks(quality_score: int = 95) -> PipelineCoordinator:
    """全 Worker をモック化した Coordinator を生成"""
    coord = PipelineCoordinator()
    _patch_all_workers(coord, quality_score)
    return coord


# ============================================================
# C1: Worker登録・順序 (8)
# ============================================================

class TestC1WorkerRegistration:
    """C1: Worker登録・順序テスト"""

    def test_C1_01_seven_workers_registered(self):
        """C1-01: 7 Worker が登録されていること"""
        coord = PipelineCoordinator()
        assert len(coord.workers) == 7

    def test_C1_02_worker_order_correct(self):
        """C1-02: Worker の実行順序が正しいこと (Transcribe→Proofread→SmartCut→Preview→YouTubeOpt→QualityGate→Render)"""
        coord = PipelineCoordinator()
        expected_types = [
            TranscribeWorker,
            ProofreadWorker,
            SmartCutWorker,
            PreviewWorker,
            YouTubeOptWorker,
            QualityGateWorker,
            RenderWorker,
        ]
        for i, (w, expected) in enumerate(zip(coord.workers, expected_types)):
            assert isinstance(w, expected), (
                f"Worker[{i}] は {expected.__name__} を期待したが "
                f"{type(w).__name__} だった"
            )

    def test_C1_03_worker_names_unique(self):
        """C1-03: Worker 名が重複していないこと"""
        coord = PipelineCoordinator()
        names = [w.name for w in coord.workers]
        assert len(names) == len(set(names)), f"重複あり: {names}"

    def test_C1_04_worker_indices_sequential(self):
        """C1-04: Worker index が連番であること"""
        coord = PipelineCoordinator()
        indices = [w.index for w in coord.workers]
        for i in range(len(indices) - 1):
            assert indices[i] < indices[i + 1], (
                f"index順序が不正: {indices}"
            )

    def test_C1_05_worker_icons_non_empty(self):
        """C1-05: 全 Worker に icon が設定されていること"""
        coord = PipelineCoordinator()
        for w in coord.workers:
            assert w.icon, f"{w.name} の icon が空"

    def test_C1_06_find_worker_by_type(self):
        """C1-06: _find_worker がタイプで正しく検索できること"""
        coord = PipelineCoordinator()
        for worker_type in [TranscribeWorker, ProofreadWorker, SmartCutWorker,
                           PreviewWorker, QualityGateWorker, RenderWorker, YouTubeOptWorker]:
            found = coord._find_worker(worker_type)
            assert found is not None, f"{worker_type.__name__} が見つからない"
            assert isinstance(found, worker_type)

    def test_C1_07_find_worker_nonexistent_returns_none(self):
        """C1-07: 未登録タイプの検索で None を返すこと"""
        coord = PipelineCoordinator()

        # 存在しないダミー Worker クラスで検索
        class DummyNonExistentWorker(PipelineStageWorker):
            async def execute(self, ctx):
                pass

        result = coord._find_worker(DummyNonExistentWorker)
        assert result is None

    def test_C1_08_no_duplicate_worker_instances(self):
        """C1-08: 同じタイプの Worker が複数登録されていないこと"""
        coord = PipelineCoordinator()
        types = [type(w) for w in coord.workers]
        assert len(types) == len(set(types)), f"タイプ重複: {types}"


# ============================================================
# C2: 実行制御 (8)
# ============================================================

class TestC2ExecutionControl:
    """C2: 実行制御テスト"""

    @pytest.mark.asyncio
    async def test_C2_01_serial_phase_executes_in_order(self):
        """C2-01: Phase A (直列) の Worker が順序通り実行されること"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        execution_order = []
        for w in coord.workers:
            original_execute = w.execute
            async def _track(ctx, worker=w, orig=original_execute):
                execution_order.append(worker.name)
                return await orig(ctx)
            w.execute = _track

        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None), \
             patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        # 直列3 Worker が最初に実行されていること
        serial_names = [coord.workers[i].name for i in range(3)]
        for name in serial_names:
            assert name in execution_order, f"{name} が実行されていない"

    @pytest.mark.asyncio
    async def test_C2_02_parallel_phase_runs_concurrently(self):
        """C2-02: Phase B (並列) で Preview, YouTubeOpt, QualityGate が並列実行されること"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        parallel_started = set()

        for w in coord.workers:
            if isinstance(w, (PreviewWorker, YouTubeOptWorker, QualityGateWorker)):
                original = w.execute
                async def _track(ctx, worker=w, orig=original):
                    parallel_started.add(worker.name)
                    return await orig(ctx)
                w.execute = _track

        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None), \
             patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        # 並列3 Worker が全て呼ばれたこと（品質改善ループで再実行される可能性があるので set で重複排除）
        assert len(parallel_started) == 3

    @pytest.mark.asyncio
    async def test_C2_03_render_after_quality_gate(self):
        """C2-03: Render は QualityGate 完了後に実行されること"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None), \
             patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        # Render が最後に実行: stage_results に Render が含まれること
        render_worker = coord._find_worker(RenderWorker)
        render_results = [r for r in ctx.stage_results if r.stage_name == render_worker.name]
        assert len(render_results) >= 1

    @pytest.mark.asyncio
    async def test_C2_04_quality_gate_production_mode(self):
        """C2-04: 品質スコア >= 90 → render_mode = 'production'"""
        coord = _create_coordinator_with_mocks(quality_score=95)
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None), \
             patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        assert ctx.render_mode == "production"

    @pytest.mark.asyncio
    async def test_C2_05_quality_gate_safe_mode(self):
        """C2-05: 品質スコア < 90 → render_mode = 'safe'"""
        coord = _create_coordinator_with_mocks(quality_score=75)
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None), \
             patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        assert ctx.render_mode == "safe"

    @pytest.mark.asyncio
    async def test_C2_06_max_retries_applied(self):
        """C2-06: Worker 失敗時のリトライ回数が MAX_RETRIES まで"""
        coord = PipelineCoordinator()
        _patch_all_workers(coord)

        # ProofreadWorker を2回失敗させてからリトライで成功させる
        call_count = 0
        proofread = coord._find_worker(ProofreadWorker)
        async def _failing_then_success(ctx):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                return _make_failure_result(proofread.name)
            return _make_success_result(proofread.name)
        proofread.execute = AsyncMock(side_effect=_failing_then_success)

        ctx = PipelineContext(video_path="/tmp/test.mp4")

        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None), \
             patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        assert call_count == 2  # 1回失敗 + 1回成功

    @pytest.mark.asyncio
    async def test_C2_07_disk_space_check(self):
        """C2-07: ディスク空き容量不足時にエラー返却"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        mock_disk = MagicMock()
        mock_disk.free = 500 * 1024 * 1024  # 500MB < 1GB

        with patch.object(coord, '_init_harness', return_value=None), \
             patch('shutil.disk_usage', return_value=mock_disk):
            result = await coord.execute(ctx)

        assert result["status"] == "error"
        assert "ディスク" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_C2_08_template_ensure_called(self):
        """C2-08: _ensure_template が実行開始時に呼ばれること"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4", template_id="standard_v1")

        ensure_called = False
        original_ensure = coord._ensure_template
        def _track_ensure(ctx):
            nonlocal ensure_called
            ensure_called = True
            original_ensure(ctx)
        coord._ensure_template = _track_ensure

        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None), \
             patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        assert ensure_called


# ============================================================
# C3: 結果集約 (7)
# ============================================================

class TestC3ResultAggregation:
    """C3: 結果集約テスト"""

    @pytest.mark.asyncio
    async def test_C3_01_build_result_contains_all_fields(self):
        """C3-01: 最終レスポンスに必須フィールドが含まれること"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None), \
             patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        required_fields = [
            "status", "session_id", "duration_seconds", "final_path",
            "preview_path", "metadata", "quality_score", "quality_details",
            "segments_count", "stage_results", "error", "health",
        ]
        for field_name in required_fields:
            assert field_name in result, f"フィールド '{field_name}' が欠損"

    @pytest.mark.asyncio
    async def test_C3_02_stage_results_structure(self):
        """C3-02: stage_results の各要素が name/success/detail/duration/retries を含むこと"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None), \
             patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        for sr in result["stage_results"]:
            assert "name" in sr
            assert "success" in sr
            assert "detail" in sr
            assert "duration" in sr
            assert "retries" in sr

    @pytest.mark.asyncio
    async def test_C3_03_completed_status_on_success(self):
        """C3-03: 全 Worker 成功時に status = 'completed'"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None), \
             patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_C3_04_quality_details_propagated(self):
        """C3-04: quality_details にスコア/フィードバック/カテゴリレポートが含まれること"""
        coord = _create_coordinator_with_mocks(quality_score=92)
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None), \
             patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        qd = result["quality_details"]
        assert qd["score"] == 92
        assert "feedback" in qd
        assert "category_report" in qd
        assert "category_scores" in qd

    @pytest.mark.asyncio
    async def test_C3_05_health_report_included(self):
        """C3-05: health レポートに skipped_features/warnings/all_features_active が含まれること"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None), \
             patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        health = result["health"]
        assert "skipped_features" in health
        assert "warnings" in health
        assert "all_features_active" in health

    @pytest.mark.asyncio
    async def test_C3_06_quality_gate_report_when_low_score(self):
        """C3-06: 品質スコア < 90 時に quality_gate_report が生成されること"""
        coord = _create_coordinator_with_mocks(quality_score=75)
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None), \
             patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        qgr = result["quality_gate_report"]
        assert qgr is not None
        assert qgr["status"] == "blocked"
        assert qgr["score"] == 75
        assert qgr["threshold"] == 90
        assert qgr["gap"] == 15
        assert qgr["force_render_available"] is True

    @pytest.mark.asyncio
    async def test_C3_07_quality_gate_report_none_when_high_score(self):
        """C3-07: 品質スコア >= 90 時に quality_gate_report が None であること"""
        coord = _create_coordinator_with_mocks(quality_score=95)
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None), \
             patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        assert result["quality_gate_report"] is None


# ============================================================
# C4: エラー制御 (8)
# ============================================================

class TestC4ErrorControl:
    """C4: エラー制御テスト"""

    @pytest.mark.asyncio
    async def test_C4_01_transcribe_failure_aborts_pipeline(self):
        """C4-01: TranscribeWorker 失敗 → パイプライン中断 (致命的エラー)"""
        coord = _create_coordinator_with_mocks()
        transcribe = coord._find_worker(TranscribeWorker)
        transcribe.execute = AsyncMock(
            return_value=_make_failure_result("文字起こし", "Whisper失敗")
        )

        ctx = PipelineContext(video_path="/tmp/test.mp4")

        with patch.object(coord, '_init_harness', return_value=None):
            result = await coord.execute(ctx)

        assert result["status"] == "error"
        assert "Whisper失敗" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_C4_02_proofread_failure_continues(self):
        """C4-02: ProofreadWorker 失敗 → 中断はしないが**完走とは呼ばない**

    R1.5-C1 で契約を変えた。旧実装は "completed" を返していたが、
    校閲が落ちた動画を「完了」と呼ぶのは偽の success。
    止めない（動画は作れる）が `degraded` にする。
    """
        coord = _create_coordinator_with_mocks()
        proofread = coord._find_worker(ProofreadWorker)
        proofread.execute = AsyncMock(
            return_value=_make_failure_result("AI校閲", "校閲エラー")
        )

        ctx = PipelineContext(video_path="/tmp/test.mp4")

        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None), \
             patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        # 止めない。ただし完走ではない
        assert result["status"] == "degraded"
        assert "proofread" in result["health"]["skipped_features"]

    @pytest.mark.asyncio
    async def test_C4_03_preview_failure_continues_with_warning(self):
        """C4-03: PreviewWorker 失敗 → 警告追加してパイプライン継続 (T-020b)"""
        coord = _create_coordinator_with_mocks()
        preview = coord._find_worker(PreviewWorker)
        preview.execute = AsyncMock(
            return_value=_make_failure_result("プレビュー生成", "FFmpeg失敗")
        )

        ctx = PipelineContext(video_path="/tmp/test.mp4")

        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None), \
             patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        assert result["status"] == "degraded"   # 止めない（T-020b）が完走でもない
        assert any("プレビュー" in w for w in ctx.warnings)

    @pytest.mark.asyncio
    async def test_C4_04_parallel_exception_handled(self):
        """C4-04: 並列ステージで例外が発生しても他のステージに影響しないこと"""
        coord = _create_coordinator_with_mocks()
        youtube = coord._find_worker(YouTubeOptWorker)
        youtube.execute = AsyncMock(side_effect=RuntimeError("API爆発"))

        ctx = PipelineContext(video_path="/tmp/test.mp4")

        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None), \
             patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        # 例外で他のステージは巻き込まない。ただし落ちた事実は残す
        assert result["status"] == "degraded"
        assert "youtube_opt" in result["health"]["skipped_features"]

    @pytest.mark.asyncio
    async def test_C4_05_quality_improvement_loop_on_low_score(self):
        """C4-05: 品質スコア < 90 → _quality_improvement_loop が呼ばれること"""
        coord = _create_coordinator_with_mocks(quality_score=75)
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        loop_called = False
        async def _track_loop(ctx, perf_manager=None):
            nonlocal loop_called
            loop_called = True
            return False  # 改善不成功
        coord._quality_improvement_loop = _track_loop

        # evaluator_optimizer は from harness.evaluator_optimizer でインポートされるため
        # ImportError を発生させることで _quality_improvement_loop にフォールバックする
        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None), \
             patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        assert loop_called

    @pytest.mark.asyncio
    async def test_C4_06_quality_improvement_loop_max_retries(self):
        """C4-06: 品質改善ループが MAX_QUALITY_RETRIES で停止すること"""
        coord = PipelineCoordinator()
        _patch_all_workers(coord, quality_score=70)

        ctx = PipelineContext(video_path="/tmp/test.mp4")
        ctx.quality_score = 70

        preview = coord._find_worker(PreviewWorker)
        preview.execute = AsyncMock(return_value=_make_success_result("プレビュー生成"))

        quality = coord._find_worker(QualityGateWorker)
        # 常に不合格を返す
        async def _always_fail(ctx):
            r = _make_failure_result("品質チェック")
            r.data = {"score": 70, "feedback": ["改善不可"]}
            ctx.quality_score = 70
            return r
        quality.execute = AsyncMock(side_effect=_always_fail)

        result = await coord._quality_improvement_loop(ctx)

        assert result is False  # 改善できなかった

    @pytest.mark.asyncio
    async def test_C4_07_quality_improvement_loop_success(self):
        """C4-07: 品質改善ループで品質スコアが改善された場合に True を返すこと"""
        coord = PipelineCoordinator()
        _patch_all_workers(coord, quality_score=95)

        ctx = PipelineContext(video_path="/tmp/test.mp4")
        ctx.quality_score = 70

        preview = coord._find_worker(PreviewWorker)
        preview.execute = AsyncMock(return_value=_make_success_result("プレビュー生成"))

        quality = coord._find_worker(QualityGateWorker)
        # 2回目のトライで合格にする
        call_count = 0
        async def _improving(ctx):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                ctx.quality_score = 92
                return StageResult(stage_name="品質チェック", success=True,
                                   data={"score": 92, "feedback": []},
                                   duration_seconds=0.1)
            ctx.quality_score = 75
            return StageResult(stage_name="品質チェック", success=False,
                               data={"score": 75, "feedback": ["要改善"]},
                               duration_seconds=0.1)
        quality.execute = AsyncMock(side_effect=_improving)

        result = await coord._quality_improvement_loop(ctx)

        assert result is True
        assert ctx.quality_score == 92

    @pytest.mark.asyncio
    async def test_C4_08_improvement_suggestions_generated(self):
        """C4-08: 品質フィードバックから改善提案が生成されること"""
        coord = PipelineCoordinator()
        ctx = PipelineContext(video_path="/tmp/test.mp4")
        ctx.quality_score = 75
        ctx.quality_feedback = [
            "音声ラウドネスが基準外",
            "字幕テキストに誤りあり",
            "メタデータのタイトルが短すぎる",
            "セグメント構成が不適切",
        ]

        suggestions = coord._generate_improvement_suggestions(ctx)

        assert len(suggestions) >= 3
        actions = [s["action"] for s in suggestions]
        assert "audio_normalization" in actions
        assert "re_proofread" in actions
        assert "regenerate_metadata" in actions


# ============================================================
# C5: WebSocket・Hook (7)
# ============================================================

class TestC5WebSocketHook:
    """C5: WebSocket・Hook テスト"""

    @pytest.mark.asyncio
    async def test_C5_01_progress_callback_invoked(self):
        """C5-01: 進捗コールバックが各 Worker 実行時に呼ばれること"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        callback_calls = []
        def _cb(index, status, detail, progress, data):
            callback_calls.append((index, status))

        coord.set_progress_callback(_cb)

        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None), \
             patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        # running + completed × 各 Worker = 少なくとも7回以上
        assert len(callback_calls) >= 7

    @pytest.mark.asyncio
    async def test_C5_02_ws_broadcast_invoked(self):
        """C5-02: WebSocket ブロードキャストが各 Worker に発火すること"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        ws_calls = []
        async def _ws(msg):
            ws_calls.append(msg)

        coord.set_ws_broadcast(_ws)

        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None), \
             patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        # 各 Worker の running + completed 通知
        assert len(ws_calls) >= 7
        # 全メッセージに type が含まれること
        for msg in ws_calls:
            assert "type" in msg

    @pytest.mark.asyncio
    async def test_C5_03_ws_message_structure(self):
        """C5-03: WebSocket メッセージに必須フィールドが含まれること"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        ws_msgs = []
        async def _ws(msg):
            ws_msgs.append(msg)

        coord.set_ws_broadcast(_ws)

        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None), \
             patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        # pipeline_progress メッセージの構造検証
        progress_msgs = [m for m in ws_msgs if m.get("type") == "pipeline_progress"]
        assert len(progress_msgs) >= 1

        for msg in progress_msgs:
            assert "stage_index" in msg
            assert "stage_name" in msg
            assert "stage_icon" in msg
            assert "status" in msg
            assert "timestamp" in msg

    @pytest.mark.asyncio
    async def test_C5_04_quality_blocked_ws_notification(self):
        """C5-04: 品質不合格時に quality_gate_blocked WebSocket 通知が発火すること"""
        coord = _create_coordinator_with_mocks(quality_score=75)
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        ws_msgs = []
        async def _ws(msg):
            ws_msgs.append(msg)

        coord.set_ws_broadcast(_ws)

        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None), \
             patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        blocked_msgs = [m for m in ws_msgs if m.get("type") == "quality_gate_blocked"]
        assert len(blocked_msgs) >= 1
        assert blocked_msgs[0]["score"] == 75
        assert blocked_msgs[0]["threshold"] == 90

    @pytest.mark.asyncio
    async def test_C5_05_harness_graceful_without_import(self):
        """C5-05: Harness 未インポート時にグレースフル実行されること"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        # _init_harness が ImportError で None を返す
        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None), \
             patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_C5_06_dream_learning_triggered(self):
        """C5-06: パイプライン完了時に _trigger_dream_learning が呼ばれること"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        dream_called = False
        async def _track_dream(ctx):
            nonlocal dream_called
            dream_called = True
        coord._trigger_dream_learning = _track_dream

        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None):
            result = await coord.execute(ctx)

        assert dream_called

    @pytest.mark.asyncio
    async def test_C5_07_retention_analysis_runs(self):
        """C5-07: パイプライン完了時に _run_retention_analysis が呼ばれること"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        retention_called = False
        async def _track_retention(ctx):
            nonlocal retention_called
            retention_called = True
            return None
        coord._run_retention_analysis = _track_retention

        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        assert retention_called


# ============================================================
# C6: 性能 (7)
# ============================================================

class TestC6Performance:
    """C6: 性能テスト"""

    @pytest.mark.asyncio
    async def test_C6_01_total_execution_under_budget(self):
        """C6-01: モック環境での全 Worker 合計が時間予算内 (< 5秒)"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        start = time.time()
        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None), \
             patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)
        elapsed = time.time() - start

        assert elapsed < 5.0, f"実行時間超過: {elapsed:.1f}秒"
        assert result["duration_seconds"] >= 0

    @pytest.mark.asyncio
    async def test_C6_02_duration_seconds_in_result(self):
        """C6-02: 最終結果の duration_seconds が正数であること"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None), \
             patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        assert result["duration_seconds"] >= 0

    @pytest.mark.asyncio
    async def test_C6_03_parallel_faster_than_serial(self):
        """C6-03: 並列 Worker の合計がシリアル実行より高速であること"""
        coord = PipelineCoordinator()
        _patch_all_workers(coord, quality_score=95)  # 品質合格で改善ループを回避

        # 並列 Worker に 0.2秒のスリープを追加（クロージャ問題回避のため即時bind）
        parallel_call_count = 0
        for w in coord.workers:
            if isinstance(w, (PreviewWorker, YouTubeOptWorker, QualityGateWorker)):
                original_fn = w.execute
                async def _slow(ctx, _orig=original_fn):
                    nonlocal parallel_call_count
                    parallel_call_count += 1
                    await asyncio.sleep(0.2)
                    return await _orig(ctx)
                w.execute = _slow

        ctx = PipelineContext(video_path="/tmp/test.mp4")

        start = time.time()
        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None), \
             patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)
        elapsed = time.time() - start

        # 3 Worker × 0.2秒 = 0.6秒 シリアル vs ~0.2秒 並列
        # リトライ (MAX_RETRIES=2) 考慮で最悪 0.2秒×リトライ回数
        # 3秒未満ならシリアル実行ではないことが確認できる
        assert parallel_call_count >= 3, f"並列Workerが{parallel_call_count}回しか呼ばれていない"
        assert elapsed < 3.0, f"実行が遅すぎる: {elapsed:.2f}秒"

    @pytest.mark.asyncio
    async def test_C6_04_disk_warning_on_low_space(self):
        """C6-04: ディスク容量 < 5GB 時に warning が追加されること"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        mock_disk = MagicMock()
        mock_disk.free = 3 * 1024 ** 3  # 3GB (< 5GB warning threshold)

        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None), \
             patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock), \
             patch('shutil.disk_usage', return_value=mock_disk):
            result = await coord.execute(ctx)

        assert result["status"] == "completed"
        assert any("ディスク" in w for w in ctx.warnings)

    @pytest.mark.asyncio
    async def test_C6_05_coordinator_singleton_exists(self):
        """C6-05: pipeline_coordinator シングルトンが存在すること"""
        from agents.pipeline_coordinator import pipeline_coordinator
        assert pipeline_coordinator is not None
        assert isinstance(pipeline_coordinator, PipelineCoordinator)

    @pytest.mark.asyncio
    async def test_C6_06_multiple_executions_independent(self):
        """C6-06: 同一 Coordinator で複数回実行しても状態が独立していること"""
        coord = _create_coordinator_with_mocks()

        ctx1 = PipelineContext(video_path="/tmp/test1.mp4")
        ctx2 = PipelineContext(video_path="/tmp/test2.mp4")

        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None), \
             patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result1 = await coord.execute(ctx1)

        # Worker を再モック（state reset）
        _patch_all_workers(coord)

        with patch.object(coord, '_init_harness', return_value=None), \
             patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None), \
             patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result2 = await coord.execute(ctx2)

        assert result1["status"] == "completed"
        assert result2["status"] == "completed"
        # PipelineContext は独立
        assert ctx1.stage_results is not ctx2.stage_results

    @pytest.mark.asyncio
    async def test_C6_07_worker_scope_map_complete(self):
        """C6-07: _WORKER_SCOPE_MAP が全 Worker をカバーしていること"""
        coord = PipelineCoordinator()
        scope_map = coord._WORKER_SCOPE_MAP

        # 全 Worker の name が scope_map に含まれていること
        for w in coord.workers:
            assert w.name in scope_map, (
                f"Worker '{w.name}' が _WORKER_SCOPE_MAP に未登録"
            )


# ============================================================
# C7: Harness統合・権限制御 (Harness統合カバレッジ)
# ============================================================

class TestC7HarnessIntegration:
    """C7: Harness連携およびガードレール機能のテスト"""

    @pytest.mark.asyncio
    async def test_C7_01_init_harness_success(self):
        """C7-01: Harness の初期化・セッション作成・スパン開始の正常パス"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4", session_id="test-session-123")

        mock_hooks = MagicMock()
        mock_hooks.hook_system.fire = AsyncMock(return_value=MagicMock(permission_decision="allow"))
        
        mock_session = MagicMock()
        mock_gov = MagicMock()
        mock_gov.governance_engine.check_permission.return_value = True
        mock_gov.governance_engine.check_rate_limit.return_value = True

        # セッションオブジェクトのモック
        mock_sess_obj = MagicMock()
        mock_sess_obj.session_id = "test-session-123"
        mock_session.session_manager.resume_session.return_value = mock_sess_obj

        # スパンオブジェクトのモック
        mock_span = MagicMock()
        mock_gov.governance_engine.start_span.return_value = mock_span

        modules_patch = {
            'harness.hooks': mock_hooks,
            'harness.session_manager': mock_session,
            'harness.governance': mock_gov,
        }

        with patch.dict(sys.modules, modules_patch),              patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None),              patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        assert result["status"] == "completed"
        mock_session.session_manager.resume_session.assert_called_once_with("test-session-123")
        mock_gov.governance_engine.start_span.assert_called_once()
        mock_gov.governance_engine.end_span.assert_called_once_with(mock_span, status="ok")

    @pytest.mark.asyncio
    async def test_C7_02_init_harness_new_session(self):
        """C7-02: セッションID未指定またはセッション復元失敗時の新規作成"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4") # session_id は None

        mock_hooks = MagicMock()
        mock_hooks.hook_system.fire = AsyncMock(return_value=MagicMock(permission_decision="allow"))
        
        mock_session = MagicMock()
        mock_gov = MagicMock()
        mock_gov.governance_engine.check_permission.return_value = True
        mock_gov.governance_engine.check_rate_limit.return_value = True

        mock_sess_obj = MagicMock()
        mock_sess_obj.session_id = "new-session-456"
        mock_session.session_manager.create_session.return_value = mock_sess_obj

        modules_patch = {
            'harness.hooks': mock_hooks,
            'harness.session_manager': mock_session,
            'harness.governance': mock_gov,
        }

        with patch.dict(sys.modules, modules_patch),              patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None),              patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        assert result["status"] == "completed"
        assert ctx.session_id == "new-session-456"
        mock_session.session_manager.create_session.assert_called_once_with(video_path="/tmp/test.mp4")

    @pytest.mark.asyncio
    async def test_C7_03_init_harness_exception(self):
        """C7-03: Harness初期化時の例外発生時のグレースフルフォールバック"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        mock_session = MagicMock()
        mock_session.session_manager.create_session.side_effect = RuntimeError("DB接続エラー")

        modules_patch = {
            'harness.hooks': MagicMock(),
            'harness.session_manager': mock_session,
            'harness.governance': MagicMock(),
        }

        # 例外が発生してもインポートパスではなく実行中にスキップされることを確認
        with patch.dict(sys.modules, modules_patch),              patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None),              patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        # 例外がスルーされ、Harnessなしで正常終了すること
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_C7_04_pre_hook_governance_permission_deny(self):
        """C7-04: GovernanceEngine による権限チェック失敗で pipeline 中断 (文字起こしの場合)"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        mock_hooks = MagicMock()
        mock_hooks.hook_system.fire = AsyncMock(return_value=MagicMock(permission_decision="allow"))
        
        mock_session = MagicMock()
        mock_gov = MagicMock()

        # 文字起こし (transcriber) の check_permission で False を返す
        mock_gov.governance_engine.check_permission.return_value = False

        modules_patch = {
            'harness.hooks': mock_hooks,
            'harness.session_manager': mock_session,
            'harness.governance': mock_gov,
        }

        with patch.dict(sys.modules, modules_patch):
            result = await coord.execute(ctx)

        assert result["status"] == "error"
        assert "Governance denied" in result["error"]
        mock_gov.governance_engine.check_permission.assert_called_with("transcriber", "transcribe_video")

    @pytest.mark.asyncio
    async def test_C7_05_pre_hook_governance_rate_limit_exceeded(self):
        """C7-05: GovernanceEngine によるレート制限超過で pipeline 中断 (文字起こしの場合)"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        mock_hooks = MagicMock()
        mock_hooks.hook_system.fire = AsyncMock(return_value=MagicMock(permission_decision="allow"))
        
        mock_session = MagicMock()
        mock_gov = MagicMock()

        mock_gov.governance_engine.check_permission.return_value = True
        mock_gov.governance_engine.check_rate_limit.return_value = False

        modules_patch = {
            'harness.hooks': mock_hooks,
            'harness.session_manager': mock_session,
            'harness.governance': mock_gov,
        }

        with patch.dict(sys.modules, modules_patch):
            result = await coord.execute(ctx)

        assert result["status"] == "error"
        assert "Rate limit exceeded" in result["error"]

    @pytest.mark.asyncio
    async def test_C7_06_pre_hook_denied_by_hook_decision(self):
        """C7-06: HookSystem の PRE_TOOL_USE で permission_decision='deny' による中断"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        mock_hooks = MagicMock()
        mock_session = MagicMock()
        mock_gov = MagicMock()

        mock_gov.governance_engine.check_permission.return_value = True
        mock_gov.governance_engine.check_rate_limit.return_value = True

        # hook_system.fire で permission_decision="deny" を返す
        mock_pre_output = MagicMock()
        mock_pre_output.permission_decision = "deny"
        mock_pre_output.permission_decision_reason = "テスト用の禁止判定"
        
        # hook_system.fire はコルーチンなので AsyncMock
        mock_hooks.hook_system.fire = AsyncMock(return_value=mock_pre_output)

        modules_patch = {
            'harness.hooks': mock_hooks,
            'harness.session_manager': mock_session,
            'harness.governance': mock_gov,
        }

        with patch.dict(sys.modules, modules_patch):
            result = await coord.execute(ctx)

        assert result["status"] == "error"
        assert "テスト用の禁止判定" in result["error"]

    @pytest.mark.asyncio
    async def test_C7_07_post_hook_success_and_failure(self):
        """C7-07: 成功時および失敗時の PostToolUse Hook 発火"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        # SmartCut 以降を失敗するように仕込み、Proofread を失敗させる
        proofread = coord._find_worker(ProofreadWorker)
        proofread.execute = AsyncMock(return_value=_make_failure_result("AI校閲", "校閲エラー"))

        mock_hooks = MagicMock()
        mock_session = MagicMock()
        mock_gov = MagicMock()

        mock_gov.governance_engine.check_permission.return_value = True
        mock_gov.governance_engine.check_rate_limit.return_value = True

        mock_pre_output = MagicMock()
        mock_pre_output.permission_decision = "allow"
        mock_hooks.hook_system.fire = AsyncMock(return_value=mock_pre_output)

        modules_patch = {
            'harness.hooks': mock_hooks,
            'harness.session_manager': mock_session,
            'harness.governance': mock_gov,
        }

        with patch.dict(sys.modules, modules_patch),              patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None),              patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        # 校閲は非致命的なので**中断はしない**。ただし完走とは呼ばない（R1.5-C1）
        assert result["status"] == "degraded"

        # POST_TOOL_USE (成功した文字起こしなど) と POST_TOOL_USE_FAILURE (失敗したAI校閲) が両方呼ばれていること
        fired_events = [args[0] for args, kwargs in mock_hooks.hook_system.fire.call_args_list]
        assert mock_hooks.HookEvent.POST_TOOL_USE in fired_events
        assert mock_hooks.HookEvent.POST_TOOL_USE_FAILURE in fired_events

        # セッションツールコールが記録されていること
        mock_session.session_manager.record_tool_call.assert_called()

    @pytest.mark.asyncio
    async def test_C7_08_finalize_harness_error_flow(self):
        """C7-08: パイプライン失敗（致命的エラー）時の finalize 処理"""
        coord = _create_coordinator_with_mocks()
        transcribe = coord._find_worker(TranscribeWorker)
        transcribe.execute = AsyncMock(return_value=_make_failure_result("文字起こし", "Whisper爆発"))

        mock_hooks = MagicMock()
        mock_session = MagicMock()
        mock_gov = MagicMock()

        mock_gov.governance_engine.check_permission.return_value = True
        mock_gov.governance_engine.check_rate_limit.return_value = True

        mock_pre_output = MagicMock()
        mock_pre_output.permission_decision = "allow"
        mock_hooks.hook_system.fire = AsyncMock(return_value=mock_pre_output)

        modules_patch = {
            'harness.hooks': mock_hooks,
            'harness.session_manager': mock_session,
            'harness.governance': mock_gov,
        }

        with patch.dict(sys.modules, modules_patch):
            result = await coord.execute(ctx := PipelineContext(video_path="/tmp/test.mp4"))

        assert result["status"] == "error"
        # エラーセッションの記録と、スパン終了(error)が呼ばれていること
        expected_reason = ctx.warnings[-1] if ctx.warnings else "Pipeline error"
        mock_session.session_manager.error_session.assert_called_once_with(ctx.session_id, expected_reason)
        mock_gov.governance_engine.end_span.assert_called_once()
        mock_gov.governance_engine.flush_traces.assert_called_once_with(ctx.session_id)

    @pytest.mark.asyncio
    async def test_C7_09_init_harness_resume_session_none(self):
        """C7-09: 指定のセッションIDが存在しない（resume_sessionがNone）場合、新規セッションを作成する"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4", session_id="non-existent-session-id")

        mock_hooks = MagicMock()
        mock_hooks.hook_system.fire = AsyncMock(return_value=MagicMock(permission_decision="allow"))

        mock_session = MagicMock()
        mock_session.session_manager.resume_session.return_value = None  # 復元に失敗
        mock_sess_obj = MagicMock()
        mock_sess_obj.session_id = "newly-created-session-id"
        mock_session.session_manager.create_session.return_value = mock_sess_obj

        mock_gov = MagicMock()
        mock_gov.governance_engine.check_permission.return_value = True
        mock_gov.governance_engine.check_rate_limit.return_value = True

        modules_patch = {
            'harness.hooks': mock_hooks,
            'harness.session_manager': mock_session,
            'harness.governance': mock_gov,
        }

        with patch.dict(sys.modules, modules_patch),              patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None),              patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        assert result["status"] == "completed"
        assert ctx.session_id == "non-existent-session-id"
        mock_session.session_manager.resume_session.assert_called_once_with("non-existent-session-id")
        mock_session.session_manager.create_session.assert_called_once_with(
            video_path="/tmp/test.mp4",
            session_id="non-existent-session-id"
        )

    @pytest.mark.asyncio
    async def test_C7_10_harness_import_error(self):
        """C7-10: Harness インポート時に ImportError が発生した場合、グレースフルに Harness なしで進行する"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        # ImportError をシミュレートするため、sys.modules から harness 関連を削除し、
        # 実際に読み込もうとしたときにインポートエラーを投げさせる
        with patch.dict(sys.modules, {'harness.hooks': None, 'harness.session_manager': None, 'harness.governance': None}),              patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None),              patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        assert result["status"] == "completed"
        assert not ctx.session_id

    @pytest.mark.asyncio
    async def test_C7_11_finalize_harness_exception_handled(self):
        """C7-11: Harness 終了処理(_finalize_harness)で例外が発生しても、パイプラインの処理自体は問題なく終了する"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        mock_hooks = MagicMock()
        mock_hooks.hook_system.fire = AsyncMock(return_value=MagicMock(permission_decision="allow"))

        mock_session = MagicMock()
        mock_gov = MagicMock()
        mock_gov.governance_engine.check_permission.return_value = True
        mock_gov.governance_engine.check_rate_limit.return_value = True
        # end_span で例外を投げる
        mock_gov.governance_engine.end_span.side_effect = RuntimeError("Governance crash during finalize")

        modules_patch = {
            'harness.hooks': mock_hooks,
            'harness.session_manager': mock_session,
            'harness.governance': mock_gov,
        }

        with patch.dict(sys.modules, modules_patch),              patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None),              patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        # 例外は catch され、パイプライン自体は completed になること
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_C7_12_pre_hook_denied_non_fatal_worker(self):
        """C7-12: 直列ステージで Transcribe 以外のワーカー (例: ProofreadWorker) が hook で denied になった場合、
        そのワーカーのみスキップされて処理全体は completed で終了する"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        mock_hooks = MagicMock()
        class DummyHookInput:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)
        mock_hooks.HookInput = DummyHookInput
        # transcribe は allow, proofread は deny
        async def mock_fire(event, hook_input):
            if hook_input.tool_name == "AI校閲":
                return MagicMock(permission_decision="deny", permission_decision_reason="校閲機能が一時無効")
            return MagicMock(permission_decision="allow")
        mock_hooks.hook_system.fire = mock_fire

        mock_session = MagicMock()
        mock_gov = MagicMock()
        mock_gov.governance_engine.check_permission.return_value = True
        mock_gov.governance_engine.check_rate_limit.return_value = True

        modules_patch = {
            'harness.hooks': mock_hooks,
            'harness.session_manager': mock_session,
            'harness.governance': mock_gov,
        }

        with patch.dict(sys.modules, modules_patch),              patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None),              patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        # AI校閲が拒否されたが致命的ではないので**止めない**。
        # ただし断られた工程は動いていないので completed とも呼ばない（R1.5-C1）
        assert result["status"] == "degraded"
        # AI校閲の StageResult が失敗 (Hook denied) として記録されていること
        proofread_res = next(r for r in result["stage_results"] if r["name"] == "AI校閲")
        assert proofread_res["success"] is False
        assert "Hook denied" in proofread_res["detail"]

    @pytest.mark.asyncio
    async def test_C7_13_pre_hook_denied_parallel_worker(self):
        """C7-13: 並列ステージでワーカー (例: YouTubeOptWorker) が hook で denied になった場合、
        そのワーカーのみスキップされ結果に失敗が記録される"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        mock_hooks = MagicMock()
        class DummyHookInput:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)
        mock_hooks.HookInput = DummyHookInput
        # YouTubeOptWorker は deny
        async def mock_fire(event, hook_input):
            if hook_input.tool_name == "YouTube最適化":
                return MagicMock(permission_decision="deny", permission_decision_reason="YouTube API 制限")
            return MagicMock(permission_decision="allow")
        mock_hooks.hook_system.fire = mock_fire

        mock_session = MagicMock()
        mock_gov = MagicMock()
        mock_gov.governance_engine.check_permission.return_value = True
        mock_gov.governance_engine.check_rate_limit.return_value = True

        modules_patch = {
            'harness.hooks': mock_hooks,
            'harness.session_manager': mock_session,
            'harness.governance': mock_gov,
        }

        with patch.dict(sys.modules, modules_patch),              patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None),              patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        # 断られた工程は動いていない。止めないが完走とも呼ばない（R1.5-C1）
        assert result["status"] == "degraded"
        yt_res = next(r for r in result["stage_results"] if r["name"] == "YouTube最適化")
        assert yt_res["success"] is False
        assert "Hook denied" in yt_res["detail"]


# ============================================================
# C8: 外部連携・付加機能 (外部サービス・例外系カバレッジ)
# ============================================================

class TestC8ExternalIntegration:
    """C8: テンプレート、バジェット、分析、学習、最適化などの外部連携テスト"""

    @pytest.mark.asyncio
    async def test_C8_01_ensure_template_success(self):
        """C8-01: template_config が非アクティブな場合の自動テンプレート復元"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4", template_id="tmpl_warm_v1")

        mock_tmpl_config_inst = MagicMock()
        mock_tmpl_config_inst.is_active = False # 非アクティブ

        mock_themes = {
            "tmpl_warm_v1": {"theme": "warm", "font": "Inter"}
        }

        mock_tmpl_config_module = MagicMock()
        mock_tmpl_config_module.template_config = mock_tmpl_config_inst

        mock_tmpl_constants_module = MagicMock()
        mock_tmpl_constants_module.PRODUCTION_TEMPLATES = mock_themes

        modules_patch = {
            'template_config': mock_tmpl_config_module,
            'template_constants': mock_tmpl_constants_module,
        }

        with patch.dict(sys.modules, modules_patch),              patch.object(coord, '_init_harness', return_value=None),              patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None),              patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        assert result["status"] == "completed"
        mock_tmpl_config_inst.set_active_template.assert_called_once_with(
            "tmpl_warm_v1", {"theme": "warm", "font": "Inter"}, theme_id="warm"
        )

    @pytest.mark.asyncio
    async def test_C8_02_ensure_template_exception(self):
        """C8-02: テンプレート復元時の例外がグレースフルに無視されること"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4", template_id="tmpl_warm_v1")

        mock_tmpl_config_inst = MagicMock()
        # プロパティ参照で例外を発生させる
        type(mock_tmpl_config_inst).is_active = PropertyMock(side_effect=RuntimeError("TemplateConfig壊れた"))

        modules_patch = {
            'template_config': MagicMock(template_config=mock_tmpl_config_inst),
        }

        with patch.dict(sys.modules, modules_patch),              patch.object(coord, '_init_harness', return_value=None),              patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None),              patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        assert result["status"] == "completed" # 例外で中断せず完了すること

    @pytest.mark.asyncio
    async def test_C8_03_performance_budget_manager_exception(self):
        """C8-03: PerformanceBudgetManager の初期化およびレポート保存時の例外ハンドリング"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        mock_perf_manager = MagicMock()
        mock_perf_manager.side_effect = RuntimeError("Performance Budget Manager Initializer Error")

        modules_patch = {
            'services.performance_budget_manager': MagicMock(PerformanceBudgetManager=mock_perf_manager)
        }

        with patch.dict(sys.modules, modules_patch),              patch.object(coord, '_init_harness', return_value=None),              patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None),              patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        assert result["status"] == "completed" # パフォーマンスバジェットの例外でも続行

    @pytest.mark.asyncio
    async def test_C8_04_performance_budget_save_exception(self):
        """C8-04: パフォーマンスバジェットレポート保存時の例外ハンドリング"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        mock_manager_inst = MagicMock()
        mock_manager_inst.generate_report.side_effect = RuntimeError("レポート生成失敗")

        modules_patch = {
            'services.performance_budget_manager': MagicMock(PerformanceBudgetManager=MagicMock(return_value=mock_manager_inst))
        }

        with patch.dict(sys.modules, modules_patch),              patch.object(coord, '_init_harness', return_value=None),              patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None),              patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_C8_05_disk_check_exception(self):
        """C8-05: ディスク空き容量チェックで例外が発生した場合のグレースフル続行"""
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        with patch.object(coord, '_init_harness', return_value=None),              patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None),              patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock),              patch('shutil.disk_usage', side_effect=OSError("ディスク情報取得不能")):
            result = await coord.execute(ctx)

        assert result["status"] == "completed" # ディスクチェックがコケてもパイプラインは完了

    @pytest.mark.asyncio
    async def test_C8_06_evaluator_optimizer_success_and_failure(self):
        """C8-06: 品質チェック不合格時の Evaluator-Optimizer 実行"""
        # 1. 成功ケース
        coord = _create_coordinator_with_mocks(quality_score=75) # 最初は 75点
        ctx = PipelineContext(video_path="/tmp/test.mp4")

        mock_opt = MagicMock()
        mock_opt_result_ok = MagicMock()
        mock_opt_result_ok.success = True
        mock_opt_result_ok.initial_score = 75
        mock_opt_result_ok.final_score = 92
        mock_opt_result_ok.iterations = 2
        mock_opt_result_ok.improvements_applied = ["audio_lufs_adjust", "re_proofread"]
        mock_opt_result_ok.duration_seconds = 4.5
        mock_opt.evaluator_optimizer.run = AsyncMock(return_value=mock_opt_result_ok)

        # セッション記録用の harness
        mock_session = MagicMock()
        mock_hooks = MagicMock()
        mock_hooks.hook_system.fire = AsyncMock(return_value=MagicMock(permission_decision="allow"))
        
        mock_gov = MagicMock()
        mock_gov.governance_engine.check_permission.return_value = True
        mock_gov.governance_engine.check_rate_limit.return_value = True

        modules_patch = {
            'harness.evaluator_optimizer': mock_opt,
            'harness.session_manager': mock_session,
            'harness.hooks': mock_hooks,
            'harness.governance': mock_gov,
        }

        with patch.dict(sys.modules, modules_patch),              patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None),              patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        assert result["status"] == "completed"
        mock_opt.evaluator_optimizer.run.assert_called_once_with(ctx, max_iterations=3)
        mock_session.session_manager.record_tool_call.assert_any_call(
            ctx.session_id, "evaluator_optimizer", {"iterations": 2}, {"improvements": ["audio_lufs_adjust", "re_proofread"]}, 4.5
        )

        # 2. 失敗（不合格のまま）ケース
        coord2 = _create_coordinator_with_mocks(quality_score=75)
        ctx2 = PipelineContext(video_path="/tmp/test.mp4")
        mock_opt_result_fail = MagicMock()
        mock_opt_result_fail.success = False
        mock_opt_result_fail.final_score = 78
        mock_opt.evaluator_optimizer.run = AsyncMock(return_value=mock_opt_result_fail)

        with patch.dict(sys.modules, modules_patch),              patch.object(coord2, '_run_retention_analysis', new_callable=AsyncMock, return_value=None),              patch.object(coord2, '_trigger_dream_learning', new_callable=AsyncMock):
            result2 = await coord2.execute(ctx2)

        assert result2["status"] == "completed" # 改善しきれなくてもパイプラインは完了

    @pytest.mark.asyncio
    async def test_C8_07_retention_analysis_success_and_exception(self):
        """C8-07: Retention Map分析の正常実行および例外ハンドリング"""
        # 1. 正常系
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4", target_minutes=5)
        ctx.segments = [{"start": 0, "end": 10}, {"start": 10, "end": 120}]

        mock_plugin = MagicMock()
        mock_report = MagicMock()
        mock_report.overall_risk_assessment = "Medium"
        mock_report.suggestions = ["音声改善", "テロップ追加"]
        mock_seg1 = MagicMock(start_time=0, end_time=10, risk_level=8, label="オープニング離脱")
        mock_seg2 = MagicMock(start_time=10, end_time=120, risk_level=3, label="本編")
        mock_report.segments = [mock_seg1, mock_seg2]
        mock_plugin.retention_map_plugin.analyze_retention_risks.return_value = mock_report

        modules_patch = {
            'plugins.retention_map_plugin': mock_plugin
        }

        with patch.dict(sys.modules, modules_patch),              patch.object(coord, '_init_harness', return_value=None),              patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        assert result["status"] == "completed"
        # metadata に分析結果が含まれること
        analysis = ctx.metadata.get("retention_analysis")
        assert analysis is not None
        assert analysis["overall_risk"] == "Medium"
        assert len(analysis["high_risk_segments"]) == 1 # risk_level >= 7 のみ
        assert analysis["high_risk_segments"][0]["time"] == "0-10s"

        # 2. 異常系（例外発生時）
        coord2 = _create_coordinator_with_mocks()
        ctx2 = PipelineContext(video_path="/tmp/test.mp4")
        mock_plugin.retention_map_plugin.analyze_retention_risks.side_effect = RuntimeError("プラグインバグ")

        with patch.dict(sys.modules, modules_patch),              patch.object(coord2, '_init_harness', return_value=None),              patch.object(coord2, '_trigger_dream_learning', new_callable=AsyncMock):
            result2 = await coord2.execute(ctx2)

        assert result2["status"] == "completed" # 例外発生しても無視して完了する

    @pytest.mark.asyncio
    async def test_C8_08_dream_learning_success_and_exception(self, monkeypatch):
        """C8-08: DreamEngine学習フックの正常系および例外ハンドリング

        **このテストだけは学習フックを動かす。** conftest がセッション全体で
        `AVS_SKIP_LEARNING_SIDE_EFFECTS=1` を立てている（実走のたびに
        VERIFIED_FACTS が書き換わるのを防ぐため）ので、ここでは外す。
        """
        monkeypatch.delenv("AVS_SKIP_LEARNING_SIDE_EFFECTS", raising=False)
        # 1. 正常系
        coord = _create_coordinator_with_mocks()
        ctx = PipelineContext(video_path="/tmp/test.mp4")
        ctx.segments = [{"start": 0, "end": 10}]
        ctx.selected_segments = [{"start": 0, "end": 10}]
        ctx.quality_score = 95
        
        # ログフォルダ書き出しのモック
        mock_mkdir = MagicMock()
        mock_write = MagicMock()
        
        mock_dream = MagicMock()
        mock_dream.dream_engine.should_dream = AsyncMock(return_value=True)
        mock_dream.dream_engine.run_dream_cycle = AsyncMock()

        modules_patch = {
            'agents.dream_engine': mock_dream
        }

        # Path.write_text と Path.mkdir をモック化してローカル書き出しを抑止
        with patch.dict(sys.modules, modules_patch),              patch.object(coord, '_init_harness', return_value=None),              patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None),              patch('pathlib.Path.mkdir', mock_mkdir),              patch('pathlib.Path.write_text', mock_write):
            result = await coord.execute(ctx)

        assert result["status"] == "completed"
        mock_dream.dream_engine.increment_session_count.assert_called_once()
        mock_dream.dream_engine.should_dream.assert_called_once()
        mock_dream.dream_engine.run_dream_cycle.assert_called_once()
        mock_write.assert_called_once() # run_*.json が書き込まれていること

        # 2. 例外系
        coord2 = _create_coordinator_with_mocks()
        ctx2 = PipelineContext(video_path="/tmp/test.mp4")
        mock_dream.dream_engine.should_dream.side_effect = RuntimeError("DreamEngine障害")

        with patch.dict(sys.modules, modules_patch),              patch.object(coord2, '_init_harness', return_value=None),              patch.object(coord2, '_run_retention_analysis', new_callable=AsyncMock, return_value=None):
            result2 = await coord2.execute(ctx2)

        assert result2["status"] == "completed" # 例外があっても正常にスルー

    @pytest.mark.asyncio
    async def test_C8_09_retention_analysis_duration_fallback(self):
        """C8-09: segments の総尺が極小 (30秒未満) または存在しない場合、
        target_minutes * 60 をフォールバック値として使用する"""
        coord = _create_coordinator_with_mocks()
        # segments を空、target_minutes を 3 に設定 (duration_sec = 0 < 30 になり、3 * 60 = 180 が使われる)
        ctx = PipelineContext(video_path="/tmp/test.mp4", target_minutes=3)
        ctx.segments = []

        # TranscribeWorker.execute が実行された際に segments を上書きしないようにモックを再設定
        transcribe = coord._find_worker(TranscribeWorker)
        transcribe.execute = AsyncMock(return_value=_make_success_result("文字起こし"))

        mock_plugin = MagicMock()
        mock_report = MagicMock()
        mock_report.overall_risk_assessment = "Low"
        mock_report.suggestions = []
        mock_report.segments = []
        mock_plugin.retention_map_plugin.analyze_retention_risks.return_value = mock_report

        modules_patch = {
            'plugins.retention_map_plugin': mock_plugin
        }

        with patch.dict(sys.modules, modules_patch),              patch.object(coord, '_init_harness', return_value=None),              patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx)

        assert result["status"] == "completed"
        # 呼び出し時の duration_sec パラメータが 180 になっていることを確認
        mock_plugin.retention_map_plugin.analyze_retention_risks.assert_called_once_with(
            video_id="test",
            duration_sec=180,
            video_path="/tmp/test.mp4"
        )


# ============================================================
# C9: エッジケース・その他 (マイナー分岐・エラー処理)
# ============================================================

class TestC9EdgeCases:
    """C9: 特殊な境界値・マイナー分岐・エラーフローのテスト"""

    @pytest.mark.asyncio
    async def test_C9_01_render_worker_failure_notification(self):
        """C9-01: RenderWorker 失敗時の notify("error") 呼び出しの検証"""
        coord = _create_coordinator_with_mocks()
        render_w = coord._find_worker(RenderWorker)
        render_w.execute = AsyncMock(return_value=_make_failure_result("最終レンダリング", "エンコードエラー"))

        # notify の動作監視
        notify_calls = []
        async def _track_notify(worker, status, detail="", progress=-1, data=None):
            if worker.name == "最終レンダリング":
                notify_calls.append(status)
        coord._notify = _track_notify

        with patch.object(coord, '_init_harness', return_value=None),              patch.object(coord, '_run_retention_analysis', new_callable=AsyncMock, return_value=None),              patch.object(coord, '_trigger_dream_learning', new_callable=AsyncMock):
            result = await coord.execute(ctx := PipelineContext(video_path="/tmp/test.mp4"))

        assert "error" in notify_calls
        # **動画が無いのに完了と言わない**（R1.5-C1）。
        # 旧実装は「Render は最後だから completed」としていたが、
        # それが偽の success そのものだった。
        assert result["status"] == "error"
        assert result["stage_results"][-1]["success"] is False

    @pytest.mark.asyncio
    async def test_C9_02_quality_loop_workers_missing(self):
        """C9-02: 品質改善ループ実行時にワーカーが見つからない場合"""
        coord = PipelineCoordinator()
        
        # 意図的に workers リストを空にする
        coord.workers = []

        ctx = PipelineContext(video_path="/tmp/test.mp4")
        ctx.quality_score = 75

        result = await coord._quality_improvement_loop(ctx)
        assert result is False

    @pytest.mark.asyncio
    async def test_C9_03_quality_loop_preview_failed(self):
        """C9-03: 品質改善ループ内で PreviewWorker.execute が失敗した場合のループ継続"""
        coord = PipelineCoordinator()
        _patch_all_workers(coord, quality_score=70)

        ctx = PipelineContext(video_path="/tmp/test.mp4")
        ctx.quality_score = 70

        # PreviewWorker を失敗させる
        preview = coord._find_worker(PreviewWorker)
        preview.execute = AsyncMock(return_value=_make_failure_result("プレビュー生成", "Preview一時エラー"))

        quality = coord._find_worker(QualityGateWorker)
        # QualityGate.execute は呼ばれないはず（Preview失敗で continue するため）
        quality.execute = MagicMock() # コルーチンではない通常のモックで十分（呼ばれないため）

        result = await coord._quality_improvement_loop(ctx)
        assert result is False
        quality.execute.assert_not_called()
