import json
import pytest
import struct
from pathlib import Path
from branding.history_manager import StatusHistoryManager, EventType, ThumbnailValidator, ImageValidationError
from unittest.mock import patch, MagicMock

def test_history_manager_custom_path(tmp_path):
    # テストごとにユニークな一時パスを指定
    custom_file = tmp_path / "test_history.jsonl"
    
    # 初期化した時点ではファイルは生成されない
    manager = StatusHistoryManager(history_file=custom_file)
    assert not custom_file.exists()
    
    # 最初のイベントログ記録でファイルが生成される
    manager.log_event(EventType.STATUS_CHANGE, {"test": "data"})
    assert custom_file.exists()

def test_history_manager_log_and_get(tmp_path):
    custom_file = tmp_path / "test_history.jsonl"
    manager = StatusHistoryManager(history_file=custom_file)
    
    # イベントを複数記録
    manager.log_event(EventType.STATUS_CHANGE, {"event": 1})
    manager.log_event(EventType.TASK_COMPLETION, {"event": 2})
    
    history = manager.get_history()
    assert len(history) == 2
    assert history[0]["type"] == EventType.STATUS_CHANGE.value
    assert history[0]["data"] == {"event": 1}
    assert history[1]["type"] == EventType.TASK_COMPLETION.value
    assert history[1]["data"] == {"event": 2}

def test_history_manager_limit(tmp_path):
    custom_file = tmp_path / "test_history.jsonl"
    manager = StatusHistoryManager(history_file=custom_file)
    
    for i in range(10):
        manager.log_event(EventType.SYSTEM_EVENT, {"index": i})
        
    # limit=5 で直近5件が取れること
    history = manager.get_history(limit=5)
    assert len(history) == 5
    assert history[0]["data"] == {"index": 5}
    assert history[4]["data"] == {"index": 9}

def test_history_manager_corrupted_json(tmp_path):
    custom_file = tmp_path / "test_history.jsonl"
    manager = StatusHistoryManager(history_file=custom_file)
    
    # 正常なデータ1
    manager.log_event(EventType.CHAT_INTERACTION, {"index": 1})
    
    # 破損したJSON行を直接ファイルに書き込む
    manager._ensure_storage()
    with open(custom_file, "a", encoding="utf-8") as f:
        f.write("{invalid json line\n")
        f.write("\n")  # 空行
    
    # 正常なデータ2
    manager.log_event(EventType.USER_INTERACTION, {"index": 2})
    
    # get_historyを実行
    history = manager.get_history()
    
    # 破損した行と空行がスキップされ、正常な2つのデータだけが取得できること
    assert len(history) == 2
    assert history[0]["data"] == {"index": 1}
    assert history[1]["data"] == {"index": 2}

def test_history_manager_missing_file(tmp_path):
    # 存在しないパスを指定したとき、エラーにならずに空のリストが返る
    custom_file = tmp_path / "non_existent_history.jsonl"
    manager = StatusHistoryManager(history_file=custom_file)
    history = manager.get_history()
    assert history == []

def test_history_manager_log_event_exception(tmp_path):
    custom_file = tmp_path / "test_history.jsonl"
    manager = StatusHistoryManager(history_file=custom_file)
    
    with patch("builtins.open", side_effect=IOError("Permission denied")):
        # ログメッセージが標準出力からロガーに変わったため、例外ハンドリングを確認（エラーをスルー・ログ出力するのみ）
        manager.log_event(EventType.STATUS_CHANGE, {"test": 1})

def test_history_manager_get_history_exception(tmp_path):
    custom_file = tmp_path / "test_history.jsonl"
    manager = StatusHistoryManager(history_file=custom_file)
    
    # 実際ファイルがある状態にしておく
    manager.log_event(EventType.STATUS_CHANGE, {"test": 1})
    
    with patch("builtins.open", side_effect=IOError("Read error")):
        history = manager.get_history()
        assert history == []

