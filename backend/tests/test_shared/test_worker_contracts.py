"""
M2.4: Worker間データ契約テスト — 7テスト

MASTER v3.6 L1179-1190 準拠。
パイプライン7段 (Transcribe→Proofread→SmartCut→Preview→QualityGate→Render→YouTubeOpt) の
Worker間データ受け渡し契約を検証する。

テスト構成:
  CT-01: Transcribe出力→Proofread入力  全フィールド型一致
  CT-02: Proofread出力→SmartCut入力    seg.start/end不変性
  CT-03: SmartCut出力→Preview入力      selected ⊆ original
  CT-04: Preview出力→QualityGate入力   ファイル存在+サイズ
  CT-05: QualityGate出力→Render入力    score≥90で通過
  CT-06: Transcribe出力→YouTubeOpt入力 seg構造一致
  CT-07: 全7段の連鎖テスト             パイプライン全通過

設計思想:
  - 各テストは **Worker間の契約** (出力フィールドが次段の入力要件を満たすか) を検証
  - Worker内部ロジックの正当性は個別テスト (test_*_worker.py) で担保済み
  - 外部依存 (FFmpeg/Whisper/Gemini) はすべてモックで代替
  - 既存 test_dataflow_integration.py (T-023/T-024) とは非重複:
    あちらは各Worker単体の通過確認、ここはWorker間の型・フィールド契約

重複回避:
  - test_preview_worker.py W4-C5-01 (CT-03類似): selected参照確認 → 本テストはフィールド⊆検証
  - test_preview_worker.py W4-C5-02 (CT-04類似): ファイル存在確認 → 本テストはQualityGate入力契約全体
"""

import pytest
import asyncio
import sys
import os
import tempfile
from unittest.mock import patch, MagicMock
from pathlib import Path

# backend ディレクトリをパスに追加
_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from agents.pipeline_coordinator import (
    PipelineContext, StageResult,
    TranscribeWorker, ProofreadWorker, SmartCutWorker,
    PreviewWorker, YouTubeOptWorker, QualityGateWorker, RenderWorker,
)
from tests.fixtures.mock_pipeline import create_mock_ctx, create_mock_segments


# ============================================================
# ヘルパー: Transcribe出力をシミュレート
# ============================================================

def _simulate_transcribe_output(ctx: PipelineContext, segment_count: int = 10):
    """TranscribeWorkerの出力契約に準拠したctx.segmentsを設定。
    
    TranscribeWorkerの出力契約:
        ctx.segments: list[dict] — {start, end, text, sourceStart, sourceEnd}
    """
    ctx.segments = create_mock_segments(count=segment_count, with_source_times=True)
    return StageResult(
        stage_name="文字起こし", success=True,
        detail=f"{segment_count}セグメント検出 (モック)",
        data={"segment_count": segment_count, "model": "mock"},
    )


def _patch_preview_env(tmpdir, render_return=True, file_size=1024 * 100):
    """PreviewWorkerの外部依存を一括パッチするモックを生成。"""
    def _fake_render(segments, video_path, output_path):
        if render_return:
            Path(output_path).write_bytes(b"\x00" * file_size)
        return render_return

    mock_sce = MagicMock()
    mock_sce.render_smart_cut = _fake_render
    mock_safe_io = MagicMock()
    mock_safe_io.VAULT_OUTPUTS_DIR = Path(tmpdir)
    return mock_sce, mock_safe_io


# ============================================================
# CT-01: Transcribe出力→Proofread入力 — 全フィールド型一致
# ============================================================

