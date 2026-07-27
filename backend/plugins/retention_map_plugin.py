import logging
import os
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, ValidationError
import random

logger = logging.getLogger(__name__)

# --- Prevention 1: Schema Check First ---
class RetentionSegment(BaseModel):
    start_time: int = Field(..., description="開始時間(秒)")
    end_time: int = Field(..., description="終了時間(秒)")
    risk_score: int = Field(..., description="離脱リスクスコア（0-100、高いほど危険）")
    visual_change: bool = Field(False, description="視覚的変化があったか")
    audio_change: bool = Field(False, description="聴覚的変化があったか")
    text_change: bool = Field(False, description="テロップ等の変化があったか")
    dopamine_hit: bool = Field(False, description="複合的な強い変化（ドーパミンヒット）があったか")

class ReengagementSuggestion(BaseModel):
    timestamp_sec: int = Field(..., description="提案する挿入時間(秒)")
    suggestion_type: str = Field(..., description="提案種別（B-roll, 効果音, ジャンプカット等）")
    reason: str = Field(..., description="提案の理由")

class RetentionMapReport(BaseModel):
    video_id: str
    total_duration_sec: int
    segments: List[RetentionSegment]
    suggestions: List[ReengagementSuggestion]
    overall_risk_assessment: str

class RetentionMapError(Exception):
    """Retention Map Plugin 内部で発生するエラーのカスタム例外"""
    pass

