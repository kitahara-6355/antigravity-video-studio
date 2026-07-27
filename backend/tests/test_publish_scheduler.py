import pytest
import json
from pathlib import Path
import datetime as real_datetime
from unittest.mock import patch, MagicMock

from backend.services.publish_scheduler import PublishScheduler


@pytest.fixture
def temp_schedule_file(tmp_path):
    """SCHEDULE_FILEをテスト用の一時ファイルパスに差し替えるフィクスチャ"""
    temp_file = tmp_path / "publish_schedule.json"
    with patch("backend.services.publish_scheduler.SCHEDULE_FILE", temp_file):
        yield temp_file


@pytest.fixture
def frozen_time():
    """datetime.now()を固定するフィクスチャ"""
    fixed_now = real_datetime.datetime(2026, 5, 25, 0, 0, 0)
    
    mock_dt = MagicMock()
    mock_dt.now.return_value = fixed_now
    mock_dt.strptime.side_effect = lambda *args, **kwargs: real_datetime.datetime.strptime(*args, **kwargs)
    
    with patch("backend.services.publish_scheduler.datetime", mock_dt):
        yield fixed_now


def test_load_default(temp_schedule_file):
    """ファイルが存在しない場合にデフォルト値がロードされることをテスト"""
    scheduler = PublishScheduler()
    data = scheduler._load()
    assert data["schedule"] == []
    assert data["settings"]["target_per_week"] == 2
    assert data["settings"]["preferred_days"] == ["水", "土"]


def test_load_existing(temp_schedule_file):
    """ファイルが存在する場合に正しくロードされることをテスト"""
    scheduler = PublishScheduler()
    test_data = {
        "schedule": [{"id": "pub_1", "title": "Test Video", "planned_date": "2026-05-25", "status": "draft"}],
        "settings": {"target_per_week": 3, "preferred_days": ["月"]}
    }
    temp_schedule_file.write_text(json.dumps(test_data, ensure_ascii=False), encoding="utf-8")
    
    data = scheduler._load()
    assert data["schedule"][0]["title"] == "Test Video"
    assert data["settings"]["target_per_week"] == 3


def test_save(temp_schedule_file):
    """_saveが正常にデータを書き込めることをテスト"""
    scheduler = PublishScheduler()
    test_data = {"test": "data"}
    scheduler._save(test_data)
    
    assert temp_schedule_file.exists()
    loaded = json.loads(temp_schedule_file.read_text(encoding="utf-8"))
    assert loaded == test_data


def test_add_entry(temp_schedule_file, frozen_time):
    """add_entryで予定が正しく追加されることをテスト"""
    scheduler = PublishScheduler()
    entry = scheduler.add_entry("Test Video", "2026-06-01", "draft")
    
    assert entry["title"] == "Test Video"
    assert entry["planned_date"] == "2026-06-01"
    assert entry["status"] == "draft"
    assert entry["id"].startswith("pub_20260525")
    assert "created_at" in entry
    
    # ロードして保存されているか確認
    data = scheduler._load()
    assert len(data["schedule"]) == 1
    assert data["schedule"][0]["title"] == "Test Video"


def test_get_schedule(temp_schedule_file, frozen_time):
    """get_scheduleで予定がフィルタリング・ソートされることをテスト"""
    scheduler = PublishScheduler()
    
    # 過去、今日、未来の予定を追加
    # frozen_time は 2026-05-25
    scheduler.add_entry("Past Video", "2026-05-20")
    scheduler.add_entry("Today Video", "2026-05-25")
    scheduler.add_entry("Future Video", "2026-05-30")
    
    # upcoming_only=True（今日以降のみ、昇順）
    upcoming = scheduler.get_schedule(upcoming_only=True)
    assert len(upcoming) == 2
    assert upcoming[0]["title"] == "Today Video"
    assert upcoming[1]["title"] == "Future Video"
    
    # upcoming_only=False（すべて、昇順）
    all_schedule = scheduler.get_schedule(upcoming_only=False)
    assert len(all_schedule) == 3
    assert all_schedule[0]["title"] == "Past Video"
    assert all_schedule[1]["title"] == "Today Video"
    assert all_schedule[2]["title"] == "Future Video"