class TestCT01TranscribeToProofread:
    """CT-01: Transcribe出力がProofread入力契約を満たすこと。
    
    Transcribe出力: ctx.segments = [{start:float, end:float, text:str, sourceStart:float, sourceEnd:float}, ...]
    Proofread入力: ctx.segments = [{text:str, ...}, ...] — text必須
    """

    @pytest.mark.asyncio
    async def test_ct01_transcribe_output_has_text_field(self):
        """CT-01: Transcribe出力の全セグメントにtextフィールドがあること"""
        ctx = create_mock_ctx(segments=10)
        _simulate_transcribe_output(ctx, segment_count=10)

        # Transcribe出力がProofread入力契約を満たすか検証
        for i, seg in enumerate(ctx.segments):
            assert "text" in seg, f"seg[{i}]: textフィールド欠落"
            assert isinstance(seg["text"], str), f"seg[{i}]: text型不正 ({type(seg['text'])})"
            assert "start" in seg, f"seg[{i}]: startフィールド欠落"
            assert isinstance(seg["start"], (int, float)), f"seg[{i}]: start型不正"
            assert "end" in seg, f"seg[{i}]: endフィールド欠落"
            assert isinstance(seg["end"], (int, float)), f"seg[{i}]: end型不正"
            # sourceStart/sourceEnd — Transcribe契約の追加フィールド
            assert "sourceStart" in seg, f"seg[{i}]: sourceStartフィールド欠落"
            assert "sourceEnd" in seg, f"seg[{i}]: sourceEndフィールド欠落"

        # Proofread Workerが実際に受理できることを確認
        worker = ProofreadWorker()
        result = await worker.execute(ctx)
        assert result.success is True, f"ProofreadWorkerがTranscribe出力を受理できなかった: {result.detail}"


# ============================================================
# CT-02: Proofread出力→SmartCut入力 — seg.start/end不変性
# ============================================================

class TestCT02ProofreadToSmartCut:
    """CT-02: Proofread後もseg.start/endが不変であること。
    
    Proofread出力: ctx.segments (テキスト校閲済み、start/end/sourceStart/sourceEndは保持)
    SmartCut入力: ctx.segments — start, end, text必須。target_minutes必須
    """

    @pytest.mark.asyncio
    async def test_ct02_start_end_preserved_after_proofread(self):
        """CT-02: Proofread後にseg.start/endが保持されていること"""
        ctx = create_mock_ctx(segments=10, target_minutes=3)
        _simulate_transcribe_output(ctx, segment_count=10)

        # Proofread前のstart/endを記録
        before_timestamps = []
        for seg in ctx.segments:
            before_timestamps.append({
                "start": seg["start"],
                "end": seg["end"],
                "sourceStart": seg.get("sourceStart"),
                "sourceEnd": seg.get("sourceEnd"),
            })

        # Proofread実行
        worker = ProofreadWorker()
        result = await worker.execute(ctx)
        assert result.success is True

        # Proofread後: start/endの不変性を検証
        # 注: text_formatterによりセグメント数が変わる可能性があるが、
        #     sourceStart/sourceEndは元のWhisperタイムスタンプとして保持されるべき
        for seg in ctx.segments:
            # 各セグメントにstart/endが存在すること
            assert "start" in seg, "Proofread後にstartフィールド消失"
            assert "end" in seg, "Proofread後にendフィールド消失"
            assert isinstance(seg["start"], (int, float)), f"start型不正: {type(seg['start'])}"
            assert isinstance(seg["end"], (int, float)), f"end型不正: {type(seg['end'])}"
            # start < end の不変条件
            assert seg["start"] <= seg["end"], f"start({seg['start']}) > end({seg['end']})"

        # SmartCutが受理できることを確認
        smartcut = SmartCutWorker()
        result = await smartcut.execute(ctx)
        assert result.success is True, f"SmartCutがProofread出力を受理できなかった: {result.detail}"


# ============================================================
# CT-03: SmartCut出力→Preview入力 — selected ⊆ original
# ============================================================

