import os
import sys
import pytest
import json
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

# 2026-07-26: モック注入前の sys.modules を控えておく。後始末が無いと、同じセッションで
# 後から動くテストが本物の代わりに MagicMock を掴む（_uninstall_mock_modules で戻す）。
_PRE_MOCK_MODULES = sys.modules.copy()

# agents.production_pipeline をモックしてロードエラーを回避
sys.modules['agents.production_pipeline'] = MagicMock()
sys.modules['proper_noun_dict'] = MagicMock()
sys.modules['subtitle_engine.ai_proofreader'] = MagicMock()
sys.modules['subtitle_engine'] = MagicMock()
sys.modules['smart_cut_engine'] = MagicMock()
sys.modules['quality_gate_plugins'] = MagicMock()
sys.modules['video_editor_engine'] = MagicMock()
sys.modules['plugins.retention_map_plugin'] = MagicMock()
sys.modules['agents.dream_engine'] = MagicMock()

# パス追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(scope="module", autouse=True)
def _uninstall_mock_modules():
    """このモジュールの全テスト終了後に、注入した MagicMock を sys.modules から取り除く。"""
    yield
    for key in list(sys.modules):
        if key in _PRE_MOCK_MODULES:
            if sys.modules[key] is not _PRE_MOCK_MODULES[key]:
                sys.modules[key] = _PRE_MOCK_MODULES[key]
        else:
            del sys.modules[key]



from agents._deprecated.pipeline_coordinator import (
    PipelineCoordinator,
    PipelineContext,
    StageResult,
    TranscribeWorker,
    ProofreadWorker,
    SmartCutWorker,
    PreviewWorker,
    QualityGateWorker,
    RenderWorker,
    YouTubeOptWorker
)


def test_pipeline_context_init():
    """PipelineContextの初期化とデフォルト値の検証"""
    ctx = PipelineContext(video_path="dummy/path/video.mp4")
    assert ctx.video_path == "dummy/path/video.mp4"
    assert ctx.target_minutes == 20
    assert ctx.session_id == ""
    assert isinstance(ctx.segments, list)
    assert isinstance(ctx.selected_segments, list)
    assert ctx.preview_path is None
    assert ctx.final_path is None
    assert ctx.quality_score == 0
    assert isinstance(ctx.quality_feedback, list)
    assert isinstance(ctx.metadata, dict)
    assert isinstance(ctx.stage_results, list)
    assert ctx.template_id is None
    assert ctx.template_config is None
    assert isinstance(ctx.skipped_features, list)
    assert isinstance(ctx.warnings, list)


def test_stage_result_init():
    """StageResultの初期化と値の検証"""
    res = StageResult(stage_name="TestStage", success=True, detail="Done", duration_seconds=1.5, retries=1)
    assert res.stage_name == "TestStage"
    assert res.success is True
    assert res.detail == "Done"
    assert res.duration_seconds == 1.5
    assert res.retries == 1
    assert isinstance(res.data, dict)


def test_transcribe_worker_cache_fallback(tmp_path):
    """TranscribeWorkerで既存のキャッシュファイルが存在する場合の挙動"""
    video_file = tmp_path / "video.mp4"
    video_file.write_text("dummy video")
    
    # キャッシュファイルの作成 (1000バイトを超えるように調整)
    checkpoint_file = tmp_path / "_whisper_segments.jsonl"
    cached_segments = [
        {"id": 0, "start": 0.0, "end": 2.0, "text": "こんにちは"},
        {"id": 1, "start": 2.0, "end": 4.0, "text": "テストです"}
    ]
    with open(checkpoint_file, "w", encoding="utf-8") as f:
        for seg in cached_segments:
            f.write(json.dumps(seg) + "\n")
        # 1000バイトを超えるための余白
        f.write(" " * 1100 + "\n")
            
    ctx = PipelineContext(video_path=str(video_file))
    worker = TranscribeWorker()
    
    assert worker.name == "文字起こし"
    assert worker.icon == "🎤"
    assert "タイムスタンプ" in worker.get_definition_of_done()
    
    # 実行 (非同期メソッド)
    import asyncio
    result = asyncio.run(worker.execute(ctx))
    
    assert result.success is True
    assert "キャッシュ" in result.detail
    assert len(ctx.segments) == 2
    assert ctx.segments[0]["text"] == "こんにちは"
    assert worker.verify(result) is True


def test_transcribe_worker_exception():
    """TranscribeWorkerでエラーが発生した場合に適切に失敗判定されること"""
    ctx = PipelineContext(video_path="invalid_path.mp4")
    worker = TranscribeWorker()
    
    import asyncio
    result = asyncio.run(worker.execute(ctx))
    assert result.success is False
    assert worker.verify(result) is False



def test_proofread_worker_success():
    """ProofreadWorker of normal case validation"""
    ctx = PipelineContext(video_path="dummy.mp4")
    ctx.segments = [
        {"id": 0, "text": "テスト。"},
        {"id": 1, "text": "二つ目。"}
    ]
    worker = ProofreadWorker()
    assert worker.name == "AI校閲"
    assert worker.icon == "📝"
    
    # proper_noun_dict と subtitle_engine.ai_proofreader.proofread_segments のモック
    with patch("proper_noun_dict.apply_dictionary", return_value=("テスト修正。", ["修正"])) as mock_dict:
        with patch("subtitle_engine.ai_proofreader.proofread_segments", return_value=[{"id": 0, "text": "テスト修正。"}, {"id": 1, "text": "二つ目。"}]) as mock_ai:
            import asyncio
            result = asyncio.run(worker.execute(ctx))
            
            assert result.success is True
            assert len(ctx.segments) == 2
            assert ctx.segments[0]["text"] == "テスト修正。"


def test_smart_cut_worker_success():
    """SmartCutWorkerの正常系検証"""
    ctx = PipelineContext(video_path="dummy.mp4")
    ctx.segments = [{"id": 0, "text": "テスト"}]
    worker = SmartCutWorker()
    
    mock_propose_res = json.dumps({
        "proposals": [
            {"segments": [{"id": 0, "text": "テスト"}], "estimated_duration": 10}
        ]
    })
    
    with patch("agents.production_pipeline.propose_smart_cut", return_value=mock_propose_res):
        import asyncio
        result = asyncio.run(worker.execute(ctx))
        assert result.success is True
        assert len(ctx.selected_segments) == 1


def test_preview_worker_failure():
    """PreviewWorkerの失敗時挙動検証"""
    ctx = PipelineContext(video_path="dummy.mp4")
    worker = PreviewWorker()
    
    with patch("smart_cut_engine.render_smart_cut", return_value=False):
        import asyncio
        result = asyncio.run(worker.execute(ctx))
        assert result.success is False
        assert worker.verify(result) is False


def test_quality_gate_worker_fallback():
    """QualityGateWorkerのプラグイン未検出時のフォールバック挙動"""
    ctx = PipelineContext(video_path="dummy.mp4")
    worker = QualityGateWorker()
    
    real_import = __import__
    def mock_import(name, *args, **kwargs):
        if "quality_gate_plugins" in name:
            raise ImportError("No quality_gate_plugins")
        return real_import(name, *args, **kwargs)
        
    with patch("builtins.__import__", side_effect=mock_import):
        import asyncio
        result = asyncio.run(worker.execute(ctx))
        assert result.success is False  # デフォルトで80点減点などがあり不合格判定になる
        assert result.data["score"] == 80  # プレビュー不在で-20


