import sys
import pytest
import json
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
from PIL import Image, ImageDraw

# プロジェクトルートとbackendをパスに追加
project_root = str(Path(__file__).parent.parent.resolve())
backend_dir = str(Path(__file__).parent.parent.resolve() / "backend")
if project_root not in sys.path:
    sys.path.insert(0, project_root)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from agents.pipeline_types import PipelineContext, StageResult, PipelineStageWorker
from agents.pipeline_coordinator import (
    PipelineCoordinator,
    generate_pipeline_coordinator_thumbnail,
    validate_pipeline_coordinator_thumbnail,
    resolve_pipeline_coordinator_thumbnail_task,
)

# ===========================================================================
# 1. サムネイル生成・検証関連のテスト (A分類)
# ===========================================================================

def test_generate_pipeline_coordinator_thumbnail(tmp_path):
    output_path = tmp_path / "test_thumb.png"
    res_path = generate_pipeline_coordinator_thumbnail(output_path, text="Test Text")
    assert res_path == output_path
    assert output_path.exists()
    
    with Image.open(output_path) as img:
        assert img.size == (1280, 720)
        assert img.mode == "RGB"

def test_validate_pipeline_coordinator_thumbnail_success(tmp_path):
    output_path = tmp_path / "test_thumb.png"
    generate_pipeline_coordinator_thumbnail(output_path, text="Test Success")
    
    info = validate_pipeline_coordinator_thumbnail(output_path)
    assert info["path"] == str(output_path)
    assert info["width"] == 1280
    assert info["height"] == 720
    assert info["size_bytes"] > 0

def test_validate_pipeline_coordinator_thumbnail_file_not_found():
    with pytest.raises(FileNotFoundError):
        validate_pipeline_coordinator_thumbnail("non_existent_file.png")

def test_validate_pipeline_coordinator_thumbnail_too_large(tmp_path):
    output_path = tmp_path / "large_thumb.png"
    output_path.write_bytes(b"\x00" * (4 * 1024 * 1024 + 10)) # 4MB超
    with pytest.raises(ValueError, match="exceeds 4MB limit"):
        validate_pipeline_coordinator_thumbnail(output_path)

def test_validate_pipeline_coordinator_thumbnail_corrupted(tmp_path):
    output_path = tmp_path / "corrupted_thumb.png"
    output_path.write_bytes(b"not an image file")
    with pytest.raises(ValueError, match="corrupted or invalid format"):
        validate_pipeline_coordinator_thumbnail(output_path)

def test_validate_pipeline_coordinator_thumbnail_invalid_size(tmp_path):
    output_path = tmp_path / "small_thumb.png"
    img = Image.new("RGB", (640, 360), color="blue")
    img.save(output_path, "PNG")
    with pytest.raises(ValueError, match="must be at least 1280x720"):
        validate_pipeline_coordinator_thumbnail(output_path)

def test_validate_pipeline_coordinator_thumbnail_invalid_aspect(tmp_path):
    output_path = tmp_path / "aspect_thumb.png"
    img = Image.new("RGB", (1280, 800), color="blue") # 16:10
    img.save(output_path, "PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        validate_pipeline_coordinator_thumbnail(output_path)

@pytest.mark.asyncio
async def test_resolve_pipeline_coordinator_thumbnail_task(tmp_path):
    with patch("agents.pipeline_coordinator.THUMBNAIL_OUTPUT_DIR", tmp_path):
        res_json = await resolve_pipeline_coordinator_thumbnail_task("task_123")
        info = json.loads(res_json)
        assert info["width"] == 1280
        assert info["height"] == 720
        assert Path(info["path"]).name == "task_123.png"

# ===========================================================================
# 2. PipelineCoordinator 初期化・基本ヘルパーのテスト
# ===========================================================================

def test_pipeline_coordinator_init():
    coordinator = PipelineCoordinator()
    assert len(coordinator.workers) == 7
    assert coordinator._progress_callback is None
    assert coordinator._ws_broadcast is None

def test_pipeline_coordinator_find_worker():
    coordinator = PipelineCoordinator()
    from agents.workers import TranscribeWorker, RenderWorker
    
    worker = coordinator._find_worker(TranscribeWorker)
    assert worker is not None
    assert isinstance(worker, TranscribeWorker)
    
    # 存在しないWorker型
    class DummyWorker:
        pass
    assert coordinator._find_worker(DummyWorker) is None

def test_pipeline_coordinator_set_callbacks():
    coordinator = PipelineCoordinator()
    cb = lambda *args: None
    ws = lambda *args: None
    
    coordinator.set_progress_callback(cb)
    coordinator.set_ws_broadcast(ws)
    assert coordinator._progress_callback == cb
    assert coordinator._ws_broadcast == ws

@pytest.mark.asyncio
async def test_pipeline_coordinator_notify():
    coordinator = PipelineCoordinator()
    cb_calls = []
    ws_calls = []
    
    def cb(stage_index, status, detail, progress, data):
        cb_calls.append((stage_index, status, detail, progress, data))
        
    async def ws(msg):
        ws_calls.append(msg)
        
    coordinator.set_progress_callback(cb)
    coordinator.set_ws_broadcast(ws)
    
    from agents.workers import TranscribeWorker
    worker = TranscribeWorker()
    
    await coordinator._notify(worker, "running", "detail_text", 50, {"key": "val"})
    
    assert len(cb_calls) == 1
    assert cb_calls[0] == (worker.index, "running", "detail_text", 50, {"key": "val"})
    
    assert len(ws_calls) == 1
    assert ws_calls[0]["type"] == "pipeline_progress"
    assert ws_calls[0]["stage_index"] == worker.index
    assert ws_calls[0]["status"] == "running"
    assert ws_calls[0]["detail"] == "detail_text"
    assert ws_calls[0]["progress"] == 50
    assert ws_calls[0]["data"] == {"key": "val"}

# ===========================================================================
# 3. ディスク容量チェックのテスト
# ===========================================================================

def test_check_disk_space_sufficient(tmp_path):
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "dummy.mp4"))
    
    # 10GBの空きをシミュレート
    mock_usage = MagicMock(free=10 * 1024 * 1024 * 1024)
    with patch("shutil.disk_usage", return_value=mock_usage):
        free_gb = coordinator._check_disk_space(ctx)
        assert free_gb == 10.0
        assert len(ctx.warnings) == 0

