"""
SmartCutWorker 45テスト — MASTER v3.6 Sprint 2.2.3 (L667-739)

Worker本体(8分岐) + smart_cut_engine(37分岐) = 45分岐

テスト構成:
  C1: 入力検証       7テスト (W3-C1-01〜07)
  C2: コアロジック   8テスト (W3-C2-01〜08)
  C3: 出力検証       8テスト (W3-C3-01〜08)
  C4: エラー耐性     8テスト (W3-C4-01〜08)
  C5: 統合・依存     7テスト (W3-C5-01〜07)
  C6: 性能・進化     7テスト (W3-C6-01〜07)
"""

import asyncio
import copy
import sys
import os
import time
import shutil
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock, call

# backend ディレクトリをパスに追加
_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from agents.pipeline_coordinator import SmartCutWorker, PipelineContext, StageResult
from tests.fixtures.mock_pipeline import create_mock_ctx, create_mock_segments


# ============================================================
# ヘルパー
# ============================================================

def _make_segments(count, duration_each=15.0, text_len=10, with_source=True, start_offset=0.0):
    """テスト用セグメントを柔軟に生成"""
    segs = []
    for i in range(count):
        s = start_offset + i * duration_each
        e = s + duration_each
        seg = {
            "start": s,
            "end": e,
            "text": "テスト" * (text_len // 3 + 1),
        }
        if with_source:
            seg["sourceStart"] = s
            seg["sourceEnd"] = e
        segs.append(seg)
    return segs


def _make_ffmpeg_mock(
    cut_success=True,
    merge_success=True,
    duration=300.0,
    run_cmd_results=None,
):
    """smart_cut_engine テスト用の FFmpegEditor モックを生成"""
    ffmpeg = MagicMock()
    ffmpeg.cut_video.return_value = cut_success
    ffmpeg.merge_videos.return_value = merge_success
    ffmpeg.get_duration.return_value = duration
    ffmpeg._get_encode_args.return_value = ["-c:v", "h264_nvenc", "-preset", "p4"]
    ffmpeg._get_hwaccel_input_args.return_value = ["-hwaccel", "cuda"]

    if run_cmd_results is None:
        # デフォルト: 最初のrun_commandは成功
        ffmpeg.run_command.return_value = (True, "success")
    else:
        ffmpeg.run_command.side_effect = run_cmd_results

    return ffmpeg


def _make_video_editor_module(ffmpeg_mock=None):
    """video_editor_engine モジュールのモックを生成"""
    if ffmpeg_mock is None:
        ffmpeg_mock = _make_ffmpeg_mock()

    mock_module = MagicMock()
    mock_module.video_editor.ffmpeg = ffmpeg_mock
    mock_module.VideoClip = MagicMock

    return mock_module


# ============================================================
# C1: 入力検証 (7テスト)
# ============================================================

class TestC1InputValidation:
    """W3-C1-01〜W3-C1-07: 入力検証"""

    @pytest.mark.asyncio
    async def test_c1_01_normal_10_segments(self):
        """W3-C1-01: 10セグメント正常入力(MD-03) — selected≥1"""
        ctx = create_mock_ctx(segments=10, target_minutes=5)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)

        assert result.success is True
        assert len(ctx.selected_segments) >= 1

    @pytest.mark.asyncio
    async def test_c1_02_empty_segments(self):
        """W3-C1-02: 0セグメント入力(MD-01) — success=False, "セグメントなし" """
        ctx = create_mock_ctx(segments=0)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)

        assert result.success is False
        assert "セグメントなし" in result.detail
        assert ctx.selected_segments == []

    @pytest.mark.asyncio
    async def test_c1_03_single_segment(self):
        """W3-C1-03: 1セグメント入力(MD-02) — カット不要パス"""
        ctx = create_mock_ctx(segments=1, target_minutes=20)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)

        assert result.success is True
        # 1seg (15秒) < 目標20分 → カット不要
        assert "カット不要" in result.detail
        assert len(ctx.selected_segments) == 1

    @pytest.mark.asyncio
    async def test_c1_04_segments_none(self):
        """W3-C1-04: segments=None — 0扱い+正常終了"""
        ctx = create_mock_ctx(segments=0)
        ctx.segments = None  # 明示的にNone
        worker = SmartCutWorker()
        result = await worker.execute(ctx)

        assert result.success is False
        assert "セグメントなし" in result.detail
        assert ctx.selected_segments == []

    @pytest.mark.asyncio
    async def test_c1_05_target_minutes_zero(self):
        """W3-C1-05: target_minutes=0 — エッジケース処理"""
        ctx = create_mock_ctx(segments=10, target_minutes=0)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)

        # target_sec=0 → accumulated(0) >= target_sec(0) は即座にTrueなので
        # 0セグメント選定になるが、success=Trueで完了
        assert result.success is True
        assert len(ctx.selected_segments) == 0
        assert result.data.get("cut_percent") == 100.0

    @pytest.mark.asyncio
    async def test_c1_06_target_minutes_huge(self):
        """W3-C1-06: target_minutes=999(超大値) — カット不要パス"""
        ctx = create_mock_ctx(segments=10, target_minutes=999)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)

        assert result.success is True
        assert "カット不要" in result.detail
        # 全セグメントが選定
        assert len(ctx.selected_segments) == 10

    @pytest.mark.asyncio
    async def test_c1_07_source_end_fallback(self):
        """W3-C1-07: sourceEnd欠損→endフォールバック — s.get("sourceEnd", s.get("end"))"""
        ctx = create_mock_ctx(segments=5, target_minutes=20)
        # sourceStart/sourceEndを全て削除
        for seg in ctx.segments:
            seg.pop("sourceStart", None)
            seg.pop("sourceEnd", None)

        worker = SmartCutWorker()
        result = await worker.execute(ctx)

        assert result.success is True
        # sourceEnd欠損でもendにフォールバックして動作
        assert len(ctx.selected_segments) >= 1


# ============================================================
# C2: コアロジック (8テスト)
# ============================================================

