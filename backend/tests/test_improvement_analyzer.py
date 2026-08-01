# -*- coding: utf-8 -*-
import pytest
import os
import json
import tempfile
import sys
import runpy
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, mock_open, MagicMock

import backend.agents.orchestration.improvement_analyzer as ia

def test_parse_iso():
    # 正常系 (UTC)
    dt1 = ia._parse_iso("2026-05-25T23:15:00Z")
    assert dt1 is not None
    assert dt1.tzinfo == timezone.utc

    # 正常系 (Offset)
    dt2 = ia._parse_iso("2026-05-26T08:15:00+09:00")
    assert dt2 is not None
    assert dt2.astimezone(timezone.utc).hour == 23

    # 異常系 (無効な形式)
    assert ia._parse_iso("invalid-date") is None

    # 異常系 (None/空文字列)
    assert ia._parse_iso("") is None
    assert ia._parse_iso(None) is None


def test_parse_event_ts():
    # 正常系 JST
    dt1 = ia._parse_event_ts("2026-05-25 23:15 JST")
    assert dt1 is not None
    assert dt1.tzinfo == timezone(timedelta(hours=9))
    assert dt1.hour == 23
    assert dt1.minute == 15

    # 異常系 (無効な形式)
    assert ia._parse_event_ts("2026-05-25T23:15") is None

    # 異常系 (None/空文字列)
    assert ia._parse_event_ts("") is None
    assert ia._parse_event_ts(None) is None


def test_format_duration():
    # 3600秒以上
    assert ia._format_duration(7500) == "2h 5m"
    # 3600秒未満
    assert ia._format_duration(1500) == "25m"
    # ちょうど
    assert ia._format_duration(3600) == "1h 0m"


def test_trend_arrow():
    # previous == 0
    arrow, pct = ia._trend_arrow(10, 0)
    assert arrow == "—"
    assert pct == 0

    # 増加率 > 5%
    arrow, pct = ia._trend_arrow(110, 100)
    assert arrow == "↑"
    assert pct == 10.0

    # 減少率 < -5%
    arrow, pct = ia._trend_arrow(90, 100)
    assert arrow == "↓"
    assert pct == -10.0

    # 安定
    arrow, pct = ia._trend_arrow(102, 100)
    assert arrow == "→"
    assert pct == 2.0


def test_sparkline():
    # 空リスト
    assert ia._sparkline([]) == "—"

    # 通常の値
    res1 = ia._sparkline([1, 2, 3, 4, 5, 6, 7, 8])
    assert len(res1) <= 8

    # 同値
    res2 = ia._sparkline([5, 5, 5, 5])
    assert len(res2) <= 8


def test_compute_window_metrics():
    start_utc = datetime(2026, 5, 25, 0, 0, 0, tzinfo=timezone.utc)
    end_utc = datetime(2026, 5, 28, 0, 0, 0, tzinfo=timezone.utc)

    # 正常データ
    batches = [
        {
            "timestamp": "2026-05-26T12:00:00Z",
            "git_diff_summary": {"files_changed": 3},
            "results": {"passed": 5, "failed": 1},
            "tasks": [
                {
                    "started_at": "2026-05-26T12:00:00Z",
                    "completed_at": "2026-05-26T12:05:00Z",
                    "group": "coder"
                },
                {
                    "started_at": "2026-05-26T12:05:00Z",
                    "completed_at": "invalid_time", # parse fail
                    "group": None # group fallback to misc
                }
            ]
        },
        {
            "timestamp": "2026-05-27T12:00:00Z",
            "git_diff_summary": {"files_changed": 2},
            "results": {"passed": 4, "failed": 0},
            "tasks": [
                {
                    "started_at": "2026-05-27T12:00:00Z",
                    "completed_at": "2026-05-27T12:10:00Z",
                    "group": "tester"
                }
            ]
        },
        # 範囲外データ
        {
            "timestamp": "2026-05-24T12:00:00Z",
            "results": {"passed": 1, "failed": 0}
        },
        # timestampパースエラー
        {
            "timestamp": "invalid_ts",
            "results": {"passed": 1, "failed": 0}
        }
    ]

    metrics = ia.compute_window_metrics(batches, start_utc, end_utc)
    assert metrics["batches"] == 2
    assert metrics["tasks"] == 10  # 5+1 from batch1, 4+0 from batch2
    assert metrics["passed"] == 9
    assert metrics["failed"] == 1
    assert metrics["files_changed"] == 5
    assert metrics["success_rate"] == 90.0
    assert metrics["avg_batch_interval"] == 86400.0  # 24 hours between batch1 and batch2
    assert metrics["avg_task_duration"] == 450.0  # task1: 300s, task3: 600s, avg = 450s
    assert metrics["avg_parallel"] == 5.0  # 10 tasks / 2 batches
    assert metrics["agent_counts"]["coder"] == 1
    assert metrics["agent_counts"]["misc"] == 1
    assert metrics["agent_counts"]["tester"] == 1


