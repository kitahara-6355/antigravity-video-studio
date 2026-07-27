import json
import os
import sys
import pytest
import subprocess
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, mock_open

# backend の親ディレクトリを sys.path に通すことで、絶対インポート 'import backend' が通るようにする
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import backend.agents.orchestration.health_check as hc


@pytest.fixture
def mock_paths(tmp_path, monkeypatch):
    """health_check のファイルパスを一時フォルダのものに置き換える"""
    import sys
    import backend.agents.orchestration.orchestrator
    import backend.agents.orchestration.hub_common
    import backend.agents.orchestration.hub_status
    import backend.agents.orchestration.hub_session
    import backend.agents.orchestration.hub_gate
    import backend.agents.orchestration.hub_reports
    import backend.agents.orchestration.hub_batch
    flash_session = tmp_path / "flash_session.json"
    flash_reports = tmp_path / "flash_reports.jsonl"
    phase_state = tmp_path / "phase_state.json"
    task_queue = tmp_path / "task_queue.json"
    event_log = tmp_path / "event_log.jsonl"
    opus_session = tmp_path / "opus_session.json"
    eta_tracker = tmp_path / "eta_tracker.json"
    user_schedule = tmp_path / "user_schedule.json"

    # デフォルトで pending な残タスクを1件設定しておく（DEAD判定縮小防止）
    task_queue.write_text('{"tasks": [{"status": "pending"}]}', encoding="utf-8")

    monkeypatch.setattr(hc, "FLASH_SESSION_PATH", str(flash_session))
    monkeypatch.setattr(hc, "FLASH_REPORTS_PATH", str(flash_reports))
    monkeypatch.setattr(hc, "PHASE_STATE_PATH", str(phase_state))
    monkeypatch.setattr(hc, "TASK_QUEUE_PATH", str(task_queue))
    monkeypatch.setattr(hc, "EVENT_LOG_PATH", str(event_log))
    monkeypatch.setattr(hc, "OPUS_SESSION_PATH", str(opus_session))
    monkeypatch.setattr(hc, "ORCHESTRATION_DIR", str(tmp_path))
    monkeypatch.setattr(hc, "WORKSPACE_DIR", str(tmp_path))

    path_map = {
        "FLASH_SESSION_PATH": flash_session,
        "FLASH_REPORTS_PATH": flash_reports,
        "PHASE_STATE_PATH": phase_state,
        "TASK_QUEUE_PATH": task_queue,
        "EVENT_LOG_PATH": event_log,
        "OPUS_SESSION_PATH": opus_session,
        "ETA_STORE_PATH": eta_tracker,
        "USER_SCHEDULE_PATH": user_schedule,
    }

    for name, module in list(sys.modules.items()):
        if name.startswith("backend.agents.orchestration"):
            is_hc = name.endswith("health_check")
            for var, path in path_map.items():
                if hasattr(module, var):
                    val = str(path) if is_hc else path
                    monkeypatch.setattr(module, var, val)

    return {
        "flash_session": flash_session,
        "flash_reports": flash_reports,
        "phase_state": phase_state,
        "task_queue": task_queue,
        "event_log": event_log,
        "opus_session": opus_session,
        "eta_tracker": eta_tracker,
        "user_schedule": user_schedule,
    }


def test_parse_iso():
    # 正常系 (様々なフォーマット)
    assert hc._parse_iso("2026-05-27T14:20:00.123456+09:00") is not None
    assert hc._parse_iso("2026-05-27T14:20:00+09:00") is not None
    assert hc._parse_iso("2026-05-27T14:20:00.123Z") is not None
    assert hc._parse_iso("2026-05-27T14:20:00Z") is not None
    assert hc._parse_iso("2026-05-27T14:20:00.123") is not None
    assert hc._parse_iso("2026-05-27T14:20:00") is not None
    # 異常系
    assert hc._parse_iso("invalid-date") is None
    assert hc._parse_iso("") is None


def test_safe_read_json(tmp_path):
    path = tmp_path / "test.json"
    # 存在しない場合
    assert hc._safe_read_json(str(path), {"default": 1}) == {"default": 1}

    # 正常な場合
    path.write_text('{"key": "value"}', encoding="utf-8")
    assert hc._safe_read_json(str(path)) == {"key": "value"}

    # 破損している場合
    path.write_text('{"key": ', encoding="utf-8")
    assert hc._safe_read_json(str(path), {"default": 2}) == {"default": 2}


def test_auto_stop_stale_session_non_running(mock_paths):
    # セッションが存在しない場合
    assert hc._auto_stop_stale_session(45) == "none"

    # status が running ではない場合
    mock_paths["flash_session"].write_text('{"status": "stopped"}', encoding="utf-8")
    assert hc._auto_stop_stale_session(45) == "none"


def test_auto_stop_stale_session_stages(mock_paths):
    # Stage 1: STALE (<= 30分)
    session_data = {"status": "running"}
    mock_paths["flash_session"].write_text(json.dumps(session_data), encoding="utf-8")
    assert hc._auto_stop_stale_session(25) == "none"

    # Stage 2: UNREACHABLE (<= 60分)
    assert hc._auto_stop_stale_session(45) == "warned"
    updated_session = json.loads(mock_paths["flash_session"].read_text(encoding="utf-8"))
    assert "heartbeat_warning" in updated_session
    assert updated_session["status"] == "running"
    assert mock_paths["event_log"].exists()

    # Stage 3: DEAD (> 60分)
    assert hc._auto_stop_stale_session(70) == "stopped"
    stopped_session = json.loads(mock_paths["flash_session"].read_text(encoding="utf-8"))
    assert stopped_session["status"] == "stopped"
    assert stopped_session["auto_stop_reason"] == "heartbeat_stale_70min_threshold_60min"


def test_auto_stop_stale_session_write_errors(mock_paths):
    # Stage 2 での OSError 発生
    session_data = {"status": "running"}
    mock_paths["flash_session"].write_text(json.dumps(session_data), encoding="utf-8")

    with patch("backend.agents.orchestration.health_check.atomic_write_json", side_effect=OSError("Write error")):
        assert hc._auto_stop_stale_session(45) == "none"

        # Stage 3 での OSError 発生
        assert hc._auto_stop_stale_session(70) == "none"


def test_auto_stop_stale_session_event_log_errors(mock_paths):
    # Stage 2 での event_log への書き込み時に OSError が発生しても none ではない正常結果が返ることを確認
    session_data = {"status": "running"}
    mock_paths["flash_session"].write_text(json.dumps(session_data), encoding="utf-8")

    original_open = open
    def mock_open_err(file, mode="r", *args, **kwargs):
        if "event_log.jsonl" in str(file):
            raise OSError("Write error")
        return original_open(file, mode, *args, **kwargs)

    with patch("backend.agents.orchestration.health_check.open", mock_open_err):
        assert hc._auto_stop_stale_session(45) == "warned"
        assert hc._auto_stop_stale_session(70) == "stopped"


def test_check_heartbeat(mock_paths):
    # セッションファイルがない場合
    res = hc.check_heartbeat()
    assert res["status"] == "FAIL"
    assert "flash_session.json が見つかりません" in res["detail"]

    # last_heartbeat フィールドがない場合
    mock_paths["flash_session"].write_text('{"status": "running"}', encoding="utf-8")
    res = hc.check_heartbeat()
    assert res["status"] == "FAIL"
    assert "last_heartbeat" in res["detail"]

    # パース不能な日時の場合
    mock_paths["flash_session"].write_text('{"last_heartbeat": "invalid"}', encoding="utf-8")
    res = hc.check_heartbeat()
    assert res["status"] == "FAIL"
    assert "パースできません" in res["detail"]

    # 正常系 (15分以内)
    now_str = datetime.now(timezone.utc).isoformat()
    mock_paths["flash_session"].write_text(json.dumps({"last_heartbeat": now_str}), encoding="utf-8")
    res = hc.check_heartbeat()
    assert res["status"] == "PASS"

    # WARN系 (30分以内)
    stale_str = (datetime.now(timezone.utc) - timedelta(minutes=25)).isoformat()
    mock_paths["flash_session"].write_text(json.dumps({"last_heartbeat": stale_str}), encoding="utf-8")
    res = hc.check_heartbeat()
    assert res["status"] == "WARN"

    # FAIL系 (30分超)
    dead_str = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
    mock_paths["flash_session"].write_text(json.dumps({"last_heartbeat": dead_str}), encoding="utf-8")
    res = hc.check_heartbeat()
    assert res["status"] == "FAIL"


