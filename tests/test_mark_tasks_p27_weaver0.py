import io
import os
import json
import sqlite3
import pytest
import runpy
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock
import PIL
from PIL import Image

from backend.agents.orchestration import mark_tasks_p27_weaver0

# テスト用画像生成ヘルパー
def create_test_image_bytes(width, height, format="PNG"):
    img = Image.new("RGB", (width, height), color="red")
    buf = io.BytesIO()
    img.save(buf, format=format)
    return buf.getvalue()

# ==========================================
# verify_thumbnail_quality 関数のテスト
# ==========================================

def test_verify_thumbnail_quality_bytes_success(monkeypatch):
    mock_emit_warning = MagicMock()
    monkeypatch.setattr("backend.agents.orchestration.mark_tasks_p27_weaver0.emit_warning", mock_emit_warning)

    img_bytes = create_test_image_bytes(1280, 720)
    result = mark_tasks_p27_weaver0.verify_thumbnail_quality(img_bytes)
    
    assert result["width"] == 1280
    assert result["height"] == 720
    assert result["size_bytes"] == len(img_bytes)
    assert result["valid"] is True
    mock_emit_warning.assert_not_called()

def test_verify_thumbnail_quality_bytes_corrupted(monkeypatch):
    mock_emit_warning = MagicMock()
    monkeypatch.setattr("backend.agents.orchestration.mark_tasks_p27_weaver0.emit_warning", mock_emit_warning)

    corrupted_bytes = b"not an image"
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        mark_tasks_p27_weaver0.verify_thumbnail_quality(corrupted_bytes)
        
    mock_emit_warning.assert_called_once()
    assert "Corrupted image bytes" in mock_emit_warning.call_args[0][1]

def test_verify_thumbnail_quality_file_not_found(monkeypatch, tmp_path):
    mock_emit_warning = MagicMock()
    monkeypatch.setattr("backend.agents.orchestration.mark_tasks_p27_weaver0.emit_warning", mock_emit_warning)

    non_existent_file = tmp_path / "does_not_exist.png"
    with pytest.raises(FileNotFoundError, match="Thumbnail file not found"):
        mark_tasks_p27_weaver0.verify_thumbnail_quality(non_existent_file)
        
    mock_emit_warning.assert_called_once()
    assert "File not found" in mock_emit_warning.call_args[0][1]

def test_verify_thumbnail_quality_file_success(monkeypatch, tmp_path):
    mock_emit_warning = MagicMock()
    monkeypatch.setattr("backend.agents.orchestration.mark_tasks_p27_weaver0.emit_warning", mock_emit_warning)

    img_bytes = create_test_image_bytes(1920, 1080)
    img_file = tmp_path / "valid.png"
    img_file.write_bytes(img_bytes)

    result = mark_tasks_p27_weaver0.verify_thumbnail_quality(img_file)
    
    assert result["width"] == 1920
    assert result["height"] == 1080
    assert result["size_bytes"] == len(img_bytes)
    assert result["valid"] is True
    mock_emit_warning.assert_not_called()

def test_verify_thumbnail_quality_file_corrupted(monkeypatch, tmp_path):
    mock_emit_warning = MagicMock()
    monkeypatch.setattr("backend.agents.orchestration.mark_tasks_p27_weaver0.emit_warning", mock_emit_warning)

    corrupted_file = tmp_path / "corrupted.png"
    corrupted_file.write_bytes(b"bad image file")

    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        mark_tasks_p27_weaver0.verify_thumbnail_quality(corrupted_file)
        
    mock_emit_warning.assert_called_once()
    assert "Corrupted image file" in mock_emit_warning.call_args[0][1]

def test_verify_thumbnail_quality_image_size_error(monkeypatch):
    mock_emit_warning = MagicMock()
    monkeypatch.setattr("backend.agents.orchestration.mark_tasks_p27_weaver0.emit_warning", mock_emit_warning)

    img_bytes = create_test_image_bytes(1280, 720)
    
    # img.size アクセス時に例外を投げさせる
    with patch("PIL.Image.open") as mock_open:
        mock_img = MagicMock()
        type(mock_img).size = PropertyMock(side_effect=OSError("Pillow size read error"))
        mock_open.return_value = mock_img

        with pytest.raises(ValueError, match="Failed to load image for resolution check"):
            mark_tasks_p27_weaver0.verify_thumbnail_quality(img_bytes)

    mock_emit_warning.assert_called_once()
    assert "Failed to get image size" in mock_emit_warning.call_args[0][1]

