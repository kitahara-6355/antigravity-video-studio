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

from dotenv import load_dotenv
from gemini_client_factory import get_gemini_client
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
        self.client = get_gemini_client()
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
            logger.error(f"レビューエラー: {e}")
            result = self._fallback_review()
        
        return result
    
    def _parse_review(self, text: str) -> ReviewResult:
        """レビュー結果をパース"""
        if not text or not isinstance(text, str):
            return self._fallback_review()

        import re
        json_match = re.search(r'\{[\s\S]*\}', text)
        if not json_match:
            return self._fallback_review()
        
        try:
            data = json.loads(json_match.group())
            if not isinstance(data, dict):
                return self._fallback_review()
        except json.JSONDecodeError:
            return self._fallback_review()
        
        try:
            context_fit = float(data.get("context_fit", 0.5) if data.get("context_fit") is not None else 0.5)
            constitution_fit = float(data.get("constitution_fit", 0.5) if data.get("constitution_fit") is not None else 0.5)
            technical_quality = float(data.get("technical_quality", 0.5) if data.get("technical_quality") is not None else 0.5)
        except (TypeError, ValueError):
            return self._fallback_review()

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

        issues = data.get("issues")
        if not isinstance(issues, list):
            issues = []

        suggestions = data.get("suggestions")
        if not isinstance(suggestions, list):
            suggestions = []
        
        return ReviewResult(
            passed=passed,
            score=score,
            issues=issues,
            suggestions=suggestions
        )
    
    def _fallback_review(self) -> ReviewResult:
        """**レビューできなかったときの戻り値**（R1.5-C4）。

        ここは `passed=True / overall=0.75` を返していて、docstring も
        「デフォルト合格」と書いてあった。**AI レビューが一度も走らなくても
        「合格・0.75点」**になり、`POST /api/antigravity/self-review/check` が
        `{"passed": true, "score": 0.75}` を返していた。

        `director_engine.calculate_quality_score()` と
        `verify_production_quality()` で直したのと同じクラスの3件目。
        **「問題が見つからなかった」と「見ていない」は別物。**

        `overall` は 0.0 にするが、**それは「0点」という評価ではない**ので
        `passed=False` と `issues` で「採点していない」ことを明示する
        （`QualityScore` は float を要求するため `None` を入れられない）。
        """
        return ReviewResult(
            passed=False,
            score=QualityScore(
                context_fit=0.0,
                constitution_fit=0.0,
                technical_quality=0.0,
                overall=0.0,
                details={"scored": False, "is_real": False,
                         "data_source": "unavailable",
                         "note": "**レビューは行われていません。**"
                                 "点数は評価結果ではありません"},
            ),
            issues=["レビューを実行できませんでした（**採点していません**）"],
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
        """デフォルトの改善処理"""
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
            logger.error(f"改善エラー: {e}")
            return content


# シングルトンインスタンス
self_review_engine = SelfReviewEngine()


# ============================================================
# Claude Code Breakthrough: AdvisorGate + SelfReview dual gate
# ============================================================
async def advisor_then_review(content: str, gen_type: str, context: dict,
                               task_description: str = '',
                               definition_of_done: str = '') -> tuple:
    """
    Claude Code dual verification pattern:
    1. AdvisorGate (pre-execution review)
    2. SelfReviewEngine (post-execution review)
    """
    # Step 1: AdvisorGate pre-check
    try:
        from agents.advisor_gate import advisor_gate
        if advisor_gate.should_review(gen_type):
            verdict = await advisor_gate.review_before_execution(
                task_description=task_description or f'{gen_type} generation',
                proposed_action={'content_preview': content[:500], 'type': gen_type},
                definition_of_done=definition_of_done or f'{gen_type} meets quality standards',
                context=context,
            )
            if verdict.verdict == 'rejected':
                return content, ReviewResult(
                    passed=False,
                    score=QualityScore(0, 0, 0, 0),
                    issues=[f'AdvisorGate rejected: {verdict.reasoning}'],
                    suggestions=[c.get('suggested', '') for c in verdict.corrections],
                )
    except ImportError:
        logger.debug("AdvisorGate not available — skipping pre-check")
    except Exception as e:
        logger.debug(f"AdvisorGate pre-check failed: {e}")

    # Step 2: SelfReview post-check
    return self_review_engine.review_and_improve(content, gen_type, context)



def review_generation(content: str, gen_type: str, context: Dict) -> ReviewResult:
    """生成物をレビュー（簡易関数）"""
    return self_review_engine.review(content, gen_type, context)


def review_and_improve(content: str, gen_type: str, context: Dict) -> tuple[str, ReviewResult]:
    """レビューして改善（簡易関数）"""
    return self_review_engine.review_and_improve(content, gen_type, context)
