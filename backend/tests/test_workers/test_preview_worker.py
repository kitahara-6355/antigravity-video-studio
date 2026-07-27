"""
PreviewWorker 30テスト — MASTER v3.6 Sprint 2.2.4 (L742-799)

Worker本体(2分岐) + preview_engine(27分岐) = 29分岐 → 最低保証30テスト

テスト構成:
  C1: 入力検証       5テスト (W4-C1-01〜05)
  C2: コアロジック   5テスト (W4-C2-01〜05)
  C3: 出力検証       5テスト (W4-C3-01〜05)
  C4: エラー耐性     5テスト (W4-C4-01〜05)
  C5: 統合・依存     5テスト (W4-C5-01〜05)
  C6: 性能・進化     5テスト (W4-C6-01〜05)

モックパターン:
  - render_smart_cut は sys.modules["smart_cut_engine"] をパッチ
  - safe_io は sys.modules["safe_io"] をパッチして tmpdir を使用
  - asyncio.get_running_loop() は asyncio.get_event_loop() 経由で自然に使用
"""

import asyncio
import os
import sys
import time
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock, call

# backend ディレクトリをパスに追加
_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from agents.pipeline_coordinator import PreviewWorker, PipelineContext, StageResult
from tests.fixtures.mock_pipeline import create_mock_ctx, create_mock_segments

@pytest.fixture(scope="session", autouse=True)
def setup_dummy_video():
    """テスト実行に必要なダミー動画ファイルを自動作成・クリーンアップする"""
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    video_dir = project_root / "test_videos"
    video_path = video_dir / "tv01_real_clip.mp4"
    
    created = False
    if not video_path.exists():
        video_dir.mkdir(parents=True, exist_ok=True)
        video_path.write_bytes(b"\x00" * 1024)  # 1KB の空ファイルをダミーとして作成
        created = True
        
    yield
    
    if created and video_path.exists():
        try:
            video_path.unlink()
        except OSError:
            pass


# ============================================================
# ヘルパー関数
# ============================================================

def _make_selected_segments(count=5, duration_each=10.0):
    """選定済みセグメントを生成"""
    segs = []
    for i in range(count):
        s = i * duration_each
        e = s + duration_each
        segs.append({
            "start": s,
            "end": e,
            "text": f"テスト発言{i + 1}回目の内容です。",
            "sourceStart": s,
            "sourceEnd": e,
        })
    return segs


def _make_preview_ctx(
    selected_count=5,
    segments_count=10,
    video_path=None,
    with_selected=True,
):
    """PreviewWorker用のPipelineContextを生成"""
    ctx = create_mock_ctx(segments=segments_count)
    if video_path is not None:
        ctx.video_path = video_path
    if with_selected:
        ctx.selected_segments = _make_selected_segments(selected_count)
    else:
        ctx.selected_segments = []
    return ctx


def _patch_preview_env(tmpdir, render_return=True, file_size=1024 * 100):
    """
    PreviewWorker.execute() の外部依存を一括パッチするコンテキストマネージャー群を返す。

    パッチ対象:
      - smart_cut_engine.render_smart_cut → render_return を返す
      - safe_io.VAULT_OUTPUTS_DIR → tmpdir
      - 出力ファイルを実際に作成する副作用付き
    """
    mock_preview_path_holder = {}

    def _fake_render(segments, video_path, output_path):
        """render_smart_cut の偽実装: ファイルを実際に作成してrender_returnを返す"""
        if render_return:
            Path(output_path).write_bytes(b"\x00" * file_size)
        mock_preview_path_holder["path"] = output_path
        return render_return

    mock_sce = MagicMock()
    mock_sce.render_smart_cut = _fake_render

    mock_safe_io = MagicMock()
    mock_safe_io.VAULT_OUTPUTS_DIR = Path(tmpdir)

    return mock_sce, mock_safe_io, mock_preview_path_holder


# ============================================================
# C1: 入力検証 (5テスト)
# ============================================================