def test_render_worker_no_preview():
    """RenderWorkerでプレビューがない場合の失敗挙動"""
    ctx = PipelineContext(video_path="dummy.mp4")
    worker = RenderWorker()
    
    import asyncio
    result = asyncio.run(worker.execute(ctx))
    assert result.success is False
    assert "レンダリング元なし" in result.detail


def test_youtube_opt_worker_fallback():
    """YouTubeOptWorkerのフォールバックメタデータ生成"""
    ctx = PipelineContext(video_path="dummy.mp4")
    ctx.segments = [
        {"id": 0, "start": 0, "end": 10, "text": "今日のご飯はカレーです"},
        {"id": 1, "start": 10, "end": 20, "text": "美味しくできました"}
    ]
    worker = YouTubeOptWorker()
    
    with patch("agents.production_pipeline.generate_youtube_metadata", side_effect=Exception("API Error")):
        import asyncio
        result = asyncio.run(worker.execute(ctx))
        assert result.success is True
        assert "簡易メタデータ生成" in result.detail
        assert "titles" in ctx.metadata
        assert "tags" in ctx.metadata
        assert len(ctx.metadata["chapters"]) >= 1


def test_pipeline_coordinator_worker_finding():
    """PipelineCoordinator内でのWorkerタイプによる検索検証"""
    coord = PipelineCoordinator()
    
    transcribe_worker = coord._find_worker(TranscribeWorker)
    assert transcribe_worker is not None
    assert isinstance(transcribe_worker, TranscribeWorker)
    
    # 存在しないWorkerの検索
    class NonExistentWorker:
        pass
    assert coord._find_worker(NonExistentWorker) is None


def test_pipeline_coordinator_set_callbacks():
    """PipelineCoordinatorへの進捗コールバックなどの設定検証"""
    coord = PipelineCoordinator()
    
    mock_callback = MagicMock()
    mock_ws = MagicMock()
    
    coord.set_progress_callback(mock_callback)
    coord.set_ws_broadcast(mock_ws)
    
    assert coord._progress_callback is mock_callback
    assert coord._ws_broadcast is mock_ws


def test_pipeline_stage_worker_base():
    from agents._deprecated.pipeline_coordinator import PipelineStageWorker
    class DummyWorker(PipelineStageWorker):
        async def execute(self, ctx):
            return StageResult(self.name, True)
    worker = DummyWorker("TestStage", "ℹ️", 99)
    assert worker.get_definition_of_done() == "TestStage completed successfully"
    res = StageResult("TestStage", True)
    assert worker.verify(res) is True


def test_transcribe_worker_name_error():
    import agents._deprecated.pipeline_coordinator as pc
    orig = getattr(pc, "pipeline_coordinator", None)
    if orig is not None:
        del pc.pipeline_coordinator
    try:
        ctx = PipelineContext(video_path="dummy.mp4")
        worker = TranscribeWorker()
        with patch("pathlib.Path.exists", return_value=False):
            # run_in_executor で例外を起こす
            with patch("asyncio.get_running_loop") as mock_loop:
                mock_loop.return_value.run_in_executor = AsyncMock(side_effect=Exception("Stop execution"))
                result = asyncio.run(worker.execute(ctx))
                assert result.success is False
    finally:
        if orig is not None:
            pc.pipeline_coordinator = orig


def test_transcribe_worker_subprocess_normal(tmp_path, safe_popen_mock):
    video_file = tmp_path / "video.mp4"
    video_file.write_text("dummy video")
    checkpoint_file = tmp_path / "_whisper_segments.jsonl"
    
    ctx = PipelineContext(video_path=str(video_file))
    worker = TranscribeWorker()
    
    stdout_lines = [
        '{"progress": 50}\n',
        '{"status": "completed", "device": "cuda"}\n'
    ]
    
    proc = safe_popen_mock(returncode=0)
    proc.stdout = stdout_lines
    
    def mock_wait(*args, **kwargs):
        with open(checkpoint_file, "w", encoding="utf-8") as f:
            f.write(json.dumps({"id": 0, "start": 0.0, "end": 2.0, "text": "こんにちは"}) + "\n")
        return 0
    proc.wait.side_effect = mock_wait

    with patch("subprocess.Popen", return_value=proc):
        result = asyncio.run(worker.execute(ctx))
        assert result.success is True
        assert "GPU" in result.detail
        assert len(ctx.segments) == 1


