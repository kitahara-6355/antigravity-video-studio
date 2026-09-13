import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)


class _MockCtx:
    """品質ゲートテスト用の軽量コンテキスト"""
    def __init__(self, preview_path=None, segments=None, selected_segments=None, metadata=None):
        self.preview_path = preview_path
        self.segments = segments or []
        self.selected_segments = selected_segments or []
        # **維持率予測はフック強度の実測値を要る**（R1.5-C4・19周目）。
        # 以前は `+ 70 * hook_strength_weight` と定数を足していて、
        # **予測維持率の 25% が捏造**だった。本番では HookStrengthCheck が
        # 先に走って実測値を積むので、テストでも同じものを渡す。
        self._quality_plugin_results = {
            "hook_strength_check": {"details": {"hook_score": 70}}
        }
        if metadata is not None:
            self.metadata = metadata


def test_ai_rule_check_exception():
    """AIRuleCheck.analyze で check_custom_rules が例外を投げた場合の処理を検証"""
    from quality_gate_plugins import AIRuleCheck
    
    mock_checker = MagicMock()
    mock_checker.check_custom_rules.side_effect = ValueError("AI Check failed")
    
    with patch.dict(sys.modules, {"quality_gate_ai": MagicMock(ai_quality_checker=mock_checker)}):
        r = AIRuleCheck().analyze(_MockCtx(segments=[{"text": "test"}]))
        assert r["deductions"] == 0
        assert r["feedback"] == []


def test_ai_rule_check_all_expected_exceptions():
    """AIRuleCheck.analyze で各種の想定例外（AttributeError, TypeError, ValueError, KeyError, RuntimeError）が適切にキャッチされるか検証"""
    from quality_gate_plugins import AIRuleCheck
    
    for exc_type in (AttributeError, TypeError, ValueError, KeyError, RuntimeError):
        mock_checker = MagicMock()
        mock_checker.check_custom_rules.side_effect = exc_type("AI check failed")
        
        with patch.dict(sys.modules, {"quality_gate_ai": MagicMock(ai_quality_checker=mock_checker)}):
            r = AIRuleCheck().analyze(_MockCtx(segments=[{"text": "test"}]))
            assert r["deductions"] == 0
            assert r["feedback"] == []


def test_loudness_check_exception():
    """LoudnessCheck.analyze で例外が発生した場合の処理を検証"""
    from quality_gate_plugins import LoudnessCheck
    
    mock_ve = MagicMock()
    mock_ve.video_editor.ffmpeg.run_command.side_effect = ValueError("FFmpeg failed")
    
    with patch.dict(sys.modules, {"video_editor_engine": mock_ve}):
        ctx = _MockCtx(preview_path="dummy.mp4")
        with patch("quality_gate_plugins.Path.exists", return_value=True):
            r = LoudnessCheck().analyze(ctx)
            assert r["deductions"] == 0
            assert r["feedback"] == []


def test_resolution_check_exception():
    """ResolutionCheck.analyze で例外が発生した場合の処理を検証"""
    from quality_gate_plugins import ResolutionCheck
    
    mock_ve = MagicMock()
    mock_ve.video_editor.ffmpeg.get_video_info.side_effect = KeyError("Key error")
    
    with patch.dict(sys.modules, {"video_editor_engine": mock_ve}):
        ctx = _MockCtx(preview_path="dummy.mp4")
        with patch("quality_gate_plugins.Path.exists", return_value=True):
            r = ResolutionCheck().analyze(ctx)
            assert r["deductions"] == 0
            assert r["feedback"] == []


def test_bitrate_check_exception():
    """BitrateCheck.analyze で例外が発生した場合の処理を検証 (OSError)"""
    from quality_gate_plugins import BitrateCheck
    
    mock_ve = MagicMock()
    mock_ve.video_editor.ffmpeg.get_video_info.side_effect = ValueError("Bitrate error")
    
    with patch.dict(sys.modules, {"video_editor_engine": mock_ve}):
        ctx = _MockCtx(preview_path="dummy.mp4", segments=[{"start": 0, "end": 10}])
        with patch("quality_gate_plugins.Path.exists", return_value=True), \
             patch("quality_gate_plugins.Path.stat") as mock_stat:
            mock_stat.side_effect = OSError("Disk error")
            r = BitrateCheck().analyze(ctx)
            assert r["deductions"] == 0
            assert r["feedback"] == []


