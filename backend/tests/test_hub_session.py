import json
import os
from datetime import datetime, timezone, timedelta
import pytest
from unittest.mock import patch, MagicMock

from backend.agents.orchestration.hub_session import SessionMixin
from backend.agents.orchestration.hub_common import _now_iso


class DummyOrchestrator(SessionMixin):
    """SessionMixinをテストするためのダミーオーケストレーター"""

    def __init__(self):
        self.messages = []
        self.phase_state = {"emergency_stop": False, "stop_reason": ""}
        self.flash_status = {"context_pct": 10, "archive_urgency": "ok"}

    def generate_flash_status(self) -> dict:
        return self.flash_status

    def get_phase_state(self) -> dict:
        return self.phase_state

    def send_message(self, sender: str, recipient: str, message: str, priority: str = "normal") -> str:
        msg_id = f"msg-{len(self.messages) + 1}"
        self.messages.append({
            "id": msg_id,
            "sender": sender,
            "recipient": recipient,
            "message": message,
            "priority": priority
        })
        return msg_id


@pytest.fixture
def temp_paths(tmp_path, monkeypatch):
    """セッション関連 of JSONファイルパスをテスト用の一時フォルダに差し替えるフィクスチャ"""
    session_json = tmp_path / "flash_session.json"
    directive_json = tmp_path / "opus_directive.json"
    event_log = tmp_path / "event_log.jsonl"

    monkeypatch.setattr("backend.agents.orchestration.hub_session.FLASH_SESSION_PATH", session_json)
    monkeypatch.setattr("backend.agents.orchestration.hub_session.OPUS_DIRECTIVE_PATH", directive_json)

    return {
        "session": session_json,
        "directive": directive_json,
        "event_log": event_log
    }


