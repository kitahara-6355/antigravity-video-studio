import pytest
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch
from pydantic import ValidationError
from services.soul_feedback import (
    SoulFeedbackParams,
    SoulFeedbackProcessor,
    SubtitleThumbnailVerifier,
    resolve_subtitle_thumbnail_task,
    create_subtitle_sample,
    create_integrated_sample,
)

def test_soul_feedback_params_defaults():
    params = SoulFeedbackParams()
    assert params.tempo_multiplier == 1.0
    assert params.telop_color == "#FFFFFF"
    assert params.subtitle_font_size == 24
    assert params.volume_multiplier == 1.0

def test_soul_feedback_params_validation():
    params = SoulFeedbackParams(telop_color="#ff0000")
    assert params.telop_color == "#FF0000"
    
    with pytest.raises(ValidationError):
        SoulFeedbackParams(tempo_multiplier=0.4)
        
    with pytest.raises(ValidationError):
        SoulFeedbackParams(tempo_multiplier=2.1)

    with pytest.raises(ValidationError):
        SoulFeedbackParams(subtitle_font_size=9)

    with pytest.raises(ValidationError):
        SoulFeedbackParams(subtitle_font_size=101)

    with pytest.raises(ValidationError):
        SoulFeedbackParams(volume_multiplier=-0.1)

    with pytest.raises(ValidationError):
        SoulFeedbackParams(volume_multiplier=2.1)

    with pytest.raises(ValidationError):
        SoulFeedbackParams(telop_color="invalid_color")

def test_apply_guardrails():
    proc = SoulFeedbackProcessor()
    
    in_range = {
        "tempo_multiplier": 1.5,
        "telop_color": "#00ff00",
        "subtitle_font_size": 30,
        "volume_multiplier": 1.2
    }
    params = proc.apply_guardrails(in_range)
    assert params.tempo_multiplier == 1.5
    assert params.telop_color == "#00FF00"
    assert params.subtitle_font_size == 30
    assert params.volume_multiplier == 1.2
    
    out_of_range = {
        "tempo_multiplier": 5.0,
        "telop_color": "invalid",
        "subtitle_font_size": 200,
        "volume_multiplier": -1.0
    }
    params = proc.apply_guardrails(out_of_range)
    assert params.tempo_multiplier == 2.0
    assert params.telop_color == "#FFFFFF"
    assert params.subtitle_font_size == 100
    assert params.volume_multiplier == 0.0
    
    type_errors = {
        "tempo_multiplier": "not a float",
        "subtitle_font_size": "not an int",
        "volume_multiplier": "not a float"
    }
    params = proc.apply_guardrails(type_errors)
    assert params.tempo_multiplier == 1.0
    assert params.subtitle_font_size == 24
    assert params.volume_multiplier == 1.0

def test_extract_json():
    proc = SoulFeedbackProcessor()
    
    txt1 = "Here is the json: ```json\n{\"tempo_multiplier\": 1.2}\n``` thank you"
    assert proc._extract_json(txt1) == "{\"tempo_multiplier\": 1.2}"
    
    txt2 = "```\n{\"tempo_multiplier\": 1.2}\n```"
    assert proc._extract_json(txt2) == "{\"tempo_multiplier\": 1.2}"
    
    txt3 = "some text {\"tempo_multiplier\": 1.2} other text"
    assert proc._extract_json(txt3) == "{\"tempo_multiplier\": 1.2}"
    
    txt4 = "plain text without braces"
    assert proc._extract_json(txt4) == "plain text without braces"

@pytest.mark.asyncio
async def test_parse_qualitative_feedback_success():
    proc = SoulFeedbackProcessor()
    
    response_json = '{"tempo_multiplier": 1.2, "telop_color": "#ff0000"}'
    
    with patch.object(proc, "_call_llm", return_value=response_json):
        params = await proc.parse_qualitative_feedback("テンポ早く、赤色テロップ")
        assert params.tempo_multiplier == 1.2
        assert params.telop_color == "#FF0000"

@pytest.mark.asyncio
async def test_parse_qualitative_feedback_empty_response():
    proc = SoulFeedbackProcessor()
    
    with patch.object(proc, "_call_llm", return_value=""):
        params = await proc.parse_qualitative_feedback("テンポ早く、赤色テロップ")
        assert params.tempo_multiplier == 1.0

@pytest.mark.asyncio
async def test_parse_qualitative_feedback_invalid_json():
    proc = SoulFeedbackProcessor()
    
    with patch.object(proc, "_call_llm", return_value="invalid json string"):
        params = await proc.parse_qualitative_feedback("テンポ早く、赤色テロップ")
        assert params.tempo_multiplier == 1.0

