# -*- coding: utf-8 -*-
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _wp
except ImportError:
    from path_resolver import writable_path as _wp

import pytest
import os
import sys
import time
import base64
import sqlite3
import json
from io import BytesIO
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image

# プロジェクトルートを作業パスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import ProductionContext
# plugins.thumbnail_plugin からインポート
from plugins.thumbnail_plugin import ThumbnailPlugin, validate_and_correct_thumbnail

DB_PATH = "backend/test_plugin_thumbnails.db"

@pytest.fixture(autouse=True)
def cleanup_test_db_and_temp():
    # テスト開始前のクリーンアップ
    for path in [Path(DB_PATH), Path("backend/thumbnails.db")]:
        if path.exists():
            try:
                path.unlink()
            except Exception:
                pass
    
    temp_dir = _wp("backend/temp_thumbnails")
    if temp_dir.exists():
        for f in temp_dir.glob("*"):
            try:
                f.unlink()
            except Exception:
                pass
    yield
    # 事後クリーンアップ
    for path in [Path(DB_PATH), Path("backend/thumbnails.db")]:
        if path.exists():
            try:
                path.unlink()
            except Exception:
                pass
    if temp_dir.exists():
        for f in temp_dir.glob("*"):
            try:
                f.unlink()
            except Exception:
                pass


def create_dummy_image(width: int, height: int, filepath: Path, format: str = "PNG", noisy: bool = False):
    # ダミー画像を生成して保存
    if noisy:
        import numpy as np
        rgb = np.random.randint(0, 256, (height, width, 3), dtype=np.uint8)
        img = Image.fromarray(rgb)
    else:
        img = Image.new("RGB", (width, height), color="blue")
    img.save(filepath, format=format)


def test_validate_and_correct_thumbnail_standards(tmp_path):
    # 正常系の検証テスト: 正しいアスペクト比と解像度
    img_path = tmp_path / "valid.png"
    create_dummy_image(1920, 1080, img_path)
    
    corrected_path = validate_and_correct_thumbnail(str(img_path))
    assert Path(corrected_path).exists()
    
    # 画像の検証
    with Image.open(corrected_path) as img:
        img.verify()
    
    with Image.open(corrected_path) as img:
        img.load()
        assert img.size == (1920, 1080)


def test_validate_and_correct_thumbnail_resize_and_aspect(tmp_path):
    # 異常系解像度とアスペクト比の自動補正テスト
    # 解像度不足: 800x600 -> 1280x720 (16:9) に補正されること
    img_path = tmp_path / "low_res.png"
    create_dummy_image(800, 600, img_path)
    
    corrected_path = validate_and_correct_thumbnail(str(img_path))
    
    with Image.open(corrected_path) as img:
        img.load()
        assert img.size == (1280, 720)  # 解像度は1280x720以上に補正される
        aspect = img.size[0] / img.size[1]
        assert abs(aspect - 16.0 / 9.0) < 0.01


def test_validate_and_correct_thumbnail_large_file_compression(tmp_path):
    # ファイルサイズが4MBを超える巨大画像を自動で4MB未満に圧縮するテスト
    # ノイズ画像を生成して4000x3000(アスペクト比補正もかかる)
    img_path = tmp_path / "heavy.png"
    create_dummy_image(4000, 2250, img_path, noisy=True)
    
    # 意図的に巨大ノイズにしてサイズを大きくする
    original_size = img_path.stat().st_size
    
    corrected_path = validate_and_correct_thumbnail(str(img_path))
    corrected_size = Path(corrected_path).stat().st_size
    
    assert corrected_size < 4 * 1024 * 1024  # 4MB未満に圧縮されていること
    
    with Image.open(corrected_path) as img:
        img.load()
        assert img.size[0] >= 1280 and img.size[1] >= 720


