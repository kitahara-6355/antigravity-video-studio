import pytest
import sys
import runpy
from unittest.mock import MagicMock, patch
from pathlib import Path
from PIL import Image, ImageFont

# backendディレクトリをインポート可能にする
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import backend.add_simple_branding as add_simple_branding

def test_create_combined_branding_success():
    # 正常系のテスト
    mock_logo = Image.new('RGBA', (23, 45), (255, 0, 0, 255))
    
    with patch('PIL.Image.open', return_value=mock_logo) as mock_open_img, \
         patch('PIL.ImageFont.truetype') as mock_truetype, \
         patch('PIL.Image.Image.save') as mock_save:
        
        mock_font = MagicMock()
        mock_truetype.return_value = mock_font
        
        with patch('PIL.ImageDraw.Draw') as mock_draw_cls:
            mock_draw = MagicMock()
            mock_draw.textbbox.return_value = (0, 0, 100, 20)
            mock_draw_cls.return_value = mock_draw
            
            res = add_simple_branding.create_combined_branding()
            
            assert res == Path(r"C:\Users\PC_User\Desktop\script\video-automation") / "backend" / "branding" / "final_branding.png"
            mock_open_img.assert_called_once()
            mock_save.assert_called_once()
            mock_draw.text.assert_called_once()

def test_create_combined_branding_font_fallback():
    mock_logo = Image.new('RGBA', (23, 45), (255, 0, 0, 255))
    
    with patch('PIL.Image.open', return_value=mock_logo), \
         patch('PIL.ImageFont.truetype', side_effect=Exception("Font not found")), \
         patch('PIL.ImageFont.load_default') as mock_load_default, \
         patch('PIL.Image.Image.save'), \
         patch('PIL.ImageDraw.Draw') as mock_draw_cls:
        
        mock_draw = MagicMock()
        mock_draw.textbbox.return_value = (0, 0, 100, 20)
        mock_draw_cls.return_value = mock_draw
        
        add_simple_branding.create_combined_branding()
        mock_load_default.assert_called_once()

def test_add_branding_to_video_success():
    with patch('backend.add_simple_branding.create_combined_branding', return_value=Path("dummy_branding.png")), \
         patch('subprocess.run') as mock_run, \
         patch('pathlib.Path.exists', return_value=True), \
         patch('pathlib.Path.stat') as mock_stat:
        
        ffmpeg_res = MagicMock()
        ffmpeg_res.returncode = 0
        
        ffprobe_res = MagicMock()
        ffprobe_res.returncode = 0
        ffprobe_res.stdout = "120.5\n"
        
        mock_run.side_effect = [ffmpeg_res, ffprobe_res]
        mock_stat.return_value.st_size = 1024 * 1024 * 5
        
        res = add_simple_branding.add_branding_to_video()
        
        expected_output = Path(r"C:\Users\PC_User\Desktop\script\video-automation") / "soul_narrative_YOUTUBE_READY.mp4"
        assert res == str(expected_output)
        assert mock_run.call_count == 2
        
        # Verify ffmpeg arguments
        ffmpeg_args = mock_run.call_args_list[0][0][0]
        assert "ffmpeg" in ffmpeg_args
        assert "-preset" in ffmpeg_args
        assert "veryfast" in ffmpeg_args
        assert any("overlay=15:15" in arg for arg in ffmpeg_args)
        
        # Verify ffprobe arguments
        ffprobe_args = mock_run.call_args_list[1][0][0]
        assert "ffprobe" in ffprobe_args
        assert "format=duration" in ffprobe_args

def test_add_branding_to_video_ffmpeg_failure():
    with patch('backend.add_simple_branding.create_combined_branding', return_value=Path("dummy_branding.png")), \
         patch('subprocess.run') as mock_run, \
         patch('pathlib.Path.exists', return_value=True):
        
        ffmpeg_res = MagicMock()
        ffmpeg_res.returncode = 1
        ffmpeg_res.stderr = "FFmpeg failed error"
        
        mock_run.return_value = ffmpeg_res
        
        res = add_simple_branding.add_branding_to_video()
        assert res is None
        assert mock_run.call_count == 1
        
        # Verify ffmpeg was called
        ffmpeg_args = mock_run.call_args_list[0][0][0]
        assert "ffmpeg" in ffmpeg_args

def test_add_branding_to_video_output_missing():
    with patch('backend.add_simple_branding.create_combined_branding', return_value=Path("dummy_branding.png")), \
         patch('subprocess.run') as mock_run, \
         patch('pathlib.Path.exists') as mock_exists:
        mock_exists.side_effect = [True, False]
        
        ffmpeg_res = MagicMock()
        ffmpeg_res.returncode = 0
        
        mock_run.return_value = ffmpeg_res
        
        res = add_simple_branding.add_branding_to_video()
        assert res is None
        assert mock_run.call_count == 1
        
        # Verify ffmpeg was called
        ffmpeg_args = mock_run.call_args_list[0][0][0]
        assert "ffmpeg" in ffmpeg_args

