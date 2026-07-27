import sys
import os
import importlib

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import backend.ux_verification.snapshot
import backend.ux_verification.ratchet

importlib.reload(backend.ux_verification.snapshot)
importlib.reload(backend.ux_verification.ratchet)

import pytest
import logging
from backend.ux_verification.snapshot import UXVerificationSnapshot, VerificationItem
from backend.ux_verification.ratchet import RatchetValidator, RatchetResult, RatchetViolation

def test_ratchet_validation_errors():
    validator = RatchetValidator()
    
    # previous is None
    with pytest.raises(ValueError, match="previous.*None"):
        validator.validate(None, UXVerificationSnapshot(version="v1.0.0"))
        
    # current is None
    with pytest.raises(ValueError, match="current.*None"):
        validator.validate(UXVerificationSnapshot(version="v1.0.0"), None)

def test_ratchet_validation_success(caplog):
    validator = RatchetValidator()
    
    prev = UXVerificationSnapshot(
        version="v1.0.0",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": "S1", "passed": True},
            {"id": "item2", "ux_story": "O-3", "layer": 2, "story_scene": "", "passed": False}
        ]
    )
    
    # すべて改善または現状維持
    curr = UXVerificationSnapshot(
        version="v1.0.1",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": "S1", "passed": True},
            {"id": "item2", "ux_story": "O-3", "layer": 2, "story_scene": "", "passed": True}, # passed に改善
            {"id": "item3", "ux_story": "O-4", "layer": 3, "story_scene": "S2", "passed": True}  # 項目追加
        ]
    )
    
    with caplog.at_level(logging.INFO):
        result = validator.validate(prev, curr)
        
    assert result.valid is True
    assert len(result.violations) == 0
    assert result.delta_items == 1
    assert result.delta_correlation > 0
    assert result.delta_pass == 2 # 元々は1個PASS、現在3個PASSなので +2
    
    # ログ出力検証
    assert "ラチェット検証PASS" in caplog.text
    # __str__の検証
    assert "✅ ラチェット検証PASS:" in str(result)
    assert "検証項目数:  2 → 3" in result.report
    assert "連動率:      50.0% → 66.67%" in result.report or "50.0% → 66.7%" in result.report

def test_ratchet_validation_regression(caplog):
    validator = RatchetValidator()
    
    # baseline
    prev = UXVerificationSnapshot(
        version="v1.0.0",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": "S1", "passed": True},
            {"id": "item2", "ux_story": "O-3", "layer": 2, "story_scene": "S2", "passed": True},
            {"id": "item3", "ux_story": "O-4", "layer": 3, "story_scene": "", "passed": True}
        ]
    )
    
    # 退行1: 検証項目数減少
    curr_items_down = UXVerificationSnapshot(
        version="v1.0.1",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": "S1", "passed": True},
            {"id": "item2", "ux_story": "O-3", "layer": 2, "story_scene": "S2", "passed": True}
        ]
    )
    result = validator.validate(prev, curr_items_down)
    assert result.valid is False
    assert any(v.metric == "total_items" for v in result.violations)
    
    # 退行2: 連動率低下
    # prev: 3項目中2個がstory_scene有り (66.67%)
    # curr: 3項目中1個がstory_scene有り (33.33%)
    curr_corr_down = UXVerificationSnapshot(
        version="v1.0.1",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": "S1", "passed": True},
            {"id": "item2", "ux_story": "O-3", "layer": 2, "story_scene": "", "passed": True},
            {"id": "item3", "ux_story": "O-4", "layer": 3, "story_scene": "", "passed": True}
        ]
    )
    result = validator.validate(prev, curr_corr_down)
    assert result.valid is False
    assert any(v.metric == "correlation_rate" for v in result.violations)
    
    # 退行3: PASS数減少
    curr_pass_down = UXVerificationSnapshot(
        version="v1.0.1",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": "S1", "passed": True},
            {"id": "item2", "ux_story": "O-3", "layer": 2, "story_scene": "S2", "passed": True},
            {"id": "item3", "ux_story": "O-4", "layer": 3, "story_scene": "", "passed": False} # passed から fail へ
        ]
    )
    with caplog.at_level(logging.WARNING):
        result = validator.validate(prev, curr_pass_down)
    assert result.valid is False
    assert any(v.metric == "pass_items" for v in result.violations)
    assert "ラチェット検証FAIL" in caplog.text
    assert "❌ ラチェット検証FAIL:" in str(result)

def test_ratchet_report_edge_cases():
    validator = RatchetValidator()
    
    # 充足率低下警告 (d_rate < 0 且つ d_items > 0)
    # prev: 2項目中2項目PASS (100%)
    prev = UXVerificationSnapshot(
        version="v1.0.0",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": "S1", "passed": True},
            {"id": "item2", "ux_story": "O-3", "layer": 2, "story_scene": "S2", "passed": True}
        ]
    )
    # curr: 3項目中2項目PASS (66.67%) -> d_items = +1, d_rate = -33.33%
    curr = UXVerificationSnapshot(
        version="v1.0.1",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": "S1", "passed": True},
            {"id": "item2", "ux_story": "O-3", "layer": 2, "story_scene": "S2", "passed": True},
            {"id": "item3", "ux_story": "O-4", "layer": 3, "story_scene": "S3", "passed": False} # 未パスで追加
        ]
    )
    result = validator.validate(prev, curr)
    # 項目数は増えたので validator としては valid (項目数は増、連動率は増、PASS数は現状維持なので退行なし)
    assert result.valid is True
    assert "⚠️ 充足率低下は正常: 検証項目増加による" in result.report
    
    # UXストーリー別ギャップ
    # O-4 のパス率が 0% なのでギャップに表示される
    assert "O-4: 0/1 (0%)" in result.report
    
    # すべて100%の場合はギャップが表示されないこと
    # curr2: 3項目中3項目PASS
    curr2 = UXVerificationSnapshot(
        version="v1.0.1",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": "S1", "passed": True},
            {"id": "item2", "ux_story": "O-3", "layer": 2, "story_scene": "S2", "passed": True},
            {"id": "item3", "ux_story": "O-4", "layer": 3, "story_scene": "S3", "passed": True}
        ]
    )
    result2 = validator.validate(prev, curr2)
    assert "システム適合度ギャップ" in result2.report
    # O-2, O-3, O-4 はすべて100%なので、具体的なストーリー名のリストアップは含まれない
    assert "O-2" not in result2.report.split("システム適合度ギャップ:")[1]
    assert "O-3" not in result2.report.split("システム適合度ギャップ:")[1]
    assert "O-4" not in result2.report.split("システム適合度ギャップ:")[1]