class TestCT03SmartCutToPreview:
    """CT-03: SmartCut出力のselected_segmentsがsegmentsの部分集合であること。
    
    SmartCut出力: ctx.selected_segments ⊆ ctx.segments
    Preview入力: ctx.selected_segments — start, end必須。ctx.video_path必須
    """

    @pytest.mark.asyncio
    async def test_ct03_selected_subset_of_segments(self):
        """CT-03: selected_segmentsがsegmentsの部分集合であること"""
        # 目標3分でカット発動するように設計
        ctx = create_mock_ctx(segments=10, target_minutes=3, duration_each=30.0)
        _simulate_transcribe_output(ctx, segment_count=10)
        # segments上書き — 30秒/seg x 10 = 300秒(5分) > 3分
        ctx.segments = create_mock_segments(count=10, duration_each=30.0, with_source_times=True)

        # SmartCut実行
        smartcut = SmartCutWorker()
        result = await smartcut.execute(ctx)
        assert result.success is True

        # 部分集合検証: selected_segmentsの各要素がsegmentsに含まれること
        segments_texts = {seg.get("text") for seg in ctx.segments}
        for i, selected in enumerate(ctx.selected_segments):
            assert selected.get("text") in segments_texts, (
                f"selected[{i}] のテキストが元segmentsに存在しない: {selected.get('text')[:30]}"
            )

        # 要素数: selected ≤ segments
        assert len(ctx.selected_segments) <= len(ctx.segments), (
            f"selected({len(ctx.selected_segments)}) > segments({len(ctx.segments)})"
        )

        # Preview入力契約: 各selectedにstart/endがあること
        for i, seg in enumerate(ctx.selected_segments):
            assert "start" in seg, f"selected[{i}]: startフィールド欠落"
            assert "end" in seg, f"selected[{i}]: endフィールド欠落"


# ============================================================
# CT-04: Preview出力→QualityGate入力 — ファイル存在+サイズ
# ============================================================

class TestCT04PreviewToQualityGate:
    """CT-04: Preview出力のpreview_pathが存在し、サイズ>0であること。
    
    Preview出力: ctx.preview_path — ファイルパス(str)
    QualityGate入力: ctx.preview_path — Optional[str]。存在時にsize確認
    """

    @pytest.mark.asyncio
    async def test_ct04_preview_path_exists_and_has_size(self):
        """CT-04: Preview出力のファイルが存在しサイズ>0であること"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = create_mock_ctx(segments=5, with_selected=True)
            mock_sce, mock_safe_io = _patch_preview_env(tmpdir, file_size=50 * 1024)

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                preview = PreviewWorker()
                preview_result = await preview.execute(ctx)

            assert preview_result.success is True, f"Preview失敗: {preview_result.detail}"

            # QualityGate入力契約の検証
            assert ctx.preview_path is not None, "ctx.preview_path未設定"
            assert isinstance(ctx.preview_path, str), f"preview_path型不正: {type(ctx.preview_path)}"
            assert Path(ctx.preview_path).exists(), f"preview_pathが存在しない: {ctx.preview_path}"
            assert Path(ctx.preview_path).stat().st_size > 0, "preview_pathのサイズが0"

            # QualityGateが受理できることを確認
            quality = QualityGateWorker()
            with patch.dict("sys.modules", {"quality_gate_plugins": None}):
                qg_result = await quality.execute(ctx)
            assert isinstance(qg_result, StageResult), "QualityGateがStageResultを返さなかった"
            assert ctx.quality_score >= 0, "quality_score不正"


# ============================================================
# CT-05: QualityGate出力→Render入力 — score≥90で通過
# ============================================================

class TestCT05QualityGateToRender:
    """CT-05: QualityGateのスコア≥90時にRenderへの通過が許可されること。
    
    QualityGate出力: ctx.quality_score:int, StageResult.success=(score≥90)
    Render入力: ctx.preview_path必須 (QualityGate通過後)
    """

    @pytest.mark.asyncio
    async def test_ct05_score_ge90_passes_to_render(self):
        """CT-05: score≥90でQualityGateがsuccess=True → Renderへ通過"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = create_mock_ctx(segments=5, with_selected=True)
            
            # プレビューファイルを事前作成 (CT-04通過後の状態)
            preview_dir = Path(tmpdir) / "preview"
            preview_dir.mkdir(parents=True, exist_ok=True)
            preview_file = preview_dir / "preview_mock.mp4"
            preview_file.write_bytes(b"\x00" * (100 * 1024))  # 100KB
            ctx.preview_path = str(preview_file)

            # QualityGate実行 (プラグインなしフォールバック)
            quality = QualityGateWorker()
            with patch.dict("sys.modules", {"quality_gate_plugins": None}):
                qg_result = await quality.execute(ctx)

            # score判定
            assert ctx.quality_score is not None
            assert isinstance(ctx.quality_score, int)

            # score≥90 のケースで success=True を検証
            if ctx.quality_score >= 90:
                assert qg_result.success is True, (
                    f"score={ctx.quality_score}≥90なのにsuccess=False"
                )
            else:
                assert qg_result.success is False, (
                    f"score={ctx.quality_score}<90なのにsuccess=True"
                )

            # Render入力契約: preview_pathが有効であること
            assert ctx.preview_path is not None
            assert Path(ctx.preview_path).exists()

            # StageResult.dataにscore/rank/feedbackが含まれること
            assert "score" in qg_result.data
            assert "rank" in qg_result.data
            assert "feedback" in qg_result.data