def test_get_next_deadline_no_upcoming(temp_schedule_file):
    """次回期限予定がない場合の挙動をテスト"""
    scheduler = PublishScheduler()
    result = scheduler.get_next_deadline()
    assert result["has_deadline"] is False
    assert "予定がありません" in result["message"]


def test_get_next_deadline_urgency_cases(temp_schedule_file, frozen_time):
    """次回期限の緊急度表示（赤・黄・緑）をテスト"""
    scheduler = PublishScheduler()
    
    # 🔴 今日！のケース (残り日数 <= 0)
    scheduler.add_entry("Today Video", "2026-05-25")
    result_today = scheduler.get_next_deadline()
    assert result_today["has_deadline"] is True
    assert result_today["days_left"] == 0
    assert "🔴 今日！" in result_today["urgency"]
    
    # 一旦クリア
    scheduler._save({"schedule": [], "settings": {}})
    
    # 🟡 あと3日以内のケース (1 <= 残り日数 <= 3)
    scheduler.add_entry("Yellow Video", "2026-05-28") # 28 - 25 = 3
    result_yellow = scheduler.get_next_deadline()
    assert result_yellow["days_left"] == 3
    assert "🟡 あと3日" in result_yellow["urgency"]
    
    # 一旦クリア
    scheduler._save({"schedule": [], "settings": {}})
    
    # 🟢 あと4日以上のケース (残り日数 > 3)
    scheduler.add_entry("Green Video", "2026-05-30") # 30 - 25 = 5
    result_green = scheduler.get_next_deadline()
    assert result_green["days_left"] == 5
    assert "🟢 あと5日" in result_green["urgency"]


def test_analyze_pace_insufficient_data(temp_schedule_file):
    """公開済みの動画が2本未満の場合に分析が行われないことをテスト"""
    scheduler = PublishScheduler()
    # 予定なし
    result = scheduler.analyze_pace()
    assert result["enough_data"] is False
    assert "分析には2本以上の公開済み動画が必要です" in result["message"]
    
    # 1本だけ公開済み
    scheduler.add_entry("Video 1", "2026-05-20", "published")
    result = scheduler.analyze_pace()
    assert result["enough_data"] is False


def test_analyze_pace_on_track(temp_schedule_file):
    """投稿ペースが目標内（on_track=True）の場合をテスト"""
    scheduler = PublishScheduler()
    # デフォルト設定 target_per_week = 2 => 目標間隔 = 3.5日
    # 投稿間隔: 3日間 (2026-05-20 から 2026-05-23)
    # 平均間隔 3.0日 <= 3.5日 * 1.2 (= 4.2日) => on_track=True
    scheduler.add_entry("Video 1", "2026-05-20", "published")
    scheduler.add_entry("Video 2", "2026-05-23", "published")
    
    result = scheduler.analyze_pace()
    assert result["enough_data"] is True
    assert result["on_track"] is True
    assert result["avg_interval_days"] == 3.0
    assert "目標ペース達成中" in result["recommendation"]


def test_analyze_pace_off_track(temp_schedule_file):
    """投稿ペースが目標より遅い（on_track=False）の場合をテスト"""
    scheduler = PublishScheduler()
    # デフォルト設定 target_per_week = 2 => 目標間隔 = 3.5日
    # 投稿間隔: 5日間 (2026-05-20 から 2026-05-25)
    # 平均間隔 5.0日 > 3.5日 * 1.2 (= 4.2日) => on_track=False
    scheduler.add_entry("Video 1", "2026-05-20", "published")
    scheduler.add_entry("Video 2", "2026-05-25", "published")
    
    result = scheduler.analyze_pace()
    assert result["enough_data"] is True
    assert result["on_track"] is False
    assert "投稿ペース低下" in result["recommendation"]


def test_update_status_not_found(temp_schedule_file):
    """存在しないエントリーのステータス更新がFalseを返すことをテスト"""
    scheduler = PublishScheduler()
    result = scheduler.update_status("non_existent_id", "published")
    assert result is False


