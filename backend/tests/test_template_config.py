import pytest
from backend.template_config import TemplateConfigProvider

def test_template_config_default():
    provider = TemplateConfigProvider()
    assert provider.template_id is None
    assert provider.is_active is False
    
    # デフォルト値の確認
    rules = provider.get_subtitle_rules()
    assert rules["chars_per_second"] == 4
    assert rules["max_chars_per_line"] == 15
    assert rules["max_lines"] == 2
    
    assert provider.get_max_chars_per_line() == 15
    assert provider.get_chars_per_second() == 4.0
    assert provider.get_min_display_seconds() == 1.2
    
    eng = provider.get_engagement_rules()
    assert eng["hook_window_seconds"] == 5
    assert eng["dead_air_max_seconds"] == 2.0
    
    assert provider.get_hook_window() == 5.0
    assert provider.get_dead_air_max() == 2.0
    assert provider.get_dopamine_interval() == 10.0
    
    q = provider.get_quality_benchmarks()
    assert q["ctr_target_percent"] == 5.0
    assert q["retention_target_percent"] == 50.0
    assert q["audio_loudness_lufs"] == -16.0
    
    assert provider.get_color_grading_filter() == ""
    
    margins = provider.get_safe_area_margins()
    assert margins["MarginV"] == 20  # 720 * 2 / 100 = 14.4 -> max(20, 14) -> 20
    assert margins["MarginL"] == 25  # 1280 * 2 / 100 = 25.6 -> max(20, 25) -> 25
    
    style = provider.get_subtitle_style()
    assert "FontSize=16" in style
    
    # 2パス音声ノーマライズ
    assert "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json" == provider.get_loudnorm_pass1_filter()
    assert "loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=-23.0" in provider.get_loudnorm_pass2_filter()
    assert "loudnorm=I=-16:TP=-1.5:LRA=11" == provider.get_loudnorm_filter()
    
    # ブランディング
    assert provider.get_branding_config() == {}
    
    # サマリー
    cfg = provider.get_pipeline_config()
    assert cfg["template_id"] is None
    assert cfg["theme_id"] is None

def test_set_active_template():
    provider = TemplateConfigProvider()
    
    # 正常系
    data = {
        "subtitle_rules": {"chars_per_second": 5, "safe_area_margin_percent": 10},
        "engagement_rules": {"hook_window_seconds": 6},
        "quality_benchmarks": {"audio_loudness_lufs": -24},
        "branding": {"logo_path": "logo.png"}
    }
    provider.set_active_template("nhk_documentary", data, "cool")
    assert provider.template_id == "nhk_documentary"
    assert provider.is_active is True
    
    rules = provider.get_subtitle_rules()
    assert rules["chars_per_second"] == 5.0
    assert rules["safe_area_margin_percent"] == 10.0
    
    # セーフエリア
    margins = provider.get_safe_area_margins()
    assert margins["MarginV"] == 72   # 720 * 10 / 100 = 72
    assert margins["MarginL"] == 128  # 1280 * 10 / 100 = 128
    
    # TP/LRA の NHK 放送基準
    # lufs <= -22 -> -1.5, 15
    assert "loudnorm=I=-24:TP=-1.5:LRA=15:print_format=json" == provider.get_loudnorm_pass1_filter()
    
    # ASMR 基準
    provider.set_active_template("asmr_relaxation", {}, "warm")
    assert "loudnorm=I=-16:TP=-2.0:LRA=20:print_format=json" == provider.get_loudnorm_pass1_filter()
    
    # カラーグレーディング
    provider.set_active_template("mrbeast_entertainment", {}, "warm")
    assert "eq=saturation=1.3" in provider.get_color_grading_filter()
    
    provider.set_active_template("hikakin_vlog", {}, "warm")
    assert "unsharp=" in provider.get_color_grading_filter()
    
    provider.clear()
    assert provider.template_id is None

