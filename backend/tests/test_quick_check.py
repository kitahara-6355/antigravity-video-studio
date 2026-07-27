import sys
import os
import runpy
from unittest.mock import MagicMock, patch
from pathlib import Path
import pytest

from quick_check import fPath, run_segment, main

def test_fpath():
    # Windowsパスエスケープ関数のテスト
    assert fPath("C:\\path\\to\\file") == "C\\\\:/path/to/file"
    assert fPath("C:\\path:to\\file") == "C\\\\:/path\\\\:to/file"

def test_run_segment(safe_popen_mock):
    mock_proc = safe_popen_mock(returncode=0)
    with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
        proc = run_segment("scene01", "input.mp4", 0, 10, "1152:720:26:0", "srt.srt", 0)
        assert proc == mock_proc
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert args[0] == "ffmpeg"
        assert "-ss" in args
        assert "subtitles='srt.srt'" in args[args.index("-vf") + 1]

def test_run_segment_no_srt(safe_popen_mock):
    mock_proc = safe_popen_mock(returncode=0)
    with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
        proc = run_segment("scene02", "input.mp4", 0, 10, "1920:960:0:60", None, 3)
        assert proc == mock_proc
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert "subtitles" not in args[args.index("-vf") + 1]

def test_main(safe_popen_mock):
    mock_proc = safe_popen_mock(returncode=0)
    
    # Path.mkdir と subprocess.Popen をモック
    with patch("pathlib.Path.mkdir") as mock_mkdir, \
         patch("subprocess.Popen", return_value=mock_proc) as mock_popen, \
         patch("builtins.print") as mock_print:
         
        main()
        
        assert mock_mkdir.call_count == 1
        assert mock_popen.call_count == 4
        # wait が 4 回呼ばれたか
        assert mock_proc.wait.call_count == 4
        mock_print.assert_called_with("DONE_CHECKPOINTS")

def test_run_module(safe_popen_mock):
    mock_proc = safe_popen_mock(returncode=0)
    
    with patch("pathlib.Path.mkdir") as mock_mkdir, \
         patch("subprocess.Popen", return_value=mock_proc) as mock_popen, \
         patch("builtins.print") as mock_print:
         
        runpy.run_module("quick_check", run_name="__main__")
        
        assert mock_mkdir.call_count == 1
        assert mock_popen.call_count == 4
        assert mock_proc.wait.call_count == 4
        mock_print.assert_called_with("DONE_CHECKPOINTS")

def test_fpath_edge_cases():
    # ドライブレターがない相対パス
    assert fPath("relative\\path\\to\\file") == "relative/path/to/file"
    # UNIXライクなスラッシュのみのパス
    assert fPath("/usr/bin/ffmpeg") == "/usr/bin/ffmpeg"
    # 空パス
    assert fPath("") == ""
    # コロンとバックスラッシュの複雑な組み合わせ
    assert fPath("C:\\a\\b:c\\d:e") == "C\\\\:/a/b\\\\:c/d\\\\:e"

def test_run_segment_edge_cases(safe_popen_mock):
    mock_proc = safe_popen_mock(returncode=0)
    with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
        # negative start time and negative duration (ffmpeg arguments verify only)
        proc = run_segment("scene_neg", "input.mp4", -5, -10, "100:100:0:0", "srt.srt", -1)
        assert proc == mock_proc
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        # start, duration の引数が文字列として渡されているか
        assert "-ss" in args
        assert args[args.index("-ss") + 1] == "-5"
        assert "-t" in args
        assert args[args.index("-t") + 1] == "-10"
        # telop_idx = -1
        assert "brand_telop_-1.png" in args[args.index("-vf") + 1]

def test_main_mkdir_permission_error(safe_popen_mock):
    mock_proc = safe_popen_mock(returncode=0)
    # mkdir が PermissionError を投げる場合
    with patch("pathlib.Path.mkdir", side_effect=PermissionError("Permission denied")), \
         patch("subprocess.Popen", return_value=mock_proc), \
         patch("builtins.print"):
         
        with pytest.raises(PermissionError):
            main()

