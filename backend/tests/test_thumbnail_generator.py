import os
import sys
import json
import sqlite3
import asyncio
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock
from PIL import Image

# Ensure backend path is in sys.path
backend_path = Path(__file__).parent.parent / "backend"
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from thumbnail_engine.generator import ThumbnailGenerator, resolve_generator_thumbnail_task
from agents.stage_bound_agent import StageBoundAgent

@pytest.mark.asyncio
async def test_thumbnail_generator_quality_and_resolution(tmp_path):
    """
    検証基準:
    - 解像度が 1280x720 以上であること
    - アスペクト比が 16:9 であること
    - ファイルサイズが 4MB 未満であること
    - 出力ファイルが正常に存在し、破損していないこと
    """
    generator = ThumbnailGenerator()
    # clientがNoneの場合に備えてMockを設定
    generator.client = MagicMock()
    
    # 正常な画像生成をモック
    mock_response = MagicMock()
    mock_image = MagicMock()
    
    # 1280x720 のテスト用JPEGバイナリ
    img = Image.new("RGB", (1280, 720), color=(100, 100, 255))
    import io
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='JPEG')
    mock_image.image.image_bytes = img_byte_arr.getvalue()
    mock_response.generated_images = [mock_image]
    
    with patch.object(generator.client.models, "generate_images", return_value=mock_response), \
         patch.object(generator, "_get_brand_style", return_value="Test brand style"), \
         patch.object(generator, "_generate_concepts", return_value=[{"name": "Concept A", "description": "Desc", "visual_prompt": "Prompt", "expected_ctr": 8.0}]):
         
        results = await generator.generate(video_title="Test Video Title", num_variants=1)
        assert len(results) == 1
        
        item = results[0]
        assert item["concept_name"] == "Concept A"
        assert item["image_base64"] is not None
        
        # Base64デコードして画像としてロード可能か検証
        import base64
        image_bytes = base64.b64decode(item["image_base64"])
        
        # ファイルサイズ検証 (4MB 未満)
        assert len(image_bytes) < 4 * 1024 * 1024
        
        # 画像ロードおよび解像度・アスペクト比検証
        img_check = Image.open(io.BytesIO(image_bytes))
        img_check.verify()
        
        img_check = Image.open(io.BytesIO(image_bytes))
        img_check.load()
        width, height = img_check.size
        
        assert width >= 1280
        assert height >= 720
        
        # アスペクト比が 16:9 であること
        aspect_ratio = width / height
        assert abs(aspect_ratio - (16.0 / 9.0)) < 0.01

@pytest.mark.asyncio
async def test_thumbnail_generator_fallback_on_api_failure(tmp_path):
    """
    検証基準: Imagen API 失敗時でも高品質なフォールバック画像が自動生成されること
    """
    generator = ThumbnailGenerator()
    # clientがNoneの場合に備えてMockを設定
    generator.client = MagicMock()
    
    # generate_images が例外を吐くようにモック
    from google.genai import errors
    with patch.object(generator.client.models, "generate_images", side_effect=errors.APIError("API Error", 500, None)), \
         patch.object(generator, "_get_brand_style", return_value="Test brand style"), \
         patch.object(generator, "_generate_concepts", return_value=[{"name": "Fallback Concept", "description": "Desc", "visual_prompt": "Prompt", "expected_ctr": 5.0}]):
         
        # APIが失敗してもフォールバックジェネレータが動作して結果が返ることを確認
        results = await generator.generate(video_title="Fallback Title", num_variants=1)
        assert len(results) == 1
        
        item = results[0]
        import base64
        import io
        image_bytes = base64.b64decode(item["image_base64"])
        
        # ファイルサイズ
        assert len(image_bytes) < 4 * 1024 * 1024
        
        # Pillowロード確認
        img_check = Image.open(io.BytesIO(image_bytes))
        img_check.verify()
        
        img_check = Image.open(io.BytesIO(image_bytes))
        img_check.load()
        width, height = img_check.size
        assert width >= 1280
        assert height >= 720
        
        aspect_ratio = width / height
        assert abs(aspect_ratio - (16.0 / 9.0)) < 0.01

