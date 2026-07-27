import sys
import os
import pytest
import sqlite3
import json
import asyncio
from pathlib import Path
from PIL import Image

# backend ディレクトリをパスに追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from agents.orchestration.mark_tasks_p27_weaver1_b88 import (
    generate_thumbnail,
    validate_thumbnail,
    resolve_weaver_thumbnail_task
)
from agents.stage_bound_agent import StageBoundAgent

def test_generate_and_validate_thumbnail_success(tmp_path):
    """正常系: サムネイル画像が正常に生成され、要件をすべて満たしていること"""
    output_path = tmp_path / "weaver_thumb.png"
    
    # サムネイル生成
    generate_thumbnail(output_path, width=1280, height=720, text="Test Weaver Thumbnail")
    assert output_path.exists()
    
    # 品質検証
    result = validate_thumbnail(output_path)
    assert result["width"] == 1280
    assert result["height"] == 720
    assert result["size_bytes"] < 4 * 1024 * 1024
    assert Path(result["path"]) == output_path
    
    # Pillowでロード可能であることを検証
    with Image.open(output_path) as img:
        img.verify()
        
    with Image.open(output_path) as img:
        img.load()
        assert img.size == (1280, 720)

def test_validate_thumbnail_failures(tmp_path):
    """異常系: 品質要件を満たさない画像、破損画像に対する例外スロー"""
    # 1. 存在しないファイル
    with pytest.raises(FileNotFoundError):
        validate_thumbnail(tmp_path / "non_existent.png")
        
    # 2. 解像度不足の画像
    low_res_path = tmp_path / "low_res.png"
    img = Image.new("RGB", (640, 360), color="blue")
    img.save(low_res_path, format="PNG")
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        validate_thumbnail(low_res_path)
        
    # 3. アスペクト比が 16:9 ではない画像 (4:3)
    bad_ratio_path = tmp_path / "bad_ratio.png"
    img = Image.new("RGB", (1280, 960), color="blue")
    img.save(bad_ratio_path, format="PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        validate_thumbnail(bad_ratio_path)
        
    # 4. ファイルサイズ超過 (4MB制限)
    # stat.st_size をモックしてファイルサイズ超過を偽装
    valid_path = tmp_path / "valid_size.png"
    generate_thumbnail(valid_path, width=1280, height=720, text="Mock Size Test")
    
    from unittest.mock import patch
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 5 * 1024 * 1024  # 5MB
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            validate_thumbnail(valid_path)

def test_stage_bound_agent_integration(tmp_path):
    """結合テスト: StageBoundAgent との自動リトライ、結果保存、DBマイグレーションの連携検証"""
    db_file = tmp_path / "test_weaver_stage_bound.db"
    
    # StageBoundAgent を初期化（この時点で DBマイグレーション が走り、カラムが自動作成される）
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    
    # DBマイグレーション検証
    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.execute("PRAGMA table_info(tasks)")
        columns = [row[1] for row in cursor.fetchall()]
        assert "result" in columns
        assert "retry_count" in columns
        assert "max_retries" in columns
    finally:
        conn.close()
        
    task_id = "weaver_thumb_integration_test"
    
    async def run_integration():
        # タスクを READY で登録 (リトライ回数 1 に設定)
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=1)
        
        # サムネイル出力先を一時的に変更するか、デフォルトの backend/temp_thumbnails に出力させる
        output_file = Path("backend/temp_thumbnails") / f"{task_id}.png"
        if output_file.exists():
            output_file.unlink()
            
        # Agentを起動し、非同期タスク処理を割り当てる
        await agent.start(resolve_weaver_thumbnail_task)
        
        # 完了を待つ (最大2.5秒)
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status in ("COMPLETED", "FAILED"):
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
        # 1. 完了ステータス確認
        assert final_status == "COMPLETED"
        
        # 2. 生成ファイルの存在と品質検証
        assert output_file.exists()
        result_info = validate_thumbnail(output_file)
        assert result_info["width"] == 1280
        assert result_info["height"] == 720
        assert result_info["size_bytes"] < 4 * 1024 * 1024
        
        # 3. DB結果保存・リトライ回数確認
        conn2 = sqlite3.connect(str(db_file))
        try:
            cursor2 = conn2.execute("SELECT status, result, retry_count FROM tasks WHERE id = ?", (task_id,))
            row = cursor2.fetchone()
            assert row is not None
            status, result_str, retry_count = row
            assert status == "COMPLETED"
            assert retry_count == 0  # 正常終了なのでリトライなし
            
            db_result = json.loads(result_str)
            assert db_result["width"] == 1280
            assert db_result["height"] == 720
            assert "path" in db_result
        finally:
            conn2.close()
            
        # クリーンアップ
        if output_file.exists():
            output_file.unlink()
            
    asyncio.run(run_integration())

def test_generate_thumbnail_invalid_types(tmp_path):
    """異常系: widthやheightに整数に変換できない型が渡された場合、ValueErrorを投げること"""
    output_path = tmp_path / "invalid_type.png"
    with pytest.raises(ValueError, match="Width and height must be integers"):
        generate_thumbnail(output_path, width="abc", height=720)
    with pytest.raises(ValueError, match="Width and height must be integers"):
        generate_thumbnail(output_path, width=1280, height=None)

