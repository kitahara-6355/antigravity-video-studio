"""
サービスコンテナ — 依存性注入（DI）パターン（U-11）

設計方針:
- 全サービスをレジストリに登録し、遅延初期化で起動高速化
- ルーターは `container.get("service_name")` で依存を取得
- 関数内 `from xxx import yyy` を排除し、テスタビリティを向上
- シングルトン保証: 2回目以降はキャッシュを返す

使い方:
     from service_container import container

     # ルーター内:
     tracker = container.get("usage_tracker")
     tracker.record_calls(10, "pipeline")

     # テスト時:
     container.register("usage_tracker", mock_tracker)
"""

import logging
import threading
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class ServiceContainer:
    """
    軽量DI コンテナ

    - register(name, instance_or_factory): サービスを登録
    - register_lazy(name, factory_fn): 遅延初期化で登録
    - get(name): サービスを取得（遅延初期化を実行）
    - override(name, instance): テスト用にモックを注入
    """

    def __init__(self):
        self._instances: Dict[str, Any] = {}
        self._factories: Dict[str, Callable] = {}
        self._initialized: bool = False
        self._lock = threading.RLock()
        self._initializing: set = set()

    def register(self, name: str, instance: Any) -> None:
        """即座にインスタンスを登録"""
        self._instances[name] = instance
        logger.debug(f"📦 Service registered: {name}")

    def register_lazy(self, name: str, factory: Callable[[], Any]) -> None:
        """遅延初期化ファクトリーを登録（get 時に初めて呼ばれる）"""
        self._factories[name] = factory
        logger.debug(f"📦 Service registered (lazy): {name}")

    def get(self, name: str) -> Any:
        """
        サービスを取得

        1. 既にインスタンス化済みならキャッシュを返す
        2. ファクトリーが登録されていれば初期化して返す
        3. どちらもなければ KeyError
        """
        with self._lock:
            if name in self._instances:
                return self._instances[name]

            if name in self._initializing:
                raise ValueError(f"Circular dependency detected: '{name}' is already being initialized.")

            if name in self._factories:
                self._initializing.add(name)
                try:
                    factory = self._factories[name]
                    instance = factory()
                    self._instances[name] = instance
                    self._factories.pop(name, None)
                    logger.info(f"✅ Service initialized: {name}")
                    return instance
                except Exception as e:
                    logger.error(f"❌ Service init failed: {name} — {e}", exc_info=True)
                    raise
                finally:
                    self._initializing.remove(name)

            raise KeyError(
                f"Service '{name}' is not registered. "
                f"Available: {list(self._instances.keys()) + list(self._factories.keys())}"
            )

    def override(self, name: str, instance: Any) -> None:
        """テスト用: 既存サービスをモックに差し替え"""
        self._instances[name] = instance
        self._factories.pop(name, None)
        logger.info(f"🔄 Service overridden: {name}")

    def has(self, name: str) -> bool:
        """サービスが登録済みかを確認"""
        return name in self._instances or name in self._factories

    def reset(self) -> None:
        """全サービスをクリア（テスト用）"""
        self._instances.clear()
        self._factories.clear()
        self._initialized = False

    @property
    def registered_services(self) -> list:
        """登録済みサービス名一覧"""
        return sorted(
            set(list(self._instances.keys()) + list(self._factories.keys()))
        )


# ============================================================
# グローバルコンテナ
# ============================================================
container = ServiceContainer()


