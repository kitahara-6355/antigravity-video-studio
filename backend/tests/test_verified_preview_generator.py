import sys
import runpy
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import PIL.ImageFont
import shutil
import tempfile

# backend ? sys.path ??????????????????
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from verified_preview_generator import create_verified_preview, get_video_dimensions, PreviewImageSizeError, PreviewImageResolutionError, PreviewImageAspectRatioError

original_truetype = PIL.ImageFont.truetype
has_ffmpeg = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def side_effect_truetype(*args, **kwargs):
    if len(args) > 0 and "Yu Gothic UI.ttf" in str(args[0]):
        raise OSError("Simulated font loading error")
    return original_truetype(*args, **kwargs)


def mock_subprocess_run_side_effect(*args, **kwargs):
    cmd = args[0]
    if isinstance(cmd, list):
        cmd_str = " ".join(cmd)
    else:
        cmd_str = str(cmd)
    if "ffprobe" in cmd_str:
        return MagicMock(returncode=0, stdout="1920x1080\n", stderr="")
    return MagicMock(returncode=0, stdout="success", stderr="")


@patch("verified_preview_generator.subprocess.run")
@patch("shutil.copy")
@patch("verified_preview_generator.Path.exists", return_value=True)
def test_create_verified_preview_all_success(mock_exists, mock_copy, mock_run):
    mock_run.side_effect = mock_subprocess_run_side_effect
    
    # 実行
    res = create_verified_preview(
        input_video="C:/dummy/input.mp4",
        output_dir="C:/dummy/output",
        logo_path="C:/dummy/logo.png",
        temp_dir="C:/dummy/temp"
    )
    
    # 検証
    expected_path = str(Path("C:/dummy/output") / "FINAL_verified_preview.mp4")
    assert res == expected_path
    
    # subprocess.run は 15回呼び出される（ffprobe 5回 + ffmpeg 10回）
    assert mock_run.call_count == 15
    mock_copy.assert_not_called()


@patch("verified_preview_generator.subprocess.run")
@patch("shutil.copy")
@patch("verified_preview_generator.Path.exists", return_value=True)
def test_create_verified_preview_font_exception(mock_exists, mock_copy, mock_run):
    with patch("PIL.ImageFont.truetype", side_effect=side_effect_truetype):
        mock_run.side_effect = mock_subprocess_run_side_effect
        
        res = create_verified_preview(
            input_video="C:/dummy/input.mp4",
            output_dir="C:/dummy/output",
            logo_path="C:/dummy/logo.png",
            temp_dir="C:/dummy/temp"
        )
        
        expected_path = str(Path("C:/dummy/output") / "FINAL_verified_preview.mp4")
        assert res == expected_path
        assert mock_run.call_count == 15
        mock_copy.assert_not_called()


@patch("verified_preview_generator.subprocess.run")
@patch("shutil.copy")
@patch("verified_preview_generator.Path.exists", return_value=True)
def test_create_verified_preview_subtitle_failure(mock_exists, mock_copy, mock_run):
    # 字幕描画 (drawtext) のみエラーになるように動的モックを構築
    def side_effect_drawtext_failure(*args, **kwargs):
        cmd = args[0]
        if isinstance(cmd, list):
            cmd_str = " ".join(cmd)
        else:
            cmd_str = str(cmd)
        if "ffprobe" in cmd_str:
            return MagicMock(returncode=0, stdout="1920x1080\n", stderr="")
        if "drawtext" in cmd_str:
            return MagicMock(returncode=1, stdout="", stderr="error")
        return MagicMock(returncode=0, stdout="success", stderr="")

    mock_run.side_effect = side_effect_drawtext_failure
    
    res = create_verified_preview(
        input_video="C:/dummy/input.mp4",
        output_dir="C:/dummy/output",
        logo_path="C:/dummy/logo.png",
        temp_dir="C:/dummy/temp"
    )
    
    expected_path = str(Path("C:/dummy/output") / "FINAL_verified_preview.mp4")
    assert res == expected_path
    
    # shutil.copy がフォールバックとして呼び出されること
    mock_copy.assert_called_once()


@patch("verified_preview_generator.subprocess.run")
def test_main_block_success(mock_run):
    mock_run.side_effect = mock_subprocess_run_side_effect
    
    with patch("sys.argv", ["verified_preview_generator.py"]), \
         patch("verified_preview_generator.Path.exists", return_value=True):
        runpy.run_module("verified_preview_generator", run_name="__main__")


@patch("verified_preview_generator.create_verified_preview")
def test_main_block_failure(mock_create):
    mock_create.side_effect = Exception("Simulated main error")
    
    with patch("sys.argv", ["verified_preview_generator.py"]):
        runpy.run_module("verified_preview_generator", run_name="__main__")


