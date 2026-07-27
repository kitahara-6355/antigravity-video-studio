import json
import logging
import math
from pathlib import Path
import pytest
from unittest.mock import patch

from backend.services.performance_budget_manager import (
    PerformanceBudgetManager,
    WorkerPerformance,
    PerformanceBudgetReport,
    DEFAULT_WORKER_BUDGETS,
    DEFAULT_TOTAL_BUDGET,
    DEFAULT_DEGRADATION_RULES,
)


def test_init_default(tmp_path):
    # デフォルトの引数で初期化されるかテスト
    mgr = PerformanceBudgetManager(output_dir=tmp_path)
    assert mgr._output_dir == tmp_path
    assert mgr._total_budget == DEFAULT_TOTAL_BUDGET
    assert mgr._degradation_rules == DEFAULT_DEGRADATION_RULES
    # DEFAULT_WORKER_BUDGETSが適切にパースされて読み込まれていること
    assert len(mgr._worker_budgets) == len(DEFAULT_WORKER_BUDGETS)
    assert mgr._worker_budgets["文字起こし"]["priority"] == "critical"


def test_init_with_valid_config(tmp_path):
    # 正当な設定ファイルを読み込ませるテスト
    config_data = {
        "total_budget_seconds": 300.0,
        "reference_duration_minutes": 5.0,
        "worker_budgets": {
            "文字起こし": {"budget_seconds": 100, "priority": "critical"},
            "カスタムWorker": 50.0  # 数値直指定のパースもテスト
        },
        "degradation_rules": [
            {"worker": "カスタムWorker", "action": "skip", "savings_percent": 50.0}
        ]
    }
    config_file = tmp_path / "budget_config.json"
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config_data, f)

    mgr = PerformanceBudgetManager(budget_path=config_file, output_dir=tmp_path)
    assert mgr._total_budget == 300.0
    assert mgr._worker_budgets["文字起こし"]["budget_seconds"] == 100.0
    assert mgr._worker_budgets["文字起こし"]["priority"] == "critical"
    assert mgr._worker_budgets["カスタムWorker"]["budget_seconds"] == 50.0
    assert mgr._worker_budgets["カスタムWorker"]["priority"] == "critical"  # デフォルトpriority
    assert len(mgr._degradation_rules) == 1
    assert mgr._degradation_rules[0]["worker"] == "カスタムWorker"


def test_init_with_invalid_config_structure(tmp_path, caplog):
    # 辞書ではない設定ファイル
    config_file = tmp_path / "bad_config.json"
    with open(config_file, "w", encoding="utf-8") as f:
        f.write("[1, 2, 3]")  # リスト型

    with caplog.at_level(logging.WARNING):
        mgr = PerformanceBudgetManager(budget_path=config_file, output_dir=tmp_path)
    
    assert any("バジェットファイルの構造が不正" in record.message for record in caplog.records)
    # デフォルト値にフォールバックすること
    assert mgr._total_budget == DEFAULT_TOTAL_BUDGET


def test_init_with_invalid_json(tmp_path, caplog):
    # 壊れたJSONファイル
    config_file = tmp_path / "broken.json"
    with open(config_file, "w", encoding="utf-8") as f:
        f.write("{invalid json")

    with caplog.at_level(logging.WARNING):
        mgr = PerformanceBudgetManager(budget_path=config_file, output_dir=tmp_path)
    
    assert any("バジェットファイル読込失敗" in record.message for record in caplog.records)
    assert mgr._total_budget == DEFAULT_TOTAL_BUDGET


def test_init_config_not_dict_fallback(tmp_path, monkeypatch):
    # 88行目: self._config が辞書ではない場合
    # _load_budgetsがたまたま辞書以外の不正値を返した場合の処理をテストするためにモック
    mgr_class = PerformanceBudgetManager
    monkeypatch.setattr(mgr_class, "_load_budgets", lambda self: "string_not_dict")
    mgr = mgr_class(output_dir=tmp_path)
    assert mgr._config == {}


def test_init_with_scaling(tmp_path):
    # 動画尺によるスケーリング
    # 5分で基準570秒 -> 10分なら1140秒になるべき
    mgr = PerformanceBudgetManager(output_dir=tmp_path, video_duration_min=10.0)
    assert mgr._total_budget == DEFAULT_TOTAL_BUDGET * (10.0 / 5.0)