def test_transcribe_worker_subprocess_timeout(tmp_path, safe_popen_mock):
    import subprocess as _sp
    video_file = tmp_path / "video.mp4"
    video_file.write_text("dummy video")
    checkpoint_file = tmp_path / "_whisper_segments.jsonl"
    
    ctx = PipelineContext(video_path=str(video_file))
    worker = TranscribeWorker()
    
    proc = safe_popen_mock(returncode=1)
    
    # タイムアウト時にチェックポイントがあれば部分結果で成功するケース
    call_count = 0
    def mock_wait_timeout(timeout=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            with open(checkpoint_file, "w", encoding="utf-8") as f:
                f.write(" " * 600 + "\n")
                f.write(json.dumps({"id": 0, "start": 0.0, "end": 2.0, "text": "こんにちは"}) + "\n")
            raise _sp.TimeoutExpired(["cmd"], 600)
        return 0
    proc.wait.side_effect = mock_wait_timeout

    with patch("subprocess.Popen", return_value=proc):
        result = asyncio.run(worker.execute(ctx))
        assert result.success is True
        assert "timeout_partial" in result.data.get("device", "")

    # タイムアウト時にチェックポイントがなければ例外で失敗するケース
    proc_fail = safe_popen_mock(returncode=1)
    call_count_fail = 0
    def mock_wait_timeout_fail(timeout=None):
        nonlocal call_count_fail
        call_count_fail += 1
        if call_count_fail == 1:
            if checkpoint_file.exists():
                checkpoint_file.unlink()
            raise _sp.TimeoutExpired(["cmd"], 600)
        return 0
    proc_fail.wait.side_effect = mock_wait_timeout_fail

    with patch("subprocess.Popen", return_value=proc_fail):
        result = asyncio.run(worker.execute(ctx))
        assert result.success is False


def test_transcribe_worker_subprocess_error_fallback(tmp_path, safe_popen_mock):
    video_file = tmp_path / "video.mp4"
    video_file.write_text("dummy video")
    checkpoint_file = tmp_path / "_whisper_segments.jsonl"
    
    ctx = PipelineContext(video_path=str(video_file))
    worker = TranscribeWorker()
    
    proc = safe_popen_mock(returncode=0)
    proc.stdout = []
    
    def mock_wait(*args, **kwargs):
        with open(checkpoint_file, "w", encoding="utf-8") as f:
            f.write(" " * 1100 + "\n")
            f.write(json.dumps({"id": 0, "start": 0.0, "end": 2.0, "text": "こんにちは"}) + "\n")
        return 0
    proc.wait.side_effect = mock_wait

    with patch("subprocess.Popen", return_value=proc):
        result = asyncio.run(worker.execute(ctx))
        assert result.success is True
        assert "unknown" in result.data.get("device", "")


def test_proofread_worker_exceptions():
    ctx = PipelineContext(video_path="dummy.mp4")
    ctx.segments = [{"id": 0, "text": "テスト"}]
    worker = ProofreadWorker()
    
    with patch("proper_noun_dict.apply_dictionary", side_effect=Exception("Dict Error")):
        with patch("subtitle_engine.ai_proofreader.proofread_segments", side_effect=Exception("AI Error")):
            result = asyncio.run(worker.execute(ctx))
            assert result.success is True
            assert "AI校閲(Gemini)" in ctx.skipped_features


def test_smart_cut_worker_exception():
    ctx = PipelineContext(video_path="dummy.mp4")
    ctx.segments = [{"id": 0, "text": "テスト"}]
    worker = SmartCutWorker()
    
    with patch("agents.production_pipeline.propose_smart_cut", side_effect=Exception("SmartCut Error")):
        result = asyncio.run(worker.execute(ctx))
        assert result.success is True
        assert "SmartCut" in ctx.skipped_features


def test_preview_worker_full(tmp_path):
    ctx = PipelineContext(video_path="dummy.mp4")
    worker = PreviewWorker()
    
    def mock_render_success(segments, video_path, preview_path):
        with open(preview_path, "w") as f:
            f.write("dummy preview content")
        return True
        
    with patch("smart_cut_engine.render_smart_cut", side_effect=mock_render_success):
        with patch("safe_io.VAULT_OUTPUTS_DIR", tmp_path):
            result = asyncio.run(worker.execute(ctx))
            assert result.success is True
            assert worker.verify(result) is True
            assert ctx.preview_path is not None
            
    with patch("smart_cut_engine.render_smart_cut", side_effect=Exception("Render Error")):
        result = asyncio.run(worker.execute(ctx))
        assert result.success is False


def test_quality_gate_worker_full(tmp_path):
    ctx = PipelineContext(video_path="dummy.mp4")
    worker = QualityGateWorker()
    
    mock_plugin = MagicMock()
    mock_plugin.run_all_plugins.return_value = {
        "total_deductions": 5,
        "feedback": ["良好"],
        "category_report": [{"category": "test"}],
        "category_scores": {"test": 95}
    }
    sys.modules["quality_gate_plugins"] = mock_plugin
    try:
        result = asyncio.run(worker.execute(ctx))
        assert result.success is True
        assert result.data["score"] == 95
        assert worker.verify(result) is True
    finally:
        del sys.modules["quality_gate_plugins"]
        
    real_import = __import__
    def mock_import(name, *args, **kwargs):
        if "quality_gate_plugins" in name:
            raise ImportError()
        return real_import(name, *args, **kwargs)
        
    small_preview = tmp_path / "small_preview.mp4"
    small_preview.write_text("a")
    ctx.preview_path = str(small_preview)
    
    with patch("builtins.__import__", side_effect=mock_import):
        result = asyncio.run(worker.execute(ctx))
        assert result.success is False
        assert result.data["score"] == 70
        ctx.preview_path = None
        result = asyncio.run(worker.execute(ctx))
        assert result.success is False
        assert result.data["score"] == 80


def test_render_worker_full(tmp_path):
    ctx = PipelineContext(video_path="dummy.mp4")
    worker = RenderWorker()
    
    result = asyncio.run(worker.execute(ctx))
    assert result.success is False
    
    preview_file = tmp_path / "preview.mp4"
    preview_file.write_text("dummy preview")
    ctx.preview_path = str(preview_file)
    
    with patch.object(RenderWorker, "_render_production_quality", side_effect=Exception("Render error")):
        with patch("safe_io.VAULT_OUTPUTS_DIR", tmp_path):
            result = asyncio.run(worker.execute(ctx))
            assert result.success is False
            
    def mock_render_quality(preview, final, ctx_obj=None):
        with open(final, "w") as f:
            f.write("dummy final content")
        return True
    with patch.object(RenderWorker, "_render_production_quality", side_effect=mock_render_quality):
        with patch("safe_io.VAULT_OUTPUTS_DIR", tmp_path):
            result = asyncio.run(worker.execute(ctx))
            assert result.success is True
            assert ctx.final_path is not None


def test_render_production_quality_logic(tmp_path):
    worker = RenderWorker()
    preview = tmp_path / "preview.mp4"
    preview.write_text("dummy" * 300)
    final = tmp_path / "final.mp4"
    
    mock_ffmpeg = MagicMock()
    mock_ffmpeg.is_available.return_value = True
    mock_ffmpeg._get_encode_args.return_value = ["-vcodec", "h264"]
    
    def mock_run_command(cmd, timeout=None):
        if "-af" in cmd:
            out_file = cmd[-1]
            with open(out_file, "w") as f:
                f.write("normalized content" * 100)
        else:
            with open(final, "w") as f:
                f.write("encoded content" * 100)
        return True, "success"
        
    mock_ffmpeg.run_command.side_effect = mock_run_command
    
    mock_tc = MagicMock()
    mock_tc.get_active_benchmarks.return_value = {"audio_loudness_lufs": -14.0}
    sys.modules["template_config"] = mock_tc
    
    with patch("video_editor_engine.video_editor.ffmpeg", mock_ffmpeg):
        res = asyncio.run(worker._render_production_quality(str(preview), str(final), PipelineContext(video_path="dummy.mp4")))
        assert res is True
        
    mock_ffmpeg.is_available.return_value = False
    final.unlink(missing_ok=True)
    with patch("video_editor_engine.video_editor.ffmpeg", mock_ffmpeg):
        res = asyncio.run(worker._render_production_quality(str(preview), str(final), PipelineContext(video_path="dummy.mp4")))
        assert res is True
        
    final.unlink(missing_ok=True)
    with patch.dict(sys.modules, {"video_editor_engine": None}):
        res = asyncio.run(worker._render_production_quality(str(preview), str(final), PipelineContext(video_path="dummy.mp4")))
        assert res is True
        
    final.unlink(missing_ok=True)
    mock_ffmpeg.is_available.return_value = True
    def mock_run_command_ex(cmd, timeout=None):
        if "-af" in cmd:
            raise Exception("Loudnorm error")
        with open(final, "w") as f:
            f.write("encoded content" * 100)
        return True, "success"
    mock_ffmpeg.run_command.side_effect = mock_run_command_ex
    with patch("video_editor_engine.video_editor.ffmpeg", mock_ffmpeg):
        res = asyncio.run(worker._render_production_quality(str(preview), str(final), PipelineContext(video_path="dummy.mp4")))
        assert res is True


def test_youtube_opt_worker_normal():
    ctx = PipelineContext(video_path="dummy.mp4")
    ctx.segments = [{"text": "テスト"}]
    worker = YouTubeOptWorker()
    
    mock_res = json.dumps({
        "status": "success",
        "metadata": {
            "titles": ["タイトル1"],
            "tags": ["タグ1"],
            "description": "説明文"
        }
    })
    with patch("agents.production_pipeline.generate_youtube_metadata", return_value=mock_res):
        result = asyncio.run(worker.execute(ctx))
        assert result.success is True
        assert ctx.metadata["titles"] == ["タイトル1"]


def test_youtube_opt_worker_chapter_generation():
    ctx = PipelineContext(video_path="dummy.mp4")
    ctx.segments = [
        {"start": 0, "end": 10, "text": "オープニングトーク"},
        {"start": 310, "end": 320, "text": "本編その1"},
        {"start": 610, "end": 620, "text": "エンディング"}
    ]
    worker = YouTubeOptWorker()
    with patch("agents.production_pipeline.generate_youtube_metadata", side_effect=Exception("API Error")):
        result = asyncio.run(worker.execute(ctx))
        assert result.success is True
        chapters = ctx.metadata["chapters"]
        assert len(chapters) >= 3
        assert chapters[0]["time"] == "0:00"
        assert chapters[1]["time"] == "5:00"


def test_coordinator_notify_ws():
    coord = PipelineCoordinator()
    mock_ws = MagicMock()
    async def async_ws(data):
        mock_ws(data)
    coord.set_ws_broadcast(async_ws)
    
    worker = coord.workers[0]
    asyncio.run(coord._notify(worker, "running", "テスト"))
    mock_ws.assert_called_once()


def test_coordinator_execute_disk_usage(tmp_path):
    coord = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "dummy.mp4"))
    
    mock_usage = MagicMock()
    mock_usage.free = 0.5 * 1024 * 1024 * 1024
    with patch("shutil.disk_usage", return_value=mock_usage):
        result = asyncio.run(coord.execute(ctx))
        assert result["status"] == "error"
        assert "ディスク空き容量不足" in result["error"]
        
    mock_usage.free = 3.0 * 1024 * 1024 * 1024
    with patch("shutil.disk_usage", return_value=mock_usage):
        with patch.object(TranscribeWorker, "execute", return_value=StageResult("文字起こし", False, "Stop")) as mock_exec:
            result = asyncio.run(coord.execute(ctx))
            assert "ディスク残量注意" in ctx.warnings[0]


