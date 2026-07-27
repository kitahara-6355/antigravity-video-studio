import pytest
from template_config import TemplateConfigProvider, template_config

def test_template_config_provider_default():
    provider = TemplateConfigProvider()
    assert provider.template_id is None
    assert provider.is_active is False
    assert provider.get_color_grading_filter() == ""
    assert provider.get_branding_config() == {}

    # Default rules
    sub_rules = provider.get_subtitle_rules()
    assert sub_rules["chars_per_second"] == 4
    assert provider.get_max_chars_per_line() == 15
    assert provider.get_chars_per_second() == 4
    assert provider.get_min_display_seconds() == 1.2

    eng_rules = provider.get_engagement_rules()
    assert eng_rules["hook_window_seconds"] == 5
    assert provider.get_hook_window() == 5
    assert provider.get_dead_air_max() == 2.0
    assert provider.get_dopamine_interval() == 10

    benchmarks = provider.get_quality_benchmarks()
    assert benchmarks["audio_loudness_lufs"] == -16

    margins = provider.get_safe_area_margins()
    assert margins["MarginV"] == 20  # max(20, 720 * 2 / 100) = max(20, 14) = 20
    assert margins["MarginL"] == 25  # max(20, 1280 * 2 / 100) = max(20, 25.6) = 25

    style = provider.get_subtitle_style()
    assert "Yu Gothic UI" in style

def test_template_config_provider_active():
    provider = TemplateConfigProvider()
    template_data = {
        "subtitle_rules": {
            "chars_per_second": 5,
            "max_chars_per_line": 20,
            "safe_area_margin_percent": 5,
        },
        "engagement_rules": {
            "hook_window_seconds": 8,
        },
        "quality_benchmarks": {
            "audio_loudness_lufs": -24,
            "retention_target_percent": 60,
        },
        "branding": {
            "logo_path": "/path/to/logo.png",
        }
    }
    provider.set_active_template("nhk_documentary", template_data, "cool")
    assert provider.template_id == "nhk_documentary"
    assert provider.is_active is True

    assert provider.get_max_chars_per_line() == 20
    assert provider.get_chars_per_second() == 5
    assert provider.get_hook_window() == 8
    
    # safe area margins with 5%
    margins = provider.get_safe_area_margins()
    assert margins["MarginV"] == 36
    assert margins["MarginL"] == 64

    # loudnorm params check (target is -24, which is <= -22 -> returns -1.5, 15)
    tp, lra = provider._get_loudnorm_params()
    assert tp == -1.5
    assert lra == 15

    # loudnorm pass1 filter
    p1 = provider.get_loudnorm_pass1_filter()
    assert "I=-24" in p1
    assert "TP=-1.5" in p1

    # loudnorm pass2 filter
    p2 = provider.get_loudnorm_pass2_filter()
    assert "measured_I=-23" in p2

    p2_custom = provider.get_loudnorm_pass2_filter({
        "input_i": -20,
        "input_tp": -2,
        "input_lra": 12,
        "input_thresh": -30,
        "target_offset": 0.5
    })
    assert "measured_I=-20" in p2_custom
    assert "offset=0.5" in p2_custom

    # loudnorm 1pass filter
    p_fallback = provider.get_loudnorm_filter()
    assert "I=-24" in p_fallback

    # branding config
    branding = provider.get_branding_config()
    assert branding["logo_path"] == "/path/to/logo.png"

    # clear config
    provider.clear()
    assert provider.is_active is False

