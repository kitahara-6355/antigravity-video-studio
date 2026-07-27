import pytest
import logging
from agents.orchestration.wave_scheduler import WaveScheduler

def test_wave_scheduler_normal():
    # verifies: REQ-WAVE-01
    # 正常系: デフォルトサイズでの分割
    scheduler = WaveScheduler(default_wave_size=10)
    tasks = [{"id": i} for i in range(25)]
    
    waves = scheduler.schedule_waves(tasks)
    assert len(waves) == 3
    assert len(waves[0]) == 10
    assert len(waves[1]) == 10
    assert len(waves[2]) == 5
    assert waves[0][0]["id"] == 0
    assert waves[2][-1]["id"] == 24

def test_wave_scheduler_override():
    # 正常系: wave_size によるオーバーライド
    scheduler = WaveScheduler(default_wave_size=10)
    tasks = [{"id": i} for i in range(25)]
    
    waves = scheduler.schedule_waves(tasks, wave_size=5)
    assert len(waves) == 5
    assert all(len(w) == 5 for w in waves)

def test_wave_scheduler_empty_tasks():
    # 正常系: タスクが空の場合
    scheduler = WaveScheduler()
    waves = scheduler.schedule_waves([])
    assert waves == []

def test_wave_scheduler_invalid_tasks():
    # 異常系: tasks が None やリスト以外
    scheduler = WaveScheduler()
    
    # None の場合
    waves = scheduler.schedule_waves(None)
    assert waves == []
    
    # リスト以外（辞書）の場合
    waves = scheduler.schedule_waves({"id": 1})
    assert waves == []
    
    # リスト以外（文字列）の場合
    waves = scheduler.schedule_waves("not a list")
    assert waves == []

def test_wave_scheduler_invalid_wave_size():
    # 異常系: wave_size が不正な値
    scheduler = WaveScheduler(default_wave_size=10)
    tasks = [{"id": i} for i in range(15)]
    
    # 0 の場合 -> default_wave_size にフォールバック
    with pytest.warns(UserWarning, match="must be a positive integer"):
        waves = scheduler.schedule_waves(tasks, wave_size=0)
    assert len(waves) == 2
    assert len(waves[0]) == 10
    
    # 負の数の場合 -> default_wave_size にフォールバック
    with pytest.warns(UserWarning, match="must be a positive integer"):
        waves = scheduler.schedule_waves(tasks, wave_size=-5)
    assert len(waves) == 2
    assert len(waves[0]) == 10
    
    # 文字列（非整数）の場合 -> default_wave_size にフォールバック
    with pytest.warns(UserWarning, match="Invalid wave_size"):
        waves = scheduler.schedule_waves(tasks, wave_size="invalid")
    assert len(waves) == 2
    assert len(waves[0]) == 10
    
    # 浮動小数点数の場合 -> 整数に変換されて動作
    with pytest.warns(UserWarning, match="converted to integer"):
        waves = scheduler.schedule_waves(tasks, wave_size=5.5)
    assert len(waves) == 3
    assert len(waves[0]) == 5

def test_wave_scheduler_invalid_default_wave_size():
    # 異常系: default_wave_size が不正な値
    
    # 0 の場合 -> 30 にフォールバック
    with pytest.warns(UserWarning, match="must be a positive integer"):
        scheduler = WaveScheduler(default_wave_size=0)
    assert scheduler.default_wave_size == 30
    
    # 負の数の場合 -> 30 にフォールバック
    with pytest.warns(UserWarning, match="must be a positive integer"):
        scheduler = WaveScheduler(default_wave_size=-10)
    assert scheduler.default_wave_size == 30
    
    # 非整数文字列の場合 -> 30 にフォールバック
    with pytest.warns(UserWarning, match="Invalid wave_size"):
        scheduler = WaveScheduler(default_wave_size="invalid")
    assert scheduler.default_wave_size == 30
    
    # None の場合 -> 30 にフォールバック（Noneガードにより警告なしでフォールバックされる）
    scheduler = WaveScheduler(default_wave_size=None)
    assert scheduler.default_wave_size == 30


def test_wave_scheduler_overflow():
    # 異常系: OverflowError が発生するような超巨大数を指定した場合
    # float('inf') を int() しようとすると OverflowError (または ValueError) になる
    with pytest.warns(UserWarning, match="Invalid wave_size"):
        scheduler = WaveScheduler(default_wave_size=float('inf'))
    assert scheduler.default_wave_size == 30
    
    # schedule_waves での overflow
    scheduler2 = WaveScheduler(default_wave_size=10)
    tasks = [{"id": i} for i in range(15)]
    with pytest.warns(UserWarning, match="Invalid wave_size"):
        waves = scheduler2.schedule_waves(tasks, wave_size=float('inf'))
    assert len(waves) == 2  # default_wave_size=10 にフォールバックされるはず

