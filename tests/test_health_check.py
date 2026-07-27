# -*- coding: utf-8 -*-
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, mock_open, MagicMock

import pytest

from backend.agents.orchestration import health_check

# パスのモック設定
@pytest.fixture(autouse=True)
def mock_paths(tmp_path):
    # テストごとに一時的なパスに差し替える
    health_check.ORCHESTRATION_DIR = str(tmp_path)
    health_check.FLASH_SESSION_PATH = str(tmp_path / "flash_session.json")
    health_check.FLASH_REPORTS_PATH = str(tmp_path / "flash_reports.jsonl")
    health_check.PHASE_STATE_PATH = str(tmp_path / "phase_state.json")
    health_check.TASK_QUEUE_PATH = str(tmp_path / "task_queue.json")
    health_check.OPUS_SESSION_PATH = str(tmp_path / "opus_session.json")
    health_check.EVENT_LOG_PATH = str(tmp_path / "event_log.jsonl")
    health_check.USER_SCHEDULE_PATH = str(tmp_path / "user_schedule.json")
    health_check.ETA_STORE_PATH = str(tmp_path / "eta_tracker.json")
    
    # hub_common および Mixin / Orchestrator モジュール側のパスも一括 mock
    from backend.agents.orchestration import hub_common, hub_status, hub_session, hub_gate, hub_batch, hub_reports, orchestrator
    
    modules_to_mock = [hub_common, hub_status, hub_session, hub_gate, hub_batch, hub_reports, orchestrator]
    for mod in modules_to_mock:
        if hasattr(mod, "TASK_QUEUE_PATH"):
            mod.TASK_QUEUE_PATH = tmp_path / "task_queue.json"
        if hasattr(mod, "FLASH_REPORTS_PATH"):
            mod.FLASH_REPORTS_PATH = tmp_path / "flash_reports.jsonl"
        if hasattr(mod, "PHASE_STATE_PATH"):
            mod.PHASE_STATE_PATH = tmp_path / "phase_state.json"
        if hasattr(mod, "FLASH_SESSION_PATH"):
            mod.FLASH_SESSION_PATH = tmp_path / "flash_session.json"
        if hasattr(mod, "USER_SCHEDULE_PATH"):
            mod.USER_SCHEDULE_PATH = tmp_path / "user_schedule.json"
        if hasattr(mod, "ETA_STORE_PATH"):
            mod.ETA_STORE_PATH = tmp_path / "eta_tracker.json"
        if hasattr(mod, "OPUS_DIRECTIVE_PATH"):
            mod.OPUS_DIRECTIVE_PATH = tmp_path / "opus_directive.json"
        if hasattr(mod, "MESSAGE_BOX_PATH"):
            mod.MESSAGE_BOX_PATH = tmp_path / "message_box.jsonl"
        if hasattr(mod, "OPUS_SESSION_PATH"):
            mod.OPUS_SESSION_PATH = tmp_path / "opus_session.json"
    
    # 差し替えたパスのファイルを初期化
    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({"status": "running", "last_heartbeat": datetime.now(timezone.utc).isoformat()}, f)
    with open(health_check.PHASE_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({"current_phase": 27, "current_milestone": "M27.1"}, f)
    with open(health_check.TASK_QUEUE_PATH, "w", encoding="utf-8") as f:
        json.dump({"tasks": []}, f)
    with open(health_check.OPUS_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({"session_started_at": datetime.now(timezone.utc).isoformat(), "cron_iterations": 0}, f)
    
    return tmp_path


# 1. _parse_iso のテスト
def test_parse_iso():
    formats = [
        "2026-06-02T09:51:08.123456+09:00",
        "2026-06-02T09:51:08+09:00",
        "2026-06-02T09:51:08.123456Z",
        "2026-06-02T09:51:08Z",
        "2026-06-02T09:51:08.123456",
        "2026-06-02T09:51:08",
    ]
    for fmt_str in formats:
        dt = health_check._parse_iso(fmt_str)
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 6
        assert dt.day == 2

    assert health_check._parse_iso("invalid-date") is None
    assert health_check._parse_iso("") is None
    assert health_check._parse_iso(None) is None


# 2. _safe_read_json のテスト
def test_safe_read_json(tmp_path):
    path = tmp_path / "test.json"
    assert health_check._safe_read_json(str(path), default={"a": 1}) == {"a": 1}
    
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"a": 2}, f)
    assert health_check._safe_read_json(str(path)) == {"a": 2}
    
    with open(path, "w", encoding="utf-8") as f:
        f.write("{invalid json")
    assert health_check._safe_read_json(str(path), default={"a": 3}) == {"a": 3}

    # 例外発生時の挙動 (FileNotFoundError以外)
    with patch("builtins.open", side_effect=PermissionError("Permission Denied")):
        assert health_check._safe_read_json(str(path), default={"a": 4}) == {"a": 4}


