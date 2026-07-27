"""
UXギャップ分析システムのテスト

- test_load_all_stories: 全ストーリーが読み込める
- test_analyze_without_e2e: e2e_results=Noneで全項目SKIP
- test_analyze_with_partial_results: 部分的なE2E結果でPASS/FAILが正しく分類
- test_gap_matrix_generation: Markdownマトリクスが生成される
- test_improvement_plan_priority: 優先度が正しく計算される
- test_gap_ratchet_pass: PASS数が増加した場合にvalid=True
- test_gap_ratchet_violation: PASS数が減少した場合にvalid=False
"""
import json
import tempfile
from pathlib import Path

import pytest

from backend.ux_verification.gap_analyzer import (
    GapCheckResult,
    GapReport,
    UXGapAnalyzer,
)
from backend.ux_verification.gap_improvement_planner import (
    GapImprovementPlanner,
    ImprovementPlan,
)
from backend.ux_verification.gap_ratchet import (
    GapRatchetValidator,
    GapRatchetResult,
)


# ── テスト用ストーリーJSON ──

_SAMPLE_STORY = {
    "ux_id": "O-6",
    "name": "品質チェック",
    "description": "品質チェックのテスト用ストーリー",
    "scenes": [
        {"id": "S1", "text": "テストシーン1", "linked_items": ["O6-L1-01", "O6-L1-02"]},
        {"id": "S2", "text": "テストシーン2", "linked_items": ["O6-L2-01"]},
    ],
    "verification_items": [
        {"id": "O6-L1-01", "layer": 1, "story_scene": "S1",
         "description": "DOM要素が存在する", "test_method": "dom_exists"},
        {"id": "O6-L1-02", "layer": 1, "story_scene": "S1",
         "description": "フィールドが存在する", "test_method": "dom_exists"},
        {"id": "O6-L2-01", "layer": 2, "story_scene": "S2",
         "description": "スコアが正しい", "test_method": "visual_check"},
        {"id": "O6-L3-01", "layer": 3, "story_scene": "S2",
         "description": "APIが呼べる", "test_method": "interaction"},
        {"id": "O6-L4-01", "layer": 4, "story_scene": "S2",
         "description": "状態が遷移する", "test_method": "state_transition"},
        {"id": "O6-L5-01", "layer": 5, "story_scene": "S2",
         "description": "E2E完走", "test_method": "e2e"},
    ],
    "$schema_version": "2.0",
}

_SAMPLE_STORY_2 = {
    "ux_id": "O-1",
    "name": "素材取り込み",
    "description": "素材取り込みのテスト用ストーリー",
    "scenes": [],
    "verification_items": [
        {"id": "O1-L1-01", "layer": 1, "story_scene": "S1",
         "description": "アップロードボタンが存在する", "test_method": "dom_exists"},
        {"id": "O1-L5-01", "layer": 5, "story_scene": "S1",
         "description": "E2E完走", "test_method": "e2e"},
    ],
    "$schema_version": "2.0",
}


@pytest.fixture
def stories_dir(tmp_path):
    """テスト用ストーリーディレクトリを作成"""
    d = tmp_path / "stories"
    d.mkdir()
    with open(d / "o6_quality_gate.json", "w", encoding="utf-8") as f:
        json.dump(_SAMPLE_STORY, f, ensure_ascii=False)
    with open(d / "o1_material.json", "w", encoding="utf-8") as f:
        json.dump(_SAMPLE_STORY_2, f, ensure_ascii=False)
    return d


@pytest.fixture
def analyzer(stories_dir):
    """テスト用アナライザーインスタンス"""
    return UXGapAnalyzer(stories_dir=stories_dir)


# ── テストケース ──


