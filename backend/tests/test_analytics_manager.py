import pytest
from branding.analytics_manager import AnalyticsManager

def test_get_my_stats():
    manager = AnalyticsManager()
    stats = manager.get_my_stats()
    assert "subscribers" in stats
    assert "total_views" in stats
    assert "videos" in stats
    assert "last_updated" in stats

def test_scout_rivals_normal():
    manager = AnalyticsManager()
    my_stats = {
        "subscribers": 150,
        "total_views": 4500,
        "videos": 12
    }
    rivals = manager.scout_rivals(my_stats)
    assert "nemesis" in rivals
    assert "benchmark" in rivals

def test_scout_rivals_zero_subscribers():
    manager = AnalyticsManager()
    my_stats = {
        "subscribers": 0,
        "total_views": 0,
        "views": 0
    }
    try:
        rivals = manager.scout_rivals(my_stats)
        assert "nemesis" in rivals
        assert "benchmark" in rivals
    except ZeroDivisionError:
        pytest.fail("ZeroDivisionError occurred!")

def test_calculate_gap_normal():
    manager = AnalyticsManager()
    my_stats = {
        "subscribers": 150
    }
    rivals = {
        "nemesis": {"name": "TechStarter", "subs": 180, "views": 5000, "genre": "Tech"},
        "benchmark": None
    }
    quests = manager.calculate_gap(my_stats, rivals)
    assert len(quests) == 1
    assert quests[0]["type"] == "NEMESIS_BATTLE"
    assert quests[0]["gap"] == 30

def test_calculate_gap_none_rivals():
    manager = AnalyticsManager()
    my_stats = {
        "subscribers": 150
    }
    try:
        quests = manager.calculate_gap(my_stats, None)
        assert isinstance(quests, list)
    except AttributeError:
        pytest.fail("AttributeError occurred when rivals is None!")

def test_scout_rivals_invalid_stats():
    manager = AnalyticsManager()
    
    # Test with None
    rivals_none = manager.scout_rivals(None)
    # **印が増えたので完全一致をやめる**（R1.5-C4）。ライバルは `mock_rival_db` の
    # 固定値から選ぶだけなので、`GET /api/status` が実測に見えないよう名乗らせている
    assert rivals_none["nemesis"] is None and rivals_none["benchmark"] is None
    assert rivals_none["is_real"] is False
    
    # Test with list (invalid type)
    rivals_list = manager.scout_rivals([])
    assert rivals_list["nemesis"] is None and rivals_list["benchmark"] is None
    assert rivals_list["is_real"] is False  # R1.5-C4
    
    # Test with string (invalid type)
    rivals_str = manager.scout_rivals("not_a_dict")
    assert rivals_str["nemesis"] is None and rivals_str["benchmark"] is None
    assert rivals_str["is_real"] is False  # R1.5-C4

def test_sim_add_views():
    manager = AnalyticsManager()
    initial_views = manager.mock_my_stats["total_views"]
    initial_subs = manager.mock_my_stats["subscribers"]
    
    # Case 1: Add 500 views (should yield 5 subs)
    result = manager.sim_add_views(500)
    assert result["added_views"] == 500
    assert result["added_subs"] == 5
    assert manager.mock_my_stats["total_views"] == initial_views + 500
    assert manager.mock_my_stats["subscribers"] == initial_subs + 5
    
    # Case 2: Add 50 views (should yield 0 subs due to truncation)
    result2 = manager.sim_add_views(50)
    assert result2["added_views"] == 50
    assert result2["added_subs"] == 0
    assert manager.mock_my_stats["total_views"] == initial_views + 550
    assert manager.mock_my_stats["subscribers"] == initial_subs + 5


def test_scout_rivals_no_nemesis():
    manager = AnalyticsManager()
    # Subscribers is set high so that no rival is between 1.1x and 1.5x (subs: 500,000)
    my_stats = {
        "subscribers": 500000,
        "total_views": 1000000,
        "videos": 10
    }
    rivals = manager.scout_rivals(my_stats)
    assert rivals["nemesis"] is None