def test_wave_scheduler_hard_guard_on_zero_or_negative_size():
    # 異常系: インスタンス変数を直接不正値に書き換えて実行した場合の最終防衛
    scheduler = WaveScheduler(default_wave_size=10)
    tasks = [{"id": i} for i in range(15)]
    
    # 意図的に 0 に書き換える
    scheduler.default_wave_size = 0
    with pytest.warns(UserWarning, match="Execution wave size 0 is invalid"):
        waves = scheduler.schedule_waves(tasks)
    # 最終防衛で 30 にフォールバックするため、1ウェーブになるはず
    assert len(waves) == 1
    assert len(waves[0]) == 15

    # 意図的に 負の数 に書き換える
    scheduler.default_wave_size = -5
    with pytest.warns(UserWarning, match="Execution wave size -5 is invalid"):
        waves = scheduler.schedule_waves(tasks)
    assert len(waves) == 1
    assert len(waves[0]) == 15

def test_wave_scheduler_invalid_task_elements():
    # 異常系: タスクリスト内に非辞書データが混入している場合
    scheduler = WaveScheduler(default_wave_size=5)
    tasks = [
        {"id": 1},
        "invalid_task_string",
        {"id": 2},
        12345,
        {"id": 3}
    ]
    waves = scheduler.schedule_waves(tasks)
    # 非辞書データは無視されるため、有効なタスク 3 個がウェーブとしてまとめられる
    assert len(waves) == 1
    assert len(waves[0]) == 3
    assert waves[0][0]["id"] == 1
    assert waves[0][1]["id"] == 2
    assert waves[0][2]["id"] == 3


from collections import UserDict

def test_wave_scheduler_iterable_inputs():
    # 正常系: ジェネレータが渡された場合
    scheduler = WaveScheduler(default_wave_size=5)
    def task_generator():
        for i in range(12):
            yield {"id": i}
            
    waves = scheduler.schedule_waves(task_generator())
    assert len(waves) == 3
    assert len(waves[0]) == 5
    assert len(waves[1]) == 5
    assert len(waves[2]) == 2
    assert waves[0][0]["id"] == 0
    assert waves[2][-1]["id"] == 11

    # 正常系: タプルが渡された場合
    tasks_tuple = ({"id": 100}, {"id": 101}, {"id": 102})
    waves = scheduler.schedule_waves(tasks_tuple)
    assert len(waves) == 1
    assert len(waves[0]) == 3
    assert waves[0][0]["id"] == 100

def test_wave_scheduler_mapping_tasks():
    # 正常系: UserDict を含むカスタムマッピングオブジェクトが渡された場合
    scheduler = WaveScheduler(default_wave_size=3)
    task1 = UserDict(id=1, name="task1")
    task2 = UserDict(id=2, name="task2")
    tasks = [task1, task2]
    
    waves = scheduler.schedule_waves(tasks)
    assert len(waves) == 1
    assert len(waves[0]) == 2
    assert waves[0][0]["id"] == 1
    assert waves[0][1]["id"] == 2

def test_wave_scheduler_invalid_iterable_types():
    # 異常系: 文字列、辞書、バイト列がタスクリストとして直接渡された場合、イテラブルだがエラーとして拒否されること
    scheduler = WaveScheduler()
    
    # 文字列が渡された場合
    assert scheduler.schedule_waves("not tasks string") == []
    
    # 辞書自体が渡された場合 (イテラブルなのでキーのリストと誤認されがちだが、Mappingなので拒否される)
    assert scheduler.schedule_waves({"id": 1}) == []
    
    # バイト列が渡された場合
    assert scheduler.schedule_waves(b"bytes_data") == []

def test_wave_scheduler_boolean_wave_size():
    # 異常系: wave_size に bool が渡された場合
    scheduler = WaveScheduler(default_wave_size=10)
    tasks = [{"id": i} for i in range(15)]
    
    # default_wave_size に bool を指定した場合
    with pytest.warns(UserWarning, match="cannot be boolean"):
        scheduler_bool = WaveScheduler(default_wave_size=True)
    assert scheduler_bool.default_wave_size == 30 # fallback
    
    # schedule_waves で wave_size に bool を指定した場合
    with pytest.warns(UserWarning, match="cannot be boolean"):
        waves = scheduler.schedule_waves(tasks, wave_size=True)
    assert len(waves) == 2
    assert len(waves[0]) == 10 # fallback to default_wave_size

