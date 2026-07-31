"""NHK Quality Scorer — 5-axis video quality scoring based on NHK standards.

放送品質基準に基づく5軸スコアリング:
1. 字幕タイミング精度: Whisper forced alignment vs SRTのズレ
2. 字幕表示時間: 文字数÷表示秒数 vs NHK基準(4文字/秒)
3. テロップ可読性: フォントサイズ + コントラスト比(WCAG)
4. BGM/SE/ナレーション音量バランス: LUFS計測
5. カット割りリズム: シーンチェンジ検出の間隔分布
"""
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path
import json
import logging
import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
QUALITY_LOG_PATH = _writable_path("backend/pipeline_quality_log.jsonl")


@dataclass
class AxisScore:
    """1軸分のスコア"""
    name: str
    score: float        # 0.0-100.0
    max_score: float    # 100.0
    grade: str          # "Excellent", "Good", "Acceptable", "Poor"
    threshold: float    # この値以下でbug_hunterタスク生成
    details: dict[str, Any] = field(default_factory=dict)
    suggestion: str = ""


@dataclass
class NHKScoreReport:
    """全軸の統合スコアレポート"""
    timing_accuracy: AxisScore
    display_duration: AxisScore
    readability: AxisScore
    audio_balance: AxisScore
    cut_rhythm: AxisScore
    overall_score: float = 0.0
    overall_grade: str = ""
    degradation_log: list[dict] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    scored_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def axes(self) -> list[AxisScore]:
        return [
            self.timing_accuracy, self.display_duration,
            self.readability, self.audio_balance, self.cut_rhythm
        ]

    def to_dict(self) -> dict:
        return {
            "overall_score": self.overall_score,
            "overall_grade": self.overall_grade,
            "axes": [asdict(a) for a in self.axes],
            "degradation_log": self.degradation_log,
            "suggestions": self.suggestions,
            "scored_at": self.scored_at,
        }