def test_check_git_commits(mock_paths, monkeypatch):
    # git log 失敗
    def mock_run_fail(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=1, stdout="", stderr="error")
    monkeypatch.setattr(subprocess, "run", mock_run_fail)
    res = hc.check_git_commits()
    assert res["status"] == "FAIL"
    assert "git log 実行失敗" in res["detail"]

    # git log 例外発生
    def mock_run_raise(*args, **kwargs):
        raise RuntimeError("git execution crash")
    monkeypatch.setattr(subprocess, "run", mock_run_raise)
    res = hc.check_git_commits()
    assert res["status"] == "FAIL"
    assert "Git検証エラー" in res["detail"]

    # git log に Flashコミットなし
    def mock_run_no_flash(*args, **kwargs):
        stdout = "hash1 2026-05-27T14:20:00+09:00 Regular commit\n"
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=stdout, stderr="")
    monkeypatch.setattr(subprocess, "run", mock_run_no_flash)
    res = hc.check_git_commits()
    assert res["status"] == "WARN"
    assert "直近20コミットにFlashコミットなし" in res["detail"]

    # git log 時刻パース不可
    def mock_run_bad_time(*args, **kwargs):
        stdout = "hash1 invalid_time [Flash/T-1] Commit message\n"
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=stdout, stderr="")
    monkeypatch.setattr(subprocess, "run", mock_run_bad_time)
    res = hc.check_git_commits()
    assert res["status"] == "WARN"
    assert "時刻パース不可" in res["detail"]

    # 正常系（乖離なし）
    now_str = datetime.now(timezone.utc).isoformat()
    def mock_run_ok(*args, **kwargs):
        stdout = f"hash1 {now_str} [Flash/T-1] Commit message\n"
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=stdout, stderr="")
    monkeypatch.setattr(subprocess, "run", mock_run_ok)
    mock_paths["flash_session"].write_text(json.dumps({"last_heartbeat": now_str}), encoding="utf-8")
    res = hc.check_git_commits()
    assert res["status"] == "PASS"
    assert "心拍と整合" in res["detail"]

    # 正常系（乖離あり）
    stale_str = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
    mock_paths["flash_session"].write_text(json.dumps({"last_heartbeat": stale_str}), encoding="utf-8")
    res = hc.check_git_commits()
    assert "心拍との乖離" in res["detail"]


def test_check_batch_consistency(mock_paths, monkeypatch):
    # 新規セッション（報告数 0、Git 0）
    def mock_run_git_zero(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="", stderr="")
    monkeypatch.setattr(subprocess, "run", mock_run_git_zero)

    res = hc.check_batch_consistency()
    assert res["status"] == "WARN"
    assert "新規セッションの可能性" in res["detail"]

    # 履歴破損JSONを一部含む場合、空行を含む場合、および正常カウント
    mock_paths["flash_reports"].write_text(
        '{"results": {"passed": 2, "failed": 1}}\n'
        '\n'
        'invalid_json_line\n'
        '{"results": {"passed": 1, "failed": 0}}\n',
        encoding="utf-8"
    )

    # Gitコミット数が整合範囲内 (報告2件 vs Git 3コミット)
    def mock_run_git_three(*args, **kwargs):
        stdout = "hash1 [Flash/T-1]\nhash2 [Flash/T-2]\nhash3 [Flash/T-3]\n"
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=stdout, stderr="")
    monkeypatch.setattr(subprocess, "run", mock_run_git_three)

    res = hc.check_batch_consistency()
    assert res["status"] == "PASS"
    assert "整合" in res["detail"]
    assert res["report_tasks"] == 4

    # Gitコミット数が乖離している場合 (報告2件 vs Git 10コミット)
    def mock_run_git_ten(*args, **kwargs):
        stdout = "hash\n" * 10
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=stdout, stderr="")
    monkeypatch.setattr(subprocess, "run", mock_run_git_ten)

    res = hc.check_batch_consistency()
    assert res["status"] == "WARN"
    assert "乖離" in res["detail"]


def test_check_batch_consistency_os_error(mock_paths):
    # reports ファイルをディレクトリにすることで読み込み時に OSError を発生させる
    mock_paths["flash_reports"].mkdir(exist_ok=True)
    res = hc.check_batch_consistency()
    # 報告数は 0 になるが、正常に実行完了する
    assert res["report_batches"] == 0


def test_check_batch_consistency_git_exception(mock_paths, monkeypatch):
    def mock_run_raise(*args, **kwargs):
        raise RuntimeError("git crash")
    monkeypatch.setattr(subprocess, "run", mock_run_raise)
    res = hc.check_batch_consistency()
    # 例外がキャッチされて git_commits が 0 になることを確認
    assert res["git_commits"] == 0


def test_check_session_status(mock_paths, monkeypatch):
    # セッション情報なし
    res = hc.check_session_status()
    assert res["status"] == "FAIL"
    assert "セッション情報なし" in res["detail"]

    # running で心拍が古い (60分超過による自動停止)
    stale_str = (datetime.now(timezone.utc) - timedelta(minutes=75)).isoformat()
    session_data = {"status": "running", "last_heartbeat": stale_str}
    mock_paths["flash_session"].write_text(json.dumps(session_data), encoding="utf-8")
    res = hc.check_session_status()
    assert res["status"] == "FAIL"
    assert "自動停止しました" in res["detail"]

    # running で心拍が少し古い (45分で警告のみ)
    stale_str_45 = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
    session_data_45 = {"status": "running", "last_heartbeat": stale_str_45}
    mock_paths["flash_session"].write_text(json.dumps(session_data_45), encoding="utf-8")
    res = hc.check_session_status()
    assert res["status"] == "WARN"
    assert "心拍45分前" in res["detail"]

    # 心拍復旧による警告フラグクリア
    now_str = datetime.now(timezone.utc).isoformat()
    session_recovered = {
        "status": "running",
        "last_heartbeat": now_str,
        "heartbeat_warning": "stale_45min",
        "heartbeat_warning_at": now_str,
    }
    mock_paths["flash_session"].write_text(json.dumps(session_recovered), encoding="utf-8")
    res = hc.check_session_status()
    assert res["status"] == "PASS"
    updated_session = json.loads(mock_paths["flash_session"].read_text(encoding="utf-8"))
    assert "heartbeat_warning" not in updated_session

    # 停止状態
    mock_paths["flash_session"].write_text('{"status": "stopped"}', encoding="utf-8")
    res = hc.check_session_status()
    assert res["status"] == "WARN"
    assert "stopped" in res["detail"]


def test_check_session_status_write_error(mock_paths, monkeypatch):
    # 心拍復旧による警告フラグクリア時に OSError が発生しても正常に PASS を返すことを確認
    now_str = datetime.now(timezone.utc).isoformat()
    session_recovered = {
        "status": "running",
        "last_heartbeat": now_str,
        "heartbeat_warning": "stale_45min",
        "heartbeat_warning_at": now_str,
    }
    mock_paths["flash_session"].write_text(json.dumps(session_recovered), encoding="utf-8")

    with patch("backend.agents.orchestration.health_check.atomic_write_json", side_effect=OSError("Write error")):
        res = hc.check_session_status()
        assert res["status"] == "PASS"


def test_assess_flash_lifecycle(mock_paths):
    # セッション未開始
    res = hc.assess_flash_lifecycle()
    assert res["status"] == "INFO"
    assert "未開始" in res["detail"]

    # ミッション完遂 (stopped で完了タスク数 > 0)
    mock_paths["flash_session"].write_text(
        '{"status": "stopped", "tasks_completed_in_session": 5, "batches_in_session": 1}',
        encoding="utf-8"
    )
    res = hc.assess_flash_lifecycle()
    assert res["status"] == "COMPLETE"
    assert "完遂済み" in res["detail"]

    # 完遂プロトコル待ち (running で残タスク 0、完了タスク > 0)
    mock_paths["flash_session"].write_text(
        '{"status": "running", "tasks_completed_in_session": 5, "batches_in_session": 1}',
        encoding="utf-8"
    )
    mock_paths["task_queue"].write_text('{"tasks": []}', encoding="utf-8")
    res = hc.assess_flash_lifecycle()
    assert res["status"] == "FINISHING"
    assert "完遂プロトコル待ち" in res["detail"]

    # 長時間稼働 (12時間超過)
    started_str = (datetime.now(timezone.utc) - timedelta(hours=14)).isoformat()
    mock_paths["flash_session"].write_text(
        json.dumps({
            "status": "running",
            "session_started_at": started_str,
            "tasks_completed_in_session": 5,
        }),
        encoding="utf-8"
    )
    mock_paths["task_queue"].write_text(
        '{"tasks": [{"status": "pending"}]}',
        encoding="utf-8"
    )
    res = hc.assess_flash_lifecycle()
    assert res["status"] == "WARN"
    assert "時間経過" in res["detail"]

    # 通常稼働中
    started_str_recent = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    mock_paths["flash_session"].write_text(
        json.dumps({
            "status": "running",
            "session_started_at": started_str_recent,
            "tasks_completed_in_session": 5,
        }),
        encoding="utf-8"
    )
    res = hc.assess_flash_lifecycle()
    assert res["status"] == "ACTIVE"