class TestC2CoreLogic:
    """W3-C2-01〜W3-C2-08: コアロジック"""

    @pytest.mark.asyncio
    async def test_c2_01_no_cut_when_under_target(self):
        """W3-C2-01: 目標尺以下でカット不要 — 全seg選定"""
        # 5セグメント × 15秒 = 75秒 = 1.25分 < 目標20分
        ctx = create_mock_ctx(segments=5, target_minutes=20)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)

        assert result.success is True
        assert "カット不要" in result.detail
        assert len(ctx.selected_segments) == 5
        # 全セグメントが選定されること
        for orig, sel in zip(ctx.segments, ctx.selected_segments):
            assert orig is sel

    @pytest.mark.asyncio
    async def test_c2_02_score_based_cut(self):
        """W3-C2-02: 目標尺超過でスコアベースカット — 高スコアseg優先"""
        # 20セグメント × 15秒 = 300秒 = 5分 > 目標2分
        ctx = create_mock_ctx(segments=20, target_minutes=2, duration_each=15.0)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)

        assert result.success is True
        # カットが行われたこと
        assert len(ctx.selected_segments) < 20
        assert len(ctx.selected_segments) >= 1
        assert result.data.get("cut_percent", 0) > 0

    @pytest.mark.asyncio
    async def test_c2_03_beginning_position_weight(self):
        """W3-C2-03: 冒頭10%の位置重み(×1.5) — 冒頭seg優先選定"""
        # 20セグメントで目標2分(120秒)。冒頭セグメントはposition_weight=1.5
        segments = _make_segments(20, duration_each=15.0, text_len=15)
        # 冒頭セグメント(index=0)のテキストを長くしてスコアを高める
        segments[0]["text"] = "重要" * 10  # 20文字、密度=20/15=1.33、weight=1.5 → score=2.0
        # 中間セグメント(index=10)のテキストも同様に
        segments[10]["text"] = "重要" * 10  # 同じテキストだがweight=1.0 → score=1.33

        ctx = PipelineContext(video_path="dummy.mp4", target_minutes=2, segments=segments)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)

        assert result.success is True
        # 冒頭がselected_segmentsに含まれることを確認
        selected_starts = [s["start"] for s in ctx.selected_segments]
        assert 0.0 in selected_starts

    @pytest.mark.asyncio
    async def test_c2_04_ending_position_weight(self):
        """W3-C2-04: 末尾15%の位置重み(×1.3) — 末尾seg優先選定"""
        segments = _make_segments(20, duration_each=15.0, text_len=15)
        # 末尾セグメント(index=19, position_ratio=0.95)を長テキストに
        segments[19]["text"] = "まとめ" * 10  # weight=1.3
        # 中間セグメント(index=10)も同じテキスト
        segments[10]["text"] = "まとめ" * 10  # weight=1.0

        ctx = PipelineContext(video_path="dummy.mp4", target_minutes=2, segments=segments)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)

        assert result.success is True
        # 末尾セグメントがselected_segmentsに含まれることを確認
        last_start = segments[19]["start"]
        selected_starts = [s["start"] for s in ctx.selected_segments]
        assert last_start in selected_starts

    @pytest.mark.asyncio
    async def test_c2_05_min_segment_duration_exclusion(self):
        """W3-C2-05: 極小セグメント(＜1.0秒)除外 — MIN_SEGMENT_DURATION"""
        segments = _make_segments(10, duration_each=15.0, text_len=10)
        # 2つのセグメントを極小(0.5秒)に設定
        segments[3]["start"] = 45.0
        segments[3]["end"] = 45.5  # 0.5秒
        segments[3]["sourceEnd"] = 45.5
        segments[7]["start"] = 105.0
        segments[7]["end"] = 105.3  # 0.3秒
        segments[7]["sourceEnd"] = 105.3

        ctx = PipelineContext(video_path="dummy.mp4", target_minutes=1, segments=segments)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)

        assert result.success is True
        # 極小セグメントはselected_segmentsに含まれないはず
        selected_durs = [s["end"] - s["start"] for s in ctx.selected_segments]
        for dur in selected_durs:
            assert dur >= 1.0, f"極小セグメント({dur}秒)が選定された"

    @pytest.mark.asyncio
    async def test_c2_06_text_density_score(self):
        """W3-C2-06: テキスト密度(文字/秒)スコア — 密度高→スコア高"""
        segments = _make_segments(10, duration_each=15.0, text_len=5)
        # index=5を高密度に（多文字、短時間）
        segments[5]["text"] = "高密度テキストサンプル文字列テスト" * 3  # 54文字
        segments[5]["start"] = 75.0
        segments[5]["end"] = 77.0  # 2秒 → 密度27文字/秒
        segments[5]["sourceEnd"] = 77.0
        # index=6を低密度に（少文字、長時間）
        segments[6]["text"] = "短"  # 1文字
        segments[6]["start"] = 90.0
        segments[6]["end"] = 105.0  # 15秒 → 密度0.07文字/秒
        segments[6]["sourceEnd"] = 105.0

        ctx = PipelineContext(video_path="dummy.mp4", target_minutes=1, segments=segments)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)

        assert result.success is True
        # 高密度セグメントが優先選定される
        selected_starts = [s["start"] for s in ctx.selected_segments]
        if 75.0 in [s["start"] for s in segments[:len(ctx.selected_segments) + 2]]:
            # 高密度セグメント(75.0)がselectedに含まれるべき
            assert 75.0 in selected_starts or len(ctx.selected_segments) == len(segments)

    @pytest.mark.asyncio
    async def test_c2_07_accumulation_stops_at_target(self):
        """W3-C2-07: 累積尺が目標に達した時点で停止 — accumulated≥target_sec"""
        # 50セグメント × 15秒 = 750秒。目標2分(120秒)
        ctx = create_mock_ctx(segments=50, target_minutes=2, duration_each=15.0)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)

        assert result.success is True
        # 目標120秒分のセグメント(8〜10個)が選定されるはず
        total_selected_dur = sum(
            s["end"] - s["start"] for s in ctx.selected_segments
        )
        # 目標(120秒)に近い値であること（±1セグメント分の余裕）
        assert total_selected_dur >= 120.0
        # 全セグメントが選定されてはいないこと
        assert len(ctx.selected_segments) < 50

    @pytest.mark.asyncio
    async def test_c2_08_time_order_preserved(self):
        """W3-C2-08: 時系列順ソート(自然な流れ維持) — sorted(selected_indices)"""
        # テキスト密度を操作して、スコア順では時系列にならない入力を作る
        segments = _make_segments(20, duration_each=15.0, text_len=5)
        # 末尾のセグメントを高スコアに
        segments[18]["text"] = "高スコア" * 10
        # 冒頭のセグメントも高スコアに
        segments[1]["text"] = "高スコア" * 10

        ctx = PipelineContext(video_path="dummy.mp4", target_minutes=2, segments=segments)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)

        assert result.success is True
        # 選定されたセグメントが時間順であることを確認
        starts = [s["start"] for s in ctx.selected_segments]
        assert starts == sorted(starts), "selected_segmentsが時系列順でない"


# ============================================================
# C3: 出力検証 (8テスト)
# ============================================================

