import sys
import os
import json
import base64
import asyncio
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock
from PIL import Image
import io
import sqlite3

# backend ディレクトリをパスに追加
backend_dir = Path(__file__).resolve().parents[2]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import progressive_preview_report
from agents.stage_bound_agent import StageBoundAgent

def create_valid_test_image_b64(width=1280, height=720, fmt="PNG") -> str:
    """Pillowを使用して、指定解像度の有効な画像を作成し、Base64文字列にする"""
    img = Image.new("RGB", (width, height), color=(73, 109, 137))
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode("utf-8")

def test_pp_report_thumbnail_generation_success(tmp_path):
    """正常系: 指定されたパスに正常なサムネイル画像が生成されること"""
    output_path = tmp_path / "test_thumb.png"
    text = "Test Thumbnail Text"
    
    res_path = progressive_preview_report.generate_progressive_preview_thumbnail(output_path, text=text)
    
    assert res_path == output_path
    assert output_path.exists()
    
    # ロードして解像度を確認
    with Image.open(output_path) as img:
        img.verify()
        
    with Image.open(output_path) as img:
        width, height = img.size
        assert width == 1280
        assert height == 720

def test_pp_report_thumbnail_validation_success(tmp_path):
    """正常系: 正常なサムネイル画像を検証し、要件をクリアすること"""
    output_path = tmp_path / "test_thumb.png"
    progressive_preview_report.generate_progressive_preview_thumbnail(output_path)
    
    res = progressive_preview_report.validate_thumbnail(output_path)
    assert res["width"] == 1280
    assert res["height"] == 720
    assert res["size_bytes"] > 0
    assert res["path"] == str(output_path)

def test_pp_report_thumbnail_validation_failures(tmp_path):
    """異常系: 品質要件を満たさない画像、または存在しない場合に適切にエラーになること"""
    # 1. 存在しない
    with pytest.raises(FileNotFoundError):
        progressive_preview_report.validate_thumbnail(tmp_path / "missing.png")
        
    # 2. 解像度不足
    low_res_path = tmp_path / "low_res.png"
    img = Image.new("RGB", (640, 360))
    img.save(low_res_path)
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        progressive_preview_report.validate_thumbnail(low_res_path)
        
    # 3. アスペクト比が異なる
    bad_ratio_path = tmp_path / "bad_ratio.png"
    img = Image.new("RGB", (1280, 960))
    img.save(bad_ratio_path)
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        progressive_preview_report.validate_thumbnail(bad_ratio_path)
        
    # 4. ファイルサイズ制限 (4MB超)
    valid_path = tmp_path / "valid_size.png"
    progressive_preview_report.generate_progressive_preview_thumbnail(valid_path)
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 5 * 1024 * 1024  # 5MB
        # is_dir() が呼ばれた際に st_mode が必要になるのを防ぐため、最低限 st_mode も設定するか、
        # または is_dir を patch するか。ここでは st_mode = 33206 (通常ファイル) を設定
        mock_stat.return_value.st_mode = 33206
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            progressive_preview_report.validate_thumbnail(valid_path)

    # 5. 画像データが破損している場合
    corrupt_path = tmp_path / "corrupt.png"
    corrupt_path.write_bytes(b"corrupt data")
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        progressive_preview_report.validate_thumbnail(corrupt_path)

def test_pp_report_stage_bound_agent_integration(tmp_path):
    """結合系: StageBoundAgent との自動検証・結果保存・リトライ連携テスト"""
    db_file = tmp_path / "test_stage_bound.db"
    task_id = "pp_report_thumb_test"
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    
    # 一時的なサムネイル出力ディレクトリを指定
    output_dir = tmp_path / "thumbnails"
    output_dir.mkdir()
    
    with patch("progressive_preview_report.OUTPUT_DIR", str(output_dir)):
        async def run_test():
            await agent.register_task(task_id=task_id, initial_status="READY", max_retries=1)
            await agent.start(progressive_preview_report.resolve_progressive_preview_report_task)
            
            # 完了待ち (タイムアウト 2.5 秒)
            for _ in range(50):
                status = await agent.get_task_status(task_id)
                if status in ("COMPLETED", "FAILED"):
                    break
                await asyncio.sleep(0.05)
                
            final_status = await agent.get_task_status(task_id)
            await agent.stop()
            
            assert final_status == "COMPLETED"
            
            # 生成されたファイルを検証
            output_path = output_dir / f"{task_id}.png"
            assert output_path.exists()
            
            res_info = progressive_preview_report.validate_thumbnail(output_path)
            assert res_info["width"] == 1280
            assert res_info["height"] == 720
            
            # DBに保存された結果を検証
            conn = sqlite3.connect(str(db_file))
            try:
                cursor = conn.execute("SELECT status, result, retry_count FROM tasks WHERE id = ?", (task_id,))
                row = cursor.fetchone()
                assert row is not None
                status, result_str, retry_count = row
                assert status == "COMPLETED"
                assert retry_count == 0
                
                db_result = json.loads(result_str)
                assert db_result["width"] == 1280
                assert db_result["height"] == 720
                assert "path" in db_result
            finally:
                conn.close()
                
        asyncio.run(run_test())