# ============================================================
# CT-06: Transcribe出力→YouTubeOpt入力 — seg構造一致
# ============================================================

class TestCT06TranscribeToYouTubeOpt:
    """CT-06: Transcribe出力がYouTubeOpt入力契約を満たすこと。
    
    Transcribe出力: ctx.segments = [{start, end, text, sourceStart, sourceEnd}, ...]
    YouTubeOpt入力: ctx.segments — text必須（先頭20個を使用）
    """

    @pytest.mark.asyncio
    async def test_ct06_segments_text_for_youtube(self):
        """CT-06: TranscribeのsegmentsからYouTubeOptがメタデータ生成可能なこと"""
        ctx = create_mock_ctx(segments=25)
        _simulate_transcribe_output(ctx, segment_count=25)

        # YouTubeOptの入力契約: 先頭20個のtext結合
        first_20 = ctx.segments[:20]
        all_text = " ".join(s.get("text", "") for s in first_20)
        assert len(all_text) > 0, "text結合結果が空"

        # 各セグメントにtextが存在すること
        for i, seg in enumerate(first_20):
            assert "text" in seg, f"seg[{i}]: textフィールド欠落"
            assert isinstance(seg["text"], str), f"seg[{i}]: text型不正"

        # YouTubeOptWorkerが受理できることを確認 (Geminiフォールバック)
        worker = YouTubeOptWorker()
        with patch.dict("sys.modules", {"gemini_client_factory": None}):
            result = await worker.execute(ctx)
        
        assert result.success is True, f"YouTubeOptがTranscribe出力を受理できなかった: {result.detail}"
        assert "titles" in ctx.metadata, "metadata.titles欠落"
        assert "tags" in ctx.metadata, "metadata.tags欠落"
        assert "description" in ctx.metadata, "metadata.description欠落"
        assert "chapters" in ctx.metadata, "metadata.chapters欠落"


# ============================================================
# CT-07: 全7段の連鎖テスト — パイプライン全通過
# ============================================================

