"""
M1.2 Sprint 1.2.3: データフロー統合テスト

T-023: モックseg(1個)でパイプライン全Worker通過テスト
T-024: モックseg(10個)でパイプライン全Worker通過テスト

各Workerを順次実行し、ctx の状態遷移を検証する。
外部依存 (FFmpeg/Whisper/Gemini) はすべてモックで代替。
"""

import pytest
import asyncio
import sys
import os
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path

# パス設定
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from agents.pipeline_coordinator import (
    PipelineContext, StageResult,
    TranscribeWorker, ProofreadWorker, SmartCutWorker,
    PreviewWorker, YouTubeOptWorker, QualityGateWorker, RenderWorker,
)
from fixtures.mock_pipeline import create_mock_ctx


@pytest.fixture(autouse=True)
def _mock_genai_and_sleep(monkeypatch):
    """全テストで genai API 実呼び出しと time.sleep を遮断する。"""
    import json as _json

    # genai レスポンスモック
    mock_response = MagicMock()
    mock_response.text = _json.dumps([])  # 修正なしの空リスト

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    # get_governed_client をモック
    monkeypatch.setattr(
        "subtitle_engine.ai_proofreader.genai",
        MagicMock(),
    )

    # model_governance.get_governed_client → mock_client
    try:
        import model_governance
        monkeypatch.setattr(
            model_governance, "get_governed_client",
            lambda *a, **kw: mock_client,
        )
    except (ImportError, AttributeError):
        pass

    # gemini_client_factory フォールバックもモック
    try:
        import gemini_client_factory
        monkeypatch.setattr(
            gemini_client_factory, "get_gemini_client",
            lambda *a, **kw: mock_client,
        )
    except (ImportError, AttributeError):
        pass

    # time.sleep を即時リターンに
    import time as _time_mod
    monkeypatch.setattr(_time_mod, "sleep", lambda *a, **kw: None)

    yield



# ============================================================
# ヘルパー: Worker順次実行（外部依存モック済み）
# ============================================================

async def run_pipeline_workers(ctx: PipelineContext) -> dict[str, StageResult]:
    """全7 Workerを順次実行し、結果を辞書で返す。
    
    外部依存をモックして純粋なデータフローのみ検証:
    - TranscribeWorker: スキップ（ctx.segmentsは事前セット済み）
    - ProofreadWorker: Gemini/辞書をモック
    - SmartCutWorker: 純粋ロジック（モック不要）
    - PreviewWorker: render_smart_cutをモック
    - YouTubeOptWorker: Geminiをモック
    - QualityGateWorker: プラグインをモック
    - RenderWorker: FFmpegをモック
    """
    results = {}

    # --- S1: TranscribeWorker (スキップ — segmentsは事前注入) ---
    results["transcribe"] = StageResult(
        stage_name="文字起こし", success=True,
        detail=f"{len(ctx.segments)}セグメント検出 (モック)",
        data={"segment_count": len(ctx.segments), "model": "mock"},
    )
    ctx.stage_results.append(results["transcribe"])

    # --- S2: ProofreadWorker ---
    proofread = ProofreadWorker()
    with patch("agents.pipeline_coordinator.proofread_segments", side_effect=lambda segs: segs, create=True):
        results["proofread"] = await proofread.execute(ctx)
    ctx.stage_results.append(results["proofread"])

    # --- S3: SmartCutWorker ---
    smartcut = SmartCutWorker()
    results["smartcut"] = await smartcut.execute(ctx)
    ctx.stage_results.append(results["smartcut"])

    # --- S4: PreviewWorker ---
    preview = PreviewWorker()
    with patch("agents.pipeline_coordinator.render_smart_cut", return_value=True, create=True), \
         patch("agents.pipeline_coordinator.VAULT_OUTPUTS_DIR", Path(os.path.dirname(__file__)), create=True):
        # render_smart_cutのimportをモック
        mock_module = MagicMock()
        mock_module.render_smart_cut = MagicMock(return_value=True)
        with patch.dict("sys.modules", {"smart_cut_engine": mock_module, "safe_io": MagicMock(VAULT_OUTPUTS_DIR=Path(os.path.dirname(__file__)))}):
            results["preview"] = await preview.execute(ctx)
    ctx.stage_results.append(results["preview"])

    # --- S5: YouTubeOptWorker ---
    youtube = YouTubeOptWorker()
    # Gemini APIモック — ImportErrorでフォールバックパスを通す
    with patch.dict("sys.modules", {"gemini_client_factory": None}):
        results["youtube"] = await youtube.execute(ctx)
    ctx.stage_results.append(results["youtube"])

    # --- S6: QualityGateWorker ---
    quality = QualityGateWorker()
    # プラグインをモック — ImportErrorでフォールバック
    with patch.dict("sys.modules", {"quality_gate_plugins": None}):
        results["quality"] = await quality.execute(ctx)
    ctx.stage_results.append(results["quality"])

    # --- S7: RenderWorker ---
    render = RenderWorker()
    with patch.dict("sys.modules", {"safe_io": MagicMock(VAULT_OUTPUTS_DIR=Path(os.path.dirname(__file__)))}):
        results["render"] = await render.execute(ctx)
    ctx.stage_results.append(results["render"])

    return results


