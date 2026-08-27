"""
Quality Gate AI連携強化

推奨タスク P5.1: Gemini APIを使用した高度な文脈理解チェック
推奨タスク P5.2: ユーザー定義の品質チェックルール
推奨タスク P5.3: 過去の品質問題パターン学習
"""

from typing import List, Dict, Any
from dataclasses import dataclass
import json
import logging

logger = logging.getLogger(__name__)


@dataclass
class CustomRule:
    """カスタム品質ルール"""
    id: str
    name: str
    description: str
    check_type: str  # "regex", "keyword", "ai"
    pattern: str
    severity: str = "warning"  # "error", "warning", "info"
    enabled: bool = True


@dataclass
class QualityHistory:
    """品質問題履歴"""
    issue_type: str
    message: str
    timestamp: str
    project: str = ""
    resolved: bool = False


class AIQualityChecker:
    """AI連携品質チェッカー"""
    
    def __init__(self):
        self._history: List[QualityHistory] = []
        self._custom_rules: List[CustomRule] = []
        # Model resolution via unified governance gateway
        try:
            from model_governance import model_governance
            self._model_name = model_governance._resolve_model("quality_gate")
        except ImportError:
            try:
                from model_registry import get_model
                self._model_name = get_model("quality_gate")
            except ImportError:
                self._model_name = "gemini-3.6-flash"
    
    def _build_coherence_prompt(self,
                                scenes: List[Dict[str, Any]],
                                subtitles: List[str]) -> str:
        """P5.1: 文脈整合性チェック用のプロンプトを構築"""
        return f"""
以下の動画シーンと字幕の整合性を分析してください。

シーン情報:
{json.dumps(scenes[:5], ensure_ascii=False, indent=2)}

字幕サンプル:
{chr(10).join(subtitles[:10])}

以下の観点で評価してください:
1. シーンと字幕の内容一致度 (0-100)
2. 文脈の流れの自然さ (0-100)
3. 問題がある箇所（あれば）

JSON形式で回答:
{{"scene_match": 85, "context_flow": 90, "issues": []}}
"""

    async def check_context_coherence(self, 
                                       scenes: List[Dict[str, Any]],
                                       subtitles: List[str]) -> Dict[str, Any]:
        """P5.1: 文脈整合性のAIチェック（model_governance.call() 統合）"""
        prompt = self._build_coherence_prompt(scenes, subtitles)
        try:
            from model_governance import model_governance
            result_text = await model_governance.call(
                task="quality_gate",
                prompt=prompt,
                caller="AIQualityChecker.check_context_coherence",
            )
            return {"status": "success", "result": result_text}
        except ValueError:
            return {"status": "skipped", "reason": "API key not set"}
        except (RuntimeError, TypeError, ImportError) as e:
            logger.error(f"AI check failed: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}
    
    def add_custom_rule(self, rule: CustomRule):
        """P5.2: カスタムルール追加"""
        self._custom_rules.append(rule)
    
    def check_custom_rules(self, content: str) -> List[Dict[str, Any]]:
        """カスタムルールチェック"""
        import re
        issues = []
        
        for rule in self._custom_rules:
            if not rule.enabled:
                continue
            
            if rule.check_type == "keyword":
                if rule.pattern.lower() in content.lower():
                    issues.append({
                        "rule_id": rule.id,
                        "rule_name": rule.name,
                        "severity": rule.severity,
                        "message": rule.description
                    })
            elif rule.check_type == "regex":
                if re.search(rule.pattern, content):
                    issues.append({
                        "rule_id": rule.id,
                        "rule_name": rule.name,
                        "severity": rule.severity,
                        "message": rule.description
                    })
        
        return issues
    
    def record_issue(self, issue: QualityHistory):
        """P5.3: 問題履歴記録"""
        self._history.append(issue)
    
    def get_common_issues(self, limit: int = 10) -> List[Dict[str, Any]]:
        """よくある問題パターン取得"""
        from collections import Counter
        issue_types = Counter(h.issue_type for h in self._history)
        return [
            {"type": t, "count": c}
            for t, c in issue_types.most_common(limit)
        ]
    
    def predict_issues(self, content: str) -> List[str]:
        """過去パターンから問題予測"""
        common = self.get_common_issues(5)
        predictions = []
        
        for item in common:
            if item["count"] >= 3:
                predictions.append(
                    f"過去に'{item['type']}'の問題が{item['count']}回発生しています。注意してください。"
                )
        
        return predictions


# シングルトン
ai_quality_checker = AIQualityChecker()


# デフォルトのカスタムルール
DEFAULT_RULES = [
    CustomRule(
        id="no_placeholder",
        name="プレースホルダー禁止",
        description="[TODO]や[TBD]が残っています",
        check_type="regex",
        pattern=r"\[(TODO|TBD|FIXME)\]",
        severity="warning"
    ),
    CustomRule(
        id="no_test_text",
        name="テスト文字列禁止",
        description="テスト用の文字列が残っています",
        check_type="keyword",
        pattern="ああああ",
        severity="error"
    ),
]

for rule in DEFAULT_RULES:
    ai_quality_checker.add_custom_rule(rule)
