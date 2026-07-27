# -*- coding: utf-8 -*-
import sys
import os
import io
import json
import sqlite3
import asyncio
import time
import pytest
from pathlib import Path
from PIL import Image, ImageDraw
from unittest.mock import patch, MagicMock, PropertyMock

# backend ディレクトリを sys.path に追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from agents.orchestration.mark_tasks_p27_weaver0 import (
    verify_thumbnail_quality,
    run_thumbnail_stage_task
)
from agents.stage_bound_agent import StageBoundAgent

@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_stage_weaver0.db"
    return str(db_file)

@pytest.fixture
def valid_image_bytes():
    # 1280x720, 16:9 の正常な画像をメモリ上に生成
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def test_verify_thumbnail_quality_success(valid_image_bytes):
    """正常系: 1280x720, 16:9, 小サイズで正常ロード可能なバイト列"""
    res = verify_thumbnail_quality(valid_image_bytes)
    assert res["valid"] is True
    assert res["width"] == 1280
    assert res["height"] == 720

def test_verify_thumbnail_quality_file_success(tmp_path):
    """正常系: ファイルパス指定"""
    img = Image.new("RGB", (1920, 1080), color=(100, 100, 100))
    path = tmp_path / "valid_image.png"
    img.save(path, format="PNG")
    
    res = verify_thumbnail_quality(path)
    assert res["valid"] is True
    assert res["width"] == 1920
    assert res["height"] == 1080

def test_verify_thumbnail_quality_corrupted():
    """異常系: 破損したバイト列"""
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        verify_thumbnail_quality(b"invalid corrupted bytes")

def test_verify_thumbnail_quality_file_not_found():
    """異常系: 存在しないファイルパス"""
    with pytest.raises(FileNotFoundError, match="Thumbnail file not found"):
        verify_thumbnail_quality("non_existent_file_path_123.jpg")

def test_verify_thumbnail_quality_resolution_fail(tmp_path):
    """異常系: 低解像度 (1280x720 未満)"""
    img = Image.new("RGB", (1000, 562), color=(100, 100, 100)) # 約16:9だが低解像度
    path = tmp_path / "low_res.png"
    img.save(path, format="PNG")
    
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        verify_thumbnail_quality(path)

def test_verify_thumbnail_quality_aspect_ratio_fail(tmp_path):
    """異常系: アスペクト比が 16:9 ではない"""
    img = Image.new("RGB", (1280, 1000), color=(100, 100, 100)) # 1280x720以上だが比率が違う
    path = tmp_path / "wrong_aspect.png"
    img.save(path, format="PNG")
    
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        verify_thumbnail_quality(path)

def test_verify_thumbnail_quality_size_fail(tmp_path):
    """異常系: ファイルサイズが 4MB 以上"""
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    path = tmp_path / "large_file.png"
    img.save(path, format="PNG")
    
    with patch("pathlib.Path.stat") as mock_stat:
        mock_meta = MagicMock()
        mock_meta.st_size = 4 * 1024 * 1024 + 10  # 4MB超
        mock_stat.return_value = mock_meta
        
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            verify_thumbnail_quality(path)

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_success(temp_db):
    """run_thumbnail_stage_task が正常終了し、DBに結果が正しく書き込まれ、プレミアム品質画像が生成されることを検証"""
    res_str = await run_thumbnail_stage_task("task_weaver0_001", db_path=temp_db)
    res = json.loads(res_str)
    assert res["valid"] is True
    assert res["width"] == 1280
    assert res["height"] == 720
    
    # 生成された画像の存在と内容の検証 (グラデーション背景)
    project_root = Path(__file__).resolve().parents[2]
    image_path = project_root / "temp_thumbnails" / "task_weaver0_001.png"
    assert image_path.exists()
    
    # 画像をロードして、グラデーション(単一色でないこと)を検証
    img = Image.open(image_path)
    # 上部ピクセルと下部ピクセルの色がグラデーションにより異なるはず
    color_top = img.getpixel((10, 10))
    color_bottom = img.getpixel((10, 710))
    assert color_top != color_bottom, "画像背景がグラデーションになっていません（単一色です）"
    
    # DB連携と結果保存の検証
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM thumbnail_results WHERE task_id = 'task_weaver0_001'")
    row = cursor.fetchone()
    assert row is not None
    assert "task_weaver0_001" in row[0]
    assert 1280 == row[2]
    assert 720 == row[3]
    conn.close()

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_failure(temp_db):
    """品質検証で失敗した際、emit_critical が呼ばれ例外が送出されることを検証"""
    with patch("agents.orchestration.mark_tasks_p27_weaver0.verify_thumbnail_quality", side_effect=ValueError("Mock Quality Error")),          patch("agents.orchestration.mark_tasks_p27_weaver0.emit_critical") as mock_emit_critical:
          
          with pytest.raises(ValueError, match="Mock Quality Error"):
              await run_thumbnail_stage_task("task_fail", db_path=temp_db)
          
          mock_emit_critical.assert_called_once_with("thumbnail", "Thumbnail task failed for task task_fail: Mock Quality Error")