def test_wave_scheduler_strict_type_guard():
    # 異常系: size が bool に書き換えられた場合の最終防衛
    scheduler = WaveScheduler(default_wave_size=10)
    tasks = [{"id": i} for i in range(15)]
    
    # 意図的に True (bool) に書き換える -> 最終防衛で 30 にフォールバックするため、1ウェーブになるはず
    scheduler.default_wave_size = True
    with pytest.warns(UserWarning, match="Execution wave size True is invalid"):
        waves = scheduler.schedule_waves(tasks)
    assert len(waves) == 1
    assert len(waves[0]) == 15

def test_wave_scheduler_negative_string_wave_size():
    # 異常系: wave_size に 0 や負の数を含む文字列が渡された場合 -> default_wave_size にフォールバック
    scheduler = WaveScheduler(default_wave_size=10)
    tasks = [{"id": i} for i in range(15)]
    
    with pytest.warns(UserWarning, match="must be a positive integer"):
        waves = scheduler.schedule_waves(tasks, wave_size="0")
    assert len(waves) == 2
    assert len(waves[0]) == 10
    
    with pytest.warns(UserWarning, match="must be a positive integer"):
        waves = scheduler.schedule_waves(tasks, wave_size="-5")
    assert len(waves) == 2
    assert len(waves[0]) == 10


def test_wave_scheduler_import_and_instantiation():
    # インポートと初期化が警告なしで行えることを検証
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        scheduler = WaveScheduler()
        assert scheduler is not None
        assert scheduler.default_wave_size == 30


def test_wave_scheduler_custom_int_subclass():
    # 正常系: int を継承したカスタムクラスを wave_size として渡した場合に
    # 正しくその値が wave_size として適用され、30 にフォールバックしないこと
    class CustomInt(int):
        pass

    custom_size = CustomInt(5)
    scheduler = WaveScheduler(default_wave_size=custom_size)
    assert scheduler.default_wave_size == 5

    tasks = [{"id": i} for i in range(15)]
    waves = scheduler.schedule_waves(tasks)
    assert len(waves) == 3
    assert all(len(w) == 5 for w in waves)

    # schedule_waves メソッドの引数 wave_size にカスタム int サブクラスを渡した場合
    scheduler2 = WaveScheduler(default_wave_size=10)
    waves2 = scheduler2.schedule_waves(tasks, wave_size=CustomInt(3))
    assert len(waves2) == 5
    assert all(len(w) == 3 for w in waves2)


def test_wave_scheduler_type_annotations():
    # 正常系: None や Any を渡しても型警告を誘発させずに正常動作すること
    # (型チェッカーでの検証を意図したランタイムテスト)
    scheduler = WaveScheduler(default_wave_size=None)
    assert scheduler.default_wave_size == 30

    waves = scheduler.schedule_waves(None, wave_size=None)
    assert waves == []


def test_wave_scheduler_warning_behavior():
    import warnings
    import pytest
    
    # 1. 整数と等価な float (e.g. 30.0) を指定した場合、UserWarning が発生しないこと
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        scheduler1 = WaveScheduler(default_wave_size=30.0)
        assert scheduler1.default_wave_size == 30
        
        waves1 = scheduler1.schedule_waves([{"id": 1}], wave_size=10.0)
        assert len(waves1) == 1

    # 2. 整数と等価でない float (e.g. 10.5) を指定した場合、UserWarning が発生すること
    with pytest.warns(UserWarning, match="was converted to integer"):
        scheduler2 = WaveScheduler(default_wave_size=10.5)
        assert scheduler2.default_wave_size == 10

    with pytest.warns(UserWarning, match="was converted to integer"):
        scheduler3 = WaveScheduler(default_wave_size=10)
        scheduler3.schedule_waves([{"id": 1}], wave_size=5.5)

    # 3. 不正な型や不正な値（bool, 0, 負数, 非数値）が指定された場合、UserWarning が発生すること
    with pytest.warns(UserWarning, match="cannot be boolean"):
        WaveScheduler(default_wave_size=True)

    with pytest.warns(UserWarning, match="must be a positive integer"):
        WaveScheduler(default_wave_size=0)

    with pytest.warns(UserWarning, match="must be a positive integer"):
        WaveScheduler(default_wave_size=-5)

    with pytest.warns(UserWarning, match="Invalid wave_size"):
        WaveScheduler(default_wave_size="invalid_string")


def test_wave_scheduler_none_wave_size():
    # 正常系: wave_size や default_wave_size に None を指定した場合に
    # 警告を一切発生させず、正しくフォールバックされることを検証
    import warnings
    
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        
        # default_wave_size=None の場合
        scheduler = WaveScheduler(default_wave_size=None)
        assert scheduler.default_wave_size == 30
        
        # schedule_waves で wave_size=None の場合
        tasks = [{"id": i} for i in range(5)]
        waves = scheduler.schedule_waves(tasks, wave_size=None)
        assert len(waves) == 1
        assert len(waves[0]) == 5


