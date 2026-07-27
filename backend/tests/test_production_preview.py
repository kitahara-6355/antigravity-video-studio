# -*- coding: utf-8 -*-
import sys
import os
import sqlite3
import json
import asyncio
import subprocess
from pathlib import Path
import pytest
from PIL import Image

# backend ディレクトリをパスに追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from production_preview import (
    create_production_preview,
    validate_preview_image,
    ProductionPreviewManager
)
from agents.stage_bound_agent import StageBoundAgent

@pytest.fixture
def dummy_video_and_subtitle(tmp_path):
    """
    テスト用のダミー動画（10秒）と字幕（srt）ファイルを生成するフィクスチャ。
    実際のFFmpeg呼び出しの動作を保証するために、lavfiカラーソースで動画を作成。
    """
    video_path = tmp_path / "dummy_input.mp4"
    subtitle_path = tmp_path / "dummy_input.srt"
    
    # 1. 10秒のダミー動画 (640x360) を生成
    gen_video_cmd = [
        "ffmpeg",
        "-f", "lavfi",
        "-i", "color=c=black:s=640x360:d=25",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-y",
        str(video_path)
    ]
    try:
        subprocess.run(gen_video_cmd, check=True, capture_output=True, timeout=30)
    except (subprocess.CalledProcessError, subprocess.SubprocessError) as e:
        # FFmpeg が無いか動かない環境の場合は xfail またはスキップ
        pytest.skip(f"FFmpeg is not available or failed to generate test video: {e}")
        
    # 2. 字幕ファイルを生成 (UTF-8)
    srt_content = """1
00:00:01,000 --> 00:00:03,000
こんにちは、北原美麗です。

2
00:00:04,000 --> 00:00:06,000
山田タロウです。
"""
    subtitle_path.write_text(srt_content, encoding="utf-8")
    
    return video_path, subtitle_path


