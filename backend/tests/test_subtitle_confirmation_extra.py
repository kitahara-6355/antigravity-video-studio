# -*- coding: utf-8 -*-
import sys
import os
import json
import sqlite3
import asyncio
from pathlib import Path
import pytest
from PIL import Image

# backend ディレクトリをパスに追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import subtitle_confirmation
from agents.stage_bound_agent import StageBoundAgent

def test_subtitle_confirmation_thumbnail_generation(tmp_path):
    """正常系: プレビュー画像が正しく生成されること"""
    output_file = tmp_path / "sub_test.png"
    text = "Test Subtitle Confirmation Thumbnail"
    
    # 画像生成を実行
    res_path = subtitle_confirmation.generate_subtitle_confirmation_thumbnail(
        output_file, width=1280, height=720, text=text
    )
    
    # アサーション
    assert res_path.exists()
    assert res_path == output_file
    
    # 画像を開いて検証
    with Image.open(res_path) as img:
        img.verify()
        
    with Image.open(res_path) as img:
        assert img.size == (1280, 720)


def test_subtitle_confirmation_thumbnail_invalid_size():
    """異常系: 解像度が正の整数でない場合にエラーが発生すること"""
    with pytest.raises(ValueError):
        subtitle_confirmation.generate_subtitle_confirmation_thumbnail("test.png", width=-100, height=720)
    with pytest.raises(ValueError):
        subtitle_confirmation.generate_subtitle_confirmation_thumbnail("test.png", width=1280, height="invalid")


def test_subtitle_confirmation_validation_success(tmp_path):
    """正常系: 生成された画像が品質要件を満たし、正常にバリデーションを通ること"""
    output_file = tmp_path / "valid_sub.png"
    subtitle_confirmation.generate_subtitle_confirmation_thumbnail(output_file, width=1280, height=720)
    
    res = subtitle_confirmation.validate_thumbnail_quality(output_file)
    assert res["path"] == str(output_file)
    assert res["width"] == 1280
    assert res["height"] == 720
    assert res["size_bytes"] > 0
    assert res["size_bytes"] < 4 * 1024 * 1024


def test_subtitle_confirmation_validation_failures(tmp_path):
    """異常系: 品質の異なる画像に対してバリデーションエラーが発生すること"""
    # 1. 存在しないファイル
    with pytest.raises(FileNotFoundError):
        subtitle_confirmation.validate_thumbnail_quality(tmp_path / "non_existent.png")
        
    # 2. 解像度不足の画像 (640x360)
    low_res_file = tmp_path / "low_res.png"
    img = Image.new("RGB", (640, 360), color="blue")
    img.save(low_res_file, format="PNG")
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        subtitle_confirmation.validate_thumbnail_quality(low_res_file)
        
    # 3. アスペクト比が 16:9 ではない画像 (1280x960, 4:3)
    bad_ratio_file = tmp_path / "bad_ratio.png"
    img = Image.new("RGB", (1280, 960), color="blue")
    img.save(bad_ratio_file, format="PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        subtitle_confirmation.validate_thumbnail_quality(bad_ratio_file)
        
    # 4. ファイルサイズが 4MB を超える画像 (MagicMockでstatのサイズを偽装)
    valid_file = tmp_path / "valid.png"
    img = Image.new("RGB", (1280, 720), color="blue")
    img.save(valid_file, format="PNG")
    
    from unittest.mock import patch
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 5 * 1024 * 1024  # 5MB
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            subtitle_confirmation.validate_thumbnail_quality(valid_file)


def test_stage_bound_agent_integration(tmp_path):
    """結合テスト: StageBoundAgent と連携し、タスクの登録、実行、結果保存、リトライが正しく機能すること"""
    db_file = tmp_path / "test_stage.db"
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    task_id = "test_subtitle_confirm_task"
    
    async def run_integration():
        # 1. タスクの登録 (リトライ可能回数を1回とする)
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=1)
        
        # 2. StageBoundAgent に resolve_subtitle_confirmation_task を紐づけて開始
        # 一時ディレクトリを出力先としてパッチ
        test_output_dir = tmp_path / "thumbnails"
        test_output_dir.mkdir(parents=True, exist_ok=True)
        
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(subtitle_confirmation, "OUTPUT_DIR", str(test_output_dir))
            
            await agent.start(subtitle_confirmation.resolve_subtitle_confirmation_task)
            
            # タスクが RUNNING または COMPLETED になるまで待機 (最大2秒)
            for _ in range(40):
                status = await agent.get_task_status(task_id)
                if status in ("COMPLETED", "FAILED"):
                    break
                await asyncio.sleep(0.05)
                
            final_status = await agent.get_task_status(task_id)
            await agent.stop()
            
            # アサーション: 成功していること
            assert final_status == "COMPLETED"
            
            # 生成されたプレビュー画像の検証
            expected_img_path = test_output_dir / f"{task_id}.png"
            assert expected_img_path.exists()
            
            with Image.open(expected_img_path) as img:
                img.verify()
                
            # SQLite に結果が保存されていること
            conn = sqlite3.connect(str(db_file))
            try:
                cursor = conn.execute("SELECT status, result, retry_count FROM tasks WHERE id = ?", (task_id,))
                row = cursor.fetchone()
                assert row is not None
                status, result_str, retry_count = row
                
                assert status == "COMPLETED"
                assert retry_count == 0
                
                result_data = json.loads(result_str)
                assert result_data["width"] == 1280
                assert result_data["height"] == 720
                assert "path" in result_data
                assert "size_bytes" in result_data
            finally:
                conn.close()
                
    asyncio.run(run_integration())
