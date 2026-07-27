"""NHK字幕品質スコアラー — 7軸100点満点の字幕品質スコアリング.

NHK放送基準およびM37.2仕様に準拠した字幕品質の自動評価:
1. 文字数/行 (≤13文字/行)            — 15点
2. 表示時間 (1.5〜7.0秒)              — 15点
3. 音声同期精度 (≤200ms遅延)          — 20点
4. 句読点・改行 (形態素解析ベース)      — 15点
5. コントラスト比 (WCAG 2.1 ≥4.5:1)   — 15点
6. セーフエリア (画面端≥10%)           — 10点
7. フォント一貫性 (design_tokens準拠)   — 10点
"""

import logging
import math
import os
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ============================================================
# design_tokens デフォルト値 (branding/design_tokens.json 準拠)
# ============================================================
DEFAULT_DESIGN_TOKENS = {
    "font_family": "Noto Sans JP",
    "font_size": 48,
    "font_color": "#FFFFFF",
    "outline_color": "#000000",
    "position_x_percent": 50.0,
    "position_y_percent": 85.0,
}


# ============================================================
# Data Classes
# ============================================================
@dataclass
class SubtitleEntry:
    """1件の字幕エントリ."""

    index: int
    start_time: float  # 秒
    end_time: float  # 秒
    text: str
    style: Optional[Dict[str, Any]] = None

    @property
    def duration(self) -> float:
        """表示時間（秒）."""
        return max(self.end_time - self.start_time, 0.0)

    @property
    def lines(self) -> List[str]:
        """改行で分割したテキスト行."""
        return self.text.split("\n") if self.text else []

    @property
    def char_count(self) -> int:
        """空白を除いた文字数."""
        return sum(len(line.strip()) for line in self.lines)


@dataclass
class AxisResult:
    """1軸分のスコア結果."""

    name: str
    score: float  # 0.0 - 配点上限
    max_score: float  # 配点上限
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def ratio(self) -> float:
        """達成率 (0.0-1.0)."""
        return self.score / self.max_score if self.max_score > 0 else 0.0


@dataclass
class SubtitleQualityReport:
    """字幕品質スコアリングの統合レポート."""

    total_score: float  # 0-100
    grade: str  # S / A / B / C / D
    axis_scores: Dict[str, AxisResult] = field(default_factory=dict)
    entry_count: int = 0
    problem_entries: List[Dict[str, Any]] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    scored_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        """辞書形式に変換."""
        return {
            "total_score": self.total_score,
            "grade": self.grade,
            "axis_scores": {k: asdict(v) for k, v in self.axis_scores.items()},
            "entry_count": self.entry_count,
            "problem_entries": self.problem_entries,
            "suggestions": self.suggestions,
            "scored_at": self.scored_at,
        }


# ============================================================
# SRT パーサー
# ============================================================
_SRT_TIME_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)


def _parse_timecode(tc: str) -> float:
    """SRTタイムコード文字列を秒に変換.

    Args:
        tc: "HH:MM:SS,mmm" 形式のタイムコード

    Returns:
        秒数 (float)

    Raises:
        ValueError: タイムコード形式が不正な場合
    """
    m = _SRT_TIME_RE.match(tc.strip())
    if not m:
        raise ValueError(f"不正なタイムコード形式: {tc!r}")
    h, mi, s, ms = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    return h * 3600 + mi * 60 + s + ms / 1000.0


def parse_srt(path: str) -> List[SubtitleEntry]:
    """SRTファイルをパースして SubtitleEntry のリストを返す.

    Args:
        path: .srt ファイルのパス

    Returns:
        パースされた SubtitleEntry のリスト

    Raises:
        FileNotFoundError: ファイルが存在しない場合
    """
    srt_path = Path(path)
    if not srt_path.exists():
        raise FileNotFoundError(f"SRTファイルが見つかりません: {path}")

    # BOM付きUTF-8にも対応
    content = srt_path.read_text(encoding="utf-8-sig")
    entries: List[SubtitleEntry] = []

    # ブロック分割: 空行で区切る
    blocks = re.split(r"\n\s*\n", content.strip())

    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 2:
            continue

        # 1行目: インデックス番号
        try:
            index = int(lines[0].strip())
        except ValueError:
            continue

        # 2行目: タイムコード
        time_line = lines[1].strip()
        arrow_match = re.search(r"-->", time_line)
        if not arrow_match:
            continue

        try:
            start_tc = time_line[: arrow_match.start()].strip()
            end_tc = time_line[arrow_match.end() :].strip()
            start_time = _parse_timecode(start_tc)
            end_time = _parse_timecode(end_tc)
        except ValueError as e:
            logger.warning("タイムコードパースエラー (entry %d): %s", index, e)
            continue

        # 3行目以降: テキスト
        text = "\n".join(lines[2:])

        entries.append(
            SubtitleEntry(
                index=index,
                start_time=start_time,
                end_time=end_time,
                text=text,
            )
        )

    return entries


