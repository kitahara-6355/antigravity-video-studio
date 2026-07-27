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
from PIL import Image, ImageDraw, ImageFont
from unittest.mock import patch, MagicMock, PropertyMock

# backend ディレクトリを sys.path に追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from agents.orchestration.mark_tasks_p27_weaver0_new import (
    verify_thumbnail_quality,
    run_thumbnail_stage_task
)
from agents.stage_bound_agent import StageBoundAgent

@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_stage_weaver0_new.db"
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
    path = tmp_path / "valid_image_new.png"
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
        verify_thumbnail_quality("non_existent_file_path_123_new.jpg")

def test_verify_thumbnail_quality_resolution_fail(tmp_path):
    """異常系: 低解像度 (1280x720 未満)"""
    img = Image.new("RGB", (1000, 562), color=(100, 100, 100)) # 約16:9だが低解像度
    path = tmp_path / "low_res_new.png"
    img.save(path, format="PNG")
    
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        verify_thumbnail_quality(path)

def test_verify_thumbnail_quality_aspect_ratio_fail(tmp_path):
    """異常系: アスペクト比が 16:9 ではない"""
    img = Image.new("RGB", (1280, 1000), color=(100, 100, 100)) # 1280x720以上だが比率が違う
    path = tmp_path / "wrong_aspect_new.png"
    img.save(path, format="PNG")
    
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        verify_thumbnail_quality(path)

def test_verify_thumbnail_quality_size_fail(tmp_path):
    """異常系: ファイルサイズが 4MB 以上"""
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    path = tmp_path / "large_file_new.png"
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
    res_str = await run_thumbnail_stage_task("task_weaver0_new_001", db_path=temp_db)
    res = json.loads(res_str)
    assert res["valid"] is True
    assert res["width"] == 1280
    assert res["height"] == 720
    
    # 生成された画像の存在と内容の検証 (対角グラデーション背景)
    project_root = Path(__file__).resolve().parents[2]
    image_path = project_root / "temp_thumbnails" / "task_weaver0_new_001.png"
    assert image_path.exists()
    
    # 画像をロードして、グラデーション(単一色でないこと)を検証
    img = Image.open(image_path)
    # 対角線上の色差を検証する
    color_top_left = img.getpixel((10, 10))
    color_bottom_right = img.getpixel((1270, 710))
    assert color_top_left != color_bottom_right, "画像背景が対角グラデーションになっていません（色差がありません）"
    
    # DB連携と結果保存の検証
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM thumbnail_results WHERE task_id = 'task_weaver0_new_001'")
    row = cursor.fetchone()
    assert row is not None
    assert "task_weaver0_new_001" in row[0]
    assert 1280 == row[2]
    assert 720 == row[3]
    conn.close()

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_failure(temp_db):
    """品質検証で失敗した際、emit_critical が呼ばれ例外が送出されることを検証"""
    with patch("agents.orchestration.mark_tasks_p27_weaver0_new.verify_thumbnail_quality", side_effect=ValueError("Mock Quality Error")),          patch("agents.orchestration.mark_tasks_p27_weaver0_new.emit_critical") as mock_emit_critical:
          
          with pytest.raises(ValueError, match="Mock Quality Error"):
              await run_thumbnail_stage_task("task_fail_new", db_path=temp_db)
          
          mock_emit_critical.assert_called_once_with("thumbnail", "Thumbnail task failed for task task_fail_new: Mock Quality Error")

@pytest.mark.asyncio
async def test_stage_bound_agent_integration(temp_db):
    """StageBoundAgent にタスクを登録して自動リトライが動作することを検証"""
    agent = StageBoundAgent(
        stage_name="thumbnail",
        db_path=temp_db,
        poll_interval=0.01
    )
    
    # READYタスクを登録 (max_retries=2)
    await agent.register_task("task_retry_test_new", initial_status="READY", max_retries=2)
    
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
        status = await agent.get_task_status("task_retry_test_new")
        if status == "COMPLETED":
            break
        await asyncio.sleep(0.05)
        
    await agent.stop()
    
    # 3回目でCOMPLETEDになったことを確認
    assert call_count == 3
    status = await agent.get_task_status("task_retry_test_new")
    assert status == "COMPLETED"
    
    # 最終的な結果の取得
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("SELECT * FROM tasks WHERE id = 'task_retry_test_new'")
    row = dict(cursor.fetchone())
    assert row["retry_count"] == 2
    assert row["result"] == "SUCCESS_DATA"
    conn.close()


def test_verify_thumbnail_quality_file_corrupted_path(tmp_path):
    """異常系: 破損したファイルパス指定でのエラーハンドリング (行41-43のカバー)"""
    corrupted_file = tmp_path / "corrupted_img.png"
    corrupted_file.write_bytes(b"not a real image data")
    
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        verify_thumbnail_quality(corrupted_file)

def test_verify_thumbnail_quality_size_exception(tmp_path):
    """異常系: 画像サイズ取得時のエラーハンドリング (行47-49のカバー)"""
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    path = tmp_path / "test_size_error.png"
    img.save(path, format="PNG")
    
    with patch("PIL.Image.open") as mock_open:
        mock_img = MagicMock()
        type(mock_img).size = PropertyMock(side_effect=OSError("Mock Size Read Error"))
        mock_open.return_value = mock_img
        
        with pytest.raises(ValueError, match="Failed to load image for resolution check"):
            verify_thumbnail_quality(path)