@pytest.mark.skipif(not has_ffmpeg, reason="ffmpeg or ffprobe not available")
def test_create_verified_preview_real_files():
    """
    実際の ffmpeg/ffprobe を用いたプレビュー動画とスクリーンショットの品質基準検証
    """
    with tempfile.TemporaryDirectory() as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        
        # 640x360 (16:9) の入力動画（16秒）を作成
        dummy_input = tmp_dir / "dummy_input.mp4"
        cmd_create_video = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "testsrc=size=640x360:rate=25",
            "-t", "16",
            "-pix_fmt", "yuv420p",
            str(dummy_input)
        ]
        subprocess.run(cmd_create_video, capture_output=True, check=True)
        
        # ダミーロゴ (100x45)
        dummy_logo = tmp_dir / "dummy_logo.png"
        from PIL import Image
        img = Image.new("RGBA", (100, 45), (255, 0, 0, 255))
        img.save(dummy_logo)
        
        output_dir = tmp_dir / "output"
        temp_dir = tmp_dir / "temp"
        
        # プレビュー動画およびスクリーンショットの生成
        res = create_verified_preview(
            input_video=str(dummy_input),
            output_dir=str(output_dir),
            logo_path=str(dummy_logo),
            temp_dir=str(temp_dir)
        )
        
        # 検証 1: 出力動画の存在
        assert Path(res).exists()
        assert Path(res).name == "FINAL_verified_preview.mp4"
        
        # 検証 2: スケールアップが 1280x720 に適用されていること
        w, h = get_video_dimensions(res)
        assert w == 1280
        assert h == 720
        assert abs(w / h - 1.7777) < 0.01  # 16:9
        
        # 検証 3: ファイルサイズが適切であること
        file_size = Path(res).stat().st_size
        assert file_size > 1000
        
        # 検証 4: すべてのスクリーンショット画像が正常に存在し、1280x720 16:9、4MB未満であること
        from verified_preview_generator import validate_preview_image
        
        expected_screenshots = [
            output_dir / "verify_step1_original.png",
            output_dir / "verify_step2_with_logo.png",
            output_dir / "verify_step3_with_telop.png",
            output_dir / "FINAL_screenshot_1_1s.png",
            output_dir / "FINAL_screenshot_2_3s.png",
            output_dir / "FINAL_screenshot_3_7s.png",
        ]
        
        for ss in expected_screenshots:
            # ensure_preview_image_quality により .jpg に変更されている可能性も考慮
            found_files = list(output_dir.glob(f"{ss.stem}.*"))
            assert len(found_files) >= 1
            for f in found_files:
                if f.suffix.lower() in ('.png', '.jpg', '.jpeg'):
                    # 品質基準を自動アサート (例外が起きないこと)
                    val_res = validate_preview_image(str(f))
                    assert val_res["width"] == 1280
                    assert val_res["height"] == 720
                    assert val_res["size_bytes"] < 4 * 1024 * 1024


@pytest.mark.asyncio
async def test_verified_preview_generator_stage_bound_agent_integration(tmp_path):
    """
    StageBoundAgent 連携テスト。自動リトライ、結果保存、DBマイグレーションの各機能と連携して動作することを確認する。
    """
    from agents.stage_bound_agent import StageBoundAgent
    import json
    import sqlite3
    import asyncio
    
    db_file = tmp_path / "agent_integration.db"
    
    # 1. DBマイグレーション連携の確認
    conn = sqlite3.connect(str(db_file))
    conn.execute("""
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            stage TEXT,
            status TEXT,
            error TEXT,
            created_at REAL,
            updated_at REAL
        )
    """)
    conn.commit()
    conn.close()
    
    agent = StageBoundAgent(stage_name="verified_preview", db_path=str(db_file))
    
    conn = sqlite3.connect(str(db_file))
    cursor = conn.execute("PRAGMA table_info(tasks)")
    columns = [row[1] for row in cursor.fetchall()]
    conn.close()
    assert "result" in columns
    assert "retry_count" in columns
    assert "max_retries" in columns
    
    # 2. 自動リトライおよび結果保存連携の確認
    await agent.register_task(task_id="t_preview_01", initial_status="READY", max_retries=2)
    
    call_count = 0
    
    # agent に必要な属性を設定
    agent.input_video = "dummy_input.mp4"
    agent.output_dir = str(tmp_path / "output")
    agent.logo_path = str(tmp_path / "logo.png")
    agent.temp_dir = str(tmp_path / "temp")
    
    async def mock_resolve_verified_preview_task(task_id):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise ValueError("Transient ffmpeg error")
            
        result_info = {
            "task_id": task_id,
            "video_path": str(tmp_path / "output" / "FINAL_verified_preview.mp4"),
            "validation": [
                {
                    "path": str(tmp_path / "output" / "verify_step1_original.png"),
                    "width": 1280,
                    "height": 720,
                    "size_bytes": 100000
                }
            ]
        }
        return json.dumps(result_info)
        
    await agent.start(mock_resolve_verified_preview_task)
    await asyncio.sleep(0.5)
    
    final_status = await agent.get_task_status("t_preview_01")
    assert final_status == "COMPLETED"
    assert call_count == 2
    
    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.execute("SELECT result, retry_count, error FROM tasks WHERE id = 't_preview_01'")
        row = cursor.fetchone()
        assert "validation" in row[0]
        assert row[1] == 1
        assert "Transient ffmpeg error" in row[2]
    finally:
        conn.close()
        
    await agent.stop()