# ============================================================
# 形態素解析 (簡易実装 + fugashi フォールバック)
# ============================================================
def _try_import_fugashi():
    """fugashiの利用可否を判定."""
    try:
        import fugashi  # noqa: F401

        return True
    except ImportError:
        return False


_HAS_FUGASHI = _try_import_fugashi()

# 日本語の文末・助詞・接続詞パターン（改行に適した位置）
_GOOD_BREAK_PATTERNS = re.compile(
    r"(?:"
    r"[。、！？!?…]"  # 句読点・感嘆符
    r"|[はがをにでとのもへや](?=[^\u3040-\u309F])"  # 助詞の後（次がひらがなでない）
    r"|[てでして](?=[^\u3040-\u309F])"  # 接続助詞
    r"|から|ので|けど|ため|ながら"  # 接続詞的表現
    r")$"
)

# 改行に不適切な位置（単語の途中での分割）
_BAD_BREAK_PATTERNS = re.compile(
    r"(?:"
    r"[ぁ-ん]$"  # ひらがな連続の途中（単語途中の可能性）
    r"|[ァ-ヴ]$"  # カタカナ連続の途中
    r")"
)


def _analyze_line_break_quality_fugashi(text: str) -> float:
    """fugashiを使った改行品質分析.

    Args:
        text: 改行を含む字幕テキスト

    Returns:
        品質スコア (0.0-1.0)
    """
    import fugashi

    tagger = fugashi.Tagger()
    lines = text.split("\n")
    if len(lines) <= 1:
        return 1.0  # 改行なしは問題なし

    score = 0.0
    break_count = len(lines) - 1

    for i in range(break_count):
        line = lines[i].rstrip()
        if not line:
            continue

        # 行末の形態素を取得
        words = tagger(line)
        if not words:
            score += 0.5
            continue

        last_word = words[-1]
        pos = last_word.feature.split(",")[0] if last_word.feature else ""

        # 助詞・助動詞・記号の後の改行は自然
        if pos in ("助詞", "助動詞", "記号", "補助記号"):
            score += 1.0
        # 動詞・形容詞の活用形末尾も許容
        elif pos in ("動詞", "形容詞") and len(words) > 1:
            score += 0.8
        # 名詞の後は微妙（連体修飾の途中かもしれない）
        elif pos == "名詞":
            score += 0.6
        else:
            score += 0.3

    return score / max(break_count, 1)


def _analyze_line_break_quality_regex(text: str) -> float:
    """正規表現ベースの簡易改行品質分析（fugashi不可時のフォールバック）.

    Args:
        text: 改行を含む字幕テキスト

    Returns:
        品質スコア (0.0-1.0)
    """
    lines = text.split("\n")
    if len(lines) <= 1:
        return 1.0

    score = 0.0
    break_count = len(lines) - 1

    for i in range(break_count):
        line = lines[i].rstrip()
        if not line:
            score += 0.5
            continue

        if _GOOD_BREAK_PATTERNS.search(line):
            score += 1.0
        elif _BAD_BREAK_PATTERNS.search(line):
            score += 0.2
        else:
            score += 0.5

    return score / max(break_count, 1)


def analyze_line_break_quality(text: str) -> float:
    """改行品質を分析する（fugashi優先、不可なら正規表現フォールバック）.

    Args:
        text: 字幕テキスト

    Returns:
        品質スコア (0.0-1.0)
    """
    if _HAS_FUGASHI:
        try:
            return _analyze_line_break_quality_fugashi(text)
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.warning("fugashi分析エラー、正規表現にフォールバック: %s", e)

    return _analyze_line_break_quality_regex(text)