def test_check_disk_space_warning(tmp_path):
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "dummy.mp4"))
    
    # 3GBの空きをシミュレート (警告レベル)
    mock_usage = MagicMock(free=3 * 1024 * 1024 * 1024)
    with patch("shutil.disk_usage", return_value=mock_usage):
        free_gb = coordinator._check_disk_space(ctx)
        assert free_gb == 3.0
        assert len(ctx.warnings) == 1
        assert "ディスク残量注意" in ctx.warnings[0]

def test_check_disk_space_error(tmp_path):
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "dummy.mp4"))
    
    # 500MBの空きをシミュレート (エラーレベル)
    mock_usage = MagicMock(free=500 * 1024 * 1024)
    with patch("shutil.disk_usage", return_value=mock_usage):
        free_gb = coordinator._check_disk_space(ctx)
        # free_gb は 500 * 1024 * 1024 / (1024**3) = 0.488... GB
        assert free_gb is not None
        assert free_gb < 0.5
        assert len(ctx.warnings) == 0

def test_check_disk_space_exception(tmp_path):
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "dummy.mp4"))
    
    with patch("shutil.disk_usage", side_effect=Exception("Disk error")):
        free_gb = coordinator._check_disk_space(ctx)
        assert free_gb is None
        assert len(ctx.warnings) == 0

# ===========================================================================
# 4. Harness初期化・完了・テンプレート保証のテスト
# ===========================================================================

def test_init_harness_not_installed():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy/path.mp4")
    
    # harnessモジュールをImportErrorにする
    with patch.dict("sys.modules", {"harness.hooks": None}):
        res = coordinator._init_harness(ctx)
        assert res is None

def test_init_harness_general_exception():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy/path.mp4")
    
    # harness.hooks 自体はモックで存在するが、呼び出しで例外を起こす
    with patch("harness.session_manager.session_manager.create_session", side_effect=RuntimeError("DB Error")):
        res = coordinator._init_harness(ctx)
        assert res is None

def test_init_harness_success_new_session():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy/path.mp4")
    
    mock_session = MagicMock(session_id="new_session_id_123456789")
    mock_hooks = MagicMock()
    mock_sm = MagicMock()
    mock_ge = MagicMock()
    
    mock_sm.create_session.return_value = mock_session
    mock_ge.start_span.return_value = "trace_span_obj"
    
    with patch.dict("sys.modules", {
        "harness.hooks": mock_hooks,
        "harness.session_manager": MagicMock(session_manager=mock_sm),
        "harness.governance": MagicMock(governance_engine=mock_ge),
    }):
        # Mock class definition for HookEvent, HookInput, HookOutput
        mock_hooks.HookEvent = "HookEvent_dummy"
        mock_hooks.HookInput = "HookInput_dummy"
        mock_hooks.HookOutput = "HookOutput_dummy"
        
        res = coordinator._init_harness(ctx)
        assert res is not None
        assert ctx.session_id == "new_session_id_123456789"
        mock_sm.create_session.assert_called_once_with(video_path="/dummy/path.mp4")
        mock_ge.start_span.assert_called_once()

def test_init_harness_success_resume_session():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy/path.mp4", session_id="existing_session_id")
    
    mock_session = MagicMock(session_id="existing_session_id")
    mock_hooks = MagicMock()
    mock_sm = MagicMock()
    mock_ge = MagicMock()
    
    mock_sm.resume_session.return_value = mock_session
    
    with patch.dict("sys.modules", {
        "harness.hooks": mock_hooks,
        "harness.session_manager": MagicMock(session_manager=mock_sm),
        "harness.governance": MagicMock(governance_engine=mock_ge),
    }):
        res = coordinator._init_harness(ctx)
        assert res is not None
        assert ctx.session_id == "existing_session_id"
        mock_sm.resume_session.assert_called_once_with("existing_session_id")
        mock_sm.create_session.assert_not_called()

def test_finalize_harness_success():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy/path.mp4", session_id="sess_id", quality_score=95, final_path="/dummy/final.mp4")
    
    mock_ge = MagicMock()
    mock_sm = MagicMock()
    harness = {
        "governance_engine": mock_ge,
        "session_manager": mock_sm,
        "trace_span": "span_obj",
    }
    
    coordinator._finalize_harness(harness, ctx, "ok")
    mock_ge.end_span.assert_called_once_with("span_obj", status="ok")
    mock_sm.complete_session.assert_called_once_with(
        "sess_id",
        quality_score=95,
        final_data={"stages_completed": 0, "final_path": "/dummy/final.mp4"}
    )
    mock_ge.flush_traces.assert_called_once_with("sess_id")

def test_finalize_harness_error():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy/path.mp4", session_id="sess_id")
    ctx.warnings.append("disk full")
    
    mock_ge = MagicMock()
    mock_sm = MagicMock()
    harness = {
        "governance_engine": mock_ge,
        "session_manager": mock_sm,
        "trace_span": "span_obj",
    }
    
    coordinator._finalize_harness(harness, ctx, "error")
    mock_ge.end_span.assert_called_once_with("span_obj", status="error")
    mock_sm.error_session.assert_called_once_with("sess_id", "disk full")

def test_ensure_template_restore():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy/path.mp4", template_id="theme_cool")
    
    mock_tmpl_config = MagicMock(is_active=False)
    mock_template_config_module = MagicMock(
        template_config=mock_tmpl_config,
        PRODUCTION_TEMPLATES={"theme_cool": {"style": "cool_style"}}
    )
    
    with patch.dict("sys.modules", {
        "template_config": mock_template_config_module,
        "template_constants": mock_template_config_module,
        "routers.themes_router": MagicMock(PRODUCTION_TEMPLATES={"theme_cool": {"style": "cool_style"}}),
    }):
        coordinator._ensure_template(ctx)
        mock_tmpl_config.set_active_template.assert_called_once_with(
            "theme_cool", {"style": "cool_style"}, theme_id="warm"
        )