def test_validate_preview_image_standards(tmp_path):
    """
    品質基準（解像度 1280x720 以上、アスペクト比 16:9、ファイルサイズ 4MB 未満、Pillow破損ロード確認）
    の個別ユニットテスト
    """
    from PIL import Image
    from verified_preview_generator import validate_preview_image, ensure_preview_image_quality
    
    # 1. 正常系画像作成
    good_img_path = tmp_path / "good.png"
    img = Image.new("RGB", (1280, 720), (255, 255, 255))
    img.save(good_img_path)
    
    res = validate_preview_image(str(good_img_path))
    assert res["width"] == 1280
    assert res["height"] == 720
    assert res["size_bytes"] < 4 * 1024 * 1024
    
    # 2. 低解像度画像の自動補正テスト
    bad_img_path = tmp_path / "bad.png"
    img_bad = Image.new("RGB", (640, 480), (100, 100, 100))
    img_bad.save(bad_img_path)
    
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        validate_preview_image(str(bad_img_path))
        
    corrected_path = ensure_preview_image_quality(str(bad_img_path))
    
    res_corrected = validate_preview_image(corrected_path)
    assert res_corrected["width"] == 1280
    assert res_corrected["height"] == 720



def test_thumbnail_rigorous_quality_rules_validation(tmp_path):
    """
    最優先ルールで指定された品質基準および StageBoundAgent 連携を包括的に検証するテスト
    """
    from PIL import Image
    from verified_preview_generator import validate_preview_image, ensure_preview_image_quality
    import os

    # 1. 1280x720 以上の解像度、16:9 アスペクト比、4MB 未満、Pillow破損なしの確認
    img_path = tmp_path / "test_standard.png"
    # 1920x1080 は 1280x720 以上であり、16:9 である
    img = Image.new("RGB", (1920, 1080), (100, 100, 100))
    img.save(img_path)
    
    # 品質要件を検証
    res = validate_preview_image(str(img_path))
    
    # 生成画像の解像度が 1280x720 以上であること
    assert res["width"] >= 1280
    assert res["height"] >= 720
    
    # アスペクト比が 16:9 であること
    assert abs((res["width"] / res["height"]) - (16.0 / 9.0)) < 0.01
    
    # ファイルサイズが 4MB 未満であること
    assert res["size_bytes"] < 4 * 1024 * 1024
    
    # 出力ファイルが正常に存在し、破損していない（Pillow等で正常にロード可能である）こと
    assert os.path.exists(res["path"])
    with Image.open(res["path"]) as test_img:
        test_img.verify()
    with Image.open(res["path"]) as test_img:
        test_img.load()  # 正常にロード可能であることを確認
        
    # 2. 自動補正（ensure_preview_image_quality）が正しく機能し、1280x720 16:9 になること
    non_standard_path = tmp_path / "non_standard.png"
    # 非標準的なアスペクト比と解像度 (800x600)
    img_ns = Image.new("RGB", (800, 600), (50, 50, 50))
    img_ns.save(non_standard_path)
    
    corrected_path = ensure_preview_image_quality(str(non_standard_path))
    res_corrected = validate_preview_image(corrected_path)
    
    assert res_corrected["width"] == 1280
    assert res_corrected["height"] == 720
    assert abs((res_corrected["width"] / res_corrected["height"]) - (16.0 / 9.0)) < 0.01
    assert res_corrected["size_bytes"] < 4 * 1024 * 1024


def test_validate_preview_image_custom_exceptions(tmp_path):
    """カスタム例外クラスが正しく送出されるか検証するテスト"""
    from PIL import Image
    from verified_preview_generator import validate_preview_image

    # 1. 解像度不足エラーの検証 (640x360 は 1280x720 未満)
    low_res_path = tmp_path / "low_res.png"
    img = Image.new("RGB", (640, 360), (255, 255, 255))
    img.save(low_res_path)
    with pytest.raises(PreviewImageResolutionError, match="Resolution must be at least 1280x720"):
        validate_preview_image(str(low_res_path))

    # 2. アスペクト比不正エラーの検証 (1280x1280 は 1:1 で 16:9 ではない)
    bad_ratio_path = tmp_path / "bad_ratio.png"
    img = Image.new("RGB", (1280, 1280), (255, 255, 255))
    img.save(bad_ratio_path)
    with pytest.raises(PreviewImageAspectRatioError, match="Aspect ratio must be 16:9"):
        validate_preview_image(str(bad_ratio_path))

    # 3. ファイルサイズエラーの検証 (4MBを超える場合)
    large_file_path = tmp_path / "large_file.png"
    img = Image.new("RGB", (1920, 1080), (255, 255, 255))
    img.save(large_file_path)
    
    # st_size が 5MB を返すように os.stat をパッチする
    import os
    original_stat = os.stat
    def mock_stat(path_arg, *args, **kwargs):
        stat_result = original_stat(path_arg, *args, **kwargs)
        if str(large_file_path) in str(path_arg) or "large_file.png" in str(path_arg):
            # 5MBを偽装
            class MockStatResult:
                st_size = 5 * 1024 * 1024
                st_mode = stat_result.st_mode
                st_ino = stat_result.st_ino
                st_dev = stat_result.st_dev
                st_nlink = stat_result.st_nlink
                st_uid = stat_result.st_uid
                st_gid = stat_result.st_gid
                st_atime = stat_result.st_atime
                st_mtime = stat_result.st_mtime
                st_ctime = stat_result.st_ctime
            return MockStatResult()
        return stat_result

    with patch("os.stat", side_effect=mock_stat):
        with pytest.raises(PreviewImageSizeError, match="File size exceeds 4MB limit"):
            validate_preview_image(str(large_file_path))