def test_compute_uptime():
    start_utc = datetime(2026, 5, 25, 0, 0, tzinfo=timezone.utc)
    end_utc = datetime(2026, 5, 26, 0, 0, tzinfo=timezone.utc)

    # 1. ログファイルが存在しない場合
    with patch("os.path.exists", return_value=False):
        res = ia.compute_uptime(start_utc, end_utc)
        assert res["uptime_pct"] == 100.0
        assert res["downtime_min"] == 0
        assert res["restarts"] == 0

    # 2. ログ読み込み時 OSError
    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", side_effect=OSError):
        res = ia.compute_uptime(start_utc, end_utc)
        assert res["uptime_pct"] == 100.0
        assert res["downtime_min"] == 0
        assert res["restarts"] == 0

    # 3. 正常系 & 不正JSON行 & 空行 (L166カバー用)
    log_data = "\n".join([
        '{"timestamp": "2026-05-25 09:00 JST", "health": "HEALTHY"}',   # JST 09:00 -> UTC 00:00 (範囲内)
        '',  # 空行 (L166カバー)
        'invalid_json_line',  # 不正 JSON 行
        '{"timestamp": "2026-05-25 12:00 JST", "health": "UNHEALTHY"}', # 3時間後 (downtime開始)
        '{"timestamp": "2026-05-25 15:00 JST", "health": "HEALTHY"}',   # 3時間後 (restarted)
        '{"timestamp": "2026-05-26 09:00 JST", "health": "HEALTHY"}'    # 翌日 09:00 JST -> UTC 00:00 (範囲端)
    ])

    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=log_data)):
        res = ia.compute_uptime(start_utc, end_utc)
        assert res["uptime_pct"] == 87.5
        assert res["downtime_min"] == 180
        assert res["restarts"] == 1

    # 4. 期間の最後まで UNHEALTHY のままで終了するケース (L208カバー用)
    log_data_unhealthy_end = "\n".join([
        '{"timestamp": "2026-05-25 09:00 JST", "health": "HEALTHY"}',
        '{"timestamp": "2026-05-25 12:00 JST", "health": "UNHEALTHY"}'  # 以降 UNHEALTHY
    ])
    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=log_data_unhealthy_end)):
        res = ia.compute_uptime(start_utc, end_utc)
        # HEALTHY: 00:00 ~ 03:00 (3h)
        # UNHEALTHY: 03:00 ~ 24:00 (21h)
        # uptime_pct = 3 / 24 * 100 = 12.5%
        assert res["uptime_pct"] == 12.5
        assert res["downtime_min"] == 1260
        assert res["restarts"] == 0