def test_assess_opus_session(mock_paths):
    # サジェストなしケース
    mock_paths["phase_state"].write_text('{"current_phase": 0, "current_milestone": "M4"}', encoding="utf-8")
    mock_paths["flash_session"].write_text('{"status": "running"}', encoding="utf-8")
    mock_paths["task_queue"].write_text('{"tasks": [{"status": "pending"}]}', encoding="utf-8")
    suggestions, _ = hc.assess_opus_session()
    assert suggestions is None

    # サジェストありケース (COMPLETE)
    mock_paths["flash_session"].write_text(
        '{"status": "stopped", "tasks_completed_in_session": 5, "batches_in_session": 1}',
        encoding="utf-8"
    )
    suggestions, _ = hc.assess_opus_session()
    assert suggestions is not None
    assert any("完遂済み" in s for s in suggestions)

    # サジェストありケース (Phase 25到達)
    mock_paths["flash_session"].write_text('{"status": "running"}', encoding="utf-8")
    mock_paths["phase_state"].write_text('{"current_phase": 26, "current_milestone": "M5"}', encoding="utf-8")
    suggestions_phase, _ = hc.assess_opus_session()
    assert suggestions_phase is not None
    assert any("Phase 26" in s for s in suggestions_phase)

    # サジェストありケース (WARN: 長時間稼働)
    started_str = (datetime.now(timezone.utc) - timedelta(hours=14)).isoformat()
    mock_paths["flash_session"].write_text(
        json.dumps({
            "status": "running",
            "session_started_at": started_str,
            "tasks_completed_in_session": 5,
        }),
        encoding="utf-8"
    )
    mock_paths["task_queue"].write_text('{"tasks": [{"status": "pending"}]}', encoding="utf-8")
    suggestions_warn, _ = hc.assess_opus_session()
    assert suggestions_warn is not None
    assert any("長時間稼働中" in s for s in suggestions_warn)


def test_run_health_check_healthy(mock_paths, monkeypatch):
    # すべて PASS の健康な状態
    now_str = datetime.now(timezone.utc).isoformat()
    mock_paths["flash_session"].write_text(json.dumps({"status": "running", "last_heartbeat": now_str}), encoding="utf-8")
    # Phase 26 にして opus_suggestions 出力部分をカバーする
    mock_paths["phase_state"].write_text('{"current_phase": 26, "current_milestone": "M5"}', encoding="utf-8")
    mock_paths["task_queue"].write_text('{"tasks": [{"status": "pending"}]}', encoding="utf-8")

    def mock_run_git(*args, **kwargs):
        stdout = f"hash1 {now_str} [Flash/T-1] Commit\n"
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=stdout, stderr="")
    monkeypatch.setattr(subprocess, "run", mock_run_git)

    mock_paths["flash_reports"].write_text('{"results": {"passed": 1, "failed": 0}}\n', encoding="utf-8")

    res = hc.run_health_check(); print('DEBUG_RES:', res)
    assert "HEALTHY" in res["overall"]
    assert "💡 Opusセッション運用サジェスト" in res["report"]


def test_run_health_check_unhealthy(mock_paths):
    # session ファイルなしで check_heartbeat は FAIL になり、全体も UNHEALTHY になることを検証
    res = hc.run_health_check(); print('DEBUG_RES:', res)
    assert "UNHEALTHY" in res["overall"]


def test_run_health_check_degraded_due_to_lag(mock_paths, monkeypatch):
    # 心拍は正常だが、バッチ乖離のみWARNの場合 -> HEALTHY判定となる仕様の確認
    now_str = datetime.now(timezone.utc).isoformat()
    mock_paths["flash_session"].write_text(json.dumps({"status": "running", "last_heartbeat": now_str}), encoding="utf-8")
    mock_paths["phase_state"].write_text('{"current_phase": 0, "current_milestone": "M4"}', encoding="utf-8")

    # gitコミット数と報告数の乖離 (git=10件, 報告=0件)
    def mock_run_git_many(*args, **kwargs):
        if "--oneline" in args[0]:
            stdout = "hash [Flash/T-1]\n" * 10
            return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=stdout, stderr="")
        else:
            stdout = f"hash1 {now_str} [Flash/T-1] Commit\n"
            return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=stdout, stderr="")
    monkeypatch.setattr(subprocess, "run", mock_run_git_many)

    res = hc.run_health_check(); print('DEBUG_RES:', res)
    assert "HEALTHY" in res["overall"]


def test_run_health_check_degraded_other(mock_paths, monkeypatch):
    # 心拍がWARN (STALE) で他が正常 -> DEGRADED判定
    stale_str = (datetime.now(timezone.utc) - timedelta(minutes=25)).isoformat()
    mock_paths["flash_session"].write_text(json.dumps({"status": "running", "last_heartbeat": stale_str}), encoding="utf-8")

    def mock_run_git(*args, **kwargs):
        stdout = f"hash1 {stale_str} [Flash/T-1] Commit\n"
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=stdout, stderr="")
    monkeypatch.setattr(subprocess, "run", mock_run_git)

    res = hc.run_health_check(); print('DEBUG_RES:', res)
    assert "DEGRADED" in res["overall"]



def test_main_json_mode(mock_paths, monkeypatch):
    monkeypatch.setattr(hc, "WORKSPACE_DIR", "C:\\some_path\\video-automation")
    monkeypatch.setattr(sys, "argv", ["health_check.py", "--json"])

    mock_result = {
        "overall": "🟢 HEALTHY",
        "checks": [("TestCheck", {"status": "PASS", "detail": "OK"})],
        "report": "Test Report",
        "flash_lifecycle": {"status": "ACTIVE", "detail": "Running"}
    }
    monkeypatch.setattr(hc, "run_health_check", lambda *args, **kwargs: mock_result)

    # 標準出力をキャプチャしてJSON出力を確認
    mock_stdout = MagicMock()
    monkeypatch.setattr(sys, "__stdout__", mock_stdout)
    hc.main()
    mock_stdout.write.assert_called_once()
    args, _ = mock_stdout.write.call_args
    json_data = json.loads(args[0])
    assert "overall" in json_data
    assert json_data["overall"] == "🟢 HEALTHY"


def test_main_update_dashboard(mock_paths, monkeypatch):
    monkeypatch.setattr(hc, "WORKSPACE_DIR", "C:\\some_path\\video-automation")
    monkeypatch.setattr(sys, "argv", ["health_check.py", "--update-dashboard"])

    mock_result = {
        "overall": "🟢 HEALTHY",
        "checks": [],
        "report": "Report",
        "flash_lifecycle": {"status": "ACTIVE"}
    }
    monkeypatch.setattr(hc, "run_health_check", lambda *args, **kwargs: mock_result)

    mock_gen_dash = MagicMock(return_value="dummy_path")
    mock_module = MagicMock()
    mock_module.generate_dashboard_quick = mock_gen_dash

    with patch.dict(sys.modules, {"backend.agents.orchestration.generate_subagent_reports": mock_module}):
        hc.main()
        mock_gen_dash.assert_called_once()


def test_main_nudge_and_recovery(mock_paths, monkeypatch):
    monkeypatch.setattr(hc, "WORKSPACE_DIR", "C:\\some_path\\video-automation")
    monkeypatch.setattr(sys, "argv", ["health_check.py"])

    # DEGRADED & COMPLETE 状態をシミュレート
    mock_result = {
        "overall": "🟡 DEGRADED",
        "checks": [],
        "report": "Report",
        "flash_lifecycle": {"status": "COMPLETE"}
    }
    monkeypatch.setattr(hc, "run_health_check", lambda *args, **kwargs: mock_result)

    mock_hub_instance = MagicMock()
    mock_hub_instance.read_messages.return_value = []

    mock_generate_prompt = MagicMock(return_value="recovery_instructions")

    mock_orch = MagicMock()
    mock_orch.OrchestrationHub = MagicMock(return_value=mock_hub_instance)
    mock_prompt_mod = MagicMock()
    mock_prompt_mod.generate_prompt = mock_generate_prompt

    with patch.dict(sys.modules, {
        "backend.agents.orchestration": mock_orch,
        "backend.agents.orchestration.generate_flash_prompt": mock_prompt_mod,
    }):
        mock_orch.generate_flash_prompt = mock_prompt_mod
        hc.main()
        # メッセージが送られ、復旧プロンプトが生成されること
        mock_hub_instance.send_message.assert_called_once()
        mock_generate_prompt.assert_called_once()


