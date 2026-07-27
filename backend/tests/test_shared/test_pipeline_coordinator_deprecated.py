import sys
from pathlib import Path

# Ensure backend directory is in sys.path
backend_path = str(Path(__file__).parent.parent.parent)
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

import pytest
import shutil
import asyncio
import time
import json
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock

# ===========================================================================
# 1. ハーネスや外部依存モジュールのダミー定義と sys.modules 登録
# ===========================================================================

class MockHookEvent:
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    POST_TOOL_USE_FAILURE = "post_tool_use_failure"

class MockHookOutput:
    def __init__(self, permission_decision="allow", permission_decision_reason=""):
        self.permission_decision = permission_decision
        self.permission_decision_reason = permission_decision_reason

# 2026-07-26: モック注入前の sys.modules を控えておく。
# このファイルは import 時に依存モジュールを MagicMock へ差し替えるが、後始末が無いため
# 同じセッションで後から動くテストが本物の代わりに MagicMock を掴んでいた
# （quality_gate_plugins 系で 160 件が `<MagicMock ...> == 0` で失敗）。
# 差し替えたキーはモジュール終了時に元へ戻す（_uninstall_mock_modules）。
_PRE_MOCK_MODULES = sys.modules.copy()

# 辞書やその他の依存先を事前に MagicMock で登録しておく
mock_proper_noun = MagicMock()
sys.modules['proper_noun_dict'] = mock_proper_noun

mock_template_config = MagicMock()
mock_template_config.template_config = MagicMock()
sys.modules['template_config'] = mock_template_config

mock_harness_hooks = MagicMock()
mock_harness_hooks.HookEvent = MockHookEvent
mock_harness_hooks.HookOutput = MockHookOutput
mock_harness_hooks.HookInput = MagicMock
sys.modules['harness.hooks'] = mock_harness_hooks

mock_session_manager = MagicMock()
mock_sm_instance = MagicMock()
mock_session_manager.session_manager = mock_sm_instance
sys.modules['harness.session_manager'] = mock_session_manager

mock_governance = MagicMock()
mock_ge_instance = MagicMock()
mock_governance.governance_engine = mock_ge_instance
sys.modules['harness.governance'] = mock_governance

mock_eo = MagicMock()
sys.modules['harness.evaluator_optimizer'] = mock_eo

mock_harness = MagicMock()
mock_harness.hook_system = AsyncMock()
mock_harness.session_manager = mock_sm_instance
mock_harness.governance_engine = mock_ge_instance
mock_harness.hooks = mock_harness_hooks
mock_harness.evaluator_optimizer = mock_eo
sys.modules['harness'] = mock_harness

mock_retention = MagicMock()
sys.modules['plugins.retention_map_plugin'] = mock_retention

mock_video_editor = MagicMock()
mock_video_editor.video_editor = MagicMock()
sys.modules['video_editor_engine'] = mock_video_editor

mock_proofreader = MagicMock()
sys.modules['subtitle_engine.ai_proofreader'] = mock_proofreader

mock_production_pipeline = MagicMock()
sys.modules['agents.production_pipeline'] = mock_production_pipeline

mock_smart_cut = MagicMock()
sys.modules['smart_cut_engine'] = mock_smart_cut

mock_quality_gate = MagicMock()
sys.modules['quality_gate_plugins'] = mock_quality_gate

mock_dream = MagicMock()
sys.modules['agents.dream_engine'] = mock_dream

from types import ModuleType
mock_routers = ModuleType("routers")
sys.modules['routers'] = mock_routers

mock_themes_router = ModuleType("themes_router")
mock_themes_router.PRODUCTION_TEMPLATES = {}
mock_routers.themes_router = mock_themes_router
sys.modules['routers.themes_router'] = mock_themes_router

# Load the deprecated PipelineCoordinator
from agents._deprecated.pipeline_coordinator import (
    PipelineCoordinator, PipelineContext, StageResult, PipelineStageWorker,
    TranscribeWorker, ProofreadWorker, SmartCutWorker,
    PreviewWorker, QualityGateWorker, RenderWorker, YouTubeOptWorker
)

# routers だけは import 完了後すぐ元に戻す。
# ModuleType("routers") は __path__ を持たないため、これが sys.modules に残っていると
# 後続の収集で `from routers.smartcut import ...` が
# 「'routers' is not a package」で失敗する（収集はテスト実行前に全ファイル分まとめて走るため、
# モジュール終了時の後始末では間に合わない）。
# 上の import で束縛済みの参照はそのまま残るので、このモジュールのテストには影響しない。
for _name in ("routers.themes_router", "routers"):
    if _name in _PRE_MOCK_MODULES:
        sys.modules[_name] = _PRE_MOCK_MODULES[_name]
    else:
        sys.modules.pop(_name, None)

# 一旦 sys.modules を汚染しないようにバックアップ
original_modules = sys.modules.copy()

import agents._deprecated.pipeline_coordinator as coord_mod
original_coordinator = getattr(coord_mod, "pipeline_coordinator", None)


@pytest.fixture(scope="module", autouse=True)
def _uninstall_mock_modules():
    """このモジュールの全テスト終了後に、注入した MagicMock を sys.modules から取り除く。

    後続のテストが本物のモジュールを import できるようにするため。
    注入前に存在していたものは元のオブジェクトへ戻し、無かったものは削除する。
    """
    yield
    for key in list(sys.modules):
        if key in _PRE_MOCK_MODULES:
            if sys.modules[key] is not _PRE_MOCK_MODULES[key]:
                sys.modules[key] = _PRE_MOCK_MODULES[key]
        else:
            # モック下で読み込まれたモジュールは、次に必要になったとき素の状態で読み直させる
            del sys.modules[key]


@pytest.fixture(autouse=True)
def restore_sys_modules():
    """各テスト実行後に sys.modules を初期モック状態にクリーンアップする"""
    yield
    # original_modules のキーを元に戻す
    for key in list(sys.modules.keys()):
        if key not in original_modules:
            del sys.modules[key]
    for key, val in original_modules.items():
        sys.modules[key] = val
    # pipeline_coordinator グローバル変数を復元
    if original_coordinator is not None:
        coord_mod.pipeline_coordinator = original_coordinator


# ===========================================================================
# 2. 各 Worker の個別ユニットテスト
# ===========================================================================

@pytest.mark.asyncio
async def test_transcribe_worker_cache_hit(tmp_path):
    """キャッシュが存在する場合にWhisperをスキップしてキャッシュデータを読み込む"""
    worker = TranscribeWorker()
    assert worker.get_definition_of_done() is not None

    video_file = tmp_path / "video.mp4"
    video_file.write_text("dummy video content")
    
    checkpoint_file = tmp_path / "_whisper_segments.jsonl"
    dummy_segments = [
        {"start": 0.0, "end": 2.0, "text": "こんにちは"},
        {"start": 2.0, "end": 5.0, "text": "テストです"}
    ]
    with open(checkpoint_file, "w", encoding="utf-8") as f:
        for seg in dummy_segments:
            f.write(json.dumps(seg) + "\n")
    # 1000バイト以上のキャッシュサイズ
    with open(checkpoint_file, "a", encoding="utf-8") as f:
        f.write(" " * 1000)

    ctx = PipelineContext(video_path=str(video_file))
    
    result = await worker.execute(ctx)
    assert result.success is True
    assert "キャッシュ" in result.detail
    assert len(ctx.segments) == 2
    assert ctx.segments[0]["text"] == "こんにちは"
    assert worker.verify(result) is True


@pytest.mark.asyncio
async def test_transcribe_worker_subprocess_success(tmp_path):
    """キャッシュがない場合、サブプロセスを起動して正常に文字起こしする"""
    worker = TranscribeWorker()
    video_file = tmp_path / "video.mp4"
    video_file.write_text("dummy")
    
    checkpoint_file = tmp_path / "_whisper_segments.jsonl"
    
    def side_effect_popen(*args, **kwargs):
        # チェックポイントファイル書き出し
        dummy_segments = [{"start": 0.0, "end": 2.0, "text": "こんにちは"}]
        with open(checkpoint_file, "w", encoding="utf-8") as f:
            for seg in dummy_segments:
                f.write(json.dumps(seg) + "\n")
        
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_proc.returncode = 0
        mock_proc.stdout = [json.dumps({"status": "completed", "device": "cuda"})]
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = ""
        return mock_proc

    ctx = PipelineContext(video_path=str(video_file))
    
    with patch("subprocess.Popen", side_effect=side_effect_popen):
        result = await worker.execute(ctx)
        assert result.success is True
        assert "1セグメント検出" in result.detail
        assert len(ctx.segments) == 1
        assert ctx.segments[0]["text"] == "こんにちは"


