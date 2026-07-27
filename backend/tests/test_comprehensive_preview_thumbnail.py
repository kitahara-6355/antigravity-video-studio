import pytest
import os
import sqlite3
import json
import asyncio
import sys
from pathlib import Path

# backend の親ディレクトリ（プロジェクトルート）を sys.path に追加して
# "backend.xxx" のインポートを解決できるようにする
_backend_dir = Path(__file__).resolve().parent.parent
_project_root = _backend_dir.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from PIL import Image
from backend.comprehensive_preview import (
    validate_preview_image,
    ensure_preview_image_quality,
    PreviewResolutionError,
    PreviewImageSizeExceededError,
    PreviewImageCorruptedError
)
from backend.agents.stage_bound_agent import StageBoundAgent

def test_thumbnail_resolution_and_aspect_ratio(tmp_path):
    # テスト品質基準: 解像度 1280x720 以上、アスペクト比 16:9
    
    # 1. 800x600 の画像を生成し、自動補正をかけて 1280x720 にリサイズ＆パディングされるか検証
    img_path_ng = tmp_path / "test_low_res.png"
    img = Image.new("RGB", (800, 600), (255, 0, 0))
    img.putpixel((0, 0), (0, 255, 0)) # 単一色回避
    img.save(img_path_ng)
    
    res_path = ensure_preview_image_quality(str(img_path_ng))
    assert Path(res_path).exists()
    
    val_res = validate_preview_image(res_path)
    assert val_res["width"] >= 1280
    assert val_res["height"] >= 720
    
    aspect_ratio = val_res["width"] / val_res["height"]
    assert abs(aspect_ratio - (16.0 / 9.0)) <= 0.01

def test_thumbnail_file_size_limit(tmp_path, monkeypatch):
    # テスト品質基準: ファイルサイズが 4MB 未満であること
    img_path = tmp_path / "test_size_limit.png"
    img = Image.new("RGB", (1280, 720), (0, 0, 0))
    img.putpixel((0, 0), (255, 255, 255))
    img.save(img_path)
    
    # 一時的なファイルサイズ偽装
    class MockStat:
        def __init__(self, size):
            self.st_size = size
            
    orig_stat = Path.stat
    def mock_stat_always_large(self, *args, **kwargs):
        if "test_size_limit" in str(self):
            return MockStat(5 * 1024 * 1024)
        return orig_stat(self, *args, **kwargs)
        
    monkeypatch.setattr(Path, "stat", mock_stat_always_large)
    
    with pytest.raises(ValueError, match="Could not reduce image file size below 4MB"):
        ensure_preview_image_quality(str(img_path))

def test_thumbnail_not_corrupted_and_loadable(tmp_path):
    # テスト品質基準: 出力ファイルが正常に存在し、破損していない
    img_path = tmp_path / "test_loadable.png"
    img = Image.new("RGB", (1280, 720), (128, 128, 128))
    img.putpixel((0, 0), (0, 0, 0))
    img.save(img_path)
    
    res_path = ensure_preview_image_quality(str(img_path))
    assert Path(res_path).exists()
    
    # Pillowで読み込んで正常にロードできるか
    with Image.open(res_path) as loaded_img:
        loaded_img.load()
        assert loaded_img.size == (1280, 720)

@pytest.mark.asyncio
async def test_thumbnail_stage_bound_agent_integration(tmp_path):
    # テスト品質基準: StageBoundAgent等に登録され、自動リトライや結果保存、DBマイグレーションの各機能と連携して動作すること
    db_file = tmp_path / "test_stage_bound_agent_integration.db"
    
    agent = StageBoundAgent(stage_name="comprehensive_preview", db_path=str(db_file))
    
    # 1. DBマイグレーション確認
    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks';")
        assert cursor.fetchone() is not None
        
        cursor.execute("PRAGMA table_info(tasks);")
        columns = {col[1] for col in cursor.fetchall()}
        for col in ["id", "status", "result", "error", "retry_count"]:
            assert col in columns
    finally:
        conn.close()
        
    # 2. タスク登録・実行・結果保存
    task_id = "test_thumbnail_task_001"
    await agent.register_task(task_id=task_id, initial_status="READY", max_retries=2)
    
    raw_img_path = tmp_path / "raw_thumbnail.png"
    img = Image.new("RGB", (800, 600), (100, 100, 100))
    img.putpixel((0, 0), (0, 0, 0))
    img.save(raw_img_path)
    
    corrected_path = ensure_preview_image_quality(str(raw_img_path))
    val_res = validate_preview_image(corrected_path)
    
    dummy_result = {
        "task_id": task_id,
        "validation": [val_res]
    }
    
    async def process_func(tid):
        return json.dumps(dummy_result)
        
    await agent.start(process_func)
    await asyncio.sleep(0.1)
    await agent.stop()
    
    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT status, result, retry_count, error FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "COMPLETED"
        
        saved_result = json.loads(row[1])
        assert saved_result["validation"][0]["width"] >= 1280
        assert saved_result["validation"][0]["height"] >= 720
        assert row[2] == 0
        assert row[3] is None
    finally:
        conn.close()