def test_init_with_invalid_scaling(tmp_path):
    # 不正なスケーリング値（負数、非数値、None）
    mgr = PerformanceBudgetManager(output_dir=tmp_path, video_duration_min=-5.0)
    assert mgr._total_budget == DEFAULT_TOTAL_BUDGET

    mgr = PerformanceBudgetManager(output_dir=tmp_path, video_duration_min="invalid")
    assert mgr._total_budget == DEFAULT_TOTAL_BUDGET


def test_parse_float_fallback_negative_check(tmp_path):
    # 148行目: must_be_positive and val <= 0 の検証
    # total_budget_seconds が 0 や負数の場合のフォールバックテスト
    config_data = {
        "total_budget_seconds": -10.0,
        "reference_duration_minutes": 0.0,
    }
    config_file = tmp_path / "neg_budget_config.json"
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config_data, f)

    mgr = PerformanceBudgetManager(budget_path=config_file, output_dir=tmp_path)
    assert mgr._total_budget == DEFAULT_TOTAL_BUDGET


def test_degradation_rules_initialization_exceptions(tmp_path):
    # 196-197, 199行目: savings_percent が数値に変換できない場合、およびルールリストが空になる場合のフォールバックテスト
    config_data = {
        "degradation_rules": [
            {"worker": "YouTube最適化", "action": "test", "savings_percent": "invalid_percent"}
        ]
    }
    config_file = tmp_path / "deg_err_config.json"
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config_data, f)

    mgr = PerformanceBudgetManager(budget_path=config_file, output_dir=tmp_path)
    # ルールが空になり、デフォルトルールにフォールバックされること
    assert mgr._degradation_rules == DEFAULT_DEGRADATION_RULES


def test_parse_single_worker_budget_edge_cases(tmp_path):
    # 個別Workerのパースにおけるエッジケース検証
    mgr = PerformanceBudgetManager(output_dir=tmp_path)

    # 負のバジェット値
    res = mgr._parse_single_worker_budget("文字起こし", {"budget_seconds": -50, "priority": "critical"})
    assert res["budget_seconds"] == 0.0

    # 非数値のバジェット値 (TypeError/ValueError)
    res = mgr._parse_single_worker_budget("文字起こし", {"budget_seconds": "invalid", "priority": "critical"})
    assert res["budget_seconds"] == DEFAULT_WORKER_BUDGETS["文字起こし"]["budget_seconds"]

    # 不正なpriority
    res = mgr._parse_single_worker_budget("文字起こし", {"budget_seconds": 120, "priority": "invalid"})
    assert res["priority"] == "critical"


def test_record_worker_time(tmp_path, caplog):
    mgr = PerformanceBudgetManager(output_dir=tmp_path)

    # 正常系: 記録が累積されること
    mgr.record_worker_time("文字起こし", 10.0)
    assert mgr.get_cumulative_time() == 10.0
    mgr.record_worker_time("文字起こし", 15.5)
    assert mgr.get_cumulative_time() == 25.5
    assert mgr._current_session["文字起こし"] == 25.5

    # 異常系: 空のWorker名
    with caplog.at_level(logging.WARNING):
        mgr.record_worker_time("", 10.0)
    assert any("記録対象のWorker名が空" in record.message for record in caplog.records)

    # 異常系: 負のduration
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        mgr.record_worker_time("文字起こし", -5.0)
    assert any("負のduration" in record.message for record in caplog.records)
    # 累積値は変わらないはず
    assert mgr._current_session["文字起こし"] == 25.5

    # 異常系: NaN / inf のduration
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        mgr.record_worker_time("文字起こし", float('nan'))
    assert any("無効なduration" in record.message for record in caplog.records)
    
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        mgr.record_worker_time("文字起こし", float('inf'))
    assert any("無効なduration" in record.message for record in caplog.records)

    # 異常系: 非数値（文字列など）のduration
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        mgr.record_worker_time("文字起こし", "invalid_time")
    assert any("非数値のduration" in record.message for record in caplog.records)


def test_get_worker_budget_exceptions(tmp_path):
    # 260-261行目: budget_secondsが数値に変換できない場合
    mgr = PerformanceBudgetManager(output_dir=tmp_path)
    mgr._worker_budgets["テスト"] = {"budget_seconds": "not_a_number", "priority": "critical"}
    assert mgr.get_worker_budget("テスト") == 0.0


def test_check_budget(tmp_path):
    mgr = PerformanceBudgetManager(output_dir=tmp_path)
    # デフォルトのトータルバジェットは570
    mgr._total_budget = 100.0

    mgr.record_worker_time("文字起こし", 90.0)
    assert mgr.check_budget("文字起こし") is True

    mgr.record_worker_time("AI校閲", 15.0)
    assert mgr.check_budget("AI校閲") is False  # 累積が105になり超過


