"""
template_config.py -- テンプレート設定プロバイダー

テンプレートの品質基準をパイプライン全体に供給するシングルトン。
各ステージ（字幕レンダリング・音声ノーマライズ・品質ゲート等）が
ここから設定を取得し、テンプレート基準を強制適用する。

監査指摘事項への対応:
  - themes_router.py の PRODUCTION_TEMPLATES を正規のソースとして参照
  - FFmpeg用 force_style / loudnorm フィルタ文字列を自動生成
  - パイプライン各ステージへの注入インターフェースを提供
"""

import logging
import math
from typing import Dict, Any, Optional, Union, Tuple, Callable

from template_constants import (
    _DEFAULT_SUBTITLE_RULES,
    _DEFAULT_ENGAGEMENT_RULES,
    _DEFAULT_QUALITY_BENCHMARKS,
)

logger = logging.getLogger(__name__)


def _try_parse_float(value: Any) -> Optional[float]:
    """値を float にキャストしてみる。変換できない、あるいは None/bool なら None。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _is_finite_number(num: float) -> bool:
    """数値が有限値（NaN でも Inf でもない）かどうかを判定。"""
    return math.isfinite(num)


def _parse_numeric_value(value: Any) -> Optional[Union[int, float]]:
    """値を解析して int または float を返し、変換できない場合は None を返す。"""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    num = _try_parse_float(value)
    if num is None or not _is_finite_number(num):
        return None
    if num.is_integer():
        return int(num)
    return num


def _to_numeric_clamped(value: Any, default: Any, positive_only: bool = False) -> Any:
    """数値を安全にキャスト・クランプする共通ヘルパー。"""
    num = _parse_numeric_value(value)
    if num is None:
        return default
    if positive_only and num <= 0:
        return default
    return num


def _coerce_to_numeric(value: Any, default: Any) -> Any:
    """数値を安全にキャストする。整数値の場合は int で返す。"""
    return _to_numeric_clamped(value, default, positive_only=False)


def _coerce_to_positive_numeric(value: Any, default: Any) -> Any:
    """正の数（> 0）のみを許容する安全なキャスト。"""
    return _to_numeric_clamped(value, default, positive_only=True)


def _coerce_to_positive_int(value: Any, default: int) -> int:
    """正の整数（> 0）のみを許容する安全なキャスト。"""
    return int(_to_numeric_clamped(value, default, positive_only=True))


# 後方互換性およびテスト用のエイリアス定義
_to_numeric = _coerce_to_numeric
_to_positive_numeric = _coerce_to_positive_numeric
_to_positive_int = _coerce_to_positive_int


def _standardize_by_schema(
    rules: Dict[str, Any],
    schema: Dict[str, Tuple[Any, Callable[[Any, Any], Any]]]
) -> Dict[str, Any]:
    """スキーマ定義に従って辞書の値をクランプ・キャスト・標準化する共通ヘルパー。"""
    for key, (default, coerce_func) in schema.items():
        rules[key] = coerce_func(rules.get(key), default)
    return rules


# スキーマ定義の定数化（計算効率向上と関数分割の準備）
_SUBTITLE_PACING_SCHEMA = {
    "chars_per_second": (4, _coerce_to_positive_numeric),
    "max_chars_per_line": (15, _coerce_to_positive_int),
    "max_lines": (2, _coerce_to_positive_int),
    "lead_frames": (3, _coerce_to_positive_int),
    "trail_frames": (5, _coerce_to_positive_int),
    "min_display_seconds": (1.2, _coerce_to_positive_numeric),
}

_SUBTITLE_STYLE_SCHEMA = {
    "border_style": (4, _coerce_to_positive_int),
    "alignment": (2, _coerce_to_positive_int),
}

_QUALITY_BENCHMARKS_SCHEMA = {
    "ctr_target_percent": (5.0, _coerce_to_positive_numeric),
    "retention_target_percent": (50, _coerce_to_positive_numeric),
    "audio_loudness_lufs": (-16, _coerce_to_numeric),
}

_ENGAGEMENT_RULES_SCHEMA = {
    "hook_window_seconds": (5, _coerce_to_positive_numeric),
    "dopamine_interval_seconds": (10, _coerce_to_positive_numeric),
    "reengagement_mark_seconds": (180, _coerce_to_positive_numeric),
    "dead_air_max_seconds": (2.0, _coerce_to_positive_numeric),
}


class TemplateConfigProvider:
    """
    テンプレート設定をパイプラインの各ステージに供給する。

    使い方:
        from template_config import template_config
        style = template_config.get_subtitle_style()
        loudnorm = template_config.get_loudnorm_filter()
    """

    def __init__(self):
        self._active_template_id: Optional[str] = None
        self._active_template: Optional[Dict] = None
        self._active_theme_id: Optional[str] = None
        # 上級者向けオーバーライド（憲法§7: ユーザー成長性対応）
        self._overrides: Dict[str, Any] = {}
        # AI分析結果 of 動的注入ポイント（AI技術進化対応）
        self._ai_analysis: Dict[str, Any] = {}

    def set_active_template(self, template_id: str, template_data: Dict,
                             theme_id: str = "warm"):
        """パイプライン開始時にテンプレートを設定"""
        self._active_template_id = str(template_id) if template_id is not None else None
        self._active_template = dict(template_data) if isinstance(template_data, dict) else None
        self._active_theme_id = str(theme_id) if theme_id is not None else "warm"
        self._overrides = {}  # テンプレート切替時にリセット
        self._ai_analysis = {}
        logger.info(f"✅ テンプレート設定: {self._active_template_id} × {self._active_theme_id}")

    def set_overrides(self, overrides: Dict[str, Any]):
        """
        テンプレート基準の個別オーバーライド。
        
        上級者がテンプレートの特定パラメータだけ変更する場合に使用。
        例: {"subtitle_rules": {"font_size_min_px": 16, "chars_per_second": 4}}
        
        ネストされた辞書は shallow merge（キー単位で上書き）される。
        """
        if isinstance(overrides, dict):
            self._overrides = dict(overrides)
        else:
            self._overrides = {}
            logger.warning("🔧 警告: overridesが辞書型ではありません。空辞書を設定します。")
        logger.info(f"🔧 テンプレートオーバーライド適用: {list(self._overrides.keys())}")

    def set_ai_analysis(self, analysis: Dict[str, Any]):
        """
        AI分析結果の動的注入。
        
        将来的にVision API等が素材を分析した結果を注入するための
        拡張ポイント。カラーグレーディング等の動的設定に使用。
        
        例: {"color_grading_filter": "eq=saturation=1.2:contrast=1.1,..."}
        """
        if isinstance(analysis, dict):
            self._ai_analysis = dict(analysis)
        else:
            self._ai_analysis = {}
            logger.warning("🤖 警告: analysisが辞書型ではありません。空辞書を設定します。")
        logger.info(f"🤖 AI分析結果注入: {list(self._ai_analysis.keys())}")

    def clear(self):
        """テンプレート設定をクリア"""
        self._active_template_id = None
        self._active_template = None
        self._active_theme_id = None
        self._overrides = {}
        self._ai_analysis = {}

    @property
    def template_id(self) -> Optional[str]:
        return self._active_template_id

    @property
    def is_active(self) -> bool:
        return self._active_template is not None

    def _get_override_string(self, key: str) -> Optional[str]:
        """AI分析結果またはオーバーライド設定から文字列値を安全に取得する"""
        for source in (self._ai_analysis, self._overrides):
            if isinstance(source, dict) and key in source:
                val = source[key]
                if isinstance(val, str):
                    return val
        return None

    def _merge_overrides(self, base_dict: Dict[str, Any], section_key: str) -> Dict[str, Any]:
        """指定したセクションのオーバーライドを基本辞書にマージする"""
        merged = dict(base_dict)
        if isinstance(self._overrides, dict):
            section_overrides = self._overrides.get(section_key)
            if isinstance(section_overrides, dict):
                merged.update(section_overrides)
        return merged

    # ================================================================
    # 字幕ルール
    # ================================================================

    def _standardize_subtitle_pacing(self, rules: Dict[str, Any]) -> None:
        """字幕の表示速度や時間に関するパラメータをバリデーション及びクランプ・標準化する"""
        _standardize_by_schema(rules, _SUBTITLE_PACING_SCHEMA)

    def _standardize_subtitle_layout(self, rules: Dict[str, Any]) -> None:
        """字幕の配置レイアウト（セーフエリア・フォントサイズ）に関するパラメータをクランプ・標準化する"""
        safe_val = _to_positive_numeric(rules.get("safe_area_margin_percent"), 2)
        rules["safe_area_margin_percent"] = safe_val if safe_val <= 50 else 2

        font_size = _to_positive_int(rules.get("font_size_min_px"), 16)
        rules["font_size_min_px"] = max(8, font_size)

    def _standardize_subtitle_style(self, rules: Dict[str, Any]) -> None:
        """字幕のデザインスタイル（枠線、配置位置など）に関するパラメータをクランプ・標準化する"""
        rules["outline_required"] = bool(rules.get("outline_required", True))
        _standardize_by_schema(rules, _SUBTITLE_STYLE_SCHEMA)

    def _validate_and_standardize_subtitle_rules(self, raw_rules: Dict[str, Any]) -> Dict[str, Any]:
        """字幕ルールの型チェックと範囲制限を行うバリデータ"""
        validated = dict(raw_rules)
        self._standardize_subtitle_pacing(validated)
        self._standardize_subtitle_layout(validated)
        self._standardize_subtitle_style(validated)
        return validated

    def _get_subtitle_base_rules(self) -> Dict[str, Any]:
        """アクティブテンプレートから字幕の基本ルールを解決する"""
        rules = dict(_DEFAULT_SUBTITLE_RULES)
        if isinstance(self._active_template, dict):
            template_subtitle_rules = self._active_template.get("subtitle_rules")
            if isinstance(template_subtitle_rules, dict):
                rules.update(template_subtitle_rules)
        return rules

    def _apply_subtitle_overrides(self, base_rules: Dict[str, Any]) -> Dict[str, Any]:
        """基本ルールに対してオーバーライド（ユーザー設定）を適用する"""
        return self._merge_overrides(base_rules, "subtitle_rules")

    def _get_rule_value(self, rules: Dict[str, Any], key: str, default: Any, cast_func: Callable[[Any], Any]) -> Any:
        """指定したキーのルール値を安全に取得し、指定したキャスト関数を適用して返す"""
        try:
            return cast_func(rules.get(key, default))
        except (ValueError, TypeError):
            return default

    def get_subtitle_rules(self) -> Dict:
        """字幕ルールを取得（テンプレート→オーバーライドの順で適用）"""
        base_rules = self._get_subtitle_base_rules()
        resolved_rules = self._apply_subtitle_overrides(base_rules)
        return self._validate_and_standardize_subtitle_rules(resolved_rules)

    def get_max_chars_per_line(self) -> int:
        """1行あたりの最大文字数"""
        return self._get_rule_value(self.get_subtitle_rules(), "max_chars_per_line", 15, int)

    def get_chars_per_second(self) -> float:
        """1秒あたりの文字数上限"""
        return self._get_rule_value(self.get_subtitle_rules(), "chars_per_second", 4.0, float)

    def get_min_display_seconds(self) -> float:
        """最小表示時間（秒）"""
        return self._get_rule_value(self.get_subtitle_rules(), "min_display_seconds", 1.2, float)

    # ================================================================
    # エンゲージメント基準
    # ================================================================

    def _validate_and_standardize_engagement_rules(self, raw_rules: Dict[str, Any]) -> Dict[str, Any]:
        """エンゲージメントルールの型チェックと範囲制限を行うバリデータ"""
        validated = dict(raw_rules)
        return _standardize_by_schema(validated, _ENGAGEMENT_RULES_SCHEMA)

    def get_engagement_rules(self) -> Dict:
        """エンゲージメントルールを取得"""
        rules_dict = dict(_DEFAULT_ENGAGEMENT_RULES)
        if isinstance(self._active_template, dict):
            engagement_rules = self._active_template.get("engagement_rules")
            if isinstance(engagement_rules, dict):
                rules_dict.update(engagement_rules)
        return self._validate_and_standardize_engagement_rules(rules_dict)

    def get_hook_window(self) -> float:
        """冒頭フック許容時間（秒）"""
        return self._get_rule_value(self.get_engagement_rules(), "hook_window_seconds", 5.0, float)

    def get_dead_air_max(self) -> float:
        """無音区間の最大許容時間（秒）"""
        return self._get_rule_value(self.get_engagement_rules(), "dead_air_max_seconds", 2.0, float)

    def get_dopamine_interval(self) -> float:
        """ドーパミンヒット間隔（秒）"""
        return self._get_rule_value(self.get_engagement_rules(), "dopamine_interval_seconds", 10.0, float)

    # ================================================================
    # 品質ベンチマーク
    # ================================================================

    def _validate_and_standardize_quality_benchmarks(self, raw_rules: Dict) -> Dict:
        """品質ベンチマークの型チェックと範囲制限を行うバリデータ"""
        validated = dict(raw_rules)
        return _standardize_by_schema(validated, _QUALITY_BENCHMARKS_SCHEMA)

    def get_quality_benchmarks(self) -> Dict:
        """品質ベンチマークを取得"""
        rules_dict = dict(_DEFAULT_QUALITY_BENCHMARKS)
        if isinstance(self._active_template, dict):
            quality_benchmarks = self._active_template.get("quality_benchmarks")
            if isinstance(quality_benchmarks, dict):
                rules_dict.update(quality_benchmarks)
        return self._validate_and_standardize_quality_benchmarks(rules_dict)

    # ================================================================
    # カラーグレーディング（フェーズ1: 100点必達）
    # ================================================================

    # テンプレート別カラーフィルタ — 業界基準のルックを再現
    _COLOR_GRADING_FILTERS = {
        "nhk_documentary": (
            "eq=saturation=0.95:contrast=1.0,"
            "colorbalance=rs=-0.02:gs=0:bs=0.02"
        ),
        "mrbeast_entertainment": (
            "eq=saturation=1.3:contrast=1.15:brightness=0.02,"
            "colorbalance=rs=0.03:gs=0.01:bs=-0.02"
        ),
        "hikakin_vlog": (
            "eq=saturation=1.1:contrast=1.05:brightness=0.01,"
            "unsharp=5:5:0.5:5:5:0.0"
        ),
        "asmr_relaxation": (
            "eq=saturation=0.85:contrast=0.95:brightness=-0.04,"
            "colorbalance=rs=-0.03:gs=-0.01:bs=0.04"
        ),
    }

    def _get_color_grading_override(self) -> Optional[str]:
        """AI分析結果およびオーバーライドの設定を取得（AI優先）"""
        return self._get_override_string("color_grading_filter")

    def _get_color_grading_default(self) -> str:
        """アクティブなテンプレートのデフォルトカラーグレーディングフィルタを取得"""
        if self._active_template_id:
            try:
                template_id_str = str(self._active_template_id)
                return self._COLOR_GRADING_FILTERS.get(template_id_str, "")
            except (ValueError, TypeError):
                return ""
        return ""

    def get_color_grading_filter(self) -> str:
        """カラーグレーディングフィルタを取得。"""
        override_val = self._get_color_grading_override()
        if override_val is not None:
            return override_val
        return self._get_color_grading_default()

    # ================================================================
    # セーフエリア完全計算（3方向）
    # ================================================================

    def _get_safe_area_margin_percent(self) -> float:
        """字幕ルールからセーフエリアのマージンパーセンテージ（0-50%）を安全に取得する"""
        raw_percent = self.get_subtitle_rules().get("safe_area_margin_percent", 2.0)
        return float(_coerce_to_positive_numeric(raw_percent, 2.0))

    def _calculate_margins_720p(self, safe_area_percent: float) -> Dict[str, int]:
        """720p（1280x720）基準でセーフエリアマージンを計算する"""
        margin_vertical = max(20, int(720 * safe_area_percent / 100))
        margin_left_right = max(20, int(1280 * safe_area_percent / 100))
        return {
            "MarginV": margin_vertical,
            "MarginL": margin_left_right,
            "MarginR": margin_left_right,
        }

    def get_safe_area_margins(self) -> Dict[str, int]:
        """
        セーフエリアマージンを3方向で計算（720p基準）。

        戻り値: {"MarginV": 72, "MarginL": 64, "MarginR": 64}
        """
        safe_area_percent = self._get_safe_area_margin_percent()
        return self._calculate_margins_720p(safe_area_percent)

    def _get_subtitle_style_params(self, style_rules: Dict[str, Any]) -> Dict[str, Any]:
        """字幕スタイルに必要なパラメータのディクショナリを生成する"""
        margins = self.get_safe_area_margins()
        return {
            "font_size": style_rules.get("font_size_min_px", 16),
            "outline": 1 if style_rules.get("outline_required", True) else 0,
            "border_style": style_rules.get("border_style", 4),
            "alignment": style_rules.get("alignment", 2),
            "margin_v": margins["MarginV"],
            "margin_l": margins["MarginL"],
            "margin_r": margins["MarginR"]
        }

    def _format_subtitle_style(self, style_params: Dict[str, Any]) -> str:
        """スタイルパラメータから FFmpeg subtitles フィルタの force_style 文字列を組み立てる"""
        return (
            f"FontSize={style_params['font_size']},"
            f"PrimaryColour=&HFFFFFF,"
            f"OutlineColour=&H000000,"
            f"BackColour=&H80000000,"     # 半透明黒背景
            f"Outline={style_params['outline']},"
            f"BorderStyle={style_params['border_style']},"  # 4=背景ボックス
            f"FontName=Yu Gothic UI,"
            f"MarginV={style_params['margin_v']},"
            f"MarginL={style_params['margin_l']},"
            f"MarginR={style_params['margin_r']},"
            f"Alignment={style_params['alignment']}"        # 2=下部中央
        )

    def get_subtitle_style(self) -> str:
        """
        FFmpeg subtitles フィルタの force_style 文字列を生成。
        A-1: NHK準拠下帯字幕スタイル。
        """
        rules = self.get_subtitle_rules()
        style_params = self._get_subtitle_style_params(rules)
        return self._format_subtitle_style(style_params)

    # ================================================================
    # 2パス音声ノーマライズ（EBU R128準拠）
    # ================================================================

    def _get_loudnorm_target_and_params(self) -> Tuple[Union[int, float], float, Union[int, float]]:
        """品質ベンチマークからターゲットLUFS値およびテンプレート別のTrue Peak、Loudness Rangeパラメータを取得する"""
        benchmarks = self.get_quality_benchmarks()
        target = benchmarks.get("audio_loudness_lufs", -16)
        true_peak, loudness_range = self._get_loudnorm_params()
        return target, true_peak, loudness_range

    def get_loudnorm_pass1_filter(self) -> str:
        """
        2パスloudnorm Pass1（計測用）。
        print_format=jsonで計測値を出力。
        """
        target, true_peak, loudness_range = self._get_loudnorm_target_and_params()
        return f"loudnorm=I={target}:TP={true_peak}:LRA={loudness_range}:print_format=json"

    def _parse_measured_params(self, measured_dict: Dict[str, Any]) -> Dict[str, Any]:
        """計測されたラウドネスパラメータをパースしてクランプまたは安全にキャストする"""
        return {
            "i": _to_numeric(measured_dict.get('input_i'), -23.0),
            "tp": _to_numeric(measured_dict.get('input_tp'), -1.0),
            "lra": _to_numeric(measured_dict.get('input_lra'), 10.0),
            "thresh": _to_numeric(measured_dict.get('input_thresh'), -34.0),
            "offset": _to_numeric(measured_dict.get('target_offset'), 0.0)
        }

    def _format_loudnorm_pass2_filter(
        self,
        target: float,
        true_peak: float,
        loudness_range: float,
        measured_params: Dict[str, Any]
    ) -> str:
        """Pass2用フィルタ文字列をフォーマットする"""
        return (
            f"loudnorm=I={target}:TP={true_peak}:LRA={loudness_range}"
            f":measured_I={measured_params['i']}"
            f":measured_TP={measured_params['tp']}"
            f":measured_LRA={measured_params['lra']}"
            f":measured_thresh={measured_params['thresh']}"
            f":offset={measured_params['offset']}"
            f":linear=true"
        )

    def get_loudnorm_pass2_filter(self, measured: Optional[Dict] = None) -> str:
        """
        2パスloudnorm Pass2（適用用）。

        Args:
            measured: Pass1で計測されたJSON値
                {input_i, input_tp, input_lra, input_thresh, target_offset}
        """
        measured_dict = measured if isinstance(measured, dict) else {}
        target, true_peak, loudness_range = self._get_loudnorm_target_and_params()
        measured_params = self._parse_measured_params(measured_dict)
        return self._format_loudnorm_pass2_filter(
            target, true_peak, loudness_range, measured_params
        )

    def _get_asmr_loudnorm_params(self) -> Tuple[float, Union[int, float]]:
        """ASMR relaxationテンプレートのTrue PeakおよびLoudness Rangeを取得"""
        return -2.0, 20

    def _get_standard_loudnorm_params(self) -> Tuple[float, Union[int, float]]:
        """ターゲット音量に基づいて、True PeakおよびLoudness Rangeを取得"""
        benchmarks = self.get_quality_benchmarks()
        target = benchmarks.get("audio_loudness_lufs", -16.0)
        target = _coerce_to_numeric(target, -16.0)
            
        if target <= -22:
            true_peak, loudness_range = -1.5, 15  # NHK放送基準
        else:
            true_peak, loudness_range = -1.5, 11  # Web標準
        return true_peak, loudness_range

    def _get_loudnorm_params(self) -> Tuple[float, Union[int, float]]:
        """テンプレート別のTrue PeakおよびLoudness Rangeパラメータを取得する"""
        if self._active_template_id == "asmr_relaxation":
            return self._get_asmr_loudnorm_params()
        return self._get_standard_loudnorm_params()

    def get_loudnorm_filter(self) -> str:
        """後方互換: 1パスフォールバック"""
        target, true_peak, loudness_range = self._get_loudnorm_target_and_params()
        return f"loudnorm=I={target}:TP={true_peak}:LRA={loudness_range}"

    # ================================================================
    # フック強度・維持率予測（品質ゲート用）
    # ================================================================

    def get_hook_strength_thresholds(self) -> Dict:
        """
        フック強度判定の閾値セット。
        品質ゲートがセグメントデータからフック強度を算出する際に使用。
        """
        eng = self.get_engagement_rules()
        hook_window = eng.get("hook_window_seconds", 5)

        return {
            "hook_window_seconds": hook_window,
            "min_words_in_hook": 3,       # フック内の最低単語数
            "min_segments_in_hook": 1,     # フック内の最低セグメント数
            "score_weights": {
                "has_speech": 40,          # フック内に発話があるか
                "speech_density": 30,      # 発話密度
                "no_dead_air": 30,         # 無音なしか
            },
        }

    def get_retention_prediction_config(self) -> Dict:
        """
        維持率予測の設定。
        セグメント密度・無音率・テンション分布から予測維持率を算出する。
        """
        benchmarks = self.get_quality_benchmarks()
        eng = self.get_engagement_rules()

        return {
            "target_retention_percent": benchmarks.get("retention_target_percent", 50),
            "dopamine_interval": eng.get("dopamine_interval_seconds", 10),
            "dead_air_max": eng.get("dead_air_max_seconds", 2.0),
            "scoring": {
                "segment_density_weight": 0.35,   # 字幕密度
                "hook_strength_weight": 0.25,      # フック強度
                "dead_air_penalty_weight": 0.20,   # 無音ペナルティ
                "pacing_consistency_weight": 0.20,  # ペーシング一貫性
            },
        }

    # ================================================================
    # ブランディング設定（C-01修正: FIX-6A/6Bから参照）
    # ================================================================

    def get_branding_config(self) -> Dict:
        """ブランディング設定を取得（ロゴ・BGM等）"""
        if isinstance(self._active_template, dict):
            branding_dict = self._active_template.get("branding")
            branding_dict = dict(branding_dict) if isinstance(branding_dict, dict) else {}
        else:
            branding_dict = {}
        return self._merge_overrides(branding_dict, "branding")

    # ================================================================
    # パイプライン注入用サマリー
    # ================================================================

    def get_pipeline_config(self) -> Dict[str, Any]:
        """パイプラインコンテキストに注入する設定一式"""
        return {
            "template_id": self._active_template_id,
            "theme_id": self._active_theme_id,
            "subtitle_style": self.get_subtitle_style(),
            "loudnorm_filter": self.get_loudnorm_filter(),
            "color_grading_filter": self.get_color_grading_filter(),
            "safe_area_margins": self.get_safe_area_margins(),
            "subtitle_rules": self.get_subtitle_rules(),
            "engagement_rules": self.get_engagement_rules(),
            "quality_benchmarks": self.get_quality_benchmarks(),
            "hook_thresholds": self.get_hook_strength_thresholds(),
            "retention_config": self.get_retention_prediction_config(),
        }


# シングルトン
template_config = TemplateConfigProvider()