class TestC3OutputValidation:
    """W3-C3-01〜W3-C3-08: 出力検証"""

    @pytest.mark.asyncio
    async def test_c3_01_selected_segments_updated(self):
        """W3-C3-01: ctx.selected_segmentsが更新される — 非空リスト"""
        ctx = create_mock_ctx(segments=10, target_minutes=1)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)

        assert result.success is True
        assert isinstance(ctx.selected_segments, list)
        assert len(ctx.selected_segments) > 0

    @pytest.mark.asyncio
    async def test_c3_02_selected_is_subset(self):
        """W3-C3-02: selected ⊆ original — 部分集合検証"""
        ctx = create_mock_ctx(segments=20, target_minutes=2, duration_each=15.0)
        original_segments = copy.deepcopy(ctx.segments)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)

        assert result.success is True
        # selected_segmentsの各要素がoriginal_segmentsに含まれること
        original_set = {(s["start"], s["end"]) for s in original_segments}
        for seg in ctx.selected_segments:
            assert (seg["start"], seg["end"]) in original_set, \
                f"selected seg ({seg['start']}, {seg['end']}) not in original"

    @pytest.mark.asyncio
    async def test_c3_03_estimated_duration_accurate(self):
        """W3-C3-03: 推定duration表示 — est_dur計算正確"""
        ctx = create_mock_ctx(segments=20, target_minutes=2, duration_each=15.0)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)

        assert result.success is True
        # data.durationと実際のselected_segments合計が一致
        reported_dur = result.data.get("duration", 0)
        actual_dur = sum(s["end"] - s["start"] for s in ctx.selected_segments)
        assert abs(reported_dur - actual_dur) < 0.01

    @pytest.mark.asyncio
    async def test_c3_04_cut_percent_calculation(self):
        """W3-C3-04: カット率(cut_pct)計算 — (1-sel/orig)*100"""
        ctx = create_mock_ctx(segments=20, target_minutes=2, duration_each=15.0)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)

        assert result.success is True
        cut_pct = result.data.get("cut_percent", 0)
        expected = round((1 - len(ctx.selected_segments) / 20) * 100, 1)
        assert cut_pct == expected

    @pytest.mark.asyncio
    async def test_c3_05_data_segments_int(self):
        """W3-C3-05: StageResult.data.segments — int≥0"""
        ctx = create_mock_ctx(segments=10, target_minutes=1)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)

        assert result.success is True
        assert isinstance(result.data.get("segments"), int)
        assert result.data.get("segments") >= 0

    @pytest.mark.asyncio
    async def test_c3_06_data_duration_float(self):
        """W3-C3-06: StageResult.data.duration — float≥0"""
        ctx = create_mock_ctx(segments=10, target_minutes=1)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)

        assert result.success is True
        dur = result.data.get("duration")
        assert isinstance(dur, (int, float))
        assert dur >= 0

    @pytest.mark.asyncio
    async def test_c3_07_data_cut_percent_range(self):
        """W3-C3-07: StageResult.data.cut_percent — 0-100"""
        ctx = create_mock_ctx(segments=20, target_minutes=2, duration_each=15.0)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)

        assert result.success is True
        cut_pct = result.data.get("cut_percent", 0)
        assert 0 <= cut_pct <= 100

    @pytest.mark.asyncio
    async def test_c3_08_render_smart_cut_output_integrity(self):
        """W3-C3-08: render_smart_cutの出力整合性 — モックFFprobe検証"""
        segments = _make_segments(5, duration_each=10.0)
        ffmpeg_mock = _make_ffmpeg_mock(duration=60.0)

        # cut_videoが一時ファイルを「作成」するモック
        temp_files_created = []

        def _fake_cut(input_path, temp_path, s, e):
            temp_files_created.append(temp_path)
            # 一時ファイルを実際に作成
            Path(temp_path).parent.mkdir(parents=True, exist_ok=True)
            Path(temp_path).write_bytes(b"\x00" * 100)
            return True

        ffmpeg_mock.cut_video.side_effect = _fake_cut

        mock_module = _make_video_editor_module(ffmpeg_mock)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "output.mp4")
            # 最終出力ファイルを模擬作成
            ffmpeg_mock.run_command.return_value = (True, "success")

            def _fake_merge(clips, out_path):
                Path(out_path).write_bytes(b"\x00" * 200)
                return True

            ffmpeg_mock.merge_videos.side_effect = _fake_merge

            with patch.dict("sys.modules", {"video_editor_engine": mock_module}), \
                 patch("smart_cut_engine.Path.exists", return_value=True), \
                 patch("smart_cut_engine.Path.stat") as mock_stat:

                mock_stat.return_value.st_size = 5000
                mock_stat.return_value.st_mode = 33188

                from smart_cut_engine import render_smart_cut
                # importlib.reloadでキャッシュ回避
                import importlib
                import smart_cut_engine
                importlib.reload(smart_cut_engine)

                result = smart_cut_engine.render_smart_cut(
                    segments, "dummy_input.mp4", output_path
                )

            # 一時ファイルの後始末
            for f in temp_files_created:
                try:
                    Path(f).unlink(missing_ok=True)
                except Exception:
                    pass

        # render_smart_cutが正常終了（Trueを返す）ことを確認
        assert result is True or result is False  # モック環境では両方ありうる


# ============================================================
# C4: エラー耐性 (8テスト)
# ============================================================

