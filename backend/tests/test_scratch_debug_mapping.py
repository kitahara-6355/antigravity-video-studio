# -*- coding: utf-8 -*-
"""
test_scratch_debug_mapping.py — debug_mapping.py のユニットテストおよび統合テスト
"""
import sys
import os
import json
import asyncio
import tempfile
import pytest
from pathlib import Path
from PIL import Image

# プロジェクトルートとbackendをパスに追加
backend_dir = Path(__file__).resolve().parents[1]
project_root = backend_dir.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.scratch.debug_mapping import (
    generate_thumbnail,
    validate_thumbnail,
    resolve_thumbnail_task
)
from backend.agents.stage_bound_agent import StageBoundAgent

@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)

def test_generate_and_validate_success(temp_dir):
    output_path = temp_dir / "success_thumb.png"
    
    # 正常な生成
    generate_thumbnail(output_path, width=1280, height=720, text="Success Thumbnail")
    assert output_path.exists()
    
    # 正常な検証
    result = validate_thumbnail(output_path)
    assert result["width"] == 1280
    assert result["height"] == 720
    assert result["size_bytes"] > 0
    assert result["path"] == str(output_path)
    
    # ロード可能チェック
    with Image.open(output_path) as img:
        img.load()
        assert img.size == (1280, 720)

def test_validate_failures(temp_dir):
    # 1. 存在しないファイル
    with pytest.raises(FileNotFoundError):
        validate_thumbnail(temp_dir / "non_existent.png")
        
    # 2. 解像度不足
    low_res_path = temp_dir / "low_res.png"
    generate_thumbnail(low_res_path, width=800, height=450, text="Low Res")
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        validate_thumbnail(low_res_path)
        
    # 3. アスペクト比不正
    bad_aspect_path = temp_dir / "bad_aspect.png"
    generate_thumbnail(bad_aspect_path, width=1280, height=1024, text="Bad Aspect 5:4")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        validate_thumbnail(bad_aspect_path)

def test_corrupted_image(temp_dir):
    corrupted_path = temp_dir / "corrupted.png"
    # 不正なデータを書き込んで破損ファイルを生成
    with open(corrupted_path, "wb") as f:
        f.write(b"NOT A REAL PNG FILE DATA")
        
    with pytest.raises(ValueError, match="Image structural verification failed|invalid format"):
        validate_thumbnail(corrupted_path)

def test_validate_size_limit(temp_dir, monkeypatch):
    large_path = temp_dir / "large.png"
    generate_thumbnail(large_path, width=1280, height=720)
    
    # ファイルサイズ取得をモックして4MB超にみせかける
    class MockStat:
        def __init__(self, size):
            self.st_size = size
            
    monkeypatch.setattr(Path, "stat", lambda self, *args, **kwargs: MockStat(5 * 1024 * 1024))
    with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
        validate_thumbnail(large_path)

def test_atomic_write_failure_cleanup(temp_dir):
    output_path = temp_dir / "should_not_exist.png"
    
    # 不正なサイズ指定により生成途中でエラーを発生させる
    with pytest.raises(ValueError):
        generate_thumbnail(output_path, width=-100, height=720)
        
    # 一時ファイルおよび出力ファイルが存在しないことを確認
    assert not output_path.exists()
    temp_files = list(temp_dir.glob("*.tmp"))
    assert len(temp_files) == 0

