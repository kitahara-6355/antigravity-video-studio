import sys
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch

# プロジェクトルートとアーカイブディレクトリを sys.path に追加
ROOT_DIR = Path(__file__).parent.parent.resolve()
ARCHIVE_DIR = ROOT_DIR / "backend" / "archives" / "archive_stable_v3.0_20260118_0953"

sys.path.insert(0, str(ROOT_DIR / "backend"))
sys.path.insert(0, str(ARCHIVE_DIR))

# アーカイブ版 generation_engine をインポート
import os
os.environ.setdefault("GOOGLE_API_KEY", "dummy_api_key")
import generation_engine
from generation_engine import (
    GenerationType,
    GenerationRequest,
    GenerationResult,
    PromptOptimizer,
    ImagenGenerator,
    VeoGenerator,
    GenerationEngine
)

@pytest.fixture
def mock_genai_client():
    with patch("generation_engine.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        yield mock_client

@pytest.fixture
def mock_get_model():
    with patch("generation_engine.get_model") as mock_get:
        mock_get.return_value = "mocked-model"
        yield mock_get

def test_prompt_optimizer_success(mock_genai_client, mock_get_model):
    # Setup mock response
    mock_response = MagicMock()
    mock_response.text = "Optimized Japanese prompt text"
    mock_genai_client.models.generate_content.return_value = mock_response

    optimizer = PromptOptimizer()
    req = GenerationRequest(
        id="req_01",
        type=GenerationType.THUMBNAIL,
        prompt="テスト用プロンプト",
        context={"key": "val"},
        style_hints=["style1"]
    )
    
    result = optimizer.optimize(req)
    assert result == "Optimized Japanese prompt text"
    mock_genai_client.models.generate_content.assert_called_once()

def test_prompt_optimizer_failure_fallback(mock_genai_client, mock_get_model):
    # Setup mock to raise RuntimeError
    mock_genai_client.models.generate_content.side_effect = RuntimeError("API Error")

    optimizer = PromptOptimizer()
    req = GenerationRequest(
        id="req_02",
        type=GenerationType.THUMBNAIL,
        prompt="テスト用プロンプト",
        context={"key": "val"},
        style_hints=["style1"]
    )
    
    result = optimizer.optimize(req)
    # フォールバック処理が走るはず
    assert "テスト用プロンプト" in result
    assert "style1" in result
    assert "thumbnail" in result or "thumbnail style" in result

def test_imagen_generator_success_bytes(mock_genai_client, tmp_path):
    mock_image = MagicMock()
    mock_image.image.image_bytes = b"fake_png_data"
    # hasattr の挙動をモックするために spec を設定するか、または直接属性を持たせる
    del mock_image.image.image_bytes  # 一旦消して、hasattrで検知できるようにする
    
    # 実際の実装:
    # if hasattr(image_data, 'image') and hasattr(image_data.image, 'image_bytes'):
    # hasattr判定が機能するようにオブジェクトを構成
    mock_image_data = MagicMock()
    mock_image_data.image = MagicMock()
    mock_image_data.image.image_bytes = b"fake_png_data"
    
    mock_response = MagicMock()
    mock_response.generated_images = [mock_image_data]
    mock_genai_client.models.generate_images.return_value = mock_response

    generator = ImagenGenerator(output_dir=tmp_path)
    req = GenerationRequest(
        id="req_img_01",
        type=GenerationType.THUMBNAIL,
        prompt="Image prompt"
    )
    
    res = generator.generate("Optimized image prompt", req)
    assert res.success is True
    assert res.output_path is not None
    assert Path(res.output_path).exists()
    with open(res.output_path, "rb") as f:
        assert f.read() == b"fake_png_data"

def test_imagen_generator_success_base64(mock_genai_client, tmp_path):
    import base64
    encoded_data = base64.b64encode(b"fake_base64_png_data").decode("utf-8")
    
    mock_image_data = MagicMock()
    mock_image_data.image = MagicMock()
    # image_bytes 属性を持たせない（hasattr(image_data.image, 'image_bytes') が False になるようにする）
    del mock_image_data.image.image_bytes
    mock_image_data.image.image_bytes = encoded_data  # base64デコード対象となる文字列を設定
    
    mock_response = MagicMock()
    mock_response.generated_images = [mock_image_data]
    mock_genai_client.models.generate_images.return_value = mock_response

    generator = ImagenGenerator(output_dir=tmp_path)
    req = GenerationRequest(
        id="req_img_02",
        type=GenerationType.THUMBNAIL,
        prompt="Image prompt"
    )
    
    res = generator.generate("Optimized image prompt", req)
    assert res.success is True
    assert res.output_path is not None
    assert Path(res.output_path).exists()
    with open(res.output_path, "rb") as f:
        assert f.read() == b"fake_base64_png_data"

def test_imagen_generator_failure(mock_genai_client, tmp_path):
    mock_genai_client.models.generate_images.side_effect = ValueError("Imagen API Failure")

    generator = ImagenGenerator(output_dir=tmp_path)
    req = GenerationRequest(
        id="req_img_err",
        type=GenerationType.THUMBNAIL,
        prompt="Image prompt"
    )
    
    res = generator.generate("Optimized image prompt", req)
    assert res.success is False
    assert res.error == "Imagen API Failure"

def test_veo_generator_success(mock_genai_client, tmp_path):
    mock_video_data = MagicMock()
    mock_video_data.video = MagicMock()
    mock_video_data.video.video_bytes = b"fake_mp4_data"
    
    mock_response = MagicMock()
    mock_response.generated_videos = [mock_video_data]
    mock_genai_client.models.generate_videos.return_value = mock_response

    generator = VeoGenerator(output_dir=tmp_path)
    req = GenerationRequest(
        id="req_video_01",
        type=GenerationType.OPENING,
        prompt="Video prompt"
    )
    
    res = generator.generate("Optimized video prompt", req)
    assert res.success is True
    assert res.output_path is not None
    assert Path(res.output_path).exists()
    with open(res.output_path, "rb") as f:
        assert f.read() == b"fake_mp4_data"

def test_veo_generator_failure(mock_genai_client, tmp_path):
    mock_genai_client.models.generate_videos.side_effect = ValueError("Veo API Failure")

    generator = VeoGenerator(output_dir=tmp_path)
    req = GenerationRequest(
        id="req_video_err",
        type=GenerationType.OPENING,
        prompt="Video prompt"
    )
    
    res = generator.generate("Optimized video prompt", req)
    assert res.success is False
    assert res.error == "Veo API Failure"

def test_generation_engine_dispatch(mock_genai_client, mock_get_model, tmp_path):
    # Set up optimizer mock
    mock_opt_resp = MagicMock()
    mock_opt_resp.text = "Optimized text"
    mock_genai_client.models.generate_content.return_value = mock_opt_resp
    
    # Set up image generation mock
    mock_image_data = MagicMock()
    mock_image_data.image = MagicMock()
    mock_image_data.image.image_bytes = b"fake_png"
    mock_img_resp = MagicMock()
    mock_img_resp.generated_images = [mock_image_data]
    mock_genai_client.models.generate_images.return_value = mock_img_resp
    
    # Set up video generation mock
    mock_video_data = MagicMock()
    mock_video_data.video = MagicMock()
    mock_video_data.video.video_bytes = b"fake_mp4"
    mock_vid_resp = MagicMock()
    mock_vid_resp.generated_videos = [mock_video_data]
    mock_genai_client.models.generate_videos.return_value = mock_vid_resp

    engine = GenerationEngine(output_dir=tmp_path)
    
    # Image Type (Thumbnail)
    req_thumb = GenerationRequest(
        id="thumb_id",
        type=GenerationType.THUMBNAIL,
        prompt="Thumbnail prompt"
    )
    res_thumb = engine.generate(req_thumb)
    assert res_thumb.success is True
    assert "images" in res_thumb.output_path
    
    # Video Type (Opening)
    req_open = GenerationRequest(
        id="open_id",
        type=GenerationType.OPENING,
        prompt="Opening prompt"
    )
    res_open = engine.generate(req_open)
    assert res_open.success is True
    assert "videos" in res_open.output_path

def test_generation_engine_review(mock_genai_client, mock_get_model, tmp_path):
    # Set up mocks
    mock_opt_resp = MagicMock()
    mock_opt_resp.text = "Optimized text"
    mock_genai_client.models.generate_content.return_value = mock_opt_resp
    
    mock_image_data = MagicMock()
    mock_image_data.image = MagicMock()
    mock_image_data.image.image_bytes = b"fake_png"
    mock_img_resp = MagicMock()
    mock_img_resp.generated_images = [mock_image_data]
    mock_genai_client.models.generate_images.return_value = mock_img_resp

    engine = GenerationEngine(output_dir=tmp_path)
    
    # Mock Reviewer
    mock_reviewer = MagicMock()
    mock_review_result = MagicMock()
    mock_review_result.score.overall = 0.95
    mock_review_result.passed = True
    mock_review_result.issues = []
    mock_reviewer.review.return_value = mock_review_result
    engine.reviewer = mock_reviewer
    
    req = GenerationRequest(
        id="thumb_id",
        type=GenerationType.THUMBNAIL,
        prompt="Thumbnail prompt"
    )
    
    res = engine.generate(req)
    assert res.success is True
    assert res.quality_score == 0.95
    assert res.metadata["review"]["passed"] is True
    
    # Test Reviewer exception handling
    mock_reviewer.review.side_effect = RuntimeError("Review Failed")
    res_err = engine.generate(req)
    assert res_err.success is True  # Review failure shouldn't fail the whole generation
    assert res_err.quality_score == 0.85  # Review failure leaves the score at generator's value (0.85)

def test_prompt_optimizer_value_error_fallback(mock_genai_client, mock_get_model):
    # Setup mock to raise ValueError
    mock_genai_client.models.generate_content.side_effect = ValueError("Mock Value Error")

    optimizer = PromptOptimizer()
    req = GenerationRequest(
        id="req_03",
        type=GenerationType.THUMBNAIL,
        prompt="テスト用プロンプト",
        context={"key": "val"},
        style_hints=["style1"]
    )
    
    result = optimizer.optimize(req)
    # ValueErrorをキャッチしてフォールバック処理が走るはず
    assert "テスト用プロンプト" in result
    assert "style1" in result
    assert "thumbnail" in result

def test_imagen_generator_os_error_failure(mock_genai_client, tmp_path):
    mock_image_data = MagicMock()
    mock_image_data.image = MagicMock()
    mock_image_data.image.image_bytes = b"fake_png_data"
    
    mock_response = MagicMock()
    mock_response.generated_images = [mock_image_data]
    mock_genai_client.models.generate_images.return_value = mock_response

    generator = ImagenGenerator(output_dir=tmp_path)
    req = GenerationRequest(
        id="req_img_oserr",
        type=GenerationType.THUMBNAIL,
        prompt="Image prompt"
    )
    
    with patch("builtins.open", side_effect=OSError("Disk Full")):
        res = generator.generate("Optimized image prompt", req)
        
    assert res.success is False
    assert "Disk Full" in res.error

def test_veo_generator_os_error_failure(mock_genai_client, tmp_path):
    mock_video_data = MagicMock()
    mock_video_data.video = MagicMock()
    mock_video_data.video.video_bytes = b"fake_mp4_data"
    
    mock_response = MagicMock()
    mock_response.generated_videos = [mock_video_data]
    mock_genai_client.models.generate_videos.return_value = mock_response

    generator = VeoGenerator(output_dir=tmp_path)
    req = GenerationRequest(
        id="req_video_oserr",
        type=GenerationType.OPENING,
        prompt="Video prompt"
    )
    
    with patch("builtins.open", side_effect=OSError("Permission Denied")):
        res = generator.generate("Optimized video prompt", req)
        
    assert res.success is False
    assert "Permission Denied" in res.error