def test_bitrate_check_warning_path():
    """BitrateCheck.analyze で ValueError などの一般的な例外が発生した場合の警告ログパスの検証"""
    from quality_gate_plugins import BitrateCheck
    
    mock_ve = MagicMock()
    mock_ve.video_editor.ffmpeg.get_video_info.side_effect = ValueError("Mock Value Error")
    
    with patch.dict(sys.modules, {"video_editor_engine": mock_ve}):
        ctx = _MockCtx(preview_path="dummy.mp4", segments=[{"start": 0, "end": 10}])
        with patch("quality_gate_plugins.Path.exists", return_value=True):
            r = BitrateCheck().analyze(ctx)
            assert r["deductions"] == 0
            assert r["feedback"] == []


def test_metadata_completeness_missing_attr():
    """MetadataCompletenessCheck で ctx に metadata 属性がない場合の処理を検証"""
    from quality_gate_plugins import MetadataCompletenessCheck
    
    class DummyCtx:
        pass
        
    ctx = DummyCtx()
    r = MetadataCompletenessCheck().analyze(ctx)
    assert r["deductions"] == 10
    assert "▶ メタデータ未生成 — YouTube最適化が完全に欠如" in r["feedback"]


def test_run_all_plugins_exception():
    """run_all_plugins でプラグインが例外を投げた際の処理を検証"""
    from quality_gate_plugins import run_all_plugins, PLUGIN_REGISTRY, QualityCheckPlugin
    
    class FaultyPlugin(QualityCheckPlugin):
        name = "faulty_plugin"
        category = "core"
        def analyze(self, ctx, template_config=None):
            raise RuntimeError("Plugin failed")
            
    faulty = FaultyPlugin()
    original_registry = list(PLUGIN_REGISTRY)
    PLUGIN_REGISTRY.append(faulty)
    
    try:
        ctx = _MockCtx(segments=[{"text": "test"}])
        result = run_all_plugins(ctx)
        assert result["final_score"] >= 0
        assert "faulty_plugin" not in result["plugin_results"]
    finally:
        PLUGIN_REGISTRY.remove(faulty)


def test_pacing_statistics_error():
    """RetentionPredictionCheck.analyze で pacing_score 計算時の statistics.stdev/mean 例外パスを検証"""
    from quality_gate_plugins import RetentionPredictionCheck
    
    # 全体で5つ以上のセグメントがあるが、duration > 0 なのは1つだけなので、durationsの要素数は1となりstdevが例外を投げる
    ctx = _MockCtx(segments=[
        {"text": "test1", "start": 0, "end": 5},
        {"text": "test2", "start": 5, "end": 5},
        {"text": "test3", "start": 5, "end": 5},
        {"text": "test4", "start": 5, "end": 5},
        {"text": "test5", "start": 5, "end": 5},
    ])
    r = RetentionPredictionCheck().analyze(ctx)
    assert r["deductions"] >= 0
    # **測れなかったペーシングを定数 50 で埋めない**（R1.5-C4・19周目）。
    # 50 は実際に取りうる点なので、**実測した 50 と測れなかった 50 が
    # 区別できなかった**。測れなければ `None` にして予測ごと止める。
    assert r["details"]["pacing_score"] is None
    assert r["checked"] is False
    assert r["details"]["predicted_retention"] is None


def test_loudness_json_decode_error():
    """LoudnessCheck.analyze で JSONDecodeError や ValueError が発生した場合のスルー処理を検証"""
    from quality_gate_plugins import LoudnessCheck
    
    mock_ve = MagicMock()
    # 不正なJSONを出力させる
    mock_ve.video_editor.ffmpeg.run_command.return_value = (True, '{"input_i": "bad')
    
    with patch.dict(sys.modules, {"video_editor_engine": mock_ve}):
        ctx = _MockCtx(preview_path="dummy.mp4")
        with patch("quality_gate_plugins.Path.exists", return_value=True):
            r = LoudnessCheck().analyze(ctx)
            assert r["deductions"] == 0
            assert r["feedback"] == []


def test_duration_sanity_ratio_warning():
    """DurationSanityCheck.analyze で ratio < 0.3 の警告パスを検証"""
    from quality_gate_plugins import DurationSanityCheck
    
    ctx = _MockCtx(
        segments=[{"start": 0, "end": 100}],
        selected_segments=[{"start": 0, "end": 20}] # ratio = 0.2 < 0.3
    )
    r = DurationSanityCheck().analyze(ctx)
    assert r["deductions"] == 5
    assert "出力尺注意" in r["feedback"][0]


def test_run_all_plugins_block_mode_core_score_low():
    """run_all_plugins で core_score < 50 による block_recommended = True を検証"""
    from quality_gate_plugins import run_all_plugins
    
    # preview_pathがNoneなのでFileSizeCheckで20点減点、かつセグメントやメタデータもないため
    # PipelineCompletionCheck等でさらに大幅に減点され、core_score < 50 になる
    ctx = _MockCtx(preview_path=None)
    result = run_all_plugins(ctx, block_mode=True)
    assert result["block_recommended"] is True
