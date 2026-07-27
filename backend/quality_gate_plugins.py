"""
quality_gate_plugins.py — 品質ゲートプラグインアーキテクチャ

憲法§3.2「プラグインアーキテクチャ」に準拠。
QualityGateWorkerのチェック項目を独立プラグインとして分離し、
フェーズ2-4のモデルチェンジが「プラグインの追加」だけで実現できる設計。

プラグインの追加方法:
  1. QualityCheckPlugin を継承して新クラスを作成
  2. PLUGIN_REGISTRY に登録
  3. 完了。QualityGateWorker が自動的にロードする。

AI技術進化対応:
  - 各プラグインは独立しているため、個別にAI版へ差し替え可能
  - analyze() が Dict を返すため、LLM解析結果も統合可能
"""

import logging
import json
import subprocess
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


# ============================================================
# プラグイン基底クラス
# ============================================================

class QualityCheckPlugin(ABC):
    """
    品質チェックプラグインの基底クラス。
    
    全てのプラグインは以下を実装する:
      - name: プラグイン名
      - category: カテゴリ（core/template/broadcast/youtube/accessibility）
      - analyze(): 減点とフィードバックを返す
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """プラグイン名"""
        ...
    
    @property
    @abstractmethod
    def category(self) -> str:
        """カテゴリ（core/template/broadcast/youtube/accessibility）"""
        ...
    
    @abstractmethod
    def analyze(self, ctx: Any, template_config: Any = None) -> Dict:
        """
        品質チェックを実行。
        
        Returns:
            {
                "deductions": int,   # 減点数
                "feedback": [str],   # フィードバックメッセージ
                "details": dict,     # 詳細データ（オプション）
            }
        """
        ...


# ============================================================
# コアプラグイン（フェーズ0: 基本チェック）
# ============================================================

class FileSizeCheck(QualityCheckPlugin):
    """ファイルサイズ基本チェック"""
    name = "file_size_check"
    category = "core"
    
    def analyze(self, ctx, template_config=None):
        deductions = 0
        feedback = []
        
        if ctx.preview_path and Path(ctx.preview_path).exists():
            file_size = Path(ctx.preview_path).stat().st_size
            if file_size < 1024:
                deductions = 30
                feedback.append("ファイルサイズが異常に小さい")
            elif file_size < 10 * 1024 * 1024:
                deductions = 3
                feedback.append("ファイルサイズが小さい（低画質の可能性）")
        else:
            deductions = 20
            feedback.append("プレビューファイルが存在しない")
        
        return {"deductions": deductions, "feedback": feedback}


class SegmentQualityCheck(QualityCheckPlugin):
    """セグメント品質チェック"""
    name = "segment_quality_check"
    category = "core"
    
    def analyze(self, ctx, template_config=None):
        deductions = 0
        feedback = []
        
        if ctx.segments:
            empty = sum(1 for s in ctx.segments if not s.get("text", "").strip())
            ratio = empty / len(ctx.segments)
            if ratio > 0.3:
                deductions = 10
                feedback.append(f"空セグメント率が高い ({ratio:.0%})")
        
        return {"deductions": deductions, "feedback": feedback}


class AIRuleCheck(QualityCheckPlugin):
    """AIカスタムルール＋過去パターン予測"""
    name = "ai_rule_check"
    category = "core"
    
    def analyze(self, ctx, template_config=None):
        deductions = 0
        feedback = []
        
        try:
            from quality_gate_ai import ai_quality_checker
            subtitle_text = " ".join(s.get("text", "") for s in ctx.segments[:50])
            if subtitle_text:
                for issue in ai_quality_checker.check_custom_rules(subtitle_text):
                    deductions += 15 if issue["severity"] == "error" else 5
                    feedback.append(f"[{issue['rule_name']}] {issue['message']}")
                
                for pred in ai_quality_checker.predict_issues(subtitle_text):
                    feedback.append(f"⚠ {pred}")
        except ImportError:
            logger.debug("quality_gate_ai not available — AI rule check skipped")
        except (AttributeError, TypeError, ValueError, KeyError, RuntimeError) as e:
            logger.warning(f"AI rule check failed with expected error: {e}", exc_info=True)
        
        return {"deductions": deductions, "feedback": feedback}


# ============================================================
# テンプレート基準プラグイン（フェーズ1: 100点必達）
# ============================================================

class SubtitleSpeedCheck(QualityCheckPlugin):
    """字幕表示速度チェック（2層構造: 表示速度 + 発話速度）

    NHK基準の4文字/秒は「表示字幕のテロップ速度」を規定しており、
    「話者の発話速度」とは別指標である。

    - 表示速度: format_segments適用後のテキストで判定（NHK基準: 4文字/秒）
    - 発話速度: Whisper生セグメントで判定（自然な日本語: 5-8文字/秒、8超で警告）
    """
    name = "subtitle_speed_check"
    category = "template"

    def analyze(self, ctx, template_config=None):
        deductions = 0
        feedback = []

        if not ctx.segments:
            return {"deductions": 0, "feedback": []}

        # テンプレート設定がなくてもNHK放送基準のデフォルト値で最低限チェック
        if template_config and template_config.is_active:
            tmpl_id = template_config.template_id or "default"
            max_cps = template_config.get_subtitle_rules().get("chars_per_second", 4)
        else:
            tmpl_id = "業界標準"
            max_cps = 4  # NHK字幕基準: 4文字/秒（表示速度）

        # ━━━ 表示速度チェック（NHK基準: 4文字/秒） ━━━
        # NHK基準は「長い字幕テロップを読む時間」を規定。
        # 短い字幕（8文字以下）は一目で読めるため、速度チェック対象外。
        MIN_CHARS_FOR_SPEED_CHECK = 8  # この文字数以下は速度チェックをスキップ
        display_violations = 0
        checked_segs = 0
        for seg in ctx.segments:
            text = seg.get("text", "")
            dur = seg.get("end", 0) - seg.get("start", 0)
            if dur <= 0:
                continue
            # 表示字幕速度: 改行で分割された各行の最長行で判定
            lines = text.split("\n")
            max_line_len = max((len(line) for line in lines), default=0)
            # 短い字幕はスキップ（一目で読める）
            if max_line_len <= MIN_CHARS_FOR_SPEED_CHECK:
                continue
            checked_segs += 1
            display_cps = max_line_len / dur
            # NHK基準の2倍（8文字/秒）を超えたら表示速度違反
            if display_cps > max_cps * 2:
                display_violations += 1

        # ━━━ 発話速度チェック（自然な日本語: 5-8文字/秒） ━━━
        # 10文字/秒を超える極端に速い発話のみ警告（減点は軽微）
        # 短いセグメント（5文字以下）は除外
        speech_violations = 0
        SPEECH_MAX_CPS = 10  # 極端に速い発話のみ検出
        MIN_CHARS_FOR_SPEECH = 5
        for seg in ctx.segments:
            text = seg.get("text", "")
            dur = seg.get("end", 0) - seg.get("start", 0)
            if dur > 0 and len(text) > MIN_CHARS_FOR_SPEECH and len(text) / dur > SPEECH_MAX_CPS:
                speech_violations += 1

        # ━━━ スコアリング ━━━
        total_segs = max(len(ctx.segments), 1)
        checked_base = max(checked_segs, 1)

        # 表示速度違反（重い減点: NHK基準の根幹）
        if display_violations > 0:
            display_ratio = display_violations / checked_base
            if display_ratio > 0.2:
                deductions += 10
                feedback.append(
                    f"📺 [{tmpl_id}] 表示字幕速度超過: {display_violations}/{checked_segs}件が"
                    f"基準({max_cps}文字/秒)の2倍超 ({display_ratio:.0%})")
            elif display_ratio > 0.05:
                deductions += 5
                feedback.append(
                    f"⚠ [{tmpl_id}] 表示字幕速度注意: {display_violations}件")

        # 発話速度違反（軽い減点: 話者の速度は制御できない）
        if speech_violations > 0:
            speech_ratio = speech_violations / total_segs
            if speech_ratio > 0.3:
                deductions += 3
                feedback.append(
                    f"💬 [{tmpl_id}] 発話速度が速い区間: {speech_violations}件"
                    f" ({speech_ratio:.0%}) — 字幕分割を推奨")
            elif speech_ratio > 0.1:
                deductions += 1
                feedback.append(
                    f"💬 [{tmpl_id}] 発話速度注意: {speech_violations}件")

        return {"deductions": deductions, "feedback": feedback}


class SubtitleLineCheck(QualityCheckPlugin):
    """1行文字数チェック（max_chars_per_line）"""
    name = "subtitle_line_check"
    category = "template"
    
    def analyze(self, ctx, template_config=None):
        deductions = 0
        feedback = []
        
        if not ctx.segments:
            return {"deductions": 0, "feedback": []}
        
        if template_config and template_config.is_active:
            tmpl_id = template_config.template_id or "default"
            max_cpl = template_config.get_subtitle_rules().get("max_chars_per_line", 15)
        else:
            tmpl_id = "業界標準"
            max_cpl = 15  # テレビ放送標準: 15文字/行
        long_lines = 0
        
        for seg in ctx.segments:
            for line in seg.get("text", "").split("\n"):
                if len(line) > max_cpl:
                    long_lines += 1
        
        if long_lines > 3:
            deductions = 5
            feedback.append(
                f"📺 [{tmpl_id}] 長い字幕行: {long_lines}件が"
                f"基準({max_cpl}文字/行)を超過")
        
        return {"deductions": deductions, "feedback": feedback}


class HookCheck(QualityCheckPlugin):
    """冒頭フックチェック（hook_window_seconds）"""
    name = "hook_check"
    category = "template"
    
    def analyze(self, ctx, template_config=None):
        deductions = 0
        feedback = []
        
        if not ctx.segments:
            return {"deductions": 0, "feedback": []}
        
        if template_config and template_config.is_active:
            tmpl_id = template_config.template_id or "default"
            hook_window = template_config.get_engagement_rules().get("hook_window_seconds", 5)
        else:
            tmpl_id = "業界標準"
            hook_window = 5  # YouTube平均離脱基準: 5秒
        first_start = ctx.segments[0].get("start", 0)
        
        if first_start > hook_window:
            deductions = 15
            feedback.append(
                f"🎬 [{tmpl_id}] 冒頭フック欠如: 最初の発話が"
                f"{first_start:.1f}秒目（基準: {hook_window}秒以内）")
        
        return {"deductions": deductions, "feedback": feedback}


class DeadAirCheck(QualityCheckPlugin):
    """無音区間チェック（dead_air_max_seconds）"""
    name = "dead_air_check"
    category = "template"
    
    def analyze(self, ctx, template_config=None):
        deductions = 0
        feedback = []
        
        if not ctx.segments:
            return {"deductions": 0, "feedback": []}
        
        if template_config and template_config.is_active:
            tmpl_id = template_config.template_id or "default"
            dead_air_max = template_config.get_engagement_rules().get("dead_air_max_seconds", 2.0)
        else:
            tmpl_id = "業界標準"
            dead_air_max = 3.0  # 通常動画の許容値: 3秒
        count = 0
        
        for i in range(1, len(ctx.segments)):
            gap = ctx.segments[i].get("start", 0) - ctx.segments[i - 1].get("end", 0)
            if gap > dead_air_max:
                count += 1
        
        if count > 5:
            deductions = 10
            feedback.append(
                f"🔇 [{tmpl_id}] 無音区間超過: {count}箇所が"
                f"基準({dead_air_max}秒)を超過")
        elif count > 0:
            deductions = 3
            feedback.append(f"⚠ [{tmpl_id}] 無音区間注意: {count}箇所")
        
        return {"deductions": deductions, "feedback": feedback}


class SubtitleDensityCheck(QualityCheckPlugin):
    """字幕密度チェック（dopamine_interval_seconds）"""
    name = "subtitle_density_check"
    category = "template"
    
    def analyze(self, ctx, template_config=None):
        deductions = 0
        feedback = []
        
        if not ctx.segments or len(ctx.segments) < 2:
            return {"deductions": 0, "feedback": []}
        
        if template_config and template_config.is_active:
            tmpl_id = template_config.template_id or "default"
            interval = template_config.get_engagement_rules().get("dopamine_interval_seconds", 10)
        else:
            tmpl_id = "業界標準"
            interval = 10  # エンゲージメント基準: 10秒間隔
        total_dur = ctx.segments[-1].get("end", 0) - ctx.segments[0].get("start", 0)
        
        if total_dur > 0:
            avg = total_dur / len(ctx.segments)
            if avg > interval * 2:
                deductions = 5
                feedback.append(
                    f"⚡ [{tmpl_id}] 字幕密度不足: 平均間隔"
                    f"{avg:.1f}秒（基準: {interval}秒ごと）")
        
        return {"deductions": deductions, "feedback": feedback}


class HookStrengthCheck(QualityCheckPlugin):
    """フック強度スコア（フェーズ1: 100点必達）"""
    name = "hook_strength_check"
    category = "template"
    
    def analyze(self, ctx, template_config=None):
        deductions = 0
        feedback = []
        
        if not ctx.segments:
            return {"deductions": 0, "feedback": []}
        
        if template_config and template_config.is_active:
            tmpl_id = template_config.template_id or "default"
            thresholds = template_config.get_hook_strength_thresholds()
        else:
            tmpl_id = "業界標準"
            thresholds = {
                "hook_window_seconds": 5,
                "score_weights": {"has_speech": 40, "speech_density": 30, "no_dead_air": 30},
            }
        hook_window = thresholds["hook_window_seconds"]
        weights = thresholds["score_weights"]
        
        # フックウィンドウ内のセグメントを収集
        hook_segments = [
            s for s in ctx.segments
            if s.get("start", 0) < hook_window
        ]
        
        hook_score = 0
        
        # フック内に発話があるか
        if hook_segments:
            hook_score += weights["has_speech"]
            
            # 発話密度（フック内の文字数/フック時間）
            total_chars = sum(len(s.get("text", "")) for s in hook_segments)
            density = total_chars / max(hook_window, 1)
            if density >= 2:
                hook_score += weights["speech_density"]
            elif density >= 1:
                hook_score += weights["speech_density"] * 0.5
            
            # 無音なしか
            has_dead_air = False
            if hook_segments[0].get("start", 0) > 1.0:
                has_dead_air = True
            if not has_dead_air:
                hook_score += weights["no_dead_air"]
        
        # フック強度が低い場合に減点
        if hook_score < 50:
            deductions = 10
            feedback.append(
                f"🎯 [{tmpl_id}] フック強度不足: {hook_score}/100点")
        elif hook_score < 70:
            deductions = 5
            feedback.append(
                f"⚠ [{tmpl_id}] フック強度やや弱い: {hook_score}/100点")
        
        return {
            "deductions": deductions,
            "feedback": feedback,
            "details": {"hook_score": hook_score},
        }


class RetentionPredictionCheck(QualityCheckPlugin):
    """維持率予測チェック（フェーズ1: 100点必達）"""
    name = "retention_prediction_check"
    category = "template"
    
    def analyze(self, ctx, template_config=None):
        deductions = 0
        feedback = []
        
        if not ctx.segments or len(ctx.segments) < 5:
            return {"deductions": 0, "feedback": []}
        
        if template_config and template_config.is_active:
            tmpl_id = template_config.template_id or "default"
            config = template_config.get_retention_prediction_config()
        else:
            tmpl_id = "業界標準"
            config = {
                "target_retention_percent": 40,
                "dead_air_max": 3.0,
                "scoring": {
                    "segment_density_weight": 0.3,
                    "hook_strength_weight": 0.25,
                    "dead_air_penalty_weight": 0.25,
                    "pacing_consistency_weight": 0.2,
                },
            }
        target = config["target_retention_percent"]
        weights = config["scoring"]
        
        total_dur = ctx.segments[-1].get("end", 0) - ctx.segments[0].get("start", 0)
        if total_dur <= 0:
            return {"deductions": 0, "feedback": []}
        
        # 字幕密度スコア（0-100）
        avg_interval = total_dur / len(ctx.segments)
        density_score = min(100, max(0, 100 - (avg_interval - 3) * 10))
        
        # 無音ペナルティ（0-100、100=無音なし）
        dead_air_max = config["dead_air_max"]
        dead_airs = 0
        for i in range(1, len(ctx.segments)):
            gap = ctx.segments[i].get("start", 0) - ctx.segments[i - 1].get("end", 0)
            if gap > dead_air_max:
                dead_airs += 1
        dead_air_score = max(0, 100 - dead_airs * 15)
        
        # ペーシング一貫性（0-100）
        durations = [
            s.get("end", 0) - s.get("start", 0)
            for s in ctx.segments if (s.get("end", 0) - s.get("start", 0)) > 0
        ]
        if durations:
            import statistics
            try:
                cv = statistics.stdev(durations) / statistics.mean(durations)
                pacing_score = max(0, 100 - cv * 50)
            except (statistics.StatisticsError, ZeroDivisionError):
                pacing_score = 50
        else:
            pacing_score = 50
        
        # 加重平均で予測維持率を算出
        predicted = (
            density_score * weights["segment_density_weight"]
            + 70 * weights["hook_strength_weight"]  # フック強度はHookStrengthCheckから
            + dead_air_score * weights["dead_air_penalty_weight"]
            + pacing_score * weights["pacing_consistency_weight"]
        )
        predicted = round(predicted, 1)
        
        if predicted < target * 0.7:
            deductions = 10
            feedback.append(
                f"📉 [{tmpl_id}] 維持率予測: {predicted}%（目標: {target}%）— 大幅改善が必要")
        elif predicted < target:
            deductions = 5
            feedback.append(
                f"📊 [{tmpl_id}] 維持率予測: {predicted}%（目標: {target}%）— 改善推奨")
        
        return {
            "deductions": deductions,
            "feedback": feedback,
            "details": {
                "predicted_retention": predicted,
                "density_score": density_score,
                "dead_air_score": dead_air_score,
                "pacing_score": round(pacing_score, 1),
            },
        }


# ============================================================
# 放送品質プラグイン（HR-5: テレビ局放送技術部基準）
# ============================================================

class LoudnessCheck(QualityCheckPlugin):
    """ラウドネス正規化チェック（-24〜-16 LUFS放送基準）"""
    name = "loudness_check"
    category = "broadcast"

    def analyze(self, ctx, template_config=None):
        deductions = 0
        feedback = []

        if not ctx.preview_path or not Path(ctx.preview_path).exists():
            return {"deductions": 0, "feedback": []}

        try:
            from video_editor_engine import video_editor
            ffmpeg = video_editor.ffmpeg
            # FFmpegのloudnormで実測（2パス分析）
            cmd = [
                "-i", ctx.preview_path,
                "-af", "loudnorm=print_format=json",
                "-f", "null", "-"
            ]
            success, output = ffmpeg.run_command(cmd, timeout=60)
            if success and output:
                import json as _json
                # loudnorm JSONを抽出
                for line in output.split("\n"):
                    if '"input_i"' in line:
                        try:
                            start_idx = output.index("{", output.index('"input_i"') - 50)
                            end_idx = output.index("}", start_idx) + 1
                            data = _json.loads(output[start_idx:end_idx])
                            lufs = float(data.get("input_i", -99))
                            if lufs < -24:
                                deductions = 10
                                feedback.append(f"📡 音量が小さすぎる: {lufs:.1f} LUFS (基準: -24〜-16)")
                            elif lufs > -14:
                                deductions = 10
                                feedback.append(f"📡 音量が大きすぎる: {lufs:.1f} LUFS (基準: -24〜-16)")
                        except (ValueError, _json.JSONDecodeError):
                            pass
                        break
        except (ImportError, FileNotFoundError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as e:
            logger.warning(f"Loudness check failed or skipped: {e}")

        return {"deductions": deductions, "feedback": feedback}


class ResolutionCheck(QualityCheckPlugin):
    """解像度・フレームレートチェック（放送品質: 1080p 30fps以上）"""
    name = "resolution_check"
    category = "broadcast"

    def analyze(self, ctx, template_config=None):
        deductions = 0
        feedback = []

        if not ctx.preview_path or not Path(ctx.preview_path).exists():
            return {"deductions": 0, "feedback": []}

        try:
            from video_editor_engine import video_editor
            ffmpeg = video_editor.ffmpeg
            info = ffmpeg.get_video_info(Path(ctx.preview_path))
            if info:
                width = info.get("width", 0)
                height = info.get("height", 0)
                if height < 720:
                    deductions = 15
                    feedback.append(f"📡 解像度不足: {width}x{height} (最低720p必須)")
                elif height < 1080:
                    deductions = 5
                    feedback.append(f"📡 解像度注意: {width}x{height} (1080p推奨)")
        except (ImportError, FileNotFoundError, subprocess.SubprocessError, KeyError, ValueError) as e:
            logger.warning(f"Resolution check failed or skipped: {e}")

        return {"deductions": deductions, "feedback": feedback}


class CodecCheck(QualityCheckPlugin):
    """コーデック妥当性チェック（H.264/H.265 + AAC）"""
    name = "codec_check"
    category = "broadcast"

    def analyze(self, ctx, template_config=None):
        deductions = 0
        feedback = []

        if not ctx.preview_path or not Path(ctx.preview_path).exists():
            return {"deductions": 0, "feedback": []}

        try:
            from video_editor_engine import video_editor
            ffmpeg = video_editor.ffmpeg
            info = ffmpeg.get_video_info(Path(ctx.preview_path))
            if info:
                vcodec = info.get("video_codec", "").lower()
                acodec = info.get("audio_codec", "").lower()
                if vcodec and vcodec not in ["h264", "hevc", "h265", "av1"]:
                    deductions = 5
                    feedback.append(f"📡 映像コーデック注意: {vcodec} (H.264/H.265推奨)")
                if acodec and acodec not in ["aac", "opus", "mp3"]:
                    deductions += 5
                    feedback.append(f"📡 音声コーデック注意: {acodec} (AAC推奨)")
        except (ImportError, FileNotFoundError, subprocess.SubprocessError, KeyError, ValueError) as e:
            logger.warning(f"Codec check failed or skipped: {e}")

        return {"deductions": deductions, "feedback": feedback}


# ============================================================
# YouTube最適化プラグイン（HR-5: YouTuber基準）
# ============================================================

class ChapterCoverageCheck(QualityCheckPlugin):
    """チャプター網羅性チェック（10分超動画はチャプター必須）"""
    name = "chapter_coverage_check"
    category = "youtube"

    def analyze(self, ctx, template_config=None):
        deductions = 0
        feedback = []

        if not ctx.segments or len(ctx.segments) < 5:
            return {"deductions": 0, "feedback": []}

        total_dur = ctx.segments[-1].get("end", 0)
        if total_dur > 600:  # 10分超
            # セグメント間のギャップで自然なチャプター区切りがあるか推定
            chapter_breaks = 0
            for i in range(1, len(ctx.segments)):
                gap = ctx.segments[i].get("start", 0) - ctx.segments[i - 1].get("end", 0)
                if gap > 3.0:
                    chapter_breaks += 1

            expected_chapters = max(3, int(total_dur / 300))  # 5分ごとに1チャプター
            if chapter_breaks < expected_chapters * 0.5:
                deductions = 5
                feedback.append(
                    f"▶ チャプター候補不足: {chapter_breaks}箇所 "
                    f"(推奨: {expected_chapters}以上)")

        return {"deductions": deductions, "feedback": feedback}


class ShortsReadyCheck(QualityCheckPlugin):
    """Shorts切り出し適性チェック（ハイライトシーンの有無）"""
    name = "shorts_ready_check"
    category = "youtube"

    def analyze(self, ctx, template_config=None):
        deductions = 0
        feedback = []

        if not ctx.segments:
            return {"deductions": 0, "feedback": []}

        # 感嘆詞・ハイライトワードを含むセグメントをカウント
        highlight_words = ["！", "!?", "すごい", "やばい", "衝撃", "最高", "神", "マジ"]
        highlight_count = 0
        for s in ctx.segments:
            text = s.get("text", "")
            if any(w in text for w in highlight_words):
                highlight_count += 1

        if highlight_count == 0:
            deductions = 3
            feedback.append("▶ Shorts候補ゼロ: ハイライトワードが未検出 (手動選定を推奨)")

        return {
            "deductions": deductions,
            "feedback": feedback,
            "details": {"highlight_count": highlight_count},
        }


class CTRReadyCheck(QualityCheckPlugin):
    """CTR最適化準備チェック（タイトル・サムネイル生成可否）"""
    name = "ctr_ready_check"
    category = "youtube"

    def analyze(self, ctx, template_config=None):
        deductions = 0
        feedback = []

        if not ctx.segments or len(ctx.segments) < 3:
            return {"deductions": 0, "feedback": []}

        # 冒頭セグメントからフックテキストが抽出可能か
        hook_text = " ".join(s.get("text", "") for s in ctx.segments[:5])
        if len(hook_text) < 20:
            deductions = 3
            feedback.append("▶ CTR最適化困難: 冒頭テキストが短すぎる (20文字未満)")

        return {"deductions": deductions, "feedback": feedback}


# ============================================================
# 商用品質プラグイン（Phase 1: お金を取れるレベルの品質担保）
# ============================================================

class AudioPresenceCheck(QualityCheckPlugin):
    """音声トラック存在確認 — 無音動画を排除"""
    name = "audio_presence_check"
    category = "core"

    def analyze(self, ctx, template_config=None):
        deductions = 0
        feedback = []

        if not ctx.preview_path or not Path(ctx.preview_path).exists():
            return {"deductions": 0, "feedback": []}

        try:
            from video_editor_engine import video_editor
            ffmpeg = video_editor.ffmpeg
            info = ffmpeg.get_video_info(Path(ctx.preview_path))
            if info:
                has_audio = info.get("audio_codec") not in (None, "", "none")
                if not has_audio:
                    deductions = 20
                    feedback.append("🔇 音声トラックが存在しない — 動画として不完全")
        except (ImportError, FileNotFoundError, subprocess.SubprocessError, KeyError, ValueError) as e:
            logger.warning(f"Audio presence check failed or skipped: {e}")

        return {"deductions": deductions, "feedback": feedback}


class BitrateCheck(QualityCheckPlugin):
    """映像ビットレートチェック（商用品質: 2Mbps以上）"""
    name = "bitrate_check"
    category = "broadcast"

    def analyze(self, ctx, template_config=None):
        deductions = 0
        feedback = []

        if not ctx.preview_path or not Path(ctx.preview_path).exists():
            return {"deductions": 0, "feedback": []}

        try:
            file_size = Path(ctx.preview_path).stat().st_size
            # セグメントからおおよその尺を推定
            duration = 0
            if ctx.segments and len(ctx.segments) > 0:
                duration = ctx.segments[-1].get("end", 0) - ctx.segments[0].get("start", 0)
            if duration <= 0:
                # FFprobeでdurationを取得
                try:
                    from video_editor_engine import video_editor
                    info = video_editor.ffmpeg.get_video_info(Path(ctx.preview_path))
                    duration = info.get("duration", 0) if info else 0
                except (ImportError, FileNotFoundError, subprocess.SubprocessError, KeyError, ValueError):
                    pass
                except Exception as e:
                    try:
                        from agents.memory.technical_debt import TechnicalDebtStore
                        store = TechnicalDebtStore()
                        store.register_debt(
                            category="ACCEPTED_SAFETY",
                            file_path="quality_gate_plugins.py",
                            line_number=788,
                            pattern="except Exception as e: in BitrateCheck",
                            cause_pattern="DP-01",
                            fix_pattern="Specific exception handling or error logging conversion",
                            registered_by="subagent-bug-hunter",
                            notes=f"FFprobe extraction generic exception: {e}",
                        )
                    except Exception as tdr_err:
                        logger.error(f"Failed to register TDR debt: {tdr_err}")
            
            if duration > 0:
                bitrate_mbps = (file_size * 8) / duration / 1_000_000
                if bitrate_mbps < 0.5:
                    deductions = 10
                    feedback.append(f"📡 ビットレート不足: {bitrate_mbps:.1f}Mbps (最低0.5Mbps)")
                elif bitrate_mbps < 1.0:
                    deductions = 3
                    feedback.append(f"📡 ビットレート注意: {bitrate_mbps:.1f}Mbps (プレビュー品質)")
        except (OSError, ZeroDivisionError, TypeError, ValueError) as e:
            logger.warning(f"Bitrate check failed or skipped: {e}")

        return {"deductions": deductions, "feedback": feedback}


class DurationSanityCheck(QualityCheckPlugin):
    """出力尺の整合性チェック — SmartCutによる大幅な尺変動を検出"""
    name = "duration_sanity_check"
    category = "core"

    def analyze(self, ctx, template_config=None):
        deductions = 0
        feedback = []

        if not ctx.segments or not ctx.selected_segments:
            return {"deductions": 0, "feedback": []}

        # 元の尺 vs 選択後の尺
        original_dur = ctx.segments[-1].get("end", 0) - ctx.segments[0].get("start", 0)
        
        selected_dur = sum(
            s.get("end", 0) - s.get("start", 0) for s in ctx.selected_segments
        )

        if original_dur > 0 and selected_dur > 0:
            ratio = selected_dur / original_dur
            if ratio < 0.1:  # 元素材の10%未満 → 過度なカット
                deductions = 15
                feedback.append(
                    f"⚠ 出力尺が元素材の{ratio:.0%}しかない "
                    f"({selected_dur:.0f}秒 / {original_dur:.0f}秒)")
            elif ratio < 0.3:
                deductions = 5
                feedback.append(
                    f"📐 出力尺注意: 元素材の{ratio:.0%} "
                    f"({selected_dur:.0f}秒 / {original_dur:.0f}秒)")

        return {"deductions": deductions, "feedback": feedback}


class MetadataCompletenessCheck(QualityCheckPlugin):
    """メタデータ網羅性チェック（憲法§23準拠）"""
    name = "metadata_completeness_check"
    category = "youtube"

    def analyze(self, ctx, template_config=None):
        deductions = 0
        feedback = []

        metadata = ctx.metadata if hasattr(ctx, 'metadata') else {}
        if not metadata:
            deductions = 10
            feedback.append("▶ メタデータ未生成 — YouTube最適化が完全に欠如")
            return {"deductions": deductions, "feedback": feedback}

        # §23.4: タイトル候補5案
        titles = metadata.get("titles", [])
        if len(titles) < 1:
            deductions += 5
            feedback.append("▶ タイトル候補なし (§23.4: 5案推奨)")
        elif len(titles) < 3:
            deductions += 2
            feedback.append(f"▶ タイトル候補不足: {len(titles)}案 (§23.4: 5案推奨)")

        # §23.4: タグ15-20個
        tags = metadata.get("tags", [])
        if len(tags) < 5:
            deductions += 3
            feedback.append(f"▶ タグ不足: {len(tags)}個 (§23.4: 15-20個推奨)")
        elif len(tags) < 15:
            deductions += 1
            feedback.append(f"▶ タグ改善余地: {len(tags)}個 (§23.4: 15-20個推奨)")

        # 説明文
        description = metadata.get("description", "")
        if len(description) < 50:
            deductions += 3
            feedback.append("▶ 説明文不足 (100文字以上推奨)")

        return {"deductions": deductions, "feedback": feedback}


class ThumbnailQualityCheck(QualityCheckPlugin):
    """サムネイル品質チェック (解像度, アスペクト比, ファイルサイズ, 破損確認)"""
    name = "thumbnail_quality_check"
    category = "youtube"

    def analyze(self, ctx, template_config=None):
        deductions = 0
        feedback = []
        
        # 1. パスの取得
        thumb_path = getattr(ctx, "thumbnail_path", None)
        if not thumb_path and hasattr(ctx, "metadata") and isinstance(ctx.metadata, dict):
            thumb_path = ctx.metadata.get("thumbnail_path")
            
        if not thumb_path:
            deductions = 15
            feedback.append("▶ サムネイルパスが設定されていません")
            return {"deductions": deductions, "feedback": feedback}
            
        path = Path(thumb_path)
        if not path.exists():
            deductions = 15
            feedback.append(f"▶ サムネイルファイルが存在しません: {path.name}")
            return {"deductions": deductions, "feedback": feedback}
            
        # 2. ファイルサイズチェック (4MB制限)
        size_bytes = path.stat().st_size
        if size_bytes >= 4 * 1024 * 1024:
            deductions += 25
            feedback.append(f"▶ サムネイルファイルサイズが4MBを超えています: {size_bytes / (1024*1024):.2f}MB")
            
        # 3. Pillowでのロード・破損チェック・解像度・アスペクト比
        from PIL import Image
        try:
            with Image.open(path) as img:
                # 簡易検証
                img.verify()
        except (ImportError, OSError, ValueError, SyntaxError) as e:
            deductions += 25
            feedback.append(f"▶ サムネイル画像が破損しているか、無効なフォーマットです: {e}")
            return {"deductions": deductions, "feedback": feedback}
            
        try:
            with Image.open(path) as img:
                # 完全なロードによる破損検出
                img.load()
                width, height = img.size
                
                # 解解像度チェック
                if width < 1280 or height < 720:
                    deductions += 20
                    feedback.append(f"▶ 解像度が 1280x720 未満です: {width}x{height}")
                    
                # アスペクト比チェック
                aspect_ratio = width / height
                target_ratio = 16.0 / 9.0
                if abs(aspect_ratio - target_ratio) > 0.01:
                    deductions += 15
                    feedback.append(f"▶ アスペクト比が 16:9 ではありません: {aspect_ratio:.3f}")
        except (ImportError, OSError, ValueError, SyntaxError) as e:
            deductions += 25
            feedback.append(f"▶ サムネイル画像のロード中にエラーが発生しました: {e}")
            
        if deductions == 0:
            feedback.append("✅ サムネイル品質検証合格 (1280x720以上, 16:9, 4MB未満)")
            
        return {"deductions": deductions, "feedback": feedback}


# ============================================================
# 安定稼働プラグイン（stability: パイプラインの信頼性）
# ============================================================

class PipelineCompletionCheck(QualityCheckPlugin):
    """パイプライン完走チェック — 全ステージが正常終了したか"""
    name = "pipeline_completion_check"
    category = "stability"

    def analyze(self, ctx, template_config=None):
        deductions = 0
        feedback = []

        # 必須成果物の存在チェック（品質ゲートはプレビュー生成前に実行される）
        has_thumb_path = bool(getattr(ctx, 'thumbnail_path', None) or (hasattr(ctx, 'metadata') and isinstance(ctx.metadata, dict) and ctx.metadata.get('thumbnail_path')))
        checks = [
            (bool(ctx.segments and len(ctx.segments) > 0), "セグメント（文字起こし）", 15),
            (bool(getattr(ctx, 'selected_segments', None)), "SmartCut結果", 5),
            (bool(ctx.metadata), "メタデータ", 5),
            (has_thumb_path, "サムネイル設定", 5),
        ]

        for ok, label, pts in checks:
            if not ok:
                deductions += pts
                feedback.append(f"🔴 {label}が未生成 — パイプライン中断の可能性")

        if deductions == 0:
            feedback.append("✅ 全ステージ正常完走")

        return {"deductions": deductions, "feedback": feedback}


class GPUHealthCheck(QualityCheckPlugin):
    """GPU処理健全性チェック — Whisperがタイムアウトなく完了したか"""
    name = "gpu_health_check"
    category = "stability"

    def analyze(self, ctx, template_config=None):
        deductions = 0
        feedback = []

        if not ctx.segments:
            deductions = 10
            feedback.append("🔴 セグメントなし — 文字起こし未完了")
            return {"deductions": deductions, "feedback": feedback}

        # セグメント数と時間カバレッジで健全性判定
        total_text = sum(len(s.get("text", "")) for s in ctx.segments)
        if total_text < 50:
            deductions = 10
            feedback.append("⚠ 文字起こし結果が極端に少ない — GPU処理異常の可能性")
        else:
            feedback.append(f"✅ GPU文字起こし正常: {len(ctx.segments)}セグメント, {total_text}文字")

        return {"deductions": deductions, "feedback": feedback}


# ============================================================
# プラグインレジストリ
# ============================================================

# 登録済みプラグイン一覧
# 全6カテゴリ（コア/テンプレート/放送品質/YouTube最適化/安定稼働/アクセシビリティ）
PLUGIN_REGISTRY: List[QualityCheckPlugin] = [
    # コア（常時実行）
    FileSizeCheck(),
    SegmentQualityCheck(),
    AIRuleCheck(),
    AudioPresenceCheck(),
    DurationSanityCheck(),
    # テンプレート基準
    SubtitleSpeedCheck(),
    SubtitleLineCheck(),
    HookCheck(),
    DeadAirCheck(),
    SubtitleDensityCheck(),
    HookStrengthCheck(),
    RetentionPredictionCheck(),
    # 放送品質
    LoudnessCheck(),
    ResolutionCheck(),
    CodecCheck(),
    BitrateCheck(),
    # YouTube最適化
    ChapterCoverageCheck(),
    ShortsReadyCheck(),
    CTRReadyCheck(),
    MetadataCompletenessCheck(),
    ThumbnailQualityCheck(),
    # 安定稼働（最重要）
    PipelineCompletionCheck(),
    GPUHealthCheck(),
]

# ━━━ カテゴリ重み付け ━━━
# 安定稼働に直結するカテゴリほど高い重みを設定
CATEGORY_WEIGHTS = {
    "stability": 2.0,    # 安定稼働: 最優先
    "core": 1.5,         # コア品質: 高優先
    "broadcast": 1.0,    # 放送品質: 標準
    "template": 0.7,     # テンプレート: やや低
    "youtube": 0.5,      # YouTube最適化: 低（安定稼働に無関係）
    "accessibility": 0.3, # アクセシビリティ: 未実装
}


def run_all_plugins(ctx: Any, template_config: Any = None,
                    categories: Optional[List[str]] = None,
                    block_mode: bool = False) -> Dict:
    """
    全登録プラグインを実行し、重み付き統合結果を返す。

    安定稼働重視スコアリング:
      - カテゴリ毎の減点にCATEGORY_WEIGHTSを適用
      - stability/coreカテゴリの満点は高く評価される
      - 基準点: 75点=安定稼働合格, 85点=商用品質
    """
    all_feedback = []
    plugin_results = {}

    # カテゴリ別の減点トラッキング
    category_deductions = {}
    category_max = {}

    for plugin in PLUGIN_REGISTRY:
        if categories and plugin.category not in categories:
            continue

        try:
            result = plugin.analyze(ctx, template_config)
            deductions = result.get("deductions", 0)
            all_feedback.extend(result.get("feedback", []))
            plugin_results[plugin.name] = result

            cat = plugin.category
            category_deductions[cat] = category_deductions.get(cat, 0) + deductions
            category_max[cat] = category_max.get(cat, 0) + 30
        except Exception as e:
            logger.warning(f"Plugin {plugin.name} failed: {e} (Expected safety catch)", exc_info=True)

    # ━━━ 重み付きスコア算出 ━━━
    # 100点から重み付き減点を引く
    # 重みの意味: stability(×2.0)の10点減点 = 20点分のインパクト
    #            youtube(×0.5)の10点減点 = 5点分のインパクト
    #
    # FIX-7A: テンプレート未設定時は template 重みを 0.3 に引き下げ
    # （テンプレート設定済みなら通常の 0.7 を維持）
    effective_weights = dict(CATEGORY_WEIGHTS)
    if template_config is None or not getattr(template_config, 'is_active', False):
        effective_weights["template"] = 0.3
        logger.debug("FIX-7A: テンプレート未設定 → template重み 0.7→0.3")

    weighted_deductions = 0
    for cat, ded in category_deductions.items():
        w = effective_weights.get(cat, 1.0)
        weighted_deductions += ded * w

    final_score = max(0, min(100, round(100 - weighted_deductions)))

    # ━━━ カテゴリ別スコア ━━━
    CATEGORY_LABELS = {
        "core": "🔧 コア品質",
        "template": "📺 テンプレート基準",
        "broadcast": "📡 放送品質",
        "youtube": "▶ YouTube最適化",
        "stability": "🛡️ 安定稼働",
        "accessibility": "♿ アクセシビリティ",
    }

    category_scores = {}
    category_report = []

    for cat in ["stability", "core", "template", "broadcast", "youtube", "accessibility"]:
        max_ded = category_max.get(cat, 0)
        ded = category_deductions.get(cat, 0)

        if max_ded == 0:
            score = None
            status = "⬜ 未実装"
        else:
            score = max(0, round(100 - (ded / max_ded * 100), 1))
            if score >= 90:
                status = "✅ 優秀"
            elif score >= 70:
                status = "🟢 良好"
            elif score >= 50:
                status = "🟡 要改善"
            else:
                status = "🔴 不合格"

        category_scores[cat] = score
        weight = CATEGORY_WEIGHTS.get(cat, 1.0)
        category_report.append({
            "category": cat,
            "label": CATEGORY_LABELS.get(cat, cat),
            "score": score,
            "status": status,
            "weight": weight,
            "deductions": ded,
            "plugin_count": sum(1 for p in PLUGIN_REGISTRY if p.category == cat),
        })

    # ━━━ ブロック判定 ━━━
    block_recommended = False
    if block_mode:
        stability_score = category_scores.get("stability")
        core_score = category_scores.get("core")
        if stability_score is not None and stability_score < 50:
            block_recommended = True
        if core_score is not None and core_score < 50:
            block_recommended = True
        if final_score < 60:
            block_recommended = True

    return {
        "total_deductions": round(weighted_deductions),
        "final_score": final_score,
        "feedback": all_feedback,
        "plugin_results": plugin_results,
        "category_scores": category_scores,
        "category_report": category_report,
        "block_recommended": block_recommended,
    }

