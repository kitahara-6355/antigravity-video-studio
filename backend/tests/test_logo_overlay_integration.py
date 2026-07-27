import os
import subprocess
import pytest
from PIL import Image
from logo_overlay import LogoOverlay

def test_logo_overlay_integration_metrics(tmp_path):
    """
    解像度/アスペクト比/ファイルサイズの実ファイル検証テスト
    """
    # 一時ファイルのパス設定
    dummy_video = str(tmp_path / "dummy_video.mp4")
    dummy_logo = str(tmp_path / "dummy_logo.png")
    output_image = str(tmp_path / "preview_out.jpg")
    output_video = str(tmp_path / "video_out.mp4")
    
    # 1. FFmpegで 320x240 (アスペクト比 4:3) のダミー動画を生成
    # (カラー: 青, 長さ: 2秒)
    video_cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", "color=c=blue:s=320x240:d=2",
        "-f", "lavfi",
        "-i", "anullsrc=r=44100:cl=stereo",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-pix_fmt", "yuv420p",
        "-t", "2",
        dummy_video
    ]
    subprocess.run(video_cmd, check=True, capture_output=True)
    
    # 2. FFmpegで 32x32 のダミーロゴ (PNG) を生成
    # (カラー: 赤)
    logo_cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", "color=c=red:s=32x32:d=1",
        "-vframes", "1",
        dummy_logo
    ]
    subprocess.run(logo_cmd, check=True, capture_output=True)
    
    overlay = LogoOverlay()
    
    # 3. プレビュー静画の生成
    res_image_path = overlay.generate_preview_image(
        input_video=dummy_video,
        logo_path=dummy_logo,
        output_image=output_image,
        position=(10, 10),
        opacity=0.8,
        target_height=16,
        time_offset=0.5
    )
    
    # 4. 生成結果の検証
    # (1) パスの存在確認
    assert os.path.exists(res_image_path)
    assert res_image_path == output_image
    
    # (2) ファイルサイズの検証 (0バイト以上、妥当なサイズ範囲内)
    file_size = os.path.getsize(output_image)
    assert file_size > 100, f"File size is too small: {file_size} bytes"
    assert file_size < 500000, f"File size is too large: {file_size} bytes"
    
    # (3) 解像度の検証 (Pillowを利用)
    with Image.open(output_image) as img:
        width, height = img.size
        assert width == 1280, f"Expected width 1280, got {width}"
        assert height == 720, f"Expected height 720, got {height}"
        
        # (4) アスペクト比の検証 (1280/720 = 16:9 = 1.777)
        aspect_ratio = width / height
        expected_ratio = 16.0 / 9.0
        assert abs(aspect_ratio - expected_ratio) < 1e-5, f"Expected aspect ratio {expected_ratio}, got {aspect_ratio}"

    # 5. 動画全体のロゴオーバーレイの検証
    res_video_path = overlay.apply_logo(
        input_video=dummy_video,
        logo_path=dummy_logo,
        output_path=output_video,
        position=(10, 10),
        opacity=0.8,
        target_height=16
    )
    assert os.path.exists(res_video_path)
    video_size = os.path.getsize(output_video)
    assert video_size > 1000, f"Video file is too small: {video_size} bytes"


import json
import asyncio
from agents.stage_bound_agent import StageBoundAgent

