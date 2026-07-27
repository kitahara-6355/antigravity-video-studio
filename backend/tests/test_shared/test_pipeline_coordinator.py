import pytest
import sys
# Original modules backup for clearing imports contamination
_original_modules = sys.modules.copy()
import os
import json
import io
import asyncio
import types
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

# 依存モジュールのダミーを types.ModuleType で作成して登録
def create_dummy_module(name, attrs=None):
    mod = types.ModuleType(name)
    if attrs:
        for k, v in attrs.items():
            setattr(mod, k, v)
    sys.modules[name] = mod
    return mod

# harness.hooks のダミークラス定義
class DummyHookEvent:
    PRE_TOOL_USE = "PRE_TOOL_USE"
    POST_TOOL_USE = "POST_TOOL_USE"
    POST_TOOL_USE_FAILURE = "POST_TOOL_USE_FAILURE"

class DummyHookInput:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

class DummyHookOutput:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

dummy_harness_hooks = create_dummy_module("harness.hooks")
dummy_harness_hooks.HookEvent = DummyHookEvent
dummy_harness_hooks.HookInput = DummyHookInput
dummy_harness_hooks.HookOutput = DummyHookOutput

dummy_harness_eval_opt = create_dummy_module("harness.evaluator_optimizer")
dummy_harness_eval_opt.evaluator_optimizer = MagicMock()

# 各ダミーモジュールの設定
dummy_proper_noun = create_dummy_module("proper_noun_dict")
dummy_proper_noun.apply_dictionary = MagicMock(return_value=("corrected_text", ["correction"]))
dummy_proper_noun.proper_noun_dict = MagicMock()

dummy_ai_proofreader = create_dummy_module("subtitle_engine.ai_proofreader")
dummy_ai_proofreader.proofread_segments = MagicMock(side_effect=lambda segs: [{"text": "proofread_text"}])

dummy_prod_pipeline = create_dummy_module("agents.production_pipeline")
dummy_prod_pipeline.propose_smart_cut = MagicMock(return_value=json.dumps({
    "proposals": [{"segments": [{"text": "smart_cut"}], "estimated_duration": 100}]
}))
dummy_prod_pipeline.generate_youtube_metadata = MagicMock(return_value=json.dumps({
    "status": "success",
    "metadata": {
        "titles": ["AI Title"],
        "tags": ["AI", "Vlog"],
        "description": "AI Description",
        "chapters": [{"time": "0:00", "title": "Start"}]
    }
}))

dummy_smart_cut = create_dummy_module("smart_cut_engine")
dummy_smart_cut.render_smart_cut = MagicMock(return_value=True)

dummy_quality_plugins = create_dummy_module("quality_gate_plugins")
dummy_quality_plugins.run_all_plugins = MagicMock(return_value={
    "total_deductions": 5,
    "feedback": ["Deducted 5 points"],
    "category_report": [],
    "category_scores": {}
})

dummy_video_editor_engine = create_dummy_module("video_editor_engine")
mock_video_editor = MagicMock()
mock_video_editor.ffmpeg.is_available.return_value = True
mock_video_editor.ffmpeg._get_encode_args.return_value = ["-c:v", "libx264"]
mock_video_editor.ffmpeg.run_command.return_value = (True, "success")
dummy_video_editor_engine.video_editor = mock_video_editor

dummy_template_config = create_dummy_module("template_config")
dummy_template_config.template_config = MagicMock()
dummy_template_config.template_config.is_active = False
dummy_template_config.template_config.get_active_benchmarks.return_value = {
    "audio_loudness_lufs": -16.0
}

dummy_dream_engine = create_dummy_module("agents.dream_engine")
dummy_dream_engine.dream_engine = MagicMock()
dummy_dream_engine.dream_engine.should_dream = AsyncMock(return_value=False)

dummy_retention = create_dummy_module("plugins.retention_map_plugin")
dummy_retention.retention_map_plugin = MagicMock()
mock_report = MagicMock()
mock_report.overall_risk_assessment = "low"
mock_report.suggestions = ["suggestion1"]
mock_report.segments = []
dummy_retention.retention_map_plugin.analyze_retention_risks.return_value = mock_report

