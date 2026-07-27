import os

import sys

import json

import pytest

from unittest.mock import MagicMock, patch, call

from pathlib import Path



# 動的パス解決

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))



from backend.agents.orchestration import learning_integration



@pytest.fixture(autouse=True)

def reset_learning_state():

    original_reports = learning_integration._reports_path

    original_cache = learning_integration._cache_path

    original_engine = learning_integration._engine

    

    learning_integration._reports_path = None

    learning_integration._cache_path = None

    learning_integration._engine = None

    

    yield

    

    learning_integration._reports_path = original_reports

    learning_integration._cache_path = original_cache

    learning_integration._engine = original_engine



def test_get_engine():

    with patch("backend.agents.orchestration.learning_integration.TaskLearningEngine") as mock_engine_cls:

        # シングルトンをリセット

        learning_integration._engine = None

        engine1 = learning_integration.get_engine()

        engine2 = learning_integration.get_engine()

        assert engine1 is engine2

        mock_engine_cls.assert_called_once()



def test_suggest_module_for_group():

    # 正常系

    mock_engine = MagicMock()

    mock_engine.suggest_module_for_group.return_value = "module_a"

    with patch("backend.agents.orchestration.learning_integration.get_engine", return_value=mock_engine):

        res = learning_integration.suggest_module_for_group("design", ["module_a", "module_b"], {"module_c"})

        assert res == "module_a"

        mock_engine.suggest_module_for_group.assert_called_once_with("design", ["module_a", "module_b"], {"module_c"})



    # 異常系: FileNotFoundError (OSErrorのサブクラス)

    mock_engine.suggest_module_for_group.side_effect = FileNotFoundError("cache missing")

    with patch("backend.agents.orchestration.learning_integration.get_engine", return_value=mock_engine), \
         patch("backend.agents.orchestration.learning_integration.logger") as mock_logger:

        res = learning_integration.suggest_module_for_group("design", ["module_a"])

        assert res is None

        mock_logger.warning.assert_called_once()



    # 異常系: KeyError

    mock_engine.suggest_module_for_group.side_effect = KeyError("key error")

    with patch("backend.agents.orchestration.learning_integration.get_engine", return_value=mock_engine), \
         patch("backend.agents.orchestration.learning_integration.logger") as mock_logger:

        res = learning_integration.suggest_module_for_group("design", ["module_a"])

        assert res is None

        mock_logger.warning.assert_called_once()



def test_get_optimal_composition():

    # 正常系

    mock_engine = MagicMock()

    mock_engine.suggest_optimal_batch_composition.return_value = {"design": 2, "bug_hunter": 3}

    with patch("backend.agents.orchestration.learning_integration.get_engine", return_value=mock_engine):

        res = learning_integration.get_optimal_composition(5)

        assert res == {"design": 2, "bug_hunter": 3}

        mock_engine.suggest_optimal_batch_composition.assert_called_once_with(5)



    # 異常系: FileNotFoundError

    mock_engine.suggest_optimal_batch_composition.side_effect = FileNotFoundError("cache missing")

    with patch("backend.agents.orchestration.learning_integration.get_engine", return_value=mock_engine), \
         patch("backend.agents.orchestration.learning_integration.logger") as mock_logger:

        res = learning_integration.get_optimal_composition(5)

        assert res is None

        mock_logger.warning.assert_called_once()



    # 異常系: ValueError

    mock_engine.suggest_optimal_batch_composition.side_effect = ValueError("value error")

    with patch("backend.agents.orchestration.learning_integration.get_engine", return_value=mock_engine), \
         patch("backend.agents.orchestration.learning_integration.logger") as mock_logger:

        res = learning_integration.get_optimal_composition(5)

        assert res is None

        mock_logger.warning.assert_called_once()