@pytest.mark.asyncio
async def test_logo_overlay_stage_bound_agent_integration(tmp_path):
    # テスト用DBパス
    db_path = str(tmp_path / "test_stage_agent.db")
    
    # 1. ダミー動画とダミーロゴの作成
    dummy_video = str(tmp_path / "dummy_video.mp4")
    dummy_logo = str(tmp_path / "dummy_logo.png")
    output_image = str(tmp_path / "preview_out.png")
    
    # FFmpegでダミー生成
    import subprocess
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=1",
        "-c:v", "libx264", "-t", "1", dummy_video
    ], check=True, capture_output=True)
    
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=16x16:d=1",
        "-vframes", "1", dummy_logo
    ], check=True, capture_output=True)
    
    # 2. StageBoundAgent の初期化
    agent = StageBoundAgent(stage_name="thumbnail_overlay", db_path=db_path, poll_interval=0.01)
    
    # 3. タスク関数の定義
    overlay = LogoOverlay()
    
    async def process_task(task_id: str) -> str:
        res = overlay.generate_preview_image(
            input_video=dummy_video,
            logo_path=dummy_logo,
            output_image=output_image,
            position=(10, 10),
            opacity=0.8,
            target_height=20,
            time_offset=0.1
        )
        
        # Pillowによるロード検証
        from pathlib import Path
        from PIL import Image
        img_path = Path(res)
        assert img_path.exists()
        size_bytes = img_path.stat().st_size
        assert size_bytes < 4 * 1024 * 1024
        
        with Image.open(img_path) as img:
            img.verify()
        with Image.open(img_path) as img:
            img.load()
            width, height = img.size
            
        assert width >= 1280
        assert height >= 720
        assert abs((width / height) - (16.0 / 9.0)) < 0.01
        
        return json.dumps({
            "status": "success",
            "path": res,
            "width": width,
            "height": height,
            "size": size_bytes
        })

    # 4. タスクを登録 (max_retries=2)
    task_id = "task_preview_001"
    await agent.register_task(task_id, initial_status="READY", max_retries=2)
    
    # 5. エージェントを起動
    await agent.start(process_task)
    
    for _ in range(50):
        status = await agent.get_task_status(task_id)
        if status == "COMPLETED":
            break
        await asyncio.sleep(0.1)
        
    status = await agent.get_task_status(task_id)
    assert status == "COMPLETED"
    
    # 結果がDBに保存されていることを検証
    conn = agent._get_conn()
    cursor = conn.execute("SELECT result, error, retry_count FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    assert row is not None
    result_data = json.loads(row[0])
    assert result_data["status"] == "success"
    assert result_data["width"] == 1280
    assert result_data["height"] == 720
    assert row[1] is None
    
    # 6. 失敗と自動リトライの検証
    async def process_failed_task(task_id: str) -> str:
        overlay.generate_preview_image(
            input_video="non_existent.mp4",
            logo_path=dummy_logo,
            output_image=output_image,
        )
        return "success"
        
    failed_task_id = "task_preview_failed_001"
    await agent.register_task(failed_task_id, initial_status="READY", max_retries=1)
    
    await agent.stop()
    await agent.start(process_failed_task)
    
    for _ in range(50):
        status = await agent.get_task_status(failed_task_id)
        if status == "FAILED":
            break
        await asyncio.sleep(0.1)
        
    status = await agent.get_task_status(failed_task_id)
    assert status == "FAILED"
    
    cursor = conn.execute("SELECT retry_count, error FROM tasks WHERE id = ?", (failed_task_id,))
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == 1
    assert "ValueError" in row[1] or "not found" in row[1]
    
    conn.close()
    await agent.stop()


def test_logo_overlay_integration_strict_resolution_aspect_and_size(tmp_path):
    """
    異なるアスペクト比（縦動画）の入力でも、出力画像が正しく16:9（1280x720）に
    リサイズおよびパディングされること、および空ファイルのバリデーションを確認する
    """
    dummy_video_portrait = str(tmp_path / "dummy_video_portrait.mp4")
    dummy_logo = str(tmp_path / "dummy_logo.png")
    output_image_jpg = str(tmp_path / "preview_portrait.jpg")
    output_image_png = str(tmp_path / "preview_portrait.png")
    empty_file = str(tmp_path / "empty_file.mp4")

    # 1. 縦動画 (240x320, 3:4) を生成
    video_cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", "color=c=green:s=240x320:d=1",
        "-c:v", "libx264",
        "-t", "1",
        dummy_video_portrait
    ]
    subprocess.run(video_cmd, check=True, capture_output=True)

    # 2. ロゴ (16x16) を生成
    logo_cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", "color=c=red:s=16x16:d=1",
        "-vframes", "1",
        dummy_logo
    ]
    subprocess.run(logo_cmd, check=True, capture_output=True)

    # 3. 空ファイルを生成
    with open(empty_file, "wb") as f:
        pass

    overlay = LogoOverlay()

    # (A) JPG出力の検証
    res_jpg = overlay.generate_preview_image(
        input_video=dummy_video_portrait,
        logo_path=dummy_logo,
        output_image=output_image_jpg,
        position=(5, 5),
        opacity=0.9,
        target_height=20,
        time_offset=0.2
    )
    assert os.path.exists(res_jpg)
    with Image.open(res_jpg) as img:
        width, height = img.size
        assert width == 1280, f"Expected 1280, got {width}"
        assert height == 720, f"Expected 720, got {height}"
        aspect_ratio = width / height
        assert abs(aspect_ratio - (16.0 / 9.0)) < 1e-5
        
    size_jpg = os.path.getsize(res_jpg)
    assert 0 < size_jpg < 4 * 1024 * 1024

    # (B) PNG出力の検証
    res_png = overlay.generate_preview_image(
        input_video=dummy_video_portrait,
        logo_path=dummy_logo,
        output_image=output_image_png,
        position=(5, 5),
        opacity=0.9,
        target_height=20,
        time_offset=0.2
    )
    assert os.path.exists(res_png)
    with Image.open(res_png) as img:
        width, height = img.size
        assert width == 1280
        assert height == 720
        
    size_png = os.path.getsize(res_png)
    assert 0 < size_png < 4 * 1024 * 1024

    # (C) 空ファイルに対するバリデーションの検証
    with pytest.raises(ValueError) as exc:
        overlay.generate_preview_image(
            input_video=empty_file,
            logo_path=dummy_logo,
            output_image=output_image_jpg
        )
    assert "empty" in str(exc.value)

    with pytest.raises(ValueError) as exc:
        overlay.generate_preview_image(
            input_video=dummy_video_portrait,
            logo_path=empty_file,
            output_image=output_image_jpg
        )
    assert "empty" in str(exc.value)