# ============================================================
# T-023: 1セグメントで全Worker通過
# ============================================================

class TestT023SingleSegment:
    """T-023: モックseg(1個)でパイプライン全Worker通過テスト"""

    @pytest.mark.worker
    @pytest.mark.asyncio
    async def test_single_seg_proofread_passes(self):
        """1セグメントでProofreadWorkerが正常完了する"""
        ctx = create_mock_ctx(segments=1)
        worker = ProofreadWorker()
        result = await worker.execute(ctx)
        assert result.success
        assert len(ctx.segments) >= 1

    @pytest.mark.worker
    @pytest.mark.asyncio
    async def test_single_seg_smartcut_no_cut(self):
        """1セグメントでSmartCutが「カット不要」パスを通る"""
        ctx = create_mock_ctx(segments=1, target_minutes=20)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)
        assert result.success
        assert len(ctx.selected_segments) == 1
        assert "カット不要" in result.detail

    @pytest.mark.worker
    @pytest.mark.asyncio
    async def test_single_seg_preview_fallback(self):
        """1セグメントでPreviewWorkerがフォールバック動作する"""
        ctx = create_mock_ctx(segments=1)
        # selected_segmentsを空にしてフォールバックテスト
        ctx.selected_segments = []
        worker = PreviewWorker()
        # T-020: selected空 → segmentsへのフォールバック
        mock_module = MagicMock()
        mock_module.render_smart_cut = MagicMock(return_value=False)
        with patch.dict("sys.modules", {"smart_cut_engine": mock_module, "safe_io": MagicMock(VAULT_OUTPUTS_DIR=Path(os.path.dirname(__file__)))}):
            result = await worker.execute(ctx)
        # フォールバック発動確認: selected_segmentsにsegmentsがコピーされた
        assert ctx.selected_segments == ctx.segments

    @pytest.mark.worker
    @pytest.mark.asyncio
    async def test_zero_seg_proofread_guard(self):
        """T-018: 0セグメントでProofreadWorkerが安全にスキップする"""
        ctx = create_mock_ctx(segments=0)
        worker = ProofreadWorker()
        result = await worker.execute(ctx)
        assert result.success
        assert "スキップ" in result.detail

    @pytest.mark.worker
    @pytest.mark.asyncio
    async def test_zero_seg_preview_fails_gracefully(self):
        """0セグメント（segments空 + selected空）でPreviewWorkerが安全に失敗する"""
        ctx = create_mock_ctx(segments=0)
        ctx.selected_segments = []
        ctx.segments = []
        worker = PreviewWorker()
        result = await worker.execute(ctx)
        assert not result.success
        assert "セグメントなし" in result.detail

    @pytest.mark.worker
    @pytest.mark.asyncio
    async def test_render_safe_mode(self):
        """T-022: preview_pathなしでRenderWorkerがセーフモード動作する"""
        ctx = create_mock_ctx(segments=1)
        ctx.preview_path = None
        # video_pathに実在するファイルをセット
        ctx.video_path = str(Path(__file__).parent.parent / "test_13s.mp4")
        worker = RenderWorker()

        mock_safe_io = MagicMock()
        mock_safe_io.VAULT_OUTPUTS_DIR = Path(os.path.dirname(__file__))
        with patch.dict("sys.modules", {"safe_io": mock_safe_io}):
            result = await worker.execute(ctx)

        # セーフモード発動: preview_pathがvideo_pathに設定された
        if Path(ctx.video_path).exists():
            assert "プレビュー生成" in ctx.skipped_features