def test_ensure_preview_image_quality_extreme_resolutions(tmp_path):
    # 極端な高解像度 (4K: 3840x2160) からのダウンスケール＆アスペクト比維持
    img_path_4k = tmp_path / "test_4k.png"
    img = Image.new("RGB", (3840, 2160), (0, 255, 0))
    img.putpixel((0, 0), (255, 0, 0))
    img.save(img_path_4k)
    res_path = ensure_preview_image_quality(str(img_path_4k))
    val_res = validate_preview_image(res_path)
    assert val_res["width"] == 1280
    assert val_res["height"] == 720

    # 極端なアスペクト比 (1:1 正方形: 1000x1000) -> 1280x720 (16:9) へのパディング
    img_path_square = tmp_path / "test_square.png"
    img2 = Image.new("RGB", (1000, 1000), (0, 0, 255))
    img2.putpixel((0, 0), (255, 0, 0))
    img2.save(img_path_square)
    res_path_sq = ensure_preview_image_quality(str(img_path_square))
    val_res_sq = validate_preview_image(res_path_sq)
    assert val_res_sq["width"] == 1280
    assert val_res_sq["height"] == 720

def test_ensure_preview_image_quality_unsupported_format(tmp_path):
    # 未サポートの拡張子 (.gif)
    img_path_gif = tmp_path / "test_unsupported.gif"
    Image.new("RGB", (800, 600)).save(img_path_gif)
    with pytest.raises(ValueError, match="Unsupported file format"):
        ensure_preview_image_quality(str(img_path_gif))

def test_validate_preview_image_corrupted_format_handling(tmp_path):
    # 完全に破損したファイル（空ファイル）
    empty_path = tmp_path / "empty.png"
    empty_path.write_bytes(b"")
    with pytest.raises(PreviewImageCorruptedError):
        validate_preview_image(str(empty_path))

    # ヘッダーだけの破損ファイル
    corrupted_path = tmp_path / "corrupted_header.png"
    corrupted_path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00")
    with pytest.raises(PreviewImageCorruptedError):
        validate_preview_image(str(corrupted_path))

def test_ensure_preview_image_quality_disk_gc(tmp_path, monkeypatch):
    # ディスク空き容量不足かつ古い tmp ファイルのクリーンアップシミュレーション
    img_path = tmp_path / "test_disk_gc.png"
    img = Image.new("RGB", (1280, 720), (255, 255, 255))
    img.putpixel((0, 0), (255, 0, 0))
    img.save(img_path)

    # 模擬的な古い一時ファイルを複数作成
    old_tmp_1 = tmp_path / "old_file.1234.tmp"
    old_tmp_2 = tmp_path / "old_file.5678.tmp"
    old_tmp_1.write_text("old data")
    old_tmp_2.write_text("old data")

    # shutil.disk_usage の戻り値として、最初 (gc前) は空き容量不足(5MB)、クリーンアップ後に15MBになるように仕組む
    call_count = 0
    def mock_disk_usage(path):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # 1回目のディスクチェックでは容量不足を検知
            return (100 * 1024 * 1024, 95 * 1024 * 1024, 5 * 1024 * 1024)
        else:
            # GCが走った後は十分な空きがあるとする
            return (100 * 1024 * 1024, 85 * 1024 * 1024, 15 * 1024 * 1024)

    import shutil
    monkeypatch.setattr(shutil, "disk_usage", mock_disk_usage)

    # ensure_preview_image_quality を実行
    res_path = ensure_preview_image_quality(str(img_path))
    assert Path(res_path).exists()
    # 古い一時ファイルがGCされて削除されたことを検証
    assert not old_tmp_1.exists()
    assert not old_tmp_2.exists()

def test_validate_preview_image_grayscale_handling(tmp_path):
    # L モード（グレースケール）画像の検証で TypeError が発生しないこと
    img_path = tmp_path / "grayscale.png"
    # 単一色画像
    img = Image.new("L", (1280, 720), 128)
    # テスト環境の Image.new モックを回避して確実に単一色にするためにピクセルを上書き
    try:
        img.putpixel((0, 0), 128)
    except Exception:
        pass
    img.save(img_path)
    
    with pytest.raises(PreviewImageCorruptedError, match="Image is a single solid color"):
        validate_preview_image(str(img_path))
        
    # 非単一色画像
    img.putpixel((0, 0), 0)
    img.save(img_path)
    
    val_res = validate_preview_image(str(img_path))
    assert val_res["width"] == 1280
    assert val_res["height"] == 720

def test_ensure_preview_image_quality_format_consistency(tmp_path):
    # 出力された画像の拡張子と実際のデータフォーマットが一致していること
    img_path = tmp_path / "format_check.png"
    img = Image.new("RGB", (800, 600), (255, 0, 0))
    img.putpixel((0, 0), (0, 255, 0))
    img.save(img_path)
    
    res_path = ensure_preview_image_quality(str(img_path))
    assert res_path.endswith(".png")
    
    # 実際に PNG フォーマットで保存されているか確認
    with Image.open(res_path) as loaded_img:
        assert loaded_img.format == "PNG"