# 3. _calc_hb_minutes のテスト
def test_calc_hb_minutes():
    assert health_check._calc_hb_minutes(None) is None
    assert health_check._calc_hb_minutes("") is None
    assert health_check._calc_hb_minutes("invalid") is None

    now = datetime.now(timezone.utc)
    ten_min_ago = (now - timedelta(minutes=10)).isoformat()
    assert health_check._calc_hb_minutes(ten_min_ago) == 10


# 4. reset_opus_session のテスト
def test_reset_opus_session():
    conv_id = "test_conversation_123"
    res = health_check.reset_opus_session(conv_id)
    
    assert res["conversation_id"] == conv_id
    assert res["cron_iterations"] == 0
    assert "session_started_at" in res
    assert "last_cron_at" in res
    
    saved = health_check._safe_read_json(health_check.OPUS_SESSION_PATH)
    assert saved["conversation_id"] == conv_id


# 5. _send_stale_nudge のテスト
def test_send_stale_nudge():
    # status != running のとき
    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({"status": "stopped"}, f)
    
    if os.path.exists(health_check.EVENT_LOG_PATH):
        os.remove(health_check.EVENT_LOG_PATH)
        
    health_check._send_stale_nudge(20, "2026-06-02 09:51 JST")
    assert not os.path.exists(health_check.EVENT_LOG_PATH)

    # status == running のとき
    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({"status": "running"}, f)
    
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
        mock_hub = mock_hub_class.return_value
        health_check._send_stale_nudge(20, "2026-06-02 09:51 JST")
        mock_hub.send_message.assert_called_once()
        
    session = health_check._safe_read_json(health_check.FLASH_SESSION_PATH)
    assert "last_stale_nudge_at" in session
    assert os.path.exists(health_check.EVENT_LOG_PATH)
    
    # 2回目の呼び出し（10分以内のためスキップされる）
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
        mock_hub = mock_hub_class.return_value
        health_check._send_stale_nudge(22, "2026-06-02 09:51 JST")
        mock_hub.send_message.assert_not_called()

    # 例外発生時
    with patch("backend.agents.orchestration.OrchestrationHub", side_effect=Exception("Network Error")):
        # 例外が内部でキャッチされ、クラッシュしないことを確認
        health_check._send_stale_nudge(20, "2026-06-02 09:51 JST")


# 6. _auto_stop_stale_session のテスト
def test_auto_stop_stale_session():
    # 分岐1: セッション情報がない or running でない
    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({"status": "stopped"}, f)
    assert health_check._auto_stop_stale_session(20) == "none"

    # セッション status = running に設定
    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({"status": "running"}, f)

    # Stage 1: hb_minutes <= 30
    # 15分未満 -> ナッジなし、戻り値 none
    with patch("backend.agents.orchestration.health_check._send_stale_nudge") as mock_nudge:
        assert health_check._auto_stop_stale_session(10) == "none"
        mock_nudge.assert_not_called()

    # 15分以上30分以下 -> ナッジ送信、戻り値 none
    with patch("backend.agents.orchestration.health_check._send_stale_nudge") as mock_nudge:
        assert health_check._auto_stop_stale_session(20) == "none"
        mock_nudge.assert_called_once()

    # ケースA: 残タスクなし (pending/running = 0)、心拍40分
    # threshold = 30 となり、hb_minutes(40) > dead_threshold(30) -> Stage 3 (DEAD: stopped)
    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({"status": "running"}, f)
    with open(health_check.TASK_QUEUE_PATH, "w", encoding="utf-8") as f:
        json.dump({"tasks": [{"status": "completed"}]}, f)
        
    assert health_check._auto_stop_stale_session(40) == "stopped"
    session = health_check._safe_read_json(health_check.FLASH_SESSION_PATH)
    assert session["status"] == "stopped"
    assert "heartbeat_stale_40min_threshold_30min" in session["auto_stop_reason"]

    # ケースB: 残タスクあり (pending=1)、心拍40分
    # threshold = 60 となり、hb_minutes(40) <= dead_threshold(60) -> Stage 2 (UNREACHABLE: warned)
    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({"status": "running"}, f)
    with open(health_check.TASK_QUEUE_PATH, "w", encoding="utf-8") as f:
        json.dump({"tasks": [{"status": "pending"}]}, f)
        
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
        mock_hub = mock_hub_class.return_value
        mock_hub._recover_timed_out_tasks.return_value = True
        assert health_check._auto_stop_stale_session(40) == "warned"
        
    session = health_check._safe_read_json(health_check.FLASH_SESSION_PATH)
    assert session["status"] == "running"
    assert session["heartbeat_warning"] == "stale_40min"

    # 例外時のフォールバック (TASK_QUEUE_PATH が破損している場合など)
    bak_path = health_check.TASK_QUEUE_PATH + ".bak"
    if os.path.exists(bak_path):
        os.remove(bak_path)
    with open(health_check.TASK_QUEUE_PATH, "w", encoding="utf-8") as f:
        f.write("{corrupt")
    # 例外がキャッチされ、pending_count=0 と見なされる
    assert health_check._auto_stop_stale_session(40) == "stopped"