def test_main_execution():
    mock_logo = Image.new('RGBA', (23, 45), (255, 0, 0, 255))
    
    with patch('PIL.Image.open', return_value=mock_logo), \
         patch('PIL.ImageFont.truetype'), \
         patch('PIL.Image.Image.save'), \
         patch('PIL.ImageDraw.Draw') as mock_draw_cls, \
         patch('subprocess.run') as mock_run, \
         patch('pathlib.Path.exists', return_value=True), \
         patch('pathlib.Path.stat') as mock_stat:
        
        mock_draw = MagicMock()
        mock_draw.textbbox.return_value = (0, 0, 100, 20)
        mock_draw_cls.return_value = mock_draw
        
        ffmpeg_res = MagicMock()
        ffmpeg_res.returncode = 0
        
        ffprobe_res = MagicMock()
        ffprobe_res.returncode = 0
        ffprobe_res.stdout = "120.5\n"
        
        mock_run.side_effect = [ffmpeg_res, ffprobe_res]
        mock_stat.return_value.st_size = 1024 * 1024 * 5
        
        sys.modules['add_simple_branding'] = MagicMock()
        if 'add_simple_branding' in sys.modules:
            del sys.modules['add_simple_branding']
            
        runpy.run_module('add_simple_branding', run_name='__main__')

def test_main_execution_failure():
    mock_logo = Image.new('RGBA', (23, 45), (255, 0, 0, 255))
    
    with patch('PIL.Image.open', return_value=mock_logo), \
         patch('PIL.ImageFont.truetype'), \
         patch('PIL.Image.Image.save'), \
         patch('PIL.ImageDraw.Draw') as mock_draw_cls, \
         patch('subprocess.run') as mock_run, \
         patch('pathlib.Path.exists', return_value=True), \
         patch('pathlib.Path.stat') as mock_stat:
        
        mock_draw = MagicMock()
        mock_draw.textbbox.return_value = (0, 0, 100, 20)
        mock_draw_cls.return_value = mock_draw
        
        ffmpeg_res = MagicMock()
        ffmpeg_res.returncode = 1
        ffmpeg_res.stderr = "FFmpeg error"
        
        mock_run.return_value = ffmpeg_res
        mock_stat.return_value.st_size = 1024 * 1024 * 5
        
        sys.modules['add_simple_branding'] = MagicMock()
        if 'add_simple_branding' in sys.modules:
            del sys.modules['add_simple_branding']
            
        runpy.run_module('add_simple_branding', run_name='__main__')

def test_add_branding_to_video_ffprobe_invalid_output():
    with patch('backend.add_simple_branding.create_combined_branding', return_value=Path("dummy_branding.png")), \
         patch('subprocess.run') as mock_run, \
         patch('pathlib.Path.exists', return_value=True), \
         patch('pathlib.Path.stat') as mock_stat:
        
        ffmpeg_res = MagicMock()
        ffmpeg_res.returncode = 0
        
        ffprobe_res = MagicMock()
        ffprobe_res.returncode = 0
        ffprobe_res.stdout = "not_a_float\n"
        
        mock_run.side_effect = [ffmpeg_res, ffprobe_res]
        mock_stat.return_value.st_size = 1024 * 1024 * 5
        
        with pytest.raises(ValueError):
            add_simple_branding.add_branding_to_video()
            
        assert mock_run.call_count == 2
        assert "ffmpeg" in mock_run.call_args_list[0][0][0]
        assert "ffprobe" in mock_run.call_args_list[1][0][0]

def test_create_combined_branding_save_failure():
    mock_logo = Image.new('RGBA', (23, 45), (255, 0, 0, 255))
    
    with patch('PIL.Image.open', return_value=mock_logo), \
         patch('PIL.ImageFont.truetype'), \
         patch('PIL.Image.Image.save', side_effect=OSError("Save failed")), \
         patch('PIL.ImageDraw.Draw') as mock_draw_cls:
        
        mock_draw = MagicMock()
        mock_draw.textbbox.return_value = (0, 0, 100, 20)
        mock_draw_cls.return_value = mock_draw
        
        with pytest.raises(OSError):
            add_simple_branding.create_combined_branding()