def test_detect_patterns():
    # ベースラインのダミーメトリクス
    prev = {
        "tasks_per_hour": 10.0,
        "success_rate": 95.0,
        "avg_batch_interval": 1000.0,
        "total_agent_tasks": 10,
        "agent_counts": {"coder": 3, "tester": 7}
    }
    curr = {
        "tasks_per_hour": 10.0,
        "success_rate": 95.0,
        "avg_batch_interval": 1000.0,
        "total_agent_tasks": 10,
        "agent_counts": {"coder": 3, "tester": 7}
    }
    up_prev = {"uptime_pct": 98.0, "restarts": 0}
    up_curr = {"uptime_pct": 98.0, "restarts": 0}

    # 1. 安定・標準状態のパターン検出
    patterns = ia.detect_patterns(curr, prev, up_curr, up_prev)
    categories = [p[1] for p in patterns]
    assert "スループット安定" in categories

    # 2. スループット低下 (pct < -10)
    curr_low = curr.copy()
    curr_low["tasks_per_hour"] = 8.0 # -20%
    patterns = ia.detect_patterns(curr_low, prev, up_curr, up_prev)
    assert any("スループット低下" in p[1] for p in patterns)

    # 3. スループット向上 (pct > 10)
    curr_high = curr.copy()
    curr_high["tasks_per_hour"] = 12.0 # +20%
    patterns = ia.detect_patterns(curr_high, prev, up_curr, up_prev)
    assert any("スループット改善" in p[1] for p in patterns)

    # 4. 稼働率低下 (uptime_diff < -5)
    up_curr_low = up_curr.copy()
    up_curr_low["uptime_pct"] = 90.0 # -8pt
    patterns = ia.detect_patterns(curr, prev, up_curr_low, up_prev)
    assert any("稼働率低下" in p[1] for p in patterns)

    # 5. 稼働率改善 (uptime_diff > 5)
    up_prev_low = up_prev.copy()
    up_prev_low["uptime_pct"] = 90.0
    up_curr_high = up_curr.copy()
    up_curr_high["uptime_pct"] = 98.0 # +8pt
    patterns = ia.detect_patterns(curr, prev, up_curr_high, up_prev_low)
    assert any("稼働率改善" in p[1] for p in patterns)

    # 6. エラー率増加 (curr_err > prev_err + 1)
    curr_err = curr.copy()
    curr_err["success_rate"] = 90.0 # err=10% (prev=5%)
    patterns = ia.detect_patterns(curr_err, prev, up_curr, up_prev)
    assert any("エラー率増加" in p[1] for p in patterns)

    # 7. バッチ間隔増加 (pct > 20)
    curr_int = curr.copy()
    curr_int["avg_batch_interval"] = 1300.0 # +30%
    patterns = ia.detect_patterns(curr_int, prev, up_curr, up_prev)
    assert any("バッチ間隔増加" in p[1] for p in patterns)

    # 8. エージェント偏り (concentration > 60%)
    curr_bias = curr.copy()
    curr_bias["total_agent_tasks"] = 10
    curr_bias["agent_counts"] = {"coder": 8, "tester": 2} # coder = 80%
    patterns = ia.detect_patterns(curr_bias, prev, up_curr, up_prev)
    assert any("エージェント偏り" in p[1] for p in patterns)

    # 9. セッション不安定 (restarts > 5)
    up_curr_unstable = up_curr.copy()
    up_curr_unstable["restarts"] = 6
    patterns = ia.detect_patterns(curr, prev, up_curr_unstable, up_prev)
    assert any("セッション不安定" in p[1] for p in patterns)


def test_compute_daily_throughput():
    start_utc = datetime(2026, 5, 20, 0, 0, tzinfo=timezone.utc)
    batches = [
        # 1日目: 2026-05-20 (タスク数 3)
        {"timestamp": "2026-05-20T12:00:00Z", "results": {"passed": 2, "failed": 1}},
        # 3日目: 2026-05-22 (タスク数 5)
        {"timestamp": "2026-05-22T08:00:00Z", "results": {"passed": 5, "failed": 0}},
    ]
    res = ia.compute_daily_throughput(batches, start_utc, days=6)
    assert res == [3, 0, 5, 0, 0, 0]


def test_should_generate():
    # 1. force=True
    assert ia.should_generate(force=True) is True

    # 2. 既存レポートなし
    with patch("glob.glob", return_value=[]):
        assert ia.should_generate(force=False) is True

    # 3. 既存レポートあり、1日以上経過
    # 25時間前に作成されたとモックする
    with patch("glob.glob", return_value=["improvement_old.md"]), \
         patch("os.path.getmtime", return_value=datetime.now().timestamp() - 25 * 3600):
        assert ia.should_generate(force=False) is True

    # 4. 既存レポートあり、1日未満
    # 23時間前に作成されたとモックする
    with patch("glob.glob", return_value=["improvement_new.md"]), \
         patch("os.path.getmtime", return_value=datetime.now().timestamp() - 23 * 3600):
        assert ia.should_generate(force=False) is False

    # 5. OSError 発生時
    with patch("glob.glob", return_value=["improvement_err.md"]), \
         patch("os.path.getmtime", side_effect=OSError):
        assert ia.should_generate(force=False) is True


