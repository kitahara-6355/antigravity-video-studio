"""
Design Auto Learner - デザイン自動学習

PROJECT_CONSTITUTION §17.3 準拠:
- 意思決定からの自動学習
- 品質チェック結果からの学習
"""
from typing import Dict, Any, Optional
from datetime import datetime
from threading import Lock
import logging
import json

logger = logging.getLogger(__name__)


class DesignAutoLearner:
    """
    デザイン自動学習エンジン
    
    PROJECT_CONSTITUTION §17.3 準拠:
    - ユーザーの意思決定から学習
    - 品質チェック結果から改善
    
    使用例:
        learner = DesignAutoLearner()
        learner.learn_from_decision("サムネイル", "reject", "色が薄い", {"mood": "elegant"})
    """
    
    LEARNING_THRESHOLD = 3  # 同じ理由が3回以上でトークン更新を提案
    
    def __init__(self):
        self._learning_store_path = None
        self._lock = Lock()
    
    @property
    def learning_store_path(self):
        if self._learning_store_path is None:
            from pathlib import Path
            self._learning_store_path = Path(__file__).parent.parent / "branding" / "design_learning_store.json"
        return self._learning_store_path
    
    def _create_decision_entry(
        self,
        target_type: str,
        decision: str,
        reason: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """意思決定のエントリーを作成 (関数分割)"""
        return {
            "timestamp": datetime.now().isoformat(),
            "target_type": target_type,
            "decision": decision,
            "reason": reason,
            "mood": context.get("mood", "elegant"),
            "context": context
        }
    
    def learn_from_decision(
        self,
        target_type: str,
        decision: str,
        reason: Optional[str],
        context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        意思決定から学習
        
        Args:
            target_type: 対象タイプ（thumbnail, video, text など）
            decision: 判断（approve, reject, modify）
            reason: 理由
            context: コンテキスト情報（mood など）
        
        Returns:
            学習結果
        """
        if context is None or not isinstance(context, dict):
            context = {}
        if reason is None:
            reason = ""
        elif not isinstance(reason, str):
            reason = str(reason)

        logger.info(f"Learning from decision: {target_type} - {decision}")
        
        with self._lock:
            # 学習データを保存
            decision_entry = self._create_decision_entry(target_type, decision, reason, context)
            self._store_learning(decision_entry)
            
            # パターン分析
            patterns = self._analyze_patterns(target_type, decision, reason)
            
            # 閾値を超えた場合、トークン更新を提案
            if patterns.get("count", 0) >= self.LEARNING_THRESHOLD:
                suggestion = self._generate_token_suggestion(patterns)
                if suggestion:
                    return {
                        "status": "suggestion",
                        "message": f"同じパターンが{patterns['count']}回検出されました",
                        "suggestion": suggestion,
                        "patterns": patterns
                    }
            
            return {
                "status": "learned",
                "message": "学習データを記録しました",
                "entry": decision_entry
            }
    
    def learn_from_quality_check(
        self,
        quality_result: Optional[Dict[str, Any]],
        mood: str = "elegant"
    ) -> Dict[str, Any]:
        """
        品質チェック結果から学習
        
        Args:
            quality_result: 品質チェック結果
            mood: ムード
        
        Returns:
            学習結果
        """
        if quality_result is None or not isinstance(quality_result, dict):
            logger.warning("Invalid quality result provided to learn_from_quality_check.")
            return {
                "status": "error",
                "message": "Invalid quality result"
            }

        with self._lock:
            issues = quality_result.get("issues", [])
            if not isinstance(issues, list):
                issues = []
                
            score_raw = quality_result.get("score", 0)
            try:
                score = float(score_raw)
            except (ValueError, TypeError):
                logger.warning(f"Invalid score value: {score_raw}. Defaulting to 0.")
                score = 0
            
            if score >= 80:
                # 高スコアの場合、現在の設定を強化
                return self._reinforce_current_settings(mood)
            
            # 低スコアの場合、問題から学習 (リスト内包表記を用いて簡潔に構築)
            suggestions = [
                s for issue in issues
                if (s := self._issue_to_suggestion(issue, mood)) is not None
            ]
            
            return {
                "status": "analyzed",
                "score": score,
                "suggestions": suggestions
            }
    
    def _store_learning(self, entry: Dict) -> None:
        """学習データを保存"""
        store_data = self._load_store()
        store_data.setdefault("entries", []).append(entry)
        store_data["last_updated"] = datetime.now().isoformat()
        self._save_store(store_data)
    
    def _load_store(self) -> Dict:
        """学習ストアをロード (例外処理を整理)"""
        try:
            if not self.learning_store_path.exists():
                return {"entries": []}
        except OSError as e:
            logger.error(f"Failed to check existence of learning store path: {e}")
            return {"entries": []}
            
        try:
            with open(self.learning_store_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning("Failed to decode JSON from learning store.")
        except OSError as e:
            logger.error(f"Failed to read learning store: {e}")
            
        return {"entries": []}
    
    def _save_store(self, store_data: Dict) -> None:
        """学習ストアを保存 (命名改善: store -> store_data)"""
        try:
            self.learning_store_path.parent.mkdir(parents=True, exist_ok=True)
            import os
            tmp_path = self.learning_store_path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(store_data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.learning_store_path)
        except OSError as e:
            logger.error(f"Failed to save learning store: {e}")
    
    def _analyze_patterns(
        self,
        target_type: str,
        decision: str,
        reason: str
    ) -> Dict[str, Any]:
        """パターン分析"""
        store_data = self._load_store()
        entries = store_data.get("entries", [])
        
        # 同様の理由をカウント
        similar_count = 0
        moods = []
        
        for entry in entries:
            if (entry.get("decision") == decision and
                self._is_similar_reason(entry.get("reason", ""), reason)):
                similar_count += 1
                moods.append(entry.get("mood"))
        
        return {
            "count": similar_count,
            "target_type": target_type,
            "decision": decision,
            "reason": reason,
            "affected_moods": list(set(moods))
        }
    
    def _is_similar_reason(self, reference_reason: str, target_reason: str) -> bool:
        """理由が類似しているか判定 (命名改善: reason1, reason2 -> reference_reason, target_reason)"""
        # 簡易実装: キーワードベース
        keywords_ref = set(reference_reason.lower().split())
        keywords_tgt = set(target_reason.lower().split())
        
        if not keywords_ref or not keywords_tgt:
            return False
        
        overlap = len(keywords_ref & keywords_tgt)
        return overlap >= 2 or (overlap / min(len(keywords_ref), len(keywords_tgt)) > 0.5)
    
    def _has_color_keywords(self, reason: str) -> bool:
        """カラー関連のキーワードを含むか (関数分割)"""
        return any(w in reason for w in ["色", "color", "暗い", "明るい", "薄い", "濃い"])
        
    def _has_typography_keywords(self, reason: str) -> bool:
        """フォント関連のキーワードを含むか (関数分割)"""
        return any(w in reason for w in ["フォント", "font", "文字", "読み", "大き", "小さ"])
        
    def _has_motion_keywords(self, reason: str) -> bool:
        """モーション関連のキーワードを含むか (関数分割)"""
        return any(w in reason for w in ["動き", "アニメ", "早い", "遅い", "硬い"])
    
    def _generate_token_suggestion(self, patterns: Dict) -> Optional[Dict]:
        """トークン更新の提案を生成 (マッピング定義により構造を改善)"""
        reason = patterns.get("reason", "")
        reason_lower = reason.lower()  # {"reason": None} の場合に AttributeError をスローする挙動を維持
        
        affected_moods = patterns.get("affected_moods", [])
        
        rules = [
            (self._has_color_keywords, "color_palette", "カラーパレットの調整を検討"),
            (self._has_typography_keywords, "typography", "タイポグラフィの調整を検討"),
            (self._has_motion_keywords, "motion", "モーション設定の調整を検討"),
        ]
        
        for check_fn, suggestion_type, suggestion_msg in rules:
            if check_fn(reason_lower):
                return {
                    "type": suggestion_type,
                    "suggestion": suggestion_msg,
                    "affected_moods": affected_moods
                }
        
        return None
    
    def _reinforce_current_settings(self, mood: str) -> Dict[str, Any]:
        """現在の設定を強化（高スコア時）"""
        return {
            "status": "reinforced",
            "message": f"ムード '{mood}' の設定は効果的です",
            "mood": mood
        }
    
    def _issue_to_suggestion(self, quality_issue: Dict, mood: str) -> Optional[Dict]:
        """問題から提案を生成 (命名改善: issue -> quality_issue)"""
        issue_type = quality_issue.get("type", "")
        
        if issue_type == "color_contrast":
            return {
                "mood": mood,
                "type": "color_palette",
                "suggestion": "コントラストを強化"
            }
        
        if issue_type == "readability":
            return {
                "mood": mood,
                "type": "typography",
                "suggestion": "フォントサイズを大きく"
            }
        
        return None
    
    def get_learning_summary(self) -> Dict[str, Any]:
        """学習サマリーを取得"""
        with self._lock:
            store_data = self._load_store()
            entries = store_data.get("entries", [])
            
            # 統計
            by_decision = {"approve": 0, "reject": 0, "modify": 0}
            by_mood = {}
            
            for entry in entries:
                decision = entry.get("decision", "")
                mood = entry.get("mood", "")
                
                if decision in by_decision:
                    by_decision[decision] += 1
                
                by_mood[mood] = by_mood.get(mood, 0) + 1
            
            return {
                "total_entries": len(entries),
                "by_decision": by_decision,
                "by_mood": by_mood,
                "last_updated": store_data.get("last_updated")
            }


# シングルトンインスタンス
design_auto_learner = DesignAutoLearner()