def test_add_branding_to_video_ffprobe_process_failure():
    with patch('backend.add_simple_branding.create_combined_branding', return_value=Path("dummy_branding.png")), \
         patch('subprocess.run') as mock_run, \
         patch('pathlib.Path.exists', return_value=True), \
         patch('pathlib.Path.stat') as mock_stat:
        
        ffmpeg_res = MagicMock()
        ffmpeg_res.returncode = 0
        
        ffprobe_res = MagicMock()
        ffprobe_res.returncode = 1
        ffprobe_res.stdout = ""
        
        mock_run.side_effect = [ffmpeg_res, ffprobe_res]
        mock_stat.return_value.st_size = 1024 * 1024 * 5
        
        with pytest.raises(ValueError):
            add_simple_branding.add_branding_to_video()
            
        assert mock_run.call_count == 2
        assert "ffmpeg" in mock_run.call_args_list[0][0][0]
        assert "ffprobe" in mock_run.call_args_list[1][0][0]

def test_branding_dimensions_aspect_ratio_and_size():
    import tempfile
    from PIL import Image
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_base = Path(tmpdir)
        logo_dir = tmp_base / "backend" / "branding" / "logos"
        logo_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. 正常系：ロゴ画像が存在する場合
        logo_path = logo_dir / "brand_logo.png"
        dummy_logo = Image.new('RGBA', (23, 45), (255, 0, 0, 255))
        dummy_logo.save(logo_path)
        
        # ブランディング画像を作成 (高さ45px)
        output_path = add_simple_branding.create_combined_branding(target_height=45, base_path=tmp_base)
        
        assert output_path.exists()
        # ファイルサイズの検証（0バイト超、かつ1MB未満）
        size = output_path.stat().st_size
        assert size > 0
        assert size < 1024 * 1024
        
        # 解像度とアスペクト比を検証
        with Image.open(output_path) as img:
            width, height = img.size
            assert height == 45
            assert width == 331
            aspect_ratio = width / height
            assert abs(aspect_ratio - (331 / 45)) < 0.01

        # 2. スケーリングの検証 (高さ90px)
        output_path_90 = add_simple_branding.create_combined_branding(target_height=90, base_path=tmp_base)
        with Image.open(output_path_90) as img:
            width, height = img.size
            assert height == 90
            assert width == 662
            aspect_ratio = width / height
            assert abs(aspect_ratio - (331 / 45)) < 0.01

        # 3. ロゴ画像が存在しない場合のエラーハンドリング（プレースホルダーによるフォールバック）
        logo_path.unlink()
        
        output_path_fallback = add_simple_branding.create_combined_branding(target_height=45, base_path=tmp_base)
        assert output_path_fallback.exists()
        with Image.open(output_path_fallback) as img:
            width, height = img.size
            assert height == 45
            assert width == 331

def test_simple_branding_thumbnail_quality_and_validation():
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "thumbnail.png"
        
        # 正常な解像度で生成
        add_simple_branding.generate_simple_branding_thumbnail(out_path, width=1280, height=720, text="Test Branding")
        
        assert out_path.exists()
        
        # バリデーション関数のテスト
        result = add_simple_branding.validate_thumbnail(out_path)
        assert result["width"] == 1280
        assert result["height"] == 720
        assert result["size_bytes"] < 4 * 1024 * 1024
        
        # アスペクト比の確認
        aspect_ratio = result["width"] / result["height"]
        assert abs(aspect_ratio - (16/9)) < 0.01

def test_simple_branding_thumbnail_invalid_resolution():
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "invalid_thumbnail.png"
        
        # 不正な解像度で生成 (800x600) 時に早期に ValueError がスローされることを確認
        with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
            add_simple_branding.generate_simple_branding_thumbnail(out_path, width=800, height=600, text="Invalid Res")

def test_simple_branding_thumbnail_invalid_aspect_ratio():
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "invalid_aspect.png"
        
        # 16:9 ではない解像度で生成 (1280x1000) 時に早期に ValueError がスローされることを確認
        with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
            add_simple_branding.generate_simple_branding_thumbnail(out_path, width=1280, height=1000, text="Invalid Aspect")