def test_update_status_success(temp_schedule_file, frozen_time):
    """ステータスの更新が正常に行われ、publishedの場合に日付が設定されることをテスト"""
    scheduler = PublishScheduler()
    entry = scheduler.add_entry("Test Video", "2026-05-30", "draft")
    entry_id = entry["id"]
    
    # draft -> in_progress
    result = scheduler.update_status(entry_id, "in_progress")
    assert result is True
    
    data = scheduler._load()
    updated_entry = data["schedule"][0]
    assert updated_entry["status"] == "in_progress"
    assert "published_at" not in updated_entry
    
    # in_progress -> published
    result = scheduler.update_status(entry_id, "published")
    assert result is True
    
    data = scheduler._load()
    updated_entry = data["schedule"][0]
    assert updated_entry["status"] == "published"
    assert updated_entry["published_at"] == frozen_time.isoformat()


def test_get_settings_default(temp_schedule_file):
    """設定が未保存の場合にデフォルト値が取得できることをテスト"""
    scheduler = PublishScheduler()
    settings = scheduler.get_settings()
    assert settings["target_per_week"] == 2
    assert settings["preferred_days"] == ["水", "土"]
    assert settings["reminder_hours_before"] == 24
    assert settings["auto_schedule"] is False


def test_update_settings_all_fields(temp_schedule_file):
    """update_settingsで設定が正常に更新されることをテスト"""
    scheduler = PublishScheduler()
    new_settings = scheduler.update_settings(
        target_per_week=3,
        preferred_days=["月", "木"],
        reminder_hours_before=12,
        auto_schedule=True
    )
    
    assert new_settings["target_per_week"] == 3
    assert new_settings["preferred_days"] == ["月", "木"]
    assert new_settings["reminder_hours_before"] == 12
    assert new_settings["auto_schedule"] is True
    
    # ロードして確認
    settings = scheduler.get_settings()
    assert settings == new_settings


def test_update_settings_validation_limits(temp_schedule_file):
    """update_settingsのバリデーション境界値（範囲外の自動補正）をテスト"""
    scheduler = PublishScheduler()
    
    # 範囲下限未満
    settings = scheduler.update_settings(target_per_week=0, reminder_hours_before=0)
    assert settings["target_per_week"] == 1
    assert settings["reminder_hours_before"] == 1
    
    # 範囲上限超え
    settings = scheduler.update_settings(target_per_week=10, reminder_hours_before=200)
    assert settings["target_per_week"] == 7
    assert settings["reminder_hours_before"] == 168


def test_update_settings_invalid_days(temp_schedule_file):
    """update_settingsで無効な曜日が除外されることをテスト"""
    scheduler = PublishScheduler()
    settings = scheduler.update_settings(preferred_days=["月", "不正な曜日", "金"])
    assert settings["preferred_days"] == ["月", "金"]


def test_update_settings_none_values(temp_schedule_file):
    """update_settingsで引数がNoneの場合に設定が維持されることをテスト"""
    scheduler = PublishScheduler()
    # 初期値設定
    scheduler.update_settings(
        target_per_week=4,
        preferred_days=["金"],
        reminder_hours_before=48,
        auto_schedule=True
    )
    
    # Noneで更新呼び出し
    settings = scheduler.update_settings(
        target_per_week=None,
        preferred_days=None,
        reminder_hours_before=None,
        auto_schedule=None
    )
    
    assert settings["target_per_week"] == 4
    assert settings["preferred_days"] == ["金"]
    assert settings["reminder_hours_before"] == 48
    assert settings["auto_schedule"] is True


def test_get_next_deadline_non_midnight_urgency(temp_schedule_file):
    """datetime.now() が正午などの非深夜帯の時刻の場合でも、翌日の期限が正しく残り1日と判定されることをテスト"""
    scheduler = PublishScheduler()
    
    # 2026-05-25 12:00:00 に固定
    fixed_now = real_datetime.datetime(2026, 5, 25, 12, 0, 0)
    
    mock_dt = MagicMock()
    mock_dt.now.return_value = fixed_now
    mock_dt.strptime.side_effect = lambda *args, **kwargs: real_datetime.datetime.strptime(*args, **kwargs)
    
    with patch("backend.services.publish_scheduler.datetime", mock_dt):
        # 翌日（5月26日）の予定を追加
        scheduler.add_entry("Tomorrow Video", "2026-05-26")
        
        result = scheduler.get_next_deadline()
        
        assert result["has_deadline"] is True
        assert result["days_left"] == 1  # 修正前は 0 になるバグがある
        assert "🟡 あと1日" in result["urgency"]


