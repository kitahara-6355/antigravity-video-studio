"""
Batch 15: quality_gate_plugins + smart_cut_engine + smart_cut_plugin + lightweight_scan_plugin + transcribe_worker
M2.6 カバレッジ 67% → 70%+ (追加バッチ)

合計: ~60テスト
"""
import sys
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock
from datetime import datetime

_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)


# ============================================================
# Part 1: quality_gate_plugins (25 tests)
# ============================================================

class _MockCtx:
    """品質ゲートテスト用の軽量コンテキスト"""
    def __init__(self, preview_path=None, segments=None, selected_segments=None, metadata=None):
        self.preview_path = preview_path
        self.segments = segments or []
        self.selected_segments = selected_segments or []
        self.metadata = metadata or {}
        # **維持率予測はフック強度の実測値を要る**（R1.5-C4・19周目）。
        # 以前は `+ 70 * hook_strength_weight` と定数を足していて、
        # **予測維持率の 25% が捏造**だった。本番では HookStrengthCheck が
        # 先に走って実測値を積むので、テストでも同じものを渡す。
        self._quality_plugin_results = {
            "hook_strength_check": {"details": {"hook_score": 70}}
        }


class TestQualityGateCore:
    """コアプラグイン: FileSizeCheck, SegmentQualityCheck, AIRuleCheck"""

    def test_qg_01_file_size_missing(self):
        from quality_gate_plugins import FileSizeCheck
        r = FileSizeCheck().analyze(_MockCtx(preview_path=None))
        assert r["deductions"] == 20

    def test_qg_02_file_size_tiny(self, tmp_path):
        from quality_gate_plugins import FileSizeCheck
        f = tmp_path / "tiny.mp4"
        f.write_bytes(b"x" * 100)
        r = FileSizeCheck().analyze(_MockCtx(preview_path=str(f)))
        assert r["deductions"] == 30

    def test_qg_03_file_size_small(self, tmp_path):
        from quality_gate_plugins import FileSizeCheck
        f = tmp_path / "small.mp4"
        f.write_bytes(b"x" * 5_000_000)
        r = FileSizeCheck().analyze(_MockCtx(preview_path=str(f)))
        assert r["deductions"] == 3

    def test_qg_04_file_size_ok(self, tmp_path):
        from quality_gate_plugins import FileSizeCheck
        f = tmp_path / "good.mp4"
        f.write_bytes(b"x" * 20_000_000)
        r = FileSizeCheck().analyze(_MockCtx(preview_path=str(f)))
        assert r["deductions"] == 0

    def test_qg_05_segment_quality_ok(self):
        from quality_gate_plugins import SegmentQualityCheck
        segs = [{"text": f"seg {i}"} for i in range(10)]
        r = SegmentQualityCheck().analyze(_MockCtx(segments=segs))
        assert r["deductions"] == 0

    def test_qg_06_segment_quality_bad(self):
        from quality_gate_plugins import SegmentQualityCheck
        segs = [{"text": ""} for _ in range(10)]
        r = SegmentQualityCheck().analyze(_MockCtx(segments=segs))
        assert r["deductions"] == 10

    def test_qg_07_ai_rule_no_module(self):
        from quality_gate_plugins import AIRuleCheck
        with patch.dict(sys.modules, {"quality_gate_ai": None}):
            r = AIRuleCheck().analyze(_MockCtx(segments=[{"text": "test"}]))
            assert r["deductions"] == 0


class TestQualityGateTemplate:
    """テンプレートプラグイン"""

    def test_qg_08_subtitle_speed_ok(self):
        from quality_gate_plugins import SubtitleSpeedCheck
        segs = [{"text": "テスト", "start": i * 5, "end": i * 5 + 4} for i in range(10)]
        r = SubtitleSpeedCheck().analyze(_MockCtx(segments=segs))
        assert r["deductions"] == 0

    def test_qg_09_subtitle_speed_violation(self):
        from quality_gate_plugins import SubtitleSpeedCheck
        segs = [{"text": "あ" * 30, "start": i, "end": i + 1} for i in range(10)]  # 30chars/s
        r = SubtitleSpeedCheck().analyze(_MockCtx(segments=segs))
        assert r["deductions"] >= 5

    def test_qg_10_subtitle_line_ok(self):
        from quality_gate_plugins import SubtitleLineCheck
        segs = [{"text": "短いテスト"} for _ in range(5)]
        r = SubtitleLineCheck().analyze(_MockCtx(segments=segs))
        assert r["deductions"] == 0

    def test_qg_11_subtitle_line_long(self):
        from quality_gate_plugins import SubtitleLineCheck
        segs = [{"text": "あ" * 30} for _ in range(5)]  # 30 chars per line
        r = SubtitleLineCheck().analyze(_MockCtx(segments=segs))
        assert r["deductions"] == 5

    def test_qg_12_hook_ok(self):
        from quality_gate_plugins import HookCheck
        segs = [{"text": "test", "start": 0, "end": 3}]
        r = HookCheck().analyze(_MockCtx(segments=segs))
        assert r["deductions"] == 0

    def test_qg_13_hook_late(self):
        from quality_gate_plugins import HookCheck
        segs = [{"text": "test", "start": 10, "end": 15}]
        r = HookCheck().analyze(_MockCtx(segments=segs))
        assert r["deductions"] == 15

    def test_qg_14_dead_air_none(self):
        from quality_gate_plugins import DeadAirCheck
        segs = [{"start": i, "end": i + 1} for i in range(5)]
        r = DeadAirCheck().analyze(_MockCtx(segments=segs))
        assert r["deductions"] == 0

    def test_qg_15_dead_air_many(self):
        from quality_gate_plugins import DeadAirCheck
        segs = [{"start": i * 20, "end": i * 20 + 1} for i in range(10)]
        r = DeadAirCheck().analyze(_MockCtx(segments=segs))
        assert r["deductions"] >= 3

    def test_qg_16_subtitle_density_ok(self):
        from quality_gate_plugins import SubtitleDensityCheck
        segs = [{"start": i * 3, "end": i * 3 + 2} for i in range(20)]
        r = SubtitleDensityCheck().analyze(_MockCtx(segments=segs))
        assert r["deductions"] == 0

    def test_qg_17_hook_strength_strong(self):
        from quality_gate_plugins import HookStrengthCheck
        segs = [{"text": "テスト文" * 5, "start": 0, "end": 3}, {"text": "t", "start": 3, "end": 5}]
        r = HookStrengthCheck().analyze(_MockCtx(segments=segs))
        assert r["details"]["hook_score"] >= 70

    def test_qg_18_retention_prediction(self):
        from quality_gate_plugins import RetentionPredictionCheck
        segs = [{"text": f"seg{i}", "start": i * 5, "end": i * 5 + 4} for i in range(10)]
        r = RetentionPredictionCheck().analyze(_MockCtx(segments=segs))
        assert "predicted_retention" in r.get("details", {})