@pytest.mark.asyncio
async def test_transcribe_worker_subprocess_timeout(tmp_path):
    """サブプロセスがタイムアウトし、部分的なキャッシュを使用する"""
    import subprocess as _sp
    worker = TranscribeWorker()
    video_file = tmp_path / "video.mp4"
    video_file.write_text("dummy")
    
    checkpoint_file = tmp_path / "_whisper_segments.jsonl"
    dummy_segments = [{"start": 0.0, "end": 2.0, "text": "部分結果"}]
    with open(checkpoint_file, "w", encoding="utf-8") as f:
        for seg in dummy_segments:
            f.write(json.dumps(seg) + "\n")
    with open(checkpoint_file, "a", encoding="utf-8") as f:
        f.write(" " * 600)  # 500バイト超

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    # 1回目の wait() でタイムアウト、2回目の wait(timeout=10) で正常終了(0)を返す
    mock_proc.wait.side_effect = [_sp.TimeoutExpired(cmd="whisper", timeout=10), 0]
    mock_proc.stdout = []
    mock_proc.stderr = MagicMock()
    mock_proc.stderr.read.return_value = ""

    ctx = PipelineContext(video_path=str(video_file))
    
    with patch("subprocess.Popen", return_value=mock_proc):
        result = await worker.execute(ctx)
        assert result.success is True
        assert "timeout_partial" in result.data["device"]
        assert len(ctx.segments) == 1
        assert ctx.segments[0]["text"] == "部分結果"


@pytest.mark.asyncio
async def test_transcribe_worker_subprocess_fail(tmp_path):
    """サブプロセスが異常終了し、チェックポイントもない場合は失敗する"""
    worker = TranscribeWorker()
    video_file = tmp_path / "video.mp4"
    video_file.write_text("dummy")

    mock_proc = MagicMock()
    mock_proc.poll.return_value = 1
    mock_proc.returncode = 1
    mock_proc.stdout = []
    mock_proc.stderr = MagicMock()
    mock_proc.stderr.read.return_value = "CUDA out of memory"

    ctx = PipelineContext(video_path=str(video_file))
    
    with patch("subprocess.Popen", return_value=mock_proc):
        result = await worker.execute(ctx)
        assert result.success is False
        assert "Whisperサブプロセス失敗" in result.detail


@pytest.mark.asyncio
async def test_proofread_worker_success():
    """固有名詞辞書とAI校閲が適用される正常系"""
    worker = ProofreadWorker()
    assert worker.get_definition_of_done() is not None

    ctx = PipelineContext(video_path="test.mp4")
    ctx.segments = [
        {"text": "キタハラサンの動画です"},
        {"text": "これはテストです"}
    ]

    mock_proper_noun.apply_dictionary = MagicMock(side_effect=[
        ("北原さんの動画です", ["キタハラサン"]),
        ("これはテストです", [])
    ])
    mock_proofreader.proofread_segments = MagicMock(return_value=[
        {"text": "北原さんの動画です。"},
        {"text": "これはテストです。"}
    ])

    result = await worker.execute(ctx)
    assert result.success is True
    assert result.data["dict"] == 1
    assert result.data["ai"] == 2
    assert len(ctx.segments) == 2
    assert ctx.segments[0]["text"] == "北原さんの動画です。"


@pytest.mark.asyncio
async def test_proofread_worker_exception_fallback():
    """辞書やAI校閲で例外が発生しても、非致命的エラーとして続行し警告が追加される"""
    worker = ProofreadWorker()
    ctx = PipelineContext(video_path="test.mp4")
    ctx.segments = [{"text": "テスト"}]

    mock_proper_noun.apply_dictionary = MagicMock(side_effect=Exception("dict error"))
    mock_proofreader.proofread_segments = MagicMock(side_effect=Exception("AI error"))

    result = await worker.execute(ctx)
    assert result.success is True
    assert "固有名詞辞書適用スキップ" in ctx.warnings[0]
    assert "AI校閲(Gemini)" in ctx.skipped_features


@pytest.mark.asyncio
async def test_smart_cut_worker_success():
    """SmartCutで目標の構成案を取得する"""
    worker = SmartCutWorker()
    assert worker.get_definition_of_done() is not None

    ctx = PipelineContext(video_path="test.mp4", target_minutes=10)
    ctx.segments = [{"text": "セグメント1"}, {"text": "セグメント2"}]

    dummy_proposal = {
        "proposals": [
            {
                "segments": [{"text": "セグメント1"}],
                "estimated_duration": 300
            }
        ]
    }
    mock_production_pipeline.propose_smart_cut = MagicMock(return_value=json.dumps(dummy_proposal))

    result = await worker.execute(ctx)
    assert result.success is True
    assert len(ctx.selected_segments) == 1
    assert ctx.selected_segments[0]["text"] == "セグメント1"


@pytest.mark.asyncio
async def test_smart_cut_worker_exception():
    """SmartCutで例外が発生した場合、全セグメントを保持してフォールバックする"""
    worker = SmartCutWorker()
    ctx = PipelineContext(video_path="test.mp4", target_minutes=10)
    ctx.segments = [{"text": "セグメント1"}, {"text": "セグメント2"}]

    mock_production_pipeline.propose_smart_cut = MagicMock(side_effect=Exception("smart cut API error"))

    result = await worker.execute(ctx)
    assert result.success is True
    assert len(ctx.selected_segments) == 2
    assert "SmartCut" in ctx.skipped_features


@pytest.mark.asyncio
async def test_preview_worker_success(tmp_path):
    """プレビュー生成が正常に完了する"""
    worker = PreviewWorker()
    assert worker.get_definition_of_done() is not None

    outputs_dir = tmp_path / "outputs"
    
    def side_effect_render(segs, video_path, preview_path):
        Path(preview_path).parent.mkdir(parents=True, exist_ok=True)
        Path(preview_path).write_text("dummy preview mp4 data")
        with open(preview_path, "a") as f:
            f.write(" " * 2000)
        return True

    mock_smart_cut.render_smart_cut = MagicMock(side_effect=side_effect_render)

    with patch("safe_io.VAULT_OUTPUTS_DIR", outputs_dir):
        ctx = PipelineContext(video_path="test.mp4")
        ctx.selected_segments = [{"text": "1"}]

        result = await worker.execute(ctx)
        assert result.success is True
        assert ctx.preview_path is not None
        assert Path(ctx.preview_path).exists()
        assert worker.verify(result) is True


@pytest.mark.asyncio
async def test_preview_worker_fail(tmp_path):
    """プレビュー生成処理が失敗を返す、または例外が発生する場合"""
    worker = PreviewWorker()
    outputs_dir = tmp_path / "outputs"
    
    mock_smart_cut.render_smart_cut = MagicMock(return_value=False)

    with patch("safe_io.VAULT_OUTPUTS_DIR", outputs_dir):
        ctx = PipelineContext(video_path="test.mp4")
        
        result = await worker.execute(ctx)
        assert result.success is False
        assert "プレビュー生成失敗" in result.detail

        # 例外時
        mock_smart_cut.render_smart_cut = MagicMock(side_effect=Exception("render error"))
        result2 = await worker.execute(ctx)
        assert result2.success is False
        assert "render error" in result2.detail


@pytest.mark.asyncio
async def test_quality_gate_worker_plugin_success():
    """品質ゲートがプラグイン実行を通して成功する"""
    worker = QualityGateWorker()
    assert worker.get_definition_of_done() is not None

    ctx = PipelineContext(video_path="test.mp4")
    
    mock_quality_gate.run_all_plugins = MagicMock(return_value={
        "total_deductions": 5,
        "feedback": ["音量が少し小さい"],
        "category_report": [{"category": "audio", "deduction": 5}],
        "category_scores": {"audio": 95}
    })
    
    result = await worker.execute(ctx)
    assert result.success is True
    assert result.data["score"] == 95
    assert result.data["rank"] == "S"
    assert worker.verify(result) is True