def test_update_status_multiple_entries(temp_schedule_file, frozen_time):
    """複数エントリーが存在する状態で特定のIDを更新するケース、および存在しないIDを更新して不一致ループを抜けるケースをテスト"""
    import backend.services.publish_scheduler
    from datetime import timedelta
    scheduler = PublishScheduler()
    
    # 1つ目のエントリーを登録
    entry_a = scheduler.add_entry("Video A", "2026-05-30", "draft")
    
    # モックの現在時刻を進めてIDの重複を防ぐ
    backend.services.publish_scheduler.datetime.now.return_value = frozen_time + timedelta(seconds=1)
    
    # 2つ目のエントリーを登録
    entry_b = scheduler.add_entry("Video B", "2026-06-01", "draft")
    
    entry_a_id = entry_a["id"]
    entry_b_id = entry_b["id"]
    
    assert entry_a_id != entry_b_id
    
    # entry_b を更新 (1つ目のループで不一致になり、2つ目のループに進む分岐 113->112 を発生させる)
    result = scheduler.update_status(entry_b_id, "in_progress")
    assert result is True
    
    data = scheduler._load()
    assert data["schedule"][0]["status"] == "draft"  # entry_a はそのまま
    assert data["schedule"][1]["status"] == "in_progress"  # entry_b が更新されている
    
    # 存在しない ID を更新 (すべてのループで不一致になり、ループを抜ける)
    result_none = scheduler.update_status("non_existent_id", "published")
    assert result_none is False


def test_load_corrupted_json(temp_schedule_file):
    """JSONファイルが破損している場合にデフォルトのデータが返されることをテスト"""
    scheduler = PublishScheduler()
    temp_schedule_file.write_text("{invalid json", encoding="utf-8")
    
    data = scheduler._load()
    assert data["schedule"] == []
    assert data["settings"]["target_per_week"] == 2


def test_add_entry_validation_errors(temp_schedule_file):
    """add_entryでの入力値バリデーションをテスト"""
    scheduler = PublishScheduler()
    
    # タイトルが空
    with pytest.raises(ValueError, match="Title cannot be empty"):
        scheduler.add_entry("", "2026-06-01")
        
    with pytest.raises(ValueError, match="Title cannot be empty"):
        scheduler.add_entry("   ", "2026-06-01")
        
    # 無効な日付フォーマット
    with pytest.raises(ValueError, match="Invalid planned_date format"):
        scheduler.add_entry("Title", "2026/06/01")
        
    with pytest.raises(ValueError, match="Invalid planned_date format"):
        scheduler.add_entry("Title", "invalid-date")
        
    # 無効なステータス
    with pytest.raises(ValueError, match="Invalid status"):
        scheduler.add_entry("Title", "2026-06-01", status="unknown_status")


def test_update_status_validation_error(temp_schedule_file):
    """update_statusでの入力値バリデーションをテスト"""
    scheduler = PublishScheduler()
    entry = scheduler.add_entry("Test Video", "2026-06-01")
    
    with pytest.raises(ValueError, match="Invalid status"):
        scheduler.update_status(entry["id"], "invalid_status")


def test_get_next_deadline_with_corrupted_entry(temp_schedule_file, frozen_time):
    """不正な日付フォーマットの予定が含まれていても、正常な予定から次回期限が正しく計算されることをテスト"""
    scheduler = PublishScheduler()
    
    # 2026-05-25 (frozen_time)
    # 不正な日付形式のエントリーを追加
    # add_entry自体はバリデーションされるので、_saveを直接使って不正な状態を作り出す
    data = {
        "schedule": [
            {"id": "pub_corrupted", "title": "Corrupted Video", "planned_date": "invalid-date", "status": "draft"},
            {"id": "pub_valid", "title": "Valid Video", "planned_date": "2026-05-28", "status": "draft"}
        ],
        "settings": {}
    }
    scheduler._save(data)
    
    result = scheduler.get_next_deadline()
    assert result["has_deadline"] is True
    assert result["next_title"] == "Valid Video"
    assert result["days_left"] == 3
    assert "🟡 あと3日" in result["urgency"]