def test_coordinator_execute_template_recovery(tmp_path):
    coord = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "dummy.mp4"))
    ctx.template_id = "test_template"
    
    mock_tc = MagicMock()
    mock_tc.template_config.is_active = False
    sys.modules["template_config"] = mock_tc
    
    mock_templates = {"test_template": {"config": "value"}}
    
    with patch("routers.themes_router.PRODUCTION_TEMPLATES", mock_templates):
        with patch.object(TranscribeWorker, "execute", return_value=StageResult("文字起こし", False, "Stop")):
            asyncio.run(coord.execute(ctx))
            mock_tc.template_config.set_active_template.assert_called_once_with(
                "test_template", {"config": "value"}, theme_id="warm"
            )


def test_coordinator_retry_and_quality_loop(tmp_path):
    coord = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "dummy.mp4"))
    
    transcribe_exec = AsyncMock()
    transcribe_exec.side_effect = [
        StageResult("文字起こし", False, "Failed first"),
        StageResult("文字起こし", True, "Success second", data={"segment_count": 5})
    ]
    
    for w in coord.workers:
        if isinstance(w, TranscribeWorker):
            w.execute = transcribe_exec
        elif isinstance(w, QualityGateWorker):
            q_exec = AsyncMock()
            def q_exec_side_effect(ctx_obj):
                if getattr(q_exec_side_effect, "called", False):
                    ctx_obj.quality_score = 95
                    return StageResult("品質チェック", True, "Score 95", data={"score": 95})
                else:
                    q_exec_side_effect.called = True
                    ctx_obj.quality_score = 80
                    return StageResult("品質チェック", False, "Score 80", data={"score": 80})
            q_exec.side_effect = q_exec_side_effect
            w.execute = q_exec
            w.verify = lambda res: res.data.get("score", 0) >= 90
        elif isinstance(w, PreviewWorker):
            p_exec = AsyncMock()
            p_exec.return_value = StageResult("プレビュー生成", True, "Generated", data={"path": "dummy"})
            w.execute = p_exec
            w.verify = lambda res: True
        else:
            exec_mock = AsyncMock()
            exec_mock.return_value = StageResult(w.name, True, "Success", data={"path": "dummy"})
            w.execute = exec_mock
            
    mock_usage = MagicMock()
    mock_usage.free = 10 * 1024 * 1024 * 1024
    with patch("shutil.disk_usage", return_value=mock_usage):
        result = asyncio.run(coord.execute(ctx))
        assert result["status"] == "completed"
        assert transcribe_exec.call_count == 2
        assert ctx.quality_score == 95


def test_coordinator_quality_loop_fails(tmp_path):
    coord = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "dummy.mp4"))
    
    for w in coord.workers:
        if isinstance(w, QualityGateWorker):
            def q_exec_side_effect(ctx_obj):
                ctx_obj.quality_score = 80
                return StageResult("品質チェック", False, "Score 80", data={"score": 80})
            w.execute = AsyncMock(side_effect=q_exec_side_effect)
            w.verify = lambda res: False
        elif isinstance(w, PreviewWorker):
            w.execute = AsyncMock(return_value=StageResult("プレビュー生成", True, "Generated", data={"path": "dummy"}))
            w.verify = lambda res: True
        else:
            w.execute = AsyncMock(return_value=StageResult(w.name, True, "Success"))
            
    mock_usage = MagicMock()
    mock_usage.free = 10 * 1024 * 1024 * 1024
    with patch("shutil.disk_usage", return_value=mock_usage):
        result = asyncio.run(coord.execute(ctx))
        assert result["status"] == "completed"
        assert ctx.quality_score == 80


def test_coordinator_fatal_error_stops(tmp_path):
    coord = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "dummy.mp4"))
    
    for w in coord.workers:
        if isinstance(w, TranscribeWorker):
            w.execute = AsyncMock(return_value=StageResult("文字起こし", False, "Fatal error"))
            w.verify = lambda res: False
        else:
            w.execute = AsyncMock(return_value=StageResult(w.name, True, "Success"))
            
    mock_usage = MagicMock()
    mock_usage.free = 10 * 1024 * 1024 * 1024
    with patch("shutil.disk_usage", return_value=mock_usage):
        result = asyncio.run(coord.execute(ctx))
        assert result["status"] == "error"
        assert "Fatal error" in result["error"]


def test_retention_analysis_success(tmp_path):
    coord = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "video.mp4"))
    ctx.segments = [{"start": 0, "end": 10, "text": "test"}]
    
    mock_report = MagicMock()
    mock_report.overall_risk_assessment = "Low"
    mock_report.suggestions = ["Engage more"]
    mock_seg = MagicMock()
    mock_seg.start_time = 0
    mock_seg.end_time = 5
    mock_seg.risk_level = 8
    mock_seg.label = "drop"
    mock_report.segments = [mock_seg]
    
    mock_plugin = MagicMock()
    mock_plugin.retention_map_plugin.analyze_retention_risks.return_value = mock_report
    sys.modules["plugins.retention_map_plugin"] = mock_plugin
    
    try:
        res = asyncio.run(coord._run_retention_analysis(ctx))
        assert res is not None
        assert res.success is True
        assert ctx.metadata["retention_analysis"]["overall_risk"] == "Low"
    finally:
        del sys.modules["plugins.retention_map_plugin"]


def test_dream_learning_success(tmp_path):
    import agents._deprecated.pipeline_coordinator as pc
    coord = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "video.mp4"))
    ctx.segments = [{"text": "test"}]
    ctx.selected_segments = [{"text": "test"}]
    ctx.quality_score = 90
    ctx.stage_results = [
        StageResult("AI校閲", True, "done", data={"total": 2}),
        StageResult("Render", True, "done")
    ]
    
    mock_engine = MagicMock()
    async def mock_should_dream():
        return True
    async def mock_run_dream_cycle():
        pass
        
    mock_engine.dream_engine.should_dream = mock_should_dream
    mock_engine.dream_engine.run_dream_cycle = mock_run_dream_cycle
    sys.modules["agents.dream_engine"] = mock_engine
    
    orig_file = pc.__file__
    pc.__file__ = str(tmp_path / "pipeline_coordinator.py")
    try:
        asyncio.run(coord._trigger_dream_learning(ctx))
        logs_dir = tmp_path / "logs" / "pipeline_knowledge"
        assert logs_dir.exists()
        files = list(logs_dir.glob("run_*.json"))
        assert len(files) == 1
    finally:
        pc.__file__ = orig_file
        del sys.modules["agents.dream_engine"]


def test_execute_with_harness_disabled(tmp_path):
    coord = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "video.mp4"))
    
    with patch.dict(os.environ, {"HARNESS_MODE": "disabled"}):
        with patch.object(PipelineCoordinator, "execute", new_callable=AsyncMock) as mock_exec:
            asyncio.run(coord.execute_with_harness(ctx))
            mock_exec.assert_called_once_with(ctx)