def test_ratchet_multiple_violations():
    validator = RatchetValidator()
    # 基準
    prev = UXVerificationSnapshot(
        version="v1.0.0",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": "S1", "passed": True},
            {"id": "item2", "ux_story": "O-3", "layer": 2, "story_scene": "S2", "passed": True},
            {"id": "item3", "ux_story": "O-4", "layer": 3, "story_scene": "", "passed": True}
        ]
    )
    # 複数違反が同時に発生するケース:
    # 1. 項目数減少: 3 -> 2
    # 2. 連動率低下: 2/3 (66.7%) -> 0/2 (0.0%)
    # 3. PASS数減少: 3 -> 1
    curr = UXVerificationSnapshot(
        version="v1.0.1",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": "", "passed": True},
            {"id": "item2", "ux_story": "O-3", "layer": 2, "story_scene": "", "passed": False}
        ]
    )
    result = validator.validate(prev, curr)
    assert result.valid is False
    assert len(result.violations) == 3
    
    metrics = [v.metric for v in result.violations]
    assert "total_items" in metrics
    assert "correlation_rate" in metrics
    assert "pass_items" in metrics
    
    # 文字列表現にすべてのエラーが含まれるか
    err_str = str(result)
    assert "❌ ラチェット検証FAIL: 3件の違反" in err_str
    assert "検証項目数が減少" in err_str
    assert "UXストーリー連動率が低下" in err_str
    assert "PASS項目数が減少" in err_str

def test_ratchet_fulfillment_warning_conditions():
    validator = RatchetValidator()
    
    # 基本のprev (充足率100%, 項目数2)
    prev = UXVerificationSnapshot(
        version="v1.0.0",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": "S1", "passed": True},
            {"id": "item2", "ux_story": "O-3", "layer": 2, "story_scene": "S2", "passed": True}
        ]
    )
    
    # パターン1: 充足率低下、かつ項目数増加 (警告が出る)
    curr1 = UXVerificationSnapshot(
        version="v1.0.1",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": "S1", "passed": True},
            {"id": "item2", "ux_story": "O-3", "layer": 2, "story_scene": "S2", "passed": True},
            {"id": "item3", "ux_story": "O-4", "layer": 3, "story_scene": "S3", "passed": False}
        ]
    )
    result1 = validator.validate(prev, curr1)
    assert "⚠️ 充足率低下は正常: 検証項目増加による" in result1.report

    # パターン2: 充足率増加(または不変)、かつ項目数増加 (警告は出ない)
    curr2 = UXVerificationSnapshot(
        version="v1.0.1",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": "S1", "passed": True},
            {"id": "item2", "ux_story": "O-3", "layer": 2, "story_scene": "S2", "passed": True},
            {"id": "item3", "ux_story": "O-4", "layer": 3, "story_scene": "S3", "passed": True}
        ]
    )
    result2 = validator.validate(prev, curr2)
    assert "⚠️ 充足率低下は正常" not in result2.report

    # パターン3: 充足率低下、かつ項目数減少・不変 (警告は出ない。そもそもvalidatorとしては退行でFAILになるがレポート生成自体は行われる)
    curr3 = UXVerificationSnapshot(
        version="v1.0.1",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": "S1", "passed": True},
            {"id": "item2", "ux_story": "O-3", "layer": 2, "story_scene": "S2", "passed": False}
        ]
    )
    result3 = validator.validate(prev, curr3)
    assert result3.valid is False
    assert "⚠️ 充足率低下は正常" not in result3.report

def test_ratchet_gap_report_edge_cases():
    validator = RatchetValidator()
    prev = UXVerificationSnapshot(
        version="v1.0.0",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": "S1", "passed": True}
        ]
    )
    
    # 1. 項目数が0のストーリー（total=0）をシミュレート
    curr = UXVerificationSnapshot(
        version="v1.0.1",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": "S1", "passed": True}
        ]
    )
    curr.compute_aggregates()
    curr.items_per_story["O-Zero"] = 0
    curr.pass_per_story["O-Zero"] = 0
    
    report = validator._generate_report(prev, curr)
    assert "O-Zero: 0/0 (0%)" in report

    # 2. 複数のストーリーでパス率が100%未満の場合、アルファベット順にソートされることの検証
    curr2 = UXVerificationSnapshot(
        version="v1.0.1",
        items=[
            {"id": "item1", "ux_story": "O-3", "layer": 1, "story_scene": "S1", "passed": False},
            {"id": "item2", "ux_story": "O-2", "layer": 1, "story_scene": "S1", "passed": False}
        ]
    )
    prev2 = UXVerificationSnapshot(version="v1.0.0", items=[])
    prev2.compute_aggregates()
    curr2.compute_aggregates()
    report2 = validator._generate_report(prev2, curr2)
    
    idx_o2 = report2.index("O-2: 0/1 (0%)")
    idx_o3 = report2.index("O-3: 0/1 (0%)")
    assert idx_o2 < idx_o3