@pytest.mark.asyncio
async def test_parse_qualitative_feedback_timeout():
    proc = SoulFeedbackProcessor()
    
    async def mock_timeout_call(prompt):
        await asyncio.sleep(0.1)
        raise asyncio.TimeoutError()
        
    with patch.object(proc, "_call_llm", side_effect=mock_timeout_call):
        params = await proc.parse_qualitative_feedback("テンポ早く")
        assert params.tempo_multiplier == 1.0

@pytest.mark.asyncio
async def test_parse_qualitative_feedback_other_exception():
    proc = SoulFeedbackProcessor()
    
    with patch.object(proc, "_call_llm", side_effect=RuntimeError("unknown error")):
        params = await proc.parse_qualitative_feedback("テンポ早く")
        assert params.tempo_multiplier == 1.0
        assert params.telop_color == "#FFFFFF"
        assert params.subtitle_font_size == 24
        assert params.volume_multiplier == 1.0

@pytest.mark.asyncio
async def test_call_llm_no_client():
    proc = SoulFeedbackProcessor()
    with patch("services.soul_feedback.get_gemini_client", return_value=None):
        res = await proc._call_llm("prompt")
        assert res is None

@pytest.mark.asyncio
async def test_call_llm_success():
    proc = SoulFeedbackProcessor()
    
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "  llm result  "
    mock_client.models.generate_content.return_value = mock_response
    
    with patch("services.soul_feedback.get_gemini_client", return_value=mock_client):
        res = await proc._call_llm("prompt")
        assert res == "llm result"
        mock_client.models.generate_content.assert_called_once_with(
            model=proc.model_name,
            contents="prompt"
        )

@pytest.mark.asyncio
async def test_call_llm_parse_error():
    proc = SoulFeedbackProcessor()
    
    mock_client = MagicMock()
    mock_response = MagicMock()
    type(mock_response).text = property(lambda self: TypeError("parse error"))
    mock_client.models.generate_content.return_value = mock_response
    
    with patch("services.soul_feedback.get_gemini_client", return_value=mock_client):
        res = await proc._call_llm("prompt")
        assert res is None

def test_apply_guardrails_validation_error():
    from services.soul_feedback import SoulFeedbackParams as RealParams
    proc = SoulFeedbackProcessor()
    
    calls = []
    def side_effect_func(*args, **kwargs):
        if not calls:
            calls.append(1)
            raise ValidationError.from_exception_data(title="SoulFeedbackParams", line_errors=[])
        return RealParams()
        
    with patch("services.soul_feedback.SoulFeedbackParams", side_effect=side_effect_func):
        params = proc.apply_guardrails({"tempo_multiplier": 1.0})
        assert params.tempo_multiplier == 1.0


# --- 新規追加テスト (カバレッジ向上用) ---

@pytest.mark.asyncio
async def test_parse_qualitative_feedback_non_dict_json():
    import json
    proc = SoulFeedbackProcessor()
    # JSONとしてパースできるが、辞書ではないリストを返させる
    response_json = '[1, 2, 3]'
    with patch.object(proc, "_call_llm", return_value=response_json):
        params = await proc.parse_qualitative_feedback("ダミー指示")
        assert params.tempo_multiplier == 1.0
        assert params.telop_color == "#FFFFFF"


def test_import_error_fallback_definition():
    import sys
    import importlib
    
    original_soul_feedback = sys.modules.get("services.soul_feedback")
    original_alert_system = sys.modules.get("usage_tracker.alert_system")
    
    try:
        if "services.soul_feedback" in sys.modules:
            del sys.modules["services.soul_feedback"]
        
        # usage_tracker.alert_systemのインポートを失敗させる
        sys.modules["usage_tracker.alert_system"] = None
        
        # 再ロード
        import services.soul_feedback as sf_reloaded
        
        # フォールバック関数が正しく動作することを確認
        assert sf_reloaded.emit_warning is not None
        assert sf_reloaded.emit_critical is not None
        
        # フォールバック関数の実行
        with patch("services.soul_feedback.logger.warning") as mock_warn, \
             patch("services.soul_feedback.logger.error") as mock_error:
            sf_reloaded.emit_warning("test_domain", "warn_msg")
            sf_reloaded.emit_critical("test_domain", "crit_msg")
            mock_warn.assert_called_once_with("[test_domain] warn_msg")
            mock_error.assert_called_once_with("[test_domain] CRITICAL: crit_msg")
        
    finally:
        # 個別に復元
        if original_soul_feedback is not None:
            sys.modules["services.soul_feedback"] = original_soul_feedback
        elif "services.soul_feedback" in sys.modules:
            del sys.modules["services.soul_feedback"]
            
        if original_alert_system is not None:
            sys.modules["usage_tracker.alert_system"] = original_alert_system
        elif "usage_tracker.alert_system" in sys.modules:
            del sys.modules["usage_tracker.alert_system"]