@pytest.mark.asyncio
async def test_quality_gate_worker_fallback(tmp_path):
    """quality_gate_plugins が見つからない場合のフォールバック品質チェック"""
    worker = QualityGateWorker()
    
    # quality_gate_plugins を sys.modules から一時的に削除して ImportError を起こす
    sys.modules['quality_gate_plugins'] = None

    ctx1 = PipelineContext(video_path="test.mp4")
    preview_file1 = tmp_path / "preview1.mp4"
    preview_file1.write_text(" " * 2000)
    ctx1.preview_path = str(preview_file1)
    
    result1 = await worker.execute(ctx1)
    assert result1.success is True
    assert result1.data["score"] == 100


@pytest.mark.asyncio
async def test_render_worker_success(tmp_path):
    """最終レンダリング及びラウドネス正規化が成功する"""
    worker = RenderWorker()
    assert worker.get_definition_of_done() is not None

    outputs_dir = tmp_path / "outputs"
    final_dir = outputs_dir / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    
    preview_file = tmp_path / "preview.mp4"
    preview_file.write_text("preview video data")
    
    ctx = PipelineContext(video_path="test.mp4")
    ctx.preview_path = str(preview_file)

    mock_ffmpeg = MagicMock()
    mock_ffmpeg.is_available.return_value = True
    mock_ffmpeg._get_encode_args.return_value = []
    
    def side_effect_run(cmd, timeout):
        # エンコード、または正規化コマンドでのファイル書き出し
        final_path = cmd[-1]
        Path(final_path).parent.mkdir(parents=True, exist_ok=True)
        Path(final_path).write_text("final data " * 200) # 1KB以上
        return (True, "success")

    mock_ffmpeg.run_command.side_effect = side_effect_run
    mock_video_editor.video_editor.ffmpeg = mock_ffmpeg

    with patch("safe_io.VAULT_OUTPUTS_DIR", outputs_dir):
         result = await worker.execute(ctx)
         assert result.success is True
         assert ctx.final_path is not None
         assert Path(ctx.final_path).exists()


@pytest.mark.asyncio
async def test_render_worker_encode_fail_and_copy_fallback(tmp_path):
    """エンコードが失敗した場合、プレビューファイルを最終出力先にコピーしてフォールバックする"""
    worker = RenderWorker()
    outputs_dir = tmp_path / "outputs"
    
    preview_file = tmp_path / "preview.mp4"
    preview_file.write_text("preview data " * 200)
        
    ctx = PipelineContext(video_path="test.mp4")
    ctx.preview_path = str(preview_file)

    mock_ffmpeg = MagicMock()
    mock_ffmpeg.is_available.return_value = True
    mock_ffmpeg.run_command.return_value = (False, "FFmpeg failed")
    mock_video_editor.video_editor.ffmpeg = mock_ffmpeg

    with patch("safe_io.VAULT_OUTPUTS_DIR", outputs_dir):
         result = await worker.execute(ctx)
         assert result.success is True
         assert "本番品質エンコード" in ctx.skipped_features
         assert Path(ctx.final_path).exists()


@pytest.mark.asyncio
async def test_render_worker_loudness_error(tmp_path):
    """ラウドネス正規化でエラーが発生しても、エンコード済みのファイルを維持して成功とする"""
    worker = RenderWorker()
    outputs_dir = tmp_path / "outputs"
    
    preview_file = tmp_path / "preview.mp4"
    preview_file.write_text("preview data " * 200)
        
    ctx = PipelineContext(video_path="test.mp4")
    ctx.preview_path = str(preview_file)

    mock_ffmpeg = MagicMock()
    mock_ffmpeg.is_available.return_value = True
    mock_ffmpeg._get_encode_args.return_value = []
    
    def side_effect_run(cmd, timeout):
        if "-af" in cmd:
            raise Exception("loudnorm filter error")
        final_path = cmd[-1]
        Path(final_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(preview_file, final_path)
        return (True, "encode success")

    mock_ffmpeg.run_command.side_effect = side_effect_run
    mock_video_editor.video_editor.ffmpeg = mock_ffmpeg

    with patch("safe_io.VAULT_OUTPUTS_DIR", outputs_dir):
         result = await worker.execute(ctx)
         assert result.success is True
         assert "ラウドネス正規化" in ctx.skipped_features
         assert Path(ctx.final_path).exists()


@pytest.mark.asyncio
async def test_youtube_opt_worker_success():
    """YouTubeメタデータ生成が正常に完了する"""
    worker = YouTubeOptWorker()
    assert worker.get_definition_of_done() is not None

    ctx = PipelineContext(video_path="test.mp4")
    ctx.segments = [{"text": "こんにちは"}, {"text": "世界"}]

    dummy_metadata = {
        "status": "success",
        "metadata": {
            "titles": ["キタハラ式YouTube活用法"],
            "tags": ["Vlog", "ビジネス"],
            "description": "説明文"
        }
    }
    mock_production_pipeline.generate_youtube_metadata = MagicMock(return_value=json.dumps(dummy_metadata))

    result = await worker.execute(ctx)
    assert result.success is True
    assert ctx.metadata["titles"][0] == "キタハラ式YouTube活用法"


@pytest.mark.asyncio
async def test_youtube_opt_worker_fallback():
    """例外発生時のYouTubeメタデータ簡易自動生成フォールバック"""
    worker = YouTubeOptWorker()
    ctx = PipelineContext(video_path="test.mp4")
    ctx.segments = [
        {"text": "これはテスト動画です。キタハラサンのチャンネル登録よろしく。"},
        {"start": 320, "end": 350, "text": "チャプター2の内容です。"}
    ]

    mock_production_pipeline.generate_youtube_metadata = MagicMock(side_effect=Exception("API quota error"))

    result = await worker.execute(ctx)
    assert result.success is True
    assert "YouTube最適化(Gemini)" in ctx.skipped_features
    assert len(ctx.metadata["tags"]) >= 1
    assert "description" in ctx.metadata
    assert len(ctx.metadata["chapters"]) == 2


# ===========================================================================
# 3. PipelineCoordinator のユニットテスト
# ===========================================================================

@pytest.mark.asyncio
async def test_pipeline_coordinator_disk_space_error():
    """ディスク容量が最低制限(1GB)未満の場合にエラー終了する"""
    pc = PipelineCoordinator()
    ctx = PipelineContext(video_path="test.mp4")

    mock_usage = MagicMock(free=500 * 1024 * 1024)
    with patch("shutil.disk_usage", return_value=mock_usage):
        result = await pc.execute(ctx)
        assert result["status"] == "error"
        assert "ディスク空き容量不足" in result["error"]


@pytest.mark.asyncio
async def test_pipeline_coordinator_disk_space_warning():
    """ディスク容量が注意制限(5GB)未満の場合に警告を記録して続行する"""
    pc = PipelineCoordinator()
    ctx = PipelineContext(video_path="test.mp4")

    mock_usage = MagicMock(free=3 * 1024 * 1024 * 1024)
    for worker in pc.workers:
        worker.execute = AsyncMock(return_value=StageResult(stage_name=worker.name, success=True, detail="ok"))
        worker.verify = MagicMock(return_value=True)

    with patch("shutil.disk_usage", return_value=mock_usage), \
         patch.object(pc, "_run_retention_analysis", return_value=None), \
         patch.object(pc, "_trigger_dream_learning", return_value=None):
         
         result = await pc.execute(ctx)
         assert result["status"] == "completed"
         assert any("ディスク残量注意: 3.0GB" in w for w in ctx.warnings)


@pytest.mark.asyncio
async def test_pipeline_coordinator_execute_success_and_retry():
    """Workerのリトライ及び正常終了、WebSocket通知の確認"""
    pc = PipelineCoordinator()
    ctx = PipelineContext(video_path="test.mp4")

    mock_ws = AsyncMock()
    pc.set_ws_broadcast(mock_ws)
    
    mock_progress = MagicMock()
    pc.set_progress_callback(mock_progress)

    transcribe_worker = pc.workers[0]
    transcribe_worker.verify = MagicMock(side_effect=[False, True])
    transcribe_worker.execute = AsyncMock(side_effect=[
        StageResult(stage_name=transcribe_worker.name, success=False, detail="Failed first"),
        StageResult(stage_name=transcribe_worker.name, success=True, detail="Success second")
    ])

    for w in pc.workers[1:]:
        w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail="ok"))
        w.verify = MagicMock(return_value=True)

    mock_usage = MagicMock(free=10 * 1024 * 1024 * 1024)
    with patch("shutil.disk_usage", return_value=mock_usage), \
         patch.object(pc, "_run_retention_analysis", return_value=None), \
         patch.object(pc, "_trigger_dream_learning", return_value=None):
         
         result = await pc.execute(ctx)
         assert result["status"] == "completed"
         mock_ws.assert_called()
         mock_progress.assert_called()
         
         transcribe_res = next(r for r in ctx.stage_results if r.stage_name == transcribe_worker.name)
         assert transcribe_res.retries == 1


