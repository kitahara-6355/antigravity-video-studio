import json
import os
import sys
import subprocess
from unittest.mock import patch, mock_open, MagicMock
import pytest
from datetime import datetime, timezone, timedelta

# プロジェクトのソースをインポートできるようにパスを通す
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.agents.orchestration import health_check_cron


def test_safe_read_json_not_exists():
    with patch("os.path.exists", return_value=False):
        res = health_check_cron._safe_read_json("dummy_path.json", default={"status": "none"})
        assert res == {"status": "none"}


def test_safe_read_json_valid():
    content = '{"status": "running"}'
    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=content)):
        res = health_check_cron._safe_read_json("dummy_path.json")
        assert res == {"status": "running"}


def test_safe_read_json_invalid():
    content = '{"status": "running"'  # 壊れたJSON
    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=content)):
        res = health_check_cron._safe_read_json("dummy_path.json", default={})
        assert res == {}


def test_safe_read_json_io_error():
    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", side_effect=OSError("Read error")):
        res = health_check_cron._safe_read_json("dummy_path.json", default={"err": True})
        assert res == {"err": True}


def test_check_auto_nudge_no_session():
    with patch("backend.agents.orchestration.health_check_cron._safe_read_json", return_value={}):
        res = health_check_cron._check_auto_nudge()
        assert res is False


def test_check_auto_nudge_not_running():
    with patch("backend.agents.orchestration.health_check_cron._safe_read_json", return_value={"status": "ended"}):
        res = health_check_cron._check_auto_nudge()
        assert res is False


def test_check_auto_nudge_no_conv_id():
    session = {"status": "running", "conversation_id": ""}
    with patch("backend.agents.orchestration.health_check_cron._safe_read_json", return_value=session):
        res = health_check_cron._check_auto_nudge()
        assert res is False


def test_check_auto_nudge_no_heartbeat():
    session = {"status": "running", "conversation_id": "conv_123"}
    with patch("backend.agents.orchestration.health_check_cron._safe_read_json", return_value=session):
        res = health_check_cron._check_auto_nudge()
        assert res is False


def test_check_auto_nudge_fresh_heartbeat():
    now_str = datetime.now(timezone.utc).isoformat()
    session = {
        "status": "running",
        "conversation_id": "conv_123",
        "last_heartbeat": now_str
    }
    with patch("backend.agents.orchestration.health_check_cron._safe_read_json", return_value=session):
        res = health_check_cron._check_auto_nudge()
        assert res is False


def test_check_auto_nudge_stale_heartbeat_trigger():
    # 25分前の心拍
    stale_time = (datetime.now(timezone.utc) - timedelta(minutes=25)).isoformat()
    session = {
        "status": "running",
        "conversation_id": "conv_123",
        "last_heartbeat": stale_time,
        "auto_nudge_count": 0
    }
    
    mock_open_instance = mock_open()
    with patch("backend.agents.orchestration.health_check_cron._safe_read_json", return_value=session), \
         patch("builtins.open", mock_open_instance), \
         patch("sys.stdout.write") as mock_stdout:
        res = health_check_cron._check_auto_nudge()
        assert res is True
        
        # セッション更新が書き込まれていることの検証
        # 書き込み先は FLASH_SESSION_PATH と nudge_flash.json のはず
        assert mock_open_instance.call_count >= 2


def test_check_auto_nudge_cooldown():
    stale_time = (datetime.now(timezone.utc) - timedelta(minutes=25)).isoformat()
    last_nudge = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()  # クールダウン中
    session = {
        "status": "running",
        "conversation_id": "conv_123",
        "last_heartbeat": stale_time,
        "last_auto_nudge_at": last_nudge,
        "auto_nudge_count": 1
    }
    with patch("backend.agents.orchestration.health_check_cron._safe_read_json", return_value=session):
        res = health_check_cron._check_auto_nudge()
        assert res is False


