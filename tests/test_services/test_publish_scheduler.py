import pytest
from datetime import datetime, timedelta
from unittest.mock import patch
from pathlib import Path
import json

from backend.services.publish_scheduler import publish_scheduler


@pytest.fixture
def clean_scheduler(tmp_path):
    """SCHEDULE_FILEをテスト用の一時ファイルパスにパッチし、クリアした状態のpublish_schedulerを返します。"""
    temp_file = tmp_path / "publish_schedule_test.json"
    with patch("backend.services.publish_scheduler.SCHEDULE_FILE", temp_file):
        if temp_file.exists():
            temp_file.unlink()
        yield publish_scheduler


def test_load_default(clean_scheduler):
    """ファイルが存在しない場合にデフォルトの設定がロードされることをテスト"""
    data = clean_scheduler._load()
    assert "schedule" in data
    assert data["schedule"] == []
    assert data["settings"]["target_per_week"] == 2
    assert data["settings"]["preferred_days"] == ["水", "土"]


def test_add_entry(clean_scheduler):
    """投稿予定の追加が正しく行われ、ファイルに保存されることをテスト"""
    entry = clean_scheduler.add_entry(title="テスト動画", planned_date="2026-06-01", status="draft")
    assert entry["title"] == "テスト動画"
    assert entry["planned_date"] == "2026-06-01"
    assert entry["status"] == "draft"
    assert entry["id"].startswith("pub_")
    assert "created_at" in entry

    # 保存されたデータをロードして確認
    data = clean_scheduler._load()
    assert len(data["schedule"]) == 1
    assert data["schedule"][0]["title"] == "テスト動画"
    assert data["schedule"][0]["id"] == entry["id"]


def test_get_schedule(clean_scheduler):
    """今後の予定のみの取得、全件取得、および予定が日付順にソートされることをテスト"""
    today = datetime.now()
    past_date = (today - timedelta(days=2)).strftime("%Y-%m-%d")
    future_date_1 = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    future_date_2 = (today + timedelta(days=3)).strftime("%Y-%m-%d")

    clean_scheduler.add_entry("過去の予定", past_date)
    clean_scheduler.add_entry("未来の予定2", future_date_2)
    clean_scheduler.add_entry("未来の予定1", future_date_1)

    # upcoming_only=True（デフォルト）: 未来の予定のみ、かつ日付順にソート
    schedule_upcoming = clean_scheduler.get_schedule(upcoming_only=True)
    assert len(schedule_upcoming) == 2
    assert schedule_upcoming[0]["title"] == "未来の予定1"
    assert schedule_upcoming[1]["title"] == "未来の予定2"

    # upcoming_only=False: 過去も含む全予定、かつ日付順にソート
    schedule_all = clean_scheduler.get_schedule(upcoming_only=False)
    assert len(schedule_all) == 3
    assert schedule_all[0]["title"] == "過去の予定"
    assert schedule_all[1]["title"] == "未来の予定1"
    assert schedule_all[2]["title"] == "未来の予定2"


def test_get_next_deadline(clean_scheduler):
    """次回投稿期限までの日数と緊急度の判定をテスト"""
    # 1. 予定が一切ない場合
    res = clean_scheduler.get_next_deadline()
    assert not res["has_deadline"]
    assert "予定がありません" in res["message"]

    # 2. 今日が期限の場合 (days_left = 0)
    today_str = datetime.now().strftime("%Y-%m-%d")
    clean_scheduler.add_entry("今日の動画", today_str)
    res = clean_scheduler.get_next_deadline()
    assert res["has_deadline"]
    assert res["days_left"] == 0
    assert res["urgency"] == "🔴 今日！"
    assert res["next_title"] == "今日の動画"

    # 3. 期限があと2日の場合 (1 <= days_left <= 3)
    # データをクリア
    clean_scheduler._save({"schedule": [], "settings": {"target_per_week": 2, "preferred_days": ["水", "土"]}})
    two_days_later = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
    clean_scheduler.add_entry("2日後の動画", two_days_later)
    res = clean_scheduler.get_next_deadline()
    assert res["has_deadline"]
    assert res["days_left"] == 2
    assert res["urgency"] == "🟡 あと2日"

    # 4. 期限があと5日の場合 (days_left > 3)
    clean_scheduler._save({"schedule": [], "settings": {"target_per_week": 2, "preferred_days": ["水", "土"]}})
    five_days_later = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
    clean_scheduler.add_entry("5日後の動画", five_days_later)
    res = clean_scheduler.get_next_deadline()
    assert res["has_deadline"]
    assert res["days_left"] == 5
    assert res["urgency"] == "🟢 あと5日"

    # 5. 日付が過去の場合 (days_left < 0) で max(days_left, 0) が機能することの検証
    past_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    # 文字列比較 planned_date >= today をバイパスするため get_schedule をモック
    with patch.object(
        clean_scheduler,
        "get_schedule",
        return_value=[{"title": "過去の予定", "planned_date": past_str, "status": "draft"}],
    ):
        res = clean_scheduler.get_next_deadline()
        assert res["has_deadline"]
        assert res["days_left"] == 0
        assert res["urgency"] == "🔴 今日！"