# harness関連のダミーモジュール
mock_harness_session_mgr = MagicMock()
mock_harness_gov_eng = MagicMock()
mock_harness_hook_sys = MagicMock()
mock_harness_hook_sys.fire = AsyncMock()

dummy_harness = create_dummy_module("harness")
dummy_harness.hook_system = mock_harness_hook_sys
dummy_harness.session_manager = mock_harness_session_mgr
dummy_harness.governance_engine = mock_harness_gov_eng

from backend.agents._deprecated.pipeline_coordinator import (
    PipelineCoordinator,
    PipelineContext,
    StageResult,
    TranscribeWorker,
    ProofreadWorker,
    SmartCutWorker,
    PreviewWorker,
    QualityGateWorker,
    RenderWorker,
    YouTubeOptWorker,
)

# Collect created dummy modules for test execution phase
_dummy_modules_names = [
    "harness.hooks", "harness.evaluator_optimizer", "proper_noun_dict",
    "subtitle_engine.ai_proofreader", "agents.production_pipeline",
    "smart_cut_engine", "quality_gate_plugins", "video_editor_engine",
    "template_config", "agents.dream_engine", "plugins.retention_map_plugin",
    "harness"
]
_dummy_modules = {name: sys.modules[name] for name in _dummy_modules_names if name in sys.modules}

# Restore original modules after import phase to prevent test discovery contamination
for name in list(sys.modules.keys()):
    if name not in _original_modules:
        del sys.modules[name]
sys.modules.update(_original_modules)

@pytest.fixture(autouse=True, scope="function")
def mock_sys_modules():
    # Inject dummy modules during test execution
    saved = {}
    for name, dummy in _dummy_modules.items():
        saved[name] = sys.modules.get(name)
        sys.modules[name] = dummy
    yield
    # Restore original modules after test execution
    for name, orig in saved.items():
        if orig is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = orig


@pytest.fixture(autouse=True)
def reset_mocks():
    dummy_proper_noun.apply_dictionary.reset_mock()
    dummy_proper_noun.apply_dictionary.return_value = ("corrected_text", ["correction"])
    
    dummy_ai_proofreader.proofread_segments.reset_mock()
    dummy_ai_proofreader.proofread_segments.side_effect = lambda segs: [{"text": "proofread_text"}]
    
    dummy_prod_pipeline.propose_smart_cut.reset_mock()
    dummy_prod_pipeline.propose_smart_cut.return_value = json.dumps({
        "proposals": [{"segments": [{"text": "smart_cut"}], "estimated_duration": 100}]
    })
    
    dummy_prod_pipeline.generate_youtube_metadata.reset_mock()
    dummy_prod_pipeline.generate_youtube_metadata.return_value = json.dumps({
        "status": "success",
        "metadata": {
            "titles": ["AI Title"],
            "tags": ["AI", "Vlog"],
            "description": "AI Description",
            "chapters": [{"time": "0:00", "title": "Start"}]
        }
    })
    
    dummy_smart_cut.render_smart_cut.reset_mock()
    dummy_smart_cut.render_smart_cut.return_value = True
    
    dummy_quality_plugins.run_all_plugins.reset_mock()
    dummy_quality_plugins.run_all_plugins.return_value = {
        "total_deductions": 5,
        "feedback": ["Deducted 5 points"],
        "category_report": [],
        "category_scores": {}
    }
    
    mock_video_editor.ffmpeg.run_command.reset_mock()
    mock_video_editor.ffmpeg.run_command.return_value = (True, "success")
    
    mock_harness_hook_sys.fire.reset_mock()
    mock_harness_hook_sys.fire.side_effect = None
    mock_harness_hook_sys.fire.return_value = AsyncMock()


# ============================================================
# Worker Tests
# ============================================================