def test_overrides_and_ai_analysis():
    provider = TemplateConfigProvider()
    
    # overrides
    provider.set_overrides({
        "subtitle_rules": {"chars_per_second": 8},
        "color_grading_filter": "override_filter",
        "branding": {"logo_height": 50}
    })
    rules = provider.get_subtitle_rules()
    assert rules["chars_per_second"] == 8.0
    assert provider.get_color_grading_filter() == "override_filter"
    assert provider.get_branding_config() == {"logo_height": 50}
    
    # ai_analysis
    provider.set_ai_analysis({
        "color_grading_filter": "ai_filter"
    })
    # AI が最優先
    assert provider.get_color_grading_filter() == "ai_filter"
    
    # 型異常
    provider.set_overrides("invalid")
    assert provider.get_subtitle_rules()["chars_per_second"] == 4.0
    
    provider.set_ai_analysis("invalid")
    assert provider.get_color_grading_filter() == ""

def test_edge_cases_and_type_coercion():
    provider = TemplateConfigProvider()
    
    # None/invalid値が設定された場合
    data = {
        "subtitle_rules": {
            "chars_per_second": "invalid",
            "max_chars_per_line": None,
            "max_lines": "3",
            "safe_area_margin_percent": -5,
            "font_size_min_px": 5, # max(8, 5) -> 8
            "border_style": "invalid",
            "alignment": None
        },
        "engagement_rules": {
            "hook_window_seconds": "invalid",
            "dead_air_max_seconds": None,
            "reengagement_mark_seconds": "invalid",
            "dopamine_interval_seconds": -1
        },
        "quality_benchmarks": {
            "ctr_target_percent": "invalid",
            "retention_target_percent": -10,
            "audio_loudness_lufs": "invalid"
        }
    }
    
    provider.set_active_template("nhk_documentary", data)
    
    rules = provider.get_subtitle_rules()
    assert rules["chars_per_second"] == 4.0
    assert rules["max_chars_per_line"] == 15
    assert rules["max_lines"] == 3
    assert rules["safe_area_margin_percent"] == 2.0
    assert rules["font_size_min_px"] == 8
    assert rules["border_style"] == 4
    assert rules["alignment"] == 2
    
    eng = provider.get_engagement_rules()
    assert eng["hook_window_seconds"] == 5.0
    assert eng["dead_air_max_seconds"] == 2.0
    assert eng["reengagement_mark_seconds"] == 180.0
    assert eng["dopamine_interval_seconds"] == 10.0
    
    qb = provider.get_quality_benchmarks()
    assert qb["ctr_target_percent"] == 5.0
    assert qb["retention_target_percent"] == 50.0 # _safe_positive_float により、<= 0 はデフォルト値 50 になる
    assert qb["audio_loudness_lufs"] == -16.0
    
    # get_max_chars_per_line etc.
    assert provider.get_max_chars_per_line() == 15
    assert provider.get_chars_per_second() == 4.0
    assert provider.get_min_display_seconds() == 1.2
    
    # safe_area_margin_percent = "invalid"
    provider.set_overrides({"subtitle_rules": {"safe_area_margin_percent": "invalid"}})
    margins = provider.get_safe_area_margins()
    assert margins["MarginV"] == 20
    
    # safe_area_margin_percent = 60 (out of bounds)
    provider.set_overrides({"subtitle_rules": {"safe_area_margin_percent": 60}})
    margins = provider.get_safe_area_margins()
    assert margins["MarginV"] == 20
    
    # measured in loudnorm_pass2_filter is invalid
    provider.set_active_template("nhk_documentary", {})
    pass2 = provider.get_loudnorm_pass2_filter({
        "input_i": "invalid",
        "input_tp": None,
        "input_lra": "12.5",
        "input_thresh": -30
    })
    assert "measured_I=-23.0" in pass2
    assert "measured_TP=-1.0" in pass2
    assert "measured_LRA=12.5" in pass2
    assert "measured_thresh=-30" in pass2