def test_run_segment_ffmpeg_missing():
    # ffmpeg が存在しない場合の FileNotFoundError を再現
    with patch("subprocess.Popen", side_effect=FileNotFoundError("[Errno 2] No such file or directory: 'ffmpeg'")):
        with pytest.raises(FileNotFoundError) as exc_info:
            run_segment("scene01", "input.mp4", 0, 10, "1152:720:26:0", "srt.srt", 0)
        assert "ffmpeg" in str(exc_info.value)

def test_main_ffmpeg_error():
    # main 実行中に ffmpeg 起動エラー（FileNotFoundError）が発生した場合
    with patch("pathlib.Path.mkdir") as mock_mkdir, \
         patch("subprocess.Popen", side_effect=FileNotFoundError("[Errno 2] No such file or directory: 'ffmpeg'")), \
         patch("builtins.print"):
         
        with pytest.raises(FileNotFoundError):
            main()
        assert mock_mkdir.call_count == 1

def test_fpath_special_characters():
    # スペースや日本語、特殊文字を含むパスのテスト
    assert fPath("C:\\My Documents\\日本語の動画.mp4") == "C\\\\:/My Documents/日本語の動画.mp4"
    assert fPath("D:\\test's\\file.srt") == "D\\\\:/test's/file.srt"
    assert fPath("E:\\path/with/mixed\\slashes") == "E\\\\:/path/with/mixed/slashes"

def test_run_segment_special_characters(safe_popen_mock):
    mock_proc = safe_popen_mock(returncode=0)
    with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
        # シングルクォートなどの特殊文字が srt パスに含まれる場合
        srt_path = "C:\\path\\to\\user's_subtitles.srt"
        proc = run_segment("scene_spec", "input.mp4", 0, 10, "1280:720:0:0", srt_path, 0)
        assert proc == mock_proc
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        # srtパスが適切にエスケープされて subtitles フィルタに入っているか
        expected_srt_filter = "subtitles='C\\\\:/path/to/user's_subtitles.srt'"
        assert expected_srt_filter in args[args.index("-vf") + 1]

def test_main_process_failure(safe_popen_mock):
    # wait がエラーコードや例外を投げた場合の main の挙動
    # wait() が 1 を返すモック
    mock_proc_fail = safe_popen_mock(returncode=1)
    # wait を上書きしてモック
    mock_proc_fail.wait = MagicMock(return_value=1)
    
    with patch("pathlib.Path.mkdir") as mock_mkdir, \
         patch("subprocess.Popen", return_value=mock_proc_fail) as mock_popen, \
         patch("builtins.print") as mock_print:
         
        main()
        
        assert mock_mkdir.call_count == 1
        assert mock_popen.call_count == 4
        assert mock_proc_fail.wait.call_count == 4
        # wait が 1 を返しても例外は投げず、DONE_CHECKPOINTS まで到達する仕様であることの確認
        mock_print.assert_called_with("DONE_CHECKPOINTS")



# ============================================================
# サムネイル生成・品質検証・StageBoundAgent連携テスト (Phase 27)
# ============================================================

def test_generate_quick_check_thumbnail(tmp_path):
    from PIL import Image
    from quick_check import generate_quick_check_thumbnail, validate_quick_check_thumbnail
    output_path = tmp_path / "quick_check_thumb.png"
    
    result_path = generate_quick_check_thumbnail(output_path, text="Test Quick Check")
    assert result_path.exists()
    
    result_info = validate_quick_check_thumbnail(result_path)
    assert result_info["path"] == str(result_path)
    assert result_info["width"] == 1280
    assert result_info["height"] == 720
    assert result_info["size_bytes"] < 4 * 1024 * 1024
    
    with Image.open(result_path) as img:
        img.verify()