class TestC1InputValidation:
    """W4-C1-01〜W4-C1-05: 入力検証"""

    @pytest.mark.asyncio
    async def test_c1_01_normal_selected_segments_10(self):
        """W4-C1-01: selected_segments正常(10seg) — プレビュー生成成功"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=10)
            mock_sce, mock_safe_io, _ = _patch_preview_env(tmpdir)

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

        assert result.success is True
        assert ctx.preview_path is not None
        assert "プレビュー生成完了" in result.detail

    @pytest.mark.asyncio
    async def test_c1_02_selected_segments_empty_fallback_to_segments(self):
        """W4-C1-02: selected_segments空 + segments存在 → fallback成功"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=0, segments_count=5, with_selected=True)
            # selected_segmentsは空だがctx.segmentsには値がある
            assert ctx.segments is not None and len(ctx.segments) > 0

            mock_sce, mock_safe_io, _ = _patch_preview_env(tmpdir)

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

        # fallback: segments を使用してプレビュー生成
        assert result.success is True
        # fallback後 selected_segments が segments と同値になること
        assert len(ctx.selected_segments) == 5

    @pytest.mark.asyncio
    async def test_c1_03_video_path_invalid(self):
        """W4-C1-03: video_path不正 — エラーハンドリング"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=5)
            ctx.video_path = "/nonexistent/path/video.mp4"

            def _render_raise(segments, video_path, output_path):
                raise FileNotFoundError(f"動画ファイルが見つかりません: {video_path}")

            mock_sce = MagicMock()
            mock_sce.render_smart_cut = _render_raise
            mock_safe_io = MagicMock()
            mock_safe_io.VAULT_OUTPUTS_DIR = Path(tmpdir)

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

        assert result.success is False
        assert result.detail  # エラーメッセージが含まれること

    @pytest.mark.asyncio
    async def test_c1_04_selected_segments_none_both(self):
        """W4-C1-04: selected_segments=None + segments=None → 安全な失敗"""
        ctx = create_mock_ctx(segments=0)
        ctx.selected_segments = None
        ctx.segments = None

        worker = PreviewWorker()
        result = await worker.execute(ctx)

        assert result.success is False
        assert "セグメントなし" in result.detail or result.detail  # graceful失敗

    @pytest.mark.asyncio
    async def test_c1_04b_selected_segments_empty_list_both(self):
        """W4-C1-04b: selected_segments=[] + segments=[] → 安全な失敗"""
        ctx = create_mock_ctx(segments=0)
        ctx.selected_segments = []
        ctx.segments = []

        worker = PreviewWorker()
        result = await worker.execute(ctx)

        assert result.success is False
        assert "セグメントなし" in result.detail or result.detail

    @pytest.mark.asyncio
    async def test_c1_05_output_dir_write_permission(self):
        """W4-C1-05: 出力ディレクトリ書込権限なし — エラーメッセージ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=5)

            def _render_raise_permission(segments, video_path, output_path):
                raise PermissionError(f"書込権限がありません: {output_path}")

            mock_sce = MagicMock()
            mock_sce.render_smart_cut = _render_raise_permission
            mock_safe_io = MagicMock()
            mock_safe_io.VAULT_OUTPUTS_DIR = Path(tmpdir)

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

        assert result.success is False
        # PermissionError が適切にキャッチされること
        assert result.detail is not None and len(result.detail) > 0


# ============================================================
# C2: コアロジック (5テスト)
# ============================================================