# 7. check_heartbeat のテスト
def test_check_heartbeat():
    if os.path.exists(health_check.FLASH_SESSION_PATH):
        os.remove(health_check.FLASH_SESSION_PATH)
    res = health_check.check_heartbeat()
    assert res["status"] == "FAIL"
    assert "flash_session.json が見つかりません" in res["detail"]

    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({"status": "running"}, f)
    res = health_check.check_heartbeat()
    assert res["status"] == "FAIL"
    assert "last_heartbeat フィールドがありません" in res["detail"]

    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({"status": "running", "last_heartbeat": "invalid"}, f)
    res = health_check.check_heartbeat()
    assert res["status"] == "FAIL"
    assert "心拍日時をパースできません" in res["detail"]

    now = datetime.now(timezone.utc)
    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({"status": "running", "last_heartbeat": (now - timedelta(minutes=5)).isoformat()}, f)
    res = health_check.check_heartbeat()
    assert res["status"] == "PASS"

    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({"status": "running", "last_heartbeat": (now - timedelta(minutes=20)).isoformat()}, f)
    res = health_check.check_heartbeat()
    assert res["status"] == "WARN"

    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({"status": "running", "last_heartbeat": (now - timedelta(minutes=45)).isoformat()}, f)
    res = health_check.check_heartbeat()
    assert res["status"] == "FAIL"


# 8. check_git_commits のテスト
def test_check_git_commits():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="error")
        res = health_check.check_git_commits()
        assert res["status"] == "FAIL"
        assert "git log 実行失敗" in res["detail"]

    with patch("subprocess.run", side_effect=Exception("command not found")):
        res = health_check.check_git_commits()
        assert res["status"] == "FAIL"
        assert "Git検証エラー" in res["detail"]

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="hash1 2026-06-02T09:00:00Z Regular commit\n")
        res = health_check.check_git_commits()
        assert res["status"] == "WARN"
        assert "直近20コミットにFlashコミットなし" in res["detail"]

    now = datetime.now(timezone.utc)
    commit_time = (now - timedelta(minutes=10)).isoformat()
    git_stdout = f"hash1 {commit_time} [Flash/test] Test commit\n"
    
    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({"status": "running", "last_heartbeat": commit_time}, f)
        
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=git_stdout)
        res = health_check.check_git_commits()
        assert res["status"] == "PASS"
        assert "心拍と整合" in res["detail"]

    commit_time_old = (now - timedelta(minutes=45)).isoformat()
    git_stdout_old = f"hash1 {commit_time_old} [Flash/test] Test commit\n"
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=git_stdout_old)
        res = health_check.check_git_commits()
        assert res["status"] == "WARN"
        assert "心拍との乖離" in res["detail"]


# 9. check_batch_consistency のテスト
def test_check_batch_consistency():
    if os.path.exists(health_check.FLASH_REPORTS_PATH):
        os.remove(health_check.FLASH_REPORTS_PATH)
        
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        res = health_check.check_batch_consistency()
        assert res["status"] == "WARN"
        assert "バッチ履歴・Gitコミットともに0件" in res["detail"]

    with open(health_check.FLASH_REPORTS_PATH, "w", encoding="utf-8") as f:
        f.write(json.dumps({"results": {"passed": 2, "failed": 0}}) + "\n")
        f.write(json.dumps({"results": {"passed": 1, "failed": 0}}) + "\n")
        f.write(json.dumps({"results": {"passed": 3, "failed": 1}}) + "\n")
        
    git_oneline = "hash1\nhash2\nhash3\n"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=git_oneline)
        res = health_check.check_batch_consistency()
        assert res["status"] == "PASS"
        assert "整合" in res["detail"]
        assert res["report_batches"] == 3
        assert res["git_commits"] == 3
        assert res["report_tasks"] == 7

    git_oneline_many = "hash\n" * 10
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=git_oneline_many)
        res = health_check.check_batch_consistency()
        assert res["status"] == "WARN"
        assert "乖離" in res["detail"]