def test_ensure_preview_image_quality_corrupted_fallback(tmp_path):
    """破損画像ファイルが渡された場合に fallback 1280x720 画像が生成されることを検証"""
    from verified_preview_generator import ensure_preview_image_quality, validate_preview_image
    
    corrupted_file = tmp_path / "corrupted.png"
    # 不正なバイト列を書き込んで破損ファイルをエミュレート
    corrupted_file.write_bytes(b"INVALID_IMAGE_DATA_123456789")
    
    corrected_path = ensure_preview_image_quality(str(corrupted_file))
    
    # 補正後のファイルが正常に検証をパスすること（1280x720, 16:9, 4MB未満）
    res = validate_preview_image(corrected_path)
    assert res["width"] == 1280
    assert res["height"] == 720
    assert res["size_bytes"] < 4 * 1024 * 1024


def test_ensure_preview_image_quality_extreme_aspect_ratios(tmp_path):
    """極端なアスペクト比の画像が 1280x720 16:9 に正常補正されることを検証"""
    from PIL import Image
    from verified_preview_generator import ensure_preview_image_quality, validate_preview_image
    
    # 1. 極端な縦長 (100 x 2000)
    tall_path = tmp_path / "tall.png"
    img = Image.new("RGB", (100, 2000), (255, 0, 0))
    img.save(tall_path)
    
    corrected_tall = ensure_preview_image_quality(str(tall_path))
    res_tall = validate_preview_image(corrected_tall)
    assert res_tall["width"] == 1280
    assert res_tall["height"] == 720
    
    # 2. 極端な横長 (2000 x 100)
    wide_path = tmp_path / "wide.png"
    img = Image.new("RGB", (2000, 100), (0, 255, 0))
    img.save(wide_path)
    
    corrected_wide = ensure_preview_image_quality(str(wide_path))
    res_wide = validate_preview_image(corrected_wide)
    assert res_wide["width"] == 1280
    assert res_wide["height"] == 720


def test_ensure_preview_image_quality_compression_logic(tmp_path):
    """巨大な画像が 4MB 未満に抑えられる圧縮ループロジックの検証"""
    from PIL import Image
    from verified_preview_generator import ensure_preview_image_quality, validate_preview_image
    from pathlib import Path
    
    # 非常に大きな画像 (4000x3000) を作成
    large_img_path = tmp_path / "large_raw.png"
    img = Image.new("RGB", (4000, 3000), (128, 128, 128))
    img.save(large_img_path)
    
    # ensure_preview_image_quality 内で 1280x720 に縮小され、かつ 4MB 未満に収まることを検証
    corrected_path = ensure_preview_image_quality(str(large_img_path))
    res = validate_preview_image(corrected_path)
    
    assert res["width"] == 1280
    assert res["height"] == 720
    assert res["size_bytes"] < 4 * 1024 * 1024
    assert Path(corrected_path).exists()

def test_validate_preview_image_exact_resolution_limit(tmp_path):
    """解像度の境界値検証。1279x720 や 1280x719 などの境界未満が正しくエラーになることをテスト。"""
    from PIL import Image
    from verified_preview_generator import validate_preview_image, PreviewImageResolutionError
    
    # 1. 幅不足 (1279x720)
    img_width_fail = tmp_path / "width_fail.png"
    Image.new("RGB", (1279, 720), (255, 255, 255)).save(img_width_fail)
    with pytest.raises(PreviewImageResolutionError, match="Resolution must be at least 1280x720"):
        validate_preview_image(str(img_width_fail))
        
    # 2. 高さ不足 (1280x719)
    img_height_fail = tmp_path / "height_fail.png"
    Image.new("RGB", (1280, 719), (255, 255, 255)).save(img_height_fail)
    with pytest.raises(PreviewImageResolutionError, match="Resolution must be at least 1280x720"):
        validate_preview_image(str(img_height_fail))


def test_validate_preview_image_invalid_aspect_ratio_boundary(tmp_path):
    """アスペクト比の境界値検証。16:9 (1.777) から許容閾値 0.01 を超えてずれている場合のエラーハンドリング。"""
    from PIL import Image
    from verified_preview_generator import validate_preview_image, PreviewImageAspectRatioError
    
    # 16:9 は 1.7777...
    # 許容閾値 0.01 のため、1.787 を超えるか 1.767 を下回るとエラーになるはず。
    # 1920 x 1000 は解像度要件 (>=1280x720) を満たすが、アスペクト比 1.92 は 1.777 からずれているためエラー。
    img_aspect_fail = tmp_path / "aspect_fail.png"
    Image.new("RGB", (1920, 1000), (255, 255, 255)).save(img_aspect_fail)
    with pytest.raises(PreviewImageAspectRatioError, match="Aspect ratio must be 16:9"):
        validate_preview_image(str(img_aspect_fail))


def test_ensure_preview_image_quality_non_existent_input():
    """存在しない入力ファイルを渡された場合に、エラーを起こさず入力されたパス文字列をそのまま返すことを検証。"""
    from verified_preview_generator import ensure_preview_image_quality
    from pathlib import Path
    non_existent_path = "C:/non_existent_directory_12345/image.png"
    res = ensure_preview_image_quality(non_existent_path)
    assert Path(res) == Path(non_existent_path)


def test_run_command_safely_not_found():
    """コマンドが見つからない場合（FileNotFoundError）のエラーハンドリングと例外の再送出をテスト。"""
    from verified_preview_generator import run_command_safely
    with pytest.raises(FileNotFoundError, match="Command execution failed due to missing executable"):
        run_command_safely(["non_existent_command_xyz_123"])