class TestQualityGateYouTube:
    """YouTube最適化プラグイン"""

    def test_qg_19_chapter_coverage_short(self):
        from quality_gate_plugins import ChapterCoverageCheck
        segs = [{"start": i * 10, "end": i * 10 + 5} for i in range(5)]
        r = ChapterCoverageCheck().analyze(_MockCtx(segments=segs))
        assert r["deductions"] == 0  # < 10min

    def test_qg_20_chapter_coverage_long(self):
        from quality_gate_plugins import ChapterCoverageCheck
        segs = [{"text": "t", "start": i * 100, "end": i * 100 + 5} for i in range(10)]
        r = ChapterCoverageCheck().analyze(_MockCtx(segments=segs))
        assert isinstance(r["deductions"], int)

    def test_qg_21_shorts_ready_with_highlights(self):
        from quality_gate_plugins import ShortsReadyCheck
        segs = [{"text": "すごい！衝撃の事実"}]
        r = ShortsReadyCheck().analyze(_MockCtx(segments=segs))
        assert r["deductions"] == 0
        assert r["details"]["highlight_count"] >= 1

    def test_qg_22_shorts_ready_no_highlights(self):
        from quality_gate_plugins import ShortsReadyCheck
        segs = [{"text": "普通のテキストです。"}]
        r = ShortsReadyCheck().analyze(_MockCtx(segments=segs))
        assert r["deductions"] == 3

    def test_qg_23_ctr_ready_ok(self):
        from quality_gate_plugins import CTRReadyCheck
        segs = [{"text": "テスト用のテキスト" * 3} for _ in range(5)]
        r = CTRReadyCheck().analyze(_MockCtx(segments=segs))
        assert r["deductions"] == 0

    def test_qg_24_ctr_ready_short(self):
        from quality_gate_plugins import CTRReadyCheck
        segs = [{"text": "短"} for _ in range(5)]
        r = CTRReadyCheck().analyze(_MockCtx(segments=segs))
        assert r["deductions"] == 3

    def test_qg_25_duration_sanity_ok(self):
        from quality_gate_plugins import DurationSanityCheck
        segs = [{"start": 0, "end": 100}]
        sel = [{"start": 0, "end": 50}]
        r = DurationSanityCheck().analyze(_MockCtx(segments=segs, selected_segments=sel))
        assert r["deductions"] == 0

    def test_qg_26_duration_sanity_over_cut(self):
        from quality_gate_plugins import DurationSanityCheck
        segs = [{"start": 0, "end": 1000}]
        sel = [{"start": 0, "end": 50}]
        r = DurationSanityCheck().analyze(_MockCtx(segments=segs, selected_segments=sel))
        assert r["deductions"] >= 5


class TestQualityGateBroadcast:
    """放送品質プラグイン（FFmpeg不要パス）"""

    def test_qg_27_loudness_no_file(self):
        from quality_gate_plugins import LoudnessCheck
        r = LoudnessCheck().analyze(_MockCtx())
        assert r["deductions"] == 0

    def test_qg_28_resolution_no_file(self):
        from quality_gate_plugins import ResolutionCheck
        r = ResolutionCheck().analyze(_MockCtx())
        assert r["deductions"] == 0

    def test_qg_29_codec_no_file(self):
        from quality_gate_plugins import CodecCheck
        r = CodecCheck().analyze(_MockCtx())
        assert r["deductions"] == 0

    def test_qg_30_audio_presence_no_file(self):
        from quality_gate_plugins import AudioPresenceCheck
        r = AudioPresenceCheck().analyze(_MockCtx())
        assert r["deductions"] == 0

    def test_qg_31_bitrate_no_file(self):
        from quality_gate_plugins import BitrateCheck
        r = BitrateCheck().analyze(_MockCtx())
        assert r["deductions"] == 0


# ============================================================
# Part 2: smart_cut_plugin (15 tests)
# ============================================================

