import pytest
from PIL import Image
import io
import base64
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
import sys
import os

# プロジェクトルートとbackendをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from thumbnail_engine.generator import generator as thumbnail_generator
from main import app

client = TestClient(app)

def create_dummy_image(width: int, height: int, target_size_bytes: int = 0) -> bytes:
    """テスト用のダミーJPEG画像バイナリを生成"""
    img = Image.new("RGB", (width, height), color="blue")
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='JPEG', quality=95)
    data = img_byte_arr.getvalue()
    
    # サイズ調整が必要な場合はパディングを追加
    if len(data) < target_size_bytes:
        data += b'\x00' * (target_size_bytes - len(data))
    return data

def test_dummy_image_helper():
    data = create_dummy_image(100, 100)
    assert len(data) > 0
    img = Image.open(io.BytesIO(data))
    assert img.size == (100, 100)

@pytest.mark.asyncio
async def test_verify_and_optimize_image_aspect_ratio():
    """アスペクト比が16:9でない画像（例: 3:2）を入力し、16:9に補正されるかテスト"""
    # 1500x1000 は 3:2
    input_data = create_dummy_image(1500, 1000)
    
    optimized_data = thumbnail_generator.verify_and_optimize_image(input_data)
    assert optimized_data is not None
    
    # 最適化後の画像のアスペクト比を検証
    img = Image.open(io.BytesIO(optimized_data))
    width, height = img.size
    
    # 16:9 アスペクト比に極めて近いこと (誤差2%以内)
    ratio = width / height
    assert abs(ratio - 16 / 9) < 0.02
    # 解像度がYouTube最小要件(640x360)以上、推奨解像度(1280x720)近辺であることを確認
    assert width >= 640
    assert height >= 360

@pytest.mark.asyncio
async def test_verify_and_optimize_image_file_size():
    """ファイルサイズが2MBを超える画像を圧縮し、2MB未満に補正されるかテスト"""
    # 2.2MBの画像データ
    input_data = create_dummy_image(3000, 2000, target_size_bytes=int(2.2 * 1024 * 1024))
    assert len(input_data) > 2 * 1024 * 1024
    
    optimized_data = thumbnail_generator.verify_and_optimize_image(input_data)
    assert optimized_data is not None
    assert len(optimized_data) < 2 * 1024 * 1024
    
    # 補正後も画像として妥当でアスペクト比が16:9であることを確認
    img = Image.open(io.BytesIO(optimized_data))
    width, height = img.size
    ratio = width / height
    assert abs(ratio - 16 / 9) < 0.02

@pytest.mark.asyncio
async def test_verify_and_optimize_image_resolution():
    """極端に小さい解像度の画像が、最小要件（640x360または1280x720）にアップスケールされるかテスト"""
    # 320x180 (16:9だが小さい)
    input_data = create_dummy_image(320, 180)
    
    optimized_data = thumbnail_generator.verify_and_optimize_image(input_data)
    assert optimized_data is not None
    
    img = Image.open(io.BytesIO(optimized_data))
    width, height = img.size
    assert width >= 640
    assert height >= 360

def test_api_thumbnail_generate_endpoint_validation():
    """FastAPI のエンドポイントに不正なパラメータを送信した際のバリデーションエラーテスト"""
    # 必須パラメータ video_title が無い
    response = client.post("/api/thumbnail/generate", json={
        "video_description": "テスト説明",
        "num_variants": 3
    })
    assert response.status_code == 422

@patch("thumbnail_engine.generator.generator._generate_concepts")
@patch("thumbnail_engine.generator.generator._generate_image")
def test_api_thumbnail_generate_success(mock_generate_image, mock_generate_concepts):
    """APIエンドポイントの正常系テスト。モック画像が最適化されて返されることを検証。"""
    # APIキーのモック
    with patch.object(thumbnail_generator, "api_key", "dummy_api_key"):
        # モック設定
        mock_generate_concepts.return_value = [
            {
                "id": "concept_0",
                "name": "テストコンセプト",
                "description": "テスト用詳細",
                "visual_prompt": "A beautiful cinematic thumbnail",
                "expected_ctr": 8.5,
                "emotion": "curiosity"
            }
        ]
        # モック画像として3:2のダミー画像を返す
        dummy_img = create_dummy_image(1500, 1000)
        mock_generate_image.return_value = dummy_img
        
        response = client.post("/api/thumbnail/generate", json={
            "video_title": "テスト動画タイトル",
            "video_description": "テスト動画説明",
            "num_variants": 1
        })
        
        assert response.status_code == 200
        res_data = response.json()
        assert len(res_data) == 1
        assert res_data[0]["concept_name"] == "テストコンセプト"
        assert "image_base64" in res_data[0]
        
        # 返された画像が16:9に最適化されているか検証
        img_data = base64.b64decode(res_data[0]["image_base64"])
        img = Image.open(io.BytesIO(img_data))
        width, height = img.size
        ratio = width / height
        assert abs(ratio - 16 / 9) < 0.02