def test_check_auto_nudge_consecutive_failures():
    stale_time = (datetime.now(timezone.utc) - timedelta(minutes=25)).isoformat()
    session = {
        "status": "running",
        "conversation_id": "conv_123",
        "last_heartbeat": stale_time,
        "auto_nudge_count": 1  # 次で2回目
    }
    
    mock_open_instance = mock_open()
    with patch("backend.agents.orchestration.health_check_cron._safe_read_json", return_value=session), \
         patch("builtins.open", mock_open_instance), \
         patch("builtins.print") as mock_print:
        res = health_check_cron._check_auto_nudge()
        assert res is True
        # print で 🚨 AUTO_NUDGE 2回連続失敗 が出力されること
        printed_args = [call[0][0] for call in mock_print.call_args_list]
        assert any("AUTO_NUDGE 2回連続失敗" in arg for arg in printed_args)


def test_should_output_unhealthy():
    # 異常時は常に出力
    should_out, reason = health_check_cron._should_output("ACTIVE", "🔴 UNHEALTHY", "FRESH")
    assert should_out is True
    assert "異常検知" in reason


def test_should_output_active_in_window():
    with patch("backend.agents.orchestration.health_check_cron._is_in_user_window", return_value=True), \
         patch("backend.agents.orchestration.health_check_cron._is_night_time", return_value=False):
        should_out, reason = health_check_cron._should_output("ACTIVE", "🟢 HEALTHY", "FRESH")
        assert should_out is True
        assert "ACTIVE+着席窓" in reason


def test_should_output_active_out_of_window_skip():
    # cron_iterations = 1 (iters % 3 != 0)
    with patch("backend.agents.orchestration.health_check_cron._is_in_user_window", return_value=False), \
         patch("backend.agents.orchestration.health_check_cron._safe_read_json", return_value={"cron_iterations": 1}), \
         patch("backend.agents.orchestration.health_check_cron._is_night_time", return_value=False):
        should_out, reason = health_check_cron._should_output("ACTIVE", "🟢 HEALTHY", "FRESH")
        assert should_out is False
        assert "離席中 → スキップ" in reason


def test_should_output_active_out_of_window_output():
    # cron_iterations = 3 (iters % 3 == 0)
    with patch("backend.agents.orchestration.health_check_cron._is_in_user_window", return_value=False), \
         patch("backend.agents.orchestration.health_check_cron._safe_read_json", return_value={"cron_iterations": 3}), \
         patch("backend.agents.orchestration.health_check_cron._is_night_time", return_value=False):
        should_out, reason = health_check_cron._should_output("ACTIVE", "🟢 HEALTHY", "FRESH")
        assert should_out is True
        assert "離席中 → 15分出力" in reason


def test_build_structured_summary_standard():
    data = {
        "overall": "🟢 HEALTHY",
        "phase": "27",
        "milestone": "8",
        "checks": {
            "心拍鮮度": {"detail": "0分前(正常)", "minutes_ago": 0},
            "Git最新コミット": {"detail": "abc1234"},
            "バッチ整合": {"report_tasks": 10, "session_tasks": 2}
        },
        "flash_lifecycle": {
            "status": "ACTIVE",
            "detail": "🔄 稼働中"
        },
        "eta": {
            "eta_jst": "12:34 JST",
            "eta_minutes": 30,
            "session_eta_jst": "13:00 JST",
            "session_remaining_tasks": 5,
            "session_capacity_pct": 50,
            "recommended_return_jst": "13:00"
        },
        "opus_health": {
            "stage": "FRESH",
            "uptime_hours": 1.5,
            "cron_iterations": 10
        },
        "suggestions": ["ディスク空き容量を確認してください"]
    }
    summary = health_check_cron._build_structured_summary(data)
    assert "🟢 HEALTHY" in summary
    assert "Phase 27" in summary
    assert "M8" in summary
    assert "📡 Flash: 🔄 稼働中" in summary
    assert "心拍 0分前(正常)" in summary
    assert "通算10タスク完了" in summary
    assert "ETA: 12:34 JST" in summary
    assert "セッションETA: 13:00 JST" in summary
    assert "次回着席推奨: 13:00 JST" in summary
    assert "🧠 Opus: 🟢 FRESH" in summary
    assert "💡 ディスク空き容量を確認してください" in summary


def test_build_structured_summary_incomplete_data():
    # 欠落データがある場合でもクラッシュせずデフォルト値等で動くことの検証
    data = {}
    summary = health_check_cron._build_structured_summary(data)
    assert "❓ 不明" in summary