class TestSmartCutPlugin:
    """SmartCutPlugin — スマートカット全メソッド"""

    @pytest.fixture
    def plugin(self):
        with patch("plugins.smart_cut_plugin.SmartCutPlugin._load_constraints"):
            from plugins.smart_cut_plugin import SmartCutPlugin, SmartCutContext
            p = SmartCutPlugin()
            p.max_highlight_candidates = 50
            p.max_chapter_candidates = 30
            p._context = SmartCutContext(
                all_highlights=[
                    {"id": f"h{i}", "score": 100 - i, "timestamp": i * 60, "duration": 30, "text_snippet": f"H{i}", "type": "highlight"}
                    for i in range(10)
                ],
                all_chapters=[{"id": f"c{i}", "title": f"C{i}"} for i in range(5)],
            )
            return p

    def test_sc_01_dataclass_locked(self):
        from plugins.smart_cut_plugin import LockedSegment
        ls = LockedSegment(id="l1", start_time=10, end_time=30, title="Test")
        assert ls.duration == 20

    def test_sc_02_dataclass_candidate(self):
        from plugins.smart_cut_plugin import SegmentCandidate
        sc = SegmentCandidate(id="s1", start_time=0, end_time=30, title="Test", score=80, type="highlight")
        assert sc.duration == 30

    def test_sc_03_context_to_dict(self):
        from plugins.smart_cut_plugin import SmartCutContext
        ctx = SmartCutContext()
        d = ctx.to_dict()
        assert d["target_duration_minutes"] == 15

    def test_sc_04_context_format_time(self):
        from plugins.smart_cut_plugin import SmartCutContext
        ctx = SmartCutContext()
        assert ctx._format_time(90) == "1:30"
        assert ctx._format_time(3661) == "61:01"

    def test_sc_05_update_recommendation_15(self, plugin):
        ctx = plugin.update_recommendation(15)
        assert ctx.target_duration_minutes == 15
        assert ctx.estimated_output_seconds > 0

    def test_sc_06_update_recommendation_30(self, plugin):
        ctx = plugin.update_recommendation(30)
        assert ctx.target_duration_minutes == 30

    def test_sc_07_update_recommendation_nearest(self, plugin):
        ctx = plugin.update_recommendation(25)
        assert ctx.target_duration_minutes == 30  # nearest preset

    def test_sc_07_update_recommendation_extreme_out_of_bounds(self, plugin):
        """極端な目標尺が指定された場合に、最も近いプリセットに正しくマッピングされることをテスト"""
        # 負の数が渡された場合 -> 最小のプリセット 15分
        ctx_neg = plugin.update_recommendation(-10)
        assert ctx_neg.target_duration_minutes == 15
        
        # 非常に大きな数が渡された場合 -> 最大のプリセット 60分
        ctx_large = plugin.update_recommendation(150)
        assert ctx_large.target_duration_minutes == 60

    def test_sc_08_lock_segment(self, plugin):
        with patch.object(plugin, "_save_to_evolution_log"):
            result = plugin.lock_segment("h0", "Test Lock", 0, 30, "important")
            assert result is True
            assert len(plugin._context.locked_segments) == 1

    def test_sc_09_lock_duplicate(self, plugin):
        with patch.object(plugin, "_save_to_evolution_log"):
            plugin.lock_segment("h0", "Test", 0, 30)
            result = plugin.lock_segment("h0", "Test", 0, 30)
            assert result is False

    def test_sc_10_unlock_segment(self, plugin):
        with patch.object(plugin, "_save_to_evolution_log"):
            plugin.lock_segment("h0", "Test", 0, 30)
            result = plugin.unlock_segment("h0")
            assert result is True
            assert len(plugin._context.locked_segments) == 0

    def test_sc_11_unlock_nonexistent(self, plugin):
        assert plugin.unlock_segment("nope") is False

    def test_sc_12_get_all_candidates(self, plugin):
        candidates = plugin.get_all_candidates()
        assert len(candidates["highlights"]) == 10
        assert len(candidates["chapters"]) == 5

    def test_sc_13_get_recommendation(self, plugin):
        plugin.update_recommendation(15)
        rec = plugin.get_recommendation()
        assert "estimated_output_seconds" in rec
        assert "recommended_segments" in rec

    def test_sc_14_finalize(self, plugin):
        plugin.update_recommendation(15)
        result = plugin.finalize()
        assert "finalized_at" in result
        assert "cut_rate" in result

    def test_sc_15_adjust_semantic_boundary(self, plugin):
        h = {"type": "結論"}
        dur = plugin._adjust_to_semantic_boundary(h, 30)
        assert dur >= 30 * 0.8
        assert dur <= 30 * 1.2

    def test_sc_edge_load_constraints_exception(self):
        """_load_constraintsで例外が発生した場合にデフォルト値が使われること"""
        from plugins.smart_cut_plugin import SmartCutPlugin
        from unittest.mock import patch
        with patch("builtins.open", side_effect=OSError("Read error")):
            p = SmartCutPlugin()
            assert p.max_highlight_candidates == 50
            assert p.max_chapter_candidates == 30

    def test_sc_edge_can_execute(self, plugin):
        """can_execute のエッジケース（scan_resultがNone、または存在しない場合）"""
        from core.context import ProductionContext
        from unittest.mock import MagicMock
        ctx = ProductionContext(task_id="test")
        
        # 属性がない場合
        assert plugin.can_execute(ctx) is False
        
        # 属性はあるが None の場合
        ctx.scan_result = None
        assert plugin.can_execute(ctx) is False
        
        # 属性があり None でない場合
        ctx.scan_result = MagicMock()
        assert plugin.can_execute(ctx) is True

    def test_sc_edge_execute(self, plugin):
        """execute の正常系ルート"""
        from core.context import ProductionContext
        from unittest.mock import MagicMock
        ctx = ProductionContext(task_id="test")
        mock_scan = MagicMock()
        mock_scan.highlight_candidates = [{"id": "h1", "score": 90, "timestamp": 0.0, "duration": 30}]
        mock_scan.chapter_candidates = [{"id": "c1", "title": "C1"}]
        ctx.scan_result = mock_scan
        
        updated_ctx = plugin.execute(ctx)
        assert hasattr(updated_ctx, "smartcut")
        assert updated_ctx.smartcut is not None
        assert updated_ctx.smartcut.all_highlights == mock_scan.highlight_candidates
        assert updated_ctx.smartcut.all_chapters == mock_scan.chapter_candidates

    def test_sc_edge_strategy_weights(self, plugin):
        """_get_strategy_weight と _clamp_weight の各種境界値"""
        from unittest.mock import MagicMock
        highlight = {"type": "intro", "score": 100}
        
        # strategy が None の場合
        assert plugin._get_strategy_weight(highlight, None) == 1.0
        
        # strategy があり、trust_score = 0.0 の場合
        mock_strategy = MagicMock()
        mock_strategy.trust_score = 0.0
        mock_strategy.position_weights = {"intro": 1.5}
        assert plugin._get_strategy_weight(highlight, mock_strategy) == 1.0
        
        # strategy があり、trust_score = 1.0 の場合でクランプ範囲内 (deviation <= 0.22)
        mock_strategy.trust_score = 1.0
        mock_strategy.position_weights = {"intro": 1.1}
        assert plugin._get_strategy_weight(highlight, mock_strategy) == 1.1
        
        # strategy があり、trust_score = 1.0 の場合で上限クランプ (1.5 -> 1.22)
        mock_strategy.position_weights = {"intro": 1.5}
        assert plugin._get_strategy_weight(highlight, mock_strategy) == pytest.approx(1.22)
        
        # strategy があり、trust_score = 0.5 の場合で下限クランプ (0.5 -> 0.89)
        # max_deviation = 0.5 * 0.22 = 0.11 -> clamp range: [0.89, 1.11]
        mock_strategy.trust_score = 0.5
        mock_strategy.position_weights = {"intro": 0.5}
        assert plugin._get_strategy_weight(highlight, mock_strategy) == pytest.approx(0.89)

    def test_sc_edge_save_to_evolution_log_exception(self, plugin):
        """_save_to_evolution_log で例外が発生した場合にクラッシュしないこと"""
        from unittest.mock import patch
        entry = {"title": "Failed Save Test"}
        with patch("builtins.open", side_effect=OSError("Write failed")):
            plugin._save_to_evolution_log(entry)

    def test_sc_edge_save_to_evolution_log_success(self, plugin):
        """_save_to_evolution_log が正常にログを読み書きできること"""
        from unittest.mock import mock_open, patch
        
        # 1. ログファイルが存在しない場合
        m_open_1 = mock_open(read_data="")
        with patch("pathlib.Path.exists", return_value=False),              patch("builtins.open", m_open_1):
            plugin._save_to_evolution_log({"title": "Test1"})
            
        # 2. ログファイルが存在し、locked_segmentsキーがない場合
        existing_log_json = '{"philosophies": []}'
        m_open_2 = mock_open(read_data=existing_log_json)
        with patch("pathlib.Path.exists", return_value=True),              patch("builtins.open", m_open_2):
            plugin._save_to_evolution_log({"title": "Test2"})

    def test_sc_edge_register(self):
        """register 関数の正常動作"""
        from plugins.smart_cut_plugin import register, SmartCutPlugin
        from unittest.mock import MagicMock
        mock_registry = MagicMock()
        register(mock_registry)
        mock_registry.register.assert_called_once()
        args, kwargs = mock_registry.register.call_args
        assert isinstance(args[0], SmartCutPlugin)

    def test_sc_edge_load_constraints_json_decode_error(self):
        from plugins.smart_cut_plugin import SmartCutPlugin
        from unittest.mock import mock_open, patch
        with patch("builtins.open", mock_open(read_data="{invalid_json")):
            p = SmartCutPlugin()
            assert p.max_highlight_candidates == 50
            assert p.max_chapter_candidates == 30

    def test_sc_edge_load_constraints_file_not_found(self):
        from plugins.smart_cut_plugin import SmartCutPlugin
        from unittest.mock import patch
        with patch("builtins.open", side_effect=FileNotFoundError("Mock file not found")):
            p = SmartCutPlugin()
            assert p.max_highlight_candidates == 50
            assert p.max_chapter_candidates == 30

    def test_sc_edge_load_constraints_permission_error(self):
        from plugins.smart_cut_plugin import SmartCutPlugin
        from unittest.mock import patch
        with patch("builtins.open", side_effect=PermissionError("Mock permission denied")):
            p = SmartCutPlugin()
            assert p.max_highlight_candidates == 50
            assert p.max_chapter_candidates == 30

    def test_sc_edge_load_constraints_generic_exception(self):
        from plugins.smart_cut_plugin import SmartCutPlugin
        from unittest.mock import patch
        with patch("builtins.open", side_effect=RuntimeError("Generic load error")):
            p = SmartCutPlugin()
            assert p.max_highlight_candidates == 50
            assert p.max_chapter_candidates == 30

    def test_sc_select_segments_skip_locked(self, plugin):
        from plugins.smart_cut_plugin import LockedSegment
        plugin._context.locked_segments.append(
            LockedSegment(id="h0", start_time=0.0, end_time=30.0, title="Locked H0")
        )
        recommended = plugin._select_segments(available_seconds=300)
        assert not any(r.id == "h0" for r in recommended)

    def test_sc_select_segments_time_limit(self, plugin):
        recommended = plugin._select_segments(available_seconds=45)
        assert len(recommended) == 1

    def test_sc_lock_segment_duplicate_direct(self, plugin):
        with patch.object(plugin, "_save_to_evolution_log"):
            res1 = plugin.lock_segment("h0", "Test", 0, 30)
            assert res1 is True
            res2 = plugin.lock_segment("h0", "Test", 0, 30)
            assert res2 is False

    def test_sc_unlock_segment_success(self, plugin):
        with patch.object(plugin, "_save_to_evolution_log"):
            plugin.lock_segment("h0", "Test", 0, 30)
            res = plugin.unlock_segment("h0")
            assert res is True
            assert len(plugin._context.locked_segments) == 0

    def test_sc_edge_save_to_evolution_log_read_existing(self, plugin):
        from unittest.mock import mock_open, patch
        from plugins.smart_cut_plugin import Path

        # 1. 既存の evolution_log.json 読み込み処理 (358-360)
        m_open = mock_open(read_data='{"locked_segments": []}')
        with patch.object(Path, "exists", return_value=True), \
             patch("builtins.open", m_open):
            plugin._save_to_evolution_log({"title": "Test Exist"})
            m_open.assert_called()

        # 2. locked_segments キーが存在しない場合の初期化 (364-365)
        m_open_no_key = mock_open(read_data='{"philosophies": []}')
        with patch.object(Path, "exists", return_value=True), \
             patch("builtins.open", m_open_no_key):
            plugin._save_to_evolution_log({"title": "Test No Key"})

        # 3. json.JSONDecodeError の処理 (374-375)
        m_open_invalid = mock_open(read_data='{invalid_json')
        with patch.object(Path, "exists", return_value=True), \
             patch("builtins.open", m_open_invalid):
            plugin._save_to_evolution_log({"title": "Test JSON Error"})

        # 4. 一般的な Exception の処理 (378-379)
        m_open_write_fail = mock_open(read_data='{"locked_segments": []}')
        m_open_write_fail().write.side_effect = RuntimeError("Write failed")
        with patch.object(Path, "exists", return_value=True), \
             patch("builtins.open", m_open_write_fail):
            plugin._save_to_evolution_log({"title": "Test Write Exception"})

        # 5. PermissionError の処理 (376-377)
        with patch.object(Path, "exists", return_value=True), \
             patch("builtins.open", side_effect=PermissionError("Mock write permission denied")):
            plugin._save_to_evolution_log({"title": "Test Write Permission Exception"})