@pytest.mark.asyncio
async def test_pipeline_coordinator_quality_improvement_loop(tmp_path):
    """品質ゲートが不合格だった場合に、プレビュー再生成を繰り返す品質改善ループ"""
    pc = PipelineCoordinator()
    ctx = PipelineContext(video_path="test.mp4")

    qg_worker = pc._find_worker(QualityGateWorker)
    preview_worker = pc._find_worker(PreviewWorker)

    # loopの中でqg_worker.executeが呼ばれた時にctx.quality_scoreを92に更新するように設定する
    async def side_effect_qg(context):
        context.quality_score = 92
        return StageResult(stage_name=qg_worker.name, success=True, detail="score=92", data={"feedback": []})

    qg_worker.verify = MagicMock(side_effect=[False, True])
    qg_worker.execute = AsyncMock(side_effect=side_effect_qg)
    
    preview_worker.execute = AsyncMock(return_value=StageResult(stage_name=preview_worker.name, success=True, detail="preview re-rendered"))

    res = await pc._quality_improvement_loop(ctx)
    assert res is True
    assert preview_worker.execute.call_count == 2
    assert qg_worker.execute.call_count == 2


@pytest.mark.asyncio
async def test_pipeline_coordinator_retention_analysis():
    """Retention Map分析の実行と結果のメタデータ紐付け"""
    pc = PipelineCoordinator()
    ctx = PipelineContext(video_path="test.mp4")
    ctx.segments = [{"start": 0, "end": 10}, {"start": 10, "end": 20}]

    mock_report = MagicMock()
    mock_report.overall_risk_assessment = "Low Risk"
    mock_segment = MagicMock()
    mock_segment.start_time = 10
    mock_segment.end_time = 20
    mock_segment.risk_level = 8
    mock_segment.label = "dropoff"
    mock_report.segments = [mock_segment]
    mock_report.suggestions = ["Engage early"]

    mock_retention.retention_map_plugin = MagicMock()
    mock_retention.retention_map_plugin.analyze_retention_risks.return_value = mock_report

    res = await pc._run_retention_analysis(ctx)
    assert res is not None
    assert res.stage_name == "Retention分析"
    assert ctx.metadata["retention_analysis"]["overall_risk"] == "Low Risk"


@pytest.mark.asyncio
async def test_pipeline_coordinator_dream_learning(tmp_path):
    """学習トリガー判定とDreamEngineへの接続"""
    pc = PipelineCoordinator()
    
    import agents._deprecated.pipeline_coordinator as coord_mod
    with patch.object(coord_mod, "__file__", str(tmp_path / "pipeline_coordinator.py")):
        ctx = PipelineContext(video_path="test.mp4")
        ctx.segments = [{"text": "1"}]
        ctx.selected_segments = [{"text": "1"}]
        ctx.quality_score = 95
        ctx.stage_results = [StageResult(stage_name="AI校閲", success=True, data={"total": 2})]

        mock_dream.dream_engine = MagicMock()
        mock_dream.dream_engine.should_dream = AsyncMock(return_value=True)
        mock_dream.dream_engine.run_dream_cycle = AsyncMock()

        await pc._trigger_dream_learning(ctx)
        
        knowledge_dir = tmp_path / "logs" / "pipeline_knowledge"
        assert knowledge_dir.exists()
        assert len(list(knowledge_dir.glob("run_*.json"))) == 1
        
        mock_dream.dream_engine.should_dream.assert_called_once()
        mock_dream.dream_engine.run_dream_cycle.assert_called_once()


# ===========================================================================
# 4. execute_with_harness パスのユニットテスト
# ===========================================================================

@pytest.mark.asyncio
async def test_execute_with_harness_disabled():
    """HARNESS_MODEがdisabledの場合にレガシーのexecuteを直接呼び出す"""
    pc = PipelineCoordinator()
    ctx = PipelineContext(video_path="test.mp4")
    
    mock_execute = AsyncMock(return_value={"status": "completed"})
    
    with patch.dict("os.environ", {"HARNESS_MODE": "disabled"}), \
         patch.object(pc, "execute", mock_execute):
         
         res = await pc.execute_with_harness(ctx)
         assert res["status"] == "completed"
         mock_execute.assert_called_once_with(ctx)


@pytest.mark.asyncio
async def test_execute_with_harness_denied():
    """Harness Hook で deny 判定が発生した場合にパイプラインが停止する"""
    pc = PipelineCoordinator()
    ctx = PipelineContext(video_path="test.mp4")

    mock_session = MagicMock(session_id="session123")
    mock_sm_instance.create_session.return_value = mock_session
    mock_sm_instance.resume_session.return_value = None

    mock_pre_output = MagicMock()
    mock_pre_output.permission_decision = "deny"
    mock_pre_output.permission_decision_reason = "Mock Hook Deny"
    mock_harness.hook_system.fire = AsyncMock(return_value=mock_pre_output)

    # Hook Event などの属性を Mock にするのではなく本物の MockHookEvent を使う
    mock_harness_hooks.HookEvent = MockHookEvent
    mock_harness_hooks.HookOutput = MockHookOutput
    mock_harness_hooks.HookInput = MagicMock

    res = await pc.execute_with_harness(ctx)
    assert res["status"] == "error"
    assert "Mock Hook Deny" in res["error"]
    mock_sm_instance.error_session.assert_called_once_with("session123", "Hook denied at 文字起こし")


@pytest.mark.asyncio
async def test_execute_with_harness_evaluator_optimizer():
    """Harness環境下で品質ゲート不合格時に Evaluator-Optimizer ワークフローが起動する"""
    pc = PipelineCoordinator()
    ctx = PipelineContext(video_path="test.mp4")

    mock_session = MagicMock(session_id="session123")
    mock_sm_instance.create_session.return_value = mock_session
    mock_sm_instance.resume_session.return_value = None

    mock_pre_output = MagicMock()
    mock_pre_output.permission_decision = "allow"
    mock_harness.hook_system.fire = AsyncMock(return_value=mock_pre_output)

    for w in pc.workers:
        w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail="ok", duration_seconds=0.1, data={}))
        w.verify = MagicMock(return_value=True)
    
    qg_worker = pc._find_worker(QualityGateWorker)
    qg_worker.verify = MagicMock(return_value=False)

    mock_opt_result = MagicMock()
    mock_opt_result.success = True
    mock_opt_result.initial_score = 85
    mock_opt_result.final_score = 92
    mock_opt_result.iterations = 2
    mock_opt_result.improvements_applied = ["loudness_fix"]
    mock_opt_result.duration_seconds = 3.0
    
    mock_eo.evaluator_optimizer = AsyncMock()
    mock_eo.evaluator_optimizer.run = AsyncMock(return_value=mock_opt_result)

    with patch.object(pc, "_run_retention_analysis", return_value=None), \
         patch.object(pc, "_trigger_dream_learning", return_value=None):
         
         res = await pc.execute_with_harness(ctx)
         assert res["status"] == "completed"
         mock_sm_instance.record_tool_call.assert_any_call(
             "session123", "evaluator_optimizer",
             {"iterations": 2}, {"improvements": ["loudness_fix"]}, 3.0
         )