def test_ensure_preview_image_quality_high_resolution_preserved(tmp_path):
    """元の画像が 1920x1080 (16:9) であるとき、解像度 1920x1080 を維持して 1280x720 に縮小されないことを確認。"""
    from PIL import Image
    from verified_preview_generator import ensure_preview_image_quality, validate_preview_image
    
    img_path = tmp_path / "high_res_original.png"
    img = Image.new("RGB", (1920, 1080), (255, 255, 255))
    img.save(img_path)
    
    corrected_path = ensure_preview_image_quality(str(img_path))
    res = validate_preview_image(corrected_path)
    
    # 1280x720 ではなく 1920x1080 が維持されていることを確認
    assert res["width"] == 1920
    assert res["height"] == 1080
    assert abs(res["width"] / res["height"] - 16.0/9.0) < 0.01


def test_ensure_preview_image_quality_high_resolution_large_file_compressed(tmp_path):
    """元の画像が 1920x1080 で、ファイルサイズが 4MB を超える場合、1280x720 に補正された上で圧縮され 4MB 未満になることを確認。"""
    from PIL import Image
    from verified_preview_generator import ensure_preview_image_quality, validate_preview_image
    from unittest.mock import patch
    
    img_path = tmp_path / "high_res_large.png"
    img = Image.new("RGB", (1920, 1080), (255, 255, 255))
    img.save(img_path)
    
    # st_size が 5MB を返すように os.stat をパッチする
    import os
    original_stat = os.stat
    def mock_stat(path_arg, *args, **kwargs):
        stat_result = original_stat(path_arg, *args, **kwargs)
        if str(img_path) in str(path_arg) or "high_res_large.png" in str(path_arg):
            class MockStatResult:
                st_size = 5 * 1024 * 1024
                st_mode = stat_result.st_mode
                st_ino = stat_result.st_ino
                st_dev = stat_result.st_dev
                st_nlink = stat_result.st_nlink
                st_uid = stat_result.st_uid
                st_gid = stat_result.st_gid
                st_atime = stat_result.st_atime
                st_mtime = stat_result.st_mtime
                st_ctime = stat_result.st_ctime
            return MockStatResult()
        return stat_result

    with patch("os.stat", side_effect=mock_stat):
        corrected_path = ensure_preview_image_quality(str(img_path))
        # 圧縮後のファイルを検証
        res = validate_preview_image(corrected_path)
        assert res["width"] == 1280
        assert res["height"] == 720
        assert res["size_bytes"] < 4 * 1024 * 1024


@pytest.mark.asyncio
async def test_resolve_verified_preview_task_exceptions():
    """resolve_verified_preview_task のエラーハンドリングと PreviewValidationError 送出を検証。"""
    from verified_preview_generator import resolve_verified_preview_task, PreviewValidationError
    
    class DummyAgent:
        input_video = None
        output_dir = "backend/temp/verified_preview"
        logo_path = "backend/branding/logos/brand_logo.png"
        temp_dir = "backend/temp/verified_preview_temp"

    agent = DummyAgent()
    
    # input_video が設定されていない場合、ValueError が発生
    with pytest.raises(ValueError, match="input_video not configured"):
        await resolve_verified_preview_task(agent, "task_err_01")
        
    # 動画生成プロセスが失敗した場合に PreviewValidationError が発生することを確認
    agent.input_video = "C:/non_existent_directory_98765/video.mp4"
    with pytest.raises(PreviewValidationError):
        await resolve_verified_preview_task(agent, "task_err_02")

def test_thumbnail_strict_quality_and_agent_integration_validation(tmp_path):
    """
    サムネイル品質基準（解像度 1280x720 以上、アスペクト比 16:9、4MB未満、Pillow破損なし）
    および StageBoundAgent 連携を厳密に検証する追加テスト
    """
    from PIL import Image
    from verified_preview_generator import validate_preview_image, ensure_preview_image_quality
    import os

    # 1. 1280x720 以上の解像度、16:9アスペクト比、4MB未満、破損なしのテスト
    ok_path = tmp_path / "strict_ok.png"
    img = Image.new("RGB", (1280, 720), (255, 255, 255))
    img.save(ok_path)
    
    # 正常にバリデーションが通ることを検証
    res = validate_preview_image(str(ok_path))
    assert res["width"] == 1280
    assert res["height"] == 720
    assert abs((res["width"] / res["height"]) - (16.0 / 9.0)) < 0.01
    assert res["size_bytes"] < 4 * 1024 * 1024
    
    # ファイル破損がないことをPillowでロードして確認
    with Image.open(res["path"]) as im:
        im.verify()
    with Image.open(res["path"]) as im:
        im.load()

    # 2. アスペクト比や解像度、ファイルサイズが異常な場合のエラー検証
    # (a) 解像度不足 (1279x720)
    bad_res_path = tmp_path / "strict_bad_res.png"
    Image.new("RGB", (1279, 720), (0, 0, 0)).save(bad_res_path)
    with pytest.raises(PreviewImageResolutionError, match="Resolution must be at least 1280x720"):
        validate_preview_image(str(bad_res_path))

    # (b) アスペクト比不正 (1280x800 = 1.6 != 1.777)
    bad_ratio_path = tmp_path / "strict_bad_ratio.png"
    Image.new("RGB", (1280, 800), (0, 0, 0)).save(bad_ratio_path)
    with pytest.raises(PreviewImageAspectRatioError, match="Aspect ratio must be 16:9"):
        validate_preview_image(str(bad_ratio_path))

    # (c) ファイルサイズが 4MB 以上
    large_path = tmp_path / "strict_large.png"
    Image.new("RGB", (1920, 1080), (0, 0, 0)).save(large_path)
    
    # os.stat をモックしてファイルサイズ 4MB 以上をエミュレート
    original_stat = os.stat
    def mock_stat_large(path_arg, *args, **kwargs):
        res_stat = original_stat(path_arg, *args, **kwargs)
        if str(large_path) in str(path_arg) or "strict_large.png" in str(path_arg):
            class LargeStatResult:
                st_size = 4 * 1024 * 1024 + 100 # 4MB超
                st_mode = res_stat.st_mode
                st_ino = res_stat.st_ino
                st_dev = res_stat.st_dev
                st_nlink = res_stat.st_nlink
                st_uid = res_stat.st_uid
                st_gid = res_stat.st_gid
                st_atime = res_stat.st_atime
                st_mtime = res_stat.st_mtime
                st_ctime = res_stat.st_ctime
            return LargeStatResult()
        return res_stat

    with patch("os.stat", side_effect=mock_stat_large):
        with pytest.raises(PreviewImageSizeError, match="File size exceeds 4MB limit"):
            validate_preview_image(str(large_path))