def test_validate_preview_image_quality_check(tmp_path):
    """
    validate_preview_image による品質要件のバリデーションの動作テスト。
    解像度、アスペクト比、ファイルサイズ制限、および破損検知を検証。
    """
    # 1. 正常な画像 (1280x720, 16:9, 小サイズ)
    normal_img_path = tmp_path / "normal.png"
    img = Image.new("RGB", (1280, 720), color="blue")
    img.save(normal_img_path, format="PNG")
    
    result = validate_preview_image(normal_img_path)
    assert result["width"] == 1280
    assert result["height"] == 720
    assert result["size_bytes"] < 4 * 1024 * 1024
    
    # 2. 解像度不足 (640x360)
    low_res_path = tmp_path / "low_res.png"
    img = Image.new("RGB", (640, 360), color="blue")
    img.save(low_res_path, format="PNG")
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        validate_preview_image(low_res_path)
        
    # 3. アスペクト比異常 (1280x960, 4:3)
    bad_ratio_path = tmp_path / "bad_ratio.png"
    img = Image.new("RGB", (1280, 960), color="blue")
    img.save(bad_ratio_path, format="PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        validate_preview_image(bad_ratio_path)
        
    # 4. ファイルサイズ制限 (4MB制限)
    # モックを介して Path.stat().st_size を偽装
    from unittest.mock import patch
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 5 * 1024 * 1024  # 5MB
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            validate_preview_image(normal_img_path)


def test_create_production_preview_success(dummy_video_and_subtitle, tmp_path):
    """
    create_production_preview の結合テスト。
    ダミー動画から本番品質プレビューが正常生成され、
    生成された画像が品質要件を満たしていることをアサート。
    """
    video_path, subtitle_path = dummy_video_and_subtitle
    output_dir = tmp_path / "preview_out"
    
    # テロップとロゴを適用してプレビューを生成
    result = create_production_preview(
        input_video=str(video_path),
        subtitle_file=str(subtitle_path),
        theme_text="テストテーマ",
        output_dir=str(output_dir),
        speaker1="美麗",
        speaker2="ヒロノブ"
    )
    
    assert "video" in result
    assert "screenshots" in result
    assert len(result["screenshots"]) == 3
    
    # 生成された各スクリーンショットに対して品質検査を実施
    for shot_path in result["screenshots"]:
        img_path = Path(shot_path)
        assert img_path.exists()
        
        # Pillowでロード可能であることを検証
        with Image.open(img_path) as img:
            img.verify()
            
        # 完全なロードができることを検証 (ピクセルデータ破損検知)
        with Image.open(img_path) as img:
            img.load()
            width, height = img.size
            
        assert width >= 1280
        assert height >= 720
        assert abs((width / height) - (16.0 / 9.0)) < 0.05
        assert img_path.stat().st_size < 4 * 1024 * 1024


@pytest.mark.asyncio
async def test_production_preview_agent_integration(dummy_video_and_subtitle, tmp_path):
    """
    StageBoundAgent等と連携して自動リトライや結果保存、DBマイグレーションの各機能と
    連携して動作することを確認するインテグレーションテスト。
    """
    video_path, subtitle_path = dummy_video_and_subtitle
    db_file = tmp_path / "preview_tasks.db"
    output_dir = tmp_path / "preview_agent_out"
    
    manager = ProductionPreviewManager(
        input_video=str(video_path),
        subtitle_file=str(subtitle_path),
        theme_text="エージェント連携テスト",
        output_dir=str(output_dir)
    )
    
    # StageBoundAgent の初期化 (DBマイグレーションが自動実行される)
    agent = StageBoundAgent(stage_name="preview", db_path=str(db_file))
    task_id = "test_preview_task_001"
    
    # 1. タスクの登録 (自動リトライの確認用に max_retries=2 を設定)
    await agent.register_task(task_id=task_id, initial_status="READY", max_retries=2)
    
    # 2. Agentを起動して、managerの resolve_production_preview_task ハンドラを登録
    await agent.start(manager.resolve_production_preview_task)
    
    # 3. 完了を監視
    completed = False
    for _ in range(100):
        status = await agent.get_task_status(task_id)
        if status in ("COMPLETED", "FAILED"):
            completed = True
            break
        await asyncio.sleep(0.05)
        
    final_status = await agent.get_task_status(task_id)
    await agent.stop()
    
    assert completed, "Task did not complete within timeout"
    assert final_status == "COMPLETED"
    
    # 4. DB保存結果の検証
    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.execute("SELECT status, result, retry_count FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None
        status, result_str, retry_count = row
        assert status == "COMPLETED"
        assert retry_count == 0  # リトライされずに初回成功
        
        result_data = json.loads(result_str)
        assert "video" in result_data
        assert "screenshots" in result_data
        assert len(result_data["screenshots"]) == 3
        
        # 生成された画像が実際に存在し、要件を満たしているか確認
        for shot in result_data["screenshots"]:
            assert Path(shot).exists()
            quality_info = validate_preview_image(shot)
            assert quality_info["width"] >= 1280
            assert quality_info["height"] >= 720
            assert quality_info["size_bytes"] < 4 * 1024 * 1024
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_production_preview_agent_retry_on_failure(tmp_path):
    """
    StageBoundAgent の自動リトライ機能との連携を確認。
    画像生成に失敗した際に、正しくリトライカウントがインクリメントされ、
    最終的に最大リトライ数を超えると FAILED ステータスになることをテスト。
    """
    db_file = tmp_path / "retry_test.db"
    
    # 存在しない動画ファイルを指定して意図的に失敗させる
    manager = ProductionPreviewManager(
        input_video="non_existent.mp4",
        subtitle_file="non_existent.srt",
        theme_text="リトライテスト"
    )
    
    agent = StageBoundAgent(stage_name="preview", db_path=str(db_file))
    task_id = "test_retry_task"
    
    # 最大リトライ回数を 1 に設定
    await agent.register_task(task_id=task_id, initial_status="READY", max_retries=1)
    await agent.start(manager.resolve_production_preview_task)
    
    # 完了または失敗を待つ
    for _ in range(100):
        status = await agent.get_task_status(task_id)
        if status in ("COMPLETED", "FAILED"):
            break
        await asyncio.sleep(0.05)
        
    final_status = await agent.get_task_status(task_id)
    await agent.stop()
    
    assert final_status == "FAILED"
    
    # DBでリトライ回数が上限に達しているか確認
    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.execute("SELECT status, retry_count, error FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None
        status, retry_count, error = row
        assert status == "FAILED"
        assert retry_count == 1  # 1回リトライした
        assert "Input video not found" in error
    finally:
        conn.close()


def test_validate_preview_image_edge_cases(tmp_path):
    """
    validate_preview_image の境界値および例外系テスト。
    - 0バイトファイル
    - 未識別の画像形式
    - アスペクト比の誤差許容範囲
    """
    # 1. 0バイトファイル
    zero_byte_file = tmp_path / "zero.png"
    zero_byte_file.touch()
    with pytest.raises(ValueError, match="File size is 0 bytes"):
        validate_preview_image(zero_byte_file)
        
    # 2. 未識別・非画像形式ファイル
    not_image_file = tmp_path / "text.txt"
    not_image_file.write_text("this is not an image", encoding="utf-8")
    with pytest.raises(ValueError, match="File is not a recognized image format"):
        validate_preview_image(not_image_file)
        
    # 3. アスペクト比の許容差限界テスト
    # target: 16:9 = 1.7777... 許容誤差は 0.05
    # 限界内 (1.777 + 0.04 = 1.817) -> OK (解像度要件 1280x720 以上を満たすため 1303x720 とする)
    ok_limit_path = tmp_path / "ok_limit.png"
    img = Image.new("RGB", (1303, 720), color="blue")
    img.save(ok_limit_path, format="PNG")
    result = validate_preview_image(ok_limit_path)
    assert result["width"] == 1303
    assert result["height"] == 720
    
    # 限界外 (1.777 + 0.06 = 1.837) -> NG (解像度要件 1280x720 以上を満たすため 1324x720 とする)
    ng_limit_path = tmp_path / "ng_limit.png"
    img = Image.new("RGB", (1324, 720), color="blue")
    img.save(ng_limit_path, format="PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        validate_preview_image(ng_limit_path)


def test_create_preview_screenshot_retry(dummy_video_and_subtitle, tmp_path):
    """
    FFmpegのスクリーンショット抽出が一部タイムスタンプで失敗した際に、
    自動的に異なるタイムスタンプへフォールバックしてリトライされるかテスト。
    """
    video_path, subtitle_path = dummy_video_and_subtitle
    output_dir = tmp_path / "retry_screenshot_out"
    
    from unittest.mock import patch
    import subprocess
    
    original_run = subprocess.run
    
    # 初回の 0.5s 時点での抽出を意図的に失敗させ、0.5 + 0.5 = 1.0s で成功させるモック
    call_count = {"ffmpeg": 0}
    
    def mock_run(cmd, *args, **kwargs):
        if "ffmpeg" in cmd:
            # スクリーンショット生成コマンドを特定
            is_screenshot = any("screenshot_" in str(arg) for arg in cmd)
            if is_screenshot:
                call_count["ffmpeg"] += 1
                # 1回目の試行 (ts=0.5) を失敗させる
                if "-ss" in cmd and cmd[cmd.index("-ss")+1] == "0.50":
                    raise subprocess.CalledProcessError(
                        returncode=1,
                        cmd=cmd,
                        stderr=b"Simulated FFmpeg screenshot extraction failure"
                    )
        
        return original_run(cmd, *args, **kwargs)
        
    with patch("subprocess.run", side_effect=mock_run):
        result = create_production_preview(
            input_video=str(video_path),
            subtitle_file=str(subtitle_path),
            theme_text="リトライテスト",
            output_dir=str(output_dir),
            speaker1="美麗",
            speaker2="ヒロノブ"
        )
        
    assert "video" in result
    assert len(result["screenshots"]) == 3
    # 失敗したはずの 1枚目のスクリーンショットも、タイムスタンプをずらして正常に取得できていることを確認
    for p in result["screenshots"]:
        assert Path(p).exists()
        validate_preview_image(p)


def test_high_quality_blur_padding(tmp_path):
    """
    アスペクト比が 16:9 と異なる入力画像に対して、
    高品質な背景ぼかしパディング処理が正しく動作し、最終出力が 16:9 の 1280x720 になることをテスト。
    """
    from PIL import ImageDraw
    
    # 1. アスペクト比 1:1（スクエア 640x640）の動画を入力として本番品質プレビューを作成する
    video_path = tmp_path / "square_video.mp4"
    subtitle_path = tmp_path / "dummy.srt"
    
    gen_video_cmd = [
        "ffmpeg",
        "-f", "lavfi",
        "-i", "color=c=red:s=640x640:d=25",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-y",
        str(video_path)
    ]
    try:
        subprocess.run(gen_video_cmd, check=True, capture_output=True, timeout=30)
    except (subprocess.CalledProcessError, subprocess.SubprocessError) as e:
        pytest.skip(f"FFmpeg failed to generate square video: {e}")
        
    subtitle_path.write_text("1\n00:00:01,000 --> 00:00:03,000\nテスト\n", encoding="utf-8")
    
    output_dir = tmp_path / "square_preview_out"
    
    result = create_production_preview(
        input_video=str(video_path),
        subtitle_file=str(subtitle_path),
        theme_text="スクエアテスト",
        output_dir=str(output_dir)
    )
    
    assert len(result["screenshots"]) == 3
    for shot_path in result["screenshots"]:
        img_path = Path(shot_path)
        assert img_path.exists()
        
        # 検証をパスすること
        val = validate_preview_image(img_path)
        assert val["width"] == 1280
        assert val["height"] == 720
        
        # ぼかし背景が適用されているか簡易検証
        # 16:9 の場合、元の 1:1 画像は中央に配置され、左右には
        # ぼかされた背景（赤ベース）が入るはず。黒塗り（0,0,0）ではないことをアサート
        with Image.open(img_path) as out_img:
            left_pixel = out_img.getpixel((10, 360))
            # 赤ベースなので、R値が大きく、G/B値は小さいはず（黒 [0,0,0] ではない）
            assert left_pixel[0] > 100
            assert left_pixel[1] < 50
            assert left_pixel[2] < 50

def test_create_production_preview_short_video(tmp_path):
    """
    5秒未満（短い動画：ここでは3秒）を入力とした場合でも、
    自動的に開始時刻や長さが調整され、エラーにならず正常に
    16:9 サムネイルが3枚出力されることをテストする。
    """
    video_path = tmp_path / "short_input.mp4"
    subtitle_path = tmp_path / "short_input.srt"
    output_dir = tmp_path / "short_preview_out"

    # 3秒のダミー動画 (640x360) を生成
    gen_video_cmd = [
        "ffmpeg",
        "-f", "lavfi",
        "-i", "color=c=black:s=640x360:d=3",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-y",
        str(video_path)
    ]
    try:
        subprocess.run(gen_video_cmd, check=True, capture_output=True, timeout=30)
    except (subprocess.CalledProcessError, subprocess.SubprocessError) as e:
        pytest.skip(f"FFmpeg failed to generate short test video: {e}")

    # 字幕を生成
    subtitle_path.write_text("1\n00:00:01,000 --> 00:00:02,000\n短い動画テスト\n", encoding="utf-8")

    result = create_production_preview(
        input_video=str(video_path),
        subtitle_file=str(subtitle_path),
        theme_text="短いテーマ",
        output_dir=str(output_dir),
        speaker1="美麗",
        speaker2="ヒロノブ"
    )

    assert "video" in result
    assert "screenshots" in result
    assert len(result["screenshots"]) == 3

    for shot_path in result["screenshots"]:
        img_path = Path(shot_path)
        assert img_path.exists()
        val = validate_preview_image(img_path)
        assert val["width"] == 1280
        assert val["height"] == 720


def test_get_video_duration_error_handling():
    """
    get_video_duration が CalledProcessError や ValueError などの例外発生時に
    正しくデフォルト値 10.0 を返し、エラーを伝播させないことを検証する。
    """
    from unittest.mock import patch
    import subprocess
    from production_preview import get_video_duration

    # 1. CalledProcessError を発生させる
    with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "ffprobe")):
        assert get_video_duration("dummy.mp4") == 10.0

    # 2. ValueError を発生させる（float 変換失敗）
    class DummyCompletedProcess:
        stdout = "not_a_float"
    with patch("subprocess.run", return_value=DummyCompletedProcess()):
        assert get_video_duration("dummy.mp4") == 10.0


def test_create_production_preview_cleanup_error_handling(dummy_video_and_subtitle, tmp_path):
    """
    一時ファイル削除時 (finally ブロック内) に OSError が発生しても、
    メインの処理が失敗せず、正常にプレビュー生成が完了することを検証する。
    """
    from unittest.mock import patch
    video_path, subtitle_path = dummy_video_and_subtitle
    output_dir = tmp_path / "cleanup_err_out"

    original_unlink = Path.unlink

    # unlink に OSError を発生させるモック
    def mock_unlink(self, *args, **kwargs):
        raise OSError("Simulated deletion failure")

    with patch.object(Path, "unlink", mock_unlink):
        result = create_production_preview(
            input_video=str(video_path),
            subtitle_file=str(subtitle_path),
            theme_text="クリーンアップエラーテスト",
            output_dir=str(output_dir)
        )
        
    assert "video" in result
    assert len(result["screenshots"]) == 3
    for shot_path in result["screenshots"]:
        assert Path(shot_path).exists()


def test_create_production_preview_missing_subtitle(dummy_video_and_subtitle, tmp_path):
    """字幕ファイルが存在しない場合に FileNotFoundError を投げることを検証"""
    video_path, subtitle_path = dummy_video_and_subtitle
    non_existent_srt = tmp_path / "non_existent.srt"
    
    with pytest.raises(FileNotFoundError, match="Subtitle file not found"):
        create_production_preview(
            input_video=str(video_path),
            subtitle_file=str(non_existent_srt),
            theme_text="テスト"
        )


def test_validate_preview_image_file_not_found(tmp_path):
    """検証対象の画像ファイルが存在しない場合に FileNotFoundError を投げることを検証"""
    non_existent_img = tmp_path / "non_existent.png"
    with pytest.raises(FileNotFoundError, match="Preview file not found"):
        validate_preview_image(non_existent_img)


def test_create_production_preview_extract_failures(dummy_video_and_subtitle, tmp_path):
    """動画抽出時に FFmpeg がタイムアウトまたは異常終了した場合のエラーハンドリングを検証"""
    video_path, subtitle_path = dummy_video_and_subtitle
    output_dir = tmp_path / "extract_err_out"
    
    from unittest.mock import patch
    import subprocess
    
    # 1. タイムアウトエラーのシミュレーション
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=60)):
        with pytest.raises(subprocess.TimeoutExpired):
            create_production_preview(
                input_video=str(video_path),
                subtitle_file=str(subtitle_path),
                theme_text="タイムアウトテスト",
                output_dir=str(output_dir)
            )
            
    # 2. CalledProcessErrorのシミュレーション
    with patch("subprocess.run", side_effect=subprocess.CalledProcessError(returncode=1, cmd="ffmpeg", stderr=b"Simulated FFmpeg error")):
        with pytest.raises(subprocess.CalledProcessError):
            create_production_preview(
                input_video=str(video_path),
                subtitle_file=str(subtitle_path),
                theme_text="実行エラーテスト",
                output_dir=str(output_dir)
            )


