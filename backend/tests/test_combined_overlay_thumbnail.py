# -*- coding: utf-8 -*-
import os
import sys
from pathlib import Path
current_file = Path(__file__).resolve()
backend_dir = current_file.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
services_dir = backend_dir / "services"
if str(services_dir) not in sys.path:
    sys.path.insert(0, str(services_dir))

import asyncio
import sqlite3
import pytest
from pathlib import Path
from PIL import Image
import json

from backend.combined_overlay import CombinedOverlay
from backend.agents.stage_bound_agent import StageBoundAgent

def test_thumbnail_generation_success(tmp_path):
    output_path = tmp_path / "test_thumb.png"
    overlay = CombinedOverlay()
    
    res_path = overlay.generate_thumbnail(output_path, text="Test Thumb")
    assert res_path.exists()
    
    with Image.open(res_path) as img:
        assert img.size == (1280, 720)


def test_thumbnail_validation(tmp_path):
    overlay = CombinedOverlay()
    
    # 1. 正常な画像
    ok_path = tmp_path / "ok.png"
    overlay.generate_thumbnail(ok_path, width=1280, height=720)
    result = overlay.validate_thumbnail(ok_path)
    assert result["width"] == 1280
    assert result["height"] == 720
    
    # 2. 低解像度の画像 (1280x720未満)
    bad_res_path = tmp_path / "bad_res.png"
    overlay.generate_thumbnail(bad_res_path, width=640, height=360)
    with pytest.raises(ValueError) as exc:
        overlay.validate_thumbnail(bad_res_path)
    assert "Resolution must be at least 1280x720" in str(exc.value)
    
    # 3. アスペクト比が正しくない (16:10 など)
    bad_aspect_path = tmp_path / "bad_aspect.png"
    overlay.generate_thumbnail(bad_aspect_path, width=1280, height=800)
    with pytest.raises(ValueError) as exc:
        overlay.validate_thumbnail(bad_aspect_path)
    assert "Aspect ratio must be 16:9" in str(exc.value)
    
    # 4. ファイルが存在しない
    non_existent = tmp_path / "ghost.png"
    with pytest.raises(FileNotFoundError):
        overlay.validate_thumbnail(non_existent)
        
    # 5. 破損画像
    corrupted_path = tmp_path / "corrupt.png"
    corrupted_path.write_text("not an image at all", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        overlay.validate_thumbnail(corrupted_path)
    assert "Image is corrupted" in str(exc.value)

    # 6. 4MB以上のファイルサイズ制限の検証
    large_file = tmp_path / "large_file.png"
    large_file.write_bytes(b"\x00" * (4 * 1024 * 1024 + 10))
    with pytest.raises(ValueError) as exc:
        overlay.validate_thumbnail(large_file)
    assert "File size exceeds 4MB limit" in str(exc.value)


@pytest.mark.asyncio
async def test_thumbnail_stage_bound_agent_integration(tmp_path):
    db_file = tmp_path / "thumbnail_agent.db"
    overlay = CombinedOverlay()
    overlay.output_dir = tmp_path
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    
    task_id = "t_overlay_thumb_ok"
    await agent.register_task(task_id=task_id, initial_status="READY")
    
    await agent.start(overlay.resolve_thumbnail_task)
    
    for _ in range(20):
        status = await agent.get_task_status(task_id)
        if status in ("COMPLETED", "FAILED"):
            break
        await asyncio.sleep(0.05)
        
    final_status = await agent.get_task_status(task_id)
    assert final_status == "COMPLETED"
    
    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.execute("SELECT result, error, retry_count FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None
        result_data = json.loads(row[0])
        assert result_data["width"] == 1280
        assert result_data["height"] == 720
        assert row[1] is None
        assert row[2] == 0
    finally:
        conn.close()
        
    await agent.stop()


@pytest.mark.asyncio
async def test_thumbnail_stage_bound_agent_retry_on_failure(tmp_path):
    db_file = tmp_path / "thumbnail_retry.db"
    
    overlay = CombinedOverlay()
    overlay.output_dir = Path("C:/invalid_dir_?:*")
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    
    task_id = "t_overlay_thumb_fail"
    await agent.register_task(task_id=task_id, initial_status="READY", max_retries=2)
    
    await agent.start(overlay.resolve_thumbnail_task)
    
    for _ in range(20):
        status = await agent.get_task_status(task_id)
        if status == "FAILED":
            break
        await asyncio.sleep(0.05)
        
    final_status = await agent.get_task_status(task_id)
    assert final_status == "FAILED"
    
    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.execute("SELECT retry_count, status, error FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == 2
        assert row[1] == "FAILED"
        assert row[2] is not None
    finally:
        conn.close()
        
    await agent.stop()


def test_thumbnail_invalid_dimensions(tmp_path):
    overlay = CombinedOverlay()
    
    # 0 または負の値
    with pytest.raises(ValueError) as exc:
        overlay.generate_thumbnail(tmp_path / "neg.png", width=-100, height=720)
    assert "must be positive integers" in str(exc.value)

    with pytest.raises(ValueError) as exc:
        overlay.generate_thumbnail(tmp_path / "zero.png", width=1280, height=0)
    assert "must be positive integers" in str(exc.value)

    # 整数以外
    with pytest.raises(ValueError) as exc:
        overlay.generate_thumbnail(tmp_path / "str.png", width="invalid", height=720)
    assert "must be integers" in str(exc.value)


def test_thumbnail_strict_aspect_ratio(tmp_path):
    overlay = CombinedOverlay()
    
    # 1280x730 の場合、アスペクト比は約 1.753。
    # 16:9 = 1.777... との差は 0.024。
    # 既存の許容誤差 0.05 ならパスしていたが、新しい許容誤差 0.01 ではエラーになる必要がある。
    test_path = tmp_path / "strict_aspect.png"
    overlay.generate_thumbnail(test_path, width=1280, height=730)
    
    with pytest.raises(ValueError) as exc:
        overlay.validate_thumbnail(test_path)
    assert "Aspect ratio must be 16:9" in str(exc.value)


def test_thumbnail_pixel_level_corruption_detection(tmp_path):
    overlay = CombinedOverlay()
    
    # 正常にサムネイル作成
    test_path = tmp_path / "pixel_corrupt.png"
    overlay.generate_thumbnail(test_path, width=1280, height=720)
    
    # 画像ファイルの中身の一部を壊す
    # ヘッダー (IHDR) は維持し、データ部分 (IDATなど) を上書きして verify は通るが load は失敗する状態を作る
    with open(test_path, "r+b") as f:
        f.seek(50)  # PNGのヘッダーの少し後ろ
        f.write(b"CORRUPTEDDATA" * 10)
        
    with pytest.raises(ValueError) as exc:
        overlay.validate_thumbnail(test_path)
    # verify または load で検知されるはず
    assert "Image is corrupted" in str(exc.value)


def test_thumbnail_atomic_write(tmp_path, monkeypatch):
    overlay = CombinedOverlay()
    test_path = tmp_path / "atomic.png"
    
    # img.save を呼んだときに例外が発生するようにモックする
    from PIL import Image
    def mock_save(*args, **kwargs):
        raise IOError("Simulated disk write failure")
        
    # Pillow の Image.Image.save に monkeypatch を適用
    monkeypatch.setattr(Image.Image, "save", mock_save)
    
    with pytest.raises(IOError):
        overlay.generate_thumbnail(test_path, width=1280, height=720)
        
    # 一時ファイルやターゲットファイルがディスク上に残っていないことを検証
    assert not test_path.exists()
    
    # tmp_path 以下に一時ファイル（.tmp）も残っていないことを確認
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert len(tmp_files) == 0


def test_thumbnail_gradient_and_rich_aesthetics(tmp_path):
    overlay = CombinedOverlay()
    test_path = tmp_path / "rich_thumbnail.png"
    
    # プレミアムサムネイルを生成
    overlay.generate_thumbnail(test_path, text="Rich Design Title")
    
    assert test_path.exists()
    
    # Pillowで読み込み、画像データが正常に描画されているか（単色ではないことなど）をピクセル分析で検証
    with Image.open(test_path) as img:
        assert img.size == (1280, 720)
        
        # グラデーションを検証するため、左上 (0,0) と右下 (1279,719) の色を比較し、
        # 異なる色になっていることを検証
        px = img.load()
        color_topleft = px[0, 0]
        color_bottomright = px[1279, 719]
        
        # 完全に単一の色ではないことを検証
        assert color_topleft != color_bottomright
        
        # 明確な色の差が存在すること
        diff = sum(abs(c1 - c2) for c1, c2 in zip(color_topleft, color_bottomright))
        assert diff > 10