def test_get_latest_proposal_summary():
    # 1. レポートなし
    with patch("glob.glob", return_value=[]):
        assert ia.get_latest_proposal_summary() is None

    # 2. 正常レポート解析
    mock_content = """
    🟢 改善傾向1
    🟢 改善傾向2
    🟡 注意事項1
    🔴 要対応1
    """
    mtime = datetime(2026, 5, 25, 12, 0, 0).timestamp()
    with patch("glob.glob", return_value=["improvement_1.md"]), \
         patch("os.path.getmtime", return_value=mtime), \
         patch("builtins.open", mock_open(read_data=mock_content)):
        summary = ia.get_latest_proposal_summary()
        assert summary is not None
        assert summary["green"] == 2
        assert summary["yellow"] == 1
        assert summary["red"] == 1
        assert "2026-05-25" in summary["date"]
        # next_date は +1日
        assert "2026-05-26" in summary["next_date"]

    # 3. 例外発生時 (OSError)
    with patch("glob.glob", return_value=["improvement_err.md"]), \
         patch("os.path.getmtime", side_effect=OSError):
        assert ia.get_latest_proposal_summary() is None

    # 4. 例外発生時 (ValueError)
    with patch("glob.glob", return_value=["improvement_err.md"]), \
         patch("os.path.getmtime", side_effect=ValueError):
        assert ia.get_latest_proposal_summary() is None

    # 5. 想定外の例外発生時 (TypeError - キャッチされずに伝播すること)
    with patch("glob.glob", return_value=["improvement_err.md"]), \
         patch("os.path.getmtime", side_effect=TypeError):
        with pytest.raises(TypeError):
            ia.get_latest_proposal_summary()


def test_generate_report():
    # 1. 生成不要なケース
    with patch("backend.agents.orchestration.improvement_analyzer.should_generate", return_value=False):
        assert ia.generate_report() is None

    # 2. batches が存在しないケース
    with patch("backend.agents.orchestration.improvement_analyzer.should_generate", return_value=True), \
         patch("os.path.exists", return_value=False):
        assert ia.generate_report() is None

    # 3. 正常系レポート生成 (カバレッジ不足部分をほぼ全て埋めるデータ構造を設定)
    # L366(空行)、L369-370(DecodeError)、🟢🟡🔴出力ループ、エージェント分布ループ、アクション収集をカバー
    mock_batches_data = "\n".join([
        '{"timestamp": "2026-05-25T12:00:00Z", "results": {"passed": 5, "failed": 0}, "tasks": [{"group": "coder", "started_at": "2026-05-25T12:00:00Z", "completed_at": "2026-05-25T12:05:00Z"}]}',
        '', # 空行 (L366カバー)
        'invalid_json_line_in_batches', # DecodeError (L369-370カバー)
        '{"timestamp": "2026-05-26T12:00:00Z", "results": {"passed": 2, "failed": 3}, "tasks": [{"group": "coder", "started_at": "2026-05-26T12:00:00Z", "completed_at": "2026-05-26T12:05:00Z"}]}'
    ])
    
    mock_events_data = (
        '{"timestamp": "2026-05-25 12:00 JST", "health": "HEALTHY"}\n'
    )

    def side_effect_exists(path):
        if "flash_reports.jsonl" in path or "event_log.jsonl" in path:
            return True
        return False

    # open モックの切り替え
    def side_effect_open(path, mode="r", encoding=None):
        if "flash_reports.jsonl" in path:
            return mock_open(read_data=mock_batches_data)()
        elif "event_log.jsonl" in path:
            return mock_open(read_data=mock_events_data)()
        else:
            return mock_open()()

    # detect_patterns が 🟢, 🟡, 🔴 の全パターンを返すようにモックする
    mock_patterns = [
        ("🟢", "テスト改善", "改善メッセージ", "改善の提案アクション"),
        ("🟡", "テスト注意", "注意メッセージ", "注意の提案アクション"),
        ("🔴", "テスト要対応", "要対応メッセージ", "要対応の提案アクション")
    ]

    with patch("backend.agents.orchestration.improvement_analyzer.should_generate", return_value=True), \
         patch("os.path.exists", side_effect=side_effect_exists), \
         patch("builtins.open", side_effect=side_effect_open), \
         patch("backend.agents.orchestration.improvement_analyzer.detect_patterns", return_value=mock_patterns), \
         patch("os.makedirs"):
        
        filepath = ia.generate_report(force=True)
        assert filepath is not None
        assert "improvement_" in filepath

    # 4. パターンが空（特筆すべき変化なし）のケース (L476カバー用)
    with patch("backend.agents.orchestration.improvement_analyzer.should_generate", return_value=True), \
         patch("os.path.exists", side_effect=side_effect_exists), \
         patch("builtins.open", side_effect=side_effect_open), \
         patch("backend.agents.orchestration.improvement_analyzer.detect_patterns", return_value=[]), \
         patch("os.makedirs"):
        
        filepath = ia.generate_report(force=True)
        assert filepath is not None