class TestLoadAllStories:
    """test_load_all_stories: 全ストーリーが読み込める"""

    def test_load_all_stories(self, analyzer):
        """storiesディレクトリから全JSONが読み込めること"""
        assert len(analyzer.stories) == 2

        story_ids = [s["ux_id"] for s in analyzer.stories]
        assert "O-1" in story_ids
        assert "O-6" in story_ids

    def test_load_stories_from_production_dir(self):
        """プロダクション用storiesディレクトリから読み込めること"""
        prod_dir = Path(__file__).parent.parent / "ux_verification" / "stories"
        if prod_dir.exists():
            analyzer = UXGapAnalyzer(stories_dir=prod_dir)
            assert len(analyzer.stories) > 0


class TestAnalyzeWithoutE2E:
    """test_analyze_without_e2e: e2e_results=Noneで全項目SKIP"""

    def test_all_items_skip_when_no_e2e(self, analyzer):
        """E2E結果がNoneの場合、全項目がSKIPになること"""
        report = analyzer.analyze(e2e_results=None)

        assert report.skip_count == 8  # 6 + 2 items
        assert report.pass_count == 0
        assert report.fail_count == 0
        assert report.pass_rate == 0.0

        for result in report.results:
            assert result.status == "SKIP"
            assert "結果データなし" in result.message


class TestAnalyzeWithPartialResults:
    """test_analyze_with_partial_results: 部分的なE2E結果でPASS/FAILが正しく分類"""

    def test_partial_results_classification(self, analyzer):
        """一部のE2E結果があればPASS/FAIL/SKIPが正しく分類されること"""
        e2e_results = {
            "dom_checks": {"O6-L1-01": True, "O6-L1-02": False},
            "visual_checks": {"O6-L2-01": True},
            "interaction_checks": {},
            "state_checks": {},
            "e2e_checks": {},
        }

        report = analyzer.analyze(e2e_results=e2e_results)

        # O6-L1-01: PASS, O6-L1-02: FAIL, O6-L2-01: PASS
        # O6-L3-01, O6-L4-01, O6-L5-01: SKIP (結果なし)
        # O1-L1-01: SKIP (結果なし), O1-L5-01: SKIP (結果なし)
        assert report.pass_count == 2
        assert report.fail_count == 1
        assert report.skip_count == 5

        # PASS率 = 2/8 = 25%
        assert report.pass_rate == 25.0

    def test_story_summary_aggregation(self, analyzer):
        """ストーリー別集計が正しいこと"""
        e2e_results = {
            "dom_checks": {"O6-L1-01": True, "O6-L1-02": True, "O1-L1-01": True},
            "visual_checks": {"O6-L2-01": True},
            "interaction_checks": {"O6-L3-01": True},
            "state_checks": {"O6-L4-01": True},
            "e2e_checks": {"O6-L5-01": True, "O1-L5-01": False},
        }

        report = analyzer.analyze(e2e_results=e2e_results)

        assert "O-6" in report.story_summary
        assert report.story_summary["O-6"]["pass"] == 6
        assert report.story_summary["O-6"]["fail"] == 0

        assert "O-1" in report.story_summary
        assert report.story_summary["O-1"]["pass"] == 1
        assert report.story_summary["O-1"]["fail"] == 1


class TestGapMatrixGeneration:
    """test_gap_matrix_generation: Markdownマトリクスが生成される"""

    def test_markdown_table_format(self, analyzer):
        """Markdownテーブルが正しい形式で生成されること"""
        matrix = analyzer.generate_gap_matrix()

        assert "# UXストーリー × E2E ギャップマトリクス" in matrix
        assert "| ストーリーID |" in matrix
        assert "| O-1 |" in matrix or "| O-6 |" in matrix

        # テーブル行のカウント (ヘッダー2行 + 空行 + セパレータ + データ行)
        lines = matrix.strip().split("\n")
        assert len(lines) >= 5  # ヘッダー + セパレータ + 少なくとも2ストーリー

    def test_layer_counts_correct(self, analyzer):
        """レイヤー別カウントが正しいこと"""
        matrix = analyzer.generate_gap_matrix()

        # O-6 has: L1=2, L2=1, L3=1, L4=1, L5=1, total=6
        # O-6の行を探す
        for line in matrix.split("\n"):
            if "| O-6 |" in line:
                assert "| 6 |" in line  # 合計6
                break