@pytest.mark.asyncio
async def test_stage_bound_agent_integration(temp_db):
    """StageBoundAgent にタスクを登録して自動リトライが動作することを検証"""
    agent = StageBoundAgent(
        stage_name="thumbnail",
        db_path=temp_db,
        poll_interval=0.01
    )
    
    # READYタスクを登録 (max_retries=2)
    await agent.register_task("task_retry_test", initial_status="READY", max_retries=2)
    
    # 最初の2回失敗し、3回目で成功するようなモック
    call_count = 0
    async def mock_process(task_id):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ValueError(f"Temporary Error {call_count}")
        return "SUCCESS_DATA"

    # エージェント開始
    await agent.start(mock_process)
    
    # 完了するかタイムアウトするまで待機
    start_time = time.time()
    while time.time() - start_time < 3.0:
        status = await agent.get_task_status("task_retry_test")
        if status == "COMPLETED":
            break
        await asyncio.sleep(0.05)
        
    await agent.stop()
    
    # 3回目でCOMPLETEDになったことを確認
    assert call_count == 3
    status = await agent.get_task_status("task_retry_test")
    assert status == "COMPLETED"
    
    # 最終的な結果の取得
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("SELECT * FROM tasks WHERE id = 'task_retry_test'")
    row = dict(cursor.fetchone())
    assert row["retry_count"] == 2
    assert row["result"] == "SUCCESS_DATA"
    conn.close()


def test_verify_thumbnail_quality_file_load_corrupted(tmp_path):
    """異常系: ファイルオープン時の破損エラー (PIL.UnidentifiedImageError)"""
    path = tmp_path / "corrupted.png"
    path.write_bytes(b"invalid data")
    
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        verify_thumbnail_quality(path)


def test_verify_thumbnail_quality_size_access_fail(tmp_path):
    """異常系: 画像のサイズ取得エラー"""
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    path = tmp_path / "test_size_fail.png"
    img.save(path, format="PNG")

    with patch("PIL.Image.open") as mock_open:
        mock_img = MagicMock()
        type(mock_img).size = PropertyMock(side_effect=ValueError("Mock size error"))
        mock_open.return_value = mock_img

        with pytest.raises(ValueError, match="Failed to load image for resolution check"):
            verify_thumbnail_quality(path)


@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_font_truetype_error(temp_db):
    """正常系/フォールバック: フォントファイル読み込み時にOSErrorが発生し、デフォルトフォントにフォールバックする"""
    from PIL import ImageFont
    original_truetype = ImageFont.truetype
    
    def mock_truetype(font=None, *args, **kwargs):
        if font is not None and any(p in str(font) for p in ["Windows", "Fonts", "share/fonts", "Library/Fonts"]):
            raise OSError("Mock Font Error")
        return original_truetype(font, *args, **kwargs)

    with patch("os.path.exists", return_value=True),          patch("PIL.ImageFont.truetype", side_effect=mock_truetype):
        res_str = await run_thumbnail_stage_task("task_font_err", db_path=temp_db)
        res = json.loads(res_str)
        assert res["valid"] is True


@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_no_fonts_available(temp_db):
    """正常系/フォールバック: 利用可能なフォントファイルが無く、デフォルトフォントにフォールバックする"""
    with patch("os.path.exists", return_value=False):
        res_str = await run_thumbnail_stage_task("task_no_font", db_path=temp_db)
        res = json.loads(res_str)
        assert res["valid"] is True


@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_old_pillow_fallback(temp_db):
    """正常系/フォールバック: textbbox が無く、古いPillowの textsize にフォールバックする"""
    with patch.object(ImageDraw.ImageDraw, "textbbox", side_effect=AttributeError("mock no textbbox")),          patch.object(ImageDraw.ImageDraw, "textsize", create=True, return_value=(100, 40)) as mock_textsize:
        res_str = await run_thumbnail_stage_task("task_old_pillow", db_path=temp_db)
        res = json.loads(res_str)
        assert res["valid"] is True
        mock_textsize.assert_called()


def test_main_execution():
    """main() 関数の実行と OrchestrationHub 連携の検証"""
    with patch("agents.orchestration.mark_tasks_p27_weaver0.OrchestrationHub") as mock_hub_class:
        mock_hub = mock_hub_class.return_value
        mock_hub.generate_flash_status.return_value = {"status": "success"}
        
        from agents.orchestration.mark_tasks_p27_weaver0 import main
        main()
        
        mock_hub.register_flash_conversation_id.assert_called_once_with("ce05d36d-f2c8-452b-8ea9-9053a1e718a0")
        mock_hub.flash_update_heartbeat.assert_called_once()
        mock_hub.mark_task_done.assert_called_once()
        mock_hub.generate_flash_status.assert_called_once()


def test_script_execution_via_runpy():
    """runpy を使用して __name__ == "__main__" として実行する"""
    import runpy
    with patch("agents.orchestration.mark_tasks_p27_weaver0.OrchestrationHub") as mock_hub_class:
        mock_hub = mock_hub_class.return_value
        mock_hub.generate_flash_status.return_value = {"status": "success"}
        
        # agents.orchestration.mark_tasks_p27_weaver0 を __main__ として実行
        runpy.run_module("agents.orchestration.mark_tasks_p27_weaver0", run_name="__main__")