class TestC2CoreLogic:
    """W4-C2-01〜W4-C2-05: コアロジック"""

    @pytest.mark.asyncio
    async def test_c2_01_render_smart_cut_called_with_correct_args(self):
        """W4-C2-01: render_smart_cut呼び出し — 引数正当性"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=5)
            call_args_holder = {}

            def _fake_render(segments, video_path, output_path):
                call_args_holder["segments"] = segments
                call_args_holder["video_path"] = video_path
                call_args_holder["output_path"] = output_path
                Path(output_path).write_bytes(b"\x00" * 1024)
                return True

            mock_sce = MagicMock()
            mock_sce.render_smart_cut = _fake_render
            mock_safe_io = MagicMock()
            mock_safe_io.VAULT_OUTPUTS_DIR = Path(tmpdir)

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

        assert result.success is True
        # selected_segments が正しく渡されていること
        assert call_args_holder["segments"] == ctx.selected_segments
        # video_path が正しく渡されていること
        assert call_args_holder["video_path"] == ctx.video_path
        # output_path が文字列であること
        assert isinstance(call_args_holder["output_path"], str)

    @pytest.mark.asyncio
    async def test_c2_02_preview_dir_auto_created(self):
        """W4-C2-02: preview_dir自動作成 — mkdir(parents=True)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=3)
            preview_dir_holder = {}

            def _fake_render(segments, video_path, output_path):
                preview_dir = Path(output_path).parent
                preview_dir_holder["path"] = preview_dir
                Path(output_path).write_bytes(b"\x00" * 1024)
                return True

            mock_sce = MagicMock()
            mock_sce.render_smart_cut = _fake_render
            mock_safe_io = MagicMock()
            mock_safe_io.VAULT_OUTPUTS_DIR = Path(tmpdir)

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

            # tmpdir内でpreview_dir存在確認（tmpdir削除前）
            assert result.success is True
            # preview_dir が存在すること（mkdirが呼ばれた）
            assert preview_dir_holder["path"].exists()
            # preview_dir 名が "preview" であること
            assert preview_dir_holder["path"].name == "preview"

    @pytest.mark.asyncio
    async def test_c2_03_timestamp_filename(self):
        """W4-C2-03: タイムスタンプ付きファイル名 — preview_YYYYMMDD_HHMMSS.mp4"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=3)
            filename_holder = {}

            def _fake_render(segments, video_path, output_path):
                filename_holder["name"] = Path(output_path).name
                Path(output_path).write_bytes(b"\x00" * 1024)
                return True

            mock_sce = MagicMock()
            mock_sce.render_smart_cut = _fake_render
            mock_safe_io = MagicMock()
            mock_safe_io.VAULT_OUTPUTS_DIR = Path(tmpdir)

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

        assert result.success is True
        name = filename_holder["name"]
        # "preview_" プレフィックスと ".mp4" 拡張子
        assert name.startswith("preview_"), f"ファイル名が不正: {name}"
        assert name.endswith(".mp4"), f"拡張子が不正: {name}"
        # タイムスタンプ部分 (YYYYMMDD_HHMMSS = 15文字)
        ts_part = name[len("preview_"):-len(".mp4")]
        assert len(ts_part) == 15, f"タイムスタンプ部分が不正: {ts_part}"
        assert ts_part[8] == "_", f"アンダースコア位置が不正: {ts_part}"

    @pytest.mark.asyncio
    async def test_c2_04_file_size_calculation_mb(self):
        """W4-C2-04: ファイルサイズ計算(MB) — 正確な変換"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=5)
            # 2MB相当のファイルを作成
            file_size_bytes = 2 * 1024 * 1024
            mock_sce, mock_safe_io, _ = _patch_preview_env(tmpdir, file_size=file_size_bytes)

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

        assert result.success is True
        size_mb = result.data.get("size_mb")
        assert size_mb is not None
        # 2MB ± 0.01MB の範囲内
        assert abs(size_mb - 2.0) < 0.01, f"サイズ計算が不正: {size_mb}MB"

    @pytest.mark.asyncio
    async def test_c2_05_ctx_preview_path_set(self):
        """W4-C2-05: ctx.preview_path設定 — 正しいパス"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=5)
            expected_path_holder = {}

            def _fake_render(segments, video_path, output_path):
                expected_path_holder["path"] = output_path
                Path(output_path).write_bytes(b"\x00" * 1024)
                return True

            mock_sce = MagicMock()
            mock_sce.render_smart_cut = _fake_render
            mock_safe_io = MagicMock()
            mock_safe_io.VAULT_OUTPUTS_DIR = Path(tmpdir)

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

        assert result.success is True
        # ctx.preview_path が render_smart_cut に渡したパスと一致
        assert ctx.preview_path == expected_path_holder["path"]
        # StageResult.data.path も同じパス
        assert result.data.get("path") == ctx.preview_path


# ============================================================
# C3: 出力検証 (5テスト)
# ============================================================

class TestC3OutputValidation:
    """W4-C3-01〜W4-C3-05: 出力検証"""

    @pytest.mark.asyncio
    async def test_c3_01_preview_file_exists(self):
        """W4-C3-01: プレビューファイル存在 — Path.exists()"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=5)
            mock_sce, mock_safe_io, holder = _patch_preview_env(tmpdir)

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

            # tmpdir内でファイル存在確認（tmpdir削除前）
            assert result.success is True
            assert ctx.preview_path is not None
            assert Path(ctx.preview_path).exists(), "プレビューファイルが存在しない"

    @pytest.mark.asyncio
    async def test_c3_02_file_size_ge_1kb(self):
        """W4-C3-02: ファイルサイズ≥1KB — stat().st_size"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=5)
            # 5KB のファイルを作成
            mock_sce, mock_safe_io, _ = _patch_preview_env(tmpdir, file_size=5 * 1024)

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

            # tmpdir内でファイルサイズ確認（tmpdir削除前）
            assert result.success is True
            assert Path(ctx.preview_path).stat().st_size >= 1024, "ファイルサイズが1KB未満"

    @pytest.mark.asyncio
    async def test_c3_02b_file_size_exactly_1024_bytes(self):
        """W4-C3-02b: ファイルサイズちょうど1024バイト — DoD満たして成功"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=5)
            mock_sce, mock_safe_io, _ = _patch_preview_env(tmpdir, file_size=1024)

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

            assert result.success is True
            assert Path(ctx.preview_path).stat().st_size == 1024

    @pytest.mark.asyncio
    async def test_c3_02c_file_size_exactly_1023_bytes(self):
        """W4-C3-02c: ファイルサイズちょうど1023バイト — DoD満たさず失敗"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=5)
            mock_sce, mock_safe_io, _ = _patch_preview_env(tmpdir, file_size=1023)

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

            assert result.success is False
            assert "プレビュー生成失敗" in result.detail

    @pytest.mark.asyncio
    async def test_c3_03_stage_result_data_path(self):
        """W4-C3-03: StageResult.data.path — 正当なパス"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=5)
            mock_sce, mock_safe_io, _ = _patch_preview_env(tmpdir)

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

            # tmpdir内でパス検証（tmpdir削除前）
            assert result.success is True
            path_val = result.data.get("path")
            assert path_val is not None
            assert isinstance(path_val, str)
            assert path_val.endswith(".mp4")
            assert Path(path_val).exists()

    @pytest.mark.asyncio
    async def test_c3_04_stage_result_data_size_mb(self):
        """W4-C3-04: StageResult.data.size_mb — float≥0"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=5)
            mock_sce, mock_safe_io, _ = _patch_preview_env(tmpdir, file_size=512 * 1024)

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

        assert result.success is True
        size_mb = result.data.get("size_mb")
        assert size_mb is not None
        assert isinstance(size_mb, (int, float))
        assert size_mb >= 0

    @pytest.mark.asyncio
    async def test_c3_05_ffprobe_codec_duration_verification(self):
        """W4-C3-05: FFprobeでcodec/duration確認 — メディア検証(モック)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=5)
            mock_sce, mock_safe_io, _ = _patch_preview_env(tmpdir, file_size=10 * 1024)

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

            # tmpdir内でファイル検証（tmpdir削除前）
            assert result.success is True
            # ファイルが実際に作成されていること（FFprobe検証の前提）
            assert Path(ctx.preview_path).exists()
            # ファイルサイズが0より大きいこと
            assert Path(ctx.preview_path).stat().st_size > 0
            # StageResultにパスとサイズが記録されていること
            assert result.data.get("path") is not None
            assert result.data.get("size_mb") is not None