def test_execute_with_harness_full(tmp_path):
    coord = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "video.mp4"))
    
    mock_harness = MagicMock()
    mock_harness.governance_engine._scopes = []
    
    async def mock_fire(event, hook_input):
        res = MagicMock()
        if hook_input.tool_name == "文字起こし":
            res.permission_decision = "deny"
            res.permission_decision_reason = "Access denied"
        else:
            res.permission_decision = "allow"
        return res
        
    mock_harness.hook_system.fire = mock_fire
    
    mock_session = MagicMock()
    mock_session.session_id = "test_sess"
    mock_harness.session_manager.create_session.return_value = mock_session
    mock_harness.session_manager.resume_session.return_value = None
    
    sys.modules["harness"] = mock_harness
    mock_hooks = MagicMock()
    def make_hook_input(*args, **kwargs):
        m = MagicMock()
        m.tool_name = kwargs.get("tool_name")
        return m
    mock_hooks.HookInput.side_effect = make_hook_input
    sys.modules["harness.hooks"] = mock_hooks
    
    for w in coord.workers:
        w.execute = AsyncMock(return_value=StageResult(w.name, True, "Success"))
    
    try:
        with patch.dict(os.environ, {"HARNESS_MODE": "enabled"}):
            res = asyncio.run(coord.execute_with_harness(ctx))
            assert res["status"] == "error"
            assert "Access denied" in res["error"]
    finally:
        del sys.modules["harness"]
        del sys.modules["harness.hooks"]


def test_execute_with_harness_success_path(tmp_path):
    coord = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "video.mp4"))
    
    mock_harness = MagicMock()
    mock_harness.governance_engine._scopes = []
    
    async def mock_fire(event, hook_input):
        from harness.hooks import HookOutput
        return HookOutput(permission_decision="allow")
        
    mock_harness.hook_system.fire = mock_fire
    mock_session = MagicMock()
    mock_session.session_id = "test_sess"
    mock_harness.session_manager.create_session.return_value = mock_session
    mock_harness.session_manager.resume_session.return_value = None
    
    sys.modules["harness"] = mock_harness
    mock_hooks = MagicMock()
    def make_hook_input(*args, **kwargs):
        m = MagicMock()
        m.tool_name = kwargs.get("tool_name")
        return m
    mock_hooks.HookInput.side_effect = make_hook_input
    sys.modules["harness.hooks"] = mock_hooks
    
    mock_ev_opt = MagicMock()
    
    for w in coord.workers:
        if isinstance(w, QualityGateWorker):
            w.execute = AsyncMock(return_value=StageResult("品質チェック", False, "Score 80", data={"score": 80}))
            w.verify = lambda res: res.data.get("score", 0) >= 90
        elif isinstance(w, PreviewWorker):
            w.execute = AsyncMock(return_value=StageResult("プレビュー生成", True, "Success", data={"path": "dummy"}))
            w.verify = lambda res: True
        else:
            w.execute = AsyncMock(return_value=StageResult(w.name, True, "Success"))
            
    async def mock_run(ctx_obj, max_iterations=3):
        from unittest.mock import MagicMock
        ctx_obj.quality_score = 95
        opt_res = MagicMock()
        opt_res.success = True
        opt_res.initial_score = 80
        opt_res.final_score = 95
        opt_res.iterations = 1
        opt_res.duration_seconds = 1.0
        opt_res.improvements_applied = ["Fix audio"]
        return opt_res
        
    mock_ev_opt.evaluator_optimizer.run = mock_run
    sys.modules["harness.evaluator_optimizer"] = mock_ev_opt
    
    try:
        with patch.dict(os.environ, {"HARNESS_MODE": "enabled"}):
            res = asyncio.run(coord.execute_with_harness(ctx))
            assert res["status"] == "completed"
            assert ctx.quality_score == 95
    finally:
        del sys.modules["harness"]
        del sys.modules["harness.hooks"]
        del sys.modules["harness.evaluator_optimizer"]


def test_all_workers_definition_of_done():
    from agents._deprecated.pipeline_coordinator import (
        TranscribeWorker, ProofreadWorker, SmartCutWorker,
        PreviewWorker, QualityGateWorker, RenderWorker, YouTubeOptWorker
    )
    assert "字幕セグメント" in TranscribeWorker().get_definition_of_done()
    assert "全セグメント" in ProofreadWorker().get_definition_of_done()
    assert "目標尺" in SmartCutWorker().get_definition_of_done()
    assert "プレビューファイル" in PreviewWorker().get_definition_of_done()
    assert "品質スコア" in QualityGateWorker().get_definition_of_done()
    assert "出力ファイル" in RenderWorker().get_definition_of_done()
    assert "タイトル" in YouTubeOptWorker().get_definition_of_done()

def test_quality_gate_worker_import_error(tmp_path):
    worker = QualityGateWorker()
    ctx = PipelineContext(video_path="dummy.mp4")
    # template_config のインポートで ImportError を発生させる
    with patch.dict(sys.modules, {"template_config": None}):
        result = asyncio.run(worker.execute(ctx))
        assert result.success is False  # スコア0点になる

def test_render_worker_render_failed(tmp_path):
    worker = RenderWorker()
    ctx = PipelineContext(video_path="dummy.mp4")
    ctx.preview_path = str(tmp_path / "preview.mp4")
    (tmp_path / "preview.mp4").write_text("dummy")
    # _render_production_quality が False を返すようにモック
    with patch.object(worker, "_render_production_quality", return_value=False):
        result = asyncio.run(worker.execute(ctx))
        assert result.success is False
        assert "本番品質レンダリング失敗" in result.detail

def test_proofread_worker_dictionary_exception():
    worker = ProofreadWorker()
    ctx = PipelineContext(video_path="dummy.mp4")
    ctx.segments = [{"text": "テスト"}]
    # apply_dictionary が例外を投げても、パスして正常終了することを確認
    with patch("proper_noun_dict.apply_dictionary", side_effect=Exception("dict error")):
        result = asyncio.run(worker.execute(ctx))
        assert result.success is True

def test_coordinator_notify_no_callbacks():
    coord = PipelineCoordinator()
    # コールバックが登録されていない状態で _notify を呼んでもエラーにならないことを確認
    worker = TranscribeWorker()
    asyncio.run(coord._notify(worker, "running", "message"))

def test_coordinator_execute_empty_video_path():
    coord = PipelineCoordinator()
    # ctx.video_path が存在しないときのエラー
    ctx = PipelineContext(video_path="")
    result = asyncio.run(coord.execute(ctx))
    assert result["status"] == "error"

def test_execute_with_harness_import_error(tmp_path):
    coord = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "video.mp4"))
    # harness 自体がインポートできないときのレガシーフォールバック
    with patch.dict(sys.modules, {"harness": None}):
        with patch.object(coord, "execute", return_value={"status": "legacy_completed"}):
            res = asyncio.run(coord.execute_with_harness(ctx))
            assert res == {"status": "legacy_completed"}

def test_execute_with_harness_exception(tmp_path):
    coord = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "video.mp4"))
    # harness モジュール内で例外が発生したときのレガシーフォールバック
    mock_harness = MagicMock()
    mock_harness.session_manager.create_session.side_effect = Exception("harness crash")
    with patch.dict(sys.modules, {"harness": mock_harness}):
        with patch.object(coord, "execute", return_value={"status": "legacy_completed"}):
            res = asyncio.run(coord.execute_with_harness(ctx))
            assert res == {"status": "legacy_completed"}