# ===========================================================================
# 5. カバレッジ向上のための追加ユニットテスト
# ===========================================================================

@pytest.mark.asyncio
async def test_transcribe_worker_read_thread_exception(tmp_path):
    """Whisperのstdout読み取りスレッド内で例外（JSONパース失敗等）が発生しても安全に処理されること"""
    worker = TranscribeWorker()
    video_file = tmp_path / "video.mp4"
    video_file.write_text("dummy")
    
    checkpoint_file = tmp_path / "_whisper_segments.jsonl"
    
    def side_effect_popen(*args, **kwargs):
        # チェックポイントファイル書き出し
        dummy_segments = [{"start": 0.0, "end": 2.0, "text": "こんにちは"}]
        with open(checkpoint_file, "w", encoding="utf-8") as f:
            for seg in dummy_segments:
                f.write(json.dumps(seg) + "\n")
        # 1000バイト以上のキャッシュサイズにして、プロセス正常終了時のフォールバックを通過させる
        with open(checkpoint_file, "a", encoding="utf-8") as f:
            f.write(" " * 1500)
        
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_proc.returncode = 0
        # パースできないゴミデータや空文字、進捗、不正JSON、TypeErrorを誘発させるオブジェクトなど
        # これにより _read_stdout の全エラー/分岐パスを網羅する
        mock_proc.stdout = ["invalid json", "", json.dumps({"progress": 50}), None, json.dumps({"status": "completed"})]
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = ""
        return mock_proc

    ctx = PipelineContext(video_path=str(video_file))
    with patch("subprocess.Popen", side_effect=side_effect_popen):
        result = await worker.execute(ctx)
        assert result.success is True
        assert len(ctx.segments) == 1


@pytest.mark.asyncio
async def test_transcribe_worker_timeout_no_checkpoint(tmp_path):
    """タイムアウトが発生し、かつサイズが足りないチェックポイントしかない場合は失敗すること"""
    import subprocess as _sp
    worker = TranscribeWorker()
    video_file = tmp_path / "video.mp4"
    video_file.write_text("dummy")
    
    # 500バイト未満のチェックポイント
    checkpoint_file = tmp_path / "_whisper_segments.jsonl"
    checkpoint_file.write_text("small")

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.wait.side_effect = [_sp.TimeoutExpired(cmd="whisper", timeout=10), 0]
    mock_proc.stdout = []
    mock_proc.stderr = MagicMock()
    mock_proc.stderr.read.return_value = "timeout error detail"

    ctx = PipelineContext(video_path=str(video_file))
    with patch("subprocess.Popen", return_value=mock_proc):
        result = await worker.execute(ctx)
        assert result.success is False
        assert "タイムアウト" in result.detail or "timeout" in result.detail.lower() or "timed out" in result.detail.lower()


@pytest.mark.asyncio
async def test_transcribe_worker_subprocess_fail_no_checkpoint(tmp_path):
    """サブプロセスがエラーで終了し、かつチェックポイントもない場合は失敗すること"""
    worker = TranscribeWorker()
    video_file = tmp_path / "video.mp4"
    video_file.write_text("dummy")

    mock_proc = MagicMock()
    mock_proc.poll.return_value = 1
    mock_proc.returncode = 1
    mock_proc.stdout = []
    mock_proc.stderr = MagicMock()
    mock_proc.stderr.read.return_value = "CUDA out of memory"

    ctx = PipelineContext(video_path=str(video_file))
    with patch("subprocess.Popen", return_value=mock_proc):
        result = await worker.execute(ctx)
        assert result.success is False
        assert "Whisperサブプロセス失敗" in result.detail or "CUDA" in result.detail


@pytest.mark.asyncio
async def test_quality_gate_worker_fallback_missing_preview_and_small_size(tmp_path):
    """プラグインエンジンがない場合のフォールバックで、プレビューなし・サイズ小の減点ロジック"""
    worker = QualityGateWorker()
    
    # quality_gate_plugins を一時的に無効化
    sys.modules['quality_gate_plugins'] = None

    # パターン1: プレビューパスなし
    ctx1 = PipelineContext(video_path="test.mp4")
    result1 = await worker.execute(ctx1)
    assert result1.success is False
    assert result1.data["score"] == 80  # 100 - 20 = 80
    assert "プレビューファイルが存在しない" in result1.data["feedback"]

    # パターン2: プレビューパスが存在するが、サイズが1KB未満
    ctx2 = PipelineContext(video_path="test.mp4")
    small_file = tmp_path / "small.mp4"
    small_file.write_text("small text")  # 数十バイト
    ctx2.preview_path = str(small_file)
    result2 = await worker.execute(ctx2)
    assert result2.success is False
    assert result2.data["score"] == 70  # 100 - 30 = 70
    assert "ファイルサイズが異常に小さい" in result2.data["feedback"]


@pytest.mark.asyncio
async def test_render_worker_execute_exception(tmp_path):
    """RenderWorker の execute 内で想定外の例外が発生した際の StageResult 失敗確認"""
    worker = RenderWorker()
    ctx = PipelineContext(video_path="test.mp4")
    
    # preview_path を None にして、かつ例外を発生させる
    with patch.object(Path, "mkdir", side_effect=Exception("Unexpected path exception")):
        result = await worker.execute(ctx)
        assert result.success is False
        assert "Unexpected path exception" in result.detail


@pytest.mark.asyncio
async def test_render_worker_ffmpeg_missing_fallback(tmp_path):
    """FFmpeg未検出、または video_editor_engine インポート例外時のコピーフォールバック"""
    worker = RenderWorker()
    outputs_dir = tmp_path / "outputs"
    preview_file = tmp_path / "preview.mp4"
    preview_file.write_text("preview data" * 200)
    
    ctx = PipelineContext(video_path="test.mp4")
    ctx.preview_path = str(preview_file)

    # パターン1: ffmpeg が is_available = False を返す場合
    mock_ffmpeg = MagicMock()
    mock_ffmpeg.is_available.return_value = False
    mock_video_editor.video_editor.ffmpeg = mock_ffmpeg

    with patch("safe_io.VAULT_OUTPUTS_DIR", outputs_dir):
        result = await worker.execute(ctx)
        assert result.success is True
        assert Path(ctx.final_path).exists()

    # パターン2: video_editor_engine インポートエラーをシミュレート
    # sys.modules から一時的に削除して ImportError
    sys.modules['video_editor_engine'] = None
    
    # contextをクリアして再試行
    ctx2 = PipelineContext(video_path="test.mp4")
    ctx2.preview_path = str(preview_file)
    with patch("safe_io.VAULT_OUTPUTS_DIR", outputs_dir):
        result2 = await worker.execute(ctx2)
        assert result2.success is True
        assert Path(ctx2.final_path).exists()


@pytest.mark.asyncio
async def test_pipeline_coordinator_find_worker_none():
    """_find_worker で存在しない Worker タイプを指定した場合に None が返ること"""
    pc = PipelineCoordinator()
    class DummyWorker:
        pass
    worker = pc._find_worker(DummyWorker)
    assert worker is None


@pytest.mark.asyncio
async def test_pipeline_coordinator_disk_usage_exception(tmp_path):
    """disk_usage 取得で例外が発生してもパイプラインが正常に続行すること"""
    pc = PipelineCoordinator()
    ctx = PipelineContext(video_path="test.mp4")
    
    for worker in pc.workers:
        worker.execute = AsyncMock(return_value=StageResult(stage_name=worker.name, success=True, detail="ok"))
        worker.verify = MagicMock(return_value=True)

    with patch("shutil.disk_usage", side_effect=Exception("Disk check error")), \
         patch.object(pc, "_run_retention_analysis", return_value=None), \
         patch.object(pc, "_trigger_dream_learning", return_value=None):
         
         result = await pc.execute(ctx)
         assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_pipeline_coordinator_template_restore_exception(tmp_path):
    """テンプレート復元処理で例外が発生してもパイプラインが正常に続行すること"""
    mock_template_config.template_config.set_active_template.reset_mock()
    pc = PipelineCoordinator()
    ctx = PipelineContext(video_path="test.mp4")
    ctx.template_id = "some_template"
    
    for worker in pc.workers:
        worker.execute = AsyncMock(return_value=StageResult(stage_name=worker.name, success=True, detail="ok"))
        worker.verify = MagicMock(return_value=True)

    # template_config の set_active_template が例外を投げるように設定
    mock_template_config.template_config.is_active = False
    mock_template_config.template_config.set_active_template.side_effect = Exception("Theme error")
    
    # PRODUCTION_TEMPLATES を設定
    mock_themes_router.PRODUCTION_TEMPLATES = {"some_template": {"theme": "warm"}}

    with patch.object(pc, "_run_retention_analysis", return_value=None), \
         patch.object(pc, "_trigger_dream_learning", return_value=None):
         
         result = await pc.execute(ctx)
         assert result["status"] == "completed"
         
    # side_effect をリセット
    mock_template_config.template_config.set_active_template.side_effect = None