class RetentionMapPlugin:
    """
    [Phase 3: Retention Map Engine]
    動画（または台本）のエンゲージメント低下リスクを算出し、
    維持率を高めるためのリエンゲージメントポイントを提案する。
    """
    
    def __init__(self):
        pass
        
    def analyze_retention_risks(self, video_id: str, duration_sec: int, video_path: Optional[str] = None) -> RetentionMapReport:
        """
        [3.1 Retention Map Analyzer] 
        [3.2 Dopamine Hit Checker]
        音声波形や映像情報から30秒ごと（または10秒ごと）のリスクを評価する。
        """
        if not video_id or not isinstance(video_id, str):
            logger.error(f"❌ [Retention Map] video_id が無効です: {video_id}")
            raise RetentionMapError("video_id must be a non-empty string.")

        if duration_sec is None or not isinstance(duration_sec, int) or duration_sec <= 0:
            logger.error(f"❌ [Retention Map] 不適切な duration_sec が指定されました: {duration_sec}")
            raise RetentionMapError("duration_sec must be a positive integer.")

        if duration_sec > 86400:
            logger.error(f"❌ [Retention Map] 動画長が制限（24時間）を超えています: {duration_sec}s")
            raise RetentionMapError("duration_sec cannot exceed 86400 seconds (24 hours).")

        if video_path is not None:
            if not isinstance(video_path, str) or not video_path:
                logger.error(f"❌ [Retention Map] video_path が無効な文字列です: {video_path}")
                raise RetentionMapError("video_path must be a non-empty string if provided.")
            if not os.path.exists(video_path):
                logger.error(f"❌ [Retention Map] 指定された video_path が存在しません: {video_path}")
                raise RetentionMapError(f"video_path does not exist: {video_path}")

        try:
            # Prevention 2: No Silent Mocks
            logger.warning(f"[STUB] 現状は映像・音声解析をモック稼働 (Video: {video_id})。将来的にOpenCV/Librosaと統合予定。")
            
            segments = []
            # 10秒ごとのセグメントで評価
            for start in range(0, duration_sec, 10):
                end = min(start + 10, duration_sec)
                
                # モック：ランダムに変化を付与
                has_visual = random.random() > 0.4
                has_audio = random.random() > 0.5
                has_text = random.random() > 0.6
                
                # 10秒以内に視覚・聴覚・テキストの変化が揃っていればドーパミンヒットと判定
                is_hit = has_visual and (has_audio or has_text)
                
                risk = 0
                if not is_hit:
                    risk = random.randint(40, 80)
                else:
                    risk = random.randint(5, 30)
                    
                # 最初の10秒（フック）は自動的に高刺激と仮定するか、分析を厳しくする
                if start == 0:
                    is_hit = True
                    risk = random.randint(5, 20)
                    
                segments.append(RetentionSegment(
                    start_time=start,
                    end_time=end,
                    risk_score=risk,
                    visual_change=has_visual,
                    audio_change=has_audio,
                    text_change=has_text,
                    dopamine_hit=is_hit
                ))
                
            # Prevention: 最終セグメントの時間が全体のdurationと一致しているか整合性チェック
            if segments and segments[-1].end_time != duration_sec:
                logger.warning(f"⚠️ [Retention Map] セグメント終端({segments[-1].end_time}s)が全体長({duration_sec}s)と一致していません。")
                
            return self._generate_suggestions(video_id, duration_sec, segments)
        except ValidationError as e:
            logger.exception(f"❌ [Retention Map] Pydanticのバリデーションに失敗しました: {str(e)}")
            raise RetentionMapError(f"Failed to analyze retention risks: {str(e)}") from e
        except RetentionMapError:
            raise
        except (TypeError, ValueError) as e:
            logger.exception(f"❌ [Retention Map] 引数またはパラメータの型/値エラーが発生しました: {str(e)}")
            raise RetentionMapError(f"Failed to analyze retention risks: {str(e)}") from e
        except Exception as e:
            logger.exception(f"❌ [Retention Map] 分析実行中に予期せぬ例外が発生しました: {str(e)}")
            raise RetentionMapError(f"Failed to analyze retention risks: {str(e)}") from e
        
    def _generate_suggestions(self, video_id: str, duration_sec: int, segments: List[RetentionSegment]) -> RetentionMapReport:
        """
        [3.3 Re-engagement Suggester]
        分析結果に基づき、長期間動きがない場所（特に3分などの節目）に提案を行う。
        """
        try:
            suggestions = []
            consecutive_boring_secs = 0
            
            for seg in segments:
                if not seg.dopamine_hit:
                    consecutive_boring_secs += (seg.end_time - seg.start_time)
                else:
                    consecutive_boring_secs = 0
                    
                # 30秒以上強い変化がない箇所は提案
                if consecutive_boring_secs >= 30:
                    suggestions.append(ReengagementSuggestion(
                        timestamp_sec=seg.start_time,
                        suggestion_type="ジャンプカットまたはB-roll挿入",
                        reason=f"{consecutive_boring_secs}秒間、視覚的な強い変化がありません。視聴者の離脱リスクが高まっています。"
                    ))
                    consecutive_boring_secs = 0  # 提案した後はカウントリセット
                    
            # 3分の節目（180秒）付近でのリエンゲージメントチェック
            three_min_points = [i * 180 for i in range(1, (duration_sec // 180) + 1)]
            existing_timestamps = [s.timestamp_sec for s in suggestions]
            
            for t_mark in three_min_points:
                # すでに近い時間（前後15秒以内）に退屈アラートの提案があれば重複を避ける
                if any(abs(t - t_mark) <= 15 for t in existing_timestamps):
                    continue
                    
                # 該当時間のセグメントを探す
                target_seg = next((s for s in segments if s.start_time <= t_mark < s.end_time), None)
                if target_seg and not target_seg.dopamine_hit:
                    suggestions.append(ReengagementSuggestion(
                        timestamp_sec=t_mark,
                        suggestion_type="シーンの転換（BGM変更または大文字テロップ）",
                        reason=f"{t_mark//60}分の節目です。文脈のリセットを行い、視聴者の注意を引き戻してください。"
                    ))
                    
            # 全体評価
            avg_risk = sum(s.risk_score for s in segments) / len(segments) if segments else 0
            assessment = "安全"
            if avg_risk > 60:
                assessment = "危険（要大幅な再編集）"
            elif avg_risk > 40:
                assessment = "要注意（一部シーンのテンポ改善が必要）"
                
            # Prevention 3: Japanese Validation
            logger.info(f"📊 [Retention Map] 解析完了。平均リスク: {avg_risk:.1f} ({assessment}) / 提案数: {len(suggestions)}")
            
            return RetentionMapReport(
                video_id=video_id,
                total_duration_sec=duration_sec,
                segments=segments,
                suggestions=suggestions,
                overall_risk_assessment=assessment
            )
        except ValidationError as e:
            logger.exception(f"❌ [Retention Map] 提案生成中のバリデーションに失敗しました: {str(e)}")
            raise RetentionMapError(f"Failed to generate suggestions: {str(e)}") from e
        except RetentionMapError:
            raise
        except (TypeError, ValueError, AttributeError) as e:
            logger.exception(f"❌ [Retention Map] 提案生成中にパラメータまたは属性エラーが発生しました: {str(e)}")
            raise RetentionMapError(f"Failed to generate suggestions: {str(e)}") from e
        except Exception as e:
            logger.exception(f"❌ [Retention Map] 提案生成中に予期せぬ例外が発生しました: {str(e)}")
            raise RetentionMapError(f"Failed to generate suggestions: {str(e)}") from e

# Singleton
retention_map_plugin = RetentionMapPlugin()