def test_wave_scheduler_unexpected_exception_in_int_conversion():
    # 異常系: int 変換時に予期せぬ例外を投げるオブジェクト
    class BadInt:
        def __int__(self):
            raise ZeroDivisionError("Custom zero division error inside __int__")

    scheduler = WaveScheduler(default_wave_size=10)
    tasks = [{"id": i} for i in range(15)]
    
    with pytest.warns(UserWarning, match="Unexpected error during wave_size"):
        waves = scheduler.schedule_waves(tasks, wave_size=BadInt())
        
    # fallback to default_wave_size=10
    assert len(waves) == 2
    assert len(waves[0]) == 10


def test_wave_scheduler_exception_during_task_iteration():
    # 異常系: イテレーション中に例外が発生するジェネレータ
    def broken_generator():
        yield {"id": 1}
        yield {"id": 2}
        raise RuntimeError("Something went wrong during iteration")
        yield {"id": 3}

    scheduler = WaveScheduler(default_wave_size=10)
    
    # 途中で例外が発生しても、それまでに得られたタスク (id=1, 2) が正しくスケジュールされ、クラッシュしないこと
    with pytest.warns(RuntimeWarning, match="Exception raised during task iteration"):
        waves = scheduler.schedule_waves(broken_generator())
    assert len(waves) == 1
    assert len(waves[0]) == 2
    assert waves[0][0]["id"] == 1
    assert waves[0][1]["id"] == 2


def test_wave_scheduler_unexpected_exception_in_int_conversion_logging(caplog):
    # 異常系: int 変換時の予期せぬ例外におけるエラーロギングの検証
    class BadInt:
        def __int__(self):
            raise ZeroDivisionError("Custom zero division error inside __int__")

    scheduler = WaveScheduler(default_wave_size=10)
    tasks = [{"id": i} for i in range(15)]
    
    import logging
    with caplog.at_level(logging.ERROR):
        with pytest.warns(UserWarning, match="Unexpected error during wave_size"):
            waves = scheduler.schedule_waves(tasks, wave_size=BadInt())
            
    # logger.error が出力され、ZeroDivisionError などのトレース情報が含まれることを検証
    assert len(caplog.records) > 0
    error_record = next(r for r in caplog.records if r.levelname == "ERROR")
    assert "Unexpected error during wave_size" in error_record.message
    assert error_record.exc_info is not None
    assert error_record.exc_info[0] is ZeroDivisionError

def test_wave_scheduler_exception_during_task_iteration_warning_and_logging(caplog):
    # 異常系: イテレーション中に例外が発生するジェネレータで、RuntimeWarningとエラーログ（スタックトレース含む）の検証
    def broken_generator():
        yield {"id": 1}
        yield {"id": 2}
        raise RuntimeError("Something went wrong during iteration")

    scheduler = WaveScheduler(default_wave_size=10)
    
    import logging
    with caplog.at_level(logging.ERROR):
        with pytest.warns(RuntimeWarning, match="Exception raised during task iteration"):
            waves = scheduler.schedule_waves(broken_generator())
            
    # タスクは 1, 2 だけがスケジュールされる
    assert len(waves) == 1
    assert len(waves[0]) == 2
    
    # logger.error が出力され、RuntimeError のトレース情報が含まれることを検証
    assert len(caplog.records) > 0
    error_record = next(r for r in caplog.records if r.levelname == "ERROR")
    assert "Exception raised during task iteration" in error_record.message
    assert error_record.exc_info is not None
    assert error_record.exc_info[0] is RuntimeError


def test_wave_scheduler_final_guard_warning():
    # 最終防衛ガードの検証：size を直接 0 に書き換えた場合に、警告が発生すること
    scheduler = WaveScheduler(default_wave_size=10)
    scheduler.default_wave_size = 0
    
    with pytest.warns(UserWarning, match="Execution wave size 0 is invalid"):
        waves = scheduler.schedule_waves([{"id": 1}])
    assert len(waves) == 1

def test_wave_scheduler_exception_iteration_propagation():
    # イテレーション中に NameError が発生した場合、安全にキャッチされ、それまでに得られたタスクが返され、警告が発生すること
    def name_error_generator():
        yield {"id": 1}
        # NameError を発生させる
        print(undefined_variable_name_error)
        yield {"id": 2}
        
    scheduler = WaveScheduler(default_wave_size=5)
    with pytest.warns(RuntimeWarning, match="Exception raised during task iteration"):
        waves = scheduler.schedule_waves(name_error_generator())
    # 最初の一つのタスクだけがスケジュールされる
    assert len(waves) == 1
    assert len(waves[0]) == 1
    assert waves[0][0]["id"] == 1