def test_template_config_provider_overrides_and_ai():
    provider = TemplateConfigProvider()
    
    # 1. Branding override without template
    provider.set_overrides({
        "branding": {
            "bgm_path": "/path/to/bgm.mp3"
        },
        "subtitle_rules": {
            "font_size_min_px": 24
        },
        "color_grading_filter": "eq=saturation=1.5"
    })
    branding = provider.get_branding_config()
    assert branding["bgm_path"] == "/path/to/bgm.mp3"
    
    sub_rules = provider.get_subtitle_rules()
    assert sub_rules["font_size_min_px"] == 24

    # 2. Color grading resolution priority
    # Without AI analysis: overrides priority
    assert provider.get_color_grading_filter() == "eq=saturation=1.5"

    # With AI analysis: AI analysis priority
    provider.set_ai_analysis({
        "color_grading_filter": "eq=contrast=1.2"
    })
    assert provider.get_color_grading_filter() == "eq=contrast=1.2"

    # Clean config check
    provider.clear()
    assert provider.get_color_grading_filter() == ""

def test_template_config_loudnorm_params_branches():
    provider = TemplateConfigProvider()
    
    # 1. asmr_relaxation template
    provider.set_active_template("asmr_relaxation", {}, "warm")
    tp, lra = provider._get_loudnorm_params()
    assert tp == -2.0
    assert lra == 20

    # 2. mrbeast_entertainment template (Web standard)
    provider.set_active_template("mrbeast_entertainment", {}, "warm")
    tp, lra = provider._get_loudnorm_params()
    assert tp == -1.5
    assert lra == 11

def test_template_config_color_grading_fallback_branches():
    provider = TemplateConfigProvider()
    
    # 1. nhk_documentary
    provider.set_active_template("nhk_documentary", {})
    assert "colorbalance=rs=-0.02" in provider.get_color_grading_filter()

    # 2. mrbeast_entertainment
    provider.set_active_template("mrbeast_entertainment", {})
    assert "colorbalance=rs=0.03" in provider.get_color_grading_filter()

    # 3. hikakin_vlog
    provider.set_active_template("hikakin_vlog", {})
    assert "unsharp=5:5:0.5" in provider.get_color_grading_filter()

    # 4. nonexistent template id fallback
    provider.set_active_template("nonexistent", {})
    assert provider.get_color_grading_filter() == ""

def test_template_config_thresholds_and_pipeline_config():
    provider = TemplateConfigProvider()
    
    thresholds = provider.get_hook_strength_thresholds()
    assert thresholds["hook_window_seconds"] == 5
    assert thresholds["min_words_in_hook"] == 3

    retention_cfg = provider.get_retention_prediction_config()
    assert retention_cfg["target_retention_percent"] == 50
    assert retention_cfg["scoring"]["segment_density_weight"] == 0.35

    pipe_cfg = provider.get_pipeline_config()
    assert "subtitle_style" in pipe_cfg
    assert "loudnorm_filter" in pipe_cfg
    assert pipe_cfg["template_id"] is None