def test_check_individual_budget(tmp_path):
    mgr = PerformanceBudgetManager(output_dir=tmp_path)
    # 文字起こしのデフォルトバジェットは120
    mgr.record_worker_time("文字起こし", 100.0)
    assert mgr.check_individual_budget("文字起こし") is True

    mgr.record_worker_time("文字起こし", 30.0)
    assert mgr.check_individual_budget("文字起こし") is False  # 130になり超過

    # バジェットが存在しない、または0以下のworker
    mgr._worker_budgets["テスト"] = {"budget_seconds": 0.0, "priority": "critical"}
    mgr.record_worker_time("テスト", 50.0)
    assert mgr.check_individual_budget("テスト") is True


def test_get_degradation_targets(tmp_path):
    mgr = PerformanceBudgetManager(output_dir=tmp_path)
    # トータルバジェットを 100秒に設定 -> しきい値は 80秒
    mgr._total_budget = 100.0

    # 累積時間がしきい値以下 (70秒) のときは空リスト
    mgr.record_worker_time("文字起こし", 70.0)
    assert mgr.get_degradation_targets() == []

    # 累積時間がしきい値超 (85秒) のとき
    mgr.record_worker_time("文字起こし", 15.0)  # 合計85秒
    
    # degradation_rulesに定義されているのは "YouTube最適化" と "プレビュー生成"
    # これらは両方とも 'degradable' に設定されている
    targets = mgr.get_degradation_targets()
    # デフォルトルール順序で返るはず
    assert targets == ["YouTube最適化", "プレビュー生成"]

    # 途中でルール内に存在しないか、worker名が空、あるいは辞書にない場合のエッジケース
    mgr._degradation_rules.append({"worker": "", "action": "test", "savings_percent": 10})
    mgr._degradation_rules.append({"worker": "存在しないWorker", "action": "test", "savings_percent": 10})
    
    # 空名はスキップされ、存在しないWorkerは `_worker_budgets.get("存在しないWorker")` が None となり、
    # `priority` が "critical" にフォールバックされるため、targets には含まれないはず。
    targets2 = mgr.get_degradation_targets()
    assert targets2 == ["YouTube最適化", "プレビュー生成"]


def test_generate_report(tmp_path):
    mgr = PerformanceBudgetManager(output_dir=tmp_path)
    mgr._total_budget = 100.0
    mgr.record_worker_time("文字起こし", 50.256)
    mgr.record_worker_time("AI校閲", 60.123)

    report = mgr.generate_report("session_test_123")
    assert isinstance(report, PerformanceBudgetReport)
    assert report.session_id == "session_test_123"
    # 小数第2位に丸められること
    assert report.total_duration == 110.38  # 50.256 + 60.123 = 110.379 -> 110.38
    assert report.total_budget == 100.0
    assert report.over_budget is True
    assert len(report.workers) == 2
    
    worker_perf_map = {w.worker_name: w for w in report.workers}
    assert worker_perf_map["文字起こし"].duration_seconds == 50.26
    # AI校閲はバジェット60秒に対して60.123秒なのでover_budgetのはず
    assert worker_perf_map["AI校閲"].over_budget is True

    # session_id が None の場合
    report_none = mgr.generate_report(None)
    assert report_none.session_id == "unknown_session"


def test_save_report_normal(tmp_path):
    mgr = PerformanceBudgetManager(output_dir=tmp_path)
    report = mgr.generate_report("session-abc")
    filepath = mgr.save_report(report)
    
    assert filepath.exists()
    assert filepath.name == "worker_perf_session-abc.json"
    
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["session_id"] == "session-abc"


def test_save_report_sanitize(tmp_path):
    mgr = PerformanceBudgetManager(output_dir=tmp_path)
    # パストラバーサルを防ぐための文字種制限チェック
    report = mgr.generate_report("../invalid/session/id")
    filepath = mgr.save_report(report)
    
    assert filepath.exists()
    # サニタイズされて安全なファイル名になること
    assert ".." not in filepath.name
    assert "/" not in filepath.name
    assert filepath.name == "worker_perf_invalidsessionid.json"

    # 空のsession_id
    report_empty = mgr.generate_report("")
    report_empty.session_id = ""
    filepath_empty = mgr.save_report(report_empty)
    assert filepath_empty.name == "worker_perf_unknown_session.json"

    # 349行目: サニタイズ後に空文字列になるセッションID (例: 絵文字のみ)
    report_emoji = mgr.generate_report("🌟🌟🌟")
    filepath_emoji = mgr.save_report(report_emoji)
    assert filepath_emoji.name == "worker_perf_unknown_session.json"