@pytest.mark.asyncio
async def test_transcribe_worker_cached(tmp_path):
    video_path = tmp_path / "video.mp4"
    checkpoint_path = tmp_path / "_whisper_segments.jsonl"
    
    dummy_segments = [{"start": 0.0, "end": 2.0, "text": "こんにちは"}] * 30
    with open(checkpoint_path, "w", encoding="utf-8") as f:
        for seg in dummy_segments:
            f.write(json.dumps(seg) + "\n")
            
    ctx = PipelineContext(video_path=str(video_path))
    ctx.stage_results = []
    worker = TranscribeWorker()
    
    result = await worker.execute(ctx)
    assert result.success
    assert "キャッシュ" in result.detail
    assert len(ctx.segments) == 30
    assert worker.verify(result)


@pytest.mark.asyncio
async def test_transcribe_worker_subprocess_success(tmp_path, safe_popen_mock):
    video_path = tmp_path / "video.mp4"
    checkpoint_path = tmp_path / "_whisper_segments.jsonl"
    
    dummy_segments = [{"start": 0.0, "end": 2.0, "text": "こんにちは"}]
    with open(checkpoint_path, "w", encoding="utf-8") as f:
        for seg in dummy_segments:
            f.write(json.dumps(seg) + "\n")
            
    ctx = PipelineContext(video_path=str(video_path))
    ctx.stage_results = []
    worker = TranscribeWorker()
    
    proc = safe_popen_mock(returncode=0)
    proc.stdout = io.StringIO('{"status": "completed", "device": "cpu"}\n')
    
    with patch("subprocess.Popen", return_value=proc):
        result = await worker.execute(ctx)
        assert result.success
        assert len(ctx.segments) == 1
        assert result.data["device"] == "cpu"


@pytest.mark.asyncio
async def test_transcribe_worker_subprocess_timeout(tmp_path):
    video_path = tmp_path / "video.mp4"
    checkpoint_path = tmp_path / "_whisper_segments.jsonl"
    
    # ensure_ascii=False でエスケープを防ぎ、サイズを700バイト付近に精密調整する
    # 7件 * 約102バイト => 約714バイト (500バイト超かつ1000バイト未満を確実に満たす)
    dummy_segments = [{"start": 0.0, "end": 2.0, "text": "こんにちは、テスト用の長いダミー文字列です。"}] * 7
    with open(checkpoint_path, "w", encoding="utf-8") as f:
        for seg in dummy_segments:
            f.write(json.dumps(seg, ensure_ascii=False) + "\n")
            
    ctx = PipelineContext(video_path=str(video_path))
    ctx.stage_results = []
    worker = TranscribeWorker()
    
    proc = MagicMock()
    # 1回目のwaitでTimeoutExpiredを投げ、2回目のwait(timeout=10)は正常終了させる
    proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="whisper", timeout=600), None]
    proc.poll.return_value = None
    proc.kill.return_value = None
    proc.stdout = io.StringIO("")
    
    with patch("subprocess.Popen", return_value=proc):
        result = await worker.execute(ctx)
        assert result.success
        assert result.data.get("device") == "timeout_partial"


@pytest.mark.asyncio
async def test_transcribe_worker_subprocess_timeout_no_file(tmp_path):
    video_path = tmp_path / "video.mp4"
    ctx = PipelineContext(video_path=str(video_path))
    ctx.stage_results = []
    worker = TranscribeWorker()
    
    proc = MagicMock()
    proc.wait.side_effect = subprocess.TimeoutExpired(cmd="whisper", timeout=600)
    proc.poll.return_value = None
    proc.kill.return_value = None
    proc.stdout = io.StringIO("")
    
    with patch("subprocess.Popen", return_value=proc):
        result = await worker.execute(ctx)
        assert not result.success
        assert "timed out" in result.detail.lower()


@pytest.mark.asyncio
async def test_transcribe_worker_subprocess_failure(tmp_path, safe_popen_mock):
    video_path = tmp_path / "video.mp4"
    ctx = PipelineContext(video_path=str(video_path))
    ctx.stage_results = []
    worker = TranscribeWorker()
    
    proc = safe_popen_mock(returncode=1)
    proc.stdout = io.StringIO("")
    proc.stderr = io.StringIO("GPU out of memory")
    
    with patch("subprocess.Popen", return_value=proc):
        result = await worker.execute(ctx)
        assert not result.success
        assert "Whisperサブプロセス失敗" in result.detail


