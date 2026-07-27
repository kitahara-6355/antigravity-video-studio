import os
import json
from datetime import datetime, timezone, timedelta
import pytest
from backend.agents.orchestration.design_stock import (
    DesignStockStore,
    DIFFICULTY_ORDER,
    DIFFICULTY_LABELS,
    SESSION_MAP,
    STATUS_LABELS,
)

def test_design_stock_store_init_empty(tmp_path):
    test_path = tmp_path / "design_stock_test.json"
    store = DesignStockStore(path=str(test_path))
    assert store.path == str(test_path)
    assert store.config == {"target_stock_count": 10, "phases_ahead": 3, "stale_days_sa": 3, "stale_days_bc": 7}
    assert store.items == []
    assert not os.path.exists(test_path)

def test_design_stock_store_init_existing(tmp_path):
    test_path = tmp_path / "design_stock_test.json"
    initial_data = {
        "config": {"target_stock_count": 5, "phases_ahead": 2, "stale_days_sa": 1, "stale_days_bc": 2},
        "stock_items": [
            {"id": "DS-001", "title": "Test Item", "phase": 27, "difficulty": "B", "status": "pending"}
        ]
    }
    with open(test_path, "w", encoding="utf-8") as f:
        json.dump(initial_data, f)
        
    store = DesignStockStore(path=str(test_path))
    assert store.config["target_stock_count"] == 5
    assert len(store.items) == 1
    assert store.items[0]["id"] == "DS-001"

def test_add_item(tmp_path):
    test_path = tmp_path / "design_stock_test.json"
    store = DesignStockStore(path=str(test_path))
    
    item_b = store.add_item("Title B", phase=27, difficulty="B", description="Desc B", milestone="M1", source_phase_task="task1", implementation_steps=["step1"])
    assert item_b["id"] == "DS-001"
    assert item_b["title"] == "Title B"
    assert item_b["difficulty"] == "B"
    assert item_b["session_target"] == "opus_then_flash"
    assert item_b["status"] == "pending"
    assert "three_point_check" not in item_b
    assert item_b["implementation_steps"] == ["step1"]
    
    item_a = store.add_item("Title A", phase=27, difficulty="A")
    assert item_a["id"] == "DS-002"
    assert item_a["difficulty"] == "A"
    assert item_a["session_target"] == "opus"
    assert "three_point_check" in item_a
    assert item_a["three_point_check"] == {
        "quantitative_mapping": False,
        "safety_fallback": False,
        "input_guardrail": False,
    }
    
    with pytest.raises(ValueError):
        store.add_item("Invalid", phase=27, difficulty="X")

def test_update_status(tmp_path):
    test_path = tmp_path / "design_stock_test.json"
    store = DesignStockStore(path=str(test_path))
    item = store.add_item("Title B", phase=27, difficulty="B")
    
    res = store.update_status("DS-001", "designed")
    assert res is True
    assert store.items[0]["status"] == "designed"
    assert store.items[0]["last_activity"] is not None
    
    res_fake = store.update_status("DS-999", "designed")
    assert res_fake is False

def test_update_three_point_check(tmp_path):
    test_path = tmp_path / "design_stock_test.json"
    store = DesignStockStore(path=str(test_path))
    store.add_item("Title A", phase=27, difficulty="A")
    store.add_item("Title B", phase=27, difficulty="B")
    
    res = store.update_three_point_check("DS-001", "quantitative_mapping", True)
    assert res is True
    assert store.items[0]["three_point_check"]["quantitative_mapping"] is True
    
    res_invalid_check = store.update_three_point_check("DS-001", "invalid_check", True)
    assert res_invalid_check is False
    
    res_no_check = store.update_three_point_check("DS-002", "quantitative_mapping", True)
    assert res_no_check is False
    
    res_fake = store.update_three_point_check("DS-999", "quantitative_mapping", True)
    assert res_fake is False