# 10. check_session_status のテスト
def test_check_session_status():
    if os.path.exists(health_check.FLASH_SESSION_PATH):
        os.remove(health_check.FLASH_SESSION_PATH)
    res = health_check.check_session_status()
    assert res["status"] == "FAIL"

    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({"status": "stopped"}, f)
    res = health_check.check_session_status()
    assert res["status"] == "WARN"
    assert "stopped" in res["detail"]

    now = datetime.now(timezone.utc)
    old_time = (now - timedelta(minutes=40)).isoformat()
    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({"status": "running", "last_heartbeat": old_time}, f)
    
    with patch("backend.agents.orchestration.health_check._auto_stop_stale_session", return_value="stopped"):
        res = health_check.check_session_status()
        assert res["status"] == "FAIL"
        assert "自動停止しました" in res["detail"]

    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({"status": "running", "last_heartbeat": old_time}, f)
        
    with patch("backend.agents.orchestration.health_check._auto_stop_stale_session", return_value="warned"):
        res = health_check.check_session_status()
        assert res["status"] == "WARN"
        assert "Hub連携維持中" in res["detail"]

    recent_time = (now - timedelta(minutes=5)).isoformat()
    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({"status": "running", "last_heartbeat": recent_time, "heartbeat_warning": "stale_40min"}, f)
        
    res = health_check.check_session_status()
    assert res["status"] == "PASS"
    session = health_check._safe_read_json(health_check.FLASH_SESSION_PATH)
    assert "heartbeat_warning" not in session


# 11. assess_flash_lifecycle のテスト
def test_assess_flash_lifecycle():
    if os.path.exists(health_check.FLASH_SESSION_PATH):
        os.remove(health_check.FLASH_SESSION_PATH)
    res = health_check.assess_flash_lifecycle()
    assert res["status"] == "INFO"

    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({"status": "ended", "tasks_completed_in_session": 10, "batches_in_session": 2}, f)
    res = health_check.assess_flash_lifecycle()
    assert res["status"] == "COMPLETE"
    assert "完遂済み" in res["detail"]

    now = datetime.now(timezone.utc)
    recent_time = (now - timedelta(minutes=2)).isoformat()
    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "status": "stopped",
            "auto_stop_reason": "new_session_requested",
            "last_heartbeat": recent_time,
            "tasks_completed_in_session": 5
        }, f)
    res = health_check.assess_flash_lifecycle()
    assert res["status"] == "TRANSITIONING"
    assert "遷移中" in res["detail"]

    old_time = (now - timedelta(minutes=10)).isoformat()
    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "status": "stopped",
            "auto_stop_reason": "new_session_requested",
            "last_heartbeat": old_time,
            "tasks_completed_in_session": 5
        }, f)
    res = health_check.assess_flash_lifecycle()
    assert res["status"] == "COMPLETE"

    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({"status": "running", "tasks_completed_in_session": 5}, f)
    with open(health_check.TASK_QUEUE_PATH, "w", encoding="utf-8") as f:
        json.dump({"tasks": []}, f)
    res = health_check.assess_flash_lifecycle()
    assert res["status"] == "FINISHING"

    start_time = (now - timedelta(hours=13)).isoformat()
    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "status": "running",
            "session_started_at": start_time,
            "tasks_completed_in_session": 5
        }, f)
    with open(health_check.TASK_QUEUE_PATH, "w", encoding="utf-8") as f:
        json.dump({"tasks": [{"status": "pending"}]}, f)
    res = health_check.assess_flash_lifecycle()
    assert res["status"] == "WARN"

    start_time_recent = (now - timedelta(hours=3)).isoformat()
    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "status": "running",
            "session_started_at": start_time_recent,
            "tasks_completed_in_session": 5
        }, f)
    res = health_check.assess_flash_lifecycle()
    assert res["status"] == "ACTIVE"