@pytest.mark.asyncio
async def test_resolve_branding_task_with_stage_bound_agent():
    from agents.stage_bound_agent import StageBoundAgent
    import json
    import tempfile
    import asyncio
    import time
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = str(Path(tmpdir) / "test_tasks.db")
        
        # StageBoundAgentをインスタンス化
        agent = StageBoundAgent(stage_name="simple_branding", db_path=db_file)
        
        # add_simple_branding.OUTPUT_DIR を一時ディレクトリに向ける
        original_output_dir = add_simple_branding.OUTPUT_DIR
        add_simple_branding.OUTPUT_DIR = tmpdir
        
        try:
            # タスクを READY 状態にする
            task_id = "test-task-123"
            await agent.register_task(task_id, initial_status="READY", max_retries=1)
            
            # エージェントを開始し、resolve_branding_task をバインド
            async def process_func(tid):
                return await add_simple_branding.resolve_branding_task(agent, tid)
            await agent.start(process_func)
            
            # タスクの完了を待機
            timeout = 30.0
            start_time = time.time()
            completed = False
            while time.time() - start_time < timeout:
                status = await agent.get_task_status(task_id)
                if status == "COMPLETED":
                    completed = True
                    break
                await asyncio.sleep(0.1)

            await agent.stop()
            assert completed
            
            # 結果の確認
            conn = agent._get_conn()
            try:
                row = conn.execute("SELECT result FROM tasks WHERE id = ?", (task_id,)).fetchone()
                assert row is not None
                result_data = json.loads(row[0])
                assert result_data["width"] == 1280
                assert result_data["height"] == 720
                assert Path(result_data["path"]).exists()
            finally:
                agent._close_conn(conn)
                
        finally:
            add_simple_branding.OUTPUT_DIR = original_output_dir


def test_thumbnail_rigorous_quality_and_agent_integration():
    import tempfile
    from PIL import Image
    from agents.stage_bound_agent import StageBoundAgent
    import json
    import asyncio
    import time

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "rigorous_thumbnail.png"
        
        # 1. 画像の生成
        add_simple_branding.generate_simple_branding_thumbnail(
            out_path, width=1920, height=1080, text="品質検証テスト\n第2世代高品質グラデーション\n解像度 1920x1080"
        )
        
        # 2. 存在確認
        assert out_path.exists()
        
        # 3. ファイルサイズ検証 (4MB 未満であること)
        size_bytes = out_path.stat().st_size
        assert size_bytes < 4 * 1024 * 1024
        assert size_bytes > 0
        
        # 4. 画像破損の検証 (Pillow等で正常にロード可能、ピクセル読み出し可能であること)
        try:
            with Image.open(out_path) as img:
                img.verify()
            with Image.open(out_path) as img:
                img.load()
                w, h = img.size
                # 5. 解像度が 1280x720 以上であること
                assert w >= 1280
                assert h >= 720
                # 6. アスペクト比が 16:9 であること
                aspect_ratio = w / h
                assert abs(aspect_ratio - (16/9)) < 0.01
        except Exception as e:
            pytest.fail(f"Image load verification failed: {e}")

        # 7. StageBoundAgent 連携 (自動リトライ、結果保存、マイグレーション機能の統合検証)
        db_file = str(Path(tmpdir) / "rigorous_tasks.db")
        agent = StageBoundAgent(stage_name="rigorous_branding", db_path=db_file)
        
        original_output_dir = add_simple_branding.OUTPUT_DIR
        add_simple_branding.OUTPUT_DIR = tmpdir
        
        try:
            task_id = "rigorous-task-456"
            
            async def run_agent_test():
                # タスク登録
                await agent.register_task(task_id, initial_status="READY", max_retries=2)
                # エージェントの起動とタスク処理の実行
                async def process_func(tid):
                    return await add_simple_branding.resolve_branding_task(agent, tid)
                await agent.start(process_func)
                
                # タスクが完了するまで待機
                timeout = 30.0
                start_time = time.time()
                completed = False
                while time.time() - start_time < timeout:
                    status = await agent.get_task_status(task_id)
                    if status == "COMPLETED":
                        completed = True
                        break
                    await asyncio.sleep(0.1)
                
                await agent.stop()
                return completed
                
            completed = asyncio.run(run_agent_test())
            assert completed, "StageBoundAgent integration task did not complete in time"
            
            # DBから結果を取り出して保存されたデータの検証
            conn = agent._get_conn()
            try:
                row = conn.execute("SELECT result, status FROM tasks WHERE id = ?", (task_id,)).fetchone()
                assert row is not None
                result_data = json.loads(row[0])
                assert row[1] == "COMPLETED"
                # DBマイグレーションや結果保存が正常であることの検証
                assert result_data["width"] == 1280
                assert result_data["height"] == 720
                assert Path(result_data["path"]).exists()
            finally:
                agent._close_conn(conn)
        finally:
            add_simple_branding.OUTPUT_DIR = original_output_dir