def test_verify_thumbnail_quality_file_size_exceeded(monkeypatch, tmp_path):
    mock_emit_warning = MagicMock()
    monkeypatch.setattr("backend.agents.orchestration.mark_tasks_p27_weaver0.emit_warning", mock_emit_warning)

    img_bytes = create_test_image_bytes(1280, 720)
    img_file = tmp_path / "large.png"
    img_file.write_bytes(img_bytes)

    # 4MB以上のサイズを偽装する
    with patch.object(Path, "stat") as mock_stat:
        mock_stat.return_value.st_size = 4 * 1024 * 1024 + 1
        
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            mark_tasks_p27_weaver0.verify_thumbnail_quality(img_file)
            
    mock_emit_warning.assert_called_once()
    assert "File size exceeds 4MB limit" in mock_emit_warning.call_args[0][1]

def test_verify_thumbnail_quality_resolution_too_low(monkeypatch):
    mock_emit_warning = MagicMock()
    monkeypatch.setattr("backend.agents.orchestration.mark_tasks_p27_weaver0.emit_warning", mock_emit_warning)

    # 1280x720 未満 (例: 1279x720)
    img_bytes = create_test_image_bytes(1279, 720)
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        mark_tasks_p27_weaver0.verify_thumbnail_quality(img_bytes)
        
    mock_emit_warning.assert_called_once()
    assert "Resolution must be at least 1280x720" in mock_emit_warning.call_args[0][1]

def test_verify_thumbnail_quality_aspect_ratio_invalid(monkeypatch):
    mock_emit_warning = MagicMock()
    monkeypatch.setattr("backend.agents.orchestration.mark_tasks_p27_weaver0.emit_warning", mock_emit_warning)

    # アスペクト比が 16:9 ではない (例: 1280x800)
    img_bytes = create_test_image_bytes(1280, 800)
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        mark_tasks_p27_weaver0.verify_thumbnail_quality(img_bytes)
        
    mock_emit_warning.assert_called_once()
    assert "Aspect ratio must be 16:9" in mock_emit_warning.call_args[0][1]


# ==========================================
# run_thumbnail_stage_task 関数のテスト
# ==========================================

@pytest.fixture
def mock_project_environment(tmp_path):
    # mark_tasks_p27_weaver0.__file__ を書き換えて、一時ディレクトリを作業ルートにする
    original_file = mark_tasks_p27_weaver0.__file__
    
    # 疑似ファイルパスを作成 (parents[3] が tmp_path になるようにする)
    # tmp_path / "backend" / "agents" / "orchestration" / "mark_tasks_p27_weaver0.py"
    fake_path = tmp_path / "backend" / "agents" / "orchestration" / "mark_tasks_p27_weaver0.py"
    fake_path.parent.mkdir(parents=True, exist_ok=True)
    
    mark_tasks_p27_weaver0.__file__ = str(fake_path)
    yield tmp_path
    
    # 元に戻す
    mark_tasks_p27_weaver0.__file__ = original_file

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_success(monkeypatch, mock_project_environment):
    mock_emit_critical = MagicMock()
    monkeypatch.setattr("backend.agents.orchestration.mark_tasks_p27_weaver0.emit_critical", mock_emit_critical)

    task_id = "test_task_success_999"
    # ファイルベースのDBを使用 (メモリ内DBだとコネクション切断で消えるため)
    db_file = mock_project_environment / "test.db"
    db_path = str(db_file)

    result_json = await mark_tasks_p27_weaver0.run_thumbnail_stage_task(task_id, db_path=db_path)
    
    # 結果の検証
    result = json.loads(result_json)
    assert result["width"] == 1280
    assert result["height"] == 720
    assert result["valid"] is True
    assert result["size_bytes"] > 0
    
    # ファイルの存在確認
    output_file = mock_project_environment / "temp_thumbnails" / f"{task_id}.png"
    assert output_file.exists()
    
    # DBの確認
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM thumbnail_results WHERE task_id=?", (task_id,))
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == task_id
    assert row[1] == str(output_file)
    assert row[2] == 1280
    assert row[3] == 720
    conn.close()

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_old_pillow(monkeypatch, mock_project_environment):
    task_id = "test_task_old_pillow"
    db_file = mock_project_environment / "test_old_pillow.db"
    db_path = str(db_file)
    
    # draw.textbbox が AttributeError を起こすようにモックする
    # Pillow 10 未満のフォールバック (draw.textsize) のテスト
    from PIL import ImageDraw
    original_draw = ImageDraw.ImageDraw
    
    class MockImageDraw(original_draw):
        def textbbox(self, *args, **kwargs):
            raise AttributeError("textbbox not supported")
            
        def textsize(self, text, font=None, **kwargs):
            return (150, 40)
            
    with patch("PIL.ImageDraw.Draw", return_value=MockImageDraw(Image.new("RGB", (10, 10)))):
        result_json = await mark_tasks_p27_weaver0.run_thumbnail_stage_task(task_id, db_path=db_path)
        result = json.loads(result_json)
        assert result["valid"] is True

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_font_fallback(monkeypatch, mock_project_environment):
    # truetypeモック化: 引数が文字列 (フォントファイルパス) の場合のみ OSError を発生させる
    original_truetype = PIL.ImageFont.truetype
    
    def mock_truetype_func(*args, **kwargs):
        if args and isinstance(args[0], str):
            raise OSError("Font load error")
        return original_truetype(*args, **kwargs)
        
    monkeypatch.setattr("PIL.ImageFont.truetype", mock_truetype_func)
    
    # load_default は正常なデフォルトフォントを返すようにする (truetypeモックがBytesIOで動作可能なので本物の load_default が動く)
    # よって、load_default の呼び出しをスパイする
    mock_load_default = MagicMock(side_effect=PIL.ImageFont.load_default)
    monkeypatch.setattr("PIL.ImageFont.load_default", mock_load_default)
    
    task_id = "test_task_font_fallback"
    db_file = mock_project_environment / "test_font_fallback.db"
    db_path = str(db_file)
    
    result_json = await mark_tasks_p27_weaver0.run_thumbnail_stage_task(task_id, db_path=db_path)
    result = json.loads(result_json)
    assert result["valid"] is True
    
    mock_load_default.assert_called_once()

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_value_error(monkeypatch, mock_project_environment):
    mock_emit_critical = MagicMock()
    monkeypatch.setattr("backend.agents.orchestration.mark_tasks_p27_weaver0.emit_critical", mock_emit_critical)

    task_id = "test_task_value_error"
    db_file = mock_project_environment / "test_val_err.db"
    db_path = str(db_file)

    # verify_thumbnail_quality が例外を投げるようにモックする
    with patch("backend.agents.orchestration.mark_tasks_p27_weaver0.verify_thumbnail_quality", side_effect=ValueError("Quality verification failed")):
        with pytest.raises(ValueError, match="Quality verification failed"):
            await mark_tasks_p27_weaver0.run_thumbnail_stage_task(task_id, db_path=db_path)

    mock_emit_critical.assert_called_once()
    assert "Thumbnail task failed for task" in mock_emit_critical.call_args[0][1]

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_sqlite_error(monkeypatch, mock_project_environment):
    mock_emit_critical = MagicMock()
    monkeypatch.setattr("backend.agents.orchestration.mark_tasks_p27_weaver0.emit_critical", mock_emit_critical)

    task_id = "test_task_sqlite_error"
    
    # DB接続で sqlite3.Error を投げるようにモックする
    with patch("sqlite3.connect", side_effect=sqlite3.Error("Connection refused")):
        with pytest.raises(sqlite3.Error, match="Connection refused"):
            await mark_tasks_p27_weaver0.run_thumbnail_stage_task(task_id, db_path=":memory:")

    mock_emit_critical.assert_called_once()
    assert "Thumbnail task failed for task" in mock_emit_critical.call_args[0][1]