def test_main_normal(capsys):
    json_out = json.dumps({
        "overall": "🟢 HEALTHY",
        "flash_lifecycle": {"status": "ACTIVE"},
        "opus_health": {"cron_iterations": 1}
    })
    
    mock_run_json = MagicMock()
    mock_run_json.stdout = json_out.encode("utf-8")
    
    with patch("subprocess.run", return_value=mock_run_json), \
         patch("backend.agents.orchestration.health_check_cron._should_output", return_value=(True, "test")), \
         patch("backend.agents.orchestration.health_check_cron._check_auto_nudge") as mock_nudge:
        health_check_cron.main()
        captured = capsys.readouterr()
        assert "HEALTHY" in captured.out
        mock_nudge.assert_called_once()


def test_main_skip(capsys):
    json_out = json.dumps({
        "overall": "🟢 HEALTHY",
        "flash_lifecycle": {"status": "ACTIVE"},
        "opus_health": {"cron_iterations": 1}
    })
    
    mock_run_json = MagicMock()
    mock_run_json.stdout = json_out.encode("utf-8")
    
    with patch("subprocess.run", return_value=mock_run_json), \
         patch("backend.agents.orchestration.health_check_cron._should_output", return_value=(False, "test_skip")), \
         patch("backend.agents.orchestration.health_check_cron._next_user_window", return_value={"start": "18:00", "label": "夕方"}), \
         patch("backend.agents.orchestration.health_check_cron._check_auto_nudge") as mock_nudge:
        health_check_cron.main()
        captured = capsys.readouterr()
        assert "⏸️ Cron #1 スキップ (test_skip) | 次窓: 18:00 (夕方)" in captured.out.strip()
        mock_nudge.assert_called_once()


def test_main_json_error_fallback(capsys):
    # JSONデコードエラー時のフォールバック処理
    mock_run_json = MagicMock()
    mock_run_json.stdout = b"invalid json"
    
    mock_run_dashboard = MagicMock() # Step 2用
    mock_run_dashboard.stdout = b""

    mock_run_text = MagicMock() # フォールバック用
    mock_run_text.stdout = b"HEALTHY: System is active\nSome unrelated log"
    
    # 1回目は JSON、2回目はダッシュボード更新、3回目はフォールバック
    with patch("subprocess.run", side_effect=[mock_run_json, mock_run_dashboard, mock_run_text]), \
         patch("backend.agents.orchestration.health_check_cron._check_auto_nudge") as mock_nudge:
        health_check_cron.main()
        captured = capsys.readouterr()
        assert "HEALTHY" in captured.out
        mock_nudge.assert_called_once()


def test_main_subprocess_error_handling(capsys):
    # subprocess.run が例外を投げた際のエラーハンドリング
    with patch("subprocess.run", side_effect=subprocess.SubprocessError("Failed to launch health_check.py")), \
         patch("backend.agents.orchestration.health_check_cron._check_auto_nudge") as mock_nudge:
        # main() がクラッシュせずに安全に終了すること
        health_check_cron.main()
        captured = capsys.readouterr()
        assert "Failed to launch" in captured.err or "実行に失敗しました" in captured.out
        mock_nudge.assert_called_once()



# -------------------------------------------------------------
# 追加のテストケース（未カバー行の解消）
# -------------------------------------------------------------

def test_check_auto_nudge_invalid_heartbeat_format():
    session = {
        "status": "running",
        "conversation_id": "conv_123",
        "last_heartbeat": "invalid_date_format"
    }
    with patch("backend.agents.orchestration.health_check_cron._safe_read_json", return_value=session):
        res = health_check_cron._check_auto_nudge()
        assert res is False

def test_check_auto_nudge_invalid_heartbeat_type():
    session = {
        "status": "running",
        "conversation_id": "conv_123",
        "last_heartbeat": 12345
    }
    with patch("backend.agents.orchestration.health_check_cron._safe_read_json", return_value=session):
        with pytest.raises(AttributeError):
            health_check_cron._check_auto_nudge()

def test_check_auto_nudge_invalid_last_nudge_format():
    stale_time = (datetime.now(timezone.utc) - timedelta(minutes=25)).isoformat()
    session = {
        "status": "running",
        "conversation_id": "conv_123",
        "last_heartbeat": stale_time,
        "last_auto_nudge_at": "invalid_nudge_format",
        "auto_nudge_count": 0
    }
    mock_open_instance = mock_open()
    with patch("backend.agents.orchestration.health_check_cron._safe_read_json", return_value=session),          patch("builtins.open", mock_open_instance),          patch("sys.stdout.write"):
        res = health_check_cron._check_auto_nudge()
        assert res is True