def test_save_report_fallback(tmp_path, monkeypatch):
    mgr = PerformanceBudgetManager(output_dir=tmp_path)
    report = mgr.generate_report("session-fallback")

    # 書き込みを失敗させるために _write_report_file をモックし、1回目はOSErrorを起こす
    write_calls = []
    original_write = mgr._write_report_file
    
    def mock_write(dir_path, filename, data):
        write_calls.append(dir_path)
        if len(write_calls) == 1:
            raise OSError("Permission denied")
        return original_write(dir_path, filename, data)

    monkeypatch.setattr(mgr, "_write_report_file", mock_write)
    
    filepath = mgr.save_report(report)
    
    # 2回の呼び出しがあり、2回目はテンポラリディレクトリであること
    assert len(write_calls) == 2
    assert "performance_fallback" in str(write_calls[1])
    assert filepath.exists()


def test_save_report_fallback_fail(tmp_path, monkeypatch):
    mgr = PerformanceBudgetManager(output_dir=tmp_path)
    report = mgr.generate_report("session-fail")

    # 代替フォルダへの保存も含めてすべて失敗させる
    def mock_write_fail(dir_path, filename, data):
        raise OSError("Disk full")

    monkeypatch.setattr(mgr, "_write_report_file", mock_write_fail)
    
    with pytest.raises(OSError) as exc_info:
        mgr.save_report(report)
    
    assert "Failed to save performance report anywhere" in str(exc_info.value)


def test_get_history(tmp_path):
    mgr = PerformanceBudgetManager(output_dir=tmp_path)
    
    # 379行目: 出力ディレクトリが存在しない場合の処理
    non_existent_dir = tmp_path / "non_existent"
    mgr._output_dir = non_existent_dir
    assert mgr.get_history() == []

    # 出力ディレクトリを再設定
    mgr._output_dir = tmp_path
    assert mgr.get_history() == []

    # 複数のレポートを保存する
    for i in range(5):
        report = mgr.generate_report(f"session-{i}")
        mgr.save_report(report)

    history = mgr.get_history(limit=3)
    assert len(history) == 3
    
    # 不正なlimitのハンドリング
    assert len(mgr.get_history(limit="invalid")) == 5
    assert len(mgr.get_history(limit=-10)) == 5


def test_get_history_io_errors(tmp_path, monkeypatch):
    mgr = PerformanceBudgetManager(output_dir=tmp_path)
    report = mgr.generate_report("session-io")
    mgr.save_report(report)

    # 384-385行目: glob走査中にOSErrorが発生するケースのモック (TypeError回避のため self を含める)
    def mock_glob(self, pattern):
        raise OSError("Directory lock")
    
    monkeypatch.setattr(Path, "glob", mock_glob)
    assert mgr.get_history() == []


def test_get_history_stat_errors(tmp_path, monkeypatch):
    # 391-392行目: Path.stat().st_mtime 取得中に FileNotFoundError や OSError が発生するケースの検証
    mgr = PerformanceBudgetManager(output_dir=tmp_path)
    report = mgr.generate_report("session-stat-err")
    mgr.save_report(report)

    # 本物の stat を保存
    original_stat = Path.stat

    # Path.stat() が特定のファイルに対してのみ OSError を投げるようにモックする
    # これにより、pytest内部の stat 呼び出しを壊すことなくテストを行える
    def mock_stat(self, *args, **kwargs):
        if "worker_perf_session-stat-err" in self.name:
            raise OSError("Access denied")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", mock_stat)
    
    # statエラーが発生したファイルはスキップされるため、結果は空リストになる
    assert mgr.get_history() == []


def test_get_history_broken_json(tmp_path):
    mgr = PerformanceBudgetManager(output_dir=tmp_path)
    report = mgr.generate_report("session-ok")
    mgr.save_report(report)

    # 破損したJSONファイルを紛れ込ませる
    broken_file = tmp_path / "worker_perf_broken.json"
    with open(broken_file, "w", encoding="utf-8") as f:
        f.write("{broken json")

    history = mgr.get_history()
    # 破損したファイルは無視され、正常なものだけ返るはず
    assert len(history) == 1
    assert history[0]["session_id"] == "session-ok"


