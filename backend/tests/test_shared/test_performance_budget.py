"""
M4.4 Sprint 4.4.1 + 4.4.2: PerformanceBudgetManager テスト (PB-T01〜T16)

設計書: sprint_44_performance_budget_design.md (conv_55dad40a)
対象: services/performance_budget_manager.py
Sprint 4.4.1: PB-T01〜T08 (基盤テスト + 弱点分析 + 深掘りレビュー)
Sprint 4.4.2: PB-T09〜T12 (Degradation制御) + PB-T13〜T16 (Dashboard API)
"""
import json
import pytest
from pathlib import Path

from services.performance_budget_manager import (
    PerformanceBudgetManager,
    PerformanceBudgetReport,
    WorkerPerformance,
    DEFAULT_WORKER_BUDGETS,
    DEFAULT_TOTAL_BUDGET,
)


@pytest.fixture
def perf_manager(tmp_path):
    """一時ディレクトリを使うPerformanceBudgetManager"""
    return PerformanceBudgetManager(output_dir=tmp_path / "perf")


@pytest.fixture
def budget_json(tmp_path):
    """カスタムバジェットJSONファイル"""
    budget_file = tmp_path / "custom_budget.json"
    budget_file.write_text(json.dumps({
        "schema_version": "1.0",
        "total_budget_seconds": 300,
        "worker_budgets": {
            "文字起こし": {"budget_seconds": 80, "priority": "critical"},
            "AI校閲": {"budget_seconds": 40, "priority": "critical"},
            "品質チェック": {"budget_seconds": 20, "priority": "degradable"},
        },
        "degradation_rules": [
            {"worker": "品質チェック", "action": "simple_mode", "savings_percent": 50},
        ]
    }), encoding="utf-8")
    return budget_file


class TestPerformanceBudgetRecording:
    """PB-T01〜T04: Worker実行時間の記録 (PB-01)"""

    def test_record_worker_time(self, perf_manager):
        """PB-T01: record後にcurrent_sessionに記録あり"""
        perf_manager.record_worker_time("文字起こし", 45.0)
        perf_manager.record_worker_time("AI校閲", 30.0)

        assert perf_manager._current_session["文字起こし"] == 45.0
        assert perf_manager._current_session["AI校閲"] == 30.0
        assert perf_manager.get_cumulative_time() == 75.0

    def test_save_report_creates_json(self, perf_manager, tmp_path):
        """PB-T02: worker_perf_{session}.json が生成される"""
        perf_manager.record_worker_time("文字起こし", 50.0)
        report = perf_manager.generate_report("test_session_001")
        filepath = perf_manager.save_report(report)

        assert filepath.exists()
        assert filepath.name == "worker_perf_test_session_001.json"

        data = json.loads(filepath.read_text(encoding="utf-8"))
        assert data["session_id"] == "test_session_001"
        assert data["total_duration"] == 50.0

    def test_report_contains_all_workers(self, perf_manager):
        """PB-T03: レポートに記録した全Workerのエントリが含まれる"""
        workers = ["文字起こし", "AI校閲", "SmartCut構成", "プレビュー生成",
                    "YouTube最適化", "品質チェック", "最終レンダリング"]
        for i, name in enumerate(workers):
            perf_manager.record_worker_time(name, 10.0 * (i + 1))

        report = perf_manager.generate_report("full_session")
        assert len(report.workers) == 7

        worker_names = {w.worker_name for w in report.workers}
        assert worker_names == set(workers)

    def test_report_timestamp_format(self, perf_manager):
        """PB-T04: ISO 8601形式のtimestamp"""
        perf_manager.record_worker_time("文字起こし", 10.0)
        report = perf_manager.generate_report("ts_session")

        # ISO 8601形式のタイムスタンプ検証
        assert report.timestamp != ""
        assert "T" in report.timestamp  # ISO 8601にはTセパレータがある
        # パース可能か確認
        from datetime import datetime
        parsed = datetime.fromisoformat(report.timestamp)
        assert parsed.year >= 2026


