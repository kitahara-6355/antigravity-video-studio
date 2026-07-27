import os
import json
import sqlite3
import asyncio
import pytest
from pathlib import Path
from PIL import Image

from branding_manager import BrandingManager
from agents.stage_bound_agent import StageBoundAgent
from branding.history_manager import resolve_thumbnail_task, ThumbnailValidator, ImageValidationError

@pytest.fixture
def constitution_data():
    return {
        "channel_name": "Antigravity Test Studio",
        "branding_rules": {
            "primary_color": "#FF0055",
            "font_family": "Arial",
            "logo_path": "logo.png"
        }
    }

@pytest.fixture
def branding_mgr(constitution_data):
    return BrandingManager(constitution=constitution_data)

def test_validate_image_quality_success(branding_mgr, tmp_path):
    """画像の品質基準(1280x720, 16:9, 4MB未満, 破損なし)を満たす場合、検証にパスすること"""
    # 1. 1280x720 (16:9) の正常な画像を生成
    img_path = tmp_path / "valid_image.jpg"
    img = Image.new("RGB", (1280, 720), color=(100, 100, 255))
    img.save(img_path, format="JPEG")
    
    # 2. 検証
    result = branding_mgr.validate_image_quality(img_path)
    assert result["width"] == 1280
    assert result["height"] == 720
    assert result["size_bytes"] > 0
    assert result["size_bytes"] < 4 * 1024 * 1024