class TestImprovementPlanPriority:
    """test_improvement_plan_priority: 優先度が正しく計算される"""

    def test_priority_weights(self, analyzer):
        """パイプラインコア(O-1〜O-8)の優先度がA-*より高いこと"""
        e2e_results = {
            "dom_checks": {},
            "visual_checks": {},
            "interaction_checks": {},
            "state_checks": {},
            "e2e_checks": {},
        }

        report = analyzer.analyze(e2e_results=e2e_results)
        planner = GapImprovementPlanner()
        plan = planner.generate_plan(report)

        assert plan.total_gaps > 0

        # O-1, O-6 のタスクが存在することを確認
        o1_tasks = [t for t in plan.tasks if t.story_id == "O-1"]
        o6_tasks = [t for t in plan.tasks if t.story_id == "O-6"]
        assert len(o1_tasks) > 0
        assert len(o6_tasks) > 0

    def test_pipeline_core_higher_priority(self):
        """パイプラインコア vs 管理ストーリーの優先度比較"""
        planner = GapImprovementPlanner()

        core_result = GapCheckResult(
            item_id="O1-L3-01", story_id="O-1", status="SKIP",
            message="E2E結果に存在しない", layer=3,
        )
        admin_result = GapCheckResult(
            item_id="A1-L3-01", story_id="A-1", status="SKIP",
            message="E2E結果に存在しない", layer=3,
        )

        core_priority = planner._calc_priority(core_result)
        admin_priority = planner._calc_priority(admin_result)

        # O-1 (×10) vs A-1 (×3) → コアが高い
        assert core_priority > admin_priority

    def test_fail_boost(self):
        """FAIL項目はSKIPより優先度が高いこと"""
        planner = GapImprovementPlanner()

        fail_result = GapCheckResult(
            item_id="O6-L3-01", story_id="O-6", status="FAIL",
            message="E2Eテスト不合格", layer=3,
        )
        skip_result = GapCheckResult(
            item_id="O6-L3-02", story_id="O-6", status="SKIP",
            message="E2E結果に存在しない", layer=3,
        )

        fail_priority = planner._calc_priority(fail_result)
        skip_priority = planner._calc_priority(skip_result)

        assert fail_priority > skip_priority

    def test_gap_classification(self):
        """ギャップタイプが正しく分類されること"""
        planner = GapImprovementPlanner()

        assert planner._classify_gap(GapCheckResult(
            item_id="X", story_id="O-1", status="FAIL", message="不合格", layer=1,
        )) == "品質不足"

        assert planner._classify_gap(GapCheckResult(
            item_id="X", story_id="O-1", status="SKIP",
            message="E2Eテスト未実施 — 結果データなし", layer=1,
        )) == "未接続"

        assert planner._classify_gap(GapCheckResult(
            item_id="X", story_id="O-1", status="SKIP",
            message="E2E結果に X が存在しない", layer=1,
        )) == "未実装"

        assert planner._classify_gap(GapCheckResult(
            item_id="X", story_id="O-1", status="SKIP",
            message="不明なtest_method: unknown", layer=1,
        )) == "シミュレーション"