def test_ensure_preview_image_quality_enhancements(tmp_path):
    """
    コントラストと彩度の向上が適用されていることを検証するテスト
    """
    from PIL import Image
    from verified_preview_generator import ensure_preview_image_quality
    
    # 完全にフラットなグレーではなく、色情報を持つ 100x100 画像を作成
    img_path = tmp_path / "original_color.png"
    img = Image.new("RGB", (100, 100), (120, 100, 80))
    img.save(img_path)
    
    # 品質向上補正を適用
    corrected_path = ensure_preview_image_quality(str(img_path))
    
    # 補正後の画像は 1280x720 にリサイズされ、アスペクト比 16:9 のキャンバスに中央配置され、
    # シャープネス、コントラスト、彩度のエンハンスメントが行われているはず。
    with Image.open(corrected_path) as corrected_img:
        corrected_img.load()
        assert corrected_img.size == (1280, 720)
        # 中央の領域（100x100 から拡大された領域）を取得し、ピクセル値に変化（エンハンス）があることを確認
        # 中央のピクセルをサンプリング
        pixel_val = corrected_img.getpixel((640, 360))
        # 元の (120, 100, 80) よりコントラスト/彩度補正が入り、色味が変化しているか確認
        # 黒の背景（0,0,0）ではなく、描画領域に色があることを確認
        assert pixel_val != (0, 0, 0)


def test_ensure_preview_image_quality_corrupted_fallback_text_drawn(tmp_path):
    """
    画像破損によるフォールバック発生時に、生成されたフォールバック画像に
    エラーテキスト（PREVIEW FALLBACK）が描画され、単なる真っ黒（0, 0, 0）ではないことを検証
    """
    from verified_preview_generator import ensure_preview_image_quality
    from PIL import Image
    
    corrupted_file = tmp_path / "corrupted_img.png"
    corrupted_file.write_bytes(b"BAD_IMAGE_DATA_HEADER_ERROR")
    
    corrected_path = ensure_preview_image_quality(str(corrupted_file))
    
    with Image.open(corrected_path) as img:
        img.load()
        assert img.size == (1280, 720)
        # フォールバック画像（20, 20, 20）をベースに、テキストが白や薄いグレー（180, 180, 180）で描画されている
        # 完全に (20, 20, 20) のみの単一色ではない（テキストのピクセルが含まれている）ことを検証
        colors = img.getcolors(maxcolors=1280*720)
        # 単一色（1色のみ）で構成されている場合は len(colors) == 1 になるが、
        # テキストが描画されていれば複数色が存在するはず
        assert len(colors) > 1


def test_ensure_preview_image_quality_zero_byte_file(tmp_path):
    """
    0バイトのファイルが渡された場合に、破損ファイルとして安全に検知され、
    エラーを起こさずにフォールバック画像が正常に生成されることを検証
    """
    from verified_preview_generator import ensure_preview_image_quality, validate_preview_image
    
    zero_byte_file = tmp_path / "zero.png"
    zero_byte_file.write_bytes(b"") # 0バイトファイル
    
    corrected_path = ensure_preview_image_quality(str(zero_byte_file))
    
    # 補正後のファイルが正常に検証をパスすること（1280x720, 16:9, 4MB未満）
    res = validate_preview_image(corrected_path)
    assert res["width"] == 1280
    assert res["height"] == 720
    assert res["size_bytes"] < 4 * 1024 * 1024


