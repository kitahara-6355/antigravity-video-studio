import sys
import os
import pytest
import json
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image

# パス追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.check_pipeline_status import (
    generate_pipeline_status_thumbnail,
    validate_pipeline_status_thumbnail,
    resolve_pipeline_status_thumbnail_task
)

def test_generate_and_validate_success(tmp_path):
    """正常系: 品質基準を満たした画像が生成され、検証が通ることを確認"""
    img_path = tmp_path / "valid_pipeline_status.png"
    text = "Pipeline Status: completed\nStage: render"
    
    generate_pipeline_status_thumbnail(img_path, width=1280, height=720, text=text)
    
    assert img_path.exists()
    
    result = validate_pipeline_status_thumbnail(img_path)
    assert result["path"] == str(img_path)
    assert result["width"] == 1280
    assert result["height"] == 720
    assert result["size_bytes"] < 4 * 1024 * 1024

def test_validation_file_not_found():
    """異常系: ファイルが存在しない場合に FileNotFoundError が発生することを確認"""
    with pytest.raises(FileNotFoundError):
        validate_pipeline_status_thumbnail("non_existent_file.png")

def test_validation_resolution_insufficient(tmp_path):
    """異常系: 解像度が足りない場合に ValueError が発生することを確認"""
    img_path = tmp_path / "low_res.png"
    # 640x360 の画像
    generate_pipeline_status_thumbnail(img_path, width=640, height=360)
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        validate_pipeline_status_thumbnail(img_path)

def test_validation_aspect_ratio_invalid(tmp_path):
    """異常系: アスペクト比が 16:9 ではない場合に ValueError が発生することを確認"""
    img_path = tmp_path / "bad_ratio.png"
    # 1280x960 (4:3)
    generate_pipeline_status_thumbnail(img_path, width=1280, height=960)
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        validate_pipeline_status_thumbnail(img_path)

def test_validation_file_size_exceeded(tmp_path):
    """異常系: ファイルサイズが 4MB を超える場合に ValueError が発生することを確認"""
    img_path = tmp_path / "oversized.png"
    generate_pipeline_status_thumbnail(img_path)
    
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 5 * 1024 * 1024  # 5MB
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            validate_pipeline_status_thumbnail(img_path)

def test_validation_corrupted_image(tmp_path):
    """異常系: 画像データが破損している場合に ValueError が発生することを確認"""
    img_path = tmp_path / "corrupted.png"
    with open(img_path, "wb") as f:
        f.write(b"not a valid png image data")
        
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        validate_pipeline_status_thumbnail(img_path)

def test_stage_bound_agent_integration(tmp_path):
    """StageBoundAgent / DB結果保存 / 非同期リトライフローとの連携検証"""
    db_file = tmp_path / "test_pipeline_status.db"
    
    from backend.agents.stage_bound_agent import StageBoundAgent
    import sqlite3
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    task_id = "pipeline_status_thumb_task"
    
    async def run_test():
        # タスク登録
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=2)
        
        # モックしたレスポンスデータ
        mock_data = {
            "status": "completed",
            "current_stage": "render"
        }
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(mock_data).encode("utf-8")
        
        with patch("urllib.request.urlopen", return_value=mock_response):
            await agent.start(resolve_pipeline_status_thumbnail_task)
            
            # 完了するまで少し待つ
            for _ in range(50):
                status = await agent.get_task_status(task_id)
                if status in ("COMPLETED", "FAILED"):
                    break
                await asyncio.sleep(0.05)
                
            final_status = await agent.get_task_status(task_id)
            await agent.stop()
            
            assert final_status == "COMPLETED"
            
            # 生成された画像が存在し、品質をパスするか確認
            output_file = Path("backend/temp_thumbnails") / f"{task_id}.png"
            assert output_file.exists()
            
            try:
                result_info = validate_pipeline_status_thumbnail(output_file)
                assert result_info["width"] == 1280
                assert result_info["height"] == 720
                
                # DBに結果が正しく書き込まれているか確認
                conn = sqlite3.connect(str(db_file))
                try:
                    cursor = conn.execute("SELECT status, result, retry_count FROM tasks WHERE id = ?", (task_id,))
                    row = cursor.fetchone()
                    assert row is not None
                    status, result_str, retry_count = row
                    assert status == "COMPLETED"
                    assert retry_count == 0
                    
                    db_result = json.loads(result_str)
                    assert db_result["width"] == 1280
                    assert db_result["height"] == 720
                    assert "path" in db_result
                finally:
                    conn.close()
            finally:
                if output_file.exists():
                    output_file.unlink()

    asyncio.run(run_test())