# 12. assess_opus_session のテスト
def test_assess_opus_session():
    now = datetime.now(timezone.utc)
    
    start_fresh = (now - timedelta(hours=4)).isoformat()
    with open(health_check.OPUS_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({"session_started_at": start_fresh, "cron_iterations": 5}, f)
    
    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({"status": "running"}, f)
        
    sugg, health = health_check.assess_opus_session()
    assert health["stage"] == "FRESH"
    assert health["uptime_hours"] == 4.0

    start_aging = (now - timedelta(hours=10)).isoformat()
    with open(health_check.OPUS_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({"session_started_at": start_aging, "cron_iterations": 10}, f)
    sugg, health = health_check.assess_opus_session()
    assert health["stage"] == "AGING"
    assert any("AGING" in s for s in sugg)

    start_stale = (now - timedelta(hours=18)).isoformat()
    with open(health_check.OPUS_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({"session_started_at": start_stale, "cron_iterations": 20}, f)
    sugg, health = health_check.assess_opus_session()
    assert health["stage"] == "STALE"
    assert any("STALE" in s for s in sugg)

    with open(health_check.PHASE_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({"current_phase": 27}, f)
    sugg, health = health_check.assess_opus_session()
    assert any("ロードマップ完了目前" in s for s in sugg)

    with open(health_check.PHASE_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({"current_phase": 25}, f)
    sugg, health = health_check.assess_opus_session()
    assert any("残4Phase" in s for s in sugg)


# 13. _compute_eta_and_next_check のテスト
def test_compute_eta_and_next_check():
    now = datetime.now(timezone.utc)
    
    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({"status": "ended"}, f)
    res = health_check._compute_eta_and_next_check()
    assert "完遂済み" in res["reason"]
    assert res["next_check_minutes"] == 0

    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({"status": "running"}, f)
    with open(health_check.TASK_QUEUE_PATH, "w", encoding="utf-8") as f:
        json.dump({"tasks": []}, f)
    res = health_check._compute_eta_and_next_check()
    assert "残タスクなし" in res["reason"]
    assert res["next_check_minutes"] == 10

    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({"status": "running", "tasks_completed_in_session": 0}, f)
    with open(health_check.TASK_QUEUE_PATH, "w", encoding="utf-8") as f:
        json.dump({"tasks": [{"status": "pending"}]}, f)
    if os.path.exists(health_check.FLASH_REPORTS_PATH):
        os.remove(health_check.FLASH_REPORTS_PATH)
    res = health_check._compute_eta_and_next_check()
    assert "スループット" in res["reason"]
    assert res["next_check_minutes"] == 15

    with open(health_check.FLASH_REPORTS_PATH, "w", encoding="utf-8") as f:
        entry = {"timestamp": now.isoformat(), "results": {"passed": 5, "failed": 0}}
        f.write(json.dumps(entry) + "\n")
        
    with open(health_check.TASK_QUEUE_PATH, "w", encoding="utf-8") as f:
        tasks = [{"status": "pending"}] * 10
        json.dump({"tasks": tasks}, f)
        
    res = health_check._compute_eta_and_next_check()
    assert res["eta_minutes"] == 120
    assert res["next_check_minutes"] == 100

    # スケジュール窓外のテスト
    with open(health_check.USER_SCHEDULE_PATH, "w", encoding="utf-8") as f:
        schedule = {
            "weekday": {
                "windows": [
                    {"start": "01:00", "end": "03:00", "label": "深夜窓"}
                ]
            },
            "weekend": {
                "windows": []
            }
        }
        json.dump(schedule, f)
        
    res_out = health_check._compute_eta_and_next_check()
    assert "recommended_return_jst" in res_out

    # eta_tracker.json のロード例外時のフォールバック
    with open(health_check.ETA_STORE_PATH, "w", encoding="utf-8") as f:
        f.write("{corrupted")
    res_corr = health_check._compute_eta_and_next_check()
    assert "eta_minutes" in res_corr


# 14. run_health_check のテスト
def test_run_health_check():
    # 全て PASS
    with patch("backend.agents.orchestration.health_check.check_heartbeat", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.check_git_commits", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.check_batch_consistency", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.check_session_status", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.check_loop_stagnation", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.check_ux_ratchet_health", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.check_metrics_lock", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.evaluate_effectiveness_gate", return_value={"failed": False}), \
         patch("backend.agents.orchestration.health_check.assess_flash_lifecycle", return_value={"status": "ACTIVE", "detail": "test", "recommendation": "test"}), \
         patch("backend.agents.orchestration.health_check._compute_eta_and_next_check", return_value={"reason": "test"}), \
         patch("backend.agents.orchestration.health_check.assess_opus_session", return_value=([], {"stage": "FRESH"})):
        
        res = health_check.run_health_check()
        assert "HEALTHY" in res["overall"]

    # FAIL あり
    with patch("backend.agents.orchestration.health_check.check_heartbeat", return_value={"status": "FAIL", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.check_git_commits", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.check_batch_consistency", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.check_session_status", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.check_loop_stagnation", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.check_ux_ratchet_health", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.check_metrics_lock", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.evaluate_effectiveness_gate", return_value={"failed": False}), \
         patch("backend.agents.orchestration.health_check.assess_flash_lifecycle", return_value={"status": "ACTIVE", "detail": "test", "recommendation": "test"}), \
         patch("backend.agents.orchestration.health_check._compute_eta_and_next_check", return_value={"reason": "test"}), \
         patch("backend.agents.orchestration.health_check.assess_opus_session", return_value=([], {"stage": "FRESH"})):
        
        res = health_check.run_health_check()
        assert "UNHEALTHY" in res["overall"]

    # 心拍正常でバッチ乖離のみ WARN
    with patch("backend.agents.orchestration.health_check.check_heartbeat", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.check_git_commits", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.check_batch_consistency", return_value={"status": "WARN", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.check_session_status", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.check_loop_stagnation", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.check_ux_ratchet_health", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.check_metrics_lock", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.evaluate_effectiveness_gate", return_value={"failed": False}), \
         patch("backend.agents.orchestration.health_check.assess_flash_lifecycle", return_value={"status": "ACTIVE", "detail": "test", "recommendation": "test"}), \
         patch("backend.agents.orchestration.health_check._compute_eta_and_next_check", return_value={"reason": "test"}), \
         patch("backend.agents.orchestration.health_check.assess_opus_session", return_value=([], {"stage": "FRESH"})):
        
        res = health_check.run_health_check()
        assert "HEALTHY" in res["overall"]

    # その他 (DEGRADED)
    with patch("backend.agents.orchestration.health_check.check_heartbeat", return_value={"status": "WARN", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.check_git_commits", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.check_batch_consistency", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.check_session_status", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.check_loop_stagnation", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.check_ux_ratchet_health", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.check_metrics_lock", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.evaluate_effectiveness_gate", return_value={"failed": False}), \
         patch("backend.agents.orchestration.health_check.assess_flash_lifecycle", return_value={"status": "ACTIVE", "detail": "test", "recommendation": "test"}), \
         patch("backend.agents.orchestration.health_check._compute_eta_and_next_check", return_value={"reason": "test"}), \
         patch("backend.agents.orchestration.health_check.assess_opus_session", return_value=([], {"stage": "FRESH"})):
        
        res = health_check.run_health_check()
        assert "DEGRADED" in res["overall"]


# 新規追加テスト: 効果検証ゲートしきい値逸脱時の overall 変化テスト
def test_run_health_check_effectiveness_gate():
    # 通常は HEALTHY だが、効果検証ゲートでエラーになった場合の DEGRADED 判定（current_milestone != M34.2）
    with patch("backend.agents.orchestration.health_check.check_heartbeat", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.check_git_commits", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.check_batch_consistency", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.check_session_status", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.check_loop_stagnation", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.check_ux_ratchet_health", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.check_metrics_lock", return_value={"status": "PASS", "detail": "test"}), \
         patch("backend.agents.orchestration.health_check.evaluate_effectiveness_gate", return_value={"failed": True, "report_path": "warning.md", "wasted_rate": 55.0, "dep_leak_fails": 3}), \
         patch("backend.agents.orchestration.health_check.assess_flash_lifecycle", return_value={"status": "ACTIVE", "detail": "test", "recommendation": "test"}), \
         patch("backend.agents.orchestration.health_check._compute_eta_and_next_check", return_value={"reason": "test"}), \
         patch("backend.agents.orchestration.health_check.assess_opus_session", return_value=([], {"stage": "FRESH"})):
        
        # マイルストーンが M34.2 以外 (初期値は mock_paths により M27.1)
        res = health_check.run_health_check()
        assert res["overall"] == "🟡 DEGRADED"
        assert "効果検証しきい値逸脱" in res["report"]

        # マイルストーンが M34.2 の場合は UNHEALTHY
        with open(health_check.PHASE_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump({"current_phase": 34, "current_milestone": "M34.2"}, f)
        
        res = health_check.run_health_check()
        assert res["overall"] == "🔴 UNHEALTHY"

# 15. main のテスト
def test_main():
    # 1. argv モック (--json あり)
    with patch("sys.argv", ["health_check.py", "--json"]), \
         patch("backend.agents.orchestration.health_check.run_health_check") as mock_run_hc, \
         patch("backend.agents.orchestration.health_check.assess_opus_session", return_value=([], {})):
        
        mock_run_hc.return_value = {
            "overall": "🟢 HEALTHY",
            "checks": [("check1", {"status": "PASS", "detail": "test"})],
            "flash_lifecycle": {"status": "ACTIVE"},
            "eta": {"reason": "test"},
            "phase_data": {"current_phase": 27}
        }
        
        # 画面出力のキャプチャで JSON 出力されるか検証
        with patch("builtins.print") as mock_print:
            health_check.main()
            mock_print.assert_called_once()
            args = mock_print.call_args[0][0]
            parsed = json.loads(args)
            assert parsed["overall"] == "🟢 HEALTHY"

    # 2. argv モック (--json なし)
    with patch("sys.argv", ["health_check.py"]), \
         patch("backend.agents.orchestration.health_check.run_health_check") as mock_run_hc:
        
        mock_run_hc.return_value = {
            "overall": "🟢 HEALTHY",
            "checks": [("check1", {"status": "PASS", "detail": "test"})],
            "flash_lifecycle": {"status": "ACTIVE"},
            "eta": {"reason": "test"},
            "phase_data": {"current_phase": 27},
            "report": "This is report"
        }
        
        with patch("builtins.print") as mock_print:
            health_check.main()
            mock_print.assert_any_call("This is report")

    # 3. 自動ナッジ送信 & クールダウン判定
    # DEGRADED 時
    with patch("sys.argv", ["health_check.py"]), \
         patch("backend.agents.orchestration.health_check.run_health_check") as mock_run_hc, \
         patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
        
        mock_run_hc.return_value = {
            "overall": "🟡 DEGRADED",
            "checks": [], "flash_lifecycle": {}, "eta": {}, "phase_data": {}, "report": "report"
        }
        mock_hub = mock_hub_class.return_value
        
        # すでにナッジされたメッセージが存在する場合 (クールダウン内)
        now_utc = datetime.now(timezone.utc)
        recent_nudge = {
            "content": "【自動ナッジ】",
            "timestamp": now_utc.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        }
        mock_hub.read_messages.return_value = [recent_nudge]
        
        health_check.main()
        mock_hub.send_message.assert_not_called()

        # ナッジ履歴が古い場合 (ナッジ送信される)
        mock_hub.send_message.reset_mock()
        old_time = now_utc - timedelta(minutes=20)
        old_nudge = {
            "content": "【自動ナッジ】",
            "timestamp": old_time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        }
        mock_hub.read_messages.return_value = [old_nudge]
        
        health_check.main()
        mock_hub.send_message.assert_called_once()

    # 4. 復旧プロンプトの自動生成 & クールダウン判定
    # UNHEALTHY 時
    with patch("sys.argv", ["health_check.py"]), \
         patch("backend.agents.orchestration.health_check.run_health_check") as mock_run_hc, \
         patch("backend.agents.orchestration.generate_flash_prompt.generate_prompt", return_value="dummy_prompt") as mock_gen_prompt:
        
        mock_run_hc.return_value = {
            "overall": "🔴 UNHEALTHY",
            "checks": [], "flash_lifecycle": {"status": "COMPLETE"}, "eta": {}, "phase_data": {}, "report": "report"
        }
        
        # クールダウン対象外 (直前30分以内に generate_flash_prompt が実行されていない)
        with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
            json.dump({"auto_stopped_at": None}, f)
            
        health_check.main()
        mock_gen_prompt.assert_called_once()

    # 5. --update-dashboard のテスト
    with patch("sys.argv", ["health_check.py", "--update-dashboard"]), \
         patch("backend.agents.orchestration.health_check.run_health_check") as mock_run_hc, \
         patch("backend.agents.orchestration.harness_auditor.run_all_audits") as mock_audits, \
         patch("backend.agents.orchestration.generate_subagent_reports.generate_dashboard_quick", return_value="dashboard_path") as mock_gen_dash:
         
        mock_run_hc.return_value = {
            "overall": "🟢 HEALTHY",
            "checks": [], "flash_lifecycle": {}, "eta": {}, "phase_data": {}, "report": "report"
        }
        
        health_check.main()
        mock_audits.assert_called_once()
        mock_gen_dash.assert_called_once()

    # 6. プロンプト生成クールダウン
    with patch("sys.argv", ["health_check.py"]), \
         patch("backend.agents.orchestration.health_check.run_health_check") as mock_run_hc, \
         patch("backend.agents.orchestration.generate_flash_prompt.generate_prompt") as mock_gen_prompt:
         
        mock_run_hc.return_value = {
            "overall": "🔴 UNHEALTHY",
            "checks": [], "flash_lifecycle": {"status": "COMPLETE"}, "eta": {}, "phase_data": {}, "report": "report"
        }
        
        # 直前5分前に自動停止された場合 (クールダウン中)
        now = datetime.now(timezone.utc)
        with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "auto_stopped_at": (now - timedelta(minutes=5)).isoformat(),
                "auto_stop_reason": "new_session_requested"
            }, f)
            
        health_check.main()
        mock_gen_prompt.assert_not_called()


# 16. run_health_check ガイダンス出力のテスト
def test_run_health_check_guidance():
    # R7: COMPLETE/ended 時の自動案内
    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "status": "ended",
            "last_heartbeat": datetime.now(timezone.utc).isoformat(),
            "tasks_completed_in_session": 10,
            "batches_in_session": 2
        }, f)
        
    res = health_check.run_health_check()
    assert "Flash側チャットを閉じる" in res["report"]
    assert "Antigravityアプリ全体を終了" in res["report"]

    # R7: UNHEALTHY / 自動停止時の案内
    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "status": "stopped",
            "auto_stop_reason": "heartbeat_stale_40min_threshold_30min",
            "last_heartbeat": (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat(),
            "tasks_completed_in_session": 5
        }, f)
        
    res = health_check.run_health_check()
    assert "Flash側チャットを閉じる" in res["report"]


# 17. _compute_eta_and_next_check の窓内・遅延検知テスト
def test_compute_eta_additional_paths():
    now = datetime.now(timezone.utc)
    now_jst = now.astimezone(timezone(timedelta(hours=9)))
    
    current_day = "weekday" if now_jst.weekday() < 5 else "weekend"
    # ETAが2時間後になるため、窓を広めに設定する
    start_str = (now_jst - timedelta(hours=1)).strftime("%H:%M")
    end_str = (now_jst + timedelta(hours=4)).strftime("%H:%M")
    
    with open(health_check.USER_SCHEDULE_PATH, "w", encoding="utf-8") as f:
        schedule = {
            "weekday": {"windows": [{"start": start_str, "end": end_str, "label": "テスト窓"}]},
            "weekend": {"windows": [{"start": start_str, "end": end_str, "label": "テスト窓"}]}
        }
        json.dump(schedule, f)
        
    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "status": "running",
            "session_started_at": (now - timedelta(hours=1)).isoformat(), # 1時間前に開始
            "tasks_completed_in_session": 5, # 5タスク完了
            "context_consumption_pct": 10, # 10% コンテキスト消費
            "last_heartbeat": now.isoformat()
        }, f)
        
    with open(health_check.TASK_QUEUE_PATH, "w", encoding="utf-8") as f:
        json.dump({"tasks": [{"status": "pending"}] * 10}, f)
        
    res = health_check._compute_eta_and_next_check()
    assert res["recommended_return_jst"] == start_str

    # drift_minutes のプラス方向 (遅延) のテスト
    with open(health_check.ETA_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "eta_timestamp": (now + timedelta(minutes=30)).isoformat(),
            "next_check_jst": "10:00"
        }, f)
        
    with open(health_check.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "status": "running",
            "session_started_at": (now - timedelta(hours=1)).isoformat(),
            "tasks_completed_in_session": 5,
            "last_heartbeat": now.isoformat()
        }, f)
        
    res_drift = health_check._compute_eta_and_next_check()
    assert "drift_minutes" in res_drift


# 18. main 内の nudge クールダウンの別パターン
def test_main_nudge_no_nudge_content():
    with patch("sys.argv", ["health_check.py"]), \
         patch("backend.agents.orchestration.health_check.run_health_check") as mock_run_hc, \
         patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
         
        mock_run_hc.return_value = {
            "overall": "🟡 DEGRADED",
            "checks": [], "flash_lifecycle": {}, "eta": {}, "phase_data": {}, "report": "report"
        }
        mock_hub = mock_hub_class.return_value
        
        mock_hub.read_messages.return_value = [
            {"content": "普通のメッセージ", "timestamp": datetime.now(timezone.utc).isoformat() + "Z"}
        ]
        
        health_check.main()
        mock_hub.send_message.assert_called_once()
