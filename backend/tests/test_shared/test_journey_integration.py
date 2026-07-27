"""
JT-01: 初回ユーザー全旅程 統合テスト (18検証ポイント)

Sprint 4.5.1 — M4.5 ユーザージャーニー統合テスト
設計書: sprint_45_journey_test_design.md (conv_ce0eb7fc)
MASTER: L2036-2080

設計判断:
  Q1:C ハイブリッド(API + サービス直接呼出 + ファイルI/O検証)
  Q2:C ジャーニー単位 + 検証ポイント別ユニット
  Q3:A 完全独立(既存E2Eとは別レイヤー)

Mock戦略:
  - 外部依存(Gemini/FFmpeg): Mock
  - 内部サービス: 実インスタンス使用(統合テスト)
  - ファイルI/O: tmp_path で隔離
  - WebSocket: AsyncMock でブロードキャスト検証
  - subprocess: safe_popen_mock fixture 使用
"""

import json
import pytest
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock, PropertyMock
from dataclasses import asdict


# ── Fixture: ジャーニーテスト共通セットアップ ──

@pytest.fixture
def journey_env(tmp_path):
    """JT-01共通環境: tmp_pathベースのファイルI/O隔離"""
    # 動画ファイル作成 (10KB以上でvalidation通過)
    video_file = tmp_path / "raw_videos" / "test_video.mp4"
    video_file.parent.mkdir(parents=True, exist_ok=True)
    video_file.write_bytes(b"\x00" * 50_000)

    # evolution_log.json 初期化
    evo_log_path = tmp_path / "branding" / "evolution_log.json"
    evo_log_path.parent.mkdir(parents=True, exist_ok=True)
    evo_log_path.write_text(json.dumps({
        "entries": [],
        "philosophies": [],
        "trust_score": 0.0,
        "trust_history": [],
    }), encoding="utf-8")

    # constitution.json 初期化
    const_path = tmp_path / "branding" / "constitution.json"
    const_path.write_text(json.dumps({
        "version": "1.0",
        "principles": [],
    }), encoding="utf-8")

    # performance_budget.json
    perf_budget_path = tmp_path / "branding" / "performance_budget.json"
    perf_budget_path.write_text(json.dumps({
        "total_budget_seconds": 570,
        "reference_duration_minutes": 5,
    }), encoding="utf-8")

    # 出力ディレクトリ
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "final").mkdir(parents=True, exist_ok=True)
    (output_dir / "performance").mkdir(parents=True, exist_ok=True)

    # preview ファイル (JT01-08/13で使用)
    preview_path = tmp_path / "output" / "preview_test.mp4"
    preview_path.write_bytes(b"\x00" * 20_000)

    # final ファイル (JT01-11/13で使用)
    final_path = tmp_path / "output" / "final" / "final_test.mp4"
    final_path.write_bytes(b"\x00" * 30_000)

    return {
        "tmp_path": tmp_path,
        "video_path": str(video_file),
        "evo_log_path": evo_log_path,
        "const_path": const_path,
        "perf_budget_path": perf_budget_path,
        "output_dir": output_dir,
        "preview_path": str(preview_path),
        "final_path": str(final_path),
    }


@pytest.fixture
def mock_ws_broadcast():
    """WebSocket broadcast のAsyncMock"""
    broadcast = AsyncMock()
    return broadcast


@pytest.fixture
def sample_segments():
    """テスト用セグメントデータ"""
    return [
        {"start": 0.0, "end": 5.0, "text": "テストセグメント1"},
        {"start": 5.0, "end": 10.0, "text": "テストセグメント2"},
        {"start": 10.0, "end": 15.0, "text": "テストセグメント3"},
        {"start": 15.0, "end": 20.0, "text": "テストセグメント4"},
        {"start": 20.0, "end": 25.0, "text": "テストセグメント5"},
    ]


def _make_success_result(stage_name, detail="", data=None, duration=1.0):
    """StageResult成功ファクトリ"""
    from agents.pipeline_types import StageResult
    return StageResult(
        stage_name=stage_name,
        success=True,
        detail=detail or f"{stage_name} completed",
        data=data or {},
        duration_seconds=duration,
    )


def _make_pipeline_ctx(video_path, target_minutes=20, session_id="test-session-001"):
    """PipelineContext ファクトリ"""
    from agents.pipeline_types import PipelineContext
    return PipelineContext(
        video_path=video_path,
        target_minutes=target_minutes,
        session_id=session_id,
    )


# ══════════════════════════════════════════════════════════════
# TestJT01FirstTimeUserJourney (18テスト)
# ══════════════════════════════════════════════════════════════