# ===========================================================================
# 5. Pre/Post Hooks & Governance のテスト
# ===========================================================================

@pytest.mark.asyncio
async def test_fire_pre_hook_no_harness():
    coordinator = PipelineCoordinator()
    from agents.workers import TranscribeWorker
    worker = TranscribeWorker()
    ctx = PipelineContext(video_path="/dummy.mp4")
    
    denied, reason = await coordinator._fire_pre_hook(None, worker, ctx)
    assert not denied
    assert reason is None

@pytest.mark.asyncio
async def test_fire_pre_hook_governance_denied_permission():
    coordinator = PipelineCoordinator()
    from agents.workers import TranscribeWorker
    worker = TranscribeWorker()
    ctx = PipelineContext(video_path="/dummy.mp4")
    
    mock_ge = MagicMock()
    mock_ge.check_permission.return_value = False # 権限なし
    harness = {"governance_engine": mock_ge}
    
    denied, reason = await coordinator._fire_pre_hook(harness, worker, ctx)
    assert denied
    assert "Governance denied" in reason

@pytest.mark.asyncio
async def test_fire_pre_hook_governance_denied_rate_limit():
    coordinator = PipelineCoordinator()
    from agents.workers import TranscribeWorker
    worker = TranscribeWorker()
    ctx = PipelineContext(video_path="/dummy.mp4")
    
    mock_ge = MagicMock()
    mock_ge.check_permission.return_value = True
    mock_ge.check_rate_limit.return_value = False # レート制限超過
    harness = {"governance_engine": mock_ge}
    
    denied, reason = await coordinator._fire_pre_hook(harness, worker, ctx)
    assert denied
    assert "Rate limit exceeded" in reason

@pytest.mark.asyncio
async def test_fire_pre_hook_hook_system_denied():
    coordinator = PipelineCoordinator()
    from agents.workers import TranscribeWorker
    worker = TranscribeWorker()
    ctx = PipelineContext(video_path="/dummy.mp4", session_id="sess_id")
    
    mock_ge = MagicMock()
    mock_ge.check_permission.return_value = True
    mock_ge.check_rate_limit.return_value = True
    
    mock_hook_system = AsyncMock()
    mock_hook_output = MagicMock(permission_decision="deny", permission_decision_reason="Hook policy block")
    mock_hook_system.fire.return_value = mock_hook_output
    
    mock_sm = MagicMock()
    
    harness = {
        "governance_engine": mock_ge,
        "hook_system": mock_hook_system,
        "HookInput": MagicMock(return_value="hook_input_obj"),
        "HookEvent": MagicMock(PRE_TOOL_USE="PRE_TOOL_USE"),
        "session_manager": mock_sm
    }
    
    denied, reason = await coordinator._fire_pre_hook(harness, worker, ctx)
    assert denied
    assert reason == "Hook policy block"
    mock_sm.update_stage.assert_not_called()

@pytest.mark.asyncio
async def test_fire_pre_hook_allowed():
    coordinator = PipelineCoordinator()
    from agents.workers import TranscribeWorker
    worker = TranscribeWorker()
    ctx = PipelineContext(video_path="/dummy.mp4", session_id="sess_id")
    
    mock_ge = MagicMock()
    mock_ge.check_permission.return_value = True
    mock_ge.check_rate_limit.return_value = True
    
    mock_hook_system = AsyncMock()
    mock_hook_output = MagicMock(permission_decision="allow")
    mock_hook_system.fire.return_value = mock_hook_output
    
    mock_sm = MagicMock()
    
    harness = {
        "governance_engine": mock_ge,
        "hook_system": mock_hook_system,
        "HookInput": MagicMock(return_value="hook_input_obj"),
        "HookEvent": MagicMock(PRE_TOOL_USE="PRE_TOOL_USE"),
        "session_manager": mock_sm
    }
    
    denied, reason = await coordinator._fire_pre_hook(harness, worker, ctx)
    assert not denied
    assert reason is None
    mock_sm.update_stage.assert_called_once_with("sess_id", worker.index, f"{worker.name} 実行中")

@pytest.mark.asyncio
async def test_fire_post_hook_no_harness():
    coordinator = PipelineCoordinator()
    from agents.workers import TranscribeWorker
    worker = TranscribeWorker()
    ctx = PipelineContext(video_path="/dummy.mp4")
    result = StageResult(stage_name=worker.name, success=True, detail="ok", duration_seconds=1.0)
    
    # 例外が起きないことを確認
    await coordinator._fire_post_hook(None, worker, result, ctx)

@pytest.mark.asyncio
async def test_fire_post_hook_success():
    coordinator = PipelineCoordinator()
    from agents.workers import TranscribeWorker
    worker = TranscribeWorker()
    ctx = PipelineContext(video_path="/dummy.mp4", session_id="sess_id")
    result = StageResult(stage_name=worker.name, success=True, detail="ok", duration_seconds=1.0, data={"count": 10})
    
    mock_hook_system = AsyncMock()
    mock_sm = MagicMock()
    harness = {
        "hook_system": mock_hook_system,
        "HookInput": MagicMock(return_value="hook_input_obj"),
        "HookEvent": MagicMock(POST_TOOL_USE="POST_TOOL_USE"),
        "session_manager": mock_sm
    }
    
    await coordinator._fire_post_hook(harness, worker, result, ctx)
    mock_hook_system.fire.assert_called_once_with("POST_TOOL_USE", "hook_input_obj")
    mock_sm.record_tool_call.assert_called_once_with(
        "sess_id", worker.name, {"stage": worker.index}, {"count": 10}, 1.0
    )