@pytest.mark.asyncio
async def test_pipeline_coordinator_non_fatal_stage_fail(tmp_path):
    """非致命的なステージ（文字起こし(0)・プレビュー(3)以外。例: AI校閲など）が失敗しても中断せず完了すること"""
    pc = PipelineCoordinator()
    ctx = PipelineContext(video_path="test.mp4")

    # index=1 (ProofreadWorker) のみ失敗させ、verify=True (非致命的なので verify は True)
    # verifyがFalseであっても、non-fatalステージなら中断はしない
    proofread_worker = pc.workers[1]
    proofread_worker.execute = AsyncMock(return_value=StageResult(stage_name=proofread_worker.name, success=False, detail="non fatal fail"))
    proofread_worker.verify = MagicMock(return_value=False)

    for w in pc.workers:
        if w != proofread_worker:
            w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail="ok"))
            w.verify = MagicMock(return_value=True)

    mock_usage = MagicMock(free=10 * 1024 * 1024 * 1024)
    with patch("shutil.disk_usage", return_value=mock_usage), \
         patch.object(pc, "_run_retention_analysis", return_value=None), \
         patch.object(pc, "_trigger_dream_learning", return_value=None):
         
         result = await pc.execute(ctx)
         assert result["status"] == "completed"
         # 中断されていないこと
         assert any(r.stage_name == "最終レンダリング" for r in ctx.stage_results)


@pytest.mark.asyncio
async def test_pipeline_coordinator_retention_analysis_exception(tmp_path):
    """Retention Map分析実行中に例外が発生してもパイプライン全体は正常完了すること"""
    pc = PipelineCoordinator()
    ctx = PipelineContext(video_path="test.mp4")
    
    for worker in pc.workers:
        worker.execute = AsyncMock(return_value=StageResult(stage_name=worker.name, success=True, detail="ok"))
        worker.verify = MagicMock(return_value=True)

    mock_retention.retention_map_plugin.analyze_retention_risks.side_effect = Exception("Retention plugin crash")

    mock_usage = MagicMock(free=10 * 1024 * 1024 * 1024)
    with patch("shutil.disk_usage", return_value=mock_usage), \
         patch.object(pc, "_trigger_dream_learning", return_value=None):
         
         result = await pc.execute(ctx)
         assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_pipeline_coordinator_dream_learning_exception(tmp_path):
    """DreamEngine学習フックで例外が発生してもパイプライン全体は正常完了すること"""
    pc = PipelineCoordinator()
    ctx = PipelineContext(video_path="test.mp4")
    
    for worker in pc.workers:
        worker.execute = AsyncMock(return_value=StageResult(stage_name=worker.name, success=True, detail="ok"))
        worker.verify = MagicMock(return_value=True)

    mock_dream.dream_engine.should_dream.side_effect = Exception("Dream engine crashed")

    mock_usage = MagicMock(free=10 * 1024 * 1024 * 1024)
    with patch("shutil.disk_usage", return_value=mock_usage), \
         patch.object(pc, "_run_retention_analysis", return_value=None):
         
         result = await pc.execute(ctx)
         assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_quality_improvement_loop_missing_workers():
    """PreviewWorker または QualityGateWorker が見つからない場合に改善ループが False を返すこと"""
    pc = PipelineCoordinator()
    ctx = PipelineContext(video_path="test.mp4")
    
    # Workerをクリアして見つからない状況を作る
    pc.workers = []
    
    res = await pc._quality_improvement_loop(ctx)
    assert res is False


@pytest.mark.asyncio
async def test_quality_improvement_loop_feedback_accumulation():
    """改善ループの各イテレーションで品質フィードバックが蓄積されること"""
    pc = PipelineCoordinator()
    ctx = PipelineContext(video_path="test.mp4")

    qg_worker = pc._find_worker(QualityGateWorker)
    preview_worker = pc._find_worker(PreviewWorker)

    # 1回目は feedback を含む StageResult
    # 2回目に合格するように verify を設定
    qg_worker.verify = MagicMock(side_effect=[False, True])
    
    async def side_effect_qg(context):
        context.quality_score = 95
        return StageResult(
            stage_name=qg_worker.name,
            success=True,
            detail="good",
            data={"feedback": ["フィードバック1"]}
        )

    qg_worker.execute = AsyncMock(side_effect_qg)
    preview_worker.execute = AsyncMock(return_value=StageResult(stage_name=preview_worker.name, success=True))

    # 初回の stage_result としてフィードバック付きのものを登録しておく
    ctx.stage_results.append(StageResult(
        stage_name=qg_worker.name,
        success=False,
        data={"feedback": ["初期フィードバック"]}
    ))

    res = await pc._quality_improvement_loop(ctx)
    assert res is True
    assert "初期フィードバック" in ctx.quality_feedback


@pytest.mark.asyncio
async def test_quality_improvement_loop_preview_fail_continue():
    """改善ループ内でプレビュー生成が失敗した場合に continue し、上限に達して False が返ること"""
    pc = PipelineCoordinator()
    ctx = PipelineContext(video_path="test.mp4")

    qg_worker = pc._find_worker(QualityGateWorker)
    preview_worker = pc._find_worker(PreviewWorker)

    # プレビュー生成を失敗させる
    preview_worker.execute = AsyncMock(return_value=StageResult(stage_name=preview_worker.name, success=False, detail="fail"))
    
    res = await pc._quality_improvement_loop(ctx)
    assert res is False
    # preview_worker.execute が MAX_QUALITY_RETRIES (3) 回呼ばれることを確認
    assert preview_worker.execute.call_count == 3


@pytest.mark.asyncio
async def test_execute_with_harness_resume_session():
    """既存の session_id が渡された場合に、resume_session が呼ばれること"""
    pc = PipelineCoordinator()
    ctx = PipelineContext(video_path="test.mp4", session_id="session123")

    mock_session = MagicMock(session_id="session123")
    mock_sm_instance.resume_session.return_value = mock_session

    # Hook 出力を allow に
    mock_pre_output = MagicMock(permission_decision="allow")
    mock_harness.hook_system.fire = AsyncMock(return_value=mock_pre_output)

    # 全Workerを成功させる
    for w in pc.workers:
        w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail="ok", duration_seconds=0.1, data={}))
        w.verify = MagicMock(return_value=True)

    with patch.object(pc, "_run_retention_analysis", return_value=None), \
         patch.object(pc, "_trigger_dream_learning", return_value=None):
         
         res = await pc.execute_with_harness(ctx)
         assert res["status"] == "completed"
         mock_sm_instance.resume_session.assert_called_once_with("session123")


@pytest.mark.asyncio
async def test_execute_with_harness_non_fatal_deny():
    """Harness PreToolUse Hook で deny 判定かつ非致命的ステージの場合、中断せず続行すること"""
    pc = PipelineCoordinator()
    ctx = PipelineContext(video_path="test.mp4")

    mock_session = MagicMock(session_id="session123")
    mock_sm_instance.create_session.return_value = mock_session
    mock_sm_instance.resume_session.return_value = None

    # Hook Event で AI校閲(index=1) のみ deny にする
    async def side_effect_hook(event, hook_input):
        mock_out = MagicMock()
        if hook_input.tool_name == "AI校閲":
            mock_out.permission_decision = "deny"
            mock_out.permission_decision_reason = "Denied AI"
        else:
            mock_out.permission_decision = "allow"
        return mock_out

    mock_harness.hook_system.fire = AsyncMock(side_effect=side_effect_hook)

    for w in pc.workers:
        w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail="ok", duration_seconds=0.1, data={}))
        w.verify = MagicMock(return_value=True)

    with patch.object(pc, "_run_retention_analysis", return_value=None), \
         patch.object(pc, "_trigger_dream_learning", return_value=None):
         
         res = await pc.execute_with_harness(ctx)
         assert res["status"] == "completed"
         # AI校閲が deny され、結果に Hook denied が追加されていること
         ai_res = next(r for r in ctx.stage_results if r.stage_name == "AI校閲")
         assert "Hook denied" in ai_res.detail