def test_scout_rivals_no_benchmark():
    manager = AnalyticsManager()
    # Subscribers is set high so that no rival is between 10x and 100x
    my_stats = {
        "subscribers": 500000,
        "total_views": 1000000,
        "videos": 10
    }
    rivals = manager.scout_rivals(my_stats)
    assert rivals["benchmark"] is None

def test_calculate_gap_no_nemesis():
    manager = AnalyticsManager()
    my_stats = {
        "subscribers": 150
    }
    rivals = {
        "nemesis": None,
        "benchmark": {"name": "TechMastery", "subs": 15000}
    }
    quests = manager.calculate_gap(my_stats, rivals)
    assert quests == []

def test_calculate_gap_invalid_nemesis_format():
    manager = AnalyticsManager()
    
    # Case A: nemesis is not a dict
    my_stats = {"subscribers": 150}
    rivals_str = {"nemesis": "not_a_dict"}
    assert manager.calculate_gap(my_stats, rivals_str) == []
    
    # Case B: nemesis missing 'subs' key
    rivals_missing_subs = {"nemesis": {"name": "NoSubs"}}
    assert manager.calculate_gap(my_stats, rivals_missing_subs) == []
    
    # Case C: my_stats missing 'subscribers' key
    my_stats_missing = {"total_views": 1000}
    rivals_normal = {"nemesis": {"name": "TechStarter", "subs": 180}}
    assert manager.calculate_gap(my_stats_missing, rivals_normal) == []

@pytest.mark.asyncio
async def test_generate_and_validate_thumbnail_success(tmp_path):
    manager = AnalyticsManager()
    task_id = "test_task_normal"
    db_path = str(tmp_path / "test_stage.db")
    
    # 正常系の呼び出し
    result = await manager.generate_and_validate_thumbnail(
        task_id=task_id,
        title="Valid Title",
        text="Test Thumbnail Text",
        db_path=db_path,
        output_dir=str(tmp_path),
        max_retries=1
    )
    
    # 1. 戻り値の検証
    assert result["task_id"] == task_id
    assert "path" in result
    assert result["width"] >= 1280
    assert result["height"] >= 720
    assert "verified_at" in result
    
    # 2. 生成されたファイルの物理検証
    import os
    from PIL import Image
    
    img_path = result["path"]
    assert os.path.exists(img_path)
    
    # ファイルサイズの検証 (4MB 未満)
    file_size = os.path.getsize(img_path)
    assert file_size < 4 * 1024 * 1024
    
    # Pillowによる破損チェックと解像度/アスペクト比の検証
    with Image.open(img_path) as img:
        img.verify()  # 破損していないか検証
    
    with Image.open(img_path) as img:
        img.load()  # 正常にロード可能か
        width, height = img.size
        assert width >= 1280
        assert height >= 720
        # アスペクト比が 16:9 であること (許容誤差 0.05)
        actual_ratio = float(width) / float(height)
        target_ratio = 16.0 / 9.0
        assert abs(actual_ratio - target_ratio) <= 0.05
        
    # 3. DBマイグレーション & 結果保存の検証
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        # tasks テーブルの検証
        cursor = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        task_row = cursor.fetchone()
        assert task_row is not None
        assert task_row["status"] == "COMPLETED"
        assert task_row["stage"] == "thumbnail"
        
        # thumbnail_results テーブルの検証
        cursor = conn.execute("SELECT * FROM thumbnail_results WHERE task_id = ?", (task_id,))
        res_row = cursor.fetchone()
        assert res_row is not None
        assert res_row["width"] == width
        assert res_row["height"] == height
        assert res_row["size_bytes"] == file_size
    finally:
        conn.close()

