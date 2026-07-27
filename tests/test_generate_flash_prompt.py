import os
import sys
from unittest.mock import patch, MagicMock

import pytest

# テスト対象のパスを設定
WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, WORKSPACE_DIR)
sys.path.insert(0, os.path.join(WORKSPACE_DIR, "backend"))

from backend.agents.orchestration import generate_flash_prompt

def test_generate_prompt_basic():
    # jsonファイルの読み込みをすべてモックする
    mock_phase_info = {
        "current_phase": 34,
        "current_milestone": "M34.1",
        "emergency_stop": False
    }
    mock_directive_info = {
        "directive_id": "test_directive",
        "notes": "test notes",
        "priorities": {"group1": 100},
        "focus_modules": []
    }
    mock_task_queue = {
        "current_batch_id": "test_batch",
        "tasks": [{"group": "thumbnail", "status": "pending"}]
    }
    mock_session = {
        "status": "stopped",
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "opus_conversation_id": "test_opus_id"
    }
    mock_user_schedule = {
        "windows": [{"start": "09:00", "end": "18:00", "label": "work"}]
    }

    with patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json") as mock_read:
        def side_effect(path, default=None):
            if "phase_state" in path:
                return mock_phase_info
            elif "opus_directive" in path:
                return mock_directive_info
            elif "task_queue" in path:
                return mock_task_queue
            elif "flash_session" in path:
                return mock_session
            elif "user_schedule" in path:
                return mock_user_schedule
            return default

        mock_read.side_effect = side_effect

        prompt = generate_flash_prompt.generate_prompt()
        assert "Flash専用セッション 起動指示プロンプト" in prompt
        assert "Phase 34" in prompt
        assert "test_directive" in prompt


def test_generate_prompt_auto_stop_oserror():
    # 旧セッションが running のときに atomic_write_json が OSError を投げるケース
    mock_phase_info = {
        "current_phase": 34,
        "current_milestone": "M34.1",
        "emergency_stop": False
    }
    mock_directive_info = {}
    mock_task_queue = {
        "current_batch_id": "test_batch",
        "tasks": []
    }
    # status を running にして自動停止を誘発させる
    mock_session = {
        "status": "running",
        "conversation_id": "old_conv_123"
    }
    mock_user_schedule = {}

    with patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json") as mock_read, \
         patch("backend.agents.orchestration.generate_flash_prompt.atomic_write_json", side_effect=OSError("Write failed")) as mock_write, \
         patch("sys.stderr") as mock_stderr:

        def side_effect(path, default=None):
            if "phase_state" in path:
                return mock_phase_info
            elif "opus_directive" in path:
                return mock_directive_info
            elif "task_queue" in path:
                return mock_task_queue
            elif "flash_session" in path:
                return mock_session
            elif "user_schedule" in path:
                return mock_user_schedule
            return default

        mock_read.side_effect = side_effect

        prompt = generate_flash_prompt.generate_prompt()
        
        # atomic_write_json が呼び出されたことを検証
        mock_write.assert_called_once()
        # sys.stderr.write が OSError のエラーメッセージを出力しているか検証
        mock_stderr.write.assert_any_call("❌ 旧セッション停止失敗: Write failed")


def test_generate_prompt_evolution_and_focus():
    # 優先度の自動調整と重点モジュールのテスト
    mock_phase_info = {
        "current_phase": 34,
        "current_milestone": "M34.1",
        "emergency_stop": False
    }
    mock_directive_info = {
        "directive_id": "test_directive",
        "notes": "test notes",
        "priorities": {"group1": 33, "group2": 33, "group3": 33},
        "focus_modules": ["/path/to/module_a.py", "/path/to/module_b.py"]
    }
    mock_task_queue = {
        "current_batch_id": "test_batch",
        "tasks": [{"group": "thumbnail", "status": "pending"}]
    }
    mock_session = {
        "status": "stopped"
    }
    mock_user_schedule = {}
    mock_evo_log = {
        "agent_performance": {
            "group1": {"success_rate": 0.8, "passed": 8, "total": 10},
            "group2": {"success_rate": 0.5, "passed": 5, "total": 10},
            "group3": {"success_rate": 0.2, "passed": 2, "total": 10}
        }
    }

    with patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json") as mock_read:
        def side_effect(path, default=None):
            if "phase_state" in path:
                return mock_phase_info
            elif "opus_directive" in path:
                return mock_directive_info
            elif "task_queue" in path:
                return mock_task_queue
            elif "flash_session" in path:
                return mock_session
            elif "user_schedule" in path:
                return mock_user_schedule
            elif "evolution_log" in path:
                return mock_evo_log
            return default

        mock_read.side_effect = side_effect

        prompt = generate_flash_prompt.generate_prompt()
        assert "- **重点モジュール**: `module_a.py`, `module_b.py`" in prompt
        assert "エージェント打率実績" in prompt
        assert "group1" in prompt
        assert "80.0%打率" in prompt