def test_wave_scheduler_unexpected_exception_propagation():
    # wave_size 変換中に NameError が発生した場合、安全にキャッチされ、UserWarning が発生し、デフォルト値にフォールバックすること
    class NameErrorInt:
        def __int__(self):
            # NameError を発生させる
            print(undefined_variable_name_error)
            return 5
            
    scheduler = WaveScheduler(default_wave_size=10)
    with pytest.warns(UserWarning, match="Unexpected error during wave_size"):
        waves = scheduler.schedule_waves([{"id": 1}], wave_size=NameErrorInt())
    # default_wave_size=10 にフォールバックされる
    assert len(waves) == 1

def test_wave_scheduler_warning_stacklevel():
    # 警告の stacklevel が正しく呼び出し元（このテストコード）を指していることを検証
    import warnings
    
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        # 不正な wave_size を指定して警告を誘発
        WaveScheduler(default_wave_size=0)
        
        assert len(w) == 1
        # 警告の発生箇所が、このテストファイル（test_wave_scheduler.py）であることを検証
        assert "test_wave_scheduler.py" in w[0].filename

def test_wave_scheduler_keyboard_interrupt_propagation():
    # 異常系: wave_size 変換中に KeyboardInterrupt や SystemExit が発生した場合、
    # 揉み消されずに raise されること
    class KeyboardInterruptInt:
        def __int__(self):
            raise KeyboardInterrupt("Simulated user interrupt")

    scheduler = WaveScheduler(default_wave_size=10)
    with pytest.raises(KeyboardInterrupt):
        scheduler.schedule_waves([{"id": 1}], wave_size=KeyboardInterruptInt())


def test_wave_scheduler_task_iteration_keyboard_interrupt_propagation():
    # 異常系: タスクイテレーション中に KeyboardInterrupt が発生した場合、
    # 揉み消されずに raise されること
    def keyboard_interrupt_generator():
        yield {"id": 1}
        raise KeyboardInterrupt("Simulated user interrupt during iteration")

    scheduler = WaveScheduler(default_wave_size=5)
    with pytest.raises(KeyboardInterrupt):
        scheduler.schedule_waves(keyboard_interrupt_generator())


def test_wave_scheduler_float_nonpositive_wave_size():
    # 異常系: wave_size に整数と等価な0以下の float (0.0, -5.0) が指定された場合
    scheduler = WaveScheduler(default_wave_size=10)
    tasks = [{"id": i} for i in range(15)]

    # 0.0 の場合 -> default_wave_size にフォールバック
    with pytest.warns(UserWarning, match="must be a positive integer"):
        waves = scheduler.schedule_waves(tasks, wave_size=0.0)
    assert len(waves) == 2
    assert len(waves[0]) == 10

    # -5.0 の場合 -> default_wave_size にフォールバック
    with pytest.warns(UserWarning, match="must be a positive integer"):
        waves = scheduler.schedule_waves(tasks, wave_size=-5.0)
    assert len(waves) == 2
    assert len(waves[0]) == 10


def test_wave_scheduler_assertion_error_propagation():
    # 異常系: wave_size 変換中に AssertionError が発生した場合、伝播すること
    class AssertionErrorInt:
        def __int__(self):
            assert False, "Simulated assertion error"
            return 5

    scheduler = WaveScheduler(default_wave_size=10)
    with pytest.raises(AssertionError, match="Simulated assertion error"):
        scheduler.schedule_waves([{"id": 1}], wave_size=AssertionErrorInt())


def test_wave_scheduler_memory_error_propagation():
    # 異常系: wave_size 変換中に MemoryError が発生した場合、伝播すること
    class MemoryErrorInt:
        def __int__(self):
            raise MemoryError("Simulated memory error")

    scheduler = WaveScheduler(default_wave_size=10)
    with pytest.raises(MemoryError, match="Simulated memory error"):
        scheduler.schedule_waves([{"id": 1}], wave_size=MemoryErrorInt())


def test_wave_scheduler_attribute_error_propagation():
    # 異常系: wave_size 変換中に AttributeError が発生した場合、安全にキャッチされ、フォールバックされること
    class AttributeErrorInt:
        def __int__(self):
            raise AttributeError("Simulated attribute error")

    scheduler = WaveScheduler(default_wave_size=10)
    with pytest.warns(UserWarning, match="Unexpected error during wave_size"):
        waves = scheduler.schedule_waves([{"id": 1}], wave_size=AttributeErrorInt())
    assert len(waves) == 1