def test_set_active_template_type_error():
    provider = TemplateConfigProvider()
    
    # template_data が辞書でない場合
    provider.set_active_template("some_id", None)
    assert provider.is_active is False
    assert provider.get_subtitle_rules()["chars_per_second"] == 4.0
    
    provider.set_active_template(123, "invalid_data", [])
    assert provider.template_id == "123"
    assert provider.is_active is False

def test_hook_and_retention_configs():
    provider = TemplateConfigProvider()
    
    th = provider.get_hook_strength_thresholds()
    assert th["hook_window_seconds"] == 5.0
    
    rc = provider.get_retention_prediction_config()
    assert rc["target_retention_percent"] == 50.0

def test_template_config_coverage_gap():
    from backend.template_config import _coerce_to_numeric, _coerce_to_positive_numeric
    
    # 1. _coerce_to_numeric のエッジケース
    assert _coerce_to_numeric(None, -16) == -16
    assert _coerce_to_numeric(10, -16) == 10
    assert _coerce_to_numeric(10.5, -16) == 10.5
    assert _coerce_to_numeric("invalid", -16) == -16
    assert _coerce_to_numeric("10.0", -16) == 10  # float から int への変換 (57行目カバー)
    
    # 2. _coerce_to_positive_numeric のエッジケース
    assert _coerce_to_positive_numeric(None, 4) == 4
    assert _coerce_to_positive_numeric(10, 4) == 10
    assert _coerce_to_positive_numeric(-5, 4) == 4
    assert _coerce_to_positive_numeric(0, 4) == 4
    assert _coerce_to_positive_numeric(10.5, 4) == 10.5
    assert _coerce_to_positive_numeric("invalid", 4) == 4
    assert _coerce_to_positive_numeric("-5.0", 4) == 4  # <= 0 の default 返却 (72行目カバー)
    assert _coerce_to_positive_numeric(0.0, 4) == 4

    provider = TemplateConfigProvider()
    
    # 3. get_subtitle_rules の max_lines や safe_area_margin_percent 境界テスト
    provider.set_active_template("test", {
        "subtitle_rules": {
            "max_lines": 3.5, # float decimal
            "safe_area_margin_percent": 60, # > 50 -> fallback to 2
        }
    })
    rules = provider.get_subtitle_rules()
    assert rules["max_lines"] == 3
    assert rules["safe_area_margin_percent"] == 2

    # 4. 例外ハンドラテスト (TypeError/ValueError)
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
    
    # get_safe_area_margins での safe_pct < 0 ルート (348行目カバー)
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
    
    # get_branding_config の branding キーが dict でない場合のルート (504-505行目カバー)
    provider.set_active_template("test", {"branding": "not_a_dict"})
    assert provider.get_branding_config() == {}

def test_new_robust_guards():
    from backend.template_config import _coerce_to_numeric, _coerce_to_positive_numeric, TemplateConfigProvider
    import math

    # bool値の入力
    assert _coerce_to_numeric(True, -16) == -16
    assert _coerce_to_numeric(False, -16) == -16
    assert _coerce_to_positive_numeric(True, 4) == 4
    assert _coerce_to_positive_numeric(False, 4) == 4

    # NaN / Inf の入力
    assert _coerce_to_numeric(float("nan"), -16) == -16
    assert _coerce_to_numeric(float("inf"), -16) == -16
    assert _coerce_to_numeric(float("-inf"), -16) == -16
    assert _coerce_to_positive_numeric(float("nan"), 4) == 4
    assert _coerce_to_positive_numeric(float("inf"), 4) == 4
    assert _coerce_to_positive_numeric(float("-inf"), 4) == 4

    # 新規追加された字幕キーのキャスト検証
    provider = TemplateConfigProvider()
    provider.set_active_template("test", {
        "subtitle_rules": {
            "lead_frames": "invalid",
            "trail_frames": 4.5,
            "min_display_seconds": "invalid"
        }
    })
    rules = provider.get_subtitle_rules()
    assert rules["lead_frames"] == 3
    assert rules["trail_frames"] == 4
    assert rules["min_display_seconds"] == 1.2
