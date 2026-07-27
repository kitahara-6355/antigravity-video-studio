import pytest
from backend.tests.analyze_coverage import calculate_gap, print_report, main, modules

def test_calculate_gap_basic():
    # 正常系の検証
    test_modules = [
        ("module_a.py", 100, 50, 50),
        ("module_b.py", 200, 10, 95),
        ("module_c.py", 150, 40, 73),
    ]
    # total=450, missed=100. target_pct=70 -> max_missed = 135 -> need_to_cover = 100 - 135 = -35.
    # テストのために need_to_cover > 0 になるような値を設定
    res = calculate_gap(test_modules, total_statements=500, total_missed_statements=200, target_coverage_pct=80)
    
    # max_missed = 500 * (100 - 80) / 100 = 100
    # need_to_cover = 200 - 100 = 100
    assert res["max_missed_statements"] == 100
    assert res["needed_to_cover"] == 100
    
    # ソート順の検証: missの降順 (50, 40, 10)
    sorted_names = [m["name"] for m in res["sorted_modules"]]
    assert sorted_names == ["module_a.py", "module_c.py", "module_b.py"]
    
    # gap_percentage の計算検証 (miss / need_to_cover * 100)
    # a: 50 / 100 * 100 = 50.0
    # c: 40 / 100 * 100 = 40.0
    # b: 10 / 100 * 100 = 10.0
    assert res["sorted_modules"][0]["gap_percentage"] == 50.0
    assert res["sorted_modules"][1]["gap_percentage"] == 40.0
    assert res["sorted_modules"][2]["gap_percentage"] == 10.0
    
    # marker の検証: miss >= 50 は " <<<", それ以外は ""
    assert res["sorted_modules"][0]["marker"] == " <<<"
    assert res["sorted_modules"][1]["marker"] == ""
    assert res["sorted_modules"][2]["marker"] == ""
    
    # total_missed_listed: 50 + 40 + 10 = 100
    assert res["total_missed_listed"] == 100
    # final_coverage_pct: (500 - (200 - 100)) / 500 * 100 = 400 / 500 * 100 = 80.0
    assert res["final_coverage_pct"] == 80.0

def test_calculate_gap_boundary():
    # 空のリスト
    res_empty = calculate_gap([], total_statements=100, total_missed_statements=30, target_coverage_pct=70)
    assert res_empty["sorted_modules"] == []
    assert res_empty["total_missed_listed"] == 0
    
    # need_to_cover が 0 以下のケース
    res_negative = calculate_gap(
        [("module_a.py", 100, 10, 90)],
        total_statements=100,
        total_missed_statements=10,
        target_coverage_pct=70
    )
    # max_missed = 30 -> need_to_cover = 10 - 30 = -20.
    assert res_negative["needed_to_cover"] < 0
    # need_to_cover <= 0 の場合、pct_of_gap は 0.0 になること
    assert res_negative["sorted_modules"][0]["gap_percentage"] == 0.0
    
    # total_statements が 0 のケース (ゼロ除算の回避確認)
    res_zero_stmts = calculate_gap(
        [("module_a.py", 0, 0, 100)],
        total_statements=0,
        total_missed_statements=0,
        target_coverage_pct=70
    )
    assert res_zero_stmts["final_coverage_pct"] == 0.0

def test_print_report(capsys):
    test_results = {
        "sorted_modules": [
            {"name": "module_a.py", "statements": 100, "missed_statements": 50, "coverage_pct": 50, "gap_percentage": 50.0, "marker": " <<<"}
        ],
        "max_missed_statements": 100,
        "needed_to_cover": 100,
        "total_missed_listed": 50,
        "final_coverage_pct": 90.0
    }
    print_report(test_results, total_statements=500, total_missed_statements=200, target_coverage_pct=80)
    captured = capsys.readouterr()
    
    assert "Current: 49% (500 stmts, 200 missed)" in captured.out
    assert "Target: 80% (max 100 missed)" in captured.out
    assert "Need to cover: 100 additional stmts" in captured.out
    assert "module_a.py" in captured.out
    assert "50.0% <<<" in captured.out
    assert "Total missed in listed modules: 50" in captured.out
    assert "Cumulative coverage after covering all: 90.0%" in captured.out

def test_main(capsys):
    # mainが例外なく実行できること
    main()
    captured = capsys.readouterr()
    assert "Current: 49%" in captured.out
    assert "Cumulative coverage after covering all" in captured.out
    assert len(modules) > 0