class TestBudgetMonitoring:
    """PB-T05〜T08: バジェット監視 (PB-02)"""

    def test_total_budget_under_570(self, perf_manager):
        """PB-T05: 全Worker合計 < 570s → over_budget=False"""
        perf_manager.record_worker_time("文字起こし", 100.0)
        perf_manager.record_worker_time("AI校閲", 50.0)
        perf_manager.record_worker_time("SmartCut構成", 20.0)
        perf_manager.record_worker_time("プレビュー生成", 80.0)
        perf_manager.record_worker_time("YouTube最適化", 50.0)
        perf_manager.record_worker_time("品質チェック", 20.0)
        perf_manager.record_worker_time("最終レンダリング", 140.0)
        # 合計: 460s < 570s

        report = perf_manager.generate_report("under_budget")
        assert report.over_budget is False
        assert report.total_duration == 460.0
        assert report.total_budget == DEFAULT_TOTAL_BUDGET

    def test_total_budget_over_570(self, perf_manager):
        """PB-T06: 全Worker合計 > 570s → over_budget=True"""
        perf_manager.record_worker_time("文字起こし", 200.0)
        perf_manager.record_worker_time("AI校閲", 100.0)
        perf_manager.record_worker_time("SmartCut構成", 50.0)
        perf_manager.record_worker_time("プレビュー生成", 100.0)
        perf_manager.record_worker_time("最終レンダリング", 200.0)
        # 合計: 650s > 570s

        report = perf_manager.generate_report("over_budget")
        assert report.over_budget is True
        assert report.total_duration == 650.0

    def test_individual_worker_over_budget(self, perf_manager):
        """PB-T07: 単体Worker超過検出"""
        # 文字起こしのバジェットは120s
        perf_manager.record_worker_time("文字起こし", 150.0)
        assert perf_manager.check_individual_budget("文字起こし") is False

        # AI校閲のバジェットは60s
        perf_manager.record_worker_time("AI校閲", 30.0)
        assert perf_manager.check_individual_budget("AI校閲") is True

        # レポートでも超過フラグが正しい
        report = perf_manager.generate_report("individual_check")
        transcribe = next(w for w in report.workers if w.worker_name == "文字起こし")
        proofread = next(w for w in report.workers if w.worker_name == "AI校閲")
        assert transcribe.over_budget is True
        assert proofread.over_budget is False

    def test_budget_from_json(self, budget_json, tmp_path):
        """PB-T08: performance_budget.json から読込"""
        mgr = PerformanceBudgetManager(
            budget_path=budget_json,
            output_dir=tmp_path / "perf"
        )

        # カスタムバジェット値が反映されていること
        assert mgr._total_budget == 300
        assert mgr.get_worker_budget("文字起こし") == 80
        assert mgr.get_worker_budget("AI校閲") == 40

        # 記録+レポート生成
        mgr.record_worker_time("文字起こし", 90.0)  # 80sバジェット超過
        assert mgr.check_individual_budget("文字起こし") is False

        report = mgr.generate_report("json_session")
        assert report.total_budget == 300


class TestWeaknessAnalysisFixes:
    """弱点分析(m44_weakness_analysis)から導出した追加テスト"""

    def test_budget_boundary_exact_570(self, tmp_path):
        """W-01: 570秒ちょうどはover_budget=False (境界値テスト)"""
        mgr = PerformanceBudgetManager(output_dir=tmp_path / "perf")
        mgr.record_worker_time("文字起こし", 570.0)

        assert mgr.check_budget("文字起こし") is True  # ちょうどはセーフ
        report = mgr.generate_report("boundary")
        assert report.over_budget is False

    def test_duration_scaling_10min(self, tmp_path):
        """C-01: 10分動画ではバジェットが1140秒に自動スケーリング"""
        mgr = PerformanceBudgetManager(
            output_dir=tmp_path / "perf",
            video_duration_min=10.0  # 5分基準の2倍
        )
        assert mgr._total_budget == 1140.0  # 570 * 2

        # 800秒は10分動画ならセーフ (5分動画ならNG)
        mgr.record_worker_time("全Worker", 800.0)
        assert mgr.check_budget("全Worker") is True

    def test_quality_check_is_critical(self, tmp_path):
        """D-01/D-02: 品質チェックはcriticalであり、degradation対象にならない"""
        mgr = PerformanceBudgetManager(output_dir=tmp_path / "perf")

        # 80%超過の状態を作る (570 * 0.8 = 456)
        mgr.record_worker_time("文字起こし", 300.0)
        mgr.record_worker_time("AI校閲", 200.0)
        # 累積500 > 456(80%ライン)

        targets = mgr.get_degradation_targets()
        # 品質チェックはcriticalなのでdegradation対象に含まれない
        assert "品質チェック" not in targets
        # degradableなWorkerのみが対象
        for t in targets:
            entry = mgr._worker_budgets.get(t, {})
            assert entry.get("priority") == "degradable"

    def test_progress_snapshot(self, tmp_path):
        """C-02: WebSocket連携用の進捗スナップショットが正しく生成される"""
        mgr = PerformanceBudgetManager(output_dir=tmp_path / "perf")
        mgr.record_worker_time("文字起こし", 100.0)
        mgr.record_worker_time("AI校閲", 50.0)

        snap = mgr.get_progress_snapshot()
        assert snap["type"] == "performance_budget_progress"
        assert snap["cumulative_seconds"] == 150.0
        assert snap["total_budget_seconds"] == 570.0
        assert snap["remaining_seconds"] == 420.0
        assert snap["workers_completed"] == 2
        assert snap["workers_total"] == 7
        assert snap["over_budget"] is False
        assert 0 < snap["consumption_ratio"] < 1

        # total_budget が 0 の場合 (カバレッジ補完)
        mgr._total_budget = 0.0
        snap_zero = mgr.get_progress_snapshot()
        assert snap_zero["consumption_ratio"] == 0