def test_get_diminishing_modules():

    # 正常系

    mock_engine = MagicMock()

    mock_engine.detect_diminishing_returns.return_value = [{"module": "module_a", "success_rate": 0.3}]

    with patch("backend.agents.orchestration.learning_integration.get_engine", return_value=mock_engine):

        res = learning_integration.get_diminishing_modules()

        assert res == {"module_a"}

        mock_engine.detect_diminishing_returns.assert_called_once_with(threshold=0.5)



    # 異常系: FileNotFoundError

    mock_engine.detect_diminishing_returns.side_effect = FileNotFoundError("cache missing")

    with patch("backend.agents.orchestration.learning_integration.get_engine", return_value=mock_engine), \
         patch("backend.agents.orchestration.learning_integration.logger") as mock_logger:

        res = learning_integration.get_diminishing_modules()

        assert res == set()

        mock_logger.warning.assert_called_once()



    # 異常系: AttributeError

    mock_engine.detect_diminishing_returns.side_effect = AttributeError("attribute error")

    with patch("backend.agents.orchestration.learning_integration.get_engine", return_value=mock_engine), \
         patch("backend.agents.orchestration.learning_integration.logger") as mock_logger:

        res = learning_integration.get_diminishing_modules()

        assert res == set()

        mock_logger.warning.assert_called_once()



def test_refresh_and_cache():

    # 正常系

    with patch("backend.agents.orchestration.learning_integration.TaskLearningEngine") as mock_engine_cls:

        mock_engine = MagicMock()

        mock_engine_cls.return_value = mock_engine

        learning_integration.refresh_and_cache()

        mock_engine.save_cache.assert_called_once()

        assert learning_integration._engine is mock_engine



    # 異常系: FileNotFoundError

    with patch("backend.agents.orchestration.learning_integration.TaskLearningEngine") as mock_engine_cls, \
         patch("backend.agents.orchestration.learning_integration.logger") as mock_logger:

        mock_engine_cls.side_effect = FileNotFoundError("file missing")

        learning_integration.refresh_and_cache()

        mock_logger.warning.assert_called_once()



    # 異常系: ValueError

    with patch("backend.agents.orchestration.learning_integration.TaskLearningEngine") as mock_engine_cls, \
         patch("backend.agents.orchestration.learning_integration.logger") as mock_logger:

        mock_engine_cls.side_effect = ValueError("value error")

        learning_integration.refresh_and_cache()

        mock_logger.warning.assert_called_once()



def test_set_paths():

    original_reports = learning_integration._reports_path

    original_cache = learning_integration._cache_path

    original_engine = learning_integration._engine



    try:

        dummy_reports = Path("dummy_reports.jsonl")

        dummy_cache = Path("dummy_cache.json")

        learning_integration._engine = MagicMock()

        

        learning_integration.set_paths(dummy_reports, dummy_cache)

        

        assert learning_integration._reports_path == dummy_reports

        assert learning_integration._cache_path == dummy_cache

        assert learning_integration._engine is None

    finally:

        learning_integration._reports_path = original_reports

        learning_integration._cache_path = original_cache

        learning_integration._engine = original_engine



def test_set_paths_invalid_type():

    with pytest.raises(TypeError, match="reports_path must be Path or None"):

        learning_integration.set_paths(reports_path="invalid_string_path")  # type: ignore



def test_set_paths_invalid_cache_path_type():

    with pytest.raises(TypeError, match="cache_path must be Path or None"):

        learning_integration.set_paths(cache_path="invalid_string_path")  # type: ignore



def test_suggest_module_for_group_invalid_type():

    with pytest.raises(TypeError, match="group must be str"):

        learning_integration.suggest_module_for_group(123, ["module_a"])  # type: ignore



def test_suggest_module_for_group_invalid_modules_type():

    with pytest.raises(TypeError, match="available_modules must be list"):

        learning_integration.suggest_module_for_group("design", "invalid_modules")  # type: ignore



def test_suggest_module_for_group_invalid_exclude_type():

    with pytest.raises(TypeError, match="exclude must be set or None"):

        learning_integration.suggest_module_for_group("design", ["module_a"], "invalid_exclude")  # type: ignore



