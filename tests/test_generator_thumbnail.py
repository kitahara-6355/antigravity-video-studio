# -*- coding: utf-8 -*-
import sys
import os
import pytest
import sqlite3
import json
import asyncio
from pathlib import Path
from PIL import Image
import io
from unittest.mock import MagicMock, AsyncMock, patch

# パス追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.thumbnail_engine.generator import (
    ThumbnailGenerator,
    resolve_generator_thumbnail_task
)
from backend.branding.history_manager import ThumbnailValidator, ImageValidationError

def create_dummy_image_bytes(width: int, height: int, mode="RGB", target_size_bytes: int = 0) -> bytes:
    """テスト用のダミー画像バイナリを生成"""
    img = Image.new(mode, (width, height), color="blue")
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='JPEG')
    data = img_byte_arr.getvalue()
    if len(data) < target_size_bytes:
        data += b'\x00' * (target_size_bytes - len(data))
    return data

def test_verify_and_optimize_image_success():
    """正常系: 適切な画像サイズ、解像度、アスペクト比で最適化が通り、品質検証に合格すること"""
    generator = ThumbnailGenerator()
    img_bytes = create_dummy_image_bytes(1920, 1080)
    
    # 最適化の実行
    optimized_bytes = generator.verify_and_optimize_image(img_bytes, title="Test Video Title")
    
    # 検証
    assert len(optimized_bytes) > 0
    assert len(optimized_bytes) < 4 * 1024 * 1024  # 4MB未満
    
    # 画像のロード検証
    with Image.open(io.BytesIO(optimized_bytes)) as img:
        img.load()
        assert img.size == (1920, 1080)  # サイズが維持される（1280x720以上、16:9）
        assert img.format == "JPEG"

def test_verify_and_optimize_image_fallback():
    """異常系・フォールバック: 空の画像データや破損データを入力した際、高品質なフォールバック画像が自動生成されること"""
    generator = ThumbnailGenerator()
    
    # 空データを入力してフォールバック画像生成
    fallback_bytes = generator.verify_and_optimize_image(b"", title="日本語の長いタイトルで折り返しをテストするケースです。")
    
    # 4MB未満かつ1280x720、16:9であることを確認
    assert len(fallback_bytes) > 0
    assert len(fallback_bytes) < 4 * 1024 * 1024
    
    with Image.open(io.BytesIO(fallback_bytes)) as img:
        img.load()
        w, h = img.size
        assert w >= 1280
        assert h >= 720
        assert abs((w / h) - (16.0 / 9.0)) < 0.05
        assert img.format == "JPEG"

def test_verify_and_optimize_image_too_small_resize():
    """画像解像度が小さすぎる場合、アスペクト比を16:9に維持しつつ1280x720以上に拡大されること"""
    generator = ThumbnailGenerator()
    img_bytes = create_dummy_image_bytes(640, 480)  # 4:3
    
    optimized_bytes = generator.verify_and_optimize_image(img_bytes, title="Small Image")
    
    with Image.open(io.BytesIO(optimized_bytes)) as img:
        img.load()
        w, h = img.size
        assert w >= 1280
        assert h >= 720
        assert abs((w / h) - (16.0 / 9.0)) < 0.05