def test_analyze_pace(clean_scheduler):
    """投稿ペースの分析ロジックをテスト"""
    # 1. 公開済み動画が2本未満の場合
    res = clean_scheduler.analyze_pace()
    assert not res["enough_data"]
    assert "分析には2本以上の公開済み動画が必要です" in res["message"]

    # 2. 目標ペース達成中の場合 (target_per_week = 2 -> 目標間隔 3.5日, 平均間隔 3日)
    today = datetime.now()
    three_days_ago = (today - timedelta(days=3)).strftime("%Y-%m-%d")
    today_str = today.strftime("%Y-%m-%d")

    data = {
        "schedule": [
            {"id": "pub_1", "title": "動画1", "planned_date": three_days_ago, "status": "published"},
            {"id": "pub_2", "title": "動画2", "planned_date": today_str, "status": "published"},
        ],
        "settings": {"target_per_week": 2, "preferred_days": ["水", "土"]},
    }
    clean_scheduler._save(data)

    res = clean_scheduler.analyze_pace()
    assert res["enough_data"]
    assert res["total_published"] == 2
    assert res["avg_interval_days"] == 3.0
    assert res["target_interval_days"] == 3.5
    assert res["on_track"]
    assert "目標ペース達成中" in res["recommendation"]

    # 3. 目標ペース低下の場合 (平均間隔 5日 > 3.5 * 1.2 = 4.2日)
    five_days_ago = (today - timedelta(days=5)).strftime("%Y-%m-%d")
    data["schedule"][0]["planned_date"] = five_days_ago
    clean_scheduler._save(data)

    res = clean_scheduler.analyze_pace()
    assert not res["on_track"]
    assert "投稿ペース低下" in res["recommendation"]


def test_update_status(clean_scheduler):
    """投稿ステータスの更新ロジックをテスト"""
    entry = clean_scheduler.add_entry("ステータステスト動画", "2026-06-01")
    entry_id = entry["id"]

    # 1. 存在しないIDの更新 -> False
    assert not clean_scheduler.update_status("invalid_id", "published")

    # 2. 存在するIDの更新 (published以外) -> True、published_at なし
    assert clean_scheduler.update_status(entry_id, "in_progress")
    data = clean_scheduler._load()
    updated = next(e for e in data["schedule"] if e["id"] == entry_id)
    assert updated["status"] == "in_progress"
    assert "published_at" not in updated

    # 3. publishedへの更新 -> True、published_at あり
    assert clean_scheduler.update_status(entry_id, "published")
    data = clean_scheduler._load()
    updated = next(e for e in data["schedule"] if e["id"] == entry_id)
    assert updated["status"] == "published"
    assert "published_at" in updated


def test_settings_and_update(clean_scheduler):
    """設定取得および更新における各種境界値とバリデーションをテスト"""
    # 1. デフォルト設定の取得
    settings = clean_scheduler.get_settings()
    assert settings["target_per_week"] == 2
    assert settings["preferred_days"] == ["水", "土"]
    assert settings["reminder_hours_before"] == 24
    assert settings["auto_schedule"] is False

    # 2. 有効な値での更新
    updated = clean_scheduler.update_settings(
        target_per_week=3, preferred_days=["月", "水", "金"], reminder_hours_before=12, auto_schedule=True
    )
    assert updated["target_per_week"] == 3
    assert updated["preferred_days"] == ["月", "水", "金"]
    assert updated["reminder_hours_before"] == 12
    assert updated["auto_schedule"] is True

    # 3. 最大値を超える無効な値の丸め処理と曜日フィルタリング
    updated_invalid_max = clean_scheduler.update_settings(
        target_per_week=10, preferred_days=["月", "火", "Invalid曜日"], reminder_hours_before=200
    )
    assert updated_invalid_max["target_per_week"] == 7  # 7に丸め
    assert updated_invalid_max["preferred_days"] == ["月", "火"]  # 無効な曜日は除外
    assert updated_invalid_max["reminder_hours_before"] == 168  # 168に丸め

    # 4. 最小値を下回る無効な値の丸め処理
    updated_invalid_min = clean_scheduler.update_settings(target_per_week=0, reminder_hours_before=0)
    assert updated_invalid_min["target_per_week"] == 1  # 1に丸め
    assert updated_invalid_min["reminder_hours_before"] == 1  # 1に丸め


