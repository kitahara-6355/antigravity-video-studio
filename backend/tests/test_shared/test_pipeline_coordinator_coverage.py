import sys
from pathlib import Path

# Ensure backend directory is in sys.path
backend_path = str(Path(__file__).parent.parent.parent)
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

# Backup original sys.modules
original_modules = sys.modules.copy()

# List of dummy modules created globally by other test files (e.g. test_pipeline_coordinator.py)
dummy_module_names = [
    'proper_noun_dict', 'template_config', 'harness', 
    'harness.session_manager', 'harness.governance', 'harness.hooks', 
    'harness.evaluator_optimizer', 'plugins.retention_map_plugin',
    'video_editor_engine', 'subtitle_engine.ai_proofreader',
    'agents.production_pipeline', 'smart_cut_engine', 'quality_gate_plugins',
    'agents.dream_engine'
]

# Temporarily remove dummy modules so we can load the real ones during imports
#
# 2026-07-26: 以前は __file__ に文字列 'video-automation' が含まれるかで
# ダミー判定していた。これは開発機のフォルダ名に依存しており、
# CI(Linux) のチェックアウト先 antigravity-video-studio では一致しないため、
# 実モジュール14個（proper_noun_dict 等）を sys.modules から除去していた。
# 除去されたモジュールは後で再 import されて別オブジェクトになるため、
# tests/test_antigravity_pipeline_chaos.py の patch.object が
# パイプライン本体と別のインスタンスを指し、10件が失敗していた
# （assert 192 == 0 = 例外を注入したのに実データが返る）。
#
# 判定を「このリポジトリ配下のファイルを持つか」に変更する。
# ディレクトリ名ではなくリポジトリルートとの位置関係で判断するため、
# チェックアウト先の名前に依存しない。
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _is_dummy_module(mod) -> bool:
    """実ファイルを持たない、またはリポジトリ外のモジュールをダミーとみなす。"""
    file_attr = getattr(mod, '__file__', None)
    if not file_attr:
        return True
    try:
        Path(file_attr).resolve().relative_to(_REPO_ROOT)
    except (ValueError, OSError):
        return True
    return False


removed_dummies = {}
for name in dummy_module_names:
    if name in sys.modules and _is_dummy_module(sys.modules[name]):
        removed_dummies[name] = sys.modules.pop(name)

import pytest
import shutil
import asyncio
import time
import json
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock

# Load the real PipelineCoordinator under test
from agents.pipeline_coordinator import PipelineCoordinator, PipelineContext, StageResult

# Restore dummy modules disabled to prevent test pollution
pass