def test_ratchet_violation_fields():
    violation = RatchetViolation(
        metric="total_items",
        previous_value=10.0,
        current_value=8.0,
        delta=-2.0,
        message="Total items decreased"
    )
    assert violation.metric == "total_items"
    assert violation.previous_value == 10.0
    assert violation.current_value == 8.0
    assert violation.delta == -2.0
    assert violation.message == "Total items decreased"

    res = RatchetResult(valid=True)
    assert res.valid is True
    assert res.violations == []
    assert res.delta_items == 0
    assert res.delta_correlation == 0.0
    assert res.delta_pass == 0
    assert res.report == ""


def test_ratchet_gap_report_layer_details():
    validator = RatchetValidator()
    prev = UXVerificationSnapshot(version="v1.0.0", items=[])
    curr = UXVerificationSnapshot(
        version="v1.0.1",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": "S1", "passed": False},
            {"id": "item2", "ux_story": "O-2", "layer": 3, "story_scene": "S2", "passed": False},
            {"id": "item3", "ux_story": "O-2", "layer": 3, "story_scene": "S3", "passed": False},
            {"id": "item4", "ux_story": "O-2", "layer": 5, "story_scene": "S4", "passed": True},
            {"id": "item5", "ux_story": "O-2", "layer": 0, "story_scene": "S5", "passed": False},
        ]
    )
    # 明示的に layer を None に設定してフォールバック処理をテスト
    curr.items[4].layer = None

    prev.compute_aggregates()
    curr.compute_aggregates()
    report = validator._generate_report(prev, curr)
    
    # O-2: 1/5 (20%) — L0層で1件未PASS, L1層で1件未PASS, L3層で2件未PASS
    assert "O-2: 1/5 (20%) — L0層で1件未PASS, L1層で1件未PASS, L3層で2件未PASS" in report


def test_ratchet_gap_report_passed_none():
    """passed が None（未検証/スキップ）の場合のギャップレポート出力を検証"""
    validator = RatchetValidator()
    prev = UXVerificationSnapshot(
        version="v1.0.0",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": "S1", "passed": True}
        ]
    )
    # item2 は passed が None (未検証)
    curr = UXVerificationSnapshot(
        version="v1.0.1",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": "S1", "passed": True},
            {"id": "item2", "ux_story": "O-2", "layer": 2, "story_scene": "S2", "passed": None}
        ]
    )
    result = validator.validate(prev, curr)
    # passed=None は is not True を満たすため、ギャップレポートに含まれる
    assert "O-2: 1/2 (50%) — L2層で1件未PASS" in result.report


def test_ratchet_result_string_representation_boundaries():
    """valid=True で delta が負の値の場合などの __str__ フォーマット（極端な入力の検証）"""
    res = RatchetResult(
        valid=True,
        delta_items=-5,
        delta_correlation=-12.5,
        delta_pass=-3
    )
    str_res = str(res)
    assert "✅ ラチェット検証PASS: 項目+-5, 連動率+-12.5%, PASS+-3" in str_res


def test_ratchet_correlation_rate_float_precision():
    """連動率が極めて小さな浮動小数点の場合の検証と表示"""
    validator = RatchetValidator()
    
    # 項目数を非常に大きくして、1項目の追加による連動率の変化を極小にする
    items_prev = [{"id": f"item{i}", "ux_story": "O-2", "layer": 1, "story_scene": "S1" if i < 1000 else "", "passed": True} for i in range(10000)]
    # prev 連動率: 1000/10000 * 100 = 10.0%
    prev = UXVerificationSnapshot(version="v1.0.0", items=items_prev)
    
    # 1項目だけ story_scene を追加する (連動率: 1001/10000 = 10.01%) -> 変化 +0.01%
    items_curr = list(items_prev)
    items_curr[1000] = {"id": "item1000", "ux_story": "O-2", "layer": 1, "story_scene": "S2", "passed": True}
    curr = UXVerificationSnapshot(version="v1.0.1", items=items_curr)
    
    result = validator.validate(prev, curr)
    assert result.valid is True
    # 小数点第1位での表示確認 (10.01% - 10.0% = 0.01% -> 表示は 0.0%)
    assert "連動率+0.0%" in str(result)


def test_ratchet_gap_report_missing_layer_key():
    """VerificationItem の get および __contains__ において、存在しないキーが指定された場合の挙動を検証"""
    item = VerificationItem(id="item1", ux_story="O-2", passed=False)
    
    # 存在しないキーに対して __contains__ (in) が False を返すことを確認
    assert "non_existent_key" not in item
    
    # 存在しないキーに対して get() がデフォルト値を返すことを確認
    assert item.get("non_existent_key", 999) == 999
    
    # 存在しないキーに対して __getitem__ ([]) が KeyError を送出することを確認
    with pytest.raises(KeyError):
        _ = item["non_existent_key"]