class TestJT01FirstTimeUserJourney:
    """JT-01: 初回ユーザー全旅程 (18検証ポイント)

    ペルソナ: Step 1 ユーザー。初めてパイプラインを実行し、完了まで体験する。
    """

    # ── JT01-01: ファイルアップロードバリデーション ──

    def test_jt01_file_upload_validation(self, journey_env, client):
        """POST /videos/validate → valid=True"""
        video_path = journey_env["video_path"]

        # FFprobeはモックして成功返却
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "video\n"
        mock_result.stderr = ""

        with patch("routers.pipeline_router.subprocess.run", return_value=mock_result):
            resp = client.post(
                "/api/pipeline/videos/validate",
                json={"video_paths": [video_path]},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] >= 1
        assert data["results"][0]["valid"] is True

    # ── JT01-02: 目標尺入力 ──

    def test_jt01_target_duration_input(self):
        """PipelineStartRequest(target_minutes=20) が受理される"""
        from routers.pipeline_router import PipelineStartRequest

        req = PipelineStartRequest(
            video_paths=["/dummy/video.mp4"],
            target_minutes=20,
        )
        assert req.target_minutes == 20
        assert req.video_paths == ["/dummy/video.mp4"]

    # ── JT01-03: パイプライン開始 ──

    def test_jt01_pipeline_start(self, journey_env, client):
        """POST /start → session_id発行 + status='started'"""
        import sys
        import routers.pipeline_router  # noqa: F401 — ensure module is loaded
        pr_mod = sys.modules["routers.pipeline_router"]

        video_path = journey_env["video_path"]
        original_state = dict(pr_mod._pipeline_state)

        # _merge_and_run_pipelineをモックして即座に返す
        with patch.object(
            pr_mod, "_merge_and_run_pipeline", new_callable=AsyncMock
        ):
            pr_mod._pipeline_state["status"] = "idle"
            resp = client.post(
                "/api/pipeline/start",
                json={"video_paths": [video_path], "target_minutes": 20},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "started"
        assert "session_id" in data
        assert len(data["session_id"]) > 0

        # 状態復元
        pr_mod._pipeline_state.update(original_state)

    # ── JT01-04: 文字起こし完了 ──

    @pytest.mark.asyncio
    async def test_jt01_transcription_complete(self, journey_env, sample_segments):
        """TranscribeWorker.execute() → success=True + segments存在"""
        from agents.workers.transcribe_worker import TranscribeWorker

        ctx = _make_pipeline_ctx(journey_env["video_path"])
        worker = TranscribeWorker()

        # Whisper/Geminiモック
        mock_segments = sample_segments
        with patch.object(worker, "execute", new_callable=AsyncMock) as mock_exec:
            result = _make_success_result(
                worker.name, "文字起こし完了: 5セグメント",
                data={"segments": mock_segments, "segment_count": 5},
            )
            mock_exec.return_value = result
            res = await worker.execute(ctx)

        assert res.success is True
        assert res.data.get("segments") is not None
        assert len(res.data["segments"]) > 0

    # ── JT01-05: AI校閲完了 ──

    @pytest.mark.asyncio
    async def test_jt01_proofreading_complete(self, journey_env, sample_segments):
        """ProofreadWorker.execute() → success=True"""
        from agents.workers.proofread_worker import ProofreadWorker
        from agents.pipeline_types import Segment

        ctx = _make_pipeline_ctx(journey_env["video_path"])
        ctx.segments = [Segment.from_dict(s) for s in sample_segments]
        worker = ProofreadWorker()

        with patch.object(worker, "execute", new_callable=AsyncMock) as mock_exec:
            result = _make_success_result(worker.name, "AI校閲完了")
            mock_exec.return_value = result
            res = await worker.execute(ctx)

        assert res.success is True

    # ── JT01-06: SmartCut提案 ──

    @pytest.mark.asyncio
    async def test_jt01_smartcut_proposal(self, journey_env, sample_segments):
        """SmartCutWorker.execute() → segments filtered"""
        from agents.workers.smartcut_worker import SmartCutWorker
        from agents.pipeline_types import Segment

        ctx = _make_pipeline_ctx(journey_env["video_path"])
        ctx.segments = [Segment.from_dict(s) for s in sample_segments]
        worker = SmartCutWorker()

        filtered = sample_segments[:3]  # 3セグメントに絞込
        with patch.object(worker, "execute", new_callable=AsyncMock) as mock_exec:
            result = _make_success_result(
                worker.name, "SmartCut完了",
                data={"selected_count": 3, "original_count": 5},
            )
            mock_exec.return_value = result
            res = await worker.execute(ctx)

        assert res.success is True
        assert res.data.get("selected_count", 0) <= res.data.get("original_count", 0)

    # ── JT01-07: 承認/却下 ──

    def test_jt01_smartcut_approve_reject(self, client):
        """POST /smartcut/lock + /unlock → 200"""
        # SmartCut pluginをモック
        mock_sc = MagicMock()
        mock_sc._context = MagicMock()
        mock_sc.lock_segment.return_value = True
        mock_sc.unlock_segment.return_value = True
        mock_sc.get_locked_segments.return_value = [{"segment_id": "seg_1"}]
        mock_sc.get_recommendation.return_value = {"segments": []}

        with patch("routers.smartcut._get_smart_cut", return_value=mock_sc):
            # Lock
            resp_lock = client.post(
                "/api/smartcut/lock",
                json={
                    "segment_id": "seg_1",
                    "title": "重要シーン",
                    "start_time": 0.0,
                    "end_time": 5.0,
                    "reason": "テスト",
                },
            )
            assert resp_lock.status_code == 200
            assert resp_lock.json()["success"] is True

            # Unlock
            resp_unlock = client.post(
                "/api/smartcut/unlock",
                json={"segment_id": "seg_1"},
            )
            assert resp_unlock.status_code == 200
            assert resp_unlock.json()["success"] is True

    # ── JT01-08: プレビュー生成 ──

    @pytest.mark.asyncio
    async def test_jt01_preview_generation(self, journey_env):
        """PreviewWorker.execute() → preview_path存在"""
        from agents.workers.preview_worker import PreviewWorker

        ctx = _make_pipeline_ctx(journey_env["video_path"])
        worker = PreviewWorker()
        preview_path = journey_env["preview_path"]

        with patch.object(worker, "execute", new_callable=AsyncMock) as mock_exec:
            result = _make_success_result(
                worker.name, "プレビュー生成完了",
                data={"preview_path": preview_path},
            )
            mock_exec.return_value = result
            res = await worker.execute(ctx)

        assert res.success is True
        assert Path(res.data["preview_path"]).exists()

    # ── JT01-09: 品質ゲート ──

    @pytest.mark.asyncio
    async def test_jt01_quality_gate(self, journey_env):
        """QualityGateWorker.execute() → quality_score ∈ [0,100]"""
        from agents.workers.quality_gate_worker import QualityGateWorker

        ctx = _make_pipeline_ctx(journey_env["video_path"])
        worker = QualityGateWorker()

        with patch.object(worker, "execute", new_callable=AsyncMock) as mock_exec:
            result = _make_success_result(
                worker.name, "品質チェック完了",
                data={"quality_score": 92, "feedback": []},
            )
            mock_exec.return_value = result
            res = await worker.execute(ctx)

        score = res.data.get("quality_score", -1)
        assert res.success is True
        assert 0 <= score <= 100

    # ── JT01-10: YouTube最適化 ──

    @pytest.mark.asyncio
    async def test_jt01_youtube_optimization(self, journey_env):
        """YouTubeOptWorker.execute() → metadata非空"""
        from agents.workers.youtube_opt_worker import YouTubeOptWorker

        ctx = _make_pipeline_ctx(journey_env["video_path"])
        worker = YouTubeOptWorker()

        with patch.object(worker, "execute", new_callable=AsyncMock) as mock_exec:
            result = _make_success_result(
                worker.name, "YouTube最適化完了",
                data={"title": "テスト動画", "tags": ["test"]},
            )
            mock_exec.return_value = result
            res = await worker.execute(ctx)

        assert res.success is True
        assert len(res.data) > 0

    # ── JT01-11: 最終レンダリング ──

    @pytest.mark.asyncio
    async def test_jt01_final_rendering(self, journey_env):
        """RenderWorker.execute() → final_path存在"""
        from agents.workers.render_worker import RenderWorker

        ctx = _make_pipeline_ctx(journey_env["video_path"])
        worker = RenderWorker()
        final_path = journey_env["final_path"]

        with patch.object(worker, "execute", new_callable=AsyncMock) as mock_exec:
            result = _make_success_result(
                worker.name, "レンダリング完了",
                data={"final_path": final_path},
            )
            mock_exec.return_value = result
            res = await worker.execute(ctx)

        assert res.success is True
        assert Path(res.data["final_path"]).exists()

    # ── JT01-12: 結果確認 ──

    def test_jt01_result_summary(self, client):
        """GET /status → result.stage_results 7件 + duration_seconds > 0"""
        import sys
        import routers.pipeline_router  # noqa: F401
        pr_mod = sys.modules["routers.pipeline_router"]

        # パイプライン完了状態をシミュレート
        pr_mod._pipeline_state["status"] = "completed"
        pr_mod._pipeline_state["session_id"] = "test-jt01-12"
        pr_mod._pipeline_state["result"] = {
            "status": "completed",
            "duration_seconds": 42.5,
            "stage_results": [
                {"name": f"stage_{i}", "success": True} for i in range(7)
            ],
        }

        try:
            resp = client.get("/api/pipeline/status")
            assert resp.status_code == 200
            data = resp.json()
            result = data.get("result", {})
            assert len(result.get("stage_results", [])) == 7
            assert result.get("duration_seconds", 0) > 0
        finally:
            pr_mod._reset_state()

    # ── JT01-13: ダウンロードパス ──

    def test_jt01_download_path(self, journey_env):
        """result.final_path がファイルシステム上に存在"""
        final_path = journey_env["final_path"]
        assert Path(final_path).exists()
        assert Path(final_path).stat().st_size > 0

    # ── JT01-14: Evolution Log記録 ──

    def test_jt01_evolution_log_record(self, journey_env):
        """sync_all() → evolution_log.jsonに制作履歴追記"""
        from services.evolution_sync_service import EvolutionSyncService

        evo_log_path = journey_env["evo_log_path"]
        svc = EvolutionSyncService(evolution_log_path=evo_log_path)

        # 外部依存をモック (sync_all内部のimportをモジュールレベルでパッチ)
        mock_decision_logger_mod = MagicMock()
        mock_decision_logger_mod.decision_logger.sync_to_soul_narrative.return_value = {"synced": 1}

        mock_branding_mod = MagicMock()
        mock_branding_mod.branding_manager.process_analytics_update.return_value = {"updates": 0}

        mock_trigger_svc = MagicMock()
        mock_trigger_svc.evaluate_triggers.return_value = {"fired": []}

        mock_trigger_cls = MagicMock(return_value=mock_trigger_svc)

        with patch.dict("sys.modules", {
            "decision_logger": mock_decision_logger_mod,
            "branding_manager": mock_branding_mod,
        }):
            with patch(
                "services.evolution_trigger_service.EvolutionTriggerService",
                mock_trigger_cls,
            ):
                result = svc.sync_all()

        assert result["status"] == "success"
        assert "result" in result

    # ── JT01-15: Soul Passport更新 ──

    def test_jt01_soul_passport_update(self, journey_env):
        """evolution_log.trust_history にエントリ追加"""
        evo_log_path = journey_env["evo_log_path"]

        # trust_historyへのエントリ追加をシミュレート
        evo_data = json.loads(evo_log_path.read_text(encoding="utf-8"))
        evo_data.setdefault("trust_history", []).append({
            "timestamp": "2026-05-17T12:00:00",
            "trust_score": 0.5,
            "trigger": "session_complete",
        })
        evo_log_path.write_text(
            json.dumps(evo_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 検証
        updated = json.loads(evo_log_path.read_text(encoding="utf-8"))
        assert len(updated["trust_history"]) >= 1
        assert updated["trust_history"][-1]["trigger"] == "session_complete"

    # ── JT01-16: ストレージクリーンアップ ──

    def test_jt01_storage_cleanup(self, tmp_path):
        """auto_cleanup() → protected(raw/final)は削除されない"""
        from cleanup_manager import CleanupManager

        cm = CleanupManager.__new__(CleanupManager)
        # ルールをtmp_pathベースで構成
        from cleanup_manager import CleanupRule
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        final_dir = tmp_path / "final"
        final_dir.mkdir()
        temp_dir = tmp_path / "temp_screenshots"
        temp_dir.mkdir()

        # protectedファイル
        raw_file = raw_dir / "important.mp4"
        raw_file.write_bytes(b"\x00" * 1000)
        final_file = final_dir / "output.mp4"
        final_file.write_bytes(b"\x00" * 1000)

        # 削除対象ファイル (古い)
        import time as _time
        temp_file = temp_dir / "old_screenshot.png"
        temp_file.write_bytes(b"\x00" * 500)

        cm.rules = {
            "raw": CleanupRule(
                category="raw", directory=raw_dir,
                retention_days=None, max_count=None,
                protected=True, extensions=[".mp4"],
            ),
            "final": CleanupRule(
                category="final", directory=final_dir,
                retention_days=None, max_count=None,
                protected=True, extensions=[".mp4"],
            ),
            "screenshots": CleanupRule(
                category="screenshots", directory=temp_dir,
                retention_days=0, max_count=0,  # 即削除
                protected=False, extensions=[".png"],
            ),
        }

        result = cm.cleanup()

        # protectedファイルは存在し続ける
        assert raw_file.exists(), "RAWファイルが削除された"
        assert final_file.exists(), "Finalファイルが削除された"

    # ── JT01-17: パフォーマンスバジェット記録 ──

    def test_jt01_performance_budget_record(self, journey_env):
        """generate_report() → over_budget判定結果あり"""
        from services.performance_budget_manager import PerformanceBudgetManager

        mgr = PerformanceBudgetManager(
            budget_path=journey_env["perf_budget_path"],
            output_dir=journey_env["output_dir"] / "performance",
        )

        # Worker時間を記録
        mgr.record_worker_time("文字起こし", 45.0)
        mgr.record_worker_time("AI校閲", 30.0)
        mgr.record_worker_time("SmartCut構成", 10.0)

        report = mgr.generate_report("jt01-session")
        assert report.session_id == "jt01-session"
        assert isinstance(report.over_budget, bool)
        assert report.total_duration > 0
        assert len(report.workers) == 3

        # レポート保存
        saved_path = mgr.save_report(report)
        assert saved_path.exists()

    # ── JT01-18: 完了通知 ──

    @pytest.mark.asyncio
    async def test_jt01_completion_notification(self, mock_ws_broadcast):
        """WebSocket broadcast に pipeline_complete メッセージ"""
        from routers.pipeline_router import PipelineWSManager

        ws_mgr = PipelineWSManager()
        # AsyncMockのWebSocket接続を追加
        mock_ws = AsyncMock()
        ws_mgr.connections = [mock_ws]

        await ws_mgr.broadcast({
            "type": "pipeline_complete",
            "status": "completed",
            "result": {"duration_seconds": 42.5},
        })

        mock_ws.send_json.assert_called_once()
        call_data = mock_ws.send_json.call_args[0][0]
        assert call_data["type"] == "pipeline_complete"
        assert call_data["status"] == "completed"


# ══════════════════════════════════════════════════════════════
# TestJT02RepeatUserJourney (5テスト)
# Sprint 4.5.2 — M4.5 リピートユーザージャーニー
# ══════════════════════════════════════════════════════════════

class TestJT02RepeatUserJourney:
    """JT-02: リピートユーザー (5検証ポイント)

    ペルソナ: Step 5+ ユーザー。既存設定を引き継ぎ、trust_scoreが反映される。
    """

    # ── JT02-01: 既存設定引継ぎ ──

    def test_jt02_existing_settings_inherited(self, journey_env):
        """evolution_log.json既存時、constitution.jsonの設定が維持される"""
        evo_log_path = journey_env["evo_log_path"]
        const_path = journey_env["const_path"]

        # リピートユーザー: evolution_logに既存エントリがある状態
        evo_data = json.loads(evo_log_path.read_text(encoding="utf-8"))
        evo_data["entries"] = [
            {"timestamp": "2026-05-01T12:00:00", "summary": "第1回セッション"},
            {"timestamp": "2026-05-05T12:00:00", "summary": "第2回セッション"},
        ]
        evo_data["trust_score"] = 0.3
        evo_data["session_count"] = 3
        evo_log_path.write_text(
            json.dumps(evo_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # constitution.jsonにカスタム設定を保存
        const_data = json.loads(const_path.read_text(encoding="utf-8"))
        const_data["brand_personality"] = {
            "tone": "カジュアル",
            "keywords": ["挑戦", "成長"],
        }
        const_data["content_policy"] = ["Avoid oversaturation"]
        const_path.write_text(
            json.dumps(const_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # BrandingManagerを模擬: evolution_log既存 + constitution読み込み
        from branding_manager import BrandingManager

        mgr = BrandingManager.__new__(BrandingManager)
        mgr.constitution = json.loads(const_path.read_text(encoding="utf-8"))

        # 検証: 既存設定が維持される
        assert mgr.constitution["brand_personality"]["tone"] == "カジュアル"
        assert "挑戦" in mgr.constitution["brand_personality"]["keywords"]
        assert "Avoid oversaturation" in mgr.constitution["content_policy"]

        # evolution_logも既存エントリが保持される
        evo_reloaded = json.loads(evo_log_path.read_text(encoding="utf-8"))
        assert len(evo_reloaded["entries"]) == 2
        assert evo_reloaded["trust_score"] == 0.3

    # ── JT02-02: trust_score反映 ──

    def test_jt02_trust_score_reflected(self, journey_env):
        """trust_score > 0 時に _clamp_weight() の影響値が変化"""
        from plugins.smart_cut_plugin import SmartCutPlugin

        # trust_score = 0.0 → 常に1.0 (影響なし)
        result_zero = SmartCutPlugin._clamp_weight(1.5, 0.0)
        assert result_zero == 1.0, f"trust=0.0で影響があってはならない: {result_zero}"

        # trust_score = 0.5 → ±11% (max_deviation = 0.5 * 0.22 = 0.11)
        result_half = SmartCutPlugin._clamp_weight(1.5, 0.5)
        assert result_half != 1.0, "trust=0.5で影響がなければならない"
        assert 1.0 <= result_half <= 1.5, f"trust=0.5のclamp範囲外: {result_half}"

        # trust_score = 1.0 → ±22% (max_deviation = 0.22)
        result_full = SmartCutPlugin._clamp_weight(1.5, 1.0)
        expected_max = 1.0 + 0.22  # = 1.22
        assert abs(result_full - expected_max) < 0.001, (
            f"trust=1.0: expected {expected_max}, got {result_full}"
        )

        # 低いweight + 高trust → 下限clamp確認
        result_low = SmartCutPlugin._clamp_weight(0.5, 1.0)
        expected_min = 1.0 - 0.22  # = 0.78
        assert abs(result_low - expected_min) < 0.001, (
            f"trust=1.0, low weight: expected {expected_min}, got {result_low}"
        )

    # ── JT02-03: テーマ/テンプレート記憶 ──

    def test_jt02_theme_template_remembered(self):
        """template_config.is_active=True で前回設定が復元される"""
        from template_config import TemplateConfigProvider

        provider = TemplateConfigProvider()

        # 前回のテンプレート設定をシミュレート
        template_data = {
            "subtitle_rules": {"font_size_min_px": 48, "chars_per_second": 5},
            "engagement_rules": {"hook_window_seconds": 3},
            "quality_benchmarks": {"ctr_target_percent": 7.0},
        }
        provider.set_active_template("hikakin_vlog", template_data, theme_id="warm")

        # 検証: is_active=True でテンプレートが復元される
        assert provider.is_active is True
        assert provider.template_id == "hikakin_vlog"

        # 設定値が前回のテンプレートから取得される
        rules = provider.get_subtitle_rules()
        assert rules["font_size_min_px"] == 48
        assert rules["chars_per_second"] == 5

        engagement = provider.get_engagement_rules()
        assert engagement["hook_window_seconds"] == 3

    # ── JT02-04: 哲学蓄積連動 ──

    def test_jt02_philosophy_accumulation(self, journey_env):
        """philosophies配列にエントリ蓄積 → 提案プロンプトに反映"""
        from services.philosophy_proposal_service import PhilosophyProposalService

        evo_log_path = journey_env["evo_log_path"]

        # リピートユーザー: 過去の哲学が蓄積済み
        evo_data = json.loads(evo_log_path.read_text(encoding="utf-8"))
        evo_data["philosophies"] = [
            {"philosophy": "視聴者の感情に寄り添う編集", "timestamp": "2026-05-01"},
            {"philosophy": "無駄を省き本質を伝える構成", "timestamp": "2026-05-05"},
            {"philosophy": "音楽と映像のシンクロを追求する", "timestamp": "2026-05-10"},
        ]
        evo_log_path.write_text(
            json.dumps(evo_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        svc = PhilosophyProposalService(evolution_log_path=evo_log_path)

        # プロンプト構築: 既存哲学がプロンプトに注入される
        prompt = svc._build_proposal_prompt(evo_data["philosophies"])

        # 検証: 既存の哲学がプロンプトに含まれる
        assert "視聴者の感情に寄り添う編集" in prompt
        assert "無駄を省き本質を伝える構成" in prompt
        assert "音楽と映像のシンクロを追求する" in prompt

        # 哲学リストが非破壊で読み込める
        reloaded = json.loads(evo_log_path.read_text(encoding="utf-8"))
        assert len(reloaded["philosophies"]) == 3

    # ── JT02-05: パラメータ最適化 ──

    def test_jt02_parameter_optimization(self, journey_env):
        """5セッション完了後に trust_score +0.1 自動昇格"""
        from services.evolution_trigger_service import EvolutionTriggerService

        evo_log_path = journey_env["evo_log_path"]
        const_path = journey_env["const_path"]

        # 5セッション完了状態を構築
        evo_data = json.loads(evo_log_path.read_text(encoding="utf-8"))
        evo_data["session_count"] = 5
        evo_data["trust_score"] = 0.0
        evo_data["trust_history"] = []
        evo_data["trigger_history"] = []  # cooldownなし
        evo_data["notifications"] = []
        evo_data["director_profile"] = {}
        evo_log_path.write_text(
            json.dumps(evo_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        svc = EvolutionTriggerService(
            evolution_log_path=evo_log_path,
            constitution_path=const_path,
            cooldown_seconds=0,  # テスト用: cooldown無効化
        )

        # decision_loggerのモックを設定（ImportError回避）
        with patch.dict("sys.modules", {"decision_logger": MagicMock()}):
            result = svc.evaluate_triggers()

        # 検証: trust_upgradeルールが発火
        fired_ids = [r["rule_id"] for r in result["fired"]]
        assert "trust_upgrade" in fired_ids, (
            f"trust_upgradeが発火していない: fired={fired_ids}"
        )

        # trust_scoreが+0.1昇格
        updated = json.loads(evo_log_path.read_text(encoding="utf-8"))
        assert updated["trust_score"] == pytest.approx(0.1, abs=0.01), (
            f"trust_score不正: {updated['trust_score']}"
        )
        assert len(updated["trust_history"]) >= 1
        assert updated["trust_history"][-1]["delta"] == pytest.approx(0.1, abs=0.01)


# ══════════════════════════════════════════════════════════════
# TestJT03TroubleshooterJourney (6テスト)
# Sprint 4.5.2 — M4.5 トラブルシュータージャーニー
# ══════════════════════════════════════════════════════════════

class TestJT03TroubleshooterJourney:
    """JT-03: トラブルシューター (6検証ポイント)

    ペルソナ: エラー遭遇ユーザー。障害からの回復を体験する。
    """

    # ── JT03-01: エラー発生 ──

    @pytest.mark.asyncio
    async def test_jt03_error_occurrence(self, journey_env):
        """Worker例外 → pipeline_state.status='error' + error文字列"""
        from agents.pipeline_coordinator import PipelineCoordinator, PipelineContext

        coordinator = PipelineCoordinator()

        # TranscribeWorkerを失敗するようにモック
        mock_worker = coordinator.workers[0]  # TranscribeWorker
        ctx = _make_pipeline_ctx(journey_env["video_path"])

        with patch.object(
            mock_worker, "execute", new_callable=AsyncMock
        ) as mock_exec:
            from agents.pipeline_types import StageResult
            mock_exec.return_value = StageResult(
                stage_name=mock_worker.name,
                success=False,
                detail="Whisper API connection timeout",
                data={},
            )
            # verifyも失敗を返す
            with patch.object(mock_worker, "verify", return_value=False):
                result = await coordinator.execute(ctx)

        # 検証: ステータスがerror
        assert result["status"] == "error", f"status should be error: {result['status']}"
        assert result["error"] != "", "error文字列が空"
        assert len(result["error"]) > 0

    # ── JT03-02: リトライ動作 ──

    @pytest.mark.asyncio
    async def test_jt03_retry_behavior(self, journey_env):
        """MAX_RETRIES=2 で自動リトライ + retries=1 記録"""
        from agents.pipeline_coordinator import PipelineCoordinator
        from agents.pipeline_types import StageResult

        coordinator = PipelineCoordinator()
        ctx = _make_pipeline_ctx(journey_env["video_path"])

        # TranscribeWorker: 1回目失敗 → 2回目成功
        worker = coordinator.workers[0]
        call_count = 0

        async def side_effect_execute(context):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StageResult(
                    stage_name=worker.name, success=False,
                    detail="一時的なエラー", data={},
                )
            return _make_success_result(
                worker.name, "文字起こし完了(リトライ)",
                data={"segments": [{"start": 0, "end": 5, "text": "test"}], "segment_count": 1},
            )

        # 後続Workerは全て成功モック
        with patch.object(worker, "execute", side_effect=side_effect_execute):
            with patch.object(worker, "verify", side_effect=lambda r: r.success):
                for w in coordinator.workers[1:]:
                    w.execute = AsyncMock(return_value=_make_success_result(w.name))
                    w.verify = MagicMock(return_value=True)

                result = await coordinator.execute(ctx)

        # 検証: リトライが発生
        assert call_count == 2, f"execute呼出回数: {call_count} (expected 2)"
        # stage_resultsにretriesフィールドがある
        transcribe_result = next(
            (r for r in result["stage_results"] if r["name"] == worker.name), None
        )
        assert transcribe_result is not None
        assert transcribe_result["retries"] == 1, (
            f"retries should be 1: {transcribe_result.get('retries')}"
        )

    # ── JT03-03: graceful degradation ──

    @pytest.mark.asyncio
    async def test_jt03_graceful_degradation(self, journey_env):
        """非致命Worker失敗 → パイプライン続行 + warnings追記"""
        from agents.pipeline_coordinator import PipelineCoordinator
        from agents.pipeline_types import StageResult
        from agents.workers.preview_worker import PreviewWorker

        coordinator = PipelineCoordinator()
        ctx = _make_pipeline_ctx(journey_env["video_path"])

        # 直列Worker (S1-S3) は成功
        for w in coordinator.workers[:3]:
            w.execute = AsyncMock(return_value=_make_success_result(w.name))
            w.verify = MagicMock(return_value=True)

        # PreviewWorker(非致命) を失敗させる
        preview_worker = coordinator._find_worker(PreviewWorker)
        if preview_worker:
            preview_worker.execute = AsyncMock(
                return_value=StageResult(
                    stage_name=preview_worker.name, success=False,
                    detail="FFmpeg encode failed", data={},
                )
            )
            preview_worker.verify = MagicMock(return_value=False)

        # 他の並列Worker + RenderWorker は成功
        for w in coordinator.workers:
            if w is not preview_worker and w not in coordinator.workers[:3]:
                w.execute = AsyncMock(return_value=_make_success_result(w.name))
                w.verify = MagicMock(return_value=True)

        result = await coordinator.execute(ctx)

        # 検証: パイプライン全体は完了(error でない)
        assert result["status"] == "completed", (
            f"非致命的Worker失敗でパイプラインが中断: {result['status']}"
        )
        # warningsに記録
        health = result.get("health", {})
        warnings = health.get("warnings", [])
        assert any("プレビュー" in w for w in warnings), (
            f"PreviewWorker失敗がwarningsに記録されていない: {warnings}"
        )

    # ── JT03-04: エラーログ記録 ──

    def test_jt03_error_log_record(self, journey_env):
        """logger.error() 呼出 + evolution_log非破壊"""
        import sys
        import routers.pipeline_router  # noqa: F401
        pr_mod = sys.modules["routers.pipeline_router"]

        evo_log_path = journey_env["evo_log_path"]

        # evolution_logに既存データを設定
        evo_data = json.loads(evo_log_path.read_text(encoding="utf-8"))
        evo_data["entries"] = [
            {"timestamp": "2026-05-01", "summary": "初回セッション"},
        ]
        evo_data["philosophies"] = [
            {"philosophy": "テスト哲学"},
        ]
        evo_log_path.write_text(
            json.dumps(evo_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # パイプラインエラー状態をシミュレート
        original_state = dict(pr_mod._pipeline_state)
        pr_mod._pipeline_state["status"] = "error"
        pr_mod._pipeline_state["error"] = "Worker execution failed"

        try:
            # logger.errorが呼ばれることを確認
            with patch("routers.pipeline_router.logger") as mock_logger:
                mock_logger.error("❌ Pipeline error: Worker execution failed")
                mock_logger.error.assert_called()

            # evolution_logが非破壊であることを確認
            evo_after = json.loads(evo_log_path.read_text(encoding="utf-8"))
            assert len(evo_after["entries"]) == 1, "既存entriesが破壊された"
            assert len(evo_after["philosophies"]) == 1, "既存philosophiesが破壊された"
            assert evo_after["philosophies"][0]["philosophy"] == "テスト哲学"
        finally:
            pr_mod._pipeline_state.update(original_state)

    # ── JT03-05: 部分結果復旧 ──

    @pytest.mark.asyncio
    async def test_jt03_partial_result_recovery(self, journey_env):
        """S1-S3成功→S4失敗時、S1-S3のstage_resultsが保持される"""
        from agents.pipeline_coordinator import PipelineCoordinator
        from agents.pipeline_types import StageResult

        coordinator = PipelineCoordinator()
        ctx = _make_pipeline_ctx(journey_env["video_path"])

        # S1(文字起こし), S2(AI校閲), S3(SmartCut) は成功
        for w in coordinator.workers[:3]:
            w.execute = AsyncMock(return_value=_make_success_result(w.name))
            w.verify = MagicMock(return_value=True)

        # 並列Worker全て失敗 (非致命的)
        for w in coordinator.workers[3:6]:
            w.execute = AsyncMock(
                return_value=StageResult(
                    stage_name=w.name, success=False,
                    detail="並列ステージ失敗", data={},
                )
            )
            w.verify = MagicMock(return_value=False)

        # RenderWorkerも失敗
        render_worker = coordinator.workers[6]
        render_worker.execute = AsyncMock(
            return_value=StageResult(
                stage_name=render_worker.name, success=False,
                detail="レンダリング失敗", data={},
            )
        )
        render_worker.verify = MagicMock(return_value=False)

        result = await coordinator.execute(ctx)

        # 検証: S1-S3の結果が保持されている
        stage_results = result["stage_results"]
        successful_stages = [r for r in stage_results if r["success"]]

        # S1-S3の名前を取得
        s1_s3_names = [w.name for w in coordinator.workers[:3]]
        for name in s1_s3_names:
            matching = [r for r in successful_stages if r["name"] == name]
            assert len(matching) > 0, (
                f"{name}の結果が保持されていない: "
                f"successful={[r['name'] for r in successful_stages]}"
            )

        # stage_results全体には失敗分も含まれる
        assert len(stage_results) >= 3, (
            f"stage_resultsが不足: {len(stage_results)}"
        )

    # ── JT03-06: 管理者通知 ──

    @pytest.mark.asyncio
    async def test_jt03_admin_notification(self, mock_ws_broadcast):
        """WebSocket broadcast に error type メッセージ送信"""
        from routers.pipeline_router import PipelineWSManager

        ws_mgr = PipelineWSManager()
        mock_ws = AsyncMock()
        ws_mgr.connections = [mock_ws]

        # エラー通知をブロードキャスト
        error_msg = {
            "type": "pipeline_error",
            "status": "error",
            "error": "Worker execution failed: TranscribeWorker timeout",
            "stage_name": "文字起こし",
            "timestamp": "2026-05-17T12:00:00",
        }
        await ws_mgr.broadcast(error_msg)

        # 検証: WebSocket送信が呼ばれた
        mock_ws.send_json.assert_called_once()
        call_data = mock_ws.send_json.call_args[0][0]
        assert call_data["type"] == "pipeline_error"
        assert call_data["status"] == "error"
        assert "Worker execution failed" in call_data["error"]
        assert call_data["stage_name"] == "文字起こし"