class TestDeepReviewFixes:
    """深掘りレビュー(m44_deep_review)から導出したバグ修正テスト"""

    def test_retry_accumulates_time(self, tmp_path):
        """BUG-01: リトライ時にrecord_worker_timeが累積加算される"""
        mgr = PerformanceBudgetManager(output_dir=tmp_path / "perf")

        # 1回目: 45秒で失敗
        mgr.record_worker_time("文字起こし", 45.0)
        assert mgr._current_session["文字起こし"] == 45.0

        # 2回目: 50秒で成功 → 累積95秒
        mgr.record_worker_time("文字起こし", 50.0)
        assert mgr._current_session["文字起こし"] == 95.0  # 上書きなら50.0になるはず

        # 累積時間も正確
        assert mgr.get_cumulative_time() == 95.0

        # レポートでも累積が反映
        report = mgr.generate_report("retry_test")
        w = next(w for w in report.workers if w.worker_name == "文字起こし")
        assert w.duration_seconds == 95.0

    def test_critical_priority_protected(self, tmp_path):
        """EDGE-03: update_budget_configで品質チェックのpriorityは変更不可"""
        mgr = PerformanceBudgetManager(output_dir=tmp_path / "perf")

        # 品質チェックのpriority変更を試行
        mgr.update_budget_config({
            "worker_budgets": {
                "品質チェック": {"priority": "degradable", "budget_seconds": 60}
            }
        })

        # priorityは変更されない (critical のまま)
        assert mgr._worker_budgets["品質チェック"]["priority"] == "critical"
        # budget_secondsは変更される (priority以外は更新可能)
        assert mgr._worker_budgets["品質チェック"]["budget_seconds"] == 60

    def test_critical_priority_protected_all(self, tmp_path):
        """EDGE-03: 文字起こし・最終レンダリングもprotected"""
        mgr = PerformanceBudgetManager(output_dir=tmp_path / "perf")

        for worker_name in ["文字起こし", "最終レンダリング"]:
            mgr.update_budget_config({
                "worker_budgets": {
                    worker_name: {"priority": "degradable"}
                }
            })
            assert mgr._worker_budgets[worker_name]["priority"] == "critical"

    def test_degradable_priority_can_be_changed(self, tmp_path):
        """EDGE-03: degradable Workerのpriorityは変更可能"""
        mgr = PerformanceBudgetManager(output_dir=tmp_path / "perf")

        mgr.update_budget_config({
            "worker_budgets": {
                "プレビュー生成": {"priority": "critical"}
            }
        })
        # プレビュー生成はprotectedリストにないので変更可能
        assert mgr._worker_budgets["プレビュー生成"]["priority"] == "critical"


class TestDegradationControl:
    """PB-T09〜T12: Degradation制御テスト (Sprint 4.4.2)

    設計書: sprint_442_implementation_prompt
    対象: get_degradation_targets() の動作検証
    """

    def test_degradation_targets_identified(self, tmp_path):
        """PB-T09: 累積 > 80%バジェット時にdegradableリスト返却"""
        mgr = PerformanceBudgetManager(output_dir=tmp_path / "perf")
        # 80%ライン = 570 * 0.8 = 456秒
        # 累積500秒 > 456秒 → degradation発動
        mgr.record_worker_time("文字起こし", 300.0)
        mgr.record_worker_time("AI校閲", 200.0)

        targets = mgr.get_degradation_targets()
        assert len(targets) > 0, "80%超過時にdegradationターゲットが空であってはならない"
        # degradableなWorkerのみが返る
        for t in targets:
            entry = mgr._worker_budgets.get(t, {})
            assert entry.get("priority") == "degradable", f"{t} はdegradableであるべき"

    def test_degradation_not_triggered_under_budget(self, tmp_path):
        """PB-T10: 予算内ではdegradation空リスト"""
        mgr = PerformanceBudgetManager(output_dir=tmp_path / "perf")
        # 80%ライン = 456秒。累積200秒はそれ以下
        mgr.record_worker_time("文字起こし", 100.0)
        mgr.record_worker_time("AI校閲", 100.0)

        targets = mgr.get_degradation_targets()
        assert targets == [], f"予算内で返されたターゲット: {targets}"

    def test_degradation_priority_order(self, tmp_path):
        """PB-T11: degradable優先順 = YouTube最適化→プレビュー生成 (2段階)

        MASTER定義「品質→YT→プレビュー」から品質チェックを除外済み(D-01/D-02修正)
        DEFAULT_DEGRADATION_RULES の順序が反映されることを検証。
        """
        mgr = PerformanceBudgetManager(output_dir=tmp_path / "perf")
        # 80%超過状態を作る
        mgr.record_worker_time("文字起こし", 300.0)
        mgr.record_worker_time("AI校閲", 200.0)

        targets = mgr.get_degradation_targets()
        assert len(targets) == 2, f"degradableは2件のはず: {targets}"
        assert targets[0] == "YouTube最適化", f"1番目はYouTube最適化のはず: {targets[0]}"
        assert targets[1] == "プレビュー生成", f"2番目はプレビュー生成のはず: {targets[1]}"

    def test_critical_workers_never_degraded(self, tmp_path):
        """PB-T12: critical Worker（品質チェック含む）はdegradeされない

        EDGE-03のPROTECTED_CRITICAL_WORKERSとの連動を検証。
        全criticalWorkerがdegradationターゲットに含まれないことを確認。
        """
        mgr = PerformanceBudgetManager(output_dir=tmp_path / "perf")
        # 大幅超過状態 (570 * 0.8 = 456を超える)
        mgr.record_worker_time("全Worker", 600.0)

        targets = mgr.get_degradation_targets()
        # criticalなWorker名を列挙
        critical_workers = [
            name for name, entry in mgr._worker_budgets.items()
            if isinstance(entry, dict) and entry.get("priority") == "critical"
        ]
        assert len(critical_workers) >= 5, f"critical Workerが5件未満: {critical_workers}"

        for cw in critical_workers:
            assert cw not in targets, f"critical Worker '{cw}' がdegradationターゲットに含まれている"

        # 品質チェックは特にEDGE-03で保護されているため明示的に検証
        assert "品質チェック" not in targets
        assert "文字起こし" not in targets
        assert "最終レンダリング" not in targets