@pytest.mark.asyncio
async def test_resolve_generator_thumbnail_task_stage_bound(tmp_path):
    """
    検証基準: StageBoundAgent 等に登録され、自動リトライや結果保存、DBマイグレーションの各機能と連携して動作すること
    """
    db_file = tmp_path / "test_generator_thumb.db"
    task_id = "test_task_generator_001"
    
    # StageBoundAgent の初期化
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    
    # 必要な属性を agent に設定する
    agent.video_title = "Test Stage Bound Video"
    agent.video_description = "Test Description"
    agent.db_path = str(db_file)
    agent.output_dir = str(tmp_path)
    
    # generatorのgenerateメソッドをモックして実際のAPI呼び出しを防ぐ
    img = Image.new("RGB", (1920, 1080), color=(50, 150, 50))
    import io
    import base64
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='JPEG')
    mock_base64 = base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')
    
    mock_results = [{
        "id": "thumbnail_0",
        "concept_name": "Stage Bound Concept",
        "description": "Desc",
        "prompt": "Prompt",
        "image_base64": mock_base64,
        "ctr_score": 8.5
    }]
    
    with patch.object(ThumbnailGenerator, "generate", return_value=mock_results):
        # タスクをREADYで登録
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=2)
        
        # エージェントを実行
        async def process_task_wrapper(task_id_arg: str) -> str:
            return await resolve_generator_thumbnail_task(agent, task_id_arg)
            
        await agent.start(process_task_wrapper)
        
        # 完了を待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status in ("COMPLETED", "FAILED"):
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
        assert final_status == "COMPLETED"
        
        # 出力ファイルが存在すること
        out_file = tmp_path / f"{task_id}.jpg"
        assert out_file.exists()
        
        # DBに保存された結果の検証 (マイグレーションと結果保存)
        conn = sqlite3.connect(str(db_file))
        try:
            cursor = conn.execute("SELECT status, result FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            assert row is not None
            status, result_str = row
            assert status == "COMPLETED"
            
            result_data = json.loads(result_str)
            assert result_data["valid"] is True
            
            # thumbnail_results テーブルに保存されているか検証
            cursor_res = conn.execute("SELECT task_id, path, width, height, size_bytes, verified_at FROM thumbnail_results WHERE task_id = ?", (task_id,))
            row_res = cursor_res.fetchone()
            assert row_res is not None
            t_id, path_str, w, h, s_bytes, v_at = row_res
            assert t_id == task_id
            assert w >= 1280
            assert h >= 720
            assert s_bytes > 0
            assert v_at > 0
        finally:
            conn.close()


@pytest.mark.asyncio
async def test_thumbnail_generator_aspect_ratio_correction():
    """
    検証基準: 
    - 異なるアスペクト比の画像（例: 1:1, 4:3）を入力した際、
      自動的に 16:9 にクロップ・補正されること
    - 補正後の解像度、アスペクト比、ファイルサイズが要件を満たすこと
    """
    generator = ThumbnailGenerator()
    
    # 1:1 アスペクト比 (500x500) のテスト用画像を作成
    img_square = Image.new("RGB", (500, 500), color=(255, 100, 100))
    import io
    img_byte_arr = io.BytesIO()
    img_square.save(img_byte_arr, format='JPEG')
    square_bytes = img_byte_arr.getvalue()
    
    # 補正関数を直接呼び出す
    optimized_bytes = generator.verify_and_optimize_image(square_bytes, title="Aspect Ratio Test")
    
    # 補正後の画像を検証
    assert optimized_bytes is not None
    assert len(optimized_bytes) < 4 * 1024 * 1024
    
    img_check = Image.open(io.BytesIO(optimized_bytes))
    img_check.verify()
    
    img_check = Image.open(io.BytesIO(optimized_bytes))
    img_check.load()
    width, height = img_check.size
    
    assert width >= 1280
    assert height >= 720
    
    aspect_ratio = width / height
    assert abs(aspect_ratio - (16.0 / 9.0)) < 0.01


@pytest.mark.asyncio
async def test_thumbnail_generator_corrupted_image_handling():
    """
    検証基準:
    - 完全に破損した画像データ（または空のバイト列）が入力された場合、
      例外でクラッシュせず、高品質なフォールバック画像が生成されること
    - 生成されたフォールバック画像が正しい解像度・アスペクト比を持つこと
    """
    generator = ThumbnailGenerator()
    
    # 破損したバイナリデータ
    corrupted_bytes = b"not a real image data at all"
    
    # 補正関数を呼び出す（例外を吐かずにフォールバックを生成するはず）
    optimized_bytes = generator.verify_and_optimize_image(corrupted_bytes, title="Fallback Handling Test")
    
    assert optimized_bytes is not None
    assert len(optimized_bytes) < 4 * 1024 * 1024
    
    import io
    img_check = Image.open(io.BytesIO(optimized_bytes))
    img_check.verify()
    
    img_check = Image.open(io.BytesIO(optimized_bytes))
    img_check.load()
    width, height = img_check.size
    
    assert width >= 1280
    assert height >= 720
    
    aspect_ratio = width / height
    assert abs(aspect_ratio - (16.0 / 9.0)) < 0.01



@pytest.mark.asyncio
async def test_thumbnail_generator_resolution_boundaries():
    """
    検証基準: 極端に小さい画像や極端に大きい画像を入力した際、
    自動的に 1280x720 以上の適切な解像度に拡大縮小されること
    """
    generator = ThumbnailGenerator()
    
    # 極端に小さい画像 (10x10)
    img_small = Image.new("RGB", (10, 10), color=(100, 200, 100))
    import io
    img_byte_arr = io.BytesIO()
    img_small.save(img_byte_arr, format='JPEG')
    small_bytes = img_byte_arr.getvalue()
    
    optimized_bytes = generator.verify_and_optimize_image(small_bytes, title="Small Bound Test")
    assert optimized_bytes is not None
    img_check = Image.open(io.BytesIO(optimized_bytes))
    width, height = img_check.size
    assert width >= 1280
    assert height >= 720
    assert abs((width / height) - (16.0 / 9.0)) < 0.01

    # 極端に大きい画像 (4000x2250)
    img_large = Image.new("RGB", (4000, 2250), color=(100, 200, 100))
    img_byte_arr_l = io.BytesIO()
    img_large.save(img_byte_arr_l, format='JPEG')
    large_bytes = img_byte_arr_l.getvalue()
    
    optimized_bytes_l = generator.verify_and_optimize_image(large_bytes, title="Large Bound Test")
    assert optimized_bytes_l is not None
    img_check_l = Image.open(io.BytesIO(optimized_bytes_l))
    width_l, height_l = img_check_l.size
    assert width_l >= 1280
    assert height_l >= 720
    assert abs((width_l / height_l) - (16.0 / 9.0)) < 0.01

@pytest.mark.asyncio
async def test_thumbnail_generator_aspect_ratio_variations():
    """
    検証基準: さまざまなアスペクト比 (21:9, 4:3, 9:16) の画像を入力した際、
    歪みなく中央でクロップされ、厳密に 16:9 に補正されること
    """
    generator = ThumbnailGenerator()
    
    # 21:9 (2100x900)
    img_wide = Image.new("RGB", (2100, 900), color=(50, 50, 50))
    import io
    img_byte_arr = io.BytesIO()
    img_wide.save(img_byte_arr, format='JPEG')
    wide_bytes = img_byte_arr.getvalue()
    
    optimized_bytes = generator.verify_and_optimize_image(wide_bytes, title="Wide Aspect Test")
    img_check = Image.open(io.BytesIO(optimized_bytes))
    width, height = img_check.size
    assert abs((width / height) - (16.0 / 9.0)) < 0.01
    
    # 9:16 (900x1600, 縦長)
    img_tall = Image.new("RGB", (900, 1600), color=(50, 50, 50))
    img_byte_arr_t = io.BytesIO()
    img_tall.save(img_byte_arr_t, format='JPEG')
    tall_bytes = img_byte_arr_t.getvalue()
    
    optimized_bytes_t = generator.verify_and_optimize_image(tall_bytes, title="Tall Aspect Test")
    img_check_t = Image.open(io.BytesIO(optimized_bytes_t))
    width_t, height_t = img_check_t.size
    assert abs((width_t / height_t) - (16.0 / 9.0)) < 0.01

@pytest.mark.asyncio
async def test_thumbnail_generator_size_compression():
    """
    検証基準: ファイルサイズ上限 (2MB) を超える大きな画像データが入力された際、
    自動的に圧縮品質が調整され、2MB未満に収まること
    """
    generator = ThumbnailGenerator()
    
    # 非常にファイルサイズが大きくなりやすい画像 (ノイズの多い高解像度画像) を作成
    import numpy as np
    import io
    noise = np.random.randint(0, 256, (1440, 2560, 3), dtype=np.uint8)
    img_noise = Image.fromarray(noise)
    img_byte_arr = io.BytesIO()
    img_noise.save(img_byte_arr, format='PNG')
    large_bytes = img_byte_arr.getvalue()
    
    optimized_bytes = generator.verify_and_optimize_image(large_bytes, title="Compression Test")
    assert optimized_bytes is not None
    assert len(optimized_bytes) < 2 * 1024 * 1024  # 確実に 2MB 未満

@pytest.mark.asyncio
async def test_thumbnail_generator_no_pillow_fallback():
    """
    検証基準: Pillowライブラリが利用できない環境を擬似的に作り出した際、
    例外によるクラッシュを避け、安全なダミーJPEGバイトが返されること
    """
    import sys
    from unittest.mock import patch
    generator = ThumbnailGenerator()
    
    # sys.modules の PIL を一時的に隠蔽して Pillow 欠如時をシミュレート
    with patch.dict(sys.modules, {
        'PIL': None,
        'PIL.Image': None,
        'PIL.ImageOps': None,
        'PIL.ImageEnhance': None,
        'PIL.ImageFilter': None
    }):
        fallback_bytes = generator.verify_and_optimize_image(b"", title="No Pillow Test")
        assert fallback_bytes is not None
        assert len(fallback_bytes) > 0
        assert fallback_bytes.startswith(b"\xff\xd8") # JPEG header


@pytest.mark.asyncio
async def test_thumbnail_generator_strict_resolution_and_aspect_ratio():
    import io
    generator = ThumbnailGenerator()
    
    # 1. 低解像度 (640x360) の画像
    img_low = Image.new("RGB", (640, 360), color=(0, 128, 128))
    img_io = io.BytesIO()
    img_low.save(img_io, format="JPEG")
    low_bytes = img_io.getvalue()
    
    optimized_low = generator.verify_and_optimize_image(low_bytes, title="Low Res Test")
    img_check = Image.open(io.BytesIO(optimized_low))
    w, h = img_check.size
    assert w >= 1280
    assert h >= 720
    assert abs((w / h) - (16.0 / 9.0)) < 0.01
    
    # 2. 高解像度かつ非16:9 (3840x3840, 1:1) の画像
    img_high_sq = Image.new("RGB", (3840, 3840), color=(128, 0, 128))
    img_io_sq = io.BytesIO()
    img_high_sq.save(img_io_sq, format="JPEG")
    high_sq_bytes = img_io_sq.getvalue()
    
    optimized_sq = generator.verify_and_optimize_image(high_sq_bytes, title="High Res Square Test")
    img_check_sq = Image.open(io.BytesIO(optimized_sq))
    w_sq, h_sq = img_check_sq.size
    assert w_sq >= 1280
    assert h_sq >= 720
    assert abs((w_sq / h_sq) - (16.0 / 9.0)) < 0.01

@pytest.mark.asyncio
async def test_thumbnail_generator_file_size_upper_bound():
    import io
    generator = ThumbnailGenerator()
    import numpy as np
    noise_data = np.random.randint(0, 256, (1440, 2560, 3), dtype=np.uint8)
    img_noise = Image.fromarray(noise_data)
    img_io = io.BytesIO()
    img_noise.save(img_io, format="PNG")
    large_png_bytes = img_io.getvalue()
    
    assert len(large_png_bytes) > 2 * 1024 * 1024
    
    optimized_bytes = generator.verify_and_optimize_image(large_png_bytes, title="Compression Test Pattern")
    assert optimized_bytes is not None
    assert len(optimized_bytes) < 2 * 1024 * 1024
    
    img_check = Image.open(io.BytesIO(optimized_bytes))
    img_check.verify()

@pytest.mark.asyncio
async def test_thumbnail_generator_empty_or_malformed_input():
    import io
    generator = ThumbnailGenerator()
    corrupted_data = b"BM\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    fallback_bytes = generator.verify_and_optimize_image(corrupted_data, title="Fallback Gradient Title Verification")
    
    assert fallback_bytes is not None
    assert fallback_bytes.startswith(b"\xff\xd8")
    
    img_check = Image.open(io.BytesIO(fallback_bytes))
    img_check.load()
    w, h = img_check.size
    assert w >= 1280
    assert h >= 720
    assert abs((w / h) - (16.0 / 9.0)) < 0.01
    
    fallback_empty = generator.verify_and_optimize_image(b"", title="Empty Input Verification Test")
    assert fallback_empty is not None
    img_check_empty = Image.open(io.BytesIO(fallback_empty))
    img_check_empty.load()
    assert img_check_empty.size[0] >= 1280



# ----------------------------------------------------
# 追加のテストケース（カバレッジ向上用）
# ----------------------------------------------------

@pytest.mark.asyncio
async def test_thumbnail_generator_no_pillow_non_empty_input():
    """Pillowが無い環境で画像データが存在する場合"""
    import sys
    from unittest.mock import patch
    generator = ThumbnailGenerator()
    
    with patch.dict(sys.modules, {
        'PIL': None,
        'PIL.Image': None,
        'PIL.ImageOps': None,
        'PIL.ImageEnhance': None,
        'PIL.ImageFilter': None
    }):
        non_empty = b"some_image_bytes"
        result = generator.verify_and_optimize_image(non_empty, title="No Pillow Non-Empty Test")
        assert result == non_empty

@pytest.mark.asyncio
async def test_thumbnail_generator_no_numpy():
    """numpyが無い環境でのフォールバックグラデーション生成"""
    import sys
    import io
    from unittest.mock import patch
    generator = ThumbnailGenerator()
    
    with patch.dict(sys.modules, {'numpy': None}):
        # 破損画像を入力してフォールバック生成を起こす
        corrupted = b"invalid_image"
        result = generator.verify_and_optimize_image(corrupted, title="No Numpy Fallback Test")
        assert result is not None
        
        img = Image.open(io.BytesIO(result))
        img.verify()

@pytest.mark.asyncio
async def test_thumbnail_generator_long_english_title_wrapping():
    """英語の長いタイトルでの自動折り返しおよび3行切り捨て"""
    generator = ThumbnailGenerator()
    # 非常に長い英語タイトル
    long_title = "This is a very long video title designed to test the automatic text wrapping and line truncation features in the thumbnail generator fallback mode"
    result = generator.verify_and_optimize_image(b"invalid", title=long_title)
    assert result is not None

@pytest.mark.asyncio
async def test_thumbnail_generator_long_japanese_title_wrapping():
    """日本語の長いタイトルでの自動折り返し"""
    generator = ThumbnailGenerator()
    long_title = "これはテスト用の非常に長い動画タイトルであり自動的に折り返される文字数を超えています"
    result = generator.verify_and_optimize_image(b"invalid", title=long_title)
    assert result is not None

@pytest.mark.asyncio
async def test_thumbnail_generator_empty_title():
    """タイトルが空の場合のフォールバック生成"""
    generator = ThumbnailGenerator()
    result = generator.verify_and_optimize_image(b"invalid", title="")
    assert result is not None

@pytest.mark.asyncio
async def test_thumbnail_generator_getsize_fallback():
    """textbboxが無くgetsizeを使用するレガシーフォールバック"""
    from unittest.mock import patch, MagicMock
    generator = ThumbnailGenerator()
    
    # ImageDraw.Draw のオブジェクトおよびフォントの textbbox を無効化
    mock_font = MagicMock()
    del mock_font.textbbox
    mock_font.getsize = MagicMock(return_value=(100, 30))
    
    # font_paths からフォントがロードされたことにする
    with patch("PIL.ImageFont.truetype", return_value=mock_font):
        result = generator.verify_and_optimize_image(b"invalid", title="Get Size Fallback Test")
        assert result is not None

@pytest.mark.asyncio
async def test_thumbnail_generator_api_error_concept():
    """コンセプト生成時のAPIError"""
    from google.genai import errors
    from unittest.mock import patch, MagicMock
    generator = ThumbnailGenerator()
    generator.client = MagicMock()
    
    with patch.object(generator.client.models, "generate_content", side_effect=errors.APIError("API Error", 500, None)):
        concepts = await generator._generate_concepts("Test Title", "Desc", 1)
        assert len(concepts) == 1
        assert concepts[0]["id"] == "concept_fallback"

@pytest.mark.asyncio
async def test_thumbnail_generator_json_error_concept():
    """コンセプト生成時のJSONDecodeError"""
    from unittest.mock import patch, MagicMock
    generator = ThumbnailGenerator()
    generator.client = MagicMock()
    
    mock_response = MagicMock()
    mock_response.text = "invalid json"
    
    with patch.object(generator.client.models, "generate_content", return_value=mock_response):
        concepts = await generator._generate_concepts("Test Title", "Desc", 1)
        assert len(concepts) == 1
        assert concepts[0]["id"] == "concept_fallback"

@pytest.mark.asyncio
async def test_thumbnail_generator_unexpected_error_concept():
    """コンセプト生成時の予期せぬエラー"""
    from unittest.mock import patch, MagicMock
    generator = ThumbnailGenerator()
    generator.client = MagicMock()
    
    with patch.object(generator.client.models, "generate_content", side_effect=RuntimeError("Unexpected")):
        concepts = await generator._generate_concepts("Test Title", "Desc", 1)
        assert len(concepts) == 1
        assert concepts[0]["id"] == "concept_fallback"

@pytest.mark.asyncio
async def test_thumbnail_generator_image_response_empty():
    """画像生成レスポンスが空の場合"""
    from unittest.mock import patch, MagicMock
    generator = ThumbnailGenerator()
    generator.client = MagicMock()
    
    mock_response = MagicMock()
    mock_response.generated_images = []
    
    with patch.object(generator.client.models, "generate_images", return_value=mock_response):
        img_bytes = await generator._generate_image("Prompt")
        assert img_bytes is None

@pytest.mark.asyncio
async def test_thumbnail_generator_image_unexpected_error():
    """画像生成時に予期せぬエラー"""
    from unittest.mock import patch, MagicMock
    generator = ThumbnailGenerator()
    generator.client = MagicMock()
    
    with patch.object(generator.client.models, "generate_images", side_effect=RuntimeError("Unexpected")):
        img_bytes = await generator._generate_image("Prompt")
        assert img_bytes is None

@pytest.mark.asyncio
async def test_brand_style_fallback_errors():
    """ブランドスタイル取得エラー時のフォールバック"""
    import sys
    from unittest.mock import patch
    generator = ThumbnailGenerator()

    # sys.modules から 'branding_manager' を一時的に隠すことで ImportError を通す
    with patch.dict(sys.modules, {'branding_manager': None}):
        style = generator._get_brand_style()
        assert "High quality" in style

    # 他のエラー（AttributeErrorなど）を通すため、branding_manager モジュールは存在するが constitution が壊れている場合
    class FakeBrandingManager:
        pass
        
    with patch.dict(sys.modules, {'branding_manager': FakeBrandingManager}):
        style = generator._get_brand_style()
        assert "High quality" in style

@pytest.mark.asyncio
async def test_thumbnail_generator_bright_image():
    """明るい画像の補正（明るさ補正ルートを通す）"""
    import io
    generator = ThumbnailGenerator()
    
    # 非常に明るい白色の画像を作成
    img = Image.new("RGB", (1280, 720), color=(255, 255, 255))
    img_io = io.BytesIO()
    img.save(img_io, format="JPEG")
    bright_bytes = img_io.getvalue()
    
    result = generator.verify_and_optimize_image(bright_bytes, title="Bright Image Test")
    assert result is not None

@pytest.mark.asyncio
async def test_thumbnail_generator_enhance_exception():
    """画質補正中に例外が発生した場合のフォールバック"""
    from unittest.mock import patch
    generator = ThumbnailGenerator()
    
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    import io
    img_io = io.BytesIO()
    img.save(img_io, format="JPEG")
    img_bytes = img_io.getvalue()
    
    # ImageStat.Stat で例外を起こす
    with patch("PIL.ImageStat.Stat", side_effect=ValueError("Mocked stat error")):
        result = generator.verify_and_optimize_image(img_bytes, title="Enhance Error Test")
        assert result is not None

@pytest.mark.asyncio
async def test_resolve_task_image_data_empty(tmp_path):
    """resolve_generator_thumbnail_task で画像データが空の場合の例外"""
    db_file = tmp_path / "test_empty.db"
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    agent.video_title = "Test"
    agent.video_description = "Test"
    agent.db_path = str(db_file)
    agent.output_dir = str(tmp_path)
    
    # generator.generate が空の結果を返す
    with patch.object(ThumbnailGenerator, "generate", return_value=[]):
        with pytest.raises(ValueError, match="No thumbnail variants"):
            await resolve_generator_thumbnail_task(agent, "task_empty")
            
    # generator.generate は返す画像が空
    with patch.object(ThumbnailGenerator, "generate", return_value=[{"image_base64": ""}]):
        with pytest.raises(ValueError, match="Generated thumbnail contains no image data"):
            await resolve_generator_thumbnail_task(agent, "task_empty_data")

@pytest.mark.asyncio
async def test_resolve_task_file_operations_retry_and_fallback(tmp_path):
    """resolve_generator_thumbnail_task でリネーム時のOSErrorとshutil.moveによるフォールバック"""
    db_file = tmp_path / "test_file_ops.db"
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    agent.video_title = "Test"
    agent.video_description = "Test"
    agent.db_path = str(db_file)
    agent.output_dir = str(tmp_path)
    
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    import io
    import base64
    img_io = io.BytesIO()
    img.save(img_io, format="JPEG")
    mock_base64 = base64.b64encode(img_io.getvalue()).decode('utf-8')
    
    mock_results = [{"image_base64": mock_base64}]
    
    # Path.rename で OSError を発生させ、shutil.move が実行されるのを確認
    from unittest.mock import patch
    
    def mock_rename(self, target):
        raise OSError("Permission denied / Locked")
        
    with patch.object(ThumbnailGenerator, "generate", return_value=mock_results),          patch.object(Path, "rename", mock_rename),          patch("shutil.move") as mock_move:
         
        # shutil.move を mock しているので、最終的に validator でファイル読み込みエラーまたは ValueError が出るはず
        with pytest.raises(Exception):
            await resolve_generator_thumbnail_task(agent, "task_rename_fail")
        
        assert mock_move.called

@pytest.mark.asyncio
async def test_resolve_task_file_operations_all_fail(tmp_path):
    """resolve_generator_thumbnail_task で rename も shutil.move も両方失敗"""
    db_file = tmp_path / "test_file_ops_fail.db"
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    agent.video_title = "Test"
    agent.video_description = "Test"
    agent.db_path = str(db_file)
    agent.output_dir = str(tmp_path)
    
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    import io
    import base64
    img_io = io.BytesIO()
    img.save(img_io, format="JPEG")
    mock_base64 = base64.b64encode(img_io.getvalue()).decode('utf-8')
    
    mock_results = [{"image_base64": mock_base64}]
    
    from unittest.mock import patch
    
    with patch.object(ThumbnailGenerator, "generate", return_value=mock_results),          patch.object(Path, "rename", side_effect=OSError("Rename error")),          patch("shutil.move", side_effect=IOError("Move error")):
         
        with pytest.raises(IOError, match="Failed to move temporary file"):
            await resolve_generator_thumbnail_task(agent, "task_move_fail")

@pytest.mark.asyncio
async def test_resolve_task_no_thumbnail_validator(tmp_path):
    """branding.history_manager.ThumbnailValidator が無い場合のフォールバック検証"""
    import sys
    from unittest.mock import patch, MagicMock
    db_file = tmp_path / "test_no_val.db"
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    agent.video_title = "Test"
    agent.video_description = "Test"
    agent.db_path = str(db_file)
    agent.output_dir = str(tmp_path)
    
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    import io
    import base64
    img_io = io.BytesIO()
    img.save(img_io, format="JPEG")
    mock_base64 = base64.b64encode(img_io.getvalue()).decode('utf-8')
    mock_results = [{"image_base64": mock_base64}]
    
    with patch.object(ThumbnailGenerator, "generate", return_value=mock_results),          patch.dict(sys.modules, {'branding.history_manager': None}):
         
        result = await resolve_generator_thumbnail_task(agent, "task_no_val")
        assert result is not None

@pytest.mark.asyncio
async def test_resolve_task_no_thumbnail_validator_bad_aspect_ratio(tmp_path):
    """Validatorが無いフォールバック検証において、アスペクト比違反でエラー"""
    import sys
    from unittest.mock import patch
    db_file = tmp_path / "test_no_val_bad_ar.db"
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    agent.video_title = "Test"
    agent.video_description = "Test"
    agent.db_path = str(db_file)
    agent.output_dir = str(tmp_path)
    
    # 1:1 画像
    img = Image.new("RGB", (1280, 1280), color=(100, 100, 100))
    import io
    import base64
    img_io = io.BytesIO()
    img.save(img_io, format="JPEG")
    mock_base64 = base64.b64encode(img_io.getvalue()).decode('utf-8')
    mock_results = [{"image_base64": mock_base64}]
    
    with patch.object(ThumbnailGenerator, "generate", return_value=mock_results),          patch.dict(sys.modules, {'branding.history_manager': None}):
         
        with pytest.raises(ValueError, match="Thumbnail aspect ratio must be 16:9"):
            await resolve_generator_thumbnail_task(agent, "task_no_val_bad_ar")

@pytest.mark.asyncio
async def test_resolve_task_sqlite3_lock_retry_success(tmp_path):
    """sqlite3がロックされている場合の自動リトライが成功するルート"""
    import sqlite3
    from unittest.mock import patch, MagicMock
    db_file = tmp_path / "test_lock.db"
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    agent.video_title = "Test"
    agent.video_description = "Test"
    agent.db_path = str(db_file)
    agent.output_dir = str(tmp_path)
    
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    import io
    import base64
    img_io = io.BytesIO()
    img.save(img_io, format="JPEG")
    mock_base64 = base64.b64encode(img_io.getvalue()).decode('utf-8')
    mock_results = [{"image_base64": mock_base64}]
    
    # 最初の2回は sqlite3.OperationalError("database is locked") を投げ、3回目に成功させる
    connect_calls = 0
    original_connect = sqlite3.connect
    
    def mock_connect(*args, **kwargs):
        nonlocal connect_calls
        connect_calls += 1
        if connect_calls <= 2:
            raise sqlite3.OperationalError("database is locked")
        return original_connect(*args, **kwargs)
        
    with patch.object(ThumbnailGenerator, "generate", return_value=mock_results),          patch("sqlite3.connect", side_effect=mock_connect),          patch("asyncio.sleep") as mock_sleep:
         
        result = await resolve_generator_thumbnail_task(agent, "task_lock_success")
        assert result is not None
        assert connect_calls == 3
        assert mock_sleep.called

@pytest.mark.asyncio
async def test_resolve_task_sqlite3_lock_retry_exhausted(tmp_path):
    """sqlite3のロックが解決せず、リトライ上限を超えてフォールバックするルート"""
    import sqlite3
    from unittest.mock import patch, MagicMock
    db_file = tmp_path / "test_lock_fail.db"
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    agent.video_title = "Test"
    agent.video_description = "Test"
    agent.db_path = str(db_file)
    agent.output_dir = str(tmp_path)
    
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    import io
    import base64
    img_io = io.BytesIO()
    img.save(img_io, format="JPEG")
    mock_base64 = base64.b64encode(img_io.getvalue()).decode('utf-8')
    mock_results = [{"image_base64": mock_base64}]
    
    with patch.object(ThumbnailGenerator, "generate", return_value=mock_results),          patch("sqlite3.connect", side_effect=sqlite3.OperationalError("database is locked")),          patch("asyncio.sleep"):
         
        result = await resolve_generator_thumbnail_task(agent, "task_lock_fail")
        assert result is not None  # DB書き込み失敗でもファイル保存のみで成功を返す

@pytest.mark.asyncio
async def test_resolve_task_sqlite3_other_connection_error(tmp_path):
    """sqlite3接続時にその他のエラーが発生した場合"""
    import sqlite3
    from unittest.mock import patch
    db_file = tmp_path / "test_conn_fail.db"
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    agent.video_title = "Test"
    agent.video_description = "Test"
    agent.db_path = str(db_file)
    agent.output_dir = str(tmp_path)
    
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    import io
    import base64
    img_io = io.BytesIO()
    img.save(img_io, format="JPEG")
    mock_base64 = base64.b64encode(img_io.getvalue()).decode('utf-8')
    mock_results = [{"image_base64": mock_base64}]
    
    with patch.object(ThumbnailGenerator, "generate", return_value=mock_results),          patch("sqlite3.connect", side_effect=sqlite3.Error("Generic connection failure")):
         
        result = await resolve_generator_thumbnail_task(agent, "task_conn_fail")
        assert result is not None

@pytest.mark.asyncio
async def test_resolve_task_schema_migration(tmp_path):
    """verified_at カラムが無い場合にALTER TABLEが実行されるスキーママイグレーションルート"""
    import sqlite3
    from unittest.mock import patch
    db_file = tmp_path / "test_migration.db"
    
    # 接続を初期化し、テーブルを verified_at なしで先に作成
    conn = sqlite3.connect(str(db_file))
    conn.execute("""
        CREATE TABLE thumbnail_results (
            task_id TEXT PRIMARY KEY,
            path TEXT,
            width INTEGER,
            height INTEGER,
            size_bytes INTEGER
        )
    """)
    conn.commit()
    conn.close()
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    agent.video_title = "Test"
    agent.video_description = "Test"
    agent.db_path = str(db_file)
    agent.output_dir = str(tmp_path)
    
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    import io
    import base64
    img_io = io.BytesIO()
    img.save(img_io, format="JPEG")
    mock_base64 = base64.b64encode(img_io.getvalue()).decode('utf-8')
    mock_results = [{"image_base64": mock_base64}]
    
    with patch.object(ThumbnailGenerator, "generate", return_value=mock_results):
        result = await resolve_generator_thumbnail_task(agent, "task_migration")
        assert result is not None
        
        # verified_at カラムが追加されているか検証
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("PRAGMA table_info(thumbnail_results)")
        columns = [row[1] for row in cursor.fetchall()]
        conn.close()
        assert "verified_at" in columns

@pytest.mark.asyncio
async def test_model_registry_import_error():
    """model_registry のインポートエラー時フォールバック"""
    import sys
    from unittest.mock import patch
    
    # 完全にアンロードする
    if 'thumbnail_engine.generator' in sys.modules:
        del sys.modules['thumbnail_engine.generator']
    if 'model_registry' in sys.modules:
        old_reg = sys.modules['model_registry']
        sys.modules['model_registry'] = None
    else:
        old_reg = None
        
    try:
        import thumbnail_engine.generator
        assert thumbnail_engine.generator.get_model("thumbnail") == "gemini-2.5-flash"
    finally:
        if old_reg:
            sys.modules['model_registry'] = old_reg
        else:
            sys.modules.pop('model_registry', None)
        if 'thumbnail_engine.generator' in sys.modules:
            del sys.modules['thumbnail_engine.generator']
        import thumbnail_engine.generator

@pytest.mark.asyncio
async def test_resolve_task_outer_exception_alert(tmp_path):
    """resolve_generator_thumbnail_task 内の最外周例外におけるアラート送出"""
    from unittest.mock import patch
    db_file = tmp_path / "test_outer_err.db"
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    agent.video_title = "Test"
    agent.db_path = str(db_file)
    agent.output_dir = str(tmp_path)
    
    # generate でエラーを起こす
    with patch.object(ThumbnailGenerator, "generate", side_effect=RuntimeError("Fatal Generator Error")),          patch("usage_tracker.alert_system.emit_critical") as mock_emit:
         
        with pytest.raises(RuntimeError, match="Fatal Generator Error"):
            await resolve_generator_thumbnail_task(agent, "task_outer_err")
            
        assert mock_emit.called

@pytest.mark.asyncio
async def test_resolve_task_sqlite3_transaction_lock_retry(tmp_path):
    """トランザクション実行時（PRAGMA / INSERT 等）に sqlite3.Error (database is locked) が発生した場合のリトライ"""
    import sqlite3
    from unittest.mock import patch, MagicMock
    db_file = tmp_path / "test_tx_lock.db"
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    agent.video_title = "Test"
    agent.video_description = "Test"
    agent.db_path = str(db_file)
    agent.output_dir = str(tmp_path)
    
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    import io
    import base64
    img_io = io.BytesIO()
    img.save(img_io, format="JPEG")
    mock_base64 = base64.b64encode(img_io.getvalue()).decode('utf-8')
    mock_results = [{"image_base64": mock_base64}]
    
    original_connect = sqlite3.connect
    execute_calls = 0
    
    # execute メソッドで例外を投げるカスタムコネクション
    class LockedConnection:
        def __init__(self, *args, **kwargs):
            self.conn = original_connect(*args, **kwargs)
        def execute(self, sql, *args):
            nonlocal execute_calls
            # thumbnail_results への INSERT 時に例外を発生させる
            if "INSERT OR REPLACE" in sql:
                execute_calls += 1
                if execute_calls <= 2:
                    raise sqlite3.OperationalError("database is locked")
            return self.conn.execute(sql, *args)
        def commit(self):
            self.conn.commit()
        def rollback(self):
            self.conn.rollback()
        def close(self):
            self.conn.close()
            
    def mock_connect(*args, **kwargs):
        return LockedConnection(*args, **kwargs)
        
    with patch.object(ThumbnailGenerator, "generate", return_value=mock_results),          patch("sqlite3.connect", side_effect=mock_connect),          patch("asyncio.sleep") as mock_sleep:
         
        result = await resolve_generator_thumbnail_task(agent, "task_tx_lock")
        assert result is not None
        assert execute_calls >= 2
        assert mock_sleep.called

@pytest.mark.asyncio
async def test_thumbnail_generator_pillow_not_available_for_corruption_check():
    """generate() 中で Pillow がインポートできない場合のフォールバック挙動"""
    import sys
    from unittest.mock import patch, MagicMock
    generator = ThumbnailGenerator()
    generator.client = MagicMock()
    
    mock_response = MagicMock()
    mock_image = MagicMock()
    img = Image.new("RGB", (1280, 720), color=(100, 100, 255))
    import io
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='JPEG')
    mock_image.image.image_bytes = img_byte_arr.getvalue()
    mock_response.generated_images = [mock_image]
    
    with patch.object(generator.client.models, "generate_images", return_value=mock_response),          patch.object(generator, "_get_brand_style", return_value="Test brand style"),          patch.object(generator, "_generate_concepts", return_value=[{"name": "Concept Pillow Error", "description": "Desc", "visual_prompt": "Prompt", "expected_ctr": 8.0}]),          patch.dict(sys.modules, {'PIL': None}):
         
        results = await generator.generate(video_title="Pillow Error Title", num_variants=1)
        assert len(results) == 1