def test_script_execution(capsys):
    import runpy
    # runpyを使ってスクリプトとして直接実行された場合をシミュレート
    runpy.run_path("backend/tests/analyze_coverage.py", run_name="__main__")
    captured = capsys.readouterr()
    assert "Current: 49%" in captured.out
    assert "Cumulative coverage after covering all" in captured.out

def test_calculate_gap_invalid_inputs():
    # 不正なタプル形式のモジュールリストを渡した場合に ValueError が発生することの検証
    invalid_modules = [
        ("invalid_module.py", 100, 50)  # 要素数が足りない (4つの要素が必要)
    ]
    with pytest.raises(ValueError):
        calculate_gap(invalid_modules)

def test_calculate_gap_extreme_pct():
    # target_pct が 0 や 100 の場合の境界値検証
    test_modules = [("module_a.py", 100, 50, 50)]
    
    # target_pct = 0 (max_missed = 100 * 100 / 100 = 100, need_to_cover = 50 - 100 = -50)
    res_zero = calculate_gap(test_modules, total_statements=100, total_missed_statements=50, target_coverage_pct=0)
    assert res_zero["max_missed_statements"] == 100
    assert res_zero["needed_to_cover"] == -50
    assert res_zero["sorted_modules"][0]["gap_percentage"] == 0.0

    # target_pct = 100 (max_missed = 0, need_to_cover = 50 - 0 = 50)
    res_hundred = calculate_gap(test_modules, total_statements=100, total_missed_statements=50, target_coverage_pct=100)
    assert res_hundred["max_missed_statements"] == 0
    assert res_hundred["needed_to_cover"] == 50
    assert res_hundred["sorted_modules"][0]["gap_percentage"] == 100.0

def test_calculate_gap_missed_greater_than_total():
    # current_missed が total_stmts より大きい異常系の検証
    test_modules = [("module_a.py", 100, 150, -50)]
    res = calculate_gap(test_modules, total_statements=100, total_missed_statements=150, target_coverage_pct=70)
    # max_missed = 30, need_to_cover = 150 - 30 = 120
    assert res["needed_to_cover"] == 120
    # cumulative_coverage_pct: (100 - (150 - 150)) / 100 * 100 = 100.0
    assert res["final_coverage_pct"] == 100.0

def test_print_report_invalid_results():
    # results のキーが不足している場合に KeyError が発生することの検証
    incomplete_results = {
        "sorted_modules": []
        # 他のキーが欠損している
    }
    with pytest.raises(KeyError):
        print_report(incomplete_results)

def test_calculate_gap_invalid_target_pct():
    with pytest.raises(ValueError, match="target_pct must be between 0 and 100"):
        calculate_gap([], target_coverage_pct=-1)
    with pytest.raises(ValueError, match="target_pct must be between 0 and 100"):
        calculate_gap([], target_coverage_pct=101)

def test_calculate_gap_negative_stmts():
    with pytest.raises(ValueError, match="total_stmts and current_missed must be non-negative"):
        calculate_gap([], total_statements=-1)
    with pytest.raises(ValueError, match="total_stmts and current_missed must be non-negative"):
        calculate_gap([], total_missed_statements=-1)

def test_calculate_gap_invalid_tuple_length():
    invalid_modules = [("module_a.py", 100, 50)]  # 要素数3
    with pytest.raises(ValueError, match="Module item at index 0 must be a tuple/list of length 4"):
        calculate_gap(invalid_modules)
    invalid_modules2 = ["not_a_tuple"]  # タプルでもリストでもない
    with pytest.raises(ValueError, match="Module item at index 0 must be a tuple/list of length 4"):
        calculate_gap(invalid_modules2)

def test_calculate_gap_need_to_cover_zero():
    # need_to_cover がちょうど 0 になるケース (current_missed - max_missed == 0)
    test_modules = [("module_a.py", 100, 50, 50)]
    res = calculate_gap(test_modules, total_statements=500, total_missed_statements=100, target_coverage_pct=80)
    assert res["needed_to_cover"] == 0
    assert res["sorted_modules"][0]["gap_percentage"] == 0.0

def test_calculate_gap_invalid_element_types():
    # タプル内の値の型が不正な場合の挙動テスト
    invalid_modules = [("module_a.py", 100, "50", 50)]
    with pytest.raises(TypeError):
        calculate_gap(invalid_modules)

def test_calculate_gap_invalid_modules_list_type():
    # modules_listにNoneなどイテレート不可能な値が渡された場合にTypeErrorが発生することを検証
    with pytest.raises(TypeError):
        calculate_gap(None)