class TestPipelineCoordinatorCoverage:
    """pipeline_coordinator.py のカバレッジ100%を達成するためのテストクラス"""

    @pytest.fixture(autouse=True)
    def clean_sys_modules(self):
        dummy_module_names = [
            'proper_noun_dict', 'template_config', 'harness', 
            'harness.session_manager', 'harness.governance', 'harness.hooks', 
            'harness.evaluator_optimizer', 'plugins.retention_map_plugin',
            'video_editor_engine', 'subtitle_engine.ai_proofreader',
            'agents.production_pipeline', 'smart_cut_engine', 'quality_gate_plugins',
            'agents.dream_engine'
        ]
        removed = {}
        for name in dummy_module_names:
            # 2026-07-26: ここもディレクトリ名（'video-automation'）でダミー判定していた。
            # モジュール冒頭と同じく、リポジトリ配下かどうかで判断する。
            # 旧判定は CI(Linux) のチェックアウト先で全モジュールをダミーとみなし、
            # 各テストの前に実モジュール14個を sys.modules から落としていた。
            if name in sys.modules and _is_dummy_module(sys.modules[name]):
                removed[name] = sys.modules.pop(name)
        yield
        # Restore dummy modules disabled to prevent test pollution
        pass

    def test_init_harness_import_error(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        
        with patch("builtins.__import__", side_effect=ImportError("Mocked ImportError")):
            harness = pc._init_harness(ctx)
            assert harness is None

    def test_init_harness_general_exception(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        
        with patch("harness.session_manager.session_manager.create_session", side_effect=Exception("Mocked general error")):
            harness = pc._init_harness(ctx)
            assert harness is None

    def test_init_harness_resume_session_success(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="existing_session_id")
        
        mock_ge = MagicMock()
        mock_sm = MagicMock()
        mock_session = MagicMock()
        mock_session.session_id = "existing_session_id"
        mock_sm.resume_session.return_value = mock_session
        
        with patch("harness.session_manager.session_manager", mock_sm), \
             patch("harness.governance.governance_engine", mock_ge):
            harness = pc._init_harness(ctx)
            assert harness is not None
            mock_sm.resume_session.assert_called_once_with("existing_session_id")
            mock_sm.create_session.assert_not_called()

    def test_init_harness_create_new_session(self):
        """151-152 のカバー: session_id が None の時に create_session を呼ぶパス"""
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id=None)
        
        mock_ge = MagicMock()
        mock_sm = MagicMock()
        mock_session = MagicMock()
        mock_session.session_id = "new_generated_session_id"
        mock_sm.create_session.return_value = mock_session
        
        with patch("harness.session_manager.session_manager", mock_sm), \
             patch("harness.governance.governance_engine", mock_ge):
            harness = pc._init_harness(ctx)
            assert harness is not None
            mock_sm.create_session.assert_called_once_with(video_path="test.mp4")
            assert ctx.session_id == "new_generated_session_id"

    def test_ensure_template_import_error(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123", template_id="nhk_style")
        
        with patch("builtins.__import__", side_effect=ImportError("Mocked ImportError")):
            pc._ensure_template(ctx)

    def test_ensure_template_exception(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123", template_id="nhk_style")
        
        with patch("template_config.TemplateConfigProvider.is_active", new_callable=PropertyMock, side_effect=Exception("Mocked error")):
            pc._ensure_template(ctx)

    def test_ensure_template_restore(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123", template_id="nhk_style")
        
        mock_template_config = MagicMock()
        mock_template_config.is_active = False
        
        with patch("template_config.template_config", mock_template_config), \
             patch("template_constants.PRODUCTION_TEMPLATES", {"nhk_style": {"some": "data"}}):
            pc._ensure_template(ctx)
            mock_template_config.set_active_template.assert_called_once_with(
                "nhk_style", {"some": "data"}, theme_id="warm"
            )

    @pytest.mark.asyncio
    async def test_execute_disk_space_insufficient(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        
        mock_usage = MagicMock(free=500 * 1024 * 1024)  # 500MB
        with patch("shutil.disk_usage", return_value=mock_usage):
            pc._init_harness = MagicMock(return_value=None)
            pc._finalize_harness = MagicMock()
            
            res = await pc.execute(ctx)
            assert res["status"] == "error"
            assert "ディスク空き容量不足" in res["error"]

    @pytest.mark.asyncio
    async def test_execute_disk_space_warning(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        
        mock_usage = MagicMock(free=3 * 1024 * 1024 * 1024)  # 3GB
        with patch("shutil.disk_usage", return_value=mock_usage):
            pc._init_harness = MagicMock(return_value=None)
            pc._finalize_harness = MagicMock()
            for w in pc.workers:
                w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail="ok", duration_seconds=0.1, data={}))
                w.verify = MagicMock(return_value=True)
                
            res = await pc.execute(ctx)
            assert "ディスク残量注意: 3.0GB" in ctx.warnings
            assert res["status"] == "completed"

    @pytest.mark.asyncio
    async def test_execute_disk_check_exception(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        
        with patch("shutil.disk_usage", side_effect=Exception("Disk error")):
            pc._init_harness = MagicMock(return_value=None)
            pc._finalize_harness = MagicMock()
            for w in pc.workers:
                w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail="ok", duration_seconds=0.1, data={}))
                w.verify = MagicMock(return_value=True)
                
            res = await pc.execute(ctx)
            assert res["status"] == "completed"

    @pytest.mark.asyncio
    async def test_performance_budget_manager_import_error(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        
        mock_usage = MagicMock(free=10 * 1024 * 1024 * 1024)
        with patch("shutil.disk_usage", return_value=mock_usage), \
             patch("builtins.__import__", side_effect=ImportError("Mocked PerformanceBudgetManager import error")):
            for w in pc.workers:
                w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail="ok", duration_seconds=0.1, data={}))
                w.verify = MagicMock(return_value=True)
                
            res = await pc.execute(ctx)
            assert res["status"] == "completed"

    @pytest.mark.asyncio
    async def test_pre_hook_governance_permission_denied(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        
        mock_ge = MagicMock()
        mock_ge.check_permission.return_value = False  # Permission Denied
        
        harness = {
            "governance_engine": mock_ge,
            "HookInput": MagicMock(),
            "hook_system": AsyncMock(),
            "HookEvent": MagicMock(),
            "session_manager": MagicMock(),
            "trace_span": MagicMock(),
        }
        
        worker = pc.workers[0]  # TranscribeWorker
        denied, reason = await pc._fire_pre_hook(harness, worker, ctx)
        assert denied is True
        assert "Governance denied" in reason

    @pytest.mark.asyncio
    async def test_pre_hook_governance_rate_limit_exceeded(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        
        mock_ge = MagicMock()
        mock_ge.check_permission.return_value = True
        mock_ge.check_rate_limit.return_value = False  # Rate limit exceeded
        
        harness = {
            "governance_engine": mock_ge,
            "HookInput": MagicMock(),
            "hook_system": AsyncMock(),
            "HookEvent": MagicMock(),
            "session_manager": MagicMock(),
            "trace_span": MagicMock(),
        }
        
        worker = pc.workers[0]
        denied, reason = await pc._fire_pre_hook(harness, worker, ctx)
        assert denied is True
        assert "Rate limit exceeded" in reason

    @pytest.mark.asyncio
    async def test_pre_hook_system_deny(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        
        mock_ge = MagicMock()
        mock_ge.check_permission.return_value = True
        mock_ge.check_rate_limit.return_value = True
        
        mock_hook_system = AsyncMock()
        mock_pre_output = MagicMock()
        mock_pre_output.permission_decision = "deny"
        mock_pre_output.permission_decision_reason = "Hook denied reason"
        mock_hook_system.fire.return_value = mock_pre_output
        
        harness = {
            "governance_engine": mock_ge,
            "HookInput": MagicMock(),
            "hook_system": mock_hook_system,
            "HookEvent": MagicMock(),
            "session_manager": MagicMock(),
            "trace_span": MagicMock(),
        }
        
        worker = pc.workers[0]
        denied, reason = await pc._fire_pre_hook(harness, worker, ctx)
        assert denied is True
        assert reason == "Hook denied reason"

    @pytest.mark.asyncio
    async def test_execute_first_worker_denied(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        
        pc._init_harness = MagicMock(return_value=None)
        pc._finalize_harness = MagicMock()
        pc._fire_pre_hook = AsyncMock(return_value=(True, "Mocked governance deny"))
        
        mock_usage = MagicMock(free=10 * 1024 * 1024 * 1024)
        with patch("shutil.disk_usage", return_value=mock_usage):
            res = await pc.execute(ctx)
            assert res["status"] == "error"
            assert "Mocked governance deny" in res["error"]

    @pytest.mark.asyncio
    async def test_execute_later_worker_denied(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        
        pc._init_harness = MagicMock(return_value=None)
        pc._finalize_harness = MagicMock()
        
        async def side_effect_pre_hook(harness, worker, ctx):
            from agents.workers import TranscribeWorker
            if isinstance(worker, TranscribeWorker):
                return False, None
            return True, "Mocked later deny"
            
        pc._fire_pre_hook = AsyncMock(side_effect=side_effect_pre_hook)
        pc._fire_post_hook = AsyncMock()
        
        for w in pc.workers:
            w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail="ok", duration_seconds=0.1, data={}))
            w.verify = MagicMock(return_value=True)
            
        mock_usage = MagicMock(free=10 * 1024 * 1024 * 1024)
        with patch("shutil.disk_usage", return_value=mock_usage):
            res = await pc.execute(ctx)
            assert res["status"] == "completed"

    @pytest.mark.asyncio
    async def test_execute_serial_worker_retry_and_success(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        
        pc._init_harness = MagicMock(return_value=None)
        pc._finalize_harness = MagicMock()
        pc._fire_pre_hook = AsyncMock(return_value=(False, None))
        pc._fire_post_hook = AsyncMock()
        
        transcribe_worker = pc.workers[0]
        transcribe_worker.verify = MagicMock(side_effect=[False, True])
        transcribe_worker.execute = AsyncMock(side_effect=[
            StageResult(stage_name=transcribe_worker.name, success=False, detail="Failed first", duration_seconds=0.1, data={}),
            StageResult(stage_name=transcribe_worker.name, success=True, detail="Success second", duration_seconds=0.1, data={}),
        ])
        
        for w in pc.workers[1:]:
            w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail="ok", duration_seconds=0.1, data={}))
            w.verify = MagicMock(return_value=True)
            
        mock_usage = MagicMock(free=10 * 1024 * 1024 * 1024)
        with patch("shutil.disk_usage", return_value=mock_usage):
            res = await pc.execute(ctx)
            assert res["status"] == "completed"
            transcribe_res = next(r for r in ctx.stage_results if r.stage_name == transcribe_worker.name)
            assert transcribe_res.success is True
            assert transcribe_res.retries == 1

    @pytest.mark.asyncio
    async def test_execute_serial_worker_fail_completely(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        
        pc._init_harness = MagicMock(return_value=None)
        pc._finalize_harness = MagicMock()
        pc._fire_pre_hook = AsyncMock(return_value=(False, None))
        pc._fire_post_hook = AsyncMock()
        
        transcribe_worker = pc.workers[0]
        transcribe_worker.verify = MagicMock(return_value=False)
        transcribe_worker.execute = AsyncMock(return_value=StageResult(stage_name=transcribe_worker.name, success=False, detail="Failed completely", duration_seconds=0.1, data={}))
        
        for w in pc.workers[1:]:
            w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail="ok", duration_seconds=0.1, data={}))
            w.verify = MagicMock(return_value=True)
            
        mock_usage = MagicMock(free=10 * 1024 * 1024 * 1024)
        with patch("shutil.disk_usage", return_value=mock_usage):
            res = await pc.execute(ctx)
            assert res["status"] == "error"
            assert "Failed completely" in res["error"]

    @pytest.mark.asyncio
    async def test_execute_parallel_worker_exception_and_preview_fail(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        ctx.quality_score = 85
        
        pc._init_harness = MagicMock(return_value=None)
        pc._finalize_harness = MagicMock()
        pc._fire_pre_hook = AsyncMock(return_value=(False, None))
        pc._fire_post_hook = AsyncMock()
        
        from agents.workers import TranscribeWorker, ProofreadWorker, SmartCutWorker
        for w in pc.workers:
            if isinstance(w, (TranscribeWorker, ProofreadWorker, SmartCutWorker)):
                w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail="ok", duration_seconds=0.1, data={}))
                w.verify = MagicMock(return_value=True)
                
        from agents.workers import PreviewWorker, YouTubeOptWorker, QualityGateWorker, RenderWorker
        preview_worker = pc._find_worker(PreviewWorker)
        yt_worker = pc._find_worker(YouTubeOptWorker)
        qg_worker = pc._find_worker(QualityGateWorker)
        render_worker = pc._find_worker(RenderWorker)
        
        preview_worker.execute = AsyncMock(return_value=StageResult(stage_name=preview_worker.name, success=False, detail="Preview generation failed", duration_seconds=0.1, data={}))
        preview_worker.verify = MagicMock(return_value=True)
        
        yt_worker.execute = AsyncMock(side_effect=Exception("YouTube API failure"))
        
        qg_worker.execute = AsyncMock(return_value=StageResult(stage_name=qg_worker.name, success=True, detail="Quality check done", duration_seconds=0.1, data={"score": 85}))
        qg_worker.verify = MagicMock(return_value=True)
        
        render_worker.execute = AsyncMock(return_value=StageResult(stage_name=render_worker.name, success=True, detail="Render completed", duration_seconds=0.1, data={}))
        render_worker.verify = MagicMock(return_value=True)
        
        mock_ws = AsyncMock()
        pc.set_ws_broadcast(mock_ws)
        
        mock_usage = MagicMock(free=10 * 1024 * 1024 * 1024)
        with patch("shutil.disk_usage", return_value=mock_usage):
            res = await pc.execute(ctx)
            assert res["status"] == "completed"
            assert any("プレビュー生成失敗" in w for w in ctx.warnings)
            assert ctx.render_mode == "safe"
            mock_ws.assert_called()

    @pytest.mark.asyncio
    async def test_execute_parallel_worker_pre_hook_denied(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        
        async def side_effect_pre_hook(harness, worker, ctx):
            from agents.workers import YouTubeOptWorker
            if isinstance(worker, YouTubeOptWorker):
                return True, "YouTubeOptWorker denied"
            return False, None
            
        pc._fire_pre_hook = AsyncMock(side_effect=side_effect_pre_hook)
        pc._init_harness = MagicMock(return_value=None)
        pc._finalize_harness = MagicMock()
        pc._fire_post_hook = AsyncMock()
        
        for w in pc.workers:
            w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail="ok", duration_seconds=0.1, data={}))
            w.verify = MagicMock(return_value=True)
            
        mock_usage = MagicMock(free=10 * 1024 * 1024 * 1024)
        with patch("shutil.disk_usage", return_value=mock_usage):
            res = await pc.execute(ctx)
            assert res["status"] == "completed"

    @pytest.mark.asyncio
    async def test_execute_evaluator_optimizer_success(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        ctx.quality_score = 85
        
        pc._init_harness = MagicMock(return_value={"session_manager": MagicMock()})
        pc._finalize_harness = MagicMock()
        pc._fire_pre_hook = AsyncMock(return_value=(False, None))
        pc._fire_post_hook = AsyncMock()
        
        for w in pc.workers:
            w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail="ok", duration_seconds=0.1, data={}))
            w.verify = MagicMock(return_value=True)
            
        from agents.workers import QualityGateWorker
        qg_worker = pc._find_worker(QualityGateWorker)
        qg_worker.verify = MagicMock(return_value=False)
        
        mock_opt_result = MagicMock()
        mock_opt_result.success = True
        mock_opt_result.initial_score = 85
        mock_opt_result.final_score = 92
        mock_opt_result.iterations = 2
        mock_opt_result.improvements_applied = ["audio_fix"]
        mock_opt_result.duration_seconds = 5.0
        
        mock_evaluator_optimizer = AsyncMock()
        mock_evaluator_optimizer.run.return_value = mock_opt_result
        
        mock_usage = MagicMock(free=10 * 1024 * 1024 * 1024)
        with patch("shutil.disk_usage", return_value=mock_usage), \
             patch("harness.evaluator_optimizer.evaluator_optimizer", mock_evaluator_optimizer):
            res = await pc.execute(ctx)
            assert res["status"] == "completed"

    @pytest.mark.asyncio
    async def test_execute_evaluator_optimizer_failed(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        ctx.quality_score = 85
        
        pc._init_harness = MagicMock(return_value=None)
        pc._finalize_harness = MagicMock()
        pc._fire_pre_hook = AsyncMock(return_value=(False, None))
        pc._fire_post_hook = AsyncMock()
        
        for w in pc.workers:
            w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail="ok", duration_seconds=0.1, data={}))
            w.verify = MagicMock(return_value=True)
            
        from agents.workers import QualityGateWorker
        qg_worker = pc._find_worker(QualityGateWorker)
        qg_worker.verify = MagicMock(return_value=False)
        
        mock_opt_result = MagicMock()
        mock_opt_result.success = False
        mock_opt_result.final_score = 88
        
        mock_evaluator_optimizer = AsyncMock()
        mock_evaluator_optimizer.run.return_value = mock_opt_result
        
        mock_usage = MagicMock(free=10 * 1024 * 1024 * 1024)
        with patch("shutil.disk_usage", return_value=mock_usage), \
             patch("harness.evaluator_optimizer.evaluator_optimizer", mock_evaluator_optimizer):
            res = await pc.execute(ctx)
            assert res["status"] == "completed"

    @pytest.mark.asyncio
    async def test_quality_improvement_loop_fallback_success(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        ctx.quality_score = 85
        ctx.quality_feedback = []
        
        pc._init_harness = MagicMock(return_value=None)
        pc._finalize_harness = MagicMock()
        pc._fire_pre_hook = AsyncMock(return_value=(False, None))
        pc._fire_post_hook = AsyncMock()
        
        for w in pc.workers:
            w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail="ok", duration_seconds=0.1, data={"feedback": ["low volume"]}))
            w.verify = MagicMock(return_value=True)
            
        from agents.workers import QualityGateWorker
        qg_worker = pc._find_worker(QualityGateWorker)
        qg_worker.verify = MagicMock(side_effect=[False, False, False, True])
        
        mock_usage = MagicMock(free=10 * 1024 * 1024 * 1024)
        with patch("shutil.disk_usage", return_value=mock_usage), \
             patch("builtins.__import__", side_effect=ImportError("evaluator_optimizer not found")):
            res = await pc.execute(ctx)
            assert res["status"] == "completed"

    @pytest.mark.asyncio
    async def test_quality_improvement_loop_with_perf_manager(self):
        """631 と 642 をカバー: perf_manager.record_worker_time を呼ぶパス"""
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        ctx.quality_score = 85
        ctx.quality_feedback = []
        
        from agents.workers import QualityGateWorker, PreviewWorker
        qg_worker = pc._find_worker(QualityGateWorker)
        preview_worker = pc._find_worker(PreviewWorker)
        
        qg_worker.verify = MagicMock(side_effect=[False, True])
        qg_worker.execute = AsyncMock(return_value=StageResult(stage_name=qg_worker.name, success=True, detail="ok", duration_seconds=0.1, data={"feedback": ["low volume"]}))
        preview_worker.execute = AsyncMock(return_value=StageResult(stage_name=preview_worker.name, success=True, detail="ok", duration_seconds=0.1, data={}))
        
        mock_perf_manager = MagicMock()
        
        res = await pc._quality_improvement_loop(ctx, perf_manager=mock_perf_manager)
        assert res is True
        mock_perf_manager.record_worker_time.assert_any_call(preview_worker.name, pytest.approx(0.0, abs=1.0))
        mock_perf_manager.record_worker_time.assert_any_call(qg_worker.name, pytest.approx(0.0, abs=1.0))

    @pytest.mark.asyncio
    async def test_quality_improvement_loop_missing_workers(self):
        pc = PipelineCoordinator()
        pc.workers = []  # Empty workers list
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        
        res = await pc._quality_improvement_loop(ctx)
        assert res is False

    @pytest.mark.asyncio
    async def test_quality_improvement_loop_max_retries_reached(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        ctx.quality_score = 85
        ctx.quality_feedback = []
        
        from agents.workers import QualityGateWorker, PreviewWorker
        qg_worker = pc._find_worker(QualityGateWorker)
        preview_worker = pc._find_worker(PreviewWorker)
        
        qg_worker.verify = MagicMock(return_value=False)
        qg_worker.execute = AsyncMock(return_value=StageResult(stage_name=qg_worker.name, success=True, detail="ok", duration_seconds=0.1, data={"feedback": ["bad audio"]}))
        preview_worker.execute = AsyncMock(return_value=StageResult(stage_name=preview_worker.name, success=True, detail="ok", duration_seconds=0.1, data={}))
        
        res = await pc._quality_improvement_loop(ctx)
        assert res is False

    def test_finalize_harness_cases(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        
        # Case 1: harness is None
        pc._finalize_harness(None, ctx)
        
        # Case 2: status is "error"
        mock_ge = MagicMock()
        mock_sm = MagicMock()
        harness = {
            "governance_engine": mock_ge,
            "session_manager": mock_sm,
            "trace_span": MagicMock(),
        }
        ctx.warnings = ["Test warning"]
        pc._finalize_harness(harness, ctx, status="error")
        mock_sm.error_session.assert_called_once_with(ctx.session_id, "Test warning")
        
        # Case 3: Exception in finalize is swallowed
        mock_ge.end_span.side_effect = Exception("Finalize error")
        pc._finalize_harness(harness, ctx, status="ok")

    def test_generate_improvement_suggestions(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        
        ctx.quality_feedback = [
            "音声ラウドネスが基準以下です",
            "字幕のフォントサイズが大きすぎます",
            "メタデータのタグを追加してください",
            "セグメント構成が長いです"
        ]
        
        suggestions = pc._generate_improvement_suggestions(ctx)
        actions = [s["action"] for s in suggestions]
        assert "audio_normalization" in actions
        assert "re_proofread" in actions
        assert "regenerate_metadata" in actions
        assert "restructure_segments" in actions

    @pytest.mark.asyncio
    async def test_run_retention_analysis_success(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        ctx.segments = [{"start": 0, "end": 10}, {"start": 10, "end": 25}]
        
        mock_report = MagicMock()
        mock_report.overall_risk_assessment = "Low"
        mock_segment = MagicMock()
        mock_segment.start_time = 10
        mock_segment.end_time = 20
        mock_segment.risk_level = 8
        mock_segment.label = "dropoff"
        mock_report.segments = [mock_segment]
        mock_report.suggestions = ["Engage early"]
        
        mock_plugin = MagicMock()
        mock_plugin.analyze_retention_risks.return_value = mock_report
        
        with patch("plugins.retention_map_plugin.retention_map_plugin", mock_plugin):
            res = await pc._run_retention_analysis(ctx)
            assert res is not None
            assert res.stage_name == "Retention分析"
            assert ctx.metadata["retention_analysis"]["overall_risk"] == "Low"
            assert len(ctx.metadata["retention_analysis"]["high_risk_segments"]) == 1

    @pytest.mark.asyncio
    async def test_run_retention_analysis_with_segment_objects(self):
        from agents.pipeline_types import Segment
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        ctx.segments = [Segment(start=0.0, end=10.0, text="hello"), Segment(start=10.0, end=25.0, text="world")]
        
        mock_report = MagicMock()
        mock_report.overall_risk_assessment = "Low"
        mock_segment = MagicMock()
        mock_segment.start_time = 10
        mock_segment.end_time = 20
        mock_segment.risk_level = 8
        mock_segment.label = "dropoff"
        mock_report.segments = [mock_segment]
        mock_report.suggestions = ["Engage early"]
        
        mock_plugin = MagicMock()
        mock_plugin.analyze_retention_risks.return_value = mock_report
        
        with patch("plugins.retention_map_plugin.retention_map_plugin", mock_plugin):
            res = await pc._run_retention_analysis(ctx)
            assert res is not None
            assert res.stage_name == "Retention分析"
            assert ctx.metadata["retention_analysis"]["overall_risk"] == "Low"
            assert len(ctx.metadata["retention_analysis"]["high_risk_segments"]) == 1

    @pytest.mark.asyncio
    async def test_run_retention_analysis_fallback_duration(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=5, session_id="s123")
        ctx.segments = []
        
        mock_report = MagicMock()
        mock_report.overall_risk_assessment = "High"
        mock_report.segments = []
        mock_report.suggestions = []
        
        mock_plugin = MagicMock()
        mock_plugin.analyze_retention_risks.return_value = mock_report
        
        with patch("plugins.retention_map_plugin.retention_map_plugin", mock_plugin):
            res = await pc._run_retention_analysis(ctx)
            mock_plugin.analyze_retention_risks.assert_called_once_with(
                video_id="test",
                duration_sec=300,
                video_path="test.mp4"
            )
            assert res is not None

    @pytest.mark.asyncio
    async def test_run_retention_analysis_exception(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=5, session_id="s123")
        
        with patch("builtins.__import__", side_effect=ImportError("plugin not found")):
            res = await pc._run_retention_analysis(ctx)
            assert res is None

    @pytest.mark.asyncio
    async def test_trigger_dream_learning_success(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=5, session_id="s123")
        ctx.segments = []
        ctx.selected_segments = []
        ctx.quality_score = 95
        ctx.stage_results = []
        
        mock_dream_engine = MagicMock()
        mock_dream_engine.increment_session_count = MagicMock()
        mock_dream_engine.should_dream = AsyncMock(return_value=True)
        mock_dream_engine.run_dream_cycle = AsyncMock()
        
        from agents import pipeline_coordinator
        actual_knowledge_dir = Path(pipeline_coordinator.__file__).parent / "logs" / "pipeline_knowledge"
        
        if actual_knowledge_dir.exists():
            shutil.rmtree(str(actual_knowledge_dir))
            
        with patch("agents.dream_engine.dream_engine", mock_dream_engine):
            await pc._trigger_dream_learning(ctx)
            
            assert actual_knowledge_dir.exists()
            files = list(actual_knowledge_dir.glob("run_*.json"))
            assert len(files) == 1
            
            mock_dream_engine.increment_session_count.assert_called_once()
            mock_dream_engine.should_dream.assert_called_once()
            mock_dream_engine.run_dream_cycle.assert_called_once()
            
            shutil.rmtree(str(actual_knowledge_dir))

    @pytest.mark.asyncio
    async def test_trigger_dream_learning_exception(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=5, session_id="s123")
        
        with patch("agents.dream_engine.dream_engine", side_effect=Exception("Dream engine error")):
            await pc._trigger_dream_learning(ctx)

    @pytest.mark.asyncio
    async def test_execute_harness_integration_full_flow(self):
        """565 (StageResult.append) をカバーするために _run_retention_analysis を AsyncMock(StageResult) に差し替える"""
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="")
        ctx.quality_score = 95
        
        mock_progress = MagicMock()
        pc.set_progress_callback(mock_progress)
        
        mock_ge = MagicMock()
        mock_ge.check_permission.return_value = True
        mock_ge.check_rate_limit.return_value = True
        
        mock_sm = MagicMock()
        mock_sm.resume_session.return_value = None
        mock_session = MagicMock()
        mock_session.session_id = "new_session_id_456"
        mock_sm.create_session.return_value = mock_session
        
        mock_hook_system = AsyncMock()
        mock_pre_output = MagicMock()
        mock_pre_output.permission_decision = "allow"
        mock_hook_system.fire.return_value = mock_pre_output
        
        harness = {
            "hook_system": mock_hook_system,
            "HookEvent": MagicMock(),
            "HookInput": MagicMock(),
            "HookOutput": MagicMock(),
            "session_manager": mock_sm,
            "governance_engine": mock_ge,
            "trace_span": MagicMock(),
        }
        
        def side_effect_init_harness(context):
            context.session_id = "new_session_id_456"
            return harness
            
        pc._init_harness = MagicMock(side_effect=side_effect_init_harness)
        
        for w in pc.workers:
            w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail="ok", duration_seconds=0.1, data={}))
            w.verify = MagicMock(return_value=True)
            
        pc._run_retention_analysis = AsyncMock(
            return_value=StageResult(stage_name="Retention分析", success=True, detail="ok", duration_seconds=0.1, data={})
        )
            
        mock_usage = MagicMock(free=10 * 1024 * 1024 * 1024)
        with patch("shutil.disk_usage", return_value=mock_usage):
            res = await pc.execute(ctx)
            assert res["status"] == "completed"
            assert ctx.session_id == "new_session_id_456"
            assert ctx.render_mode == "production"
            # 565 が実行されて ctx.stage_results に追加されていること
            assert any(r.stage_name == "Retention分析" for r in ctx.stage_results)

    def test_finalize_harness_error(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        ctx.warnings = ["fatal error"]
        
        mock_ge = MagicMock()
        mock_sm = MagicMock()
        harness = {
            "governance_engine": mock_ge,
            "session_manager": mock_sm,
            "trace_span": MagicMock(),
        }
        
        pc._finalize_harness(harness, ctx, status="error")
        mock_sm.error_session.assert_called_once_with(ctx.session_id, "fatal error")

    @pytest.mark.asyncio
    async def test_execute_quality_improvement_loop_fallback_failed(self):
        """559 をカバーするためにループ失敗を再現"""
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        ctx.quality_score = 85
        ctx.quality_feedback = []
        
        pc._init_harness = MagicMock(return_value=None)
        pc._finalize_harness = MagicMock()
        pc._fire_pre_hook = AsyncMock(return_value=(False, None))
        pc._fire_post_hook = AsyncMock()
        
        for w in pc.workers:
            w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail="ok", duration_seconds=0.1, data={}))
            w.verify = MagicMock(return_value=True)
            
        from agents.workers import QualityGateWorker, PreviewWorker
        qg_worker = pc._find_worker(QualityGateWorker)
        qg_worker.verify = MagicMock(return_value=False)
        qg_worker.execute = AsyncMock(return_value=StageResult(stage_name=qg_worker.name, success=True, detail="ok", duration_seconds=0.1, data={"feedback": ["still low"]}))
        
        preview_worker = pc._find_worker(PreviewWorker)
        preview_worker.execute = AsyncMock(return_value=StageResult(stage_name=preview_worker.name, success=True, detail="ok", duration_seconds=0.1, data={}))
        
        mock_usage = MagicMock(free=10 * 1024 * 1024 * 1024)
        with patch("shutil.disk_usage", return_value=mock_usage), \
             patch("builtins.__import__", side_effect=ImportError("evaluator_optimizer not found")):
            res = await pc.execute(ctx)
            assert res["status"] == "completed"

    @pytest.mark.asyncio
    async def test_execute_performance_budget_save_report_exception(self):
        """585-586 をカバーするために save_report での例外発生を模倣"""
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        
        pc._init_harness = MagicMock(return_value=None)
        pc._finalize_harness = MagicMock()
        pc._fire_pre_hook = AsyncMock(return_value=(False, None))
        pc._fire_post_hook = AsyncMock()
        
        for w in pc.workers:
            w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail="ok", duration_seconds=0.1, data={}))
            w.verify = MagicMock(return_value=True)
            
        mock_perf_manager = MagicMock()
        mock_perf_manager.generate_report.side_effect = Exception("Failed to generate report")
        
        mock_usage = MagicMock(free=10 * 1024 * 1024 * 1024)
        with patch("shutil.disk_usage", return_value=mock_usage), \
             patch("services.performance_budget_manager.PerformanceBudgetManager", return_value=mock_perf_manager):
            res = await pc.execute(ctx)
            assert res["status"] == "completed"

    @pytest.mark.asyncio
    async def test_quality_improvement_loop_preview_fail(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        ctx.quality_score = 85
        ctx.quality_feedback = []
        
        from agents.workers import QualityGateWorker, PreviewWorker
        qg_worker = pc._find_worker(QualityGateWorker)
        preview_worker = pc._find_worker(PreviewWorker)
        
        qg_worker.verify = MagicMock(return_value=False)
        preview_worker.execute = AsyncMock(return_value=StageResult(stage_name=preview_worker.name, success=False, detail="Failed to render preview", duration_seconds=0.1, data={}))
        
        res = await pc._quality_improvement_loop(ctx)
        assert res is False

    @pytest.mark.asyncio
    async def test_execute_render_worker_fail(self):
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        ctx.quality_score = 95
        
        pc._init_harness = MagicMock(return_value=None)
        pc._finalize_harness = MagicMock()
        pc._fire_pre_hook = AsyncMock(return_value=(False, None))
        pc._fire_post_hook = AsyncMock()
        
        for w in pc.workers:
            w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail="ok", duration_seconds=0.1, data={}))
            w.verify = MagicMock(return_value=True)
            
        from agents.workers import RenderWorker
        render_worker = pc._find_worker(RenderWorker)
        render_worker.execute = AsyncMock(return_value=StageResult(stage_name=render_worker.name, success=False, detail="Failed to render final video", duration_seconds=0.1, data={}))
        
        mock_usage = MagicMock(free=10 * 1024 * 1024 * 1024)
        with patch("shutil.disk_usage", return_value=mock_usage):
            res = await pc.execute(ctx)
            assert res["status"] == "completed"

    @pytest.mark.asyncio
    async def test_fire_post_hook_success_and_failure(self):
        """287-292 のカバー: post_hook 失敗系パス"""
        pc = PipelineCoordinator()
        ctx = PipelineContext(video_path="test.mp4", target_minutes=10, session_id="s123")
        
        mock_hook_system = AsyncMock()
        mock_hook_event = MagicMock()
        harness = {
            "hook_system": mock_hook_system,
            "HookInput": MagicMock,
            "HookEvent": mock_hook_event,
            "session_manager": MagicMock(),
        }
        
        worker = pc.workers[0]
        success_result = StageResult(stage_name=worker.name, success=True, detail="ok", duration_seconds=1.0, data={"some": "data"})
        await pc._fire_post_hook(harness, worker, success_result, ctx)
        harness["session_manager"].record_tool_call.assert_called_once()
        
        harness["session_manager"].reset_mock()
        fail_result = StageResult(stage_name=worker.name, success=False, detail="some error", duration_seconds=1.0, data={})
        await pc._fire_post_hook(harness, worker, fail_result, ctx)
        mock_hook_system.fire.assert_called()

def test_quality_gate_agent_ebvp_asserts():
    from quality_gate_agent import QualityGateAgent
    agent = QualityGateAgent()
    
    # 誤字脱字テスト
    content_typo = {
        "segments": [{"text": "以外と美味しい"}]
    }
    report_typo = agent.run_gate(content_typo)
    assert len(report_typo.issues) > 0
    assert "誤りの可能性があります" not in report_typo.issues[0].message
    assert "誤りです" in report_typo.issues[0].message
    
    # AI固有名詞テスト
    content_scene = {
        "scenes": [{"source_type": "AI", "name": "キタハラ"}]
    }
    report_scene = agent.run_gate(content_scene)
    assert len(report_scene.issues) > 0
    assert "含まれている可能性" not in report_scene.issues[0].message
    assert "含まれています" in report_scene.issues[0].message