def test_create_production_preview_logo_overlay_failure(dummy_video_and_subtitle, tmp_path):
    """CombinedOverlay.apply_brand_overlay 失敗時のエラー伝播を検証"""
    video_path, subtitle_path = dummy_video_and_subtitle
    output_dir = tmp_path / "overlay_err_out"
    
    from unittest.mock import patch
    
    with patch("combined_overlay.CombinedOverlay.apply_brand_overlay", side_effect=OSError("Simulated Overlay OSError")):
        with pytest.raises(OSError, match="Simulated Overlay OSError"):
            create_production_preview(
                input_video=str(video_path),
                subtitle_file=str(subtitle_path),
                theme_text="テロップエラーテスト",
                output_dir=str(output_dir)
            )


def test_create_production_preview_subtitle_burn_fallback(dummy_video_and_subtitle, tmp_path):
    """字幕焼き込みが失敗しても、ロゴ+テロップ適用のみでフォールバックされ、最終的に成功することを検証"""
    video_path, subtitle_path = dummy_video_and_subtitle
    output_dir = tmp_path / "sub_fallback_out"
    
    from unittest.mock import patch
    import subprocess
    
    original_run = subprocess.run
    
    def mock_run_sub_fail(cmd, *args, **kwargs):
        # 字幕焼き込み用の ffmpeg コマンド（subtitlesフィルタが含まれる）をシミュレーションエラーにする
        if "ffmpeg" in cmd and any("subtitles=" in str(arg) for arg in cmd):
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=cmd,
                stderr=b"Simulated FFmpeg subtitle burning error"
            )
        return original_run(cmd, *args, **kwargs)
        
    with patch("subprocess.run", side_effect=mock_run_sub_fail):
        result = create_production_preview(
            input_video=str(video_path),
            subtitle_file=str(subtitle_path),
            theme_text="フォールバックテスト",
            output_dir=str(output_dir)
        )
        
    # 字幕焼き込みが失敗しても処理全体は成功し、3枚のスクリーンショットが生成されることを確認
    assert "video" in result
    assert len(result["screenshots"]) == 3
    for shot_path in result["screenshots"]:
        assert Path(shot_path).exists()