@pytest.mark.asyncio
async def test_fire_post_hook_failure():
    coordinator = PipelineCoordinator()
    from agents.workers import TranscribeWorker
    worker = TranscribeWorker()
    ctx = PipelineContext(video_path="/dummy.mp4", session_id="sess_id")
    result = StageResult(stage_name=worker.name, success=False, detail="crash error", duration_seconds=2.0)
    
    mock_hook_system = AsyncMock()
    mock_sm = MagicMock()
    harness = {
        "hook_system": mock_hook_system,
        "HookInput": MagicMock(return_value="hook_input_obj"),
        "HookEvent": MagicMock(POST_TOOL_USE_FAILURE="POST_TOOL_USE_FAILURE"),
        "session_manager": mock_sm
    }
    
    await coordinator._fire_post_hook(harness, worker, result, ctx)
    mock_hook_system.fire.assert_called_once_with("POST_TOOL_USE_FAILURE", "hook_input_obj")
    mock_sm.record_tool_call.assert_not_called()

# ===========================================================================
# 6. 直列 / 並列 / 最終ステージ実行のテスト
# ===========================================================================

@pytest.mark.asyncio
async def test_execute_serial_stages_success():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy.mp4")
    
    # 直列ワーカー (Transcribe, Proofread, SmartCut) の execute メソッドをモック化
    for w in coordinator.workers:
        if w.name in ["文字起こし", "AI校閲", "SmartCut構成"]:
            w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail=f"{w.name} success", duration_seconds=0.5))
            w.verify = MagicMock(return_value=True)
            
    perf_manager = MagicMock()
    
    err = await coordinator._execute_serial_stages(ctx, None, perf_manager)
    assert err is None
    assert len(ctx.stage_results) == 3
    for r in ctx.stage_results:
        assert r.success
        assert r.retries == 0
    assert perf_manager.record_worker_time.call_count == 3

@pytest.mark.asyncio
async def test_execute_serial_stages_retry_and_success():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy.mp4")
    
    # 最初の1回目は verify が失敗し、2回目で成功する
    from agents.workers import TranscribeWorker
    worker = coordinator._find_worker(TranscribeWorker)
    
    # TranscribeWorker 以外は最初から成功するようにする
    for w in coordinator.workers:
        if w != worker:
            w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail="success"))
            w.verify = MagicMock(return_value=True)
            
    worker.execute = AsyncMock(return_value=StageResult(stage_name=worker.name, success=True, detail="run success"))
    worker.verify = MagicMock(side_effect=[False, True]) # 1回目失敗, 2回目成功
    
    err = await coordinator._execute_serial_stages(ctx, None, None)
    assert err is None
    # リトライが発生し、2回目のリトライで成功
    transcribe_res = next(r for r in ctx.stage_results if r.stage_name == worker.name)
    assert transcribe_res.success
    assert transcribe_res.retries == 1

@pytest.mark.asyncio
async def test_execute_serial_stages_fatal_transcribe_failure():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy.mp4")
    
    # TranscribeWorker が完全に失敗するケース
    from agents.workers import TranscribeWorker
    worker = coordinator._find_worker(TranscribeWorker)
    worker.execute = AsyncMock(return_value=StageResult(stage_name=worker.name, success=False, detail="Transcribe failed parsing", duration_seconds=1.0))
    worker.verify = MagicMock(return_value=False)
    
    err = await coordinator._execute_serial_stages(ctx, None, None)
    assert err == "Transcribe failed parsing"
    # execute_serial_stages は TranscribeWorker が失敗したら直ちに中断してエラーを返す
    assert len(ctx.stage_results) == 1
    assert ctx.stage_results[0].success is False

@pytest.mark.asyncio
async def test_execute_parallel_stages_success():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy.mp4")
    
    # 並列ワーカー (Preview, YouTubeOpt, QualityGate) をモック化
    for w in coordinator.workers:
        if w.name in ["プレビュー生成", "YouTube最適化", "品質チェック"]:
            w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail="ok"))
            w.verify = MagicMock(return_value=True)
            
    await coordinator._execute_parallel_stages(ctx, None, None)
    # 3つすべて実行されているはず
    parallel_names = ["プレビュー生成", "YouTube最適化", "品質チェック"]
    for name in parallel_names:
        assert any(r.stage_name == name and r.success for r in ctx.stage_results)

@pytest.mark.asyncio
async def test_execute_parallel_stages_preview_failure_warning_only():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy.mp4")
    
    from agents.workers import PreviewWorker, YouTubeOptWorker, QualityGateWorker
    
    preview_worker = coordinator._find_worker(PreviewWorker)
    preview_worker.execute = AsyncMock(return_value=StageResult(stage_name=preview_worker.name, success=False, detail="ffmpeg leak"))
    preview_worker.verify = MagicMock(return_value=False)
    
    youtube_worker = coordinator._find_worker(YouTubeOptWorker)
    youtube_worker.execute = AsyncMock(return_value=StageResult(stage_name=youtube_worker.name, success=True, detail="ok"))
    youtube_worker.verify = MagicMock(return_value=True)
    
    quality_worker = coordinator._find_worker(QualityGateWorker)
    quality_worker.execute = AsyncMock(return_value=StageResult(stage_name=quality_worker.name, success=True, detail="ok"))
    quality_worker.verify = MagicMock(return_value=True)
    
    await coordinator._execute_parallel_stages(ctx, None, None)
    # PreviewWorker の失敗は warnings に追加され、パイプライン全体は中断しない (T-020b)
    assert len(ctx.warnings) == 1
    assert "プレビュー生成失敗" in ctx.warnings[0]
    assert any(r.stage_name == preview_worker.name and not r.success for r in ctx.stage_results)

@pytest.mark.asyncio
async def test_execute_parallel_stages_with_exception():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy.mp4")
    
    from agents.workers import PreviewWorker, YouTubeOptWorker, QualityGateWorker
    
    # 1つのワーカーで例外が発生
    preview_worker = coordinator._find_worker(PreviewWorker)
    preview_worker.execute = AsyncMock(side_effect=RuntimeError("Gather crash"))
    
    youtube_worker = coordinator._find_worker(YouTubeOptWorker)
    youtube_worker.execute = AsyncMock(return_value=StageResult(stage_name=youtube_worker.name, success=True, detail="ok"))
    youtube_worker.verify = MagicMock(return_value=True)
    
    quality_worker = coordinator._find_worker(QualityGateWorker)
    quality_worker.execute = AsyncMock(return_value=StageResult(stage_name=quality_worker.name, success=True, detail="ok"))
    quality_worker.verify = MagicMock(return_value=True)
    
    # 例外が起きても asyncio.gather(return_exceptions=True) によりキャッチされる
    await coordinator._execute_parallel_stages(ctx, None, None)
    # 成功したワーカーは記録される
    assert any(r.stage_name == youtube_worker.name and r.success for r in ctx.stage_results)
    assert any(r.stage_name == quality_worker.name and r.success for r in ctx.stage_results)

