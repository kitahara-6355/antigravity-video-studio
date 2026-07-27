import os
import json
from datetime import datetime, timezone, timedelta
import pytest
from unittest.mock import patch

from backend.agents.orchestration.design_stock import DesignStockStore


def test_design_stock_store_initialization_no_file(tmp_path):
    """ファイルが存在しない場合の初期ロードテスト"""
    test_file = tmp_path / "non_existent.json"
    store = DesignStockStore(path=str(test_file))
    
    # デフォルト値がセットされていることを確認
    assert store.config == {
        "target_stock_count": 10,
        "phases_ahead": 3,
        "stale_days_sa": 3,
        "stale_days_bc": 7
    }
    assert store.items == []


def test_design_stock_store_initialization_with_file(tmp_path):
    """ファイルが存在する場合のロードテスト"""
    test_file = tmp_path / "existing.json"
    initial_data = {
        "config": {"target_stock_count": 5},
        "stock_items": [{"id": "DS-001", "title": "Test Item"}]
    }
    with open(test_file, "w", encoding="utf-8") as f:
        json.dump(initial_data, f)
        
    store = DesignStockStore(path=str(test_file))
    assert store.config == {"target_stock_count": 5}
    assert len(store.items) == 1
    assert store.items[0]["id"] == "DS-001"


def test_add_item_invalid_difficulty(tmp_path):
    """不正な難易度を指定した際に ValueError が発生することの検証"""
    store = DesignStockStore(path=str(tmp_path / "test.json"))
    with pytest.raises(ValueError) as excinfo:
        store.add_item("Title", phase=27, difficulty="Z")
    assert "Invalid difficulty: Z. Must be S/A/B/C" in str(excinfo.value)


@pytest.mark.parametrize("difficulty,expected_target,has_check", [
    ("S", "opus", True),
    ("A", "opus", True),
    ("B", "opus_then_flash", False),
    ("C", "flash", False)
])
def test_add_item_difficulties(tmp_path, difficulty, expected_target, has_check):
    """各難易度（S, A, B, C）でのアイテム追加テスト"""
    store = DesignStockStore(path=str(tmp_path / "test.json"))
    item = store.add_item(
        title="Test Task",
        phase=28,
        difficulty=difficulty,
        description="Test Desc",
        milestone="M1",
        source_phase_task="T-123",
        implementation_steps=["Step1", "Step2"]
    )
    
    assert item["id"] == "DS-001"
    assert item["title"] == "Test Task"
    assert item["phase"] == 28
    assert item["difficulty"] == difficulty
    assert item["session_target"] == expected_target
    assert item["status"] == "pending"
    assert item["description"] == "Test Desc"
    assert item["milestone"] == "M1"
    assert item["source_phase_task"] == "T-123"
    assert item["implementation_steps"] == ["Step1", "Step2"]
    
    if has_check:
        assert "three_point_check" in item
        assert item["three_point_check"] == {
            "quantitative_mapping": False,
            "safety_fallback": False,
            "input_guardrail": False
        }
    else:
        assert "three_point_check" not in item


def test_next_id_increment(tmp_path):
    """IDの連番生成機能のテスト"""
    store = DesignStockStore(path=str(tmp_path / "test.json"))
    item1 = store.add_item("Task 1", phase=1, difficulty="C")
    item2 = store.add_item("Task 2", phase=1, difficulty="C")
    
    assert item1["id"] == "DS-001"
    assert item2["id"] == "DS-002"
    
    # 削除後にIDの最大値からインクリメントされるか
    store.add_item("Task 3", phase=1, difficulty="C")
    store.remove_item("DS-002")
    
    # 既存の最大IDは DS-003 なので次は DS-004 になるべき
    item4 = store.add_item("Task 4", phase=1, difficulty="C")
    assert item4["id"] == "DS-004"


def test_update_status(tmp_path):
    """ステータス更新の成否テスト"""
    store = DesignStockStore(path=str(tmp_path / "test.json"))
    item = store.add_item("Task", phase=1, difficulty="C")
    
    # 正常系
    assert store.update_status("DS-001", "designed") is True
    assert store.items[0]["status"] == "designed"
    
    # 異常系 (存在しないID)
    assert store.update_status("DS-999", "designed") is False