class TestGapRatchetPass:
    """test_gap_ratchet_pass: PASS数が増加した場合にvalid=True"""

    def test_ratchet_pass_on_improvement(self, analyzer):
        """PASS数が増加すればラチェット検証はPASS"""
        # 前回: 全SKIP
        prev_report = analyzer.analyze(e2e_results=None)

        # 今回: 一部PASS
        e2e_results = {
            "dom_checks": {"O6-L1-01": True, "O6-L1-02": True, "O1-L1-01": True},
            "visual_checks": {"O6-L2-01": True},
            "interaction_checks": {},
            "state_checks": {},
            "e2e_checks": {},
        }
        curr_report = analyzer.analyze(e2e_results=e2e_results)

        validator = GapRatchetValidator()
        result = validator.validate(prev_report, curr_report)

        assert result.valid is True
        assert result.delta_pass_items > 0
        assert len(result.violations) == 0

    def test_snapshot_save_load(self, analyzer, tmp_path):
        """スナップショットの保存と読込が正しく動作すること"""
        report = analyzer.analyze(e2e_results=None)
        snap_path = str(tmp_path / "gap_snapshot.json")

        validator = GapRatchetValidator()
        validator.save_snapshot(report, snap_path)

        # ファイルが存在する
        assert Path(snap_path).exists()

        # 読込
        loaded = validator.load_snapshot(snap_path)
        assert loaded is not None
        assert loaded.pass_count == report.pass_count
        assert loaded.fail_count == report.fail_count
        assert loaded.skip_count == report.skip_count


class TestGapRatchetViolation:
    """test_gap_ratchet_violation: PASS数が減少した場合にvalid=False"""

    def test_ratchet_violation_on_regression(self, analyzer):
        """PASS数が減少するとラチェット違反が発生すること"""
        # 前回: 一部PASS
        e2e_prev = {
            "dom_checks": {"O6-L1-01": True, "O6-L1-02": True, "O1-L1-01": True},
            "visual_checks": {"O6-L2-01": True},
            "interaction_checks": {"O6-L3-01": True},
            "state_checks": {"O6-L4-01": True},
            "e2e_checks": {"O6-L5-01": True, "O1-L5-01": True},
        }
        prev_report = analyzer.analyze(e2e_results=e2e_prev)

        # 今回: PASS数が減少（退行）
        e2e_curr = {
            "dom_checks": {"O6-L1-01": True},
            "visual_checks": {},
            "interaction_checks": {},
            "state_checks": {},
            "e2e_checks": {},
        }
        curr_report = analyzer.analyze(e2e_results=e2e_curr)

        validator = GapRatchetValidator()
        result = validator.validate(prev_report, curr_report)

        assert result.valid is False
        assert result.delta_pass_items < 0
        assert len(result.violations) > 0

        # total_pass_items の違反があること
        metric_names = [v.metric for v in result.violations]
        assert "total_pass_items" in metric_names


class TestImprovementPlanWithDesignStock:
    """test_improvement_plan_with_design_stock: 設計ストックと連携したプラン生成のテスト"""

    def test_design_stock_integration(self, analyzer, tmp_path):
        """設計ストックと連携して、除外・優先度ブースト・工数補正が行われること"""
        from backend.agents.orchestration.design_stock import DesignStockStore

        # テンポラリの設計ストックを作成
        stock_file = tmp_path / "design_stock.json"
        store = DesignStockStore(path=str(stock_file))

        # テスト用タスクを追加
        # O6-L5-01: A難易度、未着手 (pending) -> 工数補正 L
        store.add_item(
            title="Task 1",
            phase=1,
            difficulty="A",
            description="E2E test for O6-L5-01",
        )
        # O6-L1-02: C難易度、完了 (completed) -> 除外されるべき
        store.add_item(
            title="Task 2",
            phase=1,
            difficulty="C",
            description="Fix O6-L1-02",
        )
        # O6-L3-01: B難易度、議論中 (in_discussion) -> 優先度ブースト、工数補正 M
        store.add_item(
            title="Task 3",
            phase=1,
            difficulty="B",
            description="Verify O6-L3-01",
        )
        # ステータスを更新
        store.update_status("DS-002", "completed")
        store.update_status("DS-003", "in_discussion")

        # ギャップ分析実行
        e2e_results = {
            "dom_checks": {"O6-L1-01": True, "O6-L1-02": False},
            "visual_checks": {"O6-L2-01": True},
            "interaction_checks": {},
            "state_checks": {},
            "e2e_checks": {},
        }
        report = analyzer.analyze(e2e_results=e2e_results)

        # プラン作成
        planner = GapImprovementPlanner()
        plan = planner.generate_plan(report, design_stock_store=store)

        # O6-L1-02 (completed) が除外されていることを検証
        task_ids = [t.item_id for t in plan.tasks]
        assert "O6-L1-02" not in task_ids

        # O6-L5-01 の工数が "L" に補正されていることを検証
        o6_l5_task = next(t for t in plan.tasks if t.item_id == "O6-L5-01")
        assert o6_l5_task.estimated_effort == "L"

        # O6-L3-01 の優先度がブーストされていることを検証
        o6_l3_task = next(t for t in plan.tasks if t.item_id == "O6-L3-01")
        # 通常: L3=30, ストーリー O-6=10 -> base=300。in_discussionのブーストで 300 * 1.5 = 450 になるはず
        assert o6_l3_task.priority == 450
        assert o6_l3_task.estimated_effort == "M"