@pytest.mark.asyncio
async def test_proofread_worker_success():
    ctx = PipelineContext(video_path="video.mp4")
    ctx.stage_results = []
    ctx.segments = [{"text": "元のテキスト"}]
    worker = ProofreadWorker()
    
    result = await worker.execute(ctx)
    assert result.success
    assert result.data["total"] == 2
    assert ctx.segments[0]["text"] == "proofread_text"


@pytest.mark.asyncio
async def test_proofread_worker_import_error():
    ctx = PipelineContext(video_path="video.mp4")
    ctx.stage_results = []
    ctx.segments = [{"text": "元のテキスト"}]
    worker = ProofreadWorker()
    
    with patch("proper_noun_dict.apply_dictionary", side_effect=ImportError):
        with patch("subtitle_engine.ai_proofreader.proofread_segments", side_effect=Exception("API Error")):
            result = await worker.execute(ctx)
            assert result.success
            assert "AI校閲(Gemini)" in ctx.skipped_features


@pytest.mark.asyncio
async def test_smart_cut_worker_success():
    ctx = PipelineContext(video_path="video.mp4")
    ctx.stage_results = []
    ctx.segments = [{"text": "セグメント1"}]
    worker = SmartCutWorker()
    
    result = await worker.execute(ctx)
    assert result.success
    assert len(ctx.selected_segments) == 1
    assert ctx.selected_segments[0]["text"] == "smart_cut"


@pytest.mark.asyncio
async def test_smart_cut_worker_failure():
    ctx = PipelineContext(video_path="video.mp4")
    ctx.stage_results = []
    ctx.segments = [{"text": "セグメント1"}]
    worker = SmartCutWorker()
    
    with patch("agents.production_pipeline.propose_smart_cut", side_effect=Exception("Error")):
        result = await worker.execute(ctx)
        assert result.success
        assert "SmartCut" in ctx.skipped_features
        assert ctx.selected_segments == ctx.segments


@pytest.mark.asyncio
async def test_preview_worker_success(tmp_path):
    mock_vault = tmp_path / "vault"
    ctx = PipelineContext(video_path="video.mp4")
    ctx.stage_results = []
    worker = PreviewWorker()
    
    with patch("safe_io.VAULT_OUTPUTS_DIR", mock_vault):
        def side_effect_render(segs, v_path, out_path):
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_text("dummy mp4 data", encoding="utf-8")
            return True
        dummy_smart_cut.render_smart_cut.side_effect = side_effect_render
        
        result = await worker.execute(ctx)
        assert result.success
        assert ctx.preview_path is not None
        assert worker.verify(result)
        
        dummy_smart_cut.render_smart_cut.side_effect = None


@pytest.mark.asyncio
async def test_preview_worker_failure(tmp_path):
    mock_vault = tmp_path / "vault"
    ctx = PipelineContext(video_path="video.mp4")
    ctx.stage_results = []
    worker = PreviewWorker()
    
    with patch("safe_io.VAULT_OUTPUTS_DIR", mock_vault):
        dummy_smart_cut.render_smart_cut.return_value = False
        result = await worker.execute(ctx)
        assert not result.success
        assert not worker.verify(result)


@pytest.mark.asyncio
async def test_quality_gate_worker_success():
    ctx = PipelineContext(video_path="video.mp4")
    ctx.stage_results = []
    worker = QualityGateWorker()
    
    result = await worker.execute(ctx)
    assert result.success
    assert ctx.quality_score == 95
    assert worker.verify(result)


@pytest.mark.asyncio
async def test_quality_gate_worker_fallback(tmp_path):
    ctx = PipelineContext(video_path="video.mp4")
    ctx.stage_results = []
    ctx.preview_path = str(tmp_path / "preview.mp4")
    Path(ctx.preview_path).write_text("a" * 500, encoding="utf-8")
    
    worker = QualityGateWorker()
    
    with patch("quality_gate_plugins.run_all_plugins", side_effect=ImportError):
        result = await worker.execute(ctx)
        assert not result.success
        assert ctx.quality_score == 70