def test_remove_item(tmp_path):
    test_path = tmp_path / "design_stock_test.json"
    store = DesignStockStore(path=str(test_path))
    store.add_item("Title A", phase=27, difficulty="A")
    store.add_item("Title B", phase=27, difficulty="B")
    
    assert len(store.items) == 2
    store.remove_item("DS-001")
    assert len(store.items) == 1
    assert store.items[0]["id"] == "DS-002"

def test_get_sorted_items(tmp_path):
    test_path = tmp_path / "design_stock_test.json"
    store = DesignStockStore(path=str(test_path))
    
    store.add_item("Title C", phase=27, difficulty="C")
    store.add_item("Title S", phase=27, difficulty="S")
    store.add_item("Title B", phase=27, difficulty="B")
    store.add_item("Title A", phase=27, difficulty="A")
    
    sorted_items = store.get_sorted_items()
    assert [item["difficulty"] for item in sorted_items] == ["S", "A", "B", "C"]

def test_calculate_age_days(tmp_path):
    test_path = tmp_path / "design_stock_test.json"
    store = DesignStockStore(path=str(test_path))
    
    now = datetime.now(timezone.utc)
    
    dt_str = (now - timedelta(days=5)).isoformat().replace("+00:00", "Z")
    age = store._calculate_age_days(dt_str, now)
    assert pytest.approx(age, abs=0.01) == 5.0
    
    dt_str_naive = (now - timedelta(days=2)).replace(tzinfo=None).isoformat()
    age_naive = store._calculate_age_days(dt_str_naive, now)
    assert pytest.approx(age_naive, abs=0.01) == 2.0
    
    assert store._calculate_age_days("", now) is None
    assert store._calculate_age_days("invalid-date-format", now) is None
    assert store._calculate_age_days(None, now) is None

def test_get_stale_items(tmp_path):
    test_path = tmp_path / "design_stock_test.json"
    store = DesignStockStore(path=str(test_path))
    
    now = datetime.now(timezone.utc)
    stale_sa_dt = (now - timedelta(days=4)).isoformat()
    stale_bc_dt = (now - timedelta(days=8)).isoformat()
    fresh_dt = (now - timedelta(days=1)).isoformat()
    
    item1 = store.add_item("Title S", phase=27, difficulty="S")
    item1["last_activity"] = stale_sa_dt
    
    item2 = store.add_item("Title B", phase=27, difficulty="B")
    item2["last_activity"] = stale_bc_dt
    
    item3 = store.add_item("Title C", phase=27, difficulty="C")
    item3["last_activity"] = fresh_dt
    
    item4 = store.add_item("Title A", phase=27, difficulty="A")
    item4["last_activity"] = stale_sa_dt
    item4["status"] = "dispatched"
    
    item5 = store.add_item("Title C2", phase=27, difficulty="C")
    item5["last_activity"] = "invalid-date"
    
    item6 = store.add_item("Title C3", phase=27, difficulty="C")
    item6["last_activity"] = None
    item6["created_at"] = stale_bc_dt
    
    item7 = store.add_item("Title C4", phase=27, difficulty="C")
    item7["last_activity"] = stale_bc_dt
    item7["status"] = "completed"
    
    stale = store.get_stale_items()
    stale_ids = [i["id"] for i in stale]
    assert "DS-001" in stale_ids
    assert "DS-002" in stale_ids
    assert "DS-003" not in stale_ids
    assert "DS-004" not in stale_ids
    assert "DS-005" not in stale_ids
    assert "DS-006" in stale_ids
    assert "DS-007" not in stale_ids

def test_get_stock_health(tmp_path):
    test_path = tmp_path / "design_stock_test.json"
    store = DesignStockStore(path=str(test_path))
    
    store.add_item("Title S", phase=27, difficulty="S")
    store.add_item("Title A", phase=27, difficulty="A")
    store.add_item("Title B", phase=28, difficulty="B")
    item_dispatched = store.add_item("Title C", phase=29, difficulty="C")
    item_dispatched["status"] = "dispatched"
    
    health = store.get_stock_health()
    assert health["total_active"] == 3
    assert health["target"] == 10
    assert health["shortage"] == 7
    assert health["by_difficulty"] == {"S": 1, "A": 1, "B": 1, "C": 0}
    assert health["by_status"] == {"pending": 3}
    assert health["phases_covered"] == [27, 28]