@pytest.mark.asyncio
async def test_execute_final_rendering_stage_quality_passed():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy.mp4")
    ctx.quality_score = 92 # 90以上 -> production mode
    
    from agents.workers import RenderWorker
    render_worker = coordinator._find_worker(RenderWorker)
    render_worker.execute = AsyncMock(return_value=StageResult(stage_name=render_worker.name, success=True, detail="high quality render"))
    
    await coordinator._execute_final_rendering_stage(ctx, None, None)
    assert ctx.render_mode == "production"
    assert any(r.stage_name == render_worker.name and r.success for r in ctx.stage_results)

@pytest.mark.asyncio
async def test_execute_final_rendering_stage_quality_failed():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy.mp4")
    ctx.quality_score = 80 # 90点未満 -> safe mode & WebSocket通知
    
    from agents.workers import RenderWorker
    render_worker = coordinator._find_worker(RenderWorker)
    render_worker.execute = AsyncMock(return_value=StageResult(stage_name=render_worker.name, success=True, detail="safe render"))
    
    ws_msgs = []
    async def ws_broadcast(msg):
        ws_msgs.append(msg)
        
    coordinator.set_ws_broadcast(ws_broadcast)
    
    await coordinator._execute_final_rendering_stage(ctx, None, None)
    assert ctx.render_mode == "safe"
    assert len(ws_msgs) == 3
    assert ws_msgs[0]["type"] == "quality_gate_blocked"
    assert ws_msgs[0]["score"] == 80
    assert ws_msgs[0]["render_mode"] == "safe"
    assert ws_msgs[1]["status"] == "running"
    assert ws_msgs[2]["status"] == "completed"

# ===========================================================================
# 7. 品質改善（Evaluator-Optimizer）および改善ループのテスト
# ===========================================================================

@pytest.mark.asyncio
async def test_optimize_quality_evaluator_optimizer_success():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy.mp4", session_id="sess_123")
    
    from agents.workers import QualityGateWorker
    quality_worker = coordinator._find_worker(QualityGateWorker)
    
    # 失敗していた品質チェック結果を stage_results に入れる
    quality_result = StageResult(stage_name=quality_worker.name, success=False, detail="bad audio", data={"feedback": ["low audio"]})
    ctx.stage_results.append(quality_result)
    quality_worker.verify = MagicMock(return_value=False)
    
    mock_opt_result = MagicMock(success=True, initial_score=80, final_score=95, iterations=2, improvements_applied=["audio_normalization"])
    mock_eo = AsyncMock()
    mock_eo.run.return_value = mock_opt_result
    
    mock_sm = MagicMock()
    harness = {"session_manager": mock_sm}
    
    with patch.dict("sys.modules", {"harness.evaluator_optimizer": MagicMock(evaluator_optimizer=mock_eo)}):
        await coordinator._optimize_quality(ctx, harness, None)
        mock_eo.run.assert_called_once_with(ctx, max_iterations=3)
        mock_sm.record_tool_call.assert_called_once()

@pytest.mark.asyncio
async def test_optimize_quality_fallback_loop_success():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy.mp4", session_id="sess_123")
    ctx.quality_score = 80
    
    from agents.workers import QualityGateWorker, PreviewWorker
    quality_worker = coordinator._find_worker(QualityGateWorker)
    preview_worker = coordinator._find_worker(PreviewWorker)
    
    # 品質チェック失敗の stage_result
    quality_result = StageResult(stage_name=quality_worker.name, success=False, detail="bad", data={"feedback": ["typo text"]})
    ctx.stage_results.append(quality_result)
    quality_worker.verify = MagicMock(return_value=False)
    
    # harness.evaluator_optimizer がない（ImportError）状況を作り、quality_improvement_loop にフォールバックさせる
    preview_worker.execute = AsyncMock(return_value=StageResult(stage_name=preview_worker.name, success=True, detail="new preview"))
    
    # improvement loop で1回リトライ後に成功する
    quality_worker.execute = AsyncMock(return_value=StageResult(stage_name=quality_worker.name, success=True, detail="passed"))
    
    # 1回目のリトライ verify=True
    def verify_mock(res):
        if res.detail == "passed":
            ctx.quality_score = 92
            return True
        return False
    quality_worker.verify.side_effect = verify_mock
    
    with patch.dict("sys.modules", {"harness.evaluator_optimizer": None}):
        # ループ実行
        await coordinator._optimize_quality(ctx, None, None)
        # リトライ成功
        assert ctx.quality_score == 92
        assert len(ctx.quality_feedback) == 1
        assert ctx.quality_feedback[0] == "typo text"

@pytest.mark.asyncio
async def test_quality_improvement_loop_max_retries():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy.mp4")
    ctx.quality_score = 80
    
    from agents.workers import QualityGateWorker, PreviewWorker
    quality_worker = coordinator._find_worker(QualityGateWorker)
    preview_worker = coordinator._find_worker(PreviewWorker)
    
    # 改善ループが最大回数 (3回) 回っても不合格なケース
    preview_worker.execute = AsyncMock(return_value=StageResult(stage_name=preview_worker.name, success=True, detail="preview ok"))
    quality_worker.execute = AsyncMock(return_value=StageResult(stage_name=quality_worker.name, success=False, detail="still bad", data={"feedback": ["feedback_msg"]}))
    quality_worker.verify = MagicMock(return_value=False)
    
    # 改善ループ呼び出し
    res = await coordinator._quality_improvement_loop(ctx, None)
    assert res is False
    # execute は 3回 呼び出されるはず
    assert preview_worker.execute.call_count == 3
    assert quality_worker.execute.call_count == 3