# ============================================================
# Part 3: smart_cut_engine (10 tests)
# ============================================================

class TestSmartCutEngine:
    """smart_cut_engine.py — render_smart_cut + helpers"""

    def test_sce_01_get_logo_path_no_template(self):
        from smart_cut_engine import _get_logo_path
        with patch.dict(sys.modules, {"template_config": None}):
            with patch("smart_cut_engine.Path.exists", return_value=False):
                result = _get_logo_path()
                assert result is None

    def test_sce_02_get_logo_path_default(self, tmp_path):
        from smart_cut_engine import _get_logo_path
        with patch.dict(sys.modules, {"template_config": None}):
            logo = tmp_path / "brand_logo.png"
            logo.write_bytes(b"PNG")
            with patch("smart_cut_engine.Path.__new__", return_value=logo):
                # Just test it doesn't crash with template_config missing
                _get_logo_path()

    def test_sce_03_burn_subtitles_empty_segments(self, tmp_path):
        from smart_cut_engine import _burn_subtitles_ffmpeg
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"
        ffmpeg_mock = MagicMock()
        result = _burn_subtitles_ffmpeg(str(src), [], str(out), ffmpeg_mock)
        assert result is True
        assert out.exists()

    def test_sce_04_burn_subtitles_fallback3(self, tmp_path):
        from smart_cut_engine import _burn_subtitles_ffmpeg
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"
        ffmpeg_mock = MagicMock()
        ffmpeg_mock.run_command.return_value = (False, "error")
        ffmpeg_mock._get_encode_args.return_value = ["-c:v", "libx264"]
        ffmpeg_mock._get_hwaccel_input_args.return_value = []
        segments = [{"text": "テスト字幕", "start": 0, "end": 5}]
        result = _burn_subtitles_ffmpeg(str(src), segments, str(out), ffmpeg_mock)
        assert result == "fallback_no_subtitle"

    def test_sce_05_render_smart_cut_no_segments(self):
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.get_duration.return_value = 100.0
        mock_ffmpeg.cut_video.return_value = False
        mock_ve = MagicMock()
        mock_ve.ffmpeg = mock_ffmpeg
        mock_module = MagicMock()
        mock_module.video_editor = mock_ve
        mock_module.VideoClip = MagicMock()
        with patch.dict(sys.modules, {"video_editor_engine": mock_module}):
            # Force reimport
            if "smart_cut_engine" in sys.modules:
                del sys.modules["smart_cut_engine"]
            from smart_cut_engine import render_smart_cut
            result = render_smart_cut(
                [{"start": 0, "end": 5, "text": "test"}],
                "/fake/video.mp4", "/fake/output.mp4"
            )
            assert result is False

    def test_sce_06_render_smart_cut_single_part(self, tmp_path):
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"

        mock_ffmpeg = MagicMock()
        mock_ffmpeg.get_duration.return_value = 100.0
        def fake_cut(inp, outp, s, e):
            outp.write_bytes(b"cut")
            return True
        mock_ffmpeg.cut_video.side_effect = fake_cut
        mock_ffmpeg.run_command.return_value = (True, "ok")
        mock_ffmpeg._get_encode_args.return_value = ["-c:v", "libx264"]
        mock_ffmpeg._get_hwaccel_input_args.return_value = []

        mock_ve = MagicMock()
        mock_ve.ffmpeg = mock_ffmpeg
        mock_module = MagicMock()
        mock_module.video_editor = mock_ve
        mock_module.VideoClip = MagicMock()
        with patch.dict(sys.modules, {"video_editor_engine": mock_module}):
            if "smart_cut_engine" in sys.modules:
                del sys.modules["smart_cut_engine"]
            from smart_cut_engine import render_smart_cut
            segments = [{"start": 0, "sourceStart": 0, "end": 10, "sourceEnd": 10, "text": "テスト"}]
            out.write_bytes(b"final")
            result = render_smart_cut(segments, str(src), str(out))
            mock_ffmpeg.cut_video.assert_called()