def test_wave_scheduler_import_error_propagation():
    # 異常系: wave_size 変換中に ImportError が発生した場合、安全にキャッチされ、フォールバックされること
    class ImportErrorInt:
        def __int__(self):
            raise ImportError("Simulated import error")

    scheduler = WaveScheduler(default_wave_size=10)
    with pytest.warns(UserWarning, match="Unexpected error during wave_size"):
        waves = scheduler.schedule_waves([{"id": 1}], wave_size=ImportErrorInt())
    assert len(waves) == 1


def test_wave_scheduler_task_iteration_assertion_error_propagation():
    # 異常系: タスクイテレーション中に AssertionError が発生した場合、伝播すること
    def assertion_error_generator():
        yield {"id": 1}
        assert False, "Simulated assertion error during iteration"

    scheduler = WaveScheduler(default_wave_size=5)
    with pytest.raises(AssertionError, match="Simulated assertion error during iteration"):
        scheduler.schedule_waves(assertion_error_generator())


def test_wave_scheduler_task_iteration_memory_error_propagation():
    # 異常系: タスクイテレーション中に MemoryError が発生した場合、伝播すること
    def memory_error_generator():
        yield {"id": 1}
        raise MemoryError("Simulated memory error during iteration")

    scheduler = WaveScheduler(default_wave_size=5)
    with pytest.raises(MemoryError, match="Simulated memory error during iteration"):
        scheduler.schedule_waves(memory_error_generator())


def test_wave_scheduler_task_iteration_attribute_error_propagation():
    # 異常系: タスクイテレーション中に AttributeError が発生した場合、安全にキャッチされ、それまでに得られたタスクが返されること
    def attribute_error_generator():
        yield {"id": 1}
        raise AttributeError("Simulated attribute error during iteration")

    scheduler = WaveScheduler(default_wave_size=5)
    with pytest.warns(RuntimeWarning, match="Exception raised during task iteration"):
        waves = scheduler.schedule_waves(attribute_error_generator())
    assert len(waves) == 1
    assert len(waves[0]) == 1


def test_wave_scheduler_task_iteration_import_error_propagation():
    # 異常系: タスクイテレーション中に ImportError が発生した場合、安全にキャッチされ、それまでに得られたタスクが返されること
    def import_error_generator():
        yield {"id": 1}
        raise ImportError("Simulated import error during iteration")

    scheduler = WaveScheduler(default_wave_size=5)
    with pytest.warns(RuntimeWarning, match="Exception raised during task iteration"):
        waves = scheduler.schedule_waves(import_error_generator())
    assert len(waves) == 1
    assert len(waves[0]) == 1


def test_wave_scheduler_task_iteration_type_error_propagation():
    # 異常系: タスクイテレーション中に TypeError が発生した場合、安全にキャッチされ、それまでに得られたタスクが返されること
    def type_error_generator():
        yield {"id": 1}
        raise TypeError("Simulated TypeError during iteration")

    scheduler = WaveScheduler(default_wave_size=5)
    with pytest.warns(RuntimeWarning, match="Exception raised during task iteration"):
        waves = scheduler.schedule_waves(type_error_generator())
    assert len(waves) == 1
    assert len(waves[0]) == 1


def test_wave_scheduler_task_iteration_value_error_propagation():
    # 異常系: タスクイテレーション中に ValueError が発生した場合、安全にキャッチされ、それまでに得られたタスクが返されること
    def value_error_generator():
        yield {"id": 1}
        raise ValueError("Simulated ValueError during iteration")

    scheduler = WaveScheduler(default_wave_size=5)
    with pytest.warns(RuntimeWarning, match="Exception raised during task iteration"):
        waves = scheduler.schedule_waves(value_error_generator())
    assert len(waves) == 1
    assert len(waves[0]) == 1


def test_wave_scheduler_task_iteration_key_error_propagation():
    # 異常系: タスクイテレーション中に KeyError が発生した場合、安全にキャッチされ、それまでに得られたタスクが返されること
    def key_error_generator():
        yield {"id": 1}
        raise KeyError("Simulated KeyError during iteration")

    scheduler = WaveScheduler(default_wave_size=5)
    with pytest.warns(RuntimeWarning, match="Exception raised during task iteration"):
        waves = scheduler.schedule_waves(key_error_generator())
    assert len(waves) == 1
    assert len(waves[0]) == 1