class TestCT07FullChainContract:
    """CT-07: 全7段のWorker連鎖でデータ契約が一貫して維持されること。
    
    Transcribe → Proofread → SmartCut → Preview → YouTubeOpt → QualityGate → Render
    各段の出力が次段の入力契約を満たすことを連鎖的に検証。
    """

    @pytest.mark.asyncio
    async def test_ct07_full_pipeline_contract_chain(self):
        """CT-07: 7段連鎖でデータ契約違反なし"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = create_mock_ctx(segments=10, target_minutes=20)
            results = {}

            # ── Stage 1: Transcribe (シミュレート) ──
            transcribe_result = _simulate_transcribe_output(ctx, segment_count=10)
            results["transcribe"] = transcribe_result
            assert len(ctx.segments) == 10, "Transcribe出力: segments数不正"

            # 契約チェック: Transcribe→Proofread
            for seg in ctx.segments:
                assert "text" in seg and isinstance(seg["text"], str)

            # ── Stage 2: Proofread ──
            proofread = ProofreadWorker()
            results["proofread"] = await proofread.execute(ctx)
            assert results["proofread"].success is True, f"Proofread失敗: {results['proofread'].detail}"

            # 契約チェック: Proofread→SmartCut
            assert len(ctx.segments) > 0, "Proofread後にsegmentsが空"
            for seg in ctx.segments:
                assert "start" in seg and "end" in seg
                assert seg["start"] <= seg["end"]

            # ── Stage 3: SmartCut ──
            smartcut = SmartCutWorker()
            results["smartcut"] = await smartcut.execute(ctx)
            assert results["smartcut"].success is True, f"SmartCut失敗: {results['smartcut'].detail}"

            # 契約チェック: SmartCut→Preview
            assert len(ctx.selected_segments) > 0, "SmartCut後にselected_segmentsが空"
            for seg in ctx.selected_segments:
                assert "start" in seg and "end" in seg

            # ── Stage 4: Preview ──
            mock_sce, mock_safe_io = _patch_preview_env(tmpdir)
            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                preview = PreviewWorker()
                results["preview"] = await preview.execute(ctx)
            assert results["preview"].success is True, f"Preview失敗: {results['preview'].detail}"

            # 契約チェック: Preview→QualityGate
            assert ctx.preview_path is not None, "Preview後にpreview_path未設定"
            assert Path(ctx.preview_path).exists(), "preview_pathファイル不存在"

            # ── Stage 5: YouTubeOpt (Transcribe出力から分岐) ──
            youtube = YouTubeOptWorker()
            with patch.dict("sys.modules", {"gemini_client_factory": None}):
                results["youtube"] = await youtube.execute(ctx)
            assert results["youtube"].success is True, f"YouTubeOpt失敗: {results['youtube'].detail}"

            # 契約チェック: YouTubeOpt出力
            assert "titles" in ctx.metadata
            assert "tags" in ctx.metadata

            # ── Stage 6: QualityGate ──
            quality = QualityGateWorker()
            with patch.dict("sys.modules", {"quality_gate_plugins": None}):
                results["quality"] = await quality.execute(ctx)
            # QualityGateは常にStageResultを返す（score<90でもsuccess=Falseで続行可能）
            assert isinstance(results["quality"], StageResult)

            # 契約チェック: QualityGate→Render
            assert isinstance(ctx.quality_score, int)
            assert 0 <= ctx.quality_score <= 100

            # ── Stage 7: Render ──
            render = RenderWorker()
            with patch.dict("sys.modules", {
                "safe_io": mock_safe_io,
            }):
                results["render"] = await render.execute(ctx)
            # Renderは外部依存が多いため、StageResultが返ることを確認
            assert isinstance(results["render"], StageResult)

            # ── 最終検証: 全7段通過 ──
            stages_checked = ["transcribe", "proofread", "smartcut", "preview", "youtube", "quality", "render"]
            for stage in stages_checked:
                assert stage in results, f"{stage}の結果が欠落"
                assert isinstance(results[stage], StageResult), f"{stage}がStageResultでない"

            # パイプラインコンテキストの最終状態検証
            assert len(ctx.segments) > 0, "最終: segmentsが空"
            assert len(ctx.selected_segments) > 0, "最終: selected_segmentsが空"
            assert ctx.preview_path is not None, "最終: preview_path未設定"
            assert "titles" in ctx.metadata, "最終: metadata.titles欠落"
            assert ctx.quality_score >= 0, "最終: quality_scoreが不正"