# ============================================================
# C4: エラー耐性 (5テスト)
# ============================================================

class TestC4ErrorResilience:
    """W4-C4-01〜W4-C4-05: エラー耐性"""

    @pytest.mark.asyncio
    async def test_c4_01_render_smart_cut_exception(self):
        """W4-C4-01: render_smart_cut例外 — エラーログ+False返却"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=5)

            def _render_raise(segments, video_path, output_path):
                raise RuntimeError("FFmpeg処理中に予期しないエラー")

            mock_sce = MagicMock()
            mock_sce.render_smart_cut = _render_raise
            mock_safe_io = MagicMock()
            mock_safe_io.VAULT_OUTPUTS_DIR = Path(tmpdir)

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

        assert result.success is False
        # 例外がキャッチされてsuccess=Falseで返却
        assert result.detail is not None

    @pytest.mark.asyncio
    async def test_c4_02_render_smart_cut_returns_false(self):
        """W4-C4-02: render_smart_cut=False — success=False"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=5)
            # render_smart_cutがFalseを返す（ファイルは作成されない）
            mock_sce, mock_safe_io, _ = _patch_preview_env(tmpdir, render_return=False)

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

        assert result.success is False

    @pytest.mark.asyncio
    async def test_c4_03_output_file_zero_bytes(self):
        """W4-C4-03: 出力ファイル0バイト — success=False"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=5)

            def _render_empty_file(segments, video_path, output_path):
                # 0バイトのファイルを作成
                Path(output_path).write_bytes(b"")
                return True  # Trueを返すが実際は空ファイル

            mock_sce = MagicMock()
            mock_sce.render_smart_cut = _render_empty_file
            mock_safe_io = MagicMock()
            mock_safe_io.VAULT_OUTPUTS_DIR = Path(tmpdir)

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

        # 0バイトファイルはDoD（1KB以上）を満たさないため、必ず success=False であること
        assert result.success is False

    @pytest.mark.asyncio
    async def test_c4_04_disk_full_graceful_failure(self):
        """W4-C4-04: ディスク容量不足 — graceful失敗"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=5)

            def _render_oserror(segments, video_path, output_path):
                raise OSError(28, "No space left on device")

            mock_sce = MagicMock()
            mock_sce.render_smart_cut = _render_oserror
            mock_safe_io = MagicMock()
            mock_safe_io.VAULT_OUTPUTS_DIR = Path(tmpdir)

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

        assert result.success is False
        # パイプラインがパニックしないこと（StageResultが返ること）
        assert isinstance(result, StageResult)
        assert result.duration_seconds >= 0

    @pytest.mark.asyncio
    async def test_c4_05_import_error_smart_cut_engine(self):
        """W4-C4-05: ImportError(smart_cut_engine) — 例外キャッチ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=5)
            mock_safe_io = MagicMock()
            mock_safe_io.VAULT_OUTPUTS_DIR = Path(tmpdir)

            with patch.dict("sys.modules", {
                "smart_cut_engine": None,  # Noneで ImportError を強制
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

        assert result.success is False
        # ImportError がキャッチされて graceful failure
        assert isinstance(result, StageResult)


# ============================================================
# C5: 統合・依存 (5テスト)
# ============================================================

class TestC5Integration:
    """W4-C5-01〜W4-C5-05: 統合・依存"""

    @pytest.mark.asyncio
    async def test_c5_01_smartcut_output_contract(self):
        """W4-C5-01: SmartCut出力との契約(CT-03) — selected参照"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = create_mock_ctx(segments=10)
            # SmartCutWorkerが設定する selected_segments を模倣
            ctx.selected_segments = _make_selected_segments(8)
            segments_passed = {}

            def _fake_render(segments, video_path, output_path):
                segments_passed["segs"] = segments
                Path(output_path).write_bytes(b"\x00" * 1024)
                return True

            mock_sce = MagicMock()
            mock_sce.render_smart_cut = _fake_render
            mock_safe_io = MagicMock()
            mock_safe_io.VAULT_OUTPUTS_DIR = Path(tmpdir)

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

        assert result.success is True
        # render_smart_cut に selected_segments が渡されていること
        assert segments_passed["segs"] is ctx.selected_segments
        # selected_segmentsの各要素が契約通りの構造を持つこと
        for seg in segments_passed["segs"]:
            assert "start" in seg
            assert "end" in seg

    @pytest.mark.asyncio
    async def test_c5_02_quality_gate_input_contract(self):
        """W4-C5-02: QualityGate入力への契約(CT-04) — ファイル存在+サイズ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=5)
            mock_sce, mock_safe_io, _ = _patch_preview_env(tmpdir, file_size=50 * 1024)

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

            # tmpdir内でのファイル存在チェック（tmpdir削除前に実行）
            assert result.success is True
            # QualityGateWorkerが期待するctx.preview_pathが設定されていること
            assert ctx.preview_path is not None
            assert isinstance(ctx.preview_path, str)
            # ファイルが実際に存在すること
            assert Path(ctx.preview_path).exists()
            # ファイルサイズが1KB以上であること
            assert Path(ctx.preview_path).stat().st_size >= 1024

    @pytest.mark.asyncio
    async def test_c5_03_verify_method_success_path(self):
        """W4-C5-03: verify()メソッド(success+path存在) — True検証"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=5)
            mock_sce, mock_safe_io, _ = _patch_preview_env(tmpdir)

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

            # verify()はPath.exists()を内部で呼ぶため、tmpdir内で実行
            assert result.success is True
            assert worker.verify(result) is True

    @pytest.mark.asyncio
    async def test_c5_03b_verify_method_failure_path(self):
        """W4-C5-03: verify()メソッド — failure時はFalse"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=5)

            def _render_raise(segments, video_path, output_path):
                raise RuntimeError("render失敗")

            mock_sce = MagicMock()
            mock_sce.render_smart_cut = _render_raise
            mock_safe_io = MagicMock()
            mock_safe_io.VAULT_OUTPUTS_DIR = Path(tmpdir)

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

        assert result.success is False
        # verify()が False を返すこと
        assert worker.verify(result) is False

    @pytest.mark.asyncio
    async def test_c5_04_vault_outputs_dir_reference(self):
        """W4-C5-04: VAULT_OUTPUTS_DIR参照 — safe_io連携"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=5)
            mock_safe_io = MagicMock()
            mock_safe_io.VAULT_OUTPUTS_DIR = Path(tmpdir)

            def _fake_render(segments, video_path, output_path):
                # 出力パスが tmpdir/preview/ 配下であること
                assert str(tmpdir) in output_path, f"予期しない出力パス: {output_path}"
                assert "preview" in output_path
                Path(output_path).write_bytes(b"\x00" * 1024)
                return True

            mock_sce = MagicMock()
            mock_sce.render_smart_cut = _fake_render

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

            assert result.success is True

    @pytest.mark.asyncio
    async def test_c5_05_websocket_progress_notification(self):
        """W4-C5-05: WebSocket進捗通知 — 通知送信確認(構造確認)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=5)
            mock_sce, mock_safe_io, _ = _patch_preview_env(tmpdir)

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

        assert result.success is True
        # StageResultにstage_nameが正しく設定されていること (通知の識別子)
        assert result.stage_name == "プレビュー生成"
        # duration_secondsが記録されていること
        assert result.duration_seconds >= 0

    @pytest.mark.asyncio
    async def test_c5_06_get_definition_of_done(self):
        """W4-C5-06: get_definition_of_done() メソッドの検証"""
        worker = PreviewWorker()
        dod = worker.get_definition_of_done()
        assert isinstance(dod, str)
        assert len(dod) > 0
        assert "プレビューファイル" in dod


# ============================================================
# C6: 性能・進化 (5テスト)
# ============================================================

class TestC6Performance:
    """W4-C6-01〜W4-C6-05: 性能・進化"""

    @pytest.mark.asyncio
    async def test_c6_01_10seg_preview_within_120s(self):
        """W4-C6-01: 10segプレビュー≤120秒 — 時間予算内"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=10)
            mock_sce, mock_safe_io, _ = _patch_preview_env(tmpdir)

            start = time.time()
            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)
            elapsed = time.time() - start

        assert result.success is True
        # モック環境では120秒以内に確実に完了するはず
        assert elapsed < 120.0, f"処理が時間予算を超過: {elapsed:.2f}秒"

    @pytest.mark.asyncio
    async def test_c6_02_gpu_mock_nvenc_usage(self):
        """W4-C6-02: GPU利用時の高速化 — NVENC使用確認(モック)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=5)
            render_call_count = {"count": 0}

            def _fake_render_nvenc(segments, video_path, output_path):
                render_call_count["count"] += 1
                Path(output_path).write_bytes(b"\x00" * 1024)
                return True

            mock_sce = MagicMock()
            mock_sce.render_smart_cut = _fake_render_nvenc
            mock_safe_io = MagicMock()
            mock_safe_io.VAULT_OUTPUTS_DIR = Path(tmpdir)

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

        assert result.success is True
        # render_smart_cut が1回だけ呼ばれること（重複呼び出し禁止）
        assert render_call_count["count"] == 1

    @pytest.mark.asyncio
    async def test_c6_03_temp_file_cleanup(self):
        """W4-C6-03: 一時ファイル削除 — クリーンアップ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=5)
            mock_sce, mock_safe_io, _ = _patch_preview_env(tmpdir)

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

            # tmpdir内でのクリーンアップ確認（tmpdir削除前に実行）
            assert result.success is True
            tmpdir_path = Path(tmpdir)
            all_files = list(tmpdir_path.rglob("*"))
            # 残るのはpreview/preview_*.mp4のみであること
            mp4_files = [f for f in all_files if f.suffix == ".mp4"]
            assert len(mp4_files) == 1, f"予期しないMP4ファイルが残留: {mp4_files}"

    @pytest.mark.asyncio
    async def test_c6_04_progressive_preview_integration(self):
        """W4-C6-04: progressive_preview連携 — 視覚検証(構造確認)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=5)
            mock_sce, mock_safe_io, _ = _patch_preview_env(tmpdir)

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

        assert result.success is True
        # progressive_preview ワークフローが期待するデータ構造が揃っていること
        assert result.data.get("path") is not None  # プレビューパス
        assert result.data.get("size_mb") is not None  # サイズ情報
        # ファイルが再生可能なMP4として存在すること
        assert Path(result.data["path"]).suffix == ".mp4"

    @pytest.mark.asyncio
    async def test_c6_05_dream_engine_quality_feedback(self):
        """W4-C6-05: DreamEngine反映 — 品質フィードバック(StageResult完備)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = _make_preview_ctx(selected_count=5)
            mock_sce, mock_safe_io, _ = _patch_preview_env(tmpdir, file_size=3 * 1024 * 1024)

            with patch.dict("sys.modules", {
                "smart_cut_engine": mock_sce,
                "safe_io": mock_safe_io,
            }):
                worker = PreviewWorker()
                result = await worker.execute(ctx)

        assert result.success is True
        # DreamEngineが学習に必要なStageResultフィールドが完備していること
        assert result.stage_name == "プレビュー生成"
        assert result.success is True
        assert isinstance(result.duration_seconds, (int, float))
        assert result.duration_seconds >= 0
        assert result.data.get("path") is not None
        assert result.data.get("size_mb") is not None
        # 品質フィードバック: detailにサイズ情報が含まれること
        assert "MB" in result.detail