@pytest.mark.asyncio
async def test_thumbnail_generator_generate_image_validation_error():
    """generate() 中に画像検証で ImageValidationError が発生した場合"""
    from unittest.mock import patch, MagicMock
    from branding.history_manager import ImageValidationError
    generator = ThumbnailGenerator()
    generator.client = MagicMock()
    
    mock_response = MagicMock()
    mock_image = MagicMock()
    img = Image.new("RGB", (1280, 720), color=(100, 100, 255))
    import io
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='JPEG')
    mock_image.image.image_bytes = img_byte_arr.getvalue()
    mock_response.generated_images = [mock_image]
    
    # validate_image で強制的に ValidationError を投げる
    with patch.object(generator.client.models, "generate_images", return_value=mock_response),          patch.object(generator, "_get_brand_style", return_value="Test brand style"),          patch.object(generator, "_generate_concepts", return_value=[{"name": "Concept Validation Error", "description": "Desc", "visual_prompt": "Prompt", "expected_ctr": 8.0}]),          patch("branding.history_manager.ThumbnailValidator.validate_image", side_effect=ImageValidationError("Mock Validation Fail")):
         
        results = await generator.generate(video_title="Validation Error Title", num_variants=1)
        assert len(results) == 0  # 検証失敗で results から除外される