# ============================================================
# WCAG コントラスト比計算
# ============================================================
def _hex_to_rgb(hex_color: str) -> tuple:
    """16進カラーコードをRGBタプルに変換.

    Args:
        hex_color: "#RRGGBB" 形式のカラーコード

    Returns:
        (R, G, B) タプル (0-255)
    """
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    return (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
    )


def _relative_luminance(rgb: tuple) -> float:
    """WCAG 2.1準拠の相対輝度を計算.

    Args:
        rgb: (R, G, B) タプル (0-255)

    Returns:
        相対輝度 (0.0-1.0)
    """

    def linearize(c: int) -> float:
        srgb = c / 255.0
        if srgb <= 0.04045:
            return srgb / 12.92
        return ((srgb + 0.055) / 1.055) ** 2.4

    r, g, b = linearize(rgb[0]), linearize(rgb[1]), linearize(rgb[2])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def calc_contrast_ratio(color1: str, color2: str) -> float:
    """2色間のWCAG 2.1準拠コントラスト比を計算.

    Args:
        color1: "#RRGGBB" 形式のカラーコード
        color2: "#RRGGBB" 形式のカラーコード

    Returns:
        コントラスト比 (1.0-21.0)
    """
    l1 = _relative_luminance(_hex_to_rgb(color1))
    l2 = _relative_luminance(_hex_to_rgb(color2))
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