def test_create_subtitle_sample_flow(tmp_path):
    from pathlib import Path
    from services.soul_feedback import create_subtitle_sample
    output_file = tmp_path / "subtitle_test.png"
    
    # 正常系 (パス指定)
    res_path = create_subtitle_sample(output_file)
    assert Path(res_path).exists()
    assert res_path == str(output_file)
    
    # 既存ファイルが存在する状況での呼び出し (行235をカバー)
    res_path2 = create_subtitle_sample(output_file)
    assert Path(res_path2).exists()
    
    # 正常系 (デフォルトパス)
    default_target = Path(__file__).parent.parent / "subtitle_sample.png"
    existed = default_target.exists()
    try:
        res_path_default = create_subtitle_sample()
        assert Path(res_path_default).exists()
        assert Path(res_path_default).resolve() == default_target.resolve()
    finally:
        if not existed and default_target.exists():
            default_target.unlink()


def test_create_subtitle_sample_font_fallback(tmp_path):
    import PIL
    from services.soul_feedback import create_subtitle_sample
    output_file = tmp_path / "subtitle_test_fallback.png"
    
    orig_truetype = PIL.ImageFont.truetype
    def mock_truetype(font=None, size=None, *args, **kwargs):
        actual_size = size
        if not actual_size and args:
            actual_size = args[0]
        if font and "Yu Gothic" in str(font):
            if actual_size == 18:
                raise IOError("font not found")
            return PIL.ImageFont.load_default()
        return orig_truetype(font, size, *args, **kwargs)
        
    with patch("PIL.ImageFont.truetype", side_effect=mock_truetype):
        res_path = create_subtitle_sample(output_file)
        assert Path(res_path).exists()


def test_create_subtitle_sample_exception_handling(tmp_path):
    from services.soul_feedback import create_subtitle_sample
    output_file = tmp_path / "subtitle_test_fail.png"
    
    orig_unlink = Path.unlink
    def mock_unlink(self, *args, **kwargs):
        # 一時ファイルの削除で OSError を投げて、例外ハンドラ（行240-243）をカバー
        if "subtitle_test_fail" in self.name and self.suffix == ".tmp":
            raise OSError("mocked permission error")
        return orig_unlink(self, *args, **kwargs)
        
    def mock_save(fp, format=None, **params):
        # 一時ファイルを実際に touch して存在させる
        Path(fp).touch()
        raise RuntimeError("save failed")
        
    Path.unlink = mock_unlink
    try:
        with patch("PIL.Image.Image.save", side_effect=mock_save):
            with pytest.raises(RuntimeError):
                create_subtitle_sample(output_file)
    finally:
        Path.unlink = orig_unlink
        
    tmp_files = list(tmp_path.glob("*.tmp"))
    # 削除例外を pass しているため、一時ファイルが残ることを確認
    assert len(tmp_files) == 1
    # 後片付け
    for f in tmp_files:
        orig_unlink(f)


def test_create_integrated_sample_flow(tmp_path):
    from pathlib import Path
    from services.soul_feedback import create_integrated_sample
    output_file = tmp_path / "integrated_test.png"
    
    # 正常系 (パス指定)
    res_path = create_integrated_sample(output_file)
    assert Path(res_path).exists()
    assert res_path == str(output_file)
    
    # 既存ファイルが存在する状況での呼び出し (行312をカバー)
    res_path2 = create_integrated_sample(output_file)
    assert Path(res_path2).exists()
    
    # デフォルトパス
    default_target = Path(__file__).parent.parent / "B_plan_with_subtitle.png"
    existed = default_target.exists()
    try:
        res_path_default = create_integrated_sample()
        assert Path(res_path_default).exists()
    finally:
        if not existed and default_target.exists():
            default_target.unlink()