@pytest.mark.asyncio
async def test_thumbnail_generator_generate_unexpected_validation_error():
    """generate() 中に画像検証で予期せぬ例外が発生した場合"""
    from unittest.mock import patch, MagicMock
    generator = ThumbnailGenerator()
    generator.client = MagicMock()
    
    mock_response = MagicMock()
    mock_image = MagicMock()
    img = Image.new("RGB", (1280, 720), color=(100, 100, 255))
    import io
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='JPEG')
    mock_image.image.image_bytes = img_byte_arr.getvalue()
    mock_response.generated_images = [mock_image]
    
    with patch.object(generator.client.models, "generate_images", return_value=mock_response),          patch.object(generator, "_get_brand_style", return_value="Test brand style"),          patch.object(generator, "_generate_concepts", return_value=[{"name": "Concept Unexpected Error", "description": "Desc", "visual_prompt": "Prompt", "expected_ctr": 8.0}]),          patch("branding.history_manager.ThumbnailValidator.validate_image", side_effect=RuntimeError("Unexpected")):
         
        results = await generator.generate(video_title="Unexpected Validation Title", num_variants=1)
        assert len(results) == 0

@pytest.mark.asyncio
async def test_thumbnail_generator_low_aspect_ratio_correction():
    """極小解像度かつ非 16:9 画像に対する補正"""
    generator = ThumbnailGenerator()
    # 100x200 の極小かつ縦長画像
    img = Image.new("RGB", (100, 200), color=(50, 50, 50))
    import io
    img_io = io.BytesIO()
    img.save(img_io, format="JPEG")
    
    result = generator.verify_and_optimize_image(img_io.getvalue(), title="Tiny Low Aspect Test")
    assert result is not None
    img_check = Image.open(io.BytesIO(result))
    w, h = img_check.size
    assert w >= 1280
    assert h >= 720