# ============================================================
# NHKSubtitleScorer メインクラス
# ============================================================
class NHKSubtitleScorer:
    """NHK放送基準に基づく7軸字幕品質スコアラー.

    7つの品質指標で字幕を100点満点で評価する:
    - 文字数/行 (15点): 1行あたり≤13文字
    - 表示時間 (15点): 1.5〜7.0秒
    - 音声同期精度 (20点): 音声開始からの遅延≤200ms
    - 句読点・改行 (15点): 形態素解析による自然な改行位置
    - コントラスト比 (15点): WCAG 2.1基準≥4.5:1
    - セーフエリア (10点): 画面端からの距離≥10%
    - フォント一貫性 (10点): design_tokens準拠

    Usage:
        scorer = NHKSubtitleScorer()
        report = scorer.score("subtitles.srt")
        print(f"Total: {report.total_score} / Grade: {report.grade}")
    """

    # === 配点 ===
    WEIGHT_CHARS_PER_LINE = 15.0
    WEIGHT_DISPLAY_TIME = 15.0
    WEIGHT_AUDIO_SYNC = 20.0
    WEIGHT_LINE_BREAK = 15.0
    WEIGHT_CONTRAST = 15.0
    WEIGHT_SAFE_AREA = 10.0
    WEIGHT_FONT_CONSISTENCY = 10.0

    # === 閾値 ===
    MAX_CHARS_PER_LINE = 13  # NHK基準: 1行あたり最大文字数
    DISPLAY_TIME_MIN = 1.5  # 最小表示時間（秒）
    DISPLAY_TIME_MAX = 7.0  # 最大表示時間（秒）
    AUDIO_SYNC_THRESHOLD_MS = 200  # 音声同期許容遅延（ミリ秒）
    CONTRAST_RATIO_MIN = 4.5  # WCAG 2.1 AA基準
    SAFE_AREA_MIN_PERCENT = 10.0  # 画面端からの最小距離（%）

    def __init__(
        self,
        design_tokens: Optional[Dict[str, Any]] = None,
    ) -> None:
        """初期化.

        Args:
            design_tokens: ブランドデザイントークン。
                           Noneの場合はデフォルト値を使用。
        """
        self.design_tokens = design_tokens or DEFAULT_DESIGN_TOKENS.copy()

    # ----------------------------------------------------------
    # Public API
    # ----------------------------------------------------------
    def score(
        self, subtitle_path: str, audio_path: Optional[str] = None
    ) -> SubtitleQualityReport:
        """SRTファイルから字幕品質をスコアリング.

        Args:
            subtitle_path: .srtファイルのパス
            audio_path: 音声ファイルのパス（音声同期精度の評価に使用。
                        Noneの場合は同期精度を満点として扱う）

        Returns:
            SubtitleQualityReport
        """
        entries = parse_srt(subtitle_path)
        return self._evaluate(entries, audio_path=audio_path)

    def score_text(
        self, entries: List[SubtitleEntry]
    ) -> SubtitleQualityReport:
        """SubtitleEntry リストから直接スコアリング.

        Args:
            entries: 字幕エントリのリスト

        Returns:
            SubtitleQualityReport
        """
        return self._evaluate(entries, audio_path=None)

    # ----------------------------------------------------------
    # 内部評価エンジン
    # ----------------------------------------------------------
    def _evaluate(
        self,
        entries: List[SubtitleEntry],
        audio_path: Optional[str] = None,
    ) -> SubtitleQualityReport:
        """全7軸を評価し統合レポートを生成."""
        if not entries:
            return SubtitleQualityReport(
                total_score=0.0,
                grade="D",
                entry_count=0,
                suggestions=["字幕エントリが存在しません。"],
            )

        problem_entries: List[Dict[str, Any]] = []

        # 各軸の評価
        ax_chars = self._score_chars_per_line(entries, problem_entries)
        ax_display = self._score_display_time(entries, problem_entries)
        ax_sync = self._score_audio_sync(entries, audio_path, problem_entries)
        ax_break = self._score_line_break(entries, problem_entries)
        ax_contrast = self._score_contrast(entries, problem_entries)
        ax_safe = self._score_safe_area(entries, problem_entries)
        ax_font = self._score_font_consistency(entries, problem_entries)

        axis_scores = {
            "chars_per_line": ax_chars,
            "display_time": ax_display,
            "audio_sync": ax_sync,
            "line_break": ax_break,
            "contrast": ax_contrast,
            "safe_area": ax_safe,
            "font_consistency": ax_font,
        }

        total_score = sum(ax.score for ax in axis_scores.values())
        total_score = round(min(total_score, 100.0), 1)
        grade = self._compute_grade(total_score)

        # 改善提案の生成
        suggestions = self._generate_suggestions(axis_scores, problem_entries)

        return SubtitleQualityReport(
            total_score=total_score,
            grade=grade,
            axis_scores=axis_scores,
            entry_count=len(entries),
            problem_entries=problem_entries,
            suggestions=suggestions,
        )

    # ----------------------------------------------------------
    # 軸1: 文字数/行 (15点)
    # ----------------------------------------------------------
    def _score_chars_per_line(
        self,
        entries: List[SubtitleEntry],
        problems: List[Dict[str, Any]],
    ) -> AxisResult:
        """1行あたりの文字数を評価.

        NHK基準: 1行あたり13文字以下。
        超過行の割合に応じて減点。
        """
        total_lines = 0
        violation_lines = 0
        max_chars_seen = 0

        for entry in entries:
            for line in entry.lines:
                cleaned = line.strip()
                if not cleaned:
                    continue
                total_lines += 1
                char_count = len(cleaned)
                max_chars_seen = max(max_chars_seen, char_count)

                if char_count > self.MAX_CHARS_PER_LINE:
                    violation_lines += 1
                    problems.append({
                        "entry_index": entry.index,
                        "axis": "chars_per_line",
                        "detail": f"行文字数超過: {char_count}文字 (上限{self.MAX_CHARS_PER_LINE})",
                        "text": cleaned[:30],
                    })

        if total_lines == 0:
            return AxisResult(
                name="文字数/行",
                score=self.WEIGHT_CHARS_PER_LINE,
                max_score=self.WEIGHT_CHARS_PER_LINE,
            )

        compliance_rate = 1.0 - (violation_lines / total_lines)
        score = round(self.WEIGHT_CHARS_PER_LINE * compliance_rate, 2)

        return AxisResult(
            name="文字数/行",
            score=score,
            max_score=self.WEIGHT_CHARS_PER_LINE,
            details={
                "total_lines": total_lines,
                "violation_lines": violation_lines,
                "max_chars_seen": max_chars_seen,
                "compliance_rate": round(compliance_rate, 3),
            },
        )

    # ----------------------------------------------------------
    # 軸2: 表示時間 (15点)
    # ----------------------------------------------------------
    def _score_display_time(
        self,
        entries: List[SubtitleEntry],
        problems: List[Dict[str, Any]],
    ) -> AxisResult:
        """字幕の表示時間を評価.

        NHK基準: 1.5秒〜7.0秒。
        範囲外エントリの割合に応じて減点。
        """
        violations = 0
        too_short = 0
        too_long = 0

        for entry in entries:
            dur = entry.duration
            if dur < self.DISPLAY_TIME_MIN:
                violations += 1
                too_short += 1
                problems.append({
                    "entry_index": entry.index,
                    "axis": "display_time",
                    "detail": f"表示時間不足: {dur:.2f}秒 (下限{self.DISPLAY_TIME_MIN}秒)",
                })
            elif dur > self.DISPLAY_TIME_MAX:
                violations += 1
                too_long += 1
                problems.append({
                    "entry_index": entry.index,
                    "axis": "display_time",
                    "detail": f"表示時間超過: {dur:.2f}秒 (上限{self.DISPLAY_TIME_MAX}秒)",
                })

        total = len(entries)
        compliance_rate = 1.0 - (violations / total) if total > 0 else 1.0
        score = round(self.WEIGHT_DISPLAY_TIME * compliance_rate, 2)

        return AxisResult(
            name="表示時間",
            score=score,
            max_score=self.WEIGHT_DISPLAY_TIME,
            details={
                "total_entries": total,
                "too_short": too_short,
                "too_long": too_long,
                "compliance_rate": round(compliance_rate, 3),
            },
        )

    # ----------------------------------------------------------
    # 軸3: 音声同期精度 (20点)
    # ----------------------------------------------------------
    def _score_audio_sync(
        self,
        entries: List[SubtitleEntry],
        audio_path: Optional[str],
        problems: List[Dict[str, Any]],
    ) -> AxisResult:
        """音声開始からの字幕表示遅延を評価.

        音声ファイルが指定されていない場合は満点を返す（測定不可）。
        実際の音声解析にはffprobe/Whisperが必要だが、
        本実装ではstyleに 'audio_offset_ms' が含まれている場合のみ評価。
        """
        if audio_path is None:
            return AxisResult(
                name="音声同期精度",
                score=self.WEIGHT_AUDIO_SYNC,
                max_score=self.WEIGHT_AUDIO_SYNC,
                details={"status": "audio_not_provided", "note": "音声パス未指定のため満点扱い"},
            )

        # style に audio_offset_ms が含まれるエントリのみ評価
        evaluated = 0
        violations = 0

        for entry in entries:
            if entry.style and "audio_offset_ms" in entry.style:
                evaluated += 1
                offset_ms = abs(entry.style["audio_offset_ms"])
                if offset_ms > self.AUDIO_SYNC_THRESHOLD_MS:
                    violations += 1
                    problems.append({
                        "entry_index": entry.index,
                        "axis": "audio_sync",
                        "detail": f"同期遅延: {offset_ms}ms (閾値{self.AUDIO_SYNC_THRESHOLD_MS}ms)",
                    })

        if evaluated == 0:
            # audio_offset_msデータがない場合も満点扱い
            return AxisResult(
                name="音声同期精度",
                score=self.WEIGHT_AUDIO_SYNC,
                max_score=self.WEIGHT_AUDIO_SYNC,
                details={"status": "no_offset_data", "note": "オフセットデータなし（満点扱い）"},
            )

        compliance_rate = 1.0 - (violations / evaluated)
        score = round(self.WEIGHT_AUDIO_SYNC * compliance_rate, 2)

        return AxisResult(
            name="音声同期精度",
            score=score,
            max_score=self.WEIGHT_AUDIO_SYNC,
            details={
                "evaluated": evaluated,
                "violations": violations,
                "compliance_rate": round(compliance_rate, 3),
            },
        )

    # ----------------------------------------------------------
    # 軸4: 句読点・改行 (15点)
    # ----------------------------------------------------------
    def _score_line_break(
        self,
        entries: List[SubtitleEntry],
        problems: List[Dict[str, Any]],
    ) -> AxisResult:
        """改行位置の文法的な自然さを評価.

        形態素解析（fugashi利用可能時）または正規表現ベースの
        簡易分析で、改行位置の適切さを判定する。
        """
        if not entries:
            return AxisResult(
                name="句読点・改行",
                score=self.WEIGHT_LINE_BREAK,
                max_score=self.WEIGHT_LINE_BREAK,
            )

        total_quality = 0.0
        multi_line_count = 0

        for entry in entries:
            if len(entry.lines) <= 1:
                # 1行の字幕は改行品質の評価対象外（満点扱い）
                total_quality += 1.0
            else:
                multi_line_count += 1
                quality = analyze_line_break_quality(entry.text)
                total_quality += quality

                if quality < 0.5:
                    problems.append({
                        "entry_index": entry.index,
                        "axis": "line_break",
                        "detail": f"不自然な改行位置 (品質スコア: {quality:.2f})",
                        "text": entry.text[:50],
                    })

        avg_quality = total_quality / len(entries)
        score = round(self.WEIGHT_LINE_BREAK * avg_quality, 2)

        return AxisResult(
            name="句読点・改行",
            score=score,
            max_score=self.WEIGHT_LINE_BREAK,
            details={
                "avg_quality": round(avg_quality, 3),
                "multi_line_entries": multi_line_count,
                "total_entries": len(entries),
            },
        )

    # ----------------------------------------------------------
    # 軸5: コントラスト比 (15点)
    # ----------------------------------------------------------
    def _score_contrast(
        self,
        entries: List[SubtitleEntry],
        problems: List[Dict[str, Any]],
    ) -> AxisResult:
        """WCAG 2.1基準のコントラスト比を評価.

        エントリのstyleにfont_color / outline_colorが
        含まれている場合はそれを使用。
        含まれていない場合はdesign_tokensのデフォルト値を使用。
        """
        default_fg = self.design_tokens.get("font_color", "#FFFFFF")
        default_bg = self.design_tokens.get("outline_color", "#000000")

        ratios: List[float] = []
        violations = 0

        for entry in entries:
            fg = default_fg
            bg = default_bg
            if entry.style:
                fg = entry.style.get("font_color", default_fg)
                bg = entry.style.get("outline_color", default_bg)

            try:
                ratio = calc_contrast_ratio(fg, bg)
            except (ValueError, IndexError):
                ratio = 0.0

            ratios.append(ratio)
            if ratio < self.CONTRAST_RATIO_MIN:
                violations += 1
                problems.append({
                    "entry_index": entry.index,
                    "axis": "contrast",
                    "detail": f"コントラスト比不足: {ratio:.2f}:1 (基準{self.CONTRAST_RATIO_MIN}:1)",
                })

        total = len(entries)
        compliance_rate = 1.0 - (violations / total) if total > 0 else 1.0
        avg_ratio = sum(ratios) / len(ratios) if ratios else 0.0
        score = round(self.WEIGHT_CONTRAST * compliance_rate, 2)

        return AxisResult(
            name="コントラスト比",
            score=score,
            max_score=self.WEIGHT_CONTRAST,
            details={
                "avg_ratio": round(avg_ratio, 2),
                "min_ratio": round(min(ratios), 2) if ratios else 0.0,
                "violations": violations,
                "compliance_rate": round(compliance_rate, 3),
            },
        )

    # ----------------------------------------------------------
    # 軸6: セーフエリア (10点)
    # ----------------------------------------------------------
    def _score_safe_area(
        self,
        entries: List[SubtitleEntry],
        problems: List[Dict[str, Any]],
    ) -> AxisResult:
        """字幕の画面端からの距離（セーフエリア）を評価.

        styleの position_x_percent / position_y_percent で判定。
        styleがない場合はdesign_tokensのデフォルト値を使用。
        """
        default_x = self.design_tokens.get("position_x_percent", 50.0)
        default_y = self.design_tokens.get("position_y_percent", 85.0)

        violations = 0

        for entry in entries:
            x = default_x
            y = default_y
            if entry.style:
                x = entry.style.get("position_x_percent", default_x)
                y = entry.style.get("position_y_percent", default_y)

            # 画面端からの距離チェック
            margin_left = x
            margin_right = 100.0 - x
            margin_top = y
            margin_bottom = 100.0 - y

            min_margin = min(margin_left, margin_right, margin_top, margin_bottom)

            if min_margin < self.SAFE_AREA_MIN_PERCENT:
                violations += 1
                problems.append({
                    "entry_index": entry.index,
                    "axis": "safe_area",
                    "detail": f"セーフエリア違反: 最小余白{min_margin:.1f}% (基準{self.SAFE_AREA_MIN_PERCENT}%)",
                })

        total = len(entries)
        compliance_rate = 1.0 - (violations / total) if total > 0 else 1.0
        score = round(self.WEIGHT_SAFE_AREA * compliance_rate, 2)

        return AxisResult(
            name="セーフエリア",
            score=score,
            max_score=self.WEIGHT_SAFE_AREA,
            details={
                "violations": violations,
                "compliance_rate": round(compliance_rate, 3),
            },
        )

    # ----------------------------------------------------------
    # 軸7: フォント一貫性 (10点)
    # ----------------------------------------------------------
    def _score_font_consistency(
        self,
        entries: List[SubtitleEntry],
        problems: List[Dict[str, Any]],
    ) -> AxisResult:
        """全字幕のフォント設定がdesign_tokensと一貫しているかを評価.

        style が設定されていないエントリはデフォルト使用とみなし問題なし。
        style が設定されている場合、font_family / font_size が
        design_tokens と一致しているかチェック。
        """
        expected_family = self.design_tokens.get("font_family", "Noto Sans JP")
        expected_size = self.design_tokens.get("font_size", 48)

        styled_count = 0
        violations = 0
        font_families_seen: set = set()

        for entry in entries:
            if not entry.style:
                continue  # デフォルト使用 = 問題なし

            styled_count += 1

            family = entry.style.get("font_family")
            size = entry.style.get("font_size")

            if family:
                font_families_seen.add(family)

            is_violation = False
            details_parts: List[str] = []

            if family and family != expected_family:
                is_violation = True
                details_parts.append(
                    f"フォント不一致: {family} (期待: {expected_family})"
                )

            if size is not None and size != expected_size:
                is_violation = True
                details_parts.append(
                    f"サイズ不一致: {size}px (期待: {expected_size}px)"
                )

            if is_violation:
                violations += 1
                problems.append({
                    "entry_index": entry.index,
                    "axis": "font_consistency",
                    "detail": "; ".join(details_parts),
                })

        if styled_count == 0:
            # style情報なし = 全エントリがデフォルト使用 → 満点
            return AxisResult(
                name="フォント一貫性",
                score=self.WEIGHT_FONT_CONSISTENCY,
                max_score=self.WEIGHT_FONT_CONSISTENCY,
                details={"status": "all_default", "note": "全エントリがデフォルトスタイル使用"},
            )

        compliance_rate = 1.0 - (violations / styled_count)
        score = round(self.WEIGHT_FONT_CONSISTENCY * compliance_rate, 2)

        return AxisResult(
            name="フォント一貫性",
            score=score,
            max_score=self.WEIGHT_FONT_CONSISTENCY,
            details={
                "styled_entries": styled_count,
                "violations": violations,
                "font_families_seen": sorted(font_families_seen),
                "compliance_rate": round(compliance_rate, 3),
            },
        )

    # ----------------------------------------------------------
    # グレード判定
    # ----------------------------------------------------------
    @staticmethod
    def _compute_grade(score: float) -> str:
        """100点満点スコアからS/A/B/C/Dグレードを判定.

        Args:
            score: 合計スコア (0-100)

        Returns:
            グレード文字列
        """
        if score >= 90:
            return "S"
        elif score >= 75:
            return "A"
        elif score >= 60:
            return "B"
        elif score >= 40:
            return "C"
        else:
            return "D"

    # ----------------------------------------------------------
    # 改善提案生成
    # ----------------------------------------------------------
    @staticmethod
    def _generate_suggestions(
        axis_scores: Dict[str, AxisResult],
        problem_entries: List[Dict[str, Any]],
    ) -> List[str]:
        """軸スコアと問題エントリから改善提案を生成."""
        suggestions: List[str] = []

        for key, ax in axis_scores.items():
            if ax.ratio >= 0.9:
                continue  # 90%以上は提案不要

            if key == "chars_per_line":
                count = ax.details.get("violation_lines", 0)
                suggestions.append(
                    f"【文字数/行】{count}行が13文字を超過しています。"
                    f"改行位置の見直しで可読性が向上します。"
                )
            elif key == "display_time":
                short = ax.details.get("too_short", 0)
                long = ax.details.get("too_long", 0)
                parts = []
                if short > 0:
                    parts.append(f"{short}件が1.5秒未満")
                if long > 0:
                    parts.append(f"{long}件が7.0秒超過")
                if parts:
                    suggestions.append(
                        f"【表示時間】{'、'.join(parts)}。"
                        f"表示時間を1.5〜7.0秒に収めてください。"
                    )
            elif key == "audio_sync":
                v = ax.details.get("violations", 0)
                if v > 0:
                    suggestions.append(
                        f"【音声同期】{v}件の字幕が音声と200ms以上ズレています。"
                        f"Whisper forced alignmentの再実行を推奨します。"
                    )
            elif key == "line_break":
                avg = ax.details.get("avg_quality", 0)
                suggestions.append(
                    f"【句読点・改行】改行品質スコアが{avg:.2f}です。"
                    f"助詞・句読点の後での改行を推奨します。"
                )
            elif key == "contrast":
                v = ax.details.get("violations", 0)
                if v > 0:
                    suggestions.append(
                        f"【コントラスト】{v}件がWCAG AA基準(4.5:1)未満です。"
                        f"フォント色・アウトライン色の見直しを推奨します。"
                    )
            elif key == "safe_area":
                v = ax.details.get("violations", 0)
                if v > 0:
                    suggestions.append(
                        f"【セーフエリア】{v}件が画面端10%以内に配置されています。"
                        f"字幕位置をセーフエリア内に移動してください。"
                    )
            elif key == "font_consistency":
                v = ax.details.get("violations", 0)
                if v > 0:
                    suggestions.append(
                        f"【フォント一貫性】{v}件がdesign_tokensと不一致です。"
                        f"フォント設定を統一してください。"
                    )

        return suggestions


