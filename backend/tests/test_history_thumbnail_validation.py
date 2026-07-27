# -*- coding: utf-8 -*-
import sys
import os
import io
import pytest
import sqlite3
import json
import asyncio
from pathlib import Path
from PIL import Image

# プロジェクトルートとbackendをパスに追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.branding.history_manager import (
    ThumbnailValidator, 
    PremiumThumbnailGenerator, 
    ImageValidationError, 
    resolve_thumbnail_task
)
from backend.agents.stage_bound_agent import StageBoundAgent

def create_dummy_image_bytes(width: int, height: int, mode: str = "RGB") -> bytes:
    """テスト用のダミー画像バイナリを生成するヘルパー関数"""
    img = Image.new(mode, (width, height), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def test_validate_image_success():
    """正常系: 基準を満たす画像の検証が成功することを確認"""
    # 1280x720 (16:9)
    img_bytes = create_dummy_image_bytes(1280, 720)
    assert ThumbnailValidator.validate_image(img_bytes) is True

def test_validate_image_too_small():
    """異常系: 解像度が基準未満の場合にエラーが発生することを確認"""
    # 640x360 (16:9 だが小さい)
    img_bytes = create_dummy_image_bytes(640, 360)
    with pytest.raises(ImageValidationError, match="(?i)resolution .* is below minimum requirement"):
        ThumbnailValidator.validate_image(img_bytes, min_width=1280, min_height=720)

def test_validate_image_wrong_aspect_ratio():
    """異常系: アスペクト比が 16:9 以外の場合にエラーが発生することを確認"""
    # 1280x1280 (1:1)
    img_bytes = create_dummy_image_bytes(1280, 1280)
    with pytest.raises(ImageValidationError, match="(?i)aspect ratio .* does not match expected 16:9"):
        ThumbnailValidator.validate_image(img_bytes, aspect_ratio="16:9")

def test_validate_image_too_large():
    """異常系: ファイルサイズが制限を超えた場合にエラーが発生することを確認"""
    img_bytes = create_dummy_image_bytes(1280, 720)
    # サイズ上限を極端に小さくして検証
    with pytest.raises(ImageValidationError, match="(?i)file size .* exceeds limit"):
        ThumbnailValidator.validate_image(img_bytes, max_size_bytes=100)

def test_validate_image_corrupted():
    """異常系: 破損したバイナリデータの場合にエラーが発生することを確認"""
    bad_bytes = b"not an image at all"
    with pytest.raises(ImageValidationError):
        ThumbnailValidator.validate_image(bad_bytes)

def test_premium_thumbnail_generator_success(tmp_path):
    """正常系: PremiumThumbnailGeneratorで生成された画像が品質基準を満たすことを確認"""
    output_file = tmp_path / "premium_test.png"
    
    # 画像生成
    PremiumThumbnailGenerator.generate(
        output_path=output_file,
        width=1280,
        height=720,
        text="Premium Quality\nTest Thumbnail"
    )
    
    # 存在確認
    assert output_file.exists()
    
    # ファイルサイズ確認 (4MB未満)
    size_bytes = output_file.stat().st_size
    assert size_bytes < 4 * 1024 * 1024
    
    # Pillowによるオープン・破損チェック
    with Image.open(output_file) as img:
        img.verify()
        
    with Image.open(output_file) as img:
        img.load()
        assert img.size == (1280, 720)
        
    # バイナリ検証
    with open(output_file, "rb") as f:
        img_bytes = f.read()
    assert ThumbnailValidator.validate_image(img_bytes) is True

@pytest.mark.asyncio
async def test_resolve_thumbnail_task_integration(tmp_path):
    """StageBoundAgentと連携したresolve_thumbnail_taskの動作確認"""
    db_file = tmp_path / "test_resolve.db"
    task_id = "test_task_resolve_001"
    
    # StageBoundAgent の初期化
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    await agent.register_task(task_id=task_id, initial_status="READY")
    
    # process_func として resolve_thumbnail_task を登録
    async def process_wrapper(tid):
        return await resolve_thumbnail_task(tid, db_path=str(db_file), output_dir=tmp_path)
        
    await agent.start(process_wrapper)
    
    # 完了まで待機
    for _ in range(50):
        status = await agent.get_task_status(task_id)
        if status == "COMPLETED":
            break
        await asyncio.sleep(0.05)
        
    final_status = await agent.get_task_status(task_id)
    await agent.stop()
    
    assert final_status == "COMPLETED"
    
    # 結果のDB格納確認
    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.execute("SELECT * FROM thumbnail_results WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None
        tid, path, width, height, size_bytes, verified_at = row
        assert tid == task_id
        assert width == 1280
        assert height == 720
        assert Path(path).exists()
        assert size_bytes < 4 * 1024 * 1024
    finally:
        conn.close()