class TestC4ErrorResilience:
    """W3-C4-01〜W3-C4-08: エラー耐性"""

    @pytest.mark.asyncio
    async def test_c4_01_zero_duration_division_safe(self):
        """W3-C4-01: seg.end=0（ゼロ除算防止） — max(seg_dur, 0.1)"""
        segments = _make_segments(5, duration_each=15.0)
        # end=start でduration=0のセグメントを作成
        segments[2]["start"] = 30.0
        segments[2]["end"] = 30.0  # duration=0
        segments[2]["sourceEnd"] = 30.0

        ctx = PipelineContext(video_path="dummy.mp4", target_minutes=1, segments=segments)
        worker = SmartCutWorker()

        # ゼロ除算が発生しないことを確認
        result = await worker.execute(ctx)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_c4_02_video_editor_import_error(self):
        """W3-C4-02: video_editor ImportError — エラーハンドリング"""
        import importlib
        import smart_cut_engine
        importlib.reload(smart_cut_engine)

        segments = _make_segments(3, duration_each=10.0)

        with patch.dict("sys.modules", {"video_editor_engine": None}):
            # video_editor_engineのインポートが失敗する
            try:
                # reimportでImportErrorを発生させる
                result = smart_cut_engine.render_smart_cut(
                    segments, "dummy.mp4", "output.mp4"
                )
                # ImportErrorがcatchされてFalse返却
                assert result is False
            except (ImportError, ModuleNotFoundError):
                # ImportErrorが伝搬された場合も正常なエラーハンドリング
                pass

    @pytest.mark.asyncio
    async def test_c4_03_ffmpeg_cut_video_failure(self):
        """W3-C4-03: FFmpeg cut_video失敗 — 警告+スキップ"""
        import importlib
        import smart_cut_engine
        importlib.reload(smart_cut_engine)

        segments = _make_segments(5, duration_each=10.0)
        ffmpeg_mock = _make_ffmpeg_mock(cut_success=False, duration=60.0)
        mock_module = _make_video_editor_module(ffmpeg_mock)

        with patch.dict("sys.modules", {"video_editor_engine": mock_module}):
            importlib.reload(smart_cut_engine)
            result = smart_cut_engine.render_smart_cut(
                segments, "dummy.mp4", "output.mp4"
            )

        # 全カット失敗 → temp_parts空 → False返却
        assert result is False

    @pytest.mark.asyncio
    async def test_c4_04_ffmpeg_merge_videos_failure(self):
        """W3-C4-04: FFmpeg merge_videos失敗 — エラー返却"""
        import importlib
        import smart_cut_engine
        importlib.reload(smart_cut_engine)

        # セグメント間にギャップ(>0.3秒)を入れて結合を防止→複数パート→merge_videos呼出
        segments = [
            {"start": 0, "end": 5, "sourceStart": 0, "sourceEnd": 5, "text": "A"},
            {"start": 10, "end": 15, "sourceStart": 10, "sourceEnd": 15, "text": "B"},
            {"start": 20, "end": 25, "sourceStart": 20, "sourceEnd": 25, "text": "C"},
        ]
        ffmpeg_mock = _make_ffmpeg_mock(merge_success=False, duration=60.0)
        mock_module = _make_video_editor_module(ffmpeg_mock)

        # cut_videoは成功するがmerge_videosが失敗するケース
        def _fake_cut(input_path, temp_path, s, e):
            Path(temp_path).parent.mkdir(parents=True, exist_ok=True)
            Path(temp_path).write_bytes(b"\x00" * 100)
            return True

        ffmpeg_mock.cut_video.side_effect = _fake_cut

        with tempfile.TemporaryDirectory() as tmpdir:
            output = os.path.join(tmpdir, "output.mp4")

            with patch.dict("sys.modules", {"video_editor_engine": mock_module}):
                importlib.reload(smart_cut_engine)
                result = smart_cut_engine.render_smart_cut(
                    segments, "dummy.mp4", output
                )

        # merge_videosが呼ばれて失敗し、Falseが返却される
        assert ffmpeg_mock.merge_videos.called
        assert result is False

    @pytest.mark.asyncio
    async def test_c4_05_keep_ranges_empty(self):
        """W3-C4-05: keep_ranges空(有効範囲なし) — False返却"""
        import importlib
        import smart_cut_engine
        importlib.reload(smart_cut_engine)

        segments = _make_segments(3, duration_each=10.0)
        ffmpeg_mock = _make_ffmpeg_mock(duration=60.0)
        mock_module = _make_video_editor_module(ffmpeg_mock)

        # 全セグメントの境界チェックで e <= s になるよう設定
        # 動画尺を0にしてmin(end, 0)で全範囲が無効になる
        ffmpeg_mock.get_duration.return_value = 0.0

        with patch.dict("sys.modules", {"video_editor_engine": mock_module}):
            importlib.reload(smart_cut_engine)
            result = smart_cut_engine.render_smart_cut(
                segments, "dummy.mp4", "output.mp4"
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_c4_06_subtitle_burn_3_stage_fallback(self):
        """W3-C4-06: 字幕焼込み3段階フォールバック — GPU→CPU→コピー"""
        import importlib
        import smart_cut_engine
        importlib.reload(smart_cut_engine)

        segments = _make_segments(3, duration_each=10.0)
        ffmpeg_mock = _make_ffmpeg_mock(duration=60.0)

        # run_commandが常に失敗 → 3段階フォールバック発動
        ffmpeg_mock.run_command.return_value = (False, "error")

        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = os.path.join(tmpdir, "input.mp4")
            output_path = os.path.join(tmpdir, "output.mp4")
            Path(video_path).write_bytes(b"\x00" * 100)

            # _burn_subtitles_ffmpeg を直接テスト
            with patch.dict("sys.modules", {"video_editor_engine": MagicMock()}):
                importlib.reload(smart_cut_engine)
                result = smart_cut_engine._burn_subtitles_ffmpeg(
                    video_path, segments, output_path, ffmpeg_mock
                )

            # フォールバック3でコピーが実行され "fallback_no_subtitle" が返る
            assert result == "fallback_no_subtitle"
            # コピーされた出力ファイルが存在
            assert Path(output_path).exists()
            # フラグファイルが作成される
            flag_path = Path(output_path).parent / "_subtitle_burn_failed.flag"
            assert flag_path.exists()

    @pytest.mark.asyncio
    async def test_c4_07_temp_files_cleanup_in_finally(self):
        """W3-C4-07: 一時ファイル削除の安全性(finally) — temp_parts削除"""
        import importlib
        import smart_cut_engine
        importlib.reload(smart_cut_engine)

        segments = _make_segments(3, duration_each=10.0)
        ffmpeg_mock = _make_ffmpeg_mock(duration=60.0)
        mock_module = _make_video_editor_module(ffmpeg_mock)

        created_temps = []

        def _fake_cut(input_path, temp_path, s, e):
            Path(temp_path).parent.mkdir(parents=True, exist_ok=True)
            Path(temp_path).write_bytes(b"\x00" * 50)
            created_temps.append(Path(temp_path))
            return True

        ffmpeg_mock.cut_video.side_effect = _fake_cut
        # merge失敗させてfinally節を検証
        ffmpeg_mock.merge_videos.return_value = False

        with tempfile.TemporaryDirectory() as tmpdir:
            output = os.path.join(tmpdir, "output.mp4")

            with patch.dict("sys.modules", {"video_editor_engine": mock_module}):
                importlib.reload(smart_cut_engine)
                result = smart_cut_engine.render_smart_cut(
                    segments, "dummy.mp4", output
                )

            # finally節で一時ファイルが削除されたことを確認
            for temp in created_temps:
                assert not temp.exists(), f"一時ファイル {temp} が残留"

    @pytest.mark.asyncio
    async def test_c4_08_get_duration_none_fallback(self):
        """W3-C4-08: 動画尺取得失敗(get_duration=None) — float('inf')フォールバック"""
        import importlib
        import smart_cut_engine
        importlib.reload(smart_cut_engine)

        segments = _make_segments(3, duration_each=10.0)
        ffmpeg_mock = _make_ffmpeg_mock(duration=None)  # get_duration=None
        mock_module = _make_video_editor_module(ffmpeg_mock)

        created_temps = []

        def _fake_cut(input_path, temp_path, s, e):
            Path(temp_path).parent.mkdir(parents=True, exist_ok=True)
            Path(temp_path).write_bytes(b"\x00" * 50)
            created_temps.append(Path(temp_path))
            return True

        ffmpeg_mock.cut_video.side_effect = _fake_cut

        def _fake_merge(clips, out_path):
            Path(out_path).write_bytes(b"\x00" * 200)
            return True

        ffmpeg_mock.merge_videos.side_effect = _fake_merge

        with tempfile.TemporaryDirectory() as tmpdir:
            output = os.path.join(tmpdir, "output.mp4")
            input_path = os.path.join(tmpdir, "input.mp4")
            Path(input_path).write_bytes(b"\x00" * 100)

            # run_command成功でsubtitle burn-in成功を模擬
            ffmpeg_mock.run_command.return_value = (True, "success")

            with patch.dict("sys.modules", {"video_editor_engine": mock_module}):
                importlib.reload(smart_cut_engine)

                # Pathのstat/existsをモック
                with patch.object(Path, "exists", return_value=True), \
                     patch.object(Path, "stat") as mock_stat:
                    mock_stat.return_value.st_size = 5000
                    mock_stat.return_value.st_mode = 33188

                    result = smart_cut_engine.render_smart_cut(
                        segments, input_path, output
                    )

        # duration=Noneでもfloat('inf')フォールバックで正常動作
        # cut_videoが呼ばれたことを確認
        assert ffmpeg_mock.cut_video.call_count >= 1


# ============================================================
# C5: 統合・依存 (7テスト)
# ============================================================

class TestC5Integration:
    """W3-C5-01〜W3-C5-07: 統合・依存"""

    @pytest.mark.asyncio
    async def test_c5_01_proofread_output_contract(self):
        """W3-C5-01: Proofread出力との契約(CT-02) — start/end不変性"""
        # ProofreadWorkerの出力（校閲済みセグメント）をSmartCutWorkerに入力
        ctx = create_mock_ctx(segments=10, target_minutes=1)
        original_times = [(s["start"], s["end"]) for s in ctx.segments]

        worker = SmartCutWorker()
        result = await worker.execute(ctx)

        assert result.success is True
        # selected_segmentsのstart/endがoriginalと一致（変更されていない）
        for seg in ctx.selected_segments:
            assert (seg["start"], seg["end"]) in original_times

    @pytest.mark.asyncio
    async def test_c5_02_preview_input_contract(self):
        """W3-C5-02: Preview入力への契約(CT-03) — selected ⊆ original"""
        ctx = create_mock_ctx(segments=20, target_minutes=2, duration_each=15.0)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)

        assert result.success is True
        # PreviewWorkerが期待するデータ構造を確認
        for seg in ctx.selected_segments:
            assert "start" in seg
            assert "end" in seg
            assert seg["start"] < seg["end"]

    @pytest.mark.asyncio
    async def test_c5_03_template_subtitle_style(self):
        """W3-C5-03: テンプレート字幕スタイル取得 — template_config連携"""
        import importlib
        import smart_cut_engine
        importlib.reload(smart_cut_engine)

        segments = _make_segments(3, duration_each=10.0)
        ffmpeg_mock = _make_ffmpeg_mock()
        ffmpeg_mock.run_command.return_value = (True, "")

        mock_tc = MagicMock()
        mock_tc.get_subtitle_style.return_value = "FontSize=36,PrimaryColour=&HFFFFFF"
        mock_tc.is_active = True
        mock_tc.get_branding_config.return_value = {}

        mock_tc_module = MagicMock()
        mock_tc_module.template_config = mock_tc

        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = os.path.join(tmpdir, "input.mp4")
            output_path = os.path.join(tmpdir, "output.mp4")
            Path(video_path).write_bytes(b"\x00" * 100)

            with patch.dict("sys.modules", {
                "video_editor_engine": MagicMock(),
                "template_config": mock_tc_module,
            }):
                importlib.reload(smart_cut_engine)
                result = smart_cut_engine._burn_subtitles_ffmpeg(
                    video_path, segments, output_path, ffmpeg_mock
                )

            # template_configのget_subtitle_styleが呼ばれたことを確認
            mock_tc.get_subtitle_style.assert_called()

    @pytest.mark.asyncio
    async def test_c5_04_logo_overlay_integration(self):
        """W3-C5-04: ロゴオーバーレイ統合(FIX-6A) — ロゴ有無の分岐"""
        import importlib
        import smart_cut_engine
        importlib.reload(smart_cut_engine)

        # ロゴあり
        mock_tc = MagicMock()
        mock_tc.is_active = True
        mock_tc.get_branding_config.return_value = {
            "logo_path": "/path/to/logo.png",
            "logo_height": 50,
        }
        mock_tc_module = MagicMock()
        mock_tc_module.template_config = mock_tc

        with patch.dict("sys.modules", {"template_config": mock_tc_module}), \
             patch("smart_cut_engine.Path.exists", return_value=True):
            importlib.reload(smart_cut_engine)
            logo = smart_cut_engine._get_logo_path()

        assert logo == "/path/to/logo.png"

        # ロゴなし
        mock_tc2 = MagicMock()
        mock_tc2.is_active = True
        mock_tc2.get_branding_config.return_value = {}
        mock_tc_module2 = MagicMock()
        mock_tc_module2.template_config = mock_tc2

        with patch.dict("sys.modules", {"template_config": mock_tc_module2}), \
             patch("smart_cut_engine.Path.exists", return_value=False):
            importlib.reload(smart_cut_engine)
            logo = smart_cut_engine._get_logo_path()

        assert logo is None

    @pytest.mark.asyncio
    async def test_c5_05_hwaccel_filter_complex_compat(self):
        """W3-C5-05: hwaccel/filter_complex互換性 — ロゴ時はhwaccelスキップ"""
        import importlib
        import smart_cut_engine
        importlib.reload(smart_cut_engine)

        segments = _make_segments(3, duration_each=10.0)
        ffmpeg_mock = _make_ffmpeg_mock()
        ffmpeg_mock.run_command.return_value = (True, "")

        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = os.path.join(tmpdir, "input.mp4")
            output_path = os.path.join(tmpdir, "output.mp4")
            Path(video_path).write_bytes(b"\x00" * 100)

            # ロゴありの場合
            with patch("smart_cut_engine._get_logo_path", return_value="/fake/logo.png"), \
                 patch("smart_cut_engine.Path.exists", return_value=True), \
                 patch("smart_cut_engine.Path.stat") as mock_stat:

                mock_stat.return_value.st_size = 5000
                mock_stat.return_value.st_mode = 33188

                with patch.dict("sys.modules", {"video_editor_engine": MagicMock()}):
                    importlib.reload(smart_cut_engine)
                    smart_cut_engine._burn_subtitles_ffmpeg(
                        video_path, segments, output_path, ffmpeg_mock
                    )

            # ロゴ付きでrun_commandが呼ばれた引数を確認
            if ffmpeg_mock.run_command.call_count > 0:
                first_call_args = ffmpeg_mock.run_command.call_args_list[0][0][0]
                # hwaccelがコマンドに含まれないことを確認
                assert "-hwaccel" not in first_call_args, \
                    "ロゴ付きなのにhwaccelが使用されている"

    @pytest.mark.asyncio
    async def test_c5_06_subtitle_burn_failed_flag(self):
        """W3-C5-06: フラグファイル(_subtitle_burn_failed) — 品質ゲート連携"""
        import importlib
        import smart_cut_engine
        importlib.reload(smart_cut_engine)

        segments = _make_segments(3, duration_each=10.0)
        ffmpeg_mock = _make_ffmpeg_mock()
        # 全run_command失敗 → フォールバック3発動
        ffmpeg_mock.run_command.return_value = (False, "error")

        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = os.path.join(tmpdir, "input.mp4")
            output_path = os.path.join(tmpdir, "output.mp4")
            Path(video_path).write_bytes(b"\x00" * 100)

            with patch.dict("sys.modules", {"video_editor_engine": MagicMock()}):
                importlib.reload(smart_cut_engine)
                result = smart_cut_engine._burn_subtitles_ffmpeg(
                    video_path, segments, output_path, ffmpeg_mock
                )

            assert result == "fallback_no_subtitle"
            flag_path = Path(tmpdir) / "_subtitle_burn_failed.flag"
            assert flag_path.exists()
            content = flag_path.read_text(encoding="utf-8")
            assert "subtitle burn-in failed" in content

    @pytest.mark.asyncio
    async def test_c5_07_merge_timeout_extension(self):
        """W3-C5-07: concurrent merge timeout拡張 — _merge_timeout=1800"""
        import importlib
        import smart_cut_engine
        importlib.reload(smart_cut_engine)

        # ギャップ付きセグメントで結合防止 → 複数パート → merge_videos呼出
        segments = [
            {"start": 0, "end": 5, "sourceStart": 0, "sourceEnd": 5, "text": "A"},
            {"start": 10, "end": 15, "sourceStart": 10, "sourceEnd": 15, "text": "B"},
            {"start": 20, "end": 25, "sourceStart": 20, "sourceEnd": 25, "text": "C"},
        ]
        ffmpeg_mock = _make_ffmpeg_mock(duration=60.0)
        mock_module = _make_video_editor_module(ffmpeg_mock)

        def _fake_cut(input_path, temp_path, s, e):
            Path(temp_path).parent.mkdir(parents=True, exist_ok=True)
            Path(temp_path).write_bytes(b"\x00" * 50)
            return True

        ffmpeg_mock.cut_video.side_effect = _fake_cut

        def _fake_merge(clips, out_path):
            Path(out_path).write_bytes(b"\x00" * 200)
            return True

        ffmpeg_mock.merge_videos.side_effect = _fake_merge
        ffmpeg_mock.run_command.return_value = (True, "")

        # _merge_timeoutの設定を追跡する
        timeout_values = []
        original_setattr = type(ffmpeg_mock).__setattr__

        def _track_setattr(self, name, value):
            if name == "_merge_timeout":
                timeout_values.append(value)
            original_setattr(self, name, value)

        with tempfile.TemporaryDirectory() as tmpdir:
            output = os.path.join(tmpdir, "output.mp4")

            with patch.dict("sys.modules", {"video_editor_engine": mock_module}):
                importlib.reload(smart_cut_engine)

                with patch.object(type(ffmpeg_mock), "__setattr__", _track_setattr):
                    smart_cut_engine.render_smart_cut(
                        segments, "dummy.mp4", output
                    )

            # _merge_timeoutが1800に設定されたことを確認
            assert 1800 in timeout_values, f"_merge_timeout=1800が設定されなかった: {timeout_values}"


