"""
quality_gate.py — 統合品質ゲート (Phase 39 M39.2)

6品質指標（NHK字幕品質・コントラスト比・セーフエリア・音声ラウドネス・
エンコード品質・フレームドロップ）を統合評価し、動画の出荷判定を行う。

既存モジュールとの関係:
- backend/services/nhk_quality_scorer.py: 5軸NHK品質スコアラ（字幕品質の詳細評価を委譲）
- backend/agents/workers/quality_gate_worker.py: パイプラインステージとしての品質ゲート
- 本モジュール: 上記を統合し、スタンドアロンでも使える品質評価API
"""

import json
import logging
import math
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# データクラス定義
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass
class QualityConfig:
    """品質ゲートの設定値。

    Attributes:
        min_total_score: 合格最低スコア (0-100)
        subtitle_weight: NHK字幕品質の配点比率
        visual_weight: 視覚品質（コントラスト比 + セーフエリア）の配点比率
        audio_weight: 音声品質（ラウドネス）の配点比率
        encoding_weight: エンコード品質（CRF + フレームドロップ）の配点比率
        ffprobe_path: ffprobe実行ファイルのパス
    """
    min_total_score: float = 80.0
    subtitle_weight: float = 0.30
    visual_weight: float = 0.30
    audio_weight: float = 0.20
    encoding_weight: float = 0.20
    ffprobe_path: str = "ffprobe"


@dataclass
class SubtitleScore:
    """字幕品質スコアの詳細。

    NHK放送基準に基づく字幕品質の各指標を保持する。

    Attributes:
        chars_per_line: 1行あたりの平均文字数 (目標: <= 13)
        display_duration_avg: 平均表示時間（秒） (目標: 1.5-7.0秒)
        sync_offset_ms: 同期オフセット（ミリ秒） (目標: <= 200ms)
        line_break_quality: 改行品質スコア (0-100, 形態素解析ベース)
        contrast_ratio: コントラスト比 (目標: >= 4.5:1, WCAG 2.1 AA)
        safe_area_compliance: セーフエリア準拠率 (0-100)
        font_consistency: フォント一貫性スコア (0-100)
        total: 字幕品質の総合スコア (0-100)
    """
    chars_per_line: float = 0.0
    display_duration_avg: float = 0.0
    sync_offset_ms: float = 0.0
    line_break_quality: float = 0.0
    contrast_ratio: float = 0.0
    safe_area_compliance: float = 100.0
    font_consistency: float = 100.0
    total: float = 0.0


@dataclass
class VisualScore:
    """視覚品質スコア。

    Attributes:
        contrast_ratio: コントラスト比 (WCAG 2.1 AA基準: >= 4.5:1)
        contrast_score: コントラスト比のスコア (0-100, 配点10点分)
        safe_area_compliance: セーフエリア準拠率 (0-100)
        safe_area_score: セーフエリアのスコア (0-100, 配点10点分)
        total: 視覚品質の総合スコア (0-100)
    """
    contrast_ratio: float = 0.0
    contrast_score: float = 0.0
    safe_area_compliance: float = 100.0
    safe_area_score: float = 100.0
    total: float = 0.0


@dataclass
class AudioScore:
    """音声品質スコア。

    Attributes:
        loudness_lufs: 計測ラウドネス値 (LUFS)
        loudness_target: ターゲットラウドネス値 (-14 LUFS)
        loudness_deviation: ターゲットからの偏差
        total: 音声品質のスコア (0-100, 配点20点分)
        available: ffprobeで計測可能だったか
    """
    loudness_lufs: float = 0.0
    loudness_target: float = -14.0
    loudness_deviation: float = 0.0
    total: float = 0.0
    available: bool = False


@dataclass
class EncodingScore:
    """エンコード品質スコア。

    Attributes:
        crf_value: 推定CRF値 (低いほど高品質, 目標: <= 23)
        crf_score: CRFスコア (0-100, 配点10点分)
        frame_drop_count: フレームドロップ数 (目標: 0)
        frame_drop_score: フレームドロップスコア (0-100, 配点20点分)
        codec: 使用コーデック
        bitrate: ビットレート (bps)
        total: エンコード品質の総合スコア (0-100)
        available: ffprobeで計測可能だったか
    """
    crf_value: float = 0.0
    crf_score: float = 100.0
    frame_drop_count: int = 0
    frame_drop_score: float = 100.0
    codec: str = ""
    bitrate: float = 0.0
    total: float = 0.0
    available: bool = False


@dataclass
class ImprovementSuggestion:
    """改善提案。

    Attributes:
        category: カテゴリ (subtitle/visual/audio/encoding)
        severity: 深刻度 (critical/warning/info)
        current_value: 現在値
        target_value: 目標値
        suggestion: 改善提案テキスト
    """
    category: str = ""
    severity: str = "info"
    current_value: Any = None
    target_value: Any = None
    suggestion: str = ""