def test_screenshot_attempt_negative_timestamp_skip(dummy_video_and_subtitle, tmp_path):
    """スクリーンショット抽出時のタイムスタンプが負になった場合にスキップされ、エラーにならないことを検証"""
    video_path, subtitle_path = dummy_video_and_subtitle
    output_dir = tmp_path / "neg_ts_skip_out"
    
    # 実際の動画は 25 秒あるが、get_video_duration の戻り値を 0.2 秒に偽装する。
    # これにより ts が 0.02s になり、リトライ試行候補は [0.02, 0.52, -0.48, 1.02] となる。
    # 0.02s の試行をエラーにすると、-0.48s は負なのでスキップされ、0.52s はダミー画像を生成して成功させる。
    
    original_run = subprocess.run
    call_attempts = []
    
    def mock_run_with_neg_ts(cmd, *args, **kwargs):
        if "ffmpeg" in cmd and any("screenshot_" in str(arg) for arg in cmd):
            # コマンド引数から -ss の値を取得
            try:
                ss_idx = cmd.index("-ss")
                ts_val = float(cmd[ss_idx + 1])
                call_attempts.append(ts_val)
                # 0.02 秒（正）は失敗させる
                if abs(ts_val - 0.02) < 0.01:
                    raise subprocess.CalledProcessError(returncode=1, cmd=cmd, stderr=b"Simulated error")
                
                # 0.02秒以外の正のタイムスタンプ試行は、実際にFFmpegを実行せずダミー画像を生成して成功とする
                screenshot_path = cmd[-1]  # 通常は出力パスが最後
                from PIL import Image
                img = Image.new("RGB", (1280, 720), color="blue")
                img.save(screenshot_path, format="PNG")
                
                from unittest.mock import MagicMock
                res = MagicMock()
                res.returncode = 0
                return res
            except (ValueError, IndexError):
                pass
        return original_run(cmd, *args, **kwargs)
        
    from unittest.mock import patch
    with patch("subprocess.run", side_effect=mock_run_with_neg_ts), \
         patch("production_preview.get_video_duration", return_value=0.2):
         
        result = create_production_preview(
            input_video=str(video_path),
            subtitle_file=str(subtitle_path),
            theme_text="負のタイムスタンプテスト",
            output_dir=str(output_dir)
        )
        
    # 負のタイムスタンプ（-0.48s）は `attempt_ts < 0` によって continue されているため、
    # call_attempts には負の数字が入っていないことを確認
    assert all(ts >= 0 for ts in call_attempts)
    assert len(result["screenshots"]) == 3


