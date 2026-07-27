import sys
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch, mock_open

# backend ディレクトリを sys.path に追加
ROOT_DIR = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT_DIR / "backend"))

# 本物の self_review_engine や API クライアントをインポート・初期化させないために
# 先行して sys.modules にダミーを登録する
mock_self_review = MagicMock()
mock_reviewer_instance = MagicMock()
mock_self_review.self_review_engine = mock_reviewer_instance
sys.modules["self_review_engine"] = mock_self_review

mock_gemini_factory = MagicMock()
mock_gemini_client_instance = MagicMock()
mock_gemini_factory.get_gemini_client.return_value = mock_gemini_client_instance
sys.modules["gemini_client_factory"] = mock_gemini_factory

mock_model_registry = MagicMock()
mock_model_registry.get_model.return_value = "mocked-model"
sys.modules["model_registry"] = mock_model_registry

# generation_engine をインポート
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
def mock_gemini_client():
    with patch("generation_engine.get_gemini_client") as mock_factory:
        mock_client = MagicMock()
        mock_factory.return_value = mock_client
        yield mock_client

@pytest.fixture
def mock_get_model():
    with patch("generation_engine.get_model") as mock_get:
        mock_get.return_value = "mocked-model"
        yield mock_get

def test_prompt_optimizer_constitution_not_found(mock_gemini_client, mock_get_model):
    # constitution.json が存在しない場合の挙動をテスト
    # Path.exists() が False を返すようにモックする
    with patch.object(Path, "exists", return_value=False):
        optimizer = PromptOptimizer()
        assert optimizer.constitution == {}

def test_prompt_optimizer_fallback_optimize_all_types(mock_gemini_client, mock_get_model):
    optimizer = PromptOptimizer()
    
    # 全ての GenerationType で _fallback_optimize が正しく文字列を生成することを検証
    for gtype in GenerationType:
        req = GenerationRequest(
            id=f"test_{gtype.value}",
            type=gtype,
            prompt="ベースプロンプト",
            style_hints=["ヒント1", "ヒント2"]
        )
        result = optimizer._fallback_optimize(req)
        assert "ベースプロンプト" in result
        assert "ヒント1, ヒント2" in result
        
        # 各タイプごとの品質指示が含まれていることを確認
        quality_hints = {
            GenerationType.THUMBNAIL: "high quality, professional, eye-catching, YouTube thumbnail style",
            GenerationType.SCENE_IMAGE: "cinematic, high resolution, detailed",
            GenerationType.TELOP_BACKGROUND: "subtle, text-friendly, gradient background",
            GenerationType.OPENING: "dynamic, professional intro, motion graphics",
            GenerationType.ENDING: "elegant, call to action, subscribe reminder",
            GenerationType.TRANSITION: "smooth, seamless, professional transition"
        }
        assert quality_hints[gtype] in result

def test_prompt_optimizer_optimize_exception_fallback(mock_gemini_client, mock_get_model):
    # API呼び出しで例外が発生したときに _fallback_optimize が呼ばれることをテスト
    mock_gemini_client.models.generate_content.side_effect = Exception("API Error")
    
    optimizer = PromptOptimizer()
    req = GenerationRequest(
        id="test_err",
        type=GenerationType.THUMBNAIL,
        prompt="例外テスト",
        style_hints=["テストスタイル"]
    )
    
    # 例外をキャッチしてフォールバック結果が返ってくるはず
    result = optimizer.optimize(req)
    assert "例外テスト" in result
    assert "テストスタイル" in result
    assert "YouTube thumbnail style" in result

