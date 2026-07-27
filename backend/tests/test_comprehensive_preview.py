"""
test_comprehensive_preview.py — comprehensive_preview.py のユニットテスト
全分岐をモックでカバー。
"""
import sys
from pathlib import Path

# backend の親ディレクトリ（プロジェクトルート）を sys.path に追加して
# "backend.xxx" のインポートを解決できるようにする
_backend_dir = Path(__file__).resolve().parent.parent
_project_root = _backend_dir.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest
import subprocess
from unittest.mock import patch, MagicMock, mock_open
from PIL import Image

# テスト内の Image.new をラップしてソリッドカラー（単一色）判定を回避する
_orig_image_new = Image.new

def _test_image_new(mode, size, color=None):
    img = _orig_image_new(mode, size, color)
    try:
        px = img.load()
        if mode in ("RGB", "RGBA"):
            if color and isinstance(color, tuple) and len(color) >= 3:
                r, g, b = color[:3]
                a = color[3] if len(color) > 3 else 255
                px[0, 0] = (255 - r, 255 - g, 255 - b) + ((a,) if mode == "RGBA" else ())
            else:
                px[0, 0] = (255, 255, 255) + ((255,) if mode == "RGBA" else ())
        elif mode == "L":
            val = color if isinstance(color, int) else 128
            px[0, 0] = 255 - val
        elif mode == "P":
            px[0, 0] = 1
    except Exception:
        pass
    return img

@pytest.fixture(autouse=True)
def _patch_image_new_for_solid_color_bypass():
    """Image.new をラップして単一色判定を回避する（このファイルのテストのみ有効）"""
    Image.new = _test_image_new
    yield
    Image.new = _orig_image_new

# comprehensive_preview.py は関数内で from xxx import を使う
# sys.modules にモックモジュールを注入して解決

_mock_overlay = MagicMock()
_mock_grading = MagicMock()
_mock_screenshot = MagicMock()

_mock_modules = {
    "preview_report_generator": MagicMock(),
    "combined_overlay": MagicMock(CombinedOverlay=MagicMock(return_value=_mock_overlay)),
    "color_grading": MagicMock(ColorGrading=MagicMock(return_value=_mock_grading)),
    "screenshot_generator": MagicMock(generate_multiple_screenshots=MagicMock(return_value=["s1.png", "s2.png"])),
}


@pytest.fixture(autouse=True)
def _mock_imports_and_reset():
    """モジュールモック + 各テスト前にMock呼び出しリセット"""
    _mock_overlay.reset_mock()
    _mock_grading.reset_mock()
    _mock_modules["screenshot_generator"].generate_multiple_screenshots.reset_mock()
    _mock_modules["screenshot_generator"].generate_multiple_screenshots.return_value = ["s1.png", "s2.png"]
    with patch.dict(sys.modules, _mock_modules):
        if "backend.comprehensive_preview" in sys.modules:
            del sys.modules["backend.comprehensive_preview"]
        yield


def _import_module():
    import importlib
    if "backend.comprehensive_preview" in sys.modules:
        return importlib.reload(sys.modules["backend.comprehensive_preview"])
    return importlib.import_module("backend.comprehensive_preview")


class TestCreateComprehensivePreview:

    def test_success_with_subtitle(self, tmp_path):
        """正常系: 字幕ファイルが存在する場合"""
        mod = _import_module()

        subtitle_content = "1\n00:00:01,000 --> 00:00:05,000\nテスト字幕\n"

        def mock_exists(self):
            # input_video (input.mp4) と whisper_semantic.srt が存在するものとみなす
            name = str(self)
            if "input.mp4" in name or "whisper_semantic.srt" in name:
                return True
            return False

        with patch.object(Path, "mkdir"), \
             patch("subprocess.run"), \
             patch.object(Path, "exists", mock_exists), \
             patch("builtins.open", mock_open(read_data=subtitle_content)):

            result = mod.create_comprehensive_preview("input.mp4", str(tmp_path))

        assert "logo_telop" in result
        assert "color_graded" in result
        assert "screenshots" in result
        assert result["subtitle_file"] is not None
        assert _mock_overlay.apply_brand_overlay.call_count == 2
        _mock_grading.apply_lut.assert_called_once()

    def test_success_without_subtitle(self, tmp_path):
        """正常系: 字幕ファイルが存在しない場合"""
        mod = _import_module()

        def mock_exists(self):
            name = str(self)
            if "input.mp4" in name:
                return True
            return False

        with patch.object(Path, "mkdir"), \
             patch("subprocess.run"), \
             patch.object(Path, "exists", mock_exists):

            result = mod.create_comprehensive_preview("input.mp4", str(tmp_path))

        assert result["subtitle_file"] is None

    def test_invalid_input_video_type(self):
        """引数エラー: input_video の型が不正"""
        mod = _import_module()
        with pytest.raises(ValueError, match="input_video must be a non-empty string or Path object"):
            mod.create_comprehensive_preview(None)
        with pytest.raises(ValueError, match="input_video must be a non-empty string or Path object"):
            mod.create_comprehensive_preview("")
        with pytest.raises(ValueError, match="input_video must be a non-empty string or Path object"):
            mod.create_comprehensive_preview(123)

    def test_invalid_output_dir_type(self):
        """引数エラー: output_dir の型が不正"""
        mod = _import_module()
        with pytest.raises(ValueError, match="output_dir must be a non-empty string or Path object"):
            mod.create_comprehensive_preview("input.mp4", None)
        with pytest.raises(ValueError, match="output_dir must be a non-empty string or Path object"):
            mod.create_comprehensive_preview("input.mp4", "")
        with pytest.raises(ValueError, match="output_dir must be a non-empty string or Path object"):
            mod.create_comprehensive_preview("input.mp4", 123)

    def test_file_not_found(self):
        """エラー: 入力ファイルが存在しない"""
        mod = _import_module()
        with patch.object(Path, "exists", return_value=False):
            with pytest.raises(FileNotFoundError, match="Input video file not found"):
                mod.create_comprehensive_preview("nonexistent.mp4")

    def test_mkdir_error(self):
        """エラー: ディレクトリ作成失敗"""
        mod = _import_module()
        with patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "mkdir", side_effect=OSError("Permission denied")):
            with pytest.raises(OSError, match="Permission denied"):
                mod.create_comprehensive_preview("input.mp4")

    def test_ffmpeg_failure(self):
        """異常系: ffmpeg失敗 (CalledProcessError)"""
        mod = _import_module()

        with patch.object(Path, "mkdir"), \
             patch.object(Path, "exists", return_value=True), \
             patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "ffmpeg", stderr=b"ffmpeg error output")):

            with pytest.raises(mod.PreviewGenerationError):
                mod.create_comprehensive_preview("input.mp4")

    def test_ffmpeg_timeout(self):
        """異常系: ffmpegタイムアウト"""
        mod = _import_module()

        with patch.object(Path, "mkdir"), \
             patch.object(Path, "exists", return_value=True), \
             patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ffmpeg", 60)):

            with pytest.raises(mod.PreviewGenerationError):
                mod.create_comprehensive_preview("input.mp4")

    def test_subtitle_read_io_error(self, tmp_path):
        """正常系（フォールバック）: 字幕読み込み時に OSError が発生した場合"""
        mod = _import_module()

        def mock_exists(self):
            name = str(self)
            if "input.mp4" in name or "whisper_semantic.srt" in name:
                return True
            return False

        with patch.object(Path, "mkdir"), \
             patch("subprocess.run"), \
             patch.object(Path, "exists", mock_exists), \
             patch("builtins.open", side_effect=OSError("Read error")):

            result = mod.create_comprehensive_preview("input.mp4", str(tmp_path))

        # 字幕ファイル読み込みに失敗しても処理自体は続行し、subtitle_file は None になる
        assert result["subtitle_file"] is None

    def test_subtitle_read_decode_error(self, tmp_path):
        """正常系（フォールバック）: 字幕読み込み時に UnicodeDecodeError が発生した場合"""
        mod = _import_module()

        def mock_exists(self):
            name = str(self)
            if "input.mp4" in name or "whisper_semantic.srt" in name:
                return True
            return False

        with patch.object(Path, "mkdir"), \
             patch("subprocess.run"), \
             patch.object(Path, "exists", mock_exists), \
             patch("builtins.open", side_effect=UnicodeDecodeError("utf-8", b"", 0, 1, "invalid byte")):

            result = mod.create_comprehensive_preview("input.mp4", str(tmp_path))

        assert result["subtitle_file"] is None

    def test_screenshots_generated(self, tmp_path):
        """スクリーンショットが3セット生成される"""
        mod = _import_module()

        mock_gen = _mock_modules["screenshot_generator"].generate_multiple_screenshots
        mock_gen.return_value = ["a.png", "b.png", "c.png"]

        def mock_exists(self):
            name = str(self)
            if "input.mp4" in name:
                return True
            return False

        with patch.object(Path, "mkdir"), \
             patch("subprocess.run"), \
             patch.object(Path, "exists", mock_exists):

            result = mod.create_comprehensive_preview("input.mp4", str(tmp_path))

        assert mock_gen.call_count == 3
        assert result["screenshots"]["logo"] == ["a.png", "b.png", "c.png"]
        assert result["screenshots"]["color"] == ["a.png", "b.png", "c.png"]
        assert result["screenshots"]["comprehensive"] == ["a.png", "b.png", "c.png"]

    def test_ffmpeg_failure_no_stderr(self):
        """異常系: ffmpeg失敗 (CalledProcessError) で stderr が None の場合"""
        mod = _import_module()

        with patch.object(Path, "mkdir"), \
             patch.object(Path, "exists", return_value=True), \
             patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "ffmpeg", stderr=None)):

            with pytest.raises(mod.PreviewGenerationError):
                mod.create_comprehensive_preview("input.mp4")

    def test_success_with_long_subtitle(self, tmp_path):
        """正常系: 字幕ファイルが20行を超える場合"""
        mod = _import_module()

        subtitle_content = "\n".join(f"line {i}" for i in range(100))

        def mock_exists(self):
            name = str(self)
            if "input.mp4" in name or "whisper_semantic.srt" in name:
                return True
            return False

        with patch.object(Path, "mkdir"), \
             patch("subprocess.run"), \
             patch.object(Path, "exists", mock_exists), \
             patch("builtins.open", mock_open(read_data=subtitle_content)):

            result = mod.create_comprehensive_preview("input.mp4", str(tmp_path))

        assert "logo_telop" in result
        assert "color_graded" in result
        assert "screenshots" in result
        assert result["subtitle_file"] is not None

    def test_success_with_comprehensive_preview(self, tmp_path):
        """正常系: 全要素統合プレビュー(04_comprehensive.mp4)が生成され、戻り値に含まれること"""
        mod = _import_module()

        def mock_exists(self):
            name = str(self)
            if "input.mp4" in name:
                return True
            return False

        with patch.object(Path, "mkdir"), \
             patch("subprocess.run"), \
             patch.object(Path, "exists", mock_exists):

            result = mod.create_comprehensive_preview("input.mp4", str(tmp_path))

        assert "comprehensive" in result
        assert "comprehensive" in result["screenshots"]
        assert result["comprehensive"].endswith("04_comprehensive.mp4")
        assert _mock_overlay.apply_brand_overlay.call_count == 2
        assert _mock_grading.apply_lut.call_count == 1

    def test_custom_timestamps(self, tmp_path):
        """正常系: カスタムタイムスタンプを指定した場合"""
        mod = _import_module()

        mock_gen = _mock_modules["screenshot_generator"].generate_multiple_screenshots
        mock_gen.return_value = ["x.png"]

        def mock_exists(self):
            name = str(self)
            if "input.mp4" in name:
                return True
            return False

        custom_ts = [1.2, 5.5]

        with patch.object(Path, "mkdir"), \
             patch("subprocess.run"), \
             patch.object(Path, "exists", mock_exists):

            result = mod.create_comprehensive_preview("input.mp4", str(tmp_path), timestamps=custom_ts)

        assert mock_gen.call_count == 3
        for call in mock_gen.call_args_list:
            assert call[0][1] == custom_ts

    def test_invalid_timestamps(self):
        """引数エラー: timestamps の型が不正"""
        mod = _import_module()
        with pytest.raises(ValueError, match="timestamps must be a list of numbers"):
            mod.create_comprehensive_preview("input.mp4", timestamps="not a list")
        with pytest.raises(ValueError, match="timestamps must be a list of numbers"):
            mod.create_comprehensive_preview("input.mp4", timestamps=[1, "two", 3])