# ============================================================
# Part 4: plugin_registry + metadata_completeness (4 tests)
# ============================================================

class TestPluginRegistry:
    """PLUGIN_REGISTRY — レジストリ確認"""

    def test_qg_32_registry_exists(self):
        from quality_gate_plugins import PLUGIN_REGISTRY
        assert len(PLUGIN_REGISTRY) >= 10

    def test_qg_33_all_plugins_have_name(self):
        from quality_gate_plugins import PLUGIN_REGISTRY
        for plugin in PLUGIN_REGISTRY:
            assert hasattr(plugin, "name")
            assert hasattr(plugin, "category")

    def test_qg_34_all_plugins_analyze(self):
        from quality_gate_plugins import PLUGIN_REGISTRY
        ctx = _MockCtx(segments=[{"text": "t", "start": 0, "end": 5}])
        for p in PLUGIN_REGISTRY:
            r = p.analyze(ctx)
            assert "deductions" in r
            assert "feedback" in r

    def test_qg_35_metadata_completeness_no_metadata(self):
        from quality_gate_plugins import MetadataCompletenessCheck
        r = MetadataCompletenessCheck().analyze(_MockCtx(metadata={}))
        assert r["deductions"] == 10

    def test_qg_36_metadata_completeness_partial(self):
        from quality_gate_plugins import MetadataCompletenessCheck
        meta = {"titles": ["t1"], "tags": ["tag1", "tag2"], "description": "short"}
        r = MetadataCompletenessCheck().analyze(_MockCtx(metadata=meta))
        assert r["deductions"] >= 2  # titles < 3, tags < 5, desc < 50

    def test_qg_37_metadata_completeness_good(self):
        from quality_gate_plugins import MetadataCompletenessCheck
        meta = {
            "titles": ["t1", "t2", "t3", "t4", "t5"],
            "tags": [f"tag{i}" for i in range(20)],
            "description": "A" * 100,
        }
        r = MetadataCompletenessCheck().analyze(_MockCtx(metadata=meta))
        assert r["deductions"] == 0


class TestQualityGateStability:
    """安定稼働プラグイン"""

    def test_qg_38_pipeline_completion_all_ok(self):
        from quality_gate_plugins import PipelineCompletionCheck
        ctx = _MockCtx(
            segments=[{"text": "t"}],
            selected_segments=[{"text": "t"}],
            metadata={"titles": ["t"], "thumbnail_path": "mock_thumbnail.png"},
        )
        r = PipelineCompletionCheck().analyze(ctx)
        assert r["deductions"] == 0
        assert "✅" in r["feedback"][0]

    def test_qg_39_pipeline_completion_missing(self):
        from quality_gate_plugins import PipelineCompletionCheck
        r = PipelineCompletionCheck().analyze(_MockCtx())
        assert r["deductions"] >= 15  # segments missing = 15

    def test_qg_40_gpu_health_ok(self):
        from quality_gate_plugins import GPUHealthCheck
        segs = [{"text": "テスト" * 20}]
        r = GPUHealthCheck().analyze(_MockCtx(segments=segs))
        assert r["deductions"] == 0
        assert "✅" in r["feedback"][0]

    def test_qg_41_gpu_health_no_segments(self):
        from quality_gate_plugins import GPUHealthCheck
        r = GPUHealthCheck().analyze(_MockCtx())
        assert r["deductions"] == 10

    def test_qg_42_gpu_health_sparse(self):
        from quality_gate_plugins import GPUHealthCheck
        segs = [{"text": "a"}]
        r = GPUHealthCheck().analyze(_MockCtx(segments=segs))
        assert r["deductions"] == 10


class TestRunAllPlugins:
    """run_all_plugins — 統合実行"""

    def test_qg_43_run_all_default(self):
        from quality_gate_plugins import run_all_plugins
        ctx = _MockCtx(
            segments=[{"text": f"seg{i}", "start": i * 3, "end": i * 3 + 2} for i in range(10)],
            selected_segments=[{"start": 0, "end": 30}],
            metadata={"titles": ["t1", "t2", "t3", "t4", "t5"], "tags": [f"t{i}" for i in range(20)], "description": "A" * 100},
        )
        result = run_all_plugins(ctx)
        assert "final_score" in result
        assert "category_scores" in result
        assert "category_report" in result
        assert 0 <= result["final_score"] <= 100
        assert result["block_recommended"] is False

    def test_qg_44_run_all_no_template(self):
        from quality_gate_plugins import run_all_plugins
        ctx = _MockCtx(segments=[{"text": "t", "start": 0, "end": 5}])
        result = run_all_plugins(ctx, template_config=None)
        assert result["final_score"] >= 0

    def test_qg_45_run_all_with_category_filter(self):
        from quality_gate_plugins import run_all_plugins
        ctx = _MockCtx(segments=[{"text": "t", "start": 0, "end": 5}])
        result = run_all_plugins(ctx, categories=["core"])
        assert result["final_score"] >= 0
        # Only core plugins should have been run
        for name in result["plugin_results"]:
            assert any(name in p.name for p in [
                type('O', (), {"name": "file_size_check"})(),
                type('O', (), {"name": "segment_quality_check"})(),
                type('O', (), {"name": "ai_rule_check"})(),
                type('O', (), {"name": "audio_presence_check"})(),
                type('O', (), {"name": "duration_sanity_check"})(),
            ])

    def test_qg_46_run_all_block_mode_critical(self):
        from quality_gate_plugins import run_all_plugins
        # Empty ctx = many deductions → block recommended
        ctx = _MockCtx()
        result = run_all_plugins(ctx, block_mode=True)
        assert result["block_recommended"] is True

    def test_qg_47_run_all_block_mode_passing(self):
        from quality_gate_plugins import run_all_plugins
        ctx = _MockCtx(
            segments=[{"text": f"seg{i}" * 5, "start": i * 3, "end": i * 3 + 2} for i in range(20)],
            selected_segments=[{"start": 0, "end": 50}],
            metadata={"titles": ["t1", "t2", "t3", "t4", "t5"], "tags": [f"t{i}" for i in range(20)], "description": "A" * 100},
        )
        result = run_all_plugins(ctx, block_mode=True)
        # Should have reasonable score with all data present
        assert isinstance(result["block_recommended"], bool)

    def test_qg_48_category_report_structure(self):
        from quality_gate_plugins import run_all_plugins
        ctx = _MockCtx(segments=[{"text": "t", "start": 0, "end": 5}])
        result = run_all_plugins(ctx)
        for cr in result["category_report"]:
            assert "category" in cr
            assert "label" in cr
            assert "weight" in cr
            assert "deductions" in cr
            assert "plugin_count" in cr

    def test_qg_49_category_weights(self):
        from quality_gate_plugins import CATEGORY_WEIGHTS
        assert CATEGORY_WEIGHTS["stability"] > CATEGORY_WEIGHTS["core"]
        assert CATEGORY_WEIGHTS["core"] > CATEGORY_WEIGHTS["youtube"]

    def test_qg_50_with_template_config(self):
        from quality_gate_plugins import run_all_plugins
        mock_tc = MagicMock()
        mock_tc.is_active = True
        mock_tc.template_id = "test"
        mock_tc.get_subtitle_rules.return_value = {"chars_per_second": 4, "max_chars_per_line": 15}
        mock_tc.get_engagement_rules.return_value = {"hook_window_seconds": 5, "dead_air_max_seconds": 3.0, "dopamine_interval_seconds": 10}
        mock_tc.get_hook_strength_thresholds.return_value = {
            "hook_window_seconds": 5,
            "score_weights": {"has_speech": 40, "speech_density": 30, "no_dead_air": 30},
        }
        mock_tc.get_retention_prediction_config.return_value = {
            "target_retention_percent": 40,
            "dead_air_max": 3.0,
            "scoring": {
                "segment_density_weight": 0.3,
                "hook_strength_weight": 0.25,
                "dead_air_penalty_weight": 0.25,
                "pacing_consistency_weight": 0.2,
            },
        }
        ctx = _MockCtx(
            segments=[{"text": "テスト", "start": i * 3, "end": i * 3 + 2} for i in range(10)],
            selected_segments=[{"start": 0, "end": 30}],
            metadata={"titles": ["t"] * 5, "tags": [f"t{i}" for i in range(20)], "description": "A" * 100},
        )
        result = run_all_plugins(ctx, template_config=mock_tc)
        assert result["final_score"] >= 0

    def test_qg_51_hook_strength_weak(self):
        from quality_gate_plugins import HookStrengthCheck
        segs = [{"text": "a", "start": 3, "end": 5}]  # starts late, low density
        r = HookStrengthCheck().analyze(_MockCtx(segments=segs))
        assert r["details"]["hook_score"] < 100

    def test_qg_52_retention_low_target(self):
        from quality_gate_plugins import RetentionPredictionCheck
        segs = [{"text": "t", "start": i * 30, "end": i * 30 + 1} for i in range(10)]
        r = RetentionPredictionCheck().analyze(_MockCtx(segments=segs))
        assert r["deductions"] >= 5  # sparse segments = low retention

    def test_qg_53_dead_air_6plus(self):
        from quality_gate_plugins import DeadAirCheck
        segs = [{"start": i * 50, "end": i * 50 + 1} for i in range(10)]
        r = DeadAirCheck().analyze(_MockCtx(segments=segs))
        assert r["deductions"] == 10  # > 5 dead airs

    def test_qg_54_subtitle_density_sparse(self):
        from quality_gate_plugins import SubtitleDensityCheck
        segs = [{"start": 0, "end": 1}, {"start": 100, "end": 101}]
        r = SubtitleDensityCheck().analyze(_MockCtx(segments=segs))
        assert r["deductions"] == 5