def test_corrupt_data_handling(clean_scheduler, tmp_path):
    """ファイルが空、または壊れたJSON、または期待しないデータ型（リストやnull等）の場合のロバストネスをテスト"""
    temp_file = tmp_path / "publish_schedule_corrupt.json"
    with patch("backend.services.publish_scheduler.SCHEDULE_FILE", temp_file):
        # 1. JSONとして不正な文字列（構文エラー）
        temp_file.write_text("invalid json format", encoding="utf-8")
        data = clean_scheduler._load()
        assert isinstance(data, dict)
        assert data["schedule"] == []
        
        # 2. JSONとしては有効だが、辞書ではない型（例: リリスト型）
        temp_file.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        data = clean_scheduler._load()
        assert isinstance(data, dict)
        assert data["schedule"] == []

        # 3. JSONとしては有効だが、null（None）
        temp_file.write_text(json.dumps(None), encoding="utf-8")
        data = clean_scheduler._load()
        assert isinstance(data, dict)
        assert data["schedule"] == []

        # 4. 部分的にキーが欠落している（settingsが欠損）
        temp_file.write_text(json.dumps({"schedule": []}), encoding="utf-8")
        settings = clean_scheduler.get_settings()
        assert settings["target_per_week"] == 2  # デフォルト値にフォールバックされること


def test_add_entry_race_condition(clean_scheduler):
    """並行して add_entry が呼び出された際、データ競合によりデータが消失しないことをテスト"""
    import threading
    
    num_threads = 5
    entries_per_thread = 10
    
    def worker(thread_idx):
        for i in range(entries_per_thread):
            title = f"Thread {thread_idx} Video {i}"
            clean_scheduler.add_entry(title=title, planned_date="2026-06-01", status="draft")
            
    threads = []
    for idx in range(num_threads):
        t = threading.Thread(target=worker, args=(idx,))
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
    # 全てのエントリーが正しく保存されているか確認
    data = clean_scheduler._load()
    assert len(data["schedule"]) == num_threads * entries_per_thread
    
    # 全てのタイトルが含まれているか確認
    saved_titles = {e["title"] for e in data["schedule"]}
    for idx in range(num_threads):
        for i in range(entries_per_thread):
            expected_title = f"Thread {idx} Video {i}"
            assert expected_title in saved_titles


def test_add_entry_invalid_date_validation(clean_scheduler):
    """不正な planned_date による ValueError 送出の追加検証"""
    with pytest.raises(ValueError, match="Invalid planned_date format"):
        clean_scheduler.add_entry(title="不正動画1", planned_date="2026/06/01")
        
    with pytest.raises(ValueError, match="Invalid planned_date format"):
        clean_scheduler.add_entry(title="不正動画2", planned_date="invalid-date")

    with pytest.raises(ValueError, match="Invalid planned_date format"):
        clean_scheduler.add_entry(title="不正動画3", planned_date="")


def test_save_invalid_type(clean_scheduler):
    """_saveに辞書以外を渡した際のTypeError送出をテスト"""
    with pytest.raises(TypeError, match="Data to save must be a dictionary"):
        clean_scheduler._save("string data")


def test_add_entry_validation_errors(clean_scheduler):
    """add_entryでの各種バリデーションエラーをテスト"""
    # 1. タイトルが空
    with pytest.raises(ValueError, match="Title cannot be empty"):
        clean_scheduler.add_entry(title="", planned_date="2026-06-01")
    # 2. タイトルが空白のみ
    with pytest.raises(ValueError, match="Title cannot be empty"):
        clean_scheduler.add_entry(title="   ", planned_date="2026-06-01")
    # 3. 不正なステータス
    with pytest.raises(ValueError, match="Invalid status"):
        clean_scheduler.add_entry(title="テスト", planned_date="2026-06-01", status="invalid_status")


def test_get_next_deadline_with_corrupt_date(clean_scheduler):
    """予定一覧に不正な日付形式が含まれる場合のエラーハンドリングをテスト"""
    # 1件の正常エントリーと、1件の異常エントリーを登録
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # 異常エントリーを追加（add_entryはバリデーションされるため、_saveで直接注入）
    data = {
        "schedule": [
            {"id": "pub_corrupt", "title": "日付壊れた動画", "planned_date": "invalid-date", "status": "draft"},
            {"id": "pub_valid", "title": "正常な動画", "planned_date": today_str, "status": "draft"}
        ],
        "settings": {"target_per_week": 2, "preferred_days": ["水", "土"]}
    }
    clean_scheduler._save(data)
    
    # 期限の取得が正常に行われ、正常な動画が期限として返ってくること
    res = clean_scheduler.get_next_deadline()
    assert res["has_deadline"]
    assert res["next_title"] == "正常な動画"
    assert res["days_left"] == 0