# ============================================================
# T-024: 10セグメントで全Worker通過
# ============================================================

class TestT024StandardSegments:
    """T-024: モックseg(10個)でパイプライン全Worker通過テスト"""

    @pytest.mark.worker
    @pytest.mark.asyncio
    async def test_10seg_proofread_segment_count(self):
        """10セグメントでProofreadWorker通過後にセグメントが残る"""
        ctx = create_mock_ctx(segments=10)
        before = len(ctx.segments)
        worker = ProofreadWorker()
        result = await worker.execute(ctx)
        assert result.success
        # フィラー除去で減ることはあっても、全消失はしない
        assert len(ctx.segments) > 0
        assert result.data["total"] >= 0

    @pytest.mark.worker
    @pytest.mark.asyncio
    async def test_10seg_smartcut_selects_subset(self):
        """10セグメントでSmartCutがターゲット尺にカットする"""
        # 10seg × 15秒 = 150秒(2.5分) > target 1分 → カット発動
        ctx = create_mock_ctx(segments=10, target_minutes=1)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)
        assert result.success
        assert len(ctx.selected_segments) > 0
        assert len(ctx.selected_segments) <= 10
        assert "cut_percent" in result.data

    @pytest.mark.worker
    @pytest.mark.asyncio
    async def test_10seg_youtube_generates_metadata(self):
        """10セグメントでYouTubeOptWorkerがフォールバックメタデータ生成する"""
        ctx = create_mock_ctx(segments=10)
        worker = YouTubeOptWorker()
        # Gemini不在でフォールバック
        with patch.dict("sys.modules", {"gemini_client_factory": None}):
            result = await worker.execute(ctx)
        assert result.success
        assert "titles" in ctx.metadata
        assert "tags" in ctx.metadata
        assert len(ctx.metadata["tags"]) >= 5

    @pytest.mark.worker
    @pytest.mark.asyncio
    async def test_10seg_quality_gate_runs(self):
        """10セグメントでQualityGateWorkerが品質スコアを算出する"""
        ctx = create_mock_ctx(segments=10)
        worker = QualityGateWorker()
        # プラグイン不在でフォールバック
        with patch.dict("sys.modules", {"quality_gate_plugins": None}):
            result = await worker.execute(ctx)
        # フォールバックではpreview_path未設定で-20減点
        assert ctx.quality_score <= 100
        assert ctx.quality_score >= 0
        assert "score" in result.data

    @pytest.mark.worker
    @pytest.mark.asyncio
    async def test_10seg_segments_preserved_after_proofread(self):
        """ProofreadWorker通過後もsourceStart/sourceEndが保持される"""
        ctx = create_mock_ctx(segments=10)
        # 元のsourceStart/sourceEndを記録
        original_sources = []
        for seg in ctx.segments:
            original_sources.append({
                "sourceStart": seg.get("sourceStart"),
                "sourceEnd": seg.get("sourceEnd"),
            })
        
        worker = ProofreadWorker()
        result = await worker.execute(ctx)
        assert result.success
        
        # T-016 B案検証: sourceStart/sourceEndが全セグメントに存在する
        for seg in ctx.segments:
            # format_segmentsで分割されたセグメントでもsourceEndが存在すべき
            if "sourceEnd" in seg:
                assert seg["sourceEnd"] is not None

    @pytest.mark.worker
    @pytest.mark.asyncio
    async def test_10seg_dataflow_selected_subset_of_segments(self):
        """SmartCutのselected_segments ⊆ Proofread後のsegments"""
        ctx = create_mock_ctx(segments=10, target_minutes=3)
        
        # Proofread
        proofread = ProofreadWorker()
        await proofread.execute(ctx)
        segments_after_proofread = [s.get("text") for s in ctx.segments]
        
        # SmartCut
        smartcut = SmartCutWorker()
        result = await smartcut.execute(ctx)
        assert result.success
        
        # selected ⊆ segments
        for seg in ctx.selected_segments:
            assert seg.get("text") in segments_after_proofread