def test_analyze_pace_with_corrupted_entry(temp_schedule_file):
    """不正な日付形式の公開済みエントリーが含まれていても、それを無視してペース分析が続行できることをテスト"""
    scheduler = PublishScheduler()
    
    data = {
        "schedule": [
            {"id": "pub_1", "title": "Video 1", "planned_date": "2026-05-20", "status": "published"},
            {"id": "pub_corrupted", "title": "Corrupted Video", "planned_date": "invalid-date", "status": "published"},
            {"id": "pub_2", "title": "Video 2", "planned_date": "2026-05-23", "status": "published"}
        ],
        "settings": {"target_per_week": 2}
    }
    scheduler._save(data)
    
    result = scheduler.analyze_pace()
    assert result["enough_data"] is True
    assert result["avg_interval_days"] == 3.0
    assert result["total_published"] == 3  # filterされて計算自体は2本で処理される


def test_save_os_error(temp_schedule_file):
    """_save実行時にOSErrorが発生した場合に適切に例外が再スローされることをテスト"""
    scheduler = PublishScheduler()
    
    # _store プロパティが返すモックをセットして save で OSError を投げさせる
    mock_store = MagicMock()
    mock_store.path = temp_schedule_file
    mock_store.save.side_effect = OSError("Disk full")
    scheduler._cached_store = mock_store
    
    with pytest.raises(OSError, match="Disk full"):
        scheduler._save({"test": "data"})


def test_extra_edge_cases_for_coverage(temp_schedule_file):
    """未カバーの例外分岐や補正処理を網羅的にテスト"""
    scheduler = PublishScheduler()
    
    # 1. _load で辞書ではない場合（モックを使用）
    with patch.object(scheduler._store, "load", return_value=None):
        data = scheduler._load()
        assert data["schedule"] == []
        assert isinstance(data["settings"], dict)

    # 1-2. _load で辞書だがキーがない
    temp_schedule_file.write_text(json.dumps({"settings": None}), encoding="utf-8")
    data = scheduler._load()
    assert data["schedule"] == []
    assert isinstance(data["settings"], dict)
    
    # 2. add_entry で元のファイルが非辞書型（例: null）、および schedule がリストでない場合
    original_update = scheduler._store.update
    def mock_update_non_dict(updater_fn):
        return original_update(lambda data: updater_fn(None))
        
    with patch.object(scheduler._store, "update", side_effect=mock_update_non_dict):
        entry = scheduler.add_entry(title="新規動画1", planned_date="2026-06-01")
        assert entry["title"] == "新規動画1"

    temp_schedule_file.write_text(json.dumps({"schedule": "invalid_type_not_list"}), encoding="utf-8")
    entry = scheduler.add_entry(title="新規動画2", planned_date="2026-06-02")
    assert entry["title"] == "新規動画2"
    
    # 3. get_next_deadline で不正な日付のエントリーしか存在しない場合
    temp_schedule_file.write_text(json.dumps({
        "schedule": [{"id": "pub_bad", "title": "悪い日付", "planned_date": "bad-date"}],
        "settings": {}
    }), encoding="utf-8")
    res = scheduler.get_next_deadline()
    assert not res["has_deadline"]

    # 4. analyze_pace で不正な日付除外後に有効な公開済みが2件未満になる場合
    temp_schedule_file.write_text(json.dumps({
        "schedule": [
            {"id": "pub_1", "title": "正常", "planned_date": "2026-06-01", "status": "published"},
            {"id": "pub_2", "title": "異常", "planned_date": "bad-date", "status": "published"}
        ]
    }), encoding="utf-8")
    res = scheduler.analyze_pace()
    assert not res["enough_data"]
    
    # 5. update_status で元のファイルが非辞書型（early return の検証）
    with patch.object(scheduler._store, "update", side_effect=mock_update_non_dict):
        assert not scheduler.update_status(entry_id="any", status="draft")
    
    # 6. update_settings で元のファイルが非辞書型
    with patch.object(scheduler._store, "update", side_effect=mock_update_non_dict):
        settings = scheduler.update_settings(target_per_week=3)
        assert settings["target_per_week"] == 3
    
    # 7. update_settings で settings が非辞書型
    temp_schedule_file.write_text(json.dumps({"settings": None}), encoding="utf-8")
    settings = scheduler.update_settings(target_per_week=4)
    assert settings["target_per_week"] == 4
    
    # 8. _save で辞書ではない場合に TypeError を投げること
    with pytest.raises(TypeError, match="Data to save must be a dictionary"):
        scheduler._save("not_a_dictionary")
    

    

    

    