def test_api_thumbnail_generate_missing_api_key():
    """APIキーが無い場合、500 Internal Server Error が返されることを検証"""
    # 異なるインポートパスによるパッチ漏れを防ぐため、複数のパスでapi_keyをNoneにする
    try:
        from routers.preview import thumbnail_generator as preview_gen
    except ImportError:
        preview_gen = None

    with patch.object(thumbnail_generator, "api_key", None):
        if preview_gen is not None:
            preview_gen.api_key = None
        response = client.post("/api/thumbnail/generate", json={
            "video_title": "テスト動画タイトル",
            "video_description": "テスト動画説明",
            "num_variants": 1
        })
        assert response.status_code == 500
        assert "Google AI API Key is not configured" in response.json()["detail"]


def test_api_render_thumbnail_success(tmp_path):
    """/api/render/thumbnail エンドポイントの正常系テスト。
    モック画像が生成され、品質基準を満たし、StageBoundAgent連携が機能することを検証。
    """
    db_file = tmp_path / "test_render_thumbnail_db.db"
    
    # thumbnail_generator.generate のモック
    with patch("thumbnail_engine.generator.generator.generate") as mock_generate:
        dummy_img = create_dummy_image(1280, 720)
        mock_generate.return_value = [
            {
                "id": "thumb_test_0",
                "concept_name": "テストコンセプト",
                "description": "テスト説明",
                "prompt": "A beautiful cinematic thumbnail",
                "image_base64": base64.b64encode(dummy_img).decode("utf-8"),
                "ctr_score": 8.5
            }
        ]
        
        response = client.post("/api/render/thumbnail", json={
            "video_title": "テスト動画タイトル",
            "video_description": "テスト動画説明",
            "width": 1280,
            "height": 720,
            "quality": 95,
            "db_path": str(db_file)
        })
        
        assert response.status_code == 200
        res_data = response.json()
        assert res_data["success"] is True
        assert len(res_data["thumbnails"]) == 1
        
        thumb = res_data["thumbnails"][0]
        assert thumb["width"] == 1280
        assert thumb["height"] == 720
        assert thumb["aspect_ratio"] == "1280:720"
        assert thumb["file_size_bytes"] > 0
        assert thumb["file_size_bytes"] < 4 * 1024 * 1024
        
        # Pillowで正常ロードできるか検証
        img_data = base64.b64decode(thumb["image_base64"])
        img = Image.open(io.BytesIO(img_data))
        img.load()
        assert img.size == (1280, 720)

def test_api_render_thumbnail_invalid_resolution(tmp_path):
    """解像度が 1280x720 未満の場合に 400 Bad Request を返すことを検証"""
    db_file = tmp_path / "test_render_thumbnail_db.db"
    response = client.post("/api/render/thumbnail", json={
        "video_title": "テスト動画タイトル",
        "width": 640,
        "height": 360,
        "db_path": str(db_file)
    })
    assert response.status_code == 400
    assert "Resolution must be at least 1280x720" in response.json()["detail"]

def test_api_render_thumbnail_invalid_aspect_ratio(tmp_path):
    """アスペクト比が 16:9 ではない場合に 400 Bad Request を返すことを検証"""
    db_file = tmp_path / "test_render_thumbnail_db.db"
    response = client.post("/api/render/thumbnail", json={
        "video_title": "テスト動画タイトル",
        "width": 1280,
        "height": 960,  # 4:3
        "db_path": str(db_file)
    })
    assert response.status_code == 400
    assert "Unsupported aspect ratio" in response.json()["detail"]