def test_main_nudge_cooldown(mock_paths, monkeypatch):
    monkeypatch.setattr(hc, "WORKSPACE_DIR", "C:\\some_path\\video-automation")
    monkeypatch.setattr(sys, "argv", ["health_check.py"])

    # DEGRADED 状態をシミュレート
    mock_result = {
        "overall": "🟡 DEGRADED",
        "checks": [],
        "report": "Report",
        "flash_lifecycle": {"status": "ACTIVE"}
    }
    monkeypatch.setattr(hc, "run_health_check", lambda *args, **kwargs: mock_result)

    mock_hub_instance = MagicMock()
    ten_mins_ago = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    mock_hub_instance.read_messages.return_value = [
        {"content": "【自動ナッジ】何かエラー", "timestamp": ten_mins_ago}
    ]

    mock_orch = MagicMock()
    mock_orch.OrchestrationHub = MagicMock(return_value=mock_hub_instance)

    with patch.dict(sys.modules, {
        "backend.agents.orchestration": mock_orch,
    }):
        hc.main()
        # クールダウン中なのでナッジ送信はスキップされる
        mock_hub_instance.send_message.assert_not_called()


def test_main_nudge_timestamp_error(mock_paths, monkeypatch):
    monkeypatch.setattr(hc, "WORKSPACE_DIR", "C:\\some_path\\video-automation")
    monkeypatch.setattr(sys, "argv", ["health_check.py"])

    # DEGRADED 状態をシミュレート
    mock_result = {
        "overall": "🟡 DEGRADED",
        "checks": [],
        "report": "Report",
        "flash_lifecycle": {"status": "ACTIVE"}
    }
    monkeypatch.setattr(hc, "run_health_check", lambda *args, **kwargs: mock_result)

    mock_hub_instance = MagicMock()
    # 不正なタイムスタンプを指定して ValueError 等の例外を発生させ、それが pass されるか検証
    mock_hub_instance.read_messages.return_value = [
        {"content": "【自動ナッジ】何かエラー", "timestamp": "invalid_timestamp_string"}
    ]

    mock_orch = MagicMock()
    mock_orch.OrchestrationHub = MagicMock(return_value=mock_hub_instance)

    with patch.dict(sys.modules, {
        "backend.agents.orchestration": mock_orch,
    }):
        hc.main()
        # 不正なタイムスタンプ行は無視されて、新規ナッジが送信される
        mock_hub_instance.send_message.assert_called_once()


def test_main_nudge_exception(mock_paths, monkeypatch):
    monkeypatch.setattr(hc, "WORKSPACE_DIR", "C:\\some_path\\video-automation")
    monkeypatch.setattr(sys, "argv", ["health_check.py"])

    # DEGRADED 状態をシミュレート
    mock_result = {
        "overall": "🟡 DEGRADED",
        "checks": [],
        "report": "Report",
        "flash_lifecycle": {"status": "ACTIVE"}
    }
    monkeypatch.setattr(hc, "run_health_check", lambda *args, **kwargs: mock_result)

    mock_orch = MagicMock()
    mock_orch.OrchestrationHub.side_effect = RuntimeError("DB connection lost")

    with patch.dict(sys.modules, {
        "backend.agents.orchestration": mock_orch,
    }):
        # 例外がキャッチされて main() が正常終了すること
        hc.main()


def test_main_prompt_generation_exception(mock_paths, monkeypatch):
    monkeypatch.setattr(hc, "WORKSPACE_DIR", "C:\\some_path\\video-automation")
    monkeypatch.setattr(sys, "argv", ["health_check.py"])

    # UNHEALTHY 状態をシミュレート
    mock_result = {
        "overall": "🔴 UNHEALTHY",
        "checks": [],
        "report": "Report",
        "flash_lifecycle": {"status": "ACTIVE"}
    }
    monkeypatch.setattr(hc, "run_health_check", lambda *args, **kwargs: mock_result)

    mock_orch = MagicMock()
    mock_prompt_mod = MagicMock()
    mock_prompt_mod.generate_prompt.side_effect = Exception("Prompt error")

    with patch.dict(sys.modules, {
        "backend.agents.orchestration": mock_orch,
        "backend.agents.orchestration.generate_flash_prompt": mock_prompt_mod,
    }):
        mock_orch.generate_flash_prompt = mock_prompt_mod
        # 例外がキャッチされて main() が正常終了すること
        hc.main()


def test_main_dashboard_update_exception(mock_paths, monkeypatch):
    monkeypatch.setattr(hc, "WORKSPACE_DIR", "C:\\some_path\\video-automation")
    monkeypatch.setattr(sys, "argv", ["health_check.py", "--update-dashboard"])

    mock_result = {
        "overall": "🟢 HEALTHY",
        "checks": [],
        "report": "Report",
        "flash_lifecycle": {"status": "ACTIVE"}
    }
    monkeypatch.setattr(hc, "run_health_check", lambda *args, **kwargs: mock_result)

    mock_module = MagicMock()
    mock_module.generate_dashboard_quick.side_effect = Exception("Dashboard failed")

    with patch.dict(sys.modules, {"backend.agents.orchestration.generate_subagent_reports": mock_module}):
        # 例外がキャッチされて main() が正常終了すること
        hc.main()


def test_main_as_script(mock_paths, monkeypatch):
    import runpy
    # スクリプトを直接実行したときの if __name__ == "__main__": をカバーする
    monkeypatch.setattr(hc, "WORKSPACE_DIR", "C:\\some_path\\video-automation")
    monkeypatch.setattr(sys, "argv", ["health_check.py", "--json"])
    monkeypatch.setattr(hc, "run_health_check", lambda: {
        "overall": "🟢 HEALTHY",
        "checks": [("TestCheck", {"status": "PASS", "detail": "OK"})],
        "report": "Report",
        "flash_lifecycle": {"status": "ACTIVE"}
    })

    with patch("builtins.print"):
        runpy.run_path(hc.__file__, run_name="__main__")


class MockDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        base_dt = cls(2026, 5, 28, 10, 0, 0, tzinfo=timezone.utc)
        if tz is not None:
            return base_dt.astimezone(tz)
        return base_dt.replace(tzinfo=None)


@pytest.fixture
def mock_datetime(monkeypatch):
    import sys
    monkeypatch.setattr(hc, "datetime", MockDatetime)
    monkeypatch.setattr(sys.modules[__name__], "datetime", MockDatetime)
    for name, module in list(sys.modules.items()):
        if name.startswith("backend.agents.orchestration"):
            if hasattr(module, "datetime"):
                monkeypatch.setattr(module, "datetime", MockDatetime)


def test_compute_eta_ended(mock_paths, mock_datetime):
    mock_paths["flash_session"].write_text('{"status": "ended"}', encoding="utf-8")
    eta = hc._compute_eta_and_next_check()
    assert eta["reason"] == "セッション完遂済み"
    assert eta["next_check_minutes"] == 0
    assert eta["next_check_jst"] == "今すぐ（新規セッション開設が必要）"


def test_compute_eta_remaining_zero(mock_paths, mock_datetime):
    mock_paths["flash_session"].write_text('{"status": "running"}', encoding="utf-8")
    mock_paths["task_queue"].write_text('{"tasks": []}', encoding="utf-8")
    eta = hc._compute_eta_and_next_check()
    assert eta["eta_minutes"] == 5
    assert eta["eta_jst"] == "19:05"
    assert eta["next_check_minutes"] == 10
    assert eta["next_check_jst"] == "19:10"


def test_compute_eta_throughput_zero(mock_paths, mock_datetime):
    mock_paths["flash_session"].write_text(
        '{"status": "running", "tasks_completed_in_session": 0}', encoding="utf-8"
    )
    queue_data = {"tasks": [{"status": "pending"}] * 5}
    mock_paths["task_queue"].write_text(json.dumps(queue_data), encoding="utf-8")
    eta = hc._compute_eta_and_next_check()
    assert eta["throughput_tph"] == 0
    assert eta["next_check_minutes"] == 15
    assert eta["next_check_jst"] == "19:15"