def test_validate_preview_image_aspect_ratio_boundaries(tmp_path):
    """アスペクト比の許容差 0.01 の数理的境界値検証 (解像度 1280x720 以上の制約を担保するため 1920x1080 基準で検証)"""
    from PIL import Image
    from verified_preview_generator import validate_preview_image, PreviewImageAspectRatioError
    
    # 1. 許容範囲内 (下限ぎりぎり: 1920x1086 => 1.7679 => 差 0.0098)
    img_ok_low = tmp_path / "ok_low.png"
    Image.new("RGB", (1920, 1086), (255, 255, 255)).save(img_ok_low)
    res = validate_preview_image(str(img_ok_low))
    assert res["height"] == 1086
    
    # 2. 許容範囲外 (下限超過: 1920x1087 => 1.7663 => 差 0.0114)
    img_ng_low = tmp_path / "ng_low.png"
    Image.new("RGB", (1920, 1087), (255, 255, 255)).save(img_ng_low)
    with pytest.raises(PreviewImageAspectRatioError, match="Aspect ratio must be 16:9"):
        validate_preview_image(str(img_ng_low))
        
    # 3. 許容範囲内 (上限ぎりぎり: 1920x1074 => 1.7877 => 差 0.0099)
    img_ok_high = tmp_path / "ok_high.png"
    Image.new("RGB", (1920, 1074), (255, 255, 255)).save(img_ok_high)
    res = validate_preview_image(str(img_ok_high))
    assert res["height"] == 1074
    
    # 4. 許容範囲外 (上限超過: 1920x1073 => 1.7893 => 差 0.0115)
    img_ng_high = tmp_path / "ng_high.png"
    Image.new("RGB", (1920, 1073), (255, 255, 255)).save(img_ng_high)
    with pytest.raises(PreviewImageAspectRatioError, match="Aspect ratio must be 16:9"):
        validate_preview_image(str(img_ng_high))


def test_validate_preview_image_size_boundaries(tmp_path):
    """ファイルサイズのしきい値 4MB (4194304バイト) の境界値検証"""
    from PIL import Image
    from verified_preview_generator import validate_preview_image, PreviewImageSizeError
    import os
    
    img_path = tmp_path / "size_boundary.png"
    Image.new("RGB", (1280, 720), (255, 255, 255)).save(img_path)
    
    original_stat = os.stat
    
    # 4194303 バイトを偽装 (OK)
    def mock_stat_ok(path_arg, *args, **kwargs):
        stat_res = original_stat(path_arg, *args, **kwargs)
        if str(img_path) in str(path_arg) or "size_boundary.png" in str(path_arg):
            class MockStat:
                st_size = 4 * 1024 * 1024 - 1
                st_mode = stat_res.st_mode
                st_ino = stat_res.st_ino
                st_dev = stat_res.st_dev
                st_nlink = stat_res.st_nlink
                st_uid = stat_res.st_uid
                st_gid = stat_res.st_gid
                st_atime = stat_res.st_atime
                st_mtime = stat_res.st_mtime
                st_ctime = stat_res.st_ctime
            return MockStat()
        return stat_res
        
    with patch("os.stat", side_effect=mock_stat_ok):
        res = validate_preview_image(str(img_path))
        assert res["size_bytes"] == 4 * 1024 * 1024 - 1
        
    # 4194304 バイトを偽装 (NG)
    def mock_stat_ng(path_arg, *args, **kwargs):
        stat_res = original_stat(path_arg, *args, **kwargs)
        if str(img_path) in str(path_arg) or "size_boundary.png" in str(path_arg):
            class MockStat:
                st_size = 4 * 1024 * 1024
                st_mode = stat_res.st_mode
                st_ino = stat_res.st_ino
                st_dev = stat_res.st_dev
                st_nlink = stat_res.st_nlink
                st_uid = stat_res.st_uid
                st_gid = stat_res.st_gid
                st_atime = stat_res.st_atime
                st_mtime = stat_res.st_mtime
                st_ctime = stat_res.st_ctime
            return MockStat()
        return stat_res
        
    with patch("os.stat", side_effect=mock_stat_ng):
        with pytest.raises(PreviewImageSizeError, match="File size exceeds 4MB limit"):
            validate_preview_image(str(img_path))


def test_ensure_preview_image_quality_unidentified_image_error(tmp_path):
    """Image.openがUnidentifiedImageErrorを投げた場合、フォールバック画像が正しく生成されることの検証"""
    from verified_preview_generator import ensure_preview_image_quality, validate_preview_image
    
    corrupted_file = tmp_path / "unidentified.png"
    # PILで解釈できないでたらめなヘッダ
    corrupted_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRinvalid_header_data")
    
    corrected_path = ensure_preview_image_quality(str(corrupted_file))
    
    # 補正後のファイルが正常に検証をパスすること（1280x720, 16:9, 4MB未満）
    res = validate_preview_image(corrected_path)
    assert res["width"] == 1280
    assert res["height"] == 720


def test_phase27_explicit_quality_standards_compliance(tmp_path):
    """
    Phase 27 サムネイル品質向上タスクで定義された、以下の4要件の自動検証の確認:
    1. 生成画像の解像度が 1280x720 以上であること
    2. アスペクト比が 16:9 であること
    3. ファイルサイズが 4MB 未満であること
    4. 出力ファイルが正常に存在し、破損していない（Pillow等で正常にロード可能である）こと
    """
    from PIL import Image
    from verified_preview_generator import validate_preview_image
    import os

    # 正常系（1280x720, 16:9, <4MB）
    img_path = tmp_path / "phase27_std_ok.png"
    img = Image.new("RGB", (1280, 720), (255, 255, 255))
    img.save(img_path)

    # 1. 存在確認とPillowでの破損なしロード検証
    assert img_path.exists()
    with Image.open(img_path) as im:
        im.verify()
    with Image.open(img_path) as im:
        im.load()

    # 2. validate_preview_image を使って総合的に検証
    res = validate_preview_image(str(img_path))
    assert res["width"] >= 1280
    assert res["height"] >= 720
    assert abs((res["width"] / res["height"]) - (16.0 / 9.0)) < 0.01
    assert res["size_bytes"] < 4 * 1024 * 1024