# ==========================================
# main 関数のテスト
# ==========================================

def test_main_success(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"status": "ok"}
    
    with patch("backend.agents.orchestration.mark_tasks_p27_weaver0.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            mark_tasks_p27_weaver0.main()
            
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("ce05d36d-f2c8-452b-8ea9-9053a1e718a0")
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    mock_hub_instance.mark_task_done.assert_called_once_with(
        "T-batch_86850c-thumbnail-001",
        "pass",
        {
            "message": "Phase 27 のサムネイル生成/画像処理ロジックを改善し、StageBoundAgent連携および品質検証をパス。",
            "changed_files": [
                "backend/agents/orchestration/mark_tasks_p27_weaver0.py",
                "backend/agents/orchestration/mark_task_helper.py"
            ]
        }
    )
    mock_hub_instance.generate_flash_status.assert_called_once()
    
    captured = capsys.readouterr()
    assert "TASK_MARKED_DONE" in captured.out
    assert "FLASH_STATUS" in captured.out
    assert '{"status": "ok"}' in captured.out

def test_main_as_script(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"status": "script_ok"}
    
    script_path = os.path.abspath("backend/agents/orchestration/mark_tasks_p27_weaver0.py")
    
    with patch("backend.agents.orchestration.mark_tasks_p27_weaver0.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            runpy.run_path(script_path, run_name="__main__")
            
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("ce05d36d-f2c8-452b-8ea9-9053a1e718a0")
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    mock_hub_instance.mark_task_done.assert_called_once_with(
        "T-batch_86850c-thumbnail-001",
        "pass",
        {
            "message": "Phase 27 のサムネイル生成/画像処理ロジックを改善し、StageBoundAgent連携および品質検証をパス。",
            "changed_files": [
                "backend/agents/orchestration/mark_tasks_p27_weaver0.py",
                "backend/agents/orchestration/mark_task_helper.py"
            ]
        }
    )
    mock_hub_instance.generate_flash_status.assert_called_once()
    
    captured = capsys.readouterr()
    assert "TASK_MARKED_DONE" in captured.out
    assert "FLASH_STATUS" in captured.out
    assert '{"status": "script_ok"}' in captured.out
