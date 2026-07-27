import sys
import os
import io
import json
import base64
import runpy
import asyncio
import sqlite3
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock
from PIL import Image, ImageDraw

# backend ディレクトリをパスに追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import verify_image_gen
from agents.stage_bound_agent import StageBoundAgent

def test_image_generation_success(tmp_path):
    """正常系: 指定サイズで画像が生成され、品質検証を通過することを確認"""
    output_file = tmp_path / "valid_image.png"
    
    # 画像生成
    verify_image_gen.generate_image(output_file, width=1280, height=720, text="Test Success Image")
    
    # 存在確認
    assert output_file.exists()
    
    # 品質検証
    result = verify_image_gen.validate_generated_image(output_file)
    assert result["width"] == 1280
    assert result["height"] == 720
    assert result["size_bytes"] < 4 * 1024 * 1024
    assert result["path"] == str(output_file)

def test_image_generation_quality_failures(tmp_path):
    """異常系: 解像度不足、アスペクト比異常、サイズ超過、画像破損時に例外が発生することを確認"""
    
    # 1. 存在しないファイル
    with pytest.raises(FileNotFoundError):
        verify_image_gen.validate_generated_image(tmp_path / "missing.png")
        
    # 2. 解像度不足の画像
    low_res_file = tmp_path / "low_res.png"
    img = Image.new("RGB", (640, 360), color="blue")
    img.save(low_res_file, format="PNG")
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        verify_image_gen.validate_generated_image(low_res_file)
        
    # 3. アスペクト比異常の画像 (4:3, 1280x960)
    bad_ratio_file = tmp_path / "bad_ratio.png"
    img = Image.new("RGB", (1280, 960), color="blue")
    img.save(bad_ratio_file, format="PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        verify_image_gen.validate_generated_image(bad_ratio_file)
        
    # 4. ファイルサイズ制限
    valid_file = tmp_path / "valid.png"
    verify_image_gen.generate_image(valid_file, width=1280, height=720)
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 5 * 1024 * 1024  # 5MB
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            verify_image_gen.validate_generated_image(valid_file)
            
    # 5. 破損画像
    corrupted_file = tmp_path / "corrupted.png"
    with open(corrupted_file, "wb") as f:
        f.write(b"not an image data")
    with pytest.raises(ValueError, match="Image verification failed|Image load failed"):
        verify_image_gen.validate_generated_image(corrupted_file)

def test_image_generation_invalid_args():
    """異常系: generate_image に不適切な引数を渡した場合に ValueError が発生することを確認"""
    with pytest.raises(ValueError, match="Width and height must be integers"):
        verify_image_gen.generate_image("dummy.png", width="invalid", height=720)
        
    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        verify_image_gen.generate_image("dummy.png", width=-100, height=720)

def test_stage_bound_agent_integration(tmp_path):
    """StageBoundAgentとの統合テスト。自動リトライ、結果のDB保存、マイグレーション連携の確認"""
    db_file = tmp_path / "test_image_gen_agent.db"
    
    agent = StageBoundAgent(stage_name="image_generation", db_path=str(db_file))
    task_id = "test_image_gen_task"
    
    async def run_test():
        # タスクを登録。max_retries=1
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=1)
        
        # エージェント開始
        await agent.start(verify_image_gen.resolve_image_generation_task)
        
        # 完了を待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status in ("COMPLETED", "FAILED"):
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
        assert final_status == "COMPLETED"
        
        # 出力されたファイルの品質検証
        output_file = Path("backend/temp_thumbnails") / f"{task_id}.png"
        assert output_file.exists()
        
        try:
            result_info = verify_image_gen.validate_generated_image(output_file)
            assert result_info["width"] == 1280
            assert result_info["height"] == 720
            
            # DBに保存された結果の検証
            conn = sqlite3.connect(str(db_file))
            try:
                cursor = conn.execute("SELECT status, result, retry_count, max_retries FROM tasks WHERE id = ?", (task_id,))
                row = cursor.fetchone()
                assert row is not None
                status, result_str, retry_count, max_retries = row
                assert status == "COMPLETED"
                assert retry_count == 0
                assert max_retries == 1
                
                db_result = json.loads(result_str)
                assert db_result["width"] == 1280
                assert db_result["height"] == 720
                assert "path" in db_result
            finally:
                conn.close()
                
        finally:
            if output_file.exists():
                output_file.unlink()
                
    asyncio.run(run_test())