def test_compute_eta_normal_and_drift(mock_paths, mock_datetime, monkeypatch):
    mock_paths["flash_session"].write_text(
        '{"status": "running", "tasks_completed_in_session": 10, "session_started_at": "2026-05-28T08:00:00Z"}',
        encoding="utf-8"
    )
    queue_data = {"tasks": [{"status": "pending"}] * 10}
    mock_paths["task_queue"].write_text(json.dumps(queue_data), encoding="utf-8")

    eta = hc._compute_eta_and_next_check()
    assert eta["throughput_tph"] == 5.0
    assert eta["eta_minutes"] == 120
    assert eta["eta_jst"] == "21:00"
    assert eta["next_check_minutes"] == 100
    assert eta["next_check_jst"] == "20:40"
    assert eta["drift_minutes"] == 0

    class MockDatetimeLater(MockDatetime):
        @classmethod
        def now(cls, tz=None):
            base_dt = cls(2026, 5, 28, 10, 30, 0, tzinfo=timezone.utc)
            if tz is not None:
                return base_dt.astimezone(tz)
            return base_dt.replace(tzinfo=None)

    monkeypatch.setattr(hc, "datetime", MockDatetimeLater)

    # 完了数を 9 に調整し、throughput を 9 / 2.5 = 3.6 とする。
    # 3.6 < 5.0 * 0.8 (= 4.0) の条件を満たすため「処理速度低下」がトリガーされる。
    mock_paths["flash_session"].write_text(
        '{"status": "running", "tasks_completed_in_session": 9, "session_started_at": "2026-05-28T08:00:00Z"}',
        encoding="utf-8"
    )

    eta2 = hc._compute_eta_and_next_check()
    assert eta2["throughput_tph"] == 3.6
    assert eta2["eta_minutes"] == 166
    assert eta2["drift_minutes"] == 76
    assert "処理速度低下" in eta2["drift_reason"]

    # 15タスクに増やす。完了9, throughput=3.6。remaining=15 => eta = 15/3.6 * 60 = 250分。
    # 前回の残り期待値 = 166 - 0 = 166分。drift = 250 - 166 = 84分。
    queue_data2 = {"tasks": [{"status": "pending"}] * 15}
    mock_paths["task_queue"].write_text(json.dumps(queue_data2), encoding="utf-8")

    eta3 = hc._compute_eta_and_next_check()
    assert eta3["drift_minutes"] == 84
    assert "新規タスク追加" in eta3["drift_reason"]

    # 5タスクに減らす。完了9, throughput=3.6。remaining=5 => eta = 5/3.6 * 60 = 83分。
    # 前回の残り期待値 = 250 - 0 = 250分。drift = 83 - 250 = -167分。
    queue_data3 = {"tasks": [{"status": "pending"}] * 5}
    mock_paths["task_queue"].write_text(json.dumps(queue_data3), encoding="utf-8")

    eta4 = hc._compute_eta_and_next_check()
    assert eta4["drift_minutes"] == -167
    assert eta4["drift_reason"] == "処理効率向上"


def test_compute_eta_next_check_conditional_branches(mock_paths, mock_datetime):
    mock_paths["flash_session"].write_text(
        '{"status": "running", "tasks_completed_in_session": 6, "session_started_at": "2026-05-28T09:00:00Z"}',
        encoding="utf-8"
    )
    queue_data = {"tasks": [{"status": "pending"}] * 2}
    mock_paths["task_queue"].write_text(json.dumps(queue_data), encoding="utf-8")
    
    eta = hc._compute_eta_and_next_check()
    assert eta["eta_minutes"] == 20
    assert eta["next_check_minutes"] == 15

    mock_paths["flash_session"].write_text(
        '{"status": "running", "tasks_completed_in_session": 12, "session_started_at": "2026-05-28T09:00:00Z"}',
        encoding="utf-8"
    )
    queue_data2 = {"tasks": [{"status": "pending"}] * 1}
    mock_paths["task_queue"].write_text(json.dumps(queue_data2), encoding="utf-8")
    
    eta2 = hc._compute_eta_and_next_check()
    assert eta2["eta_minutes"] == 5
    assert eta2["next_check_minutes"] == 5


def test_resource_release_guidance_report(mock_paths, mock_datetime, monkeypatch):
    mock_paths["flash_session"].write_text(
        '{"status": "stopped", "tasks_completed_in_session": 5, "batches_in_session": 1}',
        encoding="utf-8"
    )
    def mock_run_git(*args, **kwargs):
        stdout = "hash1 2026-05-28T10:00:00Z [Flash/T-1] Commit\n"
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=stdout, stderr="")
    monkeypatch.setattr(subprocess, "run", mock_run_git)

    res = hc.run_health_check(); print('DEBUG_RES:', res)
    assert "Flashセッション完遂後のリソース解放" in res["report"]
    assert "Flash側チャットがまだ開いている場合は閉じてください" in res["report"]


def test_flash_reports_parsing_robustness(mock_paths, mock_datetime):
    mock_paths["flash_reports"].write_text(
        '{"timestamp": "2026-05-28T09:30:00Z", "results": {"passed": 2, "failed": 1}}\n'
        '{"timestamp": "2026-05-28T09:35:00Z", "results": "not_a_dict"}\n'
        '{"timestamp": "2026-05-28T09:40:00Z", "results": {"passed": "invalid", "failed": 0}}\n'
        '{"timestamp": "invalid_time", "results": {"passed": 1, "failed": 0}}\n'
        'this_is_not_json\n',
        encoding="utf-8"
    )
    
    mock_paths["flash_session"].write_text(
        '{"status": "running"}', encoding="utf-8"
    )
    queue_data = {"tasks": [{"status": "pending"}] * 5}
    mock_paths["task_queue"].write_text(json.dumps(queue_data), encoding="utf-8")

    eta = hc._compute_eta_and_next_check()
    assert eta["throughput_tph"] == 3.0


def test_flash_reports_parsing_robustness_with_empty_lines(mock_paths, mock_datetime):
    mock_paths["flash_reports"].write_text(
        '{"timestamp": "2026-05-28T09:30:00Z", "results": {"passed": 2, "failed": 1}}\n'
        '\n'
        '{"timestamp": "2026-05-28T09:35:00Z", "results": "not_a_dict"}\n'
        '{"timestamp": "2026-05-28T09:40:00Z", "results": {"passed": "invalid", "failed": 0}}\n'
        '{"timestamp": "invalid_time", "results": {"passed": 1, "failed": 0}}\n'
        'this_is_not_json\n',
        encoding="utf-8"
    )
    
    mock_paths["flash_session"].write_text(
        '{"status": "running"}', encoding="utf-8"
    )
    queue_data = {"tasks": [{"status": "pending"}] * 5}
    mock_paths["task_queue"].write_text(json.dumps(queue_data), encoding="utf-8")

    eta = hc._compute_eta_and_next_check()
    assert eta["throughput_tph"] == 3.0


def test_compute_eta_throughput_read_error(mock_paths, mock_datetime):
    mock_paths["flash_reports"].write_text("{}", encoding="utf-8")
    
    original_open = open
    def mock_open_err(file, mode="r", *args, **kwargs):
        if "flash_reports.jsonl" in str(file):
            raise OSError("Read error")
        return original_open(file, mode, *args, **kwargs)

    mock_paths["flash_session"].write_text(
        '{"status": "running", "tasks_completed_in_session": 5, "session_started_at": "2026-05-28T09:00:00Z"}',
        encoding="utf-8"
    )
    mock_paths["task_queue"].write_text('{"tasks": [{"status": "pending"}]}', encoding="utf-8")

    with patch("backend.agents.orchestration.health_check.open", mock_open_err):
        eta = hc._compute_eta_and_next_check()
        assert eta["throughput_tph"] == 5.0


def test_compute_eta_drift_wait_loss_and_report(mock_paths, mock_datetime, monkeypatch):
    prev_eta = {
        "timestamp": "2026-05-28T09:30:00Z",
        "eta_minutes": 120,
        "remaining": 10,
        "throughput_tph": 5.0
    }
    tracker_path = mock_paths["flash_session"].parent / "eta_tracker.json"
    tracker_path.write_text(json.dumps(prev_eta), encoding="utf-8")
    
    now_str = "2026-05-28T10:00:00Z"
    mock_paths["flash_session"].write_text(
        json.dumps({
            "status": "running",
            "last_heartbeat": now_str,
            "tasks_completed_in_session": 5,
            "session_started_at": "2026-05-28T09:00:00Z"
        }),
        encoding="utf-8"
    )
    mock_paths["task_queue"].write_text(
        json.dumps({"tasks": [{"status": "pending"}] * 10}), encoding="utf-8"
    )
    
    def mock_run_git(*args, **kwargs):
        stdout = f"hash1 {now_str} [Flash/T-1] Commit\n"
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=stdout, stderr="")
    monkeypatch.setattr(subprocess, "run", mock_run_git)

    res = hc.run_health_check(); print('DEBUG_RES:', res)
    assert res["eta"]["drift_minutes"] == 30
    assert res["eta"]["drift_reason"] == "待機時間ロス"