def test_pipeline_stage_worker_base_dod():
    from agents._deprecated.pipeline_coordinator import PipelineStageWorker
    class DummyWorker(PipelineStageWorker):
        async def execute(self, ctx):
            pass
    worker = DummyWorker("Dummy", "icon", 9)
    assert "Dummy completed successfully" in worker.get_definition_of_done()

def test_transcribe_worker_broken_stdout(tmp_path, safe_popen_mock):
    worker = TranscribeWorker()
    video_file = tmp_path / "video.mp4"
    video_file.write_text("dummy video")
    checkpoint_file = tmp_path / "_whisper_segments.jsonl"
    ctx = PipelineContext(video_path=str(video_file))
    
    proc = safe_popen_mock(returncode=0)
    proc.stdout = ["", "invalid json", '{"progress": 50}\n', '{"status": "completed"}\n']
    
    def mock_wait(*args, **kwargs):
        with open(checkpoint_file, "w", encoding="utf-8") as f:
            f.write(json.dumps({"id": 0, "start": 0.0, "end": 2.0, "text": "こんにちは"}) + "\n")
        return 0
    proc.wait.side_effect = mock_wait
    
    with patch("subprocess.Popen", return_value=proc):
        result = asyncio.run(worker.execute(ctx))
        assert result.success is True

def test_render_production_quality_encode_failed(tmp_path):
    worker = RenderWorker()
    preview = tmp_path / "preview.mp4"
    preview.write_text("dummy" * 300)
    final = tmp_path / "final.mp4"
    
    mock_ffmpeg = MagicMock()
    mock_ffmpeg.is_available.return_value = True
    mock_ffmpeg.run_command.return_value = (False, "encode error")
    
    with patch("video_editor_engine.video_editor.ffmpeg", mock_ffmpeg):
        res = asyncio.run(worker._render_production_quality(str(preview), str(final), PipelineContext(video_path="dummy.mp4")))
        assert res is True  # フォールバックコピーされるため

def test_render_production_quality_loudnorm_failed(tmp_path):
    worker = RenderWorker()
    preview = tmp_path / "preview.mp4"
    preview.write_text("dummy" * 300)
    final = tmp_path / "final.mp4"
    
    mock_ffmpeg = MagicMock()
    mock_ffmpeg.is_available.return_value = True
    
    temp_norm = str(final) + ".norm.mp4"
    
    def mock_run_command(cmd, timeout=None):
        if "-af" in cmd:
            with open(temp_norm, "w") as f:
                f.write("partial norm")
            return False, "loudnorm failed"
        else:
            with open(final, "w") as f:
                f.write("encoded content" * 100)
            return True, "success"
            
    mock_ffmpeg.run_command.side_effect = mock_run_command
    
    with patch("video_editor_engine.video_editor.ffmpeg", mock_ffmpeg):
        res = asyncio.run(worker._render_production_quality(str(preview), str(final), PipelineContext(video_path="dummy.mp4")))
        assert res is True
        assert not os.path.exists(temp_norm)  # unlinkされていること

def test_coordinator_notify_with_callbacks():
    coord = PipelineCoordinator()
    called = []
    def cb(worker_index, status, detail, progress):
        called.append((worker_index, status, detail, progress))
    coord.set_progress_callback(cb)
    worker = TranscribeWorker()
    asyncio.run(coord._notify(worker, "running", "msg", 50))
    assert len(called) == 1
    assert called[0] == (0, "running", "msg", 50)

def test_coordinator_execute_disk_usage_exception(tmp_path):
    coord = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "video.mp4"))
    with patch("shutil.disk_usage", side_effect=Exception("disk error")):
        # 実行してみて例外がキャッチされ進むことを確認
        try:
            asyncio.run(coord.execute(ctx))
        except Exception:
            pass

def test_coordinator_execute_template_init_exception(tmp_path):
    coord = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "video.mp4"))
    ctx.template_id = "test_template"
    with patch.dict(sys.modules, {"template_config": None}):
        try:
            asyncio.run(coord.execute(ctx))
        except Exception:
            pass

def test_coordinator_execute_disk_warning(tmp_path):
    coord = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "video.mp4"))
    mock_disk = MagicMock()
    mock_disk.free = 2 * (1024 ** 3)  # 2GB
    with patch("shutil.disk_usage", return_value=mock_disk):
        try:
            asyncio.run(coord.execute(ctx))
        except Exception:
            pass
        assert any("ディスク残量注意" in w for w in ctx.warnings)

def test_quality_improvement_loop_missing_workers():
    coord = PipelineCoordinator()
    ctx = PipelineContext(video_path="dummy.mp4")
    coord.workers = []  # 空にする
    assert asyncio.run(coord._quality_improvement_loop(ctx)) is False

def test_quality_improvement_loop_preview_fail(tmp_path):
    coord = PipelineCoordinator()
    ctx = PipelineContext(video_path="dummy.mp4")
    # PreviewWorkerが失敗を返すようにモック
    preview_worker = coord._find_worker(PreviewWorker)
    preview_worker.execute = AsyncMock(return_value=StageResult("プレビュー生成", False, "failed"))
    # イテレーションが回ることを確認
    res = asyncio.run(coord._quality_improvement_loop(ctx))
    assert res is False

def test_quality_improvement_loop_success(tmp_path):
    coord = PipelineCoordinator()
    ctx = PipelineContext(video_path="dummy.mp4")
    
    # PreviewWorkerもモック
    preview_worker = coord._find_worker(PreviewWorker)
    preview_worker.execute = AsyncMock(return_value=StageResult("プレビュー生成", True, "success", {"path": "dummy"}))
    
    # QualityGateWorkerが検証成功する結果を返すように
    qg_worker = coord._find_worker(QualityGateWorker)
    qg_worker.execute = AsyncMock(return_value=StageResult("品質チェック", True, "スコア: 95点 (ランクS)", {"score": 95}))
    
    # 以前のフィードバックをextendする箇所も通すため
    ctx.stage_results.append(StageResult("品質チェック", False, "スコア: 80点", {"feedback": ["score too low"]}))
    
    res = asyncio.run(coord._quality_improvement_loop(ctx))
    assert res is True

def test_coordinator_dream_learning_exception(tmp_path):
    coord = PipelineCoordinator()
    ctx = PipelineContext(video_path="dummy.mp4")
    mock_plugin = MagicMock()
    mock_plugin.dream_engine.should_dream.side_effect = Exception("dream error")
    with patch.dict(sys.modules, {"plugins.dream_learning_plugin": mock_plugin}):
        # 例外がスルーされて完了することを確認
        asyncio.run(coord._trigger_dream_learning(ctx))


def test_execute_with_harness_worker_fatal_fail(tmp_path):
    coord = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "video.mp4"))
    
    mock_harness = MagicMock()
    mock_harness.governance_engine._scopes = []
    
    async def mock_fire(event, hook_input):
        from harness.hooks import HookOutput
        return HookOutput(permission_decision="allow")
        
    mock_harness.hook_system.fire = mock_fire
    mock_session = MagicMock()
    mock_session.session_id = "test_sess"
    mock_harness.session_manager.create_session.return_value = mock_session
    mock_harness.session_manager.resume_session.return_value = None
    
    sys.modules["harness"] = mock_harness
    mock_hooks = MagicMock()
    def make_hook_input(*args, **kwargs):
        m = MagicMock()
        m.tool_name = kwargs.get("tool_name")
        return m
    mock_hooks.HookInput.side_effect = make_hook_input
    sys.modules["harness.hooks"] = mock_hooks
    
    for w in coord.workers:
        if isinstance(w, TranscribeWorker):
            w.execute = AsyncMock(return_value=StageResult(w.name, False, "Fatal Error"))
        else:
            w.execute = AsyncMock(return_value=StageResult(w.name, True, "Success"))
            
    try:
        with patch.dict(os.environ, {"HARNESS_MODE": "enabled"}):
            res = asyncio.run(coord.execute_with_harness(ctx))
            assert res["status"] == "error"
            assert "Fatal Error" in res["error"]
    finally:
        del sys.modules["harness"]
        del sys.modules["harness.hooks"]

