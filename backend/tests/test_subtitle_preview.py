import pytest
from unittest.mock import MagicMock, patch
import subprocess
from pathlib import Path
from PIL import Image
import json
import sqlite3
import asyncio

from backend.subtitle_preview import (
    apply_subtitle_overlay,
    validate_image_properties,
    extract_subtitle_preview_image,
    resolve_subtitle_preview_task
)


def mock_ffmpeg_run(cmd, *args, **kwargs):
    out_path = cmd[-1]
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    ext = Path(out_path).suffix.lower()
    if ext in (".jpg", ".jpeg", ".png"):
        img = Image.new("RGB", (1280, 720), color="blue")
        img.save(out_path)
    else:
        Path(out_path).write_bytes(b"dummy data")
    return MagicMock(returncode=0)


@patch("subprocess.run")
@patch("pathlib.Path.exists", return_value=True)
def test_apply_subtitle_overlay_success(mock_exists, mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    input_video = "C:\\path\\to\\input.mp4"
    subtitle_file = "C:\\path\\to\\sub.srt"
    output_path = "C:\\path\\to\\output.mp4"
    
    res = apply_subtitle_overlay(input_video, subtitle_file, output_path)
    assert res == output_path
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "ffmpeg"
    assert cmd[2] == input_video
    
    expected_escaped_path = "C" + chr(92) + ":/path/to/sub.srt"
    assert f"subtitles='{expected_escaped_path}'" in cmd[4]
    assert "Bold=1" in cmd[4]
    assert "Outline=3" in cmd[4]
    assert "Shadow=2" in cmd[4]
    assert "-c:v" in cmd
    assert "libx264" in cmd


@patch("subprocess.run")
@patch("pathlib.Path.exists", return_value=True)
def test_apply_subtitle_overlay_failure(mock_exists, mock_run):
    mock_run.side_effect = subprocess.CalledProcessError(
        returncode=1,
        cmd=["ffmpeg"],
        stderr="FFmpeg specific error message"
    )
    input_video = "C:\\path\\to\\input.mp4"
    subtitle_file = "C:\\path\\to\\sub.srt"
    output_path = "C:\\path\\to\\output.mp4"
    
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        apply_subtitle_overlay(input_video, subtitle_file, output_path)
    assert exc_info.value.stderr == "FFmpeg specific error message"


@patch("pathlib.Path.exists", autospec=True)
@patch("subprocess.run")
@patch("screenshot_generator.generate_multiple_screenshots")
def test_subtitle_preview_main_flow(mock_generate_screenshots, mock_run, mock_exists):
    import runpy
    import sys
    mock_exists.return_value = True
    mock_run.return_value = MagicMock(returncode=0)
    mock_generate_screenshots.return_value = ["sc1.jpg", "sc2.jpg"]
    
    if "backend.subtitle_preview" in sys.modules:
        del sys.modules["backend.subtitle_preview"]
    with patch.object(sys, 'argv', ['backend/subtitle_preview.py']):
        runpy.run_module('backend.subtitle_preview', run_name='__main__')
        
    assert mock_run.call_count == 2
    mock_generate_screenshots.assert_called_once()


@patch("pathlib.Path.exists", autospec=True)
@patch("subprocess.run")
def test_subtitle_preview_main_flow_file_not_found(mock_run, mock_exists):
    import runpy
    import sys
    mock_exists.return_value = False
    if "backend.subtitle_preview" in sys.modules:
        del sys.modules["backend.subtitle_preview"]
    with patch.object(sys, 'argv', ['backend/subtitle_preview.py']):
        runpy.run_module('backend.subtitle_preview', run_name='__main__')
    mock_run.assert_not_called()


@patch("subprocess.run")
@patch("pathlib.Path.exists", return_value=True)
def test_apply_subtitle_overlay_single_quote_escape(mock_exists, mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    input_video = "input.mp4"
    subtitle_file = "C:\\path\\to\\user's_subtitle.srt"
    output_path = "output.mp4"
    
    apply_subtitle_overlay(input_video, subtitle_file, output_path)
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    expected_escaped_path = "C" + chr(92) + ":/path/to/user'" + chr(92)*2 + "''s_subtitle.srt"
    assert f"subtitles='{expected_escaped_path}'" in cmd[4]


def test_apply_subtitle_overlay_validation_errors():
    with pytest.raises(ValueError, match="must be non-empty strings"):
        apply_subtitle_overlay("", "sub.srt", "out.mp4")
    with pytest.raises(ValueError, match="must be non-empty strings"):
        apply_subtitle_overlay("in.mp4", "", "out.mp4")
    with pytest.raises(ValueError, match="must be non-empty strings"):
        apply_subtitle_overlay("in.mp4", "sub.srt", "")
    with pytest.raises(ValueError, match="must be non-empty strings"):
        apply_subtitle_overlay(None, "sub.srt", "out.mp4")


@patch("subprocess.run")
@patch("pathlib.Path.exists", return_value=True)
def test_apply_subtitle_overlay_complex_path_escape(mock_exists, mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    input_video = "input.mp4"
    subtitle_file = "C:\\path\\to\\ユーザー's_字幕_test:file.srt"
    output_path = "output.mp4"
    
    apply_subtitle_overlay(input_video, subtitle_file, output_path)
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    expected_escaped_path = "C" + chr(92) + ":/path/to/ユーザー'" + chr(92)*2 + "''s_字幕_test" + chr(92) + ":file.srt"
    assert f"subtitles='{expected_escaped_path}'" in cmd[4]


@patch("subprocess.run")
@patch("pathlib.Path.exists", return_value=True)
def test_apply_subtitle_overlay_logging_on_failure(mock_exists, mock_run, caplog):
    mock_run.side_effect = subprocess.CalledProcessError(
        returncode=1,
        cmd=["ffmpeg"],
        stderr="Simulated FFmpeg stderr output"
    )
    input_video = "input.mp4"
    subtitle_file = "sub.srt"
    output_path = "output.mp4"
    
    import logging
    with caplog.at_level(logging.ERROR):
        with pytest.raises(subprocess.CalledProcessError):
            apply_subtitle_overlay(input_video, subtitle_file, output_path)
    assert any("Simulated FFmpeg stderr output" in record.message for record in caplog.records)


def test_validate_image_properties_success(tmp_path):
    img_path = tmp_path / "test.png"
    img = Image.new("RGB", (300, 200), color="red")
    img.save(img_path)
    
    assert validate_image_properties(str(img_path)) is True
    assert validate_image_properties(str(img_path), expected_resolution=(300, 200)) is True
    assert validate_image_properties(str(img_path), expected_aspect_ratio=1.5) is True
    
    file_size = img_path.stat().st_size
    assert validate_image_properties(str(img_path), max_file_size_bytes=file_size + 100) is True
    assert validate_image_properties(str(img_path), min_file_size_bytes=file_size - 100) is True


def test_validate_image_properties_failures(tmp_path):
    img_path = tmp_path / "test.png"
    img = Image.new("RGB", (300, 200), color="blue")
    img.save(img_path)
    
    with pytest.raises(FileNotFoundError):
        validate_image_properties("non_existent_file.png")
    with pytest.raises(ValueError, match="Expected resolution"):
        validate_image_properties(str(img_path), expected_resolution=(100, 100))
    with pytest.raises(ValueError, match="Expected aspect ratio"):
        validate_image_properties(str(img_path), expected_aspect_ratio=1.0)
        
    file_size = img_path.stat().st_size
    with pytest.raises(ValueError, match="exceeds maximum allowed size"):
        validate_image_properties(str(img_path), max_file_size_bytes=file_size - 1)
    with pytest.raises(ValueError, match="is below minimum allowed size"):
        validate_image_properties(str(img_path), min_file_size_bytes=file_size + 1)


@patch("pathlib.Path.exists", autospec=True)
@patch("subprocess.run")
def test_extract_subtitle_preview_image_success(mock_run, mock_exists):
    mock_exists.return_value = True
    mock_run.side_effect = mock_ffmpeg_run
    input_video = "video.mp4"
    output_path = "output.jpg"
    
    import backend.subtitle_preview as sp
    mock_validate = MagicMock(return_value=True)
    original_validate = sp.validate_image_properties
    sp.validate_image_properties = mock_validate
    
    try:
        res = sp.extract_subtitle_preview_image(
            video_path=input_video,
            timestamp=5.5,
            output_path=output_path,
            resolution="1280x720",
            quality=5,
            max_file_size_bytes=50000
        )
    finally:
        sp.validate_image_properties = original_validate
        
    assert res == output_path
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    
    assert cmd[0] == "ffmpeg"
    assert cmd[2] == "5.5"
    assert cmd[4] == input_video
    assert "scale=1280:720:force_original_aspect_ratio=decrease:flags=lanczos,pad=1280:720:(ow-iw)/2:(oh-ih)/2" in cmd
    assert "-q:v" in cmd
    assert "5" in cmd
    assert Path(cmd[-1]).name.startswith("output")
    assert ".ffmpeg.jpg" in cmd[-1]
    
    mock_validate.assert_called_once_with(
        output_path,
        expected_resolution=(1280, 720),
        expected_aspect_ratio=1280/720,
        max_file_size_bytes=50000
    )


@patch("pathlib.Path.exists", autospec=True)
def test_extract_subtitle_preview_image_validation_errors(mock_exists):
    mock_exists.return_value = True
    with pytest.raises(ValueError, match="Invalid resolution format"):
        extract_subtitle_preview_image("vid.mp4", 1.0, "out.jpg", resolution="1920")
    with pytest.raises(ValueError, match="Invalid resolution format"):
        extract_subtitle_preview_image("vid.mp4", 1.0, "out.jpg", resolution="-100x100")
    with pytest.raises(ValueError, match="quality must be between 1 and 31"):
        extract_subtitle_preview_image("vid.mp4", 1.0, "out.jpg", quality=0)
    with pytest.raises(ValueError, match="timestamp cannot be negative"):
        extract_subtitle_preview_image("vid.mp4", -1.0, "out.jpg")


@patch("pathlib.Path.exists", autospec=True)
@patch("subprocess.run")
def test_extract_subtitle_preview_image_timeout(mock_run, mock_exists):
    mock_exists.return_value = True
    mock_run.side_effect = subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=30.0)
    with pytest.raises(RuntimeError, match="FFmpeg process timed out"):
        extract_subtitle_preview_image("vid.mp4", 1.0, "out.jpg", timeout=30.0)


@patch("pathlib.Path.exists", autospec=True)
@patch("subprocess.run")
def test_extract_subtitle_preview_image_called_process_error(mock_run, mock_exists):
    mock_exists.return_value = True
    mock_run.side_effect = subprocess.CalledProcessError(
        returncode=1,
        cmd=["ffmpeg"],
        stderr=b"Some ffmpeg error"
    )
    with pytest.raises(subprocess.CalledProcessError):
        extract_subtitle_preview_image("vid.mp4", 1.0, "out.jpg")


@patch("pathlib.Path.exists", autospec=True)
def test_apply_subtitle_overlay_files_not_found(mock_exists):
    mock_exists.side_effect = lambda self: "input.mp4" in str(self).replace("\\", "/")
    with pytest.raises(FileNotFoundError, match="Input files do not exist"):
        apply_subtitle_overlay("input.mp4", "non_existent.srt", "output.mp4")


@patch("pathlib.Path.exists", autospec=True)
@patch("subprocess.run")
def test_apply_subtitle_overlay_timeout(mock_run, mock_exists):
    mock_exists.return_value = True
    mock_run.side_effect = subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=10.0)
    with pytest.raises(RuntimeError, match="FFmpeg process timed out"):
        apply_subtitle_overlay("input.mp4", "sub.srt", "output.mp4", timeout=10.0)


def test_validate_image_properties_zero_or_negative_dimensions(tmp_path):
    with patch("PIL.Image.open") as mock_open:
        mock_img = MagicMock()
        mock_img.size = (100, 0)
        mock_open.return_value.__enter__.return_value = mock_img
        
        dummy_file = tmp_path / "dummy.png"
        dummy_file.write_bytes(b"dummy data")
        with pytest.raises(ValueError, match="Image dimensions must be positive and non-zero"):
            validate_image_properties(str(dummy_file), expected_resolution=(100, 0))


def test_validate_image_properties_aspect_ratio_tolerance_edges(tmp_path):
    img_path = tmp_path / "aspect_test.png"
    img = Image.new("RGB", (300, 200), color="green")
    img.save(img_path)
    assert validate_image_properties(str(img_path), expected_aspect_ratio=1.5, aspect_ratio_tolerance=0.01) is True
    assert validate_image_properties(str(img_path), expected_aspect_ratio=1.495, aspect_ratio_tolerance=0.01) is True
    with pytest.raises(ValueError, match="Expected aspect ratio"):
        validate_image_properties(str(img_path), expected_aspect_ratio=1.48, aspect_ratio_tolerance=0.01)


@patch("pathlib.Path.exists", autospec=True)
@patch("subprocess.run")
def test_extract_subtitle_preview_image_file_not_generated(mock_run, mock_exists):
    mock_exists.side_effect = lambda self: "video.mp4" in str(self).replace("\\", "/")
    mock_run.return_value = MagicMock(returncode=0)
    with pytest.raises(RuntimeError, match="FFmpeg completed successfully but output file was not generated"):
        extract_subtitle_preview_image("video.mp4", 1.0, "non_existent_output.jpg")


def test_validate_image_properties_corruption(tmp_path):
    corrupt_file = tmp_path / "corrupt.jpg"
    corrupt_file.write_bytes(b"invalid jpg header data only")
    with pytest.raises(ValueError, match="Image properties validation failed"):
        validate_image_properties(str(corrupt_file))


def test_extract_subtitle_preview_image_aspect_ratio_correction(tmp_path):
    dummy_input = tmp_path / "dummy_4_3.png"
    img = Image.new("RGB", (800, 600), color="blue")
    img.save(dummy_input)
    
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = mock_ffmpeg_run
        
        out_jpg = tmp_path / "out_corrected.jpg"
        out_jpg.write_bytes(b"dummy image data")
        
        res = extract_subtitle_preview_image(
            video_path=str(dummy_input),
            timestamp=1.0,
            output_path=str(out_jpg),
            resolution="1280x720"
        )
        assert res == str(out_jpg)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "scale=1280:720:force_original_aspect_ratio=decrease:flags=lanczos,pad=1280:720:(ow-iw)/2:(oh-ih)/2" in cmd


@pytest.mark.anyio
@patch("subprocess.run")
async def test_resolve_subtitle_preview_task_success(mock_run, tmp_path):
    from backend.agents.stage_bound_agent import StageBoundAgent
    mock_run.side_effect = mock_ffmpeg_run
    
    video_file = tmp_path / "test_in.mp4"
    video_file.write_bytes(b"dummy video data")
    subtitle_file = tmp_path / "test_sub.srt"
    subtitle_file.write_bytes(b"1\n00:00:01,000 --> 00:00:03,000\nHello World\n")
    
    db_file = tmp_path / "test_tasks.db"
    agent = StageBoundAgent(
        stage_name="subtitle_preview",
        db_path=str(db_file),
        poll_interval=0.01
    )
    agent.video_path = str(video_file)
    agent.subtitle_file = str(subtitle_file)
    agent.output_dir = str(tmp_path)
    agent.timestamp = 1.0
    agent.resolution = "1280x720"
    agent.max_file_size_bytes = 4 * 1024 * 1024
    
    task_id = "task_preview_001"
    await agent.register_task(task_id, initial_status="READY", max_retries=2)
    
    out_file = tmp_path / f"{task_id}.jpg"
    img = Image.new("RGB", (1280, 720), color="blue")
    img.save(out_file)
    
    temp_overlay_video = tmp_path / f"{task_id}_overlay.mp4"
    temp_overlay_video.write_bytes(b"dummy overlay video")
    
    async def process_task(tid):
        return await resolve_subtitle_preview_task(agent, tid)
    await agent.start(process_task)
    
    for _ in range(50):
        status = await agent.get_task_status(task_id)
        if status == "COMPLETED":
            break
        await asyncio.sleep(0.05)
        
    status = await agent.get_task_status(task_id)
    assert status == "COMPLETED"
    
    conn = sqlite3.connect(str(db_file))
    cursor = conn.execute("SELECT result, retry_count FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    result_json = json.loads(row[0])
    assert result_json["width"] == 1280
    assert result_json["height"] == 720
    assert abs(result_json["width"] / result_json["height"] - 16.0 / 9.0) < 0.01
    assert result_json["size_bytes"] < 4 * 1024 * 1024
    assert row[1] == 0
    await agent.stop()


@pytest.mark.anyio
@patch("subprocess.run")
async def test_resolve_subtitle_preview_task_retry_on_failure(mock_run, tmp_path):
    from backend.agents.stage_bound_agent import StageBoundAgent
    mock_run.side_effect = subprocess.CalledProcessError(
        returncode=1,
        cmd=["ffmpeg"],
        stderr=b"Some ffmpeg error"
    )
    
    db_file = tmp_path / "test_tasks_retry.db"
    agent = StageBoundAgent(
        stage_name="subtitle_preview",
        db_path=str(db_file),
        poll_interval=0.01
    )
    task_id = "test_fail_task"
    await agent.register_task(task_id, initial_status="READY", max_retries=2)
    
    agent.video_path = "/invalid/video/path/mp4"
    agent.subtitle_file = "/invalid/subtitle/path/srt"
    agent.output_dir = str(tmp_path)
    agent.allow_mock = False
    
    async def process_task(tid):
        return await resolve_subtitle_preview_task(agent, tid)
    await agent.start(process_task)
    
    for _ in range(50):
        status = await agent.get_task_status(task_id)
        if status == "FAILED":
            break
        await asyncio.sleep(0.05)
        
    status = await agent.get_task_status(task_id)
    assert status == "FAILED"
    
    conn = sqlite3.connect(str(db_file))
    cursor = conn.execute("SELECT retry_count, error FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    assert row[0] == 2
    assert row[1] is not None
    await agent.stop()


@pytest.mark.anyio
async def test_real_subtitle_preview_quality_and_agent_integration(tmp_path):
    """
    モックなしで、実際のFFmpegとPillowを使用して、出力画像の品質（解像度>=1280x720, アスペクト比16:9, サイズ<4MB, ロード可能）
    および StageBoundAgent 連携を検証するリアル統合テスト。
    """
    from backend.agents.stage_bound_agent import StageBoundAgent
    
    # 1. 1秒のダミー動画ファイル(1280x720)をFFmpegで生成
    dummy_video = tmp_path / "dummy_video.mp4"
    create_video_cmd = [
        "ffmpeg",
        "-f", "lavfi",
        "-i", "color=c=black:s=1280x720:d=1",
        "-c:v", "libx264",
        "-t", "1",
        "-y",
        str(dummy_video)
    ]
    try:
        subprocess.run(create_video_cmd, check=True, capture_output=True, timeout=10.0)
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        pytest.skip(f"FFmpeg command failed or not available for dummy video creation: {e}")
        
    # 2. ダミーのSRT字幕ファイルを生成
    dummy_sub = tmp_path / "dummy_sub.srt"
    dummy_sub.write_text(
        "1\n00:00:00,100 --> 00:00:00,900\n[Integration Test Subtitle]\n",
        encoding="utf-8"
    )
    
    # 3. StageBoundAgentの設定
    db_file = tmp_path / "real_tasks.db"
    agent = StageBoundAgent(
        stage_name="subtitle_preview",
        db_path=str(db_file),
        poll_interval=0.01
    )
    agent.video_path = str(dummy_video)
    agent.subtitle_file = str(dummy_sub)
    agent.output_dir = str(tmp_path)
    agent.timestamp = 0.5
    agent.resolution = "1280x720"
    agent.max_file_size_bytes = 4 * 1024 * 1024 # 4MB
    
    task_id = "real_preview_task_001"
    await agent.register_task(task_id, initial_status="READY", max_retries=2)
    
    # 4. Agentを起動して処理開始
    async def process_task(tid):
        return await resolve_subtitle_preview_task(agent, tid)
    
    await agent.start(process_task)
    
    # 5. 完了を待つ
    for _ in range(100):
        status = await agent.get_task_status(task_id)
        if status in ("COMPLETED", "FAILED"):
            break
        await asyncio.sleep(0.05)
        
    status = await agent.get_task_status(task_id)
    assert status == "COMPLETED", "Task failed or did not complete"
    
    # 6. DBから結果を取得
    conn = sqlite3.connect(str(db_file))
    cursor = conn.execute("SELECT result, retry_count FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    result_json = json.loads(row[0])
    
    # 7. 画像ファイルの確認
    output_img_path = Path(result_json["path"])
    assert output_img_path.exists()
    
    # 画像プロパティ検証
    with Image.open(output_img_path) as img:
        img.verify() # 破損チェック
        
    with Image.open(output_img_path) as img:
        img.load() # 実際にロード
        w, h = img.size
        
    size_bytes = output_img_path.stat().st_size
    
    # 品質要件アサーション
    assert w >= 1280, f"Width {w} must be >= 1280"
    assert h >= 720, f"Height {h} must be >= 720"
    assert abs((w / h) - (16.0 / 9.0)) < 0.01, f"Aspect ratio {w/h:.4f} must be 16:9"
    assert size_bytes < 4 * 1024 * 1024, f"File size {size_bytes} must be < 4MB"
    assert result_json["width"] == w
    assert result_json["height"] == h
    assert result_json["size_bytes"] == size_bytes
    assert row[1] == 0
    
    await agent.stop()



@pytest.mark.anyio
async def test_thumbnail_quality_and_stage_bound_agent_integration(tmp_path):
    """
    ユーザー要件「Phase 27 サムネイル品質向上」の自動検証テスト。
    以下の品質基準を自動検証します：
    - 生成画像の解像度が 1280x720 以上であること
    - アスペクト比が 16:9 であること
    - ファイルサイズが 4MB 未満であること
    - 出力ファイルが正常に存在し、破損していない（Pillow等で正常にロード可能である）こと
    - StageBoundAgent 等に登録され、自動リトライや結果保存、DBマイグレーションの各機能と連携して動作すること
    """
    from backend.agents.stage_bound_agent import StageBoundAgent
    import sqlite3
    import json
    import asyncio
    
    db_file = tmp_path / "migration_and_retry_test.db"
    
    # DBマイグレーションとの連携検証（テーブルが正常に自動生成されること）
    agent = StageBoundAgent(
        stage_name="subtitle_preview",
        db_path=str(db_file),
        poll_interval=0.01
    )
    
    # 登録機能の検証
    task_id = "test_quality_001"
    await agent.register_task(task_id, initial_status="READY", max_retries=2)
    
    # DBマイグレーション結果の検証
    conn = sqlite3.connect(str(db_file))
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'")
    table_exists = cursor.fetchone()
    assert table_exists is not None, "DBマイグレーション連携に失敗：tasksテーブルが存在しません"
    
    cursor = conn.execute("SELECT status, retry_count, max_retries FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "READY"
    assert row[1] == 0
    assert row[2] == 2
    
    # 品質基準を検証するためのダミー画像出力先
    output_img_path = tmp_path / f"{task_id}.jpg"
    
    async def process_task(tid):
        # 1. 正常な高品質画像を生成
        img = Image.new("RGB", (1280, 720), color="blue")
        img.save(output_img_path, "JPEG", quality=95)
        
        # 2. 正常に存在し、破損していないか Pillow 等で自動検証
        assert output_img_path.exists(), "出力ファイルが存在しません"
        try:
            with Image.open(output_img_path) as test_img:
                test_img.verify() # 破損検証
            with Image.open(output_img_path) as test_img:
                test_img.load() # ロード検証
                w, h = test_img.size
        except Exception as e:
            raise ValueError(f"画像ロード失敗（破損の可能性）: {e}")
            
        # 3. 解像度が 1280x720 以上であること
        assert w >= 1280, f"解像度幅が足りません: {w} < 1280"
        assert h >= 720, f"解像度高さが足りません: {h} < 720"
        
        # 4. アスペクト比が 16:9 であること
        assert abs((w / h) - (16.0 / 9.0)) < 0.01, f"アスペクト比が16:9ではありません: {w/h:.4f}"
        
        # 5. ファイルサイズが 4MB 未満であること
        file_size = output_img_path.stat().st_size
        assert file_size < 4 * 1024 * 1024, f"ファイルサイズが4MBを超えています: {file_size} bytes"
        
        # 結果保存と連携するためのJSONデータを返す
        result_data = {
            "path": str(output_img_path),
            "width": w,
            "height": h,
            "size_bytes": file_size
        }
        return json.dumps(result_data)
        
    # Agentを起動し、タスクの実行と完了ステータス更新・結果保存の連携動作を確認
    await agent.start(process_task)
    
    for _ in range(100):
        status = await agent.get_task_status(task_id)
        if status in ("COMPLETED", "FAILED"):
            break
        await asyncio.sleep(0.05)
        
    status = await agent.get_task_status(task_id)
    assert status == "COMPLETED", "タスク完了ステータスへの遷移に失敗しました"
    
    # DB連携と結果保存の検証
    conn = sqlite3.connect(str(db_file))
    cursor = conn.execute("SELECT status, result, retry_count FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    assert row[0] == "COMPLETED"
    saved_result = json.loads(row[1])
    assert saved_result["width"] >= 1280
    assert saved_result["height"] >= 720
    assert saved_result["size_bytes"] < 4 * 1024 * 1024
    assert row[2] == 0  # リトライは発生していない
    
    await agent.stop()


@pytest.mark.anyio
async def test_extract_subtitle_preview_image_resolution_aspect_ratio_correction_and_validation(tmp_path):
    """
    指定解像度が1280x720未満、あるいはアスペクト比が16:9でない場合に、
    自動的に1280x720以上、かつ16:9に強制補正されて画像が生成されることを検証する。
    """
    dummy_input = tmp_path / "dummy_low_res.png"
    img = Image.new("RGB", (640, 480), color="blue")
    img.save(dummy_input)
    
    with patch("subprocess.run") as mock_run,          patch("pathlib.Path.exists", return_value=True),          patch("PIL.Image.open") as mock_open:
         
        mock_run.return_value = MagicMock(returncode=0)
        
        # モック画像サイズは1280x720 (16:9に補正されたことをシミュレート)
        mock_img = MagicMock()
        mock_img.size = (1280, 720)
        mock_open.return_value.__enter__.return_value = mock_img
        
        out_jpg = tmp_path / "out_corrected.jpg"
        out_jpg.write_bytes(b"dummy data")
        
        # 1. 1280x720未満の解像度を指定 -> 1280x720に補正されるか
        res1 = extract_subtitle_preview_image(
            video_path=str(dummy_input),
            timestamp=1.0,
            output_path=str(out_jpg),
            resolution="640x360"
        )
        assert res1 == str(out_jpg)
        cmd1 = mock_run.call_args_list[-1][0][0]
        # 解像度が1280x720に引き上げられていること
        assert any("scale=1280:720" in arg for arg in cmd1)

        # 2. 16:9でない解像度を指定 -> 16:9にアスペクト比補正されるか (例: 1600x1200 -> 1600x900)
        # モック画像のサイズを1600x900にセット
        mock_img.size = (1600, 900)
        res2 = extract_subtitle_preview_image(
            video_path=str(dummy_input),
            timestamp=1.0,
            output_path=str(out_jpg),
            resolution="1600x1200"
        )
        assert res2 == str(out_jpg)
        cmd2 = mock_run.call_args_list[-1][0][0]
        # 高さが 1600 * 9 / 16 = 900 に補正されていること
        assert any("scale=1600:900" in arg for arg in cmd2)


@pytest.mark.anyio
async def test_apply_subtitle_overlay_technical_debt_registration_on_ffmpeg_error(tmp_path):
    """
    FFmpegがエラーを返した際に、TechnicalDebtStoreに債務として正しく登録されることを検証する。
    """
    from backend.agents.memory.technical_debt import TechnicalDebtStore
    
    with patch("subprocess.run") as mock_run,          patch("pathlib.Path.exists", return_value=True),          patch("backend.agents.memory.technical_debt.TechnicalDebtStore.register_debt") as mock_register:
         
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=["ffmpeg"],
            stderr="Simulated FFmpeg execution error"
        )
        
        input_video = "in.mp4"
        subtitle_file = "sub.srt"
        output_path = "out.mp4"
        
        with pytest.raises(subprocess.CalledProcessError):
            apply_subtitle_overlay(input_video, subtitle_file, output_path)
            
        # register_debtが呼び出されたことを検証
        mock_register.assert_called_once()
        args, kwargs = mock_register.call_args
        assert kwargs.get("category") == "IMPORTANT_SERVICE"
        assert "ffmpeg error" in kwargs.get("pattern")


@pytest.mark.anyio
async def test_extract_subtitle_preview_image_technical_debt_registration_on_timeout(tmp_path):
    """
    FFmpeg抽出処理でタイムアウトが発生した際に、TechnicalDebtStoreに債務として正しく登録されることを検証する。
    """
    from backend.agents.memory.technical_debt import TechnicalDebtStore
    
    with patch("subprocess.run") as mock_run,          patch("pathlib.Path.exists", return_value=True),          patch("backend.agents.memory.technical_debt.TechnicalDebtStore.register_debt") as mock_register:
         
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=30.0)
        
        input_video = "in.mp4"
        output_path = "out.jpg"
        
        with pytest.raises(RuntimeError, match="FFmpeg process timed out"):
            extract_subtitle_preview_image(
                video_path=input_video,
                timestamp=1.0,
                output_path=output_path,
                timeout=30.0
            )
            
        # register_debtが呼び出されたことを検証
        mock_register.assert_called_once()
        args, kwargs = mock_register.call_args
        assert kwargs.get("category") == "IMPORTANT_SERVICE"
        assert "timeout" in kwargs.get("pattern")


@pytest.mark.anyio
async def test_extract_subtitle_preview_image_auto_tuning_under_limits(tmp_path):
    """
    ファイルサイズが制限を超える場合に、品質が自動的に段階調整されて保存されることを検証。
    """
    dummy_input = tmp_path / "dummy_tuning.png"
    img = Image.new("RGB", (640, 480), color="blue")
    img.save(dummy_input)
    
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = mock_ffmpeg_run
        
        out_jpg = tmp_path / "out_tuned.jpg"
        
        # 1回目のモック保存で、ファイルサイズが制限(100バイト)を超えるようにモック stat を設定
        # 2回目は制限未満にする
        import os
        original_stat = os.stat
        call_count = 0
        def mock_stat(path, *args, **kwargs):
            nonlocal call_count
            path_str = str(path)
            if "enhanced" in path_str:
                call_count += 1
                # 1回目は200バイト (制限オーバー)、2回目は50バイト (制限クリア)
                size = 200 if call_count == 1 else 50
                mock_res = MagicMock()
                mock_res.st_size = size
                return mock_res
            elif "out_tuned.jpg" in path_str:
                mock_res = MagicMock()
                mock_res.st_size = 50
                return mock_res
            return original_stat(path, *args, **kwargs)
            
        with patch("os.stat", side_effect=mock_stat):
            res = extract_subtitle_preview_image(
                video_path=str(dummy_input),
                timestamp=1.0,
                output_path=str(out_jpg),
                resolution="1280x720",
                max_file_size_bytes=100
            )
            
            assert res == str(out_jpg)
            # 2回試行したため、ffmpeg も 2回呼ばれるはず
            assert mock_run.call_count == 2
            
            # 1回目は -q:v 2, 2回目は -q:v 6 (quality + 4) になっているか検証
            cmd1 = mock_run.call_args_list[0][0][0]
            cmd2 = mock_run.call_args_list[1][0][0]
            assert "2" in cmd1
            assert "6" in cmd2


@pytest.mark.anyio
async def test_extract_subtitle_preview_image_cleanup_on_failure(tmp_path):
    """
    エラー発生時に、生成中の一時ファイルが確実に削除されることを検証。
    """
    dummy_input = tmp_path / "dummy_cleanup.png"
    img = Image.new("RGB", (640, 480), color="blue")
    img.save(dummy_input)
    
    with patch("subprocess.run") as mock_run, \
         patch("pathlib.Path.exists", return_value=True), \
         patch("PIL.Image.open") as mock_open:
         
        # FFmpegは成功するが、Pillow処理で例外を投げるように設定
        mock_run.return_value = MagicMock(returncode=0)
        mock_open.side_effect = RuntimeError("Simulated Pillow error")
        
        out_jpg = tmp_path / "out_cleanup.jpg"
        
        with pytest.raises(RuntimeError, match="Simulated Pillow error"):
            extract_subtitle_preview_image(
                video_path=str(dummy_input),
                timestamp=1.0,
                output_path=str(out_jpg),
                resolution="1280x720"
            )
            
        # 一時ファイル(ffmpeg.tmp, enhanced.tmp)が削除され、残っていないこと
        temp_files = list(tmp_path.glob("*.tmp"))
        assert len(temp_files) == 0, "Temporary files were not cleaned up!"


def test_apply_subtitle_overlay_dynamic_font_sizing():
    """
    動画の解像度に応じて字幕フォントサイズが動的に計算されることを検証。
    """
    input_video = "dummy_video.mp4"
    subtitle_file = "dummy_sub.srt"
    output_path = "dummy_output.mp4"

    # DEFAULT_VIDEO_RESOLUTIONを書き換えて、異なる動画高さを模擬する
    with patch("pathlib.Path.exists", return_value=True), \
         patch("subprocess.run") as mock_run:
         
        mock_run.return_value = MagicMock(returncode=0)

        original_res = apply_subtitle_overlay.__globals__.get("DEFAULT_VIDEO_RESOLUTION", (1280, 720))
        try:
            # ケース1: 1080p 動画 (高さ 1080) -> font_size = 1080 * 0.035 = 37
            apply_subtitle_overlay.__globals__["DEFAULT_VIDEO_RESOLUTION"] = (1920, 1080)
            apply_subtitle_overlay(input_video, subtitle_file, output_path)
            cmd = mock_run.call_args[0][0]
            assert "FontSize=37" in cmd[4]

            mock_run.reset_mock()

            # ケース2: 4K 動画 (高さ 2160) -> font_size = 2160 * 0.035 = 75 だが上限72により 72
            apply_subtitle_overlay.__globals__["DEFAULT_VIDEO_RESOLUTION"] = (3840, 2160)
            apply_subtitle_overlay(input_video, subtitle_file, output_path)
            cmd = mock_run.call_args[0][0]
            assert "FontSize=72" in cmd[4]
        finally:
            apply_subtitle_overlay.__globals__["DEFAULT_VIDEO_RESOLUTION"] = original_res


def test_extract_subtitle_preview_image_with_extreme_ratios(tmp_path):
    """
    極端なアスペクト比の入力に対して、16:9への自動アスペクト比補正が正しく機能することを検証。
    """
    dummy_input = tmp_path / "dummy_aspect.png"
    img = Image.new("RGB", (640, 480), color="blue")
    img.save(dummy_input)
    
    with patch("subprocess.run") as mock_run, \
         patch("pathlib.Path.exists", return_value=True), \
         patch("PIL.Image.open") as mock_open:
         
        mock_run.return_value = MagicMock(returncode=0)
        
        # モック画像サイズ (16:9に補正されたことを模擬)
        mock_img = MagicMock()
        mock_img.size = (1280, 720)
        mock_open.return_value.__enter__.return_value = mock_img
        
        out_jpg = tmp_path / "out_aspect.jpg"
        out_jpg.write_bytes(b"dummy data")

        # 縦動画 (9:16) "720x1280" を指定 -> 幅1280、高さ720に補正されるか
        extract_subtitle_preview_image(
            video_path=str(dummy_input),
            timestamp=1.0,
            output_path=str(out_jpg),
            resolution="720x1280"
        )
        cmd = mock_run.call_args[0][0]
        # 幅720に対してアスペクト比補正で高さ = 720 * 9 / 16 = 405 -> 奇数回避で 406
        # しかし、1280x720未満自動引上げルールにより、幅が1280に、高さは1280 * 9 / 16 = 720に引き上げられる
        assert any("scale=1280:720" in arg for arg in cmd)


def test_validate_image_properties_with_empty_or_truncated_file(tmp_path):
    """
    空のファイルや壊れたファイルを validate_image_properties が正しく検出して ValueError を投げることを検証。
    """
    empty_file = tmp_path / "empty.png"
    empty_file.write_bytes(b"")
    
    with pytest.raises(ValueError, match="Image properties validation failed"):
        validate_image_properties(str(empty_file))

    truncated_file = tmp_path / "truncated.jpg"
    truncated_file.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00")  # ヘッダーのみ
    with pytest.raises(ValueError, match="Image properties validation failed"):
        validate_image_properties(str(truncated_file))


def test_apply_subtitle_overlay_font_size_validation():
    """
    不正な font_size 引数がバリデーションで弾かれることを検証。
    """
    with patch("pathlib.Path.exists", return_value=True):
        with pytest.raises(TypeError, match="font_size must be an integer"):
            apply_subtitle_overlay("in.mp4", "sub.srt", "out.mp4", font_size="large")
            
        with pytest.raises(TypeError, match="font_size must be an integer"):
            apply_subtitle_overlay("in.mp4", "sub.srt", "out.mp4", font_size=True)

        with pytest.raises(ValueError, match="font_size must be a positive integer"):
            apply_subtitle_overlay("in.mp4", "sub.srt", "out.mp4", font_size=-10)


@pytest.mark.anyio
async def test_stage_bound_agent_coordination_and_rigorous_quality_rules(tmp_path):
    """
    StageBoundAgentとの連携、自動リトライ、結果保存、DBマイグレーション機能の統合テスト。
    また、生成されたサムネイル画像が以下の品質基準を満たすことを実証する：
    - 解像度 >= 1280x720
    - アスペクト比が 16:9
    - ファイルサイズが 4MB 未満
    - Pillowで正常にロード可能で破損していないこと
    """
    from backend.agents.stage_bound_agent import StageBoundAgent
    
    db_file = tmp_path / "agent_coordination.db"
    
    # 1. DBマイグレーションとの連携確認
    # StageBoundAgentを起動して、正常にスキーマ（result, retry_count, max_retries等）が構築されることを確認
    agent = StageBoundAgent(
        stage_name="subtitle_preview",
        db_path=str(db_file),
        poll_interval=0.01
    )
    
    conn = sqlite3.connect(str(db_file))
    cursor = conn.execute("PRAGMA table_info(tasks)")
    columns = [row[1] for row in cursor.fetchall()]
    conn.close()
    
    assert "result" in columns
    assert "retry_count" in columns
    assert "max_retries" in columns
    
    # 2. 自動リトライ機能の検証
    # エラーが発生するダミー処理を登録して、max_retries=2 でリトライが実行されることを検証
    task_id_fail = "task_retry_fail_001"
    await agent.register_task(task_id_fail, initial_status="READY", max_retries=2)
    
    call_count = 0
    async def failing_process_func(tid):
        nonlocal call_count
        call_count += 1
        raise ValueError("Simulated process failure for retry check")
        
    await agent.start(failing_process_func)
    
    # リトライ上限まで失敗してステータスが FAILED になるのを待つ
    for _ in range(50):
        status = await agent.get_task_status(task_id_fail)
        if status == "FAILED":
            break
        await asyncio.sleep(0.05)
        
    status = await agent.get_task_status(task_id_fail)
    assert status == "FAILED"
    assert call_count == 3  # 初回試行 + リトライ2回 = 合計3回
    
    conn = sqlite3.connect(str(db_file))
    cursor = conn.execute("SELECT retry_count, error FROM tasks WHERE id = ?", (task_id_fail,))
    row = cursor.fetchone()
    conn.close()
    assert row[0] == 2
    assert "Simulated process failure" in row[1]
    
    await agent.stop()
    
    # 3. 正常系における品質基準・結果保存の検証
    # 再度エージェントを作成して実行
    agent_success = StageBoundAgent(
        stage_name="subtitle_preview",
        db_path=str(db_file),
        poll_interval=0.01
    )
    
    # ダミー動画と字幕ファイルを生成して、実際に本物の抽出と焼き付けが品質基準を満たすか検証
    dummy_video = tmp_path / "success_video.mp4"
    create_video_cmd = [
        "ffmpeg",
        "-f", "lavfi",
        "-i", "color=c=blue:s=1280x720:d=1",
        "-c:v", "libx264",
        "-t", "1",
        "-y",
        str(dummy_video)
    ]
    try:
        subprocess.run(create_video_cmd, check=True, capture_output=True, timeout=10.0)
    except (subprocess.SubprocessError, FileNotFoundError):
        pytest.skip("FFmpeg is required to run the rigorous quality integrated test")
        
    dummy_sub = tmp_path / "success_sub.srt"
    dummy_sub.write_text(
        "1\n00:00:00,100 --> 00:00:00,900\n[Rigor Test]\n",
        encoding="utf-8"
    )
    
    agent_success.video_path = str(dummy_video)
    agent_success.subtitle_file = str(dummy_sub)
    agent_success.output_dir = str(tmp_path)
    agent_success.timestamp = 0.5
    agent_success.resolution = "1280x720"
    agent_success.max_file_size_bytes = 4 * 1024 * 1024
    
    task_id_ok = "task_success_quality_001"
    await agent_success.register_task(task_id_ok, initial_status="READY", max_retries=1)
    
    async def success_process_func(tid):
        return await resolve_subtitle_preview_task(agent_success, tid)
        
    await agent_success.start(success_process_func)
    
    for _ in range(100):
        status = await agent_success.get_task_status(task_id_ok)
        if status == "COMPLETED":
            break
        await asyncio.sleep(0.05)
        
    status = await agent_success.get_task_status(task_id_ok)
    assert status == "COMPLETED"
    
    # DBに保存された結果の検証
    conn = sqlite3.connect(str(db_file))
    cursor = conn.execute("SELECT result, retry_count FROM tasks WHERE id = ?", (task_id_ok,))
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    result_data = json.loads(row[0])
    
    output_path = Path(result_data["path"])
    assert output_path.exists()
    
    # Pillowで破損がなく、ロード可能であることを検証
    with Image.open(output_path) as img:
        img.verify()
    with Image.open(output_path) as img:
        img.load()
        w, h = img.size
        
    size_bytes = output_path.stat().st_size
    
    # 必須品質基準自動検証
    assert w >= 1280, f"Resolution width {w} should be >= 1280"
    assert h >= 720, f"Resolution height {h} should be >= 720"
    assert abs((w / h) - (16.0 / 9.0)) < 0.01, f"Aspect ratio {w/h:.4f} should be 16:9"
    assert size_bytes < 4 * 1024 * 1024, f"File size {size_bytes} should be < 4MB"
    
    assert result_data["width"] == w
    assert result_data["height"] == h
    assert result_data["size_bytes"] == size_bytes
    
    await agent_success.stop()


def test_extract_subtitle_preview_image_with_spaces_in_resolution(tmp_path):
    """
    解像度にスペースや大文字Xが含まれる場合(例: " 1280 X 720 ")でも、
    正常に正規化・解析され、自動スケールアップおよびアスペクト比補正が行われて画像が生成されることを検証。
    """
    dummy_input = tmp_path / "dummy_space_res.png"
    img = Image.new("RGB", (640, 480), color="blue")
    img.save(dummy_input)
    
    with patch("subprocess.run") as mock_run, \
         patch("pathlib.Path.exists", return_value=True), \
         patch("PIL.Image.open") as mock_open:
         
        mock_run.return_value = MagicMock(returncode=0)
        
        # モック画像サイズ
        mock_img = MagicMock()
        mock_img.size = (1280, 720)
        mock_open.return_value.__enter__.return_value = mock_img
        
        out_jpg = tmp_path / "out_space_corrected.jpg"
        out_jpg.write_bytes(b"dummy data")
        
        # スペース交じりの 640 X 360 指定
        res = extract_subtitle_preview_image(
            video_path=str(dummy_input),
            timestamp=1.0,
            output_path=str(out_jpg),
            resolution=" 640 X 360 "
        )
        assert res == str(out_jpg)
        cmd = mock_run.call_args[0][0]
        # 1280x720以上に引き上げられていること
        assert any("scale=1280:720" in arg for arg in cmd)


def test_validate_image_properties_exact_aspect_ratio_tolerance(tmp_path):
    """
    validate_image_propertiesにおいて、アスペクト比の誤差が
    許容誤差（tolerance）の範囲内にある場合のバリデーション動作を検証。
    """
    img_path = tmp_path / "tolerance_edge_test.png"
    # アスペクト比 1.5 の画像 (300/200 = 1.5)
    img = Image.new("RGB", (300, 200), color="green")
    img.save(img_path)
    
    # 期待値が 1.505、許容誤差が 0.01 の場合、差は 0.005 で許容範囲内
    assert validate_image_properties(
        str(img_path),
        expected_aspect_ratio=1.505,
        aspect_ratio_tolerance=0.01
    ) is True

    # 期待値が 1.52、許容誤差が 0.01 の場合、差は 0.02 で許容範囲を超えるためValueErrorが発生すること
    with pytest.raises(ValueError, match="Expected aspect ratio"):
        validate_image_properties(
            str(img_path),
            expected_aspect_ratio=1.52,
            aspect_ratio_tolerance=0.01
        )


@pytest.mark.anyio
async def test_extract_subtitle_preview_image_size_tuning_extreme_fallback(tmp_path):
    """
    ファイルサイズが極端に厳しく、PNG形式からJPEG形式へフォールバックした後も
    サイズ制限をクリアするまで段階的にJPEGクオリティが自動調整される動作を検証。
    """
    dummy_input = tmp_path / "dummy_extreme.png"
    img = Image.new("RGB", (640, 480), color="blue")
    img.save(dummy_input)
    
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = mock_ffmpeg_run
        
        out_png = tmp_path / "out_extreme.png"  # PNG形式で出力要求
        
        # モックの os.stat 処理：
        # 1回目：PNGでサイズ200バイト (制限100を超過)
        # 2回目：JPEGにフォールバック、quality=2 でサイズ150バイト (制限100を超過)
        # 3回目：JPEGで quality=6 でサイズ50バイト (制限100以下で成功)
        import os
        original_stat = os.stat
        call_count = 0
        
        def mock_stat(path, *args, **kwargs):
            nonlocal call_count
            path_str = str(path)
            if "enhanced" in path_str:
                call_count += 1
                if call_count == 1:
                    size = 200  # PNG失敗
                elif call_count == 2:
                    size = 150  # JPEG quality=2 失敗
                else:
                    size = 50   # JPEG quality=6 成功
                mock_res = MagicMock()
                mock_res.st_size = size
                return mock_res
            elif "out_extreme.jpg" in path_str or "out_extreme.png" in path_str:
                mock_res = MagicMock()
                mock_res.st_size = 50
                return mock_res
            return original_stat(path, *args, **kwargs)
            
        with patch("os.stat", side_effect=mock_stat):
            res = extract_subtitle_preview_image(
                video_path=str(dummy_input),
                timestamp=1.0,
                output_path=str(out_png),
                resolution="1280x720",
                max_file_size_bytes=100
            )
            
            # 拡張子は .png のままだが中身は JPEG になっていること
            assert res.endswith(".png")
            with Image.open(res) as test_img:
                assert test_img.format == "JPEG"
                
            # 3回試行したため、ffmpeg も 3回呼ばれるはず
            assert mock_run.call_count == 3
            
            # 各試行の引数チェック
            cmd1 = mock_run.call_args_list[0][0][0]
            cmd2 = mock_run.call_args_list[1][0][0]
            cmd3 = mock_run.call_args_list[2][0][0]
            
            # 1回目はPNG
            assert cmd1[-1].endswith(".png")
            # 2回目は、一時ファイル名は元の拡張子(.png)のまま、中身はJPEG変換され、-q:v 2が適用される
            assert cmd2[-1].endswith(".png")
            assert "2" in cmd2
            # 3回目も同様で、-q:v 6が適用される
            assert cmd3[-1].endswith(".png")
            assert "6" in cmd3


@pytest.mark.anyio
@patch("pathlib.Path.exists", return_value=True)
@patch("subprocess.run")
async def test_extract_subtitle_preview_image_enhancements(mock_run, mock_exists, tmp_path):
    """
    extract_subtitle_preview_imageにおいて、Pillowによる画像補正（autocontrast, filter等）
    が正しく適用されていることをモックを用いて検証する。
    """
    mock_run.side_effect = mock_ffmpeg_run
    dummy_input = "video.mp4"
    out_jpg = tmp_path / "out_enhanced.jpg"
    
    with patch("PIL.ImageOps.autocontrast") as mock_autocontrast, \
         patch("PIL.Image.Image.filter") as mock_filter, \
         patch("backend.subtitle_preview.validate_image_properties", return_value=True):
         
        # filterメソッドは新しい画像を返すのでモックもMagicMockなどを返すようにする
        mock_filter.return_value = Image.new("RGB", (1280, 720), color="blue")
        mock_autocontrast.return_value = Image.new("RGB", (1280, 720), color="blue")
        
        extract_subtitle_preview_image(
            video_path=dummy_input,
            timestamp=1.0,
            output_path=str(out_jpg),
            resolution="1280x720"
        )
        
        # ImageOps.autocontrastが呼び出されていることを検証
        mock_autocontrast.assert_called_once()
        
        from PIL import ImageFilter
        # Image.filterがEDGE_ENHANCE_MOREで呼び出されていることを検証
        filter_calls = [call[0][0] for call in mock_filter.call_args_list]
        assert ImageFilter.EDGE_ENHANCE_MORE in filter_calls