def test_get_dashboard_summary_empty(tmp_path):
    test_path = tmp_path / "design_stock_test.json"
    store = DesignStockStore(path=str(test_path))
    
    summary = store.get_dashboard_summary()
    assert "設計ストックが空です" in summary

def test_get_dashboard_summary_with_items(tmp_path):
    test_path = tmp_path / "design_stock_test.json"
    store = DesignStockStore(path=str(test_path))
    
    now = datetime.now(timezone.utc)
    stale_dt = (now - timedelta(days=10)).isoformat()
    
    item1 = store.add_item("Title S", phase=27, difficulty="S")
    item1["last_activity"] = stale_dt
    
    item2 = store.add_item("Title C", phase=27, difficulty="C")
    item2["last_activity"] = stale_dt
    
    item3 = store.add_item("Title Dispatched", phase=28, difficulty="B")
    item3["status"] = "dispatched"
    
    item4 = store.add_item("Title A", phase=27, difficulty="A")
    item4["created_at"] = (now - timedelta(days=2)).isoformat().replace("+00:00", "Z")
    
    item5 = store.add_item("Title Other", phase=27, difficulty="B")
    item5["last_activity"] = None
    item5["created_at"] = None
    
    summary = store.get_dashboard_summary()
    
    assert "最高難度" in summary
    assert "低難度" in summary
    assert "Title S" in summary
    assert "Title C" in summary
    assert "Title Dispatched" not in summary
    assert "Title Other" in summary
    assert "—" in summary
    
    assert "滞留設計 & 解消スケジュール" in summary
    assert "DS-001" in summary
    
    assert "ストック不足" in summary
    assert "6個" in summary

def test_get_dashboard_summary_no_high_difficulty(tmp_path):
    test_path = tmp_path / "design_stock_test.json"
    store = DesignStockStore(path=str(test_path))
    
    store.add_item("Title B", phase=27, difficulty="B")
    
    summary = store.get_dashboard_summary()
    assert "高難度タスクなし" in summary

def test_update_three_point_check_to_false(tmp_path):
    test_path = tmp_path / "design_stock_test.json"
    store = DesignStockStore(path=str(test_path))
    store.add_item("Title A", phase=27, difficulty="A")
    
    # 最初は False に設定されているはず
    assert store.items[0]["three_point_check"]["quantitative_mapping"] is False
    
    # True に更新
    res_true = store.update_three_point_check("DS-001", "quantitative_mapping", True)
    assert res_true is True
    assert store.items[0]["three_point_check"]["quantitative_mapping"] is True
    
    # 再度 False に更新
    res_false = store.update_three_point_check("DS-001", "quantitative_mapping", False)
    assert res_false is True
    assert store.items[0]["three_point_check"]["quantitative_mapping"] is False

def test_next_id_with_non_numeric_ids(tmp_path):
    test_path = tmp_path / "design_stock_test.json"
    initial_data = {
        "config": {"target_stock_count": 5, "phases_ahead": 2, "stale_days_sa": 1, "stale_days_bc": 2},
        "stock_items": [
            {"id": "DS-001", "title": "Test 1", "phase": 27, "difficulty": "B", "status": "pending"},
            {"id": "DS-MD-P34-test_weaver-41be", "title": "Test 2", "phase": 27, "difficulty": "B", "status": "pending"},
            {"id": "DS-003", "title": "Test 3", "phase": 27, "difficulty": "B", "status": "pending"},
            {"id": "DS-invalid", "title": "Test 4", "phase": 27, "difficulty": "B", "status": "pending"}
        ]
    }
    with open(test_path, "w", encoding="utf-8") as f:
        json.dump(initial_data, f)
        
    store = DesignStockStore(path=str(test_path))
    next_id = store._next_id()
    assert next_id == "DS-004"