class TestDashboardAPI:
    """PB-T13〜T16: Dashboard APIテスト (Sprint 4.4.2)

    設計書: sprint_442_implementation_prompt
    対象: /api/admin/performance/* エンドポイント
    """

    @pytest.fixture(autouse=True)
    def setup_client(self, tmp_path):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        import importlib
        from unittest.mock import patch

        # admin_setup_router モジュールを明示的にロード
        admin_module = importlib.import_module("routers.admin_setup_router")

        # テスト用のPerformanceBudgetManagerを作成
        mgr = PerformanceBudgetManager(output_dir=tmp_path / "perf")
        # テスト用にいくつかWorker時間を記録
        mgr.record_worker_time("文字起こし", 45.0)
        mgr.record_worker_time("AI校閲", 30.0)

        # レポートを1件保存しておく(history用)
        report = mgr.generate_report("test_session_api")
        mgr.save_report(report)

        # _perf_manager をモジュールレベルで差し替え
        self._patcher = patch.object(admin_module, "_perf_manager", mgr)
        self._patcher.start()

        app = FastAPI()
        app.include_router(admin_module.router)
        app.include_router(admin_module.perf_router)
        self.client = TestClient(app)
        self.mgr = mgr

        yield

        # teardown: patchを解除
        self._patcher.stop()

    def test_api_performance_current(self):
        """PB-T13: GET /api/admin/performance/current → 200 + snapshot形式"""
        r = self.client.get("/api/admin/performance/current")
        assert r.status_code == 200
        data = r.json()

        # snapshot形式の必須フィールドを検証
        assert data["type"] == "performance_budget_progress"
        assert "cumulative_seconds" in data
        assert "total_budget_seconds" in data
        assert "consumption_ratio" in data
        assert "remaining_seconds" in data
        assert "workers_completed" in data
        assert "workers_total" in data
        assert "over_budget" in data

        # テストで記録した値が反映されていること
        assert data["cumulative_seconds"] == 75.0  # 45 + 30
        assert data["workers_completed"] == 2

    def test_api_performance_history(self):
        """PB-T14: GET /api/admin/performance/history → 200 + list[report]"""
        r = self.client.get("/api/admin/performance/history")
        assert r.status_code == 200
        data = r.json()

        assert isinstance(data, list)
        assert len(data) >= 1, "少なくとも1件のレポートが存在するはず"

        # レポート形式の検証
        report = data[0]
        assert "session_id" in report
        assert "total_duration" in report
        assert "total_budget" in report
        assert "over_budget" in report
        assert "workers" in report

    def test_api_performance_budget_get(self):
        """PB-T15: GET /api/admin/performance/budget → budget定義JSON"""
        r = self.client.get("/api/admin/performance/budget")
        assert r.status_code == 200
        data = r.json()

        # get_budget_config()の形式を検証
        assert "total_budget_seconds" in data
        assert "worker_budgets" in data
        assert "degradation_rules" in data
        assert "threshold_ratio" in data
        assert data["threshold_ratio"] == 0.8

    def test_api_performance_budget_update(self):
        """PB-T16: PUT /api/admin/performance/budget → 更新成功 + priority保護確認"""
        # 正常な更新
        r = self.client.put("/api/admin/performance/budget", json={
            "total_budget_seconds": 600,
            "worker_budgets": {
                "AI校閲": {"budget_seconds": 90}
            }
        })
        assert r.status_code == 200
        data = r.json()
        assert data["total_budget_seconds"] == 600
        assert data["worker_budgets"]["AI校閲"]["budget_seconds"] == 90

        # EDGE-03: critical Workerのpriority変更試行
        r2 = self.client.put("/api/admin/performance/budget", json={
            "worker_budgets": {
                "品質チェック": {"priority": "degradable", "budget_seconds": 50}
            }
        })
        assert r2.status_code == 200
        data2 = r2.json()
        # priority は変更されない (critical のまま)
        assert data2["worker_budgets"]["品質チェック"]["priority"] == "critical"
        # budget_seconds は変更される
        assert data2["worker_budgets"]["品質チェック"]["budget_seconds"] == 50