def test_validate_image_quality_bytes(branding_mgr):
    """バイト配列での画像検証が正常に行えること"""
    # 1. バイト配列の画像生成
    import io
    img = Image.new("RGB", (1920, 1080), color=(100, 100, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    img_bytes = buf.getvalue()
    
    # 2. 検証
    result = branding_mgr.validate_image_quality(img_bytes)
    assert result["width"] == 1920
    assert result["height"] == 1080
    assert result["size_bytes"] == len(img_bytes)

def test_validate_image_quality_invalid_ratio(branding_mgr, tmp_path):
    """アスペクト比が16:9でない場合にValueErrorを投げること"""
    # 1. 800x600 (4:3) の画像を生成
    img_path = tmp_path / "invalid_ratio.jpg"
    img = Image.new("RGB", (800, 600), color=(255, 0, 0))
    img.save(img_path, format="JPEG")
    
    # 2. 検証がアスペクト比違反を検知して ValueError を投げること
    with pytest.raises(ValueError, match="Aspect ratio"):
        branding_mgr.validate_image_quality(img_path)

def test_validate_image_quality_too_small(branding_mgr, tmp_path):
    """解像度が1280x720未満の場合にValueErrorを投げること"""
    # 1. 640x360 (16:9だが低解像度)
    img_path = tmp_path / "too_small.jpg"
    img = Image.new("RGB", (640, 360), color=(255, 0, 0))
    img.save(img_path, format="JPEG")
    
    # 2. 検証
    with pytest.raises(ValueError, match="Resolution"):
        branding_mgr.validate_image_quality(img_path)

def test_validate_image_quality_corrupted(branding_mgr, tmp_path):
    """破損画像（デコード不可）を検証した際にIOErrorを投げること"""
    # 1. 不正な画像データをファイルに保存
    corrupt_path = tmp_path / "corrupted.jpg"
    with open(corrupt_path, "wb") as f:
        f.write(b"not a valid image data")
        
    # 2. 検証が IOError を投げること
    with pytest.raises(IOError):
        branding_mgr.validate_image_quality(corrupt_path)

def test_fallback_image_generation(branding_mgr):
    """フォールバック画像が正しく生成され、品質基準を満たし、長いタイトルが折り返されること"""
    # 非常に長いタイトル（折り返しが必要）
    long_title = "これは非常に長いタイトルでありフォールバック画像生成時に複数行に折り返される必要があります"
    img_bytes = branding_mgr._generate_fallback_image_bytes(long_title)
    
    # 品質検証
    result = branding_mgr.validate_image_quality(img_bytes)
    assert result["width"] == 1280
    assert result["height"] == 720
    assert result["size_bytes"] < 4 * 1024 * 1024

@pytest.mark.anyio
async def test_stage_bound_agent_integration(tmp_path, constitution_data):
    """StageBoundAgentと連携し、正常なサムネイル生成タスクを完了できること"""
    db_file = tmp_path / "tasks.db"
    agent = StageBoundAgent(
        stage_name="thumbnail",
        db_path=str(db_file),
        poll_interval=0.01
    )
    
    # BrandingManagerを初期化
    mgr = BrandingManager(constitution=constitution_data)
    
    # タスクの登録
    task_id = "task_branding_thumb_success"
    await agent.register_task(
        task_id,
        initial_status="READY",
        max_retries=2
    )
    
    # タスク解決関数のバインド
    async def process_task(tid):
        return await mgr.resolve_thumbnail_task(task_id=tid, output_dir=str(tmp_path))
        
    # Agent起動
    await agent.start(process_task)
    
    # 完了待機
    for _ in range(50):
        status = await agent.get_task_status(task_id)
        if status == "COMPLETED":
            break
        await asyncio.sleep(0.05)
        
    status = await agent.get_task_status(task_id)
    assert status == "COMPLETED"
    
    # 結果の検証
    conn = sqlite3.connect(str(db_file))
    cursor = conn.execute("SELECT result, retry_count FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    result_json = json.loads(row[0])
    assert result_json["width"] >= 1280
    assert result_json["height"] >= 720
    assert Path(result_json["path"]).exists()
    assert row[1] == 0  # リトライ0回
    
    await agent.stop()

@pytest.mark.anyio
async def test_stage_bound_agent_retry_on_failure(tmp_path, constitution_data):
    """無効な入力やファイル書き込み不可などのエラー時に自動リトライが働き最終的にFAILEDになること"""
    db_file = tmp_path / "tasks_retry.db"
    agent = StageBoundAgent(
        stage_name="thumbnail",
        db_path=str(db_file),
        poll_interval=0.01
    )
    
    # BrandingManagerを初期化
    mgr = BrandingManager(constitution=constitution_data)
    
    # タスク登録 (無効なパスにより resolve_thumbnail_task 内で OSError が発生する)
    task_id = "task_branding_thumb_fail"
    await agent.register_task(
        task_id,
        initial_status="READY",
        max_retries=2
    )
    
    async def process_task(tid):
        return await mgr.resolve_thumbnail_task(task_id=tid, output_dir=":/invalid_path/\\/?*")
        
    # Agent起動
    await agent.start(process_task)
    
    # 失敗待機
    for _ in range(50):
        status = await agent.get_task_status(task_id)
        if status == "FAILED":
            break
        await asyncio.sleep(0.05)
        
    status = await agent.get_task_status(task_id)
    assert status == "FAILED"
    
    # リトライ回数とエラーの検証
    conn = sqlite3.connect(str(db_file))
    cursor = conn.execute("SELECT retry_count, error FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    assert row[0] == 2  # max_retries = 2
    assert row[1] is not None and len(row[1]) > 0
    
    await agent.stop()


def test_history_manager_log_event_exception(tmp_path):
    from branding.history_manager import StatusHistoryManager, EventType
    from unittest.mock import patch
    history_file = tmp_path / "history.jsonl"
    mgr = StatusHistoryManager(history_file=history_file)
    with patch("builtins.open", side_effect=OSError("fake disk error")):
        mgr.log_event(EventType.SYSTEM_EVENT, {"test": "data"})

def test_history_manager_get_history_exception(tmp_path):
    from branding.history_manager import StatusHistoryManager
    from unittest.mock import patch
    history_file = tmp_path / "history.jsonl"
    history_file.touch()
    mgr = StatusHistoryManager(history_file=history_file)
    with patch("builtins.open", side_effect=OSError("fake read error")):
        res = mgr.get_history()
        assert res == []

def test_history_manager_get_recent_events(tmp_path):
    from branding.history_manager import StatusHistoryManager, EventType
    history_file = tmp_path / "history.jsonl"
    mgr = StatusHistoryManager(history_file=history_file)
    mgr.log_event(EventType.SYSTEM_EVENT, {"val": 1})
    mgr.log_event(EventType.STATUS_CHANGE, {"val": 2})
    events = mgr.get_recent_events(EventType.SYSTEM_EVENT)
    assert len(events) == 1
    assert events[0]["data"]["val"] == 1

def test_thumbnail_validator_pillow_import_error():
    import sys
    from unittest.mock import patch
    with patch.dict(sys.modules, {'PIL': None}):
        import struct
        png_data = b'\x89PNG\r\n\x1a\n' + b'\x00' * 8 + struct.pack('>II', 1920, 1080) + b'IEND'
        size, mode = ThumbnailValidator._get_image_dimensions_and_mode(png_data)
        assert size == (1920, 1080)
        assert mode is None

def test_thumbnail_validator_corrupt_png():
    import sys
    from unittest.mock import patch
    png_short = b'\x89PNG\r\n\x1a\n' + b'\x00' * 4
    with patch.dict(sys.modules, {'PIL': None}), pytest.raises(ImageValidationError):
        ThumbnailValidator._get_image_dimensions_and_mode(png_short)

def test_thumbnail_validator_corrupt_jpeg():
    import sys
    from unittest.mock import patch
    
    jpeg_short = b'\xff\xd8'
    with patch.dict(sys.modules, {'PIL': None}), pytest.raises(ImageValidationError, match="JPEG image is too short"):
        ThumbnailValidator._get_image_dimensions_and_mode(jpeg_short)
        
    import struct
    jpeg_invalid_marker = b'\xff\xd8\xff\xe0' + struct.pack('>H', 1) + b'\x00' * 5 + b'\xff\xd9'
    with patch.dict(sys.modules, {'PIL': None}), pytest.raises(ImageValidationError, match="marker segment length is too small"):
        ThumbnailValidator._get_image_dimensions_and_mode(jpeg_invalid_marker)
        
    jpeg_overflow = b'\xff\xd8\xff\xe0' + struct.pack('>H', 100) + b'\x00' * 5 + b'\xff\xd9'
    with patch.dict(sys.modules, {'PIL': None}), pytest.raises(ImageValidationError, match="segment extends beyond"):
        ThumbnailValidator._get_image_dimensions_and_mode(jpeg_overflow)

def test_thumbnail_validator_aspect_ratio_1_1():
    from PIL import Image
    import io
    
    img = Image.new("RGB", (800, 800), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    img_bytes = buf.getvalue()
    
    assert ThumbnailValidator.validate_image(img_bytes, aspect_ratio="1:1", min_width=500, min_height=500)
    
    img_16_9 = Image.new("RGB", (1600, 900), color=(255, 255, 255))
    buf_16_9 = io.BytesIO()
    img_16_9.save(buf_16_9, format="JPEG")
    img_16_9_bytes = buf_16_9.getvalue()
    
    with pytest.raises(ImageValidationError, match="does not match expected 1:1"):
        ThumbnailValidator.validate_image(img_16_9_bytes, aspect_ratio="1:1", min_width=500, min_height=500)

def test_thumbnail_validator_invalid_color_mode():
    from PIL import Image
    import io
    
    img = Image.new("L", (1280, 720), color=128)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    img_bytes = buf.getvalue()
    
    with pytest.raises(ImageValidationError, match="color mode L is not allowed"):
        ThumbnailValidator.validate_image(img_bytes, allowed_modes=["RGB", "RGBA"])

def test_thumbnail_validator_empty_bytes():
    with pytest.raises(ImageValidationError, match="Image data is empty"):
        ThumbnailValidator.validate_image(b"")

def test_thumbnail_validator_invalid_dimensions():
    import struct
    png_data = b'\x89PNG\r\n\x1a\n' + b'\x00' * 8 + struct.pack('>II', 0, 1080) + b'IEND'
    import sys
    from unittest.mock import patch
    with patch.dict(sys.modules, {'PIL': None}), pytest.raises(ImageValidationError, match="[Ii]nvalid image dimensions"):
        ThumbnailValidator.validate_image(png_data)

def test_history_manager_get_history_json_decode_error(tmp_path):
    from branding.history_manager import StatusHistoryManager
    history_file = tmp_path / "history.jsonl"
    with open(history_file, "w", encoding="utf-8") as f:
        f.write("invalid json\n\n{\"type\": \"SYSTEM_EVENT\", \"data\": {\"valid\": true}}\n")
    mgr = StatusHistoryManager(history_file=history_file)
    res = mgr.get_history()
    assert len(res) == 1
    assert res[0]["data"]["valid"] is True

def test_thumbnail_db_migration_integration(tmp_path):
    """古いスキーマのDBからマイグレーションが正常に実行され、StageBoundAgentが正常に起動できること"""
    db_file = tmp_path / "old_tasks.db"
    
    # 1. 古いテーブル構造（result, retry_count, max_retries カラムがない状態）を作成
    conn = sqlite3.connect(str(db_file))
    conn.execute("""
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            stage TEXT,
            status TEXT,
            error TEXT,
            created_at REAL,
            updated_at REAL
        )
    """)
    conn.commit()
    conn.close()
    
    # 2. StageBoundAgent を初期化（_init_db 内でマイグレーションが実行されるはず）
    agent = StageBoundAgent(
        stage_name="thumbnail",
        db_path=str(db_file),
        poll_interval=0.01
    )
    
    # 3. カラムが正しく追加されているか確認
    conn = sqlite3.connect(str(db_file))
    cursor = conn.execute("PRAGMA table_info(tasks)")
    columns = [row[1] for row in cursor.fetchall()]
    conn.close()
    
    assert "result" in columns
    assert "retry_count" in columns
    assert "max_retries" in columns

@pytest.mark.anyio
async def test_resolve_thumbnail_task_quality_validation(tmp_path, constitution_data):
    """resolve_thumbnail_taskで出力されたファイルが、解像度、アスペクト比、ファイルサイズ、Pillowロード可能性の全品質基準を満たすこと"""
    mgr = BrandingManager(constitution=constitution_data)
    task_id = "test_quality_val_task"
    
    # タスク解決を実行し、JSON出力を得る
    res_json_str = await mgr.resolve_thumbnail_task(task_id=task_id, output_dir=str(tmp_path))
    res_data = json.loads(res_json_str)
    
    output_path = Path(res_data["path"])
    
    # 1. ファイルの存在確認
    assert output_path.exists()
    
    # 2. Pillowによるロード可能・破損なしの検証
    img = Image.open(output_path)
    img.load()  # 実際にピクセルデータをメモリに読み込み、破損していないか確認
    
    # 3. 解像度の検証
    width, height = img.size
    assert width >= 1280
    assert height >= 720
    
    # 4. アスペクト比の検証 (16:9 であること)
    aspect_ratio = width / height
    expected_ratio = 16.0 / 9.0
    assert abs(aspect_ratio - expected_ratio) < 0.02
    
    # 5. ファイルサイズの検証 (4MB 未満であること)
    size_bytes = output_path.stat().st_size
    assert size_bytes < 4 * 1024 * 1024
    
    img.close()


# =========================================================================
# 新規追加: branding.history_manager.resolve_thumbnail_task の自動検証テスト
# =========================================================================

@pytest.mark.anyio
async def test_history_manager_resolve_thumbnail_task_quality_validation(tmp_path):
    """history_manager.resolve_thumbnail_task が生成画像の解像度(>=1280x720)、16:9、4MB未満、破損なし、DB保存をすべて満たすこと"""
    task_id = "history_mgr_quality_test"
    db_file = tmp_path / "history_mgr_tasks.db"
    
    # 1. タスクを実行してJSON形式の結果を取得
    res_json_str = await resolve_thumbnail_task(task_id, db_path=str(db_file), output_dir=str(tmp_path))
    res_data = json.loads(res_json_str)
    
    output_path = Path(res_data["path"])
    
    # 2. 生成ファイルの存在確認
    assert output_path.exists()
    
    # 3. Pillowによる破損なし (正常ロード可能) の検証
    with Image.open(output_path) as img:
        img.load()
        width, height = img.size
        
        # 4. 解像度の検証 (1280x720 以上であること)
        assert width >= 1280
        assert height >= 720
        
        # 5. アスペクト比の検証 (16:9 であること)
        aspect_ratio = width / height
        expected_ratio = 16.0 / 9.0
        assert abs(aspect_ratio - expected_ratio) < 0.05

    # 6. ファイルサイズの検証 (4MB 未満であること)
    size_bytes = output_path.stat().st_size
    assert size_bytes < 4 * 1024 * 1024
    
    # 7. DBに結果が正常保存・マイグレーションされていることの検証
    conn = sqlite3.connect(str(db_file))
    cursor = conn.execute("SELECT path, width, height, size_bytes FROM thumbnail_results WHERE task_id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    assert Path(row[0]) == output_path
    assert row[1] == width
    assert row[2] == height
    assert row[3] == size_bytes

@pytest.mark.anyio
async def test_history_manager_stage_bound_agent_integration(tmp_path):
    """StageBoundAgent に history_manager.resolve_thumbnail_task を登録し、正常完了およびDB保存できること"""
    db_file = tmp_path / "stage_bound_history.db"
    agent = StageBoundAgent(
        stage_name="thumbnail",
        db_path=str(db_file),
        poll_interval=0.01
    )
    
    task_id = "task_history_agent_success"
    await agent.register_task(
        task_id,
        initial_status="READY",
        max_retries=2
    )
    
    async def process_task(tid):
        return await resolve_thumbnail_task(tid, task_id=tid, db_path=str(db_file), output_dir=str(tmp_path))
        
    await agent.start(process_task)
    
    # 完了待機
    for _ in range(50):
        status = await agent.get_task_status(task_id)
        if status == "COMPLETED":
            break
        await asyncio.sleep(0.05)
        
    status = await agent.get_task_status(task_id)
    assert status == "COMPLETED"
    
    # 結果の検証
    conn = sqlite3.connect(str(db_file))
    cursor = conn.execute("SELECT result, error FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    assert row[1] is None or row[1] == ""
    result_json = json.loads(row[0])
    assert result_json["width"] >= 1280
    assert result_json["height"] >= 720
    assert Path(result_json["path"]).exists()
    
    await agent.stop()

@pytest.mark.anyio
async def test_history_manager_stage_bound_agent_retry_on_failure(tmp_path):
    """不正なパスにより history_manager.resolve_thumbnail_task が失敗した場合に自動リトライが働き最終的にFAILEDになること"""
    db_file = tmp_path / "stage_bound_history_retry.db"
    agent = StageBoundAgent(
        stage_name="thumbnail",
        db_path=str(db_file),
        poll_interval=0.01
    )
    
    task_id = "task_history_agent_fail"
    await agent.register_task(
        task_id,
        initial_status="READY",
        max_retries=2
    )
    
    async def process_task(tid):
        return await resolve_thumbnail_task(tid, task_id=tid, db_path=str(db_file), output_dir=":/invalid_path/\\/?*")
        
    await agent.start(process_task)
    
    # 失敗待機
    for _ in range(50):
        status = await agent.get_task_status(task_id)
        if status == "FAILED":
            break
        await asyncio.sleep(0.05)
        
    status = await agent.get_task_status(task_id)
    assert status == "FAILED"
    
    # リトライ回数とエラーの検証
    conn = sqlite3.connect(str(db_file))
    cursor = conn.execute("SELECT retry_count, error FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    assert row[0] == 2  # max_retries = 2
    assert row[1] is not None and len(row[1]) > 0
    
    await agent.stop()

# =========================================================================
# 新規追加: BrandingManager カバレッジ改善テスト
# =========================================================================
from unittest.mock import patch, MagicMock
from branding.history_manager import EventType
from branding_manager import BrandingManager

@pytest.fixture
def mock_branding_paths(tmp_path):
    # テスト用の一時パスを作成
    const_path = tmp_path / "constitution.json"
    strat_path = tmp_path / "strategy.json"
    user_path = tmp_path / "user_model.json"
    evo_path = tmp_path / "evolution_log.json"
    sub_path = tmp_path / "segments_a_plus_plus.json"
    
    # ダミーデータを書き込む
    const_data = {
        "channel_name": "Test Channel",
        "target_audience": "Tech Enthusiasts",
        "brand_personality": {
            "tone": "Informative",
            "keywords": ["tech", "future"]
        },
        "visual_identity": {"style_prompt": "Neon Cyberpunk"},
        "evolution_vision": "Initial Vision"
    }
    strat_data = {
        "current_phase": "Phase 1",
        "current_mission": {
            "focus": "Views",
            "target_value": 1000,
            "advice": "Keep editing"
        }
    }
    user_data = {
        "name": "Test Studio",
        "profiles": {
            "admin": {
                "name": "Admin User",
                "ranks": {
                    "tech_rank": {"level": "Novice", "xp": 10}
                }
            },
            "owner": {
                "name": "Owner User",
                "ranks": {
                    "biz_rank": {"level": "Novice", "xp": 20}
                }
            }
        },
        "collaborative_settings": {
            "auto_pilot_ratio": 0.9
        }
    }
    sub_data = [
        {"text": "Hello world", "start": 0.0, "end": 2.0}
    ]
    
    with open(const_path, "w", encoding="utf-8") as f:
        json.dump(const_data, f)
    with open(strat_path, "w", encoding="utf-8") as f:
        json.dump(strat_data, f)
    with open(user_path, "w", encoding="utf-8") as f:
        json.dump(user_data, f)
    with open(sub_path, "w", encoding="utf-8") as f:
        json.dump(sub_data, f)
        
    with patch("branding_manager.CONSTITUTION_PATH", str(const_path)), \
         patch("branding_manager.STRATEGY_PATH", str(strat_path)), \
         patch("branding_manager.USER_MODEL_PATH", str(user_path)), \
         patch("branding_manager.SUBTITLES_PATH", str(sub_path)), \
         patch("branding_manager.BRANDING_DIR", str(tmp_path)):
        yield {
            "constitution": const_path,
            "strategy": strat_path,
            "user_model": user_path,
            "evolution_log": evo_path,
            "subtitles": sub_path,
            "tmp_dir": tmp_path
        }

@pytest.fixture
def branding_mgr(mock_branding_paths):
    return BrandingManager()

# --- JSON 例外ハンドリングのテスト ---
def test_load_json_exceptions(tmp_path):
    mgr = BrandingManager()
    
    # 1. FileNotFoundError
    res = mgr._load_json(tmp_path / "nonexistent.json")
    assert res == {}
    
    # 2. JSONDecodeError
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("invalid json", encoding="utf-8")
    res = mgr._load_json(bad_json)
    assert res == {}
    
    # 3. PermissionError
    with patch("builtins.open", side_effect=PermissionError("Permission denied")):
        res = mgr._load_json(bad_json)
        assert res == {}

def test_save_json_exceptions(tmp_path):
    mgr = BrandingManager()
    target_path = tmp_path / "target.json"
    
    # 1. PermissionError
    with patch("builtins.open", side_effect=PermissionError("Permission denied")):
        mgr._save_json(target_path, {"test": 123})
        
    # 2. TypeError (非シリアライズオブジェクト)
    mgr._save_json(target_path, {"test": object()})
    
    # 3. OSError
    with patch("builtins.open", side_effect=OSError("OS Error")):
        mgr._save_json(target_path, {"test": 123})


# --- コンテキスト構築のテスト ---
def test_get_context_block(branding_mgr):
    context = branding_mgr.get_context_block()
    assert "BRAND CONSTITUTION" in context
    assert "Test Channel" in context
    assert "Tech Enthusiasts" in context
    assert "STRATEGIC MISSION" in context
    assert "Trinity 2.0" in context

def test_get_philosophies_context(branding_mgr, mock_branding_paths):
    # 1. 進化ログがない初期状態
    context = branding_mgr.get_philosophies_context()
    assert "初心者からスタート" in context
    
    # 2. 進化ログがある場合
    evo_log_path = mock_branding_paths["evolution_log"]
    evo_data = {
        "integrated_philosophy": "究極の映像美",
        "philosophies": [
            {"philosophy": "常に新しさを求める", "timestamp": "2026-07-01T12:00:00Z"},
            {"philosophy": "視聴者に寄り添う", "timestamp": "2026-07-02T12:00:00Z"}
        ],
        "entries": [
            {"summary": "音質の重要性を学んだ"}
        ]
    }
    with open(evo_log_path, "w", encoding="utf-8") as f:
        json.dump(evo_data, f)
        
    context = branding_mgr.get_philosophies_context()
    assert "究極の映像美" in context
    assert "常に新しさを求める" in context
    assert "音質の重要性を学んだ" in context

def test_get_deep_context(branding_mgr):
    with patch("agents.context_resolver.ContextResolver.get_deep_context_block", return_value="Deep Context Mock") as mock_resolver:
        res = branding_mgr.get_deep_context()
        assert res == "Deep Context Mock"


# --- ユーザーランク更新と自動化レベル再計算のテスト ---
def test_update_user_rank_levels(branding_mgr):
    # 1. 初期化時の確認
    assert branding_mgr.user_model["profiles"]["admin"]["ranks"]["tech_rank"]["xp"] == 10
    
    # 2. tech_rank XPを境界値付近まで更新してレベルの切り替えを検証
    # Novice (< 100) -> Intermediate (>= 100)
    with patch("branding.history_manager.history_manager.log_event") as mock_log:
        branding_mgr.update_user_rank("tech_rank", amount=90) # 合計 100 XP
        assert branding_mgr.user_model["profiles"]["admin"]["ranks"]["tech_rank"]["xp"] == 100
        assert branding_mgr.user_model["profiles"]["admin"]["ranks"]["tech_rank"]["level"] == "Editor (Intermediate)"
        assert branding_mgr.user_model["collaborative_settings"]["auto_pilot_ratio"] == 0.5
        assert mock_log.call_count == 2
        
    # 3. Intermediate -> Master (>= 500)
    branding_mgr.update_user_rank("tech_rank", amount=400) # 合計 500 XP
    assert branding_mgr.user_model["profiles"]["admin"]["ranks"]["tech_rank"]["level"] == "Director (Master)"
    assert branding_mgr.user_model["collaborative_settings"]["auto_pilot_ratio"] == 0.1
    
    # 4. biz_rank の更新
    branding_mgr.update_user_rank("biz_rank", amount=50)
    assert branding_mgr.user_model["profiles"]["owner"]["ranks"]["biz_rank"]["xp"] == 70

def test_update_user_rank_corrupted_model(branding_mgr):
    branding_mgr.user_model = None
    branding_mgr.update_user_rank("tech_rank", amount=10)
    assert branding_mgr.user_model["profiles"]["admin"]["ranks"]["tech_rank"]["xp"] == 10


# --- 自己進化ロジックのテスト ---
def test_evolve_constitution(branding_mgr):
    success_event = {
        "type": "Thumbnail CTR",
        "value": "12.5%",
        "keyword": "neon"
    }
    branding_mgr.evolve_constitution(success_event)
    assert "Success: Thumbnail CTR - 12.5%" in branding_mgr.constitution["evolution_vision"]
    assert "neon" in branding_mgr.constitution["brand_personality"]["keywords"]
    
    # 例外系: constitution が dict ではない場合
    branding_mgr.constitution = None
    branding_mgr.evolve_constitution(success_event)
    assert isinstance(branding_mgr.constitution, dict)

def test_sync_decisions_to_constitution(branding_mgr):
    # 1. 正常系
    mock_trigger_svc = MagicMock()
    mock_trigger_svc.evaluate_triggers.return_value = {
        "fired": [{"action": "append", "detail": "Add keyword 'retro'"}]
    }
    with patch("services.evolution_trigger_service.EvolutionTriggerService", return_value=mock_trigger_svc):
        res = branding_mgr.sync_decisions_to_constitution()
        assert res["synced"] is True
        assert "append: Add keyword 'retro'" in res["changes"]
        
    # 2. 例外系 (ImportError)
    with patch("services.evolution_trigger_service.EvolutionTriggerService", side_effect=ImportError("No module")):
        res = branding_mgr.sync_decisions_to_constitution()
        assert res["synced"] is False
        assert "No module" in res["error"]

def test_auto_evolve_all(branding_mgr):
    branding_mgr.sync_decisions_to_constitution = MagicMock(return_value={"synced": True})
    
    mock_decision_logger = MagicMock()
    mock_decision_logger.sync_to_soul_narrative.return_value = {"synced": True}
    
    with patch("branding_manager.decision_logger", mock_decision_logger):
        # 1. 哲学の統合が行われない条件 (哲学件数が 10 の倍数でない)
        branding_mgr.get_evolution_log = MagicMock(return_value={"philosophies": ["a", "b"]})
        res = branding_mgr.auto_evolve_all()
        assert res["decision_sync"]["synced"] is True
        assert res["soul_narrative_sync"]["synced"] is True
        assert res["philosophy_check"]["integrated"] is False
        
        # 2. 哲学の統合が行われる条件 (哲学件数が 10)
        branding_mgr.get_evolution_log = MagicMock(return_value={"philosophies": ["a"] * 10})
        branding_mgr._integrate_philosophies = MagicMock()
        res = branding_mgr.auto_evolve_all()
        assert res["philosophy_check"]["integrated"] is True
        branding_mgr._integrate_philosophies.assert_called_once()


# --- アナリティクス連携とレポート取り込みのテスト ---
def test_process_analytics_update(branding_mgr):
    mock_analytics = MagicMock()
    mock_analytics.get_my_stats.return_value = {"subscribers": 100, "total_views": 5000}
    mock_analytics.scout_rivals.return_value = [{"name": "Rival A"}]
    mock_analytics.calculate_gap.return_value = ["Gain 500 views"]
    
    with patch("branding.analytics_manager.analytics_manager", mock_analytics):
        res = branding_mgr.process_analytics_update()
        assert res["stats"]["total_views"] == 5000
        assert res["biz_xp"] == 50 
        assert branding_mgr.user_model["profiles"]["owner"]["ranks"]["biz_rank"]["xp"] == 50
        assert branding_mgr.user_model["external_status"]["rivals"] == [{"name": "Rival A"}]

def test_update_user_model_and_strategy(branding_mgr):
    # 1. update_user_model
    branding_mgr.user_model = {"ai_notes": "Initial"}
    branding_mgr.update_user_model("New Note")
    assert "Initial New Note" in branding_mgr.user_model["ai_notes"]
    
    # 2. update_strategy
    branding_mgr.strategy = {"current_phase": "P1", "current_mission": {"advice": "none"}}
    branding_mgr.update_strategy(phase="P2", advise="New Advice")
    assert branding_mgr.strategy["current_phase"] == "P2"
    assert branding_mgr.strategy["current_mission"]["advice"] == "New Advice"

def test_ingest_report(branding_mgr):
    report_data = {
        "xp_grant": 30,
        "agenda_proposal": "Next Steps"
    }
    branding_mgr.log_evolution = MagicMock()
    res = branding_mgr.ingest_report(report_data)
    assert res["status"] == "success"
    assert res["xp_granted"] == 30
    assert res["agenda"] == "Next Steps"
    branding_mgr.log_evolution.assert_called_once_with(report_data)


# --- AI成長ナラティブ生成と過去哲学統合のテスト (Gemini Mock) ---
def test_log_evolution(branding_mgr, mock_branding_paths):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "summary": "成長した",
        "insight": "より深いこだわりを発見した",
        "stat_changes": ["Tech XP +30"],
        "new_philosophy_hint": "常に挑戦する"
    })
    mock_client.models.generate_content.return_value = mock_response
    
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client), \
         patch("model_registry.get_model", return_value="gemini-mock"):
        
        # 1. 通常処理と哲学の累積
        session_data = {"result": "success", "xp_grant": 30}
        entry = branding_mgr.log_evolution(session_data)
        
        assert entry["summary"] == "成長した"
        evo_log = branding_mgr.get_evolution_log()
        assert len(evo_log["entries"]) == 1
        assert evo_log["philosophies"][0]["philosophy"] == "常に挑戦する"
        
        # 2. 10件ごとの統合トリガー
        branding_mgr._integrate_philosophies = MagicMock()
        evo_log["philosophies"] = [{"philosophy": f"ph_{i}"} for i in range(9)]
        branding_mgr.save_evolution_log(evo_log)
        
        branding_mgr.log_evolution(session_data)
        branding_mgr._integrate_philosophies.assert_called_once()

def test_integrate_philosophies(branding_mgr):
    # 1. 哲学が少ない場合は実行しない
    evo_log = {"philosophies": ["a", "b"]}
    branding_mgr._integrate_philosophies(evo_log)
    assert "integrated_philosophy" not in evo_log
    
    # 2. 哲学が3件以上ある場合、Geminiを呼び出して統合
    evo_log = {"philosophies": [{"philosophy": "a"}, {"philosophy": "b"}, {"philosophy": "c"}]}
    
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "統合された大いなる哲学"
    mock_client.models.generate_content.return_value = mock_response
    
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client), \
         patch("model_registry.get_model", return_value="gemini-mock"):
        branding_mgr._integrate_philosophies(evo_log)
        assert evo_log["integrated_philosophy"] == "統合された大いなる哲学"
        assert len(evo_log["integration_history"]) == 1
        assert evo_log["integration_history"][0]["source_count"] == 3