def test_pp_report_generator_invalid_dimensions():
    """異常系: 不正なサイズパラメータに対してValueErrorが発生こと"""
    with pytest.raises(ValueError, match="Width and height must be integers"):
        progressive_preview_report.generate_progressive_preview_thumbnail("path.png", width="invalid")
        
    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        progressive_preview_report.generate_progressive_preview_thumbnail("path.png", width=-1)



def test_pp_report_thumbnail_validation_aspect_ratio_boundary(tmp_path):
    """異常系: アスペクト比がわずかに16:9の許容誤差(0.01)を超える場合にエラーになること"""
    bad_path = tmp_path / "bad_aspect.png"
    # 解像度は1280x720以上を満たしつつ、アスペクト比がずれているもの (1300x720)
    img = Image.new("RGB", (1300, 720))
    img.save(bad_path)
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        progressive_preview_report.validate_thumbnail(bad_path)

def test_pp_report_thumbnail_validation_size_boundary(tmp_path):
    """異常系: ファイルサイズが4MB境界値前後の場合の検証"""
    valid_path = tmp_path / "boundary_size.png"
    progressive_preview_report.generate_progressive_preview_thumbnail(valid_path)
    
    # 4MB未満
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 4 * 1024 * 1024 - 1
        mock_stat.return_value.st_mode = 33206
        res = progressive_preview_report.validate_thumbnail(valid_path)
        assert res is not None

    # 4MB以上
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 4 * 1024 * 1024
        mock_stat.return_value.st_mode = 33206
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            progressive_preview_report.validate_thumbnail(valid_path)


def test_pp_report_thumbnail_generation_high_res(tmp_path):
    """正常系: 1280x720を超える高解像度（1920x1080等）でも16:9であれば正常に生成・検証されること"""
    output_path = tmp_path / "high_res_thumb.png"
    # 1920x1080 で生成
    res_path = progressive_preview_report.generate_progressive_preview_thumbnail(
        output_path, width=1920, height=1080, text="1920x1080 High Res"
    )
    assert res_path == output_path
    
    # 検証してエラーにならないことを確認
    res = progressive_preview_report.validate_thumbnail(output_path)
    assert res["width"] == 1920
    assert res["height"] == 1080
    assert res["size_bytes"] < 4 * 1024 * 1024

def test_pp_report_thumbnail_aspect_ratio_exact_bounds(tmp_path):
    """境界値テスト: アスペクト比が16:9許容誤差の境界上にある場合の挙動検証"""
    # 1280x720 = 1.77777...
    # 許容されるアスペクト比の誤差は 0.01。
    
    # 1. 範囲内のわずかなズレ (1285x720 -> 比率1.7847, 誤差0.0069 < 0.01。かつ解像度も1280x720以上を満たす)
    ok_path = tmp_path / "aspect_ok.png"
    img_ok = Image.new("RGB", (1285, 720))
    img_ok.save(ok_path)
    res = progressive_preview_report.validate_thumbnail(ok_path)
    assert res["width"] == 1285
    assert res["height"] == 720

    # 2. 範囲外のわずかなズレ (1295x720 -> 比率1.7986, 誤差0.0208 > 0.01。かつ解像度は1280x720以上を満たす)
    bad_path = tmp_path / "aspect_bad.png"
    img_bad = Image.new("RGB", (1295, 720))
    img_bad.save(bad_path)
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        progressive_preview_report.validate_thumbnail(bad_path)

def test_pp_report_thumbnail_optimization_and_size_limit(tmp_path):
    """検証テスト: 実際に生成されたサムネイルのファイルサイズが4MB未満で、最適化が有効に働いていること"""
    output_path = tmp_path / "opt_test.png"
    progressive_preview_report.generate_progressive_preview_thumbnail(output_path, text="Optimization Test")
    
    # 実ファイルサイズの取得
    size = output_path.stat().st_size
    # 4MBより圧倒的に小さく、かつ正常に生成されていることを確認
    assert size > 0
    assert size < 4 * 1024 * 1024
    
    # validate_thumbnailを通ることを確認
    res = progressive_preview_report.validate_thumbnail(output_path)
    assert res["size_bytes"] == size

def test_pp_report_thumbnail_corrupt_pixel_data_detection(tmp_path):
    """異常系: ファイルは存在するが、画像の一部（ピクセルデータ）が途中で破損している場合にPillowが検知すること"""
    output_path = tmp_path / "partial_corrupt.png"
    # 正常な画像を生成
    progressive_preview_report.generate_progressive_preview_thumbnail(output_path)
    
    # ファイルサイズを確認して、ファイルの後半を0で塗りつぶす等の物理的破損を模擬
    with open(output_path, "r+b") as f:
        f.seek(1000) # ヘッダー以降の適当な位置
        f.write(b"\x00" * 5000)
        
    # validate_thumbnail がピクセルデータのロード強制(load())により例外を検知することを確認
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        progressive_preview_report.validate_thumbnail(output_path)