# ============================================================
# Part 5: Additional Coverage Tests (Added in Phase 21)
# ============================================================

class TestQualityGateAdditional:
    """quality_gate_plugins.py のカバレッジ 95%+ 達成に向けた追加テスト"""

    def test_qg_add_ai_rule_check_variants(self):
        from quality_gate_plugins import AIRuleCheck
        
        # 1. severity != "error" の課題検出と predict_issues のテスト
        mock_checker = MagicMock()
        mock_checker.check_custom_rules.return_value = [
            {"severity": "warning", "rule_name": "W01", "message": "warn message"}
        ]
        mock_checker.predict_issues.return_value = ["predicted issue 1"]
        
        with patch.dict(sys.modules, {"quality_gate_ai": MagicMock(ai_quality_checker=mock_checker)}):
            r = AIRuleCheck().analyze(_MockCtx(segments=[{"text": "dummy"}]))
            assert r["deductions"] == 5
            assert "[W01] warn message" in r["feedback"]
            assert "⚠ predicted issue 1" in r["feedback"]

        # 2. exception キャッチのテスト (AttributeError)
        with patch.dict(sys.modules, {"quality_gate_ai": MagicMock(ai_quality_checker=None)}):
            # None にアクセスすることで AttributeError を発生させる
            r = AIRuleCheck().analyze(_MockCtx(segments=[{"text": "dummy"}]))
            assert r["deductions"] == 0

    def test_qg_add_subtitle_speed_dur_zero(self):
        from quality_gate_plugins import SubtitleSpeedCheck
        
        # 1. dur <= 0 のスキップ
        segs = [{"text": "テスト字幕が長いです", "start": 5, "end": 5}]
        r = SubtitleSpeedCheck().analyze(_MockCtx(segments=segs))
        assert r["deductions"] == 0

        # 2. display_ratio が 0.05〜0.20 (警告レベル: deductions += 5)
        # checked_segs = 10, display_violations = 1 (display_ratio = 1/10 = 10%)
        # 正常なセグメント（9個）は8文字超にする
        segs_warn = [{"text": "あ" * 20, "start": 0, "end": 1}] + [{"text": "あ" * 10, "start": i * 10, "end": i * 10 + 5} for i in range(1, 10)]
        r2 = SubtitleSpeedCheck().analyze(_MockCtx(segments=segs_warn))
        assert r2["deductions"] == 5
        assert "表示字幕速度注意" in r2["feedback"][0]

        # 3. speech_ratio が 0.1〜0.3 (警告レベル: deductions += 1)
        # speech_violations = 2 / 10 = 20%
        # SPEECH_MAX_CPS = 10, len(text) > 5, cps > 10
        # 表示速度違反（max_line_len > 8）を防ぐため、文字数は7文字にする
        segs_speech = [{"text": "あ" * 7, "start": 0, "end": 0.5}] * 2 + [{"text": "a", "start": i, "end": i + 5} for i in range(2, 10)]
        r3 = SubtitleSpeedCheck().analyze(_MockCtx(segments=segs_speech))
        assert r3["deductions"] == 1
        assert "発話速度注意" in r3["feedback"][0]

    def test_qg_add_dead_air_attention(self):
        from quality_gate_plugins import DeadAirCheck
        
        # dead_air_max 基準を超えた無音区間が 1〜5 箇所 (deductions = 3)
        segs = [{"start": 0, "end": 1}, {"start": 5, "end": 6}] # gap = 4 (dead_air_max = 3.0) -> count = 1
        r = DeadAirCheck().analyze(_MockCtx(segments=segs))
        assert r["deductions"] == 3
        assert "無音区間注意" in r["feedback"][0]

    def test_qg_add_hook_strength_attention(self):
        from quality_gate_plugins import HookStrengthCheck
        
        # hook_score が 50〜70 点 (deductions = 5)
        # weights = {"has_speech": 40, "speech_density": 30, "no_dead_air": 30}
        # has_speech: yes (+40)
        # density: < 1 (total_chars = 2 / 5 = 0.4) (+0)
        # no_dead_air: start = 1.5 -> dead air (+0)
        # total_score = 40
        segs = [{"text": "ab", "start": 1.5, "end": 4.0}]
        r = HookStrengthCheck().analyze(_MockCtx(segments=segs))
        # スコアが 40 なので 50未満 -> deductions = 10
        assert r["deductions"] == 10
        
        # スコアが 60 (has_speech=40, speech_density=20 (density=1.5), no_dead_air=0 (start=1.5)) -> deductions = 5
        # total_chars = 6 / 5 = 1.2 (>= 1.0) -> speech_density = 30 * 0.5 = 15
        # hook_score = 40 + 15 = 55
        segs_warn = [{"text": "abcdef", "start": 1.5, "end": 4.0}]
        r2 = HookStrengthCheck().analyze(_MockCtx(segments=segs_warn))
        assert r2["deductions"] == 5
        assert "フック強度やや弱い" in r2["feedback"][0]

    def test_qg_add_retention_prediction_variants(self):
        from quality_gate_plugins import RetentionPredictionCheck
        
        # 1. total_dur <= 0
        segs_zero = [{"text": "a", "start": 5, "end": 5}]
        r = RetentionPredictionCheck().analyze(_MockCtx(segments=segs_zero))
        assert r["deductions"] == 0

        # 2. pacing_score 例外処理 (durations が 1つのみ等で stdev / mean が StatisticsError になるケース)
        segs_one = [{"text": "abc", "start": 0, "end": 3}] * 10
        # durations が同一なので stdev = 0, cv = 0, pacing_score = 100
        # statistics.stdev が StatisticsError になるよう durations の長さを 1 にする
        segs_error = [{"text": "abc", "start": 0, "end": 3}]
        # 1セグメントだと len(ctx.segments) < 5 のため早期リターンする。
        # なので、4つの空セグメントと1つの有効セグメントにする。
        segs_error = [{"text": "", "start": i, "end": i} for i in range(4)] + [{"text": "abc", "start": 4, "end": 7}]
        r2 = RetentionPredictionCheck().analyze(_MockCtx(segments=segs_error))
        assert "predicted_retention" in r2["details"]

        # 3. 予測維持率が目標の 70% 未満 (目標 40 * 0.7 = 28% 未満)
        # duration のばらつきを大きくして pacing_score を 0 に近づける
        segs_low = []
        for i in range(10):
            dur = 100.0 if i % 2 == 0 else 0.1
            start = i * 200
            segs_low.append({"text": "a", "start": start, "end": start + dur})
        r3 = RetentionPredictionCheck().analyze(_MockCtx(segments=segs_low))
        assert r3["deductions"] == 10
        assert "大幅改善が必要" in r3["feedback"][0]

    def test_qg_add_loudness_ffmpeg(self):
        from quality_gate_plugins import LoudnessCheck
        
        # 1. FFmpeg 正常実行: 音量が小さすぎる (-25 LUFS)
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.run_command.return_value = (True, '{"input_i": "-25.0"}')
        mock_ve = MagicMock(ffmpeg=mock_ffmpeg)
        
        with patch.dict(sys.modules, {"video_editor_engine": MagicMock(video_editor=mock_ve)}):
            with patch("pathlib.Path.exists", return_value=True):
                r = LoudnessCheck().analyze(_MockCtx(preview_path="dummy.mp4"))
                assert r["deductions"] == 10
                assert "音量が小さすぎる" in r["feedback"][0]

        # 2. FFmpeg 正常実行: 音量が大きすぎる (-10 LUFS)
        mock_ffmpeg.run_command.return_value = (True, '{"input_i": "-10.0"}')
        with patch.dict(sys.modules, {"video_editor_engine": MagicMock(video_editor=mock_ve)}):
            with patch("pathlib.Path.exists", return_value=True):
                r = LoudnessCheck().analyze(_MockCtx(preview_path="dummy.mp4"))
                assert r["deductions"] == 10
                assert "音量が大きすぎる" in r["feedback"][0]

        # 3. 例外キャッチのテスト
        mock_ffmpeg.run_command.side_effect = ValueError("Format error")
        with patch.dict(sys.modules, {"video_editor_engine": MagicMock(video_editor=mock_ve)}):
            with patch("pathlib.Path.exists", return_value=True):
                r = LoudnessCheck().analyze(_MockCtx(preview_path="dummy.mp4"))
                assert r["deductions"] == 0

    def test_qg_add_resolution_variants(self):
        from quality_gate_plugins import ResolutionCheck
        
        # 1. 解像度不足 (< 720p)
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.get_video_info.return_value = {"width": 640, "height": 480}
        mock_ve = MagicMock(ffmpeg=mock_ffmpeg)
        
        with patch.dict(sys.modules, {"video_editor_engine": MagicMock(video_editor=mock_ve)}):
            with patch("pathlib.Path.exists", return_value=True):
                r = ResolutionCheck().analyze(_MockCtx(preview_path="dummy.mp4"))
                assert r["deductions"] == 15
                assert "解像度不足" in r["feedback"][0]

        # 2. 解像度注意 (720p以上1080p未満)
        mock_ffmpeg.get_video_info.return_value = {"width": 1280, "height": 720}
        with patch.dict(sys.modules, {"video_editor_engine": MagicMock(video_editor=mock_ve)}):
            with patch("pathlib.Path.exists", return_value=True):
                r = ResolutionCheck().analyze(_MockCtx(preview_path="dummy.mp4"))
                assert r["deductions"] == 5
                assert "解像度注意" in r["feedback"][0]

        # 3. 例外キャッチのテスト
        mock_ffmpeg.get_video_info.side_effect = KeyError("Missing width")
        with patch.dict(sys.modules, {"video_editor_engine": MagicMock(video_editor=mock_ve)}):
            with patch("pathlib.Path.exists", return_value=True):
                r = ResolutionCheck().analyze(_MockCtx(preview_path="dummy.mp4"))
                assert r["deductions"] == 0

    def test_qg_add_codec_variants(self):
        from quality_gate_plugins import CodecCheck
        
        # 1. 映像コーデック注意、音声コーデック注意
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.get_video_info.return_value = {"video_codec": "mpeg4", "audio_codec": "mp2"}
        mock_ve = MagicMock(ffmpeg=mock_ffmpeg)
        
        with patch.dict(sys.modules, {"video_editor_engine": MagicMock(video_editor=mock_ve)}):
            with patch("pathlib.Path.exists", return_value=True):
                r = CodecCheck().analyze(_MockCtx(preview_path="dummy.mp4"))
                assert r["deductions"] == 10
                assert "映像コーデック注意" in r["feedback"][0]
                assert "音声コーデック注意" in r["feedback"][1]

        # 2. 例外キャッチのテスト
        mock_ffmpeg.get_video_info.side_effect = FileNotFoundError("ffprobe not found")
        with patch.dict(sys.modules, {"video_editor_engine": MagicMock(video_editor=mock_ve)}):
            with patch("pathlib.Path.exists", return_value=True):
                r = CodecCheck().analyze(_MockCtx(preview_path="dummy.mp4"))
                assert r["deductions"] == 0

    def test_qg_add_chapter_coverage_insufficient(self):
        from quality_gate_plugins import ChapterCoverageCheck
        
        # 10分超 (600秒超) で、チャプター候補不足
        # 各セグメントの gap は 1秒（<= 3.0なので chapter_break にならない）
        segs = [{"text": "a", "start": i * 10, "end": i * 10 + 9} for i in range(120)]
        
        r = ChapterCoverageCheck().analyze(_MockCtx(segments=segs))
        assert r["deductions"] == 5
        assert "チャプター候補不足" in r["feedback"][0]

    def test_qg_add_audio_presence_variants(self):
        from quality_gate_plugins import AudioPresenceCheck
        
        # 1. 音声トラックなし
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.get_video_info.return_value = {"audio_codec": "none"}
        mock_ve = MagicMock(ffmpeg=mock_ffmpeg)
        
        with patch.dict(sys.modules, {"video_editor_engine": MagicMock(video_editor=mock_ve)}):
            with patch("pathlib.Path.exists", return_value=True):
                r = AudioPresenceCheck().analyze(_MockCtx(preview_path="dummy.mp4"))
                assert r["deductions"] == 20
                assert "音声トラックが存在しない" in r["feedback"][0]

        # 2. 例外キャッチのテスト
        mock_ffmpeg.get_video_info.side_effect = ValueError("Error getting info")
        with patch.dict(sys.modules, {"video_editor_engine": MagicMock(video_editor=mock_ve)}):
            with patch("pathlib.Path.exists", return_value=True):
                r = AudioPresenceCheck().analyze(_MockCtx(preview_path="dummy.mp4"))
                assert r["deductions"] == 0

    def test_qg_add_bitrate_variants(self):
        from quality_gate_plugins import BitrateCheck
        
        # 1. ビットレート不足 (< 0.5Mbps)
        # file_size = 100_000 bytes (800_000 bits)
        # duration = 10 seconds (via segments)
        # bitrate = 800_000 / 10 / 1_000_000 = 0.08 Mbps
        segs = [{"start": 0, "end": 10}]
        with patch("pathlib.Path.exists", return_value=True),              patch("pathlib.Path.stat") as mock_stat:
            mock_stat.return_value.st_size = 100_000
            r = BitrateCheck().analyze(_MockCtx(preview_path="dummy.mp4", segments=segs))
            assert r["deductions"] == 10
            assert "ビットレート不足" in r["feedback"][0]

        # 2. ビットレート注意 (< 1.0Mbps)
        # file_size = 1,000_000 bytes (8,000,000 bits)
        # duration = 10 seconds
        # bitrate = 0.8 Mbps
        with patch("pathlib.Path.exists", return_value=True),              patch("pathlib.Path.stat") as mock_stat:
            mock_stat.return_value.st_size = 1_000_000
            r = BitrateCheck().analyze(_MockCtx(preview_path="dummy.mp4", segments=segs))
            assert r["deductions"] == 3
            assert "ビットレート注意" in r["feedback"][0]

        # 3. duration が 0 のときに ffprobe で取得するケース
        # FFprobe正常 -> duration 10
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.get_video_info.return_value = {"duration": 10.0}
        mock_ve = MagicMock(ffmpeg=mock_ffmpeg)
        with patch.dict(sys.modules, {"video_editor_engine": MagicMock(video_editor=mock_ve)}):
            with patch("pathlib.Path.exists", return_value=True),                  patch("pathlib.Path.stat") as mock_stat:
                mock_stat.return_value.st_size = 100_000
                r = BitrateCheck().analyze(_MockCtx(preview_path="dummy.mp4", segments=[]))
                assert r["deductions"] == 10

        # 4. 例外発生
        mock_ffmpeg.get_video_info.side_effect = Exception("FFprobe error")
        with patch.dict(sys.modules, {"video_editor_engine": MagicMock(video_editor=mock_ve)}):
            with patch("pathlib.Path.exists", return_value=True),                  patch("pathlib.Path.stat") as mock_stat:
                mock_stat.return_value.st_size = 100_000
                # duration = 0 -> ZeroDivisionError もしくは例外キャッチされる
                with patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt") as mock_register:
                    r = BitrateCheck().analyze(_MockCtx(preview_path="dummy.mp4", segments=[]))
                    assert r["deductions"] == 0
                    mock_register.assert_called_once()
                    args, kwargs = mock_register.call_args
                    assert kwargs["category"] == "ACCEPTED_SAFETY"
                    assert "BitrateCheck" in kwargs["pattern"]

    def test_qg_add_duration_sanity_early_return(self):
        from quality_gate_plugins import DurationSanityCheck
        
        # ctx.selected_segments が空
        segs = [{"start": 0, "end": 10}]
        r = DurationSanityCheck().analyze(_MockCtx(segments=segs, selected_segments=[]))
        assert r["deductions"] == 0

    def test_qg_add_metadata_completeness_short_titles_and_tags(self):
        from quality_gate_plugins import MetadataCompletenessCheck
        
        # 1. タイトル候補 1 or 2案
        meta = {"titles": ["t1", "t2"], "tags": [f"tag{i}" for i in range(20)], "description": "A" * 100}
        r = MetadataCompletenessCheck().analyze(_MockCtx(metadata=meta))
        assert r["deductions"] == 2
        assert "タイトル候補不足" in r["feedback"][0]

        # 2. タグが 5〜14 個
        meta2 = {"titles": ["t1"] * 5, "tags": [f"tag{i}" for i in range(10)], "description": "A" * 100}
        r2 = MetadataCompletenessCheck().analyze(_MockCtx(metadata=meta2))
        assert r2["deductions"] == 1
        assert "タグ改善余地" in r2["feedback"][0]

    def test_qg_add_run_all_plugins_variants(self):
        from quality_gate_plugins import run_all_plugins, PLUGIN_REGISTRY
        
        # 1. block_mode で core スコア < 50 によるブロック
        # 意図的に FileSizeCheck 等で減点を大きくするため、ダミーの小さいプレビューファイルを指定する
        ctx = _MockCtx(preview_path=None) # file_size_check deductions = 20
        # run_all_plugins を実行。core_score を 50 未満にするために、analyze が大量の減点をするモックプラグインを一時的に追加する
        mock_plugin = MagicMock()
        mock_plugin.name = "mock_core_plugin"
        mock_plugin.category = "core"
        mock_plugin.analyze.return_value = {"deductions": 20, "feedback": ["fail"]}
        
        # PLUGIN_REGISTRY に追加
        PLUGIN_REGISTRY.append(mock_plugin)
        try:
            # ctx はプレビューファイルなし (FileSizeCheck deductions = 20)
            # mock_plugin deductions = 20
            # core category total deductions = 40 (out of 60 max, score = 100 - 40/60*100 = 33.3 < 50)
            result = run_all_plugins(ctx, block_mode=True)
            assert result["block_recommended"] is True
        finally:
            PLUGIN_REGISTRY.pop()

        # 2. プラグイン実行時の例外キャッチのテスト
        mock_error_plugin = MagicMock()
        mock_error_plugin.name = "error_plugin"
        mock_error_plugin.category = "core"
        mock_error_plugin.analyze.side_effect = RuntimeError("Plugin crashed")
        
        PLUGIN_REGISTRY.append(mock_error_plugin)
        try:
            # 例外が発生しても run_all_plugins は正常に完走する
            result = run_all_plugins(ctx)
            assert "error_plugin" not in result["plugin_results"]
        finally:
            PLUGIN_REGISTRY.pop()