def test_create_integrated_sample_font_fallback(tmp_path):
    import PIL
    from services.soul_feedback import create_integrated_sample
    output_file = tmp_path / "integrated_test_fallback.png"
    
    orig_truetype = PIL.ImageFont.truetype
    def mock_truetype(font=None, size=None, *args, **kwargs):
        actual_size = size
        if not actual_size and args:
            actual_size = args[0]
        if font and "Yu Gothic" in str(font):
            if actual_size == 18:
                raise IOError("font not found")
            return PIL.ImageFont.load_default()
        return orig_truetype(font, size, *args, **kwargs)
        
    with patch("PIL.ImageFont.truetype", side_effect=mock_truetype):
        res_path = create_integrated_sample(output_file)
        assert Path(res_path).exists()


def test_create_integrated_sample_exception_handling(tmp_path):
    from services.soul_feedback import create_integrated_sample
    output_file = tmp_path / "integrated_test_fail.png"
    
    orig_unlink = Path.unlink
    def mock_unlink(self, *args, **kwargs):
        if "integrated_test_fail" in self.name and self.suffix == ".tmp":
            raise OSError("mocked permission error")
        return orig_unlink(self, *args, **kwargs)
        
    def mock_save(fp, format=None, **params):
        Path(fp).touch()
        raise RuntimeError("save failed")
        
    Path.unlink = mock_unlink
    try:
        with patch("PIL.Image.Image.save", side_effect=mock_save):
            with pytest.raises(RuntimeError):
                create_integrated_sample(output_file)
    finally:
        Path.unlink = orig_unlink
        
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert len(tmp_files) == 1
    for f in tmp_files:
        orig_unlink(f)


def test_subtitle_thumbnail_verifier_validate_not_found():
    with pytest.raises(FileNotFoundError):
        SubtitleThumbnailVerifier.validate("non_existent_file.png")


def test_subtitle_thumbnail_verifier_validate_oversize(tmp_path):
    large_file = tmp_path / "large_file.png"
    large_file.write_bytes(b"\x00" * (4 * 1024 * 1024)) # 4MB
    with pytest.raises(ValueError, match="exceeds 4MB limit"):
        SubtitleThumbnailVerifier.validate(large_file)


def test_subtitle_thumbnail_verifier_validate_corrupted_verify(tmp_path):
    corrupted_file = tmp_path / "corrupted_verify.png"
    corrupted_file.write_bytes(b"not an image file")
    with pytest.raises(ValueError, match="Image verify failed"):
        SubtitleThumbnailVerifier.validate(corrupted_file)


def test_subtitle_thumbnail_verifier_validate_corrupted_load(tmp_path):
    from PIL import Image
    dummy_img = tmp_path / "dummy_load_fail.png"
    img = Image.new('RGB', (1280, 720), (255, 255, 255))
    img.save(dummy_img, "PNG")
    
    with patch("PIL.Image.Image.load", side_effect=IOError("corrupted pixels")):
        with pytest.raises(ValueError, match="Image load failed"):
            SubtitleThumbnailVerifier.validate(dummy_img)


def test_subtitle_thumbnail_verifier_validate_invalid_resolution(tmp_path):
    from PIL import Image
    small_file = tmp_path / "small.png"
    img = Image.new('RGB', (640, 360), (255, 255, 255))
    img.save(small_file, "PNG")
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        SubtitleThumbnailVerifier.validate(small_file)


