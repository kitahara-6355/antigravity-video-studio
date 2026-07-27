# -*- coding: utf-8 -*-
import sys
import os
import pytest
import sqlite3
import json
import asyncio
from pathlib import Path
from PIL import Image
import io

# パス追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.branding.history_manager import (
    ThumbnailValidator,
    PremiumThumbnailGenerator,
    resolve_thumbnail_task,
    ImageValidationError
)
from backend.agents.stage_bound_agent import StageBoundAgent

def create_dummy_image_bytes(width: int, height: int, mode="RGB", target_size_bytes: int = 0) -> bytes:
    """テスト用のダミー画像バイナリを生成"""
    img = Image.new(mode, (width, height), color="red")
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    data = img_byte_arr.getvalue()
    if len(data) < target_size_bytes:
        data += b'\x00' * (target_size_bytes - len(data))
    return data

def test_thumbnail_validator_success():
    """正常系: 適切な画像サイズ、解像度、アスペクト比で検証が通ることを検証"""
    img_bytes = create_dummy_image_bytes(1280, 720)
    assert ThumbnailValidator.validate_image(img_bytes) is True

def test_thumbnail_validator_empty():
    """異常系: 空の画像バイト列で ImageValidationError が発生することを検証"""
    with pytest.raises(ImageValidationError, match="Image data is empty"):
        ThumbnailValidator.validate_image(b"")

def test_thumbnail_validator_too_large():
    """異常系: ファイルサイズ制限 (4MB) 超過の検証"""
    img_bytes = create_dummy_image_bytes(1280, 720, target_size_bytes=4 * 1024 * 1024 + 100)
    with pytest.raises(ImageValidationError, match="exceeds limit of"):
        ThumbnailValidator.validate_image(img_bytes, max_size_bytes=4 * 1024 * 1024)

def test_thumbnail_validator_resolution_insufficient():
    """異常系: 最小解像度未満の検証"""
    img_bytes = create_dummy_image_bytes(640, 360)
    with pytest.raises(ImageValidationError, match="below minimum requirement"):
        ThumbnailValidator.validate_image(img_bytes, min_width=1280, min_height=720)

def test_thumbnail_validator_aspect_ratio_invalid():
    """異常系: 不正なアスペクト比の検証"""
    img_bytes = create_dummy_image_bytes(1280, 960)  # 4:3
    with pytest.raises(ImageValidationError, match="does not match expected 16:9"):
        ThumbnailValidator.validate_image(img_bytes, aspect_ratio="16:9")

def test_thumbnail_validator_mode_invalid():
    """異常系: 許容されないカラーモードの検証"""
    img_bytes = create_dummy_image_bytes(1280, 720, mode="L")
    with pytest.raises(ImageValidationError, match="color mode L is not allowed"):
        ThumbnailValidator.validate_image(img_bytes, allowed_modes=["RGB"])

def test_thumbnail_validator_corrupted():
    """異常系: 破損した画像の検証"""
    corrupt_bytes = b"not an image at all"
    with pytest.raises(ImageValidationError, match="Image quality check failed"):
        ThumbnailValidator.validate_image(corrupt_bytes)

def test_premium_generator_success(tmp_path):
    """正常系: プレミアムサムネイルが正常にファイルとして生成できることを検証"""
    output_path = tmp_path / "test_premium.png"
    result_path = PremiumThumbnailGenerator.generate(output_path, width=1280, height=720, text="Antigravity Test")
    
    assert result_path.exists()
    assert result_path == output_path
    
    # 生成されたファイルを読み込み検証
    img_bytes = result_path.read_bytes()
    assert ThumbnailValidator.validate_image(img_bytes) is True
    
    with Image.open(result_path) as img:
        img.load()  # 破損していないか確認
        assert img.size == (1280, 720)

def test_premium_generator_invalid_params(tmp_path):
    """異常系: プレミアムサムネイル生成時の引数異常の検証"""
    output_path = tmp_path / "test_invalid.png"
    
    # 最小解像度未満
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        PremiumThumbnailGenerator.generate(output_path, width=640, height=360)
        
    # アスペクト比が16:9以外
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        PremiumThumbnailGenerator.generate(output_path, width=1280, height=960)

@pytest.mark.asyncio
async def test_resolve_thumbnail_task_integration(tmp_path):
    """StageBoundAgent および sqlite3 と連携した resolve_thumbnail_task の正常動作を検証"""
    db_file = tmp_path / "test_history_manager_thumb.db"
    output_dir = tmp_path / "output_thumbs"
    task_id = "task_hist_001"
    
    # StageBoundAgentを準備
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    await agent.register_task(task_id=task_id, initial_status="READY", max_retries=1)
    
    # 解決関数の定義
    async def process_func(tid):
        return await resolve_thumbnail_task(tid, db_path=str(db_file), output_dir=output_dir)
        
    # エージェント開始
    await agent.start(process_func)
    
    # 処理完了を監視
    for _ in range(50):
        status = await agent.get_task_status(task_id)
        if status in ("COMPLETED", "FAILED"):
            break
        await asyncio.sleep(0.05)
        
    final_status = await agent.get_task_status(task_id)
    await agent.stop()
    
    assert final_status == "COMPLETED"
    
    # 生成された画像の検証
    expected_path = output_dir / f"{task_id}.png"
    assert expected_path.exists()
    
    img_bytes = expected_path.read_bytes()
    assert ThumbnailValidator.validate_image(img_bytes) is True
    
    with Image.open(expected_path) as img:
        img.load()
        assert img.size == (1280, 720)
        
    # sqlite3 データベースに結果が書き込まれていることを検証 (thumbnail_results テーブル)
    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.execute("SELECT task_id, path, width, height, size_bytes FROM thumbnail_results WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None
        db_task_id, db_path, db_width, db_height, db_size_bytes = row
        assert db_task_id == task_id
        assert Path(db_path) == expected_path
        assert db_width == 1280
        assert db_height == 720
        assert db_size_bytes == len(img_bytes)
    finally:
        conn.close()