def test_generate_thumbnail_negative_or_zero_dims(tmp_path):
    """異常系: widthやheightに0以下の値が渡された場合、ValueErrorを投げること"""
    output_path = tmp_path / "invalid_dims.png"
    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        generate_thumbnail(output_path, width=0, height=720)
    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        generate_thumbnail(output_path, width=1280, height=-10)

def test_generate_thumbnail_overwrite_existing(tmp_path):
    """正常系: すでにファイルが存在する場合、正しく削除されて上書きされること"""
    output_path = tmp_path / "overwrite.png"
    # ダミーファイルを作成しておく
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write("dummy")
    
    assert output_path.exists()
    
    generate_thumbnail(output_path, width=1280, height=720, text="Overwritten")
    assert output_path.exists()
    
    # 画像ファイルとして正常であることを検証
    with Image.open(output_path) as img:
        img.verify()

def test_generate_thumbnail_atomic_write_failure(tmp_path):
    """異常系: 保存時にエラーが発生した場合、一時ファイルを削除して例外を再スローすること"""
    output_path = tmp_path / "fail.png"
    
    import uuid
    from unittest.mock import patch, MagicMock
    
    # uuid.uuid4をモックして一時ファイル名を固定
    mock_uuid = MagicMock()
    mock_uuid.hex = "testuuid"
    
    # 固定された一時ファイルパス
    temp_path = output_path.with_suffix(f".testuuid.tmp")
    
    # 一時ファイルを事前に作成し、開いたままにすることで削除不可にする
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    temp_file_handle = open(temp_path, "w")
    temp_file_handle.write("lock")
    temp_file_handle.flush()
    
    # Image.saveでOSErrorを発生させる
    with patch("PIL.Image.Image.save", side_effect=OSError("Disk Full")), \
         patch("uuid.uuid4", return_value=mock_uuid):
         
        with pytest.raises(OSError, match="Disk Full"):
            generate_thumbnail(output_path, width=1280, height=720)
            
    # テスト後にファイルをクローズしてクリーンアップ
    temp_file_handle.close()
    if temp_path.exists():
        temp_path.unlink()
        
    assert not output_path.exists()

def test_validate_thumbnail_verify_corrupted(tmp_path):
    """異常系: Image.verifyで例外が発生した場合、ValueErrorに変換されること"""
    valid_path = tmp_path / "corrupt_verify.png"
    generate_thumbnail(valid_path, width=1280, height=720)
    
    # Image.verifyでSyntaxErrorをシミュレート
    from unittest.mock import patch, MagicMock
    
    original_open = Image.open
    def mock_open(*args, **kwargs):
        img = original_open(*args, **kwargs)
        img.verify = MagicMock(side_effect=SyntaxError("Bad structure"))
        return img
        
    with patch("PIL.Image.open", side_effect=mock_open):
        with pytest.raises(ValueError, match="Image is corrupted or invalid format: Bad structure"):
            validate_thumbnail(valid_path)

def test_validate_thumbnail_load_corrupted(tmp_path):
    """異常系: Image.loadで例外が発生した場合、ValueErrorに変換されること"""
    valid_path = tmp_path / "corrupt_load.png"
    generate_thumbnail(valid_path, width=1280, height=720)
    
    # Image.loadでOSErrorをシミュレート
    from unittest.mock import patch, MagicMock
    
    original_open = Image.open
    def mock_open(*args, **kwargs):
        img = original_open(*args, **kwargs)
        img.load = MagicMock(side_effect=OSError("Load error"))
        return img
        
    with patch("PIL.Image.open", side_effect=mock_open):
        with pytest.raises(ValueError, match="Image is corrupted or invalid format: Load error"):
            validate_thumbnail(valid_path)

def test_main_flow(capsys):
    """正常系: main関数が正常に実行され、OrchestrationHubを介してタスク完了登録が行われること"""
    from unittest.mock import patch, MagicMock
    
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"status": "ok"}
    
    with patch("agents.orchestration.mark_tasks_p27_weaver1_b88.OrchestrationHub", return_value=mock_hub_instance):
        from agents.orchestration.mark_tasks_p27_weaver1_b88 import main
        main()
        
        # モックの呼び出しを確認
        mock_hub_instance.register_flash_conversation_id.assert_called_once_with("a9736a64-a242-485f-942e-bf8476d21fa6")
        mock_hub_instance.flash_update_heartbeat.assert_called_once()
        mock_hub_instance.mark_task_done.assert_called_once()
        mock_hub_instance.generate_flash_status.assert_called_once()
        
        # 標準出力を取得
        captured = capsys.readouterr()
        assert "TASK_MARKED_DONE" in captured.out
        assert 'FLASH_STATUS:{"status": "ok"}' in captured.out

def test_main_script_execution():
    """正常系: __main__ブロック経由での実行が正常に行われること"""
    import runpy
    from unittest.mock import patch, MagicMock
    
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"status": "ok"}
    
    # modules_path を特定
    script_path = str(Path(__file__).resolve().parents[1] / "agents" / "orchestration" / "mark_tasks_p27_weaver1_b88.py")
    
    # OrchestrationHubをモックして、main実行をシミュレート
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance), \
         patch("builtins.print") as mock_print:
         
        runpy.run_path(script_path, run_name="__main__")
        
        # main() が呼び出されたことを確認
        mock_hub_instance.register_flash_conversation_id.assert_called_once_with("a9736a64-a242-485f-942e-bf8476d21fa6")
        # printが呼び出されたことを確認
        mock_print.assert_any_call("TASK_MARKED_DONE")