def test_suggest_module_for_group_invalid_element_types():

    with pytest.raises(TypeError, match="all elements in available_modules must be str"):

        learning_integration.suggest_module_for_group("design", ["module_a", 123])  # type: ignore



    with pytest.raises(TypeError, match="all elements in exclude must be str"):

        learning_integration.suggest_module_for_group("design", ["module_a"], {"module_b", 456})  # type: ignore



def test_get_optimal_composition_invalid_type():

    with pytest.raises(TypeError, match="batch_size must be int"):

        learning_integration.get_optimal_composition("invalid_batch_size")  # type: ignore



def test_get_optimal_composition_negative_batch_size():

    with pytest.raises(ValueError, match="batch_size must be non-negative"):

        learning_integration.get_optimal_composition(-5)



# 追加テスト: 全例外クラス（KeyError, ValueError, TypeError, AttributeError, ZeroDivisionError）の挙動検証

@pytest.mark.parametrize("exception_class", [

    KeyError,

    ValueError,

    TypeError,

    AttributeError,

    ZeroDivisionError,

])

def test_suggest_module_for_group_specific_exceptions(exception_class):

    mock_engine = MagicMock()

    mock_engine.suggest_module_for_group.side_effect = exception_class("test specific exception")

    with patch("backend.agents.orchestration.learning_integration.get_engine", return_value=mock_engine), \
         patch("backend.agents.orchestration.learning_integration.logger") as mock_logger:

        res = learning_integration.suggest_module_for_group("design", ["module_a"])

        assert res is None

        mock_logger.warning.assert_called_once()

        assert "Engine logic error in suggest_module_for_group" in mock_logger.warning.call_args[0][0]



@pytest.mark.parametrize("exception_class", [

    KeyError,

    ValueError,

    TypeError,

    AttributeError,

    ZeroDivisionError,

])

def test_get_optimal_composition_specific_exceptions(exception_class):

    mock_engine = MagicMock()

    mock_engine.suggest_optimal_batch_composition.side_effect = exception_class("test specific exception")

    with patch("backend.agents.orchestration.learning_integration.get_engine", return_value=mock_engine), \
         patch("backend.agents.orchestration.learning_integration.logger") as mock_logger:

        res = learning_integration.get_optimal_composition(5)

        assert res is None

        mock_logger.warning.assert_called_once()

        assert "Engine logic error in get_optimal_composition" in mock_logger.warning.call_args[0][0]



@pytest.mark.parametrize("exception_class", [

    KeyError,

    ValueError,

    TypeError,

    AttributeError,

    ZeroDivisionError,

])

def test_get_diminishing_modules_specific_exceptions(exception_class):

    mock_engine = MagicMock()

    mock_engine.detect_diminishing_returns.side_effect = exception_class("test specific exception")

    with patch("backend.agents.orchestration.learning_integration.get_engine", return_value=mock_engine), \
         patch("backend.agents.orchestration.learning_integration.logger") as mock_logger:

        res = learning_integration.get_diminishing_modules()

        assert res == set()

        mock_logger.warning.assert_called_once()

        assert "Engine logic error in get_diminishing_modules" in mock_logger.warning.call_args[0][0]



@pytest.mark.parametrize("exception_class", [

    KeyError,

    ValueError,

    TypeError,

    AttributeError,

    ZeroDivisionError,

])

def test_refresh_and_cache_specific_exceptions(exception_class):

    with patch("backend.agents.orchestration.learning_integration.TaskLearningEngine") as mock_engine_cls, \
         patch("backend.agents.orchestration.learning_integration.logger") as mock_logger:

        mock_engine_cls.side_effect = exception_class("test specific exception")

        learning_integration.refresh_and_cache()

        mock_logger.warning.assert_called_once()

        assert "Engine logic error in refresh_and_cache" in mock_logger.warning.call_args[0][0]



# 追加テスト: 予期しない例外(Exception)のハンドリング検証