# ============================================================
# CLI / テスト用エントリーポイント
# ============================================================
if __name__ == "__main__":
    import json
    import sys

    print("=" * 60)
    print("NHK字幕品質スコアラー — テスト実行")
    print("=" * 60)

    # テスト用のSubtitleEntry生成
    test_entries = [
        SubtitleEntry(
            index=1,
            start_time=0.0,
            end_time=3.0,
            text="こんにちは、世界",
        ),
        SubtitleEntry(
            index=2,
            start_time=3.5,
            end_time=6.0,
            text="NHK放送基準に\n基づくテスト",
        ),
        SubtitleEntry(
            index=3,
            start_time=6.5,
            end_time=9.5,
            text="字幕品質スコアリング",
        ),
        SubtitleEntry(
            index=4,
            start_time=10.0,
            end_time=13.0,
            text="この字幕は十三文字以内です",
        ),
        SubtitleEntry(
            index=5,
            start_time=13.5,
            end_time=14.0,  # 0.5秒 → 表示時間不足
            text="短すぎ",
        ),
        SubtitleEntry(
            index=6,
            start_time=15.0,
            end_time=23.0,  # 8.0秒 → 表示時間超過
            text="この字幕は長すぎる表示時間",
        ),
        SubtitleEntry(
            index=7,
            start_time=24.0,
            end_time=27.0,
            text="この行は十四文字を超過しています",  # 15文字 > 13
        ),
    ]

    scorer = NHKSubtitleScorer()
    report = scorer.score_text(test_entries)

    print(f"\n📊 総合スコア: {report.total_score}/100 (グレード: {report.grade})")
    print(f"📝 エントリ数: {report.entry_count}")

    print("\n--- 軸別スコア ---")
    for key, ax in report.axis_scores.items():
        bar_len = int(ax.ratio * 20)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        print(f"  {ax.name:<12} [{bar}] {ax.score:.1f}/{ax.max_score:.0f}")

    if report.problem_entries:
        print(f"\n⚠️  問題エントリ: {len(report.problem_entries)}件")
        for p in report.problem_entries[:5]:
            print(f"  #{p['entry_index']} [{p['axis']}] {p['detail']}")
        if len(report.problem_entries) > 5:
            print(f"  ... 他 {len(report.problem_entries) - 5}件")

    if report.suggestions:
        print("\n💡 改善提案:")
        for s in report.suggestions:
            print(f"  • {s}")

    print("\n--- JSON出力 ---")
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))

    # SRTパーサーテスト（ファイルが指定された場合）
    if len(sys.argv) > 1:
        srt_file = sys.argv[1]
        print(f"\n\n{'='*60}")
        print(f"SRTファイル評価: {srt_file}")
        print(f"{'='*60}")
        file_report = scorer.score(srt_file)
        print(f"📊 総合スコア: {file_report.total_score}/100 (グレード: {file_report.grade})")