@pytest.mark.asyncio
async def test_execute_with_harness_governance_scope():
    """ governance_engine._scopes にマッチする agent_id の権限チェックパスを通す """
    pc = PipelineCoordinator()
    ctx = PipelineContext(video_path="test.mp4")

    mock_session = MagicMock(session_id="session123")
    mock_sm_instance.create_session.return_value = mock_session
    mock_sm_instance.resume_session.return_value = None

    mock_pre_output = MagicMock(permission_decision="allow")
    mock_harness.hook_system.fire = AsyncMock(return_value=mock_pre_output)

    for w in pc.workers:
        w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail="ok", duration_seconds=0.1, data={}))
        w.verify = MagicMock(return_value=True)

    # scope ID と Worker 属性のマッチングを検証するため、_scopes を設定
    mock_ge_instance._scopes = ["文字起こし", "preview"]

    with patch.object(pc, "_run_retention_analysis", return_value=None), \
         patch.object(pc, "_trigger_dream_learning", return_value=None):
         
         res = await pc.execute_with_harness(ctx)
         assert res["status"] == "completed"


@pytest.mark.asyncio
async def test_execute_with_harness_post_tool_failure():
    """PostToolUseFailure Hook が発火し、致命的ステージの失敗により中断されること"""
    pc = PipelineCoordinator()
    ctx = PipelineContext(video_path="test.mp4")

    mock_session = MagicMock(session_id="session123")
    mock_sm_instance.create_session.return_value = mock_session
    mock_sm_instance.resume_session.return_value = None

    mock_pre_output = MagicMock(permission_decision="allow")
    mock_harness.hook_system.fire = AsyncMock(return_value=mock_pre_output)

    # 1つ目の Worker (文字起こし, index=0) を失敗させる
    transcribe_worker = pc.workers[0]
    transcribe_worker.execute = AsyncMock(return_value=StageResult(stage_name=transcribe_worker.name, success=False, detail="Transcribe failed"))
    transcribe_worker.verify = MagicMock(return_value=False)

    for w in pc.workers[1:]:
        w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail="ok"))
        w.verify = MagicMock(return_value=True)

    res = await pc.execute_with_harness(ctx)
    assert res["status"] == "error"
    from unittest.mock import ANY
    mock_harness.hook_system.fire.assert_any_call(
        MockHookEvent.POST_TOOL_USE_FAILURE,
        ANY
    )


@pytest.mark.asyncio
async def test_execute_with_harness_evaluator_optimizer_fail_fallback():
    """Evaluator-Optimizer が不合格のまま終了したケース、および Evaluator-Optimizer インポートエラー時の動作"""
    pc = PipelineCoordinator()
    ctx = PipelineContext(video_path="test.mp4")

    mock_session = MagicMock(session_id="session123")
    mock_sm_instance.create_session.return_value = mock_session
    mock_sm_instance.resume_session.return_value = None

    mock_pre_output = MagicMock(permission_decision="allow")
    mock_harness.hook_system.fire = AsyncMock(return_value=mock_pre_output)

    for w in pc.workers:
        w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail="ok"))
        w.verify = MagicMock(return_value=True)

    qg_worker = pc._find_worker(QualityGateWorker)
    qg_worker.verify = MagicMock(return_value=False)

    # パターン1: Evaluator-Optimizer が不合格で終了
    mock_opt_result = MagicMock()
    mock_opt_result.success = False
    mock_opt_result.final_score = 88
    mock_eo.evaluator_optimizer.run = AsyncMock(return_value=mock_opt_result)

    with patch.object(pc, "_run_retention_analysis", return_value=None), \
         patch.object(pc, "_trigger_dream_learning", return_value=None):
         
         res = await pc.execute_with_harness(ctx)
         assert res["status"] == "completed" # 品質合格しなくても全体は completed で返る

    # パターン2: Evaluator-Optimizer 未導入時のレガシー改善ループへのフォールバック（成功）
    sys.modules['harness.evaluator_optimizer'] = None
    
    # 改善ループをモックして成功させる
    mock_improvement_loop = AsyncMock(return_value=True)
    with patch.object(pc, "_run_retention_analysis", return_value=None), \
         patch.object(pc, "_trigger_dream_learning", return_value=None), \
         patch.object(pc, "_quality_improvement_loop", mock_improvement_loop):
         
         res2 = await pc.execute_with_harness(ctx)
         assert res2["status"] == "completed"
         mock_improvement_loop.assert_called_once()

    # パターン3: Evaluator-Optimizer 未導入時のレガシー改善ループ失敗（1159行目）および Retention分析成功（1164行目）
    sys.modules['harness.evaluator_optimizer'] = None
    mock_improvement_loop_fail = AsyncMock(return_value=False)
    mock_report = StageResult(stage_name="Retention分析", success=True, detail="ok")
    
    # 新しいコンテキストを用意して実行
    ctx3 = PipelineContext(video_path="test.mp4")
    for w in pc.workers:
        w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail="ok"))
        w.verify = MagicMock(return_value=True)
    qg_w = pc._find_worker(QualityGateWorker)
    qg_w.verify = MagicMock(return_value=False)
    
    with patch.object(pc, "_run_retention_analysis", return_value=mock_report), \
         patch.object(pc, "_trigger_dream_learning", return_value=None), \
         patch.object(pc, "_quality_improvement_loop", mock_improvement_loop_fail):
         
         res3 = await pc.execute_with_harness(ctx3)
         assert res3["status"] == "completed"
         mock_improvement_loop_fail.assert_called_once()
         assert any(r.stage_name == "Retention分析" for r in ctx3.stage_results)


@pytest.mark.asyncio
async def test_execute_with_harness_import_error_fallback():
    """Harnessモジュールインポートエラー時のレガシー execute フォールバック"""
    pc = PipelineCoordinator()
    ctx = PipelineContext(video_path="test.mp4")

    # harness をインポートエラーにするため None に設定
    sys.modules['harness'] = None

    mock_execute = AsyncMock(return_value={"status": "completed_legacy"})
    with patch.object(pc, "execute", mock_execute):
        res = await pc.execute_with_harness(ctx)
        assert res["status"] == "completed_legacy"
        mock_execute.assert_called_once_with(ctx)


# ===========================================================================
# 6. 極限カバレッジ向上のための追加ユニットテスト
# ===========================================================================

@pytest.mark.asyncio
async def test_pipeline_stage_worker_base():
    """PipelineStageWorker 基底クラスのデフォルト実装をカバー (82, 86, 90)"""
    class DummyWorker(PipelineStageWorker):
        pass
    DummyWorker.__abstractmethods__ = set()
    worker = DummyWorker("Dummy", "icon", 9)
    await worker.execute(None)
    assert worker.get_definition_of_done() == "Dummy completed successfully"
    assert worker.verify(StageResult("Dummy", True)) is True


@pytest.mark.asyncio
async def test_transcribe_worker_name_error_handling(tmp_path):
    """pipeline_coordinator グローバル変数が存在しない場合の例外処理をカバー (141-142)"""
    worker = TranscribeWorker()
    video_file = tmp_path / "video.mp4"
    video_file.write_text("dummy")
    
    checkpoint_file = tmp_path / "_whisper_segments.jsonl"
    
    # グローバル変数を削除して NameError を誘発
    if hasattr(coord_mod, "pipeline_coordinator"):
        del coord_mod.pipeline_coordinator
        
    def side_effect_popen(*args, **kwargs):
        # 1000B以上のチェックポイントファイルを用意してフォールバック通過させる
        with open(checkpoint_file, "w", encoding="utf-8") as f:
            f.write(json.dumps({"start": 0.0, "end": 2.0, "text": "test"}) + "\n")
        with open(checkpoint_file, "a", encoding="utf-8") as f:
            f.write(" " * 1500)
            
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_proc.returncode = 0
        mock_proc.stdout = [json.dumps({"status": "completed"})]
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = ""
        return mock_proc

    ctx = PipelineContext(video_path=str(video_file))
    with patch("subprocess.Popen", side_effect=side_effect_popen):
        result = await worker.execute(ctx)
        assert result.success is True