def setup_services():
    """
    全サービスを遅延登録

    main.py の起動時に1回呼ばれる。
    実際のインスタンス化は初回 get() 時に行われるため、
    起動時間への影響はゼロ。
    """
    if container._initialized:
        return
    container._initialized = True

    # ------ API Usage Tracker ------
    container.register_lazy("usage_tracker", lambda: _init_usage_tracker())

    # ------ YouTube Analytics ------
    container.register_lazy("youtube_analytics", lambda: _init_youtube_analytics())

    # ------ YouTube Optimizer ------
    container.register_lazy("youtube_optimizer", lambda: _init_youtube_optimizer())

    # ------ Thumbnail Plugin ------
    container.register_lazy("thumbnail_plugin", lambda: _init_thumbnail_plugin())

    # ------ Speaker Diarizer ------
    container.register_lazy("speaker_diarizer", lambda: _init_speaker_diarizer())

    # ------ Branding Manager ------
    container.register_lazy("branding_manager", lambda: _init_branding_manager())

    # ------ Pipeline Coordinator ------
    container.register_lazy("pipeline_coordinator", lambda: _init_pipeline_coordinator())

    # ------ Gemini Client ------
    container.register_lazy("gemini_client", lambda: _init_gemini_client())

    # ------ Harness（Anthropic推奨パターン） ------
    container.register_lazy("harness_hook_system", lambda: _init_harness_hooks())
    container.register_lazy("harness_session_manager", lambda: _init_harness_sessions())
    container.register_lazy("harness_governance", lambda: _init_harness_governance())
    container.register_lazy("harness_tool_registry", lambda: _init_harness_tools())

    logger.info(
        f"📦 ServiceContainer: {len(container.registered_services)} services registered (lazy)"
    )


# ============================================================
# ファクトリー関数（遅延初期化）
# ============================================================

def _init_usage_tracker():
    from usage_tracker.api_usage_tracker import APIUsageTracker
    from pathlib import Path
    data_dir = Path(__file__).parent / "data"
    return APIUsageTracker(data_dir / "api_usage.json")


def _init_youtube_analytics():
    from services.youtube_analytics_client import YouTubeAnalyticsClient
    return YouTubeAnalyticsClient()


def _init_youtube_optimizer():
    try:
        from plugins.youtube_optimizer_plugin import youtube_optimizer
        return youtube_optimizer
    except ImportError:
        logger.warning("YouTubeOptimizerPlugin not available")
        return None


def _init_thumbnail_plugin():
    try:
        from plugins.thumbnail_plugin import ThumbnailPlugin
        return ThumbnailPlugin()
    except ImportError:
        logger.warning("ThumbnailPlugin not available")
        return None


def _init_speaker_diarizer():
    from subtitle_engine.speaker_diarizer import SpeakerDiarizer
    return SpeakerDiarizer()


def _init_branding_manager():
    try:
        from branding_manager import BrandingManager
        return BrandingManager()
    except ImportError:
        logger.warning("BrandingManager not available")
        return None


def _init_pipeline_coordinator():
    """旧 PipelineCoordinator（レガシーフォールバック用）"""
    try:
        from agents.pipeline_coordinator import PipelineCoordinator
        return PipelineCoordinator()
    except ImportError:
        logger.info("PipelineCoordinator not available — Harness mode is primary")
        return None


def _init_gemini_client():
    try:
        from gemini_client_factory import get_gemini_client
        return get_gemini_client()
    except (ImportError, ModuleNotFoundError) as e:
        logger.info(f"Gemini client factory not available: {e}")
        return None
    except Exception as e:
        logger.error(f"Gemini client init failed: {e}", exc_info=True)
        return None


def _init_harness_hooks():
    """Harness Hook システム初期化（ビルトインフック登録込み）"""
    try:
        from harness.hooks import hook_system
        hook_system.register_builtin_hooks()
        return hook_system
    except ImportError:
        logger.warning("Harness hooks not available")
        return None


def _init_harness_sessions():
    """Harness セッション管理初期化"""
    try:
        from harness.session_manager import session_manager
        return session_manager
    except ImportError:
        logger.warning("Harness sessions not available")
        return None


def _init_harness_governance():
    """Harness ガバナンスエンジン初期化"""
    try:
        from harness.governance import governance_engine
        return governance_engine
    except ImportError:
        logger.warning("Harness governance not available")
        return None


def _init_harness_tools():
    """Harness ツールレジストリ初期化"""
    try:
        from harness.tool_registry import tool_registry
        return tool_registry
    except ImportError:
        logger.warning("Harness tool registry not available")
        return None
