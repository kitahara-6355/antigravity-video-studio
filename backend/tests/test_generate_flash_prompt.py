# -*- coding: utf-8 -*-
import pytest
import os
import json
from unittest.mock import patch, mock_open, MagicMock
from backend.agents.orchestration.generate_flash_prompt import (
    _safe_read_json,
    _get_phase_info,
    _get_directive_info,
    _get_batch_status,
    _get_session_history,
    generate_prompt,
    main
)

def test_safe_read_json_not_exists():
    with patch("os.path.exists", return_value=False):
        res = _safe_read_json("dummy_path.json", default={"x": 1})
        assert res == {"x": 1}

def test_safe_read_json_invalid_json():
    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data="invalid json")):
        res = _safe_read_json("dummy_path.json", default={"x": 2})
        assert res == {"x": 2}

def test_safe_read_json_success():
    data = {"current_phase": 25, "current_milestone": "M25.2"}
    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=json.dumps(data))):
        res = _safe_read_json("dummy_path.json", default={})
        assert res == data

def test_get_phase_info():
    # phase_state.json が存在しない場合
    with patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json", return_value={}):
        res = _get_phase_info()
        assert res == {"phase": "?", "milestone": "?", "emergency_stop": False}

    # 正常な場合
    with patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json", return_value={
        "current_phase": 25,
        "current_milestone": "M25.2",
        "emergency_stop": True
    }):
        res = _get_phase_info()
        assert res == {"phase": 25, "milestone": "M25.2", "emergency_stop": True}

def test_get_directive_info():
    # Directive  ファイルなし
    with patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json", return_value=None):
        res = _get_directive_info()
        assert "Directiveファイルなし" in res

    # 正常な場合
    with patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json", return_value={
        "directive_id": "DIR-001",
        "notes": "Test notes",
        "priorities": {"test_weaver": 60, "bug_hunter": 40},
        "focus_modules": ["backend/api/routes/video.py"]
    }):
        res = _get_directive_info()
        assert "DIR-001" in res
        assert "Test notes" in res
        assert "test_weaver" in res
        assert "video.py" in res

def test_get_batch_status():
    # タスクキューなし
    with patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json", return_value=None):
        res = _get_batch_status()
        assert "タスクキューなし" in res

    # 正常な場合
    with patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json", return_value={
        "current_batch_id": "batch_123",
        "tasks": [
            {"status": "pending"},
            {"status": "running"},
            {"status": "pass"},
            {"status": "fail"},
            {"status": "failed"},
        ]
    }):
        res = _get_batch_status()
        assert "batch_123" in res
        assert "pending=1" in res
        assert "running=1" in res
        assert "pass=1" in res
        assert "fail=2" in res

def test_get_session_history():
    # セッション情報なし
    with patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json", return_value=None):
        res = _get_session_history()
        assert "セッション情報なし" in res

    # 正常な場合
    with patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json", return_value={
        "tasks_completed_in_session": 10,
        "batches_in_session": 2
    }):
        res = _get_session_history()
        assert "10タスク完了" in res
        assert "2バッチ処理" in res

def test_generate_prompt():
    with patch("backend.agents.orchestration.generate_flash_prompt._get_phase_info", return_value={"phase": 25, "milestone": "M25.2", "emergency_stop": False}), \
         patch("backend.agents.orchestration.generate_flash_prompt._get_directive_info", return_value="Mock Directive Info"), \
         patch("backend.agents.orchestration.generate_flash_prompt._get_batch_status", return_value="Mock Batch Status"), \
         patch("backend.agents.orchestration.generate_flash_prompt._get_session_history", return_value="Mock Session History"):
        
        prompt = generate_prompt()
        assert "Mock Directive Info" in prompt
        assert "Mock Batch Status" in prompt
        assert "Mock Session History" in prompt
        assert "Phase 25" in prompt
        assert "M25.2" in prompt

def test_main():
    with patch("backend.agents.orchestration.generate_flash_prompt.generate_prompt", return_value="Mocked Prompt Text"), \
         patch("builtins.print") as mock_print:
        main()
        mock_print.assert_any_call("Mocked Prompt Text")

def test_main_guard_inactive():
    import backend.agents.orchestration.generate_flash_prompt as gfp
    original_workspace = gfp.WORKSPACE_DIR
    gfp.WORKSPACE_DIR = "C:/some/path/video-automation 2"
    try:
        with patch("backend.agents.orchestration.generate_flash_prompt.generate_prompt", return_value="Mocked Prompt"), \
             patch("builtins.print") as mock_print:
            gfp.main()
            mock_print.assert_any_call("Mocked Prompt")
    finally:
        gfp.WORKSPACE_DIR = original_workspace