@pytest.mark.asyncio
async def test_generate_and_validate_thumbnail_invalid_title(tmp_path):
    manager = AnalyticsManager()
    db_path = str(tmp_path / "test_stage.db")
    
    # 空タイトルに対する ValueError 検証
    with pytest.raises(ValueError, match="Video title cannot be empty"):
        await manager.generate_and_validate_thumbnail(
            task_id="test_task_empty_title",
            title="",
            db_path=db_path,
            output_dir=str(tmp_path)
        )
        
    with pytest.raises(ValueError, match="Video title cannot be empty"):
        await manager.generate_and_validate_thumbnail(
            task_id="test_task_space_title",
            title="   ",
            db_path=db_path,
            output_dir=str(tmp_path)
        )

@pytest.mark.asyncio
async def test_generate_and_validate_thumbnail_retry_on_failure(tmp_path, monkeypatch):
    manager = AnalyticsManager()
    task_id = "test_task_retry"
    db_path = str(tmp_path / "test_stage.db")
    
    # 一時的に画像生成を失敗させるためのモック
    from branding.history_manager import PremiumThumbnailGenerator, ImageValidationError
    
    call_count = 0
    def mock_generate(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Temporary I/O error during image generation")
        # 2回目は本来の生成を実行
        return original_generate(*args, **kwargs)
        
    original_generate = PremiumThumbnailGenerator.generate
    monkeypatch.setattr(PremiumThumbnailGenerator, "generate", mock_generate)
    
    # max_retries = 1 なので、1回失敗しても2回目のリトライで成功するはず
    result = await manager.generate_and_validate_thumbnail(
        task_id=task_id,
        title="Valid Title",
        text="Test Retry Text",
        db_path=db_path,
        output_dir=str(tmp_path),
        max_retries=1
    )
    
    assert result["task_id"] == task_id
    assert call_count == 2  # 1回失敗、1回成功
    
    # DBの状態検証（最終的にCOMPLETEDで、retry_countが1であること）
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row["status"] == "COMPLETED"
        assert row["retry_count"] == 1
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_generate_and_validate_thumbnail_invalid_resolution(tmp_path):
    manager = AnalyticsManager()
    db_path = str(tmp_path / "test_stage.db")
    
    # 1. 解像度が低すぎる場合
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        await manager.generate_and_validate_thumbnail(
            task_id="test_low_res",
            title="Valid Title",
            db_path=db_path,
            output_dir=str(tmp_path),
            width=1000,
            height=500
        )
        
    # 2. アスペクト比が正しくない場合 (16:9ではない)
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        await manager.generate_and_validate_thumbnail(
            task_id="test_invalid_aspect",
            title="Valid Title",
            db_path=db_path,
            output_dir=str(tmp_path),
            width=1280,
            height=1280
        )

@pytest.mark.asyncio
async def test_generate_and_validate_thumbnail_size_limit_exceeded(tmp_path):
    manager = AnalyticsManager()
    db_path = str(tmp_path / "test_stage.db")
    
    # max_size_bytes を極端に小さく (例えば 100 バイト) 制限して呼び出し、サイズオーバーのエラーを検証
    with pytest.raises(RuntimeError, match="Thumbnail generation task failed:.*[Ff]ile [Ss]ize"):
        await manager.generate_and_validate_thumbnail(
            task_id="test_size_limit",
            title="Valid Title",
            db_path=db_path,
            output_dir=str(tmp_path),
            max_size_bytes=100,
            max_retries=0
        )


@pytest.mark.asyncio
async def test_generate_and_validate_thumbnail_all_retries_fail(tmp_path, monkeypatch):
    """すべてのリトライが失敗し、最終的に FAILED になることの検証"""
    manager = AnalyticsManager()
    task_id = "test_task_all_fail"
    db_path = str(tmp_path / "test_stage.db")
    
    from branding.history_manager import PremiumThumbnailGenerator
    
    # 常にエラーをスローするモック
    def mock_generate_always(*args, **kwargs):
        raise RuntimeError("Persistent image generation error")
        
    monkeypatch.setattr(PremiumThumbnailGenerator, "generate", mock_generate_always)
    
    # max_retries=1 (計2回試行) で呼び出し、最終的に RuntimeError になること
    with pytest.raises(RuntimeError, match="Thumbnail generation task failed:.*Persistent image generation error"):
        await manager.generate_and_validate_thumbnail(
            task_id=task_id,
            title="Valid Title",
            text="Test All Fail",
            db_path=db_path,
            output_dir=str(tmp_path),
            max_retries=1
        )
        
    # DBステータスが FAILED であることの検証
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row["status"] == "FAILED"
        assert "Persistent image generation error" in row["error"]
        assert row["retry_count"] == 1
    finally:
        conn.close()

@pytest.mark.asyncio
async def test_generate_and_validate_thumbnail_corrupt_file_handling(tmp_path, monkeypatch):
    """画像ファイルが破損している（Pillowでロード不可な）場合のエラーハンドリング検証"""
    manager = AnalyticsManager()
    task_id = "test_task_corrupt_img"
    db_path = str(tmp_path / "test_stage.db")
    
    from branding.history_manager import PremiumThumbnailGenerator
    
    # ゴミデータを書き出すモック生成器
    def mock_generate_corrupt(output_path, *args, **kwargs):
        with open(output_path, "wb") as f:
            f.write(b"NOT_A_VALID_IMAGE_DATA_AT_ALL_HELLOWORLD")
        from pathlib import Path
        return Path(output_path)
        
    monkeypatch.setattr(PremiumThumbnailGenerator, "generate", mock_generate_corrupt)
    
    # max_retries=0 で実行し、画像破損による ImageValidationError -> RuntimeError になること
    with pytest.raises(RuntimeError, match="Thumbnail generation task failed:.*(corrupted|format|recognized)"):
        await manager.generate_and_validate_thumbnail(
            task_id=task_id,
            title="Valid Title",
            text="Test Corrupt",
            db_path=db_path,
            output_dir=str(tmp_path),
            max_retries=0
        )

@pytest.mark.asyncio
async def test_generate_and_validate_thumbnail_timeout_db_update(tmp_path, monkeypatch):
    """ポーリング待機がタイムアウトした際に、DBステータスがFAILEDに更新されることの検証"""
    manager = AnalyticsManager()
    task_id = "test_task_timeout"
    db_path = str(tmp_path / "test_stage.db")
    
    # タイムアウトを引き起こすために、エージェントの get_task_status を常に READY に固定
    from agents.stage_bound_agent import StageBoundAgent
    original_get_status = StageBoundAgent.get_task_status
    
    async def mock_get_task_status(self, tid):
        return "READY"
        
    monkeypatch.setattr(StageBoundAgent, "get_task_status", mock_get_task_status)
    
    # タイムアウト時間を一時的に短縮するために、テスト用の短いタイムアウト処理を適用
    # （実際のプロダクションコードでは30秒ループですが、ここでは mock を使って TimeoutError を誘発）
    # ループ自体のタイムアウトを短くするため、time.time() の初期値を過去の値にモックする
    import time
    original_time = time.time
    time_calls = 0
    def mock_time():
        nonlocal time_calls
        time_calls += 1
        if time_calls > 3:
            return original_time() + 100.0  # タイムアウト閾値(30秒)を超えるようにジャンプさせる
        return original_time()
        
    monkeypatch.setattr(time, "time", mock_time)
    
    with pytest.raises(TimeoutError, match="Thumbnail generation timed out"):
        await manager.generate_and_validate_thumbnail(
            task_id=task_id,
            title="Valid Title",
            db_path=db_path,
            output_dir=str(tmp_path),
            max_retries=0
        )
        
    # DBの状態検証（FAILEDでタイムアウトエラーが記録されていること）
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row["status"] == "FAILED"
        assert "Thumbnail generation timed out" in row["error"]
    finally:
        conn.close()

@pytest.mark.asyncio
async def test_generate_and_validate_thumbnail_aspect_ratio_error(tmp_path):
    """アスペクト比が16:9でない場合に ValueError が発生することの検証"""
    manager = AnalyticsManager()
    db_path = str(tmp_path / "test_stage.db")
    
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        await manager.generate_and_validate_thumbnail(
            task_id="test_invalid_aspect",
            title="Valid Title",
            db_path=db_path,
            output_dir=str(tmp_path),
            width=1280,
            height=1000,
            aspect_ratio="16:9"
        )

@pytest.mark.asyncio
async def test_generate_and_validate_thumbnail_extreme_resolutions(tmp_path):
    """解像度が不適切な（負の数や小さすぎる）場合に ValueError が発生することの検証"""
    manager = AnalyticsManager()
    db_path = str(tmp_path / "test_stage.db")
    
    with pytest.raises(ValueError, match="Resolution must be positive integers"):
        await manager.generate_and_validate_thumbnail(
            task_id="test_neg_res",
            title="Valid Title",
            db_path=db_path,
            output_dir=str(tmp_path),
            width=-1280,
            height=720
        )
        
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        await manager.generate_and_validate_thumbnail(
            task_id="test_small_res",
            title="Valid Title",
            db_path=db_path,
            output_dir=str(tmp_path),
            width=640,
            height=360
        )

@pytest.mark.asyncio
async def test_generate_and_validate_thumbnail_options(tmp_path):
    """高度な描画オプション（矢印、サークル、バナー）を指定して正常に生成できることの検証"""
    manager = AnalyticsManager()
    task_id = "test_task_with_options"
    db_path = str(tmp_path / "test_stage.db")
    
    result = await manager.generate_and_validate_thumbnail(
        task_id=task_id,
        title="Valid Title With Options",
        text="Premium Options\nSecond Line Text",
        db_path=db_path,
        output_dir=str(tmp_path),
        max_retries=0,
        draw_arrow=True,
        draw_circle=True,
        use_banner=True
    )
    
    assert result["task_id"] == task_id
    assert "path" in result
    
    # 物理ファイルの検証
    import os
    from PIL import Image
    assert os.path.exists(result["path"])
    with Image.open(result["path"]) as img:
        img.verify()
    with Image.open(result["path"]) as img:
        img.load()
        assert img.size == (1280, 720)


@pytest.mark.asyncio
async def test_generate_and_validate_thumbnail_oserror_during_generation(tmp_path, monkeypatch):
    """画像生成中に OSError が発生した場合に ImageValidationError が発生することの検証"""
    manager = AnalyticsManager()
    task_id = "test_task_oserror_gen"
    db_path = str(tmp_path / "test_stage.db")
    
    from branding.history_manager import PremiumThumbnailGenerator
    
    def mock_generate_oserror(*args, **kwargs):
        raise OSError("Simulated disk I/O error during generation")
        
    monkeypatch.setattr(PremiumThumbnailGenerator, "generate", mock_generate_oserror)
    
    with pytest.raises(RuntimeError, match="Thumbnail generation task failed:.*Simulated disk I/O error"):
        await manager.generate_and_validate_thumbnail(
            task_id=task_id,
            title="Valid Title",
            db_path=db_path,
            output_dir=str(tmp_path),
            max_retries=0
        )

@pytest.mark.asyncio
async def test_generate_and_validate_thumbnail_sqlite_error_during_save(tmp_path, monkeypatch):
    """DB結果保存時に sqlite3.Error が発生した場合のロールバック動作検証"""
    manager = AnalyticsManager()
    task_id = "test_task_sqlite_err"
    db_path = str(tmp_path / "test_stage.db")
    
    import sqlite3
    import inspect
    original_connect = sqlite3.connect
    
    def mock_connect(database, *args, **kwargs):
        frame_names = [f.function for f in inspect.stack()]
        if database == db_path and "process_func" in frame_names:
            raise sqlite3.Error("Simulated write failure")
        return original_connect(database, *args, **kwargs)
        
    monkeypatch.setattr(sqlite3, "connect", mock_connect)
    
    with pytest.raises(RuntimeError, match="Thumbnail generation task failed:.*Simulated write failure"):
        await manager.generate_and_validate_thumbnail(
            task_id=task_id,
            title="Valid Title",
            db_path=db_path,
            output_dir=str(tmp_path),
            max_retries=0
        )