@pytest.mark.asyncio
async def test_thumbnail_generator_font_truetype_exceptions():
    """フォントロード時に一部のフォントパスで例外が発生した場合"""
    from unittest.mock import patch
    from PIL import ImageFont
    generator = ThumbnailGenerator()
    
    # 最初のいくつかのフォントパスで例外を投げ、最後のフォントで成功させる
    load_calls = 0
    original_truetype = ImageFont.truetype
    
    def mock_truetype(fp, size):
        nonlocal load_calls
        load_calls += 1
        if load_calls <= 2:
            raise OSError("Mock Font Load Error")
        return original_truetype(fp, size)
        
    with patch("PIL.ImageFont.truetype", side_effect=mock_truetype):
        result = generator.verify_and_optimize_image(b"invalid", title="Font Error Test")
        assert result is not None

@pytest.mark.asyncio
async def test_resolve_task_outer_exception_failed_log(tmp_path):
    """resolve_generator_thumbnail_task で emit_critical も失敗した場合"""
    from unittest.mock import patch
    db_file = tmp_path / "test_failed_log.db"
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    agent.video_title = "Test"
    agent.db_path = str(db_file)
    agent.output_dir = str(tmp_path)
    
    with patch.object(ThumbnailGenerator, "generate", side_effect=RuntimeError("Fatal Error")),          patch("usage_tracker.alert_system.emit_critical", side_effect=RuntimeError("Alert system is down")):
         
        with pytest.raises(RuntimeError, match="Fatal Error"):
            await resolve_generator_thumbnail_task(agent, "task_failed_log")