def test_generate_thumbnail_invalid_dimensions(tmp_path):
    """幅と高さに無効な値を指定した場合にValueErrorが発生することを確認 (L99-100, L103)"""
    img_path = tmp_path / "invalid_dim.png"
    with pytest.raises(ValueError, match="Width and height must be integers"):
        generate_pipeline_status_thumbnail(img_path, width="invalid", height=720)
    
    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        generate_pipeline_status_thumbnail(img_path, width=0, height=720)
        
    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        generate_pipeline_status_thumbnail(img_path, width=1280, height=-10)

def test_generate_thumbnail_existing_output(tmp_path):
    """すでに出力ファイルが存在する場合にunlinkが呼ばれて上書きされることを確認 (L123)"""
    img_path = tmp_path / "existing.png"
    # 最初の一回作成
    generate_pipeline_status_thumbnail(img_path, width=1280, height=720)
    assert img_path.exists()
    
    # 二回目、上書き
    generate_pipeline_status_thumbnail(img_path, width=1280, height=720, text="Overwritten")
    assert img_path.exists()
    # 画像の中身を検証してパスすることを確認
    result = validate_pipeline_status_thumbnail(img_path)
    assert result["width"] == 1280

def test_generate_thumbnail_save_exception(tmp_path):
    """保存中に例外が発生した場合に一時ファイルが削除され例外が再スローされることを確認 (L125-131)"""
    img_path = tmp_path / "failed_save.png"
    
    # 2026-07-26: 以前は hasattr(pathlib, "WindowsPath") で分岐していたが、
    # WindowsPath は Linux でもクラスとして存在する（インスタンス化できないだけ）。
    # そのため Linux でも "pathlib.WindowsPath.rename" をパッチしてしまい、
    # 実際に使われる PosixPath には効かず DID NOT RAISE で失敗していた。
    # rename / unlink は基底の Path に定義されており両プラットフォームの
    # 具象クラスが継承しているので、Path をパッチすれば両方に効く。
    rename_target = "pathlib.Path.rename"
    unlink_target = "pathlib.Path.unlink"
    
    with patch(rename_target, side_effect=RuntimeError("Rename failed")):
        with pytest.raises(RuntimeError, match="Rename failed"):
            generate_pipeline_status_thumbnail(img_path)
            
    # 一時ファイル削除時にも例外が発生して pass するケース (L127-130)
    with patch(rename_target, side_effect=RuntimeError("Rename failed")):
        with patch(unlink_target, side_effect=OSError("Unlink failed")):
            with pytest.raises(RuntimeError, match="Rename failed"):
                generate_pipeline_status_thumbnail(img_path)

def test_validate_thumbnail_load_exception(tmp_path):
    """Image.loadが例外を投げた場合にValueErrorが発生することを確認 (L159-160)"""
    img_path = tmp_path / "load_fail.png"
    generate_pipeline_status_thumbnail(img_path)
    
    # Image.openで開いたオブジェクトの load() が例外を投げるようにする
    original_open = Image.open
    def mock_open(*args, **kwargs):
        img = original_open(*args, **kwargs)
        img.load = MagicMock(side_effect=RuntimeError("Load failed"))
        return img
        
    with patch("PIL.Image.open", side_effect=mock_open):
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            validate_pipeline_status_thumbnail(img_path)

@pytest.mark.asyncio
async def test_resolve_thumbnail_task_urlopen_exception():
    """urlopenが例外を投げた場合に offline テキストで画像が生成されることを確認 (L189-190)"""
    task_id = "test_urlopen_fail"
    output_path = Path("backend/temp_thumbnails") / f"{task_id}.png"
    if output_path.exists():
        output_path.unlink()
        
    with patch("urllib.request.urlopen", side_effect=RuntimeError("Network down")):
        result_json = await resolve_pipeline_status_thumbnail_task(task_id)
        assert output_path.exists()
        
        result_info = json.loads(result_json)
        assert result_info["width"] == 1280
        
        # クリーンアップ
        output_path.unlink()

@pytest.mark.asyncio
async def test_resolve_thumbnail_task_asyncio_exception():
    """to_threadなどで想定外の例外が発生した場合に例外が処理されることを確認 (L200-201)"""
    task_id = "test_asyncio_fail"
    output_path = Path("backend/temp_thumbnails") / f"{task_id}.png"
    if output_path.exists():
        output_path.unlink()
        
    # asyncio.to_threadが例外を投げるようにモック
    with patch("asyncio.to_thread", side_effect=RuntimeError("Thread dispatch failed")):
        result_json = await resolve_pipeline_status_thumbnail_task(task_id)
        assert output_path.exists()
        
        result_info = json.loads(result_json)
        assert result_info["width"] == 1280
        
        # クリーンアップ
        output_path.unlink()
