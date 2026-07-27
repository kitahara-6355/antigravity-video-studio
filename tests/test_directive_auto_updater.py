import json
import logging
from unittest.mock import MagicMock, patch
import pytest

from backend.agents.orchestration import directive_auto_updater

@pytest.fixture
def mock_paths(tmp_path, monkeypatch):
    directive_file = tmp_path / "opus_directive.json"
    phase_state_file = tmp_path / "phase_state.json"
    
    # directive_auto_updater のグローバル定数を差し替え
    monkeypatch.setattr(directive_auto_updater, "_DIRECTIVE_PATH", directive_file)
    monkeypatch.setattr(directive_auto_updater, "_PHASE_STATE_PATH", phase_state_file)
    
    return {
        "directive": directive_file,
        "phase_state": phase_state_file
    }

def test_should_update(mock_paths):
    # phase_state.json が存在しない場合 (デフォルト 29)
    # opus_directive.json も存在しない場合 (デフォルト "" -> phase None)
    assert directive_auto_updater.should_update() is True
    
    # 両方に同じ phase を書き込む
    mock_paths["phase_state"].write_text(json.dumps({"current_phase": 33}), encoding="utf-8")
    mock_paths["directive"].write_text(json.dumps({"directive_id": "D-opus-auto-p33-v1"}), encoding="utf-8")
    
    assert directive_auto_updater.should_update() is False
    assert directive_auto_updater.should_update(current_phase=33) is False
    
    # 異なる phase の場合
    assert directive_auto_updater.should_update(current_phase=34) is True

def test_auto_update_directive_no_change(mock_paths):
    mock_paths["phase_state"].write_text(json.dumps({"current_phase": 33}), encoding="utf-8")
    directive_data = {
        "directive_id": "D-opus-auto-p33-v1",
        "priorities": {"design_stock": 10, "test_weaver": 20}
    }
    mock_paths["directive"].write_text(json.dumps(directive_data), encoding="utf-8")
    
    # Phaseが同じなら更新スキップして既存のものを返す
    res = directive_auto_updater.auto_update_directive(current_phase=33)
    assert res == directive_data

def test_auto_update_directive_success(mock_paths):
    # 以前の directive
    mock_paths["directive"].write_text(json.dumps({"directive_id": "D-opus-auto-p32-v1"}), encoding="utf-8")
    
    # TaskLearningEngine のモック
    mock_engine = MagicMock()
    mock_engine.get_group_performance_report.return_value = {
        "test_weaver": {"hit_rate": 0.8},
        "bug_hunter": {"hit_rate": 0.9},
        "refactor": {"hit_rate": 0.3},
        "tdr_cleanup": {"hit_rate": 0.2},
        "thumbnail": {"hit_rate": 0.5}
    }
    mock_engine.detect_diminishing_returns.return_value = [{"module": "module_a"}]
    
    with patch("backend.agents.orchestration.task_learning_engine.TaskLearningEngine", return_value=mock_engine):
        res = directive_auto_updater.auto_update_directive(current_phase=33)
        
        assert res["directive_id"] == "D-opus-auto-p33-v1"
        assert res["auto_generated"] is True
        assert "module_a" in res["blacklist_override"]
        
        # 優先度の合計が 100 になるか
        priorities = res["priorities"]
        assert sum(priorities.values()) == 100
        # 各グループの最低保障 5%
        for g in ["test_weaver", "bug_hunter", "refactor", "tdr_cleanup", "thumbnail"]:
            assert priorities[g] >= 5
        assert priorities["design_stock"] == 10

@pytest.mark.parametrize("exception_type", [
    ImportError,
    FileNotFoundError,
    json.JSONDecodeError("msg", "doc", 0),
    PermissionError,
    ValueError
])
def test_auto_update_directive_learning_engine_exceptions(mock_paths, exception_type):
    mock_paths["directive"].write_text(json.dumps({"directive_id": "D-opus-auto-p32-v1"}), encoding="utf-8")
    
    # ラーニングエンジン呼び出し時に具体的な例外を発生させる
    with patch("backend.agents.orchestration.task_learning_engine.TaskLearningEngine", side_effect=exception_type):
        res = directive_auto_updater.auto_update_directive(current_phase=33)
        
        # 例外が発生しても処理はフォールバックして成功する
        assert res["directive_id"] == "D-opus-auto-p33-v1"
        assert res["priorities"] == {
            "test_weaver": 20,
            "bug_hunter": 20,
            "refactor": 20,
            "tdr_cleanup": 15,
            "thumbnail": 15,
            "design_stock": 10,
        }

def test_auto_update_directive_unexpected_exception(mock_paths):
    mock_paths["directive"].write_text(json.dumps({"directive_id": "D-opus-auto-p32-v1"}), encoding="utf-8")
    
    # 想定外の例外（例: AttributeError）はキャッチされず上に伝播する
    with patch("backend.agents.orchestration.task_learning_engine.TaskLearningEngine", side_effect=AttributeError("unexpected")):
        with pytest.raises(AttributeError):
            directive_auto_updater.auto_update_directive(current_phase=33)