def test_subtitle_thumbnail_verifier_validate_invalid_aspect_ratio(tmp_path):
    from PIL import Image
    square_file = tmp_path / "square.png"
    img = Image.new('RGB', (1280, 1280), (255, 255, 255))
    img.save(square_file, "PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        SubtitleThumbnailVerifier.validate(square_file)


def test_subtitle_thumbnail_verifier_validate_success(tmp_path):
    from PIL import Image
    valid_file = tmp_path / "valid.png"
    img = Image.new('RGB', (1920, 1080), (255, 255, 255))
    img.save(valid_file, "PNG")
    
    res = SubtitleThumbnailVerifier.validate(valid_file)
    assert res["path"] == str(valid_file)
    assert res["width"] == 1920
    assert res["height"] == 1080
    assert res["size_bytes"] > 0


@pytest.mark.asyncio
async def test_resolve_subtitle_thumbnail_task_success(tmp_path):
    from pathlib import Path
    import json
    agent = MagicMock()
    agent.output_dir = tmp_path
    
    res_str = await resolve_subtitle_thumbnail_task(agent, "task_123")
    res = json.loads(res_str)
    
    assert Path(res["path"]).exists()
    assert res["width"] == 1920
    assert res["height"] == 1080


@pytest.mark.asyncio
async def test_resolve_subtitle_thumbnail_task_no_output_dir():
    from pathlib import Path
    import json
    agent = MagicMock()
    del agent.output_dir  # 属性が存在しないようにする
    
    dummy_res = {"path": "dummy_path.png", "width": 1280, "height": 720, "size_bytes": 100}
    with patch("services.soul_feedback.create_subtitle_sample") as mock_create, \
         patch("services.soul_feedback.SubtitleThumbnailVerifier.validate", return_value=dummy_res) as mock_val:
        res_str = await resolve_subtitle_thumbnail_task(agent, "task_no_dir")
        res = json.loads(res_str)
        assert res["path"] == "dummy_path.png"
        
        called_args, _ = mock_create.call_args
        assert Path(called_args[0]).name == "task_no_dir.png"
        assert "backend/temp_thumbnails" in str(Path(called_args[0]).parent).replace('\\', '/')


@pytest.mark.asyncio
async def test_resolve_subtitle_thumbnail_task_failure():
    agent = MagicMock()
    with patch("services.soul_feedback.create_subtitle_sample", side_effect=RuntimeError("creation failed")), \
         patch("services.soul_feedback.emit_critical") as mock_emit:
        with pytest.raises(RuntimeError, match="creation failed"):
            await resolve_subtitle_thumbnail_task(agent, "task_fail")
        mock_emit.assert_called_once()


def test_create_subtitle_sample_non_existent_directory(tmp_path):
    non_existent_dir = tmp_path / "new_subdir" / "nested_dir"
    output_file = non_existent_dir / "subtitle_test.png"
    
    res_path = create_subtitle_sample(output_file)
    assert Path(res_path).exists()
    assert Path(res_path).parent == non_existent_dir


def test_create_integrated_sample_non_existent_directory(tmp_path):
    non_existent_dir = tmp_path / "new_subdir_integrated" / "nested_dir"
    output_file = non_existent_dir / "integrated_test.png"
    
    res_path = create_integrated_sample(output_file)
    assert Path(res_path).exists()
    assert Path(res_path).parent == non_existent_dir


@pytest.mark.asyncio
async def test_parse_qualitative_feedback_unexpected_exception_logging():
    proc = SoulFeedbackProcessor()
    
    with patch.object(proc, "_call_llm", side_effect=RuntimeError("unexpected api error")), \
         patch("services.soul_feedback.logger.error") as mock_log_error:
        params = await proc.parse_qualitative_feedback("指示")
        assert params.tempo_multiplier == 1.0
        
        mock_log_error.assert_called_once()
        called_args, called_kwargs = mock_log_error.call_args
        assert "[SoulFeedback] Unexpected error" in called_args[0]
        assert called_kwargs.get("exc_info") is True


@pytest.mark.asyncio
async def test_resolve_subtitle_thumbnail_task_failure_logging():
    agent = MagicMock()
    with patch("services.soul_feedback.create_subtitle_sample", side_effect=RuntimeError("creation failed")), \
         patch("services.soul_feedback.emit_critical"), \
         patch("services.soul_feedback.logger.error") as mock_log_error:
        with pytest.raises(RuntimeError, match="creation failed"):
            await resolve_subtitle_thumbnail_task(agent, "task_fail_log")
        
        mock_log_error.assert_called_once()
        called_args, called_kwargs = mock_log_error.call_args
        assert "[SoulFeedback] Subtitle thumbnail task failed" in called_args[0]
        assert called_kwargs.get("exc_info") is True

@pytest.mark.asyncio
async def test_parse_qualitative_feedback_google_api_error():
    from google.api_core.exceptions import GoogleAPIError
    proc = SoulFeedbackProcessor()
    
    class MockGoogleAPIError(GoogleAPIError):
        pass
        
    with patch.object(proc, "_call_llm", side_effect=MockGoogleAPIError("API error")),          patch("services.soul_feedback.logger.error") as mock_log_error:
        params = await proc.parse_qualitative_feedback("指示")
        assert params.tempo_multiplier == 1.0
        
        mock_log_error.assert_called_once()
        called_args, called_kwargs = mock_log_error.call_args
        assert "[SoulFeedback] Unexpected error" in called_args[0]
        assert called_kwargs.get("exc_info") is True


@pytest.mark.asyncio
async def test_resolve_subtitle_thumbnail_task_specific_errors():
    agent = MagicMock()
    for exc in [TypeError("type error"), KeyError("key error"), AttributeError("attr error"), OSError("os error")]:
        with patch("services.soul_feedback.create_subtitle_sample", side_effect=exc),              patch("services.soul_feedback.emit_critical") as mock_emit:
            with pytest.raises(type(exc)):
                await resolve_subtitle_thumbnail_task(agent, "task_fail_specific")
            mock_emit.assert_called_once()
