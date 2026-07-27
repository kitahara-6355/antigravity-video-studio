"""
TaskLearningEngine と OrchestrationHub の統合レイヤー

OrchestrationHub の _generate_batch() から呼び出し可能な
薄いインターフェースを提供する。

Flash稼働中でも安全に使用可能（読み取り専用 of 分析結果を返すのみ）。
"""
import json
import logging
import threading
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, TypedDict, List, Set, Dict

from backend.agents.orchestration.task_learning_engine import TaskLearningEngine

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parent
_reports_path: Optional[Path] = None
_cache_path: Optional[Path] = None
_engine: Optional[TaskLearningEngine] = None
_last_engine_reports_path: Optional[Path] = None
_last_engine_cache_path: Optional[Path] = None
_lock = threading.Lock()

# ==========================================
# 1. 型定義 (TypedDict)
# ==========================================

class GroupStats(TypedDict):
    hits: int
    total: int
    durations: List[float]

class ModuleAffinity(TypedDict):
    module: str
    best_group: str
    hit_rate: float
    sample_size: int
    all_groups: Dict[str, dict]

class DiminishingReturn(TypedDict):
    module: str
    trend: str
    recent_avg: float
    earlier_avg: float
    decline_rate: float
    total_tasks: int

class GroupPerformance(TypedDict):
    hit_rate: float
    total: int
    hits: int
    avg_duration_sec: float

# ==========================================
# 2. カスタム例外クラス
# ==========================================

class LearningIntegrationError(Exception):
    """learning_integration モジュールにおける基底例外クラス"""
    pass

class EngineInitializationError(LearningIntegrationError):
    """エンジンの初期化（ファイル読み込みやパース含む）に失敗した際の例外"""
    pass

class EngineExecutionError(LearningIntegrationError):
    """エンジンのロジック実行時に発生した例外"""
    pass


@contextmanager
def _handle_engine_exceptions(action_name: str):
    """例外を適切にキャッチしてカスタム例外にマッピングする"""
    try:
        yield
    except LearningIntegrationError:
        raise
    except (OSError, json.JSONDecodeError) as e:
        raise EngineInitializationError(f"Cache file access error during {action_name}: {e}") from e
    except (KeyError, ValueError, TypeError, AttributeError, ZeroDivisionError) as e:
        raise EngineExecutionError(f"Engine logic error during {action_name}: {e}") from e
    except Exception as e:
        raise EngineExecutionError(f"Unexpected error ({type(e).__name__}) during {action_name}: {e}") from e


def _log_global_exception(func_name: str, e: Exception) -> None:
    """グローバル関数での例外を適切にログに記録するヘルパー"""
    cause = e.__cause__ or e
    cause_type = type(cause).__name__
    if isinstance(e, EngineInitializationError):
        logger.warning(f"[LearningIntegration] Cache file access error or invalid in {func_name} ({cause_type}): {cause}")
    elif isinstance(e, (EngineExecutionError, TypeError, ValueError)):
        if isinstance(cause, (KeyError, ValueError, TypeError, AttributeError, ZeroDivisionError)):
            logger.warning(f"[LearningIntegration] Engine logic error in {func_name} ({cause_type}): {cause}")
        else:
            tb = traceback.format_exc()
            logger.error(f"[LearningIntegration] Unexpected exception in {func_name} ({cause_type}): {cause}" + chr(10) + tb, exc_info=True)

# ==========================================
# 3. クラス設計 (LearningIntegrationHub)
# ==========================================

class LearningIntegrationHub:
    """TaskLearningEngine との統合を管理するメインハブクラス (設計スタブ)"""

    def __init__(self, reports_path: Optional[Path] = None, cache_path: Optional[Path] = None) -> None:
        if reports_path is not None and not isinstance(reports_path, Path):
            raise TypeError(f"reports_path must be Path or None, got {type(reports_path)}")
        if cache_path is not None and not isinstance(cache_path, Path):
            raise TypeError(f"cache_path must be Path or None, got {type(cache_path)}")
        self.reports_path = reports_path
        self.cache_path = cache_path

    def get_engine(self) -> TaskLearningEngine:
        """TaskLearningEngine インスタンスを取得する"""
        try:
            return get_engine(self.reports_path, self.cache_path)
        except Exception as e:
            raise EngineInitializationError(f"TaskLearningEngine initialization failed: {e}") from e

    def suggest_module_for_group(
        self,
        group: str,
        available_modules: List[str],
        exclude: Optional[Set[str]] = None
    ) -> Optional[str]:
        """指定グループに最適なモジュールを推薦する (スタブ)"""
        # 型チェック
        if not isinstance(group, str):
            raise TypeError(f"group must be str, got {type(group)}")
        if not isinstance(available_modules, list):
            raise TypeError(f"available_modules must be list, got {type(available_modules)}")
        if not all(isinstance(m, str) for m in available_modules):
            raise TypeError("all elements in available_modules must be str")
        if exclude is not None:
            if not isinstance(exclude, set):
                raise TypeError(f"exclude must be set or None, got {type(exclude)}")
            if not all(isinstance(e, str) for e in exclude):
                raise TypeError("all elements in exclude must be str")

        with _handle_engine_exceptions("suggest_module_for_group"):
            engine = self.get_engine()
            return engine.suggest_module_for_group(group, available_modules, exclude)

    def get_optimal_composition(self, batch_size: int) -> Optional[Dict[str, int]]:
        """最適なバッチ配分を取得する (スタブ)"""
        if not isinstance(batch_size, int):
            raise TypeError(f"batch_size must be int, got {type(batch_size)}")
        if batch_size < 0:
            raise ValueError(f"batch_size must be non-negative, got {batch_size}")

        with _handle_engine_exceptions("get_optimal_composition"):
            engine = self.get_engine()
            return engine.suggest_optimal_batch_composition(batch_size)

    def get_diminishing_modules(self) -> Set[str]:
        """収穫逓減に入ったモジュールの集合を返す (スタブ)"""
        with _handle_engine_exceptions("get_diminishing_modules"):
            engine = self.get_engine()
            declining = engine.detect_diminishing_returns(threshold=0.5)
            return {d["module"] for d in declining}

    def refresh_and_cache(self) -> None:
        """学習エンジンをリフレッシュしてキャッシュを更新する (スタブ)"""
        with _handle_engine_exceptions("refresh_and_cache"):
            # ロックを取得する前に新しいエンジンを生成し、キャッシュを保存する（ディスク I/O 競合回避）
            new_engine = TaskLearningEngine(reports_path=self.reports_path, cache_path=self.cache_path)
            new_engine.save_cache()

            global _engine, _last_engine_reports_path, _last_engine_cache_path
            with _lock:
                _engine = new_engine
                _last_engine_reports_path = self.reports_path
                _last_engine_cache_path = self.cache_path
            logger.info("[LearningIntegrationHub] Cache refreshed")