def test_ratchet_result_string_representation_exact_format():
    """違反発生時およびPASS時の __str__ 出力形式が改行・インデントを含めて期待通りであることを厳密に検証"""
    # 1. 違反が複数の場合
    violation1 = RatchetViolation(
        metric="total_items",
        previous_value=5,
        current_value=4,
        delta=-1,
        message="検証項目数が減少: 5 → 4 (Δ-1)"
    )
    violation2 = RatchetViolation(
        metric="pass_items",
        previous_value=5,
        current_value=3,
        delta=-2,
        message="PASS項目数が減少 (リグレッション): 5 → 3 (Δ-2)"
    )
    
    res = RatchetResult(
        valid=False,
        violations=[violation1, violation2]
    )
    
    expected_fail_str = (
        "❌ ラチェット検証FAIL: 2件の違反\n"
        "  - 検証項目数が減少: 5 → 4 (Δ-1)\n"
        "  - PASS項目数が減少 (リグレッション): 5 → 3 (Δ-2)"
    )
    assert str(res) == expected_fail_str

    # 2. 正常時のフォーマット検証
    res_success = RatchetResult(
        valid=True,
        delta_items=2,
        delta_correlation=1.5,
        delta_pass=1
    )
    expected_success_str = "✅ ラチェット検証PASS: 項目+2, 連動率+1.5%, PASS+1"
    assert str(res_success) == expected_success_str


def test_ratchet_empty_snapshots():
    validator = RatchetValidator()
    
    # 両方空
    prev_empty = UXVerificationSnapshot(version="v1.0.0", items=[])
    curr_empty = UXVerificationSnapshot(version="v1.0.1", items=[])
    
    result = validator.validate(prev_empty, curr_empty)
    assert result.valid is True
    assert result.delta_items == 0
    assert result.delta_correlation == 0.0
    assert result.delta_pass == 0
    assert "検証項目数:  0 → 0" in result.report
    assert "連動率:      0.0% → 0.0%" in result.report
    assert "充足PASS:    0 → 0" in result.report
    assert "充足率:      0.0% → 0.0%" in result.report

    # 項目ありから空へ退行
    prev_has_items = UXVerificationSnapshot(
        version="v1.0.0",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": "S1", "passed": True}
        ]
    )
    result_regression = validator.validate(prev_has_items, curr_empty)
    assert result_regression.valid is False
    assert any(v.metric == "total_items" for v in result_regression.violations)


def test_ratchet_multiple_regressions():
    validator = RatchetValidator()
    
    # prev: 3項目中 2項目PASS (66.67%), 2項目story_sceneあり (66.67%)
    prev = UXVerificationSnapshot(
        version="v1.0.0",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": "S1", "passed": True},
            {"id": "item2", "ux_story": "O-3", "layer": 2, "story_scene": "S2", "passed": True},
            {"id": "item3", "ux_story": "O-4", "layer": 3, "story_scene": "", "passed": False}
        ]
    )
    
    # curr: 2項目中 0項目PASS (0%), 0項目story_sceneあり (0%)
    curr = UXVerificationSnapshot(
        version="v1.0.1",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": "", "passed": False},
            {"id": "item2", "ux_story": "O-3", "layer": 2, "story_scene": "", "passed": False}
        ]
    )
    
    result = validator.validate(prev, curr)
    assert result.valid is False
    assert len(result.violations) == 3
    
    metrics = {v.metric for v in result.violations}
    assert "total_items" in metrics
    assert "correlation_rate" in metrics
    assert "pass_items" in metrics
    
    # 各違反メッセージの確認
    total_items_violation = next(v for v in result.violations if v.metric == "total_items")
    assert total_items_violation.delta == -1
    
    correlation_violation = next(v for v in result.violations if v.metric == "correlation_rate")
    assert correlation_violation.delta < 0
    
    pass_violation = next(v for v in result.violations if v.metric == "pass_items")
    assert pass_violation.delta == -2


def test_ratchet_gap_report_inconsistent_data():
    """itemsが空であるにもかかわらず集計値が存在するデータ不整合時のギャップレポート出力を検証"""
    validator = RatchetValidator()
    prev = UXVerificationSnapshot(version="v1.0.0", items=[])
    curr = UXVerificationSnapshot(version="v1.0.1", items=[])
    
    # 手動で集計値を設定し、項目が無いのに未パスが存在するように不整合を起こす
    curr.items_per_story = {"O-2": 10}
    curr.pass_per_story = {"O-2": 0}
    
    report = validator._generate_report(prev, curr)
    
    # ギャップレポートとして出力され、detailsは空になる（エラーにならない）ことを確認
    assert "O-2: 0/10 (0%)" in report
    # L0層などの詳細表示（" — L0層で..."）が含まれていないことを確認
    assert " — " not in report.split("システム適合度ギャップ:")[1]


def test_ratchet_gap_report_layer_sorting_edge_cases():
    """レイヤー値に None, 負数, 10以上の数値を含む場合の辞書順ソートを検証"""
    validator = RatchetValidator()
    prev = UXVerificationSnapshot(version="v1.0.0", items=[])
    curr = UXVerificationSnapshot(
        version="v1.0.1",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "passed": False},
            {"id": "item2", "ux_story": "O-2", "layer": 2, "passed": False},
            {"id": "item3", "ux_story": "O-2", "layer": 10, "passed": False},
            {"id": "item4", "ux_story": "O-2", "layer": -1, "passed": False},
            {"id": "item5", "ux_story": "O-2", "layer": None, "passed": False},
        ]
    )
    prev.compute_aggregates()
    curr.compute_aggregates()
    
    report = validator._generate_report(prev, curr)
    
    # sorted(unpassed_by_layer.keys()) の並び順は "L-1", "L0", "L1", "L10", "L2" (辞書順) になるはず
    # 各層の件数表記が含まれることを確認
    assert "L-1層で1件未PASS" in report
    assert "L0層で1件未PASS" in report
    assert "L1層で1件未PASS" in report
    assert "L10層で1件未PASS" in report
    assert "L2層で1件未PASS" in report
    
    # 並び順の検証
    idx_lm1 = report.index("L-1層で1件未PASS")
    idx_l0 = report.index("L0層で1件未PASS")
    idx_l1 = report.index("L1層で1件未PASS")
    idx_l10 = report.index("L10層で1件未PASS")
    idx_l2 = report.index("L2層で1件未PASS")
    
    assert idx_lm1 < idx_l0 < idx_l1 < idx_l10 < idx_l2