def test_compute_eta_write_tracker_error(mock_paths, mock_datetime):
    mock_paths["flash_session"].write_text(
        '{"status": "running", "tasks_completed_in_session": 5, "session_started_at": "2026-05-28T09:00:00Z"}',
        encoding="utf-8"
    )
    mock_paths["task_queue"].write_text('{"tasks": [{"status": "pending"}]}', encoding="utf-8")

    with patch("backend.agents.orchestration.hub_common._write_json", side_effect=OSError("Write error")):
        eta = hc._compute_eta_and_next_check()
        assert eta["throughput_tph"] == 5.0


def test_run_health_check_effectiveness_gate_failed(mock_paths, monkeypatch):
    # 効果検証ゲートがしきい値逸脱でFAILする場合の挙動を検証
    now_str = datetime.now(timezone.utc).isoformat()
    mock_paths["flash_session"].write_text(json.dumps({"status": "running", "last_heartbeat": now_str}), encoding="utf-8")
    mock_paths["phase_state"].write_text('{"current_phase": 33, "current_milestone": "M4"}', encoding="utf-8")
    mock_paths["task_queue"].write_text('{"tasks": [{"status": "pending"}]}', encoding="utf-8")

    def mock_run_git(*args, **kwargs):
        stdout = f"hash1 {now_str} [Flash/T-1] Commit\n"
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=stdout, stderr="")
    monkeypatch.setattr(subprocess, "run", mock_run_git)

    # ResearchReporter をモックして空振り率70.0%を返すようにする
    class MockResearchReporter:
        def __init__(self, workspace_path):
            pass
        def calculate_metrics(self):
            return {"wasted_rate": 70.0, "dep_leak_fails": 0}

    # sys.modules を上書きして、インポートパスに関わらずモッククラスが使われるようにする
    import sys
    from types import ModuleType
    mock_mod = ModuleType("agents.orchestration.research_reporter")
    mock_mod.ResearchReporter = MockResearchReporter
    
    # テスト前の状態を保存
    old_modules = {}
    for key in ["agents", "agents.orchestration", "agents.orchestration.research_reporter", "backend.agents.orchestration.research_reporter"]:
        if key in sys.modules:
            old_modules[key] = sys.modules[key]
            
    sys.modules["agents.orchestration.research_reporter"] = mock_mod
    sys.modules["backend.agents.orchestration.research_reporter"] = mock_mod

    try:
        res = hc.run_health_check()
        assert "DEGRADED" in res["overall"]
        assert "🚨 【効果検証しきい値逸脱】警告レポートが自動生成されました" in res["report"]
    finally:
        # モジュールキャッシュを復元
        for key in ["agents.orchestration.research_reporter", "backend.agents.orchestration.research_reporter"]:
            if key in old_modules:
                sys.modules[key] = old_modules[key]
            elif key in sys.modules:
                del sys.modules[key]


def test_send_stale_nudge_variations(mock_paths, monkeypatch):
    # 47: session が None の場合
    mock_paths["flash_session"].unlink(missing_ok=True)
    hc._send_stale_nudge(20, "2026-06-22 12:00 JST")
    
    # 47: status が running ではない場合
    mock_paths["flash_session"].write_text('{"status": "stopped"}', encoding="utf-8")
    hc._send_stale_nudge(20, "2026-06-22 12:00 JST")

    # 52-56: last_stale_nudge_at が10分以内の場合
    now_str = datetime.now(timezone.utc).isoformat()
    session_data = {"status": "running", "last_stale_nudge_at": now_str}
    mock_paths["flash_session"].write_text(json.dumps(session_data), encoding="utf-8")
    hc._send_stale_nudge(20, "2026-06-22 12:00 JST")

    # 71-72: OrchestrationHub から例外
    stale_str = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    session_data = {"status": "running", "last_stale_nudge_at": stale_str}
    mock_paths["flash_session"].write_text(json.dumps(session_data), encoding="utf-8")
    
    mock_hub_class = MagicMock()
    mock_hub_class.side_effect = Exception("Hub crash")
    mock_orch = MagicMock()
    mock_orch.OrchestrationHub = mock_hub_class
    with patch.dict(sys.modules, {"backend.agents.orchestration": mock_orch}):
        hc._send_stale_nudge(20, "2026-06-22 12:00 JST")

    # 78-79: atomic_write_json が例外
    stale_str = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    session_data = {"status": "running", "last_stale_nudge_at": stale_str}
    mock_paths["flash_session"].write_text(json.dumps(session_data), encoding="utf-8")
    with patch("backend.agents.orchestration.health_check.atomic_write_json", side_effect=Exception("Write crash")):
        hc._send_stale_nudge(20, "2026-06-22 12:00 JST")

    # 92-93: open(EVENT_LOG_PATH) が OSError
    stale_str = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    session_data = {"status": "running", "last_stale_nudge_at": stale_str}
    mock_paths["flash_session"].write_text(json.dumps(session_data), encoding="utf-8")
    original_open = open
    def mock_open_err(file, mode="r", *args, **kwargs):
        if "event_log.jsonl" in str(file):
            raise OSError("Access denied")
        return original_open(file, mode, *args, **kwargs)
    with patch("backend.agents.orchestration.health_check.open", mock_open_err):
        hc._send_stale_nudge(20, "2026-06-22 12:00 JST")

    # 98-99: 内部で例外（_parse_iso が例外を投げるなど）
    stale_str = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    session_data = {"status": "running", "last_stale_nudge_at": stale_str}
    mock_paths["flash_session"].write_text(json.dumps(session_data), encoding="utf-8")
    with patch("backend.agents.orchestration.health_check._parse_iso", side_effect=Exception("Parse crash")):
        hc._send_stale_nudge(20, "2026-06-22 12:00 JST")


def test_reset_opus_session(mock_paths):
    # 102-120: reset_opus_session のテスト
    data = hc.reset_opus_session("test_conv_id")
    assert data["conversation_id"] == "test_conv_id"
    assert data["cron_iterations"] == 0
    
    # 118-119: atomic_write_json が例外
    with patch("backend.agents.orchestration.health_check.atomic_write_json", side_effect=Exception("Write crash")):
        data2 = hc.reset_opus_session("test_conv_id_2")
        assert data2["conversation_id"] == "test_conv_id_2"


def test_calc_hb_minutes_variations():
    # 125-130: _calc_hb_minutes の分岐
    assert hc._calc_hb_minutes(None) is None
    assert hc._calc_hb_minutes("") is None
    assert hc._calc_hb_minutes("invalid_date") is None


def test_auto_stop_stale_session_variations(mock_paths):
    # 171-172: _safe_read_json(TASK_QUEUE_PATH) で例外
    session_data = {"status": "running"}
    mock_paths["flash_session"].write_text(json.dumps(session_data), encoding="utf-8")
    
    original_safe_read = hc._safe_read_json
    def mock_safe_read_selectively(path, default=None):
        if "task_queue.json" in str(path):
            raise Exception("Read crash")
        return original_safe_read(path, default)

    with patch("backend.agents.orchestration.health_check._safe_read_json", mock_safe_read_selectively):
        # exception occurs when reading queue, but it catches it and dead_threshold becomes 60
        # hb_minutes=35 => <= 60 => warned
        assert hc._auto_stop_stale_session(35) == "warned"

    # 189-195: ウォッチドッグ例外
    mock_hub_instance = MagicMock()
    mock_hub_instance._recover_timed_out_tasks.return_value = True
    mock_orch = MagicMock()
    mock_orch.OrchestrationHub = MagicMock(return_value=mock_hub_instance)
    
    with patch.dict(sys.modules, {"backend.agents.orchestration": mock_orch}):
        # atomic_write_json inside watchdog throws Exception
        original_atomic_write = hc.atomic_write_json
        def mock_atomic_write(path, data):
            if "task_queue.json" in str(path):
                raise Exception("Task queue write crash")
            return original_atomic_write(path, data)
        with patch("backend.agents.orchestration.health_check.atomic_write_json", mock_atomic_write):
            assert hc._auto_stop_stale_session(45) == "warned"

        # Hub implementation throws Exception
        mock_orch.OrchestrationHub.side_effect = Exception("Hub initialization failed")
        assert hc._auto_stop_stale_session(45) == "warned"


