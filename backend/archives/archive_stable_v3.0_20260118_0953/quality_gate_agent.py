"""
Quality Gate Agent - 品質ゲート自動化

システム改善計画 フェーズ5: 品質保証の完全自動化
レンダリング前に独立プロセスで品質チェックを実行
"""

import json
import logging
import re
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional
from enum import Enum

logger = logging.getLogger(__name__)

KATAKANA_PATTERN = re.compile(r'[ァ-ヶー]{4,}')


class QualityLevel(Enum):
    """品質レベル定義"""
    CRITICAL = "critical"  # 致命的（レンダリング不可）
    WARNING = "warning"    # 警告（修正推奨）
    INFO = "info"          # 情報（参考）


@dataclass
class QualityIssue:
    """品質問題"""
    level: QualityLevel
    category: str
    message: str
    suggestion: str
    location: Optional[str] = None


@dataclass
class QualityReport:
    """品質レポート"""
    is_ready: bool
    score: int
    issues: List[QualityIssue]
    summary: str
    
    def to_dict(self) -> dict:
        return {
            "is_ready": self.is_ready,
            "score": self.score,
            "issues": [
                {
                    "level": issue.level.value,
                    "category": issue.category,
                    "message": issue.message,
                    "suggestion": issue.suggestion,
                    "location": issue.location
                }
                for issue in self.issues
            ],
            "summary": self.summary
        }