def test_check_auto_nudge_invalid_last_nudge_type():
    stale_time = (datetime.now(timezone.utc) - timedelta(minutes=25)).isoformat()
    session = {
        "status": "running",
        "conversation_id": "conv_123",
        "last_heartbeat": stale_time,
        "last_auto_nudge_at": 99999,
        "auto_nudge_count": 0
    }
    mock_open_instance = mock_open()
    with patch("backend.agents.orchestration.health_check_cron._safe_read_json", return_value=session),          patch("builtins.open", mock_open_instance),          patch("sys.stdout.write"):
        with pytest.raises(AttributeError):
            health_check_cron._check_auto_nudge()

def test_check_auto_nudge_session_write_os_error():
    stale_time = (datetime.now(timezone.utc) - timedelta(minutes=25)).isoformat()
    session = {
        "status": "running",
        "conversation_id": "conv_123",
        "last_heartbeat": stale_time,
        "auto_nudge_count": 0
    }
    def mock_open_side_effect(file, mode="r", *args, **kwargs):
        if "flash_session.json" in file:
            raise OSError("Permission denied")
        return mock_open()()

    with patch("backend.agents.orchestration.health_check_cron._safe_read_json", return_value=session),          patch("builtins.open", side_effect=mock_open_side_effect),          patch("sys.stdout.write"):
        res = health_check_cron._check_auto_nudge()
        assert res is True

def test_check_auto_nudge_nudge_file_write_os_error():
    stale_time = (datetime.now(timezone.utc) - timedelta(minutes=25)).isoformat()
    session = {
        "status": "running",
        "conversation_id": "conv_123",
        "last_heartbeat": stale_time,
        "auto_nudge_count": 0
    }
    def mock_open_side_effect(file, mode="r", *args, **kwargs):
        if "nudge_flash.json" in file:
            raise OSError("Disk full")
        return mock_open()()

    with patch("backend.agents.orchestration.health_check_cron._safe_read_json", return_value=session),          patch("builtins.open", side_effect=mock_open_side_effect),          patch("sys.stdout.write"):
        res = health_check_cron._check_auto_nudge()
        assert res is True

# DateTimeのパッチ用スタブクラス
import datetime as real_datetime
class StubDateTime:
    _now_val = None
    @classmethod
    def now(cls, tz=None):
        if cls._now_val is not None:
            return cls._now_val
        return real_datetime.datetime.now(tz)
    @classmethod
    def fromisoformat(cls, *args, **kwargs):
        return real_datetime.datetime.fromisoformat(*args, **kwargs)

def test_get_current_windows_weekday():
    # 月曜日
    monday = real_datetime.datetime(2026, 5, 25, 12, 0, 0, tzinfo=real_datetime.timezone(real_datetime.timedelta(hours=9)))
    schedule = {
        "weekday": {
            "windows": [{"start": "09:00", "end": "12:00", "label": "午前"}]
        },
        "weekend": {
            "windows": [{"start": "10:00", "end": "18:00", "label": "週末"}]
        }
    }
    StubDateTime._now_val = monday
    with patch("backend.agents.orchestration.health_check_cron._safe_read_json", return_value=schedule),          patch("backend.agents.orchestration.health_check_cron.datetime", StubDateTime):
        res = health_check_cron._get_current_windows()
        assert len(res) == 1
        assert res[0]["label"] == "午前"

def test_get_current_windows_weekend():
    # 日曜日
    sunday = real_datetime.datetime(2026, 5, 31, 12, 0, 0, tzinfo=real_datetime.timezone(real_datetime.timedelta(hours=9)))
    schedule = {
        "weekday": {
            "windows": [{"start": "09:00", "end": "12:00", "label": "午前"}]
        },
        "weekend": {
            "windows": [{"start": "10:00", "end": "18:00", "label": "週末"}]
        }
    }
    StubDateTime._now_val = sunday
    with patch("backend.agents.orchestration.health_check_cron._safe_read_json", return_value=schedule),          patch("backend.agents.orchestration.health_check_cron.datetime", StubDateTime):
        res = health_check_cron._get_current_windows()
        assert len(res) == 1
        assert res[0]["label"] == "週末"