def test_assess_flash_lifecycle_variations(mock_paths):
    # 477: status == "ended"
    mock_paths["flash_session"].write_text('{"status": "ended", "tasks_completed_in_session": 5, "batches_in_session": 2}', encoding="utf-8")
    res = hc.assess_flash_lifecycle()
    assert res["status"] == "COMPLETE"

    # 488-490: stopped and new_session_requested, last_heartbeat <= 5 min
    now_str = datetime.now(timezone.utc).isoformat()
    mock_paths["flash_session"].write_text(json.dumps({
        "status": "stopped",
        "auto_stop_reason": "new_session_requested",
        "last_heartbeat": now_str,
        "tasks_completed_in_session": 3
    }), encoding="utf-8")
    res2 = hc.assess_flash_lifecycle()
    assert res2["status"] == "TRANSITIONING"


def test_check_compaction_in_transcript(tmp_path, monkeypatch):
    # 539-557: check_compaction_in_transcript
    assert hc.check_compaction_in_transcript(None) is False
    assert hc.check_compaction_in_transcript("") is False
    
    # 存在しないパス
    assert hc.check_compaction_in_transcript("non_existent_conv_id") is False

    # パスが存在し、キーワードが含まれる場合
    conv_id = "test_conv_compaction"
    app_data_dir = tmp_path / "appdata"
    monkeypatch.setattr(hc, "os", MagicMock(path=os.path, makedirs=os.makedirs))
    
    # os.path.exists のモック
    original_exists = os.path.exists
    def mock_exists(path):
        if "test_conv_compaction" in str(path):
            return True
        return original_exists(path)
    
    # mock_open を使って transcript.jsonl をシミュレート
    transcript_content = '{"line": "compaction occurred"}\n'
    with patch("os.path.exists", mock_exists):
        with patch("builtins.open", mock_open(read_data=transcript_content)):
            assert hc.check_compaction_in_transcript(conv_id) is True

        # 例外発生時の挙動
        def mock_open_raise(*args, **kwargs):
            raise Exception("Read error")
        with patch("builtins.open", mock_open_raise):
            assert hc.check_compaction_in_transcript(conv_id) is False


def test_assess_opus_session_variations(mock_paths, monkeypatch):
    # 577-583: compaction_occurred detect
    mock_paths["opus_session"].write_text(json.dumps({
        "session_started_at": datetime.now(timezone.utc).isoformat(),
        "conversation_id": "test_conv_compaction_2",
        "compaction_occurred": False
    }), encoding="utf-8")
    
    monkeypatch.setattr(hc, "check_compaction_in_transcript", lambda cid: True)
    
    suggestions, health = hc.assess_opus_session(check_compaction=True)
    assert health["stage"] == "STALE"
    assert any("コンテキスト圧縮" in s for s in suggestions)
    
    # atomic_write_json が例外
    mock_paths["opus_session"].write_text(json.dumps({
        "session_started_at": datetime.now(timezone.utc).isoformat(),
        "conversation_id": "test_conv_compaction_3",
        "compaction_occurred": False
    }), encoding="utf-8")
    with patch("backend.agents.orchestration.health_check.atomic_write_json", side_effect=Exception("Write error")):
        suggestions, health = hc.assess_opus_session(check_compaction=True)
        assert health["stage"] == "STALE"

    # stage FRESH (uptime <= 8)
    started_fresh = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
    mock_paths["opus_session"].write_text(json.dumps({
        "session_started_at": started_fresh,
        "compaction_occurred": False
    }), encoding="utf-8")
    _, health_fresh = hc.assess_opus_session()
    assert health_fresh["stage"] == "FRESH"

    # stage AGING (8 < uptime <= 16)
    started_aging = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
    mock_paths["opus_session"].write_text(json.dumps({
        "session_started_at": started_aging,
        "compaction_occurred": False
    }), encoding="utf-8")
    suggestions_aging, health_aging = hc.assess_opus_session()
    assert health_aging["stage"] == "AGING"
    assert any("AGING" in s for s in suggestions_aging)

    # suggestions: Phase 順調に進行中
    mock_paths["phase_state"].write_text('{"current_phase": 10, "current_milestone": "M3"}', encoding="utf-8")
    mock_paths["opus_session"].write_text(json.dumps({
        "session_started_at": started_fresh,
        "compaction_occurred": False
    }), encoding="utf-8")
    suggestions_phase, _ = hc.assess_opus_session()
    assert any("順調に進行中" in s for s in suggestions_phase)


def test_check_loop_stagnation_variations(mock_paths, monkeypatch):
    # 662-663: JSONパース例外
    mock_paths["flash_reports"].write_text('{"tasks": [{"status": "pass"}]}\ninvalid_json\n', encoding="utf-8")
    res = hc.check_loop_stagnation()
    assert res["status"] == "PASS"

    # 680-688: 同一モジュール連続FAIL
    mock_paths["flash_reports"].write_text(
        '{"tasks": [{"status": "fail", "target_module": "mod_a"}]}\n'
        '{"tasks": [{"status": "fail", "target_module": "mod_a"}]}\n'
        '{"tasks": [{"status": "fail", "target_module": "mod_a"}]}\n',
        encoding="utf-8"
    )
    mock_hub_instance = MagicMock()
    mock_orch = MagicMock()
    mock_orch.OrchestrationHub = MagicMock(return_value=mock_hub_instance)
    with patch.dict(sys.modules, {"backend.agents.orchestration": mock_orch}):
        res2 = hc.check_loop_stagnation()
        assert res2["status"] == "FAIL"
        assert "同一モジュール連続FAIL: mod_a" in res2["detail"]
        mock_hub_instance.auto_heal_stagnation.assert_called_once()
        
    # auto_heal_stagnation が例外を投げる場合
    mock_hub_instance.auto_heal_stagnation.side_effect = Exception("Heal error")
    with patch.dict(sys.modules, {"backend.agents.orchestration": mock_orch}):
        res3 = hc.check_loop_stagnation()
        assert res3["status"] == "FAIL"

    # 710-712: 有効打率の急低下 (rate < 10.0%)
    mock_paths["flash_reports"].write_text(
        '{"tasks": [{"status": "skip", "result": {}}]}\n'
        '{"tasks": [{"status": "skip", "result": {}}]}\n'
        '{"tasks": [{"status": "skip", "result": {}}]}\n',
        encoding="utf-8"
    )
    res4 = hc.check_loop_stagnation()
    assert res4["status"] == "FAIL"
    assert "有効打率の急低下" in res4["detail"]

    # 712: total_tasks == 0
    mock_paths["flash_reports"].write_text(
        '{"tasks": []}\n'
        '{"tasks": []}\n'
        '{"tasks": []}\n',
        encoding="utf-8"
    )
    res_zero = hc.check_loop_stagnation()
    assert res_zero["status"] == "PASS"


def test_check_ux_ratchet_health_exception(monkeypatch):
    # 736-737: check_ux_ratchet_health 例外
    monkeypatch.setattr(subprocess, "run", MagicMock(side_effect=Exception("Subprocess failed")))
    res = hc.check_ux_ratchet_health()
    assert res["status"] == "FAIL"
    assert "UXストーリー検証エラー" in res["detail"]


def test_check_metrics_lock_variations(mock_paths):
    # 750-751: json.loads 例外
    mock_paths["flash_reports"].write_text('{"metrics": {"coverage_pct": 80, "test_count": 100}}\ninvalid_json\n', encoding="utf-8")
    res = hc.check_metrics_lock()
    assert res["status"] == "PASS"

    # OSError 例外
    with patch("builtins.open", side_effect=OSError("Read error")):
        res_oserror = hc.check_metrics_lock()
        assert res_oserror["status"] == "PASS"

    # 761: メトリクス固着 (15バッチ変動なし)
    report_line = '{"metrics": {"coverage_pct": 85.0, "test_count": 120}}\n'
    mock_paths["flash_reports"].write_text(report_line * 15, encoding="utf-8")
    res2 = hc.check_metrics_lock()
    assert res2["status"] == "FAIL"
    assert "メトリクス固着" in res2["detail"]


def test_run_health_check_resource_governor_exception(mock_paths, monkeypatch):
    # 773-775: ResourceGovernor 例外
    mock_gov = MagicMock()
    mock_gov.kill_zombie_test_processes.side_effect = Exception("Governor crash")
    mock_rg_mod = MagicMock()
    mock_rg_mod.ResourceGovernor = MagicMock(return_value=mock_gov)
    
    with patch.dict(sys.modules, {"backend.agents.orchestration.resource_governor": mock_rg_mod}):
        now_str = datetime.now(timezone.utc).isoformat()
        mock_paths["flash_session"].write_text(json.dumps({"status": "running", "last_heartbeat": now_str}), encoding="utf-8")
        
        # run_health_check should catch the exception and log a warning, then proceed
        res = hc.run_health_check()
        assert "overall" in res