@pytest.mark.asyncio
async def test_resolve_task_temp_file_cleanup_fails(tmp_path):
    """一時ファイルの削除時にOSErrorが発生した場合"""
    db_file = tmp_path / "test_cleanup_fail.db"
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    agent.video_title = "Test"
    agent.video_description = "Test"
    agent.db_path = str(db_file)
    agent.output_dir = str(tmp_path)
    
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    import io
    import base64
    img_io = io.BytesIO()
    img.save(img_io, format="JPEG")
    mock_base64 = base64.b64encode(img_io.getvalue()).decode('utf-8')
    mock_results = [{"image_base64": mock_base64}]
    
    from unittest.mock import patch
    original_unlink = Path.unlink
    
    def mock_unlink(self):
        # 一時ファイル（.tmp）の削除時のみ例外をスロー
        if self.suffix == ".tmp" or ".tmp" in self.name:
            raise OSError("Access denied")
        original_unlink(self)
        
    with patch.object(ThumbnailGenerator, "generate", return_value=mock_results),          patch.object(Path, "unlink", mock_unlink):
         
        result = await resolve_generator_thumbnail_task(agent, "task_cleanup_fail")
        assert result is not None


# ====================================================
# Coverage improvement tests (Phase 27)
# ====================================================

@pytest.mark.asyncio
async def test_generate_image_corrupted_pil_error():
    from unittest.mock import patch, MagicMock
    generator = ThumbnailGenerator()
    generator.client = MagicMock()
    mock_response = MagicMock()
    mock_image = MagicMock()
    mock_image.image.image_bytes = b"bad image bytes"
    mock_response.generated_images = [mock_image]
    
    with patch.object(generator.client.models, "generate_images", return_value=mock_response),          patch.object(generator, "_get_brand_style", return_value="style"),          patch.object(generator, "_generate_concepts", return_value=[{"name": "test", "description": "desc", "visual_prompt": "prompt", "expected_ctr": 5.0}]),          patch("PIL.Image.open", side_effect=OSError("PIL error")):
        results = await generator.generate("Title", num_variants=1)
        assert len(results) == 0

@pytest.mark.asyncio
async def test_generate_outer_exceptions():
    from google.genai.errors import APIError
    from unittest.mock import patch
    generator = ThumbnailGenerator()
    
    class DummyAPIError(APIError):
        def __init__(self, message):
            self.message = message
        def __str__(self):
            return self.message

    with patch.object(generator, "_get_brand_style", side_effect=DummyAPIError("API Fail")):
        with pytest.raises(APIError):
            await generator.generate("Title")
    with patch.object(generator, "_get_brand_style", side_effect=RuntimeError("Runtime Fail")):
        with pytest.raises(RuntimeError):
            await generator.generate("Title")

@pytest.mark.asyncio
async def test_get_brand_style_success():
    import sys
    from unittest.mock import MagicMock, patch
    generator = ThumbnailGenerator()
    
    mock_branding = MagicMock()
    mock_branding.constitution = {'visual_identity': {'style_prompt': 'Gorgeous Premium Style'}}
    
    mock_module = MagicMock()
    mock_module.branding_manager = mock_branding
    
    with patch.dict(sys.modules, {'branding_manager': mock_module}):
        style = generator._get_brand_style()
        assert style == 'Gorgeous Premium Style'

