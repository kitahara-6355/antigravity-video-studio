# -*- coding: utf-8 -*-
import os
import sys
import json
import pytest
import sqlite3
import asyncio
from pathlib import Path
from PIL import Image
from unittest.mock import MagicMock, patch, AsyncMock

# プロジェクトルートをパスに追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# 対象モジュールのインポート
from backend.agents.orchestration.mark_and_update_000 import ThumbnailProcessor, run_thumbnail_task


@pytest.fixture
def temp_output_dir(tmp_path):
    d = tmp_path / "thumbnails"
    d.mkdir()
    yield d


def test_thumbnail_processor_success(temp_output_dir):
    """正常系: 1280x720 16:9 の画像が生成され、検証を通過すること"""
    processor = ThumbnailProcessor()
    out_path = temp_output_dir / "valid_thumb.png"
    
    # 画像生成
    processor.generate_thumbnail(out_path, width=1280, height=720, text="Test Success")
    assert out_path.exists()
    
    # 品質検証
    with patch("backend.agents.orchestration.mark_and_update_000.emit_warning") as mock_warn:
        result = processor.validate_thumbnail(out_path)
        assert result["width"] == 1280
        assert result["height"] == 720
        assert result["size_bytes"] > 0
        assert Path(result["path"]) == out_path
        mock_warn.assert_not_called()


def test_thumbnail_processor_invalid_resolution(temp_output_dir):
    """異常系: 解像度が 1280x720 未満の場合に検証エラーとなり、警告が発行されること"""
    processor = ThumbnailProcessor()
    out_path = temp_output_dir / "low_res_thumb.png"
    
    # 640x360（アスペクト比は16:9だが低解像度）
    processor.generate_thumbnail(out_path, width=640, height=360, text="Low Res")
    
    with patch("backend.agents.orchestration.mark_and_update_000.emit_warning") as mock_warn:
        with pytest.raises(ValueError) as excinfo:
            processor.validate_thumbnail(out_path)
        assert "Resolution must be at least 1280x720" in str(excinfo.value)
        mock_warn.assert_called_once()


def test_thumbnail_processor_invalid_aspect_ratio(temp_output_dir):
    """異常系: アスペクト比が 16:9 以外の場合に検証エラーとなり、警告が発行されること"""
    processor = ThumbnailProcessor()
    out_path = temp_output_dir / "bad_ratio_thumb.png"
    
    # 1280x1280（1:1解像度）
    processor.generate_thumbnail(out_path, width=1280, height=1280, text="Square")
    
    with patch("backend.agents.orchestration.mark_and_update_000.emit_warning") as mock_warn:
        with pytest.raises(ValueError) as excinfo:
            processor.validate_thumbnail(out_path)
        assert "Aspect ratio must be 16:9" in str(excinfo.value)
        mock_warn.assert_called_once()


def test_thumbnail_processor_exceed_size_limit(temp_output_dir):
    """異常系: ファイルサイズが 4MB 以上の場合に検証エラーとなり、警告が発行されること"""
    processor = ThumbnailProcessor()
    out_path = temp_output_dir / "huge_thumb.png"
    
    processor.generate_thumbnail(out_path, width=1280, height=720, text="Huge")
    
    # stat().st_size を 4MB 以上に偽装するパッチ
    with patch.object(Path, "stat") as mock_stat, \
         patch("backend.agents.orchestration.mark_and_update_000.emit_warning") as mock_warn:
        
        mock_stat_val = MagicMock()
        mock_stat_val.st_size = 4 * 1024 * 1024 + 10  # 4MB超
        mock_stat.return_value = mock_stat_val
        
        with pytest.raises(ValueError) as excinfo:
            processor.validate_thumbnail(out_path)
        assert "File size exceeds 4MB limit" in str(excinfo.value)
        mock_warn.assert_called_once()


def test_thumbnail_processor_corrupted(temp_output_dir):
    """異常系: 画像ファイルが破損している場合に検証エラーとなり、警告が発行されること"""
    processor = ThumbnailProcessor()
    out_path = temp_output_dir / "corrupted_thumb.png"
    
    # 壊れたデータを直接書き込む
    out_path.write_bytes(b"invalid image header data that cannot be loaded by PIL")
    
    with patch("backend.agents.orchestration.mark_and_update_000.emit_warning") as mock_warn:
        with pytest.raises(ValueError) as excinfo:
            processor.validate_thumbnail(out_path)
        assert "corrupted or invalid" in str(excinfo.value)
        mock_warn.assert_called_once()


@pytest.mark.asyncio
async def test_run_thumbnail_task_integration(temp_output_dir):
    """統合テスト: StageBoundAgent を介してタスクを実行し、完了後に OrchestrationHub.mark_task_done が呼ばれること"""
    db_file = temp_output_dir / "test_agents.db"
    task_id = "T-test_thumbnail_001"
    
    # mock OrchestrationHub
    mock_hub = MagicMock()
    
    with patch("backend.agents.orchestration.mark_and_update_000.OrchestrationHub", return_value=mock_hub):
        # タスク実行
        await run_thumbnail_task(
            db_path=str(db_file),
            task_id=task_id,
            output_dir=str(temp_output_dir),
            width=1280,
            height=720,
            text="Integration Test Thumbnail"
        )
        
        # mark_task_done が "pass" で呼ばれているはず
        mock_hub.mark_task_done.assert_called_once()
        args, kwargs = mock_hub.mark_task_done.call_args
        assert args[0] == task_id
        assert args[1] == "pass"
        report = args[2]
        assert "width" in report
        assert report["width"] == 1280
        assert report["height"] == 720