def test_suggest_module_for_group_unexpected_exception():

    mock_engine = MagicMock()

    mock_engine.suggest_module_for_group.side_effect = Exception("unexpected fatal error")

    with patch("backend.agents.orchestration.learning_integration.get_engine", return_value=mock_engine), \
         patch("backend.agents.orchestration.learning_integration.logger") as mock_logger:

        res = learning_integration.suggest_module_for_group("design", ["module_a"])

        assert res is None

        mock_logger.error.assert_called_once()

        assert "Unexpected exception in suggest_module_for_group" in mock_logger.error.call_args[0][0]



def test_get_optimal_composition_unexpected_exception():

    mock_engine = MagicMock()

    mock_engine.suggest_optimal_batch_composition.side_effect = Exception("unexpected fatal error")

    with patch("backend.agents.orchestration.learning_integration.get_engine", return_value=mock_engine), \
         patch("backend.agents.orchestration.learning_integration.logger") as mock_logger:

        res = learning_integration.get_optimal_composition(5)

        assert res is None

        mock_logger.error.assert_called_once()

        assert "Unexpected exception in get_optimal_composition" in mock_logger.error.call_args[0][0]



def test_get_diminishing_modules_unexpected_exception():

    mock_engine = MagicMock()

    mock_engine.detect_diminishing_returns.side_effect = Exception("unexpected fatal error")

    with patch("backend.agents.orchestration.learning_integration.get_engine", return_value=mock_engine), \
         patch("backend.agents.orchestration.learning_integration.logger") as mock_logger:

        res = learning_integration.get_diminishing_modules()

        assert res == set()

        mock_logger.error.assert_called_once()

        assert "Unexpected exception in get_diminishing_modules" in mock_logger.error.call_args[0][0]



def test_refresh_and_cache_unexpected_exception():

    with patch("backend.agents.orchestration.learning_integration.TaskLearningEngine") as mock_engine_cls, \
         patch("backend.agents.orchestration.learning_integration.logger") as mock_logger:

        mock_engine_cls.side_effect = Exception("unexpected fatal error")

        learning_integration.refresh_and_cache()

        mock_logger.error.assert_called_once()

        assert "Unexpected exception in refresh_and_cache" in mock_logger.error.call_args[0][0]


# ==========================================
# 新規設計の LearningIntegrationHub テスト
# ==========================================

from backend.agents.orchestration.learning_integration import (
    LearningIntegrationHub,
    LearningIntegrationError,
    EngineInitializationError,
    EngineExecutionError,
)

def test_hub_suggest_module_for_group_success():
    mock_engine = MagicMock()
    mock_engine.suggest_module_for_group.return_value = "module_x"
    with patch("backend.agents.orchestration.learning_integration.get_engine", return_value=mock_engine):
        hub = LearningIntegrationHub()
        res = hub.suggest_module_for_group("design", ["module_x"])
        assert res == "module_x"
        mock_engine.suggest_module_for_group.assert_called_once_with("design", ["module_x"], None)

def test_hub_suggest_module_for_group_type_errors():
    hub = LearningIntegrationHub()
    with pytest.raises(TypeError, match="group must be str"):
        hub.suggest_module_for_group(123, ["module_x"])  # type: ignore

    with pytest.raises(TypeError, match="available_modules must be list"):
        hub.suggest_module_for_group("design", "invalid")  # type: ignore

def test_hub_execution_error_on_logic_exception():
    mock_engine = MagicMock()
    mock_engine.suggest_module_for_group.side_effect = KeyError("missing key")
    with patch("backend.agents.orchestration.learning_integration.get_engine", return_value=mock_engine):
        hub = LearningIntegrationHub()
        with pytest.raises(EngineExecutionError) as exc_info:
            hub.suggest_module_for_group("design", ["module_x"])
        assert isinstance(exc_info.value.__cause__, KeyError)

def test_hub_initialization_error_on_engine_failure():
    with patch("backend.agents.orchestration.learning_integration.get_engine", side_effect=Exception("init crash")):
        hub = LearningIntegrationHub()
        with pytest.raises(EngineInitializationError) as exc_info:
            hub.suggest_module_for_group("design", ["module_x"])
        assert "TaskLearningEngine initialization failed" in str(exc_info.value)