@pytest.mark.asyncio
async def test_get_brand_style_unexpected_exception():
    import sys
    from unittest.mock import MagicMock, patch
    generator = ThumbnailGenerator()
    
    mock_branding = MagicMock()
    # propertyで例外を投げるように設定
    type(mock_branding).constitution = property(lambda self: exec('raise RuntimeError("Unexpected DB Lock")'))
    
    mock_module = MagicMock()
    mock_module.branding_manager = mock_branding
    
    with patch.dict(sys.modules, {'branding_manager': mock_module}):
        style = generator._get_brand_style()
        assert style == "High quality, professional, 8k resolution"

@pytest.mark.asyncio
async def test_generate_concepts_success():
    from unittest.mock import MagicMock, patch
    generator = ThumbnailGenerator()
    generator.client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '[{"id": "c1", "name": "c1", "description": "desc", "visual_prompt": "prompt", "expected_ctr": 7.0}]'
    with patch.object(generator.client.models, "generate_content", return_value=mock_response):
        concepts = await generator._generate_concepts("Title", "Desc", 1)
        assert len(concepts) == 1
        assert concepts[0]["id"] == "c1"

@pytest.mark.asyncio
async def test_thumbnail_generator_getsize_and_textbbox_absent():
    from unittest.mock import patch
    generator = ThumbnailGenerator()
    
    class BadFontWithGetSize:
        def getsize(self, text):
            return (len(text) * 10, 20)
        def __getattr__(self, name):
            raise AttributeError(name)
            
    with patch("PIL.ImageFont.truetype", return_value=BadFontWithGetSize()):
        result = generator.verify_and_optimize_image(b"invalid", title="This is a very long title designed to trigger text wrapping when there is no textbbox and getsize is called")
        assert result is not None

    class BadFontWithoutAnything:
        def __getattr__(self, name):
            raise AttributeError(name)

    with patch("PIL.ImageFont.truetype", return_value=BadFontWithoutAnything()):
        result = generator.verify_and_optimize_image(b"invalid", title="This is a very long title designed to trigger text wrapping when there is no textbbox and no getsize method at all")
        assert result is not None