# ==========================================
# 4. 後方互換性のためのグローバル関数
# ==========================================

def set_paths(reports_path: Optional[Path] = None, cache_path: Optional[Path] = None) -> None:
    """テスト用にファイルのパスを上書きする。"""
    if reports_path is not None and not isinstance(reports_path, Path):
        raise TypeError(f"reports_path must be Path or None, got {type(reports_path)}")
    if cache_path is not None and not isinstance(cache_path, Path):
        raise TypeError(f"cache_path must be Path or None, got {type(cache_path)}")
    
    global _reports_path, _cache_path, _engine, _last_engine_reports_path, _last_engine_cache_path
    with _lock:
        _reports_path = reports_path
        _cache_path = cache_path
        _engine = None
        _last_engine_reports_path = None
        _last_engine_cache_path = None


def get_engine(reports_path: Optional[Path] = None, cache_path: Optional[Path] = None) -> TaskLearningEngine:
    """シングルトンの TaskLearningEngine を取得する。"""
    global _engine, _last_engine_reports_path, _last_engine_cache_path
    
    # target_reports / target_cache はスレッドローカルまたは引数から算出
    target_reports = reports_path if reports_path is not None else _reports_path
    target_cache = cache_path if cache_path is not None else _cache_path

    from backend.agents.orchestration.task_learning_engine import _FLASH_REPORTS_PATH, _LEARNING_CACHE_PATH
    expected_reports = target_reports or _FLASH_REPORTS_PATH
    expected_cache = target_cache or _LEARNING_CACHE_PATH

    with _lock:
        if _engine is not None:
            last_reports = _last_engine_reports_path or _FLASH_REPORTS_PATH
            last_cache = _last_engine_cache_path or _LEARNING_CACHE_PATH
            
            if last_reports != expected_reports or last_cache != expected_cache:
                _engine = None

        if _engine is None:
            _engine = TaskLearningEngine(reports_path=target_reports, cache_path=target_cache)
            _last_engine_reports_path = target_reports
            _last_engine_cache_path = target_cache
            
    return _engine


def suggest_module_for_group(group: str, available_modules: list[str],
                               exclude: Optional[set] = None) -> Optional[str]:
    """指定グループに最適なモジュールを推薦する。"""
    hub = LearningIntegrationHub(reports_path=_reports_path, cache_path=_cache_path)
    try:
        return hub.suggest_module_for_group(group, available_modules, exclude)
    except LearningIntegrationError as e:
        _log_global_exception("suggest_module_for_group", e)
        return None


def get_optimal_composition(batch_size: int) -> Optional[dict[str, int]]:
    """最適なバッチ配分を取得する。"""
    hub = LearningIntegrationHub(reports_path=_reports_path, cache_path=_cache_path)
    try:
        return hub.get_optimal_composition(batch_size)
    except LearningIntegrationError as e:
        _log_global_exception("get_optimal_composition", e)
        return None


def get_diminishing_modules() -> set[str]:
    """収穫逓減に入ったモジュールの集合を返す。"""
    hub = LearningIntegrationHub(reports_path=_reports_path, cache_path=_cache_path)
    try:
        return hub.get_diminishing_modules()
    except LearningIntegrationError as e:
        _log_global_exception("get_diminishing_modules", e)
        return set()


def refresh_and_cache() -> None:
    """学習エンジンをリフレッシュしてキャッシュを更新する。"""
    hub = LearningIntegrationHub(reports_path=_reports_path, cache_path=_cache_path)
    try:
        hub.refresh_and_cache()
    except LearningIntegrationError as e:
        _log_global_exception("refresh_and_cache", e)