@pytest.mark.asyncio
async def test_quality_gate_worker_fallback_no_file():
    ctx = PipelineContext(video_path="video.mp4")
    ctx.stage_results = []
    ctx.preview_path = None
    worker = QualityGateWorker()
    
    with patch("quality_gate_plugins.run_all_plugins", side_effect=ImportError):
        result = await worker.execute(ctx)
        assert not result.success
        assert ctx.quality_score == 80


@pytest.mark.asyncio
async def test_render_worker_success(tmp_path):
    mock_vault = tmp_path / "vault"
    ctx = PipelineContext(video_path="video.mp4")
    ctx.stage_results = []
    ctx.preview_path = str(tmp_path / "preview.mp4")
    Path(ctx.preview_path).write_text("preview content", encoding="utf-8")
    
    worker = RenderWorker()
    
    with patch("safe_io.VAULT_OUTPUTS_DIR", mock_vault):
        def side_effect_run(cmd, timeout=1800):
            Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
            Path(cmd[-1]).write_text("rendered final mp4 data" * 100, encoding="utf-8")
            return True, "success"
        mock_video_editor.ffmpeg.run_command.side_effect = side_effect_run
        
        result = await worker.execute(ctx)
        assert result.success
        assert ctx.final_path is not None
        
        mock_video_editor.ffmpeg.run_command.side_effect = None


@pytest.mark.asyncio
async def test_render_worker_no_preview():
    ctx = PipelineContext(video_path="video.mp4")
    ctx.stage_results = []
    ctx.preview_path = None
    worker = RenderWorker()
    
    result = await worker.execute(ctx)
    assert not result.success
    assert "レンダリング元なし" in result.detail


@pytest.mark.asyncio
async def test_youtube_opt_worker_success():
    ctx = PipelineContext(video_path="video.mp4")
    ctx.stage_results = []
    ctx.segments = [{"text": "セグメント"}]
    worker = YouTubeOptWorker()
    
    result = await worker.execute(ctx)
    assert result.success
    assert ctx.metadata["titles"] == ["AI Title"]


@pytest.mark.asyncio
async def test_youtube_opt_worker_fallback():
    ctx = PipelineContext(video_path="video.mp4")
    ctx.stage_results = []
    ctx.segments = [{"text": "こんにちは", "start": 0, "end": 5}]
    worker = YouTubeOptWorker()
    
    with patch("agents.production_pipeline.generate_youtube_metadata", side_effect=Exception("API Error")):
        result = await worker.execute(ctx)
        assert result.success
        assert "簡易メタデータ生成" in result.detail
        assert "chapters" in ctx.metadata


# ============================================================
# Coordinator Tests
# ============================================================

@pytest.mark.asyncio
async def test_coordinator_execute_disk_space_error():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="video.mp4")
    ctx.stage_results = []
    
    mock_disk = MagicMock(free=0.5 * 1024**3)
    with patch("shutil.disk_usage", return_value=mock_disk):
        result = await coordinator.execute(ctx)
        assert result["status"] == "error"
        assert "ディスク空き容量不足" in result["error"]


@pytest.mark.asyncio
async def test_coordinator_execute_disk_space_warning(tmp_path):
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "video.mp4"))
    ctx.stage_results = []
    
    for worker in coordinator.workers:
        worker.execute = AsyncMock(return_value=StageResult(stage_name=worker.name, success=True, detail="success"))
        worker.verify = MagicMock(return_value=True)
        
    mock_disk = MagicMock(free=3 * 1024**3)
    with patch("shutil.disk_usage", return_value=mock_disk):
        result = await coordinator.execute(ctx)
        assert result["status"] == "completed"
        assert any("ディスク残量注意" in w for w in ctx.warnings)


@pytest.mark.asyncio
async def test_coordinator_execute_retry_and_success():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="video.mp4")
    ctx.stage_results = []
    
    mock_worker = MagicMock()
    mock_worker.name = "文字起こし"
    mock_worker.index = 0
    mock_worker.execute = AsyncMock(side_effect=[
        StageResult(stage_name="文字起こし", success=False, detail="Temporary failure"),
        StageResult(stage_name="文字起こし", success=True, detail="Success after retry")
    ])
    mock_worker.verify.side_effect = [False, True]
    
    coordinator.workers = [mock_worker]
    
    result = await coordinator.execute(ctx)
    assert result["status"] == "completed"
    assert mock_worker.execute.call_count == 2