def test_imagen_generator_coverage(mock_gemini_client, mock_get_model, tmp_path):
    import base64
    # アスペクト比ごとの検証も含めてテスト
    ratios = ["16:9", "1:1", "9:16", "4:3", "unknown_ratio"]
    for ratio in ratios:
        generator = ImagenGenerator(output_dir=tmp_path)
        
        # 1. 正常系 (bytes)
        mock_image_data = MagicMock()
        mock_image_data.image.image_bytes = b"fake_bytes"
        mock_response = MagicMock()
        mock_response.generated_images = [mock_image_data]
        mock_gemini_client.models.generate_images.return_value = mock_response
        
        req = GenerationRequest(
            id=f"test_img_{ratio.replace(':', '_')}",
            type=GenerationType.THUMBNAIL,
            prompt="テスト画像",
            aspect_ratio=ratio
        )
        
        result = generator.generate("最適化プロンプト", req)
        assert result.success is True
        assert result.output_path is not None
        assert Path(result.output_path).exists()
        
    # 2. base64 パス
    # hasattr をハックして else に入らせる
    mock_image_data = MagicMock()
    mock_image_data.image.image_bytes = base64.b64encode(b"fake_base64_bytes").decode("utf-8")
    mock_response = MagicMock()
    mock_response.generated_images = [mock_image_data]
    mock_gemini_client.models.generate_images.return_value = mock_response
    
    original_hasattr = hasattr
    def custom_hasattr(obj, name):
        if name == 'image_bytes' and obj is mock_image_data.image:
            return False
        return original_hasattr(obj, name)
        
    with patch("builtins.hasattr", custom_hasattr):
        generator = ImagenGenerator(output_dir=tmp_path)
        req = GenerationRequest(
            id="test_img_b64",
            type=GenerationType.THUMBNAIL,
            prompt="テスト画像"
        )
        result = generator.generate("最適化プロンプト", req)
        assert result.success is True
        assert Path(result.output_path).exists()
        with open(result.output_path, "rb") as f:
            assert f.read() == b"fake_base64_bytes"

    # 3. 生成画像が空の場合
    mock_response_empty = MagicMock()
    mock_response_empty.generated_images = []
    mock_gemini_client.models.generate_images.return_value = mock_response_empty
    
    result = generator.generate("最適化プロンプト", req)
    assert result.success is False
    assert result.error == "No images generated"

    # 4. 例外発生時
    mock_gemini_client.models.generate_images.side_effect = Exception("Imagen API Error")
    result = generator.generate("最適化プロンプト", req)
    assert result.success is False
    assert "Imagen API Error" in result.error

def test_veo_generator_coverage(mock_gemini_client, mock_get_model, tmp_path):
    import base64
    generator = VeoGenerator(output_dir=tmp_path)
    
    # 1. 正常系 (bytes) & duration境界値検証
    mock_video_data = MagicMock()
    mock_video_data.video.video_bytes = b"fake_video_bytes"
    mock_response = MagicMock()
    mock_response.generated_videos = [mock_video_data]
    mock_gemini_client.models.generate_videos.return_value = mock_response
    
    req = GenerationRequest(
        id="test_video_normal",
        type=GenerationType.OPENING,
        prompt="テスト動画",
        duration_sec=10.0  # 10秒を指定（上限8秒に制限されるはず）
    )
    
    result = generator.generate("最適化プロンプト", req)
    assert result.success is True
    assert result.output_path is not None
    assert Path(result.output_path).exists()
    
    # API呼び出し時のパラメータ検証 (min(request.duration_sec, 8) が 8 になっていること)
    mock_gemini_client.models.generate_videos.assert_called_once()
    called_args, called_kwargs = mock_gemini_client.models.generate_videos.call_args
    assert called_kwargs["config"]["duration_seconds"] == 8
    
    # 2. base64 パス
    mock_video_data_b64 = MagicMock()
    mock_video_data_b64.video.video_bytes = base64.b64encode(b"fake_video_b64_bytes").decode("utf-8")
    mock_response_b64 = MagicMock()
    mock_response_b64.generated_videos = [mock_video_data_b64]
    mock_gemini_client.models.generate_videos.return_value = mock_response_b64
    
    original_hasattr = hasattr
    def custom_hasattr_video(obj, name):
        if name == 'video_bytes' and obj is mock_video_data_b64.video:
            return False
        return original_hasattr(obj, name)
        
    with patch("builtins.hasattr", custom_hasattr_video):
        req_b64 = GenerationRequest(
            id="test_video_b64",
            type=GenerationType.OPENING,
            prompt="テスト動画"
        )
        result = generator.generate("最適化プロンプト", req_b64)
        assert result.success is True
        assert Path(result.output_path).exists()
        with open(result.output_path, "rb") as f:
            assert f.read() == b"fake_video_b64_bytes"

    # 3. 動画が空の場合
    mock_response_empty = MagicMock()
    mock_response_empty.generated_videos = []
    mock_gemini_client.models.generate_videos.return_value = mock_response_empty
    
    result = generator.generate("最適化プロンプト", req)
    assert result.success is False
    assert result.error == "No videos generated"

    # 4. 例外発生時
    mock_gemini_client.models.generate_videos.side_effect = Exception("Veo API Error")
    result = generator.generate("最適化プロンプト", req)
    assert result.success is False
    assert "Veo API Error" in result.error