class QualityGateAgent:
    """品質ゲートエージェント"""
    
    # 品質基準しきい値
    THRESHOLD_PASS = 80
    THRESHOLD_WARNING = 60
    
    def __init__(self):
        self.checks = [
            self._check_typos,
            self._check_brand_consistency,
            self._check_subtitle_rhythm,
            self._check_scene_coherence
        ]
    
    def run_gate(self, content: Dict[str, Any]) -> QualityReport:
        """
        品質ゲートを実行
        
        Args:
            content: {
                "full_text": str,       # 脚本テキスト
                "scenes": list,         # シーン構成
                "segments": list,       # 字幕データ
                "constitution": dict    # ブランド憲法
            }
        
        Returns:
            QualityReport: 品質レポート
        """
        issues: List[QualityIssue] = []
        
        # 各チェックを実行
        for check_func in self.checks:
            try:
                check_issues = check_func(content)
                issues.extend(check_issues)
            except KeyError as e:
                logger.warning(f"Quality check missing required key: {check_func.__name__} - Missing key: {e}", exc_info=True)
            except TypeError as e:
                logger.warning(f"Quality check type mismatch: {check_func.__name__} - {e}", exc_info=True)
            except ValueError as e:
                logger.warning(f"Quality check invalid value: {check_func.__name__} - {e}", exc_info=True)
            except (AttributeError, IndexError, RuntimeError, re.error) as e:
                logger.error(f"Unexpected quality check failure: {check_func.__name__} - {e}", exc_info=True)
        
        # スコア計算
        score = self._calculate_score(issues)
        
        # 合格判定
        is_ready = score >= self.THRESHOLD_PASS and not any(
            issue.level == QualityLevel.CRITICAL for issue in issues
        )
        
        # サマリー生成
        summary = self._generate_summary(score, issues, is_ready)
        
        report = QualityReport(
            is_ready=is_ready,
            score=score,
            issues=issues,
            summary=summary
        )
        
        logger.info(f"Quality Gate: Score={score}, Ready={is_ready}, Issues={len(issues)}")
        
        return report
    
    def _calculate_score(self, issues: List[QualityIssue]) -> int:
        """スコア計算"""
        base_score = 100
        
        for issue in issues:
            if issue.level == QualityLevel.CRITICAL:
                base_score -= 30
            elif issue.level == QualityLevel.WARNING:
                base_score -= 10
            elif issue.level == QualityLevel.INFO:
                base_score -= 2
        
        return max(0, min(100, base_score))
    
    def _generate_summary(self, score: int, issues: List[QualityIssue], is_ready: bool) -> str:
        """サマリー生成"""
        critical_count = sum(1 for i in issues if i.level == QualityLevel.CRITICAL)
        warning_count = sum(1 for i in issues if i.level == QualityLevel.WARNING)
        
        if is_ready:
            if score >= 90:
                return "✅ 優秀な品質です。レンダリングを推奨します。"
            else:
                return f"✅ 合格基準を満たしています（スコア: {score}）。{warning_count}件の警告を確認後、レンダリング可能です。"
        else:
            return f"❌ 品質基準未達（スコア: {score}）。{critical_count}件の致命的問題を修正してください。"
    
    # =====================================
    # 品質チェック関数
    # =====================================
    
    def _check_typos(self, content: Dict[str, Any]) -> List[QualityIssue]:
        """誤字脱字チェック（簡易版）"""
        issues = []
        segments = content.get("segments", [])
        
        # よくある誤変換パターン
        common_errors = {
            "以外と": "意外と",
            "とうり": "とおり",
            "づつ": "ずつ",
        }
        
        for i, seg in enumerate(segments):
            if not isinstance(seg, dict):
                continue
            text = str(seg.get("text") or "")
            for wrong, correct in common_errors.items():
                if wrong in text:
                    issues.append(QualityIssue(
                        level=QualityLevel.WARNING,
                        category="誤字脱字",
                        message=f"「{wrong}」は「{correct}」の誤りの可能性があります",
                        suggestion=f"「{wrong}」→「{correct}」に修正を検討",
                        location=f"字幕 #{i+1}"
                    ))
        
        return issues
    
    def _check_brand_consistency(self, content: Dict[str, Any]) -> List[QualityIssue]:
        """ブランド整合性チェック"""
        issues = []
        constitution = content.get("constitution", {})
        full_text = content.get("full_text", "")
        
        # 禁止ワードチェック
        forbidden_words = constitution.get("forbidden_words", [])
        for word in forbidden_words:
            if word in full_text:
                issues.append(QualityIssue(
                    level=QualityLevel.CRITICAL,
                    category="ブランド保護",
                    message=f"禁止ワード「{word}」が含まれています",
                    suggestion="該当箇所を削除または言い換えてください"
                ))
        
        return issues
    
    def _check_subtitle_rhythm(self, content: Dict[str, Any]) -> List[QualityIssue]:
        """字幕リズムチェック"""
        issues = []
        segments = content.get("segments", [])
        
        for i, seg in enumerate(segments):
            if not isinstance(seg, dict):
                continue
            text = str(seg.get("text") or "")
            try:
                start = float(seg.get("start") or 0.0)
                end = float(seg.get("end") or 0.0)
            except (ValueError, TypeError):
                start = 0.0
                end = 0.0
            duration = end - start
            char_count = len(text)
            
            # 長すぎる字幕チェック（20文字以上 かつ 表示時間3秒未満）
            if char_count > 20 and duration < 3:
                issues.append(QualityIssue(
                    level=QualityLevel.WARNING,
                    category="リズム",
                    message=f"字幕が長すぎます（{char_count}文字/{duration:.1f}秒）",
                    suggestion="字幕を2行に分割するか、表示時間を延長してください",
                    location=f"字幕 #{i+1}"
                ))
            
            # 短すぎる字幕チェック（2文字以下）
            if char_count <= 2 and char_count > 0:
                issues.append(QualityIssue(
                    level=QualityLevel.INFO,
                    category="リズム",
                    message=f"非常に短い字幕です（{char_count}文字）",
                    suggestion="前後の字幕と結合を検討してください",
                    location=f"字幕 #{i+1}"
                ))
        
        return issues
    
    def _check_scene_coherence(self, content: Dict[str, Any]) -> List[QualityIssue]:
        """シーン演出の論理性チェック"""
        issues = []
        scenes = content.get("scenes", [])
        full_text = content.get("full_text", "")
        
        for i, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                continue
            source_type = str(scene.get("source_type") or "AI")
            name = str(scene.get("name") or "")
            
            # AI生成なのに固有名詞が含まれている場合は警告
            if source_type == "AI":
                if KATAKANA_PATTERN.search(name):
                    issues.append(QualityIssue(
                        level=QualityLevel.INFO,
                        category="演出ロジック",
                        message=f"AI生成シーンに固有名詞が含まれている可能性",
                        suggestion="実写素材の使用を検討してください",
                        location=f"シーン #{i+1}: {name}"
                    ))
        
        return issues


# シングルトンインスタンス
quality_gate = QualityGateAgent()