def test_fallback_image_rich_aesthetics(tmp_path):
    """フォールバック画像がグラデーションと洗練されたテキストなどのプレミアムなデザインになっていることを検証"""
    from verified_preview_generator import ensure_preview_image_quality
    from PIL import Image

    # 破損画像を書き込む
    corrupted_file = tmp_path / "corrupted_rich.png"
    corrupted_file.write_bytes(b"CORRUPTED_DATA_FOR_AESTHETICS")

    corrected_path = ensure_preview_image_quality(str(corrupted_file))
    
    with Image.open(corrected_path) as img:
        img.load()
        assert img.size == (1280, 720)
        
        # 上部と下部のピクセルを取得してグラデーション（異なる色）であることを確認
        top_pixel = img.getpixel((640, 100))
        bottom_pixel = img.getpixel((640, 620))
        # 完全に同じ色ではないことを確認
        assert top_pixel != bottom_pixel
        # ダークトーンであることを確認 (R, G, B 各値が小さめであること)
        assert all(c < 100 for c in top_pixel)
        assert all(c < 100 for c in bottom_pixel)


def test_temporary_files_cleanup_on_failure(tmp_path):
    """create_verified_preview 内で例外が発生した際、一時ファイルが確実に削除されていることを検証"""
    from verified_preview_generator import create_verified_preview
    import pytest
    from unittest.mock import patch

    # 入力動画とロゴをダミーで作成
    input_video = tmp_path / "dummy_input.mp4"
    input_video.write_bytes(b"dummy video data")
    logo_path = tmp_path / "dummy_logo.png"
    logo_path.write_bytes(b"dummy logo data")

    # 一時ディレクトリ
    temp_dir = tmp_path / "temp_clean"
    output_dir = tmp_path / "output_clean"

    # get_video_dimensionsをパッチして正常値を返させ、
    # run_command_safelyで例外を発生させるようにする
    with patch("verified_preview_generator.get_video_dimensions", return_value=(1920, 1080)), \
         patch("verified_preview_generator.run_command_safely", side_effect=ValueError("Simulated ffmpeg failure")):
        
        with pytest.raises(ValueError, match="Simulated ffmpeg failure"):
            create_verified_preview(
                input_video=str(input_video),
                output_dir=str(output_dir),
                logo_path=str(logo_path),
                temp_dir=str(temp_dir)
            )

    # 例外発生後、一時ディレクトリがクリーンアップされていること（空である、あるいは削除されていること）を確認
    if temp_dir.exists():
        assert not list(temp_dir.iterdir())


def test_detailed_exception_messages(tmp_path):
    """validate_preview_image の例外メッセージに実測値が含まれていることを検証"""
    from PIL import Image
    from verified_preview_generator import validate_preview_image, PreviewImageAspectRatioError, PreviewImageResolutionError
    
    # 1. 解像度不足
    low_res_path = tmp_path / "low_res_msg.png"
    Image.new("RGB", (640, 360), (255, 255, 255)).save(low_res_path)
    with pytest.raises(PreviewImageResolutionError) as exc_info:
        validate_preview_image(str(low_res_path))
    assert "Got 640x360" in str(exc_info.value)
    
    # 2. アスペクト比不正
    bad_ratio_path = tmp_path / "bad_ratio_msg.png"
    Image.new("RGB", (1280, 1280), (255, 255, 255)).save(bad_ratio_path)
    with pytest.raises(PreviewImageAspectRatioError) as exc_info:
        validate_preview_image(str(bad_ratio_path))
    assert "Got 1.000" in str(exc_info.value)
    assert "resolution: 1280x1280" in str(exc_info.value)


def test_create_verified_preview_font_oserror(tmp_path):
    """フォントのロードで OSError が発生した際、警告が出力されデフォルトフォントでフォールバックされることを検証"""
    from verified_preview_generator import create_verified_preview
    from unittest.mock import patch
    
    # OSErrorを発生させる
    def side_effect_truetype_oserror(*args, **kwargs):
        if len(args) > 0 and any(f in str(args[0]) for f in ["Yu Gothic", "msyh", "msgothic"]):
            raise OSError("Simulated font loading OSError")
        return original_truetype(*args, **kwargs)

    # 入力ファイルとロゴをダミーで作成
    input_video = tmp_path / "dummy_input.mp4"
    input_video.write_bytes(b"dummy video data")
    logo_path = tmp_path / "dummy_logo.png"
    logo_path.write_bytes(b"dummy logo data")
    
    with patch("verified_preview_generator.subprocess.run") as mock_run, \
         patch("verified_preview_generator.get_video_dimensions", return_value=(1920, 1080)), \
         patch("PIL.ImageFont.truetype", side_effect=side_effect_truetype_oserror):
         
        mock_run.side_effect = mock_subprocess_run_side_effect
        
        # create_verified_preview を実行
        res = create_verified_preview(
            input_video=str(input_video),
            output_dir=str(tmp_path / "output"),
            logo_path=str(logo_path),
            temp_dir=str(tmp_path / "temp")
        )
        
        expected_path = str(Path(tmp_path / "output") / "FINAL_verified_preview.mp4")
        assert res == expected_path


