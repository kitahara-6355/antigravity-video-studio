"""
Hook Improver Service - フック改善案生成サービス

PROJECT_CONSTITUTION §23 YouTube最適化規約準拠:
- Gemini APIでフック改善案を生成
- 入力: 現在のフックテキスト、スコア、問題点
- 出力: 3つの改善案（代替フレーズ）
"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import logging
import os

# Model Registry (SSoT: model_config.json)
try:
    from model_registry import get_model
except ImportError:
    # **モデル ID を直書きしない**（R1.5-C6）。正典は model_config.json で、
    # それを読む解決器が model_policy（標準ライブラリだけに依存するので
    # model_registry より落ちにくい）。直書きの既定値は入替のたびに腐り、
    # 実際それで 2026-10-16 に提供終了する 2.5 系が本番の実行経路に居座った。
    from model_policy import resolve as _resolve

    def get_model(task):
        return _resolve(task).model

logger = logging.getLogger(__name__)


@dataclass
class HookImprovement:
    """フック改善案"""
    original_text: str
    improved_text: str
    improvement_type: str  # "attention", "emotion", "curiosity"
    expected_score_boost: int  # 予想スコア上昇
    rationale: str  # 改善理由


@dataclass
class HookImprovementResult:
    """フック改善結果"""
    original_score: int
    improvements: List[HookImprovement] = field(default_factory=list)
    best_recommendation: Optional[HookImprovement] = None
    analysis_summary: str = ""


class HookImproverService:
    """
    フック改善サービス
    
    Gemini APIを使用して、動画の冒頭5秒（フック）を
    より視聴維持率が高くなるよう改善案を生成する。
    """
    
    IMPROVEMENT_TYPES = {
        "attention": "注意を引く表現に変更",
        "emotion": "感情に訴える表現に変更",
        "curiosity": "好奇心を刺激する表現に変更"
    }
    
    def __init__(self):
        self._client = None
    
    def _get_client(self):
        """Gemini クライアントを取得"""
        if self._client is None:
            from google import genai
            from gemini_client_factory import get_gemini_client
            self._client = get_gemini_client()
        return self._client
    
    async def generate_improvements(
        self,
        hook_text: str,
        current_score: int,
        hook_analysis: Dict[str, Any],
        video_topic: str = ""
    ) -> HookImprovementResult:
        """
        フック改善案を生成
        
        Args:
            hook_text: 現在のフックテキスト
            current_score: 現在のフックスコア
            hook_analysis: フック分析結果
            video_topic: 動画のトピック
            
        Returns:
            HookImprovementResult: 3つの改善案を含む結果
        """
        logger.info(f"Generating hook improvements for score {current_score}")
        
        try:
            client = self._get_client()
            
            # 問題点を抽出
            problems = hook_analysis.get("improvement_suggestions", [])
            attention_grabber = hook_analysis.get("attention_grabber", "不明")
            
            prompt = self._build_prompt(
                hook_text=hook_text,
                current_score=current_score,
                problems=problems,
                attention_grabber=attention_grabber,
                video_topic=video_topic
            )
            
            response = client.models.generate_content(
                model=get_model("proofreader"),
                contents=prompt
            )
            
            # レスポンスをパース
            improvements = self._parse_response(response.text, hook_text)
            
            # 最良の推奨を選択
            best = max(improvements, key=lambda x: x.expected_score_boost) if improvements else None
            
            result = HookImprovementResult(
                original_score=current_score,
                improvements=improvements,
                best_recommendation=best,
                analysis_summary=f"3つの改善案を生成しました。最も効果的な案は「{best.improvement_type}」タイプで、約{best.expected_score_boost}点のスコア向上が期待できます。" if best else "改善案を生成できませんでした。"
            )
            
            logger.info(f"Generated {len(improvements)} hook improvements")
            return result
            
        except Exception as e:
            logger.error(f"Hook improvement generation failed: {e}")
            return HookImprovementResult(
                original_score=current_score,
                improvements=[],
                analysis_summary=f"改善案の生成に失敗しました: {str(e)}"
            )
    
    def _build_prompt(
        self,
        hook_text: str,
        current_score: int,
        problems: List[str],
        attention_grabber: str,
        video_topic: str
    ) -> str:
        """プロンプトを構築"""
        problems_text = "\n".join([f"- {p}" for p in problems]) if problems else "特になし"
        
        return f"""
あなたはYouTube動画の専門家です。動画の冒頭5秒（フック）を改善してください。

## 現在のフック
テキスト: "{hook_text}"
スコア: {current_score}/100
タイプ: {attention_grabber}
動画トピック: {video_topic or "不明"}

## 問題点
{problems_text}

## タスク
以下の3タイプで改善案を1つずつ生成してください：

1. **attention（注意型）**: 驚きや衝撃で視聴者の注意を引く
2. **emotion（感情型）**: 共感や感動で視聴者の心を掴む
3. **curiosity（好奇心型）**: 疑問や謎で視聴者を引き込む

## 出力形式（JSON）
```json
[
  {{
    "type": "attention",
    "improved_text": "改善後のテキスト",
    "score_boost": 15,
    "rationale": "この改善が効果的な理由"
  }},
  {{
    "type": "emotion",
    "improved_text": "改善後のテキスト",
    "score_boost": 12,
    "rationale": "この改善が効果的な理由"
  }},
  {{
    "type": "curiosity",
    "improved_text": "改善後のテキスト",
    "score_boost": 18,
    "rationale": "この改善が効果的な理由"
  }}
]
```

日本語で回答してください。
"""
    
    def _parse_response(self, response_text: str, original_text: str) -> List[HookImprovement]:
        """レスポンスをパース"""
        import json
        
        try:
            # JSONブロックを抽出
            if "```json" in response_text:
                json_text = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                json_text = response_text.split("```")[1].split("```")[0]
            else:
                json_text = response_text
            
            data = json.loads(json_text.strip())
            
            improvements = []
            for item in data:
                improvement = HookImprovement(
                    original_text=original_text,
                    improved_text=item.get("improved_text", ""),
                    improvement_type=item.get("type", "unknown"),
                    expected_score_boost=item.get("score_boost", 0),
                    rationale=item.get("rationale", "")
                )
                improvements.append(improvement)
            
            return improvements
            
        except Exception as e:
            logger.warning(f"Failed to parse hook improvement response: {e}")
            return []


# シングルトンインスタンス
hook_improver = HookImproverService()