def test_module_execution_as_main():
    import runpy
    import sys
    gfp_module_name = "backend.agents.orchestration.generate_flash_prompt"
    original_module = sys.modules.get(gfp_module_name)
    if gfp_module_name in sys.modules:
        del sys.modules[gfp_module_name]
    
    try:
        with patch("builtins.print") as mock_print:
            runpy.run_module(gfp_module_name, run_name="__main__")
            any_success_msg = any("プロンプト生成完了" in str(args[0]) for args, _ in mock_print.call_args_list if args)
            assert any_success_msg
    finally:
        if original_module:
            sys.modules[gfp_module_name] = original_module


def test_safe_read_json_os_error():
    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", side_effect=OSError("Permission denied")):
        res = _safe_read_json("dummy_path.json", default={"x": 3})
        assert res == {"x": 3}

def test_get_phase_info_missing_keys():
    with patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json", return_value={
        "current_phase": 25,
    }):
        res = _get_phase_info()
        assert res == {"phase": 25, "milestone": "?", "emergency_stop": False}

def test_get_directive_info_empty_fields():
    with patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json", return_value={
        "directive_id": "DIR-002"
    }):
        res = _get_directive_info()
        assert "DIR-002" in res
        assert "優先度配分" not in res
        assert "重点モジュール" not in res
        assert "戦略メモ" in res

def test_get_batch_status_empty_tasks():
    with patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json", return_value={
        "current_batch_id": "batch_empty",
        "tasks": []
    }):
        res = _get_batch_status()
        assert "batch_empty" in res
        assert "pending=0" in res
        assert "running=0" in res
        assert "pass=0" in res
        assert "fail=0" in res

def test_get_batch_status_unknown_status():
    with patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json", return_value={
        "current_batch_id": "batch_unknown",
        "tasks": [
            {"status": "pending"},
            {"status": "skipped"},
            {"status": "aborted"},
            {"status": "pass"}
        ]
    }):
        res = _get_batch_status()
        assert "batch_unknown" in res
        assert "pending=1" in res
        assert "running=0" in res
        assert "pass=1" in res
        assert "fail=0" in res


def test_get_thumbnail_status_no_queue():
    from backend.agents.orchestration.generate_flash_prompt import _get_thumbnail_status
    with patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json", return_value=None):
        res = _get_thumbnail_status()
        assert "サムネイルタスク情報なし" in res

def test_get_thumbnail_status_no_thumb_tasks():
    from backend.agents.orchestration.generate_flash_prompt import _get_thumbnail_status
    with patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json", return_value={
        "tasks": [
            {"group": "test_weaver", "status": "pass"}
        ]
    }):
        res = _get_thumbnail_status()
        assert "現在のバッチにサムネイルタスクはありません" in res

def test_get_thumbnail_status_success():
    from backend.agents.orchestration.generate_flash_prompt import _get_thumbnail_status
    with patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json", return_value={
        "tasks": [
            {"group": "thumbnail", "status": "pending"},
            {"group": "thumbnail", "status": "running"},
            {"group": "thumbnail", "status": "pass"},
            {"group": "thumbnail", "status": "fail"},
            {"group": "thumbnail", "status": "failed"},
            {"group": "test_weaver", "status": "pass"}
        ]
    }):
        res = _get_thumbnail_status()
        assert "合計=5件" in res
        assert "pending=1" in res
        assert "running=1" in res
        assert "pass=1" in res
        assert "fail=2" in res


def test_get_directive_info_with_agent_performance():
    # priorities に対し、agent_performance（成功率）が存在する場合の自動調整テスト
    directive_data = {
        "directive_id": "DIR-003",
        "notes": "Adjustment test",
        "priorities": {"test_weaver": 50, "bug_hunter": 50},
        "focus_modules": []
    }
    
    evo_log_data = {
        "agent_performance": {
            "test_weaver": {"success_rate": 0.5, "passed": 5, "total": 10},
            "bug_hunter": {"success_rate": 1.0, "passed": 8, "total": 8}
        }
    }

    def mock_read_json(path, default=None):
        if "opus_directive.json" in path:
            return directive_data
        elif "evolution_log.json" in path:
            return evo_log_data
        return default

    with patch("backend.agents.orchestration.generate_flash_prompt._safe_read_json", side_effect=mock_read_json):
        res = _get_directive_info()
        assert "DIR-003" in res
        assert "優先度配分（自動進化同期）" in res
        assert "`test_weaver`: 33%" in res
        assert "`bug_hunter`: 67%" in res
        assert "50.0%打率" in res
        assert "100.0%打率" in res