def test_run_health_check_archive_urgency_and_opus_stage(mock_paths, monkeypatch):
    # 833-834, 836: archive_urgency == "warn" / "info"
    # 856, 858: opus_stage == "STALE" / "AGING"
    now_str = datetime.now(timezone.utc).isoformat()
    mock_paths["flash_session"].write_text(json.dumps({
        "status": "running",
        "last_heartbeat": now_str,
        "archive_urgency": "warn",
        "context_consumption_pct": 85
    }), encoding="utf-8")
    
    started_stale = (datetime.now(timezone.utc) - timedelta(hours=20)).isoformat()
    mock_paths["opus_session"].write_text(json.dumps({
        "session_started_at": started_stale,
        "compaction_occurred": False
    }), encoding="utf-8")
    
    res = hc.run_health_check()
    assert "Flashコンテキスト飽和" in res["report"]
    assert "セッション移行を強く推奨" in res["report"]
    
    # info / AGING
    mock_paths["flash_session"].write_text(json.dumps({
        "status": "running",
        "last_heartbeat": now_str,
        "archive_urgency": "info",
        "context_consumption_pct": 65
    }), encoding="utf-8")
    
    started_aging = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
    mock_paths["opus_session"].write_text(json.dumps({
        "session_started_at": started_aging,
        "compaction_occurred": False
    }), encoding="utf-8")
    
    res2 = hc.run_health_check()
    assert "Flashコンテキスト消費増加中" in res2["report"]
    assert "移行準備を推奨" in res2["report"]


def test_evaluate_effectiveness_gate_phase_thresholds(mock_paths, monkeypatch):
    # 915, 917, 919: Phase threshold branches
    class MockResearchReporter:
        def __init__(self, workspace_path):
            pass
        def calculate_metrics(self):
            return {"wasted_rate": 45.0, "dep_leak_fails": 0}
            
    import sys
    from types import ModuleType
    mock_mod = ModuleType("agents.orchestration.research_reporter")
    mock_mod.ResearchReporter = MockResearchReporter
    
    old_modules = {}
    for key in ["agents.orchestration.research_reporter", "backend.agents.orchestration.research_reporter"]:
        if key in sys.modules:
            old_modules[key] = sys.modules[key]
    sys.modules["agents.orchestration.research_reporter"] = mock_mod
    sys.modules["backend.agents.orchestration.research_reporter"] = mock_mod

    try:
        # Phase 36
        mock_paths["phase_state"].write_text('{"current_phase": 36, "current_milestone": "M4"}', encoding="utf-8")
        res_36 = hc.evaluate_effectiveness_gate(mock_paths["flash_session"].parent, {})
        assert res_36["failed"] is True  # wasted_rate 45.0 >= 20.0
        
        # Phase 35
        mock_paths["phase_state"].write_text('{"current_phase": 35, "current_milestone": "M4"}', encoding="utf-8")
        res_35 = hc.evaluate_effectiveness_gate(mock_paths["flash_session"].parent, {})
        assert res_35["failed"] is True  # wasted_rate 45.0 >= 30.0

        # Phase 34
        mock_paths["phase_state"].write_text('{"current_phase": 34, "current_milestone": "M4"}', encoding="utf-8")
        res_34 = hc.evaluate_effectiveness_gate(mock_paths["flash_session"].parent, {})
        assert res_34["failed"] is True  # wasted_rate 45.0 >= 40.0

        # Exceptions handling (968-969)
        mock_paths["phase_state"].write_text('{"current_phase": 33, "current_milestone": "M4"}', encoding="utf-8")
        with patch("backend.agents.orchestration.health_check._safe_read_json", side_effect=Exception("Read crash")):
            res_err = hc.evaluate_effectiveness_gate(mock_paths["flash_session"].parent, {})
            assert res_err["failed"] is False
    finally:
        for key in ["agents.orchestration.research_reporter", "backend.agents.orchestration.research_reporter"]:
            if key in old_modules:
                sys.modules[key] = old_modules[key]
            elif key in sys.modules:
                del sys.modules[key]


def test_main_variations(mock_paths, monkeypatch):
    # 992-993: OPUS_SESSION_PATH write exception
    # 1003: assess_opus_session returns not tuple
    # 1068: lc_status == "TRANSITIONING"
    # 1076-1083: prompt generation skip and exceptions
    monkeypatch.setattr(hc, "WORKSPACE_DIR", "C:\\some_path\\video-automation")
    monkeypatch.setattr(sys, "argv", ["health_check.py", "--json"])
    
    mock_result = {
        "overall": "🔴 UNHEALTHY",
        "checks": [],
        "report": "Report",
        "flash_lifecycle": {"status": "TRANSITIONING"},
        "phase_data": {}
    }
    monkeypatch.setattr(hc, "run_health_check", lambda *args, **kwargs: mock_result)
    monkeypatch.setattr(hc, "assess_opus_session", lambda *args, **kwargs: ["suggestion"]) # returns list, not tuple (1003)

    # opus write exception (992-993)
    original_safe_read = hc._safe_read_json
    def mock_safe_read(path, default=None):
        if "opus_session.json" in str(path):
            return {"cron_iterations": 1}
        return original_safe_read(path, default)
    
    with patch("backend.agents.orchestration.health_check._safe_read_json", mock_safe_read):
        with patch("backend.agents.orchestration.health_check.atomic_write_json", side_effect=Exception("Write error")):
            with patch("builtins.print"):
                hc.main()  # should pass and not crash
                
    # lc_status == "TRANSITIONING" prompt generation skip (1068)
    with patch("builtins.print") as mock_print:
        hc.main()
        
    # prompt generation skip via cooldown (1076-1083)
    mock_result_unhealthy = {
        "overall": "🔴 UNHEALTHY",
        "checks": [],
        "report": "Report",
        "flash_lifecycle": {"status": "ACTIVE"},
        "phase_data": {}
    }
    monkeypatch.setattr(hc, "run_health_check", lambda *args, **kwargs: mock_result_unhealthy)
    
    # mock flash_session with auto_stopped_at within 30 minutes
    now_str = datetime.now(timezone.utc).isoformat()
    mock_paths["flash_session"].write_text(json.dumps({
        "status": "stopped",
        "auto_stopped_at": now_str,
        "auto_stop_reason": "new_session_requested"
    }), encoding="utf-8")
    
    with patch("builtins.print"):
        hc.main()  # should print cooldown skip and not generate prompt
        
    # exception during cooldown check (1083)
    def mock_safe_read_crash(path, default=None):
        if "flash_session.json" in str(path):
            raise Exception("Read crash")
        return original_safe_read(path, default)
        
    with patch("backend.agents.orchestration.health_check._safe_read_json", mock_safe_read_crash):
        with patch("builtins.print"):
            hc.main()  # should handle exception and proceed to normal prompt generation (which might print error)


def test_auto_stop_stale_session_remaining_zero_and_watchdog_success(mock_paths, monkeypatch):
    # 170: remaining == 0 => dead_threshold = 30
    session_data = {"status": "running"}
    mock_paths["flash_session"].write_text(json.dumps(session_data), encoding="utf-8")
    mock_paths["task_queue"].write_text('{"tasks": []}', encoding="utf-8")
    assert hc._auto_stop_stale_session(35) == "stopped"
    
    # 191: Watchdog success path (hub._recover_timed_out_tasks returns True, write success)
    session_data = {"status": "running"}
    mock_paths["flash_session"].write_text(json.dumps(session_data), encoding="utf-8")
    mock_paths["task_queue"].write_text('{"tasks": [{"status": "running"}]}', encoding="utf-8")
    
    mock_hub_instance = MagicMock()
    mock_hub_instance._recover_timed_out_tasks.return_value = True
    mock_orch = MagicMock()
    mock_orch.OrchestrationHub = MagicMock(return_value=mock_hub_instance)
    
    with patch.dict(sys.modules, {"backend.agents.orchestration": mock_orch}):
        with patch("builtins.print") as mock_print:
            assert hc._auto_stop_stale_session(45) == "warned"
            mock_print.assert_any_call("🔧 ウォッチドッグ: タイムアウトタスクを自動回復しました")


def test_sys_path_insertion(monkeypatch):
    import importlib
    workspace_dir = hc.WORKSPACE_DIR
    backend_path = os.path.join(workspace_dir, "backend")
    
    # 一旦 sys.path から除外したリストを作成
    filtered_path = [p for p in sys.path if p != workspace_dir and p != backend_path]
    monkeypatch.setattr(sys, "path", filtered_path)
    
    # 再インポート（再ロード）してトップレベルコードを走らせる
    importlib.reload(hc)
    
    # 20行目と23行目の insert(0, ...) が実行され、sys.path に追加されたことをアサート
    assert workspace_dir in sys.path
    assert backend_path in sys.path