def test_history_manager_get_recent_events(tmp_path):
    custom_file = tmp_path / "test_history.jsonl"
    manager = StatusHistoryManager(history_file=custom_file)
    
    # 異なるタイプのイベントを記録
    manager.log_event(EventType.STATUS_CHANGE, {"data": "status1"})
    manager.log_event(EventType.TASK_COMPLETION, {"data": "task1"})
    manager.log_event(EventType.STATUS_CHANGE, {"data": "status2"})
    manager.log_event(EventType.STATUS_CHANGE, {"data": "status3"})
    
    # STATUS_CHANGE だけをフィルタリングして取得
    status_events = manager.get_recent_events(EventType.STATUS_CHANGE, limit=2)
    
    # 最新の2件だけが取れること
    assert len(status_events) == 2
    assert status_events[0]["data"] == {"data": "status2"}
    assert status_events[1]["data"] == {"data": "status3"}
    assert all(e["type"] == EventType.STATUS_CHANGE.value for e in status_events)


# =====================================================================
# ThumbnailValidator の追加検証テスト
# =====================================================================

# 正常な1280x720 JPEG (16:9) のダミーヘッダ
VALID_DUMMY_JPEG = b'\xff\xd8\xff\xc0\x00\x0b\x08\x02\xd0\x05\x00\x03\x01"x00'
# 1920x1080 PNG (16:9) のダミーヘッダ
VALID_DUMMY_PNG = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x07\x80\x00\x00\x04\x38\x08\x02\x00\x00\x00'

def test_thumbnail_validator_success_cases():
    """正常系JPEG/PNGの検証テスト"""
    # 正常なJPEGがパスすることを確認
    assert ThumbnailValidator.validate_image(VALID_DUMMY_JPEG) is True
    # 正常なPNGがパスすることを確認
    assert ThumbnailValidator.validate_image(VALID_DUMMY_PNG) is True

def test_thumbnail_validator_empty_data():
    """空データの検証テスト"""
    with pytest.raises(ImageValidationError, match="Image data is empty"):
        ThumbnailValidator.validate_image(b"")

def test_thumbnail_validator_corrupted_short_binary():
    """極端に短いバイナリや破損したデータの検証テスト"""
    # ヘッダ判定のみ一致するがデータ長が足りない PNG
    short_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00'
    with pytest.raises(ImageValidationError, match="missing header data|Failed to parse image binary structure"):
        ThumbnailValidator.validate_image(short_png)
        
    # 不適切なテキストデータ
    with pytest.raises(ImageValidationError, match="Unsupported image format"):
        ThumbnailValidator.validate_image(b"this is a text file, not an image at all.")

def test_thumbnail_validator_jpeg_infinite_loop_prevention():
    """JPEGのセグメント長が異常な場合（無限ループ防止）のテスト"""
    # JPEGヘッダの直後に異常なセグメント長（length = 0）を持つ破損バイナリ
    loop_jpeg = b'\xff\xd8\xff\xe0\x00\x00\x00\x00\x00'
    with pytest.raises(ImageValidationError, match="marker segment length is too small|Failed to parse image binary structure"):
        ThumbnailValidator.validate_image(loop_jpeg)

def test_thumbnail_validator_color_mode_check():
    """カラーモード品質チェックの検証テスト"""
    # Pillowが利用可能な場合に、不適切なカラーモード（モノクロ "1" や グレースケール "L"）を制限する
    try:
        from PIL import Image
        pillow_available = True
    except ImportError:
        pillow_available = False

    if pillow_available:
        # モノクロ "1" の画像データをモック
        mock_img = MagicMock()
        mock_img.size = (1280, 720)
        mock_img.mode = "1"
        
        with patch("PIL.Image.open") as mock_open:
            mock_open.return_value.__enter__.return_value = mock_img
            
            # デフォルトの allowed_modes = ["RGB", "RGBA", ...] に "1" は含まれないため失敗するはず
            with pytest.raises(ImageValidationError, match="color mode '1' is not in allowed color spaces"):
                ThumbnailValidator.validate_image(VALID_DUMMY_JPEG)
                
            # 明示的に "1" を許可した場合はパスするはず
            assert ThumbnailValidator.validate_image(VALID_DUMMY_JPEG, allowed_modes=["1"]) is True
            
            # グレースケール "L" をモック
            mock_img.mode = "L"
            with pytest.raises(ImageValidationError, match="color mode 'L' is not in allowed color spaces"):
                ThumbnailValidator.validate_image(VALID_DUMMY_JPEG)
    else:
        # Pillowがない場合はカラーモードチェックはスキップされ成功する
        assert ThumbnailValidator.validate_image(VALID_DUMMY_JPEG) is True