def test_pp_report_thumbnail_long_text_autoscaling(tmp_path):
    """正常系: 非常に長いテキストを渡しても、フォント自動スケーリング機能によりはみ出さず正常に画像が生成されること"""
    output_path = tmp_path / "long_text_thumb.png"
    # 非常に長いテキスト（パネルの元の高さを超えるほどの長い文字列）
    long_text = "\n".join([f"Line {i}: This is a very long text to test automatic scaling capability. We want to make sure it doesn't cause any drawing errors." for i in range(25)])
    
    res_path = progressive_preview_report.generate_progressive_preview_thumbnail(output_path, text=long_text)
    assert res_path == output_path
    assert output_path.exists()
    
    res = progressive_preview_report.validate_thumbnail(output_path)
    assert res["width"] == 1280
    assert res["height"] == 720


def test_pp_report_thumbnail_cleanup_on_error(tmp_path):
    """異常系: 画像生成中にエラーが発生した場合、作成中の一時ファイル(.tmp)が確実にクリーンアップされること"""
    output_path = tmp_path / "error_cleanup.png"
    
    # Image.alpha_composite をモックして例外を発生させる
    with patch("PIL.Image.alpha_composite", side_effect=RuntimeError("Composite failed")):
        # フォールバックも失敗するように _generate_fallback_thumbnail をモック
        with patch("progressive_preview_report._generate_fallback_thumbnail", side_effect=RuntimeError("Fallback failed")):
            with pytest.raises(RuntimeError, match="Fallback failed"):
                progressive_preview_report.generate_progressive_preview_thumbnail(output_path)
                
    # 一時ファイルが残っていないか検証
    temp_files = list(tmp_path.glob("*.tmp"))
    assert len(temp_files) == 0


def test_pp_report_thumbnail_fallback_generation(tmp_path):
    """正常系: 高品質画像生成で例外が発生した際、自動的にフォールバック画像生成が行われ有効な画像が出力されること"""
    output_path = tmp_path / "fallback_triggered.png"
    
    # Image.alpha_composite をモックして例外を発生させ、高品質生成を失敗させる
    with patch("PIL.Image.alpha_composite", side_effect=RuntimeError("Composite failed")):
        # ログに警告が出力される
        with patch("progressive_preview_report.logger.warning") as mock_warning:
            res_path = progressive_preview_report.generate_progressive_preview_thumbnail(output_path, text="Testing Fallback")
            assert res_path == output_path
            assert output_path.exists()
            mock_warning.assert_called_once()
            assert "Using fallback thumbnail" in mock_warning.call_args[0][0]
            
    # 生成されたフォールバック画像が正しく検証をパスすることを確認
    res = progressive_preview_report.validate_thumbnail(output_path)
    assert res["width"] == 1280
    assert res["height"] == 720

def test_pp_report_strict_standards_verification(tmp_path):
    """
    ユーザー指示の必須品質基準を個別に厳密検証する独立テスト:
    - 解像度が 1280x720 以上であること
    - アスペクト比が 16:9 (誤差0.01以内) であること
    - ファイルサイズが 4MB 未満であること
    - 出力ファイルが正常に存在し、破損していない (Image.open と load が通ること)
    """
    output_path = tmp_path / "mandatory_standard_test.png"
    text = "Mandatory Standards Verification\nResolution >= 1280x720\nAspect Ratio == 16:9\nSize < 4MB\nValid PNG format"
    
    # 1. サムネイル生成
    generated = progressive_preview_report.generate_progressive_preview_thumbnail(output_path, text=text)
    assert Path(generated).exists()
    
    # 2. ファイルサイズ検証 (4MB 未満)
    size_bytes = generated.stat().st_size
    assert size_bytes < 4 * 1024 * 1024, f"File size is {size_bytes} bytes, which exceeds 4MB"
    assert size_bytes > 0
    
    # 3. Pillowによる破損チェックとロード検証
    with Image.open(generated) as img:
        img.verify() # verify()で破損がないことを確認
        
    with Image.open(generated) as img:
        img.load() # ピクセルデータをロードして破損チェック
        width, height = img.size
        
    # 4. 解像度検証 (1280x720 以上)
    assert width >= 1280, f"Width is {width}, expected >= 1280"
    assert height >= 720, f"Height is {height}, expected >= 720"
    
    # 5. アスペクト比検証 (16:9)
    aspect_ratio = width / height
    expected_ratio = 16.0 / 9.0
    assert abs(aspect_ratio - expected_ratio) <= 0.01, f"Aspect ratio is {aspect_ratio:.3f}, expected 16:9 (1.778)"