def test_thumbnail_plugin_stage_bound_agent_integration(tmp_path):
    # ThumbnailPlugin が StageBoundAgent にタスクを登録して動作するテスト
    # モックを作成して検証する
    context = ProductionContext()
    context.db_path = DB_PATH
    
    # context の get_extension メソッドと拡張設定を再現
    context_data = {
        "video_title": "Integration Test Title",
        "video_description": "Integration Test Desc",
        "thumbnail_count": 0
    }
    
    def mock_get_extension(key, default=None):
        return context_data.get(key, default)
        
    def mock_set_extension(key, val):
        context_data[key] = val
        
    context.get_extension = mock_get_extension
    context.set_extension = mock_set_extension
    
    # サムネイル候補のダミー設定
    class MockCandidate:
        def __init__(self, cid, path):
            self.id = cid
            self.concept = "Premium Concept"
            self.target_emotion = "excited"
            self.text_overlay = "Amazing Video!"
            self.predicted_ctr = 95.0
            self.path = path
            
    img_path = tmp_path / "candidate_01.png"
    create_dummy_image(1280, 720, img_path)
    
    candidate = MockCandidate("candidate_001", img_path)
    context.thumbnail_candidates = []
    
    # Optimizer のモック
    mock_optimizer = MagicMock()
    
    # optimize_context が返す結果のモック
    class MockOptimizeResult:
        def __init__(self, candidates_list):
            self.thumbnail_candidates = candidates_list
            
    async def mock_optimize_context(*args, **kwargs):
        return MockOptimizeResult([candidate])
        
    mock_optimizer.optimize_context = mock_optimize_context
    
    plugin = ThumbnailPlugin(num_candidates=1)
    
    with patch("plugins.youtube_optimizer_plugin.youtube_optimizer", mock_optimizer), \
         patch("service_container.container.has", return_value=True), \
         patch("service_container.container.get", return_value=mock_optimizer):
        
        result_context = plugin.execute(context)
        
        # 検証
        assert result_context is not None
        assert len(result_context.thumbnail_candidates) == 1
        
        saved_candidate = result_context.thumbnail_candidates[0]
        assert saved_candidate["id"] == "candidate_001"
        assert saved_candidate["path"] is not None
        assert Path(saved_candidate["path"]).exists()
        
        # SQLite DBにレコードが登録・結果が保存されていることを確認
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute("SELECT id, stage, status, result, max_retries FROM tasks")
            rows = cursor.fetchall()
            assert len(rows) == 1
            task_id, stage, status, result_str, max_retries = rows[0]
            assert stage == "thumbnail"
            assert status == "COMPLETED"
            assert max_retries == 2
            
            result_data = json.loads(result_str)
            assert result_data["id"] == "candidate_001"
            assert result_data["width"] == 1280
            assert result_data["height"] == 720
        finally:
            conn.close()


def test_validate_and_correct_thumbnail_edge_cases(tmp_path):
    # 存在しないファイルのテスト
    with pytest.raises(FileNotFoundError):
        validate_and_correct_thumbnail(str(tmp_path / "nonexistent.png"))

    # 破損ファイル（中身がテキスト）のテスト
    corrupt_path = tmp_path / "corrupt.png"
    with open(corrupt_path, "w", encoding="utf-8") as f:
        f.write("not an image")
    with pytest.raises(ValueError) as excinfo:
        validate_and_correct_thumbnail(str(corrupt_path))
    assert "not a recognized image format" in str(excinfo.value) or "invalid" in str(excinfo.value)

    # 暗い画像（明るさ・コントラストの微調整が機能することを確認）
    dark_path = tmp_path / "dark.png"
    # 暗いグレーの画像を作成
    img = Image.new("RGB", (1920, 1080), color=(10, 10, 10))
    img.save(dark_path, format="PNG")
    corrected_path = validate_and_correct_thumbnail(str(dark_path))
    assert Path(corrected_path).exists()
    with Image.open(corrected_path) as img_corr:
        img_corr.load()
        assert img_corr.size == (1920, 1080)


def test_validate_and_correct_thumbnail_standards_strict(tmp_path):
    # 品質基準の厳格な検証テスト
    # 解像度不足、アスペクト比不正の画像を生成
    bad_path = tmp_path / "bad.png"
    create_dummy_image(800, 800, bad_path) # 1:1アスペクト比、1280x720未満
    
    corrected_path = validate_and_correct_thumbnail(str(bad_path))
    
    assert Path(corrected_path).exists()
    with Image.open(corrected_path) as img:
        img.load()
        width, height = img.size
        # 解像度は 1280x720 以上であること
        assert width >= 1280
        assert height >= 720
        # アスペクト比が 16:9 であること
        aspect_ratio = width / height
        assert abs(aspect_ratio - 16.0 / 9.0) < 0.05
        # ファイルサイズが 4MB 未満であること
        assert Path(corrected_path).stat().st_size < 4 * 1024 * 1024
        # 破損していない（Pillowでロード・verify可能）
        with Image.open(corrected_path) as img_verify:
            img_verify.verify()
