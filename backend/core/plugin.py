"""
Plugin Base Class - プラグインベースクラス

PROJECT_CONSTITUTION §16 準拠:
- 共通インターフェース
- model_requirements宣言
- 自動モデル登録
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, TYPE_CHECKING
from enum import Enum
import logging

if TYPE_CHECKING:
    from .context import ProductionContext

logger = logging.getLogger(__name__)


class PluginPhase(Enum):
    """プラグイン実行フェーズ"""
    PRE_PROCESS = "pre_process"      # 前処理（解析など）
    ANALYSIS = "analysis"             # 分析
    GENERATION = "generation"         # 生成
    POST_PROCESS = "post_process"     # 後処理
    FINALIZATION = "finalization"     # 最終処理


class Plugin(ABC):
    """
    プラグインベースクラス
    
    PROJECT_CONSTITUTION §16 準拠:
    全てのプラグインはこのクラスを継承し、共通インターフェースを実装する。
    
    使用例:
        class MyPlugin(Plugin):
            name = "my_plugin"
            phase = PluginPhase.GENERATION
            priority = 10
            
            model_requirements = {
                "task": "my_task",
                "model": "gemini-2.5-flash",
                "fallback": "gemini-2.5-flash"
            }
            
            def execute(self, context):
                # 処理
                return context
    """
    
    # === 必須プロパティ ===
    
    @property
    @abstractmethod
    def name(self) -> str:
        """プラグイン一意識別子"""
        pass
    
    @property
    def phase(self) -> PluginPhase:
        """実行フェーズ（デフォルト: GENERATION）"""
        return PluginPhase.GENERATION
    
    @property
    def priority(self) -> int:
        """同一フェーズ内の実行順序（小さいほど先に実行）"""
        return 50
    
    # === モデル要件（PROJECT_CONSTITUTION §16.3）===
    
    @property
    def model_requirements(self) -> Optional[Dict[str, Any]]:
        """
        使用AIモデルの宣言
        
        Returns:
            {
                "task": "thumbnail",          # タスク名
                "model": "imagen-4.0",        # 使用モデル
                "fallback": "imagen-3.0",     # フォールバック
                "api_type": "imagen"          # API種別 (gemini/imagen/veo)
            }
        """
        return None
    
    def get_model(self) -> Optional[str]:
        """
        登録されたモデルを取得（陳腐化チェック済み）
        
        ModelRegistryを経由して、陳腐化チェック済みのモデル名を取得する。
        """
        if self.model_requirements:
            if not isinstance(self.model_requirements, dict):
                logger.warning(f"model_requirements must be a dictionary, got {type(self.model_requirements)}")
                return None
            try:
                try:
                    from backend.model_registry import get_model
                except ImportError:
                    from model_registry import get_model
                
                try:
                    plugin_name = self.name
                except (AttributeError, TypeError, ValueError, NotImplementedError, RuntimeError) as name_err:
                    plugin_name = self.__class__.__name__
                    logger.warning(f"Failed to access plugin name: {name_err}")
                
                task = self.model_requirements.get("task", plugin_name)
                if not isinstance(task, str):
                    task = str(task)
                return get_model(task)
            except (ImportError, AttributeError, TypeError, ValueError, KeyError, IndexError, OSError, RuntimeError) as e:
                logger.warning(f"ModelRegistry not available, using declared model: {e}")
                return self.model_requirements.get("model")
        return None
    
    # === 実行メソッド ===
    
    @abstractmethod
    def execute(self, context: "ProductionContext") -> "ProductionContext":
        """
        プラグインのメイン処理
        
        Args:
            context: 制作コンテキスト
            
        Returns:
            更新された制作コンテキスト
        """
        pass
    
    def can_execute(self, context: "ProductionContext") -> bool:
        """
        実行可能かどうかを判定
        
        Args:
            context: 制作コンテキスト
            
        Returns:
            実行可能ならTrue
        """
        return True
    
    def on_error(self, context: "ProductionContext", error: Exception) -> "ProductionContext":
        """
        エラー発生時のハンドリング
        
        Args:
            context: 制作コンテキスト
            error: 発生したエラー
            
        Returns:
            エラー処理後のコンテキスト
        """
        try:
            plugin_name = self.name
        except (AttributeError, TypeError, ValueError, NotImplementedError, RuntimeError):
            plugin_name = self.__class__.__name__

        logger.error(f"Plugin {plugin_name} error: {error}")
        
        if context is not None and hasattr(context, "set_extension") and callable(context.set_extension):
            try:
                context.set_extension(f"{plugin_name}_error", str(error))
            except (AttributeError, TypeError, ValueError, KeyError, RuntimeError) as ext_err:
                logger.error(f"Failed to write error extension to context: {ext_err}")
        else:
            logger.warning(f"Invalid context passed to on_error: {type(context)}")
            
        return context
    
    def validate(self) -> None:
        """
        プラグインの整合性を自己検証する
        
        Raises:
            ValueError: 設定値が不正な場合
            TypeError: 型が不正な場合
        """
        try:
            plugin_name = self.name
        except (AttributeError, TypeError, ValueError, NotImplementedError, RuntimeError) as e:
            raise ValueError(f"Plugin name is not accessible or not implemented: {e}")

        if not plugin_name or not isinstance(plugin_name, str):
            raise ValueError(f"Plugin name must be a non-empty string, got: {plugin_name}")
            
        try:
            phase_val = self.phase
        except (AttributeError, TypeError, ValueError, NotImplementedError, RuntimeError) as e:
            raise ValueError(f"Plugin phase is not accessible: {e}")

        if not isinstance(phase_val, PluginPhase):
            raise TypeError(f"Plugin phase must be a PluginPhase Enum, got: {phase_val}")
            
        try:
            priority_val = self.priority
        except (AttributeError, TypeError, ValueError, NotImplementedError, RuntimeError) as e:
            raise ValueError(f"Plugin priority is not accessible: {e}")

        if not isinstance(priority_val, int):
            raise TypeError(f"Plugin priority must be an integer, got: {priority_val}")
            
        try:
            reqs = self.model_requirements
        except (AttributeError, TypeError, ValueError, NotImplementedError, RuntimeError) as e:
            raise ValueError(f"Plugin model_requirements is not accessible: {e}")

        if reqs is not None:
            if not isinstance(reqs, dict):
                raise TypeError(f"Plugin model_requirements must be a dictionary, got: {reqs}")
            task = reqs.get("task")
            if task is not None and not isinstance(task, str):
                raise TypeError(f"model_requirements 'task' must be a string, got: {task}")
            model = reqs.get("model")
            if model is not None and not isinstance(model, str):
                raise TypeError(f"model_requirements 'model' must be a string, got: {model}")
    
    # === ユーティリティ ===
    
    def log(self, message: str, level: str = "info") -> None:
        """ロギングヘルパー"""
        log_func = getattr(logger, level, logger.info)
        log_func(f"[{self.name}] {message}")
    
    def __repr__(self) -> str:
        return f"<Plugin {self.name} phase={self.phase.value} priority={self.priority}>"
