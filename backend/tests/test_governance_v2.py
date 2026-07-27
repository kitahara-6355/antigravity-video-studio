# -*- coding: utf-8 -*-
"""DS-037統合後のガバナンステスト（v2→v1統合版）。

旧 test_governance_v2.py から移行。OrchestrationHub（v1統合版）と
health_check モジュールの統合機能をテストする。
"""
import json
import pytest
import subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta
from backend.agents.orchestration import OrchestrationHub
from backend.agents.orchestration import orchestrator
from backend.agents.orchestration import health_check


@pytest.fixture
def mock_governance_paths(tmp_path, monkeypatch):
    base_dir = tmp_path / "orchestration"
    memory_dir = tmp_path / "memory"
    inbox_dir = tmp_path / "inbox"
    base_dir.mkdir(parents=True, exist_ok=True)
    memory_dir.mkdir(parents=True, exist_ok=True)
    inbox_dir.mkdir(parents=True, exist_ok=True)
    
    (tmp_path / "backend").mkdir(parents=True, exist_ok=True)
    (tmp_path / "backend" / "model_config.json").touch()

    # hub_common のパス設定
    from backend.agents.orchestration import hub_common, hub_gate, hub_batch, hub_session, hub_status, hub_reports
    # hub_common のパス変数を設定
    for mod in [hub_common, hub_gate, hub_batch]:
        monkeypatch.setattr(mod, "TASK_QUEUE_PATH", base_dir / "task_queue.json")
        monkeypatch.setattr(mod, "FLASH_REPORTS_PATH", base_dir / "flash_reports.jsonl")
        monkeypatch.setattr(mod, "PHASE_STATE_PATH", memory_dir / "phase_state.json")
        monkeypatch.setattr(mod, "FLASH_SESSION_PATH", base_dir / "flash_session.json")
    monkeypatch.setattr(hub_common, "OPUS_DIRECTIVE_PATH", base_dir / "opus_directive.json")
    monkeypatch.setattr(hub_common, "MESSAGE_BOX_PATH", base_dir / "message_box.jsonl")
    monkeypatch.setattr(hub_common, "PHASE_GATES_PATH", memory_dir / "phase_gates.json")
    monkeypatch.setattr(hub_common, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(hub_common, "_PROJECT_ROOT", tmp_path)
    # hub_gate にも MESSAGE_BOX_PATH, PHASE_GATES_PATH を設定
    monkeypatch.setattr(hub_gate, "MESSAGE_BOX_PATH", base_dir / "message_box.jsonl")
    monkeypatch.setattr(hub_gate, "PHASE_GATES_PATH", memory_dir / "phase_gates.json")
    monkeypatch.setattr(hub_gate, "OPUS_DIRECTIVE_PATH", base_dir / "opus_directive.json")

    # health_check.py のパス設定
    monkeypatch.setattr(health_check, "TASK_QUEUE_PATH", str(base_dir / "task_queue.json"))
    monkeypatch.setattr(health_check, "FLASH_SESSION_PATH", str(base_dir / "flash_session.json"))
    monkeypatch.setattr(health_check, "FLASH_REPORTS_PATH", str(base_dir / "flash_reports.jsonl"))
    monkeypatch.setattr(health_check, "PHASE_STATE_PATH", str(memory_dir / "phase_state.json"))

    state_data = {
        "current_phase": 27,
        "current_milestone": "M27.1",
        "emergency_stop": False,
        "awaiting_opus": False,
        "metrics": {"coverage_pct": 75.0, "test_count": 120, "critical_debt": 0}
    }
    with open(memory_dir / "phase_state.json", "w", encoding="utf-8") as f:
        json.dump(state_data, f)
        
    return base_dir, memory_dir


def test_orchestration_hub_skip_classification(mock_governance_paths, monkeypatch):
    """DS-037統合: 空PASS→skip分類テスト（旧OrchestrationHubV2テスト）"""
    base_dir, memory_dir = mock_governance_paths
    hub = OrchestrationHub()

    # subprocess.runをモック
    class MockCompletedProcess:
        def __init__(self, stdout, returncode=0):
            self.stdout = stdout
            self.returncode = returncode

    def mock_run(cmd, *args, **kwargs):
        cmd_str = " ".join(cmd)
        if "pytest" in cmd_str:
            return MockCompletedProcess("125 passed\nCoverage: 76.5%\n")
        elif "git" in cmd_str and "diff" in cmd_str:
            return MockCompletedProcess("backend/utils.py\n")
        elif "git" in cmd_str and "ls-files" in cmd_str:
            return MockCompletedProcess("")
        return MockCompletedProcess("")

    monkeypatch.setattr(subprocess, "run", mock_run)

    # タスクキューにダミーのタスクを設定
    queue_data = {
        "tasks": [
            {
                "id": "T1",
                "group": "test_weaver",
                "target_module": "backend/utils.py",
                "status": "pass",
                "result": {"changed_files": []}
            },
            {
                "id": "T2",
                "group": "test_weaver",
                "target_module": "backend/utils.py",
                "status": "pass",
                "result": {"changed_files": ["backend/utils.py"]}
            }
        ]
    }
    with open(base_dir / "task_queue.json", "w", encoding="utf-8") as f:
        json.dump(queue_data, f)

    # バッチレポート処理の実行
    hub.submit_batch_report("B1", {"passed": 2, "failed": 0})

    # flash_reports.jsonl に記録された結果を確認
    reports_path = base_dir / "flash_reports.jsonl"
    assert reports_path.exists()
    
    with open(reports_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        assert len(lines) == 1
        recorded = json.loads(lines[0])
        # T1は空PASSなので skip に分類される
        tasks = recorded["tasks"]
        t1 = next(t for t in tasks if t["id"] == "T1")
        t2 = next(t for t in tasks if t["id"] == "T2")
        assert t1["status"] == "skip"
        assert t2["status"] == "pass"


def test_health_check_loop_stagnation_detection(mock_governance_paths, monkeypatch):
    """DS-037統合: 固着検知テスト（旧health_check_v2テスト）"""
    base_dir, memory_dir = mock_governance_paths

    # 固着を検知させるため、直近のバッチレポートに同一モジュールの失敗を書き込む
    reports_path = base_dir / "flash_reports.jsonl"
    
    # 3バッチ連続で同一モジュールのFAIL
    batches = [
        {
            "timestamp": (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat(),
            "results": {"passed": 0, "failed": 1},
            "tasks": [{"id": "T1", "status": "fail", "target_module": "backend/api.py"}]
        },
        {
            "timestamp": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
            "results": {"passed": 0, "failed": 1},
            "tasks": [{"id": "T2", "status": "fail", "target_module": "backend/api.py"}]
        },
        {
            "timestamp": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
            "results": {"passed": 0, "failed": 1},
            "tasks": [{"id": "T3", "status": "fail", "target_module": "backend/api.py"}]
        }
    ]
    with open(reports_path, "w", encoding="utf-8") as f:
        for b in batches:
            f.write(json.dumps(b) + "\n")

    # セッションファイルをセット
    session_data = {
        "status": "running",
        "last_heartbeat": datetime.now(timezone.utc).isoformat()
    }
    with open(base_dir / "flash_session.json", "w", encoding="utf-8") as f:
        json.dump(session_data, f)

    # 固着チェック実行（v1統合版）
    result = health_check.check_loop_stagnation()
    assert result["status"] == "FAIL"
    assert "同一モジュール連続FAIL" in result["detail"]


def test_health_check_ux_ratchet_check(mock_governance_paths, monkeypatch):
    """DS-037統合: UXラチェットテスト（旧health_check_v2テスト）"""
    class MockCompletedProcess:
        def __init__(self, returncode, stdout=""):
            self.returncode = returncode
            self.stdout = stdout

    def mock_run(cmd, *args, **kwargs):
        if "test_ux_ratchet.py" in cmd:
            return MockCompletedProcess(0, "6 passed")
        return MockCompletedProcess(0)

    monkeypatch.setattr(subprocess, "run", mock_run)

    result = health_check.check_ux_ratchet_health()
    assert result["status"] == "PASS"
    assert "PASS" in result["detail"]