def test_generation_engine_coverage(mock_gemini_client, mock_get_model, tmp_path):
    # 1. self_review_engine がインポート失敗した場合のテスト (307-308)
    with patch.dict("sys.modules", {"self_review_engine": None}):
        engine_no_reviewer = GenerationEngine(output_dir=tmp_path)
        assert engine_no_reviewer.reviewer is None
    
    # 2. reviewer が存在し、正常に機能する場合のテスト (335-345)
    # 本物の self_review_engine をインポートさせないために sys.modules をダミーにモックする
    with patch.dict("sys.modules", {"self_review_engine": mock_self_review}):
        engine = GenerationEngine(output_dir=tmp_path)
        
        # optimize のモック
        mock_optimizer = MagicMock()
        mock_optimizer.optimize.return_value = "最適化プロンプト"
        engine.prompt_optimizer = mock_optimizer
        
        # veo と imagen のモック
        mock_veo = MagicMock()
        mock_veo.generate.return_value = GenerationResult(
            request_id="test_video",
            success=True,
            output_path="path/to/video.mp4",
            optimized_prompt="最適化プロンプト"
        )
        engine.veo = mock_veo
        
        mock_imagen = MagicMock()
        mock_imagen.generate.return_value = GenerationResult(
            request_id="test_img",
            success=True,
            output_path="path/to/image.png",
            optimized_prompt="最適化プロンプト"
        )
        engine.imagen = mock_imagen
        
        # reviewer のモック
        mock_reviewer = MagicMock()
        mock_review_result = MagicMock()
        mock_review_result.score.overall = 0.9
        mock_review_result.passed = True
        mock_review_result.issues = ["なし"]
        mock_reviewer.review.return_value = mock_review_result
        engine.reviewer = mock_reviewer
        
        # 画像生成リクエスト
        req_img = GenerationRequest(
            id="req_img_01",
            type=GenerationType.THUMBNAIL,
            prompt="テスト"
        )
        result_img = engine.generate(req_img)
        assert result_img.success is True
        assert result_img.quality_score == 0.9
        assert result_img.metadata["review"]["passed"] is True
        
        # 動画生成リクエスト
        req_video = GenerationRequest(
            id="req_vid_01",
            type=GenerationType.OPENING,
            prompt="テスト動画"
        )
        result_video = engine.generate(req_video)
        assert result_video.success is True
        mock_veo.generate.assert_called_once_with("最適化プロンプト", req_video)
        
        # 3. reviewer が例外を投げる場合のテスト (346-347)
        mock_reviewer.review.side_effect = Exception("Review engine failed")
        result_img_err = engine.generate(req_img)
        assert result_img_err.success is True
        
        # 4. ショートカットメソッドのテスト (356-364, 370-378, 385-393)
        res_thumb = engine.generate_thumbnail("タイトル", context={"episode": 1}, style="anime")
        assert res_thumb.success is True
        
        res_open = engine.generate_opening("チャンネル名", duration_sec=6.0)
        assert res_open.success is True
        
        res_end = engine.generate_ending("チャンネル名", call_to_action="登録してね", duration_sec=6.0)
        assert res_end.success is True
        
        # 5. 簡易関数のテスト (401-404, 409-410, 415-416)
        import generation_engine
        orig_veo = generation_engine.generation_engine.veo
        orig_imagen = generation_engine.generation_engine.imagen
        
        generation_engine.generation_engine.veo = mock_veo
        generation_engine.generation_engine.imagen = mock_imagen
        
        try:
            from generation_engine import generate_thumbnail, generate_opening, generate_ending
            res_func_thumb = generate_thumbnail("タイトル")
            assert res_func_thumb["success"] is True
            
            res_func_open = generate_opening("チャンネル名")
            assert res_func_open["success"] is True
            
            res_func_end = generate_ending("チャンネル名")
            assert res_func_end["success"] is True
        finally:
            generation_engine.generation_engine.veo = orig_veo
            generation_engine.generation_engine.imagen = orig_imagen