def test_template_config_coverage_gap():
    from template_config import _coerce_to_numeric, _coerce_to_positive_numeric
    import math

    # 1. _coerce_to_numeric のエッジケース
    assert _coerce_to_numeric(None, -16) == -16
    assert _coerce_to_numeric(True, -16) == -16
    assert _coerce_to_numeric(False, -16) == -16
    assert _coerce_to_numeric(10, -16) == 10
    assert _coerce_to_numeric(10.5, -16) == 10.5
    assert _coerce_to_numeric("invalid", -16) == -16
    assert _coerce_to_numeric("10.0", -16) == 10  # float から int への変換 (57行目カバー)
    assert _coerce_to_numeric(float("nan"), -16) == -16
    assert _coerce_to_numeric(float("inf"), -16) == -16
    assert _coerce_to_numeric(float("-inf"), -16) == -16
    
    # 2. _coerce_to_positive_numeric のエッジケース
    assert _coerce_to_positive_numeric(None, 4) == 4
    assert _coerce_to_positive_numeric(True, 4) == 4
    assert _coerce_to_positive_numeric(False, 4) == 4
    assert _coerce_to_positive_numeric(10, 4) == 10
    assert _coerce_to_positive_numeric(-5, 4) == 4
    assert _coerce_to_positive_numeric(0, 4) == 4
    assert _coerce_to_positive_numeric(10.5, 4) == 10.5
    assert _coerce_to_positive_numeric("invalid", 4) == 4
    assert _coerce_to_positive_numeric("-5.0", 4) == 4  # <= 0 の default 返却
    assert _coerce_to_positive_numeric(0.0, 4) == 4
    assert _coerce_to_positive_numeric(float("nan"), 4) == 4
    assert _coerce_to_positive_numeric(float("inf"), 4) == 4
    assert _coerce_to_positive_numeric(float("-inf"), 4) == 4

    provider = TemplateConfigProvider()
    
    # 3. overrides / ai_analysis の non-dict input のフォールバック
    provider.set_overrides("invalid")
    assert provider.get_subtitle_rules()["chars_per_second"] == 4.0
    
    provider.set_ai_analysis("invalid")
    assert provider.get_color_grading_filter() == ""

    # 4. get_subtitle_rules の max_lines や safe_area_margin_percent 境界テスト
    provider.set_active_template("test", {
        "subtitle_rules": {
            "max_lines": 3.5, # float decimal
            "safe_area_margin_percent": 60, # > 50 -> fallback to 2
            "font_size_min_px": 5, # max(8, 5) -> 8
            "lead_frames": "invalid",
            "trail_frames": 4.5,
            "min_display_seconds": "invalid",
            "border_style": object(), # 例外ルート (207-208行目カバー)
            "alignment": "invalid_alignment" # 例外ルート (212-213行目カバー)
        }
    })
    rules = provider.get_subtitle_rules()
    assert rules["max_lines"] == 3
    assert rules["safe_area_margin_percent"] == 2
    assert rules["font_size_min_px"] == 8
    assert rules["lead_frames"] == 3
    assert rules["trail_frames"] == 4
    assert rules["min_display_seconds"] == 1.2
    assert rules["border_style"] == 4
    assert rules["alignment"] == 2

    # 5. 例外ハンドラテスト (TypeError/ValueError)
    class BadStr:
        def __str__(self):
            raise ValueError("bad string conversion")
            
    # get_max_chars_per_line / get_chars_per_second / get_min_display_seconds の例外ルート
    provider.get_subtitle_rules = lambda: {
        "max_chars_per_line": object(),
        "chars_per_second": object(),
        "min_display_seconds": object()
    }
    assert provider.get_max_chars_per_line() == 15
    assert provider.get_chars_per_second() == 4.0
    assert provider.get_min_display_seconds() == 1.2
    
    # get_hook_window / get_dead_air_max / get_dopamine_interval の例外ルート
    provider.get_engagement_rules = lambda: {
        "hook_window_seconds": object(),
        "dead_air_max_seconds": object(),
        "dopamine_interval_seconds": object()
    }
    assert provider.get_hook_window() == 5.0
    assert provider.get_dead_air_max() == 2.0
    assert provider.get_dopamine_interval() == 10.0
    
    # get_color_grading_filter の例外ルート
    provider.clear()
    provider._active_template_id = BadStr()
    assert provider.get_color_grading_filter() == ""
    
    # get_safe_area_margins の例外ルート
    provider.get_subtitle_rules = lambda: {"safe_area_margin_percent": object()}
    margins = provider.get_safe_area_margins()
    assert margins["MarginV"] == 20
    
    # get_safe_area_margins での safe_pct < 0 ルート
    provider.get_subtitle_rules = lambda: {"safe_area_margin_percent": -5.0}
    margins = provider.get_safe_area_margins()
    assert margins["MarginV"] == 20
    
    # _get_loudnorm_params の例外ルート
    provider.get_quality_benchmarks = lambda: {"audio_loudness_lufs": object()}
    assert provider._get_loudnorm_params() == (-1.5, 11)
    
    # get_branding_config の template が dict でない場合の else ルート
    provider.clear()
    provider._active_template = "not_a_dict"
    assert provider.get_branding_config() == {}
    
    # get_branding_config の branding キーが dict でない場合のルート
    provider.set_active_template("test", {"branding": "not_a_dict"})
    assert provider.get_branding_config() == {}
