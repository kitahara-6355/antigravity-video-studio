"""
Hook Evolution Service — フック改善履歴の管理サービス

AR-04 対応: youtube_optimizer.py のルーター層から
ビジネスロジック（evolution_log.json の読み書き）を分離。
"""
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
from safe_io import SafeJsonStore, BRANDING_DIR

logger = logging.getLogger(__name__)

EVOLUTION_LOG_FILE = BRANDING_DIR / "evolution_log.json"


class HookEvolutionService:
    """フック改善適用・取り消し・履歴管理サービス"""

    def __init__(self):
        self._store = SafeJsonStore(
            EVOLUTION_LOG_FILE,
            default={"entries": [], "hook_improvements": []}
        )

    def apply_improvement(
        self,
        task_id: str,
        improvement_type: str,
        original_text: str,
        improved_text: str,
        expected_score_boost: int = 0
    ) -> Dict[str, Any]:
        """フック改善を適用し、evolution_log に記録する"""
        def updater(data):
            if "hook_improvements" not in data:
                data["hook_improvements"] = []
            data["hook_improvements"].append({
                "timestamp": datetime.now().isoformat(),
                "task_id": task_id,
                "type": improvement_type,
                "original_text": original_text,
                "improved_text": improved_text,
                "expected_score_boost": expected_score_boost,
                "status": "applied"
            })
            return data

        try:
            self._store.update(updater)
            logger.info(f"Hook improvement applied: {improvement_type}")

            return {
                "success": True,
                "applied": {
                    "type": improvement_type,
                    "text": improved_text,
                    "expected_boost": expected_score_boost
                },
                "message": f"「{improvement_type}」タイプの改善案を適用しました",
                "can_revert": True
            }
        except (OSError, TypeError, ValueError, AttributeError, KeyError) as e:
            logger.error(f"Failed to apply hook improvement: {e}")
            return {
                "success": False,
                "message": f"改善案の適用に失敗しました: {e}"
            }

    def revert_latest(self, task_id: str = "") -> Dict[str, Any]:
        """最後の適用済み改善を取り消す"""
        try:
            data = self._store.load()
            improvements = data.get("hook_improvements", [])

            for entry in reversed(improvements):
                if entry.get("status") == "applied":
                    if task_id and entry.get("task_id") != task_id:
                        continue
                    entry["status"] = "reverted"
                    entry["reverted_at"] = datetime.now().isoformat()
                    self._store.save(data)
                    return {
                        "success": True,
                        "reverted_text": entry["original_text"],
                        "message": "改善前のテキストに戻しました"
                    }

            return {
                "success": False,
                "message": "元に戻せる改善案がありません"
            }
        except (OSError, TypeError, ValueError, AttributeError, KeyError) as e:
            logger.error(f"Failed to revert latest hook improvement: {e}")
            return {
                "success": False,
                "message": f"改善案の取り消しに失敗しました: {e}"
            }

    def get_history(self, task_id: str = "") -> Dict[str, Any]:
        """フック改善履歴を取得する"""
        try:
            data = self._store.load()
            history = data.get("hook_improvements", [])

            if task_id:
                history = [h for h in history if h.get("task_id") == task_id]

            return {
                "success": True,
                "count": len(history),
                "history": history
            }
        except (OSError, TypeError, ValueError, AttributeError, KeyError) as e:
            logger.error(f"Failed to get hook improvement history: {e}")
            return {
                "success": False,
                "message": f"履歴の取得に失敗しました: {e}",
                "history": []
            }


# Singleton
hook_evolution_service = HookEvolutionService()