class TestThumbnailQualityValidation:

    def test_validate_preview_image_success(self, tmp_path):
        """正常系: 1280x720 (16:9) の画像が正常に検証されること"""
        from PIL import Image
        img_path = tmp_path / "valid.png"
        img = Image.new("RGB", (1280, 720), (255, 0, 0))
        img.save(img_path)
        
        from backend.comprehensive_preview import validate_preview_image
        result = validate_preview_image(str(img_path))
        assert result["width"] == 1280
        assert result["height"] == 720
        assert result["size_bytes"] > 0

    def test_validate_preview_image_not_found(self):
        """異常系: 画像ファイルが存在しない場合"""
        from backend.comprehensive_preview import validate_preview_image
        with pytest.raises(FileNotFoundError):
            validate_preview_image("nonexistent_image.png")

    def test_validate_preview_image_invalid_resolution(self, tmp_path):
        """異常系: 解像度不足"""
        from PIL import Image
        img_path = tmp_path / "low_res.png"
        img = Image.new("RGB", (1000, 500), (255, 0, 0))
        img.save(img_path)
        
        from backend.comprehensive_preview import validate_preview_image
        with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
            validate_preview_image(str(img_path))

    def test_validate_preview_image_invalid_aspect(self, tmp_path):
        """異常系: アスペクト比が 16:9 以外 (例: 1280x800)"""
        from PIL import Image
        img_path = tmp_path / "aspect_16_10.png"
        img = Image.new("RGB", (1280, 800), (255, 0, 0))
        img.save(img_path)
        
        from backend.comprehensive_preview import validate_preview_image
        with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
            validate_preview_image(str(img_path))

    def test_validate_preview_image_file_size_exceeded(self, tmp_path, monkeypatch):
        """異常系: ファイルサイズが4MB以上"""
        from PIL import Image
        from pathlib import Path
        img_path = tmp_path / "size_exceeded.png"
        img = Image.new("RGB", (1280, 720), (255, 0, 0))
        img.save(img_path)
        
        class MockStat:
            def __init__(self, size):
                self.st_size = size
                
        # パスの stat().st_size をモックしてファイルサイズ制限をシミュレート。
        orig_stat = Path.stat
        def mock_stat(self, *args, **kwargs):
            if "size_exceeded.png" in str(self):
                return MockStat(5 * 1024 * 1024)
            return orig_stat(self, *args, **kwargs)
            
        monkeypatch.setattr(Path, "stat", mock_stat)
        
        from backend.comprehensive_preview import validate_preview_image
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            validate_preview_image(str(img_path))

    def test_ensure_preview_image_quality_no_change(self, tmp_path):
        """自動補正: すでに 1280x720 (16:9) の場合は補正しない"""
        from PIL import Image
        img_path = tmp_path / "no_change.png"
        img = Image.new("RGB", (1280, 720), (0, 0, 255))
        img.save(img_path)
        
        from backend.comprehensive_preview import ensure_preview_image_quality, validate_preview_image
        res_path = ensure_preview_image_quality(str(img_path))
        
        result = validate_preview_image(res_path)
        assert result["width"] == 1280
        assert result["height"] == 720

    def test_ensure_preview_image_quality_adjust(self, tmp_path):
        """自動補正: 解像度が低い 800x600 (4:3) 画像を 1280x720 (16:9) に補正"""
        from PIL import Image
        img_path = tmp_path / "to_adjust.png"
        img = Image.new("RGB", (800, 600), (255, 0, 0))
        img.save(img_path)
        
        from backend.comprehensive_preview import ensure_preview_image_quality, validate_preview_image
        res_path = ensure_preview_image_quality(str(img_path))
        
        result = validate_preview_image(res_path)
        assert result["width"] == 1280
        assert result["height"] == 720

    @pytest.mark.asyncio
    async def test_stage_bound_agent_integration_with_preview_task(self, tmp_path):
        """結合テスト: StageBoundAgent と連携し、自動検証、結果保存、および完了ステータス遷移の確認"""
        from backend.agents.stage_bound_agent import StageBoundAgent
        from PIL import Image
        import sqlite3
        import json
        import asyncio
        
        db_file = tmp_path / "agent_preview.db"
        agent = StageBoundAgent(stage_name="comprehensive_preview", db_path=str(db_file))
        
        # 依存パラメータを設定
        video_path = tmp_path / "dummy_video.mp4"
        video_path.write_bytes(b"dummy mp4 content")
        
        agent.input_video = str(video_path)
        agent.output_dir = str(tmp_path / "output_preview")
        agent.timestamps = [1.0]
        
        task_id = "t_comp_prev_001"
        await agent.register_task(task_id=task_id, initial_status="READY")
        
        comp_screenshots_dir = tmp_path / "output_preview" / "screenshots"
        comp_screenshots_dir.mkdir(parents=True, exist_ok=True)
        screenshot_file = comp_screenshots_dir / "04_comprehensive_1_1s.png"
        
        # 1280x720 のテスト用画像を事前に作成
        img = Image.new("RGB", (1280, 720), (0, 255, 0))
        img.save(screenshot_file)
        
        mock_result = {
            "base": str(tmp_path / "output_preview" / "base_10s.mp4"),
            "logo_telop": str(tmp_path / "output_preview" / "01_logo_telop.mp4"),
            "subtitle_file": None,
            "color_graded": str(tmp_path / "output_preview" / "03_color_graded.mp4"),
            "comprehensive": str(tmp_path / "output_preview" / "04_comprehensive.mp4"),
            "screenshots": {
                "logo": [str(screenshot_file)],
                "color": [str(screenshot_file)],
                "comprehensive": [str(screenshot_file)]
            }
        }
        
        from unittest.mock import patch
        from backend.comprehensive_preview import resolve_comprehensive_preview_task
        
        async def process_wrapper(tid):
            return await resolve_comprehensive_preview_task(agent, tid)
            
        with patch("backend.comprehensive_preview.create_comprehensive_preview", return_value=mock_result):
            await agent.start(process_wrapper)
            for _ in range(30):
                final_status = await agent.get_task_status(task_id)
                if final_status in ("COMPLETED", "FAILED"):
                    break
                await asyncio.sleep(0.1)
            
        final_status = await agent.get_task_status(task_id)
        assert final_status == "COMPLETED"
        
        # DBに保存された結果を検証
        conn = sqlite3.connect(str(db_file))
        try:
            cursor = conn.execute("SELECT result, retry_count, error FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            assert row is not None
            result_json = json.loads(row[0])
            assert result_json["task_id"] == task_id
            assert "validation" in result_json
            assert result_json["validation"][0]["width"] == 1280
            assert result_json["validation"][0]["height"] == 720
        finally:
            conn.close()
            
        await agent.stop()

    @pytest.mark.asyncio
    async def test_stage_bound_agent_integration_retry_on_invalid_image(self, tmp_path):
        """結合テスト: 品質基準違反時に自動的にリトライされるかどうかの検証"""
        from backend.agents.stage_bound_agent import StageBoundAgent
        from PIL import Image
        import asyncio
        
        db_file = tmp_path / "agent_preview_retry.db"
        agent = StageBoundAgent(stage_name="comprehensive_preview", db_path=str(db_file))
        
        video_path = tmp_path / "dummy_video.mp4"
        video_path.write_bytes(b"dummy")
        
        agent.input_video = str(video_path)
        agent.output_dir = str(tmp_path / "output_preview")
        agent.timestamps = [1.0]
        
        # max_retries = 1 (最大2回実行)
        task_id = "t_comp_prev_retry"
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=1)
        
        comp_screenshots_dir = tmp_path / "output_preview" / "screenshots"
        comp_screenshots_dir.mkdir(parents=True, exist_ok=True)
        screenshot_file = comp_screenshots_dir / "retry_screenshot.png"
        
        call_count = 0
        
        def mock_create_preview(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # 1回目は 100x100 の無効な画像（拡張子を無効にして強制エラー）
                img = Image.new("RGB", (100, 100), (0, 0, 0))
                invalid_file = screenshot_file.with_suffix(".txt")
                img.save(invalid_file)
                ret_file = invalid_file
            else:
                # 2回目は 1280x720 の有効な画像
                img = Image.new("RGB", (1280, 720), (0, 255, 0))
                img.save(screenshot_file)
                ret_file = screenshot_file
                
            return {
                "base": str(tmp_path / "base.mp4"),
                "logo_telop": str(tmp_path / "logo.mp4"),
                "subtitle_file": None,
                "color_graded": str(tmp_path / "color.mp4"),
                "comprehensive": str(tmp_path / "comp.mp4"),
                "screenshots": {
                    "comprehensive": [str(ret_file)]
                }
            }
            
        from unittest.mock import patch
        from backend.comprehensive_preview import resolve_comprehensive_preview_task
        
        async def process_wrapper(tid):
            return await resolve_comprehensive_preview_task(agent, tid)
            
        with patch("backend.comprehensive_preview.create_comprehensive_preview", side_effect=mock_create_preview):
            await agent.start(process_wrapper)
            for _ in range(40):
                final_status = await agent.get_task_status(task_id)
                if final_status in ("COMPLETED", "FAILED"):
                    break
                await asyncio.sleep(0.1)
            
        final_status = await agent.get_task_status(task_id)
        assert final_status == "COMPLETED"
        assert call_count == 2
        
        await agent.stop()

    def test_ensure_preview_image_quality_modes(self, tmp_path):
        """自動補正: RGBA, P, L 各モードの画像が正常に RGB に変換・補正されること"""
        from PIL import Image
        from backend.comprehensive_preview import ensure_preview_image_quality, validate_preview_image

        for mode in ["RGBA", "P", "L"]:
            img_path = tmp_path / f"test_{mode}.png"
            if mode == "RGBA":
                img = Image.new("RGBA", (800, 600), (255, 0, 0, 128))
            elif mode == "P":
                img = Image.new("P", (800, 600))
                # 簡易パレット設定
                img.putpalette([255, 0, 0] * 256)
            else:
                img = Image.new("L", (800, 600), 128)

            img.save(img_path)

            res_path = ensure_preview_image_quality(str(img_path))
            result = validate_preview_image(res_path)

            assert result["width"] == 1280
            assert result["height"] == 720
            
            # 保存された画像が RGB モードであることを確認
            with Image.open(res_path) as loaded_img:
                assert loaded_img.mode == "RGB"

    def test_ensure_preview_image_quality_jpeg(self, tmp_path):
        """自動補正: jpeg拡張子の場合、JPEGとして最適化して保存されること"""
        from PIL import Image
        from backend.comprehensive_preview import ensure_preview_image_quality, validate_preview_image

        img_path = tmp_path / "test_jpeg.jpg"
        img = Image.new("RGB", (800, 600), (0, 255, 0))
        img.save(img_path, "JPEG")

        res_path = ensure_preview_image_quality(str(img_path))
        result = validate_preview_image(res_path)

        assert result["width"] == 1280
        assert result["height"] == 720
        assert Path(res_path).suffix.lower() == ".jpg"
        
        # 形式が JPEG であることを確認
        with Image.open(res_path) as loaded_img:
            assert loaded_img.format == "JPEG"

    def test_ensure_preview_image_quality_corrupted_cleanup(self, tmp_path):
        """異常系・クリーンアップ: 破損画像処理時に適切に ValueError が発生し、一時ファイルが残らないこと"""
        from backend.comprehensive_preview import ensure_preview_image_quality
        
        # 破損した偽の画像ファイル（テキストファイル）
        corrupted_path = tmp_path / "corrupted.png"
        corrupted_path.write_text("this is not an image file")

        with pytest.raises(ValueError, match="Failed to process image for quality adjustment"):
            ensure_preview_image_quality(str(corrupted_path))

        # tmpファイルが残っていないか検証
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_validate_preview_image_various_resolutions(self, tmp_path):
        """品質基準テスト: 各種解像度の検証 (1280x720, 1920x1080 はOK、それ未満はNG)"""
        from PIL import Image
        from backend.comprehensive_preview import validate_preview_image

        # 正常系: 1920x1080 (16:9)
        img_path = tmp_path / "valid_high.png"
        img = Image.new("RGB", (1920, 1080), (0, 0, 0))
        img.save(img_path)
        res = validate_preview_image(str(img_path))
        assert res["width"] == 1920
        assert res["height"] == 1080

        # 異常系: 幅が足りない (1279x720)
        img_path = tmp_path / "invalid_width.png"
        img = Image.new("RGB", (1279, 720), (0, 0, 0))
        img.save(img_path)
        with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
            validate_preview_image(str(img_path))

        # 異常系: 高さが足りない (1280x719)
        img_path = tmp_path / "invalid_height.png"
        img = Image.new("RGB", (1280, 719), (0, 0, 0))
        img.save(img_path)
        with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
            validate_preview_image(str(img_path))

    def test_validate_preview_image_strict_aspect_ratios(self, tmp_path):
        """品質基準テスト: アスペクト比16:9の境界値テスト（誤差0.01以内がOK）"""
        from PIL import Image
        from backend.comprehensive_preview import validate_preview_image

        # 正常系: 1280x720 (1.77777...)
        img_path = tmp_path / "aspect_ok.png"
        img = Image.new("RGB", (1280, 720), (0, 0, 0))
        img.save(img_path)
        assert validate_preview_image(str(img_path)) is not None

        # 正常系: わずかにズレているが誤差0.01以内 (1285x720 -> 1.7847, 誤差 0.007)
        img_path = tmp_path / "aspect_near_ok.png"
        img = Image.new("RGB", (1285, 720), (0, 0, 0))
        img.save(img_path)
        assert validate_preview_image(str(img_path)) is not None

        # 異常系: 誤差0.01を超える (1298x720 -> 1.8027, 誤差 0.024)
        img_path = tmp_path / "aspect_ng.png"
        img = Image.new("RGB", (1298, 720), (0, 0, 0))
        img.save(img_path)
        with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
            validate_preview_image(str(img_path))

    def test_validate_preview_image_file_size_boundary(self, tmp_path, monkeypatch):
        """品質基準テスト: 4MBファイルサイズの境界値検証 (4MB未満はOK, 4MB以上はNG)"""
        from PIL import Image
        from pathlib import Path
        from backend.comprehensive_preview import validate_preview_image

        img_path = tmp_path / "boundary.png"
        img = Image.new("RGB", (1280, 720), (0, 0, 0))
        img.save(img_path)

        class MockStat:
            def __init__(self, size):
                self.st_size = size

        orig_stat = Path.stat

        # 4MB - 1バイト (4,194,303 バイト) -> OK
        def mock_stat_ok(self, *args, **kwargs):
            if "boundary.png" in str(self):
                return MockStat(4 * 1024 * 1024 - 1)
            return orig_stat(self, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", mock_stat_ok)
        assert validate_preview_image(str(img_path)) is not None

        # 4MBちょうど (4,194,304 バイト) -> NG
        def mock_stat_ng(self, *args, **kwargs):
            if "boundary.png" in str(self):
                return MockStat(4 * 1024 * 1024)
            return orig_stat(self, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", mock_stat_ng)
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            validate_preview_image(str(img_path))

    def test_ensure_preview_image_quality_io_error_retry(self, tmp_path):
        """堅牢性テスト: I/Oエラー時（ファイルロック等）のリトライ動作検証"""
        from PIL import Image
        import time
        from unittest.mock import patch
        from backend.comprehensive_preview import ensure_preview_image_quality

        img_path = tmp_path / "retry_io.png"
        img = Image.new("RGB", (800, 600), (0, 0, 0))
        img.save(img_path)

        call_count = 0
        orig_save = Image.Image.save

        def mock_save(self, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise OSError("Temporary file lock")
            return orig_save(self, *args, **kwargs)

        with patch("PIL.Image.Image.save", mock_save), \
             patch("time.sleep") as mock_sleep:
            res_path = ensure_preview_image_quality(str(img_path))
            assert Path(res_path).exists()
            assert call_count == 3
            assert mock_sleep.call_count == 2

    def test_create_comprehensive_preview_cleanup_on_error(self, tmp_path):
        """堅牢性テスト: 途中で例外が発生した場合に中間ファイルが確実に削除されることの検証"""
        from unittest.mock import patch
        import sys
        from backend.tests.test_comprehensive_preview import _import_module

        mod = _import_module()
        create_comprehensive_preview = mod.create_comprehensive_preview

        def mock_exists(self):
            # input_video 自体は存在するとみなす
            if "input.mp4" in str(self):
                return True
            return False

        # sys.modules のモックオブジェクトを直接書き換え
        if "combined_overlay" in sys.modules:
            sys.modules["combined_overlay"].CombinedOverlay.return_value.apply_brand_overlay.side_effect = RuntimeError("Overlay failed")

        try:
            with patch.object(Path, "mkdir"), \
                 patch("subprocess.run"), \
                 patch.object(Path, "exists", mock_exists):

                # 例外が伝播することを確認
                with pytest.raises(RuntimeError, match="Overlay failed"):
                    create_comprehensive_preview("input.mp4", str(tmp_path))

                # 一時ファイル (base_10s.mp4) がクリーンアップされて存在しないこと
                temp_video = tmp_path / "base_10s.mp4"
                assert not temp_video.exists()
        finally:
            # モックの挙動をリセット
            if "combined_overlay" in sys.modules:
                sys.modules["combined_overlay"].CombinedOverlay.return_value.apply_brand_overlay.side_effect = None

    def test_ensure_preview_image_quality_size_reduction_retry(self, tmp_path, monkeypatch):
        """品質基準テスト: 4MB制限を超えた場合に自動圧縮リカバリが段階的に行われ、最終的に4MB未満で保存されること"""
        from PIL import Image
        from pathlib import Path
        img_path = tmp_path / "large_image.png"
        img = Image.new("RGB", (2000, 1500), (0, 0, 0))
        img.save(img_path)
        
        # 1回目と2回目の save 後のファイルサイズを4MB以上 (5MB)、3回目を3MBにするモック
        call_count = 0
        orig_stat = Path.stat
        
        class MockStat:
            def __init__(self, size):
                self.st_size = size
                
        def mock_stat(self, *args, **kwargs):
            nonlocal call_count
            if "large_image" in str(self):
                if ".tmp" in str(self):
                    call_count += 1
                    if call_count == 1:
                        return MockStat(5 * 1024 * 1024) # 5MB
                    elif call_count == 2:
                        return MockStat(4.5 * 1024 * 1024) # 4.5MB
                    else:
                        return MockStat(3 * 1024 * 1024) # 3MB
                # リネーム後の元ファイルに対するstat取得時は、直近のサイズ（3MB）を返す
                if call_count >= 3:
                    return MockStat(3 * 1024 * 1024)
                return MockStat(5 * 1024 * 1024)
            return orig_stat(self, *args, **kwargs)
            
        monkeypatch.setattr(Path, "stat", mock_stat)
        
        from backend.comprehensive_preview import ensure_preview_image_quality, validate_preview_image
        res_path = ensure_preview_image_quality(str(img_path))
        
        result = validate_preview_image(res_path)
        assert result["width"] == 1280
        assert result["height"] == 720
        assert call_count >= 3

    def test_ensure_preview_image_quality_upscale_low_res(self, tmp_path):
        """品質基準テスト: 低解像度の画像（例: 320x180）が正しく1280x720にアップスケールされパディングされること"""
        from PIL import Image
        from backend.comprehensive_preview import ensure_preview_image_quality, validate_preview_image
        img_path = tmp_path / "low_res_target.png"
        img = Image.new("RGB", (320, 180), (100, 100, 100))
        img.save(img_path)
        
        res_path = ensure_preview_image_quality(str(img_path))
        result = validate_preview_image(res_path)
        assert result["width"] == 1280
        assert result["height"] == 720

    def test_ensure_preview_image_quality_extreme_aspect_padding(self, tmp_path):
        """品質基準テスト: アスペクト比が極端な画像がアスペクト比16:9で正常に黒帯パディングされること"""
        from PIL import Image
        from backend.comprehensive_preview import ensure_preview_image_quality, validate_preview_image
        img_path = tmp_path / "extreme_aspect.png"
        img = Image.new("RGB", (2000, 400), (255, 255, 255))
        img.save(img_path)
        
        res_path = ensure_preview_image_quality(str(img_path))
        result = validate_preview_image(res_path)
        assert result["width"] == 1280
        assert result["height"] == 720

    def test_ensure_preview_image_quality_all_compression_fails(self, tmp_path, monkeypatch):
        """堅牢性テスト: すべてのフォーマット試行で4MB未満に収まらなかった場合にValueErrorが発生し、一時ファイルが残らないこと"""
        from PIL import Image
        from pathlib import Path
        import pytest
        img_path = tmp_path / "never_shrink.png"
        img = Image.new("RGB", (1280, 720), (0, 0, 0))
        img.save(img_path)
        
        class MockStat:
            def __init__(self, size):
                self.st_size = size
                
        orig_stat = Path.stat
        def mock_stat_always_large(self, *args, **kwargs):
            if "never_shrink" in str(self):
                return MockStat(5 * 1024 * 1024)
            return orig_stat(self, *args, **kwargs)
            
        monkeypatch.setattr(Path, "stat", mock_stat_always_large)
        
        from backend.comprehensive_preview import ensure_preview_image_quality
        with pytest.raises(ValueError, match="Could not reduce image file size below 4MB"):
            ensure_preview_image_quality(str(img_path))
            
        # 一時ファイルが残っていないか検証
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_ensure_preview_image_quality_blur_padding(self, tmp_path):
        """品質基準テスト: padding_mode="blur" を指定した場合に、背景がブラー処理された1280x720の画像が生成されること"""
        from PIL import Image
        from backend.comprehensive_preview import ensure_preview_image_quality, validate_preview_image
        
        # 縦横比が 4:3 (800x600) のテスト用画像を作成
        img_path = tmp_path / "to_blur_adjust.png"
        img = Image.new("RGB", (800, 600), (255, 0, 0))
        img.save(img_path)
        
        res_path = ensure_preview_image_quality(str(img_path), padding_mode="blur")
        
        result = validate_preview_image(res_path)
        assert result["width"] == 1280
        assert result["height"] == 720
        
        # 生成された画像が単調な黒帯ではなく、背景に色（元の赤がブラーされたものなど）が含まれていることを検証
        with Image.open(res_path) as out_img:
            edge_pixel = out_img.getpixel((10, 360))
            assert edge_pixel != (0, 0, 0), f"Edge pixel is black, blur padding might have failed: {edge_pixel}"
            assert edge_pixel[0] > 50 and edge_pixel[1] < 100 and edge_pixel[2] < 100

    def test_ensure_preview_image_quality_decompression_bomb(self, tmp_path):
        """堅牢性テスト: 巨大すぎる画像が渡された場合に、DecompressionBombErrorを回避してValueErrorが発生すること"""
        from PIL import Image
        import pytest
        from backend.comprehensive_preview import ensure_preview_image_quality
        from PIL.Image import DecompressionBombError
        
        img_path = tmp_path / "huge_bomb.png"
        img_path.write_bytes(b"dummy image data")
        
        def mock_open_bomb(*args, **kwargs):
            raise DecompressionBombError("Image size exceeds limit")
            
        from unittest.mock import patch
        with patch("PIL.Image.open", side_effect=mock_open_bomb):
            with pytest.raises(ValueError, match="Image size exceeds safety limits or is corrupted"):
                ensure_preview_image_quality(str(img_path))

    def test_ensure_preview_image_quality_rename_fallback(self, tmp_path):
        """堅牢性テスト: 一時ファイルのリネームが例外（Windows環境のロック等）で失敗した際、
        shutil.copyとunlinkによる代替処理で正常に保存されること"""
        from PIL import Image
        from pathlib import Path
        import shutil
        from unittest.mock import patch
        from backend.comprehensive_preview import ensure_preview_image_quality, validate_preview_image
        
        img_path = tmp_path / "rename_fail.png"
        img = Image.new("RGB", (800, 600), (0, 255, 0))
        img.save(img_path)
        
        rename_calls = 0
        
        def mock_os_replace(src, dst):
            nonlocal rename_calls
            rename_calls += 1
            raise PermissionError("Access denied (Windows mock)")
            
        with patch("backend.comprehensive_preview.os.replace", mock_os_replace), \
             patch("shutil.copy", wraps=shutil.copy) as mock_copy:
             
            res_path = ensure_preview_image_quality(str(img_path))
            
            assert mock_copy.call_count > 0
            assert Path(res_path).exists()
            
            result = validate_preview_image(res_path)
            assert result["width"] == 1280
            assert result["height"] == 720

    @pytest.mark.asyncio
    async def test_comprehensive_thumbnail_quality_standards_and_agent_integration(self, tmp_path):
        """品質基準（解像度 1280x720 以上、16:9 アスペクト比、4MB未満、正常ロード可能）と
        StageBoundAgent / DBマイグレーションとの連携を自動検証するテスト"""
        from PIL import Image
        from backend.comprehensive_preview import validate_preview_image, ensure_preview_image_quality
        from backend.agents.stage_bound_agent import StageBoundAgent
        import sqlite3
        import json
        import os

        # 1. 正常な品質基準を満たす画像の検証
        img_path_ok = tmp_path / "img_ok.png"
        img_ok = Image.new("RGB", (1280, 720), (0, 255, 0))
        img_ok.save(img_path_ok)

        val_res = validate_preview_image(str(img_path_ok))
        assert val_res["width"] == 1280
        assert val_res["height"] == 720
        assert val_res["size_bytes"] < 4 * 1024 * 1024
        
        # 破損していないことを Pillow で正常ロードして再確認
        with Image.open(val_res["path"]) as loaded_img:
            loaded_img.load()
            assert loaded_img.size == (1280, 720)

        # 2. 品質基準から外れた画像の自動補正・検証
        # 解像度不足かつアスペクト比が 4:3 (800x600) の画像
        img_path_ng = tmp_path / "img_ng.png"
        img_ng = Image.new("RGB", (800, 600), (255, 0, 0))
        img_ng.save(img_path_ng)

        # 自動品質補正を呼び出す
        res_path_corrected = ensure_preview_image_quality(str(img_path_ng))
        
        # 補正後の画像を検証
        val_res_corrected = validate_preview_image(res_path_corrected)
        assert val_res_corrected["width"] == 1280
        assert val_res_corrected["height"] == 720
        assert val_res_corrected["size_bytes"] < 4 * 1024 * 1024
        
        # アスペクト比が 16:9 になっていることを確認
        assert abs((val_res_corrected["width"] / val_res_corrected["height"]) - (16.0 / 9.0)) <= 0.01

        # 3. StageBoundAgent / DBマイグレーションとの連携検証
        db_file = tmp_path / "test_migration_integration.db"
        
        # テストのためにDBマイグレーションと連携された StageBoundAgent を初期化
        agent = StageBoundAgent(stage_name="comprehensive_preview", db_path=str(db_file))
        
        # DBテーブルの存在とマイグレーションの確認
        conn = sqlite3.connect(str(db_file))
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks';")
            assert cursor.fetchone() is not None
            
            # カラム（id, status, result, error, retry_count, updated_at）が存在することを確認
            cursor.execute("PRAGMA table_info(tasks);")
            columns = {col[1] for col in cursor.fetchall()}
            for expected_col in ["id", "status", "result", "error", "retry_count", "updated_at"]:
                assert expected_col in columns
        finally:
            conn.close()

        # タスク結果保存・自動リトライ連携の確認
        task_id = "test_task_standards_01"
        
        # READY で登録
        import asyncio
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=2)
        
        # ダミーの処理結果を設定してタスク実行
        dummy_result = {
            "task_id": task_id,
            "validation": [val_res_corrected]
        }
        
        async def mock_process(tid):
            return json.dumps(dummy_result)

        # Agentを起動してタスクを処理させる
        await agent.start(mock_process)
        await asyncio.sleep(0.1)
        await agent.stop()

        # DB上の結果が COMPLETED になり、結果データが正しく保存されていることを検証
        conn = sqlite3.connect(str(db_file))
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT status, result, retry_count, error FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == "COMPLETED"
            saved_result = json.loads(row[1])
            assert saved_result["validation"][0]["width"] == 1280
            assert saved_result["validation"][0]["height"] == 720
            assert row[2] == 0  # retry_count
            assert row[3] is None  # error
        finally:
            conn.close()

    @pytest.mark.asyncio
    async def test_explicit_thumbnail_quality_improvement_standards(self, tmp_path):
        """
        ユーザー要求仕様「サムネイル品質向上」の自動検証テスト。
        - 生成画像の解像度が 1280x720 以上であること
        - アスペクト比が 16:9 であること
        - ファイルサイズが 4MB 未満であること
        - 出力ファイルが正常に存在し、破損していない（Pillow等で正常にロード可能である）こと
        - StageBoundAgent 等に登録され、自動リトライや結果保存、DBマイグレーションの各機能と連携して動作すること
        """
        from PIL import Image
        from backend.comprehensive_preview import validate_preview_image, ensure_preview_image_quality
        from backend.agents.stage_bound_agent import StageBoundAgent
        import sqlite3
        import json
        import asyncio
        from pathlib import Path

        # 1. 解像度、アスペクト比、ファイルサイズ、破損なしロードの検証
        # テスト用の解像度 800x600 の画像を生成し、自動補正をかける
        raw_img_path = tmp_path / "raw_thumbnail.png"
        raw_img = Image.new("RGB", (800, 600), (120, 120, 120))
        raw_img.save(str(raw_img_path))

        # 自動補正の適用
        corrected_path = ensure_preview_image_quality(str(raw_img_path))

        # 品質基準の検証
        val_res = validate_preview_image(corrected_path)
        
        # - 生成画像の解像度が 1280x720 以上であること
        assert val_res["width"] >= 1280
        assert val_res["height"] >= 720
        
        # - アスペクト比が 16:9 であること (誤差0.01以内)
        aspect_ratio = val_res["width"] / val_res["height"]
        assert abs(aspect_ratio - (16.0 / 9.0)) <= 0.01
        
        # - ファイルサイズが 4MB 未満であること
        assert val_res["size_bytes"] < 4 * 1024 * 1024
        
        # - 出力ファイルが正常に存在し、破損していない（Pillow等で正常にロード可能である）こと
        assert Path(corrected_path).exists()
        with Image.open(corrected_path) as loaded_img:
            loaded_img.load() # 正常にロード可能であることを確認
            assert loaded_img.size == (1280, 720)

        # 2. StageBoundAgent 連携 (自動リトライ、結果保存、DBマイグレーション)
        db_file = tmp_path / "explicit_migration_test.db"
        agent = StageBoundAgent(stage_name="comprehensive_preview", db_path=str(db_file))

        # DBマイグレーションが実行され、必要なテーブルとカラムが存在することの検証
        conn = sqlite3.connect(str(db_file))
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks';")
            assert cursor.fetchone() is not None, "tasks table must exist"
            
            cursor.execute("PRAGMA table_info(tasks);")
            columns = {col[1] for col in cursor.fetchall()}
            for col in ["id", "status", "result", "error", "retry_count"]:
                assert col in columns, f"Column {col} must exist in tasks table"
        finally:
            conn.close()

        # タスク登録・実行・結果保存の検証
        task_id = "explicit_task_01"
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=2)

        # ダミーの処理結果（検証データを含む）を返すプロセス関数
        dummy_result = {
            "task_id": task_id,
            "validation": [val_res]
        }

        async def process_func(tid):
            return json.dumps(dummy_result)

        # Agentの開始と停止
        await agent.start(process_func)
        await asyncio.sleep(0.1)
        await agent.stop()

        # DB保存結果の検証
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
            assert row[2] == 0  # retry_count
            assert row[3] is None  # error
        finally:
            conn.close()

    def test_ensure_preview_image_quality_brightness_and_color_enhancement(self, tmp_path):
        """品質向上テスト: 暗い画像が渡された場合に明るさと色彩が向上されることを検証"""
        from PIL import Image
        from backend.comprehensive_preview import ensure_preview_image_quality
        
        # 16:9 の非常に暗いグレーの画像 (RGB = 30, 30, 30)
        img_path = tmp_path / "dark_image.png"
        img = Image.new("RGB", (800, 450), (30, 30, 30))
        img.save(img_path)
        
        res_path = ensure_preview_image_quality(str(img_path))
        
        # 補正後の画像を読み込み、平均輝度と色彩が向上していることを確認
        with Image.open(res_path) as corrected_img:
            stat_img = corrected_img.convert("L")
            mean_brightness = sum(stat_img.getdata()) / (1280 * 720)
            assert mean_brightness > 30.0

    def test_ensure_preview_image_quality_cleanup_on_save_error(self, tmp_path):
        """堅牢性テスト: 保存処理中に例外が発生した場合、一時ファイルが確実に削除されることの検証"""
        from PIL import Image
        from unittest.mock import patch
        from backend.comprehensive_preview import ensure_preview_image_quality
        
        img_path = tmp_path / "error_trigger.png"
        img = Image.new("RGB", (800, 600), (0, 0, 0))
        img.save(img_path)
        
        # 保存時に例外を発生させる
        def mock_save_error(*args, **kwargs):
            raise IOError("Disk full or permission denied")
            
        with patch("PIL.Image.Image.save", side_effect=mock_save_error):
            # 例外メッセージは 4MB 以下への圧縮失敗になる
            with pytest.raises(ValueError, match="Could not reduce image file size below 4MB"):
                ensure_preview_image_quality(str(img_path))
                
        # 一時ファイル（.tmp）が残っていないことを検証
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0, f"Temp files remained: {tmp_files}"

    def test_ensure_preview_image_quality_unsharp_mask_applied(self, tmp_path):
        """品質向上テスト: リサイズ時にアンシャープマスクフィルタが正常に適用されることの検証"""
        from PIL import Image, ImageFilter
        from unittest.mock import patch
        from backend.comprehensive_preview import ensure_preview_image_quality
        
        img_path = tmp_path / "test_unsharp.png"
        # リサイズが発生するように 800x600 の画像を生成
        img = Image.new("RGB", (800, 600), (128, 128, 128))
        img.save(img_path)
        
        filter_called = False
        orig_filter = Image.Image.filter
        
        def mock_filter(self, filter_obj):
            nonlocal filter_called
            if isinstance(filter_obj, ImageFilter.UnsharpMask):
                filter_called = True
                assert filter_obj.radius == 1.5
                assert filter_obj.percent == 125
                assert filter_obj.threshold == 1
            return orig_filter(self, filter_obj)
            
        with patch("PIL.Image.Image.filter", mock_filter):
            ensure_preview_image_quality(str(img_path))
            
        assert filter_called, "ImageFilter.UnsharpMask was not applied"

    def test_ensure_preview_image_quality_quantization_dither_applied(self, tmp_path, monkeypatch):
        """品質向上テスト: PNG-8 減色圧縮時にディザリングオプションが指定されて実行されることの検証"""
        from PIL import Image
        from pathlib import Path
        from unittest.mock import patch
        from backend.comprehensive_preview import ensure_preview_image_quality
        
        img_path = tmp_path / "test_dither.png"
        img = Image.new("RGB", (800, 600), (0, 0, 0))
        img.save(img_path)
        
        # 1回目のPNG保存（quantizeなし）で4MBを超えているとみなし、2回目のquantize保存を行わせる
        # 3回目（ditherあり）などを誘発させるためにサイズチェックをモック
        call_count = 0
        class MockStat:
            def __init__(self, size):
                self.st_size = size
                
        orig_stat = Path.stat
        def mock_stat_forcing_fallback(self, *args, **kwargs):
            nonlocal call_count
            if "test_dither" in str(self) and ".tmp" in str(self):
                call_count += 1
                if call_count == 1:
                    # 1回目は4MB超
                    return MockStat(5 * 1024 * 1024)
                else:
                    # 2回目（quantize実行時）は4MB未満にして成功させる
                    return MockStat(2 * 1024 * 1024)
            return orig_stat(self, *args, **kwargs)
            
        monkeypatch.setattr(Path, "stat", mock_stat_forcing_fallback)
        
        quantize_called = False
        orig_quantize = Image.Image.quantize
        
        def mock_quantize(self, colors=256, dither=1, **kwargs):
            nonlocal quantize_called
            quantize_called = True
            # Floyd-Steinberg dithering 定数が指定されているか検証
            dither_val = getattr(Image, "FLOYDSTEINBERG", 1)
            assert dither == dither_val
            return orig_quantize(self, colors=colors, dither=dither, **kwargs)
            
        with patch("PIL.Image.Image.quantize", mock_quantize):
            ensure_preview_image_quality(str(img_path))
            
        assert quantize_called, "quantize with dither was not called"

    def test_ensure_preview_image_quality_noise_reduction_smooth(self, tmp_path, monkeypatch):
        """品質向上テスト: 減色しても4MBに収まらない場合に、ノイズ低減フィルター（SMOOTH）を適用して再圧縮することの検証"""
        from PIL import Image, ImageFilter
        from pathlib import Path
        from unittest.mock import patch
        from backend.comprehensive_preview import ensure_preview_image_quality
        
        img_path = tmp_path / "test_smooth.png"
        img = Image.new("RGB", (800, 600), (0, 0, 0))
        img.save(img_path)
        
        # 1回目 (通常PNG), 2回目 (Quantize), 3回目 (Quantize + Smooth) までのサイズチェックを制御
        call_count = 0
        class MockStat:
            def __init__(self, size):
                self.st_size = size
                
        orig_stat = Path.stat
        def mock_stat_forcing_smooth(self, *args, **kwargs):
            nonlocal call_count
            if "test_smooth" in str(self) and ".tmp" in str(self):
                call_count += 1
                if call_count <= 2:
                    # 1, 2回目は4MB超
                    return MockStat(5 * 1024 * 1024)
                else:
                    # 3回目 (Smooth適用時) は4MB未満にして成功させる
                    return MockStat(2 * 1024 * 1024)
            return orig_stat(self, *args, **kwargs)
            
        monkeypatch.setattr(Path, "stat", mock_stat_forcing_smooth)
        
        smooth_applied = False
        orig_filter = Image.Image.filter
        
        def mock_filter(self, filter_obj):
            nonlocal smooth_applied
            if filter_obj == ImageFilter.SMOOTH:
                smooth_applied = True
            return orig_filter(self, filter_obj)
            
        with patch("PIL.Image.Image.filter", mock_filter):
            ensure_preview_image_quality(str(img_path))
            
        assert smooth_applied, "ImageFilter.SMOOTH was not applied under high compression pressure"

    def test_ensure_preview_image_quality_brightness_bright_image(self, tmp_path):
        """品質向上テスト: 明るすぎる画像（平均輝度 >= 200）が渡された場合、白飛び防止として輝度が下げられることの検証"""
        from PIL import Image
        from backend.comprehensive_preview import ensure_preview_image_quality
        
        # 16:9 の明るい白画像 (RGB = 220, 220, 220) -> 平均輝度 220
        img_path = tmp_path / "bright_image.png"
        img = Image.new("RGB", (800, 450), (220, 220, 220))
        img.save(img_path)
        
        res_path = ensure_preview_image_quality(str(img_path))
        
        with Image.open(res_path) as corrected_img:
            stat_img = corrected_img.convert("L")
            mean_brightness = sum(stat_img.getdata()) / (1280 * 720)
            # 明るさが抑えられていることを検証
            assert mean_brightness < 210.0

    def test_ensure_preview_image_quality_adaptive_contrast_flat_image(self, tmp_path):
        """品質向上テスト: コントラストが極めて低い平坦な画像（輝度範囲 < 100）の場合、コントラスト補正強度が上がることの検証"""
        from PIL import Image, ImageEnhance
        from unittest.mock import patch
        from backend.comprehensive_preview import ensure_preview_image_quality
        
        # 非常にフラットなグレー画像 (RGB = 125, 125, 125)
        img_path = tmp_path / "flat_contrast_image.png"
        img = Image.new("RGB", (800, 450), (125, 125, 125))
        # わずかなノイズを入れて単調な画像にする
        pixels = img.load()
        pixels[0, 0] = (120, 120, 120)
        pixels[10, 10] = (130, 130, 130)
        img.save(img_path)
        
        contrast_factor_applied = None
        orig_enhance = ImageEnhance.Contrast.enhance
        
        def mock_enhance(self, factor):
            nonlocal contrast_factor_applied
            contrast_factor_applied = factor
            return orig_enhance(self, factor)
            
        with patch("backend.comprehensive_preview.ImageEnhance.Contrast.enhance", mock_enhance):
            ensure_preview_image_quality(str(img_path))
            
        # コントラスト係数 1.25（ImageOps.equalize 適用による補正強度の増加）が適用されたことを検証
        assert contrast_factor_applied == 1.25

    def test_validate_preview_image_custom_exceptions(self, tmp_path, monkeypatch):
        """エラーハンドリングテスト: 品質要件を満たさない各ケースにおいて、適切なカスタム例外が発生することの検証"""
        from PIL import Image
        from pathlib import Path
        from backend.comprehensive_preview import (
            validate_preview_image,
            PreviewImageSizeExceededError,
            PreviewResolutionError
        )
        
        # 1. 解像度不足 -> PreviewResolutionError
        img_path_low = tmp_path / "low_res_custom.png"
        Image.new("RGB", (100, 100)).save(img_path_low)
        with pytest.raises(PreviewResolutionError):
            validate_preview_image(str(img_path_low))
            
        # 2. アスペクト比不正 -> PreviewResolutionError
        img_path_aspect = tmp_path / "bad_aspect_custom.png"
        Image.new("RGB", (1280, 800)).save(img_path_aspect)
        with pytest.raises(PreviewResolutionError):
            validate_preview_image(str(img_path_aspect))

        # 3. ファイルサイズ上限超過 -> PreviewImageSizeExceededError
        img_path_size = tmp_path / "large_size_custom.png"
        Image.new("RGB", (1280, 720)).save(img_path_size)
        
        class MockStat:
            def __init__(self, size):
                self.st_size = size
                
        orig_stat = Path.stat
        def mock_stat(self, *args, **kwargs):
            if "large_size_custom.png" in str(self):
                return MockStat(5 * 1024 * 1024)
            return orig_stat(self, *args, **kwargs)
            
        monkeypatch.setattr(Path, "stat", mock_stat)
        with pytest.raises(PreviewImageSizeExceededError):
            validate_preview_image(str(img_path_size))

    def test_validate_preview_image_truncated_detection(self, tmp_path):
        """エラーハンドリングテスト: 途中で切れた破損画像（truncated）が PreviewImageCorruptedError として検出されることの検証"""
        from PIL import Image
        import io
        from backend.comprehensive_preview import validate_preview_image, PreviewImageCorruptedError
        
        img_path = tmp_path / "truncated_custom.png"
        
        # 正しいPNGファイルを作成
        img = Image.new("RGB", (1280, 720), (255, 0, 0))
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_bytes = img_byte_arr.getvalue()
        
        # データを途中で切り捨てる（意図的な破損）
        truncated_bytes = img_bytes[:len(img_bytes) // 2]
        img_path.write_bytes(truncated_bytes)
        
        with pytest.raises(PreviewImageCorruptedError):
            validate_preview_image(str(img_path))

    def test_ensure_preview_image_quality_jpeg_subsampling_passed(self, tmp_path):
        """品質向上テスト: JPEG保存時に subsampling=0 が指定されていることの検証"""
        from PIL import Image
        from unittest.mock import patch
        from backend.comprehensive_preview import ensure_preview_image_quality
        
        img_path = tmp_path / "test_jpeg_subsampling.jpg"
        Image.new("RGB", (800, 600)).save(img_path, "JPEG")
        
        save_kwargs_captured = []
        orig_save = Image.Image.save
        
        def mock_save(self, fp, format=None, **kwargs):
            save_kwargs_captured.append(kwargs)
            return orig_save(self, fp, format=format, **kwargs)
            
        with patch("PIL.Image.Image.save", mock_save):
            ensure_preview_image_quality(str(img_path))
            
        # subsampling が 0 (4:4:4) であることを確認する
        found_subsampling_0 = any(kw.get("subsampling") == 0 for kw in save_kwargs_captured)
        assert found_subsampling_0, "subsampling=0 was not passed during JPEG save"

    def test_create_comprehensive_preview_cleanup_retry_flow(self, tmp_path):
        """堅牢性テスト: 例外発生時のクリーンアップ処理において、削除失敗時にリトライおよび最終クリーンアップが行われることの検証"""
        from unittest.mock import patch, MagicMock
        from backend.tests.test_comprehensive_preview import _import_module
        import time
        import sys
        
        mod = _import_module()
        create_comprehensive_preview = mod.create_comprehensive_preview
        
        def mock_exists(self):
            name = str(self)
            if "input.mp4" in name or "base_10s.mp4" in name:
                return True
            return False
            
        # combined_overlay で例外を発生させる
        if "combined_overlay" in sys.modules:
            sys.modules["combined_overlay"].CombinedOverlay.return_value.apply_brand_overlay.side_effect = RuntimeError("Overlay error")
            
        unlink_calls = 0
        orig_unlink = Path.unlink
        
        # 最初の2回は permission error で unlink を失敗させ、3回目に成功させる
        def mock_unlink(self, *args, **kwargs):
            nonlocal unlink_calls
            if "base_10s.mp4" in str(self):
                unlink_calls += 1
                if unlink_calls < 3:
                    raise PermissionError("File locked by another process (mock)")
                return None
            return orig_unlink(self, *args, **kwargs)
            
        try:
            with patch.object(Path, "mkdir"), \
                 patch("subprocess.run"), \
                 patch.object(Path, "exists", mock_exists), \
                 patch.object(Path, "unlink", mock_unlink), \
                 patch("time.sleep") as mock_sleep:
                 
                with pytest.raises(RuntimeError, match="Overlay error"):
                    create_comprehensive_preview("input.mp4", str(tmp_path))
                    
                # unlink がリトライされ、計3回試行されたことを検証
                assert unlink_calls == 3
                assert mock_sleep.call_count == 2
        finally:
            if "combined_overlay" in sys.modules:
                sys.modules["combined_overlay"].CombinedOverlay.return_value.apply_brand_overlay.side_effect = None

    def test_ensure_preview_image_quality_retains_icc_profile(self, tmp_path):
        """品質向上テスト: 元画像にICCカラープロファイルが含まれる場合、補正後も保持されることの検証"""
        from PIL import Image
        from backend.comprehensive_preview import ensure_preview_image_quality
        
        # ダミーのICCプロファイル付き画像を作成
        img_path = tmp_path / "test_icc.png"
        img = Image.new("RGB", (800, 600), (255, 0, 0))
        dummy_icc = b"dummy_icc_profile_data"
        img.save(img_path, "PNG", icc_profile=dummy_icc)
        
        # 補正を実行
        res_path = ensure_preview_image_quality(str(img_path))
        
        # 補正後の画像を読み込んでICCプロファイルが存在し、維持されていることを確認
        with Image.open(res_path) as corrected_img:
            assert corrected_img.info.get("icc_profile") == dummy_icc

    def test_create_comprehensive_preview_throws_custom_error_on_ffmpeg_failure(self):
        """エラーハンドリングテスト: FFmpeg失敗時に PreviewGenerationError がスローされることの検証"""
        from unittest.mock import patch
        from backend.tests.test_comprehensive_preview import _import_module
        
        mod = _import_module()
        
        with patch.object(Path, "mkdir"), \
             patch.object(Path, "exists", return_value=True), \
             patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "ffmpeg", stderr=b"ffmpeg failure")):
             
            with pytest.raises(mod.PreviewGenerationError, match="ffmpeg extraction failed"):
                mod.create_comprehensive_preview("input.mp4")

    @pytest.mark.asyncio
    async def test_resolve_comprehensive_preview_task_wraps_exception(self):
        """エラーハンドリングテスト: タスク実行中に例外が発生した場合、PreviewGenerationError にラップされることの検証"""
        from unittest.mock import patch
        from backend.comprehensive_preview import resolve_comprehensive_preview_task, PreviewGenerationError
        
        class DummyAgent:
            input_video = "dummy.mp4"
            output_dir = "dummy_dir"
            timestamps = [1.0]
            
        agent = DummyAgent()
        
        with patch("backend.comprehensive_preview.create_comprehensive_preview", side_effect=RuntimeError("something went wrong")):
            with pytest.raises(PreviewGenerationError, match="Task execution failed: something went wrong"):
                await resolve_comprehensive_preview_task(agent, "task_01")

    def test_validate_preview_image_empty_file(self, tmp_path):
        """境界値テスト: ファイルサイズが0の空ファイルの場合に PreviewImageCorruptedError が発生することを確認"""
        from backend.comprehensive_preview import validate_preview_image, PreviewImageCorruptedError
        empty_file = tmp_path / "empty_image_backend.png"
        empty_file.touch()
        
        with pytest.raises(PreviewImageCorruptedError, match="Image file is empty"):
            validate_preview_image(str(empty_file))

    def test_ensure_preview_image_quality_corrupted_icc_profile(self, tmp_path):
        """エッジケーステスト: 破損したICCプロファイルを持つ画像が渡された場合に、デコードまたは検証段階で適切にエラーが捕捉されることを確認"""
        from PIL import Image
        from backend.comprehensive_preview import ensure_preview_image_quality, validate_preview_image, PreviewImageCorruptedError
        img_path = tmp_path / "corrupted_icc_backend.png"
        img = Image.new("RGB", (800, 600), color=(100, 100, 100))
        img.save(img_path, format="PNG", icc_profile=b"corrupted_icc_bytes_that_are_invalid_and_too_short")
        
        try:
            res_path = ensure_preview_image_quality(str(img_path))
            res = validate_preview_image(res_path)
            assert res["width"] == 1280
            assert res["height"] == 720
        except (PreviewImageCorruptedError, ValueError):
            pass

    def test_ensure_preview_image_quality_vertical_aspect_padding(self, tmp_path):
        """品質基準テスト: 縦長アスペクト比（9:16, 例: 540x960）の入力画像が、自動補正によりアスペクト比16:9かつ解像度1280x720以上に正しく変換されることを検証"""
        from PIL import Image
        from backend.comprehensive_preview import ensure_preview_image_quality, validate_preview_image
        
        img_path = tmp_path / "vertical_input.png"
        img = Image.new("RGB", (540, 960), (0, 0, 255))
        img.save(img_path)
        
        res_path = ensure_preview_image_quality(str(img_path))
        result = validate_preview_image(res_path)
        
        assert result["width"] >= 1280
        assert result["height"] >= 720
        aspect_ratio = result["width"] / result["height"]
        assert abs(aspect_ratio - (16.0 / 9.0)) <= 0.01

    def test_ensure_preview_image_quality_square_aspect_padding(self, tmp_path):
        """品質基準テスト: 正方形アスペクト比（1:1, 例: 800x800）の入力画像が、自動補正によりアスペクト比16:9かつ解像度1280x720以上に正しく変換されることを検証"""
        from PIL import Image
        from backend.comprehensive_preview import ensure_preview_image_quality, validate_preview_image
        
        img_path = tmp_path / "square_input.png"
        img = Image.new("RGB", (800, 800), (0, 255, 0))
        img.save(img_path)
        
        res_path = ensure_preview_image_quality(str(img_path))
        result = validate_preview_image(res_path)
        
        assert result["width"] >= 1280
        assert result["height"] >= 720
        aspect_ratio = result["width"] / result["height"]
        assert abs(aspect_ratio - (16.0 / 9.0)) <= 0.01

    def test_validate_preview_image_border_cases_resolution_and_aspect(self, tmp_path):
        """境界値テスト: 厳密な解像度(1280x720)およびアスペクト比の誤差許容上限(0.01)の境界値における動作検証"""
        from PIL import Image
        from backend.comprehensive_preview import validate_preview_image, PreviewResolutionError
        
        # 1. ちょうど 1280x720 (16:9) -> 成功
        img_path_exact = tmp_path / "exact_1280.png"
        Image.new("RGB", (1280, 720), (255, 255, 255)).save(img_path_exact)
        res_exact = validate_preview_image(str(img_path_exact))
        assert res_exact["width"] == 1280
        assert res_exact["height"] == 720

        # 2. アスペクト比の誤差許容上限のギリギリ内側 (1286x720 -> 1.7861, 16:9との差は約0.0083 <= 0.01) -> 成功
        img_path_limit_in = tmp_path / "limit_in.png"
        Image.new("RGB", (1286, 720), (255, 255, 255)).save(img_path_limit_in)
        assert validate_preview_image(str(img_path_limit_in)) is not None

        # 3. アスペクト比の誤差許容上限のギリギリ外側 (1288x720 -> 1.7888, 16:9との差は約0.0111 > 0.01) -> 失敗
        img_path_limit_out = tmp_path / "limit_out.png"
        Image.new("RGB", (1288, 720), (255, 255, 255)).save(img_path_limit_out)
        with pytest.raises(PreviewResolutionError, match="Aspect ratio must be 16:9"):
            validate_preview_image(str(img_path_limit_out))

    def test_ensure_preview_image_quality_low_contrast_flat_equalize(self, tmp_path):
        """品質向上テスト: 非常にフラットなグレー画像（コントラスト範囲 < 50）の場合、ImageOps.equalize が適用されることを検証"""
        from PIL import Image, ImageOps
        from unittest.mock import patch
        from backend.comprehensive_preview import ensure_preview_image_quality

        img_path = tmp_path / "super_flat_image.png"
        # ほぼ単一色の極めてコントラストの低い画像
        img = Image.new("RGB", (800, 450), (128, 128, 128))
        pixels = img.load()
        pixels[0, 0] = (127, 127, 127)
        pixels[10, 10] = (129, 129, 129)
        img.save(img_path)

        equalize_called = False
        orig_equalize = ImageOps.equalize

        def mock_equalize(image, mask=None):
            nonlocal equalize_called
            equalize_called = True
            return orig_equalize(image, mask=mask)

        with patch("backend.comprehensive_preview.ImageOps.equalize", mock_equalize):
            ensure_preview_image_quality(str(img_path))

        assert equalize_called, "ImageOps.equalize was not applied to a very flat image"

    def test_ensure_preview_image_quality_unsupported_extension(self, tmp_path):
        """エラーハンドリングテスト: サポートされていない拡張子のファイルが渡された場合、PreviewGenerationError が発生することを確認"""
        from backend.comprehensive_preview import ensure_preview_image_quality, PreviewGenerationError
        
        img_path = tmp_path / "test.gif"
        # ファイルは存在してもしなくても、拡張子チェックで弾かれるはず
        with pytest.raises(PreviewGenerationError, match="Unsupported file format: .gif"):
            ensure_preview_image_quality(str(img_path))

    def test_ensure_preview_image_quality_invalid_padding_mode(self, tmp_path):
        """エラーハンドリングテスト: 無効な padding_mode が渡された場合、PreviewGenerationError が発生することを確認"""
        from PIL import Image
        from backend.comprehensive_preview import ensure_preview_image_quality, PreviewGenerationError
        
        img_path = tmp_path / "padding_test.png"
        Image.new("RGB", (800, 600)).save(img_path)
        
        with pytest.raises(PreviewGenerationError, match="Unsupported padding_mode: invalid_mode"):
            ensure_preview_image_quality(str(img_path), padding_mode="invalid_mode")

    def test_draw_subtitle_border_spacing_dynamic(self, tmp_path):
        """品質向上テスト: 字幕描画において、画像サイズに基づいて輪郭線の太さ（border_width）と行間（line_spacing）が動的調整されていることを検証"""
        from PIL import Image, ImageDraw
        from backend.comprehensive_preview import _draw_subtitle_on_image

        # 4K相当の大画像 (3840x2160) を作成
        img_path_4k = tmp_path / "test_4k.png"
        Image.new("RGB", (3840, 2160), (100, 100, 100)).save(img_path_4k)

        # 描画時の border_width をキャプチャする
        captured_border_width = None
        orig_text = ImageDraw.ImageDraw.text

        def mock_text(self, xy, text, *args, **kwargs):
            nonlocal captured_border_width
            # シグネチャ不一致による TypeError を防止するため、*args, **kwargs を安全に受け取る
            stroke_width = kwargs.get("stroke_width", 0)
            if stroke_width > 0:
                captured_border_width = stroke_width
            return orig_text(self, xy, text, *args, **kwargs)

        # 直接モンキーパッチを適用して確実にキャプチャする
        ImageDraw.ImageDraw.text = mock_text
        try:
            # 字幕を2行分描画して、行間調整もトリガーする
            _draw_subtitle_on_image(str(img_path_4k), "字幕テスト1\n字幕テスト2")
        finally:
            ImageDraw.ImageDraw.text = orig_text

        # 3840 * 0.004 = 15.36 -> max(2, 8) => border_width は 8 に調整されるはず (高さは 2160 なので 2160 * 0.004 = 8.64 -> 8)
        assert captured_border_width == 8, f"Expected border_width=8 for 4K vertical resolution, got {captured_border_width}"

    def test_draw_subtitle_dynamic_border_and_opacity_blend(self, tmp_path):
        """品質向上テスト: 字幕フォントサイズに応じた border_width の調整と、背景の輝度に応じた透明度の動的な変化を検証"""
        from PIL import Image, ImageDraw
        from backend.comprehensive_preview import _draw_subtitle_on_image
        import re

        # 暗い画像 (平均輝度が低い)
        img_dark_path = tmp_path / "dark_image.png"
        img_dark = Image.new("RGB", (1280, 720), (20, 20, 20))
        img_dark.save(img_dark_path)

        # 明るい画像 (平均輝度が高い)
        img_bright_path = tmp_path / "bright_image.png"
        img_bright = Image.new("RGB", (1280, 720), (240, 240, 240))
        img_bright.save(img_bright_path)

        # 描画時の border_width と opacity_val を検証するために mock を使用
        # 実際には rounded_rectangle の呼び出し引数をキャプチャする
        captured_opacity_dark = None
        captured_opacity_bright = None

        orig_rounded = ImageDraw.ImageDraw.rounded_rectangle
        def mock_rounded_dark(self, xy, radius=0, fill=None, outline=None, width=1):
            nonlocal captured_opacity_dark
            if fill and len(fill) == 4:
                captured_opacity_dark = fill[3]
            return orig_rounded(self, xy, radius, fill, outline, width)

        def mock_rounded_bright(self, xy, radius=0, fill=None, outline=None, width=1):
            nonlocal captured_opacity_bright
            if fill and len(fill) == 4:
                captured_opacity_bright = fill[3]
            return orig_rounded(self, xy, radius, fill, outline, width)

        # 暗い画像での検証
        ImageDraw.ImageDraw.rounded_rectangle = mock_rounded_dark
        try:
            _draw_subtitle_on_image(str(img_dark_path), "暗い背景用のテスト字幕")
        finally:
            ImageDraw.ImageDraw.rounded_rectangle = orig_rounded

        # 明るい画像での検証
        ImageDraw.ImageDraw.rounded_rectangle = mock_rounded_bright
        try:
            _draw_subtitle_on_image(str(img_bright_path), "明るい背景用のテスト字幕")
        finally:
            ImageDraw.ImageDraw.rounded_rectangle = orig_rounded

        # 暗い背景では透明度を下げて (110)、明るい背景では透明度を上げて (160) 目立たせる
        assert captured_opacity_dark == 110, f"Expected dark opacity 110, got {captured_opacity_dark}"
        assert captured_opacity_bright == 160, f"Expected bright opacity 160, got {captured_opacity_bright}"

    def test_create_comprehensive_preview_ffmpeg_retry_recovery(self, tmp_path):
        """エラーハンドリングテスト: FFmpeg の抽出処理が一時的に失敗しても、リトライで正常に復旧して完遂することを検証"""
        from unittest.mock import patch, MagicMock
        import subprocess
        from pathlib import Path
        from backend.tests.test_comprehensive_preview import _import_module, _mock_overlay, _mock_grading

        mod = _import_module()
        create_comprehensive_preview = mod.create_comprehensive_preview

        call_count = 0

        def mock_subprocess_run_with_retry(cmd, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise subprocess.CalledProcessError(
                    returncode=1,
                    cmd=cmd,
                    stderr=b"Temporary file lock or I/O error"
                )
            # 3回目は成功 (モック用)
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            return mock_proc

        def mock_exists(self):
            name = str(self)
            if "input.mp4" in name or "base_10s.mp4" in name:
                return True
            return False

        with patch.object(Path, "mkdir"),              patch("subprocess.run", side_effect=mock_subprocess_run_with_retry),              patch.object(Path, "exists", mock_exists),              patch("time.sleep") as mock_sleep:

            result = create_comprehensive_preview("input.mp4", str(tmp_path))
            assert "logo_telop" in result
            assert call_count == 3
            assert mock_sleep.call_count == 2

    def test_validate_preview_image_aspect_ratio_exact_boundaries(self, tmp_path):
        """境界値テスト: アスペクト比 16:9 に対する判定境界 (誤差0.01) 付近での動作を精密に検証"""
        from PIL import Image
        from backend.comprehensive_preview import validate_preview_image, PreviewResolutionError

        # 16:9 の基準アスペクト比は 1.77777...
        # 1. 誤差 0.009 (許容内)
        # 1280x720 に対して width を調整して誤差 0.009 になる値
        # (1280 + 6) / 720 = 1286 / 720 = 1.78611... (差 0.0083) -> OK
        img_in_path = tmp_path / "boundary_in.png"
        Image.new("RGB", (1286, 720), (255, 255, 255)).save(img_in_path)
        assert validate_preview_image(str(img_in_path)) is not None

        # 2. 誤差 0.011 (許容外)
        # (1280 + 8) / 720 = 1288 / 720 = 1.78888... (差 0.0111) -> NG
        img_out_path = tmp_path / "boundary_out.png"
        Image.new("RGB", (1288, 720), (255, 255, 255)).save(img_out_path)
        with pytest.raises(PreviewResolutionError, match="Aspect ratio must be 16:9"):
            validate_preview_image(str(img_out_path))


class TestCoverageEnhancements:
    def test_parse_srt_subtitle_invalid_format(self, tmp_path):
        """_parse_srt_subtitle_for_timestamp のパース失敗や不正なSRT形式をカバー"""
        from backend.comprehensive_preview import _parse_srt_subtitle_for_timestamp
        srt_file = tmp_path / "invalid.srt"
        # 存在しないパス -> 空文字
        assert _parse_srt_subtitle_for_timestamp(srt_file, 1.0) == ""

        # 不正なブロック構造
        srt_file.write_text("1\n00:00:01,000\n", encoding="utf-8")
        assert _parse_srt_subtitle_for_timestamp(srt_file, 1.0) == ""

        # タイムスタンプが不正な形式で例外発生
        srt_file.write_text("1\n00:00:01,000 --> invalid_time\nテスト\n", encoding="utf-8")
        assert _parse_srt_subtitle_for_timestamp(srt_file, 1.0) == ""

    def test_draw_subtitle_font_load_fails(self, tmp_path, monkeypatch):
        """フォント読み込みが全て失敗した場合のデフォルトフォントフォールバック、および textsize/textbbox 例外のテスト"""
        from PIL import Image, ImageFont
        from backend.comprehensive_preview import _draw_subtitle_on_image
        
        img_path = tmp_path / "font_fail.png"
        Image.new("RGB", (1280, 720), (255, 0, 0)).save(img_path)
        
        # すべてのフォントファイルが存在しないものと見なす
        from pathlib import Path
        orig_exists = Path.exists
        def mock_exists(self):
            if ".ttc" in self.name or ".ttf" in self.name:
                return False
            return orig_exists(self)
            
        monkeypatch.setattr(Path, "exists", mock_exists)
        
        # textbbox/textsize の両方で例外を発生させる
        from PIL.ImageDraw import ImageDraw
        orig_textbbox = getattr(ImageDraw, "textbbox", None)
        orig_textsize = getattr(ImageDraw, "textsize", None)
        
        def mock_textbbox(self, *args, **kwargs):
            raise OSError("Mock Textbbox Error")
            
        def mock_textsize(self, *args, **kwargs):
            raise OSError("Mock Textsize Error")
            
        if orig_textbbox:
            monkeypatch.setattr(ImageDraw, "textbbox", mock_textbbox)
        if orig_textsize:
            monkeypatch.setattr(ImageDraw, "textsize", mock_textsize)
            
        # 座布団輝度計算の例外を発生させるために、img.crop 自体で例外を発生させる
        orig_crop = Image.Image.crop
        def mock_crop(self, *args, **kwargs):
            raise OSError("Mock Crop Error")
        monkeypatch.setattr(Image.Image, "crop", mock_crop)
            
        _draw_subtitle_on_image(str(img_path), "テスト字幕")

    def test_validate_preview_image_memory_error(self, tmp_path, monkeypatch):
        """validate_preview_image で MemoryError が発生した際の例外ハンドリング"""
        from PIL import Image
        from backend.comprehensive_preview import validate_preview_image, PreviewImageCorruptedError
        img_path = tmp_path / "mem_err.png"
        Image.new("RGB", (1280, 720)).save(img_path)
        
        def mock_transpose(self, method):
            raise MemoryError("Mock Memory Error")
            
        monkeypatch.setattr(Image.Image, "transpose", mock_transpose)
        with pytest.raises(PreviewImageCorruptedError, match="Out of memory"):
            validate_preview_image(str(img_path))

    def test_ensure_preview_image_quality_invalid_path_and_disk_space(self, tmp_path, monkeypatch):
        """ensure_preview_image_quality で無効なパス文字やディスク容量不足の動作検証"""
        from backend.comprehensive_preview import ensure_preview_image_quality
        import shutil
        
        # 1. 無効なパス文字
        with pytest.raises(OSError, match="Invalid characters in path"):
            ensure_preview_image_quality("invalid_chars_<>:\"|?*.png")
            
        # 2. ディスク容量不足
        def mock_disk_usage(path):
            # free space = 5MB (10MB未満)
            return shutil._ntuple_diskusage(100*1024*1024, 95*1024*1024, 5*1024*1024)
            
        monkeypatch.setattr(shutil, "disk_usage", mock_disk_usage)
        img_path = tmp_path / "disk_test.png"
        from PIL import Image
        Image.new("RGB", (800, 600)).save(img_path)
        
        with pytest.raises(OSError, match="Insufficient disk space"):
            ensure_preview_image_quality(str(img_path))

    def test_ensure_preview_image_quality_extreme_downscale(self, tmp_path, monkeypatch):
        """ensure_preview_image_quality で downscale_factor が適用されるルートの検証"""
        from PIL import Image
        from pathlib import Path
        from backend.comprehensive_preview import ensure_preview_image_quality
        img_path = tmp_path / "extreme_downscale.png"
        Image.new("RGB", (2000, 1500), (0, 0, 0)).save(img_path)
        
        call_count = 0
        class MockStat:
            def __init__(self, size):
                self.st_size = size
                
        orig_stat = Path.stat
        def mock_stat_forcing_downscale(self, *args, **kwargs):
            nonlocal call_count
            if "extreme_downscale" in str(self) and ".tmp" in str(self):
                call_count += 1
                # 6回目（downscale_factor 0.75 での保存）で 4MB 未満にする
                if call_count <= 5:
                    return MockStat(5 * 1024 * 1024)
                else:
                    return MockStat(3 * 1024 * 1024)
            return orig_stat(self, *args, **kwargs)
            
        monkeypatch.setattr(Path, "stat", mock_stat_forcing_downscale)
        res_path = ensure_preview_image_quality(str(img_path))
        assert Path(res_path).exists()

    def test_ensure_preview_image_quality_exif_transpose(self, tmp_path):
        """品質向上テスト: EXIFのOrientationタグ（向き情報）を持つ画像が正しく自動回転補正（exif_transpose）されることを検証"""
        from PIL import Image
        from backend.comprehensive_preview import ensure_preview_image_quality, validate_preview_image
        
        # 縦長 (600x800) のテスト用画像を作成
        img = Image.new("RGB", (600, 800), (255, 0, 0))
        exif = img.getexif()
        # EXIFの Orientationタグ(274) に 6 (時計回りに90度回転) を設定
        exif[274] = 6
        
        img_path = tmp_path / "exif_orient_test.jpg"
        img.save(img_path, "JPEG", exif=exif)
        
        # ensure_preview_image_quality を適用
        res_path = ensure_preview_image_quality(str(img_path))
        
        # 補正後の画像を検証
        result = validate_preview_image(res_path)
        assert result["width"] == 1280
        assert result["height"] == 720

    def test_draw_subtitle_loop_counter_safety(self, tmp_path):
        """品質向上テスト: 字幕描画のフォントサイズ自動縮小ループが安全カウンタで無限ループを防ぐことの検証"""
        from PIL import Image
        from backend.comprehensive_preview import _draw_subtitle_on_image
        
        img_path = tmp_path / "loop_safety.png"
        Image.new("RGB", (1280, 720), (100, 100, 100)).save(img_path)
        
        # 非常に長いテキストを渡し、フォントサイズフィッティングが安全カウンタで停止することを確認する
        long_subtitle = "あ" * 1000
        # 実行してハングしないことを確認
        _draw_subtitle_on_image(str(img_path), long_subtitle)
        assert Path(img_path).exists()

    def test_validate_preview_image_corrupted_icc_profile_raising_error(self, tmp_path):
        """エラーハンドリングテスト: 破損したICCプロファイルを持つ画像を検証した際、PreviewImageCorruptedError が発生することの検証"""
        from PIL import Image
        from backend.comprehensive_preview import validate_preview_image, PreviewImageCorruptedError
        
        img_path = tmp_path / "corrupted_icc.png"
        img = Image.new("RGB", (1280, 720), (255, 255, 255))
        # 不正な短いICCプロファイルデータを渡す
        img.save(img_path, "PNG", icc_profile=b"invalid_icc_data_too_short")
        
        with pytest.raises(PreviewImageCorruptedError, match="Corrupted ICC profile"):
            validate_preview_image(str(img_path))

    def test_draw_subtitle_text_measurement_exceptions(self, tmp_path, monkeypatch):
        """例外ハンドリングテスト: テキストの幅・高さ測定時に AttributeError や TypeError などの例外が発生した場合に、
        安全に近似フォールバックロジックが適用されることを検証"""
        from PIL import Image
        from backend.comprehensive_preview import _draw_subtitle_on_image
        
        img_path = tmp_path / "text_measure_err.png"
        Image.new("RGB", (1280, 720), (128, 128, 128)).save(img_path)
        
        # textbbox と textsize に属性が存在しない、あるいは呼び出しで TypeError を発生させる
        from PIL.ImageDraw import ImageDraw
        def mock_textbbox(self, *args, **kwargs):
            raise TypeError("Mocked textbbox TypeError")
            
        def mock_textsize(self, *args, **kwargs):
            raise TypeError("Mocked textsize TypeError")
            
        monkeypatch.setattr(ImageDraw, "textbbox", mock_textbbox, raising=False)
        monkeypatch.setattr(ImageDraw, "textsize", mock_textsize, raising=False)
        
        # 実行して例外をスローせず、処理が正常に完了することを確認
        _draw_subtitle_on_image(str(img_path), "テスト字幕例外フォールバック")
        assert img_path.exists()

    def test_draw_subtitle_brightness_calculation_exceptions(self, tmp_path, monkeypatch):
        """例外ハンドリングテスト: 平均輝度計算処理において PIL.ImageStat の読み込み等で例外が発生した場合に、
        デフォルト値（128）を使って安全に処理が完了することを検証"""
        from PIL import Image
        from backend.comprehensive_preview import _draw_subtitle_on_image
        
        img_path = tmp_path / "brightness_calc_err.png"
        Image.new("RGB", (1280, 720), (128, 128, 128)).save(img_path)
        
        # PIL.ImageStat のインポート時に例外を誘発させるため、sys.modules を差し替えるか、ImageStat モジュール内の Stat クラスで例外を発生させる
        import sys
        from unittest.mock import MagicMock
        
        # ImageStat.Stat が呼ばれたときに AttributeError を発生させる
        import PIL.ImageStat
        def mock_stat_init(*args, **kwargs):
            raise AttributeError("Mocked ImageStat AttributeError")
            
        monkeypatch.setattr(PIL.ImageStat, "Stat", mock_stat_init)
        
        # 実行して例外をスローせず、処理が正常に完了することを確認
        _draw_subtitle_on_image(str(img_path), "テスト字幕例外フォールバック２")
        assert img_path.exists()

    def test_parse_srt_subtitle_for_timestamp_value_error(self, tmp_path):
        """例外ハンドリングテスト: SRTファイルが壊れており、時間のパース中に ValueError が発生した場合に安全に空文字を返すことを検証"""
        from backend.comprehensive_preview import _parse_srt_subtitle_for_timestamp
        
        # 時間フォーマットが壊れているSRTファイルを作成
        srt_path = tmp_path / "broken.srt"
        srt_path.write_text("1\n00:00:0X,000 --> 00:00:05,000\nテスト字幕\n", encoding="utf-8")
        
        # 例外をスローせず、安全に空文字が返ることを確認
        res = _parse_srt_subtitle_for_timestamp(srt_path, 2.0)
        assert res == ""

    def test_parse_srt_subtitle_for_timestamp_index_error(self, tmp_path):
        """例外ハンドリングテスト: SRTファイルが壊れており、時間のパース中に IndexError が発生した場合に安全に空文字を返すことを検証"""
        from backend.comprehensive_preview import _parse_srt_subtitle_for_timestamp
        
        # 時間フォーマットが足りない（コロンがない）SRTファイルを作成
        srt_path = tmp_path / "broken_index.srt"
        srt_path.write_text("1\n00:00 --> 00:05\nテスト字幕\n", encoding="utf-8")
        
        # 例外をスローせず、安全に空文字が返ることを確認
        res = _parse_srt_subtitle_for_timestamp(srt_path, 2.0)
        assert res == ""

    async def test_resolve_comprehensive_preview_task_specific_exception_wrapping(self):
        """resolve_comprehensive_preview_task で具体的な例外が発生した際のラッピング検証"""
        from backend.comprehensive_preview import resolve_comprehensive_preview_task, PreviewGenerationError
        
        class DummyAgent:
            pass
            
        agent = DummyAgent()
        agent.input_video = "dummy_nonexistent_video.mp4"
        agent.output_dir = "dummy_out"
        agent.timestamps = [1.0]

        with patch("backend.comprehensive_preview.create_comprehensive_preview", side_effect=ValueError("Invalid args")):
            with pytest.raises(PreviewGenerationError, match="Task execution failed: Invalid args"):
                await resolve_comprehensive_preview_task(agent, "task_fail_spec")

    def test_draw_subtitle_on_image_specific_exception_wrapping(self, tmp_path):
        """_draw_subtitle_on_image で具体的な例外が発生した際に PreviewGenerationError にラップされるか検証"""
        from backend.comprehensive_preview import _draw_subtitle_on_image, PreviewGenerationError
        img_path = tmp_path / "spec_fail.png"
        from PIL import Image
        img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
        img.save(img_path)
        
        # OSエラーをシミュレート
        with patch("PIL.Image.open", side_effect=OSError("Disk read error")):
            with pytest.raises(PreviewGenerationError, match="Failed to draw subtitle on image: Disk read error"):
                _draw_subtitle_on_image(str(img_path), "例外テスト")



    def test_validate_preview_image_non_rgb_modes(self, tmp_path):
        """例外・境界テスト: 画像モードが RGB 以外の（L や RGBA などの）場合における validate_preview_image の動作検証"""
        from PIL import Image
        from backend.comprehensive_preview import validate_preview_image
        
        # L モード (グレースケール) の 1280x720 画像
        img_path_l = tmp_path / "gray_scale.png"
        Image.new("L", (1280, 720), 128).save(img_path_l)
        res_l = validate_preview_image(str(img_path_l))
        assert res_l["width"] == 1280
        assert res_l["height"] == 720
        
        # RGBA モードの 1280x720 画像
        img_path_rgba = tmp_path / "rgba_image.png"
        Image.new("RGBA", (1280, 720), (100, 150, 200, 255)).save(img_path_rgba)
        res_rgba = validate_preview_image(str(img_path_rgba))
        assert res_rgba["width"] == 1280
        assert res_rgba["height"] == 720

    def test_ensure_preview_image_quality_enhancement_logic(self, tmp_path):
        """最適化テスト: ImageChops/ImageStat に置き換えたコントラスト・色彩・彩度補正が正常動作することの確認"""
        from PIL import Image
        from backend.comprehensive_preview import ensure_preview_image_quality, validate_preview_image
        
        # コントラストが非常に低い（平坦な単一色に近い）800x600 画像を用意（ただし単一色チェックをすり抜けるために微小な変化を付ける）
        img_path = tmp_path / "low_contrast.png"
        img = Image.new("RGB", (800, 600), (100, 100, 100))
        px = img.load()
        px[0, 0] = (101, 101, 101) # 単一色回避
        img.save(img_path)
        
        res_path = ensure_preview_image_quality(str(img_path))
        result = validate_preview_image(res_path)
        
        assert result["width"] == 1280
        assert result["height"] == 720
        assert Path(res_path).exists()

    def test_create_comprehensive_preview_ffmpeg_os_error_retry(self, tmp_path):
        """例外ハンドリングテスト: ffmpeg呼び出し時に OSError が発生した場合にリトライループが走り、最終的に例外が投げられることの検証"""
        import sys
        from unittest.mock import patch
        from backend.tests.test_comprehensive_preview import _import_module
        
        mod = _import_module()
        
        def mock_exists(self):
            if "input.mp4" in str(self):
                return True
            return False

        # subprocess.run が OSError を投げるようにモックする
        call_count = 0
        def mock_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise OSError("ffmpeg execution failed (OS error)")

        with patch.object(Path, "mkdir"),              patch.object(Path, "exists", mock_exists),              patch("subprocess.run", side_effect=mock_run),              patch("time.sleep") as mock_sleep:
             
             with pytest.raises(mod.PreviewGenerationError, match="ffmpeg execution failed"):
                 mod.create_comprehensive_preview("input.mp4", str(tmp_path))
                 
             # 3回リトライしたことを確認
             assert call_count == 3
             assert mock_sleep.call_count == 2

class TestEnhancedErrorHandling:

    def test_parse_srt_with_partially_corrupted_blocks(self, tmp_path):
        """正常系（堅牢性）: 一部の字幕ブロックの形式が崩れていても、正常なブロックはパースできること"""
        mod = _import_module()
        from unittest.mock import patch, mock_open

        # 2つ目のブロックでタイムスタンプのコロンが足りない壊れたブロック、3つ目は正常なブロック
        corrupted_subtitle_content = (
            "1\n00:00:01,000 --> 00:00:03,000\n正常な字幕1\n\n"
            "2\n00:00:04,000 --> 00:0405,000\n壊れた字幕\n\n"
            "3\n00:00:06,000 --> 00:00:08,000\n正常な字幕2\n"
        )

        def mock_exists(self):
            name = str(self)
            if "input.mp4" in name or "whisper_semantic.srt" in name:
                return True
            return False

        with patch.object(Path, "mkdir"), \
             patch("subprocess.run"), \
             patch.object(Path, "exists", mock_exists), \
             patch.object(Path, "read_text", return_value=corrupted_subtitle_content):

            # 正常な字幕1のタイムスタンプ(2.0秒)でのパース結果を検証
            res1 = mod._parse_srt_subtitle_for_timestamp(Path("whisper_semantic.srt"), 2.0)
            assert res1 == "正常な字幕1"

            # 壊れた字幕のタイムスタンプ(5.0秒)でのパース結果は空（例外ログ出力されるがエラーにはならない）
            res2 = mod._parse_srt_subtitle_for_timestamp(Path("whisper_semantic.srt"), 5.0)
            assert res2 == ""

            # 正常な字幕2のタイムスタンプ(7.0秒)でのパース結果が正しく取得できること（後続処理が壊れていない）
            res3 = mod._parse_srt_subtitle_for_timestamp(Path("whisper_semantic.srt"), 7.0)
            assert res3 == "正常な字幕2"

    def test_create_preview_cleanup_on_unexpected_exception(self, tmp_path):
        """異常系（リソース解放保証）: 想定外の例外が発生した場合でも、作成中だった一時ファイルがクリーンアップされること"""
        mod = _import_module()
        from unittest.mock import patch
        import pytest

        # 一時ファイルが作成された状態をモックするため、created_filesに格納される想定のファイルを用意
        temp_dir = tmp_path / "comprehensive_preview"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_video = temp_dir / "base_10s.mp4"
        temp_video.touch()

        # create_comprehensive_previewの途中で意図的に想定外の例外(ZeroDivisionError)を発生させるため、
        # CombinedOverlayのapply_brand_overlayで例外をスローさせる
        from backend.tests.test_comprehensive_preview import _mock_overlay
        _mock_overlay.apply_brand_overlay.side_effect = ZeroDivisionError("Simulated unexpected error")

        def mock_exists(self):
            name = str(self)
            if "input.mp4" in name:
                return True
            # モックされた一時ファイルが存在することを示す
            if "base_10s.mp4" in name:
                return True
            return False

        # 一時ファイル削除のためのフックを検証
        with patch.object(Path, "exists", mock_exists), \
             patch("subprocess.run"), \
             patch("combined_overlay.CombinedOverlay", return_value=_mock_overlay):
            
            with pytest.raises(ZeroDivisionError, match="Simulated unexpected error"):
                mod.create_comprehensive_preview("input.mp4", str(temp_dir))

        # 元に戻す
        _mock_overlay.apply_brand_overlay.side_effect = None