def test_generate_prompt_missing_data():
    # 各種jsonが空の場合のテスト
    mock_phase_info = {}
    mock_directive_info = {}
    mock_task_queue = {}
    mock_session = {}
    mock_user_schedule = {}

    with patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json") as mock_read:
        def side_effect(path, default=None):
            if "phase_state" in path:
                return mock_phase_info
            elif "opus_directive" in path:
                return mock_directive_info
            elif "task_queue" in path:
                return mock_task_queue
            elif "flash_session" in path:
                return mock_session
            elif "user_schedule" in path:
                return mock_user_schedule
            return default

        mock_read.side_effect = side_effect

        prompt = generate_flash_prompt.generate_prompt()
        assert "タスクキューなし（新規バッチ生成から開始）" in prompt
        assert "セッション情報なし（新規セッション）" in prompt
        assert "サムネイルタスク情報なし" in prompt
        assert "Directiveファイルなし（デフォルト優先度で実行）" in prompt


def test_generate_prompt_datetime_and_profiles():
    from datetime import datetime, timezone
    mock_phase_info = {}
    mock_directive_info = {}
    mock_task_queue = {}
    mock_session = {
        "status": "stopped"
    }
    
    mock_user_schedule = {
        "weekday": {
            "windows": [{"start": "09:00", "end": "18:00", "label": "work"}],
            "reliability_pct": 85
        },
        "weekend": {
            "windows": [{"start": "10:00", "end": "22:00", "label": "play"}]
        },
        "flash_profiles": {
            "standard": {
                "mode_name": "STANDARD_TEST",
                "batch_size": 6,
                "timer_seconds": 300,
                "archive_batches": 30,
                "archive_hours": 5,
                "context_target_pct": 70,
                "context_warn_pct": 60,
                "status_verbosity": "full",
                "subagent_timeout": 600,
                "batch_timeout": 900,
                "context_pct_per_batch": 4,
            },
            "weekend": {
                "mode_name": "WEEKEND_TEST",
                "batch_size": 8,
                "timer_seconds": 300,
                "archive_batches": 35,
                "archive_hours": 6,
                "context_target_pct": 70,
                "context_warn_pct": 60,
                "status_verbosity": "full",
                "subagent_timeout": 600,
                "batch_timeout": 900,
                "context_pct_per_batch": 4,
            },
            "night": {
                "batch_size": 10,
                "timer_seconds": 480,
                "archive_batches": 40,
                "archive_hours": 8,
                "context_target_pct": 70,
                "context_warn_pct": 60,
                "status_verbosity": "minimal",
                "subagent_timeout": 900,
                "batch_timeout": 1200,
                "context_pct_per_batch": 4,
            }
        }
    }

    # 平日昼間のテスト (月曜 12:00 JST -> 03:00 UTC)
    with patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json") as mock_read, \
         patch("backend.agents.orchestration.generate_flash_prompt.datetime") as mock_dt:
        
        mock_dt.now.return_value = datetime(2026, 6, 22, 3, 0, tzinfo=timezone.utc)
        mock_dt.fromisoformat = datetime.fromisoformat
        
        def side_effect(path, default=None):
            if "phase_state" in path:
                return mock_phase_info
            elif "opus_directive" in path:
                return mock_directive_info
            elif "task_queue" in path:
                return mock_task_queue
            elif "flash_session" in path:
                return mock_session
            elif "user_schedule" in path:
                return mock_user_schedule
            return default

        mock_read.side_effect = side_effect

        prompt = generate_flash_prompt.generate_prompt()
        assert "月曜日 — 平日（定期チェックモード）" in prompt
        assert "09:00-18:00 (work)" in prompt
        assert "**遵守率**: 85%" in prompt
        assert "STANDARD_TEST" in prompt

    # 休日昼間のテスト (土曜 12:00 JST -> 03:00 UTC)
    with patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json") as mock_read, \
         patch("backend.agents.orchestration.generate_flash_prompt.datetime") as mock_dt:
        
        mock_dt.now.return_value = datetime(2026, 6, 27, 3, 0, tzinfo=timezone.utc)
        mock_dt.fromisoformat = datetime.fromisoformat
        mock_read.side_effect = side_effect

        prompt = generate_flash_prompt.generate_prompt()
        assert "土曜日 — 休日（終日対応モード）" in prompt
        assert "10:00-22:00 (play)" in prompt
        assert "終日対応窓内 — 随時確認可能" in prompt
        assert "WEEKEND_TEST" in prompt

    # 平日夜間のテスト (月曜 23:30 JST -> 14:30 UTC)
    with patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json") as mock_read, \
         patch("backend.agents.orchestration.generate_flash_prompt.datetime") as mock_dt:
        
        mock_dt.now.return_value = datetime(2026, 6, 22, 14, 30, tzinfo=timezone.utc)
        mock_dt.fromisoformat = datetime.fromisoformat
        mock_read.side_effect = side_effect

        prompt = generate_flash_prompt.generate_prompt()
        # mode_name が無いためフォールバックして "NIGHT" になるはず
        assert "NIGHT" in prompt
        assert "夜間モード特別指示" in prompt