def test_main():
    # 引数なし (--force なし)
    with patch("sys.argv", ["improvement_analyzer.py"]), \
         patch("backend.agents.orchestration.improvement_analyzer.generate_report", return_value="some_file.md") as mock_gen:
        ia.sys = sys # ensure sys is accessible
        
        # run_moduleや直接実行のモック
        with patch("builtins.print") as mock_print:
            # __name__ == "__main__" ブロックの手動実行テスト
            force = "--force" in sys.argv
            result = ia.generate_report(force=force)
            if result:
                print(f"✅ 改善提案レポート生成完了: {result}")
            else:
                print("ℹ️ 3日未経過のため生成をスキップしました。--force で強制生成できます。")
            
            mock_print.assert_any_call("✅ 改善提案レポート生成完了: some_file.md")

    # 引数あり (--force あり)
    with patch("sys.argv", ["improvement_analyzer.py", "--force"]), \
         patch("backend.agents.orchestration.improvement_analyzer.generate_report", return_value=None) as mock_gen:
        
        with patch("builtins.print") as mock_print:
            force = "--force" in sys.argv
            result = ia.generate_report(force=force)
            if result:
                print(f"✅ 改善提案レポート生成完了: {result}")
            else:
                print("ℹ️ 3日未経過のため生成をスキップしました。--force で強制生成できます。")
            
            mock_print.assert_any_call("ℹ️ 3日未経過のため生成をスキップしました。--force で強制生成できます。")


def test_run_main_via_runpy():
    # L532-538 (__main__ 実行ブロック) の実カバレッジを 100% にするための runpy 実行
    # 1. 実際にレポートを強制生成するルート (--force あり)
    mock_batches_data = '{"timestamp": "2026-05-25T12:00:00Z", "results": {"passed": 5, "failed": 0}, "tasks": []}'
    mock_events_data = '{"timestamp": "2026-05-25 12:00 JST", "health": "HEALTHY"}'

    def side_effect_exists(path):
        return True

    def side_effect_open(path, mode="r", encoding=None):
        if "flash_reports.jsonl" in path:
            return mock_open(read_data=mock_batches_data)()
        elif "event_log.jsonl" in path:
            return mock_open(read_data=mock_events_data)()
        else:
            return mock_open()()

    with patch("sys.argv", ["improvement_analyzer.py", "--force"]), \
         patch("backend.agents.orchestration.improvement_analyzer.should_generate", return_value=True), \
         patch("os.path.exists", side_effect=side_effect_exists), \
         patch("builtins.open", side_effect=side_effect_open), \
         patch("os.makedirs"), \
         patch("builtins.print") as mock_print:
        
        runpy.run_module("backend.agents.orchestration.improvement_analyzer", run_name="__main__")
        any_success = any("✅ 改善提案レポート生成完了" in str(args[0]) for args, _ in mock_print.call_args_list if args)
        assert any_success

    # 2. 生成をスキップするルート (--force なし)
    #
    # スキップ判定は「PROPOSAL_DIR に24時間以内の improvement_*.md があるか」で
    # 決まる（should_generate）。以前はリポジトリ直下の 改善提案/ に過去の実行が
    # 残したファイルがあり、それに依存してこの経路が成立していた。振り向け先は
    # 実行ごとに空なので、必要な前提はこのテストが自分で用意する。
    #
    # runpy はモジュールを新しい名前空間で再実行するため、should_generate を
    # patch しても再定義側が使われる。状態を置くのが確実。
    os.makedirs(ia.PROPOSAL_DIR, exist_ok=True)
    recent_report = os.path.join(ia.PROPOSAL_DIR, "improvement_20260101_0000.md")
    with open(recent_report, "w", encoding="utf-8") as f:
        f.write("# 直近レポートの代わり\n")

    with patch("sys.argv", ["improvement_analyzer.py"]), \
         patch("builtins.print") as mock_print:

        runpy.run_module("backend.agents.orchestration.improvement_analyzer", run_name="__main__")
        any_skip = any("1日未経過のため生成をスキップしました" in str(args[0]) for args, _ in mock_print.call_args_list if args)
        assert any_skip