def test_thumbnail_preview_generation():
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "thumbnail.png"
        preview_path = Path(tmpdir) / "thumbnail_preview.png"
        
        # 正常生成
        add_simple_branding.generate_simple_branding_thumbnail(
            out_path, width=1920, height=1080, text="高品質サムネイル", preview_path=preview_path
        )
        
        assert out_path.exists()
        assert preview_path.exists()
        
        # 検証
        res_main = add_simple_branding.validate_thumbnail(out_path, is_preview=False)
        assert res_main["width"] == 1920
        assert res_main["height"] == 1080
        
        res_preview = add_simple_branding.validate_thumbnail(preview_path, is_preview=True)
        assert res_preview["width"] == 640
        assert res_preview["height"] == 360
        assert res_preview["size_bytes"] < res_main["size_bytes"]

def test_thumbnail_text_auto_wrapping_and_scaling():
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "wrapped_thumbnail.png"
        
        # 非常に長いテキスト（通常であれば幅や高さからはみ出る量）
        long_text = "これは非常に長いテキストです。" * 20
        
        # スケーリングと折り返しにより、エラーを出さずに生成できること
        add_simple_branding.generate_simple_branding_thumbnail(
            out_path, width=1280, height=720, text=long_text
        )
        
        assert out_path.exists()
        res = add_simple_branding.validate_thumbnail(out_path)
        assert res["width"] == 1280

def test_thumbnail_corrupted_image_detection():
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        corrupted_path = Path(tmpdir) / "corrupted.png"
        
        # 破損ファイル (0バイトまたはランダムなバイト)
        corrupted_path.write_bytes(b"not a valid png image data at all")
        
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            add_simple_branding.validate_thumbnail(corrupted_path)
            
        # 0バイトファイル
        empty_path = Path(tmpdir) / "empty.png"
        empty_path.write_bytes(b"")
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            add_simple_branding.validate_thumbnail(empty_path)

def test_thumbnail_rigorous_size_under_limit():
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "size_test.png"
        
        # 非常に大きなテキストを描画
        add_simple_branding.generate_simple_branding_thumbnail(
            out_path, width=1920, height=1080, text="Size Test\n" * 10
        )
        
        assert out_path.exists()
        res = add_simple_branding.validate_thumbnail(out_path)
        
        # ファイルサイズが4MBの制限を遥かに下回る（Pillow標準の圧縮が効いていること）
        assert res["size_bytes"] < 4 * 1024 * 1024  # 4MB未満


# --- 追加された堅牢性およびカバレッジ向上テスト ---

def test_invalid_inputs_for_thumbnail_generation():
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "invalid_input.png"
        
        # 1. width/heightが非整数の場合
        with pytest.raises(ValueError, match="Width and height must be integers"):
            add_simple_branding.generate_simple_branding_thumbnail(out_path, width="abc", height=720)
            
        # 2. width/heightが0以下の場合
        with pytest.raises(ValueError, match="Width and height must be positive integers"):
            add_simple_branding.generate_simple_branding_thumbnail(out_path, width=-100, height=720)
            
        # 3. テキストが None/空文字列 の場合にデフォルト値が設定されることの検証
        add_simple_branding.generate_simple_branding_thumbnail(out_path, width=1280, height=720, text=None)
        assert out_path.exists()
        res = add_simple_branding.validate_thumbnail(out_path)
        assert res["width"] == 1280

def test_thumbnail_rigorous_size_validation_errors():
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "val_error.png"
        
        # サムネイルの正常生成
        add_simple_branding.generate_simple_branding_thumbnail(out_path, width=1280, height=720)
        
        # 1. 4MBを超える場合の例外検証
        with patch('pathlib.Path.stat') as mock_stat:
            mock_stat.return_value.st_size = 5 * 1024 * 1024  # 5MB
            with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
                add_simple_branding.validate_thumbnail(out_path)
                
        # 2. メイン画像解像度が1280x720未満の場合の例外検証
        small_path = Path(tmpdir) / "small.png"
        # 直接解像度の低い画像を作成
        img_small = Image.new("RGB", (640, 360))
        img_small.save(small_path)
        with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
            add_simple_branding.validate_thumbnail(small_path, is_preview=False)
            
        # 3. プレビュー画像解像度が320x180未満の場合の例外検証
        tiny_path = Path(tmpdir) / "tiny.png"
        img_tiny = Image.new("RGB", (300, 150))
        img_tiny.save(tiny_path)
        with pytest.raises(ValueError, match="Preview resolution must be at least 320x180"):
            add_simple_branding.validate_thumbnail(tiny_path, is_preview=True)
            
        # 4. アスペクト比が 16:9 でない場合の例外検証
        square_path = Path(tmpdir) / "square.png"
        img_square = Image.new("RGB", (1280, 1280))
        img_square.save(square_path)
        with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
            add_simple_branding.validate_thumbnail(square_path)

def test_add_branding_to_video_no_input():
    with patch('pathlib.Path.exists', return_value=False):
        res = add_simple_branding.add_branding_to_video()
        assert res is None