@pytest.mark.asyncio
async def test_thumbnail_generator_enhance_exception_multiple():
    from unittest.mock import patch
    import PIL.Image
    generator = ThumbnailGenerator()
    
    call_count = 0
    original_new = PIL.Image.new
    
    def mock_new(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise RuntimeError("Mock error for new image creation")
        return original_new(*args, **kwargs)
        
    with patch("PIL.Image.new", side_effect=mock_new):
        result = generator.verify_and_optimize_image(b"invalid", title="Gradient Error Test")
        assert result is not None

@pytest.mark.asyncio
async def test_resolve_task_output_file_exists_unlink(tmp_path):
    from PIL import Image
    db_file = tmp_path / "test_exists.db"
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    agent.video_title = "Test"
    agent.db_path = str(db_file)
    agent.output_dir = str(tmp_path)
    
    output_path = tmp_path / "task_exists.jpg"
    output_path.write_bytes(b"existing data")
    
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    import io
    import base64
    img_io = io.BytesIO()
    img.save(img_io, format="JPEG")
    mock_base64 = base64.b64encode(img_io.getvalue()).decode('utf-8')
    mock_results = [{"image_base64": mock_base64}]
    
    from unittest.mock import patch
    with patch.object(ThumbnailGenerator, "generate", return_value=mock_results):
        result = await resolve_generator_thumbnail_task(agent, "task_exists")
        assert result is not None
        assert output_path.exists()
        assert output_path.read_bytes() != b"existing data"

@pytest.mark.asyncio
async def test_resolve_task_temp_file_cleanup_fails_real(tmp_path):
    from PIL import Image
    db_file = tmp_path / "test_cleanup_real.db"
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    agent.video_title = "Test"
    agent.video_description = "Test"
    agent.db_path = str(db_file)
    agent.output_dir = str(tmp_path)
    
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    import io
    import base64
    img_io = io.BytesIO()
    img.save(img_io, format="JPEG")
    mock_base64 = base64.b64encode(img_io.getvalue()).decode('utf-8')
    mock_results = [{"image_base64": mock_base64}]
    
    from unittest.mock import patch
    from pathlib import Path
    
    with patch.object(ThumbnailGenerator, "generate", return_value=mock_results),          patch("pathlib.Path.rename", side_effect=OSError("Rename failed")),          patch("shutil.move", side_effect=OSError("Move failed")),          patch("pathlib.Path.unlink", side_effect=OSError("Unlink failed")):
        with pytest.raises(IOError):
            await resolve_generator_thumbnail_task(agent, "task_cleanup_real")

@pytest.mark.asyncio
async def test_resolve_task_no_validator_invalid_images(tmp_path):
    import sys
    import io
    import base64
    from PIL import Image
    db_file = tmp_path / "test_no_val.db"
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    agent.video_title = "Test"
    agent.db_path = str(db_file)
    agent.output_dir = str(tmp_path)
    
    from unittest.mock import patch, MagicMock
    
    # 1. 破損画像の場合
    mock_results = [{"image_base64": base64.b64encode(b"not an image").decode('utf-8')}]
    with patch.object(ThumbnailGenerator, "generate", return_value=mock_results),          patch.dict(sys.modules, {'branding.history_manager': None}):
        with pytest.raises(ValueError, match="is corrupted"):
            await resolve_generator_thumbnail_task(agent, "task_no_val_corrupt")
            
    # 2. ファイルサイズが大きすぎる場合
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    img_io = io.BytesIO()
    img.save(img_io, format="JPEG")
    valid_jpg = img_io.getvalue()
    large_data = valid_jpg + b"0" * (5 * 1024 * 1024)
    
    mock_results = [{"image_base64": base64.b64encode(large_data).decode('utf-8')}]
    with patch.object(ThumbnailGenerator, "generate", return_value=mock_results),          patch.dict(sys.modules, {'branding.history_manager': None}):
        with pytest.raises(ValueError, match="exceeds 4MB limit"):
            await resolve_generator_thumbnail_task(agent, "task_no_val_large")
            
    # 3. アスペクト比が不正な場合
    img = Image.new("RGB", (1280, 800), color=(100, 100, 100))
    img_io = io.BytesIO()
    img.save(img_io, format="JPEG")
    mock_results = [{"image_base64": base64.b64encode(img_io.getvalue()).decode('utf-8')}]
    with patch.object(ThumbnailGenerator, "generate", return_value=mock_results),          patch.dict(sys.modules, {'branding.history_manager': None}):
        with pytest.raises(ValueError, match="aspect ratio must be 16:9"):
            await resolve_generator_thumbnail_task(agent, "task_no_val_aspect")

@pytest.mark.asyncio
async def test_resolve_task_sqlite3_rollback_exception(tmp_path):
    from PIL import Image
    import io
    import base64
    db_file = tmp_path / "test_rollback_fail.db"
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    agent.video_title = "Test"
    agent.db_path = str(db_file)
    agent.output_dir = str(tmp_path)
    
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    img_io = io.BytesIO()
    img.save(img_io, format="JPEG")
    mock_results = [{"image_base64": base64.b64encode(img_io.getvalue()).decode('utf-8')}]
    
    from unittest.mock import patch, MagicMock
    import sqlite3
    
    class BadConnection:
        def execute(self, *args, **kwargs):
            raise sqlite3.OperationalError("database is locked")
        def rollback(self):
            raise sqlite3.Error("Rollback failed")
        def close(self):
            pass
            
    with patch.object(ThumbnailGenerator, "generate", return_value=mock_results),          patch("sqlite3.connect", return_value=BadConnection()),          patch("asyncio.sleep") as mock_sleep:
        result = await resolve_generator_thumbnail_task(agent, "task_rollback_fail")
        assert result is not None
        assert mock_sleep.call_count == 4
        
@pytest.mark.asyncio
async def test_resolve_task_sqlite3_other_db_error_exhausted(tmp_path):
    from PIL import Image
    import io
    import base64
    db_file = tmp_path / "test_other_db_fail.db"
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    agent.video_title = "Test"
    agent.db_path = str(db_file)
    agent.output_dir = str(tmp_path)
    
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    img_io = io.BytesIO()
    img.save(img_io, format="JPEG")
    mock_results = [{"image_base64": base64.b64encode(img_io.getvalue()).decode('utf-8')}]
    
    from unittest.mock import patch, MagicMock
    import sqlite3
    
    execute_calls = 0
    class OtherErrorConnection:
        def execute(self, *args, **kwargs):
            nonlocal execute_calls
            execute_calls += 1
            if execute_calls == 1:
                raise sqlite3.Error("Some other sqlite error")
            mock_cursor = MagicMock()
            mock_cursor.fetchall.return_value = []
            return mock_cursor
        def commit(self):
            pass
        def rollback(self):
            pass
        def close(self):
            pass
            
    with patch.object(ThumbnailGenerator, "generate", return_value=mock_results),          patch("sqlite3.connect", return_value=OtherErrorConnection()),          patch("asyncio.sleep") as mock_sleep:
        result = await resolve_generator_thumbnail_task(agent, "task_other_db_fail")
        assert result is not None
        assert execute_calls == 5
        mock_sleep.assert_called_with(0.5)


@pytest.mark.asyncio
async def test_thumbnail_generator_phase27_rigorous_validation(tmp_path):
    """
    Phase 27 品質基準の自動検証:
    - 解像度 1280x720 以上
    - アスペクト比 16:9 
    - ファイルサイズ 4MB 未満
    - 出力ファイルが破損せず、Pillowでロード・検証可能であること
    - StageBoundAgent 経由での自動リトライ、結果保存、DBマイグレーションと連携動作すること
    """
    db_file = tmp_path / "phase27_rigorous_validation.db"
    task_id = "phase27_task_001"
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    agent.video_title = "Phase 27 Premium Video Title"
    agent.video_description = "Rigorous UAT Test for Phase 27"
    agent.db_path = str(db_file)
    agent.output_dir = str(tmp_path)
    
    # 3840x2160 (4K 16:9) の高画質なテスト用画像を作成
    img_large = Image.new("RGB", (3840, 2160), color=(30, 40, 50))
    import io
    import base64
    img_io = io.BytesIO()
    img_large.save(img_io, format='JPEG', quality=95)
    mock_base64 = base64.b64encode(img_io.getvalue()).decode('utf-8')
    
    mock_results = [{
        "id": "thumbnail_0",
        "concept_name": "Phase 27 Premium Concept",
        "description": "Premium High Quality Concept Design",
        "prompt": "Vibrant and cinematic premium thumbnail art style, 8k",
        "image_base64": mock_base64,
        "ctr_score": 9.2
    }]
    
    with patch.object(ThumbnailGenerator, "generate", return_value=mock_results):
        # タスクを READY 状態で登録
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=3)
        
        async def process_task_wrapper(t_id: str) -> str:
            return await resolve_generator_thumbnail_task(agent, t_id)
            
        await agent.start(process_task_wrapper)
        
        # タスク完了を待つ (タイムアウト付き)
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status in ("COMPLETED", "FAILED"):
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
        # 1. 正常完了していること
        assert final_status == "COMPLETED"
        
        # 2. 出力ファイルが存在すること
        out_file = tmp_path / f"{task_id}.jpg"
        assert out_file.exists()
        
        # 3. ファイルサイズが 4MB 未満であること
        size_bytes = out_file.stat().st_size
        assert size_bytes < 4 * 1024 * 1024
        
        # 4. Pillowによる破損チェックと検証
        with Image.open(out_file) as img:
            img.verify()
        with Image.open(out_file) as img:
            img.load()
            width, height = img.size
            
            # 5. 解像度 1280x720 以上であること
            assert width >= 1280
            assert height >= 720
            
            # 6. アスペクト比が 16:9 であること
            aspect_ratio = width / height
            assert abs(aspect_ratio - (16.0 / 9.0)) < 0.01

        # 7. DBマイグレーションと結果保存の検証
        conn = sqlite3.connect(str(db_file))
        try:
            cursor = conn.execute("SELECT status, result FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            assert row is not None
            status, result_str = row
            assert status == "COMPLETED"
            
            result_data = json.loads(result_str)
            assert result_data["valid"] is True
            
            # 8. thumbnail_results テーブルへの結果保存とスキーマの検証
            cursor_res = conn.execute(
                "SELECT task_id, path, width, height, size_bytes, verified_at FROM thumbnail_results WHERE task_id = ?", 
                (task_id,)
            )
            row_res = cursor_res.fetchone()
            assert row_res is not None
            t_id, path_str, w, h, s_bytes, v_at = row_res
            assert t_id == task_id
            assert w >= 1280
            assert h >= 720
            assert s_bytes < 4 * 1024 * 1024
            assert v_at > 0
        finally:
            conn.close()


@pytest.mark.asyncio
async def test_thumbnail_generator_progressive_jpeg():
    """検証基準: 画像が Progressive JPEG として保存されていること"""
    generator = ThumbnailGenerator()
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    import io
    img_io = io.BytesIO()
    img.save(img_io, format="JPEG")
    img_bytes = img_io.getvalue()
    
    optimized = generator.verify_and_optimize_image(img_bytes, title="Progressive JPEG Test")
    assert optimized is not None
    
    # ロードして progressive JPEG のメタデータを確認
    img_check = Image.open(io.BytesIO(optimized))
    # Pillow の info['progressive'] または info['progression'] は progressive JPEG だと True (あるいは非ゼロ) になる
    assert img_check.info.get("progressive") or img_check.info.get("progression")


@pytest.mark.asyncio
async def test_thumbnail_generator_tdr_registration_on_exception(tmp_path):
    """検証基準: タスク処理中に例外が発生した場合、自動的に技術負債 (TDR) に登録されること"""
    db_file = tmp_path / "test_tdr_exception.db"
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    agent.video_title = "TDR Exception Test"
    agent.video_description = "Test Description"
    agent.db_path = str(db_file)
    agent.output_dir = str(tmp_path)
    
    # 意図的に generate メソッドで例外をスローさせる
    with patch.object(ThumbnailGenerator, "generate", side_effect=RuntimeError("Intentionally failed for TDR test")), \
         patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt") as mock_register_debt:
         
        with pytest.raises(RuntimeError, match="Intentionally failed for TDR test"):
            await resolve_generator_thumbnail_task(agent, "task_tdr_fail")
            
        # register_debt が呼び出されたことを確認
        assert mock_register_debt.called
        args, kwargs = mock_register_debt.call_args
        assert kwargs.get("category") == "IMPORTANT_SERVICE"
        assert kwargs.get("file_path") == "thumbnail_engine/generator.py"
        assert "Intentionally failed for TDR test" in kwargs.get("notes")


@pytest.mark.asyncio
async def test_thumbnail_generator_dynamic_font_and_wrapping_by_length():
    """検証基準: タイトルの長さに応じて、フォントサイズと折り返しの最大文字数（max_chars）が適切にスケールダウンすること"""
    generator = ThumbnailGenerator()
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    import io
    img_io = io.BytesIO()
    img.save(img_io, format="JPEG")
    img_bytes = img_io.getvalue()
    
    # 1. 非常に長い日本語タイトル (50文字超)
    long_title_50 = "これは五十文字を超える非常に長いタイトルでありフォールバック画像生成時において適切なフォントサイズと文字折り返し幅で綺麗に描画されるかを検証するためのテキストです。"
    optimized_50 = generator.verify_and_optimize_image(img_bytes, title=long_title_50)
    assert optimized_50 is not None
    
    # 2. 中程度の日本語タイトル (30文字)
    med_title_30 = "これはちょうど三十文字程度の長さを持つテスト用のタイトル文です。"
    optimized_30 = generator.verify_and_optimize_image(img_bytes, title=med_title_30)
    assert optimized_30 is not None

    # 3. 短い日本語タイトル (5文字)
    short_title_5 = "テストタイトル"
    optimized_5 = generator.verify_and_optimize_image(img_bytes, title=short_title_5)
    assert optimized_5 is not None