# ==========================================
# 追加の例外伝播 & スレッドセーフティ検証テスト
# ==========================================

def test_hub_get_optimal_composition_initialization_error():
    with patch("backend.agents.orchestration.learning_integration.get_engine", side_effect=EngineInitializationError("init failed")):
        hub = LearningIntegrationHub()
        with pytest.raises(EngineInitializationError):
            hub.get_optimal_composition(5)

def test_hub_get_diminishing_modules_initialization_error():
    with patch("backend.agents.orchestration.learning_integration.get_engine", side_effect=EngineInitializationError("init failed")):
        hub = LearningIntegrationHub()
        with pytest.raises(EngineInitializationError):
            hub.get_diminishing_modules()

def test_hub_refresh_and_cache_initialization_error():
    with patch("backend.agents.orchestration.learning_integration.TaskLearningEngine", side_effect=EngineInitializationError("init failed")):
        hub = LearningIntegrationHub()
        with pytest.raises(EngineInitializationError):
            hub.refresh_and_cache()

def test_hub_get_engine_thread_safety():
    import threading
    import time
    
    instantiation_count = 0
    def slow_init(*args, **kwargs):
        nonlocal instantiation_count
        time.sleep(0.05)
        instantiation_count += 1
        return MagicMock()

    with patch("backend.agents.orchestration.learning_integration.TaskLearningEngine", side_effect=slow_init):
        # シングルトンをクリア
        learning_integration._engine = None
        
        engines = []
        threads = []
        def worker():
            engines.append(learning_integration.get_engine())
            
        for _ in range(5):
            t = threading.Thread(target=worker)
            threads.append(t)
            t.start()
            
        for t in threads:
            t.join()
            
        assert len(engines) == 5
        first_engine = engines[0]
        for eng in engines:
            assert eng is first_engine
            
        assert instantiation_count == 1


def test_hub_custom_paths_propagation():
    """LearningIntegrationHub にカスタムパスを渡した際、適切に TaskLearningEngine に伝播すること、
    およびパスが変更された場合にシングルトンが再生成されることを検証する"""
    
    # グローバルなシングルトンをクリア
    learning_integration._engine = None
    learning_integration._last_engine_reports_path = None
    learning_integration._last_engine_cache_path = None
    
    path_reports_1 = Path("custom_reports_1.jsonl")
    path_cache_1 = Path("custom_cache_1.json")
    
    hub1 = LearningIntegrationHub(reports_path=path_reports_1, cache_path=path_cache_1)
    
    with patch("backend.agents.orchestration.learning_integration.TaskLearningEngine") as mock_engine_cls:
        mock_instance = MagicMock()
        mock_instance.reports_path = path_reports_1
        mock_instance.cache_path = path_cache_1
        mock_engine_cls.return_value = mock_instance
        
        # 1回目の呼び出し
        engine1 = hub1.get_engine()
        mock_engine_cls.assert_called_once_with(reports_path=path_reports_1, cache_path=path_cache_1)
        
        # 同じパスで2回目の呼び出し（シングルトンなので TaskLearningEngine 自体は再度呼ばれない）
        engine2 = hub1.get_engine()
        assert engine1 is engine2
        assert mock_engine_cls.call_count == 1
        
        # 異なるパスで呼び出し（再作成されるべき）
        path_reports_2 = Path("custom_reports_2.jsonl")
        path_cache_2 = Path("custom_cache_2.json")
        hub2 = LearningIntegrationHub(reports_path=path_reports_2, cache_path=path_cache_2)
        
        mock_instance_2 = MagicMock()
        mock_instance_2.reports_path = path_reports_2
        mock_instance_2.cache_path = path_cache_2
        mock_engine_cls.return_value = mock_instance_2
        
        engine3 = hub2.get_engine()
        assert engine3 is not engine1
        assert mock_engine_cls.call_count == 2
        mock_engine_cls.assert_called_with(reports_path=path_reports_2, cache_path=path_cache_2)

