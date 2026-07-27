import pytest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch
from backend.services.hook_evolution_service import HookEvolutionService

@pytest.fixture
def temp_evolution_log():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "evolution_log.json"
        # 初期データを空で作成
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump({"entries": [], "hook_improvements": []}, f)
        yield log_file

def test_hook_evolution_service_lifecycle(temp_evolution_log):
    # EVOLUTION_LOG_FILE を一時ファイルにパッチしてインスタンス作成
    with patch("backend.services.hook_evolution_service.EVOLUTION_LOG_FILE", temp_evolution_log):
        service = HookEvolutionService()

        # 1. 改善の適用
        res = service.apply_improvement(
            task_id="task-123",
            improvement_type="opening_hook",
            original_text="Hello guys",
            improved_text="Hey everyone, welcome!",
            expected_score_boost=5
        )
        assert res["success"] is True
        assert res["applied"]["text"] == "Hey everyone, welcome!"

        # 2. 履歴の確認
        history_res = service.get_history(task_id="task-123")
        assert history_res["success"] is True
        assert history_res["count"] == 1
        assert history_res["history"][0]["original_text"] == "Hello guys"

        # 他のtask_idではヒットしないこと
        history_empty = service.get_history(task_id="task-999")
        assert history_empty["success"] is True
        assert history_empty["count"] == 0

        # 3. 改善の取り消し
        revert_res = service.revert_latest(task_id="task-123")
        assert revert_res["success"] is True
        assert revert_res["reverted_text"] == "Hello guys"

        # 履歴が reverted になっていること
        history_reverted = service.get_history(task_id="task-123")
        assert history_reverted["history"][0]["status"] == "reverted"

def test_hook_evolution_service_revert_filtering(temp_evolution_log):
    with patch("backend.services.hook_evolution_service.EVOLUTION_LOG_FILE", temp_evolution_log):
        service = HookEvolutionService()

        # 複数のタスクから適用
        service.apply_improvement("task-A", "type-A", "orig-A", "impr-A")
        service.apply_improvement("task-B", "type-B", "orig-B", "impr-B")

        # task-A を指定して revert を試みる
        # 最新は task-B (applied) だが、指定が task-A なので task-B はスキップされ task-A が revert されるはず
        revert_res = service.revert_latest(task_id="task-A")
        assert revert_res["success"] is True
        assert revert_res["reverted_text"] == "orig-A"

        # 状態確認
        history = service.get_history()["history"]
        # task-A は reverted、task-B は applied のまま
        task_a_entry = next(h for h in history if h["task_id"] == "task-A")
        task_b_entry = next(h for h in history if h["task_id"] == "task-B")
        assert task_a_entry["status"] == "reverted"
        assert task_b_entry["status"] == "applied"