def test_analyze_pace_with_corrupt_date(clean_scheduler):
    """公開済み動画に不正な日付形式が含まれる場合のエラーハンドリングをテスト"""
    # 正常な動画2件と、異常な動画1件
    today = datetime.now()
    three_days_ago = (today - timedelta(days=3)).strftime("%Y-%m-%d")
    today_str = today.strftime("%Y-%m-%d")
    
    data = {
        "schedule": [
            {"id": "pub_1", "title": "動画1", "planned_date": three_days_ago, "status": "published"},
            {"id": "pub_2", "title": "動画2", "planned_date": today_str, "status": "published"},
            {"id": "pub_corrupt", "title": "日付壊れた動画", "planned_date": "invalid-date", "status": "published"}
        ],
        "settings": {"target_per_week": 2, "preferred_days": ["水", "土"]}
    }
    clean_scheduler._save(data)
    
    # 分析が正常に行われること（壊れたものは除外される）
    res = clean_scheduler.analyze_pace()
    assert res["enough_data"]
    assert res["total_published"] == 3
    assert res["avg_interval_days"] == 3.0


def test_update_status_validation_errors(clean_scheduler):
    """update_statusでのステータスバリデーションエラーをテスト"""
    with pytest.raises(ValueError, match="Invalid status"):
        clean_scheduler.update_status(entry_id="pub_123", status="invalid_status")


def test_extra_edge_cases_for_coverage(clean_scheduler, tmp_path):
    """未カバーの例外分岐や補正処理を網羅的にテスト"""
    temp_file = tmp_path / "publish_schedule_extra.json"
    with patch("backend.services.publish_scheduler.SCHEDULE_FILE", temp_file):
        # 1. _load で辞書ではない場合（モックを使用）
        with patch.object(clean_scheduler._store, "load", return_value=None):
            data = clean_scheduler._load()
            assert data["schedule"] == []
            assert isinstance(data["settings"], dict)

        # 1-2. _load で辞書だがキーがない
        temp_file.write_text(json.dumps({"settings": None}), encoding="utf-8")
        data = clean_scheduler._load()
        assert data["schedule"] == []
        assert isinstance(data["settings"], dict)
        
        # 2. add_entry で元のファイルが非辞書型（例: null）、および schedule がリストでない場合
        # SafeJsonStore.load() / load_unsafe() が dict を返すため、モックで非dictを渡す
        original_update = clean_scheduler._store.update
        def mock_update_non_dict(updater_fn):
            return original_update(lambda data: updater_fn(None))
            
        with patch.object(clean_scheduler._store, "update", side_effect=mock_update_non_dict):
            entry = clean_scheduler.add_entry(title="新規動画1", planned_date="2026-06-01")
            assert entry["title"] == "新規動画1"

        temp_file.write_text(json.dumps({"schedule": "invalid_type_not_list"}), encoding="utf-8")
        entry = clean_scheduler.add_entry(title="新規動画2", planned_date="2026-06-02")
        assert entry["title"] == "新規動画2"
        
        # 3. get_next_deadline で不正な日付のエントリーしか存在しない場合
        temp_file.write_text(json.dumps({
            "schedule": [{"id": "pub_bad", "title": "悪い日付", "planned_date": "bad-date"}],
            "settings": {}
        }), encoding="utf-8")
        res = clean_scheduler.get_next_deadline()
        assert not res["has_deadline"]
        
        # 4. analyze_pace で不正な日付除外後に有効な公開済みが2件未満になる場合
        temp_file.write_text(json.dumps({
            "schedule": [
                {"id": "pub_1", "title": "正常", "planned_date": "2026-06-01", "status": "published"},
                {"id": "pub_2", "title": "異常", "planned_date": "bad-date", "status": "published"}
            ]
        }), encoding="utf-8")
        res = clean_scheduler.analyze_pace()
        assert not res["enough_data"]
        
        # 5. update_status で元のファイルが非辞書型（early return の検証）
        with patch.object(clean_scheduler._store, "update", side_effect=mock_update_non_dict):
            assert not clean_scheduler.update_status(entry_id="any", status="draft")
        
        # 6. update_settings で元のファイルが非辞書型
        with patch.object(clean_scheduler._store, "update", side_effect=mock_update_non_dict):
            settings = clean_scheduler.update_settings(target_per_week=3)
            assert settings["target_per_week"] == 3
        
        # 7. update_settings で settings が非辞書型
        temp_file.write_text(json.dumps({"settings": None}), encoding="utf-8")
        settings = clean_scheduler.update_settings(target_per_week=4)
        assert settings["target_per_week"] == 4