def test_generate_thumbnail_with_no_resampling():
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "no_resample.png"
        preview_path = Path(tmpdir) / "no_resample_preview.png"
        
        # LANCZOS を一時的に None にしてフォールバック処理を強制
        original_lanczos = add_simple_branding.LANCZOS
        add_simple_branding.LANCZOS = None
        try:
            add_simple_branding.generate_simple_branding_thumbnail(
                out_path, width=1280, height=720, text="No Resampling Test", preview_path=preview_path
            )
            assert out_path.exists()
            assert preview_path.exists()
        finally:
            add_simple_branding.LANCZOS = original_lanczos

def test_mkdir_error_handling():
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        # 事前にディレクトリを作成しておくことで、mkdirが例外を出してもsaveは成功するようにする
        out_dir = Path(tmpdir) / "mkdir_err"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "thumbnail.png"
        
        # Path.mkdir が TypeError をスローする場合
        with patch('pathlib.Path.mkdir', side_effect=TypeError("Mock type error")):
            add_simple_branding.generate_simple_branding_thumbnail(out_path, width=1280, height=720)
            assert out_path.exists()
            
        # Path.mkdir が OSError をスローする場合
        with patch('pathlib.Path.mkdir', side_effect=OSError("Mock OS error")):
            add_simple_branding.generate_simple_branding_thumbnail(out_path, width=1280, height=720)
            assert out_path.exists()

def test_logo_placeholder_and_font_fallback():
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_base = Path(tmpdir)
        logo_dir = tmp_base / "backend" / "branding" / "logos"
        logo_dir.mkdir(parents=True, exist_ok=True)
        
        original_truetype = ImageFont.truetype
        def mock_truetype(font, *args, **kwargs):
            # システムフォントロード時はエラーにするが、load_default内のtruetype(BytesIO等)は通す
            if isinstance(font, (str, Path)) and any(p in str(font).lower() for p in ["fonts", "truetype", "c:"]):
                raise OSError("Mock font load error")
            return original_truetype(font, *args, **kwargs)
            
        # truetype に mock_truetype を設定
        with patch('PIL.ImageFont.truetype', side_effect=mock_truetype):
            # create_combined_branding を実行
            output_path = add_simple_branding.create_combined_branding(target_height=45, base_path=tmp_base)
            assert output_path.exists()


def test_validate_thumbnail_file_not_found():
    # 存在しないファイルに対する例外
    with pytest.raises(FileNotFoundError):
        add_simple_branding.validate_thumbnail(Path("non_existent_file_12345.png"))

def test_validate_thumbnail_load_corruption():
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "load_corrupt.png"
        add_simple_branding.generate_simple_branding_thumbnail(out_path, width=1280, height=720)
        
        # verify() は成功するが load() で OSError をスローさせる
        with patch('PIL.Image.Image.load', side_effect=OSError("Mock load error")):
            with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
                add_simple_branding.validate_thumbnail(out_path)

def test_thumbnail_extreme_long_text_scaling():
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "extreme_long.png"
        # 改行が多く高さが極めて高いため、フォントサイズ縮小ループが回るはずのテキスト
        extreme_text = "\n".join(["Line " + str(i) for i in range(100)])
        add_simple_branding.generate_simple_branding_thumbnail(out_path, width=1280, height=720, text=extreme_text)
        assert out_path.exists()
        res = add_simple_branding.validate_thumbnail(out_path)
        assert res["width"] == 1280

def test_thumbnail_unlink_exceptions():
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "unlink_err.png"
        
        def mock_save_with_temp_creation(fp, *args, **kwargs):
            # 一時ファイルを実在させてから例外を投げる
            Path(fp).write_bytes(b"dummy temp data")
            raise OSError("Mock save error")
            
        # save()時に一時ファイルを作成してエラーを投げ、さらに unlink() で OSError をスローさせる
        with patch('PIL.Image.Image.save', side_effect=mock_save_with_temp_creation), \
             patch('pathlib.Path.unlink', side_effect=OSError("Mock unlink error")) as mock_unlink:
             
             with pytest.raises(OSError, match="Mock save error"):
                 add_simple_branding.generate_simple_branding_thumbnail(out_path, width=1280, height=720)
                 
             # unlinkが呼ばれて例外がキャッチされたことを確認
             assert mock_unlink.call_count >= 1