@pytest.mark.asyncio
async def test_coordinator_execute_fatal_error():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="video.mp4")
    ctx.stage_results = []
    
    mock_worker = MagicMock()
    mock_worker.name = "文字起こし"
    mock_worker.index = 0
    mock_worker.execute = AsyncMock(return_value=StageResult(stage_name="文字起こし", success=False, detail="Fatal error"))
    mock_worker.verify.return_value = False
    
    coordinator.workers = [mock_worker]
    
    result = await coordinator.execute(ctx)
    assert result["status"] == "error"
    assert "Fatal error" in result["error"]


@pytest.mark.asyncio
async def test_coordinator_quality_improvement_loop():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="video.mp4")
    ctx.stage_results = [StageResult(stage_name="品質チェック", success=False, data={"feedback": ["low quality"]})]
    
    preview_worker = coordinator._find_worker(PreviewWorker)
    quality_worker = coordinator._find_worker(QualityGateWorker)
    
    preview_worker.execute = AsyncMock(return_value=StageResult(stage_name="プレビュー生成", success=True))
    quality_worker.execute = AsyncMock(return_value=StageResult(stage_name="品質チェック", success=True))
    
    quality_worker.verify = MagicMock(side_effect=[False, True])
    
    improved = await coordinator._quality_improvement_loop(ctx)
    assert improved
    assert preview_worker.execute.call_count == 2
    assert quality_worker.execute.call_count == 2


# ============================================================
# Harness Integration Tests
# ============================================================

@pytest.mark.asyncio
async def test_harness_mode_disabled():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="video.mp4")
    ctx.stage_results = []
    
    with patch.dict(os.environ, {"HARNESS_MODE": "disabled"}):
        with patch.object(coordinator, "execute", return_value={"status": "completed"}) as mock_exec:
            result = await coordinator.execute_with_harness(ctx)
            assert result["status"] == "completed"
            mock_exec.assert_called_once_with(ctx)


@pytest.mark.asyncio
async def test_harness_mode_enabled_allow():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="video.mp4")
    ctx.stage_results = []
    
    for worker in coordinator.workers:
        worker.execute = AsyncMock(return_value=StageResult(stage_name=worker.name, success=True, detail="success"))
        worker.verify = MagicMock(return_value=True)
        
    mock_session = MagicMock()
    mock_session.session_id = "test-session"
    mock_harness_session_mgr.create_session.return_value = mock_session
    mock_harness_session_mgr.resume_session.return_value = None
    
    mock_decision = MagicMock()
    mock_decision.permission_decision = "allow"
    
    mock_harness_hook_sys.fire = AsyncMock(return_value=mock_decision)
    
    with patch.dict(os.environ, {"HARNESS_MODE": "enabled"}):
        result = await coordinator.execute_with_harness(ctx)
        assert result["status"] == "completed"
        assert mock_harness_hook_sys.fire.call_count > 0


@pytest.mark.asyncio
async def test_harness_mode_enabled_deny_fatal():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="video.mp4")
    ctx.stage_results = []
    
    for worker in coordinator.workers:
        worker.execute = AsyncMock(return_value=StageResult(stage_name=worker.name, success=True, detail="success"))
        worker.verify = MagicMock(return_value=True)
        
    mock_session = MagicMock()
    mock_session.session_id = "test-session"
    mock_harness_session_mgr.create_session.return_value = mock_session
    mock_harness_session_mgr.resume_session.return_value = None
    
    mock_decision = MagicMock()
    mock_decision.permission_decision = "deny"
    mock_decision.permission_decision_reason = "Not allowed to execute"
    
    mock_harness_hook_sys.fire = AsyncMock(return_value=mock_decision)
    
    with patch.dict(os.environ, {"HARNESS_MODE": "enabled"}):
        result = await coordinator.execute_with_harness(ctx)
        assert result["status"] == "error"
        assert "Not allowed to execute" in result["error"]
