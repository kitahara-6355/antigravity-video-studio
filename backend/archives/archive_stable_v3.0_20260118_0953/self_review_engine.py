"""
Self-Review Engine
Phase 6: Quality Assurance

機能:
- 生成物の自己検分
- 文脈適合度評価
- 自己改善ループ
- 品質スコアリング
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime

from google import genai
from dotenv import load_dotenv
import os

from model_registry import get_model

load_dotenv()
logger = logging.getLogger(__name__)


@dataclass
class QualityScore:
    """品質スコア"""
    context_fit: float  # 文脈適合度
    constitution_fit: float  # 憲法適合度
    technical_quality: float  # 技術品質
    overall: float  # 総合スコア
    details: Dict = field(default_factory=dict)


@dataclass
class ReviewResult:
    """レビュー結果"""
    passed: bool
    score: QualityScore
    issues: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    improvement_applied: bool = False
    improvement_history: List[Dict] = field(default_factory=list)


@dataclass
class ImprovementRecord:
    """改善記録"""
    round: int
    original_score: float
    improved_score: float
    changes_made: List[str]
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class SelfReviewEngine:
    """自己検分・自己改善エンジン"""
    
    REVIEW_PROMPT = """
以下の生成物を評価してください。

## 生成物
タイプ: {generation_type}
内容: {content}

## 文脈
{context}

## 評価基準
1. **context_fit**: 文脈との適合度（0.0-1.0）
2. **constitution_fit**: ブランド憲法との適合度（0.0-1.0）
3. **technical_quality**: 技術的品質（0.0-1.0）

## ブランド憲法
{constitution}

## 出力形式（JSON）
{{
  "context_fit": 0.85,
  "constitution_fit": 0.90,
  "technical_quality": 0.80,
  "issues": ["問題点1", "問題点2"],
  "suggestions": ["改善提案1", "改善提案2"]
}}
"""

    IMPROVEMENT_PROMPT = """
以下の生成物を改善してください。

## 現在の生成物
{current_content}

## 問題点
{issues}

## 改善提案
{suggestions}

## ブランド憲法
{constitution}