# ===========================================================================
# 8. build_result & 改善提案のテスト
# ===========================================================================

def test_build_result_and_improvement_suggestions():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy/path.mp4")
    ctx.quality_score = 85 # 90点未満
    # **「測った」は値ではなく旗で表す**（R1.5-C4）。`quality_gate_report` は
    # `> 0` の番兵値ではなく旗で組み立てるようになった
    ctx.quality_scored = True
    ctx.quality_feedback = ["音量が小さい", "字幕テキストに誤字があります", "メタデータにタグがない", "セグメント構成の尺が長い"]
    
    res = coordinator._build_result(ctx, "completed", 0.0)
    assert res["status"] == "completed"
    assert res["quality_score"] == 85
    
    report = res["quality_gate_report"]
    assert report is not None
    assert report["status"] == "blocked"
    assert report["gap"] == 5
    
    suggestions = report["improvement_suggestions"]
    # 4種類の提案がすべて含まれていることを確認
    actions = [s["action"] for s in suggestions]
    assert "audio_normalization" in actions
    assert "re_proofread" in actions
    assert "regenerate_metadata" in actions
    assert "restructure_segments" in actions

# ===========================================================================
# 9. Retention Map 分析 & DreamEngine 学習フックのテスト
# ===========================================================================

@pytest.mark.asyncio
async def test_run_retention_analysis_success():
    coordinator = PipelineCoordinator()
    
    ctx = PipelineContext(video_path="/dummy/video_stem.mp4")
    ctx.segments = [{"start": 0.0, "end": 10.0}, {"start": 10.0, "end": 20.0}]
    
    mock_report = MagicMock()
    mock_report.overall_risk_assessment = "Medium"
    mock_report.suggestions = ["engage user at 10s"]
    mock_segment = MagicMock(start_time=10, end_time=15, risk_level=8, label="drop risk")
    mock_report.segments = [mock_segment]
    
    mock_plugin = MagicMock()
    mock_plugin.analyze_retention_risks.return_value = mock_report
    
    with patch.dict("sys.modules", {"plugins.retention_map_plugin": MagicMock(retention_map_plugin=mock_plugin)}):
        res = await coordinator._run_retention_analysis(ctx)
        assert res is not None
        assert res.stage_name == "Retention分析"
        assert res.success is True
        assert ctx.metadata["retention_analysis"]["overall_risk"] == "Medium"
        assert len(ctx.metadata["retention_analysis"]["high_risk_segments"]) == 1

@pytest.mark.asyncio
async def test_trigger_dream_learning_success(tmp_path):
    coordinator = PipelineCoordinator()
    
    # ダミーのビデオファイル
    video_file = tmp_path / "test_video.mp4"
    video_file.write_text("video")
    
    ctx = PipelineContext(video_path=str(video_file))
    ctx.segments = [{"start": 0}]
    ctx.selected_segments = []
    ctx.quality_score = 95
    ctx.stage_results = [
        StageResult(stage_name="AI校閲", success=True, detail="ok", duration_seconds=1.0, data={"total": 5})
    ]
    
    mock_de = AsyncMock()
    mock_de.increment_session_count = MagicMock() # Warning対策: コルーチンではないためMagicMockにする
    mock_de.should_dream = AsyncMock(return_value=True)
    mock_de.run_dream_cycle = AsyncMock()
    
    # ログ出力先を tmp_path に変更するために、Path(__file__).parent / "logs" をモック化
    with patch.dict("sys.modules", {"agents.dream_engine": MagicMock(dream_engine=mock_de)}), \
         patch("agents.pipeline_coordinator.Path.mkdir"), \
         patch("agents.pipeline_coordinator.Path.write_text") as mock_write:
         
        await coordinator._trigger_dream_learning(ctx)
        mock_de.increment_session_count.assert_called_once()
        mock_de.should_dream.assert_called_once()
        mock_de.run_dream_cycle.assert_called_once()
        mock_write.assert_called_once()

# ===========================================================================
# 10. execute メインパスのテスト
# ===========================================================================

@pytest.mark.asyncio
async def test_execute_main_disk_space_insufficient(tmp_path):
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "dummy.mp4"))
    
    # ディスク空き容量を 0.5GB (1GB未満) にする
    mock_usage = MagicMock(free=500 * 1024 * 1024)
    with patch("shutil.disk_usage", return_value=mock_usage):
        res = await coordinator.execute(ctx)
        assert res["status"] == "error"
        assert "ディスク空き容量不足" in res["error"]

@pytest.mark.asyncio
async def test_execute_main_success(tmp_path):
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "dummy.mp4"))
    
    # ディスク十分
    mock_usage = MagicMock(free=10 * 1024 * 1024 * 1024)
    
    # 各種ステージ実行関数をモック化
    coordinator._init_performance_budget_manager = MagicMock(return_value=None)
    coordinator._init_harness = MagicMock(return_value=None)
    coordinator._ensure_template = MagicMock()
    coordinator._execute_serial_stages = AsyncMock(return_value=None)
    coordinator._execute_parallel_stages = AsyncMock()
    coordinator._execute_final_rendering_stage = AsyncMock()
    coordinator._optimize_quality = AsyncMock()
    coordinator._run_retention_analysis = AsyncMock(return_value=None)
    coordinator._trigger_dream_learning = AsyncMock()
    coordinator._finalize_harness = MagicMock()
    coordinator._save_performance_report = MagicMock(return_value={"total_duration": 10.0})
    
    with patch("shutil.disk_usage", return_value=mock_usage):
        res = await coordinator.execute(ctx)
        assert res["status"] == "completed"
        assert res["performance_budget"] == {"total_duration": 10.0}
        coordinator._finalize_harness.assert_called_once()


# ===========================================================================
# 11. 追加カバレッジ向上テストケース
# ===========================================================================