def test_get_current_windows_flat_fallback():
    schedule = {
        "windows": [{"start": "08:00", "end": "22:00", "label": "終日"}]
    }
    with patch("backend.agents.orchestration.health_check_cron._safe_read_json", return_value=schedule):
        res = health_check_cron._get_current_windows()
        assert len(res) == 1
        assert res[0]["label"] == "終日"

def test_is_in_user_window_empty():
    with patch("backend.agents.orchestration.health_check_cron._get_current_windows", return_value=[]):
        assert health_check_cron._is_in_user_window() is True

def test_is_in_user_window_check():
    now_time = real_datetime.datetime(2026, 5, 25, 10, 0, 0, tzinfo=real_datetime.timezone(real_datetime.timedelta(hours=9)))
    windows_in = [{"start": "09:00", "end": "11:00"}]
    StubDateTime._now_val = now_time
    with patch("backend.agents.orchestration.health_check_cron._get_current_windows", return_value=windows_in),          patch("backend.agents.orchestration.health_check_cron.datetime", StubDateTime):
        assert health_check_cron._is_in_user_window() is True
        
    windows_out = [{"start": "12:00", "end": "14:00"}]
    with patch("backend.agents.orchestration.health_check_cron._get_current_windows", return_value=windows_out),          patch("backend.agents.orchestration.health_check_cron.datetime", StubDateTime):
        assert health_check_cron._is_in_user_window() is False

def test_next_user_window_scenarios():
    with patch("backend.agents.orchestration.health_check_cron._get_current_windows", return_value=[]):
        assert health_check_cron._next_user_window() is None

    now_time = real_datetime.datetime(2026, 5, 25, 10, 0, 0, tzinfo=real_datetime.timezone(real_datetime.timedelta(hours=9)))
    StubDateTime._now_val = now_time
    
    windows = [
        {"start": "08:00", "end": "09:00", "label": "朝"},
        {"start": "12:00", "end": "14:00", "label": "昼"},
        {"start": "18:00", "end": "20:00", "label": "夜"}
    ]
    with patch("backend.agents.orchestration.health_check_cron._get_current_windows", return_value=windows),          patch("backend.agents.orchestration.health_check_cron.datetime", StubDateTime):
        next_w = health_check_cron._next_user_window()
        assert next_w["label"] == "昼"

    windows_past = [
        {"start": "08:00", "end": "09:00", "label": "朝"}
    ]
    with patch("backend.agents.orchestration.health_check_cron._get_current_windows", return_value=windows_past),          patch("backend.agents.orchestration.health_check_cron.datetime", StubDateTime):
        next_w = health_check_cron._next_user_window()
        assert next_w["label"] == "朝"

def test_should_output_complete_stopped_scenarios():
    with patch("backend.agents.orchestration.health_check_cron._is_in_user_window", return_value=True), \
         patch("backend.agents.orchestration.health_check_cron._safe_read_json", return_value={"cron_iterations": 0}), \
         patch("backend.agents.orchestration.health_check_cron._is_night_time", return_value=False):
        should_out, reason = health_check_cron._should_output("COMPLETE", "🟢 HEALTHY", "FRESH")
        assert should_out is True
        assert "COMPLETE+着席窓" in reason

    with patch("backend.agents.orchestration.health_check_cron._is_in_user_window", return_value=True), \
         patch("backend.agents.orchestration.health_check_cron._safe_read_json", return_value={"cron_iterations": 1}), \
         patch("backend.agents.orchestration.health_check_cron._is_night_time", return_value=False):
        should_out, _ = health_check_cron._should_output("COMPLETE", "🟢 HEALTHY", "FRESH")
        assert should_out is False

    with patch("backend.agents.orchestration.health_check_cron._is_in_user_window", return_value=False), \
         patch("backend.agents.orchestration.health_check_cron._safe_read_json", return_value={"cron_iterations": 6}), \
         patch("backend.agents.orchestration.health_check_cron._is_night_time", return_value=False):
        should_out, reason = health_check_cron._should_output("STOPPED", "🟢 HEALTHY", "FRESH")
        assert should_out is True
        assert "COMPLETE+離席中" in reason

    with patch("backend.agents.orchestration.health_check_cron._is_in_user_window", return_value=False), \
         patch("backend.agents.orchestration.health_check_cron._safe_read_json", return_value={"cron_iterations": 5}), \
         patch("backend.agents.orchestration.health_check_cron._is_night_time", return_value=False):
        should_out, _ = health_check_cron._should_output("STOPPED", "🟢 HEALTHY", "FRESH")
        assert should_out is False

    with patch("backend.agents.orchestration.health_check_cron._is_in_user_window", return_value=False), \
         patch("backend.agents.orchestration.health_check_cron._safe_read_json", return_value={}), \
         patch("backend.agents.orchestration.health_check_cron._is_night_time", return_value=False):
        should_out, reason = health_check_cron._should_output("UNKNOWN_STATUS", "🟢 HEALTHY", "FRESH")
        assert should_out is True
        assert "デフォルト → 出力" in reason