def test_update_three_point_check(tmp_path):
    """3点チェック項目の更新テスト"""
    store = DesignStockStore(path=str(tmp_path / "test.json"))
    
    # S/Aアイテム (3点チェックあり)
    store.add_item("Task S", phase=1, difficulty="S")
    # Bアイテム (3点チェックなし)
    store.add_item("Task B", phase=1, difficulty="B")
    
    # 正常系：存在するS/Aアイテムの正しいチェック項目を更新
    assert store.update_three_point_check("DS-001", "quantitative_mapping", True) is True
    assert store.items[0]["three_point_check"]["quantitative_mapping"] is True
    
    # 異常系：存在するS/Aアイテムの存在しないチェック項目を更新
    assert store.update_three_point_check("DS-001", "non_existent_check", True) is False
    
    # 異常系：3点チェックを持たないアイテムを更新
    assert store.update_three_point_check("DS-002", "quantitative_mapping", True) is False
    
    # 異常系：存在しないID
    assert store.update_three_point_check("DS-999", "quantitative_mapping", True) is False


def test_get_sorted_items(tmp_path):
    """難易度順 (S -> A -> B -> C) にソートされるかの検証"""
    store = DesignStockStore(path=str(tmp_path / "test.json"))
    store.add_item("B Task", phase=1, difficulty="B")
    store.add_item("S Task", phase=1, difficulty="S")
    store.add_item("C Task", phase=1, difficulty="C")
    store.add_item("A Task", phase=1, difficulty="A")
    
    sorted_items = store.get_sorted_items()
    assert [i["difficulty"] for i in sorted_items] == ["S", "A", "B", "C"]


def test_calculate_age_days(tmp_path):
    """経過日数計算 (_calculate_age_days) の境界値および異常系テスト"""
    store = DesignStockStore(path=str(tmp_path / "test.json"))
    now = datetime(2026, 6, 27, 12, 0, 0, tzinfo=timezone.utc)
    
    # 正常系: Z タイムゾーン
    dt_str_z = "2026-06-26T12:00:00Z"
    age = store._calculate_age_days(dt_str_z, now)
    assert age == 1.0
    
    # 正常系: タイムゾーンなし (UTCとして扱われる)
    dt_str_no_tz = "2026-06-25T12:00:00"
    age_no_tz = store._calculate_age_days(dt_str_no_tz, now)
    assert age_no_tz == 2.0
    
    # 境界/異常系: 空文字列
    assert store._calculate_age_days("", now) is None
    assert store._calculate_age_days(None, now) is None
    
    # 異常値: パースエラー
    assert store._calculate_age_days("invalid-date-string", now) is None
    
    # 異常値: 型エラー (TypeError)
    assert store._calculate_age_days(12345, now) is None


def test_get_stale_items(tmp_path):
    """滞留検知機能のテスト"""
    store = DesignStockStore(path=str(tmp_path / "test.json"))
    
    # テスト現在時刻を仮定
    now = datetime.now(timezone.utc)
    
    # 1. 正常系: S難易度で3日以上経過 (stale_days_sa = 3)
    # last_activity を 4日前 に設定
    dt_stale_sa = (now - timedelta(days=4)).isoformat()
    item_sa = store.add_item("SA Stale", phase=1, difficulty="A")
    item_sa["last_activity"] = dt_stale_sa
    
    # 2. 正常系: C難易度で7日以上経過 (stale_days_bc = 7)
    # last_activity を 8日前 に設定
    dt_stale_bc = (now - timedelta(days=8)).isoformat()
    item_bc = store.add_item("BC Stale", phase=1, difficulty="C")
    item_bc["last_activity"] = dt_stale_bc
    
    # 3. 除外系: 滞留しているが dispatched ステータス
    item_disp = store.add_item("SA Disp", phase=1, difficulty="A")
    item_disp["last_activity"] = dt_stale_sa
    item_disp["status"] = "dispatched"
    
    # 4. 除外系: 経過時間が閾値未満
    dt_fresh = (now - timedelta(days=1)).isoformat()
    item_fresh = store.add_item("Fresh", phase=1, difficulty="A")
    item_fresh["last_activity"] = dt_fresh
    
    # 5. 例外系: 日時情報が破損している場合
    item_corrupt = store.add_item("Corrupt Date", phase=1, difficulty="A")
    item_corrupt["last_activity"] = "corrupt-date"
    # item_corrupt に created_at がフォールバックされるため、created_at も破損させる
    item_corrupt["created_at"] = "corrupt-date"
    
    store._save()
    
    stale = store.get_stale_items()
    # SA Stale と BC Stale の2件が検知されるべき
    assert len(stale) == 2
    stale_ids = {i["id"] for i in stale}
    assert "DS-001" in stale_ids  # SA Stale
    assert "DS-002" in stale_ids  # BC Stale