def test_validate_quick_check_thumbnail_quality_failures(tmp_path):
    import pytest
    from PIL import Image
    from unittest.mock import patch
    from quick_check import generate_quick_check_thumbnail, validate_quick_check_thumbnail
    
    with pytest.raises(FileNotFoundError):
        validate_quick_check_thumbnail(tmp_path / "non_existent.png")
        
    low_res_path = tmp_path / "low_res.png"
    img = Image.new("RGB", (640, 360), color="blue")
    img.save(low_res_path, format="PNG")
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        validate_quick_check_thumbnail(low_res_path)
        
    bad_ratio_path = tmp_path / "bad_ratio.png"
    img = Image.new("RGB", (1280, 960), color="blue")
    img.save(bad_ratio_path, format="PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        validate_quick_check_thumbnail(bad_ratio_path)
        
    valid_img_path = tmp_path / "valid_size.png"
    generate_quick_check_thumbnail(valid_img_path)
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 5 * 1024 * 1024
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            validate_quick_check_thumbnail(valid_img_path)
            
    with pytest.raises(ValueError, match="Width and height must be integers"):
        generate_quick_check_thumbnail(valid_img_path, width="invalid")
    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        generate_quick_check_thumbnail(valid_img_path, width=-100)

def test_stage_bound_agent_integration_quick_check(tmp_path):
    import asyncio
    import sqlite3
    import json
    from pathlib import Path
    from agents.stage_bound_agent import StageBoundAgent
    from quick_check import resolve_quick_check_thumbnail_task, validate_quick_check_thumbnail, BASE_DIR
    
    db_file = tmp_path / "quick_check_agent_test.db"
    output_dir = BASE_DIR / "backend" / "temp_thumbnails"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    task_id = "quick_check_thumb_test"
    
    async def run_test():
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=2)
        
        await agent.start(resolve_quick_check_thumbnail_task)
        
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status in ("COMPLETED", "FAILED"):
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
        assert final_status == "COMPLETED"
        
        output_path = output_dir / f"{task_id}.png"
        assert output_path.exists()
        
        result_info = validate_quick_check_thumbnail(output_path)
        assert result_info["width"] == 1280
        assert result_info["height"] == 720
        assert result_info["size_bytes"] < 4 * 1024 * 1024
        
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
        finally:
            conn.close()
            
    asyncio.run(run_test())

def test_stage_bound_agent_integration_quick_check_retry(tmp_path):
    import asyncio
    import sqlite3
    from pathlib import Path
    from unittest.mock import MagicMock
    from agents.stage_bound_agent import StageBoundAgent
    import quick_check
    
    db_file = tmp_path / "quick_check_agent_retry_test.db"
    
    # generate_quick_check_thumbnailを一時的にモックしてリトライ動作を確認
    orig_generate = quick_check.generate_quick_check_thumbnail
    mock_generate = MagicMock(side_effect=[RuntimeError("Temporary error"), Path("/dummy")])
    quick_check.generate_quick_check_thumbnail = mock_generate
    
    # validate_quick_check_thumbnailもダミー情報を返すようにモック
    orig_validate = quick_check.validate_quick_check_thumbnail
    quick_check.validate_quick_check_thumbnail = MagicMock(return_value={"width": 1280, "height": 720, "size_bytes": 100, "path": "dummy"})
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    task_id = "quick_check_thumb_retry_test"
    
    async def run_test():
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=1)
        
        await agent.start(quick_check.resolve_quick_check_thumbnail_task)
        
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status in ("COMPLETED", "FAILED"):
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
        assert final_status == "COMPLETED"
        assert mock_generate.call_count == 2
        
        conn = sqlite3.connect(str(db_file))
        try:
            cursor = conn.execute("SELECT status, retry_count, error FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            assert row is not None
            status, retry_count, error = row
            assert status == "COMPLETED"
            assert retry_count == 1
        finally:
            conn.close()
            
    try:
        asyncio.run(run_test())
    finally:
        quick_check.generate_quick_check_thumbnail = orig_generate
        quick_check.validate_quick_check_thumbnail = orig_validate
