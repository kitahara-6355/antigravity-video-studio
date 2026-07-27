import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock
from PIL import Image

# プロジェクトルートとbackendをsys.pathに追加
_project_root = str(Path(__file__).resolve().parent.parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
_backend_dir = str(Path(_project_root) / "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from quality_gate_plugins import (
    FileSizeCheck, SegmentQualityCheck, AIRuleCheck, SubtitleSpeedCheck,
    SubtitleLineCheck, HookCheck, DeadAirCheck, SubtitleDensityCheck,
    HookStrengthCheck, RetentionPredictionCheck, LoudnessCheck, ResolutionCheck,
    CodecCheck, AudioPresenceCheck, BitrateCheck, ChapterCoverageCheck,
    ShortsReadyCheck, CTRReadyCheck, MetadataCompletenessCheck, ThumbnailQualityCheck,
    PipelineCompletionCheck, GPUHealthCheck, run_all_plugins
)

class _MockCtx:
    def __init__(self, preview_path=None, segments=None, selected_segments=None, metadata=None, thumbnail_path=None):
        self.preview_path = preview_path
        self.segments = segments or []
        self.selected_segments = selected_segments or []
        self.metadata = metadata or {}
        if thumbnail_path:
            self.thumbnail_path = thumbnail_path

def test_file_size_check_variants(tmp_path):
    # 1. 1024バイト未満
    f1 = tmp_path / "small.mp4"
    f1.write_bytes(b"\x00" * 500)
    ctx1 = _MockCtx(preview_path=str(f1))
    r1 = FileSizeCheck().analyze(ctx1)
    assert r1["deductions"] == 30
    assert "ファイルサイズが異常に小さい" in r1["feedback"]

    # 2. 10MB未満
    f2 = tmp_path / "mid.mp4"
    f2.write_bytes(b"\x00" * (1024 * 1024))
    ctx2 = _MockCtx(preview_path=str(f2))
    r2 = FileSizeCheck().analyze(ctx2)
    assert r2["deductions"] == 3
    assert "ファイルサイズが小さい（低画質の可能性）" in r2["feedback"]

def test_segment_quality_check_high_ratio():
    ctx = _MockCtx(segments=[
        {"text": ""},
        {"text": "   "},
        {"text": "valid"},
    ]) # empty ratio = 2/3 = 66% > 30%
    r = SegmentQualityCheck().analyze(ctx)
    assert r["deductions"] == 10
    assert "空セグメント率が高い" in r["feedback"][0]

def test_ai_rule_check_active():
    mock_ai = MagicMock()
    mock_ai.check_custom_rules.return_value = [
        {"severity": "error", "rule_name": "R1", "message": "error msg"},
        {"severity": "warning", "rule_name": "R2", "message": "warn msg"}
    ]
    mock_ai.predict_issues.return_value = ["predicted issue"]
    
    with patch.dict(sys.modules, {"quality_gate_ai": MagicMock(ai_quality_checker=mock_ai)}):
        ctx = _MockCtx(segments=[{"text": "test segment"}])
        r = AIRuleCheck().analyze(ctx)
        assert r["deductions"] == 20 # 15 + 5
        assert "[R1] error msg" in r["feedback"]
        assert "⚠ predicted issue" in r["feedback"]

def test_subtitle_speed_check_warnings():
    # 1. display_ratio > 0.05 且つ <= 0.2 (表示字幕速度注意)
    segs = [{"start": 0, "end": 1.0, "text": "あ" * 10}] * 1 + [{"start": 0, "end": 5.0, "text": "ああああああああああ"}] * 9
    tc = MagicMock()
    tc.is_active = True
    tc.template_id = "test_tmpl"
    tc.get_subtitle_rules.return_value = {"chars_per_second": 4}
    ctx = _MockCtx(segments=segs)
    r = SubtitleSpeedCheck().analyze(ctx, tc)
    assert r["deductions"] == 5
    assert "表示字幕速度注意" in r["feedback"][0]

    # 2. speech_ratio > 0.1 且つ <= 0.3 (発話速度注意)
    segs2 = [{"start": 0, "end": 0.5, "text": "あ" * 6}] * 2 + [{"start": 0, "end": 1.0, "text": "い"}] * 8
    r2 = SubtitleSpeedCheck().analyze(_MockCtx(segments=segs2), tc)
    assert r2["deductions"] == 1
    assert "発話速度注意" in r2["feedback"][0]

def test_subtitle_line_check_with_template():
    tc = MagicMock()
    tc.is_active = True
    tc.template_id = "test_tmpl"
    tc.get_subtitle_rules.return_value = {"max_chars_per_line": 5}
    
    ctx = _MockCtx(segments=[{"text": "123456"}] * 4) # long lines = 4 > 3
    r = SubtitleLineCheck().analyze(ctx, tc)
    assert r["deductions"] == 5
    assert "長い字幕行" in r["feedback"][0]

def test_hook_check_with_template():
    tc = MagicMock()
    tc.is_active = True
    tc.template_id = "test_tmpl"
    tc.get_engagement_rules.return_value = {"hook_window_seconds": 3}
    
    ctx = _MockCtx(segments=[{"start": 4.0, "end": 5.0, "text": "hello"}])
    r = HookCheck().analyze(ctx, tc)
    assert r["deductions"] == 15
    assert "冒頭フック欠如" in r["feedback"][0]

def test_dead_air_check_many_gaps():
    segs = []
    for i in range(10):
        segs.append({"start": float(i * 10), "end": float(i * 10 + 2)})
    # gaps = 8s > dead_air_max(3s), count = 9 > 5
    r = DeadAirCheck().analyze(_MockCtx(segments=segs))
    assert r["deductions"] == 10
    assert "無音区間超過" in r["feedback"][0]

def test_subtitle_density_check_with_template():
    tc = MagicMock()
    tc.is_active = True
    tc.template_id = "test_tmpl"
    tc.get_engagement_rules.return_value = {"dopamine_interval_seconds": 5}
    
    # total_dur = 30s, len = 2. avg = 15s > interval * 2 (10s)
    ctx = _MockCtx(segments=[{"start": 0, "end": 2}, {"start": 28, "end": 30}])
    r = SubtitleDensityCheck().analyze(ctx, tc)
    assert r["deductions"] == 5
    assert "字幕密度不足" in r["feedback"][0]

def test_retention_prediction_check_variations():
    # 1. template config active, triggering deductions = 10 (predicted < target * 0.7)
    tc = MagicMock()
    tc.is_active = True
    tc.template_id = "test_tmpl"
    tc.get_retention_prediction_config.return_value = {
        "target_retention_percent": 80,
        "dead_air_max": 2.0,
        "scoring": {
            "segment_density_weight": 0.3,
            "hook_strength_weight": 0.25,
            "dead_air_penalty_weight": 0.25,
            "pacing_consistency_weight": 0.2,
        }
    }
    
    ctx = _MockCtx(segments=[
        {"start": 0, "end": 2},
        {"start": 200, "end": 202},
        {"start": 400, "end": 402},
        {"start": 600, "end": 602},
        {"start": 800, "end": 802}
    ])
    
    r = RetentionPredictionCheck().analyze(ctx, tc)
    assert r["deductions"] == 10
    assert "大幅改善が必要" in r["feedback"][0]

    # 2. target * 0.7 <= predicted < target
    tc2 = MagicMock()
    tc2.is_active = True
    tc2.template_id = "test_tmpl"
    tc2.get_retention_prediction_config.return_value = {
        "target_retention_percent": 50,
        "dead_air_max": 2.0,
        "scoring": {
            "segment_density_weight": 0.3,
            "hook_strength_weight": 0.25,
            "dead_air_penalty_weight": 0.25,
            "pacing_consistency_weight": 0.2,
        }
    }
    r2 = RetentionPredictionCheck().analyze(ctx, tc2)
    assert r2["deductions"] == 5
    assert "改善推奨" in r2["feedback"][0]

    # 3. durations is empty -> pacing_score = 50
    # Make total_dur = 10 > 0, but each segment's duration = 0.
    ctx_empty_dur = _MockCtx(segments=[
        {"start": 0, "end": 0},
        {"start": 2, "end": 2},
        {"start": 4, "end": 4},
        {"start": 6, "end": 6},
        {"start": 10, "end": 10},
    ])
    r3 = RetentionPredictionCheck().analyze(ctx_empty_dur)
    assert r3["details"]["pacing_score"] == 50

def test_codec_check_exception():
    mock_ve = MagicMock()
    mock_ve.video_editor.ffmpeg.get_video_info.side_effect = RuntimeError("Mock error")
    with patch.dict(sys.modules, {"video_editor_engine": mock_ve}):
        r = CodecCheck().analyze(_MockCtx(preview_path="dummy.mp4"))
        assert r["deductions"] == 0

def test_chapter_coverage_check_with_gap():
    segs = [
        {"start": 0, "end": 100},
        {"start": 105, "end": 200}, # gap = 5 > 3.0 -> break 1
        {"start": 201, "end": 300}, # gap = 1
        {"start": 305, "end": 400}, # gap = 5 > 3.0 -> break 2
        {"start": 401, "end": 700}
    ]
    r = ChapterCoverageCheck().analyze(_MockCtx(segments=segs))
    assert r["deductions"] == 0

def test_shorts_ready_check_highlights():
    ctx = _MockCtx(segments=[{"text": "これはやばい！"}])
    r = ShortsReadyCheck().analyze(ctx)
    assert r["deductions"] == 0
    assert r["details"]["highlight_count"] == 1

def test_ctr_ready_check_short_text():
    ctx = _MockCtx(segments=[{"text": "a"}] * 3)
    r = CTRReadyCheck().analyze(ctx)
    assert r["deductions"] == 3
    assert "冒頭テキストが短すぎる" in r["feedback"][0]

def test_audio_presence_check_exception():
    mock_ve = MagicMock()
    mock_ve.video_editor.ffmpeg.get_video_info.side_effect = Exception("error")
    with patch.dict(sys.modules, {"video_editor_engine": mock_ve}):
        r = AudioPresenceCheck().analyze(_MockCtx(preview_path="dummy.mp4"))
        assert r["deductions"] == 0

def test_bitrate_check_duration_zero_ffprobe_path():
    mock_ve = MagicMock()
    mock_ve.video_editor.ffmpeg.get_video_info.return_value = {"duration": 10.0}
    with patch.dict(sys.modules, {"video_editor_engine": mock_ve}):
        ctx = _MockCtx(preview_path="dummy.mp4", segments=[{"start": 0, "end": 0}])
        with patch("quality_gate_plugins.Path.exists", return_value=True), \
             patch("quality_gate_plugins.Path.stat") as mock_stat:
            mock_stat.return_value.st_size = 500000
            r = BitrateCheck().analyze(ctx)
            assert r["deductions"] == 10
            assert "ビットレート不足" in r["feedback"][0]

def test_metadata_completeness_check_very_incomplete():
    ctx = _MockCtx(metadata={"titles": [], "tags": [], "description": ""})
    r = MetadataCompletenessCheck().analyze(ctx)
    assert r["deductions"] == 11 # 5 (titles) + 3 (tags) + 3 (description)

def test_thumbnail_quality_check_various_cases(tmp_path):
    # 1. path is None
    r1 = ThumbnailQualityCheck().analyze(_MockCtx(thumbnail_path=None))
    assert r1["deductions"] == 15
    assert "サムネイルパスが設定されていません" in r1["feedback"][0]

    # 2. file does not exist
    r2 = ThumbnailQualityCheck().analyze(_MockCtx(thumbnail_path="nonexistent.png"))
    assert r2["deductions"] == 15
    assert "サムネイルファイルが存在しません" in r2["feedback"][0]

    # 3. size >= 4MB
    f_large = tmp_path / "large.png"
    f_large.write_bytes(b"\x00" * 10)
    with patch("quality_gate_plugins.Path.exists", return_value=True), \
         patch("quality_gate_plugins.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 5 * 1024 * 1024
        with patch("PIL.Image.open") as mock_open:
            mock_img = MagicMock()
            mock_open.return_value.__enter__.return_value = mock_img
            r3 = ThumbnailQualityCheck().analyze(_MockCtx(thumbnail_path="dummy.png"))
            assert r3["deductions"] >= 25

    # 4. Pillow verify error
    f_bad = tmp_path / "bad.png"
    f_bad.write_bytes(b"\x00" * 10)
    with patch("PIL.Image.open") as mock_open:
        mock_img = MagicMock()
        mock_img.verify.side_effect = OSError("verify error")
        mock_open.return_value.__enter__.return_value = mock_img
        r4 = ThumbnailQualityCheck().analyze(_MockCtx(thumbnail_path=str(f_bad)))
        assert r4["deductions"] == 25
        assert "画像が破損しているか" in r4["feedback"][0]

    # 5. Load error
    with patch("PIL.Image.open") as mock_open:
        mock_img = MagicMock()
        mock_img.verify.return_value = None
        mock_img.load.side_effect = OSError("load error")
        mock_open.return_value.__enter__.return_value = mock_img
        r5 = ThumbnailQualityCheck().analyze(_MockCtx(thumbnail_path=str(f_bad)))
        assert r5["deductions"] == 25
        assert "ロード中にエラーが発生" in r5["feedback"][0]

    # 6. Resolution < 1280x720 & Aspect ratio invalid
    with patch("PIL.Image.open") as mock_open:
        mock_img = MagicMock()
        mock_img.verify.return_value = None
        mock_img.load.return_value = None
        type(mock_img).size = PropertyMock(return_value=(640, 480))
        mock_open.return_value.__enter__.return_value = mock_img
        r6 = ThumbnailQualityCheck().analyze(_MockCtx(thumbnail_path=str(f_bad)))
        assert r6["deductions"] == 35 # 20 (resolution) + 15 (aspect ratio)

def test_pipeline_completion_check_success():
    ctx = _MockCtx(
        segments=[{"text": "ok"}],
        selected_segments=[{"text": "ok"}],
        metadata={"titles": ["ok"]},
        thumbnail_path="ok.png"
    )
    r = PipelineCompletionCheck().analyze(ctx)
    assert r["deductions"] == 0
    assert "✅ 全ステージ正常完走" in r["feedback"]

def test_gpu_health_check_success():
    ctx = _MockCtx(segments=[{"text": "abcdefghij"}] * 10) # 100 chars
    r = GPUHealthCheck().analyze(ctx)
    assert r["deductions"] == 0
    assert "GPU文字起こし正常" in r["feedback"][0]

def test_run_all_plugins_block_mode_by_core():
    from quality_gate_plugins import PLUGIN_REGISTRY
    mock_core_plugin = MagicMock()
    mock_core_plugin.category = "core"
    mock_core_plugin.name = "mock_core_fail"
    mock_core_plugin.analyze.return_value = {"deductions": 30, "feedback": ["fail"]}
    
    original = list(PLUGIN_REGISTRY)
    try:
        PLUGIN_REGISTRY.clear()
        PLUGIN_REGISTRY.append(mock_core_plugin)
        ctx = _MockCtx()
        result = run_all_plugins(ctx, block_mode=True, categories=["core"])
        assert result["block_recommended"] is True
    finally:
        PLUGIN_REGISTRY.clear()
        PLUGIN_REGISTRY.extend(original)


def test_bitrate_check_io_error_handling():
    # Path.stat() が OSError を投げるケース
    ctx = _MockCtx(preview_path="dummy.mp4", segments=[{"start": 0, "end": 10}])
    with patch("quality_gate_plugins.Path.exists", return_value=True), \
         patch("quality_gate_plugins.Path.stat", side_effect=OSError("Disk read failed")):
        r = BitrateCheck().analyze(ctx)
        assert r["deductions"] == 0
        assert r["feedback"] == []


def test_thumbnail_quality_check_corrupted_image_handling(tmp_path):
    # PIL.Image.open() が SyntaxError を投げるケース（画像破損）
    f_corrupt = tmp_path / "corrupt.png"
    f_corrupt.write_bytes(b"\x00" * 10)
    with patch("PIL.Image.open", side_effect=SyntaxError("Corrupt PNG structure")):
        r = ThumbnailQualityCheck().analyze(_MockCtx(thumbnail_path=str(f_corrupt)))
        assert r["deductions"] == 25
        assert "画像が破損しているか" in r["feedback"][0]