def test_thumbnail_validator_parsing_exceptions():
    """struct.error や IndexError などのパース例外発生時のハンドリング"""
    # struct.unpack時に例外が発生した場合に正しくImageValidationErrorへ変換されるか
    with patch("struct.unpack", side_effect=struct.error("unpack requires a buffer of 2 bytes")):
        with pytest.raises(ImageValidationError, match="Failed to parse image binary structure"):
            ThumbnailValidator.validate_image(VALID_DUMMY_JPEG)


# =====================================================================
# 追加の例外・境界値およびカバレッジ向上テスト
# =====================================================================

def test_history_manager_log_event_unexpected_exception(tmp_path):
    custom_file = tmp_path / "test_history.jsonl"
    manager = StatusHistoryManager(history_file=custom_file)
    with patch("builtins.open", side_effect=TypeError("Unexpected error")):
        manager.log_event(EventType.STATUS_CHANGE, {"test": 1})

def test_history_manager_get_history_unexpected_exception(tmp_path):
    custom_file = tmp_path / "test_history.jsonl"
    manager = StatusHistoryManager(history_file=custom_file)
    manager.log_event(EventType.STATUS_CHANGE, {"test": 1})
    with patch("builtins.open", side_effect=TypeError("Unexpected error")):
        history = manager.get_history()
        assert history == []

def test_thumbnail_validator_pillow_import_error():
    import sys
    # sys.modulesにNoneを設定してImportErrorをシミュレート
    with patch.dict(sys.modules, {"PIL": None, "PIL.Image": None}):
        # Pillowがない場合でも自前バイナリ解析フォールバックでPNGがパスすることを確認
        assert ThumbnailValidator.validate_image(VALID_DUMMY_PNG) is True
        # 自前JPEG解析の正常系も通すため、Pillow無しの状態でJPEGを検証
        assert ThumbnailValidator.validate_image(VALID_DUMMY_JPEG) is True

def test_thumbnail_validator_limits():
    # 4MB制限のテスト（4MBを超えるサイズ）
    header = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x07\x80\x00\x00\x04\x38\x08\x02\x00\x00\x00'
    large_bytes_with_header = header + b'\x00' * (4 * 1024 * 1024 - len(header) + 10)
    with pytest.raises(ImageValidationError, match="exceeds limit"):
        ThumbnailValidator.validate_image(large_bytes_with_header)

    # 最小解像度（1280x720）を下回るテスト (例: 640x360)
    low_res_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x02\x80\x00\x00\x01\x68\x08\x02\x00\x00\x00'
    with pytest.raises(ImageValidationError, match="below minimum requirement"):
        ThumbnailValidator.validate_image(low_res_png)

    # アスペクト比不一致のテスト（例: 1:1）
    square_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x05\x00\x00\x00\x05\x00\x08\x02\x00\x00\x00'
    with pytest.raises(ImageValidationError, match="does not match expected 16:9"):
        ThumbnailValidator.validate_image(square_png)
        
    with pytest.raises(ImageValidationError, match="does not match expected 1:1"):
        ThumbnailValidator.validate_image(VALID_DUMMY_PNG, aspect_ratio="1:1")