@pytest.mark.asyncio
async def test_quality_gate_worker_template_config_import_error():
    """template_config インポートエラー時のフォールバックをカバー (391-392)"""
    worker = QualityGateWorker()
    ctx = PipelineContext(video_path="test.mp4")
    
    sys.modules['template_config'] = None
    mock_quality_gate.run_all_plugins = MagicMock(return_value={
        "total_deductions": 0,
        "feedback": [],
        "category_report": [],
        "category_scores": {}
    })
    
    result = await worker.execute(ctx)
    assert result.success is True


@pytest.mark.asyncio
async def test_render_worker_render_fail_and_no_preview(tmp_path):
    """RenderWorker のレンダリング元なしとレンダリング失敗パスをカバー (464, 476)"""
    worker = RenderWorker()
    outputs_dir = tmp_path / "outputs"
    
    # 1. レンダリング元なし (476行目)
    ctx1 = PipelineContext(video_path="test.mp4")
    ctx1.preview_path = None
    with patch("safe_io.VAULT_OUTPUTS_DIR", outputs_dir):
        result1 = await worker.execute(ctx1)
        assert result1.success is False
        assert "レンダリング元なし" in result1.detail

    # 2. _render_production_quality が False を返して失敗 (464行目)
    ctx2 = PipelineContext(video_path="test.mp4")
    preview_file = tmp_path / "preview.mp4"
    preview_file.write_text("preview data")
    ctx2.preview_path = str(preview_file)
    
    with patch("safe_io.VAULT_OUTPUTS_DIR", outputs_dir), \
         patch.object(worker, "_render_production_quality", return_value=False):
        result2 = await worker.execute(ctx2)
        assert result2.success is False
        assert "本番品質レンダリング失敗" in result2.detail


@pytest.mark.asyncio
async def test_render_worker_loudness_config_error_and_unlink(tmp_path):
    """get_active_benchmarksの例外(531-532)と、ラウドネス失敗時の一時ファイルunlink(558)をカバー"""
    worker = RenderWorker()
    outputs_dir = tmp_path / "outputs"
    preview_file = tmp_path / "preview.mp4"
    preview_file.write_text("preview data")
    
    ctx = PipelineContext(video_path="test.mp4")
    ctx.preview_path = str(preview_file)
    
    # 531-532: get_active_benchmarks が例外を投げるように設定
    mock_template_config.template_config.get_active_benchmarks = MagicMock(side_effect=Exception("Config load failed"))
    
    # 558: ラウドネスフィルタ実行でエラーを返しつつ、一時ファイルが存在する状態を作る
    mock_ffmpeg = MagicMock()
    mock_ffmpeg.is_available.return_value = True
    mock_ffmpeg._get_encode_args.return_value = []
    
    def side_effect_run(cmd, timeout):
        final_path = cmd[-1]
        if "-af" in cmd:
            # 一時ファイルを書き出してからエラーを返す
            Path(final_path).write_text("temp data" * 150)
            return (False, "Loudness filter failed")
        Path(final_path).parent.mkdir(parents=True, exist_ok=True)
        Path(final_path).write_text("encoded data" * 150)
        return (True, "Encode success")
        
    mock_ffmpeg.run_command.side_effect = side_effect_run
    mock_video_editor.video_editor.ffmpeg = mock_ffmpeg
    
    with patch("safe_io.VAULT_OUTPUTS_DIR", outputs_dir):
        result = await worker.execute(ctx)
        assert result.success is True
        # 一時ファイルが正常に削除されていることを確認
        assert not Path(ctx.final_path + ".norm.mp4").exists()


@pytest.mark.asyncio
async def test_pipeline_coordinator_template_restore_success(tmp_path):
    """正常にテンプレートが復元されるケースをカバー (730-739)"""
    mock_template_config.template_config.set_active_template.reset_mock()
    pc = PipelineCoordinator()
    ctx = PipelineContext(video_path="test.mp4")
    ctx.template_id = "vibrant_modern"
    
    for worker in pc.workers:
        worker.execute = AsyncMock(return_value=StageResult(stage_name=worker.name, success=True, detail="ok"))
        worker.verify = MagicMock(return_value=True)

    # template_config.template_config.is_active = False に設定
    mock_template_config.template_config.is_active = False
    
    dummy_templates = {"vibrant_modern": {"theme": "warm"}}
    
    with patch("routers.themes_router.PRODUCTION_TEMPLATES", dummy_templates), \
         patch.object(pc, "_run_retention_analysis", return_value=None), \
         patch.object(pc, "_trigger_dream_learning", return_value=None), \
         patch("shutil.disk_usage", return_value=MagicMock(free=10 * 1024 * 1024 * 1024)):
         
         result = await pc.execute(ctx)
         assert result["status"] == "completed"
         mock_template_config.template_config.set_active_template.assert_called_once_with(
             "vibrant_modern", {"theme": "warm"}, theme_id="warm"
         )


@pytest.mark.asyncio
async def test_pipeline_coordinator_fatal_stage_fail():
    """致命的なステージが失敗して中断されるケースをカバー (769-770)"""
    pc = PipelineCoordinator()
    ctx = PipelineContext(video_path="test.mp4")
    
    # index 0 (文字起こし) を失敗させる
    pc.workers[0].execute = AsyncMock(return_value=StageResult(stage_name="文字起こし", success=False, detail="Transcribe failed"))
    pc.workers[0].verify = MagicMock(return_value=False)
    
    result = await pc.execute(ctx)
    assert result["status"] == "error"
    assert "Transcribe failed" in result["error"]


@pytest.mark.asyncio
async def test_pipeline_coordinator_improvement_fail_and_retention_append(tmp_path):
    """品質改善ループ上限到達(774-776)と、retention_report追加(783)をカバー"""
    pc = PipelineCoordinator()
    ctx = PipelineContext(video_path="test.mp4")
    
    # 全Workerを成功させるが、QualityGateWorkerは失敗させる
    for w in pc.workers:
        if isinstance(w, QualityGateWorker):
            w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=False, detail="Failed quality"))
            w.verify = MagicMock(return_value=False)
        else:
            w.execute = AsyncMock(return_value=StageResult(stage_name=w.name, success=True, detail="ok"))
            w.verify = MagicMock(return_value=True)
            
    # 品質改善ループも失敗させる
    mock_improvement_loop = AsyncMock(return_value=False)
    
    # Retention分析は成功させてStageResultを返すようにする
    mock_report = StageResult(stage_name="Retention分析", success=True, detail="Retention ok")
    
    with patch.object(pc, "_quality_improvement_loop", mock_improvement_loop), \
         patch.object(pc, "_run_retention_analysis", return_value=mock_report), \
         patch.object(pc, "_trigger_dream_learning", return_value=None), \
         patch("shutil.disk_usage", return_value=MagicMock(free=10 * 1024 * 1024 * 1024)):
         
         result = await pc.execute(ctx)
         assert result["status"] == "completed"
         mock_improvement_loop.assert_called_once()
         assert any(r.stage_name == "Retention分析" for r in ctx.stage_results)


@pytest.mark.asyncio
async def test_execute_with_harness_exception_fallback():
    """ハーネス実行中の想定外の例外によるレガシーフォールバック処理をカバー (1186-1188)"""
    pc = PipelineCoordinator()
    ctx = PipelineContext(video_path="test.mp4")
    
    # create_session で例外をスローさせる
    mock_sm_instance.create_session.side_effect = Exception("Harness session init error")
    mock_execute = AsyncMock(return_value={"status": "fallback_legacy"})
    
    with patch.object(pc, "execute", mock_execute):
        result = await pc.execute_with_harness(ctx)
        assert result["status"] == "fallback_legacy"
        mock_execute.assert_called_once_with(ctx)