def test_ratchet_special_version_characters():
    """バージョン文字列に改行や特殊文字、空文字列が含まれる場合の動作を検証"""
    validator = RatchetValidator()
    
    # 改行や日本語、特殊文字
    prev = UXVerificationSnapshot(version="v1.0.0\n[先行リリース]")
    curr = UXVerificationSnapshot(version="v1.0.1\n[最新リリース☆]")
    
    result = validator.validate(prev, curr)
    assert result.valid is True
    assert "UX検証適合度差分レポート v1.0.0\n[先行リリース] → v1.0.1\n[最新リリース☆]" in result.report
    
    # 空文字列
    prev_empty_v = UXVerificationSnapshot(version="")
    curr_empty_v = UXVerificationSnapshot(version="")
    result_empty = validator.validate(prev_empty_v, curr_empty_v)
    assert result_empty.valid is True
    assert "UX検証適合度差分レポート  → " in result_empty.report


def test_ratchet_invalid_snapshots_initialization():
    """スナップショット内のitemsが極端な値（Noneや空リストなど）の場合の挙動の検証"""
    validator = RatchetValidator()
    
    prev = UXVerificationSnapshot(version="v1.0.0", items=[])
    curr = UXVerificationSnapshot(version="v1.0.1")
    curr.items = None  # 強制的に None をセット
    
    with pytest.raises(TypeError):
        validator.validate(prev, curr)


def test_ratchet_result_delta_boundary_values():
    """deltaの値が極端な値（負の値、非常に大きい値）の場合の挙動の検証"""
    validator = RatchetValidator()
    
    # prev: 1項目中 1項目story_sceneあり (100.0%)
    prev = UXVerificationSnapshot(
        version="v1.0.0",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": "S1", "passed": True}
        ]
    )
    
    # curr: 1項目中 0項目story_sceneあり (0.0%) -> delta_correlation = -100.0
    curr = UXVerificationSnapshot(
        version="v1.0.1",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": "", "passed": True}
        ]
    )
    
    result = validator.validate(prev, curr)
    assert result.valid is False
    assert result.delta_correlation == -100.0
    correlation_violation = next(v for v in result.violations if v.metric == "correlation_rate")
    assert correlation_violation.delta == -100.0
    assert "Δ-100.0%" in correlation_violation.message



def test_ratchet_fulfillment_warning_boundaries():
    """充足率警告の判定境界条件の検証"""
    validator = RatchetValidator()
    
    # delta_rate < 0 かつ delta_items > 0 の時だけ警告が出る
    # 1. delta_rate = 0, delta_items > 0 の場合（警告なし）
    prev = UXVerificationSnapshot(
        version="v1.0.0",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "passed": True}
        ]
    )
    curr = UXVerificationSnapshot(
        version="v1.0.1",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "passed": True},
            {"id": "item2", "ux_story": "O-3", "layer": 2, "passed": True}
        ]
    )
    result = validator.validate(prev, curr)
    assert "⚠️ 充足率低下は正常" not in result.report

    # 2. delta_rate < 0, delta_items = 0 の場合（警告なし）
    prev2 = UXVerificationSnapshot(
        version="v1.0.0",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "passed": True}
        ]
    )
    curr2 = UXVerificationSnapshot(
        version="v1.0.1",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "passed": False}
        ]
    )
    result2 = validator.validate(prev2, curr2)
    assert "⚠️ 充足率低下は正常" not in result2.report


def test_ratchet_gap_report_various_layer_values():
    """layerの値が多様な型や形式の場合の堅牢性の検証"""
    validator = RatchetValidator()
    prev = UXVerificationSnapshot(version="v1.0.0", items=[])
    
    curr = UXVerificationSnapshot(
        version="v1.0.1",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 2.5, "passed": False},
            {"id": "item2", "ux_story": "O-2", "layer": "4", "passed": False},
            {"id": "item3", "ux_story": "O-2", "layer": -3, "passed": False},
        ]
    )
    prev.compute_aggregates()
    curr.compute_aggregates()
    
    report = validator._generate_report(prev, curr)
    assert "L2.5層で1件未PASS" in report
    assert "L4層で1件未PASS" in report
    assert "L-3層で1件未PASS" in report


def test_ratchet_extreme_and_invalid_data():
    validator = RatchetValidator()
    
    # 1. 巨大入力 (10,000件のアイテム)
    prev_items = [
        {"id": f"item_{i}", "ux_story": f"O-{i%10}", "layer": i%5, "story_scene": "S1" if i%2==0 else "", "passed": True}
        for i in range(10000)
    ]
    curr_items = [
        {"id": f"item_{i}", "ux_story": f"O-{i%10}", "layer": i%5, "story_scene": "S1" if i%2==0 else "", "passed": True}
        for i in range(10000)
    ]
    # currに1件追加して増加を確認
    curr_items.append({"id": "item_extra", "ux_story": "O-1", "layer": 1, "story_scene": "S1", "passed": True})
    
    prev = UXVerificationSnapshot(version="v1.0.0", items=prev_items)
    curr = UXVerificationSnapshot(version="v1.0.1", items=curr_items)
    
    result = validator.validate(prev, curr)
    assert result.valid is True
    assert result.delta_items == 1

    # 2. 負の値の不整合データ (データ破損のシミュレーション)
    prev_empty = UXVerificationSnapshot(version="v1.0.0", items=[])
    curr_corrupt = UXVerificationSnapshot(version="v1.0.1", items=[])
    curr_corrupt.items_per_story = {"O-Corrupt": -5}
    curr_corrupt.pass_per_story = {"O-Corrupt": -2}
    
    report = validator._generate_report(prev_empty, curr_corrupt)
    # max(-5, 1) で除算が行われ、round(-2 / 1 * 100) -> -200% となるはず。クラッシュしないことを確認。
    assert "O-Corrupt: -2/-5 (-200%)" in report

    # 3. キー欠損がある VerificationItem のフォールバック
    prev_missing = UXVerificationSnapshot(
        version="v1.0.0",
        items=[
            {"id": "item1"}  # ux_story, layer, story_scene, passed すべて欠損
        ]
    )
    curr_missing = UXVerificationSnapshot(
        version="v1.0.1",
        items=[
            {"id": "item1"},
            {"id": "item2", "ux_story": "O-2"}  # 一部欠損
        ]
    )
    result_missing = validator.validate(prev_missing, curr_missing)
    assert result_missing.valid is True