def test_hub_get_engine_thread_safety_with_set_paths():
    """get_engine と set_paths が同時に呼ばれてもスレッドセーフであることを検証"""
    import threading
    import time
    
    # グローバルな状態をクリア
    learning_integration._engine = None
    learning_integration._reports_path = None
    learning_integration._cache_path = None
    
    stop_event = threading.Event()
    
    def path_updater():
        i = 0
        while not stop_event.is_set():
            p_rep = Path(f"dummy_rep_{i}.jsonl")
            p_cac = Path(f"dummy_cac_{i}.json")
            learning_integration.set_paths(p_rep, p_cac)
            i += 1
            time.sleep(0.005)
            
    def engine_reader():
        while not stop_event.is_set():
            try:
                # 毎回異なるパスに対して get_engine される可能性があるが
                # 競合によるクラッシュや破損が発生しないことを検証
                learning_integration.get_engine()
            except Exception:
                # どんな例外もスレッド競合によるバグ以外は許容
                pass
            time.sleep(0.005)
            
    t1 = threading.Thread(target=path_updater)
    t2 = threading.Thread(target=engine_reader)
    
    t1.start()
    t2.start()
    
    time.sleep(0.5)
    stop_event.set()
    
    t1.join()
    t2.join()
    
    # 最後にクリーンアップして終了することを確認
    learning_integration.set_paths(None, None)


def test_hub_init_invalid_paths_type():
    """LearningIntegrationHubの初期化時に不正なパス型が渡された場合にTypeErrorが発生することを確認"""
    with pytest.raises(TypeError, match="reports_path must be Path or None"):
        LearningIntegrationHub(reports_path="invalid_path")  # type: ignore

    with pytest.raises(TypeError, match="cache_path must be Path or None"):
        LearningIntegrationHub(cache_path="invalid_path")  # type: ignore


def test_handle_engine_exceptions_unexpected_error_details():
    """_handle_engine_exceptionsが予期せぬ例外をキャッチした際、例外クラス名がメッセージに含まれることを確認"""
    from backend.agents.orchestration.learning_integration import _handle_engine_exceptions, EngineExecutionError

    class CustomTestException(Exception):
        pass

    with pytest.raises(EngineExecutionError) as exc_info:
        with _handle_engine_exceptions("test_action"):
            raise CustomTestException("fatal crash")

    assert "CustomTestException" in str(exc_info.value)
    assert "fatal crash" in str(exc_info.value)


def test_hub_refresh_and_cache_singleton_retention():
    """refresh_and_cache()を実行した後、get_engine()が再生成を行わずに同じインスタンスを返すことを検証"""
    # グローバルシングルトンをクリア
    learning_integration._engine = None
    learning_integration._last_engine_reports_path = None
    learning_integration._last_engine_cache_path = None

    path_reports = Path("custom_reports_for_refresh.jsonl")
    path_cache = Path("custom_cache_for_refresh.json")

    hub = LearningIntegrationHub(reports_path=path_reports, cache_path=path_cache)

    with patch("backend.agents.orchestration.learning_integration.TaskLearningEngine") as mock_engine_cls:
        mock_instance = MagicMock()
        mock_engine_cls.return_value = mock_instance

        # 1. refresh_and_cache を実行する
        hub.refresh_and_cache()
        mock_engine_cls.assert_called_once_with(reports_path=path_reports, cache_path=path_cache)
        mock_instance.save_cache.assert_called_once()

        # 2. get_engine を呼び出す（シングルトンが維持されて再生成されないこと）
        engine = hub.get_engine()
        assert engine is mock_instance
        # 呼び出し回数は1回のまま（get_engine時に再生成されない）
        assert mock_engine_cls.call_count == 1