@pytest.mark.asyncio
async def test_stage_bound_agent_integration(temp_dir):
    # StageBoundAgent との連携統合テスト
    db_path = str(temp_dir / "test_tasks.db")
    agent = StageBoundAgent(stage_name="thumbnail", db_path=db_path)
    
    # エージェントインスタンスにプロパティを設定
    agent.output_dir = temp_dir
    agent.width = 1280
    agent.height = 720
    agent.text = "Integration test"
    
    task_id = "T-integration-001"
    await agent.register_task(task_id, initial_status="READY", max_retries=2)
    
    # DBマイグレーションのカラム検証
    import sqlite3
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("PRAGMA table_info(tasks)")
    columns = [row[1] for row in cursor.fetchall()]
    assert "result" in columns
    assert "retry_count" in columns
    assert "max_retries" in columns
    conn.close()
    
    # エージェント実行
    # resolve_thumbnail_task に agent を self としてバインドして process_func を登録
    async def process_wrapper(tid):
        return await resolve_thumbnail_task(agent, tid)
        
    await agent.start(process_wrapper)
    
    # タスク完了を待つ (ポーリング)
    for _ in range(20):
        status = await agent.get_task_status(task_id)
        if status == "COMPLETED":
            break
        await asyncio.sleep(0.05)
        
    status = await agent.get_task_status(task_id)
    assert status == "COMPLETED"
    
    # 結果保存の検証
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("SELECT result, error, retry_count FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    result_data = json.loads(row[0])
    assert result_data["width"] == 1280
    assert result_data["height"] == 720
    assert Path(result_data["path"]).exists()
    assert row[1] is None  # error
    assert row[2] == 0  # retry_count
    
    await agent.stop()

@pytest.mark.asyncio
async def test_stage_bound_agent_retry_flow(temp_dir):
    # 自動リトライの検証フロー
    db_path = str(temp_dir / "test_retry.db")
    agent = StageBoundAgent(stage_name="thumbnail", db_path=db_path)
    
    # 意図的に生成エラーを起こす設定（幅に無効な値）
    agent.output_dir = temp_dir
    agent.width = -1
    agent.height = 720
    agent.text = "Fail test"
    
    task_id = "T-fail-001"
    # リトライ上限を1回に設定
    await agent.register_task(task_id, initial_status="READY", max_retries=1)
    
    async def process_wrapper(tid):
        return await resolve_thumbnail_task(agent, tid)
        
    await agent.start(process_wrapper)
    
    # リトライ上限に達して FAILED になるまでポーリング
    for _ in range(30):
        status = await agent.get_task_status(task_id)
        if status == "FAILED":
            break
        await asyncio.sleep(0.05)
        
    status = await agent.get_task_status(task_id)
    assert status == "FAILED"
    
    # DBの状態検証（リトライカウントが1に達していること）
    import sqlite3
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("SELECT status, error, retry_count, max_retries FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    assert row[0] == "FAILED"
    assert "Width and height must be positive integers" in row[1]
    assert row[2] == 1  # retry_count
    assert row[3] == 1  # max_retries
    
    await agent.stop()

def test_generate_invalid_types(temp_dir):
    output_path = temp_dir / "invalid_type.png"
    # width や height に整数変換不可能なオブジェクトを指定
    with pytest.raises(ValueError, match="Width and height must be integers"):
        generate_thumbnail(output_path, width="not_an_int", height=720)
    
    with pytest.raises(ValueError, match="Width and height must be integers"):
        generate_thumbnail(output_path, width=1280, height=[720])


def test_generate_unlink_existing(temp_dir):
    output_path = temp_dir / "existing.png"
    # あらかじめファイルを作成しておく
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("dummy content")
    
    # 既存ファイルがある状態で生成
    generate_thumbnail(output_path, width=1280, height=720, text="New Image")
    assert output_path.exists()
    
    # 画像として正常に読み込めることを確認
    with Image.open(output_path) as img:
        assert img.size == (1280, 720)


def test_generate_save_exception(temp_dir, monkeypatch):
    output_path = temp_dir / "save_fail.png"
    
    # Image.Image.save メソッドが例外を投げるようにモックする
    # 実際に一時ファイルをディスクに書き出した上で例外を投げる
    def mock_save(self, fp, *args, **kwargs):
        with open(fp, "wb") as f:
            f.write(b"")
        raise OSError("Simulated save failure")
        
    monkeypatch.setattr(Image.Image, "save", mock_save)
    
    with pytest.raises(OSError, match="Simulated save failure"):
        generate_thumbnail(output_path, width=1280, height=720)
        
    # 一時ファイルが残っていないことを確認する
    temp_files = list(temp_dir.glob("*.tmp"))
    assert len(temp_files) == 0


def test_generate_save_exception_unlink_failure(temp_dir, monkeypatch):
    output_path = temp_dir / "save_unlink_fail.png"
    
    # 保存時に一時ファイルを生成した上で例外を投げさせる
    def mock_save(self, fp, *args, **kwargs):
        with open(fp, "wb") as f:
            f.write(b"")
        raise OSError("Simulated save failure")
    monkeypatch.setattr(Image.Image, "save", mock_save)
    
    # Path.unlink 自体が例外を投げるようにモックする
    orig_unlink = Path.unlink
    def mock_unlink(self, *args, **kwargs):
        # 一時ファイルに対する unlink の場合に例外を投げるようにする
        if ".tmp" in self.name:
            raise OSError("Simulated unlink failure")
        return orig_unlink(self, *args, **kwargs)
        
    monkeypatch.setattr(Path, "unlink", mock_unlink)
    
    # 実行すると、保存失敗時の例外が正常に投げられ、unlink例外は pass される
    with pytest.raises(OSError, match="Simulated save failure"):
        generate_thumbnail(output_path, width=1280, height=720)


def test_validate_load_exception(temp_dir, monkeypatch):
    valid_path = temp_dir / "load_fail.png"
    generate_thumbnail(valid_path, width=1280, height=720)
    
    # Image.Image.load メソッドが例外を投げるようにモックする
    def mock_load(*args, **kwargs):
        raise OSError("Simulated load failure")
    
    monkeypatch.setattr(Image.Image, "load", mock_load)
    
    with pytest.raises(ValueError, match="Image pixel data load failed"):
        validate_thumbnail(valid_path)