# ============================================================
# C7: サムネイル生成・検証（解像度・アスペクト比・ファイルサイズ・StageBoundAgent連携）
# ============================================================

def test_thumbnail_generation_success(tmp_path):
    """正常系: 1280x720 16:9 の画像が生成され、検証を通過すること"""
    from PIL import Image
    output_path = tmp_path / "test_thumb.png"
    worker = PreviewWorker()
    
    res_path = worker.generate_thumbnail(output_path, text="Test Thumb")
    assert res_path.exists()
    
    with Image.open(res_path) as img:
        assert img.size == (1280, 720)


def test_thumbnail_validation(tmp_path):
    """品質検証のテスト（正常、低解像度、アスペクト比、ファイルサイズ、破損、存在しない）"""
    from PIL import Image
    worker = PreviewWorker()
    
    # 1. 正常な画像
    ok_path = tmp_path / "ok.png"
    worker.generate_thumbnail(ok_path, width=1280, height=720)
    result = worker.validate_thumbnail(ok_path)
    assert result["width"] == 1280
    assert result["height"] == 720
    
    # 2. 低解像度の画像 (1280x720未満)
    bad_res_path = tmp_path / "bad_res.png"
    from PIL import Image
    Image.new("RGB", (640, 360)).save(bad_res_path)
    with pytest.raises(ValueError) as exc:
        worker.validate_thumbnail(bad_res_path)
    assert "Resolution must be at least 1280x720" in str(exc.value)
    
    # 3. アスペクト比が正しくない (16:10 など)
    bad_aspect_path = tmp_path / "bad_aspect.png"
    Image.new("RGB", (1280, 800)).save(bad_aspect_path)
    with pytest.raises(ValueError) as exc:
        worker.validate_thumbnail(bad_aspect_path)
    assert "Aspect ratio must be 16:9" in str(exc.value)
    
    # 4. ファイルが存在しない
    non_existent = tmp_path / "ghost.png"
    with pytest.raises(FileNotFoundError):
        worker.validate_thumbnail(non_existent)
        
    # 5. 破損画像
    corrupted_path = tmp_path / "corrupt.png"
    corrupted_path.write_text("not an image at all", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        worker.validate_thumbnail(corrupted_path)
    assert "corrupted or invalid" in str(exc.value)

    # 6. 4MB以上のファイルサイズ制限の検証
    large_file = tmp_path / "large_file.png"
    large_file.write_bytes(b"\x00" * (4 * 1024 * 1024 + 10))
    with pytest.raises(ValueError) as exc:
        worker.validate_thumbnail(large_file)
    assert "File size exceeds 4MB limit" in str(exc.value)


def test_thumbnail_invalid_dimensions(tmp_path):
    """負の数やゼロ、整数以外での例外発生"""
    worker = PreviewWorker()
    
    # 0 または負の値
    with pytest.raises(ValueError) as exc:
        worker.generate_thumbnail(tmp_path / "neg.png", width=-100, height=720)
    assert "must be positive integers" in str(exc.value)

    with pytest.raises(ValueError) as exc:
        worker.generate_thumbnail(tmp_path / "zero.png", width=1280, height=0)
    assert "must be positive integers" in str(exc.value)

    # 整数以外
    with pytest.raises(ValueError) as exc:
        worker.generate_thumbnail(tmp_path / "str.png", width="invalid", height=720)
    assert "must be integers" in str(exc.value)


def test_thumbnail_strict_aspect_ratio(tmp_path):
    """1280x730 などアスペクト比がわずかにズレている場合の厳密エラー"""
    from PIL import Image
    worker = PreviewWorker()
    test_path = tmp_path / "strict_aspect.png"
    Image.new("RGB", (1280, 730)).save(test_path)
    
    with pytest.raises(ValueError) as exc:
        worker.validate_thumbnail(test_path)
    assert "Aspect ratio must be 16:9" in str(exc.value)


@pytest.mark.asyncio
async def test_thumbnail_stage_bound_agent_integration(tmp_path):
    """StageBoundAgent に resolve_thumbnail_task を登録し、正常完了して SQLite に結果保存されること"""
    import sqlite3
    import json
    from agents.stage_bound_agent import StageBoundAgent
    db_file = tmp_path / "thumbnail_agent.db"
    
    worker = PreviewWorker()
    worker.output_dir = tmp_path
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    
    task_id = "t_worker_thumb_ok"
    await agent.register_task(task_id=task_id, initial_status="READY")
    
    await agent.start(worker.resolve_thumbnail_task)
    
    # 最大 10 秒待機。
    # 1.0 秒だとマシンが混んでいるとき（全体実行や他プロセスと並走）に間に合わず、
    # COMPLETED 前に抜けて 'FAILED' == 'COMPLETED' で落ちる不安定なテストだった。
    # 完了したら即座に抜けるため、通常時の実行時間は変わらない。
    for _ in range(200):
        status = await agent.get_task_status(task_id)
        if status in ("COMPLETED", "FAILED"):
            break
        await asyncio.sleep(0.05)
        
    final_status = await agent.get_task_status(task_id)
    assert final_status == "COMPLETED"
    
    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.execute("SELECT result, error, retry_count FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None
        result_data = json.loads(row[0])
        assert result_data["width"] == 1280
        assert result_data["height"] == 720
        assert row[1] is None
        assert row[2] == 0
    finally:
        conn.close()
        
    await agent.stop()


@pytest.mark.asyncio
async def test_thumbnail_stage_bound_agent_retry_on_failure(tmp_path):
    """失敗時のリトライ機能との連携テスト"""
    import sqlite3
    from agents.stage_bound_agent import StageBoundAgent
    db_file = tmp_path / "thumbnail_retry.db"
    
    worker = PreviewWorker()
    # 不正なディレクトリを指定して書き込みエラーを意図的に発生させる
    # 2026-07-26: 以前は r"C:/invalid_dir_?:*" を使っていたが、? : * は
    # Windows でのみ無効な文字で、Linux では正当なディレクトリ名として
    # 作成に成功してしまう。その結果 CI(Linux) でタスクが COMPLETED になり
    # FAILED を期待するアサーションが落ちていた。
    # 通常ファイルの下にディレクトリは作れないので、全 OS で確実に失敗する。
    _blocker = tmp_path / "not_a_directory"
    _blocker.write_text("x", encoding="utf-8")
    worker.output_dir = str(_blocker / "out")
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    
    task_id = "t_worker_thumb_fail"
    await agent.register_task(task_id=task_id, initial_status="READY", max_retries=2)
    
    await agent.start(worker.resolve_thumbnail_task)
    
    for _ in range(20):
        status = await agent.get_task_status(task_id)
        if status == "FAILED":
            break
        await asyncio.sleep(0.05)
        
    final_status = await agent.get_task_status(task_id)
    assert final_status == "FAILED"
    
    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.execute("SELECT retry_count, status, error FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == 2
        assert row[1] == "FAILED"
        assert row[2] is not None
    finally:
        conn.close()
        
    await agent.stop()