@pytest.mark.asyncio
async def test_run_thumbnail_task_timeout(temp_output_dir):
    """異常系: タイムアウト時間を超えた場合に TimeoutError が発生すること"""
    db_file = temp_output_dir / "test_timeout.db"
    task_id = "T-test_timeout_001"
    
    mock_hub = MagicMock()
    with patch("backend.agents.orchestration.mark_and_update_000.OrchestrationHub", return_value=mock_hub):
        # タイムアウトを極小値に設定して即座にタイムアウトさせる
        with pytest.raises(TimeoutError) as excinfo:
            await run_thumbnail_task(
                db_path=str(db_file),
                task_id=task_id,
                output_dir=str(temp_output_dir),
                width=1280,
                height=720,
                text="Timeout Test",
                timeout=0.01
            )
        assert "Task execution timed out" in str(excinfo.value)
        mock_hub.mark_task_done.assert_called_once_with(task_id, "fail", {"error": "TimeoutError: Task execution timed out"})


@pytest.mark.asyncio
async def test_run_thumbnail_task_failure(temp_output_dir):
    """異常系: タスク処理中に例外が発生し、ステータスが FAILED になった場合に RuntimeError が発生すること"""
    db_file = temp_output_dir / "test_failed.db"
    task_id = "T-test_failed_001"
    
    mock_hub = MagicMock()
    # 画像生成で例外を発生させるパッチ
    with patch("backend.agents.orchestration.mark_and_update_000.ThumbnailProcessor.generate_thumbnail", side_effect=ValueError("Simulated generation error")), \
         patch("backend.agents.orchestration.mark_and_update_000.OrchestrationHub", return_value=mock_hub):
        with pytest.raises(RuntimeError) as excinfo:
            await run_thumbnail_task(
                db_path=str(db_file),
                task_id=task_id,
                output_dir=str(temp_output_dir),
                width=1280,
                height=720,
                text="Failed Test",
                timeout=5.0
            )
        assert "Task failed" in str(excinfo.value)
        mock_hub.mark_task_done.assert_called_once_with(task_id, "fail", {"error": "Simulated generation error"})


@pytest.mark.asyncio
async def test_run_thumbnail_task_db_error_resilience(temp_output_dir):
    """堅牢性テスト: データベース接続時に sqlite3.Error が発生しても、リトライで正常終了すること"""
    db_file = temp_output_dir / "test_db_error.db"
    task_id = "T-test_db_error_001"
    
    # 最初の数回だけ sqlite3.connect がエラーを投げるようにモックする
    orig_connect = sqlite3.connect
    connect_call_count = 0
    
    def mock_connect(*args, **kwargs):
        nonlocal connect_call_count
        connect_call_count += 1
        # 最初の2回（Agentの初期化とタスク登録）は正常に通し、
        # 3〜4回目のポーリング時呼び出しで DB エラーを発生させる。
        # 5回目以降は正常に接続させる。
        if 3 <= connect_call_count <= 4:
            raise sqlite3.OperationalError("database is locked (mocked)")
        return orig_connect(*args, **kwargs)
        
    mock_hub = MagicMock()
    
    with patch("backend.agents.orchestration.mark_and_update_000.OrchestrationHub", return_value=mock_hub),          patch("sqlite3.connect", side_effect=mock_connect),          patch("backend.agents.orchestration.mark_and_update_000.emit_warning") as mock_warn:
         
        await run_thumbnail_task(
            db_path=str(db_file),
            task_id=task_id,
            output_dir=str(temp_output_dir),
            width=1280,
            height=720,
            text="DB Error Resilience Test",
            timeout=5.0
        )
        
        # mock_hub.mark_task_done.assert_called_once() が呼ばれ、最終的に成功したことを確認
        mock_hub.mark_task_done.assert_called_once()
        # データベース接続エラーにより警告が発行されていることを確認
        assert mock_warn.call_count >= 1
@pytest.mark.asyncio
async def test_run_thumbnail_task_in_memory(temp_output_dir):
    """統合テスト（インメモリ）: インメモリDB（:memory:）を使用した場合でも、正しくタスクが完了すること"""
    task_id = "T-test_thumbnail_in_memory"
    mock_hub = MagicMock()
    
    with patch("backend.agents.orchestration.mark_and_update_000.OrchestrationHub", return_value=mock_hub):
        run_future = asyncio.create_task(
            run_thumbnail_task(
                db_path=":memory:",
                task_id=task_id,
                output_dir=str(temp_output_dir),
                width=1280,
                height=720,
                text="In Memory Test"
            )
        )
        
        # タイムアウト付きで待機。正しく接続が共有されていればすぐに完了するはず。
        await asyncio.wait_for(run_future, timeout=5.0)
        
        mock_hub.mark_task_done.assert_called_once()