def test_create_production_preview_aspect_ratio_wide(dummy_video_and_subtitle, tmp_path):
    """横長のアスペクト比（例: 24:9 = 2.666）の動画を入力とした場合にアスペクト比分岐（242行目付近）が動作することを検証"""
    video_path, subtitle_path = dummy_video_and_subtitle
    output_dir = tmp_path / "wide_preview_out"
    
    # 24:9 (960x360) のダミー動画を生成
    wide_video_path = tmp_path / "wide_video.mp4"
    gen_video_cmd = [
        "ffmpeg",
        "-f", "lavfi",
        "-i", "color=c=blue:s=960x360:d=15",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-y",
        str(wide_video_path)
    ]
    import subprocess
    subprocess.run(gen_video_cmd, check=True, capture_output=True, timeout=30)
    
    result = create_production_preview(
        input_video=str(wide_video_path),
        subtitle_file=str(subtitle_path),
        theme_text="横長アスペクト比テスト",
        output_dir=str(output_dir)
    )
    
    assert len(result["screenshots"]) == 3
    for shot_path in result["screenshots"]:
        img_path = Path(shot_path)
        assert img_path.exists()
        val = validate_preview_image(img_path)
        assert val["width"] == 1280
        assert val["height"] == 720


def test_create_production_preview_jpeg_fallback_over_4mb(dummy_video_and_subtitle, tmp_path):
    """PNGサイズが4MBを超えた場合にJPEGへフォールバックされることを検証"""
    video_path, subtitle_path = dummy_video_and_subtitle
    output_dir = tmp_path / "jpg_fallback_out"
    
    # 最初の PNG 保存後に Path.stat().st_size が 5MB を返すようにし、
    # 2回目の JPEG 保存後には 3MB を返すようにする。
    # 他のパス操作（ディレクトリ作成等）に影響を与えないよう、パス名に "screenshot_" が含まれている場合のみ stat を偽装する。
    from unittest.mock import patch, MagicMock
    
    original_stat = Path.stat
    def mock_stat(self_path, *args, **kwargs):
        path_str = str(self_path)
        if "screenshot_" in path_str:
            import os
            if path_str.endswith(".png"):
                return os.stat_result((33188, 0, 0, 1, 0, 0, 5 * 1024 * 1024, 0, 0, 0))
            elif path_str.endswith(".jpg"):
                return os.stat_result((33188, 0, 0, 1, 0, 0, 3 * 1024 * 1024, 0, 0, 0))
        return original_stat(self_path, *args, **kwargs)
    
    with patch.object(Path, "stat", mock_stat):
        result = create_production_preview(
            input_video=str(video_path),
            subtitle_file=str(subtitle_path),
            theme_text="JPEGフォールバックテスト",
            output_dir=str(output_dir)
        )
        
    assert len(result["screenshots"]) == 3
    for shot_path in result["screenshots"]:
        # JPEGになっているため拡張子が .jpg であることを確認
        assert shot_path.endswith(".jpg")
        assert Path(shot_path).exists()