def test_generate_thumbnail_font_load_failure():
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "font_fail.png"
        
        # truetypeロードだけを例外にして、デフォルトフォントへのフォールバックを行わせる
        original_truetype = ImageFont.truetype
        def mock_truetype(font, *args, **kwargs):
            # システムフォントロード時はエラーにするが、load_default内のtruetypeは通す
            if isinstance(font, (str, Path)) and any(p in str(font).lower() for p in ["fonts", "truetype", "c:"]):
                raise OSError("Mock font load error")
            return original_truetype(font, *args, **kwargs)
            
        with patch('PIL.ImageFont.truetype', side_effect=mock_truetype), \
             patch('PIL.ImageDraw.ImageDraw.textbbox', side_effect=ValueError("Bbox calculation error")):
             add_simple_branding.generate_simple_branding_thumbnail(out_path, width=1280, height=720, text="Font Fail Test")
             assert out_path.exists()


def test_lanczos_resampling_fallback_branches():
    class MockImage:
        pass
        
    # 分岐 1: Resampling があり、LANCZOS がある場合
    mock_img = MockImage()
    class MockResampling:
        LANCZOS = 999
    mock_img.Resampling = MockResampling
    assert add_simple_branding._get_lanczos_filter(mock_img) == 999
    
    # 分岐 2: Resampling がなく、LANCZOS がある場合
    mock_img = MockImage()
    mock_img.LANCZOS = 888
    assert add_simple_branding._get_lanczos_filter(mock_img) == 888
    
    # 分岐 3: Resampling がなく、LANCZOS もなく、ANTIALIAS がある場合
    mock_img = MockImage()
    mock_img.ANTIALIAS = 777
    assert add_simple_branding._get_lanczos_filter(mock_img) == 777
    
    # 分岐 4: AttributeError が発生し、BICUBIC がある場合
    class MockImageWithProperty:
        @property
        def Resampling(self):
            raise AttributeError("No Resampling attribute")
        @property
        def BICUBIC(self):
            return 666
            
    assert add_simple_branding._get_lanczos_filter(MockImageWithProperty()) == 666
    
    # 分岐 5: AttributeError が発生し、BICUBIC もない場合
    class MockImageWithPropertyNoBicubic:
        @property
        def Resampling(self):
            raise AttributeError("No Resampling")
        @property
        def BICUBIC(self):
            raise AttributeError("No BICUBIC")
            
    assert add_simple_branding._get_lanczos_filter(MockImageWithPropertyNoBicubic()) is None


def test_logo_resize_fallback_when_lanczos_is_none():
    mock_logo = MagicMock()
    mock_logo.convert.return_value = mock_logo
    mock_logo.size = (10, 10)
    
    orig_lanczos = add_simple_branding.LANCZOS
    add_simple_branding.LANCZOS = None
    try:
        with patch('PIL.Image.open', return_value=mock_logo), \
             patch('pathlib.Path.exists', return_value=True):
             
            add_simple_branding._load_and_resize_logo(Path("dummy.png"), 20, 20)
            mock_logo.resize.assert_called_once_with((20, 20))
    finally:
        add_simple_branding.LANCZOS = orig_lanczos


def test_logo_placeholder_draw_text_error():
    with patch('PIL.Image.open', side_effect=FileNotFoundError("Not found")), \
         patch('PIL.ImageDraw.ImageDraw.text', side_effect=ValueError("Draw error")):
         
         logo = add_simple_branding._load_and_resize_logo(Path("dummy.png"), 20, 20)
         assert logo.size == (20, 20)


def test_select_branding_font_fallback_exception():
    with patch('pathlib.Path.exists', return_value=False), \
         patch('PIL.ImageFont.load_default', side_effect=[OSError("Load default fail"), MagicMock()]) as mock_load:
         
         font = add_simple_branding._select_branding_font(12)
         assert font is not None
         assert mock_load.call_count == 2


def test_thumbnail_validation_edge_cases(tmp_path):
    out_path = tmp_path / "edge_case.png"
    with pytest.raises(ValueError, match="Resolution exceeds maximum limit"):
        add_simple_branding.generate_simple_branding_thumbnail(out_path, width=8000, height=4500)
        
    with pytest.raises(ValueError, match="Output path must be a file path, not a directory"):
        add_simple_branding.generate_simple_branding_thumbnail(tmp_path, width=1280, height=720)
        
    unsupported_path = tmp_path / "unsupported.gif"
    with pytest.raises(ValueError, match="Unsupported file format"):
        add_simple_branding.generate_simple_branding_thumbnail(unsupported_path, width=1280, height=720)


def test_fit_text_font_load_default_error():
    mock_draw = MagicMock()
    with patch('pathlib.Path.exists', return_value=False), \
         patch('PIL.ImageFont.load_default', side_effect=OSError("Default font fail")):
         
         font, size = add_simple_branding._fit_text_font(
             mock_draw, ["Line 1"], 100, 100, 24, 2
         )
         assert font is None