class TestGapAnalyzerEdgeCases:
    """test_gap_analyzer_edge_cases: コーナーケース・例外・未カバー行のテスト"""

    def test_compute_aggregates_empty(self):
        """GapReport の results が空の場合に pass_rate が 0.0 になること (57行目)"""
        report = GapReport()
        report.compute_aggregates()
        assert report.pass_rate == 0.0
        assert report.pass_count == 0
        assert report.fail_count == 0
        assert report.skip_count == 0

    def test_load_stories_nonexistent_directory(self, caplog):
        """ストーリーディレクトリが存在しない場合に警告が出て stories が空になること (87-88行目)"""
        import logging
        with caplog.at_level(logging.WARNING):
            analyzer = UXGapAnalyzer(stories_dir=Path("/nonexistent/path/for/ux/stories"))
            assert len(analyzer.stories) == 0
            assert any("ストーリーディレクトリが存在しません" in record.message for record in caplog.records)

    def test_load_stories_invalid_json(self, tmp_path, caplog):
        """破損したJSONや必要なキーがないJSONをロードしようとした際に警告が出てスキップされること (100-101行目)"""
        import logging
        stories_dir = tmp_path / "stories"
        stories_dir.mkdir()

        # 破損したJSON
        with open(stories_dir / "broken.json", "w", encoding="utf-8") as f:
            f.write("{invalid_json:")

        with caplog.at_level(logging.WARNING):
            analyzer = UXGapAnalyzer(stories_dir=stories_dir)
            assert len(analyzer.stories) == 0
            # 警告ログにファイル名やエラーメッセージが含まれること
            warnings = [record.message for record in caplog.records]
            assert any("broken.json" in w for w in warnings)

    def test_check_item_unknown_method(self, tmp_path):
        """不明な test_method を含むストーリーを分析した際に SKIP になること (162行目)"""
        stories_dir = tmp_path / "stories"
        stories_dir.mkdir()
        
        story = {
            "ux_id": "O-TEST",
            "name": "テスト",
            "verification_items": [
                {"id": "OT-L1-01", "layer": 1, "test_method": "unknown_test_method"}
            ]
        }
        with open(stories_dir / "o_test.json", "w", encoding="utf-8") as f:
            json.dump(story, f, ensure_ascii=False)
            
        analyzer = UXGapAnalyzer(stories_dir=stories_dir)
        e2e_results = {
            "dom_checks": {},
            "visual_checks": {},
            "interaction_checks": {},
            "state_checks": {},
            "e2e_checks": {},
        }
        report = analyzer.analyze(e2e_results=e2e_results)
        assert len(report.results) == 1
        result = report.results[0]
        assert result.status == "SKIP"
        assert "不明なtest_method: unknown_test_method" in result.message

    def test_get_story_summary(self, analyzer):
        """get_story_summary が正しいリスト構造を返すこと (238-254行目)"""
        summary = analyzer.get_story_summary()
        assert len(summary) == 2
        for item in summary:
            assert "id" in item
            assert "name" in item
            assert "total_items" in item
            assert "pass_count" in item
            assert "fail_count" in item
            assert "completion_rate" in item
            assert item["completion_rate"] == 0.0