def test_init_harness_resume_session_not_found():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy/path.mp4", session_id="missing_session_id")
    
    mock_session = MagicMock(session_id="missing_session_id")
    mock_hooks = MagicMock()
    mock_sm = MagicMock()
    mock_ge = MagicMock()
    
    mock_sm.resume_session.return_value = None # 見つからない
    mock_sm.create_session.return_value = mock_session
    mock_ge.start_span.return_value = "trace_span_obj"
    
    with patch.dict("sys.modules", {
        "harness.hooks": mock_hooks,
        "harness.session_manager": MagicMock(session_manager=mock_sm),
        "harness.governance": MagicMock(governance_engine=mock_ge),
    }):
        res = coordinator._init_harness(ctx)
        assert res is not None
        assert ctx.session_id == "missing_session_id"
        mock_sm.resume_session.assert_called_once_with("missing_session_id")
        mock_sm.create_session.assert_called_once_with(video_path="/dummy/path.mp4", session_id="missing_session_id")

def test_finalize_harness_no_harness():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy/path.mp4")
    coordinator._finalize_harness(None, ctx, "ok")

def test_finalize_harness_exception():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy/path.mp4")
    mock_ge = MagicMock()
    mock_ge.end_span.side_effect = Exception("Finalize error")
    harness = {
        "governance_engine": mock_ge,
        "trace_span": "span_obj"
    }
    coordinator._finalize_harness(harness, ctx, "ok")

@pytest.mark.asyncio
async def test_execute_main_serial_stage_fatal_failure(tmp_path):
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "dummy.mp4"))
    
    mock_usage = MagicMock(free=10 * 1024 * 1024 * 1024)
    
    coordinator._init_performance_budget_manager = MagicMock(return_value=None)
    coordinator._init_harness = MagicMock(return_value={"governance_engine": MagicMock(), "trace_span": "span"})
    coordinator._ensure_template = MagicMock()
    coordinator._execute_serial_stages = AsyncMock(return_value="Fatal Transcribe Error")
    coordinator._finalize_harness = MagicMock()
    
    with patch("shutil.disk_usage", return_value=mock_usage):
        res = await coordinator.execute(ctx)
        assert res["status"] == "error"
        assert res["error"] == "Fatal Transcribe Error"
        coordinator._finalize_harness.assert_called_once()

@pytest.mark.asyncio
async def test_execute_main_with_retention_report(tmp_path):
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "dummy.mp4"))
    
    mock_usage = MagicMock(free=10 * 1024 * 1024 * 1024)
    mock_retention_report = StageResult(stage_name="Retention分析", success=True, detail="ok")
    
    coordinator._init_performance_budget_manager = MagicMock(return_value=None)
    coordinator._init_harness = MagicMock(return_value=None)
    coordinator._ensure_template = MagicMock()
    coordinator._execute_serial_stages = AsyncMock(return_value=None)
    coordinator._execute_parallel_stages = AsyncMock()
    coordinator._execute_final_rendering_stage = AsyncMock()
    coordinator._optimize_quality = AsyncMock()
    coordinator._run_retention_analysis = AsyncMock(return_value=mock_retention_report)
    coordinator._trigger_dream_learning = AsyncMock()
    coordinator._finalize_harness = MagicMock()
    coordinator._save_performance_report = MagicMock(return_value=None)
    
    with patch("shutil.disk_usage", return_value=mock_usage):
        res = await coordinator.execute(ctx)
        assert res["status"] == "completed"
        assert any(r.stage_name == "Retention分析" for r in ctx.stage_results)

def test_init_performance_budget_manager_exception():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy/path.mp4")
    
    mock_pbm = MagicMock()
    mock_pbm.side_effect = RuntimeError("Init Error")
    
    with patch.dict("sys.modules", {
        "services.performance_budget_manager": MagicMock(PerformanceBudgetManager=mock_pbm)
    }):
        res = coordinator._init_performance_budget_manager(ctx)
        assert res is None

@pytest.mark.asyncio
async def test_execute_serial_stages_denied():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy.mp4")
    
    async def mock_fire_pre_hook(harness, worker, context):
        return True, "Hook Policy Denied"
        
    coordinator._fire_pre_hook = mock_fire_pre_hook
    
    err = await coordinator._execute_serial_stages(ctx, None, None)
    assert err == "Hook Policy Denied"
    assert len(ctx.stage_results) == 1
    assert ctx.stage_results[0].success is False
    assert "Hook denied" in ctx.stage_results[0].detail

@pytest.mark.asyncio
async def test_execute_serial_stages_non_transcribe_denied():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy.mp4")
    
    for w in coordinator.workers:
        w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail="ok"))
        w.verify = MagicMock(return_value=True)
        
    async def mock_fire_pre_hook(harness, worker, context):
        if worker.name == "AI校閲":
            return True, "Proofread Denied"
        return False, None
        
    coordinator._fire_pre_hook = mock_fire_pre_hook
    
    err = await coordinator._execute_serial_stages(ctx, None, None)
    assert err is None
    assert len(ctx.stage_results) == 3
    proofread_res = next(r for r in ctx.stage_results if r.stage_name == "AI校閲")
    assert proofread_res.success is False
    assert "Proofread Denied" in proofread_res.detail

@pytest.mark.asyncio
async def test_execute_parallel_stages_denied():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy.mp4")
    
    for w in coordinator.workers:
        w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail="ok"))
        w.verify = MagicMock(return_value=True)
        
    async def mock_fire_pre_hook(harness, worker, context):
        if worker.name == "プレビュー生成":
            return True, "Preview Denied"
        return False, None
        
    coordinator._fire_pre_hook = mock_fire_pre_hook
    
    await coordinator._execute_parallel_stages(ctx, None, None)
    preview_res = next(r for r in ctx.stage_results if r.stage_name == "プレビュー生成")
    assert preview_res.success is False
    assert "Preview Denied" in preview_res.detail