def test_api_render_thumbnail_empty_title(tmp_path):
    """タイトルが空の場合に 400 Bad Request を返すことを検証"""
    db_file = tmp_path / "test_render_thumbnail_db.db"
    response = client.post("/api/render/thumbnail", json={
        "video_title": "   ",
        "width": 1280,
        "height": 720,
        "db_path": str(db_file)
    })
    assert response.status_code == 400
    assert "Video title cannot be empty" in response.json()["detail"]


def test_api_render_thumbnail_quality_verification(tmp_path):
    """
    追加テスト：生成されたサムネイル画像が以下の品質基準を満たすことを検証する。
    - 解像度が 1280x720 であること。
    - アスペクト比が 16:9 であること。
    - ファイルサイズが 4MB 未満であること。
    - 画像データが破損しておらず、Pillow で正常にロードできること。
    """
    db_file = tmp_path / "test_render_thumbnail_db_quality.db"
    
    # 4MBより少し小さい（例: 3.5MB）ダミー画像をモックで用意
    target_size = int(3.5 * 1024 * 1024)
    dummy_img = create_dummy_image(1280, 720, target_size_bytes=target_size)
    
    with patch("thumbnail_engine.generator.generator.generate") as mock_generate:
        mock_generate.return_value = [
            {
                "id": "thumb_test_quality",
                "concept_name": "品質検証コンセプト",
                "description": "品質検証用の説明",
                "prompt": "A high quality test thumbnail",
                "image_base64": base64.b64encode(dummy_img).decode("utf-8"),
                "ctr_score": 9.0
            }
        ]
        
        response = client.post("/api/render/thumbnail", json={
            "video_title": "品質検証テスト動画",
            "video_description": "品質検証テスト説明",
            "width": 1280,
            "height": 720,
            "quality": 90,
            "db_path": str(db_file)
        })
        
        assert response.status_code == 200
        res_data = response.json()
        assert res_data["success"] is True
        assert len(res_data["thumbnails"]) == 1
        
        thumb = res_data["thumbnails"][0]
        
        # 1. 解像度の検証 (1280x720)
        assert thumb["width"] == 1280
        assert thumb["height"] == 720
        
        # 2. アスペクト比の検証 (16:9)
        assert thumb["aspect_ratio"] == "1280:720"
        aspect_ratio = thumb["width"] / thumb["height"]
        assert abs(aspect_ratio - (16.0 / 9.0)) < 0.01
        
        # 3. ファイルサイズが 4MB 未満であることの検証
        file_size_bytes = thumb["file_size_bytes"]
        assert file_size_bytes < 4 * 1024 * 1024
        assert file_size_bytes > 0
        
        # 4. 画像データの破損チェック
        image_base64 = thumb["image_base64"]
        img_data = base64.b64decode(image_base64)
        img = Image.open(io.BytesIO(img_data))
        try:
            img.load()  # これが例外なく実行できれば破損していない
        except Exception as e:
            pytest.fail(f"生成された画像データが破損しています: {e}")


@patch("routers.render.BytesIO")
def test_api_render_thumbnail_exceeds_4mb_limit(mock_bytes_io, tmp_path):
    """
    ファイルサイズが 4MB 以上の画像をモック生成した場合に、
    500 Internal Server Error が返され、4MB制限超過のエラー詳細が含まれることを検証する。
    """
    db_file = tmp_path / "test_render_thumbnail_db_large.db"
    
    import io
    def dummy_bytes_io(*args, **kwargs):
        real_io = io.BytesIO(*args, **kwargs)
        if not args and not kwargs:
            real_io.getvalue = lambda: b'\x00' * int(4.5 * 1024 * 1024)
        return real_io
        
    mock_bytes_io.side_effect = dummy_bytes_io
    
    dummy_img = create_dummy_image(1280, 720)
    
    with patch("thumbnail_engine.generator.generator.generate") as mock_generate:
        mock_generate.return_value = [
            {
                "id": "thumb_test_too_large",
                "concept_name": "超過テスト",
                "description": "超過テスト",
                "prompt": "Too large image prompt",
                "image_base64": base64.b64encode(dummy_img).decode("utf-8"),
                "ctr_score": 5.0
            }
        ]
        
        response = client.post("/api/render/thumbnail", json={
            "video_title": "超過検証テスト動画",
            "width": 1280,
            "height": 720,
            "quality": 95,
            "db_path": str(db_file)
        })
        
        assert response.status_code == 500
        assert "exceeds 4MB limit" in response.json()["detail"]