def test_wave_scheduler_task_iteration_index_error_propagation():
    # 異常系: タスクイテレーション中に IndexError が発生した場合、安全にキャッチされ、それまでに得られたタスクが返されること
    def index_error_generator():
        yield {"id": 1}
        raise IndexError("Simulated IndexError during iteration")

    scheduler = WaveScheduler(default_wave_size=5)
    with pytest.warns(RuntimeWarning, match="Exception raised during task iteration"):
        waves = scheduler.schedule_waves(index_error_generator())
    assert len(waves) == 1
    assert len(waves[0]) == 1


def test_wave_scheduler_warning_error_during_validation_propagation(monkeypatch):
    # 異常系: validation 中に warnings.warn 自体が TypeError などを投げた場合（例: 引数間違いや警告エラー設定）、
    # coercion failed として握りつぶされず、上に伝播することを確認。
    def mock_warn(message, category=None, stacklevel=1):
        raise TypeError("Mocked TypeError inside warnings.warn")

    import warnings
    monkeypatch.setattr(warnings, "warn", mock_warn)

    scheduler = WaveScheduler(default_wave_size=10)
    # warnings.warn が呼ばれるような無効な wave_size を渡す。
    # ここで発生した TypeError は coercion failed の try スコープ外なので、揉み消されずに伝播するはず。
    with pytest.raises(TypeError, match="Mocked TypeError inside warnings.warn"):
        scheduler.schedule_waves([{"id": 1}], wave_size=0)

def test_wave_scheduler_zero_fallback_no_warning_duplication():
    # 正常系: wave_size=0, default_wave_size=0 の場合、
    # 警告は1回だけ (Falling back to 30) 発生し、最終的に 30 にフォールバックされること。
    scheduler = WaveScheduler(default_wave_size=10)
    scheduler.default_wave_size = 0
    
    tasks = [{"id": i} for i in range(5)]
    with pytest.warns(UserWarning, match="Falling back to 30") as w:
        waves = scheduler.schedule_waves(tasks, wave_size=0)
    
    # 警告が 1 回だけであることを検証
    assert len(w) == 1
    assert len(waves) == 1
    assert len(waves[0]) == 5


def test_wave_scheduler_system_error_propagation():
    # 異常系: wave_size 変換中に SystemError が発生した場合、伝播すること
    class SystemErrorInt:
        def __int__(self):
            raise SystemError("Simulated system error")
            
    scheduler = WaveScheduler(default_wave_size=10)
    with pytest.raises(SystemError, match="Simulated system error"):
        scheduler.schedule_waves([{"id": 1}], wave_size=SystemErrorInt())

def test_wave_scheduler_recursion_error_propagation():
    # 異常系: wave_size 変換中に RecursionError が発生した場合、伝播すること
    class RecursionErrorInt:
        def __int__(self):
            raise RecursionError("Simulated recursion error")
            
    scheduler = WaveScheduler(default_wave_size=10)
    with pytest.raises(RecursionError, match="Simulated recursion error"):
        scheduler.schedule_waves([{"id": 1}], wave_size=RecursionErrorInt())

def test_wave_scheduler_task_iteration_system_error_propagation():
    # 異常系: タスクイテレーション中に SystemError が発生した場合、伝播すること
    def system_error_generator():
        yield {"id": 1}
        raise SystemError("Simulated system error during iteration")
        
    scheduler = WaveScheduler(default_wave_size=5)
    with pytest.raises(SystemError, match="Simulated system error during iteration"):
        scheduler.schedule_waves(system_error_generator())

def test_wave_scheduler_task_iteration_recursion_error_propagation():
    # 異常系: タスクイテレーション中に RecursionError が発生した場合、伝播すること
    def recursion_error_generator():
        yield {"id": 1}
        raise RecursionError("Simulated recursion error during iteration")
        
    scheduler = WaveScheduler(default_wave_size=5)
    with pytest.raises(RecursionError, match="Simulated recursion error during iteration"):
        scheduler.schedule_waves(recursion_error_generator())


def test_wave_scheduler_exception_group_fatal_propagation():
    # 異常系: ExceptionGroup 内に AssertionError などの致命的例外が含まれている場合、伝播すること
    class FatalExceptionGroupInt:
        def __int__(self):
            raise ExceptionGroup("Nested fatal error", [AssertionError("Fatal assertion inside group")])

    scheduler = WaveScheduler(default_wave_size=10)
    with pytest.raises(ExceptionGroup) as excinfo:
        scheduler.schedule_waves([{"id": 1}], wave_size=FatalExceptionGroupInt())
    
    assert excinfo.value.subgroup((AssertionError,)) is not None