def test_generate_prompt_auto_stop_and_cooldown():
    from datetime import datetime, timezone, timedelta
    mock_phase_info = {}
    mock_directive_info = {}
    mock_user_schedule = {}

    # Case 1: running_tasks があり、--force なしの場合は自動停止をスキップする
    mock_task_queue_running = {
        "tasks": [{"status": "running"}]
    }
    mock_session_running = {
        "status": "running",
        "conversation_id": "old_conv_123"
    }

    with patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json") as mock_read, \
         patch("sys.argv", ["generate_flash_prompt.py"]), \
         patch("sys.stderr") as mock_stderr:

        def side_effect(path, default=None):
            if "phase_state" in path:
                return mock_phase_info
            elif "opus_directive" in path:
                return mock_directive_info
            elif "task_queue" in path:
                return mock_task_queue_running
            elif "flash_session" in path:
                return mock_session_running
            elif "user_schedule" in path:
                return mock_user_schedule
            return default

        mock_read.side_effect = side_effect
        generate_flash_prompt.generate_prompt()
        mock_stderr.write.assert_any_call("   自動停止をスキップします（--force で強制停止可能）")

    # Case 2: running_tasks がなく、自動停止が正常に書き込まれる
    mock_task_queue_empty = {
        "tasks": []
    }
    with patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json") as mock_read, \
         patch("backend.agents.orchestration.generate_flash_prompt.atomic_write_json") as mock_write, \
         patch("sys.argv", ["generate_flash_prompt.py"]), \
         patch("sys.stderr") as mock_stderr:

        def side_effect2(path, default=None):
            if "phase_state" in path:
                return mock_phase_info
            elif "opus_directive" in path:
                return mock_directive_info
            elif "task_queue" in path:
                return mock_task_queue_empty
            elif "flash_session" in path:
                return mock_session_running
            elif "user_schedule" in path:
                return mock_user_schedule
            return default

        mock_read.side_effect = side_effect2
        generate_flash_prompt.generate_prompt()
        mock_write.assert_called_once()
        mock_stderr.write.assert_any_call("⚠️ 旧Flashセッション (conv: old_conv_123) を自動停止しました (reason: new_session_requested)")

    # Case 3: クールダウン（5分以内）により sys.exit(0) で終了する
    now_utc = datetime.now(timezone.utc)
    two_mins_ago = now_utc - timedelta(minutes=2)
    mock_session_cooldown = {
        "status": "stopped",
        "auto_stop_reason": "new_session_requested",
        "auto_stopped_at": two_mins_ago.isoformat()
    }
    with patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json") as mock_read, \
         patch("sys.argv", ["generate_flash_prompt.py"]), \
         patch("sys.stderr") as mock_stderr:

        def side_effect3(path, default=None):
            if "phase_state" in path:
                return mock_phase_info
            elif "opus_directive" in path:
                return mock_directive_info
            elif "task_queue" in path:
                return mock_task_queue_empty
            elif "flash_session" in path:
                return mock_session_cooldown
            elif "user_schedule" in path:
                return mock_user_schedule
            return default

        mock_read.side_effect = side_effect3
        with pytest.raises(SystemExit) as excinfo:
            generate_flash_prompt.generate_prompt()
        assert excinfo.value.code == 0
        mock_stderr.write.assert_any_call("   --force オプションで強制生成できます")

    # Case 4: クールダウン中だが --force がある場合は強制生成する
    with patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json") as mock_read, \
         patch("sys.argv", ["generate_flash_prompt.py", "--force"]):

        mock_read.side_effect = side_effect3
        prompt = generate_flash_prompt.generate_prompt()
        assert "Flash専用セッション 起動指示プロンプト" in prompt

    # Case 5: auto_stopped_at が不正なフォーマットで ValueError をスルーする
    mock_session_invalid_date = {
        "status": "stopped",
        "auto_stop_reason": "new_session_requested",
        "auto_stopped_at": "invalid_date_format"
    }
    with patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json") as mock_read, \
         patch("sys.argv", ["generate_flash_prompt.py"]):

        def side_effect4(path, default=None):
            if "phase_state" in path:
                return mock_phase_info
            elif "opus_directive" in path:
                return mock_directive_info
            elif "task_queue" in path:
                return mock_task_queue_empty
            elif "flash_session" in path:
                return mock_session_invalid_date
            elif "user_schedule" in path:
                return mock_user_schedule
            return default

        mock_read.side_effect = side_effect4
        prompt = generate_flash_prompt.generate_prompt()
        assert "Flash専用セッション 起動指示プロンプト" in prompt


