"""
Model Registry: Centralized model management with dynamic optimization checking.

機能:
1. タスク別最適モデル選択
2. 廃止予定モデル警告
3. フォールバック自動切り替え
4. 動的モデル最適性チェック（API経由で利用可能なモデルを確認）
"""
import json
import os
import logging
import google.api_core.exceptions
from pathlib import Path
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from dotenv import load_dotenv

# Load environment
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

logger = logging.getLogger(__name__)

@dataclass
class ModelDeprecationWarning:
    """廃止警告（Python標準DeprecationWarningとの名前衝突を回避）"""
    model: str
    replacement: str
    deadline: str
    reason: str
    days_remaining: int

class ModelRegistry:
    """
    モデル管理の中央レジストリ
    
    使用例:
        registry = ModelRegistry()
        model = registry.get_model_for_task("subtitle_split")
        warnings = registry.check_deprecation_warnings()
    """
    
    _instance = None
    _config: Dict[str, Any] = None
    _available_models_cache: List[str] = None
    _cache_timestamp: datetime = None
    CACHE_TTL_SECONDS = 3600  # 1時間
    
    def __new__(cls):
        """Singleton pattern"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_config()
        return cls._instance
    
    def _load_config(self):
        """設定ファイルを読み込み"""
        config_path = Path(__file__).parent / "model_config.json"
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                self._config = json.load(f)
            logger.info(f"Model config loaded: version {self._config.get('version')}")
        except FileNotFoundError:
            logger.warning("model_config.json not found, using defaults")
            self._config = {
                "default_model": "gemini-3.6-flash",
                "task_mapping": {},
                "deprecated": {}
            }
    
    def _delegate_to_governance(self, task: str) -> Optional[str]:
        """model_governance が利用可能なら解決を委譲する"""
        try:
            from model_governance import model_governance
            return model_governance._resolve_model(task)
        except ImportError:
            return None

    def get_model_for_task(self, task: str) -> str:
        """
        タスクに最適なモデルを返す
        
        Phase D: model_governance._resolve_model() に内部委譲 (Strangler Fig)。
        37箇所の呼び出し元を変更せずにガバナンス統一を実現。
        
        Args:
            task: タスク名 (subtitle_split, quality_gate, director, etc.)
        
        Returns:
            モデル名
        """
        # Phase D: model_governance に委譲（deprecated差替 + 監査ログ自動適用）
        governed_model = self._delegate_to_governance(task)
        if governed_model is not None:
            return governed_model
        
        # フォールバック: model_governance 未導入時は既存ロジック
        task_mapping = self._config.get("task_mapping", {})
        model = task_mapping.get(task, self._config.get("default_model", "gemini-3.6-flash"))
        
        # 廃止予定モデルのチェック
        deprecated = self._config.get("deprecated", {})
        if model in deprecated:
            replacement = deprecated[model]["replacement"]
            logger.warning(f"Model '{model}' is deprecated, using '{replacement}' instead")
            return replacement
        
        return model
    
    def get_default_model(self) -> str:
        """デフォルトモデルを返す"""
        return self._config.get("default_model", "gemini-3.6-flash")
    
    def get_fallback(self, model: str) -> Optional[str]:
        """フォールバックモデルを返す"""
        models = self._config.get("models", {})
        if model in models:
            return models[model].get("fallback")
        return self.get_default_model()
    
    def check_deprecation_warnings(self) -> List[ModelDeprecationWarning]:
        """廃止予定モデルの警告を返す"""
        warnings = []
        deprecated = self._config.get("deprecated", {})
        today = date.today()
        
        for model, info in deprecated.items():
            deadline = datetime.strptime(info["deadline"], "%Y-%m-%d").date()
            days_remaining = (deadline - today).days
            
            if days_remaining <= 90:  # 90日以内に廃止
                warnings.append(ModelDeprecationWarning(
                    model=model,
                    replacement=info["replacement"],
                    deadline=info["deadline"],
                    reason=info.get("reason", ""),
                    days_remaining=days_remaining
                ))
        
        return warnings
    
    def _is_cache_valid(self, force_refresh: bool) -> bool:
        """キャッシュが有効かどうかを判定"""
        if force_refresh or self._available_models_cache is None:
            return False
        if not self._cache_timestamp:
            return False
        elapsed = (datetime.now() - self._cache_timestamp).total_seconds()
        return elapsed < self.CACHE_TTL_SECONDS

    def _fetch_available_models_from_api(self) -> Optional[List[str]]:
        """APIから利用可能なモデルのリストを取得。失敗時はNoneを返す"""
        try:
            from gemini_client_factory import get_gemini_client
            client = get_gemini_client()
            if not client:
                logger.warning("GOOGLE_API_KEY not found, skipping availability check")
                return None
            
            models = client.models.list()
            return [m.name.replace("models/", "") for m in models]
        except google.api_core.exceptions.GoogleAPIError as e:
            logger.error(f"Google API error fetching model list: {e}")
            return None
        except ImportError as e:
            logger.error(f"Import error fetching model list: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching model list: {e}")
            return None

    def check_model_availability(self, force_refresh: bool = False) -> Dict[str, bool]:
        """
        動的モデル最適性チェック: API経由で利用可能なモデルを確認
        
        Args:
            force_refresh: キャッシュを無視して再取得
        
        Returns:
            {モデル名: 利用可能かどうか} の辞書
        """
        if self._is_cache_valid(force_refresh):
            return self._build_availability_dict()
        
        fetched = self._fetch_available_models_from_api()
        if fetched is None:
            return {}
        
        self._available_models_cache = fetched
        self._cache_timestamp = datetime.now()
        logger.info(f"Fetched {len(self._available_models_cache)} available models from API")
        
        return self._build_availability_dict()
    
    def _build_availability_dict(self) -> Dict[str, bool]:
        """設定ファイルのモデルの利用可能状況を辞書で返す"""
        if self._available_models_cache is None:
            return {}
        
        result = {}
        configured_models = list(self._config.get("models", {}).keys())
        configured_models += list(self._config.get("deprecated", {}).keys())
        
        for model in configured_models:
            # APIモデル名は "gemini-2.0-flash" or "gemini-2.0-flash-001" など
            result[model] = any(
                model in available_model 
                for available_model in self._available_models_cache
            )
        
        return result
    
    def get_optimal_model_report(self) -> str:
        """
        現在のモデル最適性レポートを生成
        """
        report = []
        report.append("=" * 50)
        report.append("Model Registry - 最適性レポート")
        report.append("=" * 50)
        
        # 廃止警告
        warnings = self.check_deprecation_warnings()
        if warnings:
            report.append("\n⚠️ 廃止予定モデル警告:")
            for w in warnings:
                status = "🔴 期限切れ" if w.days_remaining < 0 else f"⚠️ 残り{w.days_remaining}日"
                report.append(f"  - {w.model} → {w.replacement} ({status})")
        
        # 利用可能チェック
        availability = self.check_model_availability()
        if availability:
            report.append("\n📡 モデル利用可能状況:")
            for model, available in availability.items():
                status = "✅ 利用可能" if available else "❌ 利用不可"
                report.append(f"  - {model}: {status}")
        
        # タスクマッピング
        report.append("\n📋 タスク別モデル割り当て:")
        for task, model in self._config.get("task_mapping", {}).items():
            report.append(f"  - {task}: {model}")
        
        report.append("=" * 50)
        return "\n".join(report)
    
    def validate_configuration(self) -> List[str]:
        """
        設定ファイルの整合性チェック
        
        Returns:
            問題点のリスト
        """
        issues = []
        
        # タスクマッピングのモデルが存在するかチェック
        models = self._config.get("models", {})
        deprecated = self._config.get("deprecated", {})
        
        for task, model in self._config.get("task_mapping", {}).items():
            if model not in models and model not in deprecated:
                issues.append(f"Task '{task}' references unknown model '{model}'")
        
        # フォールバックモデルが存在するかチェック
        for model, info in models.items():
            fallback = info.get("fallback")
            if fallback and fallback not in models:
                issues.append(f"Model '{model}' has invalid fallback '{fallback}'")
        
        return issues
    
    # === プラグインからの動的登録（PROJECT_CONSTITUTION §16.3）===
    
    def _extract_plugin_requirements(self, plugin) -> Optional[Dict[str, Any]]:
        """プラグインからモデル要件を抽出する"""
        req = getattr(plugin, 'model_requirements', None)
        if not req:
            return None
        
        model = req.get("model")
        if not model:
            return None
        
        return {
            "task": req.get("task", getattr(plugin, 'name', 'unknown')),
            "model": model,
            "fallback": req.get("fallback")
        }

    def _merge_plugin_requirements(self, task: str, model: str, fallback: Optional[str], plugin_name: str) -> None:
        """抽出されたプラグイン要件を設定にマージする"""
        if "task_mapping" not in self._config:
            self._config["task_mapping"] = {}
        self._config["task_mapping"][task] = model
        
        if "models" not in self._config:
            self._config["models"] = {}
        
        if model not in self._config["models"]:
            self._config["models"][model] = {
                "status": "auto_registered",
                "description": f"Auto-registered by {plugin_name}",
                "use_cases": [task],
                "fallback": fallback,
                "cost_tier": "unknown"
            }
        else:
            if task not in self._config["models"][model].get("use_cases", []):
                self._config["models"][model].setdefault("use_cases", []).append(task)

    def register_plugin_requirement(self, plugin) -> None:
        """
        プラグインのモデル要件を動的登録
        
        Args:
            plugin: model_requirementsプロパティを持つプラグイン
        """
        requirements = self._extract_plugin_requirements(plugin)
        if not requirements:
            return
        
        task = requirements["task"]
        model = requirements["model"]
        fallback = requirements["fallback"]
        plugin_name = getattr(plugin, 'name', 'plugin')
        
        self._merge_plugin_requirements(task, model, fallback, plugin_name)
        
        # 陳腐化チェック
        self._check_and_warn_plugin(model, plugin_name)
        
        logger.info(f"Registered plugin model requirement: {task} -> {model}")
    
    def _check_and_warn_plugin(self, model: str, plugin_name: str) -> None:
        """プラグインのモデルが陳腐化していないかチェック"""
        deprecated = self._config.get("deprecated", {})
        if model in deprecated:
            dep = deprecated[model]
            logger.warning(
                f"⚠️ Plugin '{plugin_name}' uses deprecated model '{model}'. "
                f"Replace with '{dep['replacement']}' by {dep['deadline']}"
            )
    
    def run_startup_checks(self) -> Dict[str, Any]:
        """
        起動時の総合チェック（PROJECT_CONSTITUTION §16.3）
        
        Returns:
            チェック結果の辞書
        """
        result = {
            "deprecation_warnings": [],
            "unavailable_models": [],
            "fallbacks_applied": [],
            "status": "ok"
        }
        
        # 廃止警告チェック
        warnings = self.check_deprecation_warnings()
        for w in warnings:
            result["deprecation_warnings"].append({
                "model": w.model,
                "replacement": w.replacement,
                "deadline": w.deadline,
                "days_remaining": w.days_remaining
            })
            logger.warning(f"⚠️ Deprecated model: {w.model} -> {w.replacement} (deadline: {w.deadline})")
        
        # 設定整合性チェック
        issues = self.validate_configuration()
        if issues:
            result["configuration_issues"] = issues
            result["status"] = "warning"
            for issue in issues:
                logger.warning(f"⚠️ Configuration issue: {issue}")
        
        if result["deprecation_warnings"]:
            result["status"] = "warning"
        
        logger.info(f"Startup checks completed: {result['status']}")
        return result


# グローバルインスタンス取得用関数
def get_registry() -> ModelRegistry:
    """ModelRegistryのシングルトンインスタンスを取得"""
    return ModelRegistry()


def get_model(task: str) -> str:
    """タスクに最適なモデルを取得（ショートカット関数）"""
    return get_registry().get_model_for_task(task)


def run_startup_checks() -> Dict[str, Any]:
    """起動時チェックを実行（ショートカット関数）"""
    return get_registry().run_startup_checks()


# MODEL_CONFIG: 設定へのアクセスをモジュールレベル __getattr__ で提供
def __getattr__(name: str) -> Any:
    if name == "MODEL_CONFIG":
        return get_registry()._config
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


def __dir__() -> List[str]:
    return globals().keys() | {"MODEL_CONFIG"}


# CLI実行時のレポート出力
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    registry = ModelRegistry()
    print(registry.get_optimal_model_report())
    
    issues = registry.validate_configuration()
    if issues:
        print("\n❌ 設定の問題点:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("\n✅ 設定に問題はありません")