def test_hub_refresh_and_cache_save_failure_retains_old_engine():
    """refresh_and_cacheのキャッシュ保存失敗時に、古いエンジンインスタンスが維持されることを検証"""
    mock_old_engine = MagicMock()
    learning_integration._engine = mock_old_engine
    learning_integration._last_engine_reports_path = Path("old_reports")
    learning_integration._last_engine_cache_path = Path("old_cache")

    hub = learning_integration.LearningIntegrationHub(
        reports_path=Path("new_reports"),
        cache_path=Path("new_cache")
    )

    mock_new_engine = MagicMock()
    mock_new_engine.save_cache.side_effect = RuntimeError("Save failed")

    with patch("backend.agents.orchestration.learning_integration.TaskLearningEngine", return_value=mock_new_engine):
        with pytest.raises(learning_integration.EngineExecutionError):
            hub.refresh_and_cache()

    # save_cache が失敗したため、グローバルな _engine は元の mock_old_engine のままであるべき
    assert learning_integration._engine is mock_old_engine
    assert learning_integration._last_engine_reports_path == Path("old_reports")
    assert learning_integration._last_engine_cache_path == Path("old_cache")


def test_hub_refresh_and_cache_lock_localization_non_blocking():
    """refresh_and_cache が save_cache() の実行中（時間のかかるI/O）であっても、
    他のスレッドが get_engine() を呼び出した際にロックでブロックされないことを検証する。"""
    import threading
    import time

    # グローバルな状態を初期化
    mock_old_engine = MagicMock()
    learning_integration._reports_path = Path("old_reports")
    learning_integration._cache_path = Path("old_cache")
    learning_integration._engine = mock_old_engine
    learning_integration._last_engine_reports_path = Path("old_reports")
    learning_integration._last_engine_cache_path = Path("old_cache")

    hub = learning_integration.LearningIntegrationHub(
        reports_path=Path("old_reports"),
        cache_path=Path("old_cache")
    )

    save_cache_started = threading.Event()
    save_cache_hold = threading.Event()
    get_engine_completed = threading.Event()
    retrieved_engine = []

    def slow_save_cache():
        save_cache_started.set()
        # 他のスレッドが get_engine を呼び出すまでスリープ（ブロック状態を模倣）
        save_cache_hold.wait(timeout=2.0)

    mock_new_engine = MagicMock()
    mock_new_engine.save_cache.side_effect = slow_save_cache

    def run_refresh():
        hub.refresh_and_cache()

    with patch("backend.agents.orchestration.learning_integration.TaskLearningEngine", return_value=mock_new_engine):
        # スレッドAで refresh_and_cache を実行
        t_refresh = threading.Thread(target=run_refresh)
        t_refresh.start()

        # スレッドAが save_cache() に入るのを待つ
        save_cache_started.wait(timeout=1.0)

        # スレッドBで get_engine() を実行
        def run_get_engine():
            retrieved_engine.append(learning_integration.get_engine())
            get_engine_completed.set()

        t_get = threading.Thread(target=run_get_engine)
        t_get.start()

        # get_engine が即座に（save_cache_hold がセットされる前、つまり refresh_and_cache の I/O 中に）完了することを確認する
        completed = get_engine_completed.wait(timeout=0.5)
        # 即座に完了したため、古いエンジンを取得できているはず
        assert completed is True
        assert retrieved_engine[0] is mock_old_engine

        # スレッドAの処理を進めて完了させる
        save_cache_hold.set()
        t_refresh.join(timeout=1.0)
        t_get.join(timeout=1.0)

    # 最終的に _engine は mock_new_engine に差し替わっているはず
    assert learning_integration._engine is mock_new_engine


def test_task_learning_engine_save_cache_raises_exception():
    """TaskLearningEngine の save_cache が書き込み失敗時に例外を投げることを検証する"""
    from backend.agents.orchestration.task_learning_engine import TaskLearningEngine
    
    # 存在しない（書き込み不可能な）パスを設定して save_cache が例外を投げるかテストする
    invalid_path = Path("/invalid_dir_does_not_exist_123456/cache.json")
    engine = TaskLearningEngine(cache_path=invalid_path)
    
    # save_cache() は例外を投げるはず（従来は握り潰して logger.warning を出すだけだった）
    with pytest.raises(Exception):
        engine.save_cache()