@pytest.mark.asyncio
async def test_font_loading_exceptions_and_fallback(temp_db):
    """正常系: フォントロード時の例外およびデフォルトフォントへのフォールバック (行126-127, 129-130のカバー)"""
    default_font = ImageFont.load_default()
    with patch("os.path.exists", return_value=True), \
         patch("PIL.ImageFont.truetype", side_effect=OSError("Font load error")), \
         patch("PIL.ImageFont.load_default", return_value=default_font) as mock_load_default:
        
        res_str = await run_thumbnail_stage_task("task_font_fallback_test", db_path=temp_db)
        res = json.loads(res_str)
        assert res["valid"] is True
        assert mock_load_default.call_count >= 2

@pytest.mark.asyncio
async def test_textsize_fallback_on_attribute_error(temp_db):
    """正常系: textbbox メソッドが AttributeError を投げた場合の textsize フォールバック (行145-146, 177-178のカバー)"""
    original_draw = ImageDraw.Draw
    
    def mock_draw(*args, **kwargs):
        draw_obj = original_draw(*args, **kwargs)
        if hasattr(draw_obj, "textbbox"):
            draw_obj.textbbox = MagicMock(side_effect=AttributeError("textbbox not supported"))
        # textsize メソッドのフォールバック定義
        draw_obj.textsize = MagicMock(return_value=(100, 20))
        return draw_obj

    with patch("PIL.ImageDraw.Draw", side_effect=mock_draw):
        res_str = await run_thumbnail_stage_task("task_textsize_fallback_test", db_path=temp_db)
        res = json.loads(res_str)
        assert res["valid"] is True

def test_main_execution():
    """正常系: main() 関数の実行と if __name__ == '__main__' ブロックのカバー (行215-234, 237のカバー)"""
    import runpy
    
    # backend.agents.orchestration.OrchestrationHub クラスそのものをパッチする
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        mock_hub.generate_flash_status.return_value = {"status": "success"}
        
        # 警告回避のため、実行前にモジュールを sys.modules から一時退避する
        orig_module = sys.modules.pop("agents.orchestration.mark_tasks_p27_weaver0_new", None)
        try:
            # モジュールをスクリプト（__main__）として実行する
            runpy.run_module("agents.orchestration.mark_tasks_p27_weaver0_new", run_name="__main__")
        finally:
            if orig_module is not None:
                sys.modules["agents.orchestration.mark_tasks_p27_weaver0_new"] = orig_module
        
        mock_hub.register_flash_conversation_id.assert_called_once_with("a9736a64-a242-485f-942e-bf8476d21fa6")
        mock_hub.flash_update_heartbeat.assert_called_once()
        mock_hub.mark_task_done.assert_called_once_with(
            "T-batch_a97ee3-test_weaver-000",
            "pass",
            {
                "message": "Phase 27 のサムネイル生成/画像処理ロジックを改善し、StageBoundAgent連携および品質検証をパス。",
                "changed_files": [
                    "backend/agents/orchestration/mark_tasks_p27_weaver0_new.py",
                    "backend/tests/test_mark_tasks_p27_weaver0_new.py"
                ]
            }
        )
        mock_hub.generate_flash_status.assert_called_once()


@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_type_error(temp_db):
    """異常系: TypeErrorが発生した際にemit_criticalが呼ばれ例外が送出されること"""
    with patch("agents.orchestration.mark_tasks_p27_weaver0_new.verify_thumbnail_quality", side_effect=TypeError("Mock Type Error")), \
         patch("agents.orchestration.mark_tasks_p27_weaver0_new.emit_critical") as mock_emit_critical:
        
        with pytest.raises(TypeError, match="Mock Type Error"):
            await run_thumbnail_stage_task("task_type_error_test", db_path=temp_db)
            
        mock_emit_critical.assert_called_once_with("thumbnail", "Thumbnail task failed for task task_type_error_test: Mock Type Error")


@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_database_error(temp_db):
    """異常系: DatabaseErrorが発生した際にemit_criticalが呼ばれ例外が送出されること"""
    with patch("sqlite3.connect", side_effect=sqlite3.DatabaseError("Mock DB Error")), \
         patch("agents.orchestration.mark_tasks_p27_weaver0_new.emit_critical") as mock_emit_critical:
        
        with pytest.raises(sqlite3.DatabaseError, match="Mock DB Error"):
            await run_thumbnail_stage_task("task_db_error_test", db_path=temp_db)
            
        mock_emit_critical.assert_called_once_with("thumbnail", "Thumbnail task failed for task task_db_error_test: Mock DB Error")


@pytest.mark.asyncio
async def test_font_loading_warning_emitted(temp_db):
    """正常系: フォントロード失敗時にemit_warningが正しく呼ばれること"""
    default_font = ImageFont.load_default()
    with patch("os.path.exists", return_value=True), \
         patch("PIL.ImageFont.truetype", side_effect=OSError("Font load error")), \
         patch("PIL.ImageFont.load_default", return_value=default_font), \
         patch("agents.orchestration.mark_tasks_p27_weaver0_new.emit_warning") as mock_emit_warning:
        
        res_str = await run_thumbnail_stage_task("task_font_warning_test", db_path=temp_db)
        res = json.loads(res_str)
        assert res["valid"] is True
        # font_pathsに定義された4つすべてのフォント試行失敗警告と、最後のフォールバック警告が出ることを確認
        assert mock_emit_warning.call_count >= 5