def test_validate_preview_image_corrupted(tmp_path):
    """破損画像や不適切なデータに対する validate_preview_image の例外送出を検証"""
    corrupt_png = tmp_path / "corrupt.png"
    # 不完全なPNG（中身がテキスト）
    corrupt_png.write_text("not an image", encoding="utf-8")
    
    with pytest.raises(ValueError, match="File is not a recognized image format"):
        validate_preview_image(corrupt_png)
        
    # verifyは通るがloadで失敗する画像をシミュレートするため、Pillow をモックする
    from unittest.mock import patch, MagicMock
    from PIL import Image, UnidentifiedImageError
    
    mock_img = MagicMock()
    # verify() は正常終了するが、load() は OSError を投げる
    mock_img.verify.return_value = None
    mock_img.load.side_effect = OSError("Corrupted structure during load")
    
    with patch("PIL.Image.open", return_value=mock_img):
        # 存在する任意のパスを渡す
        dummy_file = tmp_path / "dummy.png"
        dummy_file.touch()
        # stat 偽装でサイズ制限回避
        with patch("pathlib.Path.stat") as mock_stat:
            mock_stat.return_value.st_size = 100
            with pytest.raises(ValueError, match="Image is corrupted and cannot be loaded"):
                validate_preview_image(dummy_file)