def test_thumbnail_and_preview_resize_no_resampling_attribute_error(tmp_path):
    mock_img = MagicMock()
    mock_resized = MagicMock()
    
    # 呼び出し回数をカウントして、1回目の resize 呼び出しに対してのみ AttributeError を投げる
    call_count = 0
    def mock_resize_side_effect(size, resample=None, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise AttributeError("Simulated AttributeError for Resampling")
        return mock_resized
        
    mock_img.resize.side_effect = mock_resize_side_effect
    
    # 登録されている可能性のあるすべての add_simple_branding モジュールの LANCZOS を None にする
    import sys
    orig_lanczos_dict = {}
    for name, module in list(sys.modules.items()):
        if name in ('add_simple_branding', 'backend.add_simple_branding') or name.endswith('.add_simple_branding'):
            if module is not None:
                orig_lanczos_dict[module] = getattr(module, 'LANCZOS', None)
                module.LANCZOS = None
                
    # さらに、関数の __globals__ からも直接 LANCZOS を None にする
    fn_globals = add_simple_branding._save_thumbnail_to_path.__globals__
    orig_fn_lanczos = fn_globals.get('LANCZOS')
    fn_globals['LANCZOS'] = None
                
    try:
        with patch.object(Path, 'rename') as mock_rename:
            add_simple_branding._save_thumbnail_to_path(
                mock_img, 1280, 720, tmp_path / "temp.png", tmp_path / "out.png", ".png"
            )
            # 2回目のリサイズで BILINEAR (2) が呼び出されたことを検証
            mock_img.resize.assert_any_call((1280, 720), 2)
            mock_rename.assert_called_once_with(tmp_path / "out.png")
            
        # プレビュー側の検証
        mock_img.reset_mock()
        call_count = 0
        mock_img.resize.side_effect = mock_resize_side_effect
        with patch.object(Path, 'rename') as mock_rename:
            add_simple_branding._generate_preview_if_needed(
                mock_img, tmp_path / "preview.png", tmp_path / "temp_preview.png"
            )
            mock_img.resize.assert_any_call((640, 360), 2)
            mock_rename.assert_called_once_with(tmp_path / "preview.png")
    finally:
        for module, val in orig_lanczos_dict.items():
            module.LANCZOS = val
        fn_globals['LANCZOS'] = orig_fn_lanczos








def test_thumbnail_save_formats(tmp_path):
    jpg_path = tmp_path / "format_test.jpg"
    add_simple_branding.generate_simple_branding_thumbnail(jpg_path, width=1280, height=720, text="JPEG")
    assert jpg_path.exists()
    
    webp_path = tmp_path / "format_test.webp"
    add_simple_branding.generate_simple_branding_thumbnail(webp_path, width=1280, height=720, text="WEBP")
    assert webp_path.exists()


def test_thumbnail_and_preview_unlink_os_error(tmp_path):
    mock_img = MagicMock()
    
    out_path = tmp_path / "out.png"
    out_path.write_bytes(b"existing")
    temp_path = tmp_path / "temp.png"
    
    original_unlink = Path.unlink
    def mock_unlink(self, *args, **kwargs):
        if self.name in ("out.png", "preview.png"):
            raise OSError("Mock unlink failure")
        return original_unlink(self, *args, **kwargs)
        
    with patch.object(Path, 'unlink', new=mock_unlink), \
         patch.object(Path, 'rename') as mock_rename:
         
         add_simple_branding._save_thumbnail_to_path(
             mock_img, 1280, 720, temp_path, out_path, ".png"
         )
         mock_rename.assert_called_once_with(out_path)
         
    preview_path = tmp_path / "preview.png"
    preview_path.write_bytes(b"existing")
    temp_preview_path = tmp_path / "temp_preview.png"
    
    with patch.object(Path, 'unlink', new=mock_unlink), \
         patch.object(Path, 'rename') as mock_rename:
         
         add_simple_branding._generate_preview_if_needed(
             mock_img, preview_path, temp_preview_path
         )
         mock_rename.assert_called_once_with(preview_path)


def test_preview_mkdir_error(tmp_path):
    out_path = tmp_path / "mkdir_test.png"
    preview_path = tmp_path / "preview.png"
    
    original_mkdir = Path.mkdir
    def mock_mkdir(self, *args, **kwargs):
        if self == preview_path.parent:
            raise OSError("Mock mkdir failure")
        return original_mkdir(self, *args, **kwargs)
        
    with patch.object(Path, 'mkdir', new=mock_mkdir):
        add_simple_branding.generate_simple_branding_thumbnail(
            out_path, width=1280, height=720, text="Mkdir Test", preview_path=preview_path
        )
        assert out_path.exists()
        assert preview_path.exists()






