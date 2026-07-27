import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from backend.agents.orchestration.orchestrator import OrchestrationHub

def test_input_guardrail():
    hub = OrchestrationHub()
    
    # 不正な型に対するガードレール検証
    with pytest.raises(TypeError):
        hub.get_user_intervention_forecast("invalid_datetime")
        
    with pytest.raises(TypeError):
        hub._compute_eta_and_next_check("invalid_datetime")
        
    # tzinfo なし（naive datetime）に対する自動UTC適用検証
    naive_dt = datetime(2026, 6, 4, 12, 0, 0)
    forecast = hub.get_user_intervention_forecast(naive_dt)
    assert forecast is not None

def test_safety_fallback_empty_files():
    hub = OrchestrationHub()
    
    # 各JSONの読み込みエラー時（破損・欠落）のセーフティフォールバック検証
    with patch("backend.agents.orchestration.orchestrator._read_json", side_effect=Exception("Read error")):
        with patch("pathlib.Path.exists", return_value=False):
            res = hub._compute_eta_and_next_check()
            assert res["remaining"] == 0
            assert res["throughput_tph"] == 0.0
            
            forecast = hub.get_user_intervention_forecast()
            assert "🙋‍♂️ ユーザー介入見通し" in forecast

def test_quantitative_mapping():
    hub = OrchestrationHub()
    
    # 10:00 UTC = 19:00 JST
    now_dt = datetime(2026, 6, 4, 10, 0, 0, tzinfo=timezone.utc)
    
    # 正常なデータがある状態での定量マッピングの一貫性を検証
    test_session = {
        "status": "running",
        "tasks_completed_in_session": 10,
        "context_consumption_pct": 20,
        "session_started_at": (now_dt - timedelta(hours=2)).isoformat()
    }
    test_queue = {
        "tasks": [
            {"status": "pending"},
            {"status": "pending"},
            {"status": "running"}
        ]
    }
    test_schedule = {
        "flash_profiles": {
            "standard": {
                "context_target_pct": 70,
                "context_pct_per_batch": 4,
                "batch_size": 6
            }
        },
        "windows": [
            {"start": "09:00", "end": "12:00", "label": "朝"}
        ]
    }
    
    # _read_json をモックして擬似データを注入
    def mock_read_json(path):
        from backend.agents.orchestration.orchestrator import FLASH_SESSION_PATH, TASK_QUEUE_PATH, USER_SCHEDULE_PATH
        # 文字列として部分一致比較
        path_str = str(path).replace("\\", "/")
        if "flash_session.json" in path_str:
            return test_session
        elif "task_queue.json" in path_str:
            return test_queue
        elif "user_schedule.json" in path_str:
            return test_schedule
        return {}
        
    with patch("backend.agents.orchestration.orchestrator._read_json", side_effect=mock_read_json):
        with patch("pathlib.Path.exists", return_value=False):
            res = hub._compute_eta_and_next_check(now_dt)
            
            assert res["throughput_tph"] == 5.0
            assert res["remaining"] == 3
            assert res["eta_minutes"] == 36
            assert res["session_remaining_tasks"] == 25
            assert res["session_eta_minutes"] == 300  # 5時間
            
            forecast = hub.get_user_intervention_forecast(now_dt)
            
            # 定量的マッピングの検証
            assert "Flash 10タスク完了" in forecast
            assert "コンテキスト20%" in forecast
            assert "セッション残容量25タスク" in forecast
            # ETA JST: 19:00 + 5h = 24:00 (00:00 JST)
            # %H:%M 形式なので 00:00 JST となるはず
            assert "00:00 JST" in forecast