def test_get_stock_health(tmp_path):
    """ヘルスステータス取得の検証"""
    store = DesignStockStore(path=str(tmp_path / "test.json"))
    
    # config 値の設定
    store._data["config"]["target_stock_count"] = 5
    
    store.add_item("Item 1", phase=27, difficulty="S")
    store.add_item("Item 2", phase=27, difficulty="A")
    store.add_item("Item 3", phase=28, difficulty="B")
    
    # 投入済み（dispatched）はアクティブカウントから除外されるべき
    item_disp = store.add_item("Item 4", phase=29, difficulty="C")
    store.update_status(item_disp["id"], "dispatched")
    
    health = store.get_stock_health()
    assert health["total_active"] == 3
    assert health["target"] == 5
    assert health["shortage"] == 2
    assert health["by_difficulty"] == {"S": 1, "A": 1, "B": 1, "C": 0}
    assert health["by_status"] == {"pending": 3}
    assert health["phases_covered"] == [27, 28]


def test_get_dashboard_summary_empty(tmp_path):
    """ストックが空の場合のダッシュボードテキスト検証"""
    store = DesignStockStore(path=str(tmp_path / "test.json"))
    summary = store.get_dashboard_summary()
    assert "設計ストックが空です" in summary


def test_get_dashboard_summary_with_items_and_stale(tmp_path):
    """アイテムおよび滞留がある場合のダッシュボード出力検証"""
    store = DesignStockStore(path=str(tmp_path / "test.json"))
    store._data["config"]["target_stock_count"] = 5
    
    # 滞留アイテムを意図的に作成
    now = datetime.now(timezone.utc)
    dt_stale = (now - timedelta(days=5)).isoformat()
    
    item1 = store.add_item("Stale S Task", phase=27, difficulty="S", description="Need discussion on Council.")
    item1["last_activity"] = dt_stale
    item1["created_at"] = dt_stale
    
    item2 = store.add_item("Normal B Task", phase=28, difficulty="B")
    
    # 経過日数計算が None になるケースを検証し、241行目をカバーする
    item3 = store.add_item("No Age Task", phase=29, difficulty="C")
    item3["created_at"] = ""
    
    store._save()
    
    summary = store.get_dashboard_summary()
    
    # 各種キーワードがサマリーに含まれることを確認
    assert "設計ストック" in summary
    assert "🔴 最高難度" in summary
    assert "Stale S Task" in summary
    assert "Normal B Task" in summary
    assert "滞留設計 & 解消スケジュール" in summary
    assert "ストック不足" in summary  # 2個のため目標5個に対して不足
    
    # 高難度タスクが存在するため、「高難度タスクなし」警告は出ないはず
    assert "高難度タスクなし" not in summary


def test_get_dashboard_summary_warnings(tmp_path):
    """「高難度タスクなし」などの警告を含むダッシュボード出力の検証"""
    store = DesignStockStore(path=str(tmp_path / "test.json"))
    store._data["config"]["target_stock_count"] = 1  # 目標を1に設定してストック不足警告を防ぐ
    
    # 低難度タスクのみ追加（高難度S/Aなし）
    store.add_item("Low Difficulty Task", phase=30, difficulty="C")
    
    summary = store.get_dashboard_summary()
    assert "高難度タスクなし" in summary
    assert "ストック不足" not in summary


def test_get_dashboard_summary_multiple_stale_scheduling(tmp_path):
    """多くの滞留アイテムがある場合に解消スケジュールが曜日名に正しくマッピングされることの検証"""
    store = DesignStockStore(path=str(tmp_path / "test.json"))
    
    # 6個の滞留タスクを追加（スケジュール表示件数は最大5個なのでスライスの挙動も検証できる）
    now = datetime.now(timezone.utc)
    dt_stale = (now - timedelta(days=10)).isoformat()
    
    for i in range(6):
        item = store.add_item(f"Stale Task {i}", phase=30, difficulty="C", description=f"Desc {i}")
        item["last_activity"] = dt_stale
        item["created_at"] = dt_stale
        
    store._save()
    
    summary = store.get_dashboard_summary()
    
    # 曜日指定が正しく機能しているか確認
    # 曜日名（月曜、火曜、水曜、木曜、金曜）のいずれかが含まれること
    assert any(day in summary for day in ["月曜", "火曜", "水曜", "木曜", "金曜"])
    assert "滞留設計 & 解消スケジュール" in summary