def test_wave_scheduler_exception_group_nonfatal_fallback():
    # 異常系: ExceptionGroup 内に致命的例外が含まれていない場合、安全にフォールバックすること
    class NonFatalExceptionGroupInt:
        def __int__(self):
            raise ExceptionGroup("Nested non-fatal error", [ValueError("Non-fatal value error inside group")])

    scheduler = WaveScheduler(default_wave_size=10)
    tasks = [{"id": i} for i in range(15)]
    
    # 致命的でないのでフォールバックされ、警告が発生する
    with pytest.warns(UserWarning, match="Unexpected error during wave_size"):
        waves = scheduler.schedule_waves(tasks, wave_size=NonFatalExceptionGroupInt())
    
    # default_wave_size=10 にフォールバックされる
    assert len(waves) == 2
    assert len(waves[0]) == 10

def test_wave_scheduler_task_iteration_exception_group_fatal_propagation():
    # 異常系: タスクイテレーション中に AssertionError を含む ExceptionGroup が発生した場合、伝播すること
    def fatal_group_generator():
        yield {"id": 1}
        raise ExceptionGroup("Nested fatal error during iteration", [AssertionError("Fatal assertion during iteration")])

    scheduler = WaveScheduler(default_wave_size=5)
    with pytest.raises(ExceptionGroup) as excinfo:
        scheduler.schedule_waves(fatal_group_generator())
        
    assert excinfo.value.subgroup((AssertionError,)) is not None

def test_wave_scheduler_task_iteration_exception_group_nonfatal_fallback():
    # 異常系: タスクイテレーション中に致命的例外を含まない ExceptionGroup が発生した場合、安全にキャッチされ、それまでのタスクが返されること
    def nonfatal_group_generator():
        yield {"id": 1}
        yield {"id": 2}
        raise ExceptionGroup("Nested non-fatal error during iteration", [ValueError("Non-fatal value error during iteration")])

    scheduler = WaveScheduler(default_wave_size=5)
    with pytest.warns(RuntimeWarning, match="Exception raised during task iteration"):
        waves = scheduler.schedule_waves(nonfatal_group_generator())
        
    # 最初期に得られたタスクが返される
    assert len(waves) == 1
    assert len(waves[0]) == 2

def test_wave_scheduler_exception_group_compatibility():
    # 互換性定義により、ExceptionGroup が常にモジュールに存在することを確認
    import agents.orchestration.wave_scheduler as ws
    assert hasattr(ws, "ExceptionGroup")
    assert issubclass(ws.ExceptionGroup, BaseException)

def test_wave_scheduler_exception_group_mocked_fallback(caplog):
    # ExceptionGroup がダミークラス（Python < 3.11 環境を模擬）の状態で
    # 例外が発生したときのフォールバック処理を検証
    import agents.orchestration.wave_scheduler as ws
    import logging
    
    # 元の ExceptionGroup を退避
    original_EG = ws.ExceptionGroup
    
    # Python < 3.11 を模擬したダミーの ExceptionGroup に差し替える
    class DummyExceptionGroup(BaseException):
        pass
        
    ws.ExceptionGroup = DummyExceptionGroup
    
    try:
        class BadInt:
            def __int__(self):
                # 任意の例外を投げる
                raise ZeroDivisionError("Simulated validation failure")
                
        scheduler = WaveScheduler(default_wave_size=10)
        
        with caplog.at_level(logging.ERROR):
            with pytest.warns(UserWarning, match="Unexpected error during wave_size"):
                waves = scheduler.schedule_waves([{"id": 1}], wave_size=BadInt())
        
        # default_wave_size=10 にフォールバックされるはず
        assert len(waves) == 1
        
    finally:
        # 元に戻す
        ws.ExceptionGroup = original_EG


def test_wave_scheduler_exception_group_no_subgroup(caplog):
    # subgroup メソッドを持たないダミーの ExceptionGroup クラスが
    # NameError からフォールバック定義された状態での安全なエラー処理を検証
    import agents.orchestration.wave_scheduler as ws
    import logging
    
    # 元の ExceptionGroup を退避
    original_EG = ws.ExceptionGroup
    
    # subgroup メソッドを持たないカスタム ExceptionGroup クラス
    class NoSubgroupExceptionGroup(Exception):
        pass
        
    ws.ExceptionGroup = NoSubgroupExceptionGroup
    
    try:
        class ExceptionGroupRaiser:
            def __int__(self):
                raise NoSubgroupExceptionGroup("Dummy group error")
                
        scheduler = WaveScheduler(default_wave_size=10)
        
        with caplog.at_level(logging.ERROR):
            with pytest.warns(UserWarning, match="Unexpected error during wave_size"):
                waves = scheduler.schedule_waves([{"id": 1}], wave_size=ExceptionGroupRaiser())
                
        # AttributeError にならず、default_wave_size=10 にフォールバックされるはず
        assert len(waves) == 1
        
    finally:
        # 元に戻す
        ws.ExceptionGroup = original_EG