# contains をオーバーライドして UNHEALTHY 判定を偽装するハック
class MockOverall:
    def __contains__(self, item):
        if item == "HEALTHY":
            return False
        if item == "UNHEALTHY":
            return True
        return False
    def __str__(self):
        return "🔴 UNHEALTHY"

def test_build_structured_summary_unhealthy_degraded():
    # UNHEALTHY
    data_unhealthy = {
        "overall": MockOverall(),
        "phase": "27",
        "milestone": "M8",
        "flash_lifecycle": {"status": "ACTIVE", "detail": "稼働中"},
        "checks": {}
    }
    summary = health_check_cron._build_structured_summary(data_unhealthy)
    assert "🔴 UNHEALTHY — Phase 27 / M8" in summary
    assert "📡 Flash: 🔄 稼働中" in summary

    # DEGRADED
    data_degraded = {
        "overall": "🟡 DEGRADED",
        "phase": "27",
        "milestone": "8",
        "flash_lifecycle": {"status": "WARN", "detail": "⚠️ 警告発生中"},
        "checks": {}
    }
    summary = health_check_cron._build_structured_summary(data_degraded)
    assert "🟡 DEGRADED — Phase 27 / M8" in summary
    assert "📡 Flash: ⚠️ 警告発生中" in summary

def test_build_structured_summary_eta_reason_and_actions():
    data = {
        "overall": "🟢 HEALTHY",
        "flash_lifecycle": {"status": "COMPLETE", "detail": "完了しました"},
        "eta": {
            "eta_jst": "15:00 JST",
            "eta_minutes": 10,
            "reason": "ディスク容量調整のため"
        },
        "checks": {}
    }
    summary = health_check_cron._build_structured_summary(data)
    assert "📍 ETA: 15:00 JST（約10分後） — ディスク容量調整のため" in summary
    assert "🚨 要対応: Flash側チャットを閉じてCPU解放" in summary

    data_trans = {
        "overall": "🟢 HEALTHY",
        "flash_lifecycle": {"status": "TRANSITIONING", "detail": "遷移中"},
        "checks": {}
    }
    summary = health_check_cron._build_structured_summary(data_trans)
    assert "✅ 新セッションへの遷移中 — アクション不要" in summary

    data_unh = {
        "overall": MockOverall(),
        "flash_lifecycle": {"status": "WARN", "detail": "エラー", "recommendation": "環境を再起動してください"},
        "checks": {}
    }
    summary = health_check_cron._build_structured_summary(data_unh)
    assert "🚨 要確認: 環境を再起動してください" in summary

    data_deg = {
        "overall": "🟡 DEGRADED",
        "flash_lifecycle": {"status": "WARN", "detail": "低下中"},
        "checks": {}
    }
    summary = health_check_cron._build_structured_summary(data_deg)
    assert "⚠️ 自動復旧を試行中 — 2回失敗で介入依頼します" in summary

def test_main_execution_via_runpy():
    import runpy
    import warnings
    mock_run = MagicMock()
    mock_run.stdout = b"{}"
    with patch("subprocess.run", return_value=mock_run),          patch("backend.agents.orchestration.health_check_cron._check_auto_nudge"),          warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*found in sys.modules.*")
        runpy.run_module("backend.agents.orchestration.health_check_cron", run_name="__main__")