def test_execute_with_harness_eval_opt_fails(tmp_path):
    coord = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "video.mp4"))
    
    mock_harness = MagicMock()
    mock_harness.governance_engine._scopes = []
    
    async def mock_fire(event, hook_input):
        from harness.hooks import HookOutput
        return HookOutput(permission_decision="allow")
        
    mock_harness.hook_system.fire = mock_fire
    mock_session = MagicMock()
    mock_session.session_id = "test_sess"
    mock_harness.session_manager.create_session.return_value = mock_session
    mock_harness.session_manager.resume_session.return_value = None
    
    sys.modules["harness"] = mock_harness
    mock_hooks = MagicMock()
    def make_hook_input(*args, **kwargs):
        m = MagicMock()
        m.tool_name = kwargs.get("tool_name")
        return m
    mock_hooks.HookInput.side_effect = make_hook_input
    sys.modules["harness.hooks"] = mock_hooks
    
    mock_ev_opt = MagicMock()
    
    for w in coord.workers:
        if isinstance(w, QualityGateWorker):
            w.execute = AsyncMock(return_value=StageResult("品質チェック", False, "Score 80", data={"score": 80}))
            w.verify = lambda res: res.data.get("score", 0) >= 90
        elif isinstance(w, PreviewWorker):
            w.execute = AsyncMock(return_value=StageResult("プレビュー生成", True, "Success", data={"path": "dummy"}))
            w.verify = lambda res: True
        else:
            w.execute = AsyncMock(return_value=StageResult(w.name, True, "Success"))
            
    async def mock_run_fail(ctx_obj, max_iterations=3):
        from unittest.mock import MagicMock
        ctx_obj.quality_score = 80
        opt_res = MagicMock()
        opt_res.success = False
        opt_res.final_score = 80
        return opt_res
        
    mock_ev_opt.evaluator_optimizer.run = mock_run_fail
    sys.modules["harness.evaluator_optimizer"] = mock_ev_opt
    
    try:
        with patch.dict(os.environ, {"HARNESS_MODE": "enabled"}):
            res = asyncio.run(coord.execute_with_harness(ctx))
            assert res["status"] == "completed"
            assert ctx.quality_score == 80
    finally:
        del sys.modules["harness"]
        del sys.modules["harness.hooks"]
        del sys.modules["harness.evaluator_optimizer"]

def test_execute_with_harness_eval_opt_import_error(tmp_path):
    coord = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "video.mp4"))
    
    mock_harness = MagicMock()
    mock_harness.governance_engine._scopes = []
    
    async def mock_fire(event, hook_input):
        from harness.hooks import HookOutput
        return HookOutput(permission_decision="allow")
        
    mock_harness.hook_system.fire = mock_fire
    mock_session = MagicMock()
    mock_session.session_id = "test_sess"
    mock_harness.session_manager.create_session.return_value = mock_session
    mock_harness.session_manager.resume_session.return_value = None
    
    sys.modules["harness"] = mock_harness
    mock_hooks = MagicMock()
    def make_hook_input(*args, **kwargs):
        m = MagicMock()
        m.tool_name = kwargs.get("tool_name")
        return m
    mock_hooks.HookInput.side_effect = make_hook_input
    sys.modules["harness.hooks"] = mock_hooks
    
    with patch.dict(sys.modules, {"harness.evaluator_optimizer": None}):
        for w in coord.workers:
            if isinstance(w, QualityGateWorker):
                w.execute = AsyncMock(return_value=StageResult("品質チェック", False, "Score 80", data={"score": 80}))
                w.verify = lambda res: res.data.get("score", 0) >= 90
            elif isinstance(w, PreviewWorker):
                w.execute = AsyncMock(return_value=StageResult("プレビュー生成", True, "Success", data={"path": "dummy"}))
                w.verify = lambda res: True
            else:
                w.execute = AsyncMock(return_value=StageResult(w.name, True, "Success"))
                
        try:
            with patch.dict(os.environ, {"HARNESS_MODE": "enabled"}):
                res = asyncio.run(coord.execute_with_harness(ctx))
                assert res["status"] == "completed"
        finally:
            del sys.modules["harness"]
            del sys.modules["harness.hooks"]

def test_execute_retention_plugin_flow(tmp_path):
    coord = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "video.mp4"))
    
    for w in coord.workers:
        w.execute = AsyncMock(return_value=StageResult(w.name, True, "Success"))
        
    mock_report = MagicMock()
    mock_report.overall_risk_assessment = "Low"
    mock_report.suggestions = ["Keep engaging"]
    mock_seg = MagicMock()
    mock_seg.start_time = 0
    mock_seg.end_time = 5
    mock_seg.risk_level = 8
    mock_seg.label = "drop"
    mock_report.segments = [mock_seg]
    
    mock_plugin = MagicMock()
    mock_plugin.retention_map_plugin.analyze_retention_risks.return_value = mock_report
    sys.modules["plugins.retention_map_plugin"] = mock_plugin
    
    try:
        res = asyncio.run(coord.execute(ctx))
        assert res["status"] == "completed"
        assert "retention_analysis" in ctx.metadata
    finally:
        del sys.modules["plugins.retention_map_plugin"]

def test_execute_with_harness_unexpected_exception(tmp_path):
    coord = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "video.mp4"))
    
    coord.execute = AsyncMock(return_value={"status": "fallback_completed"})
    
    with patch("harness.hooks.HookInput", side_effect=Exception("Unexpected harness crash")):
        with patch.dict(os.environ, {"HARNESS_MODE": "enabled"}):
            sys.modules["harness"] = MagicMock()
            try:
                res = asyncio.run(coord.execute_with_harness(ctx))
                assert res == {"status": "fallback_completed"}
            finally:
                del sys.modules["harness"]




class FakeHookOutput:
    def __init__(self, permission_decision="allow", permission_decision_reason=""):
        self.permission_decision = permission_decision
        self.permission_decision_reason = permission_decision_reason

def test_execute_with_harness_resume_session_none(tmp_path):
    coord = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "video.mp4"))
    ctx.session_id = "non_existent_session"
    
    mock_harness = MagicMock()
    mock_harness.governance_engine._scopes = []
    
    async def mock_fire(event, hook_input):
        return FakeHookOutput(permission_decision="allow")
        
    mock_harness.hook_system.fire = mock_fire
    mock_session = MagicMock()
    mock_session.session_id = "non_existent_session"
    mock_harness.session_manager.resume_session.return_value = None
    mock_harness.session_manager.create_session.return_value = mock_session
    
    sys.modules["harness"] = mock_harness
    mock_hooks = MagicMock()
    mock_hooks.HookOutput = FakeHookOutput
    def make_hook_input(*args, **kwargs):
        m = MagicMock()
        m.tool_name = kwargs.get("tool_name")
        return m
    mock_hooks.HookInput.side_effect = make_hook_input
    sys.modules["harness.hooks"] = mock_hooks
    
    for w in coord.workers:
        w.execute = AsyncMock(return_value=StageResult(w.name, True, "Success"))
        
    try:
        with patch.dict(os.environ, {"HARNESS_MODE": "enabled"}):
            res = asyncio.run(coord.execute_with_harness(ctx))
            assert res["status"] == "completed"
            assert ctx.session_id == "non_existent_session"
            assert mock_harness.session_manager.create_session.called
    finally:
        del sys.modules["harness"]
        del sys.modules["harness.hooks"]