def test_ratchet_invalid_types():
    """previous や current に不正な型を渡した場合の挙動を検証"""
    validator = RatchetValidator()
    # 文字列や数値を渡した場合に AttributeError が発生することを確認
    with pytest.raises(AttributeError):
        validator.validate("not_a_snapshot", UXVerificationSnapshot(version="v1.0.0"))
    with pytest.raises(AttributeError):
        validator.validate(UXVerificationSnapshot(version="v1.0.0"), 12345)


def test_ratchet_passed_value_variations():
    """passedにTrue/False以外の値（数値、文字列、オブジェクトなど）が指定された場合の挙動を検証"""
    validator = RatchetValidator()
    prev = UXVerificationSnapshot(version="v1.0.0", items=[])
    
    # passed に様々な値（1, "True", [True]）を格納
    curr = UXVerificationSnapshot(
        version="v1.0.1",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "passed": 1},
            {"id": "item2", "ux_story": "O-2", "layer": 2, "passed": "True"},
            {"id": "item3", "ux_story": "O-2", "layer": 3, "passed": [True]},
        ]
    )
    prev.compute_aggregates()
    curr.compute_aggregates()
    
    # passed is not True なので、これらはすべて「未PASS」扱いになり、ギャップレポートに含まれるはず
    report = validator._generate_report(prev, curr)
    assert "O-2: 0/3 (0%)" in report
    assert "L1層で1件未PASS" in report
    assert "L2層で1件未PASS" in report
    assert "L3層で1件未PASS" in report


def test_ratchet_layer_type_variations():
    """layerに辞書やリストなどの特殊な型が格納された場合の堅牢性を検証"""
    validator = RatchetValidator()
    prev = UXVerificationSnapshot(version="v1.0.0", items=[])
    
    curr = UXVerificationSnapshot(
        version="v1.0.1",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": [1, 2], "passed": False},
            {"id": "item2", "ux_story": "O-2", "layer": {"level": 3}, "passed": False},
        ]
    )
    prev.compute_aggregates()
    curr.compute_aggregates()
    
    # layer_name = f"L{l_val}" にて、リストや辞書も文字列化されて出力され、クラッシュしないことを確認
    report = validator._generate_report(prev, curr)
    assert "L[1, 2]層で1件未PASS" in report
    assert "L{'level': 3}層で1件未PASS" in report


def test_ratchet_float_precision_edge_cases():
    """連動率が極めて近い場合の単調増加の比較判定エッジケースを検証"""
    validator = RatchetValidator()
    
    # 項目数を10000にし、微小な差を作る
    # prev: 5001 / 10000 = 50.01%
    prev_items = [{"id": f"item_{i}", "ux_story": "O-2", "layer": 1, "story_scene": "S1" if i < 5001 else "", "passed": True} for i in range(10000)]
    # curr: 5000 / 10000 = 50.0%
    curr_items = [{"id": f"item_{i}", "ux_story": "O-2", "layer": 1, "story_scene": "S1" if i < 5000 else "", "passed": True} for i in range(10000)]
    
    prev = UXVerificationSnapshot(version="v1.0.0", items=prev_items)
    curr = UXVerificationSnapshot(version="v1.0.1", items=curr_items)
    
    # 連動率が低下（50.01% -> 50.0%）しているので、違反（退行）と判定されるべき
    result = validator.validate(prev, curr)
    assert result.valid is False
    assert any(v.metric == "correlation_rate" for v in result.violations)


def test_ratchet_snapshot_item_edge_cases():
    """ux_story, passed, layer が None や空値、欠損しているときのエッジケースを検証"""
    validator = RatchetValidator()
    
    # 1. ux_story が空文字列または None、欠損
    # (ux_storyが無いものはギャップレポートで "unknown" となるが、レイヤー詳細情報が出ない仕様)
    prev = UXVerificationSnapshot(
        version="v1.0.0",
        items=[
            {"id": "item1", "ux_story": "", "layer": 1, "passed": False},
            {"id": "item2", "ux_story": None, "layer": 1, "passed": False},
            {"id": "item3", "layer": 1, "passed": False}
        ]
    )
    
    curr = UXVerificationSnapshot(
        version="v1.0.1",
        items=[
            {"id": "item1", "ux_story": "", "layer": 1, "passed": True},
            {"id": "item2", "ux_story": None, "layer": 1, "passed": True},
            {"id": "item3", "layer": 1, "passed": False}
        ]
    )
    
    result = validator.validate(prev, curr)
    assert result.valid is True
    # ギャップレポートの確認。ux_storyがないものは "unknown" にまとめられる
    assert "unknown: 2/3 (67%)" in result.report
    assert "L1" not in result.report # レイヤー詳細は一致判定の都合で出力されない仕様
    
    # 2. passed が None (未PASS扱い)
    prev_none = UXVerificationSnapshot(
        version="v1.0.0",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "passed": None}
        ]
    )
    curr_none = UXVerificationSnapshot(
        version="v1.0.1",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "passed": None}
        ]
    )
    result_none = validator.validate(prev_none, curr_none)
    assert result_none.valid is True
    assert result_none.delta_pass == 0
    assert "O-2: 0/1 (0%)" in result_none.report

    # 3. layer が None
    prev_layer_none = UXVerificationSnapshot(
        version="v1.0.0",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": None, "passed": False}
        ]
    )
    curr_layer_none = UXVerificationSnapshot(
        version="v1.0.1",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": None, "passed": False}
        ]
    )
    result_layer_none = validator.validate(prev_layer_none, curr_layer_none)
    assert result_layer_none.valid is True
    assert "L0層で1件未PASS" in result_layer_none.report