@pytest.mark.asyncio
async def test_execute_stages_with_perf_manager():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy.mp4")
    ctx.quality_score = 80
    
    for w in coordinator.workers:
        w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail="ok", data={"feedback": []}))
        if w.name == "品質チェック":
            w.verify = MagicMock(side_effect=[False, False, True, True])
        else:
            w.verify = MagicMock(return_value=True)
            
    mock_perf = MagicMock()
    
    await coordinator._execute_parallel_stages(ctx, None, mock_perf)
    assert mock_perf.record_worker_time.call_count >= 1
    
    await coordinator._execute_final_rendering_stage(ctx, None, mock_perf)
    
    with patch.dict("sys.modules", {"harness.evaluator_optimizer": None}):
        await coordinator._optimize_quality(ctx, None, mock_perf)

@pytest.mark.asyncio
async def test_execute_final_rendering_stage_failure():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy.mp4")
    ctx.quality_score = 95
    
    from agents.workers import RenderWorker
    render_worker = coordinator._find_worker(RenderWorker)
    render_worker.execute = AsyncMock(return_value=StageResult(stage_name=render_worker.name, success=False, detail="render crash"))
    
    await coordinator._execute_final_rendering_stage(ctx, None, None)
    res = next(r for r in ctx.stage_results if r.stage_name == render_worker.name)
    assert res.success is False

@pytest.mark.asyncio
async def test_optimize_quality_evaluator_optimizer_still_failed():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy.mp4", session_id="sess_123")
    
    from agents.workers import QualityGateWorker
    quality_worker = coordinator._find_worker(QualityGateWorker)
    
    quality_result = StageResult(stage_name=quality_worker.name, success=False, detail="bad audio", data={"feedback": ["low audio"]})
    ctx.stage_results.append(quality_result)
    quality_worker.verify = MagicMock(return_value=False)
    
    mock_opt_result = MagicMock(success=False, final_score=85)
    mock_eo = AsyncMock()
    mock_eo.run.return_value = mock_opt_result
    
    with patch.dict("sys.modules", {"harness.evaluator_optimizer": MagicMock(evaluator_optimizer=mock_eo)}):
        await coordinator._optimize_quality(ctx, None, None)
        mock_eo.run.assert_called_once_with(ctx, max_iterations=3)

@pytest.mark.asyncio
async def test_optimize_quality_fallback_loop_still_failed():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy.mp4")
    ctx.quality_score = 80
    
    from agents.workers import QualityGateWorker, PreviewWorker
    quality_worker = coordinator._find_worker(QualityGateWorker)
    preview_worker = coordinator._find_worker(PreviewWorker)
    
    quality_result = StageResult(stage_name=quality_worker.name, success=False, detail="bad")
    ctx.stage_results.append(quality_result)
    
    preview_worker.execute = AsyncMock(return_value=StageResult(stage_name=preview_worker.name, success=True, detail="new preview"))
    quality_worker.execute = AsyncMock(return_value=StageResult(stage_name=quality_worker.name, success=False, detail="still bad", data={"feedback": []}))
    quality_worker.verify = MagicMock(return_value=False)
    
    with patch.dict("sys.modules", {"harness.evaluator_optimizer": None}):
        await coordinator._optimize_quality(ctx, None, None)
        assert quality_worker.verify.call_count >= 3

@pytest.mark.asyncio
async def test_quality_improvement_loop_workers_not_found():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy.mp4")
    
    coordinator.workers = []
    
    res = await coordinator._quality_improvement_loop(ctx, None)
    assert res is False

@pytest.mark.asyncio
async def test_quality_improvement_loop_preview_failed():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy.mp4")
    ctx.quality_score = 80
    
    from agents.workers import QualityGateWorker, PreviewWorker
    quality_worker = coordinator._find_worker(QualityGateWorker)
    preview_worker = coordinator._find_worker(PreviewWorker)
    
    preview_worker.execute = AsyncMock(return_value=StageResult(stage_name=preview_worker.name, success=False, detail="preview crash"))
    quality_worker.execute = AsyncMock(return_value=StageResult(stage_name=quality_worker.name, success=False, detail="bad"))
    quality_worker.verify = MagicMock(return_value=False)
    
    res = await coordinator._quality_improvement_loop(ctx, None)
    assert res is False

@pytest.mark.asyncio
async def test_run_retention_analysis_fallback_duration():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy/video.mp4")
    ctx.segments = []
    ctx.target_minutes = 5
    
    mock_report = MagicMock()
    mock_report.overall_risk_assessment = "Low"
    mock_report.suggestions = []
    mock_report.segments = []
    
    mock_plugin = MagicMock()
    mock_plugin.analyze_retention_risks.return_value = mock_report
    
    with patch.dict("sys.modules", {"plugins.retention_map_plugin": MagicMock(retention_map_plugin=mock_plugin)}):
        res = await coordinator._run_retention_analysis(ctx)
        assert res is not None
        mock_plugin.analyze_retention_risks.assert_called_once_with(
            video_id="video",
            duration_sec=300,
            video_path="/dummy/video.mp4"
        )

@pytest.mark.asyncio
async def test_run_retention_analysis_exception_caught():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy/video.mp4")
    
    with patch.dict("sys.modules", {"plugins.retention_map_plugin": Exception("Plugin error")}):
        res = await coordinator._run_retention_analysis(ctx)
        assert res is None

@pytest.mark.asyncio
async def test_trigger_dream_learning_exception_caught():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy/video.mp4")
    
    with patch.dict("sys.modules", {"agents.dream_engine": Exception("Dream error")}):
        await coordinator._trigger_dream_learning(ctx)

def test_validate_pipeline_coordinator_thumbnail_load_exception(tmp_path):
    output_path = tmp_path / "corrupted.png"
    output_path.write_bytes(b"\x00\x00")
    
    mock_img = MagicMock()
    with patch("PIL.Image.open", side_effect=[mock_img, RuntimeError("PIL open error")]):
        with pytest.raises(ValueError, match="Failed to load image for resolution check"):
            validate_pipeline_coordinator_thumbnail(output_path)

def test_ensure_template_exception_caught():
    coordinator = PipelineCoordinator()
    ctx = PipelineContext(video_path="/dummy/path.mp4", template_id="theme_cool")
    
    with patch.dict("sys.modules", {
        "template_config": Exception("Template config error")
    }):
        coordinator._ensure_template(ctx)