class TestPerformanceBudgetRobustness:
    """カオス耐性とロバストネス向上の検証テスト (例外ハンドリング、パストラバーサル、無効値のフォールバック)"""

    def test_load_budgets_with_invalid_json_format(self, tmp_path):
        """不正なJSON（辞書ではないリスト型や、構文エラーのJSON）を指定した際に、クラッシュせずデフォルトにフォールバックすること"""
        # リスト型の不正なJSON
        bad_json = tmp_path / "invalid_budget1.json"
        bad_json.write_text('["not", "a", "dict"]', encoding="utf-8")
        mgr1 = PerformanceBudgetManager(budget_path=bad_json)
        assert mgr1._total_budget == DEFAULT_TOTAL_BUDGET
        assert mgr1.get_worker_budget("文字起こし") == 120

        # 構文エラーのあるJSON
        bad_json2 = tmp_path / "invalid_budget2.json"
        bad_json2.write_text('{invalid_json: true}', encoding="utf-8")
        mgr2 = PerformanceBudgetManager(budget_path=bad_json2)
        assert mgr2._total_budget == DEFAULT_TOTAL_BUDGET

    def test_init_with_invalid_video_duration(self, tmp_path):
        """video_duration_min に負数、ゼロ、None、非数値型を渡した場合に安全にデフォルトのバジェット（スケーリングなし）になること"""
        # 負数の場合
        mgr_neg = PerformanceBudgetManager(output_dir=tmp_path / "perf", video_duration_min=-5.0)
        assert mgr_neg._total_budget == DEFAULT_TOTAL_BUDGET

        # ゼロの場合
        mgr_zero = PerformanceBudgetManager(output_dir=tmp_path / "perf", video_duration_min=0.0)
        assert mgr_zero._total_budget == DEFAULT_TOTAL_BUDGET

        # 非数値型（文字列）の場合
        mgr_str = PerformanceBudgetManager(output_dir=tmp_path / "perf", video_duration_min="invalid_duration")
        assert mgr_str._total_budget == DEFAULT_TOTAL_BUDGET

        # Noneの場合
        mgr_none = PerformanceBudgetManager(output_dir=tmp_path / "perf", video_duration_min=None)
        assert mgr_none._total_budget == DEFAULT_TOTAL_BUDGET

    def test_record_time_with_invalid_duration(self, perf_manager):
        """record_worker_time に NaN, inf, 負数, None, 文字列などの無効値を渡してもクラッシュせず 0.0 として処理されること"""
        import math

        # NaN の場合
        perf_manager.record_worker_time("文字起こし", float('nan'))
        assert perf_manager._current_session["文字起こし"] == 0.0

        # 無限大の場合
        perf_manager.record_worker_time("AI校閲", float('inf'))
        assert perf_manager._current_session["AI校閲"] == 0.0

        # 負数の場合
        perf_manager.record_worker_time("SmartCut構成", -30.0)
        assert perf_manager._current_session["SmartCut構成"] == 0.0

        # Noneの場合
        perf_manager.record_worker_time("プレビュー生成", None)
        assert perf_manager._current_session["プレビュー生成"] == 0.0

        # 文字列の場合
        perf_manager.record_worker_time("YouTube最適化", "invalid_time")
        assert perf_manager._current_session["YouTube最適化"] == 0.0

    def test_save_report_path_traversal_protection(self, perf_manager, tmp_path):
        """session_id に ../ などの危険な文字列を渡しても、パストラバーサルが発生せず安全なファイル名で出力されること"""
        perf_manager.record_worker_time("文字起こし", 10.0)
        report = perf_manager.generate_report("../../../traversal_session")
        filepath = perf_manager.save_report(report)

        # パスが output_dir 内に平滑化されて保存されていることを検証
        assert filepath.parent.resolve() == perf_manager._output_dir.resolve()
        assert "traversal_session" in filepath.name
        assert ".." not in filepath.name

    def test_save_report_io_error_fallback(self, perf_manager, monkeypatch):
        """レポート保存時に OSError が発生した際、代替フォルダ（一時ディレクトリ）に安全に保存されること"""
        from pathlib import Path
        
        original_mkdir = Path.mkdir
        
        # 最初の保存処理で出力先フォルダ作成またはファイル書き込み時に OSError を発生させるようモック
        # ただし、fallback先の一時ディレクトリのmkdirは通す
        def mock_mkdir(self_obj, *args, **kwargs):
            if "performance_fallback" in str(self_obj):
                return original_mkdir(self_obj, *args, **kwargs)
            raise OSError("Mock disk full / permission error")

        monkeypatch.setattr(Path, "mkdir", mock_mkdir)

        perf_manager.record_worker_time("文字起こし", 10.0)
        report = perf_manager.generate_report("fallback_test_session")
        
        # 保存を試行すると、最初の mkdir が OSError になり、一時ディレクトリにフォールバックして成功するはず
        filepath = perf_manager.save_report(report)
        assert filepath.exists()
        assert "fallback" in str(filepath.parent).lower()

    def test_get_history_concurrent_deletion(self, perf_manager, monkeypatch):
        """get_history の走査処理中にファイルが削除された場合でも、エラーでクラッシュせずに処理を続行できること"""
        perf_manager.record_worker_time("文字起こし", 10.0)
        
        # 2つのセッションを作成してレポート保存
        report1 = perf_manager.generate_report("session_a")
        report2 = perf_manager.generate_report("session_b")
        p1 = perf_manager.save_report(report1)
        p2 = perf_manager.save_report(report2)

        # glob 取得後に unlink されるカオスシナリオをシミュレート
        import builtins
        original_open = builtins.open
        
        def mock_open(file, *args, **kwargs):
            if str(p1) in str(file):
                raise FileNotFoundError("Mock deleted file")
            return original_open(file, *args, **kwargs)

        with monkeypatch.context() as m:
            m.setattr(builtins, "open", mock_open)
            if p1.exists():
                p1.unlink()
            history = perf_manager.get_history()
            
            # session_a (削除された) はスキップされ、session_b のみ取得されること
            assert len(history) == 1
            assert history[0]["session_id"] == "session_b"

    def test_update_budget_config_with_invalid_types(self, perf_manager):
        """update_budget_config に無効な値（文字列、負数、Noneなど）を渡した際に、安全に無視またはエラー回避すること"""
        # total_budget_seconds に無効な文字列を渡した場合
        perf_manager.update_budget_config({"total_budget_seconds": "invalid_value"})
        assert perf_manager._total_budget == DEFAULT_TOTAL_BUDGET

        # total_budget_seconds に負数を渡した場合
        perf_manager.update_budget_config({"total_budget_seconds": -100.0})
        assert perf_manager._total_budget == DEFAULT_TOTAL_BUDGET

        # updates 自体が辞書ではない場合
        perf_manager.update_budget_config("not_a_dict")
        assert perf_manager._total_budget == DEFAULT_TOTAL_BUDGET

        # worker_budgets が辞書ではない場合
        perf_manager.update_budget_config({"worker_budgets": "not_a_dict"})
        assert perf_manager.get_worker_budget("文字起こし") == 120

    def test_load_budgets_config_not_dict(self, monkeypatch):
        """_load_budgetsが辞書以外を返した場合の config 初期化"""
        monkeypatch.setattr(PerformanceBudgetManager, "_load_budgets", lambda self: None)
        mgr = PerformanceBudgetManager()
        assert mgr._config == {}

    def test_worker_budgets_invalid_values(self, tmp_path):
        """worker_budgets内の無効な値に対するフォールバック検証"""
        budget_file = tmp_path / "invalid_worker_budgets.json"
        
        budget_file.write_text(json.dumps({
            "worker_budgets": {
                "文字起こし": {"budget_seconds": -10.0, "priority": "invalid_priority"},
                "AI校閲": {"budget_seconds": "invalid_sec"},
                "SmartCut構成": -5.0,
                "プレビュー生成": "invalid_val"
            }
        }), encoding="utf-8")
        
        mgr = PerformanceBudgetManager(budget_path=budget_file)
        
        # 文字起こし: budget_seconds < 0 -> 0.0, priority はデフォルト（critical）
        assert mgr._worker_budgets["文字起こし"]["budget_seconds"] == 0.0
        assert mgr._worker_budgets["文字起こし"]["priority"] == "critical"
        
        # AI校閲: 例外キャッチ -> デフォルト
        assert mgr._worker_budgets["AI校閲"]["budget_seconds"] == 60.0
        assert mgr._worker_budgets["AI校閲"]["priority"] == "critical"
        
        # SmartCut構成: 値が辞書ではなく数値かつ負数 -> 0.0
        assert mgr._worker_budgets["SmartCut構成"]["budget_seconds"] == 0.0
        assert mgr._worker_budgets["SmartCut構成"]["priority"] == "critical"
        
        # プレビュー生成: 値が辞書ではなく非数値 -> デフォルト
        assert mgr._worker_budgets["プレビュー生成"]["budget_seconds"] == 90.0
        assert mgr._worker_budgets["プレビュー生成"]["priority"] == "degradable"

    def test_total_budget_and_ref_duration_invalid(self, tmp_path):
        """total_budget_seconds と reference_duration_minutes が0以下や無効値の場合のフォールバック"""
        budget_file = tmp_path / "invalid_total_budget.json"
        budget_file.write_text(json.dumps({
            "total_budget_seconds": -50,
            "reference_duration_minutes": "invalid"
        }), encoding="utf-8")
        
        mgr = PerformanceBudgetManager(budget_path=budget_file)
        assert mgr._total_budget == DEFAULT_TOTAL_BUDGET

        budget_file2 = tmp_path / "invalid_total_budget2.json"
        budget_file2.write_text(json.dumps({
            "total_budget_seconds": "invalid",
            "reference_duration_minutes": -10
        }), encoding="utf-8")
        
        mgr2 = PerformanceBudgetManager(budget_path=budget_file2)
        assert mgr2._total_budget == DEFAULT_TOTAL_BUDGET

    def test_degradation_rules_invalid(self, tmp_path):
        """degradation_rules が無効な場合のフォールバック"""
        budget_file = tmp_path / "invalid_degradation_rules.json"
        budget_file.write_text(json.dumps({
            "degradation_rules": [
                {"worker": "YouTube最適化", "action": "cache_first", "savings_percent": "invalid_savings"}
            ]
        }), encoding="utf-8")
        
        mgr = PerformanceBudgetManager(budget_path=budget_file)
        assert len(mgr._degradation_rules) == 2
        assert mgr._degradation_rules[0]["worker"] == "YouTube最適化"

    def test_record_worker_time_empty_name(self, perf_manager):
        """worker_name が空の場合に早期リターンすること"""
        perf_manager.record_worker_time("", 10.0)
        perf_manager.record_worker_time(None, 10.0)
        assert len(perf_manager._current_session) == 0

    def test_get_worker_budget_exceptions(self, perf_manager):
        """get_worker_budget の例外ハンドリング"""
        perf_manager._worker_budgets["テスト"] = {"budget_seconds": "invalid_type", "priority": "critical"}
        assert perf_manager.get_worker_budget("テスト") == 0.0
        
        perf_manager._worker_budgets["テスト2"] = "invalid_type"
        assert perf_manager.get_worker_budget("テスト2") == 0.0

    def test_check_individual_budget_under_zero(self, perf_manager):
        """budget <= 0 の場合の check_individual_budget 挙動"""
        perf_manager._worker_budgets["テスト"] = {"budget_seconds": 0.0, "priority": "critical"}
        perf_manager.record_worker_time("テスト", 10.0)
        assert perf_manager.check_individual_budget("テスト") is True

    def test_degradation_targets_missing_worker_key(self, tmp_path):
        """degradation_rules 内のルールに 'worker' キーが無い場合のスキップ"""
        mgr = PerformanceBudgetManager(output_dir=tmp_path / "perf")
        # 手動でworkerキーのないルールを追加
        mgr._degradation_rules.append({"action": "some_action", "savings_percent": 30})
        mgr.record_worker_time("文字起こし", 500.0)
        targets = mgr.get_degradation_targets()
        assert "YouTube最適化" in targets
        assert len(targets) == 2

    def test_save_report_session_id_empty_fallback(self, perf_manager):
        """session_id の安全な文字列化で空になった場合の 'unknown_session' フォールバック"""
        report = perf_manager.generate_report("???")
        filepath = perf_manager.save_report(report)
        assert "unknown_session" in filepath.name

    def test_save_report_both_io_errors(self, perf_manager, monkeypatch):
        """save_report で通常先と代替先の両方で OSError が発生した場合の例外送出"""
        from pathlib import Path
        
        def mock_mkdir(self_obj, *args, **kwargs):
            raise OSError("Mock disk failure")

        monkeypatch.setattr(Path, "mkdir", mock_mkdir)

        report = perf_manager.generate_report("double_failure")
        with pytest.raises(OSError) as exc_info:
            perf_manager.save_report(report)
        assert "Failed to save performance report anywhere" in str(exc_info.value)

    def test_get_history_limit_invalid(self, perf_manager):
        """get_history の limit に負数または無効値を渡した場合のフォールバック"""
        report = perf_manager.generate_report("session_1")
        perf_manager.save_report(report)

        hist1 = perf_manager.get_history(limit=-5)
        assert len(hist1) == 1
        
        hist2 = perf_manager.get_history(limit="invalid_limit")
        assert len(hist2) == 1

    def test_get_history_dir_not_exists(self, tmp_path):
        """出力ディレクトリが存在しない場合の get_history 挙動"""
        non_existent_dir = tmp_path / "non_existent_dir"
        mgr = PerformanceBudgetManager(output_dir=non_existent_dir)
        assert mgr.get_history() == []

    def test_get_history_glob_os_error(self, perf_manager):
        """glob 走査中に OSError が発生した場合の早期リターン"""
        from unittest.mock import MagicMock
        
        mock_dir = MagicMock()
        mock_dir.exists.return_value = True
        mock_dir.glob.side_effect = OSError("Mock disk scan failure")
        
        perf_manager._output_dir = mock_dir
        assert perf_manager.get_history() == []

    def test_get_history_stat_os_error(self, perf_manager, monkeypatch):
        """p.stat().st_mtime で OSError が発生した場合のスキップ"""
        from pathlib import Path
        
        report = perf_manager.generate_report("session_stat_fail")
        perf_manager.save_report(report)
        
        original_stat = Path.stat
        def mock_stat(self_obj, *args, **kwargs):
            if "worker_perf_" in str(self_obj):
                raise FileNotFoundError("Mock file missing during stat")
            return original_stat(self_obj, *args, **kwargs)
            
        monkeypatch.setattr(Path, "stat", mock_stat)
        
        assert perf_manager.get_history() == []

    def test_get_history_json_decode_or_os_error(self, perf_manager):
        """ファイルの JSON パースエラーまたは open 時の OSError でのスキップ"""
        perf_manager.record_worker_time("文字起こし", 10.0)
        report = perf_manager.generate_report("session_ok")
        perf_manager.save_report(report)
        
        bad_json = perf_manager._output_dir / "worker_perf_bad_json.json"
        bad_json.write_text("{broken json", encoding="utf-8")
        
        history = perf_manager.get_history()
        assert len(history) == 1
        assert history[0]["session_id"] == "session_ok"

    def test_update_budget_config_invalid_types_inner(self, perf_manager):
        """update_budget_config の内部での型変換例外処理のカバー"""
        perf_manager.update_budget_config({
            "worker_budgets": {
                "AI校閲": {"budget_seconds": "invalid_budget"}
            }
        })
        assert perf_manager.get_worker_budget("AI校閲") == 60.0

        # 無効な priority の更新試行 (カバレッジ補完)
        perf_manager.update_budget_config({
            "worker_budgets": {
                "AI校閲": {"priority": "invalid_priority"}
            }
        })
        assert perf_manager._worker_budgets["AI校閲"]["priority"] == "critical"

        perf_manager.update_budget_config({
            "worker_budgets": {
                "AI校閲": "invalid_direct_value"
            }
        })
        assert perf_manager.get_worker_budget("AI校閲") == 60.0

        perf_manager.update_budget_config({
            "worker_budgets": {
                "AI校閲": 80.0
            }
        })
        assert perf_manager.get_worker_budget("AI校閲") == 80.0

    def test_reset_session(self, perf_manager):
        """reset_session の動作検証"""
        perf_manager.record_worker_time("文字起こし", 50.0)
        perf_manager._degradation_applied.append("YouTube最適化")
        
        perf_manager.reset_session()
        assert len(perf_manager._current_session) == 0
        assert len(perf_manager._degradation_applied) == 0

    def test_init_with_string_paths(self, tmp_path):
        """budget_path や output_dir に文字列型 (str) が渡された場合でも正常に動作すること"""
        budget_file = tmp_path / "str_budget.json"
        budget_file.write_text(json.dumps({
            "total_budget_seconds": 400
        }), encoding="utf-8")
        
        mgr = PerformanceBudgetManager(
            budget_path=str(budget_file),
            output_dir=str(tmp_path / "str_perf")
        )
        
        assert mgr._total_budget == 400
        
        mgr.record_worker_time("文字起こし", 50.0)
        report = mgr.generate_report("str_session")
        filepath = mgr.save_report(report)
        
        assert filepath.exists()
        assert "str_session" in filepath.name

    def test_load_budgets_unicode_decode_error(self, tmp_path):
        """_load_budgets において UnicodeDecodeError が発生した際に、クラッシュせずデフォルト値にフォールバックすること"""
        bad_file = tmp_path / "unicode_error.json"
        with open(bad_file, "wb") as f:
            f.write(b"\xff\xfe\x00\x00")
            
        mgr = PerformanceBudgetManager(budget_path=bad_file)
        assert mgr._total_budget == DEFAULT_TOTAL_BUDGET
        assert mgr.get_worker_budget("文字起こし") == 120.0

    def test_load_report_contents_unicode_decode_error(self, perf_manager):
        """get_history 時に UnicodeDecodeError となるファイルが含まれていても、クラッシュせずにそのファイルをスキップすること"""
        perf_manager.record_worker_time("文字起こし", 10.0)
        report = perf_manager.generate_report("session_ok_unicode")
        perf_manager.save_report(report)
        
        bad_json = perf_manager._output_dir / "worker_perf_bad_unicode.json"
        with open(bad_json, "wb") as f:
            f.write(b"\xff\xfe\x00\x00")
            
        history = perf_manager.get_history()
        assert len(history) == 1
        assert history[0]["session_id"] == "session_ok_unicode"

    def test_save_report_type_error_handling(self, perf_manager):
        """save_report に不正なオブジェクトが渡され AttributeError が発生した際、クラッシュせずにAttributeErrorが再送出されること"""
        bad_report = {"session_id": "bad", "total_duration": 10.0}
        with pytest.raises(AttributeError):
            perf_manager.save_report(bad_report)  # type: ignore

    def test_save_report_serialization_error_fallback(self, perf_manager):
        """save_report において JSON シリアライズエラー (TypeError) が発生した際、フォールバックの保存も失敗し、最終的な OSError が発生すること"""
        class Unserializable:
            pass

        perf_manager.record_worker_time("文字起こし", 10.0)
        report = perf_manager.generate_report("unserializable_session")
        report.workers.append(WorkerPerformance(
            worker_name="特殊Worker",
            duration_seconds=10.0,
            budget_seconds=30.0,
            over_budget=False
        ))
        report.workers[0].worker_name = Unserializable()  # type: ignore

        with pytest.raises(OSError) as exc_info:
            perf_manager.save_report(report)
        assert "Failed to save performance report anywhere" in str(exc_info.value)