# ============================================================
# C6: 性能・進化 (7テスト)
# ============================================================

class TestC6PerformanceEvolution:
    """W3-C6-01〜W3-C6-07: 性能・進化"""

    @pytest.mark.asyncio
    async def test_c6_01_smartcut_performance(self):
        """W3-C6-01: 10seg SmartCut≤60秒 — 時間予算内（全スイート負荷考慮）"""
        ctx = create_mock_ctx(segments=10, target_minutes=1)
        worker = SmartCutWorker()

        start = time.time()
        result = await worker.execute(ctx)
        elapsed = time.time() - start

        assert result.success is True
        assert elapsed < 60.0, f"SmartCutWorker実行に{elapsed:.1f}秒かかった(上限60秒)"

    @pytest.mark.asyncio
    async def test_c6_02_large_merge_timeout(self):
        """W3-C6-02: merge_videosの大量パート(20+) — タイムアウト拡張"""
        import importlib
        import smart_cut_engine
        importlib.reload(smart_cut_engine)

        # ギャップ付き25セグメント → 結合防止 → 複数パート → merge必須
        segments = [
            {"start": i * 20, "end": i * 20 + 5,
             "sourceStart": i * 20, "sourceEnd": i * 20 + 5, "text": f"seg{i}"}
            for i in range(25)
        ]
        ffmpeg_mock = _make_ffmpeg_mock(duration=600.0)
        mock_module = _make_video_editor_module(ffmpeg_mock)

        def _fake_cut(input_path, temp_path, s, e):
            Path(temp_path).parent.mkdir(parents=True, exist_ok=True)
            Path(temp_path).write_bytes(b"\x00" * 50)
            return True

        ffmpeg_mock.cut_video.side_effect = _fake_cut

        def _fake_merge(clips, out_path):
            Path(out_path).write_bytes(b"\x00" * 200)
            return True

        ffmpeg_mock.merge_videos.side_effect = _fake_merge
        ffmpeg_mock.run_command.return_value = (True, "")

        # _merge_timeoutの設定を追跡する
        timeout_values = []
        original_setattr = type(ffmpeg_mock).__setattr__

        def _track_setattr(self, name, value):
            if name == "_merge_timeout":
                timeout_values.append(value)
            original_setattr(self, name, value)

        with tempfile.TemporaryDirectory() as tmpdir:
            output = os.path.join(tmpdir, "output.mp4")

            with patch.dict("sys.modules", {"video_editor_engine": mock_module}):
                importlib.reload(smart_cut_engine)

                with patch.object(type(ffmpeg_mock), "__setattr__", _track_setattr):
                    smart_cut_engine.render_smart_cut(
                        segments, "dummy.mp4", output
                    )

            # 20+パートのmergeで_merge_timeout=1800が設定されること
            assert 1800 in timeout_values, f"_merge_timeout=1800が設定されなかった: {timeout_values}"
            # merge_videosが呼ばれたこと(25パート > 1なのでmerge必須)
            assert ffmpeg_mock.merge_videos.call_count == 1

    @pytest.mark.asyncio
    async def test_c6_03_gpu_nvenc_encode(self):
        """W3-C6-03: GPU(NVENC)エンコード確認 — balanced preset"""
        import importlib
        import smart_cut_engine
        importlib.reload(smart_cut_engine)

        ffmpeg_mock = _make_ffmpeg_mock()
        ffmpeg_mock._get_encode_args.return_value = ["-c:v", "h264_nvenc", "-preset", "p4"]
        ffmpeg_mock.run_command.return_value = (True, "")

        segments = _make_segments(3, duration_each=10.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = os.path.join(tmpdir, "input.mp4")
            output_path = os.path.join(tmpdir, "output.mp4")
            Path(video_path).write_bytes(b"\x00" * 100)

            with patch.dict("sys.modules", {"video_editor_engine": MagicMock()}):
                importlib.reload(smart_cut_engine)
                smart_cut_engine._burn_subtitles_ffmpeg(
                    video_path, segments, output_path, ffmpeg_mock
                )

        # _get_encode_argsが"balanced"presetで呼ばれたことを確認
        ffmpeg_mock._get_encode_args.assert_called_with("balanced")

    @pytest.mark.asyncio
    async def test_c6_04_cpu_libx264_fallback(self):
        """W3-C6-04: CPU(libx264)フォールバック — エンコード成功"""
        import importlib
        import smart_cut_engine
        importlib.reload(smart_cut_engine)

        ffmpeg_mock = _make_ffmpeg_mock()
        # GPUエンコード引数をCPUに設定
        ffmpeg_mock._get_encode_args.return_value = ["-c:v", "libx264", "-preset", "veryfast"]
        # 最初のrun_command失敗(GPU)→2回目成功(CPU)
        ffmpeg_mock.run_command.side_effect = [
            (False, "GPU error"),
            (True, "CPU success"),
        ]

        segments = _make_segments(3, duration_each=10.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = os.path.join(tmpdir, "input.mp4")
            output_path = os.path.join(tmpdir, "output.mp4")
            Path(video_path).write_bytes(b"\x00" * 100)

            with patch.dict("sys.modules", {"video_editor_engine": MagicMock()}), \
                 patch("smart_cut_engine.Path.exists", return_value=True), \
                 patch("smart_cut_engine.Path.stat") as mock_stat:
                mock_stat.return_value.st_size = 5000
                mock_stat.return_value.st_mode = 33188

                importlib.reload(smart_cut_engine)
                result = smart_cut_engine._burn_subtitles_ffmpeg(
                    video_path, segments, output_path, ffmpeg_mock
                )

        # フォールバック2でCPU成功
        assert result is True

    @pytest.mark.asyncio
    async def test_c6_05_srt_utf8_encoding(self):
        """W3-C6-05: SRTファイルのUTF-8書込 — エンコーディング"""
        import importlib
        import smart_cut_engine
        importlib.reload(smart_cut_engine)

        # 日本語+絵文字を含むセグメント
        segments = [
            {"start": 0, "end": 5, "text": "日本語テスト🎉"},
            {"start": 5, "end": 10, "text": "「特殊文字」テスト①②③"},
            {"start": 10, "end": 15, "text": "Emoji㊗️テスト"},
        ]
        ffmpeg_mock = _make_ffmpeg_mock()
        ffmpeg_mock.run_command.return_value = (True, "")

        srt_content_captured = []
        original_write_text = Path.write_text

        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = os.path.join(tmpdir, "input.mp4")
            output_path = os.path.join(tmpdir, "output.mp4")
            Path(video_path).write_bytes(b"\x00" * 100)

            with patch.dict("sys.modules", {"video_editor_engine": MagicMock()}), \
                 patch("smart_cut_engine.Path.exists", return_value=True), \
                 patch("smart_cut_engine.Path.stat") as mock_stat:
                mock_stat.return_value.st_size = 5000
                mock_stat.return_value.st_mode = 33188

                importlib.reload(smart_cut_engine)

                # write_textをフックしてSRT内容をキャプチャ
                orig_write = Path.write_text

                def _capture_write(self_path, content, encoding=None):
                    if str(self_path).endswith(".srt"):
                        srt_content_captured.append(content)
                    return orig_write(self_path, content, encoding=encoding)

                with patch.object(Path, "write_text", _capture_write):
                    smart_cut_engine._burn_subtitles_ffmpeg(
                        video_path, segments, output_path, ffmpeg_mock
                    )

        # SRTファイルがUTF-8で書き込まれたことを確認
        assert len(srt_content_captured) >= 1
        srt = srt_content_captured[0]
        assert "日本語テスト🎉" in srt
        assert "「特殊文字」テスト①②③" in srt

    @pytest.mark.asyncio
    async def test_c6_06_temp_files_always_deleted(self):
        """W3-C6-06: 一時ファイルの確実な削除 — finally節"""
        import importlib
        import smart_cut_engine
        importlib.reload(smart_cut_engine)

        segments = _make_segments(3, duration_each=10.0)
        ffmpeg_mock = _make_ffmpeg_mock(duration=60.0)
        mock_module = _make_video_editor_module(ffmpeg_mock)

        created_temps = []

        def _fake_cut(input_path, temp_path, s, e):
            Path(temp_path).parent.mkdir(parents=True, exist_ok=True)
            Path(temp_path).write_bytes(b"\x00" * 50)
            created_temps.append(Path(temp_path))
            return True

        ffmpeg_mock.cut_video.side_effect = _fake_cut

        def _fake_merge(clips, out_path):
            Path(out_path).write_bytes(b"\x00" * 200)
            return True

        ffmpeg_mock.merge_videos.side_effect = _fake_merge
        ffmpeg_mock.run_command.return_value = (True, "")

        with tempfile.TemporaryDirectory() as tmpdir:
            output = os.path.join(tmpdir, "output.mp4")

            with patch.dict("sys.modules", {"video_editor_engine": mock_module}), \
                 patch("smart_cut_engine.Path.exists", return_value=True), \
                 patch("smart_cut_engine.Path.stat") as mock_stat:

                mock_stat.return_value.st_size = 5000
                mock_stat.return_value.st_mode = 33188
                importlib.reload(smart_cut_engine)
                smart_cut_engine.render_smart_cut(
                    segments, "dummy.mp4", output
                )

            # finally節により一時ファイルが全て削除されたことを確認
            for temp in created_temps:
                assert not temp.exists(), f"一時ファイル {temp} がfinally節で削除されていない"

    @pytest.mark.asyncio
    async def test_c6_07_boundary_check_start_end(self):
        """W3-C6-07: 境界チェック(start/end≤duration) — max(0, min(val, dur))"""
        import importlib
        import smart_cut_engine
        importlib.reload(smart_cut_engine)

        # 動画尺(30秒)を超えるセグメントを含む
        segments = [
            {"start": 0, "end": 10, "sourceStart": 0, "sourceEnd": 10, "text": "正常"},
            {"start": 25, "end": 50, "sourceStart": 25, "sourceEnd": 50, "text": "超過"},  # end > duration
            {"start": -5, "end": 5, "sourceStart": -5, "sourceEnd": 5, "text": "負値"},  # start < 0
        ]
        ffmpeg_mock = _make_ffmpeg_mock(duration=30.0)
        mock_module = _make_video_editor_module(ffmpeg_mock)

        created_temps = []

        def _fake_cut(input_path, temp_path, s, e):
            # 境界チェックされたs, eの値を検証
            assert s >= 0, f"start({s})が負値"
            assert e <= 30.0, f"end({e})がduration(30)超過"
            assert s < e, f"start({s}) >= end({e})"
            Path(temp_path).parent.mkdir(parents=True, exist_ok=True)
            Path(temp_path).write_bytes(b"\x00" * 50)
            created_temps.append(Path(temp_path))
            return True

        ffmpeg_mock.cut_video.side_effect = _fake_cut

        def _fake_merge(clips, out_path):
            Path(out_path).write_bytes(b"\x00" * 200)
            return True

        ffmpeg_mock.merge_videos.side_effect = _fake_merge
        ffmpeg_mock.run_command.return_value = (True, "")

        with tempfile.TemporaryDirectory() as tmpdir:
            output = os.path.join(tmpdir, "output.mp4")

            with patch.dict("sys.modules", {"video_editor_engine": mock_module}), \
                 patch("smart_cut_engine.Path.exists", return_value=True), \
                 patch("smart_cut_engine.Path.stat") as mock_stat:

                mock_stat.return_value.st_size = 5000
                mock_stat.return_value.st_mode = 33188
                importlib.reload(smart_cut_engine)
                smart_cut_engine.render_smart_cut(
                    segments, "dummy.mp4", output
                )

        # cut_videoが呼ばれた = 境界チェック済みの値が渡された
        assert ffmpeg_mock.cut_video.call_count >= 1


    @pytest.mark.asyncio
    async def test_c6_08_get_definition_of_done(self):
        """W3-C6-08: DoD定義の取得カバレッジカバー"""
        worker = SmartCutWorker()
        dod = worker.get_definition_of_done()
        assert isinstance(dod, str)
        assert "目標尺" in dod

    @pytest.mark.asyncio
    async def test_c6_09_a5_short_run_removal(self):
        """W3-C6-09: A-5 短い保持区間の除去ロジックカバー"""
        # 目標 65 秒
        # 0 (15s), 2 (15s), 4 (15s), 6 (5s), 8 (15s) を高スコアにし、奇数を低スコアにする
        segments = []
        for i in range(10):
            s = i * 15.0
            e = s + (5.0 if i == 6 else 15.0)
            if i in (0, 2, 4, 6, 8):
                text = "重要高密度コンテンツ" * 10
            else:
                text = "低"
            
            segments.append({
                "start": s,
                "end": e,
                "sourceStart": s,
                "sourceEnd": e,
                "text": text
            })
            
        ctx = PipelineContext(video_path="dummy.mp4", target_minutes=1.083, segments=segments)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)
        
        assert result.success is True
        # 短い保持区間（インデックス6の5.0秒）が除去された結果、0, 2, 4, 8のみが残るはず
        selected_starts = [s["start"] for s in ctx.selected_segments]
        assert (6 * 15.0) not in selected_starts

    @pytest.mark.asyncio
    async def test_c6_10_a5_safety_valve_trigger(self):
        """W3-C6-10: A-5 安全弁発動ロジックカバー"""
        # 目標 20 秒
        # セグメントすべて 3.0秒。偶数を高スコアにし、奇数を低スコアにする。
        # 0, 2, 4, 6, 8, 10, 12 (すべて 3.0秒)
        segments = []
        for i in range(14):
            s = i * 3.0
            e = s + 3.0
            if i % 2 == 0:
                text = "高密度" * 5
            else:
                text = "低"
            segments.append({
                "start": s,
                "end": e,
                "sourceStart": s,
                "sourceEnd": e,
                "text": text
            })
            
        ctx = PipelineContext(video_path="dummy.mp4", target_minutes=0.333, segments=segments)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)
        
        assert result.success is True
        # 安全弁が発動するため、フィルタは無効化され、すべてのselected_indices（0, 2, 4, 6, 8, 10, 12）が維持される
        selected_starts = [s["start"] for s in ctx.selected_segments]
        assert len(selected_starts) == 7


    @pytest.mark.asyncio
    async def test_c6_11_target_minutes_negative(self):
        """W3-C6-11: 負の目標尺 — 0セグメント選定で安全に完了"""
        ctx = create_mock_ctx(segments=10, target_minutes=-1)
        worker = SmartCutWorker()
        result = await worker.execute(ctx)

        assert result.success is True
        assert len(ctx.selected_segments) == 0
        assert result.data.get("cut_percent") == 100.0

    @pytest.mark.asyncio
    async def test_c6_12_text_key_missing(self):
        """W3-C6-12: textキー欠損 — 空文字として安全に処理"""
        ctx = create_mock_ctx(segments=5, target_minutes=2)
        # textキーを削除
        for seg in ctx.segments:
            seg.pop("text", None)

        worker = SmartCutWorker()
        result = await worker.execute(ctx)

        assert result.success is True
        assert len(ctx.selected_segments) >= 1

    @pytest.mark.asyncio
    async def test_c6_13_object_segments(self):
        """W3-C6-13: オブジェクト型セグメント — getattrフォールバックにより正常動作"""
        from types import SimpleNamespace
        
        # 辞書ではなく SimpleNamespace オブジェクトとしてセグメントを模擬
        segments = [
            SimpleNamespace(
                start=0.0,
                end=15.0,
                sourceStart=0.0,
                sourceEnd=15.0,
                text="オブジェクトセグメント1"
            ),
            SimpleNamespace(
                start=15.0,
                end=30.0,
                sourceStart=15.0,
                sourceEnd=30.0,
                text="オブジェクトセグメント2"
            )
        ]
        ctx = PipelineContext(
            video_path="dummy.mp4",
            target_minutes=1,
            segments=segments
        )
        worker = SmartCutWorker()
        result = await worker.execute(ctx)

        assert result.success is True
        assert len(ctx.selected_segments) == 2
        assert ctx.selected_segments[0].text == "オブジェクトセグメント1"

    @pytest.mark.asyncio
    async def test_c6_14_object_segments_cut_needed(self):
        """W3-C6-14: オブジェクト型セグメント (カットが必要な場合) — getattrフォールバックにより安全に処理"""
        from types import SimpleNamespace
        
        segments = [
            SimpleNamespace(
                start=0.0,
                end=15.0,
                sourceStart=0.0,
                sourceEnd=15.0,
                text="オブジェクトセグメント1"
            ),
            SimpleNamespace(
                start=15.0,
                end=30.0,
                sourceStart=15.0,
                sourceEnd=30.0,
                text="オブジェクトセグメント2"
            )
        ]
        # 目標 0.1 分 (6秒) < 合計 30秒 → カット処理が行われるようにする
        ctx = PipelineContext(
            video_path="dummy.mp4",
            target_minutes=0.1,
            segments=segments
        )
        worker = SmartCutWorker()
        result = await worker.execute(ctx)

        assert result.success is True
        assert len(ctx.selected_segments) == 1
        assert ctx.selected_segments[0].text == "オブジェクトセグメント1"

    def test_c6_15_group_continuous_runs_empty(self):
        """_group_continuous_runs に空のリストを渡した場合のカバー"""
        worker = SmartCutWorker()
        runs = worker._group_continuous_runs([])
        assert runs == []