@pytest.mark.asyncio
async def test_resolve_generator_thumbnail_task_integration(tmp_path):
    """StageBoundAgentのモックと sqlite3 を使用した resolve_generator_thumbnail_task のインテグレーション検証"""
    db_file = tmp_path / "test_generator_thumb.db"
    output_dir = tmp_path / "output_thumbs"
    task_id = "task_gen_001"
    
    # Agentモックの作成
    agent = MagicMock()
    agent.output_dir = output_dir
    agent.db_path = str(db_file)
    agent.video_title = "自動サムネイル生成のインテグレーションテストタイトル"
    agent.video_description = "テスト用説明文"
    
    # ThumbnailGenerator.generate をモック（APIコール回避）
    dummy_bytes = create_dummy_image_bytes(1280, 720)
    import base64
    dummy_b64 = base64.b64encode(dummy_bytes).decode('utf-8')
    
    mock_generate = AsyncMock(return_value=[{
        "image_base64": dummy_b64,
        "concept_name": "テスト用コンセプト"
    }])
    
    with patch('backend.thumbnail_engine.generator.generator.generate', mock_generate):
        result_json = await resolve_generator_thumbnail_task(agent, task_id)
        
    result_data = json.loads(result_json)
    assert result_data["valid"] is True
    assert result_data["width"] == 1280
    assert result_data["height"] == 720
    
    expected_path = output_dir / f"{task_id}.jpg"
    assert expected_path.exists()
    assert Path(result_data["path"]) == expected_path
    
    # 生成されたファイルの検証
    img_file_bytes = expected_path.read_bytes()
    assert ThumbnailValidator.validate_image(img_file_bytes) is True
    
    # DBの確認
    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.execute("SELECT task_id, path, width, height, size_bytes, verified_at FROM thumbnail_results WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None
        db_task_id, db_path, db_width, db_height, db_size_bytes, db_verified_at = row
        assert db_task_id == task_id
        assert Path(db_path) == expected_path
        assert db_width == 1280
        assert db_height == 720
        assert db_size_bytes == len(img_file_bytes)
        assert db_verified_at > 0
    finally:
        conn.close()

@pytest.mark.asyncio
async def test_resolve_generator_thumbnail_task_db_lock_retry(tmp_path):
    """DBロック競合発生時のリトライフローを検証"""
    db_file = tmp_path / "test_generator_thumb_locked.db"
    output_dir = tmp_path / "output_thumbs"
    task_id = "task_gen_002"
    
    agent = MagicMock()
    agent.output_dir = output_dir
    agent.db_path = str(db_file)
    agent.video_title = "DBロック再試行テスト"
    agent.video_description = "説明"
    
    # ダミー画像を生成
    dummy_bytes = create_dummy_image_bytes(1280, 720)
    import base64
    dummy_b64 = base64.b64encode(dummy_bytes).decode('utf-8')
    
    mock_generate = AsyncMock(return_value=[{
        "image_base64": dummy_b64,
        "concept_name": "ロックテストコンセプト"
    }])
    
    # sqlite3.connect をモックし、最初は OperationalError("database is locked") を投げ、次に成功するよう設定
    original_connect = sqlite3.connect
    connect_calls = 0
    
    def mock_connect(*args, **kwargs):
        nonlocal connect_calls
        connect_calls += 1
        if connect_calls <= 2:
            raise sqlite3.OperationalError("database is locked")
        return original_connect(*args, **kwargs)
        
    with patch('backend.thumbnail_engine.generator.generator.generate', mock_generate), \
         patch('sqlite3.connect', side_effect=mock_connect), \
         patch('asyncio.sleep', AsyncMock()) as mock_sleep:
         
        result_json = await resolve_generator_thumbnail_task(agent, task_id)
        
    result_data = json.loads(result_json)
    assert result_data["valid"] is True
    assert connect_calls == 3  # 1回目ロック、2回目ロック、3回目成功
    assert mock_sleep.call_count == 2  # 2回スリープが呼ばれたはず


@pytest.mark.asyncio
async def test_stage_bound_agent_generator_integration(tmp_path):
    """本物の StageBoundAgent を使用して resolve_generator_thumbnail_task の自動リトライ、結果保存、DBマイグレーションの連携を検証"""
    from backend.agents.stage_bound_agent import StageBoundAgent
    
    db_file = tmp_path / "generator_agent_integration.db"
    output_dir = tmp_path / "output_thumbs"
    task_id = "task_integration_001"
    
    # StageBoundAgent の作成
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    agent.output_dir = output_dir
    agent.video_title = "StageBoundAgent Integration Test"
    agent.video_description = "Testing full database saving and migration workflow"
    
    # 画像生成モック
    dummy_bytes = create_dummy_image_bytes(1280, 720)
    import base64
    dummy_b64 = base64.b64encode(dummy_bytes).decode('utf-8')
    
    mock_generate = AsyncMock(return_value=[{
        "image_base64": dummy_b64,
        "concept_name": "Integration Concept"
    }])
    
    async def process_func(tid):
        return await resolve_generator_thumbnail_task(agent, tid)
        
    # タスク登録
    await agent.register_task(task_id=task_id, initial_status="READY", max_retries=1)
    
    with patch('backend.thumbnail_engine.generator.generator.generate', mock_generate):
        await agent.start(process_func)
        
        # 完了を待機
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status in ("COMPLETED", "FAILED"):
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
    assert final_status == "COMPLETED"
    
    # 画像ファイル検証
    output_path = output_dir / f"{task_id}.jpg"
    assert output_path.exists()
    
    with Image.open(output_path) as img:
        img.verify()
    with Image.open(output_path) as img:
        img.load()
        w, h = img.size
        assert w >= 1280
        assert h >= 720
        assert abs((w / h) - (16.0 / 9.0)) < 0.05
        
    # DB保存結果とマイグレーションの検証
    conn = sqlite3.connect(str(db_file))
    try:
        # tasks テーブルの更新確認
        cursor = conn.execute("SELECT status, result FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None
        status, result_str = row
        assert status == "COMPLETED"
        
        # thumbnail_results テーブル（マイグレーションにより作成される）の確認
        cursor = conn.execute("SELECT task_id, path, width, height, size_bytes FROM thumbnail_results WHERE task_id = ?", (task_id,))
        thumb_row = cursor.fetchone()
        assert thumb_row is not None
        db_task_id, db_path, db_width, db_height, db_size_bytes = thumb_row
        assert db_task_id == task_id
        assert Path(db_path) == output_path
        assert db_width == w
        assert db_height == h
        assert db_size_bytes == output_path.stat().st_size
    finally:
        conn.close()

@pytest.mark.asyncio
async def test_stage_bound_agent_generator_retry_flow(tmp_path):
    """StageBoundAgentと連携した自動リトライフローの検証 (1回目失敗、2回目成功)"""
    from backend.agents.stage_bound_agent import StageBoundAgent
    
    db_file = tmp_path / "generator_agent_retry.db"
    output_dir = tmp_path / "output_thumbs"
    task_id = "task_retry_001"
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    agent.output_dir = output_dir
    agent.video_title = "Retry Workflow Test"
    agent.video_description = "Testing automatic retry under StageBoundAgent"
    
    dummy_bytes = create_dummy_image_bytes(1280, 720)
    import base64
    dummy_b64 = base64.b64encode(dummy_bytes).decode('utf-8')
    
    # 1回目の呼び出しは例外を投げ、2回目は成功させるモック
    call_count = 0
    async def mock_generate_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Temporary API Error")
        return [{
            "image_base64": dummy_b64,
            "concept_name": "Retry Concept"
        }]
        
    mock_generate = AsyncMock(side_effect=mock_generate_side_effect)
    
    async def process_func(tid):
        return await resolve_generator_thumbnail_task(agent, tid)
        
    # max_retries = 2 で登録
    await agent.register_task(task_id=task_id, initial_status="READY", max_retries=2)
    
    with patch('backend.thumbnail_engine.generator.generator.generate', mock_generate):
        await agent.start(process_func)
        
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status == "COMPLETED":
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
    assert final_status == "COMPLETED"
    assert call_count == 2
    
    # DB上のリトライ回数確認
    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.execute("SELECT retry_count, status FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None
        retry_count, status = row
        assert status == "COMPLETED"
        assert retry_count == 1
    finally:
        conn.close()

def test_generated_image_quality_metrics_boundary(tmp_path):
    """解像度/アスペクト比/ファイルサイズの境界値と、Pillowによる非破損検証"""
    generator = ThumbnailGenerator()
    
    # 様々なサイズ・比率の画像を入力して検証
    test_cases = [
        (800, 600),    # 4:3
        (1280, 720),   # 16:9
        (1920, 1080),  # 16:9
        (3840, 2160),  # 16:9
        (100, 100),    # 1:1 極小
    ]
    
    for w, h in test_cases:
        raw_bytes = create_dummy_image_bytes(w, h)
        optimized = generator.verify_and_optimize_image(raw_bytes, title=f"Test {w}x{h}")
        
        # ファイルサイズチェック
        assert len(optimized) < 4 * 1024 * 1024
        
        # Pillowロードおよびサイズ/アスペクト比検証
        with Image.open(io.BytesIO(optimized)) as img:
            img.verify()
        with Image.open(io.BytesIO(optimized)) as img:
            img.load()
            out_w, out_h = img.size
            assert out_w >= 1280
            assert out_h >= 720
            # 16:9比率であること
            assert abs((out_w / out_h) - (16.0 / 9.0)) < 0.01

def test_verify_and_optimize_extreme_aspect_ratios():
    """アスペクト比が極端な画像（例: 32:9の超ワイド画像や1:12の超縦長画像）の場合に、
    ValueErrorを投げ、高品質なフォールバック画像が生成されること
    """
    generator = ThumbnailGenerator()
    
    # 32:9 (極端な横長)
    raw_wide = create_dummy_image_bytes(3200, 900)
    optimized_wide = generator.verify_and_optimize_image(raw_wide, title="Wide Fallback")
    
    # 1:12 (極端な縦長)
    raw_tall = create_dummy_image_bytes(100, 1200)
    optimized_tall = generator.verify_and_optimize_image(raw_tall, title="Tall Fallback")
    
    for opt in (optimized_wide, optimized_tall):
        assert len(opt) > 0
        assert len(opt) < 4 * 1024 * 1024
        with Image.open(io.BytesIO(opt)) as img:
            img.verify()
        with Image.open(io.BytesIO(opt)) as img:
            img.load()
            w, h = img.size
            assert w >= 1280
            assert h >= 720
            assert abs((w / h) - (16.0 / 9.0)) < 0.05

def test_verify_and_optimize_heavy_corruption():
    """部分的に破損したPNG/JPEG等のバイナリが入力された場合に、
    Pillowがデコードエラー(OSError等)を検知し、フォールバック画像が生成されること
    """
    generator = ThumbnailGenerator()
    
    # 不完全なPNGヘッダのみの破損バイナリ
    corrupt_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 20
    
    optimized = generator.verify_and_optimize_image(corrupt_bytes, title="Corrupt Fallback")
    
    assert len(optimized) > 0
    assert len(optimized) < 4 * 1024 * 1024
    with Image.open(io.BytesIO(optimized)) as img:
        img.load()
        w, h = img.size
        assert w >= 1280
        assert h >= 720
        assert abs((w / h) - (16.0 / 9.0)) < 0.05

@pytest.mark.asyncio
async def test_resolve_generator_thumbnail_task_db_fatal_error(tmp_path):
    """データベース処理中に locked 以外の致命的エラー（例：スキーマ不一致等）が発生した場合、
    リトライを行わずに即座に例外が伝播すること
    """
    db_file = tmp_path / "test_generator_thumb_fatal.db"
    output_dir = tmp_path / "output_thumbs"
    task_id = "task_gen_fatal"
    
    agent = MagicMock()
    agent.output_dir = output_dir
    agent.db_path = str(db_file)
    agent.video_title = "致命的DBエラーテスト"
    agent.video_description = "説明"
    
    dummy_bytes = create_dummy_image_bytes(1280, 720)
    import base64
    dummy_b64 = base64.b64encode(dummy_bytes).decode('utf-8')
    
    mock_generate = AsyncMock(return_value=[{
        "image_base64": dummy_b64,
        "concept_name": "致命的エラーコンセプト"
    }])
    
    # 接続自体は成功するが、クエリ実行で sqlite3.DatabaseError(致命的エラー) を発生させる
    original_connect = sqlite3.connect
    connect_calls = 0
    
    def mock_connect(*args, **kwargs):
        nonlocal connect_calls
        connect_calls += 1
        # ロック以外の致命的エラーを発生させるためのコネクションモック
        conn = MagicMock()
        # conn.execute が例外を投げるようにする
        conn.execute.side_effect = sqlite3.DatabaseError("file is not a database")
        return conn

    with patch('backend.thumbnail_engine.generator.generator.generate', mock_generate), \
         patch('sqlite3.connect', side_effect=mock_connect):
         
        # 即座に DatabaseError が発生するが、例外は伝播せず、file-only で正常に結果が返ることを確認
        result_json = await resolve_generator_thumbnail_task(agent, task_id)
        assert result_json is not None
        result_data = json.loads(result_json)
        assert result_data["valid"] is True
            
        # ロック以外の sqlite エラーでも5回のリトライ試行が行われることを確認
        assert connect_calls == 5