## 出力形式
改善後の内容のみを出力してください。
"""

    # 品質閾値
    THRESHOLDS = {
        "context_fit": 0.70,
        "constitution_fit": 0.80,
        "technical_quality": 0.60,
        "overall": 0.70
    }
    
    MAX_IMPROVEMENT_ROUNDS = 3

    def __init__(self):
        api_key = os.getenv("GOOGLE_API_KEY")
        if api_key:
            try:
                self.client = genai.Client(api_key=api_key)
            except Exception as e:
                logger.error(f"Google GenAI Client初期化エラー: {e}", exc_info=True)
                self.client = None
        else:
            logger.warning("GOOGLE_API_KEY が設定されていません。SelfReviewEngine はフォールバックモードで動作します。")
            self.client = None
        self.model = get_model("quality_gate")
        self.constitution = self._load_constitution()
    
    def _load_constitution(self) -> Dict:
        """憲法を読み込み"""
        const_path = Path(__file__).parent / "branding" / "constitution.json"
        if const_path.exists():
            with open(const_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}
    
    def review(self, content: str, generation_type: str, context: Dict) -> ReviewResult:
        """
        生成物をレビュー
        
        Args:
            content: 生成物の内容
            generation_type: telop, image_prompt, scene_structure, etc.
            context: 文脈情報
        
        Returns:
            ReviewResult
        """
        if self.client is None:
            logger.warning("Google GenAI Client が初期化されていないため、フォールバックレビューを適用します。")
            return self._fallback_review()

        prompt = self.REVIEW_PROMPT.format(
            generation_type=generation_type,
            content=content,
            context=json.dumps(context, ensure_ascii=False),
            constitution=json.dumps(self.constitution, ensure_ascii=False, indent=2)
        )
        
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt
            )
            result = self._parse_review(response.text)
        except Exception as e:
            logger.error(f"レビューエラー: {e}", exc_info=True)
            result = self._fallback_review()
        
        return result
    
    def _parse_review(self, text: str) -> ReviewResult:
        """レビュー結果をパース"""
        import re
        json_match = re.search(r'\{[\s\S]*\}', text)
        if not json_match:
            return self._fallback_review()
        
        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError:
            return self._fallback_review()
        
        context_fit = data.get("context_fit", 0.5)
        constitution_fit = data.get("constitution_fit", 0.5)
        technical_quality = data.get("technical_quality", 0.5)
        overall = (context_fit + constitution_fit + technical_quality) / 3
        
        score = QualityScore(
            context_fit=context_fit,
            constitution_fit=constitution_fit,
            technical_quality=technical_quality,
            overall=overall
        )
        
        passed = (
            context_fit >= self.THRESHOLDS["context_fit"] and
            constitution_fit >= self.THRESHOLDS["constitution_fit"] and
            technical_quality >= self.THRESHOLDS["technical_quality"] and
            overall >= self.THRESHOLDS["overall"]
        )
        
        return ReviewResult(
            passed=passed,
            score=score,
            issues=data.get("issues", []),
            suggestions=data.get("suggestions", [])
        )
    
    def _fallback_review(self) -> ReviewResult:
        """フォールバックレビュー（デフォルト合格）"""
        return ReviewResult(
            passed=True,
            score=QualityScore(
                context_fit=0.75,
                constitution_fit=0.75,
                technical_quality=0.75,
                overall=0.75
            )
        )
    
    def review_and_improve(self, 
                           content: str, 
                           generation_type: str, 
                           context: Dict,
                           improve_func: Optional[Callable] = None) -> tuple[str, ReviewResult]:
        """
        レビューして必要なら自己改善
        
        Args:
            content: 生成物
            generation_type: タイプ
            context: 文脈
            improve_func: カスタム改善関数（オプション）
        
        Returns:
            (改善後の内容, レビュー結果)
        """
        current_content = content
        improvement_history = []
        
        for round_num in range(1, self.MAX_IMPROVEMENT_ROUNDS + 1):
            result = self.review(current_content, generation_type, context)
            
            if result.passed:
                result.improvement_history = improvement_history
                result.improvement_applied = len(improvement_history) > 0
                logger.info(f"自己検分合格 (Round {round_num}): {result.score.overall:.2f}")
                return current_content, result
            
            # 改善を試みる
            logger.info(f"自己検分不合格 (Round {round_num}): {result.score.overall:.2f}")
            logger.info(f"問題点: {result.issues}")
            
            if improve_func:
                improved = improve_func(current_content, result.issues, result.suggestions)
            else:
                improved = self._default_improve(current_content, result, context)
            
            improvement_history.append({
                "round": round_num,
                "original_score": result.score.overall,
                "issues": result.issues,
                "changes_made": result.suggestions
            })
            
            current_content = improved
        
        # 最大回数到達
        final_result = self.review(current_content, generation_type, context)
        final_result.improvement_history = improvement_history
        final_result.improvement_applied = True
        
        return current_content, final_result

    def _default_improve(self, content: str, result: ReviewResult, context: Dict) -> str:
        """デフォルトの改善処理を行います。"""
        if self.client is None:
            logger.warning("Google GenAI Client が初期化されていないため、改善をスキップします。")
            return content

        prompt = self.IMPROVEMENT_PROMPT.format(
            current_content=content,
            issues="\n".join(f"- {i}" for i in result.issues),
            suggestions="\n".join(f"- {s}" for s in result.suggestions),
            constitution=json.dumps(self.constitution, ensure_ascii=False, indent=2)
        )
        
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt
            )
            return response.text.strip()
        except Exception as e:
            logger.error(f"改善エラー: {e}", exc_info=True)
            return content


# シングルトンインスタンス
self_review_engine = SelfReviewEngine()


def review_generation(content: str, gen_type: str, context: Dict) -> ReviewResult:
    """生成物をレビュー（簡易関数）"""
    return self_review_engine.review(content, gen_type, context)


def review_and_improve(content: str, gen_type: str, context: Dict) -> tuple[str, ReviewResult]:
    """レビューして改善（簡易関数）"""
    return self_review_engine.review_and_improve(content, gen_type, context)