def test_thumbnail_validator_jpeg_edge_cases():
    import sys
    # 自前JPEG解析ロジックを確実に走らせるためにPillowを無効化
    with patch.dict(sys.modules, {"PIL": None, "PIL.Image": None}):
        # L131-132: non-0xff bytes at start of loop
        non_ff_jpeg = b'\xff\xd8\x00\x00\xff\xc0\x00\x0b\x08\x02\xd0\x05\x00\x03\x01"x00'
        assert ThumbnailValidator.validate_image(non_ff_jpeg) is True

        # L137: ends with 0xff
        ends_ff_jpeg = b'\xff\xd8\xff\xff'
        with pytest.raises(ImageValidationError, match="Invalid JPEG format or SOF marker not found"):
            ThumbnailValidator.validate_image(ends_ff_jpeg)

        # L143: marker in (...)
        marker_continue_jpeg = b'\xff\xd8\xff\xd0\xff\xc0\x00\x0b\x08\x02\xd0\x05\x00\x03\x01"x00'
        assert ThumbnailValidator.validate_image(marker_continue_jpeg) is True

        # L146: length segment too short
        short_len_jpeg = b'\xff\xd8\xff\xc0\x00'
        with pytest.raises(ImageValidationError, match="Invalid JPEG format or SOF marker not found"):
            ThumbnailValidator.validate_image(short_len_jpeg)

        # L156-158: length is correct, but insufficient bytes for dimensions
        insufficient_bytes_jpeg = b'\xff\xd8\xff\xc0\x00\x04\x08'
        with pytest.raises(ImageValidationError, match="Invalid JPEG format or SOF marker not found"):
            ThumbnailValidator.validate_image(insufficient_bytes_jpeg)

        # L157: idx += length をカバー（APP0マーカーの後にSOF0マーカーが続く）
        multi_marker_jpeg = b'\xff\xd8' + b'\xff\xe0\x00\x04\x00\x00' + b'\xff\xc0\x00\x0b\x08\x02\xd0\x05\x00\x03\x01"x00'
        assert ThumbnailValidator.validate_image(multi_marker_jpeg) is True

@pytest.mark.asyncio
async def test_premium_thumbnail_generation_and_verification(tmp_path):
    """プレミアムサムネイル画像生成と品質検証のテスト"""
    from branding.history_manager import PremiumThumbnailGenerator, ThumbnailValidator
    
    output_path = tmp_path / "premium_thumb_test.png"
    task_id = "test-task-123"
    
    # プレミアムサムネイルの生成
    generated_path = PremiumThumbnailGenerator.generate(
        output_path=output_path,
        text=f"Test Premium: {task_id}"
    )
    
    assert generated_path.exists()
    
    # 生成された画像のバイナリ検証
    with open(generated_path, "rb") as f:
        img_bytes = f.read()
        
    # 解像度、アスペクト比、ファイルサイズ制限、カラーモード等の検証
    assert ThumbnailValidator.validate_image(img_bytes) is True
    
    # Pillowによる破損なしチェック
    from PIL import Image
    with Image.open(generated_path) as img:
        img.load()
        assert img.size[0] >= 1280
        assert img.size[1] >= 720
        assert abs((img.size[0] / img.size[1]) - (16.0 / 9.0)) < 0.05
        assert len(img_bytes) < 4 * 1024 * 1024