@dataclass
class QualityReport:
    """品質ゲートの統合レポート。

    Attributes:
        video_path: 評価対象の動画ファイルパス
        total_score: 総合スコア (0-100)
        passed: 合格判定 (total_score >= min_total_score)
        subtitle_score: 字幕品質スコア (字幕ファイルがない場合はNone)
        visual_score: 視覚品質スコア
        audio_score: 音声品質スコア
        encoding_score: エンコード品質スコア
        evaluated_at: 評価日時 (ISO 8601)
        details: 各指標の生データ
    """
    video_path: str = ""
    total_score: float = 0.0
    passed: bool = False
    subtitle_score: Optional[SubtitleScore] = None
    visual_score: VisualScore = field(default_factory=VisualScore)
    audio_score: AudioScore = field(default_factory=AudioScore)
    encoding_score: EncodingScore = field(default_factory=EncodingScore)
    nhk_grade: Optional[str] = None
    evaluated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """レポートを辞書形式で返す。"""
        result = {
            "video_path": self.video_path,
            "total_score": self.total_score,
            "passed": self.passed,
            "visual_score": asdict(self.visual_score),
            "audio_score": asdict(self.audio_score),
            "encoding_score": asdict(self.encoding_score),
            "nhk_grade": self.nhk_grade,
            "evaluated_at": self.evaluated_at,
            "details": self.details,
        }
        if self.subtitle_score is not None:
            result["subtitle_score"] = asdict(self.subtitle_score)
        return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# QualityGate 本体
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class QualityGate:
    """統合品質ゲート — 6指標による動画品質評価。

    ds_phase_39.md M39.2 に準拠した6品質指標:
    1. NHK字幕品質 (30点) — nhk_quality_scorer連携
    2. コントラスト比 (10点) — WCAG 2.1 AA基準
    3. セーフエリア (10点) — 座標計算
    4. 音声ラウドネス (20点) — ffprobe loudnormフィルター
    5. エンコード品質 (10点) — CRF値
    6. フレームドロップ (20点) — ffprobe frame count

    使用例::

        gate = QualityGate()
        report = gate.evaluate("output.mp4", "output.srt")
        if report.passed:
            print("品質ゲート通過")
        else:
            suggestions = gate.generate_improvement_report(report)
            for s in suggestions:
                print(f"[{s.severity}] {s.suggestion}")
    """

    # ── 閾値定数 ──
    WCAG_AA_CONTRAST = 4.5
    LOUDNESS_TARGET_LUFS = -14.0
    LOUDNESS_TOLERANCE_LUFS = 1.0
    MAX_CRF = 23
    MAX_CHARS_PER_LINE = 13
    DISPLAY_DURATION_MIN = 1.5  # 秒
    DISPLAY_DURATION_MAX = 7.0  # 秒
    SYNC_OFFSET_MAX_MS = 200.0  # ミリ秒

    def __init__(self, config: Optional[QualityConfig] = None):
        """QualityGateを初期化。

        Args:
            config: 品質設定。Noneの場合はデフォルト値を使用。
        """
        self.config = config or QualityConfig()
        self._ffprobe_available: Optional[bool] = None

    # ━━━ 公開API ━━━

    def evaluate(
        self, video_path: str, subtitle_path: Optional[str] = None
    ) -> QualityReport:
        """動画を総合評価し、品質レポートを生成する。

        Args:
            video_path: 評価対象の動画ファイルパス
            subtitle_path: SRT字幕ファイルパス (オプション)

        Returns:
            QualityReport: 総合品質レポート

        Raises:
            FileNotFoundError: video_pathが存在しない場合
        """
        if not Path(video_path).exists():
            raise FileNotFoundError(f"動画ファイルが見つかりません: {video_path}")

        logger.info(f"🔍 品質ゲート評価開始: {video_path}")

        # 各品質軸を評価
        subtitle_score = None
        self._last_nhk_grade = None
        if subtitle_path and Path(subtitle_path).exists():
            subtitle_score = self.check_subtitle_quality(subtitle_path)

        video_score = self.check_video_quality(video_path)
        audio_score = self.check_audio_quality(video_path)
        encoding_score = self._check_encoding_quality(video_path)

        # 重み付き総合スコア算出
        total_score = self._calculate_total_score(
            subtitle_score, video_score, audio_score, encoding_score
        )

        report = QualityReport(
            video_path=video_path,
            total_score=round(total_score, 1),
            passed=total_score >= self.config.min_total_score,
            subtitle_score=subtitle_score,
            visual_score=video_score,
            audio_score=audio_score,
            encoding_score=encoding_score,
            nhk_grade=getattr(self, "_last_nhk_grade", None),
            details=self._build_details(
                subtitle_score, video_score, audio_score, encoding_score
            ),
        )

        rank = self._rank(total_score)
        logger.info(
            f"✅ 品質ゲート評価完了: {total_score:.1f}点 (ランク{rank}) "
            f"{'PASS' if report.passed else 'FAIL'}"
        )

        return report

    def check_subtitle_quality(self, subtitle_path: str) -> SubtitleScore:
        """字幕ファイルの品質を評価する。

        NHK放送基準に基づき以下を検証:
        - 1行あたりの文字数 (目標: <= 13文字)
        - 表示時間 (目標: 1.5-7.0秒)
        - 同期精度 (目標: <= 200ms)
        - コントラスト比 (WCAG 2.1 AA: >= 4.5:1)
        - セーフエリア準拠

        Args:
            subtitle_path: SRT字幕ファイルパス

        Returns:
            SubtitleScore: 字幕品質の詳細スコア
        """
        if not Path(subtitle_path).exists():
            logger.warning(f"字幕ファイルが見つかりません: {subtitle_path}")
            self._last_nhk_grade = None
            return SubtitleScore(total=0.0)

        # NHKSubtitleScorer が利用可能なら委譲
        try:
            from backend.video_pipeline.nhk_subtitle_scorer import NHKSubtitleScorer
            scorer = NHKSubtitleScorer()
            score_func = getattr(scorer, "score", getattr(scorer, "score_srt", None))
            if score_func is not None:
                nhk_report = score_func(subtitle_path)
                self._last_nhk_grade = getattr(nhk_report, "grade", None)
                axis_scores = getattr(nhk_report, "axis_scores", {}) or {}

                def _get_axis_val(name1: str, name2: str) -> float:
                    ax = axis_scores.get(name1) or axis_scores.get(name2)
                    if ax is not None:
                        return float(getattr(ax, "score", 0.0))
                    for k, v in axis_scores.items():
                        if getattr(v, "name", "") in (name1, name2) or k in (name1, name2):
                            return float(getattr(v, "score", 0.0))
                    return 0.0

                return SubtitleScore(
                    chars_per_line=_get_axis_val("chars_per_line", "文字数/行"),
                    display_duration_avg=_get_axis_val("display_time", "表示時間"),
                    sync_offset_ms=_get_axis_val("audio_sync", "音声同期精度"),
                    line_break_quality=_get_axis_val("line_break", "句読点・改行"),
                    contrast_ratio=_get_axis_val("contrast", "コントラスト比"),
                    safe_area_compliance=_get_axis_val("safe_area", "セーフエリア"),
                    font_consistency=_get_axis_val("font_consistency", "フォント一貫性"),
                    total=float(getattr(nhk_report, "total_score", 0.0)),
                )
        except (ImportError, AttributeError, ValueError, TypeError, KeyError, RuntimeError, OSError) as e:
            logger.warning(f"NHKSubtitleScorer による字幕評価に失敗、フォールバックします: {e}")

        self._last_nhk_grade = None
        entries = self._parse_srt(subtitle_path)
        if not entries:
            logger.warning(f"字幕エントリが空です: {subtitle_path}")
            return SubtitleScore(total=50.0)

        # 1行あたりの平均文字数
        chars_per_line = self._calc_avg_chars_per_line(entries)

        # 平均表示時間
        display_duration_avg = self._calc_avg_display_duration(entries)

        # 同期オフセット推定 (隣接エントリ間のギャップ異常)
        sync_offset_ms = self._estimate_sync_offset(entries)

        # 改行品質 (簡易評価 — 形態素解析の代替)
        line_break_quality = self._eval_line_break_quality(entries)

        # コントラスト比 (デフォルト白文字+黒縁取りを想定)
        contrast_ratio = self._default_subtitle_contrast()

        # セーフエリア準拠 (SRT座標情報がない場合は100%想定)
        safe_area_compliance = 100.0

        # フォント一貫性 (SRTには書式情報がないため100%想定)
        font_consistency = 100.0

        # 総合スコア算出
        total = self._calc_subtitle_total(
            chars_per_line, display_duration_avg, sync_offset_ms,
            line_break_quality, contrast_ratio, safe_area_compliance,
            font_consistency
        )

        return SubtitleScore(
            chars_per_line=round(chars_per_line, 1),
            display_duration_avg=round(display_duration_avg, 2),
            sync_offset_ms=round(sync_offset_ms, 1),
            line_break_quality=round(line_break_quality, 1),
            contrast_ratio=round(contrast_ratio, 2),
            safe_area_compliance=round(safe_area_compliance, 1),
            font_consistency=round(font_consistency, 1),
            total=round(total, 1),
        )

    def check_video_quality(self, video_path: str) -> VisualScore:
        """動画の視覚品質（コントラスト比 + セーフエリア）を評価する。

        Args:
            video_path: 動画ファイルパス

        Returns:
            VisualScore: 視覚品質スコア
        """
        # コントラスト比: デフォルト字幕（白文字+黒背景）の推定コントラスト比
        contrast_ratio = self._default_subtitle_contrast()
        contrast_score = self._score_contrast(contrast_ratio)

        # セーフエリア: ffprobe情報から動画解像度を取得し準拠率を算出
        safe_area_compliance = 100.0
        safe_area_score = 100.0

        video_info = self._get_video_info(video_path)
        if video_info:
            width = video_info.get("width", 0)
            height = video_info.get("height", 0)
            if width > 0 and height > 0:
                safe_area_compliance = self._calc_safe_area_compliance(
                    width, height
                )
                safe_area_score = safe_area_compliance

        total = (contrast_score + safe_area_score) / 2.0

        return VisualScore(
            contrast_ratio=round(contrast_ratio, 2),
            contrast_score=round(contrast_score, 1),
            safe_area_compliance=round(safe_area_compliance, 1),
            safe_area_score=round(safe_area_score, 1),
            total=round(total, 1),
        )

    def check_audio_quality(self, video_path: str) -> AudioScore:
        """動画の音声ラウドネスを評価する。

        ffprobeのloudnormフィルターで計測し、-14 LUFS ± 1 をターゲットとする。

        Args:
            video_path: 動画ファイルパス

        Returns:
            AudioScore: 音声品質スコア
        """
        loudness = self._get_audio_loudness(video_path)

        if loudness is None:
            logger.warning("音声ラウドネス計測不可 — N/Aとして除外")
            return AudioScore(
                loudness_lufs=0.0,
                loudness_target=self.LOUDNESS_TARGET_LUFS,
                loudness_deviation=0.0,
                total=0.0,
                available=False,
            )

        deviation = abs(loudness - self.LOUDNESS_TARGET_LUFS)
        score = self._score_loudness(deviation)

        return AudioScore(
            loudness_lufs=round(loudness, 1),
            loudness_target=self.LOUDNESS_TARGET_LUFS,
            loudness_deviation=round(deviation, 1),
            total=round(score, 1),
            available=True,
        )

    def generate_improvement_report(
        self, report: QualityReport
    ) -> List[ImprovementSuggestion]:
        """品質レポートから改善提案リストを生成する。

        Args:
            report: QualityReport

        Returns:
            改善提案のリスト（深刻度順: critical > warning > info）
        """
        suggestions: List[ImprovementSuggestion] = []

        # ── 字幕関連 ──
        if report.subtitle_score is not None:
            sub = report.subtitle_score
            if sub.chars_per_line > self.MAX_CHARS_PER_LINE:
                suggestions.append(ImprovementSuggestion(
                    category="subtitle",
                    severity="warning",
                    current_value=sub.chars_per_line,
                    target_value=self.MAX_CHARS_PER_LINE,
                    suggestion=(
                        f"1行あたりの文字数が{sub.chars_per_line:.1f}文字です。"
                        f"NHK基準の{self.MAX_CHARS_PER_LINE}文字以下に抑えてください。"
                    ),
                ))

            if sub.display_duration_avg < self.DISPLAY_DURATION_MIN:
                suggestions.append(ImprovementSuggestion(
                    category="subtitle",
                    severity="critical",
                    current_value=sub.display_duration_avg,
                    target_value=f"{self.DISPLAY_DURATION_MIN}-{self.DISPLAY_DURATION_MAX}",
                    suggestion=(
                        f"字幕の平均表示時間が{sub.display_duration_avg:.1f}秒と短すぎます。"
                        f"{self.DISPLAY_DURATION_MIN}秒以上を推奨します。"
                    ),
                ))
            elif sub.display_duration_avg > self.DISPLAY_DURATION_MAX:
                suggestions.append(ImprovementSuggestion(
                    category="subtitle",
                    severity="warning",
                    current_value=sub.display_duration_avg,
                    target_value=f"{self.DISPLAY_DURATION_MIN}-{self.DISPLAY_DURATION_MAX}",
                    suggestion=(
                        f"字幕の平均表示時間が{sub.display_duration_avg:.1f}秒と長すぎます。"
                        f"{self.DISPLAY_DURATION_MAX}秒以下を推奨します。"
                    ),
                ))

            if sub.sync_offset_ms > self.SYNC_OFFSET_MAX_MS:
                suggestions.append(ImprovementSuggestion(
                    category="subtitle",
                    severity="critical",
                    current_value=sub.sync_offset_ms,
                    target_value=self.SYNC_OFFSET_MAX_MS,
                    suggestion=(
                        f"字幕の同期オフセットが{sub.sync_offset_ms:.0f}msです。"
                        f"{self.SYNC_OFFSET_MAX_MS:.0f}ms以下に改善してください。"
                    ),
                ))

            if sub.contrast_ratio < self.WCAG_AA_CONTRAST:
                suggestions.append(ImprovementSuggestion(
                    category="subtitle",
                    severity="critical",
                    current_value=sub.contrast_ratio,
                    target_value=self.WCAG_AA_CONTRAST,
                    suggestion=(
                        f"字幕のコントラスト比が{sub.contrast_ratio:.1f}:1です。"
                        f"WCAG 2.1 AA基準の{self.WCAG_AA_CONTRAST}:1以上にしてください。"
                    ),
                ))

        # ── 視覚品質 ──
        vis = report.visual_score
        if vis.contrast_ratio < self.WCAG_AA_CONTRAST:
            suggestions.append(ImprovementSuggestion(
                category="visual",
                severity="critical",
                current_value=vis.contrast_ratio,
                target_value=self.WCAG_AA_CONTRAST,
                suggestion=(
                    f"動画のコントラスト比が{vis.contrast_ratio:.1f}:1です。"
                    f"WCAG 2.1 AA基準の{self.WCAG_AA_CONTRAST}:1以上が必要です。"
                ),
            ))
        if vis.safe_area_compliance < 100.0:
            suggestions.append(ImprovementSuggestion(
                category="visual",
                severity="warning",
                current_value=vis.safe_area_compliance,
                target_value=100.0,
                suggestion=(
                    f"セーフエリア準拠率が{vis.safe_area_compliance:.0f}%です。"
                    "字幕や重要な要素がセーフエリア内に収まっているか確認してください。"
                ),
            ))

        # ── 音声品質 ──
        aud = report.audio_score
        if aud.available and aud.loudness_deviation > self.LOUDNESS_TOLERANCE_LUFS:
            severity = "critical" if aud.loudness_deviation > 3.0 else "warning"
            suggestions.append(ImprovementSuggestion(
                category="audio",
                severity=severity,
                current_value=aud.loudness_lufs,
                target_value=f"{self.LOUDNESS_TARGET_LUFS} ± {self.LOUDNESS_TOLERANCE_LUFS}",
                suggestion=(
                    f"音声ラウドネスが{aud.loudness_lufs:.1f} LUFSです。"
                    f"ターゲット{self.LOUDNESS_TARGET_LUFS} LUFS "
                    f"± {self.LOUDNESS_TOLERANCE_LUFS}に調整してください。"
                ),
            ))

        # ── エンコード品質 ──
        enc = report.encoding_score
        if enc.available:
            if enc.crf_value > self.MAX_CRF:
                suggestions.append(ImprovementSuggestion(
                    category="encoding",
                    severity="warning",
                    current_value=enc.crf_value,
                    target_value=self.MAX_CRF,
                    suggestion=(
                        f"推定CRF値が{enc.crf_value:.0f}です。"
                        f"CRF {self.MAX_CRF}以下でエンコードしてください。"
                    ),
                ))
            if enc.frame_drop_count > 0:
                suggestions.append(ImprovementSuggestion(
                    category="encoding",
                    severity="critical",
                    current_value=enc.frame_drop_count,
                    target_value=0,
                    suggestion=(
                        f"フレームドロップが{enc.frame_drop_count}件検出されました。"
                        "エンコード設定を見直してください。"
                    ),
                ))

        # 深刻度順でソート
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        suggestions.sort(key=lambda s: severity_order.get(s.severity, 99))

        return suggestions

    # ━━━ ffprobe連携（内部メソッド） ━━━

    def _is_ffprobe_available(self) -> bool:
        """ffprobeが利用可能かチェックする。結果をキャッシュ。"""
        if self._ffprobe_available is not None:
            return self._ffprobe_available
        try:
            subprocess.run(
                [self.config.ffprobe_path, "-version"],
                capture_output=True, timeout=10,
            )
            self._ffprobe_available = True
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            logger.warning(
                f"ffprobeが利用不可です: {self.config.ffprobe_path}"
            )
            self._ffprobe_available = False
        return self._ffprobe_available

    def _get_video_info(self, path: str) -> Optional[Dict[str, Any]]:
        """ffprobeで動画情報をJSON取得する。

        Args:
            path: 動画ファイルパス

        Returns:
            動画情報の辞書。ffprobe利用不可時はNone。
            {
                "width": int, "height": int,
                "codec": str, "bitrate": float,
                "duration": float, "nb_frames": int,
                "nb_read_frames": int,  # 実際に読み取れたフレーム数
                "format": dict,         # ffprobe format情報
                "streams": list,        # ffprobe streams情報
            }
        """
        if not self._is_ffprobe_available():
            return None

        try:
            result = subprocess.run(
                [
                    self.config.ffprobe_path,
                    "-v", "quiet",
                    "-print_format", "json",
                    "-show_format",
                    "-show_streams",
                    "-count_frames",
                    path,
                ],
                capture_output=True, text=True, encoding="utf-8", timeout=60,
            )
            if result.returncode != 0:
                logger.warning(
                    f"ffprobe失敗 (exit {result.returncode}): "
                    f"{result.stderr[:200] if result.stderr else ''}"
                )
                return None

            data = json.loads(result.stdout)
        except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as e:
            logger.warning(f"ffprobe実行エラー: {e}")
            return None

        # ストリーム情報を解析
        streams = data.get("streams", [])
        fmt = data.get("format", {})

        video_stream = next(
            (s for s in streams if s.get("codec_type") == "video"), {}
        )

        info: Dict[str, Any] = {
            "width": _safe_int(video_stream.get("width")),
            "height": _safe_int(video_stream.get("height")),
            "codec": video_stream.get("codec_name", ""),
            "bitrate": _safe_float(fmt.get("bit_rate")),
            "duration": _safe_float(fmt.get("duration")),
            "nb_frames": _safe_int(video_stream.get("nb_frames")),
            "nb_read_frames": _safe_int(video_stream.get("nb_read_frames")),
            "format": fmt,
            "streams": streams,
        }
        return info

    def _get_audio_loudness(self, path: str) -> Optional[float]:
        """ffprobeのloudnormフィルターで音声ラウドネスを計測する。

        Args:
            path: 動画ファイルパス

        Returns:
            入力ラウドネス値 (LUFS)。計測不可時はNone。
        """
        if not self._is_ffprobe_available():
            return None

        # ffprobeではなくffmpegのloudnormフィルターを使用
        # ffmpegがffprobeと同じディレクトリにある想定
        ffmpeg_path = self.config.ffprobe_path.replace("ffprobe", "ffmpeg")

        try:
            result = subprocess.run(
                [
                    ffmpeg_path,
                    "-i", path,
                    "-af", "loudnorm=print_format=json",
                    "-f", "null",
                    "-",
                ],
                capture_output=True, text=True, encoding="utf-8", timeout=120,
            )

            # loudnormの出力はstderrに出る
            stderr_text = result.stderr or ""
            return self._parse_loudnorm_output(stderr_text)

        except (subprocess.SubprocessError, OSError) as e:
            logger.warning(f"音声ラウドネス計測エラー: {e}")
            return None

    def _parse_loudnorm_output(self, stderr: str) -> Optional[float]:
        """loudnormフィルターのJSON出力からinput_iを抽出する。

        Args:
            stderr: ffmpegのstderr出力

        Returns:
            入力ラウドネス値 (LUFS)。パース失敗時はNone。
        """
        # loudnormはJSON形式で出力する: {"input_i": "-14.2", ...}
        # stderrの末尾にJSONが含まれる
        import re
        json_match = re.search(
            r'\{[^{}]*"input_i"\s*:\s*"[^"]*"[^{}]*\}', stderr
        )
        if not json_match:
            return None

        try:
            loudnorm_data = json.loads(json_match.group())
            input_i = loudnorm_data.get("input_i", "")
            return float(input_i)
        except (json.JSONDecodeError, ValueError, TypeError):
            return None

    # ━━━ エンコード品質チェック ━━━

    def _check_encoding_quality(self, video_path: str) -> EncodingScore:
        """エンコード品質（CRF + フレームドロップ）を評価する。

        Args:
            video_path: 動画ファイルパス

        Returns:
            EncodingScore: エンコード品質スコア
        """
        video_info = self._get_video_info(video_path)

        if video_info is None:
            return EncodingScore(available=False)

        codec = video_info.get("codec", "")
        bitrate = video_info.get("bitrate", 0.0)

        # CRF推定: ビットレートと解像度からCRF値を逆算推定
        width = video_info.get("width", 1920)
        height = video_info.get("height", 1080)
        crf_value = self._estimate_crf(bitrate, width, height)
        crf_score = self._score_crf(crf_value)

        # フレームドロップ: nb_frames vs nb_read_frames の差
        nb_frames = video_info.get("nb_frames", 0)
        nb_read_frames = video_info.get("nb_read_frames", 0)
        frame_drop_count = self._calc_frame_drops(nb_frames, nb_read_frames)
        frame_drop_score = self._score_frame_drops(frame_drop_count)

        # CRF配点10点、フレームドロップ配点20点 → 比率 1:2
        total = (crf_score * 1 + frame_drop_score * 2) / 3.0

        return EncodingScore(
            crf_value=round(crf_value, 1),
            crf_score=round(crf_score, 1),
            frame_drop_count=frame_drop_count,
            frame_drop_score=round(frame_drop_score, 1),
            codec=codec,
            bitrate=bitrate,
            total=round(total, 1),
            available=True,
        )

    # ━━━ スコア算出ヘルパー ━━━

    def _calculate_total_score(
        self,
        subtitle: Optional[SubtitleScore],
        visual: VisualScore,
        audio: AudioScore,
        encoding: EncodingScore,
    ) -> float:
        """重み付き総合スコアを算出する。

        ffprobeが利用不可で計測できなかった軸は除外し、
        利用可能な軸の重みで再正規化する。

        Args:
            subtitle: 字幕品質スコア (Noneの場合は除外)
            visual: 視覚品質スコア
            audio: 音声品質スコア
            encoding: エンコード品質スコア

        Returns:
            重み付き総合スコア (0-100)
        """
        weighted_scores: List[tuple] = []
        config = self.config

        # 字幕: NHK字幕品質 (30点分)
        if subtitle is not None:
            weighted_scores.append((subtitle.total, config.subtitle_weight))

        # 視覚: コントラスト比(10) + セーフエリア(10) = 20点分
        weighted_scores.append((visual.total, config.visual_weight))

        # 音声: ラウドネス (20点分)
        if audio.available:
            weighted_scores.append((audio.total, config.audio_weight))

        # エンコード: CRF(10) + フレームドロップ(20) = 30点分
        if encoding.available:
            weighted_scores.append((encoding.total, config.encoding_weight))

        if not weighted_scores:
            return 0.0

        total_weight = sum(w for _, w in weighted_scores)
        if total_weight <= 0:
            return 0.0

        return sum(s * w for s, w in weighted_scores) / total_weight

    def _score_contrast(self, contrast_ratio: float) -> float:
        """コントラスト比をスコア化する (0-100)。

        - >= 7.0:1 (WCAG AAA): 100点
        - >= 4.5:1 (WCAG AA):  80点 + 比例加算
        - < 4.5:1:              比例減点
        """
        if contrast_ratio >= 7.0:
            return 100.0
        elif contrast_ratio >= self.WCAG_AA_CONTRAST:
            # 4.5-7.0 の範囲で 80-100 にマッピング
            ratio = (contrast_ratio - self.WCAG_AA_CONTRAST) / (7.0 - self.WCAG_AA_CONTRAST)
            return 80.0 + ratio * 20.0
        else:
            # 0-4.5 の範囲で 0-80 にマッピング
            if self.WCAG_AA_CONTRAST <= 0:
                return 0.0
            return max(0.0, (contrast_ratio / self.WCAG_AA_CONTRAST) * 80.0)

    def _score_loudness(self, deviation: float) -> float:
        """ラウドネス偏差をスコア化する (0-100)。

        - 偏差 0: 100点
        - 偏差 <= 1 LUFS: 90-100点
        - 偏差 > 1 LUFS: 指数的に減点
        """
        if deviation <= self.LOUDNESS_TOLERANCE_LUFS:
            return 100.0 - (deviation / self.LOUDNESS_TOLERANCE_LUFS) * 10.0
        else:
            # 偏差が大きいほど急速に減点
            excess = deviation - self.LOUDNESS_TOLERANCE_LUFS
            return max(0.0, 90.0 - excess * 20.0)

    def _score_crf(self, crf_value: float) -> float:
        """CRF値をスコア化する (0-100)。

        - CRF <= 18: 100点 (高品質)
        - CRF <= 23: 70-100点 (適正範囲)
        - CRF > 23: 急速に減点
        """
        if crf_value <= 18:
            return 100.0
        elif crf_value <= self.MAX_CRF:
            ratio = (crf_value - 18) / (self.MAX_CRF - 18)
            return 100.0 - ratio * 30.0
        else:
            excess = crf_value - self.MAX_CRF
            return max(0.0, 70.0 - excess * 10.0)

    def _score_frame_drops(self, frame_drop_count: int) -> float:
        """フレームドロップ数をスコア化する (0-100)。

        - 0フレーム: 100点
        - 1-5フレーム: 60-99点
        - > 5フレーム: 急速に減点
        """
        if frame_drop_count <= 0:
            return 100.0
        elif frame_drop_count <= 5:
            return max(60.0, 100.0 - frame_drop_count * 8.0)
        else:
            return max(0.0, 60.0 - (frame_drop_count - 5) * 12.0)

    def _estimate_crf(
        self, bitrate: float, width: int, height: int
    ) -> float:
        """ビットレートと解像度からCRF値を逆算推定する。

        H.264/H.265のCRF-ビットレート関係は対数的。
        ここでは1080pを基準とした簡易推定を行う。

        Args:
            bitrate: ビットレート (bps)
            width: 動画幅 (px)
            height: 動画高さ (px)

        Returns:
            推定CRF値 (0-51)
        """
        if bitrate <= 0:
            return 28.0  # 情報不足時のデフォルト

        # 1080pでの参照ビットレート (CRF=23 ≈ 4Mbps)
        ref_bitrate_1080p = 4_000_000.0
        ref_crf = 23.0

        # 解像度補正: ピクセル数比で参照ビットレートを調整
        pixels = width * height
        ref_pixels = 1920 * 1080
        if ref_pixels > 0 and pixels > 0:
            pixel_ratio = pixels / ref_pixels
            adjusted_ref = ref_bitrate_1080p * pixel_ratio
        else:
            adjusted_ref = ref_bitrate_1080p

        if adjusted_ref <= 0:
            return 28.0

        # CRF ≈ ref_crf - 6 * log2(bitrate / adjusted_ref)
        # CRFが6下がるとビットレートが約2倍になる関係
        ratio = bitrate / adjusted_ref
        if ratio <= 0:
            return 51.0

        crf = ref_crf - 6.0 * math.log2(ratio)
        return max(0.0, min(51.0, crf))

    def _calc_frame_drops(
        self, nb_frames: int, nb_read_frames: int
    ) -> int:
        """フレームドロップ数を算出する。

        Args:
            nb_frames: ffprobeが報告するフレーム数 (ヘッダ情報)
            nb_read_frames: 実際に読み取れたフレーム数

        Returns:
            フレームドロップ数 (0以上)
        """
        if nb_frames <= 0 or nb_read_frames <= 0:
            return 0  # 情報不足の場合はドロップなしとする
        return max(0, nb_frames - nb_read_frames)

    # ━━━ 字幕解析ヘルパー ━━━

    def _parse_srt(self, srt_path: str) -> List[Dict[str, Any]]:
        """SRTファイルをパースしてエントリのリストを返す。

        Args:
            srt_path: SRTファイルパス

        Returns:
            [{"start": ms, "end": ms, "text": str}, ...]
        """
        import re

        entries: List[Dict[str, Any]] = []

        try:
            text = Path(srt_path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            logger.warning(f"SRTファイル読み込みエラー: {e}")
            return entries

        # SRTフォーマット: 番号行 → タイムコード行 → テキスト行
        blocks = re.split(r"\n\s*\n", text.strip())
        for block in blocks:
            lines = block.strip().split("\n")
            if len(lines) < 2:
                continue

            # タイムコード行を探す
            timecode_line = None
            text_lines = []
            for i, line in enumerate(lines):
                if " --> " in line:
                    timecode_line = line
                    text_lines = lines[i + 1:]
                    break

            if not timecode_line:
                continue

            start_ms, end_ms = self._parse_srt_timecode(timecode_line)
            if start_ms is not None and end_ms is not None:
                entries.append({
                    "start": start_ms,
                    "end": end_ms,
                    "text": "\n".join(text_lines),
                })

        return entries

    def _parse_srt_timecode(self, line: str) -> tuple:
        """SRTタイムコード行をパースする。

        Args:
            line: "00:01:23,456 --> 00:01:25,789"

        Returns:
            (start_ms, end_ms) のタプル。パース失敗時は (None, None)。
        """
        import re

        pattern = (
            r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
            r"\s*-->\s*"
            r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
        )
        match = re.match(pattern, line.strip())
        if not match:
            return (None, None)

        g = match.groups()

        def to_ms(h: str, m: str, s: str, ms: str) -> int:
            return int(h) * 3600000 + int(m) * 60000 + int(s) * 1000 + int(ms)

        start = to_ms(g[0], g[1], g[2], g[3])
        end = to_ms(g[4], g[5], g[6], g[7])
        return (start, end)

    def _calc_avg_chars_per_line(self, entries: List[Dict]) -> float:
        """字幕エントリの1行あたりの平均文字数を算出する。"""
        total_chars = 0
        total_lines = 0
        for entry in entries:
            text = entry.get("text", "")
            for line in text.split("\n"):
                stripped = line.strip()
                if stripped:
                    total_chars += len(stripped)
                    total_lines += 1
        if total_lines == 0:
            return 0.0
        return total_chars / total_lines

    def _calc_avg_display_duration(self, entries: List[Dict]) -> float:
        """字幕エントリの平均表示時間を算出する (秒)。"""
        if not entries:
            return 0.0
        durations = [
            (e["end"] - e["start"]) / 1000.0
            for e in entries
            if e["end"] > e["start"]
        ]
        if not durations:
            return 0.0
        return sum(durations) / len(durations)

    def _estimate_sync_offset(self, entries: List[Dict]) -> float:
        """隣接字幕間のギャップ異常から同期オフセットを推定する (ms)。

        大きなギャップや重複が多いほどオフセットが大きいと推定。
        """
        if len(entries) < 2:
            return 0.0

        offsets = []
        for i in range(1, len(entries)):
            gap = entries[i]["start"] - entries[i - 1]["end"]
            if gap < 0:
                # 重複: 負のギャップの絶対値をオフセットとする
                offsets.append(abs(gap))
            elif gap > 5000:
                # 5秒以上のギャップは同期異常の可能性
                offsets.append(min(gap - 5000, 1000))

        if not offsets:
            return 0.0
        return sum(offsets) / len(offsets)

    def _eval_line_break_quality(self, entries: List[Dict]) -> float:
        """改行品質を簡易評価する (0-100)。

        形態素解析の完全な代替として、以下のヒューリスティクスを使用:
        - 1行の文字数が均等に近いほど高スコア
        - 極端に短い行（2文字以下）がないほど高スコア
        """
        if not entries:
            return 100.0

        penalties = 0
        total_checks = 0

        for entry in entries:
            text = entry.get("text", "")
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            if len(lines) <= 1:
                continue

            total_checks += 1
            lengths = [len(l) for l in lines]

            # 行間の長さの偏差が大きいと減点
            avg_len = sum(lengths) / len(lengths)
            if avg_len > 0:
                variance = sum((l - avg_len) ** 2 for l in lengths) / len(lengths)
                cv = math.sqrt(variance) / avg_len  # 変動係数
                if cv > 0.5:
                    penalties += 1

            # 2文字以下の極端に短い行
            if any(l <= 2 for l in lengths):
                penalties += 1

        if total_checks == 0:
            return 100.0

        penalty_rate = penalties / max(total_checks * 2, 1)
        return max(0.0, 100.0 - penalty_rate * 100.0)

    def _default_subtitle_contrast(self) -> float:
        """デフォルトの字幕コントラスト比を返す。

        白文字(#FFFFFF) + 黒縁取り/半透明黒背景の標準字幕スタイルを想定。
        WCAG準拠の正確なコントラスト比を計算する。
        """
        # 白文字の相対輝度
        lum_white = self._relative_luminance(255, 255, 255)
        # 黒背景の相対輝度
        lum_black = self._relative_luminance(0, 0, 0)
        return self._contrast_ratio(lum_white, lum_black)

    @staticmethod
    def _relative_luminance(r: int, g: int, b: int) -> float:
        """sRGB色空間の相対輝度を計算する (WCAG 2.1準拠)。

        Args:
            r, g, b: 0-255のRGB値

        Returns:
            相対輝度 (0.0-1.0)
        """
        def linearize(c: int) -> float:
            srgb = c / 255.0
            if srgb <= 0.04045:
                return srgb / 12.92
            return ((srgb + 0.055) / 1.055) ** 2.4

        r_lin = linearize(r)
        g_lin = linearize(g)
        b_lin = linearize(b)
        return 0.2126 * r_lin + 0.7152 * g_lin + 0.0722 * b_lin

    @staticmethod
    def _contrast_ratio(lum1: float, lum2: float) -> float:
        """2つの相対輝度からコントラスト比を算出する (WCAG 2.1準拠)。

        Args:
            lum1, lum2: 相対輝度 (0.0-1.0)

        Returns:
            コントラスト比 (1.0-21.0)
        """
        lighter = max(lum1, lum2)
        darker = min(lum1, lum2)
        return (lighter + 0.05) / (darker + 0.05)

    def _calc_safe_area_compliance(
        self, width: int, height: int
    ) -> float:
        """セーフエリア準拠率を算出する。

        放送用セーフエリア (Action Safe: 93%, Title Safe: 90%) を想定。
        標準的な解像度であれば100%準拠とする。

        Args:
            width: 動画幅 (px)
            height: 動画高さ (px)

        Returns:
            準拠率 (0-100)
        """
        # 標準解像度: 1920x1080, 1280x720, 3840x2160
        standard_ratios = [16 / 9, 4 / 3]
        if height <= 0:
            return 0.0

        aspect = width / height
        is_standard = any(abs(aspect - r) < 0.05 for r in standard_ratios)

        if is_standard:
            # 標準アスペクト比: Title Safe Area (90%) を想定
            # 字幕がデフォルト位置（下部中央）にある場合は準拠
            return 100.0

        # 非標準アスペクト比は減点
        return 80.0

    def _calc_subtitle_total(
        self,
        chars_per_line: float,
        display_duration_avg: float,
        sync_offset_ms: float,
        line_break_quality: float,
        contrast_ratio: float,
        safe_area_compliance: float,
        font_consistency: float,
    ) -> float:
        """字幕品質の総合スコアを算出する (0-100)。

        配点:
        - 文字数: 15点
        - 表示時間: 15点
        - 同期精度: 20点
        - 改行品質: 15点
        - コントラスト比: 15点
        - セーフエリア: 10点
        - フォント一貫性: 10点
        """
        score = 0.0

        # 文字数 (15点): 13文字以下で満点、超過で減点
        if chars_per_line <= self.MAX_CHARS_PER_LINE:
            score += 15.0
        else:
            excess = chars_per_line - self.MAX_CHARS_PER_LINE
            score += max(0.0, 15.0 - excess * 2.0)

        # 表示時間 (15点): 1.5-7.0秒で満点
        if self.DISPLAY_DURATION_MIN <= display_duration_avg <= self.DISPLAY_DURATION_MAX:
            score += 15.0
        elif display_duration_avg < self.DISPLAY_DURATION_MIN:
            ratio = display_duration_avg / max(self.DISPLAY_DURATION_MIN, 0.01)
            score += 15.0 * ratio
        else:
            excess = display_duration_avg - self.DISPLAY_DURATION_MAX
            score += max(0.0, 15.0 - excess * 3.0)

        # 同期精度 (20点): 200ms以下で満点
        if sync_offset_ms <= self.SYNC_OFFSET_MAX_MS:
            score += 20.0
        else:
            excess = sync_offset_ms - self.SYNC_OFFSET_MAX_MS
            score += max(0.0, 20.0 - excess * 0.05)

        # 改行品質 (15点): 0-100 → 0-15
        score += (line_break_quality / 100.0) * 15.0

        # コントラスト比 (15点)
        contrast_score = self._score_contrast(contrast_ratio)
        score += (contrast_score / 100.0) * 15.0

        # セーフエリア (10点)
        score += (safe_area_compliance / 100.0) * 10.0

        # フォント一貫性 (10点)
        score += (font_consistency / 100.0) * 10.0

        return min(100.0, max(0.0, score))

    # ━━━ レポートヘルパー ━━━

    def _build_details(
        self,
        subtitle: Optional[SubtitleScore],
        visual: VisualScore,
        audio: AudioScore,
        encoding: EncodingScore,
    ) -> Dict[str, Any]:
        """品質レポートの詳細データを構築する。"""
        details: Dict[str, Any] = {
            "visual": asdict(visual),
            "audio": asdict(audio),
            "encoding": asdict(encoding),
        }
        if subtitle is not None:
            details["subtitle"] = asdict(subtitle)
        return details

    @staticmethod
    def _rank(score: float) -> str:
        """スコアをランクに変換する。"""
        if score >= 95:
            return "S"
        elif score >= 90:
            return "A"
        elif score >= 80:
            return "B"
        elif score >= 60:
            return "C"
        return "D"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ユーティリティ関数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _safe_float(val: Any, default: float = 0.0) -> float:
    """安全にfloatへ変換する。"""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    """安全にintへ変換する。"""
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# エントリポイント
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


if __name__ == "__main__":
    import sys

    print("=" * 60)
    print("統合品質ゲート — セルフテスト")
    print("=" * 60)

    # 基本インスタンス化テスト
    config = QualityConfig()
    gate = QualityGate(config)
    print(f"✅ QualityGate インスタンス化成功")
    print(f"   min_total_score: {config.min_total_score}")
    print(f"   weights: subtitle={config.subtitle_weight}, "
          f"visual={config.visual_weight}, "
          f"audio={config.audio_weight}, "
          f"encoding={config.encoding_weight}")

    # コントラスト比の計算テスト
    lum_w = QualityGate._relative_luminance(255, 255, 255)
    lum_b = QualityGate._relative_luminance(0, 0, 0)
    cr = QualityGate._contrast_ratio(lum_w, lum_b)
    print(f"✅ コントラスト比 (白/黒): {cr:.1f}:1 (期待: 21.0:1)")

    # スコア関数テスト
    print(f"✅ コントラスト スコア (21.0): {gate._score_contrast(21.0):.0f}点")
    print(f"✅ コントラスト スコア (4.5): {gate._score_contrast(4.5):.0f}点")
    print(f"✅ コントラスト スコア (3.0): {gate._score_contrast(3.0):.0f}点")
    print(f"✅ ラウドネス スコア (0.0dB偏差): {gate._score_loudness(0.0):.0f}点")
    print(f"✅ ラウドネス スコア (1.0dB偏差): {gate._score_loudness(1.0):.0f}点")
    print(f"✅ ラウドネス スコア (3.0dB偏差): {gate._score_loudness(3.0):.0f}点")
    print(f"✅ CRF スコア (18): {gate._score_crf(18):.0f}点")
    print(f"✅ CRF スコア (23): {gate._score_crf(23):.0f}点")
    print(f"✅ CRF スコア (28): {gate._score_crf(28):.0f}点")
    print(f"✅ フレームドロップ スコア (0): {gate._score_frame_drops(0):.0f}点")
    print(f"✅ フレームドロップ スコア (3): {gate._score_frame_drops(3):.0f}点")
    print(f"✅ フレームドロップ スコア (10): {gate._score_frame_drops(10):.0f}点")

    # ランク変換テスト
    for s in [100, 95, 90, 80, 60, 30]:
        print(f"   ランク {s}点: {QualityGate._rank(s)}")

    # ImprovementSuggestion生成テスト
    report = QualityReport(
        video_path="test.mp4",
        total_score=65.0,
        passed=False,
        subtitle_score=SubtitleScore(
            chars_per_line=18.0,
            display_duration_avg=0.8,
            sync_offset_ms=350.0,
            contrast_ratio=3.5,
            total=40.0,
        ),
        visual_score=VisualScore(contrast_ratio=3.5, total=50.0),
        audio_score=AudioScore(
            loudness_lufs=-20.0,
            loudness_deviation=6.0,
            total=30.0,
            available=True,
        ),
        encoding_score=EncodingScore(
            crf_value=28,
            frame_drop_count=5,
            total=40.0,
            available=True,
        ),
    )

    suggestions = gate.generate_improvement_report(report)
    print(f"\n✅ 改善提案: {len(suggestions)}件")
    for i, s in enumerate(suggestions, 1):
        print(f"   {i}. [{s.severity}] {s.category}: {s.suggestion[:60]}...")

    # 動画ファイルが引数で指定された場合は実際に評価
    if len(sys.argv) > 1:
        video = sys.argv[1]
        srt = sys.argv[2] if len(sys.argv) > 2 else None
        print(f"\n{'='*60}")
        print(f"動画評価: {video}")
        print(f"{'='*60}")
        try:
            result = gate.evaluate(video, srt)
            print(f"総合スコア: {result.total_score:.1f}点")
            print(f"合格判定: {'PASS ✅' if result.passed else 'FAIL ❌'}")
            print(f"ランク: {QualityGate._rank(result.total_score)}")
            if result.subtitle_score:
                print(f"字幕スコア: {result.subtitle_score.total:.1f}点")
            print(f"視覚スコア: {result.visual_score.total:.1f}点")
            print(f"音声スコア: {result.audio_score.total:.1f}点")
            print(f"エンコードスコア: {result.encoding_score.total:.1f}点")

            improvement = gate.generate_improvement_report(result)
            if improvement:
                print(f"\n改善提案:")
                for s in improvement:
                    print(f"  [{s.severity}] {s.suggestion}")
        except FileNotFoundError as e:
            print(f"❌ {e}")
    else:
        print("\n💡 動画ファイルを引数に渡すと実際に評価します:")
        print("   python quality_gate.py <video.mp4> [subtitle.srt]")

    print(f"\n{'='*60}")
    print("全セルフテスト完了")
    print(f"{'='*60}")