def test_generate_prompt_forced_mode_and_custom_night():
    from datetime import datetime, timezone
    mock_phase_info = {}
    mock_directive_info = {}
    mock_task_queue = {}
    mock_session = {
        "status": "stopped"
    }

    # Case 1: --mode 引数による強制モード
    mock_user_schedule = {
        "flash_profiles": {
            "night": {
                "mode_name": "NIGHT_FORCED",
                "batch_size": 10,
                "timer_seconds": 480,
                "archive_batches": 40,
                "archive_hours": 8,
                "context_target_pct": 70,
                "context_warn_pct": 60,
                "status_verbosity": "minimal",
                "subagent_timeout": 900,
                "batch_timeout": 1200,
                "context_pct_per_batch": 4,
            }
        }
    }
    with patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json") as mock_read, \
         patch("sys.argv", ["generate_flash_prompt.py", "--mode", "night"]):

        def side_effect(path, default=None):
            if "phase_state" in path:
                return mock_phase_info
            elif "opus_directive" in path:
                return mock_directive_info
            elif "task_queue" in path:
                return mock_task_queue
            elif "flash_session" in path:
                return mock_session
            elif "user_schedule" in path:
                return mock_user_schedule
            return default

        mock_read.side_effect = side_effect
        prompt = generate_flash_prompt.generate_prompt()
        assert "NIGHT_FORCED" in prompt

    # Case 2: night_start <= night_end での夜間判定 (01:00-05:00 の間で 03:00)
    mock_user_schedule_custom_night = {
        "mode_schedule": {
            "night_start": "01:00",
            "night_end": "05:00"
        },
        "flash_profiles": {
            "night": {
                "mode_name": "CUSTOM_NIGHT",
                "batch_size": 10,
                "timer_seconds": 480,
                "archive_batches": 40,
                "archive_hours": 8,
                "context_target_pct": 70,
                "context_warn_pct": 60,
                "status_verbosity": "minimal",
                "subagent_timeout": 900,
                "batch_timeout": 1200,
                "context_pct_per_batch": 4,
            }
        }
    }
    with patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json") as mock_read, \
         patch("backend.agents.orchestration.generate_flash_prompt.datetime") as mock_dt, \
         patch("sys.argv", ["generate_flash_prompt.py"]):

        mock_dt.now.return_value = datetime(2026, 6, 22, 18, 0, tzinfo=timezone.utc) # UTC 18:00 -> JST 03:00
        mock_dt.fromisoformat = datetime.fromisoformat

        def side_effect2(path, default=None):
            if "phase_state" in path:
                return mock_phase_info
            elif "opus_directive" in path:
                return mock_directive_info
            elif "task_queue" in path:
                return mock_task_queue
            elif "flash_session" in path:
                return mock_session
            elif "user_schedule" in path:
                return mock_user_schedule_custom_night
            return default

        mock_read.side_effect = side_effect2
        prompt = generate_flash_prompt.generate_prompt()
        assert "CUSTOM_NIGHT" in prompt


def test_main_and_direct_run():
    # safe_read_json の実体を通過させる
    res = generate_flash_prompt._safe_read_json("non_existent_file.json", default={"test": 123})
    assert res == {"test": 123}

    # main() を直接呼び出し
    with patch("sys.argv", ["generate_flash_prompt.py", "--force"]), \
         patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json") as mock_read, \
         patch("sys.stdout") as mock_stdout:
        
        def side_effect(path, default=None):
            if "flash_session" in path:
                return {"status": "stopped"}
            return default if default is not None else {}

        mock_read.side_effect = side_effect

        generate_flash_prompt.main()
        mock_stdout.write.assert_any_call("上記をそのまま新規Flashセッションに貼り付けてください。")


def test_main_via_runpy():
    import runpy
    with patch("sys.argv", ["generate_flash_prompt.py", "--force"]), \
         patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json") as mock_read, \
         patch("sys.stdout") as mock_stdout:
        
        def side_effect(path, default=None):
            if "flash_session" in path:
                return {"status": "stopped"}
            return default if default is not None else {}

        mock_read.side_effect = side_effect

        script_path = os.path.abspath(generate_flash_prompt.__file__)
        runpy.run_path(script_path, run_name="__main__")
        
        assert mock_stdout.write.called