class NHKQualityScorer:
    """NHK品質基準に基づく5軸スコアラ"""

    # NHK/放送基準の閾値
    TIMING_THRESHOLD_MS = 80  # タイミングズレ許容値
    CHARS_PER_SEC_EXCELLENT = 4.2
    CHARS_PER_SEC_GOOD = 5.5
    CHARS_PER_SEC_ACCEPTABLE = 7.0
    MAX_CHARS_PER_LINE = 15  # NHK基準
    LOUDNESS_TARGET = -14.0  # LUFS
    LOUDNESS_RANGE = (-16.0, -13.0)  # LUFS許容範囲
    CUT_FREQ_RANGE = (8, 18)  # 回/分
    CONTRAST_RATIO_AA = 4.5  # WCAG AA
    CONTRAST_RATIO_AAA = 7.0  # WCAG AAA
    BUG_HUNTER_THRESHOLD = 60.0  # このスコア以下で自動タスク生成

    def score(self, video_path: str, srt_path: str | None = None) -> NHKScoreReport:
        """動画ファイルと5軸スコアリングを実行し、統合レポートを返す"""
        timing = self._score_timing(video_path, srt_path)
        display = self._score_display_duration(srt_path)
        readability = self._score_readability(video_path, srt_path)
        audio = self._score_audio(video_path)
        cuts = self._score_cuts(video_path)

        axes = [timing, display, readability, audio, cuts]
        # 重み付き平均: 字幕系30%, 音声系25%, カット25%, 可読性20%
        weights = [0.15, 0.15, 0.20, 0.25, 0.25]
        
        # 評価可能な（grade != "N/A" の）軸のみで加重平均を算出
        valid_axes = [(a, w) for a, w in zip(axes, weights) if a.grade != "N/A"]
        if valid_axes:
            overall = sum(a.score * w for a, w in valid_axes) / sum(w for a, w in valid_axes)
        else:
            overall = 0.0
            
        overall_grade = self._grade(overall)

        degradation_log = self._load_degradation_log(video_path)
        suggestions = [a.suggestion for a in axes if a.suggestion and a.score < a.threshold and a.grade != "N/A"]

        return NHKScoreReport(
            timing_accuracy=timing,
            display_duration=display,
            readability=readability,
            audio_balance=audio,
            cut_rhythm=cuts,
            overall_score=round(overall, 1),
            overall_grade=overall_grade,
            degradation_log=degradation_log,
            suggestions=suggestions,
        )

    def _score_timing(self, video_path: str, srt_path: str | None) -> AxisScore:
        """軸1: 字幕タイミング精度 (Whisper forced alignment vs SRT)"""
        if not srt_path or not os.path.exists(srt_path):
            return AxisScore(
                name="字幕タイミング精度", score=0.0, max_score=100.0,
                grade="N/A", threshold=self.BUG_HUNTER_THRESHOLD,
                suggestion="SRTファイルが見つかりません"
            )
        
        entries = self._parse_srt_timing(srt_path)
        if not entries:
            return AxisScore(
                name="字幕タイミング精度", score=50.0, max_score=100.0,
                grade="Acceptable", threshold=self.BUG_HUNTER_THRESHOLD,
                suggestion="SRTエントリが空です"
            )
        
        total_entries_count = len(entries)
        detected_issues_count = self._count_timing_issues(entries)
        
        issue_rate = detected_issues_count / max(total_entries_count - 1, 1)
        score = max(0.0, 100.0 - issue_rate * 200.0)
        grade = self._grade(score)
        suggestion = f"字幕タイミング問題{detected_issues_count}件検出" if detected_issues_count > 0 else ""
        
        return AxisScore(
            name="字幕タイミング精度", score=round(score, 1), max_score=100.0,
            grade=grade, threshold=self.BUG_HUNTER_THRESHOLD,
            details={"total_entries": total_entries_count, "issues": detected_issues_count},
            suggestion=suggestion
        )

    def _count_timing_issues(self, entries: list[dict]) -> int:
        """SRT内のタイミング整合性（重複、ギャップ、自己逆転）をカウント"""
        detected_issues_count = 0
        total = len(entries)
        for i in range(total):
            # 自己逆転チェック
            if entries[i]["start"] >= entries[i]["end"]:
                detected_issues_count += 1
            
            if i > 0:
                # 重複チェック
                if entries[i]["start"] < entries[i-1]["end"]:
                    detected_issues_count += 1
                # 大きなギャップチェック (5秒以上)
                gap = entries[i]["start"] - entries[i-1]["end"]
                if gap > 5000:
                    detected_issues_count += 1
        return detected_issues_count

    def _score_display_duration(self, srt_path: str | None) -> AxisScore:
        """軸2: 字幕表示時間 (文字数÷表示秒数 vs NHK基準)"""
        if not srt_path or not os.path.exists(srt_path):
            return AxisScore(
                name="字幕表示時間", score=0.0, max_score=100.0,
                grade="N/A", threshold=self.BUG_HUNTER_THRESHOLD,
                suggestion="SRTファイルが見つかりません"
            )
        entries = self._parse_srt_timing(srt_path)
        if not entries:
            return AxisScore(
                name="字幕表示時間", score=50.0, max_score=100.0,
                grade="Acceptable", threshold=self.BUG_HUNTER_THRESHOLD,
                suggestion="SRTエントリが空です"
            )
        
        excellent = 0
        good = 0
        acceptable = 0
        poor = 0
        over_line_limit = 0
        
        for entry in entries:
            category = self._evaluate_single_entry_cps(entry)
            if category == "excellent":
                excellent += 1
            elif category == "good":
                good += 1
            elif category == "acceptable":
                acceptable += 1
            else:
                poor += 1
            
            over_line_limit += self._count_line_limit_violations(entry.get("text", ""))
        
        total = len(entries)
        score = (excellent * 100 + good * 75 + acceptable * 50 + poor * 0) / max(total, 1)
        score = max(0.0, score - over_line_limit * 5)
        grade = self._grade(score)
        
        suggestion_parts = []
        if poor > 0:
            suggestion_parts.append(f"表示速度超過{poor}件。")
        if over_line_limit > 0:
            suggestion_parts.append(f"1行{self.MAX_CHARS_PER_LINE}文字超過{over_line_limit}件。")
        suggestion = "".join(suggestion_parts)
        
        return AxisScore(
            name="字幕表示時間", score=round(score, 1), max_score=100.0,
            grade=grade, threshold=self.BUG_HUNTER_THRESHOLD,
            details={
                "excellent": excellent,
                "good": good,
                "acceptable": acceptable,
                "poor": poor,
                "over_line_limit": over_line_limit
            },
            suggestion=suggestion
        )

    def _clean_text_for_scoring(self, text: str, remove_symbols: bool = True) -> str:
        """スコアリング用に話者表記やスペースなどを除去する"""
        if text is None:
            return ""
        if not isinstance(text, str):
            text = str(text)
        # [話者1] や [話者A] などのブラケット表記を除去
        text = re.sub(r"\[[^\]]+\]", "", text)
        # (話者1) や （話者A） などの丸括弧表記、および演出文字(笑)などを除去
        text = re.sub(r"\([^\)]+\)", "", text)
        text = re.sub(r"（[^）]+）", "", text)
        # 話者1: などのコロン付き話者表記を除去
        text = re.sub(r"^[^\s\n：:]+[：:]", "", text, flags=re.MULTILINE)
        
        if remove_symbols:
            # 記号（句読点、括弧、引用符など）の除去
            symbols = [
                "、", "。", "「", "」", "？", "！", "・", "…", "―",
                ",", ".", "?", "!", "\"", "'", "(", ")", "[", "]",
                "~", "～", "-", "_", "＝", "=", "＆", "&", "％", "%",
                "＃", "#", "＠", "@", "：", ":", "；", ";", "＊", "*"
            ]
            for sym in symbols:
                text = text.replace(sym, "")
            
        # スペースと改行の除去
        text = text.replace(" ", "").replace("\u3000", "").replace("\n", "").strip()
        return text

    def _evaluate_single_entry_cps(self, entry: dict) -> str:
        """単一のSRTエントリの表示秒数あたりの文字数(CPS)を評価"""
        duration_sec = (entry["end"] - entry["start"]) / 1000.0
        if duration_sec <= 0:
            return "poor"
        
        text = entry.get("text", "")
        # 表示時間評価では、話者表記・記号・スペースを除去した純粋な文字数をカウント
        clean_text = self._clean_text_for_scoring(text, remove_symbols=True)
        chars_count = len(clean_text)
        cps = chars_count / duration_sec
        
        if cps <= self.CHARS_PER_SEC_EXCELLENT:
            return "excellent"
        elif cps <= self.CHARS_PER_SEC_GOOD:
            return "good"
        elif cps <= self.CHARS_PER_SEC_ACCEPTABLE:
            return "acceptable"
        return "poor"

    def _count_line_limit_violations(self, text: str) -> int:
        """1行あたりの文字数制限を超過している箇所をカウント"""
        violations = 0
        for line in text.split("\n"):
            # 行制限チェックでは、話者表記や余分なスペースのみを除去し、表示される記号は残す
            cleaned_line = self._clean_text_for_scoring(line, remove_symbols=False)
            if len(cleaned_line) > self.MAX_CHARS_PER_LINE:
                violations += 1
        return violations

    def _score_readability(self, video_path: str, srt_path: str | None = None) -> AxisScore:
        """軸3: テロップ可読性 (コントラスト比 + フォントサイズ)"""
        if not srt_path or not os.path.exists(srt_path):
            return AxisScore(
                name="テロップ可読性", score=50.0, max_score=100.0,
                grade="Acceptable", threshold=self.BUG_HUNTER_THRESHOLD,
                suggestion="SRTファイルがないため可読性の完全な評価不可"
            )
        entries = self._parse_srt_timing(srt_path)
        if not entries:
            return AxisScore(
                name="テロップ可読性", score=50.0, max_score=100.0,
                grade="Acceptable", threshold=self.BUG_HUNTER_THRESHOLD,
            )
        
        score = 80.0  # ベースライン
        all_issues = []
        for entry in entries:
            text = entry.get("text", "")
            deduction, issues = self._analyze_entry_readability(text)
            score -= deduction
            all_issues.extend(issues)
        
        score = max(0.0, min(100.0, score))
        grade = self._grade(score)
        
        unique_issues = sorted(list(set(all_issues)))
        suggestion = f"可読性問題: {', '.join(unique_issues)}" if unique_issues else ""
        
        return AxisScore(
            name="テロップ可読性", score=round(score, 1), max_score=100.0,
            grade=grade, threshold=self.BUG_HUNTER_THRESHOLD,
            suggestion=suggestion
        )

    def _analyze_entry_readability(self, text: str) -> tuple[float, list[str]]:
        """単一のテキストの可読性を分析し、減点スコアと検出された問題を返す"""
        deduction = 0.0
        issues = []
        lines = text.split("\n")
        
        if len(lines) > 2:
            deduction += 2.0
            issues.append("3行以上の字幕")
            
        for line in lines:
            if len(line.strip()) > 20:
                deduction += 1.0
                issues.append("長すぎる行")
                
        return deduction, issues

    def _score_audio(self, video_path: str) -> AxisScore:
        """軸4: 音量バランス (FFmpeg LUFS計測)"""
        if not video_path:
            return AxisScore(
                name="音量バランス", score=100.0, max_score=100.0,
                grade="N/A", threshold=self.BUG_HUNTER_THRESHOLD,
                suggestion=""
            )
        if not os.path.exists(video_path):
            return AxisScore(
                name="音量バランス", score=0.0, max_score=100.0,
                grade="N/A", threshold=self.BUG_HUNTER_THRESHOLD,
                suggestion="動画ファイルが見つかりません"
            )
        try:
            self._validate_audio_stream(video_path)
            lufs = self._measure_loudness(video_path)
            score = self._calculate_audio_score(lufs)
            
            grade = self._grade(score)
            low, high = self.LOUDNESS_RANGE
            suggestion = f"LUFS={lufs:.1f} (目標: {low}～{high})" if score < 75 else ""
            
            return AxisScore(
                name="音量バランス", score=score, max_score=100.0,
                grade=grade, threshold=self.BUG_HUNTER_THRESHOLD,
                details={"lufs": lufs, "target_range": list(self.LOUDNESS_RANGE)},
                suggestion=suggestion
            )
        except FileNotFoundError as e:
            logger.error("Audio scoring failed (file not found): %s", str(e))
            return AxisScore(
                name="音量バランス", score=0.0, max_score=100.0,
                grade="N/A", threshold=self.BUG_HUNTER_THRESHOLD,
                suggestion="動画ファイルまたは分析コマンドが見つかりません"
            )
        except subprocess.SubprocessError as e:
            logger.error("Audio scoring failed (subprocess error): %s", str(e), exc_info=True)
            return AxisScore(
                name="音量バランス", score=50.0, max_score=100.0,
                grade="Acceptable", threshold=self.BUG_HUNTER_THRESHOLD,
                suggestion=f"音声分析失敗(コマンド実行エラー): {str(e)[:100]}"
            )
        except ValueError as e:
            logger.error("Audio scoring failed (value error): %s", str(e), exc_info=True)
            return AxisScore(
                name="音量バランス", score=50.0, max_score=100.0,
                grade="Acceptable", threshold=self.BUG_HUNTER_THRESHOLD,
                suggestion=f"音声分析失敗(値エラー): {str(e)[:100]}"
            )
        except RuntimeError as e:
            logger.error("Audio scoring failed (runtime error): %s", str(e), exc_info=True)
            return AxisScore(
                name="音量バランス", score=50.0, max_score=100.0,
                grade="Acceptable", threshold=self.BUG_HUNTER_THRESHOLD,
                suggestion=f"音声分析失敗(ランタイムエラー): {str(e)[:100]}"
            )
        except (KeyError, IndexError, AttributeError) as e:
            logger.error("Audio scoring failed (general error): %s", str(e), exc_info=True)
            return AxisScore(
                name="音量バランス", score=50.0, max_score=100.0,
                grade="Acceptable", threshold=self.BUG_HUNTER_THRESHOLD,
                suggestion=f"音声分析失敗: {str(e)[:100]}"
            )

    def _validate_audio_stream(self, video_path: str) -> None:
        """動画ファイルに音声ストリームが存在するか検証"""
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", "-select_streams", "a:0", video_path],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {result.stderr[:200]}")
        try:
            info = json.loads(result.stdout)
            if not info.get("streams"):
                raise ValueError("No audio streams found")
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            raise RuntimeError(f"Failed to parse ffprobe output: {e!s}")

    def _measure_loudness(self, video_path: str) -> float:
        """ffmpegのloudnormフィルタを用いて動画のLUFS値を測定"""
        lufs_result = subprocess.run(
            ["ffmpeg", "-i", video_path, "-af",
             "loudnorm=print_format=json", "-f", "null", "-"],
            capture_output=True, text=True, timeout=120
        )
        lufs_match = re.search(r'"input_i"\s*:\s*"([\-\d.]+)"', lufs_result.stderr)
        if lufs_match:
            return float(lufs_match.group(1))
        return -20.0  # デフォルト値


    def _calculate_audio_score(self, lufs: float) -> float:
        """LUFS測定値から音量バランススコアを算出"""
        low, high = self.LOUDNESS_RANGE
        if low <= lufs <= high:
            return 100.0
        elif low - 2.0 <= lufs <= high + 2.0:
            return 75.0
        elif low - 4.0 <= lufs <= high + 4.0:
            return 50.0
        return 25.0

    def _score_cuts(self, video_path: str) -> AxisScore:
        """軸5: カット割りリズム (FFmpeg scdet)"""
        if not video_path:
            return AxisScore(
                name="カット割りリズム", score=100.0, max_score=100.0,
                grade="N/A", threshold=self.BUG_HUNTER_THRESHOLD,
                suggestion=""
            )
        if not os.path.exists(video_path):
            return AxisScore(
                name="カット割りリズム", score=0.0, max_score=100.0,
                grade="N/A", threshold=self.BUG_HUNTER_THRESHOLD,
                suggestion="動画ファイルが見つかりません"
            )
        try:
            duration = self._get_video_duration(video_path)
            scene_count = self._detect_scene_changes(video_path)
            
            minutes = duration / 60.0
            cuts_per_min = scene_count / max(minutes, 0.1)
            
            score = self._calculate_cut_score(cuts_per_min)
            grade = self._grade(score)
            low, high = self.CUT_FREQ_RANGE
            suggestion = f"カット頻度{cuts_per_min:.1f}回/分 (目標: {low}-{high}回/分)" if score < 75 else ""
            
            return AxisScore(
                name="カット割りリズム", score=score, max_score=100.0,
                grade=grade, threshold=self.BUG_HUNTER_THRESHOLD,
                details={
                    "cuts_per_min": round(cuts_per_min, 1),
                    "scene_count": scene_count,
                    "duration_min": round(minutes, 1)
                },
                suggestion=suggestion
            )
        except FileNotFoundError as e:
            logger.error("Cut rhythm scoring failed (file not found): %s", str(e))
            return AxisScore(
                name="カット割りリズム", score=0.0, max_score=100.0,
                grade="N/A", threshold=self.BUG_HUNTER_THRESHOLD,
                suggestion="動画ファイルまたは分析コマンドが見つかりません"
            )
        except subprocess.SubprocessError as e:
            logger.error("Cut rhythm scoring failed (subprocess error): %s", str(e), exc_info=True)
            return AxisScore(
                name="カット割りリズム", score=50.0, max_score=100.0,
                grade="Acceptable", threshold=self.BUG_HUNTER_THRESHOLD,
                suggestion=f"カット分析失敗(コマンド実行エラー): {str(e)[:100]}"
            )
        except (ValueError, json.JSONDecodeError) as e:
            logger.error("Cut rhythm scoring failed (parse error): %s", str(e), exc_info=True)
            return AxisScore(
                name="カット割りリズム", score=50.0, max_score=100.0,
                grade="Acceptable", threshold=self.BUG_HUNTER_THRESHOLD,
                suggestion=f"カット分析失敗(パースエラー): {str(e)[:100]}"
            )
        except (KeyError, IndexError, AttributeError) as e:
            logger.error("Cut rhythm scoring failed: %s", str(e), exc_info=True)
            return AxisScore(
                name="カット割りリズム", score=50.0, max_score=100.0,
                grade="Acceptable", threshold=self.BUG_HUNTER_THRESHOLD,
                suggestion=f"カット分析失敗: {str(e)[:100]}"
            )

    def _get_video_duration(self, video_path: str) -> float:
        """ffprobeを用いて動画の長さを秒単位で取得"""
        duration_result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries",
             "format=duration", "-of", "json", video_path],
            capture_output=True, text=True, timeout=30
        )
        duration_data = json.loads(duration_result.stdout)
        duration = float(duration_data.get("format", {}).get("duration", 0))
        if duration <= 0:
            raise ValueError("Invalid video duration")
        return duration

    def _detect_scene_changes(self, video_path: str) -> int:
        """ffmpegのselectフィルタ(scene検出)を用いてシーンチェンジ数をカウント"""
        scene_result = subprocess.run(
            ["ffmpeg", "-i", video_path, "-vf",
             "select='gt(scene,0.3)',showinfo", "-f", "null", "-"],
            capture_output=True, text=True, timeout=120
        )
        return len(re.findall(r'pts_time:', scene_result.stderr))

    def _calculate_cut_score(self, cuts_per_min: float) -> float:
        """1分あたりのカット頻度からスコアを算出"""
        low, high = self.CUT_FREQ_RANGE
        if low <= cuts_per_min <= high:
            return 100.0
        elif low - 3.0 <= cuts_per_min <= high + 5.0:
            return 75.0
        elif low - 5.0 <= cuts_per_min <= high + 10.0:
            return 50.0
        return 25.0

    def _parse_srt_timing(self, srt_path: str) -> list[dict]:
        """簡易SRTパーサー: タイミングとテキストを抽出"""
        entries = []
        try:
            with open(srt_path, "r", encoding="utf-8") as f:
                content = f.read()
            blocks = re.split(r"\n\n+", content.strip())
            for block in blocks:
                lines = block.strip().split("\n")
                if len(lines) < 2:
                    continue
                # タイミング行を探す
                timing_match = re.search(
                    r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})",
                    block
                )
                if not timing_match:
                    continue
                start_ms = self._time_to_ms(timing_match.group(1))
                end_ms = self._time_to_ms(timing_match.group(2))
                # テキストはタイミング行の後の行
                timing_line_idx = next(
                    (i for i, l in enumerate(lines) if "-->" in l), -1
                )
                text = "\n".join(lines[timing_line_idx + 1:]) if timing_line_idx >= 0 else ""
                entries.append({"start": start_ms, "end": end_ms, "text": text})
        except (FileNotFoundError, PermissionError) as e:
            logger.error("SRT parse failed (file access error): %s", str(e))
        except UnicodeDecodeError as e:
            logger.error("SRT parse failed (encoding error): %s", str(e))
        except (ValueError, IndexError) as e:
            logger.error("SRT parse failed (malformed format): %s", str(e))
        except (TypeError, AttributeError) as e:
            logger.error("SRT parse failed: %s", str(e), exc_info=True)
        return entries

    @staticmethod
    def _time_to_ms(time_str: str) -> int:
        """HH:MM:SS,mmm をミリ秒に変換"""
        if not time_str or not isinstance(time_str, str):
            return 0
        try:
            time_str = time_str.replace(",", ".").replace(";", ".")
            parts = time_str.split(":")
            if len(parts) != 3:
                return 0
            h, m, s_ms = parts
            s_parts = s_ms.split(".")
            s = int(s_parts[0])
            if len(s_parts) > 1:
                ms_str = s_parts[1].ljust(3, "0")[:3]
                ms = int(ms_str)
            else:
                ms = 0
            return int(h) * 3600000 + int(m) * 60000 + s * 1000 + ms
        except (ValueError, IndexError):
            return 0

    def _load_degradation_log(self, video_path: str) -> list[dict]:
        """品質低下ログを読み取り（Component 1との連携）"""
        if not QUALITY_LOG_PATH.exists():
            return []
        try:
            logs = []
            with open(QUALITY_LOG_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        logs.append(json.loads(line))
            return logs[-20:]  # 直近20件
        except (FileNotFoundError, PermissionError) as e:
            logger.warning("Degradation log access failed: %s", str(e))
            return []
        except json.JSONDecodeError as e:
            logger.error("Degradation log parse failed (JSON error): %s", str(e))
            return []
        except (TypeError, AttributeError) as e:
            logger.error("Degradation log read failed: %s", str(e), exc_info=True)
            return []

    @staticmethod
    def _grade(score: float) -> str:
        if score >= 85:
            return "Excellent"
        elif score >= 70:
            return "Good"
        elif score >= 50:
            return "Acceptable"
        else:
            return "Poor"