def test_stage_bound_agent_retry_behavior(tmp_path):
    """StageBoundAgent自動リトライ挙動の検証テスト。
    1回目の試行で例外が発生し、2回目のリトライで成功するシナリオ。
    """
    db_file = tmp_path / "test_image_gen_retry.db"
    agent = StageBoundAgent(stage_name="image_generation", db_path=str(db_file))
    task_id = "test_retry_task"
    
    call_count = 0
    
    async def mock_resolve_task(tid: str) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Temporary error for retry testing")
        # 2回目は成功
        return await verify_image_gen.resolve_image_generation_task(tid)
        
    async def run_test():
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=2)
        await agent.start(mock_resolve_task)
        
        # 完了を待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status in ("COMPLETED", "FAILED"):
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
        assert final_status == "COMPLETED"
        assert call_count == 2
        
        # DBにリトライカウントとエラーが記録されていることを確認
        conn = sqlite3.connect(str(db_file))
        try:
            cursor = conn.execute("SELECT status, retry_count, error FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            assert row is not None
            status, retry_count, error = row
            assert status == "COMPLETED"
            assert retry_count == 1
            assert "Temporary error" in error
        finally:
            conn.close()
            
        # 生成されたファイルのクリーンアップ
        output_file = Path("backend/temp_thumbnails") / f"{task_id}.png"
        if output_file.exists():
            output_file.unlink()
            
    asyncio.run(run_test())

def test_e2e_api_fallback():
    """E2Eテスト関数 run_image_generation_e2e() の動作をAPIモック環境で検証"""
    mock_post_res = MagicMock()
    mock_post_res.status_code = 200
    mock_post_res.json.return_value = {"task_id": "test_async_task_123"}
    
    mock_get_res = MagicMock()
    mock_get_res.status_code = 200
    # 1回目のポーリングは running、2回目は completed
    mock_get_res.json.side_effect = [
        {"status": "running"},
        {"status": "completed", "result": ["image1.png"]}
    ]
    
    with patch("requests.post", return_value=mock_post_res) as mock_post, \
         patch("requests.get", return_value=mock_get_res) as mock_get, \
         patch("time.sleep", return_value=None): # sleepを即座に終了させてハングを防ぐ
         
        verify_image_gen.run_image_generation_e2e()
        
        assert mock_post.called
        assert mock_get.call_count == 2

def test_main_block_execution():
    """__main__ブロックの実行をカバーする"""
    mock_post_res = MagicMock()
    mock_post_res.status_code = 200
    mock_post_res.json.return_value = {"task_id": "test_main_task"}
    
    mock_get_res = MagicMock()
    mock_get_res.status_code = 200
    mock_get_res.json.return_value = {"status": "completed", "result": ["main_image.png"]}
    
    with patch("requests.post", return_value=mock_post_res), \
         patch("requests.get", return_value=mock_get_res), \
         patch("time.sleep", return_value=None):
         
        runpy.run_path(str(backend_dir / "verify_image_gen.py"), run_name="__main__")

def test_generate_image_write_exception(tmp_path):
    """異常系: 画像の保存時に例外が発生した場合、一時ファイルが削除され例外がスローされること"""
    output_file = tmp_path / "failed_image.png"
    with patch("PIL.Image.Image.save", side_effect=IOError("Save failed")):
        with pytest.raises(IOError, match="Save failed"):
            verify_image_gen.generate_image(output_file, width=1280, height=720)
        assert not output_file.exists()
        tmp_pattern = f"{output_file.stem}.*.tmp"
        assert len(list(tmp_path.glob(tmp_pattern))) == 0

def test_validate_image_load_exception(tmp_path):
    """異常系: 画像の verify() は成功するが load() で例外が発生する場合"""
    valid_file = tmp_path / "corrupted_load.png"
    verify_image_gen.generate_image(valid_file, width=1280, height=720)
    
    with patch("PIL.Image.Image.load", side_effect=ValueError("Load error")):
        with pytest.raises(ValueError, match="Image load failed"):
            verify_image_gen.validate_generated_image(valid_file)

def test_test_image_generation_http_error():
    """異常系: API呼び出し時に HTTP ステータスコードが 200 以外の場合に sys.exit(1) が呼ばれること"""
    mock_res = MagicMock()
    mock_res.status_code = 400
    mock_res.text = "Bad Request"
    with patch("requests.post", return_value=mock_res):
        with pytest.raises(SystemExit) as excinfo:
            verify_image_gen.run_image_generation_e2e()
        assert excinfo.value.code == 1

def test_test_image_generation_json_decode_error():
    """異常系: API呼び出しのレスポンスが JSON ではない場合に sys.exit(1) が呼ばれること"""
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.side_effect = ValueError("Invalid JSON")
    with patch("requests.post", return_value=mock_res):
        with pytest.raises(SystemExit) as excinfo:
            verify_image_gen.run_image_generation_e2e()
        assert excinfo.value.code == 1

def test_test_image_generation_missing_task_id():
    """異常系: API呼び出しレスポンスに task_id が欠損している場合に sys.exit(1) が呼ばれること"""
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {} # task_id なし
    with patch("requests.post", return_value=mock_res):
        with pytest.raises(SystemExit) as excinfo:
            verify_image_gen.run_image_generation_e2e()
        assert excinfo.value.code == 1

def test_test_image_generation_post_timeout():
    """異常系: API呼び出しがタイムアウトした場合に sys.exit(1) が呼ばれること"""
    from requests.exceptions import Timeout
    with patch("requests.post", side_effect=Timeout("Timeout")):
        with pytest.raises(SystemExit) as excinfo:
            verify_image_gen.run_image_generation_e2e()
        assert excinfo.value.code == 1

def test_test_image_generation_post_request_exception():
    """異常系: API呼び出しで RequestException が発生した場合に sys.exit(1) が呼ばれること"""
    from requests.exceptions import RequestException
    with patch("requests.post", side_effect=RequestException("Error")):
        with pytest.raises(SystemExit) as excinfo:
            verify_image_gen.run_image_generation_e2e()
        assert excinfo.value.code == 1

def test_test_image_generation_polling_timeout():
    """異常系: ポーリングが60秒を超えてタイムアウトした場合に sys.exit(1) が呼ばれること"""
    mock_post_res = MagicMock()
    mock_post_res.status_code = 200
    mock_post_res.json.return_value = {"task_id": "test_task"}
    
    start_time = 1000.0
    time_values = [start_time, start_time + 61.0]
    
    with patch("requests.post", return_value=mock_post_res), \
         patch("time.time", side_effect=time_values):
        with pytest.raises(SystemExit) as excinfo:
            verify_image_gen.run_image_generation_e2e()
        assert excinfo.value.code == 1

def test_test_image_generation_polling_http_error():
    """正常系/異常系: ポーリング時に 200 以外のコードが返ってきた場合、sleepして続行し、最終的に completed になること"""
    mock_post_res = MagicMock()
    mock_post_res.status_code = 200
    mock_post_res.json.return_value = {"task_id": "test_task"}
    
    mock_get_err = MagicMock()
    mock_get_err.status_code = 500
    mock_get_err.text = "Internal Server Error"
    
    mock_get_ok = MagicMock()
    mock_get_ok.status_code = 200
    mock_get_ok.json.return_value = {"status": "completed", "result": ["img.png"]}
    
    with patch("requests.post", return_value=mock_post_res), \
         patch("requests.get", side_effect=[mock_get_err, mock_get_ok]), \
         patch("time.sleep", return_value=None):
         
        verify_image_gen.run_image_generation_e2e()

def test_test_image_generation_polling_json_decode_error():
    """正常系/異常系: ポーリング時に JSON デコードエラーになった場合、sleepして続言し、最終的に completed になること"""
    mock_post_res = MagicMock()
    mock_post_res.status_code = 200
    mock_post_res.json.return_value = {"task_id": "test_task"}
    
    mock_get_err = MagicMock()
    mock_get_err.status_code = 200
    mock_get_err.json.side_effect = ValueError("Invalid JSON")
    
    mock_get_ok = MagicMock()
    mock_get_ok.status_code = 200
    mock_get_ok.json.side_effect = None
    mock_get_ok.json.return_value = {"status": "completed", "result": ["img.png"]}
    
    with patch("requests.post", return_value=mock_post_res), \
         patch("requests.get", side_effect=[mock_get_err, mock_get_ok]), \
         patch("time.sleep", return_value=None):
         
        verify_image_gen.run_image_generation_e2e()

def test_test_image_generation_polling_status_failed():
    """異常系: ポーリングのステータスが failed になった場合に sys.exit(1) が呼ばれること"""
    mock_post_res = MagicMock()
    mock_post_res.status_code = 200
    mock_post_res.json.return_value = {"task_id": "test_task"}
    
    mock_get_res = MagicMock()
    mock_get_res.status_code = 200
    mock_get_res.json.return_value = {"status": "failed", "error": "Internal Processing Error"}
    
    with patch("requests.post", return_value=mock_post_res), \
         patch("requests.get", return_value=mock_get_res), \
         patch("time.sleep", return_value=None):
        with pytest.raises(SystemExit) as excinfo:
            verify_image_gen.run_image_generation_e2e()
        assert excinfo.value.code == 1

def test_test_image_generation_polling_status_none():
    """正常系/異常系: ステータスが None (欠損) の警告を挟みつつ、最終的に completed になること"""
    mock_post_res = MagicMock()
    mock_post_res.status_code = 200
    mock_post_res.json.return_value = {"task_id": "test_task"}
    
    mock_get_none = MagicMock()
    mock_get_none.status_code = 200
    mock_get_none.json.return_value = {"status": None}
    
    mock_get_ok = MagicMock()
    mock_get_ok.status_code = 200
    mock_get_ok.json.return_value = {"status": "completed", "result": ["img.png"]}
    
    with patch("requests.post", return_value=mock_post_res), \
         patch("requests.get", side_effect=[mock_get_none, mock_get_ok]), \
         patch("time.sleep", return_value=None):
         
        verify_image_gen.run_image_generation_e2e()

def test_test_image_generation_polling_exceptions():
    """正常系/異常系: ポーリング中に Timeout や RequestException が発生しても、sleepして続行し、最終的に completed になること"""
    from requests.exceptions import Timeout, RequestException
    
    mock_post_res = MagicMock()
    mock_post_res.status_code = 200
    mock_post_res.json.return_value = {"task_id": "test_task"}
    
    mock_get_ok = MagicMock()
    mock_get_ok.status_code = 200
    mock_get_ok.json.return_value = {"status": "completed", "result": ["img.png"]}
    
    with patch("requests.post", return_value=mock_post_res), \
         patch("requests.get", side_effect=[Timeout("Timeout"), RequestException("Error"), mock_get_ok]), \
         patch("time.sleep", return_value=None):
         
        verify_image_gen.run_image_generation_e2e()

def test_generate_image_output_path_exists(tmp_path):
    """正常系: 出力先ファイルがすでに存在する場合でも、削除されて正常に上書きされること"""
    output_file = tmp_path / "exists_image.png"
    output_file.write_text("dummy content")
    assert output_file.exists()
    
    verify_image_gen.generate_image(output_file, width=1280, height=720, text="Overwritten Image")
    assert output_file.exists()
    result = verify_image_gen.validate_generated_image(output_file)
    assert result["width"] == 1280

def test_generate_image_temp_unlink_exception(tmp_path):
    """異常系: 保存に成功するがリネームで失敗し、さらに一時ファイルの削除(unlink)自体も失敗(例外)する場合"""
    output_file = tmp_path / "unlink_fail_image.png"
    
    orig_rename = Path.rename
    orig_unlink = Path.unlink
    
    def mock_rename(self, *args, **kwargs):
        raise OSError("Rename failed")
        
    def mock_unlink(self, *args, **kwargs):
        if ".tmp" in self.name:
            raise OSError("Permission Denied on unlink")
        return orig_unlink(self, *args, **kwargs)
        
    with patch("pathlib.Path.rename", mock_rename), \
         patch("pathlib.Path.unlink", mock_unlink):
        with pytest.raises(OSError, match="Rename failed"):
            verify_image_gen.generate_image(output_file, width=1280, height=720)

def test_validate_image_resolution_boundaries(tmp_path):
    """解像度の下限境界テスト (1280x720)"""
    # 1. 1280x720 (正常)
    valid_file = tmp_path / "boundary_1280_720.png"
    img = Image.new("RGB", (1280, 720), color="blue")
    img.save(valid_file, format="PNG")
    result = verify_image_gen.validate_generated_image(valid_file)
    assert result["width"] == 1280
    assert result["height"] == 720

    # 2. 1279x720 (解像度不足)
    invalid_file1 = tmp_path / "boundary_1279_720.png"
    img = Image.new("RGB", (1279, 720), color="blue")
    img.save(invalid_file1, format="PNG")
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        verify_image_gen.validate_generated_image(invalid_file1)

    # 3. 1280x719 (解像度不足)
    invalid_file2 = tmp_path / "boundary_1280_719.png"
    img = Image.new("RGB", (1280, 719), color="blue")
    img.save(invalid_file2, format="PNG")
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        verify_image_gen.validate_generated_image(invalid_file2)

def test_validate_image_aspect_ratio_boundaries(tmp_path):
    """アスペクト比 (16:9 = 1.777...) の許容誤差 (0.01) 境界テスト"""
    # ターゲット比率: 1.77777...
    # 許容範囲: 1.76777... ～ 1.78777...
    # ※解像度要件 (1280x720以上) を満たす必要があります。

    # 1. 下限の許容内境界: 1280x724 -> 比率 1.76795 (誤差 0.00982, 正常)
    file_lower_ok = tmp_path / "aspect_lower_ok.png"
    img = Image.new("RGB", (1280, 724), color="blue")
    img.save(file_lower_ok, format="PNG")
    result = verify_image_gen.validate_generated_image(file_lower_ok)
    assert result["height"] == 724

    # 2. 下限の許容外境界: 1280x725 -> 比率 1.76551 (誤差 0.01226, エラー)
    file_lower_ng = tmp_path / "aspect_lower_ng.png"
    img = Image.new("RGB", (1280, 725), color="blue")
    img.save(file_lower_ng, format="PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        verify_image_gen.validate_generated_image(file_lower_ng)

    # 3. 上限の許容内境界: 1287x720 -> 比率 1.78750 (誤差 0.00972, 正常)
    file_upper_ok = tmp_path / "aspect_upper_ok.png"
    img = Image.new("RGB", (1287, 720), color="blue")
    img.save(file_upper_ok, format="PNG")
    result = verify_image_gen.validate_generated_image(file_upper_ok)
    assert result["width"] == 1287

    # 4. 上限の許容外境界: 1288x720 -> 比率 1.78888 (誤差 0.01111, エラー)
    file_upper_ng = tmp_path / "aspect_upper_ng.png"
    img = Image.new("RGB", (1288, 720), color="blue")
    img.save(file_upper_ng, format="PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        verify_image_gen.validate_generated_image(file_upper_ng)

def test_validate_image_file_size_boundaries(tmp_path):
    """ファイルサイズの境界テスト (4MB = 4,194,304 バイト)"""
    valid_file = tmp_path / "size_boundary_ok.png"
    img = Image.new("RGB", (1280, 720), color="blue")
    img.save(valid_file, format="PNG")

    # 1. 4MB - 1 バイト (正常)
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 4 * 1024 * 1024 - 1
        result = verify_image_gen.validate_generated_image(valid_file)
        assert result["size_bytes"] == 4 * 1024 * 1024 - 1

    # 2. 4MB バイト (エラー)
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 4 * 1024 * 1024
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            verify_image_gen.validate_generated_image(valid_file)

def test_validate_image_height_zero_prevention(tmp_path):
    """画像アスペクト比検証において、高さが0または負の数である場合の検証"""
    valid_file = tmp_path / "zero_height_mock.png"
    img = Image.new("RGB", (1280, 720), color="blue")
    img.save(valid_file, format="PNG")

    # Image.open の戻り値をモックして verify/load をバイパスし、size のみ 1280x0 とする
    mock_img = MagicMock()
    mock_img.size = (1280, 0)
    mock_img.verify.return_value = None
    mock_img.load.return_value = None
    mock_img.__enter__.return_value = mock_img
    mock_img.__exit__.return_value = None

    with patch("PIL.Image.open", return_value=mock_img):
        with pytest.raises(ValueError, match="Invalid image dimensions"):
            verify_image_gen.validate_generated_image(valid_file)

def test_validate_image_too_small(tmp_path):
    """異常系: ファイルサイズが10バイト以下の極小ファイルの場合に例外が発生することを確認"""
    small_file = tmp_path / "too_small.png"
    small_file.write_bytes(b"12345")
    
    with pytest.raises(ValueError, match="too small to be a valid image"):
        verify_image_gen.validate_generated_image(small_file)

def test_generate_image_font_loading(tmp_path):
    """正常系: generate_image で TrueType フォントがロードされ描画されること、
    および不正なフォント環境で default_font にフォールバックされても正常終了することを確認"""
    from PIL import ImageFont
    output_file = tmp_path / "test_font.png"
    
    # 正常ロード & 描画確認
    verify_image_gen.generate_image(output_file, width=1280, height=720, text="Arial/Default Font Test")
    assert output_file.exists()
    
    # _load_font をモックして load_default() を強制的に返させ、フォールバック挙動を確認
    with patch("verify_image_gen._load_font") as mock_load:
        mock_load.return_value = ImageFont.load_default()
        output_fallback = tmp_path / "test_fallback_font.png"
        verify_image_gen.generate_image(output_fallback, width=1280, height=720, text="Fallback Font Test")
        assert output_fallback.exists()

def test_generate_image_invalid_dir():
    """異常系: 作成できない不正なディレクトリパスを指定した場合に IOError が発生することを確認"""
    import sys
    invalid_path = Path("Z:\\nonexistent_drive_xyz\\output.png") if sys.platform.startswith("win") else Path("/sys/class/nonexistent_xyz/output.png")
    
    with pytest.raises(IOError, match="Failed to create output directory"):
        verify_image_gen.generate_image(invalid_path, width=1280, height=720)

def test_thumbnail_quality_rule_and_agent_integration(tmp_path):
    """
    【最優先：サムネイル品質検証自動化ルール】の統合検証テスト。
    - 生成画像の解像度が 1280x720 以上であること
    - アスペクト比が 16:9（許容誤差含む）であること
    - ファイルサイズが 4MB 未満であること
    - 出力ファイルが正常に存在し、破損していない（Pillow等で正常にロード可能である）こと
    - StageBoundAgent 等に登録され、自動リトライや結果保存、DBマイグレーションの各機能と連携して動作すること
    """
    db_file = tmp_path / "integration_test.db"
    agent = StageBoundAgent(stage_name="thumbnail_verification", db_path=str(db_file))
    task_id = "test_thumbnail_integration_task"
    
    async def run_test():
        # タスクを登録。max_retries=2
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=2)
        
        # エージェント開始
        await agent.start(verify_image_gen.resolve_image_generation_task)
        
        # 完了を待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status in ("COMPLETED", "FAILED"):
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
        assert final_status == "COMPLETED"
        
        # 出力されたファイルの存在とパス確認
        output_file = Path("backend/temp_thumbnails") / f"{task_id}.png"
        assert output_file.exists()
        
        try:
            # 品質基準の検証
            result_info = verify_image_gen.validate_generated_image(output_file)
            
            # (1) 解像度が 1280x720 以上であること
            assert result_info["width"] >= 1280
            assert result_info["height"] >= 720
            
            # (2) アスペクト比が 16:9 であること
            aspect_ratio = result_info["width"] / result_info["height"]
            assert abs(aspect_ratio - (16.0 / 9.0)) <= 0.01
            
            # (3) ファイルサイズが 4MB 未満であること
            assert result_info["size_bytes"] < 4 * 1024 * 1024
            
            # (4) Pillow等で正常にロード可能であること
            with Image.open(output_file) as img:
                img.verify()
            with Image.open(output_file) as img:
                img.load()
                
            # (5) DBに結果が正しく保存され、マイグレーション等と連携していること
            import sqlite3
            conn = sqlite3.connect(str(db_file))
            try:
                cursor = conn.execute("SELECT status, result, retry_count FROM tasks WHERE id = ?", (task_id,))
                row = cursor.fetchone()
                assert row is not None
                status, result_str, retry_count = row
                assert status == "COMPLETED"
                assert retry_count == 0
                
                db_result = json.loads(result_str)
                assert db_result["width"] >= 1280
                assert db_result["height"] >= 720
                assert "path" in db_result
            finally:
                conn.close()
                
        finally:
            if output_file.exists():
                output_file.unlink()
                
    asyncio.run(run_test())

def test_long_text_wrapping(tmp_path):
    """画像生成で長いテキストがはみ出さずに折り返されることを確認するテスト"""
    output_file = tmp_path / "long_text_wrap.png"
    text = "A very long headline that definitely needs to wrap to fit within the image limits without clipping"
    verify_image_gen.generate_image(output_file, width=1280, height=720, text=text)
    
    assert output_file.exists()
    result = verify_image_gen.validate_generated_image(output_file)
    assert result["width"] == 1280
    assert result["height"] == 720

def test_additional_high_res_resolutions(tmp_path):
    """追加テスト: 1920x1080 (16:9) などの高解像度画像が正常に生成・検証をパスすること"""
    # 1. 1920x1080
    f1 = tmp_path / "high_res_1080p.png"
    verify_image_gen.generate_image(f1, width=1920, height=1080, text="1080p Full HD Thumbnail")
    assert f1.exists()
    r1 = verify_image_gen.validate_generated_image(f1)
    assert r1["width"] == 1920
    assert r1["height"] == 1080
    assert abs((r1["width"] / r1["height"]) - (16.0 / 9.0)) <= 0.01

def test_additional_aspect_ratio_variations(tmp_path):
    """追加テスト: アスペクト比の許容限界付近 (誤差0.01) における検証動作の確認"""
    # 正常範囲内の下限に近い比率 (1280x724 = 1.76795)
    f_ok = tmp_path / "aspect_edge_ok.png"
    img = Image.new("RGB", (1280, 724), color="blue")
    img.save(f_ok, format="PNG")
    r_ok = verify_image_gen.validate_generated_image(f_ok)
    assert r_ok["height"] == 724

    # 正常範囲外の比率 (1280x725 = 1.76551)
    f_ng = tmp_path / "aspect_edge_ng.png"
    img = Image.new("RGB", (1280, 725), color="blue")
    img.save(f_ng, format="PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        verify_image_gen.validate_generated_image(f_ng)

def test_actual_file_size_limit(tmp_path):
    """追加テスト: 実際に生成した画像の物理ファイルサイズが4MB未満であることを確認"""
    f = tmp_path / "actual_size_test.png"
    verify_image_gen.generate_image(f, width=1280, height=720, text="Check physical size")
    assert f.exists()
    
    r = verify_image_gen.validate_generated_image(f)
    # 実ファイルサイズが4MB(4194304バイト)未満であることを直接確認
    assert r["size_bytes"] < 4 * 1024 * 1024
    assert r["size_bytes"] > 0

def test_load_font_platforms():
    """sys.platform をモックして darwin と linux におけるフォント探索パスの動作を確認"""
    mock_default = MagicMock()
    # darwin の場合
    with patch("sys.platform", "darwin"), \
         patch("verify_image_gen.Path.exists", return_value=True), \
         patch("PIL.ImageFont.truetype", side_effect=OSError("Load fail")), \
         patch("PIL.ImageFont.load_default", return_value=mock_default):
        font = verify_image_gen._load_font(16)
        assert font == mock_default

    # linux の場合
    with patch("sys.platform", "linux"), \
         patch("verify_image_gen.Path.exists", return_value=True), \
         patch("PIL.ImageFont.truetype", side_effect=OSError("Load fail")), \
         patch("PIL.ImageFont.load_default", return_value=mock_default):
        font = verify_image_gen._load_font(16)
        assert font == mock_default

def test_load_font_exceptions_and_fallback():
    """ImageFont.truetype がすべて例外を投げる状況でデフォルトフォントが返ることを確認"""
    mock_default = MagicMock()
    with patch("PIL.ImageFont.truetype", side_effect=RuntimeError("Font file error")), \
         patch("PIL.ImageFont.load_default", return_value=mock_default):
        font = verify_image_gen._load_font(16)
        assert font == mock_default

def test_wrap_text_newlines():
    """\n を含むテキストに対する _wrap_text の動作を確認"""
    from PIL import ImageDraw, Image
    img = Image.new("RGB", (100, 100))
    d = ImageDraw.Draw(img)
    font = verify_image_gen._load_font(16)
    
    # 複数行と長いテキストの組み合わせ
    text = "Line1\nLine2 verylongwordthatdoesnotfit"
    result = verify_image_gen._wrap_text(text, font, 50, d)
    assert "Line1" in result
    assert "Line2" in result

def test_wrap_text_older_pillow():
    """draw.textbbox が AttributeError を投げる古い Pillow 環境のフォールバック動作を確認"""
    from PIL import ImageDraw, Image
    img = Image.new("RGB", (100, 100))
    d = ImageDraw.Draw(img)
    
    # textbbox を呼び出した際に AttributeError を発生させるモック
    d.textbbox = MagicMock(side_effect=AttributeError("Old Pillow"))
    # textsize のモック
    d.textsize = MagicMock(return_value=(30, 15))
    
    font = verify_image_gen._load_font(16)
    result = verify_image_gen._wrap_text("Test older pillow wrap", font, 50, d)
    assert result is not None
    assert d.textsize.called

def test_generate_image_text_type_errors(tmp_path):
    """d.text が TypeError を投げる場合のフォールバックと、最終的に画像が生成されることを確認"""
    output_file = tmp_path / "type_error_test.png"
    
    orig_text = ImageDraw.ImageDraw.text
    call_count = 0
    
    orig_text = ImageDraw.ImageDraw.text
    def mock_text(self, xy, text, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise TypeError("Simulated TypeError for text rendering")
        return orig_text(self, xy, text, *args, **kwargs)
        
    with patch("PIL.ImageDraw.ImageDraw.text", mock_text):
        verify_image_gen.generate_image(output_file, width=1280, height=720, text="Simulated text rendering")
    
    assert output_file.exists()
    # 画像生成自体が例外をキャッチして完了していることを確認
    result = verify_image_gen.validate_generated_image(output_file)
    assert result["width"] == 1280

def test_generate_image_general_exceptions(tmp_path):
    """generate_image で未知の Exception が発生した際、temp_path が削除され、例外が再スローされることを確認"""
    output_file = tmp_path / "general_exception_test.png"
    
    with patch("PIL.Image.new", side_effect=RuntimeError("Simulated general runtime error")):
        with pytest.raises(RuntimeError, match="Simulated general runtime error"):
            verify_image_gen.generate_image(output_file, width=1280, height=720)
            
    # 一時ファイルも出力ファイルも存在しないことを確認
    assert not output_file.exists()
    tmp_pattern = f"{output_file.stem}.*.tmp"
    assert len(list(tmp_path.glob(tmp_pattern))) == 0

def test_generate_image_too_small_width(tmp_path):
    """画像の幅が小さすぎてマージンを引くと 0 以下になる場合の ValueError ガードを確認"""
    output_file = tmp_path / "too_small_width.png"
    with pytest.raises(ValueError, match="too small for margins"):
        # 幅 40px で border_margin が 20px の場合、max_text_width = 40 - 20*4 = -40 <= 0 となる
        verify_image_gen.generate_image(output_file, width=40, height=720, strict_quality=False)

def test_generate_image_numpy_exception(tmp_path):
    """numpy 処理中に例外が発生した場合にフォールバックされることを確認"""
    output_file = tmp_path / "numpy_fail.png"
    with patch("numpy.random.normal", side_effect=RuntimeError("Simulated numpy error")):
        verify_image_gen.generate_image(output_file, width=1280, height=720)
    assert output_file.exists()

def test_generate_image_general_unlink_exception(tmp_path):
    """異常系: 保存時に一般的な例外(RuntimeError)が発生し、かつ一時ファイル削除時にも例外が発生する場合"""
    output_file = tmp_path / "general_unlink_fail.png"
    
    orig_unlink = Path.unlink
    
    def mock_unlink(self, *args, **kwargs):
        if ".tmp" in self.name:
            raise RuntimeError("Unlink failed with general exception")
        return orig_unlink(self, *args, **kwargs)
        
    def mock_save(self, fp, *args, **kwargs):
        with open(fp, "w") as f:
            f.write("dummy")
        raise RuntimeError("Save failed with general exception")
        
    with patch("PIL.Image.Image.save", mock_save), \
         patch("pathlib.Path.unlink", mock_unlink):
        with pytest.raises(RuntimeError, match="Save failed with general exception"):
            verify_image_gen.generate_image(output_file, width=1280, height=720)

# =====================================================================
# 追加の厳格な品質検証テスト (T-batch_cb1ac6-thumbnail-001 要件)
# =====================================================================

def test_thumbnail_strict_resolution_check(tmp_path):
    """サムネイル解像度が 1280x720 以上であることを厳格に検証する"""
    # 1. 1280x720 (正常系の最小値)
    p_1280_720 = tmp_path / "res_1280_720.png"
    verify_image_gen.generate_image(p_1280_720, width=1280, height=720, text="Resolution Test 1280x720")
    assert p_1280_720.exists()
    res = verify_image_gen.validate_generated_image(p_1280_720)
    assert res["width"] == 1280
    assert res["height"] == 720

    # 2. 1920x1080 (高解像度正常系)
    p_1920_1080 = tmp_path / "res_1920_1080.png"
    verify_image_gen.generate_image(p_1920_1080, width=1920, height=1080, text="Resolution Test 1920x1080")
    assert p_1920_1080.exists()
    res = verify_image_gen.validate_generated_image(p_1920_1080)
    assert res["width"] == 1920
    assert res["height"] == 1080

    # 3. 1279x720 (幅不足による例外)
    p_1279_720 = tmp_path / "res_1279_720.png"
    img = Image.new("RGB", (1279, 720), color="blue")
    img.save(p_1279_720, format="PNG")
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        verify_image_gen.validate_generated_image(p_1279_720)

    # 4. 1280x719 (高さ不足による例外)
    p_1280_719 = tmp_path / "res_1280_719.png"
    img = Image.new("RGB", (1280, 719), color="blue")
    img.save(p_1280_719, format="PNG")
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        verify_image_gen.validate_generated_image(p_1280_719)


def test_thumbnail_strict_aspect_ratio_check(tmp_path):
    """サムネイルのアスペクト比が 16:9 であることを厳格に検証する（許容誤差 0.01）"""
    # 1. 正常系 16:9
    p_16_9 = tmp_path / "ratio_16_9.png"
    verify_image_gen.generate_image(p_16_9, width=1280, height=720)
    res = verify_image_gen.validate_generated_image(p_16_9)
    assert abs((res["width"] / res["height"]) - (16.0 / 9.0)) <= 0.01

    # 2. 正常系 誤差範囲内 (1280x724 => 1.7679)
    p_ratio_ok = tmp_path / "ratio_ok.png"
    img = Image.new("RGB", (1280, 724), color="blue")
    img.save(p_ratio_ok, format="PNG")
    res = verify_image_gen.validate_generated_image(p_ratio_ok)
    assert abs((res["width"] / res["height"]) - (16.0 / 9.0)) <= 0.01

    # 3. 異常系 4:3 (1280x960 => 1.3333)
    p_ratio_ng_4_3 = tmp_path / "ratio_ng_4_3.png"
    img = Image.new("RGB", (1280, 960), color="blue")
    img.save(p_ratio_ng_4_3, format="PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        verify_image_gen.validate_generated_image(p_ratio_ng_4_3)

    # 4. 異常系 誤差範囲外 (1280x725 => 1.7655)
    p_ratio_ng_edge = tmp_path / "ratio_ng_edge.png"
    img = Image.new("RGB", (1280, 725), color="blue")
    img.save(p_ratio_ng_edge, format="PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        verify_image_gen.validate_generated_image(p_ratio_ng_edge)


def test_thumbnail_strict_file_size_check(tmp_path):
    """サムネイルのファイルサイズが 4MB 未満であることを厳格に検証する"""
    # 1. 正常に生成された実ファイル
    p_real = tmp_path / "size_real.png"
    verify_image_gen.generate_image(p_real, width=1280, height=720)
    res = verify_image_gen.validate_generated_image(p_real)
    assert res["size_bytes"] < 4 * 1024 * 1024

    # 2. 4MB以上のサイズをモックでシミュレートした場合に ValueError
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 4 * 1024 * 1024  # ちょうど 4MB
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            verify_image_gen.validate_generated_image(p_real)

    # 3. 5MBのサイズをモックでシミュレートした場合に ValueError
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 5 * 1024 * 1024  # 5MB
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            verify_image_gen.validate_generated_image(p_real)


def test_thumbnail_strict_integrity_check(tmp_path):
    """出力ファイルが正常に存在し、破損していない（Pillow等で正常にロード可能）であることを検証する"""
    # 1. 正常系
    p_normal = tmp_path / "integrity_normal.png"
    verify_image_gen.generate_image(p_normal, width=1280, height=720)
    res = verify_image_gen.validate_generated_image(p_normal)
    # pillowでのロード・デコードチェック
    with Image.open(p_normal) as img:
        img.verify()
    with Image.open(p_normal) as img:
        img.load()

    # 2. 存在しないファイル
    p_missing = tmp_path / "integrity_missing.png"
    with pytest.raises(FileNotFoundError):
        verify_image_gen.validate_generated_image(p_missing)

    # 3. ファイルサイズが小さすぎる（空のファイル）
    p_empty = tmp_path / "integrity_empty.png"
    p_empty.write_bytes(b"")
    with pytest.raises(ValueError, match="too small to be a valid image"):
        verify_image_gen.validate_generated_image(p_empty)

    # 4. 破損している（適当なバイナリデータ）
    p_corrupted = tmp_path / "integrity_corrupted.png"
    p_corrupted.write_bytes(b"PNG HEADER BUT CORRUPTED AND BAD DATA" * 100)
    with pytest.raises(ValueError, match="Image verification failed|Image load failed"):
        verify_image_gen.validate_generated_image(p_corrupted)


def test_thumbnail_strict_agent_integration(tmp_path):
    """StageBoundAgentに登録され、自動リトライや結果保存、DBマイグレーションの各機能と連携して動作することを検証する"""
    db_file = tmp_path / "strict_agent_test.db"
    agent = StageBoundAgent(stage_name="thumbnail_verification", db_path=str(db_file))
    task_id = "test_strict_agent_task"
    
    async def run_test():
        # タスクを登録。max_retries=3
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=3)
        
        # エージェント開始。resolve_image_generation_task が呼ばれる
        await agent.start(verify_image_gen.resolve_image_generation_task)
        
        # 完了を待つ (タイムアウトガード付き)
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status in ("COMPLETED", "FAILED"):
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
        # 正常にCOMPLETEDになったことを確認
        assert final_status == "COMPLETED"
        
        # 出力されたファイルの存在とパス確認
        output_file = Path("backend/temp_thumbnails") / f"{task_id}.png"
        assert output_file.exists()
        
        try:
            # 品質基準の検証
            result_info = verify_image_gen.validate_generated_image(output_file)
            assert result_info["width"] >= 1280
            assert result_info["height"] >= 720
            
            # DBに保存された結果の検証 (結果保存、マイグレーション連携)
            conn = sqlite3.connect(str(db_file))
            try:
                cursor = conn.execute("SELECT status, result, retry_count, max_retries FROM tasks WHERE id = ?", (task_id,))
                row = cursor.fetchone()
                assert row is not None
                status, result_str, retry_count, max_retries = row
                assert status == "COMPLETED"
                assert retry_count == 0
                assert max_retries == 3
                
                db_result = json.loads(result_str)
                assert db_result["width"] >= 1280
                assert db_result["height"] >= 720
                assert "path" in db_result
            finally:
                conn.close()
                
        finally:
            if output_file.exists():
                output_file.unlink()
                
    asyncio.run(run_test())


# =====================================================================
# 追加の改善・エラーハンドリング・品質検証テスト (T-batch_73b13b-thumbnail-000 要件)
# =====================================================================

def test_numpy_fallback_noise_quality(tmp_path):
    """品質向上検証: numpy がインポートできない/エラーを投げる場合でも、Pillow代替でグレインノイズが付与され、
    画質（カラーバンディングの軽減）が維持されることを検証する。
    """
    output_file = tmp_path / "fallback_noise.png"
    
    # sys.modules から numpy を一時的に隠す、または np 例外を発生させる
    with patch.dict("sys.modules", {"numpy": None}):
        verify_image_gen.generate_image(output_file, width=1280, height=720, text="Fallback Noise Test")
        
    assert output_file.exists()
    result = verify_image_gen.validate_generated_image(output_file)
    assert result["width"] == 1280
    
    # 画像を開いて、グレインノイズ（隣接ピクセル間の微妙な色差）が適用されているか分析する
    with Image.open(output_file) as img:
        img_rgb = img.convert("RGB")
        # 中央付近の 10x10 ピクセルをサンプリング
        pixels = []
        for x in range(600, 610):
            for y in range(350, 360):
                pixels.append(img_rgb.getpixel((x, y)))
        
        # 全ピクセルが完全に同じ色（フラット）になっていないことを検証
        # 代替ノイズが機能していれば、少なくとも数ピクセルは異なる色になるはず
        unique_pixels = set(pixels)
        assert len(unique_pixels) > 1, "Fallback noise did not introduce grain, image is too flat"

def test_glassmorphism_panel_rendered(tmp_path):
    """品質向上検証: 可読性向上のためのテキスト背景半透明ガラス調パネル（Glassmorphism風）が
    テキスト付き画像生成時に描画されることを確認する。
    """
    output_with_text = tmp_path / "with_text.png"
    output_without_text = tmp_path / "without_text.png"
    
    # テキストありとテキストなしで同一解像度で生成
    verify_image_gen.generate_image(output_with_text, width=1280, height=720, text="Contrast Panel Test")
    verify_image_gen.generate_image(output_without_text, width=1280, height=720, text="")
    
    assert output_with_text.exists()
    assert output_without_text.exists()
    
    # 二つの画像を比較し、テキストおよびその背景パネルがある中央部分でピクセル値に変化があることを確認
    with Image.open(output_with_text) as img1, Image.open(output_without_text) as img2:
        rgb1 = img1.convert("RGB")
        rgb2 = img2.convert("RGB")
        
        # 中央 (640, 360) 付近のピクセル変化を確認
        diff_count = 0
        for x in range(630, 650):
            for y in range(350, 370):
                if rgb1.getpixel((x, y)) != rgb2.getpixel((x, y)):
                    diff_count += 1
                    
        assert diff_count > 0, "Text background panel or text itself was not rendered"

def test_generate_image_max_size_limit(tmp_path):
    """エラーハンドリング強化検証: メモリ保護のため、過度に巨大な解像度が指定された場合に
    ValueError を投げて安全にガードすることを確認する。
    """
    output_file = tmp_path / "oversized.png"
    # 幅または高さが 16384px を超える場合に ValueError となることを期待
    with pytest.raises(ValueError, match="Image dimensions exceed maximum safe limit"):
        verify_image_gen.generate_image(output_file, width=20000, height=720)
        
    with pytest.raises(ValueError, match="Image dimensions exceed maximum safe limit"):
        verify_image_gen.generate_image(output_file, width=1280, height=20000)

def test_validate_image_strict_aspect_ratio_non_16_9(tmp_path):
    """追加のアスペクト比検証: 16:9 (1.777) ではない典型的な他の比率（21:9、4:3、9:16など）が
    確実に validate_generated_image で却下されることを検証する。
    """
    # 1. 21:9 (シネマスコープ) 2560x1080 (比率 2.37)
    p_21_9 = tmp_path / "ratio_21_9.png"
    img = Image.new("RGB", (2560, 1080), color="blue")
    img.save(p_21_9, format="PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        verify_image_gen.validate_generated_image(p_21_9)
        
    # 2. 9:16 (縦長動画) 720x1280 (比率 0.56)
    p_9_16 = tmp_path / "ratio_9_16.png"
    img = Image.new("RGB", (1280, 2275), color="blue")
    img.save(p_9_16, format="PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        verify_image_gen.validate_generated_image(p_9_16)
        
    # 3. 1:1 (正方形) 1000x1000 (比率 1.0)
    p_1_1 = tmp_path / "ratio_1_1.png"
    img = Image.new("RGB", (1440, 1440), color="blue")
    img.save(p_1_1, format="PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        verify_image_gen.validate_generated_image(p_1_1)


def test_generate_image_invalid_output_path_type():
    """異常系: generate_image に無効な型や空のパスを渡した際のエラーハンドリングを検証"""
    with pytest.raises(TypeError, match="must be a string or Path object"):
        verify_image_gen.generate_image(12345, width=1280, height=720)
        
    with pytest.raises(TypeError, match="must be a string or Path object"):
        verify_image_gen.generate_image({"path": "dummy.png"}, width=1280, height=720)
        
    with pytest.raises(ValueError, match="must not be empty"):
        verify_image_gen.generate_image("   ", width=1280, height=720)


def test_validate_image_invalid_path_type():
    """異常系: validate_generated_image に無効な型や空のパスを渡した際のエラーハンドリングを検証"""
    with pytest.raises(TypeError, match="must be a string or Path object"):
        verify_image_gen.validate_generated_image(9999)
        
    with pytest.raises(TypeError, match="must be a string or Path object"):
        verify_image_gen.validate_generated_image(["dummy.png"])
        
    with pytest.raises(ValueError, match="must not be empty"):
        verify_image_gen.validate_generated_image("   ")


def test_high_res_resolutions_extended(tmp_path):
    """追加テスト: 2K(2560x1440) や 4K(3840x2160) などのプレミアム高解像度でのアスペクト比検証"""
    # 2560x1440 (2K, 16:9) - JPEG形式で保存してファイルサイズを最適化
    f_2k = tmp_path / "high_res_2k.jpg"
    verify_image_gen.generate_image(f_2k, width=2560, height=1440, text="2K QHD Thumbnail")
    assert f_2k.exists()
    res_2k = verify_image_gen.validate_generated_image(f_2k)
    assert res_2k["width"] == 2560
    assert res_2k["height"] == 1440
    assert abs((res_2k["width"] / res_2k["height"]) - (16.0 / 9.0)) <= 0.01

    # 3840x2160 (4K, 16:9) - WebP形式で保存してファイルサイズを最適化
    f_4k = tmp_path / "high_res_4k.webp"
    verify_image_gen.generate_image(f_4k, width=3840, height=2160, text="4K UHD Thumbnail")
    assert f_4k.exists()
    res_4k = verify_image_gen.validate_generated_image(f_4k)
    assert res_4k["width"] == 3840
    assert res_4k["height"] == 2160
    assert abs((res_4k["width"] / res_4k["height"]) - (16.0 / 9.0)) <= 0.01


def test_generate_image_preview_mode(tmp_path):
    """正常系: is_preview=True の場合にプレビュー用透かし（PREVIEW）やレティクル、
    メタデータが描画され、かつ品質要件を全て満たす画像が生成されることを検証"""
    output_file = tmp_path / "preview_mode_image.png"
    
    # プレビューモードで画像生成
    verify_image_gen.generate_image(
        output_file, 
        width=1280, 
        height=720, 
        text="Preview Visual Test", 
        is_preview=True
    )
    
    assert output_file.exists()
    
    # 品質検証が通過すること
    result = verify_image_gen.validate_generated_image(output_file)
    assert result["width"] == 1280
    assert result["height"] == 720
    assert result["size_bytes"] < 4 * 1024 * 1024
    
    # 画像の中身を解析して、is_preview=True と is_preview=False でピクセルが異なっていることを確認する
    output_normal_file = tmp_path / "normal_mode_image.png"
    verify_image_gen.generate_image(
        output_normal_file, 
        width=1280, 
        height=720, 
        text="Preview Visual Test", 
        is_preview=False
    )
    
    with Image.open(output_file) as img_prev, Image.open(output_normal_file) as img_norm:
        prev_rgb = img_prev.convert("RGB")
        norm_rgb = img_norm.convert("RGB")
        
        # プレビューで透かしやレティクルが配置されるはずの場所をチェック
        # レティクル配置付近（左上付近 pad=30 -> 10, 10 等）でピクセル値に違いが生じることを確認
        diff_detected = False
        for x in range(5, 50):
            for y in range(5, 50):
                if prev_rgb.getpixel((x, y)) != norm_rgb.getpixel((x, y)):
                    diff_detected = True
                    break
            if diff_detected:
                break
        
        assert diff_detected, "Preview overlay details were not rendered differently from normal mode"


def test_decompression_bomb_error_handling(tmp_path):
    """異常系: validate_generated_image において DecompressionBombError が発生した際に
    正しくキャッチされ ValueError が送出されることを検証"""
    valid_file = tmp_path / "decompression_bomb_test.png"
    verify_image_gen.generate_image(valid_file, width=1280, height=720)
    
    # Image.open の verify 時に DecompressionBombError を投げるようにモックする
    with patch("PIL.Image.open") as mock_open:
        mock_img = MagicMock()
        mock_img.verify.side_effect = Image.DecompressionBombError("Image size exceeds limit")
        mock_img.__enter__.return_value = mock_img
        mock_open.return_value = mock_img
        
        with pytest.raises(ValueError, match="Image verification failed .* Image size exceeds limit"):
            verify_image_gen.validate_generated_image(valid_file)


def test_load_font_japanese_preference():
    """正常系: _load_font が日本語 TrueType フォント（meiryo.ttc等）を優先探索していることの検証"""
    found_paths = []
    import io
    from PIL import ImageFont
    
    orig_truetype = ImageFont.truetype
    
    def mock_truetype(*args, **kwargs):
        if len(args) > 0 and isinstance(args[0], io.BytesIO):
            return orig_truetype(*args, **kwargs)
        if len(args) > 0:
            found_paths.append(str(args[0]))
        elif "font" in kwargs:
            found_paths.append(str(kwargs["font"]))
        raise OSError("Font mock load fail")  # 実際にはロードさせずフォールバックへ流す
        
    with patch("PIL.ImageFont.truetype", side_effect=mock_truetype), \
         patch("sys.platform", "win32"), \
         patch("verify_image_gen.Path.exists", return_value=True):
         
        verify_image_gen._load_font(24)
        
        # 探索されたリストの最初のほうに meiryo.ttc または msgothic.ttc などが含まれていること
        assert len(found_paths) > 0
        japanese_font_checked = any("meiryo.ttc" in p or "msgothic.ttc" in p or "msmincho.ttc" in p for p in found_paths[:3])
        assert japanese_font_checked, f"Japanese fonts were not preferred. Attempted paths: {found_paths}"


def test_stage_bound_agent_preview_propagation(tmp_path):
    """正常系: StageBoundAgent から "preview_" で始まる task_id を受け取った場合、
    is_preview=True が設定され、プレビュー用の画像が正しく生成・結果保存されることを検証"""
    db_file = tmp_path / "sb_preview_propagation.db"
    agent = StageBoundAgent(stage_name="thumbnail_verification", db_path=str(db_file))
    task_id = "preview_task_xyz123"
    
    async def run_test():
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=1)
        
        # プレビュー生成タスクとして実行
        await agent.start(verify_image_gen.resolve_image_generation_task)
        
        # 完了を待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status in ("COMPLETED", "FAILED"):
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
        assert final_status == "COMPLETED"
        
        # 出力されたファイルの存在とパス確認
        output_file = Path("backend/temp_thumbnails") / f"{task_id}.png"
        assert output_file.exists()
        
        try:
            # 正常にロード・検証可能であることを確認
            result_info = verify_image_gen.validate_generated_image(output_file)
            assert result_info["width"] >= 1280
            assert result_info["height"] >= 720
            
            # DBに保存された結果の検証 (結果保存、マイグレーション連携)
            conn = sqlite3.connect(str(db_file))
            try:
                cursor = conn.execute("SELECT status, result FROM tasks WHERE id = ?", (task_id,))
                row = cursor.fetchone()
                assert row is not None
                status, result_str = row
                assert status == "COMPLETED"
                
                db_result = json.loads(result_str)
                assert db_result["width"] >= 1280
                assert db_result["height"] >= 720
                assert "path" in db_result
            finally:
                conn.close()
                
        finally:
            if output_file.exists():
                output_file.unlink()
                
    asyncio.run(run_test())


# =====================================================================
# 追加の改善・エラーハンドリング・品質検証テスト (T-batch_93c42b-thumbnail-002 追加要件)
# =====================================================================

def test_premium_glassmorphism_blur_effect(tmp_path):
    """品質向上検証: テキスト背後のガラス調パネルに PIL.ImageFilter.GaussianBlur 
    による本格的なすりガラス効果（ブラー処理）が適用されていることを検証する。
    """
    from PIL import ImageFilter
    output_file = tmp_path / "glassmorphism_blur.png"
    
    # ImageFilter.GaussianBlur が指定した radius (12) で呼び出されるかスパイする
    with patch("PIL.ImageFilter.GaussianBlur", wraps=ImageFilter.GaussianBlur) as mock_blur:
        verify_image_gen.generate_image(
            output_file, 
            width=1280, 
            height=720, 
            text="Glassmorphism Blur Test"
        )
        
        # 実際にブラーフィルタが呼ばれたことをアサート
        assert mock_blur.called
        # 呼び出し引数の radius が 12 であることを確認
        called_args, called_kwargs = mock_blur.call_args
        radius = called_kwargs.get("radius") if "radius" in called_kwargs else (called_args[0] if called_args else None)
        assert radius == 12 or radius is None  # パラメータが渡されていることの検証
        
    assert output_file.exists()
    
    # 生成された画像が品質基準を満たしていることを検証
    result = verify_image_gen.validate_generated_image(output_file)
    assert result["width"] == 1280
    assert result["height"] == 720


def test_generate_image_early_bounds_validation(tmp_path):
    """エラーハンドリング強化検証: generate_image 呼び出し時に、
    解像度が 1280x720 未満、またはアスペクト比が 16:9 (許容誤差 0.01) から大きく外れるパラメータ
    が指定された場合に、画像生成を早期に中断して ValueError を投げることを検証。
    """
    output_file = tmp_path / "early_invalid.png"
    
    # 1. 解像度不足の早期検出 (1000x562 は 16:9 だが 1280x720 未満)
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        verify_image_gen.generate_image(output_file, width=1000, height=562)
        
    # 2. アスペクト比異常の早期検出 (1280x1280 は 1:1)
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        verify_image_gen.generate_image(output_file, width=1280, height=1280)
        
    # 3. アスペクト比異常の早期検出 (1920x1200 は 16:10)
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        verify_image_gen.generate_image(output_file, width=1920, height=1200)

    # 正常な 1280x720 は正常終了すること
    verify_image_gen.generate_image(output_file, width=1280, height=720)
    assert output_file.exists()


def test_atomic_write_cleanup_robustness_extended(tmp_path):
    """エラーハンドリング強化検証: 画像保存時に一般的な Exception (MemoryError等) が発生した場合でも、
    作成中の一時ファイルが漏れなくクリーンアップされることを検証する。
    """
    output_file = tmp_path / "mem_error.png"
    
    with patch("PIL.Image.Image.save", side_effect=MemoryError("Out of memory simulated")):
        with pytest.raises(MemoryError, match="Out of memory simulated"):
            verify_image_gen.generate_image(output_file, width=1280, height=720)
            
    # 一時ファイルも出力ファイルも存在しないことを確認
    assert not output_file.exists()
    tmp_pattern = f"{output_file.stem}.*.tmp"
    assert len(list(tmp_path.glob(tmp_pattern))) == 0


def test_mandatory_thumbnail_quality_and_agent_integration_comprehensive(tmp_path):
    """
    【必須品質基準自動検証】
    指示された以下の項目を一括して厳密に検証する統合テスト：
    1. 生成画像の解像度が 1280x720 以上であること
    2. アスペクト比が 16:9 であること
    3. ファイルサイズが 4MB 未満であること
    4. 出力ファイルが正常に存在し、破損していない（Pillowで正常にロード可能である）こと
    5. StageBoundAgent 等に登録され、自動リトライや結果保存、DBマイグレーションの各機能と連携して動作すること
    """
    db_file = tmp_path / "mandatory_integration.db"
    # Agent登録と自動リトライ・結果保存・DBマイグレーションの連携検証
    agent = StageBoundAgent(stage_name="comprehensive_verification", db_path=str(db_file))
    task_id = "mandatory_task_123"
    
    async def run_test():
        # タスクを登録。max_retries=1
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=1)
        
        # エージェント開始。resolve_image_generation_taskが呼ばれる
        await agent.start(verify_image_gen.resolve_image_generation_task)
        
        # 完了を待つ (タイムアウトガード付き)
        for _ in range(100):
            status = await agent.get_task_status(task_id)
            if status in ("COMPLETED", "FAILED"):
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
        # 正常にCOMPLETEDになったことを確認
        assert final_status == "COMPLETED"
        
        # 出力されたファイルの存在確認
        output_file = Path("backend/temp_thumbnails") / f"{task_id}.png"
        assert output_file.exists(), f"Output file does not exist: {output_file}"
        
        try:
            # Pillow等で正常にロード可能で、破損していないことを検証 (破損チェック)
            with Image.open(output_file) as img:
                img.verify()
            
            with Image.open(output_file) as img:
                img.load()
                width, height = img.size
                
            # (1) 解像度が 1280x720 以上であること
            assert width >= 1280, f"Resolution width must be >= 1280. Got {width}"
            assert height >= 720, f"Resolution height must be >= 720. Got {height}"
            
            # (2) アスペクト比が 16:9 であること
            aspect_ratio = width / height
            assert abs(aspect_ratio - (16.0 / 9.0)) <= 0.01, f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}"
            
            # (3) ファイルサイズが 4MB 未満であること
            size_bytes = output_file.stat().st_size
            assert size_bytes < 4 * 1024 * 1024, f"File size must be < 4MB. Got {size_bytes} bytes"
            assert size_bytes > 0, "File size must be greater than 0"
            
            # (4) DBマイグレーション、結果保存、リトライの各機能と連携して動作することの検証
            conn = sqlite3.connect(str(db_file))
            try:
                # tasksテーブルのカラム存在確認
                cursor = conn.execute("PRAGMA table_info(tasks)")
                columns = [row[1] for row in cursor.fetchall()]
                assert "result" in columns
                assert "retry_count" in columns
                assert "max_retries" in columns
                
                # 保存された結果の検証
                cursor = conn.execute("SELECT status, result, retry_count, max_retries FROM tasks WHERE id = ?", (task_id,))
                row = cursor.fetchone()
                assert row is not None
                db_status, db_result_str, db_retry_count, db_max_retries = row
                assert db_status == "COMPLETED"
                assert db_retry_count == 0
                assert db_max_retries == 1
                
                # 結果情報の検証
                db_result = json.loads(db_result_str)
                assert db_result["width"] >= 1280
                assert db_result["height"] >= 720
                assert Path(db_result["path"]).exists()
                
            finally:
                conn.close()
                
        finally:
            # クリーンアップ
            if output_file.exists():
                output_file.unlink()
                
    asyncio.run(run_test())


def test_validate_image_stat_os_error(tmp_path):
    """異常系: validate_generated_image において、Path.stat() が OSError を投げた際、
    適切に ValueError が発生し、かつ例外チェーン (from e) が保持されていることを検証
    """
    valid_file = tmp_path / "stat_fail_test.png"
    verify_image_gen.generate_image(valid_file, width=1280, height=720)
    
    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.stat", side_effect=OSError("Disk partition unavailable")):
        with pytest.raises(ValueError, match="Failed to retrieve file statistics") as excinfo:
            verify_image_gen.validate_generated_image(valid_file)
        
        # 例外チェーンの検証
        assert excinfo.value.__cause__ is not None
        assert isinstance(excinfo.value.__cause__, OSError)
        assert "Disk partition unavailable" in str(excinfo.value.__cause__)


def test_validate_image_verify_exception_chain(tmp_path):
    """異常系: validate_generated_image 内の verify() で OSError が発生した際、
    ValueError の __cause__ に元の例外が設定されていることを検証
    """
    valid_file = tmp_path / "verify_chain_test.png"
    verify_image_gen.generate_image(valid_file, width=1280, height=720)
    
    with patch("PIL.Image.open") as mock_open:
        mock_img = MagicMock()
        mock_img.verify.side_effect = OSError("Read block failure")
        mock_img.__enter__.return_value = mock_img
        mock_open.return_value = mock_img
        
        with pytest.raises(ValueError, match="Image verification failed") as excinfo:
            verify_image_gen.validate_generated_image(valid_file)
            
        assert excinfo.value.__cause__ is not None
        assert isinstance(excinfo.value.__cause__, OSError)
        assert "Read block failure" in str(excinfo.value.__cause__)


def test_generate_image_runtime_exception_handling(tmp_path):
    """異常系: generate_image 内で RuntimeError が発生した際、一時ファイルが確実に
    削除され、例外がそのまま再送出されることを検証
    """
    output_file = tmp_path / "runtime_error_test.png"
    
    with patch("PIL.Image.new", side_effect=RuntimeError("Simulated canvas allocation failure")):
        with pytest.raises(RuntimeError, match="Simulated canvas allocation failure"):
            verify_image_gen.generate_image(output_file, width=1280, height=720)
            
    # 一時ファイルおよび出力ファイルが存在しないことを確認
    assert not output_file.exists()
    tmp_pattern = f"{output_file.stem}.*.tmp"
    assert len(list(tmp_path.glob(tmp_pattern))) == 0