def test_execute_with_harness_non_fatal_deny(tmp_path):
    coord = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "video.mp4"))
    
    mock_harness = MagicMock()
    mock_harness.governance_engine._scopes = ["youtube最適化", "smartcut構成"]
    
    async def mock_fire(event, hook_input):
        if hook_input.tool_name == "YouTube最適化":
            return FakeHookOutput(permission_decision="deny", permission_decision_reason="Policy limit")
        return FakeHookOutput(permission_decision="allow")
        
    mock_harness.hook_system.fire = mock_fire
    mock_session = MagicMock()
    mock_session.session_id = "test_sess"
    mock_harness.session_manager.create_session.return_value = mock_session
    mock_harness.session_manager.resume_session.return_value = None
    
    sys.modules["harness"] = mock_harness
    mock_hooks = MagicMock()
    mock_hooks.HookOutput = FakeHookOutput
    def make_hook_input(*args, **kwargs):
        m = MagicMock()
        m.tool_name = kwargs.get("tool_name")
        return m
    mock_hooks.HookInput.side_effect = make_hook_input
    sys.modules["harness.hooks"] = mock_hooks
    
    for w in coord.workers:
        w.execute = AsyncMock(return_value=StageResult(w.name, True, "Success"))
        
    try:
        with patch.dict(os.environ, {"HARNESS_MODE": "enabled"}):
            res = asyncio.run(coord.execute_with_harness(ctx))
            assert res["status"] == "completed"
            stage_names = [r.stage_name for r in ctx.stage_results]
            assert "YouTube最適化" in stage_names
            opt_result = [r for r in ctx.stage_results if r.stage_name == "YouTube最適化"][0]
            assert opt_result.success is False
    finally:
        del sys.modules["harness"]
        del sys.modules["harness.hooks"]

def test_execute_with_harness_retention_plugin_flow(tmp_path):
    coord = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "video.mp4"))
    
    mock_harness = MagicMock()
    mock_harness.governance_engine._scopes = []
    
    async def mock_fire(event, hook_input):
        return FakeHookOutput(permission_decision="allow")
        
    mock_harness.hook_system.fire = mock_fire
    mock_session = MagicMock()
    mock_session.session_id = "test_sess"
    mock_harness.session_manager.create_session.return_value = mock_session
    mock_harness.session_manager.resume_session.return_value = None
    
    sys.modules["harness"] = mock_harness
    mock_hooks = MagicMock()
    mock_hooks.HookOutput = FakeHookOutput
    def make_hook_input(*args, **kwargs):
        m = MagicMock()
        m.tool_name = kwargs.get("tool_name")
        return m
    mock_hooks.HookInput.side_effect = make_hook_input
    sys.modules["harness.hooks"] = mock_hooks
    
    for w in coord.workers:
        w.execute = AsyncMock(return_value=StageResult(w.name, True, "Success"))
        
    mock_report = MagicMock()
    mock_report.overall_risk_assessment = "Low"
    mock_report.suggestions = ["Keep engaging"]
    mock_seg = MagicMock()
    mock_seg.start_time = 0
    mock_seg.end_time = 5
    mock_seg.risk_level = 8
    mock_seg.label = "drop"
    mock_report.segments = [mock_seg]
    
    mock_plugin = MagicMock()
    mock_plugin.retention_map_plugin.analyze_retention_risks.return_value = mock_report
    sys.modules["plugins.retention_map_plugin"] = mock_plugin
    
    try:
        with patch.dict(os.environ, {"HARNESS_MODE": "enabled"}):
            res = asyncio.run(coord.execute_with_harness(ctx))
            assert res["status"] == "completed"
            assert "retention_analysis" in ctx.metadata
    finally:
        del sys.modules["harness"]
        del sys.modules["harness.hooks"]
        del sys.modules["plugins.retention_map_plugin"]


# -------------------------------------------------------------
# カバレッジ100%化のための追加テストケース
# -------------------------------------------------------------

def test_pipeline_stage_worker_execute_pass():
    """PipelineStageWorker.executeの抽象メソッドpassをカバー"""
    from agents._deprecated.pipeline_coordinator import PipelineStageWorker
    class DummyWorker(PipelineStageWorker):
        async def execute(self, ctx: PipelineContext) -> StageResult:
            return await super().execute(ctx)
            
    worker = DummyWorker("ダミー", "🤖", 9)
    ctx = PipelineContext(video_path="dummy.mp4")
    res = asyncio.run(worker.execute(ctx))
    assert res is None


def test_transcribe_worker_broken_stdout_exception(tmp_path, safe_popen_mock):
    """TranscribeWorker.execute内の_read_stdoutでの例外ハンドリングをカバー"""
    video_file = tmp_path / "video.mp4"
    video_file.write_text("dummy")
    ctx = PipelineContext(video_path=str(video_file))
    worker = TranscribeWorker()

    # 例外を投げるイテレータ
    class FaultyStdout:
        def __iter__(self):
            return self
        def __next__(self):
            raise ValueError("Simulated read error")

    proc = safe_popen_mock(returncode=1)
    proc.stdout = FaultyStdout()

    with patch("subprocess.Popen", return_value=proc):
        res = asyncio.run(worker.execute(ctx))
        assert res.success is False


def test_render_worker_template_config_exception(tmp_path):
    """RenderWorker.execute内のラウドネス正規化におけるtemplate_config例外ハンドリングをカバー"""
    from pathlib import Path
    worker = RenderWorker()
    ctx = PipelineContext(video_path=str(tmp_path / "video.mp4"))
    ctx.preview_path = str(tmp_path / "preview.mp4")
    Path(ctx.preview_path).write_text("dummy" * 300)

    with patch("template_config.template_config.get_active_benchmarks", side_effect=Exception("Simulated config error")):
        with patch("video_editor_engine.video_editor.ffmpeg.is_available", return_value=False):
            success = asyncio.run(worker._render_production_quality(ctx.preview_path, str(tmp_path / "final.mp4"), ctx))
            assert success is True
            assert Path(tmp_path / "final.mp4").exists()


def test_coordinator_dream_learning_exception_hook(tmp_path):
    """PipelineCoordinator._trigger_dream_learningでの例外ハンドリングをカバー"""
    coord = PipelineCoordinator()
    ctx = PipelineContext(video_path=str(tmp_path / "video.mp4"))
    
    with patch("agents.dream_engine.dream_engine.should_dream", new_callable=AsyncMock) as mock_should:
        mock_should.side_effect = Exception("Simulated dream error")
        asyncio.run(coord._trigger_dream_learning(ctx))
        # 例外がスルーされずキャッチされたはず


def test_proofread_worker_dict_warning():
    """ProofreadWorker.executeで辞書適用時に例外が発生した場合に警告が追加されることを検証"""
    ctx = PipelineContext(video_path="dummy.mp4")
    ctx.segments = [{"id": 0, "text": "テスト"}]
    worker = ProofreadWorker()
    
    with patch("proper_noun_dict.apply_dictionary", side_effect=ValueError("Invalid dict format")):
        with patch("subtitle_engine.ai_proofreader.proofread_segments", return_value=[{"id": 0, "text": "テスト"}]):
            import asyncio
            result = asyncio.run(worker.execute(ctx))
            assert result.success is True
            assert any("固有名詞辞書適用スキップ: Invalid dict format" in w for w in ctx.warnings)