def test_flash_session_start(temp_paths):
    orchestrator = DummyOrchestrator()
    orchestrator.flash_session_start()

    assert temp_paths["session"].exists()
    with open(temp_paths["session"], "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["status"] == "running"
    assert data["exit_reason"] is None
    assert data["progress_pct"] == 0
    assert data["current_activity"] == "initializing"
    assert data["recent_errors"] == []


def test_flash_update_status(temp_paths):
    orchestrator = DummyOrchestrator()
    orchestrator.flash_session_start()

    orchestrator.flash_update_status(
        activity="executing",
        step="Step 2: タスク実行中",
        batch_id="batch_abc123",
        task_group="bug_hunter",
        progress_pct=45,
        subagents_running=2,
        subagents_completed=3
    )

    with open(temp_paths["session"], "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["current_activity"] == "executing"
    assert data["current_step"] == "Step 2: タスク実行中"
    assert data["current_batch_id"] == "batch_abc123"
    assert data["current_task_group"] == "bug_hunter"
    assert data["progress_pct"] == 45
    assert data["subagents_running"] == 2
    assert data["subagents_completed"] == 3


def test_flash_report_error(temp_paths):
    orchestrator = DummyOrchestrator()
    orchestrator.flash_session_start()

    # エラーを12件報告して、最新10件のみが保存されることを検証
    for i in range(12):
        orchestrator.flash_report_error(error_summary=f"Err {i}", module=f"mod_{i}")

    with open(temp_paths["session"], "r", encoding="utf-8") as f:
        data = json.load(f)

    assert len(data["recent_errors"]) == 10
    assert data["recent_errors"][0]["error"] == "Err 2"
    assert data["recent_errors"][-1]["error"] == "Err 11"
    assert data["stall_count"] == 12


def test_flash_heartbeat_normal(temp_paths):
    orchestrator = DummyOrchestrator()
    orchestrator.flash_session_start()

    orchestrator.flash_heartbeat()

    with open(temp_paths["session"], "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["batches_in_session"] == 1
    assert data["stall_count"] == 0
    assert data["context_consumption_pct"] == 10
    assert data["context_pct_history"] == [10]


def test_flash_heartbeat_auto_recovery(temp_paths):
    orchestrator = DummyOrchestrator()
    orchestrator.flash_session_start()

    # 一度 stopped 状態にする
    with open(temp_paths["session"], "r", encoding="utf-8") as f:
        data = json.load(f)
    data["status"] = "stopped"
    data["auto_stop_reason"] = "resource_critical"
    with open(temp_paths["session"], "w", encoding="utf-8") as f:
        json.dump(data, f)

    # 心拍更新による自動復旧を検証
    orchestrator.flash_heartbeat()

    with open(temp_paths["session"], "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["status"] == "running"
    assert data["auto_stop_reason"] is None
    assert data["auto_stopped_at"] is None

    # イベントログが記録されているか検証
    event_log_path = temp_paths["session"].parent / "event_log.jsonl"
    assert event_log_path.exists()
    with open(event_log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["lifecycle"] == "AUTO_RECOVERED"


def test_register_flash_conversation_id(temp_paths):
    orchestrator = DummyOrchestrator()
    orchestrator.flash_session_start()

    orchestrator.register_flash_conversation_id("conv-999")

    with open(temp_paths["session"], "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["conversation_id"] == "conv-999"


def test_flash_update_heartbeat(temp_paths):
    orchestrator = DummyOrchestrator()
    orchestrator.flash_session_start()

    orchestrator.flash_update_heartbeat(context_pct=25)

    with open(temp_paths["session"], "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["context_consumption_pct"] == 25
    assert data["batches_in_session"] == 0  # バッチカウントは増えない


def test_flash_update_heartbeat_auto_recovery(temp_paths):
    orchestrator = DummyOrchestrator()
    orchestrator.flash_session_start()

    with open(temp_paths["session"], "r", encoding="utf-8") as f:
        data = json.load(f)
    data["status"] = "stopped"
    data["auto_stop_reason"] = "resource_critical"
    with open(temp_paths["session"], "w", encoding="utf-8") as f:
        json.dump(data, f)

    orchestrator.flash_update_heartbeat()

    with open(temp_paths["session"], "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["status"] == "running"
    assert data["auto_stop_reason"] is None


def test_flash_session_end(temp_paths):
    orchestrator = DummyOrchestrator()
    orchestrator.flash_session_start()

    orchestrator.flash_session_end(exit_reason="completed_all_tasks")

    with open(temp_paths["session"], "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["status"] == "ended"
    assert data["exit_reason"] == "completed_all_tasks"
    assert data["current_activity"] == "ended"

    assert len(orchestrator.messages) == 1
    assert orchestrator.messages[0]["message"] == "Flash セッション終了: completed_all_tasks"
    assert orchestrator.messages[0]["priority"] == "urgent"


def test_get_flash_session(temp_paths):
    orchestrator = DummyOrchestrator()
    assert orchestrator.get_flash_session() == {}

    orchestrator.flash_session_start()
    session = orchestrator.get_flash_session()
    assert session["status"] == "running"


def test_check_flash_alive(temp_paths):
    orchestrator = DummyOrchestrator()

    # セッションが存在しない場合
    alive_info = orchestrator.check_flash_alive()
    assert not alive_info["alive"]
    assert alive_info["status"] == "not_started"

    orchestrator.flash_session_start()

    # 正常な稼働状態
    alive_info = orchestrator.check_flash_alive()
    assert alive_info["alive"]
    assert alive_info["status"] == "running"

    # 心拍が古い場合（stale）
    with open(temp_paths["session"], "r", encoding="utf-8") as f:
        data = json.load(f)
    past_time = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat(timespec="seconds")
    data["last_heartbeat"] = past_time
    with open(temp_paths["session"], "w", encoding="utf-8") as f:
        json.dump(data, f)

    alive_info = orchestrator.check_flash_alive(timeout_minutes=30)
    assert not alive_info["alive"]
    assert alive_info["status"] == "stale"
    assert alive_info["minutes_since"] >= 45


def test_diagnose_flash_issues(temp_paths):
    orchestrator = DummyOrchestrator()

    # 1. 未起動状態の診断
    diagnosis = orchestrator.diagnose_flash_issues()
    assert diagnosis["needs_intervention"]
    assert any(issue["type"] == "not_started" for issue in diagnosis["issues"])

    orchestrator.flash_session_start()

    # 2. セッション終了状態の診断
    orchestrator.flash_session_end(exit_reason="finished")
    diagnosis = orchestrator.diagnose_flash_issues()
    assert diagnosis["needs_intervention"]
    assert any(issue["type"] == "session_ended" for issue in diagnosis["issues"])

    # セッションを一旦正常稼働に戻す
    orchestrator.flash_session_start()

    # 3. 連続エラー検知の診断
    for _ in range(3):
        orchestrator.flash_report_error("some error")

    diagnosis = orchestrator.diagnose_flash_issues()
    assert diagnosis["needs_intervention"]
    assert any(issue["type"] == "repeated_errors" for issue in diagnosis["issues"])

    # 4. 進捗停滞検知の診断
    # 心拍を15分前にし、進捗率を0にする
    with open(temp_paths["session"], "r", encoding="utf-8") as f:
        data = json.load(f)
    past_time = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat(timespec="seconds")
    data["last_heartbeat"] = past_time
    data["progress_pct"] = 0
    data["stall_count"] = 0  # エラー起因のstallをリセット
    with open(temp_paths["session"], "w", encoding="utf-8") as f:
        json.dump(data, f)

    diagnosis = orchestrator.diagnose_flash_issues()
    assert any(issue["type"] == "no_progress" for issue in diagnosis["issues"])

    # 5. 緊急停止検知
    orchestrator.phase_state["emergency_stop"] = True
    orchestrator.phase_state["stop_reason"] = "critical_resource_leak"
    diagnosis = orchestrator.diagnose_flash_issues()
    assert diagnosis["needs_intervention"]
    assert any(issue["type"] == "emergency_stop" for issue in diagnosis["issues"])


def test_send_improvement_directive(temp_paths):
    orchestrator = DummyOrchestrator()
    msg_id = orchestrator.send_improvement_directive(
        problem_type="stall",
        instructions="Reduce batch size to 2"
    )

    assert msg_id == "msg-1"
    assert len(orchestrator.messages) == 1
    assert orchestrator.messages[0]["message"] == "[改善指示/stall] Reduce batch size to 2"


def test_flash_heartbeat_exceptions(temp_paths):
    orchestrator = DummyOrchestrator()
    orchestrator.flash_session_start()

    # 1. generate_flash_status で例外が発生した場合 (152-153)
    def raise_error():
        raise ValueError("Simulated generator error")
    orchestrator.generate_flash_status = raise_error
    
    # 例外が内部でキャッチされ、処理が継続することを確認
    orchestrator.flash_heartbeat()

    # 2. open で OSError が発生した場合 (135-136)
    with open(temp_paths["session"], "r", encoding="utf-8") as f:
        data = json.load(f)
    data["status"] = "stopped"
    data["auto_stop_reason"] = "resource_critical"
    with open(temp_paths["session"], "w", encoding="utf-8") as f:
        json.dump(data, f)

    original_open = open
    def mock_open(file, *args, **kwargs):
        if "event_log.jsonl" in str(file):
            raise OSError("Simulated write error")
        return original_open(file, *args, **kwargs)

    with patch("builtins.open", mock_open):
        orchestrator.flash_heartbeat()
    
    # OSError が無視されて status が running に更新されることを確認
    with open(temp_paths["session"], "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["status"] == "running"


def test_flash_update_heartbeat_exceptions(temp_paths):
    orchestrator = DummyOrchestrator()
    orchestrator.flash_session_start()

    # 1. generate_flash_status 例外発生 (218-219)
    def raise_error():
        raise ValueError("Simulated generator error")
    orchestrator.generate_flash_status = raise_error
    
    orchestrator.flash_update_heartbeat()

    # 2. open 例外発生 (205-206)
    with open(temp_paths["session"], "r", encoding="utf-8") as f:
        data = json.load(f)
    data["status"] = "stopped"
    data["auto_stop_reason"] = "resource_critical"
    with open(temp_paths["session"], "w", encoding="utf-8") as f:
        json.dump(data, f)

    original_open = open
    def mock_open(file, *args, **kwargs):
        if "event_log.jsonl" in str(file):
            raise OSError("Simulated write error")
        return original_open(file, *args, **kwargs)

    with patch("builtins.open", mock_open):
        orchestrator.flash_update_heartbeat()
    
    with open(temp_paths["session"], "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["status"] == "running"


def test_check_flash_alive_status_empty(temp_paths):
    orchestrator = DummyOrchestrator()
    orchestrator.flash_session_start()

    # status が None や空文字の場合 (245-246)
    with open(temp_paths["session"], "r", encoding="utf-8") as f:
        data = json.load(f)
    data["status"] = None
    with open(temp_paths["session"], "w", encoding="utf-8") as f:
        json.dump(data, f)

    alive_info = orchestrator.check_flash_alive()
    assert alive_info["status"] == "not_started"


def test_diagnose_flash_issues_stale(temp_paths):
    orchestrator = DummyOrchestrator()
    orchestrator.flash_session_start()

    # 応答なし (stale) の診断 (313)
    with open(temp_paths["session"], "r", encoding="utf-8") as f:
        data = json.load(f)
    past_time = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat(timespec="seconds")
    data["last_heartbeat"] = past_time
    with open(temp_paths["session"], "w", encoding="utf-8") as f:
        json.dump(data, f)

    diagnosis = orchestrator.diagnose_flash_issues()
    assert diagnosis["needs_intervention"]
    assert any(issue["type"] == "stale" for issue in diagnosis["issues"])

