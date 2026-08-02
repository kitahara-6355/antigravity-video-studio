"""
Design System - デザインシステム統合モジュール

PROJECT_CONSTITUTION §17 準拠:
- デザイントークン管理
- ムード連動
- 変更履歴記録
- evolution_log.json 連携 (DS-06 M3.5)
"""
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path

from typing import Dict, Any, Optional, List
from pathlib import Path
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)


class DesignTokenManager:
    """
    デザイントークンマネージャー
    
    PROJECT_CONSTITUTION §17 準拠:
    - constitution.jsonからdesign_tokensを管理
    - ムード別トークンの取得
    - 変更履歴の記録
    """
    
    def __init__(self):
        self._branding_dir = Path(__file__).parent.parent / "branding"
        self._constitution_path = self._branding_dir / "constitution.json"
        self._history_path = self._branding_dir / "design_tokens_history.json"
        # 実行のたびに追記される進化履歴。設定ファイル（constitution.json 等）と
        # 違って書き換わるので、読み書きの両方をこの経路へ通す。
        self._evolution_log_path = _writable_path("backend/branding/evolution_log.json")
        self._design_tokens_path = Path(__file__).parent.parent.parent / "frontend" / "src" / "design_tokens.json"
        self._cache: Optional[Dict] = None
        self._cache_mtime: float = 0
    
    def get_tokens(self, mood: str = "elegant") -> Dict[str, Any]:
        """
        指定ムードのデザイントークンを取得
        
        Args:
            mood: ムード名（elegant, dynamic, dramatic）
        
        Returns:
            デザイントークン辞書
        """
        constitution = self._load_constitution()
        tokens = constitution.get("design_tokens", {})
        
        if mood not in tokens:
            logger.warning(f"Mood '{mood}' not found, falling back to elegant")
            mood = "elegant"
        
        return tokens.get(mood, {})
    
    def get_all_tokens(self) -> Dict[str, Dict]:
        """全ムードのトークンを取得"""
        constitution = self._load_constitution()
        return constitution.get("design_tokens", {})
    
    def get_color_palette(self, mood: str = "elegant") -> Dict[str, str]:
        """カラーパレットを取得"""
        tokens = self.get_tokens(mood)
        return tokens.get("color_palette", {})
    
    def get_typography(self, mood: str = "elegant") -> Dict[str, Any]:
        """タイポグラフィ設定を取得"""
        tokens = self.get_tokens(mood)
        return tokens.get("typography", {})
    
    def get_motion(self, mood: str = "elegant") -> Dict[str, Any]:
        """モーション設定を取得"""
        tokens = self.get_tokens(mood)
        return tokens.get("motion", {})
    
    def get_prompt_suffix(self, mood: str = "elegant", api_type: str = "imagen") -> str:
        """AI生成用プロンプトサフィックスを取得"""
        tokens = self.get_tokens(mood)
        if api_type == "imagen":
            return tokens.get("imagen_prompt_suffix", "")
        elif api_type == "veo":
            return tokens.get("veo_prompt_suffix", "")
        return ""
    
    def update_tokens(
        self,
        mood: str,
        updates: Dict[str, Any],
        source: str = "manual",
        reason: str = ""
    ) -> Dict[str, Any]:
        """
        デザイントークンを更新（PROJECT_CONSTITUTION §17.3）
        
        Args:
            mood: 対象ムード
            updates: 更新内容
            source: 更新元（manual, chat, decision, quality_check）
            reason: 更新理由
        
        Returns:
            更新結果
        """
        if not isinstance(updates, dict):
            raise TypeError("updates must be a dictionary")
        constitution = self._load_constitution()
        tokens = constitution.setdefault("design_tokens", {})
        mood_tokens = tokens.setdefault(mood, {})
        
        import copy
        old_values = {}
        for key, value in updates.items():
            if key in mood_tokens:
                old_values[key] = copy.deepcopy(mood_tokens[key])
        
        # 更新を適用
        for key, value in updates.items():
            if isinstance(value, dict) and key in mood_tokens and isinstance(mood_tokens[key], dict):
                mood_tokens[key].update(value)
            else:
                mood_tokens[key] = value
        
        # 保存
        self._save_constitution(constitution)
        
        # 変更履歴を記録
        self._record_change(mood, updates, old_values, source, reason)
        
        # キャッシュを無効化
        self._cache = None
        
        logger.info(f"Updated design tokens for mood '{mood}' from {source}")
        
        return {
            "status": "updated",
            "mood": mood,
            "updates": updates,
            "source": source
        }
    
    def _load_constitution(self) -> Dict:
        """constitution.jsonをロード（キャッシュ付き）"""
        try:
            mtime = self._constitution_path.stat().st_mtime
            
            if self._cache is not None and mtime <= self._cache_mtime:
                return self._cache
            
            with open(self._constitution_path, "r", encoding="utf-8") as f:
                self._cache = json.load(f)
                self._cache_mtime = mtime
                return self._cache
        except FileNotFoundError as e:
            logger.warning(f"Constitution file not found at {self._constitution_path}: {e}")
            return {}
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse constitution JSON: {e}")
            return {}
        except (PermissionError, OSError) as e:
            logger.error(f"Failed to access constitution file: {e}")
            return {}
    
    def _save_constitution(self, constitution: Dict) -> None:
        """constitution.jsonを保存"""
        with open(self._constitution_path, "w", encoding="utf-8") as f:
            json.dump(constitution, f, ensure_ascii=False, indent=2)
    
    def _record_change(
        self,
        mood: str,
        updates: Dict,
        old_values: Dict,
        source: str,
        reason: str
    ) -> None:
        """変更履歴を記録"""
        history = self._load_history()
        
        entry = {
            "timestamp": datetime.now().isoformat(),
            "mood": mood,
            "updates": updates,
            "old_values": old_values,
            "source": source,
            "reason": reason
        }
        
        history.setdefault("changes", []).append(entry)
        history["last_updated"] = datetime.now().isoformat()
        
        self._save_history(history)
        
        # evolution_log.json にもデザイン変更を記録 (DS-06)
        self._record_to_evolution_log(mood, updates, old_values, source, reason)
    
    def _load_history(self) -> Dict:
        """変更履歴をロード"""
        if not self._history_path.exists():
            return {"changes": []}
        try:
            with open(self._history_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load design tokens history: {e}")
        return {"changes": []}
    
    def _save_history(self, history: Dict) -> None:
        """変更履歴を保存"""
        with open(self._history_path, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    
    def get_change_history(self, limit: int = 10) -> List[Dict]:
        """変更履歴を取得"""
        history = self._load_history()
        changes = history.get("changes", [])
        return changes[-limit:] if limit else changes
    
    def _record_to_evolution_log(
        self,
        mood: str,
        updates: Dict,
        old_values: Dict,
        source: str,
        reason: str
    ) -> None:
        """
        evolution_log.json にデザイン変更を記録 (DS-06 M3.5)
        
        Soul System Phase 4 統合の基盤。
        デザイントークン変更を進化ログに記録し、
        チャンネルの美的嗜好の推移を追跡可能にする。
        """
        try:
            evolution_log = {"entries": []}
            if self._evolution_log_path.exists():
                with open(self._evolution_log_path, "r", encoding="utf-8") as f:
                    evolution_log = json.load(f)
            
            # デザイン変更エントリを構築
            changed_keys = list(updates.keys())
            entry = {
                "timestamp": datetime.now().timestamp(),
                "type": "design_token_change",
                "summary": f"デザイントークン更新: {mood} ({', '.join(changed_keys[:3])}{'...' if len(changed_keys) > 3 else ''})",
                "insight": reason or f"{source}によるデザイントークン変更",
                "source": source,
                "stat_changes": [
                    f"{mood}/{key}" for key in changed_keys
                ],
                "detail": {
                    "mood": mood,
                    "updates": updates,
                    "old_values": old_values
                }
            }
            
            evolution_log.setdefault("entries", []).append(entry)
            
            with open(self._evolution_log_path, "w", encoding="utf-8") as f:
                json.dump(evolution_log, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Design token change recorded to evolution_log: {mood}")
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse evolution_log JSON: {e}")
        except (PermissionError, OSError) as e:
            logger.warning(f"Failed to write design token change to evolution_log: {e}")
    
    def get_frontend_tokens(self) -> Optional[Dict]:
        """
        フロントエンド用 design_tokens.json を読み込む (DS-06 M3.5)
        
        Returns:
            design_tokens.json の内容、またはNone
        """
        try:
            if self._design_tokens_path.exists():
                with open(self._design_tokens_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse frontend design tokens JSON: {e}")
        except (PermissionError, OSError) as e:
            logger.warning(f"Failed to read frontend design tokens: {e}")
        return None
    
    def update_frontend_tokens(
        self,
        theme: str,
        category: str,
        updates: Dict[str, Any],
        source: str = "manual",
        reason: str = ""
    ) -> Dict[str, Any]:
        """
        フロントエンド用 design_tokens.json を更新 (DS-06 M3.5)
        
        Args:
            theme: テーマ名 (light / dark)
            category: カテゴリ (color / typography / shadow / radius / motion)
            updates: 更新内容
            source: 更新元
            reason: 更新理由
        
        Returns:
            更新結果
        """
        if not isinstance(updates, dict):
            raise TypeError("updates must be a dictionary")
        tokens = self.get_frontend_tokens()
        if tokens is None:
            return {"status": "error", "message": "design_tokens.json not found"}
        
        theme_data = tokens.get("themes", {}).get(theme)
        if theme_data is None:
            return {"status": "error", "message": f"theme '{theme}' not found"}
        
        cat_data = theme_data.get(category)
        if cat_data is None:
            return {"status": "error", "message": f"category '{category}' not found in theme '{theme}'"}
        
        # 更新前の値を記録
        old_values = {}
        for key, value in updates.items():
            if key in cat_data:
                old_values[key] = cat_data[key]
        
        # deep merge
        for key, value in updates.items():
            if isinstance(value, dict) and key in cat_data and isinstance(cat_data[key], dict):
                cat_data[key].update(value)
            else:
                cat_data[key] = value
        
        # 保存
        with open(self._design_tokens_path, "w", encoding="utf-8") as f:
            json.dump(tokens, f, ensure_ascii=False, indent=2)
        
        # evolution_log に記録
        self._record_to_evolution_log(
            f"{theme}/{category}",
            updates,
            old_values,
            source,
            reason
        )
        
        logger.info(f"Updated frontend design tokens: {theme}/{category}")
        
        return {
            "status": "updated",
            "theme": theme,
            "category": category,
            "updates": updates,
            "source": source
        }


# シングルトンインスタンス
design_token_manager = DesignTokenManager()