def test_ratchet_boundary_cases():
    """すべての変化量が 0 (同値) の場合の境界値を検証"""
    validator = RatchetValidator()
    
    prev = UXVerificationSnapshot(
        version="v1.0.0",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": "S1", "passed": True},
            {"id": "item2", "ux_story": "O-3", "layer": 2, "story_scene": "", "passed": False}
        ]
    )
    
    curr = UXVerificationSnapshot(
        version="v1.0.1",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": "S1", "passed": True},
            {"id": "item2", "ux_story": "O-3", "layer": 2, "story_scene": "", "passed": False}
        ]
    )
    
    result = validator.validate(prev, curr)
    assert result.valid is True
    assert result.delta_items == 0
    assert result.delta_correlation == 0.0
    assert result.delta_pass == 0


def test_ratchet_invalid_list_elements():
    """スナップショットの items リストに辞書や VerificationItem 以外の不正なオブジェクトが入っている場合の例外発生を検証"""
    # dictやVerificationItem以外の型を入れた場合は TypeError になることを確認する
    with pytest.raises(TypeError, match="Invalid item type"):
        UXVerificationSnapshot(
            version="v1.0.0",
            items=[
                "this_is_a_string_not_a_dict"
            ]
        )
        
    with pytest.raises(TypeError, match="Invalid item type"):
        UXVerificationSnapshot(
            version="v1.0.0",
            items=[
                None
            ]
        )


def test_ratchet_extreme_and_invalid_data_extended():
    """極端な値や異常な形式のデータに対する耐性を追加検証"""
    validator = RatchetValidator()
    
    # 1. バージョン文字列に非常に長い文字列や日本語、Unicode文字が含まれる場合
    #    (レポートヘッダーがクラッシュせず生成されること)
    long_and_unicode_version = "v1.0.0-beta.1+build.12345.日本語テスト.🌟🚀"
    prev = UXVerificationSnapshot(version=long_and_unicode_version, items=[])
    curr = UXVerificationSnapshot(version="v1.0.1", items=[])
    result = validator.validate(prev, curr)
    assert result.valid is True
    assert long_and_unicode_version in result.report

    # 2. ux_story名に極端な文字列やUnicodeが含まれる場合
    #    (ソートやレポートが壊れないこと)
    ux_story_unicode = "O-🌟-🚀-日本語"
    prev_story = UXVerificationSnapshot(version="v1.0.0", items=[])
    curr_story = UXVerificationSnapshot(
        version="v1.0.1",
        items=[
            {"id": "item1", "ux_story": ux_story_unicode, "layer": 1, "passed": False}
        ]
    )
    result_story = validator.validate(prev_story, curr_story)
    assert result_story.valid is True
    assert ux_story_unicode in result_story.report
    assert "0/1 (0%)" in result_story.report

    # 3. items に VerificationItem インスタンスと dict が混在する場合
    from backend.ux_verification.snapshot import VerificationItem
    mixed_items = [
        VerificationItem(id="item1", ux_story="O-2", layer=1, passed=True),
        {"id": "item2", "ux_story": "O-2", "layer": 2, "passed": False}
    ]
    prev_mixed = UXVerificationSnapshot(version="v1.0.0", items=[])
    curr_mixed = UXVerificationSnapshot(version="v1.0.1", items=mixed_items)
    result_mixed = validator.validate(prev_mixed, curr_mixed)
    assert result_mixed.valid is True
    assert result_mixed.delta_items == 2
    assert result_mixed.delta_pass == 1

    # 4. story_sceneが文字列ではなく整数やリストなどの不正な型の場合
    #    (空文字列でない限り correlation_rate の計算で真偽値判定され、クラッシュしないこと)
    prev_invalid_scene = UXVerificationSnapshot(version="v1.0.0", items=[])
    curr_invalid_scene = UXVerificationSnapshot(
        version="v1.0.1",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": 12345, "passed": True},
            {"id": "item2", "ux_story": "O-2", "layer": 1, "story_scene": ["S1"], "passed": True}
        ]
    )
    result_invalid_scene = validator.validate(prev_invalid_scene, curr_invalid_scene)
    assert result_invalid_scene.valid is True
    # 両方とも空（または空文字列）ではないので連動率は 100.0% になるはず
    assert result_invalid_scene.delta_correlation == 100.0