@pytest.mark.asyncio
async def test_stage_bound_agent_integration(tmp_path):
    """StageBoundAgent連携、自動リトライ、結果保存、DBマイグレーションのテスト"""
    import asyncio
    import sqlite3
    from agents.stage_bound_agent import StageBoundAgent
    from branding.history_manager import resolve_thumbnail_task
    
    db_path = tmp_path / "tasks.db"
    agent = StageBoundAgent(
        stage_name="thumbnail",
        db_path=str(db_path),
        poll_interval=0.01
    )
    
    task_id = "T-test-integration-001"
    # タスクを READY 状態で登録
    await agent.register_task(task_id, initial_status="READY", max_retries=1)
    
    # process_func として登録して実行
    output_dir = tmp_path / "temp_thumbnails"
    
    async def process_func(t_id):
        # history_manager 内に定義する resolve_thumbnail_task を非同期で呼び出す
        return await resolve_thumbnail_task(t_id, db_path=str(db_path), output_dir=output_dir)
        
    await agent.start(process_func)
    
    # タスクが完了（COMPLETED）するのを待つ
    for _ in range(50):
        status = await agent.get_task_status(task_id)
        if status == "COMPLETED":
            break
        await asyncio.sleep(0.1)
        
    await agent.stop()
    
    # 最終ステータスが COMPLETED であること
    assert await agent.get_task_status(task_id) == "COMPLETED"
    
    # DBマイグレーションと結果保存の検証
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='thumbnail_results'")
        assert cursor.fetchone() is not None, "thumbnail_results table should be migrated"
        
        cursor = conn.execute("SELECT * FROM thumbnail_results WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None, "Result record should be saved in DB"
        # columns: task_id, path, width, height, size_bytes, verified_at
        assert row[0] == task_id
        assert Path(row[1]).exists(), "Generated image path should exist"
        assert row[2] >= 1280
        assert row[3] >= 720
        assert row[4] < 4 * 1024 * 1024
    finally:
        conn.close()


def test_thumbnail_quality_explicit_requirements(tmp_path):
    """
    要件で指定された品質基準を個別に厳密に自動検証するテスト：
    - 生成画像の解像度が 1280x720 以上であること
    - アスペクト比が 16:9 であること
    - ファイルサイズが 4MB 未満であること
    - 出力ファイルが正常に存在し、破損していない（Pillow等で正常にロード可能である）こと
    """
    from branding.history_manager import PremiumThumbnailGenerator, ThumbnailValidator
    from PIL import Image

    output_path = tmp_path / "explicit_requirements_thumb.png"
    
    # 1. プレミアムサムネイルを生成
    generated_path = PremiumThumbnailGenerator.generate(
        output_path=output_path,
        text="Quality Assurance Test"
    )
    
    # 2. 出力ファイルが正常に存在することの検証
    assert generated_path.exists()
    assert generated_path.is_file()

    # 3. ファイルサイズが 4MB 未満であることの検証
    size_bytes = generated_path.stat().st_size
    assert size_bytes < 4 * 1024 * 1024, f"File size {size_bytes} is >= 4MB"

    # 4. 破損していないこと（Pillow等で正常にロード可能である）の検証
    try:
        with Image.open(generated_path) as img:
            img.load()  # ロードしてデコード処理を実行することで破損していないことを保証
            width, height = img.size
    except Exception as e:
        pytest.fail(f"Failed to load image with Pillow (possibly corrupted): {e}")

    # 5. 解像度が 1280x720 以上であることの検証
    assert width >= 1280, f"Width {width} is less than 1280"
    assert height >= 720, f"Height {height} is less than 720"

    # 6. アスペクト比が 16:9 であることの検証
    # アスペクト比誤差許容範囲 5%
    aspect_ratio = width / height
    target_ratio = 16.0 / 9.0
    assert abs(aspect_ratio - target_ratio) < 0.05, f"Aspect ratio {aspect_ratio:.3f} is not close to 16:9"

    # 7. バリデータを通しても True が返ることの検証
    with open(generated_path, "rb") as f:
        img_bytes = f.read()
    assert ThumbnailValidator.validate_image(img_bytes) is True


@pytest.mark.asyncio
async def test_stage_bound_agent_retry_behavior(tmp_path):
    """
    StageBoundAgent等に登録され、自動リトライ機能が正しく動作することの検証
    """
    import asyncio
    import sqlite3
    from agents.stage_bound_agent import StageBoundAgent
    
    db_path = tmp_path / "retry_tasks.db"
    agent = StageBoundAgent(
        stage_name="thumbnail",
        db_path=str(db_path),
        poll_interval=0.01
    )
    
    task_id = "T-retry-test-001"
    # 最大リトライ回数2で登録
    await agent.register_task(task_id, initial_status="READY", max_retries=2)
    
    call_count = 0
    
    async def process_func_with_retry(t_id):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            # 1回目は失敗させる
            raise ValueError("Simulated transient failure")
        else:
            # 2回目は成功させる
            return json.dumps({"task_id": t_id, "status": "success_after_retry"})
            
    await agent.start(process_func_with_retry)
    
    # タスクが完了（COMPLETED）するのを待つ
    for _ in range(50):
        status = await agent.get_task_status(task_id)
        if status in ("COMPLETED", "FAILED"):
            break
        await asyncio.sleep(0.1)
        
    await agent.stop()
    
    # リトライにより2回呼び出され、最終的に COMPLETED になっていること
    assert call_count == 2
    assert await agent.get_task_status(task_id) == "COMPLETED"


