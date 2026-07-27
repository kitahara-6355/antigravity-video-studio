import os
import json
import pytest
from unittest.mock import patch
from datetime import datetime, timezone

from backend.agents.orchestration.health_check import (
    reset_opus_session,
    assess_opus_session,
    check_compaction_in_transcript
)

# 一時的なファイルパスを設定するためのフィクスチャ
@pytest.fixture
def temp_paths(tmp_path):
    temp_opus_json = tmp_path / "temp_opus_session.json"
    temp_flash_json = tmp_path / "temp_flash_session.json"
    temp_task_json = tmp_path / "temp_task_queue.json"
    temp_phase_json = tmp_path / "temp_phase_state.json"
    
    # 必須の初期データ
    temp_opus_json.write_text("{}", encoding="utf-8")
    temp_flash_json.write_text('{"status": "running", "last_heartbeat": "2026-06-07T10:00:00Z"}', encoding="utf-8")
    temp_task_json.write_text('{"tasks": []}', encoding="utf-8")
    temp_phase_json.write_text('{"current_phase": 33, "current_milestone": "M33.1"}', encoding="utf-8")

    with patch("backend.agents.orchestration.health_check.OPUS_SESSION_PATH", str(temp_opus_json)), \
         patch("backend.agents.orchestration.health_check.FLASH_SESSION_PATH", str(temp_flash_json)), \
         patch("backend.agents.orchestration.health_check.TASK_QUEUE_PATH", str(temp_task_json)), \
         patch("backend.agents.orchestration.health_check.PHASE_STATE_PATH", str(temp_phase_json)):
        yield temp_opus_json


def test_reset_opus_session(temp_paths):
    conv_id = "test-conversation-id-123"
    data = reset_opus_session(conv_id)
    assert data["conversation_id"] == conv_id
    assert data["compaction_occurred"] is False

    # ファイルの読み込み確認
    with open(temp_paths, "r", encoding="utf-8") as f:
        file_data = json.load(f)
    assert file_data["conversation_id"] == conv_id
    assert file_data["compaction_occurred"] is False


def test_assess_opus_session_compaction_flag(temp_paths):
    # すでに compaction_occurred = True の場合
    started_str = datetime.now(timezone.utc).isoformat()
    session_data = {
        "session_started_at": started_str,
        "conversation_id": "test-conv",
        "cron_iterations": 1,
        "compaction_occurred": True
    }
    with open(temp_paths, "w", encoding="utf-8") as f:
        json.dump(session_data, f)

    result = assess_opus_session()
    suggestions = result[0] if isinstance(result, tuple) else result
    opus_health = result[1] if isinstance(result, tuple) else {}
    
    assert opus_health["stage"] == "STALE"
    assert any("コンテキスト圧縮" in s for s in suggestions)


def test_assess_opus_session_compaction_autodetect(temp_paths, tmp_path):
    started_str = datetime.now(timezone.utc).isoformat()
    session_data = {
        "session_started_at": started_str,
        "conversation_id": "test-autodetect-conv",
        "cron_iterations": 1,
        "compaction_occurred": False
    }
    with open(temp_paths, "w", encoding="utf-8") as f:
        json.dump(session_data, f)

    # transcript.jsonl をモックするためのフォルダ構造
    compaction_log = '{"step_index":0,"source":"USER_EXPLICIT","type":"USER_INPUT","content":"コンテキスト圧縮が発生しました"}\n'
    
    # 簡易化のために、tmp_path に合わせたパスを返すように os.path.expanduser をパッチする。
    mock_home = str(tmp_path)
    real_brain_dir = tmp_path / ".gemini" / "antigravity" / "brain" / "test-autodetect-conv" / ".system_generated" / "logs"
    real_brain_dir.mkdir(parents=True, exist_ok=True)
    real_transcript = real_brain_dir / "transcript.jsonl"
    real_transcript.write_text(compaction_log, encoding="utf-8")

    with patch("os.path.expanduser", return_value=mock_home):
        # コンパクションの検出確認
        assert check_compaction_in_transcript("test-autodetect-conv") is True
        
        # assess_opus_session の実行により、自動検知されて STALE になること
        result = assess_opus_session(check_compaction=True)
        suggestions = result[0] if isinstance(result, tuple) else result
        opus_health = result[1] if isinstance(result, tuple) else {}
        
        assert opus_health["stage"] == "STALE"
        assert any("コンテキスト圧縮" in s for s in suggestions)
        
        # フラグがファイルに書き出されたか確認
        with open(temp_paths, "r", encoding="utf-8") as f:
            updated_data = json.load(f)
        assert updated_data["compaction_occurred"] is True