def test_ratchet_boundary_rate_and_empty_list():
    """境界値テスト: 項目数やPASS数などのメトリクスが 0 から 1 に変化する境界条件"""
    validator = RatchetValidator()
    
    # prev が空、curr に 1件 (passed=False) -> 充足率 0%
    prev_empty = UXVerificationSnapshot(version="v1.0.0", items=[])
    curr_one_fail = UXVerificationSnapshot(
        version="v1.0.1",
        items=[{"id": "item1", "ux_story": "O-2", "layer": 1, "passed": False}]
    )
    result1 = validator.validate(prev_empty, curr_one_fail)
    assert result1.valid is True
    assert "充足率:      0.0% → 0.0%" in result1.report
    assert "O-2: 0/1 (0%)" in result1.report

    # prev が空、curr に 1件 (passed=True) -> 充足率 100%
    curr_one_pass = UXVerificationSnapshot(
        version="v1.0.1",
        items=[{"id": "item1", "ux_story": "O-2", "layer": 1, "passed": True}]
    )
    result2 = validator.validate(prev_empty, curr_one_pass)
    assert result2.valid is True
    assert "充足率:      0.0% → 100.0%" in result2.report
    assert "O-2" not in result2.report.split("システム適合度ギャップ:")[1] # 100% なのでギャップリストに含まれない

    # story_scene が 空文字列 vs 非空文字列
    curr_scene_empty = UXVerificationSnapshot(
        version="v1.0.1",
        items=[{"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": ""}]
    )
    result3 = validator.validate(prev_empty, curr_scene_empty)
    assert result3.delta_correlation == 0.0

    curr_scene_filled = UXVerificationSnapshot(
        version="v1.0.1",
        items=[{"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": " "}] # スペース1文字でも非空なので連動する
    )
    result4 = validator.validate(prev_empty, curr_scene_filled)
    assert result4.delta_correlation == 100.0


def test_ratchet_invalid_metrics_types():
    """極端な数値型や不正な型が設定された場合の挙動をテスト"""
    validator = RatchetValidator()
    prev = UXVerificationSnapshot(version="v1.0.0", items=[])
    curr = UXVerificationSnapshot(version="v1.0.1", items=[])
    
    # 巨大な整数
    prev.total_items = 10**18
    curr.total_items = 10**18 + 1
    
    # 無限大やNaN
    prev.correlation_rate = float('inf')
    curr.correlation_rate = float('inf')
    
    prev.pass_items = -100
    curr.pass_items = -99
    
    violations = []
    
    # 巨大整数での減少なし
    validator._collect_total_items_violations(prev, curr, violations)
    assert len(violations) == 0
    
    # 巨大整数での減少あり
    curr.total_items = 10**18 - 1
    validator._collect_total_items_violations(prev, curr, violations)
    assert len(violations) == 1
    assert violations[0].delta == -1
    
    # NaNや無限大の比較
    violations_nan = []
    prev.correlation_rate = float('nan')
    curr.correlation_rate = float('nan')
    # NaN < NaN は Python では False になるため、違反は検出されない
    validator._collect_correlation_rate_violations(prev, curr, violations_nan)
    assert len(violations_nan) == 0


def test_ratchet_gap_report_custom_object_layer():
    """layerに独自オブジェクトが渡された場合の挙動をテスト"""
    class CustomLayer:
        def __str__(self):
            return "CustomLayerName"
            
    validator = RatchetValidator()
    prev = UXVerificationSnapshot(version="v1.0.0", items=[])
    curr = UXVerificationSnapshot(
        version="v1.0.1",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": CustomLayer(), "passed": False}
        ]
    )
    prev.compute_aggregates()
    curr.compute_aggregates()
    
    report = validator._generate_report(prev, curr)
    assert "LCustomLayerName層で1件未PASS" in report


def test_ratchet_result_empty_violations_str():
    """違反がない（空リスト）またはNoneの場合の文字列表現の頑健性をテスト"""
    res = RatchetResult(valid=False, violations=[])
    # violationsが空リストのときにFAIL表示がクラッシュしないか
    assert "❌ ラチェット検証FAIL: 0件の違反" in str(res)
    
    # Noneの場合（Pythonのデフォルト引数により通常はリストだが、強制的にNoneを代入した場合）
    res_none = RatchetResult(valid=False, violations=None)
    with pytest.raises(TypeError):
        # len(None)でTypeErrorが発生することを確認
        _ = str(res_none)


def test_ratchet_extreme_edges_additional():
    validator = RatchetValidator()
    
    # 1. 不正型: previous, current に UXVerificationSnapshot 以外のオブジェクト (例: dict) を渡した場合
    #    この場合は AttributeError が発生するはず
    with pytest.raises(AttributeError):
        validator.validate({"version": "v1.0.0"}, {"version": "v1.0.1"})

    # 2. 不正型: delta_correlation に非数値 (str) を指定した場合の __str__
    #    ValueError が発生することを確認
    res = RatchetResult(valid=True, delta_correlation="invalid_type")
    with pytest.raises(ValueError):
        _ = str(res)

    # 3. 巨大入力: 非常に多くのアイテムがある場合 (1万件) の動作
    large_items = [{"id": f"item_{i}", "ux_story": "O-2", "layer": i % 10, "passed": True} for i in range(1000)]
    prev_large = UXVerificationSnapshot(version="v1.0.0", items=large_items)
    curr_large = UXVerificationSnapshot(version="v1.0.1", items=large_items + [{"id": "new_item", "ux_story": "O-2", "layer": 0, "passed": True}])
    
    result = validator.validate(prev_large, curr_large)
    assert result.valid is True
    assert result.delta_items == 1
    assert result.delta_pass == 1

    # 4. 特殊文字・絵文字・制御文字を大量に含むバージョン・ストーリー名の挙動
    special_str = "\x00\x01\n\r\t🔥🚀🌟" * 10
    prev_special = UXVerificationSnapshot(version=special_str, items=[])
    curr_special = UXVerificationSnapshot(
        version="v1.0.1", 
        items=[{"id": "item1", "ux_story": special_str, "layer": special_str, "passed": False}]
    )
    result_special = validator.validate(prev_special, curr_special)
    assert result_special.valid is True
    assert special_str in result_special.report