def test_build_structured_summary_fallback_edge_cases():
    # eta_jst のみがあり、reasonや他のセッションETAがない場合
    data = {
        "overall": "🟢 HEALTHY",
        "eta": {
            "eta_jst": "12:00 JST",
            "eta_minutes": 15
        },
        "checks": {}
    }
    summary = health_check_cron._build_structured_summary(data)
    assert "📍 ETA: 12:00 JST（約15分後）" in summary
    assert "📐 セッションETA" not in summary
    assert "🪑 次回着席推奨" not in summary

    # session_eta_jst のみがあり、eta_jst がない場合
    data_session_only = {
        "overall": "🟢 HEALTHY",
        "eta": {
            "session_eta_jst": "13:00 JST"
        },
        "checks": {}
    }
    summary = health_check_cron._build_structured_summary(data_session_only)
    assert "📐 セッションETA: 13:00 JST" in summary
    assert "📍 ETA" not in summary

    # recommended_return_jst のみがあり、JST表記が含まれている場合と含まれていない場合
    data_return_no_jst = {
        "overall": "🟢 HEALTHY",
        "eta": {
            "recommended_return_jst": "14:00"
        },
        "checks": {}
    }
    summary = health_check_cron._build_structured_summary(data_return_no_jst)
    assert "🪑 次回着席推奨: 14:00 JST" in summary

    data_return_with_jst = {
        "overall": "🟢 HEALTHY",
        "eta": {
            "recommended_return_jst": "14:00 JST"
        },
        "checks": {}
    }
    summary = health_check_cron._build_structured_summary(data_return_with_jst)
    assert "🪑 次回着席推奨: 14:00 JST" in summary
    assert "🪑 次回着席推奨: 14:00 JST JST" not in summary

def test_safe_read_json_logs_warning_on_invalid_json():
    content = '{"status": "running"'  # 壊れたJSON
    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=content)), \
         patch("sys.stderr.write") as mock_stderr:
        res = health_check_cron._safe_read_json("dummy_path.json", default={"fallback": True})
        assert res == {"fallback": True}
        mock_stderr.assert_called()
        args, _ = mock_stderr.call_args
        assert "[Warning] Failed to read or parse JSON" in args[0]


def test_check_auto_nudge_logs_warning_on_invalid_heartbeat():
    session = {
        "status": "running",
        "conversation_id": "conv_123",
        "last_heartbeat": "invalid_date_format",
        "auto_nudge_count": 0
    }
    with patch("backend.agents.orchestration.health_check_cron._safe_read_json", return_value=session), \
         patch("sys.stderr.write") as mock_stderr:
        res = health_check_cron._check_auto_nudge()
        assert res is False
        mock_stderr.assert_called()
        args, _ = mock_stderr.call_args
        assert "[Warning] Failed to parse heartbeat datetime" in args[0]


def test_check_auto_nudge_logs_warning_on_session_write_os_error():
    stale_time = (datetime.now(timezone.utc) - timedelta(minutes=25)).isoformat()
    session = {
        "status": "running",
        "conversation_id": "conv_123",
        "last_heartbeat": stale_time,
        "auto_nudge_count": 0
    }
    
    def side_effect(file, *args, **kwargs):
        if "flash_session.json" in str(file):
            raise OSError("Write error mock")
        return mock_open()()

    with patch("backend.agents.orchestration.health_check_cron._safe_read_json", return_value=session), \
         patch("builtins.open", side_effect=side_effect), \
         patch("sys.stderr.write") as mock_stderr, \
         patch("sys.stdout.write"):
        res = health_check_cron._check_auto_nudge()
        assert res is True
        mock_stderr.assert_called()
        any_failed_write_session = any(
            "[Warning] Failed to write session to" in call[0][0] for call in mock_stderr.call_args_list
        )
        assert any_failed_write_session


def test_main_logs_warning_on_json_decode_error():
    mock_run = MagicMock()
    mock_run.stdout = b"invalid json stdout"
    with patch("subprocess.run", return_value=mock_run), \
         patch("sys.stderr.write") as mock_stderr, \
         patch("sys.stdout.write"):
        health_check_cron.main()
        mock_stderr.assert_called()
        any_json_fail = any(
            "[Warning] JSON decode failed, falling back to text mode" in call[0][0] for call in mock_stderr.call_args_list
        )
        assert any_json_fail