def test_update_budget_config(tmp_path):
    mgr = PerformanceBudgetManager(output_dir=tmp_path)
    
    # 不正な更新パラメータ型 (dictではない)
    res = mgr.update_budget_config("not a dict")
    assert res == mgr.get_budget_config()

    # 正当な更新
    updates = {
        "total_budget_seconds": 400.0,
        "worker_budgets": {
            "AI校閲": {"budget_seconds": 80.0, "priority": "degradable"},
            "SmartCut構成": 45.0
        }
    }
    res = mgr.update_budget_config(updates)
    assert res["total_budget_seconds"] == 400.0
    assert res["worker_budgets"]["AI校閲"]["budget_seconds"] == 80.0
    assert res["worker_budgets"]["AI校閲"]["priority"] == "degradable"
    assert res["worker_budgets"]["SmartCut構成"]["budget_seconds"] == 45.0

    # 443行目: 無効な数値 (負数) でのtotal_budget_seconds更新
    mgr.update_budget_config({"total_budget_seconds": -50.0})
    assert mgr.get_budget_config()["total_budget_seconds"] == 400.0

    # 444-445行目: _update_total_budget_config で例外発生時の処理 (非数値での更新試行)
    # 450-451行目: _update_worker_budgets_config で worker_budgets が辞書ではない場合の処理
    updates_invalid = {
        "total_budget_seconds": "not_a_float",  # ValueError例外を起こす
        "worker_budgets": "not_a_dict"  # 辞書以外の不正な型
    }
    res2 = mgr.update_budget_config(updates_invalid)
    # 値が更新されていないこと
    assert res2["total_budget_seconds"] == 400.0

    # 484-486行目: _parse_update_budget_seconds で例外発生時の処理 (数値に変換できない値を個々の値として渡す)
    # 496行目: _parse_update_priority で無効なpriority指定時の None 返却処理
    updates_worker_invalid = {
        "worker_budgets": {
            "AI校閲": {"budget_seconds": "not_a_float", "priority": "invalid_priority"}
        }
    }
    mgr.update_budget_config(updates_worker_invalid)
    # 値が変わっていないこと
    assert mgr.get_budget_config()["worker_budgets"]["AI校閲"]["budget_seconds"] == 80.0
    assert mgr.get_budget_config()["worker_budgets"]["AI校閲"]["priority"] == "degradable"


def test_update_budget_config_critical_protection(tmp_path, caplog):
    # EDGE-03: critical Workerのpriorityをdegradableに変更する操作が無視されること (491-492行目)
    mgr = PerformanceBudgetManager(output_dir=tmp_path)
    
    updates = {
        "worker_budgets": {
            "品質チェック": {"priority": "degradable"},
            "文字起こし": {"priority": "degradable"},
            "最終レンダリング": {"priority": "degradable"},
        }
    }
    
    with caplog.at_level(logging.WARNING):
        mgr.update_budget_config(updates)
    
    assert any("保護されたWorker '品質チェック' のpriorityは変更できません" in record.message for record in caplog.records)
    # 変更されていないことの確認
    assert mgr._worker_budgets["品質チェック"]["priority"] == "critical"
    assert mgr._worker_budgets["文字起こし"]["priority"] == "critical"
    assert mgr._worker_budgets["最終レンダリング"]["priority"] == "critical"


def test_reset_session(tmp_path):
    # 500-501行目: セッションリセット
    mgr = PerformanceBudgetManager(output_dir=tmp_path)
    mgr.record_worker_time("文字起こし", 50.0)
    mgr._degradation_applied.append("test")

    mgr.reset_session()
    assert mgr._current_session == {}
    assert mgr._degradation_applied == []


def test_get_progress_snapshot(tmp_path):
    # 509-513行目: progress snapshot の取得
    mgr = PerformanceBudgetManager(output_dir=tmp_path)
    mgr._total_budget = 100.0
    mgr.record_worker_time("文字起こし", 30.0)
    mgr.record_worker_time("AI校閲", 20.0)

    snapshot = mgr.get_progress_snapshot()
    assert snapshot["type"] == "performance_budget_progress"
    assert snapshot["cumulative_seconds"] == 50.0
    assert snapshot["total_budget_seconds"] == 100.0
    assert snapshot["consumption_ratio"] == 0.5
    assert snapshot["remaining_seconds"] == 50.0
    assert snapshot["workers_completed"] == 2
    assert snapshot["over_budget"] is False

    # トータルバジェットが0の場合
    mgr._total_budget = 0.0
    snapshot_zero = mgr.get_progress_snapshot()
    assert snapshot_zero["consumption_ratio"] == 0.0
